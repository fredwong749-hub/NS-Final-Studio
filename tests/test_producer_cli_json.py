"""producer.py status --json / regen --dry 单测（临时目录，不碰真数据）。"""
from __future__ import annotations

import importlib.util
import json
import sys
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
spec = importlib.util.spec_from_file_location("producer_cli_t", ROOT / "tools/autopilot/producer.py")
PR = importlib.util.module_from_spec(spec)
spec.loader.exec_module(PR)


def mk(tmp: Path):
    paths = PR.Paths(root=tmp, pd=tmp / "pd", run_id="r1")
    (tmp / "pd").mkdir(parents=True)
    (tmp / "pd/registry.json").write_text(json.dumps({"counts": {"x": 1}, "episodes": [
        {"ep": 1, "headline": "h", "shots": [{"shot": "ep01-S1", "objects": {"first": {"status": "passed"}}},
                                              {"shot": "ep01-S2", "objects": {"first": {"status": "ready", "waiting_for": "空闲道"}}}]},
        {"ep": 2, "headline": "h2", "shots": []}]}), encoding="utf-8")
    (tmp / "pd/control.json").write_text(json.dumps({"paused": False, "hold_lanes": ["gpu36:0"]}), encoding="utf-8")
    (tmp / "pd/heartbeat.json").write_text(json.dumps({"ts": "2026-11-05T10:00:00"}), encoding="utf-8")
    (tmp / "data/autopilot").mkdir(parents=True)
    (tmp / "data/autopilot/pause_hold.json").write_text(json.dumps({"shots": [{"shot": "ep01-S2"}, {"shot": "ep01-S3", "released": True}]}), encoding="utf-8")
    return paths


def test_status_json(tmp_path):
    d = PR.status_json(mk(tmp_path), 1)
    assert [e["ep"] for e in d["episodes"]] == [1]
    assert d["episodes"][0]["shots"][1] == {"shot": "ep01-S2", "first": "ready", "why": "空闲道"}
    assert d["hold_lanes"] == ["gpu36:0"] and d["heartbeat"] == "2026-11-05T10:00:00"
    assert [x["shot"] for x in d["pause_hold"]] == ["ep01-S2"] and d["runaway_hold"] == []
    json.dumps(d)


def test_regen_dry_writes_nothing(tmp_path, monkeypatch):
    paths = mk(tmp_path)
    fake = types.ModuleType("ns_render.pipeline")
    fake.load_takes = lambda sid: {"active": {"image": 1}}
    pkg = types.ModuleType("ns_render")
    pkg.pipeline = fake
    monkeypatch.setitem(sys.modules, "ns_render", pkg)
    monkeypatch.setitem(sys.modules, "ns_render.pipeline", fake)
    r = PR.regen_cmd(paths, 1, [], "t", "tester", None, dry=True)
    assert r["regen"] == ["ep01-S1", "ep01-S2"] and r["dry"] is True and r["at"]
    assert not (tmp_path / "pd/master_rejects.json").exists()
    assert not (tmp_path / "pd/log.jsonl").exists()
