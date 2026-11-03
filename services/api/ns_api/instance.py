"""正式实例判定（RESTARTFIX-O，ISS-1103-011049-7420，总调度 P0）。

事故：SENTINEL S10 每 10 分钟跑 tools/qa/decision_check.py，它的 pinned_api 用 `TestClient(ns_api.app)` 起一份进程内 app（真实 data/），
TestClient 会跑完全部 startup 事件——JOBS.restore（把真 API 在跑的任务标 failed）、EPROD / PJ 恢复、owner_pick replay（补执行项目方决定）、
postflight 扫描——每个只活 45–60 s（api_lifecycle 00:18 / 00:28 / … / 01:10），成了对真实数据的第二个推进入口；
00:59 那次 replay 中途进程没了，v2cast-ch_tang_yao 停在 accepted。

规则：会改真实数据 / 重派任务的启动副作用只在“正式实例”上跑：
  1) 环境变量 NS_API_MANAGED=1——只由 tools/factory/api_watchdog.py 给它起的 uvicorn 子进程设（restart_api.ps1 / laptop_autostart.ps1 都经看门狗起）；
  2) 不是预检（NS_API_PREFLIGHT）、不是 pytest；
  3) 拿到单实例锁 data/ops/api_primary_<port>.lock（进程活着就一直持有，进程没了系统自动释放）——同端口第二份正式实例拿不到；
  4) 需要确认“自己就是 :<port> 上那一份”的（owner_pick replay，后台线程）再调 holds_port()：GET /api/_instance 返回的 token 等于本进程的。
"""
from __future__ import annotations

import json
import os
import secrets
import sys
import time
import urllib.request
from pathlib import Path

TOKEN = secrets.token_hex(8)
_LOCK_FH = None
_DECIDED: dict = {}


def port() -> int:
    try:
        return int(os.environ.get("NS_API_PORT") or 8800)
    except ValueError:
        return 8800


def _lock_path() -> Path:
    # ISS-1103-014614-9db2(4)：跟数据目录走（ns_render.pipeline.DATA，随 NS_PROJECT_ROOT / 测试换目录），不固定在仓库 data/
    try:
        from ns_render import pipeline as P  # noqa: PLC0415
        data = Path(P.DATA)
    except Exception:  # noqa: BLE001  # arch-ok: 导入不到就退回仓库 data/
        data = Path(__file__).resolve().parents[3] / "data"
    return data / "ops" / f"api_primary_{port()}.lock"


def _try_lock(path: Path) -> bool:
    """独占锁：Windows msvcrt.locking / 其他 fcntl.flock；文件句柄放模块全局，进程活着就一直持有"""
    global _LOCK_FH
    path.parent.mkdir(parents=True, exist_ok=True)
    fh = open(path, "a+b")  # noqa: SIM115
    try:
        if os.name == "nt":
            import msvcrt  # noqa: PLC0415
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl  # noqa: PLC0415
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        fh.close()
        return False
    try:   # 锁区之外写持有者信息（只是给人看的，判定只认锁）
        fh.seek(16)
        fh.truncate()
        fh.write(json.dumps({"pid": os.getpid(), "port": port(), "at": time.strftime("%Y-%m-%dT%H:%M:%S")}).encode())
        fh.flush()
    except OSError:  # arch-ok: 写说明失败不影响持锁
        pass
    _LOCK_FH = fh
    return True


def why_not() -> str | None:
    """None = 正式实例，可以跑启动副作用；否则返回原因（第一次判定后缓存）"""
    if "why" in _DECIDED:
        return _DECIDED["why"]
    if os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules:
        why = "pytest"
    elif os.environ.get("NS_API_PREFLIGHT"):
        why = "预检实例（NS_API_PREFLIGHT）"
    elif os.environ.get("NS_API_MANAGED") != "1":
        why = "不是看门狗管理的正式实例（没有 NS_API_MANAGED=1：TestClient / 手起 uvicorn / 进程内导入）"
    elif not _try_lock(_lock_path()):
        why = f"同端口 :{port()} 已有一份正式实例持有单实例锁"
    else:
        why = None
    _DECIDED["why"] = why
    return why


def startup_side_effects_allowed() -> bool:
    return why_not() is None


def holds_port(timeout_s: float = 120.0, sleep=time.sleep) -> bool:
    """等到 :port 能回 /api/_instance 且 token 是本进程的 = 本进程就是在 :port 上服务的那一份（uvicorn 跑完 startup 才绑端口，所以要等）"""
    end = time.time() + timeout_s
    while True:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{port()}/api/_instance", timeout=3) as r:  # noqa: S310 — 本机
                if json.loads(r.read().decode("utf-8")).get("token") == TOKEN:
                    return True
        except Exception:  # noqa: BLE001  # arch-ok: 还没绑上 / 别人占着 → 继续等，到点返回 False
            pass
        if time.time() >= end:
            return False
        sleep(1.0)


def info() -> dict:
    return {"pid": os.getpid(), "token": TOKEN, "port": port(), "managed": os.environ.get("NS_API_MANAGED") == "1",
            "side_effects": startup_side_effects_allowed(), "why_not": why_not()}
