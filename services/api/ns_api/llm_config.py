"""
统一模型与 API 配置（docs/canvas-ui-spec-v3-merge.md §8.2；接口契约 docs/api_v1_contract.md §A；fredw-92/W1）。

  config/llm_providers.json         服务商清单（不含密钥）：名称、base_url、模型列表、默认模型、超时、默认参数；
                                    purposes = 每个用途默认用哪家哪个模型
  config/llm_providers.local.json   只放密钥 {"providers": {<id>: {"api_key": "..."}}}（config/*.local.json 已 gitignore）
  config/render_endpoints.json      出图 / 视频 ComfyUI 地址（gpu3 隧道）

密钥来源（先到先用）：环境变量 key_env → llm_providers.local.json → 旧文件 key_files（如 config/abliteration.local.json，
迁移期读兼容）。任何接口都只返回 has_key，永不回传密钥；错误信息里出现密钥会替换成 ***。

调用方（script_chat / 导演加强 / tools/qwen_repair_loop.py）用：
  resolve(purpose, override=None) -> {"id","name","base_url","model","api_key","timeout_s","params",...}
  chat_request(resolved, messages, stream, max_tokens=None, extra=None) -> urlopen 响应
  complete_text(resolved, system, user) -> {"content","reasoning","usage"}   非流式
override = 接口上的 llm:{provider?, model?, params?}（每处 ⚙ 只改这一次）。

接口：
  GET  /api/llm/providers                 服务商 + 用途（has_key，无密钥）
  PUT  /api/llm/providers/{id}            改字段；api_key 只写进 .local.json（空串 = 删除）
  PUT  /api/llm/purposes/{purpose}        {provider, model}
  POST /api/llm/providers/{id}/test       发一条极短请求 → {ok, latency_ms, detail}
  GET  /api/render/endpoints              [{id:"image"|"video", url, gpu, reachable, detail}]
  PUT  /api/render/endpoints/{id}         {url}
"""
from __future__ import annotations

import copy
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
PROVIDERS_FILE = REPO / "config" / "llm_providers.json"
LOCAL_FILE = REPO / "config" / "llm_providers.local.json"
RENDER_FILE = REPO / "config" / "render_endpoints.json"

PURPOSES = {
    "script_write": "剧本写作",
    "script_repair": "格式返修",
    "director_boost": "导演加强",
    "lora_llm": "LoRA 训练用 LLM（打标 / 规划）",
    "prompt_rewrite": "首帧提示词改写",
}
EDITABLE = ("name", "base_url", "models", "default_model", "timeout_s", "params", "enabled", "ctx", "extra_body")

# 文件不存在时的内置默认（与 config/llm_providers.json 初版一致）
DEFAULTS: dict = {
    "providers": {
        "abliteration": {
            "name": "abliteration.ai", "base_url": "https://api.abliteration.ai/v1",
            "models": ["abliterated-model-large-flash", "abliterated-model-large-v2"],
            "default_model": "abliterated-model-large-flash",
            "key_env": "ABLITERATION_API_KEY", "key_files": ["config/abliteration.local.json"],
            "timeout_s": 1800, "params": {"temperature": 0.7, "max_tokens": 32000, "reasoning": None},
            "pricing_source": "models",
            "reasoning_body": {"on": {"reasoning_effort": "high"}, "off": {"reasoning_effort": "none"},
                               "off_unsupported": ["abliterated-model-large-v2"],
                               "doc": "https://docs.abliteration.ai/capabilities/thinking.md"}},
        "deepseek": {
            "name": "DeepSeek", "base_url": "https://api.deepseek.com", "models": ["deepseek-flash", "deepseek-v4-pro"],
            "default_model": "deepseek-flash", "key_env": "DEEPSEEK_API_KEY", "timeout_s": 1800,
            "params": {"temperature": 0.7, "max_tokens": 8000, "reasoning": None},
            "reasoning_body": {"on": {"thinking": {"type": "enabled"}}, "off": {"thinking": {"type": "disabled"}},
                               "doc": "https://api-docs.deepseek.com/guides/thinking_mode"}},
        "minimax": {
            "name": "MiniMax", "base_url": "https://api.minimax.io/v1", "models": ["MiniMax-M3.1-Flash", "MiniMax-M3"],
            "default_model": "MiniMax-M3.1-Flash", "key_env": "MINIMAX_API_KEY", "timeout_s": 1800,
            "params": {"temperature": 0.7, "max_tokens": 32000, "reasoning": None},
            "reasoning_body": {"on": {}, "off": {"thinking": {"type": "disabled"}},
                               "off_unsupported": ["MiniMax-M3.1-Flash"],
                               "doc": "https://platform.minimax.io/docs/api-reference/text-openai-api"}},
    },
    "purposes": {p: {"provider": "abliteration", "model": "abliterated-model-large-flash"} for p in PURPOSES},
}

_io_lock = threading.Lock()


class LLMConfigError(RuntimeError):
    """给项目方看的配置错误（中文，界面原样显示）"""


# ------------------------------------------------------------------ 读写

def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {}
    except ValueError as e:
        raise LLMConfigError(f"{p.name} 不是合法 JSON：{e}") from e


def _write_json(p: Path, data: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    tmp.replace(p)


def load() -> dict:
    cfg = _read_json(PROVIDERS_FILE) or copy.deepcopy(DEFAULTS)
    cfg.setdefault("providers", {})
    cfg.setdefault("purposes", {})
    for p in PURPOSES:   # 缺的用途按内置默认补
        cfg["purposes"].setdefault(p, dict(DEFAULTS["purposes"][p]))
    return cfg


def api_key(pid: str, cfg: dict | None = None) -> str | None:
    cfg = cfg or load()
    p = cfg["providers"].get(pid) or {}
    if p.get("key_env") and os.environ.get(p["key_env"]):
        return os.environ[p["key_env"]]
    k = ((_read_json(LOCAL_FILE).get("providers") or {}).get(pid) or {}).get("api_key")
    if k:
        return k
    for rel in p.get("key_files") or []:   # 旧文件读兼容（config/abliteration.local.json 等）
        kf = Path(rel) if Path(rel).is_absolute() else REPO / rel
        if kf.exists():
            k = _read_json(kf).get("api_key")
            if k:
                return k
    return None


def redact(text: str, *keys: str | None) -> str:
    for k in keys:
        if k:
            text = text.replace(k, "***")
    return text


def reasoning_support(p: dict, model: str) -> dict:
    """这家这个模型能不能开 / 关推理（config 里 reasoning_body：on / off 请求体片段 + 不支持的模型清单，
    写法以各家官方文档为准，链接在 reasoning_body.doc）。没配 reasoning_body = 该服务商不支持，开关不生效"""
    rb = p.get("reasoning_body") or {}
    if not rb:
        return {"on": False, "off": False, "note": "该服务商不支持推理开关（按模型自身默认）", "doc": None}
    on = "on" in rb and model not in (rb.get("on_unsupported") or [])
    off = "off" in rb and model not in (rb.get("off_unsupported") or [])
    note = "" if on and off else ("该模型不能关闭推理" if on else "该模型不支持推理开关")
    return {"on": on, "off": off, "note": note, "doc": rb.get("doc")}


# ------------------------------------------------------------------ 价格与费用档

PRICE_TTL_OK, PRICE_TTL_FAIL = 3600, 300
_price_cache: dict[str, tuple[float, dict]] = {}


def _fetch_models(rv: dict) -> list[dict]:
    headers = {"Authorization": f"Bearer {rv['api_key']}"} if rv.get("api_key") else {}
    req = urllib.request.Request(rv["base_url"] + "/models", headers=headers)
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read().decode("utf-8")).get("data") or []


def model_pricing(pid: str, cfg: dict | None = None) -> dict:
    """{model: {prompt, completion, input_cache_read}}（美元 / token）。只对 pricing_source="models" 的服务商
    读 GET {base_url}/models 的 pricing（abliteration 有）；拿不到 = {}（界面显示“未知”）。缓存 1 小时（失败 5 分钟）"""
    cfg = cfg or load()
    p = cfg["providers"].get(pid) or {}
    if p.get("pricing_source") != "models" or not p.get("base_url"):
        return {}
    hit = _price_cache.get(pid)
    if hit and time.time() - hit[0] < (PRICE_TTL_OK if hit[1] else PRICE_TTL_FAIL):
        return hit[1]
    out: dict = {}
    try:
        rv = {"base_url": p["base_url"].rstrip("/"), "api_key": api_key(pid, cfg)}
        for m in _fetch_models(rv):
            pr = m.get("pricing") or {}
            if m.get("id") and pr.get("prompt") is not None and pr.get("completion") is not None:
                out[m["id"]] = {k: float(pr.get(k) or 0) for k in ("prompt", "completion", "input_cache_read")}
    except (OSError, ValueError, TypeError, AttributeError):
        out = {}
    _price_cache[pid] = (time.time(), out)
    return out


def estimate_cost(pid: str, model: str, prompt_tokens: int, max_tokens: int, cfg: dict | None = None) -> dict:
    """费用上限 = 提示 token 估计 × 输入单价 + max_tokens × 输出单价（推理 token 也按输出计）"""
    pr = model_pricing(pid, cfg).get(model)
    if not pr:
        return {"prompt_tokens": prompt_tokens, "max_tokens": max_tokens, "upper_usd": None, "tier": "未知",
                "label": "未知（服务商没有提供单价）", "pricing": None}
    usd = prompt_tokens * pr["prompt"] + max_tokens * pr["completion"]
    tier = "低" if usd < 0.05 else "中" if usd < 0.5 else "高"
    return {"prompt_tokens": prompt_tokens, "max_tokens": max_tokens, "upper_usd": round(usd, 4), "tier": tier,
            "label": f"{tier}：最多约 ${usd:.3f}（提示约 {prompt_tokens} + 输出上限 {max_tokens} token）",
            "pricing": {"prompt_per_m": round(pr["prompt"] * 1e6, 4), "completion_per_m": round(pr["completion"] * 1e6, 4),
                        "currency": "USD"}}


def public_view(cfg: dict | None = None, prompt_tokens: int = 0) -> dict:
    cfg = cfg or load()
    provs = []
    for pid, p in cfg["providers"].items():
        params = {"temperature": None, "max_tokens": None, "reasoning": None, **(p.get("params") or {})}
        models = list(p.get("models") or [])
        prices = model_pricing(pid, cfg)
        dm = p.get("default_model") or ""
        provs.append({"id": pid, "name": p.get("name") or pid, "base_url": p.get("base_url") or "",
                      "models": models, "default_model": dm,
                      "has_key": bool(api_key(pid, cfg)), "key_env": p.get("key_env"),
                      "enabled": p.get("enabled", True), "timeout_s": p.get("timeout_s") or 600,
                      "params": params, "doc": p.get("_doc"),
                      "reasoning_support": {m: reasoning_support(p, m) for m in models},
                      "pricing": {m: ({"prompt_per_m": round(prices[m]["prompt"] * 1e6, 4),
                                       "completion_per_m": round(prices[m]["completion"] * 1e6, 4),
                                       "currency": "USD"} if m in prices else None) for m in models},
                      "estimate": estimate_cost(pid, dm, prompt_tokens, int(params.get("max_tokens") or 0), cfg)
                      if dm else None})
    purps = [{"id": k, "label": v, "provider": cfg["purposes"][k].get("provider"),
              "model": cfg["purposes"][k].get("model")} for k, v in PURPOSES.items()]
    return {"providers": provs, "purposes": purps}


def update_provider(pid: str, body: dict) -> dict:
    with _io_lock:
        cfg = _read_json(PROVIDERS_FILE) or copy.deepcopy(DEFAULTS)
        cfg.setdefault("providers", {})
        p = cfg["providers"].setdefault(pid, {"name": pid, "models": [], "params": {}})
        for k in EDITABLE:
            if body.get(k) is not None:
                p[k] = ({**(p.get("params") or {}), **body[k]} if k == "params" else body[k])
        if "api_key" in body and body["api_key"] is not None:
            loc = _read_json(LOCAL_FILE)
            loc.setdefault("providers", {})
            if body["api_key"].strip():
                loc["providers"].setdefault(pid, {})["api_key"] = body["api_key"].strip()
            else:
                loc["providers"].get(pid, {}).pop("api_key", None)
            _write_json(LOCAL_FILE, loc)
        _write_json(PROVIDERS_FILE, cfg)
    return next(x for x in public_view()["providers"] if x["id"] == pid)


def set_purpose(purpose: str, provider: str, model: str | None) -> dict:
    if purpose not in PURPOSES:
        raise LLMConfigError(f"用途只能是 {' | '.join(PURPOSES)}")
    with _io_lock:
        cfg = _read_json(PROVIDERS_FILE) or copy.deepcopy(DEFAULTS)
        if provider not in cfg.get("providers", {}):
            raise LLMConfigError(f"没有这个服务商：{provider}")
        model = model or cfg["providers"][provider].get("default_model") or ""
        cfg.setdefault("purposes", {})[purpose] = {"provider": provider, "model": model}
        _write_json(PROVIDERS_FILE, cfg)
    return {"id": purpose, "label": PURPOSES[purpose], "provider": provider, "model": model}


# ------------------------------------------------------------------ 解析与调用

def resolve(purpose: str | None = None, override: dict | None = None, cfg: dict | None = None) -> dict:
    """用途默认 → 覆盖 llm:{provider?, model?, params?}。返回调用所需的一切（含密钥，只用于请求头）"""
    cfg = cfg or load()
    ov = override or {}
    pur = cfg["purposes"].get(purpose or "script_write") or {}
    pid = ov.get("provider") or pur.get("provider")
    if not pid or pid not in cfg["providers"]:
        raise LLMConfigError(f"没有这个服务商：{pid}（在「模型与 API」页或 config/llm_providers.json 配置）")
    p = cfg["providers"][pid]
    if ov.get("provider") and not ov.get("model"):
        model = p.get("default_model")
    else:
        model = ov.get("model") or pur.get("model") or p.get("default_model")
    if not model:
        raise LLMConfigError(f"{p.get('name') or pid} 没有填模型名（在「模型与 API」页按官方文档填写）")
    if not p.get("base_url"):
        raise LLMConfigError(f"{p.get('name') or pid} 没有填 base_url")
    params = {**(p.get("params") or {}), **{k: v for k, v in (ov.get("params") or {}).items() if v is not None}}
    rs = reasoning_support(p, model)
    want = params.get("reasoning")
    note = None
    if want is not None and not rs["on" if want else "off"]:   # 不假装生效：不发该字段，并告诉调用方
        note = f"推理开关（{'开' if want else '关'}）对 {p.get('name') or pid} / {model} 不生效：{rs['note']}"
    return {"id": pid, "name": p.get("name") or pid, "base_url": p["base_url"].rstrip("/"), "model": model,
            "api_key": api_key(pid, cfg), "key_env": p.get("key_env"), "timeout_s": p.get("timeout_s") or 600,
            "params": params, "extra_body": p.get("extra_body") or {}, "reasoning_body": p.get("reasoning_body"),
            "reasoning_ok": rs, "reasoning_note": note,
            "ctx": p.get("ctx"), "reserve": p.get("reserve") or 0, "tokenize_url": p.get("tokenize_url"),
            "appendix_budget": p.get("appendix_budget"), "purpose": purpose}


HTTP_HINT = {401: "API key 无效或已失效", 402: "余额不足，请到服务商充值", 403: "API key 没有权限",
             404: "模型名或地址不对（「模型与 API」页 / config/llm_providers.json）",
             429: "被限流（请求太多或额度用完），稍后再试", 500: "写作模型服务内部错误", 502: "写作模型网关错误",
             503: "写作模型暂时不可用", 504: "写作模型网关超时"}


def request_body(rv: dict, messages: list[dict], stream: bool, max_tokens: int | None = None) -> dict:
    pr = rv["params"]
    body = {"model": rv["model"], "messages": messages, "stream": stream}
    if pr.get("temperature") is not None:
        body["temperature"] = pr["temperature"]
    mt = max_tokens or pr.get("max_tokens")
    if mt:
        body["max_tokens"] = int(mt)
    body.update(rv.get("extra_body") or {})
    rb = rv.get("reasoning_body") or {}   # 每家开 / 关推理的写法不同：服务商条目里写 reasoning_body.on / off
    want = pr.get("reasoning")
    if want is not None and rb and not rv.get("reasoning_note"):   # 不支持的组合不发（resolve 已给 reasoning_note）
        body.update(rb.get("on" if want else "off") or {})
    if stream:
        body["stream_options"] = {"include_usage": True}
    return body


def chat_request(rv: dict, messages: list[dict], stream: bool, max_tokens: int | None = None, error_cls=LLMConfigError):
    """发 /chat/completions，返回 urlopen 响应（调用方 with 关闭）；错误转成 error_cls（中文，密钥已遮盖）"""
    if not rv.get("api_key") and rv.get("key_env"):
        raise error_cls(f"缺少 {rv['name']} 的 API key：在「模型与 API」页填写，或设环境变量 {rv['key_env']}")
    headers = {"Content-Type": "application/json"}
    if rv.get("api_key"):
        headers["Authorization"] = f"Bearer {rv['api_key']}"
    req = urllib.request.Request(rv["base_url"] + "/chat/completions",
                                 data=json.dumps(request_body(rv, messages, stream, max_tokens)).encode("utf-8"),
                                 headers=headers, method="POST")
    name, key = rv["name"], rv.get("api_key")
    try:
        return urllib.request.urlopen(req, timeout=rv["timeout_s"])
    except urllib.error.HTTPError as e:
        raise error_cls(redact(f"{name} HTTP {e.code}（{HTTP_HINT.get(e.code, '请求失败')}）："
                               f"{e.read().decode('utf-8', 'replace')[:300]}", key)) from e
    except TimeoutError as e:
        raise error_cls(f"{name} 超时：{rv['timeout_s']} 秒没有响应") from e
    except urllib.error.URLError as e:
        raise error_cls(redact(f"{name} 连不上（{rv['base_url']}）：{e.reason}", key)) from e
    except OSError as e:
        raise error_cls(redact(f"{name} 连接中断（{rv['base_url']}）：{e}", key)) from e


def complete_text(rv: dict, system: str | None, user: str, max_tokens: int | None = None,
                  error_cls=LLMConfigError) -> dict:
    """非流式一问一答 → {"content","reasoning","usage","finish"}"""
    msgs = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": user}]
    with chat_request(rv, msgs, False, max_tokens, error_cls) as r:
        try:
            data = json.loads(r.read().decode("utf-8"))
            ch = data["choices"][0]
        except (ValueError, KeyError, IndexError) as e:
            raise error_cls(f"{rv['name']} 返回格式不对：{e!r}") from e
    msg = ch.get("message") or {}
    return {"content": msg.get("content") or "", "reasoning": msg.get("reasoning") or msg.get("reasoning_content") or "",
            "usage": data.get("usage"), "finish": ch.get("finish_reason")}


def test_provider(pid: str, model: str | None = None) -> dict:
    t0 = time.time()
    try:
        rv = resolve(None, {"provider": pid, "model": model, "params": {"max_tokens": 16, "temperature": 0}})
        out = complete_text(rv, None, "ping")
        return {"ok": True, "latency_ms": int((time.time() - t0) * 1000),
                "detail": f"{rv['model']} 已响应；usage={json.dumps(out['usage'], ensure_ascii=False)}"}
    except LLMConfigError as e:
        return {"ok": False, "latency_ms": int((time.time() - t0) * 1000), "detail": str(e)}


# ------------------------------------------------------------------ 出图 / 视频端点

RENDER_DEFAULTS = {
    "image": {"url": os.environ.get("NS_COMFY_URL") or "http://127.0.0.1:18188", "gpu": 0,
              "label": "Image 2.1 Turbo（gpu3 GPU0 ComfyUI，隧道 18188 → 8188）"},
    "video": {"url": "http://127.0.0.1:18191", "gpu": 3, "label": "MiniMax H3（gpu3 GPU3 ComfyUI，隧道 18191 → 8191）"},
}


def render_endpoints() -> dict:
    saved = _read_json(RENDER_FILE)
    return {k: {**v, **(saved.get(k) or {})} for k, v in RENDER_DEFAULTS.items()}


def saved_render_url(gpu: int) -> str | None:
    """「模型与 API」页保存过的、指向这张卡的地址（image / video 按各自 gpu 匹配）；没保存过返回 None，
    调用方（ns_api/jobs.comfy_url）再按环境变量 / 内置默认兜底"""
    try:
        saved = _read_json(RENDER_FILE)
    except LLMConfigError:
        return None
    for eid, d in RENDER_DEFAULTS.items():
        e = saved.get(eid)
        if isinstance(e, dict) and e.get("url") and int(e.get("gpu", d["gpu"])) == int(gpu):
            return str(e["url"]).rstrip("/")
    return None


def _probe(url: str) -> tuple[bool, str]:
    """F4：与 /api/render-backend 同一个探测（ns_render.endpoints.probe：8 s 超时、15 s 缓存）"""
    from ns_render import endpoints as EP
    st = EP.probe(url)
    return bool(st["reachable"]), st.get("detail") or ""


# ------------------------------------------------------------------ 接口

router = APIRouter()


def _http(e: LLMConfigError, code: int = 400):
    return HTTPException(code, str(e))


@router.get("/api/llm/providers")
def get_providers(prompt_tokens: int = 0):
    """prompt_tokens = 本次请求的提示 token 估计（剧本创作页从 /api/script-chat/estimate 拿）；
    每家 estimate = 它 × 输入单价 + 该家 max_tokens × 输出单价"""
    try:
        return public_view(prompt_tokens=max(0, prompt_tokens))
    except LLMConfigError as e:
        raise _http(e, 500)


class ProviderBody(BaseModel):
    name: str | None = None
    base_url: str | None = None
    models: list[str] | None = None
    default_model: str | None = None
    timeout_s: float | None = None
    params: dict | None = None
    enabled: bool | None = None
    api_key: str | None = None


@router.put("/api/llm/providers/{pid}")
def put_provider(pid: str, body: ProviderBody):
    if not pid.replace("_", "").replace("-", "").isalnum():
        raise HTTPException(400, "服务商 id 只能是字母、数字、_、-")
    try:
        return update_provider(pid, body.model_dump(exclude_unset=True))
    except LLMConfigError as e:
        raise _http(e)


class PurposeBody(BaseModel):
    provider: str
    model: str | None = None


@router.get("/api/llm/purposes")
def get_purposes():
    """与 GET /api/llm/providers 的 purposes 同一数组 [{id,label,provider,model}]（不查单价，快）"""
    try:
        cfg = load()
    except LLMConfigError as e:
        raise _http(e, 500)
    return [{"id": k, "label": v, "provider": cfg["purposes"][k].get("provider"),
             "model": cfg["purposes"][k].get("model")} for k, v in PURPOSES.items()]


@router.put("/api/llm/purposes/{purpose}")
def put_purpose(purpose: str, body: PurposeBody):
    try:
        return set_purpose(purpose, body.provider, body.model)
    except LLMConfigError as e:
        raise _http(e)


class TestBody(BaseModel):
    model: str | None = None


@router.post("/api/llm/providers/{pid}/test")
def post_test(pid: str, body: TestBody | None = None):
    if pid not in load()["providers"]:
        raise HTTPException(404, f"没有这个服务商：{pid}")
    return test_provider(pid, body.model if body else None)


@router.get("/api/render/endpoints")
def get_render_endpoints():
    out = []
    for k, v in render_endpoints().items():
        ok, detail = _probe(v["url"])
        out.append({"id": k, "url": v["url"], "gpu": v.get("gpu"), "label": v.get("label"),
                    "reachable": ok, "detail": detail})
    return out


class EndpointBody(BaseModel):
    url: str


@router.put("/api/render/endpoints/{eid}")
def put_render_endpoint(eid: str, body: EndpointBody):
    if eid not in RENDER_DEFAULTS:
        raise HTTPException(404, "端点只有 image | video")
    if not body.url.startswith(("http://", "https://")):
        raise HTTPException(400, "地址要以 http:// 或 https:// 开头")
    with _io_lock:
        saved = _read_json(RENDER_FILE)
        saved.setdefault(eid, {})["url"] = body.url.rstrip("/")
        _write_json(RENDER_FILE, saved)
    v = render_endpoints()[eid]
    from ns_render import endpoints as EP
    EP.forget(v["url"])                     # 地址刚改：不用缓存，立即重新探测
    ok, detail = _probe(v["url"])
    return {"id": eid, "url": v["url"], "gpu": v.get("gpu"), "reachable": ok, "detail": detail}
