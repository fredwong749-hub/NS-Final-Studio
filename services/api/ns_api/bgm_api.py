"""整集配乐候选 + 一键换用（BGM10 2026-11-01；链接 P4-BGM，docs/BGM.md）。

  GET  /api/music/{ep}/candidates   本集当前用的配乐 + 其他通过闸门的候选（▶ 地址、度量、谁选的、理由）；
                                    没过闸门的不列出，只给个数（项目方只看通过的候选）
  POST /api/music/{ep}/choose       {"id": "r1_c3"} 换用这一条：重写 data/music/series10/epNN.wav + .json，
                                    meta.json 记历史，写审计（登录即本人，一键生效）；{"undo": true} 换回上一条
数据：tools/bgm/agent.py 产出的 data/music/series10/epNN/meta.json 与 cands/*.flac。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["bgm"])
SHOW = ("duration_s", "clap", "energy_r", "tempo_bpm", "tempo_ok", "vocal_rel_db", "p_vocal", "longest_gap_s", "tags")


def _deliver():
    p = str(REPO / "tools" / "bgm")
    if p not in sys.path:
        sys.path.insert(0, p)
    import deliver  # noqa: PLC0415
    return deliver


def music_dir() -> Path:
    """series10 的配乐目录（有就用它；旧剧 data/music 已隔离）"""
    d = REPO / "data" / "music" / "series10"
    return d if d.is_dir() else REPO / "data" / "music"


def file_url(p: Path) -> str:
    return "/files/" + p.relative_to(REPO / "data").as_posix() + f"?v={int(p.stat().st_mtime)}"


def _meta(ep: int) -> dict:
    p = REPO / "data" / "music" / "series10" / f"ep{ep:02d}" / "meta.json"
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@router.get("/api/music/{ep}/candidates")
def candidates(ep: int):
    st = _meta(ep)
    if not st:
        raise HTTPException(404, f"第 {ep} 集还没有配乐候选")
    chosen = (st.get("chosen") or {}).get("id")
    base = REPO / "data" / "music" / "series10" / f"ep{ep:02d}" / "cands"
    rows, hidden = [], 0
    for c in st.get("candidates") or []:
        f = base / f"{c['id']}.flac"
        if not c.get("gate_pass") or not f.is_file():
            hidden += 1
            continue
        m = c.get("metrics") or {}
        rows.append({"id": c["id"], "round": c.get("round"), "url": file_url(f), "chosen": c["id"] == chosen,
                     "model": c.get("model"), "seed": c.get("seed"), "bpm": c.get("bpm_param"), "flags": c.get("flags") or [],
                     "flags_plain": c.get("flags_plain") or [],
                     "metrics": {k: m.get(k) for k in SHOW}})
    rows.sort(key=lambda r: (not r["chosen"], r["id"]))
    b = st.get("brief") or {}
    last_review = next((r.get("review") for r in reversed(st.get("rounds") or []) if r.get("review")), None) or {}
    return {"episode": ep, "status": st.get("status"), "chosen": st.get("chosen"), "needs_owner_listen": bool(st.get("needs_owner_listen")),
            "brief": {"caption_en": b.get("caption_en"), "bpm": b.get("bpm"), "key": b.get("key"),
                      "instrumentation": b.get("instrumentation"), "mood_arc": b.get("mood_arc"), "sections": b.get("sections")},
            "review": {"reason": last_review.get("reason"), "ranking": last_review.get("ranking"), "model": last_review.get("_model")},
            "rounds": len(st.get("rounds") or []), "candidates": rows, "hidden_failed": hidden,
            "history": st.get("history") or []}


class ChooseBody(BaseModel):
    id: str | None = None
    undo: bool = False


def require_owner(request: Request) -> dict:
    """写操作的身份：没登录 401，不是项目方（查看者等）403。不在 try 里、不兜底成 owner（UIAUDIT P0，verify_bgm10_r1.md）"""
    from ns_api.auth import user_of  # noqa: PLC0415  导入失败 = 服务配置错误，直接 500，不放行
    u = user_of(request)
    if not u:
        raise HTTPException(401, "请先登录再换配乐")
    if u.get("role") != "owner":
        raise HTTPException(403, "只有项目方能换配乐")
    return u


@router.post("/api/music/{ep}/choose")
def choose(ep: int, body: ChooseBody, request: Request):
    u = require_owner(request)            # 换用与撤销同一道检查，先于任何读写
    from ns_api.auth import audit_line  # noqa: PLC0415
    st = _meta(ep)
    if not st:
        raise HTTPException(404, f"第 {ep} 集还没有配乐候选")
    target = body.id
    if body.undo:
        target = (st.get("chosen") or {}).get("previous")
        if not target:
            raise HTTPException(409, "没有上一条可以换回")
    if not target:
        raise HTTPException(400, "要给候选 id")
    who = str(u.get("name") or "")
    try:
        st2 = _deliver().choose(ep, target, by=f"界面：{who}（{u['role']}）",
                                reason="项目方在声音页换用" + ("（撤销）" if body.undo else ""))
    except ValueError as e:
        raise HTTPException(409, str(e)) from e
    except RuntimeError as e:
        raise HTTPException(500, f"换用没成功：{e}") from e
    audit_line({"user": who, "role": u["role"], "action": "bgm_choose", "episode": ep, "candidate": target,
                "previous": (st2.get("chosen") or {}).get("previous"), "undo": body.undo})
    return candidates(ep)
