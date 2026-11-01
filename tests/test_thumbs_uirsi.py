"""UIRSI 缩略图：只读 data/ 下的图、按宽度缓存、源图变了换缓存、越界 404。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient
from PIL import Image


def test_thumb_cache_and_bounds(tmp_path, monkeypatch):
    from ns_api import thumbs as T
    monkeypatch.setattr(T, "REPO", tmp_path)
    img = tmp_path / "data" / "pipeline" / "x.png"
    img.parent.mkdir(parents=True)
    Image.new("RGB", (1000, 2000), (200, 10, 10)).save(img)
    app = FastAPI()
    app.include_router(T.router)
    c = TestClient(app)
    r = c.get("/api/thumb", params={"src": "/files/pipeline/x.png?v=1", "w": 300})
    assert r.status_code == 200 and r.headers["content-type"] == "image/jpeg"
    from io import BytesIO
    assert Image.open(BytesIO(r.content)).size == (360, 720)       # 按 120 取整
    assert len(list((tmp_path / "data" / "_cache" / "thumbs").glob("*.jpg"))) == 1
    c.get("/api/thumb", params={"src": "/files/pipeline/x.png", "w": 360})
    assert len(list((tmp_path / "data" / "_cache" / "thumbs").glob("*.jpg"))) == 1   # 同宽复用
    assert c.get("/api/thumb", params={"src": "/files/../secret.png"}).status_code == 404
    assert c.get("/api/thumb", params={"src": "/etc/x.png"}).status_code == 422


def test_thumb_assets_source(tmp_path, monkeypatch):
    from ns_api import thumbs as T
    monkeypatch.setattr(T, "REPO", tmp_path)
    img = tmp_path / "assets" / "characters" / "a" / "face.png"
    img.parent.mkdir(parents=True)
    Image.new("RGB", (800, 800)).save(img)
    app = FastAPI()
    app.include_router(T.router)
    c = TestClient(app)
    assert c.get("/api/thumb", params={"src": "/api/assets/file?path=assets/characters/a/face.png&v=1", "w": 120}).status_code == 200
    assert c.get("/api/thumb", params={"src": "/api/assets/file?path=../x.png"}).status_code == 404
