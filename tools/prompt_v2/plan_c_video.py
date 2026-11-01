"""PROMPT（2026-10-31，方案 C）：按导演版分镜出视频（Ref2VA 为主），产物只放 data/pipeline/runs/ep02_claude_director_v1/video/，不写 takes。

变体：
  official    官方 ref2va int8 + SigmaShift 12/3 + fp16 视频 VAE，20 步 split 10 两段式（= LAB X4 配方；只在 gpu33 有权重）
  singularity 社区 Minimax-h3_Singularity_ref2va_v2_pruned_int8_convrot_r2（gpu36；不接 SigmaShift——h3_comfy_expert §3
              “Singularity…不接这个节点”；int8 视频 VAE；仅内部对比）
图结构复用 tools/lab_ep02/ref2va_run.build（项目方工作流 API 版）。参考图 = plans/S<n>.ref2va.plan.json 的 ref_slots 顺序
（<Picture k> = 第 k 张脸部裁切）；提示词 = prompts/S<n>.ref2va.txt。
每道每次只排 1 个：脚本串行，上一条出完才交下一条；front=true 插队首（总调度 10-31：方案 C 优先）。
用法：.venv/Scripts/python.exe tools/prompt_v2/plan_c_video.py <lane url> <variant> <shot:seed> [<shot:seed> …]
"""
from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "render_router"))
sys.path.insert(0, str(ROOT / "tools" / "lab_ep02"))
import ref2va_run as RV  # noqa: E402
from ns_render.comfy_client import ComfyClient  # noqa: E402

RUN = ROOT / "data" / "pipeline" / "runs" / "ep02_claude_director_v1"
OUT = RUN / "video"
VARIANTS = {
    "official": {"unet": "minimax_h3_ref2va_pruned_int8_convrot.safetensors", "vae": "minimax_h3_video_vae_fp16.safetensors",
                 "shift": True, "upscaler": "minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors"},
    "singularity": {"unet": "Minimax-h3_Singularity_ref2va_v2_pruned_int8_convrot_r2.safetensors",
                    "vae": "minimax_h3_video_vae_int8_convrot.safetensors", "shift": False,
                    "upscaler": "minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors"},
}


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
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.loads(r.read().decode("utf-8"))["prompt_id"]
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode("utf-8", "replace")[:1500]) from e


def build(prompt, refs, frames, seed, prefix, var):
    v = VARIANTS[var]
    wf, lo = RV.build(prompt, refs, frames, seed, prefix, 20, 10, 0.71, False, "comfy kitchen attention", v["upscaler"])
    wf["74"]["inputs"]["unet_name"] = v["unet"]
    wf["58"]["inputs"]["vae_name"] = v["vae"]
    if not v["shift"]:
        wf.pop("61")
        wf["76"]["inputs"]["model"] = ["74", 0]
    return wf, lo


def run_one(c, url, var, shot, seed):
    n = int(shot.lstrip("S"))
    name = f"S{n}_{var}_s{seed}"
    dest = OUT / f"{name}.mp4"
    if dest.exists():
        return
    plan = json.loads((RUN / "plans" / f"S{n}.ref2va.plan.json").read_text(encoding="utf-8"))
    prompt = (RUN / "prompts" / f"S{n}.ref2va.txt").read_text(encoding="utf-8").strip()
    refs = [ROOT / s["path"] for s in plan["ref_slots"]]
    frames = int(plan["frames"])
    # 总调度 10-31：方案 C 优先于 A/B 的额外 seed——front=true 插到队首；本脚本串行，同一时间每道只占 1 个
    names = []
    for r in refs:                                   # 隧道偶发 10054：重试 5 次
        for k in range(5):
            try:
                names.append(c.upload_image(r, "ns_final/planc", remote=False))
                break
            except Exception as e:  # noqa: BLE001
                if k == 4:
                    raise
                print(time.strftime("%H:%M:%S"), "retry upload", repr(e)[:80], flush=True)
                time.sleep(15)
    wf, lo = build(prompt, names, frames, seed, f"planc/{name}", var)
    meta = {"name": name, "shot": f"ep02-S{n}", "variant": var, "seed": seed, "frames": frames, "lane": url, "lo_res": lo,
            "refs": [str(r.relative_to(ROOT)).replace("\\", "/") for r in refs], "prompt_file": f"prompts/S{n}.ref2va.txt",
            "tag": "PROMPT-planC", "started": time.strftime("%Y-%m-%d %H:%M:%S"), **VARIANTS[var]}
    (OUT / f"{name}.json").write_text(json.dumps({**meta, "workflow": wf}, ensure_ascii=False, indent=1), encoding="utf-8")
    t0 = time.monotonic()
    try:
        sp = str(ROOT / "services" / "agent")
        if sp not in sys.path:
            sys.path.append(sp)
        from ns_agent import comfy_tag as CT
        _tag = CT.make("PROMPT", "video", episode=2, shot=f"S{n}", label=f"方案C {var} s{seed}", job=name)
    except Exception:  # noqa: BLE001
        _tag = None
    pid = submit_front(url, wf, _tag)
    print(time.strftime("%H:%M:%S"), "submitted", name, pid, flush=True)
    while True:
        try:
            entry = c.wait(pid, 4 * 3600)
            break
        except Exception as e:  # noqa: BLE001  隧道抖动：重连等待，不重渲
            if "timed out" not in str(e) and "refused" not in str(e) and "10061" not in str(e):
                raise
            time.sleep(30)
    item = next(f for f in c.output_files(entry) if f["filename"].endswith(".mp4"))
    c.download(item, dest)
    meta.update(render_s=round(time.monotonic() - t0, 1), file=str(dest.relative_to(ROOT)).replace("\\", "/"), prompt_id=pid)
    (OUT / f"{name}.json").write_text(json.dumps({**meta, "workflow": wf}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(time.strftime("%H:%M:%S"), "done", name, meta["render_s"], flush=True)


def main(argv):
    url, var, *jobs = argv
    OUT.mkdir(parents=True, exist_ok=True)
    c = ComfyClient(url, timeout=120)
    for j in jobs:
        shot, seed = j.split(":")
        try:
            run_one(c, url, var, shot, int(seed))
        except Exception as e:  # noqa: BLE001
            print(time.strftime("%H:%M:%S"), "FAIL", j, repr(e)[:300], flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
