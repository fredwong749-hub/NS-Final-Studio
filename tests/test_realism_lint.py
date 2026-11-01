"""RESEARCH 真人写实系统侧检查 RL01–RL03（knowledge/rules/research_realism.yaml）。"""
import importlib.util
from pathlib import Path

from PIL import Image, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
_s = importlib.util.spec_from_file_location("ns_realism_lint_t", ROOT / "tools" / "research" / "realism_lint.py")
RL = importlib.util.module_from_spec(_s)
_s.loader.exec_module(RL)

SUF = "专业电影画面，徕卡M 50mm f/2镜头，焦点锐利，微反差强，皮肤纹理清晰，自然高光，暖调通透，干净真实"
SHARP = {"sharpen": {"enabled": True, "radius": 1.2, "amount": 0.6}, "style_suffix": SUF}


def ids(x):
    return [i["id"] for i in x]


def test_rl01_double_sharpening():
    p = "特写，林晚侧脸，面部清晰对焦，五官锐利，台灯暖光从右侧落在脸颊上，" + SUF
    assert "RL01" in ids(RL.lint_prompt(p, SHARP))
    assert "RL01" not in ids(RL.lint_prompt(p, {"sharpen": {"enabled": False}, "style_suffix": SUF}))
    assert "RL01" not in ids(RL.lint_prompt("特写，林晚侧脸，台灯暖光从右侧落在脸颊上", SHARP))


def test_rl02_cold_body_warm_suffix():
    p = "近景，冷白顶光从正上方打下来，" + SUF
    assert "RL02" in ids(RL.lint_prompt(p, SHARP))
    assert "RL02" not in ids(RL.lint_prompt("近景，暖黄台灯从右侧落在脸上，" + SUF, SHARP))


def test_rl03_q4_lap_on_sharpened_delivery():
    rq = {"image_presets": [{"id": "frame_v9", "params": {"sharpen": {"enabled": True}}}]}
    assert ids(RL.lint_config(rq, {"image_thresholds": {"Q4_texture": {"lap_full_min": 175}}})) == ["RL03"]
    assert RL.lint_config({"image_presets": [{"id": "x", "params": {}}]},
                          {"image_thresholds": {"Q4_texture": {"lap_full_min": 175}}}) == []


def test_usm_alone_inflates_q4_laplacian():
    """K-REV-X01 的机理：同一张图只加 UnsharpMask（frame_v9 的 1.2 / 60% / 2），契约 Q4 的 lap_full 明显升高"""
    import sys
    sys.path.insert(0, str(ROOT / "services" / "agent"))
    from ns_agent.gen_contract.metrics import texture
    src = ROOT / "data/ab/leica_sharp/ep02-S1/Sstar_g.png"
    if not src.exists():
        import pytest
        pytest.skip("A/B 原图不在")
    im = Image.open(src).convert("RGB")
    usm = im.filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    assert texture(usm)["lap_full"] > 1.6 * texture(im)["lap_full"]


def test_leica_sstar_sharpen_unchanged_l087():
    """L-087（项目方 11-01 17:5x 选 R0）：徕卡 S★ 的锐化参数保持 USM 1.2 / 60% / 阈值 2；owner_decisions D-IMG-87b 引用本测试"""
    import json
    rq = json.loads((ROOT / "config/render_quality.json").read_text(encoding="utf-8"))
    p = next(x for x in rq["image_presets"] if x["id"] == "leica_sstar")["params"]
    assert p["sharpen"] == {"enabled": True, "radius": 1.2, "amount": 0.6, "threshold": 2}
    assert rq["default_preset"] == "leica_sstar"


def test_realism_lints_record_only_l087():
    """L-087：RL01–RL03 只记录，不报警"""
    p = "特写，面部清晰对焦，五官锐利，冷白顶光从正上方打下来，" + SUF
    assert {i["level"] for i in RL.lint_prompt(p, SHARP)} == {"record"}
