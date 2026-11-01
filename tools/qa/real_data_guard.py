"""测试期“真实数据写保护”（ITERAUDIT 2026-11-01，规则 K-OPS-Q03）。

起因：11-01 03:15 tests/test_unified_frame.py 起的后台 postflight 线程活过了夹具——monkeypatch 已把 P.RENDERS 还原成真实路径，
线程随后写坏了真实 data/renders/ep01/S1/takes.json。

由 tests/conftest.py 在会话开始时 install()、结束时 report()。装上后：
- 本进程任何线程对真实 <仓库>/data 下的写操作（builtins.open / io.open 写模式、Path.write_text / write_bytes、
  os.replace / os.rename / os.remove / os.unlink / os.makedirs / os.mkdir、tempfile.mkstemp(dir=…)、shutil.copy* / move）
  一律抛 RealDataWriteError，并记进 VIOLATIONS（就算调用方把异常吞了，会话结束也会报出来）。
- 读不受影响。
- 显式放行：测试标 @pytest.mark.real_data（conftest 在该用例期间 allow()），或代码里 with allow(): …
"""
from __future__ import annotations

import builtins
import io
import os
import shutil
import tempfile
import threading
import traceback
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REAL_DATA = os.path.normcase(os.path.abspath(ROOT / "data"))
VIOLATIONS: list[dict] = []
_state = {"on": False, "allow": 0, "orig": {}}
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC


class RealDataWriteError(PermissionError):
    """测试期写真实 data/（tools/qa/real_data_guard.py）"""


def is_real(path) -> bool:
    try:
        p = os.path.normcase(os.path.abspath(os.fspath(path)))
    except TypeError:
        return False   # 文件描述符等
    return p == REAL_DATA or p.startswith(REAL_DATA + os.sep)


def _hit(op: str, path) -> None:
    if not _state["on"] or _state["allow"] or not is_real(path):
        return
    v = {"op": op, "path": os.fspath(path), "thread": threading.current_thread().name,
         "test": os.environ.get("PYTEST_CURRENT_TEST", "（用例之外：夹具收尾 / 后台线程）"),
         "stack": "".join(traceback.format_stack(limit=8)[:-2])}
    VIOLATIONS.append(v)
    raise RealDataWriteError(f"测试期禁止写真实数据：{op} {os.fspath(path)}（{v['test']}）")


def _wrap_open(orig):
    def guarded(file, mode="r", *a, **k):
        if isinstance(mode, str) and any(c in mode for c in "wax+"):
            _hit(f"open({mode})", file)
        return orig(file, mode, *a, **k)
    guarded.__wrapped__ = orig
    return guarded


def _wrap_path(op, idx=(0,)):
    def deco(orig):
        def guarded(*a, **k):
            for i in idx:
                if len(a) > i:
                    if op.endswith("mkdir") or op.endswith("makedirs"):
                        try:
                            if os.path.isdir(os.fspath(a[i])):
                                continue   # 已存在的目录 mkdir(exist_ok) 不算写
                        except TypeError:
                            pass
                    _hit(op, a[i])
            if op == "mkstemp" and k.get("dir") is not None:
                _hit(op, k["dir"])
            return orig(*a, **k)
        guarded.__wrapped__ = orig
        return guarded
    return deco


def _wrap_os_open(orig):
    def guarded(path, flags, *a, **k):
        if flags & _WRITE_FLAGS:
            _hit("os.open", path)
        return orig(path, flags, *a, **k)
    guarded.__wrapped__ = orig
    return guarded


def install() -> None:
    if _state["on"]:
        return
    o = _state["orig"]
    o["builtins.open"], o["io.open"] = builtins.open, io.open
    builtins.open = io.open = _wrap_open(o["io.open"])
    o["os.open"] = os.open
    os.open = _wrap_os_open(o["os.open"])
    for name, idx in (("replace", (1,)), ("rename", (1,)), ("remove", (0,)), ("unlink", (0,)), ("makedirs", (0,)),
                      ("mkdir", (0,)), ("rmdir", (0,))):
        o[f"os.{name}"] = getattr(os, name)
        setattr(os, name, _wrap_path(f"os.{name}", idx)(getattr(os, name)))
    for name, idx in (("copyfile", (1,)), ("copy", (1,)), ("copy2", (1,)), ("move", (1,)), ("rmtree", (0,)),
                      ("copytree", (1,))):
        o[f"shutil.{name}"] = getattr(shutil, name)
        setattr(shutil, name, _wrap_path(f"shutil.{name}", idx)(getattr(shutil, name)))
    o["tempfile.mkstemp"] = tempfile.mkstemp
    tempfile.mkstemp = _wrap_path("mkstemp", ())(tempfile.mkstemp)
    for name in ("write_text", "write_bytes", "touch", "unlink", "mkdir", "rename", "replace", "rmdir"):
        o[f"Path.{name}"] = getattr(Path, name)
        idx = (0, 1) if name in ("rename", "replace") else (0,)
        setattr(Path, name, _wrap_path(f"Path.{name}", idx)(getattr(Path, name)))
    _state["on"] = True


def uninstall() -> None:
    if not _state["on"]:
        return
    o = _state["orig"]
    builtins.open, io.open, os.open = o["builtins.open"], o["io.open"], o["os.open"]
    for k, v in o.items():
        mod, _, name = k.partition(".")
        target = {"os": os, "shutil": shutil, "tempfile": tempfile, "Path": Path}.get(mod)
        if target is not None:
            setattr(target, name, v)
    _state["on"] = False


def active() -> bool:
    return _state["on"] and not _state["allow"]


@contextmanager
def allow():
    """显式放行（@pytest.mark.real_data 的用例）。注意：放行期间别的线程也放行。"""
    _state["allow"] += 1
    try:
        yield
    finally:
        _state["allow"] -= 1


@contextmanager
def expect_violation():
    """测本守卫自己用：块内产生的违规记录收走，不算进会话结果"""
    n = len(VIOLATIONS)
    caught: list[dict] = []
    try:
        yield caught
    finally:
        caught.extend(VIOLATIONS[n:])
        del VIOLATIONS[n:]


def sentinels(limit: int = 6) -> dict[str, float]:
    """几份“不该被测试碰”的真实文件的 mtime"""
    # 不放 data/renders/*/takes.json：线上 API / PRODUCER 跑着时会正常改它（11-01 全量测试实测 ep01/ep02 S1 被线上改动，
    # 测试进程 0 次写入）；takes.json 的测试写入由上面的进程内守卫当场抛错，不靠哨兵
    cands = [ROOT / "data/assets/identity_refs/manifest.json", ROOT / "data/import/script_v2.json",
             ROOT / "data/looks/wardrobe.json", ROOT / "config/recipes/learned.yaml",
             ROOT / "data/auth/viewer_token", ROOT / "knowledge/settings.yaml"]
    out = {}
    for p in cands:
        if p.exists() and str(p) not in out:
            out[str(p)] = p.stat().st_mtime
        if len(out) >= limit:
            break
    return out
