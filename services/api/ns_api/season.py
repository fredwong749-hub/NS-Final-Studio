"""全剧总览（UIRSI 2026-11-01，项目方：“之前更容易看到整部剧里每一个 episode、每一个镜头之间的关系……把它拉回来，也思考一下怎样做逻辑更好”）。

  GET /api/season   全季结构（只读剧本 + 版本表）：每集标题、场景；每镜 景别 · 场景 · 出场人物（在画 / 局部 / 画外）·
                    衔接（换场 / 同场换机位 / 接力 + 承接什么）· 换造型点 · 时长；没有当前首帧时给最新一张合格候选的图址（缩略用）。
状态（首帧 / 尾帧 / 视频 / 通过）由前端从集摘要（/api/episodes/summary，store 轮询）实时合上，不在这里重复算。
"""
from __future__ import annotations

import json
import re
from pathlib import Path

from fastapi import APIRouter

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["season"])
SIZE_RE = re.compile(r"(大远景|远景|大全景|全景|中全景|中景|中近景|近景|大特写|特写)")
_cache: dict = {"key": None, "val": None}


def _script() -> tuple[dict, float]:
    p = REPO / "data" / "import" / "script_v2.json"
    try:
        return json.loads(p.read_text(encoding="utf-8")), p.stat().st_mtime
    except (OSError, ValueError):
        return {}, 0.0


def _cands(ep: int) -> dict:
    try:
        from ns_api import takes_ui  # noqa: PLC0415
        return takes_ui.candidates(ep).get("shots") or {}
    except Exception:  # noqa: BLE001
        return {}


def _structure(sc: dict) -> list[dict]:
    lib = {x.get("scene_id"): x.get("name") for x in (sc.get("globals") or {}).get("scene_library") or []}
    out = []
    for e in sc.get("episodes") or []:
        n = int(e.get("number") or 0)
        # 换造型点：剧本造型表里 from_shot = 这一镜起换装
        switch: dict[int, list[str]] = {}
        for lk in e.get("looks") or []:
            if lk.get("from_shot"):
                switch.setdefault(int(lk["from_shot"]), []).append(lk.get("character") or "")
        shots = []
        for s in e.get("shots") or []:
            i = int(s.get("index") or 0)
            m = SIZE_RE.search(s.get("img_prompt") or "")
            cast = []
            for c in s.get("cast") or []:
                if isinstance(c, dict):
                    cast.append({"name": c.get("name") or "", "presence": c.get("presence") or ""})
            shots.append({"id": f"ep{n:02d}-S{i}", "index": i, "size": m.group(1) if m else None,
                          "scene_id": s.get("scene_id"), "scene": lib.get(s.get("scene_id")) or s.get("scene_id"),
                          "link": s.get("link") or None, "carry": None if (s.get("link_carry") in (None, "", "无")) else s.get("link_carry"),
                          "cast": cast, "switch": switch.get(i, []),
                          # DATAALIGN（K-UI-D01）：与 /api/episodes 的 duration.seconds 同一规则（剧本没写 = 10 秒兜底，标 default），两页总秒数一致
                          "seconds": s.get("duration") if s.get("duration") is not None else 10,
                          "seconds_source": s.get("duration_source") or ("script" if s.get("duration") is not None else "default"),
                          "adult": bool(s.get("adult"))})
        out.append({"number": n, "title": e.get("title"), "scenes": [lib.get(x) or x for x in e.get("scene_ids") or []],
                    "shots": shots})
    return out


@router.get("/api/season")
def season():
    sc, mt = _script()
    if _cache["key"] != mt:
        _cache.update(key=mt, val=_structure(sc))
    eps = json.loads(json.dumps(_cache["val"]))
    for e in eps:
        c = _cands(e["number"])
        for s in e["shots"]:
            st = (c.get(s["id"]) or {}).get("image") or {}
            ok = [t for t in st.get("takes") or [] if t.get("ok") is not False and not t.get("bad")]
            s["cand_url"] = ok[-1]["url"] if ok and st.get("active") is None else None
            s["cand_n"] = len(ok) if st.get("active") is None else 0
            # UIRSI r40：旧剧本版本的图（剧本更新前出的）不作候选；有它们而没有新图时，格子写“未出（剧本已更新）”
            s["old_script_n"] = sum(1 for t in st.get("takes") or [] if t.get("script") == "old")
            s["status"] = (c.get(s["id"]) or {}).get("status") or {"main": None, "tags": []}
            # 当前版本本身是旧剧本出的（全量重做没撤掉的尾帧等）：前端不显示这张、按“未出（剧本已更新）”处理
            for stg, key in (("image", "first_old"), ("last", "last_old")):
                x = (c.get(s["id"]) or {}).get(stg) or {}
                a = x.get("active")
                s[key] = (a is not None and any(t.get("n") == a and t.get("script") == "old" for t in x.get("takes") or []))                     or x.get("active_quarantined") is not None   # r41：当前版本已隔离
        # UIRSI r40：板块层面（集 + 各阶段）已确认 / 进行中 / 过期 / 未开始，口径同镜头格标签
        try:
            from ns_api import shot_status  # noqa: PLC0415
            e["blocks"] = shot_status.episode_blocks(e["number"], e["shots"])
        except Exception:  # noqa: BLE001
            e["blocks"] = None
    return {"episodes": eps}
