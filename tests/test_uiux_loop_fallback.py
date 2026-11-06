"""UIUX-LOOP r2（11-06）：尾帧兜底（L-204 D8 / L-203 last_frame_fallback i2va）要在出图页 / 视频页看得见、不自相矛盾。
现场：ep01 S4 / S8 / S13 的 takes.json 顶层 last_frame_fallback={mode: i2va, first_n, why}，但出图页尾帧格写“在重出”“新 v8”，
视频页写“缺尾帧 · 去出图补尾帧”——和已经定下的兜底决定打架。全部临时目录。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import frames_index as FI  # noqa: E402
from ns_api import v1_guard as G  # noqa: E402
from ns_api import shot_status as SS
from ns_api import video_index as VI  # noqa: E402
from ns_render import pipeline as P  # noqa: E402

RUN = "series10_v2"
PF_OK = {"ok": True, "items": [{"id": "Q1", "status": "pass"}]}
PF_FAIL = {"ok": False, "blocking": ["FL"], "items": [{"id": "FL", "status": "fail"}]}
FB = {"mode": "i2va", "first_n": 25, "at": "2026-11-06T17:59:23", "by": "producer.gaze_fallback", "rule": "L-204 D8",
      "why": "尾帧 3 次 + 2 轮换种子仍全部看镜头 → 本镜视频退回只给首帧（I2VA）"}


def T(n, stage, pf=None):
    return {"n": n, "stage": stage, "file": f"renders/{RUN}/ep01/S4/takes/{stage}_{n:03d}.png", **({"postflight": pf} if pf else {})}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps({"primary": RUN, "legacy_unprefixed_run": "series10_v1", "runs": {}}), encoding="utf-8")
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders" / RUN)
    monkeypatch.setattr(FI, "_script_chars", lambda run=None: {})
    monkeypatch.setattr(FI, "_ledger_shots", lambda ep=None: [])   # UIUX-LOOP-2 r7：只测目录里的镜，不并活登记表
    monkeypatch.setattr(VI, "_ledger_shots", lambda ep=None: [])
    monkeypatch.setattr(SS, "ledger_cell", lambda sid, st: None)   # 这里只测 takes.json 的兜底口径，不读活登记表
    monkeypatch.setattr(FI, "_jobs_by_shot", lambda: {})
    monkeypatch.setattr(FI, "_edits_by_cell", lambda: {})
    G._cache.clear()
    yield data
    G._cache.clear()


def _shot(data, takes, active, extra=None):
    d = data / "renders" / RUN / "ep01" / "S4"
    (d / "takes").mkdir(parents=True, exist_ok=True)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active, **(extra or {})}), encoding="utf-8")
    for t in takes:
        (data / t["file"]).parent.mkdir(parents=True, exist_ok=True)
        (data / t["file"]).write_bytes(b"x" * 16)
    return d


def _row(ep=1):
    return {x["id"]: x for e in FI.build(ep)["episodes"] for x in e["shots"]}["ep01-S4"]


def test_last_fallback_cell_is_calm_not_missing_or_new(env):
    """兜底生效、没有当前尾帧：state=fallback；不标“新”（哪怕有通过的尾帧版本）、不写“在重出”、不算缺图"""
    _shot(env, [T(25, "image", PF_OK), T(7, "last", PF_FAIL), T(8, "last", PF_OK)], {"image": 25}, {"last_frame_fallback": FB})
    r = _row()
    c = r["last"]
    assert c["state"] == "fallback" and c["new_n"] is None and c["sys_retry"] == 0 and c["pending"] is None
    assert c["fallback"]["mode"] == "i2va" and "只给首帧" in c["fallback"]["word"] and "看镜头" in c["fallback"]["why"]
    assert r["first"]["state"] == "current" and r["first"]["fallback"] is None
    assert FI.build(1)["counts"]["missing"] == 0 and FI.build(1, "missing")["episodes"] == []


def test_fallback_void_when_first_frame_changed(env):
    """首帧换了（first_n 25 ≠ 当前 26）：兜底作废，尾帧格回到正常口径（缺图 / 在重出）"""
    _shot(env, [T(26, "image", PF_OK), T(7, "last", PF_FAIL)], {"image": 26}, {"last_frame_fallback": FB})
    c = _row()["last"]
    assert c["state"] == "none" and c["fallback"] is None and c["sys_retry"] == 1


def test_videos_overview_fallback_shot_is_not_need_frames(env):
    """视频页：兜底镜不是“缺尾帧 · 去出图补”，是等出视频（todo），带 fallback=i2va；首帧真缺时仍是 need_frames"""
    _shot(env, [T(25, "image", PF_OK)], {"image": 25}, {"last_frame_fallback": FB})
    r = {x["id"]: x for e in VI.build(1, jobs=[], median_s=300.0)["episodes"] for x in e["shots"]}["ep01-S4"]
    assert r["state"] == "todo" and r["missing"] == [] and r["fallback"] == "i2va"
    _shot(env, [], {}, {"last_frame_fallback": {"mode": "i2va", "first_n": None}})
    r = {x["id"]: x for e in VI.build(1, jobs=[], median_s=300.0)["episodes"] for x in e["shots"]}["ep01-S4"]
    assert r["state"] == "need_frames" and r["missing"] == ["first"]


def test_last_fallback_parser():
    assert FI.last_fallback({"active": {"image": 25}, "last_frame_fallback": FB})["mode"] == "i2va"
    assert FI.last_fallback({"active": {"image": 3}, "last_frame_fallback": FB}) is None
    assert FI.last_fallback({"active": {}, "last_frame_fallback": {"mode": "i2va"}})["word"].startswith("不用尾帧")
    assert FI.last_fallback({"active": {}}) is None and FI.last_fallback({"last_frame_fallback": {"first_n": 1}}) is None
