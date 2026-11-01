"""
视频任务（docs/api_v1_contract.md §D，fredw-92/W3）。

POST /api/shots/{id}/video-jobs  body {parent?, prompt_override?, seed?, steps?, seconds?, lora_strength?, gpu?: 3|0,
                                        loras?: [{name, strength}]}
  loras（fredw-92/VB）：附加 H3 LoRA，串在 Turbo LoRA（和剧本视频 LoRA）之后；名字须在目标道 ComfyUI 的
  LoraLoaderModelOnly 列表里，强度 0–1.5；记在 take.params.model.extra_loras 与 params.loras。
GET  /api/video-loras  → config/render_quality.json 的可选视频 LoRA（含许可 / 用途 / 推荐强度），画布下拉用
  base（fredw-92/PF）：不传 = config video_bases.default（RR 2026-10-31 起 "official_base"：基模 24 步、只给首帧）|
  "official_turbo"（旧默认，Turbo v1.1 768p、euler、6/3、8 步、首尾帧）| "pika_flex"（Pika H3 Flex
  FL2VA LoRA、lcm、官方 7 值 sigma、6 步、不叠 Turbo；steps / lora_strength 固定，传了且不等于官方值 → 422）。
  基底 LoRA 按目标道 object_info 校验（没有 → 422，读不到 → 503）；take.params.base / base_params 记全部参数。
GET  /api/video-bases  → config/render_quality.json video_bases（画布“视频基底”选项）
  → {job_id, ...}；首尾帧须已定稿，否则 409 {missing:[first|last], message}。
  结果是一个 stage="video" 的 take（params 记全部参数 + 首尾帧版本 / sha；parent 形成版本链），走 GET /api/jobs/{id}。
last_frame_mode（fredw-92/QCV）：不传 = 基底的 default_last_frame_mode（official_base = "none"，official_turbo = "use"）|
  "use"（首尾帧都给）| "none"（只给首帧，I2VA 对齐句）|
  "auto"（首尾帧几乎一样时只给首帧）。提交时算定稿首帧 ↔ 尾帧差（ns_render.motion_qc.keyframe_check），太小 →
  响应 warnings / keyframe_check 带中文提示（“尾帧和首帧几乎一样，视频大概率不动”），不拦项目方自己点的出片。
  出片后每版算运动量写 take.qc.motion（verdict pass|warn|fail、labels “静止·不合格”“结尾定住 Ns”、metrics）。
POST /api/qc/motion/backfill?episode=ep02&force=false → 给现有视频版本补 qc.motion（已有同版本的跳过）
GET  /api/shots/{id}/video-takes  → 视频版本链（每版 params、parent、过期原因 stale），供对比。

不做内容检测 / 成人拦截；提示词原样（见 ns_render.h3_video）。
"""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from ns_render import frame_edit as FE
from ns_render import h3_video as HV
from ns_render import pipeline as P
from ns_render import workflows as W
from ns_schema.h3_lint import frames_for_seconds
from ns_api import jobs as J
from ns_render.comfy_client import ComfyError

router = APIRouter()
get_script = P.load_script          # app.py 换成返回当前内存剧本的函数
on_done = None                      # app.py：任务完成后的回调（清摘要缓存等）
on_qc_changed = None                # app.py：补运动质检后清摘要缓存（fredw-92/QCV）
# F4：预计耗时 = 最近同卡视频任务耗时中位数（data/jobs/v1），没有历史按 840 s（GPU3 实测约 14 min），见 jobs.estimate


class VideoLora(BaseModel):
    name: str
    strength: float


class VideoJobRequest(BaseModel):
    parent: int | None = None
    prompt_override: str | None = None
    seed: int | None = None
    steps: int | None = None
    seconds: float | None = None
    lora_strength: float | None = None
    gpu: int | str | None = None      # G36：道 id（3 / "gpu36:1"）；不给或 "auto" → jobs.pick_lane 自动分配
    loras: list[VideoLora] | None = None
    base: str | None = None
    last_frame_mode: str | None = None    # fredw-92/QCV：use | none | auto；不传 = 基底默认（RR：official_base = none）
    by: str | None = None                 # PREP 资料闸门：auto / episode_produce … = 自动提交，资料不全 409；不给 = 手动，照出 + materials_warnings
    recipe_plan: "RecipePlan | None" = None   # ARCH：配方引擎计划（plan_hash 记进 take.params.recipe；带 graph = 原样出图）


class RecipePlan(BaseModel):
    """ARCH（services/recipes 配方引擎 + tools/iterate_loop）：plan_hash / recipe_id 只做溯源；graph 不为空时按图原样出片
    （ns_api.recipe_render，用于 Ref2VA / 两段式等 API 参数表达不了的配方），images = 占位符 @ref:<角色名> → 参考图相对路径"""
    plan_hash: str
    recipe_id: str
    graph: dict | None = None
    images: dict[str, str] | None = None


VideoJobRequest.model_rebuild()


def _validate(req: VideoJobRequest):
    if not (req.gpu is None or str(req.gpu).strip().lower() == "auto") and req.gpu not in J.GPUS:
        raise HTTPException(422, f"gpu 只能是 {J.GPUS}")
    if req.steps is not None and not W.H3_MIN_TURBO_STEPS <= req.steps <= 50:
        raise HTTPException(422, f"steps 须在 {W.H3_MIN_TURBO_STEPS}–50（Turbo LoRA 少于 {W.H3_MIN_TURBO_STEPS} 步会慢动作 / 蜡化）")
    if req.seconds is not None:
        if req.seconds <= 0:
            raise HTTPException(422, "seconds 须为正数")
        if req.seconds > W.H3_FRAMES_MAX / 24:
            raise HTTPException(422, f"seconds 超出 H3 上限 {W.H3_FRAMES_MAX / 24:.2f} 秒（{W.H3_FRAMES_MAX} 帧）")
    if req.lora_strength is not None and not 0 <= req.lora_strength <= 2:
        raise HTTPException(422, "lora_strength 须在 0–2")
    if req.seed is not None and req.seed < 0:
        raise HTTPException(422, "seed 须 ≥ 0")
    if req.last_frame_mode is not None and req.last_frame_mode not in HV.LAST_FRAME_MODES:
        raise HTTPException(422, f"last_frame_mode 只能是 {list(HV.LAST_FRAME_MODES)}")
    try:
        spec = HV.base_spec(req.base)
    except KeyError:
        ids = [b["id"] for b in HV.video_bases()["bases"]]
        raise HTTPException(422, f"base 只能是 {ids}")
    if not spec.get("steps_adjustable"):
        if req.steps is not None and req.steps != int(spec["steps"]):
            raise HTTPException(422, f"基底 {spec['id']} 步数固定为 {spec['steps']}（官方 sigma 表，不能改）")
        if req.lora_strength is not None and req.lora_strength != float(spec.get("lora_strength", 1.0)):
            raise HTTPException(422, f"基底 {spec['id']} 的 LoRA 强度固定为 {spec.get('lora_strength', 1.0)}")
    names = [x.name.strip() for x in req.loras or []]
    for x in req.loras or []:
        if not x.name.strip():
            raise HTTPException(422, "loras[].name 不能为空")
        if not HV.EXTRA_LORA_MIN <= x.strength <= HV.EXTRA_LORA_MAX:
            raise HTTPException(422, f"loras[].strength 须在 {HV.EXTRA_LORA_MIN:g}–{HV.EXTRA_LORA_MAX:g}（{x.name}）")
        if x.name.strip() == W.H3_TURBO_8STEP_768P:
            raise HTTPException(422, "Turbo LoRA 已在图里，强度用 lora_strength 调" if spec["id"] == HV.DEFAULT_BASE
                                else f"基底 {spec['id']} 不能叠 Turbo LoRA")
        if x.name.strip() == spec.get("lora"):
            raise HTTPException(422, f"{x.name.strip()} 是基底 LoRA，已在图里")
    if len(set(names)) != len(names):
        raise HTTPException(422, "loras 里有重复的名字")


def _check_lane_loras(req: VideoJobRequest):
    """附加 LoRA（和非默认基底的 LoRA）按目标道 ComfyUI 的 object_info 校验（读不到 → 503）"""
    spec = HV.base_spec(req.base)
    need_base = spec["id"] != HV.DEFAULT_BASE
    if not req.loras and not need_base:
        return
    try:
        avail = P.available_loras(J.client_factory(req.gpu))
    except (ComfyError, OSError, KeyError, TypeError) as e:
        raise HTTPException(503, f"读不到 GPU{req.gpu} 的 LoRA 列表：{e}")
    if need_base and spec.get("lora") and spec["lora"] not in avail:
        raise HTTPException(422, f"GPU{req.gpu} 上没有基底 {spec['id']} 的 LoRA：{spec['lora']}")
    bad = [x.name.strip() for x in req.loras or [] if x.name.strip() not in avail]
    if bad:
        raise HTTPException(422, f"GPU{req.gpu} 上没有这些 LoRA：{', '.join(bad)}")


def lane_with_video_loras(lane, need: list[tuple[str, float]], frames: int, avail_of=None, lane_list=None) -> dict:
    """FIX（ep02_iter P0，C2/E3）：本镜视频身份 LoRA 按在画角色确定；目标道缺 → 改派有这些 LoRA 且帧数够的道；
    一条都没有 → 409（以前编译时按道的 LoRA 列表悄悄去掉，同一镜不同版本挂法不一样）。
    → {lane, rerouted_from?, need}；读不到目标道 LoRA 列表时不改派（出片时 h3_video.render 会再查一次）"""
    from ns_render import endpoints as EP
    names = [n for n, _ in need or []]
    if not names:
        return {"lane": lane}
    avail_of = avail_of or (lambda g: P.available_loras(J.client_factory(g)))
    try:
        if not HV.missing_video_loras(need, avail_of(lane)):
            return {"lane": lane, "need": names}
    except Exception:  # noqa: BLE001
        return {"lane": lane, "need": names, "unchecked": True}
    try:
        cands = [ln["gpu"] for ln in (lane_list if lane_list is not None else J.lanes()) if ln.get("ok")
                 and ln["gpu"] != lane and int(ln.get("max_frames") or EP.max_frames(ln["gpu"])) >= int(frames)]
    except Exception:  # noqa: BLE001
        cands = []
    for g in cands:
        try:
            if not HV.missing_video_loras(need, avail_of(g)):
                return {"lane": g, "need": names, "rerouted_from": EP.lane_name(lane)}
        except Exception:  # noqa: BLE001
            continue
    raise HTTPException(409, f"本镜需要视频 LoRA {', '.join(names)}（按在画角色确定），GPU {lane} 和其他可用道都没有；"
                             "不派单（不在缺 LoRA 的道上静默不挂）")


@router.get("/api/video-loras")
def video_loras():
    """fredw-92/VB：可选附加视频 LoRA（config/render_quality.json optional_video_loras）"""
    return {"loras": HV.optional_video_loras(), "strength_range": [HV.EXTRA_LORA_MIN, HV.EXTRA_LORA_MAX]}


@router.get("/api/video-bases")
def video_bases():
    """fredw-92/PF：视频基底（config/render_quality.json video_bases）"""
    return HV.video_bases()


def route_long(lane, frames: int) -> dict:
    """fredw-92/LS：本道实测上限（ns_render.endpoints.max_frames）够 → 原道；不够 → 改派能一次出这么长的道
    （可达的里排队最少的；探测不到就按配置顺序）。一条都没有 → 409（不截短、不偷偷出短版）。
    → {lane, lane_max_frames, rerouted_from?}"""
    from ns_render import endpoints as EP
    if frames <= EP.max_frames(lane):
        return {"lane": lane, "lane_max_frames": EP.max_frames(lane)}
    cands = EP.long_lanes(frames)
    if not cands:
        raise HTTPException(409, f"{frames} 帧（剧本时长）超过所有道的实测上限（最长 "
                                 f"{max(EP.max_frames(g) for g in J.GPUS)} 帧），没有长镜头道可派；"
                                 "请先启动长镜头道 gpu36:2（docs/USER_GUIDE_v1.md）")
    pick = cands[0]
    try:
        info = {ln["gpu"]: ln for ln in J.lanes()}
        live = [g for g in cands if (info.get(g) or {}).get("ok")]
        if live:
            pick = min(live, key=lambda g: ((info[g].get("load_s") or 0), cands.index(g)))
    except Exception:  # noqa: BLE001  探测失败不挡提交：按配置顺序
        pass
    return {"lane": pick, "lane_max_frames": EP.max_frames(pick), "rerouted_from": EP.lane_name(lane)}


@router.post("/api/shots/{shot_id}/video-jobs")
def create_video_job(shot_id: str, req: VideoJobRequest):
    script = get_script()
    try:
        P.find_shot(script, shot_id)
    except (KeyError, StopIteration, ValueError):
        raise HTTPException(404, "没有这个镜头")
    _validate(req)
    from ns_api import material_readiness as MR
    mat_warn = MR.job_gate(script, shot_id, req.by)          # PREP：自动提交资料不全 → 409；手动只提醒
    ok, why = FE.frames_ready(shot_id)   # W2：首尾帧都定稿且尾帧未过期
    if not ok:
        lk = P.load_takes(shot_id).get("locked") or {}
        missing = [k for k, st in (("first", "image"), ("last", "last")) if lk.get(st) is None] or ["last"]
        return JSONResponse(status_code=409, content={"detail": f"不能出视频：{why}", "missing": missing})
    try:
        frames_in = HV.locked_frames(shot_id)
    except HV.FramesNotLocked as e:
        return JSONResponse(status_code=409, content={"detail": str(e), "missing": e.missing})
    takes = P.load_takes(shot_id)
    if req.parent is not None and not any(t["stage"] == "video" and t["n"] == req.parent for t in takes["takes"]):
        raise HTTPException(404, f"没有视频版本 {req.parent}")
    parent = req.parent if req.parent is not None else takes.get("active", {}).get("video")
    seconds = req.seconds or HV.shot_seconds(script, shot_id)
    try:   # G36：不指定道 → 按空闲 / 队长自动分（任何空闲道都能接视频，出图道要等出图队列空）
        lane = J.resolve_lane(req.gpu, "video", HV.frames_for(seconds)[0])
    except ValueError as e:
        raise HTTPException(422, str(e))
    frames = HV.frames_for(seconds)[0]
    route = route_long(lane, frames)          # fredw-92/LS：超过本道实测上限 → 改派长镜头道（不截短）
    lane = route["lane"]
    vl = lane_with_video_loras(lane, HV.required_video_loras(script, shot_id), frames)   # FIX P0：身份 LoRA 按角色
    if vl["lane"] != lane:
        route = {**route, "lane": vl["lane"], "lora_rerouted_from": vl.get("rerouted_from")}
        lane = vl["lane"]
    req = req.model_copy(update={"gpu": lane})
    _check_lane_loras(req)
    base_id = HV.base_spec(req.base)["id"]
    pre = HV.keyframe_precheck(frames_in)            # fredw-92/QCV：出片前首尾帧差，只提示不拦
    # MOT / RR：请求没写 last_frame_mode 时用基底自己的默认（默认基底 official_base = "none" 只给首帧；official_turbo = "use"）
    mode = HV.default_last_frame_mode(HV.base_spec(req.base), req.last_frame_mode)
    use_last = HV.use_last_frame(mode, pre)
    warnings = [pre["message"]] if pre.get("warn") and use_last else []
    # FIX（CHAIN F3）：提交前按实际模式（首尾帧 FL2VA / 只给首帧 I2VA）跑 lint_h3，block → 409（项目方原话覆盖豁免）
    prompt0, psrc, _c = HV.resolve_prompt(script, shot_id, req.prompt_override, set())
    if psrc not in HV.LINT_EXEMPT_SOURCES:
        failed, why = HV.submit_lint(HV.final_prompt(prompt0, frames, use_last)[0], frames, use_last)
        if failed:
            return JSONResponse(status_code=409, content={
                "detail": "H3 提示词没过官方规范检查（block），不出片：" + "；".join(
                    f"{r} {d}" for r, d in zip(failed, why)), "lint_failed": failed})
    rp = req.recipe_plan
    if rp is not None and rp.graph:   # ARCH：配方图提交前校验（禁用节点 / 悬空连线 / 占位符）+ 图里提示词跑同一个 lint
        from ns_api import recipe_render as RR
        errs = RR.validate_graph(rp.graph, rp.images)
        if errs:
            raise HTTPException(422, "配方图校验不通过：" + "；".join(errs))
        g_last = RR.PH_LAST in RR.placeholders(rp.graph)
        g_frames = RR.graph_frames(rp.graph) or frames
        failed, why = HV.submit_lint(RR.graph_prompt(rp.graph), g_frames, g_last)
        if failed:
            return JSONResponse(status_code=409, content={
                "detail": "配方图提示词没过官方规范检查（block），不出片：" + "；".join(
                    f"{r} {d}" for r, d in zip(failed, why)), "lint_failed": failed})
    params = {**req.model_dump(exclude_none=True, exclude={"recipe_plan"}), "base": base_id, "parent": parent,
              "seconds": seconds,
              "frames": frames, "frames_requested": frames_for_seconds(seconds),
              "method": "single", "route": route,
              "first": frames_in["first"], "last": frames_in["last"],
              "last_frame_mode": mode, "last_frame_used": use_last, "keyframe_check": pre,
              "warnings": warnings}   # fredw-92/LS：frames = 剧本时长，不截短
    if rp is not None:
        params["recipe"] = {"plan_hash": rp.plan_hash, "recipe_id": rp.recipe_id, "graph": bool(rp.graph)}
        if rp.graph:
            params["method"] = "recipe_graph"

    def run(client, job):
        if rp is not None and rp.graph:
            from ns_api import recipe_render as RR
            take = RR.render_graph(client, shot_id, rp.graph, plan_hash=rp.plan_hash, recipe_id=rp.recipe_id,
                                   images=rp.images, seed=req.seed, parent=parent, job=job, gpu=req.gpu,
                                   wait=J.wait_prompt)
        else:
            take = HV.render(client, get_script(), shot_id, seed=req.seed, steps=req.steps, seconds=req.seconds,
                             lora_strength=req.lora_strength, prompt_override=req.prompt_override, parent=parent,
                             job=job, gpu=req.gpu, wait=J.wait_prompt,
                             extra_loras=[(x.name.strip(), x.strength) for x in req.loras or []], base=base_id,
                             last_frame_mode=mode)
            if rp is not None:   # ARCH：take.params 记配方计划（溯源 / 作业丢失时按 plan_hash 找回）
                FE.annotate(shot_id, "video", take.n, params={**(take.params or {}),
                                                             "recipe": {"plan_hash": rp.plan_hash,
                                                                        "recipe_id": rp.recipe_id}})
        FE.annotate(shot_id, "video", take.n, from_first=take.from_first)   # 清 W2 的 stale.video（由当前定稿首帧得到）
        if on_done:
            on_done(shot_id, take)
        return {"take": take.n, "take_params": take.params, "wall_render_s": take.seconds,
                "qc": take.qc}

    job = J.submit("video", shot_id, req.gpu, run, params=params, eta_s=J.estimate("video", req.gpu))
    return {**job, "warnings": warnings, "keyframe_check": pre,
            **({"materials_warnings": mat_warn} if mat_warn else {})} if isinstance(job, dict) else job


@router.post("/api/qc/motion/backfill")
def motion_backfill(episode: str | None = None, shot_id: str | None = None, force: bool = False):
    """fredw-92/QCV：给现有视频版本补运动量质检（take.qc.motion）。→ {count, fail, warn, results}"""
    from ns_render import motion_qc as MQ
    res = MQ.backfill([shot_id] if shot_id else None, force=force, episode=episode)
    if on_qc_changed and any(not r.get("skipped") for r in res):
        on_qc_changed()
    return {"count": len(res), "fail": sum(r["verdict"] == "fail" for r in res),
            "warn": sum(r["verdict"] == "warn" for r in res), "results": res}


@router.get("/api/shots/{shot_id}/video-takes")
def video_takes(shot_id: str):
    """视频版本链：每版 params / parent / 是否当前 / 过期原因（定稿首尾帧换了）"""
    try:   # fredw-92/B-fix：先确认镜头存在（"abc" / "a-b-c" 以前在 shot_dir 里 ValueError → 500）
        P.find_shot(get_script(), shot_id)
    except (KeyError, StopIteration, ValueError):
        raise HTTPException(404, "没有这个镜头")
    takes = P.load_takes(shot_id)
    act = takes.get("active", {}).get("video")
    out = []
    for t in takes["takes"]:
        if t["stage"] != "video":
            continue
        out.append({**t, "active": t["n"] == act, "stale": HV.stale_reasons(t, takes),
                    "url": f"/files/{t['file']}", "last_url": f"/files/{t['last_frame']}" if t.get("last_frame") else None})
    return {"active": act, "takes": out, "jobs": [j for j in J.all_jobs(shot_id) if j["kind"] == "video"][:20]}
