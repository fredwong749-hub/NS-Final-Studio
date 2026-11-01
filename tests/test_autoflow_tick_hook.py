"""DISTILL 编排器每拍挂进 resident_sync loop（WORKFLOW 11-02；K-OPS-W22）。
- autoflow_tick_once：跑子进程、输出写文件、超时杀进程树并返回 rc=timeout；
- loop 启动时起独立守护线程（不拖住推送循环）。全部用假命令，不碰生产。"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
import resident_sync as RS  # noqa: E402


def _fake_run(monkeypatch, tmp_path, body):
    script = tmp_path / "tools/autopilot/run.py"
    script.parent.mkdir(parents=True)
    script.write_text(body, encoding="utf-8")
    monkeypatch.setattr(RS, "ROOT", tmp_path)


def test_tick_ok(monkeypatch, tmp_path):
    _fake_run(monkeypatch, tmp_path, "import sys\nprint('{\"tick\": %r}' % sys.argv[1:])\n")
    r = RS.autoflow_tick_once(timeout_s=60, dry=True)
    assert r["rc"] == 0 and "tick" in r["tail"] and "--dry-run" in r["tail"]


def test_tick_timeout_kills(monkeypatch, tmp_path):
    _fake_run(monkeypatch, tmp_path, "import time\ntime.sleep(60)\n")
    t0 = time.time()
    r = RS.autoflow_tick_once(timeout_s=2)
    assert r["rc"] == "timeout" and time.time() - t0 < 40


def test_loop_starts_thread():
    src = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    body = src.split("def loop(", 1)[1].split("\ndef ", 1)[0]
    assert "threading.Thread(target=autoflow_thread" in body and "daemon=True" in body
    assert RS.AUTOFLOW_EVERY_S == 60 and RS.AUTOFLOW_TICK is True


def test_three_parts_threads_and_core_merges(monkeypatch, tmp_path):
    """04:2x：一拍拆成 core / line3 / api 三条线各自线程；core 每拍写 last_tick 并并入另两条线最近结果，不等它们"""
    src = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    body = src.split("def loop(", 1)[1].split("\ndef ", 1)[0]
    assert "for part in AUTOFLOW_PARTS" in body and set(RS.AUTOFLOW_PARTS) == {"core", "line3", "api"}
    import tick_parts as TP
    calls = []
    monkeypatch.setattr(TP.FL, "status_all", lambda root, write=True: {"at": "x", "blockers": [], "global": {}})
    monkeypatch.setattr(TP.FL, "coverage", lambda root, write=True: {})
    monkeypatch.setattr(TP.FL, "autoflow_tick", lambda root, apply=True: calls.append("af") or {"ran": []})
    monkeypatch.setattr(TP.FL, "line3_tick", lambda *a, **k: (_ for _ in ()).throw(AssertionError("core 不许等 line3")))
    monkeypatch.setattr(TP.FL, "api_restart_tick", lambda *a, **k: (_ for _ in ()).throw(AssertionError("core 不许等 api")))
    out = tmp_path / "data/autopilot/flow"
    out.mkdir(parents=True)
    (out / "api_restart_tick.json").write_text('{"at": "t0", "result": {"status": "busy"}}', encoding="utf-8")
    r = TP.run_part("core", root=tmp_path)
    assert r["part"] == "core" and calls == ["af"]
    import json as _j
    st = _j.loads((out / "status.json").read_text(encoding="utf-8"))
    assert st["global"]["api_restart"] == {"status": "busy"} and st["global"]["last_tick"]["dry"] is False
    assert (out / "last_tick.json").is_file()
