"""
LAB（2026-10-31）：项目方工作流「Realistic AI Video MiniMax H3」（data/ab/owner_workflows/）的 API 版，直接提交 ComfyUI。
ref2va（参考图 = 角色定妆图，不是首帧）+ 20 步 euler/simple，SplitSigmas@10：前 10 步低分辨率 → 分离 AV latent →
MinimaxH3LatentUpscaler3D 放大到目标尺寸 → 合并 → 后 10 步全尺寸精修。BasicGuider（无 CFG），SigmaShift 12/3，
ModelAttentionBackend comfy kitchen attention。

和项目方原图一致的地方：节点、步数、split、guider、VAE（fp16 视频 / fp32 音频）、CLIP、ref_image_size match。
项目方原图的 BasicScheduler 接的是未 shift 的 UNET（link 73）——默认照原图（--sched-shifted 可改成接 shift 后的模型）。
放大器：项目方用 minimax_h3_latent_upscaler_3d_fp16 / megapixels 1.4；gpu33 上只有 *_conv_v1_bf16，用 target dimensions
直接放到 768×1344（竖屏 9:16），首段 = 目标的 lo_scale（默认 0.71 ≈ 0.5 MP，与原图 0.5→1.4 MP 同比例）。

产物只放 data/ab/lab_ref2va/，不写 takes、不定稿。

用法：.venv/Scripts/python.exe tools/lab_ep02/ref2va_run.py <name> <lane url> <seed> <seconds> <prompt.txt> <ref1.png> [ref2 ...]
       [--steps 20] [--split 10] [--lo-scale 0.71] [--sched-shifted] [--attn pytorch] [--audio ref.wav]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "render_router"))
from ns_render.comfy_client import ComfyClient  # noqa: E402

OUT = ROOT / "data" / "ab" / "lab_ref2va"
W, H = 768, 1344


def frames_for(sec: float) -> int:
    a = max(5, round(sec * 24))
    return a + (5 - a % 17) % 17


def a32(x: float) -> int:
    return max(32, int(round(x / 32)) * 32)


def build(prompt, refs, frames, seed, prefix, steps, split, lo_scale, sched_shifted, attn, upscaler, audios=(),
          single=False, guide=None):
    """single：一段全尺寸采样（不 split / 不放大）；guide：首帧图名 → MiniMaxH3AddGuide frame 0（E5 multiframe）"""
    lw, lh = (W, H) if single else (a32(W * lo_scale), a32(H * lo_scale))
    wf = {
        "74": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
                                                      "weight_dtype": "default"}},
        "57": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors",
                                                      "type": "minimax", "device": "default"}},
        "58": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_fp16.safetensors"}},
        "59": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "61": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["74", 0], "shift_video": 12.0, "shift_audio": 3.0}},
        "76": {"class_type": "ModelAttentionBackend", "inputs": {"model": ["61", 0], "attention": attn}},
        "60": {"class_type": "MiniMaxH3ReferenceToVideo",
               "inputs": {"clip": ["57", 0], "vae": ["58", 0], "audio_vae": ["59", 0], "prompt": prompt,
                          "width": lw, "height": lh, "length": frames, "ref_image_size": "match"}},
        "62": {"class_type": "BasicGuider", "inputs": {"model": ["76", 0], "conditioning": ["60", 0]}},
        "63": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "64": {"class_type": "BasicScheduler", "inputs": {"model": ["61", 0] if sched_shifted else ["74", 0],
                                                          "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "65": {"class_type": "SplitSigmas", "inputs": {"sigmas": ["64", 0], "step": split}},
        "77": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "69": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["77", 0], "guider": ["62", 0], "sampler": ["63", 0], "sigmas": ["65", 0],
                          "latent_image": ["60", 1]}},
        "72": {"class_type": "LTXVSeparateAVLatent", "inputs": {"av_latent": ["69", 1]}},
        "80": {"class_type": "MinimaxH3LatentUpscaler3D",
               "inputs": {"latent": ["72", 0], "model_name": upscaler, "mode": "target dimensions",
                          "mode.width": W, "mode.height": H, "align": 32, "enable_temporal_chunking": True,
                          "force_unload": True, "device": "cuda", "precision": "fp16"}},
        "73": {"class_type": "LTXVConcatAVLatent", "inputs": {"video_latent": ["80", 0], "audio_latent": ["72", 1]}},
        "75": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["77", 0], "guider": ["62", 0], "sampler": ["63", 0], "sigmas": ["65", 1],
                          "latent_image": ["73", 0]}},
        "78": {"class_type": "VAEDecode", "inputs": {"samples": ["75", 0], "vae": ["58", 0]}},
        "70": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["75", 0], "vae": ["59", 0]}},
        "130": {"class_type": "CreateVideo", "inputs": {"images": ["78", 0], "audio": ["70", 0], "fps": 24.0}},
        "92": {"class_type": "SaveVideo", "inputs": {"video": ["130", 0], "filename_prefix": prefix,
                                                     "format": "mp4", "codec": "auto"}},
    }
    for i, name in enumerate(refs):
        wf[f"56{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        wf["60"]["inputs"][f"ref_images.ref_image_{i}"] = [f"56{i}", 0]
    for i, name in enumerate(audios):
        wf[f"57{i}"] = {"class_type": "LoadAudio", "inputs": {"audio": name}}
        wf["60"]["inputs"][f"ref_audios.ref_audio_{i}"] = [f"57{i}", 0]
    if guide:
        wf["590"] = {"class_type": "LoadImage", "inputs": {"image": guide}}
        wf["591"] = {"class_type": "ImageScale", "inputs": {"image": ["590", 0], "upscale_method": "lanczos",
                                                             "width": lw, "height": lh, "crop": "center"}}
        wf["592"] = {"class_type": "MiniMaxH3AddGuide", "inputs": {"positive": ["60", 0], "latent": ["60", 1],
                                                                   "frame_idx": 0, "vae": ["58", 0], "image": ["591", 0]}}
        wf["62"]["inputs"]["conditioning"] = ["592", 0]
    if single:
        wf["69"]["inputs"]["sigmas"] = ["64", 0]
        for k in ("65", "72", "80", "73", "75"):
            wf.pop(k)
        wf["78"]["inputs"]["samples"] = ["69", 0]
        wf["70"]["inputs"]["samples"] = ["69", 0]
    return wf, (lw, lh)


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("name"); ap.add_argument("url"); ap.add_argument("seed", type=int); ap.add_argument("seconds", type=float)
    ap.add_argument("prompt"); ap.add_argument("refs", nargs="+")
    ap.add_argument("--steps", type=int, default=20); ap.add_argument("--split", type=int, default=10)
    ap.add_argument("--lo-scale", type=float, default=0.71); ap.add_argument("--sched-shifted", action="store_true")
    ap.add_argument("--attn", default="comfy kitchen attention")
    ap.add_argument("--upscaler", default="minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors")
    ap.add_argument("--dry", action="store_true")
    ap.add_argument("--audio", action="append", default=[])
    ap.add_argument("--single", action="store_true")
    ap.add_argument("--guide", default=None)
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    c = ComfyClient(a.url, timeout=120)
    prompt = Path(a.prompt).read_text(encoding="utf-8").strip()
    refs = [c.upload_image(Path(r), "ns_final/lab_ref2va", remote=False) for r in a.refs]
    auds = [c.upload_image(Path(x), "", remote=False) for x in a.audio]
    gname = c.upload_image(Path(a.guide), "ns_final/lab_ref2va", remote=False) if a.guide else None
    frames = frames_for(a.seconds)
    wf, lo = build(prompt, refs, frames, a.seed, f"lab_ref2va/{a.name}", a.steps, a.split, a.lo_scale,
                   a.sched_shifted, a.attn, a.upscaler, auds, a.single, gname)
    meta = {"name": a.name, "lane": a.url, "seed": a.seed, "seconds": a.seconds, "frames": frames, "lo_res": lo,
            "target": [W, H], "steps": a.steps, "split": a.split, "sched_shifted": a.sched_shifted, "attn": a.attn,
            "upscaler": a.upscaler, "refs": a.refs, "audios": a.audio, "single": a.single, "guide": a.guide, "prompt_file": a.prompt, "tag": "LAB",
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    (OUT / f"{a.name}.json").write_text(json.dumps({**meta, "workflow": wf}, ensure_ascii=False, indent=1), encoding="utf-8")
    if a.dry:
        print(json.dumps(meta, ensure_ascii=False)); return
    t0 = time.monotonic()
    pid = c.submit(wf)
    print("submitted", a.name, pid, flush=True)
    while True:   # 隧道抖动：重连等待，不重渲
        try:
            entry = c.wait(pid, 4 * 3600)
            break
        except Exception as e:  # noqa: BLE001
            if "timed out" not in str(e) and "refused" not in str(e) and "10061" not in str(e) and "Unavailable" not in type(e).__name__:
                raise
            print("retry wait", str(e)[:100], flush=True)
            time.sleep(30)
    dt = round(time.monotonic() - t0, 1)
    item = next(f for f in c.output_files(entry) if f["filename"].endswith(".mp4"))
    dest = OUT / f"{a.name}.mp4"
    c.download(item, dest)
    meta.update(render_s=dt, file=str(dest.relative_to(ROOT)).replace("\\", "/"), prompt_id=pid)
    (OUT / f"{a.name}.json").write_text(json.dumps({**meta, "workflow": wf}, ensure_ascii=False, indent=1), encoding="utf-8")
    print("done", a.name, dt, dest, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
