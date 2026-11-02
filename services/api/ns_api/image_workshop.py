"""图像工坊后端路由（FILMUI，项目方 11-02 12:5x：“为什么没有 UI，做了一半也没做完？”；总调度 13:0x 授权，CONSENT 记在总调度名下）。

GET  /api/image-workshop/bases     基座列表 + 就绪状态（唯一来源：tools/imglab/bases_api.py → data/ab/imglab/bases_status.json）
GET  /api/image-workshop/history?shot=epNN-SN
                                   本镜在图像工坊出过的图（data/ab/workshop/takes.jsonl，只读；不写镜头 takes.json）
POST /api/image-workshop/jobs      非 Qwen 基座出图（MOSS / Klein）：P1 先返回 501 + 原因，不做假出图。
                                   Qwen-Image 2.1（S★ R0）出图走现有 POST /api/shots/{id}/frame-jobs {scope:"ab", experiment:"workshop"}
                                   ——结果只进 data/ab/workshop/，不写镜头账本、不设当前（“采用到镜头”等结构问题 #16 一本账，sv-11）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException

ROOT = Path(__file__).resolve().parents[3]
WORKSHOP = ROOT / "data" / "ab" / "workshop" / "takes.jsonl"
router = APIRouter(tags=["image-workshop"])


def _bases_mod():
    p = str(ROOT / "tools" / "imglab")
    if p not in sys.path:
        sys.path.insert(0, p)
    import bases_api  # noqa: PLC0415  IMGLAB 的纯函数模块（不起服务）
    return bases_api


@router.get("/api/image-workshop/bases")
def bases():
    out = []
    for b in _bases_mod().list_bases():
        out.append({k: b.get(k) for k in ("id", "name", "license", "max_refs", "default_preset", "size", "state", "state_detail", "presets", "note", "mode")})
    # 本页 P1 只接通了 Qwen 的出图路径；其余基座就绪也先标“出图接口待接”，前端据此禁用“出图”
    for b in out:
        b["submit"] = "frame_jobs_ab" if b["id"] == "qwen21" else None
    return {"bases": out}


@router.get("/api/image-workshop/history")
def history(shot: str, limit: int = 60):
    if not WORKSHOP.exists():
        return {"items": []}
    items = []
    for line in WORKSHOP.read_text(encoding="utf-8").splitlines():
        try:
            r = json.loads(line)
        except ValueError:  # arch-ok: 坏行跳过（追加写入中途断电），其余照常
            continue
        if r.get("shot") != shot:
            continue
        f = r.get("file")
        items.append({"id": r.get("id"), "seed": r.get("seed"), "file": f, "url": f"/files/{f}" if f else None,
                      "created_at": r.get("created_at"), "seconds": r.get("seconds"), "tier": r.get("tier"),
                      "prompt": r.get("prompt"), "refs": r.get("refs"), "preset": r.get("preset"),
                      "postflight": r.get("postflight")})
    return {"items": items[-limit:][::-1]}


@router.post("/api/image-workshop/jobs")
def jobs(body: dict):
    base = (body or {}).get("base")
    raise HTTPException(501, f"基座 {base} 的出图接口还没接上（IMGLAB bases_api.build_jobs → 出图道，P3）；本版请用 Qwen-Image 2.1")
