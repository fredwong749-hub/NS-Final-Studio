"""NAVIA：/api/videos/overview（全部集 x 每镜视频状态 + 预计时间）。临时目录，不碰生产数据。"""
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_api import shot_status as SS
from ns_api import video_index as VI
from ns_render import pipeline as P

NOW = 1_800_000_000.0


def _shot(root, ep, idx, takes, active):
    d = root / f"ep{ep:02d}" / f"S{idx}"
    d.mkdir(parents=True)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active}), encoding="utf-8")


def V(n):
    return {"n": n, "stage": "video", "file": f"renders/ep01/S1/takes/video_{n:03d}.mp4"}


def test_states_and_eta(tmp_path, monkeypatch):
    r = tmp_path / "r"
    _shot(r, 1, 1, [V(1)], {"image": 1, "last": 1, "video": 1})   # 已定稿
    _shot(r, 1, 2, [V(1)], {"image": 1, "last": 1, "video": 1})   # 待审
    _shot(r, 1, 3, [], {"image": 1, "last": 1})                   # 在出
    _shot(r, 1, 4, [], {"image": 1, "last": 1})                   # 排队 1
    _shot(r, 1, 5, [], {"image": 1})                              # 缺尾帧
    _shot(r, 2, 1, [], {"image": 1, "last": 1})                   # 帧齐未出
    monkeypatch.setattr(P, "RENDERS", r)
    monkeypatch.setattr(SS, "_reviewed", lambda sid, t: "passed" if sid == "ep01-S1" else None)
    monkeypatch.setattr(VI, "_ledger_shots", lambda ep=None: [])   # UIUX-LOOP-2 r7：只测目录里的镜 / 任务表口径，不读活登记表
    monkeypatch.setattr(SS, "ledger_cell", lambda sid, st: None)
    jobs = [{"id": "a", "shot_id": "ep01-S3", "kind": "video", "state": "running", "gpu": 3, "started_at": "2027-01-15T08:00:00+00:00", "created_at": "2027-01-15T07:59:00+00:00"},
            {"id": "b", "shot_id": "ep01-S4", "kind": "video", "state": "queued", "gpu": 3, "created_at": "2027-01-15T08:00:10+00:00"}]
    app = FastAPI()
    app.include_router(VI.router)
    d = VI.build(jobs=jobs, median_s=600, now=1_800_000_000.0)
    st = {s["id"]: s for e in d["episodes"] for s in e["shots"]}
    assert {k: v["state"] for k, v in st.items()} == {"ep01-S1": "final", "ep01-S2": "pending_review", "ep01-S3": "rendering", "ep01-S4": "queued", "ep01-S5": "need_frames", "ep02-S1": "todo"}
    assert st["ep01-S5"]["missing"] == ["last"] and st["ep01-S4"]["queue_pos"] == 1 and st["ep01-S4"]["eta"] and st["ep01-S3"]["eta"]
    assert d["summary"]["total"] == 6 and d["summary"]["eta_all"] and d["summary"]["median_s"] == 600
    assert [e["ep"] for e in d["episodes"]] == [1, 2]
    assert VI.build(ep=2, jobs=[], median_s=600)["summary"]["total"] == 1
    assert VI.build(state="final", jobs=jobs, median_s=600)["summary"]["total"] == 1
    c = TestClient(app)
    assert c.get("/api/videos/overview?state=bogus").status_code == 422
