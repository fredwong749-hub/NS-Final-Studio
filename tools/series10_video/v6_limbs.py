"""VIDEO10 · GEN_CONTRACT V6（多肢 / 缺肢 / 手指）检测器——MediaPipe HandLandmarker + PoseLandmarker（服务器 venv_hand，CPU）。

能测的（像素级，不看内容）：
- 每帧手的个数、左右手标签、人体骨架个数（每 2 帧采一次，12 fps）；
- 多手：手数 > 2 × 人数（人数 = 剧本在画人数与骨架数的较大者）的帧占比；
- 同侧重复：只有 1 人时同一帧出现两只同侧手（两只“Left”）的帧占比；
- 闪变：手数在相邻采样帧之间跳变 ≥2，或 a→b→a 单帧闪现（手 / 骨架凭空出现又消失）的次数；
- 手指：MediaPipe 每只手固定输出 21 点、不能数“六指”；改测手指骨长比例异常（某根手指总长 < 手掌宽 0.25 或 > 2.5 倍）的手占比。
测不到：没有手、也没有骨架入画（脸部特写等）的帧占比 ≥ 80% → V6 记“未测”（不是通过）。

    venv_hand/bin/python v6_limbs.py <video.mp4> '<json: {"people": n}>'   → stdout 最后一行 JSON
阈值（标定见 knowledge K-REV-304，calibrate 用 tools/series10_video/calibrate_v67.py 的统计）在 TH 里。
"""
from __future__ import annotations

import os as _os   # K-OPS-V13（VQAGATE 11-02 00:3x）：服务器打分 / 检测脚本限线程——96 核机上 onnxruntime / OpenMP 默认吃满全部核心（gpu33 7432% CPU）
for _k in ("OMP_NUM_THREADS", "MKL_NUM_THREADS", "OPENBLAS_NUM_THREADS", "NUMEXPR_NUM_THREADS"):
    _os.environ[_k] = _os.environ.get("NS_SCORE_THREADS", "4")
NS_THREADS = int(_os.environ.get("NS_SCORE_THREADS", "4"))

import json
from pathlib import Path
import sys

import cv2
cv2.setNumThreads(NS_THREADS)
import numpy as np

HAND_TASK = "/root/work/fredw/mp_models/hand_landmarker.task"
POSE_TASK = "/root/work/fredw/mp_models/pose_landmarker_full.task"
# 标定（11-01，10 条已出片、印样看无多肢）：extra_hand 0–0.031、dup_side 0–0.034、flicker 0–8（双人 / 全身遮挡多）、
# bad_finger 0–0.80（背身 / 远景手小时 2D 骨长投影不可靠）→ 手指比例只记录不判；其余阈值放在观测最大值之上（只有负例，无正例）
TH = {"extra_hand_frac": 0.05, "dup_side_frac": 0.15, "flicker_max": 10, "bad_finger_frac": None, "untested_frac": 0.80}
# VQAGATE 11-01（总调度：空阈值按 K-REV-Q05 算缺陷；V6 阈值落定前多肢一律判不过）：阈值以 config/gen_contract.json
# video_thresholds.V6 为准（出处与标定写在那里），读不到才用上面的默认值
try:
    TH.update({k: v for k, v in json.loads((Path(__file__).resolve().parents[2] / "config" / "gen_contract.json").read_text(
        encoding="utf-8")).get("video_thresholds", {}).get("V6", {}).items() if not k.startswith("_") and k != "src"})
except Exception:  # noqa: BLE001
    pass
FINGERS = [(1, 4), (5, 8), (9, 12), (13, 16), (17, 20)]   # MediaPipe 手指根 → 指尖


def finger_ok(lm) -> bool:
    p = np.array([[q.x, q.y] for q in lm])
    palm = np.linalg.norm(p[5] - p[17]) + 1e-6
    for a, b in FINGERS:
        seg = sum(np.linalg.norm(p[k + 1] - p[k]) for k in range(a, b))
        if seg < 0.25 * palm or seg > 2.5 * palm:
            return False
    return True


def main(argv):
    import mediapipe as mp
    from mediapipe.tasks.python import BaseOptions, vision
    path, meta = argv[0], json.loads(argv[1]) if len(argv) > 1 else {}
    hl = vision.HandLandmarker.create_from_options(vision.HandLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=HAND_TASK), running_mode=vision.RunningMode.VIDEO, num_hands=6,
        min_hand_detection_confidence=0.5))
    pl = vision.PoseLandmarker.create_from_options(vision.PoseLandmarkerOptions(
        base_options=BaseOptions(model_asset_path=POSE_TASK), running_mode=vision.RunningMode.VIDEO, num_poses=4))
    cap = cv2.VideoCapture(path)
    rows, i = [], 0
    while True:
        ok, f = cap.read()
        if not ok:
            break
        if i % 2 == 0:
            im = mp.Image(image_format=mp.ImageFormat.SRGB, data=cv2.cvtColor(f, cv2.COLOR_BGR2RGB))
            ts = int(i * 1000 / 24)
            r, q = hl.detect_for_video(im, ts), pl.detect_for_video(im, ts)
            sides = [c[0].category_name for c in r.handedness]
            rows.append({"f": i, "hands": len(r.hand_landmarks), "sides": sides, "poses": len(q.pose_landmarks),
                         "bad_fingers": sum(0 if finger_ok(lm) else 1 for lm in r.hand_landmarks)})
        i += 1
    hl.close()
    pl.close()
    n = len(rows)
    if not n:
        print(json.dumps({"v6": {"status": "未测", "why": "读不到帧"}}))
        return
    people = max(int(meta.get("people") or 1), int(np.median([r["poses"] for r in rows]) or 0), 1)
    empty = sum(1 for r in rows if r["hands"] == 0 and r["poses"] == 0) / n
    extra = sum(1 for r in rows if r["hands"] > 2 * people) / n
    dup = sum(1 for r in rows if people == 1 and (r["sides"].count("Left") > 1 or r["sides"].count("Right") > 1)) / n
    hs = [r["hands"] for r in rows]
    ps = [r["poses"] for r in rows]
    flick = sum(1 for k in range(1, n) if abs(hs[k] - hs[k - 1]) >= 2)
    flick += sum(1 for k in range(1, n - 1) if hs[k - 1] == hs[k + 1] != hs[k])
    flick += sum(1 for k in range(1, n - 1) if ps[k - 1] == ps[k + 1] != ps[k])
    nh = sum(hs)
    badf = sum(r["bad_fingers"] for r in rows) / nh if nh else 0.0
    m = {"frames": n, "people": people, "empty_frac": round(empty, 3), "extra_hand_frac": round(extra, 3),
         "dup_side_frac": round(dup, 3), "flicker": flick, "bad_finger_frac": round(badf, 3),
         "hands_max": max(hs), "poses_max": max(ps), "hand_frames": sum(1 for h in hs if h)}
    if empty >= TH["untested_frac"]:
        st, why = "未测", f"{empty:.0%} 的帧没有手也没有身体入画"
    else:
        fails = [k for k, bad in (("多手", extra > TH["extra_hand_frac"]),
                                  ("手数超过人数×2", TH.get("hands_max_per_person") is not None
                                   and max(hs) > TH["hands_max_per_person"] * people),
                                  ("同侧重复手", dup > TH["dup_side_frac"]),
                                  ("手 / 身体闪变", flick > TH["flicker_max"]),
                                  ("手指比例异常", TH["bad_finger_frac"] is not None and badf > TH["bad_finger_frac"])) if bad]
        st, why = ("不通过", "、".join(fails)) if fails else ("通过", "")
    print(json.dumps({"v6": {"status": st, "why": why, **m, "th": TH}}, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv[1:])
