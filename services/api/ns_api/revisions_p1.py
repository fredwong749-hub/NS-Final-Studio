"""
资产二次修改 P1 接口（docs/ux_round5/B_revision.md §5 / §7 P1；UX6）。

    POST /api/revisions/{key}/set-current    {rev, by, owner_quote?, note?}  移当前指针（含回滚）
                                             定妆 / 身份 LoRA / 音色：by≠owner 或没原话 → 403；
                                             原地覆盖前自动快照；配置型只写提议 data/assets/proposals/（不改 config/）
    GET  /api/revisions/{key}/actions        这个键的写入记录（set-current 等）
    POST /api/shots/{shot_id}/deps/keep      {stage, key, n?, by:"owner", owner_quote}  保留旧版（kept 豁免）
    GET  /api/shots/{shot_id}/deps/waivers   本镜豁免记录
    GET  /api/episodes/{n}/cut/deps          成片过期：最新一版成片 vs 当前定稿（“落后 N 镜”，复用 cuts 的比对）+ 成片之后改过的音色
    GET  /api/loras                          LoRA 总表（只读合并，含视频身份 LoRA、训练数据是否来自旧定妆）
    POST /api/loras/registry                 登记一个 LoRA 版本（candidate；视频 LoRA 带 sha 与训练所用定妆 rev）
    POST /api/loras/registry/{lora_id}/status {status, by, owner_quote}  采用 / 作废（项目方闸门）
    GET  /api/asset-proposals?kind=          提议列表（只读）

不提交渲染任务；不改 config/；不删任何文件；不做内容检测。
"""
from __future__ import annotations

import re
import time

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ns_agent import asset_revs as AR
from ns_agent import asset_revs_p1 as ARP
from ns_agent import lora_registry as LR
from ns_render import pipeline as P

router = APIRouter(tags=["revisions-p1"])


class SetCurrentBody(BaseModel):
    rev: str
    by: str | None = None
    owner_quote: str | None = None
    note: str | None = None


@router.post("/api/revisions/{key}/set-current")
def set_current(key: str, body: SetCurrentBody):
    if not re.fullmatch(r"[a-z]+:[\w.\-:]+", key):
        raise HTTPException(404, f"没有这个依赖键：{key}")
    try:
        return ARP.set_current(key, body.rev, body.by, body.owner_quote, body.note, P.ROOT)
    except ARP.GateError as e:
        raise HTTPException(403, str(e)) from e
    except ARP.RevNotFound as e:
        raise HTTPException(409, str(e)) from e


@router.get("/api/revisions/{key}/actions")
def key_actions(key: str):
    return {"key": key, "actions": ARP.actions(P.ROOT, key)}


class KeepBody(BaseModel):
    stage: str
    key: str
    n: int | None = None
    by: str | None = None
    owner_quote: str | None = None


@router.post("/api/shots/{shot_id}/deps/keep")
def keep_old(shot_id: str, body: KeepBody):
    if not re.fullmatch(r"ep\d+-S\d+", shot_id):
        raise HTTPException(404, f"unknown shot: {shot_id}")
    if body.stage not in ("image", "last", "video"):
        raise HTTPException(422, "stage 只能是 image / last / video")
    rev = None
    if body.key == AR.INPUTS_KEY:
        try:
            from ns_agent.state_timeline import shot_inputs_sha
            rev = shot_inputs_sha(shot_id, P.ROOT)
        except Exception:  # noqa: BLE001
            rev = None
    try:
        return ARP.keep(shot_id, body.stage, body.key, body.by, body.owner_quote, body.n, P.ROOT, rev_at_waiver=rev)
    except ARP.GateError as e:
        raise HTTPException(403, str(e)) from e


@router.get("/api/shots/{shot_id}/deps/waivers")
def shot_waivers(shot_id: str):
    return {"shot_id": shot_id, "waivers": ARP.waivers(P.ROOT, shot_id)}


@router.get("/api/episodes/{n}/cut/deps")
def cut_deps(n: int):
    """最新一版成片（不算 4K 副本）落后于当前定稿几镜（复用 cuts._summary 的 changed）+ 成片之后账本里改过的音色"""
    from ns_api import cuts as C
    d = C._epdir()
    files = sorted(d.glob(f"ep{n:02d}*.mp4"), key=lambda p: p.stat().st_mtime, reverse=True) if d.is_dir() else []
    files = [f for f in files if re.match(rf"ep{n:02d}(?!\d)", f.name) and not f.stem.endswith("_4k")]
    if not files:
        return {"episode": n, "cut": None, "stale": False, "behind": 0, "changed": [], "voices_changed": [],
                "note": "本集还没有成片"}
    latest = files[0]
    s = C._summary(latest, n)
    mtime = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(latest.stat().st_mtime))
    voices = []
    for k, hist in AR.read_ledger(P.ROOT).items():
        if not k.startswith("voice:"):
            continue
        later = [h for h in hist if h.get("by") != "baseline" and str(h.get("at") or "") > mtime]
        if later:
            voices.append({"key": k, "label": AR.label(k, P.ROOT), "at": later[-1].get("at"),
                           "to_v": later[-1].get("seq")})
    return {"episode": n, "cut": {"name": s["name"], "url": s["url"], "mtime": s["mtime"], "tags": s["tags"]},
            "stale": bool(s["changed"] or voices), "behind": len(s["changed"]), "changed": s["changed"],
            "voices_changed": voices,
            "note": "落后 = 成片里用的视频 ≠ 现在的定稿（_cc 校色副本算同一版）；音色在成片之后改过 = 需要重新合成"}


@router.get("/api/loras")
def loras():
    return LR.table(P.ROOT)


class RegisterBody(BaseModel):
    file: str
    kind: str = "image"
    character: str | None = None
    step: int | None = None
    sha256: str | None = None
    local_path: str | None = None
    from_identity_rev: str | None = None
    dataset_manifest: str | None = None
    trigger: str | None = None
    strength: float | None = None
    location: str | None = None
    by: str | None = None
    note: str | None = None
    status: str | None = None          # 只能不填或 candidate；accepted / void 走 status 接口（项目方闸门）


@router.post("/api/loras/registry")
def register_lora(body: RegisterBody):
    try:
        return LR.register(body.model_dump(), P.ROOT)
    except LR.GateError as e:
        raise HTTPException(403, str(e)) from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


class StatusBody(BaseModel):
    status: str
    by: str | None = None
    owner_quote: str | None = None


@router.post("/api/loras/registry/{lora_id}/status")
def lora_status(lora_id: str, body: StatusBody):
    try:
        return LR.set_status(lora_id, body.status, body.by, body.owner_quote, P.ROOT)
    except LR.GateError as e:
        raise HTTPException(403, str(e)) from e
    except KeyError as e:
        raise HTTPException(404, f"没有登记：{lora_id}") from e
    except ValueError as e:
        raise HTTPException(422, str(e)) from e


@router.get("/api/asset-proposals")
def proposals(kind: str | None = None):
    return {"proposals": ARP.list_proposals(P.ROOT, kind)}
