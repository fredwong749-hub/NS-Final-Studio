"""
人物管理页的后端（项目方 2026-10-30：“新增人物管理资产页面”；fredw-25）。

新建人物（建目录 + character.json）、改名 / 角色说明 / 归档、按目标上传图片
（底板 / 参考图 / 表情 / 单品 / 造型），写进对应子目录并追加 manifest。资产页（assets.py）按目录自动识别。
系统只管文件与计数，不看图、不评价图。

接口：
  GET  /api/people                                人物管理总表
  POST /api/people {id, name, role?, notes?}      新建人物
  PUT  /api/people/{id} {name?, role?, notes?, archived?}
  POST /api/people/{id}/upload (multipart file, target, name?)
"""
from __future__ import annotations

import hashlib
import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel

from ns_agent.looks import LookStore
from ns_api import assets as A
from ns_api.looks import get_store

router = APIRouter(tags=["manage"])

MAX_IMAGE_BYTES = 40 * 2**20
SLUG_RE = re.compile(r"^[a-z][a-z0-9_]{1,31}$")
META = "character.json"


# ---------------------------------------------------------------- 人物管理

def read_meta(cid: str) -> dict:
    try:
        return json.loads((A.chars_dir() / cid / META).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _write_meta(cid: str, meta: dict):
    d = A.chars_dir() / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / META).write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _row(c: dict) -> dict:
    """资产页的角色数据 → 人物管理总表一行（只做计数，不看图）"""
    meta = read_meta(c["id"])
    items = {k: len(v) for k, v in c["items"].items()}
    return {
        "id": c["id"], "name": meta.get("name") or c["name"], "role": meta.get("role", ""),
        "notes": meta.get("notes", ""), "archived": bool(meta.get("archived")),
        "created_at": meta.get("created_at"), "dir": c["dir"], "dir_exists": c["dir_exists"],
        "face_url": c["face_url"], "hero_url": (c["hero"] or {}).get("url"),
        "plates": {v: (e or {}).get("url") for v, e in c["plates"].items()},
        "item_counts": items, "expressions": len(c["expressions"]), "looks": len(c["looks"]),
        "look_labels": [lk.get("label") or lk.get("name") for lk in c["looks"]][:8],
        "wardrobe": len(c["wardrobe"]), "missing_count": c["missing_count"], "missing": c["missing"][:20],
        "unregistered": c["unregistered"],
        "used_by_shots": max((lk.get("used_by_shots", 0) for lk in c["looks"]), default=0),
    }


@router.get("/api/people")
def people(store: LookStore = Depends(get_store)):
    cat = A.list_characters(store)
    return {"plate_views": cat["plate_views"], "item_categories": cat["item_categories"],
            "people": [_row(c) for c in cat["characters"]]}


class NewPerson(BaseModel):
    id: str
    name: str
    role: str = ""
    notes: str = ""


@router.post("/api/people", status_code=201)
def create_person(body: NewPerson, store: LookStore = Depends(get_store)):
    cid = body.id.strip().lower()
    if not SLUG_RE.match(cid):
        raise HTTPException(422, "人物 id 只能用小写字母、数字、下划线，字母开头，2–32 位（如 su_qing）")
    if not body.name.strip():
        raise HTTPException(422, "中文名不能为空")
    if (A.chars_dir() / cid).exists() or cid in A.character_ids():
        raise HTTPException(409, f"人物 {cid} 已存在")
    for sub in ("plates", "expressions", "looks", *(f"items/{c}" for c in A.ITEM_CATS)):
        (A.chars_dir() / cid / sub).mkdir(parents=True, exist_ok=True)
    _write_meta(cid, {"id": cid, "name": body.name.strip(), "role": body.role.strip(), "notes": body.notes.strip(),
                      "archived": False, "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")})
    return next(r for r in people(store)["people"] if r["id"] == cid)


class PersonPatch(BaseModel):
    name: str | None = None
    role: str | None = None
    notes: str | None = None
    archived: bool | None = None


@router.put("/api/people/{character}")
def update_person(character: str, body: PersonPatch, store: LookStore = Depends(get_store)):
    cid = A._char(character)
    meta = {"id": cid, **read_meta(cid)}
    for k, v in body.model_dump(exclude_none=True).items():
        meta[k] = v.strip() if isinstance(v, str) else v
    if "name" in meta and not str(meta["name"]).strip():
        raise HTTPException(422, "中文名不能为空")
    meta["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%S")
    _write_meta(cid, meta)
    return next(r for r in people(store)["people"] if r["id"] == cid)


def upload_target(cid: str, target: str) -> tuple[Path, str, str]:
    """target → (目录, manifest kind, 文件名主干)。plate/<视角|master>、portrait、expression/<名>、item/<类别>、look/<名>"""
    group, _, cat = target.partition("/")
    base = A.chars_dir() / cid
    clean = re.sub(r"[^\w-]+", "_", cat).strip("_")
    if group == "plate" and cat in (*A.PLATE_VIEWS, "master"):
        return base / "plates", f"plate/{cat}", cat
    if group == "portrait":
        return base / "refs", "portrait/ref", "ref"
    if group == "expression" and clean:
        return base / "expressions", f"expression/{cat}", clean
    if group == "item" and A._norm_cat(cat) in A.ITEM_CATS:
        c = A._norm_cat(cat)
        return base / "items" / c / "uploads", f"item/{c}", c
    if group == "look" and clean:
        return base / "looks" / clean, f"look/{cat}", clean
    raise HTTPException(422, "target 形如 plate/front|3q|side|back|master、portrait、expression/<名>、item/<类别>、look/<名>")


@router.post("/api/people/{character}/upload", status_code=201)
async def upload_person_image(character: str, file: UploadFile = File(...), target: str = Form(...),
                              name: str = Form("")):
    """上传图片到人物资产目录（新文件，不覆盖旧图）；manifest 记 sha256 / 来源 = upload"""
    cid = A._char(character)
    d, kind, stem = upload_target(cid, target)
    suffix = Path(file.filename or "x.png").suffix.lower()
    if suffix not in A.IMAGE_EXT:
        raise HTTPException(422, f"只接受图片 {sorted(A.IMAGE_EXT)}")
    data = await file.read()
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(413, "图片超过 40 MB")
    sha = hashlib.sha256(data).hexdigest()
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{stem}_{time.strftime('%Y%m%d-%H%M%S')}_{sha[:6]}{suffix}"
    dest.write_bytes(data)
    entry = {"file": dest.name, "kind": kind, "name": name.strip() or Path(file.filename or dest.name).stem,
             "sha256": sha, "source": "upload", "created_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    A._append_manifest(d, entry)
    return {**entry, "file": A.rel(dest), "url": A.file_url(A.rel(dest))}
