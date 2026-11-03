"""W17b RELEASE-P1（A17 第 28 轮 P1-1…P1-5 + W18 restart_queue mode）：
P1-1 CliRunner 超时杀整棵进程树；P1-3 required_groups；P1-5 handover 失败即停；P1-4 cut_lock 续期；restart_queue 按 mode 执行。
全部临时目录 + 打桩：不 commit 真仓库、不碰服务器、不写真实 data/。"""
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SV = _load("tools/qa/system_version.py", "ns_sv_w17b_t")
RT = _load("tools/autopilot/release_tick.py", "ns_release_tick_w17b_t")
TA = _load("tests/test_release_auto.py", "ns_test_release_auto_w17b")      # 复用 FakeRunner / FakeRS / CFG / _req / repo 夹具的写法


@pytest.fixture
def repo(tmp_path, monkeypatch):
    r = TA.repo.__wrapped__(tmp_path, monkeypatch)
    monkeypatch.setattr(SV, "CUT_LOCK", tmp_path / "cut_lock.json")      # 本文件自己的 SV 实例也换成临时锁（真机此刻可能在 cut）
    return r


# ---------------------------------------------------------------- P1-1
def test_cli_runner_timeout_kills_whole_tree(tmp_path, monkeypatch):
    """W37：超时 → run_watched 把启动时记录的身份 (pid, 启动窗口, argv) 交给 _kill_tree。_kill_tree 打桩，不真杀任何进程
    （旧版在真实进程树上演练 taskkill /T /F，pid 复用时 /T 领养到 api_watchdog.py——CUTC_PRECHECK ⑦-1）"""
    root = tmp_path / "r"
    (root / "tools/qa").mkdir(parents=True)
    (root / "tools/qa/system_version.py").write_text("import time\ntime.sleep(4)\n", encoding="utf-8")
    calls = []
    monkeypatch.setattr(SV, "_kill_tree", lambda pr, ident=None, **kw: calls.append((pr.pid, dict(ident or {}))) or {"killed": []})
    sv = SimpleNamespace(ENV=dict(os.environ), PY=sys.executable, run_watched=SV.run_watched)
    runner = RT.CliRunner(sv, {"cut_timeout_s": 1}, root, poll_s=0.2)
    t0 = time.time()
    rep = runner.cut("deadbeef", dry=True)
    assert rep["rc"] == 124 and rep["ok"] is False and "超时" in rep["reason"] and time.time() - t0 < 60
    assert len(calls) == 1
    pid, ident = calls[0]
    assert ident["pid"] == pid and ident["t0"] <= ident["t1"] and t0 <= ident["t0"]
    assert ident["argv"][0] == sys.executable and ident["argv"][1].endswith("system_version.py")


def _row(ppid, born, cmd="python.exe x"):
    return {"ppid": ppid, "born": born, "cmd": cmd}


def test_kill_plan_skips_pid_reuse_adopted_orphan():
    """⑦-1 原样：47184 api_watchdog.py 的父 pid 被复用到我们树里，但它比“父”早出生 → 不杀；真孙进程照杀；根最后杀"""
    ident = {"pid": 100, "t0": 1000.0, "t1": 1000.5, "argv": ["C:/py/python.exe", "tools/qa/system_version.py"]}
    table = {100: _row(1, 1000.2, "C:/py/python.exe tools/qa/system_version.py cut"),
             200: _row(100, 1001.0, "python.exe -m pytest"),
             300: _row(200, 1002.0, "python.exe worker"),
             47184: _row(200, 500.0, "python.exe tools/factory/api_watchdog.py --by restart_api"),
             999: _row(47184, 600.0, "python.exe child_of_watchdog")}
    pids, refused = SV.kill_plan(ident, table)
    assert pids[-1] == 100 and set(pids) == {100, 200, 300}
    assert 47184 not in pids and 999 not in pids
    assert any("47184" in m and "复用" in m for m in refused)


def test_kill_plan_refuses_impostor_root():
    """根 pid 的创建时间不在启动窗口 / 命令行不是我们起的程序 → 根和它的“子树”都不杀"""
    ident = {"pid": 100, "t0": 1000.0, "t1": 1000.5, "argv": ["C:/py/python.exe", "x.py"]}
    pids, refused = SV.kill_plan(ident, {100: _row(1, 5000.0, "python.exe api_watchdog.py"), 200: _row(100, 5001.0)})
    assert pids == [] and "启动窗口" in refused[0]
    pids, refused = SV.kill_plan(ident, {100: _row(1, 1000.1, "node.exe server.js"), 200: _row(100, 1001.0)})
    assert pids == [] and "命令行" in refused[0]


def test_kill_plan_root_gone_claims_only_later_born_orphans():
    ident = {"pid": 100, "t0": 1000.0, "t1": 1000.5, "argv": ["python.exe"]}
    pids, refused = SV.kill_plan(ident, {200: _row(100, 1001.0), 201: _row(100, 10.0, "python.exe old")})
    assert pids == [200] and any("201" in m for m in refused)


def test_kill_tree_uses_plan_and_never_tree_flag(monkeypatch):
    """_kill_tree 只杀核对过的 pid（桩 killer 收下，不真杀）；根身份不符时只用句柄杀自己的根"""
    class FakePr:
        pid, killed = 100, 0

        def poll(self):
            return None

        def kill(self):
            self.killed += 1
    ident = {"pid": 100, "t0": 1000.0, "t1": 1000.5, "argv": ["python.exe"]}
    got, pr = [], FakePr()
    res = SV._kill_tree(pr, ident, table_fn=lambda: {100: _row(1, 1000.2), 200: _row(100, 1001.0), 7: _row(100, 3.0)},
                        killer=got.extend)
    assert got == [200, 100] and pr.killed == 0 and res["refused"]
    got, pr = [], FakePr()
    SV._kill_tree(pr, ident, table_fn=lambda: {100: _row(1, 9000.0, "python.exe someone_else")}, killer=got.extend)
    assert got == [] and pr.killed == 1
    got, pr = [], FakePr()
    res = SV._kill_tree(pr, ident, table_fn=lambda: None, killer=got.extend)
    assert got == [] and pr.killed == 1 and res["how"] == "handle"


def test_cli_runner_normal_report(tmp_path):
    root = tmp_path / "r"
    (root / "tools/qa").mkdir(parents=True)
    (root / "tools/qa/system_version.py").write_text(
        "import json, sys\nrp = sys.argv[sys.argv.index('--report-json') + 1]\n"
        "json.dump({'ok': True, 'id': 'sv-x', 'dry': '--dry' in sys.argv}, open(rp, 'w'))\n", encoding="utf-8")
    sv = SimpleNamespace(ENV=dict(os.environ), PY=sys.executable, run_watched=SV.run_watched)
    rep = RT.CliRunner(sv, {}, root, poll_s=0.1).cut("deadbeef", dry=True)
    assert rep == {"ok": True, "id": "sv-x", "dry": True, "rc": 0}


# ---------------------------------------------------------------- P1-3
def test_one_group_approved_is_not_enough(repo):
    TA._req(repo, reviews=[{"group": "G2", "verdict": "可入", "p0": []}])
    fr = TA.FakeRunner()
    res = RT.release_once(repo, sv=SV, runner=fr, cfg=TA.CFG)
    assert res["status"] == "not_approved" and fr.calls == []
    assert "缺复审组 G3、G4、G5、G6、G7" in res["reason"] and res["required_groups"] == ["G2", "G3", "G4", "G5", "G6", "G7"]


def test_request_can_add_but_not_remove_groups(repo):
    six = [{"group": f"G{i}", "verdict": "可入", "p0": []} for i in range(2, 8)]
    TA._req(repo, reviews=six, required_groups=["G2"])                      # 想只要 G2：不行，G2–G7 照样要齐 → 齐了就发
    assert RT.release_once(repo, sv=SV, runner=TA.FakeRunner(), cfg=TA.CFG)["status"] == "done"
    TA._req(repo, reviews=six, required_groups=["G8"], at="2")              # 加一组 G8 没审 → 不发
    res = RT.release_once(repo, sv=SV, runner=TA.FakeRunner(), cfg=TA.CFG)
    assert res["status"] == "not_approved" and "G8" in res["reason"]
    TA._req(repo, reviews=six[:2], at="3")                                   # release.json 可改必须齐的组
    assert RT.release_once(repo, sv=SV, runner=TA.FakeRunner(), cfg={**TA.CFG, "required_groups": ["G2", "G3"]})["status"] == "done"
    assert RT.validate_request({"list": "x", "reviews": [{"group": "G2"}], "required_groups": "G2"})


# ---------------------------------------------------------------- P1-5
def test_handover_server_step_failure_stops_before_killing(repo):
    TA._deployed(repo)

    class RS(TA.FakeRS):
        def request_restart(self, host, reason, by="x", urgent=False):
            raise RuntimeError("restart_queue 写不进去")
    rs = RS()
    out = RT.handover_once(repo, apply=True, sv=SV, rs=rs, stage_fn=TA._stage(4),
                           laptop_fn=lambda *a: {"ok": True, "out": "restarted"}, cfg=TA.CFG)
    assert out["ok"] is False and rs.cmds == []                              # 不 probe、不 kill
    ho = json.loads((repo / RT.RES_REL).read_text(encoding="utf-8"))["handover"]
    assert ho["aborted_at"] == "server_restart" and ho["skipped"] == ["stop_legacy"]
    assert [s["id"] for s in ho["steps"]] == ["laptop_producer", "server_restart", "stop_legacy"] and ho["steps"][2]["ok"] is None
    assert [i["step"] for i in TA._issues(repo)] == ["handover:server_restart"]
    assert "失败即停" in (repo / "docs/master/V2_LIVE.md").read_text(encoding="utf-8")


# ---------------------------------------------------------------- P1-4
def test_cut_lock_renew_only_own_active_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(SV, "CUT_LOCK", tmp_path / "cut_lock.json")
    base = {"active": True, "sv": "sv-1", "pid": os.getpid(), "expires_t": time.time() + 5}
    SV.CUT_LOCK.write_text(json.dumps(base))
    assert SV.cut_lock_renew("sv-1") is True
    d = json.loads(SV.CUT_LOCK.read_text())
    assert d["expires_t"] > time.time() + SV.CUT_LOCK_TTL_S - 60 and d["renewed_at"]
    for other in ({**base, "sv": "sv-2"}, {**base, "pid": os.getpid() + 1}, {**base, "active": False}):
        SV.CUT_LOCK.write_text(json.dumps(other))
        assert SV.cut_lock_renew("sv-1") is False and json.loads(SV.CUT_LOCK.read_text()) == other


def _read_lock():
    for _ in range(50):                    # Windows：续期线程 os.replace 的瞬间读会 PermissionError，重试
        try:
            return json.loads(SV.CUT_LOCK.read_text())
        except (PermissionError, ValueError):
            time.sleep(0.02)
    return json.loads(SV.CUT_LOCK.read_text())


def test_cut_lock_renewer_thread_stops(tmp_path, monkeypatch):
    monkeypatch.setattr(SV, "CUT_LOCK", tmp_path / "cut_lock.json")
    SV.CUT_LOCK.write_text(json.dumps({"active": True, "sv": "sv-1", "pid": os.getpid(), "expires_t": time.time() + 1}))
    stop = SV.start_cut_lock_renewer("sv-1", every_s=0.05)
    for _ in range(100):
        if "renewed_at" in _read_lock():
            break
        time.sleep(0.05)
    stop()
    assert SV.cut_locked() is not None
    SV.CUT_LOCK.write_text(json.dumps({"active": False, "sv": "sv-1", "pid": os.getpid()}))
    time.sleep(0.3)
    assert _read_lock()["active"] is False           # stop() 之后不会再盖掉 active=false


# ---------------------------------------------------------------- restart_queue mode
def test_restart_queue_executes_requested_mode(monkeypatch, tmp_path):
    RQ = _load("tools/autopilot/restart_queue.py", "ns_restart_queue_w17b_t")
    monkeypatch.setattr(RQ, "REQ", tmp_path / "req.jsonl")
    monkeypatch.setattr(RQ, "DONE", tmp_path / "done.jsonl")
    monkeypatch.setattr(RQ, "pre_paused", lambda h, rs: None)
    monkeypatch.setattr(RQ, "drain", lambda h, rs: {"drained": True})
    modes = []
    rs = SimpleNamespace(STATE=tmp_path / "st.json", RESTART_MIN_GAP_S=1800, R="/r", PY={"gpu36": "py", "gpu33": "py"},
                         jl=lambda p, d: json.loads(p.read_text()) if p.exists() else d,
                         js=lambda p, o: p.write_text(json.dumps(o)), log=lambda *a: None,
                         ssh=lambda *a, **k: b"ok", restart=lambda h, mode="all": modes.append((h, mode)) or "started")
    RQ.request("gpu36", "lifecycle 出图", "lifecycle", mode="producer-only")
    RQ.request("gpu36", "lifecycle 出图 2", "lifecycle", mode="producer-only")
    r = RQ.process("gpu36", rs=rs, now=10_000.0)
    assert r["ok"] and r["mode"] == "producer-only" and modes == [("gpu36", "producer-only")]
    RQ.request("gpu33", "night", "x", mode="night")                         # 别名 night = night-only
    assert RQ.process("gpu33", rs=rs, now=10_000.0)["mode"] == "night-only" and modes[-1] == ("gpu33", "night-only")
    RQ.request("gpu36", "a", "x", mode="producer-only", urgent=True)
    RQ.request("gpu36", "b", "x", mode="night-only")
    assert RQ.process("gpu36", rs=rs, now=10_001.0)["mode"] == "all"        # 混合 = all
    RQ.request("gpu36", "老请求没写 mode", "x", urgent=True)
    assert RQ.process("gpu36", rs=rs, now=10_002.0)["mode"] == "all"


def test_restart_queue_mode_normalize():
    RQ = _load("tools/autopilot/restart_queue.py", "ns_restart_queue_w17b_t2")
    assert [RQ.norm_mode(x) for x in ("producer-only", "night", "night-only", "all", None, "", "bogus", " producer ")] == \
        ["producer-only", "night-only", "night-only", "all", "all", "all", "all", "producer-only"]
    assert RQ.merged_mode([{"mode": "producer-only"}, {}]) == "all"
