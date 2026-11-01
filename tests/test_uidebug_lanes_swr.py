"""UIDEBUG（docs/uirsi/debug_wiring.md W-07 / W-08）：展示接口不再因为缓存过期卡几秒到几十秒。

- GET /api/render/lanes（顶栏 / 精修 / 场景页轮询）：探测结果过期 → 先给上次结果、后台刷新；
  提交任务时的选卡（lanes() 默认 / pick_lane）照旧现探，不受影响。
- GET /api/render/image-presets 的 allowed（ComfyUI object_info）：过期不久 → 先给旧值、后台刷新；refresh=true 仍同步现取。
"""
import threading
import time

from ns_api import frame_jobs as FJ
from ns_api import jobs as J
from ns_render import endpoints as EP

URL = "http://127.0.0.1:65530"


def _slow_probe_factory(calls, delay=0.5):
    def fake(url, **kw):
        calls.append(url)
        time.sleep(delay)
        res = {"url": url, "reachable": True, "detail": "HTTP 200 (fresh)"}
        with EP._probe_guard:
            EP._probe_cache[url] = (time.monotonic(), res)
        return {**res, "cached": False}
    return fake


def test_peek_is_read_only(monkeypatch):
    monkeypatch.setattr(EP, "_probe_cache", {})
    assert EP.peek(URL) is None
    EP._probe_cache[URL] = (1.0, {"reachable": True})
    assert EP.peek(URL + "/") == (1.0, {"reachable": True})


def test_view_probe_serves_stale_and_refreshes_in_background(monkeypatch):
    monkeypatch.setattr(J, "reachable_fn", None)
    monkeypatch.setattr(EP, "_probe_cache", {URL: (time.monotonic() - 40, {"url": URL, "reachable": True, "detail": "old"})})
    calls = []
    monkeypatch.setattr(EP, "probe", _slow_probe_factory(calls))
    monkeypatch.setattr(J, "_view_probe_threads", {})
    t0 = time.monotonic()
    r = J._probe_for_view(URL)
    assert time.monotonic() - t0 < 0.3, "展示接口不该等现探"
    assert r["detail"] == "old" and r["cached"] and r["age_s"] >= 39
    th = J._view_probe_threads[URL]
    th.join(3)
    assert calls == [URL] and EP.peek(URL)[1]["detail"] == "HTTP 200 (fresh)"
    # 再取：新鲜结果，且不再起线程
    r2 = J._probe_for_view(URL)
    assert r2["detail"] == "HTTP 200 (fresh)" and calls == [URL]


def test_view_probe_without_cache_waits_briefly_too_old_serves_stale(monkeypatch):
    """IMGPERF（11-01，PAGEWATCH 实测 /api/render/lanes 10–14 s）：从没探过 → 最多等 VIEW_FIRST_WAIT_S；
    旧于 LANES_VIEW_STALE_S 也不再在请求里现探，先回旧值（stale=True）并后台刷新"""
    monkeypatch.setattr(J, "reachable_fn", None)
    monkeypatch.setattr(J, "_view_probe_threads", {})
    calls = []
    monkeypatch.setattr(EP, "probe", _slow_probe_factory(calls, delay=0))
    monkeypatch.setattr(EP, "_probe_cache", {})
    assert J._probe_for_view(URL)["detail"] == "HTTP 200 (fresh)" and calls == [URL]
    monkeypatch.setattr(EP, "_probe_cache", {URL: (time.monotonic() - J.LANES_VIEW_STALE_S - 5, {"detail": "ancient"})})
    r = J._probe_for_view(URL)
    assert r["detail"] == "ancient" and r["stale"] is True
    J._view_probe_threads[URL].join(3)
    assert len(calls) == 2 and J._probe_for_view(URL)["detail"] == "HTTP 200 (fresh)"


def test_view_probe_cold_slow_lane_does_not_block_and_single_flight(monkeypatch):
    """探不通的道（隧道断 / 超时）：请求只等 VIEW_FIRST_WAIT_S；10 个并发请求只起 1 个探测"""
    monkeypatch.setattr(J, "reachable_fn", None)
    monkeypatch.setattr(J, "_view_probe_threads", {})
    monkeypatch.setattr(J, "VIEW_FIRST_WAIT_S", 0.2)
    monkeypatch.setattr(EP, "_probe_cache", {})
    calls = []
    monkeypatch.setattr(EP, "probe", _slow_probe_factory(calls, delay=1.0))
    out = []
    ths = [threading.Thread(target=lambda: out.append(J._probe_for_view(URL))) for _ in range(10)]
    t0 = time.monotonic()
    for t in ths:
        t.start()
    for t in ths:
        t.join(3)
    assert time.monotonic() - t0 < 0.8
    assert len(out) == 10 and all(r.get("probing") for r in out) and calls == [URL]
    J._view_probe_threads[URL].join(3)
    assert J._probe_for_view(URL)["detail"] == "HTTP 200 (fresh)" and calls == [URL]


def test_submission_lanes_still_probe_live(monkeypatch):
    """lanes()（不带 view）= 选卡用：照旧走 _safe_probe，不读展示用的旧值"""
    seen = []
    monkeypatch.setattr(J, "_safe_probe", lambda u: seen.append(("live", u)) or {"reachable": True})
    monkeypatch.setattr(J, "_probe_for_view", lambda u: seen.append(("view", u)) or {"reachable": True})
    monkeypatch.setattr(J, "train_locks", lambda s, wait=True: set())
    J.lanes()
    assert seen and all(k == "live" for k, _ in seen)
    seen.clear()
    J.lanes(view=True)
    assert seen and all(k == "view" for k, _ in seen)


class _FakeClient:
    def __init__(self, gate):
        self.gate = gate
        self.timeout = 300

    def object_info(self):
        self.gate.wait(3)
        return {"LoraLoader": {"input": {"required": {"lora_name": [["new_lora.safetensors"]]}}}}


def test_allowed_serves_stale_then_refreshes(monkeypatch):
    gate = threading.Event()
    monkeypatch.setattr(J, "client_factory", lambda g: _FakeClient(gate))
    old = {"loras": ["old.safetensors"], "gpu": 0}
    monkeypatch.setattr(FJ, "_ALLOWED", {0: (time.time() - FJ.ALLOWED_TTL_S - 30, old)})
    monkeypatch.setattr(FJ, "_allowed_threads", {})
    t0 = time.monotonic()
    r = FJ.lane_allowed(0)
    assert time.monotonic() - t0 < 0.3, "出图参数面板不该等 object_info"
    assert r["source"] == "cache" and r["refreshing"] and r["loras"] == ["old.safetensors"]
    gate.set()
    FJ._allowed_threads[0].join(3)
    assert FJ._ALLOWED[0][1]["loras"] != ["old.safetensors"]
    assert FJ.lane_allowed(0)["source"] == "cache" and "refreshing" not in FJ.lane_allowed(0)


def test_allowed_refresh_true_and_cold_are_synchronous(monkeypatch):
    gate = threading.Event()
    gate.set()
    monkeypatch.setattr(J, "client_factory", lambda g: _FakeClient(gate))
    monkeypatch.setattr(FJ, "_ALLOWED", {})
    assert FJ.lane_allowed(0)["source"] == "live"
    FJ._ALLOWED[0] = (time.time() - FJ.ALLOWED_TTL_S - 30, {"loras": ["x"]})
    assert FJ.lane_allowed(0, refresh=True)["source"] == "live"
    FJ._ALLOWED[0] = (time.time() - FJ.ALLOWED_STALE_S - 30, {"loras": ["x"]})
    assert FJ.lane_allowed(0)["source"] == "live"
