"""UIUX-LOOP r4（11-06）：镜头状态标签以活的 producer 登记表为准。
现场：ep01 14:49 重导（L-204 psm11）changed_shots 含 S1/S2/S4…，出图页 / 总览把这些镜的当前首尾帧标“旧剧本版本”、板块“过期”；
但登记表 first/last/video 全是 passed（take 号 = 当前版），大脑按 16/16 做完在合成。另有 6 镜因“最新一版（系统自动重试）看图没过”
挂成主标签“看图没过”，而当前版早已通过——项目方只看通过的。全部临时目录。"""
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import shot_status as SS  # noqa: E402
from ns_api import takes_ui as TU  # noqa: E402
from ns_api import v1_guard as G  # noqa: E402
from ns_render import pipeline as P  # noqa: E402

RUN = "series10_v2"
PF_OK = {"ok": True, "items": [{"id": "Q1", "status": "pass"}]}
JUDGE_FAIL = {"vqa_rounds": [{"judge": {"verdict": "fail", "failed_checks": ["accessory_mismatch"]}}]}


def T(n, stage, created, pf=PF_OK, params=None):
    return {"n": n, "stage": stage, "file": f"renders/{RUN}/ep01/S1/takes/{stage}_{n:03d}.png", "created_at": created, "postflight": pf, **({"params": params} if params else {})}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"primary": RUN, "legacy_unprefixed_run": "series10_v1", "runs": {}}), encoding="utf-8")
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders" / RUN)
    monkeypatch.setattr(TU, "cutoff_for", lambda ep, shot=None: "2026-11-06T14:49:28")   # 这一镜 14:49 重导过
    monkeypatch.setattr(TU, "script_sha", lambda: "deadbeef")
    monkeypatch.setattr(SS, "_reg", {"mt": None, "val": {}})
    G._cache.clear()
    yield data
    G._cache.clear()


def _shot(data, takes, active):
    d = data / "renders" / RUN / "ep01" / "S1"
    (d / "takes").mkdir(parents=True, exist_ok=True)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active}), encoding="utf-8")
    for t in takes:
        (data / t["file"]).write_bytes(b"x" * 16)


def _registry(tmp_path, monkeypatch, objs):
    reg = tmp_path / "registry.json"
    reg.write_text(json.dumps({"episodes": [{"ep": 1, "shots": [{"shot": "ep01-S1", "index": 1, "objects": objs}]}]}), encoding="utf-8")
    monkeypatch.setattr(SS, "REGISTRY", reg)
    monkeypatch.setattr(SS, "_reg", {"mt": None, "val": {}})


def _cands():
    app = FastAPI()
    app.include_router(TU.router)
    return TestClient(app).get("/api/candidates?ep=1").json()["shots"]["ep01-S1"]


def test_ledger_passed_current_take_is_not_old(env, tmp_path, monkeypatch):
    """当前首帧 v3 出于重导之前，但登记表 first passed take=3 → script=current、ok、标签 ok；登记表没 passed → 仍按作废线算 old"""
    _shot(env, [T(3, "image", "2026-11-05T09:34:32")], {"image": 3})
    _registry(tmp_path, monkeypatch, {"first": {"status": "passed", "take": 3}})
    r = _cands()
    assert r["image"]["takes"][0]["script"] == "current" and r["image"]["takes"][0]["ok"] is True
    assert r["status"]["main"] == "ok" and not any(t["kind"] == "old" for t in r["status"]["tags"])
    _registry(tmp_path, monkeypatch, {"first": {"status": "ready"}})
    r = _cands()
    assert r["image"]["takes"][0]["script"] == "old" and r["image"]["takes"][0]["ok"] is False
    assert any(t["kind"] == "old" for t in r["status"]["tags"])


def test_ledger_take_number_must_match(env, tmp_path, monkeypatch):
    _shot(env, [T(3, "image", "2026-11-05T09:34:32")], {"image": 3})
    _registry(tmp_path, monkeypatch, {"first": {"status": "passed", "take": 9}})
    assert _cands()["image"]["takes"][0]["script"] == "old"
    assert SS.ledger_passed("ep01-S1", "image", 3) is False and SS.ledger_passed("ep01-S1", "first") is True


def test_newer_failed_attempt_not_main_label_when_stage_passed(env, tmp_path, monkeypatch):
    """当前尾帧 v9 通过（登记表 passed take=9），之后系统又试了 v10 看图没过 → 不挂“看图没过”；登记表 ready（真在重出）→ 挂"""
    takes = [T(3, "image", "2026-11-06T15:00:00"), T(9, "last", "2026-11-06T15:10:00"), T(10, "last", "2026-11-06T16:00:00", {"ok": False, "blocking": ["Q2"]}, JUDGE_FAIL)]
    _shot(env, takes, {"image": 3, "last": 9})
    _registry(tmp_path, monkeypatch, {"first": {"status": "passed", "take": 3}, "last": {"status": "passed", "take": 9}})
    st = _cands()["status"]
    assert st["main"] == "ok" and not any(t["kind"] == "vqa_fail" for t in st["tags"])
    _registry(tmp_path, monkeypatch, {"first": {"status": "passed", "take": 3}, "last": {"status": "ready", "reason": "首帧换过，尾帧作废"}})
    st = _cands()["status"]
    assert any(t["kind"] == "vqa_fail" and t["stage"] == "尾帧" for t in st["tags"])
