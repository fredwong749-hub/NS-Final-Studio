"""大脑状态（UIUX-LOOP-2 r6，11-06）：总览里一块只读小面板——大脑（BRAIN-FW / 会话内 PS-MASTER）最近决定了什么、给项目方说了什么。

GET /api/brain/status
  → {at, mode:{enabled, dry_run, model, interval_s, word}, status_at, status_age_s,
     decisions:[{at, kind, dry, by, reason, expected, result}]（最新在前，最多 n），
     notes:[{at, level, text}]（data/brain/owner_notes.md 末尾几行，最新在前），
     snapshot:{at, run, age_s, probe_errors, issues_open, idle_lanes}, status_md}
来源只有本机文件：data/brain/STATUS.md（tools/brain/brain_status.py 生成）、decisions.jsonl、owner_notes.md、snapshot.json、config/brain/brain.json。
不连机器、不写文件；读不到哪份就哪部分为空，并在 missing 里写明（页面写“还没有”）。时间 JST（文件里本来就带 +09:00）。
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from fastapi import APIRouter

from ns_api.clock import JST, jst_now_str

ROOT = Path(__file__).resolve().parents[3]
BRAIN = ROOT / "data" / "brain"
CFG = ROOT / "config" / "brain" / "brain.json"
router = APIRouter(tags=["brain-status"])
CACHE_TTL_S = 5.0
_cache: dict = {"t": 0.0, "val": None}
NOTE_RE = re.compile(r"^(\d{2}-\d{2} \d{2}:\d{2}) (🔴|🟡|🟢) BRAIN：(.*)$")
LEVEL = {"🔴": "red", "🟡": "yellow", "🟢": "green"}


def _read(p: Path, missing: list[str]) -> str | None:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:  # arch-ok: 哪份文件没有就记进 missing（响应里带出），面板写“还没有”
        missing.append(p.name)
        return None


def _tail_jsonl(txt: str | None, n: int) -> list[dict]:
    out = []
    for ln in (txt or "").splitlines()[-n:]:
        try:
            d = json.loads(ln)
        except ValueError:  # arch-ok: 只追加日志里的半行跳过，其余照给
            continue
        if isinstance(d, dict):
            out.append(d)
    return out


def _age(p: Path) -> tuple[str | None, int | None]:
    try:
        mt = p.stat().st_mtime
    except OSError:  # arch-ok: 没有文件 = 没有时间（missing 里已记）
        return None, None
    from datetime import datetime  # noqa: PLC0415
    return datetime.fromtimestamp(mt, JST).strftime("%Y-%m-%d %H:%M:%S"), int(time.time() - mt)


def build(root: Path = ROOT, n: int = 8) -> dict:
    """纯函数（tests 用 tmp root）"""
    brain = root / "data" / "brain"
    missing: list[str] = []
    cfg_txt = _read(root / "config" / "brain" / "brain.json", missing)
    try:
        cfg = json.loads(cfg_txt) if cfg_txt else {}
    except ValueError:  # arch-ok: 配置写坏 = 按“没配置”显示，并记进 missing
        cfg, missing = {}, missing + ["brain.json(坏)"]
    enabled, dry = bool(cfg.get("enabled")), bool(cfg.get("dry_run", True))
    mode = {"enabled": enabled, "dry_run": dry, "model": cfg.get("model"), "interval_s": cfg.get("interval_s"),
            "word": ("API 常驻 · " + ("只记不做" if dry else "会动手")) if enabled else "常驻关着 · 由会话内总调度当大脑"}
    dec = _tail_jsonl(_read(brain / "decisions.jsonl", missing), n)
    decisions = []
    for d in reversed(dec):
        p = d.get("params") if isinstance(d.get("params"), dict) else {}
        decisions.append({"at": d.get("at"), "kind": d.get("kind"), "dry": bool(d.get("dry")), "by": d.get("by"),
                          "reason": str(p.get("reason") or "")[:300], "expected": str(p.get("expected_effect") or "")[:200],
                          "result": str(d.get("result") or "")[:200], "rejected": d.get("rejected")})
    notes = []
    for ln in reversed((_read(brain / "owner_notes.md", missing) or "").splitlines()[-n:]):
        m = NOTE_RE.match(ln.strip())
        if m:
            notes.append({"at": m.group(1), "level": LEVEL[m.group(2)], "text": m.group(3)[:400]})
        elif ln.strip():
            notes.append({"at": None, "level": "green", "text": ln.strip()[:400]})
    snap_txt = _read(brain / "snapshot.json", missing)
    try:
        snap = json.loads(snap_txt) if snap_txt else {}
    except ValueError:  # arch-ok: 快照正在被写（半份）= 这一轮没有快照摘要，下次 5 s 后再读
        snap = {}
    iw = snap.get("idle_watch") if isinstance(snap.get("idle_watch"), dict) else {}
    snapshot = {"at": snap.get("at"), "run": snap.get("run"),
                "age_s": int(time.time() - float(snap["t"])) if snap.get("t") else None,
                "probe_errors": list(snap.get("probe_errors") or []),
                "issues_open": len(snap.get("issues_open") or []),
                "idle_lanes": list(iw.get("idle") or iw.get("idle_lanes") or [])} if snap else None
    status_md = _read(brain / "STATUS.md", missing)
    status_at, status_age = _age(brain / "STATUS.md")
    return {"at": jst_now_str(), "mode": mode, "status_at": status_at, "status_age_s": status_age,
            "decisions": decisions, "notes": notes, "snapshot": snapshot, "status_md": status_md, "missing": missing}


@router.get("/api/brain/status")
def brain_status():
    now = time.time()
    if _cache["val"] is not None and now - _cache["t"] < CACHE_TTL_S:
        return _cache["val"]
    out = build()
    _cache.update(t=now, val=out)
    return out
