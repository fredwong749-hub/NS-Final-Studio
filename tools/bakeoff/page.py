"""BAKEOFF 对照页 + 接触印样 + 契约逐项表（笔记本上跑；读 data/ab/image_bakeoff/{plan,results}.json 与 thumbs/）。

不自动打开：先给总调度审（GEN_CONTRACT §0.3），总调度签 master_review.md 后再 Start-Process。
Q4 质感线（暂定，写进 K 规则待验）：质感综合分 = 平均( z(高频能量), z(纹理标准差), z(log 脸部 Laplacian), -z(油光占比) )，
z 用全部 t2i 有脸样本算；过线 = 综合分 > 现行出图（IMGGEN series10 首帧，项目方判“塑料/油/糊”）的平均值，且油光占比 ≤ 现行出图中位数。
"""
from __future__ import annotations

import html
import json
import math
import random
import shutil
from collections import defaultdict
from pathlib import Path
from statistics import mean, median

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[2]
AB = ROOT / "data/ab/image_bakeoff"
PAGE = ROOT / "data/review_pages/image_bakeoff"


def _font(n):
    for f in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/simhei.ttf"):
        try:
            return ImageFont.truetype(f, n)
        except OSError:
            pass
    return ImageFont.load_default()


# 整组不计分（总调度亲审结论）；单张检测见 refcopy.py + score_srv（栅格 / 格子≈参考 / 文字 ≥5 / 同一人两次）
EXCLUDE_GROUPS = {("krea2_ref", "contract"): "输出 = 参考板拼图（总调度 11-01 亲审 contact_t2i #05）"}


def label_of(mk, mode, models):
    if mk in models:
        return models[mk]["label"]
    return "现行出图（IMGGEN series10 第一轮，带 lin_wan_qi）" if mk == "prod_current" else str(mode)


def texture_scores(items, res):
    keys = ["hf", "texstd", "lap_face", "spec"]
    pool = {k: [] for k in keys}
    for it in items:
        q = res.get(it["id"], {}).get("Q4", {})
        if it["kind"] in ("t2i", "prod") and all(k in q for k in keys):
            for k in keys:
                pool[k].append(math.log1p(q[k]) if k == "lap_face" else q[k])
    st = {k: (mean(v), (sum((x - mean(v)) ** 2 for x in v) / max(1, len(v) - 1)) ** 0.5 or 1) for k, v in pool.items() if len(v) > 2}
    out = {}
    for it in items:
        q = res.get(it["id"], {}).get("Q4", {})
        if len(st) == 4 and all(k in q for k in keys):
            z = lambda k, v: (v - st[k][0]) / st[k][1]  # noqa: E731
            out[it["id"]] = round((z("hf", q["hf"]) + z("texstd", q["texstd"]) + z("lap_face", math.log1p(q["lap_face"])) - z("spec", q["spec"])) / 4, 3)
    prod = [out[i["id"]] for i in items if i["kind"] == "prod" and i["id"] in out]
    prod_spec = [res[i["id"]]["Q4"]["spec"] for i in items if i["kind"] == "prod" and "spec" in res.get(i["id"], {}).get("Q4", {})]
    # 油光线：现行出图中位数实测≈0（V>0.88 且 S<0.22 的冷白镜面高光很少，项目方说的“油”多是暖色大面积柔光）→ 暂取 1% 脸部面积，待人工标注校准
    line = (mean(prod) if prod else 0.0, max(0.01, median(prod_spec) if prod_spec else 0.0))
    return out, line


def build():
    plan = json.loads((AB / "plan.json").read_text(encoding="utf-8"))
    rj = json.loads((AB / "results.json").read_text(encoding="utf-8"))
    res = rj["items"]
    items = [i for i in plan["items"] if i["id"] in res]
    models = plan["models"]
    tex, (tex_line, spec_line) = texture_scores(items, res)
    # 契约 postflight（REFLOCK remote_score.postflight_full，gpu33 CLIP）：Q1–Q7 的通过 / 不过以它为准；
    # score_srv 的 Q2 / Q7 颜色直方图代理只作参考，不参与排名（总调度 11-01 + ITERAUDIT）
    pf = {}
    for f in ("heldout_pf33.json", "all_pf33.json", "rescore_pf33.json"):     # 后者覆盖前者：rescore = 现行契约口径重打（Q5 停用“肢体比例”）
        fp = AB / f
        if fp.exists() and fp.stat().st_size > 2:
            try:
                pf.update(json.loads(fp.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                pass
    for i in items:
        d = pf.get(i["id"]) or {}
        res[i["id"]]["pf"] = {x["id"]: x["status"] for x in d.get("items", [])}
        res[i["id"]]["pf_detail"] = {x["id"]: x["detail"] for x in d.get("items", [])}
    for i in items:
        r = res[i["id"]]
        q4 = r.get("Q4", {})
        r["tex"] = tex.get(i["id"])
        r["Q4_ok"] = None if r["tex"] is None else (r["tex"] > tex_line and q4.get("spec", 1) <= spec_line)
        r["Q5_ok"] = not r.get("Q5")
        r["Q6_ok"] = not r.get("Q6")
    PAGE.mkdir(parents=True, exist_ok=True)
    (PAGE / "thumbs").mkdir(exist_ok=True)
    for i in items:
        s = AB / "thumbs" / f"{i['id']}.jpg"
        if s.exists():
            shutil.copy(s, PAGE / "thumbs" / s.name)
    # 盲测编号：每个（模型, 组）一个随机字母，固定种子
    groups = sorted({(i["model"], i["mode"]) for i in items if i["kind"] in ("t2i", "prod")}, key=str)
    rnd = random.Random(1031)
    codes = [f"#{n:02d}" for n in range(1, len(groups) + 1)]
    rnd.shuffle(codes)
    code = dict(zip(groups, codes))
    egroups = sorted({i["model"] for i in items if i["kind"] == "edit"})
    ecodes = [f"E{n:02d}" for n in range(1, len(egroups) + 1)]
    rnd.shuffle(ecodes)
    ecode = dict(zip(egroups, ecodes))

    # 汇总（每个模型×组）
    agg = defaultdict(lambda: defaultdict(list))
    for i in items:
        r = res[i["id"]]
        if (r.get("ref_copy") or {}).get("copied") or (i["model"], i["mode"]) in EXCLUDE_GROUPS:            # 输出 = 参考板 / 参考拼图：不计分，单列（总调度 11-01 #05）
            agg[(i["model"], i["mode"] + "·输出=参考板（不计分）")]["n"].append(1)
            continue
        k = (i["model"], i["mode"]) if i["kind"] != "edit" else (i["model"], "edit·未比对造型")
        a = agg[k]
        for c, v in (r.get("Q1") or {}).items():
            if v.get("sim") is not None:
                a[f"sim_{c}"].append(v["sim"])
        for q, st in (r.get("pf") or {}).items():         # 契约口径：pass=1，fail=0；na / untested 不进分母、另计
            if st in ("pass", "fail"):
                a[f"{q}_ok"].append(1 if st == "pass" else 0)
            elif st == "untested":
                a["untested"].append(q)
        if r.get("tex") is not None:
            a["tex"].append(r["tex"])
        for f in ("spec", "hf", "texstd", "skin_sat"):
            if f in r.get("Q4", {}):
                a[f].append(r["Q4"][f])
        if r.get("Q2"):
            a["Q2"].append(mean(r["Q2"].values()))
        if r.get("Q7") is not None:
            a["Q7"].append(r["Q7"])
        if r.get("sec"):
            a["sec"].append(r["sec"])
        a["n"].append(1)

    def m(a, k, f="{:.3f}", pct=False):
        v = a.get(k)
        if not v:
            return "—"
        x = mean(v)
        return f"{x * 100:.0f}%" if pct else f.format(x)

    rows = []
    for k, a in agg.items():
        rows.append((k, a))
    rows.sort(key=lambda t: -(mean(t[1]["tex"]) if t[1].get("tex") else -9))
    summary = []
    for (mk, mode), a in rows:
        lab = label_of(mk, mode, models)
        summary.append(dict(model=mk, mode=mode, label=lab, n=len(a["n"]), tex=m(a, "tex"), spec=m(a, "spec", "{:.4f}"), hf=m(a, "hf", "{:.2f}"),
                            sim_lin=m(a, "sim_lin_wan"), Q1=m(a, "Q1_ok", pct=True), Q3=m(a, "Q3_ok", pct=True), Q4=m(a, "Q4_ok", pct=True),
                            Q5=m(a, "Q5_ok", pct=True), Q6=m(a, "Q6_ok", pct=True), Q2=m(a, "Q2_ok", pct=True), Q7=m(a, "Q7_ok", pct=True),
                            untested=len(a.get("untested", [])), sec=m(a, "sec", "{:.0f}s"),
                            license=models[mk].get("license", "") if mk in models else "Qwen Research License（仅非商用）"))
    (AB / "summary.json").write_text(json.dumps(dict(tex_line=tex_line, spec_line=spec_line, rows=summary), ensure_ascii=False, indent=1),
                                     encoding="utf-8")

    # 接触印样
    def contact(kind, keyf, name):
        its = [i for i in items if i["kind"] in kind and i["seed"] in (plan["seeds"][0], None) or (i["kind"] == "prod" and "prod" in kind)]
        shots = sorted({i["shot"] for i in its})
        cols = sorted({keyf(i) for i in its}, key=lambda c: (codes + ecodes).index(c) if c in codes + ecodes else 0)
        tw, thh, pad = 180, 315, 24
        sheet = Image.new("RGB", (60 + len(cols) * tw, pad + len(shots) * (thh + pad)), "white")
        d = ImageDraw.Draw(sheet)
        f = _font(16)
        for ci, c in enumerate(cols):
            d.text((60 + ci * tw + 4, 2), c, fill="black", font=f)
        for si, s in enumerate(shots):
            d.text((4, pad + si * (thh + pad) + 4), s, fill="black", font=f)
            for ci, c in enumerate(cols):
                it = next((i for i in its if i["shot"] == s and keyf(i) == c), None)
                p = PAGE / "thumbs" / f"{it['id']}.jpg" if it else None
                if p and p.exists():
                    im = Image.open(p).resize((tw - 4, thh))
                    sheet.paste(im, (60 + ci * tw, pad + si * (thh + pad)))
        sheet.save(PAGE / name, quality=85)

    contact(("t2i", "prod"), lambda i: code[(i["model"], i["mode"])], "contact_t2i.jpg")
    contact(("edit",), lambda i: ecode[i["model"]], "contact_edit.jpg")

    e = html.escape
    css = """:root{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--card:#fff;--line:#e3e2dc;--ok:#1f7a3a;--bad:#b3261e}
@media (prefers-color-scheme: dark){:root:not([data-theme=light]){--bg:#161615;--fg:#ecebe6;--mut:#a3a29c;--card:#1f1f1d;--line:#34332f;--ok:#6fcf8a;--bad:#ff8a80}}
body{background:var(--bg);color:var(--fg);font:14px/1.5 system-ui,"Microsoft YaHei",sans-serif;margin:0;padding:16px}
h1{font-size:20px}h2{font-size:17px;margin-top:28px}table{border-collapse:collapse;font-size:12px}td,th{border:1px solid var(--line);padding:3px 6px;text-align:right}
th{background:var(--card)}td.l,th.l{text-align:left}.row{display:flex;gap:6px;overflow-x:auto;padding-bottom:6px}
.cell{background:var(--card);border:1px solid var(--line);border-radius:6px;padding:4px;min-width:176px;max-width:176px}
.cell img{width:84px;height:147px;object-fit:cover;border-radius:3px}.ok{color:var(--ok)}.bad{color:var(--bad)}.mut{color:var(--mut);font-size:12px}
details summary{cursor:pointer;font-size:12px}.wrap{overflow-x:auto}"""

    def okc(v):
        return "" if v is None else ("<span class=ok>过</span>" if v else "<span class=bad>不过</span>")

    def cell(i, label):
        r = res[i["id"]]
        sims = " ".join(f"{k[:2]}{v['sim']:.2f}" if v.get("sim") is not None else f"{k[:2]}无脸" for k, v in (r.get("Q1") or {}).items())
        sib = [j for j in items if j["shot"] == i["shot"] and j["model"] == i["model"] and j["mode"] == i["mode"]]
        imgs = "".join(f'<a href="thumbs/{j["id"]}.jpg" target=_blank><img src="thumbs/{j["id"]}.jpg" loading=lazy></a>' for j in sib)
        det = (f"<b>{e(label_of(i['model'], i['mode'], models))}</b> · {e(i['mode'])}<br>"
               f"Q1 {okc(r.get('Q1_ok'))} {e(sims)}<br>Q3 {okc((r.get('Q3') or {}).get('ok'))} 档{(r.get('Q3') or {}).get('got')}/{(r.get('Q3') or {}).get('expect')}<br>"
               f"Q4 {okc(r.get('Q4_ok'))} 质感{r.get('tex')} 油{r.get('Q4', {}).get('spec')} 高频{r.get('Q4', {}).get('hf')}<br>"
               f"Q5 {okc(r.get('Q5_ok'))} {e(','.join(r.get('Q5') or []))} · Q6 {okc(r.get('Q6_ok'))}<br>"
               f"契约 postflight：{e(' '.join(f'{k}:{v}' for k, v in sorted((r.get('pf') or {}).items())) or '未测')}<br>"
               f"（直方图代理，不排名）Q2 {e(str(r.get('Q2')))} · Q7 {r.get('Q7')}<br>耗时 {r.get('sec')}s · 参考 {e(','.join(i['ref_roles']) or '无')}"
               + (f" · 槽位不足去掉 {e(','.join(i['dropped']))}" if i.get("dropped") else ""))
        return f'<div class=cell><b>{e(label)}</b><br>{imgs}<details><summary>揭晓模型与分数</summary><div class=mut>{det}</div></details></div>'

    parts = [f"<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content='width=device-width,initial-scale=1'>"
             f"<title>出图模型对决</title><style>{css}</style></head><body>",
             "<h1>出图模型真人质感对决（BAKEOFF 第 1 轮）</h1>",
             f"<p class=mut>协议见 docs/ep02_iter/image_bakeoff.md。每格是一个盲测编号（模型×组），两张是两个 seed；点“揭晓”看模型名和分数。"
             f"排名表的 Q1–Q7 过线率取契约 postflight（REFLOCK 实现，gpu33 CLIP；na / 未测不进分母）。"
             f"*Q4 契约线（整图 Laplacian ≥175）留出复核判对率 0.50–0.59、AUC 0.41（data/review_pages/asset_reflock/heldout_bakeoff.json），只作参考；"
             f"质感排序用 BAKEOFF 脸部指标综合分（脸部肤色区高频 / 纹理标准差 / Laplacian − 油光，z 分数），同一留出集上脸部 Laplacian AUC 0.93、高频 0.83（只有 2 个反例，待扩充）。"
             f"score_srv 的 Q2 / Q7 颜色直方图代理只在展开里给参考，不参与排名。</p>",
             "<h2>一、出图（同一镜头横排比较）</h2>"]
    for sid in sorted({i["shot"] for i in items if i["kind"] in ("t2i", "prod")}):
        its = [i for i in items if i["shot"] == sid and i["kind"] in ("t2i", "prod")]
        firsts = {}
        for i in its:
            firsts.setdefault((i["model"], i["mode"]), i)
        cat = its[0]["cat"]
        parts.append(f"<h3>{e(sid)} · {e(cat)}（源 {e(its[0]['src'])}，景别 {e(its[0]['size'])}）</h3><div class=row>")
        for k in sorted(firsts, key=lambda k: code[k]):
            parts.append(cell(firsts[k], code[k]))
        parts.append("</div>")
    parts.append("<h2>二、编辑能力（同一张不合格首帧 ep05-S5）</h2>")
    for eid in sorted({i["shot"] for i in items if i["kind"] == "edit"}):
        its = [i for i in items if i["shot"] == eid]
        firsts = {}
        for i in its:
            firsts.setdefault(i["model"], i)
        parts.append(f"<h3>{e(eid)} · {e(its[0]['cat'])}</h3><p class=mut>{e(its[0]['prompt'][:160])}</p><div class=row>")
        parts.append('<div class=cell><b>原图</b><br><img src="thumbs/src_edit.jpg"></div>')
        for k in sorted(firsts, key=lambda k: ecode[k]):
            parts.append(cell(firsts[k], ecode[k]))
        parts.append("</div>")
    parts.append("<h2>三、排名与契约逐项（按质感综合分排序）</h2><details><summary>展开（含模型名）</summary><div class=wrap><table><tr>"
                 + "".join(f"<th class=l>{h}</th>" if n < 2 else f"<th>{h}</th>" for n, h in enumerate(
                     ["模型", "组", "张数", "质感综合（BAKEOFF 脸部指标）", "油光", "高频", "林晚余弦(ref2va)", "Q1过", "Q2过", "Q3过", "Q4过*", "Q5过", "Q6过", "Q7过", "未测项", "单张耗时", "许可"]))
                 + "</tr>")
    for s in summary:
        parts.append("<tr>" + "".join(f"<td class=l>{e(str(s[k]))}</td>" if n < 2 else f"<td>{e(str(s[k]))}</td>" for n, k in enumerate(
            ["label", "mode", "n", "tex", "spec", "hf", "sim_lin", "Q1", "Q2", "Q3", "Q4", "Q5", "Q6", "Q7", "untested", "sec", "license"])) + "</tr>")
    parts.append("</table></div></details>")
    parts.append(f"<p class=mut>参考互相余弦 {e(json.dumps(rj.get('ref_cross'), ensure_ascii=False))}；项目方母版 vs IMGGEN 林晚参考 {rj.get('master_vs_ref2va_lin_wan')}</p>")
    parts.append("<p class=mut>接触印样：contact_t2i.jpg / contact_edit.jpg（同目录）</p></body></html>")
    src = AB / "thumbs" / "src_edit.jpg"
    if src.exists():
        shutil.copy(src, PAGE / "thumbs" / "src_edit.jpg")
    (PAGE / "index.html").write_text("\n".join(parts), encoding="utf-8")
    print("page", PAGE / "index.html", len(items), "items")
