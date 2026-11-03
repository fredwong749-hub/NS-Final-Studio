"""
本镜参考切换（docs/api_v1_contract.md §E 前半，canvas-ui-spec-v3 §6；fredw-92/W5）。

    GET  /api/shots/{id}/refs            每个出场人物当前生效的整套形象 / 单件 / 参考图 + 来源层 + 可选项；场景底图
    POST /api/shots/{id}/refs/preview    {scope, change} → 影响面：affected / stale / continuity_warnings（不写任何东西）
    POST /api/shots/{id}/refs/apply      同 body + {rerender_first?, by?}；scope=episode 必须 by=owner（改集默认 = 造型确认失效）

三层继承：集默认（data/looks 默认 → 集计划，项目方确认 look_confirmed）→ 场景（episode_edit.json scene_overrides）
→ 镜头（edits.json ref_overrides）。只记录与下一层不同的部分；只能选已有资产（造型 / 衣橱单品 / 场景底图）。
change 结构：
    {characters: {<人物 slug 或中文名>: {look?: look_id, parts?: {outfit|shoes|makeup|nails|hair|accessory: 单品 id | null},
                                         reset?: bool}},
     scene?: plate_id（assets/scenes 下相对路径）| "none"（不用底图）| "inherit"（恢复下一层）,
     reset?: bool（清空这一层 = 恢复下一层；镜头 / 场景范围），
     copy_from?: shot_id（借用另一镜当前生效的整套参考）}
parts 里的 null = 这一件恢复继承；给了 look 而没给 parts = 整套换掉（这一层原来的单件清空）。
不做内容检测；参考与 LoRA 调度仍归渲染器，这里只记录“选了哪个已有资产”。
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ns_agent import ref_overrides as RO
from ns_agent.looks import LookStore, Resolver, resolve_character
from ns_api.looks import get_store
from ns_render import pipeline as P
from ns_schema.edits import PART_SLOTS, CharRefOverride, RefOverrides
from ns_schema.looks import CHARACTERS, LookPatch

router = APIRouter(tags=["refs"])
IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def project_root() -> Path:
    return P.ROOT


# ---------------------------------------------------------------- 请求体

class CharChange(BaseModel):
    look: str | None = None
    parts: dict[str, str | None] = Field(default_factory=dict)
    reset: bool = False


class RefChange(BaseModel):
    characters: dict[str, CharChange] = Field(default_factory=dict)
    scene: str | None = None
    reset: bool = False
    copy_from: str | None = None


class RefsBody(BaseModel):
    scope: Literal["shot", "scene", "episode"]
    change: RefChange = Field(default_factory=RefChange)
    rerender_first: bool = False     # 前端“应用并重出首帧”传 true；默认只应用
    by: str | None = None            # scope=episode 必须 "owner"
    note: str = ""                   # 项目方原话（可选，记在返回里）


# ---------------------------------------------------------------- 读

def _shot(store: LookStore, shot_id: str):
    try:
        return store.shot(shot_id)
    except (KeyError, ValueError) as e:
        raise HTTPException(404, f"没有这个镜头：{shot_id}") from e


def _legacy() -> bool:
    """当前剧是 V1（或没有 runs.json 的临时根）"""
    from ns_agent import run_paths as _RPA
    try:
        return _RPA.is_legacy_run(project_root())
    except Exception:  # noqa: BLE001  # arch-ok: 认不出当前剧 = 按非 V1 处理（更严）
        return False


def _run_script():
    """当前剧的导入稿（ns_agent.run_paths 唯一入口）；没有 / 读不了 → None（不回退 V1 的 data/import/script_v2.json）"""
    from ns_agent import run_paths as _RPA
    from ns_schema.script import ScriptImport
    try:
        f = _RPA.script_json(project_root())
        return ScriptImport.model_validate_json(f.read_text(encoding="utf-8")) if f.is_file() else None
    except Exception as e:  # noqa: BLE001 —— 读不了 / 校验不过 = None（调用方按“本剧没有登记场景”处理），如实记下
        print(f"[ref_switch] 当前剧导入稿读不了：{e} → 按无导入稿", file=sys.stderr)
        return None


def run_scene_registry(script=None) -> dict[str, str | None]:
    """V2CUT-O 11-03（L-126）：非 V1 剧本剧登记过的场景 → 登记的底图（资产包清单 scenes.<id>.base；没登记底图 = None）。
    登记 = 本剧导入稿的 scene_library 或本剧资产包清单 scenes；V1 的 assets/scenes 目录 / data/scenes.json 一律不算"""
    from ns_api import run_paths as _RP
    script = script if script is not None else _run_script()
    reg: dict[str, str | None] = {e.scene_id: None for e in (getattr(getattr(script, "globals", None), "scene_library", None) or [])}
    for sid, sc in ((_RP.manifest(project_root()) or {}).get("scenes") or {}).items():
        base = sc.get("base") if isinstance(sc, dict) else None
        f = (base.get("file") if isinstance(base, dict) else base) or None
        reg[sid] = f if f and (project_root() / f).is_file() else None
    return reg


def scene_map(res: Resolver) -> dict[str, str]:
    """shot_id → scene_id（与 state_timeline / Resolver.scene_of 同一口径）。
    V2CUT-O：非 V1 剧只认当前剧导入稿每镜写明的 **场景**，且该场景本剧登记过；没登记 = 不返回（不按镜号借 V1 的分组）"""
    if not _legacy():
        script = _run_script()
        reg = run_scene_registry(script)
        return {s.id: s.scene_id for e in (script.episodes if script else []) for s in e.shots
                if getattr(s, "scene_id", None) and s.scene_id in reg}
    from ns_agent.state_timeline import group_scenes
    return {r["shot_id"]: r["scene_id"] for r in group_scenes(res.script, lambda s: {c for c, _ in res.characters(s)})}


def _canvas(res: Resolver) -> RO.Canvas:
    return res.canvas or RO.Canvas()


def _thumb(rel: str | None) -> str | None:
    from ns_api import assets as A
    return A.file_url(rel) if rel else None


def plate_options(scene_id: str | None) -> list[dict]:
    """本场景的底图候选（assets/scenes/<scene_id>/ 下的图片）+ “不用底图”。
    V2CUT-O：非 V1 剧只列本剧登记的那一张底图（没登记 = 只有“不用底图”）"""
    base = project_root() / "assets" / "scenes"
    out = []
    if not _legacy():
        f = run_scene_registry().get(scene_id) if scene_id else None
        if f:
            from ns_api import v2_assets as V2      # 资产包文件只经 /api/v2/asset-file 发
            out.append({"plate_id": f, "scene_id": scene_id, "name": Path(f).stem, "url": V2._url(f) if f.startswith("assets_v2/") else _thumb(f)})
    elif scene_id and (base / scene_id).is_dir():
        for p in sorted((base / scene_id).iterdir()):
            if p.is_file() and p.suffix.lower() in IMAGE_EXT and "_face_" not in p.stem:
                rel = p.relative_to(base).as_posix()
                out.append({"plate_id": rel, "scene_id": scene_id, "name": p.stem,
                            "url": _thumb(f"assets/scenes/{rel}")})
    out.append({"plate_id": "none", "scene_id": scene_id, "name": "不用底图", "url": None})
    return out


def _default_plate(scene_id: str | None) -> str | None:
    if not scene_id:
        return None
    if not _legacy():                       # V2CUT-O：非 V1 剧只认本剧登记的底图，不看 V1 的 assets/scenes/<id>/
        return run_scene_registry().get(scene_id)
    from ns_agent.state_timeline import plate_info
    info = plate_info(project_root(), scene_id)
    return info["plate"] if info.get("plate_sha256") else None


def _first_parts(r) -> dict[str, str | None]:
    return {s: (r.slots[s].items[0] if s in r.slots and r.slots[s].items else None) for s in PART_SLOTS}


def _char_source(canvas: RO.Canvas, ep: int, scene_id: str | None, shot_id: str, char: str) -> str:
    sh, sc = canvas.shot(shot_id), canvas.scene(ep, scene_id)
    if sh and char in sh.characters and not sh.characters[char].is_empty():
        return "shot"
    if sc and char in sc.characters and not sc.characters[char].is_empty():
        return "scene"
    return "episode"


def shot_refs_view(store: LookStore, shot_id: str) -> dict:
    from ns_api import assets as A
    shot = _shot(store, shot_id)
    res = store.resolver()
    smap = scene_map(res)
    scene_id = smap.get(shot_id)
    canvas = _canvas(res)
    idx = A.AssetIndex(store)
    group = A.shot_refs(store, shot_id, idx)
    book = store.lookbook()
    items = store.wardrobe().items
    chars = []
    for c, src in res.characters(shot):
        r = res.core(c, shot.episode, shot_id, src)
        ep_default = res.core(c, shot.episode)
        looks = [{"id": lk.id, "name": lk.name, "label": lk.label, "preview_url": _thumb(lk.preview_image),
                  "episode_default": lk.id == ep_default.look_id, "current": lk.id == r.look_id}
                 for lk in book.looks if lk.character == c]
        parts = {s: [{"id": it.id, "name": it.name, "thumb_url": idx.item_thumb(it.id),
                      "current": it.id in (r.slots[s].items if s in r.slots else [])}
                     for it in items if it.slot == s and it.character in (c, None)] for s in PART_SLOTS}
        chars.append({
            "id": c, "name": CHARACTERS.get(c, c), "present_source": src,
            "effective": {"look": r.look_id, "look_name": r.look_name, "label": r.label, "parts": _first_parts(r),
                          "parts_all": {s: v.items for s, v in r.slots.items()},
                          "images": [x for x in group["refs"] if x["character"] == c and x.get("file")]},
            "source": _char_source(canvas, shot.episode, scene_id, shot_id, c),
            "episode_default": {"look": ep_default.look_id, "parts": _first_parts(ep_default)},
            "layers": {"scene": (canvas.scene(shot.episode, scene_id).characters.get(c).model_dump()
                                 if canvas.scene(shot.episode, scene_id)
                                 and c in canvas.scene(shot.episode, scene_id).characters else None),
                       "shot": (canvas.shot(shot_id).characters[c].model_dump()
                                if canvas.shot(shot_id) and c in canvas.shot(shot_id).characters else None)},
            "options": {"looks": looks, "parts": parts},
        })
    plate, psrc = RO.effective_scene(canvas, shot.episode, scene_id, shot_id)
    default_plate = _default_plate(scene_id)
    v2url = lambda p: __import__("ns_api.v2_assets", fromlist=["_url"])._url(p)   # noqa: E731
    eff = plate or (default_plate if not _legacy() else
                    default_plate and Path(default_plate).relative_to("assets/scenes").as_posix())
    return {
        "shot_id": shot_id, "episode": shot.episode, "scene_id": scene_id,
        "characters": chars,
        "scene": {"effective": {"plate_id": eff, "url": None if eff in (None, "none") else
                                (v2url(eff) if str(eff).startswith("assets_v2/") else _thumb(f"assets/scenes/{eff}")),
                                "source": psrc, "default_plate": default_plate},
                  "options": plate_options(scene_id)},
        "ref_group": {"files": group["files"], "count": group["count"], "limit": group["limit"]},
    }


def _asset_script():
    """资产项目（series10 等）→ 当前系统剧本；否则 None（走旧造型库）。DATA_MAP §6-1：切换必须写进出图实际读的来源"""
    try:
        from ns_api import ref_switch_assets as RA
        from ns_schema.script import ScriptImport
        from ns_agent import run_paths as _RPA
        # V2CUT-O 11-03：当前剧的导入稿（V2 = data/import/runs/<run>/script_v2.json）；以前写死 V1 的 data/import/script_v2.json，
        # V2 镜头拿到的是 V1 剧本的 sk_office_night / 林晚。测试的临时项目没有 runs.json → <data>/import/script_v2.json（旧行为）
        f = _RPA.script_json(P.DATA.parent)
        if not f.exists():
            return None
        script = ScriptImport.model_validate_json(f.read_text(encoding="utf-8"))
        return script if RA.project_of(script) else None
    except Exception:  # noqa: BLE001
        return None


@router.get("/api/shots/{shot_id}/refs")
def get_shot_refs(shot_id: str, store: LookStore = Depends(get_store)):
    script = _asset_script()
    if script is not None:
        from ns_api import ref_switch_assets as RA
        return RA.view(script, shot_id)
    return shot_refs_view(store, shot_id)


# ---------------------------------------------------------------- 变更：校验 + 模拟

def _norm_chars(change: RefChange) -> dict[str, CharChange]:
    out = {}
    for k, v in change.characters.items():
        try:
            out[resolve_character(k)] = v
        except (KeyError, ValueError) as e:
            raise HTTPException(422, f"未知人物：{k}") from e
    return out


def copy_change(store: LookStore, res: Resolver, src_shot: str) -> RefChange:
    """“用 S3 的设置”：另一镜当前生效的整套形象 + 单件 + 底图"""
    s = _shot(store, src_shot)
    smap = scene_map(res)
    chars = {}
    for c, src in res.characters(s):
        r = res.core(c, s.episode, src_shot, src)
        chars[c] = CharChange(look=r.look_id, parts={k: v for k, v in _first_parts(r).items() if v})
    plate, _ = RO.effective_scene(_canvas(res), s.episode, smap.get(src_shot), src_shot)
    return RefChange(characters=chars, scene=plate)


def validate_change(store: LookStore, chars: dict[str, CharChange], scene: str | None) -> None:
    """只能选已有资产：造型属于该人物；单品存在、槽位对、属于该人物或通用；底图存在"""
    book = {lk.id: lk for lk in store.lookbook().looks}
    items = {i.id: i for i in store.wardrobe().items}
    for c, cc in chars.items():
        if cc.look:
            lk = book.get(cc.look)
            if not lk:
                raise HTTPException(422, f"没有这个造型：{cc.look}（只能选已有资产，新资产请到资产页生成 / 上传）")
            if lk.character != c:
                raise HTTPException(422, f"造型 {cc.look} 属于 {lk.character}，不是 {c}")
        for slot, iid in cc.parts.items():
            if slot not in PART_SLOTS:
                raise HTTPException(422, f"单件只能是 {PART_SLOTS}，收到 {slot}")
            if iid is None:
                continue
            it = items.get(iid)
            if not it:
                raise HTTPException(422, f"没有这个资产：{iid}（只能选已有资产，新资产请到资产页生成 / 上传）")
            if it.slot != slot:
                raise HTTPException(422, f"{iid} 是 {it.slot}，不能放到 {slot}")
            if it.character not in (None, c):
                raise HTTPException(422, f"{iid} 属于 {it.character}，不是 {c}")
    if scene and scene not in ("none", "inherit") and RO.plate_path(project_root(), scene) is None:
        raise HTTPException(422, f"没有这个场景底图：{scene}（assets/scenes 下的相对路径，或 none / inherit）")


def apply_layer(old: RefOverrides | None, chars: dict[str, CharChange], scene: str | None,
                reset: bool) -> RefOverrides:
    new = RefOverrides() if reset or old is None else old.model_copy(deep=True)
    for c, cc in chars.items():
        cur = CharRefOverride() if cc.reset else (new.characters.get(c) or CharRefOverride()).model_copy(deep=True)
        if "look" in cc.model_fields_set:
            cur.look = cc.look or None
            if cc.look and "parts" not in cc.model_fields_set:
                cur.parts = {}               # 整套换掉：这一层原来的单件清空
        for slot, iid in cc.parts.items():
            if iid:
                cur.parts[slot] = iid
            else:
                cur.parts.pop(slot, None)
        if cur.is_empty():
            new.characters.pop(c, None)
        else:
            new.characters[c] = cur
    if scene:
        new.scene = None if scene == "inherit" else scene
    return new


def _prune(res_lower: Resolver, layer: RefOverrides, ep: int, probe_shot: str | None) -> RefOverrides:
    """每一层只记录与下一层不同的部分：与下一层解析结果相同的 look / 单件去掉"""
    out = layer.model_copy(deep=True)
    for c, co in list(out.characters.items()):
        r = res_lower.core(c, ep, probe_shot)
        if co.look and co.look == r.look_id and not co.parts:
            co.look = None
        for slot, iid in list(co.parts.items()):
            if not co.look and slot in r.slots and r.slots[slot].items == [iid]:
                co.parts.pop(slot)
        if co.is_empty():
            out.characters.pop(c)
    return out


def _clone_canvas(cv: RO.Canvas) -> RO.Canvas:
    return RO.Canvas({"shots": dict(cv.shots), "scenes": {k: dict(v) for k, v in cv.scenes.items()}})


class Plan:
    """一次变更的模拟结果：新的画布 / 新的集计划 + 前后两个解析器"""

    def __init__(self, store: LookStore, shot_id: str, body: RefsBody):
        self.store, self.shot_id, self.body = store, shot_id, body
        self.shot = _shot(store, shot_id)
        self.ep = self.shot.episode
        self.before = store.resolver()
        self.smap = scene_map(self.before)
        self.scene_id = self.smap.get(shot_id)
        change = body.change
        if change.copy_from:
            borrowed = copy_change(store, self.before, change.copy_from)
            borrowed.characters.update(change.characters)
            change = RefChange(characters=borrowed.characters, scene=change.scene or borrowed.scene,
                               reset=change.reset)
        self.chars = _norm_chars(change)
        self.scene_change = change.scene
        self.reset = change.reset
        validate_change(store, self.chars, self.scene_change)
        cv = _clone_canvas(_canvas(self.before))
        self.canvas_after = cv
        self.schedule_after = store.schedule()
        self.episode_patches: dict[str, LookPatch] = {}
        if body.scope == "shot":
            lower = Resolver(self.before.script, store.wardrobe(), store.lookbook(), self.schedule_after,
                             self._without_shot(cv, shot_id))
            layer = apply_layer(cv.shot(shot_id), self.chars, self.scene_change, self.reset)
            self.layer = _prune(lower, layer, self.ep, shot_id)
            cv.shots[shot_id] = self.layer
        elif body.scope == "scene":
            if not self.scene_id:
                raise HTTPException(409, f"{shot_id} 没有场景分组，不能按场景改")
            lower = Resolver(self.before.script, store.wardrobe(), store.lookbook(), self.schedule_after, None)
            layer = apply_layer(cv.scene(self.ep, self.scene_id), self.chars, self.scene_change, self.reset)
            self.layer = _prune(lower, layer, self.ep, None)
            cv.scenes.setdefault(str(self.ep), {})[self.scene_id] = self.layer
        else:
            if self.reset or any(cc.reset for cc in self.chars.values()):
                raise HTTPException(422, "集默认不能清空（恢复集默认请对镜头 / 场景层用 reset）")
            if self.scene_change:
                raise HTTPException(422, "场景底图不能按整集改：请用 scope=scene 或 shot")
            self.layer = None
            for c, cc in self.chars.items():
                old = self.schedule_after.episodes.get(str(self.ep), {}).get(c) or LookPatch()
                look_set = "look" in cc.model_fields_set and bool(cc.look)
                slots = {} if look_set and "parts" not in cc.model_fields_set else dict(old.slots or {})
                for slot, iid in cc.parts.items():
                    if iid:
                        slots[slot] = [iid]
                    else:
                        slots.pop(slot, None)
                kw = {"slots": slots or None}
                if "look" in cc.model_fields_set:
                    kw["look_id"] = cc.look or None
                patch = LookPatch(**kw)
                self.episode_patches[c] = patch
                merged = LookStore._merge(old, patch)
                self.schedule_after.episodes.setdefault(str(self.ep), {})[c] = merged
        self.after = Resolver(self.before.script, store.wardrobe(), store.lookbook(), self.schedule_after, cv)

    @staticmethod
    def _without_shot(cv: RO.Canvas, shot_id: str) -> RO.Canvas:
        c = _clone_canvas(cv)
        c.shots.pop(shot_id, None)
        return c

    def scope_shots(self) -> list:
        shots = [s for s in self.before.shots if s.episode == self.ep]
        if self.body.scope == "shot":
            return [s for s in shots if s.id == self.shot_id]
        if self.body.scope == "scene":
            return [s for s in shots if self.smap.get(s.id) == self.scene_id]
        return shots

    def _sig(self, res: Resolver, s) -> tuple:
        looks = tuple((c, res.core(c, s.episode, s.id, src).hash) for c, src in res.characters(s))
        plate = RO.effective_scene(res.canvas, s.episode, self.smap.get(s.id), s.id)[0]
        return looks, plate

    def affected(self) -> list[str]:
        """本集里解析结果（造型哈希或底图）会变的镜头"""
        return [s.id for s in self.before.shots if s.episode == self.ep
                and self._sig(self.before, s) != self._sig(self.after, s)]

    def continuity(self, affected: list[str]) -> list[dict]:
        """同一场景相邻两镜（同一人物都在镜）造型或底图不同 → 衔接风险（至少一镜在受影响列表里）"""
        out = []
        aff = set(affected)
        shots = [s for s in self.after.shots if s.episode == self.ep]
        for a, b in zip(shots, shots[1:]):
            if self.smap.get(a.id) != self.smap.get(b.id) or not ({a.id, b.id} & aff):
                continue
            ca, cb = dict(self.after.characters(a)), dict(self.after.characters(b))
            for c in [x for x in cb if x in ca]:
                ra, rb = self.after.core(c, a.episode, a.id, ca[c]), self.after.core(c, b.episode, b.id, cb[c])
                fields = [s for s in PART_SLOTS if (ra.slots[s].items if s in ra.slots else [])
                          != (rb.slots[s].items if s in rb.slots else [])]
                if ra.look_id != rb.look_id:
                    fields.insert(0, "look")
                if fields:
                    out.append({"severity": "error", "kind": "look_differs", "shot_id": b.id, "prev_shot_id": a.id,
                                "scene_id": self.smap.get(b.id), "character": c, "fields": fields,
                                "message": f"同一场景 {a.id} → {b.id}：{CHARACTERS.get(c, c)} 的"
                                           f"{'、'.join(fields)} 不同（衔接风险）"})
            pa = RO.effective_scene(self.after.canvas, a.episode, self.smap.get(a.id), a.id)[0]
            pb = RO.effective_scene(self.after.canvas, b.episode, self.smap.get(b.id), b.id)[0]
            if pa != pb:
                out.append({"severity": "error", "kind": "plate_differs", "shot_id": b.id, "prev_shot_id": a.id,
                            "scene_id": self.smap.get(b.id), "character": None, "fields": ["scene"],
                            "message": f"同一场景 {a.id} → {b.id}：底图不同（{pa or '场景默认'} / {pb or '场景默认'}）"})
        return out


def has_takes(shot_id: str) -> bool:
    try:
        return any(t.get("stage") in ("image", "last", "video") for t in P.load_takes(shot_id).get("takes") or [])
    except Exception:  # noqa: BLE001
        return False


def preview(store: LookStore, shot_id: str, body: RefsBody) -> tuple[Plan, dict]:
    plan = Plan(store, shot_id, body)
    affected = plan.affected()
    out = {
        "scope": body.scope, "shot_id": shot_id, "episode": plan.ep, "scene_id": plan.scene_id,
        "scope_shots": [s.id for s in plan.scope_shots()],
        "affected": affected,
        "stale": [s for s in affected if has_takes(s)],
        "continuity_warnings": plan.continuity(affected),
        "layer": plan.layer.model_dump() if plan.layer is not None else None,
        "episode_patches": {c: p.model_dump(include={"look_id", "slots"}) for c, p in plan.episode_patches.items()},
        "requires_owner": body.scope == "episode",
    }
    if body.scope == "episode":
        out["message"] = (f"改第 {plan.ep} 集默认造型 = 改造型确认：需要项目方本人（by=owner），"
                          f"应用后本集 {'、'.join(CHARACTERS.get(c, c) for c in plan.chars)} 的造型确认失效，需重新确认")
    return plan, out


@router.post("/api/shots/{shot_id}/refs/preview")
def post_preview(shot_id: str, body: RefsBody, store: LookStore = Depends(get_store)):
    script = _asset_script()
    if script is not None:
        from ns_api import ref_switch_assets as RA
        return RA.preview(script, shot_id, body)
    return preview(store, shot_id, body)[1]


# ---------------------------------------------------------------- 应用

def _after_write(store: LookStore):
    try:   # 集摘要立即重算（app 已加载时）
        import sys
        app = sys.modules.get("ns_api.app")
        if app is not None and hasattr(app, "_summary_cache"):
            app._summary_cache.invalidate()
    except Exception:  # noqa: BLE001
        pass
    store._changed()   # 项目数据目录 → 后台防抖重建 state_timeline（inputs_sha 随之变）


def _rerender(shot_ids: list[str]) -> list[dict]:
    """“应用并重出首帧”：每镜入一个首帧任务（W2 frame-jobs，mode=regen）；单镜失败不影响应用"""
    out = []
    try:
        from ns_api import frame_jobs as FJ   # W2
    except Exception:  # noqa: BLE001
        FJ = None
    for sid in shot_ids:
        try:
            if FJ is None or not hasattr(FJ, "create_frame_job"):
                raise RuntimeError("出图任务接口（W2 frame-jobs）还没上线，请稍后在镜头上点重出首帧")
            job = FJ.create_frame_job(sid, FJ.FrameJobBody(stage="first", mode="regen"))
            out.append({"shot_id": sid, "ok": True, "job_id": job.get("job_id") or job.get("id")})
        except HTTPException as e:
            out.append({"shot_id": sid, "ok": False, "error": e.detail})
        except Exception as e:  # noqa: BLE001
            out.append({"shot_id": sid, "ok": False, "error": str(e)})
    return out


def apply(store: LookStore, shot_id: str, body: RefsBody) -> dict:
    if body.scope == "episode" and body.by != "owner":
        raise HTTPException(403, "改集默认（scope=episode）等于改造型确认，只接受项目方本人（by=owner）；"
                                 "只改这一镜 / 这一场请用 scope=shot / scene")
    plan, out = preview(store, shot_id, body)
    renders = P.RENDERS
    if body.scope == "shot":
        with P.shot_lock(shot_id):
            e = P.load_edit(shot_id)
            e.ref_overrides = plan.layer
            P.save_edit(shot_id, e)
        RO.set_shot(renders, shot_id, plan.layer)
    elif body.scope == "scene":
        with P.episode_lock(plan.ep):   # fredw-92/B-fix：与 PUT /api/episodes/{n}/edit 同一把每集锁
            ee = P.load_episode_edit(plan.ep)
            if plan.layer.is_empty():
                ee.scene_overrides.pop(plan.scene_id, None)
            else:
                ee.scene_overrides[plan.scene_id] = plan.layer
            P.save_episode_edit(plan.ep, ee)
            RO.set_episode_scenes(renders, plan.ep, ee.scene_overrides)
    else:
        for c, patch in plan.episode_patches.items():
            try:
                store.patch_episode(plan.ep, c, patch)
                store.confirm_episodes(str(plan.ep), c, "", revoke=True)   # 改集默认 → 原造型确认失效
            except (KeyError, ValueError) as e:
                raise HTTPException(422, str(e)) from e
        out["look_confirmed"] = False
        out["message"] = (f"已改第 {plan.ep} 集默认造型；本集 {'、'.join(CHARACTERS.get(c, c) for c in plan.episode_patches)}"
                          f" 的造型确认（look_confirmed）已失效，请项目方重新确认")
    _after_write(store)
    out["applied"] = True
    out["note"] = body.note
    out["rerender"] = _rerender([s for s in out["affected"]] if body.rerender_first else [])
    return out


@router.post("/api/shots/{shot_id}/refs/apply")
def post_apply(shot_id: str, body: RefsBody, store: LookStore = Depends(get_store)):
    script = _asset_script()
    if script is not None:
        from ns_api import ref_switch_assets as RA
        out = RA.apply(script, shot_id, body)
        _after_write(store)
        out["rerender"] = _rerender(list(out["affected"]) if body.rerender_first else [])
        return out
    return apply(store, shot_id, body)
