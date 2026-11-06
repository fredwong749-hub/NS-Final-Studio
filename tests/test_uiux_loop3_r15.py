"""UIUX-LOOP-3 第 15 轮（11-06，Fable 复审 SHIP-WITH-FIXES）：
B1 tools/autopilot/runs._jl_cached：缓存写进字典后又从字典回读，另一线程同时 pop → KeyError；改为用本地元组。
B2 services/api/ns_api/video_index：只登记在登记表、本机没 takes.json 的镜 missing 永远是 [first, last]，
   `elif missing and not cur` 把登记表的 视频 running / ready、首尾帧 passed 全盖成“缺首尾帧 · 去出图”。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent", "services/render", "services/post", "services/render_router", "tools/autopilot"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

RUN = "s_v2"


def test_registry_cache_survives_concurrent_pop(tmp_path, monkeypatch):
    import runs as R
    p = tmp_path / "config/pipeline/runs.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"primary": "a", "runs": {"a": {"priority": 0, "status": "producing"}}}), encoding="utf-8")

    class PoppingDict(dict):
        """模拟另一线程在 set 之后立刻 pop（旧写法在这里 KeyError）"""
        def __setitem__(self, k, v):
            super().__setitem__(k, v)
            super().pop(k, None)
    monkeypatch.setattr(R, "_REG_CACHE", PoppingDict())
    assert R.registry(tmp_path)["primary"] == "a"
    assert R.registry(tmp_path)["runs"]["a"]["status"] == "producing"
    assert R.primary_run(tmp_path) == "a"


@pytest.fixture
def env(tmp_path, monkeypatch):
    from ns_api import frames_index as FI
    from ns_api import shot_status as SS
    from ns_api import video_index as VI
    from ns_render import pipeline as P
    data = tmp_path / "data"
    renders = data / "renders" / RUN
    renders.mkdir(parents=True)
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", renders)
    monkeypatch.setattr(FI, "_script_chars", lambda run=None: {})
    monkeypatch.setattr(FI, "_jobs_by_shot", lambda: {})
    monkeypatch.setattr(FI, "_edits_by_cell", lambda: {})
    monkeypatch.setattr(VI, "_video_jobs", lambda: [])
    monkeypatch.setattr(VI, "_median_s", lambda: 600.0)
    monkeypatch.setattr(SS, "_reviewed", lambda sid, t: None)
    reg = tmp_path / "registry.json"
    monkeypatch.setattr(SS, "REGISTRY", reg)
    SS._reg.update(mt=None, val={})

    def write_reg(shots: dict[str, dict]):
        eps: dict[int, list] = {}
        for sid, objs in shots.items():
            ep = int(sid[2:4])
            eps.setdefault(ep, []).append({"shot": sid, "index": int(sid.split("-S")[1]), "objects": objs})
        reg.write_text(json.dumps({"run": RUN, "episodes": [{"ep": e, "shots": v} for e, v in sorted(eps.items())]}), encoding="utf-8")
        SS._reg.update(mt=None, val={})
    return write_reg


def test_ledger_only_shots_follow_ledger_not_missing_frames(env):
    """本机一个 takes.json 都没有（图 / 片还没同步到），全靠登记表"""
    from ns_api import video_index as VI
    env({
        "ep01-S1": {"first": {"status": "passed", "take": 3}, "last": {"status": "passed", "take": 2}, "video": {"status": "running"}},
        "ep01-S2": {"first": {"status": "passed", "take": 3}, "last": {"status": "passed", "take": 2}, "video": {"status": "ready"}},
        "ep01-S3": {"first": {"status": "passed", "take": 3}, "last": {"status": "passed", "take": 2}, "video": {"status": "pending"}},
        "ep01-S4": {"first": {"status": "passed", "take": 3}, "last": {"status": "passed", "take": 2}, "video": {"status": "failed", "reason": "三次都没过"}},
        "ep01-S5": {"first": {"status": "ready"}, "last": {"status": "pending"}, "video": {"status": "pending"}},
        "ep01-S6": {"first": {"status": "failed", "reason": "x"}, "last": {"status": "pending"}, "video": {"status": "pending"}},
        "ep01-S7": {"video": {"status": "pending"}},
    })
    d = VI.build()
    st = {s["id"]: s for e in d["episodes"] for s in e["shots"]}
    assert st["ep01-S1"]["state"] == "rendering" and st["ep01-S1"]["missing"] == []
    assert st["ep01-S2"]["state"] == "queued" and st["ep01-S2"]["missing"] == []
    assert st["ep01-S3"]["state"] == "todo" and st["ep01-S3"]["missing"] == [] and "等出视频" in st["ep01-S3"]["ledger"]["word"]
    assert st["ep01-S4"]["state"] == "failed" and st["ep01-S4"]["missing"] == []
    # 首帧还在排队 → 等首尾帧（r7 口径不变）
    assert st["ep01-S5"]["state"] == "todo" and st["ep01-S5"]["ledger"]["word"].startswith("等首尾帧") and st["ep01-S5"]["missing"] == ["first", "last"]
    # 首帧没出来（登记表 failed = 系统在重试）→ 先报首帧那格，不是尾帧 pending，也不是“去出图”
    assert st["ep01-S6"]["state"] == "todo" and st["ep01-S6"]["ledger"]["state"] == "failed" and st["ep01-S6"]["ledger"]["word"].startswith("等首尾帧")
    # 登记表里首尾帧对象都没有 → 才是“缺首尾帧 · 去出图”
    assert st["ep01-S7"]["state"] == "need_frames" and st["ep01-S7"]["missing"] == ["first", "last"]
    assert d["summary"]["need_frames"] == 1 and d["summary"]["rendering"] == 1 and d["summary"]["queued"] == 1 and d["summary"]["failed"] == 1
