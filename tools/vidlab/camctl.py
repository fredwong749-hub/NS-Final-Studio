"""VIDLAB 结构化运镜：给 MiniMax H3 Fun ControlNet（MiniMaxH3FunControlNetApply）生成“机位轨迹”控制视频（线 2，G0 结构化方案）。

做法（不需要深度模型）：
1. 首帧 → Canny 边缘（只取背景：MediaPipe selfie_multiclass 人物分割把人挡掉，人物表演不被边缘锁死）；
2. 按运镜词表 id 的虚拟机位轨迹（缓入缓出），对边缘图逐帧做仿射变换（推 / 拉 = 绕中心缩放，横移 = 平移，摇 / 升降 = 平移 + 轻微缩放，环绕 = 平移 + 微旋）；
3. 写成 768×1344、24 fps、与成片同帧数的 mp4 → 服务器 VHS_LoadVideoPath → control_video。
幅度 AMP 是“小幅”档（与 camera_moves.yaml 模板里的 with small amplitude 对应），改幅度改这里，同步 docs/research/vidlab/。

  python tools/vidlab/camctl.py <首帧.png> <move_id> <frames> <out.mp4> [--amp 1.0]
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
import cv2  # noqa: E402

W, H, FPS = 768, 1344, 24
SEG_MODEL = ROOT / "models_cache" / "vision" / "selfie_multiclass_256x256.tflite"
# 每个运镜在整条镜头里的终点：(tx 占宽, ty 占高, 缩放, 旋转度)；画面内容相对机位反向运动
AMP = {
    "push_in": (0.0, 0.0, 1.10, 0.0),
    "pull_out": (0.0, 0.0, 0.91, 0.0),
    "truck_right": (-0.07, 0.0, 1.0, 0.0), "truck": (-0.07, 0.0, 1.0, 0.0),
    "truck_left": (0.07, 0.0, 1.0, 0.0),
    "pan_right": (-0.09, 0.0, 1.01, 0.0), "pan_left": (0.09, 0.0, 1.01, 0.0),
    "tilt_up": (0.0, 0.05, 1.0, 0.0), "tilt_down": (0.0, -0.05, 1.0, 0.0),
    "pedestal_up": (0.0, 0.06, 1.0, 0.0), "pedestal_down": (0.0, -0.06, 1.0, 0.0),
    "arc": (-0.06, 0.0, 1.03, 1.5),
    "static": (0.0, 0.0, 1.0, 0.0),
}


def ease(t: float) -> float:
    return 0.5 - 0.5 * np.cos(np.pi * t)


def person_mask(bgr: np.ndarray, dilate: int = 25) -> np.ndarray:
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions
    from mediapipe.tasks.python import vision as V
    opt = V.ImageSegmenterOptions(base_options=BaseOptions(model_asset_path=str(SEG_MODEL)), output_category_mask=True)
    with V.ImageSegmenter.create_from_options(opt) as seg:
        r = seg.segment(mp.Image(image_format=mp.ImageFormat.SRGB, data=np.ascontiguousarray(bgr[:, :, ::-1])))
        cat = r.category_mask.numpy_view()
    m = (cat > 0).astype(np.uint8) * 255          # 0 = 背景，其余 = 人（头发 / 身体 / 脸 / 衣服 …）
    return cv2.dilate(m, np.ones((dilate, dilate), np.uint8))


def edges(bgr: np.ndarray, dilate: int = 25) -> np.ndarray:
    # 暗场浅景深背景对比低：先 CLAHE 拉局部对比再 Canny（20/60），否则背景边缘太稀、控制力不够
    g = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY))
    g = cv2.GaussianBlur(g, (5, 5), 0)
    e = cv2.Canny(g, 20, 60)
    e[person_mask(bgr, dilate) > 0] = 0
    return e


def render(first: Path, move: str, frames: int, out: Path, amp: float = 1.0, dilate: int = 25) -> dict:
    if move not in AMP:
        raise SystemExit(f"运镜 {move} 没有轨迹定义（AMP）")
    img = cv2.imread(str(first))
    s = max(W / img.shape[1], H / img.shape[0])
    img = cv2.resize(img, (int(round(img.shape[1] * s)), int(round(img.shape[0] * s))), interpolation=cv2.INTER_LANCZOS4)
    y0, x0 = (img.shape[0] - H) // 2, (img.shape[1] - W) // 2
    img = img[y0:y0 + H, x0:x0 + W]                   # 与 ImageScale crop=center 同口径
    e = edges(img, dilate)
    tx, ty, sc, rot = AMP[move]
    # 先按本运镜的最大平移 / 缩小 / 旋转放大一点铺满（vl_r1 冒烟：平移后露出的无边缘黑区被模型画成暗色竖条）
    pre = 1.0 + 2 * max(abs(tx * amp), abs(ty * amp)) + max(0.0, (1 - sc) * amp) + abs(np.radians(rot * amp))
    if pre > 1.0:
        e = cv2.warpAffine(e, cv2.getRotationMatrix2D((W / 2, H / 2), 0, pre), (W, H), flags=cv2.INTER_LINEAR)
    out.parent.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "gray", "-s", f"{W}x{H}", "-r", str(FPS),
                          "-i", "-", "-c:v", "libx264", "-crf", "12", "-pix_fmt", "yuv420p", str(out)], stdin=subprocess.PIPE)
    for i in range(frames):
        k = ease(i / max(1, frames - 1)) * amp
        M = cv2.getRotationMatrix2D((W / 2, H / 2), rot * k, 1 + (sc - 1) * k)
        M[0, 2] += tx * W * k
        M[1, 2] += ty * H * k
        f = cv2.warpAffine(e, M, (W, H), flags=cv2.INTER_LINEAR, borderValue=0)
        p.stdin.write(f.tobytes())
    p.stdin.close()
    rc = p.wait(timeout=600)
    if rc:
        raise RuntimeError(f"ffmpeg rc={rc}")
    return {"move": move, "frames": frames, "amp": amp, "end": AMP[move], "edge_px": int((e > 0).sum()), "prescale": round(pre, 3), "dilate": dilate}


if __name__ == "__main__":
    a = sys.argv[1:]
    amp = float(a[a.index("--amp") + 1]) if "--amp" in a else 1.0
    print(render(Path(a[0]), a[1], int(a[2]), Path(a[3]), amp))
