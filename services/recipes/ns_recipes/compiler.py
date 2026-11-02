"""编译：Shot Spec + 配方（+ 规则表给的参数覆盖）→ RenderPlan（纯函数，同输入同 plan_hash）。

RenderPlan 内容：配方 id / overlay / 配方哈希、模式、帧数、分辨率、种子、提示词全文与静态校验、ComfyUI API 图（图片为占位符）、
输入图（路径 + sha）、道要求、后处理、验收阈值、可走 :8800 API 的请求体（及 API 表达不了的项）、plan_hash。
不含时间戳、不读 GPU / 网络状态。
"""
from __future__ import annotations

import copy
import json
from pathlib import Path
import hashlib

from ns_schema.shot_spec import ShotSpec, frames_for_seconds

from . import COMPILER_VERSION
from . import graph as G
from . import lint as L
from . import prompt as PR
from .registry import Registry, canonical_hash, set_path
from .selector import Selection, select

PLAN_SCHEMA = "nsfs.render_plan/1"
API_BASES = {"official_base": {"steps": 24, "sampler": "euler", "scheduler": "simple", "shift": [12.0, 3.0]}}


class CompileError(Exception):
    pass


def derive_seed(spec: ShotSpec, recipe_id: str, attempt: int, offset: int = 0) -> int:
    h = hashlib.sha256(f"{spec.id}|{spec.spec_hash()}|{recipe_id}|{attempt}|{offset}".encode()).hexdigest()
    return int(h[:8], 16)


def _mode(rc: dict, spec: ShotSpec) -> tuple[str, bool]:
    """→ (提示词 / 图模式, 是否送尾帧)"""
    if rc.get("mode") == "ref2va" or (rc.get("ref2va") or {}).get("enabled"):
        return "ref2va", False
    lfm = (rc.get("keyframes") or {}).get("last_frame_mode", "none")
    use_last = lfm == "use" and "last" in spec.keyframes
    return ("fl2va" if use_last else "i2va"), use_last


def _primary_run() -> str | None:
    """当前主剧 id：统一调 tools/autopilot/runs.py primary_run（K-OPS-F24 唯一入口；测试钉 NS_PRIMARY_RUN 生效），读不到抛异常"""
    import importlib.util as _u
    root = Path(__file__).resolve().parents[3]
    sp = _u.spec_from_file_location("runs_for_recipes", root / "tools" / "autopilot" / "runs.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m.primary_run(root)


def ref_slots(spec: ShotSpec, rc: dict) -> list[dict]:
    slots = []
    r = rc.get("ref2va") or {}
    if r.get("first_frame_slot0"):
        slots.append({"role": "first_frame", "sha": (spec.keyframes.get("first").sha if spec.keyframes.get("first") else None)})
    crops = r.get("identity_crops") or {}
    for c in spec.faces:
        # V2（lab_recipes.md X4）：整张定妆图会把项链 / 粉裙带进画面 → 用脸部裁切。identity_crops 只登记项目方挑定的
        # 身份图（data/assets/identity_refs/manifest.json，by=owner），所以没有 spec.identity_ref 的角色（顾沉 / 陈宇）也可用
        # K-OPS-E29 / AUDIT-M A-01（总调度 11-02 17:1x）：身份脸唯一入口 asset_refs.face_of——配方里写死的旧裁切（L-122 换脸前的
        # face_ref2va）只在 face_of 解不出时兜底，否则 Ref2VA 视频的身份槽还是旧脸（和帧打分口径分叉）
        from ns_agent import asset_refs as _AR
        _pj = r.get("project") or _primary_run()
        _cid = _AR.NAME_ID.get(c.name) or getattr(c, "id", None)
        _cur = _AR.face_of(_pj, _cid) if _cid else None
        if _AR.manifest_rel(_pj):
            # L-126（总调度 11-02 18:5x）：资产包模式的剧（V2）只认清单里的身份脸——没有就不放身份槽（preflight I2 挡住出图），
            # 绝不退回配方裁切 / 剧本 identity_ref（那是 V1 的脸）
            if _cur:
                slots.append({"role": "identity", "character": c.name, "path": _cur, "sha": None})
            continue
        crop = _cur or crops.get(c.name) or crops.get(getattr(c, "id", None) or "")
        if crop:
            slots.append({"role": "identity", "character": c.name, "path": crop, "sha": None,
                          **({"crop_of": c.identity_ref.path} if c.identity_ref else {})})
        elif c.identity_ref:
            slots.append({"role": "identity", "character": c.name, "path": c.identity_ref.path, "sha": c.identity_ref.sha})
    if r.get("look_refs"):
        # VIDEO10 → REFLOCK 审（11-01，契约 I3“Ref2VA 的身份 + 造型参考”）：每个在画露脸角色再给一张本镜造型参考
        # = 该造型设定图正面全身栏去头（asset_refs.sheet_crop front_nohead：脸只由身份图提供）。造型 id 与首帧同源：
        # ① 本镜当前首帧版本 contract.asset_refs.characters[].look；② 没有 → asset_refs.resolve_shot 解出的 look
        # （资产中心排期 > 画布逐镜切换 > 逐镜登记 > 剧本造型行，和出图同一套解析）。解不出 → 记 missing（交 preflight 显示）
        slots += look_slots(spec, r.get("project") or "series10_v1")
    return slots[: int(r.get("max_refs", 9))]


def _first_frame_looks(spec: ShotSpec) -> dict:
    import json
    from .registry import ROOT
    ep, s = spec.id.split("-")
    try:
        d = json.loads((ROOT / "data" / "renders" / ep / s / "takes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    n = (d.get("active") or {}).get("image")
    t = next((t for t in d.get("takes") or [] if t.get("stage") == "image" and t.get("n") == n), None) or {}
    chars = (((t.get("contract") or {}).get("asset_refs") or {}).get("characters")) or []
    return {ch.get("name"): ch.get("look") for ch in chars if ch.get("name") and ch.get("look")}


def look_slots(spec: ShotSpec, project: str) -> list[dict]:
    try:
        from ns_agent import asset_refs as AR
    except ImportError:
        return [{"role": "outfit", "character": c.name, "path": None, "missing": "ns_agent.asset_refs 不可用"} for c in spec.faces]
    by_name, how = _first_frame_looks(spec), "first_frame_contract"
    if not all(c.name in by_name for c in spec.faces):
        try:
            from ns_render import pipeline as P
            si = P.load_script()
            ep = next(e for e in si.episodes if e.number == spec.episode)
            sh = next(x for x in ep.shots if x.index == spec.index)
            sr = AR.resolve_shot(project, ep, sh)
            for ch in sr.characters:
                if ch.get("look") and ch.get("name") not in by_name:
                    by_name[ch["name"]] = ch["look"]
            how = how + "+resolve_shot"
        except Exception:  # noqa: BLE001
            pass
    out = []
    for c in spec.faces:
        cid = getattr(c, "id", None) or ""
        lid = by_name.get(c.name)
        sheet = AR.sheet_of(project, cid, lid) if lid else None
        if not sheet:
            out.append({"role": "outfit", "character": c.name, "path": None, "look": lid, "sheet": None,
                        "missing": "解不出本镜造型" if not lid else f"造型 {lid} 没有已选定的设定图（sheets_chosen.json）"})
            continue
        out.append({"role": "outfit", "character": c.name, "path": AR.sheet_crop(project, sheet, "front_nohead"),
                    "sha": None, "look": lid, "sheet": sheet, "look_source": how})
    return out


def api_request(rc: dict, spec: ShotSpec, mode: str, prompt_text: str, seed: int, w: int, h: int) -> dict:
    """映射到 POST /api/shots/{id}/video-jobs（VideoJobRequest）。API 表达不了的项列进 unsupported。"""
    s = rc["sampling"]
    loras = G.enabled_loras(rc)
    unsupported = []
    body = {"seed": seed, "seconds": float(spec.duration_s), "prompt_override": prompt_text,
            "last_frame_mode": "use" if mode == "fl2va" else "none", "by": "iterate_loop"}
    if "pika_flex" in loras:
        body["base"] = "pika_flex"
        rest = {k: v for k, v in loras.items() if k != "pika_flex"}
    else:
        body["base"] = "official_base"
        ref = API_BASES["official_base"]
        if s["sampler"] != ref["sampler"]:
            unsupported.append(f"sampler={s['sampler']}")
        if s.get("scheduler") != ref["scheduler"]:
            unsupported.append(f"scheduler={s.get('scheduler')}")
        if list(map(float, s["shift"])) != ref["shift"]:
            unsupported.append(f"shift={s['shift']}")
        if int(s["steps"]) != ref["steps"]:
            body["steps"] = int(s["steps"])
        rest = loras
    if rest:
        body["loras"] = [{"name": v["file"], "strength": float(v["strength"])} for _k, v in sorted(rest.items())]
    if mode == "ref2va":
        unsupported.append("mode=ref2va")
    if (rc.get("two_stage") or {}).get("enabled"):
        unsupported.append("two_stage")
    if (w, h) != (768, 1344):
        unsupported.append(f"resolution={w}x{h}")
    if s.get("attention", "pytorch") != "pytorch":
        unsupported.append(f"attention={s['attention']}")
    return {"endpoint": f"/api/shots/{spec.id}/video-jobs", "body": body, "compatible": not unsupported,
            "unsupported": unsupported}


def blocked_swap(registry: Registry, rid: str, overlays: list[str]) -> tuple[str, str | None]:
    """overlay 禁用的配方（例 flush_risk 禁 Pika）被显式指定时（recipe_choice.json / iterate_loop），换成配方自己声明的
    blocked_substitute，并返回原因（写进计划 selection）；没有声明替身 → 原样返回（lint / 选择器照旧处理）。
    WORKFLOW 11-01：series10 默认改 Pika 后，build_jobs 直接按 id 编译、不走选择器，泛红防护靠这里兜住（K-REN-301）"""
    seen = set()
    note = None
    while rid not in seen:
        seen.add(rid)
        by = [o for o in overlays or [] if rid in ((registry.overlays.get(o) or {}).get("block_recipes") or [])]
        sub = (registry.raw.get(rid) or {}).get("blocked_substitute")
        if not by or not sub:
            break
        note = f"{rid} 被 overlay {','.join(by)} 禁用 → 换 {sub}（blocked_substitute）"
        rid = sub
    return rid, note


POLICY_PATH = Path(__file__).resolve().parents[3] / "config" / "pipeline" / "video_policy.json"


def video_policy() -> dict:
    """视频配方政策（config/pipeline/video_policy.json，WORKFLOW）：项目方 11-01 18:0x L-088“视频全部用皮卡来做，皮卡做不了就等”"""
    try:
        return json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def policy_applies(spec) -> bool:
    """政策只管登记的项目（video_policy.scope_source_contains 出现在剧本来源路径里，例 series10_v1）；旧项目 / 测试夹具不受影响"""
    key = video_policy().get("scope_source_contains")
    src = str(getattr(getattr(spec, "source", None), "script_file", "") or "")
    return bool(key) and key in src


def hold_reason(registry: Registry, rid: str, overlays: list[str], spec=None) -> str | None:
    """→ 这一镜这个配方要 hold 的原因（不出片、不回退旧配方）；None = 可以编译。
    ① pika_only：配方不在允许清单 → hold（逐镜写原因）；② 配方被 overlay 禁用且声明 blocked_action: hold（flush_risk 禁 Pika）→ hold"""
    pol = video_policy().get("pika_only") or {}
    if spec is not None and not policy_applies(spec):
        return None
    if pol.get("enabled") and rid not in (pol.get("allowed") or []):
        return pol.get("reason_not_pika", "等 Pika 方案（L-088：视频全部用 Pika）").format(recipe=rid)
    by = [o for o in overlays or [] if rid in ((registry.overlays.get(o) or {}).get("block_recipes") or [])]
    if by and (registry.raw.get(rid) or {}).get("blocked_action") == "hold":
        return (pol.get("reason_overlay") or {}).get(by[0]) or f"等 Pika 方案（被 overlay {','.join(by)} 禁用）"
    return None


def _hold(spec: ShotSpec, rid: str, sel: Selection, why: str) -> dict:
    """hold 计划：字段齐全（graph 为空、status = "hold:<原因>"），下游 build_jobs.compile_variant 原样把状态带进作业，
    vidgen 只派 status ∈ {ready, lint_error} 的变体 → 这一镜等着，不回退旧配方"""
    plan = {"schema": PLAN_SCHEMA, "compiler_version": COMPILER_VERSION, "status": f"hold:{why}",
            "spec": {"id": spec.id, "rev": spec.rev, "hash": spec.spec_hash()},
            "recipe": {"id": rid, "label": None, "status": None, "overlays": list(sel.overlays), "learned": [], "hash": None,
                       "registry_hash": None, "experiment": None},
            "selection": {"chosen": sel.recipe_id, "reasons": sel.reasons + [why], "fallback": [], "features": sel.features},
            "attempt": 0, "overrides": {}, "mode": "hold", "use_last_frame": False, "frames": 0,
            "seconds": float(spec.duration_s), "width": 0, "height": 0, "seed": 0,
            "prompt": {"text": "", "notes": [why], "format": None}, "inputs": {}, "ref_slots": [], "graph": {},
            "lane": {"long": False, "frames": 0}, "acceptance": {}, "lint": [], "reason": why}
    plan["plan_hash"] = plan_hash(plan)
    return plan


def compile_shot(spec: ShotSpec, registry: Registry, *, attempt: int = 1, recipe_id: str | None = None,
                 overrides: dict | None = None, selection: Selection | None = None,
                 allow_experimental: set[str] | None = None) -> dict:
    sel = selection or select(spec, registry, allow=allow_experimental)
    rid = recipe_id or sel.recipe_id
    rid, blocked_note = blocked_swap(registry, rid, sel.overlays)
    why = hold_reason(registry, rid, sel.overlays, spec)
    if why:
        return _hold(spec, rid, sel, why)
    rc = registry.resolve(rid, overlays=sel.overlays, exposure=spec.end_frame.exposure_intent)
    applied = {}
    for path, val in sorted((overrides or {}).items()):
        if path.startswith("seed."):
            continue
        set_path(rc, path, val)
        applied[path] = val
    mode, use_last = _mode(rc, spec)
    frames = frames_for_seconds(spec.duration_s, rc["frames"]["fps"])
    if frames > rc["frames"]["max"]:
        raise CompileError(f"{spec.id} {spec.duration_s}s = {frames} 帧，超过 H3 上限 {rc['frames']['max']}")
    w, h = int(rc["resolution"]["width"]), int(rc["resolution"]["height"])
    seed_offset = int((overrides or {}).get("seed.offset", 0))
    seed = int((overrides or {}).get("seed.value") or derive_seed(spec, rid, attempt, seed_offset))
    all_slots = ref_slots(spec, rc) if mode == "ref2va" else []
    slots = [s for s in all_slots if not s.get("missing")]       # missing 只进计划（preflight 显示），不进图和提示词
    try:
        pr = (PR.build_ref2va(spec, rc, frames, slots, attempt) if mode == "ref2va"
              else PR.build_base(spec, rc, mode, frames, attempt))
    except PR.NeedsWriter as e:
        return _needs_writer(spec, rid, sel, str(e))
    prefix = f"ns_final/{spec.id}/iter_{rid}_a{attempt}"
    if mode == "ref2va":
        wf = G.ref2va(rc, pr["text"], w, h, frames, seed, prefix, slots)
    elif (rc.get("two_stage") or {}).get("enabled"):
        wf = G.two_stage(rc, pr["text"], w, h, frames, seed, prefix, use_last)
    else:
        wf = G.single(rc, pr["text"], w, h, frames, seed, prefix, use_last)
    issues = L.lint_prompt(pr["text"], mode, rc, spec, frames) + L.lint_graph(wf, rc, frames, w, h)
    acc = copy.deepcopy(rc["acceptance"])
    if not any(not d.off_screen and d.speaker in {c.name for c in spec.visible} for d in spec.audio.dialogue):
        acc["lipsync_corr_min"] = None
    if spec.end_frame.exposure_intent in ("dark", "black"):
        acc["dark_run_s_max"] = None
    lane_long = frames > int(rc["frames"]["lane_max_default"]) or (rc.get("lane") or {}).get("prefer") == "long"
    inputs = {k: {"path": v.path, "sha": v.sha} for k, v in sorted(spec.keyframes.items())}
    params = registry.params_of(rc)
    plan = {
        "schema": PLAN_SCHEMA,
        "compiler_version": COMPILER_VERSION,
        "status": "ready" if not any(i["level"] == "error" for i in issues) else "lint_error",
        "spec": {"id": spec.id, "rev": spec.rev, "hash": spec.spec_hash()},
        "recipe": {"id": rid, "label": rc.get("label"), "status": rc.get("status"), "overlays": rc["_overlays"],
                   "learned": rc["_learned"], "hash": registry.recipe_hash(rc), "registry_hash": registry.source_hash,
                   "experiment": registry.raw[rid].get("experiment")},
        "selection": {"chosen": sel.recipe_id, "reasons": sel.reasons + ([blocked_note] if blocked_note else []),
                      "fallback": sel.fallback, "features": sel.features,
                      **({"blocked_swap": blocked_note} if blocked_note else {})},
        "attempt": attempt,
        "overrides": applied | ({"seed.offset": seed_offset} if seed_offset else {}),
        "mode": mode,
        "use_last_frame": use_last,
        "frames": frames,
        "seconds": float(spec.duration_s),
        "width": w, "height": h,
        "seed": seed,
        "prompt": {"text": pr["text"], "notes": pr["notes"], "format": "ref-en" if mode == "ref2va" else "base-en"},
        "inputs": inputs,
        "ref_slots": all_slots,
        "graph": wf,
        "lane": {"long": lane_long, "frames": frames,
                 **({"only": [str(x) for x in (rc.get("lane") or {})["only"]]} if (rc.get("lane") or {}).get("only") else {})},
        "post": rc["post"],
        "acceptance": acc,
        "guidance": rc.get("guidance") or {},
        "keyframe_hints": rc.get("keyframe_hints") or {},
        "params": params,
        "lint": issues,
        "api": api_request(rc, spec, mode, pr["text"], seed, w, h),
        "provenance_ref": {p: v for p, v in sorted(rc.get("provenance", {}).items())
                           if v.get("status") != "确认" or v.get("learned")},
    }
    plan["plan_hash"] = plan_hash(plan)
    return plan


def plan_hash(plan: dict) -> str:
    return canonical_hash({k: v for k, v in plan.items() if k not in ("plan_hash", "provenance_ref", "selection")})


def _needs_writer(spec: ShotSpec, rid: str, sel: Selection, why: str) -> dict:
    plan = {"schema": PLAN_SCHEMA, "compiler_version": COMPILER_VERSION, "status": "needs_writer",
            "spec": {"id": spec.id, "rev": spec.rev, "hash": spec.spec_hash()},
            "recipe": {"id": rid}, "selection": {"chosen": sel.recipe_id, "reasons": sel.reasons,
                                                 "fallback": sel.fallback, "features": sel.features},
            "reason": why}
    plan["plan_hash"] = plan_hash(plan)
    return plan
