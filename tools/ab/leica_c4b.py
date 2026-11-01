"""fredw-92 补：C4b = C0 → lanczos 放大 1152×2016 → Base 模型重绘（参照 config/render_quality.json 定稿档第二遍：
euler / simple，steps 14，cfg 3.0，噪声种子 +1，texture_fix VAE），denoise 0.25 → PIL lanczos 缩回 768×1344。
LoRA 同 C：krea2 0.5 + lin_wan 0.6。三镜 ep02-S4/S1/S6。结果写进 data/ab/leica_sharp/settings.json（变体 C4b）。"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import xp_common as X  # noqa: E402
import leica_sharp as L  # noqa: E402
from ns_render import workflows as W            # noqa: E402
from ns_render.comfy_client import ComfyClient  # noqa: E402

Q = json.loads((X.ROOT / "config" / "render_quality.json").read_text(encoding="utf-8"))["tiers"]["final"]
STEPS = max(int(Q["pass2_min_steps"]), int(Q["steps"] * Q["pass2_steps_ratio"]))   # 14
DENOISE = 0.25
LORAS = [(L.KREA, 0.5), (L.LW, 0.6)]


def main():
    res = json.loads(L.SETTINGS.read_text(encoding="utf-8"))
    for shot, seed in L.SHOTS.items():
        rec = res["shots"][shot]
        if "C4b" in rec["variants"]:
            continue
        sd = L.OUT / shot
        key, url = L.wait_lane()
        cl = ComfyClient(url, timeout=120)
        init = cl.input_image(sd / "C0.png", "ns_final/ab")
        m = W.QwenModel(unet=Q["unet"], clip=Q["clip"], vae=Q["vae"], turbo=False, steps=STEPS, cfg=float(Q["cfg"]),
                        sampler=Q["sampler"])
        wf = W._qwen_graph(rec["prompt"], rec["negative"], L.BW, L.BH, int(seed) + int(Q["pass2_seed_offset"]),
                           f"ns_ab/leica_{shot}_C4b", m, LORAS, init_image=init, denoise=DENOISE)
        t0 = time.time()
        entry, _ = cl.run(wf, timeout_s=1800)
        item = next(f for f in cl.output_files(entry) if f["filename"].endswith(".png"))
        raw = cl.download(item, sd / "C4b_raw_1152x2016.png")
        L.down(raw, sd / "C4b.png")
        t1 = time.time()
        lane = f"gpu33 GPU{key}" if key in X.GPU33 else url
        rec["variants"]["C4b"] = {
            "file": "C4b.png", "raw_file": raw.name, "raw_size": [L.BW, L.BH], "lane": lane,
            "exec_s": X.exec_seconds(entry), "wall_s": round(t1 - t0, 1), "loras": [list(x) for x in LORAS],
            "gen_size": [L.BW, L.BH], "refine": True, "prompt_suffix": None,
            "params": {"init": "C0.png（本镜 C0 交付图）", "upscale": "ImageScale lanczos 768×1344 → 1152×2016",
                       "unet": Q["unet"], "vae": Q["vae"], "clip": Q["clip"], "sampler": Q["sampler"],
                       "scheduler": "simple", "steps": STEPS, "cfg": Q["cfg"], "denoise": DENOISE,
                       "noise_seed": int(seed) + int(Q["pass2_seed_offset"]), "downscale": "PIL lanczos → 768×1344",
                       "src": "config/render_quality.json tiers.final 第二遍（pass2_steps = max(8, 35×0.4) = 14；denoise 按要求 0.25）"}}
        L.SETTINGS.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
        X.log(f"leica_sharp {shot} C4b", lane, t0, t1, [sd / "C4b.png"], f"Base 14 步 denoise 0.25，exec {rec['variants']['C4b']['exec_s']} s")
        print(shot, "C4b", rec["variants"]["C4b"]["exec_s"], flush=True)


if __name__ == "__main__":
    main()
