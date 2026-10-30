"""本机 ComfyUI 未启动时：任务挂起等待（comfy_wait.who=offline），启动后继续；/api/render-backend 报告状态。"""
import threading

from ns_api import app as APP


def test_render_backend_reports_unreachable(monkeypatch):
    from ns_render import endpoints as EP
    EP.forget()
    monkeypatch.setattr(APP.LLMC, "render_endpoints", lambda: {"image": {"url": "http://h:1"}})
    monkeypatch.setattr(EP, "_probe_now", lambda url, timeout: {"url": url, "reachable": False, "error": "refused",
                                                                "detail": "连不上：refused"})
    st = APP.render_backend()
    assert st["url"] == "http://h:1" and st["reachable"] is False and st["error"] == "refused"
    EP.forget()


def test_render_backend_and_endpoints_share_one_cached_probe(monkeypatch):
    """F4：/api/render-backend 与 /api/render/endpoints 用同一个探测（8 s 超时、15 s 缓存），结果一致"""
    from ns_render import endpoints as EP
    EP.forget()
    calls = []

    def fake(url, timeout):
        calls.append((url, timeout))
        return {"url": url, "reachable": len(calls) == 1, "detail": "HTTP 200" if len(calls) == 1 else "x"}
    monkeypatch.setattr(EP, "_probe_now", fake)
    monkeypatch.setattr(APP.LLMC, "render_endpoints",
                        lambda: {"image": {"url": "http://h:1", "gpu": 0}, "video": {"url": "http://h:1", "gpu": 3}})
    a = APP.render_backend()
    eps = APP.LLMC.get_render_endpoints()
    assert a["reachable"] is True and all(e["reachable"] is True for e in eps)   # 第 2、3 次读缓存：不会“抖”成不可达
    assert calls == [("http://h:1", EP.PROBE_TIMEOUT_S)] and EP.PROBE_TIMEOUT_S >= 8 and EP.PROBE_TTL_S >= 15
    assert EP.probe("http://h:1")["cached"] is True
    assert EP.probe("http://h:1", ttl=0)["cached"] is False and len(calls) == 2    # 过期后重新探测
    EP.forget()


def test_job_waits_until_comfy_online(monkeypatch):
    calls = {"n": 0}

    def status(url):
        calls["n"] += 1
        return {"url": url, "reachable": calls["n"] >= 3, "error": None if calls["n"] >= 3 else "refused"}

    monkeypatch.setattr("ns_orch.executors.comfy_status", status)
    monkeypatch.setattr(APP, "OFFLINE_RETRY_S", 0)
    seen = []
    real_sleep = APP.time.sleep
    job = {"id": "x", "state": "running"}
    monkeypatch.setattr(APP.time, "sleep", lambda s: (seen.append(dict(job.get("comfy_wait") or {})), real_sleep(0)))
    t = threading.Thread(target=APP._wait_comfy_online, args=(job,))
    t.start()
    t.join(5)
    assert not t.is_alive()
    assert seen and seen[0]["who"] == "offline" and "ComfyUI" in seen[0]["what"]
    assert seen[0]["since"] == seen[-1]["since"]  # 等待起点不随重试变化
    assert "comfy_wait" not in job and job["state"] == "running"
