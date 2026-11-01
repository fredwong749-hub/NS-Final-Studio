"""林晚脸部汇总图 data/ab/lin_wan_face_summary.jpg：texture_ep02_S4（A–G）、leica_sharp（三镜 C0–C7、C4b、S1–S5、S★）、
realphoto_lora（三镜 R0–R6）。每张图用 NudeNet 找脸（FACE_*），多张脸时取周围蓝色头发占比最高的那张（林晚蓝发），
以脸框中心取正方形 1:1 原像素裁切（边长 = 1.6 × 脸框长边），再统一缩放到同一高度。框位置写进 face_summary_boxes.json。"""
import colorsys
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).parent))
import xp_common as X  # noqa: E402

AB = X.AB
TILE = 320
LABEL_H = 92
ROW_HEAD = 230
PAD = 6


def short_lora(loras):
    m = {"krea2_film_texture_qwen21": "krea2", "lin_wan_qi_v1": "lw", "canon_qwen21": "canon"}
    out = []
    for n, s in loras or []:
        k = Path(n).stem
        out.append(f"{m.get(k, k[:14])} {s:g}")
    return " + ".join(out)


def items():
    rows = []
    t = json.loads((AB / "texture_ep02_S4" / "settings.json").read_text(encoding="utf-8"))
    tex = []
    for k in "ABCDEFG":
        v = t["variants"][k]
        p = v["params"]
        size = p.get("pass2_size") or p.get("size")
        model = "Turbo 8步" if "turbo" in p["unet"] else (f"Base {p['steps']}步 cfg{p['cfg']:g}" + (" 两段式" if p.get("pass2_size") else ""))
        vae = "TF VAE" if "texture_fix" in p["vae"] else "普通 VAE"
        extra = " · 调色0.6" if v.get("params", {}).get("grade") or k in "EFG" else ""
        extra += " · 去“面部清晰对焦”" if k == "G" else ""
        tex.append((k, AB / "texture_ep02_S4" / v["file"], f"{model} · {vae} · {size[0]}×{size[1]}\n{short_lora(p['loras'])}{extra}"))
    rows.append(("ep02-S4", "texture_ep02_S4", tex))
    lz = json.loads((AB / "leica_sharp" / "settings.json").read_text(encoding="utf-8"))
    rp = json.loads((AB / "realphoto_lora" / "settings.json").read_text(encoding="utf-8"))
    order = ["C0", "C1", "C2", "C3", "C4", "C4b", "C5", "C6", "C7", "S1", "S2", "S3", "S4", "S5", "Sstar"]
    sharp = {"C5", "C6", "C7", "Sstar"}
    refine = {"C4": "Turbo重绘1步", "C4b": "Base重绘14步 d0.25", "C7": "Turbo重绘1步"}
    for shot in ("ep02-S4", "ep02-S1", "ep02-S6"):
        rec = lz["shots"][shot]
        cells = []
        for n in order:
            v = rec["variants"].get(n)
            if not v or "file" not in v:
                continue
            src = rec["variants"].get(v.get("from", n), v)
            gs = src.get("gen_size") or [768, 1344]
            suf = f" · 后缀{n[1]}" if n in ("S1", "S2", "S3", "S4", "S5") else (" · 后缀1" if n == "Sstar" else "")
            info = (f"Turbo 8步 · 出图 {gs[0]}×{gs[1]}" + (f" · {refine[n]}" if n in refine else "") + "\n" +
                    short_lora(src.get("loras")) + (" · 锐化 USM1.2/0.6/2" if n in sharp else "") + suf)
            cells.append(("S★" if n == "Sstar" else n, AB / "leica_sharp" / shot / v["file"], info))
        rows.append((shot, "leica_sharp", cells))
        if shot in rp["shots"]:
            cells = []
            for n, v in rp["shots"][shot]["variants"].items():
                cells.append((n, AB / "realphoto_lora" / v["file"],
                              f"Turbo 8步 · 768×1344 · {v.get('label', '')}\n{short_lora(v.get('loras'))}"))
            rows.append((shot, "realphoto_lora", cells))
    # 同镜头放一起：S4 三行、S1 两行、S6 两行
    rank = {"ep02-S4": 0, "ep02-S1": 1, "ep02-S6": 2}
    return sorted(rows, key=lambda r: rank[r[0]])


def blue_score(im: Image.Image, box) -> float:
    x, y, w, h = box
    W, H = im.size
    reg = im.crop((max(0, x - w // 2), max(0, y - h // 2), min(W, x + w + w // 2), min(H, y + h + h // 2)))
    a = np.asarray(reg.resize((64, 64)).convert("HSV"), dtype=np.float32)
    hue, sat, val = a[..., 0] * 360 / 255, a[..., 1] / 255, a[..., 2] / 255
    return float(((hue > 190) & (hue < 250) & (sat > 0.25) & (val > 0.15)).mean())


def face_box(det, path: Path, im: Image.Image):
    faces = [d for d in det.detect(str(path)) if d["class"].startswith("FACE")]
    if not faces:
        return None, None
    best = max(faces, key=lambda d: blue_score(im, d["box"]) + 0.05 * d["score"])
    x, y, w, h = best["box"]
    s = int(1.6 * max(w, h))
    cx, cy = x + w / 2, y + h / 2
    W, H = im.size
    s = min(s, W, H)
    x0 = int(min(max(0, cx - s / 2), W - s))
    y0 = int(min(max(0, cy - s / 2), H - s))
    return [x0, y0, s], best


def main():
    from nudenet import NudeDetector
    det = NudeDetector()
    rows = items()
    ncol = max(len(r[2]) for r in rows)
    Wt = ROW_HEAD + ncol * (TILE + PAD) + PAD
    Ht = 70 + len(rows) * (TILE + LABEL_H + PAD) + PAD
    sheet = Image.new("RGB", (Wt, Ht), (22, 22, 22))
    dr = ImageDraw.Draw(sheet)
    f_t, f_h, f_n, f_s = X.font(30), X.font(22), X.font(24), X.font(15)
    dr.text((PAD, 14), "林晚脸部汇总 · 每格 = 该图林晚脸部 1:1 原像素正方形裁切（按各图人脸位置定框，边长=1.6×脸框），统一缩放到同一高度 "
            f"{TILE}px；格下：变体 / 关键参数 / 原裁切边长", fill=(255, 255, 255), font=f_t)
    boxes = {}
    for ri, (shot, exp, cells) in enumerate(rows):
        y = 70 + ri * (TILE + LABEL_H + PAD)
        for j, ln in enumerate([shot, exp]):
            dr.text((PAD, y + 10 + j * 30), ln, fill=(255, 220, 80) if j == 0 else (200, 200, 200), font=f_h)
        for ci, (name, path, info) in enumerate(cells):
            x = ROW_HEAD + PAD + ci * (TILE + PAD)
            im = Image.open(path).convert("RGB")
            box, d = face_box(det, path, im)
            key = f"{exp}/{shot}/{name}"
            if box is None:
                dr.rectangle((x, y, x + TILE, y + TILE), outline=(120, 0, 0))
                dr.text((x + 8, y + 8), "未检出人脸", fill=(255, 80, 80), font=f_n)
                boxes[key] = None
            else:
                x0, y0, s = box
                crop = im.crop((x0, y0, x0 + s, y0 + s)).resize((TILE, TILE), Image.LANCZOS)
                sheet.paste(crop, (x, y))
                boxes[key] = {"file": str(path.relative_to(X.ROOT)), "box_x0_y0_side": box, "image_size": list(im.size),
                              "face_det": d["box"], "det_score": round(d["score"], 3)}
            dr.text((x + 4, y + TILE + 2), name, fill=(255, 220, 80), font=f_n)
            lines = info.split("\n") + ([f"原裁切 {box[2]}px（图 {im.size[0]}×{im.size[1]}）"] if box else [])
            ly = y + TILE + 4
            for k, ln in enumerate(lines):
                for wl in X.wrap(dr, ln, f_s, TILE - (50 if k == 0 else 4))[:2 if k == 0 else 1]:
                    dr.text((x + (48 if k == 0 and ly < y + TILE + 26 else 4), ly), wl, fill=(230, 230, 230), font=f_s)
                    ly += 19
    out = AB / "lin_wan_face_summary.jpg"
    sheet.save(out, quality=94)
    (AB / "face_summary_boxes.json").write_text(json.dumps(boxes, ensure_ascii=False, indent=1), encoding="utf-8")
    print(out, sheet.size, sum(1 for b in boxes.values() if b is None), "missing")


if __name__ == "__main__":
    main()
