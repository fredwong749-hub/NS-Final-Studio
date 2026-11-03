"""
RR（2026-10-31）：API 中途重启（任务被标“API 重启中断”）时，ComfyUI 上其实已跑完 / 仍在跑的视频任务 → 从该道 ComfyUI
history 取回 mp4，按 h3_video.render 的同样字段存成 video take（不设为当前、不定稿）。不改提示词，提示词 / 种子 / 帧数
原样取自当时提交给 ComfyUI 的工作流。

用法：python tools/rr_recover_video_takes.py JOB_ID [JOB_ID ...] [--wait 7200]
  JOB_ID = data/jobs/v1/<id>.json 里 kind=video 的任务（有 prompt_id）；--wait = 仍在跑的最多等多少秒
"""
from __future__ import annotations

import json
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/render_router", "packages/schema", "services/api"):
    sys.path.insert(0, str(ROOT / p))
from ns_render import endpoints as EP  # noqa: E402
from ns_render import motion_qc as MQ  # noqa: E402
from ns_render import pipeline as P  # noqa: E402
from ns_render import render_paths as RP  # noqa: E402  W33
from ns_schema.edits import Take  # noqa: E402


def _json(url: str):
    return json.load(urllib.request.urlopen(url, timeout=120))


def recover(jid: str, wait_s: float) -> dict:
    job = json.loads((ROOT / "data" / "jobs" / "v1" / f"{jid}.json").read_text(encoding="utf-8"))
    shot, gpu, pid, jp = job["shot_id"], job["gpu"], job.get("prompt_id"), job.get("params") or {}
    if not pid:
        return {"job": jid, "shot": shot, "error": "没有 prompt_id（没提交到 ComfyUI）"}
    takes = P.load_takes(shot)
    if any(t.get("job_id") == jid for t in takes["takes"]):
        return {"job": jid, "shot": shot, "skipped": "已存成 take"}
    url = EP.url_for_gpu(gpu)
    t_end = time.time() + wait_s
    while True:
        h = _json(f"{url}/history/{pid}").get(pid)
        if h and (h.get("status") or {}).get("completed"):
            break
        if h and (h.get("status") or {}).get("status_str") == "error":
            return {"job": jid, "shot": shot, "error": "ComfyUI 执行失败"}
        if time.time() > t_end:
            return {"job": jid, "shot": shot, "error": "等待超时（还在跑）"}
        time.sleep(30)
    wf = h["prompt"][2]
    item = next(f for o in h["outputs"].values() for k in ("gifs", "videos", "images", "files") for f in (o.get(k) or [])
                if str(f.get("filename", "")).endswith(".mp4"))
    d = P.shot_dir(shot)
    with P.shot_lock(shot):
        n = P._next_n(shot, "video")
    base = f"{RP.take_rel_dir(d, P.DATA, P.RENDERS)}/video_{n:03d}_{jid}"   # W33
    dst = P.DATA / f"{base}.mp4"
    dst.parent.mkdir(parents=True, exist_ok=True)
    q = urllib.parse.urlencode({"filename": item["filename"], "subfolder": item.get("subfolder", ""),
                                "type": item.get("type", "output")})
    with urllib.request.urlopen(f"{url}/view?{q}", timeout=900) as r:
        dst.write_bytes(r.read())
    lf = P.extract_last_frame(dst, P.DATA / f"{base}_last.png")
    motion = MQ.video_motion(dst)
    gen = wf["131"]["inputs"]
    loras = [[v["inputs"]["lora_name"], v["inputs"]["strength_model"]] for v in wf.values()
             if v.get("class_type") == "LoraLoaderModelOnly"]
    msgs = {m[0]: m[1].get("timestamp") for m in (h.get("status") or {}).get("messages", [])}
    render_s = round((msgs.get("execution_success", 0) - msgs.get("execution_start", 0)) / 1000, 1) or None
    params = {**{k: v for k, v in jp.items() if k not in ("warnings",)},
              "seed": wf["129"]["inputs"]["noise_seed"], "steps": wf["124"]["inputs"].get("steps"),
              "frames": gen["length"], "prompt_source": "script", "gpu": gpu,
              "last": None if jp.get("last_frame_used") is False else jp.get("last"),
              "last_unused": jp.get("last") if jp.get("last_frame_used") is False else None,
              "model": {"extra_loras": loras, "base_lora": None, "turbo_lora": None},
              "render_s": render_s,
              "recovered": {"by": "RR", "at": P.now(), "why": "API 重启中断，结果从 ComfyUI history 取回",
                            "prompt_id": pid, "comfy_file": item}}
    take = Take(n=n, stage="video", file=f"{base}.mp4", seed=int(params["seed"]), prompt=gen["prompt"],
                seconds=render_s, frames=int(gen["length"]), created_at=P.now(),
                last_frame=f"{base}_last.png" if lf else None, workflow="h3_fl2va", parent=jp.get("parent"),
                from_first=(jp.get("first") or {}).get("n"), gpu=gpu, job_id=jid, params=params,
                qc={"motion": motion})
    P._add_take(shot, take, activate=False)
    return {"job": jid, "shot": shot, "take": n, "file": take.file, "qc": motion.get("labels"),
            "verdict": motion.get("verdict")}


def main(a):
    wait_s = 0.0
    if "--wait" in a:
        i = a.index("--wait")
        wait_s = float(a[i + 1])
        del a[i:i + 2]
    sys.stdout.reconfigure(encoding="utf-8")
    for jid in a:
        try:
            print(json.dumps(recover(jid, wait_s), ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001
            print(json.dumps({"job": jid, "error": repr(e)[:300]}, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
