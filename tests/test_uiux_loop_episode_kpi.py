"""UIUX-LOOP r3（11-06）：每集进度 / KPI 面板的后端 GET /api/episodes/kpi（L-205 ≤ 50 min、L-207 三段）。
纯函数 build() 用临时登记表 / takes / 快照；阶段、计时、兜底、只给通过的图。全部临时目录。"""
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import episode_kpi as K  # noqa: E402

NOW = 1_800_000_000.0
URL = lambda rel: f"/files/{rel}" if rel else None  # noqa: E731


def _shot(sid, idx, **st):
    objs = {k: {"status": v} for k, v in st.items()}
    return {"shot": sid, "index": idx, "objects": objs}


def _takes(renders: Path, sid: str, active: dict, extra=None):
    ep, s = sid.split("-")
    d = renders / ep / s
    d.mkdir(parents=True, exist_ok=True)
    takes = [{"stage": st, "n": n, "file": f"renders/r/{ep}/{s}/takes/{st}_{n}.png"} for st, n in active.items()]
    d.joinpath("takes.json").write_text(json.dumps({"takes": takes, "active": active, **(extra or {})}), encoding="utf-8")


def test_phases_counts_fallback_and_budget(tmp_path):
    renders = tmp_path / "renders"
    reg = {"run": "r", "heartbeat": NOW - 20, "episodes": [
        {"ep": 1, "title": "一", "shots": [_shot("ep01-S1", 1, first="passed", last="passed", video="passed"),
                                            _shot("ep01-S2", 2, first="passed", last="ready", video="pending")],
         "objects": {"assembly": {"status": "pending"}}},
        {"ep": 2, "title": "二", "shots": [_shot("ep02-S1", 1, first="ready", last="pending", video="pending")]},
        {"ep": 3, "title": "三", "shots": [_shot("ep03-S1", 1, first="pending")]},
    ]}
    _takes(renders, "ep01-S1", {"image": 3, "last": 7, "video": 2})
    _takes(renders, "ep01-S2", {"image": 5}, {"last_frame_fallback": {"mode": "i2va", "first_n": 5, "why": "看镜头"}})
    snap = {"t": NOW - 60, "at": "x", "kpi": {"1": {"start": "11-06 14:50", "elapsed_min": 65.0, "eta_min": 12.0, "assembled": False}}}
    out = K.build(registry=reg, renders=renders, snapshot=snap, local_starts={"2": NOW - 600}, now=NOW, url=URL, vurl=URL)
    assert out["source"]["kpi"] == "brain" and out["source"]["registry_age_s"] == 20
    e1, e2, e3 = out["episodes"]
    # ep1：首帧齐、尾帧 1 + 兜底 1 = 齐 → 视频阶段；超预算 15 min；兜底镜不算尾帧缺、不给图
    assert e1["phase"] == "videos" and e1["state"] == "over_budget" and e1["over_min"] == 15.0 and e1["eta_min"] == 12.0
    assert (e1["first_done"], e1["last_done"], e1["fallback_n"], e1["video_done"]) == (2, 1, 1, 1)
    s1, s2 = e1["shots"]
    assert s1["first"]["url"].endswith("image_3.png") and s1["last"]["url"].endswith("last_7.png") and s1["video"]["url"].endswith("video_2.png")
    assert s2["last"]["state"] == "fallback" and s2["last"]["url"] is None and s2["last"]["fallback"]["mode"] == "i2va"
    assert s2["video"]["state"] == "pending" and s2["video"]["url"] is None
    # ep2：快照里没有 → 本机日志起点（10 min 前），在预算内，首尾帧阶段
    assert e2["phase"] == "frames" and e2["state"] == "in_budget" and e2["elapsed_min"] == 10.0 and e2["over_min"] is None
    # ep3：没起点、没产物
    assert e3["phase"] == "not_started" and e3["state"] == "not_started" and e3["start"] is None


def test_assembled_but_videos_missing_is_assembly_not_done():
    assert K.derive_phase(16, 16, 12, 3, 14, True, True) == "assembly"
    assert K.derive_phase(16, 16, 13, 3, 16, True, True) == "done"
    assert K.derive_phase(16, 16, 16, 0, 16, False, True) == "assembly"
    assert K.derive_phase(16, 0, 0, 0, 0, False, False) == "not_started"


def test_stale_snapshot_falls_back_to_local(tmp_path):
    reg = {"run": "r", "episodes": [{"ep": 1, "title": "一", "shots": [_shot("ep01-S1", 1, first="running")]}]}
    snap = {"t": NOW - 7200, "kpi": {"1": {"start": "x", "elapsed_min": 9999, "assembled": True}}}
    out = K.build(registry=reg, renders=tmp_path, snapshot=snap, local_starts={}, now=NOW, url=URL, vurl=URL)
    e = out["episodes"][0]
    assert out["source"]["kpi"] == "local" and e["phase"] == "frames" and e["state"] == "not_started" and e["elapsed_min"] is None


def test_first_dispatch_local(tmp_path):
    log = tmp_path / "log.jsonl"
    log.write_text("\n".join([json.dumps({"ev": "dispatch", "t": 100.0, "obj": "first:ep01-S3"}), json.dumps({"ev": "dispatch", "t": 50.0, "obj": "last:ep01-S1"}),
                              json.dumps({"ev": "adopt", "t": 10.0, "obj": "first:ep02-S1"}), "garbage"]), encoding="utf-8")
    assert K.first_dispatch_local(log) == {"1": 50.0}
    assert K.first_dispatch_local(tmp_path / "none.jsonl") == {}


def test_route_registered_and_cached(monkeypatch):
    calls = []
    monkeypatch.setattr(K, "_build_live", lambda run: (calls.append(run), {"run": run, "episodes": []})[1])
    monkeypatch.setattr(K, "_cache", {})
    app = FastAPI()
    app.include_router(K.router)
    c = TestClient(app)
    assert c.get("/api/episodes/kpi").json()["episodes"] == []
    assert c.get("/api/episodes/kpi").status_code == 200 and calls == [None]
