#!/usr/bin/env python3
"""人物一致性客观度量：ArcFace（insightface buffalo_l / w600k_r50）脸向量余弦。

每个视频按 --fps 抽帧（图片算 1 帧），检测所有脸，每张脸对每个角色参考求余弦，
脸归给余弦最高的角色（不靠发色猜人）；输出每镜每角色的 均值 / 中位 / 最低 / p10 / 出镜覆盖率，
以及“镜内漂移”（与本镜第一张同角色脸的余弦）。另存曲线 PNG。

只做技术度量，不判断内容。

用法（gpu36，自己的 venv）：
  /root/work/fredw/venv_idm/bin/python identity_metric.py \
      --ref lin_wan=refs/lin_wan.png --ref gu_chen=refs/gu_chen_sheet.png \
      --out out/baseline  S1=videos/S1.mp4 S2=videos/S2.mp4 frame_S2=img.png

参考可写多次同名（--ref lin_wan=a.png --ref lin_wan=b.png）→ 取归一化平均向量。
参考图里有多张脸（四栏设定图）时，默认取最大的那张；--ref-all-faces 则全部平均。

阈值参考（见 docs/ep02_iter/consistency_research.md）：ArcFace 余弦 ≥0.5 基本可认作同一人，
0.3–0.5 相像，<0.3 多半像另一个人。
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from pathlib import Path

import cv2
import numpy as np

SAME = 0.50
SIMILAR = 0.30


def load_app(det_size: int, providers: list[str], root: str | None = None):
    from insightface.app import FaceAnalysis
    kw = {"root": root} if root else {}
    app = FaceAnalysis(name="buffalo_l", allowed_modules=["detection", "recognition"], providers=providers, **kw)
    app.prepare(ctx_id=0, det_size=(det_size, det_size))
    return app


def faces_of(app, bgr: np.ndarray, min_px: int, min_score: float):
    out = []
    for f in app.get(bgr):
        x1, y1, x2, y2 = f.bbox
        w = x2 - x1
        if w < min_px or f.det_score < min_score:
            continue
        e = f.normed_embedding.astype(np.float32)
        out.append({"bbox": [round(float(v), 1) for v in f.bbox], "w": round(float(w), 1),
                    "score": round(float(f.det_score), 3), "emb": e})
    return out


def ref_embeddings(app, refs: list[str], all_faces: bool, min_px: int):
    groups: dict[str, list[np.ndarray]] = {}
    notes = {}
    for spec in refs:
        name, path = spec.split("=", 1)
        img = cv2.imread(path)
        if img is None:
            sys.exit(f"参考图读不到：{path}")
        fs = faces_of(app, img, min_px=min(min_px, 40), min_score=0.5)
        if not fs:
            # 小图上检测失败时放大再试
            big = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
            fs = faces_of(app, big, min_px=40, min_score=0.5)
        if not fs:
            sys.exit(f"参考图里没检测到脸：{path}")
        fs.sort(key=lambda f: -f["w"])
        use = fs if all_faces else fs[:1]
        groups.setdefault(name, []).extend(f["emb"] for f in use)
        notes.setdefault(name, []).append({"path": path, "faces_found": len(fs), "used": len(use),
                                           "max_face_px": fs[0]["w"]})
    embs = {}
    for k, v in groups.items():
        m = np.mean(v, axis=0)
        embs[k] = m / np.linalg.norm(m)
    return embs, notes


def iter_frames(path: str, fps: float):
    p = Path(path)
    if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp"):
        img = cv2.imread(str(p))
        if img is not None:
            yield 0.0, img
        return
    cap = cv2.VideoCapture(str(p))
    src_fps = cap.get(cv2.CAP_PROP_FPS) or 24.0
    step = max(1, int(round(src_fps / fps)))
    i = 0
    while True:
        ok, fr = cap.read()
        if not ok:
            break
        if i % step == 0:
            yield i / src_fps, fr
        i += 1
    cap.release()


def stats(xs):
    if not xs:
        return None
    a = np.array(xs, dtype=np.float32)
    return {"n": int(a.size), "mean": round(float(a.mean()), 3), "median": round(float(np.median(a)), 3),
            "min": round(float(a.min()), 3), "p10": round(float(np.percentile(a, 10)), 3),
            "max": round(float(a.max()), 3)}


def verdict(med):
    if med is None:
        return "无脸"
    return "同人" if med >= SAME else ("相像" if med >= SIMILAR else "不像")


def plot(curves: dict, dur: float, title: str, out: Path):
    W, H, L, B = 900, 300, 50, 30
    img = np.full((H, W, 3), 255, np.uint8)
    for y in (0.0, SIMILAR, SAME, 1.0):
        py = int(H - B - y * (H - B - 10))
        cv2.line(img, (L, py), (W - 10, py), (200, 200, 200), 1)
        cv2.putText(img, f"{y:.1f}", (5, py + 4), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (90, 90, 90), 1)
    cols = [(200, 80, 30), (30, 120, 220), (40, 160, 40), (150, 40, 150)]
    for ci, (name, pts) in enumerate(curves.items()):
        c = cols[ci % len(cols)]
        prev = None
        for t, v in pts:
            px = int(L + (t / max(dur, 1e-3)) * (W - L - 20))
            py = int(H - B - max(0.0, v) * (H - B - 10))
            cv2.circle(img, (px, py), 2, c, -1)
            if prev and t - prev[0] < 1.01:
                cv2.line(img, prev[1], (px, py), c, 1)
            prev = (t, (px, py))
        cv2.putText(img, name, (L + 10 + ci * 140, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.5, c, 1)
    cv2.putText(img, title[:60], (W - 420, 18), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1)
    cv2.imwrite(str(out), img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--ref", action="append", required=True, help="name=path，可重复")
    ap.add_argument("--ref-all-faces", action="store_true")
    ap.add_argument("--fps", type=float, default=4.0)
    ap.add_argument("--min-face", type=int, default=48, help="脸框宽小于此像素不计")
    ap.add_argument("--min-score", type=float, default=0.6)
    ap.add_argument("--det-size", type=int, default=640)
    ap.add_argument("--assign-min", type=float, default=0.15,
                    help="脸对所有参考的最高余弦低于此值时记为 unknown（路人/认不出）")
    ap.add_argument("--cpu", action="store_true")
    ap.add_argument("--model-root", default=None, help="insightface 模型根目录（含 models/buffalo_l）；默认 ~/.insightface")
    ap.add_argument("--out", required=True)
    ap.add_argument("items", nargs="+", help="label=video_or_image")
    a = ap.parse_args()

    providers = ["CPUExecutionProvider"] if a.cpu else ["CUDAExecutionProvider", "CPUExecutionProvider"]
    app = load_app(a.det_size, providers, a.model_root)
    refs, ref_notes = ref_embeddings(app, a.ref, a.ref_all_faces, a.min_face)
    names = list(refs)
    if len(names) > 1:
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                ref_notes.setdefault("_cross", []).append(
                    {names[i] + "~" + names[j]: round(float(refs[names[i]] @ refs[names[j]]), 3)})
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    report = {"model": "insightface buffalo_l (retinaface det_10g + arcface w600k_r50)",
              "thresholds": {"same": SAME, "similar": SIMILAR}, "fps": a.fps, "min_face": a.min_face,
              "refs": ref_notes, "items": {}}
    rows = []
    for item in a.items:
        label, path = item.split("=", 1)
        per = {n: [] for n in names}
        curves = {n: [] for n in names}
        first_emb: dict[str, np.ndarray] = {}
        drift = {n: [] for n in names}
        unknown = 0
        nframes = 0
        dur = 0.0
        for t, fr in iter_frames(path, a.fps):
            nframes += 1
            dur = t
            for f in faces_of(app, fr, a.min_face, a.min_score):
                sims = {n: float(f["emb"] @ refs[n]) for n in names}
                best = max(sims, key=sims.get)
                if sims[best] < a.assign_min:
                    unknown += 1
                    continue
                per[best].append(sims[best])
                curves[best].append((t, sims[best]))
                if best not in first_emb:
                    first_emb[best] = f["emb"]
                drift[best].append(float(f["emb"] @ first_emb[best]))
                rows.append([label, round(t, 3), best, round(sims[best], 4), f["w"], f["score"]]
                            + [round(sims[n], 4) for n in names])
        res = {"path": path, "frames_sampled": nframes, "unknown_faces": unknown, "chars": {}}
        for n in names:
            s = stats(per[n])
            res["chars"][n] = {"vs_ref": s, "verdict": verdict(s["median"] if s else None),
                               "coverage": round(len(set(t for t, _ in curves[n])) / max(nframes, 1), 3),
                               "self_drift_min": round(min(drift[n]), 3) if drift[n] else None}
        report["items"][label] = res
        if nframes > 1:
            plot(curves, dur, f"{label}", out / f"curve_{label}.png")
        print(label, json.dumps({n: (res["chars"][n]["vs_ref"] or {}).get("median") for n in names}), flush=True)
    with open(out / "frames.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["item", "t", "assigned", "cos", "face_px", "det_score"] + [f"cos_{n}" for n in names])
        w.writerows(rows)
    (out / "identity.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    # 简表
    lines = ["| 项 | " + " | ".join(f"{n} 均值/中位/最低（覆盖）" for n in names) + " |",
             "|---|" + "---|" * len(names)]
    for label, res in report["items"].items():
        cells = []
        for n in names:
            c = res["chars"][n]
            s = c["vs_ref"]
            cells.append("—" if not s else f"{s['mean']}/{s['median']}/{s['min']}（{c['coverage']:.0%}）{c['verdict']}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    (out / "summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
