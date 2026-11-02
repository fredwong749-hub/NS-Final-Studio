"""链条契约（CHAINSPEC 2026-10-31）：chain.yaml 引用完整、上游 schema 校验、连接逐字一致、bug 归因。不调用 LLM。"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))

import chainlib  # noqa: E402,F401  (设置 sys.path)
from ns_schema import episode_outline as EO  # noqa: E402
from ns_schema import screenplay as SPM  # noqa: E402
from ns_schema import storyline as SL  # noqa: E402


def _storyline(age=22):
    return {"schema": "nsfs.storyline/1", "title": "T", "premise": "p", "world": {"setting": "s"},
            "characters": [{"name": "甲", "char_id": "ch_a", "role": "主角", "age": age, "gender": "女", "zh_look": "系统锁",
                            "en_phrase": "a 22-year-old East Asian woman with long black hair",
                            "voice_phrase": "a bright young female voice, brisk pace"}],
            "scenes": [{"scene_id": "sk_room", "name": "房间", "space": "小房间", "time_of_day": "夜", "light": "台灯暖光",
                        "fixtures": "桌子、椅子"}],
            "episodes": [{"episode": 1, "title": "一", "owner_line": "原话", "logline": "原话展开", "characters": ["甲"],
                          "scenes": ["sk_room"]}]}


def test_chain_integrity():
    import check_chain
    errs = [r for r in check_chain.integrity() if r["level"] == "error"]
    assert not errs, errs


def test_storyline_adult_and_link():
    assert SL.check_storyline(_storyline()).ok
    rep = SL.check_storyline(_storyline(age=17))
    assert "SL-02" in {i.rule for i in rep.issues}
    brief = SL.Brief.model_validate({"outline": "x", "episodes": {"from": 1, "to": 1}, "episode_lines": {1: "原话改"}})
    s = SL.Storyline.model_validate(_storyline())
    assert "LK01-02" in {i.rule for i in SL.check_link_p0_p1(brief, s).issues}


def test_outline_and_screenplay_links():
    s = SL.Storyline.model_validate(_storyline())
    o = EO.EpisodeOutline.model_validate({"episode": 1, "title": "一", "logline": "原话展开", "intimate": False,
                                          "target_duration_s": 60, "characters": ["甲"], "scenes": ["sk_room"],
                                          "beats": [{"id": "B1", "summary": "坐下", "scene_id": "sk_room", "characters": ["甲"],
                                                     "est_s": 30, "purpose": "hook"},
                                                    {"id": "B2", "summary": "起身", "scene_id": "sk_room", "characters": ["甲"],
                                                     "est_s": 30, "purpose": "payoff"}], "carry_out": "站着"})
    assert EO.check_link_p1_p2(s, o).ok
    sp = SPM.Screenplay.model_validate({"episode": 1, "title": "一", "target_duration_s": 60, "scenes": [
        {"no": 1, "scene_id": "sk_room", "beat_ids": ["B1", "B2"], "characters": ["甲"],
         "lines": [{"kind": "action", "text": "她坐下"}, {"kind": "dialogue", "speaker": "甲", "text": "好。"}]}]})
    assert SPM.check_link_p2_p3(o, sp).ok
    good = [{"index": 1, "scene_id": "sk_room", "cast": ["甲"], "duration": 60, "dialogue": [("甲", "好。")], "voiceover": None}]
    assert SPM.check_link_p3_p4(sp, good).ok
    bad = [{**good[0], "dialogue": [("甲", "好的。")], "voiceover": ("甲", "多出来的独白")}]
    rules = {i.rule for i in SPM.check_link_p3_p4(sp, bad).issues if i.level == "block"}
    assert {"LK34-01", "LK34-03"} <= rules


def test_screenplay_speaker_prefix_blocked():
    rep = SPM.check_screenplay({"episode": 1, "title": "一", "target_duration_s": 60, "scenes": [
        {"no": 1, "scene_id": "sk_room", "beat_ids": ["B1"], "characters": ["甲"],
         "lines": [{"kind": "dialogue", "speaker": "甲", "text": "“好。”"}]}]}, roster=["甲"])
    assert "SP-04" in {i.rule for i in rep.issues}


def test_attribute_narrator_to_p4_p9():
    import attribute_bug
    r = attribute_bug.attribute("旁白声音老")
    assert r["primary_link"] == "P4-P9"
    assert attribute_bug.attribute("完全无关的描述 xyz")["primary_link"] is None


def test_storyline_placeholder_blocked():
    """SL-12（总调度 11-02，r4-fable 发现第 3 集正文漏出“（未提供）”）：占位词一律阻断；全半角都认；正常文字不误伤"""
    for bad in ("（未提供）", "(未提供)", "待定", "TODO 补", "她叫XXX", "ＸＸＸ", "<女主名>", "＜场景＞", "tbd"):
        s = _storyline()
        s["episodes"][0]["logline"] = "原话展开，" + bad
        rep = SL.check_storyline(s)
        assert any(i.rule == "SL-12" and i.field == "episodes[0].logline" for i in rep.issues), bad
        assert not rep.ok
    s = _storyline()
    s["episodes"][0]["logline"] = "她把 TODOS 清单撕了，Xbox 摔在地上，定下心来"     # 不是占位词
    assert SL.check_storyline(s).ok
    assert SL.placeholder_hits({"a": [{"b": "x（未提供）"}]}) == [("a[0].b", "未提供")]
