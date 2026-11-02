"""资产统一动作（ASSETUX，L-120）：选用 / 不选 / 移到回收区 三个动作，四类资产（face / sheet / item / scene_plate）同一套入口。

设计：data/review_pages/assetux/index.html 第 1 节（总调度 R1 审过）。本模块只做“分发 + 护栏”，真正落盘仍走 character_hub 里
已有的函数（不另起一套账）：
  POST /api/assets/{asset_id}/select   选用：设为当前，返回 prev + undo 说明（撤销 = 对 prev 再 select，单品走 unuse）
  POST /api/assets/{asset_id}/reject   不选：记原因，不删文件、不动当前；当前图不能直接不选
  POST /api/assets/{asset_id}/trash    删除 = 隔离到回收区（不真删）；当前图不能直接移走；真删只在回收区
护栏：
  · 换身份脸 / 设定图要带 impact_ack = 界面给项目方看的“会影响 N 个镜头”的 N；没带 → 409（项目方 11-02 15:45 一键换脸没有提示，不许再发生）。
    服务端能算出影响数时（impact_counter 可注入）必须对得上，对不上 409 要求重看。
  · asset_id：face / sheet = 人物 id；item = 单品 id（cid 另传）。
"""
from __future__ import annotations

import re
from typing import Callable

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(tags=["asset-actions"])
KINDS = ("face", "sheet", "item", "scene_plate")

# 影响数提供者：(cid, kind, look) -> int | None（默认 shot_cast.impact_count，按出图同口径数镜头）。None = 算不出（只校验“有没有带确认”）。
def _default_counter(cid: str, kind: str, look: str | None) -> int | None:
    from ns_api import shot_cast as SC
    return SC.impact_count(cid, kind, look)


impact_counter: Callable[[str, str, str | None], int | None] = _default_counter


class SelectBody(BaseModel):
    kind: str
    cid: str
    file: str
    look: str | None = None
    project: str | None = None
    impact_ack: int | None = None      # 项目方在确认框里看到的“会影响 N 个镜头”的 N（face / sheet 必带）


class RejectActBody(BaseModel):
    kind: str
    cid: str
    file: str
    reasons: list[str] = []
    note: str = ""
    redo: bool = False
    undo: bool = False                 # true = 恢复（从“已不选”收回）
    look: str | None = None
    item_id: str | None = None
    project: str | None = None


class TrashActBody(BaseModel):
    kind: str
    cid: str
    file: str | None = None
    item_id: str | None = None         # 整件单品移走
    ref_id: str | None = None          # 身份脸候选（参考图）
    gen_id: str | None = None          # 再生成候选（生成记录）
    look: str | None = None
    project: str | None = None


def _check_kind(kind: str) -> None:
    if kind not in KINDS:
        raise HTTPException(422, f"kind 只能是 {' | '.join(KINDS)}")
    if kind == "scene_plate":
        raise HTTPException(501, "场景图还没接进统一动作（场景底图的当前 / 候选账本还没定，先不假装能用）")


def _current_file(H, kind: str, cid: str, look: str | None, item_id: str | None, project: str | None, store=None) -> str | None:
    pj = H.current_project(project)
    if kind == "face":
        return H.R.face_of(pj, cid)
    if kind == "sheet":
        return H.R.sheet_of(pj, cid, look or "")
    if kind == "item" and item_id and store is not None:
        it = next((i for i in store.wardrobe().items if i.id == item_id and i.character == cid), None)
        return it.images[0].file if it and it.images else None
    return None


def _need_ack(H, body: SelectBody, cur: str | None) -> None:
    if body.kind not in ("face", "sheet") or cur == body.file:
        return
    if body.impact_ack is None:
        n = impact_counter(body.cid, body.kind, body.look)
        raise HTTPException(409, {"code": "impact_ack_required", "impact": n,
                                  "message": "换这张会影响出图，需要先给项目方看影响数并确认（带 impact_ack）"})
    n = impact_counter(body.cid, body.kind, body.look)
    if n is not None and n != body.impact_ack:
        raise HTTPException(409, {"code": "impact_changed", "impact": n,
                                  "message": f"影响数已经变成 {n}，请重新确认"})


@router.post("/api/assets/{asset_id}/select")
def select(asset_id: str, body: SelectBody, request: Request):
    from ns_api import character_hub as H
    _check_kind(body.kind)
    if body.kind in ("face", "sheet") and asset_id != body.cid:
        raise HTTPException(422, "face / sheet 的 asset_id 就是人物 id")
    store = None
    if body.kind == "item":
        from ns_api import looks as LK
        store = LK.get_store()
    prev = _current_file(H, body.kind, body.cid, body.look, asset_id if body.kind == "item" else None, body.project, store)
    _need_ack(H, body, prev)
    if body.kind == "face":
        r = H.set_face(body.cid, H.FaceBody(file=body.file, project=body.project), request)
        undo = {"how": "select", "file": r.get("prev")}
    elif body.kind == "sheet":
        if not (body.look and re.fullmatch(r"[A-Z]", body.look)):
            raise HTTPException(422, "设定图要说是哪套造型（look = A / B / C）")
        r = H.set_sheet(body.cid, H.SheetBody(look=body.look, file=body.file, project=body.project), request)
        undo = {"how": "select", "file": r.get("prev")}
    else:
        if body.file in H._regen_files(asset_id, "item"):
            import asyncio
            r = asyncio.run(H.use_item_regen(body.cid, asset_id, H.AdoptGenBody(file=body.file), request, store))
            undo = {"how": "unuse", "file": r["file"], "prev": r.get("prev")}
        else:
            r = H.set_primary(body.cid, asset_id, H.PrimaryBody(file=body.file), request, store)
            undo = {"how": "select", "file": r.get("prev")}
    return {"ok": True, "kind": body.kind, "file": body.file, "prev": r.get("prev"), "undo": undo, "by": r.get("by")}


@router.post("/api/assets/{asset_id}/reject")
def reject(asset_id: str, body: RejectActBody, request: Request):
    from ns_api import character_hub as H
    _check_kind(body.kind)
    if not body.undo:
        if not body.reasons and not body.note.strip():
            raise HTTPException(422, "不选要记一个原因（点一个原因，或写一句话）")
        store = None
        if body.kind == "item":
            from ns_api import looks as LK
            store = LK.get_store()
        cur = _current_file(H, body.kind, body.cid, body.look, body.item_id or asset_id, body.project, store)
        if cur and cur == body.file:
            raise HTTPException(409, "这张是当前在用的图，先选用别的图，再把它收起来")
    kind_map = {"face": "face", "sheet": "sheet", "item": "item_image"}
    return H.reject_asset(H.RejectBody(kind=kind_map[body.kind], file=body.file, reasons=body.reasons, note=body.note,
                                       redo=body.redo, cid=body.cid, undo=body.undo), request)


@router.post("/api/assets/{asset_id}/trash")
def trash(asset_id: str, body: TrashActBody, request: Request):
    from ns_api import character_hub as H
    from ns_api import trash as T
    _check_kind(body.kind)
    by = H._actor(request)
    store = None
    if body.kind == "item":
        from ns_api import looks as LK
        store = LK.get_store()
    if body.file:
        cur = _current_file(H, body.kind, body.cid, body.look, body.item_id or asset_id, body.project, store)
        if cur and cur == body.file:
            raise HTTPException(409, "当前在用的图不能直接移走，先选用别的图")
    if body.kind == "item" and not body.file and not body.gen_id:
        iid = body.item_id or asset_id
        return H.trash_item(body.cid, iid, request, body.project, store)
    if body.ref_id:
        typ, oid = "asset_ref", f"{asset_id}/{body.ref_id}"
    elif body.gen_id:
        typ, oid = "asset_gen", f"{asset_id}/{body.gen_id}"
    elif body.kind == "sheet" and body.file:
        typ, oid = "sheet_candidate", body.file
    else:
        raise HTTPException(422, "要说清移走哪一个：item_id（整件单品）/ ref_id / gen_id / 设定图候选 file")
    entry = T.delete_object(request, type=typ, id=oid, confirm=True, by=by, reason="资产页：移到回收区")
    H._log(by, body.cid, "trash", kind=body.kind, file=body.file, entry_id=entry.get("entry_id"))
    return {"ok": True, "entry_id": entry.get("entry_id"), "by": by}


class RewriteBody(BaseModel):
    kind: str
    text: str
    ctx: dict = {}


@router.post("/api/assets/rewrite")
def rewrite_preview(body: RewriteBody):
    """所有带提示词的入口（编辑器局部修改、新造型、新单品…）出图前调用：口语 → 外部写作 API 改写 → 回显“它理解的改动”。
    失败 502（不出图、不退回本地硬写，L-119）。"""
    from ns_api import prompt_rewrite as PR
    if not body.text.strip():
        raise HTTPException(422, "先写一句想怎么改")
    try:
        r = PR.rewrite(body.kind, body.text, body.ctx)
    except PR.RewriteError as e:
        raise HTTPException(502, f"提示词改写没成功，没有出图：{e}") from e
    return {k: r[k] for k in ("prompt", "negative_add", "zh_summary", "model")}
