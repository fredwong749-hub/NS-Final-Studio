"""
MOT（fredw-92，2026-10-31）：视频“卡顿 / 慢 / 重影”指标。只看像素，不看内容。

项目方原话：“画面连贯性很差，女主角的脚移动出现影子多腿问题；第二，整个画面显示很卡顿，很慢的节奏，很不连贯”。

指标（每条视频）：
- diff：相邻帧 96×168 灰度平均差（同 motion_qc），mean。
- J4 / J17：帧差按 t mod 4（H3 视频 VAE 时间步长 4，一个 latent = 4 帧）/ t mod 17（VAE 17 帧一段）分相位求均值，
  max 相位均值 ÷ 总均值。完全平滑 ≈ 1.0；每 4 帧一跳会明显 > 1。同时给光流版 J4f。
- flow：OpenCV Farneback（192×336 灰度），每对相邻帧平均光流长度，换算成 768 宽画面的像素 / 帧 → pace（节奏）。
- jerk：光流长度的二阶差分均值 ÷ 光流均值（越大越“一顿一顿”）。
- stall：动作中途的“停帧”占比（本帧光流 < 前后两帧均值的 35%，且前后在动）→ 重复帧 / 半帧率。
- ghost：下半身区域（画面下 45%）的“光流解释不了的变化”：|f_t − warp(f_{t-1})| 与 |f_t − f_{t-1}| 之比，
  高 = 那块不是在“移动”，而是在“淡入淡出 / 叠影”（双重曝光、腿糊成两条）。只做筛查，最后要看腿部条带图。

用法：python tools/motion_judder.py OUT_DIR video1.mp4 [video2.mp4 ...] [--label name=path]
输出：OUT_DIR/metrics.json、metrics.md、每条的 *_series.csv
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

FW, FH = 192, 336       # 光流分辨率（768×1344 的 1/4）
SCALE = 768 / FW


def frames_gray(path: Path, w=FW, h=FH) -> np.ndarray:
    r = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-vf", f"scale={w}:{h},format=gray",
                        "-f", "rawvideo", "-"], capture_output=True)
    if r.returncode != 0:
        raise RuntimeError(r.stderr[-300:].decode("utf-8", "replace"))
    return np.frombuffer(r.stdout, np.uint8).reshape(-1, h, w)


def fps_of(path: Path) -> float:
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=r_frame_rate",
                        "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    try:
        a, b = r.stdout.strip().split("/")
        return float(a) / float(b)
    except ValueError:
        return 24.0


def phase_ratio(x: np.ndarray, p: int, start: int = 1) -> tuple[float, int, list]:
    """x[i] 对应第 start+i 帧（帧差 i = 帧 i+1 − 帧 i）；按帧号 mod p 分相位。→ (max/mean, 最大相位, 各相位均值)"""
    if len(x) < 2 * p or x.mean() <= 1e-6:
        return 1.0, -1, []
    idx = (np.arange(len(x)) + start) % p
    means = [float(x[idx == k].mean()) for k in range(p)]
    k = int(np.argmax(means))
    return round(means[k] / float(x.mean()), 3), k, [round(m, 3) for m in means]


def phase_z(x: np.ndarray, p: int, n_perm: int = 400) -> float:
    """J 的显著性：把序列随机打乱 n_perm 次得到“没有周期”时的 J 分布，→ (J − 均值) / 标准差。> 3 基本可以认定有周期"""
    if len(x) < 2 * p or x.mean() <= 1e-6:
        return 0.0
    j = phase_ratio(x, p)[0]
    rng = np.random.default_rng(0)
    null = np.array([phase_ratio(rng.permutation(x), p)[0] for _ in range(n_perm)])
    return round(float((j - null.mean()) / (null.std() + 1e-9)), 2)


def warp(prev: np.ndarray, flow: np.ndarray) -> np.ndarray:
    h, w = flow.shape[:2]
    gx, gy = np.meshgrid(np.arange(w, dtype=np.float32), np.arange(h, dtype=np.float32))
    # flow 是 prev→cur；用反向近似：cur(x) ≈ prev(x − flow(x))
    return cv2.remap(prev, gx - flow[..., 0], gy - flow[..., 1], cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def analyze(path: Path) -> tuple[dict, dict]:
    g = frames_gray(path)
    n = len(g)
    small = np.stack([cv2.resize(f, (96, 168), interpolation=cv2.INTER_AREA) for f in g]).astype(np.float32)
    diff = np.abs(np.diff(small, axis=0)).mean(axis=(1, 2))
    mag, ghost, lowdiff = [], [], []
    y0 = int(FH * 0.55)
    for t in range(1, n):
        a, b = g[t - 1], g[t]
        fl = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 4, 15, 3, 5, 1.2, 0)
        m = np.hypot(fl[..., 0], fl[..., 1])
        mag.append(float(m.mean()) * SCALE)
        wa = warp(a.astype(np.float32), fl)
        res = np.abs(b.astype(np.float32) - wa)[y0:]
        raw = np.abs(b.astype(np.float32) - a.astype(np.float32))[y0:]
        lowdiff.append(float(raw.mean()))
        ghost.append(float(res.mean() / (raw.mean() + 1e-3)) if raw.mean() > 0.6 else 0.0)
    mag = np.array(mag)
    ghost = np.array(ghost)
    lowdiff = np.array(lowdiff)
    fps = fps_of(path)
    mm = float(mag.mean()) if len(mag) else 0.0
    jerk = float(np.abs(np.diff(mag, 2)).mean() / (mm + 1e-6)) if len(mag) > 3 else 0.0
    stall = 0
    moving = 0
    for i in range(1, len(mag) - 1):
        nb = (mag[i - 1] + mag[i + 1]) / 2
        if nb > 0.8:          # 前后在动（>0.8 px/帧 @768）
            moving += 1
            if mag[i] < 0.35 * nb:
                stall += 1
    j4, ph4, means4 = phase_ratio(diff, 4)
    j4f, ph4f, _ = phase_ratio(mag, 4)
    j17, ph17, _ = phase_ratio(diff, 17)
    # 下半身“鬼影候选帧”：下半区在动（lowdiff 高）且光流解释不了（ghost 比值高）
    cand = [int(i + 1) for i in np.argsort(-(ghost * (lowdiff > np.percentile(lowdiff, 60))))[:6]
            if ghost[i] > 0]
    m = {"file": str(path).replace("\\", "/"), "frames": n, "fps": round(fps, 3), "seconds": round(n / fps, 2),
         "diff_mean": round(float(diff.mean()), 3),
         "J4": j4, "J4_z": phase_z(diff, 4), "J4_phase": ph4, "J4_phase_means": means4, "J4_flow": j4f,
         "J4_flow_z": phase_z(mag, 4), "J17": j17,
         "pace_px_per_frame": round(mm, 2), "pace_p90": round(float(np.percentile(mag, 90)), 2) if len(mag) else 0,
         "pace_px_per_s": round(mm * fps, 1), "jerk": round(jerk, 3),
         "stall_frac": round(stall / moving, 3) if moving else 0.0, "moving_pairs": moving,
         "ghost_low_mean": round(float(ghost[ghost > 0].mean()), 3) if (ghost > 0).any() else 0.0,
         "ghost_low_p95": round(float(np.percentile(ghost[ghost > 0], 95)), 3) if (ghost > 0).any() else 0.0,
         "ghost_candidates": cand}
    series = {"diff": diff.tolist(), "flow": mag.tolist(), "ghost": ghost.tolist(), "lowdiff": lowdiff.tolist()}
    return m, series


def main(argv):
    out = Path(argv[0])
    out.mkdir(parents=True, exist_ok=True)
    items = []
    for a in argv[1:]:
        if "=" in a and not Path(a).exists():
            k, v = a.split("=", 1)
            items.append((k, Path(v)))
        else:
            items.append((Path(a).stem, Path(a)))
    res = {}
    for name, p in items:
        m, s = analyze(p)
        m["name"] = name
        res[name] = m
        with open(out / f"{name}_series.csv", "w", encoding="utf-8") as f:
            f.write("frame,diff,flow,ghost_low,lowdiff\n")
            for i in range(len(s["diff"])):
                f.write(f"{i + 1},{s['diff'][i]:.3f},{s['flow'][i]:.3f},{s['ghost'][i]:.3f},{s['lowdiff'][i]:.3f}\n")
        print(name, {k: m[k] for k in ("frames", "diff_mean", "J4", "J4_flow", "J17", "pace_px_per_frame",
                                         "jerk", "stall_frac", "ghost_low_p95")}, flush=True)
    prev = {}
    jp = out / "metrics.json"
    if jp.is_file():
        prev = json.loads(jp.read_text(encoding="utf-8"))
    prev.update(res)
    jp.write_text(json.dumps(prev, ensure_ascii=False, indent=1), encoding="utf-8")
    rows = ["| 名称 | 帧 | 帧差均值 | J4（帧差） | J4 z | J4（光流） | J4 光流 z | J17 | 节奏 px/帧@768 | jerk | 停帧占比 | 下半身鬼影 p95 |",
            "|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for k, m in prev.items():
        rows.append(f"| {k} | {m['frames']} | {m['diff_mean']} | {m['J4']} | {m.get('J4_z', '')} | {m['J4_flow']} | "
                    f"{m.get('J4_flow_z', '')} | {m['J17']} | "
                    f"{m['pace_px_per_frame']} | {m['jerk']} | {m['stall_frac']} | {m['ghost_low_p95']} |")
    (out / "metrics.md").write_text("\n".join(rows) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1:])
