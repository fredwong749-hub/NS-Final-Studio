"""
PLANB（ep02 双方案对打·方案 B，2026-10-31）：保住定稿首帧构图的两段式路线，直接提交 gpu36 的 ComfyUI。

配方 pdd2（默认）：
  UNET fl2va_pruned_int8 → MiniMaxH3PDDAccApply(FL2VA-Acc-8Step, nfe 8, 1.0/1.0) → SigmaShift 12/3 → kitchen attention
  第一段：I2VA（只给定稿首帧）544×960，PDD σ 表前 4 步（1 → .923），euler，BasicGuider
  → LTXVSeparateAVLatent → MinimaxH3LatentUpscaler3D(conv_v1_fp16, target 768×1344) → LTXVConcatAVLatent
  第二段：同一首帧在 768×1344 重新编码条件，PDD σ 表后 4 步（.923 → 0），euler
配方 base2：无 PDD，基模 24 步 simple，SplitSigmas@12（σ .923），其余同上（给没加载 PDD 节点的道用）。
FaceRefine（--refine，同一张图里）：解码 → H3FaceTrackCrop(face_yolov8m, crop 2.5, 768×768, identity_track 关)
  → I2V 条件（无首帧，画布 = 裁切尺寸）+ H3InjectVideoLatent → fl2va 基模（不挂 PDD）12/3，
  BasicScheduler simple 10 步 denoise 0.42 → H3FaceStitch(face_only, 24/24, colour_match 1) → 另存 _fr。
  音频一律用主生成的音轨。

产物：data/ab/planB/ep02/<镜>/<name>.mp4（+ _fr.mp4）+ <name>.json（图、提示词、GPU 秒 = ComfyUI execution_start→success）。
不写 takes、不定稿。

用法：.venv/Scripts/python.exe tools/lab_ep02/planb_run.py <name> <url> <shot S1> [--seed 20261101] [--recipe pdd2|base2]
        [--refine] [--refine-denoise 0.42] [--prompt-file p.txt] [--last] [--lo 544x960] [--size 768x1344] [--attn ...]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "render_router"))
from ns_render import h3_video as HV  # noqa: E402
from ns_render import pipeline as P  # noqa: E402
from ns_render.comfy_client import ComfyClient  # noqa: E402

OUT = ROOT / "data" / "ab" / "planB" / "ep02"
UNET = "minimax_h3_fl2va_pruned_int8_convrot.safetensors"
CLIP = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
VVAE = "minimax_h3_video_vae_int8_convrot.safetensors"
AVAE = "minimax_h3_audio_vae_fp32.safetensors"
UPS = "minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors"
PDD = "MiniMax-H3-FL2VA-Acc-8Step.safetensors"


def wh(s: str) -> tuple[int, int]:
    w, h = (int(v) for v in s.lower().split("x"))
    return w, h


def build(prompt, first, last, frames, seed, prefix, *, recipe, lo, size, attn, refine, refine_denoise,
          refine_steps, base_steps=24, base_split=12, sampler="euler", loras=()):
    W, H = size
    lw, lh = lo
    wf = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "minimax", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VVAE}},
        "4": {"class_type": "VAELoader", "inputs": {"vae_name": AVAE}},
        "10": {"class_type": "LoadImage", "inputs": {"image": first}},
        "11": {"class_type": "ImageScale", "inputs": {"image": ["10", 0], "upscale_method": "lanczos",
                                                      "width": lw, "height": lh, "crop": "center"}},
        "12": {"class_type": "ImageScale", "inputs": {"image": ["10", 0], "upscale_method": "lanczos",
                                                      "width": W, "height": H, "crop": "center"}},
        "20": {"class_type": "MiniMaxH3ImageToVideo",
               "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": prompt, "width": lw, "height": lh,
                          "length": frames, "first_frame": ["11", 0]}},
        "21": {"class_type": "MiniMaxH3ImageToVideo",
               "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": prompt, "width": W, "height": H,
                          "length": frames, "first_frame": ["12", 0]}},
        "32": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "33": {"class_type": "ModelAttentionBackend", "inputs": {"model": ["32", 0], "attention": attn}},
        "40": {"class_type": "BasicGuider", "inputs": {"model": ["33", 0], "conditioning": ["20", 0]}},
        "41": {"class_type": "BasicGuider", "inputs": {"model": ["33", 0], "conditioning": ["21", 0]}},
        "42": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": sampler}},
        "43": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "50": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["43", 0], "guider": ["40", 0], "sampler": ["42", 0], "sigmas": ["45", 0],
                          "latent_image": ["20", 1]}},
        "51": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["50", 1]}},
        "52": {"class_type": "MinimaxH3LatentUpscaler3D",
               "inputs": {"latent": ["51", 0], "model_name": UPS, "mode": "target dimensions",
                          "mode.width": W, "mode.height": H, "align": 32, "enable_temporal_chunking": True,
                          "force_unload": True, "device": "cuda", "precision": "fp16"}},
        "53": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["52", 0], "audio_latent": ["51", 1]}},
        "54": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["43", 0], "guider": ["41", 0], "sampler": ["42", 0], "sigmas": ["45", 1],
                          "latent_image": ["53", 0]}},
        "60": {"class_type": "VAEDecode", "inputs": {"samples": ["54", 0], "vae": ["3", 0]}},
        "61": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["54", 0], "vae": ["4", 0]}},
        "62": {"class_type": "CreateVideo", "inputs": {"images": ["60", 0], "audio": ["61", 0], "fps": 24.0}},
        "63": {"class_type": "SaveVideo", "inputs": {"video": ["62", 0], "filename_prefix": prefix,
                                                     "format": "mp4", "codec": "auto"}},
    }
    if last:
        wf["13"] = {"class_type": "LoadImage", "inputs": {"image": last}}
        wf["14"] = {"class_type": "ImageScale", "inputs": {"image": ["13", 0], "upscale_method": "lanczos",
                                                           "width": lw, "height": lh, "crop": "center"}}
        wf["15"] = {"class_type": "ImageScale", "inputs": {"image": ["13", 0], "upscale_method": "lanczos",
                                                           "width": W, "height": H, "crop": "center"}}
        wf["20"]["inputs"]["last_frame"] = ["14", 0]
        wf["21"]["inputs"]["last_frame"] = ["15", 0]
    if recipe == "pdd2":
        wf["30"] = {"class_type": "MiniMaxH3PDDAccApply",
                    "inputs": {"model": ["1", 0], "pdd_file": PDD, "nfe": "8", "lora_strength": 1.0,
                               "head_strength": 1.0, "on_off_grid": "error"}}
        wf["32"]["inputs"]["model"] = ["30", 0]
        wf["45"] = {"class_type": "SplitSigmas", "inputs": {"sigmas": ["30", 1], "step": 4}}     # σ .923
    elif recipe == "base1":   # 单段全尺寸基模（对照用；不放大）
        wf["44"] = {"class_type": "BasicScheduler", "inputs": {"model": ["32", 0], "scheduler": "simple",
                                                               "steps": base_steps, "denoise": 1.0}}
        wf["50"]["inputs"].update(guider=["41", 0], sigmas=["44", 0], latent_image=["21", 1])
        for k in ("20", "11", "40", "51", "52", "53", "54"):
            wf.pop(k)
        wf["60"]["inputs"]["samples"] = ["50", 0]
        wf["61"]["inputs"]["samples"] = ["50", 0]
        wf.pop("14", None)
        if "21" in wf and "last_frame" in wf["21"]["inputs"]:
            pass
    else:   # base2
        wf["44"] = {"class_type": "BasicScheduler", "inputs": {"model": ["32", 0], "scheduler": "simple",
                                                               "steps": base_steps, "denoise": 1.0}}
        wf["45"] = {"class_type": "SplitSigmas", "inputs": {"sigmas": ["44", 0], "step": base_split}}
    src = ["1", 0]
    for i, (ln, st) in enumerate(loras):
        wf[f"9{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": src, "lora_name": ln, "strength_model": st}}
        src = [f"9{i}", 0]
    if loras:
        if recipe == "pdd2":
            wf["30"]["inputs"]["model"] = src
        else:
            wf["32"]["inputs"]["model"] = src
    if refine:
        wf.update({
            "70": {"class_type": "H3FaceTrackCrop",
                   "inputs": {"images": ["60", 0], "detector": "face_yolov8m.pt", "confidence": 0.35, "crop_factor": 2.5,
                              "canvas_width": 768, "canvas_height": 768, "canvas_mode": "manual", "smooth_window": 21,
                              "size_smooth_window": 51, "smooth_method": "gaussian", "size_mode": "per_frame",
                              "identity_track": False, "select": "largest_face", "fallback_detector": "none",
                              "identity_model": "insightface", "cut_detection": "none", "absent_shots": "off"}},
            "71": {"class_type": "MiniMaxH3ImageToVideo",
                   "inputs": {"clip": ["2", 0], "vae": ["3", 0], "prompt": prompt, "width": ["70", 4],
                              "height": ["70", 5], "length": ["70", 6]}},
            "72": {"class_type": "H3InjectVideoLatent", "inputs": {"av_latent": ["71", 1], "images": ["70", 0],
                                                                   "vae": ["3", 0]}},
            "73": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["1", 0], "shift_video": 12.0, "shift_audio": 3.0}},
            "74": {"class_type": "ModelAttentionBackend", "inputs": {"model": ["73", 0], "attention": attn}},
            "75": {"class_type": "BasicGuider", "inputs": {"model": ["74", 0], "conditioning": ["71", 0]}},
            "76": {"class_type": "BasicScheduler", "inputs": {"model": ["74", 0], "scheduler": "simple",
                                                              "steps": refine_steps, "denoise": refine_denoise}},
            "77": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed + 7}},
            "78": {"class_type": "SamplerCustomAdvanced",
                   "inputs": {"noise": ["77", 0], "guider": ["75", 0], "sampler": ["42", 0], "sigmas": ["76", 0],
                              "latent_image": ["72", 0]}},
            "79": {"class_type": "VAEDecode", "inputs": {"samples": ["78", 0], "vae": ["3", 0]}},
            "80": {"class_type": "H3FaceStitch",
                   "inputs": {"base_images": ["60", 0], "refined_crops": ["79", 0], "transform": ["70", 1],
                              "paste_region": "face_only", "mask_dilation": 24, "feather": 24, "colour_match": 1.0,
                              "blend": 1.0, "undetected_frames": "fade_out"}},
            "81": {"class_type": "CreateVideo", "inputs": {"images": ["80", 0], "audio": ["61", 0], "fps": 24.0}},
            "82": {"class_type": "SaveVideo", "inputs": {"video": ["81", 0], "filename_prefix": prefix + "_fr",
                                                         "format": "mp4", "codec": "auto"}},
        })
    return wf


def gpu_seconds(entry: dict) -> float | None:
    ts = {}
    for kind, d in (entry.get("status") or {}).get("messages") or []:
        if isinstance(d, dict) and "timestamp" in d:
            ts[kind] = d["timestamp"]
    if "execution_start" in ts and ("execution_success" in ts or "execution_error" in ts):
        end = ts.get("execution_success", ts.get("execution_error"))
        return round((end - ts["execution_start"]) / 1000.0, 1)
    return None


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("name"); ap.add_argument("url"); ap.add_argument("shot")
    ap.add_argument("--seed", type=int, default=20261101)
    ap.add_argument("--recipe", default="pdd2", choices=("pdd2", "base2", "base1"))
    ap.add_argument("--lora", action="append", default=[], help="name:strength（挂在 UNET 后、PDD/shift 前；修脸那段不挂）")
    ap.add_argument("--refine", action="store_true")
    ap.add_argument("--refine-denoise", type=float, default=0.42)
    ap.add_argument("--refine-steps", type=int, default=10)
    ap.add_argument("--prompt-file", default=None)
    ap.add_argument("--last", action="store_true", help="FL2VA：同时给定稿尾帧")
    ap.add_argument("--lo", default="544x960"); ap.add_argument("--size", default="768x1344")
    ap.add_argument("--attn", default="comfy kitchen attention")
    ap.add_argument("--base-steps", type=int, default=24); ap.add_argument("--base-split", type=int, default=12)
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--fetch", default=None, help="已提交的 prompt_id：只等待并取回（隧道/等待进程断了时用）")
    a = ap.parse_args(argv)
    sid = f"ep02-{a.shot}"
    out = OUT / a.shot
    out.mkdir(parents=True, exist_ok=True)
    frames_in = HV.locked_frames(sid)
    secs = HV.shot_seconds(P.load_script(), sid)
    frames = HV.frames_for(secs)[0]
    if a.prompt_file:
        raw = Path(a.prompt_file).read_text(encoding="utf-8").strip()
        prompt_src = a.prompt_file
    else:
        raw = json.loads((P.DATA / f"renders/ep02/{a.shot}/compiled.json").read_text(encoding="utf-8"))["video_prompt"]
        prompt_src = f"data/renders/ep02/{a.shot}/compiled.json"
    prompt, removed = (HV.realign(raw, frames), []) if a.last else HV.i2v_prompt(HV.realign(raw, frames))
    c = ComfyClient(a.url, timeout=900)
    first = c.upload_image(HV.keyframe_file(P.DATA / frames_in["first"]["file"]), "ns_final/planB", remote=False)
    last = (c.upload_image(HV.keyframe_file(P.DATA / frames_in["last"]["file"]), "ns_final/planB", remote=False)
            if a.last else None)
    wf = build(prompt, first, last, frames, a.seed, f"planB/{a.shot}/{a.name}", recipe=a.recipe, lo=wh(a.lo),
               size=wh(a.size), attn=a.attn, refine=a.refine, refine_denoise=a.refine_denoise,
               refine_steps=a.refine_steps, base_steps=a.base_steps, base_split=a.base_split,
               loras=[(x.rsplit(":", 1)[0], float(x.rsplit(":", 1)[1])) for x in a.lora])
    meta = {"name": a.name, "shot": sid, "url": a.url, "seed": a.seed, "recipe": a.recipe, "refine": a.refine,
            "refine_denoise": a.refine_denoise, "refine_steps": a.refine_steps, "lo": a.lo, "size": a.size,
            "attn": a.attn, "last": a.last, "loras": a.lora, "frames": frames, "seconds": secs, "first": frames_in["first"],
            "prompt_src": prompt_src, "prompt_removed": removed, "tag": "PLANB",
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    mj = out / f"{a.name}.json"
    mj.write_text(json.dumps({**meta, "prompt": prompt, "workflow": wf}, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.dry:
        print(json.dumps(meta, ensure_ascii=False)); return
    t0 = time.monotonic()
    if a.fetch:
        old = json.loads(mj.read_text(encoding="utf-8")) if mj.exists() else {}
        pid = a.fetch
        meta["started"] = old.get("started", meta["started"])
    else:
        pid = c.submit(wf)
    meta["prompt_id"] = pid
    print("submitted", a.name, pid, flush=True)
    mj.write_text(json.dumps({**meta, "prompt": prompt, "workflow": wf}, ensure_ascii=False, indent=1), encoding="utf-8")
    while True:   # 隧道抖动：重连等待，不重渲
        try:
            entry = c.wait(pid, 6 * 3600)
            break
        except Exception as e:  # noqa: BLE001
            if "timed out" not in str(e) and "refused" not in str(e) and "10061" not in str(e) \
                    and "Unavailable" not in type(e).__name__ and "reset" not in str(e).lower():
                raise
            print("retry wait", str(e)[:100], flush=True)
            time.sleep(30)
    files = [f for f in c.output_files(entry) if f["filename"].endswith(".mp4")]
    got = {}
    for f in files:
        key = "fr" if "_fr" in f["filename"] else "raw"
        dest = out / (f"{a.name}_fr.mp4" if key == "fr" else f"{a.name}.mp4")
        c.download(f, dest)
        got[key] = str(dest.relative_to(ROOT)).replace("\\", "/")
    meta.update(wall_s=round(time.monotonic() - t0, 1), gpu_s=gpu_seconds(entry), files=got,
                finished=time.strftime("%Y-%m-%d %H:%M:%S"))
    mj.write_text(json.dumps({**meta, "prompt": prompt, "workflow": wf}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", a.name, "gpu_s", meta["gpu_s"], got, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
