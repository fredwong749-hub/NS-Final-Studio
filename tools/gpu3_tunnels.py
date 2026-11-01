"""
笔记本 → gpu3 的 ssh 隧道守护（fredw-d9，2026-10-30：画布取 gpu3 首尾帧时桥 502，原因是隧道断了没人重连）。

每 30 秒检查每条隧道的健康接口；连续 2 次失败就重开这条隧道（只重开本工具自己起的 ssh，不碰别的进程）。
端口被别的正常隧道占着时，只要健康检查通过就不动它。

    uv run python tools/gpu3_tunnels.py            # 前台常驻（Ctrl+C 退出，自己起的 ssh 一并关掉）
    uv run python tools/gpu3_tunnels.py --check    # 只检查一次，打印每条隧道的状态
"""
from __future__ import annotations

import argparse
import http.client
import subprocess
import sys
import time
import urllib.request
from datetime import datetime

# 本地端口, gpu3 端口, 健康检查路径（与 services/api/ns_api/readiness.py BRIDGE_URL、tools/qwen_task.py、tools/qwen_chat.py 一致）
TUNNELS = [
    ("bridge", 15180, 5180, "/api/gpu3/health"),
    ("mailbox", 18099, 8099, "/health"),
    # ("qwen-llm", 18098, 8098, "/health"),  # INFRA 2026-10-31 停用：10-30 千问已撤下，gpu33 :8098 不再有服务，守护每分钟重开这条隧道是空转
]
INTERVAL_S, FAILS_BEFORE_RESTART = 30, 2


def log(msg: str) -> None:
    print(f"{datetime.now():%F %T} {msg}", flush=True)


def healthy(port: int, path: str) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=8) as r:
            return r.status == 200
    except (OSError, http.client.HTTPException):  # 封板修复：BadStatusLine / IncompleteRead 不是 OSError，曾让守护整个退出
        return False


def spawn(local: int, remote: int) -> subprocess.Popen:
    return subprocess.Popen(["ssh", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                             "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=3",
                             "-L", f"{local}:127.0.0.1:{remote}", "gpu33"],
                            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if a.check:
        bad = [name for name, local, _, path in TUNNELS if not healthy(local, path)]
        for name, local, remote, path in TUNNELS:
            log(f"{name:9} 127.0.0.1:{local} -> gpu3:{remote}  {'down' if name in bad else 'ok'}")
        return 1 if bad else 0

    mine: dict[str, subprocess.Popen] = {}
    fails = {name: 0 for name, *_ in TUNNELS}
    log("gpu3 tunnels supervisor started")
    try:
        while True:
            for name, local, remote, path in TUNNELS:
                if healthy(local, path):
                    if fails[name]:
                        log(f"{name}: ok again")
                    fails[name] = 0
                    continue
                fails[name] += 1
                if fails[name] < FAILS_BEFORE_RESTART:
                    continue
                p = mine.get(name)
                if p and p.poll() is None:
                    p.terminate()
                    try:
                        p.wait(10)
                    except subprocess.TimeoutExpired:
                        p.kill()
                mine[name] = spawn(local, remote)
                log(f"{name}: down {fails[name]}x, (re)opened ssh -L {local}:127.0.0.1:{remote} gpu33 (pid {mine[name].pid})")
                fails[name] = 0
            time.sleep(INTERVAL_S)
    except KeyboardInterrupt:
        return 0
    finally:
        for p in mine.values():
            if p.poll() is None:
                p.terminate()


if __name__ == "__main__":
    sys.exit(main())
