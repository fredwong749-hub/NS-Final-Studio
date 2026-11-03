"""ASSETUX 1b：“出图”页索引 /api/frames-index（全部集 x 每镜首尾帧当前版；缺图 / 新 / 已定稿 / 生成中；筛选在服务端）。
全部在临时目录里，不碰生产数据。"""
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_api import frames_index as FI
from ns_render import pipeline as P

ROOT = Path(__file__).resolve().parents[1]


def _shot(root, ep, idx, takes, active, locked=None):
    d = root / f"ep{ep:02d}" / f"S{idx}"
    d.mkdir(parents=True)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active, "locked": locked or {}}), encoding="utf-8")


def T(n, stage, **kw):
    return {"n": n, "stage": stage, "file": f"renders/ep01/S1/takes/{stage}_{n:03d}.png", **kw}


@pytest.fixture()
def c(tmp_path, monkeypatch):
    r = tmp_path / "renders"
    # S1：首尾帧都定稿；S2：首帧当前 + 有更新的一版（新），尾帧缺；S3：什么都没有
    _shot(r, 1, 1, [T(1, "image"), T(1, "last")], {"image": 1, "last": 1}, {"image": {"n": 1}, "last": {"n": 1}})
    _shot(r, 1, 2, [T(1, "image"), T(2, "image")], {"image": 1})
    _shot(r, 1, 3, [], {})
    _shot(r, 2, 1, [T(3, "image", quarantined={"at": "x"}), T(1, "image")], {"image": 1}, {})
    monkeypatch.setattr(P, "RENDERS", r)
    monkeypatch.setattr(FI, "_script_chars", lambda run=None: {"ep01-S1": ["lin_wan"], "ep01-S2": ["lin_wan", "gu_chen"], "ep02-S1": ["gu_chen"]})
    monkeypatch.setattr(FI, "_jobs_by_shot", lambda: {("ep01-S2", "last"): {"state": "running", "eta_s": 90, "job_id": "j1", "started_at": None, "created_at": None}})
    app = FastAPI()
    app.include_router(FI.router)
    return TestClient(app)


def cells(d):
    return {s["id"]: s for e in d["episodes"] for s in e["shots"]}


def test_all_episodes_one_cell_per_frame(c):
    d = c.get("/api/frames-index").json()
    s = cells(d)
    assert [e["ep"] for e in d["episodes"]] == [1, 2] and set(s) == {"ep01-S1", "ep01-S2", "ep01-S3", "ep02-S1"}
    assert s["ep01-S1"]["first"]["state"] == "final" and s["ep01-S1"]["last"]["state"] == "final"
    assert s["ep01-S1"]["first"]["url"] == "/files/renders/ep01/S1/takes/image_001.png"
    assert s["ep01-S2"]["first"]["state"] == "current" and s["ep01-S2"]["first"]["new_n"] == 2     # 有更新的一版 = 新
    assert s["ep01-S2"]["first"]["new_url"].endswith("image_002.png")
    assert s["ep01-S2"]["last"]["state"] == "none" and s["ep01-S2"]["last"]["gen"]["state"] == "running"   # 缺图但在生成：呼吸灯
    assert s["ep01-S3"]["first"]["state"] == "none" and s["ep01-S3"]["first"]["url"] is None
    assert s["ep02-S1"]["first"]["new_n"] is None                                                   # 隔离的旧版本不算“新”
    assert {k: d["counts"][k] for k in ("shots", "missing", "new", "final")} == {"shots": 4, "missing": 3, "new": 1, "final": 1}
    assert d["gen"] == {"running": 1, "queued": 0}


def test_filters_by_episode_status_and_character(c):
    assert [x["id"] for e in c.get("/api/frames-index?ep=2").json()["episodes"] for x in e["shots"]] == ["ep02-S1"]
    assert set(cells(c.get("/api/frames-index?status=missing").json())) == {"ep01-S2", "ep01-S3", "ep02-S1"}
    assert set(cells(c.get("/api/frames-index?status=new").json())) == {"ep01-S2"}
    assert set(cells(c.get("/api/frames-index?status=final").json())) == {"ep01-S1"}
    assert set(cells(c.get("/api/frames-index?char=gu_chen").json())) == {"ep01-S2", "ep02-S1"}
    assert c.get("/api/frames-index?status=rejected").status_code == 422                            # 没有“不要”这个状态


def test_failing_versions_are_never_shown_as_new(c, tmp_path, monkeypatch):
    """17:0x 事故：ep07-S3 尾帧 #19 Q1 fail（陌生人）当“新”给项目方看。现在只有通过验收的版本才算“新”，没通过的留在系统里重出"""
    r = tmp_path / "renders"
    fail_pf = {"items": [{"id": "Q1", "status": "fail", "detail": "身份余弦 0.22 < 0.6"}]}
    _shot(r, 3, 3, [T(8, "last"), T(19, "last", postflight=fail_pf), T(20, "last", postflight={"items": [{"id": "Q1", "status": "pass"}]})], {"last": 8})
    monkeypatch.setattr(P, "RENDERS", r)
    s = cells(c.get("/api/frames-index?ep=3").json())["ep03-S3"]["last"]
    assert s["new_n"] == 20 and s["new_url"].endswith("last_020.png")          # 新 = 最新一版里通过的那张
    assert s["sys_retry"] == 1                                                  # #19 没过：只记次数（“系统在重出”），不给图
    _shot(r, 3, 4, [T(8, "last"), T(19, "last", postflight=fail_pf)], {"last": 8})
    s4 = cells(c.get("/api/frames-index?ep=3").json())["ep03-S4"]["last"]
    assert s4["new_n"] is None and s4["new_url"] is None and s4["sys_retry"] == 1 and s4["url"].endswith("last_008.png")
    assert "ep03-S4" not in cells(c.get("/api/frames-index?status=new").json())       # 没有通过的新版本 = 不算“待你看”


def test_candidates_api_hides_failing_versions_when_only_passing(tmp_path, monkeypatch):
    """所有给项目方看的入口读 /api/candidates?only_passing=1：没通过的版本不返回（当前版本本身除外）；不带参数仍是排查口径（带 ok / why_not）"""
    from ns_api import takes_ui as TU
    r = tmp_path / "renders"
    fail_pf = {"items": [{"id": "Q1", "status": "fail", "detail": "陌生人"}]}
    _shot(r, 7, 3, [T(8, "last"), T(19, "last", postflight=fail_pf)], {"last": 8})
    monkeypatch.setattr(P, "RENDERS", r)
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(TU, "_P", lambda: P)
    for n in (8, 19):
        f = tmp_path / "renders" / "ep01" / "S1" / "takes"
        f.mkdir(parents=True, exist_ok=True)
        (f / f"last_{n:03d}.png").write_bytes(b"x")
    allv = TU.candidates(7)["shots"]["ep07-S3"]["last"]["takes"]
    onlyp = TU.candidates(7, only_passing=True)["shots"]["ep07-S3"]["last"]["takes"]
    assert [x["n"] for x in allv] == [8, 19] and [x["n"] for x in onlyp] == [8]
    assert allv[1]["ok"] is False
    src = (ROOT / "apps" / "web" / "src" / "v3" / "candidates.ts").read_text(encoding="utf-8")
    assert "only_passing=1" in src                                              # 画布格、候选框、出图页都经这里
