"""写实 / 去塑料感 A/B（项目方 11-02 12:1x：“太塑料感……不够真人美女的细腻感，肤色、腿的肤色等细节”）。
scope=ab：图只进 data/ab/imglab/realism/<round>/，不写 takes / 设定图登记；S★ R0 生产不动（L-087），新方案只作候选给项目方看。

臂的定义放数据文件（冻结期也能改）：data/ab/imglab/realism/arms.json
  {"<arm>": {"kind": "sheet" | "klein" | "moss" | "refine",
             "cfg": 3.0, "steps": 25, "negative": "...", "replace": [["旧", "新"]], "append": "...",
             "loras": [["niceasians_qwen21.safetensors", 0.6]], "vae": "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors",
             "refine": {"unet": "...", "loras": [...], "prompt": "...", "steps": 8, "denoise": 0.35},   # kind=refine：拿现行设定图做低 denoise 二次精修
             "params": {...}}}                                                                        # kind=klein/moss：tools/imglab/bases.py 参数覆盖
sheet 臂复用 tools/assetmaster/gen_look_sheets.graph_for（与现行 s2 设定图同一张图），只改臂里写的字段。

    .venv/Scripts/python.exe tools/imglab/realism_ab.py run --round r1 --key lin_wan_lookD --seed 202 --arms SH1,SH2 --lane http://127.0.0.1:18289
    .venv/Scripts/python.exe tools/imglab/realism_ab.py score --round r1
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for p in ("services/render_router", "services/agent", "packages/schema", "tools/pipeline", "tools/series10_imggen", "tools/assetmaster",
          "tools/imglab", "tools/gen_contract"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))
BASE = ROOT / "data/ab/imglab/realism"
ARMS = BASE / "arms.json"


def _resolve_uploads(g: dict, up) -> dict:
    for n in g.values():
        for k, v in list(n["inputs"].items()):
            if isinstance(v, str) and v.startswith("@upload:"):
                n["inputs"][k] = up(ROOT / v[len("@upload:"):])
    return g


S2_RES = ROOT / "data/assetmaster/sheets_s2/results.json"


def _s2_graph(key: str, seed: int, prefix: str):
    """第二季造型设定图（data/assetmaster/sheets_s2/results.json 记录的原提示词 / 身份脸 / 单品）按原工作流重建：
    tools/ab/char_sheet_qi21.graph（Qwen-Image 2.1 base int8 + AnyAngle 0.6，25 步 cfg 1 euler/simple，参考分辨率 2048），
    参考 = [身份脸, 四栏姿势模板, 单品参考板]，画幅同现行 1984×1120"""
    sys.path.insert(0, str(ROOT / "tools/ab"))
    import char_sheet_qi21 as CS
    import flux_gen as FG
    r = json.loads(S2_RES.read_text(encoding="utf-8"))[key][str(seed)]
    bd = FG.board([str(ROOT / f) for f in r["items"]], BASE / "boards" / f"{key}.png")
    refs = ["@upload:" + r["face"], "@upload:" + CS.POSE.relative_to(ROOT).as_posix(),
            "@upload:" + Path(bd).resolve().relative_to(ROOT.resolve()).as_posix()]
    g = CS.graph(r["prompt"], refs, seed, 1984, 1120, prefix, ref_res=2048)
    return g, r["prompt"], None


def sheet_graph(key: str, seed: int, arm: dict, prefix: str):
    import gen_look_sheets as GL
    try:
        g, prompt, _ch = GL.graph_for(key, seed)
    except KeyError:                        # 第二季造型不在 SERIES 设定图作业里 → 按 sheets_s2 记录重建
        g, prompt, _ch = _s2_graph(key, seed, prefix)
    g = copy.deepcopy(g)
    enc = next(n for n in g.values() if n.get("class_type") == "TextEncodeQwenImage21")
    ks = next(n for n in g.values() if n.get("class_type") in ("KSampler", "KSamplerAdvanced"))
    for old, new in arm.get("replace") or []:
        prompt = prompt.replace(old, new)
    if arm.get("append"):
        prompt = prompt + " " + arm["append"]
    enc["inputs"]["prompt"] = prompt
    if "negative" in arm:
        enc["inputs"]["negative_prompt"] = arm["negative"]
    for k in ("cfg", "steps"):
        if k in arm:
            ks["inputs"][k] = arm[k]
    if arm.get("vae"):
        next(n for n in g.values() if n.get("class_type") == "VAELoader")["inputs"]["vae_name"] = arm["vae"]
    model = ks["inputs"]["model"]
    for i, (name, w) in enumerate(arm.get("loras") or []):
        nid = f"97{i}"
        g[nid] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": name, "strength_model": float(w)}}
        model = [nid, 0]
    ks["inputs"]["model"] = model
    save = next(n for n in g.values() if n.get("class_type") == "SaveImage")
    save["inputs"]["filename_prefix"] = prefix
    return g, prompt


def refine_graph(src_name: str, arm: dict, seed: int, w: int, h: int, prefix: str) -> dict:
    """现行设定图 → 低 denoise 二次精修（VAEEncode → KSampler denoise<1，2.1 编辑：原图同时作 image_1 参考）"""
    r = arm["refine"]
    g = {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": r.get("unet", "qwen_image_2.1_turbo_int8_convrot.safetensors"), "weight_dtype": "default"}},
         "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": "qwen3vl_8b_int8_convrot.safetensors", "type": "qwen_image", "device": "default"}},
         "3": {"class_type": "VAELoader", "inputs": {"vae_name": r.get("vae", "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors")}},
         "4": {"class_type": "LoadImage", "inputs": {"image": src_name}},
         "5": {"class_type": "ImageScale", "inputs": {"image": ["4", 0], "upscale_method": "lanczos", "width": w, "height": h, "crop": "disabled"}},
         "6": {"class_type": "VAEEncode", "inputs": {"pixels": ["5", 0], "vae": ["3", 0]}},
         "7": {"class_type": "TextEncodeQwenImage21", "inputs": {"clip": ["2", 0], "prompt": r["prompt"], "negative_prompt": r.get("negative", ""),
                                                                "resolution": 0, "vae": ["3", 0], "images.image_1": ["5", 0]}}}
    model = ["1", 0]
    for i, (name, wt) in enumerate(r.get("loras") or []):
        g[f"8{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": name, "strength_model": float(wt)}}
        model = [f"8{i}", 0]
    g["20"] = {"class_type": "KSampler", "inputs": {"model": model, "positive": ["7", 0], "negative": ["7", 1], "latent_image": ["6", 0], "seed": seed,
                                                    "steps": int(r.get("steps", 8)), "cfg": float(r.get("cfg", 1.0)), "sampler_name": r.get("sampler", "euler"),
                                                    "scheduler": r.get("scheduler", "simple"), "denoise": float(r.get("denoise", 0.35))}}
    g["21"] = {"class_type": "VAEDecode", "inputs": {"samples": ["20", 0], "vae": ["3", 0]}}
    g["90"] = {"class_type": "SaveImage", "inputs": {"images": ["21", 0], "filename_prefix": prefix}}
    return g


def lane_idle(url: str) -> bool:
    import urllib.request
    try:
        q = json.loads(urllib.request.urlopen(url + "/queue", timeout=10).read())
        return not (q["queue_running"] or q["queue_pending"])
    except Exception:  # noqa: BLE001  # arch-ok: 连不上按忙处理（不交单）
        return False


def run(rnd: str, key: str, seed: int, arms: list[str], lane: str, src_sheet: str | None) -> None:
    from PIL import Image
    from ns_render.comfy_client import ComfyClient
    import bases as BS
    spec = json.loads(ARMS.read_text(encoding="utf-8"))
    d = BASE / rnd
    d.mkdir(parents=True, exist_ok=True)
    log = d / "takes.jsonl"
    client = ComfyClient(lane)
    up = lambda p: client.upload_image(Path(p), subfolder="ns_ab/imglab")  # noqa: E731
    for arm in arms:
        a = spec[arm]
        while not lane_idle(lane):
            time.sleep(5)
        prefix = f"ns_ab/imglab/realism/{rnd}/{key}_{arm}_s{seed}"
        kind = a.get("kind", "sheet")
        if kind == "sheet":
            g, prompt = sheet_graph(key, seed, a, prefix)
            g = _resolve_uploads(g, up)
        elif kind == "refine":
            src = ROOT / (src_sheet or f"data/assetmaster/sheets_s2/{key}_s{seed}.png")
            w, h = Image.open(src).size
            g = refine_graph(up(src), a, seed + int(a["refine"].get("seed_offset", 1)), w - w % 16, h - h % 16, prefix)   # 精修换种子（Qwen #61：同种子出蚀刻纹）
            prompt = a["refine"]["prompt"]
        elif kind in ("fashion_qwen", "fashion_klein", "fashion_moss"):
            # 时尚大片预设（项目方 12:5x：W 杂志式高饱和棚拍 / 外景）：单张人像，不是四栏设定图。参考 = [L-086 身份脸, 本造型单品板]；
            # Qwen 走生产唯一出图路径 unified_frame.build_graph（S★ 参数不动，只换提示词）；Klein / MOSS 走 tools/imglab/bases.py
            prompt = a["prompt"]
            refs = [ROOT / r for r in a.get("refs") or []]
            if kind == "fashion_qwen":
                from ns_render import unified_frame as UF
                g, _eff, prompt = UF.build_graph({"prompt": prompt, "refs": [str(r.relative_to(ROOT)) for r in refs]}, seed, up, prefix)
                if a.get("loras"):
                    src = g["13"]["inputs"]["model"]
                    for i, (name, w) in enumerate(a["loras"]):
                        g[f"97{i}"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": src, "lora_name": name, "strength_model": float(w)}}
                        src = [f"97{i}", 0]
                    g["13"]["inputs"]["model"] = src
            else:
                base = kind.split("_")[1]
                names = [up(r) for r in refs] if base == "klein" or (a.get("params") or {}).get("use_edit_lora") else []
                g = BS.build(base, prompt, names, seed, prefix, a.get("params"))
        else:
            g0, prompt = sheet_graph(key, seed, {}, prefix)
            refs = [n["inputs"]["image"] for n in g0.values() if n.get("class_type") == "LoadImage"]
            names = [up(ROOT / r[len("@upload:"):]) if str(r).startswith("@upload:") else r for r in refs]
            for old, new in a.get("replace") or []:
                prompt = prompt.replace(old, new)
            g = BS.build(kind, prompt, names, seed, prefix, a.get("params"))
        t0 = time.time()
        entry, secs = client.run(g, timeout_s=2400)
        item = next(f for f in client.output_files(entry) if f["filename"].endswith(".png"))
        out = d / f"{key}_{arm}_s{seed}.png"
        client.download(item, out)
        rec = {"scope": "ab", "experiment": "imglab_realism", "round": rnd, "key": key, "arm": arm, "seed": seed, "spec": a,
               "file": out.relative_to(ROOT).as_posix(), "comfy_s": round(secs, 1), "wall_s": round(time.time() - t0, 1),
               "prompt": prompt, "lane": lane, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
        with log.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        print(json.dumps({k: rec[k] for k in ("key", "arm", "seed", "comfy_s")}, ensure_ascii=False), flush=True)


def skin_metrics(path: Path) -> dict:
    """皮肤质感旁证（只作相对比较，阈值未标定）：最大脸框内皮肤区的高频能量（Laplacian 方差）、YCrCb 肤色掩膜内 Lab 的 a*/b* 标准差
    （肤色不均 = 真实感的一部分）、镜面高光占比（V>0.95 且 S<0.15 的像素比例，塑料高光越多越高）"""
    import cv2
    import numpy as np
    img = cv2.imread(str(path))
    ycc = cv2.cvtColor(img, cv2.COLOR_BGR2YCrCb)
    skin = cv2.inRange(ycc, (0, 135, 85), (255, 180, 135)) > 0
    if skin.sum() < 500:
        return {"skin_px": int(skin.sum())}
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY).astype(np.float64)
    lap = cv2.Laplacian(gray, cv2.CV_64F)
    lab = cv2.cvtColor(img, cv2.COLOR_BGR2LAB).astype(np.float64)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV).astype(np.float64) / 255.0
    spec = (hsv[..., 2] > 0.95) & (hsv[..., 1] < 0.15) & skin
    return {"skin_px": int(skin.sum()), "skin_hf": round(float(lap[skin].var()), 1),
            "skin_a_std": round(float(lab[..., 1][skin].std()), 2), "skin_b_std": round(float(lab[..., 2][skin].std()), 2),
            "spec_ratio": round(float(spec.sum() / skin.sum()), 4)}


def score(rnd: str, host: str = "gpu33") -> None:
    import remote_score as RS
    d = BASE / rnd
    recs = [json.loads(ln) for ln in (d / "takes.jsonl").read_text(encoding="utf-8").splitlines()]
    files = {f"{r['key']}|{r['arm']}|{r['seed']}": r["file"] for r in recs}
    base_key = recs[0]["key"]
    cur = ROOT / f"data/assetmaster/sheets_s2/{base_key}_s{recs[0]['seed']}.png"
    if cur.exists():
        files[f"{base_key}|S0_current|{recs[0]['seed']}"] = cur.relative_to(ROOT).as_posix()
    m = RS.score_local_files(host, files)
    out = {}
    for k, f in files.items():
        faces = ((m.get("items") or {}).get(k) or {}).get("faces") or []
        big = max(faces, key=lambda x: x.get("h_ratio") or 0) if faces else {}
        sims = big.get("sims") or {}
        out[k] = {"file": f, "q1_lin_wan": sims.get("lin_wan"), "q1_topk": max([v for kk, v in sims.items() if kk.startswith("lin_wan")] or [None]),
                  "faces": len(faces), "hands": (m.get("hands") or {}).get(k), **skin_metrics(ROOT / f)}
    tmp = d / "scores.json.tmp"
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, d / "scores.json")
    for k, v in out.items():
        print(k, {x: v.get(x) for x in ("q1_lin_wan", "q1_topk", "skin_hf", "skin_a_std", "spec_ratio")})


def main(argv=None) -> int:
    os.chdir(ROOT)
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["run", "score"])
    ap.add_argument("--round", required=True)
    ap.add_argument("--key", default="lin_wan_lookD")
    ap.add_argument("--seed", type=int, default=202)
    ap.add_argument("--arms", default="")
    ap.add_argument("--lane", default="http://127.0.0.1:18289")
    ap.add_argument("--src", default=None, help="refine 臂的源设定图（缺省 data/assetmaster/sheets_s2/<key>_s<seed>.png）")
    a = ap.parse_args(argv)
    if a.cmd == "run":
        run(a.round, a.key, a.seed, [x for x in a.arms.split(",") if x], a.lane, a.src)
    else:
        score(a.round)
    return 0


if __name__ == "__main__":
    sys.exit(main())
