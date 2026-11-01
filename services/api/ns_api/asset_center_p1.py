"""
资产中心 P1（docs/ux_round5/A_assets_ia.md §5 B6–B10；UX6）。只读为主 + 最小可编辑，不改 config/、不删数据、不做内容检测。

B6 版本链 vs 另存为新资产
    GET  /api/assets/{asset_id}/chain               形象 / 单品的版本链（同一资产 id）+ 以前“存为新版本”复制出的 <id>-vN
                                                    资产（只做映射显示，标“历史复制”，不合并、不删）
    POST /api/assets/{asset_id}/fork                另存为新资产（= versions mode=save_as）；“新版本”走 versions mode=version
    POST /api/assets/{asset_id}/chain/set-current   {file, by, note?}  形象：把链上某一版设回当前预览（用到它的镜头标过期，不重出）
B7 道具·产品
    GET  /api/props                                 衣橱里带 LoRA 的饰品映射过来（只读）+ data/props.json 自建条目
    POST /api/props    PUT /api/props/{id}          自建条目的名称 / 说明 / LoRA 文件 / 触发词（不动衣橱数据）
B8 音色
    GET  /api/voices                                config/voices.json 只读展示 + 当前 rev / vN + 待处理提议
    POST /api/voices/{cid}/proposals                {changes:{sid?, voice?, speed?}, by, owner_quote?, note?} → data/assets/proposals/
                                                    （不直接写 config；换音色属于项目方闸门，提议里标 requires_owner）
B10 提示词模板库（容器：系统只存、编号、引用；正文由项目方 / 写作方写）
    GET  /api/prompt-templates   POST /api/prompt-templates   PUT /api/prompt-templates/{id}（加新版本）
    POST /api/prompt-templates/{id}/refs {target, v?, by}   GET /api/prompt-templates/{id}/usage
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ns_agent import asset_revs as AR
from ns_agent import asset_revs_p1 as ARP
from ns_agent.looks import LookStore
from ns_api import assets as A
from ns_api.looks import get_store
from ns_render import pipeline as P

router = APIRouter(tags=["asset-center-p1"])
_lock = threading.RLock()
TEMPLATE_KINDS = {"portrait": "立绘模板", "scene_plate": "场景底图模板", "video_format": "视频提示词格式模板",
                  "image_format": "首帧提示词格式模板", "other": "其他"}


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _rjson(p: Path, default):
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
        return d if isinstance(d, type(default)) else default
    except (OSError, ValueError):
        return default


def _wjson(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


# ================================================================== B6 版本链

def _versions_rec(asset_id: str) -> list[dict]:
    from ns_api import asset_edit as AE
    return [r for r in AE._read("asset_versions").get(asset_id, []) if isinstance(r, dict)]


def chain(store: LookStore, asset_id: str) -> dict:
    from ns_api import asset_edit as AE
    asset = AE.resolve_asset(store, asset_id)
    if asset["kind"] not in ("look", "item"):
        raise HTTPException(422, "版本链只对形象 / 单品；场景底图看 /api/assets/scenes/{id}，定妆看 /api/revisions/identity:<slug>")
    recs = _versions_rec(asset_id)
    cur_file = AE.current_image(store, asset)
    versions: list[dict] = []
    if asset["kind"] == "item":
        it = next(i for i in store.wardrobe().items if i.id == asset_id)
        for im in sorted(it.images, key=lambda im: -im.version):
            versions.append({"version": im.version, "file": im.file, "url": A.file_url(im.file), "variant": im.variant,
                             "source": im.source, "at": im.created_at, "current": im.file == cur_file,
                             "kind": "image"})
    else:
        lk = next(x for x in store.lookbook().looks if x.id == asset_id)
        seen = set()
        for r in sorted((r for r in recs if r.get("in_place") and r.get("asset_id") == asset_id),
                        key=lambda r: -int(r.get("version") or 0)):
            if r.get("file") in seen:
                continue
            seen.add(r.get("file"))
            versions.append({"version": r.get("version"), "file": r.get("file"), "url": A.file_url(r.get("file")),
                             "label": r.get("label"), "at": r.get("created_at"), "origin": r.get("origin"),
                             "current": r.get("file") == cur_file, "kind": "in_place"})
        for f in [lk.preview_image, *lk.reference_images]:
            if f and f not in seen and (A.ROOT / f).is_file():
                seen.add(f)
                versions.append({"version": None, "file": f, "url": A.file_url(f), "label": "原始 / 参考",
                                 "at": None, "current": f == cur_file, "kind": "original"})
    # 历史复制：以前“存为新版本”默认复制出的 <id>-vN（asset_versions 里 from_asset=本资产且不是 in_place，或 id 形如 <id>-vN）
    ids = ({i.id for i in store.wardrobe().items} if asset["kind"] == "item" else {x.id for x in store.lookbook().looks})
    copies = {}
    for r in recs:
        if not r.get("in_place") and r.get("asset_id") and r["asset_id"] != asset_id:
            copies[r["asset_id"]] = {"asset_id": r["asset_id"], "version": r.get("version"), "file": r.get("file"),
                                     "url": A.file_url(r.get("file")), "at": r.get("created_at"),
                                     "label": r.get("label"), "exists": r["asset_id"] in ids}
    for i in ids:
        if re.fullmatch(re.escape(asset_id) + r"-v\d+", i) and i not in copies:
            copies[i] = {"asset_id": i, "version": int(i.rsplit("-v", 1)[1]), "file": None, "url": None, "at": None,
                         "label": None, "exists": True}
    for c in copies.values():
        c["mapped"] = "历史复制"
        if c["exists"] and not c.get("url"):
            try:
                c["file"] = AE.current_image(store, AE.resolve_asset(store, c["asset_id"]))
                c["url"] = A.file_url(c["file"])
            except HTTPException:
                pass
    return {"asset_id": asset_id, "kind": asset["kind"], "name": asset["name"], "current_file": cur_file,
            "versions": versions, "copies": sorted(copies.values(), key=lambda c: c.get("version") or 0),
            "note": "“历史复制”= 以前“存为新版本”复制出的独立资产；这里只映射显示，不合并、不删。"}


@router.get("/api/assets/{asset_id}/chain")
def get_chain(asset_id: str, store: LookStore = Depends(get_store)):
    return chain(store, asset_id)


@router.post("/api/assets/{asset_id}/fork")
def fork(asset_id: str, body: dict, store: LookStore = Depends(get_store)):
    from ns_api import asset_edit as AE
    vb = AE.VersionBody(**{k: v for k, v in (body or {}).items() if k not in ("in_place", "mode")}, mode="save_as")
    return AE.save_version(asset_id, vb, store)


class ChainSetBody(BaseModel):
    file: str
    by: str | None = None
    note: str | None = None


@router.post("/api/assets/{asset_id}/chain/set-current")
def chain_set_current(asset_id: str, body: ChainSetBody, store: LookStore = Depends(get_store)):
    c = chain(store, asset_id)
    if c["kind"] != "look":
        raise HTTPException(409, "单品的当前图按“偏好角度 + 最新版本”自动取，回到旧版要等单品主图指针（下一步）；现在可以对比、另存")
    if not any(v["file"] == body.file for v in c["versions"]):
        raise HTTPException(422, "这个文件不在本形象的版本链上")
    if body.file == c["current_file"]:
        return {"asset_id": asset_id, "file": body.file, "changed": False, "affected_shots": []}
    lk = store.get_look(asset_id)
    new = lk.model_copy(update={"preview_image": body.file,
                                "reference_images": [body.file] + [r for r in lk.reference_images if r != body.file]})
    try:
        affected = store.upsert_look(new)
    except (KeyError, ValueError) as e:
        raise HTTPException(422, str(e)) from e
    ARP._append(P.ROOT / ARP.ACTIONS, {"action": "chain_set_current", "key": f"look:{asset_id}",
                                       "from_file": c["current_file"], "to_file": body.file, "by": body.by or "canvas",
                                       "note": body.note, "at": _now()})
    return {"asset_id": asset_id, "file": body.file, "changed": True, **affected.model_dump()}


# ================================================================== B7 道具·产品

def _props_path() -> Path:
    return P.DATA / "props.json"


def props(store: LookStore) -> list[dict]:
    out = []
    for it in store.wardrobe().items:
        if it.slot == "accessory" and getattr(it, "lora_file", None):
            img = A.AssetIndex(store).item_image(it.id)
            out.append({"id": it.id, "name": it.name, "kind": "jewellery", "owner": it.character,
                        "lora_file": it.lora_file, "trigger": getattr(it, "trigger", None), "thumb": A.file_url(img),
                        "source": "wardrobe", "editable": False, "note": "衣橱单品映射（只读；迁不迁由项目方决定）"})
    for p in _rjson(_props_path(), {"props": []}).get("props") or []:
        if isinstance(p, dict) and p.get("id"):
            out.append({**p, "source": "props", "editable": True,
                        "thumb": A.file_url(p.get("image")) if p.get("image") else None})
    return out


@router.get("/api/props")
def get_props(store: LookStore = Depends(get_store)):
    return {"props": props(store)}


class PropBody(BaseModel):
    name: str
    kind: str = "product"
    owner: str | None = None
    lora_file: str | None = None
    trigger: str | None = None
    image: str | None = None
    note: str | None = None
    by: str | None = None


def _check_prop(b: PropBody) -> None:
    if not b.name.strip():
        raise HTTPException(422, "name 不能为空")
    if b.lora_file and not re.fullmatch(r"[\w.\-]+\.safetensors", b.lora_file):
        raise HTTPException(422, "lora_file 要是文件名（*.safetensors）")
    if b.image and not ((A.ROOT / b.image).is_file() and b.image.replace("\\", "/").startswith("assets/")):
        raise HTTPException(422, "image 要是 assets/ 下已有的图片")


@router.post("/api/props")
def create_prop(body: PropBody):
    _check_prop(body)
    with _lock:
        d = _rjson(_props_path(), {"props": []})
        pid = f"prop-{uuid.uuid4().hex[:8]}"
        row = {"id": pid, **body.model_dump(), "created_at": _now(), "updated_at": _now()}
        d.setdefault("props", []).append(row)
        _wjson(_props_path(), d)
    return row


@router.put("/api/props/{prop_id}")
def update_prop(prop_id: str, body: PropBody):
    _check_prop(body)
    with _lock:
        d = _rjson(_props_path(), {"props": []})
        row = next((p for p in d.get("props") or [] if p.get("id") == prop_id), None)
        if not row:
            raise HTTPException(404, f"没有这个自建道具：{prop_id}（衣橱映射的条目只读）")
        row.update({**body.model_dump(), "updated_at": _now()})
        _wjson(_props_path(), d)
    return row


# ================================================================== B8 音色

VOICE_FIELDS = {"sid": int, "voice": str, "speed": float}


@router.get("/api/voices")
def get_voices():
    v = AR._json(P.ROOT / "config" / "voices.json")
    if not isinstance(v, dict):
        return {"tts_model": None, "characters": [], "proposals": [], "note": "读不到 config/voices.json"}
    led = AR.read_ledger(P.ROOT)
    props_ = ARP.list_proposals(P.ROOT, "voice")
    rows = []
    for cid, c in (v.get("characters") or {}).items():
        if not isinstance(c, dict):
            continue
        rev = AR.voice_rev(P.ROOT, cid)
        rows.append({"cid": cid, "name": c.get("name") or AR.char_name(cid), "gender": c.get("gender"),
                     "sid": c.get("sid"), "voice": c.get("voice"), "speed": c.get("speed"), "f0_hz": c.get("f0_hz"),
                     "note": c.get("note"), "key": f"voice:{cid}", "rev": rev, "seq": AR.seq_of(f"voice:{cid}", rev, led),
                     "pending": [p for p in props_ if p.get("character") == cid and p.get("status") == "pending"]})
    return {"tts_model": (v.get("tts_model") or {}).get("id"), "characters": rows,
            "line_overrides": len(v.get("line_overrides") or {}), "proposals": props_,
            "note": "只读：config/voices.json 不由系统直接改；改动写成提议，换音色要项目方本人确认"}


class VoiceProposal(BaseModel):
    changes: dict = Field(default_factory=dict)
    by: str | None = None
    owner_quote: str | None = None
    note: str | None = None


@router.post("/api/voices/{cid}/proposals")
def voice_proposal(cid: str, body: VoiceProposal):
    v = AR._json(P.ROOT / "config" / "voices.json")
    cur = ((v or {}).get("characters") or {}).get(cid) if isinstance(v, dict) else None
    if not isinstance(cur, dict):
        raise HTTPException(404, f"voices.json 里没有这个角色：{cid}")
    ch = {}
    for k, val in (body.changes or {}).items():
        if k not in VOICE_FIELDS:
            raise HTTPException(422, f"只能提议改 {sorted(VOICE_FIELDS)}")
        try:
            ch[k] = VOICE_FIELDS[k](val)
        except (TypeError, ValueError) as e:
            raise HTTPException(422, f"{k} 格式不对") from e
    if not ch:
        raise HTTPException(422, "changes 不能为空")
    return ARP.write_proposal("voice", {
        "character": cid, "key": f"voice:{cid}", "config": "config/voices.json", "path": ["characters", cid],
        "from": {k: cur.get(k) for k in ch}, "to": ch, "by": body.by or "canvas", "owner_quote": body.owner_quote,
        "requires_owner": True, "owner_confirmed": body.by == "owner" and bool((body.owner_quote or "").strip()),
        "user_note": body.note}, P.ROOT)


# ================================================================== B10 提示词模板库

def _tpl_path() -> Path:
    return P.DATA / "prompt_templates.json"


def _tpl_refs_path() -> Path:
    return P.DATA / "prompt_template_refs.jsonl"


def _author_ok(by: str | None) -> bool:
    """模板正文只能由项目方 / 写作方写（系统只存）：by = owner | writer[:名字]"""
    return bool(by) and (by == "owner" or by == "writer" or by.startswith("writer:"))


def _tpl_view(t: dict) -> dict:
    vs = t.get("versions") or []
    return {**t, "current_v": vs[-1]["v"] if vs else None, "current": vs[-1] if vs else None,
            "kind_label": TEMPLATE_KINDS.get(t.get("kind"), t.get("kind"))}


@router.get("/api/prompt-templates")
def list_templates():
    d = _rjson(_tpl_path(), {"templates": []})
    return {"templates": [_tpl_view(t) for t in d.get("templates") or [] if isinstance(t, dict)],
            "kinds": TEMPLATE_KINDS,
            "note": "容器：系统只存、编号、引用；正文由项目方 / 写作方写（by=owner | writer:<名>）"}


class TemplateBody(BaseModel):
    name: str | None = None
    kind: str | None = None
    text: str
    by: str | None = None
    note: str | None = None


@router.post("/api/prompt-templates")
def create_template(body: TemplateBody):
    if not _author_ok(body.by):
        raise HTTPException(403, "模板正文由项目方 / 写作方写：by 要是 owner 或 writer:<名字>")
    if not (body.name or "").strip() or not body.text.strip():
        raise HTTPException(422, "name 和 text 不能为空")
    if (body.kind or "other") not in TEMPLATE_KINDS:
        raise HTTPException(422, f"kind 只能是 {list(TEMPLATE_KINDS)}")
    with _lock:
        d = _rjson(_tpl_path(), {"templates": []})
        n = 1 + max((int(str(t.get("id", "pt-0")).split("-")[-1]) for t in d.get("templates") or []
                     if re.fullmatch(r"pt-\d+", str(t.get("id")))), default=0)
        t = {"id": f"pt-{n:03d}", "name": body.name.strip(), "kind": body.kind or "other", "created_at": _now(),
             "versions": [{"v": 1, "text": body.text, "by": body.by, "at": _now(), "note": body.note}]}
        d.setdefault("templates", []).append(t)
        _wjson(_tpl_path(), d)
    return _tpl_view(t)


@router.put("/api/prompt-templates/{tid}")
def update_template(tid: str, body: TemplateBody):
    if not _author_ok(body.by):
        raise HTTPException(403, "模板正文由项目方 / 写作方写：by 要是 owner 或 writer:<名字>")
    with _lock:
        d = _rjson(_tpl_path(), {"templates": []})
        t = next((x for x in d.get("templates") or [] if x.get("id") == tid), None)
        if not t:
            raise HTTPException(404, f"没有这个模板：{tid}")
        if body.name:
            t["name"] = body.name.strip()
        vs = t.setdefault("versions", [])
        vs.append({"v": (vs[-1]["v"] + 1) if vs else 1, "text": body.text, "by": body.by, "at": _now(),
                   "note": body.note})
        _wjson(_tpl_path(), d)
    return _tpl_view(t)


class TplRefBody(BaseModel):
    target: str
    v: int | None = None
    by: str | None = None


@router.post("/api/prompt-templates/{tid}/refs")
def ref_template(tid: str, body: TplRefBody):
    d = _rjson(_tpl_path(), {"templates": []})
    t = next((x for x in d.get("templates") or [] if x.get("id") == tid), None)
    if not t:
        raise HTTPException(404, f"没有这个模板：{tid}")
    v = body.v or _tpl_view(t)["current_v"]
    if not any(x.get("v") == v for x in t.get("versions") or []):
        raise HTTPException(422, f"{tid} 没有 v{v}")
    row = {"template": tid, "v": v, "target": body.target, "by": body.by or "canvas", "at": _now()}
    ARP._append(_tpl_refs_path(), row)
    return row


@router.get("/api/prompt-templates/{tid}/usage")
def template_usage(tid: str):
    rows = [r for r in ARP._jsonl(_tpl_refs_path()) if r.get("template") == tid]
    return {"template": tid, "refs": rows}
