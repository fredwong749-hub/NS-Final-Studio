"""全仓 Python 语法 / 导入守卫（CODE-RSI 2026-11-01，规则 K-OPS-C01 / K-OPS-C02，knowledge/rules/ops_code_rsi.yaml）。

起因：11-01 一天里三次“别的 loop 把字符串写断 → 全部测试起不来”（unified_frame.py 16:55、pipeline.py 17:48 等）。
pytest 只在导入到那个文件时才炸，而且炸的是收集阶段，报错淹没在几百行里；这个守卫在收轮时先把它拦下来。

查什么（每个 .py）：
  E1 解码      必须是合法 UTF-8（允许 BOM）
  E2 编译      compile()：语法错误、写断的字符串、空字节；SyntaxWarning（非法转义 "\\|" 等，Python 3.14 起会变错误）也算错
  E3 未定义名  pyflakes 的 UndefinedName / UndefinedExport / UndefinedLocal（没装 pyflakes → 记“未测”，退出码 2）
  E4 项目内导入  `import ns_x.y` / `from ns_x.y import z`：ns_x 是本仓库的包（services/*/ns_*、packages/*/ns_*）时，
               模块文件必须存在；z 必须是该模块顶层定义的名字或子模块（模块里有 __getattr__ / import * 时不查名字）
不查：未使用的导入、风格（那些不会让测试起不来）。

用法：
  .venv/Scripts/python.exe tools/qa/syntax_guard.py                # 全仓，退出码 0 = 干净，1 = 有错，2 = 未测（缺 pyflakes）
  .venv/Scripts/python.exe tools/qa/syntax_guard.py --json out.json  # 另写 JSON
  .venv/Scripts/python.exe tools/qa/syntax_guard.py path/a.py dir/   # 只查给定文件 / 目录
结果默认写 data/qa/syntax_guard/last.json（--dry 不写）。iter_gate 的 Y1 项调用它（每个 loop 收轮必过）。
只读检查：不改任何源文件。
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import sys
import time
import warnings
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/qa/syntax_guard"
# 扫描根（相对仓库）；data/ 下是一次性产物脚本，不进闸门（另报）
SCAN_ROOTS = ("apps", "services", "packages", "tools", "tests", "ops", "golden", "docs", "training", "infra", "templates")
SKIP_DIRS = {".venv", "node_modules", ".git", "__pycache__", "models_cache", "comfy", "dist", ".pytest_cache", "_quarantine"}
# 已知误报（文件, pyflakes 消息类）：Blender 插件用中文字符串当属性注解，pyflakes 当成前向引用
ALLOW = {
    ("tools/ns_latex_tools.py", "UndefinedName"),
    ("tools/ns_latex_tools.py", "ForwardAnnotationSyntaxError"),
}
PYFLAKES_HARD = {"UndefinedName", "UndefinedExport", "UndefinedLocal", "ForwardAnnotationSyntaxError"}


def rel(p: Path) -> str:
    try:
        return p.resolve().relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def iter_files(paths: list[str] | None = None) -> list[Path]:
    roots = [Path(p) if Path(p).is_absolute() else ROOT / p for p in paths] if paths else [ROOT / r for r in SCAN_ROOTS]
    out: list[Path] = []
    for r in roots:
        if r.is_file():
            if r.suffix == ".py":
                out.append(r)
            continue
        if not r.is_dir():
            continue
        for dp, dns, fns in os.walk(r):
            dns[:] = [d for d in dns if d not in SKIP_DIRS]
            out += [Path(dp) / f for f in fns if f.endswith(".py")]
    return sorted(set(out))


# ---------------------------------------------------------------- 项目包索引（E4）
def package_roots(root: Path = ROOT) -> dict[str, Path]:
    pk: dict[str, Path] = {}
    for base in ("services", "packages"):
        for d in sorted((root / base).glob("*/ns_*")):
            if (d / "__init__.py").exists():
                pk.setdefault(d.name, d)
    return pk


def module_file(mod: str, pk: dict[str, Path]) -> Path | None | bool:
    """返回模块文件；不是项目包 → False；是项目包但找不到 → None"""
    parts = mod.split(".")
    if parts[0] not in pk:
        return False
    d = pk[parts[0]]
    for i, p in enumerate(parts[1:]):
        last = i == len(parts) - 2
        if (d / p).is_dir() and ((d / p / "__init__.py").exists() or not last):
            d = d / p
            continue
        if last and (d / f"{p}.py").exists():
            return d / f"{p}.py"
        return None
    return d / "__init__.py" if (d / "__init__.py").exists() else None


_DEF_CACHE: dict[str, tuple[set[str], bool]] = {}


def top_names(f: Path) -> tuple[set[str], bool]:
    """模块顶层定义的名字；第二项 = 动态（有 __getattr__ / import *），动态时不查名字"""
    k = str(f)
    if k in _DEF_CACHE:
        return _DEF_CACHE[k]
    names: set[str] = set()
    dyn = False
    try:
        tree = ast.parse(f.read_text(encoding="utf-8-sig"))
    except Exception:  # noqa: BLE001  语法错误由 E2 报
        _DEF_CACHE[k] = (names, True)
        return names, True

    def visit(body):
        nonlocal dyn
        for n in body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.add(n.name)
                if n.name == "__getattr__":
                    dyn = True
            elif isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                tg = n.targets if isinstance(n, ast.Assign) else [n.target]
                for t in tg:
                    for x in ast.walk(t):
                        if isinstance(x, ast.Name):
                            names.add(x.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for a in n.names:
                    if a.name == "*":
                        dyn = True
                    else:
                        names.add(a.asname or a.name.split(".")[0])
            elif isinstance(n, (ast.If, ast.Try, ast.With, ast.For, ast.While)):
                for fld in ("body", "orelse", "finalbody"):
                    visit(getattr(n, fld, []) or [])
                for h in getattr(n, "handlers", []) or []:
                    visit(h.body)
            elif isinstance(n, ast.Match):
                for c in n.cases:
                    visit(c.body)
            elif hasattr(ast, "TypeAlias") and isinstance(n, ast.TypeAlias):
                names.add(n.name.id)
            if isinstance(n, (ast.Assign,)) and any(isinstance(t, ast.Name) and t.id == "globals" for t in ast.walk(n)):
                dyn = True
            if isinstance(n, ast.Expr) and "globals()" in ast.unparse(n):
                dyn = True
    visit(tree.body)
    _DEF_CACHE[k] = (names, dyn)
    return names, dyn


def check_imports(f: Path, tree: ast.AST, pk: dict[str, Path]) -> list[dict]:
    errs = []
    for n in ast.walk(tree):
        if isinstance(n, ast.Import):
            for a in n.names:
                mf = module_file(a.name, pk)
                if mf is None:
                    errs.append({"code": "E4", "line": n.lineno, "msg": f"import {a.name}：项目模块不存在"})
        elif isinstance(n, ast.ImportFrom) and n.level == 0 and n.module:
            mf = module_file(n.module, pk)
            if mf is False:
                continue
            if mf is None:
                errs.append({"code": "E4", "line": n.lineno, "msg": f"from {n.module} import …：项目模块不存在"})
                continue
            names, dyn = top_names(mf)
            if dyn:
                continue
            for a in n.names:
                if a.name == "*" or a.name in names:
                    continue
                if mf.name == "__init__.py" and ((mf.parent / f"{a.name}.py").exists() or (mf.parent / a.name / "__init__.py").exists()):
                    continue
                errs.append({"code": "E4", "line": n.lineno, "msg": f"from {n.module} import {a.name}：{rel(mf)} 顶层没有这个名字"})
    return errs


# ---------------------------------------------------------------- 单文件检查（子进程里跑）
def check_file(path: str) -> dict:
    f = Path(path)
    r = rel(f)
    res = {"file": r, "errors": []}
    try:
        raw = f.read_bytes()
    except OSError as e:
        res["errors"].append({"code": "E1", "line": 0, "msg": f"读不了：{e}"})
        return res
    try:
        src = raw.decode("utf-8-sig")
    except UnicodeDecodeError as e:
        res["errors"].append({"code": "E1", "line": raw[: e.start].count(b"\n") + 1, "msg": f"不是合法 UTF-8：{e.reason}"})
        return res
    tree = None
    with warnings.catch_warnings():
        warnings.simplefilter("error", SyntaxWarning)   # 告警升级后 compile 抛 SyntaxError（或 SyntaxWarning）
        try:
            tree = compile(src, r, "exec", ast.PyCF_ONLY_AST, dont_inherit=True)
            compile(tree, r, "exec", dont_inherit=True)
        except (SyntaxError, SyntaxWarning, ValueError) as e:
            msg = str(getattr(e, "msg", e))
            line = getattr(e, "lineno", 0) or 0
            if isinstance(e, SyntaxWarning) or "invalid escape sequence" in msg or "is not valid" in msg:
                res["errors"].append({"code": "E2", "line": line, "msg": f"SyntaxWarning（非法转义，3.14 起是错误）：{msg}"})
                tree = None
            else:
                res["errors"].append({"code": "E2", "line": line, "msg": f"{type(e).__name__}：{msg}"})
                return res
    if tree is None:   # 只有告警：照常继续查名字 / 导入
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            tree = compile(src, r, "exec", ast.PyCF_ONLY_AST, dont_inherit=True)
    try:
        from pyflakes import checker as PC
    except ImportError:
        res["pyflakes"] = False
    else:
        res["pyflakes"] = True
        for m in PC.Checker(tree, filename=r).messages:
            kind = type(m).__name__
            if kind in PYFLAKES_HARD and (r, kind) not in ALLOW:
                res["errors"].append({"code": "E3", "line": m.lineno, "msg": f"{kind}：{m.message % m.message_args}"})
    res["errors"] += check_imports(f, tree, package_roots())
    return res


def run(paths: list[str] | None = None, jobs: int | None = None) -> dict:
    t0 = time.time()
    files = iter_files(paths)
    results = None
    if len(files) > 40 and (jobs or 0) != 1:
        try:   # 多进程（20 线程笔记本 ≈ 2 秒）；被 spec_from_file_location 加载时子进程拿不到本模块 → 退回单进程
            with ProcessPoolExecutor(max_workers=jobs or min(16, os.cpu_count() or 4)) as ex:
                results = list(ex.map(check_file, [str(f) for f in files], chunksize=16))
        except Exception:  # noqa: BLE001
            results = None
    if results is None:
        results = [check_file(str(f)) for f in files]
    bad = [x for x in results if x["errors"]]
    no_pf = any(x.get("pyflakes") is False for x in results)
    verdict = "FAIL" if bad else ("UNTESTED" if no_pf else "PASS")
    return {"schema": "nsfs.syntax_guard/1", "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "verdict": verdict,
            "files": len(files), "bad_files": len(bad), "pyflakes": not no_pf,
            "seconds": round(time.time() - t0, 2), "errors": [{"file": x["file"], **e} for x in bad for e in x["errors"]]}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="全仓 Python 语法 / 导入守卫（K-OPS-C01）")
    ap.add_argument("paths", nargs="*")
    ap.add_argument("--json")
    ap.add_argument("-j", "--jobs", type=int)
    ap.add_argument("--dry", action="store_true", help="不写 data/qa/syntax_guard/last.json")
    a = ap.parse_args(argv)
    rep = run(a.paths or None, a.jobs)
    text = json.dumps(rep, ensure_ascii=False, indent=1)
    if a.json:
        Path(a.json).write_text(text, encoding="utf-8")
    if not a.dry and not a.paths:
        OUT.mkdir(parents=True, exist_ok=True)
        tmp = OUT / "last.json.tmp"
        tmp.write_text(text, encoding="utf-8")
        os.replace(tmp, OUT / "last.json")
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    for e in rep["errors"][:80]:
        print(f"{e['file']}:{e['line']}: {e['code']} {e['msg']}")
    if len(rep["errors"]) > 80:
        print(f"…… 另有 {len(rep['errors']) - 80} 条，见 JSON")
    print(f"syntax_guard {rep['verdict']}：{rep['files']} 个文件，{rep['bad_files']} 个有错，{rep['seconds']} 秒"
          + ("" if rep["pyflakes"] else "（没装 pyflakes：E3 未测）"))
    return {"PASS": 0, "FAIL": 1, "UNTESTED": 2}[rep["verdict"]]


if __name__ == "__main__":
    sys.exit(main())
