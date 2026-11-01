"""把知识库全部规则（knowledge/generated/index.json）做成一张本地网页清单：data/review_pages/rules/index.html。
用法：python tools/knowledge/rules_page.py [--open]
先跑 tools/knowledge/compile.py 保证 index.json 是最新的。页面自带搜索 / 按领域 / 按状态 / 只看没有自动检查的。"""
from __future__ import annotations

import html
import json
import os
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "knowledge" / "generated" / "index.json"
OUT = ROOT / "data" / "review_pages" / "rules" / "index.html"

DOMAIN = {"render": "出图 / 出视频", "writer": "写剧本", "prompt": "提示词", "review": "审片 / 质检",
          "asset": "资产（人物 / 服装 / 场景）", "edit": "剪辑 / 配乐", "ui": "画布界面", "ops": "运维 / 机器 / 流程",
          "loop": "自动迭代"}


def main():
    d = json.loads(SRC.read_text(encoding="utf-8"))
    rules = d["rules"]
    rows = []
    for r in rules:
        rows.append({
            "id": r.get("id"), "domain": r.get("domain") or "其他", "title": r.get("title") or "",
            "when": r.get("when") or "", "then": r.get("then") or "", "status": r.get("status") or "",
            "enforced": r.get("enforced", True) is not False,
            "check": [c if isinstance(c, str) else json.dumps(c, ensure_ascii=False) for c in (r.get("check") or [])],
            "evidence": [(e.get("src") or "") + ((" — " + (e.get("quote") or e.get("note") or "")) if (e.get("quote") or e.get("note")) else "")
                         for e in (r.get("evidence") or []) if isinstance(e, dict)],
            "date": str(r.get("date") or ""), "link": r.get("link") or [],
        })
    dom = Counter(x["domain"] for x in rows)
    st = Counter(x["status"] for x in rows)
    noenf = sum(1 for x in rows if not x["enforced"])
    data = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")
    page = TEMPLATE.replace("__DATA__", data).replace("__DOMAINS__", json.dumps(DOMAIN, ensure_ascii=False)) \
        .replace("__META__", html.escape(f"知识库版本 {d.get('kb_version')} · 共 {len(rows)} 条 · "
                                         f"没有自动检查 {noenf} 条 · 生成于 {time.strftime('%Y-%m-%d %H:%M')}")) \
        .replace("__DOMCOUNT__", json.dumps(dom, ensure_ascii=False)).replace("__STCOUNT__", json.dumps(st, ensure_ascii=False))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(page, encoding="utf-8")
    os.replace(tmp, OUT)
    print(OUT, len(rows))
    if "--open" in sys.argv:
        os.startfile(OUT)  # noqa: S606  本地打开给项目方看


TEMPLATE = r"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>系统规则清单</title>
<style>
:root{--bg:#f7f7f5;--card:#fff;--fg:#1d1d1f;--mut:#6b6b70;--line:#e3e3e0;--acc:#2f6fdf;--ok:#1f8a4c;--warn:#b26a00;--bad:#c0392b}
@media (prefers-color-scheme:dark){:root{--bg:#141416;--card:#1d1d20;--fg:#ececee;--mut:#9a9aa2;--line:#2c2c31;--acc:#6aa0ff;--ok:#4cc27e;--warn:#e0a03a;--bad:#ef6b5e}}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--fg);font:15px/1.6 "Microsoft YaHei",system-ui,sans-serif}
header{position:sticky;top:0;background:var(--bg);border-bottom:1px solid var(--line);padding:14px 16px;z-index:2}
h1{font-size:20px;margin:0 0 4px}.meta{color:var(--mut);font-size:13px}
.bar{display:flex;flex-wrap:wrap;gap:8px;margin-top:10px}
input,select{font:inherit;padding:6px 10px;border:1px solid var(--line);border-radius:8px;background:var(--card);color:var(--fg)}
input{flex:1 1 240px}label.chk{display:flex;align-items:center;gap:4px;font-size:14px}
main{max-width:1100px;margin:0 auto;padding:12px 16px 60px}
h2{font-size:17px;margin:22px 0 8px}h2 small{color:var(--mut);font-weight:normal}
details{background:var(--card);border:1px solid var(--line);border-radius:10px;margin:6px 0;padding:8px 12px}
summary{cursor:pointer;display:flex;gap:8px;align-items:baseline;flex-wrap:wrap}
.id{font-family:Consolas,monospace;font-size:12px;color:var(--mut)}.t{flex:1 1 300px}
.tag{font-size:12px;border-radius:6px;padding:0 6px;border:1px solid currentColor;white-space:nowrap}
.s-确认{color:var(--ok)}.s-建议{color:var(--acc)}.s-待验{color:var(--warn)}.s-项目方闸门{color:var(--bad)}.s-待许可登记{color:var(--warn)}
.ne{color:var(--warn)}dl{margin:8px 0 2px;display:grid;grid-template-columns:5.5em 1fr;gap:4px 10px}dt{color:var(--mut)}dd{margin:0;word-break:break-word}
ul{margin:0;padding-left:1.2em}.cnt{color:var(--mut);font-size:13px;margin-top:6px}
</style></head><body>
<header><h1>系统规则清单</h1><div class="meta">__META__</div>
<div class="bar"><input id="q" placeholder="搜索：比如 视线、鞋、字幕、Flex、节奏"><select id="dom"><option value="">全部领域</option></select>
<select id="st"><option value="">全部状态</option></select><label class="chk"><input type="checkbox" id="ne" style="flex:none">只看还没有自动检查的</label></div>
<div class="cnt" id="cnt"></div></header>
<main id="list"></main>
<script>
const R=__DATA__, D=__DOMAINS__, DC=__DOMCOUNT__, SC=__STCOUNT__;
const $=s=>document.querySelector(s), esc=s=>String(s).replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
for(const k of Object.keys(DC).sort((a,b)=>DC[b]-DC[a])) $("#dom").insertAdjacentHTML("beforeend",`<option value="${k}">${esc(D[k]||k)}（${DC[k]}）</option>`);
for(const k of Object.keys(SC)) $("#st").insertAdjacentHTML("beforeend",`<option value="${k}">${esc(k)}（${SC[k]}）</option>`);
function draw(){
  const q=$("#q").value.trim().toLowerCase(), dm=$("#dom").value, st=$("#st").value, ne=$("#ne").checked;
  const f=R.filter(r=>(!dm||r.domain===dm)&&(!st||r.status===st)&&(!ne||!r.enforced)&&(!q||JSON.stringify(r).toLowerCase().includes(q)));
  const g={};for(const r of f)(g[r.domain]=g[r.domain]||[]).push(r);
  let h="";for(const k of Object.keys(g).sort((a,b)=>g[b].length-g[a].length)){
    h+=`<h2>${esc(D[k]||k)} <small>${g[k].length} 条</small></h2>`;
    for(const r of g[k]) h+=`<details><summary><span class="id">${esc(r.id)}</span><span class="t">${esc(r.title)}</span>
<span class="tag s-${esc(r.status)}">${esc(r.status||"—")}</span>${r.enforced?"":'<span class="tag ne">没有自动检查</span>'}</summary>
<dl><dt>什么时候</dt><dd>${esc(r.when||"—")}</dd><dt>怎么做</dt><dd>${esc(r.then||"—")}</dd>
<dt>自动检查</dt><dd>${r.check.length?"<ul>"+r.check.map(c=>`<li>${esc(c)}</li>`).join("")+"</ul>":"—"}</dd>
<dt>依据</dt><dd>${r.evidence.length?"<ul>"+r.evidence.map(c=>`<li>${esc(c)}</li>`).join("")+"</ul>":"—"}</dd>
<dt>日期</dt><dd>${esc(r.date||"—")}</dd></dl></details>`;}
  $("#list").innerHTML=h||'<p>没有符合条件的规则。</p>';$("#cnt").textContent=`显示 ${f.length} / ${R.length} 条`;
}
for(const id of ["#q","#dom","#st","#ne"]) $(id).addEventListener("input",draw);draw();
</script></body></html>"""

if __name__ == "__main__":
    main()
