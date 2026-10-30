"""
出图与精修循环接口（docs/api_v1_contract.md §C；fredw-92/W2）。

POST /api/shots/{id}/frame-jobs   {stage: first|last, mode: regen|instruct|refs, parent?, prompt?, instruction?,
                                   strength?: small|medium|large, refs?: [{asset_id|path, role}], seed?, gpu?: 0|3, llm?,
                                   tier?: preview|final}
                                  tier=final（fredw-92/Q1，config/render_quality.json）：在父版本（默认 = 定稿版，没有定稿用当前版）上
                                  出定稿档版本（Base 两段式，见 ns_render.final_tier），父版本是定稿版时接替定稿；mode 只能 regen
                                  → {job_id, ...}；任务进 ns_api.jobs 的按卡队列（每卡一个 worker），结果是一个新 take
GET  /api/shots/{id}/frame-jobs   本镜的任务（新 → 旧）
POST /api/shots/{id}/takes/{stage}/{n}/lock | /unlock   定稿 / 取消定稿（stage: first|image|last|video）；
                                  lock body {final:true}（或 render_quality.json auto_final_on_lock）→ 同时排定稿档任务（final_job）
POST /api/shots/{id}/takes/{stage}/{n}/final          “出定稿版”：= frame-jobs {tier:final, parent:n}
任务状态 / 取消：GET /api/jobs/{job_id}、POST /api/jobs/{job_id}/cancel（ns_api.jobs）。
出图参数（fredw-92/PX，ns_render.image_params）：frame-jobs 另收 preset + params 覆盖，校验不过 422；
每一版 take.params.effective 记实际生效的参数。GET /api/render/image-presets（预设 + 范围 + ComfyUI 实时可选值），
POST /api/render/image-presets（存为我的预设）、DELETE /api/render/image-presets/{id}。

不做内容检测：每个任务 1 张，不评分、不看图判定、不否决；提示词与修改原话原样传给 Image 2.1。
"""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ns_api import jobs as J
from ns_render import endpoints as EP
from ns_render import final_tier as FT
from ns_render import frame_edit as FE
from ns_render import image_params as IP
from ns_render import pipeline as P
from ns_render.comfy_client import ComfyError

router = APIRouter(tags=["frame-jobs"])
STAGE_ALIASES = {"first": "image", "image": "image", "last": "last", "video": "video"}
HTTP_TIMEOUT_S = 300                  # 单次 HTTP（上传 / 下载 / object_info）超时
POLL_S = 2.0                          # 等 ComfyUI 结果的轮询间隔（取消最多晚这么久生效）


class RefIn(BaseModel):
    asset_id: str | None = None
    path: str | None = None
    role: str = "item"                 # identity | style | color | item


class FrameJobBody(BaseModel):
    stage: str
    mode: str = "regen"
    parent: int | None = None
    prompt: str | None = None
    instruction: str | None = None
    strength: str | None = None
    refs: list[RefIn] | None = None
    seed: int | None = None
    gpu: int | str | None = None      # G36：道 id（0 / "gpu36:0"）；不给或 "auto" → jobs.pick_lane（偏好 gpu33:0，任意空闲道）
    llm: dict | None = None           # 契约 ⚙ 覆盖：出图本身不调语言模型，只记录
    tier: str = "preview"             # fredw-92/Q1：preview = Turbo 单遍（快）| final = 定稿档（gpu3 生产值）
    # fredw-92/PX：出图参数。preset = config/render_quality.json image_presets / user_presets 的 id；
    # params = 覆盖（ns_render.image_params.DEFAULTS 的字段）。都不给 = default_preset（项目方 2026-10-31 选定 C）
    preset: str | None = None
    params: dict | None = None


def _app():
    from ns_api import app as A          # 延迟导入：当前剧本在 app._script
    return A


def _shot(shot_id: str):
    try:
        return P.find_shot(_app()._script, shot_id)
    except KeyError:
        raise HTTPException(404, f"没有镜头 {shot_id}")


def _invalidate():
    try:
        _app()._summary_cache.invalidate()
    except Exception:  # noqa: BLE001
        pass


def resolve_ref(r: RefIn) -> dict:
    """refs[]：asset_id 先经 W5 的 ns_api.assets.resolve_asset_ref 解析成图片路径（相对项目根：资产参考图 ref_id
    或资产主图）；解析不到时把 asset_id 当路径兜底；给了 path 就直接用 path（相对项目根或 data/）"""
    d = r.model_dump(exclude_none=True)
    if not r.path and r.asset_id:
        from ns_api import assets as AS
        try:
            path = AS.resolve_asset_ref(r.asset_id)
        except HTTPException:
            path = None
        d["path"] = Path(path).as_posix() if path else r.asset_id
        d["resolved_from"] = "asset" if path else "path"
    try:
        FE.resolve_ref_path(d)
    except ValueError as e:
        raise HTTPException(422, f"参考图 {r.asset_id or r.path}：{e}")
    return d


class _Cancellable:
    """ComfyClient 包装：run() 改走 jobs.wait_prompt（取消时只中断 / 删除自己的 prompt）"""

    def __init__(self, client, job: dict, eff: dict | None = None):
        self._c, self._job = client, job
        self._eff = eff                      # fredw-92/PX：出图参数（None = 现状，工作流不改）
        self.last_image_wf: dict | None = None
        if getattr(client, "timeout", 0) and client.timeout < HTTP_TIMEOUT_S:
            client.timeout = HTTP_TIMEOUT_S   # 经隧道上传 / 下载大图：60 s 不够

    def __getattr__(self, name):
        return getattr(self._c, name)

    def run(self, workflow: dict, timeout_s: float):
        if J.cancelled(self._job):
            raise J.Cancelled()
        if IP.is_image_graph(workflow):
            IP.apply(workflow, self._eff, FE.identity_lora_files() if self._eff else None)
            self.last_image_wf = workflow
        problems = self._c.check(workflow)
        if problems:
            raise ComfyError("工作流检查不通过:\n  " + "\n  ".join(problems))
        t0 = time.monotonic()
        entry = J.wait_prompt(self._c, self._job, self._c.submit(workflow), timeout_s, poll_s=POLL_S)
        return entry, time.monotonic() - t0


def resolve_params(body: FrameJobBody) -> dict | None:
    """fredw-92/PX：preset + params → 有效出图参数；都没给 → None（现状）。校验不过 → 422（中文）。
    preset 是定稿档预设且没显式给 tier → 走定稿档"""
    preset = body.preset
    if not preset and not body.params:
        if body.tier == "final":
            return None                      # 定稿档不传参数 = Q1 原样
        preset = IP.default_preset()         # 项目方 2026-10-31 选定 C：预览档默认
    gpu = EP.default_gpu("image") if body.gpu is None or body.gpu == "auto" else body.gpu
    try:
        gpu = J.norm(gpu)
    except ValueError:
        pass
    hit = _ALLOWED.get(gpu)
    try:
        return IP.resolve(preset, body.params, tier=body.tier if "tier" in body.model_fields_set else None,
                          mode=body.mode, allowed=hit[1] if hit else None)
    except IP.ParamError as e:
        raise HTTPException(422, "出图参数不对：" + "；".join(e.errors))


# ComfyUI 实时可选值（按卡缓存）：LoRA / 采样器 / 调度器 / 模型文件
_ALLOWED: dict[int, tuple[float, dict]] = {}
ALLOWED_TTL_S = 600


def lane_allowed(gpu: int, refresh: bool = False) -> dict:
    now = time.time()
    hit = _ALLOWED.get(gpu)
    if hit and not refresh and now - hit[0] < ALLOWED_TTL_S:
        return {**hit[1], "source": "cache", "age_s": round(now - hit[0])}
    try:
        cl = J.client_factory(gpu)
        if getattr(cl, "timeout", None):
            cl.timeout = 20
        info = {**IP.allowed_from_object_info(cl.object_info()), "gpu": gpu, "fetched_at": P.now()}
        _ALLOWED[gpu] = (now, info)
        return {**info, "source": "live", "age_s": 0}
    except Exception as e:  # noqa: BLE001  ComfyUI 连不上：用旧缓存或内置值，不挡页面
        if hit:
            return {**hit[1], "source": "cache", "age_s": round(now - hit[0]), "error": str(e)[:300]}
        return {**IP.allowed_from_object_info({}), "gpu": gpu, "source": "unavailable", "error": str(e)[:300]}


@router.get("/api/render/image-presets")
def image_presets(gpu: int | str | None = None, refresh: bool = False):
    """出图参数面板：预设（内置 + 我的）、现状默认值、范围、ComfyUI 实时可选值（按卡缓存 10 分钟）"""
    g = EP.default_gpu("image") if gpu is None else gpu
    if g not in J.GPUS:
        raise HTTPException(400, f"gpu 只能是 {J.GPUS}")
    g = J.norm(g)
    q = IP.quality()
    fin = (q.get("tiers") or {}).get("final") or {}
    return {"presets": IP.presets(), "defaults": IP.DEFAULTS, "ranges": IP.RANGES, "labels": IP.FIELD_LABEL,
            "unets": IP.UNETS, "vaes": IP.VAES, "identity": IP.IDENTITY,
            "identity_loras": sorted(FE.identity_lora_files()), "banned_loras": fin.get("banned_loras") or [],
            "realism_loras": fin.get("realism_loras") or [], "final_preset": IP.FINAL_PRESET, "default_preset": IP.default_preset(),
            "notes": IP.NOTES, "allowed": lane_allowed(g, refresh)}


class PresetBody(BaseModel):
    label: str
    params: dict
    tier: str = "preview"
    note: str = ""
    base: str | None = None


@router.post("/api/render/image-presets")
def save_image_preset(body: PresetBody):
    """“存为我的预设”：写进 config/render_quality.json user_presets（同名覆盖）"""
    try:
        return IP.save_user_preset(body.label, body.params, tier=body.tier, note=body.note, base=body.base)
    except IP.ParamError as e:
        raise HTTPException(422, "预设不对：" + "；".join(e.errors))


@router.delete("/api/render/image-presets/{preset_id}")
def delete_image_preset(preset_id: str):
    if not IP.delete_user_preset(preset_id):
        raise HTTPException(404, f"没有我的预设 {preset_id}（内置预设不能删）")
    return {"deleted": preset_id}


def _lane(gpu):
    """G36：None / "auto" → jobs.pick_lane("image")；否则校验道 id（不合法 → 400）"""
    try:
        return J.resolve_lane(gpu, "image")
    except ValueError:
        raise HTTPException(400, f"gpu 只能是 {J.GPUS}")


def _eta(mode: str, gpu) -> float:
    """F4：同类（frame）同卡最近完成任务耗时的中位数（含盘上 data/jobs/v1），没有历史 70 s；× 排队数"""
    return J.estimate("frame", gpu)


@router.post("/api/shots/{shot_id}/frame-jobs")
def create_frame_job(shot_id: str, body: FrameJobBody):
    _shot(shot_id)
    if body.stage not in FE.STAGE_OF:
        raise HTTPException(400, "stage 只能是 first | last")
    if body.tier not in FT.TIERS:
        raise HTTPException(400, f"tier 只能是 {' | '.join(FT.TIERS)}")
    eff = resolve_params(body)
    tier = eff["tier"] if eff else body.tier
    seed = body.seed if body.seed is not None else (eff or {}).get("seed")
    if tier == "final":
        if body.mode != "regen":
            raise HTTPException(400, "tier=final 只能 mode=regen（在父版本上出定稿版）")
        return submit_final(shot_id, FE.STAGE_OF[body.stage], parent=body.parent, seed=seed, gpu=body.gpu,
                            eff=eff, overrides=body.params)
    if body.mode not in FE.MODES:
        raise HTTPException(400, f"mode 只能是 {' | '.join(FE.MODES)}")
    stage = FE.STAGE_OF[body.stage]
    gpu = _lane(body.gpu)
    if body.strength is not None and body.strength not in FE.EDIT_DENOISE:
        raise HTTPException(400, f"strength 只能是 {' | '.join(FE.EDIT_DENOISE)}")
    data = P.load_takes(shot_id)
    if body.parent is not None and not any(t["stage"] == stage and t["n"] == body.parent for t in data["takes"]):
        raise HTTPException(404, f"没有{body.stage == 'first' and '首帧' or '尾帧'} v{body.parent}")
    refs = [resolve_ref(r) for r in body.refs or []]
    if body.mode == "regen":
        if stage == "last" and (data.get("locked") or {}).get("image") is None:
            raise HTTPException(409, "首帧还没定稿：尾帧由定稿首帧编辑得到，先定稿首帧")
    else:
        if not (body.instruction or "").strip():
            raise HTTPException(422, "指令改图 / 换参考需要修改要求（instruction）")
        if body.mode == "refs" and not refs:
            raise HTTPException(422, "换参考再改需要至少一张参考图（refs）")
        if body.parent is None and (data.get("active") or {}).get(stage) is None:
            raise HTTPException(409, f"还没有{'首帧' if stage == 'image' else '尾帧'}，先整张出一版（mode=regen）")
    params = body.model_dump(exclude_none=True)
    params["refs"] = refs or None
    # 给了数值重绘幅度（params.strength）的换参考：需要底图，按“中”档带上父版本作底图，幅度由数值覆盖
    strength = body.strength or ("medium" if eff and eff.get("strength") is not None and body.mode == "refs" else None)

    def run(client, job):
        c = _Cancellable(client, job, eff)
        script = _app()._script
        spec_removed = None
        try:
            if body.mode == "regen":
                prompt = body.prompt
                if eff and not eff["spec_words"]:   # 去掉系统追加的规格句（作者原文不动）
                    comp = P.compile_with_edits(script, shot_id, P.available_loras(c))
                    src = prompt or ((comp.image_prompt if stage == "image" else comp.last_prompt) or "")
                    terms = IP.spec_terms(script, comp, stage)
                    spec_removed = [t for t in terms if t in src]
                    prompt = IP.strip_spec(src, terms)
                take = FE.regen(c, script, shot_id, stage, prompt=prompt, parent=body.parent,
                                seed=seed, job=job)
            else:
                take = FE.edit_frame(c, script, shot_id, stage, mode=body.mode, parent=body.parent,
                                     instruction=body.instruction or "", strength=strength, refs=refs,
                                     seed=seed, job=job)
            t = take if isinstance(take, dict) else take.model_dump()
            take = IP.finish(shot_id, stage, t["n"], eff, c.last_image_wf, overrides=body.params,
                             spec_removed=spec_removed)
        except J.Cancelled:
            raise
        except Exception as e:
            if not J.cancelled(job):
                P._write_json(P.shot_dir(shot_id) / "errors.json", {"last": str(e), "at": P.now()})
            raise
        finally:
            _invalidate()
        return _result(shot_id, stage, take)

    job = J.submit("frame", shot_id, gpu, run, params=params, eta_s=_eta(body.mode, gpu),
                   stage=body.stage, mode=body.mode, url=EP.url_for_gpu(gpu))
    return job


def _result(shot_id: str, stage: str, take) -> dict:
    t = take if isinstance(take, dict) else take.model_dump()
    if not t.get("look_hash"):   # F4：与旧渲染队列一样补记造型哈希（「造型已改」判定）；改图版本已继承父版本的
        _app()._record_look_hash(shot_id, stage, t["n"])
        t = next((x for x in P.load_takes(shot_id)["takes"] if x["stage"] == stage and x["n"] == t["n"]), t)
    rel = t.get("file")
    url = f"/files/{rel}" if rel and (P.DATA / rel).exists() else None
    return {"take": {**t, "url": url}, "take_n": t["n"]}


def submit_final(shot_id: str, stage: str, *, parent: int | None = None, seed: int | None = None,
                 gpu: int | str | None = None, eff: dict | None = None, overrides: dict | None = None) -> dict:
    """fredw-92/Q1：定稿档任务（ns_render.final_tier.render_final）。父版本默认 = 定稿版，没有定稿用当前版"""
    if stage not in ("image", "last"):
        raise HTTPException(400, "定稿档只用于首帧 / 尾帧")
    gpu = _lane(gpu)
    try:
        src = FT.pick_parent(shot_id, stage, parent)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'"))
    except ComfyError as e:
        raise HTTPException(409, str(e))
    if src.get("mode") == FT.FINAL_MODE:
        raise HTTPException(409, f"{stage} v{src['n']} 已经是定稿档版本")
    name = "first" if stage == "image" else "last"
    params = {"stage": name, "mode": "regen", "tier": "final", "parent": src["n"], "seed": seed, "gpu": gpu,
              "preset": (eff or {}).get("preset"), "params": overrides}

    def run(client, job):
        c = _Cancellable(client, job, eff)
        try:
            take = FT.render_final(c, _app()._script, shot_id, stage, parent=src["n"], seed=seed, job=job,
                                   cfg=IP.final_cfg_for(eff) if eff else None,
                                   spec_words=(eff or {}).get("spec_words", True))
            t = take if isinstance(take, dict) else take.model_dump()
            take = IP.finish(shot_id, stage, t["n"], eff, c.last_image_wf, overrides=overrides)
        except J.Cancelled:
            raise
        except Exception as e:
            if not J.cancelled(job):
                P._write_json(P.shot_dir(shot_id) / "errors.json", {"last": str(e), "at": P.now()})
            raise
        finally:
            _invalidate()
        return _result(shot_id, stage, take)

    return J.submit("frame", shot_id, gpu, run, params={k: v for k, v in params.items() if v is not None},
                    eta_s=_eta("final", gpu), stage=name, mode="regen", tier="final", url=EP.url_for_gpu(gpu))


@router.get("/api/shots/{shot_id}/frame-jobs")
def list_frame_jobs(shot_id: str):
    _shot(shot_id)   # fredw-92/B-fix：不存在的镜头 → 404（以前 200 []）
    return [j for j in J.all_jobs(shot_id) if j.get("kind") == "frame"]


def _stage(stage: str) -> str:
    if stage not in STAGE_ALIASES:
        raise HTTPException(400, "stage 只能是 first | last | video")
    return STAGE_ALIASES[stage]


class LockBody(BaseModel):
    """尾帧来自视频版本时（POST .../takes/last/{n}/lock）：from_stage="video" 表示 n 是视频版本号，
    取它的 last_frame；chain="gpu3" + file（相对 data/，renders_gpu3/...）= gpu3 链视频上的尾帧"""
    from_stage: str | None = None
    chain: str = "canvas"
    file: str | None = None
    final: bool | None = None          # fredw-92/Q1：true = 定稿后排一个定稿档任务；None = 按 render_quality.json auto_final_on_lock


def _lock_view(out: dict) -> dict:
    return {"locked": out.get("locked") or {}, "locked_src": out.get("locked_src") or {},
            "stale": out.get("stale") or {}, "active": out.get("active") or {}}


@router.post("/api/shots/{shot_id}/takes/{stage}/{n}/lock")
def lock_take(shot_id: str, stage: str, n: int, body: LockBody | None = None):
    """定稿。stage 接受 first|image（存为 takes.json locked.image）、last、video；顶层 locked 按 stage 分别记"""
    _shot(shot_id)
    st = _stage(stage)
    body = body or LockBody()
    try:
        if st == "last" and (body.from_stage == "video" or body.chain == "gpu3"):
            if body.chain not in ("canvas", "gpu3"):
                raise HTTPException(400, "chain 只能是 canvas | gpu3")
            out = FE.lock_last_from(shot_id, video_n=n, file=body.file, chain=body.chain)
        else:
            with P.shot_lock(shot_id):   # fredw-92/B-fix：检查“首帧已定稿”与定稿在同一把每镜锁里（FE.lock 内同锁可重入）
                if st == "last" and (P.load_takes(shot_id).get("locked") or {}).get("image") is None:
                    raise HTTPException(409, "首帧还没定稿，不能定稿尾帧")
                out = FE.lock(shot_id, st, n)
    except KeyError as e:
        raise HTTPException(404, str(e).strip("'"))
    _invalidate()
    view = _lock_view(out)
    want = body.final if body.final is not None else FT.auto_final_on_lock()
    if want and st in ("image", "last"):
        locked = next((t for t in out.get("takes") or [] if t["stage"] == st and t["n"] == (out.get("locked") or {}).get(st)), {})
        if locked.get("mode") != FT.FINAL_MODE and locked.get("workflow") not in FE.NO_PROMPT_WORKFLOWS:
            view["final_job"] = submit_final(shot_id, st, parent=locked.get("n"))
    return view


class FinalBody(BaseModel):
    seed: int | None = None
    gpu: int | str | None = None      # G36：道 id（0 / "gpu36:0"）；不给或 "auto" → jobs.pick_lane（偏好 gpu33:0，任意空闲道）


@router.post("/api/shots/{shot_id}/takes/{stage}/{n}/final")
def final_take(shot_id: str, stage: str, n: int, body: FinalBody | None = None):
    """“出定稿版”（fredw-92/Q1）：在 vN 上出定稿档版本；vN 是定稿版时，定稿版完成后接替定稿"""
    _shot(shot_id)
    st = _stage(stage)
    return submit_final(shot_id, st, parent=n, seed=body.seed if body else None, gpu=body.gpu if body else None)


@router.post("/api/shots/{shot_id}/takes/{stage}/{n}/unlock")
def unlock_take(shot_id: str, stage: str, n: int):
    _shot(shot_id)
    out = FE.unlock(shot_id, _stage(stage))
    _invalidate()
    return _lock_view(out)
