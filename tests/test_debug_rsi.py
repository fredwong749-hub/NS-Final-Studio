"""DEBUG-RSI 11-02（总调度 fredw-2b 派）：运行期故障修复的回归测试。

K-OPS-E01  /history 轮询短断不整单作废（作业已交上去，宽限期内继续等）
K-OPS-E02  /view 下载 IncompleteRead 归为连接问题并重试，不重渲染
K-OPS-E03  超时取消只取消自己这一单（定向 interrupt + 出队），不全局 /interrupt
"""
import http.client
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services/render_router"))

from ns_render import comfy_client as CC  # noqa: E402


class FakeClient(CC.ComfyClient):
    def __init__(self, script):
        super().__init__("http://127.0.0.1:1")
        self.script = list(script)
        self.calls = []

    def _request(self, path, data=None, headers=None, timeout=None, method=None):
        self.calls.append((path, data))
        act = self.script.pop(0) if self.script else b"{}"
        if isinstance(act, BaseException):
            raise act
        return act


@pytest.fixture(autouse=True)
def fast(monkeypatch):
    monkeypatch.setattr(CC.time, "sleep", lambda s: None)


def done_entry(pid):
    return json.dumps({pid: {"status": {"status_str": "success", "completed": True}, "outputs": {}}}).encode()


def test_r01_poll_timeout_keeps_waiting():
    c = FakeClient([CC.ComfyUnavailable("/history/x: timed out"), CC.ComfyUnavailable("/history/x: timed out"),
                    b"{}", done_entry("x")])
    e = c.wait("x", timeout_s=60, poll_s=0)
    assert e["status"]["completed"]
    assert not any(p == "/interrupt" for p, _ in c.calls)


def test_r01_poll_gives_up_after_grace(monkeypatch):
    t = [0.0]
    monkeypatch.setattr(CC.time, "monotonic", lambda: t[0])

    def sleep(s):
        t[0] += s
    monkeypatch.setattr(CC.time, "sleep", sleep)
    monkeypatch.setattr(CC, "POLL_GRACE_S", 30)
    c = FakeClient([CC.ComfyUnavailable("down")] * 100)
    with pytest.raises(CC.ComfyUnavailable):
        c.wait("x", timeout_s=10_000, poll_s=1)


def test_r02_incomplete_read_is_unavailable_and_retried(tmp_path):
    class C(FakeClient):
        pass
    c = C([])
    # _request 真实实现：urlopen 里抛 IncompleteRead → ComfyUnavailable
    real = CC.ComfyClient._request

    def boom(*a, **k):
        raise http.client.IncompleteRead(b"x" * 10, 100)
    import urllib.request
    orig = urllib.request.urlopen
    urllib.request.urlopen = boom
    try:
        with pytest.raises(CC.ComfyUnavailable):
            real(c, "/view?x")
    finally:
        urllib.request.urlopen = orig
    # download：前两次断，第三次成功
    c2 = FakeClient([CC.ComfyUnavailable("IncompleteRead"), CC.ComfyUnavailable("IncompleteRead"), b"PNGDATA"])
    c2.instance = lambda: "i"
    out = c2.download({"filename": "a.png", "subfolder": "", "type": "temp"}, tmp_path / "a.png")
    assert out.read_bytes() == b"PNGDATA"
    assert sum(1 for p, _ in c2.calls if p.startswith("/view")) == 3


def test_r03_timeout_cancels_only_own_prompt(monkeypatch):
    t = [0.0]
    monkeypatch.setattr(CC.time, "monotonic", lambda: t[0])

    def sleep(s):
        t[0] += s
    monkeypatch.setattr(CC.time, "sleep", sleep)
    c = FakeClient([b"{}"] * 50)
    with pytest.raises(CC.ComfyError):
        c.wait("mine", timeout_s=10, poll_s=3)
    ints = [d for p, d in c.calls if p == "/interrupt"]
    assert ints and all(json.loads(d) == {"prompt_id": "mine"} for d in ints)
    assert any(p == "/queue" and json.loads(d) == {"delete": ["mine"]} for p, d in c.calls)


def test_r03_no_bare_interrupt_in_wait_source():
    src = (ROOT / "services/render_router/ns_render/comfy_client.py").read_text(encoding="utf-8")
    body = src.split("def wait(", 1)[1].split("\n    def ", 1)[0]
    assert "self.interrupt()" not in body


# ---- K-OPS-E04：资产暂缓清单（data/autopilot/*_hold.json，IMGFIX r5 lookA_hold）producer 派单必须跳过 ----
def _producer():
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    import producer as PR  # noqa: E402
    return PR


def test_r04_asset_hold_objects(tmp_path):
    PR = _producer()
    d = tmp_path / "autopilot"
    d.mkdir()
    (d / "lookA_hold.json").write_text(json.dumps({"active": True, "shots": [
        {"shot": "ep01-S1", "objects": ["first:ep01-S1", "last:ep01-S1"]}]}), encoding="utf-8")
    (d / "old_hold.json").write_text(json.dumps({"active": False, "shots": [{"objects": ["first:ep09-S9"]}]}), encoding="utf-8")
    (d / "bad_hold.json").write_text("{not json", encoding="utf-8")
    assert PR.asset_hold_objects(tmp_path) == {"first:ep01-S1", "last:ep01-S1"}
    assert PR.asset_hold_objects(tmp_path / "missing") == set()


def test_r04_dispatch_consults_hold_before_rescore_and_dispatch():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    body = src.split("def dispatch_frames(", 1)[1].split("\n    def ", 1)[0]
    i_hold = body.index("asset_hold_objects(")
    i_skip = body.index("in held")
    assert i_hold < i_skip < body.index("rescore_take") and i_skip < body.index("self.leases.acquire(")


# ---- K-OPS-E05：打分等待不许占住派单线程；打分积压到上限停派 ----
def test_e05_pool_larger_than_lanes_and_backlog_blocks_dispatch():
    PR = _producer()
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert "max_workers=max(8, 3 * (len(self.lanes) or 1))" in src
    import threading

    class P:
        pass
    p = object.__new__(PR.Producer)
    p.mu = threading.RLock()
    p.scoring = {"first:ep01-S1", "first:ep01-S2"}
    p.score_backlog_max = 2
    logs = []
    p.logf = lambda ev, **kw: logs.append(ev)
    # 有空道，但积压已满 → 不碰候选（reg 是空壳；若往下走会 KeyError）
    p.dispatch_frames({}, {"gpu33:0": {"free": True}}, {})
    assert logs == ["score_backlog"]


def test_e05_scoring_cleared_in_finally():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    body = src.split("def _run_one(", 1)[1].split("\n    def ", 1)[0]
    assert "self.scoring.add(oid)" in body
    fin = body.split("finally:", 1)[1]
    assert "self.scoring.discard(oid)" in fin


def test_e05_backlog_scales_with_vlm_instances(monkeypatch):
    PR = _producer()
    monkeypatch.setenv("NS_VQA_INSTANCES", "3")
    assert PR.vlm_instances() == 3
    monkeypatch.setenv("NS_VQA_INSTANCES", "junk")
    assert PR.vlm_instances() == 1
