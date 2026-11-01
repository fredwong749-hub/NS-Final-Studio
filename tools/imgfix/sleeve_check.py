"""IMGFIX r5：造型 A 设定图袖子修复候选的契约检查 + 对比页 data/review_pages/lookA_sleeve_fix/index.html。

逐项（每张候选）：
  S1 两只袖子都在：右袖框（正面栏像素 x 262–330、y 230–460）米白像素占比 ≤ 3%，深灰像素占比 ≥ 85%（左袖同口径作对照）
  S2 色差：右袖与左袖（关于人物中线镜像位置）平均 Lab ΔE76 ≤ 6
  S3 框外不变：袖子遮罩（膨胀后）以外，整张设定图像素最大差 = 0（脸、发、身材、裙、鞋、背景、其他三栏都没动）
  S4 身份 Q1：契约同一 ArcFace（tools/gen_contract/local_score），特写栏的脸对现行身份脸，候选 ≥ 原图 − 0.005
  S5 交界无米白细条：右袖内侧 4 px 带里米白像素 ≤ 2%
    .venv/Scripts/python.exe tools/imgfix/sleeve_check.py
"""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "tools/gen_contract"), str(ROOT / "services/agent"), str(ROOT / "packages/schema")]
ORIG = ROOT / "data/assetmaster/sheets_v2/adopted/lin_wan_lookA_v2_s202.png"
CAND = ROOT / "data/assetmaster/sheets_v2/candidates/lookA_sleeve_fix"
PAGE = ROOT / "data/review_pages/lookA_sleeve_fix"
PX0 = 664                     # 正面栏左边界（sheet_layout front 0.335 × 1984）
R_BOX = (262, 230, 330, 460)  # 右袖（她的左臂）检查框，正面栏像素
CX = 187.5


def lab(a):
    a = a / 255.0
    a = np.where(a > 0.04045, ((a + 0.055) / 1.055) ** 2.4, a / 12.92)
    M = np.array([[0.4124, 0.3576, 0.1805], [0.2126, 0.7152, 0.0722], [0.0193, 0.1192, 0.9505]])
    xyz = a @ M.T / np.array([0.95047, 1.0, 1.08883])
    f = np.where(xyz > 0.008856, np.cbrt(xyz), 7.787 * xyz + 16 / 116)
    return np.stack([116 * f[..., 1] - 16, 500 * (f[..., 0] - f[..., 1]), 200 * (f[..., 1] - f[..., 2])], -1)


def cream(a):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    return (r > 165) & (g > 150) & (b > 115) & ((r - b) > 12)


def dark(a):
    return a.max(-1) < 130


def sleeve_stats(sheet: np.ndarray) -> dict:
    p = sheet[:, PX0:PX0 + 439].astype(np.float32)
    x0, y0, x1, y1 = R_BOX
    right = p[y0:y1, x0:x1]
    lx0, lx1 = int(2 * CX - x1), int(2 * CX - x0)
    left = p[y0:y1, lx0:lx1][:, ::-1]
    body = ~((right > 235).all(-1))                       # 去掉白背景
    lbody = ~((left > 235).all(-1))
    rc, rd = cream(right)[body].mean(), dark(right)[body].mean()
    lc, ld = cream(left)[lbody].mean(), dark(left)[lbody].mean()
    sel = dark(right) & body
    lsel = dark(left) & lbody
    de = float(np.linalg.norm(lab(right[sel]).mean(0) - lab(left[lsel]).mean(0))) if sel.any() and lsel.any() else None
    # 内侧交界带：每行最左边的非白像素往右 4 px
    band = []
    for row in right:
        nz = np.where(~(row > 235).all(-1))[0]
        if len(nz):
            band.append(row[nz[0]:nz[0] + 4])
    band = np.concatenate(band) if band else np.zeros((0, 3))
    fringe = float(cream(band[None])[0].mean()) if len(band) else None
    return {"right_cream": round(float(rc), 4), "right_dark": round(float(rd), 4), "left_cream": round(float(lc), 4),
            "left_dark": round(float(ld), 4), "deltaE_vs_left": None if de is None else round(de, 2),
            "inner_fringe_cream": None if fringe is None else round(fringe, 4)}


def main():
    import local_score as LS
    orig = np.asarray(Image.open(ORIG).convert("RGB")).astype(np.int16)
    files = sorted(CAND.glob("lin_wan_lookA_v2_s202_sleevefix_*.png"))
    meta = {}
    log = CAND / "candidates.jsonl"
    if log.exists():
        for ln in log.read_text(encoding="utf-8").splitlines():
            r = json.loads(ln)
            meta[Path(r["file"]).name] = r
    # Q1：特写栏（half，0–0.335）裁出来打分
    crops = {}
    (CAND / "q1").mkdir(exist_ok=True)
    for f in [ORIG, *files]:
        c = CAND / "q1" / f"{f.stem}_half.png"
        Image.open(f).convert("RGB").crop((0, 0, 664, 1120)).save(c)
        crops[f.name] = str(c)
    sc = LS.score(crops)["items"]

    def q1(name):
        v = [x.get("sims", {}).get("lin_wan") for x in sc.get(name, {}).get("faces") or []]
        v = [x for x in v if x is not None]
        return round(max(v), 4) if v else None
    q1o = q1(ORIG.name)
    rows = []
    base = sleeve_stats(orig.astype(np.uint8))
    for f in files:
        a = np.asarray(Image.open(f).convert("RGB")).astype(np.int16)
        diff = np.abs(a - orig).max(-1)
        m = meta.get(f.name) or {}
        # 框外：袖子遮罩包络（正面栏 x 225–375、y 160–570）以外的像素
        outside = diff.copy()
        outside[160:570, PX0 + 225:PX0 + 375] = 0      # 遮罩包络：袖子框 + 膨胀 6 px + 羽化 3σ
        st = sleeve_stats(a.astype(np.uint8))
        q = q1(f.name)
        checks = {
            "S1 两只袖子都在": st["right_cream"] <= 0.03 and st["right_dark"] >= 0.85,
            "S2 ΔE≤6": st["deltaE_vs_left"] is not None and st["deltaE_vs_left"] <= 6,
            "S3 框外像素不变": int(outside.max()) == 0,
            "S4 Q1 不降": q is not None and q1o is not None and q >= q1o - 0.005,
            "S5 交界无米白细条": st["inner_fringe_cream"] is not None and st["inner_fringe_cream"] <= 0.02,
        }
        rows.append({"file": str(f.relative_to(ROOT)).replace("\\", "/"), "seed": m.get("seed"), "denoise": m.get("denoise"),
                     "method": m.get("method", "edit_no_mask（第 1 次）"), **st, "outside_max_diff": int(outside.max()),
                     "changed_px_in_box": int((diff > 0).sum()), "q1": q, "q1_orig": q1o, "checks": checks,
                     "pass": all(checks.values())})
    rep = {"orig": {"file": str(ORIG.relative_to(ROOT)).replace("\\", "/"), **base, "q1": q1o}, "candidates": rows}
    PAGE.mkdir(parents=True, exist_ok=True)
    (PAGE / "check.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1), encoding="utf-8")
    for r in rows:
        print(Path(r["file"]).name, "PASS" if r["pass"] else "fail", {k: v for k, v in r["checks"].items() if not v},
              r["right_cream"], r["right_dark"], r["deltaE_vs_left"], r["inner_fringe_cream"], r["q1"], flush=True)
    return rep


def page(rep: dict, picks: list[str]) -> Path:
    e = html.escape
    rel = lambda p: "../../../" + p  # noqa: E731
    by = {r["file"]: r for r in rep["candidates"]}
    zoom = PAGE / "zoom"
    zoom.mkdir(exist_ok=True)

    def z(f, tag):
        out = zoom / f"{tag}.png"
        Image.open(ROOT / f).crop((PX0, 0, PX0 + 439, 760)).save(out)
        crop_out = zoom / f"{tag}_front_nohead.png"
        return f"zoom/{out.name}"
    cells = [f"<td><img src='{z(rep['orig']['file'], 'orig')}'><div>原图 adopted v2_s202（左臂米白袖）<br>Q1 {rep['orig']['q1']}</div></td>"]
    trs = []
    for i, f in enumerate(picks):
        r = by[f]
        cells.append(f"<td><img src='{z(f, f'cand{i}')}'><div><b>候选 {i + 1}</b>（seed {r['seed']}，denoise {r['denoise']}）<br>"
                     f"右袖米白 {r['right_cream']:.1%} / 深灰 {r['right_dark']:.1%}；ΔE {r['deltaE_vs_left']}；交界米白 {r['inner_fringe_cream']:.1%}"
                     f"<br>框外像素最大差 {r['outside_max_diff']}；Q1 {r['q1']}（原 {r['q1_orig']}）</div></td>")
        trs.append("<tr><th>" + e(f"候选 {i + 1}") + "</th>" + "".join(f"<td>{'✅' if v else '❌'} {e(k)}</td>" for k, v in r["checks"].items()) + "</tr>")
    doc = f"""<!doctype html><meta charset="utf-8"><title>造型 A 设定图袖子修复</title>
<style>body{{font:14px/1.5 system-ui,"Microsoft YaHei";margin:20px;background:#111;color:#ddd}}img{{width:300px;display:block;background:#fff}}
td,th{{border:1px solid #444;padding:6px;vertical-align:top}}table{{border-collapse:collapse;margin-bottom:16px}}div{{font-size:12px;max-width:300px}}</style>
<h2>林晚造型 A 设定图 v2_s202：正面栏左臂外套袖修复（只放契约全过的候选）</h2>
<p>只重画正面栏画面右侧那只袖子（遮罩内），遮罩外像素与原图逐像素相同（S3）。数据 data/review_pages/lookA_sleeve_fix/check.json；脚本 tools/imgfix/sleeve_fix.py、sleeve_check.py。</p>
<table><tr>{''.join(cells)}</tr></table><h3>契约逐项</h3><table>{''.join(trs)}</table>"""
    (PAGE / "index.html").write_text(doc, encoding="utf-8")
    return PAGE / "index.html"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    rep = main()
    ok = [r for r in rep["candidates"] if r["pass"]]
    ok.sort(key=lambda r: (r["inner_fringe_cream"], r["deltaE_vs_left"]))
    print(page(rep, [r["file"] for r in ok[:3]]))
