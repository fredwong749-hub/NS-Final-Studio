"""BAKEOFF：给 REFLOCK 的 3 处阈值做留出复核（docs/ITERATION_PROTOCOL.md §4：复核方 ≠ 标定方、不用标定时的同一批图）。

  sheets  出 3 张盲测接触印样（只有编号，不写模型 / 分数）给总调度定标签：
          Q4 质感（可接受 / 塑料糊）、Q2 鞋（是不是本镜登记那双）、Q5 手（正常 / 不正常）
          → data/review_pages/asset_reflock/heldout_{q4,q2shoe,q5hand}.jpg + heldout_index.json（编号 → 图路径）
  score   读 heldout_labels.json（总调度给的标签 {编号: 1/0}）+ 阈值判定 → 每项样本数、判对率、误判图
          → data/review_pages/asset_reflock/heldout_bakeoff.json
标签只来自总调度 / 项目方；BAKEOFF 不用自己的主观判断（REFLOCK 11-01 要求）。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
AB = ROOT / "data/ab/image_bakeoff"
OUT = ROOT / "data/review_pages/asset_reflock"
FIX = ROOT / "data/pipeline/runs/series10_v1/images/imgfix"
sys.path.insert(0, str(ROOT / "services/agent"))


def font(n):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(f, n)
        except OSError:
            pass
    return ImageFont.load_default()


def grid(tiles, name, tw=300, th=525, cols=6, title=""):
    rows = (len(tiles) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, 40 + rows * (th + 30)), "white")
    d = ImageDraw.Draw(sheet)
    d.text((8, 8), title, fill="black", font=font(20))
    for k, (code, im) in enumerate(tiles):
        x, y = (k % cols) * tw, 40 + (k // cols) * (th + 30)
        im = im.copy()
        im.thumbnail((tw - 6, th))
        sheet.paste(im, (x + 3, y))
        d.rectangle((x + 3, y, x + 3 + 26 * max(2, len(code)) // 2 + 20, y + 28), fill="white")
        d.text((x + 6, y + 2), code, fill="black", font=font(22))
    sheet.save(OUT / name, quality=88)


def sheets():
    OUT.mkdir(parents=True, exist_ok=True)
    plan = json.loads((AB / "plan.json").read_text(encoding="utf-8"))
    items = {i["id"]: i for i in plan["items"]}
    idx = {"q4": {}, "q2shoe": {}, "q5hand": {}}
    # Q4：imgfix 留出变体（REFLOCK 没用来标定的）+ BAKEOFF 三个模型的契约组第 1 个 seed
    q4 = []
    for shot in ("ep01-S5", "ep05-S5", "ep05-S7", "ep09-S2"):
        for v in ("v10H", "v3", "vR", "vN", "v1", "v2", "v4"):
            for f in (FIX / shot / f"{v}_post.png", FIX / shot / f"{v}.png"):
                if f.exists():
                    q4.append(str(f.relative_to(ROOT)).replace("\\", "/"))
                    break
    for f in sorted((AB / "full").glob("*_contract_20261031.jpg")):
        if any(f"_{m}_" in f.name for m in ("qwen21_sstar", "klein4b", "qedit2511")) and "_base_" not in f.name:
            q4.append(str(f.relative_to(ROOT)).replace("\\", "/"))
    tiles = []
    for k, p in enumerate(q4, 1):
        code = f"T{k:02d}"
        idx["q4"][code] = p
        tiles.append((code, Image.open(ROOT / p).convert("RGB")))
    grid(tiles, "heldout_q4.jpg", title="Q4 质感留出集：每张请判 1=可接受 / 0=塑料或糊（只看皮肤与清晰度，不看构图内容）")
    # Q2 鞋：中全景 B4（鞋可见）所有组的下半身裁切 + 登记鞋图
    shoe_ref = ROOT / "assets/characters/lin_wan/items/shoes/S01_side45_s0.png"
    tiles = [("参考鞋", Image.open(shoe_ref).convert("RGB"))] if shoe_ref.exists() else []
    k = 0
    for f in sorted((AB / "full").glob("B4_*.jpg")):
        im = Image.open(f).convert("RGB")
        W, H = im.size
        k += 1
        code = f"S{k:02d}"
        idx["q2shoe"][code] = str(f.relative_to(ROOT)).replace("\\", "/")
        tiles.append((code, im.crop((0, int(H * 0.55), W, H))))
    grid(tiles, "heldout_q2shoe.jpg", th=330, title="Q2 鞋留出集：每张请判 1=就是参考鞋（12cm 透明侧开细高跟）/ 0=不是或看不清")
    # Q5 手：林晚在画、手入画的契约组 / face 组（近景、中近景、中全景）
    k = 0
    tiles = []
    for f in sorted((AB / "full").glob("B[1234]_*_2026103*.jpg")):
        it = items.get(f.stem)
        if not it or it["mode"] not in ("contract", "face"):
            continue
        k += 1
        code = f"H{k:02d}"
        idx["q5hand"][code] = str(f.relative_to(ROOT)).replace("\\", "/")
        tiles.append((code, Image.open(f).convert("RGB")))
    grid(tiles, "heldout_q5hand.jpg", title="Q5 手留出集：每张请判 1=手正常 / 0=手畸形（多指、缺指、扭曲、指甲长成爪）")
    (OUT / "heldout_index.json").write_text(json.dumps(idx, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: len(v) for k, v in idx.items()}, OUT)


def score():
    from ns_agent.gen_contract import postflight as PF
    from ns_agent.gen_contract import cfg
    th = cfg().get("image_thresholds") or {}
    idx = json.loads((OUT / "heldout_index.json").read_text(encoding="utf-8"))
    lab = json.loads((OUT / "heldout_labels.json").read_text(encoding="utf-8"))
    pf = json.loads((AB / "postflight.json").read_text(encoding="utf-8")) if (AB / "postflight.json").exists() else {}
    res = json.loads((AB / "results.json").read_text(encoding="utf-8"))["items"]
    # REFLOCK 服务器版 postflight（tools/gen_contract/remote_score.postflight_full，gpu33 3090 上跑 CLIP）的结果优先
    p33 = AB / "heldout_pf33.json"
    if p33.exists():
        for k, v in json.loads(p33.read_text(encoding="utf-8")).items():
            q2 = next((x for x in v.get("items", []) if x["id"] == "Q2"), {})
            q4 = next((x for x in v.get("items", []) if x["id"] == "Q4"), {})
            pf[k] = {**v, "local": {"Q2": (q2.get("evidence") or {}).get("rows"), "Q4": q4.get("evidence") or None}}
    out = {"source": "BAKEOFF heldout.py", "thresholds": {k: th.get(k) for k in ("Q2_outfit", "Q4_texture", "Q5_hands")}}

    def stem(p):
        return Path(p).stem

    def summary(name, rows):
        n = [r for r in rows if r["label"] is not None and r["pred"] is not None]
        ok = [r for r in n if r["label"] == r["pred"]]
        out[name] = {"n": len(n), "acc": round(len(ok) / len(n), 3) if n else None, "unlabeled": len(rows) - len(n),
                     "wrong": [r for r in n if r["label"] != r["pred"]], "rows": rows}

    t4 = th.get("Q4_texture") or {}
    rows = []
    for code, p in idx["q4"].items():
        q = (pf.get(stem(p), {}).get("local") or {}).get("Q4")
        if q is None:                            # 不用 CLIP：本机直接调 REFLOCK 的 texture()，脸框取 score_srv 的 remote（imgfix 图没有 → 中心区）
            from PIL import Image as _I
            fs = (res.get(stem(p), {}).get("remote") or {}).get("faces") or []
            q = PF.texture(_I.open(ROOT / p).convert("RGB"), fs[0]["bbox"] if fs else None)
        pred = None if q.get("error") else int(q["lap_full"] >= t4.get("lap_full_min", 0) and q["sat_mean"] <= t4.get("sat_mean_max", 1)
                                               and q["specular"] <= t4.get("specular_max", 1))
        pred2 = None if q.get("error") else int(q["lap_full"] >= t4.get("lap_full_min", 0) and q["sat_mean"] <= t4.get("sat_mean_max", 1))
        rows.append({"code": code, "path": p, "label": lab.get("q4", {}).get(code), "pred": pred, "pred_lap_sat": pred2,
                     "lap_full": q.get("lap_full"), "sat_mean": q.get("sat_mean"), "specular": q.get("specular")})
    summary("Q4", rows)
    summary("Q4_lap_sat_only", [{**r, "pred": r["pred_lap_sat"]} for r in rows])   # REFLOCK 11-01 口径：只判 lap_full + sat_mean
    need = ((th.get("Q2_outfit") or {}).get("clip_item_by_zone") or {}).get("feet", 0.775)
    rows = []
    for code, p in idx["q2shoe"].items():
        q2 = (pf.get(stem(p), {}).get("local") or {}).get("Q2") or []
        feet = [r for r in q2 if r.get("zone") == "feet"]
        clip = max((r["clip"] for r in feet), default=None)
        rows.append({"code": code, "path": p, "label": lab.get("q2shoe", {}).get(code), "pred": None if clip is None else int(clip >= need),
                     "clip": clip})
    summary("Q2_shoe", rows)
    rows = []
    for code, p in idx["q5hand"].items():
        d = pf.get(stem(p), {})
        q5 = next((x for x in d.get("items", []) if x["id"] == "Q5"), None)
        rows.append({"code": code, "path": p, "label": lab.get("q5hand", {}).get(code),
                     "pred": None if q5 is None or q5["status"] == "untested" else int(q5["status"] == "pass"),
                     "flags": res.get(stem(p), {}).get("Q5")})
    summary("Q5_hand", rows)
    (OUT / "heldout_bakeoff.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print({k: (v["n"], v["acc"]) for k, v in out.items() if isinstance(v, dict) and "acc" in v})


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    {"sheets": sheets, "score": score}[sys.argv[1]]()
