"""V2 资产页的数据（ASSETUX，总调度 20:10）：只读 assets_v2/manifest.json，没有就明说，不退回 V1。

GET  /api/v2/assets                     女主 lead_f 按类分组：身份脸 / 造型 O1–O4 / 鞋 SH1–SH2 / 身体饰品 J1–J2；其他人物和场景 = 占位（等剧本定稿后出候选）
GET  /api/v2/asset-file?path=           只发清单里登记的、非成人的文件（成人类 = 仅本地，不给网页缩略图）
POST /api/v2/assets/{asset_id}/edit     “修改”：把一句话原样记下，立刻 202（L-123 延伸：反馈永不拒收）；后续由出图线接手
成人类（adult=true / route=local_only：O2 / O3 / J1 / J2）：网页只给文字卡（名称 + “仅本地，项目方触发”），没有图片地址，也没有“修改”。
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel

ROOT = Path(__file__).resolve().parents[3]
MANIFEST = ROOT / "assets_v2" / "manifest.json"
EDITS = ROOT / "data" / "state" / "v2_asset_edit_requests.json"
router = APIRouter(tags=["v2-assets"])
_lock = threading.RLock()
ADULT_NOTE = "仅本地，项目方触发"
LOOK_ORDER = ["O1", "O2", "O3", "O4"]
GROUPS = [("face", "身份脸"), ("looks", "造型（整套服装）"), ("shoes", "鞋"), ("jewelry", "身体饰品")]


def load_manifest() -> dict:
    try:
        return json.loads(MANIFEST.read_text(encoding="utf-8"))
    except FileNotFoundError as e:
        raise HTTPException(503, "V2 资产清单还没有建好（assets_v2/manifest.json）") from e
    except ValueError as e:
        raise HTTPException(503, "V2 资产清单读不了，请告诉总调度") from e


def _edits() -> list[dict]:
    try:
        return json.loads(EDITS.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 还没有任何修改记录 = 空列表，调用方当没有进行中的修改；记录文件写入走临时文件再替换，不会写出半截
        return []


def _save(rows: list[dict]) -> None:
    EDITS.parent.mkdir(parents=True, exist_ok=True)
    tmp = EDITS.with_suffix(".tmp")
    tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(EDITS)


def _url(rel: str | None) -> str | None:
    if not rel or not (ROOT / rel).is_file():
        return None
    from urllib.parse import quote          # V2CUT-O：文件名里有 #（sk_white_cyc_base_sk_white_cyc#2.png）不编码会被当成锚点截断
    return f"/api/v2/asset-file?path={quote(rel, safe='/')}&v={int((ROOT / rel).stat().st_mtime)}"


def _card(aid: str, kind: str, name: str, file: str | None, adult: bool, route: str | None, edit: dict | None, note: str = "") -> dict:
    local = bool(adult or route == "local_only")
    text = ADULT_NOTE if local else (note if file is None else "")
    return {"id": aid, "kind": kind, "name": name, "adult": local, "url": None if local else _url(file), "text": text,
            "can_edit": bool(not local and file and _url(file)), "edit": edit}


def registered_files(man: dict | None = None) -> dict[str, bool]:
    """清单里登记的文件 → 是不是成人类（成人类网页不发图）"""
    man = man or load_manifest()
    out: dict[str, bool] = {}
    for ch in (man.get("characters") or {}).values():
        f = (ch.get("face") or {}).get("file")
        if f:
            out[f] = False
        for lk in (ch.get("looks") or {}).values():
            for it in (lk.get("items") or {}).values():
                if it.get("file"):
                    out[it["file"]] = bool(lk.get("adult") or lk.get("route") == "local_only")
            if (lk.get("sheet") or {}).get("file"):
                out[lk["sheet"]["file"]] = bool(lk.get("adult") or lk.get("route") == "local_only")
        for it in (ch.get("items") or {}).values():
            if it.get("file"):
                out[it["file"]] = bool(it.get("adult") or it.get("route") == "local_only")
    for sc in (man.get("scenes") or {}).values():        # AUTOFIX-O 11-03：场景底图（scenes[sid].base）也是登记文件，以前漏了 → 404
        b = (sc or {}).get("base") if isinstance(sc, dict) else None
        if isinstance(b, dict) and b.get("file"):
            out[b["file"]] = bool(b.get("adult") or b.get("route") == "local_only")
    return out


@router.get("/api/v2/assets")
def assets():
    man = load_manifest()
    last: dict[str, dict] = {}
    for r in _edits():
        last[r["asset"]] = {k: r.get(k) for k in ("id", "text", "state", "at", "note")}
    chars = []
    for cid, ch in (man.get("characters") or {}).items():
        groups = []
        face = ch.get("face") or {}
        groups.append({"key": "face", "title": "身份脸", "cards": [_card(f"{cid}:face", "face", "女主身份脸", face.get("file"), False, None, last.get(f"{cid}:face"))]})
        looks = ch.get("looks") or {}
        cards = [_card(f"{cid}:{k}", "look", f"{k} · {looks[k].get('name')}", (next(iter((looks[k].get("items") or {}).values()), {}) or {}).get("file"),
                       bool(looks[k].get("adult")), looks[k].get("route"), last.get(f"{cid}:{k}")) for k in LOOK_ORDER if k in looks]
        groups.append({"key": "looks", "title": "造型（整套服装）", "cards": cards})
        items = ch.get("items") or {}
        for key, title, slot_set in (("shoes", "鞋", {"shoes"}), ("jewelry", "身体饰品", {"body_jewelry"})):
            cs = []
            for iid in sorted(items):
                it = items[iid]
                if it.get("slot") in slot_set:
                    cs.append(_card(f"{cid}:{iid}", "item", f"{iid} · {it.get('name')}", it.get("file"), bool(it.get("adult")), it.get("route"),
                                    last.get(f"{cid}:{iid}"), note="还没有这件的原图（等项目方上传）"))
            groups.append({"key": key, "title": title, "cards": cs})
        chars.append({"id": cid, "display_name": ch.get("display_name") or "女主", "groups": groups})
    return {"run": man.get("run"), "locked": bool(man.get("locked")), "characters": chars,
            "pending": [{"label": "其他人物和场景", "note": "等剧本定稿后出候选"}]}


@router.get("/api/v2/asset-file")
def asset_file(path: str):
    reg = registered_files()
    if path not in reg:
        raise HTTPException(404, "not found")           # 清单外的一律不发
    if reg[path]:
        raise HTTPException(403, ADULT_NOTE)             # 成人类：网页不发图
    p = (ROOT / path).resolve()
    if not p.is_relative_to((ROOT / "assets_v2").resolve()) or not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p)


class EditBody(BaseModel):
    text: str = ""
    chips: list[str] = []


@router.post("/api/v2/assets/{asset_id}/edit", status_code=202)
def edit(asset_id: str, body: EditBody, request: Request):
    """“修改”：只把话原样记下（一句话、点过的建议 chip、哪一张、时间、谁），立刻返回；之后由出图线接手（改写、出图、进候选），不在这里同步做"""
    man = load_manifest()
    cards = {c["id"]: c for ch in assets()["characters"] for g in ch["groups"] for c in g["cards"]}
    c = cards.get(asset_id)
    if c is None:
        raise HTTPException(404, "没有这张资产")
    if not c["can_edit"]:
        raise HTTPException(409, ADULT_NOTE if c["adult"] else "这一项还没有原图，先等项目方上传")
    try:
        from ns_api import character_hub as H
        by = H._actor(request)
    except Exception:  # noqa: BLE001  # arch-ok: 取不到登录名也照常记账（记“未登录”），不挡项目方的修改
        by = "未登录"
    rec = {"id": "ae-" + uuid.uuid4().hex[:10], "asset": asset_id, "text": body.text.strip() or "同样的要求，换个种子再出一版", "chips": body.chips[:8],
           "by": by, "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "state": "received", "note": "已记下，出图线接手后会显示在这里",
           "manifest_locked": bool(man.get("locked"))}
    with _lock:
        rows = _edits()
        rows.append(rec)
        _save(rows)
    return {"ok": True, "id": rec["id"], "state": rec["state"], "note": rec["note"]}
