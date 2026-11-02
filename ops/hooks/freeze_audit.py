"""冻结锁第 2 层：笔记本 venv 里所有 Python 进程，system_version cut 冻结期间不许写代码目录（SYSARCH，总调度 11-02 12:0x 派；K-OPS-Y03）。

装法（sv-10 入版后由 SYSARCH 装，NETFIX 已授权）：.venv/Lib/site-packages/ns_freeze_guard.pth 一行加载本模块并调 install()；
和 ns_netfix_ssh_shim.pth 各自独立，撤销 = 删这个 .pth。
做法：sys.addaudithook 监听 open（只看写模式）/ os.rename / os.replace / os.remove / shutil 系列最终落到的这些事件；
目标是冻结目录（tools services packages config knowledge ops tests apps）、cut_lock 有效、本进程不是持锁的 cut → 抛 PermissionError。
NETFIX 11-02 要求：只在写模式判断；cut_lock.json 每 2 s 最多 stat 一次（按 mtime 缓存）；路径规范化后比前缀；
豁免 data/ 与 ops/logs/（监管进程、puller 一直在写），以及运行期配置 config/netfix/override.json、partition.json（DEBUG 兜底进程借道到期会改写）。
持锁豁免：pid == cut_lock.pid，或环境变量 NS_FREEZE_EXEMPT=1（system_version cut 给自己和子进程设，FACTORY 接）。
本 hook 自身任何异常都吞掉、放行（绝不因为守卫出错让业务进程挂掉）——只有“确定冻结 + 确定写冻结目录”才拒绝。
"""
from __future__ import annotations

import json
import os
import sys
import time

ROOT = os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
LOCK = os.path.join(ROOT, "data", "system_versions", "cut_lock.json")
FROZEN = ("tools", "services", "packages", "config", "knowledge", "ops", "tests", "apps")
EXEMPT_PREFIX = ("ops/logs/",)
EXEMPT_FILES = {"config/netfix/override.json", "config/netfix/partition.json"}
STAT_EVERY_S = 2.0
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND
_cache = {"checked": 0.0, "mtime": None, "lock": None}
_busy = False


def _lock(now: float | None = None) -> dict | None:
    """有效的冻结锁 → dict；没有 / 过期 / 读不到 → None（读不到不拦：第 1 层和第 3、4 层兜底，这里不做失败关闭以免误伤生产）"""
    now = time.time() if now is None else now
    if now - _cache["checked"] < STAT_EVERY_S:
        return _cache["lock"]
    _cache["checked"] = now
    try:
        mt = os.stat(LOCK).st_mtime
    except OSError:
        _cache.update(mtime=None, lock=None)
        return None
    if mt != _cache["mtime"]:
        try:
            with open(LOCK, encoding="utf-8") as fh:
                d = json.load(fh)
        except (OSError, ValueError):
            d = None   # arch-ok: 锁文件写到一半 / 坏了：本层不拦，第 1 层（lock_guard 失败关闭）与第 3、4 层兜底
        _cache.update(mtime=mt, lock=d)
    d = _cache["lock"]
    if not d or not d.get("active") or float(d.get("expires_t") or 0) <= now:
        return None
    return d


def rel_frozen(path) -> str | None:
    """路径落在冻结目录（且不在豁免里）→ 相对路径；否则 None"""
    if isinstance(path, int):
        return None
    if isinstance(path, bytes):
        path = os.fsdecode(path)
    p = os.path.normcase(os.path.abspath(os.fspath(path)))
    if not (p == ROOT or p.startswith(ROOT + os.sep)):
        return None
    rel = os.path.relpath(p, ROOT).replace(os.sep, "/")
    top = rel.split("/", 1)[0]
    if top not in FROZEN or rel in EXEMPT_FILES or rel.startswith(EXEMPT_PREFIX):
        return None
    return rel


def _is_write_open(args) -> bool:
    _path, mode, flags = (list(args) + [None, None, None])[:3]
    if isinstance(mode, str) and any(c in mode for c in "wax+"):
        return True
    return isinstance(flags, int) and bool(flags & _WRITE_FLAGS)


def _exempt_process(lock: dict) -> bool:
    return os.environ.get("NS_FREEZE_EXEMPT") == "1" or str(lock.get("pid")) == str(os.getpid())


def check(event: str, args) -> None:
    """可测的核心：该拒绝就抛 PermissionError，否则什么都不做"""
    if event == "open":
        if not _is_write_open(args):
            return
        targets = [args[0]]
    elif event in ("os.rename", "os.replace"):
        targets = [args[0], args[1]]
    elif event in ("os.remove", "os.rmdir", "os.mkdir"):
        targets = [args[0]]
    else:
        return
    rels = [r for r in (rel_frozen(t) for t in targets) if r]
    if not rels:
        return
    lock = _lock()
    if not lock or _exempt_process(lock):
        return
    raise PermissionError(f"{lock.get('sv')} 冻结中（K-OPS-Y03 / K-OPS-F08）：不许写 {rels[0]}，解冻后再改")


def _hook(event: str, args) -> None:
    global _busy
    if _busy or event not in ("open", "os.rename", "os.replace", "os.remove", "os.rmdir", "os.mkdir"):
        return
    _busy = True
    try:
        check(event, args)
    except PermissionError:
        raise
    except Exception:   # noqa: BLE001  # arch-ok: 守卫自身出错一律放行，绝不让业务进程因守卫挂掉
        return
    finally:
        _busy = False


def install() -> None:
    if os.environ.get("NS_FREEZE_GUARD", "").lower() in ("off", "0", "no"):
        return
    sys.addaudithook(_hook)
