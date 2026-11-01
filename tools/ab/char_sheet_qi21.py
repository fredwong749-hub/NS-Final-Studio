#!/usr/bin/env python3
"""CONSIST：用项目方给的 Qwen-Image 2.1 角色设定图工作流（data/ab/owner_workflows/aisley_char_sheet）
出林晚 / 顾沉 / 陈宇四栏设定图候选，以及以设定图为 <image1> 的 ep02 首帧对照版。

只出候选到 data/ab/char_sheets/，不改定妆、不改 config。
参数与项目方工作流一致：qwen_image_2.1_int8_convrot + QI2.1_AnyAngle 0.6、qwen3vl_8b_int8_convrot(qwen_image)、
TextEncodeQwenImage21(resolution 2048)、qwen_image_2.1_vae_bf16、KSampler 25 步 cfg 1 euler simple。

用法：python tools/ab/char_sheet_qi21.py sheets  --url http://127.0.0.1:18188
      python tools/ab/char_sheet_qi21.py frames  --url ... --sheet lin_wan=path --sheet gu_chen=path --shots S2,S4
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/ab/char_sheets"
WF_DIR = ROOT / "data/ab/owner_workflows/aisley_char_sheet"
POSE = WF_DIR / "character_sheet_pose.png"

# 项目方 Prompt.txt 第二种模板（角色图 + 姿势模板），原文照用
P_CHAR_POSE = (WF_DIR / "Prompt.txt").read_text(encoding="utf-8").split("[Character Image + Pose Image]")[1].split("-----")[0].strip()

# 人物外貌只取 data/ab/char_fix/registry_draft.md 草稿的“人物表行”原文；服装取 ep02 剧本首帧提示词里的原词
REGISTRY = {
    "gu_chen": "a 34-year-old East Asian man with short black hair, a composed handsome face, fair skin and a broad-shouldered build",
    "chen_yu": "a 23-year-old East Asian man with short black hair, a warm open face, fair skin and a lean build",
}
OUTFIT = {"gu_chen": "a black tailored dress shirt and black trousers (黑色高定衬衫)",
          "chen_yu": "casual clothes (休闲装)"}

# 无参考图的男角色：只给姿势模板做 <image1>，外貌由文字给出
P_TEXT_POSE = (
    "Create a professional photorealistic four-panel character reference sheet of one man: {desc}. He wears {outfit}. "
    "Follow <image1> strictly as the template for the four-column layout, poses, and crops; take only the poses and "
    "composition from <image1>, not the mannequin's appearance, body shape or gender. "
    "The far-left panel must be a noticeably enlarged, front-facing head close-up: the head is upright, both eyes look "
    "directly at the camera, the entire hairstyle remains visible at the top, and the image is cropped at the upper chest. "
    "The second panel shows a standing full-body front view with both feet fully visible. The third panel shows a "
    "standard full-body side view facing the right edge of the frame. The fourth panel shows a standing full-body back "
    "view. All four panels show the same man with consistent identity, hairstyle and clothing. Realistic human anatomy, "
    "photorealistic skin and hair, plain white studio background, soft even lighting, no text or additional people."
)

W, H = 1984, 1120  # 16:9 ≈2.2 MP（项目方 ResolutionSelector 16:9 / 2.2 / 8 的近似）


def api(url, path, data=None, ctype="application/json"):
    req = urllib.request.Request(url + path, data=data, headers={"Content-Type": ctype} if data else {})
    with urllib.request.urlopen(req, timeout=600) as r:
        return r.read()


def upload(url, p: Path) -> str:
    # 隧道带宽紧：转 JPEG q95 上传（视觉近无损，体积约 1/5）
    import io
    from PIL import Image
    buf = io.BytesIO()
    Image.open(p).convert("RGB").save(buf, "JPEG", quality=95)
    b = "----consist" + uuid.uuid4().hex
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"consist_{p.stem}.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + buf.getvalue() +f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n".encode()
    r = json.loads(api(url, "/upload/image", body, f"multipart/form-data; boundary={b}"))
    return r["name"]


def graph(prompt: str, images: list[str], seed: int, w: int, h: int, prefix: str, extra_lora=None, ref_res=2048):
    g = {
        "470": {"class_type": "UNETLoader", "inputs": {"unet_name": "qwen_image_2.1_int8_convrot.safetensors", "weight_dtype": "default"}},
        "478": {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["470", 0], "lora_name": "QI2.1_AnyAngle.safetensors", "strength_model": 0.6}},
        "472": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
        "473": {"class_type": "VAELoader", "inputs": {"vae_name": "qwen_image_2.1_vae_bf16.safetensors"}},
        "474": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "471": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["472", 0], "prompt": prompt, "negative_prompt": "",
                                                                 "resolution": ref_res, "vae": ["473", 0]}},
        "476": {"class_type": "KSampler", "inputs": {"model": ["478", 0], "seed": seed, "steps": 25, "cfg": 1.0, "sampler_name": "euler",
                                                    "scheduler": "simple", "positive": ["471", 0], "negative": ["471", 1],
                                                    "latent_image": ["474", 0], "denoise": 1.0}},
        "475": {"class_type": "VAEDecode", "inputs": {"samples": ["476", 0], "vae": ["473", 0]}},
        "461": {"class_type": "SaveImage", "inputs": {"images": ["475", 0], "filename_prefix": prefix}},
    }
    model = ["478", 0]
    if extra_lora:
        g["479"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": ["478", 0], "lora_name": extra_lora[0], "strength_model": extra_lora[1]}}
        model = ["479", 0]
    g["476"]["inputs"]["model"] = model
    for i, name in enumerate(images, 1):
        g[f"48{i}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
        g["471"]["inputs"][f"images.image_{i}"] = [f"48{i}", 0]
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


def run(url, g, dest: Path, tag: dict | None = None):
    body = {"prompt": g, "client_id": "consist"}
    t = tag or _ns_tag(kind="sheet", obj=Path(dest).stem, label="Qwen-Image 2.1 设定图")
    if t:
        body["extra_data"] = {"ns_tag": t}
    pid = json.loads(api(url, "/prompt", json.dumps(body).encode()))["prompt_id"]
    t0 = time.time()
    while True:
        time.sleep(5)
        h = json.loads(api(url, f"/history/{pid}"))
        if pid in h:
            st = h[pid].get("status", {})
            if st.get("status_str") == "error":
                raise RuntimeError(json.dumps(st)[:800])
            for node in h[pid]["outputs"].values():
                for im in node.get("images", []):
                    q = f"/view?filename={im['filename']}&subfolder={im['subfolder']}&type={im['type']}"
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes(api(url, q))
                    print(f"  -> {dest.relative_to(ROOT)} {time.time()-t0:.0f}s", flush=True)
                    return
        if time.time() - t0 > 1800:
            raise TimeoutError(pid)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["sheets", "frames"])
    ap.add_argument("--url", default="http://127.0.0.1:18188")
    ap.add_argument("--seeds", default="101,202")
    ap.add_argument("--only", default="")
    ap.add_argument("--sheet", action="append", default=[])
    ap.add_argument("--shots", default="")
    ap.add_argument("--jobs", default="", help="frames 模式：JSON 文件，[{shot, prompt, images:[...], seed, tag}]")
    a = ap.parse_args()
    seeds = [int(s) for s in a.seeds.split(",")]
    log = OUT / "runs.jsonl"
    OUT.mkdir(parents=True, exist_ok=True)
    if a.mode == "sheets":
        pose = upload(a.url, POSE)
        lin = upload(a.url, ROOT / "assets/characters/lin_wan/lin_wan.png")
        plan = []
        for s in seeds:
            plan.append(("lin_wan", "A_owner", P_CHAR_POSE, [lin, pose], s, None))
            plan.append(("lin_wan", "B_owner+lnwanLoRA0.6", "lnwan_qi, " + P_CHAR_POSE, [lin, pose], s, ("lin_wan_qi_v1.safetensors", 0.6)))
            for c in ("gu_chen", "chen_yu"):
                plan.append((c, "T_text+pose", P_TEXT_POSE.format(desc=REGISTRY[c], outfit=OUTFIT[c]), [pose], s, None))
        for c, tag, p, ims, s, lora in plan:
            if a.only and c not in a.only.split(","):
                continue
            dest = OUT / c / f"{c}_sheet_{tag.split('_')[0]}_s{s}.png"
            print(c, tag, s, flush=True)
            run(a.url, graph(p, ims, s, W, H, f"consist/{c}_{tag.split('_')[0]}", lora), dest)
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": time.strftime("%F %T"), "char": c, "variant": tag, "seed": s, "file": str(dest.relative_to(ROOT)),
                                     "prompt": p, "lora_extra": lora, "size": [W, H]}, ensure_ascii=False) + "\n")
    else:
        jobs = json.loads(Path(a.jobs).read_text(encoding="utf-8"))
        cache = {}
        for j in jobs:
            names = []
            for p in j["images"]:
                if p not in cache:
                    cache[p] = upload(a.url, ROOT / p)
                names.append(cache[p])
            dest = OUT / j.get("subdir", "frames") / f"{j['shot']}_{j['tag']}_s{j['seed']}.png"
            print(j["shot"], j["tag"], flush=True)
            run(a.url, graph(j["prompt"], names, j["seed"], j.get("w", 768), j.get("h", 1344), f"consist/{j['shot']}",
                             tuple(j["lora"]) if j.get("lora") else None, j.get("ref_res", 1024)), dest)
            with open(log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"t": time.strftime("%F %T"), **j, "file": str(dest.relative_to(ROOT))}, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
