"""FIX（ep02_iter P0 止血，docs/ep02_iter/refactor_proposal.md §4 P0 + chain_audit A2/A3/A4/A12/B4/C2/C5/E3/E6/E7）。
纯 CPU，不碰真数据。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("packages/schema", "services/agent", "services/render_router", "services/api", "tools"):
    sys.path.insert(0, str(ROOT / p))

from ns_agent import compiler as C  # noqa: E402
from ns_schema.script import CharacterLock, Episode, ScriptGlobals, Shot  # noqa: E402

G = ScriptGlobals(image_suffix="85mm人像镜头f/1.2大光圈",
                  character_locks=[CharacterLock(name="林晚", description="蓝发"),
                                   CharacterLock(name="顾沉", description="34岁成年男性CEO")])


def _shot(img, motion="lnwan01，她抬眼——低头", idx=1):
    ep = Episode(number=2, title="t", source_line=1)
    s = Shot(episode=2, index=idx, img_prompt=img, img_triggers=[], motion_prompt=motion,
             motion_triggers=["lnwan01"] if motion.startswith("lnwan01") else [], source_line=1)
    return ep, s


def _g_with_video_lora():
    from ns_schema.script import LoraTrigger
    return G.model_copy(update={"lora_triggers": [LoraTrigger(trigger="lnwan01", kind="video", description="林晚视频身份",
                                                              file="lin_wan_h3_v1.safetensors", strength=[0.6, 1.0])]})


# ---------------- A2 系统后缀不得覆盖本镜原文的明确要求

def test_face_hidden_drops_face_clauses_from_suffix():
    g = C.DEFAULT_PROMPT_GUARD
    t = "暗部保留细节，面部可辨，画面光比1:4，非纯黑"
    out = C.guard_term(t, "特写，夜晚，蓝发垂落遮住部分脸部，只露出下巴", g)
    assert "面部" not in out and "暗部保留细节" in out and "非纯黑" not in out   # 否定子句改写
    assert C.guard_term("面部清晰对焦，五官锐利", "特写，只露出下巴", g) == ""


def test_black_end_state_drops_not_black():
    g = C.DEFAULT_PROMPT_GUARD
    out = C.guard_term("暗部保留细节，面部可辨，画面光比1:4，非纯黑", "衣橱昏暗，衣橱门缓缓关上，画面陷入全黑", g)
    assert "非纯黑" not in out and "面部可辨" not in out and "暗部仍有可见层次" not in out


def test_unchanged_term_keeps_separators():
    g = dict(C.DEFAULT_PROMPT_GUARD, cfg_one_positive_only=False)
    assert C.guard_term("衣装完整、无裸露", "写字楼", g) == "衣装完整、无裸露"
    assert C.guard_term("暗部保留细节，面部可辨，画面光比1:4，非纯黑", "夜", g) == "暗部保留细节，面部可辨，画面光比1:4，非纯黑"


def test_compile_s11_like_shot_has_no_conflicting_system_words():
    ep, s = _shot("特写，夜晚衣橱内，林晚的手挂外套，蓝发垂落遮住部分脸部，只露出下巴和颈部线条，背景深邃黑暗",
                  motion="lnwan01，camera push in 缓推，手指停留——衣橱门缓缓关上，画面陷入全黑")
    c = C.compile_shot(ep, s, G, set())
    assert "面部可辨" not in c.image_prompt and "面部清晰对焦" not in c.image_prompt
    assert "非纯黑" not in c.last_prompt and "面部可辨" not in c.last_prompt
    assert c.prompt_lint == []


def test_lint_prompt_flags_conflict():
    errs = C.lint_prompt("蓝发遮住脸，面部可辨，非纯黑", "蓝发遮住脸，画面陷入全黑")
    assert len(errs) == 2


# ---------------- A3 cfg=1：正向不放否定子句；负面词不送不记

def test_cfg1_safe_term_positive_only():
    ep, s = _shot("写字楼工位，林晚低头")
    c = C.compile_shot(ep, s, G, set())
    assert "衣装完整" in c.image_prompt and "无裸露" not in c.image_prompt
    assert c.video_negative_status == "ignored_cfg1"


def test_negative_dropped_when_cfg_le_1():
    from ns_render import pipeline as P
    from ns_render import workflows as W
    turbo, base = W.QwenModel(), W.QwenModel(turbo=False, cfg=3.0)
    assert W.negative_for(turbo, "字幕") == "" and W.negative_for(base, "字幕") == "字幕"
    wf = W.qwen_t2i("p", "字幕、水印", 64, 64, 1, "x", m=turbo)
    assert wf["20"]["inputs"]["negative_prompt"] == "" and wf["38"]["inputs"]["cfg"] == 1.0
    wf = W.qwen_t2i("p", "字幕、水印", 64, 64, 1, "x", m=base)
    assert wf["20"]["inputs"]["negative_prompt"] == "字幕、水印"
    ep, s = _shot("写字楼工位，林晚低头")
    c = C.compile_shot(ep, s, G, set())
    assert P.image_negative(c, turbo) == "" and P.image_negative(c, base) == c.image_negative
    assert P.image_negative(c) == c.image_negative   # 不给模型 = 旧行为（只供显示 / 编辑）


# ---------------- A4 / P0 ⑦ “提到名字” ≠ “人在画面”

def test_object_possessive_is_mention_only():
    ep, s = _shot("特写，林晚在出租车后座，脸埋进顾沉的西装衣领，闭着眼")
    c = C.compile_shot(ep, s, G, set())
    assert "【顾沉】" not in c.image_prompt and c.mentioned_only == ["顾沉"]


def test_body_part_possessive_counts_as_present():
    for img in ("特写，顾沉的手指指向屏幕，林晚仰头", "中景，林晚仰头注视顾沉的背影", "叠影中顾沉的吻，林晚闭眼"):
        ep, s = _shot(img)
        assert "【顾沉】" in C.compile_shot(ep, s, G, set()).image_prompt, img


def test_object_possessive_owner_then_he_is_present():
    ep, s = _shot("中景，她与顾沉的日常：他递给她一片西瓜")
    assert "【顾沉】" in C.compile_shot(ep, s, G, set()).image_prompt


# ---------------- C2/E3 视频身份 LoRA 按角色确定，与道无关

def test_video_lora_independent_of_lane(monkeypatch):
    g = _g_with_video_lora()
    on = dict(C.DEFAULT_PROMPT_GUARD, video_identity_enabled=True)
    monkeypatch.setattr(C, "prompt_guard", lambda root=None: on)
    ep, s = _shot("近景，林晚抬眼")
    a = C.compile_shot(ep, s, g, set())
    b = C.compile_shot(ep, s, g, {"lin_wan_h3_v1.safetensors"})
    assert a.video_loras == b.video_loras == [("lin_wan_h3_v1.safetensors", 1.0)]
    ep, s = _shot("中景，陈宇站在玄关，林晚背对镜头站在厨房方向")
    c = C.compile_shot(ep, s, g, {"lin_wan_h3_v1.safetensors"})
    assert c.video_loras == [] and "背对" in c.video_loras_dropped[0]


def test_video_identity_disabled_is_deterministic_off():
    ep, s = _shot("近景，林晚抬眼")
    g = _g_with_video_lora()
    for avail in (set(), {"lin_wan_h3_v1.safetensors"}):
        c = C.compile_shot(ep, s, g, avail)
        assert c.video_loras == [] and "未启用" in c.video_loras_dropped[0]


def test_render_refuses_lane_without_required_lora():
    from ns_render import h3_video as HV
    assert HV.missing_video_loras([("a.safetensors", 1.0)], {"b.safetensors"}) == ["a.safetensors"]
    assert HV.missing_video_loras([], set()) == []
    e = HV.MissingVideoLora(["a.safetensors"], "gpu36:0")
    assert "不在缺 LoRA 的道上出片" in str(e)


def test_dispatch_reroutes_to_lane_with_lora():
    from fastapi import HTTPException
    from ns_api import video_jobs as VJ
    avail = {3: {"x"}, "gpu36:0": {"lin_wan_h3_v1.safetensors"}}
    lanes = [{"gpu": 3, "ok": True, "max_frames": 362}, {"gpu": "gpu36:0", "ok": True, "max_frames": 362}]
    need = [("lin_wan_h3_v1.safetensors", 1.0)]
    r = VJ.lane_with_video_loras(3, need, 158, avail_of=lambda g: avail[g], lane_list=lanes)
    assert r["lane"] == "gpu36:0"
    assert VJ.lane_with_video_loras(3, [], 158, avail_of=lambda g: set())["lane"] == 3
    with pytest.raises(HTTPException) as ei:
        VJ.lane_with_video_loras(3, need, 158, avail_of=lambda g: set(), lane_list=lanes)
    assert ei.value.status_code == 409


# ---------------- C5 只给首帧时正文不得引用 Picture 2

H3 = ("How the reference pictures align with the target video — x\n\nintegrated_multimodal_description: [Shot 1] "
      "A shot begins in the framing established by Picture 1. (S1) says: <d>[Chinese] 方案第三页。</d> "
      "She leans in, her expression intense, and settles into the pose, spacing, and composition established by "
      "Picture 2 at the end of the shot.\n\noverall_soundscape: Hum.\n\nnon_diegetic_music: N/A")


def test_i2v_prompt_removes_picture2_keeps_action_and_dialogue():
    from ns_render import h3_video as HV
    out, removed = HV.i2v_prompt(HV.realign(H3, 158))
    assert out.split("\n")[0] == HV.I2V_ALIGN_LINE and "Picture 2" not in out
    assert "She leans in, her expression intense." in out and "<d>[Chinese] 方案第三页。</d>" in out
    assert "established by <Picture 1>" in out and len(removed) == 1
    whole = H3.replace("She leans in, her expression intense, and settles", "She settles")
    out2, _ = HV.i2v_prompt(HV.realign(whole, 158))
    assert "Picture 2" not in out2 and "She settles" not in out2 and ". ." not in out2
    assert HV.i2v_prompt("自由文本\n第二行") == ("自由文本\n第二行", [])


# ---------------- E6 Take.gpu 接受字符串道 id

def test_take_accepts_string_lane():
    from ns_schema.edits import Take
    t = Take(n=1, stage="video", file="x.mp4", seed=1, prompt="p", seconds=1.0, created_at="t", gpu="gpu36:0")
    assert t.gpu == "gpu36:0" and Take(n=1, stage="video", file="x", seed=1, prompt="", seconds=1.0,
                                       created_at="t", gpu=3).gpu == 3


# ---------------- E7 坏图闸门按后处理后尺寸比较

def test_bad_image_gate_accepts_post_size(tmp_path):
    from PIL import Image
    from ns_render import image_check as IC
    f = tmp_path / "image_006_post.png"
    Image.effect_noise((768, 1344), 60).convert("RGB").save(f)
    take = {"stage": "image", "file": f.name, "params": {
        "post": {"size": [768, 1344], "rendered_size": [1152, 2016], "file": "other.png"},
        "effective": {"width": 768, "height": 1344, "rendered_size": [1152, 2016]}}}
    old = IC.ENABLED
    IC.ENABLED = True
    try:
        assert IC.check_take(take, tmp_path) is None            # post.file 对不上也不误判
        take["params"] = {"effective": {"rendered_size": [2000, 3000]}}
        assert "与请求的" in (IC.check_take(take, tmp_path) or "")
    finally:
        IC.ENABLED = old


# ---------------- A12 / B4 写作模型输出确定性校验

def test_writer_output_check_rules():
    from ns_schema import llm_output_check as L
    names = {"顾沉": ["顾沉", "Gu Chen"], "林晚": ["林晚", "Lin Wan"]}
    good = "The young East Asian woman looks up. (S1) says: <d>[Chinese] 方案第三页，数据错了。</d> She swallows."
    r = L.check_writer_output(good, dialogue=["方案第三页，数据错了。"], names=names,
                              on_screen_anchors={"林晚": ["East Asian"]})
    assert r.ok, r.errors
    bad = ("Gu Chen leans in. (S1) says: <d>[Chinese] 顾沉，声音低沉克制：方案第三页，数据错了。</d> "
           "She buries her face in the collar of a 34-year-old adult male CEO.")
    r = L.check_writer_output(bad, dialogue=["方案第三页，数据错了。"], names=names,
                              on_screen_anchors={"林晚": ["East Asian"]},
                              absent_phrases={"顾沉": ["34-year-old adult male CEO"]})
    assert {e["rule"] for e in r.errors} == {"D1", "D2", "N1", "A1", "P1"}
    r = L.check_writer_output("x <d>[Chinese, Chen Yu's warm voice] 这么大的外套？</d>", dialogue=["这么大的外套？"])
    assert any(e["rule"] == "D1" for e in r.errors)


def test_validator_possessive_object_not_stray():
    import validate_qwen_script as V  # noqa: F401  （导入即检查新规则表与依赖）
    assert "H3-X4" in V.LINT_RULE_TEXT and "H3-X6" in V.LINT_RULE_TEXT
