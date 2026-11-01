"""
DIR：脸部泛红逐帧追踪 —— 同一镜的多个版本（生成原片 / 去抖后 / 调色后 / 成片段落 / 关键帧图）逐帧对比林晚脸颊红度，
定位泛红出现在哪一步、哪几帧。只测像素，不看内容。

用法（.venv python）：
  .venv/Scripts/python.exe tools/ep02_director/red_trace.py <输出名> 名=视频.mp4[@起点秒] ... [kf=关键帧.png]
  例：red_trace.py S1_pika raw=data/ab/motion_fix/renders/S1_PIKA_F1_int8.mp4 dj=data/ab/motion_fix/dejudder/S1_PIKA_F1_dj.mp4
  某个版本加 "!601" / "!709" 后缀 = 强制按该矩阵解码（查色彩矩阵错配用），如 dj601=...dj.mp4!601
输出 data/ab/director/red_trace/<输出名>/：trace.csv、trace.json、trace.png（曲线）、worst.jpg（最红那帧各版本并排）
指标（同 review.py）：cheek_a95 = 林晚（蓝发判定）脸颊带 LAB a* 的 95 分位；cheek_red = 脸颊带 a*≥25 像素占比；
face_a / face_L = 脸内区域 a* / L* 中位数；frame_red = 整帧 a*≥35 且 C*≥40 像素占比。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import review as R  # noqa: E402
import cv2  # noqa: E402

OUT = R.OUT_BASE / "red_trace"


def frame_metrics(f: np.ndarray, faces: R.Faces) -> dict:
    row = {"frame_red": round(R.red_blobs(f)["red_frac"], 4)}
    fs = [fc for fc in faces.detect(f, small=True) if float(fc[3]) >= 30]
    fc = R.label_faces(f, fs).get("lin_wan")
    if fc is None:
        return row
    roi, ck = R.face_roi(fc, f.shape), R.cheek_roi(fc, f.shape)
    if roi:
        c = R.face_colour(f, roi)
        row.update(face_a=round(c["a"], 2), face_L=round(c["L"], 2), face_b=round(c["b"], 2), face_S=round(c["S"], 3))
    if ck:
        c = R.face_colour(f, ck)
        row.update(cheek_a95=round(c["a_p95"], 2), cheek_red=round(c["red_frac"], 3))
    row["box"] = [int(v) for v in fc[:4]]
    return row


def load(spec: str):
    name, rest = spec.split("=", 1)
    force = None
    if "!" in rest:
        rest, force = rest.rsplit("!", 1)
        force = {"601": "bt601", "709": "bt709"}[force]
    start = 0.0
    if "@" in rest:
        rest, st = rest.rsplit("@", 1)
        start = float(st)
    p = Path(rest) if Path(rest).is_absolute() else R.ROOT / rest
    return name, p, start, force


def main(argv):
    out_name, specs = argv[0], argv[1:]
    out = OUT / out_name
    out.mkdir(parents=True, exist_ok=True)
    faces = R.Faces()
    res, frames_keep = {}, {}
    for sp in specs:
        name, p, start, force = load(sp)
        if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
            im = cv2.cvtColor(cv2.imread(str(p)), cv2.COLOR_BGR2RGB)
            h, w = im.shape[:2]
            s = max(R.TW / w, R.TH / h)
            im = cv2.resize(im, (int(round(w * s)), int(round(h * s))), interpolation=cv2.INTER_AREA)
            y0, x0 = (im.shape[0] - R.TH) // 2, (im.shape[1] - R.TW) // 2
            fr = [im[y0:y0 + R.TH, x0:x0 + R.TW]]
            matrix = "png(sRGB)"
        else:
            v = R.vstream(R.probe(p))
            matrix = force or R.matrix_of(v, "bt709")
            n = int(v.get("nb_frames") or 0)
            dur = (n / R.fps_of(v)) if n else None
            fr = R.decode(p, start or None, dur, R.TW, R.TH, matrix)
        rows = [frame_metrics(f, faces) for f in fr]
        res[name] = {"file": str(p), "start": start, "matrix": matrix, "rows": rows}
        frames_keep[name] = fr
        ck = [r.get("cheek_a95") for r in rows if r.get("cheek_a95") is not None]
        cr = [r.get("cheek_red") for r in rows if r.get("cheek_red") is not None]
        print(f"{name:14s} frames={len(rows):4d} matrix={matrix:9s} cheek_a95 first={ck[0] if ck else None} "
              f"med={np.median(ck) if ck else None} max={max(ck) if ck else None}  cheek_red max={max(cr) if cr else None} "
              f"frames>=25%={sum(1 for x in cr if x >= 0.25)}", flush=True)
    # 汇总
    summ = {}
    for name, r in res.items():
        rows = r["rows"]
        ck = np.array([x.get("cheek_a95", np.nan) for x in rows], float)
        cr = np.array([x.get("cheek_red", np.nan) for x in rows], float)
        fa = np.array([x.get("face_a", np.nan) for x in rows], float)
        ok = ~np.isnan(ck)
        first_red = next((i for i, x in enumerate(cr) if x >= R.CHEEK_RED_WARN), None)
        summ[name] = {"matrix": r["matrix"], "frames": len(rows), "face_frames": int(ok.sum()),
                      "cheek_a95_first": float(ck[ok][0]) if ok.any() else None,
                      "cheek_a95_med": round(float(np.nanmedian(ck)), 2) if ok.any() else None,
                      "cheek_a95_max": round(float(np.nanmax(ck)), 2) if ok.any() else None,
                      "cheek_red_max": round(float(np.nanmax(cr)), 3) if ok.any() else None,
                      "cheek_red_frames_ge25": int(np.nansum(cr >= R.CHEEK_RED_WARN)),
                      "first_red_frame": first_red,
                      "first_red_t": round(first_red / 24, 2) if first_red is not None else None,
                      "face_a_med": round(float(np.nanmedian(fa)), 2) if ok.any() else None}
    names = list(res)
    if len(names) >= 2:
        base = names[0]
        for nm in names[1:]:
            a = np.array([x.get("cheek_a95", np.nan) for x in res[base]["rows"]], float)
            b = np.array([x.get("cheek_a95", np.nan) for x in res[nm]["rows"]], float)
            k = min(len(a), len(b))
            if k > 1:
                d = b[:k] - a[:k]
                summ[nm]["vs_" + base + "_cheek_a95_mean_delta"] = round(float(np.nanmean(d)), 2) if np.isfinite(d).any() else None
    (out / "trace.json").write_text(json.dumps({"summary": summ, "series": res}, ensure_ascii=False), encoding="utf-8")
    with open(out / "trace.csv", "w", encoding="utf-8") as f:
        f.write("version,frame,cheek_a95,cheek_red,face_a,face_L,frame_red\n")
        for name, r in res.items():
            for i, x in enumerate(r["rows"]):
                f.write(f"{name},{i},{x.get('cheek_a95', '')},{x.get('cheek_red', '')},{x.get('face_a', '')},"
                        f"{x.get('face_L', '')},{x.get('frame_red', '')}\n")
    plot(res, out / "trace.png")
    worst(res, frames_keep, out / "worst.jpg")
    print(json.dumps(summ, ensure_ascii=False, indent=1))


def plot(res, path):
    from PIL import Image, ImageDraw, ImageFont
    W, H, pad = 1400, 460, 50
    img = Image.new("RGB", (W, H), (252, 252, 252))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=13)
    except TypeError:
        font = ImageFont.load_default()
    n = max(len(r["rows"]) for r in res.values())
    lo, hi = 10.0, 50.0

    def X(i):
        return pad + (W - 2 * pad) * i / max(1, n - 1)

    def Y(v):
        return H - pad - (H - 2 * pad) * (min(max(v, lo), hi) - lo) / (hi - lo)
    for v in (15, 20, 25, 30, 40):
        d.line([pad, Y(v), W - pad, Y(v)], fill=(225, 225, 225))
        d.text((8, Y(v) - 7), str(v), fill=(80, 80, 80), font=font)
    for i in range(0, n, 24):
        d.text((X(i) - 6, H - pad + 6), f"{i // 24}s", fill=(80, 80, 80), font=font)
    pal = [(30, 90, 200), (210, 40, 40), (30, 150, 60), (150, 60, 170), (230, 140, 20), (20, 160, 170), (90, 90, 90)]
    for k, (name, r) in enumerate(res.items()):
        c = pal[k % len(pal)]
        pts = [(X(i), Y(x["cheek_a95"])) for i, x in enumerate(r["rows"]) if x.get("cheek_a95") is not None]
        if len(pts) > 1:
            d.line(pts, fill=c, width=2)
        elif pts:
            d.ellipse([pts[0][0] - 4, pts[0][1] - 4, pts[0][0] + 4, pts[0][1] + 4], fill=c)
        d.text((pad + 10 + 170 * k, 10), f"— {name}", fill=c, font=font)
    d.text((pad, H - 20), "Lin Wan cheek band LAB a* p95 per frame (normal skin ~15-20; flush >=25)", fill=(60, 60, 60),
           font=font)
    img.save(path)


def worst(res, frames, path):
    from PIL import Image
    ref = max(res, key=lambda nm: max((x.get("cheek_red", 0) for x in res[nm]["rows"]), default=0))
    rows = res[ref]["rows"]
    i = int(np.argmax([x.get("cheek_red", 0) for x in rows]))
    tiles = []
    for nm, fr in frames.items():
        j = min(i, len(fr) - 1)
        f = fr[j]
        box = res[nm]["rows"][j].get("box")
        if box:
            x, y, w, h = box
            x0, y0 = max(0, x - w // 2), max(0, y - h // 2)
            crop = f[y0:min(f.shape[0], y + h + h // 2), x0:min(f.shape[1], x + w + w // 2)]
        else:
            crop = f
        tiles.append(Image.fromarray(np.ascontiguousarray(crop)).resize((300, 300)))
    img = Image.new("RGB", (300 * len(tiles), 300))
    for k, t in enumerate(tiles):
        img.paste(t, (300 * k, 0))
    img.save(path, quality=90)
    (path.with_suffix(".txt")).write_text(f"frame {i} (from {ref}); order: {', '.join(frames)}\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
