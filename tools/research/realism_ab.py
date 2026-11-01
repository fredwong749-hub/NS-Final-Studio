"""真人写实调参 A/B（RESEARCH，R11-12 / R11-13，2026-11-01，总调度 fredw-2b 派）。

只做 CPU、不占 GPU、不写 takes.json：拿生产首帧（frame_v9 / 徕卡 S★ 结构）已保存的 1152×2016 原图（take.raw_file），
按 ns_render.image_params.post_file 同一后处理（PIL lanczos 缩回 768×1344 → UnsharpMask）重做三档锐化：

  R0  现行：UnsharpMask 半径 1.2 / 60% / 阈值 2（frame_v9、leica_sstar 的 sharpen）
  R1  不锐化：只缩回
  R2  轻锐化：半径 0.8 / 30% / 阈值 3

同种子、同提示词、同原图，只差后处理，所以差别全部来自锐化。度量：契约 Q4 的 lap_full（整图 Laplacian）、
脸部 face_hf / face_lap / face_oil / p_plastic（ns_agent.gen_contract.metrics.face_texture）、边缘过冲 halo（本文件）。
另核对 R0 与生产交付图 *_raw_post.png 的像素差，确认复现的是同一条后处理。

用法：.venv/Scripts/python.exe -X utf8 tools/research/realism_ab.py [--no-clip]
输出：data/ab/realism_ab/<shot>/{R0,R1,R2}.png、crop_face.png、metrics.json；审片页 data/review_pages/realism_ab/index.html
"""
from __future__ import annotations

import argparse
import html
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "agent"))

OUT = ROOT / "data" / "ab" / "realism_ab"
PAGE = ROOT / "data" / "review_pages" / "realism_ab"
SIZE = (768, 1344)
TIERS = {
    "R0": {"label": "现行锐化 USM 1.2 / 60% / 2", "usm": {"radius": 1.2, "percent": 60, "threshold": 2}},
    "R1": {"label": "不锐化（只缩回）", "usm": None},
    "R2": {"label": "轻锐化 USM 0.8 / 30% / 3", "usm": {"radius": 0.8, "percent": 30, "threshold": 3}},
}
# 非亲密镜头（series10 ep01 办公室夜景），生产当前首帧；景别：特写 / 中景 / 近景
SHOTS = [("ep01-S1", "特写"), ("ep01-S2", "中景"), ("ep01-S5", "近景")]
PINNED = {"ep01-S1": 14, "ep01-S2": 6, "ep01-S5": 4}


def halo(img: Image.Image) -> float:
    """边缘过冲：Canny 强边缘 5px 带内，像素超出 σ2 模糊后 7×7 邻域最大 / 最小值的平均幅度（0–255）。USM 光晕越重越大。"""
    import cv2
    g = np.asarray(img.convert("L")).astype(np.float32)
    e = cv2.Canny(g.astype(np.uint8), 60, 140) > 0
    band = cv2.dilate(e.astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    b = cv2.GaussianBlur(g, (0, 0), 2.0)
    mx = cv2.dilate(b, np.ones((7, 7), np.uint8))
    mn = cv2.erode(b, np.ones((7, 7), np.uint8))
    over = np.maximum(g - mx, 0) + np.maximum(mn - g, 0)
    return round(float(over[band].mean()), 3) if band.any() else 0.0


def face_box(img: Image.Image):
    """本机 YuNet（models_cache/vision/face_detection_yunet_2023mar.onnx，tools/ab/crop_identity_refs.py 同一个）取最大脸框；
    检测不到返回 None（脸部指标记 —，不算过）"""
    import cv2
    a = np.ascontiguousarray(np.asarray(img.convert("RGB"))[..., ::-1])
    det = cv2.FaceDetectorYN.create(str(ROOT / "models_cache/vision/face_detection_yunet_2023mar.onnx"), "",
                                    (a.shape[1], a.shape[0]), 0.6)
    _, fs = det.detect(a)
    if fs is None or len(fs) == 0:
        return None
    x, y, w, h = max(fs[:, :4].tolist(), key=lambda r: r[2] * r[3])
    return [int(x), int(y), int(x + w), int(y + h)]


def current_take(shot: str) -> dict:
    ep, s = shot.split("-")
    d = json.loads((ROOT / "data" / "renders" / ep / s / "takes.json").read_text(encoding="utf-8"))
    n = PINNED.get(shot) or (d.get("active") or {}).get("image")   # 11-01 首次跑时的当前首帧，钉死（之后生产会换当前 / 撤版本）
    t = next(t for t in d["takes"] if t.get("stage") == "image" and t.get("n") == n)
    if not t.get("raw_file"):
        raise SystemExit(f"{shot} 当前首帧 #{n} 没有 raw_file，不能离线复现后处理")
    return t


def run(use_clip: bool) -> dict:
    from ns_agent.gen_contract.metrics import face_texture, texture
    res = {"tiers": TIERS, "shots": []}
    for shot, size in SHOTS:
        t = current_take(shot)
        raw = Image.open(ROOT / "data" / t["raw_file"]).convert("RGB")
        delivered = Image.open(ROOT / "data" / t["file"]).convert("RGB")
        od = OUT / shot
        od.mkdir(parents=True, exist_ok=True)
        imgs = {}
        for k, tier in TIERS.items():
            im = raw.resize(SIZE, Image.LANCZOS)
            if tier["usm"]:
                im = im.filter(ImageFilter.UnsharpMask(**tier["usm"]))
            im.save(od / f"{k}.png")
            imgs[k] = im
        diff = float(np.abs(np.asarray(imgs["R0"], np.int16) - np.asarray(delivered, np.int16)).mean())
        fb = face_box(imgs["R1"])
        row = {"shot": shot, "size": size, "take": t["n"], "seed": t.get("seed"), "raw": t["raw_file"], "delivered": t["file"],
               "r0_vs_delivered_mean_abs": round(diff, 3), "face_box": fb, "tiers": {}}
        for k, im in imgs.items():
            tx = texture(im, fb)
            m = {"lap_full": tx["lap_full"], "specular": tx["specular"], "halo": halo(im)}
            if fb and use_clip:
                m.update(face_texture(im, fb) or {})
            row["tiers"][k] = m
        # 脸部 1:1 局部拼图（以 R1 检测到的脸框为中心，三档同一位置）
        if fb:
            x1, y1, x2, y2 = fb
            cx, cy, half = (x1 + x2) // 2, (y1 + y2) // 2, max(x2 - x1, y2 - y1)
            box = (max(0, cx - half), max(0, cy - half), min(SIZE[0], cx + half), min(SIZE[1], cy + half))
            crops = [imgs[k].crop(box) for k in TIERS]
            w, h = crops[0].size
            sheet = Image.new("RGB", (w * 3 + 20, h + 28), (24, 24, 24))
            dr = ImageDraw.Draw(sheet)
            for i, (k, c) in enumerate(zip(TIERS, crops)):
                sheet.paste(c, (i * (w + 10), 28))
                dr.text((i * (w + 10) + 4, 6), k, fill=(255, 210, 80))
            sheet.save(od / "crop_face.png")
            row["crop_box"] = list(box)
        res["shots"].append(row)
    (OUT / "metrics.json").write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    return res


def page(res: dict) -> None:
    PAGE.mkdir(parents=True, exist_ok=True)
    rel = "../../ab/realism_ab"
    keys = ["lap_full", "halo", "face_hf", "face_lap", "p_plastic", "face_oil", "specular"]
    css = """
:root{--bg:#f6f5f2;--fg:#1d1d1b;--mut:#6b6a66;--card:#fff;--line:#dedbd3;--acc:#9a5b00}
@media (prefers-color-scheme:dark){:root{--bg:#161615;--fg:#ecebe7;--mut:#a3a19b;--card:#21211f;--line:#3a3935;--acc:#f0b55a}}
body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif}
main{max-width:1180px;margin:0 auto;padding:20px 16px 60px}
h1{font-size:22px;margin:4px 0 6px}h2{font-size:18px;margin:28px 0 8px}
.mut{color:var(--mut)}.card{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:14px;margin:12px 0}
.row{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.row img{width:100%;border-radius:6px;display:block}
table{border-collapse:collapse;width:100%;font-size:13px;overflow-x:auto;display:block}
td,th{border-bottom:1px solid var(--line);padding:5px 8px;text-align:right;white-space:nowrap}th:first-child,td:first-child{text-align:left}
.tag{font-weight:600;color:var(--acc)}.crop{width:100%;border-radius:6px}
@media (max-width:640px){.row{grid-template-columns:1fr}}
"""
    parts = [f"<!doctype html><html lang='zh'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>"
             f"<title>写实锐化 A/B</title><style>{css}</style></head><body><main>",
             "<h1>写实调参 A/B · 锐化三档（R11-12 / R11-13）</h1>",
             "<div class='card'><b>结论：项目方选 R0，现行保持。</b>（11-01 17:5x 原话：“这个版本出来的东西,无论是画面效果还是颜色,都非常满意……很棒哎!”；"
             "徕卡 S★ 全套、USM 1.2/60/2、契约 Q4 都不改，L-087）</div>",
             "<p class='mut'>同一张生产原图（1152×2016，同种子同提示词），只换交付前的锐化。R0 = 现行 frame_v9 / 徕卡 S★；"
             "R1 = 不锐化；R2 = 轻锐化。CPU 离线重做，没有占 GPU，没有写进镜头版本。非亲密镜头（ep01 办公室）。"
             "本页只列图和数字，不替项目方选；结论与建议见 RESEARCH 报告。</p>"]
    parts.append("<div class='card'><b>怎么看</b>：先看每镜下面的“脸部 1:1”三联图（左 R0 · 中 R1 · 右 R2），"
                 "注意发丝边、睫毛、鼻翼和下颌边上的白边（光晕）与皮肤是不是“砂纸感”。整图在下面一行。</div>")
    for row in res["shots"]:
        parts.append(f"<h2>{html.escape(row['shot'])} · {row['size']} · 当前首帧 #{row['take']}</h2>")
        parts.append(f"<p class='mut'>原图 {html.escape(row['raw'])}；R0 与生产交付图逐像素平均差 {row['r0_vs_delivered_mean_abs']}"
                     f"（0–255，≈0 表示复现的是同一条后处理）</p>")
        if row.get("crop_box"):
            parts.append(f"<img class='crop' src='{rel}/{row['shot']}/crop_face.png' alt='脸部 1:1 三联'>")
        parts.append("<div class='row'>" + "".join(
            f"<div><div class='tag'>{k} · {html.escape(TIERS[k]['label'])}</div><a href='{rel}/{row['shot']}/{k}.png'>"
            f"<img loading='lazy' src='{rel}/{row['shot']}/{k}.png' alt='{k}'></a></div>" for k in TIERS) + "</div>")
        parts.append("<table><tr><th>档</th>" + "".join(f"<th>{k}</th>" for k in keys) + "</tr>" + "".join(
            "<tr><td>" + k + "</td>" + "".join(f"<td>{row['tiers'][k].get(c, '—')}</td>" for c in keys) + "</tr>"
            for k in TIERS) + "</table>")
    parts.append("<h2>指标说明</h2><ul class='mut'>"
                 "<li>lap_full：契约 Q4 现行判据（整图缩到宽 768 的 Laplacian 方差，线 175）。锐化会直接把它抬高。</li>"
                 "<li>halo：强边缘附近超出局部亮暗范围的平均幅度，越大白边 / 黑边越重。</li>"
                 "<li>face_hf / face_lap：脸框中间 60% 的高频能量 / Laplacian 方差（脸检测用 OpenCV Haar，检测不到就是 —）。</li>"
                 "<li>p_plastic：CLIP 探针“塑料娃娃脸 vs 真人照片”的前者概率（契约同一探针）。</li>"
                 "<li>face_oil / specular：脸部 / 区域近白低饱和像素占比（油光）。</li></ul>")
    parts.append("<h2>GPU 档（G0 / G1 / G2）</h2><p class='mut'>已取消：项目方选 R0，改提示词 / 换 LoRA 属推翻刚确认的选择（L-087）。</p>")
    parts.append("</main></body></html>")
    (PAGE / "index.html").write_text("\n".join(parts), encoding="utf-8")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-clip", action="store_true", help="不跑 CLIP 探针（p_plastic 记 —）")
    a = ap.parse_args()
    res = run(not a.no_clip)
    page(res)
    for row in res["shots"]:
        print(row["shot"], row["r0_vs_delivered_mean_abs"], {k: v for k, v in row["tiers"].items()})


if __name__ == "__main__":
    main()
