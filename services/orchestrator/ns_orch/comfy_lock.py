"""
T44：本机 ComfyUI 单一调度——画布渲染队列（ns_api 后台线程）与编排器子进程不同时占用 ComfyUI。

一把跨进程文件锁：<仓库>/data/comfy.lock（NS_COMFY_LOCK 可改；与 NS_PROJECT_ROOT 无关，全机一把）。
  - Windows 用 msvcrt.locking，POSIX 用 fcntl.flock；进程崩了操作系统自动放锁，不会留死锁。
  - 同一进程里另开一个句柄也拿不到（两种实现都是按句柄 / 打开文件描述），所以线程之间同样互斥。
  - 持有者信息写在 comfy.lock.json（只用于显示「谁在占用」，判断以文件锁为准）。

用法：
  画布：每个渲染 / 资产任务 `with hold("canvas", job=…, wait=…)`（排队等待，等的时候任务上显示占用者）。
  编排器：出图子进程整段 `try_hold("orchestrator", …)`，拿不到就 Waiting（下一轮再试，不计失败）。
已知限制（见 docs/TASKS.md T44 计划）：编排器按「整集一个子进程」持锁，期间画布任务会一直等到这一集出完；
细化到每镜持锁需要改 tools/render_batch.py（不在本模块范围）。
"""
from __future__ import annotations

import json
import os
import time
from contextlib import contextmanager
from pathlib import Path

from ns_api.project_ctx import REPO

LOCK_PATH = Path(os.environ.get("NS_COMFY_LOCK") or (REPO / "data" / "comfy.lock"))

if os.name == "nt":
    import msvcrt

    def _try_lock(fh) -> bool:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            return True
        except OSError:
            return False

    def _unlock(fh) -> None:
        try:
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        except OSError:
            pass
else:
    import fcntl

    def _try_lock(fh) -> bool:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            return False

    def _unlock(fh) -> None:
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass


def _info_path() -> Path:
    return LOCK_PATH.with_name(LOCK_PATH.name + ".json")


def holder() -> dict | None:
    """当前占用者（只作显示）：锁空闲时返回 None"""
    if is_free():
        return None
    try:
        return json.loads(_info_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"who": "unknown"}


def is_free() -> bool:
    fh = _open()
    try:
        if _try_lock(fh):
            _unlock(fh)
            return True
        return False
    finally:
        fh.close()


def _open():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    fh = open(LOCK_PATH, "a+b")
    return fh


class Busy(Exception):
    def __init__(self, info: dict | None):
        who = (info or {}).get("who", "unknown")
        what = (info or {}).get("what") or ""
        super().__init__(f"本机 ComfyUI 正被 {who} 占用" + (f"（{what}）" if what else ""))
        self.info = info


def acquire(who: str, what: str = "", *, timeout: float | None = None, poll: float = 1.0, on_wait=None):
    """拿锁 → 文件句柄（交给 release）。timeout=0 只试一次；None = 一直等。拿不到抛 Busy。
    on_wait(info) 在每次等待时回调（画布用来在任务上显示占用者）。"""
    t0 = time.monotonic()
    while True:
        fh = _open()
        if _try_lock(fh):
            try:
                _info_path().write_text(json.dumps({"who": who, "what": what, "pid": os.getpid(),
                                                    "since": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())},
                                                   ensure_ascii=False), encoding="utf-8")
            except OSError:
                pass
            return fh
        fh.close()
        info = holder()
        if timeout is not None and time.monotonic() - t0 >= timeout:
            raise Busy(info)
        if on_wait:
            on_wait(info)
        time.sleep(poll)


def release(fh) -> None:
    try:
        _info_path().unlink(missing_ok=True)
    except OSError:
        pass
    _unlock(fh)
    fh.close()


@contextmanager
def hold(who: str, what: str = "", *, timeout: float | None = None, poll: float = 1.0, on_wait=None):
    fh = acquire(who, what, timeout=timeout, poll=poll, on_wait=on_wait)
    try:
        yield
    finally:
        release(fh)
