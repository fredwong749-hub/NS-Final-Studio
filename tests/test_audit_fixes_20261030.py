"""封板修复回归（2026-10-30 全系统审计）：合并导入的全局头、集标题与 🔴、按集版本、文件名版本、ASCII 引号、
项目文件密钥、本人闸门 by、尾帧后缀"""
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from ns_agent.importer.script_md import _parse_episodes, _split_dialogue
from ns_agent.state_timeline import VERSION_IN_NAME, episode_version
from ns_schema.script import CharacterLock, LoraTrigger, ScriptGlobals, ScriptImport, SourceFile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from import_script import dedupe_sources, merge_globals  # noqa: E402


def test_merge_globals_keeps_base_when_new_empty():
    base = ScriptGlobals(character_locks=[CharacterLock(name="林晚", description="x")], motion_suffix="m",
                         base_negative="n", lora_triggers=[LoraTrigger(trigger="a", kind="image", description="旧")])
    new = ScriptGlobals(lora_triggers=[LoraTrigger(trigger="a", kind="image", description="新"),
                                       LoraTrigger(trigger="b", kind="video", description="")])
    g = merge_globals(base, new)
    assert [c.name for c in g.character_locks] == ["林晚"] and g.motion_suffix == "m" and g.base_negative == "n"
    assert {t.trigger: t.description for t in g.lora_triggers} == {"a": "新", "b": ""}


def test_episode_heading_variants_and_red_anywhere():
    for head in ("## ep03 《电梯》🔴", "## EP03《电梯》🔴", "## 🔴ep03《电梯》", "##ep03《电梯》🔴", "## ep03《电梯🔴》"):
        w: list[str] = []
        eps = _parse_episodes(head + "\n**镜1｜img**：x\n", set(), w)
        assert [e.number for e in eps] == [3] and eps[0].high_intensity and eps[0].title == "电梯", head
    w = []
    _parse_episodes("## ep03电梯\n", set(), w)
    assert any("像集标题" in x for x in w)


def test_episode_version_unknown_when_latest_source_unversioned():
    s = ScriptImport(sources=[SourceFile(path="a v2.md", sha256="1", version="v3", episodes=[1]),
                              SourceFile(path="draft.md", sha256="2", version=None, episodes=[1])],
                     globals=ScriptGlobals(), episodes=[])
    assert episode_version(s, 1) == "unknown"


def test_dedupe_same_path_unions_episodes_and_resolves_relative():
    a = SourceFile(path="data/x/script.md", sha256="1", version="v3", episodes=[1])
    b = SourceFile(path=str(Path(__file__).resolve().parents[1] / "data" / "x" / "script.md"), sha256="2",
                   version="v3", episodes=[2])
    out = dedupe_sources([a, b])
    assert len(out) == 1 and out[0].episodes == [1, 2]


def test_version_in_name_ignores_rules_tag():
    assert VERSION_IN_NAME.findall("为他而骚_ep02_qwen_rules_v2_20261030.md") == []
    assert VERSION_IN_NAME.findall("为他而骚 （剧本和镜头）v2.md") == ["2"]
    assert VERSION_IN_NAME.findall("为他而骚 （剧本和镜头）v3.1.md") == ["3"]


def test_ascii_quotes_with_slash():
    lines, stage = _split_dialogue('（她）"你好／再见"')
    assert [x.text for x in lines] == ["你好／再见"] and stage == []


def _client():
    from ns_api.app import app
    return TestClient(app)


def test_project_file_refuses_config_and_local_secrets():
    c = _client()
    for rel in ("config/abliteration.local.json", "config/visual_bible.toml", "ops/autostart/README.md"):
        assert c.get(f"/api/projects/weita/file/{rel}").status_code == 404, rel


def test_owner_gates_require_explicit_owner():
    import pytest
    from fastapi import HTTPException

    from ns_api.projects import _owner
    for bad in ("", "claude-agent", "  "):
        with pytest.raises(HTTPException) as e:
            _owner(bad)
        assert e.value.status_code == 403
    assert _owner("owner") == "owner" and _owner("项目方") == "项目方"


def test_last_frame_rejects_html():
    c = _client()
    from ns_api import app as A
    shot_id = next(f"ep{e.number:02d}-S{s.index}" for e in A._script.episodes for s in e.shots)
    r = c.post(f"/api/shots/{shot_id}/last-frame", files={"file": ("x.html", b"<script>1</script>", "text/html")})
    assert r.status_code == 422


def test_dedupe_keeps_older_version_episodes():
    """复核：同一文件旧版 v2（集 1,2）+ 新版 v3（集 3）→ 1、2 仍是 v2，不能被算成 v3"""
    base = SourceFile(path="script play lib/script.md", sha256="1", version="v2", episodes=[1, 2])
    new = SourceFile(path=str(Path(__file__).resolve().parents[1] / "script play lib" / "script.md"), sha256="2",
                     version="v3", episodes=[3])
    s = ScriptImport(sources=dedupe_sources([base, new]), globals=ScriptGlobals(), episodes=[])
    assert [episode_version(s, n) for n in (1, 2, 3, 4)] == ["v2", "v2", "v3", "unknown"]


def test_unpaired_ascii_quote_keeps_splitting():
    lines, _ = _split_dialogue('他（5"屏）：“甲”／她：“乙”')
    assert [x.text for x in lines] == ["甲", "乙"]


def test_merge_globals_locks_by_name():
    base = ScriptGlobals(character_locks=[CharacterLock(name="林晚", description="a"), CharacterLock(name="顾沉", description="b")])
    new = ScriptGlobals(character_locks=[CharacterLock(name="林晚", description="新")])
    g = merge_globals(base, new)
    assert {c.name: c.description for c in g.character_locks} == {"林晚": "新", "顾沉": "b"}


def test_gpu3_rerender_adult_accepts_any_caller(monkeypatch):
    """2026-10-30 取消成人过滤器：成人镜 / 🔴 集经 gpu3 重出不再要求 by=owner。"""
    from types import SimpleNamespace

    from ns_api import app as A
    from ns_api import readiness as RD
    ep = SimpleNamespace(number=1, high_intensity=True, shots=[])
    shot = SimpleNamespace(id="ep01-S1", adult=True)
    monkeypatch.setattr(A, "_find", lambda sid: (ep, shot))
    monkeypatch.setattr(A, "_refuse_explicit", lambda s: None)
    sent = []
    monkeypatch.setattr(RD, "post_rerender", lambda req: sent.append(req) or {"requests": [{"id": "r1"}]})
    monkeypatch.setattr(A.P, "load_edit", lambda sid: A.ShotEdit() if hasattr(A, "ShotEdit") else SimpleNamespace(model_dump=lambda: {}))
    c = _client()
    assert c.post("/api/shots/ep01-S1/gpu3-rerender", json={"stage": "image"}).status_code == 200 and len(sent) == 1
    assert c.post("/api/shots/ep01-S1/gpu3-rerender", json={"stage": "image", "by": "agent"}).status_code == 200
    assert len(sent) == 2
