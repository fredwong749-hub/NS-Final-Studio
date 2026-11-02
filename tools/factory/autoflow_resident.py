"""剧本写作推进的常驻服务（总调度 11-02 19:4x：HOLLYWOOD 的 autoflow watch 挂在会话下，会话一结束就停 → 做成和 producer 一样的常驻）。

在笔记本上跑（写作包 / 写手产物都在笔记本）：
  - 单实例：data/factory/autoflow_resident.lock（O_EXCL 建，记 pid；锁主进程已死 = 陈旧、接管），第二份起不来；
  - 每 interval 秒读 config/pipeline/runs.json，只推进状态在 ADVANCE_STATUSES 的剧（paused / frozen / archived 一律不碰，K-OPS-F20）；
  - 推进 = 对 run_dir 里写手已交稿（.done）的集起 `autoflow.py run --source daemon`（与 HOLLYWOOD watch 同一实现，跨进程推进锁在 autoflow 里）；
  - 不写任何 control / 暂停字段（不清别人的暂停，A-09 ③ / K-OPS-F26）；
  - 心跳 data/factory/autoflow_resident.json（pid / t / 在推进的剧 / 最近一次起的集），SENTINEL 按心跳年龄判掉线。
用法：.venv/Scripts/python.exe tools/factory/autoflow_resident.py [--interval 30] [--once]；拉起 / 重启：ops/restart_autoflow.ps1
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOCK = ROOT / "data/factory/autoflow_resident.lock"
HEARTBEAT = ROOT / "data/factory/autoflow_resident.json"
# 写作推进只对“在做”的剧：preparing（V2 剧本写作阶段）/ active / producing；paused、frozen、archived 一律不碰
ADVANCE_STATUSES = ("preparing", "active", "producing")


def _load(name: str, rel: str):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=30)
        return str(pid) in (r.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(lock: Path = LOCK) -> bool:
    """单实例：拿到锁 = True；别的活进程拿着 = False；锁主进程已死 = 接管"""
    lock.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), "at": time.time()}))
            return True
        except FileExistsError:
            try:
                pid = int(json.loads(lock.read_text(encoding="utf-8")).get("pid") or 0)
            except (OSError, ValueError):   # arch-ok: 锁文件坏 = 当作陈旧，接管
                pid = 0
            if _pid_alive(pid):
                return False
            lock.unlink(missing_ok=True)
    return False


def release_lock(lock: Path = LOCK) -> None:
    try:
        if int(json.loads(lock.read_text(encoding="utf-8")).get("pid") or 0) == os.getpid():
            lock.unlink(missing_ok=True)
    except (OSError, ValueError):   # arch-ok: 锁已不在 / 坏了 = 没什么可放
        pass


def advance_runs(root: Path = ROOT) -> list[str]:
    """runs.json 里可推进的剧（状态在 ADVANCE_STATUSES）；登记表读不出 = 一部都不推（失败关闭）"""
    try:
        d = json.loads((root / "config/pipeline/runs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不出 = 不推进任何剧
        return []
    return sorted(r for r, v in (d.get("runs") or {}).items() if (v or {}).get("status") in ADVANCE_STATUSES)


def _write_hb(rec: dict) -> None:
    HEARTBEAT.parent.mkdir(parents=True, exist_ok=True)
    tmp = HEARTBEAT.with_suffix(".tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, HEARTBEAT)


def tick(procs: dict, af=None, runs_mod=None, spawn=None) -> dict:
    """一拍：每部可推进的剧，写手已交稿的集起一个 autoflow run（同一集已在跑就跳过）。返回本拍记录"""
    af = af or _load("autoflow_for_resident", "tools/script_rsi/autoflow.py")
    if runs_mod is None:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from tools.autopilot import runs as runs_mod    # OVERSIGHT-F P2：tools 侧 runs 唯一入口
    spawn = spawn or (lambda rd, ep: subprocess.Popen([sys.executable, str(ROOT / "tools/script_rsi/autoflow.py"), "run", "--run-dir", str(rd),
                                                       "--episode", str(ep), "--import", "dry", "--source", "daemon"], cwd=ROOT,
                                                      env={**os.environ, "PYTHONUTF8": "1"}))
    started = []
    runs = advance_runs()
    for run in runs:
        rd = runs_mod.run_dir(run, ROOT)
        if not rd.is_dir():
            continue
        for ep in af.pending_done(rd):
            key = (run, ep)
            p = procs.get(key)
            if p is not None and p.poll() is None:
                continue
            procs[key] = spawn(rd, ep)
            started.append(f"{run} ep{int(ep):02d}")
    return {"runs": runs, "started": started}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--interval", type=int, default=30)
    ap.add_argument("--once", action="store_true")
    a = ap.parse_args(argv)
    if not acquire_lock():
        print("autoflow_resident 已有一份在跑（data/factory/autoflow_resident.lock），本进程退出")
        return 3
    procs: dict = {}
    last = []
    try:
        while True:
            try:
                r = tick(procs)
                last = r["started"] or last
                _write_hb({"pid": os.getpid(), "t": time.time(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "runs": r["runs"],
                           "last_started": last, "interval_s": a.interval, "by": "tools/factory/autoflow_resident.py"})
            except Exception as e:  # noqa: BLE001  一拍出错只记，不退出（常驻）
                _write_hb({"pid": os.getpid(), "t": time.time(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "error": repr(e)[:300]})
            if a.once:
                return 0
            time.sleep(a.interval)
    finally:
        release_lock()


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
