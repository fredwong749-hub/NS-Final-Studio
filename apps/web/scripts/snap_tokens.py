"""UIRSI 排版收敛（项目方原话：“字的大小、depth 的大小……margin 和 padding 的设置……字的颜色、排版和间距”）。

把 CSS 里写死的间距 / 字号吸到 token 上：
- padding / margin / gap 里的 px：1–2px 细调保留；其余吸到最近的 4 的网格并换成 --sp-*（4/8/12/16/24/32），
  0 保留；大于 32 的（定位 / 栅格宽）不动。负值同样处理。
- font-size 的 px：吸到最近的 --fs-*（12/13/14/16/20）；≥24 的大字不动。
theme.css 不动。只改值，不改选择器；每个文件改了多少写到 stdout。
用法：.venv/Scripts/python.exe apps/web/scripts/snap_tokens.py [--dry]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src"
SP = {4: "var(--sp-1)", 8: "var(--sp-2)", 12: "var(--sp-3)", 16: "var(--sp-4)", 24: "var(--sp-6)", 32: "var(--sp-8)"}
FS = {12: "var(--fs-xs)", 13: "var(--fs-sm)", 14: "var(--fs-m)", 16: "var(--fs-lg)", 20: "var(--fs-xl)"}
SP_PROPS = re.compile(r"(?<![-\w])((?:padding|margin)(?:-(?:top|right|bottom|left|inline|block)(?:-(?:start|end))?)?|gap|row-gap|column-gap)(\s*:\s*)([^;{}]+)")
FS_PROP = re.compile(r"(?<![-\w])(font-size)(\s*:\s*)([^;{}]+)")
PX = re.compile(r"(-?)(\d+(?:\.\d+)?)px")


def snap_sp(m: re.Match) -> str:
    neg, v = m.group(1), float(m.group(2))
    if v <= 2 or v > 32:
        return m.group(0)
    best = min(SP, key=lambda k: (abs(k - v), -k if v >= 10 else k))   # 10 → 8（偏紧，防 1280 宽溢出）；14 → 16
    if v == 10:
        best = 8
    tok = SP[best]
    return f"calc(-1 * {tok})" if neg else tok


def snap_fs(m: re.Match) -> str:
    v = float(m.group(2))
    if v >= 24 or m.group(1):
        return m.group(0)
    best = min(FS, key=lambda k: (abs(k - v), k))
    if v < 12:
        best = 12   # 最小字号 12（C 原则 22）
    return FS[best]


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    dry = "--dry" in sys.argv
    total = 0
    for f in sorted(SRC.rglob("*.css")):
        if f.name == "theme.css":
            continue
        s = f.read_text(encoding="utf-8")
        n = 0

        def sp(m: re.Match) -> str:
            nonlocal n
            new = PX.sub(snap_sp, m.group(3))
            n += new != m.group(3)
            return m.group(1) + m.group(2) + new

        def fs(m: re.Match) -> str:
            nonlocal n
            new = PX.sub(snap_fs, m.group(3))
            n += new != m.group(3)
            return m.group(1) + m.group(2) + new

        t = FS_PROP.sub(fs, SP_PROPS.sub(sp, s))
        if t != s:
            total += n
            print(f"{f.relative_to(SRC)}: {n}")
            if not dry:
                f.write_text(t, encoding="utf-8")
    print(f"合计 {total} 处声明")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
