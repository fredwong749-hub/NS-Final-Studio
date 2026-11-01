"""跳板带宽：按单条连接限速还是总量限速（NETFIX 11-01 23:5x，总调度派）。
并行 N 条 ssh（各自完整握手）各下载 / 上传 SIZE 字节，按“首字节到末字节”计每条速率和总吞吐（不含握手）。
  .venv/Scripts/python.exe tools/netfix/bw_test.py --host gpu33 --streams 1,2,4,8 --kb 384 [--up]
结果追加 data/netfix/bw_test.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/netfix/bw_test.jsonl"
SSH = ["C:/Program Files/Git/usr/bin/ssh.exe", "-F", "config/netfix/ssh_config", "-o", "BatchMode=yes", "-o", "ConnectTimeout=30"]


def one(host: str, size: int, up: bool, res: list, i: int) -> None:
    t0 = time.time()
    if up:
        cmd = SSH + [host, "python3 -c \"import sys,time;d=sys.stdin.buffer;n=0;b=d.read(1);t=time.time();n=len(b)\n"
                           "while True:\n c=d.read(65536)\n if not c: break\n n+=len(c)\nprint(n,round(time.time()-t,2))\""]
        p = subprocess.run(cmd, input=os.urandom(size), capture_output=True, timeout=900)
        try:
            n, dt = p.stdout.decode().split()
            res[i] = {"bytes": int(n), "xfer_s": float(dt), "total_s": round(time.time() - t0, 1)}
        except ValueError:
            res[i] = {"error": p.stderr.decode("utf-8", "replace")[-200:]}
        return
    p = subprocess.Popen(SSH + [host, f"head -c {size} /dev/urandom"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n, tf = 0, None
    while True:
        b = p.stdout.read(16384)
        if not b:
            break
        if tf is None:
            tf = time.time()
        n += len(b)
    p.wait()
    te = time.time()
    res[i] = {"bytes": n, "xfer_s": round(te - (tf or te), 2), "total_s": round(te - t0, 1)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="gpu33")
    ap.add_argument("--streams", default="1,2,4,8")
    ap.add_argument("--kb", type=int, default=384)
    ap.add_argument("--up", action="store_true")
    a = ap.parse_args()
    for n in [int(x) for x in a.streams.split(",")]:
        res = [None] * n
        th = [threading.Thread(target=one, args=(a.host, a.kb * 1024, a.up, res, i)) for i in range(n)]
        t0 = time.time()
        for t in th:
            t.start()
        for t in th:
            t.join()
        ok = [r for r in res if r and "bytes" in r and r["xfer_s"] > 0]
        tot = sum(r["bytes"] for r in ok)
        span = max((r["xfer_s"] for r in ok), default=0)
        rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "host": a.host, "dir": "up" if a.up else "down", "streams": n,
               "per_stream_kBps": [round(r["bytes"] / r["xfer_s"] / 1024, 1) for r in ok],
               "aggregate_kBps": round(tot / span / 1024, 1) if span else None, "wall_s": round(time.time() - t0, 1),
               "errors": [r for r in res if not r or "error" in r]}
        print(json.dumps(rec, ensure_ascii=False), flush=True)
        with open(OUT, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
