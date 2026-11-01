"""SCRIPT-RSI 11-01（D-SCR-07，项目方 18:2x“所有图片不要看镜头”）：编译器视线句覆盖。

- 出片：所有可用视频配方（含 Pika：i2va_pika_flex / dialogue_closeup_pika / static_emotion_pika）都继承 _base 的
  prompt.eyeline_cue / open_motion_cue，正向写法、不提 camera / lens（K-REN-G02 / K-REN-G05）。
- 出图：双人系统句不写朝向镜头（K-REN-703）；视线补句逐人覆盖（K-REN-G06）。
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in ("packages/schema", "services/agent", "services/api", "services/recipes"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))


def test_every_video_recipe_inherits_eyeline_and_open_motion():
    from ns_recipes import registry as R
    from ns_recipes.lint import NEG_WORDS_RE
    reg = R.load()
    ids = [p.stem for p in (ROOT / "services/recipes/recipes").glob("*.yaml") if not p.stem.startswith("_")
           and p.stem != "community_pending"]
    assert {"i2va_pika_flex", "dialogue_closeup_pika", "static_emotion_pika"} <= set(ids)
    for rid in ids:
        p = reg.resolve(rid).get("prompt") or {}
        for k in ("eyeline_cue", "open_motion_cue"):
            assert (p.get(k) or "").strip(), f"{rid} 缺 prompt.{k}"
            assert not NEG_WORDS_RE.search(p[k]) and not re.search(r"camera|lens", p[k], re.I), f"{rid}.{k}"


def test_two_shot_clause_positive_gaze_no_camera():
    from ns_agent.framing import two_shot_clause
    s = two_shot_clause(2, None)
    # ⤴ VIDEO-RCA 11-01（总调度 r2 决定，K-REN-703 证据例外）：现行为实测句 TWO_SHOT_TESTED（看镜头 3/4 → 0/4），
    # 只允许“不看镜头 / off the lens”这种否定式提到镜头；r2 A/B 后若正向句同样有效，改回 TWO_SHOT_POSITIVE
    from ns_agent.framing import TWO_SHOT_POSITIVE, TWO_SHOT_TESTED
    assert s in (TWO_SHOT_TESTED, TWO_SHOT_POSITIVE)
    assert not re.search(r"朝向镜头|看着镜头|toward the camera|at the camera|into the lens", s)
    assert not re.search(r"镜头|camera|lens", TWO_SHOT_POSITIVE) and "视线" in TWO_SHOT_POSITIVE
    assert two_shot_clause(2, "part") == "" and two_shot_clause(1, None) == ""


def _shot(img, beat=""):
    return {"img_prompt": img, "cast": [{"name": "林晚", "presence": "在画"}, {"name": "陈宇", "presence": "在画"}],
            "extras": [{"label": "分拍", "text": beat}] if beat else []}


def test_eyeline_note_covers_second_person():
    from ns_agent import frame_job as FJ
    beat = "0–2秒｜陈宇把汤放上桌｜视线=汤碗｜表情=嘴角带笑｜反应=林晚：视线落在他的手上，手指收紧"
    sh = _shot("中景，林晚坐在桌前，视线落在汤碗；陈宇站在桌对面，双手端汤", beat)
    n = FJ.eyeline_note(sh, None, sh["img_prompt"])
    assert n.startswith("陈宇的视线落在汤碗上") and "林晚" not in n
    sh = _shot("中景，林晚坐在桌前；陈宇站在桌对面", beat)
    n = FJ.eyeline_note(sh, None, sh["img_prompt"])
    assert "林晚的视线落在他的手上（" in n and "陈宇的视线落在汤碗上" in n and "镜头" not in n


def test_eyeline_note_defaults_to_partner_and_skips_covered():
    from ns_agent import frame_job as FJ
    sh = _shot("中景，林晚坐在桌前，视线落在陈宇脸上；陈宇垂眼看着汤碗")
    assert FJ.eyeline_note(sh, None, sh["img_prompt"]) == ""
    sh = _shot("中景，林晚坐在桌前，视线落在陈宇脸上；陈宇站在桌对面")
    assert FJ.eyeline_note(sh, None, sh["img_prompt"]) == "陈宇的视线落在林晚的脸上（看画内的人或物，眼神有落点）。"
