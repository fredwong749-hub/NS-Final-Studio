#!/usr/bin/env python3
"""IMGGEN 第二轮（2026-10-31）：坏手 / 多肢的最简自动筛查——只标“可疑”，不判不合格（K-REV-123）。

在出图机器上跑（自己的 /root/work/fredw/venv_hand，mediapipe Tasks API + /root/work/fredw/mp_models 的
hand_landmarker / pose_landmarker_full），只测像素，不看内容：
- 手数：检测到的手 > 2 × 人数（人数 = max(姿态人数, 脸数, 1)）→ 多手可疑
- 手型：每只手 21 个关键点，手指链长 / 手掌长（腕→中指根）超出 [0.3, 3.0]，或相邻两指指尖几乎重合 → 手型可疑
- 肢体：姿态人数 > 脸数 + 1（多出来的身体），或某人左右前臂 / 上臂长度比 > 2.2 → 肢体可疑

输入 stdin：{"items": [{"id", "path", "faces": n}]}；输出 stdout 一行 JSON：{id: {"hands", "poses", "flags": [...]}}
"""
from __future__ import annotations

import json
import math
import sys

M = __import__("os").environ.get("NS_MP_MODELS", "/root/work/fredw/mp_models")   # LOCALGPU：笔记本本机打分 = D:\ns_score\models\mediapipe
FINGERS = [(1, 2, 3, 4), (5, 6, 7, 8), (9, 10, 11, 12), (13, 14, 15, 16), (17, 18, 19, 20)]


def d(a, b):
    return math.hypot(a.x - b.x, a.y - b.y)


def load_models():
    """mediapipe 手 / 姿态模型；常驻服务 score_srv.py 只调一次"""
    import mediapipe as mp  # noqa: F401
    from mediapipe.tasks import python as mpt
    from mediapipe.tasks.python import vision as V
    hl = V.HandLandmarker.create_from_options(V.HandLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=f"{M}/hand_landmarker.task"), num_hands=8,
        min_hand_detection_confidence=0.4))
    pl = V.PoseLandmarker.create_from_options(V.PoseLandmarkerOptions(
        base_options=mpt.BaseOptions(model_asset_path=f"{M}/pose_landmarker_full.task"), num_poses=4,
        min_pose_detection_confidence=0.5))
    return hl, pl


def detect(man, models=None):
    import mediapipe as mp
    hl, pl = models or load_models()
    out = {}
    for it in man["items"]:
        try:
            img = mp.Image.create_from_file(it["path"])
        except Exception as e:  # noqa: BLE001
            out[it["id"]] = {"error": str(e)[:100]}
            continue
        hr = hl.detect(img)
        pr = pl.detect(img)
        hands = hr.hand_landmarks or []
        poses = pr.pose_landmarks or []
        faces = int(it.get("faces") or 0)
        people = max(len(poses), faces, 1)
        flags = []
        if len(hands) > 2 * people:
            flags.append(f"多手可疑（{len(hands)} 只手 / {people} 人）")
        for k, h in enumerate(hands):
            palm = d(h[0], h[9]) or 1e-6
            bad = []
            for f in FINGERS:
                ln = sum(d(h[f[i]], h[f[i + 1]]) for i in range(3))
                r = ln / palm
                if r < 0.3 or r > 3.0:          # 5 厘米水晶甲会把指尖点外推，上限放到 3.0
                    bad.append(round(r, 2))
            tips = [h[4], h[8], h[12], h[16], h[20]]
            close = sum(1 for i in range(4) if d(tips[i], tips[i + 1]) < 0.04 * palm)
            if bad or close >= 2:
                flags.append(f"手型可疑（第{k + 1}只手：指长比 {bad or '-'}，指尖重合 {close}）")
        if len(poses) > faces + 1 and faces > 0:
            flags.append(f"多身体可疑（姿态 {len(poses)} / 脸 {faces}）")
        for k, p in enumerate(poses):
            try:
                ua = [d(p[11], p[13]), d(p[12], p[14])]
                fa = [d(p[13], p[15]), d(p[14], p[16])]
                vis = min(p[i].visibility or 0 for i in (11, 12, 13, 14, 15, 16))
                if vis > 0.6 and min(ua + fa) > 0 and max(ua) / min(ua) > 2.2 or vis > 0.6 and min(fa) > 0 and max(fa) / min(fa) > 2.2:
                    flags.append(f"肢体比例可疑（第{k + 1}人 上臂 {ua[0]:.2f}/{ua[1]:.2f} 前臂 {fa[0]:.2f}/{fa[1]:.2f}）")
            except (IndexError, ZeroDivisionError):
                pass
        out[it["id"]] = {"hands": len(hands), "poses": len(poses), "flags": flags}
    return out


def main():
    man = json.load(sys.stdin)
    print(json.dumps(detect(man), ensure_ascii=False))


if __name__ == "__main__":
    main()
