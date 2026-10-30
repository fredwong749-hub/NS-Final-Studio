"""
画布上的 H3 提示词（SOP §9A.1）：选来源、拆四块、跑 lint。

来源优先级（2026-10-30 与 gpu3 渲染器约定）：
  1. gpu3 同步回来的 compiled.json["h3_prompt"]（或 compiled.json / takes.json 视频版本里以对齐句开头的提示词）→ gpu3 最终
  2. 剧本 **H3提示词**（Shot.h3_prompt；可叠加画布对正文 / 环境声的修改）→ 剧本
  3. 笔记本构建器草稿 → 笔记本草稿（剧本缺 H3提示词）
video_negative 不再显示（cfg 1 没有负向分支）；旧版中文视频提示词只作 legacy_video_prompt。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

from ns_agent import h3_prompt as H3B
from ns_schema.h3_lint import ALIGN_PREFIX, FIELDS, failed_rules, lint_h3, lint_ok, parse_h3

from ns_api import readiness as RD

SOURCE_LABEL = {"gpu3": "gpu3 最终", "script": "剧本", "laptop": "笔记本草稿（剧本缺 H3提示词）"}


def _read(p: Path):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


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
            "prompt_sha256": sha or (hashlib.sha256(prompt.encode("utf-8")).hexdigest() if prompt else None),
            "prompt_sha256_source": "takes.json" if sha else "computed",
            "is_h3": prompt.startswith(ALIGN_PREFIX)}


def gpu3_prompt(shot_id: str, slug: str) -> tuple[str | None, str | None, dict | None, set[str]]:
    """→ (H3 文本, 出处, 视频 take 信息, 项目方豁免的 rule_id)"""
    d = RD.shot_gpu3_dir(shot_id, slug)
    compiled = _read(d / "compiled.json") or {}
    take = video_take(_read(d / "takes.json"))
    status = _read(d / "status.json") or {}
    ovr = {str(o.get("rule_id")) for o in ((status.get("audit") or {}).get("overrides") or [])
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
    return text, where, take, ovr


def blocks(text: str) -> dict:
    p = parse_h3(text)
    f = p["fields"]
    return {"alignment": p["align"], "body": f.get(FIELDS[0], ""), "soundscape": f.get(FIELDS[1], ""),
            "music": f.get(FIELDS[2], "")}


def view(s, compiled, edit, slug: str, intimate: bool) -> dict:
    """摘要 / 详情里的 H3 字段"""
    g_text, g_where, take, ovr = gpu3_prompt(s.id, slug)
    edited = bool(getattr(edit, "h3_body", None) or getattr(edit, "soundscape", None))
    if g_text:
        text, src, frames = g_text.strip("\n"), "gpu3", (take or {}).get("frames") or compiled.h3_frames
        label = SOURCE_LABEL["gpu3"]
    else:
        text, src, frames = compiled.video_prompt, compiled.h3_prompt_source or "laptop", compiled.h3_frames
        label = SOURCE_LABEL.get(src, src) + ("＋画布修改" if edited else "")
    results = lint_h3(text, frames=frames, intimate=intimate, **H3B.lint_inputs(s))
    for r in results:
        r["overridden"] = r["rule_id"] in ovr and not r["ok"]
    return {
        "h3_prompt": text,
        "h3_prompt_source": src,
        "h3_prompt_source_label": label,
        "h3_prompt_where": g_where or ("剧本 **H3提示词**" if src == "script" else "ns_agent.h3_prompt 构建器"),
        "h3_blocks": blocks(text),
        "h3_frames": frames,
        "h3_lint": results,
        "h3_lint_ok": lint_ok(results, ovr),
        "h3_failed": failed_rules(results, ovr),
        "h3_overrides": sorted(ovr),
        "h3_missing": list(getattr(compiled, "h3_missing", []) or []) if src != "gpu3" else [],
        "h3_editable": src != "gpu3",
        "h3_take": take,
    }
