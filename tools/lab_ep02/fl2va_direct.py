"""
LAB：用生产同一个图生成器（ns_render.h3_video.build）出 I2VA（只给首帧），直接提交到指定 ComfyUI 道（:8800 连不上的道
或需要额外 LoRA 时用）。提示词 = 剧本 H3 提示词经 i2v_prompt 修正（I2VA 对齐句 + 去 Picture 2 分句），首帧 = 定稿首帧。
产物 data/ab/lab/direct/<name>.mp4 + .json，不写 takes。

用法：.venv/Scripts/python.exe tools/lab_ep02/fl2va_direct.py <name> <url> <shot S1> <seed> <base official_base|pika_flex>
        [--steps 24] [--lora name:strength ...] [--width 768 --height 1344]
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

OUT = ROOT / "data" / "ab" / "lab" / "direct"


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("name"); ap.add_argument("url"); ap.add_argument("shot"); ap.add_argument("seed", type=int)
    ap.add_argument("base"); ap.add_argument("--steps", type=int, default=None)
    ap.add_argument("--lora", action="append", default=[])
    ap.add_argument("--size", default=None, help="WxH，例如 736x1312（E2 分辨率对照）")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    sid = f"ep02-{a.shot}"
    c = json.loads((P.DATA / f"renders/ep02/{a.shot}/compiled.json").read_text(encoding="utf-8"))
    frames_in = HV.locked_frames(sid)
    secs = HV.shot_seconds(P.load_script(), sid)
    frames = HV.frames_for(secs)[0]
    prompt, removed = HV.i2v_prompt(HV.realign(c["video_prompt"], frames))
    client = ComfyClient(a.url, timeout=120)
    first = client.upload_image(P.DATA / frames_in["first"]["file"], "ns_final/lab", remote=False)
    spec = HV.base_spec(a.base)
    loras = [(x.rsplit(":", 1)[0], float(x.rsplit(":", 1)[1])) for x in a.lora]
    wf = HV.build(prompt, first, None, frames, a.seed, f"lab/{a.name}", steps=a.steps, extra_loras=loras,
                  base=None if spec["id"] == HV.DEFAULT_BASE else spec)
    if a.size:
        sw, sh = (int(v) for v in a.size.lower().split("x"))
        for n in wf.values():
            if n.get("class_type") in ("MiniMaxH3ImageToVideo", "ImageScale"):
                n["inputs"]["width"], n["inputs"]["height"] = sw, sh
    meta = {"name": a.name, "size": a.size, "shot": sid, "url": a.url, "seed": a.seed, "base": a.base, "steps": a.steps, "loras": loras,
            "frames": frames, "first": frames_in["first"], "prompt_removed": removed, "tag": "LAB",
            "started": time.strftime("%Y-%m-%d %H:%M:%S")}
    (OUT / f"{a.name}.json").write_text(json.dumps({**meta, "prompt": prompt, "workflow": wf}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    t0 = time.monotonic()
    pid = client.submit(wf)
    print("submitted", a.name, pid, flush=True)
    while True:   # 隧道抖动：重连等待，不重渲
        try:
            entry = client.wait(pid, 4 * 3600)
            break
        except Exception as e:  # noqa: BLE001
            if "timed out" not in str(e) and "refused" not in str(e) and "10061" not in str(e) and "Unavailable" not in type(e).__name__:
                raise
            print("retry wait", str(e)[:100], flush=True)
            time.sleep(30)
    item = next(f for f in client.output_files(entry) if f["filename"].endswith(".mp4"))
    dest = OUT / f"{a.name}.mp4"
    client.download(item, dest)
    meta.update(render_s=round(time.monotonic() - t0, 1), file=str(dest.relative_to(ROOT)).replace("\\", "/"))
    (OUT / f"{a.name}.json").write_text(json.dumps({**meta, "prompt": prompt, "workflow": wf}, ensure_ascii=False, indent=1),
                                        encoding="utf-8")
    print("done", a.name, meta["render_s"], dest, flush=True)


if __name__ == "__main__":
    main(sys.argv[1:])
