"""UX4：GET /api/post/dialogue-source 只读 config/render_quality.json 的 post.dialogue_source。"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "api"))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ns_api import post_settings as P  # noqa: E402


def _client(tmp_path, cfg):
    f = tmp_path / "render_quality.json"
    f.write_text(json.dumps(cfg), encoding="utf-8")
    P.CFG = f
    a = FastAPI()
    a.include_router(P.router)
    return TestClient(a)


def test_default_and_per_episode(tmp_path, monkeypatch):
    old = P.CFG
    try:
        c = _client(tmp_path, {"post": {"dialogue_source": {"default": "h3", "per_episode": {"5": "tts"}}}})
        r = c.get("/api/post/dialogue-source?ep=2").json()
        assert r["source"] == "h3" and r["label"] == "视频原声"
        assert c.get("/api/post/dialogue-source?ep=5").json()["source"] == "tts"
    finally:
        P.CFG = old


def test_missing_config_falls_back(tmp_path):
    old = P.CFG
    try:
        P.CFG = tmp_path / "nope.json"
        a = FastAPI()
        a.include_router(P.router)
        r = TestClient(a).get("/api/post/dialogue-source").json()
        assert r["source"] == "tts"
    finally:
        P.CFG = old
