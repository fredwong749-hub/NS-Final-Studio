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
def test_e05_pool_larger_than_lanes_and_backlog_blocks_dispatch(tmp_path, monkeypatch):
    PR = _producer()
    monkeypatch.setattr(PR, "decision_file_problems", lambda *a, **k: [])       # 决策文件闸门另有测试，这里只测积压闸
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert "max_workers=max(8, max(self.score_backlog_max, 96)" in src
    import threading

    class P:
        pass
    p = object.__new__(PR.Producer)
    p.mu = threading.RLock()
    p.scoring = {"first:ep01-S1", "first:ep01-S2"}
    p.score_backlog_max = 2
    p._backlog_env = 2; p.score_done = []; p.lanes = {"gpu33:0": "u"}; p.depth = 2
    p.p = PR.Paths(root=tmp_path)          # 临时目录：主剧、没有更高优先级的剧；S3 工单写到临时目录
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
    monkeypatch.setattr(PR, "asset_hold_objects", lambda d, *a: set())
    monkeypatch.setattr(PR, "redo_inputs_changed_v2", lambda *a: None)
    monkeypatch.setattr(PR, "job_sig", lambda paths, sid: "S1")
    assert pr.escalate_exhausted(reg)["heavy"] == 1                       # 输入没变 → 追加重档
    assert pr.ledger()["first:ep01-S1"]["ladder_plan"]
    assert pr.escalate_exhausted(reg)["best_effort"] == 1                 # 重档也用完 → 尽力 + 工单
    assert pr.ledger()["first:ep01-S1"]["final"] == "best_effort"
    monkeypatch.setattr(PR, "redo_inputs_changed_v2", lambda *a: "作业输入变了")
    assert pr.escalate_exhausted(reg)["reset"] == 1                       # 输入变了 → 重置不计次
    assert pr.ledger()["first:ep01-S1"]["redo_tries"] == 0


# ---- r3 ③：import-staged --run（非主剧写 data/import/runs/<run>/，登记 run，事件带 run_id） ----
def test_import_staged_run_writes_per_run_file(tmp_path, monkeypatch):
    PR = _producer()
    import subprocess as SP
    root = tmp_path
    (root / "config/pipeline").mkdir(parents=True)
    (root / "config/pipeline/runs.json").write_text(json.dumps({"primary": "series10_v1", "legacy_unprefixed_run": "series10_v1", "runs": {"series10_v1": {}}}), encoding="utf-8")
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
    monkeypatch.setattr(PR, "asset_hold_objects", lambda d, *a: set())
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


# ---- r3 ⑦ K-OPS-E15：多剧并行（一剧一进程；主剧路径不变；非主剧分文件 / 分渲染目录；按优先级派单） ----
def test_e15_multi_run_paths_and_priority(tmp_path):
    PR = _producer()
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"primary": PR.RUN_ID, "legacy_unprefixed_run": PR.RUN_ID, "runs": {   # K-OPS-F24：旧路径只给 legacy 剧
        PR.RUN_ID: {"priority": 0, "status": "producing"}, "s2": {"priority": 10, "status": "producing"}}}), encoding="utf-8")
    a, b = PR.Paths(root=tmp_path), PR.Paths(root=tmp_path, run_id="s2")
    assert a.pd == tmp_path / "data/producer" and a.renders == tmp_path / "data/renders"          # 主剧旧路径兼容
    assert b.pd == tmp_path / "data/producer/runs/s2" and b.renders == tmp_path / "data/renders/s2"
    assert a.ledger != b.ledger and a.registry != b.registry                                      # 两部剧同镜号互不覆盖
    env = PR.run_env("s2", tmp_path)
    assert env["NS_RENDERS_DIR"].endswith(str(Path("data/renders/s2"))) and PR.run_env(PR.RUN_ID, tmp_path) == {}
    a.pd.mkdir(parents=True)
    a.registry.write_text(json.dumps({"episodes": [{"shots": [{"objects": {"first": {"status": "ready"}}}]}]}), encoding="utf-8")
    assert PR.higher_priority_busy(b) == {PR.RUN_ID: 1}                                           # 主剧有活 → 第二季让
    assert PR.higher_priority_busy(a) == {}                                                       # 主剧不让任何人
    a.registry.write_text(json.dumps({"episodes": []}), encoding="utf-8")
    assert PR.higher_priority_busy(b) == {}                                                       # 主剧没活 → 第二季用空档


def test_e15_pipeline_renders_env():
    src = (ROOT / "services/render_router/ns_render/pipeline.py").read_text(encoding="utf-8")
    assert 'os.environ.get("NS_RENDERS_DIR")' in src and 'os.environ.get("NS_SCRIPT_JSON")' in src


# ---- K-OPS-E17：预取深度（每道 1 跑 + 1 排队）+ 积压上限按打分吞吐定 + 压线开 S3 工单 ----
def test_e17_prefetch_and_dynamic_backlog(monkeypatch, tmp_path):
    PR = _producer()
    monkeypatch.setenv("NS_PRODUCER_PREFETCH", "2")
    assert PR.prefetch_depth() == 2
    t = 10_000.0
    assert PR.dynamic_backlog([], t, 3, 2) == 6                                   # 下限 = 道数 × 深度
    assert PR.dynamic_backlog([t - i * 20 for i in range(45)], t, 3, 2) == 45      # 15 分钟 45 张 = 3/分 × 15
    import threading
    pr = object.__new__(PR.Producer)
    pr.p = PR.Paths(root=tmp_path); pr.p.pd.mkdir(parents=True, exist_ok=True)
    pr.mu = threading.RLock(); pr.depth = 2; pr.lanes = {"gpu33:0": "u"}; pr.lane_cool = {}
    pr.lane_busy = {"gpu33:0": ["first:ep01-S1"]}
    pr.train_locks_fn = lambda srv: set()
    pr.lane_probe = lambda url: {"ok": True, "n": 1, "agents": ["PRODUCER"]}
    monkeypatch.setattr(PR, "lane_held", lambda ln: False)
    assert pr.probe_lanes({})["gpu33:0"]["free"] is True                          # 1 在跑 → 还能预取 1 单
    pr.lane_busy = {"gpu33:0": ["a", "b"]}
    pr.lane_probe = lambda url: {"ok": True, "n": 2, "agents": ["PRODUCER", "PRODUCER"]}
    assert pr.probe_lanes({})["gpu33:0"]["free"] is False                         # 深度满
    pr.lane_busy = {}
    pr.lane_probe = lambda url: {"ok": True, "n": 1, "agents": ["IMGLAB"]}
    assert pr.probe_lanes({})["gpu33:0"]["free"] is False                         # 别人的非让道任务 → 不挤


def test_e17_backlog_gate_opens_s3_ticket(tmp_path):
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    body = src.split("def dispatch_frames(", 1)[1].split(chr(10) + "    def ", 1)[0]
    assert 'sentinel_ticket(self.p, "score_backlog"' in body and "dynamic_backlog(" in body


# ---- K-OPS-E18：producer 进程内时间统一 Asia/Tokyo（经 ssh 调的 CLI 也一样） ----
def test_e18_producer_forces_tokyo_tz():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    head = src.split("def ", 1)[0]
    assert 'os.environ["TZ"] = "Asia/Tokyo"' in head and "time.tzset()" in head


# ---- K-OPS-E18 数据层：控制文件时间戳必须带偏移 ----
def test_e18_tz_check_flags_naive_timestamps(tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "debug"))
    import tz_check as TC
    f = tmp_path / "c.json"
    f.write_text(json.dumps({"paused_at": "2026-11-01T13:52:00", "ok": "2026-11-02T03:52:00+09:00", "z": "2026-11-02T00:00:00Z",
                             "n": [{"at": "2026-11-02T04:00"}], "text": "not a ts"}), encoding="utf-8")
    bad = TC.scan(json.loads(f.read_text(encoding="utf-8")))
    assert sorted(p for p, _ in bad) == ["$.n[0].at", "$.paused_at"]
    assert TC.main(["--strict", str(f)]) == 1 and TC.main([str(f)]) == 0


# ---- K-OPS-E19：按镜暂停 + 到期失效；全道暂停超 30 分钟开工单 ----
def test_e19_pause_shots_and_expiry(tmp_path):
    PR = _producer()
    p = PR.Paths(root=tmp_path); p.pd.mkdir(parents=True, exist_ok=True)
    PR.pause_shots(p, ["ep01-S1"], "总调度", "试", minutes=30)
    assert "first:ep01-S1" in PR.asset_hold_objects(p.data)
    d = json.loads((p.data / "autopilot/pause_hold.json").read_text(encoding="utf-8"))
    d["shots"][0]["expires_at"] = "2000-01-01T00:00:00"
    (p.data / "autopilot/pause_hold.json").write_text(json.dumps(d), encoding="utf-8")
    assert "first:ep01-S1" not in PR.asset_hold_objects(p.data)              # 到期自动失效


def test_e19_global_pause_over_30min_opens_ticket(tmp_path):
    PR = _producer()
    p = PR.Paths(root=tmp_path); p.pd.mkdir(parents=True, exist_ok=True)
    PR.set_paused(p, True, by="总调度", note="P0")
    PR.pause_tick(p, t=time.time() + 1900, alerts=tmp_path / "a.jsonl")
    PR.pause_tick(p, t=time.time() + 2000, alerts=tmp_path / "a.jsonl")
    lines = (tmp_path / "data/sentinel/tickets.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1 and json.loads(lines[0])["obj"] == "global_pause"


# ---- K-OPS-E20：night 的挂道（control hold_lanes）在任何模式下都生效，且挂道变化会触发重算 ----
def test_e20_night_hold_lanes_respected():
    src = (ROOT / "tools/series10_video/night.py").read_text(encoding="utf-8")
    body = src.split("def apply_lane_policy(", 1)[1].split(chr(10) + "def ", 1)[0]
    assert '"|hold=" + ",".join(sorted(ctrl.get("hold_lanes", []) or []))' in body        # 挂道进缓存 key
    assert 'set(IMAGE_LANES if mode == "video_lane_only" else []) | set(ctl_hold)' in body  # 两种模式都合并控制文件挂道


# ---- K-OPS-E09 修订 + E21：重置只看作业签名变化（不比出图后的提示词）；单对象 1 小时超 8 次自动暂停 ----
def test_e09_reset_only_when_job_sig_changes(monkeypatch, tmp_path):
    PR = _producer()
    p = PR.Paths(root=tmp_path)
    monkeypatch.setattr(PR, "job_sig", lambda paths, sid: "S1")
    assert PR.redo_inputs_changed_v2(p, "ep05-S3", "first", {"ladder_sig": "S1"}) is None     # 签名没变 → 不重置
    assert PR.redo_inputs_changed_v2(p, "ep05-S3", "first", {"ladder_sig": "S0"}) == "作业输入变了"
    monkeypatch.setattr(PR, "redo_inputs_changed", lambda *a: "提示词变了")
    assert PR.redo_inputs_changed_v2(p, "ep05-S3", "first", {}) is None                       # 第一次也不信“提示词变了”


def test_e21_obj_rate_guard(tmp_path):
    PR = _producer()
    import threading
    pr = object.__new__(PR.Producer)
    pr.p = PR.Paths(root=tmp_path); pr.p.pd.mkdir(parents=True, exist_ok=True)
    pr.mu = threading.RLock(); pr.logf = lambda ev, **kw: None
    o = {"id": "first:ep05-S3", "shot": "ep05-S3"}
    pr._obj_disp = {o["id"]: [time.time() - i * 60 for i in range(8)]}
    assert pr.obj_rate_exceeded(o, 8) is True
    assert "first:ep05-S3" in PR.asset_hold_objects(pr.p.data)
    assert json.loads((tmp_path / "data/sentinel/tickets.jsonl").read_text(encoding="utf-8").splitlines()[0])["obj"] == "first:ep05-S3"
    pr._obj_disp = {o["id"]: [time.time() - 4000]}
    assert pr.obj_rate_exceeded({"id": "first:ep01-S1", "shot": "ep01-S1"}, 8) is False


# ---- K-OPS-E22：剧本 H3校验 标“本地生成 / 占位”的镜，服务器一律不派 ----
def test_e22_local_only_shots():
    PR = _producer()
    from types import SimpleNamespace as NS
    sc = NS(episodes=[NS(shots=[NS(id="ep07-S10", h3_check="本地生成（亲密镜占位）"), NS(id="ep07-S9", h3_check=None),
                                NS(id="ep08-S4", h3_check="暂缓（露骨内容）")])])
    assert PR.local_only_shots(sc) == {"ep07-S10", "ep08-S4"}
    assert PR.is_server_lane("gpu33:1") and PR.is_server_lane("gpu36:0") and not PR.is_server_lane("laptop:0")
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    body = src.split("def dispatch_frames(", 1)[1].split(chr(10) + "    def ", 1)[0]
    assert "local_only_shots(self.script())" in body and "local_only_skip" in body


# ---- K-OPS-E23：项目方定稿锁的阶段不自动重出（防“撤回 → 重出 → 设不成当前”空转） ----
def test_e23_owner_lock_counts_as_final():
    PR = _producer()
    td = {"active": {"last": 11}, "locked": {"last": 11}, "locked_by": {"last": {"by": "owner", "n": 11}},
          "takes": [{"stage": "last", "n": 11, "postflight": {"ok": False}}]}
    o = PR._frame_obj("last", "last", "ep01-S1", 1, td, {}, {}, {}, {}, False, deps_ok=True, first={"status": "passed"})
    assert o["status"] == "passed" and o.get("owner_locked")


# ---- K-OPS-E24：重新导入后作业签名变了 → 已过的首帧自动重出（不计次） ----
def test_e24_first_input_changed(monkeypatch, tmp_path):
    PR = _producer()
    p = PR.Paths(root=tmp_path)
    fo = {"id": "first:ep01-S1", "status": "passed", "take": 3}
    # K-REN-956 + 护栏（17:3x）：只认剧本输入签名 passed_input_sig；编译产物（job_sig）变了不重出已通过的帧
    monkeypatch.setattr(PR, "job_sig", lambda paths, sid: "NEW")
    monkeypatch.setattr(PR, "input_sig", lambda paths, sid: "IN_NEW")
    assert PR.first_input_changed(p, "ep01-S1", fo, {"passed_sig": "OLD"})["status"] == "passed"            # 只有编译变化
    assert PR.first_input_changed(p, "ep01-S1", fo, {"passed_sig": "OLD", "passed_input_sig": "IN_OLD"})["status"] == "ready"
    assert PR.first_input_changed(p, "ep01-S1", fo, {"passed_sig": "OLD", "passed_input_sig": "IN_NEW"})["status"] == "passed"
    assert PR.first_input_changed(p, "ep01-S1", fo, {"passed_sig": "stale:补丁", "passed_input_sig": "stale:补丁"})["status"] == "ready"   # requeue_first 手动兜底
    assert PR.first_input_changed(p, "ep01-S1", fo, {})["status"] == "passed"                       # 旧数据没签名不动
    assert PR.first_input_changed(p, "ep01-S1", {**fo, "owner_locked": True}, {"passed_sig": "OLD"})["status"] == "passed"


# ---- K-OPS-Y04：借道 / 临时挂道收进 tools/debug/lanes.py（加锁、到期自动清） ----
def test_y04_lanes_lend_hold_sweep(tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "debug"))
    import lanes as LN
    part = tmp_path / "partition.json"
    part.write_text(json.dumps({"retired_lanes": ["gpu36:2"]}), encoding="utf-8")
    t0 = 1_800_000_000.0
    LN.lend("gpu33:3", "IMGFIX", 40, "imggen-s10", "test", part=part, now=t0)
    LN.hold("gpu36:0", 5, "restart", part=part, now=t0)
    d = json.loads(part.read_text(encoding="utf-8"))
    assert set(d["retired_lanes"]) == {"gpu36:2", "gpu33:3", "gpu36:0"}
    assert d["_lent_lanes"]["gpu33:3"]["client_prefix"] == "imggen-s10" and d["_lent_lanes"]["gpu33:3"]["expires_at"]
    assert LN.sweep(part=part, now=t0 + 10 * 60) == ["gpu36:0"]                      # 挂道 5 分钟到期，借道 40 分钟未到
    assert LN.sweep(part=part, now=t0 + 41 * 60) == ["gpu33:3"]
    d = json.loads(part.read_text(encoding="utf-8"))
    assert d["retired_lanes"] == ["gpu36:2"] and not d["_lent_lanes"] and not d["_temp_holds"]


def test_e25_repart_check():
    sys.path.insert(0, str(ROOT / "tools" / "debug"))
    import lanes as LN
    probs = LN.repart_check({"gpu33": [8, 9, 11]}, {"gpu33": {1, 3}, "gpu36": {8, 9}})
    assert len(probs) == 2 and "ep08" in probs[0]                                   # ep11 两边都没有 → 可直接搬


# ---- K-OPS-E26：缺资产（I3 / I4）/ 期望 refs 表不一致 → 等资产，签名一变自动放回（不靠 30 分钟退避） ----
def _wa_producer(PR, tmp_path):
    import threading
    pr = object.__new__(PR.Producer)
    pr.p = PR.Paths(root=tmp_path); pr.p.pd.mkdir(parents=True, exist_ok=True); pr.p.run.mkdir(parents=True, exist_ok=True)
    pr.mu = threading.RLock(); pr.events = []
    pr.logf = lambda ev, **kw: pr.events.append((ev, kw))
    return pr


def test_e26_wait_kind():
    PR = _producer()
    assert PR.wait_kind("ep01-S1 生成契约 preflight 不通过：I3 本镜造型 id + 造型设定图：林晚 造型B 没有设定图") == "asset"
    assert PR.wait_kind("preflight：I4 景别可见的单品资产图：资产缺图：林晚 造型A 的服装“米白衬衫”没有图") == "asset"
    assert PR.wait_kind("生成契约 preflight 不通过，未提交：K-OPS-F03 refs 与目标状态不一致：x") == "refs"
    assert PR.wait_kind("I5 场景参考底图：场景 x 没有参考底图") is None       # 别的原因照旧 30 分钟退避


def _wait(pr, PR, oid, kind):
    pr.led_update(oid, blocked_until=time.time() + PR.WAIT_ASSET_MAX_S,
                  waiting_asset={"kind": kind, "asset_sig": PR.asset_sig(pr.p), "refs_sig": PR.refs_table_sig(pr.p.root)})
    pr.led_update("assets:" + oid.split(":", 1)[1], blocked=True, at=time.time())


def test_e26_asset_release_on_registry_change(tmp_path):
    PR = _producer()
    pr = _wa_producer(PR, tmp_path)
    _wait(pr, PR, "first:ep01-S1", "asset")
    assert pr.release_waiting_assets(every_s=0) == []                              # 没变 → 继续等
    assert pr.ledger()["first:ep01-S1"]["blocked_until"] > time.time()
    d = pr.p.run / "assets"; d.mkdir(parents=True)
    (d / "sheets_chosen.json").write_text('{"sheet:lin_wan_lookB": {}}', encoding="utf-8")   # 设定图登记 → 签名变
    assert pr.release_waiting_assets(every_s=0) == ["first:ep01-S1"]
    r = pr.ledger()["first:ep01-S1"]
    assert r["blocked_until"] == 0 and r["waiting_asset"] is None and "不计次" in r["reason"]
    assert pr.ledger()["assets:ep01-S1"]["blocked"] is False
    assert pr.events[-1][0] == "asset_release" and pr.events[-1][1]["counted"] is False
    assert pr.release_waiting_assets(every_s=0) == []                              # 已放回，不重复


def test_e26_refs_release_on_expected_table_change(tmp_path):
    PR = _producer()
    pr = _wa_producer(PR, tmp_path)
    f = tmp_path / "data/factory/inbox/expected_refs.json"; f.parent.mkdir(parents=True)
    f.write_text("{}", encoding="utf-8")
    _wait(pr, PR, "first:ep02-S3", "refs")
    _wait(pr, PR, "first:ep02-S4", "asset")
    assert pr.release_waiting_assets(every_s=0) == []
    f.write_text('{"series10_s2": {}}', encoding="utf-8")                          # FACTORY 重建期望表
    assert pr.release_waiting_assets(every_s=0) == ["first:ep02-S3"]               # 只放等表的；等资产的不动
    assert pr.ledger()["first:ep02-S4"]["blocked_until"] > time.time()


def test_e26_release_throttled(tmp_path):
    PR = _producer()
    pr = _wa_producer(PR, tmp_path)
    _wait(pr, PR, "first:ep03-S1", "asset")
    pr.release_waiting_assets(every_s=60)
    (pr.p.run / "P1_looks.json").write_text("{}", encoding="utf-8")
    assert pr.release_waiting_assets(every_s=60) == []                              # 一分钟内不重查
    pr._wa_check_t = 0
    assert pr.release_waiting_assets(every_s=60) == ["first:ep03-S1"]


def test_e26_asset_sig_follows_config_registry(tmp_path):
    PR = _producer()
    p = PR.Paths(root=tmp_path)
    cfg = tmp_path / "config/recipes/asset_refs.json"; cfg.parent.mkdir(parents=True)
    cfg.write_text('{"projects": {"s1": {"sheets_file": "data/s1_sheets.json"}}}', encoding="utf-8")
    a = PR.asset_sig(p)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "data/s1_sheets.json").write_text("{}", encoding="utf-8")           # 父季设定图表登记 → 变
    b = PR.asset_sig(p)
    assert a != b
    w = tmp_path / "data/looks/wardrobe.json"; w.parent.mkdir(parents=True); w.write_text("{}", encoding="utf-8")
    assert PR.asset_sig(p) != b                                                     # 单品图登记 → 变


# ---- 附录 A2：takes.json 唯一写入口 mutate_takes + tools/pipeline/takes_cli.py ----
def _pl(monkeypatch, tmp_path):
    for p in ("services/render_router", "packages/schema", "services/agent", "services/recipes"):
        if str(ROOT / p) not in sys.path:
            sys.path.insert(0, str(ROOT / p))
    from ns_render import pipeline as P
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data/renders")
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "ROOT", tmp_path)
    return P


def test_a2_mutate_takes_seq_lastop_conflict(monkeypatch, tmp_path):
    P = _pl(monkeypatch, tmp_path)
    p = P.takes_path("ep01-S1"); p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"takes": [{"n": 1}], "active": {"image": 1}}), encoding="utf-8")   # 旧文件没有 seq = 0
    d = P.mutate_takes("ep01-S1", lambda doc: doc["takes"].append({"n": 2}), op="t", by="DEBUG_RSI", op_id="o1", expect_seq=0)
    assert d["seq"] == 1 and d["last_op"]["op_id"] == "o1" and d["last_op"]["at"].endswith("+09:00")
    assert len(json.loads(p.read_text(encoding="utf-8"))["takes"]) == 2
    d2 = P.mutate_takes("ep01-S1", lambda doc: doc["takes"].append({"n": 3}), op="t", by="x", op_id="o1")   # 重放 → 不执行
    assert d2["seq"] == 1 and len(d2["takes"]) == 2
    import pytest
    with pytest.raises(P.TakesConflict) as ei:
        P.mutate_takes("ep01-S1", lambda doc: None, op="t", by="x", expect_seq=0)
    assert ei.value.actual == 1
    assert len(list((p.parent / ".takes_bak").glob("takes.*.json"))) == 1


def test_a2_backup_rotation_moves_to_quarantine(monkeypatch, tmp_path):
    P = _pl(monkeypatch, tmp_path)
    p = P.takes_path("ep02-S1"); p.parent.mkdir(parents=True)
    p.write_text('{"takes": [], "active": {}}', encoding="utf-8")
    monkeypatch.setattr(P, "TAKES_BAK_KEEP", 2)
    for i in range(4):
        P.mutate_takes("ep02-S1", lambda doc: None, op="t", by="x")
        time.sleep(0.02)
    assert len(list((p.parent / ".takes_bak").glob("*.json"))) == 2
    assert len(list((tmp_path / "data/_quarantine/takes_bak/_/ep02-S1").glob("*.json"))) == 2     # 不删，隔离
    assert json.loads(p.read_text(encoding="utf-8"))["seq"] == 4


def test_a2_last_ops_capped_and_run_path(monkeypatch, tmp_path):
    P = _pl(monkeypatch, tmp_path)
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text('{"primary": "s1", "legacy_unprefixed_run": "s1", "runs": {"s1": {}, "s2": {}}}', encoding="utf-8")
    assert P.takes_path("ep01-S1", "s1") == tmp_path / "data/renders/ep01/S1/takes.json"
    assert P.takes_path("ep01-S1", "s2") == tmp_path / "data/renders/s2/ep01/S1/takes.json"
    monkeypatch.setattr(P, "TAKES_LAST_OPS", 3)
    for i in range(5):
        d = P.mutate_takes("ep01-S1", lambda doc: None, op="t", by="x", op_id=f"o{i}", run="s2")
    assert [x["op_id"] for x in d["last_ops"]] == ["o2", "o3", "o4"] and d["seq"] == 5


def test_a2_takes_cli_get_replace(monkeypatch, tmp_path, capsys):
    import io
    P = _pl(monkeypatch, tmp_path)
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    import takes_cli as TC
    p = P.takes_path("ep03-S2"); p.parent.mkdir(parents=True)
    p.write_text('{"takes": [{"n": 1}], "active": {"image": 1}}', encoding="utf-8")
    assert TC.main(["get", "--sid", "ep03-S2"]) == 0
    got = json.loads(capsys.readouterr().out)
    assert got["seq"] == 0 and got["doc"]["active"]["image"] == 1

    def run(args, doc):
        monkeypatch.setattr(sys, "stdin", io.TextIOWrapper(io.BytesIO(json.dumps(doc).encode("utf-8"))))
        rc = TC.main(args)
        return rc, json.loads(capsys.readouterr().out)
    new = {"takes": [{"n": 1}, {"n": 2}], "active": {"image": 2}, "seq": 99}
    rc, out = run(["replace", "--sid", "ep03-S2", "--op", "merge", "--by", "WORKFLOW", "--expect-seq", "0", "--op-id", "w1"], new)
    assert rc == 0 and out == {"ok": True, "seq": 1}
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["active"]["image"] == 2 and d["seq"] == 1 and d["last_op"]["by"] == "WORKFLOW"   # stdin 里的 seq 被忽略
    rc, out = run(["replace", "--sid", "ep03-S2", "--op", "merge", "--by", "WORKFLOW", "--expect-seq", "0"], new)
    assert rc == 3 and out["code"] == "stale_base" and out["seq"] == 1
    rc, out = run(["replace", "--sid", "ep03-S2", "--op", "m", "--by", "W"], {"active": {}})
    assert rc == 2


def test_a2_legacy_save_takes_goes_through_entry(monkeypatch, tmp_path):
    P = _pl(monkeypatch, tmp_path)
    p = P.takes_path("ep04-S1"); p.parent.mkdir(parents=True)
    p.write_text('{"takes": [], "active": {}}', encoding="utf-8")
    d = P.load_takes("ep04-S1"); d["active"]["image"] = 1
    P._save_takes("ep04-S1", d)
    assert json.loads(p.read_text(encoding="utf-8"))["seq"] == 1
    stale = {"takes": [], "active": {}, "seq": 0}                                  # 读的时候 seq=0，期间别人写到 1
    P._save_takes("ep04-S1", stale)
    assert json.loads(p.read_text(encoding="utf-8"))["seq"] == 2                   # seq 不倒退
    c = (tmp_path / "data/state/takes_conflicts.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(c) == 1 and json.loads(c[0])["file_seq"] == 1
    # fn 返回 pop 出来的 dict 不会把整份 doc 换掉
    P.mutate_takes("ep04-S1", lambda x: x.setdefault("master_gate", {}).__setitem__("image", {"k": 1}), op="t", by="x")
    P.mutate_takes("ep04-S1", lambda x: (x.get("master_gate") or {}).pop("image", None), op="t", by="x")
    d = json.loads(p.read_text(encoding="utf-8"))
    assert "takes" in d and d["master_gate"] == {} and d["seq"] == 4


# ---- Y04 补：借道借出满 10 分钟没人用 → 自动收回（总调度 11-02 14:0x） ----
def test_y04_idle_sweep(tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "debug"))
    import lanes as LN
    part = tmp_path / "partition.json"
    t0 = time.time()
    for lane in ("gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1"):
        LN.lend(lane, "X", 60, "x-", "t", part=part, now=t0 - 20 * 60)
    LN.lend("gpu33:0", "Y", 60, "y-", "t", part=part, now=t0 - 2 * 60)              # 刚借出 2 分钟 → 不收
    st = {"gpu33:1": {"ok": True, "busy": False, "last_end": t0 - 15 * 60},          # 空 15 分钟 → 收
          "gpu33:3": {"ok": True, "busy": True, "last_end": None},                   # 在跑 → 不收
          "gpu36:0": {"ok": True, "busy": False, "last_end": t0 - 3 * 60},           # 3 分钟前刚出完 → 不收
          "gpu36:1": {"ok": False}}                                                  # 探测失败 → 不动
    called = []
    gone = LN.idle_sweep(10, probe=lambda l: (called.append(l), st[l])[1], part=part, now=t0)
    assert gone == ["gpu33:1"] and "gpu33:0" not in called
    d = json.loads(part.read_text(encoding="utf-8"))
    assert "gpu33:1" not in d["_lent_lanes"] and "gpu33:1" not in d["retired_lanes"] and "gpu33:3" in d["retired_lanes"]
    assert any(json.loads(x)["ev"] == "idle_release" for x in (tmp_path / "lane_loans.jsonl").read_text(encoding="utf-8").splitlines())
    assert LN.lane_port("gpu33:3") == 8191


# ---- 视频按镜 hold：data/autopilot/video_hold.json → build_jobs 不出变体（总调度 11-02 14:2x，fb-0001） ----
def test_video_hold_filters_and_expires(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    B = _load_s10v("build_jobs")      # script_name_guard：tools/char_assets 也有 build_jobs.py，按路径加载
    f = tmp_path / "video_hold.json"
    monkeypatch.setattr(B, "VIDEO_HOLD", f)
    assert B.video_holds() == {}
    t = time.time()
    fut = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t + 3600))
    past = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t - 60))
    f.write_text(json.dumps({"active": True, "items": {
        "ep02-S3": {"reason_kind": "wait_script_patch", "reason": "fb-0001", "expires_at": fut},
        "ep04-S1": {"reason_kind": "x", "expires_at": past}}}), encoding="utf-8")
    h = B.video_holds(t)
    assert list(h) == ["ep02-S3"] and h["ep02-S3"].startswith("wait_script_patch")
    f.write_text('{"active": false, "items": {"ep02-S3": {}}}', encoding="utf-8")
    assert B.video_holds(t) == {}
    f.write_text("{bad", encoding="utf-8")
    import pytest
    with pytest.raises(ValueError):
        B.video_holds(t)


# ---- K-OPS-E28：每镜每阶段 24 小时自动出图硬上限（ep05-S3 首帧 92 版），不受各条重置路径影响 ----
def test_e28_stage_renders_24h_counts_takes():
    PR = _producer()
    t = time.time()
    ts = lambda h: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t - h * 3600))
    td = {"takes": [{"stage": "image", "created_at": ts(1)}, {"stage": "image", "created_at": ts(23)},
                    {"stage": "image", "created_at": ts(25)},                              # 超过 24 小时不算
                    {"stage": "image", "created_at": ts(2), "origin": "manual_edit"},      # 手工编辑不算
                    {"stage": "last", "created_at": ts(1)}]}
    assert PR.stage_renders_24h(td, "image", t) == 2 and PR.stage_renders_24h(td, "last", t) == 1


def test_e28_hard_cap_blocks_and_uncap(monkeypatch, tmp_path):
    PR = _producer()
    import threading
    pr = object.__new__(PR.Producer)
    pr.p = PR.Paths(root=tmp_path); pr.p.pd.mkdir(parents=True, exist_ok=True)
    pr.mu = threading.RLock(); pr.events = []
    pr.logf = lambda ev, **kw: pr.events.append((ev, kw))
    t = time.time()
    takes = {"takes": [{"stage": "image", "n": i, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t - i * 60))}
                       for i in range(10)]}
    for p in ("services/render_router", "packages/schema", "services/agent", "services/recipes"):
        if str(ROOT / p) not in sys.path:
            sys.path.insert(0, str(ROOT / p))
    from ns_render import pipeline as P
    monkeypatch.setattr(P, "load_takes", lambda sid: takes)
    o = {"id": "first:ep05-S3", "shot": "ep05-S3"}
    assert pr.hard_capped(o, cap=10) is True
    led = pr.ledger()["first:ep05-S3"]
    assert led["hard_capped"]["n"] == 10 and "K-OPS-E28" in led["reason"]
    assert json.loads((tmp_path / "data/sentinel/tickets.jsonl").read_text(encoding="utf-8").splitlines()[0])["obj"] == "first:ep05-S3"
    assert pr.hard_capped(o, cap=10) is True and sum(1 for e in pr.events if e[0] == "hard_cap") == 1    # 只开一次单
    pr.led_update("first:ep05-S3", redo_tries=0, tries=0, final=None)        # 各条重置路径只清阶梯次数 → 仍然封顶
    assert pr.hard_capped(o, cap=10) is True
    pr.led_update("first:ep05-S3", cap_extra={"n": 2, "t": time.time() - 1})    # uncap：放行之后再出 2 版
    assert pr.hard_capped(o, cap=10) is False
    later = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() + 5))
    takes["takes"] += [{"stage": "image", "n": 90, "created_at": later}, {"stage": "image", "n": 91, "created_at": later}]
    assert pr.hard_capped(o, cap=10) is True                                     # 放行后已出 2 版 → 又封顶
    assert pr.hard_capped({"id": "last:ep05-S3", "shot": "ep05-S3"}, cap=10) is False   # 阶段分开算
    assert pr.hard_capped({"id": "video:ep05-S3", "shot": "ep05-S3"}, cap=10) is False  # 视频走 vidgen 有限阶梯


# ---- night 跨服务器派单：分给另一台的集跳过，不算失败（FOCUS 第 5 条，ep07 / 09 / 10 视频卡住） ----
def test_night_skips_other_host(monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
    import night as N
    calls = []
    monkeypatch.setattr(N, "run", lambda args, timeout=3600: (calls.append(list(args)), (0, "ok"))[1])
    monkeypatch.setattr(N, "_rssh", lambda: type("R", (), {"_local_self": staticmethod(lambda h: "other" if h == "gpu36" else "self")}))
    monkeypatch.setattr(N, "jl", lambda p, d=None: {"7": "gpu33", "8": "gpu36"} if str(p).endswith("hosts.json") else d)
    monkeypatch.setattr(N, "log", lambda *a: None)
    ctrl = {"hold_lanes": [], "per_lane": 2, "shared_lanes": [], "yield_s": 180}
    assert N.dispatch_hosts({"gpu33", "gpu36"}, {}, ctrl) is True
    pushes = [c for c in calls if "push" in c]
    assert [c[-1] for c in pushes] == ["gpu33"] and not any("gpu36" in c for c in calls)


# ---- K-OPS-E29：身份脸唯一入口 asset_refs.face_of（总调度 11-02 16:3x：视频身份分读 config faces、复核带写死 L-086，L-122 换脸后分叉） ----
FACE_PROD_DIRS = ["services", "packages", "tools/autopilot", "tools/series10_video", "tools/pipeline", "tools/gen_contract",
                  "tools/script_rsi", "tools/qa", "tools/factory", "tools/netfix", "tools/debug"]
FACE_LIST_OK = {   # 只枚举候选文件做存在性检查 / 列表展示，允许读配置 faces；“当前身份脸是哪张”一律 face_of
    "services/agent/ns_agent/asset_refs.py", "services/agent/ns_agent/gen_contract/preflight.py",
    "tools/pipeline/remote_preflight.py", "services/api/ns_api/character_hub.py", "tools/qa/identity_face_check.py"}


def test_e29_identity_face_single_entry():
    import ast
    import re
    lit = re.compile(r"identity_refs/[a-z_]+/[a-z_]+_face|/refs/lin_wan/ar-|face_hd_A_s202")
    bad = []
    for d in FACE_PROD_DIRS:
        for f in (ROOT / d).rglob("*.py"):
            rel = f.relative_to(ROOT).as_posix()
            if rel in FACE_LIST_OK or "/tests/" in rel:
                continue
            tree = ast.parse(f.read_text(encoding="utf-8"))
            docs = {id(n.body[0].value) for n in ast.walk(tree)
                    if isinstance(n, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.body
                    and isinstance(n.body[0], ast.Expr) and isinstance(getattr(n.body[0], "value", None), ast.Constant)}
            for n in ast.walk(tree):
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in docs and lit.search(n.value):
                    bad.append(f"{rel}:{n.lineno} 写死身份脸路径")
                if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == "get" and n.args
                        and isinstance(n.args[0], ast.Constant) and n.args[0].value == "faces" and "cfg" in ast.unparse(n.func.value).lower()):
                    bad.append(f"{rel}:{n.lineno} 直接读配置 faces")
    assert not bad, bad


def test_e29_video_score_refs_use_face_of(monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    B = _load_s10v("build_jobs")      # script_name_guard：tools/char_assets 也有 build_jobs.py，按路径加载
    from ns_agent import asset_refs as AR
    monkeypatch.setattr(AR, "face_of", lambda project, cid: f"faces/{project}/{cid}.png")
    spec = type("S", (), {"faces": [type("C", (), {"name": "林晚"})(), type("C", (), {"name": "路人"})()]})()
    assert B.score_refs(spec, None) == {"林晚": f"faces/{B.RUN.name}/lin_wan.png"}


# ---- L-124 ep01-S1：E13 不覆盖定稿锁；视频尾帧关键帧映射 + 首尾成对；提交连报错转 blocked ----
def test_l124_last_consistent_respects_owner_lock():
    PR = _producer()
    td = {"active": {"image": 22, "last": 11}, "takes": [{"stage": "image", "n": 22, "created_at": "2026-11-02T04:07"},
                                                         {"stage": "last", "n": 11, "created_at": "2026-11-01T05:00"}]}
    lo = {"status": "passed", "owner_locked": True, "take": 11}
    assert PR.last_consistent(td, {"status": "passed"}, lo) is lo
    lo2 = {"status": "passed", "take": 11}
    assert PR.last_consistent(td, {"status": "passed"}, lo2)["status"] == "ready"       # 没锁的照旧 E13 作废


def test_l124_build_jobs_last_frame_pairing(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    B = _load_s10v("build_jobs")      # script_name_guard：tools/char_assets 也有 build_jobs.py，按路径加载
    monkeypatch.setattr(B, "ROOT", tmp_path)
    d = tmp_path / "data/renders/ep01/S1"; d.mkdir(parents=True)
    (tmp_path / "data/renders/ep01/S1/last_011.png").write_bytes(b"x")
    (d / "takes.json").write_text(json.dumps({"locked": {"last": 11}, "active": {"last": 12}, "takes": [
        {"stage": "last", "n": 11, "file": "renders/ep01/S1/last_011.png", "created_at": "2026-11-01T05:00:00"},
        {"stage": "last", "n": 12, "file": "renders/ep01/S1/missing.png", "postflight": {"ok": True}}]}), encoding="utf-8")
    got = B.passed_lasts()
    assert got == {"ep01-S1": {"file": "data/renders/ep01/S1/last_011.png", "created_at": "2026-11-01T05:00:00"}}   # 定稿锁优先
    src = (ROOT / "tools/series10_video/build_jobs.py").read_text(encoding="utf-8")
    assert '"@last_frame"' in src and "stale_pair" in src


def test_l124_vidgen_blocks_after_two_submit_errors():
    src = (ROOT / "tools/series10_video/vidgen.py").read_text(encoding="utf-8")
    assert "SHOT_BLOCKED_SUBMIT" in src and 'x.get("state") == "submit_error"' in src


# ---- K-OPS-E30（L-124）：派单按集顺序，驳回 / 插队只在同一集内优先 ----
def test_e30_episode_order_key():
    PR = _producer()
    c = [(3, 1, 2, {"redo": True}), (1, 1, 5, {}), (1, 0, 7, {}), (2, 1, 1, {"redo": True}), (1, 1, 2, {"redo": True})]
    got = [(x[0], x[2]) for x in sorted(c, key=PR.episode_order_key)]
    assert got == [(1, 2), (1, 7), (1, 5), (2, 1), (3, 2)]      # ep01 全部先于 ep02 的驳回单；集内驳回先、尾帧先


def test_e30_vidgen_pending_sorted_by_episode():
    src = (ROOT / "tools/series10_video/vidgen.py").read_text(encoding="utf-8")
    assert "K-OPS-E30" in src and "sorted(shots.items()" in src


def test_l124_vidgen_force_queue_bypasses_cap(monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
    import vidgen as V
    monkeypatch.setattr(V, "policy_ok", lambda var: True)
    shot = {"variants": {k: {"status": "ready"} for k in ("v1", "mot", "s2", "s3", "r24", "alt", "s4")}}
    rec = {"renders": [{"variant": k, "score": {"gate": {"fails": ["动作不足"]}}} for k in ("v1", "mot", "s2", "s3")]}
    assert V.next_variant(shot, rec) is None                          # 4 次上限到了
    rec["force_queue"] = ["r24", "alt", "s4"]
    assert V.next_variant(shot, rec) == "r24"                         # 加变体不受上限限制
    rec["renders"].append({"variant": "r24", "score": {}})
    assert V.next_variant(shot, rec) == "alt"


# ---- 排队位置 / 预计完成（给 ASSETUX）：E30 同口径排序；服务器 registry 过期时标 stale ----
def test_queue_eta_order_and_stale(tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    import queue_eta as Q
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text('{"primary": "s1", "legacy_unprefixed_run": "s1", "runs": {"s1": {}}}', encoding="utf-8")
    (tmp_path / "data/state/netfix").mkdir(parents=True)
    (tmp_path / "data/state/netfix/partition.json").write_text(json.dumps(
        {"images": {"gpu33": [1, 2]}, "video": {"gpu33": [1, 2]}, "lanes": {"gpu33": ["gpu33:0", "gpu33:1"]}}), encoding="utf-8")
    def ob(i, st, redo=False):
        return {"id": i, "status": st, "redo": redo}
    reg = {"updated": "x", "episodes": [
        {"ep": 2, "shots": [{"shot": "ep02-S1", "index": 1, "objects": {"first": ob("first:ep02-S1", "ready", True), "last": ob("last:ep02-S1", "pending")}}]},
        {"ep": 1, "shots": [{"shot": "ep01-S3", "index": 3, "objects": {"first": ob("first:ep01-S3", "ready"), "last": ob("last:ep01-S3", "ready")}}]}]}
    (tmp_path / "data/producer").mkdir(parents=True)
    (tmp_path / "data/producer/registry.json").write_text(json.dumps(reg), encoding="utf-8")
    d = Q.compute(tmp_path, now=1_000_000.0)
    o = d["objects"]
    assert [k for k, v in sorted(o.items(), key=lambda kv: kv[1]["pos"])] == ["last:ep01-S3", "first:ep01-S3", "first:ep02-S1"]
    assert o["first:ep02-S1"]["ahead"] == ["last:ep01-S3", "first:ep01-S3"] and d["basis"]["stale"] is True


# ---- sv-14 护栏（总调度 11-02 17:3x）：编译变化不作废已通过帧；anomaly 判出重复人 / 多余人头的首帧不进视频；A-02 打分超时只重打分 ----
def test_guard_stale_whitelist():
    PR = _producer()
    assert PR.stale_requeue_reasons(["编译器升级"]) == []
    assert PR.stale_requeue_reasons(["本镜输入已改"]) == []          # 站位句 / 参考槽调整落在这里：交验收，不重出
    assert PR.stale_requeue_reasons(["造型已改"]) == [] and PR.stale_requeue_reasons(True) == []
    assert PR.stale_requeue_reasons(["提示词已改", "编译器升级"]) == ["提示词已改"]
    assert PR.stale_requeue_reasons("剧本已改") == ["剧本已改"]


def test_guard_anomaly_blocks_video(monkeypatch, tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    B = _load_s10v("build_jobs")      # script_name_guard：tools/char_assets 也有 build_jobs.py，按路径加载
    rows = {("ep04-S10", "image_006.png"): {"ok": "fail", "count": {"status": "fail", "defects": ["duplicate_person：两个头都是陈宇"]}}}
    assert "duplicate_person" in B.anomaly_block("ep04-S10", "renders/ep04/S10/takes/image_006.png", {"ok": True}, rows)
    assert B.anomaly_block("ep04-S10", "renders/ep04/S10/takes/image_007.png", {"ok": True}, rows) is None      # 另一版没判过：不拦
    pf = {"ok": True, "items": [{"id": "Q10", "evidence": {"count": {"defects": ["extra_head：镜里是陌生人"]}}}]}
    assert "extra_head" in B.anomaly_block("ep01-S1", "x.png", pf, {})
    assert B.anomaly_block("ep01-S1", "x.png", {"ok": True, "items": [{"id": "Q10", "evidence": {"count": {"defects": ["extra_hands：3 只手"]}}}]}, {}) is None


def test_guard_a02_score_timeout_only_rescore():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    i = src.index('pf = res["pf_future"].result(timeout=1800)')
    block = src[i - 200:i + 900]
    assert "except Exception" in block and "rescore_take=res[\"take\"]" in block and "score_timeout" in block


# ---- D-VQA-01 收紧（总调度 17:4x）：首帧没跑过 / 没通过第 8 步验收的不进视频，按镜生效 ----
def test_accept_gate_status():
    sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    B = _load_s10v("build_jobs")      # script_name_guard：tools/char_assets 也有 build_jobs.py，按路径加载
    rows = {("ep07-S1", "image_008.png"): {"ok": "pass", "count": {"defects": []}},
            ("ep07-S2", "image_008.png"): {"ok": "fail", "count": {"defects": []}}}
    assert B.accept_status("ep07-S1", "renders/ep07/S1/takes/image_008.png", {}, rows) == "pass"
    assert B.accept_status("ep07-S2", "renders/ep07/S2/takes/image_008.png", {}, rows) == "fail"
    assert B.accept_status("ep07-S3", "x/image_001.png", {}, rows) is None                     # 没跑过 → 不进视频
    assert B.accept_status("ep07-S1", "x.png", {"items": [{"id": "Q10", "status": "untested"}]}, rows) == "untested"   # Q10 优先
    assert B.ACCEPT_REQUIRED is True


# ---- A-09（V2_READINESS）：E28 带时区比较；hold 按 run 隔离；restart_queue 只解自己设的暂停 ----
def test_a09_ts_epoch_timezones():
    PR = _producer()
    a = PR.ts_epoch("2026-11-02T18:00:00+09:00")
    assert PR.ts_epoch("2026-11-02T18:00:00") == a                       # 不带时区按东京
    assert PR.ts_epoch("2026-11-02T04:00:00-05:00") == a                 # EST 旧串换算后相同
    assert PR.ts_epoch("2026-11-02T09:00:00Z") == a and PR.ts_epoch("x") is None and PR.ts_epoch(None) is None
    t = a + 3600
    td = {"takes": [{"stage": "image", "created_at": "2026-11-02T04:30:00-05:00"},      # 东京 18:30，在 24 小时内
                    {"stage": "image", "created_at": "2026-11-01T17:00:00+09:00"}]}     # 25 小时前
    assert PR.stage_renders_24h(td, "image", t) == 1


def test_a09_hold_isolated_by_run(tmp_path):
    PR = _producer()
    d = tmp_path / "autopilot"; d.mkdir()
    (d / "runaway_hold.json").write_text(json.dumps({"active": True, "shots": [
        {"shot": "ep05-S3", "objects": ["first:ep05-S3"]},                               # 旧条目没写 run → 只管主剧
        {"shot": "ep01-S1", "run": "series10_v2", "objects": ["first:ep01-S1"]}]}), encoding="utf-8")
    v1 = PR.asset_hold_objects(tmp_path, "series10_v1", "series10_v1")
    v2 = PR.asset_hold_objects(tmp_path, "series10_v2", "series10_v1")
    assert v1 == {"first:ep05-S3"} and v2 == {"first:ep01-S1"}
    assert PR.asset_hold_objects(tmp_path) == {"first:ep05-S3", "first:ep01-S1"}           # 不指定 run（旧调用）= 全部


def test_a09_restart_queue_keeps_foreign_pause():
    sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
    import restart_queue as RQ
    class RS:
        R = "/r"
        def __init__(self, ctrl): self.ctrl = ctrl
        def ssh(self, host, cmd, **kw): return json.dumps(self.ctrl).encode()
    assert RQ.pre_paused("gpu33", RS({"paused": True, "paused_by": "DEPLOY_ATOMIC"})) == "DEPLOY_ATOMIC"
    assert RQ.pre_paused("gpu33", RS({"paused": False})) is None
    class Bad(RS):
        def ssh(self, host, cmd, **kw): raise RuntimeError("连不上")
    assert RQ.pre_paused("gpu33", Bad({})).startswith("unknown")                          # 读不到 = 保守按已暂停


def _load_s10v(name: str):
    """按文件路径加载 tools/series10_video/<name>.py（同名脚本别处也有，裸 import 在别的测试先改过 sys.path 时会撞名）"""
    import importlib.util as _u
    import sys as _s
    key = f"s10v_{name}"
    if key in _s.modules:
        return _s.modules[key]
    sp = _u.spec_from_file_location(key, ROOT / "tools" / "series10_video" / f"{name}.py")
    m = _u.module_from_spec(sp)
    _s.modules[key] = m
    sp.loader.exec_module(m)
    return m
