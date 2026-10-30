"""P2 X5：texture_ep02_S4 的 C、G 两个变体推到 ep02-S1 / S6 / S9 首帧（编译提示词原样、锁定 take 同种子）。
参数照 data/ab/texture_ep02_S4/settings.json（C、G）。输出 data/ab/texture_C_G_ep02/。用法：python tools/ab/xp_image.py render|sheets"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import xp_common as X  # noqa: E402
from ns_render import workflows as W            # noqa: E402
from ns_render import final_tier as FT          # noqa: E402
from ns_render import grade as G                # noqa: E402
from ns_render import pipeline as P             # noqa: E402
from ns_render.comfy_client import ComfyClient  # noqa: E402

OUT = X.AB / "texture_C_G_ep02"
OUT.mkdir(parents=True, exist_ok=True)
SETTINGS = OUT / "settings.json"
SRC = json.loads((X.AB / "texture_ep02_S4" / "settings.json").read_text(encoding="utf-8"))
CLAUSE = SRC["prompt_G_removed"] + "，"
TURBO_UNET = "qwen_image_2.1_turbo_int8_convrot.safetensors"
CLIP = SRC["clip"]
VAE_TF = "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"
KREA = "krea2_film_texture_qwen21.safetensors"
LW = "lin_wan_qi_v1.safetensors"
PW, PH = 768, 1344
SHOTS = ["ep02-S1", "ep02-S6", "ep02-S9"]


def final_graph(prompt, neg, seed, prefix, cfg, loras):   # 同 texture_ep02_S4 的 E/F/G（第一遍空 latent）
    m = FT.final_model(cfg)
    p1, p2 = tuple(cfg["pass1_size"]), tuple(cfg["pass2_size"])
    wf = W._qwen_graph(prompt, neg, p1[0], p1[1], seed, prefix, m, loras)
    wf.update({
        "50": {"class_type": "ImageScale", "inputs": {"image": ["41", 0], "upscale_method": "lanczos",
                                                      "width": p2[0], "height": p2[1], "crop": "disabled"}},
        "51": {"class_type": "VAEEncode", "inputs": {"pixels": ["50", 0], "vae": ["12", 0]}},
        "52": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed) + int(cfg.get("pass2_seed_offset", 1))}},
        "53": {"class_type": "BasicScheduler", "inputs": {"model": ["13", 0], "scheduler": cfg.get("scheduler", "simple"),
                                                          "steps": FT.pass2_steps(cfg), "denoise": float(cfg["pass2_denoise"])}},
        "54": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["52", 0], "guider": ["38", 0], "sampler": ["36", 0], "sigmas": ["53", 0],
                          "latent_image": ["51", 0]}},
        "55": {"class_type": "VAEDecode", "inputs": {"samples": ["54", 0], "vae": ["12", 0]}},
    })
    wf["90"]["inputs"]["images"] = ["55", 0]
    return wf


def locked_image(shot):
    from ns_render.h3_video import locked_n
    t = P.load_takes(shot)
    n = locked_n(t, "image")
    tk = next(x for x in t["takes"] if x["stage"] == "image" and x["n"] == n)
    return tk


def wait_lane():
    while True:
        for key, url in X.lanes().items():
            if key in ("1", "3"):
                continue
            if X.lane_free(key, url):
                return key, url
        time.sleep(20)


def render():
    cfg = FT.final_cfg()
    res = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {"shots": {}}
    res["note"] = ("C、G 参数取自 data/ab/texture_ep02_S4/settings.json；同镜同种子（锁定首帧 take 的种子）；"
                   "G 主图为调色版（final tier grade 0.6），另存 _raw")
    res["final_cfg"] = cfg
    for shot in SHOTS:
        c = X.get_json(f"{X.API}/api/shots/{shot}", 180)["compiled"]
        prompt, neg = c["image_prompt"], c.get("image_negative") or ""
        lk = locked_image(shot)
        seed = int(lk["seed"])
        rec = res["shots"].setdefault(shot, {"seed": seed, "prompt": prompt, "negative": neg,
                                             "locked": {"n": lk["n"], "file": lk["file"], "workflow": lk.get("workflow")},
                                             "variants": {}})
        g_prompt = prompt.replace(CLAUSE, "", 1)
        g_note = "去掉系统追加的“面部清晰对焦，五官锐利”" if g_prompt != prompt else "本镜提示词里没有“面部清晰对焦，五官锐利”，G 提示词与 C 相同（=E）"
        e_loras = FT.final_loras([(LW, 0.8)], {KREA, LW}, cfg)
        jobs = [
            ("C", SRC["variants"]["C"]["label"], prompt,
             W.qwen_t2i(prompt, neg, PW, PH, seed, f"ns_ab/tcg_{shot}_C",
                        W.QwenModel(unet=TURBO_UNET, clip=CLIP, vae=VAE_TF, turbo=True), [(KREA, 0.5), (LW, 0.6)]),
             SRC["variants"]["C"]["params"], False),
            ("G", SRC["variants"]["G"]["label"] + "；" + g_note, g_prompt,
             final_graph(g_prompt, neg, seed, f"ns_ab/tcg_{shot}_G", cfg, e_loras),
             dict(SRC["variants"]["G"]["params"], loras=[list(x) for x in e_loras],
                  pass2_seed=seed + int(cfg.get("pass2_seed_offset", 1))), True),
        ]
        for letter, label, p, wf, params, graded in jobs:
            if letter in rec["variants"]:
                continue
            key, url = wait_lane()
            cl = ComfyClient(url, timeout=120)
            t0 = time.time()
            entry, _ = cl.run(wf, timeout_s=2400)
            item = next(f for f in cl.output_files(entry) if f["filename"].endswith(".png"))
            name = f"{shot}_{letter}"
            if graded:
                raw = cl.download(item, OUT / f"{name}_raw.png")
                gc = cfg["grade"]
                gi = G.grade_file(raw, OUT / f"{name}.png", reference=X.ROOT / gc["reference"],
                                  strength=float(gc["strength"]), dark=bool(c.get("dark", False)))
                params = dict(params, grade_info=gi, raw_file=raw.name)
            else:
                cl.download(item, OUT / f"{name}.png")
            t1 = time.time()
            lane = f"gpu33 GPU{key}" if key in X.GPU33 else url
            rec["variants"][letter] = {"label": label, "file": f"{name}.png", "exec_s": X.exec_seconds(entry),
                                       "wall_s": round(t1 - t0, 1), "lane": lane, "prompt": p,
                                       "params": dict(params, seed=seed)}
            X.log(f"X5 texture C/G {shot} {letter}", lane, t0, t1, [OUT / f"{name}.png"])
            SETTINGS.write_text(json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
            print(shot, letter, rec["variants"][letter]["exec_s"], flush=True)


def sheets():
    from PIL import Image
    res = json.loads(SETTINGS.read_text(encoding="utf-8"))
    tiles = []
    for shot, rec in res["shots"].items():
        lk = rec["locked"]
        tiles.append((Image.open(P.DATA / lk["file"]).convert("RGB"), "锁",
                      f"{shot} 现锁定首帧 take n={lk['n']}（{lk.get('workflow')}，种子 {rec['seed']}）——参照，不是本轮产物"))
        for letter in ("C", "G"):
            v = rec["variants"].get(letter)
            if not v:
                continue
            pr = v["params"]
            lor = "，".join(f"{n.split('.')[0]} {s}" for n, s in pr.get("loras", []))
            extra = (f"两段式 {pr.get('pass1_size')}→{pr.get('pass2_size')} denoise {pr.get('pass2_denoise')} / "
                     f"{pr.get('pass2_steps')} 步 · 调色 0.6" if letter == "G" else "Turbo 8步 cfg1")
            tiles.append((Image.open(OUT / v["file"]).convert("RGB"), letter,
                          f"{shot} {v['label']}\n{pr.get('unet')} · {pr.get('vae')}\nLoRA {lor} · {extra}\n"
                          f"种子 {rec['seed']} · GPU {v['exec_s']} s"))
    X.sheet(tiles, OUT / "contact_sheet.jpg", 432, 756, cols=3, label_h=170, max_lines=8,
            title="ep02 S1/S6/S9 首帧 · texture 变体 C 与 G（参数同 texture_ep02_S4）· 每行：锁定版参照 | C | G")


if __name__ == "__main__":
    {"render": render, "sheets": sheets}[sys.argv[1]]()
