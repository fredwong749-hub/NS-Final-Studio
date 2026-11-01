"""VIDEO-RCA：把图 / 视频帧里检出的脸裁成一行行小图（人工判视线用；同 score_clip 的 YuNet）。
    python facecrop.py out.jpg img1.png[:帧号] img2.mp4:12 ...   （视频写 路径:帧号）
每个输入一行，行首写文件名；每张脸 = 1.6×脸框外扩、缩到 240 高。
"""
import sys
from pathlib import Path

import cv2
import numpy as np

REPO = Path("/root/work/fredw/video10_srv") if Path("/root/work/fredw/video10_srv").exists() else Path(__file__).resolve().parents[2]
for p in ("tools", "tools/ep02_director", "packages/qc"):
    sys.path.insert(0, str(REPO / p))
import review as R  # noqa: E402


def load(spec):
    if ".mp4" in spec:
        path, _, n = spec.rpartition(":")
        cap = cv2.VideoCapture(path)
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(n))
        ok, fr = cap.read()
        return fr if ok else None
    return cv2.imread(spec)


def main(out, specs):
    faces = R.Faces()
    rows = []
    for sp in specs:
        bgr = load(sp)
        if bgr is None:
            continue
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        fs = sorted([f for f in faces.detect(rgb, small=True) if float(f[3]) >= 24], key=lambda f: float(f[0]))
        tiles = []
        for f in fs[:3]:
            x, y, w, h = [float(v) for v in f[:4]]
            cx, cy, s = x + w / 2, y + h / 2, max(w, h) * 1.6
            x0, y0 = int(max(0, cx - s / 2)), int(max(0, cy - s / 2))
            crop = bgr[y0:int(min(bgr.shape[0], cy + s / 2)), x0:int(min(bgr.shape[1], cx + s / 2))]
            if crop.size:
                tiles.append(cv2.resize(crop, (240, 240), interpolation=cv2.INTER_AREA))
        label = np.full((240, 260, 3), 255, np.uint8)
        name = Path(sp.split(":")[0]).stem[-26:] + ("" if ".mp4" not in sp else f" f{sp.rpartition(':')[2]}")
        cv2.putText(label, name, (4, 120), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
        row = np.hstack([label] + (tiles or [np.full((240, 240, 3), 200, np.uint8)]))
        rows.append(row)
    wmax = max(r.shape[1] for r in rows)
    rows = [np.hstack([r, np.full((240, wmax - r.shape[1], 3), 255, np.uint8)]) for r in rows]
    cv2.imwrite(out, np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 85])


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2:])
