"""
V2（2026-10-31，ARCH 风险：新提示词 `At 00:SS.mmm` 分拍可能被 H3 当切镜标记而中途硬切）：
对方案 A 回来的每条版本跑 ns_render.motion_qc 的跳切检测 + HSV 直方图硬切（同 lab_score：Bhattacharyya > 0.35 且帧差 > max(8, 6×中位)），
按“旧提示词 / 新提示词”分组汇总，并对照提示词里的分拍时间码看切点是否落在时间码附近（±0.5 s）。

用法：python tools/ep02_iter/cut_check.py [--out data/ab/v2_iter/cut_check.json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "render_router"))
from ns_render import motion_qc as MQ  # noqa: E402

STAMP = re.compile(r"At (\d{2}):(\d{2}(?:\.\d+)?)")


def hist_cuts(path: Path, fps: float) -> list[float]:
    import cv2
    cap = cv2.VideoCapture(str(path))
    prev_h, prev_g, out, diffs, rows = None, None, [], [], []
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        sm = cv2.resize(fr, (96, 168))
        hsv = cv2.cvtColor(sm, cv2.COLOR_BGR2HSV)
        h = cv2.calcHist([hsv], [0, 1], None, [32, 32], [0, 180, 0, 256])
        cv2.normalize(h, h)
        g = cv2.cvtColor(sm, cv2.COLOR_BGR2GRAY).astype(np.float32)
        if prev_h is not None:
            rows.append((i, cv2.compareHist(prev_h, h, cv2.HISTCMP_BHATTACHARYYA), float(np.abs(g - prev_g).mean())))
        prev_h, prev_g = h, g
        i += 1
    cap.release()
    if not rows:
        return []
    med = float(np.median([r[2] for r in rows]))
    return [round(k / fps, 2) for k, b, d in rows if b > 0.35 and d > max(8.0, 6 * med)]


def stamps_of(plan_path: Path | None) -> list[float]:
    if not plan_path or not plan_path.exists():
        return []
    t = json.loads(plan_path.read_text(encoding="utf-8")).get("prompt", {}).get("text", "")
    return [int(m.group(1)) * 60 + float(m.group(2)) for m in STAMP.finditer(t)]


def items() -> list[dict]:
    """方案 A 的版本 = takes.json 里带 params.recipe.plan_hash 的视频版本（loop / fanout 都经 :8800 recipe 接入点）"""
    out = []
    plan_dirs = [ROOT / "data/iterate_loop/ep02_v2/plans", ROOT / "data/ab/v2_iter/fanout/plans"]
    for tj in sorted((ROOT / "data/renders/ep02").glob("S*/takes.json")):
        for t in json.loads(tj.read_text(encoding="utf-8")).get("takes") or []:
            ph = ((t.get("params") or {}).get("recipe") or {}).get("plan_hash")
            if t.get("stage") != "video" or not ph or not t.get("file"):
                continue
            plan = next((d / f"{ph[:16]}.json" for d in plan_dirs if (d / f"{ph[:16]}.json").exists()), None)
            out.append({"id": f"{tj.parent.name}_v{t['n']}", "file": str(ROOT / "data" / t["file"]), "plan": plan,
                        "qc_labels": ((t.get("qc") or {}).get("motion") or {}).get("labels")})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(ROOT / "data/ab/v2_iter/cut_check.json"))
    a = ap.parse_args()
    rows = []
    for it in items():
        f = Path(it["file"])
        if not f.exists():
            continue
        fps = MQ._probe_fps(f)
        mq = MQ.video_motion(f)
        hc = hist_cuts(f, fps)
        st = stamps_of(it["plan"])
        near = [c for c in hc if any(abs(c - s) <= 0.5 for s in st)]
        rows.append({"id": it["id"], "file": str(f), "group": "new" if st else "old",
                     "stamps": st, "hist_cuts_s": hc, "cuts_near_stamps": near,
                     "motion_qc_cuts_s": (mq.get("metrics") or mq).get("cut_s"), "verdict": mq.get("verdict"),
                     "labels": mq.get("labels")})
        print(it["id"], rows[-1]["group"], "hist", hc, "near", near, "mq", rows[-1]["motion_qc_cuts_s"], mq.get("labels"))
    Path(a.out).write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
