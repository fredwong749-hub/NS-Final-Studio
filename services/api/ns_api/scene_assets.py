"""
场景资产库（docs/TODO_v1_close.md §6 S2；fredw-92/S-back）。场景 = asset_edit 的一种资产（kind = scene，asset_id = 场景 id），
参考图 / 生成 / 版本全部复用 asset_edit 的接口：

    POST /api/assets/{scene_id}/refs                 上传参考图，role = space|style|color|prop（空间|风格|色彩|道具，中文也收）
    POST /api/assets/{scene_id}/refs/from-take       镜头版本设为参考
    POST /api/assets/{scene_id}/gen-jobs             Image 2.1 文生图 / image2img（jobs.py 按卡队列，默认出图卡 GPU0）
    POST /api/assets/{scene_id}/versions             存为场景底图新版本 {job_id|gen_id|file|take, label, variant?}
                                                     variant = main（主底图，默认）| 机位 / 时段变体名（low、top、night…）

本模块另加：
    GET    /api/assets/scenes                        场景卡列表（描述、底图、定稿状态、出现集数 / 镜数、变体）
    GET    /api/assets/scenes/{scene_id}             场景详情（描述 + 来源、底图 / 变体、版本、参考图、生成记录、用到的镜头）
    POST   /api/assets/scenes/{scene_id}/plate       定稿 {version, variant?, by?: canvas|owner, owner_quote?}
    DELETE /api/assets/scenes/{scene_id}/plate       取消画布定稿 ?variant=（不删文件）

描述：剧本场景表（ScriptGlobals.scene_library，原文）优先，其次 data/scenes.json（state_timeline 推断的地点 / 时段 / 光线）。
定稿：版本图复制成 assets/scenes/<id>/plate.png（变体 plate_<variant>.png），manifest.json 记 locked；
S2 闸门（state_timeline.plate_info）照旧：只有 by=owner 且带项目方原话时才写 owner_confirmed_*（= 闸门通过）；
画布定稿只让底图从 missing 变 candidate（“画布已定稿”），不冒充项目方确认。
定稿换了图 → 带过旧底图的首帧版本过期「场景底图已改」（ns_render.scene_plate.stale_reasons）。不做内容检测。
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import threading
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ns_agent.looks import LookStore
from ns_api import assets as A
from ns_api.looks import get_store
from ns_render import pipeline as P
from ns_render import scene_plate as SP

router = APIRouter(tags=["scene-assets"])
VARIANT_RE = re.compile(r"^[a-z0-9_]{1,32}$")
OWNER_KEYS = ("owner_confirmed_at", "owner_confirmed_ref", "plate_sha256")
_lock = threading.RLock()


def root() -> Path:
    return A.ROOT


# ---------------------------------------------------------------- 场景从哪来

def _store() -> LookStore:
    return get_store()


def _script(store: LookStore | None = None):
    try:
        return (store or _store()).resolver().script
    except Exception:  # noqa: BLE001
        return None


def scenes_json() -> dict[str, dict]:
    try:
        d = json.loads((root() / "data" / "scenes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {s["scene_id"]: s for s in (d.get("scenes") or []) if isinstance(s, dict) and s.get("scene_id")} \
        if isinstance(d, dict) else {}


def library(script) -> dict:
    return {e.scene_id: e for e in getattr(getattr(script, "globals", None), "scene_library", None) or []}


_USAGE: dict[int, tuple[object, dict[str, list[str]]]] = {}


def usage(store: LookStore | None = None) -> dict[str, list[str]]:
    """scene_id → [shot_id…]（剧本 **场景** 优先，其余 group_scenes 推断；与 ref_switch.scene_map 同一口径）"""
    store = store or _store()
    try:
        res = store.resolver()
    except Exception:  # noqa: BLE001
        return {}
    hit = _USAGE.get(id(res.script))
    if hit and hit[0] is res.script:
        return hit[1]
    from ns_api.ref_switch import scene_map
    out: dict[str, list[str]] = {}
    for shot_id, sid in scene_map(res).items():
        out.setdefault(sid, []).append(shot_id)
    _USAGE.clear()
    _USAGE[id(res.script)] = (res.script, out)
    return out


def scene_ids(store: LookStore | None = None) -> list[str]:
    store = store or _store()
    ids = list(library(_script(store)))
    ids += [s for s in scenes_json() if s not in ids]
    ids += [s for s in usage(store) if s not in ids]
    d = SP.scenes_dir(root())
    if d.is_dir():
        ids += sorted(p.name for p in d.iterdir() if p.is_dir() and p.name.startswith("sk_") and p.name not in ids)
    return ids


def scene_exists(scene_id: str, store: LookStore | None = None) -> bool:
    if not scene_id or "/" in scene_id or "\\" in scene_id or ".." in scene_id:
        return False
    if (SP.scenes_dir(root()) / scene_id).is_dir() or scene_id in scenes_json():
        return True
    store = store or _store()
    return scene_id in library(_script(store)) or scene_id in usage(store)


def describe(scene_id: str, store: LookStore | None = None) -> dict:
    """场景描述：剧本场景表原文（source=script）> data/scenes.json 推断（source=scenes.json）"""
    e = library(_script(store)).get(scene_id)
    if e is not None:
        return {"source": "script", "name": e.name, "space": e.space, "time_of_day": e.time_of_day, "light": e.light,
                "fixtures": e.fixtures, "defined_in": list(e.defined_in),
                "conflicts": [c.model_dump() for c in e.conflicts]}
    sj = scenes_json().get(scene_id)
    if sj:
        light = (sj.get("plate_detail") or {}).get("light") or {}
        return {"source": "scenes.json", "name": sj.get("place") or "", "space": "",
                "time_of_day": sj.get("time_of_day") or "", "light": light, "fixtures": "", "times": sj.get("times") or []}
    return {"source": "none", "name": "", "space": "", "time_of_day": "", "light": "", "fixtures": ""}


def scene_name(scene_id: str, store: LookStore | None = None) -> str:
    return describe(scene_id, store).get("name") or scene_id


# ---------------------------------------------------------------- 底图 / 变体 / 状态

def _gate(scene_id: str) -> dict:
    from ns_agent.state_timeline import plate_info
    return plate_info(root(), scene_id)


def current_plate(scene_id: str) -> str | None:
    """场景当前主底图（相对项目根）：manifest.plate / plate.png；没有就 None"""
    man = SP.read_manifest(root(), scene_id)
    p = SP.scenes_dir(root()) / scene_id / (man.get("plate") or "plate.png")
    return p.relative_to(root()).as_posix() if p.is_file() else None


def variants(scene_id: str) -> list[dict]:
    """主底图 + 变体（场景目录下的图片 = ref_switch 的底图候选 plate_id）+ 画布定稿记录"""
    d = SP.scenes_dir(root()) / scene_id
    man = SP.read_manifest(root(), scene_id)
    main_file = man.get("plate") or "plate.png"
    out = []
    for p in sorted(d.iterdir()) if d.is_dir() else []:
        if not (p.is_file() and p.suffix.lower() in A.IMAGE_EXT) or "_face_" in p.stem or p.stem.endswith(("_raw", "_ungraded")):
            continue
        variant = SP.MAIN if p.name == main_file else (p.stem[6:] if p.stem.startswith("plate_") else p.stem)
        lock = SP.lock_record(root(), scene_id, variant) if (variant == SP.MAIN or p.stem.startswith("plate_")) else None
        rel = p.relative_to(root()).as_posix()
        out.append({"variant": variant, "plate_id": f"{scene_id}/{p.name}", "file": rel, "url": A.file_url(rel),
                    "locked": bool(lock), "locked_by": (lock or {}).get("by"), "locked_at": (lock or {}).get("at"),
                    "version": (lock or {}).get("version"), "sha256": SP.sha_file(p)})
    out.sort(key=lambda v: (v["variant"] != SP.MAIN, v["variant"]))
    return out


def plate_view(scene_id: str) -> dict:
    g = _gate(scene_id)
    lock = SP.lock_record(root(), scene_id)
    status = g["plate_status"]
    label = {"owner_confirmed": "项目方已确认", "missing": "没有底图"}.get(status) or \
        ("画布已定稿（待项目方确认）" if lock else "候选（未定稿）")
    cur = current_plate(scene_id)
    return {"file": cur, "url": A.file_url(cur), "plate_status": status, "status_label": label,
            "locked": bool(lock), "locked_by": (lock or {}).get("by"), "locked_at": (lock or {}).get("at"),
            "version": (lock or {}).get("version"), "sha256": g["plate_sha256"],
            "owner_confirmed_at": g["owner_confirmed_at"], "s2_gate_ok": status == "owner_confirmed"}


def _episodes(shots: list[str]) -> list[int]:
    return sorted({int(s[2:4]) for s in shots if s.startswith("ep") and s[2:4].isdigit()})


def scene_card(scene_id: str, store: LookStore, use: dict[str, list[str]]) -> dict:
    from ns_api import asset_edit as AE
    shots = use.get(scene_id, [])
    vers = AE._read("asset_versions").get(scene_id, [])
    return {"scene_id": scene_id, "asset_id": scene_id, "kind": "scene", "name": scene_name(scene_id, store),
            "description": describe(scene_id, store), "plate": plate_view(scene_id), "variants": variants(scene_id),
            "episodes": _episodes(shots), "episode_count": len(_episodes(shots)), "shot_count": len(shots),
            "versions": len(vers), "refs": len(AE._read("asset_refs").get(scene_id, []))}


@router.get("/api/assets/scenes")
def list_scenes(store: LookStore = Depends(get_store)):
    from ns_api import asset_edit as AE
    use = usage(store)
    return {"roles": [{"id": r, "label": AE.SCENE_ROLE_LABEL[r]} for r in AE.SCENE_ROLES],
            "scenes": [scene_card(sid, store, use) for sid in scene_ids(store)]}


@router.get("/api/assets/scenes/{scene_id}")
def get_scene(scene_id: str, store: LookStore = Depends(get_store)):
    """与 GET /api/assets/characters/{cid} 同形：assets:[{id,asset_id,kind,name,file,url,refs,versions,gens}] 给资产编辑器"""
    from ns_api import asset_edit as AE
    if not scene_exists(scene_id, store):
        raise HTTPException(404, f"没有这个场景：{scene_id}")
    use = usage(store)
    shots = use.get(scene_id, [])
    refs = [AE._with_url(r) for r in AE._read("asset_refs").get(scene_id, [])]
    vers = [AE._with_url(v) for v in AE._read("asset_versions").get(scene_id, [])]
    gens = [AE._gen_view(g) for g in AE._read("asset_gens").get(scene_id, [])]
    script = _script(store)
    details = {}
    for ep in getattr(script, "episodes", None) or []:
        for s in ep.shots:
            if s.id in shots:
                details[s.id] = {"shot_id": s.id, "episode": ep.number, "index": s.index,
                                 "scene_detail": getattr(s, "scene_detail", None),
                                 "scene_source": "script" if getattr(s, "scene_id", None) else "inferred"}
    cur = current_plate(scene_id)
    card = scene_card(scene_id, store, use)
    return {**card, "refs_list": refs, "version_list": vers, "gens": gens,
            "usage": {"episodes": _episodes(shots), "shots": [details.get(s, {"shot_id": s}) for s in shots]},
            "roles": [{"id": r, "label": AE.SCENE_ROLE_LABEL[r]} for r in AE.SCENE_ROLES],
            "strengths": AE.denoise_map(),
            "assets": [{"id": scene_id, "asset_id": scene_id, "kind": "scene", "name": card["name"], "slot": None,
                        "file": cur, "url": A.file_url(cur), "refs": refs, "versions": vers, "gens": gens}],
            "asset_refs": {scene_id: refs} if refs else {}, "asset_versions": {scene_id: vers} if vers else {},
            "asset_gens": {scene_id: gens} if gens else {}, "ref_roles": [{"id": r, "label": AE.SCENE_ROLE_LABEL[r]}
                                                                       for r in AE.SCENE_ROLES]}


# ---------------------------------------------------------------- 版本（asset_edit.save_version 转来）

def save_scene_version(asset: dict, src: Path, origin: dict, body) -> dict:
    from ns_api import asset_edit as AE
    sid = asset["id"]
    variant = SP.MAIN if body.variant in (None, "", "clean") else body.variant
    if not VARIANT_RE.match(variant):
        raise HTTPException(422, "variant 只能是 main 或小写英文 / 数字 / 下划线（如 low、top、night）")
    data = src.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    with _lock:
        allv = AE._read("asset_versions")
        prev = allv.get(sid, [])
        version = 1 + max((int(v.get("version") or 0) for v in prev), default=0)
        d = SP.scenes_dir(root()) / sid / "versions"
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{sid}_{variant}_v{version}{src.suffix.lower()}"
        dest.write_bytes(data)
        rec = {"version": version, "asset_id": sid, "from_asset": sid, "kind": "scene", "variant": variant,
               "in_place": True, "file": A.rel(dest), "label": body.label, "origin": origin, "sha256": sha,
               "created_at": AE._now()}
        allv.setdefault(sid, []).append(rec)
        AE._write("asset_versions", allv)
    return {**AE._with_url(rec), "affected_shots": [], "locked": False,
            "message": "已存为场景底图新版本；定稿请调 POST /api/assets/scenes/{id}/plate"}


# ---------------------------------------------------------------- 定稿

class PlateLockBody(BaseModel):
    version: int
    variant: str | None = None          # 不给 = 该版本存的 variant
    by: str = "canvas"                  # canvas | owner（owner 必须带项目方原话）
    owner_quote: str | None = None


def _stale_shots(scene_id: str, store: LookStore) -> list[str]:
    """用到这个场景、首帧版本带过本场景底图且那张图已不是当时那张 → 过期（「场景底图已改」）"""
    out = []
    for shot_id in usage(store).get(scene_id, []):
        try:
            takes = P.load_takes(shot_id).get("takes") or []
        except Exception:  # noqa: BLE001
            continue
        if any(t.get("stage") == "image" and (t.get("scene_plate") or {}).get("scene_id") == scene_id
               and SP.stale_reasons(t, root()) for t in takes):
            out.append(shot_id)
    return out


def _rebuild() -> None:
    """项目数据目录（非测试沙箱）→ 后台重建 state_timeline.json + scenes.json（S2 闸门读 scenes.json）"""
    try:
        if Path(root()).resolve() != Path(P.ROOT).resolve():
            return
        from ns_agent.state_timeline import schedule_rebuild
        schedule_rebuild(root())
    except Exception:  # noqa: BLE001
        pass


@router.post("/api/assets/scenes/{scene_id}/plate")
def lock_plate(scene_id: str, body: PlateLockBody, store: LookStore = Depends(get_store)):
    from ns_api import asset_edit as AE
    if not scene_exists(scene_id, store):
        raise HTTPException(404, f"没有这个场景：{scene_id}")
    if body.by not in ("canvas", "owner"):
        raise HTTPException(422, "by 只能是 canvas | owner")
    quote = (body.owner_quote or "").strip()
    if body.by == "owner" and not quote:
        raise HTTPException(422, "by=owner 必须带项目方原话 owner_quote（S2 闸门的确认要能追溯到项目方本人）")
    rec = next((v for v in AE._read("asset_versions").get(scene_id, []) if int(v.get("version") or 0) == body.version),
               None)
    if not rec or not (root() / rec["file"]).is_file():
        raise HTTPException(404, f"{scene_id} 没有底图版本 v{body.version}")
    variant = body.variant or rec.get("variant") or SP.MAIN
    if not VARIANT_RE.match(variant):
        raise HTTPException(422, "variant 只能是 main 或小写英文 / 数字 / 下划线")
    if body.by == "owner" and variant != SP.MAIN:
        raise HTTPException(422, "项目方确认只针对主底图（S2 闸门）；变体用 by=canvas 定稿")
    src = root() / rec["file"]
    data = src.read_bytes()
    sha = hashlib.sha256(data).hexdigest()
    now = SP.now()
    with _lock:
        man = SP.read_manifest(root(), scene_id)
        d = SP.scenes_dir(root()) / scene_id
        d.mkdir(parents=True, exist_ok=True)
        stem = SP.variant_stem(variant)
        old_name = (man.get("plate") or "plate.png") if variant == SP.MAIN else \
            ((man.get("locked_variants") or {}).get(variant) or {}).get("file")
        dest = d / f"{stem}{src.suffix.lower()}"
        for old in {d / old_name if old_name else None, dest} - {None}:
            if old.is_file() and SP.sha_file(old) != sha:      # 旧图留档，不覆盖丢失
                hist = d / "history"
                hist.mkdir(exist_ok=True)
                shutil.copy2(old, hist / f"{old.stem}_{now.replace(':', '').replace('-', '')}{old.suffix}")
        dest.write_bytes(data)
        lock = {"by": body.by, "at": now, "sha256": sha, "version": body.version, "variant": variant, "file": dest.name,
                "source_file": rec["file"]}
        if variant == SP.MAIN:
            man.update(plate=dest.name, scene_id=scene_id, locked=lock)
            if body.by == "owner":
                man.update(owner_confirmed_at=now, owner_confirmed_ref=quote, plate_sha256=sha)
            elif man.get("plate_sha256") != sha:
                for k in OWNER_KEYS:                    # 换了图 → 旧的项目方确认作废（plate_info 也按 sha 判）
                    man.pop(k, None)
        else:
            man.setdefault("locked_variants", {})[variant] = lock
        man.setdefault("variants", {})[stem] = {"file": dest.name, "sha256": sha, "version": body.version,
                                                "locked_by": body.by, "locked_at": now, "source": "canvas"}
        SP.write_manifest(root(), scene_id, man)
        allv = AE._read("asset_versions")
        for v in allv.get(scene_id, []):
            if v.get("variant", SP.MAIN) == variant or (variant == SP.MAIN and not v.get("variant")):
                v["locked"] = int(v.get("version") or 0) == body.version
        AE._write("asset_versions", allv)
    stale = _stale_shots(scene_id, store)
    _rebuild()
    return {"scene_id": scene_id, "variant": variant, "plate_id": f"{scene_id}/{dest.name}",
            "file": dest.relative_to(root()).as_posix(), "url": A.file_url(dest.relative_to(root()).as_posix()),
            "plate": plate_view(scene_id), "stale_shots": stale, "stale_reason": SP.STALE_REASON if stale else None}


@router.delete("/api/assets/scenes/{scene_id}/plate")
def unlock_plate(scene_id: str, variant: str = SP.MAIN, store: LookStore = Depends(get_store)):
    """取消画布定稿（文件与项目方确认都不动；项目方确认的撤销仍走 tools/sop_owner.py plate --revoke）"""
    if not scene_exists(scene_id, store):
        raise HTTPException(404, f"没有这个场景：{scene_id}")
    with _lock:
        man = SP.read_manifest(root(), scene_id)
        if variant == SP.MAIN:
            man.pop("locked", None)
        else:
            (man.get("locked_variants") or {}).pop(variant, None)
        SP.write_manifest(root(), scene_id, man)
    _rebuild()
    return {"scene_id": scene_id, "variant": variant, "plate": plate_view(scene_id)}
