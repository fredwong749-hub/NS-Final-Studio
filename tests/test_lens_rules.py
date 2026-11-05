"""L3 焦段光圈表 / 背景光源 / 双人站位（K-WRT-816–818；rubric_code.l3_checks / writer_lints.check_l3）"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    s = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


RC = _load("rubric_code_l3t", "tools/script_rsi/rubric_code.py")
WL = _load("writer_lints_l3t", "tools/qa/writer_lints.py")


def shot(i, n=1, scene="s1", depths=("前", "后")):
    return NS(index=i, scene_id=scene, cast=[NS(name=f"人{k}", presence="在画", x="左", depth=depths[k % len(depths)]) for k in range(n)])


def block(i, size="近景", optic="85mm｜T1.4｜高度=1.5m 眼平", bg="背景=远处亮着的灯架和监视器", extra=""):
    return (f"**镜{i}｜img**：{size}，人0站着\n**光学**：{optic}\n**构图**：前景=椅背｜中景=人0{extra}｜{bg}\n**motion**：x")


def run(shots, blocks):
    return RC.l3_checks(shots, blocks)


def test_good_passes():
    assert run([shot(1)], [block(1)]) == {}


def test_missing_fields():
    r = run([shot(1)], [block(1, optic="85mm")])
    assert "optic#1" in r and "T 光圈" in r["optic#1"][1] and "机位高度" in r["optic#1"][1]
    assert "optic#1" in run([shot(1)], [block(1, optic="")])


def test_pairs_by_shot_type():
    assert "optic#1" in run([shot(1)], [block(1, size="特写", optic="50mm｜T2｜高度=1.5m")])          # 特写要 85+
    assert run([shot(1)], [block(1, size="特写", optic="105mm｜T1.2｜高度=1.5m")]) == {}
    assert "optic#1" in run([shot(1)], [block(1, size="近景", optic="85mm｜T2.8｜高度=1.5m")])       # T 太小光圈
    assert run([shot(1, 2)], [block(1, size="中景", optic="50mm｜T2｜高度=1.5m")]) == {}
    assert "optic#1" in run([shot(1, 2)], [block(1, size="中景", optic="85mm｜T2｜高度=1.5m")])
    assert run([shot(1)], [block(1, size="全景", optic="28mm｜T2.8｜高度=1.6m")]) == {}
    assert "optic#1" in run([shot(1)], [block(1, size="全景", optic="85mm｜T1.4｜高度=1.6m")])
    b = block(1, size="近景", optic="85mm｜T1.4｜高度=1.5m").replace("近景，", "过肩近景，")
    assert run([shot(1)], [b]) == {}


def test_one_establishing_per_scene():
    sh = [shot(1, scene="a"), shot(2, scene="a"), shot(3, scene="b")]
    bl = [block(i, size="全景", optic="28mm｜T2.8｜高度=1.6m") for i in (1, 2, 3)]
    r = run(sh, bl)
    assert "estab#2" in r and "estab#1" not in r and "estab#3" not in r


def test_background_needs_practicals():
    r = run([shot(1)], [block(1, bg="背景=一面白色幕布")])
    assert "bokeh#1" in r
    assert "bokeh#1" not in run([shot(1)], [block(1, bg="背景=远处霓虹招牌")])


def test_two_shot_not_side_by_side():
    r = run([shot(1, 2)], [block(1, size="中景", optic="50mm｜T2｜高度=1.5m", extra="并排站着正对镜头")])
    assert "twoshot#1" in r
    r = run([shot(1, 2, depths=("中",))], [block(1, size="中景", optic="50mm｜T2｜高度=1.5m")])
    assert "twoshot#1" in r                                           # cast 景深层全相同
    assert "twoshot#1" not in run([shot(1, 2)], [block(1, size="中景", optic="50mm｜T2｜高度=1.5m")])


def test_rules_registered_warn_and_in_index():
    import json
    for rid in ("QW-L9", "QW-L10", "QW-L11"):
        assert WL.RULES[rid][0] == "warn"
    idx = json.loads((ROOT / "knowledge/generated/index.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in (idx["rules"] if isinstance(idx, dict) and "rules" in idx else idx)}
    assert {"K-WRT-816", "K-WRT-817", "K-WRT-818"} <= ids


def test_lens_id_supplies_focal_and_t_so_l4_l9_do_not_double_report():
    """【镜头】只写新 id（arri_cine_85_t14 = 85mm T1.4）：L9 用 id 的焦段 / T，不再要求【光学】行里重复写 mm / T（只缺机位高度）"""
    b = ("**镜1｜img**：近景，人0站着\n**镜头**：arri_cine_85_t14\n**光学**：高度=1.5m\n**构图**：前景=椅背｜中景=人0｜背景=远处灯架\n**motion**：x")
    assert RC.l3_checks([shot(1)], [b]) == {}
    assert RC.lens_ids() >= {"arri_cine_50_t2", "arri_cine_85_t14", "leica_cine_100_macro_t2", "leica_cine_135_t12", "leica_cine_28_t28"}
    b2 = b.replace("arri_cine_85_t14", "arri_cine_50_t2")                  # 近景用 50mm T2 → 表外，L9 报一次
    r = RC.l3_checks([shot(1)], [b2])
    assert "optic#1" in r
    assert "lens#1" not in RC.l2_checks([shot(1)], [b2], "", "series10_v2")   # L4 不报表内范围


def test_pace_estimated_after_trim():
    shots = [NS(index=i, duration=6, dialogue=[], voiceover=None, cast=[]) for i in range(1, 12)]   # 66 s 剪前 → 46 s 剪后
    ep = NS(number=1, shots=shots)
    t3 = [x for x in WL.check_pacing(ep) if x["rule_id"] == "QW-T3"]
    assert len(t3) == 1 and t3[0]["level"] == "warn" and "46" in t3[0]["detail"]
    ep2 = NS(number=1, shots=[NS(index=i, duration=6, dialogue=[], voiceover=None, cast=[]) for i in range(1, 16)])   # 90 s → 63 s
    assert not [x for x in WL.check_pacing(ep2) if x["rule_id"] == "QW-T3"]
