"""REFLOCK 本地审阅页：data/review_pages/asset_reflock/index.html（+ 契约逐项结果表 contract_table.md、接触印样 contact_sheet.jpg）。

    .venv/Scripts/python.exe tools/gen_contract/reflock_page.py
"""
from __future__ import annotations

import html
import json
import os
import statistics as S
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "services" / "agent"))
from ns_agent import asset_refs as AR  # noqa: E402
from ns_agent.gen_contract import report as RP  # noqa: E402

PAGE = ROOT / "data/review_pages/asset_reflock"
VAL = ROOT / "data/pipeline/runs/series10_v1/images/reflock_val/v9"   # 第二轮：v9 配方（总调度 11-01）
E = html.escape
VLAB = {"vR": "有资产参考（REFLOCK 槽位）", "vRb": "有资产参考 + 双人两脸各一槽", "vN": "无资产参考（只挂脸）", "asset": "有资产参考", "noasset": "无资产参考"}
MARK = {"pass": ("通过", "ok"), "fail": ("不通过", "bad"), "na": ("不适用", "na"), "untested": ("未测", "bad")}


def rel(p) -> str:
    return os.path.relpath(ROOT / p, PAGE).replace("\\", "/")


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def table(items):
    rows = "".join(f"<tr><td>{E(i['id'])}</td><td>{E(i['title'])}</td><td class={MARK.get(i['status'], ('', ''))[1]}>"
                   f"{MARK.get(i['status'], (i['status'], ''))[0]}</td><td>{E(i.get('detail') or '')}</td></tr>" for i in items)
    return f"<table><tr><th>项</th><th>内容</th><th>结果</th><th>说明 / 数字</th></tr>{rows}</table>"


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    jobs = jl(VAL / "jobs.json", [])
    st = jl(VAL / "state.json", {})
    cal = jl(PAGE / "calibration.json", {})
    cal2 = jl(PAGE / "calibration_imgfix.json", {}) or {}
    q4rows = "".join(f"<tr><td>{E(r['key'])}</td><td>{'认可' if r['label'] == 'good' else '不可接受（v0）'}</td><td>{r['lap_full']}</td>"
                     f"<td>{r['sat_mean']}</td><td class={'ok' if r['pass'] else 'bad'}>{'过' if r['pass'] else '不过'}</td></tr>"
                     for r in cal2.get("q4_full") or [])
    audit = jl(PAGE / "look_audit.json", {})
    revs = jl(ROOT / "data/pipeline/runs/series10_v1/assets/look_revisions.json", {})
    out = []
    # ---------------- 验证：每镜 有资产 vs 无资产
    md_rows, sheet_entries, comp = [], [], []
    shots = []
    for j in jobs:
        if j["shot"] not in shots:
            shots.append(j["shot"])
    for sid in shots:
        js = [j for j in jobs if j["shot"] == sid]
        ja = next((j for j in js if j["variant"] in ("asset", "vR")), None)
        rec = (ja or {}).get("asset_refs") or {}
        out.append(f"<h3>{E(sid)}</h3>")
        out.append("<div class=refs><b>本镜锁定的参考（按槽位）</b>：" + "".join(
            f"<figure><img src='{rel(s['file'])}'><figcaption>图{s['index']}·{E(s['kind'])}<br>{E('、'.join(s['labels']))}</figcaption></figure>"
            for s in rec.get("slots") or []) + "</div>")
        out.append("<p class=mut>提示词里的参考标注：" + E("".join(s.get("line", "") for s in rec.get("slots") or [])) + "</p>")
        out.append("<div class=grid>")
        for j in js:
            s = st.get(j["id"]) or {}
            pf = s.get("postflight") or {}
            q2 = next((i for i in pf.get("items", []) if i["id"] == "Q2"), {})
            q1 = next((i for i in pf.get("items", []) if i["id"] == "Q1"), {})
            rows = (q2.get("evidence") or {}).get("rows") or []
            q2s = "；".join(f"{r['label']} {r['clip']:.3f}" for r in rows)
            img = j.get("out") or s.get("file") or ""
            if img and (ROOT / img).exists():
                out.append(f"<figure class=card><img src='{rel(img)}'><figcaption><b>{VLAB.get(j['variant'], j['variant'])}</b> seed {j['seed']}"
                           f"<br>契约：{'通过' if pf.get('ok') else '不通过：' + E(','.join(pf.get('blocking') or []))}"
                           f"<br>身份：{E(q1.get('detail') or '')}<br>造型 Q2：{E(q2s)}</figcaption></figure>")
                md_rows.append({"subject": f"{j['id']}（{VLAB.get(j['variant'], j['variant'])}）", "image": img,
                                "pre": s.get("preflight"), "post": pf or None})
                sheet_entries.append({"label": f"{j['id']} {VLAB.get(j['variant'], j['variant'])}  契约{'通过' if pf.get('ok') else '不通过'}  {q2s[:60]}",
                                      "image": img, "refs": j["refs"]})
                for r in rows:
                    comp.append({"shot": sid, "variant": j["variant"], "label": r["label"], "zone": r.get("zone"), "clip": r["clip"]})
        out.append("</div>")
    # Q2 对比汇总
    agg = {}
    for c in comp:
        agg.setdefault((c["shot"], c["label"]), {}).setdefault(c["variant"], []).append(c["clip"])
    cmp_rows = "".join(
        f"<tr><td>{E(k[0])}</td><td>{E(k[1])}</td><td>{S.mean(v.get('asset', [0])):.3f}</td><td>{S.mean(v.get('noasset', [0])):.3f}</td>"
        f"<td>{S.mean(v.get('asset', [0])) - S.mean(v.get('noasset', [0])):+.3f}</td></tr>" for k, v in agg.items())
    val_html = "\n".join(out)
    md = RP.markdown(md_rows, "契约逐项结果表（REFLOCK 验证 3 镜 × 2 seed × 有 / 无资产参考）")
    (PAGE / "contract_table.md").write_text(md, encoding="utf-8")
    cs = RP.contact_sheet(sheet_entries, PAGE / "contact_sheet.jpg") if sheet_entries else None
    # 标定
    cal_rows = "".join(f"<tr><td>{E(k)}</td><td>{E(r['case'])}</td><td>{'正例' if r['positive'] else '反例'}</td><td>{r['clip']:.3f}</td><td>{r['hist']:.3f}</td></tr>"
                       for k in ("shoes", "skirt") for r in cal.get(k, []))
    tex = cal.get("texture") or []
    tex_s = ""
    if tex:
        def pct(key, q):
            xs = sorted(t[key] for t in tex if key in t)
            return xs[int(q * (len(xs) - 1))] if xs else None
        tex_s = "；".join(f"{k} p10 {pct(k, .1)} / 中位 {pct(k, .5)} / p90 {pct(k, .9)}" for k in ("lap_var", "hf_ratio", "sat_p95", "specular"))
    # 审计
    iss = audit.get("issues") or []
    lv = {"block": "bad", "warn": "warn", "info": "na"}
    aud_rows = "".join(f"<tr><td class={lv.get(i['level'], '')}>{E(i['level'])}</td><td>{E(i['kind'])}</td><td>{E(i['where'])}</td><td>{E(i['detail'])}</td>"
                       f"<td>{E(i.get('fix') or '')}</td></tr>" for i in iss)
    rev_rows = "".join(f"<tr><td>{E(r['shot'])}</td><td>{E(r['proposal'].get('choice', ''))}</td><td>{E(r['proposal'].get('why', ''))}</td>"
                       f"<td>{E(r['proposal'].get('registry_note', ''))}</td><td>{'通过' if r['ok'] else E(str(r['checks']))}</td></tr>"
                       for r in revs.get("revisions") or [])
    # 资产来源
    inv = AR.look_inventory("series10_v1")
    stc = {"wardrobe": ("衣橱产品图", "ok"), "sheet_only": ("仅设定图", "warn"), "missing": ("资产缺图", "bad"), "identity": ("身份", "na")}
    inv_rows = "".join(f"<tr><td>{E(lk['name'])}</td><td>{E(lk['look'])}</td><td>{E(p['label'])}</td><td>{E(p['slot'])}</td>"
                       f"<td class={stc[p['status']][1]}>{stc[p['status']][0]}</td><td>{E(p['item_id'] or '')}</td>"
                       f"<td>{'<img class=th src=' + chr(39) + rel(p['item_file']) + chr(39) + '>' if p['item_file'] else ''}</td></tr>"
                       for lk in inv for p in lk["parts"])
    doc = f"""<!doctype html><html lang=zh><head><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1">
<title>资产参考锁定</title><style>
:root{{--bg:#fafaf8;--fg:#1d1d1b;--mut:#6b6b66;--line:#ddd;--ok:#1f7a3a;--bad:#b3261e;--warn:#9a6700;--card:#fff}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#161615;--fg:#ecece8;--mut:#a3a39c;--line:#3a3a37;--ok:#5cc27a;--bad:#ff8a80;--warn:#e3b341;--card:#1f1f1d}}}}
body{{background:var(--bg);color:var(--fg);font:15px/1.6 system-ui,"Microsoft YaHei",sans-serif;margin:0;padding:16px;max-width:1500px}}
h1{{font-size:22px}} h2{{font-size:18px;border-top:1px solid var(--line);padding-top:14px;margin-top:28px}} h3{{font-size:16px}}
table{{border-collapse:collapse;width:100%;margin:8px 0;font-size:13px}} td,th{{border:1px solid var(--line);padding:4px 6px;vertical-align:top;text-align:left}}
.ok{{color:var(--ok);font-weight:600}} .bad{{color:var(--bad);font-weight:600}} .warn{{color:var(--warn);font-weight:600}} .na{{color:var(--mut)}} .mut{{color:var(--mut);font-size:13px}}
.grid{{display:flex;flex-wrap:wrap;gap:10px}} .card{{background:var(--card);border:1px solid var(--line);padding:6px;margin:0;width:300px}} .card img{{width:100%}}
.refs figure{{display:inline-block;margin:4px;width:150px;vertical-align:top;font-size:12px}} .refs img{{width:150px;max-height:220px;object-fit:contain;background:#fff}}
img.th{{height:60px}} .wrap{{overflow-x:auto}}
</style></head><body>
<h1>资产参考锁定（REFLOCK）· 生成契约</h1>
<p>项目方原话：“关于女主角鞋子的一致性也全部错了……你要在 image 里面让它知道，这个女孩要穿这个鞋子、穿这个衣服、戴这个饰品等等，然后才能锁定一致性。”</p>
<p>现在的做法：每镜出图前，由系统解析器 <code>ns_agent.asset_refs</code> 按 Shot Spec（在画角色、造型 id、景别）选出必须锁定的参考图：身份脸 &gt; 本镜造型设定图（去头）&gt; 景别可见的单品图（鞋可见时鞋最先）&gt; 场景。槽位不够时拼成参考板，提示词逐一写“图N是…必须完全一致”。没有图的部件列为“资产缺图”，阻断出图，不再用文字代替。所有出图提交前必须过契约 preflight（I1–I10），出图后必须过 postflight（Q1–Q7）。</p>
<h2>验证：3 镜 × 2 seed，有资产参考 vs 无资产参考（gpu33:1）</h2>
<p class=mut>两组用的是同一份编译器正文、同一个 S★ 后缀、同一组 seed，唯一的差别是参考图：有资产参考组按上面的槽位规划；无资产参考组是旧做法，只挂身份脸。Q2 是 CLIP 区域相似度（单品按所在区域滑窗取最高值）。逐项结果表见 contract_table.md，接触印样见 contact_sheet.jpg。</p>
<div class=wrap><table><tr><th>镜</th><th>参考项</th><th>有资产参考</th><th>无资产参考</th><th>差</th></tr>{cmp_rows}</table></div>
{val_html}
{f"<p><a href='contact_sheet.jpg'>接触印样 contact_sheet.jpg</a>　<a href='contract_table.md'>契约逐项结果表 contract_table.md</a></p>" if cs else ""}
<h2>Q4 质感标定（总调度认可集：v9 / v10 / v10L 可接受，v0 塑料、糊）——判对 {E(str(cal2.get("q4_accuracy", "")))}</h2>
<div class=wrap><table><tr><th>图</th><th>标签</th><th>整图 Laplacian（宽 768）</th><th>平均饱和度</th><th>判定（线 175）</th></tr>{q4rows}</table></div>
<p class=mut>Q2 第二轮：认可集里只靠文字的 v3 / v0 本身就穿对了大部分衣服，手、颈、上身、腰、全身区的单品 CLIP 分不开（0.64–0.89 混在一起）→ 这些区只记录不判；只判已用已知答案图标定过的鞋（≥0.775）、下装（≥0.83）、整套设定图（≥0.74）。</p>
<h2>阈值标定（Q2，已知答案的图）</h2>
<div class=wrap><table><tr><th>参考</th><th>样本</th><th>类别</th><th>CLIP</th><th>直方图</th></tr>{cal_rows}</table></div>
<p class=mut>线：鞋 0.775、短裙 0.83，其它区域暂定 0.80；颜色直方图对透明鞋无效，只记录不判。质感分布（现有 series10 首帧中心区域）：{E(tex_s)}</p>
<h2>剧本 / 造型审计（系统剧本 series10）</h2>
<div class=wrap><table><tr><th>级别</th><th>类型</th><th>位置</th><th>说明</th><th>修法</th></tr>{aud_rows}</table></div>
<h3>写作模型修订提案（abliteration，关推理；台词不动）</h3>
<div class=wrap><table><tr><th>镜</th><th>选择</th><th>理由</th><th>登记修改</th><th>机器校验</th></tr>{rev_rows}</table></div>
<h2>资产来源：每套造型每个部件</h2>
<div class=wrap><table><tr><th>角色</th><th>造型</th><th>部件</th><th>槽</th><th>来源</th><th>单品 id</th><th>图</th></tr>{inv_rows}</table></div>
</body></html>"""
    (PAGE / "index.html").write_text(doc, encoding="utf-8")
    print(PAGE / "index.html")


if __name__ == "__main__":
    main()
