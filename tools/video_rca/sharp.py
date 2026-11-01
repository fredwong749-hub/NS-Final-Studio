"""VIDEO-RCA：视频清晰度（模型 / 采样层，“糊”类）。只读原片，不经代理 / 放大。

指标（灰度、原分辨率）：
- lap：拉普拉斯方差（细节量，越大越锐）
- ten：Tenengrad（Sobel 梯度平方均值）
- hf：高频能量占比（FFT 半径 > 0.25 奈奎斯特的能量 / 总能量）
按时间取 9 个点（0、1/8 … 末帧）；ratio_* = 该点 / 第 0 帧（第 0 帧 ≈ 首帧原图，衡量随时间变糊多少）。
ratio_mid = 中间 50% 时段的 lap 中位数 / 第 0 帧 lap。

    python sharp.py <video.mp4> [首帧图]   → stdout JSON
"""
import json
import sys

import cv2
import numpy as np


def metrics(g: np.ndarray) -> dict:
    g = g.astype(np.float32)
    lap = float(cv2.Laplacian(g, cv2.CV_32F).var())
    gx = cv2.Sobel(g, cv2.CV_32F, 1, 0)
    gy = cv2.Sobel(g, cv2.CV_32F, 0, 1)
    ten = float(np.mean(gx * gx + gy * gy))
    f = np.fft.fftshift(np.abs(np.fft.fft2(g - g.mean())) ** 2)
    h, w = g.shape
    yy, xx = np.ogrid[:h, :w]
    r = np.sqrt(((yy - h / 2) / (h / 2)) ** 2 + ((xx - w / 2) / (w / 2)) ** 2)
    hf = float(f[r > 0.25].sum() / max(f.sum(), 1e-9))
    return {"lap": round(lap, 2), "ten": round(ten, 1), "hf": round(hf, 5)}


def main(p, ff=None):
    cap = cv2.VideoCapture(p)
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    idx = sorted({min(n - 1, int(round(k * (n - 1) / 8))) for k in range(9)})
    pts = []
    for i in idx:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if not ok:
            continue
        g = cv2.cvtColor(fr, cv2.COLOR_BGR2GRAY)
        pts.append({"frame": i, **metrics(g)})
    w, h = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    out = {"size": [w, h], "frames": n, "points": pts}
    if pts:
        l0 = pts[0]["lap"] or 1e-9
        mid = [q["lap"] for q in pts if n * 0.25 <= q["frame"] <= n * 0.75]
        out["ratio_mid"] = round(float(np.median(mid)) / l0, 3) if mid else None
        out["ratio_end"] = round(pts[-1]["lap"] / l0, 3)
        out["lap_mid"] = round(float(np.median(mid)), 2) if mid else None
        out["hf_mid"] = round(float(np.median([q["hf"] for q in pts if n * 0.25 <= q["frame"] <= n * 0.75])), 5) if mid else None
    if ff:
        im = cv2.imread(ff)
        if im is not None:
            im = cv2.resize(im, (w, h), interpolation=cv2.INTER_LANCZOS4)
            out["first_frame"] = metrics(cv2.cvtColor(im, cv2.COLOR_BGR2GRAY))
    print(json.dumps(out))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
