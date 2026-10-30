"""T08：Frame Spec 的 gpu3 字段（focus_part / gaze / screen_share / 只含表情词的 expression / 时间线复用）。

金标准：tests/fixtures/t06_golden/prompts_before.json —— T08 只增 spec 字段，首帧/尾帧提示词、facts、角色、校验结果必须逐字不变。
"""
import importlib.util
import json
from pathlib import Path

import pytest

from ns_agent import bible as B
from ns_agent import frame_spec as F
from ns_schema.frame_spec import FrameSpec
from ns_schema.script import CharacterLock, Episode, ScriptGlobals, ScriptImport, Shot

FIX = Path(__file__).parent / "fixtures" / "t06_golden"
REPO = Path(__file__).resolve().parents[1]
G0 = ScriptGlobals(image_suffix="85mm人像镜头f/1.2大光圈，无字幕、无文字、无水印",
                   character_locks=[CharacterLock(name="林晚", description="蓝发及腰、齐刘海")])


def _spec(img: str, motion: str = "lnwan01，static，她不动", **kw) -> FrameSpec:
    ep = Episode(number=1, title="t", source_line=1)
    s = Shot(episode=1, index=1, img_prompt=img, motion_prompt=motion, motion_triggers=["lnwan01"], source_line=1)
    return F.build_spec(ep, s, G0, **kw)


def _char(spec: FrameSpec, cid: str):
    return next(c for c in spec.characters if c.id == cid)


# ------------------------------------------------------------------ 表情 sanitizer：去掉什么（一览）

# (输入, 保留, [去掉的 “片段｜原因”])
SANITIZE_CASES = [
    ("微笑，脸颊泛红", "微笑，脸颊泛红", []),
    ("微笑，穿着黑色漆皮高跟鞋", "微笑", ["穿着黑色漆皮高跟鞋｜clothing"]),
    ("含泪、白衬衫领口敞开", "含泪", ["白衬衫领口敞开｜clothing"]),
    ("惊讶，特写镜头", "惊讶", ["特写镜头｜camera"]),
    ("羞涩，镜头缓慢推近", "羞涩", ["镜头缓慢推近｜camera"]),
    ("咬唇，低头看向手机", "咬唇", ["低头看向手机｜gaze"]),
    ("紧张，直视镜头", "紧张", ["直视镜头｜camera"]),       # 镜头词优先于视线词
    ("得意；转身走向门口", "得意", ["转身走向门口｜action"]),
    ("端庄 双手捧着文件夹", "端庄", ["双手捧着文件夹｜action"]),
    ("闭眼，坐在床边", "闭眼", ["坐在床边｜action"]),
    ("抿唇，口红", "抿唇", ["口红｜clothing"]),
    ("嘴角微微上扬，夜晚的街道", "嘴角微微上扬", ["夜晚的街道｜not_expression"]),
    ("眼神迷离，微笑，微笑", "眼神迷离，微笑", []),         # 去重
    ("", "", []),
]


@pytest.mark.parametrize("text,kept,stripped", SANITIZE_CASES)
def test_sanitize_expression_lists_what_it_strips(text, kept, stripped):
    assert F.sanitize_expression(text) == (kept, stripped)


def test_expression_terms_need_expression_context():
    # 旧版按单字命中：湿透的衬衫 → 睫毛湿润，抿了一口汤 → 抿唇，环咬着 → 咬唇
    assert F.expression_terms("她湿透的衬衫贴在身上") == ""
    assert F.expression_terms("她抿了一口汤") == ""
    assert F.expression_terms("珠链和环咬着结合处") == ""
    assert F.expression_terms("嘴唇抿了抿把笑意压回去") == "微笑，抿唇"
    assert F.expression_terms("她咬住沾着唇膏的下唇") == "咬唇"
    assert F.expression_terms("她咬牙") == "咬牙"
    assert F.expression_terms("捂住嘴笑，耳根通红") == "微笑，耳根泛红"
    assert F.expression_terms("睫毛上挂着夜的湿气") == "睫毛湿润"
    assert F.expression_terms("她端庄地微笑") == "微笑，端庄"


def test_llm_refine_expression_is_sanitized():
    spec = _spec("近景，林晚坐在工位前")
    out = json.dumps({"first_frame": {"expression": "微笑，穿着白衬衫，低头"},
                      "characters": [{"name": "林晚", "expression": {"start": "羞涩，特写镜头", "end": "得意"}}]},
                     ensure_ascii=False)
    s = Shot(episode=1, index=1, img_prompt="近景，林晚坐在工位前", motion_prompt="lnwan01，static，她不动",
             motion_triggers=["lnwan01"], source_line=1)
    new = F.refine_with_llm(spec, s, lambda _: out)
    assert new.generator.startswith("rules+llm")
    assert new.first_frame.expression == "微笑"
    assert _char(new, "lin_wan").expression.start == "羞涩" and _char(new, "lin_wan").expression.end == "得意"
    assert "first_frame：穿着白衬衫｜clothing" in new.expression_stripped
    assert "林晚.start：特写镜头｜camera" in new.expression_stripped


def test_validate_flags_dirty_expression():
    spec = _spec("近景，林晚坐在工位前")
    spec.first_frame.expression = "微笑，高跟鞋"
    assert any(p.startswith("表情含非表情词") for p in F.validate(spec))


# ------------------------------------------------------------------ focus_part

@pytest.mark.parametrize("img,part,label,src", [
    ("特写她的脚，脚趾微微蜷起", "foot", "脚", "text"),
    ("高跟鞋特写，鞋跟敲在大理石上", "shoes", "高跟鞋", "text"),
    ("手部特写，她的指尖划过桌面", "hand", "手", "text"),
    ("极近特写，她的手机屏幕亮起“在吗”", "screen", "屏幕", "guess"),
    ("近景，林晚的脸被台灯照亮", "face", "脸", "guess"),
    ("镜头推向她的高跟鞋，林晚站在门口", "shoes", "高跟鞋", "text"),
    ("中景，林晚坐在床边", "", "", "none"),
])
def test_focus_part(img, part, label, src):
    spec = _spec(img)
    assert (spec.focus_part, spec.focus_label, spec.focus_part_source) == (part, label, src)


def test_focus_hand_is_not_phone():
    assert _spec("特写，桌上的手机亮起").focus_part == "object"


# ------------------------------------------------------------------ gaze

@pytest.mark.parametrize("img,target,cue", [
    ("近景，林晚看向镜头", "camera", "看向镜头"),
    ("近景，林晚直视前方", "camera", "直视"),
    ("近景，林晚低头", "down", "低头"),
    ("近景，林晚抬眼", "up", "抬眼"),
    ("近景，林晚闭着眼", "closed", "闭着眼"),
    ("近景，林晚盯着手机", "object", "盯着手机"),
    ("近景，林晚看向窗外", "away", "看向窗外"),
    ("全景，林晚的背影", "away", "背影"),
])
def test_gaze_cues(img, target, cue):
    g = _char(_spec(img), "lin_wan").gaze_start
    assert (g.target, g.cue, g.source) == (target, cue, "text")


def test_gaze_other_character_and_subject():
    spec = _spec("中景，林晚侧脸看向他，顾沉低头看文件", motion="lnwan01，static，两人不动")
    lw, gc = _char(spec, "lin_wan"), _char(spec, "gu_chen")
    assert (lw.gaze_start.target, lw.gaze_start.at, lw.gaze_start.source) == ("other", "gu_chen", "guess")  # 侧脸 先出现
    assert (gc.gaze_start.target, gc.gaze_start.source) == ("down", "text")
    spec = _spec("中景，顾沉看着她", motion="lnwan01，static，林晚不动")
    assert (_char(spec, "gu_chen").gaze_start.target, _char(spec, "gu_chen").gaze_start.at) == ("other", "lin_wan")


def test_gaze_defaults_and_end_frame():
    alone = _char(_spec("中景，林晚坐在床边"), "lin_wan")
    assert (alone.gaze_start.target, alone.gaze_start.source) == ("away", "guess")
    assert (alone.gaze_end.target, alone.gaze_end.source) == ("away", "same")
    two = _spec("中景，林晚和顾沉站在电梯里")
    assert (_char(two, "lin_wan").gaze_start.target, _char(two, "lin_wan").gaze_start.at) == ("other", "gu_chen")
    end = _char(_spec("近景，林晚低头", motion="lnwan01，static，她低头——缓缓抬眼看向镜头"), "lin_wan")
    assert end.gaze_start.target == "down" and (end.gaze_end.target, end.gaze_end.source) == ("camera", "text")


# ------------------------------------------------------------------ screen_share

def test_screen_share_primary_secondary_bokeh():
    spec = _spec("近景，林晚坐在前景，顾沉在背景虚化")
    lw, gc = _char(spec, "lin_wan"), _char(spec, "gu_chen")
    assert (lw.screen_share_value, lw.screen_share_source, lw.screen_position) == (0.5, "guess", "foreground")
    assert gc.clarity == "bokeh" and gc.screen_share_value == 0.1 and gc.screen_position == "background"
    spec = _spec("中景，林晚和顾沉面对面站着")
    assert _char(spec, "lin_wan").screen_share_value == 0.4 and _char(spec, "gu_chen").screen_share_value == 0.24
    assert _char(spec, "gu_chen").screen_share == "0.24（次要人物）"
    assert _char(_spec("特写，林晚的脸占满画面"), "lin_wan").screen_share_source == "text"


# ------------------------------------------------------------------ 时间线复用

def test_timeline_fields_reused_verbatim():
    tl = {"shot_id": "ep01-S1", "inputs_sha": "abc123", "framing": "full", "framing_source": "guess",
          "faces_visible": ["lin_wan"], "faces_visible_source": "text",
          "props": [{"id": "lora-ptxcorset", "name": "黑色漆皮束腰", "state": "hanging", "state_source": "text",
                     "state_end": "hanging", "state_end_source": "text", "holder": None, "mention": "束腰",
                     "trigger": "ptxcorset", "trigger_conflict": True, "look_conflict": False}],
          "characters": {"lin_wan": {"changes_within_shot": [{"slot": "outfit", "item": "lora-ptxcorset",
                                                              "from": "worn", "to": "removed", "source": "guess"}],
                                     "items_end": {"outfit": []}, "visibility_end": "visible"}}}
    spec = _spec("中景，林晚站在墙边，束腰挂在墙上", timeline_shot=tl)
    lw = _char(spec, "lin_wan")
    assert (spec.framing, spec.framing_source, spec.faces_visible, spec.timeline_inputs_sha) == (
        "full", "guess", ["lin_wan"], "abc123")
    assert spec.prop_states[0].id == "lora-ptxcorset" and spec.prop_states[0].state == "hanging"
    assert lw.face_visible is True and lw.items_end == {"outfit": []} and lw.changes_within_shot[0]["to"] == "removed"
    kinds = {r.split("：")[0] for r in spec.risks}
    assert kinds == {"far_small_face", "trigger_conflict", "wardrobe_change"}
    # 不给时间线：同一规则现算，timeline_inputs_sha = None
    bare = _spec("中景，林晚站在墙边，束腰挂在墙上")
    assert bare.timeline_inputs_sha is None and bare.framing == "medium" and bare.prop_states == []


# ------------------------------------------------------------------ 金标准 + 全剧 360 镜

def _snapshot_mod():
    spec = importlib.util.spec_from_file_location("t06_snapshot", FIX / "snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_golden_prompts_unchanged_with_t08_fields_and_timeline():
    """T08 只增字段：带上时间线后，360 镜的 qwen / qwen_last / facts / 角色 / 校验 与 T06 金标准逐字相同"""
    b = B.load_bible(root=FIX)
    before = json.loads((FIX / "prompts_before.json").read_text(encoding="utf-8"))
    script = ScriptImport.model_validate_json((FIX / "data" / "import" / "script_v2.json").read_text(encoding="utf-8"))
    tl = F.load_timeline_index(REPO)   # 仓库时间线（没有也行：字段现算）
    g = script.globals
    all_trig = {t.trigger for t in g.lora_triggers if t.file}
    specs, diff = [], []
    for ep in script.episodes:
        for s in ep.shots:
            for tag, trig in (("spec_none", set()), ("spec_all", all_trig)):
                sp = F.build_spec(ep, s, g, available_triggers=trig, bible=b, timeline_shot=tl.get(s.id))
                row = {"qwen": sp.model_prompt.qwen, "qwen_last": sp.model_prompt.qwen_last,
                       "facts": [[f.text, f.kind, f.must, f.frame] for f in sp.facts],
                       "characters": [c.name for c in sp.characters], "validation": sp.validation}
                diff += [(s.id, tag, k) for k in row if json.loads(json.dumps(row[k], ensure_ascii=False))
                         != before[s.id][tag][k]]
                if tag == "spec_all":
                    specs.append(sp)
    assert len(specs) == 360 and diff == []
    st = F.spec_stats(specs)
    assert st["shots"] == 360 and st["validation_problems"] == 0 and st["expression_dirty"] == 0
    assert sum(st["focus_part"].values()) == 360 and set(st["focus_part"]) >= {"hand", "eye", "face"}
    assert set(st["gaze_start"]) <= {"camera", "other", "down", "up", "away", "object", "closed", "unknown"}
    assert st["gaze_start_source"].get("text", 0) > 30
    for sp in specs:   # 每个字段都能被 gpu3 原样读回
        assert FrameSpec.model_validate(sp.model_dump()) == sp
