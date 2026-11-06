"""ORPHAN-TAKE（11-06）：项目方“总览 ep01 S5 尾帧 标‘新’却写‘文件不在’，一直出不来”。
根因：v12 在 gpu36:1 借道出好 → producer 重启 → 打分线程丢了（postflight 永远 {state: running, ok: null}）、outbox 没写；
笔记本 takes_scan 并回 takes.json 有 v12、图没有；出图页把它当“新”（没 fail 项 = 通过；_url 不看文件在不在）。
规则（只给看通过的图）：打分没结论 / orphan / 没通过 / 图没拉到的版本一律不算“新”；没图可给时格子写“等打分 / 图在传输中 / 在重出”。
全部临时目录，不碰真实 data。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import frames_index as FI  # noqa: E402
from ns_api import takes_ui as TU  # noqa: E402
from ns_api import v1_guard as G  # noqa: E402
from ns_render import pipeline as P  # noqa: E402

RUN = "series10_v2"
PF_RUN = {"state": "running", "ok": None}
PF_OK = {"ok": True, "items": [{"id": "Q1", "status": "pass"}]}
PF_FAIL = {"ok": False, "blocking": ["Q9"], "items": [{"id": "Q9", "status": "fail", "detail": "看图没过"}]}


def T(n, stage, pf=None, **kw):
    return {"n": n, "stage": stage, "file": f"renders/{RUN}/ep01/S5/takes/{stage}_{n:03d}.png", "producer": {"lane": "gpu36:1"},
            **({"postflight": pf} if pf is not None else {}), **kw}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps(
        {"primary": RUN, "legacy_unprefixed_run": "series10_v1", "runs": {}}), encoding="utf-8")
    renders = data / "renders" / RUN
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", renders)
    monkeypatch.setattr(FI, "_script_chars", lambda run=None: {})
    monkeypatch.setattr(FI, "_jobs_by_shot", lambda: {})
    monkeypatch.setattr(FI, "_edits_by_cell", lambda: {})
    G._cache.clear()
    yield data
    G._cache.clear()


def _shot(data, takes, active, present=()):
    d = data / "renders" / RUN / "ep01" / "S5"
    (d / "takes").mkdir(parents=True, exist_ok=True)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active}), encoding="utf-8")
    for t in takes:
        if t["n"] in present:
            (data / t["file"]).write_bytes(b"x" * 16)


def _last(ep=1):
    return {x["id"]: x for e in FI.build(ep)["episodes"] for x in e["shots"]}["ep01-S5"]["last"]


def test_unscored_take_is_not_new_and_cell_says_waiting_for_score(env):
    """现场：v8 当前（图在）、v12 postflight running（图不在）、v13 Q9 fail（图在）→ 显示当前 v8，不标“新”；pending = v12 等打分"""
    _shot(env, [T(8, "last", PF_OK), T(12, "last", PF_RUN), T(13, "last", PF_FAIL)], {"last": 8}, present=(8, 13))
    c = _last()
    assert c["state"] == "current" and c["n"] == 8 and c["url"].endswith("last_008.png")
    assert c["new_n"] is None and c["new_url"] is None
    assert c["pending"] == {"n": 12, "word": "等打分", "why": "等打分"}
    assert c["sys_retry"] == 1          # v13 没过 = 系统在重出；v12 等打分不算


def test_passing_but_file_missing_is_not_new(env):
    """通过了但原图还没拉到笔记本：不标“新”（否则前端写“文件不在”）；pending = 图在传输中；拉到后才算新"""
    _shot(env, [T(8, "last", PF_OK), T(14, "last", PF_OK)], {"last": 8}, present=(8,))
    c = _last()
    assert c["new_n"] is None and c["pending"] == {"n": 14, "word": "图在传输中", "why": "通过了，原图还没从服务器拉到笔记本"}
    (env / T(14, "last")["file"]).write_bytes(b"x" * 16)
    c = _last()
    assert c["new_n"] == 14 and c["new_url"].endswith("last_014.png") and c["pending"] is None


def test_no_current_only_unscored_cell_is_none_with_pending(env):
    """没有当前版、只有一版在等打分：state=none（前端写“尾帧等打分”，不是“文件不在”）"""
    _shot(env, [T(1, "last", PF_RUN)], {}, present=())
    c = _last()
    assert c["state"] == "none" and c["url"] is None and c["new_n"] is None
    assert c["pending"]["word"] == "等打分" and c["pending"]["n"] == 1


def test_orphan_and_failed_never_shown(env):
    """producer 标了 orphan 的版本和 ok=false 的版本：不算新、不算待，归 sys_retry（系统在重出）"""
    pf_orphan = {"state": "orphan", "ok": False, "reasons": ["打分被进程重启打断"]}
    _shot(env, [T(2, "last", pf_orphan), T(3, "last", {"ok": False, "blocking": ["Q1"]})], {}, present=(2, 3))
    c = _last()
    assert c["state"] == "none" and c["new_n"] is None and c["pending"] is None and c["sys_retry"] == 2
    assert FI.build(1, "new")["episodes"] == []            # “待你看”筛选里没有它


def test_takes_ui_unscored_and_verdict():
    assert TU.unscored({"postflight": PF_RUN}) == "等打分"
    assert TU.unscored({"postflight": {"ok": None, "error": "boom"}}) == "等打分"
    assert "链路" in TU.unscored({"postflight": {"ok": False, "score_infra": True, "items": []}})
    assert "打断" in TU.unscored({"postflight": {"state": "orphan", "ok": False}})
    assert TU.unscored({"postflight": PF_OK}) is None
    assert TU.unscored({}) is None                                   # 没有 postflight 记录（画布 / 手工）照原口径
    assert TU._verdict({"postflight": PF_RUN}, None) == (False, "等打分")
    ok, why = TU._verdict({"postflight": {"ok": False, "blocking": ["Q9"]}}, None)
    assert ok is False and "Q9" in why                                # ok=false 没逐项 fail 也不作候选
    assert TU._verdict({"postflight": PF_OK}, None) == (True, None)
    assert TU._verdict({}, None) == (True, None)


def test_candidates_hide_unscored_for_owner(env):
    """画布 / 总览候选（takes_ui.candidates only_passing）：等打分的版本 ok=false、不给项目方挑；总览 cand_url 据此也不会拿到它"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    _shot(env, [T(12, "last", PF_RUN), T(13, "last", PF_OK)], {}, present=(12, 13))
    app = FastAPI()
    app.include_router(TU.router)
    c = TestClient(app)
    r = c.get("/api/candidates?ep=1").json()["shots"]["ep01-S5"]["last"]
    assert {x["n"]: x["ok"] for x in r["takes"]} == {12: False, 13: True}
    assert next(x for x in r["takes"] if x["n"] == 12)["why_not"] == "等打分"
    r2 = c.get("/api/candidates?ep=1&only_passing=1").json()["shots"]["ep01-S5"]["last"]
    assert [x["n"] for x in r2["takes"]] == [13]
