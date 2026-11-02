"""DETECT-S：tools/vqa/anomaly.py 的判定纯函数（人数 / 头数 / 镜像 / 同一人两次 / 手脚）。不连远端。"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from tools.vqa import anomaly as A  # noqa: E402

CAST2 = [{"name": "林晚", "presence": "在画"}, {"name": "陈宇", "presence": "在画"}]


def _v(seed: int, n: int = 8):
    import random
    r = random.Random(seed)
    return [r.uniform(-1, 1) for _ in range(n)]


def face(emb, box, sims=None, score=0.9):
    return {"box": box, "score": score, "emb": emb, "sims": sims or {}}


def feat(faces, mirror=None, **kw):
    return {"W": 1000, "H": 1000, "faces": faces, "mirror": mirror, "persons": [], "hands": [], "dw": [], **kw}


A_, B_ = _v(1), _v(2)


def test_two_people_clean():
    f = feat([face(A_, [100, 100, 200, 220], {"lin_wan": 0.8}), face(B_, [500, 100, 600, 220], {"chen_yu": 0.6})])
    r = A.judge(f, CAST2)
    assert r["verdict"] == "clean" and not r["defects"]


def test_duplicate_person_outside_mirror():
    f = feat([face(A_, [100, 100, 200, 220], {"lin_wan": 0.8}), face(B_, [500, 100, 600, 220], {"chen_yu": 0.6}),
              face(B_, [500, 500, 600, 620], {"chen_yu": 0.52})])
    r = A.judge(f, CAST2)
    assert r["verdict"] == "hit" and r["defects"][0]["code"] == "duplicate_person"


def test_mirror_head_allowed_when_it_is_a_present_person():
    mask = {"W": 1000, "H": 1000, "rows": ["0" * 5 + "1" * 5] * 10}      # 右半边是镜子
    f = feat([face(A_, [100, 100, 200, 220]), face(B_, [100, 400, 200, 520]), face(A_, [700, 100, 800, 220])], mask)
    r = A.judge(f, CAST2)
    assert r["metrics"]["heads_mirror"] == 1 and r["verdict"] == "clean"


def test_mirror_head_stranger_flagged():
    mask = {"W": 1000, "H": 1000, "rows": ["0" * 5 + "1" * 5] * 10}
    f = feat([face(A_, [100, 100, 200, 220]), face(B_, [100, 400, 200, 520]), face(_v(99), [700, 100, 800, 220])], mask)
    r = A.judge(f, CAST2)
    assert r["verdict"] == "hit" and r["defects"][0]["code"] == "extra_head"


def test_extra_head_not_same_person():
    f = feat([face(A_, [100, 100, 200, 220]), face(B_, [500, 100, 600, 220]), face(_v(7), [800, 100, 900, 220])])
    r = A.judge(f, CAST2)
    assert any(d["code"] == "extra_head" for d in r["defects"])


def test_back_view_not_counted_and_weak_face_dropped():
    cast = [{"name": "林晚", "presence": "在画"}, {"name": "陈宇", "presence": "在画", "part": "背影"}]
    f = feat([face(A_, [100, 100, 200, 220]), face(B_, [500, 100, 600, 220], score=0.6)])
    r = A.judge(f, cast)
    assert r["metrics"]["expected_faced"] == 1 and r["metrics"]["heads"] == 1 and r["verdict"] == "clean"


def test_small_faces_ignored():
    f = feat([face(A_, [100, 100, 110, 115]), face(B_, [500, 100, 600, 220])])
    assert A.judge(f, CAST2)["metrics"]["faces_small"] == 1


def test_hands_over_two_per_person():
    dwp = {"box": [0, 0, 500, 900], "feet": [], "lhand": None, "rhand": None}
    hands = [{"box": [10 + 60 * i, 400, 60 + 60 * i, 450], "conf": 0.9} for i in range(3)]
    r = A.judge(feat([], dw=[dwp], hands=hands), None)
    assert any(d["code"] == "extra_hands" for d in r["defects"])
    r2 = A.judge(feat([], dw=[dwp], hands=hands[:2]), None)
    assert not r2["defects"]


def test_finger_ratio_v6():
    ok = [[0.0, 0.0, 1]] + [[i * 20.0, 100.0 - k * 20.0, 1] for i in range(5) for k in range(4)]
    assert A.finger_bad(ok) is False
    short = [[float(i), 0.0, 1] for i in range(21)]
    short[5], short[17] = [0.0, 0.0, 1], [100.0, 0.0, 1]            # 掌宽 100，手指总长只有几个像素
    assert A.finger_bad(short) is True
    assert A.finger_bad([[0, 0, 0.1]] * 21) is None


def test_mirror_cover():
    mask = {"W": 100, "H": 100, "rows": ["0011"] * 4}
    assert A.mirror_cover([60, 0, 100, 100], mask) == 1.0
    assert A.mirror_cover([0, 0, 40, 100], mask) == 0.0


def test_partial_cast_gets_head_slot_but_stranger_flagged():
    cast = [{"name": "林晚", "presence": "局部", "part": "手", "faced": False}]
    f = feat([face(A_, [100, 100, 200, 220], {"lin_wan": 0.8})], refs_loaded=["lin_wan"])
    assert A.judge(f, cast)["verdict"] == "clean"
    f2 = feat([face(A_, [100, 100, 200, 220], {"lin_wan": 0.8}), face(_v(5), [500, 100, 560, 190], {"lin_wan": 0.05})], refs_loaded=["lin_wan", "gu_chen"])
    cast2 = [{"name": "林晚", "presence": "在画", "faced": True}, {"name": "顾沉", "presence": "局部", "part": "手臂", "faced": False}]
    r = A.judge(f2, cast2)
    assert r["defects"][0]["code"] == "extra_head"
    cast3 = cast2 + [{"name": "路人甲", "presence": "在画", "faced": True}]
    assert A.judge(f2, cast3)["verdict"] == "clean"


def test_geometric_mirror_same_height_opposite_yaw():
    ka = [[110, 150], [150, 150], [125, 175], [112, 195], [148, 195]]       # 鼻偏左
    kb = [[610, 150], [650, 150], [645, 175], [612, 195], [648, 195]]       # 鼻偏右
    fa = face(A_, [100, 100, 160, 220], {"gu_chen": 0.6}); fa["kps"] = ka
    fb = face(A_, [600, 110, 660, 230], {"gu_chen": 0.6}); fb["kps"] = kb
    r = A.judge(feat([fa, fb], refs_loaded=["gu_chen"]), [{"name": "顾沉", "presence": "在画", "faced": True}])
    assert r["verdict"] == "clean" and r["metrics"]["heads_mirror_geo"] == 1
    fb2 = face(A_, [600, 500, 660, 620], {"gu_chen": 0.6}); fb2["kps"] = kb       # 高度不同 = 不是镜像
    r2 = A.judge(feat([fa, fb2], refs_loaded=["gu_chen"]), [{"name": "顾沉", "presence": "在画", "faced": True}])
    assert r2["defects"][0]["code"] == "duplicate_person"


def test_signature_red_cord_misowned():
    dwp = {"box": [0, 0, 500, 900], "feet": [], "lhand": None, "rhand": None}
    f = feat([], dw=[dwp], wrists=[{"person": 0, "red": 0.02, "comp_span": 0.8, "comp_fill": 0.2}])
    r = A.judge(f, [{"name": "林晚", "presence": "局部", "part": "手"}])
    assert r["defects"][0]["code"] == "signature_item_misowned"
    assert not A.judge(f, [{"name": "陈宇", "presence": "局部", "part": "手"}])["defects"]


def test_hands_quota_counts_partial_people():
    dwp = {"box": [0, 0, 500, 900], "feet": [], "lhand": None, "rhand": None}
    hands = [{"box": [10 + 80 * i, 400, 60 + 80 * i, 450], "conf": 0.9} for i in range(3)]
    f = feat([], dw=[], hands=hands)
    cast = [{"name": "林晚", "presence": "在画"}, {"name": "陈宇", "presence": "局部", "part": "手"}]
    assert not A.judge(f, cast)["defects"]


def test_geometric_mirror_by_vertical_frame_line():
    fa = face(A_, [360, 270, 490, 450], {"gu_chen": 0.6})
    fb = face(A_, [650, 310, 750, 475], {"gu_chen": 0.64})
    cast = [{"name": "顾沉", "presence": "在画", "faced": True}]
    r = A.judge(feat([fa, fb], refs_loaded=["gu_chen"], vlines=[580]), cast)
    assert r["verdict"] == "clean" and r["metrics"]["heads_mirror_geo"] == 1
    r2 = A.judge(feat([fa, fb], refs_loaded=["gu_chen"], vlines=[800]), cast)       # 竖线不在两脸之间
    assert r2["defects"][0]["code"] == "duplicate_person"


def test_red_cord_thin_ring_vs_red_cloth():
    assert A.red_cord_like({"red": 0.02, "comp_span": 0.8, "comp_fill": 0.2}, A.TH)
    assert not A.red_cord_like({"red": 0.32, "comp_span": 0.9, "comp_fill": 0.9}, A.TH)
    assert not A.red_cord_like({"red": 0.002, "comp_span": 0.1, "comp_fill": 0.5}, A.TH)
