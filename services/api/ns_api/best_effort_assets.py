"""资产“尽力版”标记（L-215 块 J 复审第 4 条，PS-MASTER 11-07）：资产换了几种做法都没出来、系统先按尽力版继续的，
在资产页上要看得见（大白话，不说技术词）。

GET /api/assets/best-effort?run=  → {run, items: [{id, target, who, what, mark: "尽力版", say}]}
来源：资产作业（data/pipeline/asset_jobs/<run>/*.json）里 escalated.kind == "best_effort" 的作业（asset_worker.fallback_ladder 写）。
只回文字，不回图 / 提示词。
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

from fastapi import APIRouter

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["assets-best-effort"])
MARK = "尽力版"
_CID = re.compile(r"（[A-Za-z0-9_]+）")


def _aj():
    sp = importlib.util.spec_from_file_location("asset_jobs_for_best_effort", REPO / "tools" / "pipeline" / "asset_jobs.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def items(run: str, root: Path = REPO, jobs: list[dict] | None = None) -> list[dict]:
    out = []
    for j in jobs if jobs is not None else _aj().list_jobs(Path(root), run):
        esc = j.get("escalated") or {}
        if esc.get("kind") != "best_effort":
            continue
        sp = j.get("spec") or {}
        who = sp.get("name") or _CID.sub("", str(j.get("who") or "")) or "这件资产"
        what = {"face": "身份脸", "scene": "场景底图", "sheet": "造型设定图"}.get(str(j.get("kind")), f"单品“{sp.get('label') or ''}”")
        fb = esc.get("fallback") or {}
        say = (f"先借用了造型 {fb.get('look')} 里最像的一张，流程没停；想换随时说一句" if fb
               else "换了几种做法都没出满意的，流程没停；想改随时说一句")
        out.append({"id": j.get("id"), "target": j.get("target"), "who": who, "what": what, "mark": MARK, "say": say})
    return out


@router.get("/api/assets/best-effort")
def get_best_effort(run: str | None = None):
    from ns_api import adult_trigger as AT  # noqa: PLC0415
    r = AT._run_of(run)
    return {"run": r, "items": items(r)}
