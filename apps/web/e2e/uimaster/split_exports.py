"""PW-019 搬家工具：把组件文件（.tsx）里指定的非组件导出挪到同名 .helpers.ts，组件文件改为从那里导入。
用法：python split_exports.py <组件文件> <名字1,名字2,…> <输出目录> [--reexport]
  产出：<输出目录>/<文件名>（新组件文件）、<输出目录>/<基名>.helpers.ts（新 helpers 文件）、<输出目录>/plan.txt（导入方清单）
  --reexport：组件文件里留一行过渡再导出（别人文件里的导入还没改时用；改完再删）
只负责“搬”：搬完一律用 safe_edit.sh（语法 + tsc，不过回滚）写回；helpers 先写入，再写组件文件。
限制：只认顶层 `export function` / `export const` / `export let`（到下一个顶格的 `}` / `};` / 本行 `;` 结束）。
"""
import os
import re
import sys

src_path, names_arg, out_dir = sys.argv[1], sys.argv[2], sys.argv[3]
reexport = "--reexport" in sys.argv
locals_ = []
exported_types = []
if "--locals" in sys.argv:
    locals_ = [n for n in sys.argv[sys.argv.index("--locals") + 1].split(",") if n]
names = [n for n in names_arg.split(",") if n]
s = open(src_path, encoding="utf-8").read()
lines = s.split("\n")


def find_block(name):
    pre = r"^(?:export\s+)?" if name in locals_ else r"^export\s+"
    kinds = r"(?:function\*?|const|let|type|interface)" if name in locals_ else r"(?:function\*?|const|let)"
    pat = re.compile(pre + r"(?:async\s+)?" + kinds + r"\s+" + re.escape(name) + r"\b")
    for i, ln in enumerate(lines):
        if pat.match(ln):
            # 原来就导出的类型 / 接口跟着挪走：组件文件留一行 type 再导出（类型不影响热更新），别处的 type 导入照常可用
            if name in locals_ and re.match(r"^export\s+(?:type|interface)\s", ln):
                exported_types.append(name)
            # 往上带上紧挨着的注释行
            st = i
            while st > 0 and (lines[st - 1].startswith("//") or lines[st - 1].startswith("/**") or lines[st - 1].startswith(" *") or lines[st - 1].startswith(" */")):
                st -= 1
            # 单行声明
            if ln.rstrip().endswith(";") and ln.count("{") == ln.count("}") and ln.count("(") == ln.count(")") and ln.count("[") == ln.count("]"):
                return st, i
            for j in range(i + 1, len(lines)):
                if re.match(r"^(\}|\};|\]|\];|\);|\)\s*;?)\s*(//.*)?$", lines[j]):
                    return st, j
            raise SystemExit(f"找不到 {name} 的结尾")
    raise SystemExit(f"找不到 export {name}")


blocks = sorted((find_block(n) for n in names + locals_), key=lambda x: x[0])
moved, keep, k = [], [], 0
for st, en in blocks:
    keep.extend(lines[k:st])
    moved.append("\n".join(lines[st:en + 1]))
    k = en + 1
keep.extend(lines[k:])
body = "\n\n".join(moved)
# 一起挪走的私有名字在 helpers 里要导出（组件文件还会用）
for n in locals_:
    body = re.sub(r"^((?:async\s+)?(?:function\*?|const|let|type|interface)\s+" + re.escape(n) + r"\b)", r"export \1", body, flags=re.M)
comp = "\n".join(keep)

# helpers 需要的导入：原文件的 import 里，被 helpers 正文用到的名字
imports = re.findall(r"^import\s+(type\s+)?\{([^}]*)\}\s+from\s+(\"[^\"]+\");?$", s, re.M)
default_imports = re.findall(r"^import\s+([A-Za-z_$][\w$]*)\s*(?:,\s*\{([^}]*)\})?\s+from\s+(\"[^\"]+\");?$", s, re.M)
h_imports = []
for is_type, specs, mod in imports:
    use = []
    for sp in specs.split(","):
        t = sp.strip()
        if not t:
            continue
        local = t.split(" as ")[-1].replace("type ", "").strip()
        if re.search(r"\b" + re.escape(local) + r"\b", body):
            use.append(t)
    if use:
        fix_mod = mod
        h_imports.append(f"import {'type ' if is_type else ''}{{ {', '.join(use)} }} from {fix_mod};")
for dflt, specs, mod in default_imports:
    if re.search(r"\b" + re.escape(dflt) + r"\b", body):
        h_imports.append(f"import {dflt} from {mod};")
# helpers 可能还用到组件文件里没导出的本地名字 → 交给 tsc 报出来（报了就回滚，人工处理）
base = os.path.splitext(os.path.basename(src_path))[0]
helpers_name = f"{base}.helpers.ts"
helpers = (f"// PW-019：从 {base}.tsx 挪出来的非组件导出（组件文件只导出组件，热更新才不会退化成整页重载）。\n"
           + "\n".join(h_imports) + "\n\n" + body.strip() + "\n")
if "<" in body and re.search(r"<[A-Za-z]", body) and "React" not in helpers:
    pass  # 有 JSX 的话 .ts 会报错 → tsc 回滚

# 组件文件：还在用的名字从 helpers 导入
# 组件里还在用的名字（前面是 . 的不算：ref.current ≠ 本地变量 current）
still = [n for n in names + locals_ if re.search(r"(?<![.\w$])" + re.escape(n) + r"\b", comp)]
add = ""
if still:
    # 类型 / 接口要写成 type 导入（tsconfig 开了 verbatimModuleSyntax）
    is_type = lambda n: bool(re.search(r"^(?:export\s+)?(?:type|interface)\s+" + re.escape(n) + r"\b", body, re.M))
    add += f'import {{ {", ".join(("type " + n) if is_type(n) else n for n in still)} }} from "./{base}.helpers";\n'
if exported_types:
    add += f'export type {{ {", ".join(exported_types)} }} from "./{base}.helpers";\n'
if reexport:
    add += f'// 过渡期：别处还从这里导入；都改成 from "./{base}.helpers" 后删掉下一行（PW-019）\n'
    add += f'export {{ {", ".join(names)} }} from "./{base}.helpers";\n'
# 插在最后一个 import 之后
last_imp = 0
for m in re.finditer(r"^import [^\n]*;?$", comp, re.M):
    last_imp = m.end()
comp = comp[:last_imp] + "\n" + add + comp[last_imp:] if add else comp
# 清掉组件文件里搬走后不再用到的导入名（只处理 {…} 形式）
def prune(m):
    is_type, specs, mod = m.group(1) or "", m.group(2), m.group(3)
    rest = comp.replace(m.group(0), "")
    keep_specs = []
    for sp in specs.split(","):
        t = sp.strip()
        if not t:
            continue
        local = t.split(" as ")[-1].replace("type ", "").strip()
        if re.search(r"\b" + re.escape(local) + r"\b", rest):
            keep_specs.append(t)
    if not keep_specs:
        return ""
    return f"import {is_type}{{ {', '.join(keep_specs)} }} from {mod};"
comp = re.sub(r"^import\s+(type\s+)?\{([^}]*)\}\s+from\s+(\"[^\"]+\");?$", prune, comp, flags=re.M)
comp = re.sub(r"\n{3,}", "\n\n", comp)

os.makedirs(out_dir, exist_ok=True)
open(os.path.join(out_dir, os.path.basename(src_path)), "w", encoding="utf-8").write(comp)
open(os.path.join(out_dir, helpers_name), "w", encoding="utf-8").write(helpers)
print(f"ok 搬了 {len(names)} 个：{names}；组件文件里还用到：{still}；helpers 导入 {len(h_imports)} 行")
