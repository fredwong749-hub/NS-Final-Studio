"""视频手形检测（抽帧）（VQAGATE 11-02 20:1x，总调度续派第 ③ 项）。

视频里的手（多手、手指数 / 长度比例异常）原来只有 V6（score_clip 的 MediaPipe HandLandmarker，每手固定 21 点，数不出六指）。
这里改用图片验收同一套检测器（tools/vqa/anomaly.py：hand_yolov9c 手框 + DWPose 133 点手指骨长），对片子均匀抽帧逐帧判：
  - 抽 N 帧（默认 8，跳过首尾 5%，避开淡入淡出），存成 jpg 送 anomaly.measure（常驻服务 http 地址优先，否则 gpu36 rssh；
    检测卡按主机选，坏卡绝不用）；
  - 每帧 anomaly.judge 取手相关的非低置信命中（extra_hands / finger_ratio(conf≠low) / hands 归属）；
  - ≥ min_hits 帧（默认 2）命中同一类 → fail；1 帧 → 记录（单帧误检多，不拦）；分母只算检出了手的帧；
  - 测成的帧 < 3 → untested（不当通过）；测成了但都没检出手 → na。
图片 / 帧只进本地或自有服务器模型（K-REV-V01）。

    python tools/vqa/video_hands.py <clip.mp4> <epNN-SN> [--host http://10.0.0.36:8893] [--frames 8]
"""
from __future__ import annotations

import json
import sys
import tempfile
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
HAND_CODES = ("extra_hands", "finger_ratio", "hand_dup")
MIN_TESTED = 3          # 至少测成这么多帧才算数（OVERSIGHT-F 第 6 轮）


def sample_frames(clip: Path, n: int = 8, out_dir: Path | None = None) -> list[Path]:
    """均匀抽 n 帧（跳过首尾 5%）→ jpg 路径列表；读不了视频 → []"""
    import cv2
    cap = cv2.VideoCapture(str(clip))
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    if total <= 0:
        cap.release()
        return []
    out_dir = Path(out_dir or tempfile.mkdtemp(prefix="vqagate_vh_"))
    out_dir.mkdir(parents=True, exist_ok=True)
    lo, hi = int(total * 0.05), max(int(total * 0.95) - 1, int(total * 0.05))
    idxs = sorted({lo + round(i * (hi - lo) / max(1, n - 1)) for i in range(n)})
    paths = []
    for i in idxs:
        cap.set(cv2.CAP_PROP_POS_FRAMES, i)
        ok, fr = cap.read()
        if ok:
            p = out_dir / f"{clip.stem}_f{i:05d}.jpg"
            cv2.imwrite(str(p), fr, [cv2.IMWRITE_JPEG_QUALITY, 92])
            paths.append(p)
    cap.release()
    return paths


def judge_frames(per_frame: list[dict], min_hits: int = 2) -> dict:
    """per_frame = [{"frame", "defects": [{code, conf, detail}], "hands": n, "error"?}] → {status, hits, reasons, tested}（纯函数）"""
    ok = [f for f in per_frame if not f.get("error")]
    if len(ok) < MIN_TESTED:
        # OVERSIGHT-F 第 6 轮 P2：测成的帧太少（< 3）不算数 = untested，不当通过
        return {"status": "untested", "tested": len(ok), "hits": {}, "reasons": [f"只测成 {len(ok)} 帧（< {MIN_TESTED}），手形判不了"]}
    tested = [f for f in ok if (f.get("hands") or 0) > 0]          # 分母只算检出了手的帧
    if not tested:
        return {"status": "na", "tested": 0, "hits": {}, "reasons": [f"{len(ok)} 帧都没检出手"]}
    cnt: Counter = Counter()
    first: dict = {}
    for f in tested:
        codes = {d["code"] for d in f.get("defects") or [] if d.get("code") in HAND_CODES and d.get("conf") != "low"}
        for c in codes:
            cnt[c] += 1
            first.setdefault(c, f"{f['frame']}：" + next(d["detail"] for d in f["defects"] if d["code"] == c)[:80])
    bad = {c: n for c, n in cnt.items() if n >= min_hits}
    return {"status": "fail" if bad else "pass", "tested": len(tested), "hits": dict(cnt),
            "reasons": [f"{c} {n}/{len(tested)} 帧（例 {first[c]}）" for c, n in bad.items()],
            "noted": [f"{c} 只有 {n} 帧（单帧不拦）" for c, n in cnt.items() if n < min_hits]}


def check_clip(clip, sid: str, host: str | None = None, n: int = 8, min_hits: int = 2) -> dict:
    from tools.vqa import anomaly as AN
    frames = sample_frames(Path(clip), n)
    if not frames:
        return {"status": "untested", "tested": 0, "hits": {}, "reasons": ["视频读不了 / 没有帧"]}
    try:
        cast = AN.shot_cast(sid)
    except KeyError:                   # 镜头不在当前剧本里（例：主剧已切 V2，拿 V1 片子来测）：手形判定不依赖 cast，照判
        cast = None
    try:
        feats = AN.measure({p.name: p for p in frames}, host or "gpu36")
    except Exception as e:  # noqa: BLE001 — 检测器没跑成 = untested，不当通过
        return {"status": "untested", "tested": 0, "hits": {}, "reasons": [f"检测器没跑成：{type(e).__name__}: {e}"[:200]]}
    rows = []
    for p in frames:
        f = feats.get(p.name) or {}
        if not f or f.get("error"):
            rows.append({"frame": p.name, "error": f.get("error") or "无结果"})
            continue
        r = AN.judge(f, cast)
        rows.append({"frame": p.name, "defects": r["defects"], "hands": (r.get("metrics") or {}).get("hands")})
    return {**judge_frames(rows, min_hits), "frames": [r["frame"] for r in rows]}


def main(argv: list[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("clip")
    ap.add_argument("sid")
    ap.add_argument("--host", default=None)
    ap.add_argument("--frames", type=int, default=8)
    a = ap.parse_args(argv)
    print(json.dumps(check_clip(a.clip, a.sid, a.host, a.frames), ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
