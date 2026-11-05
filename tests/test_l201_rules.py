"""L-201 ③（K-WRT-L201a / L201b；rubric_code.l201_checks / writer_lints.check_l201）：同场相邻两镜景别或机位至少一项要变；
现实↔幻想切换前后两镜都要写出触发画面（光闪 / 灯亮 / 白闪 / 黑场…）。两条导入即阻断（QW-L12 / QW-L13 level=block）"""
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


RC = _load("rubric_code_l201t", "tools/script_rsi/rubric_code.py")
WL = _load("writer_lints_l201t", "tools/qa/writer_lints.py")


def shot(i, scene="sk_a"):
    return NS(index=i, scene_id=scene, cast=[NS(name="人0", presence="在画", x="中", depth="中")])


def block(i, size="中景", cam="侧 45°、平视略低", optic="50mm｜T2｜高度=1.4m", seg="【现实段】", beats="0–2秒｜人0抬手｜视线=门｜表情=嘴唇抿着",
          cut="动作匹配切｜人0抬手", link="同场换机位｜承：动作｜人0抬手"):
    return (f"**镜{i}｜img**：{size}，{cam}，人0站着\n**机位与景别**：{size}｜{cam}｜人0\n**光学**：{optic}\n"
            f"**场景**：sk_a｜{seg}白幕前\n**衔接**：{link}\n**分拍**：{beats}\n**下镜**：{cut}\n**motion**：x——{size}，人0")


def run(blocks):
    return RC.l201_checks([shot(i + 1) for i in range(len(blocks))], blocks)


# ---- K-WRT-L201a 同场相邻镜景别 / 机位

def test_same_size_and_camera_blocked():
    r = run([block(1), block(2)])
    assert "adj#2" in r and "景别" in r["adj#2"][1]


def test_size_change_passes():
    assert "adj#2" not in run([block(1), block(2, size="中近景")])


def test_angle_change_passes():
    assert "adj#2" not in run([block(1), block(2, cam="右前 45°、低机位微仰")])


def test_height_change_alone_passes():
    assert "adj#2" not in run([block(1), block(2, optic="50mm｜T2｜高度=1.3m")])


def test_different_scene_not_compared():
    sh = [shot(1, "sk_a"), shot(2, "sk_b")]
    assert "adj#2" not in RC.l201_checks(sh, [block(1), block(2)])


def test_framing_signature():
    size, sig = RC.l201_framing(block(1))
    assert size == "中景" and "侧45°" in sig and "平视" in sig and sig.endswith("@高度=1.4m")


# ---- K-WRT-L201b 现实↔幻想触发画面

def test_segment_switch_without_trigger_blocked():
    r = run([block(1, seg="【现实段】", beats="0–5秒｜人0的下巴抬起｜视线=灯架", cut="动作匹配切｜人0的下巴抬起"),
             block(2, seg="【幻想段】", cam="右前 45°", link="同场换机位｜承：动作｜人0的下巴抬起")])
    assert "seg#2" in r and "镜1 【分拍】/【下镜】" in r["seg#2"][1] and "镜2 【衔接】" in r["seg#2"][1]


def test_segment_switch_trigger_one_side_only_blocked():
    r = run([block(1, seg="【现实段】", beats="0–5秒｜人0抬眼，环形灯啪地亮起、暖白光闪满画面｜视线=灯架", cut="光闪匹配切｜环形灯亮起"),
             block(2, seg="【幻想段】", cam="右前 45°", link="同场换机位｜承：动作｜人0的下巴抬起")])
    assert "seg#2" in r and "镜2 【衔接】" in r["seg#2"][1] and "镜1" not in r["seg#2"][1].split("：", 1)[1].split("没写")[0]


def test_segment_switch_with_trigger_both_sides_passes():
    r = run([block(1, seg="【现实段】", beats="0–5秒｜人0抬眼，环形灯啪地亮起、暖白光闪满画面｜视线=灯架", cut="光闪匹配切｜环形灯亮起"),
             block(2, seg="【幻想段】", cam="右前 45°", link="同场换机位｜承：光闪｜从灯亮的白闪余晖里开始")])
    assert "seg#2" not in r
    r = run([block(1, seg="【幻想段】", beats="0–5秒｜灯熄灭，画面落到黑场｜视线=灯架", cut="硬切｜理由=黑场"),
             block(2, seg="【现实段】", cam="右前 45°", link="同场换机位｜承：黑场｜从黑场里亮起")])
    assert "seg#2" not in r


def test_no_segment_marks_not_checked():
    assert "seg#2" not in run([block(1, seg=""), block(2, seg="", cam="右前 45°")])
    assert "seg#2" not in run([block(1, seg="【现实段】"), block(2, seg="【现实段】", cam="右前 45°")])


def test_segment_parse():
    assert RC.l201_segment(block(1, seg="【幻想段】")) == "fantasy"
    assert RC.l201_segment(block(1, seg="【现实段】")) == "reality"
    assert RC.l201_segment(block(1, seg="")) is None


# ---- 接线：writer_lints 规则级别 block、知识库 id、光闪匹配切进下镜词表

def test_rules_registered_block_and_in_index():
    import json
    for rid in ("QW-L12", "QW-L13"):
        assert WL.RULES[rid][0] == "block"
    assert WL.L201_LEVEL == "block"
    idx = json.loads((ROOT / "knowledge/generated/index.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in (idx["rules"] if isinstance(idx, dict) and "rules" in idx else idx)}
    assert {"K-WRT-L201a", "K-WRT-L201b"} <= ids
    assert "光闪匹配切" in RC.L2_CUT_TYPES
    kn = (ROOT / "config/recipes/writer_knowledge.md").read_text(encoding="utf-8")
    assert "[K-WRT-L201a]" in kn and "[K-WRT-L201b]" in kn


def test_check_l201_issue_level_block():
    text = "## ep1《x》\n**剧情**：y\n\n" + block(1) + "\n\n" + block(2) + "\n"
    ep = NS(number=1, shots=[shot(1), shot(2)])
    out = WL.check_l201(ep, text)
    assert out and all(x["level"] == "block" for x in out) and {x["rule_id"] for x in out} == {"QW-L12"}


def test_validator_wires_l201():
    src = (ROOT / "tools/validate_qwen_script.py").read_text(encoding="utf-8")
    assert "WL.check_l201(ep, text)" in src


@pytest.mark.parametrize("name, want", [("P4_ep01.L3_psm7.md", {"QW-L13"}), ("P4_ep01.L3_psm8.md", set())])
def test_ep01_staging_s1_s2(name, want):
    """psm7 的 S1→S2（现实→幻想）只写“下巴抬起”→ QW-L13；psm8 写了光闪触发 + 机位 / 高度都换 → 两条都不报"""
    p = ROOT / "data/pipeline/runs/series10_v2/staging" / name
    if not p.exists():
        pytest.skip(f"{name} 不在本机")
    V = _load("validate_qwen_script_l201t", "tools/validate_qwen_script.py")
    rep = V.validate(p, 1, [], require_scenes=True, run="series10_v2")
    ep = rep["episodes"][0]
    got = {i["rule_id"] for i in ep.get("issues", []) if i["rule_id"] in ("QW-L12", "QW-L13")}
    assert got == want
    if not want:
        assert rep["blocking"] == 0
