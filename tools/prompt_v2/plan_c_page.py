"""PROMPT（2026-10-31，方案 C）：本地审片页 data/review_pages/ep02_planC/index.html。
每镜一行：镜号 / 时长、导演稿的景别·机位·分拍·声音·转场（原文摘录）、分镜预览图、方案 C 各变体视频（official / singularity）、
机器指标（lab_score 结果，若有），并列出现版 ep02（v1 成片，11 镜）对应的镜头设计做对照。成片在页顶。
只读数据、只写这个 html；所有路径相对页面目录。
"""
from __future__ import annotations

import html
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / "data" / "pipeline" / "runs" / "ep02_claude_director_v1"
PAGE = ROOT / "data" / "review_pages" / "ep02_planC" / "index.html"
# 导演稿镜 → 现版 ep02（v1，11 镜）对应镜
V1_MAP = {1: [1], 2: [2], 3: [3], 4: [4], 5: [5], 6: [6], 7: [7], 8: [8], 9: [9, 10, 11]}


def rel(p: Path) -> str:
    return os.path.relpath(p, PAGE.parent).replace("\\", "/")


def cut_sections() -> dict[int, dict]:
    t = (RUN / "ep02_director_cut.md").read_text(encoding="utf-8")
    out = {}
    for m in re.finditer(r"^## 镜(\d+)｜(.+?)\n(.*?)(?=^## 镜|\Z)", t, re.M | re.S):
        n, title, body = int(m.group(1)), m.group(2).strip(), m.group(3)
        out[n] = {"title": title, "body": body.strip()}
    return out


def v1_design(i: int) -> str:
    p = ROOT / f"data/ab/prompt_v2/ep02/old/S{i}.sent.txt"
    sp = ROOT / f"data/recipes_out/ep02/ep02-S{i}.spec.json"
    s = json.loads(sp.read_text(encoding="utf-8")) if sp.exists() else {}
    cam = s.get("camera", {})
    dl = "／".join(d["text"] for d in (s.get("audio") or {}).get("dialogue", []))
    words = len(re.sub(r"<d>.*?</d>", " ", p.read_text(encoding="utf-8")).split()) if p.exists() else 0
    return (f"S{i}｜{s.get('duration_s', '?')} 秒｜{cam.get('size') or ''}｜{cam.get('move') or ''}"
            + (f"｜台词：{dl}" if dl else "") + f"｜H3 正文 {words} 词，无分拍时间")


def md_block(text: str) -> str:
    h = html.escape(text)
    h = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", h)
    return "<br>".join(h.splitlines())


def metrics() -> dict:
    p = RUN / "scores" / "scores.json"
    return json.loads(p.read_text(encoding="utf-8")) if p.exists() else {}


def main():
    PAGE.parent.mkdir(parents=True, exist_ok=True)
    cut = cut_sections()
    sc = metrics()
    rep = json.loads((RUN / "report.json").read_text(encoding="utf-8")) if (RUN / "report.json").exists() else {}
    ep = ROOT / "data" / "episodes" / "ep02_planC.mp4"
    v1 = ROOT / "data" / "episodes" / "ep02_v1.mp4"
    rows = []
    for n in range(1, 10):
        c = cut.get(n, {})
        prev = sorted((RUN / "preview").glob(f"S{n}_*.png"))
        vids = sorted((RUN / "video").glob(f"S{n}_*.mp4"))
        vcells = []
        for v in vids:
            m = sc.get(v.stem) or {}
            rd = m.get("red") or {}
            mm = (f"{m.get('verdict', '')} 运动 {m.get('mean', '')} J4 {m.get('J4', '')} 硬切 {len(m.get('cuts') or [])} "
                  f"泛红 {rd.get('cheek_red_max', '')} SFace {rd.get('sface_med', '')}") if m else ""
            vcells.append(f"<figure><video src='{rel(v)}' controls preload='metadata' width='216'></video>"
                          f"<figcaption>{html.escape(v.stem)}<br><small>{html.escape(mm)}</small></figcaption></figure>")
        shot = (rep.get("shots") or {}).get(f"ep02-S{n}", {})
        rows.append(f"""<tr><td class='no'><b>镜{n}</b><br>{html.escape(c.get('title', ''))}<br><small>{shot.get('seconds', '')} 秒｜{html.escape(str(shot.get('auto_recipe', '')))}</small></td>
<td class='design'>{md_block(c.get('body', ''))}</td>
<td class='pv'>{''.join(f"<a href='{rel(p)}'><img src='{rel(p)}' width='180'></a>" for p in prev) or '<i>预览图未出</i>'}</td>
<td class='vid'>{''.join(vcells) or '<i>视频未出</i>'}</td>
<td class='v1'>{'<br>'.join(html.escape(v1_design(i)) for i in V1_MAP[n])}<br><a href='{rel(ROOT / f"data/pipeline/runs/ep02_claude_director_v1/prompts/S{n}.ref2va.txt")}'>本镜 Ref2VA 提示词</a> · <a href='{rel(ROOT / f"data/pipeline/runs/ep02_claude_director_v1/prompts/S{n}.i2va.txt")}'>I2VA</a></td></tr>""")
    top = ""
    if ep.exists():
        top += f"<figure><video src='{rel(ep)}' controls width='360'></video><figcaption>方案 C 成片 ep02_planC.mp4</figcaption></figure>"
    if v1.exists():
        top += f"<figure><video src='{rel(v1)}' controls width='360'></video><figcaption>现版 ep02_v1.mp4（对照）</figcaption></figure>"
    rv = ROOT / "data" / "ab" / "director" / "planC" / "review.md"
    doc = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>ep02 方案 C 审片</title><style>
:root{{--bg:#fff;--fg:#1b1b1b;--mut:#666;--line:#ddd;--card:#f6f6f4}}
@media (prefers-color-scheme:dark){{:root{{--bg:#151515;--fg:#eee;--mut:#aaa;--line:#333;--card:#1f1f1f}}}}
body{{background:var(--bg);color:var(--fg);font:14px/1.55 system-ui,"Microsoft YaHei",sans-serif;margin:16px}}
h1{{font-size:20px}} table{{border-collapse:collapse;width:100%}} td,th{{border-top:1px solid var(--line);vertical-align:top;padding:8px}}
th{{text-align:left;color:var(--mut);font-weight:600}} td.no{{width:110px}} td.design{{width:30%;font-size:13px}} td.v1{{font-size:12px;color:var(--mut);width:18%}}
figure{{display:inline-block;margin:0 8px 8px 0}} figcaption{{font-size:12px;color:var(--mut)}} .top{{display:flex;gap:16px;flex-wrap:wrap}}
.note{{background:var(--card);padding:10px 12px;border-radius:6px;margin:10px 0}}
</style></head><body>
<h1>ep02《深夜外套》· 方案 C（导演版分镜 → 写作模型转写 → Ref2VA）</h1>
<div class="note">实验版，不导入生产剧本。导演稿：<a href="{rel(RUN / 'ep02_director_cut.md')}">ep02_director_cut.md</a>；系统格式稿：<a href="{rel(RUN / 'P4_ep02.md')}">P4_ep02.md</a>。
视频变体：<b>official</b> = 官方 ref2va int8（gpu33:3）；<b>singularity</b> = 社区 Singularity ref2va v2 r2（gpu36:0，仅内部对比）。参考图 = 项目方选定的设定图脸部裁切。
{('审片报告：<a href="' + rel(rv) + '">review.md</a>') if rv.exists() else ''}</div>
<div class="top">{top}</div>
<table><tr><th>镜</th><th>导演稿设计（景别 / 机位 / 分拍 / 声音 / 转场）</th><th>分镜预览图</th><th>方案 C 视频</th><th>现版 ep02 对应镜</th></tr>
{''.join(rows)}</table></body></html>"""
    PAGE.write_text(doc, encoding="utf-8")
    print(PAGE)


if __name__ == "__main__":
    main()
