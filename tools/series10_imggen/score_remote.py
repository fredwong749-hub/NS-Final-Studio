#!/usr/bin/env python3
"""IMGGEN（series10_v1）出图自动质检——在 gpu36 自己的 venv_idm 里跑（CPU，不占显卡）。

只测像素，不看内容：
- 人脸：insightface buffalo_l（retinaface + arcface w600k_r50，与 tools/identity_metric.py 同模型同阈值）
  每张脸给 bbox、脸高占画面比例、对每个参考的余弦。
- 文字/水印：rapidocr-onnxruntime，置信度 ≥0.6 且字高 ≥ 画面高 1.2% 的文本框算“有字”。

输入 manifest.json：{"refs": {name: [path,...]}, "items": [{"id":..., "path":..., "ocr": true}]}
输出 stdout 一行 JSON：{"refs": {...}, "items": {id: {...}}}
用法：/root/work/fredw/venv_idm/bin/python score_remote.py manifest.json
"""
from __future__ import annotations

import json
import sys

import cv2
import numpy as np


def main():
    man = json.load(sys.stdin if sys.argv[1] == "-" else open(sys.argv[1], encoding="utf-8"))
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="buffalo_l", root=__import__("os").environ.get("NS_IDM_ROOT", "/root/work/fredw/idm_models"), allowed_modules=["detection", "recognition"],
                       providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    ocr = None

    def faces(img, min_px=24):
        out = []
        for f in app.get(img):
            x1, y1, x2, y2 = [float(v) for v in f.bbox]
            if x2 - x1 < min_px or f.det_score < 0.55:
                continue
            out.append((f, [x1, y1, x2, y2]))
        return out

    refs, notes = {}, {}
    for name, paths in man.get("refs", {}).items():
        es = []
        for p in paths:
            img = cv2.imread(p)
            fs = faces(img) if img is not None else []
            if not fs and img is not None:
                # 总调度 11-02 16:3x（K-REV-V27）：L-122 新身份脸是脸部特写、脸占满画面，retinaface 在 640 检测尺度下一张脸都检不出
                # （refs lin_wan = 0 → 全剧林晚 Q1 失效）。先四周补边让脸缩到画面中部再检，再试放大（小脸参考图的老办法）
                h, w = img.shape[:2]
                pad = int(0.5 * max(h, w))
                fs = faces(cv2.copyMakeBorder(img, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=(255, 255, 255)))
            if not fs and img is not None:
                img2 = cv2.resize(img, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                fs = faces(img2)
            if fs:
                fs.sort(key=lambda t: -(t[1][2] - t[1][0]))
                es.append(fs[0][0].normed_embedding.astype(np.float32))
        if es:
            m = np.mean(es, axis=0)
            refs[name] = m / np.linalg.norm(m)
        notes[name] = len(es)
    cross = {f"{a}~{b}": round(float(refs[a] @ refs[b]), 3) for i, a in enumerate(refs) for b in list(refs)[i + 1:]}
    res = {}
    for it in man["items"]:
        img = cv2.imread(it["path"])
        if img is None:
            res[it["id"]] = {"error": "unreadable"}
            continue
        H, W = img.shape[:2]
        fl = []
        for f, b in faces(img):
            e = f.normed_embedding.astype(np.float32)
            fl.append({"bbox": [round(v, 1) for v in b], "h_ratio": round((b[3] - b[1]) / H, 4),
                       "w_ratio": round((b[2] - b[0]) / W, 4), "det": round(float(f.det_score), 3),
                       "sims": {n: round(float(e @ r), 4) for n, r in refs.items()},
                       "emb": [round(float(v), 5) for v in e]})
        fl.sort(key=lambda d: -d["h_ratio"])
        txt = []
        if it.get("ocr", True):
            if ocr is None:
                from rapidocr_onnxruntime import RapidOCR
                ocr = RapidOCR()
            r, _ = ocr(img)
            for box, s, conf in (r or []):
                ys = [p[1] for p in box]
                hh = (max(ys) - min(ys)) / H
                if conf >= 0.6 and hh >= 0.012 and len(s.strip()) >= 2:
                    txt.append({"text": s, "conf": round(float(conf), 3), "h": round(hh, 4)})
        res[it["id"]] = {"size": [W, H], "faces": fl, "text": txt}
    print(json.dumps({"refs": notes, "cross": cross, "ref_emb": {n: [round(float(v), 5) for v in r] for n, r in refs.items()}, "items": res}, ensure_ascii=False))


if __name__ == "__main__":
    main()


