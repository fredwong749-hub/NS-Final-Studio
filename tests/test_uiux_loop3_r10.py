"""UIUX-LOOP-3 第 10–11 轮（11-06）：重启后复测发现的两处回归 + runs.json 读太多次。
① /api/frame-queue：r8 的 skipped_fallback 只在 snapshot() 里，路由 frame_queue 没透出（活接口核对不到 S4 / S8 为什么不在队列里）。
② /api/pipeline/status：视频格已按登记表写“视频全部定下 16/16 镜 · 本机已收到 11/16 段”，集级一句话 plain 仍写
   “停在“视频”：视频出了 11/16 镜，其余在排队”——同一屏两个口径 → plain 跟格子同口径。
③ tools/autopilot/runs.registry()：/api/readiness 一次请求读 runs.json 4202 次（7.4 s 里的 5.4 s）→ 按 (mtime_ns, size) 记住，
   文件一换就重读；返回深拷贝（register_run / set_status 就地改再写回，不能改到缓存）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent", "tools/autopilot"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))


def test_frame_queue_route_exposes_skipped_fallback(monkeypatch):
    from ns_api import frame_edit_queue as FEQ
    snap = {"per_shot_s": 60, "lanes": 2, "running": 0, "queued": 1, "stale": None,
            "items": [{"oid": "first:ep02-S1", "shot": "ep02-S1", "ep": 2, "idx": 1, "kind": "first", "state": "queued", "pos": 1, "eta_at": 1.0, "redo": False}],
            "skipped_fallback": ["last:ep01-S4", "last:ep01-S8"]}
    monkeypatch.setattr(FEQ, "snapshot", lambda: snap)
    monkeypatch.setattr(FEQ, "_load", lambda: [])
    out = FEQ.frame_queue()
    assert out["skipped_fallback"] == ["last:ep01-S4", "last:ep01-S8"]
    assert out["items"][0]["oid"] == "first:ep02-S1" and out["queued"] == 1


def test_pipeline_episode_plain_follows_ledger_cell():
    from ns_api import pipeline_status as PS
    rows = [{"stage": st, "ok": True, "why": ""} for st in ("剧本", "导入闸门", "资产就绪", "提示词", "出图", "出图检测", "尾帧")]
    rows += [{"stage": "视频", "ok": False, "why": "11/16 镜有片段；缺 镜7,9,11,12,14"}, {"stage": "整集预览", "ok": False, "why": "等视频"}]
    by = {x["stage"]: x for x in rows}
    cells = PS.fold(rows, 1, {"video_ledger": {"done": 16, "best": 1, "total": 16}})
    assert PS.plain_episode(1, "视频", rows[-2]["why"], by, cells) == "停在“视频”：视频全部定下 16/16 镜（1 镜尽力版等你定） · 本机已收到 11/16 段"
    # 登记表没齐 → 原口径；没给 cells → 原口径（旧调用方不变）
    cells2 = PS.fold(rows, 1, {"video_ledger": {"done": 11, "best": 0, "total": 16}})
    assert PS.plain_episode(1, "视频", rows[-2]["why"], by, cells2) == "停在“视频”：视频出了 11/16 镜，其余在排队"
    assert PS.plain_episode(1, "视频", rows[-2]["why"], by) == "停在“视频”：视频出了 11/16 镜，其余在排队"
    # 不是停在视频 → 不动
    assert PS.plain_episode(1, "尾帧", "x", by, cells).startswith("停在“尾帧”：")


def test_runs_registry_cached_by_mtime_and_returns_copy(tmp_path, monkeypatch):
    import runs as R
    p = tmp_path / "config/pipeline/runs.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"primary": "a", "runs": {"a": {"priority": 0, "status": "producing"}}}), encoding="utf-8")
    reads = {"n": 0}
    real = R._jl

    def counting(path, d=None):
        reads["n"] += 1
        return real(path, d)
    monkeypatch.setattr(R, "_jl", counting)
    R._REG_CACHE.clear()
    d1 = R.registry(tmp_path)
    for _ in range(50):
        assert R.registry(tmp_path)["primary"] == "a"
    assert reads["n"] == 1, "同一份文件 51 次只解析 1 次"
    # 拿到的是拷贝：就地改不影响下一次读
    d1["runs"]["a"]["status"] = "paused"
    assert R.registry(tmp_path)["runs"]["a"]["status"] == "producing"
    # 文件换了（register_run 走 _js 原子写）→ 重读
    R.register_run("b", root=tmp_path)
    d3 = R.registry(tmp_path)
    assert "b" in d3["runs"] and d3["runs"]["b"]["status"] == "preparing"
    assert reads["n"] >= 2
    # 文件没了 → 不认旧缓存，走回退
    p.unlink()
    assert R.registry(tmp_path)["primary"] == R.DEFAULT_PRIMARY
