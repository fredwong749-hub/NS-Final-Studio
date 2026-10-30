"""GPU 实时面板：合并桥 + ssh；锁着但空闲 ≥ 10 分钟告警；GPU2 坏卡；5 秒缓存（全部 mock，不连 gpu3）"""
from ns_api import gpu_monitor as G


def _bridge():
    return [{"id": i, "name": "RTX 3090", "faulty": i == 2, "util": u, "vram_used_mb": v, "vram_total_mb": 24576,
             "processes": [], "busy_by": None, "lend_file": None, "comfy": None,
             "train_lock": {"text": '{"by": "qwen-agent", "job": "LoRA card"}'} if i in (0, 3) else {}}
            for i, (u, v) in enumerate([(0, 400), (98, 21000), (0, 15), (0, 400)])]


def _extra():
    return {"paused": {"2": {"tag": "qwen-agent-paused-for-ep01", "text": "{}"}},
            "gpus": {"1": {"temp_c": 71.0, "power_w": 300.0, "power_limit_w": 350.0}},
            "procs": {"1": [{"pid": 7, "vram_mb": 20000,
                             "cmd": "/x/llama.cpp/build/bin/llama-server -m /m/qwen.gguf --port 8098"}]}}


def test_merge_and_idle_warning(monkeypatch):
    monkeypatch.setattr(G, "_bridge", _bridge)
    monkeypatch.setattr(G, "_ssh", _extra)
    monkeypatch.setattr(G, "_qwen", lambda: {"reachable": True, "running": 1, "queued": 2, "tasks": []})
    G._last_busy.clear()
    d0 = G.collect(now=1000.0)
    g = {x["id"]: x for x in d0["gpus"]}
    assert g[2]["faulty"] and g[1]["busy"] and g[1]["temp_c"] == 71.0
    assert g[2]["paused"] == "为 ep01 预留（已暂停 Qwen，等项目方启动）" and g[0]["paused"] is None
    assert g[1]["processes"][0]["cmd"] == "Qwen LLM (llama-server :8098)"
    assert G._short("/env/python main.py --listen 127.0.0.1 --port 8188 --cache-none") == "ComfyUI :8188"
    assert G._short("/env/aitk/bin/python run.py /cfg.json").startswith("LoRA 训练")
    assert g[0]["train_lock"] == "qwen-agent · LoRA card" and not g[0]["locked_idle"]
    d1 = G.collect(now=1000.0 + G.IDLE_WARN_S + 1)
    g = {x["id"]: x for x in d1["gpus"]}
    assert g[0]["locked_idle"] and g[3]["locked_idle"] and not g[2]["locked_idle"] and not g[1]["locked_idle"]
    assert d1["qwen"]["queued"] == 2 and d1["sources"] == {"bridge": True, "ssh": True, "qwen_mailbox": True}


def test_snapshot_returned_immediately(monkeypatch):
    calls = []
    monkeypatch.setattr(G, "collect", lambda **kw: calls.append(kw) or {"at": "x", "gpus": []})
    monkeypatch.setattr(G, "_loop", lambda: None)          # 不起真线程
    G._state.update(at=0.0, data=None, thread=None)
    a = G.gpus()
    b = G.gpus()
    assert a["gpus"] == [] and "age_s" in b
    assert calls == [{"ssh": False}]                         # 第二次直接用快照；冷启动不等 ssh（封板修复 A-2）


def test_cold_collect_skips_ssh_and_owner_tolerates_non_object(monkeypatch):
    """封板修复：冷启动采集不调 ssh；锁文件是数字 / 字符串 JSON 时不崩；桥返回非列表时不崩"""
    called = []
    monkeypatch.setattr(G, "_ssh", lambda: called.append(1) or None)
    monkeypatch.setattr(G, "_bridge", lambda: {"oops": 1})
    monkeypatch.setattr(G, "_qwen", lambda: {"reachable": False, "running": None, "queued": None, "tasks": []})
    out = G.collect(ssh=False)
    assert called == [] and len(out["gpus"]) == 4 and out["sources"]["ssh"] is False
    assert G._owner("123") == "123" and G._owner('"gpu-x"') == '"gpu-x"'
    assert G._owner('{"by": "a", "job": "b"}') == "a · b"
