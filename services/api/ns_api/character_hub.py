"""
人物资产页（ASSETUX 2026-10-31）：以人物为中心，一个人一页看全。

项目方原话：
  “这个资产管理没有之前做的好，乱七八糟的……我不接受这个 UI、UX 包括里面的功能。”
  “我要把一些图片放进去，比如……我要添加这个鞋子进去作为资产，我怎么做呀？”
  “很多事情只有一个确认按钮就可以，甚至不用确认按钮就行了，就是我选这个图按一下就可以了……系统是在我 login 的，
   意味着我所做的所有行为都是我个人行为，所以你不需要每个东西都要打上一个字。”

所以：这里的写接口都是“点一下就生效”，不要原话；谁做的从登录会话取（ns_api.auth.user_of），写进
data/looks/character_hub_log.jsonl（另外 auth 中间件对每个写请求记审计）。每个写接口返回 prev，前端 10 秒“撤销”= 用 prev 再调一次。

数据都落在出图解析器（REFLOCK，services/agent/ns_agent/asset_refs.py）读的地方，点完下一次出图就用上，不用重启：
  身份脸        data/looks/face_overrides.json        {project:{cid: 路径, _by_<cid>, _at_<cid>}}   → asset_refs.face_of
  造型设定图    <run>/assets/sheets_chosen.json       sheet:<cid>_look<X>.file                      → asset_refs.sheet_of
  单品挂到造型  data/looks/item_map_overrides.json    {project:{cid:{look:{部件名: item_id|null}}}} → asset_refs.item_map
  衣橱单品      data/looks/wardrobe.json（新图插到 images[0]，解析器取第一张）+ 图片 assets/characters/<cid>/wardrobe/
删除走回收站（EDITDEL：DELETE /api/trash/object?type=asset），撤销 = POST /api/trash/{entry_id}/restore。

接口：
  GET  /api/character-hub                               当前剧的人物列表（每人：身份脸、造型数、缺图 / 仅设定图计数、单品数）
  GET  /api/character-hub/{cid}?all_items=0|1           一个人的全部：身份脸（当前 + 候选）、3 套造型（设定图当前 + 候选、
                                                        部件清单 + 缺图状态）、衣橱单品（属于哪些造型）、声音、最近操作
  POST /api/character-hub/{cid}/face        {file}                     设为当前身份脸
  POST /api/character-hub/{cid}/sheet       {look, file}               选定这套造型的设定图
  POST /api/character-hub/{cid}/map         {look, part, item_id|null} 某套造型的某个部件用哪件单品（null = 不用单品，回到设定图）
  POST /api/character-hub/{cid}/wardrobe    multipart file, cat, name, looks(JSON [{look, part}]), note  上传一件单品
  POST /api/character-hub/{cid}/items/{item_id}/images multipart file    给单品再加一张图（另一角度；主参考图不变）
  POST /api/character-hub/{cid}/check-image multipart file, cat?, name?  选图后先查（不写）：已在库里 → 那件单品；否则看图起人话名字
  POST /api/character-hub/{cid}/items/{item_id}/adopt {looks, remove?}   “用这件”：旧单品放进当前剧衣橱 + 挂到造型
  POST /api/character-hub/{cid}/looks       {use, outfit, shoes, accessory}  ＋ 新造型（存 data/looks/hub_extra_looks.json）
  POST /api/character-hub/{cid}/looks/{X}/remove                         撤销新造型（只认人物页新建的）
  POST /api/character-hub/{cid}/looks/{X}/sheet  multipart file          给造型上传设定图（设为当前）
  POST /api/character-hub/{cid}/schedule    {ep, look|null}            排期：某集整集用哪套造型（存 data/looks/hub_episode_looks.json）
  POST /api/character-hub/{cid}/items/{item_id}/rename {name}          改单品名
  POST /api/character-hub/{cid}/items/{item_id}/trash                  删除单品（进回收站；同时解除它在造型里的映射）
  POST /api/character-hub/{cid}/items/{item_id}/restore {entry_id, maps} 撤销删除
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from pydantic import BaseModel

_AGENT = Path(__file__).resolve().parents[2] / "agent"
if str(_AGENT) not in sys.path:
    sys.path.insert(0, str(_AGENT))

from ns_agent import asset_refs as R  # noqa: E402  出图参考解析器（REFLOCK）
from ns_agent.looks import LookStore  # noqa: E402
from ns_api import assets as A  # noqa: E402
from ns_api.looks import get_store  # noqa: E402
from ns_schema.looks import ItemImage, WardrobeItem  # noqa: E402

router = APIRouter(tags=["character-hub"])
_lock = threading.RLock()

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}
# 界面上的类别 → 衣橱槽位（包没有单独槽位：记成饰品 + 标签“包”）
CATS = {"outfit": ("outfit", "衣服"), "shoes": ("shoes", "鞋"), "accessory": ("accessory", "饰品"),
        "body": ("accessory", "身体饰品·穿环"), "nails": ("nails", "指甲"), "bag": ("accessory", "包"),
        "hair": ("hair", "发型"), "makeup": ("makeup", "妆容")}
TAG_CATS = {v[1]: k for k, v in CATS.items() if k in ("bag", "body")}   # 没有独立槽位、靠标签区分的类别
SLOT_NAME = {"outfit": "衣服", "shoes": "鞋", "accessory": "饰品", "nails": "指甲", "hair": "发型", "makeup": "妆容",
             "other": "其他", "marker": "标志"}
ABBR = {"lin_wan": "lw", "gu_chen": "gc", "chen_yu": "cy", "ch_a_lan": "al"}


def _root() -> Path:
    return R.ROOT


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
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, p)


def _log_path() -> Path:
    return _root() / "data" / "looks" / "character_hub_log.jsonl"


def _actor(request: Request | None) -> str:
    """登录账户名（UIRSI auth）；没登录 = “未登录”（照样记下是谁也不知道，不拦）"""
    if request is None:
        return "test"
    try:
        from ns_api import auth as AU
        u = AU.user_of(request)
        if u:
            return u.get("name") or "owner"
    except Exception:  # noqa: BLE001  auth 模块不在 / 出错时不影响点选
        pass
    return request.headers.get("x-ns-user") or "未登录"


def _log(by: str, cid: str, action: str, **detail) -> dict:
    rec = {"at": _now(), "by": by, "cid": cid, "action": action, **detail}
    p = _log_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock, p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return rec


def _recent(cid: str, n: int = 12) -> list[dict]:
    p = _log_path()
    try:
        lines = p.read_text(encoding="utf-8").splitlines()[-400:]
    except OSError:
        return []
    out = []
    for ln in reversed(lines):
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("cid") == cid:
            out.append(r)
            if len(out) >= n:
                break
    return out


# ---------------------------------------------------------------- 项目 / 路径 / URL
def projects() -> list[str]:
    return [k for k in (R._cfg().get("projects") or {}) if not k.startswith("_")]


def current_project(project: str | None = None) -> str:
    ps = projects()
    if project:
        if project not in ps:
            raise HTTPException(404, f"没有这个项目：{project}")
        return project
    if not ps:
        raise HTTPException(404, "出图参考配置里还没有项目（config/recipes/asset_refs.json）")

    def mt(p: str) -> float:
        d = _root() / (R.project_cfg(p).get("run_dir") or "")
        try:
            return d.stat().st_mtime
        except OSError:
            return 0.0
    return max(ps, key=mt)


def _run_dir(project: str) -> Path:
    return _root() / (R.project_cfg(project).get("run_dir") or f"data/pipeline/runs/{project}")


def _sheets_file(project: str) -> Path:
    return _root() / (R.project_cfg(project).get("sheets_file") or f"{_run_dir(project).relative_to(_root()).as_posix()}/assets/sheets_chosen.json")


def url(rel: str | None) -> str | None:
    if not rel:
        return None
    p = _root() / rel
    if not p.is_file():
        return None
    v = int(p.stat().st_mtime)
    if rel.startswith("data/"):
        return f"/files/{rel[5:]}?v={v}"
    if rel.startswith("assets/"):
        return f"/api/assets/file?path={rel}&v={v}"
    return None


def _img(rel: str | None, **extra) -> dict | None:
    u = url(rel)
    return {"file": rel, "url": u, **extra} if u else None


def _rel(p: Path) -> str:
    return p.resolve().relative_to(_root().resolve()).as_posix()


# ---------------------------------------------------------------- 读：人物
def _p1(project: str) -> list[dict]:
    p = _root() / (R.project_cfg(project).get("looks_file") or "")
    d = _rjson(p, [])
    return [c for c in d if isinstance(c, dict)]


def _cast(project: str) -> list[dict]:
    return [{"cid": c.get("char_id") or R.NAME_ID.get(c.get("name"), c.get("name")), "name": c.get("name"),
             "marker": c.get("marker") or "", "looks": c.get("looks") or []} for c in _p1(project)]


def _face_candidates(project: str, cid: str) -> list[dict]:
    """身份脸候选：当前 + config faces 列表 + 资产参考里 role=identity 的 + identity_refs/<cid>/*face* + 设定图目录里的 *face*"""
    root = _root()
    seen: list[str] = []

    def add(f: str | None):
        if f and f not in seen and (root / f).is_file():
            seen.append(f)
    add(R.face_of(project, cid))
    for f in (R.project_cfg(project).get("faces") or {}).get(cid) or []:
        add(f)
    refs = _rjson(root / "data" / "assets" / "asset_refs.json", {})
    for r in refs.get(cid) or []:
        if isinstance(r, dict) and r.get("role") == "identity" and not r.get("void"):
            add(r.get("file"))
    for f in _regen_files(cid, "face"):
        add(f)
    for d in (root / "data" / "assets" / "identity_refs" / cid, _run_dir(project) / "images" / "sheets" / cid):
        if d.is_dir():
            for f in sorted(d.glob("*face*")):
                if f.suffix.lower() in IMAGE_EXT:
                    add(_rel(f))
    notes = {r.get("file"): _human_note(r) for r in refs.get(cid) or [] if isinstance(r, dict)}
    ref_ids = {r.get("file"): r.get("ref_id") for r in refs.get(cid) or [] if isinstance(r, dict) and r.get("ref_id")}
    cur = R.face_of(project, cid)
    # ref_id：登记在资产参考图里的才能删（进回收站：DELETE /api/trash/object?type=asset_ref&id=<cid>/<ref_id>）
    out = []
    for f in seen:
        im = _img(f)
        if not im:
            continue
        ok, why = _crop_cached(root / f)     # L-086：前端按后端结果显示能不能“设为身份脸”（UIRSI r37）
        out.append({**im, "current": f == cur, "note": notes.get(f) or "", "ref_id": ref_ids.get(f), "crop_ok": ok, "crop_why": why})
    return out


_CROP_CACHE: dict = {}


def _crop_cached(path: Path) -> tuple[bool, str]:
    """face_crop_check 按（路径, 修改时间, 大小）缓存：人物页每次打开不重复跑 YuNet"""
    try:
        st = path.stat()
        key = (str(path), st.st_mtime_ns, st.st_size)
    except OSError:
        return False, "文件不存在"
    if key not in _CROP_CACHE:
        _CROP_CACHE[key] = face_crop_check(path)
    return _CROP_CACHE[key]


def _human_note(r: dict) -> str:
    """参考图说明转人话：内部字段（by=owner、refs.face_plate、ar-xxxx）不当主信息"""
    t = str(r.get("note") or r.get("label") or "")
    if "项目方通过" in t:
        return "项目方通过的母版（脸部裁切）"
    if r.get("by") == "owner" or "by=owner" in t:
        return "项目方选定的身份参考"
    t = re.sub(r"[，,]?\s*[A-Za-z_./=-]*[A-Za-z_]+[A-Za-z_./=-]*\s*同款", "", t)
    return "" if t.isascii() else t.strip("，, ")


def _regen_files(asset_id: str, tag: str) -> list[str]:
    """“↻ 再生成”出的图（asset_edit 生成记录，label = REGEN_TAG + tag），新的在前；作废的不算"""
    try:
        from ns_api import asset_edit as AE
        gens = AE._read("asset_gens").get(asset_id, []) or []
    except Exception:  # noqa: BLE001
        return []
    out = []
    for g in reversed(gens):
        if isinstance(g, dict) and not g.get("void") and str(g.get("label") or "") == f"{REGEN_TAG}{tag}" \
                and g.get("file") and (_root() / g["file"]).is_file():
            out.append(g["file"])
    return out


def _sheet_candidates(project: str, cid: str, look: str) -> list[dict]:
    d = _run_dir(project) / "images" / "sheets" / cid
    out = [{**_img(f), "seed": None, "thumb": None, "regen": True} for f in _regen_files(cid, f"sheet:{look}") if _img(f)]
    up = _root() / "assets" / "characters" / cid / "looks"
    for f in sorted(up.glob(f"{cid}_look{look}_*")) if up.is_dir() else []:
        if f.suffix.lower() in IMAGE_EXT:
            out.append({**_img(_rel(f)), "seed": None, "thumb": None, "uploaded": True})
    if d.is_dir():
        for f in sorted(d.glob(f"{cid}_look{look}_s*")):
            if f.suffix.lower() not in IMAGE_EXT:
                continue
            m = re.search(r"_s(\d+)$", f.stem)
            th = _run_dir(project) / "images" / "_thumbs" / f"{f.stem}.jpg"
            out.append({**_img(_rel(f)), "seed": int(m.group(1)) if m else None,
                        "thumb": url(_rel(th)) if th.is_file() else None})
    return out


def _item_file(it: WardrobeItem) -> str | None:
    """和解析器同一个取图顺序（images[] 第一张存在的 → reference_images 第一张），但直接读这个对象（不走解析器的衣橱缓存）"""
    for im in it.images:
        if (_root() / im.file).is_file():
            return im.file
    return next((r for r in it.reference_images if (_root() / r).is_file()), None)


def _item_dict(it: WardrobeItem, looks_of: dict[str, list[dict]]) -> dict:
    f = _item_file(it)
    tag_cat = next((t for t in it.tags if t in TAG_CATS), None)
    clean = re.sub(r"（[^）]*）$", "", it.name)
    return {"id": it.id, "slot": it.slot, "slot_name": tag_cat or SLOT_NAME.get(it.slot, it.slot),
            "zone": R.zone_of(it.slot, clean) if tag_cat != "身体饰品·穿环" else "body",
            "cat": TAG_CATS.get(tag_cat) if tag_cat else next((k for k, v in CATS.items() if v[0] == it.slot and k not in TAG_CATS), "accessory"),
            "note": next((n[3:] for n in it.notes if n.startswith("备注：")), ""),
            "name": re.sub(r"（产品）$", "", it.name), "image": _img(f), "images": len(it.images) or len(it.reference_images),
            "gallery": [g for g in (_img(im.file, version=im.version) for im in it.images) if g],
            "regen": [g for g in (_img(f) for f in _regen_files(it.id, "item")) if g],
            "tags": it.tags, "source": it.source, "created_at": next((im.created_at for im in it.images if im.created_at), None),
            "uploaded_by": next((n[3:] for n in it.notes if n.startswith("上传：")), None),
            "looks": looks_of.get(it.id, []), "version": it.version}


def _overrides() -> dict:
    return _rjson(R.OVERRIDES, {})


def _extra_maps(project: str, cid: str) -> dict[str, dict[str, str]]:
    """挂到造型、但造型文字里没有对应部件的单品（例如造型里没写包）：只记录，出图暂不用"""
    out: dict[str, dict[str, str]] = {}
    labels = {lk["look"]: {p["label"] for p in lk["parts"]} for lk in _inventory(project, cid)}
    for lid, m in ((_overrides().get(project) or {}).get(cid) or {}).items():
        if lid.startswith("_") or not isinstance(m, dict):
            continue
        for k, v in m.items():
            if not k.startswith("_") and v and k not in labels.get(lid, set()):
                out.setdefault(lid, {})[k] = v
    return out


def _quar(quar: dict, look: str, label: str) -> dict | None:
    """REFLOCK 隔离区（data/looks/item_map_quarantine.json）：这条映射暂不生效，待项目方确认"""
    q = (quar.get(look) or {}).get(label)
    if not isinstance(q, dict) or not q.get("item"):
        return None
    return {"item_id": q["item"], "item_name": R.item_name(q["item"]), "why": q.get("why") or ""}


def _extra_looks_path() -> Path:
    return _root() / "data" / "looks" / "hub_extra_looks.json"


def _episode_looks_path() -> Path:
    return _root() / "data" / "looks" / "hub_episode_looks.json"


def _extra_looks(project: str, cid: str) -> list[dict]:
    return [x for x in ((_rjson(_extra_looks_path(), {}).get(project) or {}).get(cid) or [])
            if isinstance(x, dict) and re.fullmatch(r"[A-Z]", str(x.get("id") or ""))]


def _inventory(project: str, cid: str) -> list[dict]:
    """解析器的造型清单 + 人物页新建的造型（解析器还没合进来时，这里补上，标 pending_resolver）"""
    inv = R.look_inventory(project, cid)
    have = {lk["look"] for lk in inv}
    for x in _extra_looks(project, cid):
        if x["id"] in have:
            continue
        sheet = R.sheet_of(project, cid, x["id"])
        parts = []
        for pp in R.parse_parts(x.get("zh") or ""):
            parts.append({"slot": pp.slot, "label": R._short(pp.label), "raw": pp.label, "zone": pp.zone, "item_id": None,
                          "item_file": None, "status": "identity" if pp.slot == "marker" else ("sheet_only" if sheet else "missing")})
        inv.append({"character": cid, "name": R.ID_NAME.get(cid, cid), "look": x["id"], "use": x.get("use") or "",
                    "zh": x.get("zh") or "", "sheet": sheet, "face": R.face_of(project, cid), "parts": parts,
                    "pending_resolver": True})
    return sorted(inv, key=lambda lk: lk["look"])


def _unregistered(cid: str, items: list) -> list[str]:
    """单品目录里有、但没登记到任何单品的图片（旧资产库的“文件未登记”警示，回退清单 F32）"""
    known = {im.file for i in items for im in i.images} | {r for i in items for r in i.reference_images}
    out = []
    for sub in ("items", "wardrobe"):
        d = _root() / "assets" / "characters" / cid / sub
        if not d.is_dir():
            continue
        for f in d.rglob("*"):
            if f.is_file() and f.suffix.lower() in IMAGE_EXT and "_thumbs" not in f.parts:
                r = _rel(f)
                if r not in known:
                    out.append(r)
    return sorted(out)[:200]


def _schedule(project: str, cid: str, looks: list[str]) -> list[dict]:
    """排期：每集这个人物用哪套造型。登记 = shot_looks.json（逐镜，系统按剧本登记）；覆盖 = 人物页改的整集造型"""
    reg = R.registry_looks(project)
    by_ep: dict[int, dict[str, int]] = {}
    for sid, m in reg.items():
        mm = re.match(r"ep(\d+)-S", sid)
        if not mm or not isinstance(m, dict) or cid not in m:
            continue
        lk = m.get(cid) or "?"
        e = by_ep.setdefault(int(mm.group(1)), {})
        e[lk] = e.get(lk, 0) + 1
    ov = (_rjson(_episode_looks_path(), {}).get(project) or {}).get(cid) or {}
    eps = sorted(set(by_ep) | {int(k) for k in ov if str(k).isdigit()})
    return [{"ep": e, "registered": by_ep.get(e, {}), "override": ov.get(str(e)) if ov.get(str(e)) in looks else None} for e in eps]


def character(project: str, cid: str, store: LookStore, all_items: bool = False) -> dict:
    cast = {c["cid"]: c for c in _cast(project)}
    if cid not in cast:
        raise HTTPException(404, f"当前剧（{project}）里没有这个人物：{cid}")
    c = cast[cid]
    inv = _inventory(project, cid)
    extra = _extra_maps(project, cid)
    looks_of: dict[str, list[dict]] = {}
    looks = []
    wd = {i.id for i in store.wardrobe().items}
    quar = ((_rjson(_root() / "data" / "looks" / "item_map_quarantine.json", {}).get(project) or {}).get(cid) or {})
    for lk in inv:
        parts = []
        for p in lk["parts"]:
            if p["slot"] == "marker":
                continue
            parts.append({**p, "slot_name": SLOT_NAME.get(p["slot"], p["slot"]),
                          "item_name": R.item_name(p["item_id"]) if p["item_id"] and p["item_id"] in wd else None,
                          "item_image": _img(p["item_file"]), "extra": False,
                          "quarantine": _quar(quar, lk["look"], p["label"])})
            if p["item_id"]:
                looks_of.setdefault(p["item_id"], []).append({"look": lk["look"], "part": p["label"]})
        for label, iid in (extra.get(lk["look"]) or {}).items():
            f = R.item_image(iid)
            parts.append({"slot": "other", "slot_name": "额外", "label": label, "raw": label, "zone": None, "item_id": iid,
                          "item_file": f, "status": "extra", "item_name": R.item_name(iid), "item_image": _img(f),
                          "extra": True})
            looks_of.setdefault(iid, []).append({"look": lk["look"], "part": label, "extra": True})
        cnt = {s: sum(1 for p in parts if p["status"] == s) for s in ("wardrobe", "sheet_only", "missing")}
        looks.append({"look": lk["look"], "use": lk["use"], "zh": lk["zh"], "sheet": _img(lk["sheet"]),
                      "custom": any(x["id"] == lk["look"] for x in _extra_looks(project, cid)),
                      "pending_resolver": bool(lk.get("pending_resolver")),
                      "candidates": [{**x, "current": x["file"] == lk["sheet"]} for x in _sheet_candidates(project, cid, lk["look"])],
                      "parts": parts, "counts": cnt})
    items_all = [i for i in store.wardrobe().items if i.character == cid]
    adopted = set(_adopted(project, cid))
    in_play = [i for i in items_all if i.id in looks_of or i.source == "hub_upload" or i.id in adopted]
    shown = items_all if all_items else in_play
    items = sorted((_item_dict(i, looks_of) for i in shown), key=lambda x: (x["source"] != "hub_upload", x["slot"], x["name"]))
    voices = _rjson(_root() / "config" / "voices.json", {})
    vc = (voices.get("characters") or {}).get(cid) if isinstance(voices.get("characters"), dict) else None
    faces = _face_candidates(project, cid)
    return {"project": project, "cid": cid, "name": c["name"], "marker": c["marker"],
            "face": next((f for f in faces if f["current"]), None), "faces": faces,
            "looks": looks, "items": items, "items_total": len(items_all), "items_hidden": len(items_all) - len(in_play),
            "unregistered": _unregistered(cid, items_all),
            "rejected": {k: v for k, v in rejected_map().items() if f"/{cid}" in k or f"{cid}_" in k},
            "voice": vc, "recent": _recent(cid), "schedule": _schedule(project, cid, [lk["look"] for lk in looks]),
            "missing": sum(lk["counts"]["missing"] for lk in looks) + (0 if any(f["current"] for f in faces) else 1),
            "sheet_only": sum(lk["counts"]["sheet_only"] for lk in looks)}


@router.get("/api/character-hub")
def list_characters(project: str | None = None, store: LookStore = Depends(get_store)):
    pj = current_project(project)
    out = []
    for c in _cast(pj):
        try:
            d = character(pj, c["cid"], store)
        except HTTPException:
            continue
        out.append({"cid": c["cid"], "name": c["name"], "face": d["face"], "looks": len(d["looks"]),
                    "sheets": sum(1 for lk in d["looks"] if lk["sheet"]), "items": len(d["items"]),
                    "missing": d["missing"], "sheet_only": d["sheet_only"]})
    return {"project": pj, "projects": projects(), "characters": out,
            "categories": [{"id": k, "slot": v[0], "name": v[1]} for k, v in CATS.items()]}


@router.get("/api/character-hub/{cid}")
def get_character(cid: str, project: str | None = None, all_items: bool = False, store: LookStore = Depends(get_store)):
    return character(current_project(project), cid, store, all_items)


# ---------------------------------------------------------------- 身份脸只接受脸部裁切（项目方 11-01 17:2x，L-086；RSI 经总调度授权加）
FACE_CROP_ASPECT = (0.6, 1.6)     # 宽 / 高：脸部裁切大致方形；整张 4 栏设定图约 1.77
FACE_CROP_MIN_FRAC = 0.12         # 最大人脸框面积 / 整图面积；旧裁切 lin_wan_face_ref2va 约 0.33，整张设定图约 0.04
YUNET = Path(__file__).resolve().parents[3] / "models_cache" / "vision" / "face_detection_yunet_2023mar.onnx"   # 模型在仓库里，不随项目根变


def face_crop_check(path: Path) -> tuple[bool, str]:
    """→ (是否像脸部裁切, 原因)。宽高比 + YuNet 最大人脸占比；检测器不可用 = 不放行（没测到不算通过）"""
    try:
        import cv2
        im = cv2.imread(str(path))
        if im is None:
            return False, "图片读不出来"
        h, w = im.shape[:2]
        if not FACE_CROP_ASPECT[0] <= w / h <= FACE_CROP_ASPECT[1]:
            return False, f"宽高比 {w / h:.2f} 不像脸部裁切（应在 {FACE_CROP_ASPECT[0]}–{FACE_CROP_ASPECT[1]}；整张设定图请先裁出大头）"
        det = cv2.FaceDetectorYN.create(str(YUNET), "", (w, h), 0.6)
        _, faces = det.detect(im)
        if faces is None or not len(faces):
            return False, "没检出人脸"
        fx, fy, fw, fh = max(faces, key=lambda r: r[2] * r[3])[:4]
        frac = float(fw * fh) / (w * h)
        if frac < FACE_CROP_MIN_FRAC:
            return False, f"人脸只占画面 {frac:.0%}（应 ≥{FACE_CROP_MIN_FRAC:.0%}），不像脸部裁切"
        return True, f"宽高比 {w / h:.2f}、人脸占 {frac:.0%}"
    except Exception as e:  # noqa: BLE001
        return False, f"检测器不可用，未测：{type(e).__name__}"


# ---------------------------------------------------------------- 写：点一下就生效（返回 prev 供撤销）
class FaceBody(BaseModel):
    file: str
    project: str | None = None


@router.post("/api/character-hub/{cid}/face")
def set_face(cid: str, body: FaceBody, request: Request):
    pj = current_project(body.project)
    if not any(f["file"] == body.file for f in _face_candidates(pj, cid)):
        raise HTTPException(422, "这张图不在这个人物的身份脸候选里")
    ok, why = face_crop_check(_root() / body.file)
    if not ok:
        raise HTTPException(422, f"身份脸只接受脸部裁切：{why}")
    by = _actor(request)
    with _lock:
        prev = R.face_of(pj, cid)
        d = _rjson(R.FACE_OVERRIDES, {})
        sec = d.setdefault(pj, {})
        sec[cid] = body.file
        sec[f"_by_{cid}"], sec[f"_at_{cid}"] = by, _now()
        _wjson(R.FACE_OVERRIDES, d)
    _log(by, cid, "face", file=body.file, prev=prev)
    return {"ok": True, "file": body.file, "prev": prev, "by": by}


class SheetBody(BaseModel):
    look: str
    file: str
    project: str | None = None


@router.post("/api/character-hub/{cid}/sheet")
def set_sheet(cid: str, body: SheetBody, request: Request):
    pj = current_project(body.project)
    if not re.fullmatch(r"[A-Z]", body.look):
        raise HTTPException(422, "造型写 A / B / C")
    cands = {x["file"]: x for x in _sheet_candidates(pj, cid, body.look)}
    if body.file not in cands:
        raise HTTPException(422, "这张图不在这套造型的设定图候选里")
    by = _actor(request)
    f = _sheets_file(pj)
    key = f"sheet:{cid}_look{body.look}"
    with _lock:
        d = _rjson(f, {})
        e = dict(d.get(key) or {})
        prev = e.get("file")
        if prev != body.file:
            if "sim" in e:
                e["sim_prev"] = e.pop("sim")   # 相似度是按旧图算的；换图后不再沿用
            e.update(file=body.file, char=cid, look=f"{cid}_look{body.look}", seed=cands[body.file].get("seed"),
                     picked_by=by, picked_at=_now())
            if not e.get("use") or not e.get("outfit"):
                lk = next((x for c in _cast(pj) if c["cid"] == cid for x in c["looks"] if x.get("id") == body.look), {})
                e.setdefault("use", lk.get("use"))
                e.setdefault("outfit", lk.get("zh"))
            d[key] = e
            _wjson(f, d)
    _log(by, cid, "sheet", look=body.look, file=body.file, prev=prev)
    return {"ok": True, "look": body.look, "file": body.file, "prev": prev, "by": by}


class MapBody(BaseModel):
    look: str
    part: str
    item_id: str | None = None
    project: str | None = None
    via: str | None = None    # 界面入口（card = 衣橱卡 A/B/C，picker = 部件换单品，undo = 撤销）：只记日志，便于对照审计


def _set_map(pj: str, cid: str, look: str, part: str, item_id: str | None, by: str) -> str | None:
    """返回改之前这个部件实际用的单品 id（含 config 系统提议）"""
    prev = ((R.item_map(pj).get(cid) or {}).get(look) or {}).get(part)
    with _lock:
        d = _rjson(R.OVERRIDES, {})
        m = d.setdefault(pj, {}).setdefault(cid, {}).setdefault(look, {})
        base = (((R.project_cfg(pj).get("item_map") or {}).get(cid) or {}).get(look) or {}).get(part)
        if item_id is None and base is None:
            m.pop(part, None)          # 系统提议里本来就没有：直接去掉这条
        else:
            m[part] = item_id
        m["_by"], m["_at"] = by, _now()
        _wjson(R.OVERRIDES, d)
    return prev


@router.post("/api/character-hub/{cid}/map")
def set_map(cid: str, body: MapBody, request: Request, store: LookStore = Depends(get_store)):
    pj = current_project(body.project)
    if body.look not in {lk["look"] for lk in _inventory(pj, cid)}:
        raise HTTPException(422, f"没有造型 {body.look}")
    part = body.part.strip()
    if not part or part.startswith("_"):
        raise HTTPException(422, "部件名不能为空")
    if body.item_id and not any(i.id == body.item_id for i in store.wardrobe().items):
        raise HTTPException(404, f"没有这件单品：{body.item_id}")
    by = _actor(request)
    prev = _set_map(pj, cid, body.look, part, body.item_id, by)
    _log(by, cid, "map", look=body.look, part=part, item_id=body.item_id, prev=prev, via=body.via,
         name=next((i.name for i in store.wardrobe().items if i.id == body.item_id), None) if body.item_id else None)
    return {"ok": True, "look": body.look, "part": part, "item_id": body.item_id, "prev": prev, "by": by}


def _new_item_id(cid: str, slot: str, existing: set[str]) -> str:
    base = f"{ABBR.get(cid, cid[:2])}-{slot}-up"
    while True:
        i = f"{base}-{uuid.uuid4().hex[:6]}"
        if i not in existing:
            return i


@router.post("/api/character-hub/{cid}/wardrobe", status_code=201)
async def upload_item(cid: str, request: Request, file: UploadFile = File(...), cat: str = Form(...),
                      name: str = Form(...), looks: str = Form("[]"), project: str | None = Form(None),
                      note: str = Form(""), force: bool = Form(False),
                      store: LookStore = Depends(get_store)):
    pj = current_project(project)
    if cid not in {c["cid"] for c in _cast(pj)}:
        raise HTTPException(404, f"当前剧里没有这个人物：{cid}")
    if cat not in CATS:
        raise HTTPException(422, f"类别只能是 {list(CATS)}")
    name = name.strip()
    if not name:
        raise HTTPException(422, "要写名称")
    try:
        targets = [t for t in json.loads(looks or "[]") if isinstance(t, dict) and t.get("look") and t.get("part")]
    except ValueError as e:
        raise HTTPException(422, "looks 要是 JSON 列表") from e
    suffix = Path(file.filename or "x.png").suffix.lower()
    if suffix not in IMAGE_EXT:
        raise HTTPException(422, f"只接受图片 {sorted(IMAGE_EXT)}")
    data = await file.read()
    if not data:
        raise HTTPException(422, "空文件")
    slot, cat_name = CATS[cat]
    by = _actor(request)
    sha = hashlib.sha256(data).hexdigest()
    with _lock:
        ids = {i.id for i in store.wardrobe().items}
        dup = None if force else _dup_of(store, cid, sha)
        if dup:
            # 不是错误：前端先调 check-image，给“用这件 / 仍作为新单品”两条出路；这里只防直接调接口时重复登记
            raise HTTPException(409, {"message": f"这张图已经在库里：“{dup.name}”。可以直接用这件（挂到造型），或仍作为新单品添加（force=true）",
                                      "item_id": dup.id, "dup": True})
        iid = _new_item_id(cid, slot, ids)
        d = _root() / "assets" / "characters" / cid / "wardrobe"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{iid}_v1{suffix}"
        dest.write_bytes(data)
        now = _now()
        img = ItemImage(file=_rel(dest), variant="clean", version=1, sha256=sha, source="upload", created_at=now)
        it = WardrobeItem(id=iid, slot=slot, name=name, character=cid, images=[img], reference_images=[img.file],
                          source="hub_upload", tags=[cat_name] if cat in TAG_CATS.values() else [],
                          notes=[f"上传：{by}", f"人物资产页上传 {now}"] + ([f"备注：{note.strip()}"] if note.strip() else []),
                          version=1)

        def fn():
            w = store.wardrobe()
            w.items.append(it)
            store._write("wardrobe", w)
        store._mutate(fn)
        man = d / "manifest.json"
        m = _rjson(man, [])
        m.append({"file": dest.name, "kind": f"item/{slot}", "name": name, "item_id": iid, "variant": "clean",
                  "version": 1, "sha256": sha, "source": "upload", "by": by, "created_at": now})
        _wjson(man, m)
    _record_version(iid, img.file, by)
    mapped = []
    for t in targets:
        prev = _set_map(pj, cid, str(t["look"]), str(t["part"]).strip(), iid, by)
        mapped.append({"look": t["look"], "part": t["part"], "prev": prev})
    _log(by, cid, "upload", item_id=iid, name=name, cat=cat, file=img.file, mapped=mapped)
    return {"ok": True, "item": _item_dict(it, {iid: [{"look": m["look"], "part": m["part"]} for m in mapped]}),
            "mapped": mapped, "by": by}


def _record_version(item_id: str, f: str, by: str, version: int = 1) -> None:
    """版本链：单品的版本链按 images[] 显示（/api/assets/{id}/chain）；这里另在 asset_versions 记一条 v1，带上传人"""
    try:
        from ns_api import asset_edit as AE
        with AE._lock:
            allv = AE._read("asset_versions")
            allv.setdefault(item_id, []).append({"asset_id": item_id, "version": version, "file": f, "in_place": True,
                                                  "origin": "upload", "label": "上传", "by": by, "created_at": _now()})
            AE._write("asset_versions", allv)
    except Exception:  # noqa: BLE001  版本账本写不了不影响单品本身
        pass


@router.post("/api/character-hub/{cid}/items/{item_id}/images", status_code=201)
async def add_item_image(cid: str, item_id: str, request: Request, file: UploadFile = File(...),
                         store: LookStore = Depends(get_store)):
    """给一件单品再加一张图（同一单品的另一角度）。加在后面：主参考图（images[0]）不变；版本号 +1，进版本链"""
    suffix = Path(file.filename or "x.png").suffix.lower()
    if suffix not in IMAGE_EXT:
        raise HTTPException(422, f"只接受图片 {sorted(IMAGE_EXT)}")
    data = await file.read()
    if not data:
        raise HTTPException(422, "空文件")
    sha = hashlib.sha256(data).hexdigest()
    by = _actor(request)
    with _lock:
        it = next((i for i in store.wardrobe().items if i.id == item_id and i.character == cid), None)
        if not it:
            raise HTTPException(404, f"没有这件单品：{item_id}")
        if any(im.sha256 == sha for im in it.images):
            raise HTTPException(409, "这张图这件单品已经有了")
        v = 1 + max((im.version for im in it.images), default=0)
        d = _root() / "assets" / "characters" / cid / "wardrobe"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{item_id}_v{v}{suffix}"
        dest.write_bytes(data)
        img = ItemImage(file=_rel(dest), variant="clean", version=v, sha256=sha, source="upload", created_at=_now())

        def fn():
            w = store.wardrobe()
            x = next(i for i in w.items if i.id == item_id)
            x.images.append(img)
            x.reference_images = [r for r in x.reference_images if r != img.file] + [img.file]
            x.version = max(x.version, v)
            store._write("wardrobe", w)
        store._mutate(fn)
        man = d / "manifest.json"
        m = _rjson(man, [])
        m.append({"file": dest.name, "kind": f"item/{it.slot}", "name": it.name, "item_id": item_id, "variant": "clean",
                  "version": v, "sha256": sha, "source": "upload", "by": by, "created_at": img.created_at})
        _wjson(man, m)
    _record_version(item_id, img.file, by, v)
    _log(by, cid, "add_image", item_id=item_id, name=it.name, file=img.file, version=v)
    return {"ok": True, "image": _img(img.file), "version": v, "by": by}


# ---------------------------------------------------------------- 选图后先查：是不是已经在库里 + 起个人话名字
def _adopted_path() -> Path:
    return _root() / "data" / "looks" / "character_hub_adopted.json"


def _adopted(project: str, cid: str) -> list[str]:
    """旧剧登记的单品被当前剧“拿来用”（不一定挂造型）：记在这里，人物页把它显示在当前衣橱里"""
    return [x for x in ((_rjson(_adopted_path(), {}).get(project) or {}).get(cid) or []) if isinstance(x, str)]


def _sha_file(p: Path) -> str | None:
    try:
        return hashlib.sha256(p.read_bytes()).hexdigest()
    except OSError:
        return None


def _dup_of(store: LookStore, cid: str, sha: str) -> WardrobeItem | None:
    """同一个人的单品里有没有同一张图：先比登记的 sha256，再比 reference_images 的文件内容（旧剧导入的单品常常只有文件）"""
    items = [i for i in store.wardrobe().items if i.character == cid]
    for i in items:
        if any(im.sha256 == sha for im in i.images):
            return i
    for i in items:
        for f in [im.file for im in i.images if not im.sha256] + list(i.reference_images):
            q = _root() / f
            if q.suffix.lower() in IMAGE_EXT and q.is_file() and _sha_file(q) == sha:
                return i
    return None


NAME_SYSTEM = ("你给服装 / 鞋 / 配饰 / 身体饰品单品起中文名，只看图片。按“颜色 + 材质 + 款式”写 6–14 个字，"
               "例如“黑色漆皮细带捆绑内衣”“透明侧开细高跟”。不加引号、不加解释、不写品牌。"
               "另外判断类别，只能是 outfit / shoes / accessory / body / nails / bag / hair / makeup 之一。"
               '只输出一行 JSON：{"name": "…", "cat": "…"}')


def _name_from_model(data: bytes, cat: str | None) -> dict:
    """调逻辑模型（abliteration，关推理）看图起名；失败返回 {}（界面让项目方自己写，不报错）"""
    import base64
    import io
    from PIL import Image
    from ns_api import llm_config as L
    im = Image.open(io.BytesIO(data)).convert("RGB")
    im.thumbnail((448, 448))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=82)
    url_ = "data:image/jpeg;base64," + base64.b64encode(b.getvalue()).decode()
    try:
        rv = L.resolve("asset_name", {"params": {"reasoning": False}})
    except Exception:  # noqa: BLE001  没配 asset_name 用途 → 用逻辑模型（edit_plan）的设置
        rv = L.resolve("edit_plan", {"params": {"reasoning": False}})
    hint = f"项目方选的类别：{CATS[cat][1]}" if cat in CATS else "类别还没选"
    msgs = [{"role": "system", "content": NAME_SYSTEM},
            {"role": "user", "content": [{"type": "text", "text": hint}, {"type": "image_url", "image_url": {"url": url_}}]}]
    with L.chat_request(rv, msgs, False, 80) as r:
        d = json.loads(r.read().decode("utf-8"))
    txt = ((d.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    m = re.search(r"\{.*\}", txt, re.S)
    try:
        out = json.loads(m.group(0)) if m else {"name": txt}
    except ValueError:
        out = {"name": txt}
    name = re.sub(r"[\"“”'「」\s{}:]|name|cat", "", str(out.get("name") or ""))[:24]
    c = out.get("cat") if out.get("cat") in CATS else None
    return {"name": name, "cat": c, "model": f"{rv.get('id')}/{rv.get('model')}"} if name else {}


@router.post("/api/character-hub/{cid}/check-image")
async def check_image(cid: str, file: UploadFile = File(...), cat: str | None = Form(None), name: bool = Form(True),
                      ignore_dup: bool = Form(False), project: str | None = Form(None), store: LookStore = Depends(get_store)):
    """选图后马上调（不写任何东西）：
    - 已经在库里 → dup = 那件单品（图、名字、属于哪些造型、在不在当前衣橱），界面给“用这件，挂到所选造型”；
    - 不在库里 → 看图起名（name=false 时不调模型）。名字永远不用文件名。"""
    pj = current_project(project)
    data = await file.read()
    if not data:
        raise HTTPException(422, "空文件")
    sha = hashlib.sha256(data).hexdigest()
    dup = None if ignore_dup else _dup_of(store, cid, sha)
    if dup:
        d = character(pj, cid, store, all_items=True)
        it = next((x for x in d["items"] if x["id"] == dup.id), None)
        cur = {x["id"] for x in character(pj, cid, store)["items"]}
        return {"dup": it, "dup_in_current": dup.id in cur,
                "suggested": {"name": it["name"] if it else dup.name, "source": "existing"}}
    sug: dict = {}
    if name:
        try:
            sug = _name_from_model(data, cat)
        except Exception as e:  # noqa: BLE001  起名失败不挡上传
            sug = {"error": str(e)[:200]}
    return {"dup": None, "dup_in_current": False,
            "suggested": {"name": sug.get("name") or "", "cat": sug.get("cat"),
                          "source": "model" if sug.get("name") else "none", "model": sug.get("model"),
                          "error": sug.get("error")}}


class AdoptBody(BaseModel):
    looks: list[dict] = []
    remove: bool = False
    project: str | None = None


@router.post("/api/character-hub/{cid}/items/{item_id}/adopt")
def adopt_item(cid: str, item_id: str, body: AdoptBody, request: Request, store: LookStore = Depends(get_store)):
    """“用这件”：把（可能是旧剧登记的）单品放进当前剧衣橱，并挂到选的造型部件。返回 prev 供撤销。
    remove=true = 撤销“放进当前剧衣橱”（映射的撤销由前端用 prev 调 /map）。"""
    pj = current_project(body.project)
    it = next((i for i in store.wardrobe().items if i.id == item_id and i.character == cid), None)
    if not it:
        raise HTTPException(404, f"没有这件单品：{item_id}")
    by = _actor(request)
    with _lock:
        d = _rjson(_adopted_path(), {})
        lst = d.setdefault(pj, {}).setdefault(cid, [])
        was = item_id in lst
        if body.remove:
            d[pj][cid] = [x for x in lst if x != item_id]
        elif not was:
            lst.append(item_id)
        _wjson(_adopted_path(), d)
    mapped = []
    if not body.remove:
        for t in body.looks:
            if t.get("look") and t.get("part"):
                prev = _set_map(pj, cid, str(t["look"]), str(t["part"]).strip(), item_id, by)
                mapped.append({"look": t["look"], "part": t["part"], "prev": prev})
    _log(by, cid, "unadopt" if body.remove else "adopt", item_id=item_id, name=it.name, mapped=mapped)
    return {"ok": True, "was_adopted": was, "mapped": mapped, "by": by}


class NewLookBody(BaseModel):
    use: str = ""
    outfit: str = ""
    shoes: str = ""
    accessory: str = ""
    project: str | None = None


@router.post("/api/character-hub/{cid}/looks", status_code=201)
def new_look(cid: str, body: NewLookBody, request: Request):
    """＋ 新造型（回退清单 P0-3）：下一个字母；部件文字由项目方填（系统只存，不写内容）。设定图另传。"""
    pj = current_project(body.project)
    if cid not in {c["cid"] for c in _cast(pj)}:
        raise HTTPException(404, f"当前剧里没有这个人物：{cid}")
    by = _actor(request)
    with _lock:
        have = {lk["look"] for lk in _inventory(pj, cid)}
        lid = next((ch for ch in "ABCDEFGHIJKLMNOPQRSTUVWXYZ" if ch not in have), None)
        if not lid:
            raise HTTPException(409, "造型字母用完了")
        zh = "｜".join(f"{k}={v.strip()}" for k, v in (("服装", body.outfit), ("鞋", body.shoes), ("饰品", body.accessory)) if v.strip())
        d = _rjson(_extra_looks_path(), {})
        d.setdefault(pj, {}).setdefault(cid, []).append({"id": lid, "use": body.use.strip(), "zh": zh, "_by": by, "_at": _now()})
        _wjson(_extra_looks_path(), d)
    _log(by, cid, "new_look", look=lid, name=body.use.strip())
    return {"ok": True, "look": lid, "by": by}


@router.post("/api/character-hub/{cid}/looks/{look}/remove")
def remove_look(cid: str, look: str, request: Request, project: str | None = None):
    """撤销“新造型”（只认人物页新建的；剧本登记的造型不能在这里删）。记录移到 _removed，不删文件"""
    pj = current_project(project)
    by = _actor(request)
    with _lock:
        d = _rjson(_extra_looks_path(), {})
        lst = (d.get(pj) or {}).get(cid) or []
        hit = [x for x in lst if x.get("id") == look]
        if not hit:
            raise HTTPException(404, f"造型 {look} 不是人物页新建的，不能在这里撤销")
        d[pj][cid] = [x for x in lst if x.get("id") != look]
        d.setdefault("_removed", []).append({**hit[0], "project": pj, "cid": cid, "removed_by": by, "removed_at": _now()})
        _wjson(_extra_looks_path(), d)
    _log(by, cid, "remove_look", look=look)
    return {"ok": True}


@router.post("/api/character-hub/{cid}/looks/{look}/sheet", status_code=201)
async def upload_sheet(cid: str, look: str, request: Request, file: UploadFile = File(...), project: str | None = Form(None)):
    """给造型上传一张设定图（成为候选并设为当前；原来的当前图还在候选里）"""
    pj = current_project(project)
    if look not in {lk["look"] for lk in _inventory(pj, cid)}:
        raise HTTPException(404, f"没有造型 {look}")
    suffix = Path(file.filename or "x.png").suffix.lower()
    if suffix not in IMAGE_EXT:
        raise HTTPException(422, f"只接受图片 {sorted(IMAGE_EXT)}")
    data = await file.read()
    if not data:
        raise HTTPException(422, "空文件")
    d = _root() / "assets" / "characters" / cid / "looks"
    d.mkdir(parents=True, exist_ok=True)
    dest = d / f"{cid}_look{look}_up{time.strftime('%m%d%H%M%S')}{suffix}"
    dest.write_bytes(data)
    r = set_sheet(cid, SheetBody(look=look, file=_rel(dest), project=pj), request)
    return {**r, "uploaded": _rel(dest)}


class ScheduleBody(BaseModel):
    ep: int
    look: str | None = None
    project: str | None = None


@router.post("/api/character-hub/{cid}/schedule")
def set_schedule(cid: str, body: ScheduleBody, request: Request):
    """排期（回退清单 P1-13）：第 ep 集整集用哪套造型；look=null = 不覆盖（回到按剧本逐镜登记）。返回 prev 供撤销"""
    pj = current_project(body.project)
    if body.look is not None and body.look not in {lk["look"] for lk in _inventory(pj, cid)}:
        raise HTTPException(422, f"没有造型 {body.look}")
    by = _actor(request)
    with _lock:
        d = _rjson(_episode_looks_path(), {})
        m = d.setdefault(pj, {}).setdefault(cid, {})
        prev = m.get(str(body.ep))
        if body.look is None:
            m.pop(str(body.ep), None)
        else:
            m[str(body.ep)] = body.look
        m["_by"], m["_at"] = by, _now()
        _wjson(_episode_looks_path(), d)
    _log(by, cid, "schedule", ep=body.ep, look=body.look, prev=prev)
    return {"ok": True, "ep": body.ep, "look": body.look, "prev": prev, "by": by}


# ---------------------------------------------------------------- ✗ 不要（UIMASTER UM-P0-02：每个待审对象都要有“用这张 / 不要”）
def _rejects_path() -> Path:
    return _root() / "data" / "looks" / "asset_rejects.jsonl"


class RejectBody(BaseModel):
    kind: str                      # face | sheet | scene_plate | item_image | other
    file: str                      # 相对项目根
    reasons: list[str] = []
    note: str = ""
    redo: bool = False             # true = 前端另调 /api/edits 重出；这里只记账
    cid: str | None = None
    undo: bool = False             # 撤销“不要”


@router.post("/api/asset-rejects")
def reject_asset(body: RejectBody, request: Request):
    """记下“这张不要”（原因 chip + 一句话）。不删文件、不动当前选择；界面把它标成“不要”。撤销 = undo=true"""
    if not body.file or body.file.startswith(("/", "..")) or ".." in body.file:
        raise HTTPException(422, "file 要是相对项目根的路径")
    by = _actor(request)
    rec = {"at": _now(), "by": by, "kind": body.kind, "file": body.file, "reasons": body.reasons[:8],
           "note": body.note.strip()[:300], "redo": body.redo, "cid": body.cid, "undo": body.undo}
    p = _rejects_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock, p.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    if body.cid:
        _log(by, body.cid, "unreject" if body.undo else "reject", kind=body.kind, file=body.file, reasons=body.reasons)
    return {"ok": True, "by": by}


def rejected_map() -> dict[str, dict]:
    out: dict[str, dict] = {}
    try:
        lines = _rejects_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return out
    for ln in lines:
        try:
            r = json.loads(ln)
        except ValueError:
            continue
        if r.get("undo"):
            out.pop(r.get("file"), None)
        else:
            out[r.get("file")] = {"reasons": r.get("reasons") or [], "note": r.get("note") or "", "at": r.get("at"), "by": r.get("by")}
    return out


@router.get("/api/asset-rejects")
def list_rejects():
    return {"rejected": rejected_map()}


class PrimaryBody(BaseModel):
    file: str


@router.post("/api/character-hub/{cid}/items/{item_id}/primary")
def set_primary(cid: str, item_id: str, body: PrimaryBody, request: Request, store: LookStore = Depends(get_store)):
    """单品附图“✓ 用这张”：把这张图挪到 images[0]（出图解析器取第一张当主参考）。返回 prev（原主图）供撤销"""
    by = _actor(request)
    out = {}

    def fn():
        w = store.wardrobe()
        it = next((i for i in w.items if i.id == item_id and i.character == cid), None)
        if not it:
            raise HTTPException(404, f"没有这件单品：{item_id}")
        idx = next((k for k, im in enumerate(it.images) if im.file == body.file), None)
        if idx is None:
            raise HTTPException(422, "这张图不是这件单品的图")
        out["prev"] = it.images[0].file if it.images else None
        im = it.images.pop(idx)
        it.images.insert(0, im)
        it.reference_images = [im.file] + [r for r in it.reference_images if r != im.file]
        store._write("wardrobe", w)
    store._mutate(fn)
    _log(by, cid, "primary", item_id=item_id, file=body.file, prev=out.get("prev"))
    return {"ok": True, "file": body.file, "prev": out.get("prev"), "by": by}


# ---------------------------------------------------------------- 隔离区（RECALL 11-01：data/_quarantine_<日期>/moves.jsonl）
@router.get("/api/asset-quarantine")
def asset_quarantine():
    """只读：已移进隔离区的东西（文件名 / 目录名 / 原路径）。资产中心据此不列、不链接隔离项（旧 60 集场景、外国演员、旧音色、证伪的 LoRA）"""
    names, paths = set(), []
    for man in sorted((_root() / "data").glob("_quarantine_*/moves.jsonl")):
        try:
            lines = man.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for ln in lines:
            try:
                r = json.loads(ln)
            except ValueError:
                continue
            if r.get("status") not in (None, "moved"):
                continue
            src = str(r.get("src") or "").replace("\\", "/")
            if not src:
                continue
            paths.append(src)
            base = src.rstrip("/").split("/")[-1]
            names.add(base)
            names.add(re.sub(r"\.[A-Za-z0-9]+$", "", base))
    return {"names": sorted(names), "paths": paths}


# ---------------------------------------------------------------- ↻ 再生成（项目方 11-01：“加个生成按钮，弹出需求提示词输入框，upload 对应的装备图片，然后生图”）
REGEN_TAG = "再生成·"


def _safe_path(rel: str) -> Path | None:
    """相对项目根的图片路径 → 绝对路径；跳出项目根 / 绝对路径 / 不是图片 → None"""
    if not rel or rel.startswith(("/", "\\")) or ":" in rel or ".." in rel.replace("\\", "/").split("/"):
        return None
    p = (_root() / rel).resolve()
    if not p.is_relative_to(_root().resolve()) or p.suffix.lower() not in IMAGE_EXT:
        return None
    return p


class RegenGear(BaseModel):
    path: str
    label: str = ""
    item_id: str | None = None


class RegenBody(BaseModel):
    kind: str                       # sheet | face | item
    file: str                       # 底图（当前设定图 / 身份脸 / 单品主图），相对项目根
    prompt: str
    look: str | None = None         # kind=sheet 时：哪套造型
    item_id: str | None = None      # kind=item 时
    gear: list[RegenGear] = []      # 弹窗里上传 / 选的装备图（已登记进衣橱）
    project: str | None = None


@router.post("/api/character-hub/{cid}/regen", status_code=202)
def regen(cid: str, body: RegenBody, request: Request, store: LookStore = Depends(get_store)):
    """资产图“↻ 再生成”：以当前图为底图 + 装备图作“取这一件”参考 + 需求提示词，走资产生成（asset gen-jobs）。
    出好的图记在生成记录里（label = 再生成·<kind>[:造型]），作为候选出现在对应位置，点“✓ 用这张”才生效。"""
    from ns_api import asset_edit as AE
    if body.kind not in ("sheet", "face", "item"):
        raise HTTPException(422, "kind 只能是 sheet | face | item")
    if not body.prompt.strip():
        raise HTTPException(422, "写一句要改成什么样")
    if body.kind == "sheet" and not (body.look and re.fullmatch(r"[A-Z]", body.look)):
        raise HTTPException(422, "再生成设定图要说是哪套造型")
    asset_id = body.item_id if body.kind == "item" else cid
    if body.kind == "item" and not any(i.id == asset_id and i.character == cid for i in store.wardrobe().items):
        raise HTTPException(404, f"没有这件单品：{asset_id}")
    base = _safe_path(body.file)
    if not base or not base.is_file():
        raise HTTPException(404, f"底图不在：{body.file}")
    asset = AE.resolve_asset(store, asset_id)
    refs = []
    for g in body.gear[:4]:
        src = _safe_path(g.path)
        if not src or not src.is_file():
            continue
        r = AE.add_ref(asset, src.read_bytes(), src.suffix, "item", "regen",
                       {"path": g.path, "item_id": g.item_id}, note=f"再生成装备参考：{g.label}".strip("："))
        refs.append(AE.GenRef(ref_id=r["ref_id"], role="item"))
    tag = f"sheet:{body.look}" if body.kind == "sheet" else body.kind
    job = AE.create_gen_job(asset_id, AE.GenBody(base=body.file, refs=refs, prompt=body.prompt.strip(),
                                                 label=f"{REGEN_TAG}{tag}"), store)
    by = _actor(request)
    _log(by, cid, "regen", kind=body.kind, look=body.look, item_id=body.item_id, prompt=body.prompt.strip()[:200],
         gear=[g.label or g.path for g in body.gear], job_id=(job or {}).get("job_id"))
    return {"ok": True, "job": job, "asset_id": asset_id, "label": f"{REGEN_TAG}{tag}", "by": by}


class AdoptGenBody(BaseModel):
    file: str


@router.post("/api/character-hub/{cid}/items/{item_id}/use-regen")
async def use_item_regen(cid: str, item_id: str, body: AdoptGenBody, request: Request, store: LookStore = Depends(get_store)):
    """单品“再生成”出的候选点“✓ 用这张”：作为新的一张图加进单品并设为主图。返回 prev 主图供撤销"""
    if body.file not in _regen_files(item_id, "item"):
        raise HTTPException(422, "这张不是这件单品再生成出的候选")
    by = _actor(request)
    src = _root() / body.file
    data = src.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    out: dict = {}

    def fn():
        w = store.wardrobe()
        it = next((i for i in w.items if i.id == item_id and i.character == cid), None)
        if not it:
            raise HTTPException(404, f"没有这件单品：{item_id}")
        out["prev"] = it.images[0].file if it.images else None
        hit = next((im for im in it.images if im.sha256 == sha), None)
        if hit is None:
            v = 1 + max((im.version for im in it.images), default=0)
            d = _root() / "assets" / "characters" / cid / "wardrobe"
            d.mkdir(parents=True, exist_ok=True)
            dest = d / f"{item_id}_v{v}{src.suffix.lower()}"
            dest.write_bytes(data)
            hit = ItemImage(file=_rel(dest), variant="clean", version=v, sha256=sha, source="generated", created_at=_now())
            it.version = max(it.version, v)
        else:
            it.images.remove(hit)
        it.images.insert(0, hit)
        it.reference_images = [hit.file] + [r for r in it.reference_images if r != hit.file]
        out["file"] = hit.file
        store._write("wardrobe", w)
    store._mutate(fn)
    _log(by, cid, "primary", item_id=item_id, file=out["file"], prev=out.get("prev"), from_regen=body.file)
    return {"ok": True, "file": out["file"], "prev": out.get("prev"), "by": by}


class UnuseRegenBody(BaseModel):
    file: str                 # use-regen 返回的 file（加进单品的那张）
    prev: str | None = None   # use-regen 返回的 prev（原来的主图）


@router.post("/api/character-hub/{cid}/items/{item_id}/unuse-regen")
def unuse_item_regen(cid: str, item_id: str, body: UnuseRegenBody, request: Request, store: LookStore = Depends(get_store)):
    """撤销“用这张”（再生成候选）：把 use-regen 加进单品的那张图拿掉（只拿掉 source=generated 的；文件留着，候选还在），
    主图回到 prev。单品回到用之前的样子"""
    by = _actor(request)
    out: dict = {}

    def fn():
        w = store.wardrobe()
        it = next((i for i in w.items if i.id == item_id and i.character == cid), None)
        if not it:
            raise HTTPException(404, f"没有这件单品：{item_id}")
        added = next((im for im in it.images if im.file == body.file and im.source == "generated"), None)
        if added:
            it.images.remove(added)
            it.reference_images = [r for r in it.reference_images if r != added.file]
        if body.prev:
            hit = next((im for im in it.images if im.file == body.prev), None)
            if hit:
                it.images.remove(hit)
                it.images.insert(0, hit)
                it.reference_images = [hit.file] + [r for r in it.reference_images if r != hit.file]
        it.version = max((im.version for im in it.images), default=1)
        out["removed"] = bool(added)
        store._write("wardrobe", w)
    store._mutate(fn)
    _log(by, cid, "unuse_regen", item_id=item_id, file=body.file, prev=body.prev)
    return {"ok": True, "removed": out["removed"], "by": by}


class RenameBody(BaseModel):
    name: str


@router.post("/api/character-hub/{cid}/items/{item_id}/rename")
def rename_item(cid: str, item_id: str, body: RenameBody, request: Request, store: LookStore = Depends(get_store)):
    name = body.name.strip()
    if not name:
        raise HTTPException(422, "名称不能为空")
    by = _actor(request)
    prev = {}

    def fn():
        w = store.wardrobe()
        it = next((i for i in w.items if i.id == item_id and i.character == cid), None)
        if not it:
            raise HTTPException(404, f"没有这件单品：{item_id}")
        prev["name"] = it.name
        it.name = name
        store._write("wardrobe", w)
    store._mutate(fn)
    _log(by, cid, "rename", item_id=item_id, name=name, prev=prev.get("name"))
    return {"ok": True, "name": name, "prev": prev.get("name"), "by": by}


@router.post("/api/character-hub/{cid}/items/{item_id}/trash")
def trash_item(cid: str, item_id: str, request: Request, project: str | None = None,
               store: LookStore = Depends(get_store)):
    from ns_api import trash as T
    pj = current_project(project)
    if not any(i.id == item_id and i.character == cid for i in store.wardrobe().items):
        raise HTTPException(404, f"没有这件单品：{item_id}")
    by = _actor(request)
    # 先解除它在造型里的映射（含系统提议），记下来供撤销
    maps = []
    for lid, m in (R.item_map(pj).get(cid) or {}).items():
        for part, iid in m.items():
            if iid == item_id:
                maps.append({"look": lid, "part": part, "prev": _set_map(pj, cid, lid, part, None, by)})
    try:
        entry = T.delete_object(request, type="asset", id=item_id, by=by, reason="人物资产页删除单品")
    except HTTPException:
        for x in maps:     # 删不了：映射还原
            _set_map(pj, cid, x["look"], x["part"], item_id, by)
        raise
    _log(by, cid, "trash", item_id=item_id, entry_id=entry.get("entry_id"), maps=maps)
    return {"ok": True, "entry_id": entry.get("entry_id"), "maps": maps, "by": by}


class RestoreBody(BaseModel):
    entry_id: str
    maps: list[dict] = []
    project: str | None = None


@router.post("/api/character-hub/{cid}/items/{item_id}/restore")
def restore_item(cid: str, item_id: str, body: RestoreBody, request: Request):
    from ns_api import trash as T
    pj = current_project(body.project)
    by = _actor(request)
    T.restore(body.entry_id)
    for x in body.maps:
        if x.get("look") and x.get("part"):
            _set_map(pj, cid, str(x["look"]), str(x["part"]), item_id, by)
    _log(by, cid, "restore", item_id=item_id, entry_id=body.entry_id)
    return {"ok": True, "by": by}
