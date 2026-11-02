"""整集“当前最新预览”接口（ASSEMBLY 11-02，项目方 16:4x：连播本集要看真正拼好的整集）。

    GET /api/episodes/{n}/preview → {url, srt_url, built_at, shots:[{shot, index, kind: video|placeholder|best_effort,
                                    start_s, duration_s}], duration_s, stale, building, eta_s}

文件由 tools/assemble_series.py --preview 产出（data/renders/epNN/_final/preview_latest.mp4 + _manifest.json），
infra_watchdog 每拍调 sweep() 自动重拼；stale / building / eta 来自 data/state/preview_sweep.json。
本接口只读，不拼片。
"""
from __future__ import annotations

from ns_api import run_paths as _RP   # K-OPS-F24：渲染根目录按当前剧（V1 已归档，不在网页显示）
import json
import time

from fastapi import APIRouter, HTTPException

from ns_render import pipeline as P

router = APIRouter(tags=["preview"])


def _jl(p, d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


@router.get("/api/episodes/{n}/preview")
def episode_preview(n: int):
    fin = _RP.renders_for_data(P.DATA) / f"ep{n:02d}" / "_final"
    man = _jl(fin / "preview_latest_manifest.json")
    sw = ((_jl(P.DATA / "state" / "preview_sweep.json", {}) or {}).get("eps") or {}).get(str(n), {})
    if not man or not (fin / "preview_latest.mp4").is_file():
        if sw.get("building"):
            return {"url": None, "building": True, "stale": True, "eta_s": sw.get("eta_s"), "shots": []}
        raise HTTPException(404, "这一集还没有拼好的预览（等巡检拼，或手动跑 tools/assemble_series.py epNN --preview）")
    mt = int((fin / "preview_latest.mp4").stat().st_mtime)
    eta = None
    if sw.get("building"):
        eta = max(30, int(float(sw.get("eta_s") or 150) - (time.time() - float(sw.get("build_started") or time.time()))))
    return {
        "url": f"/files/renders/ep{n:02d}/_final/preview_latest.mp4?v={mt}",
        "srt_url": f"/files/renders/ep{n:02d}/_final/preview_latest.srt?v={mt}",
        "built_at": man.get("built_at_iso"), "built_ts": man.get("built_at"),
        "duration_s": man.get("duration_s"), "bgm": man.get("bgm"),
        "video_shots": man.get("video_shots"), "best_effort_shots": man.get("best_effort_shots"),
        "placeholder_shots": man.get("placeholder_shots"),
        "shots": [{"shot": r["shot"], "index": r["index"], "kind": r["kind"], "start_s": r.get("start_s"),
                   "duration_s": r.get("duration_s")} for r in man.get("shots", [])],
        "stale": bool(sw.get("stale")) or bool(sw.get("building")),
        "building": bool(sw.get("building")), "eta_s": eta,
    }
