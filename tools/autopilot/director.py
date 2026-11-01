"""审片导演（P10→P11，替代剪辑导演 agent）：给 LLM / 本地 VLM 看接触印样 + 机器指标，输出严格 JSON 判定，
写进 iterate_loop 的 director/verdicts.json（loop 下一个 tick 读：fail+reseed → 重出；owner → 待项目方）。

系统提示词：config/recipes/director_system_prompt.md（由 knowledge/ 生成，带版本号）。
后端（按可用性）：
- ComfyVLM：本机 ComfyUI 的 TextGenerate + Qwen3-VL 8B（qwen3vl_8b_int8_convrot，和出图共用编码器；ns_render.qc 已在用）。
  **会占一次出图道（gpu33:0）的 GPU 时间**，所以只在非 dry-run、且总调度允许时用。
- GatewayLLM：外部写作网关（文本模型，看不到图，只看指标和机器标记）。
- RuleBased：不调用任何模型，按指标和验收阈值给判定（dry-run / 测试 / 模型输出不合格时的兜底）。
模型输出不是合格 JSON → 带错误重问一次 → 仍不合格就用 RuleBased 兜底，并在 verdict 里标 by=rule_fallback。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT / "config" / "recipes" / "director_system_prompt.md"
ACTIONS = ("none", "reseed", "recipe", "owner")
SCORE_KEYS = ("identity", "coherence", "detail", "motion", "edit", "av_sync", "color")


def system_prompt() -> str:
    return PROMPT_PATH.read_text(encoding="utf-8")


def prompt_version() -> str | None:
    m = re.search(r"director_prompt_version:\s*(\S+)", system_prompt())
    return m.group(1) if m else None


def user_message(sid: str, sh: dict, plan: dict | None = None) -> str:
    m = {k: v for k, v in (sh.get("metrics") or {}).items() if not k.startswith("_")}
    info = {"shot": sid, "attempt": sh.get("renders"), "recipe": sh.get("recipe"),
            "machine_metrics": m, "machine_flags": sh.get("flags") or [],
            "failed_thresholds": sh.get("last_failures") or [],
            "acceptance": (plan or {}).get("acceptance"), "contact_sheet": sh.get("sheet")}
    return "镜头信息（JSON）：\n" + json.dumps(info, ensure_ascii=False, indent=1) + "\n请按系统提示输出判定 JSON。"


def parse_verdict(text: str, sid: str) -> tuple[dict | None, str | None]:
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    m = re.search(r"\{.*\}", t, re.S)
    if not m:
        return None, "没有 JSON 对象"
    try:
        v = json.loads(m.group(0))
    except ValueError as e:
        return None, f"JSON 解析失败：{e}"
    if v.get("verdict") not in ("pass", "fail"):
        return None, "verdict 必须是 pass 或 fail"
    if v.get("action", "none") not in ACTIONS:
        return None, f"action 必须是 {ACTIONS}"
    try:
        conf = float(v.get("confidence", 0))
    except (TypeError, ValueError):
        return None, "confidence 必须是 0–1 的数"
    scores = v.get("scores") or {}
    clean = {}
    for k in SCORE_KEYS:
        s = scores.get(k)
        if s is None:
            clean[k] = None
            continue
        try:
            clean[k] = max(0.0, min(10.0, float(s)))
        except (TypeError, ValueError):
            return None, f"scores.{k} 必须是 0–10 的数或 null"
    issues = [str(x) for x in (v.get("issues") or [])][:12]
    return {"shot": sid, "verdict": v["verdict"], "scores": clean, "issues": issues,
            "action": v.get("action", "none") if v["verdict"] == "fail" else "none",
            "confidence": max(0.0, min(1.0, conf))}, None


class RuleBased:
    name = "rule"

    def __call__(self, sid: str, sh: dict, plan: dict | None = None, retry_note: str | None = None) -> str:
        fails = sh.get("last_failures") or []
        att = int(sh.get("renders") or 1)
        issues = [f"{f['metric']} {f['value']}（阈值 {f['threshold']}）" for f in fails]
        action = "none" if not fails else ("reseed" if att < 3 else "owner")
        return json.dumps({"shot": sid, "verdict": "fail" if fails else "pass",
                           "scores": {k: None for k in SCORE_KEYS}, "issues": issues, "action": action,
                           "confidence": 0.9 if fails else 0.7}, ensure_ascii=False)


class GatewayLLM:
    """外部文本网关（看不到图）：messages → 文本。默认 ns_api.script_chat.complete（config/llm_providers.json）"""
    name = "gateway"

    def __init__(self, complete=None):
        self.complete = complete

    def __call__(self, sid, sh, plan=None, retry_note=None):
        msgs = [{"role": "system", "content": system_prompt()},
                {"role": "user", "content": user_message(sid, sh, plan) + (f"\n上次输出不合格：{retry_note}" if retry_note else "")}]
        if self.complete is None:
            from ns_api import script_chat as SC
            return SC.complete(msgs, max_tokens=600)["content"]
        return self.complete(msgs)


class ComfyVLM:
    """本地 Qwen3-VL 8B（ComfyUI TextGenerate）看接触印样。client = ns_render.comfy_client.ComfyClient"""
    name = "comfy_vlm"

    def __init__(self, client, max_length: int = 400, timeout_s: float = 600):
        self.client, self.max_length, self.timeout_s = client, max_length, timeout_s

    def __call__(self, sid, sh, plan=None, retry_note=None):
        from ns_render import workflows as W
        sheet = ROOT / (sh.get("sheet") or "")
        name = self.client.upload_image(sheet, subfolder="ns_final/director") if sheet.is_file() else None
        prompt = system_prompt() + "\n\n" + user_message(sid, sh, plan) + (f"\n上次输出不合格：{retry_note}" if retry_note else "")
        entry, _ = self.client.run(W.text_generate(prompt, "ns_final/director", image=name, max_length=self.max_length),
                                   timeout_s=self.timeout_s)
        return "".join(entry.get("outputs", {}).get("90", {}).get("text", []) or [])


def judge(sid: str, sh: dict, backend, plan: dict | None = None) -> dict:
    raw = backend(sid, sh, plan)
    v, err = parse_verdict(raw, sid)
    by = getattr(backend, "name", "model")
    if v is None:
        raw = backend(sid, sh, plan, retry_note=err)
        v, err2 = parse_verdict(raw, sid)
        if v is None:
            v, _ = parse_verdict(RuleBased()(sid, sh, plan), sid)
            by = f"rule_fallback（{by}: {err2}）"
    v["by"] = by
    v["prompt_version"] = prompt_version()
    return v


def review_run(store, backend, min_conf: float = 0.6, shots: list[str] | None = None) -> dict:
    """对 run 里已通过机器验收的镜头出判定，合并写 director/verdicts.json（iterate_loop 接口）"""
    state = store.load()
    out = store.verdicts()
    for sid, sh in state["shots"].items():
        if shots and sid not in shots:
            continue
        if sh.get("status") != "passed" or (out.get(sid) or {}).get("plan_hash") == sh.get("plan_hash"):
            continue
        plan = None
        if sh.get("plan_hash"):
            pp = store.dir / "plans" / f"{sh['plan_hash'][:16]}.json"
            plan = json.loads(pp.read_text(encoding="utf-8")) if pp.exists() else None
        v = judge(sid, sh, backend, plan)
        if v["confidence"] < min_conf and v["verdict"] == "fail":
            v["action"] = "none"
            v["note"] = f"置信度 {v['confidence']} < {min_conf}，只记录"
            v["verdict_raw"], v["verdict"] = "fail", "pass"
        v["plan_hash"] = sh.get("plan_hash")
        out[sid] = v
        store.event("director", shot=sid, verdict=v["verdict"], action=v["action"], by=v["by"])
    store.verdicts_path.parent.mkdir(parents=True, exist_ok=True)
    store.verdicts_path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
