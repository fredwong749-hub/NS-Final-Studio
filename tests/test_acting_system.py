"""ACTING 11-01（R11-2 / R11-8 / R11-9）：系统层——成片不加字幕、出图视线说明、H3 开头即动 / 视线提示、多人视线 lint、检测器“未测”。"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/post", "services/agent", "services/recipes", "packages/schema", "packages/qc", "services/api",
          "services/render_router"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))


# ---------------- 字幕：硬默认（R11-8）
def test_no_subtitles_hard_default():
    from ns_post import ffmpeg as F
    assert F.NO_SUBTITLES is True
    for bad in (["-vf", "subtitles=a.srt"], ["-vf", "scale=1080:1920,drawtext=text='x'"], ["-i", "ep01.srt"],
                ["-c:s", "mov_text"], ["-filter_complex", "[0:v]ass=sub.ass[v]"]):
        with pytest.raises(F.FFmpegError):
            F.assert_no_subtitles(bad)
    for ok in (["-vf", "scale=1080:1920,fps=24"], ["-af", "loudnorm=I=-14,bass=g=2,aresample=48000"], ["-c:v", "libx264"]):
        F.assert_no_subtitles(ok)


def test_assemble_manifest_says_no_subtitles():
    src = (ROOT / "services/post/ns_post/assemble.py").read_text(encoding="utf-8")
    assert '"subtitles": False' in src and "subtitles=" not in src.replace('"subtitles": False', "")


# ---------------- 出图视线说明（R11-2）
def test_eyeline_note_is_registered_fixed_sentence():
    from ns_agent import asset_refs as AR
    assert AR.EYELINE_RE in AR.TEXT_NOTE_RES
    s = AR.EYELINE_NOTE.format(name="林晚", target="窗外的霓虹光斑")
    assert AR.EYELINE_RE.fullmatch(s) and "镜头" not in s


def test_eyeline_note_roundtrip_in_match_target():
    from ns_agent import asset_refs as AR
    from ns_agent import frame_job as FJ
    from ns_api.unified_stale import match_target
    body = "中景，平视，林晚坐在转椅上，专业电影画面，无字幕、无文字、无水印"
    note = AR.EYELINE_NOTE.format(name="林晚", target="窗外") + "。"
    sent = FJ.with_note(body, note)
    assert match_target(sent, body) == sent


class _Shot(dict):
    pass


def test_eyeline_note_only_when_body_has_no_gaze():
    from ns_agent import frame_job as FJ
    shot = {"img_prompt": "中景，平视，林晚坐在转椅上", "motion_prompt": "林晚抬头，视线转向窗外的霓虹光斑，手指收紧",
            "cast": [{"name": "林晚", "presence": "在画"}], "extras": []}
    n = FJ.eyeline_note(shot, None, shot["img_prompt"])
    assert "林晚的视线落在窗外的霓虹光斑上" in n
    assert FJ.eyeline_note(shot, None, "中景，林晚看向窗外") == ""


# ---------------- H3：开头即动 + 视线落点（R11-2 / R11-8），正向写法
def test_h3_cues_present_and_positive():
    from ns_recipes import registry as R
    from ns_recipes.lint import NEG_WORDS_RE
    base = R.load().resolve("i2va_pdd2")
    p = base.get("prompt") or {}
    for k in ("open_motion_cue", "eyeline_cue"):
        assert p.get(k), k
        assert not NEG_WORDS_RE.search(p[k]), f"{k} 有否定词（H3 不认否定）"
        assert "camera" not in p[k].lower() and "lens" not in p[k].lower()


def test_h3_cues_inserted_before_first_stamp():
    import re
    from ns_recipes import prompt as PR
    body = "[Shot 1] Live-action, cinematic, a close-up begins. She lifts her hand. At 00:02.000, she turns."
    recipe = {"prompt": {"open_motion_cue": "OPEN.", "eyeline_cue": "EYE."}}

    class Spec:
        id = "t"
        h3 = type("H", (), {"text": "x"})()
        audio = type("A", (), {"soundscape_en": "rain"})()
    orig = PR.split_fields
    PR.split_fields = lambda t: ("", {"integrated_multimodal_description": body})
    try:
        out = PR.build_base(Spec(), recipe, "fl2va", 97)
    finally:
        PR.split_fields = orig
    b = out["fields"]["integrated_multimodal_description"]
    assert re.search(r"OPEN\. EYE\. At 00:02\.000", b)


# ---------------- 多人镜视线 / 表情 lint（R11-9）
def test_rl_e1_multi_person_needs_gaze_and_expression():
    from ns_recipes.lint import lint_people_eyeline

    class Spec:
        faces = [1, 2]
    thin = "integrated_multimodal_description: [Shot 1] She walks in. He stands up.\n\noverall_soundscape: x"
    rich = ("integrated_multimodal_description: [Shot 1] She looks toward him, her lips pressed. He glances at her hand, "
            "his jaw tight.\n\noverall_soundscape: x")
    assert any(i["code"] == "RL-E1" for i in lint_people_eyeline(thin, Spec(), {}))
    assert not any(i["code"] == "RL-E1" for i in lint_people_eyeline(rich, Spec(), {}))
    cam = "integrated_multimodal_description: [Shot 1] She looks straight into the camera.\n\noverall_soundscape: x"
    assert any(i["code"] == "RL-E2" for i in lint_people_eyeline(cam, Spec(), {}))


# ---------------- 检测器：没脸 = 未测（不是通过）
def test_gaze_untested_without_face():
    from ns_qc import gaze as G
    if G._models() is None:
        pytest.skip("没有 YuNet")
    r = G.image_gaze(np.full((640, 360, 3), 128, np.uint8))
    assert r["status"] == "未测"
    assert G.BLOCK is False      # 标定前只记录


def test_postflight_g1_record_only(tmp_path):
    import cv2
    from ns_agent.gen_contract import postflight as PF
    p = tmp_path / "blank.png"
    cv2.imwrite(str(p), np.full((640, 360, 3), 128, np.uint8))
    st, d, ev = PF.gaze_item(p)
    assert st in ("na", "untested") and "未测" in d
