"""docs/CORE.md → data/review_pages/latest/core.html（好读的排版，深浅主题；链接改成相对 core.html 的路径）。

  .venv/Scripts/python.exe tools/knowledge/core_html.py [--src docs/CORE.md] [--out data/review_pages/latest/core.html]
只用标准库：标题、段落、列表、表格、代码块、链接、加粗、行内代码。
"""
from __future__ import annotations

import argparse
import html
import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

CSS = """
:root{--bg:#f6f4f1;--panel:#fff;--fg:#1d1c1a;--mut:#67625b;--line:#e3dfd8;--acc:#2f6fd0;--ok:#2f7a4f;--bad:#b3261e;--code:#efece7}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#151515;--panel:#1e1e1e;--fg:#ebe8e3;--mut:#a39d95;--line:#34322f;--acc:#79a8ff;--ok:#62bf86;--bad:#f2786d;--code:#262523}}
:root[data-theme="dark"]{--bg:#151515;--panel:#1e1e1e;--fg:#ebe8e3;--mut:#a39d95;--line:#34322f;--acc:#79a8ff;--ok:#62bf86;--bad:#f2786d;--code:#262523}
*{box-sizing:border-box}
body{background:var(--bg);color:var(--fg);margin:0;font:15.5px/1.7 'Microsoft YaHei','PingFang SC',system-ui,sans-serif}
main{max-width:1180px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:30px;margin:0 0 8px}
h2{font-size:21px;margin:40px 0 12px;padding-top:12px;border-top:1px solid var(--line)}
h3{font-size:17px;margin:24px 0 8px}
p,li{color:var(--fg)}
a{color:var(--acc);text-decoration:none}a:hover{text-decoration:underline}
code{background:var(--code);padding:1px 5px;border-radius:4px;font-size:.92em}
pre{background:var(--code);padding:12px 14px;border-radius:8px;overflow-x:auto;font-size:13px;line-height:1.45}
pre code{background:none;padding:0}
.tbl{overflow-x:auto;margin:10px 0 18px;border:1px solid var(--line);border-radius:8px;background:var(--panel)}
table{border-collapse:collapse;width:100%;min-width:720px}
th,td{text-align:left;vertical-align:top;padding:8px 10px;border-bottom:1px solid var(--line);font-size:14.5px}
th{color:var(--mut);font-weight:600;background:var(--panel);position:sticky;top:0}
tr:last-child td{border-bottom:none}
nav.toc{background:var(--panel);border:1px solid var(--line);border-radius:8px;padding:10px 16px;margin:16px 0}
nav.toc a{margin-right:14px;display:inline-block}
.bar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap}
button{background:var(--panel);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px 10px;cursor:pointer}
"""


def inline(text: str, link) -> str:
    out, pos = [], 0
    for m in re.finditer(r"`([^`]+)`|\[([^\]]+)\]\(([^)]+)\)|\*\*([^*]+)\*\*", text):
        out.append(html.escape(text[pos:m.start()]))
        if m.group(1) is not None:
            out.append(f"<code>{html.escape(m.group(1))}</code>")
        elif m.group(2) is not None:
            out.append(f'<a href="{html.escape(link(m.group(3)))}">{inline(m.group(2), link)}</a>')
        else:
            out.append(f"<b>{inline(m.group(4), link)}</b>")
        pos = m.end()
    out.append(html.escape(text[pos:]))
    return "".join(out)


def cells(row: str) -> list[str]:
    row = row.strip().strip("|")
    return [c.strip() for c in re.split(r"(?<!\\)\|", row)]


def convert(md: str, link) -> tuple[str, list[tuple[str, str]]]:
    lines = md.splitlines()
    out, toc, i = [], [], 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            j = i + 1
            buf = []
            while j < len(lines) and not lines[j].startswith("```"):
                buf.append(lines[j])
                j += 1
            out.append("<pre><code>" + html.escape("\n".join(buf)) + "</code></pre>")
            i = j + 1
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", ln)
        if m:
            lvl = len(m.group(1))
            anchor = f"s{len(toc)}"
            if lvl == 2:
                toc.append((anchor, m.group(2)))
            out.append(f'<h{lvl} id="{anchor}">{inline(m.group(2), link)}</h{lvl}>')
            i += 1
            continue
        if ln.startswith("|") and i + 1 < len(lines) and re.match(r"^\|[\s:|-]+\|?$", lines[i + 1]):
            head = cells(ln)
            body = []
            j = i + 2
            while j < len(lines) and lines[j].startswith("|"):
                body.append(cells(lines[j]))
                j += 1
            t = ["<div class='tbl'><table><thead><tr>" + "".join(f"<th>{inline(c, link)}</th>" for c in head) + "</tr></thead><tbody>"]
            for r in body:
                t.append("<tr>" + "".join(f"<td>{inline(c, link)}</td>" for c in r) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
            i = j
            continue
        if re.match(r"^\s*[-*]\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\s*[-*]\s+", lines[i]):
                items.append(re.sub(r"^\s*[-*]\s+", "", lines[i]))
                i += 1
            out.append("<ul>" + "".join(f"<li>{inline(x, link)}</li>" for x in items) + "</ul>")
            continue
        if re.match(r"^\s*\d+\.\s+", ln):
            items = []
            while i < len(lines) and re.match(r"^\s*\d+\.\s+", lines[i]):
                items.append(re.sub(r"^\s*\d+\.\s+", "", lines[i]))
                i += 1
            out.append("<ol>" + "".join(f"<li>{inline(x, link)}</li>" for x in items) + "</ol>")
            continue
        if ln.strip():
            buf = [ln]
            i += 1
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#|\||```|\s*[-*]\s|\s*\d+\.\s)", lines[i]):
                buf.append(lines[i])
                i += 1
            out.append("<p>" + inline(" ".join(buf), link) + "</p>")
            continue
        i += 1
    return "\n".join(out), toc


def build(src: Path, out: Path) -> Path:
    md = src.read_text(encoding="utf-8")

    def link(target: str) -> str:
        if re.match(r"^[a-z]+:", target) or target.startswith("#"):
            return target
        path, _, frag = target.partition("#")
        absolute = (src.parent / path).resolve()
        try:
            rel = os.path.relpath(absolute, out.parent.resolve()).replace("\\", "/")
        except ValueError:
            rel = absolute.as_uri()
        return rel + (f"#{frag}" if frag else "")

    body, toc = convert(md, link)
    title = re.search(r"^#\s+(.*)$", md, re.M)
    nav = "<nav class='toc'>" + "".join(f"<a href='#{a}'>{html.escape(t)}</a>" for a, t in toc) + "</nav>"
    doc = f"""<!doctype html><html lang="zh"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>核心总纲</title><style>{CSS}</style></head>
<body><main><div class="bar"><span style="color:var(--mut)">由 docs/CORE.md 生成 · tools/knowledge/core_html.py</span>
<button onclick="var r=document.documentElement;r.dataset.theme=r.dataset.theme==='dark'?'light':'dark'">深 / 浅</button></div>
{body.replace('</h1>', '</h1>' + nav, 1)}
</main></body></html>"""
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(doc, encoding="utf-8")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default=str(ROOT / "docs" / "CORE.md"))
    ap.add_argument("--out", default=str(ROOT / "data" / "review_pages" / "latest" / "core.html"))
    a = ap.parse_args(argv)
    print(build(Path(a.src), Path(a.out)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
