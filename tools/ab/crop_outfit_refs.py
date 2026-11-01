"""CONSIST：从项目方选定的 ep02 造型版设定图裁 Ref2VA「造型参考」。
第二栏（正面全身）→ full（全身，中景及更远用）、half（头顶到大腿中部，中近景用）。按非白列分栏，不靠固定比例。
输出 data/assets/identity_refs/<角色>/ep02_outfit/，sha256 写入 manifest.json 的 ep02_outfit 段。"""
import hashlib, json
from pathlib import Path
import numpy as np
from PIL import Image

R = Path(__file__).resolve().parents[2]
SRC = {"lin_wan": ("data/ab/char_sheets/outfit/lin_wan_ep02_L1office_img1sheetA202_s301.png", "ar-ac4bcb9fd1"),
       "chen_yu": ("data/ab/char_sheets/outfit/chen_yu_ep02_W7casual_img1facecrop_s401.png", "ar-907a5f8c53"),
       "gu_chen": ("data/ab/char_sheets/gu_chen/gu_chen_sheet_T_s101.png", "ar-2aba2488fa")}


def panels(a):
    ink = (a.min(axis=2) < 235)
    col = ink.sum(axis=0) > 3
    segs, s = [], None
    for x, v in enumerate(col):
        if v and s is None: s = x
        if not v and s is not None:
            if x - s > 40: segs.append((s, x))
            s = None
    if s is not None: segs.append((s, len(col)))
    return segs, ink


man = json.loads((R / "data/assets/identity_refs/manifest.json").read_text(encoding="utf-8"))
out = {}
for c, (rel, ref_id) in SRC.items():
    im = Image.open(R / rel).convert("RGB"); a = np.asarray(im)
    segs, ink = panels(a)
    segs = [s for s in segs if s[0] > a.shape[1] * 0.28]          # 跳过左栏大头（可能贴边无白隔）
    x0, x1 = segs[0]
    rows = np.where(ink[:, x0:x1].any(axis=1))[0]; y0, y1 = int(rows[0]), int(rows[-1])
    m = 24
    full = im.crop((max(0, x0 - m), max(0, y0 - m), min(a.shape[1], x1 + m), min(a.shape[0], y1 + m)))
    fh = full.size[1]
    half = full.crop((0, 0, full.size[0], int(fh * 0.58)))
    d = R / "data/assets/identity_refs" / c / "ep02_outfit"; d.mkdir(parents=True, exist_ok=True)
    rec = {"source_sheet": rel, "asset_ref_id": ref_id}
    for k, img in (("full", full), ("half", half)):
        p = d / f"{c}_ep02_outfit_{k}.png"; img.save(p)
        rec[k] = {"file": str(p.relative_to(R)).replace("\\", "/"), "size": list(img.size),
                  "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
    out[c] = rec
    print(c, segs[:3], rec["full"]["size"], rec["half"]["size"])
man["ep02_outfit"] = {"by": "owner", "owner_quote": "a", "meaning": "林晚-O1 + 陈宇-O1，顾沉沿用 s101",
                      "usage": "中景及更远：<Picture N> 加 full（或中近景用 half）作造型参考；身份仍用 *_face_ref2va.png",
                      "method": "第二栏正面全身按非白列分栏裁出（留 24 px 白边）；half = full 上 58%（头顶到大腿中部）",
                      "chars": out}
(R / "data/assets/identity_refs/manifest.json").write_text(json.dumps(man, ensure_ascii=False, indent=1), encoding="utf-8")
