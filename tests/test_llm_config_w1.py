"""v1 收尾 W1：统一模型与 API 配置（契约 §A）+ 剧本创作扩展（契约 §B）。
写作模型一律用假 urlopen；密钥只用占位串，断言任何接口都不回传。合成占位剧本，不是剧情文本。"""
import importlib.util
import io
import json
import urllib.error
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_api import llm_config as LC
from ns_api import script_chat as S
from ns_api import script_inbox as SI
from ns_api.app import app

ROOT = Path(__file__).resolve().parents[1]
c = TestClient(app)
SECRET = "sk-W1-SECRET-123"

EP = """## ep03《测试集》

**剧情**：占位

**镜1｜img**：中景，林晚
**motion**：lnwan01，static camera，她抬眼——她看向镜头
**时长**：5秒
"""


class FakeResp(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


def sse(text):
    lines = [{"choices": [{"delta": {"content": text}}]},
             {"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"completion_tokens": 3}}]
    return FakeResp(("".join(f"data: {json.dumps(x, ensure_ascii=False)}\n\n" for x in lines)
                     + "data: [DONE]\n\n").encode("utf-8"))


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    for k in ("ABLITERATION_API_KEY", "DEEPSEEK_API_KEY", "MINIMAX_API_KEY", "NS_BOOST_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(LC, "REPO", tmp_path)                       # 旧 key_files 不读到真实密钥
    monkeypatch.setattr(LC, "PROVIDERS_FILE", tmp_path / "config" / "llm_providers.json")
    monkeypatch.setattr(LC, "LOCAL_FILE", tmp_path / "config" / "llm_providers.local.json")
    monkeypatch.setattr(LC, "RENDER_FILE", tmp_path / "config" / "render_endpoints.json")
    monkeypatch.setattr(S, "count_tokens", lambda text, cfg=None: len(text))
    monkeypatch.setattr(LC, "_price_cache", {})
    monkeypatch.setattr(LC, "_fetch_models", lambda rv: [])               # 不连 /models
    data = tmp_path / "data"
    monkeypatch.setattr(S, "STORE", data / "script_chat")
    monkeypatch.setattr(SI, "REPO", tmp_path)
    monkeypatch.setattr(SI, "DATA", data)
    monkeypatch.setattr(SI, "CACHE", data / "import" / "cache.json")
    monkeypatch.setattr(SI, "IMPORT_JSON", data / "import" / "script_v2.json")
    monkeypatch.setattr(SI, "LOG", data / "import" / "import_log.jsonl")
    return tmp_path


def test_tracked_config_defaults_and_no_keys():
    real = json.loads((ROOT / "config" / "llm_providers.json").read_text(encoding="utf-8"))
    assert real["purposes"]["script_write"] == {"provider": "abliteration", "model": "abliterated-model-large-flash"}
    assert set(real["providers"]) >= {"abliteration", "deepseek", "minimax"} and "qwen" not in real["providers"]
    assert not any("api_key" in v for v in real["providers"].values())
    assert "*.local.json" in (ROOT / ".gitignore").read_text(encoding="utf-8")


def test_get_put_providers_never_leaks_key(cfg):
    r = c.get("/api/llm/providers").json()
    ab = next(p for p in r["providers"] if p["id"] == "abliteration")
    assert ab["default_model"] == "abliterated-model-large-flash" and ab["has_key"] is False
    assert {p["id"] for p in r["purposes"]} == set(LC.PURPOSES)
    assert all(not p["has_key"] for p in r["providers"])
    r = c.put("/api/llm/providers/deepseek", json={"api_key": SECRET, "params": {"temperature": 0.3}, "timeout_s": 99})
    assert r.status_code == 200 and SECRET not in r.text and r.json()["has_key"] is True
    assert r.json()["params"]["temperature"] == 0.3 and r.json()["timeout_s"] == 99
    assert SECRET not in LC.PROVIDERS_FILE.read_text(encoding="utf-8")            # 主文件不含密钥
    assert json.loads(LC.LOCAL_FILE.read_text(encoding="utf-8"))["providers"]["deepseek"]["api_key"] == SECRET
    full = c.get("/api/llm/providers")
    assert SECRET not in full.text and next(p for p in full.json()["providers"] if p["id"] == "deepseek")["has_key"]
    c.put("/api/llm/providers/deepseek", json={"api_key": ""})                     # 空串 = 删除
    assert not next(p for p in c.get("/api/llm/providers").json()["providers"] if p["id"] == "deepseek")["has_key"]


def test_key_sources_env_and_legacy_file(cfg, monkeypatch):
    (cfg / "config").mkdir(parents=True, exist_ok=True)
    (cfg / "config" / "abliteration.local.json").write_text(json.dumps({"api_key": "legacy"}), encoding="utf-8")
    assert LC.api_key("abliteration") == "legacy"
    monkeypatch.setenv("ABLITERATION_API_KEY", "env")
    assert LC.api_key("abliteration") == "env"


def test_purposes(cfg):
    r = c.put("/api/llm/purposes/script_repair", json={"provider": "minimax"})
    assert r.status_code == 200 and r.json()["model"] == "MiniMax-M3.1-Flash"
    assert c.put("/api/llm/purposes/nope", json={"provider": "minimax"}).status_code == 400
    assert c.put("/api/llm/purposes/script_write", json={"provider": "nope"}).status_code == 400
    p = {x["id"]: x for x in c.get("/api/llm/providers").json()["purposes"]}
    assert p["script_repair"]["provider"] == "minimax" and p["script_write"]["provider"] == "abliteration"
    assert LC.resolve("script_repair")["model"] == "MiniMax-M3.1-Flash"
    assert c.get("/api/llm/purposes").json() == c.get("/api/llm/providers").json()["purposes"]
    assert LC.resolve("script_repair", {"provider": "deepseek"})["model"] == "deepseek-flash"   # 换家用该家默认


def test_provider_test_endpoint(cfg, monkeypatch):
    c.put("/api/llm/providers/abliteration", json={"api_key": SECRET})
    seen = {}

    def fake(req, timeout=0):
        seen["url"], seen["auth"], seen["body"] = req.full_url, req.headers.get("Authorization"), json.loads(req.data)
        return FakeResp(json.dumps({"choices": [{"message": {"content": "pong"}, "finish_reason": "stop"}],
                                    "usage": {"total_tokens": 5}}).encode())
    monkeypatch.setattr(LC.urllib.request, "urlopen", fake)
    r = c.post("/api/llm/providers/abliteration/test").json()
    assert r["ok"] is True and "latency_ms" in r and SECRET not in json.dumps(r)
    assert seen["url"] == "https://api.abliteration.ai/v1/chat/completions" and seen["auth"] == f"Bearer {SECRET}"
    assert seen["body"]["model"] == "abliterated-model-large-flash" and seen["body"]["max_tokens"] == 16

    def deny(req, timeout=0):
        raise urllib.error.HTTPError(req.full_url, 401, "x", {}, io.BytesIO(f"bad key {SECRET}".encode()))
    monkeypatch.setattr(LC.urllib.request, "urlopen", deny)
    r = c.post("/api/llm/providers/abliteration/test").json()
    assert r["ok"] is False and "401" in r["detail"] and SECRET not in r["detail"]       # 回显的密钥被遮盖
    assert c.post("/api/llm/providers/minimax/test").json()["ok"] is False               # 没 key：不发请求
    assert c.post("/api/llm/providers/nope/test").status_code == 404


def _chat(sid, body=None):
    r = c.post(f"/api/script-chat/sessions/{sid}/chat", json=body or {})
    return [json.loads(x[6:]) for x in r.text.splitlines() if x.startswith("data: ")]


def test_outline_session_and_provider_switch(cfg, monkeypatch):
    c.put("/api/llm/providers/abliteration", json={"api_key": SECRET})
    c.put("/api/llm/providers/deepseek", json={"api_key": "sk-ds"})
    seen = []

    def fake(req, timeout=0):
        seen.append((req.full_url, json.loads(req.data)))
        return sse(EP)
    monkeypatch.setattr(S.urllib.request, "urlopen", fake)
    monkeypatch.setattr(S, "validate_draft", lambda s, n=None: None)
    assert c.post("/api/script-chat/sessions", json={"outline": "x", "episodes": [3, 1]}).status_code == 400
    assert c.post("/api/script-chat/sessions", json={"outline": "x", "rules": "rules_v9"}).status_code == 400
    s = c.post("/api/script-chat/sessions", json={"outline": "提纲第一行\n第二行", "episodes": [3, 3],
                                                  "shots_per_ep": 8, "seconds_per_shot": 10, "rules": "rules_v2"}).json()
    assert s["episode_range"] == [3, 3] and "提纲第一行\n第二行" in s["pending"] and "ep03" in s["pending"]
    ev = _chat(s["id"])                                   # content 为空 → 发提纲首条请求
    assert ev[-1]["t"] == "done" and ev[-1]["episodes"] == [3]
    url, body = seen[-1]
    assert url == "https://api.abliteration.ai/v1/chat/completions" and body["model"] == "abliterated-model-large-flash"
    assert body["messages"][-1]["content"] == s["pending"]
    ev = _chat(s["id"], {"content": "再写一遍", "llm": {"provider": "deepseek", "params": {"temperature": 0.2}}})
    url, body = seen[-1]
    assert url == "https://api.deepseek.com/chat/completions" and body["model"] == "deepseek-flash"
    assert body["temperature"] == 0.2
    got = S.load_session(s["id"])
    assert "pending" not in got and got["messages"][-1]["provider"] == "deepseek"
    assert SECRET not in json.dumps(got)
    # 会话建立时带 llm：之后每次 chat 都用它
    s2 = c.post("/api/script-chat/sessions", json={"outline": "y", "llm": {"provider": "deepseek",
                                                                           "model": "deepseek-v4-pro"}}).json()
    _chat(s2["id"])
    assert seen[-1][1]["model"] == "deepseek-v4-pro"


def test_ab_creates_two_sessions(cfg):
    r = c.post("/api/script-chat/ab", json={"outline": "提纲", "episodes": [1, 2],
                                            "llm_a": {"provider": "abliteration"},
                                            "llm_b": {"provider": "minimax", "model": "MiniMax-M3"}})
    assert r.status_code == 200
    a, b = S.load_session(r.json()["a"]), S.load_session(r.json()["b"])
    assert a["llm"] == {"provider": "abliteration"} and b["llm"]["model"] == "MiniMax-M3"
    assert a["ab"]["group"] == b["ab"]["group"] and a["pending"] == b["pending"]
    assert c.post("/api/script-chat/ab", json={"outline": "x", "llm_a": {}, "llm_b": {"provider": "minimax"}}
                  ).status_code == 400
    assert c.post("/api/script-chat/ab", json={"outline": "x", "llm_a": {"provider": "nope"},
                                               "llm_b": {"provider": "minimax"}}).status_code == 400


def test_to_inbox_registers_candidate(cfg, monkeypatch):
    monkeypatch.setattr(SI, "validate", lambda p: {"sha256": SI._sha(p), "ok": True, "blocking": 0})
    s = S.new_session()
    assert c.post(f"/api/script-chat/sessions/{s['id']}/to-inbox").status_code == 400   # 还没有整集
    S.update_session(s["id"], lambda cur: cur["episodes"].__setitem__("3", EP.strip()))
    r = c.post(f"/api/script-chat/sessions/{s['id']}/to-inbox")
    assert r.status_code == 200 and r.json()["candidate"] is True
    path = r.json()["path"]
    assert path == f"data/script_chat/{s['id']}/script.md" and r.json()["episodes"] == [3]
    inbox = c.get("/api/script-inbox").json()["candidates"]
    assert any(x["path"] == path and x["source"] == "script-chat" for x in inbox)
    assert S.load_session(s["id"])["inbox"]["path"] == path


def test_render_endpoints(cfg, monkeypatch):
    monkeypatch.setattr(LC, "_probe", lambda url: (url.endswith("18188"), "ok" if url.endswith("18188") else "连不上"))
    # G36：image / video 两行之后是各渲染道（kind="lane"），这里只看旧的两行
    r = {x["id"]: x for x in c.get("/api/render/endpoints").json() if x.get("kind") != "lane"}
    assert set(r) == {"image", "video"} and r["video"]["url"].endswith("18191") and r["video"]["gpu"] == 3
    r = c.put("/api/render/endpoints/video", json={"url": "http://127.0.0.1:18188/"})
    assert r.status_code == 200 and r.json()["reachable"] is True
    assert json.loads(LC.RENDER_FILE.read_text(encoding="utf-8"))["video"]["url"] == "http://127.0.0.1:18188"
    assert c.put("/api/render/endpoints/x", json={"url": "http://a"}).status_code == 404
    assert c.put("/api/render/endpoints/image", json={"url": "ftp://a"}).status_code == 400


def test_boost_reads_unified_config(cfg, monkeypatch):
    import ns_api.app as APP
    monkeypatch.setattr(APP, "BOOST_LLM_CONFIG", cfg / "config" / "director_boost_llm.json")
    c.put("/api/llm/providers/minimax", json={"api_key": SECRET})
    c.put("/api/llm/purposes/director_boost", json={"provider": "minimax"})
    st = c.get("/api/boost/config").json()
    assert st["provider"] == "minimax" and st["model"] == "MiniMax-M3.1-Flash" and st["api_key"] == "已配置"
    assert SECRET not in json.dumps(st)
    assert APP.load_boost_config({"provider": "deepseek"})["base_url"] == "https://api.deepseek.com"


def test_repair_loop_reads_unified_config(cfg, monkeypatch):
    spec = importlib.util.spec_from_file_location("qrl_w1", ROOT / "tools" / "qwen_repair_loop.py")
    R = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(R)
    c.put("/api/llm/providers/abliteration", json={"api_key": SECRET})
    a = R.Abliteration(False, 0.3, 10)
    assert a.model == "abliterated-model-large-flash" and a.key == SECRET
    b = R.Abliteration(False, 0.3, 10, llm={"provider": "abliteration", "model": "abliterated-model-large-v2"})
    assert b.model == "abliterated-model-large-v2"
    with pytest.raises(RuntimeError):
        R.Abliteration(False, 0.3, 10, llm={"provider": "minimax"})     # 没 key 直接报错
    assert R.build_args(["x.md", "--out", "y.md"]).backend == "llm"


# ------------------------------------------------------------------ fredw-92 追加：费用档 / 推理开关 / 校验分列 / 出图地址

def test_pricing_and_estimate(cfg, monkeypatch):
    monkeypatch.setattr(LC, "_fetch_models", lambda rv: [
        {"id": "abliterated-model-large-flash", "pricing": {"prompt": "0.000001", "completion": "0.000002"}}])
    r = c.get("/api/llm/providers", params={"prompt_tokens": 10000}).json()
    ab = next(p for p in r["providers"] if p["id"] == "abliteration")
    assert ab["pricing"]["abliterated-model-large-flash"] == {"prompt_per_m": 1.0, "completion_per_m": 2.0,
                                                               "currency": "USD"}
    assert ab["pricing"]["abliterated-model-large-v2"] is None
    assert ab["estimate"]["upper_usd"] == pytest.approx(0.01 + 32000 * 2e-6) and ab["estimate"]["tier"] == "中"
    ds = next(p for p in r["providers"] if p["id"] == "deepseek")
    assert ds["estimate"]["tier"] == "未知" and ds["estimate"]["upper_usd"] is None   # 拿不到单价 = 未知
    e = c.post("/api/script-chat/estimate", json={"outline": "提纲", "episodes": [1, 1]}).json()
    assert e["provider"] == "abliteration" and e["prompt_tokens"] > 0 and e["upper_usd"] > 0
    e2 = c.post("/api/script-chat/estimate", json={"outline": "提纲", "llm": {"provider": "minimax"}}).json()
    assert e2["tier"] == "未知" and e2["label"].startswith("未知")


def test_reasoning_toggle(cfg):
    rv = LC.resolve(None, {"provider": "abliteration", "params": {"reasoning": False}})
    assert LC.request_body(rv, [], False)["reasoning_effort"] == "none" and rv["reasoning_note"] is None
    rv = LC.resolve(None, {"provider": "abliteration", "model": "abliterated-model-large-v2",
                           "params": {"reasoning": False}})
    assert "reasoning_effort" not in LC.request_body(rv, [], False) and "不生效" in rv["reasoning_note"]
    rv = LC.resolve(None, {"provider": "deepseek", "params": {"reasoning": True}})
    assert LC.request_body(rv, [], False)["thinking"] == {"type": "enabled"}
    rv = LC.resolve(None, {"provider": "minimax", "params": {"reasoning": False}})   # M3.1-Flash 不能关
    assert "thinking" not in LC.request_body(rv, [], False) and rv["reasoning_note"]
    rv = LC.resolve(None, {"provider": "minimax", "model": "MiniMax-M3", "params": {"reasoning": False}})
    assert LC.request_body(rv, [], False)["thinking"] == {"type": "disabled"}
    LC.update_provider("custom", {"base_url": "http://x/v1", "default_model": "m", "models": ["m"]})
    rv = LC.resolve(None, {"provider": "custom", "params": {"reasoning": True}})
    assert "不支持" in rv["reasoning_note"]
    sup = next(p for p in c.get("/api/llm/providers").json()["providers"] if p["id"] == "custom")["reasoning_support"]
    assert sup["m"]["on"] is False and "不支持" in sup["m"]["note"]


def test_validation_gate_vs_strict_hints(cfg, monkeypatch):
    def fake(tool, p, episode):
        shot = {"id": "ep03-S1", "index": 1, "duration": 5, "ok": True, "repair": ""}
        gate = {"episodes": [{"number": 3, "title": "t", "issues": [], "repair": "",
                              "shots": [{**shot, "issues": [{"rule_id": "W", "level": "warn", "field": "f", "detail": "d"}]}]}]}
        strict = {"episodes": [{"number": 3, "title": "t", "issues": [], "repair": "",
                                "shots": [{**shot, "issues": [{"rule_id": "W", "level": "warn", "field": "f", "detail": "d"},
                                                              {"rule_id": "IMG-L2", "level": "block", "field": "img",
                                                               "detail": "x"}]}]}]}
        return (gate if tool == S.GATE_VALIDATOR else strict), ""
    monkeypatch.setattr(S, "_run_validator", fake)
    s = S.new_session()
    s["episodes"]["3"] = EP.strip()
    v = S.validate_draft(s)
    assert v["blocking"] == 0 and v["warnings"] == 1 and v["can_send"] is True and v["hints"] == 1
    sh = v["episodes"][0]["shots"][0]
    assert [i["rule_id"] for i in sh["issues"]] == ["W"] and [i["rule_id"] for i in sh["hints"]] == ["IMG-L2"]


def test_jobs_comfy_url_prefers_saved_endpoint(cfg, monkeypatch):
    from ns_api import jobs as J
    monkeypatch.setenv("NS_COMFY_URL_GPU3", "http://env:1")
    assert J.comfy_url(3) == "http://env:1"                                      # 没保存过：环境变量兜底
    monkeypatch.setattr(LC, "_probe", lambda url: (True, "ok"))
    c.put("/api/render/endpoints/video", json={"url": "http://saved:2/"})
    assert J.comfy_url(3) == "http://saved:2"                                    # 保存过的优先
    assert LC.saved_render_url(0) is None
