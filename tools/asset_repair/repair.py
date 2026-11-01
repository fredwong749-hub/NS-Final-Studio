"""资产缺陷局部修复（通用工具，IMGFIX r6；L-102 / ITERATION_PROTOCOL §G1：流程写成可复用工具、选图判据写成代码，不靠亲审）。

流程：spec（JSON）→ ① 铺底（把缺陷区里符合 select 的像素铺成参考区的主色，带轻微明暗起伏）→ ② Qwen-Image 2.1 潜空间遮罩重绘
（只在遮罩里加噪；init / 参考图 = 铺底后的栏）→ ③ 只把遮罩（膨胀 + 羽化）贴回原图，遮罩外逐像素不变 → ④ 契约检查 → ⑤ 自动选图。
第一次用在林晚造型 A 设定图缺左臂外套袖（L-101，config/asset_repair/lin_wan_lookA_sleeve.json）。

spec 字段：
  asset          原图（仓库相对路径）
  panel          "front" | "half" | "side" | "back" | "full"（asset_refs sheet_layout 的栏；full = 整张）
  defect_box     缺陷框（栏内像素 [x0,y0,x1,y1]）；fill_until_y：铺底只到这一行（例：袖口以上）
  select         铺底选哪些像素：{"rgb_min":[r,g,b], "r_minus_b_min":n, "exclude_white":true}
  color_from     主色取样框（栏内像素）；ref_box：契约 R2 对照框（缺省 = defect_box 关于 mirror_x 镜像）
  mirror_x       镜像轴（栏内 x）；prompt；seeds；denoises；scale（生成放大倍数）；dilate / feather（遮罩膨胀 / 羽化 px）
  checks         {"target_dark_min":0.85, "target_light_max":0.03, "de_max":6, "fringe_max":0.02, "q1_drop_max":0.005,
                  "intake": true}   # intake = 修后整图过 ns_agent.sheet_intake（K-AST-264）
自动选图（R1–R7 全过的候选里）：纹理接近参考（深色区内部高频比越接近 1 越好）优先，其次 ΔE 小。

    .venv/Scripts/python.exe tools/asset_repair/repair.py run   <spec.json> [--url http://127.0.0.1:18188]
    .venv/Scripts/python.exe tools/asset_repair/repair.py check <spec.json>      # 只检查 + 选图 + 审片页（不出图）
"""
from __future__ import annotations

import html
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
for _p in ("services/render_router", "services/agent", "packages/schema", "packages/qc", "tools/gen_contract"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))


def load_spec(p: str) -> dict:
    s = json.loads((ROOT / p).read_text(encoding="utf-8"))
    s.setdefault("seeds", [20261102, 20261202, 20261302])
    s.setdefault("denoises", [0.85, 0.92])
    s.setdefault("scale", 1.5)
    s.setdefault("dilate", 13)
    s.setdefault("feather", 9)
    s.setdefault("checks", {})
    s["_out"] = ROOT / s.get("out_dir", f"data/assetmaster/repair/{s['id']}")
    return s


def panel_xy(im, panel: str):
    from ns_agent import asset_refs as AR
    if panel == "full":
        return 0, 0, im.width, im.height
    a, b = AR._cfg()["sheet_layout"][panel]
    return int(a * im.width), 0, int(b * im.width), im.height


def _sel(a, rule: dict):
    r, g, b = a[..., 0], a[..., 1], a[..., 2]
    mn = rule.get("rgb_min", [0, 0, 0])
    m = (r > mn[0]) & (g > mn[1]) & (b > mn[2]) & ((r - b) > rule.get("r_minus_b_min", -999))
    if rule.get("exclude_white", True):
        m &= ~((r > 235) & (g > 235) & (b > 230))
    return m


def prefill(panel, s: dict):
    from PIL import Image
    a = np.asarray(panel).astype(np.float32)
    x0, y0, x1, y1 = s["defect_box"]
    y1f = min(y1, s.get("fill_until_y", y1))
    cx0, cy0, cx1, cy1 = s["color_from"]
    base = np.median(a[cy0:cy1, cx0:cx1].reshape(-1, 3), axis=0)
    sub = a[y0:y1f, x0:x1]
    m = _sel(sub, s.get("select", {}))
    yy, xx = np.mgrid[y0:y1f, x0:x1]
    shade = 1.0 + 0.06 * np.sin(yy / 23.0) - 0.05 * ((xx - x0) / max(1, x1 - x0))
    out = a.copy()
    out[y0:y1f, x0:x1][m] = np.clip(base[None, :] * shade[m][:, None], 0, 255)
    mask = np.zeros(a.shape[:2], np.uint8)
    mask[y0:y1f, x0:x1][m] = 255
    return Image.fromarray(out.astype(np.uint8)), Image.fromarray(mask)


def run(s: dict, url: str):
    from PIL import Image, ImageFilter
    from ns_render import workflows as W
    from ns_render.comfy_client import ComfyClient
    out = s["_out"]
    out.mkdir(parents=True, exist_ok=True)
    full = Image.open(ROOT / s["asset"]).convert("RGB")
    px0, py0, px1, py1 = panel_xy(full, s["panel"])
    panel = full.crop((px0, py0, px1, py1))
    pw, ph = panel.size
    filled, fmask = prefill(panel, s)
    gw, gh = (int(pw * s["scale"]) // 16) * 16, (int(ph * s["scale"]) // 16) * 16
    src = out / "prefilled_x.png"
    filled.resize((gw, gh), Image.LANCZOS).save(src)
    mpath = out / "mask_x.png"
    mk = fmask.filter(ImageFilter.MaxFilter(s["dilate"])).resize((gw, gh), Image.NEAREST)
    Image.merge("RGB", (mk, mk, mk)).save(mpath)
    cl = ComfyClient(url)
    name, mname = cl.upload_image(src, subfolder=f"ns_ab/repair_{s['id']}"), cl.upload_image(mpath, subfolder=f"ns_ab/repair_{s['id']}")
    paste_mask = fmask.filter(ImageFilter.MaxFilter(s["dilate"])).filter(ImageFilter.GaussianBlur(s["feather"]))
    log = out / "candidates.jsonl"
    for dn in s["denoises"]:
        for seed in s["seeds"]:
            tag = f"d{int(dn * 100)}_s{seed}"
            wf = W.qwen_edit(s["prompt"], "", [name], gw, gh, seed, f"ns_ab/repair_{s['id']}/{tag}", m=W.QwenModel(),
                             ref_resolution=0, crop=False, init_image=name, denoise=dn)
            wf["113"] = {"class_type": "LoadImageMask", "inputs": {"image": mname, "channel": "red"}}
            wf["114"] = {"class_type": "SetLatentNoiseMask", "inputs": {"samples": ["112", 0], "mask": ["113", 0]}}
            wf["40"]["inputs"]["latent_image"] = ["114", 0]
            entry, secs = cl.run(wf, timeout_s=1200)
            item = next(f for f in cl.output_files(entry) if f["filename"].endswith(".png"))
            raw = out / f"raw_{tag}.png"
            cl.download(item, raw)
            ed = Image.open(raw).convert("RGB").resize((pw, ph), Image.LANCZOS)
            fixed = full.copy()
            fixed.paste(Image.composite(ed, panel, paste_mask), (px0, py0))
            f = out / f"{Path(s['asset']).stem}_{s['id']}_{tag}.png"
            fixed.save(f)
            rec = {"scope": "ab", "file": str(f.relative_to(ROOT)).replace("\\", "/"), "seed": seed, "denoise": dn,
                   "comfy_s": round(secs, 1), "url": url, "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
            with log.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            print(json.dumps(rec, ensure_ascii=False), flush=True)


# ---------------------------------------------------------------- 契约检查 + 自动选图
def _lab(a):
    from ns_agent.sheet_intake import _lab as L
    return L(a)


def _tex(a):
    """面料纹理：深色区域内部（腐蚀 9 px，去掉轮廓边）的高频分量标准差。r6 实测：整框拉普拉斯被轮廓边主导，
    平涂候选（v3）比值也≈1；内部高频能分开平涂（0.44–0.79）和有面料纹理（v4 0.74–0.98）"""
    import cv2
    g = cv2.cvtColor(a.astype(np.uint8), cv2.COLOR_RGB2GRAY).astype(np.float64)
    m = cv2.erode((a.max(-1) < 130).astype(np.uint8), np.ones((9, 9), np.uint8))
    hp = g - cv2.GaussianBlur(g, (0, 0), 2.0)
    return float(hp[m > 0].std()) if m.sum() > 50 else 0.0


def _halo(sub: np.ndarray) -> tuple[float, int]:
    """R8 轮廓光晕：深色区（开运算去噪）外沿 2 px 环里，比再往外 3–6 px 环的局部亮度高 20（Lab L）以上的像素占比（白背景不算）。
    r7 标定（24 张袖子候选）：天然左袖 0.144；v4_d92_s1102 0.202（人工选中）；v4_d85_s1102 0.265（头发边浅描边）；v3 平涂 0.30–0.32"""
    import cv2
    sub = sub.astype(np.float32)
    L = cv2.cvtColor(sub.astype(np.uint8), cv2.COLOR_RGB2LAB)[..., 0].astype(np.float32)
    dark = cv2.morphologyEx((sub.max(-1) < 130).astype(np.uint8), cv2.MORPH_OPEN, np.ones((3, 3), np.uint8))
    r1 = cv2.dilate(dark, np.ones((5, 5), np.uint8)) - dark
    r2 = cv2.dilate(dark, np.ones((13, 13), np.uint8)) - cv2.dilate(dark, np.ones((7, 7), np.uint8))
    m1 = (r1 > 0) & ~(sub.min(-1) > 235)
    ref = cv2.blur(np.where(r2 > 0, L, 0), (15, 15)) / (cv2.blur((r2 > 0).astype(np.float32), (15, 15)) + 1e-6)
    return float(((L > ref + 20) & m1).sum() / max(1, m1.sum())), int(m1.sum())


def measure(sheet: np.ndarray, s: dict, px0: int) -> dict:
    p = sheet[:, px0:px0 + (s["_pw"])].astype(np.float32)
    x0, y0, x1, y1 = s.get("target_box") or s["defect_box"]
    tgt = p[y0:y1, x0:x1]
    if s.get("ref_box"):
        rx0, ry0, rx1, ry1 = s["ref_box"]
        ref = p[ry0:ry1, rx0:rx1]
    else:
        mx = s["mirror_x"]
        ref = p[y0:y1, int(2 * mx - x1):int(2 * mx - x0)][:, ::-1]
    nw = ~(tgt > 235).all(-1)
    rw = ~(ref > 235).all(-1)
    light = _sel(tgt, s.get("select", {}))[nw].mean()
    dark = (tgt.max(-1) < 130)[nw].mean()
    sel, rsel = (tgt.max(-1) < 130) & nw, (ref.max(-1) < 130) & rw
    de = float(np.linalg.norm(_lab(tgt[sel]).mean(0) - _lab(ref[rsel]).mean(0))) if sel.any() and rsel.any() else None
    band = []
    for row in tgt:
        nz = np.where(~(row > 235).all(-1))[0]
        if len(nz):
            band.append(row[nz[0]:nz[0] + 4])
    fringe = float(_sel(np.concatenate(band)[None], s.get("select", {}))[0].mean()) if band else None
    tex = _tex(tgt) / max(1e-6, _tex(ref))
    hb = s.get("halo_box") or [x0, y0, x1, y1]
    pad = 20
    hx0, hy0, hx1, hy1 = hb
    h_t = _halo(p[max(0, hy0 - pad):hy1 + pad, max(0, hx0 - pad):hx1 + pad])[0]
    if s.get("mirror_x") is not None:
        mx = s["mirror_x"]
        h_r = _halo(p[max(0, hy0 - pad):hy1 + pad, max(0, int(2 * mx - hx1) - pad):int(2 * mx - hx0) + pad][:, ::-1])[0]
    else:
        h_r = None
    return {"target_light": round(float(light), 4), "target_dark": round(float(dark), 4), "deltaE": None if de is None else round(de, 2),
            "fringe": None if fringe is None else round(fringe, 4), "texture_ratio": round(tex, 3),
            "halo": round(h_t, 4), "halo_ref": None if h_r is None else round(h_r, 4)}


def check(s: dict, write_page: bool = True) -> dict:
    from PIL import Image
    import local_score as LS
    from ns_agent import sheet_intake as SI
    c = {"target_dark_min": 0.85, "target_light_max": 0.03, "de_max": 6.0, "fringe_max": 0.02, "q1_drop_max": 0.005, "intake": True,
         "texture_min": 0.85, "halo_ratio_max": 1.5,
         **s["checks"]}
    out = s["_out"]
    orig_im = Image.open(ROOT / s["asset"]).convert("RGB")
    px0, py0, px1, py1 = panel_xy(orig_im, s["panel"])
    s["_pw"] = px1 - px0
    orig = np.asarray(orig_im).astype(np.int16)
    files = sorted(out.glob(f"{Path(s['asset']).stem}_{s['id']}_*.png"))
    _, fmask = prefill(orig_im.crop((px0, py0, px1, py1)), s)
    from PIL import ImageFilter
    env = np.asarray(fmask.filter(ImageFilter.MaxFilter(s["dilate"])).filter(ImageFilter.GaussianBlur(s["feather"]))) > 0
    envelope = np.zeros(orig.shape[:2], bool)
    envelope[py0:py1, px0:px1] = env
    qd = out / "q1"
    qd.mkdir(exist_ok=True)
    crops = {}
    for f in [ROOT / s["asset"], *files]:
        cp = qd / f"{f.stem}_half.png"
        im = Image.open(f).convert("RGB")
        hx0, _, hx1, _ = panel_xy(im, "half") if s["panel"] != "full" else (0, 0, im.width, im.height)
        im.crop((hx0, 0, hx1, im.height)).save(cp)
        crops[f.name] = str(cp)
    sc = LS.score(crops)["items"]
    cid = s.get("character")

    def q1(n):
        v = [x.get("sims", {}).get(cid) for x in sc.get(n, {}).get("faces") or []]
        v = [x for x in v if x is not None]
        return round(max(v), 4) if v else None
    q1o = q1(Path(s["asset"]).name)
    rows = []
    for f in files:
        a = np.asarray(Image.open(f).convert("RGB")).astype(np.int16)
        diff = np.abs(a - orig).max(-1)
        outside = int(diff[~envelope].max()) if (~envelope).any() else 0
        m = measure(a.astype(np.uint8), s, px0)
        q = q1(f.name)
        intake = SI.check(f, cid, s.get("look")) if c["intake"] and s.get("look") else {"ok": True, "blocking": []}
        ck = {"R1 缺陷区修好": m["target_dark"] >= c["target_dark_min"] and m["target_light"] <= c["target_light_max"],
              "R2 色差 ΔE": m["deltaE"] is not None and m["deltaE"] <= c["de_max"],
              "R3 遮罩外像素不变": outside == 0,
              "R4 身份 Q1 不降": q is not None and q1o is not None and q >= q1o - c["q1_drop_max"],
              "R5 交界无残留": m["fringe"] is not None and m["fringe"] <= c["fringe_max"],
              "R6 入库检查（K-AST-264）": bool(intake.get("ok")),
              "R7 面料纹理（内部高频比）": c["texture_min"] <= m["texture_ratio"] <= 1 / c["texture_min"],
              "R8 轮廓无光晕": m["halo_ref"] is None or m["halo"] <= c["halo_ratio_max"] * max(m["halo_ref"], 1e-3)}
        rows.append({"file": str(f.relative_to(ROOT)).replace("\\", "/"), **m, "outside_max_diff": outside, "q1": q, "q1_orig": q1o,
                     "intake_blocking": intake.get("blocking"), "checks": ck, "pass": all(ck.values())})
    ok = sorted((r for r in rows if r["pass"]), key=lambda r: (abs(1 - r["texture_ratio"]), r["deltaE"]))
    tie = vlm_tiebreak(s, ok[:4]) if len(ok) >= 2 else {"decider": "code", "why": "只有一张或没有全过的候选"}
    if tie.get("pick"):
        ok = [r for r in ok if r["file"] == tie["pick"]] + [r for r in ok if r["file"] != tie["pick"]]
    rep = {"spec": s["id"], "asset": s["asset"], "q1_orig": q1o, "orig_intake": SI.check(ROOT / s["asset"], cid, s.get("look")) if s.get("look") else None,
           "candidates": rows, "picked": ok[0]["file"] if ok else None, "tiebreak": tie,
           "pick_rule": "R1–R8 全过；纹理比（深色区内部高频 目标/参考）最接近 1，其次 ΔE 最小；≥2 张全过时交本地看图模型平局裁决（decider=local_model，看图服务不在 = 维持代码排序）", "at": time.strftime("%Y-%m-%dT%H:%M:%S")}
    (out / "check.json").write_text(json.dumps(rep, ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    if write_page:
        page(s, rep, [r["file"] for r in ok[:3]])
    return rep


def vlm_tiebreak(s: dict, cands: list[dict]) -> dict:
    """≥2 张全过 → 本地看图模型（VQAGATE 路由 ns_agent.vqa.client.generate，只走自家机器 K-REV-V01）看缺陷区放大图选最自然的一张。
    → {decider: local_model, pick, answer} | {decider: code, why}（服务不在 / 输出解析不了）"""
    from PIL import Image
    try:
        from ns_agent.vqa import client as VC
    except Exception as e:  # noqa: BLE001
        return {"decider": "code", "why": f"看图模块不可用：{e!r}"[:200]}
    out = s["_out"] / "tiebreak"
    out.mkdir(parents=True, exist_ok=True)
    x0, y0, x1, y1 = s.get("halo_box") or s["defect_box"]
    ims = []
    for i, r in enumerate(cands):
        im = Image.open(ROOT / r["file"]).convert("RGB")
        px0, _, _, _ = panel_xy(im, s["panel"])
        z = im.crop((px0 + x0 - 40, max(0, y0 - 40), px0 + x1 + 40, y1 + 40))
        z = z.resize((z.width * 2, z.height * 2), Image.LANCZOS)
        f = out / f"cand_{i + 1}.png"
        z.save(f)
        ims.append({"path": str(f), "max_pixels": 400000})
    q = (s.get("tiebreak_question") or "下面几张图是同一处修复的候选（局部放大），按顺序编号 1、2、3…。") +         "判断哪一张修复得最自然：新画的部分和周围衔接无痕、边缘没有发白的描边或光晕、颜色和纹理与对称的另一侧一致、没有伪影。"         "只输出 JSON：{\"best\": <编号>, \"why\": \"一句话\"}"
    req = {"system": "你是严格的图像质检员，只输出 JSON。", "text": q, "images": ims, "spec": f"asset_repair_tiebreak/{s['id']}"}
    try:
        res = VC.generate(req, wait_s=600, label=f"asset_repair tiebreak {s['id']}")
    except Exception as e:  # noqa: BLE001
        return {"decider": "code", "why": f"看图服务调用失败：{e!r}"[:200]}
    if "error" in res:
        return {"decider": "code", "why": f"看图服务：{res['error']}"[:200]}
    import re as _re
    m = _re.search(r"\{.*\}", res.get("text") or "", _re.S)
    try:
        ans = json.loads(m.group(0)) if m else {}
        k = int(ans.get("best"))
        return {"decider": "local_model", "pick": cands[k - 1]["file"], "answer": ans, "model": res.get("model"),
                "candidates": [r["file"] for r in cands]}
    except Exception:  # noqa: BLE001
        return {"decider": "code", "why": "看图模型输出解析不了", "raw": (res.get("text") or "")[:300]}


def page(s: dict, rep: dict, picks: list[str]) -> Path:
    from PIL import Image
    e = html.escape
    pg = ROOT / "data/review_pages" / f"asset_repair_{s['id']}"
    pg.mkdir(parents=True, exist_ok=True)
    rel = lambda p: "../../../" + p  # noqa: E731
    by = {r["file"]: r for r in rep["candidates"]}
    cells, trs = [], []
    for i, f in enumerate([s["asset"], *picks]):
        im = Image.open(ROOT / f).convert("RGB")
        x0, _, x1, _ = panel_xy(im, s["panel"])
        zp = pg / f"panel_{i}.png"
        im.crop((x0, 0, x1, im.height)).save(zp)
        r = by.get(f)
        info = "原图" if not r else (f"{'【自动选中】' if f == rep['picked'] else ''}ΔE {r['deltaE']}｜纹理比 {r['texture_ratio']}｜"
                                    f"缺陷区残留 {r['target_light']:.1%}｜遮罩外最大差 {r['outside_max_diff']}｜Q1 {r['q1']}（原 {r['q1_orig']}）")
        cells.append(f"<td><img src='{zp.name}'><div>{e(Path(f).name)}<br>{e(info)}</div></td>")
        if r:
            trs.append(f"<tr><th>{e(Path(f).name)}</th>" + "".join(f"<td>{'✅' if v else '❌'} {e(k)}</td>" for k, v in r["checks"].items()) + "</tr>")
    doc = (f"<!doctype html><meta charset='utf-8'><title>资产修复 {e(s['id'])}</title><style>body{{font:14px system-ui,'Microsoft YaHei';"
           f"margin:20px;background:#111;color:#ddd}}img{{width:260px;background:#fff}}td,th{{border:1px solid #444;padding:6px;vertical-align:top}}"
           f"table{{border-collapse:collapse;margin-bottom:14px}}div{{font-size:12px;max-width:260px}}</style><h2>资产修复：{e(s['id'])}</h2>"
           f"<p>{e(s.get('note', ''))}</p><p>选图规则：{e(rep['pick_rule'])}。只放契约全过的候选（最多 3 张）。数据：{e(str((s['_out'] / 'check.json').relative_to(ROOT)))}</p>"
           f"<table><tr>{''.join(cells)}</tr></table><table>{''.join(trs)}</table>")
    (pg / "index.html").write_text(doc, encoding="utf-8")
    return pg / "index.html"


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    a = sys.argv
    spec = load_spec(a[2])
    if a[1] == "run":
        run(spec, a[a.index("--url") + 1] if "--url" in a else "http://127.0.0.1:18188")
        r = check(spec)
    else:
        r = check(spec)
    print(json.dumps({"picked": r["picked"], "passed": sum(x["pass"] for x in r["candidates"]), "n": len(r["candidates"])}, ensure_ascii=False))
