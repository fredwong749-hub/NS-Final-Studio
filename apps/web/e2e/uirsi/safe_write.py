"""安全写回前端文件（UM-0001 之后的做法）：新内容先写到临时文件，用 vite 自己的 oxc 转换器做语法检查（vite 报错层就是语法错），
过了才原子替换目标文件（os.replace），半成品永远不会落到 apps/web/src 里。
用法：python safe_write.py <目标文件> <新内容文件>
       python safe_write.py <目标文件> --replace <old 文件> <new 文件>     # 在目标文件里把 old 整段换成 new（必须恰好出现一次）
退出码 0 = 已写回；1 = 语法不过（目标文件未改）；2 = 用法 / 匹配错误"""
import io
import os
import subprocess
import sys
import tempfile
from pathlib import Path

WEB = Path(__file__).resolve().parents[2]
CHECK = Path(__file__).resolve().parent / "syntax_check.mjs"


def check(src: str, suffix: str) -> str | None:
    with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as f:  # 后缀决定 tsx / ts
        f.write(src)
        tmp = f.name
    try:
        if suffix == ".css":
            return None if src.count("{") == src.count("}") else "花括号不配对"
        r = subprocess.run(["node", str(CHECK), tmp, suffix.lstrip(".") if suffix in (".ts", ".tsx") else "tsx"], capture_output=True, text=True, encoding="utf-8", errors="replace", cwd=str(WEB))
        return None if r.returncode == 0 else (r.stderr or r.stdout)[:2000]
    finally:
        os.unlink(tmp)


def main(argv: list[str]) -> int:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    if len(argv) < 2:
        print(__doc__)
        return 2
    target = Path(argv[0])
    if argv[1] == "--replace":
        old = Path(argv[2]).read_text(encoding="utf-8")
        new = Path(argv[3]).read_text(encoding="utf-8")
        cur = target.read_text(encoding="utf-8")
        if cur.count(old) != 1:
            print(f"old 段在 {target} 里出现 {cur.count(old)} 次（要恰好 1 次）")
            return 2
        content = cur.replace(old, new)
    else:
        content = Path(argv[1]).read_text(encoding="utf-8")
    err = check(content, target.suffix)
    if err:
        print("语法不过，目标文件未改：\n" + err)
        return 1
    tmp = target.with_name(f".{target.name}.safe_tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, target)
    print(f"已写回 {target}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
