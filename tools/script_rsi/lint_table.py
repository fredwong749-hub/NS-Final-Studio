"""SCRIPT-RSI：merge.json → 每集返修前后 lint 计数表（Markdown）+ 阻断明细。只读。

    .venv/Scripts/python.exe tools/script_rsi/lint_table.py data/script_rsi/<tag>
"""
import json
import sys
from pathlib import Path

CODES = ["QW-A1", "QW-A2", "QW-A3", "QW-A4", "QW-A5", "QW-A6", "QW-A7", "QW-A8", "QW-AX1", "QW-T1", "QW-T2"]


def main(d: str) -> int:
    od = Path(d)
    m = json.loads((od / "merge.json").read_text(encoding="utf-8"))
    cb, ca = m["counts_before"], m["counts_after"]
    inv = m["invariants"]["eps"]
    head = "| 集 | 镜数 | " + " | ".join(c.replace("QW-", "") for c in CODES) + " | 合计 | P4 阻断 | 台词逐字 |"
    rows = [head, "|" + "---|" * (len(CODES) + 5)]
    tb = ta = 0
    for e in sorted(cb, key=int):
        b, a = cb[e], ca.get(e, {})
        cells = []
        sb = sa = 0
        for c in CODES:
            x = sum(v for k, v in b.items() if k.split("|")[0] == c)
            y = sum(v for k, v in a.items() if k.split("|")[0] == c)
            sb, sa = sb + x, sa + y
            cells.append(f"{x}→{y}")
        tb, ta = tb + sb, ta + sa
        iv = inv.get(str(e)) or inv.get(e) or {}
        rows.append(f"| ep{int(e):02d} | {iv.get('shots', ['?', '?'])[0]}→{iv.get('shots', ['?', '?'])[1]} | " + " | ".join(cells)
                    + f" | {sb}→{sa} | {b.get('_block', 0)}→{a.get('_block', 0)} | {'✅' if iv.get('dialogue_verbatim') else '❌'} |")
    rows.append(f"\n合计 {tb} → {ta}")
    print("\n".join(rows))
    (od / "lint_table.md").write_text("\n".join(rows) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
