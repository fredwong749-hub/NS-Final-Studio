"""人物管理页后端（manage.py）"""
import io

import pytest
from fastapi.testclient import TestClient

from ns_api import assets as A
from ns_api import manage as MG


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setattr(A, "ASSETS_DIR", tmp_path / "assets")
    monkeypatch.setattr(A, "ROOT", tmp_path)
    from fastapi import FastAPI
    app = FastAPI()
    app.include_router(MG.router)
    return TestClient(app)


def test_create_person_and_upload(client, tmp_path, monkeypatch):
    monkeypatch.setattr(MG, "people", lambda store=None: {"people": [{"id": "su_qing"}]})
    assert client.post("/api/people", json={"id": "Bad Id", "name": "x"}).status_code == 422
    r = client.post("/api/people", json={"id": "su_qing", "name": "苏晴", "role": "闺蜜"})
    assert r.status_code == 201, r.text
    base = tmp_path / "assets" / "characters" / "su_qing"
    assert (base / "items" / "shoes").is_dir() and MG.read_meta("su_qing")["name"] == "苏晴"
    assert client.post("/api/people", json={"id": "su_qing", "name": "x"}).status_code == 409
    up = client.post("/api/people/su_qing/upload", data={"target": "plate/front"},
                     files={"file": ("f.png", io.BytesIO(b"\x89PNG fake"))})
    assert up.status_code == 201, up.text
    assert up.json()["kind"] == "plate/front" and (base / "plates" / up.json()["file"].split("/")[-1]).is_file()
    assert client.post("/api/people/su_qing/upload", data={"target": "item/socks"},
                       files={"file": ("f.png", io.BytesIO(b"x"))}).status_code == 422
    assert client.post("/api/people/su_qing/upload", data={"target": "plate/front"},
                       files={"file": ("f.exe", io.BytesIO(b"x"))}).status_code == 422
    assert A.classify("plate/front", ("plates", "x.png"), "front_1") == ("plate", "front")
