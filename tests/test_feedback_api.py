"""FEEDBACK 人类反馈后台：/api/feedback 状态流与必填闸门。"""
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_api import feedback as FB


def _client(tmp_path, monkeypatch, owner=False):
    monkeypatch.setattr(FB, "REPO", tmp_path)
    monkeypatch.setattr(FB.AUTH, "user_of", lambda req: {"name": "fred", "role": "owner"} if owner else None)
    app = FastAPI()
    app.include_router(FB.router)
    return TestClient(app)


def test_full_flow(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch)
    r = c.post("/api/feedback", json={"text": "手不对", "route": "/overview", "run": "series10_v1", "ep": "ep02", "shot": "S3",
                                      "target": {"kind": "video"}, "timecode": 4.3, "screenshot": "data:image/png;base64,iVBORw0KGgo="})
    it = r.json()
    assert it["id"] == "fb-0001" and it["status"] == "new" and it["dot"] == "red" and it["ep"] == 2 and it["has_screenshot"]
    assert c.post("/api/feedback/fb-0001/status", json={"status": "triaged"}).status_code == 422   # 缺分类
    it = c.post("/api/feedback/fb-0001/status", json={"status": "triaged", "category": "video.hand"}).json()
    assert it["owner"] == "VIDLAB" and it["dot"] == "yellow"
    assert c.post("/api/feedback/fb-0001/status", json={"status": "closed"}).status_code == 409    # 不能跳步
    c.post("/api/feedback/fb-0001/status", json={"status": "fixing"})
    assert c.post("/api/feedback/fb-0001/status", json={"status": "fixed"}).status_code == 422     # 缺修复证据
    c.post("/api/feedback/fb-0001/status", json={"status": "fixed", "fix_note": "重出", "fix_evidence": ["a.mp4"]})
    assert c.post("/api/feedback/fb-0001/status", json={"status": "verified", "verify": {"check": "V6", "result": "fail"}}).status_code == 422
    c.post("/api/feedback/fb-0001/status", json={"status": "verified", "verify": {"check": "V6", "result": "pass"}})
    assert c.post("/api/feedback/fb-0001/status", json={"status": "closed"}).status_code == 422    # 缺回归 / 改进 / 漏检分析
    it = c.post("/api/feedback/fb-0001/status", json={"status": "closed", "regression": "data/feedback/regression.jsonl#fb-0001",
                                                       "miss_analysis": "V6 不看形状", "improvements": [{"kind": "check", "ref": "V6b"}]}).json()
    assert it["status"] == "closed" and it["dot"] == "green"
    assert c.post("/api/feedback/fb-0001/status", json={"status": "new"}).status_code == 403       # agent 不能 reopen
    lst = c.get("/api/feedback").json()
    assert lst["total"] == 1 and lst["dots"]["green"] == 1
    assert c.get("/api/feedback?open=1").json()["items"] == []


def test_owner_reopen(tmp_path, monkeypatch):
    c = _client(tmp_path, monkeypatch, owner=True)
    c.post("/api/feedback", json={"text": "x"})
    c.post("/api/feedback/fb-0001/status", json={"status": "triaged", "category": "ui"})
    it = c.post("/api/feedback/fb-0001/status", json={"status": "new", "note": "没修好"}).json()
    assert it["status"] == "new" and it["reopened"] == 1 and it["by"]["name"] == "fred"
    assert c.get("/api/feedback/meta").json()["statuses"][0]["dot"] == "red"
