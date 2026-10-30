"""
林晚首帧锁脸 A/B：同一编译提示词、同一种子，t2i 对比单参考编辑（qwen_edit）。
只跑非成人镜头（compile_shot(...).adult 为 False 才渲染）。结果只写到 golden/facelock/，不加 take。

    uv run python golden/facelock/ab.py ep01-S3 ep01-S5 --seeds 2
"""
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

from ns_agent.compiler import compile_shot
from ns_render import pipeline as P
from ns_render import workflows as W
from ns_render.comfy_client import ComfyClient
from ns_render.qc import nudity_qc

OUT = Path(__file__).resolve().parent


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser()
    ap.add_argument("shots", nargs="+")
    ap.add_argument("--seeds", type=int, default=1)
    ap.add_argument("--comfy", default="http://127.0.0.1:8188")
    ap.add_argument("--model", choices=["pipeline", "turbo", "base"], default="pipeline",
                    help="pipeline = 按 pipeline.image_model（非成人的默认模型）")
    args = ap.parse_args()

    script = P.load_script()
    client = ComfyClient(args.comfy)
    loras = P.available_loras(client)
    results = json.loads((OUT / "results.json").read_text(encoding="utf-8")) if (OUT / "results.json").exists() else {}
    for shot_id in args.shots:
        ep, s = P.find_shot(script, shot_id)
        c = compile_shot(ep, s, script.globals, loras)
        if c.adult:
            print(f"{shot_id}: 成人镜头，跳过")
            continue
        ref = P.face_reference(c)
        if not ref:
            print(f"{shot_id}: 没有角色锁，跳过")
            continue
        P.check_face_lock_allowed(c)
        ref_name = client.upload_image(ref[1], subfolder="ns_final/refs")
        for k in range(args.seeds):
            seed = P.seed_for(shot_id + "/ab", k)
            row = {}
            m = {"pipeline": P.image_model(c), "turbo": P.QWEN_TURBO, "base": P.QWEN_BASE}[args.model]
            neg = P.image_negative(c)
            for arm in ("t2i", "edit"):
                if arm == "t2i":
                    wf = W.qwen_t2i(c.image_prompt, neg, *P.IMAGE_SIZE, seed, f"ns_final/ab/{shot_id}_t2i",
                                    m=m, loras=c.image_loras)
                else:
                    prompt = P.FACE_LOCK_PREFIX.format(name=ref[0]) + c.image_prompt
                    wf = W.qwen_edit(prompt, neg, ref_name, *P.IMAGE_SIZE, seed,
                                     f"ns_final/ab/{shot_id}_edit", m=m, loras=c.image_loras)
                entry, secs = client.run(wf, timeout_s=900)
                item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
                dest = OUT / f"{shot_id}_s{k}_{'turbo' if m.turbo else 'base'}_{arm}.png"
                client.download(item, dest)
                qc = nudity_qc(dest)
                row[arm] = {"file": dest.name, "seconds": round(secs, 1), "qc": qc}
                print(f"[{time.strftime('%H:%M:%S')}] {shot_id} s{k} {arm} {secs:.1f}s nudity={qc['nudity']}", flush=True)
            row["model"] = "turbo" if m.turbo else f"base_cfg{m.cfg}"
            if row["t2i"]["qc"]["nudity"] or row["edit"]["qc"]["nudity"]:
                row["compare"] = None  # 被质检拦下的图不拼对比图、不查看
                results[f"{shot_id}/s{k}/{row['model']}"] = row
                (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
                continue
            # 左 t2i / 中 edit / 右 参考图，统一缩到 960 高
            side = OUT / f"{shot_id}_s{k}_{row['model']}_compare.jpg"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error",
                            "-i", str(OUT / row["t2i"]["file"]), "-i", str(OUT / row["edit"]["file"]), "-i", str(ref[1]),
                            "-filter_complex",
                            "[0]scale=-2:960[a];[1]scale=-2:960[b];[2]scale=-2:960[c];[a][b][c]hstack=inputs=3",
                            "-q:v", "3", str(side)], check=False)
            row["seed"] = seed
            row["compare"] = side.name
            results[f"{shot_id}/s{k}/{row['model']}"] = row
            (OUT / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
