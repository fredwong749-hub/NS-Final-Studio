"""R11-10 闭环的“大脑”：写作网关 API（只收文字）判 pass / fail，并给下一轮的提示词改动（prompt_delta）。

流程（PRODUCER 每张出图后调用 review_round；只记录期不改变 PRODUCER 的通过判定，只把记录写进 take.params.vqa_rounds）：
  1 本地看图（client.inspect_image）→ 结构化描述 + 缺陷清单（文字）
  2 judge()：把【文字】+ 镜头原文 + 造型 + 契约 Q1–Q8 结果发给写作网关 → {verdict, failed_checks, prompt_delta, action, script_feedback}
  3 apply_delta(prompt, delta) → 下一轮提示词（一次只改一个维度）
K-REV-V01：text_only_guard 拒绝任何含图片字节 / data URL / 图片文件路径的内容出本机。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import ROOT, cfg, rubric

LEDGER = ROOT / "data" / "pipeline" / "ledger.jsonl"
FEEDBACK = ROOT / "data" / "vqa" / "script_feedback.jsonl"
_IMG_PAT = re.compile(r"data:image/|;base64,|\.(png|jpe?g|webp|bmp|gif|mp4|mov)\b|iVBORw0KGgo|/9j/4AAQ", re.I)


class ImageLeak(RuntimeError):
    pass


def text_only_guard(*texts: str) -> None:
    """K-REV-V01：发外部 API 之前的最后一道闸。出现图片字节 / data URL / 图片或视频文件名 → 拒发"""
    for t in texts:
        m = _IMG_PAT.search(t or "")
        if m:
            raise ImageLeak(f"K-REV-V01：拒绝把图片 / 文件路径发给外部 API（命中 {m.group(0)!r}）")


def _contract_text(contract: dict | None) -> str:
    rows = []
    for it in (contract or {}).get("items") or []:
        if it.get("id") in ("Q9", "V9"):
            continue
        rows.append(f"- {it.get('id')} {it.get('title', '')}：{it.get('status')}｜{_IMG_PAT.sub('…', it.get('detail', ''))[:200]}")
    return "\n".join(rows) or "（没有契约结果）"


def build_messages(shot_id: str, kind: str, rnd: int, prompt: str, vlm: dict, contract: dict | None,
                   history: list[dict] | None) -> list[dict]:
    sec = rubric.sections("vqa_judge.md")
    sp = vlm.get("spec") or rubric.spec_from_prompt(prompt)
    desc, defects = rubric.describe(vlm)
    hist = "\n".join(f"- 第{h.get('round')}轮：{(h.get('judge') or {}).get('verdict')}｜改 {((h.get('judge') or {}).get('prompt_delta') or {}).get('dimension')}"
                     f"｜结果 {h.get('outcome')}" for h in history or []) or "（第一轮）"
    user = sec["user"].format(shot_id=shot_id, kind=kind, round=rnd, prompt=prompt or "（无）",
                              items="、".join(sp.get("items") or []), cast="、".join(sp.get("cast") or []), size=sp.get("size"),
                              vlm_description=desc, vlm_defects=defects, contract=_contract_text(contract), history=hist)
    return [{"role": "system", "content": sec["system"]}, {"role": "user", "content": user}]


def parse_judge(text: str) -> dict | None:
    d = rubric._loads_loose(text or "")
    if not isinstance(d, dict) or d.get("verdict") not in ("pass", "fail"):
        return None
    pd = d.get("prompt_delta") or {}
    if not isinstance(pd, dict):
        pd = {"append": str(pd)}
    d["prompt_delta"] = {"dimension": str(pd.get("dimension") or ""), "append": str(pd.get("append") or "")[:300],
                         "replace": [list(x)[:2] for x in pd.get("replace") or [] if isinstance(x, (list, tuple)) and len(x) >= 2][:4],
                         "negative_append": str(pd.get("negative_append") or "")[:200]}
    d["action"] = d.get("action") if d.get("action") in ("reprompt", "reseed", "owner") else ("reprompt" if d["verdict"] == "fail" else "none")
    d["failed_checks"] = [str(x) for x in d.get("failed_checks") or []]
    return d


def _chat(messages: list[dict]) -> dict:
    """写作网关调用（llm_config 用途 vqa_judge → 回退 prompt_rewrite）；记账 data/pipeline/ledger.jsonl，预算 config judge.budget_usd"""
    from ns_api import llm_config as LC
    j = cfg().get("judge") or {}
    text_only_guard(*(m["content"] for m in messages))
    c = LC.load()
    use = j.get("purpose", "vqa_judge") if j.get("purpose", "vqa_judge") in (c.get("purposes") or {}) else j.get("fallback_purpose", "prompt_rewrite")
    rv = LC.resolve(use, {"params": {"reasoning": False, "max_tokens": int(j.get("max_tokens", 1200))}}, c)
    spent = 0.0
    if LEDGER.exists():
        for ln in LEDGER.read_text(encoding="utf-8").splitlines():
            try:
                d = json.loads(ln)
            except ValueError:
                continue
            if d.get("tag") == j.get("budget_tag", "vqa_judge"):
                spent += float(d.get("usd") or 0)
    if spent > float(j.get("budget_usd", 3.0)):
        raise RuntimeError(f"vqa_judge 预算用完：已花 ${spent:.3f}")
    t0 = time.time()
    with LC.chat_request(rv, messages, False, int(j.get("max_tokens", 1200))) as r:
        data = json.loads(r.read().decode("utf-8"))
    usage = data.get("usage") or {}
    try:
        pr = LC.model_pricing(rv["id"]).get(rv["model"]) or {"prompt": 1e-6, "completion": 2e-6}
    except Exception:  # noqa: BLE001
        pr = {"prompt": 1e-6, "completion": 2e-6}
    usd = int(usage.get("prompt_tokens") or 0) * pr["prompt"] + int(usage.get("completion_tokens") or 0) * pr["completion"]
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": j.get("budget_tag", "vqa_judge"), "provider": rv["id"],
                            "model": rv["model"], "purpose": use, "usd": round(usd, 6), "seconds": round(time.time() - t0, 1)},
                           ensure_ascii=False) + "\n")
    return {"content": ((data["choices"][0].get("message") or {}).get("content") or ""), "model": rv["model"], "usd": usd}


def judge(shot_id: str, kind: str, prompt: str, vlm: dict, contract: dict | None = None, *, rnd: int = 1,
          history: list[dict] | None = None, chat=None) -> dict:
    """→ {verdict, confidence, failed_checks, reasons, prompt_delta, action, script_feedback, by, model}。
    网关不可用 / 输出不合格两次 → 规则回退：本地看图 hard 级缺陷即 fail，prompt_delta 用 config 的固定修正句"""
    msgs = build_messages(shot_id, kind, rnd, prompt, vlm, contract, history)
    chat = chat or _chat
    err = None
    for attempt in range(2):
        try:
            out = chat(msgs if attempt == 0 else msgs + [{"role": "user", "content": f"上次输出不是要求的 JSON（{err}），只输出 JSON。"}])
        except Exception as e:  # noqa: BLE001
            err = f"{type(e).__name__}: {e}"
            if isinstance(e, ImageLeak):
                raise
            break
        d = parse_judge(out.get("content", ""))
        if d:
            d.update(by="gateway", model=out.get("model"))
            if d.get("script_feedback"):
                FEEDBACK.parent.mkdir(parents=True, exist_ok=True)
                with FEEDBACK.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "shot": shot_id, "kind": kind,
                                        "failed_checks": d["failed_checks"], "feedback": d["script_feedback"]}, ensure_ascii=False) + "\n")
            return d
        err = "不是合法 JSON"
    return rule_fallback(vlm, err)


FIX = {   # 规则回退时每类缺陷的固定修正句（一次只改一个维度：按 severity hard 优先、config 顺序取第一个）
    "extra_limbs": ("hands", "每个人只有两只手两条手臂，双手位置写清楚，手完整自然"),
    "hand_malformed": ("hands", "手部解剖正确，五指清晰分开、比例自然"),
    "body_anatomy": ("people", "人体结构自然、关节方向正确"),
    "extra_person": ("people", "画面中只有在画角色，不要出现其他人或同一人的重复"),
    "identity_drift": ("identity", "面部与身份参考图完全一致"),
    "hair_mismatch": ("hair", "发型发色与身份参考完全一致"),
    "outfit_mismatch": ("outfit", "服装与造型设定图完全一致，外层单品必须穿上"),
    "shoe_mismatch": ("shoes", "鞋与参考鞋完全一致（款式、颜色、透明度、跟高）"),
    "accessory_mismatch": ("outfit", "指甲与首饰与参考完全一致"),
    "clothing_state": ("outfit", "所有人按原文穿着完整"),
    "wrong_scene": ("scene", "场景与场景参考一致"),
    "lighting_time": ("scene", "光线与时段严格按原文"),
    "framing_mismatch": ("framing", "严格按原文景别构图"),
    "text_watermark": ("text", "画面无任何文字、字幕、标志"),
    "eye_contact": ("gaze", "视线不看镜头，看向原文写的对象"),
    "blank_expression": ("expression", "每个人都有符合情境的表情和明确的视线对象"),
    "plastic_doll": ("texture", "真实皮肤质感，可见毛孔与细微瑕疵，非磨皮、非塑料感"),
    "face_artifact": ("texture", "五官端正自然、双眼对称"),
    "artifact": ("texture", "画面干净无变形物体"),
    "collage_or_ref_leak": ("scene", "单一完整画面，不是拼图，不要白底棚拍"),
    "low_resolution": ("texture", "高清锐利，面部细节清晰"),
}


def rule_fallback(vlm: dict, why: str | None) -> dict:
    checks = cfg().get("checks") or {}
    bad = [d for d in vlm.get("defects") or [] if (checks.get(d) or {}).get("severity") == "hard"]
    if not bad:
        return {"verdict": "pass", "confidence": 0.4, "failed_checks": [], "reasons": [], "prompt_delta": {},
                "action": "none", "by": f"rule_fallback（{why}）"}
    order = list(checks)
    first = sorted(bad, key=order.index)[0]
    dim, sent = FIX.get(first, ("", ""))
    return {"verdict": "fail", "confidence": 0.5, "failed_checks": bad,
            "reasons": [f"{(checks.get(b) or {}).get('zh', b)}" for b in bad],
            "prompt_delta": {"dimension": dim, "append": sent, "replace": [], "negative_append": ""},
            "action": "reprompt", "by": f"rule_fallback（{why}）"}


_REF_NOTE = re.compile(r"图\d+是[^。]*。")     # 编译器参考图标注句（frame_job / asset_refs 生成，preflight I6 核对）


def apply_delta(prompt: str, delta: dict | None) -> str:
    """一次只改一个维度：先做 replace，再把 append 句插到“无字幕、无文字、无水印”系统尾巴之前（没有就加在末尾）"""
    p = prompt or ""
    if not delta:
        return p
    for a, b in delta.get("replace") or []:
        if not a:
            continue
        # W38（11-04）：编译器的参考图标注句（“图N是……。”）是 preflight I6 逐字核对的，不许改——原来 replace 命中标注句
        # （ep01 S8：“图3是…黑色薄透丝袜…必须与图3完全一致”）→ 每次重出 I6 挡、一张都出不来。只改标注句以外的第一处；只出现在标注里 = 不改
        guard = [m.span() for m in _REF_NOTE.finditer(p)]
        i = p.find(a)
        while i >= 0 and any(s0 <= i < e0 for s0, e0 in guard):
            i = p.find(a, i + 1)
        if i >= 0:
            p = p[:i] + b + p[i + len(a):]
    add = (delta.get("append") or "").strip().rstrip("，,。")
    if add and add not in p:
        tail = "，无字幕、无文字、无水印"
        p = p.replace(tail, f"，{add}{tail}", 1) if tail in p else f"{p.rstrip('，,。')}，{add}"
    return p


def review_round(shot_id: str, kind: str, image: str, prompt: str, references: list[str] | None,
                 contract: dict | None, history: list[dict] | None = None, *, chat=None, vlm: dict | None = None) -> dict:
    """一轮完整记录（写进 take.params.vqa_rounds[]）：{round, vlm_text, vlm_defects, judge, prompt_delta, next_prompt, outcome}"""
    from . import client
    from . import contract as VQ
    rnd = len(history or []) + 1
    vlm = vlm or client.inspect_image(image, prompt, references)
    VQ.remember(image, vlm)
    if vlm.get("error"):
        return {"round": rnd, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "vlm_error": vlm["error"], "outcome": "untested"}
    desc, defects = rubric.describe(vlm)
    j = judge(shot_id, kind, prompt, vlm, contract, rnd=rnd, history=history, chat=chat)
    nxt = apply_delta(prompt, j.get("prompt_delta")) if j["verdict"] == "fail" and j.get("action") == "reprompt" else None
    return {"round": rnd, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "vlm_key": vlm.get("key"), "vlm_text": desc,
            "vlm_defects": defects, "judge": j, "prompt_delta": j.get("prompt_delta"), "next_prompt": nxt,
            "outcome": "pass" if j["verdict"] == "pass" else ("rerun" if nxt else j.get("action", "owner")),
            "max_rounds": int((cfg().get("judge") or {}).get("max_rounds", 3))}
