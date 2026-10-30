"""
只读文档（画布里规则号 / SOP 出处的链接目标）：GET /api/docs/{name} → 简单 HTML。

锚点：
  - 表格行第一格是规则号（如 `H3-A1`、`P-B1`、`S1-W7`）→ <tr id="H3-A1">（同一文档里第一次出现的那行）
  - 标题以小节号开头（如 “## 9A. …”、“### 9A.1 …”、“## 6. …”）→ id="sec-9A" / "sec-9A.1" / "sec-6"
只渲染白名单里的文档，不写任何文件。
"""
from __future__ import annotations

import html
import re
from pathlib import Path

DOCS = {"rule_ids": "docs/audit/rule_ids.md", "SOP_production": "docs/SOP_production.md",
        "SOP_parameters": "docs/SOP_parameters.md"}
RULE_RE = re.compile(r"^`?([A-Z][A-Z0-9]*-[A-Z]+\d+)`?$")
SEC_RE = re.compile(r"^(\d+[A-Z]?(?:\.\d+)*)\.?(?:\s|$)")
CSS = """body{font:14px/1.6 system-ui,sans-serif;max-width:1100px;margin:20px auto;padding:0 16px;color:#222}
table{border-collapse:collapse;margin:8px 0}td,th{border:1px solid #ccc;padding:4px 6px;vertical-align:top}
pre{background:#f5f5f5;padding:8px;overflow:auto}code{background:#f0f0f0;padding:0 3px}
:target{background:#fff3a0;outline:2px solid #e0b000}h1,h2,h3,h4{scroll-margin-top:12px}"""


def _inline(t: str) -> str:
    t = html.escape(t)
    t = re.sub(r"`([^`]+)`", r"<code>\1</code>", t)
    t = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", t)
    return re.sub(r"&lt;(https?://[^&\s]+)&gt;", r'<a href="\1">\1</a>', t)


def render(md: str, title: str) -> str:
    out, seen = [], set()
    lines = md.splitlines()
    i = 0
    while i < len(lines):
        ln = lines[i]
        if ln.startswith("```"):
            j = i + 1
            while j < len(lines) and not lines[j].startswith("```"):
                j += 1
            out.append("<pre>" + html.escape("\n".join(lines[i + 1:j])) + "</pre>")
            i = j + 1
            continue
        if m := re.match(r"^(#{1,6})\s+(.*)$", ln):
            level, text = len(m.group(1)), m.group(2).strip()
            sm = SEC_RE.match(text)
            aid = f"sec-{sm.group(1)}" if sm else None
            attr = f' id="{aid}"' if aid and aid not in seen else ""
            seen.add(aid)
            out.append(f"<h{level}{attr}>{_inline(text)}</h{level}>")
            i += 1
            continue
        if ln.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                rows.append(lines[i])
                i += 1
            out.append("<table>")
            for k, r in enumerate(rows):
                cells = [c.strip() for c in r.strip().strip("|").split("|")]
                if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                    continue
                rm = RULE_RE.match(cells[0]) if cells else None
                attr = ""
                if rm and rm.group(1) not in seen:
                    seen.add(rm.group(1))
                    attr = f' id="{rm.group(1)}"'
                tag = "th" if k == 0 else "td"
                out.append(f"<tr{attr}>" + "".join(f"<{tag}>{_inline(c)}</{tag}>" for c in cells) + "</tr>")
            out.append("</table>")
            continue
        out.append(f"<p>{_inline(ln)}</p>" if ln.strip() else "")
        i += 1
    return (f"<!doctype html><meta charset='utf-8'><title>{html.escape(title)}</title><style>{CSS}</style>"
            + "\n".join(out))


def page(root: Path, name: str) -> str | None:
    rel = DOCS.get(name)
    if not rel or not (root / rel).is_file():
        return None
    return render((root / rel).read_text(encoding="utf-8"), rel)


def explain_local(root: Path, rule_id: str) -> dict | None:
    """桥不可达时的本地规则说明：rule_ids.md 该行 + SOP_production.md 里提到它的行（与 gpu3 explain 同名字段）"""
    rules = (root / DOCS["rule_ids"]).read_text(encoding="utf-8").splitlines()
    row, section = None, None
    for ln in rules:
        if ln.startswith("## "):
            section = ln[3:].strip()
        if ln.lstrip().startswith("|"):
            # 反引号里的 |（例如正则 `(no|not|…)`）不是列分隔符
            cells = [c.strip() for c in re.split(r"\|(?=(?:[^`]*`[^`]*`)*[^`]*$)", ln.strip().strip("|"))]
            m = RULE_RE.match(cells[0]) if cells else None
            if m and m.group(1) == rule_id:
                row = cells
                break
    if not row:
        return None
    sop = (root / DOCS["SOP_production"]).read_text(encoding="utf-8").splitlines()
    sop_lines = [{"line": i + 1, "text": t.strip()} for i, t in enumerate(sop) if rule_id in t][:6]
    get = lambda k: row[k] if len(row) > k else ""   # noqa: E731
    return {"found": True, "rule_id": rule_id, "rule": get(1), "check": get(2), "level": get(3), "sop_ref": get(4),
            "section": section, "sop_lines": sop_lines, "example_pass": None, "example_fail": None,
            "retired": "作废" in get(3)}
