"""画面质感的确定性指标（纯本地、不调模型）：H0 / PLAN_HOLLYWOOD_LOOK。

  clip_hi  亮度 >= 250 的像素占比（高光溢出 / 死白）
  clip_lo  亮度 <= 5 的占比（死黑）
  dof_ratio  中心 40% 区域与四周背景的拉普拉斯方差之比（大 = 主体清楚、背景虚 = 有景深层次）
  halo     强边缘两侧 2px 内的亮度过冲均值（USM 光晕；越大越“炸”）
  bg_lum / subj_lum / subj_bg_ratio  四周背景亮度 / 中心 40% 主体亮度 / 两者之比
  sat_mean HSV 饱和度均值（0-1）；contrast_std 亮度标准差（0-1）

  python tools/pipeline/look_metrics.py <img...>   # JSON lines
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import cv2
import numpy as np

MAX_SIDE = 1280


def _load(path) -> np.ndarray:
    data = np.fromfile(str(path), dtype=np.uint8)      # 兼容中文 / 空格路径
    img = cv2.imdecode(data, cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError(f"读不了图：{path}")
    h, w = img.shape[:2]
    s = MAX_SIDE / max(h, w)
    if s < 1:
        img = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return img


def _lapvar(g: np.ndarray, mask: np.ndarray) -> float:
    lap = cv2.Laplacian(g, cv2.CV_32F)
    v = lap[mask]
    return float(v.var()) if v.size else 0.0


def dof_ratio(gray: np.ndarray) -> float:
    g = cv2.GaussianBlur(gray, (3, 3), 0).astype(np.float32)
    h, w = g.shape
    cy0, cy1, cx0, cx1 = int(h * .3), int(h * .7), int(w * .3), int(w * .7)   # 中心 40%（宽高各 40%）
    m = np.zeros((h, w), bool)
    m[cy0:cy1, cx0:cx1] = True
    ring = np.ones((h, w), bool)
    ring[int(h * .2):int(h * .8), int(w * .2):int(w * .8)] = False            # 四周背景
    vc, vb = _lapvar(g, m), _lapvar(g, ring)
    return round(vc / max(vb, 1e-3), 3) if vc > 1e-3 else 0.0 if vb > 1e-3 else 1.0


def halo(gray: np.ndarray, thr: float = 40.0) -> float:
    """强边缘（Sobel 幅值 > thr）：沿梯度方向，边缘两侧 2px 处的亮度，与更远（5px）处的亮度比，
    亮侧偏更亮、暗侧偏更暗的过冲量均值。USM 会让这个值变大。"""
    g = gray.astype(np.float32)
    gx, gy = cv2.Sobel(g, cv2.CV_32F, 1, 0, ksize=3), cv2.Sobel(g, cv2.CV_32F, 0, 1, ksize=3)
    mag = np.hypot(gx, gy) / 4.0
    ys, xs = np.nonzero(mag > thr)
    if ys.size == 0:
        return 0.0
    if ys.size > 40000:
        sel = np.random.default_rng(0).choice(ys.size, 40000, replace=False)
        ys, xs = ys[sel], xs[sel]
    h, w = g.shape
    ux, uy = gx[ys, xs] / (mag[ys, xs] * 4 + 1e-6), gy[ys, xs] / (mag[ys, xs] * 4 + 1e-6)

    def samp(d):
        x = np.clip(np.rint(xs + ux * d).astype(int), 0, w - 1)
        y = np.clip(np.rint(ys + uy * d).astype(int), 0, h - 1)
        return g[y, x]
    hi2, hi5 = samp(2), samp(5)       # 梯度方向 = 亮侧
    lo2, lo5 = samp(-2), samp(-5)
    over = np.maximum(hi2 - hi5, 0) + np.maximum(lo5 - lo2, 0)    # 近处比远处更亮 / 更暗 = 过冲
    return round(float(over.mean()), 3)


def lum_regions(gray: np.ndarray) -> dict:
    """bg_lum 四周背景（外 20% 圈）平均亮度 0-1；subj_lum 中心 40% 区域平均亮度；subj_bg_ratio = 主体 / 背景（大 = 背景压暗、主体突出）"""
    g = gray.astype(np.float32) / 255
    h, w = g.shape
    ring = np.ones((h, w), bool)
    ring[int(h * .2):int(h * .8), int(w * .2):int(w * .8)] = False
    bg = float(g[ring].mean())
    sj = float(g[int(h * .3):int(h * .7), int(w * .3):int(w * .7)].mean())
    return {"bg_lum": round(bg, 3), "subj_lum": round(sj, 3), "subj_bg_ratio": round(sj / max(bg, 1e-3), 3)}


def measure(path) -> dict:
    img = _load(path)
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    n = gray.size
    return {
        "clip_hi": round(float((gray >= 250).sum()) / n, 4),
        "clip_lo": round(float((gray <= 5).sum()) / n, 4),
        "dof_ratio": dof_ratio(gray),
        "halo": halo(gray),
        "sat_mean": round(float(hsv[..., 1].mean()) / 255, 4),
        "contrast_std": round(float(gray.std()) / 255, 4),
        **lum_regions(gray),
    }


def main(argv=None) -> int:
    for p in (argv if argv is not None else sys.argv[1:]):
        try:
            rec = {"file": str(p), **measure(Path(p))}
        except Exception as e:  # noqa: BLE001  单张失败只记
            rec = {"file": str(p), "error": repr(e)[:200]}
        print(json.dumps(rec, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
