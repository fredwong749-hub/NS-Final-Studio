"""合并导入后 S1 按集判版本（2026-10-30：v2 底稿 + rules_v2 ep01 合并后，全部 361 镜都被判 s1_gate_not_passed）"""
from ns_agent.state_timeline import episode_version
from ns_schema.script import ScriptGlobals, ScriptImport, SourceFile


def test_episode_version_prefers_recorded_source():
    s = ScriptImport(sources=[SourceFile(path="D:/x/为他而骚 （剧本和镜头）v2.md", sha256="a"),
                              SourceFile(path="D:/x/script_chat/abc/script.md", sha256="b", version="v3", episodes=[1])],
                     globals=ScriptGlobals(), episodes=[], warnings=[])
    assert episode_version(s, 1) == "v3"
    assert episode_version(s, 2) == "v2"      # 没被新稿替换的集 = 底稿版本


def test_later_source_wins():
    s = ScriptImport(sources=[SourceFile(path="a.md", sha256="a", version="v3", episodes=[1, 2]),
                              SourceFile(path="b.md", sha256="b", version="v4", episodes=[2])],
                     globals=ScriptGlobals(), episodes=[], warnings=[])
    assert episode_version(s, 1) == "v3" and episode_version(s, 2) == "v4"
