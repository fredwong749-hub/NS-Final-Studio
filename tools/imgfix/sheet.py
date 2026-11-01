"""IMGFIX 目检拼图：每张 = 缩略全图 + 放大的脸部裁切（YuNet），标题 = 镜/臂/seed。
    .venv/Scripts/python.exe tools/imgfix/sheet.py <out.jpg> <filter-substr>...
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/localgpu"))
import identity_gaze_ab as IG  # noqa: E402


def main(out: str, subs: list[str]):
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    from ns_qc import face as QF
    rows = [json.loads(x) for x in (ROOT / "data/ab/imgfix/takes.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
    rows = [r for r in rows if all(s in f"{r['shot']}|{r['arm']}|{r['seed']}|{r.get('round')}" for s in subs)]
    m = IG.face_models()
    W, H, F = 180, 315, 180
    font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", 16)
    tiles = []
    for r in rows:
        p = ROOT / r["file"]
        im = Image.open(p).convert("RGB")
        th = im.resize((W, int(im.height * W / im.width)))
        bgr = cv2.imread(str(p))
        f = QF.largest(m.faces(bgr))
        if f is not None:
            x, y, w, h = [int(v) for v in f[:4]]
            pad = int(0.25 * w)
            fc = im.crop((max(0, x - pad), max(0, y - pad), x + w + pad, y + h + pad)).resize((F, F))
        else:
            fc = Image.new("RGB", (F, F), (60, 0, 0))
        t = Image.new("RGB", (W + F, max(H, F) + 24), (20, 20, 20))
        t.paste(th.crop((0, 0, W, min(H, th.height))), (0, 24))
        t.paste(fc, (W, 24))
        mt = r["metrics"]
        ImageDraw.Draw(t).text((4, 2), f"{r['shot'][-2:]} {r['arm']} {str(r['seed'])[-3:]} g={'HIT' if mt['gaze_mp_hit'] else '-'} q2={mt.get('q2_jacket')}",
                               fill=(255, 255, 0), font=font)
        tiles.append(t)
    cols = 4
    tw, tht = W + F, max(H, F) + 24
    sheet = Image.new("RGB", (cols * tw, ((len(tiles) + cols - 1) // cols) * tht), (0, 0, 0))
    for i, t in enumerate(tiles):
        sheet.paste(t, ((i % cols) * tw, (i // cols) * tht))
    sheet.save(out, quality=85)
    print(out, len(tiles))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
