"""UIUX-LOOP-3 第 13 轮（11-06）：/api/pipeline/status（顶栏 / 总览 / 成片页 / sop/stepbar 都靠它）20 s 缓存一过期，
那一次请求同步重算 sop_gate.status（活接口实测 3–11 s）→ 过期 ≤ 5 分钟先回旧值、后台单飞刷新；过期更久才同步重算。"""
from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/agent"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))


def _setup(monkeypatch, PS, now_box, calls):
    monkeypatch.setattr(PS, "_registry", lambda: {"primary": "r", "runs": {"r": {}}})
    monkeypatch.setattr(PS, "_now", lambda: now_box[0])

    def slow(run, reg):
        calls.append(run)
        return {"run": run, "n": len(calls)}
    monkeypatch.setattr(PS, "_pipeline_status", slow)
    PS._cache.clear()
    PS._refreshing.clear()


def test_stale_while_revalidate(monkeypatch):
    from ns_api import pipeline_status as PS
    now, calls = [1000.0], []
    _setup(monkeypatch, PS, now, calls)
    first = PS.pipeline_status()
    assert first["n"] == 1 and calls == ["r"]
    now[0] += 5                     # 20 s 内：直接缓存
    assert PS.pipeline_status() is first and len(calls) == 1
    gate = threading.Event()
    real = PS._pipeline_status

    def blocking(run, reg):
        gate.wait(5)
        return real(run, reg)
    monkeypatch.setattr(PS, "_pipeline_status", blocking)
    now[0] += 30                    # 过期（35 s）但 ≤ 5 分钟：立刻回旧值，后台刷
    t = time.perf_counter()
    got = PS.pipeline_status()
    assert got is first and time.perf_counter() - t < 1.0, "过期时不能让这次请求等重算"
    assert PS.pipeline_status() is first and "r" in PS._refreshing, "单飞：第二次过期请求不再起线程"
    gate.set()
    for _ in range(100):
        if PS._cache["r"][1]["n"] == 2:
            break
        time.sleep(0.02)
    assert PS._cache["r"][1]["n"] == 2 and "r" not in PS._refreshing
    assert PS.pipeline_status()["n"] == 2


def test_too_stale_recomputes_inline(monkeypatch):
    from ns_api import pipeline_status as PS
    now, calls = [1000.0], []
    _setup(monkeypatch, PS, now, calls)
    PS.pipeline_status()
    now[0] += PS.STALE_MAX_S + 1    # 过期超过 5 分钟：同步重算，不给太旧的
    assert PS.pipeline_status()["n"] == 2 and len(calls) == 2
