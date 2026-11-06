"""UIUX-LOOP-2 第 8 轮（11-06）：修改队列 / 进度条与大脑决定、登记表打架。
① /api/frame-queue：ep01-S4 尾帧“排第 1”，而大脑 17:49 已给 S4 / S8 写 I2VA 兜底（takes.json last_frame_fallback，没有当前尾帧）
   → 兜底镜的尾帧对象不进队列（skipped_fallback 带出），有当前尾帧的（首帧换过要重出，S9）照常排。
② /api/pipeline/status 视频格：sop_gate 只认本机 clips 目录 → “视频出了 11/16 镜，其余在排队”；登记表 16/16 已定下
   → 显示层按登记表写“视频全部定下 16/16 镜（1 镜尽力版等你定） · 本机已收到 11/16 段”，闸门判定（state=doing）不动。
"""
from __future__ import annotations

import json


def test_queue_skips_fallback_last_frames(tmp_path, monkeypatch):
    from ns_api import frame_edit_queue as FEQ
    reg = tmp_path / "registry.json"
    shots = []
    for i, (last_status, fb, cur_last) in enumerate([("ready", True, None), ("ready", True, 3), ("ready", False, None), ("running", True, None)], start=1):
        shots.append({"shot": f"ep01-S{i}", "index": i, "objects": {"first": {"id": f"first:ep01-S{i}", "status": "passed"},
                                                                        "last": {"id": f"last:ep01-S{i}", "status": last_status}}})
    reg.write_text(json.dumps({"episodes": [{"ep": 1, "shots": shots}]}), encoding="utf-8")
    monkeypatch.setattr(FEQ, "_registry_path", lambda: reg)
    FEQ._reg.update(mt=None, val=[])
    takes = {
        "ep01-S1": {"active": {"image": 25}, "last_frame_fallback": {"mode": "i2va", "first_n": 25}},      # 兜底、没当前尾帧 → 不排
        "ep01-S2": {"active": {"image": 22, "last": 3}, "last_frame_fallback": {"mode": "i2va", "first_n": 22}},   # 有当前尾帧（登记表要重出）→ 照常排
        "ep01-S3": {"active": {"image": 1}},                                                                # 没兜底 → 照常排
        "ep01-S4": {"active": {"image": 9}, "last_frame_fallback": {"mode": "i2va", "first_n": 9}},        # 兜底、登记表 running → 也不进队列
    }
    monkeypatch.setattr(FEQ, "_takes", lambda shot: takes[shot])
    monkeypatch.setattr(FEQ, "eta_table", lambda: None)
    monkeypatch.setattr(FEQ, "lanes", lambda: 2)
    s = FEQ.snapshot()
    assert s["skipped_fallback"] == ["last:ep01-S1", "last:ep01-S4"]
    assert [i["oid"] for i in s["items"]] == ["last:ep01-S2", "last:ep01-S3"] and s["queued"] == 2 and s["running"] == 0
    assert FEQ.position_of("last:ep01-S1", s) is None


def test_pipeline_video_cell_uses_ledger_when_gate_lags():
    from ns_api import pipeline_status as PS
    rows = [{"stage": st, "ok": True, "why": ""} for st in ("剧本", "导入闸门", "资产就绪", "提示词", "出图", "出图检测", "尾帧")]
    rows += [{"stage": "视频", "ok": False, "why": "11/16 镜有片段；缺 镜7,9,11,12,14"}, {"stage": "整集预览", "ok": False, "why": "等视频"}]
    cells = PS.fold(rows, 1, {"video_ledger": {"done": 16, "best": 1, "total": 16}})
    assert cells["video"]["state"] == "doing"
    assert cells["video"]["plain"] == "视频全部定下 16/16 镜（1 镜尽力版等你定） · 本机已收到 11/16 段"
    # 登记表没齐 → 原文口径不变
    cells = PS.fold(rows, 1, {"video_ledger": {"done": 11, "best": 0, "total": 16}})
    assert cells["video"]["plain"] == "视频出了 11/16 镜，其余在排队"
    cells = PS.fold(rows, 1, None)
    assert cells["video"]["plain"] == "视频出了 11/16 镜，其余在排队"


def test_video_ledger_counts_from_registry(monkeypatch):
    from ns_api import pipeline_status as PS
    from ns_api import shot_status as SS
    monkeypatch.setattr(SS, "_registry", lambda: {"ep01-S1": {"video": {"status": "passed"}}, "ep01-S2": {"video": {"status": "best_effort"}},
                                                  "ep01-S3": {"video": {"status": "ready"}}, "ep02-S1": {"video": {"status": "passed"}}})
    assert PS._video_ledger(1) == {"done": 2, "best": 1, "total": 3}
    assert PS._video_ledger(3) is None


def test_kpi_marks_start_before_import(tmp_path):
    """r9 → L-212 #9：首派早于本版剧本导入 → 计时从导入重新算（clock_from=import，start_before_import=True）；导入更早 → 按首派"""
    from ns_api import episode_kpi as K
    now = 1_800_000_000.0
    reg = {"run": "r", "episodes": [{"ep": 1, "title": "一", "shots": [{"shot": "ep01-S1", "index": 1, "objects": {"first": {"status": "passed"}}}]}]}
    snap = {"t": now - 10, "kpi": {"1": {"start": "11-03 21:47", "elapsed_min": 4000.0}}}
    out = K.build(registry=reg, renders=tmp_path, snapshot=snap, local_starts={}, now=now, url=lambda r: None, vurl=lambda r: None,
                  imports={"1": now - 300 * 60})
    e = out["episodes"][0]
    assert e["start_before_import"] is True and e["import_at"] is not None and e["elapsed_min"] == 300.0 and e["clock_from"] == "import"
    out = K.build(registry=reg, renders=tmp_path, snapshot=snap, local_starts={}, now=now, url=lambda r: None, vurl=lambda r: None,
                  imports={"1": now - 5000 * 60})
    assert out["episodes"][0]["start_before_import"] is False and out["episodes"][0]["elapsed_min"] == 4000.0
    out = K.build(registry=reg, renders=tmp_path, snapshot=snap, local_starts={}, now=now, url=lambda r: None, vurl=lambda r: None)
    assert out["episodes"][0]["start_before_import"] is False and out["episodes"][0]["import_at"] is None
