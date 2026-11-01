"""UIRSI 账户登录：项目方闸门从登录会话取身份（不再要原话），写操作自动审计。

项目方 2026-10-31 原话：“系统是在我 login 的，意味着我所做的所有行为都是我个人行为，所以你不需要每个东西都要打上一个字。”
"""
import json

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import BaseModel


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    from ns_api import auth as A
    monkeypatch.setattr(A, "REPO", tmp_path)
    app = FastAPI()

    class B(BaseModel):
        by: str = ""
        owner_quote: str = ""
        id: str = ""

    @app.post("/api/gate")   # 模拟一个旧式闸门接口：要 by=owner + 原话
    def gate(b: B):
        if b.by != "owner":
            raise HTTPException(403, "只接受项目方本人")
        if not b.owner_quote.strip():
            raise HTTPException(400, "要原话")
        return {"ok": True, "quote": b.owner_quote}

    A.install(app)
    return TestClient(app), tmp_path


def test_setup_login_logout(app_env):
    c, _ = app_env
    assert c.get("/api/auth/me").json() == {"user": None, "setup_needed": True}
    assert c.post("/api/auth/setup", json={"name": "fred", "password": "x"}).status_code == 422
    r = c.post("/api/auth/setup", json={"name": "fred", "password": "secret1"})
    assert r.status_code == 200 and r.json()["user"]["role"] == "owner"
    assert c.get("/api/auth/me").json()["user"] == {"name": "fred", "role": "owner"}
    assert c.post("/api/auth/setup", json={"name": "b", "password": "secret1"}).status_code == 409   # 只能建一次
    c.post("/api/auth/logout")
    assert c.get("/api/auth/me").json()["user"] is None
    assert c.post("/api/auth/login", json={"name": "fred", "password": "bad"}).status_code == 401
    assert c.post("/api/auth/login", json={"name": "fred", "password": "secret1"}).status_code == 200
    users = json.loads((app_env[1] / "data" / "auth" / "users.json").read_text(encoding="utf-8"))["users"]
    assert "secret1" not in json.dumps(users)                                                          # 不存明文


def test_owner_gate_from_session_no_quote(app_env):
    c, tmp = app_env
    # 未登录声称项目方 → 403
    assert c.post("/api/gate", json={"by": "owner", "owner_quote": "伪造的原话"}).status_code == 403
    c.post("/api/auth/setup", json={"name": "fred", "password": "secret1"})
    # 登录的项目方：不填原话也通过，自动记“登录点选”
    r = c.post("/api/gate", json={"by": "owner", "id": "x1"})
    assert r.status_code == 200 and "fred" in r.json()["quote"]
    c.post("/api/auth/logout")
    assert c.post("/api/gate", json={"by": "owner"}).status_code == 403
    lines = [json.loads(x) for f in (tmp / "data" / "audit").glob("*.jsonl") for x in f.read_text(encoding="utf-8").splitlines()]
    ok = [x for x in lines if x["path"] == "/api/gate" and x["status"] == 200]
    assert ok and ok[0]["user"] == "fred" and ok[0]["obj"] == {"id": "x1"} and ok[0]["owner_claim"]
    assert any(x["path"] == "/api/gate" and x["status"] == 403 and x["user"] is None for x in lines)


def test_audit_view_owner_only(app_env):
    c, _ = app_env
    assert c.get("/api/audit").status_code == 403
    c.post("/api/auth/setup", json={"name": "fred", "password": "secret1"})
    c.post("/api/gate", json={"by": "owner"})
    items = c.get("/api/audit").json()["items"]
    assert items and items[0]["path"] in ("/api/gate", "/api/auth/setup")


def test_viewer_token_can_view_not_decide(app_env):
    c, tmp = app_env
    from ns_api import auth as A
    tok = A.viewer_token()
    h = {"x-ns-viewer-token": tok}
    assert c.get("/api/auth/me", headers=h).json()["user"]["role"] == "viewer"
    assert c.post("/api/gate", json={"by": "owner"}, headers=h).status_code == 403
    assert c.get("/api/auth/me", headers={"x-ns-viewer-token": "wrong"}).json()["user"] is None
    assert c.get("/api/audit", headers=h).status_code == 200                                         # 查看者能看操作记录
