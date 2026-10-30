"""
角色资产（canvas-ui-spec-v2 §3.4 / §3.5.4–3.5.6，REQUIREMENTS E5、E6）。

文件布局（资产会话交付）：
    assets/characters/<id>/{plates/, expressions/, items/<outfit|shoes|nails|hair|makeup|accessory>/, looks/}
    任意子目录可以有 manifest.json：列表，或 {"items": [...]}；每条 {file, kind, name, prompt, seed, model,
    references, sha256, ...}，file 相对 manifest 所在目录。
没有 manifest 的图片也会列出（source = loose）。根目录下的单张图（如 lin_wan.png）作为 portrait，
没有正面 plate 时当脸图用。

接口：
    GET  /api/assets/characters                      全部角色的资产清单 + 衣橱单品（带图）+ 命名造型
    GET  /api/assets/file?path=                      读 assets/ 下的文件
    POST /api/assets/characters/{id}/import          manifest 里的单品登记到 data/looks/wardrobe.json（sha256 去重）
    POST /api/looks/wardrobe/items/{id}/images       给单品上传新图（multipart: file, variant）→ AffectedShots
    GET  /api/looks/shots/{id}/refs                  本镜送进模型的参考图组（顺序 + 截断标记，E6）
    GET  /api/looks/shots?episode=n                  一集每镜的人物信息（脸图、造型字母、单品缩略图）
生成（POST /api/assets/characters/{id}/generate）在 app.py 里入队，执行函数 generate_asset 在本模块。
"""
import hashlib
import json
import re
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ns_agent.looks import ROOT, LookStore, resolve_character
from ns_api.looks import get_store
from ns_schema.looks import CHARACTERS, SLOTS, ItemImage, WardrobeItem

router = APIRouter(tags=["assets"])

ASSETS_DIR = ROOT / "assets"                 # 测试里 monkeypatch
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
PLATE_VIEWS = ("front", "3q", "side", "back")
MASTER_ALIASES = ("master", "母版", "hero")      # plates/master.png = 写实母版（资产页大图，脸图兜底）
PLATE_ALIASES = {"front": ("front", "正"), "3q": ("3q", "34", "three_quarter", "3-4"), "side": ("side", "profile", "侧"),
                 "back": ("back", "背")}
ITEM_CATS = ("outfit", "shoes", "nails", "hair", "makeup", "accessory")
CAT_ALIASES = {"heels": "shoes", "shoe": "shoes", "nail": "nails", "clothes": "outfit", "outfits": "outfit",
               "accessories": "accessory", "jewelry": "accessory", "decor": "accessory", "other": "accessory"}
ABBR = {"lin_wan": "lw", "gu_chen": "gc", "chen_yu": "cy"}
QWEN_MAX_REFS = 10                            # Qwen Image 2.1 参考图上限（ComfyUI 节点支持 16，按规范取 10）
REF_RE = re.compile(r"REF-[A-Z]+-\d+")
VARIANTS = ("clean", "worn", "front", "3q", "side", "back")


def chars_dir() -> Path:
    return ASSETS_DIR / "characters"


def rel(p: Path) -> str:
    return p.resolve().relative_to(ROOT.resolve()).as_posix()


def file_url(relpath: str | None) -> str | None:
    """相对项目根的路径 → URL；只认 assets/ 下的真实文件（REF-xx 之类返回 None）"""
    if not relpath:
        return None
    p = (ROOT / relpath).resolve()
    if not p.is_file() or not p.is_relative_to(ASSETS_DIR.resolve()):
        return None
    return f"/api/assets/file?path={relpath}&v={int(p.stat().st_mtime)}"


def sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _norm_cat(c: str) -> str:
    c = c.lower()
    return CAT_ALIASES.get(c, c)


def _plate_view(name: str) -> str | None:
    n = name.lower()
    if any(a in n for a in MASTER_ALIASES):
        return "master"
    for v in ("3q", "front", "side", "back"):          # 3q 先于 front（"3q_front" 之类）
        if any(a in n for a in PLATE_ALIASES[v]):
            return v
    return None


def classify(kind: str | None, relparts: tuple[str, ...], stem: str) -> tuple[str, str]:
    """→ (group, category)。group: plate | expression | item | look | portrait | other"""
    if kind:
        head, _, tail = kind.partition("/")
        head = head.lower().rstrip("s")
        if head == "plate":
            return "plate", tail or _plate_view(stem) or "front"
        if head == "expression":
            return "expression", tail or stem
        if head == "item":
            return "item", _norm_cat(tail or (relparts[1] if len(relparts) > 2 else "accessory"))
        if head == "look":
            return "look", tail or stem
    top = relparts[0] if len(relparts) > 1 else ""
    if top == "plates":
        return "plate", _plate_view(stem) or "front"
    if top == "expressions":
        return "expression", stem
    if top == "items" and len(relparts) > 2:
        return "item", _norm_cat(relparts[1])
    if top == "looks":
        return "look", relparts[1] if len(relparts) > 2 else stem
    if len(relparts) == 1:
        return "portrait", stem
    return "other", top


def _read_manifest(p: Path) -> list[dict]:
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if isinstance(data, dict):
        data = data.get("items") or data.get("entries") or data.get("files") or []
    return [e for e in data if isinstance(e, dict) and e.get("file")]


def scan_character(cid: str) -> list[dict]:
    """一个角色目录下的全部资产条目（manifest 优先，其余图片作为 loose）"""
    base = chars_dir() / cid
    if not base.is_dir():
        return []
    entries, seen = [], set()
    for m in sorted(base.rglob("manifest.json")):
        for e in _read_manifest(m):
            f = (m.parent / e["file"]).resolve()
            try:
                parts = f.relative_to(base.resolve()).parts
            except ValueError:
                continue
            group, cat = classify(e.get("kind"), parts, f.stem)
            seen.add(f)
            entries.append({
                **{k: e.get(k) for k in ("name", "design", "prompt", "seed", "model", "workflow", "references",
                                         "sha256", "created_at", "tags", "description")},
                "file": rel(f) if f.exists() else (m.parent / e["file"]).relative_to(ROOT).as_posix(),
                "kind": e.get("kind") or f"{group}/{cat}", "group": group, "category": cat,
                "manifest": rel(m), "source": "manifest", "missing_file": not f.is_file(),
            })
    for f in sorted(base.rglob("*")):
        if f.suffix.lower() not in IMAGE_EXT or not f.is_file() or f.resolve() in seen:
            continue
        parts = f.relative_to(base).parts
        group, cat = classify(None, parts, f.stem)
        if group == "other":
            continue
        entries.append({"file": rel(f), "kind": f"{group}/{cat}", "group": group, "category": cat,
                        "name": f.stem, "source": "loose", "manifest": None, "missing_file": False})
    for e in entries:
        e["url"] = file_url(e["file"])
    return entries


def character_ids() -> list[str]:
    extra = sorted(p.name for p in chars_dir().iterdir() if p.is_dir() and p.name not in CHARACTERS) \
        if chars_dir().is_dir() else []
    return list(CHARACTERS) + extra


class AssetIndex:
    """一次请求里用的资产索引：每个角色的脸图、单品缩略图"""

    def __init__(self, store: LookStore):
        self.entries = {c: scan_character(c) for c in character_ids()}
        self.items = {i.id: i for i in store.wardrobe().items}

    def face(self, cid: str) -> dict | None:
        es = self.entries.get(cid, [])
        for cat in ("front", "master"):
            for e in es:
                if e["group"] == "plate" and e["category"] == cat and e["url"]:
                    return e
        return next((e for e in es if e["group"] == "portrait" and e["url"]), None)

    def hero(self, cid: str) -> dict | None:
        """资产页大图：写实母版 → 正面 plate → 根目录定妆原图"""
        es = self.entries.get(cid, [])
        for cat in ("master", "front"):
            e = next((e for e in es if e["group"] == "plate" and e["category"] == cat and e["url"]), None)
            if e:
                return e
        return next((e for e in es if e["group"] == "portrait" and e["url"]), None)

    def face_url(self, cid: str) -> str | None:
        f = self.face(cid)
        return f["url"] if f else None

    def item_image(self, iid: str, prefer: tuple[str, ...] = ("clean", "front", "worn")) -> str | None:
        """单品主图（相对项目根）：images 按 variant 偏好 + 最新版本；没有就用 reference_images 里的真实文件"""
        it = self.items.get(iid)
        if not it:
            return None
        imgs = [im for im in it.images if (ROOT / im.file).is_file()]
        for v in prefer:
            cand = sorted((im for im in imgs if im.variant == v), key=lambda im: -im.version)
            if cand:
                return cand[0].file
        if imgs:
            return max(imgs, key=lambda im: im.version).file
        return next((r for r in it.reference_images if (ROOT / r).is_file()), None)

    def item_thumb(self, iid: str) -> str | None:
        f = self.item_image(iid)
        return file_url(f) if f else None


def item_has_image(it: WardrobeItem) -> bool:
    return any((ROOT / im.file).is_file() for im in it.images) or any((ROOT / r).is_file() for r in it.reference_images)


def item_usage(store: LookStore) -> dict[str, dict]:
    """单品 → 被哪些命名造型 / 多少镜引用（镜头按解析结果统计，含 D 状态里的装饰）"""
    res = store.resolver()
    book = store.lookbook()
    use: dict[str, dict] = {}
    for lk in book.looks:
        for ids in lk.items.values():
            for i in ids:
                use.setdefault(i, {"looks": set(), "shots": set()})["looks"].add(lk.id)
    for s in res.shots:
        for c, src in res.characters(s):
            r = res.core(c, s.episode, s.id, src)
            if r.look_id:
                use.setdefault(f"look:{r.look_id}", {"looks": set(), "shots": set()})["shots"].add(s.id)
            ids = [i for v in r.slots.values() for i in v.items]
            st = res.states.get(r.d_state.value or "")
            ids += st.items if st else []
            for i in ids:
                use.setdefault(i, {"looks": set(), "shots": set()})["shots"].add(s.id)
    return use


# ---------------------------------------------------------------- 参考图组（E6）

REF_ORDER = (("face", "脸 plate"), ("outfit", "上身服装"), ("shoes", "鞋特写"), ("nails", "美甲特写"),
             ("hair", "发型"), ("makeup", "妆容"), ("accessory", "饰品"))
SLOT_VARIANT = {"outfit": ("worn", "clean", "front"), "shoes": ("clean", "worn"), "nails": ("clean", "worn"),
                "hair": ("front", "clean", "worn"), "makeup": ("front", "clean", "worn"), "accessory": ("clean", "worn")}


def shot_refs(store: LookStore, shot_id: str, idx: AssetIndex | None = None, limit: int = QWEN_MAX_REFS) -> dict:
    """本镜实际会送进图像模型的参考图组：脸 plate → 上身服装 → 鞋 → 美甲 → 发型 → 妆 → 饰（→ 场景，暂无场景资产）。
    超过 limit 的标 truncated（改用文字描述）；没有图片的单品标 text_only。"""
    idx = idx or AssetIndex(store)
    looks = store.shot_looks(shot_id)
    refs: list[dict] = []
    for r in looks.characters:
        face = idx.face(r.character)
        refs.append({"character": r.character, "name": r.name, "role": "face", "label": f"{r.name} 脸",
                     "item_id": None, "file": face["file"] if face else None,
                     "url": face["url"] if face else None, "text_only": face is None})
        for slot, label in REF_ORDER[1:]:
            for iid in r.slots.get(slot).items if r.slots.get(slot) else []:
                it = idx.items.get(iid)
                f = idx.item_image(iid, SLOT_VARIANT.get(slot, ("clean",)))
                refs.append({"character": r.character, "name": r.name, "role": slot,
                             "label": f"{r.name} {label}：{it.name if it else iid}", "item_id": iid,
                             "file": f, "url": file_url(f), "text_only": f is None})
    # 角色多时按「每个角色的脸 → 各角色同类单品」交错：先保证每个人的脸都进
    order = {k: n for n, (k, _) in enumerate(REF_ORDER)}
    refs.sort(key=lambda x: order.get(x["role"], 99))
    n = 0
    seen: set[str] = set()
    for x in refs:
        x["duplicate"] = bool(x["file"] and x["file"] in seen)
        if x["text_only"] or x["duplicate"]:
            x["truncated"] = False
            continue
        seen.add(x["file"])
        n += 1
        x["index"] = n
        x["truncated"] = n > limit
    used = [x for x in refs if not x["text_only"] and not x["duplicate"] and not x["truncated"]]
    return {"shot_id": shot_id, "limit": limit, "model": "qwen_image_2.1", "count": len(used),
            "refs": refs, "files": [x["file"] for x in used],
            "anchor_lines": [f"@图{x['index']} 作为{x['label']}参考，只采用其外观" for x in used]}


# ---------------------------------------------------------------- 角色清单

def _wardrobe_view(it: WardrobeItem, idx: AssetIndex, usage: dict) -> dict:
    u = usage.get(it.id, {"looks": set(), "shots": set()})
    return {**it.model_dump(), "image_urls": [{**im.model_dump(), "url": file_url(im.file)} for im in it.images],
            "thumb_url": idx.item_thumb(it.id), "has_image": item_has_image(it),
            "reference_urls": [file_url(r) for r in it.reference_images],
            "used_by_looks": sorted(u["looks"]), "used_by_shots": len(u["shots"])}


def character_assets(store: LookStore, cid: str, idx: AssetIndex, usage: dict) -> dict:
    es = idx.entries.get(cid) or scan_character(cid)
    w, book, sched = store.wardrobe(), store.lookbook(), store.schedule()
    plates = {v: next((e for e in es if e["group"] == "plate" and e["category"] == v), None) for v in PLATE_VIEWS}
    items: dict[str, list] = {c: [] for c in ITEM_CATS}
    for e in es:
        if e["group"] == "item":
            items.setdefault(e["category"], []).append(e)
    shas = {im.sha256: i.id for i in w.items for im in i.images if im.sha256}
    for lst in items.values():
        for e in lst:
            sha = e.get("sha256")
            if not sha and not e["missing_file"]:      # manifest 没写 sha256 / loose 文件：按文件算，和导入时一致
                sha = e["sha256"] = sha256_file(ROOT / e["file"])
            e["registered_item_id"] = shas.get(sha or "")
    wardrobe = [_wardrobe_view(i, idx, usage) for i in w.items if i.character == cid]
    looks = []
    for lk in book.looks:
        if lk.character != cid:
            continue
        looks.append({**lk.model_dump(), "preview_url": file_url(lk.preview_image),
                      "reference_urls": [file_url(r) for r in lk.reference_images],
                      "used_by_shots": len(usage.get(f"look:{lk.id}", {}).get("shots", ()))})
    missing = [f"plate/{v}" for v, e in plates.items() if not e]
    in_use = [i for i in wardrobe if i["used_by_shots"] or i["used_by_looks"]]
    missing += [f"item/{i['slot']}/{i['id']}" for i in in_use if not i["has_image"]]
    return {
        "id": cid, "name": CHARACTERS.get(cid, cid), "dir": f"assets/characters/{cid}",
        "dir_exists": (chars_dir() / cid).is_dir(), "face_url": idx.face_url(cid),
        "master": next((e for e in es if e["group"] == "plate" and e["category"] == "master"), None),
        "hero": idx.hero(cid),
        "default_look_id": sched.character_defaults.get(cid),
        "plates": plates, "expressions": [e for e in es if e["group"] == "expression"],
        "items": items, "look_images": [e for e in es if e["group"] == "look"],
        "portraits": [e for e in es if e["group"] == "portrait"],
        "wardrobe": wardrobe, "looks": looks, "missing": missing, "missing_count": len(missing),
        "unregistered": sum(1 for lst in items.values() for e in lst if not e.get("registered_item_id")),
    }


@router.get("/api/assets/characters")
def list_characters(store: LookStore = Depends(get_store)):
    idx = AssetIndex(store)
    usage = item_usage(store)
    return {"slots": list(SLOTS), "item_categories": list(ITEM_CATS), "plate_views": list(PLATE_VIEWS),
            "variants": list(VARIANTS), "max_refs": QWEN_MAX_REFS,
            "decor_states": [d.id for d in store.wardrobe().decor_states],
            "characters": [character_assets(store, c, idx, usage) for c in character_ids()]}


@router.get("/api/assets/characters/{character}")
def get_character(character: str, store: LookStore = Depends(get_store)):
    cid = _char(character)
    return character_assets(store, cid, AssetIndex(store), item_usage(store))


@router.get("/api/assets/file")
def get_file(path: str):
    p = (ROOT / path).resolve()
    if not p.is_relative_to(ASSETS_DIR.resolve()) or not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p)


def _char(c: str) -> str:
    try:
        return resolve_character(c)
    except (KeyError, ValueError):
        if (chars_dir() / c).is_dir():
            return c
        raise HTTPException(404, f"unknown character: {c}")


# ---------------------------------------------------------------- manifest 导入

def _new_item_id(cid: str, cat: str, e: dict, taken: set[str]) -> str:
    key = re.sub(r"[^A-Za-z0-9]+", "-", str(e.get("design") or Path(e["file"]).stem)).strip("-").lower()
    return f"{ABBR.get(cid, cid)}-{cat}-{key}"


@router.post("/api/assets/characters/{character}/import")
def import_manifest(character: str, store: LookStore = Depends(get_store)):
    """把 manifest 里的单品（kind=item/*）登记进衣橱：
    - sha256 已在任何单品的 images 里 → 跳过（去重）
    - 名称里带 REF-xx 且已有单品引用该 REF id → 图片挂到那个单品上（补齐 REF 注册表缺的文件）
    - 否则新建单品 <缩写>-<类别>-<design>；id 已被占用 → 跳过，不覆盖"""
    cid = _char(character)
    entries = [e for e in scan_character(cid) if e["group"] == "item" and not e["missing_file"]]
    report = {"created": [], "attached": [], "skipped": []}

    def fn():
        w = store.wardrobe()
        by_id = {i.id: i for i in w.items}
        shas = {im.sha256 for i in w.items for im in i.images if im.sha256}
        for e in entries:
            sha = e.get("sha256") or sha256_file(ROOT / e["file"])
            if sha in shas:
                report["skipped"].append({"file": e["file"], "reason": "已登记（sha256 相同）"})
                continue
            cat = e["category"] if e["category"] in SLOTS else "accessory"
            variant = "front" if cat in ("makeup", "hair") else "clean"
            img = ItemImage(file=e["file"], variant=variant, version=1, sha256=sha, source="manifest",
                            created_at=e.get("created_at"))
            refm = REF_RE.search(str(e.get("name") or ""))
            target = next((i for i in w.items if refm and refm.group(0) in i.reference_images), None)
            if target:
                img.version = 1 + max((im.version for im in target.images), default=0)
                target.images.append(img)
                if e["file"] not in target.reference_images:
                    target.reference_images.insert(0, e["file"])
                report["attached"].append({"file": e["file"], "item_id": target.id, "ref": refm.group(0)})
            else:
                iid = _new_item_id(cid, cat, e, set(by_id))
                same = by_id.get(iid)
                if same and same.character == cid and same.slot == cat:
                    # 同一设计的另一张图（如 M5_s0 / M5_s1）→ 挂成该单品的新版本，旧版本保留
                    img.version = 1 + max((im.version for im in same.images), default=0)
                    same.images.append(img)
                    same.version = max(same.version, img.version)
                    if e["file"] not in same.reference_images:
                        same.reference_images.append(e["file"])
                    report["attached"].append({"file": e["file"], "item_id": iid, "ref": "同设计新版本"})
                    shas.add(sha)
                    continue
                if same:
                    report["skipped"].append({"file": e["file"], "reason": f"id {iid} 已被其他角色/类别占用，不覆盖"})
                    continue
                it = WardrobeItem(id=iid, slot=cat, name=str(e.get("name") or e.get("design") or iid),
                                  description=str(e.get("description") or ""), character=cid,
                                  reference_images=[e["file"]], images=[img],
                                  tags=[t for t in [e.get("design"), *(e.get("tags") or [])] if t],
                                  source="reference", needs_review=True,
                                  notes=["从 manifest 导入；description 为空时不进提示词，请补写"])
                w.items.append(it)
                by_id[iid] = it
                report["created"].append({"file": e["file"], "item_id": iid})
            shas.add(sha)
        store._write("wardrobe", w)

    affected = store._mutate(fn)
    return {**report, **affected.model_dump()}


# ---------------------------------------------------------------- 单品图片上传

def upload_dir(item: WardrobeItem) -> Path:
    return chars_dir() / (item.character or "_shared") / "items" / (item.slot if item.slot in ITEM_CATS else "accessory") \
        / "uploads"


def _append_manifest(d: Path, entry: dict):
    m = d / "manifest.json"
    data = json.loads(m.read_text(encoding="utf-8")) if m.exists() else []
    if isinstance(data, dict):
        data.setdefault("items", []).append(entry)
    else:
        data.append(entry)
    d.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


@router.post("/api/looks/wardrobe/items/{item_id}/images")
async def upload_item_image(item_id: str, file: UploadFile = File(...), variant: str = Form("clean"),
                            store: LookStore = Depends(get_store)):
    """上传后生成新版本（旧版本保留），同时登记进 reference_images；返回 AffectedShots + 新图片"""
    if variant not in VARIANTS:
        raise HTTPException(422, f"variant 只能是 {VARIANTS}")
    item = next((i for i in store.wardrobe().items if i.id == item_id), None)
    if not item:
        raise HTTPException(404, f"unknown item: {item_id}")
    suffix = Path(file.filename or "x.png").suffix.lower()
    if suffix not in IMAGE_EXT:
        raise HTTPException(422, f"只接受图片 {sorted(IMAGE_EXT)}")
    data = await file.read()
    sha = hashlib.sha256(data).hexdigest()
    version = 1 + max((im.version for im in item.images), default=0)
    d = upload_dir(item)
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{item_id}_{variant}_v{version}{suffix}"
    dest.write_bytes(data)
    now = time.strftime("%Y-%m-%dT%H:%M:%S")
    img = ItemImage(file=rel(dest), variant=variant, version=version, sha256=sha, source="upload", created_at=now)
    _append_manifest(d, {"file": dest.name, "kind": f"item/{item.slot}", "name": item.name, "item_id": item_id,
                         "variant": variant, "version": version, "sha256": sha, "source": "upload", "created_at": now})

    def fn():
        w = store.wardrobe()
        it = next(i for i in w.items if i.id == item_id)
        it.images.append(img)
        it.version = max(it.version, version)
        it.reference_images = [img.file] + [r for r in it.reference_images if r != img.file]
        store._write("wardrobe", w)

    affected = store._mutate(fn)
    return {**affected.model_dump(), "image": {**img.model_dump(), "url": file_url(img.file)}}


class TagsBody(BaseModel):
    tags: list[str]


@router.put("/api/looks/wardrobe/items/{item_id}/tags")
def put_item_tags(item_id: str, body: TagsBody, store: LookStore = Depends(get_store)):
    """只改标签（不影响画面，affected 恒为 0）"""
    w = store.wardrobe()
    it = next((i for i in w.items if i.id == item_id), None)
    if not it:
        raise HTTPException(404, f"unknown item: {item_id}")
    it.tags = [t.strip() for t in body.tags if t.strip()]
    store._write("wardrobe", w)
    return {"id": item_id, "tags": it.tags}


# ---------------------------------------------------------------- 按镜头的人物信息 / 参考图组

def character_brief(r, idx: AssetIndex, looks_by_id: dict) -> dict:
    """镜头卡人物行：脸图、造型字母、各插槽单品缩略图、D 状态、换装点、冲突"""
    lk = looks_by_id.get(r.look_id)
    slots = []
    for s in ("outfit", "shoes", "nails", "hair", "makeup", "accessory"):
        v = r.slots.get(s)
        slots.append({"slot": s, "items": [{"id": i, "name": n, "thumb_url": idx.item_thumb(i)}
                                           for i, n in zip(v.items, v.names)] if v else [],
                      "source": v.source if v else None, "changed": bool(v and v.changed_from_prev)})
    return {"character": r.character, "name": r.name, "face_url": idx.face_url(r.character),
            "look_id": r.look_id, "look_label": (lk.label if lk and lk.label else ""), "look_name": r.look_name,
            "label": r.label, "d_state": r.d_state.value, "has_override": r.has_override,
            "changed_from_prev": r.changed_from_prev, "changed_fields": r.changed_fields,
            "slots": slots, "conflicts": [c.model_dump() for c in r.conflicts if c.severity != "info"]}


@router.get("/api/looks/shots")
def shots_looks(episode: int, store: LookStore = Depends(get_store)):
    try:
        ep = store.episode(episode)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]))
    res, idx = store.resolver(), AssetIndex(store)
    looks_by_id = {lk.id: lk for lk in store.lookbook().looks}
    out = []
    for s in ep.shots:
        sl = res.shot_looks(s)
        out.append({"shot_id": s.id, "look_hash": sl.look_hash,
                    "characters": [character_brief(r, idx, looks_by_id) for r in sl.characters]})
    return out


@router.get("/api/looks/shots/{shot_id}/refs")
def get_shot_refs(shot_id: str, store: LookStore = Depends(get_store)):
    try:
        return shot_refs(store, shot_id)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]) if e.args else "not found")


# ---------------------------------------------------------------- 生成（E6：Qwen Image 2.1 多参考）

GEN_TARGETS = {"plate": "plates", "expression": "expressions", "item": "items", "look": "looks"}
GEN_MODELS = ("qwen", "klein")


class GenerateRequest(BaseModel):
    target: str                      # plate/front | expression/害羞 | item/nails | look/<look_id>
    prompt: str
    references: list[str] = []       # 相对项目根的图片路径；为空时自动用该角色的脸图
    model: str = "qwen"              # qwen = Qwen Image 2.1 Turbo（本机）；klein 尚未接入
    seed: int | None = None
    name: str | None = None
    negative: str = ""


def validate_generate(cid: str, req: GenerateRequest, store: LookStore) -> GenerateRequest:
    group, _, cat = req.target.partition("/")
    if group not in GEN_TARGETS or not cat:
        raise HTTPException(422, "target 形如 plate/front、expression/<名>、item/<类别>、look/<造型 id>")
    if group == "plate" and cat not in (*PLATE_VIEWS, "master"):
        raise HTTPException(422, f"plate 视角只能是 {(*PLATE_VIEWS, 'master')}")
    if group == "item" and _norm_cat(cat) not in ITEM_CATS:
        raise HTTPException(422, f"单品类别只能是 {ITEM_CATS}")
    if req.model not in GEN_MODELS:
        raise HTTPException(422, f"model 只能是 {GEN_MODELS}")
    if req.model == "klein":
        raise HTTPException(501, "Klein 工作流尚未接入（ComfyUI 有 Flux2 节点，但 render_router 还没有 Klein 工作流）；"
                                 "先用 qwen")
    if not req.prompt.strip():
        raise HTTPException(422, "prompt 不能为空")
    refs = list(req.references)
    if not refs:
        f = AssetIndex(store).face(cid)
        refs = [f["file"]] if f else []
    for r in refs:
        p = (ROOT / r).resolve()
        if not p.is_file() or not p.is_relative_to(ROOT.resolve()):
            raise HTTPException(422, f"参考图不存在：{r}")
    req.references = refs[:QWEN_MAX_REFS]
    return req


def target_dir(cid: str, target: str) -> Path:
    group, _, cat = target.partition("/")
    d = chars_dir() / cid / GEN_TARGETS[group]
    if group == "item":
        d = d / _norm_cat(cat)
    if group == "look":
        d = d / re.sub(r"[^\w-]+", "_", cat)
    return d


def multi_ref_workflow(W, prompt: str, negative: str, refs: list[str], width: int, height: int, seed: int,
                       prefix: str) -> dict:
    """Qwen Image 2.1 多参考编辑：在 render_router 的单参考图上追加 images.image_2..N（节点为 AUTOGROW，最多 16）。
    第 1 张（脸）按画布比例居中裁切，其余（单品特写）保持原比例。"""
    if not refs:
        return W.qwen_t2i(prompt, negative, width, height, seed, prefix)
    wf = W.qwen_edit(prompt, negative, refs[0], width, height, seed, prefix)
    for k, ref in enumerate(refs[1:], start=2):
        nid = str(200 + k)
        wf[nid] = {"class_type": "LoadImage", "inputs": {"image": ref}}
        wf["20"]["inputs"][f"images.image_{k}"] = [nid, 0]
    return wf


def generate_asset(client, cid: str, req: dict, *, size=(1088, 1920)) -> dict:
    """在渲染线程里执行：上传参考图 → Qwen 2.1 编辑 → 存到资产目录并追加 manifest。返回 manifest 条目。"""
    from ns_render import workflows as W
    from ns_render.pipeline import seed_for
    group, _, cat = req["target"].partition("/")
    d = target_dir(cid, req["target"])
    seed = req.get("seed") if req.get("seed") is not None else seed_for(f"asset/{cid}/{req['target']}", int(time.time()))
    names = [client.upload_image(ROOT / r, subfolder="ns_final/assets") for r in req["references"]]
    prompt = "".join(f"图{i + 1}是参考图{i + 1}。" for i in range(len(names))) + req["prompt"] if names else req["prompt"]
    wf = multi_ref_workflow(W, prompt, req.get("negative") or "", names, *size, seed, f"ns_final/assets/{cid}")
    entry, secs = client.run(wf, timeout_s=900)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
    stem = re.sub(r"[^\w-]+", "_", req.get("name") or cat)
    dest = d / f"{stem}_s{seed}.png"
    client.download(item, dest)
    rec = {"file": dest.name, "kind": f"{group}/{_norm_cat(cat) if group == 'item' else cat}",
           "name": req.get("name") or cat, "prompt": prompt, "seed": seed,
           "model": "qwen_image_2.1_turbo_int8_convrot.safetensors",
           "workflow": "qwen_edit_multi" if names else "qwen_t2i", "references": req["references"],
           "sha256": sha256_file(dest), "created_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "seconds": round(secs, 1), "source": "generated"}
    _append_manifest(d, rec)
    return rec
