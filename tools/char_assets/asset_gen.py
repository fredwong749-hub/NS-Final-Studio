"""Character-asset ComfyUI runner for gpu3 (Qwen-Image 2.1 Base / NoctQ V4, multi-image reference edit).

Recipe: script play lib/research v6 角色资产与一致性.md
  - Base model, 25 steps, CFG 1, euler/simple (Turbo is NOT used: it copies ref pose and breaks grids)
  - TextEncodeQwenImage21 resolution=0 (refs pre-scaled by the caller: face 768², items 512-768)
  - latent "ref"  = encoder's latent (output follows image_1 size; use for small edits that must not move)
    latent "empty" = EmptyLatentImage w x h (new composition: plates, turnarounds, looks)
  - texture-fix VAE for photoreal output; <= 4 refs, one role line per ref in the prompt

jobs.jsonl line: {"id", "prompt", "refs":[abs paths]?, "latent":"empty"|"ref", "w","h", "seed",
                  "unet"?, "vae"?, "loras":[[name,strength]]?, "steps"?, "cfg"?, "sampler"?, "scheduler"?,
                  "negative"?, "resolution"?}
Writes <out>/<id>.png + <id>.json (job + timing + gpu). Resumable (skips existing png).

GPU rules (coordinator 2026-10-29/30): GPU 1 (:8189) when no trainer holds it; GPU 0 (:8188) / GPU 3 (:8191)
only while lend.gpuN exists. NEVER GPU 2. Each job holds gpu.lock.gpuN (O_EXCL, "pid:<pid> <job>").
Only submits to an empty ComfyUI queue (shared with other agents). The jewellery trainer has priority.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

ST = "/root/.local/state/NS-Studio"
JWL = "/root/claude-kimi-ns-studio-v1/ns-studio/data/train/jewellery"
PORTS = {1: 8189, 0: 8188, 3: 8191}          # GPU 2 deliberately absent
MARK = "/root/claude-kimi-ns-studio-v1/nsfs_assets/logs/released"
COOLDOWN = 60                                # seconds between our jobs on one GPU
BASE = "qwen_image_2.1_int8_convrot.safetensors"
NOCTQ = "NoctQ_V4_int8_convrot.safetensors"
VAE_TF = "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"
CLIP = "qwen3vl_8b_int8_convrot.safetensors"
NEG = ("anime, cartoon, illustration, CGI, 3d render, doll face, plastic skin, airbrushed skin, deformed hands, "
       "extra fingers, missing fingers, fused fingers, melted nails, blurry, watermark, text, logo")


def http(port, path, data=None, ctype="application/json", timeout=120):
    req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", data=data)
    if data is not None:
        req.add_header("Content-Type", ctype)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def upload(port, path: Path) -> str:
    b = uuid.uuid4().hex
    name = f"charasset_{path.parent.name}_{path.name}"
    body = (f"--{b}\r\nContent-Disposition: form-data; name=\"image\"; filename=\"{name}\"\r\n"
            f"Content-Type: application/octet-stream\r\n\r\n").encode() + path.read_bytes() + \
        f"\r\n--{b}\r\nContent-Disposition: form-data; name=\"overwrite\"\r\n\r\ntrue\r\n--{b}--\r\n".encode()
    r = json.loads(http(port, "/upload/image", body, f"multipart/form-data; boundary={b}"))
    return r["name"] if not r.get("subfolder") else f"{r['subfolder']}/{r['name']}"


def graph(job, ref_names):
    g = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": job.get("unet", BASE), "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": CLIP, "type": "qwen_image", "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": job.get("vae", VAE_TF)}},
        "4": {"class_type": "TextEncodeQwenImage21", "inputs": {
            "clip": ["2", 0], "prompt": job["prompt"], "negative_prompt": job.get("negative", NEG),
            "resolution": job.get("resolution", 0), "vae": ["3", 0]}},
        "7": {"class_type": "RandomNoise", "inputs": {"noise_seed": job["seed"]}},
        "8": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": job.get("sampler", "euler")}},
        "10": {"class_type": "SamplerCustomAdvanced", "inputs": {
            "noise": ["7", 0], "guider": ["6", 0], "sampler": ["8", 0], "sigmas": ["9", 0]}},
        "11": {"class_type": "VAEDecode", "inputs": {"samples": ["10", 0], "vae": ["3", 0]}},
        "12": {"class_type": "SaveImage", "inputs": {"images": ["11", 0], "filename_prefix": f"charasset/{job['id']}"}},
    }
    for i, n in enumerate(ref_names, 1):
        g[f"10{i}"] = {"class_type": "LoadImage", "inputs": {"image": n}}
        g["4"]["inputs"][f"images.image_{i}"] = [f"10{i}", 0]
    if job.get("latent", "empty") == "ref" and ref_names:
        g["10"]["inputs"]["latent_image"] = ["4", 2]
    else:
        g["5"] = {"class_type": "EmptyLatentImage", "inputs": {"width": job["w"], "height": job["h"], "batch_size": 1}}
        g["10"]["inputs"]["latent_image"] = ["5", 0]
    model = ["1", 0]
    for j, (name, s) in enumerate(job.get("loras", [])):
        nid = f"2{j}0"
        g[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": name, "strength_model": s}}
        model = [nid, 0]
    g["9"] = {"class_type": "BasicScheduler", "inputs": {"model": model, "scheduler": job.get("scheduler", "simple"),
                                                         "steps": job.get("steps", 25), "denoise": 1.0}}
    g["6"] = {"class_type": "CFGGuider", "inputs": {"model": model, "positive": ["4", 0], "negative": ["4", 1],
                                                    "cfg": job.get("cfg", 1.0)}}
    return g


def stale(path):
    try:
        pid = int(open(path).read().split()[0].split(":")[1])
        os.kill(pid, 0)
        return False
    except ProcessLookupError:
        return True
    except Exception:
        return False


def eligible(g, gpus):
    if g not in gpus or g == 2:
        return False
    if g != 1 and not os.path.exists(f"{ST}/lend.gpu{g}"):
        return False
    if any(os.path.exists(x) for x in (f"{ST}/train.lock.gpu{g}", f"{ST}/train.lock.{g}", f"{JWL}/GPU_IN_USE_gpu{g}.json")):
        return False
    try:
        if time.time() - os.path.getmtime(f"{MARK}.gpu{g}") < COOLDOWN:
            return False
    except FileNotFoundError:
        pass
    lockp = f"{ST}/gpu.lock.gpu{g}"
    if os.path.exists(lockp):
        if stale(lockp):
            try: os.unlink(lockp)
            except FileNotFoundError: pass
        return False
    try:
        q = json.loads(http(PORTS[g], "/queue"))
        return len(q["queue_running"]) + len(q["queue_pending"]) == 0
    except Exception:
        return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("out")
    ap.add_argument("--gpus", default="1,0,3", help="subset of 1,0,3 (2 is never used)")
    a = ap.parse_args()
    gpus = {int(x) for x in a.gpus.split(",")} - {2}
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    jobs = [json.loads(l) for l in Path(a.jobs).read_text(encoding="utf-8").splitlines() if l.strip()]
    todo = [j for j in jobs if not (out / f"{j['id']}.png").exists()]
    mu = threading.Lock()
    cid = "charasset-" + uuid.uuid4().hex[:8]
    print(f"{len(todo)}/{len(jobs)} jobs to do on GPUs {sorted(gpus)}", flush=True)

    def worker(g):
        port, lockp = PORTS[g], f"{ST}/gpu.lock.gpu{g}"
        waited = 0
        while True:
            with mu:
                if not todo:
                    return
            if not eligible(g, gpus):
                waited += 1
                if waited % 40 == 1:
                    print(f"gpu{g}: waiting (busy/locked/not lent)", flush=True)
                time.sleep(15); continue
            try:
                fd = os.open(lockp, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            except FileExistsError:
                time.sleep(5); continue
            with mu:
                job = todo.pop(0) if todo else None
            if job is None:
                os.close(fd); os.unlink(lockp); return
            os.write(fd, f"pid:{os.getpid()} charasset:{job['id']}".encode()); os.close(fd)
            t0 = time.time()
            try:
                refs = [upload(port, Path(r)) for r in job.get("refs", [])]
                body = json.dumps({"prompt": graph(job, refs), "client_id": cid}).encode()
                pid = json.loads(http(port, "/prompt", body))["prompt_id"]
                while True:
                    time.sleep(3)
                    h = json.loads(http(port, f"/history/{pid}"))
                    if pid in h:
                        break
                    if time.time() - t0 > 1800:
                        raise TimeoutError("job over 30 min")
                imgs = [im for o in h[pid].get("outputs", {}).values() for im in o.get("images", [])]
                if not imgs:
                    raise RuntimeError(json.dumps(h[pid].get("status", {}))[:600])
                im = imgs[0]
                qs = urllib.parse.urlencode({"filename": im["filename"], "subfolder": im["subfolder"], "type": im["type"]})
                (out / f"{job['id']}.png").write_bytes(http(port, f"/view?{qs}"))
                rec = {**job, "_gpu": g, "_seconds": round(time.time() - t0, 1), "_at": time.strftime("%Y-%m-%dT%H:%M:%S")}
                (out / f"{job['id']}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
                print(f"OK {job['id']} gpu{g} {time.time() - t0:.0f}s", flush=True)
            except Exception as e:
                print("err", job["id"], f"gpu{g}", getattr(e, "read", lambda: b"")()[:600], e, flush=True)
                job["_tries"] = job.get("_tries", 0) + 1
                if job["_tries"] < 3:
                    with mu:
                        todo.append(job)
            finally:
                try: os.unlink(lockp)
                except FileNotFoundError: pass
                # yield: jwl wait_idle_gpu needs >=10 s quiet (polls every 15 s); never starve the jewellery trainer.
                # Shared marker so several runners of ours respect one cooldown per GPU.
                Path(f"{MARK}.gpu{g}").touch()

    ts = [threading.Thread(target=worker, args=(g,), daemon=True) for g in sorted(gpus)]
    for t in ts: t.start()
    for t in ts: t.join()
    print("ALL_DONE", flush=True)


if __name__ == "__main__":
    sys.exit(main())
