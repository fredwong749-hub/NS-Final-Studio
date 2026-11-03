"""W22 TEST-HERMETIC（ISS-1103-145040）：cut 闸门记全部 FAILED 行 + 完整输出落盘；串行 pytest 不判僵死；
\\r\\n 输出下 flaky 串行重跑真的执行；测试进程不许连网（tests/conftest.py 网络守卫）。"""
import importlib.util
import os
import socket
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("system_version_w22", ROOT / "tools/qa/system_version.py")
SV = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SV)


def _guard():
    return next(m for m in list(sys.modules.values()) if getattr(m, "_NET_STATE", None) is not None and hasattr(m, "NET_VIOLATIONS"))


# ---------------------------------------------------------------- 网络守卫
def test_net_guard_blocks_service_ports_and_counts():
    G = _guard()
    n0 = len(G.NET_VIOLATIONS)
    for addr in (("127.0.0.1", 8870), ("127.0.0.1", 8871), ("127.0.0.1", 18188), ("10.0.0.36", 8893)):
        s = socket.socket()
        try:
            with pytest.raises(RuntimeError, match="不许连网"):
                s.connect(addr)
            with pytest.raises(RuntimeError):
                s.connect_ex(addr)
        finally:
            s.close()
    got = G.NET_VIOLATIONS[n0:]
    assert len(got) == 8 and got[0]["addr"] == "127.0.0.1:8870" and got[0]["test"].endswith("test_net_guard_blocks_service_ports_and_counts")
    del G.NET_VIOLATIONS[n0:]          # 本用例故意触发的不算进会话合计


def test_net_guard_allows_in_process_fake_server_and_8800():
    G = _guard()
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    port = srv.getsockname()[1]
    c = socket.create_connection(("127.0.0.1", port), timeout=5)
    c.close()
    srv.close()
    assert G._net_allowed(("127.0.0.1", 8800)) and G._net_allowed("/tmp/x.sock")
    assert not G._net_allowed(("localhost", 8870)) and not G._net_allowed(("gpu33", 22))


@pytest.mark.live
def test_live_marker_is_skipped_by_default():
    raise AssertionError("live 用例默认不该跑")


# ---------------------------------------------------------------- 闸门输出口径
WIN_OUT = ("....F..\r\n=========================== short test summary info ===========================\r\n"
           "FAILED tests/test_v2cut_o.py::test_ref_switch_only_registered_scenes_for_v2\r\n"
           "FAILED tests/test_b.py::test_x - AssertionError: boom\r\n"
           "2 failed, 1933 passed, 1 skipped, 30 warnings in 1427.25s (0:23:47)\r\n")


def test_failed_ids_handle_crlf_and_missing_reason():
    assert SV.failed_ids(WIN_OUT) == ["tests/test_b.py::test_x", "tests/test_v2cut_o.py::test_ref_switch_only_registered_scenes_for_v2"]
    assert len(SV.failed_lines(WIN_OUT)) == 2
    assert SV.summary_line(WIN_OUT).startswith("2 failed, 1933 passed")


def _stub_gates(monkeypatch, watch_out, rerun_code):
    monkeypatch.setenv("NS_CUT_PYTEST_N", "4")
    seen = {"watch": [], "sh": []}

    def fake_sh(cmd, timeout=1800, cwd=None, env=None):
        seen["sh"].append(cmd)
        if any("decision_check.py" in c for c in cmd):
            return 0, "合计 2：✅ 2  ❌ 0  ⏳ 0"
        if "pytest" in cmd:
            return rerun_code, ("2 passed in 3s" if rerun_code == 0 else "FAILED tests/test_b.py::test_x - boom\n1 failed, 1 passed in 3s")
        return 0, "ok"

    def fake_watch(cmd, timeout, cwd=None, env=None, stall_s=600, **kw):
        seen["watch"].append((cmd, stall_s))
        return 1, watch_out, {"stalled": False}
    monkeypatch.setattr(SV, "sh", fake_sh)
    monkeypatch.setattr(SV, "run_watched", fake_watch)
    return seen


def test_gates_flaky_rerun_runs_on_crlf_output_and_log_written(monkeypatch, tmp_path):
    seen = _stub_gates(monkeypatch, WIN_OUT, 0)
    py = {r["id"]: r for r in SV.gates([], run_tests=True, sv="sv-test-01", log_dir=tmp_path)}["pytest"]
    rerun = [c for c in seen["sh"] if "pytest" in c]
    assert rerun and "tests/test_v2cut_o.py::test_ref_switch_only_registered_scenes_for_v2" in rerun[0]   # dry #9：这次真的重跑了
    assert "-rf" in seen["watch"][0][0] and "-rf" in rerun[0]
    assert py["ok"] and py["flaky"] == SV.failed_ids(WIN_OUT)
    assert "flaky" in py["detail"] and "FAILED tests/test_b.py::test_x - AssertionError: boom" in py["detail"]
    assert "2 failed, 1933 passed" in py["detail"]
    f = tmp_path / "sv-test-01_pytest_1.txt"
    assert f.exists() and "串行重跑" in f.read_text(encoding="utf-8") and str(f) in py["log"] and py["log"] in py["detail"]
    SV.gates([], run_tests=True, sv="sv-test-01", log_dir=tmp_path)
    assert (tmp_path / "sv-test-01_pytest_2.txt").exists()                                              # dry / 正式各留一份


def test_gates_real_failure_lists_all_failed_lines(monkeypatch, tmp_path):
    _stub_gates(monkeypatch, WIN_OUT, 1)
    py = {r["id"]: r for r in SV.gates([], run_tests=True, sv="sv-test-02", log_dir=tmp_path)}["pytest"]
    assert not py["ok"] and py["flaky"] == [] and len(py["failed"]) == 2
    assert py["detail"].count("FAILED ") >= 2 and "串行重跑仍不过" in py["detail"] and py["rerun"]["still_failed"] == ["tests/test_b.py::test_x"]


def test_gates_serial_never_stall_killed(monkeypatch):
    monkeypatch.setenv("NS_CUT_PYTEST_N", "0")
    monkeypatch.setattr(SV, "sh", lambda cmd, timeout=1800, cwd=None, env=None: (0, "合计 2：✅ 2  ❌ 0  ⏳ 0"))
    seen = []
    monkeypatch.setattr(SV, "run_watched", lambda cmd, timeout, stall_s=600, **kw: seen.append(stall_s) or (0, "3 passed in 1s", {"stalled": False}))
    SV.gates([], run_tests=True)
    assert seen == [None]
    monkeypatch.setenv("NS_CUT_PYTEST_N", "4")
    seen.clear()
    SV.gates([], run_tests=True)
    assert seen and seen[0] and seen[0] > 0                                                            # xdist 仍有僵死自愈


def test_run_watched_none_window_only_timeout():
    code, out, info = SV.run_watched([sys.executable, "-c", "import time; time.sleep(1.5); print('done')"], 60, stall_s=None,
                                     poll_s=0.1, cpu_fn=lambda pid: 0.0)
    assert code == 0 and "done" in out and not info["stalled"]


def test_run_watched_output_growth_is_not_stall():
    prog = "import time,sys\nfor i in range(20):\n    print('.', flush=True); time.sleep(0.3)\nprint('ok')"
    t0 = time.time()
    code, out, info = SV.run_watched([sys.executable, "-u", "-c", prog], 60, stall_s=3.0, poll_s=0.1, cpu_fn=lambda pid: 0.0)
    assert not info["stalled"] and code == 0 and "ok" in out and time.time() - t0 < 40   # CPU 不动但一直有输出 = 不是僵死


# ---------------------------------------------------------------- W22 P0：进程守卫（tools/qa/proc_guard.py）
sys.path.insert(0, str(ROOT / "tools" / "qa"))
import proc_guard as PG  # noqa: E402


def test_proc_guard_parses_kill_commands():
    assert PG.kill_targets(["taskkill", "/PID", "123", "/T", "/F"]) == ([123], None)
    assert PG.kill_targets("taskkill.exe /F /IM python.exe")[1]
    assert PG.kill_targets(["powershell.exe", "-NoProfile", "-Command", "Stop-Process -Id 77 -Force"]) == ([77], None)
    assert PG.kill_targets(["powershell", "-Command", "Stop-Process -Name python"])[1]
    assert PG.kill_targets(["pkill", "-f", "x"])[1] and PG.kill_targets(["kill", "-9", "55"]) == ([55], None)
    assert PG.kill_targets(["git", "status"]) == ([], None)


def test_proc_guard_ownership_rules():
    me = os.getpid()
    table = {500: (1, "python tools/factory/autoflow_resident.py --interval 30"),       # 生产常驻
             600: (me, "python fake.py"), 601: (600, "python grandchild.py"),            # 本进程子孙
             700: (1, r"python C:\Users\x\AppData\Local\Temp\pytest-of-x\pytest-1\t0\app.py"),
             801: (999999, "python orphan_of_own.py")}
    PG.OWN.add(999999)
    try:
        assert not PG.pid_is_ours(500, table)[0]
        assert PG.pid_is_ours(600, table)[0] and PG.pid_is_ours(601, table)[0] and PG.pid_is_ours(700, table)[0]
        assert PG.pid_is_ours(801, table)[0]                      # 父进程（本进程起的启动器）已退出：ppid 仍认得
        assert PG.pid_is_ours(424242, table)[0]                   # 已不存在 = 杀不到任何东西
    finally:
        PG.OWN.discard(999999)


def test_proc_guard_blocks_foreign_kill_and_counts(monkeypatch):
    import subprocess
    assert PG._STATE["orig"] is not None, "conftest 没装进程守卫"
    monkeypatch.setattr(PG, "_proc_table", lambda: {4242: (1, "python tools/factory/autoflow_resident.py")})
    n0 = len(PG.VIOLATIONS)
    with pytest.raises(RuntimeError, match="不许杀别人的进程"):
        subprocess.run(["taskkill", "/PID", "4242", "/T", "/F"], capture_output=True, timeout=30)
    with pytest.raises(RuntimeError):
        os.kill(4242, 9)
    got = PG.VIOLATIONS[n0:]
    assert len(got) == 2 and got[0]["test"].endswith("test_proc_guard_blocks_foreign_kill_and_counts")
    del PG.VIOLATIONS[n0:]                                       # 本用例故意触发的不算进会话合计


def test_proc_guard_allows_killing_own_child():
    import subprocess
    p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)"])
    assert p.pid in PG.OWN
    if os.name == "nt":
        subprocess.run(["taskkill", "/PID", str(p.pid), "/T", "/F"], capture_output=True, timeout=30)
    else:
        os.kill(p.pid, 9)
    p.wait(timeout=30)


def test_snapshot_skips_live_pid_files(tmp_path):
    src, dst = tmp_path / "data", tmp_path / "snap"
    (src / "factory").mkdir(parents=True)
    for f in ("autoflow_resident.lock", "autoflow_resident.json", "api_8800.pid.json", "api_preflight.pid", "keep.json"):
        (src / "factory" / f).write_text("{}", encoding="utf-8")
    SV._hardlink_tree(src, dst)
    assert sorted(p.name for p in (dst / "factory").iterdir()) == ["keep.json"]


def test_proc_guard_tree_kill_refuses_pid_reuse_orphans():
    """父 pid 被复用：resident（13:57 出生，ppid=42668）挂在本测试 15:30 起的新 42668 下面，taskkill /T 42668 会带走它"""
    table = {42668: (os.getpid(), "python fake_child.py"), 25996: (42668, "python tools/factory/autoflow_resident.py"),
             50001: (42668, "python grandchild.py")}
    born = {42668: 2000, 25996: 1000, 50001: 3000}
    assert PG.adopted_by_reuse(42668, table, born) == [25996]
