"""项目方已定决策锁（UIRSI r40；起因：项目方 23:57:52–23:58:01 在人物中心 9 秒内连点三次，把林晚造型 A 设定图从 v2_s202
换成 s101，推翻了他自己 21:4x 的决定 L-093，事后说“只是点着看”）。

GET /api/decision-locks   只读：config/owner_decisions.yaml 里“锁住某张资产图”的断言 → 前端换图前一键确认。
  · 设定图：type grep_present、paths 含 sheets_chosen.json、pattern = 文件名片段  → {kind: sheet, match: 片段}
  · 身份脸：type json、file = data/looks/face_overrides.json、path [项目, 人物]、op eq、value = 文件 → {kind: face, cid, match: 文件}
  文案取 decision 里的 L-xxx 编号和“11-01 21:4x”这类时间（大白话：“这张已按你 11-01 21:4x 的决定定为 …”）。
  不改任何东西；决策账本仍以 docs/master/MASTER_PICTURE.md 与 owner_decisions.yaml 为准（RECALL 维护）。
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import APIRouter

router = APIRouter(tags=["decision-locks"])
ROOT = Path(__file__).resolve().parents[3]
OD = ROOT / "config" / "owner_decisions.yaml"
_cache: dict = {"mt": None, "val": []}
L_RE = re.compile(r"L-\d{3}")
WHEN_RE = re.compile(r"\d{2}-\d{2}\s+\d{1,2}:\d[\dx]")


def _locks_from(checks: list) -> list[dict]:
    out = []
    for c in checks or []:
        if not isinstance(c, dict):
            continue
        dec = str(c.get("decision") or "")
        lid = (L_RE.search(dec) or L_RE.search(str(c.get("id") or "")))
        when = WHEN_RE.search(dec)
        base = {"id": c.get("id"), "decision": lid.group(0) if lid else None, "when": when.group(0) if when else None,
                "title": c.get("title") or ""}
        paths = [str(p) for p in c.get("paths") or []]
        if c.get("type") == "grep_present" and any(p.endswith("sheets_chosen.json") for p in paths) and c.get("pattern"):
            out.append({**base, "kind": "sheet", "match": str(c["pattern"]).strip("'\"")})
        elif c.get("type") == "json" and str(c.get("file") or "").endswith("face_overrides.json") and c.get("op") == "eq" \
                and isinstance(c.get("value"), str) and len(c.get("path") or []) == 2:
            out.append({**base, "kind": "face", "cid": c["path"][1], "match": c["value"]})
    return out


def locks() -> list[dict]:
    try:
        mt = OD.stat().st_mtime
    except OSError:
        return []
    if _cache["mt"] != mt:
        import yaml  # noqa: PLC0415
        try:
            d = yaml.safe_load(OD.read_text(encoding="utf-8")) or {}
        except Exception:  # noqa: BLE001
            d = {}
        _cache.update(mt=mt, val=_locks_from(d.get("checks") or []))
    return _cache["val"]


@router.get("/api/decision-locks")
def decision_locks():
    return {"locks": locks()}
