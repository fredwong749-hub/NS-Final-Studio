"""单集导入 = 只替换这一集（2026-10-30 总调度：ep01 单集导入曾让画布只剩 1 集）"""
import importlib.util
from pathlib import Path

from ns_schema.script import Episode, ScriptGlobals, ScriptImport, Shot

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("import_script_tool", ROOT / "tools" / "import_script.py")
IS = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(IS)


def _ep(n: int, tag: str) -> Episode:
    return Episode(number=n, title=f"{tag}{n}", source_line=1,
                   shots=[Shot(episode=n, index=1, img_prompt=tag, source_line=1)])


def test_auto_triggers_add_character_lora(tmp_path):
    """系统自动补：画面里有林晚的镜头补 lnwan_qi，并在 globals 登记；没有林晚的不补；重复调用不重复加"""
    import json
    from ns_schema.script import CharacterLock
    cfg = tmp_path / "auto.json"
    cfg.write_text(json.dumps({"characters": {"林晚": [{"trigger": "lnwan_qi", "kind": "image",
                                                      "file": "x.safetensors", "strength": 0.8}]}}), encoding="utf-8")
    g = ScriptGlobals(character_locks=[CharacterLock(name="林晚", description="占位")])
    eps = [Episode(number=1, title="t", source_line=1, shots=[
        Shot(episode=1, index=1, img_prompt="林晚站在窗边", source_line=1),
        Shot(episode=1, index=2, img_prompt="空无一人的走廊", source_line=2)])]
    r = ScriptImport(sources=[], globals=g, episodes=eps, warnings=[])
    assert IS.auto_triggers(r, cfg) == 1 and IS.auto_triggers(r, cfg) == 0
    assert r.episodes[0].shots[0].img_triggers == ["lnwan_qi"] and r.episodes[0].shots[1].img_triggers == []
    assert [t.trigger for t in r.globals.lora_triggers] == ["lnwan_qi"] and r.globals.lora_triggers[0].strength == (0.8, 0.8)


def test_merge_dedupes_sources_keeping_latest(tmp_path):
    """封板修复：合并不再重复追加 sources；同一路径保留最新（带 version / episodes）的那条"""
    from ns_schema.script import SourceFile
    base = ScriptImport(sources=[SourceFile(path="lib/v2.md", sha256="a"),
                                 SourceFile(path="chat\\x\\script.md", sha256="old")],
                        globals=ScriptGlobals(), episodes=[_ep(1, "旧")], warnings=[])
    p = tmp_path / "base.json"
    p.write_text(base.model_dump_json(), encoding="utf-8")
    new = ScriptImport(sources=[SourceFile(path="chat/x/script.md", sha256="new", version="v3", episodes=[1])],
                       globals=ScriptGlobals(), episodes=[_ep(1, "新")], warnings=[])
    m = IS.merge_into(p, new)
    assert [(s.path, s.sha256, s.version) for s in m.sources] == [("lib/v2.md", "a", None),
                                                                   ("chat/x/script.md", "new", "v3")]


def test_merge_replaces_only_given_episodes(tmp_path):
    base = ScriptImport(sources=[], globals=ScriptGlobals(), episodes=[_ep(n, "旧") for n in (1, 2, 3)], warnings=[])
    p = tmp_path / "base.json"
    p.write_text(base.model_dump_json(), encoding="utf-8")
    new = ScriptImport(sources=[], globals=ScriptGlobals(), episodes=[_ep(1, "新")], warnings=["缺少集数：[2, 3]"])
    m = IS.merge_into(p, new)
    assert [(e.number, e.title) for e in m.episodes] == [(1, "新1"), (2, "旧2"), (3, "旧3")]
    assert not any(w.startswith("缺少集数") for w in m.warnings) and "替换集 [1]" in m.warnings[-1]
    # 底稿里没有的集号追加在后面
    m2 = IS.merge_into(p, ScriptImport(sources=[], globals=ScriptGlobals(), episodes=[_ep(4, "新")], warnings=[]))
    assert [e.number for e in m2.episodes] == [1, 2, 3, 4]
