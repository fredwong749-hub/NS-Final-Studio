"""P0 冒烟（总调度 11-02：Detailer、DWPose、Fun CN int8 各出 1 张非成人镜，结果给总调度亲审后才进 A/B）。
scope=ab：图只进 data/ab/imglab/smoke/，不写 takes / 账本。模型链与生产 frame_v9 同一套文件（UNET turbo int8 + krea2 0.5、qwen3vl 8b、texture_fix VAE）。

    .venv/Scripts/python.exe tools/imglab/smoke.py detailer --shot ep01-S1 --image data/renders/ep01/S1/takes/image_018_3d284048_raw_post.png
    .venv/Scripts/python.exe tools/imglab/smoke.py dwpose   --image data/renders/ep01/S5/takes/image_013_4429d20a_raw_post.png
    （Fun CN 冒烟用 tools/imglab/ab.py run --round smoke --shots ep03-S1 --arms A0,P10 --seeds job）
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/imglab"))
import ab as AB  # noqa: E402

OUT = ROOT / "data/ab/imglab/smoke"

DETAIL = {"guide_size": 768, "guide_size_for": True, "max_size": 1024, "steps": 8, "cfg": 1.0, "sampler_name": "euler",
          "scheduler": "simple", "denoise": 0.35, "feather": 10, "noise_mask": True, "force_inpaint": True,
          "bbox_threshold": 0.4, "bbox_dilation": 10, "bbox_crop_factor": 2.5, "sam_detection_hint": "center-1", "sam_dilation": 0,
          "sam_threshold": 0.93, "sam_bbox_expansion": 0, "sam_mask_hint_threshold": 0.7, "sam_mask_hint_use_negative": "False",
          "drop_size": 10, "wildcard": "", "cycle": 1, "inpaint_model": False, "noise_mask_feather": 20}


def _base(img_name: str, prompt: str) -> dict:
    return {
        "10": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_turbo_int8_convrot.safetensors", "weight_dtype": "default"}},
        "60": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["10", 0], "lora_name": "krea2_film_texture_qwen21.safetensors", "strength_model": 0.5}},
        "11": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"}},
        "20": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["11", 0], "prompt": prompt, "negative_prompt": "", "resolution": 0, "vae": ["12", 0]}},
        "1": {"class_type": "LoadImage", "inputs": {"image": img_name}},
    }


def detailer_graph(img_name: str, prompt: str, seed: int, prefix: str) -> dict:
    g = _base(img_name, prompt)
    g["30"] = {"class_type": "UltralyticsDetectorProvider", "inputs": {"model_name": "bbox/hand_yolov9c.pt"}}
    g["31"] = {"class_type": "UltralyticsDetectorProvider", "inputs": {"model_name": "bbox/face_yolov8m.pt"}}
    common = {"model": ["60", 0], "clip": ["11", 0], "vae": ["12", 0], "positive": ["20", 0], "negative": ["20", 1], "seed": seed, **DETAIL}
    g["40"] = {"class_type": "FaceDetailer", "inputs": {"image": ["1", 0], "bbox_detector": ["30", 0], **common}}       # 手
    g["41"] = {"class_type": "FaceDetailer", "inputs": {"image": ["40", 0], "bbox_detector": ["31", 0], **common}}      # 脸
    g["90"] = {"class_type": "SaveImage", "inputs": {"images": ["41", 0], "filename_prefix": prefix}}
    g["91"] = {"class_type": "SaveImage", "inputs": {"images": ["40", 0], "filename_prefix": prefix + "_handonly"}}
    return g


def dwpose_graph(img_name: str, prefix: str) -> dict:
    return {"1": {"class_type": "LoadImage", "inputs": {"image": img_name}},
            "2": {"class_type": "DWPreprocessor", "inputs": {"image": ["1", 0], "detect_hand": "enable", "detect_body": "enable",
                                                              "detect_face": "enable", "resolution": 1024, "bbox_detector": "yolox_l.onnx",
                                                              "pose_estimator": "dw-ll_ucoco_384.onnx", "scale_stick_for_xinsr_cn": "disable"}},
            "90": {"class_type": "SaveImage", "inputs": {"images": ["2", 0], "filename_prefix": prefix}}}


def submit(graph: dict, url: str, tag: str) -> list[Path]:
    from ns_render.comfy_client import ComfyClient
    client = ComfyClient(url)
    entry, secs = client.run(graph, timeout_s=1800)
    OUT.mkdir(parents=True, exist_ok=True)
    outs = []
    for i, item in enumerate(f for f in client.output_files(entry) if f["filename"].endswith(".png")):
        dest = OUT / f"{tag}_{i}_{item['filename']}"
        client.download(item, dest)
        outs.append(dest)
    rec = {"tag": tag, "lane": url, "secs": round(secs, 1), "files": [p.relative_to(ROOT).as_posix() for p in outs],
           "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    with (OUT / "smoke.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    return outs


def main(argv=None) -> int:
    from ns_render.comfy_client import ComfyClient
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["detailer", "dwpose"])
    ap.add_argument("--image", required=True)
    ap.add_argument("--shot", default="")
    ap.add_argument("--lane", default="http://127.0.0.1:18189")
    a = ap.parse_args(argv)
    if a.shot and AB.is_adult(a.shot):
        raise SystemExit(f"{a.shot} 单镜判定为成人镜头，不出")
    client = ComfyClient(a.lane)
    name = client.upload_image(ROOT / a.image, subfolder="ns_ab/imglab")
    st: dict = {}
    while not AB.lane_idle(a.lane, 60, st):      # 不抢生产：整条道空闲 ≥ 60 s 才交
        time.sleep(5)
    if a.cmd == "detailer":
        job = AB.load_job(a.shot)
        prompt = job["prompt"].split("。", 3)[-1] if job["prompt"].startswith("图1") else job["prompt"]
        submit(detailer_graph(name, prompt, int(job["seed"]), f"ns_ab/imglab/smoke/{a.shot}_detailer"), a.lane, f"{a.shot}_detailer")
    else:
        submit(dwpose_graph(name, "ns_ab/imglab/smoke/dwpose"), a.lane, "dwpose")
    return 0


if __name__ == "__main__":
    sys.exit(main())
