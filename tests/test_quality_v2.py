"""画质 v2：身份底板参考、Leica 措辞、调色、尾帧、多候选评分、导演加强、Frame Spec（不连 ComfyUI、不用 GPU）。"""
import json

import numpy as np
import pytest
from PIL import Image

from ns_agent import compiler as C
from ns_agent import frame_spec as F
from ns_render import grade as G
from ns_render import pipeline as P
from ns_render import refs as R
from ns_render import score as S
from ns_render import workflows as W
from ns_schema.edits import EpisodeEdit, ShotEdit
from ns_schema.frame_spec import Fact, FrameSpec, ScriptRef
from ns_schema.script import CharacterLock, Episode, ScriptGlobals, Shot

STYLE = ("专业电影镜头画面感，画面干净，85mm人像镜头f/1.2大光圈，主体锐利对焦，前景与背景奶油般柔焦虚化、柔和圆形光斑，"
         "浓郁饱和的暖色调电影调色，无字幕、无文字、无水印")
G0 = ScriptGlobals(image_suffix=STYLE, character_locks=[CharacterLock(name="林晚", description="蓝发及腰、齐刘海")])


def _shot(img, motion="lnwan01，camera push in 缓慢推近，她低头掩饰，睫毛颤动——抬眼又立刻低头", ep=1, i=3):
    return Episode(number=ep, title="t", source_line=1), Shot(episode=ep, index=i, img_prompt=img, motion_prompt=motion,
                                                             motion_triggers=["lnwan01"], source_line=1)


# ------------------------------------------------------------------ 编译器：Leica、尾帧、导演加强

def test_leica_term_follows_suffix_lens_and_is_not_duplicated():
    ep, s = _shot("极近特写，林晚低头侧脸")
    c = C.compile_shot(ep, s, G0, set())
    assert "Leica Summilux-SL 85mm f/1.2" in c.image_prompt and c.image_prompt.count("Leica") == 1
    assert c.image_prompt.index("Leica") < c.image_prompt.index(STYLE)       # 镜头质感在风格后缀前
    assert "林晚低头侧脸" in c.image_prompt                                  # 原文透传
    g = G0.model_copy(update={"image_suffix": "Leica SL3 锐利，" + STYLE})
    assert C.compile_shot(ep, s, g, set()).image_prompt.count("Leica") == 1  # 后缀已有 Leica 不再加


@pytest.mark.parametrize("motion,end", [
    ("camera push in，她低头掩饰——抬眼又立刻低头", "抬眼又立刻低头"),
    ("static camera，她挂好外套，然后关上衣橱门——黑暗吞没", "黑暗吞没"),
    ("camera static，看很久，然后对镜中的自己笑了一下——像在问“是你吗”", "看很久，然后对镜中的自己笑了一下"),
    ("time-lapse 延时感剪辑，纸巾越堆越多；最后一次她放下笔，镜中出现红唇", "最后一次她放下笔，镜中出现红唇"),
    ("handheld follow，张口——咽下——然后极轻地抬头", "极轻地抬头"),
])
def test_end_state(motion, end):
    assert C.end_state(motion) == end


def test_last_prompt_has_continuity_and_end_state():
    ep, s = _shot("极近特写，林晚低头侧脸")
    c = C.compile_shot(ep, s, G0, set())
    assert c.last_prompt.startswith("图1是本镜头的首帧画面。") and "同一场景同一人物同一服装" in c.last_prompt
    assert "抬眼又立刻低头" in c.last_prompt and c.end_state == "抬眼又立刻低头"


def test_boost_verbatim_before_style_and_empty_adds_nothing():
    ep, s = _shot("极近特写，林晚低头侧脸")
    base = C.compile_shot(ep, s, G0, set())
    assert C.boost_text(None, "", "  ") == ""
    assert C.compile_shot(ep, s, G0, set(), boost_first="", boost_last="").image_prompt == base.image_prompt
    b = C.boost_text("整集：眼神更冷", "镜头：睫毛挂泪")
    assert b == "整集：眼神更冷，镜头：睫毛挂泪"                       # 整集在前、镜头在后
    c = C.compile_shot(ep, s, G0, set(), boost_first=b, boost_last="尾帧加强 X")
    assert b in c.image_prompt and c.image_prompt.index(b) < c.image_prompt.index("Leica")
    assert c.image_prompt.index("林晚低头侧脸") < c.image_prompt.index(b)
    assert "尾帧加强 X" in c.last_prompt and "尾帧加强 X" not in c.image_prompt
    assert b not in c.last_prompt


def test_apply_edit_keeps_boost_on_full_override():
    c = P.CompiledShot(shot_id="x", adult=False, adult_reasons=[], image_prompt="", image_negative="", image_loras=[],
                       video_prompt="", video_negative="", video_loras=[], boost_first="导演加强A")
    out = P.apply_edit(c, ShotEdit(image_prompt=f"人工整段，{STYLE}"), STYLE)
    assert out.image_prompt == f"人工整段，导演加强A，{STYLE}"
    again = P.apply_edit(out, ShotEdit(image_prompt=out.image_prompt), STYLE)
    assert again.image_prompt.count("导演加强A") == 1


def test_episode_edit_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "RENDERS", tmp_path)
    assert P.load_episode_edit(3).boost_first is None
    P.save_episode_edit(3, EpisodeEdit(boost_first="整集加强"))
    assert json.loads((tmp_path / "ep03" / "episode_edit.json").read_text(encoding="utf-8"))["boost_first"] == "整集加强"
    assert P.load_episode_edit(3).boost_first == "整集加强"


# ------------------------------------------------------------------ 参考图：身份底板

@pytest.mark.parametrize("items,text,design", [
    (["lw-makeup-bare"], "林晚低头", "M1"), (["lw-makeup-heavy"], "林晚", "M4"), ([], "林晚", "M0"),
    (["lw-makeup-bare"], "镜中出现“恰到好处的减半红唇”", "M2"), ([], "涂抹正红唇膏", "M3"), ([], "泪痕未干", "M6"),
])
def test_makeup_design(items, text, design):
    assert R.makeup_design(items, text) == design


def _assets(tmp_path, monkeypatch, angle_plates=()):
    base = tmp_path / "lin_wan"
    mk = base / "items" / "makeup"
    mk.mkdir(parents=True)
    entries = []
    for d in ("M0", "M1", "M4"):
        Image.new("RGB", (1024, 1280), (128, 128, 128)).save(mk / f"{d}_s0.png")
        entries.append({"file": f"{d}_s0.png", "kind": "item/makeup", "design": d})
    (mk / "manifest.json").write_text(json.dumps(entries), encoding="utf-8")
    if angle_plates:
        pl = base / "plates"
        pl.mkdir()
        for a in angle_plates:
            Image.new("RGB", (768, 1344), (100, 100, 100)).save(pl / f"{a}.png")
        (pl / "manifest.json").write_text(json.dumps([{"file": f"{a}.png", "angle": a} for a in angle_plates]))
    monkeypatch.setattr(R, "CHAR_DIR", tmp_path)
    monkeypatch.setattr(R, "CACHE", tmp_path / "cache")
    monkeypatch.setattr(R, "OWNER_FACE", {})
    return base


def test_plan_refs_uses_makeup_plate_and_role_line(tmp_path, monkeypatch):
    _assets(tmp_path, monkeypatch)
    plan = R.plan_refs("极近特写，林晚低头侧脸", ["林晚", "顾沉"], {"林晚": {"makeup": ["lw-makeup-bare"]}})
    assert [r.kind for r in plan.refs] == ["face"] and plan.face.path.name == "M1_s0.png"   # 顾沉没有底板
    line = plan.role_lines()
    assert line.startswith("图1只提供林晚的面部身份与发型") and "不要沿用图1的姿势、表情、服装、首饰、背景" in line
    out = R.prescale(plan.face)
    w, h = Image.open(out).size
    assert w % 32 == 0 and h % 32 == 0 and abs(w * h - 768 * 768) < 0.1 * 768 * 768


def test_angle_plate_preferred_when_present(tmp_path, monkeypatch):
    _assets(tmp_path, monkeypatch, angle_plates=("B",))
    assert R.plan_refs("林晚背对镜头洗碗", ["林晚"]).face.path.name == "B.png"
    assert R.plan_refs("林晚侧脸", ["林晚"]).face.path.name == "M0_s0.png"     # 没有侧脸底板 → 妆容底板


def test_no_plates_no_refs(tmp_path, monkeypatch):
    monkeypatch.setattr(R, "CHAR_DIR", tmp_path)
    monkeypatch.setattr(R, "OWNER_FACE", {})
    assert R.plan_refs("林晚", ["林晚"]).refs == [] and R.plan_refs("x", []).role_lines() == ""


def test_real_plates_registered():
    # 项目方参考图脸部裁切优先（2026-10-30），不管妆容状态
    plan = R.plan_refs("林晚", ["林晚"], {"林晚": {"makeup": ["lw-makeup-heavy"]}})
    master = R.CHAR_DIR / "lin_wan" / "plates" / "master.png"
    want = "master_face_" if master.exists() else "lw_face_closeup_768"     # 母版只用脸部裁切
    assert plan.face and plan.face.path.name.startswith(want)
    assert R.plan_refs("顾沉", ["顾沉"]).refs == []


def test_realistic_plate_preferred(tmp_path, monkeypatch):
    base = _assets(tmp_path, monkeypatch)
    assert R.plan_refs("林晚", ["林晚"], {"林晚": {"makeup": ["lw-makeup-heavy"]}}).face.path.name == "M4_s0.png"
    (base / "plates").mkdir()
    Image.new("RGB", (64, 96)).save(base / "plates" / "master.png")
    assert R.plan_refs("林晚", ["林晚"], {"林晚": {"makeup": ["lw-makeup-heavy"]}}).face.path.name == "master.png"
    Image.new("RGB", (64, 96)).save(base / "items" / "makeup" / "M4_real.png")
    assert R.plan_refs("林晚", ["林晚"], {"林晚": {"makeup": ["lw-makeup-heavy"]}}).face.path.name == "M4_real.png"


def test_multi_ref_edit_without_crop():
    wf = W.qwen_edit("p", "n", ["a.png", "b.png"], 1088, 1920, 1, "x", ref_resolution=0, crop=False)
    enc = wf["20"]["inputs"]
    assert enc["resolution"] == 0 and enc["images.image_1"] == ["101", 0] and enc["images.image_2"] == ["103", 0]
    assert not [n for n in wf.values() if n["class_type"] == "ImageScale"]
    assert wf["34"]["inputs"]["width"] == 1088   # 构图来自画布，不来自参考图


def test_text_generate_workflow():
    wf = W.text_generate("问题", "x", image="a.png")
    assert wf["20"]["class_type"] == "TextGenerate" and wf["20"]["inputs"]["image"] == ["101", 0]
    assert wf["11"]["inputs"]["clip_name"] == W.TEXT_MODEL and wf["90"]["class_type"] == "SaveText"


# ------------------------------------------------------------------ 调色

def _img(path, rgb, size=(64, 96)):
    rng = np.random.default_rng(0)
    arr = np.clip(np.array(rgb)[None, None, :] + rng.normal(0, 20, (size[1], size[0], 3)), 0, 255).astype(np.uint8)
    Image.fromarray(arr).save(path)
    return path


def test_grade_keeps_raw_and_moves_towards_reference(tmp_path):
    src = _img(tmp_path / "a.png", (90, 110, 100))
    info = G.grade_file(src, tmp_path / "b.png", strength=0.6)
    assert src.exists() and (tmp_path / "b.png").exists() and info["method"] == "reinhard_lab"
    assert G.colour_distance(tmp_path / "b.png") < G.colour_distance(src)


def test_grade_never_brightens_dark_shots(tmp_path):
    src = _img(tmp_path / "d.png", (20, 22, 30))
    info = G.grade_file(src, tmp_path / "e.png", strength=0.7, dark=True)
    a = np.asarray(Image.open(src).convert("L"), float)
    b = np.asarray(Image.open(tmp_path / "e.png").convert("L"), float)
    assert info["dark"] and b.mean() <= a.mean() + 1.0


# ------------------------------------------------------------------ 评分

def test_parse_vlm_bools():
    assert S.parse_bools('```json\n{"1": true, "2": false, "3":true, "9": true}\n```', 3) == {1: True, 2: False, 3: True}


def test_smooth_fraction_detects_bokeh(tmp_path):
    flat = np.full((512, 288), 128, np.uint8)
    flat[200:300, 100:200] = np.random.default_rng(1).integers(0, 255, (100, 100))
    Image.fromarray(flat).save(tmp_path / "bokeh.png")
    busy = np.random.default_rng(2).integers(0, 255, (512, 288)).astype(np.uint8)
    Image.fromarray(busy).save(tmp_path / "busy.png")
    assert S.smooth_fraction(tmp_path / "bokeh.png") > 0.5 > S.smooth_fraction(tmp_path / "busy.png")


# ------------------------------------------------------------------ 多候选 + 尾帧（假客户端）

class _Client:
    def __init__(self):
        self.workflows = []

    def object_info(self):
        return {"LoraLoaderModelOnly": {"input": {"required": {"lora_name": [[]]}}}}

    def upload_image(self, *a, **k):
        return "up.png"

    def run(self, wf, timeout_s):
        self.workflows.append(wf)
        return {"outputs": {"90": {"images": [{"filename": f"x{len(self.workflows)}.png"}]}}}, 1.0

    output_files = staticmethod(P.ComfyClient.output_files)

    def download(self, item, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(item["filename"].encode())
        return dest


def _compiled(**kw):
    base = dict(shot_id="ep99-S1", adult=False, adult_reasons=[], image_prompt=f"【林晚】x，{STYLE}", image_negative="",
                image_loras=[], video_prompt="", video_negative="", video_loras=[], last_prompt="图1是首帧。改为结束",
                end_state="结束", image_body="林晚低头")
    base.update(kw)
    return P.CompiledShot(**base)


@pytest.fixture
def sandbox(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(P, "QC_LOG", tmp_path / "renders" / "qc_log.jsonl")
    monkeypatch.setattr(P, "compile_with_edits", lambda script, shot_id, loras, **k: _compiled())
    monkeypatch.setattr(P, "shot_looks_map", lambda shot_id: {})
    return tmp_path


def _scores(values):
    it = iter(values)
    return lambda path, qc: {"total": next(it), "missing": ["缺X"]}


def _clean(path):
    return {"nudity": False, "hits": [], "clip_bare": 0.0}


def test_best_of_candidates_is_active_and_all_kept(sandbox):
    t = P.render_image(_Client(), None, "ep99-S1", qc_fn=_clean, candidates=3, rounds=3, grade=False,
                       score_fn=_scores([0.5, 0.9, 0.7]), face_lock=False)
    data = P.load_takes("ep99-S1")
    assert t.n == 2 and data["active"]["image"] == 2 and len(data["takes"]) == 3
    assert [x["round"] for x in data["takes"]] == [1, 1, 1] and "image" not in data.get("review", {})
    assert len({x["seed"] for x in data["takes"]}) == 3


def test_low_scores_run_more_rounds_then_review(sandbox):
    t = P.render_image(_Client(), None, "ep99-S2", qc_fn=_clean, candidates=2, rounds=3, grade=False,
                       score_fn=_scores([0.1, 0.3, 0.2, 0.4, 0.35, 0.2]), face_lock=False)
    data = P.load_takes("ep99-S2")
    assert len(data["takes"]) == 6 and t.score["total"] == 0.4 and data["active"]["image"] == t.n
    assert data["review"]["image"]["best"] == t.n and data["review"]["image"]["missing"] == ["缺X"]


def test_nude_candidate_is_never_selected(sandbox):
    qc = iter([True, False])
    t = P.render_image(_Client(), None, "ep99-S3", candidates=2, rounds=1, grade=False, face_lock=False,
                       qc_fn=lambda p: {"nudity": next(qc), "hits": [], "clip_bare": 0}, score_fn=_scores([0.8]))
    assert t.n == 2 and P.load_takes("ep99-S3")["takes"][0]["score"] is None


def test_last_frame_stage_and_video_priority(sandbox):
    d = P.shot_dir("ep99-S4")
    d.mkdir(parents=True)
    Image.new("RGB", (108, 192)).save(d / "frame.png")
    client = _Client()
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(P, "compile_with_edits", lambda *a, **k: _compiled(last_prompt=""))
        with pytest.raises(P.ComfyError, match="结束状态"):
            P.render_last_frame(client, None, "ep99-S4")
    t = P.render_last_frame(client, None, "ep99-S4", candidates=1, rounds=1, grade=False, qc_fn=_clean,
                            score_fn=None)
    assert t.stage == "last" and t.file.endswith("last_001.png") and (d / "last.png").exists()
    wf = client.workflows[-1]
    assert wf["20"]["inputs"]["resolution"] == 0 and wf["20"]["inputs"]["images.image_1"] == ["101", 0]
    assert wf["20"]["inputs"]["prompt"].startswith("图1是首帧。")
    assert P.active_last_frame("ep99-S4") == sandbox / t.file


def test_video_activation_does_not_overwrite_independent_last(sandbox):
    d = P.shot_dir("ep99-S5")
    (d / "takes").mkdir(parents=True)
    for name, data in (("last_001.png", b"L"), ("video_001.mp4", b"V"), ("video_001_last.png", b"VL")):
        (d / "takes" / name).write_bytes(data)
    rel = "renders/ep99/S5/takes/"
    P._add_take("ep99-S5", P.Take(n=1, stage="last", file=rel + "last_001.png", seed=1, prompt="", created_at="x"))
    P._add_take("ep99-S5", P.Take(n=1, stage="video", file=rel + "video_001.mp4", seed=1, prompt="", created_at="x",
                                  last_frame=rel + "video_001_last.png"))
    assert (d / "last.png").read_bytes() == b"L" and (d / "video_last.png").read_bytes() == b"VL"


# ------------------------------------------------------------------ Frame Spec

def test_spec_validates_and_keeps_script_verbatim():
    ep, s = _shot("极近特写，林晚低头侧脸，齐刘海的阴影盖住上半张脸，像一份合约")
    spec = F.build_spec(ep, s, G0, boost_first="导演加强B")
    assert spec.validation == [] and spec.script_ref.img == s.img_prompt
    assert "像一份合约" in spec.not_in_image and "像一份合约" not in spec.model_prompt.qwen
    assert {"林晚低头侧脸", "齐刘海的阴影盖住上半张脸"} <= {f.text for f in spec.facts}
    assert any(f.kind == "boost" and f.must and f.text == "导演加强B" for f in spec.facts)
    q = spec.model_prompt.qwen
    assert q.index("【林晚】") < q.index("极近特写") < q.index("林晚低头侧脸") < q.index("导演加强B") < q.index(STYLE)
    assert spec.first_frame.action == "她低头掩饰" and spec.last_frame.description == "抬眼又立刻低头"


def test_spec_rejects_missing_and_invented_facts():
    spec = FrameSpec(shot_id="x", script_ref=ScriptRef(img="林晚在电梯，三串珠", motion=""),
                     facts=[Fact(text="林晚在电梯"), Fact(text="手里拿着红酒杯")])
    problems = F.validate(spec)
    assert any("未覆盖：三串珠" in p for p in problems) and any("不是原文：手里拿着红酒杯" in p for p in problems)


def test_screen_text_exception_only_for_script_text():
    ep, s = _shot("手机亮起：第一条回复——特写屏幕“在看。”", motion="camera static，她盯着屏幕")
    spec = F.build_spec(ep, s, G0)
    assert spec.technique.kind == "screen_text" and spec.on_screen_text == ["在看。"]
    assert "除屏幕上的“在看。”外无其他文字" in spec.model_prompt.qwen and "无字幕、无文字、无水印" not in spec.model_prompt.qwen


def test_llm_refine_rejects_invented_people_and_keeps_rules_version():
    ep, s = _shot("极近特写，林晚低头侧脸")
    spec = F.build_spec(ep, s, G0)
    good = F.refine_with_llm(spec, s, lambda p: json.dumps({"first_frame": {"gaze": "视线向下"},
                                                            "characters": [{"name": "林晚", "facing": "profile"}]}))
    assert good.first_frame.gaze == "视线向下" and good.characters[0].facing == "profile" and "llm" in good.generator
    junk = F.refine_with_llm(spec, s, lambda p: json.dumps({"characters": [{"name": "陌生人", "facing": "back"}]}))
    assert [c.name for c in junk.characters] == ["林晚"]
    broken = F.refine_with_llm(spec, s, lambda p: (_ for _ in ()).throw(OSError("down")))
    assert broken.generator == "rules"


# ------------------------------------------------------------------ 项目方材质规则 B7/B8、穿着 B10

def test_patent_and_heel_rules_appended_once_before_style():
    ep, s = _shot("hh12clear，一双12cm透明细高跟鞋踏入大理石反光地面，黑色漆皮长风衣")
    c = C.compile_shot(ep, s, G0, set())
    for term in (C.PATENT_TERM, C.HEEL_TERM):
        assert c.image_prompt.count(term) == 1 and c.image_prompt.index(term) < c.image_prompt.index(STYLE)
    assert "黑色漆皮长风衣" in c.image_prompt                       # 原文不动
    spec = F.build_spec(ep, s, G0)
    assert {C.PATENT_TERM, C.HEEL_TERM} <= {f.text for f in spec.facts if f.kind == "rule" and f.must}
    assert spec.validation == [] and spec.model_prompt.qwen.count(C.HEEL_TERM) == 1
    plain = C.compile_shot(*_shot("极近特写，林晚低头侧脸"), G0, set())
    assert C.PATENT_TERM not in plain.image_prompt and C.HEEL_TERM not in plain.image_prompt
    assert C.material_terms(f"漆皮，{C.PATENT_TERM}") == []        # 已有则不重复


def test_safe_shot_term_is_not_conservative():
    c = C.compile_shot(*_shot("写字楼工位，林晚低头"), G0, set())
    assert "衣装完整、无裸露" in c.image_prompt
    assert "保守" not in c.image_prompt and "职业装" not in c.image_prompt
    assert "暴露" not in c.image_negative.replace("裸露", "") and "裸露、走光、低俗姿势" in c.image_negative


def test_lens_term_skipped_for_chinese_leica():
    g = G0.model_copy(update={"image_suffix": "徕卡镜头级锐利度与通透质感，" + STYLE})
    c = C.compile_shot(*_shot("极近特写，林晚低头侧脸"), g, set())
    assert "Leica" not in c.image_prompt and c.image_prompt.count("徕卡") == 1


def test_spec_focus_gaze_expression_fields():
    ep, s = _shot("极近特写，晚间卧室床上，陈宇熟睡的侧脸虚化在背景，前景林晚睁着的眼",
                  motion="camera push in 极缓推近她的眼睛，她睁眼望着天花板——睫毛最后轻轻眨了一下")
    spec = F.build_spec(ep, s, G0)
    lw = next(c for c in spec.characters if c.name == "林晚")
    assert spec.focus_part == "eye" and lw.screen_share.startswith("0.9")
    assert lw.expression.start == "睁着眼" and "前景" not in spec.first_frame.expression
    assert "望向天花板" in spec.first_frame.gaze
    assert next(c for c in spec.characters if c.name == "陈宇").screen_share.startswith("0.1")


def test_frames_follow_duration():
    assert P.frames_for_duration(10) == 243 and P.frames_for_duration(3) == 124
    assert P.frames_for_duration(15) == 362 and (P.frames_for_duration(7) - 5) % 17 == 0


def test_refine_workflow_is_low_denoise_base_with_texture_vae():
    wf = W._qwen_graph("p", "n", 1088, 1920, 1, "x", P.REFINE_MODEL, P.REFINE_LORAS, reference=["plate.png"],
                       ref_resolution=0, crop=False, init_image="first.png", denoise=P.REFINE_DENOISE)
    assert wf["37"]["inputs"]["denoise"] == P.REFINE_DENOISE <= 0.25 and wf["37"]["inputs"]["steps"] == 12
    assert wf["40"]["inputs"]["latent_image"] == ["112", 0] and "34" not in wf
    assert wf["12"]["inputs"]["vae_name"].startswith("texture_fix")
    assert wf["60"]["inputs"]["lora_name"] == P.REFINE_LORAS[0][0] and P.REFINE_LORAS[0][1] <= 0.4


# ------------------------------------------------------------------ E8 H3 声音段

def test_video_prompt_ends_with_soundscape_and_music_sections():
    ep, s = _shot("极近特写，林晚低头侧脸")
    s.sound = "心跳声铺底，他平稳低沉的语声，电梯门开提示音"
    c = C.compile_shot(ep, s, G0, set())
    assert c.video_prompt.endswith("\n\noverall_soundscape: 心跳声铺底，电梯门开提示音\n\nnon_diegetic_music: N/A")
    assert "音效：" not in c.video_prompt and "语声" not in c.video_soundscape
    assert (c.video_soundscape_source, c.video_music_source) == ("script", "fixed")
    assert "overall_soundscape" not in c.image_prompt                       # 图片不受影响
    c2 = C.compile_shot(ep, s, G0, set(), soundscape="Soft rain.", music="Slow piano.", episode_music="Strings.")
    # 背景音乐只在后期：H3 一律 N/A，音乐文字只进 post_music
    assert c2.video_prompt.endswith("overall_soundscape: Soft rain.\n\nnon_diegetic_music: N/A")
    assert c2.video_soundscape_source == "edit" and "Slow piano" not in c2.video_prompt
    assert c2.post_music == {"episode_prompt": "Strings.", "episode_bgm": "", "shot_cue": "Slow piano.",
                             "source": "edit"}
    c3 = C.compile_shot(ep, s, G0, set(), episode_music="Low strings.")
    assert c3.video_music == "N/A" and c3.post_music["episode_prompt"] == "Low strings."


def test_apply_edit_keeps_sound_sections():
    ep, s = _shot("极近特写，林晚低头侧脸")
    s.sound = "心跳声"
    c = C.compile_shot(ep, s, G0, set())
    h3 = c.video_prompt
    out = P.apply_edit(c, ShotEdit(video_prompt="人工视频提示词", expression="咬唇"), STYLE)
    # 旧版中文提示词的人工修改只进 legacy_video_prompt（历史），H3 提示词不变（SOP §9A）
    assert out.legacy_video_prompt.startswith("人工视频提示词，表情：咬唇\n\noverall_soundscape: 心跳声")
    assert out.video_prompt == h3 and h3.endswith("overall_soundscape: 心跳声\n\nnon_diegetic_music: N/A")


# ------------------------------------------------------------------ QA-02/03/05

def test_set_active_refuses_laptop_take_on_adult_shot(sandbox, monkeypatch):
    monkeypatch.setattr(P, "shot_is_adult", lambda sid: sid == "ep99-S7")
    d = P.shot_dir("ep99-S7")
    (d / "takes").mkdir(parents=True)
    (d / "takes" / "image_001.png").write_bytes(b"x")
    data = {"takes": [P.Take(n=1, stage="image", file="renders/ep99/S7/takes/image_001.png", seed=1, prompt="",
                             created_at="x").model_dump()], "active": {}}
    P._save_takes("ep99-S7", data)
    with pytest.raises(P.AdultShotRejected):
        P.set_active("ep99-S7", "image", 1)
    data["takes"][0]["source"] = "gpu3"
    P._save_takes("ep99-S7", data)
    P.set_active("ep99-S7", "image", 1)


def test_real_adult_shots_detected():
    assert P.shot_is_adult("ep01-S3") is False
    script = P.load_script()
    adult = next(s.id for ep in script.episodes for s in ep.shots
                 if C.compile_shot(ep, s, script.globals, set()).adult)
    assert P.shot_is_adult(adult) is True


def test_possessive_place_keeps_owner_when_he_is_in_frame():
    c = C.compile_shot(*_shot("顾沉家卧室，他从背后环住她"), G0.model_copy(update={"character_locks": [
        CharacterLock(name="顾沉", description="34岁")]}), set())
    assert "【顾沉】" in c.image_prompt
    assert "【顾沉】" not in C.compile_shot(*_shot("顾沉家客厅：空无一人"), G0.model_copy(update={"character_locks": [
        CharacterLock(name="顾沉", description="34岁")]}), set()).image_prompt


def test_dash_inside_parentheses_not_split():
    assert C.split_dash("她笑（像在说——你来了）——转身") == ["她笑（像在说——你来了）", "转身"]
    assert C.split_camera("camera orbit 缓慢环绕她——微笑") == ("camera orbit", "缓慢环绕她——微笑")


def test_toenail_rule_only_when_feet_in_text_and_lin_wan_present():
    ep, s = _shot("林晚赤脚踩在地毯上")
    c = C.compile_shot(ep, s, G0, set())
    assert c.image_prompt.count(C.TOENAIL_TERM) == 1 and c.image_prompt.index(C.TOENAIL_TERM) < c.image_prompt.index(STYLE)
    assert C.TOENAIL_TERM in {f.text for f in F.build_spec(ep, s, G0).facts if f.kind == "rule"}
    assert C.TOENAIL_TERM not in C.compile_shot(*_shot("电梯轿厢，林晚低头"), G0, set()).image_prompt
    assert C.TOENAIL_TERM not in C.compile_shot(*_shot("一双透明高跟鞋踏入大理石地面"), G0, set()).image_prompt  # 林晚不在


def test_gpu3_ownership_rule_gates_all_renders(tmp_path, monkeypatch):
    cfg = tmp_path / "shot_ownership.json"
    monkeypatch.setattr(P, "OWNERSHIP", cfg)
    monkeypatch.setattr(P, "GPU3_RENDERS", tmp_path / "renders_gpu3")
    monkeypatch.setattr(P, "RENDERS", P.ROOT / "data" / "renders")
    cfg.write_text('{"projects": {"weita": {"owner": "laptop"}}}', encoding="utf-8")
    assert P.project_gate_message() is None and P.gpu3_owns("ep01-S1") is None
    st = tmp_path / "renders_gpu3" / "ep01" / "S2"
    st.mkdir(parents=True)
    (st / "status.json").write_text('{"owner": "gpu3"}', encoding="utf-8")
    assert "status.json" in P.gpu3_owns("ep01-S2") and P.gpu3_owns("ep01-S1") is None
    cfg.write_text('{"projects": {"weita": {"owner": "gpu3"}}}', encoding="utf-8")
    assert P.project_gate_message() == P.PROJECT_GATE_MSG
    for fn in (P.render_image, P.render_last_frame, P.render_video, P.refine_image):
        with pytest.raises(P.Gpu3Owned, match="gpu3 负责此项目的首尾帧与视频"):
            fn(None, None, "ep01-S1")


def test_real_ownership_config_is_gpu3_for_weita():
    assert P.project_owner("weita") == "gpu3"


# ------------------------------------------------------------------ 裸露质检 v3

def test_qc_v3_judge_rules():
    from ns_render import qc as Q
    assert Q.judge_v3([{"class": "FEMALE_BREAST_EXPOSED", "score": 0.5}], 0.0, False) is True   # 部位命中一票否决
    assert Q.judge_v3([], 0.95, False) is True                                                  # CLIP 极高
    assert Q.judge_v3([], 0.71, False) is False          # 着装图最高分 + 看图模型说没有 → 放行（v1 会误报）
    assert Q.judge_v3([], 0.25, True) is True            # ep04-S6 型：CLIP 低但看图模型看出赤裸
    assert Q.judge_v3([], 0.35, None) is True and Q.judge_v3([], 0.1, None) is False   # 没有看图模型：偏严兜底
    assert Q.NUDENET_THRESHOLDS["MALE_GENITALIA_EXPOSED"] >= 0.75
    assert any("man" in p for p in Q.NUDE_PROMPTS) and any("man wearing" in p for p in Q.CLOTHED_PROMPTS)


def test_qc_v3_uses_vlm_only_when_needed(monkeypatch, tmp_path):
    from ns_render import qc as Q
    monkeypatch.setattr(Q, "nudenet_hits", lambda p: [])
    monkeypatch.setattr(Q, "clip_bare_score", lambda p: 0.4)
    calls = []
    r = Q.nudity_qc(tmp_path / "x.png", vlm=lambda p: calls.append(p) or False)
    assert r["nudity"] is False and r["vlm"] is False and len(calls) == 1
    assert Q.nudity_qc(tmp_path / "x.png")["nudity"] is True          # 无看图模型 0.4 ≥ 0.30


@pytest.mark.skipif(not (P.ROOT / "golden/qc_calibration/vlm_check.json").exists(), reason="需要标注集")
def test_qc_calibration_record():
    rows = json.loads((P.ROOT / "golden/qc_calibration/vlm_check.json").read_text(encoding="utf-8"))
    neg = [r for r in rows if not r["label"]]
    seen_pos = [r for r in rows if r["label"] and r["src"] == "seen"]
    assert neg and not any(r["vlm"] for r in neg)          # 看图模型对核对过的着装图 0 误报
    assert seen_pos and all(r["vlm"] for r in seen_pos)    # 人工确认的裸露全部命中
