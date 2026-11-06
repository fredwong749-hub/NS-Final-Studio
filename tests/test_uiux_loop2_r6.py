"""UIUX-LOOP-2 第 6 轮（11-06）：慢接口根因 + 时间口径 + 大脑面板。
① /api/factory/health 60 s+ 不回：钩子 _factory_status 每次请求对两台机器 ssh（sync.status，timeout 60 × 4 次重试），结果还被丢掉；
   现在请求路径不许连机器：只认 sync.health_status()，没有就本地拼；status() 永不被调。
② 看图卡探针并行 + 过期回旧值后台刷（stale-while-revalidate）。
③ takes_ui._run_legacy 按 (钉剧环境变量, runs.json / run.json 改动时间) 记住，换了立即失效。
④ ns_api.clock：笔记本裸美东串 → JST；出图机写的裸串已是 JST（TZ=Asia/Tokyo）原样。
⑤ GET /api/brain/status：决定 / 给项目方的话 / 快照摘要 / STATUS.md 全文，缺哪份写进 missing。
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_factory_health_never_calls_sync_status(tmp_path, monkeypatch):
    from ns_api import factory_health as F
    mod = tmp_path / "sync.py"
    mod.write_text("def status():\n    raise RuntimeError('ssh not allowed in request thread')\n", encoding="utf-8")
    monkeypatch.setattr(F, "FACTORY", mod)
    F._fs_mod.update(mt=None, fn=None)
    assert F._factory_status() is None            # 没有 health_status → 本地拼法
    assert F._fs_mod["fn"] is None
    mod.write_text("def status():\n    raise RuntimeError('x')\n\ndef health_status():\n"
                   "    return {'lanes': [], 'vqa': [], 'phases': [], 'producer': {'state': 'busy', 'text': 'running'}}\n", encoding="utf-8")
    os.utime(mod, (time.time() + 5, time.time() + 5))
    F._fs_mod.update(mt=None, fn=None)
    out = F._factory_status()
    assert out is not None and out["lanes"] == []
    fn = F._fs_mod["fn"]
    F._factory_status()
    assert F._fs_mod["fn"] is fn                  # 模块按 mtime 只加载一次
    src = (ROOT / "services/api/ns_api/factory_health.py").read_text(encoding="utf-8")
    assert 'getattr(mod, "status"' not in src and 'getattr(mod, "health_status"' in src


def test_vqa_stale_while_revalidate(monkeypatch):
    from ns_api import factory_health as F
    calls = []

    def fake_probe():
        calls.append(time.time())
        return [{"id": "laptop", "state": "idle"}, {"id": "gpu36", "state": "down"}]
    monkeypatch.setattr(F, "_vqa_probe", fake_probe)
    F._cache.update(t=0.0, vqa=None, thread=None)
    t0 = time.time()
    assert F._vqa(t0)[0]["id"] == "laptop" and len(calls) == 1        # 第一次：同步探
    assert F._vqa(t0 + 1)[1]["state"] == "down" and len(calls) == 1   # 5 s 内：直接用
    r = F._vqa(t0 + 100)                                               # 过期：先回旧值，后台刷
    assert r[0]["id"] == "laptop"
    th = F._cache.get("thread")
    if th is not None:
        th.join(5)
    assert len(calls) == 2
    F._cache.update(t=0.0, vqa=None, thread=None)


def test_vqa_probe_parallel(monkeypatch):
    from ns_api import factory_health as F
    monkeypatch.setattr(F, "_vqa_probe_one", lambda vid, label, url: (time.sleep(0.3), {"id": vid, "state": "down"})[1])
    t = time.time()
    out = F._vqa_probe()
    assert len(out) == 2 and time.time() - t < 0.55     # 两张卡并行：不是 0.3 × 2


def test_run_legacy_cached_and_invalidated(monkeypatch):
    from ns_api import takes_ui as T
    T._run_cache.update(key=None, val=None)
    monkeypatch.setenv("NS_PRIMARY_RUN", "series10_v1")
    assert T._run_legacy() == ("series10_v1", True)
    k1 = T._run_cache["key"]
    T._run_legacy()
    assert T._run_cache["key"] == k1          # 第二次命中
    monkeypatch.setenv("NS_PRIMARY_RUN", "series10_v2")
    assert T._run_legacy()[0] == "series10_v2" and T._run_cache["key"] != k1   # 换钉剧立刻失效
    T._run_cache.update(key=None, val=None)


def test_clock_local_naive_to_jst_and_server_passthrough():
    from ns_api import clock as CK
    from ns_api import frame_edit_queue as FEQ
    s = "2026-11-06T04:49:28"
    want = datetime.fromisoformat(s).astimezone(timezone(timedelta(hours=9))).strftime("%Y-%m-%dT%H:%M:%S")
    assert CK.local_naive_to_jst(s) == want
    assert CK.local_naive_to_jst(s, with_offset=True) == want + "+09:00"
    assert CK.local_naive_to_jst("2026-11-06T05:49:28+00:00") == "2026-11-06T14:49:28"   # 带时区的按自带时区
    assert CK.local_naive_to_jst(None) is None and CK.local_naive_to_jst("not-a-time") == "not-a-time"
    assert CK.server_naive_jst("2026-11-06T16:37:03") == "2026-11-06T16:37:03"
    assert CK.server_naive_jst("2026-11-06T16:37:03", with_offset=True) == "2026-11-06T16:37:03+09:00"
    assert FEQ.to_jst(s) == want                 # 修改记录 at 走同一口径


def test_frames_index_gen_times_are_jst_with_offset(monkeypatch):
    from ns_api import frames_index as FI
    from ns_api import jobs as J
    from ns_api.clock import local_naive_to_jst
    monkeypatch.setattr(J, "all_jobs", lambda: [{"state": "queued", "shot_id": "ep01-S2", "stage": "last", "id": "j1",
                                                 "created_at": "2026-11-06T04:49:28", "started_at": None}])
    g = FI._jobs_by_shot()[("ep01-S2", "last")]
    assert g["created_at"].endswith("+09:00") and g["started_at"] is None
    assert g["created_at"] == local_naive_to_jst("2026-11-06T04:49:28", with_offset=True)


def test_brain_status_build(tmp_path):
    from ns_api import brain_status as B
    out = B.build(tmp_path)
    assert out["decisions"] == [] and out["notes"] == [] and out["snapshot"] is None and out["status_md"] is None
    assert set(out["missing"]) >= {"brain.json", "decisions.jsonl", "owner_notes.md", "snapshot.json", "STATUS.md"}
    assert "常驻关着" in out["mode"]["word"]
    b = tmp_path / "data" / "brain"
    b.mkdir(parents=True)
    (tmp_path / "config" / "brain").mkdir(parents=True)
    (tmp_path / "config" / "brain" / "brain.json").write_text(json.dumps({"enabled": True, "dry_run": True, "model": "m", "interval_s": 180}), encoding="utf-8")
    (b / "decisions.jsonl").write_text(
        json.dumps({"at": "2026-11-06 17:36:11+09:00", "kind": "no_action", "params": {"reason": "selftest", "expected_effect": "one more line"}, "dry": True, "result": "dry-run"}) + "\n"
        + json.dumps({"at": "2026-11-06 18:00:00+09:00", "kind": "note_to_owner", "params": {"reason": "milestone"}, "dry": False, "result": "noted"}) + "\nhalf-line", encoding="utf-8")
    (b / "owner_notes.md").write_text("11-06 18:00 🟢 BRAIN：ep01 首尾帧全定下了\n11-06 18:10 🔴 BRAIN：gpu36 探不到\n", encoding="utf-8")
    (b / "snapshot.json").write_text(json.dumps({"at": "2026-11-06 18:52:21+09:00", "t": time.time() - 30, "run": "r", "probe_errors": ["gpu36"],
                                                 "issues_open": [1, 2], "idle_watch": {"idle": ["gpu33:1"]}}), encoding="utf-8")
    (b / "STATUS.md").write_text("# BRAIN status\n", encoding="utf-8")
    out = B.build(tmp_path)
    assert out["missing"] == []
    assert out["mode"]["word"] == "API 常驻 · 只记不做"
    assert [d["kind"] for d in out["decisions"]] == ["note_to_owner", "no_action"]     # 最新在前，坏行跳过
    assert out["decisions"][1]["reason"] == "selftest" and out["decisions"][1]["dry"] is True
    assert out["notes"][0] == {"at": "11-06 18:10", "level": "red", "text": "gpu36 探不到"}
    assert out["snapshot"]["probe_errors"] == ["gpu36"] and out["snapshot"]["issues_open"] == 2 and out["snapshot"]["idle_lanes"] == ["gpu33:1"]
    assert 25 <= out["snapshot"]["age_s"] <= 40 and out["status_md"].startswith("# BRAIN")


def test_brain_route_registered_and_panel_mounted():
    from fastapi.testclient import TestClient
    from ns_api.app import app
    r = TestClient(app).get("/api/brain/status")
    assert r.status_code == 200 and "mode" in r.json() and "decisions" in r.json()
    sp = (ROOT / "apps/web/src/v3/pages/SeasonPage.tsx").read_text(encoding="utf-8")
    assert "<BrainPanel />" in sp and "<EpisodeKpiPanel />" in sp
    bp = (ROOT / "apps/web/src/v3/BrainPanel.tsx").read_text(encoding="utf-8")
    assert "/api/brain/status" in bp and "大脑在想什么" in bp
