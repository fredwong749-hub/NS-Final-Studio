"""VIDEO-RCA：景别退档出在首帧还是出在视频？对每条现行版：首帧（中心裁到 768×1344）最大脸高 / 画高 vs 视频 face_h_med。
同 score_clip 的尺子（YuNet，score≥0.5，脸高 ≥30 px，K-REN-122 档位）。
    .venv/Scripts/python.exe tools/video_rca/ff_size.py [--all]
"""
import json, sys
from pathlib import Path
import cv2, numpy as np
ROOT = Path(__file__).resolve().parents[2]
for p in ("tools", "tools/ep02_director", "packages/qc", "tools/video_rca"):
    sys.path.insert(0, str(ROOT / p))
import review as R
import rates as RT

def ff_h(faces, path):
    bgr = cv2.imread(str(ROOT / path))
    h, w = bgr.shape[:2]; tw = h * 768 / 1344
    if w > tw:
        x0 = int((w - tw) / 2); bgr = bgr[:, x0:x0 + int(tw)]
    else:
        th = w * 1344 / 768; y0 = int((h - th) / 2); bgr = bgr[y0:y0 + int(th)]
    bgr = cv2.resize(bgr, (768, 1344), interpolation=cv2.INTER_LANCZOS4)
    rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
    fs = [f for f in faces.detect(rgb, small=True) if float(f[3]) >= 30]
    return max(float(f[3]) for f in fs) / 1344 if fs else None

def main():
    faces = R.Faces(); rows = []
    sel = RT.load_renders() if "--all" in sys.argv else [r for r in RT.load_renders() if r["current"]]
    cache = {}
    for r in sel:
        s = r["score"]; want = RT.SIZE_IDX.get(s.get("size_wanted") or ""); vh = s.get("face_h_med")
        ff = r.get("first_frame")
        if want is None or vh is None or not ff or not (ROOT / ff).exists():
            continue
        if ff not in cache: cache[ff] = ff_h(faces, ff)
        fh = cache[ff]
        if fh is None: continue
        rows.append({"clip": f"{r['shot']}__{r['variant']}", "want": want, "ff": RT.size_class(fh), "vid": RT.size_class(vh),
                     "ff_h": round(fh, 3), "vid_h": round(vh, 3)})
    n = len(rows)
    ff_bad = sum(x["ff"] - x["want"] >= 1 for x in rows)
    vid_bad = sum(x["vid"] - x["want"] >= 1 for x in rows)
    zoom_out = sum(x["vid"] - x["ff"] >= 1 for x in rows)
    ratio = [x["vid_h"] / x["ff_h"] for x in rows]
    out = {"n": n, "首帧已退档(比要求远≥1档)": ff_bad, "视频退档": vid_bad, "视频比首帧再远≥1档": zoom_out,
           "视频脸高/首帧脸高 中位": round(float(np.median(ratio)), 3) if ratio else None,
           "视频退档里首帧本就退档": sum(1 for x in rows if x["vid"] - x["want"] >= 1 and x["ff"] - x["want"] >= 1)}
    print(json.dumps(out, ensure_ascii=False))
    Path(ROOT / "data/ab/video_rca/ff_size.json").write_text(json.dumps({"summary": out, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
main()
