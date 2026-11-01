"""UIRSI 音色试听 / 一键换音色：试听用本机合成（测试里换成假合成，不跑模型）；换音色要登录的项目方，改前整份备份，撤销=选回。"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def env(tmp_path, monkeypatch):
    from ns_api import voice_preview as V
    tts = V._post()   # 先按真实仓库路径导入合成模块，再把项目根换成临时目录
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "voices.json").write_text(json.dumps({"tts_model": "x", "characters": {
        "a": {"name": "甲", "gender": "female", "sid": 36, "voice": "zf_067", "speed": 1.0}}}, ensure_ascii=False), encoding="utf-8")
    (tmp_path / "data" / "import").mkdir(parents=True)
    (tmp_path / "data" / "import" / "script_v2.json").write_text(json.dumps({"episodes": [{"shots": [{"dialogue": [["甲", "我想再试一次。"]]}]}]}, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(V, "REPO", tmp_path)
    monkeypatch.setattr(tts, "KokoroBackend", lambda cfg, **kw: tts.FakeTts())
    monkeypatch.setattr(tts, "load_voice_config", lambda *a, **k: {})
    orig = tts.synthesize_cached
    monkeypatch.setattr(tts, "synthesize_cached", lambda b, req: orig(b, req, cache_dir=tmp_path / "data" / "cache" / "tts"))
    app = FastAPI()
    app.include_router(V.router)
    return TestClient(app), tmp_path


def test_preview_uses_first_line(env):
    c, tmp = env
    r = c.post("/api/voices/preview", json={"cid": "a"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["text"] == "我想再试一次。" and j["url"].startswith("/files/cache/tts/") and j["sid"] == 36
    assert c.post("/api/voices/preview", json={"cid": "a", "speed": 3}).status_code == 422


def test_select_owner_backup_and_undo(env):
    c, tmp = env
    assert c.post("/api/voices/a/select", json={"sid": 40}).status_code == 403
    assert c.post("/api/voices/a/select", json={"sid": 70, "by": "owner"}).status_code == 422      # 性别不对
    r = c.post("/api/voices/a/select", json={"sid": 40, "speed": 1.05, "by": "owner"})
    assert r.status_code == 200 and r.json()["prev"]["sid"] == 36
    cfg = json.loads((tmp / "config" / "voices.json").read_text(encoding="utf-8"))
    assert cfg["characters"]["a"]["sid"] == 40 and cfg["characters"]["a"]["speed"] == 1.05
    assert list((tmp / "data" / "assets" / "voice_backups").glob("voices_*.json"))
    c.post("/api/voices/a/select", json={"sid": 36, "speed": 1.0, "by": "owner"})                    # 撤销 = 选回
    assert json.loads((tmp / "config" / "voices.json").read_text(encoding="utf-8"))["characters"]["a"]["sid"] == 36
    cands = c.get("/api/voices/candidates", params={"cid": "a"}).json()
    assert 36 in cands["near"] and all(3 <= s <= 57 for s in cands["all"])
