"""露骨红标已取消（2026-10-30）：三种来源都不再产生 explicit_hold，也不拦任何动作。"""
import json

import pytest
from fastapi.testclient import TestClient

from ns_agent.importer.script_md import import_script
from ns_schema.script import Episode, ScriptGlobals, ScriptImport, Shot


def _shot(i, **kw):
    return Shot(episode=1, index=i, source_line=1, img_prompt="房间", motion_prompt="static camera", sound="安静", **kw)


@pytest.fixture()
def api(tmp_path, monkeypatch):
    from ns_api import app as app_mod
    from ns_api import readiness as RD
    from ns_render import pipeline as P
    data = tmp_path / "data"
    (data / "renders").mkdir(parents=True)
    (data / "renders_gpu3").mkdir()
    sc = ScriptImport(sources=[], globals=ScriptGlobals(), episodes=[Episode(number=1, title="t", source_line=1, shots=[
        _shot(1), _shot(2), _shot(3, h3_check="暂缓（露骨内容）"), _shot(4)])])
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    monkeypatch.setattr(RD, "GPU3_ROOT", data / "renders_gpu3")
    monkeypatch.setattr(app_mod, "_script", sc)
    return TestClient(app_mod.app), data / "renders_gpu3"


def test_importer_reads_h3_check(tmp_path):
    p = tmp_path / "v3.md"
    p.write_text("## ep01《t》\n\n**镜1｜img**：`房间`\n\n**motion**：`static camera`\n\n**H3校验**：暂缓（露骨内容）\n\n"
                 "**sound**：`安静`\n", encoding="utf-8")
    s = import_script(p).episodes[0].shots[0]
    assert s.h3_check == "暂缓（露骨内容）" and s.sound == "安静"


def test_explicit_hold_sources_no_longer_hold(api):
    c, g = api
    (g / "ep01" / "S1").mkdir(parents=True)
    (g / "ep01" / "S1" / "status.json").write_text(json.dumps({"audit": {"blocked": "explicit_content_not_supported"}}),
                                                  encoding="utf-8")
    (g / "BLOCKED.jsonl").write_text(json.dumps({"shot": "ep01-S2", "blocked": "explicit_content_not_supported"}) + "\n",
                                     encoding="utf-8")
    eps = c.get("/api/episodes").json()
    assert all(s["explicit_hold"] is None for s in eps[0]["shots"])
    assert eps[0]["explicit_hold_count"] == 0
    lst = c.get("/api/explicit-holds").json()
    assert lst["count"] == 0 and lst["shots"] == []
