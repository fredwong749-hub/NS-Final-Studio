"""
按集运行（项目方选卡）：POST /api/gpu3/projects/{slug}/episodes/{ep}/run、GET …/run/{run_id}、POST …/run/{run_id}/cancel。
调度器停用期间由项目方决定用哪张卡：桥只做资格判断、写 lend 文件、把合格项追加进队列、记录 run；真正干活的是系列渲染器
（按 {step, gpu} 消费队列 —— 渲染器侧另行实现）。
"""
from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

from .models import now
from .sources import load_json, read_jsonl

STEPS = ("frames", "video", "4k")
S2_RULES = {"R-C4", "R-C5"}          # rule_ids.md 中 sop_ref = ★1 S2 的就绪规则


class RunError(Exception):
    def __init__(self, status: int, detail):
        super().__init__(str(detail))
        self.status, self.detail = status, detail


RESERVE_SUFFIX = "render-reserve"   # train.lock 的 by 以此结尾 = 专为项目方渲染预留的卡（如 ep02-render-reserve），可按集运行


def lock_holder(lock_dir: Path, gpu: int) -> dict | None:
    """gpu.lock.gpuN（pid 已死视为过期，不算占用）、lend.gpuN（存在即占用）或 train.lock.gpuN（训练 / 写作模型占着卡；
    封板修复：以前不查它，按集运行会把活排到正在训 LoRA 的卡或 Qwen 写作模型的卡上。by=*render-reserve 的预留锁除外）。"""
    tl = lock_dir / f"train.lock.gpu{gpu}"
    if tl.exists():
        try:
            text = tl.read_text(errors="replace").strip()
        except OSError:
            text = ""
        try:
            by = str((json.loads(text) or {}).get("by") or "")
        except (ValueError, AttributeError):
            by = ""
        if not by.endswith(RESERVE_SUFFIX):
            return {"file": str(tl), "text": text[:300]}
    for name in (f"gpu.lock.gpu{gpu}", f"lend.gpu{gpu}"):
        p = lock_dir / name
        if not p.exists():
            continue
        try:
            text = p.read_text(errors="replace").strip()
        except OSError:
            text = ""
        m = re.match(r"pid:(\d+)", text)
        if m and Path("/proc").exists() and not Path(f"/proc/{m.group(1)}").exists():
            continue                     # 过期锁
        return {"file": str(p), "text": text[:300]}
    return None


def timeline_reviews(path: Path | None) -> dict[str, list[str]]:
    """state_timeline.json → {shot_id: review_reasons}，只含 needs_review 的镜头。"""
    d = load_json(path, None) if path else None
    if not isinstance(d, dict):
        return {}
    shots = d.get("shots") or []
    items = shots.items() if isinstance(shots, dict) else ((s.get("shot_id"), s) for s in shots if isinstance(s, dict))
    return {k: (v.get("review_reasons") or ["needs_review"]) for k, v in items if k and v.get("needs_review")}


def timeline_s2(path: Path | None) -> dict[str, list[str]]:
    """state_timeline.json → {shot_id: s2_blockers}，只含 s2_ready 为 false 的镜头（封板修复：以前桥不读 s2_ready，
    笔记本判“S2 未放行”的镜头在 gpu3 仍显示可出首帧）。没有 s2_ready 字段的旧时间线不拦。"""
    d = load_json(path, None) if path else None
    if not isinstance(d, dict):
        return {}
    shots = d.get("shots") or []
    items = shots.items() if isinstance(shots, dict) else ((s.get("shot_id"), s) for s in shots if isinstance(s, dict))
    return {k: [str(x) for x in (v.get("s2_blockers") or ["s2_not_ready"])] for k, v in items
            if k and isinstance(v, dict) and v.get("s2_ready") is False}


def _rid(f) -> str:
    return f.get("rule_id") if isinstance(f, dict) else str(f)


def shot_items(ep: int, shots: list[dict], shot_dirs: dict[str, Path], steps: list[str], *, red_episode: bool,
               reviews: dict[str, list[str]], qa_pass: bool, adult_shots: set[str] | None = None,
               s2_blocked: dict[str, list[str]] | None = None) -> list[dict]:
    """shots = ShotRenders dict（含 audit / shot_state / video_gate / takes / active）。
    adult_shots = 剧本 JSON 里 adult=True 的镜号；只用于 detail 说明，不再据此拦任何镜头
    （2026-10-30 项目方取消成人过滤器）。"""
    out = []
    adult_shots = adult_shots or set()
    for sh in shots:
        sid = sh["shot"]
        d = shot_dirs.get(sid)
        st = (load_json(d / "status.json", {}) or {}) if d else {}
        comp = (load_json(d / "compiled.json", {}) or {}) if d else {}
        audit = st.get("audit") if isinstance(st.get("audit"), dict) else {}
        blocked = audit.get("blocked") or st.get("blocked")
        adult = bool(comp.get("adult")) or sid in adult_shots
        red_note = []
        if blocked:
            red_note.append(f"blocked: {blocked}")
        if red_episode:
            red_note.append("🔴 本集")
        if adult:
            red_note.append("adult")
        if "frames" in steps:
            r = []
            fails = audit.get("failures") or []
            s2 = sorted({_rid(f) for f in fails if _rid(f) in S2_RULES or "★1 S2" in str((f or {}).get("sop_ref", "") if isinstance(f, dict) else "")})
            s2 += [f"timeline:{b}" for b in (s2_blocked or {}).get(sid, [])]   # 笔记本 state_timeline 的 S2 判定
            if s2:
                r.append("not_s2_ready")
            if st.get("owner") != "gpu3":
                r.append("owner_not_gpu3")
            if sid in reviews:
                r.append("needs_review")
            out.append({"shot": sid, "step": "frames", "eligible": not r, "reasons": r,
                        "detail": {"s2_rules": s2, "explicit": red_note, "owner": st.get("owner"),
                                   "review_reasons": reviews.get(sid, [])}})
        if "video" in steps:
            r = []
            if not (sh.get("video_gate") or {}).get("video_ok"):
                r.append("video_gate_false")
            act = sh.get("active") or {}
            has_first = bool(act.get("image")) or any(t["stage"] == "image" for t in sh.get("takes", []))
            has_last = bool(d and ((d / "last_target.png").exists() or (d / "last.png").exists())) or bool(
                (sh.get("active_video") or {}).get("last_target")) or bool(st.get("keyframe_pair"))
            if not (has_first and has_last):
                r.append("no_keyframes")
            out.append({"shot": sid, "step": "video", "eligible": not r, "reasons": r,
                        "detail": {"video_gate": sh.get("video_gate"), "first_frame": has_first, "last_frame": has_last,
                                   "explicit": red_note}})
    if "4k" in steps:
        r = [] if qa_pass else ["qa_not_pass"]
        out.append({"shot": f"ep{ep:02d}", "step": "4k", "eligible": not r, "reasons": r, "detail": {}})
    return out


def counts(items: list[dict]) -> dict:
    c = {"total": len(items), "eligible": sum(i["eligible"] for i in items)}
    c["ineligible"] = c["total"] - c["eligible"]
    by: dict[str, dict] = {}
    for i in items:
        b = by.setdefault(i["step"], {"eligible": 0, "ineligible": 0})
        b["eligible" if i["eligible"] else "ineligible"] += 1
    reasons: dict[str, int] = {}
    for i in items:
        for x in i["reasons"]:
            reasons[x] = reasons.get(x, 0) + 1
    return {**c, "by_step": by, "reasons": reasons}


def new_run_id(ep: int) -> str:
    return f"run-ep{ep:02d}-{uuid.uuid4().hex[:8]}"


def write_json(p: Path, data) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(f".{p.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def item_states(run: dict, queue_state: dict) -> list[dict]:
    out = []
    for it in run.get("items", []):
        q = queue_state.get(it["id"]) or {}
        out.append({**it, "state": q.get("state", "unknown"), "updated_at": q.get("at"), "error": q.get("error"),
                    "takes": q.get("takes", [])})
    return out


def lend_names_run(lock_dir: Path, gpu: int, run_id: str) -> bool:
    p = lock_dir / f"lend.gpu{gpu}"
    try:
        return run_id in p.read_text(errors="replace")
    except OSError:
        return False


def events_for(events_path: Path, ids: set[str]) -> list[dict]:
    return [e for e in read_jsonl(events_path) if e.get("id") in ids]
