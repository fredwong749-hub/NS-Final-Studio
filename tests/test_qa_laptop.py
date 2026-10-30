"""T36 QA 回归测试（docs/qa_laptop.md）。只读：不写 data/、不连 ComfyUI、不调用 /render。

- 合成用例：锁定已发现的编译器 / 导入器 / Frame Spec 缺陷。未修复的用 xfail(strict=True) 标出 QA 编号，
  修好后会变成 XPASS → 失败，提醒把 xfail 去掉（让它变成普通回归测试）。
- 真实剧本用例（data/import/script_v2.json 存在时）：60 集 × 6 镜、每镜 img/motion/sound、未成年人护栏、
  风格后缀、禁用词、成人判定一致。
- 渲染数据完整性（data/renders）：其它 agent 渲染时文件会并发变化，默认跳过；设 NS_QA_DATA=1 运行。
"""
import hashlib
import json
import os
import re
import tomllib
from pathlib import Path

import pytest

from ns_agent import compiler as C
from ns_agent import frame_spec as F
from ns_agent.importer import script_md as IM
from ns_schema.script import CharacterLock, Episode, LoraTrigger, ScriptGlobals, ScriptImport, Shot

ROOT = Path(__file__).resolve().parent.parent
# 默认用固定测试剧本（t06 金标准同一份）；NS_QA_DATA=1 时检查真实导入数据 data/import/script_v2.json
SCRIPT_JSON = (ROOT / "data" / "import" / "script_v2.json" if os.environ.get("NS_QA_DATA") == "1" else
               ROOT / "tests" / "fixtures" / "t06_golden" / "data" / "import" / "script_v2.json")
RENDERS = ROOT / "data" / "renders"
VB = tomllib.loads((ROOT / "config" / "visual_bible.toml").read_text(encoding="utf-8"))
BANNED = VB["realism"]["banned_words"]

STYLE = "专业电影镜头画面感，画面干净，徕卡镜头级锐利度，85mm人像镜头f/1.2大光圈，无字幕、无文字、无水印"
G0 = ScriptGlobals(
    image_suffix=STYLE,
    character_locks=[CharacterLock(name="林晚", description="蓝发及腰、齐刘海"),
                     CharacterLock(name="顾沉", description="34岁成年男性CEO")],
    lora_triggers=[LoraTrigger(trigger=t, kind="image", description=t, file=f"{t}.safetensors")
                   for t in ("hh12clear", "lbrng9", "lbrng9_beads")],
)


def _shot(img, triggers=(), motion="lnwan01，camera push in 缓慢推近，她低头", ep=1, i=1):
    return (Episode(number=ep, title="t", source_line=1),
            Shot(episode=ep, index=i, img_prompt=img, img_triggers=list(triggers), motion_prompt=motion,
                 motion_triggers=["lnwan01"], sound="环境音", source_line=1))


def _bare_trigger(prompt: str, trigger: str) -> bool:
    return re.search(rf"(?<![A-Za-z0-9_]){re.escape(trigger)}(?![A-Za-z0-9_])", prompt) is not None


# ------------------------------------------------------------------ 编译器

def test_strip_triggers_handles_ascii_comma_space():
    assert C._strip_triggers("hh12clear, lbrng9, lbrng9_beads，卧室", ["hh12clear", "lbrng9", "lbrng9_beads"]) == "卧室"


def test_dropped_triggers_never_reach_image_prompt():
    ep, s = _shot("hh12clear, lbrng9, lbrng9_beads，顾沉家卧室，她立于镜前", ["hh12clear", "lbrng9", "lbrng9_beads"])
    c = C.compile_shot(ep, s, G0, available_loras=set())
    assert set(c.dropped_triggers) >= {"hh12clear", "lbrng9", "lbrng9_beads"}
    for t in c.dropped_triggers:
        assert not _bare_trigger(c.image_prompt, t), t


def test_strip_triggers_chinese_comma_still_ok():
    assert C._strip_triggers("hh12clear，lbrng9，卧室", ["hh12clear", "lbrng9"]) == "卧室"


def test_possessive_place_does_not_add_character_lock():
    ep, s = _shot("顾沉家客厅：布置完成的场地——暖灯、软垫圈、小几上的酒与杯")
    c = C.compile_shot(ep, s, G0, set())
    assert "【顾沉】" not in c.image_prompt


@pytest.mark.parametrize("adult_img", ["林晚站在窗前", "她的乳环在灯下"])
def test_minor_guard_always_in_negatives(adult_img):
    ep, s = _shot(adult_img)
    g = G0.model_copy(update={"base_negative": ""})
    c = C.compile_shot(ep, s, g, set())
    assert C.MINOR_GUARD in c.image_negative and C.MINOR_GUARD in c.video_negative


# ------------------------------------------------------------------ Frame Spec

def test_motion_start_drops_camera_prefix_without_comma():
    assert "camera" not in F.motion_start("camera orbit 缓慢环绕她一身端庄的仪态——微笑、点头")
    assert "handheld" not in F.motion_start("handheld follow 情感爆发镜：她的背弓起——喉咙里挤出一声")


def test_motion_start_drops_camera_prefix_with_comma():
    assert F.motion_start("camera push in 缓慢推近，她低头掩饰——抬眼") == "她低头掩饰"


# ------------------------------------------------------------------ 导入器：对白

def test_dialogue_slash_inside_quotes_is_one_line():
    lines = IM._parse_dialogue("（他）“……谁教你的。”／（她，仰脸，一字一字）“网上学的。／为了你。”")
    assert [(d.speaker_note, d.text) for d in lines] == [("他", "……谁教你的。"), ("她，仰脸，一字一字", "网上学的。／为了你。")]


def test_dialogue_colon_between_speaker_and_quote():
    lines = IM._parse_dialogue("（他，贴在她耳侧，画外声）：“那就看你——是不是自愿。”")
    assert lines[0].speaker_note == "他，贴在她耳侧，画外声"


def test_dialogue_basic_speaker_and_stage():
    lines = IM._parse_dialogue("（接通）（她，很小声）“喂？”／（他）“嗯。”")
    assert [(d.stage, d.speaker_note, d.text) for d in lines] == [("接通", "她，很小声", "喂？"), (None, "他", "嗯。")]


# ------------------------------------------------------------------ 真实剧本（只读）

@pytest.fixture(scope="module")
def script() -> ScriptImport:
    if not SCRIPT_JSON.exists():
        pytest.skip("data/import/script_v2.json missing")
    return ScriptImport.model_validate_json(SCRIPT_JSON.read_text(encoding="utf-8"))


def _shots(script):
    for ep in script.episodes:
        for s in ep.shots:
            yield ep, s


def test_real_script_shape(script):
    assert len(script.episodes) == 60
    # v2 每集 6 镜；新剧本（如 rules_v2 的 ep01 七镜）镜数可变：只要求镜号从 1 连续
    bad = [f"ep{e.number:02d}:{[s.index for s in e.shots]}" for e in script.episodes
           if not e.shots or [s.index for s in e.shots] != list(range(1, len(e.shots) + 1))]
    assert not bad
    empty = [(s.id, f) for _, s in _shots(script) for f in ("img_prompt", "motion_prompt", "sound")
             if not getattr(s, f).strip()]
    assert not empty
    assert all(3 <= s.duration <= 15 for _, s in _shots(script))
    assert all(s.adult is not None for _, s in _shots(script))


def test_real_adult_flags_match_compiler(script):
    """导入时写进 JSON 的 adult 必须与编译器当前判定一致（gpu3 / 笔记本分工依赖它）"""
    diff = [s.id for ep, s in _shots(script) if bool(C.classify_adult(ep, s)) != bool(s.adult)]
    assert not diff, f"script_v2.json 的 adult 过期，需重跑 tools/import_script.py：{diff[:10]}"


def test_real_compile_guards_and_style(script):
    g = script.globals
    probs = []
    for ep, s in _shots(script):
        c = C.compile_shot(ep, s, g, set())
        if C.MINOR_GUARD not in c.image_negative or C.MINOR_GUARD not in c.video_negative:
            probs.append(f"{s.id} minor guard")
        if g.image_suffix and g.image_suffix not in c.image_prompt:
            probs.append(f"{s.id} style suffix")
        for p in (c.image_prompt, c.last_prompt, c.video_prompt):
            probs += [f"{s.id} banned {w}" for w in BANNED if w in p]
            for term in ("Leica", "徕卡", "无字幕"):
                if p.count(term) > 1:
                    probs.append(f"{s.id} dup {term}")
    assert not probs, probs[:20]


def test_real_no_leftover_triggers(script):
    g = script.globals
    left = []
    for ep, s in _shots(script):
        c = C.compile_shot(ep, s, g, set())
        left += [f"{s.id}:{t}" for t in c.dropped_triggers if _bare_trigger(c.image_prompt, t)]
    assert not left, left[:20]


def test_real_spec_prompt_no_duplicate_material_terms(script):
    dup = []
    for ep, s in _shots(script):
        q = F.build_spec(ep, s, script.globals, available_triggers=set()).model_prompt.qwen
        for t in (C.PATENT_TERM, C.HEEL_TERM):
            if q.count(t) > 1:
                dup.append(s.id)
    assert not dup, dup


def test_real_spec_validates(script):
    bad = [s.id for ep, s in _shots(script) if F.validate(F.build_spec(ep, s, script.globals, available_triggers=set()))]
    assert not bad, bad[:20]


# ------------------------------------------------------------------ 密钥

def test_secret_configs_are_gitignored():
    rules = (ROOT / ".gitignore").read_text(encoding="utf-8").split()
    assert "config/*.local.json" in rules and ".env" in rules


def test_tracked_boost_config_has_no_key():
    p = ROOT / "config" / "director_boost_llm.json"
    if p.exists():
        assert not json.loads(p.read_text(encoding="utf-8")).get("api_key")


# ------------------------------------------------------------------ 渲染数据完整性（NS_QA_DATA=1）

data_only = pytest.mark.skipif(os.environ.get("NS_QA_DATA") != "1" or not RENDERS.exists(),
                               reason="set NS_QA_DATA=1 to audit data/renders (read-only)")


def _takes():
    for tj in sorted(RENDERS.glob("ep*/S*/takes.json")):
        yield f"{tj.parent.parent.name}-{tj.parent.name}", tj.parent, json.loads(tj.read_text(encoding="utf-8"))


def _active(data, stage):
    n = (data.get("active") or {}).get(stage)
    return next((t for t in data["takes"] if t["stage"] == stage and t["n"] == n), None) if n is not None else None


@data_only
def test_data_active_takes_exist_and_not_qc_flagged():
    probs = []
    for sid, d, data in _takes():
        for stage in (data.get("active") or {}):
            t = _active(data, stage)
            if t is None:
                probs.append(f"{sid} {stage}: active points to missing take")
            elif not (RENDERS.parent / t["file"]).exists():
                probs.append(f"{sid} {stage}: file missing {t['file']}")
            elif (t.get("qc") or {}).get("nudity"):
                probs.append(f"{sid} {stage}: qc-flagged take is active")
    assert not probs, probs[:20]


@data_only
def test_data_frame_png_matches_active_image():
    def sha(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()
    bad = []
    for sid, d, data in _takes():
        t = _active(data, "image")
        if t and (d / "frame.png").exists() and sha(d / "frame.png") != sha(RENDERS.parent / t["file"]):
            bad.append(sid)
    assert not bad, bad


@data_only
def test_data_adult_shots_have_no_active_laptop_first_frame(script):
    adult = {s.id for _, s in _shots(script) if s.adult}
    bad = [sid for sid, d, data in _takes() if sid in adult and _active(data, "image")
           and not (_active(data, "image").get("source") or "").startswith("gpu3")]
    assert not bad, bad
