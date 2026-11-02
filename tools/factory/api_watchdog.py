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
LOG = ROOT / "data/ops/api_lifecycle.jsonl"


def log(rec: dict, path: Path | None = None) -> None:
    path = path or LOG
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), **rec}, ensure_ascii=False) + "\n")


def run(argv: list[str], by: str, popen=subprocess.Popen) -> int:
    t0 = time.time()
    p = popen([sys.executable, *argv], cwd=ROOT)
    log({"event": "started", "pid": p.pid, "watchdog_pid": os.getpid(), "by": by, "cmd": " ".join(argv)})
    try:
        rc = p.wait()
    except KeyboardInterrupt:      # 看门狗自己被停：先记一笔
        log({"event": "watchdog_interrupted", "pid": p.pid, "by": by})
        raise
    log({"event": "exited", "pid": p.pid, "rc": rc, "ran_s": round(time.time() - t0, 1), "by": by,
         "note": "rc=1 且没有 shutdown 记录 = 多半是被外部强制结束（Stop-Process -Force / taskkill /F）"})
    return rc


def main(argv=None) -> int:
    a = list(sys.argv[1:] if argv is None else argv)
    by = "unknown"
    if "--by" in a:
        i = a.index("--by")
        by, a = a[i + 1], a[:i] + a[i + 2:]
    if a and a[0] == "--":
        a = a[1:]
    return run(a, by)


if __name__ == "__main__":
    raise SystemExit(main())
