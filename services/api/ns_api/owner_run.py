"""
「按集渲染（项目方本人）」：透传 gpu3 桥 POST /api/gpu3/projects/{slug}/episodes/{ep}/run（docs/canvas.md；
桥写 lend.gpuN = "owner-run {run_id} …" 与 run_id 队列项，weita_runner 消费）。

- 只有项目方本人在画布上点（by=owner + 二次确认）；Claude / agent 会话不得调用（总调度 2026-10-30）。
- 成人 / 🔴 集不再拒绝：2026-10-30 项目方取消成人过滤器后，任何集都能经 gpu3 按集渲染。
- dry_run=true 只预览（桥不写 lend、不入队），给确认框看镜数、合格项与原因。

POST /api/gpu3/episodes/{ep}/run {gpu, steps:[frames|video|4k], note, dry_run, by:"owner"}
"""
from __future__ import annotations

import json
import urllib.error
import urllib.request

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ns_api import readiness as RD

router = APIRouter(tags=["owner-run"])
RUN_GPUS = (0, 3)


class OwnerRunBody(BaseModel):
    gpu: int
    steps: list[str]
    note: str
    dry_run: bool = True
    by: str = ""


def _require_episode(ep: int) -> None:
    from ns_api import app as A           # 延迟导入：当前剧本在 app._script
    if not any(x.number == ep for x in A._script.episodes):
        raise HTTPException(404, f"没有第 {ep} 集")


def _post(path: str, body: dict, timeout: float = 20) -> dict:
    req = urllib.request.Request(f"{RD.BRIDGE_URL}{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


@router.get("/api/gpu3/episodes/{ep}/run-eligibility")
def eligibility(ep: int):
    """面板用：这一集能不能经 gpu3 按集渲染（成人 / 🔴 集也可）。"""
    _require_episode(ep)
    return {"ep": ep, "allowed": True, "reason": ""}


@router.post("/api/gpu3/episodes/{ep}/run")
def owner_run(ep: int, body: OwnerRunBody):
    if body.by != "owner":
        raise HTTPException(403, "按集渲染只由项目方本人在画布上启动（by=owner）；agent 不得调用")
    _require_episode(ep)
    if body.gpu not in RUN_GPUS:   # 封板修复 P3：本地就拒绝（GPU2 坏卡；GPU1 固定给 Qwen 写作模型）
        raise HTTPException(422, f"gpu 只能是 {list(RUN_GPUS)}（GPU2 坏卡，GPU1 归 Qwen）")
    if not body.note.strip():
        raise HTTPException(422, "请写一句这次为什么跑（note）")
    payload = {"by": "owner", "gpu": body.gpu, "steps": body.steps, "note": body.note.strip(), "dry_run": body.dry_run}
    try:
        return _post(f"/api/gpu3/projects/{RD.current_slug()}/episodes/{ep}/run", payload)
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", "replace")
        try:
            d = json.loads(detail)
            detail = d.get("detail", detail) if isinstance(d, dict) else detail   # 封板修复：非对象 JSON 曾 500
        except ValueError:
            pass
        raise HTTPException(e.code, detail)
    except (urllib.error.URLError, OSError) as e:
        raise HTTPException(502, f"gpu3 桥不可达（{RD.BRIDGE_URL}）：{e}")
