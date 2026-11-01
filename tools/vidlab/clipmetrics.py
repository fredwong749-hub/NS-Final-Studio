"""VIDLAB（线 2：视频 RSI，总调度 fredw-2b 派，2026-11-02）：单条视频 / 片段的“表演 + 运镜”像素指标。

只看像素，不看剧情；我们的片和好莱坞参照片用同一套函数量，参照的中位数就是满分锚点（RSI_PROGRAM 线 2）。

逐帧（默认 12 fps，ffmpeg 解码，长边缩到 ≤ 1280）：
- 人脸：YuNet（ns_qc.face，OpenCV zoo）找脸 → 简单最近中心跟踪 → 每条脸轨迹按框外扩裁出放大到 384，
  跑 MediaPipe FaceLandmarker（models_cache/vision/face_landmarker.task，同 ns_qc.gaze_mp）拿 52 个 blendshape + 478 点。
- 表情（每条轨迹，覆盖 ≥ 40% 帧且 ≥ 12 帧才算）：
  expr_std   表情类 blendshape（眉 / 眼睑 / 脸颊 / 嘴 / 鼻，去掉眼球方向）3 帧中值平滑后的时间标准差，取平均
  expr_rng   同上 p95 − p5 的平均（表情幅度）
  brow_rng   上半脸（browInnerUp / browDown / browOuterUp / eyeWide / eyeSquint）的 p95 − p5 平均——“死脸”最先死在眉眼
  lm_nonrigid 478 点按两眼中心对齐（平移 + 缩放 + 旋转）后，相对 1.5 s 滑动均值形状的残差 RMS ÷ 两眼距（面部关键点快速非刚性运动；高通去掉慢转头的投影形变）
  head_std   头部转动：yaw_n / pitch_n（gaze_mp 同口径）与两眼连线角（度 / 45）的稳健标准差（p90−p10）/2.56 之和；v3 起剔除关键点错位帧
  blink_pm   眨眼次数 / 分钟（eyeBlink 均值上升沿越过 max(0.35, 轨迹中位 +0.25)，间隔 ≥ 0.15 s；v3 起）
  gaze_shift_ps 视线跳动次数 / 秒（blendshape 眼球方向 0.25 s 内变化 > 0.18）
  cam_gaze   gaze_mp 判“疑似看镜头”的帧占比
- 运镜（整帧，320 宽灰度；脸框和其下方身体区域挡掉，只看背景）：LK 光流 + estimateAffinePartial2D（RANSAC）
  每对帧的平移 / 缩放 / 旋转 → 每秒运动量（平移按画面对角线归一，缩放取 |log s|，旋转 弧度）
  cam_speed_med 每秒运动量中位，cam_moving_frac 每秒运动量 > 3% 对角线的帧占比（1% 在 LK 噪声底以下，v3 起），cam_path_ps 平均每秒累计运动量
- 卡顿：tools/motion_judder.analyze 的 J4（只对完整小片段算；参照电影不算）

本模块不做判断，只出数；判定在 tools/vidlab/score.py。
"""
from __future__ import annotations

import os as _os
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):   # K-OPS-V13：限线程
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for p in ("packages/qc", "tools"):
    sys.path.insert(0, str(ROOT / p))

import cv2  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent))
import vio as VIO  # noqa: E402

cv2.setNumThreads(int(_os.environ.get("NS_SCORE_THREADS", "4")))

ALGO = "vlm-cm-v3"          # 改算法就改版本号，缓存自动失效
CACHE = ROOT / "data" / "rsi" / "vidlab" / "clip_cache"
FPS = 12.0

EXPR_BS = ["browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
           "cheekPuff", "cheekSquintLeft", "cheekSquintRight", "eyeSquintLeft", "eyeSquintRight", "eyeWideLeft", "eyeWideRight",
           "jawOpen", "jawForward", "mouthClose", "mouthDimpleLeft", "mouthDimpleRight", "mouthFrownLeft", "mouthFrownRight",
           "mouthFunnel", "mouthLeft", "mouthRight", "mouthLowerDownLeft", "mouthLowerDownRight", "mouthPressLeft", "mouthPressRight",
           "mouthPucker", "mouthRollLower", "mouthRollUpper", "mouthShrugLower", "mouthShrugUpper", "mouthSmileLeft", "mouthSmileRight",
           "mouthStretchLeft", "mouthStretchRight", "mouthUpperUpLeft", "mouthUpperUpRight", "noseSneerLeft", "noseSneerRight"]
UPPER_BS = ["browDownLeft", "browDownRight", "browInnerUp", "browOuterUpLeft", "browOuterUpRight",
            "eyeWideLeft", "eyeWideRight", "eyeSquintLeft", "eyeSquintRight"]

_FM = None


def face_models():
    global _FM
    if _FM is None:
        from ns_qc import face as QF
        paths = QF.find_models(ROOT)
        _FM = QF.FaceModels(*paths, score=0.6) if paths else False
    return _FM or None


def landmarker():
    from ns_qc import gaze_mp as G
    return G.landmarker()


def decode(path: Path, t0: float = 0.0, dur: float | None = None, fps: float = FPS, max_side: int = 1280):
    """ffmpeg → BGR 帧列表（均匀 fps）。先探测尺寸。"""
    pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height",
                         "-of", "csv=p=0", str(path)], capture_output=True, text=True, timeout=120)
    w, h = [int(x) for x in pr.stdout.strip().split(",")[:2]]
    s = min(1.0, max_side / max(w, h))
    W, H = int(round(w * s / 2) * 2), int(round(h * s / 2) * 2)
    cmd = ["ffmpeg", "-v", "error"]
    if t0 > 0:
        cmd += ["-ss", f"{t0:.3f}"]
    cmd += ["-i", str(path)]
    if dur:
        cmd += ["-t", f"{dur:.3f}"]
    cmd += ["-vf", f"fps={fps},scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    raw = subprocess.run(cmd, capture_output=True, timeout=1800).stdout
    n = len(raw) // (W * H * 3)
    arr = np.frombuffer(raw[: n * W * H * 3], np.uint8).reshape(n, H, W, 3)
    return list(arr), (W, H)


# ---------------- 人脸轨迹 + blendshape ----------------

def _lm_on_crop(bgr, box, pad=0.6, size=384):
    lm = landmarker()
    if lm is None:
        return None
    mp, det = lm
    H, W = bgr.shape[:2]
    x, y, w, h = box
    x0, y0 = max(0, int(x - pad * w)), max(0, int(y - pad * h))
    x1, y1 = min(W, int(x + w + pad * w)), min(H, int(y + h + pad * h))
    crop = bgr[y0:y1, x0:x1]
    if crop.size == 0:
        return None
    s = size / max(crop.shape[:2])
    crop = cv2.resize(crop, (max(1, int(crop.shape[1] * s)), max(1, int(crop.shape[0] * s))), interpolation=cv2.INTER_CUBIC)
    rgb = np.ascontiguousarray(crop[:, :, ::-1])
    res = det.detect(mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb))
    if not res.face_landmarks:
        return None
    cw, ch = crop.shape[1], crop.shape[0]
    cx, cy = (x - x0 + w / 2) * s, (y - y0 + h / 2) * s
    best, bd = None, 1e18
    for i, pts in enumerate(res.face_landmarks):
        P = np.array([[p.x * cw, p.y * ch] for p in pts])
        d = (P[:, 0].mean() - cx) ** 2 + (P[:, 1].mean() - cy) ** 2
        if d < bd:
            bd, best = d, (P, {c.category_name: c.score for c in (res.face_blendshapes[i] if res.face_blendshapes else [])})
    if best is None or len(best[0]) < 478:
        return None
    return best


def _ratio(p, a, b) -> float:
    v = b - a
    d = float(np.dot(v, v))
    return float(np.clip(2 * np.dot(p - a, v) / d - 1, -1.5, 1.5)) if d > 1e-9 else 0.0


def _face_feats(P, bs):
    yaw = _ratio(P[1], P[234], P[454]) if P[234][0] < P[454][0] else _ratio(P[1], P[454], P[234])
    pitch = float(np.clip((P[1][1] - P[10][1]) / max(1e-6, P[152][1] - P[10][1]) - 0.5, -1.5, 1.5))
    le, re = P[468], P[473]
    roll = float(np.degrees(np.arctan2(re[1] - le[1], re[0] - le[0])))
    if roll > 90:
        roll -= 180
    elif roll < -90:
        roll += 180
    ex = []
    for c1, c2, ir in ((33, 133, 468), (362, 263, 473)):
        a, b = (P[c1], P[c2]) if P[c1][0] < P[c2][0] else (P[c2], P[c1])
        ex.append(_ratio(P[ir], a, b))
    gx = yaw + float(np.mean(ex))
    cam = abs(gx) <= 0.30 and abs(pitch) <= 0.62
    bs_x = ((bs.get("eyeLookOutLeft", 0) - bs.get("eyeLookInLeft", 0)) - (bs.get("eyeLookOutRight", 0) - bs.get("eyeLookInRight", 0))) / 2
    bs_y = (bs.get("eyeLookDownLeft", 0) + bs.get("eyeLookDownRight", 0) - bs.get("eyeLookUpLeft", 0) - bs.get("eyeLookUpRight", 0)) / 2
    iod = float(np.linalg.norm(le - re))
    # 对齐：两眼中心为原点、两眼距为 1、两眼连线水平
    c = (le + re) / 2
    ang = np.arctan2(re[1] - le[1], re[0] - le[0])
    R = np.array([[np.cos(-ang), -np.sin(-ang)], [np.sin(-ang), np.cos(-ang)]])
    A = ((P - c) @ R.T) / max(iod, 1e-6)
    return {"yaw": yaw, "pitch": pitch, "roll": roll, "bs_x": bs_x, "bs_y": bs_y, "cam": cam,
            "blink": (bs.get("eyeBlinkLeft", 0) + bs.get("eyeBlinkRight", 0)) / 2,
            "expr": np.array([bs.get(k, 0.0) for k in EXPR_BS]), "upper": np.array([bs.get(k, 0.0) for k in UPPER_BS]),
            "aligned": A.astype(np.float32), "iod_px": iod}


def face_tracks(frames, min_face_frac=0.05):
    fm = face_models()
    if fm is None:
        return [], "YuNet 不可用"
    tracks = []   # {"c": (x,y), "w": w, "obs": {i: feats}, "h": [face_h_frac]}
    for i, f in enumerate(frames):
        H = f.shape[0]
        dets = [d for d in fm.faces(f) if d[3] / H >= min_face_frac]
        dets = sorted(dets, key=lambda d: -d[2] * d[3])[:3]
        used = set()
        for d in dets:
            x, y, w, h = [float(v) for v in d[:4]]
            cx, cy = x + w / 2, y + h / 2
            best, bd = None, 1e18
            for k, t in enumerate(tracks):
                if k in used or i - t["last"] > 6:
                    continue
                dd = (t["c"][0] - cx) ** 2 + (t["c"][1] - cy) ** 2
                if dd < (0.6 * max(w, t["w"])) ** 2 and dd < bd:
                    best, bd = k, dd
            if best is None:
                tracks.append({"c": (cx, cy), "w": w, "obs": {}, "h": [], "last": i})
                best = len(tracks) - 1
            used.add(best)
            t = tracks[best]
            t["c"], t["w"], t["last"] = (cx, cy), w, i
            t["h"].append(h / H)
            r = _lm_on_crop(f, (x, y, w, h))
            if r is not None:
                t["obs"][i] = _face_feats(*r)
    return tracks, ""


def _medfilt3(x):
    if len(x) < 3:
        return x
    y = x.copy()
    y[1:-1] = np.median(np.stack([x[:-2], x[1:-1], x[2:]]), axis=0)
    return y


def track_metrics(t, n_frames, fps):
    idx = sorted(t["obs"])
    if len(idx) < max(12, 0.4 * n_frames):
        return None
    O = [t["obs"][i] for i in idx]
    A = np.stack([o["aligned"] for o in O])
    # 坏帧剔除（v3）：关键点相对轨迹中位形状的 RMS > 5 × 中位数 = 检测错位 / 换人，整帧不进任何指标
    med_shape = np.median(A, 0)
    rms0 = np.sqrt(((A - med_shape) ** 2).sum(-1).mean(-1))
    keep = rms0 <= 5 * max(float(np.median(rms0)), 1e-3)
    if keep.sum() < max(12, 0.4 * n_frames):
        return None
    O = [o for o, k in zip(O, keep) if k]
    idx = [i for i, k in zip(idx, keep) if k]
    A = A[keep]
    E = _medfilt3(np.stack([o["expr"] for o in O]))
    U = _medfilt3(np.stack([o["upper"] for o in O]))
    yaw = np.array([o["yaw"] for o in O]); pitch = np.array([o["pitch"] for o in O]); roll = np.array([o["roll"] for o in O])
    # 1.5 s 滑动均值做高通：去掉慢速转头在 2D 投影里造成的“假形变”，只留表情 / 说话 / 微表情这类快形变
    win = max(3, int(round(1.5 * fps)) | 1)
    ker = np.ones(win) / win
    pad = win // 2
    Ap = np.concatenate([A[:1].repeat(pad, 0), A, A[-1:].repeat(pad, 0)])
    sm = np.apply_along_axis(lambda v: np.convolve(v, ker, mode="valid"), 0, Ap.reshape(len(Ap), -1)).reshape(A.shape)
    nonrigid = float(np.sqrt(((A - sm) ** 2).sum(-1).mean()))
    # 眨眼（v3 自适应）：12 fps 下一次眨眼只占 1–2 帧，blendshape 常到不了 0.5 → 超过本轨迹中位 +0.25 且 ≥0.35 的上升沿
    blink = np.array([o["blink"] for o in O])
    thr = max(0.35, float(np.median(blink)) + 0.25)
    ups, last_t = 0, -1e9
    for k in range(1, len(blink)):
        if blink[k] >= thr > blink[k - 1] and (idx[k] - last_t) / fps >= 0.15:
            ups += 1
            last_t = idx[k]
    bx = np.array([o["bs_x"] for o in O]); by = np.array([o["bs_y"] for o in O])
    lag = max(1, int(round(0.25 * fps)))
    g = np.hypot(bx[lag:] - bx[:-lag], by[lag:] - by[:-lag]) if len(bx) > lag else np.array([])
    shifts, k = 0, 0
    while k < len(g):
        if g[k] > 0.18:
            shifts += 1
            k += lag
        else:
            k += 1

    def rstd(x):   # 稳健标准差（p90−p10）/ 2.56
        return float(np.percentile(x, 90) - np.percentile(x, 10)) / 2.56
    span_s = max((idx[-1] - idx[0] + 1) / fps, 1e-6)
    return {"frames": len(idx), "coverage": round(len(idx) / n_frames, 3), "blink_series": [round(float(b), 3) for b in blink], "face_h_med": round(float(np.median(t["h"])), 3),
            "expr_std": round(float(E.std(0).mean()), 4),
            "expr_rng": round(float((np.percentile(E, 95, 0) - np.percentile(E, 5, 0)).mean()), 4),
            "brow_rng": round(float((np.percentile(U, 95, 0) - np.percentile(U, 5, 0)).mean()), 4),
            "lm_nonrigid": round(nonrigid, 4),
            "head_std": round(rstd(yaw) + rstd(pitch) + rstd(roll) / 45.0, 4), "dropped": int((~keep).sum()),
            "blink_pm": round(ups / span_s * 60, 2), "gaze_shift_ps": round(shifts / span_s, 3),
            "cam_gaze": round(float(np.mean([o["cam"] for o in O])), 3)}


# ---------------- 运镜（背景全局运动） ----------------

def camera_motion(frames, face_boxes_per_frame, fps):
    if len(frames) < 3:
        return None
    H0, W0 = frames[0].shape[:2]
    s = 320 / W0
    w, h = 320, int(round(H0 * s))
    diag = float(np.hypot(w, h))
    gray = [cv2.cvtColor(cv2.resize(f, (w, h), interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY) for f in frames]
    sp, mov = [], []
    for i in range(1, len(gray)):
        mask = np.full((h, w), 255, np.uint8)
        for (x, y, bw, bh) in face_boxes_per_frame.get(i - 1, []):
            x0, x1 = int((x - bw) * s), int((x + 2 * bw) * s)
            y0, y1 = int((y - 0.5 * bh) * s), int((y + 4 * bh) * s)   # 脸 + 下方身体
            mask[max(0, y0):max(0, y1), max(0, x0):max(0, x1)] = 0
        p0 = cv2.goodFeaturesToTrack(gray[i - 1], 300, 0.01, 6, mask=mask)
        if p0 is None or len(p0) < 12:
            p0 = cv2.goodFeaturesToTrack(gray[i - 1], 300, 0.01, 6)
        if p0 is None or len(p0) < 8:
            continue
        p1, st, _ = cv2.calcOpticalFlowPyrLK(gray[i - 1], gray[i], p0, None, winSize=(21, 21), maxLevel=3)
        ok = st.reshape(-1) == 1
        if ok.sum() < 8:
            continue
        M, inl = cv2.estimateAffinePartial2D(p0[ok], p1[ok], method=cv2.RANSAC, ransacReprojThreshold=1.5)
        if M is None:
            continue
        sc = float(np.hypot(M[0, 0], M[1, 0]))
        rot = float(np.arctan2(M[1, 0], M[0, 0]))
        # 平移按画面中心换算（去掉缩放 / 旋转带来的中心位移）
        c = np.array([w / 2, h / 2])
        tc = M[:, :2] @ c + M[:, 2] - c
        m = (float(np.hypot(*tc)) / diag + abs(np.log(max(sc, 1e-6))) + abs(rot)) * fps
        sp.append(m)
    if not sp:
        return None
    sp = np.array(sp)
    spf = _medfilt3(sp)
    return {"cam_speed_med": round(float(np.median(spf)), 4), "cam_moving_frac": round(float((spf > 0.03).mean()), 3),
            "cam_path_ps": round(float(spf.mean()), 4), "cam_pairs": int(len(sp))}


def analyze(path: Path, t0: float = 0.0, dur: float | None = None, fps: float = FPS, j4: bool = True, use_cache: bool = True) -> dict:
    path = Path(path)
    st = path.stat()
    key = hashlib.sha1(f"{ALGO}|{path.resolve()}|{st.st_size}|{int(st.st_mtime)}|{t0:.2f}|{dur}|{fps}|{j4}".encode()).hexdigest()[:20]
    cf = CACHE / f"{key}.json"
    if use_cache and cf.is_file():
        return VIO.read_json(cf)
    frames, (W, H) = decode(path, t0, dur, fps)
    out = {"algo": ALGO, "path": str(path), "t0": t0, "dur": dur, "fps": fps, "n": len(frames), "size": [W, H]}
    tracks, note = face_tracks(frames)
    tm = [m for m in (track_metrics(t, len(frames), fps) for t in tracks) if m]
    out["tracks"] = tm
    out["face_note"] = note
    boxes = {}
    fm = face_models()
    if fm is not None:
        for i, f in enumerate(frames):
            boxes[i] = [tuple(float(v) for v in d[:4]) for d in fm.faces(f)]
    out["camera"] = camera_motion(frames, boxes, fps)
    if j4 and t0 == 0 and dur is None:
        try:
            import motion_judder as MJ
            m, _ = MJ.analyze(path)
            out["J4"] = m.get("J4")
            out["J4_z"] = m.get("J4_z")
        except Exception as e:  # noqa: BLE001
            out["J4_err"] = str(e)[:120]
    VIO.write_json(cf, out)
    return out


def clip_summary(a: dict) -> dict:
    """一条片 → 表演 / 运镜摘要：多条脸轨迹取平均（每个人都要活，不只主角）"""
    s = {}
    tr = a.get("tracks") or []
    for k in ("expr_std", "expr_rng", "brow_rng", "lm_nonrigid", "head_std", "blink_pm", "gaze_shift_ps", "cam_gaze", "face_h_med"):
        v = [t[k] for t in tr if t.get(k) is not None]
        s[k] = round(float(np.mean(v)), 4) if v else None
    s["faces"] = len(tr)
    cam = a.get("camera") or {}
    for k in ("cam_speed_med", "cam_moving_frac", "cam_path_ps"):
        s[k] = cam.get(k)
    s["J4"] = a.get("J4")
    return s


if __name__ == "__main__":
    for p in sys.argv[1:]:
        r = analyze(Path(p))
        print(json.dumps({"path": p, **clip_summary(r)}, ensure_ascii=False))
