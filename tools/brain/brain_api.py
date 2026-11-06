"""API 常驻大脑（BRAIN-FW 11-06）：每 interval_s 一轮——telemetry 快照 → Claude（claude-fable-5-1，官方 anthropic SDK）判断 →
tools 调用 = 动作 → actions.run（护栏 / 速率 / 幂等 / dry-run）→ STATUS.md + cycles.jsonl。大脑可插拔：换模型只改 config/brain/brain.json。

SDK 用法（已对照 anthropic 2.6 源码 + 官方迁移指南）：
  · client.beta.messages.stream(...) + get_final_message()（长输出不超时）；model=claude-fable-5-1 思考常开 → 不传 thinking；
    output_config={"effort": cfg.effort}；tools 全部 strict=true；tool_choice {"type": "auto"}（这代模型强制 tool_choice 返回 400）；
  · 系统提示词（prompt.md + 动作目录）放 system 块并 cache_control ephemeral（稳定前缀）；快照放 user 消息（每轮变）；
  · betas=["server-side-fallback-2026-07-01"] + fallbacks="default"（安全分类器拒答时服务端自动换模型重跑）；stop_reason=="refusal" 照样处理；
  · 超时 / 重试走 client 选项（timeout / max_retries）；凭据走 SDK 标准解析（ANTHROPIC_API_KEY / ANTHROPIC_AUTH_TOKEN / ant auth login 的 profile），
    都没有 → 退出码 3 + 明确提示，不问、不存 key。
用法：
  .venv/Scripts/python.exe tools/brain/brain_api.py --offline            # 不连 API：只写快照 + data/brain/next_prompt.md（会话内大脑用）
  .venv/Scripts/python.exe tools/brain/brain_api.py --once [--dry-run]   # 连 API 跑一轮（config enabled 可为 false）
  .venv/Scripts/python.exe tools/brain/brain_api.py --loop               # 常驻（config enabled=false 时每拍只睡，等打开）
预算：price_per_mtok × usage → data/brain/budget.json 按 JST 日累计，到 budget_usd_day 当天停。
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUT_REL = "data/brain"
CFG_REL = "config/brain/brain.json"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
DEFAULT_CFG = {"enabled": False, "dry_run": True, "interval_s": 180, "model": "claude-fable-5-1", "effort": "high", "max_tokens": 16000,
               "max_actions_per_cycle": 6, "budget_usd_day": 20.0, "request_timeout_s": 600, "max_retries": 2, "fallbacks": "default",
               "price_per_mtok": {"input": 10.0, "output": 50.0, "cache_read": 0.25, "cache_write": 12.5}}

sys.path.insert(0, str(HERE))
import actions as A  # noqa: E402
import telemetry as T  # noqa: E402
import brain_status  # noqa: E402


def load_cfg(root: Path = ROOT) -> dict:
    d = T._j(root / CFG_REL, {}) or {}
    return {**DEFAULT_CFG, **{k: v for k, v in d.items() if not k.startswith("_")}}


def jst_day(now: float) -> str:
    return time.strftime("%Y-%m-%d", time.gmtime(now + 9 * 3600))


# ------------------------------------------------------------------ 提示词
def system_blocks(root: Path = ROOT) -> list[dict]:
    """稳定前缀：prompt.md + 动作目录；最后一块带 cache_control（快照不在这里）"""
    text = (root / "tools/brain/prompt.md").read_text(encoding="utf-8") if (root / "tools/brain/prompt.md").is_file() \
        else (HERE / "prompt.md").read_text(encoding="utf-8")
    return [{"type": "text", "text": text},
            {"type": "text", "text": "## 动作目录（与工具一一对应）\n" + A.catalog_text(), "cache_control": {"type": "ephemeral"}}]


def user_message(snap: dict) -> str:
    return ("下面是本轮全局快照（JSON）与摘要。请按系统提示词判断并用工具提交动作（没有要做的就调用 no_action），最后一段中文总结。\n\n"
            "### 摘要\n" + T.summary_md(snap) + "\n### JSON\n```json\n" + json.dumps(snap, ensure_ascii=False) + "\n```\n")


def next_prompt_md(snap: dict, root: Path = ROOT) -> str:
    """离线模式：给会话内大脑（PS-MASTER）的一份完整提示 = 系统提示词 + 动作目录 + 快照"""
    sb = system_blocks(root)
    return ("# BRAIN next prompt（离线生成 " + snap.get("at", "") + "）\n\n" + sb[0]["text"] + "\n\n" + sb[1]["text"] + "\n\n"
            "## 提交方式\n动作写成 JSON 列表交给 `tools/brain/actions.py run '<json>' --snapshot-hash " + str(snap.get("hash")) +
            "`（先 --dry-run 看护栏结果）。\n\n" + user_message(snap))


# ------------------------------------------------------------------ 解析与计费
def parse_response(msg) -> dict:
    """→ {stop_reason, text, actions: [{kind, ...input}], refusal: {...}|None, usage: {...}, model}"""
    text, acts = [], []
    for b in getattr(msg, "content", None) or []:
        bt = getattr(b, "type", None)
        if bt == "text":
            text.append(b.text)
        elif bt == "tool_use":
            inp = b.input if isinstance(b.input, dict) else json.loads(b.input or "{}")
            acts.append({"kind": b.name, **inp})
    u = getattr(msg, "usage", None)
    usage = {"input": int(getattr(u, "input_tokens", 0) or 0), "output": int(getattr(u, "output_tokens", 0) or 0),
             "cache_read": int(getattr(u, "cache_read_input_tokens", 0) or 0), "cache_write": int(getattr(u, "cache_creation_input_tokens", 0) or 0)}
    sr = getattr(msg, "stop_reason", None)
    sd = getattr(msg, "stop_details", None)
    refusal = None
    if sr == "refusal":
        refusal = {"category": getattr(sd, "category", None), "explanation": getattr(sd, "explanation", None)}
        acts = []
    return {"stop_reason": sr, "text": "\n".join(text).strip(), "actions": acts, "refusal": refusal, "usage": usage,
            "model": getattr(msg, "model", None)}


def usd(usage: dict, price: dict) -> float:
    return round(sum(usage.get(k, 0) * float(price.get(k, 0)) / 1e6 for k in ("input", "output", "cache_read", "cache_write")), 4)


def budget_add(root: Path, now: float, amount: float) -> float:
    p = root / OUT_REL / "budget.json"
    d = T._j(p, {}) or {}
    day = jst_day(now)
    if d.get("day") != day:
        d = {"day": day, "usd": 0.0}
    d["usd"] = round(float(d.get("usd") or 0) + amount, 4)
    T._jw(p, d)
    return d["usd"]


def budget_today(root: Path, now: float) -> float:
    d = T._j(root / OUT_REL / "budget.json", {}) or {}
    return float(d.get("usd") or 0) if d.get("day") == jst_day(now) else 0.0


# ------------------------------------------------------------------ 客户端
def credentials_present() -> bool:
    if os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"):
        return True
    try:
        from anthropic.lib.credentials._constants import _has_auto_discoverable_credentials
        return bool(_has_auto_discoverable_credentials())
    except Exception:  # noqa: BLE001  # arch-ok: SDK 内部函数不在 = 交给首个请求判定
        return True


def make_client(cfg: dict):
    import anthropic
    return anthropic.Anthropic(timeout=float(cfg["request_timeout_s"]), max_retries=int(cfg["max_retries"]))


def ask(client, cfg: dict, snap: dict, root: Path = ROOT):
    """一轮 API 调用 → 最终 message（流式 + get_final_message）"""
    kw = dict(model=cfg["model"], max_tokens=int(cfg["max_tokens"]), system=system_blocks(root), tools=A.tool_defs(),
              tool_choice={"type": "auto"}, output_config={"effort": cfg["effort"]},
              messages=[{"role": "user", "content": user_message(snap)}])
    if cfg.get("fallbacks"):
        kw["betas"] = [FALLBACK_BETA]
        kw["fallbacks"] = cfg["fallbacks"]
    with client.beta.messages.stream(**kw) as stream:
        return stream.get_final_message()


# ------------------------------------------------------------------ 一轮
def cycle(cfg: dict, client=None, env_t: T.Env | None = None, env_a: A.Env | None = None, dry: bool | None = None, root: Path = ROOT,
          ask_fn=None) -> dict:
    env_t = env_t or T.Env(root)
    env_a = env_a or A.Env(root)
    now = env_t.now()
    dry = bool(cfg.get("dry_run")) if dry is None else bool(dry)
    rec = {"at": T.jst(now, "%Y-%m-%d %H:%M:%S+09:00"), "t": now, "dry": dry, "model": cfg["model"]}
    spent = budget_today(root, now)
    if spent >= float(cfg["budget_usd_day"]):
        rec.update(error=f"今日预算已用 ${spent} ≥ ${cfg['budget_usd_day']}，本轮不调用", n_actions=0, n_rejected=0, usd_day=spent)
        _append(root / OUT_REL / "cycles.jsonl", rec)
        return rec
    snap = T.snapshot(env_t, T.load_cfg(root), save=True)
    rec["snapshot_hash"] = snap.get("hash")
    try:
        msg = (ask_fn or ask)(client, cfg, snap, root)
        pr = parse_response(msg)
    except Exception as e:  # noqa: BLE001  一轮失败只记，不影响常驻
        rec.update(error=f"API 失败 {type(e).__name__}: {e!s}"[:300], n_actions=0, n_rejected=0, usd_day=spent)
        _append(root / OUT_REL / "cycles.jsonl", rec)
        brain_status.write(root)
        return rec
    cost = usd(pr["usage"], cfg["price_per_mtok"])
    rec.update(stop_reason=pr["stop_reason"], served_by=pr.get("model"), text=pr["text"][:1500], refusal=pr["refusal"],
               input_tokens=pr["usage"]["input"], output_tokens=pr["usage"]["output"], cache_read=pr["usage"]["cache_read"],
               cache_write=pr["usage"]["cache_write"], usd=cost, usd_day=budget_add(root, now, cost))
    res = A.run(pr["actions"], env=env_a, dry=dry, snapshot_hash=snap.get("hash"), by="BRAIN-API", max_actions=int(cfg["max_actions_per_cycle"]))
    rec.update(n_actions=len(res), n_rejected=sum(1 for r in res if r.get("rejected")),
               actions=[{"kind": r["kind"], "result": str(r.get("result"))[:120]} for r in res])
    _append(root / OUT_REL / "cycles.jsonl", rec)
    brain_status.write(root)
    return rec


def _append(p: Path, rec: dict) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    with open(p, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def offline(root: Path = ROOT, env_t: T.Env | None = None) -> Path:
    """不连 API：快照 + next_prompt.md（会话内大脑照着做），也刷新 STATUS.md"""
    snap = T.snapshot(env_t or T.Env(root), T.load_cfg(root), save=True)
    p = root / OUT_REL / "next_prompt.md"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(next_prompt_md(snap, root), encoding="utf-8")
    os.replace(tmp, p)
    brain_status.write(root)
    return p


def loop(cfg_fn=load_cfg, sleep=time.sleep, stop=None, log=print, dry: bool | None = None) -> None:
    client = None
    while not (stop and stop.is_set()):
        t0 = time.time()
        cfg = cfg_fn()
        try:
            if cfg.get("enabled"):
                if client is None:
                    client = make_client(cfg)
                r = cycle(cfg, client, dry=dry)
                log(f"{r.get('at')} 大脑一轮：动作 {r.get('n_actions')} 拒 {r.get('n_rejected')} ${r.get('usd')} 今日 ${r.get('usd_day')} {r.get('error') or ''}")
        except Exception as e:  # noqa: BLE001
            log(f"大脑一轮异常（已继续）：{e!r}")
        every = max(30.0, float(cfg.get("interval_s") or 180))
        sleep(max(5.0, every - (time.time() - t0)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="API 常驻大脑（BRAIN-FW）")
    ap.add_argument("--offline", action="store_true", help="不连 API：写快照 + next_prompt.md")
    ap.add_argument("--once", action="store_true", help="连 API 跑一轮")
    ap.add_argument("--loop", action="store_true", help="常驻")
    ap.add_argument("--dry-run", action="store_true", help="动作只记不做（覆盖 config）")
    a = ap.parse_args(argv)
    if a.offline:
        p = offline()
        print(f"离线：快照 + {p}；状态页 data/brain/STATUS.md")
        return 0
    if not (a.once or a.loop):
        ap.print_help()
        return 2
    if not credentials_present():
        print("没有 Anthropic 凭据：设 ANTHROPIC_API_KEY，或先 `ant auth login`（SDK 自动读 profile）。本程序不问、不存 key。"
              "同时可用 --offline 让会话内大脑接管。", file=sys.stderr)
        return 3
    cfg = load_cfg()
    dry = True if a.dry_run else None
    if a.once:
        try:
            r = cycle(cfg, make_client(cfg), dry=dry)
        except Exception as e:  # noqa: BLE001
            print(f"失败：{e!r}", file=sys.stderr)
            return 1
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0 if not r.get("error") else 1
    loop(dry=dry, log=lambda m: print(time.strftime("%F %T"), m, flush=True))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
