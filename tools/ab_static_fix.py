"""
静止镜头对照实验（fredw-92/QCV，2026-10-31）：同一镜头、同 seed、同剧本 H3 提示词（只换系统对齐句），
看“只给首帧”/ 换基底能不能让 ep02 的静止镜头动起来。输出只放 data/ab/static_fix/，不写 takes.json、不定稿。

用法：.venv/Scripts/python.exe tools/ab_static_fix.py <镜头 S7> <变体> <道 gpu33:3|gpu36:0|...> [--take N]
变体：
  A   只给首帧，官方 Turbo 8 步 @1.0（last_frame=None，I2VA 对齐句）
  B   首帧 + 现尾帧（= 现有版本，不重渲；只算指标）
  C   只给首帧，Pika H3 Flex 基底（6 步 lcm，官方 sigma 表）
  D   首帧 + 现尾帧，Pika H3 Flex（分开看“去掉尾帧”和“换基底”各自的作用）
  E   只给首帧，官方 Turbo @0.7
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

from ns_render import h3_video as HV
from ns_render import motion_qc as M
from ns_render import pipeline as P
from ns_render.comfy_client import ComfyClient
from ns_render import endpoints as EP

OUT = P.DATA / "ab" / "static_fix"

VARIANTS = {
    "A": {"last": False, "base": None, "ls": 1.0, "label": "只给首帧·官方8步"},
    "B": {"last": True, "base": None, "ls": 1.0, "label": "首+尾帧·官方8步（现有版本）"},
    "C": {"last": False, "base": "pika_flex", "ls": None, "label": "只给首帧·Pika Flex"},
    "D": {"last": True, "base": "pika_flex", "ls": None, "label": "首+尾帧·Pika Flex"},
    "E": {"last": False, "base": None, "ls": 0.7, "label": "只给首帧·官方8步 LoRA 0.7"},
}


def control_take(shot: str, n: int | None) -> dict:
    tk = P.load_takes(f"ep02-{shot}")
    n = n or (tk.get("active") or {}).get("video")
    return next(t for t in tk["takes"] if t["stage"] == "video" and t["n"] == n)


def client_for(lane) -> ComfyClient:
    lane = EP.norm_lane(lane)
    c = ComfyClient(EP.url_for_gpu(lane), gpu=lane)
    if EP.server_of(lane) != EP.HOME_SERVER:
        c.server_tag = EP.server_of(lane)
    return c


def run(shot: str, var: str, lane: str, take_n: int | None = None) -> dict:
    v = VARIANTS[var]
    t = control_take(shot, take_n)
    p = t["params"]
    OUT.mkdir(parents=True, exist_ok=True)
    stem = f"{shot}_{var}"
    rec = {"shot": shot, "variant": var, "label": v["label"], "control_take": t["n"], "seed": p["seed"],
           "frames": p["frames"], "lane": lane}
    if var == "B":
        src = P.DATA / t["file"]
        rec.update(file=str(src.relative_to(P.ROOT)).replace("\\", "/"), render_s=p.get("render_s"))
    else:
        cl = client_for(lane)
        prompt = t["prompt"] if v["last"] else HV.align_first_only(t["prompt"])
        first = HV.upload_once(cl, P.DATA / p["first"]["file"])
        last = HV.upload_once(cl, P.DATA / p["last"]["file"]) if v["last"] else None
        spec = HV.base_spec(v["base"]) if v["base"] else None
        wf = HV.build(prompt, first, last, p["frames"], p["seed"], f"ns_ab/{stem}", steps=p["steps"],
                      lora_strength=v["ls"] if v["ls"] is not None else 1.0,
                      extra_loras=[tuple(x) for x in p["model"].get("extra_loras") or []], base=spec)
        bad = cl.check(wf)
        if bad:
            raise SystemExit("工作流检查不通过：" + "；".join(bad))
        t0 = time.monotonic()
        pid = cl.submit(wf)
        print(stem, "submitted", lane, pid, flush=True)
        entry = cl.wait(pid, HV.timeout_for(p["frames"]))
        item = next(f for f in cl.output_files(entry) if f["filename"].endswith(".mp4"))
        src = OUT / f"{stem}.mp4"
        cl.download(item, src)
        rec.update(file=str(src.relative_to(P.ROOT)).replace("\\", "/"), render_s=round(time.monotonic() - t0, 1),
                   prompt_first_line=prompt.split("\n", 1)[0], base=(spec or {}).get("id", HV.DEFAULT_BASE),
                   lora_strength=v["ls"], prompt_id=pid)
    mo = M.video_motion(src)
    rec.update(verdict=mo["verdict"], labels=mo["labels"], metrics=mo["metrics"])
    (OUT / f"{stem}.json").write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(rec, ensure_ascii=False), flush=True)
    return rec


if __name__ == "__main__":
    a = sys.argv[1:]
    tn = int(a[a.index("--take") + 1]) if "--take" in a else None
    run(a[0], a[1], a[2] if len(a) > 2 and not a[2].startswith("--") else "gpu33:3", tn)
