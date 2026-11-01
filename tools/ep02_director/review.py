"""
DIR（剪辑导演）审片工具 —— 长期留在系统里，每一版 ep 成片 / A/B 镜头都用它出同一套数字和接触印样。
只做技术 / 剪辑层面的测量，不看剧本内容、不做内容检测。

用法（必须用项目 .venv 的 python，要 cv2）：
  .venv/Scripts/python.exe tools/ep02_director/review.py episode <成片.mp4> <timeline.json> --name v0_preview
  .venv/Scripts/python.exe tools/ep02_director/review.py clips --name pika_ab  S2_C=data/ab/static_fix/S2_C.mp4  ...
输出：data/ab/director/<name>/review.json、review.md、sheets/<镜>.jpg（每镜 10 帧接触印样）、overview.jpg、
      color_timeline.png（逐镜脸部 a* 曲线）

每镜指标（详见 rubric.md）：
- 运动：96×168 灰度相邻帧差（同 qc_ep02 / static_fix）→ 均值、p90、静止占比、≥0.5 s 静止段、开头 / 结尾定住秒数；
  Farneback 光流（192×336，同 tools/motion_judder.py）→ 节奏 px/帧@768、jerk、停帧、下半身鬼影比 p95
- 抖动：J4 / J4 z / J4 光流（tools/motion_judder.py phase_ratio / phase_z，同一个定义）
- 色彩：YuNet 找脸，脸内区域 LAB（cv2 float：L 0–100，a/b ±127）、HSV 饱和度、a*≥25 像素占比；整帧红色异常
  （a*≥35 且 C*≥40）面积和最大连通块；镜内 a* 漂移（相对开头 0.5 s 中位数）、跨镜脸部 ΔE
- 人物：OpenCV zoo YuNet + SFace（models_cache/vision，同 packages/qc/ns_qc/face.py）→ 对林晚 / 顾沉参考图余弦、
  镜内稳定性；跨镜同一人的平均向量余弦；头发蓝色规则（ns_qc.face.hair_colour）
- 景别：脸高 / 画面高 → 特写 / 近景 / 中景 / 全景（无脸）
- 音频：ffmpeg ebur128（整集 I / LRA / 真峰值；每镜 I）、静音段、切点前后 100 ms 电平跳变和爆音
- 声画：对白时间（timeline speech[]）内 嘴部区域帧差能量 vs 300–3400 Hz 语音包络，±0.5 s 互相关 → 最佳偏移 / 相关系数
- 切点：前后帧亮度 / ΔE、黑帧、单帧闪
"""
from __future__ import annotations

import argparse
import json
import math
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

os.environ.setdefault("PYTHONIOENCODING", "utf-8")
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "packages" / "qc"))

import cv2  # noqa: E402

try:
    cv2.utils.logging.setLogLevel(cv2.utils.logging.LOG_LEVEL_ERROR)
except Exception:  # noqa: BLE001
    pass

import motion_judder as MJ  # noqa: E402

try:
    from ns_qc import face as QF  # noqa: E402
except Exception:  # noqa: BLE001
    QF = None

OUT_BASE = ROOT / "data" / "ab" / "director"
TW, TH = 360, 640          # 跟踪分辨率（9:16）
SW, SH = 96, 168           # 帧差分辨率（同 qc_ep02 / static_fix）
FW, FH = 192, 336          # 光流分辨率（同 motion_judder）
SHEET_N = 10
THUMB_W, THUMB_H = 216, 384
REF_FACES = {"lin_wan": ROOT / "assets/characters/lin_wan/lin_wan.png",
             "gu_chen": ROOT / "assets/characters/gu_chen/refs/gu_chen/ar-98f7c63570.png"}

# ---- 阈值（来源见 rubric.md；改了要同步 LEARNED_SPECS.md）----
STILL_DIFF = 0.35          # 96×168 灰度帧差 < 0.35 = 静止（qc_ep02 / static_fix 同值）
FACE_RED_A = 25.0          # 脸内 a* ≥ 25 计“泛红像素”
BLOB_A, BLOB_C = 35.0, 40.0  # 整帧 a* ≥ 35 且 C* ≥ 40 计“红色异常像素”
A_DRIFT_WARN, A_DRIFT_FAIL = 6.0, 12.0  # 镜内脸颊 a* p95 相对开头 0.5 s 的最大漂移（S2_C 泛红镜：+23）
DARK_LUMA = 12.0           # 96×168 灰度均值 <12（0–255）= 近黑帧；连续 ≥1 s 标“暗场”
CHEEK_RED_WARN = 0.25      # 脸颊区 a*≥25 像素占比（正常 0–5 %；Pika S2_C 泛红 48–50 %）
CROSS_DE_WARN, CROSS_DE_FAIL = 6.0, 10.0  # 同一人跨镜脸部平均色 ΔE（CIE76）
SFACE_SAME = 0.30          # 项目锁定闸门 Q-D1 sface_median ≥0.30（packages/qc/ns_qc/thresholds.py）


def run(cmd, **kw):
    return subprocess.run(cmd, capture_output=True, **kw)


def probe(path: Path) -> dict:
    r = run(["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)],
            text=True, encoding="utf-8")
    return json.loads(r.stdout or "{}")


def vstream(p: dict) -> dict:
    return next((s for s in p.get("streams", []) if s.get("codec_type") == "video"), {})


def fps_of(v: dict) -> float:
    a, b = (v.get("r_frame_rate") or "24/1").split("/")
    return float(a) / float(b or 1)


def matrix_of(v: dict, assume: str) -> str:
    cs = (v.get("color_space") or "unknown").lower()
    if cs == "bt709":
        return "bt709"
    if cs in ("smpte170m", "bt470bg", "bt601"):
        return "bt601"
    return assume


def decode(path: Path, start: float | None, dur: float | None, w: int, h: int, matrix: str,
           fmt: str = "rgb24") -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start:
        cmd += ["-ss", f"{start:.4f}"]
    cmd += ["-i", str(path)]
    if dur:
        cmd += ["-t", f"{dur:.4f}"]
    cmd += ["-map", "0:v:0", "-vf", f"scale={w}:{h}:flags=area:in_color_matrix={matrix}:in_range=tv",
            "-f", "rawvideo", "-pix_fmt", fmt, "-"]
    r = run(cmd)
    if r.returncode != 0:
        raise RuntimeError(r.stderr.decode("utf-8", "replace")[-400:])
    c = 3 if fmt == "rgb24" else 1
    a = np.frombuffer(r.stdout, np.uint8)
    return a.reshape(-1, h, w, c) if c == 3 else a.reshape(-1, h, w)


def decode_frames_at(path: Path, times: list[float], w: int, h: int, matrix: str) -> list[np.ndarray]:
    out = []
    for t in times:
        a = decode(path, max(0.0, t), 0.05, w, h, matrix)
        out.append(a[0] if len(a) else np.zeros((h, w, 3), np.uint8))
    return out


def audio_mono(path: Path, sr: int = 16000, start: float | None = None, dur: float | None = None) -> np.ndarray:
    cmd = ["ffmpeg", "-v", "error", "-nostdin"]
    if start:
        cmd += ["-ss", f"{start:.4f}"]
    cmd += ["-i", str(path)]
    if dur:
        cmd += ["-t", f"{dur:.4f}"]
    cmd += ["-vn", "-ac", "1", "-ar", str(sr), "-f", "f32le", "-"]
    return np.frombuffer(run(cmd).stdout, np.float32).copy()


def ebur128(path: Path, start: float | None = None, dur: float | None = None) -> dict:
    cmd = ["ffmpeg", "-hide_banner", "-nostdin"]
    if start:
        cmd += ["-ss", f"{start:.4f}"]
    cmd += ["-i", str(path)]
    if dur:
        cmd += ["-t", f"{dur:.4f}"]
    cmd += ["-vn", "-af", "ebur128=peak=true", "-f", "null", "-"]
    err = run(cmd).stderr.decode("utf-8", "replace")
    tail = err[err.rfind("Summary:"):] if "Summary:" in err else ""

    def num(pat):
        m = re.search(pat, tail, re.S)
        return float(m.group(1)) if m else None
    return {"I_lufs": num(r"Integrated loudness:.*?I:\s*(-?[\d.]+)"), "LRA": num(r"LRA:\s*(-?[\d.]+)"),
            "true_peak_dbtp": num(r"True peak:.*?Peak:\s*(-?[\d.]+|-inf)")}


# ---------------- 颜色 ----------------

def lab_of(rgb: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(rgb.astype(np.float32) / 255.0, cv2.COLOR_RGB2LAB)


def face_roi(face, shape) -> tuple[int, int, int, int] | None:
    """脸内区域：去掉头发 / 背景（宽 15–85 %，高 25–92 %）。"""
    x, y, w, h = (float(v) for v in face[:4])
    H, W = shape[:2]
    x0, x1 = int(max(0, x + 0.15 * w)), int(min(W, x + 0.85 * w))
    y0, y1 = int(max(0, y + 0.25 * h)), int(min(H, y + 0.92 * h))
    return (x0, y0, x1, y1) if x1 - x0 >= 6 and y1 - y0 >= 6 else None


def cheek_roi(face, shape) -> tuple[int, int, int, int] | None:
    """脸颊带：脸框宽 10–90 %、高 50–80 %（腮红 / 泛红出现的位置）。"""
    x, y, w, h = (float(v) for v in face[:4])
    H, W = shape[:2]
    x0, x1 = int(max(0, x + 0.10 * w)), int(min(W, x + 0.90 * w))
    y0, y1 = int(max(0, y + 0.50 * h)), int(min(H, y + 0.80 * h))
    return (x0, y0, x1, y1) if x1 - x0 >= 6 and y1 - y0 >= 4 else None


def _blue_share(rgb: np.ndarray, x0, y0, x1, y1) -> float:
    if x1 <= x0 or y1 <= y0:
        return 0.0
    hsv = cv2.cvtColor(np.ascontiguousarray(rgb[y0:y1, x0:x1]), cv2.COLOR_RGB2HSV).reshape(-1, 3)
    return float(((hsv[:, 0] >= 85) & (hsv[:, 0] <= 125) & (hsv[:, 1] >= 60) & (hsv[:, 2] >= 40)).mean())


def blue_hair_share(rgb: np.ndarray, face) -> float:
    """浅蓝发得分 = 头顶带（ns_qc.face.hair_band）+ 脸两侧各半个脸宽的带 里蓝色像素占比之和
    （OpenCV H 85–125、S≥60、V≥40）。实测（S1/S2/S5/S7 Pika）：林晚 0.55–1.5，顾沉 / 他人 0–0.2；
    S≥30 不加 V 时蓝光下的黑发也有 0.3，分不开。"""
    H, W = rgb.shape[:2]
    x, y, w, h = (int(v) for v in face[:4])
    top = QF.hair_band(rgb, face) if QF else None
    t = _blue_share(rgb, *top) if top else 0.0
    yy0, yy1 = max(0, y), min(H, y + h)
    left = _blue_share(rgb, max(0, x - w // 2), yy0, max(0, x), yy1)
    right = _blue_share(rgb, min(W, x + w), yy0, min(W, x + w + w // 2), yy1)
    return t + (left + right) / 2


def label_faces(rgb: np.ndarray, fs) -> dict:
    """→ {"lin_wan": face, "other": face}：浅蓝发得分最高且 ≥0.35 的那张脸 = 林晚（每帧至多一张），其余最大的 = other。"""
    out = {}
    if not fs:
        return out
    sh = [blue_hair_share(rgb, fc) for fc in fs]
    k = int(np.argmax(sh))
    if sh[k] >= 0.35:
        out["lin_wan"] = fs[k]
    rest = [fc for j, fc in enumerate(fs) if "lin_wan" not in out or j != k]
    if rest:
        out["other"] = max(rest, key=lambda f: float(f[2]) * float(f[3]))
    return out


def face_colour(rgb: np.ndarray, roi) -> dict:
    x0, y0, x1, y1 = roi
    crop = rgb[y0:y1, x0:x1]
    lab = lab_of(crop).reshape(-1, 3)
    hsv = cv2.cvtColor(crop, cv2.COLOR_RGB2HSV).reshape(-1, 3).astype(np.float32)
    L, a, b = (float(np.median(lab[:, i])) for i in range(3))
    return {"L": L, "a": a, "b": b, "C": math.hypot(a, b), "hue": math.degrees(math.atan2(b, a)),
            "S": float(hsv[:, 1].mean() / 255.0), "red_frac": float((lab[:, 1] >= FACE_RED_A).mean()),
            "a_p95": float(np.percentile(lab[:, 1], 95))}


def red_blobs(rgb: np.ndarray) -> dict:
    lab = lab_of(rgb)
    c = np.hypot(lab[..., 1], lab[..., 2])
    mask = ((lab[..., 1] >= BLOB_A) & (c >= BLOB_C)).astype(np.uint8)
    frac = float(mask.mean())
    big = 0.0
    if mask.any():
        n, _, st, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
        if n > 1:
            big = float(st[1:, cv2.CC_STAT_AREA].max()) / mask.size
    return {"red_frac": frac, "red_blob": big, "mask": mask}


def de76(a, b) -> float:
    return float(np.linalg.norm(np.asarray(a, float) - np.asarray(b, float)))


# ---------------- 人脸 ----------------

class Faces:
    def __init__(self):
        self.ok = False
        self.note = ""
        if QF is None:
            self.note = "ns_qc 不可用"
            return
        paths = QF.find_models(ROOT)
        if not paths:
            self.note = "models_cache/vision 无 YuNet/SFace"
            return
        self.m = QF.FaceModels(*paths, score=0.6)
        self.m_small = QF.FaceModels(*paths, score=0.5)
        self.ok = True
        self.note = "YuNet 2023mar + SFace 2021dec（OpenCV zoo，sha256 见 ns_qc.face.PINNED）"
        self.refs = {}
        for k, p in REF_FACES.items():
            if p.is_file():
                bgr = cv2.imread(str(p))
                f = QF.largest(self.m.faces(bgr))
                if f is not None:
                    self.refs[k] = self.m.embed(bgr, f)

    def detect(self, rgb: np.ndarray, small: bool = False):
        if not self.ok:
            return []
        m = self.m_small if small else self.m
        return m.faces(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR))

    def embed(self, rgb: np.ndarray, face) -> np.ndarray:
        return self.m.embed(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), face)


def scale_label(face_h_frac: float | None) -> str:
    if face_h_frac is None:
        return "全景/无脸"
    if face_h_frac >= 0.22:
        return "特写"
    if face_h_frac >= 0.12:
        return "近景"
    if face_h_frac >= 0.06:
        return "中景"
    return "全景"


# ---------------- 运动 ----------------

def motion_metrics(small_gray: np.ndarray, flow_gray: np.ndarray, fps: float) -> tuple[dict, dict]:
    d = np.abs(np.diff(small_gray.astype(np.float32), axis=0)).mean(axis=(1, 2))
    still = d < STILL_DIFF
    segs, i = [], 0
    while i < len(still):
        if still[i]:
            j = i
            while j < len(still) and still[j]:
                j += 1
            if (j - i) / fps >= 0.5:
                segs.append([round(i / fps, 2), round(j / fps, 2)])
            i = j
        else:
            i += 1
    head = 0
    while head < len(still) and still[head]:
        head += 1
    tail = 0
    while tail < len(still) and still[-1 - tail]:
        tail += 1
    mag, ghost, lowdiff = [], [], []
    y0 = int(FH * 0.55)
    for t in range(1, len(flow_gray)):
        a, b = flow_gray[t - 1], flow_gray[t]
        fl = cv2.calcOpticalFlowFarneback(a, b, None, 0.5, 4, 15, 3, 5, 1.2, 0)
        mag.append(float(np.hypot(fl[..., 0], fl[..., 1]).mean()) * MJ.SCALE)
        wa = MJ.warp(a.astype(np.float32), fl)
        res = np.abs(b.astype(np.float32) - wa)[y0:]
        raw = np.abs(b.astype(np.float32) - a.astype(np.float32))[y0:]
        lowdiff.append(float(raw.mean()))
        ghost.append(float(res.mean() / (raw.mean() + 1e-3)) if raw.mean() > 0.6 else 0.0)
    mag, ghost = np.array(mag), np.array(ghost)
    mm = float(mag.mean()) if len(mag) else 0.0
    jerk = float(np.abs(np.diff(mag, 2)).mean() / (mm + 1e-6)) if len(mag) > 3 else 0.0
    stall = moving = 0
    for i in range(1, len(mag) - 1):
        nb = (mag[i - 1] + mag[i + 1]) / 2
        if nb > 0.8:
            moving += 1
            stall += mag[i] < 0.35 * nb
    j4, _, _ = MJ.phase_ratio(d, 4)
    j4f, _, _ = MJ.phase_ratio(mag, 4)
    m = {"frames": int(len(small_gray)), "diff_mean": round(float(d.mean()), 3) if len(d) else 0.0,
         "diff_p90": round(float(np.percentile(d, 90)), 3) if len(d) else 0.0,
         "still_frac": round(float(still.mean()), 3) if len(d) else 1.0, "still_segs": segs,
         "frozen_head_s": round(head / fps, 2), "frozen_tail_s": round(tail / fps, 2),
         "first_last_diff": round(float(np.abs(small_gray[-1].astype(float) - small_gray[0]).mean()), 1),
         "max_jump": round(float(d.max()), 2) if len(d) else 0.0,
         "J4": j4, "J4_z": MJ.phase_z(d, 4, 200), "J4_flow": j4f, "J4_flow_z": MJ.phase_z(mag, 4, 200),
         "pace_px_per_frame": round(mm, 2), "jerk": round(jerk, 3),
         "stall_frac": round(stall / moving, 3) if moving else 0.0,
         "ghost_low_p95": round(float(np.percentile(ghost[ghost > 0], 95)), 3) if (ghost > 0).any() else 0.0}
    return m, {"diff": d.tolist(), "flow": mag.tolist()}


# ---------------- 声画 ----------------

def voice_env(a: np.ndarray, sr: int, fps: float, n: int) -> np.ndarray:
    """300–3400 Hz 能量包络（每视频帧一个值，dB）。"""
    if a.size == 0:
        return np.zeros(n)
    F = np.fft.rfft(a)
    f = np.fft.rfftfreq(a.size, 1 / sr)
    F[(f < 300) | (f > 3400)] = 0
    v = np.fft.irfft(F, a.size)
    hop = sr / fps
    out = np.zeros(n)
    for i in range(n):
        s = v[int(i * hop): int((i + 1) * hop)]
        out[i] = 10 * np.log10(float((s ** 2).mean()) + 1e-10) if s.size else -100
    return out


def xcorr(x: np.ndarray, y: np.ndarray, max_lag: int) -> tuple[int, float, float]:
    """→ (最佳 lag（正 = 嘴动晚于声音）, 最佳相关, lag 0 相关)"""
    def pc(a, b):
        if len(a) < 6 or a.std() < 1e-6 or b.std() < 1e-6:
            return 0.0
        return float(np.corrcoef(a, b)[0, 1])
    best, bl = -2.0, 0
    for lag in range(-max_lag, max_lag + 1):
        if lag >= 0:
            a, b = y[:len(y) - lag] if lag else y, x[lag:]
        else:
            a, b = y[-lag:], x[:len(x) + lag]
        c = pc(a, b)
        if c > best:
            best, bl = c, lag
    return bl, round(best, 3), round(pc(y, x), 3)


# ---------------- 单镜 ----------------

@dataclass
class Shot:
    sid: str
    path: Path
    start: float
    dur: float
    src_file: str | None = None
    speech: list = field(default_factory=list)


def analyze_shot(sh: Shot, faces: Faces, matrix: str, out_dir: Path, fps_hint: float = 24.0) -> dict:
    rgb = decode(sh.path, sh.start, sh.dur, TW, TH, matrix)
    n = len(rgb)
    fps = fps_hint
    gray_small = np.stack([cv2.resize(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), (SW, SH), interpolation=cv2.INTER_AREA)
                           for f in rgb])
    gray_flow = np.stack([cv2.resize(cv2.cvtColor(f, cv2.COLOR_RGB2GRAY), (FW, FH), interpolation=cv2.INTER_AREA)
                          for f in rgb])
    mot, series = motion_metrics(gray_small, gray_flow, fps)
    luma = gray_small.reshape(len(gray_small), -1).mean(1)
    dark = luma < DARK_LUMA
    run_, best_ = 0, 0
    for x in dark:
        run_ = run_ + 1 if x else 0
        best_ = max(best_, run_)
    mot["luma_mean"] = round(float(luma.mean()), 1)
    mot["dark_run_s"] = round(best_ / fps, 2)

    # 逐帧：所有脸（蓝发 = 林晚，其余 = other）、脸色 / 脸颊红、整帧红色异常、嘴部能量（按人分开）
    per = []
    last = []
    mouth_e = {"lin_wan": np.zeros(n), "other": np.zeros(n)}
    face_e = {"lin_wan": np.zeros(n), "other": np.zeros(n)}
    prev_gray = None
    for i, f in enumerate(rgb):
        if i % 2 == 0 or not last:
            last = [fc for fc in faces.detect(f, small=True) if float(fc[3]) >= 30]
        rb = red_blobs(f)
        row = {"i": i, "t": round(i / fps, 3), "frame_red": rb["red_frac"], "red_blob": rb["red_blob"]}
        g = cv2.cvtColor(f, cv2.COLOR_RGB2GRAY).astype(np.float32)
        labelled = label_faces(f, last)
        prim = labelled.get("lin_wan")
        if prim is None and labelled:
            prim = labelled["other"]
        if prim is not None:
            roi = face_roi(prim, f.shape)
            if roi:
                row.update({k: round(v, 3) for k, v in face_colour(f, roi).items()})
                ck = cheek_roi(prim, f.shape)
                if ck:
                    cc = face_colour(f, ck)
                    row["cheek_a_p95"] = round(cc["a_p95"], 2)
                    row["cheek_red"] = round(cc["red_frac"], 3)
                row["face_h"] = round(float(prim[3]) / TH, 3)
                row["who"] = "lin_wan" if prim is labelled.get("lin_wan") else "other"
        for who, fc in labelled.items():
            roi = face_roi(fc, f.shape)
            if not roi or prev_gray is None:
                continue
            x0, y0, x1, y1 = roi
            face_e[who][i] = float(np.abs(g[y0:y1, x0:x1] - prev_gray[y0:y1, x0:x1]).mean())
            # 嘴：YuNet 关键点 10–13 = 右 / 左嘴角
            mx, my = (fc[10] + fc[12]) / 2, (fc[11] + fc[13]) / 2
            md = max(6.0, abs(fc[12] - fc[10]))
            mx0, mx1 = int(max(0, mx - 0.9 * md)), int(min(TW, mx + 0.9 * md))
            my0, my1 = int(max(0, my - 0.5 * md)), int(min(TH, my + 0.7 * md))
            if mx1 > mx0 + 2 and my1 > my0 + 2:
                mouth_e[who][i] = float(np.abs(g[my0:my1, mx0:mx1] - prev_gray[my0:my1, mx0:mx1]).mean())
        row["faces"] = sorted(labelled)
        prev_gray = g
        per.append(row)

    with_face = [r for r in per if "a" in r]
    col = {}
    if with_face:
        T = np.array([r["t"] for r in with_face])
        CK = np.array([r.get("cheek_a_p95", r["a_p95"]) for r in with_face])
        CR = np.array([r.get("cheek_red", r["red_frac"]) for r in with_face])
        early = T <= max(0.5, T.min() + 0.5)
        base = float(np.median(CK[early]))
        da = CK - base
        k = int(np.argmax(np.abs(da)))
        col = {"face_frames": len(with_face), "face_frac": round(len(with_face) / n, 2),
               "face_who": max(set(r["who"] for r in with_face), key=lambda w: sum(r["who"] == w for r in with_face)),
               "face_L": round(float(np.median([r["L"] for r in with_face])), 2),
               "face_a": round(float(np.median([r["a"] for r in with_face])), 2),
               "face_b": round(float(np.median([r["b"] for r in with_face])), 2),
               "face_S": round(float(np.median([r["S"] for r in with_face])), 3),
               "face_hue": round(float(np.median([r["hue"] for r in with_face])), 1),
               "cheek_a_p95_start": round(base, 2), "cheek_a_p95_med": round(float(np.median(CK)), 2),
               "cheek_a_p95_max": round(float(CK.max()), 2),
               "cheek_a_max_drift": round(float(da[k]), 2), "cheek_a_max_drift_t": round(float(T[k]), 2),
               "cheek_red_max": round(float(CR.max()), 3), "cheek_red_med": round(float(np.median(CR)), 3),
               "cheek_red_max_t": round(float(T[int(np.argmax(CR))]), 2),
               "cheek_red_frames_over_25pct": int((CR >= 0.25).sum()),
               "face_h_med": round(float(np.median([r["face_h"] for r in with_face])), 3)}
    rbs = np.array([r["red_blob"] for r in per])
    col.update({"frame_red_frac_max": round(float(max(r["frame_red"] for r in per)), 4),
                "frame_red_blob_max": round(float(rbs.max()), 4),
                "frame_red_blob_max_t": round(float(np.argmax(rbs) / fps), 2)})
    flags = []
    if col.get("cheek_a_max_drift") is not None and abs(col["cheek_a_max_drift"]) >= A_DRIFT_WARN:
        flags.append(f"脸颊 a*p95 漂移 {col['cheek_a_max_drift']:+.1f}（{col['face_who']}）@ {col['cheek_a_max_drift_t']}s"
                     + ("（严重）" if abs(col["cheek_a_max_drift"]) >= A_DRIFT_FAIL else ""))
    if col.get("cheek_red_max", 0) >= CHEEK_RED_WARN:
        flags.append(f"脸颊泛红像素占比最高 {col['cheek_red_max']:.0%} @ {col['cheek_red_max_t']}s"
                     f"（≥25% 的帧 {col['cheek_red_frames_over_25pct']}）")
    if col["frame_red_blob_max"] >= 0.01:
        flags.append(f"整帧红色异常块最大 {col['frame_red_blob_max']:.1%} 画面 @ {col['frame_red_blob_max_t']}s")
    if mot["still_frac"] >= 0.5:
        flags.append(f"静止占比 {mot['still_frac']:.0%}")
    if mot["frozen_tail_s"] >= 0.5:
        flags.append(f"结尾定住 {mot['frozen_tail_s']}s")
    if mot["dark_run_s"] >= 1.0:
        flags.append(f"近黑画面连续 {mot['dark_run_s']}s")
    if mot["frozen_head_s"] >= 0.5:
        flags.append(f"开头定住 {mot['frozen_head_s']}s")
    if mot["J4"] >= 1.2 and mot["J4_z"] >= 3:
        flags.append(f"4 帧一顿 J4 {mot['J4']}（z {mot['J4_z']}）")

    # 接触印样 + 人物识别（全分辨率抽帧）
    # 末帧取 dur − 1.5 帧：成片里 start+dur−0.5 帧 已经落到下一镜第一帧（v0 第一版印样踩过）
    times = [sh.start + min(sh.dur - 1.5 / fps, sh.dur * k / (SHEET_N - 1)) for k in range(SHEET_N)]
    v = vstream(probe(sh.path))
    full_w, full_h = int(v.get("width", 768)), int(v.get("height", 1344))
    full = decode_frames_at(sh.path, times, full_w, full_h, matrix)
    # 人物：每帧所有 ≥80 px 的脸；蓝发 = 林晚（对 lin_wan 参考），其余对 gu_chen 参考；林晚在画面里就以林晚为准
    ident = {"faces": 0}
    by = {"lin_wan": [], "other": []}
    sharp, hair = [], []
    for f in full:
        big = [fc for fc in faces.detect(f) if float(fc[3]) >= 80]
        lab = label_faces(f, big)
        for fc in big:
            who = "lin_wan" if fc is lab.get("lin_wan") else "other"
            by[who].append(faces.embed(f, fc))
            x0, y0, x1, y1 = face_roi(fc, f.shape) or (0, 0, 1, 1)
            g = cv2.cvtColor(f[y0:y1, x0:x1], cv2.COLOR_RGB2GRAY)
            g = cv2.resize(g, (128, max(1, int(128 * g.shape[0] / max(1, g.shape[1])))))
            sharp.append(float(cv2.Laplacian(g, cv2.CV_64F).var()))
            if who == "lin_wan":
                hc = QF.hair_colour(cv2.cvtColor(f, cv2.COLOR_RGB2BGR), fc)
                if hc:
                    hair.append(hc)
    ref_key = {"lin_wan": "lin_wan", "other": "gu_chen"}
    people = {}
    for who, embs in by.items():
        if not embs:
            continue
        E = np.stack(embs)
        mean = E.mean(0)
        r = faces.refs.get(ref_key[who])
        sc = [QF.cosine(e, r) for e in embs] if r is not None else []
        people[who] = {"n": len(embs), "ref": ref_key[who],
                       "ref_cos_med": round(float(np.median(sc)), 3) if sc else None,
                       "ref_cos_min": round(float(np.min(sc)), 3) if sc else None,
                       "self_cos_min": round(float(min(QF.cosine(e, mean) for e in embs)), 3),
                       "_mean_emb": mean.tolist()}
    if people:
        who = "lin_wan" if "lin_wan" in people else "other"
        p = people[who]
        ident = {"faces": sum(len(v) for v in by.values()), "who": who, "people": people,
                 "ref_cos_med": {who: p["ref_cos_med"]}, "self_cos_min": p["self_cos_min"],
                 "face_sharp_lapvar_med": round(float(np.median(sharp)), 1) if sharp else None,
                 "hair_blue_ok": f"{sum(1 for h in hair if h.get('ok'))}/{len(hair)}" if hair else None,
                 "_mean_emb": p["_mean_emb"]}
        for w, q in people.items():
            if q["ref_cos_med"] is not None and q["ref_cos_med"] < SFACE_SAME:
                flags.append(f"{w} 与参考脸（{q['ref']}）余弦中位 {q['ref_cos_med']} < {SFACE_SAME}")
            if q["self_cos_min"] < 0.6 and q["n"] >= 3:
                flags.append(f"{w} 镜内脸不稳（与本镜平均脸最低余弦 {q['self_cos_min']}）")
    sheet = out_dir / "sheets" / f"{safe(sh.sid)}.jpg"
    make_sheet(full, [t - sh.start for t in times], sh.sid, per, fps, sheet)

    # 声画
    sync = []
    if sh.speech:
        sr = 16000
        a = audio_mono(sh.path, sr, sh.start, sh.dur)
        env = voice_env(a, sr, fps, n)
        for sp in sh.speech:
            i0 = max(0, int((sp["start_s"] - sh.start - 0.5) * fps))
            i1 = min(n, int((sp["end_s"] - sh.start + 0.5) * fps))
            if i1 - i0 < 12:
                continue
            seg_face = sum(1 for r in per[i0:i1] if "a" in r) / max(1, i1 - i0)
            if seg_face < 0.5:
                sync.append({"key": sp.get("key"), "speaker": sp.get("speaker"), "face_cover": round(seg_face, 2),
                             "note": "对白期间画面里多半没有可测的脸（画外音 / 背影 / 远景），不测"})
                continue
            who = "lin_wan" if sp.get("speaker") == "lin_wan" else "other"
            me = np.maximum(mouth_e[who] - 0.6 * face_e[who], 0)
            if (me[i0:i1] > 0).mean() < 0.4:
                sync.append({"key": sp.get("key"), "speaker": sp.get("speaker"), "face_cover": round(seg_face, 2),
                             "note": f"说话人（{who}）的脸在对白期间多半不在画面里，不测"})
                continue
            lag, best, c0 = xcorr(me[i0:i1], env[i0:i1], int(0.5 * fps))
            inside = me[int((sp["start_s"] - sh.start) * fps): int((sp["end_s"] - sh.start) * fps)]
            outside = np.concatenate([me[:max(0, i0)], me[min(n, i1):]])
            ratio = float(inside.mean() / (outside.mean() + 1e-3)) if outside.size >= 6 and inside.size else None
            sync.append({"key": sp.get("key"), "speaker": sp.get("speaker"), "kind": sp.get("kind"),
                         "t": [round(sp["start_s"], 2), round(sp["end_s"], 2)], "face_cover": round(seg_face, 2),
                         "best_lag_s": round(lag / fps, 3), "corr_best": best, "corr_lag0": c0,
                         "mouth_in_vs_out": round(ratio, 2) if ratio is not None else None})
    loud = ebur128(sh.path, sh.start, sh.dur)
    return {"shot": sh.sid, "start_s": round(sh.start, 3), "dur_s": round(sh.dur, 3), "src_file": sh.src_file,
            "motion": mot, "colour": col, "identity": ident, "scale": scale_label(col.get("face_h_med")),
            "lip_sync": sync, "loudness": loud, "flags": flags,
            "sheet": str(sheet.relative_to(ROOT)).replace("\\", "/"),
            "_series": {"t": [r["t"] for r in per], "a": [r.get("cheek_a_p95") for r in per],
                        "red_frac": [r.get("cheek_red") for r in per], "blob": [r["red_blob"] for r in per],
                        **series}}


def safe(s: str) -> str:
    return re.sub(r"[^\w.-]+", "_", s)


def make_sheet(frames, times, sid, per, fps, out: Path):
    from PIL import Image, ImageDraw, ImageFont
    out.parent.mkdir(parents=True, exist_ok=True)
    cols = 5
    rows = math.ceil(len(frames) / cols)
    hdr = 22
    W = cols * THUMB_W
    img = Image.new("RGB", (W, rows * (THUMB_H + hdr) + 26), (16, 16, 16))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=14)
    except TypeError:
        font = ImageFont.load_default()
    d.text((6, 5), f"{sid}  ({len(frames)} frames, a=cheek a* p95, R=cheek px a*>=25 %, B=frame red-blob %; red bar = flagged)", fill=(230, 230, 230),
           font=font)
    for k, (f, t) in enumerate(zip(frames, times)):
        x, y = (k % cols) * THUMB_W, 26 + (k // cols) * (THUMB_H + hdr)
        img.paste(Image.fromarray(f).resize((THUMB_W, THUMB_H), Image.LANCZOS), (x, y + hdr))
        i = min(len(per) - 1, int(round(t * fps)))
        r = per[i] if per else {}
        lab = f"t={t:.2f}s f{i}"
        if "cheek_a_p95" in r:
            lab += f" a{r['cheek_a_p95']:.0f} R{r['cheek_red']:.0%}"
        lab += f" B{r.get('red_blob', 0):.1%}"
        hot = r.get("cheek_red", 0) >= CHEEK_RED_WARN or r.get("red_blob", 0) >= 0.01
        d.rectangle([x, y, x + THUMB_W - 1, y + hdr - 1], fill=(120, 20, 20) if hot else (40, 40, 40))
        d.text((x + 4, y + 3), lab, fill=(255, 255, 255), font=font)
    img.save(out, quality=88)


def color_timeline(shots: list[dict], out: Path):
    """逐镜脸部 a* 曲线（横轴 = 成片时间），红线 = 脸内泛红像素占比 ×50。"""
    from PIL import Image, ImageDraw, ImageFont
    total = max(s.get("_plot_start", s["start_s"]) + s["dur_s"] for s in shots)
    W, H, pad = 1600, 420, 40
    img = Image.new("RGB", (W, H), (250, 250, 250))
    d = ImageDraw.Draw(img)
    try:
        font = ImageFont.load_default(size=13)
    except TypeError:
        font = ImageFont.load_default()
    lo, hi = 0.0, 50.0

    def X(t):
        return pad + (W - 2 * pad) * t / total

    def Y(v):
        return H - pad - (H - 2 * pad) * (min(max(v, lo), hi) - lo) / (hi - lo)
    for v in (10, 20, 25, 30):
        d.line([pad, Y(v), W - pad, Y(v)], fill=(220, 220, 220))
        d.text((4, Y(v) - 7), f"{v}", fill=(90, 90, 90), font=font)
    for s in shots:
        st = s.get("_plot_start", s["start_s"])
        x0 = X(st)
        d.line([x0, pad, x0, H - pad], fill=(180, 180, 200))
        d.text((x0 + 3, 8), s["shot"].split("-")[-1], fill=(40, 40, 40), font=font)
        ser = s["_series"]
        pts = [(X(st + t), Y(a)) for t, a in zip(ser["t"], ser["a"]) if a is not None]
        if len(pts) > 1:
            d.line(pts, fill=(30, 90, 200), width=2)
        rp = [(X(st + t), Y(r * 50)) for t, r, a in zip(ser["t"], ser["red_frac"], ser["a"]) if a is not None]
        if len(rp) > 1:
            d.line(rp, fill=(210, 40, 40), width=1)
    d.text((pad, H - 22), "blue = cheek a* p95 (LAB)   red = cheek pixels a*>=25 share x50   grid: 10/20/25/30",
           fill=(60, 60, 60), font=font)
    img.save(out)


def overview(shots: list[dict], out: Path, path_of, matrix):
    """每镜首 / 中 / 尾三帧一行。"""
    from PIL import Image
    tw, th = 135, 240
    img = Image.new("RGB", (3 * tw * 4, th * math.ceil(len(shots) / 4)), (0, 0, 0))
    for k, s in enumerate(shots):
        fr = decode_frames_at(path_of(s), [s["start_s"] + 0.02, s["start_s"] + s["dur_s"] / 2,
                                           s["start_s"] + s["dur_s"] - 0.06], tw, th, matrix)
        for j, f in enumerate(fr):
            img.paste(Image.fromarray(f), ((k % 4) * 3 * tw + j * tw, (k // 4) * th))
    img.save(out, quality=85)


# ---------------- 整集 ----------------

def cut_report(video: Path, shots: list[dict], matrix: str, a: np.ndarray, sr: int) -> list[dict]:
    rows = []
    gd = np.abs(np.diff(a)) if a.size else np.zeros(1)
    click_ref = float(np.percentile(gd, 99.9)) if a.size else 1.0
    for prev, nxt in zip(shots, shots[1:]):
        tc = nxt["start_s"]
        fr = decode(video, max(0, tc - 2 / 24), 4 / 24 + 0.01, 180, 320, matrix)
        if len(fr) >= 4:
            labs = [lab_of(f).reshape(-1, 3).mean(0) for f in fr[:4]]
            jump = de76(labs[1], labs[2])
            flash = de76(labs[2], labs[1]) > 8 and de76(labs[2], labs[3]) > 8 and de76(labs[1], labs[3]) < 4
            black = any(l[0] < 3 for l in labs)
        else:
            jump, flash, black = None, False, False
        i = int(tc * sr)
        w = int(0.1 * sr)
        pre, post = a[max(0, i - w):i], a[i:i + w]

        def db(x):
            return 20 * math.log10(float(np.sqrt((x ** 2).mean())) + 1e-9) if x.size else -120.0
        loc = gd[max(0, i - int(0.005 * sr)): i + int(0.005 * sr)]
        rows.append({"cut": f"{prev['shot']}→{nxt['shot']}", "t": round(tc, 3),
                     "picture_dE": round(jump, 1) if jump is not None else None, "flash_frame": bool(flash),
                     "black_frame": bool(black), "audio_pre_db": round(db(pre), 1), "audio_post_db": round(db(post), 1),
                     "audio_jump_db": round(db(post) - db(pre), 1),
                     "click": bool(loc.size and loc.max() > 3 * click_ref)})
    return rows


def silence_segments(a: np.ndarray, sr: int, thr_db: float = -50.0, min_s: float = 1.0) -> list:
    win = sr // 10
    n = a.size // win
    if n == 0:
        return []
    db = 20 * np.log10(np.sqrt((a[: n * win].reshape(n, win) ** 2).mean(1)) + 1e-9)
    segs, i = [], 0
    while i < n:
        if db[i] < thr_db:
            j = i
            while j < n and db[j] < thr_db:
                j += 1
            if (j - i) * 0.1 >= min_s:
                segs.append([round(i * 0.1, 1), round(j * 0.1, 1)])
            i = j
        else:
            i += 1
    return segs


def cross_shot(shots: list[dict]) -> dict:
    """跨镜：每个人（lin_wan / other）各镜平均脸向量 → 与该人全集平均的余弦；脸部平均色 → 与全集中位的 ΔE76。
    other = 非林晚的最大那张脸（多为顾沉；S9 等镜可能是别的角色，看印样确认）。"""
    ident, colour = {}, {}
    for who in ("lin_wan", "other"):
        rows = [(s["shot"], np.array(s["identity"]["people"][who]["_mean_emb"])) for s in shots
                if who in (s["identity"].get("people") or {})]
        if len(rows) >= 2:
            m = np.mean([e for _, e in rows], 0)
            ident[who] = {k: round(QF.cosine(e, m), 3) for k, e in rows}
    labs = [(s["shot"], [s["colour"].get("face_L"), s["colour"].get("face_a"), s["colour"].get("face_b")])
            for s in shots if s["colour"].get("face_who") == "lin_wan" and s["colour"].get("face_L") is not None]
    if len(labs) >= 2:
        ml = np.median([l for _, l in labs], 0)
        colour["lin_wan"] = {k: round(de76(l, ml), 2) for k, l in labs}
    return {"identity_cos_to_char_mean": ident, "face_dE_to_char_median": colour}


def auto_scores(rep: dict) -> dict:
    """机器预评分（0–10，只是提示，最终分以 DIR 看接触印样后的人工分为准；规则见 rubric.md）。"""
    shots = rep["shots"]

    def clamp(x):
        return round(float(max(0.0, min(10.0, float(x)))), 1)
    out = {}
    # ① 人物一致性
    cs = []
    for s in shots:
        idn = s["identity"]
        if idn.get("who") and (idn.get("ref_cos_med") or {}).get(idn["who"]) is not None:   # DIRECTOR 11-02：静帧占位镜参考余弦为 None
            cs.append(idn["ref_cos_med"][idn["who"]])
    xs = [v for d in rep["cross"]["identity_cos_to_char_mean"].values() for v in d.values()]
    if cs:
        out["identity"] = clamp(10 * min(1, (np.percentile(cs, 10) - 0.2) / 0.4) - (3 if xs and min(xs) < 0.6 else 0))
    # ④ 运动
    st = np.array([s["motion"]["still_frac"] for s in shots])
    tails = np.array([s["motion"]["frozen_tail_s"] for s in shots])
    j4 = np.array([s["motion"]["J4"] if s["motion"]["J4_z"] >= 3 else 1.0 for s in shots])
    out["motion"] = clamp(10 - 8 * float((st >= 0.5).mean()) - 2 * float((tails >= 0.5).mean())
                          - 10 * float(np.clip(j4 - 1.1, 0, 0.3).mean()))
    # ⑦ 调色
    drifts = [abs(s["colour"].get("cheek_a_max_drift", 0)) for s in shots]
    xde = [v for d in rep["cross"]["face_dE_to_char_median"].values() for v in d.values()]
    out["grade"] = clamp(10 - 0.3 * max(0, max(drifts) - 4)
                         - 3 * sum(1 for s in shots if s["colour"].get("cheek_red_max", 0) >= CHEEK_RED_WARN) / len(shots) - 0.4 * max(0, (max(xde) if xde else 0) - 4)
                         - 2 * sum(1 for s in shots if s["colour"]["frame_red_blob_max"] >= 0.01) / len(shots))
    # ⑥ 声画
    L = rep.get("loudness", {})
    pen = 0.0
    if L.get("I_lufs") is not None:
        pen += min(3, abs(L["I_lufs"] + 14) * 1.0)
    if L.get("true_peak_dbtp") is not None and L["true_peak_dbtp"] > -1.0:
        pen += 1.5
    syn = [x for s in shots for x in s["lip_sync"] if "corr_best" in x]
    if syn:
        good = sum(1 for x in syn if x["corr_best"] >= 0.3 and abs(x["best_lag_s"]) <= 0.12)
        pen += 4 * (1 - good / len(syn))
    pen += min(2, 0.5 * sum(1 for c in rep.get("cuts", []) if c["click"] or abs(c["audio_jump_db"]) > 15))
    out["av"] = clamp(10 - pen)
    # ⑤ 短剧观感（只剪辑技术面）
    du = np.array([s["dur_s"] for s in shots])
    scales = [s["scale"] for s in shots]
    same = sum(1 for a, b in zip(scales, scales[1:]) if a == b)
    pen = 0.0
    pen += 2.5 * max(0, float(du.mean()) - 4.0) / 2      # 竖屏短剧常见 2–4 s 一刀；均长每多 2 s 扣 2.5
    pen += 2 * same / max(1, len(shots) - 1)
    hook = rep.get("hook", {})
    if hook.get("cuts_in_3s", 0) == 0:
        pen += 1.5
    pen += 3 * float((st >= 0.5).mean())
    out["editing"] = clamp(10 - pen)
    # ② 鬼影 / ③ 质感：只给提示（自动指标区分力弱，以印样为准）
    gh = [s["motion"]["ghost_low_p95"] for s in shots]
    out["ghost_hint"] = round(float(np.median(gh)), 3) if gh else None
    sh = [s["identity"].get("face_sharp_lapvar_med") for s in shots if s["identity"].get("face_sharp_lapvar_med")]
    out["face_sharp_hint"] = round(float(np.median(sh)), 1) if sh else None
    return out


def write_md(rep: dict, out: Path):
    L = rep.get("loudness", {})
    lines = [f"# 审片报告：{rep['name']}", "",
             f"- 文件：`{rep['video']}`；时长 {rep.get('duration_s')} s；{rep.get('n_shots')} 镜；解码矩阵 {rep['matrix']}"
             f"（文件标记 {rep.get('color_tags')}）",
             f"- 人脸：{rep['face_backend']}",
             f"- 响度：I {L.get('I_lufs')} LUFS、LRA {L.get('LRA')}、真峰值 {L.get('true_peak_dbtp')} dBTP；"
             f"≥1 s 静音段 {rep.get('silence', [])}",
             f"- 开场 3 s：{rep.get('hook')}",
             f"- 机器预评分（提示，不是终分）：{rep.get('auto_scores')}", "",
             "## 逐镜", "",
             "| 镜 | 时长 | 景别 | 帧差均值 | 静止 | 头/尾定住 s | J4 (z) | 节奏 px/帧 | 鬼影p95 | 人物(参考余弦) | 脸 L/a/b | 脸颊a*p95 起→max | 脸颊泛红max | 红块max | 每镜 I | 印样 |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    for s in rep["shots"]:
        m, c, i = s["motion"], s["colour"], s["identity"]
        who = i.get("who")
        idt = f"{who} {i['ref_cos_med'][who]}" if who else "—"
        lines.append(
            f"| {s['shot']} | {s['dur_s']} | {s['scale']} | {m['diff_mean']} | {m['still_frac']:.0%} | "
            f"{m['frozen_head_s']}/{m['frozen_tail_s']} | {m['J4']} ({m['J4_z']}) | {m['pace_px_per_frame']} | "
            f"{m['ghost_low_p95']} | {idt} | {c.get('face_L', '—')}/{c.get('face_a', '—')}/{c.get('face_b', '—')} | "
            f"{c.get('cheek_a_p95_start', '—')}→{c.get('cheek_a_p95_max', '—')} | {c.get('cheek_red_max', '—')} | {c['frame_red_blob_max']} | "
            f"{s['loudness'].get('I_lufs')} | [{Path(s['sheet']).name}]({'sheets/' + Path(s['sheet']).name}) |")
    lines += ["", "## 逐镜问题（自动标记）", ""]
    for s in rep["shots"]:
        lines.append(f"- **{s['shot']}**：" + ("；".join(s["flags"]) if s["flags"] else "无自动标记"))
    syn = [(s["shot"], x) for s in rep["shots"] for x in s["lip_sync"]]
    if syn:
        lines += ["", "## 声画（嘴部能量 vs 语音包络）", "",
                  "| 镜 | 句 | 说话人 | 时间 | 脸覆盖 | 最佳偏移 s | 最佳相关 | 0 偏移相关 | 嘴动 句内/句外 |",
                  "|---|---|---|---|---|---|---|---|---|"]
        for sid, x in syn:
            lines.append(f"| {sid} | {x.get('key')} | {x.get('speaker')} | {x.get('t', '')} | {x.get('face_cover')} | "
                         f"{x.get('best_lag_s', '—')} | {x.get('corr_best', '—')} | {x.get('corr_lag0', '—')} | "
                         f"{x.get('mouth_in_vs_out', x.get('note', '—'))} |")
    if rep.get("cuts"):
        lines += ["", "## 切点", "", "| 切点 | t | 画面 ΔE | 闪帧 | 黑帧 | 音频 前/后 dB | 跳变 dB | 爆音 |",
                  "|---|---|---|---|---|---|---|---|"]
        for c in rep["cuts"]:
            lines.append(f"| {c['cut']} | {c['t']} | {c['picture_dE']} | {c['flash_frame']} | {c['black_frame']} | "
                         f"{c['audio_pre_db']}/{c['audio_post_db']} | {c['audio_jump_db']} | {c['click']} |")
    lines += ["", "## 跨镜一致性", "", "```", json.dumps(rep["cross"], ensure_ascii=False, indent=1), "```", "",
              "曲线：`color_timeline.png`（蓝 = 脸部 a*，红 = 脸内 a*≥25 像素占比 ×50）；总览：`overview.jpg`。"]
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")


def strip_private(o):
    if isinstance(o, dict):
        return {k: strip_private(v) for k, v in o.items() if not k.startswith("_")}
    if isinstance(o, list):
        return [strip_private(v) for v in o]
    return o


def review(name: str, items: list[Shot], video_for_episode: Path | None, matrix_assume: str = "bt709",
           timeline: dict | None = None) -> dict:
    out = OUT_BASE / name
    (out / "sheets").mkdir(parents=True, exist_ok=True)
    faces = Faces()
    shots = []
    p0 = probe(items[0].path)
    v0 = vstream(p0)
    matrix = matrix_of(v0, matrix_assume)
    for sh in items:
        v = vstream(probe(sh.path))
        m = matrix_of(v, matrix_assume)
        print(f"[{name}] {sh.sid} {sh.path.name} {sh.start:.2f}+{sh.dur:.2f}s matrix={m}", flush=True)
        r = analyze_shot(sh, faces, m, out, fps_of(v))
        r["matrix"] = m
        r["color_tags"] = {k: v.get(k) for k in ("color_space", "color_primaries", "color_transfer", "color_range")}
        shots.append(r)
    rep = {"name": name, "video": str(video_for_episode or items[0].path), "matrix": matrix,
           "color_tags": {k: v0.get(k) for k in ("color_space", "color_primaries", "color_transfer", "color_range")},
           "face_backend": faces.note if faces.ok else f"无人脸模型（{faces.note}）：人物一致性只用颜色直方图代理",
           "n_shots": len(shots), "shots": shots}
    if video_for_episode is not None:
        sr = 16000
        a = audio_mono(video_for_episode, sr)
        rep["duration_s"] = round(float(vstream(p0).get("duration") or p0.get("format", {}).get("duration", 0)), 3)
        rep["loudness"] = ebur128(video_for_episode)
        rep["silence"] = silence_segments(a, sr)
        rep["cuts"] = cut_report(video_for_episode, shots, matrix, a, sr)
        d3 = [s for s in shots if s["start_s"] < 3.0]
        rep["hook"] = {"cuts_in_3s": sum(1 for s in shots if 0 < s["start_s"] < 3.0),
                       "first_shot_dur_s": shots[0]["dur_s"], "first_shot_scale": shots[0]["scale"],
                       "first_shot_pace": shots[0]["motion"]["pace_px_per_frame"],
                       "speech_starts_s": min([x["start_s"] for x in (timeline or {}).get("speech", [])] or [None])
                       if (timeline or {}).get("speech") else None, "shots_in_3s": len(d3)}
        du = [s["dur_s"] for s in shots]
        rep["rhythm"] = {"durations": du, "mean": round(float(np.mean(du)), 2), "cv": round(float(np.std(du) / np.mean(du)), 2),
                         "scales": [s["scale"] for s in shots]}
    rep["cross"] = cross_shot(shots) if QF else {}
    rep["auto_scores"] = auto_scores(rep)
    color_timeline(shots if video_for_episode else _restack(shots), out / "color_timeline.png")
    try:
        overview(shots if video_for_episode else _restack(shots), out / "overview.jpg",
                 (lambda s: video_for_episode) if video_for_episode else
                 (lambda s: next(it.path for it in items if it.sid == s["shot"])), matrix)
    except Exception as e:  # noqa: BLE001
        print("overview failed", e)
    (out / "review.json").write_text(json.dumps(strip_private(rep), ensure_ascii=False, indent=1), encoding="utf-8")
    series = {s["shot"]: s["_series"] for s in shots}
    (out / "series.json").write_text(json.dumps(series), encoding="utf-8")
    write_md(rep, out / "review.md")
    print("->", out)
    return rep


def _restack(shots):
    """clips 模式：每条从 0 开始；画曲线时首尾相接排开。总览按各自文件取帧（start 仍是 0）。"""
    t = 0.0
    res = []
    for s in shots:
        s2 = dict(s)
        s2["_plot_start"] = t
        t += s["dur_s"]
        res.append(s2)
    return res


def main(argv=None):
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="mode", required=True)
    e = sub.add_parser("episode")
    e.add_argument("video")
    e.add_argument("timeline")
    e.add_argument("--name", required=True)
    e.add_argument("--assume-matrix", default="bt709", help="文件没有色彩标记时按什么解码（播放器对高清默认 bt709）")
    c = sub.add_parser("clips")
    c.add_argument("items", nargs="+", help="名=路径 或 路径")
    c.add_argument("--name", required=True)
    c.add_argument("--assume-matrix", default="bt709")
    a = ap.parse_args(argv)
    if a.mode == "episode":
        video = Path(a.video)
        video = video if video.is_absolute() else ROOT / video
        tl = json.loads(Path(a.timeline).read_text(encoding="utf-8"))
        items = []
        for s in tl["shots"]:
            sp = [x for x in tl.get("speech", []) if x.get("shot") == s["index"] and x.get("kind") == "dialogue"]
            items.append(Shot(s["shot"], video, float(s["start_s"]), float(s["duration_s"]), s.get("file"), sp))
        review(a.name, items, video, a.assume_matrix, tl)
    else:
        items = []
        for it in a.items:
            k, p = it.split("=", 1) if "=" in it else (Path(it).stem, it)
            p = Path(p) if Path(p).is_absolute() else ROOT / p
            v = vstream(probe(p))
            dur = float(v.get("nb_frames") or 0) / fps_of(v) if v.get("nb_frames") else float(v.get("duration", 0))
            items.append(Shot(k, p, 0.0, dur, str(p)))
        review(a.name, items, None, a.assume_matrix)


if __name__ == "__main__":
    main()
