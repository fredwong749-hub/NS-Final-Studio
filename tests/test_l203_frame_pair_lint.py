"""L-203（K-WRT-L203 / L203b；rubric_code.l203_checks / writer_lints.check_l203 / validate_qwen_script.same_place）：
每镜 起幅（img + 机位与景别）与 落幅（motion“——”后）至少两项明显不同，导入即阻断（QW-L14 level=block）；
同一影棚按机位方向分背景视向子场景（<父场景id>_<视向>），相邻镜换视向不算换场（QW-LK2）"""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    s = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(s)
    s.loader.exec_module(m)
    return m


RC = _load("rubric_code_l203t", "tools/script_rsi/rubric_code.py")
WL = _load("writer_lints_l203t", "tools/qa/writer_lints.py")

IMG = "近景，侧 45° 机位，浅景深，人0站在白幕前，人0的右手把卡按在椅面上、红指甲扣着卡面，人0的视线落在画右，人0嘴唇张开，天花顶灯从上侧 45° 落在颧骨"
TAIL_SAME = "近景，侧 45° 机位，人0的右手按在椅面的卡上，视线落在画右，嘴唇合上，天花顶灯从上侧 45° 落在颧骨，白幕中灰"
TAIL_GOOD = ("近景紧，侧 45° 略俯、1.7 m 机位不动，人0的嘴唇与下颌居中，嘴唇合上、嘴角带笑，视线落向画右偏下，整张烫金卡完整摊在椅面上占画面下部，"
             "人0的右手离开卡面、红指甲悬在卡上方半寸，卡面反光映亮下颌一片暖金，天花顶灯冷白在颧骨")


def block(i, img=IMG, cam="近景｜侧 45° 略俯（C 区）｜人0一人在画", move="推近｜幅度=中｜速度=正常", motion_head="camera push in 中幅推近，人0拍下卡说了一句，手抬起",
          tail=TAIL_GOOD):
    return (f"**镜{i}｜img**：{img}\n**机位与景别**：{cam}\n**光学**：85mm｜T1.4｜高度=1.7m\n**场景**：sk_a｜【现实段】白幕前\n"
            f"**镜头运动**：{move}\n**motion**：{motion_head}——{tail}")


def run(blocks):
    return RC.l203_checks([NS(index=i + 1, scene_id="sk_a") for i in range(len(blocks))], blocks)


# ---- K-WRT-L203 起幅 / 落幅差异

def test_two_changes_pass():
    assert run([block(1)]) == {}


def test_identical_tail_blocked():
    r = run([block(1, tail=TAIL_SAME)])
    assert "pair#1" in r and "项不同" in r["pair#1"][1]


def test_short_tail_blocked():
    r = run([block(1, tail="近景，人0嘴唇合上，手悬在卡上")])
    assert "pair#1" in r and "完整尾帧" in r["pair#1"][1]


def test_size_change_alone_not_enough():
    tail = "近景紧，侧 45° 机位，人0的右手按在椅面的卡上、红指甲扣着卡面，视线落在画右，嘴唇张开，天花顶灯从上侧 45° 落在颧骨，白幕中灰向边缘渐暗一点"
    r = run([block(1, tail=tail)])
    assert "pair#1" in r and "只有 1 项" in r["pair#1"][1]


def test_static_needs_two_non_camera_changes():
    # 固定镜：景别 / 机位不算，只有“景别紧一档”这种镜头项 → 仍阻断；道具 + 姿态两项 → 过
    tail_cam_only = "近景，同机位，人0的右手按在椅面的卡上、红指甲扣着卡面，视线落在画右，嘴唇张开，天花顶灯从上侧 45° 落在颧骨，白幕中灰向边缘渐暗一点"
    r = run([block(1, move="固定镜头｜幅度=小｜速度=正常", motion_head="static shot 固定镜头，人0说了一句", tail=tail_cam_only)])
    assert "pair#1" in r and "固定镜" in r["pair#1"][1]
    tail_act = ("近景，同机位，人0站直、下巴抬起，视线落在画右，嘴唇合上，整张烫金卡完整摊在椅面上，人0的右手离开卡面悬在卡上方半寸，"
                "天花顶灯从上侧 45° 落在颧骨，白幕中灰")
    assert run([block(1, move="固定镜头｜幅度=小｜速度=正常", motion_head="static shot 固定镜头，人0说了一句", tail=tail_act)]) == {}


def test_cam_line_end_frame_segment_not_counted_as_start():
    """【机位与景别】里写了“落幅：…”的，只拿起幅段当起幅（否则落幅的词都算“已有”，永远判不出变化）"""
    cam = "近景｜侧 45° 略俯（C 区）｜起幅：人0一人在画，手按卡；落幅：近景紧，整张卡完整摊在椅面上、红指甲悬在卡上方半寸，卡面反光映亮下颌"
    assert run([block(1, cam=cam)]) == {}


def test_diff_reports_categories():
    d = RC.l203_diff(block(1))
    assert d["size"][0] and d["prop"][0] and d["light"][0] and not d["static"]
    assert RC.l203_tail(block(1)).startswith("近景紧")


def test_rule_registered_block_and_in_index():
    import json
    assert WL.RULES["QW-L14"][0] == "block"
    idx = json.loads((ROOT / "knowledge/generated/index.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in (idx["rules"] if isinstance(idx, dict) and "rules" in idx else idx)}
    assert {"K-WRT-L203", "K-WRT-L203b"} <= ids
    kn = (ROOT / "config/recipes/writer_knowledge.md").read_text(encoding="utf-8")
    assert "[K-WRT-L203]" in kn and "[K-WRT-L203b]" in kn


def test_check_l203_issue_level_block():
    text = "## ep1《x》\n**剧情**：y\n\n" + block(1, tail=TAIL_SAME) + "\n\n" + block(2) + "\n"
    ep = NS(number=1, shots=[NS(index=1), NS(index=2)])
    out = WL.check_l203(ep, text)
    assert len(out) == 1 and out[0]["level"] == "block" and out[0]["rule_id"] == "QW-L14" and "镜1" in out[0]["detail"]


def test_validator_wires_l203():
    src = (ROOT / "tools/validate_qwen_script.py").read_text(encoding="utf-8")
    assert "WL.check_l203(ep, text)" in src


# ---- K-WRT-L203b 背景视向子场景 = 同场

def test_same_place_view_subscenes():
    V = _load("validate_qwen_script_l203t", "tools/validate_qwen_script.py")
    lib = {"sk_white_cyc": object(), "sk_white_cyc_rev": object(), "sk_white_cyc_door": object(), "sk_lane_attic": object()}
    assert V.same_place("sk_white_cyc", "sk_white_cyc", lib)
    assert V.same_place("sk_white_cyc", "sk_white_cyc_rev", lib)
    assert V.same_place("sk_white_cyc_rev", "sk_white_cyc", lib)
    assert V.same_place("sk_white_cyc_rev", "sk_white_cyc_door", lib)
    assert not V.same_place("sk_white_cyc_rev", "sk_lane_attic", lib)
    assert not V.same_place("sk_white_cyc", "sk_lane_attic", lib)
    assert not V.same_place("sk_white_cyc_rev", "sk_white_cyc_door", {"sk_white_cyc_rev": 1, "sk_white_cyc_door": 1})   # 父场景没登记 = 不是同场


@pytest.mark.parametrize("name, blocked", [("P4_ep01.L3_psm8.md", True), ("P4_ep01.L3_psm9.md", False)])
def test_ep01_staging_frame_pairs(name, blocked):
    """psm8 的落幅几乎照抄起幅（镜3 / 5 / 12…）→ QW-L14 阻断；psm9（L-203 首尾帧设想回写 + 五个背景视向）→ block 0"""
    p = ROOT / "data/pipeline/runs/series10_v2/staging" / name
    if not p.exists():
        pytest.skip(f"{name} 不在本机")
    V = _load("validate_qwen_script_l203s", "tools/validate_qwen_script.py")
    rep = V.validate(p, 1, [], require_scenes=True, run="series10_v2")
    ep = rep["episodes"][0]
    got = {i["rule_id"] for i in ep.get("issues", []) if i["level"] == "block"}
    if blocked:
        assert "QW-L14" in got
    else:
        assert rep["blocking"] == 0, got
        views = {ln.split("：", 1)[1].split("｜", 1)[0] for ln in p.read_text(encoding="utf-8").splitlines() if ln.startswith("**场景**：")}
        assert {"sk_white_cyc", "sk_white_cyc_rev", "sk_white_cyc_door", "sk_white_cyc_mirror", "sk_white_cyc_top"} == views
