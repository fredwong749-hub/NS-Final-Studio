"""景深 / 背景亮度确定性指标（picture_index 用）。

原先 picture_index 反向 import tools/research/lens_sim_ab（研究脚本，连带 look_v2_ab / adherence_video 进发版树，arch_scan 退化）。
这里只放尺子要的三个函数：bg_lum（look_v2_ab.bg_lum 同口径）、metrics（lens_sim_ab.metrics 同口径：look_metrics.measure + bg_lum + fbg_ratio）。
只依赖 tools/pipeline/look_metrics.py，不 import 任何 research / vidlab 脚本。
"""
from __future__ import annotations

import sys
from pathlib import Path

import numpy as np

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT / "tools/pipeline") not in sys.path:
    sys.path.insert(0, str(_ROOT / "tools/pipeline"))


def bg_lum(path: Path) -> float:
    """四周背景（look_metrics 同一圈：外 20%）的平均亮度 0–1"""
    from PIL import Image
    g = np.asarray(Image.open(path).convert("L"), np.float32) / 255
    h, w = g.shape
    ring = np.ones((h, w), bool)
    ring[int(h * .2):int(h * .8), int(w * .2):int(w * .8)] = False
    return round(float(g[ring].mean()), 3)


def metrics(path: Path, face_box: list[int] | None = None) -> dict:
    """look_metrics 全套 + bg_lum；有脸框 [x,y,w,h]（原图像素）时加 fbg_ratio = 脸框拉普拉斯方差 / 四周背景圈"""
    import cv2
    import look_metrics as LM
    out = {**LM.measure(path), "bg_lum": bg_lum(path)}
    if face_box:
        g = cv2.cvtColor(LM._load(path), cv2.COLOR_BGR2GRAY)
        from PIL import Image
        w0, _h0 = Image.open(path).size
        sc = g.shape[1] / w0
        x, y, bw, bh = [int(v * sc) for v in face_box]
        g = cv2.GaussianBlur(g, (3, 3), 0).astype(np.float32)
        h, w = g.shape
        m = np.zeros((h, w), bool)
        m[max(0, y):min(h, y + bh), max(0, x):min(w, x + bw)] = True
        ring = np.ones((h, w), bool)
        ring[int(h * .2):int(h * .8), int(w * .2):int(w * .8)] = False
        ring &= ~m
        vf, vb = LM._lapvar(g, m), LM._lapvar(g, ring)
        out["fbg_ratio"] = round(vf / max(vb, 1e-3), 3)
    return out
