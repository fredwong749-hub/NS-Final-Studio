"""
画布上的 H3 提示词（SOP §9A.1）：选来源、拆四块、跑 lint、gpu3 审计与「出视频」闸门。

来源优先级（2026-10-30 与 gpu3 渲染器约定）：
  1. gpu3 同步回来的 compiled.json["h3_prompt"]（或 compiled.json / takes.json 视频版本里以对齐句开头的提示词）→ gpu3 最终
  2. 项目方覆盖 edits.json h3_prompt_override（经 h3-override 接口，带确认原话）→ 剧本＋画布修改
  3. 剧本 **H3提示词**（Shot.h3_prompt）→ 剧本
  4. 笔记本构建器草稿 → 笔记本草稿（剧本缺 H3提示词）
提示词哈希一律 = sha256(提示词的 UTF-8 原文，不做任何规范化)，与 gpu3 status.json audit.prompt_sha 同一定义。
video_negative 不再显示（cfg 1 没有负向分支）；旧版中文视频提示词只作 legacy_video_prompt。
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from ns_agent import h3_prompt as H3B
from ns_schema.h3_lint import ALIGN_PREFIX, FIELDS, failed_rules, lint_h3, lint_ok, parse_h3

from ns_api import readiness as RD

SOURCE_LABEL = {"gpu3": "gpu3 最终", "script": "剧本", "laptop": "笔记本草稿（剧本缺 H3提示词）"}
AUDIT_KEYS = ("verdict", "failures", "warnings", "not_checked", "overrides", "invalid_overrides", "overridden",
              "h3_edit", "h3_field", "prompt_sha", "at", "version", "rules", "blocked")


def sha256_text(text: str | None) -> str | None:
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


# ---------------------------------------------------------------- 文档链接（D）

def rule_href(rule_id: str) -> str:
    return f"/api/docs/rule_ids#{rule_id}"


def sop_href(sop_ref: str | None) -> str | None:
    """“SOP §9A.1” / “§6 #7” / “SOP §9A.3；§6 表” → SOP_production 对应小节锚点"""
    m = re.search(r"§\s*(\d+[A-Z]?(?:\.\d+)*)", sop_ref or "")
    return f"/api/docs/SOP_production#sec-{m.group(1)}" if m else None


def with_links(results: list[dict]) -> list[dict]:
    for r in results:
        r["rule_href"] = rule_href(r["rule_id"])
        r["sop_href"] = sop_href(r.get("sop_ref"))
    return results


# ---------------------------------------------------------------- gpu3 侧

def video_take(takes: dict | None) -> dict | None:
    """gpu3 takes.json 当前（或最新）视频版本的提示词与哈希"""
    ts = [t for t in (takes or {}).get("takes") or [] if t.get("stage") == "video"]
    if not ts:
        return None
    n = ((takes or {}).get("active") or {}).get("video")
    t = next((x for x in ts if x.get("n") == n), None) or max(ts, key=lambda x: x.get("n") or 0)
    prompt = t.get("prompt") or ""
    sha = t.get("prompt_sha256")
    return {"n": t.get("n"), "prompt": prompt, "frames": t.get("frames"),
            "prompt_sha256": sha or sha256_text(prompt),
            "prompt_sha256_source": "takes.json" if sha else "computed",
            "is_h3": prompt.startswith(ALIGN_PREFIX)}


def gpu3_state(shot_id: str, slug: str) -> dict:
    """gpu3 镜像：{text, where, take, overrides(set), audit(dict|None)}"""
    d = RD.shot_gpu3_dir(shot_id, slug)
    compiled = _read(d / "compiled.json") or {}
    take = video_take(_read(d / "takes.json"))
    status = _read(d / "status.json") or {}
    audit = status.get("audit") if isinstance(status, dict) and isinstance(status.get("audit"), dict) else None
    ovr = {str(o.get("rule_id")) for o in ((audit or {}).get("overrides") or [])
           if isinstance(o, dict) and o.get("rule_id") and str(o.get("owner_quote") or "").strip()}
    text, where = None, None
    if isinstance(compiled, dict):
        if isinstance(compiled.get("h3_prompt"), str) and compiled["h3_prompt"].strip():
            text, where = compiled["h3_prompt"], "compiled.json h3_prompt"
        else:
            for k, v in compiled.items():
                if isinstance(v, str) and v.startswith(ALIGN_PREFIX):
                    text, where = v, f"compiled.json {k}"
                    break
    if text is None and take and take["is_h3"]:
        text, where = take["prompt"], f"takes.json video v{take['n']}"
    return {"text": text, "where": where, "take": take, "overrides": ovr, "audit": audit}


def audit_view(audit: dict | None) -> dict | None:
    """gpu3 status.json audit（C）：原样给出约定字段，规则号带文档链接"""
    if not audit:
        return None
    out = {k: audit.get(k) for k in AUDIT_KEYS if k in audit}
    for k in ("failures", "warnings", "overrides", "invalid_overrides", "overridden"):
        items = out.get(k) or []
        if isinstance(items, list):
            out[k] = [{**x, "rule_href": rule_href(str(x.get("rule_id"))), "sop_href": sop_href(x.get("sop_ref"))}
                      if isinstance(x, dict) and x.get("rule_id") else x for x in items]
    return out


def video_gate(audit: dict | None, prompt_sha: str | None) -> dict:
    """「出视频」：gpu3 audit.verdict == pass 且 audit.prompt_sha == 画布当前提示词的 sha256"""
    reasons = []
    if not audit:
        reasons.append("gpu3 还没有本镜审计（status.json audit）")
    else:
        if audit.get("verdict") != "pass":
            reasons.append(f"gpu3 审计未通过（verdict={audit.get('verdict')!r}）")
        if not audit.get("prompt_sha"):
            reasons.append("审计里没有 prompt_sha")
        elif audit.get("prompt_sha") != prompt_sha:
            reasons.append("审计的提示词与画布当前提示词不一致（prompt_sha 不同），等 gpu3 重新审计")
    return {"ok": not reasons, "reasons": reasons, "prompt_sha": prompt_sha,
            "audit_prompt_sha": (audit or {}).get("prompt_sha")}


# ---------------------------------------------------------------- 覆盖

def script_sha(s) -> str | None:
    """剧本 **H3提示词** 的 sha256（项目方覆盖的 base_sha 与它比对；剧本没有该字段 → None）"""
    return sha256_text(getattr(s, "h3_prompt", None))


def override_info(s, edit) -> dict | None:
    """项目方覆盖的元数据；stale = 剧本 **H3提示词** 在覆盖之后变了（含：原来没有、现在有）"""
    ov = getattr(edit, "h3_prompt_override", None)
    if not ov:
        return None
    d = ov.model_dump()
    return {**{k: v for k, v in d.items() if k != "text"}, "present": True,
            "based_on": "script" if ov.script_sha else "laptop",
            "stale": ov.script_sha != script_sha(s), "current_script_sha": script_sha(s),
            "delivered": bool(ov.delivery and ov.delivery.ok)}


def blocks(text: str) -> dict:
    p = parse_h3(text)
    f = p["fields"]
    return {"alignment": p["align"], "body": f.get(FIELDS[0], ""), "soundscape": f.get(FIELDS[1], ""),
            "music": f.get(FIELDS[2], "")}


def lint(text: str, s, frames: int | None, intimate: bool, waived: set[str] = frozenset()) -> list[dict]:
    res = lint_h3(text, frames=frames, intimate=intimate, **H3B.lint_inputs(s))
    for r in res:
        r["overridden"] = r["rule_id"] in waived and not r["ok"]
    return with_links(res)


def view(s, compiled, edit, slug: str, intimate: bool) -> dict:
    """摘要 / 详情里的 H3 字段"""
    g = gpu3_state(s.id, slug)
    oi = override_info(s, edit)
    ovr = g["overrides"]
    if g["text"]:
        text, src, frames = g["text"].strip("\n"), "gpu3", (g["take"] or {}).get("frames") or compiled.h3_frames
        label, where = SOURCE_LABEL["gpu3"], g["where"]
    elif oi:
        text, src, frames = edit.h3_prompt_override.text, "owner_edit", compiled.h3_frames
        label = ("剧本" if oi["based_on"] == "script" else "笔记本草稿") + "＋画布修改" \
            + ("（草稿，未通过 §9A）" if oi["status"] != "renderable" else "") \
            + ("（剧本已更新，需重新确认）" if oi["stale"] else "")
        where = f"edits.json h3_prompt_override（项目方 {oi['at']}）"
    else:
        text, src, frames = compiled.video_prompt, compiled.h3_prompt_source or "laptop", compiled.h3_frames
        label = SOURCE_LABEL.get(src, src)
        where = "剧本 **H3提示词**" if src == "script" else "ns_agent.h3_prompt 构建器"
    results = lint(text, s, frames, intimate, ovr)
    sha = sha256_text(text)
    reqs = [r.model_dump() for r in getattr(edit, "audit_override_requests", []) or []]
    return {
        "h3_prompt": text,
        "h3_prompt_sha256": sha,            # sha256(UTF-8 原文)，与 gpu3 audit.prompt_sha 同一定义
        "h3_prompt_source": src,
        "h3_prompt_source_label": label,
        "h3_prompt_where": where,
        "h3_blocks": blocks(text),
        "h3_frames": frames,
        "h3_sss": f"{frames / 24:.2f}" if frames else None,
        "h3_lint": results,
        "h3_lint_ok": lint_ok(results, ovr),
        "h3_failed": failed_rules(results, ovr),
        "h3_overrides": sorted(ovr),
        "h3_missing": list(getattr(compiled, "h3_missing", []) or []) if src in ("script", "laptop") else [],
        # 配乐来源（编译器 resolve_music：edit | script | episode | none）；gpu3 / 项目方覆盖版本按其原文
        "h3_music_source": getattr(compiled, "video_music_source", None) if src in ("script", "laptop") else src,
        "h3_editable": True,         # 只有项目方经 h3-override 接口（带确认原话）能改
        "h3_take": g["take"],
        "h3_override": oi,
        "h3_override_stale": bool(oi and oi["stale"]),
        # 项目方改的起点：已有（未过期的）覆盖 > 剧本 / 笔记本草稿（不是 gpu3 版本）
        "h3_edit_base": blocks(edit.h3_prompt_override.text if oi and not oi["stale"]
                               else (getattr(compiled, "h3_base_prompt", "") or compiled.video_prompt)),
        "gpu3_audit": audit_view(g["audit"]),
        "video_gate": video_gate(g["audit"], sha),
        "audit_override_requests": reqs,
    }


def compose_override(base_text: str, body: str | None, soundscape: str | None) -> str:
    """在起点文本上换正文 / 环境声（对齐句、配乐保持起点原文；配乐在「配乐」字段改）；起点不是 H3 结构时报错"""
    if not (base_text or "").startswith(ALIGN_PREFIX):
        raise ValueError("起点不是 H3 四块结构")
    out = base_text
    if body is not None and body.strip():
        out = H3B.replace_field(out, FIELDS[0], body)
    if soundscape is not None and soundscape.strip():
        out = H3B.replace_field(out, FIELDS[1], soundscape)
    return out
