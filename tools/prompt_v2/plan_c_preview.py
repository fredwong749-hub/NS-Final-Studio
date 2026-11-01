"""PROMPT（2026-10-31，方案 C）：按导演版分镜出每镜分镜预览图（Qwen-Image 2.1 Base + 设定图脸部参考，768×1344，只出图）。

提示词 = 每镜 Shot Spec 的首帧中文（写作模型按导演稿转写的 img 行，系统不改）+ 每张参考图一行角色说明（asset_gen 的做法：
“图N是<角色名>的脸部参考”）+ 本集造型（人物表 / 造型行原文）。参考图 = data/assets/identity_refs/<id>/<id>_face_ref2va.png（项目方已挑定）。
道：PLANB 借出的 gpu36:0（本机隧道 http://127.0.0.1:18288），每次只排 1 个：连续两次（间隔 20 s）看到队列空才提交。
输出：data/pipeline/runs/ep02_claude_director_v1/preview/S<n>_<k>.png + .json
用法：.venv/Scripts/python.exe tools/prompt_v2/plan_c_preview.py [--url …] [--per-shot 1] [--shots 1,2]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "render_router"))
sys.path.insert(0, str(ROOT / "tools" / "char_assets"))
sys.path.insert(0, str(ROOT / "packages" / "schema"))
from ns_render.comfy_client import ComfyClient  # noqa: E402
from ns_schema.shot_spec import ShotSpec  # noqa: E402
sys.path.insert(0, str(ROOT / "services" / "agent"))
from ns_agent import framing as F  # noqa: E402

RUN = ROOT / "data" / "pipeline" / "runs" / "ep02_claude_director_v1"
OUT = RUN / "preview"
FACE = {"林晚": "data/assets/identity_refs/lin_wan/lin_wan_face_ref2va.png",
        "顾沉": "data/assets/identity_refs/gu_chen/gu_chen_face_ref2va.png",
        "陈宇": "data/assets/identity_refs/chen_yu/chen_yu_face_ref2va.png"}
UNET = "qwen_image_2.1_int8_convrot.safetensors"
CLIP = "qwen3vl_8b_int8_convrot.safetensors"
VAE = "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"
STYLE = "真人写实电影剧照，竖构图，面部清晰对焦，五官锐利，衣装完整，电影级布光，浅景深，画面干净，纯净背景"
NEG = ("anime, cartoon, illustration, CGI, 3d render, doll face, plastic skin, deformed hands, extra fingers, "
       "text, subtitles, watermark, logo")


def busy(url):
    try:
        with urllib.request.urlopen(url + "/queue", timeout=30) as r:
            d = json.loads(r.read().decode("utf-8"))
        return bool(d["queue_running"] or d["queue_pending"])
    except Exception:  # noqa: BLE001
        return None


def submit_front(url, wf, tag: dict | None = None):
    import uuid
    body_d = {"prompt": wf, "client_id": "prompt-planc-" + uuid.uuid4().hex[:8], "front": True}
    try:   # GPU 任务归属标签（K-OPS-G01，extra_data.ns_tag）；出错就不带标签
        from ns_agent import comfy_tag as CT
        CT.attach(body_d, tag)
    except Exception:  # noqa: BLE001
        body_d.pop("extra_data", None)
    body = json.dumps(body_d).encode("utf-8")
    req = urllib.request.Request(url + "/prompt", data=body, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read().decode("utf-8"))["prompt_id"]


def graph(prompt, refs, seed, prefix, w=768, h=1344, steps=25):
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": UNET, "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": VAE}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["2", 0], "prompt": prompt, "negative_prompt": NEG,
                                                                "resolution": 0, "vae": ["3", 0]}},
        "5": {"class_type": "EmptyLatentImage", "inputs": {"width": w, "height": h, "batch_size": 1}},
        "6": {"class_type": "CFGGuider", "inputs": {"model": ["1", 0], "positive": ["4", 0], "negative": ["4", 1], "cfg": 1.0}},
        "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": "euler"}},
        "9": {"class_type": "BasicScheduler", "inputs": {"model": ["1", 0], "scheduler": "simple", "steps": steps, "denoise": 1.0}},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {"noise": ["7", 0], "guider": ["6", 0], "sampler": ["8", 0],
                                                                 "sigmas": ["9", 0], "latent_image": ["5", 0]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": prefix}},
    }
    for i, n in enumerate(refs, 1):
        g[f"10{i}"] = {"class_type": "LoadImage", "inputs": {"image": n}}
        g["4"]["inputs"][f"images.image_{i}"] = [f"10{i}", 0]
    return g


def prompt_for(s: ShotSpec) -> tuple[str, list[str]]:
    faces = [c for c in s.characters_on_screen if c.presence == "在画" and c.name in FACE]
    lines = [f"图{i}是{c.name}的脸部参考（只取脸和发型）。" for i, c in enumerate(faces, 1)]
    # 景别优先（K-REN-101，services/agent/ns_agent/framing.py）：首句写景别构图；造型只写该景别下看得见的部件
    size = F.size_of(s.first_frame.text) or s.camera.size
    if F.lower_focus(s.first_frame.text):
        size_filter = None                       # 下半身是主体（鞋 / 脚特写）：不删下半身部件
    else:
        size_filter = size
    looks = []
    for c in s.characters_on_screen:
        if c.presence in ("在画", "局部") and c.en_phrase:
            lk = F.filter_parts(c.look or "", size_filter, ", ")
            looks.append(f"{c.name}：{c.en_phrase}" + (f"，{lk}" if lk else ""))
    head = F.lead(size)
    body = F.filter_parts(s.first_frame.text, size_filter)   # img 原文里看不见的部件分句也去掉（写作规则 PI-02 要求每镜写全造型）
    p = (head + "。" if head else "") + "".join(lines) + body + "。" + "；".join(looks) + "。" + STYLE
    return p, [FACE[c.name] for c in faces]


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:18288")
    ap.add_argument("--per-shot", type=int, default=1)
    ap.add_argument("--shots")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    c = ComfyClient(a.url, timeout=120)
    specs = sorted((ShotSpec.model_validate_json(p.read_text(encoding="utf-8")) for p in (RUN / "specs").glob("*.spec.json")),
                   key=lambda s: s.index)
    want = {int(x) for x in a.shots.split(",")} if a.shots else None
    for s in specs:
        if want and s.index not in want:
            continue
        for k in range(1, a.per_shot + 1):
            dest = OUT / f"S{s.index}_{k}.png"
            if dest.exists():
                continue
            prompt, refs = prompt_for(s)
            # 总调度：插进 A/B 的队列，每道只占 1 个——本脚本串行（等上一张出完才交下一张），用 front=true 插到队首
            seed = 20261101 + s.index * 10 + k
            pend = dest.with_suffix(".pending")
            t0 = time.monotonic()
            if pend.exists():                              # 上次提交后隧道断了：接着等同一个任务，不重交
                pid = pend.read_text(encoding="utf-8").strip()
            else:
                names = [c.upload_image(ROOT / r, "ns_final/planc_preview", remote=False) for r in refs]
                try:
                    from ns_agent import comfy_tag as CT
                    _tag = CT.make("PROMPT", "first_frame", episode=2, shot=f"S{s.index}", label=f"方案C分镜预览 {k}", job=s.id)
                except Exception:  # noqa: BLE001
                    _tag = None
                pid = submit_front(a.url, graph(prompt, names, seed, f"planc_preview/S{s.index}_{k}"), _tag)
                pend.write_text(pid, encoding="utf-8")
            print(time.strftime("%H:%M:%S"), "submitted", s.id, k, pid, flush=True)
            while True:
                try:
                    entry = c.wait(pid, 3600)
                    break
                except Exception as e:  # noqa: BLE001  隧道抖动：重连等待
                    print(time.strftime("%H:%M:%S"), "retry wait", str(e)[:80], flush=True)
                    time.sleep(20)
            item = next(f for f in c.output_files(entry) if f["filename"].endswith(".png"))
            c.download(item, dest)
            meta = {"shot": s.id, "k": k, "seed": seed, "prompt": prompt, "refs": refs, "unet": UNET, "steps": 25, "cfg": 1.0,
                    "size": [768, 1344], "lane": a.url, "render_s": round(time.monotonic() - t0, 1), "prompt_id": pid}
            dest.with_suffix(".json").write_text(json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
            pend.unlink(missing_ok=True)
            print(time.strftime("%H:%M:%S"), "done", dest.name, meta["render_s"], flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
