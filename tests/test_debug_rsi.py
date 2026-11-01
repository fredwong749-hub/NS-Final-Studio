"""DEBUG-RSI 11-02（总调度 fredw-2b 派）：运行期故障修复的回归测试。

K-OPS-E01  /history 轮询短断不整单作废（作业已交上去，宽限期内继续等）
K-OPS-E02  /view 下载 IncompleteRead 归为连接问题并重试，不重渲染
K-OPS-E03  超时取消只取消自己这一单（定向 interrupt + 出队），不全局 /interrupt
"""
import http.client
import json
import time
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
    assert "max_workers=max(8, self.score_backlog_max + 2 * (len(self.lanes) or 1))" in src
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


# ---- r2：出图道占用率实测工具 ----
def test_lane_util_union_and_agents():
    sys.path.insert(0, str(ROOT / "tools" / "debug"))
    import lane_util as LU
    t1 = 10_000.0
    def ent(s, e, agent):
        return {"status": {"messages": [["execution_start", {"timestamp": s * 1000}], ["execution_success", {"timestamp": e * 1000}]]},
                "prompt": [0, "x", {}, {"ns_tag": {"agent": agent}}]}
    hist = {"a": ent(t1 - 600, t1 - 300, "PRODUCER"), "b": ent(t1 - 400, t1 - 200, "IMGFIX"), "c": ent(t1 - 9000, t1 - 8000, "OLD")}
    res = LU.measure(minutes=10, lanes={"gpu33:0": 8188}, fetch=lambda h, ps: {8188: hist}, now=t1)
    r = res["lanes"]["gpu33:0"]
    assert r["jobs"] == 2 and abs(r["util"] - 400 / 600) < 0.02
    assert set(r["by_agent"]) == {"PRODUCER", "IMGFIX"}


def test_lane_util_parse():
    sys.path.insert(0, str(ROOT / "tools" / "debug"))
    import lane_util as LU
    out = LU.parse('##PORT 8188\n{"x": {}}\n##PORT 8189\n\n##PORT 8191\nnot json\n')
    assert out[8188] == {"x": {}} and out[8189] == {} and out[8191] is None


# ---- K-OPS-E06：探测 / 分析工具里每个远程调用都带 timeout ----
def test_e06_remote_calls_have_timeout():
    import re
    bad = []
    for f in sorted((ROOT / "tools" / "debug").glob("*.py")):
        src = f.read_text(encoding="utf-8")
        for m in re.finditer(r"rssh\.run\(\s*[^,]+,\s*(f?\"[^\"]*\"|f?'[^']*')", src):
            if "timeout " not in m.group(1):
                bad.append(f"{f.name}: {m.group(1)[:60]}")
        assert "subprocess" not in src or "timeout=" in src, f.name
    assert not bad, bad


# ---- K-OPS-E07：gpu36 ComfyUI 日志轮转规格（远端逐字比对用 tools/debug/check_logrotate.py） ----
def test_e07_logrotate_spec():
    sys.path.insert(0, str(ROOT / "tools" / "debug"))
    import check_logrotate as CL
    assert CL.spec_ok(CL.SPEC.read_text(encoding="utf-8")) == []


# ---- L-100：laptop:0 停用后不进道表、看板显示“看图卡” ----
def test_l100_laptop_lane_disabled_and_shown_as_vqa_card(monkeypatch):
    sys.path.insert(0, str(ROOT / "services/api"))
    from ns_render import endpoints as EP
    assert "laptop:0" not in EP._extra_lanes()
    from ns_api import infra_status as IS
    monkeypatch.setattr(IS, "_probe", lambda url: (True, 3))
    IS._cache["local"] = None
    out = IS._local(10**10)
    assert [x["id"] for x in out] == ["look"] and "看图卡" in out[0]["label"]


# ---- K-OPS-E08：暂停口径（判定 = policy.pause_decision；运维暂停到点恢复 / 显式暂停不恢复只报警） ----
def _pp(tmp_path):
    PR = _producer()
    p = PR.Paths(root=tmp_path)
    p.pd.mkdir(parents=True, exist_ok=True)
    return PR, p


def test_e08_ops_pause_auto_resumes(tmp_path):
    PR, p = _pp(tmp_path)
    c = PR.set_paused(p, True, by="restart_producer", expires_s=999)
    assert c["reason_kind"] == "restart" and c["expires_at"]
    exp = time.mktime(time.strptime(c["expires_at"], "%Y-%m-%dT%H:%M:%S"))
    assert exp - time.time() <= 181                                         # 运维暂停上限 180 s
    assert PR.pause_tick(p, t=time.time() + 60)["action"] is None
    r = PR.pause_tick(p, t=time.time() + 200)
    assert r["action"] == "resume" and not json.loads(p.ctrl.read_text(encoding="utf-8"))["paused"]


def test_e08_explicit_pause_never_auto_resumes_but_alerts_once(tmp_path):
    PR, p = _pp(tmp_path)
    c = PR.set_paused(p, True, by="总调度 fredw-2b", note="身份脸 P0")
    assert c["reason_kind"] == "master" and c["expires_at"]
    al = tmp_path / "alerts.jsonl"
    t = time.time() + 400
    assert PR.pause_tick(p, t=t, alerts=al)["action"] == "alert"
    assert PR.pause_tick(p, t=t + 60, alerts=al)["action"] == "alert"      # 10 分钟内不重复报
    assert json.loads(p.ctrl.read_text(encoding="utf-8"))["paused"] is True
    lines = al.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["id"] == "A-PAUSE-OVERDUE"


def test_e08_kind_inference():
    PR = _producer()
    assert PR.infer_pause_kind("NETFIX 切香港线路") == "line_switch"
    assert PR.infer_pause_kind("RESTART_DRAIN") == "restart" and PR.infer_pause_kind("system_version deploy") == "deploy"
    assert PR.infer_pause_kind("owner") == "owner" and PR.infer_pause_kind("总调度") == "master"


# ---- K-OPS-W15：RUN_ID 读配置；import_staged 成功后写导入事件 ----
def test_w15_run_id_from_config():
    PR = _producer()
    want = json.loads((ROOT / "config/pipeline/run.json").read_text(encoding="utf-8"))["run_id"]
    assert PR.RUN_ID == want == PR._run_id_from_config()


def test_w15_imported_episodes(tmp_path):
    PR = _producer()
    p = PR.Paths(root=tmp_path)
    assert PR.imported_episodes(p, "x/漆皮_hwd_ep04_v3.md", {}) == [4]
    assert PR.imported_episodes(p, "x/a.md", {"episodes": [2, "ep03", {"n": 5}]}) == [2, 3, 5]
    (tmp_path / "s.md").write_text("# 第 7 集 标题\n正文\n## 第8集\n", encoding="utf-8")
    assert PR.imported_episodes(p, "s.md", None) == [7, 8]


def test_w15_import_staged_appends_event_before_success():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    body = src.split("def import_staged(", 1)[1].split("\ndef ", 1)[0]
    i = body.index("IE.append_import(")
    assert i < body.rindex("return 0 if st == 200 else 1") and "if st == 200:" in body[:i]


# ---- DISTILL ①：dryrun 以“视频 passed”为成功，走不完返回非 0、报卡在哪 ----
def test_dryrun_success_requires_video_passed_and_nonzero_on_fail():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    body = src.split("def dryrun(", 1)[1].split("\ndef ", 1)[0]
    assert "max_ticks" in body and "return 2" in body and '"video", {}).get("status") == "passed"' in body
    assert "stuck" in body
    fake = src.split("class FakeFrameExec", 1)[1].split("\nclass ", 1)[0]
    assert '"id": "Q9", "status": "pass"' in fake       # 看图闸门 enforce 时演练也要能设为当前


# ---- K-OPS-E10：看图回来 pass，契约之前只因“Q9 未跑”判的 ok=False 要翻回 True；别的项不过不翻 ----
def test_e10_vqa_pass_flips_ok_when_only_q9_blocked(monkeypatch):
    sys.path.insert(0, str(ROOT / "services/agent"))
    from ns_agent.vqa import contract as VC
    monkeypatch.setattr(VC, "q9", lambda v: ("pass", "看图通过", {"defects": [], "unsure": []}))
    monkeypatch.setattr(VC, "q1_yaw_relax", lambda pf, v: None)
    pf = {"ok": False, "blocking": ["Q9"], "items": [{"id": "Q1", "status": "pass"}, {"id": "Q9", "status": "untested"}],
          "reasons": ["Q9 没有本地看图复核结果（服务排队 / 未跑）"]}
    VC.apply(pf, {"x": 1})
    assert pf["ok"] is True and pf["blocking"] == [] and not any(str(r).startswith("Q9") for r in pf["reasons"])
    pf2 = {"ok": False, "blocking": ["Q1", "Q9"], "items": [{"id": "Q1", "status": "fail"}, {"id": "Q9", "status": "untested"}],
           "reasons": ["Q1 身份 0.61 < 0.7"]}
    VC.apply(pf2, {"x": 1})
    assert pf2["ok"] is False and pf2["blocking"] == ["Q1"]


# ---- K-OPS-E09：驳回阶梯用完不再“等总调度定” ----
def test_e09_no_wait_for_master_exit_and_ladder_helpers(tmp_path):
    PR = _producer()
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert "次都没换上，等总调度定" not in src                 # 旧出口（waiting_for）已删
    assert PR.redo_ladder_policy()["heavy_plan"]
    led = {"redo_history": [{"blocking": ["Q1", "Q9"]}, {"blocking": ["Q1"]}], "history": [{"blocking": ["Q3"]}]}
    assert PR.fail_stats(led) == {"Q1": 2, "Q9": 1, "Q3": 1}
    p = PR.Paths(root=tmp_path)
    PR.sentinel_ticket(p, "first:ep01-S1", "why", {"Q1": 2}, led)
    rec = json.loads((tmp_path / "data/sentinel/tickets.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert rec["kind"] == "redo_ladder_exhausted" and rec["rule"] == "K-OPS-E09"


def test_e09_escalate_routes(monkeypatch, tmp_path):
    PR = _producer()
    import threading
    pr = object.__new__(PR.Producer)
    pr.p = PR.Paths(root=tmp_path); pr.p.pd.mkdir(parents=True, exist_ok=True)
    pr.mu = threading.RLock(); logs = []
    pr.logf = lambda ev, **kw: logs.append(ev)
    reg = {"episodes": [{"shots": [{"shot": "ep01-S1", "objects": {"first": {"id": "first:ep01-S1", "shot": "ep01-S1", "escalate": True},
                                                                      "last": {"id": "last:ep01-S1"}}}]}]}
    monkeypatch.setattr(PR, "asset_hold_objects", lambda d: set())
    monkeypatch.setattr(PR, "redo_inputs_changed", lambda *a: None)
    assert pr.escalate_exhausted(reg)["heavy"] == 1                       # 输入没变 → 追加重档
    assert pr.ledger()["first:ep01-S1"]["ladder_plan"]
    assert pr.escalate_exhausted(reg)["best_effort"] == 1                 # 重档也用完 → 尽力 + 工单
    assert pr.ledger()["first:ep01-S1"]["final"] == "best_effort"
    monkeypatch.setattr(PR, "redo_inputs_changed", lambda *a: "参考图更新了：x.png")
    assert pr.escalate_exhausted(reg)["reset"] == 1                       # 输入变了 → 重置不计次
    assert pr.ledger()["first:ep01-S1"]["redo_tries"] == 0


# ---- r3 ③：import-staged --run（非主剧写 data/import/runs/<run>/，登记 run，事件带 run_id） ----
def test_import_staged_run_writes_per_run_file(tmp_path, monkeypatch):
    PR = _producer()
    import subprocess as SP
    root = tmp_path
    (root / "config/pipeline").mkdir(parents=True)
    (root / "config/pipeline/runs.json").write_text(json.dumps({"primary": "series10_v1", "runs": {"series10_v1": {}}}), encoding="utf-8")
    (root / "stage").mkdir()
    (root / "stage/x_hwd_ep01_v1.md").write_text("# 第 1 集\n", encoding="utf-8")
    p = PR.Paths(root=root); p.pd.mkdir(parents=True, exist_ok=True)
    calls = {}

    def fake_run(cmd, **kw):
        out = Path(cmd[cmd.index("-o") + 1]); out.parent.mkdir(parents=True, exist_ok=True); out.write_text("{}", encoding="utf-8")
        calls["cmd"] = cmd
        return SP.CompletedProcess(cmd, 0, b"", b"")
    monkeypatch.setattr(SP, "run", fake_run)
    RN = PR._runs()
    monkeypatch.setattr(RN, "ROOT", root, raising=False)
    import import_events as IE
    ev = []
    monkeypatch.setattr(IE, "append_import", lambda eps, **kw: ev.append((eps, kw)))
    assert PR.import_staged_run(p, "stage/x_hwd_ep01_v1.md", "sha", "n", "总调度", "series10_s2") == 0
    assert (root / "data/import/runs/series10_s2/script_v2.json").exists() and "--no-timeline" in calls["cmd"]
    assert "series10_s2" in json.loads((root / "config/pipeline/runs.json").read_text(encoding="utf-8"))["runs"]
    assert ev and ev[0][0] == [1] and ev[0][1]["run_id"] == "series10_s2"


# ---- r3 ⑤：含尽力镜的集不再整集写 force_eps（尽力镜不进合成） ----
def test_no_force_eps_for_best_effort_episode(tmp_path):
    PR = _producer()
    p = PR.Paths(root=tmp_path); p.vid.mkdir(parents=True, exist_ok=True)
    vb = PR.VideoBridge(p)
    logs = []
    S = lambda f, l: {"objects": {"first": {"status": f}, "last": {"status": l}}}
    reg = {"episodes": [{"ep": 3, "shots": [S("passed", "passed"), S("best_effort", "best_effort")]}]}
    vb.tick(reg, {"auto_force_eps": True, "workers": {"video": "VIDEO10"}}, True, lambda ev, **kw: logs.append(ev))
    assert not (p.vid / "night_control.json").exists() or 3 not in json.loads((p.vid / "night_control.json").read_text())["force_eps"]
    assert logs == ["video_release_skipped"]


# ---- r3 ⑥ K-OPS-E11：尽力版在规则 / 资产版本变化时自动重置（不计次） ----
def test_e11_best_effort_auto_reset(monkeypatch, tmp_path):
    PR = _producer()
    import threading
    pr = object.__new__(PR.Producer)
    pr.p = PR.Paths(root=tmp_path); pr.p.pd.mkdir(parents=True, exist_ok=True)
    pr.mu = threading.RLock(); logs = []
    pr.logf = lambda ev, **kw: logs.append(ev)
    monkeypatch.setattr(PR, "asset_hold_objects", lambda d: set())
    sig = {"rule": "r1", "inputs": "i1", "refs_mtime": 10.0, "prompt_sha": "p1"}
    monkeypatch.setattr(PR, "be_rule_sig", lambda root: sig["rule"])
    monkeypatch.setattr(PR, "shot_inputs_sig", lambda paths, sid: {k: v for k, v in sig.items() if k != "rule"})
    reg = {"episodes": [{"shots": [{"shot": "ep01-S1", "objects": {"first": {"id": "first:ep01-S1", "status": "best_effort"},
                                                                      "last": {"id": "last:ep01-S1", "status": "pending"}}}]}]}
    pr.led_update("first:ep01-S1", tries=3, final="best_effort")
    assert pr.auto_reset_best_effort(reg, every_s=0)["basis"] == 1         # 第一次只记依据
    assert pr.auto_reset_best_effort(reg, every_s=0)["reset"] == 0         # 没变不动
    sig["refs_mtime"] = 99.0                                                # 参考图更新
    assert pr.auto_reset_best_effort(reg, every_s=0)["reset"] == 1
    L = pr.ledger()["first:ep01-S1"]
    assert L["tries"] == 0 and L["final"] is None and "best_effort_reset" in logs


# ---- r3 ④ K-OPS-E13：登记表一致性（尾帧不比首帧旧；首帧没过尾帧不算过） ----
def test_e13_last_voided_when_first_changed_or_not_passed():
    PR = _producer()
    td = {"active": {"image": 5, "last": 1}, "takes": [{"stage": "image", "n": 5, "created_at": "2026-11-02T01:48:52"},
                                                     {"stage": "last", "n": 1, "created_at": "2026-11-01T04:34:01"}]}
    lo = {"id": "last:ep04-S1", "status": "passed"}
    r = PR.last_consistent(td, {"status": "passed"}, lo)
    assert r["status"] == "ready" and r["voided"]                           # 首帧换过 → 尾帧重出
    r2 = PR.last_consistent({"active": {}, "takes": []}, {"status": "ready"}, lo)
    assert r2["status"] == "pending"                                        # 首帧没过 → 尾帧等
    td3 = {"active": {"image": 1, "last": 2}, "takes": [{"stage": "image", "n": 1, "created_at": "2026-11-01T01:00:00"},
                                                      {"stage": "last", "n": 2, "created_at": "2026-11-01T02:00:00"}]}
    assert PR.last_consistent(td3, {"status": "passed"}, lo)["status"] == "passed"
    reg = {"episodes": [{"shots": [{"shot": "ep04-S1", "objects": {"first": {"status": "ready"}, "last": {"status": "passed"},
                                                                       "video": {"status": "pending"}}}]}]}
    assert PR.registry_consistency(reg)[0]["kind"] == "last"


# ---- K-OPS-E14：冻结锁闸门不吞退出码 ----
def test_e14_lock_guard():
    sys.path.insert(0, str(ROOT / "tools" / "qa"))
    import subprocess as SP
    import lock_guard as LG
    locked = lambda: SP.CompletedProcess([], 3, '{"active": true}', "")
    free = lambda: SP.CompletedProcess([], 0, '{"active": false}', "")
    assert LG.lock_state(free)[0] == 0
    LG.require_unlocked(free)
    try:
        LG.require_unlocked(locked)
        raise AssertionError("应该拦住")
    except LG.LockedError:
        pass


def test_e13_data_parity_regcons(tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "qa"))
    import data_parity as DP
    f = tmp_path / "consistency.json"
    f.write_text(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "problems": [
        {"shot": "ep04-S1", "kind": "last", "why": "尾帧 passed 但首帧不是 passed"},
        {"shot": "ep04-S2", "kind": "video", "why": "视频 passed 但首 / 尾帧不是 passed"}]}), encoding="utf-8")
    fails, warns = [], []
    DP.regcons_check(f, fails, warns)
    assert len(fails) == 1 and "ep04-S1" in fails[0] and len(warns) == 1
