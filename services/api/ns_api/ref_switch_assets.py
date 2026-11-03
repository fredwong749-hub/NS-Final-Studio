"""“切换本镜参考”的资产项目分支（DATA_MAP §6-1，REFLOCK 2026-11-01，总调度派：控件改了出图不变 = bug）。

series10 这类资产项目（config/recipes/asset_refs.json 登记）出图走 ns_agent.asset_refs.resolve_shot（唯一出图路径 K-REN-134），
不读旧造型库的 ref_overrides。这里让 GET /api/shots/{id}/refs 与 preview / apply 读写同一份来源：
    镜头 / 场景范围 → <run>/assets/shot_looks.json 的 overrides {sid: {cid: {look, parts}}}、scene_overrides {sid: 底图 | "none"}
    整集范围（只接受 by=owner）→ data/looks/hub_episode_looks.json（资产中心排期，整集 > 逐镜，优先级不变）
返回结构与旧接口相同（RefBar / RefSwitchPanel 不用改，G10 不回退）。每次写入记 shot_looks.json switch_log。
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import HTTPException

from ns_agent import asset_refs as AR
from ns_render import pipeline as P

ROOT = P.ROOT
SLOTS = ("outfit", "shoes", "makeup", "nails", "hair", "accessory")


def project_of(script) -> str | None:
    from ns_render import unified_frame as UF
    return UF.project_for(script)


def _reg_path(project: str) -> Path:
    return ROOT / (AR.project_cfg(project).get("shot_looks_file") or "data/shot_looks.json")


def _load(project: str) -> dict:
    try:
        return json.loads(_reg_path(project).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(project: str, d: dict) -> None:
    p = _reg_path(project)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


def _thumb(rel: str | None) -> str | None:
    from ns_api import assets as A
    return A.file_url(rel) if rel else None


def _find(script, shot_id: str):
    try:
        return P.find_shot(script, shot_id)
    except KeyError as e:
        raise HTTPException(404, f"没有镜头 {shot_id}") from e


def _cid(name: str) -> str:
    return AR.NAME_ID.get(name, name)


def _plate_id(f: str) -> str:
    """底图 → plate_id：V1 assets/scenes 下 = 相对 assets/scenes；资产包（assets_v2/…，本剧清单登记）= 原路径（V2CUT-O）"""
    p = Path(f).as_posix()
    return p[len("assets/scenes/"):] if p.startswith("assets/scenes/") else p


def _plate_url(pid: str) -> str | None:
    if pid.startswith("assets_v2/"):
        from ns_api import v2_assets as V2      # 资产包文件只经 /api/v2/asset-file 发（清单外 / 成人类不发）
        return V2._url(pid)
    return _thumb(f"assets/scenes/{pid}")


def view(script, shot_id: str) -> dict:
    project = project_of(script)
    ep, shot = _find(script, shot_id)
    sr, plan = AR.plan_for(project, ep, shot)
    looks = AR.load_looks(project)
    wd = AR.wardrobe()
    ovs, scene_ovs = AR.shot_overrides(project)
    chars = []
    for info in sr.characters:
        cid, lid = info["character"], info.get("look")
        L = (looks.get(cid) or {}).get(lid) if lid else None
        row = AR.look_for(ep, info["name"], int(AR.g(shot, "index")))
        ep_default = AR.match_look(looks.get(cid) or {}, AR.g(row, "slots"))[0] if row is not None else None
        eff_parts = {s: None for s in SLOTS}
        parts_all = {s: [] for s in SLOTS}
        for p in (L.parts if L else []):
            if p.item_id and p.slot in parts_all:
                parts_all[p.slot].append(p.item_id)
                eff_parts[p.slot] = eff_parts[p.slot] or p.item_id
        sov = ((ovs.get(shot_id) or {}).get(cid) or {})
        for k, v in (sov.get("parts") or {}).items():
            if v:
                eff_parts[k] = v
        src = {"hub_episode": "episode", "shot_override": "shot"}.get(info.get("look_how") or "", "default")
        chars.append({
            "id": cid, "name": info["name"], "present_source": info.get("presence"),
            "effective": {"look": lid, "look_name": f"造型{lid}" if lid else None, "label": (L.use if L else None),
                          "parts": eff_parts, "parts_all": parts_all,
                          "images": [{"file": s.file, "url": _thumb(s.file), "label": "、".join(s.labels), "kind": s.kind,
                                      "character": s.character, "index": s.index} for s in plan.slots if s.character == cid]},
            "source": src,
            "episode_default": {"look": ep_default, "parts": {}},
            "layers": {"scene": None, "shot": sov or None},
            "options": {
                "looks": [{"id": k, "name": f"造型{k}", "label": v.use, "preview_url": _thumb(AR.sheet_of(project, cid, k)),
                           "episode_default": k == ep_default, "current": k == lid} for k, v in sorted((looks.get(cid) or {}).items())],
                "parts": {s: [{"id": it["id"], "name": it.get("name"), "thumb_url": _thumb(AR.item_image(it["id"])),
                               "current": it["id"] == eff_parts.get(s)}
                              for it in wd.values() if it.get("slot") == s and it.get("character") in (cid, None)] for s in SLOTS},
            },
        })
    from ns_api.ref_switch import plate_options
    sdir, _st = AR.scene_dir(AR.g(shot, "scene_id")) if AR.g(shot, "scene_id") else (None, "")
    scene_file = next((s.file for s in plan.slots if s.kind == "scene"), None) or \
        next((d["file"] for d in plan.dropped if d.get("role") == "scene"), None)
    sov = scene_ovs.get(shot_id)
    eff = "none" if sov == "none" else (sov or (_plate_id(scene_file) if scene_file else None))
    return {"shot_id": shot_id, "episode": int(AR.g(ep, "number")), "scene_id": AR.g(shot, "scene_id"),
            "characters": chars,
            "scene": {"effective": {"plate_id": eff, "url": None if eff in (None, "none") else _plate_url(eff),
                                    "source": "shot" if sov else "default", "default_plate": scene_file},
                      "options": plate_options(sdir)},
            "ref_group": {"files": plan.files, "count": len(plan.files), "limit": plan.capacity},
            "asset_refs": AR.record(sr, plan), "source_of_truth": "asset_refs（shot_looks.json / hub_episode_looks.json）"}


def _scope_shots(script, shot_id: str, scope: str) -> tuple[int, list[str]]:
    ep, shot = _find(script, shot_id)
    n = int(AR.g(ep, "number"))
    if scope == "shot":
        return n, [shot_id]
    if scope == "episode":
        return n, [s.id for s in ep.shots]
    scene = AR.g(shot, "scene_id")
    return n, [s.id for s in ep.shots if AR.g(s, "scene_id") == scene]


def _validate(project: str, chars: dict, scene: str | None) -> None:
    looks = AR.load_looks(project)
    wd = AR.wardrobe()
    for cid, ch in chars.items():
        if ch.look and ch.look not in (looks.get(cid) or {}):
            raise HTTPException(422, f"{AR.ID_NAME.get(cid, cid)} 没有造型 {ch.look}（只能选已登记造型）")
        for k, v in (ch.parts or {}).items():
            if k not in SLOTS:
                raise HTTPException(422, f"parts 只能是 {SLOTS}")
            if v and v not in wd:
                raise HTTPException(422, f"衣橱里没有单品 {v}")
    if scene not in (None, "none", "inherit") and not (ROOT / "assets" / "scenes" / scene).is_file():
        raise HTTPException(422, f"没有这张场景底图：{scene}")


def _chars(change) -> dict:
    out = {}
    for k, v in (change.characters or {}).items():
        out[_cid(k) if k in AR.NAME_ID else k] = v
    return out


def preview(script, shot_id: str, body) -> dict:
    project = project_of(script)
    chars = _chars(body.change)
    _validate(project, chars, body.change.scene)
    n, shots = _scope_shots(script, shot_id, body.scope)
    stale = [s for s in shots if (P.shot_dir(s) / "takes.json").exists()]
    return {"scope": body.scope, "episode": n, "affected": shots, "stale": stale, "continuity_warnings": [],
            "writes_to": "data/looks/hub_episode_looks.json" if body.scope == "episode" else AR.rel(_reg_path(project))}


def apply(script, shot_id: str, body) -> dict:
    project = project_of(script)
    if body.scope == "episode" and body.by != "owner":
        raise HTTPException(403, "改集默认（scope=episode）只接受项目方本人（by=owner）；只改这一镜 / 这一场请用 scope=shot / scene")
    if body.change.copy_from:
        src = view(script, body.change.copy_from)
        from ns_api.ref_switch import CharChange, RefChange
        body.change = RefChange(characters={c["id"]: CharChange(look=c["effective"]["look"],
                                                                 parts={k: v for k, v in c["effective"]["parts"].items() if v})
                                            for c in src["characters"]},
                                scene=src["scene"]["effective"]["plate_id"])
    out = preview(script, shot_id, body)
    chars = _chars(body.change)
    n, shots = out["episode"], out["affected"]
    if body.scope == "episode":
        p = AR.HUB_EP_LOOKS
        try:
            hub = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            hub = {}
        pj = hub.setdefault(project, {})
        for cid, ch in chars.items():
            if ch.reset:
                pj.setdefault(cid, {}).pop(str(n), None)
            elif ch.look:
                pj.setdefault(cid, {})[str(n)] = ch.look
        pj["_by"], pj["_at"] = body.by, time.strftime("%Y-%m-%dT%H:%M:%S")
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(hub, ensure_ascii=False, indent=1), encoding="utf-8")
    d = _load(project)
    ovs = d.setdefault("overrides", {})
    sovs = d.setdefault("scene_overrides", {})
    for sid in shots:
        if body.change.reset:
            ovs.pop(sid, None)
            sovs.pop(sid, None)
            continue
        for cid, ch in chars.items():
            cur = ovs.setdefault(sid, {}).setdefault(cid, {})
            if ch.reset:
                ovs[sid].pop(cid, None)
                continue
            if ch.look and body.scope != "episode":
                cur["look"] = ch.look
                if not ch.parts:
                    cur.pop("parts", None)                 # 给了造型没给单件 = 整套换掉
            for k, v in (ch.parts or {}).items():
                if v is None:
                    cur.setdefault("parts", {}).pop(k, None)
                else:
                    cur.setdefault("parts", {})[k] = v
            if not cur:
                ovs[sid].pop(cid, None)
        if sid in ovs and not ovs[sid]:
            ovs.pop(sid)
        sc = body.change.scene
        if sc == "inherit":
            sovs.pop(sid, None)
        elif sc:
            sovs[sid] = sc
    d.setdefault("switch_log", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "by": body.by or "canvas", "scope": body.scope,
                                           "shot": shot_id, "affected": shots, "change": body.change.model_dump(exclude_none=True),
                                           "note": getattr(body, "note", None)})
    _save(project, d)
    out.update(applied=True, note=getattr(body, "note", None))
    return out
