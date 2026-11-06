"""PS-MASTER 11-06（L-202 卡不能空）：过期 hold 不挡；retired 但队列空的道可用"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools/pipeline"), str(ROOT)]
import asset_worker as AW  # noqa: E402


class H:
    @staticmethod
    def lanes(role="image"):
        return ["gpu33:0", "gpu33:2", "gpu36:1", "gpu36:2"]


def _iso(t):
    from datetime import datetime, timedelta, timezone   # L-209 S2.3：分区 hold 时间一律 JST 串（tools/netfix/partition.jst）
    return datetime.fromtimestamp(t, timezone(timedelta(hours=9))).strftime("%Y-%m-%dT%H:%M:%S")


def test_expired_hold_and_retired_idle_lane_are_free(monkeypatch):
    monkeypatch.setattr(AW, "broken_lanes", lambda h: {"gpu33:2"})
    monkeypatch.setattr(AW, "_lanes_mod", lambda: None)
    part = {"retired_lanes": ["gpu36:1", "gpu36:2", "gpu33:0"],
            "_temp_holds": {"gpu36:1": {"by": "MASTER-WSL", "expires_at": _iso(time.time() - 3600)},
                            "gpu33:0": {"by": "MASTER-WSL", "expires_at": _iso(time.time() + 3600)}}}
    out = AW.free_lanes({}, set(), part=part, probe=lambda l: {"ok": True, "busy": False}, hosts_mod=H)
    assert out == ["gpu36:1", "gpu36:2"]          # 过期 hold 放开；未过期的别人 hold 仍挡；坏卡不用


def test_busy_lane_still_skipped(monkeypatch):
    monkeypatch.setattr(AW, "broken_lanes", lambda h: set())
    monkeypatch.setattr(AW, "_lanes_mod", lambda: None)
    out = AW.free_lanes({}, set(), part={"retired_lanes": ["gpu36:2"]},
                        probe=lambda l: {"ok": True, "busy": l == "gpu36:2"}, hosts_mod=H)
    assert "gpu36:2" not in out
