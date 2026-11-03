"""PROMPT（2026-10-31，ep02 v1 项目方 bug：切换生硬 / 表情互动生硬 / 时间轴粗 / 节奏慢）：
sysimpl-v2 时间轴格式——按秒分拍、每拍视线 / 表情 / 对方反应、开头衔接、结尾留动作、速度——的 lint、Shot Spec 与写作规则组装。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "recipes"))

from ns_api import script_chat as SC  # noqa: E402
from ns_recipes import compiler as C  # noqa: E402
from ns_recipes import lint as L  # noqa: E402
from ns_recipes import registry as R  # noqa: E402
from ns_recipes import spec_import as SI  # noqa: E402
from ns_schema.shot_spec import (Audio, Camera, Continuity, H3Text, IdentityRef, Motion, OnScreenCharacter,  # noqa: E402
                                 Scene, ShotSpec, Source, missing_fields)

HEAD = ("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second "
        "mark of the target video; Picture 2 (from Shot 1) aligns with the 6.58-second mark of the target video.\n\n")
TAIL = "\n\noverall_soundscape: Low office hum fills the room.\n\nnon_diegetic_music: N/A"
GOOD = (HEAD + "integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, a close "
        "two-shot begins in the position, framing and lighting established by Picture 1, a young woman at a desk and a man "
        "leaning over her shoulder. She is already mid-turn toward him, her eyes still on his pointing hand while her lips "
        "part and he taps the screen twice. At 00:02.000, the man (S1) says: <d>[Chinese] 方案第三页，数据错了。</d> his "
        "gaze fixed on her face, brows drawn together; she listens with lips closed, swallows and glances at the screen. "
        "At 00:04.000, she lifts her eyes back to his face, her brows rising as she pulls the keyboard closer, and he "
        "straightens up, his jaw relaxing. At 00:05.500, her fingers start typing fast, eyes darting between the screen and "
        "his hand, her mouth tightening while he steps back, still watching her as the shot ends. She settles into the "
        "spacing established by Picture 2 at the end of the shot." + TAIL)


def codes(issues, level=None):
    return {i["code"] for i in issues if level is None or i["level"] == level}


def test_good_timeline_has_no_errors():
    iss = L.lint_timeline(GOOD, 6.58, sexes=["f", "m"], strict=True)
    assert not [i for i in iss if i["level"] == "error"], iss


def test_split_beats_drops_picture2_sentence_and_dialogue():
    bs = L.split_beats(GOOD.split("integrated_multimodal_description: ")[1].split("\n\noverall")[0], 6.58)
    assert [round(b["t0"], 1) for b in bs] == [0.0, 2.0, 4.0, 5.5]
    assert "Picture 2" not in bs[-1]["text"] and "方案" not in bs[1]["text"]


def test_missing_timeline_blocks_only_under_v2():
    old = HEAD + ("integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, a shot "
                  "begins in the position, framing and lighting established by Picture 1. She looks up." + TAIL)
    assert "RL-T1" in codes(L.lint_timeline(old, 6.58, strict=True), "error")
    assert "RL-T1" in codes(L.lint_timeline(old, 6.58, strict=False), "warn")
    assert not codes(L.lint_timeline(old, 6.58, strict=False), "error")


def test_slots_reaction_continuation_end_and_speed():
    bad = (HEAD + "integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, a shot "
           "begins in the position, framing and lighting established by Picture 1, a woman and a man. She slowly raises "
           "her hand. At 00:03.000, she looks at the screen and smiles. At 00:05.000, her eyes close, lips part, and she "
           "freezes in place." + TAIL)
    iss = L.lint_timeline(bad, 6.58, sexes=["f", "m"], strict=True)
    err = codes(iss, "error")
    assert {"RL-T3", "RL-T4", "RL-T5", "RL-T6"} <= err          # 第 1 拍缺视线/表情、没写男方、没衔接、结尾定住
    assert "RL-T7" in codes(iss, "warn")                         # slowly
    assert "RL-T2" in codes(L.lint_timeline(bad.replace("At 00:03.000", "At 00:03.200").replace("At 00:05.000, ", ""),
                                            6.58, strict=True))  # 3.2→6.58 = 3.4 s 一拍


def test_stamps_must_increase_and_stay_inside():
    t = GOOD.replace("At 00:05.500", "At 00:07.000")
    assert "RL-T1" in codes(L.lint_timeline(t, 6.58, strict=True), "error")


def _spec(rules=None, beats="", faces=2, dur=4.0):
    chars = [OnScreenCharacter(id="lin_wan", name="林晚", screen_x="左", facing="右", pose="坐",
                               en_phrase="a 22-year-old Chinese woman", identity_ref=IdentityRef(path="a.png", sha="1"))]
    if faces == 2:
        chars.append(OnScreenCharacter(id="gu_chen", name="顾沉", screen_x="右", facing="左", pose="站",
                                       en_phrase="a 34-year-old East Asian man", identity_ref=IdentityRef(path="b.png", sha="2")))
    return ShotSpec(id="ep99-S2", episode=99, index=2, duration_s=dur, source=Source(rules_version=rules),
                    scene=Scene(id="sk_x"), camera=Camera(size="近景", move="static shot"), characters_on_screen=chars,
                    motion=Motion(text="x——近景", beats=SI.parse_beats(beats), end_state="近景"),
                    audio=Audio(soundscape_en="Hum."), continuity=Continuity(link="换场"),
                    h3=H3Text(mode="fl2va", text=GOOD))


def test_parse_beats_reads_v2_slots():
    b = SI.parse_beats("0–2秒｜抬头｜视线=对方的脸｜表情=眉头一紧｜反应=他手指停住；2–4秒｜打字｜视线=屏幕｜表情=抿嘴｜反应=他直起身")
    assert [(x.gaze, x.expression, x.reaction) for x in b] == [("对方的脸", "眉头一紧", "他手指停住"), ("屏幕", "抿嘴", "他直起身")]


import pytest  # noqa: E402
import ns_schema.shot_spec as SS  # noqa: E402


@pytest.fixture
def strict_on(monkeypatch):
    monkeypatch.setattr(SS, "timing_lint_level", lambda episode=None: "error")


def test_switch_defaults_to_warn_so_existing_scripts_still_render():
    """总调度 2026-10-31：新提示词导入前 RL-T* / SS-M* 只提示；config/recipes/timing_lint.json 切 error 后才拦"""
    import json
    cfg = json.loads((ROOT / "config" / "recipes" / "timing_lint.json").read_text(encoding="utf-8"))
    assert cfg["timing_lint_level"] == "warn"
    sp = _spec("rules_v2+sysimpl-v2")
    if 99 not in cfg.get("episodes_error", []):
        assert not [m for m in missing_fields(sp) if m.rule.startswith("SS-M") and m.severity == "block"]
        reg = R.load(learned_path=ROOT / "tests" / "fixtures" / "_no_learned.yaml")
        sp6 = _spec("rules_v2+sysimpl-v2", dur=6.0)
        sp6.h3.text = GOOD.replace("At 00:02.000, ", "").replace("At 00:04.000, ", "").replace("At 00:05.500, ", "")
        p = C.compile_shot(sp6, reg)
        assert not [i for i in p["lint"] if i["code"].startswith("RL-T") and i["level"] == "error"]


def test_spec_v2_requires_beats_and_slots(strict_on):
    rules = "rules_v2+sysimpl-v2"
    m = {(x.rule, x.severity) for x in missing_fields(_spec(rules))}
    assert ("SS-M1", "block") in m                                  # 4 s 也要分拍
    assert ("SS-M1", "warn") not in {(x.rule, x.severity) for x in missing_fields(_spec("rules_v2+sysimpl-v1"))}
    sp = _spec(rules, "0–2秒｜抬头｜视线=对方的脸；2–4秒｜打字｜表情=抿嘴")
    m = {(x.rule, x.severity) for x in missing_fields(sp)}
    assert {("SS-M5", "block"), ("SS-M6", "block"), ("SS-M7", "warn")} <= m
    sp1 = _spec(rules, "0–2秒｜抬头｜视线=窗外｜表情=眨眼｜反应=—；2–4秒｜起身｜视线=门｜表情=抿嘴｜反应=—", faces=1)
    assert not {x.rule for x in missing_fields(sp1)} & {"SS-M5", "SS-M6"}
    long = _spec(rules, "0–4秒｜抬头｜视线=a｜表情=b｜反应=c")
    assert "SS-M4" in {x.rule for x in missing_fields(long)}


def test_compile_blocks_untimed_prompt_only_for_v2_specs(strict_on):
    reg = R.load(learned_path=ROOT / "tests" / "fixtures" / "_no_learned.yaml")
    old = GOOD.replace("At 00:02.000, ", "").replace("At 00:04.000, ", "").replace("At 00:05.500, ", "")
    sp_v1 = _spec("rules_v2+sysimpl-v1", dur=6.0)
    sp_v1.h3.text = old
    p1 = C.compile_shot(sp_v1, reg)
    assert "RL-T1" in {i["code"] for i in p1["lint"] if i["level"] == "warn"}
    sp_v2 = _spec("rules_v2+sysimpl-v2", dur=6.0)
    sp_v2.h3.text = old
    p2 = C.compile_shot(sp_v2, reg)
    # TIMELINE-O 11-03：v2 稿缺时间轴改为在 build_base 失败关闭（needs_writer “缺时间轴”），不再编出整句再由 lint 拦
    assert p2["status"] == "needs_writer" and "缺时间轴" in p2["reason"]


def test_writer_system_prompt_carries_sysimpl_v2():
    system, parts = SC.build_system_prompt(SC.load_config(), context=None, appendix_budget=None)
    assert "## 附录：系统可实现性规则 v2" in system
    assert "rules_addendum_version: sysimpl-v2" in system
    assert "rules_addendum_version: sysimpl-v1" in system               # v1 保留，v2 追加
    for key in ("At 00:SS.mmm,", "视线=", "表情=", "反应=", "as the shot ends", "at slow speed"):
        assert key in system, key
    assert system.index("sysimpl-v1") < system.index("sysimpl-v2")
    assert SI.rules_version().split("+")[-1] >= "sysimpl-v2"


def test_i2va_drops_standalone_settle_sentence_without_double_period():
    from ns_recipes import prompt as PR
    body, _ = PR.to_i2va_body("[Shot 1] x established by Picture 1. At 00:02.000, she keeps typing as the shot ends. "
                              "She settles into the pose, spacing, and composition established by Picture 2 at the end of the shot.")
    assert body.endswith("as the shot ends.") and ".." not in body and "<Picture 1>" in body


def test_hands_only_shot_skips_gaze_and_expression():
    t = (HEAD + "integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, a close-up "
         "begins in the position, framing and lighting established by Picture 1, a hand on a coat cuff. The fingers are "
         "already sliding along the cuff. At 00:02.000, the thumb presses the fabric. At 00:04.000, the hand pushes the "
         "hanger deeper, still moving as the shot ends." + TAIL)
    assert "RL-T3" in codes(L.lint_timeline(t, 6.0, strict=True))
    assert "RL-T3" not in codes(L.lint_timeline(t, 6.0, strict=True, faces=False))


def test_parse_beats_keeps_semicolons_inside_a_beat():
    b = SI.parse_beats("0–1.6秒｜他俯身；她抬头｜视线=他看屏幕、她看他｜表情=他抿嘴；她张嘴｜反应=她肩膀绷住；"
                       "1.6–3.2秒｜他点屏幕｜视线=她的脸｜表情=眉头持平｜反应=她眨眼")
    assert [(x.t0, x.t1) for x in b] == [(0.0, 1.6), (1.6, 3.2)]
    assert b[0].gaze == "他看屏幕、她看他" and b[0].reaction and b[0].reaction.startswith("她肩膀绷住")


def test_pure_ref2va_drops_first_frame_anchor_clause():
    from ns_recipes import prompt as PR
    sp = _spec("rules_v2+sysimpl-v2", dur=6.0)
    out = PR.build_ref2va(sp, {"prompt": {"style_lead": "Live-action, cinematic, shallow depth of field"}}, 158,
                          [{"role": "identity", "character": "林晚"}, {"role": "identity", "character": "顾沉"}])
    d = out["fields"]["detailed_description"]
    assert "established by" not in d.split("At 00:")[0] and "opening frame" not in d
    assert "[Shot 1] A close two-shot" in d


def test_writer_system_prompt_carries_sysimpl_v3_camera_rules():
    system, _ = SC.build_system_prompt(SC.load_config(), context=None, appendix_budget=None)
    assert "rules_addendum_version: sysimpl-v3" in system and system.index("sysimpl-v2") < system.index("sysimpl-v3")
    for key in ("**镜头运动**", "动作匹配切", "声音先行", "180° 轴线", "不写 `[Shot 2]`"):
        assert key in system, key
    assert SI.rules_version().endswith("sysimpl-v3")


def test_p3_p4_chain_prompt_injects_camera_knowledge():
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    import writer_prompt as WP
    s = WP.system_for("P3-P4")
    assert "系统可实现性规则 v3" in s and "K-WRT-101" in s and "K-WRT-104" in s


def test_natural_language_beat_marks_are_accepted():
    t = (GOOD.replace("At 00:02.000,", "At the 2-second mark,").replace("At 00:04.000,", "At the 4-second mark,")
         .replace("At 00:05.500,", "At the 5.5-second mark,"))
    iss = L.lint_timeline(t, 6.58, sexes=["f", "m"], strict=True)
    assert not [i for i in iss if i["level"] == "error"], iss
    assert [round(x[2], 1) for x in L.find_stamps(t)] == [2.0, 4.0, 5.5]
