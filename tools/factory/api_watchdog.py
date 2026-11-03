""":8800 API 的父进程侧看门狗（总调度 11-02 20:5x：20:28 后 API 被直接结束、没有任何留痕，查不出是谁）。

只做两件事，不自动重启（重启由项目方 / 总调度决定，走 ops/restart_api.ps1）：
  1) 以子进程方式起 uvicorn（参数原样透传），记 started（pid、命令行、谁起的）；
  2) 子进程结束时记 exited（退出码、运行时长）——被强制结束也能看到时间和退出码。
日志：data/ops/api_lifecycle.jsonl（追加，一行一条）。
用法：python tools/factory/api_watchdog.py --by <调用方> -- -m uvicorn ns_api.app:app --port 8800 --host 127.0.0.1
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LOG = Path(os.environ.get("NS_API_LIFECYCLE_LOG") or ROOT / "data/ops/api_lifecycle.jsonl")   # 环境变量只给 restart_api.ps1 的测试用


def log(rec: dict, path: Path | None = None) -> None:
    path = path or LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}, ensure_ascii=False) + "\n")


def child_env(argv: list[str], base: dict | None = None) -> dict:
    """RESTARTFIX-O（ISS-1103-011049-7420）：看门狗起的 uvicorn 才是“正式实例”——NS_API_MANAGED=1 + NS_API_PORT=<--port>；
    ns_api.instance 只在这种实例上放行启动副作用（JOBS.restore / 恢复 / owner_pick replay / postflight 扫描）"""
    env = dict(os.environ if base is None else base)
    env["NS_API_MANAGED"] = "1"
    if "--port" in argv and argv.index("--port") + 1 < len(argv):
        env["NS_API_PORT"] = argv[argv.index("--port") + 1]
    env.pop("NS_API_PREFLIGHT", None)
    return env


def run(argv: list[str], by: str, popen=subprocess.Popen) -> int:
    t0 = time.time()
    env = child_env(argv)
    p = popen([sys.executable, *argv], cwd=ROOT, env=env, stdin=subprocess.DEVNULL, close_fds=True)
    log({"event": "started", "pid": p.pid, "watchdog_pid": os.getpid(), "by": by, "cmd": " ".join(argv), "managed": True, "port": env.get("NS_API_PORT")})
    try:
        rc = p.wait()
    except KeyboardInterrupt:      # 看门狗自己被停：先记一笔
        log({"event": "watchdog_interrupted", "pid": p.pid, "by": by})
        raise
    log({"event": "exited", "pid": p.pid, "rc": rc, "ran_s": round(time.time() - t0, 1), "by": by,
         "note": "rc=1 且没有 shutdown 记录 = 多半是被外部强制结束（Stop-Process -Force / taskkill /F）"})
    return rc


DETACH_FLAGS = (getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
BREAKAWAY = getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)


def detach(argv: list[str], by: str, out: str, err: str, pidfile: str = "", popen=subprocess.Popen) -> int:
    """RESTARTFIX-O（总调度 01:48 受控重启后 P1）：restart_api.ps1 起看门狗时，看门狗曾经
    ①继承调用方的 stdout/stderr 管道句柄（Start-Process 带重定向 = bInheritHandles），调用方一直等不到 EOF（01:48 那次挂了 >10 分钟）；
    ②挂在调用方会话的作业对象下，会话一结束整棵被带走（resident 01:16 就是这样）。
    这里另起一份看门狗：DETACHED_PROCESS + 新进程组 + CREATE_BREAKAWAY_FROM_JOB，stdin=DEVNULL、stdout/stderr 只给日志文件，
    close_fds=True（Windows 上只继承这三个句柄），然后立刻返回；新看门狗 pid 写进 pidfile（不经管道传）"""
    cmd = [sys.executable, str(Path(__file__).resolve()), "--by", by, "--", *argv]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(err).parent.mkdir(parents=True, exist_ok=True)
    with open(out, "ab") as fo, open(err, "ab") as fe:
        kw = {"cwd": str(ROOT), "stdin": subprocess.DEVNULL, "stdout": fo, "stderr": fe, "close_fds": True, "env": dict(os.environ)}
        breakaway = True
        if os.name == "nt":
            try:
                p = popen(cmd, creationflags=DETACH_FLAGS | BREAKAWAY, **kw)
            except OSError:            # 作业对象不允许脱离：退一步只脱离控制台 / 进程组，并记一笔
                breakaway = False
                p = popen(cmd, creationflags=DETACH_FLAGS, **kw)
        else:
            p = popen(cmd, start_new_session=True, **kw)
    log({"event": "detached", "watchdog_pid": p.pid, "by": by, "breakaway": breakaway, "launcher_pid": os.getpid(),
         "note": "" if breakaway else "作业对象不允许 CREATE_BREAKAWAY_FROM_JOB：调用方会话结束时仍可能被带走"})
    if pidfile:
        tmp = Path(pidfile).with_suffix(".tmp")
        tmp.write_text(json.dumps({"pid": p.pid, "breakaway": breakaway}), encoding="utf-8")
        os.replace(tmp, pidfile)
    return p.pid


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    head, tail = (a[:a.index("--")], a[a.index("--") + 1:]) if "--" in a else (a, [])
    opt = {}
    flags = set()
    i = 0
    while i < len(head):
        if head[i] == "--detach":
            flags.add("detach")
            i += 1
        elif head[i] in ("--by", "--out", "--err", "--pidfile") and i + 1 < len(head):
            opt[head[i][2:]] = head[i + 1]
            i += 2
        else:
            tail = head[i:] + tail       # 兼容旧写法：没有 "--" 时其余参数原样给 uvicorn
            break
    by = opt.get("by", "unknown")
    if "detach" in flags:
        logs = ROOT / "ops" / "logs"
        detach(tail, by, opt.get("out") or str(logs / "api_watchdog.out.log"), opt.get("err") or str(logs / "api_watchdog.err.log"), opt.get("pidfile", ""))
        return 0
    return run(tail, by)


if __name__ == "__main__":
    raise SystemExit(main())
