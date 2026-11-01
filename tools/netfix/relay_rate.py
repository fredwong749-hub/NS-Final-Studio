"""估算“跳板每小时新建连接数”（NETFIX r2 验收）：每 2 s 采一次笔记本到跳板入口（香港 47.243.63.181:22、直连 183.23.230.84:19422）
的 TCP 连接（Windows netstat + WSL ss），按 (本地地址, 本地端口) 去重计新连接数，换算成每小时。
每条到入口的新 TCP = 跳板上一次新的 ssh 会话（香港那条是 hkjump 转进跳板）。
  .venv/Scripts/python.exe tools/netfix/relay_rate.py --minutes 5 --tag before   → data/netfix/conn_watch_rate.jsonl
"""
import argparse
import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data/netfix/conn_watch_rate.jsonl"
ENTRIES = ("47.243.63.181:22", "183.23.230.84:19422")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def snap() -> set:
    keys = set()
    try:
        out = subprocess.run(["netstat", "-ano", "-p", "TCP"], capture_output=True, text=True, timeout=30, creationflags=NOWIN).stdout
    except (OSError, subprocess.TimeoutExpired):
        out = ""
    for ln in out.splitlines():
        p = ln.split()
        if len(p) >= 4 and p[2] in ENTRIES and p[3] in ("ESTABLISHED", "SYN_SENT"):
            keys.add(("win", p[1], p[2]))
    try:
        w = subprocess.run(["C:/Windows/System32/wsl.exe", "-d", "Ubuntu-24.04", "--exec", "ss", "-tn"], capture_output=True, text=True,
                           timeout=30, creationflags=NOWIN).stdout
    except (OSError, subprocess.TimeoutExpired):
        w = ""
    for ln in w.splitlines():
        p = ln.split()
        if len(p) >= 5 and p[4].replace("[::ffff:", "").replace("]", "") in ENTRIES:
            keys.add(("wsl", p[3], p[4]))
    return keys


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=5)
    ap.add_argument("--tag", default="")
    a = ap.parse_args()
    t0 = time.time()
    first = snap()
    seen = set(first)
    peak = len(first)
    while time.time() - t0 < a.minutes * 60:
        time.sleep(2)
        cur = snap()
        seen |= cur
        peak = max(peak, len(cur))
    new = len(seen - first)
    span = time.time() - t0
    rec = {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "tag": a.tag, "window_s": round(span), "new_conns": new,
           "per_hour": round(new * 3600 / span), "concurrent_start": len(first), "concurrent_peak": peak,
           "entries": list(ENTRIES)}
    print(json.dumps(rec, ensure_ascii=False))
    with open(OUT, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
