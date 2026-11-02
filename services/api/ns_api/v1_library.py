"""Version 1 视频库（只读）：GET /api/v1-library。V1 = runs.json 的 legacy_unprefixed_run，原地冻结（L-125），旧的不带前缀路径 data/renders。
只列“当前版视频文件真的在盘上”的镜头；不写任何文件，不提供任何修改入口；V2 页面不读这里。"""
from __future__ import annotations

import json
import re

from fastapi import APIRouter

from ns_api import v1_guard as G

router = APIRouter(tags=["v1-library"])


def build(renders=None) -> dict:
    base = renders or (G.ROOT / "data" / "renders")
    eps: dict[int, list[dict]] = {}
    for d in sorted(base.glob("ep*/S*")):
        m, s = re.fullmatch(r"ep(\d+)", d.parent.name), re.fullmatch(r"S(\d+)", d.name)
        if not (m and s and (d / "takes.json").is_file()):
            continue
        try:
            t = json.loads((d / "takes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):  # arch-ok: 单镜 takes.json 读不到只跳过这一镜，视频库少一镜可见
            continue
        n = (t.get("active") or {}).get("video")
        cur = next((x for x in t.get("takes") or [] if x.get("stage") == "video" and x.get("n") == n), None)
        f = (cur or {}).get("file")
        if not f or not (G.ROOT / "data" / f).is_file():
            continue
        eps.setdefault(int(m.group(1)), []).append({"id": f"ep{int(m.group(1)):02d}-S{int(s.group(1))}", "index": int(s.group(1)), "n": n, "video_url": "/v1-files/" + f.replace("\\", "/")})
    for rows in eps.values():
        rows.sort(key=lambda r: r["index"])
    runs = G._runs()
    leg = runs.get("legacy_unprefixed_run")
    meta = (runs.get("runs") or {}).get(leg, {})
    return {"run": leg, "label": "Version 1 视频库", "readonly": True, "frozen_at": meta.get("frozen_at"),
            "total": sum(len(v) for v in eps.values()), "episodes": [{"ep": n, "shots": rows} for n, rows in sorted(eps.items())]}


@router.get("/api/v1-library")
def v1_library():
    return build()
