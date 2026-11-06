"""L-209 S2.2 集关闭标记：项目方重新打开 / 标定稿（W-S22，11-07）。

POST /api/owner/episode-reopen {run?, ep, why?}  → 重新打开一集（执行器恢复给它派单，直到出了新一版过闸成片再关闭）。
POST /api/owner/episode-final  {run?, ep, why?}  → 项目方标定稿（不论合成闸门，本集关闭）。
GET  /api/owner/episode-state?run=                 → 各集 closed / why / 最新成片（只读，登录不登录都能看）。
  · 写操作只认登录的项目方本人（auth.user_of → role=owner）；没登录 / 查看令牌 / agent 令牌 → 403，什么都不写。
    总调度按项目方对话指示时走同一函数的 CLI：tools/autopilot/episode_state.py reopen --ep N --by "PS-MASTER（项目方对话 …）"。
  · 先追加审计 data/pipeline/episode_reopen_audit.jsonl，再原子写 data/pipeline/runs/<run>/episode_state.json；
    后台立刻经 resident_sync.push_control 推两台（与 owner_triggers.json 同一通道，复用 adult_trigger.push_now）。
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

REPO = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["owner-episode-state"])


def _es():
    sp = importlib.util.spec_from_file_location("episode_state_api", REPO / "tools" / "autopilot" / "episode_state.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _run_of(run: str | None) -> str:
    from ns_api import adult_trigger as AT  # noqa: PLC0415
    return AT._run_of(run)


def _push() -> None:
    from ns_api import adult_trigger as AT  # noqa: PLC0415
    AT.push_now()


class EpisodeAct(BaseModel):
    run: str | None = None
    ep: int
    why: str = ""


def _owner(request: Request) -> dict:
    from ns_api import auth  # noqa: PLC0415
    u = auth.user_of(request)
    if not u or u.get("role") != "owner":
        raise HTTPException(403, "只有登录的项目方本人能改集的关闭状态")
    return u


@router.get("/api/owner/episode-state")
def get_state(run: str | None = None):
    r = _run_of(run)
    m = _es()
    return {"run": r, "mode": m.mode(REPO), **m.load(r, REPO)}


@router.post("/api/owner/episode-reopen")
def post_reopen(body: EpisodeAct, request: Request):
    u = _owner(request)
    run = _run_of(body.run)
    if body.ep < 1:
        raise HTTPException(400, "集号不对")
    rec = _es().reopen(run, body.ep, u["name"], (body.why or "").strip()[:500] or "项目方要求重新打开", source="owner_api", root=REPO)
    _push()
    return {"ok": True, "run": run, "ep": body.ep, "state": rec}


@router.post("/api/owner/episode-final")
def post_final(body: EpisodeAct, request: Request):
    u = _owner(request)
    run = _run_of(body.run)
    if body.ep < 1:
        raise HTTPException(400, "集号不对")
    rec = _es().mark_final(run, body.ep, u["name"], (body.why or "").strip()[:500], source="owner_api", root=REPO)
    _push()
    return {"ok": True, "run": run, "ep": body.ep, "state": rec}
