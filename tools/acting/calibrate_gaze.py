"""ACTING 标定（R11-2 / R11-8）：看镜头 / 首秒定格检测器在现有首帧和片段上跑一遍，出给总调度标注的本地审片页。

    .venv/Scripts/python.exe tools/acting/calibrate_gaze.py            # 测 + 出页 data/review_pages/acting_gaze_calib.html
    .venv/Scripts/python.exe tools/acting/calibrate_gaze.py --score    # 读标注 data/acting/gaze_labels.json → 分得开吗

标注页每行一个样本（首帧图里的脸 / 片段前 1 秒 4 帧），检测器结论在旁边；总调度点“看镜头 / 没看 / 开头定格 / 开头在动 / 看不清”，
最后点“导出标注”得到 gaze_labels.json，放到 data/acting/。--score 输出混淆表与可分性；
只有两类分得开（看镜头 召回 ≥ 0.85 且 误报 ≤ 0.15）时，才向总调度提议把 ns_qc.gaze.BLOCK 改成 True。没有标注 = 未标定，只记录。
"""
from __future__ import annotations

import base64
import glob
import html
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "qc"))
import cv2  # noqa: E402
import numpy as np  # noqa: E402
from ns_qc import gaze as G  # noqa: E402

OUT = ROOT / "data" / "acting"
PAGE = ROOT / "data" / "review_pages" / "acting_gaze_calib.html"
IMG_GLOB = "data/pipeline/runs/series10_v1/video/inputs/*.jpg"
CLIP_GLOB = "data/pipeline/runs/series10_v1/video/_preview/*.mp4"


def b64(img, w=None) -> str:
    if w:
        img = cv2.resize(img, (w, int(img.shape[0] * w / img.shape[1])))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 82])
    return "data:image/jpeg;base64," + base64.b64encode(buf).decode()


def face_crop(bgr, box):
    x, y, w, h = (int(v) for v in box)
    pad = int(0.35 * h)
    H, W = bgr.shape[:2]
    return bgr[max(0, y - pad):min(H, y + h + pad), max(0, x - pad):min(W, x + w + pad)]


def measure():
    m = G._models()
    rows = []
    for p in sorted(glob.glob(str(ROOT / IMG_GLOB))):
        bgr = cv2.imread(p)
        r = G.image_gaze(bgr, m)
        for k, f in enumerate(r["faces"][:2]):
            rows.append({"id": f"img:{Path(p).name}#{k}", "kind": "image", "file": str(Path(p).relative_to(ROOT)).replace("\\", "/"),
                         "status": f["status"], "feat": {x: f.get(x) for x in ("iod", "yaw_n", "pitch_n", "iris_dx", "gaze_x")},
                         "thumb": b64(face_crop(bgr, f["box"]), 220)})
        if not r["faces"]:
            rows.append({"id": f"img:{Path(p).name}#-", "kind": "image", "file": p, "status": "未测", "feat": {}, "thumb": b64(bgr, 160)})
    for p in sorted(glob.glob(str(ROOT / CLIP_GLOB))):
        if p.endswith("_sg.mp4"):
            continue
        r = G.video_checks(p, m)
        cap = cv2.VideoCapture(p)
        fps = cap.get(cv2.CAP_PROP_FPS) or 24
        fr = []
        for t in (0.0, 0.33, 0.66, 1.0):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(t * fps))
            ok, f = cap.read()
            if ok:
                fr.append(cv2.resize(f, (150, int(f.shape[0] * 150 / f.shape[1]))))
        cap.release()
        rows.append({"id": f"clip:{Path(p).name}", "kind": "clip", "file": str(Path(p).relative_to(ROOT)).replace("\\", "/"),
                     "status": r["first_sec"]["status"], "cam": r["camera_gaze"]["status"],
                     "feat": {**{k: r["first_sec"][k] for k in ("still_from_start_s", "freeze", "camera_gaze_frac", "motion_mean")},
                              "cam_frac": r["camera_gaze"]["frac"], "caption_hits": r["caption"]["hits"]},
                     "thumb": b64(np.hstack(fr)) if fr else ""})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "calib_results.json").write_text(json.dumps([{k: v for k, v in x.items() if k != "thumb"} for x in rows],
                                                       ensure_ascii=False, indent=1), encoding="utf-8")
    return rows


def page(rows):
    opts_img = ["看镜头", "没看镜头", "看不清"]
    opts_clip = ["开头定格", "开头看镜头", "开头定格+看镜头", "开头在动且没看镜头", "看不清"]
    tr = []
    for x in rows:
        opts = opts_img if x["kind"] == "image" else opts_clip
        radios = " ".join(f'<label><input type=radio name="{html.escape(x["id"])}" value="{o}"> {o}</label>' for o in opts)
        det = html.escape(x["status"] + (f" / 全片：{x.get('cam')}" if x.get("cam") else ""))
        tr.append(f'<tr><td><img src="{x["thumb"]}"></td><td>{html.escape(x["id"])}<br><small>{html.escape(json.dumps(x["feat"], ensure_ascii=False))}</small>'
                  f'<br>检测器（暂定阈值）：<b>{det}</b></td><td>{radios}</td></tr>')
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text(f"""<!doctype html><meta charset=utf-8><title>ACTING 视线 / 首秒定格 标定</title>
<style>body{{font:14px sans-serif;margin:16px}}td{{border-bottom:1px solid #ddd;padding:6px;vertical-align:top}}img{{max-height:200px}}</style>
<h2>看镜头 / 开头定格 检测器标定（只给总调度标注；检测器目前只记录，不拦）</h2>
<p>每行点一个答案，最后点“导出标注”，把下载的 gaze_labels.json 放到 data/acting/，再跑 <code>calibrate_gaze.py --score</code>。
共 {len(rows)} 个样本（首帧脸 {sum(x['kind']=='image' for x in rows)}，片段 {sum(x['kind']=='clip' for x in rows)}）。</p>
<button onclick="exp()">导出标注</button>
<table>{''.join(tr)}</table>
<script>function exp(){{const o={{}};document.querySelectorAll('input[type=radio]:checked').forEach(i=>o[i.name]=i.value);
const a=document.createElement('a');a.href=URL.createObjectURL(new Blob([JSON.stringify(o,null,1)],{{type:'application/json'}}));
a.download='gaze_labels.json';a.click();}}</script>""", encoding="utf-8")


def score():
    res = {x["id"]: x for x in json.loads((OUT / "calib_results.json").read_text(encoding="utf-8"))}
    lp = OUT / "gaze_labels.json"
    if not lp.exists():
        print("未标定：没有 data/acting/gaze_labels.json")
        return 2
    lab = json.loads(lp.read_text(encoding="utf-8"))
    # 标签按选项全文比对（“没看镜头”里含“看镜头”四个字，不能用子串判）
    CAM = {"看镜头", "开头看镜头", "开头定格+看镜头"}
    FRZ = {"开头定格", "开头定格+看镜头"}

    def conf(pairs):
        tp = sum(t and p for t, p in pairs)
        fp = sum((not t) and p for t, p in pairs)
        fn = sum(t and not p for t, p in pairs)
        tn = sum((not t) and not p for t, p in pairs)
        rec = tp / (tp + fn) if tp + fn else None
        fpr = fp / (fp + tn) if fp + tn else None
        return {"n": len(pairs), "tp": tp, "fp": fp, "fn": fn, "tn": tn,
                "recall": None if rec is None else round(rec, 3), "fpr": None if fpr is None else round(fpr, 3),
                "separable": rec is not None and fpr is not None and rec >= 0.85 and fpr <= 0.15}

    rows = [(k, v, res[k]) for k, v in sorted(lab.items()) if k in res and v != "看不清"]
    img = [(v in CAM, "看镜头" in x["status"] and x["status"] != "未测") for k, v, x in rows if x["kind"] == "image"]
    clip_gaze = [(v in CAM, "看镜头" in x["status"]) for k, v, x in rows if x["kind"] == "clip"]
    clip_frz = [(v in FRZ, "定格" in x["status"]) for k, v, x in rows if x["kind"] == "clip"]
    out = {"image_camera_gaze": conf(img), "clip_first_sec_camera_gaze": conf(clip_gaze), "clip_first_sec_freeze": conf(clip_frz),
           "untested_or_unclear": len(lab) - len(rows) + sum(1 for k, v, x in rows if x["status"] == "未测")}
    # 留出复核（ITERATION_PROTOCOL H5：不能在定阈值的同一批上验收）：图片 |gaze_x| 阈值在偶数位样本上扫，奇数位上报
    feats = [(v in CAM, abs(x["feat"].get("gaze_x"))) for k, v, x in rows
             if x["kind"] == "image" and x["feat"].get("gaze_x") is not None]
    fit, hold = feats[0::2], feats[1::2]
    best = None
    for t in [i / 100 for i in range(5, 120, 1)]:
        c = conf([(y, g <= t) for y, g in fit])
        if c["recall"] is None or c["fpr"] is None:
            continue
        score_ = c["recall"] - c["fpr"]
        if best is None or score_ > best[0]:
            best = (score_, t, c)
    if best:
        out["image_gaze_x_sweep"] = {"threshold": best[1], "fit": best[2], "holdout": conf([(y, g <= best[1]) for y, g in hold]),
                                     "current_threshold": G.CAM_GAZE_X}
    out["recommend_block"] = all(out[k]["separable"] for k in ("image_camera_gaze", "clip_first_sec_camera_gaze",
                                                                "clip_first_sec_freeze"))
    print(json.dumps(out, ensure_ascii=False, indent=1))
    (OUT / "calib_score.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return 0 if out["recommend_block"] else 1


SHEETS = ROOT / "data" / "review_pages" / "acting_gaze_calib" / "sheets"
OPTS = {"image": ["看镜头", "没看镜头", "看不清"],
        "clip": ["开头定格", "开头看镜头", "开头定格+看镜头", "开头在动且没看镜头", "看不清"]}


def sheets(rows, per: int = 12):
    """总调度标注用：编号接触印样（每张 per 个样本，首帧脸与片段分开）+ index.json（sheet/编号 → 样本 id、检测器暂定结论）。
    标注文件 data/acting/gaze_labels.json 写成 {样本 id: 选项}，选项见 index.json options；--score 读它"""
    SHEETS.mkdir(parents=True, exist_ok=True)
    for old in SHEETS.glob("sheet_*.jpg"):
        old.unlink()
    index = {"options": OPTS, "labels_file": "data/acting/gaze_labels.json", "format": "{样本 id: 选项}", "sheets": []}
    for kind in ("image", "clip"):
        rs = [r for r in rows if r["kind"] == kind and r.get("thumb")]
        for k in range(0, len(rs), per):
            chunk = rs[k:k + per]
            tiles = []
            for j, r in enumerate(chunk, 1):
                raw = base64.b64decode(r["thumb"].split(",", 1)[1])
                im = cv2.imdecode(np.frombuffer(raw, np.uint8), cv2.IMREAD_COLOR)
                h = 300 if kind == "image" else 270
                im = cv2.resize(im, (max(1, int(im.shape[1] * h / im.shape[0])), h))
                pad = np.full((h + 44, max(im.shape[1], 220), 3), 255, np.uint8)
                pad[44:44 + h, :im.shape[1]] = im
                cv2.putText(pad, f"#{j}", (6, 34), cv2.FONT_HERSHEY_SIMPLEX, 1.1, (0, 0, 200), 2, cv2.LINE_AA)
                tiles.append(pad)
            cols = 4 if kind == "image" else 2
            w = max(t.shape[1] for t in tiles)
            hh = max(t.shape[0] for t in tiles)
            tiles = [np.pad(t, ((0, hh - t.shape[0]), (0, w - t.shape[1]), (0, 0)), constant_values=255) for t in tiles]
            while len(tiles) % cols:
                tiles.append(np.full((hh, w, 3), 255, np.uint8))
            grid = np.vstack([np.hstack(tiles[i:i + cols]) for i in range(0, len(tiles), cols)])
            name = f"sheet_{kind}_{k // per + 1:02d}.jpg"
            cv2.imwrite(str(SHEETS / name), grid, [cv2.IMWRITE_JPEG_QUALITY, 85])
            index["sheets"].append({"file": f"data/review_pages/acting_gaze_calib/sheets/{name}", "kind": kind,
                                    "items": [{"n": j, "id": r["id"], "src": r["file"], "detector": r["status"],
                                               **({"detector_full_clip": r["cam"]} if r.get("cam") else {}),
                                               "feat": r["feat"]} for j, r in enumerate(chunk, 1)]})
    (SHEETS / "index.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")
    return index


if __name__ == "__main__":
    if "--score" in sys.argv:
        sys.exit(score())
    rows = measure()
    page(rows)
    idx = sheets(rows)
    print(f"{len(rows)} 个样本 → {PAGE}；{len(idx['sheets'])} 张印样 → {SHEETS}")
