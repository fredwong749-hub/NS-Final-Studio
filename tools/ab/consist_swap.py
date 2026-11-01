#!/usr/bin/env python3
"""CONSIST：H3 角色替换 LoRA（后处理统一身份）实验。

把已出好的 ep02 镜头当 <Video 1>（表演 + 音轨），角色设定图的脸栏当 <Picture 1>，用 Ref2VA 重新生成同一段视频，
只换人物身份。配方照 akatz-ai/MiniMax-H3-Character-Swap-LoRA 模型卡：Ref2VA int8 底模 + character swap LoRA 1.0
+ FL2V Turbo 8step v1.0 768p 1.0、8 步、er_sde / normal、cfg 1（BasicGuider）。shift 6/3（768p Turbo 训练值，模型卡未写）。

只写 data/ab/consist_swap/，不建 take。
用法：python tools/ab/consist_swap.py --url http://127.0.0.1:28188 --video consist/S2_base24.mp4 --frames 158 \
        --picture consist/face_lin_wan_A_s101.jpg --who "the young woman with long ice-blue hair" --lora v1.5 --tag S2_v15
（--video / --picture 是 ComfyUI input 目录下的相对路径，事先放好）
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/ab/consist_swap"
LORAS = {"v1.5": "h3_character_swap_v1.5.safetensors", "pro4500": "h3_character_swap_pro4500_1000.safetensors"}
TURBO = "minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16.safetensors"

PROMPT = ("Replace {who} in <Video 1> with the character in <Picture 1>. Keep the face, facial proportions, eye shape, "
          "nose, lips, skin tone and hairstyle of the character in <Picture 1>. Keep the clothing, body, pose, motion, "
          "timing, expressions, camera movement, framing, scene, lighting, other people and soundtrack of <Video 1> unchanged. "
          "Live-action, cinematic, photorealistic.")


def api(url, path, data=None):
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": "application/json"} if data else {})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def graph(a):
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "weight_dtype": "default"}},
        "2": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["1", 0], "lora_name": LORAS[a.lora], "strength_model": a.strength}},
        "3": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["2", 0], "lora_name": TURBO, "strength_model": 1.0}},
        "4": {"class_type": "MiniMaxH3SigmaShift", "inputs": {"model": ["3", 0], "shift_video": 6.0, "shift_audio": 3.0}},
        "5": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors", "type": "minimax", "device": "default"}},
        "6": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_video_vae_int8_convrot.safetensors"}},
        "7": {"class_type": "VAELoader", "inputs": {"vae_name": "minimax_h3_audio_vae_fp32.safetensors"}},
        "8": {"class_type": "LoadVideo", "inputs": {"file": a.video}},
        "9": {"class_type": "GetVideoComponents", "inputs": {"video": ["8", 0]}},
        "10": {"class_type": "LoadImage", "inputs": {"image": a.picture}},
        # 3090 显存：参考视频截成与输出同长、缩到输出尺寸；不接参考音轨（768×1344 全长 + 音轨实测 OOM）
        "21": {"class_type": "ImageFromBatch", "inputs": {"image": ["9", 0], "batch_index": 0, "length": a.frames}},
        "22": {"class_type": "ImageScale", "inputs": {"image": ["21", 0], "upscale_method": "lanczos", "width": a.width,
                                                      "height": a.height, "crop": "center"}},
        "11": {"class_type": "MiniMaxH3ReferenceToVideo",
               "inputs": {"clip": ["5", 0], "prompt": PROMPT.format(who=a.who), "width": a.width, "height": a.height, "length": a.frames,
                          "ref_image_size": "match", "vae": ["6", 0], "audio_vae": ["7", 0],
                          "ref_images.ref_image_0": ["10", 0], "ref_videos.ref_video_0": ["22", 0]}},
        "12": {"class_type": "BasicGuider", "inputs": {"model": ["4", 0], "conditioning": ["11", 0]}},
        "13": {"class_type": "RandomNoise", "inputs": {"noise_seed": a.seed}},
        "14": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "er_sde"}},
        "15": {"class_type": "BasicScheduler", "inputs": {"model": ["4", 0], "scheduler": "normal", "steps": a.steps, "denoise": 1.0}},
        "16": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["13", 0], "guider": ["12", 0], "sampler": ["14", 0],
                                                                 "sigmas": ["15", 0], "latent_image": ["11", 1]}},
        "17": {"class_type": "VAEDecode", "inputs": {"samples": ["16", 0], "vae": ["6", 0]}},
        "18": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["16", 0], "vae": ["7", 0]}},
        "19": {"class_type": "CreateVideo", "inputs": {"images": ["17", 0], "audio": ["18", 0], "fps": 24.0}},
        "20": {"class_type": "SaveVideo", "inputs": {"video": ["19", 0], "filename_prefix": f"consist_swap/{a.tag}", "format": "mp4", "codec": "auto"}},
    }
    return g


def _ns_tag(**kw):
    """GPU 任务归属标签（K-OPS-G01，放 extra_data.ns_tag）；导入/构造出错返回 None（照常提交，不带标签）"""
    try:
        import sys
        sp = str(ROOT / "services" / "agent")
        if sp not in sys.path:
            sys.path.append(sp)
        from ns_agent import comfy_tag as CT
        return CT.make("CONSIST", **kw)
    except Exception:  # noqa: BLE001
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--video", required=True)
    ap.add_argument("--picture", required=True)
    ap.add_argument("--frames", type=int, required=True)
    ap.add_argument("--who", required=True)
    ap.add_argument("--lora", choices=list(LORAS), default="v1.5")
    ap.add_argument("--strength", type=float, default=1.0)
    ap.add_argument("--steps", type=int, default=8)
    ap.add_argument("--width", type=int, default=544, help="768×1344×192 帧 + 参考视频在 3090 上 OOM（实测 20.2+5.0 GB），默认降到 544×960")
    ap.add_argument("--height", type=int, default=960)
    ap.add_argument("--seed", type=int, default=20261031)
    ap.add_argument("--tag", required=True)
    ap.add_argument("--no-download", action="store_true", help="只在 gpu33 输出目录留文件（隧道慢时）")
    a = ap.parse_args()
    g = graph(a)
    body = {"prompt": g, "client_id": "consist"}
    t = _ns_tag(kind="video", obj=a.who, label=f"换脸一致性 {a.lora} · {a.tag}", job=a.tag)
    if t:
        body["extra_data"] = {"ns_tag": t}
    pid = json.loads(api(a.url, "/prompt", json.dumps(body).encode()))["prompt_id"]
    t0 = time.time()
    print("queued", pid, flush=True)
    while True:
        time.sleep(15)
        h = json.loads(api(a.url, f"/history/{pid}"))
        if pid not in h:
            continue
        st = h[pid].get("status", {})
        if st.get("status_str") == "error":
            print("ERROR", json.dumps(st)[:1500], flush=True)
            return
        files = [f for n in h[pid]["outputs"].values() for f in (n.get("images", []) + n.get("videos", []) + n.get("gifs", []))]
        rec = {"t": time.strftime("%F %T"), "tag": a.tag, "args": vars(a), "prompt": g["11"]["inputs"]["prompt"],
               "wall_s": round(time.time() - t0), "outputs": files}
        OUT.mkdir(parents=True, exist_ok=True)
        with open(OUT / "runs.jsonl", "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print("DONE", a.tag, rec["wall_s"], files, flush=True)
        return


if __name__ == "__main__":
    main()
