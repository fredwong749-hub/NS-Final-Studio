"""T06：规则从 config/visual_bible.toml 读；bible_version；造型注入开关。

金标准：tests/fixtures/t06_golden/prompts_before.json 是 T06 之前（规则写死在 compiler.py 常量里）对固定剧本
360 镜的全部编译结果；这里用同一份剧本 + T06 后的 visual_bible.toml（fixture 副本）重新编译，必须逐字相同。
"""
import importlib.util
import json
import re
from pathlib import Path

import pytest

from ns_agent import bible as B
from ns_agent import compiler as C
from ns_agent import frame_spec as F
from ns_schema.script import CharacterLock, Episode, ScriptGlobals, Shot

FIX = Path(__file__).parent / "fixtures" / "t06_golden"


@pytest.fixture(autouse=True)
def _framing_off(monkeypatch):
    """金标准是 T06 之前的编译结果，测的是“规则搬进 visual_bible.toml 后逐字不变”。景别取舍（K-REN-101，PROMPT 2026-10-31，
    ns_agent.framing，按 config/recipes/image_framing.json 对新项目 / 未定稿镜默认开）是之后新加的、有意的行为，
    不属于 T06 的等价性检查，这里关掉以隔离；它自己的行为由 tests/test_image_framing.py 覆盖。"""
    from ns_agent import framing as FR
    monkeypatch.setattr(FR, "enabled", lambda *a, **k: False)


def _snapshot_mod():
    spec = importlib.util.spec_from_file_location("t06_snapshot", FIX / "snapshot.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_golden_360_shots_identical_after_t06():
    b = B.load_bible(root=FIX)
    assert b.exists and not b.looks_inject
    before = json.loads((FIX / "prompts_before.json").read_text(encoding="utf-8"))
    after = json.loads(json.dumps(_snapshot_mod().snapshot({"bible": b}, {"bible": b}), ensure_ascii=False))
    assert len(before) == len(after) == 360
    diff = [(sid, tag, k) for sid in before for tag in before[sid] for k in before[sid][tag]
            if before[sid][tag][k] != after[sid][tag][k]]
    assert diff == []


def test_missing_bible_falls_back_to_constants(tmp_path):
    (tmp_path / "config").mkdir()
    # FIX：prompt_guard 读项目根 config/render_quality.json；与金标准根用同一份（条件化规则关闭），只比 bible 兜底
    (tmp_path / "config" / "render_quality.json").write_bytes((FIX / "config" / "render_quality.json").read_bytes())
    b = B.load_bible(root=tmp_path)
    assert not b.exists
    assert b.materials[0].term == C.TOENAIL_TERM and b.materials[1].term == C.PATENT_TERM
    assert b.dark_words == C.DARK_WORDS and b.safe_term == C.SAFE_SHOT_TERM
    assert b.image_style_fallback == C.DEFAULT_IMAGE_STYLE and b.minor_guard == C.MINOR_GUARD
    assert b.character("林晚").she_trigger == "lnwan01"
    # 与当前仓库的 bible 编译结果一致（两者编码同一套规则）
    ep, s = Episode(number=1, title="t", source_line=1), Shot(
        episode=1, index=1, img_prompt="hh12clear，极近特写，夜晚，林晚赤脚踩漆皮", img_triggers=["hh12clear"],
        motion_prompt="lnwan01，她抬眼——低头", motion_triggers=["lnwan01"], source_line=1)
    g = ScriptGlobals(image_suffix="85mm人像镜头f/1.2大光圈", character_locks=[CharacterLock(name="林晚", description="蓝发")])
    a = C.compile_shot(ep, s, g, set(), bible=b)
    real = C.compile_shot(ep, s, g, set(), bible=B.load_bible(root=FIX))
    assert a.image_prompt == real.image_prompt and a.image_negative == real.image_negative


def _write_bible(root: Path, text: str):
    (root / "config").mkdir(parents=True, exist_ok=True)
    (root / "config" / "visual_bible.toml").write_text(text, encoding="utf-8")


def _shot(img, motion="lnwan01，她低头——抬眼", trig=()):
    return (Episode(number=1, title="t", source_line=1),
            Shot(episode=1, index=1, img_prompt=img, img_triggers=list(trig), motion_prompt=motion,
                 motion_triggers=["lnwan01"], source_line=1))


G = ScriptGlobals(image_suffix="85mm人像镜头f/1.2大光圈，无字幕", character_locks=[
    CharacterLock(name="林晚", description="蓝发及腰"), CharacterLock(name="顾沉", description="黑衬衫")])


def test_rules_are_read_from_toml(tmp_path):
    _write_bible(tmp_path, '''
[look]
fallback_suffix = "兜底后缀，网红脸"
lens_template = "LENS {mm}/{f}"
lens_default = ["35", "2"]
[realism]
banned_words = ["网红脸"]
[[materials]]
id = "silk"
match = ["丝绸"]
term = "丝绸有柔和光泽"
[[materials]]
id = "gc_watch"
match = ["手腕"]
term = "腕表为钢表"
character = "顾沉"
[[shot_rules]]
id = "dark"
match = ["雨夜"]
term = "雨夜保留细节"
[shot_rules_safe]
term = "SAFE"
negative = "SAFENEG"
[characters.lin_wan]
name = "林晚"
detect = ["林晚", "冰蓝发"]
detect_she_with_trigger = "lnwan01"
identity_extra = "眼下一颗小痣"
[characters.gu_chen]
name = "顾沉"
detect = ["顾沉", "CEO"]
[classification]
minor_guard = "幼态"
''')
    b = B.load_bible(root=tmp_path)
    g = G.model_copy(update={"image_suffix": ""})
    c = C.compile_shot(*_shot("雨夜，冰蓝发女人穿丝绸，CEO 看着她的手腕"), g, set(), bible=b)
    p = c.image_prompt
    assert "【林晚】蓝发及腰，眼下一颗小痣" in p and "【顾沉】黑衬衫" in p           # detect + identity_extra
    assert "丝绸有柔和光泽" in p and "腕表为钢表" in p and "雨夜保留细节" in p and "SAFE" in p
    assert "兜底后缀" in p and "网红脸" not in p and "LENS 35/2" in p           # fallback + 禁用词 + lens
    assert c.dark and "SAFENEG" in c.image_negative
    assert C.MINOR_GUARD in c.image_negative and "幼态" in c.image_negative      # 内置硬规则不可替换
    c2 = C.compile_shot(*_shot("雨夜，冰蓝发女人看着手腕"), g, set(), bible=b)
    assert "腕表为钢表" not in c2.image_prompt                                  # 带 character 的材质要该角色入镜
    spec = F.build_spec(*_shot("雨夜，冰蓝发女人穿丝绸"), g, bible=b)
    assert "丝绸有柔和光泽" in {f.text for f in spec.facts if f.kind == "rule"}
    assert "雨夜保留细节" in spec.model_prompt.qwen


def test_banned_words_never_touch_script_text(tmp_path):
    _write_bible(tmp_path, '[realism]\nbanned_words = ["网红"]\n')
    b = B.load_bible(root=tmp_path)
    c = C.compile_shot(*_shot("林晚像网红一样自拍"), G, set(), bible=b)
    assert "林晚像网红一样自拍" in c.image_prompt and c.banned_hits == ["网红"]


def test_overrides_path_is_project_root_aware(tmp_path):
    _write_bible(tmp_path, "")
    (tmp_path / "config" / "adult_overrides.json").write_text(json.dumps({"force_adult": {"ep01-S1": "测试"}}),
                                                              encoding="utf-8")
    b = B.load_bible(root=tmp_path)
    assert C.classify_adult(*_shot("林晚在电梯"), bible=b) == ["人工指定:测试"]


# ------------------------------------------------------------------ bible_version

def _project(tmp_path: Path) -> Path:
    for rel in ("config/visual_bible.toml", "config/shot_ownership.json", "data/import/script_v2.json"):
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "config/visual_bible.toml").write_text('[look]\nlens_default = ["50", "1.4"]\n', encoding="utf-8")
    (tmp_path / "config/shot_ownership.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data/import/script_v2.json").write_text("{}", encoding="utf-8")
    (tmp_path / "data/looks").mkdir(parents=True)
    (tmp_path / "data/looks/looks.json").write_text("{}", encoding="utf-8")
    return tmp_path


def test_bible_version_stable_and_sensitive(tmp_path):
    root = _project(tmp_path)
    v1 = C.bible_version(root)
    assert len(v1) == 12 and v1 == C.bible_version(root)
    # 只改注释/空白：版本不变（toml 解析后规范化）
    (root / "config/visual_bible.toml").write_text('# 注释\n[look]\n\nlens_default = [ "50", "1.4" ]  # x\n',
                                                   encoding="utf-8")
    assert C.bible_version(root) == v1
    for rel, text in (("config/visual_bible.toml", '[look]\nlens_default = ["85", "1.2"]\n'),
                      ("data/import/script_v2.json", '{"a": 1}'), ("data/looks/looks.json", '{"b": 2}'),
                      ("config/shot_ownership.json", '{"c": 3}')):
        before = C.bible_version(root)
        (root / rel).write_text(text, encoding="utf-8")
        assert C.bible_version(root) != before, rel


def test_compiled_shot_carries_bible_version():
    b = B.load_bible(root=FIX)
    c = C.compile_shot(*_shot("林晚在电梯"), G, set(), bible=b)
    assert c.bible_version == B.bible_version(FIX)


def test_current_repo_bible_compiles():
    assert len(C.bible_version()) == 12
    pytest.importorskip("tomllib")


def test_wrong_types_raise_clear_error(tmp_path):
    """封板修复：类型写错时报清楚的 ValueError（原来是 IndexError / AttributeError）"""
    for body, key in (('[look]\nlens_default = "x"\n', "lens_default"), ("characters = []\n", "[characters]"),
                      ('materials = "x"\n', "[[materials]]"), ('look = 3\n', "[look]")):
        _write_bible(tmp_path, body)
        with pytest.raises(ValueError, match=re.escape(key)):
            B.load_bible(root=tmp_path)


def test_adult_overrides_per_shot_and_list_force_adult(tmp_path):
    """封板修复：per_shot 只认布尔 true（字符串 "false" 不能当真）；force_adult 写成列表也能用"""
    _write_bible(tmp_path, "")
    ov = tmp_path / "config" / "adult_overrides.json"
    for value, want in (("false", False), ('"false"', False), ('"true"', True), ("true", True), ("1", False)):
        ov.write_text('{"per_shot": %s, "force_adult": ["ep01-S1"]}' % value, encoding="utf-8")
        b = B.load_bible(root=tmp_path)
        assert b.adult_per_shot() is want, value
        assert b.forced_adult() == {"ep01-S1": "（未写原因）"}
