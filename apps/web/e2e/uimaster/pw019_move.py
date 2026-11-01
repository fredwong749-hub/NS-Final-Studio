"""PW-019 一键搬家（每一步都经 safe_edit.sh：沙盒 tsc 通过才写真文件，导入方任何时刻都拿得到导出）：
  1) split_exports.py --reexport 算出新组件文件 + helpers
  2) 写 helpers（新文件，还没人用）
  3) 组件文件改为从 helpers 导入，并留过渡再导出
  4) 逐个导入方：把这些名字改成从 helpers 导入
  5) 删掉过渡再导出
用法：python pw019_move.py <src/…/X.tsx> NAME1,NAME2 [--locals a,b]
"""
import os
import re
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
WEB = os.path.abspath(os.path.join(HERE, "../.."))
src_rel, names_arg = sys.argv[1], sys.argv[2]
extra = sys.argv[3:]
names = [n for n in names_arg.split(",") if n]
src = os.path.join(WEB, src_rel)
base = os.path.splitext(os.path.basename(src))[0]
out = tempfile.mkdtemp(prefix="pw019_")
env = dict(os.environ, PYTHONIOENCODING="utf-8")


def run(cmd):
    r = subprocess.run(cmd, cwd=WEB, env=env, capture_output=True, text=True, encoding="utf-8")
    print((r.stdout + r.stderr).strip()[-600:])
    if r.returncode != 0:
        sys.exit(f"失败：{' '.join(cmd[:3])}")


def safe_edit(target, new_text):
    tmp = os.path.join(out, "new_" + os.path.basename(target))
    open(tmp, "w", encoding="utf-8").write(new_text)
    # 用 Git Bash（Windows 上 PATH 里的 bash 可能是 WSL，认不得 D:\ 路径）
    gb = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else "bash"
    run([gb, os.path.join(HERE, "safe_edit.sh").replace("\\", "/"), target.replace("\\", "/"), tmp.replace("\\", "/")])


run([sys.executable, os.path.join(HERE, "split_exports.py"), src, names_arg, out, "--reexport"] + extra)
helpers_path = os.path.join(os.path.dirname(src), base + ".helpers.ts")
if os.path.exists(helpers_path):
    sys.exit(f"{helpers_path} 已存在，先手工合并")
# 2) helpers 是新文件：先在沙盒里跟新组件文件一起过 tsc 不方便，所以直接写（还没有任何文件导入它，写坏了也不影响页面）
open(helpers_path, "w", encoding="utf-8").write(open(os.path.join(out, base + ".helpers.ts"), encoding="utf-8").read())
# 3) 组件文件（带过渡再导出）
try:
    safe_edit(src, open(os.path.join(out, os.path.basename(src)), encoding="utf-8").read())
except SystemExit:
    os.remove(helpers_path)  # 组件文件没写成：删掉 helpers，回到原样
    raise
# 4) 导入方
src_dir = os.path.dirname(src)
for root, _, files in os.walk(os.path.join(WEB, "src")):
    for f in files:
        if not f.endswith((".ts", ".tsx")):
            continue
        p = os.path.join(root, f)
        if os.path.abspath(p) in (os.path.abspath(src), os.path.abspath(helpers_path)):
            continue
        rel_mod = os.path.relpath(os.path.splitext(src)[0], root).replace("\\", "/")
        if not rel_mod.startswith("."):
            rel_mod = "./" + rel_mod
        s = open(p, encoding="utf-8").read()
        # 行尾可能带注释：import { … } from "./X"; // 说明
        pat = re.compile(r"^import\s+(type\s+)?\{([^}]*)\}\s+from\s+\"" + re.escape(rel_mod) + r"\";?[ \t]*(//[^\n]*)?$", re.M)
        changed = False

        def fix(m):
            global changed
            if m.group(1):
                return m.group(0)
            specs = [x.strip() for x in m.group(2).split(",") if x.strip()]
            moving = [x for x in specs if x.split(" as ")[0].replace("type ", "").strip() in names]
            if not moving:
                return m.group(0)
            changed = True
            keep = [x for x in specs if x not in moving]
            lines = []
            if keep:
                lines.append(f'import {{ {", ".join(keep)} }} from "{rel_mod}";')
            lines.append(f'import {{ {", ".join(moving)} }} from "{rel_mod}.helpers";')
            return "\n".join(lines)

        s2 = pat.sub(fix, s)
        if changed:
            print(f"导入方：{os.path.relpath(p, WEB)}")
            safe_edit(p, s2)
# 5) 删过渡再导出
s = open(src, encoding="utf-8").read()
s2 = re.sub(r"// 过渡期：别处还从这里导入[^\n]*\n" + r"export \{[^}]*\} from \"\./" + re.escape(base) + r"\.helpers\";\n", "", s)
if s2 != s:
    safe_edit(src, s2)
print(f"完成：{src_rel} → {base}.helpers.ts（{', '.join(names)}）")
