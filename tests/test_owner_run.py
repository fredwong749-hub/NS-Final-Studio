"""按集渲染（项目方本人）：只认 by=owner；成人 / 🔴 集也可按集渲染；透传 dry_run（桥全部 mock）"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ns_api import owner_run as OR
from ns_api.app import app

c = TestClient(app)


@pytest.fixture
def eps(monkeypatch):
    import ns_api.app as A
    script = SimpleNamespace(episodes=[
        SimpleNamespace(number=1, high_intensity=True, shots=[SimpleNamespace(adult=True)]),
        SimpleNamespace(number=2, high_intensity=False, shots=[SimpleNamespace(adult=False)])])
    monkeypatch.setattr(A, "_script", script)
    calls = []
    monkeypatch.setattr(OR, "_post", lambda path, body, timeout=20: calls.append((path, body)) or {"run_id": "r", **body})
    return calls


def test_red_episode_allowed(eps):
    """2026-10-30 取消成人过滤器：🔴 / 成人集不再 409。"""
    assert c.get("/api/gpu3/episodes/1/run-eligibility").json()["allowed"] is True
    r = c.post("/api/gpu3/episodes/1/run", json={"gpu": 3, "steps": ["frames"], "note": "x", "by": "owner"})
    assert r.status_code == 200 and r.json()["run_id"] == "r" and len(eps) == 1


def test_gpu_restricted_locally(eps):
    for g in (1, 2):
        r = c.post("/api/gpu3/episodes/2/run", json={"gpu": g, "steps": ["frames"], "note": "x", "by": "owner"})
        assert r.status_code == 422 and eps == []


def test_owner_only_and_passthrough(eps):
    body = {"gpu": 3, "steps": ["frames", "video"], "note": "测试 ep02", "dry_run": True}
    assert c.post("/api/gpu3/episodes/2/run", json={**body, "by": "agent"}).status_code == 403
    r = c.post("/api/gpu3/episodes/2/run", json={**body, "by": "owner"}).json()
    assert r["dry_run"] is True and eps[0][0].endswith("/episodes/2/run") and eps[0][1]["by"] == "owner"


def test_unknown_episode_404(eps):
    assert c.get("/api/gpu3/episodes/9/run-eligibility").status_code == 404
