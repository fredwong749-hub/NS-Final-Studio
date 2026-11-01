"""
MOT（fredw-92，2026-10-31）：H3 视频“每 4 帧一顿”的后期去抖（重新分配时间，不改内容、不改帧数、不改时长）。

现象：H3 一个 latent 管 4 帧；生成的视频里，跨 latent 的那一次相邻帧变化约是 latent 内的 1.4–1.7 倍
（S1：官方 8 步、Pika Flex、基模 30 步都一样；VAE 往返测试是平滑的 → 不是 VAE，是生成的 latent 本身）。
做法：
1. 量每个相位（帧号 mod 4）的平均光流 → 每次相邻帧变化的“真实时间”权重 w[相位]；
2. 原帧 j 的真实时刻 T_j = 累加 w；输出第 k 帧取真实时刻 k（均匀）；
3. ffmpeg minterpolate（运动补偿）先插到 4 倍帧率，再按 T 映射挑最近的子帧 → 每次相邻帧变化变均匀。
音轨原样拷贝。只做后期，不碰生成。

用法：python tools/dejudder.py in.mp4 out.mp4
"""
from __future__ import annotations

import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import motion_judder as MJ  # noqa: E402

UP = 4
# FIX（ep02_iter v0 R5，DIR red_trace/S2_C_pika_chain）：以前 rawvideo 往返用 swscale 默认的 BT.601 系数、输出不带标记，
# 被播放器当 bt709 播时脸颊 a*p95 −1.7。现在解码 / 编码都显式 bt709（tv range），并写 bt709 标记。
DECODE_VF = "scale=in_color_matrix=bt709:in_range=tv"
ENCODE_VF = ("scale=out_color_matrix=bt709:out_range=tv,format=yuv420p,"
             "setparams=range=tv:color_primaries=bt709:color_trc=bt709:colorspace=bt709")
COLOR_TAGS = ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]


def phase_weights(path: Path) -> tuple[np.ndarray, int]:
    g = MJ.frames_gray(path)
    import cv2
    mag = []
    for t in range(1, len(g)):
        fl = cv2.calcOpticalFlowFarneback(g[t - 1], g[t], None, 0.5, 4, 15, 3, 5, 1.2, 0)
        mag.append(float(np.hypot(fl[..., 0], fl[..., 1]).mean()))
    mag = np.array(mag)
    ph = (np.arange(len(mag)) + 1) % 4
    w = np.array([mag[ph == k].mean() for k in range(4)])
    w = w / w.mean()
    return w, len(g)


def main(src: str, dst: str):
    src, dst = Path(src), Path(dst)
    w, n = phase_weights(src)
    T = np.concatenate([[0.0], np.cumsum([w[(i + 1) % 4] for i in range(n - 1)])])
    T = T * (n - 1) / T[-1]
    pick = []
    for k in range(n):
        j = min(int(np.searchsorted(T, k, side="right") - 1), n - 2)
        f = (k - T[j]) / max(T[j + 1] - T[j], 1e-9)
        pick.append(min(int(round((j + f) * UP)), (n - 1) * UP))
    with tempfile.TemporaryDirectory() as td:
        up = Path(td) / "up.mkv"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-an", "-vf",
                        f"minterpolate=fps={24 * UP}:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1",
                        "-c:v", "ffv1", str(up)], check=True)
        w_, h_ = (int(x) for x in subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height", "-of",
             "csv=p=0", str(src)], capture_output=True, text=True).stdout.strip().split(","))
        fs = w_ * h_ * 3
        want = {}
        for k, p in enumerate(pick):
            want.setdefault(p, []).append(k)
        dec = subprocess.Popen(["ffmpeg", "-v", "error", "-i", str(up), "-vf", DECODE_VF, "-f", "rawvideo",
                                "-pix_fmt", "rgb24", "-"], stdout=subprocess.PIPE)
        enc = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                                f"{w_}x{h_}", "-r", "24", "-i", "-", "-i", str(src), "-map", "0:v", "-map", "1:a?",
                                "-vf", ENCODE_VF, "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", *COLOR_TAGS,
                                "-c:a", "copy", "-shortest", str(dst)], stdin=subprocess.PIPE)
        i, last = 0, None
        while True:
            buf = dec.stdout.read(fs)
            if len(buf) < fs:
                break
            for _ in want.get(i, []):
                enc.stdin.write(buf)
            last = buf
            i += 1
        written = sum(len(v) for p, v in want.items() if p < i)
        for _ in range(n - written):   # 末尾不够（插帧少于预期）→ 用最后一帧补齐
            enc.stdin.write(last)
        enc.stdin.close()
        enc.wait()
        dec.wait()
    print("weights", np.round(w, 3).tolist(), "frames", n, "->", dst)


if __name__ == "__main__":
    main(*sys.argv[1:3])
