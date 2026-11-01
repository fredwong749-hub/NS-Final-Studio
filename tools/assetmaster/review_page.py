"""ASSETMASTER 本地审阅页：data/review_pages/series10_assets_v2/index.html
每角色 × 每造型的单品：已有图 / 新候选（暂定标★、质检结果）/ 缺图；造型设定图；项目方上传单品；剧本矛盾。
只生成文件，不打开（先交总调度审）。"""
from __future__ import annotations

import html
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PAGE = ROOT / "data" / "review_pages" / "series10_assets_v2" / "index.html"
NAMES = {"lin_wan": "林晚", "gu_chen": "顾沉", "chen_yu": "陈宇", "ch_a_lan": "阿岚"}
SLOT_ZH = {"outfit": "服装", "shoes": "鞋", "legwear": "袜", "jewelry": "首饰", "accessory": "配件", "piercing": "穿孔饰品",
           "body_mark": "纹身/疤", "nails": "指甲", "makeup": "妆容", "hair": "发型", "prop": "道具"}


def src(p: str) -> str:
    return html.escape(os.path.relpath(ROOT / p, PAGE.parent).replace("\\", "/"))


def img(p: str, cap: str = "", star=False, bad=False) -> str:
    cls = "star" if star else ("bad" if bad else "")
    return (f'<figure class="{cls}"><a href="{src(p)}" target="_blank"><img loading="lazy" src="{src(p)}"></a>'
            f'<figcaption>{html.escape(cap)}</figcaption></figure>')


def main() -> int:
    inv = json.loads((ROOT / "data/assetmaster/inventory.json").read_text(encoding="utf-8"))
    gen = json.loads((ROOT / "data/assetmaster/items.json").read_text(encoding="utf-8")) if (ROOT / "data/assetmaster/items.json").exists() else {}
    by_name = {(v["char"], v["name"]): v for v in gen.values()}
    J = lambda p: json.loads((ROOT / p).read_text(encoding="utf-8")) if (ROOT / p).exists() else {}
    flux_items, flux_scenes, flux_sheets = J("data/assetmaster/flux/items.json"), J("data/assetmaster/flux/scenes.json"), J("data/assetmaster/flux/sheets.json")
    final, qsheets = J("data/assetmaster/final_choice.json"), J("data/assetmaster/sheets_v2.json")
    qscenes = J("data/pipeline/runs/series10_v1/images/scenes/scenes.json")
    H = ["<!doctype html><meta charset=utf-8><title>series10 资产清单 v2</title><style>",
         "body{font:14px system-ui,'Microsoft YaHei';margin:16px;background:#f6f6f4;color:#222}h2{margin-top:28px}"
         "table{border-collapse:collapse;width:100%;background:#fff}td,th{border:1px solid #ddd;padding:6px;vertical-align:top}"
         "figure{display:inline-block;margin:3px;width:150px}figure img{width:150px;height:262px;object-fit:contain;background:#eee}"
         "figcaption{font-size:11px;color:#555}.star{outline:3px solid #2a8;}.bad{outline:3px solid #c33}"
         ".tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:12px}.有图{background:#cfe9d6}.缺图{background:#f6d0d0}"
         "td.sheets figure{width:330px}td.sheets figure img{width:330px;height:186px}.待确认,.图不合格{background:#f6e7c0}.身份参考覆盖{background:#dde4f0}</style>",
         "<h1>series10 资产清单 v2（ASSETMASTER，待总调度审）</h1>",
         f"<p>盘点：{html.escape(json.dumps(inv['summary'], ensure_ascii=False))}；剧本问题："
         f"{html.escape(json.dumps(inv['issue_counts'], ensure_ascii=False))}。★ = 自动选的暂定（postflight：0 人脸、0 文字、清晰度），"
         "红框 = 质检不过。候选模型：Qwen-Image 2.1 + leica_sstar（Klein 到位后补对比版）。</p>"]
    H.append("<h2>场景底图：Qwen（IMGGEN）vs FLUX.2 klein 4B</h2><table><tr><th>场景</th><th>Qwen</th><th>FLUX</th></tr>")
    for sid in sorted(set(flux_scenes) | set(qscenes)):
        fin = (final.get("scenes", {}).get(sid) or {}).get("file")
        qa = [img(v["file"], k, star=v["file"] == fin) for k, v in (qscenes.get(sid) or {}).items()
              if isinstance(v, dict) and v.get("file") and k not in ("row", "chosen") and v.get("ok", True)]
        fa = [img(v["file"], k, star=v["file"] == fin, bad=not v.get("ok")) for k, v in sorted((flux_scenes.get(sid) or {}).get("cands", {}).items()) if v.get("file")]
        H.append(f"<tr><td>{sid}<br><small>{html.escape((final.get('scenes', {}).get(sid) or {}).get('why', ''))}</small></td><td>{''.join(qa)}</td><td>{''.join(fa)}</td></tr>")
    H.append("</table>")
    H.append("<h2>造型版设定图 v2：旧版 / Qwen v2 / FLUX（★ = 最终暂定；身份 Q1 不过的不进候选）</h2><table>")
    olds = {(s["char"], s["look"]): s.get("file") for s in inv["sheets"]}
    for key in sorted(set(qsheets) | set(flux_sheets)):
        ch, lk = key.rsplit("_look", 1)
        fin = (final.get("sheets", {}).get(key) or {}).get("file")
        cells = [img(olds[(ch, lk)], "旧版") if olds.get((ch, lk)) else ""]
        for sd, v in (qsheets.get(key) or {}).items():
            if isinstance(v, dict) and v.get("file") and sd != "chosen":
                cells.append(img(v["file"], f"Qwen s{sd} sim{v.get('sim')}", star=v["file"] == fin, bad=v.get("ok") is False))
        for k, v in sorted((flux_sheets.get(key) or {}).get("cands", {}).items()):
            if v.get("file"):
                cells.append(img(v["file"], f"FLUX {k} sim{v.get('sim')}", star=v["file"] == fin, bad=v.get("ok") is False))
        H.append(f"<tr><td>{NAMES.get(ch, ch)} 造型{lk}<br><small>{html.escape((final.get('sheets', {}).get(key) or {}).get('why', ''))}</small></td><td class=sheets>{''.join(cells)}</td></tr>")
    H.append("</table>")
    cur = None
    for e in inv["items"]:
        if e["slot"] in ("prop",) or e["lib"]["status"] == "身份参考覆盖":
            continue
        if (e["char"], e["look"]) != cur:
            if cur:
                H.append("</table>")
            cur = (e["char"], e["look"])
            H.append(f"<h2>{NAMES.get(e['char'], e['char'])} · 造型 {e['look']}</h2><table><tr><th>槽位</th><th>单品</th>"
                     "<th>状态</th><th>图（已有 / 候选）</th><th>出现的镜</th></tr>")
        st = e["lib"]["status"]
        figs = []
        for m in (e["lib"].get("matches") or [])[:1]:
            if st == "有图":
                figs += [img(f, f"库 {m['id']}") for f in m["files"][:3]]
        g = by_name.get((e["char"], e["name"]))
        if g:
            ch = (g.get("chosen") or {}).get("cand")
            failed = []
            for k, v in sorted((g.get("cands") or {}).items()):
                if v.get("file"):
                    q = f"{k} 清晰{v.get('lap_var', '?')} 脸{v.get('faces', '?')} 肤{v.get('skin', '?')}"
                    if v.get("ok"):
                        figs.append(img(v["file"], q, star=k == ch))
                    else:                          # K-REN-133：候选只放通过契约的；不合格折叠在"未通过"
                        failed.append(img(v["file"], q, bad=True))
            fg = flux_items.get(g["slug"]) or {}
            fch = (fg.get("chosen") or {}).get("file")
            fin = (final.get("items", {}).get(g["slug"]) or {}).get("file")
            if fg:
                figs.append("<br><b>FLUX.2 klein 4B：</b>")
                for k, v in sorted((fg.get("cands") or {}).items()):
                    if not v.get("file"):
                        continue
                    q = f"{k} 清晰{v.get('lap_var', '?')} 脸{v.get('faces', '?')} 肤{v.get('skin', '?')}"
                    if v.get("ok"):
                        figs.append(img(v["file"], q, star=v["file"] == fin))
                    else:
                        failed.append(img(v["file"], "FLUX " + q, bad=True))
            if fin:
                figs.append(f"<div><small>最终暂定：{html.escape((final['items'][g['slug']] or {}).get('model') or '')}"
                            f"（{html.escape((final['items'][g['slug']] or {}).get('why') or '')}）</small></div>")
            if failed:
                figs.append(f"<details><summary>未通过 {len(failed)} 张（不进候选）</summary>{''.join(failed)}</details>")
        note = e["lib"].get("note", "")
        H.append(f"<tr><td>{SLOT_ZH.get(e['slot'], e['slot'])}</td><td>{html.escape(e['name'])}"
                 f"{'' if e['registered'] else '<br><small>未登记</small>'}</td>"
                 f"<td><span class='tag {st}'>{st}</span><br><small>{html.escape(note)}</small></td><td>{''.join(figs) or '—'}</td>"
                 f"<td><small>{' '.join(sorted(set(e['shots_mentioned']) | set(e['shots_look_active'])))}</small></td></tr>")
    H.append("</table><h2>项目方上传的单品（已有图，暂不挂造型）</h2><div>")
    for o in inv.get("owner_uploads", []):
        for f in o["files"]:
            H.append(img(f, f"{o['name']}（{o['id']}）"))
    H.append("</div><h2>剧本矛盾 / 未登记（剩余）</h2><table><tr><th>类型</th><th>镜</th><th>角色</th><th>内容</th><th>处理</th></tr>")
    for i in inv["issues"]:
        H.append(f"<tr><td>{html.escape(i['type'])}</td><td>{html.escape(str(i.get('shot') or i.get('ep') or ''))}</td>"
                 f"<td>{html.escape(str(i.get('char', '')))}</td><td>{html.escape(i.get('detail', ''))}</td>"
                 f"<td>{html.escape(i.get('fix', ''))}</td></tr>")
    H.append("</table>")
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    PAGE.write_text("\n".join(H), encoding="utf-8")
    print(PAGE)
    return 0


if __name__ == "__main__":
    sys.exit(main())
