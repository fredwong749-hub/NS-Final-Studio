"""
Turbo（CFG 1，负面无效） vs Base（真实 CFG，负面生效）对比，只跑非成人镜头，结果只写到本目录。
每张图都过裸露质检；被拦的图不要打开看。

    uv run python golden/base_vs_turbo/run.py ep01-S5 ep01-S3 --arms turbo base2.5 base4
"""
import argparse
import json
import sys
import time
from dataclasses import replace
from pathlib import Path

from ns_agent.compiler import compile_shot
from ns_render import pipeline as P
from ns_render import workflows as W
from ns_render.comfy_client import ComfyClient
from ns_render.qc import nudity_qc

OUT = Path(__file__).resolve().parent


def model_for(arm: str) -> W.QwenModel:
    if arm == "turbo":
        return P.QWEN_TURBO
    cfg = float(arm.removeprefix("base"))
    return replace(P.QWEN_BASE, cfg=cfg)


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("shots", nargs="+")
    ap.add_argument("--arms", nargs="+", default=["turbo", "base2.5", "base4"])
    ap.add_argument("--seeds", type=int, default=1)
    args = ap.parse_args()
    script = P.load_script()
    client = ComfyClient()
    loras = P.available_loras(client)
    res_file = OUT / "results.json"
    results = json.loads(res_file.read_text(encoding="utf-8")) if res_file.exists() else {}
    for shot_id in args.shots:
        ep, s = P.find_shot(script, shot_id)
        c = compile_shot(ep, s, script.globals, loras)
        if c.adult:
            print(f"{shot_id}: 成人镜头，跳过")
            continue
        for k in range(args.seeds):
            seed = P.seed_for(shot_id + "/bt", k)
            for arm in args.arms:
                m = model_for(arm)
                neg = P.image_negative(c)
                wf = W.qwen_t2i(c.image_prompt, neg, *P.IMAGE_SIZE, seed, f"ns_final/bt/{shot_id}_{arm}",
                                m=m, loras=c.image_loras)
                entry, secs = client.run(wf, timeout_s=1800)
                item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
                dest = OUT / f"{shot_id}_s{k}_{arm}.png"
                client.download(item, dest)
                qc = nudity_qc(dest)
                results[dest.name] = {"shot": shot_id, "arm": arm, "seed": seed, "seconds": round(secs, 1), "qc": qc}
                print(f"[{time.strftime('%H:%M:%S')}] {dest.name} {secs:.1f}s nudity={qc['nudity']} "
                      f"hits={qc['hits']} clip_bare={qc['clip_bare']}", flush=True)
                res_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
