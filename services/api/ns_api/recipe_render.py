"""配方计划接入点（ARCH 2026-10-31）：POST /api/shots/{id}/video-jobs 带 recipe_plan.graph 时，按配方引擎
（services/recipes/ns_recipes）编译好的 ComfyUI API 图原样出片，API 只负责：
  上传定稿首 / 尾帧和身份参考图 → 替换图里的占位符（@first_frame / @last_frame / @ref:<角色名> / @look:<角色名>）→ 提交 → 存 take。
图本身不重建、不改（plan_hash 可追溯、可重放）。用于 API 现有参数表达不了的配方：Ref2VA、两段式、改分辨率 / 采样器等。

校验（validate_graph，提交前在请求线程里跑，不通过 422）：禁用节点（ns_render.workflows.H3_BANNED_NODES）、
悬空连线、未知占位符、必须有 SaveVideo、参考图路径必须在 assets/ 或 data/ 下。
take.params 记 method = "recipe_graph"、recipe {plan_hash, recipe_id, graph_sha}、种子、帧数、首尾帧版本。
"""
from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path

from ns_render import comfy_client as CC
from ns_render import h3_video as HV
from ns_render import motion_qc as MQ
from ns_render import pipeline as P
from ns_render import workflows as W
from ns_render.comfy_client import ComfyError
from ns_schema.edits import Take

ROOT = P.DATA.parent
PH_FIRST, PH_LAST, PH_REF = "@first_frame", "@last_frame", "@ref:"
PH_LOOK = "@look:"          # Ref2VA 造型槽（K-REN-303）：路径由调用方在 images 里给（iterate_loop submitter 取计划 outfit 槽）
VIDEO_NODES = ("MiniMaxH3ImageToVideo", "MiniMaxH3ReferenceToVideo")


def graph_sha(graph: dict) -> str:
    return hashlib.sha256(json.dumps(graph, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                          .encode("utf-8")).hexdigest()


def placeholders(graph: dict) -> set[str]:
    return {n["inputs"]["image"] for n in graph.values()
            if n.get("class_type") == "LoadImage" and str(n.get("inputs", {}).get("image", "")).startswith("@")}


def _safe_ref(rel: str) -> Path | None:
    p = (ROOT / rel).resolve()
    for base in (ROOT / "assets", ROOT / "data"):
        try:
            p.relative_to(base.resolve())
            return p if p.is_file() else None
        except ValueError:
            continue
    return None


def validate_graph(graph: dict, images: dict[str, str] | None = None) -> list[str]:
    errs = []
    if not isinstance(graph, dict) or not graph:
        return ["graph 为空"]
    for nid, n in graph.items():
        ct = n.get("class_type")
        if not ct:
            errs.append(f"节点 {nid} 没有 class_type")
            continue
        if ct in W.H3_BANNED_NODES:
            errs.append(f"节点 {nid} {ct} 在禁用列表（H3_BANNED_NODES）")
        for k, v in (n.get("inputs") or {}).items():
            if isinstance(v, list) and len(v) == 2 and isinstance(v[0], str) and isinstance(v[1], int) and v[0] not in graph:
                errs.append(f"{nid}.{k} → {v[0]} 不存在")
    if not any(n.get("class_type") == "SaveVideo" for n in graph.values()):
        errs.append("没有 SaveVideo 节点")
    if not any(n.get("class_type") in VIDEO_NODES for n in graph.values()):
        errs.append("没有 H3 视频节点")
    for ph in placeholders(graph):
        if ph in (PH_FIRST, PH_LAST):
            continue
        if not ph.startswith((PH_REF, PH_LOOK)):
            errs.append(f"未知占位符 {ph}")
        elif not (images or {}).get(ph):
            errs.append(f"占位符 {ph} 没有给参考图路径")
        elif _safe_ref(images[ph]) is None:
            errs.append(f"参考图 {images[ph]} 不存在或不在 assets/ / data/ 下")
    return errs


def graph_prompt(graph: dict) -> str:
    for n in graph.values():
        if n.get("class_type") in VIDEO_NODES:
            return str(n["inputs"].get("prompt") or "")
    return ""


def graph_frames(graph: dict) -> int | None:
    for n in graph.values():
        if n.get("class_type") in VIDEO_NODES:
            return int(n["inputs"].get("length") or 0) or None
    return None


def render_graph(client, shot_id: str, graph: dict, *, plan_hash: str, recipe_id: str, images: dict | None = None,
                 seed: int | None = None, parent: int | None = None, job: dict | None = None, gpu=3,
                 timeout_s: float = HV.TIMEOUT_S, wait=None) -> Take:
    errs = validate_graph(graph, images)
    if errs:
        raise ComfyError("配方图校验不通过：" + "；".join(errs))
    frames_in = HV.locked_frames(shot_id)
    wf = copy.deepcopy(graph)
    phs = placeholders(wf)
    t_up = time.monotonic()
    names = {}
    if PH_FIRST in phs:
        names[PH_FIRST] = HV.upload_once(client, P.DATA / frames_in["first"]["file"])
    if PH_LAST in phs:
        names[PH_LAST] = HV.upload_once(client, P.DATA / frames_in["last"]["file"])
    for ph in phs:
        if ph.startswith((PH_REF, PH_LOOK)):
            names[ph] = HV.upload_once(client, _safe_ref(images[ph]))
    upload_s = round(time.monotonic() - t_up, 1)
    for n in wf.values():
        if n.get("class_type") == "LoadImage" and n["inputs"].get("image") in names:
            n["inputs"]["image"] = names[n["inputs"]["image"]]
    for n in wf.values():
        if n.get("class_type") == "RandomNoise" and seed is not None:
            n["inputs"]["noise_seed"] = int(seed)
    frames = graph_frames(wf) or 0
    lane_max = HV.lane_max_frames(gpu)
    if frames > lane_max:
        raise ComfyError(f"{frames} 帧超过道 {gpu} 实测上限 {lane_max} 帧（不截短）")
    problems = client.check(wf)
    if problems:
        raise ComfyError("工作流检查不通过：" + "；".join(problems))
    with P.shot_lock(shot_id):
        n_take = P._next_n(shot_id, "video")
    d = P.shot_dir(shot_id)
    t0 = time.monotonic()
    with HV.VramSampler(client) as vram:
        pid = client.submit(wf)
        if job is not None:
            job["prompt_id"] = pid
        entry = wait(client, job, pid, max(float(timeout_s), HV.timeout_for(frames, 24))) if wait \
            else client.wait(pid, max(float(timeout_s), HV.timeout_for(frames, 24)))
    secs_run = round(time.monotonic() - t0, 1)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".mp4"))
    from ns_render.frame_edit import unique_tag
    base = f"renders/{d.relative_to(P.RENDERS).as_posix()}/takes/video_{n_take:03d}_{unique_tag(job)}"
    for i in range(3):
        try:
            client.download(item, P.DATA / f"{base}.mp4")
            break
        except ComfyError:
            if i == 2:
                raise
            time.sleep(5)
    lf = P.extract_last_frame(P.DATA / f"{base}.mp4", P.DATA / f"{base}_last.png")
    motion = MQ.video_motion(P.DATA / f"{base}.mp4")
    used_seed = next((int(n["inputs"]["noise_seed"]) for n in wf.values() if n.get("class_type") == "RandomNoise"), None)
    params = {"method": "recipe_graph", "base": f"recipe:{recipe_id}",
              "recipe": {"plan_hash": plan_hash, "recipe_id": recipe_id, "graph_sha": graph_sha(graph)},
              "seed": used_seed, "frames": frames, "seconds": round(frames / 24, 3), "gpu": gpu,
              "prompt_source": "recipe", "first": frames_in["first"],
              "last": frames_in["last"] if PH_LAST in phs else None,
              "last_frame_used": PH_LAST in phs, "lane_max_frames": lane_max,
              "ref_images": {k: v for k, v in (images or {}).items()},
              "classes": sorted({n.get("class_type") for n in graph.values()}),
              "render_s": secs_run, "upload_s": upload_s, "vram_peak_gb": vram.peak, "vram_total_gb": vram.total}
    take = Take(n=n_take, stage="video", file=f"{base}.mp4", seed=used_seed or 0, prompt=graph_prompt(wf),
                seconds=secs_run, frames=frames, created_at=P.now(), last_frame=f"{base}_last.png" if lf else None,
                workflow="recipe_graph", parent=parent, from_first=frames_in["first"]["n"], gpu=gpu,
                job_id=(job or {}).get("id"), params=params, qc={"motion": motion},
                remote=CC.remote_info(client, P.DATA / f"{base}.mp4"))
    P._add_take(shot_id, take)
    P._clear_error(shot_id)
    return take
