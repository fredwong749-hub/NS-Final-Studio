"""
人物资产编辑（docs/api_v1_contract.md §E 后半，canvas-ui-spec-v3 §7.3；fredw-92/W5）：参考图组 + 用途 + image2img + 版本。

资产 asset_id = 衣橱单品 id（服装 / 鞋 / 妆 / 甲 / 发 / 饰品）| 命名造型 look_id（角色形象）| 人物 slug（身份）。

    GET    /api/assets/{asset_id}                     资产详情：参考图组、生成记录（修改链）、版本
    GET    /api/assets/{asset_id}/refs                参考图组
    POST   /api/assets/{asset_id}/refs                multipart 上传：file + role（identity|style|color|item）
    POST   /api/assets/{asset_id}/refs/from-take      {shot, stage, n, role}：定稿 / 候选帧“设为参考”
    POST   /api/assets/{asset_id}/refs/copy           {from_asset, ref_id, role?}：从其他资产复制（契约扩展）
    DELETE /api/assets/{asset_id}/refs/{ref_id}       去掉一张参考（文件保留）
    POST   /api/assets/{asset_id}/gen-jobs            {base?, refs:[{ref_id, role?}], prompt, strength, gpu?, seed?}
                                                      → job（ns_api.jobs 按卡队列，gpu3 Image 2.1；提示词原样传）
    POST   /api/assets/{asset_id}/versions            {job_id | gen_id | file | take:{shot,stage,n}, label}
                                                      → 存为资产新版本（单品 = 新图片版本；造型 = 新预览图）
    POST   /api/assets/{asset_id}/void                {gen_ids?, ref_ids?, by, owner_quote, reason}
                                                      → 标“作废候选”（文件保留；作废参考不能再用作生成参考）
GET /api/assets/characters/{cid} 里并入本模块的 asset_refs / asset_versions / asset_gens / episodes（assets.py）。

数据：data/assets/asset_refs.json、asset_gens.json、asset_versions.json；图片在 assets/characters/<cid>/refs/<asset_id>/。
不做内容检测；提示词由项目方或写作方写，这里原样传给 Image 2.1。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
import uuid
from pathlib import Path, PurePosixPath, PureWindowsPath

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from ns_agent.looks import LookStore
from ns_api import assets as A
from ns_api.looks import get_store
from ns_render import pipeline as P
from ns_schema.looks import CHARACTERS, ItemImage

router = APIRouter(tags=["asset-edit"])
ROLES = ("identity", "style", "color", "item")
ROLE_LABEL = {"identity": "取人物 / 脸", "style": "取风格", "color": "取色彩", "item": "取这一件"}
ROLE_ORDER = {"identity": 0, "item": 1, "style": 2, "color": 3}   # 生成时 图1（底图）之后的排列
# S2（fredw-92/S-back）：场景资产（kind = scene，asset_id = 场景 id sk_*）的参考图用途：空间 | 风格 | 色彩 | 道具
SCENE_ROLES = ("space", "style", "color", "prop")
SCENE_ROLE_LABEL = {"space": "取空间", "style": "取风格", "color": "取色彩", "prop": "取道具"}
SCENE_ROLE_ORDER = {"space": 0, "prop": 1, "style": 2, "color": 3}
ROLE_ALIASES = {"空间": "space", "风格": "style", "色彩": "color", "道具": "prop", "人物": "identity", "单件": "item"}


def roles_for(asset: dict | None) -> tuple[str, ...]:
    return SCENE_ROLES if (asset or {}).get("kind") == "scene" else ROLES


def role_labels(asset: dict | None) -> dict[str, str]:
    return SCENE_ROLE_LABEL if (asset or {}).get("kind") == "scene" else ROLE_LABEL


def norm_role(role: str | None) -> str | None:
    return ROLE_ALIASES.get(role, role) if role else role


def _is_scene_id(asset_id: str, store: LookStore | None = None) -> bool:
    try:
        from ns_api import scene_assets as SA
        return SA.scene_exists(asset_id, store)
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        return False
STRENGTH_FALLBACK = {"small": 0.35, "medium": 0.55, "large": 0.75}
GEN_SIZE = (1088, 1920)
GEN_TIMEOUT_S = 900
_lock = threading.RLock()


def denoise_map() -> dict[str, float]:
    try:   # 与画布精修循环同一处定义（W2 frame_edit.EDIT_DENOISE）
        from ns_render.frame_edit import EDIT_DENOISE
        return dict(EDIT_DENOISE)
    except Exception:  # noqa: BLE001
        return dict(STRENGTH_FALLBACK)


def data_dir() -> Path:
    return P.DATA / "assets"


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S")


def _read(name: str) -> dict:
    try:
        d = json.loads((data_dir() / f"{name}.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _write(name: str, d: dict) -> None:
    p = data_dir() / f"{name}.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(f".tmp{os.getpid()}")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _safe(s: str) -> str:
    return re.sub(r"[^\w-]+", "_", s)


# ---------------------------------------------------------------- 资产解析

def resolve_asset(store: LookStore, asset_id: str) -> dict:
    """→ {kind: item|look|character, id, character, slot?, name}；不存在 404"""
    it = next((i for i in store.wardrobe().items if i.id == asset_id), None)
    if it:
        return {"kind": "item", "id": it.id, "character": it.character, "slot": it.slot, "name": it.name}
    lk = next((x for x in store.lookbook().looks if x.id == asset_id), None)
    if lk:
        return {"kind": "look", "id": lk.id, "character": lk.character, "slot": None, "name": lk.name or lk.id}
    if asset_id in CHARACTERS or (A.chars_dir() / asset_id).is_dir():
        return {"kind": "character", "id": asset_id, "character": asset_id, "slot": None,
                "name": CHARACTERS.get(asset_id, asset_id)}
    if _is_scene_id(asset_id, store):   # S2：场景资产（与人物资产同一套参考图 / 生成 / 版本）
        from ns_api import scene_assets as SA
        return {"kind": "scene", "id": asset_id, "character": None, "slot": None,
                "name": SA.scene_name(asset_id, store)}
    raise HTTPException(404, f"没有这个资产：{asset_id}")


def current_image(store: LookStore, asset: dict, idx=None) -> str | None:
    """资产当前主图（相对项目根）"""
    idx = idx or A.AssetIndex(store)
    if asset["kind"] == "item":
        return idx.item_image(asset["id"], A.SLOT_VARIANT.get(asset["slot"] or "", ("clean", "front", "worn")))
    if asset["kind"] == "look":
        lk = next(x for x in store.lookbook().looks if x.id == asset["id"])
        for f in [lk.preview_image, *lk.reference_images]:
            if f and (A.ROOT / f).is_file():
                return f
        return None
    if asset["kind"] == "scene":
        from ns_api import scene_assets as SA
        return SA.current_plate(asset["id"])
    face = idx.face(asset["id"])
    return face["file"] if face else None


def refs_of(asset_id: str) -> list[dict]:
    return [dict(r) for r in _read("asset_refs").get(asset_id, [])]


def _with_url(r: dict) -> dict:
    out = {**r, "url": A.file_url(r.get("file")),
           "role_label": ROLE_LABEL.get(r.get("role", "")) or SCENE_ROLE_LABEL.get(r.get("role", ""), "")}
    if "version" in r:      # W4b 读 versions[].{id|n}
        out.update(n=r["version"], id=r.get("asset_id"))
    return out


def find_ref(ref_id: str) -> tuple[str, dict] | None:
    for aid, lst in _read("asset_refs").items():
        for r in lst:
            if r.get("ref_id") == ref_id:
                return aid, r
    return None


def resolve_asset_ref(asset_id: str, store: LookStore | None = None) -> str | None:
    """W2 frame-jobs refs[].asset_id → 图片路径（相对项目根）：资产参考图 ref_id 或资产主图"""
    hit = find_ref(asset_id)
    if hit:
        return hit[1]["file"]
    store = store or get_store()
    try:
        return current_image(store, resolve_asset(store, asset_id))
    except HTTPException:
        return None


def _ref_dir(asset: dict) -> Path:
    if asset.get("kind") == "scene":
        return A.ASSETS_DIR / "scenes" / _safe(asset["id"]) / "refs"
    return A.chars_dir() / (asset["character"] or "_shared") / "refs" / _safe(asset["id"])


def add_ref(asset: dict, src_bytes: bytes, suffix: str, role: str, source: str, origin: dict | None = None,
            note: str = "") -> dict:
    role = norm_role(role)
    if role not in roles_for(asset):
        raise HTTPException(422, f"role 只能是 {roles_for(asset)}（{'、'.join(role_labels(asset).values())}）")
    suffix = suffix.lower()
    if suffix not in A.IMAGE_EXT:
        raise HTTPException(422, f"只接受图片 {sorted(A.IMAGE_EXT)}")
    sha = hashlib.sha256(src_bytes).hexdigest()
    ref_id = f"ar-{uuid.uuid4().hex[:10]}"
    d = _ref_dir(asset)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{ref_id}{suffix}"
    dest.write_bytes(src_bytes)
    rec = {"ref_id": ref_id, "asset_id": asset["id"], "file": A.rel(dest), "role": role, "source": source,
           "origin": origin or {}, "sha256": sha, "note": note, "created_at": _now()}
    with _lock:
        allr = _read("asset_refs")
        allr.setdefault(asset["id"], []).append(rec)
        _write("asset_refs", allr)
    return _with_url(rec)


# ---------------------------------------------------------------- 读

def asset_detail(store: LookStore, asset_id: str) -> dict:
    asset = resolve_asset(store, asset_id)
    cur = current_image(store, asset)
    return {"asset": asset, "current_image": cur, "current_url": A.file_url(cur),
            "roles": [{"id": r, "label": role_labels(asset)[r]} for r in roles_for(asset)],
            "strengths": denoise_map(),
            "refs": [_with_url(r) for r in refs_of(asset_id)],
            "gens": [_gen_view(g) for g in _read("asset_gens").get(asset_id, [])],
            "versions": [_with_url(v) for v in _read("asset_versions").get(asset_id, [])]}


def _gen_view(g: dict) -> dict:
    return {**g, "url": A.file_url(g.get("file"))}


def character_extras(store: LookStore, cid: str) -> dict:
    """并进 GET /api/assets/characters/{cid}：本人物全部资产的参考图组 / 生成记录 / 版本 + 出现集数"""
    ids = {cid} | {i.id for i in store.wardrobe().items if i.character == cid} | \
        {lk.id for lk in store.lookbook().looks if lk.character == cid}
    refs, gens, vers = _read("asset_refs"), _read("asset_gens"), _read("asset_versions")
    res = store.resolver()
    episodes = sorted({s.episode for s in res.shots if any(c == cid for c, _ in res.characters(s))})
    assets = []
    idx = A.AssetIndex(store)
    for kind, lst in (("character", [(cid, CHARACTERS.get(cid, cid), None)]),
                      ("look", [(lk.id, lk.name or lk.id, None) for lk in store.lookbook().looks if lk.character == cid]),
                      ("item", [(i.id, i.name, i.slot) for i in store.wardrobe().items if i.character == cid])):
        for aid, name, slot in lst:
            cur = current_image(store, {"kind": kind, "id": aid, "slot": slot, "character": cid}, idx)
            assets.append({"id": aid, "asset_id": aid, "kind": kind, "name": name, "slot": slot,
                           "file": cur, "url": A.file_url(cur),
                           "refs": [_with_url(r) for r in refs.get(aid, [])],
                           "versions": [_with_url(v) for v in vers.get(aid, [])],
                           "gens": [_gen_view(g) for g in gens.get(aid, [])]})
    return {"assets": assets,
            "asset_refs": {a: [_with_url(r) for r in refs[a]] for a in sorted(ids) if refs.get(a)},
            "asset_gens": {a: [_gen_view(g) for g in gens[a]] for a in sorted(ids) if gens.get(a)},
            "asset_versions": {a: [_with_url(v) for v in vers[a]] for a in sorted(ids) if vers.get(a)},
            "episodes": episodes, "ref_roles": [{"id": r, "label": ROLE_LABEL[r]} for r in ROLES]}


@router.get("/api/assets/{asset_id}")
def get_asset(asset_id: str, store: LookStore = Depends(get_store)):
    return asset_detail(store, asset_id)


@router.get("/api/assets/{asset_id}/refs")
def list_refs(asset_id: str, store: LookStore = Depends(get_store)):
    resolve_asset(store, asset_id)
    return [_with_url(r) for r in refs_of(asset_id)]


# ---------------------------------------------------------------- 参考图：上传 / 设为参考 / 复制 / 去掉

MAX_UPLOAD_BYTES = 20 * 1024 * 1024   # fredw-92/B-fix：参考图上传上限 20 MB
UPLOAD_CHUNK = 1024 * 1024


async def read_upload(file: UploadFile, limit: int | None = None) -> bytes:
    """分块读，超过 limit（默认 MAX_UPLOAD_BYTES）→ 413（不把整个大文件先读进内存）"""
    limit = MAX_UPLOAD_BYTES if limit is None else limit
    buf = bytearray()
    while True:
        chunk = await file.read(UPLOAD_CHUNK)
        if not chunk:
            break
        buf += chunk
        if len(buf) > limit:
            raise HTTPException(413, f"文件太大：上限 {limit // (1024 * 1024)} MB")
    return bytes(buf)


@router.post("/api/assets/{asset_id}/refs")
async def upload_ref(asset_id: str, file: UploadFile = File(...), role: str = Form(...), note: str = Form(""),
                     store: LookStore = Depends(get_store)):
    asset = resolve_asset(store, asset_id)
    data = await read_upload(file)
    return add_ref(asset, data, Path(file.filename or "x.png").suffix, role, "upload",
                   {"filename": file.filename}, note)


class FromTakeBody(BaseModel):
    shot: str
    stage: str                      # first | image | last
    n: int
    role: str


STAGE_ALIASES = {"first": "image", "image": "image", "last": "last"}


@router.post("/api/assets/{asset_id}/refs/from-take")
def ref_from_take(asset_id: str, body: FromTakeBody, store: LookStore = Depends(get_store)):
    asset = resolve_asset(store, asset_id)
    stage = STAGE_ALIASES.get(body.stage)
    if not stage:
        raise HTTPException(422, "stage 只能是 first | last")
    try:
        data = P.load_takes(body.shot)
    except Exception as e:  # noqa: BLE001
        raise HTTPException(404, f"没有这个镜头：{body.shot}") from e
    t = next((t for t in data.get("takes") or [] if t.get("stage") == stage and t.get("n") == body.n), None)
    if not t or not t.get("file") or not (P.DATA / t["file"]).is_file():
        raise HTTPException(404, f"{body.shot} 没有 {body.stage} v{body.n} 的图")
    src = P.DATA / t["file"]
    return add_ref(asset, src.read_bytes(), src.suffix, body.role, "take",
                   {"shot": body.shot, "stage": stage, "n": body.n, "file": t["file"]})


class CopyBody(BaseModel):
    from_asset: str
    ref_id: str
    role: str | None = None


@router.post("/api/assets/{asset_id}/refs/copy")
def ref_copy(asset_id: str, body: CopyBody, store: LookStore = Depends(get_store)):
    asset = resolve_asset(store, asset_id)
    r = next((r for r in refs_of(body.from_asset) if r["ref_id"] == body.ref_id), None)
    if not r or not (A.ROOT / r["file"]).is_file():
        raise HTTPException(404, f"{body.from_asset} 没有参考图 {body.ref_id}")
    src = A.ROOT / r["file"]
    return add_ref(asset, src.read_bytes(), src.suffix, body.role or r["role"], "copy",
                   {"asset_id": body.from_asset, "ref_id": body.ref_id})


@router.delete("/api/assets/{asset_id}/refs/{ref_id}")
def ref_delete(asset_id: str, ref_id: str, store: LookStore = Depends(get_store)):
    resolve_asset(store, asset_id)
    with _lock:
        allr = _read("asset_refs")
        lst = allr.get(asset_id, [])
        keep = [r for r in lst if r.get("ref_id") != ref_id]
        if len(keep) == len(lst):
            raise HTTPException(404, f"没有参考图 {ref_id}")
        allr[asset_id] = keep
        _write("asset_refs", allr)
    return [_with_url(r) for r in keep]


# ---------------------------------------------------------------- 生成（image2img）

class GenRef(BaseModel):
    ref_id: str
    role: str | None = None          # 不给 = 用参考图登记的用途


class GenBody(BaseModel):
    base: str | None = None          # 底图：本资产参考图 ref_id | "current"（资产当前主图）| 相对项目根的图片路径；不给 = 纯参考生成
    refs: list[GenRef] = Field(default_factory=list)
    prompt: str
    strength: str | float = "medium"  # small | medium | large（或 0–1 的 denoise）；只在有底图时生效
    gpu: int | str | None = None
    seed: int | None = None
    negative: str = ""
    width: int | None = None
    height: int | None = None
    parent: str | None = None        # 修改链：上一次生成的 gen_id
    # fredw-92/ND（只增不改）：出图参数同 frame-jobs（ns_render.image_params）。preset = render_quality.json 预设 id，
    # params = 覆盖；都不给 = 旧行为（Turbo 默认图，无 LoRA）。预设里的 "@identity" = 本资产所属人物的身份 LoRA
    # （config/auto_lora_triggers.json，如林晚 lin_wan_qi_v1），加载时触发词放在提示词最前（同编译器）。
    preset: str | None = None
    params: dict | None = None
    label: str = ""                  # 写进生成记录（如“候选·待复审”）


def _path_ok(rel: str) -> Path:
    # fredw-92/B-fix：以 "/" 开头或带盘符的路径会让 base / rel 直接跳到盘根（Windows 上 ROOT / "/x.png" → D:\x.png）
    if (not rel or "\\" in rel or ":" in rel or rel.startswith("/") or ".." in rel.split("/")
            or PureWindowsPath(rel).anchor or PurePosixPath(rel).is_absolute()):
        raise HTTPException(422, f"图片路径不合法：{rel!r}")
    for base in (A.ROOT, P.DATA):
        p = base / rel
        try:
            inside = p.resolve().is_relative_to(Path(base).resolve())
        except (OSError, ValueError):
            inside = False
        if inside and p.is_file() and p.suffix.lower() in A.IMAGE_EXT:
            return p
    raise HTTPException(422, f"找不到图片：{rel}")


def plan_gen(store: LookStore, asset_id: str, body: GenBody) -> dict:
    """校验并排好 图1、图2…：底图第一，其余按用途 人物 → 单件 → 风格 → 色彩（同用途保持请求顺序）"""
    asset = resolve_asset(store, asset_id)
    if not body.prompt.strip():
        raise HTTPException(422, "prompt 不能为空（提示词由项目方或写作方写，原样传）")
    dm = denoise_map()
    if isinstance(body.strength, str):
        if body.strength not in dm:
            raise HTTPException(422, f"strength 只能是 {' | '.join(dm)}（或 0–1 的数）")
        denoise = dm[body.strength]
    else:
        if not 0 < float(body.strength) <= 1:
            raise HTTPException(422, "strength 数值须在 (0, 1]")
        denoise = float(body.strength)
    base = None
    if body.base:
        if body.base == "current":
            base = current_image(store, asset)
            if not base:
                raise HTTPException(409, "这个资产还没有图，不能用“当前图”作底图；先上传或不选底图")
        else:
            hit = find_ref(body.base)
            base = hit[1]["file"] if hit else body.base
        p = _path_ok(base)
        base = {"path": base, "abs": str(p)}
    refs = []
    for k, g in enumerate(body.refs):
        hit = find_ref(g.ref_id)
        if not hit:
            raise HTTPException(422, f"没有参考图 {g.ref_id}（先上传 / 设为参考 / 复制到资产上）")
        role = norm_role(g.role) or hit[1].get("role") or ("space" if asset["kind"] == "scene" else "item")
        if role not in roles_for(asset):
            raise HTTPException(422, f"role 只能是 {roles_for(asset)}")
        if hit[1].get("void"):
            raise HTTPException(422, f"参考图 {g.ref_id} 已作废（{hit[1]['void'].get('reason') or '作废候选'}），不能再用作参考")
        p = _path_ok(hit[1]["file"])
        refs.append({"ref_id": g.ref_id, "role": role, "path": hit[1]["file"], "abs": str(p), "k": k})
    order = SCENE_ROLE_ORDER if asset["kind"] == "scene" else ROLE_ORDER
    refs.sort(key=lambda r: (order[r["role"]], r["k"]))
    from ns_render import endpoints as EP
    from ns_api import jobs as J
    try:   # G36：不指定道 → 自动分（偏好 gpu33:0，任意空闲道）
        gpu = J.resolve_lane(body.gpu, "image")
    except ValueError:
        raise HTTPException(400, f"gpu 只能是 {J.GPUS}")
    if len(refs) + (1 if base else 0) > A.QWEN_MAX_REFS:
        raise HTTPException(422, f"参考图最多 {A.QWEN_MAX_REFS} 张（含底图）")
    images = ([{"slot": 1, "role": "base", "path": base["path"]}] if base else []) + \
        [{"slot": i, "role": r["role"], "ref_id": r["ref_id"], "path": r["path"]}
         for i, r in enumerate(refs, start=2 if base else 1)]
    eff, ident = None, []
    if body.preset or body.params:
        from ns_render import image_params as IP
        over = dict(body.params or {})
        if body.width:
            over.setdefault("width", body.width)
        if body.height:
            over.setdefault("height", body.height)
        try:
            eff = IP.resolve(body.preset, over)
        except IP.ParamError as e:
            raise HTTPException(422, str(e)) from e
        if eff.get("tier") == "final":
            raise HTTPException(422, "资产生成只支持预览档预设（定稿档走镜头 frame-jobs）")
        ident = identity_loras(asset)
    return {"asset": asset, "base": base, "refs": refs, "images": images, "denoise": denoise if base else 1.0,
            "gpu": gpu, "prompt": body.prompt, "negative": body.negative, "seed": body.seed,
            "strength": body.strength, "size": (body.width or GEN_SIZE[0], body.height or GEN_SIZE[1]),
            "parent": body.parent, "eff": eff, "identity": ident, "label": body.label}


def identity_loras(asset: dict) -> list[dict]:
    """本资产所属人物的出图身份 LoRA（config/auto_lora_triggers.json，按中文名）→ [{file, strength, trigger}]"""
    cid = asset.get("character")
    if not cid:
        return []
    try:
        from ns_agent.compiler import auto_lora_triggers
        es = auto_lora_triggers().get(CHARACTERS.get(cid, cid)) or []
    except Exception:  # noqa: BLE001
        return []
    return [{"file": str(e["file"]), "strength": float(e.get("strength") or 0.8), "trigger": e.get("trigger") or ""}
            for e in es if e.get("file") and (e.get("kind") or "image") == "image"]


def _fit32(w: int, h: int, area: int) -> tuple[int, int]:
    k = (area / (w * h)) ** 0.5
    return max(32, round(w * k / 32) * 32), max(32, round(h * k / 32) * 32)


def run_gen(client, job: dict, plan: dict) -> dict:
    """在 ns_api.jobs 的 GPU 道线程里执行：上传 → Image 2.1 编辑（有底图 = init_image + denoise）→ 存图 + 记修改链"""
    from ns_api import jobs as J
    from ns_render import workflows as W
    asset = plan["asset"]
    w, h = plan["size"]
    if plan["base"]:
        try:
            from PIL import Image
            with Image.open(plan["base"]["abs"]) as im:
                w, h = _fit32(im.width, im.height, GEN_SIZE[0] * GEN_SIZE[1])
        except Exception:  # noqa: BLE001
            pass
    names = [client.upload_image(Path(x), subfolder="ns_final/assets")
             for x in ([plan["base"]["abs"]] if plan["base"] else []) + [r["abs"] for r in plan["refs"]]]
    seed = plan["seed"] if plan["seed"] is not None else P.seed_for(f"asset-gen/{asset['id']}", int(time.time()))
    prefix = f"ns_final/assets/{_safe(asset['id'])}"
    eff = plan.get("eff")
    prompt, loras, trig = plan["prompt"], [], []
    if eff is not None:
        if eff.get("seed") is not None and plan["seed"] is None:
            seed = int(eff["seed"])
        # 身份 LoRA 先按配置强度挂上，再由 image_params.apply 按预设的 "@identity" 行改强度 / 去掉
        loras = [(x["file"], x["strength"]) for x in plan.get("identity") or []]
        uses_ident = any(x.get("name") == "@identity" for x in (eff.get("loras") or [])) or eff.get("loras") is None
        trig = [x["trigger"] for x in plan.get("identity") or [] if x.get("trigger") and uses_ident]
        if trig:
            prompt = ", ".join(trig) + ", " + prompt
    if plan["base"]:
        wf = W.qwen_edit(prompt, plan["negative"], names, w, h, seed, prefix,
                         init_image=names[0], denoise=plan["denoise"], loras=loras)
    elif names:
        wf = W.qwen_edit(prompt, plan["negative"], names, w, h, seed, prefix, crop=False, loras=loras)
    else:
        wf = W.qwen_t2i(prompt, plan["negative"], w, h, seed, prefix, loras=loras)
    effective = None
    if eff is not None:
        from ns_render import image_params as IP
        from ns_render import frame_edit as FE
        IP.apply(wf, eff, FE.identity_lora_files() | {x["file"] for x in plan.get("identity") or []})
        effective = IP.describe(wf)
        if effective is not None:
            effective["seed"] = seed
    if J.cancelled(job):
        raise J.Cancelled()
    t0 = time.monotonic()
    entry = J.wait_prompt(client, job, client.submit(wf), GEN_TIMEOUT_S)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
    gen_id = f"ag-{uuid.uuid4().hex[:10]}"
    dest = _ref_dir(asset) / "gen" / f"{gen_id}_s{seed}.png"
    client.download(item, dest)
    rec = {"gen_id": gen_id, "asset_id": asset["id"], "job_id": job.get("job_id"), "file": A.rel(dest),
           "parent": plan["parent"], "prompt": plan["prompt"], "negative": plan["negative"], "seed": seed,
           "strength": plan["strength"], "denoise": plan["denoise"], "images": plan["images"],
           "workflow": "qwen_edit_init" if plan["base"] else ("qwen_edit_multi" if names else "qwen_t2i"),
           "size": [w, h], "gpu": plan["gpu"], "seconds": round(time.monotonic() - t0, 1), "created_at": _now()}
    if eff is not None:
        rec.update(preset=eff.get("preset"), effective=effective, triggers=trig,
                   size=[int(effective["width"]), int(effective["height"])] if effective and effective.get("width") else [w, h])
        # LCA：预设的后处理（放大出图缩回 + 锐化）同 frame-jobs；原图保留为 raw_file，effective 记实际值
        from ns_render import image_params as IP
        post = IP.post_file(dest, eff)
        if effective is not None:
            effective.update(IP.post_effective(eff, effective, post))
        if post:
            rec.update(raw_file=rec["file"], file=A.rel(Path(post["path"])), size=post["size"])
    if plan.get("label"):
        rec["label"] = plan["label"]
    with _lock:
        allg = _read("asset_gens")
        allg.setdefault(asset["id"], []).append(rec)
        _write("asset_gens", allg)
    return {"file": rec["file"], "url": A.file_url(rec["file"]), "gen_id": gen_id, "result": rec}


@router.post("/api/assets/{asset_id}/gen-jobs")
def create_gen_job(asset_id: str, body: GenBody, store: LookStore = Depends(get_store)):
    from ns_api import jobs as J
    from ns_render import endpoints as EP
    plan = plan_gen(store, asset_id, body)
    params = {**body.model_dump(exclude_none=True), "images": plan["images"], "denoise": plan["denoise"]}
    return J.submit("asset_gen", None, plan["gpu"], lambda client, job: run_gen(client, job, plan),
                    params=params, eta_s=60.0, asset_id=asset_id, url=EP.url_for_gpu(plan["gpu"]))


# ---------------------------------------------------------------- 作废候选（fredw-92/CHR）
# 生成记录 / 参考图加 void = {by, owner_quote, reason, at}，label 改为“作废候选 · …”（原 label 存 label_before）。
# 只改记录，不删文件；作废的参考图不能再用作生成参考（plan_gen 422）。项目方作废须带原话。

VOID_LABEL = "作废候选"


class VoidBody(BaseModel):
    gen_ids: list[str] = Field(default_factory=list)
    ref_ids: list[str] = Field(default_factory=list)
    by: str                           # owner | agent:<名>
    owner_quote: str = ""             # by=owner 时必填：项目方原话
    reason: str = ""


def _void_label(old: str) -> str:
    if old.startswith(VOID_LABEL):
        return old
    rest = old.replace("候选·待复审", "").strip(" ·")
    return f"{VOID_LABEL} · {rest}" if rest else VOID_LABEL


def void_records(asset_id: str, body: VoidBody) -> dict:
    if not body.gen_ids and not body.ref_ids:
        raise HTTPException(422, "需要 gen_ids 或 ref_ids")
    if not body.by.strip():
        raise HTTPException(422, "by 不能为空")
    if body.by == "owner" and not body.owner_quote.strip():
        raise HTTPException(422, "项目方作废须带原话（owner_quote）")
    mark = {"by": body.by, "owner_quote": body.owner_quote, "reason": body.reason, "at": _now()}
    with _lock:
        allg, allr = _read("asset_gens"), _read("asset_refs")
        gl, rl = allg.get(asset_id, []), allr.get(asset_id, [])
        miss = [g for g in body.gen_ids if not any(x.get("gen_id") == g for x in gl)] + \
            [r for r in body.ref_ids if not any(x.get("ref_id") == r for x in rl)]
        if miss:
            raise HTTPException(404, f"{asset_id} 没有这些记录：{'、'.join(miss)}")
        for lst, ids, key in ((gl, set(body.gen_ids), "gen_id"), (rl, set(body.ref_ids), "ref_id")):
            for x in lst:
                if x.get(key) in ids:
                    if "label_before" not in x:
                        x["label_before"] = x.get("label", "")
                    x["label"] = _void_label(x.get("label") or x.get("note") or "")
                    x["void"] = mark
        if body.gen_ids:
            _write("asset_gens", allg)
        if body.ref_ids:
            _write("asset_refs", allr)
    return {"asset_id": asset_id, "gens": [_gen_view(g) for g in gl if g.get("gen_id") in set(body.gen_ids)],
            "refs": [_with_url(r) for r in rl if r.get("ref_id") in set(body.ref_ids)]}


@router.post("/api/assets/{asset_id}/void")
def post_void(asset_id: str, body: VoidBody, store: LookStore = Depends(get_store)):
    """把生成记录 / 参考图标为“作废候选”（文件保留）"""
    resolve_asset(store, asset_id)
    return void_records(asset_id, body)


# ---------------------------------------------------------------- 存为资产新版本

class VersionTake(BaseModel):
    shot: str
    stage: str
    n: int


class VersionBody(BaseModel):
    job_id: str | None = None
    gen_id: str | None = None
    file: str | None = None
    take: VersionTake | None = None
    label: str = ""
    variant: str = "clean"          # 单品图片的 variant（clean | worn | front | 3q | side | back）
    in_place: bool = False          # False（默认）= 资产库新增一个资产（<id>-vN，原资产不动、不让任何镜头过期）；
                                    # True = 原资产上加新图片 / 新预览（用到它的镜头全部过期）
    # UX6（A_assets_ia B6）：把“新版本”和“另存为新资产”分开。mode=version → 进同一资产的版本链（= in_place），
    # mode=save_as → 另存为新资产（= 旧默认，也可走 POST /api/assets/{id}/fork）；不填 = 按 in_place（兼容旧调用）
    mode: str | None = None


def _version_source(asset_id: str, body: VersionBody) -> tuple[Path, dict]:
    if body.job_id:
        from ns_api import jobs as J
        job = J.get(body.job_id)
        if not job or job.get("state") != "done" or not job.get("file"):
            raise HTTPException(409, f"任务 {body.job_id} 还没完成或没有结果图")
        return _path_ok(job["file"]), {"job_id": body.job_id, "gen_id": job.get("gen_id")}
    if body.gen_id:
        g = next((g for g in _read("asset_gens").get(asset_id, []) if g.get("gen_id") == body.gen_id), None)
        if not g:
            raise HTTPException(404, f"{asset_id} 没有生成记录 {body.gen_id}")
        if g.get("void"):
            raise HTTPException(409, f"生成记录 {body.gen_id} 已作废（{VOID_LABEL}），不能存为版本")
        return _path_ok(g["file"]), {"gen_id": body.gen_id}
    if body.take:
        stage = STAGE_ALIASES.get(body.take.stage)
        data = P.load_takes(body.take.shot)
        t = next((t for t in data.get("takes") or [] if t.get("stage") == stage and t.get("n") == body.take.n), None)
        if not t or not (P.DATA / t["file"]).is_file():
            raise HTTPException(404, f"{body.take.shot} 没有 {body.take.stage} v{body.take.n}")
        return P.DATA / t["file"], {"take": body.take.model_dump()}
    if body.file:
        return _path_ok(body.file), {"file": body.file}
    raise HTTPException(422, "需要 job_id / gen_id / take / file 之一")


def _new_id(base: str, taken: set[str], start: int) -> tuple[str, int]:
    n = start
    while f"{base}-v{n}" in taken:
        n += 1
    return f"{base}-v{n}", n


@router.post("/api/assets/{asset_id}/versions")
def save_version(asset_id: str, body: VersionBody, store: LookStore = Depends(get_store)):
    """存为资产新版本（spec §7.3）。默认资产库新增：单品 → 复制成新单品 <id>-vN（新图片作主图 / 参考）；
    造型 → 复制成新造型 <id>-vN（新预览图，形象数 +1）。原资产不动，返回新 asset_id，
    前端接着用 /api/shots/{id}/refs/apply（scope=shot “只这一镜” / scope=episode “本集默认”）。
    in_place=True：在原资产上加版本（返回同一个 asset_id + 受影响镜头）。人物身份底图不在这里改。"""
    asset = resolve_asset(store, asset_id)
    if asset["kind"] == "character":
        raise HTTPException(422, "人物身份底图（plates/master）不在这里改版本；请存到具体形象或单品上")
    if body.mode is not None:
        if body.mode not in ("version", "save_as"):
            raise HTTPException(422, "mode 只能是 version（进版本链）| save_as（另存为新资产）")
        body.in_place = body.mode == "version"
    src, origin = _version_source(asset_id, body)
    if asset["kind"] == "scene":   # S2：场景底图版本链（定稿另走 POST /api/assets/scenes/{id}/plate）
        from ns_api import scene_assets as SA
        return SA.save_scene_version(asset, src, origin, body)
    data = src.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    now = _now()
    prev = _read("asset_versions").get(asset_id, [])
    if asset["kind"] == "item":
        if body.variant not in A.VARIANTS:
            raise HTTPException(422, f"variant 只能是 {A.VARIANTS}")
        w0 = store.wardrobe()
        item = next(i for i in w0.items if i.id == asset_id)
        if body.in_place:
            new_id, version = asset_id, 1 + max((im.version for im in item.images), default=0)
        else:
            new_id, version = _new_id(asset_id, {i.id for i in w0.items}, len(prev) + 2)
        d = A.upload_dir(item)
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{new_id}_{body.variant}_v{version}{src.suffix.lower()}"
        dest.write_bytes(data)
        img = ItemImage(file=A.rel(dest), variant=body.variant, version=version, sha256=sha, source="generated",
                        created_at=now)
        A._append_manifest(d, {"file": dest.name, "kind": f"item/{item.slot}", "name": item.name, "item_id": new_id,
                               "variant": body.variant, "version": version, "sha256": sha, "source": "generated",
                               "label": body.label, "created_at": now, "origin": {**origin, "from_asset": asset_id}})
        if body.in_place:
            def fn():
                w = store.wardrobe()
                it = next(i for i in w.items if i.id == asset_id)
                it.images.append(img)
                it.version = max(it.version, version)
                it.reference_images = [img.file] + [r for r in it.reference_images if r != img.file]
                store._write("wardrobe", w)
            affected = store._mutate(fn)
        else:
            new = item.model_copy(deep=True, update={
                "id": new_id, "name": f"{item.name} · {body.label or f'v{version}'}", "images": [img],
                "reference_images": [img.file], "version": version, "source": "manual", "needs_review": False,
                "notes": [f"由 {asset_id} 生成的新版本（{now}）"]})
            affected = store.upsert_item(new)
    else:
        b0 = store.lookbook()
        lk = next(x for x in b0.looks if x.id == asset_id)
        if body.in_place:
            new_id, version = asset_id, lk.version + 1
        else:
            new_id, version = _new_id(asset_id, {x.id for x in b0.looks}, len(prev) + 2)
        d = A.chars_dir() / lk.character / "looks" / _safe(asset_id)
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{_safe(new_id)}_v{version}{src.suffix.lower()}"
        dest.write_bytes(data)
        f = A.rel(dest)
        if body.in_place:
            new = lk.model_copy(update={"version": version, "preview_image": f,
                                        "reference_images": [f] + [r for r in lk.reference_images if r != f]})
        else:
            new = lk.model_copy(deep=True, update={
                "id": new_id, "name": f"{lk.name or lk.id} · {body.label or f'v{version}'}", "label": None,
                "preview_image": f, "reference_images": [f], "version": version, "needs_review": False,
                "notes": [f"由 {asset_id} 生成的新版本（{now}）"]})
        try:
            affected = store.upsert_look(new)
        except (KeyError, ValueError) as e:
            raise HTTPException(422, str(e)) from e
    rec = {"version": version, "asset_id": new_id, "from_asset": asset_id, "kind": asset["kind"],
           "in_place": body.in_place, "file": A.rel(dest), "label": body.label, "origin": origin, "sha256": sha,
           "created_at": now}
    with _lock:
        allv = _read("asset_versions")
        allv.setdefault(asset_id, []).append(rec)
        if new_id != asset_id:
            allv.setdefault(new_id, []).append(rec)
        _write("asset_versions", allv)
    try:
        import sys
        app = sys.modules.get("ns_api.app")
        if app is not None and hasattr(app, "_summary_cache"):
            app._summary_cache.invalidate()
    except Exception:  # noqa: BLE001
        pass
    return {**_with_url(rec), **affected.model_dump()}
