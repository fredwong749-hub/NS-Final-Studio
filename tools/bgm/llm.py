"""写作 / 审听模型调用（与 tools/pipeline/run_chain.call_llm 同一套：llm_config 用途解析、记账 data/pipeline/ledger.jsonl、预算）。
用途 music_brief（config/llm_providers.json；未配置时回退 script_write）。Claude 不参与内容判断。"""
from __future__ import annotations

import json
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEDGER = ROOT / "data" / "pipeline" / "ledger.jsonl"
FALLBACK_PRICE = {"prompt": 1e-6, "completion": 2e-6}


class BudgetExceeded(RuntimeError):
    pass


def spent(tag: str) -> float:
    if not LEDGER.exists():
        return 0.0
    tot = 0.0
    for ln in LEDGER.read_text(encoding="utf-8").splitlines():
        try:
            d = json.loads(ln)
        except ValueError:
            continue
        if d.get("tag") == tag:
            tot += float(d.get("usd") or 0)
    return tot


def _resolve(purpose: str, fallback: str, reasoning: bool, max_tokens: int) -> dict:
    from ns_api import llm_config as LC
    ov = {"params": {"reasoning": reasoning, "max_tokens": max_tokens}}
    cfg = LC.load()
    use = purpose if purpose in (cfg.get("purposes") or {}) else fallback
    rv = LC.resolve(use, ov, cfg)
    rv["purpose_used"] = use
    return rv


def chat(system: str, user: str, *, cfg: dict, max_tokens: int, meta: dict) -> dict:
    from ns_api import llm_config as LC
    lc = cfg["llm"]
    rv = _resolve(lc["purpose"], lc["fallback_purpose"], bool(lc.get("reasoning")), max_tokens)
    try:
        pr = LC.model_pricing(rv["id"]).get(rv["model"]) or FALLBACK_PRICE
    except Exception:  # noqa: BLE001
        pr = FALLBACK_PRICE
    tag, budget = lc["budget_tag"], float(lc["budget_usd"])
    upper = (len(system) + len(user)) / 1.6 * pr["prompt"] + max_tokens * pr["completion"]
    have = spent(tag)
    if have + upper > budget:
        raise BudgetExceeded(f"预算 {tag}：已花 ${have:.4f}，本次上限 ${upper:.4f}，超过 ${budget}")
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    t0 = time.time()
    with LC.chat_request(rv, msgs, False, max_tokens) as r:
        data = json.loads(r.read().decode("utf-8"))
    ch = data["choices"][0]
    usage = data.get("usage") or {}
    pt, ct = int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)
    usd = pt * pr["prompt"] + ct * pr["completion"]
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": tag, "provider": rv["id"], "model": rv["model"],
                            "purpose": rv["purpose_used"], "prompt_tokens": pt, "completion_tokens": ct,
                            "usd": round(usd, 6), "seconds": round(time.time() - t0, 1), **meta}, ensure_ascii=False) + "\n")
    msg = ch.get("message") or {}
    return {"content": msg.get("content") or "", "finish": ch.get("finish_reason"), "usd": usd, "model": rv["model"],
            "provider": rv["id"], "purpose": rv["purpose_used"]}


def extract_json(text: str):
    from ns_schema.upstream_common import extract_json as X
    return X(text)
