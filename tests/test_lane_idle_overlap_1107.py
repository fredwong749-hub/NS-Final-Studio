"""11-07：L-207 下 active 集没活给的道，空闲 ≥ idle_overlap_s 后可接下一集首尾帧（不空卡）"""
import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))


def test_lanes_allowed_has_idle_overlap():
    import producer as PR
    src = inspect.getsource(PR.Producer.lanes_allowed)
    assert "idle_overlap_s" in src and "lane_idle_overlap" in src


def test_idle_overlap_grants_after_grace(monkeypatch):
    import producer as PR
    t = {"v": 1000.0}
    monkeypatch.setattr(PR, "now", lambda: t["v"])

    class LR:
        @staticmethod
        def lanes_minus_resident_review(free, cfg):
            return list(free), None

        @staticmethod
        def wait_reason(act, ep):
            return "x"
    monkeypatch.setattr(PR, "_lane_roles", lambda: LR)
    p = PR.Producer.__new__(PR.Producer)
    p._lr_cfg = {"enabled": True, "idle_overlap_s": 120}
    p._lr_phases = {}
    p.image_lanes_allowed = lambda ep: set()
    p.logf = lambda *a, **k: None
    o = {"id": "first:ep04-S1", "ep": 4}
    assert p.lanes_allowed(o, ["gpu36:0"]) == []          # 刚空：不给
    t["v"] += 121
    assert p.lanes_allowed(o, ["gpu36:0"]) == ["gpu36:0"]  # 空满 120 s：给
    p._lr_cfg["idle_overlap_s"] = 0
    assert p.lanes_allowed(o, ["gpu36:0"]) == []          # 关掉：不给
