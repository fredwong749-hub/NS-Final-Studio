"""资产图“再生成”提示词改写（L-119，项目方 11-02 15:4x）。

项目方原话：“这里的提示词我会写一些大概的思路，需要你将其转换成更符合图像模型的提示词……调用 API LM 的 key 来处理，
不能用系统本地来写，否则写不出我的感觉。”
→ 项目方的口语思路 + 造型登记字段，经写作网关（config/llm_providers.json 用途 prompt_rewrite，外部 API）改写成
Qwen-Image-Edit 的英文编辑提示词。系统提示词 = config/recipes/regen_prompt_rewrite.md（可由项目方改）。
- 只发文字：发前过 K-REV-V01 text_only_guard（图片 / 文件名一律拒发）。
- 网关不可用 / 输出两次不合格 → 抛 RewriteError，调用方不出图、如实告诉项目方；不退回本地模板硬写（项目方明确不要）。
- 每次记账 data/pipeline/ledger.jsonl（tag=regen_rewrite），超过 config 预算 → 拒绝。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SYSTEM_FILE = ROOT / "config" / "recipes" / "regen_prompt_rewrite.md"
EDIT_FILE = ROOT / "config" / "recipes" / "edit_prompt_rewrite.md"
# L-120：所有带提示词的入口都走改写。kind → 系统提示词文件（再生成一族共用 regen 文件；编辑 / 新造型 / 新单品用 edit 文件）
KIND_FILES = {"sheet": "SYSTEM_FILE", "face": "SYSTEM_FILE", "item": "SYSTEM_FILE", "scene_plate": "SYSTEM_FILE",
              "edit_mask": "EDIT_FILE", "new_look": "EDIT_FILE", "new_item": "EDIT_FILE"}
LEDGER = ROOT / "data" / "pipeline" / "ledger.jsonl"
TAG = "regen_rewrite"
BUDGET_USD_PER_DAY = 2.0
PURPOSE = "prompt_rewrite"


class RewriteError(RuntimeError):
    pass


def _spent_today() -> float:
    day = time.strftime("%Y-%m-%d")
    s = 0.0
    if LEDGER.exists():
        for ln in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
            except ValueError:   # arch-ok: 账本里坏行跳过，不影响预算判断（其余行照算）
                continue
            if d.get("tag") == TAG and str(d.get("at", "")).startswith(day):
                s += float(d.get("usd") or 0)
    return s


def system_path(kind: str) -> Path:
    if kind not in KIND_FILES:
        raise RewriteError(f"不认识的提示词入口：{kind}（只有 {' / '.join(KIND_FILES)}）")
    return globals()[KIND_FILES[kind]]


def build_user(kind: str, owner_text: str, ctx: dict) -> str:
    rows = [f"资产类型：{kind}"]
    if ctx.get("name"):
        rows.append(f"人物：{ctx['name']}")
    if ctx.get("look"):
        rows.append(f"造型：{ctx['look']}（{ctx.get('use') or ''}）")
    if ctx.get("look_zh"):
        rows.append(f"这套造型登记的字段：{ctx['look_zh']}")
    if ctx.get("item"):
        rows.append(f"单品：{ctx['item']}")
    if ctx.get("scene"):
        rows.append(f"场景：{ctx['scene']}")
    if ctx.get("region"):
        rows.append(f"项目方框选的区域（相对整张图的位置和大小）：{ctx['region']}")
    if ctx.get("gear"):
        rows.append(f"项目方另附装备参考图（模型会看到，作为“取这一件”的参考）：{'、'.join(ctx['gear'])}")
    rows.append(f"项目方原话：{owner_text.strip()}")
    return "\n".join(rows)


def _parse(text: str) -> dict:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        raise ValueError("没有 JSON")
    d = json.loads(m.group(0))
    p = str(d.get("prompt") or "").strip()
    if len(p) < 20:
        raise ValueError("prompt 太短")
    return {"prompt": p, "negative_add": str(d.get("negative_add") or "").strip(), "zh_summary": str(d.get("zh_summary") or "").strip()}


def rewrite(kind: str, owner_text: str, ctx: dict | None = None, chat=None) -> dict:
    """→ {prompt, negative_add, zh_summary, model, usd, owner_text}；失败抛 RewriteError（不出图）"""
    from ns_agent.vqa.judge import ImageLeak, text_only_guard
    from ns_api import llm_config as LC
    ctx = ctx or {}
    system = system_path(kind).read_text(encoding="utf-8")
    user = build_user(kind, owner_text, ctx)
    try:
        text_only_guard(system, user)
    except ImageLeak as e:
        raise RewriteError(str(e)) from e
    if _spent_today() > BUDGET_USD_PER_DAY:
        raise RewriteError(f"今天的提示词改写预算（${BUDGET_USD_PER_DAY}）用完了")
    msgs = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    err = None
    for attempt in range(2):
        t0 = time.time()
        try:
            if chat:
                out = chat(msgs)
                content, model, usd = out["content"], out.get("model", "test"), float(out.get("usd") or 0)
            else:
                rv = LC.resolve(PURPOSE, {"params": {"reasoning": False}})
                r = LC.complete_text(rv, system, msgs[-1]["content"], 1200)
                content, model = r["content"], rv["model"]
                u = r.get("usage") or {}
                try:
                    pr = LC.model_pricing(rv["id"]).get(rv["model"]) or {"prompt": 1e-6, "completion": 2e-6}
                except Exception:  # noqa: BLE001  价格表取不到按保守单价记账
                    pr = {"prompt": 1e-6, "completion": 2e-6}
                usd = int(u.get("prompt_tokens") or 0) * pr["prompt"] + int(u.get("completion_tokens") or 0) * pr["completion"]
                LEDGER.parent.mkdir(parents=True, exist_ok=True)
                with LEDGER.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": TAG, "provider": rv["id"], "model": model,
                                        "purpose": PURPOSE, "usd": round(usd, 6), "seconds": round(time.time() - t0, 1)},
                                       ensure_ascii=False) + "\n")
            res = _parse(content)
            return {**res, "model": model, "usd": usd, "owner_text": owner_text.strip()}
        except LC.LLMConfigError as e:
            raise RewriteError(f"写作网关不可用：{e}") from e
        except (ValueError, KeyError) as e:
            err = e
            msgs = msgs[:2] + [{"role": "user", "content": f"上次输出不合格（{e}），只输出要求的 JSON。"}]
    raise RewriteError(f"改写模型两次都没给出合格 JSON：{err}")
