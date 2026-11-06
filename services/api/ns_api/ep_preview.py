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


def _film_view(film: dict, tl: dict | None) -> dict:
    """整集成片（data/episodes/<run>/epNN_vN.mp4，装配器 timeline.json）→ 和预览同一结构，连播器照常分段 / 跳镜。
    kind：video = 真视频；still / black / placeholder = 占位（灰）；装配器标的 best_effort 单独一色"""
    shots = []
    for r in (tl or {}).get("shots") or []:
        if not r.get("shot"):
            continue
        k = "video" if r.get("kind") == "video" and not r.get("placeholder") else "placeholder"
        if k == "video" and (r.get("best_effort") or "best_effort" in str(r.get("take_policy") or "")):
            k = "best_effort"
        shots.append({"shot": r["shot"], "index": r.get("index"), "kind": k, "start_s": r.get("start_s"), "duration_s": r.get("duration_s")})
    g = film.get("gate") or {}
    return {"url": film["url"], "srt_url": film.get("srt_url"), "built_at": film["at"], "built_ts": film["mtime"],
            "duration_s": film.get("duration_s"), "bgm": ((tl or {}).get("bgm") or {}).get("file") if isinstance((tl or {}).get("bgm"), dict) else None,
            "video_shots": sum(1 for s in shots if s["kind"] == "video"), "best_effort_shots": sum(1 for s in shots if s["kind"] == "best_effort"),
            "placeholder_shots": sum(1 for s in shots if s["kind"] == "placeholder"),
            "shots": shots, "stale": False, "building": False, "eta_s": None,
            "source": "film", "film": {"name": film["name"], "version": film.get("version"), "at": film["at"], "size": film.get("size"),
                                       "kind": g.get("kind") or "unknown", "kind_word": g.get("kind_word") or "整集成片", "word": g.get("word") or "闸门记录还没同步到本机",
                                       "verdict": g.get("verdict"), "missing_n": g.get("missing_n"), "missing": g.get("missing") or [],
                                       "post": g.get("post")}}


@router.get("/api/episodes/{n}/preview")
def episode_preview(n: int):
    from ns_api import cuts as C   # noqa: PLC0415  r12：最新成片口径只在 cuts.latest_film 一处
    fin = _RP.renders_for_data(P.DATA) / f"ep{n:02d}" / "_final"
    man = _jl(fin / "preview_latest_manifest.json")
    sw = ((_jl(P.DATA / "state" / "preview_sweep.json", {}) or {}).get("eps") or {}).get(str(n), {})
    have_pv = bool(man) and (fin / "preview_latest.mp4").is_file()
    # UIUX-LOOP-3 r12：night 合成的整集成片（data/episodes/<run>/epNN_vN.mp4）比巡检拼的 preview_latest 新 → 连播给最新成片，
    # 并带 film.{kind_word, word}（“预览版 · 合成闸门没过：缺 5 镜用占位” / “成片 · 合成闸门通过”），不把占位片冒充成片
    film = C.latest_film(_RP.episodes_for_data(P.DATA), n)
    if film and (not have_pv or float(film["mtime"]) >= (fin / "preview_latest.mp4").stat().st_mtime):
        return _film_view(film, C._tl(_RP.episodes_for_data(P.DATA) / film["name"]))
    if not have_pv:
        if sw.get("building"):
            return {"url": None, "building": True, "stale": True, "eta_s": sw.get("eta_s"), "shots": []}
        raise HTTPException(404, "这一集还没有拼好的预览（等巡检拼，或手动跑 tools/assemble_series.py epNN --preview）")
    mt = int((fin / "preview_latest.mp4").stat().st_mtime)
    eta = None
    if sw.get("building"):
        eta = max(30, int(float(sw.get("eta_s") or 150) - (time.time() - float(sw.get("build_started") or time.time()))))
    try:   # r12：地址按文件真实位置（V2 = renders/<run>/epNN/_final），以前写死 renders/epNN/… = 放的是 V1 的旧预览
        rel = fin.resolve().relative_to(P.DATA.resolve()).as_posix()
    except ValueError:
        rel = f"renders/ep{n:02d}/_final"
    return {
        "url": f"/files/{rel}/preview_latest.mp4?v={mt}",
        "srt_url": f"/files/{rel}/preview_latest.srt?v={mt}",
        "source": "preview", "film": None,
        "built_at": man.get("built_at_iso"), "built_ts": man.get("built_at"),
        "duration_s": man.get("duration_s"), "bgm": man.get("bgm"),
        "video_shots": man.get("video_shots"), "best_effort_shots": man.get("best_effort_shots"),
        "placeholder_shots": man.get("placeholder_shots"),
        "shots": [{"shot": r["shot"], "index": r["index"], "kind": r["kind"], "start_s": r.get("start_s"),
                   "duration_s": r.get("duration_s")} for r in man.get("shots", [])],
        "stale": bool(sw.get("stale")) or bool(sw.get("building")),
        "building": bool(sw.get("building")), "eta_s": eta,
    }
