"""tools/ 下同名脚本的裸 import 歧义守卫（ITERAUDIT 2026-11-01，K-OPS-Q11）。

tools/autopilot/run.py 与 tools/bakeoff/run.py（还有 report.py、build_jobs.py）都叫同一个名字。测试或脚本把各自目录插进 sys.path 后
`import run`，拿到哪一个取决于 sys.path 顺序和 sys.modules 缓存——全量测试里曾报 2 个收集错误（拿到了另一个 run，no attribute 'BASE'）。

install() 在 sys.meta_path 最前面放一个查找器，只管这些歧义名：
- sys.path 上恰好只有一个候选目录 → 正常导入它；若 sys.modules 里缓存的是另一个文件 → 换成当前这个；
- 有两个及以上候选目录同时在 sys.path 上 → 抛 ImportError，写明候选文件和正确做法
  （importlib.util.spec_from_file_location("<唯一名>", 路径) 按独立模块名加载）。
不改任何 owner 的脚本名。
"""
from __future__ import annotations

import importlib.abc
import importlib.machinery
import os
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def ambiguous(root: Path = ROOT) -> dict[str, list[Path]]:
    by = defaultdict(list)
    for p in (root / "tools").rglob("*.py"):
        if "__pycache__" not in p.parts:
            by[p.stem].append(p.resolve())
    return {k: v for k, v in by.items() if len(v) > 1}


def _rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


class AmbiguousScriptImport(ImportError):
    pass


class _Finder(importlib.abc.MetaPathFinder):
    def __init__(self, names: dict[str, list[Path]]):
        self.names = names

    def find_spec(self, fullname, path=None, target=None):
        if path is not None or fullname not in self.names:
            return None
        cands = self.names[fullname]
        dirs = {os.path.normcase(str(c.parent)): c for c in cands}
        on_path = []
        for entry in sys.path:
            k = os.path.normcase(os.path.abspath(entry or "."))
            if k in dirs and dirs[k] not in on_path:
                on_path.append(dirs[k])
        if not on_path:
            return None
        if len(on_path) > 1:
            raise AmbiguousScriptImport(
                f"`import {fullname}` 有歧义：sys.path 上同时有 {', '.join(_rel(c) for c in on_path)}。"
                f"请用 importlib.util.spec_from_file_location(\"<唯一模块名>\", 路径) 按独立名字加载（tools/qa/script_name_guard.py）")
        return importlib.machinery.PathFinder.find_spec(fullname, [str(on_path[0].parent)])


_state: dict = {}


def install(root: Path = ROOT) -> dict[str, list[Path]]:
    if _state.get("finder"):
        return _state["finder"].names
    names = ambiguous(root)
    f = _Finder(names)
    sys.meta_path.insert(0, f)
    _state["finder"] = f
    return names


def uninstall() -> None:
    f = _state.pop("finder", None)
    if f and f in sys.meta_path:
        sys.meta_path.remove(f)


def evict_stale() -> list[str]:
    """sys.modules 里缓存的歧义名模块，若不是当前 sys.path 会选中的那个文件 → 删掉，下次 import 重新解析"""
    f = _state.get("finder")
    out = []
    if not f:
        return out
    for name in f.names:
        m = sys.modules.get(name)
        if m is None or not getattr(m, "__file__", None):
            continue
        try:
            spec = f.find_spec(name)
        except AmbiguousScriptImport:
            spec = None
        if spec is None or os.path.normcase(str(Path(spec.origin).resolve())) != os.path.normcase(str(Path(m.__file__).resolve())):
            del sys.modules[name]
            out.append(name)
    return out
