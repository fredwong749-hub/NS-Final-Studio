"""资产页母版挑选：被否决 / 已取代的旧母版不能当写实母版（2026-10-30 资产页大图曾显示 master_v1_rejected.png）"""
from ns_api.assets import classify


def test_archived_plates_are_not_master():
    assert classify(None, ("plates", "master.png"), "master") == ("plate", "master")
    for stem in ("master_v1_rejected", "master_v2_CL_s0_superseded", "front_retired"):
        assert classify(None, ("plates", f"{stem}.png"), stem) == ("other", "plate_archived")
        assert classify("plate/master", ("x", f"{stem}.png"), stem) == ("other", "plate_archived")


def test_non_plate_names_untouched():
    # 单品 / 表情里带这些字的不受影响（只管 plates）
    assert classify(None, ("items", "shoes", "rejected_pair.png"), "rejected_pair")[0] == "item"
