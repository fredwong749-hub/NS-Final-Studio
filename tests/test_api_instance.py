"""RESTARTFIX-O（ISS-1103-011049-7420，总调度 P0）：启动副作用只在看门狗管理的正式实例上跑。

事故：SENTINEL S10 → tools/qa/decision_check.py 的 pinned_api 每 10 分钟用 TestClient(ns_api.app) 起一份进程内 app（真实 data/），
跑完全部 startup（JOBS.restore / 恢复 / owner_pick replay / postflight 扫描），活 45–60 s（api_lifecycle 00:18 / 00:28 / … / 01:10）。
全部用临时目录 / 子进程只导入不跑 startup，不碰真实数据。
"""
from __future__ import annotations

import http.server
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "tools/factory"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import instance as INST  # noqa: E402


def _fresh(monkeypatch, tmp_path, env: dict):
    """重置判定缓存 + 锁路径换到临时目录；去掉 pytest 痕迹，按给定环境判定"""
    monkeypatch.setattr(INST, "_DECIDED", {})
    monkeypatch.setattr(INST, "_LOCK_FH", None)
    monkeypatch.setattr(INST, "_lock_path", lambda: tmp_path / "api_primary_8800.lock")
    monkeypatch.delitem(sys.modules, "pytest", raising=False)
    for k in ("PYTEST_CURRENT_TEST", "NS_API_PREFLIGHT", "NS_API_MANAGED"):
        monkeypatch.delenv(k, raising=False)
    for k, v in env.items():
        monkeypatch.setenv(k, v)


def test_unmanaged_instances_get_no_side_effects(monkeypatch, tmp_path):
    """没有 NS_API_MANAGED=1（TestClient / 手起 uvicorn / 进程内导入）、预检、pytest → 都不放行"""
    _fresh(monkeypatch, tmp_path, {})
    assert not INST.startup_side_effects_allowed() and "NS_API_MANAGED" in INST.why_not()
    _fresh(monkeypatch, tmp_path, {"NS_API_MANAGED": "1", "NS_API_PREFLIGHT": "1"})
    assert "预检" in INST.why_not()
    _fresh(monkeypatch, tmp_path, {"NS_API_MANAGED": "1", "PYTEST_CURRENT_TEST": "x"})
    assert INST.why_not() == "pytest"


def test_managed_instance_takes_single_instance_lock(monkeypatch, tmp_path):
    """正式实例拿单实例锁；同端口第二份（锁被持有）不放行"""
    _fresh(monkeypatch, tmp_path, {"NS_API_MANAGED": "1"})
    assert INST.why_not() is None and INST.startup_side_effects_allowed()
    held = INST._LOCK_FH
    try:
        monkeypatch.setattr(INST, "_DECIDED", {})
        monkeypatch.setattr(INST, "_LOCK_FH", None)
        assert "单实例锁" in INST.why_not()            # 第二个句柄拿不到锁
    finally:
        held.close()


def test_holds_port_checks_own_token(monkeypatch):
    """holds_port：:port 上回的 token 是本进程的才算“自己在服务”；别的实例占着端口 → False"""
    tok = {"v": INST.TOKEN}

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps({"token": tok["v"]}).encode())

        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        monkeypatch.setenv("NS_API_PORT", str(srv.server_address[1]))
        assert INST.holds_port(timeout_s=2)
        tok["v"] = "someone-else"
        assert not INST.holds_port(timeout_s=1.5, sleep=lambda s: None)
    finally:
        srv.shutdown()


def test_watchdog_marks_child_managed(tmp_path):
    """看门狗起的子进程：NS_API_MANAGED=1、NS_API_PORT=--port，且去掉 NS_API_PREFLIGHT"""
    import api_watchdog as W
    env = W.child_env(["-m", "uvicorn", "ns_api.app:app", "--port", "8800"], base={"NS_API_PREFLIGHT": "1", "X": "y"})
    assert env["NS_API_MANAGED"] == "1" and env["NS_API_PORT"] == "8800" and "NS_API_PREFLIGHT" not in env and env["X"] == "y"
    seen = {}

    class P_:
        pid = 1

        def wait(self):
            return 0

    def popen(cmd, **k):
        seen.update(k)
        return P_()
    orig = W.LOG
    W.LOG = tmp_path / "lc.jsonl"
    try:
        W.run(["-m", "x", "--port", "8801"], "TEST", popen=popen)
    finally:
        W.LOG = orig
    assert seen["env"]["NS_API_MANAGED"] == "1" and seen["env"]["NS_API_PORT"] == "8801"


def test_inprocess_app_import_registers_no_side_effects():
    """复现 decision_check 的进程内导入（没有 NS_API_MANAGED）：JOBS.restore / EPROD.resume_on_startup 不挂，
    owner_pick 启动补执行不起线程，postflight 扫描不起；只导入、不跑 startup（不写真实留痕）"""
    code = ("import ns_render.unified_frame as U\nsw = []\nU.start_sweeper = lambda *a, **k: sw.append(1)\n"
            "from ns_api import app as A\nfrom ns_api import jobs, episode_produce as E, owner_pick as OP, instance as I\n"
            "th = []\nOP.start_replay_thread = lambda *a, **k: th.append(1)\nOP._replay_on_startup()\n"
            "fs = list(A.app.router.on_startup)\n"
            "print('R', int(jobs.restore in fs), int(E.resume_on_startup in fs), len(th), len(sw), I.why_not() is not None)")
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(str(ROOT / p) for p in ("services/api", "services/render_router", "services/agent", "packages")),
               PYTHONIOENCODING="utf-8", NS_NO_API_SNAPSHOT="1")
    for k in ("PYTEST_CURRENT_TEST", "NS_API_PREFLIGHT", "NS_API_MANAGED", "NS_POSTFLIGHT_SWEEP"):
        env.pop(k, None)
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, env=env, cwd=str(ROOT), timeout=170)
    line = [x for x in r.stdout.splitlines() if x.startswith("R ")]
    assert line and line[-1] == "R 0 0 0 0 True", (r.stdout[-300:], r.stderr[-800:])


def test_decision_check_is_the_ten_minute_source_and_now_harmless():
    """来源核对：decision_check 的 pinned_api 用 TestClient（会跑 startup）；它的子进程不带 NS_API_MANAGED → 启动副作用全不跑"""
    src = (ROOT / "tools/qa/decision_check.py").read_text(encoding="utf-8")
    assert "TestClient(app)" in src and "NS_API_MANAGED" not in src
    app_src = (ROOT / "services/api/ns_api/app.py").read_text(encoding="utf-8")
    assert "_PREFLIGHT = _PREFLIGHT or not _SIDE_EFFECTS" in app_src
    auto = (ROOT / "ops/autostart/laptop_autostart.ps1").read_text(encoding="utf-8-sig")
    assert "tools/factory/api_watchdog.py" in auto, "开机自启也要经看门狗起（否则正式实例没有 NS_API_MANAGED）"


def test_snapshot_writes_only_on_formal_instance(monkeypatch, tmp_path):
    """ISS-1103-014614-86aa：非正式实例（TestClient / 进程内导入 / 手起）不写 data/cache/api_snapshots；正式实例写"""
    from ns_api import api_snapshot as S
    _fresh(monkeypatch, tmp_path, {})
    monkeypatch.delenv("NS_NO_API_SNAPSHOT", raising=False)
    assert S.in_tests() is True
    _fresh(monkeypatch, tmp_path, {"NS_API_MANAGED": "1"})
    monkeypatch.delenv("NS_NO_API_SNAPSHOT", raising=False)
    try:
        assert S.in_tests() is False
    finally:
        if INST._LOCK_FH:
            INST._LOCK_FH.close()
    dc = (ROOT / "tools/qa/decision_check.py").read_text(encoding="utf-8")
    assert '"NS_DISABLE_BG": "1"' not in dc and '"NS_NO_API_SNAPSHOT": "1"' in dc


def test_single_instance_lock_follows_data_dir(monkeypatch, tmp_path):
    """ISS-1103-014614-9db2(4)：单实例锁跟 ns_render.pipeline.DATA 走，测试换数据目录不会碰真锁"""
    from ns_render import pipeline as P
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setenv("NS_API_PORT", "8899")
    assert INST._lock_path() == tmp_path / "data" / "ops" / "api_primary_8899.lock"


def test_guard_api_up_timeout_covers_season_first_wait():
    """ISS-1103-014614-9db2(5)：api_up 单次超时 ≥ SEASON_FIRST_WAIT_S + 余量，不把正在首算 /api/season 的 API 误报为挂了"""
    sys.path.insert(0, str(ROOT / "tools" / "uirsi"))
    import api_restart_guard as G
    from ns_api import season
    assert G.API_UP_TIMEOUT_S >= float(season.SEASON_FIRST_WAIT_S) + 5
