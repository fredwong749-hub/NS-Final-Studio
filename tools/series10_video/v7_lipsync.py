"""VIDEO10 · GEN_CONTRACT V7（口型）检测器——insightface buffalo_l（检测 + 识别 + 106 点）+ 音频 RMS（服务器 venv_idm，CPU）。

服务器上没有 SyncNet 权重；用“嘴部开合 vs 声音包络”的相关（官方 rubric ⑥：嘴部相关 ≥0.3，K-REN acceptance.lipsync_corr_min）。
- 嘴部开合 = 内唇间距（106 点里 62 上内唇中点、60 下内唇中点，实测于 ep01-S5 首帧）/ 脸框高，逐帧（24 fps）；
  多人时按说话人身份参考（脸部裁切）挑最像的那张脸。
- 声音包络 = 片子音轨 16 kHz 单声道，每帧（1/24 s）RMS（dB），减去中位、截到 ≥0。
- 有画内对白（说话人在画、不是画外）：两条序列各做 3 帧平滑，在 ±3 帧（±0.125 s）滑动取最大 Pearson；
  ≥ corr_min 通过；另记“有声段张嘴占比”。
- 无画内对白但有独白 / 画外音（项目方定：“嘴唇闭着”）：张嘴帧（内唇间距 / 脸高 ≥ open_thr）占比 ≤ closed_max 通过。
- 无对白、无独白：不适用。
- 说话人的脸在 < 30% 的帧里检出 → “未测”（不是通过）。

    venv_idm/bin/python v7_lipsync.py <video.mp4> '<json: {"dialogue": [...], "voiceover": {...}|null, "refs": {角色: 图}, "visible": [...]}>'
"""
from __future__ import annotations

import os as _os   # K-OPS-V13（VQAGATE 11-02 00:3x）：服务器打分 / 检测脚本限线程——96 核机上 onnxruntime / OpenMP 默认吃满全部核心（gpu33 7432% CPU）
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")
NS_THREADS = int(_os.environ.get("NS_SCORE_THREADS", "4"))

import json
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
# 标定（11-01，10 条）：正对镜头的对白镜 corr 0.33–0.80；远景小脸（ep10-S5 全景，脸高 <90 px）开合噪声大 → 小脸帧记“没检出”
TH = {"corr_min": 0.30, "open_thr": 0.035, "closed_max": 0.25, "seen_min": 0.30, "max_lag": 3, "min_face_px": 90,
      # 台词段第二判据（总调度 11-02，K-REV-V16）：张嘴帧 = 内唇间距 / 脸高 ≥ win_open_thr；阈值由标定集定（GATE_CALIBRATION §13）
      # 标定（GATE_CALIBRATION §13，总调度人工标签：S4ffb s102 / S4calm s101 过，r18 三条不过）：幅度 p90−p10 过 0.004 是共同前提
      # （r18 s103 嘴几乎不动但相关 0.593，单看相关会误过），再“相关 ≥0.30 或 张嘴帧（≥0.010）占比 ≥0.30”满足其一
      "win_open_thr": 0.010, "win_open_frac_min": 0.30, "win_amp_min": 0.004}
UP, LO = 62, 60          # 106 点：上内唇中点 / 下内唇中点（ep01-S5 首帧实测：71 上外唇、62 上内唇、60 下内唇、53 下外唇）


def _cap_onnxruntime():
    """insightface 建 InferenceSession 时不传 SessionOptions → ORT 默认 intra-op 线程 = 全部核心。这里给默认会话加上线程上限"""
    import onnxruntime as ort
    if getattr(ort, "_ns_capped", False):
        return
    _orig = ort.InferenceSession.__init__

    def _init(self, path_or_bytes, sess_options=None, *a, **kw):
        if sess_options is None:
            sess_options = ort.SessionOptions()
            sess_options.intra_op_num_threads = NS_THREADS
            sess_options.inter_op_num_threads = 1
        return _orig(self, path_or_bytes, sess_options, *a, **kw)
    ort.InferenceSession.__init__ = _init
    ort._ns_capped = True


def app():
    _cap_onnxruntime()
    cv2.setNumThreads(NS_THREADS)
    from insightface.app import FaceAnalysis
    a = FaceAnalysis(name="buffalo_l", root="/root/work/fredw/idm_models",
                     allowed_modules=["detection", "recognition", "landmark_2d_106"], providers=["CPUExecutionProvider"])
    a.prepare(ctx_id=-1, det_size=(640, 640))
    return a


def audio_env(path: str, n: int, fps: float = 24.0) -> np.ndarray:
    ff = "ffmpeg"
    with tempfile.TemporaryDirectory() as td:
        w = Path(td) / "a.wav"
        subprocess.run([ff, "-v", "error", "-y", "-i", path, "-vn", "-ac", "1", "-ar", "16000", str(w)], check=True)
        with wave.open(str(w)) as wf:
            a = np.frombuffer(wf.readframes(wf.getnframes()), np.int16).astype(np.float32) / 32768.0
    hop = int(16000 / fps)
    env = np.array([np.sqrt(np.mean(a[k * hop:(k + 1) * hop] ** 2) + 1e-10) for k in range(n)])
    db = 20 * np.log10(env + 1e-6)
    return np.clip(db - np.median(db), 0, None)


def smooth(x, k=3):
    return np.convolve(x, np.ones(k) / k, mode="same")


def best_corr(x, y, lag):
    best = -1.0
    for d in range(-lag, lag + 1):
        a, b = (x[d:], y[:len(y) - d]) if d >= 0 else (x[:d], y[-d:])
        m = ~(np.isnan(a) | np.isnan(b))
        if m.sum() > 12 and np.std(a[m]) > 1e-6 and np.std(b[m]) > 1e-6:
            best = max(best, float(np.corrcoef(a[m], b[m])[0, 1]))
    return best


def best_corr_masked(x, y, lag, mask):
    """只在台词时段（mask=True 的帧）算相关，±lag 帧滑动取最大（VQAGATE 11-02：整轨 RMS 混着脚步 / 配乐，2–5 字短台词被淹没）"""
    idx = np.flatnonzero(mask)
    best = -1.0
    for d in range(-lag, lag + 1):
        j = idx + d
        ok = (j >= 0) & (j < len(y))
        a, b = x[idx[ok]], y[j[ok]]
        if len(a) > 12 and np.std(a) > 1e-6 and np.std(b) > 1e-6:
            best = max(best, float(np.corrcoef(a, b)[0, 1]))
    return best


def window_mask(windows, n, fps=24.0):
    m = np.zeros(n, bool)
    for t0, t1 in windows or []:
        m[max(0, int(t0 * fps)):min(n, int(np.ceil(t1 * fps)))] = True
    return m


def main(argv):
    path, meta = argv[0], json.loads(argv[1]) if len(argv) > 1 else {}
    visible = set(meta.get("visible") or [])
    on = [d for d in meta.get("dialogue") or [] if not d.get("off") and d.get("speaker") in visible]
    vo = meta.get("voiceover")
    off = [d for d in meta.get("dialogue") or [] if d.get("off") or d.get("speaker") not in visible]
    if not on and not vo and not off:
        print(json.dumps({"v7": {"status": "不适用", "why": "本镜无对白、无独白"}}, ensure_ascii=False))
        return
    mode = "sync" if on else "closed"
    who = on[0]["speaker"] if on else None
    a = app()
    ref = None
    rp = (meta.get("refs") or {}).get(who) if who else None
    if rp:
        img = cv2.imread(str(ROOT / rp))
        if img is not None:
            big = cv2.copyMakeBorder(img, 80, 80, 80, 80, cv2.BORDER_CONSTANT, value=(128, 128, 128))
            fs = a.get(big)
            if fs:
                ref = max(fs, key=lambda f: (f.bbox[2] - f.bbox[0]) * (f.bbox[3] - f.bbox[1])).normed_embedding
    cap = cv2.VideoCapture(path)
    ap = []
    while True:
        ok, f = cap.read()
        if not ok:
            break
        fs = a.get(f)
        if not fs:
            ap.append(np.nan)
            continue
        if ref is not None:   # 说话人的脸必须认得出（余弦 ≥ 0.20），认不出（背身 / 出画 / 别人）这帧记“没检出”
            fc = max(fs, key=lambda x: float(x.normed_embedding @ ref))
            if float(fc.normed_embedding @ ref) < 0.20:
                ap.append(np.nan)
                continue
        else:
            fc = max(fs, key=lambda x: (x.bbox[2] - x.bbox[0]) * (x.bbox[3] - x.bbox[1]))
        L = fc.landmark_2d_106
        fh = float(fc.bbox[3] - fc.bbox[1]) + 1e-6
        if fh < TH["min_face_px"]:
            ap.append(np.nan)
            continue
        ap.append(max(0.0, float(L[LO][1] - L[UP][1])) / fh)
    ap = np.array(ap, np.float32)
    n = len(ap)
    seen = float(np.mean(~np.isnan(ap))) if n else 0.0
    m = {"mode": mode, "speaker": who, "frames": n, "seen": round(seen, 3),
         "aperture_med": round(float(np.nanmedian(ap)), 4) if seen else None,
         "aperture_p90": round(float(np.nanpercentile(ap, 90)), 4) if seen else None}
    if seen < TH["seen_min"]:
        print(json.dumps({"v7": {"status": "未测", "why": f"说话人 / 主角的脸只在 {seen:.0%} 的帧里检出", **m, "th": TH}},
                         ensure_ascii=False))
        return
    open_frac = float(np.nanmean(ap >= TH["open_thr"]))
    m["open_frac"] = round(open_frac, 3)
    if mode == "closed":
        ok = open_frac <= TH["closed_max"]
        st, why = ("通过", "") if ok else ("不通过", f"独白 / 画外音镜头张嘴帧占 {open_frac:.0%}（项目方：嘴唇闭着）")
    else:
        env = audio_env(path, n)
        xs, ys = smooth(np.nan_to_num(ap, nan=np.nanmedian(ap))), smooth(env)
        c_full = best_corr(xs, ys, TH["max_lag"])
        c = c_full
        wins = meta.get("dialogue_windows") or []
        wm = window_mask(wins, n)
        if wins and wm.sum() > 12:                     # 有台词时间码：只在台词时段（时间码 ±0.5 s）算，整轨的只记录
            c = best_corr_masked(xs, ys, TH["max_lag"], wm)
            wa = ap[wm]
            wa = wa[~np.isnan(wa)]
            if len(wa):                                  # 总调度 11-02：台词段张嘴帧占比 + 开合幅度（侧脸小嘴时相关系数不稳）
                amp = float(np.percentile(wa, 90) - np.percentile(wa, 10))
                m.update(win_amp=round(amp, 4), win_open_frac=round(float(np.mean(wa >= TH["win_open_thr"])), 3),
                         win_p90=round(float(np.percentile(wa, 90)), 4))
                if meta.get("debug_aperture"):
                    m["win_aperture"] = [round(float(x), 4) for x in wa]
            m.update(corr_scope="台词时段", window_source=meta.get("window_source") or "stamps", window_frames=int(wm.sum()),
                     windows=[[round(a, 2), round(b, 2)] for a, b in wins])
        else:
            m.update(corr_scope="整轨" + ("（台词时段帧太少）" if wins else "（没有台词时间码）"))
        voiced = env > 3.0
        m.update(corr=round(c, 3), corr_full=round(c_full, 3), voiced_frac=round(float(voiced.mean()), 3),
                 open_in_voiced=round(float(np.nanmean(ap[voiced] >= TH["open_thr"])), 3) if voiced.any() else None)
        ok = c >= TH["corr_min"]
        if m.get("corr_scope") == "台词时段" and m.get("win_amp") is not None:   # K-REV-V16：台词段口径
            moving = m["win_amp"] >= TH["win_amp_min"]
            by_open = (m.get("win_open_frac") or 0) >= TH["win_open_frac_min"]
            ok = moving and (c >= TH["corr_min"] or by_open)
            m["pass_by"] = ("相关" if c >= TH["corr_min"] else "张嘴占比") if ok else None
        st, why = ("通过", "") if ok else ("不通过", f"嘴部开合与声音相关 {c:.2f} < {TH['corr_min']}，台词段张嘴占比 "
                                                   f"{m.get('win_open_frac')} / 幅度 {m.get('win_amp')} 也没过线")
    print(json.dumps({"v7": {"status": st, "why": why, **m, "th": TH}}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
