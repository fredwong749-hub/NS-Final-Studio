"""ACTING 11-01：写作方 QW-A1–A5（tools/qa/acting_lints.py；规则 K-WRT-A01–A05）。"""
from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("acting_lints_t", ROOT / "tools" / "qa" / "acting_lints.py")
AL = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(AL)


def shot(cast=("林晚",), motion="", h3=""):
    return NS(cast=[NS(name=n, presence="在画") for n in cast], motion_prompt=motion, h3_prompt=h3)


def codes(sh, beats, img="中景，林晚坐在桌前，视线落在桌上的杯子"):   # SCRIPT-RSI 11-01：合格样例补视线落点（QW-A7）
    return [i["rule_id"] for i in AL.check_shot(sh, None, img, "中景", {"分拍": beats})]


GOOD1 = ("0–2秒｜林晚把杯子推到桌边｜视线=杯沿｜表情=嘴角压平；"
         "2–4秒｜她抬眼看向门口｜视线=门口的顾沉｜表情=眉梢轻抬")


def test_good_single_person_clean():
    assert codes(shot(), GOOD1) == []


def test_a1_missing_or_vague_gaze():
    c = codes(shot(), "0–2秒｜林晚把杯子推到桌边｜视线=—｜表情=嘴角压平；2–4秒｜她起身｜视线=前方｜表情=眉梢轻抬")
    assert c.count("QW-A1") == 2


def test_a2_camera_gaze_anywhere():
    assert "QW-A2" in codes(shot(), GOOD1, img="近景，林晚直视镜头")
    assert "QW-A2" in codes(shot(motion="她抬眼看向镜头"), GOOD1)
    assert "QW-A2" in codes(shot(h3="integrated_multimodal_description: She looks straight into the camera. overall_soundscape: x"), GOOD1)
    assert "QW-A2" not in codes(shot(), GOOD1, img="近景，林晚侧面朝向镜头，视线落在窗外")   # 身体朝向不算


def test_a3_first_beat_hold_and_long_beats():
    c = codes(shot(), "0–2秒｜林晚一动不动坐着｜视线=窗外｜表情=唇微抿；2–5秒｜她起身｜视线=门口｜表情=眉梢轻抬")
    assert c.count("QW-A3") == 2          # 第一拍定住 + 一拍 3 秒
    c = codes(shot(), "0–2秒｜林晚起身｜视线=门｜表情=抿唇；2–4秒｜保持站姿｜视线=门｜表情=抿唇；4–6秒｜仍然站着｜视线=门｜表情=抿唇")
    assert "QW-A3" in c


def test_a4_expression():
    c = codes(shot(), "0–2秒｜林晚把杯子推到桌边｜视线=杯沿｜表情=情绪复杂；2–4秒｜她起身｜视线=门口｜表情=")
    assert c.count("QW-A4") == 2


def test_a5_multi_person_each_needs_gaze_and_expression():
    sh = shot(cast=("林晚", "顾沉"))
    bad = ("0–2秒｜林晚把杯子推过去｜视线=顾沉的手｜表情=嘴角压平｜反应=顾沉的手指敲了一下桌面；"
           "2–4秒｜她抬眼｜视线=顾沉眼睛｜表情=眉梢轻抬｜反应=—")
    assert codes(sh, bad).count("QW-A5") == 2
    good = ("0–2秒｜林晚把杯子推过去｜视线=顾沉的手｜表情=嘴角压平｜反应=顾沉：视线落在杯沿，下颌绷紧；"
            "2–4秒｜她抬眼｜视线=顾沉眼睛｜表情=眉梢轻抬｜反应=顾沉：抬眼看她，嘴角压平")
    assert "QW-A5" not in codes(sh, good)


def test_a5_h3_counts_per_person():
    sh = shot(cast=("林晚", "顾沉"), h3="integrated_multimodal_description: [Shot 1] She walks in. He stands. overall_soundscape: x")
    good = ("0–2秒｜林晚走进来｜视线=顾沉｜表情=嘴角压平｜反应=顾沉：视线落在她脸上，下颌绷紧")
    assert "QW-A5" in codes(sh, good)


def test_level_follows_caller():
    out = AL.check_shot(shot(), None, "近景，林晚直视镜头", "近景", {"分拍": GOOD1}, level="block")
    assert out and all(i["level"] == "block" for i in out)


def test_validator_registers_rules():
    src = (ROOT / "tools" / "validate_qwen_script.py").read_text(encoding="utf-8")
    assert "RULES.update(AL.RULES)" in src and "AL.check_shot(" in src and "level=WL.WRITER_LINT_LEVEL" in src


# ---------------- SCRIPT-RSI 11-01（D-SCR-07：项目方 18:2x“所有图片不要看镜头”）QW-A6 / A7 / A8 / AX1、QW-A1 方向词
def test_a6_facing_camera_wording():
    assert "QW-A6" in codes(shot(), GOOD1, img="中景，林晚正面朝镜头，视线落在杯沿")
    assert "QW-A6" in codes(shot(h3="integrated_multimodal_description: [Shot 1] a woman facing the camera, her eyes on the cup. overall_soundscape: x"), GOOD1)
    assert "QW-A6" not in codes(shot(), GOOD1, img="中景，林晚侧面朝向镜头，视线落在杯沿")
    assert "QW-A6" not in codes(shot(), GOOD1, img="中景，林晚背对镜头，视线落在窗外")


def test_a7_img_gaze_each_person():
    sh = shot(cast=("林晚", "顾沉"))
    beats = "0–2秒｜林晚把杯子推过去｜视线=顾沉的手｜表情=嘴角压平｜反应=顾沉：视线落在杯沿，下颌绷紧"
    c = codes(sh, beats, img="中景，林晚坐在桌前，视线落在顾沉的手上；顾沉站在桌边，双手插兜")
    assert c.count("QW-A7") == 1
    assert "QW-A7" not in codes(sh, beats, img="中景，林晚坐在桌前，视线落在顾沉的手上；顾沉垂眼看着她的杯子")
    assert "QW-A7" not in codes(sh, beats, img="中景，林晚坐在桌前，视线落在顾沉的手上；顾沉背对她站在窗边")
    # 写实套话里的“眼睛”不算视线
    assert "QW-A7" in codes(shot(), GOOD1, img="近景，林晚坐在桌前，眼睛为真实人眼大小")


def test_a8_h3_first_frame_gaze():
    no = "integrated_multimodal_description: [Shot 1] A woman sits at a table. At 00:02.000, she glances at the cup. overall_soundscape: x"
    yes = "integrated_multimodal_description: [Shot 1] A woman sits, her eyes resting on the cup. At 00:02.000, she lifts it. overall_soundscape: x"
    assert "QW-A8" in codes(shot(h3=no), GOOD1)
    assert "QW-A8" not in codes(shot(h3=yes), GOOD1)


def test_a1_direction_only_is_vague():
    c = codes(shot(), "0–2秒｜林晚把杯子推到桌边｜视线=对面｜表情=嘴角压平；2–4秒｜她起身｜视线=对面的陈宇｜表情=眉梢轻抬")
    assert c.count("QW-A1") == 1


def test_ax1_axis_flip():
    def sh(i, a, b, link="同场换机位", carry=""):
        return NS(index=i, scene_id="sk_x", link=link, link_carry=carry,
                  cast=[NS(name="林晚", presence="在画", x=a), NS(name="顾沉", presence="在画", x=b)])
    ep = NS(number=1, shots=[sh(1, "左", "右"), sh(2, "右", "左")])
    out = AL.check_episode(ep)
    assert [i["rule_id"] for i in out] == ["QW-AX1"] and out[0]["shot"] == 2
    ep = NS(number=1, shots=[sh(1, "左", "右"), sh(2, "右", "左", carry="越轴｜他绕到她身后")])
    assert AL.check_episode(ep) == []
    ep = NS(number=1, shots=[sh(1, "左", "右"), sh(2, "左", "右")])
    assert AL.check_episode(ep) == []
