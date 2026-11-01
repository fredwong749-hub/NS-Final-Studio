"""
造型（衣橱）API。数据在 data/looks/*.json，逻辑见 ns_agent.looks。只读写 JSON，从不触发渲染；
所有修改接口都返回 affected_count / affected_shots（解析结果哈希变化的镜头）。

{character} 接受 slug（lin_wan）或中文名（林晚）。
LookPatch 的写入语义：body 里出现的字段覆盖（显式 null 清空），没出现的字段保留；slots 整体替换。
"""

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel

from ns_agent.looks import ROOT, LookStore, default_store, resolve_character
from ns_schema.looks import (CHARACTERS, SLOTS, AdornmentState, AffectedShots, Look, LookPatch, LookPrompt,
                             LookSchedule, ShotLooks, Wardrobe, WardrobeItem)

router = APIRouter(tags=["looks"])
REF_ROOTS = (ROOT / "assets", ROOT / "data" / "looks")


def get_store() -> LookStore:
    return default_store()


def _call(fn, *a):
    try:
        return fn(*a)
    except KeyError as e:
        raise HTTPException(404, str(e.args[0]) if e.args else "not found")
    except ValueError as e:
        raise HTTPException(422, str(e))


def _char(c: str) -> str:
    return _call(resolve_character, c)


def ref_url(ref: str) -> str | None:
    """参考图 → URL；REF-xx 这类注册表 id 还没有文件，返回 None"""
    p = (ROOT / ref).resolve()
    if any(p.is_relative_to(r.resolve()) for r in REF_ROOTS) and p.is_file():
        return f"/api/looks/ref-image?path={ref}"
    return None


# ---------------------------------------------------------------- catalog / wardrobe

@router.get("/api/looks")
def get_catalog(store: LookStore = Depends(get_store)):
    """角色、插槽、单品（带参考图 URL）、命名造型、D 状态目录"""
    w, b, s = store.wardrobe(), store.lookbook(), store.schedule()
    return {
        "characters": [{"id": c, "name": n, "default_look_id": s.character_defaults.get(c)}
                       for c, n in CHARACTERS.items()],
        "slots": list(SLOTS),
        "items": [{**i.model_dump(), "reference_urls": [ref_url(r) for r in i.reference_images]} for i in w.items],
        "looks": [{**lk.model_dump(), "reference_urls": [ref_url(r) for r in lk.reference_images]} for lk in b.looks],
        "decor_states": [d.model_dump() for d in w.decor_states],
    }


@router.get("/api/looks/ref-image")
def get_ref_image(path: str):
    p = (ROOT / path).resolve()
    if not any(p.is_relative_to(r.resolve()) for r in REF_ROOTS) or not p.is_file():
        raise HTTPException(404, "not found")
    return FileResponse(p)


@router.get("/api/looks/wardrobe", response_model=Wardrobe)
def get_wardrobe(store: LookStore = Depends(get_store)):
    return store.wardrobe()


@router.post("/api/looks/wardrobe/items", response_model=AffectedShots, status_code=201)
def create_item(item: WardrobeItem, store: LookStore = Depends(get_store)):
    if any(i.id == item.id for i in store.wardrobe().items):
        raise HTTPException(409, f"item exists: {item.id}")
    return _call(store.upsert_item, item)


@router.put("/api/looks/wardrobe/items/{item_id}", response_model=AffectedShots)
def put_item(item_id: str, item: WardrobeItem, store: LookStore = Depends(get_store)):
    item.id = item_id
    return _call(store.upsert_item, item)


@router.put("/api/looks/wardrobe/decor/{state_id}", response_model=AffectedShots)
def put_decor_state(state_id: str, state: AdornmentState, store: LookStore = Depends(get_store)):
    state.id = state_id
    return _call(store.upsert_decor_state, state)


# ---------------------------------------------------------------- named looks

@router.get("/api/looks/looks", response_model=list[Look])
def list_looks(character: str | None = None, store: LookStore = Depends(get_store)):
    looks = store.lookbook().looks
    return [lk for lk in looks if lk.character == _char(character)] if character else looks


@router.get("/api/looks/looks/{look_id}", response_model=Look)
def get_look(look_id: str, store: LookStore = Depends(get_store)):
    lk = store.get_look(look_id)
    if not lk:
        raise HTTPException(404, f"unknown look: {look_id}")
    return lk


@router.put("/api/looks/looks/{look_id}", response_model=AffectedShots)
def put_look(look_id: str, look: Look, store: LookStore = Depends(get_store)):
    look.id = look_id
    return _call(store.upsert_look, look)


class DefaultLook(BaseModel):
    look_id: str


@router.put("/api/looks/characters/{character}/default", response_model=AffectedShots)
def put_character_default(character: str, body: DefaultLook, store: LookStore = Depends(get_store)):
    return _call(store.set_character_default, _char(character), body.look_id)


# ---------------------------------------------------------------- schedule

@router.get("/api/look-schedule", response_model=LookSchedule)
def get_schedule(store: LookStore = Depends(get_store)):
    return store.schedule()


class ScheduleReplace(BaseModel):
    character_defaults: dict[str, str] | None = None
    episodes: dict[str, dict[str, LookPatch]] | None = None


@router.put("/api/look-schedule", response_model=AffectedShots)
def put_schedule(body: ScheduleReplace, store: LookStore = Depends(get_store)):
    """整体替换 character_defaults 和/或 episodes（给出的部分）。本镜覆盖走 /api/looks/shots。"""
    return _call(store.replace_schedule, body.character_defaults, body.episodes)


class RangePatch(BaseModel):
    episodes: str            # "1-8, 17"；写错就 422，不猜
    patch: LookPatch | None = None   # None = 删除这些集的计划（恢复默认）


@router.put("/api/looks/episodes-range/{character}", response_model=AffectedShots)
def put_episode_range(character: str, body: RangePatch, store: LookStore = Depends(get_store)):
    return _call(store.patch_episodes, body.episodes, _char(character), body.patch)


# ---------------------------------------------------------------- episodes / shots

def _cast_name(cid: str) -> str:
    """旧角色表里没有的人（例：阿岚 ch_a_lan）→ 出图资产表的中文名"""
    try:
        from ns_agent.asset_refs import ID_NAME
        return ID_NAME.get(cid, cid)
    except Exception:  # noqa: BLE001
        return cid


@router.get("/api/looks/episodes/{n}")
def get_episode(n: int, store: LookStore = Depends(get_store)):
    ep = _call(store.episode, n)
    res = store.resolver()
    sched = store.schedule()
    shots = [res.shot_looks(s) for s in ep.shots]
    chars = list(dict.fromkeys([c for sl in shots for c in (r.character for r in sl.characters)]
                               + list(sched.episodes.get(str(n), {}))))
    # DATAALIGN（K-UI-D01）：登记了资产的剧（series10）本集要确认造型的人物 = 剧本 **人物** 行里在画 / 局部的人
    # （与出图同口径）；旧口径是正文关键词猜（ep05 曾多出顾沉、漏掉阿岚）。确认记录仍是 schedule 的 owner_confirmed_*
    try:
        from ns_api.shot_cast import episode_cast_ids
        ec = episode_cast_ids()
    except Exception:  # noqa: BLE001
        ec = None
    if ec is not None and n in ec:
        chars = list(ec[n])
    plan = sched.episodes.get(str(n), {})
    return {
        "episode": n, "title": ep.title,
        "characters": {
            c: {"name": CHARACTERS.get(c) or _cast_name(c), "default_look_id": sched.character_defaults.get(c),
                "plan": plan[c].model_dump() if c in plan else None,
                "resolved": res.core(c, n).model_dump()}      # 集层解析（不含本镜覆盖）
            for c in chars
        },
        "shots": [
            {"shot_id": sl.shot_id, "index": sl.index, "look_hash": sl.look_hash,
             "characters": {r.character: {"label": r.label, "look_id": r.look_id, "hash": r.hash,
                                          "has_override": r.has_override, "changed_from_prev": r.changed_from_prev,
                                          "changed_fields": r.changed_fields,
                                          "conflicts": [x.model_dump() for x in r.conflicts
                                                        if x.severity != "info"]}
                            for r in sl.characters}}
            for sl in shots
        ],
    }


@router.put("/api/looks/episodes/{n}/{character}", response_model=AffectedShots)
def put_episode_look(n: int, character: str, body: LookPatch, store: LookStore = Depends(get_store)):
    return _call(store.patch_episode, n, _char(character), body)


@router.delete("/api/looks/episodes/{n}/{character}", response_model=AffectedShots)
def delete_episode_look(n: int, character: str, store: LookStore = Depends(get_store)):
    return _call(store.patch_episode, n, _char(character), None)


@router.get("/api/looks/shots/{shot_id}", response_model=ShotLooks)
def get_shot(shot_id: str, store: LookStore = Depends(get_store)):
    return _call(store.shot_looks, shot_id)


@router.get("/api/looks/shots/{shot_id}/prompt", response_model=LookPrompt)
def get_shot_prompt(shot_id: str, store: LookStore = Depends(get_store)):
    return _call(store.look_prompt, shot_id)


@router.put("/api/looks/shots/{shot_id}/{character}", response_model=AffectedShots)
def put_shot_override(shot_id: str, character: str, body: LookPatch, store: LookStore = Depends(get_store)):
    return _call(store.patch_shot, shot_id, _char(character), body)


@router.delete("/api/looks/shots/{shot_id}/{character}", response_model=AffectedShots)
def delete_shot_override(shot_id: str, character: str, store: LookStore = Depends(get_store)):
    return _call(store.patch_shot, shot_id, _char(character), None)
