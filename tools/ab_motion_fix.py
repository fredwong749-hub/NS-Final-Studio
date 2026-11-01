"""
卡顿 / 慢动作 / 腿部重影 对照实验（MOT，fredw-92，2026-10-31）。

同一镜头、同 seed、同一对定稿首尾帧、同一条提示词（= 现有版本 take.prompt，剧本原文 + 系统对齐句；只给首帧时只把
第一行系统对齐句换成 I2VA 的，正文一字不改）。道上有 fp16 视频 VAE 时，同一次采样再用 fp16 解码一份
（*_fp16.mp4），所以“VAE 的影响”和“采样的影响”在同一张卡上分开。
输出只放 data/ab/motion_fix/，不写 takes.json、不定稿、不改默认。

用法：.venv/Scripts/python.exe tools/ab_motion_fix.py <镜头 S1> <配方> <道> [--take N]
配方 = 基底[+选项...]，例如 T11、PIKA+F1、B24+F1+LW08
  基底：T11 官方 Turbo 8 步 v1.1（现行）| T10 v1.0 | T13 4 步 v1.3（研究用，绕过 ≥6 步自检）|
        Bnn 不加 Turbo、基模 nn 步、shift 12/3、BasicGuider cfg 1（官方：权重 CFG 蒸馏，无 guider/negative）|
        PIKA Pika H3 Flex（config video_bases.pika_flex 原样）
  选项：F1 只给首帧 | LWxx lin_wan_h3_v1_step250 @0.xx | ABxx h3_antiburn_universal_v1 @0.xx
"""
from __future__ import annotations

import json
import re
import sys
import time
from dataclasses import replace

from ns_render import h3_video as HV
from ns_render import pipeline as P
from ns_render import workflows as W
from ns_render.comfy_client import ComfyClient
from ns_render import endpoints as EP

OUT = P.DATA / "ab" / "motion_fix"
VAE_INT8 = "minimax_h3_video_vae_int8_convrot.safetensors"
VAE_FP16 = "minimax_h3_video_vae_fp16.safetensors"
T10 = "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"
T13 = "minimax_h3_fl2v_turbo_4step_v1.3_768p_comfyui_bf16.safetensors"
ANTIBURN = "h3_antiburn_universal_v1.safetensors"
LINWAN = "lin_wan_h3_v1_step250.safetensors"


def control_take(shot: str, n: int | None) -> dict:
    tk = P.load_takes(f"ep02-{shot}")
    n = n or (tk.get("active") or {}).get("video")
    return next(t for t in tk["takes"] if t["stage"] == "video" and t["n"] == n)


def client_for(lane) -> ComfyClient:
    lane = EP.norm_lane(lane)
    c = ComfyClient(EP.url_for_gpu(lane), gpu=lane)
    if EP.server_of(lane) != EP.HOME_SERVER:
        c.server_tag = EP.server_of(lane)
    return c


def parse(recipe: str) -> dict:
    toks = recipe.split("+")
    base, opts = toks[0], toks[1:]
    r = {"base": base, "first_only": "F1" in opts, "extra": []}
    for o in opts:
        m = re.fullmatch(r"(LW|AB)(\d\d)", o)
        if m:
            r["extra"].append((LINWAN if m.group(1) == "LW" else ANTIBURN, int(m.group(2)) / 10))   # LW08 = 0.8
    return r


def model_for(base: str) -> W.H3Model:
    m0 = W.H3Model()
    if base == "T11":
        return m0
    if base == "T10":
        return replace(m0, loras=((T10, 1.0),))
    if base == "T13":
        W.H3_MIN_TURBO_STEPS = 4      # 仅本实验进程内
        return replace(m0, loras=((T13, 1.0),), steps=4)
    if re.fullmatch(r"B\d+", base):
        return replace(W.H3_BASE, steps=int(base[1:]))
    if base == "PIKA":
        return HV.base_model(HV.base_spec("pika_flex"))
    raise KeyError(base)


def graph(t: dict, r: dict, first: str, last: str | None, stem: str, fp16: bool) -> tuple[dict, str]:
    p = t["params"]
    m = model_for(r["base"])
    prompt = HV.align_first_only(t["prompt"]) if r["first_only"] else t["prompt"]
    wf = W.h3_fl2va(prompt, first, *P.VIDEO_SIZE, p["frames"], p["seed"], f"ns_ab/{stem}_int8",
                    m=replace(m, video_vae=VAE_INT8), loras=r["extra"], last_frame=None if r["first_only"] else last)
    if fp16:   # 同一次采样结果，再用 fp16 视频 VAE 解码一份（音频共用）
        wf["300"] = {"class_type": "VAELoader", "inputs": {"vae_name": VAE_FP16}}
        wf["301"] = {"class_type": "VAEDecode", "inputs": {"samples": ["125", 0], "vae": ["300", 0]}}
        wf["302"] = {"class_type": "CreateVideo", "inputs": {"images": ["301", 0], "audio": ["121", 0], "fps": m.fps}}
        wf["303"] = {"class_type": "SaveVideo", "inputs": {"video": ["302", 0],
                                                           "filename_prefix": f"ns_ab/{stem}_fp16",
                                                           "format": "mp4", "codec": "auto"}}
    return wf, prompt


def lane_has(cl, vae: str) -> bool:
    try:
        d = cl._request("/object_info/VAELoader")
        if isinstance(d, (bytes, str)):
            d = json.loads(d)
        return vae in d["VAELoader"]["input"]["required"]["vae_name"][0]
    except Exception:  # noqa: BLE001
        return False


def run(shot: str, recipe: str, lane: str, take_n: int | None = None) -> dict:
    t = control_take(shot, take_n)
    p = t["params"]
    r = parse(recipe)
    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"{shot}_{recipe.replace('+', '_')}"
    cl = client_for(lane)
    fp16 = lane_has(cl, VAE_FP16)
    first = HV.upload_once(cl, P.DATA / p["first"]["file"])
    last = None if r["first_only"] else HV.upload_once(cl, P.DATA / p["last"]["file"])
    wf, prompt = graph(t, r, first, last, stem, fp16)
    bad = cl.check(wf)
    if bad:
        raise SystemExit("工作流检查不通过：" + "；".join(bad))
    (OUT / "workflows").mkdir(exist_ok=True)
    (OUT / "workflows" / f"{stem}.json").write_text(json.dumps(wf, ensure_ascii=False, indent=1), encoding="utf-8")
    t0 = time.monotonic()
    pid = cl.submit(wf)
    print(stem, "submitted", lane, pid, "fp16" if fp16 else "int8-only", flush=True)
    entry = cl.wait(pid, HV.timeout_for(p["frames"]) * 4)
    secs = round(time.monotonic() - t0, 1)
    files = {}
    for f in cl.output_files(entry):
        if not f["filename"].endswith(".mp4"):
            continue
        tag = "fp16" if "_fp16" in f["filename"] else "int8"
        dst = OUT / "renders" / f"{stem}_{tag}.mp4"
        dst.parent.mkdir(exist_ok=True)
        cl.download(f, dst)
        files[tag] = str(dst.relative_to(P.ROOT)).replace("\\", "/")
    rec = {"shot": shot, "recipe": recipe, "parsed": r, "control_take": t["n"], "control_file": t["file"],
           "seed": p["seed"], "frames": p["frames"], "lane": lane, "prompt_id": pid, "render_s": secs,
           "files": files, "prompt_first_line": prompt.split("\n", 1)[0],
           "prompt_body_same_as_take": prompt.split("\n", 1)[-1] == t["prompt"].split("\n", 1)[-1],
           "loras": [(n["inputs"]["lora_name"], n["inputs"]["strength_model"]) for n in wf.values()
                     if n["class_type"] == "LoraLoaderModelOnly"],
           "steps": wf["124"]["inputs"].get("steps"), "sigmas": wf["124"]["inputs"].get("sigmas"),
           "shift": [wf["150"]["inputs"]["shift_video"], wf["150"]["inputs"]["shift_audio"]] if "150" in wf else None}
    (OUT / "renders" / f"{stem}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    return rec


if __name__ == "__main__":
    a = sys.argv[1:]
    tn = int(a[a.index("--take") + 1]) if "--take" in a else None
    run(a[0], a[1], a[2] if len(a) > 2 and not a[2].startswith("--") else "gpu36:1", tn)
