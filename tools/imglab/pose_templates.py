"""按景别的姿势骨架模板库（IMGLAB T10，docs/research/imglab/04_relight_pose.md §B）→ OpenPose 18 点彩色骨架图，
喂 Qwen-Image 2.1 Fun ControlNet Union（ComfyUI core：ModelPatchLoader + ZImageFunControlnet）做构图 / 景别约束。

要点（04 §B 结论）：景别退档主要来自模板画法——中景要把膝以下关键点画到画外截断，不是把整个人缩小放进画布。
所以模板按“画框截在身体哪里”定义：关键点坐标是相对画框的比例，可以落在 [0,1] 之外（画外 = 不画）。

关键点顺序（OpenPose COCO-18）：0 鼻 1 颈 2 右肩 3 右肘 4 右腕 5 左肩 6 左肘 7 左腕 8 右髋 9 右膝 10 右踝
11 左髋 12 左膝 13 左踝 14 右眼 15 左眼 16 右耳 17 左耳。

    .venv/Scripts/python.exe tools/imglab/pose_templates.py render 特写 out.png [--w 1152 --h 2016] [--turn 0.3] [--x 0.5]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

LIMBS = [(1, 2), (1, 5), (2, 3), (3, 4), (5, 6), (6, 7), (1, 8), (8, 9), (9, 10), (1, 11), (11, 12), (12, 13),
         (1, 0), (0, 14), (14, 16), (0, 15), (15, 17)]
COLORS = [(255, 0, 0), (255, 85, 0), (255, 170, 0), (255, 255, 0), (170, 255, 0), (85, 255, 0), (0, 255, 0),
          (0, 255, 85), (0, 255, 170), (0, 255, 255), (0, 170, 255), (0, 85, 255), (0, 0, 255), (85, 0, 255),
          (170, 0, 255), (255, 0, 255), (255, 0, 170), (255, 0, 85)]


def _body(face_h: float, top: float, x: float = 0.5, turn: float = 0.0) -> list[tuple[float, float] | None]:
    """站立正身骨架：face_h = 头顶到下巴占画高比例，top = 头顶 y；turn ∈ [-1, 1] 头向画右（+）/ 画左（−）转。
    身体比例按 8 头身：下巴 = top + face_h，肩 = 下巴 + 0.35 头，髋 = 3.2 头，膝 = 5.2 头，踝 = 7.2 头（从下巴量）"""
    H = face_h
    chin = top + H
    cx = x
    sw = 0.95 * H                     # 半肩宽（相对画高；画面 9:16 时横向再除宽高比，见 render）
    pts: list[tuple[float, float] | None] = [None] * 18
    nose_dx = 0.18 * H * turn
    pts[0] = (cx + nose_dx, top + 0.62 * H)
    pts[14] = (cx - 0.20 * H + nose_dx * 1.2, top + 0.45 * H)
    pts[15] = (cx + 0.20 * H + nose_dx * 1.2, top + 0.45 * H)
    pts[16] = (cx - 0.42 * H + nose_dx * 0.4, top + 0.50 * H) if turn < 0.6 else None
    pts[17] = (cx + 0.42 * H + nose_dx * 0.4, top + 0.50 * H) if turn > -0.6 else None
    pts[1] = (cx, chin + 0.30 * H)
    pts[2] = (cx - sw, chin + 0.40 * H)
    pts[5] = (cx + sw, chin + 0.40 * H)
    pts[3] = (cx - sw * 1.05, chin + 1.75 * H)
    pts[6] = (cx + sw * 1.05, chin + 1.75 * H)
    pts[4] = (cx - sw * 0.9, chin + 3.0 * H)
    pts[7] = (cx + sw * 0.9, chin + 3.0 * H)
    pts[8] = (cx - 0.5 * sw, chin + 3.2 * H)
    pts[11] = (cx + 0.5 * sw, chin + 3.2 * H)
    pts[9] = (cx - 0.5 * sw, chin + 5.2 * H)
    pts[12] = (cx + 0.5 * sw, chin + 5.2 * H)
    pts[10] = (cx - 0.5 * sw, chin + 7.2 * H)
    pts[13] = (cx + 0.5 * sw, chin + 7.2 * H)
    return pts


# 景别 → (头高（头顶到下巴）占画高, 头顶 y)。按“画框截在身体哪里”反推（8 头身，从下巴量：胸 1.6 头、腰 2.6、膝 5.2、踝 7.2）：
# 特写 = 头肩，头高 0.45；近景 = 胸以上；中近景 = 腰以上；中景 = 膝以上（膝在画底）；全景 = 全身；远景 = 人小。
# 检测器脸框约为头高的 0.75 倍 → 与 postflight Q3 档线（0.45/0.27/0.17/0.115/0.095/0.05）对应：特写档 1、近景档 2、中景档 3
SIZES = {"大特写": (0.62, 0.06), "极近特写": (0.62, 0.06), "特写": (0.45, 0.12), "近景": (0.30, 0.12), "中近景": (0.22, 0.11),
         "中景": (0.145, 0.10), "全景": (0.10, 0.12), "远景": (0.045, 0.40)}


def template(size: str, x: float = 0.5, turn: float = 0.0) -> list[tuple[float, float] | None]:
    face_h, top = SIZES[size]
    return _body(face_h, top, x, turn)


def render(people: list[list[tuple[float, float] | None]], w: int = 1152, h: int = 2016, stick: int | None = None):
    """→ RGB uint8 图（黑底彩色骨架）。坐标 y 相对画高、x 相对画宽中心按画高换算（保持人体比例不被 9:16 压扁）"""
    import cv2
    img = np.zeros((h, w, 3), np.uint8)
    stick = stick or max(4, int(h * 0.006))

    def px(p):
        if p is None:
            return None
        X = w * 0.5 + (p[0] - 0.5) * h      # 横向用画高做单位
        return int(round(X)), int(round(p[1] * h))

    for pts in people:
        P = [px(p) for p in pts]
        for i, (a, b) in enumerate(LIMBS):
            if P[a] is None or P[b] is None:
                continue
            cv2.line(img, P[a], P[b], [c * 0.6 for c in COLORS[i]], stick, cv2.LINE_AA)
        for i, p in enumerate(P):
            if p is not None and 0 <= p[0] < w and 0 <= p[1] < h:
                cv2.circle(img, p, stick + 2, COLORS[i], -1, cv2.LINE_AA)
    return img


def person(size: str, cx_frac: float = 0.5, turn: float = 0.0, scale: float = 1.0, top: float | None = None):
    """单人骨架：cx_frac = 人在画宽的位置（0–1）；scale 相对该景别的体型；top 覆盖头顶 y（前景人物可以伸出画框）"""
    face_h, t0 = SIZES[size]
    face_h *= scale
    pts = _body(face_h, t0 if top is None else top, 0.5, turn)
    # 把以画高为单位的横坐标平移到 cx_frac（render 里横向以画高为单位、以画面中心为原点）
    w_over_h = 1152 / 2016
    shift = (cx_frac - 0.5) * w_over_h
    return [None if p is None else (p[0] + shift, p[1]) for p in pts]


def main(argv=None) -> int:
    import cv2
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["render"])
    ap.add_argument("size", choices=list(SIZES))
    ap.add_argument("out")
    ap.add_argument("--w", type=int, default=1152)
    ap.add_argument("--h", type=int, default=2016)
    ap.add_argument("--x", type=float, default=0.5)
    ap.add_argument("--turn", type=float, default=0.0)
    a = ap.parse_args(argv)
    img = render([person(a.size, a.x, a.turn)], a.w, a.h)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_bytes(cv2.imencode(".png", cv2.cvtColor(img, cv2.COLOR_RGB2BGR))[1].tobytes())   # 中文路径不能用 imwrite
    return 0


if __name__ == "__main__":
    sys.exit(main())
