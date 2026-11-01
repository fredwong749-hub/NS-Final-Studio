"""把 .tsx 里的非组件导出挪到同名 .helpers.ts（PW-019：.tsx 只导出组件，热更新才不会退化成整页重载）。
用法：python move_exports.py <src/…/X.tsx> NAME1,NAME2,… [--locals a,b]   （--locals：被挪走的代码依赖的本文件私有常量 / 函数，一起挪过去）
做法（三步都保持可编译，避免中途出 vite 报错层；每个文件都经 safe_write 写回）：
  1) 新建 X.helpers.ts：原文件的 import 原样带过去 + 挪走的代码块（私有的改成 export）
  2) 全仓把 `import { … NAME … } from "<到 X 的相对路径>"` 里的 NAME 改成从 helpers 导入
  3) 原文件删掉这些块，改为从 "./X.helpers" 导入它自己还要用的名字
最后跑 tsc；没用到的 import 留给 tsc 报出来，按报错删。"""
import io
import re
import subprocess
import sys
from pathlib import Path

WEB = Path(__file__).resolve().parents[2]
SRC = WEB / "src"
SAFE = Path(__file__).resolve().parent / "safe_write.py"
TMP = Path(__import__("tempfile").gettempdir()) / "uirsi_move_exports"
TMP.mkdir(exist_ok=True)


def block_end(s: str, i: int) -> int:
    """从声明开头 i 扫到声明结束（顶层 ; 或函数体的 }），跳过字符串 / 模板 / 注释"""
    depth_p = depth_b = depth_k = 0
    is_fn = bool(re.match(r"export\s+(?:async\s+)?function|(?:async\s+)?function", s[i:i + 40]))
    seen_body = False
    j = i
    n = len(s)
    while j < n:
        c = s[j]
        if c in "\"'":
            q = c
            j += 1
            while j < n and s[j] != q:
                j += 2 if s[j] == "\\" else 1
        elif c == "`":
            j += 1
            d = 0
            while j < n:
                if s[j] == "\\":
                    j += 2
                    continue
                if s[j] == "`" and d == 0:
                    break
                if s.startswith("${", j):
                    d += 1
                    j += 2
                    continue
                if s[j] == "}" and d:
                    d -= 1
                j += 1
        elif s.startswith("//", j):
            j = s.find("\n", j)
            if j < 0:
                return n
            continue
        elif s.startswith("/*", j):
            j = s.find("*/", j) + 1
        elif c == "/" and (s[i:j].rstrip()[-1:] in tuple("(,=:[!&|?{};+-*%<>~^") or s[i:j].rstrip().endswith(("return", "=>"))):
            # 正则字面量（UIMASTER 11-01：/[（(][^）)]*[）)]/ 里的括号曾被算进深度，块一路吃到后面的组件 JSX）
            j += 1
            in_cls = False
            while j < n and s[j] != "\n":
                if s[j] == "\\":
                    j += 2
                    continue
                if s[j] == "[":
                    in_cls = True
                elif s[j] == "]":
                    in_cls = False
                elif s[j] == "/" and not in_cls:
                    break
                j += 1
        elif c == "(":
            depth_p += 1
        elif c == ")":
            depth_p -= 1
        elif c == "[":
            depth_k += 1
        elif c == "]":
            depth_k -= 1
        elif c == "{":
            if is_fn and depth_p == 0 and depth_b == 0 and depth_k == 0 and not seen_body:
                prev = s[i:j].rstrip()[-1:]
                # 返回类型里的对象类型（“): { a: string } | null {”）前面是 : | & , < (，不是函数体
                if prev not in ":|&,<(":
                    seen_body = True
            depth_b += 1
        elif c == "}":
            depth_b -= 1
            if is_fn and seen_body and depth_b == 0 and depth_p == 0:
                return j + 1
        elif c == ";" and depth_p == depth_b == depth_k == 0:
            return j + 1
        elif c == "\n" and not is_fn and depth_p == depth_b == depth_k == 0:
            # 没写分号的 const：下一行不是续行（不以 . ? : && || + 等开头）就结束
            rest = s[j + 1:j + 40].lstrip()
            if j > i and not re.match(r"[.?:&|+\-*/=,)\]}]", rest) and not s[i:j].rstrip().endswith(("=", "=>", "(", ",", "?", ":", "&&", "||", "+")):
                return j
        j += 1
    return n


def find_decl(s: str, name: str, exported: bool):
    pat = (r"^export\s+" if exported else r"^") + r"(?:async\s+)?(?:const|let|function|type|interface)\s+" + re.escape(name) + r"\b"
    m = re.search(pat, s, re.M)
    if not m:
        return None
    # 连同紧挨着的上方注释（/** … */ 或 // …）一起挪
    start = m.start()
    k = start
    while True:
        before = s[:k].rstrip("\n")
        line_start = before.rfind("\n") + 1
        line = before[line_start:]
        if line.strip().startswith("//"):
            k = line_start
            continue
        if line.strip().endswith("*/"):
            cs = before.rfind("/*")
            if cs >= 0:
                k = before.rfind("\n", 0, cs) + 1
                continue
        break
    end = block_end(s, m.start())
    # 保险：块里不该再出现另一个顶层声明（行首 export / function / const …），出现了说明边界算错，宁可停下
    body = s[m.end():end]
    if re.search(r"(?m)^(?:export\s|(?:async\s+)?function\s|const\s|let\s|type\s|interface\s|class\s)", body):
        raise SystemExit(f"{name} 的块边界可疑（吃进了后面的顶层声明），停下不改任何文件")
    return k, end


SAFE_EDIT = Path(__file__).resolve().parents[1] / "uimaster" / "safe_edit.sh"
# 用 Git 自带的 bash（Windows 上 PATH 里的 bash.exe 可能是 WSL，看不到 D:/ 路径）
GIT_BASH = next((b for b in (r"C:\Program Files\Git\usr\bin\bash.exe", r"C:\Program Files\Git\bin\bash.exe") if Path(b).exists()), "bash")


def safe(target: Path, content: str):
    """先在沙盒里跑 tsc，过了才写真文件（safe_edit.sh）；新建的文件（还不存在）只做语法检查后写入"""
    tmp = TMP / target.name
    tmp.write_text(content, encoding="utf-8")
    if target.exists():
        r = subprocess.run([GIT_BASH, SAFE_EDIT.as_posix(), target.as_posix(), tmp.as_posix()], capture_output=True, text=True, encoding="utf-8", errors="replace")
    else:
        r = subprocess.run([sys.executable, str(SAFE), str(target), str(tmp)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    print(r.stdout.strip() or r.stderr.strip())
    if r.returncode:
        raise SystemExit(f"safe_write 失败：{target}")


def rel_import(from_file: Path, to_file: Path) -> str:
    import os
    r = os.path.relpath(to_file.with_suffix(""), from_file.parent).replace("\\", "/")
    return r if r.startswith(".") else "./" + r


def main(argv):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    src = (WEB / argv[0]).resolve() if not Path(argv[0]).is_absolute() else Path(argv[0])
    names = [x for x in argv[1].split(",") if x]
    locals_ = []
    if "--locals" in argv:
        locals_ = [x for x in argv[argv.index("--locals") + 1].split(",") if x]
    s = src.read_text(encoding="utf-8")
    helpers = src.with_name(src.stem + ".helpers.ts")
    imports = "\n".join(m.group(0) for m in re.finditer(r"^import[\s\S]*?from\s+[\"'][^\"']+[\"'];?\s*$", s, re.M) if not m.group(0).rstrip().endswith(('.css";', ".css';", '.css"', ".css'")))
    # 相对路径 import 要按 helpers 所在目录（同目录，不变）
    blocks = []
    spans = []
    for nm in locals_:
        f = find_decl(s, nm, False)
        if not f:
            raise SystemExit(f"找不到私有 {nm}")
        txt = s[f[0]:f[1]]
        txt = re.sub(r"^((?:\s*(?://[^\n]*|/\*[\s\S]*?\*/)\s*)*)", r"\1", txt)
        decl = re.search(r"(?m)^(?:async\s+)?(?:const|let|function|type|interface)\s", txt)
        txt = txt[:decl.start()] + "export " + txt[decl.start():]
        blocks.append(txt)
        spans.append(f)
    for nm in names:
        f = find_decl(s, nm, True)
        if not f:
            raise SystemExit(f"找不到导出 {nm}")
        blocks.append(s[f[0]:f[1]])
        spans.append(f)
    header = f"// 从 {src.name} 挪出来的非组件导出（PW-019：.tsx 只导出组件，热更新才不会整页重载）\n"
    if helpers.exists():
        raise SystemExit(f"{helpers.name} 已存在，先手工合并")
    ordered = [b for _, b in sorted(zip([sp[0] for sp in spans], blocks))]
    from prune_imports import prune  # noqa: PLC0415  先删掉 helpers 用不到的 import，不留 TS6133
    safe(helpers, prune(header + imports + "\n\n" + "\n\n".join(b.strip("\n") for b in ordered) + "\n"))
    # 第 2、3 步任何一处失败：把已改的导入方原样写回（原文件还没动、导出还在，写回一定过 tsc），再删掉新建的 helpers，
    # 不留半份 helpers（UIMASTER 11-01 建议）
    changed: list[tuple[Path, str]] = []
    try:
        _steps_2_3(s, src, helpers, names, locals_, blocks, spans, changed)
    except SystemExit as e:
        for f, orig in reversed(changed):
            try:
                safe(f, orig)
            except SystemExit:
                print(f"!! 回滚 {f} 失败，请手工检查")
        helpers.unlink(missing_ok=True)
        raise SystemExit(f"{e}（已回滚 {len(changed)} 个导入方，删掉了 {helpers.name}）")


def _steps_2_3(s, src, helpers, names, locals_, blocks, spans, changed):
    # 2) 全仓改导入
    moved = set(names) | set(locals_)
    for f in list(SRC.rglob("*.ts")) + list(SRC.rglob("*.tsx")):
        if f in (src, helpers):
            continue
        t = f.read_text(encoding="utf-8")
        target = rel_import(f, src)
        pat = re.compile(r"import\s*\{([^}]*)\}\s*from\s*([\"'])" + re.escape(target) + r"\2;?")
        m = pat.search(t)
        if not m:
            continue
        specs = [x.strip() for x in m.group(1).split(",") if x.strip()]
        keep = [x for x in specs if re.sub(r"^type\s+", "", x).split(" as ")[0].strip() not in moved]
        move = [x for x in specs if x not in keep]
        if not move:
            continue
        new = ""
        if keep:
            new += f'import {{ {", ".join(keep)} }} from "{target}";'
        new += ("\n" if keep else "") + f'import {{ {", ".join(move)} }} from "{rel_import(f, helpers)}";'
        safe(f, t[:m.start()] + new + t[m.end():])
        changed.append((f, t))
    # 3) 原文件：删块 + 从 helpers 导入自己还要用的
    out = s
    for a, b in sorted(spans, reverse=True):
        out = out[:a] + out[b:].lstrip("\n")
    alltxt = "\n".join(blocks)
    type_names = {n for n in moved if re.search(r"(?m)^(?:export\s+)?(?:type|interface)\s+" + re.escape(n) + r"\b", alltxt)}
    # 只看代码不看注释（文件头注释里提到名字不算“还在用”，否则多导入一个用不到的名字 → TS6133）
    code = re.sub(r"/\*[\s\S]*?\*/", "", out)
    code = re.sub(r"(?m)(^|[^:\"'`])//[^\n]*", r"\1", code)
    used = [("type " + n if n in type_names else n) for n in sorted(moved) if re.search(r"\b" + re.escape(n) + r"\b", code)]
    if used:
        last_imp = list(re.finditer(r"^import[\s\S]*?from\s+[\"'][^\"']+[\"'];?\s*$", out, re.M))[-1]
        out = out[:last_imp.end()] + f'\nimport {{ {", ".join(used)} }} from "./{helpers.stem}";' + out[last_imp.end():]
    # 原文件删掉挪走的块后，只给那些块用的 import 先删掉再写（否则沙盒 tsc 报 TS6133、第 3 步被拒，
    # 而第 2 步已经让导入方改用 helpers——两份模块状态 / Context 会分家）
    from prune_imports import prune  # noqa: PLC0415
    safe(src, prune(out, src.suffix == ".ts"))
    _post_prune([helpers, src])



def _post_prune(paths):
    """挪完以后删掉没用到的 import（helpers 带过去的全量 import、原文件里只给挪走代码用的 import）"""
    for p in paths:
        r = subprocess.run([sys.executable, str(Path(__file__).resolve().parent / "prune_imports.py"), str(p)],
                           capture_output=True, text=True, encoding="utf-8", errors="replace")
        print(r.stdout.strip() or r.stderr.strip())


if __name__ == "__main__":
    main(sys.argv[1:])
