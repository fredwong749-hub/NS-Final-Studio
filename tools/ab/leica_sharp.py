"""fredw-92 插队：C 基础上的去磨皮 / 出锐度对比（只改技术参数，提示词逐字不变）。
镜头 ep02-S4 / S1 / S6 首帧，各用锁定版种子。输出 data/ab/leica_sharp/。
用法：python tools/ab/leica_sharp.py render | sheets <crops.json>"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import xp_common as X  # noqa: E402
from ns_render import workflows as W            # noqa: E402
from ns_render.comfy_client import ComfyClient  # noqa: E402

OUT = X.AB / "leica_sharp"
OUT.mkdir(parents=True, exist_ok=True)
SETTINGS = OUT / "settings.json"
C_SETTINGS = X.AB / "texture_ep02_S4" / "settings.json"

TURBO_UNET = "qwen_image_2.1_turbo_int8_convrot.safetensors"
CLIP = "qwen3vl_8b_int8_convrot.safetensors"
VAE_TF = "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"
KREA = "krea2_film_texture_qwen21.safetensors"
LW = "lin_wan_qi_v1.safetensors"
PW, PH = 768, 1344
BW, BH = 1152, 2016               # 1.5 倍
REFINE_DENOISE = 0.25
USM = dict(radius=1.2, percent=60, threshold=2)   # PIL UnsharpMask：半径 1.2、强度 0.6（=60%）、阈值 2

SHOTS = {"ep02-S4": 1585153822402, "ep02-S1": 52867195615437, "ep02-S6": 78710993331902}  # 锁定首帧 take 的种子

GPU_VARIANTS = {   # 名: (LoRA, 出图尺寸, 是否细节重绘)
    "C0": ([(KREA, 0.5), (LW, 0.6)], (PW, PH), False),
    "C1": ([(KREA, 0.5), (LW, 0.45)], (PW, PH), False),
    "C2": ([(LW, 0.6)], (PW, PH), False),
    "C3": ([(KREA, 0.5), (LW, 0.6)], (BW, BH), False),
    "C4": ([(KREA, 0.5), (LW, 0.6)], (PW, PH), True),
    "C7g": ([(KREA, 0.5), (LW, 0.45)], (PW, PH), True),
}


def suffixes() -> dict:
    """style_suffix_candidates.md 的“候选N：”行，原样（不改字）"""
    import re
    txt = (OUT / "style_suffix_candidates.md").read_text(encoding="utf-8")
    return {int(m.group(1)): m.group(2).strip() for m in re.finditer(r"^候选(\d)：(.+)$", txt, re.M)}


SUFFIX = suffixes()
SUFFIX_VARIANTS = {f"S{n}": n for n in SUFFIX}      # C0 参数 + 第 n 条后缀
SUFFIX_VARIANTS["Sstar_g"] = 1                          # C3 参数（1.5 倍出图）+ 第 1 条后缀；锐化后 = S★
for _n, _k in SUFFIX_VARIANTS.items():
    GPU_VARIANTS[_n] = GPU_VARIANTS["C3" if _n == "Sstar_g" else "C0"]


def variant_prompt(name, prompt):
    n = SUFFIX_VARIANTS.get(name)
    return prompt if n is None else prompt + "，" + SUFFIX[n]
LABELS = {
    "C0": "C 原样（对照）：Turbo 8步 cfg1 · TF VAE · krea2 0.5 + lin_wan 0.6 · 768×1344",
    "C1": "C · lin_wan 0.45（krea2 0.5）",
    "C2": "C · 不加 krea2（lin_wan 0.6）",
    "C3": "C · 1152×2016 出图（Turbo 8步）→ lanczos 缩回 768×1344",
    "C4": "C → lanczos 放大 1152×2016 → Turbo 重绘 denoise 0.25（sigmas \"0.25, 0\"，1 步，种子+1）→ lanczos 缩回",
    "C4b": "C0 → lanczos 放大 1152×2016 → Base 模型重绘（euler/simple 14 步 cfg3，denoise 0.25，种子+1，同 LoRA）→ lanczos 缩回",
    "C5": "C0 + unsharp mask（PIL：半径 1.2、强度 0.6、阈值 2）",
    "C6": "C3 + C5 锐化",
    "C7": "C1 + C4 重绘 + C5 锐化",
    **{f"S{n}": f"C0 参数 + 后缀候选{n}（原样，前加“，”）：{s}" for n, s in SUFFIX.items()},
    "Sstar": f"S★ = C6 技术组合（1152×2016 出图→缩回 + unsharp 1.2/0.6/2）+ 后缀候选1：{SUFFIX[1]}",
}


def model():
    return W.QwenModel(unet=TURBO_UNET, clip=CLIP, vae=VAE_TF, turbo=True)


def graph(prompt, neg, seed, prefix, loras, size, refine):
    wf = W.qwen_t2i(prompt, neg, size[0], size[1], seed, prefix, model(), loras)
    if refine:
        wf.update({
            "50": {"class_type": "ImageScale", "inputs": {"image": ["41", 0], "upscale_method": "lanczos",
                                                          "width": BW, "height": BH, "crop": "disabled"}},
            "51": {"class_type": "VAEEncode", "inputs": {"pixels": ["50", 0], "vae": ["12", 0]}},
            "52": {"class_type": "RandomNoise", "inputs": {"noise_seed": int(seed) + 1}},
            "53": {"class_type": "ManualSigmas", "inputs": {"sigmas": W.turbo_sigmas(REFINE_DENOISE)}},
            "54": {"class_type": "SamplerCustomAdvanced",
                   "inputs": {"noise": ["52", 0], "guider": ["38", 0], "sampler": ["36", 0], "sigmas": ["53", 0],
                              "latent_image": ["51", 0]}},
            "55": {"class_type": "VAEDecode", "inputs": {"samples": ["54", 0], "vae": ["12", 0]}},
        })
        wf["90"]["inputs"]["images"] = ["55", 0]
    return wf


def shot_prompt(shot):
    c = X.get_json(f"{X.API}/api/shots/{shot}", 180)["compiled"]
    prompt, neg = c["image_prompt"], c.get("image_negative") or ""
    note = "当前编译提示词（/api/shots compiled.image_prompt 原样）"
    if shot == "ep02-S4":
        cs = json.loads(C_SETTINGS.read_text(encoding="utf-8"))
        if cs["prompt_compiled"] != prompt or cs["negative"] != neg:
            prompt, neg = cs["prompt_compiled"], cs["negative"]
            note = "用 texture_ep02_S4 C 当时的提示词原样（当前编译结果已变）"
    return prompt, neg, note


def wait_lane():
    """优先 GPU0；gpu36 道若在配置里出现也可用（最多 2 个并发，本脚本串行只占 1 个）"""
    while True:
        for key, url in X.lanes().items():
            if key in ("1", "3"):
                continue            # 插队任务只用 GPU0 和 gpu36
            if X.lane_free(key, url):
                return key, url
        time.sleep(20)


def down(src: Path, dst: Path):
    from PIL import Image
    Image.open(src).convert("RGB").resize((PW, PH), Image.LANCZOS).save(dst)
    return dst


def usm(src: Path, dst: Path):
    from PIL import Image, ImageFilter
    Image.open(src).convert("RGB").filter(ImageFilter.UnsharpMask(**USM)).save(dst)
    return dst


def render():
    res = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {"shots": {}}
    res.update({"note": "C 系列去磨皮/锐度对比；同镜同种子、同提示词、同负面词；全部交付图 768×1344",
                "model": {"unet": TURBO_UNET, "clip": CLIP, "vae": VAE_TF, "sigmas": W.TURBO_SIGMAS, "cfg": 1.0,
                          "sampler": "euler"},
                "refine": {"upscale": "lanczos 1.5x → 1152×2016", "denoise": REFINE_DENOISE,
                           "sigmas": W.turbo_sigmas(REFINE_DENOISE), "noise_seed": "seed+1", "downscale": "PIL lanczos"},
                "unsharp": USM})
    for shot, seed in SHOTS.items():
        prompt, neg, pnote = shot_prompt(shot)
        sd = OUT / shot
        sd.mkdir(exist_ok=True)
        rec = res["shots"].setdefault(shot, {"seed": seed, "prompt": prompt, "negative": neg, "prompt_note": pnote,
                                             "variants": {}})
        for name, (loras, size, refine) in GPU_VARIANTS.items():
            if name in rec["variants"]:
                continue
            key, url = wait_lane()
            cl = ComfyClient(url, timeout=120)
            wf = graph(variant_prompt(name, prompt), neg, seed, f"ns_ab/leica_{shot}_{name}", loras, size, refine)
            miss = cl.check(wf)
            if miss:
                rec["variants"][name] = {"skipped": miss}
                continue
            t0 = time.time()
            entry, secs = cl.run(wf, timeout_s=1800)
            item = next(f for f in cl.output_files(entry) if f["filename"].endswith(".png"))
            dl = cl.download(item, sd / f"{name}_dl.png")
            t1 = time.time()
            from PIL import Image
            w, h = Image.open(dl).size
            if (w, h) == (PW, PH):
                final = dl.replace(sd / f"{name}.png")
            else:
                raw = dl.replace(sd / f"{name}_raw_{w}x{h}.png")
                final = down(raw, sd / f"{name}.png")
            rec["variants"][name] = {"file": final.name, "raw_size": [w, h], "lane": f"gpu33 GPU{key}" if key in X.GPU33 else url,
                                     "exec_s": X.exec_seconds(entry), "wall_s": round(t1 - t0, 1), "prompt_suffix": SUFFIX.get(SUFFIX_VARIANTS.get(name)),
                                     "loras": [list(x) for x in loras], "gen_size": list(size), "refine": refine}
            if (w, h) != (PW, PH):
                rec["variants"][name]["raw_file"] = f"{name}_raw_{w}x{h}.png"
            X.log(f"leica_sharp {shot} {name}", rec["variants"][name]["lane"], t0, t1, [sd / final.name])
            SETTINGS.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
            print(shot, name, rec["variants"][name]["exec_s"], flush=True)
        # CPU 后处理
        v = rec["variants"]
        for name, src in (("C5", "C0"), ("C6", "C3"), ("C7", "C7g"), ("Sstar", "Sstar_g")):
            if src in v and "file" in v[src]:
                usm(sd / v[src]["file"], sd / f"{name}.png")
                v[name] = {"file": f"{name}.png", "from": src, "unsharp": USM,
                           "exec_s": v[src]["exec_s"], "wall_s": v[src]["wall_s"], "lane": v[src]["lane"]}
        SETTINGS.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")


BOX_GROUP = {"C4b": "C0", "C5": "C0", "C6": "C3", "C7": "C7g", "Sstar": "Sstar_g"}  # 锐化版与源图同构图
ORDER = ["C0", "C1", "C2", "C3", "C4", "C4b", "C5", "C6", "C7", "S1", "S2", "S3", "S4", "S5", "Sstar"]


def sheets(crops_path=None):
    from PIL import Image
    res = json.loads(SETTINGS.read_text(encoding="utf-8"))
    crops = json.loads(Path(crops_path).read_text(encoding="utf-8")) if crops_path else {}
    for shot, rec in res["shots"].items():
        sd = OUT / shot
        tiles, cp = [], []
        locked = None
        for name in ORDER:
            v = rec["variants"].get(name)
            if not v or "file" not in v:
                continue
            im = Image.open(sd / v["file"]).convert("RGB")
            loras = " + ".join(f"{n.split('.')[0].split('_qwen')[0]} {s}" for n, s in
                               (v.get("loras") or rec["variants"][v.get("from", name)].get("loras", [])))
            t = f"{LABELS[name]}\nLoRA: {loras} · 种子 {rec['seed']}\nGPU 算力 {v['exec_s']} s"
            if name in ("C5", "C6", "C7"):
                t += "（GPU 部分）+ CPU 锐化"
            tiles.append((im, name, t))
            for ck, spec in (crops.get(shot) or {}).items():
                x0, y0, s = spec.get(name) or spec.get(BOX_GROUP.get(name, "")) or spec["default"]
                cp.append((ck, im.crop((x0, y0, x0 + s, y0 + s)), name, [x0, y0, s]))
        X.sheet(tiles, sd / "contact_sheet.jpg", 432, 756, cols=4, label_h=160, max_lines=7,
                title=f"{shot} 首帧 · C 系列锐度对比 · 种子 {rec['seed']} · 提示词逐字相同（{rec['prompt_note']}）")
        for ck in (crops.get(shot) or {}):
            items = [(im, n, f"框 x0,y0,边={b}")
                     for k, im, n, b in cp if k == ck]
            s = items[0][0].size[0]
            X.sheet(items, sd / f"crop_{ck}_1to1.png", s, s, cols=4, label_h=70, max_lines=3,
                    title=f"{shot} {ck} 局部 1:1 原尺寸（768×1344 交付图上裁，框按各图构图定位）")




def overview():
    res = json.loads(SETTINGS.read_text(encoding="utf-8"))
    L = ["# leica_sharp 总览：C 系列锐度技术变体 + 写作模型风格后缀（只列参数与文件，不评优劣，由项目方选）", "",
         f"- 公共参数：{res['model']['unet']} · {res['model']['clip']} · {res['model']['vae']} · euler · ManualSigmas 8 步 `{res['model']['sigmas']}` · cfg 1",
         f"- 细节重绘（C4/C7）：{res['refine']}",
         f"- 锐化（C5/C6/C7/S★）：PIL UnsharpMask {res['unsharp']}（percent 60 = 强度 0.6）",
         "- 后缀：data/ab/leica_sharp/style_suffix_candidates.md 的候选原样，前加“，”接在编译后首帧提示词末尾；其余提示词逐字不变",
         "- 交付图全部 768×1344；1.5 倍出图的原图另存 *_raw_1152x2016.png", ""]
    for shot, rec in res["shots"].items():
        L += [f"## {shot}（种子 {rec['seed']}）", "",
              f"- 提示词来源：{rec['prompt_note']}",
              f"- 拼图：data/ab/leica_sharp/{shot}/contact_sheet.jpg；局部 1:1：data/ab/leica_sharp/{shot}/crop_face_1to1.png、crop_hand_1to1.png", "",
              "| 变体 | 文件 | 参数 | LoRA | 生成尺寸 | 后缀 | GPU 秒 | 道 |", "|---|---|---|---|---|---|---|---|"]
        for name in ORDER:
            v = rec["variants"].get(name)
            if not v or "file" not in v:
                continue
            src = rec["variants"].get(v.get("from", name), v)
            suf = src.get("prompt_suffix") or "—"
            L.append(f"| {'S★' if name == 'Sstar' else name} | data/ab/leica_sharp/{shot}/{v['file']} | {LABELS[name]} | "
                     f"{'；'.join(f'{a} {b}' for a, b in src.get('loras', []))} | {src.get('gen_size')} | {suf} | {v['exec_s']} | {v['lane']} |")
        L.append("")
    (OUT / "overview.md").write_text("\n".join(L), encoding="utf-8")


if __name__ == "__main__":
    {"render": render, "overview": overview, "sheets": lambda: sheets(sys.argv[2] if len(sys.argv) > 2 else None)}[sys.argv[1]]()
