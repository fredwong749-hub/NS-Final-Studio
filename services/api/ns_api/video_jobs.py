"""
视频任务（docs/api_v1_contract.md §D，fredw-92/W3）。

POST /api/shots/{id}/video-jobs  body {parent?, prompt_override?, seed?, steps?, seconds?, lora_strength?, gpu?: 3|0,
                                        loras?: [{name, strength}]}
  loras（fredw-92/VB）：附加 H3 LoRA，串在 Turbo LoRA（和剧本视频 LoRA）之后；名字须在目标道 ComfyUI 的
  LoraLoaderModelOnly 列表里，强度 0–1.5；记在 take.params.model.extra_loras 与 params.loras。
GET  /api/video-loras  → config/render_quality.json 的可选视频 LoRA（含许可 / 用途 / 推荐强度），画布下拉用
  → {job_id, ...}；首尾帧须已定稿，否则 409 {missing:[first|last], message}。
  结果是一个 stage="video" 的 take（params 记全部参数 + 首尾帧版本 / sha；parent 形成版本链），走 GET /api/jobs/{id}。
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
    names = [x.name.strip() for x in req.loras or []]
    for x in req.loras or []:
        if not x.name.strip():
            raise HTTPException(422, "loras[].name 不能为空")
        if not HV.EXTRA_LORA_MIN <= x.strength <= HV.EXTRA_LORA_MAX:
            raise HTTPException(422, f"loras[].strength 须在 {HV.EXTRA_LORA_MIN:g}–{HV.EXTRA_LORA_MAX:g}（{x.name}）")
        if x.name.strip() == W.H3_TURBO_8STEP_768P:
            raise HTTPException(422, "Turbo LoRA 已在图里，强度用 lora_strength 调")
    if len(set(names)) != len(names):
        raise HTTPException(422, "loras 里有重复的名字")


def _check_lane_loras(req: VideoJobRequest):
    """附加 LoRA 的名字按目标道 ComfyUI 的 object_info 校验（读不到 → 503）"""
    if not req.loras:
        return
    try:
        avail = P.available_loras(J.client_factory(req.gpu))
    except (ComfyError, OSError, KeyError, TypeError) as e:
        raise HTTPException(503, f"读不到 GPU{req.gpu} 的 LoRA 列表：{e}")
    bad = [x.name.strip() for x in req.loras if x.name.strip() not in avail]
    if bad:
        raise HTTPException(422, f"GPU{req.gpu} 上没有这些 LoRA：{', '.join(bad)}")


@router.get("/api/video-loras")
def video_loras():
    """fredw-92/VB：可选附加视频 LoRA（config/render_quality.json optional_video_loras）"""
    return {"loras": HV.optional_video_loras(), "strength_range": [HV.EXTRA_LORA_MIN, HV.EXTRA_LORA_MAX]}


@router.post("/api/shots/{shot_id}/video-jobs")
def create_video_job(shot_id: str, req: VideoJobRequest):
    script = get_script()
    try:
        P.find_shot(script, shot_id)
    except (KeyError, StopIteration, ValueError):
        raise HTTPException(404, "没有这个镜头")
    _validate(req)
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
    req = req.model_copy(update={"gpu": lane})
    _check_lane_loras(req)
    params = {**req.model_dump(exclude_none=True), "parent": parent, "seconds": seconds,
              "frames": HV.frames_for(seconds)[0], "frames_requested": frames_for_seconds(seconds),
              "first": frames_in["first"], "last": frames_in["last"]}   # fredw-92/D1：frames 按显存上限（h3_video.safe_max_frames）

    def run(client, job):
        take = HV.render(client, get_script(), shot_id, seed=req.seed, steps=req.steps, seconds=req.seconds,
                         lora_strength=req.lora_strength, prompt_override=req.prompt_override, parent=parent,
                         job=job, gpu=req.gpu, wait=J.wait_prompt,
                         extra_loras=[(x.name.strip(), x.strength) for x in req.loras or []])
        FE.annotate(shot_id, "video", take.n, from_first=take.from_first)   # 清 W2 的 stale.video（由当前定稿首帧得到）
        if on_done:
            on_done(shot_id, take)
        return {"take": take.n, "take_params": take.params, "wall_render_s": take.seconds}

    job = J.submit("video", shot_id, req.gpu, run, params=params, eta_s=J.estimate("video", req.gpu))
    return job


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
