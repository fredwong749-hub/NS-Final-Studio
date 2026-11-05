"""lens_sim v2 A/B（L-192 ③）：原图 | v1（现状）| v2（真实光学标定）| v2 变形椭圆 + 背景 / 脸局部放大。只做实验，不写生产配置。
  .venv/Scripts/python.exe -X utf8 tools/research/lens_sim_v2_ab.py [--only S4]
产物：data/ab/lens_sim_v2/（单图、深度 .npy、<shot>_sheet.png 对比表、v2.json）"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/render_router", "packages/schema", "packages/qc"):
    sys.path.insert(0, str(ROOT / _p))
from ns_render import lens_sim as LS  # noqa: E402

OUT = ROOT / "data" / "ab" / "lens_sim_v2"
# shot → (源图, 光学行（等同 K-WRT-816 的【光学】）, 备注)
SHOTS = {
    "S4": ("data/ab/lens_sim_fix/ep01-S4_a_current.png", "85mm｜T1.2｜高度=1.5m 眼平", "双人中近景；85mm f/1.2 极限档"),
    "S4_t2": ("data/ab/lens_sim_fix/ep01-S4_a_current.png", "50mm｜T2｜高度=1.5m 眼平", "同图按表内双人 50mm T2"),
    "S1": ("data/ab/lens_sim_fix/ep01-S1_a_current.png", "50mm｜T2｜高度=1.5m 眼平", "三人中景 50mm T2"),
    "S13": ("data/ab/look_v2/h4/ep01-S13_a.png", "85mm｜T1.4｜高度=1.5m 眼平", "近景 85mm T1.4；前景灯架 + 背景射灯 / 环形灯"),
}
V1 = {"enabled": True, "focus": "auto", "t_stop": 2.0, "focal_mm": 75.0}


def run_one(key: str, force_depth: bool = False) -> dict:
    src, optic, note = SHOTS[key]
    base = key.split("_")[0]
    im = Image.open(ROOT / src).convert("RGB")
    dpath = OUT / f"{base}_depth.npy"
    depth = None
    if dpath.exists() and not force_depth:
        depth = np.load(str(dpath))
    v1, _ = LS.apply(im, V1, depth=depth, depth_out=None if depth is not None else dpath)
    if depth is None:
        depth = np.load(str(dpath))
    spec = {"光学": optic}
    p2 = {"enabled": True, "focus": "auto", "optics_v2": {"enabled": True}}
    v2, rec = LS.apply(im, {**p2, "spec": spec}, depth=depth)
    p3 = {**p2, "optics_v2": {"enabled": True, "anamorphic": 1.8}, "spec": spec}
    v3, _ = LS.apply(im, p3, depth=depth)
    for nm, x in (("v1", v1), ("v2", v2), ("v2_ana", v3)):
        x.save(OUT / f"{key}_{nm}.png")
    # 局部：脸（焦点）+ 背景灯
    w, h = im.size
    fb = (rec.get("focus") or {}).get("face") or [w * .3, h * .1, w * .3, h * .2]
    fx, fy, fw, fh = [int(v) for v in fb[:4]]
    pad = int(fw * 0.5)
    face_box = (max(0, fx - pad), max(0, fy - pad // 2), min(w, fx + fw + pad), min(h, fy + fh + pad // 2))
    top_box = (0, 0, w, int(h * 0.30))
    def strip(box):
        cs = [x.crop(box) for x in (im, v1, v2, v3)]
        tw = 300
        cs = [c.resize((tw, int(c.height * tw / c.width))) for c in cs]
        return cs
    cols = 4
    thumb = [x.resize((w * 560 // h, 560)) for x in (im, v1, v2, v3)]
    tw_, th_ = thumb[0].size
    face_c, top_c = strip(face_box), strip(top_box)
    H = th_ + max(c.height for c in face_c) + max(c.height for c in top_c) + 70
    W = max(tw_, 300) * cols + 5 * 10
    sheet = Image.new("RGB", (W, H), (20, 20, 20))
    d = ImageDraw.Draw(sheet)
    labels = ["原图", "v1 现状", "v2 真实光学", "v2 + 变形椭圆"]
    for i in range(cols):
        x0 = 10 + i * (max(tw_, 300) + 10)
        sheet.paste(thumb[i], (x0, 20)); d.text((x0, 4), f"{labels[i]}  [{key}] {optic}", fill=(255, 255, 255))
        sheet.paste(face_c[i], (x0, th_ + 40)); sheet.paste(top_c[i], (x0, th_ + 50 + max(c.height for c in face_c)))
    d.text((10, th_ + 28), "脸局部（眼睛 / 耳朵软硬）", fill=(200, 200, 100))
    d.text((10, th_ + 40 + max(c.height for c in face_c)), "背景上部（灯 → 圆斑）", fill=(200, 200, 100))
    sheet.save(OUT / f"{key}_sheet.png")
    keep = {k: rec[k] for k in ("metric", "coc_bg_diam_px", "coc_max_diam_px", "hl_blobs", "hl_gain_max", "levels", "radius")}
    keep["note"] = note
    return keep


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="")
    ap.add_argument("--force-depth", action="store_true")
    a = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    res = {}
    for k in SHOTS:
        if a.only and a.only not in k:
            continue
        res[k] = run_one(k, a.force_depth)
        print(k, json.dumps(res[k], ensure_ascii=False))
    old = json.loads((OUT / "v2.json").read_text(encoding="utf-8")) if (OUT / "v2.json").exists() else {}
    old.update(res)
    import os
    _tmp = OUT / "v2.json.tmp"
    _tmp.write_text(json.dumps(old, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(_tmp, OUT / "v2.json")


if __name__ == "__main__":
    main()
