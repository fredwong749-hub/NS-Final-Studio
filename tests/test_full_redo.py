"""L-088 全量重做脚本（K-OPS-W08，WORKFLOW）：前置闸门没全过绝不派单；G21 自动核“剧本导入后已重编作业”；
apply 逐镜记状态、已派的跳过（可续跑）。全部打桩，不连服务器、不写真实 data/。"""
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/autopilot"))
import full_redo as FR  # noqa: E402


def _setup(monkeypatch, tmp_path, gates=()):
    monkeypatch.setattr(FR, "GATES", tmp_path / "gates.json")
    monkeypatch.setattr(FR, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(FR, "PLAN", tmp_path / "plan.json")
    monkeypatch.setattr(FR, "ROOT", tmp_path)
    (tmp_path / "data/import").mkdir(parents=True)
    (tmp_path / "data/pipeline/runs/series10_v1/assets").mkdir(parents=True)
    (tmp_path / "data/import/script_v2.json").write_text("{}")
    (tmp_path / "data/pipeline/runs/series10_v1/assets/first_frame_jobs.json").write_text("{}")
    FR.js(FR.GATES, {g: {"ok": True, "by": "t"} for g in gates})
    monkeypatch.setattr(FR, "g21_check", lambda run_dir: {"ok": True})        # 真实核对见 tests/test_image_jobs_import.py
    FR.js(FR.PLAN, {"shots": [{"shot": "ep01-S3", "ep": 1, "host": "gpu33", "current_first": 4},
                              {"shot": "ep02-S1", "ep": 2, "host": "gpu36", "current_first": 6}]})


def test_apply_refuses_without_all_gates(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, gates=["G20", "G21", "W5", "PIKA_SMOKE"])      # 缺 SCRIPT
    r = FR.apply()
    assert r["ok"] is False and r["gates"]["SCRIPT"]["ok"] is False


def test_g21_auto_check_jobs_newer_than_script(monkeypatch, tmp_path):
    """K-OPS-Q24（RSI 11-01）：G21 不比修改时间，核对镜头集合 + 提示词来源 sha（作业比剧本新也可能是旧来源编的）"""
    _setup(monkeypatch, tmp_path, gates=FR.GATE_IDS)
    monkeypatch.setattr(FR, "g21_check", lambda run_dir: {"ok": False, "missing": ["ep01-S8"], "extra": [], "stale_sha": ["ep01-S1"]})
    st = FR.gates_status()["G21"]
    assert st["ok"] is False and "缺 1 镜" in st["auto"] and "sha 过期 1 条" in st["auto"] and not FR.gates_ok()
    monkeypatch.setattr(FR, "g21_check", lambda run_dir: {"ok": True})
    assert FR.gates_ok()


def test_apply_resumable(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path, gates=FR.GATE_IDS)
    import resident_sync as RS
    calls = []
    monkeypatch.setattr(RS, "ssh", lambda host, cmd, **kw: calls.append((host, cmd)) or b"")
    assert FR.apply(executor="server")["sent"] == 2
    assert "'first:ep01-S3' '--n' '4'" in calls[0][1] and calls[0][0] == "gpu33"
    assert FR.apply(executor="server")["sent"] == 0                                                 # 已派的跳过
    st = json.loads(FR.STATE.read_text(encoding="utf-8"))
    assert set(st["done"]) == {"first:ep01-S3", "first:ep02-S1"}
