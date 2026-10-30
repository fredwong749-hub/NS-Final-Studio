"""
逐镜 H3 / 审计数据（读）与两项人工操作（写）：
- 读：status.json.audit、status.json 的状态字段、compiled.json 的 h3_*、edits.json 的 h3_prompt_override、active 视频 take。
- 写 1：h3_edit → renders_gpu3/epXX/SN/edits.json 的 h3_prompt_override（原子写）+ edits_history.jsonl；只做 lint，不渲染。
- 写 2：override → 追加到 edits.json 的 audit_override_requests（rule_id 必须在 docs/audit/rule_ids.md 里，且有项目方原话）；
  不写 status.json —— 由 gpu3 的 shot_audit 合并进 audit.overrides。
规则编号表与 lint 都来自同步过去的仓库（ns_schema/h3_lint.py、docs/audit/rule_ids.md），这里不复制规则。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import threading
from collections import Counter
from pathlib import Path

from .models import now
from .sources import load_json

_lock = threading.Lock()
_lint_cache: dict[tuple[str, float], object] = {}

STATE_KEYS = ("state", "blocked", "owner", "scene_id", "segment_id", "continuity", "bible_version")
AUDIT_KEYS = ("version", "verdict", "failures", "warnings", "not_checked", "overrides", "invalid_overrides",
              "h3_edit", "prompt_sha")
H3_KEYS = ("h3_prompt", "h3_prompt_sha256", "h3_prompt_source", "h3_prompt_base_sha256")


def sha256(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def atomic_write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, p)


# ------------------------------------------------------------------ 读
def shot_audit(shot_dir: Path, takes: list, active: dict) -> dict:
    """takes = [(TakeOut, paths)]（renders_gpu3 来源）；返回画布需要的 H3/审计块。"""
    st = load_json(shot_dir / "status.json", {}) or {}
    comp = load_json(shot_dir / "compiled.json", {}) or {}
    edits = load_json(shot_dir / "edits.json", {}) or {}
    raw = load_json(shot_dir / "takes.json", {}) or {}
    a = st.get("audit") if isinstance(st.get("audit"), dict) else None
    audit = {k: a.get(k) for k in AUDIT_KEYS} if a else None
    h3 = {k: comp.get(k) for k in H3_KEYS}
    ov = edits.get("h3_prompt_override") if isinstance(edits.get("h3_prompt_override"), dict) else None
    h3["override"] = ov
    h3["effective_sha256"] = (ov or {}).get("sha256") or comp.get("h3_prompt_sha256") or (
        sha256(comp["h3_prompt"]) if comp.get("h3_prompt") else None)
    vid = None
    n = (active or {}).get("video")
    for t in raw.get("takes", []):
        if t.get("stage") == "video" and (t.get("n") == n or n is None):
            vid = t
    active_video = None
    if vid:
        active_video = {"n": vid.get("n"), "prompt": vid.get("prompt"),
                        "prompt_sha256": vid.get("prompt_sha256") or (sha256(vid["prompt"]) if vid.get("prompt") else None),
                        "reference": vid.get("reference"), "references": vid.get("references"),
                        "last_target": vid.get("last_target") or vid.get("last_frame_target"),
                        "frames": vid.get("frames")}
    state = {k: st.get(k) for k in STATE_KEYS}
    if audit is not None:
        audit["override_requests"] = edits.get("audit_override_requests") or []
    elif edits.get("audit_override_requests"):
        audit = {"override_requests": edits["audit_override_requests"]}
    eff = h3["effective_sha256"]
    gate = {"verdict": (audit or {}).get("verdict"), "prompt_sha": (audit or {}).get("prompt_sha"), "effective_sha256": eff,
            "blocked": state.get("blocked")}
    gate["video_ok"] = bool(gate["verdict"] == "pass" and gate["prompt_sha"] and gate["prompt_sha"] == eff and not gate["blocked"])
    return {"audit": audit, "h3": h3, "shot_state": state, "active_video": active_video, "video_gate": gate}


def audit_class(st: dict) -> str:
    """pass / fail / blocked / none（blocked 优先：例如 explicit_content_not_supported）"""
    if st.get("blocked") or st.get("state") == "blocked":
        return "blocked"
    v = ((st.get("audit") or {}).get("verdict") or "").lower() if isinstance(st.get("audit"), dict) else ""
    return v if v in ("pass", "fail") else "none"


def episode_audit_summary(shot_dirs: list[Path]) -> dict:
    counts = Counter({"pass": 0, "fail": 0, "blocked": 0, "none": 0})
    rules: Counter = Counter()
    for d in shot_dirs:
        st = load_json(d / "status.json", {}) or {}
        counts[audit_class(st)] += 1
        a = st.get("audit") if isinstance(st.get("audit"), dict) else {}
        for f in a.get("failures") or []:
            rid = f.get("rule_id") if isinstance(f, dict) else str(f)
            if rid:
                rules[rid] += 1
    return {**dict(counts), "top_failures": [{"rule_id": r, "count": c} for r, c in rules.most_common(3)]}


# ------------------------------------------------------------------ 规则表 / lint
def rule_ids(path: Path | None) -> dict[str, bool]:
    """rule_id → 是否有效（标“作废”的为 False）。读 markdown 表格第一列。"""
    out: dict[str, bool] = {}
    if not path or not path.exists():
        return out
    for ln in path.read_text(encoding="utf-8", errors="replace").splitlines():
        m = re.match(r"^\|\s*([A-Z][A-Z0-9]*-[A-Z]+\d+[a-z]?)\s*\|", ln)
        if m:
            out[m.group(1)] = "作废" not in ln
    return out


def load_lint(path: Path | None):
    if not path or not path.exists():
        raise FileNotFoundError(f"h3_lint.py 不在 {path}")
    key = (str(path), path.stat().st_mtime)
    if key not in _lint_cache:
        spec = importlib.util.spec_from_file_location(f"h3_lint_{abs(hash(key))}", path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)  # 只用标准库（见 h3_lint.py 文件头）
        _lint_cache.clear()
        _lint_cache[key] = mod
    return _lint_cache[key]


def lint(lint_path: Path | None, text: str, shot_dir: Path, overrides: set[str]) -> dict:
    comp = load_json(shot_dir / "compiled.json", {}) or {}
    st = load_json(shot_dir / "status.json", {}) or {}
    frames = (st.get("video") or {}).get("frames") or comp.get("frames")
    if not frames:
        raw = load_json(shot_dir / "takes.json", {}) or {}
        frames = next((t.get("frames") for t in reversed(raw.get("takes", [])) if t.get("stage") == "video" and t.get("frames")), None)
    mod = load_lint(lint_path)
    results = mod.lint_h3(text, frames=frames, intimate=bool(comp.get("adult")))
    return {"ok": mod.lint_ok(results, overrides), "failed": mod.failed_rules(results, overrides),
            "warnings": mod.failed_rules(results, overrides, level="warn"), "frames": frames,
            "intimate": bool(comp.get("adult")), "results": results, "lint_file": str(lint_path)}


# ------------------------------------------------------------------ 写
def write_h3_edit(shot_dir: Path, text: str, by: str, base_sha: str | None) -> dict:
    with _lock:
        cur = shot_audit(shot_dir, [], {})["h3"]["effective_sha256"]
        if base_sha and cur and base_sha != cur:
            raise ConflictError(f"提示词已被改过（当前 sha {cur[:12]}…，你基于 {base_sha[:12]}…）；请刷新后再改")
        edits = load_json(shot_dir / "edits.json", {}) or {}
        rec = {"text": text, "sha256": sha256(text), "by": by, "at": now(), "base_sha": base_sha or cur}
        edits["h3_prompt_override"] = rec
        atomic_write_json(shot_dir / "edits.json", edits)
        with (shot_dir / "edits_history.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"field": "h3_prompt_override", **rec}, ensure_ascii=False) + "\n")
        return rec


def add_override_request(shot_dir: Path, rule_id: str, owner_quote: str, by: str) -> dict:
    with _lock:
        edits = load_json(shot_dir / "edits.json", {}) or {}
        rec = {"rule_id": rule_id, "owner_quote": owner_quote, "by": by, "at": now()}
        edits["audit_override_requests"] = [*(edits.get("audit_override_requests") or []), rec]
        atomic_write_json(shot_dir / "edits.json", edits)
        with (shot_dir / "edits_history.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps({"field": "audit_override_requests", **rec}, ensure_ascii=False) + "\n")
        return {"request": rec, "requests": edits["audit_override_requests"]}


class ConflictError(Exception):
    pass
