"""fredw-92/D2：剧本写了场景 id 时，关键词推断的“地点变了”不切段；转场词照旧切段（合成占位剧本）。"""
import importlib.util
from pathlib import Path

from ns_agent import state_timeline as ST
from ns_agent.importer.script_md import import_script

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("_t_s1_d2", ROOT / "tests/test_scenes_s1.py")
S1 = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(S1)


def test_inferred_place_break_ignored_within_script_scene(tmp_path):
    imp = import_script(S1.write(tmp_path, S1.GLOBAL + S1.ep_text(1)))
    ids = [s.id for s in imp.episodes[0].shots]
    trans = ["episode", "place", "", "次日", "place", ""]
    rows = [{"shot_id": sid, "scene_id": "x", "segment_id": "", "segment_start": bool(t), "place": "", "place_key": "",
             "place_source": "", "time_of_day": "", "time_source": "", "transition": t} for sid, t in zip(ids, trans)]
    out = ST._apply_script_scenes(imp, rows)
    assert [r["segment_id"][-2:] for r in out] == ["01", "01", "01", "02", "02", "02"]
    assert [r["transition"] for r in out] == ["episode", "", "", "次日", "", ""]
    assert all(r["scene_id"] == "sk_place_a" for r in out)


def test_registry_drift_warns_on_merge():
    """fredw-92/D2：单集稿重写了底稿已登记的人物 / 场景时，合并导入给提示（底稿未替换的集逐字引用旧文字）"""
    import sys
    from ns_schema.script import CharacterEntry, SceneEntry, ScriptGlobals
    sys.path.insert(0, str(ROOT / "tools"))
    from import_script import registry_drift
    base = ScriptGlobals(character_registry=[CharacterEntry(name="甲", en="old en", voice="v", defined_in=[3])],
                         scene_library=[SceneEntry(scene_id="sk_a", name="A", defined_in=[3])])
    new = ScriptGlobals(character_registry=[CharacterEntry(name="甲", en="new en", voice="v", defined_in=[4])],
                        scene_library=[SceneEntry(scene_id="sk_a", name="A", defined_in=[4])])
    w = registry_drift(base, new, {4})
    assert len(w) == 1 and "甲" in w[0] and "EN外貌短语" in w[0] and "ep03" in w[0] and "保留先登记" in w[0]
    assert registry_drift(base, new, {3, 4}) == []      # 定义它的那集也被替换了：无冲突


def test_merge_globals_keeps_first_registration():
    """fredw-92 2026-10-31 定：合并导入登记冲突时保留先登记的；定义它的集全部被替换时才用新稿的"""
    import sys
    from ns_schema.script import CharacterEntry, ScriptGlobals
    sys.path.insert(0, str(ROOT / "tools"))
    from import_script import merge_globals
    base = ScriptGlobals(character_registry=[CharacterEntry(name="甲", en="old", defined_in=[3])])
    new = ScriptGlobals(character_registry=[CharacterEntry(name="甲", en="new", defined_in=[4]),
                                            CharacterEntry(name="乙", en="b", defined_in=[4])])
    assert [(c.name, c.en) for c in merge_globals(base, new, {4}).character_registry] == [("甲", "old"), ("乙", "b")]
    assert [(c.name, c.en) for c in merge_globals(base, new, {3, 4}).character_registry][0] == ("甲", "new")
