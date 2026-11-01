"""VIDEO-RCA：4 帧一顿量化（同 motion_judder 口径 + 2 帧相位）。逐条输出 J2 / J4 / z / 相位均值 / 停帧 stall / jerk；可对比去抖前后。
    python judder.py a.mp4 [b.mp4 ...]   → 每行一个 JSON
"""
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
REPO = Path("/root/work/fredw/video10_srv") if Path("/root/work/fredw/video10_srv").exists() else ROOT
sys.path.insert(0, str(REPO / "tools"))
import motion_judder as MJ  # noqa: E402


def one(p):
    m, ser = MJ.analyze(Path(p))
    g = MJ.frames_gray(Path(p)).astype(np.float32)
    d = np.abs(np.diff(g, axis=0)).mean(axis=(1, 2))
    ph4 = [float(d[(np.arange(len(d)) + 1) % 4 == k].mean()) for k in range(4)]
    j2, _, _ = MJ.phase_ratio(d, 2)
    z2 = MJ.phase_z(d, 2)
    return {"file": Path(p).name, "J4": round(m["J4"], 3), "J4_z": round(m["J4_z"], 2), "J2": round(j2, 3), "J2_z": round(z2, 2),
            "phase4": [round(x / np.mean(ph4), 3) for x in ph4], "stall": m.get("stall"), "jerk": m.get("jerk"),
            "pace": m.get("pace_px_per_frame")}


if __name__ == "__main__":
    for p in sys.argv[1:]:
        print(json.dumps(one(p), ensure_ascii=False), flush=True)
