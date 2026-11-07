# 11-07 审计 Step 3 / G4：冒烟夹具剧（kind=smoke）笔记本侧不挂服务器道、不按分区；正式剧不变
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools/netfix"))
import dispatch as D

PART = {"images": {"gpu33": [1, 3], "gpu36": [2, 4], "laptop": []},
        "lanes": {"gpu33": ["gpu33:0", "gpu33:1"], "gpu36": ["gpu36:0"], "laptop": ["laptop:0"]}}
READY = {"episodes": {"1": {"shots": ["ep01-S1", "ep01-S2"]}}}


def _patch(monkeypatch, kind):
    monkeypatch.setattr(D, "is_smoke_run", lambda r: kind == "smoke" and r == "t_run")
    monkeypatch.setattr(D, "read_override", lambda: {})
    monkeypatch.setattr(D, "held_lanes", lambda part, now_t=None: set())
    monkeypatch.setattr(D, "ready_shots", lambda ready: {1: ["ep01-S1", "ep01-S2"]})


def test_smoke_run_gets_server_lanes(monkeypatch):
    _patch(monkeypatch, "smoke")
    f = D.control_for("laptop", {}, READY, PART, ph={}, runs=[], run_id="t_run")
    assert f["hold_lanes"] == [] and f["only"] != [D.NONE]


def test_normal_run_still_holds_server_lanes(monkeypatch):
    _patch(monkeypatch, "normal")
    f = D.control_for("laptop", {}, READY, PART, ph={}, runs=[], run_id="t_run")
    assert set(f["hold_lanes"]) >= {"gpu33:0", "gpu33:1", "gpu36:0"} and f["only"] == [D.NONE]
