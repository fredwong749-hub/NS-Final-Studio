"""删掉 .ts / .tsx 文件里没用到的 import 说明符（move_exports 带过去的全量 import 用不到的那部分）。经 safe_write 写回。
用法：python prune_imports.py <文件>"""
import io
import re
import subprocess
import sys
import tempfile
from pathlib import Path

SAFE = Path(__file__).resolve().parent / "safe_write.py"
# 只认带 from 的 import；子句里不允许出现引号 / 分号，避免把上一行的副作用 import（import "x.css";）吞进来
IMP = re.compile(r"^import\s+(?:(type)\s+)?([^\"';]*?)\s+from\s+([\"'][^\"']+[\"']);?[ \t]*$", re.M)
CSS_IMP = re.compile(r"^import\s+[\"'][^\"']+\.css[\"'];?[ \t]*\n", re.M)


def prune(s: str, path_is_ts: bool = True) -> str:
    body = IMP.sub("", s)

    def used(n: str) -> bool:
        return re.search(r"(?<![\w$.])" + re.escape(n) + r"(?![\w$])", body) is not None

    def fix(m):
        tkw, clause, src = m.group(1), m.group(2), m.group(3)
        cm = re.match(r"^\s*([\w$]+)?\s*,?\s*(\{([\s\S]*)\})?\s*$", clause)
        if not cm:
            return m.group(0)  # import * as X：不动
        default = cm.group(1)
        named = [x.strip() for x in (cm.group(3) or "").split(",") if x.strip()]
        keep_named = [x for x in named if used(x.split(" as ")[-1].replace("type ", "").strip())]
        keep_default = default if default and used(default) else None
        if not keep_named and not keep_default:
            return ""
        parts = ([keep_default] if keep_default else []) + (["{ " + ", ".join(keep_named) + " }"] if keep_named else [])
        return f"import {'type ' if tkw else ''}{', '.join(parts)} from {src};"

    out = IMP.sub(fix, s)
    if path_is_ts:
        out = CSS_IMP.sub("", out)  # .ts 里不需要样式副作用 import
    return re.sub(r"\n{3,}", "\n\n", out)


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    f = Path(sys.argv[1])
    new = prune(f.read_text(encoding="utf-8"), f.suffix == ".ts")
    tmp = Path(tempfile.gettempdir()) / ("pruned_" + f.name)
    tmp.write_text(new, encoding="utf-8")
    r = subprocess.run([sys.executable, str(SAFE), str(f), str(tmp)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout.strip() or r.stderr.strip())
    sys.exit(r.returncode)
