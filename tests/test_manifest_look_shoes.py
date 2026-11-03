import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "agent"))
from ns_agent import asset_refs as AR


def test_manifest_look_item_slot(monkeypatch):
    m = {"characters": {"c": {"looks": {"X": {"name": "裙", "items": {
        "X_g": {"name": "黑色短裙", "file": "a.png"}, "SH": {"name": "透明高跟", "slot": "shoes", "file": "b.png"}}}}}}}
    monkeypatch.setattr(AR, "manifest", lambda p: m)
    monkeypatch.setattr(AR, "manifest_rel", lambda p: "x")
    parts = AR.manifest_looks("p")["c"]["X"].parts
    got = {p.item_id: (p.slot, p.zone) for p in parts}
    assert got["SH"] == ("shoes", "feet") and got["X_g"][0] == "outfit"
