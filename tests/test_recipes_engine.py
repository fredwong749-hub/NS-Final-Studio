"""配方引擎（ARCH）：配方注册表 provenance 完整、选择器、编译确定性、提示词格式、Shot Spec 解析与缺字段清单。"""
import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "recipes"))

from ns_recipes import compiler as C  # noqa: E402
from ns_recipes import graph as G  # noqa: E402
from ns_recipes import prompt as PR  # noqa: E402
from ns_recipes import registry as R  # noqa: E402
from ns_recipes import selector as S  # noqa: E402
from ns_recipes import spec_import as SI  # noqa: E402
from ns_schema.shot_spec import (Audio, Beat, Camera, Continuity, H3Text, IdentityRef, Motion, OnScreenCharacter,  # noqa: E402
                                 Scene, ShotSpec, SpeechSeg, beat_gaps, check_sequence, frames_for_seconds,
                                 missing_fields)

FL2VA_TEXT = (
    "How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second "
    "mark of the target video; Picture 2 (from Shot 1) aligns with the 6.58-second mark of the target video.\n\n"
    "integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, a close shot begins "
    "in the position, framing and lighting established by Picture 1, a young woman with long hair at a desk. The camera "
    "pushes in with small amplitude at slow speed as she lifts her head, and settles into the pose established by "
    "Picture 2 at the end of the shot.\n\n"
    "overall_soundscape: Low office hum fills the room.\n\n"
    "non_diegetic_music: N/A")
EN_LW = "a young woman with long hair"


@pytest.fixture(scope="module")
def reg():
    return R.load(learned_path=ROOT / "tests" / "fixtures" / "_no_learned.yaml")


def mk(**kw) -> ShotSpec:
    base = dict(id="ep99-S1", episode=99, index=1, duration_s=6.0,
                scene=Scene(id="sk_x", time_of_day="白天"),
                camera=Camera(size="近景", move="push in"),
                characters_on_screen=[OnScreenCharacter(id="lin_wan", name="林晚", screen_x="左", depth="中",
                                                        facing="右", pose="坐", en_phrase=EN_LW,
                                                        identity_ref=IdentityRef(path="assets/x.png", sha="ab"))],
                motion=Motion(text="lnwan01，camera push in，林晚抬头——近景", end_state="近景"),
                audio=Audio(soundscape_en="Low office hum fills the room."),
                continuity=Continuity(link="换场"),
                h3=H3Text(mode="fl2va", text=FL2VA_TEXT))
    base.update(kw)
    return ShotSpec(**base)


# ---- 注册表 ----
def test_registry_valid_and_every_param_has_provenance(reg):
    assert reg.validate() == []
    assert {"dialogue_closeup", "walk_fullbody", "static_emotion", "two_person", "long_take", "establishing"} <= set(reg.ids())
    assert {"night", "flush_risk"} <= set(reg.overlays)


def test_license_pending_never_selectable(reg):
    for rid, r in reg.raw.items():
        if r.get("status") == "待许可登记":
            assert not S.selectable(r), rid


def test_validate_catches_missing_provenance(reg):
    bad = copy.deepcopy(reg)
    bad.raw["static_emotion"]["sampling"] = {"steps": 30}
    bad.raw["static_emotion"]["provenance"].pop("sampling.steps", None)
    bad.raw["_base"] = copy.deepcopy(bad.raw["_base"])
    bad.raw["_base"]["provenance"].pop("sampling.steps")
    assert any("sampling.steps" in e for e in bad.validate())


# ---- 选择器 ----
def test_select_types(reg):
    talk = mk(audio=Audio(soundscape_en="x", dialogue=[SpeechSeg(speaker="林晚", text="好。", t0=1, t1=2)]))
    assert S.select(talk, reg).recipe_id == "dialogue_closeup"
    assert S.select(mk(), reg).recipe_id == "static_emotion"
    walk = mk(camera=Camera(size="全景", move="tracking shot"), motion=Motion(text="林晚走向门口"))
    assert S.select(walk, reg).recipe_id == "walk_fullbody"
    empty = mk(characters_on_screen=[])
    assert S.select(empty, reg).recipe_id == "establishing"
    two = mk(characters_on_screen=[*mk().characters_on_screen,
                                   OnScreenCharacter(id="gu_chen", name="顾沉", screen_x="右", en_phrase="a man")])
    # V2 2026-10-31：双人镜首选 Ref2VA（lab_recipes.md 批 2），基模 two_person 作回退
    assert S.select(two, reg).recipe_id == "two_person_ref2va" and "two_person" in S.select(two, reg).fallback
    long_ = mk(duration_s=12.0)
    sel = S.select(long_, reg)
    assert sel.recipe_id == "long_take" and "long_take_two_stage" in sel.fallback


def test_overlays_night_and_flush(reg):
    sp = mk(scene=Scene(id="sk_x", time_of_day="深夜"),
            h3=H3Text(mode="fl2va", text=FL2VA_TEXT.replace("lifts her head", "lifts her flushed face")))
    sel = S.select(sp, reg)
    assert set(sel.overlays) == {"night", "flush_risk"}
    assert "static_emotion_pika" not in sel.fallback          # flush 镜头禁 Pika


def test_recipe_hint(reg):
    assert S.select(mk(recipe_hint="走动全身"), reg).recipe_id == "walk_fullbody"
    assert S.select(mk(recipe_hint="long_take_two_stage"), reg).recipe_id == "static_emotion"   # 不可选 → 按规则


# ---- 编译 ----
def test_compile_deterministic_same_hash(reg):
    a = C.compile_shot(mk(), reg)
    b = C.compile_shot(mk(), reg)
    assert a["plan_hash"] == b["plan_hash"] and a["status"] == "ready"
    c = C.compile_shot(mk(), reg, attempt=2)
    assert c["plan_hash"] != a["plan_hash"] and c["seed"] != a["seed"]
    d = C.compile_shot(mk(), reg, overrides={"sampling.steps": 30})
    assert d["plan_hash"] != a["plan_hash"] and d["graph"]["124"]["inputs"]["steps"] == 30


def test_imported_at_not_in_hash(reg):
    a = mk()
    b = mk()
    b.source.imported_at = "2026-11-01T00:00:00"
    assert C.compile_shot(a, reg)["plan_hash"] == C.compile_shot(b, reg)["plan_hash"]


def test_i2va_prompt_official(reg):
    p = C.compile_shot(mk(), reg)
    t = p["prompt"]["text"]
    assert t.splitlines()[0] == PR.I2VA_LINE
    assert "Picture 2" not in t and "<Picture 1>" in t
    assert p["mode"] == "i2va" and "last_frame" not in p["graph"]["131"]["inputs"]
    assert p["frames"] == 158 and (p["frames"] - 5) % 17 == 0
    assert p["api"]["compatible"] and p["api"]["body"]["base"] == "official_base"
    assert p["api"]["body"]["last_frame_mode"] == "none"


def test_retry_anchor_injected(reg):
    p = C.compile_shot(mk(), reg, attempt=2)
    assert "The frame keeps " + EN_LW in p["prompt"]["text"]
    assert "on the left side of the frame" in p["prompt"]["text"]


def test_needs_writer_when_no_h3(reg):
    p = C.compile_shot(mk(h3=H3Text()), reg)
    assert p["status"] == "needs_writer"


def test_lipsync_only_for_onscreen_dialogue(reg):
    assert C.compile_shot(mk(), reg)["acceptance"]["lipsync_corr_min"] is None
    talk = mk(audio=Audio(soundscape_en="x", dialogue=[SpeechSeg(speaker="林晚", text="好。", t0=1, t1=2)]))
    assert C.compile_shot(talk, reg)["acceptance"]["lipsync_corr_min"] == 0.3


def test_graph_variants_link_integrity(reg):
    sp = mk()
    for rid in ("walk_fullbody_motion_repair", "long_take_two_stage", "two_person_ref2va", "dialogue_closeup_pika"):
        p = C.compile_shot(sp, reg, recipe_id=rid)
        assert p["status"] == "ready", (rid, p["lint"])
        assert G.dangling_links(p["graph"]) == []
    ts = C.compile_shot(sp, reg, recipe_id="long_take_two_stage")
    classes = {n["class_type"] for n in ts["graph"].values()}
    assert {"SplitSigmas", "LTXVSeparateAVLatent", "MinimaxH3LatentUpscaler3D", "LTXVConcatAVLatent"} <= classes
    assert ts["graph"]["131"]["inputs"]["width"] == 544 and ts["graph"]["132"]["inputs"]["width"] == 768
    assert not ts["api"]["compatible"] and "two_stage" in ts["api"]["unsupported"]
    mr = C.compile_shot(sp, reg, recipe_id="walk_fullbody_motion_repair")
    assert mr["api"]["body"]["loras"] == [{"name": "Motion_Repair_V2.safetensors", "strength": 0.4}]   # V2：0.9 有害（lab_recipes.md D1）
    pk = C.compile_shot(sp, reg, recipe_id="dialogue_closeup_pika")
    assert pk["api"]["body"]["base"] == "pika_flex" and pk["graph"]["124"]["class_type"] == "ManualSigmas"
    assert "150" not in pk["graph"]


def test_ref2va_six_fields(reg, monkeypatch):
    # 身份槽按当前剧解析（L-126：V2 清单模式失败关闭）；这条测 V1 配方口径，显式钉在 V1（VQAGATE 11-02 18:4x）
    monkeypatch.setattr(C, "_primary_run", lambda: "series10_v1")
    p = C.compile_shot(mk(), reg, recipe_id="two_person_ref2va")
    t = p["prompt"]["text"]
    heads = [ln.split(":")[0] for ln in t.splitlines() if ln and ln.split(":")[0] in PR.REF_FIELDS]
    assert heads == list(PR.REF_FIELDS)
    # V2 20:20：纯 Ref2VA（不给首帧、不 AddGuide；lab_recipes.md E5 结论）→ <Picture 1> 是第一个身份参考
    assert "<Subject 1>" in t and "come from <Picture 1>" in t and "is the first frame" not in t
    assert "[reference generation]" in t
    assert p["graph"]["131"]["class_type"] == "MiniMaxH3ReferenceToVideo" and "170" not in p["graph"]
    assert p["mode"] == "ref2va" and not p["api"]["compatible"]
    # multiframe（E5）仍可由覆盖打开
    mf = C.compile_shot(mk(), reg, recipe_id="two_person_ref2va",
                        overrides={"ref2va.first_frame_slot0": True, "ref2va.add_guide_first_frame": True})
    assert "<Picture 1> is the first frame of [Shot 1]" in mf["prompt"]["text"]
    assert "[keyframe completion + reference generation]" in mf["prompt"]["text"]
    assert mf["graph"]["170"]["inputs"]["frame_idx"] == 0


def test_lint_flags_picture2_and_soundscape(reg):
    rc = reg.resolve("static_emotion")
    from ns_recipes import lint as L
    bad = PR.I2VA_LINE + "\n\nintegrated_multimodal_description: x established by Picture 2.\n\noverall_soundscape: \n\nnon_diegetic_music: N/A"
    codes = {i["code"] for i in L.lint_prompt(bad, "i2va", rc)}
    assert {"RL-A4", "RL-S1"} <= codes


def test_frames_grid():
    assert frames_for_seconds(6) == 158 and frames_for_seconds(8) == 192 and frames_for_seconds(12) == 294
    assert frames_for_seconds(4) == 107


# ---- Shot Spec ----
def test_missing_fields_and_overflow():
    sp = mk(audio=Audio(soundscape_en=None, dialogue=[SpeechSeg(speaker="林晚", text="x", t0=4.0, t1=5.9,
                                                                t_source="script")]))
    rules = {m.rule: m.severity for m in missing_fields(sp)}
    assert rules["SS-A3"] == "block" and rules["SS-A5"] == "block" and rules["SS-A1"] == "block"
    assert "SS-M1" in rules                                      # 6 s 无分拍


def test_beat_gaps():
    assert beat_gaps([Beat(t0=0, t1=2), Beat(t0=2, t1=4), Beat(t0=4, t1=6)], 6) == []
    assert beat_gaps([Beat(t0=0, t1=2), Beat(t0=3, t1=6)], 6)


def test_sequence_lr_swap():
    a = mk()
    b = mk(id="ep99-S2", index=2, continuity=Continuity(link="接力", from_prev="x"),
           characters_on_screen=[OnScreenCharacter(id="lin_wan", name="林晚", screen_x="右", en_phrase=EN_LW)])
    assert any(m.rule == "SS-X4" for m in check_sequence([a, b]))


def test_parse_markdown_fixture():
    sp = SI.specs_from_markdown(ROOT / "tests" / "fixtures" / "recipes_min_script.md", 9, with_assets=False)[0]
    assert sp.camera.size == "近景" and sp.camera.move == "push in"
    assert [c.screen_x for c in sp.characters_on_screen] == ["左", "右"]
    assert sp.characters_on_screen[0].facing == "右" and sp.characters_on_screen[1].pose == "站立"
    assert [b.t1 for b in sp.motion.beats] == [2.0, 4.0, 6.0]
    assert sp.audio.dialogue[0].t0 == 2.0 and sp.audio.dialogue[0].t_source == "script"
    assert sp.audio.mouth == {"顾沉": "open"}
    assert sp.scene.lighting.key == "左侧暖台灯" and sp.scene.landmarks[0].name == "a desk lamp"
    assert sp.h3.mode == "fl2va" and sp.continuity.to_next
    assert sp.characters_on_screen[0].look == "black fitted top"
