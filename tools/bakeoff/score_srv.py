#!/usr/bin/env python3
"""BAKEOFF 质检（gpu36 的 /root/work/fredw/venv_idm 里跑，CPU）。按 GEN_CONTRACT v1 Q1–Q7 打分，只测像素，不看内容。

Q1 身份：insightface buffalo_l（与 tools/identity_metric.py 同模型），对本人参考余弦；林晚 ≥0.70、其他 ≥0.60；对他人 < max(0.40, 参考互余弦+0.05)。
Q2 造型（代理）：脸下方身体区 HS 直方图 vs 造型设定图，相关系数；REFLOCK 的 DINO/CLIP 裁区实现出来后替换。
Q3 景别：脸高/画面高 → 档位（IMGGEN K-REN-122 校准的 BANDS），与镜头景别差 ≤1 档算过。
Q4 质感：脸部肤色区（YCrCb）高频能量、5×5 局部标准差均值、Laplacian 方差；全图 Laplacian；饱和度；肤色区镜面高光占比（V>0.90 且 S<0.20，“油”）。
Q5 手/肢体：hands_remote.py（mediapipe，venv_hand），可疑即标。
Q6 文字/水印：rapidocr（同 IMGGEN 阈值）。
Q7 场景（代理）：画面上部 30% + 左右各 15% 边带的 HS 直方图 vs 场景参考，相关系数。
输出 results.json + thumbs/*.jpg（360 宽）。
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
SIZE_IDX = {"极近特写": 0, "大特写": 0, "特写": 1, "近景": 2, "中近景": 2, "中景": 3, "中全景": 4, "全身": 5, "全景": 5, "远景": 6, "大远景": 6}
BANDS = [0.45, 0.27, 0.17, 0.115, 0.095, 0.05]
NAME_THR = {"lin_wan": 0.70}


def imread(p):
    im = cv2.imread(str(p))
    if im is None:                       # 推送时造型设定图转成了 JPEG 内容但保留 .png 名：OpenCV 5 按扩展名解码会失败 → PIL 兜底
        from PIL import Image
        im = cv2.cvtColor(np.array(Image.open(p).convert("RGB")), cv2.COLOR_RGB2BGR)
    return im


def band(h):
    for i, b in enumerate(BANDS):
        if h >= b:
            return i
    return 6


def hs_hist(img, mask=None):
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    h = cv2.calcHist([hsv], [0, 1], mask, [30, 32], [0, 180, 0, 256])
    return cv2.normalize(h, h).flatten()


def texture(img, box):
    H, W = img.shape[:2]
    x1, y1, x2, y2 = box
    cx, cy, bw, bh = (x1 + x2) / 2, (y1 + y2) / 2, (x2 - x1) * 1.1, (y2 - y1) * 1.1
    xa, ya, xb, yb = int(max(0, cx - bw / 2)), int(max(0, cy - bh / 2)), int(min(W, cx + bw / 2)), int(min(H, cy + bh / 2))
    crop = img[ya:yb, xa:xb]
    if crop.size == 0 or crop.shape[0] < 16:
        return None
    crop = cv2.resize(crop, (256, int(256 * crop.shape[0] / crop.shape[1])), interpolation=cv2.INTER_AREA)
    ycc = cv2.cvtColor(crop, cv2.COLOR_BGR2YCrCb)
    skin = ((ycc[..., 1] >= 133) & (ycc[..., 1] <= 173) & (ycc[..., 2] >= 77) & (ycc[..., 2] <= 127))
    skin = cv2.erode(skin.astype(np.uint8), np.ones((5, 5), np.uint8)).astype(bool)
    if skin.sum() < 500:
        return {"skin_px": int(skin.sum())}
    g = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY).astype(np.float32)
    hf = np.abs(g - cv2.GaussianBlur(g, (0, 0), 1.5))
    mu = cv2.blur(g, (5, 5))
    sd = np.sqrt(np.maximum(cv2.blur(g * g, (5, 5)) - mu * mu, 0))
    lap = cv2.Laplacian(g, cv2.CV_32F)
    hsv = cv2.cvtColor(crop, cv2.COLOR_BGR2HSV).astype(np.float32) / 255.0
    # “油”：镜面高光像素本身不在 YCrCb 肤色范围里（偏白），所以按脸部椭圆（检测框内 85%）统计，而不是按肤色掩码
    hh, ww = crop.shape[:2]
    yy, xx = np.mgrid[0:hh, 0:ww]
    ell = ((xx - ww / 2) / (ww * 0.425)) ** 2 + ((yy - hh / 2) / (hh * 0.425)) ** 2 <= 1
    spec = (hsv[..., 2] > 0.88) & (hsv[..., 1] < 0.22) & ell
    skin_e = ell
    return {"skin_px": int(skin.sum()), "hf": round(float(hf[skin].mean()), 3), "texstd": round(float(sd[skin].mean()), 3),
            "lap_face": round(float(lap[skin].var()), 2), "skin_sat": round(float(hsv[..., 1][skin].mean()), 4),
            "spec": round(float(spec.sum() / max(1, skin_e.sum())), 5)}


def main():
    plan = json.loads((HERE / "plan.json").read_text(encoding="utf-8"))
    meta = {}
    if (HERE / "gen_meta.jsonl").exists():
        for ln in (HERE / "gen_meta.jsonl").read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            meta[r["id"]] = r
    from insightface.app import FaceAnalysis
    app = FaceAnalysis(name="buffalo_l", root="/root/work/fredw/idm_models", allowed_modules=["detection", "recognition"],
                       providers=["CPUExecutionProvider"])
    app.prepare(ctx_id=-1, det_size=(640, 640))
    from rapidocr_onnxruntime import RapidOCR
    ocr = RapidOCR()

    def faces(img):
        out = [(f, [float(v) for v in f.bbox]) for f in app.get(img)]
        return [(f, b) for f, b in out if b[2] - b[0] >= 24 and f.det_score >= 0.55]

    refs = {}
    for name, paths in plan["score_face"].items():
        es = []
        for p in paths:
            im = imread(str(HERE / "refs" / p))
            fs = faces(im) or faces(cv2.resize(im, None, fx=2, fy=2))
            if fs:
                es.append(max(fs, key=lambda t: t[1][2] - t[1][0])[0].normed_embedding)
        if es:
            m = np.mean(es, 0)
            refs[name] = m / np.linalg.norm(m)
    cross = {a: max([float(refs[a] @ refs[b]) for b in refs if b.split("@")[0] != a.split("@")[0]] or [0]) for a in refs}
    # 额外：项目方母版 vs IMGGEN 参考（同一个人吗）
    master = imread(str(HERE / "refs/assets/characters/lin_wan/refs/lin_wan/ar-c2351c9dcf.png"))
    mf = []
    for sc in (1.0, 0.5, 0.35, 2.0):           # 母版是大脸裁切（800×924），1 倍时检测器常常找不到 → 缩小再试
        if master is not None and not mf:
            mf = faces(cv2.resize(master, None, fx=sc, fy=sc) if sc != 1.0 else master)
    master_emb = max(mf, key=lambda t: t[1][2] - t[1][0])[0].normed_embedding if mf else None
    master_sim = round(float(max(mf, key=lambda t: t[1][2] - t[1][0])[0].normed_embedding @ refs["lin_wan"]), 4) if mf and "lin_wan" in refs else None

    hist_cache = {}

    def ref_hist(p):
        if p not in hist_cache:
            hist_cache[p] = hs_hist(imread(str(HERE / "refs" / p)))
        return hist_cache[p]

    (HERE / "thumbs").mkdir(exist_ok=True)
    es = [i for i in plan["items"] if i["kind"] == "edit"]
    if es:
        cv2.imwrite(str(HERE / "thumbs/src_edit.jpg"), cv2.resize(imread(str(HERE / "refs" / es[0]["src"])), (360, 630)))
    res, hand_in = {}, []
    for it in plan["items"]:
        p = HERE / "refs" / it["path"] if it["kind"] == "prod" else HERE / "out" / f"{it['id']}.png"
        if not p.exists():
            continue
        img = imread(str(p))
        if img.shape[:2] != (1344, 768):
            img = cv2.resize(img, (768, 1344), interpolation=cv2.INTER_AREA)
        H, W = img.shape[:2]
        th = cv2.resize(img, (360, 630), interpolation=cv2.INTER_AREA)
        cv2.imwrite(str(HERE / "thumbs" / f"{it['id']}.jpg"), th, [cv2.IMWRITE_JPEG_QUALITY, 86])
        fl = sorted(faces(img), key=lambda t: -(t[1][3] - t[1][1]))
        r = {"n_faces": len(fl), "sec": meta.get(it["id"], {}).get("sec"),
             # score_remote.py 同格式（REFLOCK postflight 的 remote 输入）
             "remote": {"faces": [{"bbox": [round(v, 1) for v in b], "h_ratio": round((b[3] - b[1]) / H, 4), "det": round(float(f.det_score), 3),
                                   "sims": {**{n: round(float(f.normed_embedding @ rv), 4) for n, rv in refs.items()},
                                            **({"lin_wan@master": round(float(f.normed_embedding @ master_emb), 4)} if master_emb is not None else {})}}
                                  for f, b in fl]}}
        (HERE / "full").mkdir(exist_ok=True)
        cv2.imwrite(str(HERE / "full" / f"{it['id']}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        # Q1：期望角色按最高相似度贪心配对
        ids, used = {}, set()
        for c in it["chars"]:
            best = None
            if c not in refs:
                continue
            for k, (f, b) in enumerate(fl):
                if k in used or c not in refs:
                    continue
                s = float(f.normed_embedding @ refs[c])
                if best is None or s > best[0]:
                    best = (s, k, b)
            if best:
                used.add(best[1])
                f = fl[best[1]][0]
                others = [float(f.normed_embedding @ refs[o]) for o in refs if o.split("@")[0] != c]
                thr = NAME_THR.get(c, 0.60)
                lim = max(0.40, cross.get(c, 0) + 0.05)
                ids[c] = {"sim_master": round(float(f.normed_embedding @ master_emb), 4) if c == "lin_wan" and master_emb is not None else None,
                          "sim": round(best[0], 4), "max_other": round(max(others), 4), "ok": best[0] >= thr and max(others) < lim,
                          "face_h": round((best[2][3] - best[2][1]) / H, 4), "box": [round(v, 1) for v in best[2]]}
            else:
                ids[c] = {"sim": None, "ok": False}
        r["Q1"] = ids
        r["Q1_ok"] = all(v["ok"] for v in ids.values()) if ids else None
        # Q3
        exp = SIZE_IDX.get(it["size"])
        if it["size"] == "空镜":
            r["Q3"] = {"expect": "空镜", "got": len(fl), "ok": len(fl) == 0}
        elif fl and exp is not None:
            main_c = it["chars"][0] if it["chars"] else None
            fh = ids.get(main_c, {}).get("face_h") or (fl[0][1][3] - fl[0][1][1]) / H
            gb = band(fh)
            r["Q3"] = {"expect": exp, "got": gb, "face_h": round(fh, 4), "ok": abs(gb - exp) <= 1}
        else:
            r["Q3"] = {"expect": exp, "got": None, "ok": False if it["chars"] else None}
        # Q4
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
        q4 = {"lap_img": round(float(cv2.Laplacian(g, cv2.CV_32F).var()), 2), "sat_img": round(float(hsv[..., 1].mean() / 255), 4)}
        main_box = None
        if it["chars"] and ids.get(it["chars"][0], {}).get("box"):
            main_box = ids[it["chars"][0]]["box"]
        elif fl:
            main_box = fl[0][1]
        if main_box:
            q4.update(texture(img, main_box) or {})
        r["Q4"] = q4
        # Q2 / Q7 代理
        if it["looks"] and main_box:
            y0 = int(min(H - 10, main_box[3]))
            body = img[y0:, int(W * 0.2):int(W * 0.8)]
            if body.shape[0] > 40:
                r["Q2"] = {c: round(float(cv2.compareHist(hs_hist(body), ref_hist(pth), cv2.HISTCMP_CORREL)), 4) for c, pth in it["looks"].items()}
        if it.get("scene"):
            m = np.zeros((H, W), np.uint8)
            m[: int(H * 0.3)] = 255
            m[:, : int(W * 0.15)] = 255
            m[:, int(W * 0.85):] = 255
            r["Q7"] = round(float(cv2.compareHist(hs_hist(img, m), ref_hist(it["scene"]), cv2.HISTCMP_CORREL)), 4)
        # Q6
        o, _ = ocr(img)
        r["remote"]["text"] = r["Q6_raw"] = [{"text": s, "conf": round(float(cf), 3), "h": round((max(q[1] for q in box) - min(q[1] for q in box)) / H, 4)}
                                             for box, s, cf in (o or [])]
        r["Q6"] = [{"text": s, "conf": round(float(cf), 3)} for box, s, cf in (o or [])
                   if cf >= 0.6 and (max(q[1] for q in box) - min(q[1] for q in box)) / H >= 0.012 and len(s.strip()) >= 2]
        # 输出 = 参考板 / 参考拼图（总调度 11-01 #05）：白色栅格、格子≈参考、整图≈参考、大量文字、同一人出现两次 → 判“照抄参考”，不计分
        try:
            import refcopy as RC
            rc = RC.ref_copy_score(img) if it["kind"] != "edit" else {}
        except Exception as e:  # noqa: BLE001
            rc = {"error": str(e)[:120]}
        embs = [f.normed_embedding for f, _ in fl]
        dup = max((float(embs[a] @ embs[b]) for a in range(len(embs)) for b in range(a + 1, len(embs))), default=0.0)
        rc["dup_face"] = round(dup, 4)
        rc["n_text"] = len(r["Q6"])
        rc["copied"] = bool(rc.get("copied")) or rc["n_text"] >= 5 or (dup >= 0.55 and it["kind"] != "edit")
        r["ref_copy"] = rc
        res[it["id"]] = r
        hand_in.append({"id": it["id"], "path": str(p), "faces": max(1, len(fl))})
    # Q5（另一个 venv）
    try:
        hr = subprocess.run(["/root/work/fredw/venv_hand/bin/python", str(HERE / "hands_remote.py")], input=json.dumps({"items": hand_in}),
                            capture_output=True, text=True, timeout=3600)
        hands = json.loads(hr.stdout.strip().splitlines()[-1])
        for k, v in hands.items():
            if k in res:
                res[k]["Q5"] = v.get("flags", [])
    except Exception as e:  # noqa: BLE001
        print("hands 失败", e, file=sys.stderr)
    out = {"cross_raw": {f"{a}~{b}": round(float(refs[a] @ refs[b]), 4) for i, a in enumerate(refs) for b in list(refs)[i + 1:]},
           "ref_cross": {k: round(v, 4) for k, v in cross.items()}, "master_vs_ref2va_lin_wan": master_sim, "items": res}
    (HERE / "results.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print("SCORED", len(res))


if __name__ == "__main__":
    main()
