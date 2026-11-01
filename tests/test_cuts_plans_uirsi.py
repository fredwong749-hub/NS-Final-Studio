"""UIRSI：成片页列出方案 A/B/C 的整集成片（只读，出来后自动出现）；逐镜试验片不算。"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_render import pipeline as P


def test_plan_cuts_listed(tmp_path, monkeypatch):
    from ns_api import cuts as C
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    for rel in ("episodes/ep02_v1.mp4", "ab/planB/ep02/ep02_planB.mp4", "ab/planB/ep02/S2/B1_S2.mp4",
                "ab/planC/ep02_planC_v1.mp4", "episodes/planA/ep02_A.mp4", "ab/planC/ep12_x.mp4"):
        f = tmp_path / "data" / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(b"x")
    app = FastAPI()
    app.include_router(C.router)
    cuts = TestClient(app).get("/api/episodes/2/cuts").json()["cuts"]
    names = {c["name"] for c in cuts}
    assert names == {"ep02_v1.mp4", "方案 B · ep02_planB.mp4", "方案 C · ep02_planC_v1.mp4", "方案 A · ep02_A.mp4"}
    b = next(c for c in cuts if c["plan"] == "B")
    assert b["url"].startswith("/files/ab/planB/ep02/ep02_planB.mp4") and "方案 B" in b["tags"]


def test_old_script_cuts_flagged(tmp_path, monkeypatch):
    """比最近一次整份替换导入（mode=replace）更早合成的成片标 old_script（界面默认不显示）；按集合并导入不算"""
    import json as J
    import os
    import time as T
    from ns_api import cuts as C
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    ep = tmp_path / "data" / "episodes"
    ep.mkdir(parents=True)
    (ep / "ep01_old.mp4").write_bytes(b"x")
    (ep / "ep01_new.mp4").write_bytes(b"x")
    os.utime(ep / "ep01_old.mp4", (1000, 1000))
    os.utime(ep / "ep01_new.mp4", (5_000_000_000, 5_000_000_000))
    log = tmp_path / "data" / "import" / "import_log.jsonl"
    log.parent.mkdir(parents=True)
    app = FastAPI()
    app.include_router(C.router)
    cl = TestClient(app)
    log.write_text(J.dumps({"at": "2026-10-31T20:08:50", "mode": "merge"}) + chr(10), encoding="utf-8")
    assert not any(c["old_script"] for c in cl.get("/api/episodes/1/cuts").json()["cuts"])
    at = T.strftime("%Y-%m-%dT%H:%M:%S", T.localtime(3000))
    with log.open("a", encoding="utf-8") as f:
        f.write(J.dumps({"at": at, "mode": "replace"}) + chr(10))
    d = cl.get("/api/episodes/1/cuts").json()
    assert {c["name"]: c["old_script"] for c in d["cuts"]} == {"ep01_old.mp4": True, "ep01_new.mp4": False}
    assert cl.get("/api/script/replaced-at").json()["at"] == at
