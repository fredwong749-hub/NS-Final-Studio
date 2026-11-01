""":8800 整体卡顿抓现场（DATAALIGN 2026-11-01，笔记 docs/dataalign/STALL_NOTES.md）。

每秒探一次轻接口（默认 /api/comfy-lock），探测超过 --slow 秒（或超时）→ 立刻 py-spy dump 服务器全部线程（--nonblocking 不停进程），
写 docs/dataalign/stalls/<时间>.txt；探测延迟逐条记 docs/dataalign/stalls/probe.jsonl。只读：不改任何数据、不起停服务。

    .venv/Scripts/python.exe tools/qa/data_parity/stall_watch.py --minutes 120 [--slow 2] [--path /api/comfy-lock]
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = ROOT / "docs" / "dataalign" / "stalls"


def server_pid() -> int | None:
    try:
        out = subprocess.run(["powershell", "-NoProfile", "-Command",
                              "Get-NetTCPConnection -LocalPort 8800 | Where-Object { $_.OwningProcess -ne 0 } | ForEach-Object { $_.OwningProcess } | Where-Object { (Get-Process -Id $_ -ErrorAction SilentlyContinue).ProcessName -like 'python*' } | Select-Object -First 1"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        return int(out.splitlines()[0]) if out else None   # 监听行的 PID 在这台机器上显示 0，取已建立连接的 python 进程
    except Exception:  # noqa: BLE001
        return None


def dump(pid: int, tag: str) -> Path:
    OUT.mkdir(parents=True, exist_ok=True)
    f = OUT / f"{time.strftime('%Y%m%d_%H%M%S')}_{tag}.txt"
    out = []
    # --nonblocking 读进程内存时偶尔撞上正在变的帧（os error 299）→ 重试；两次都失败再用阻塞模式（暂停进程一瞬，卡顿时可以接受）
    for mode in (["--nonblocking"], ["--nonblocking"], []):
        try:
            r = subprocess.run(["uv", "run", "--with", "py-spy", "py-spy", "dump", "--pid", str(pid), *mode],
                               capture_output=True, text=True, timeout=60, cwd=ROOT, encoding="utf-8", errors="replace")
            out.append(f"=== py-spy dump {' '.join(mode) or '(blocking)'} rc={r.returncode}\n{r.stdout}\n--- stderr ---\n{r.stderr}")
            if r.returncode == 0 and "Thread" in r.stdout:
                break
        except Exception as e:  # noqa: BLE001
            out.append(f"dump failed: {e!r}")
    f.write_text("\n".join(out), encoding="utf-8")
    return f


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=120)
    ap.add_argument("--slow", type=float, default=2.0)
    ap.add_argument("--path", default="/api/comfy-lock")
    ap.add_argument("--max-dumps", type=int, default=12)
    a = ap.parse_args()
    tok = (ROOT / "data" / "auth" / "viewer_token").read_text(encoding="utf-8").strip()
    pid = server_pid()
    print("server pid", pid, flush=True)
    OUT.mkdir(parents=True, exist_ok=True)
    log = (OUT / "probe.jsonl").open("a", encoding="utf-8")
    end = time.time() + a.minutes * 60
    dumps = 0
    while time.time() < end:
        res: dict = {}
        t0 = time.time()

        def probe():
            try:
                req = urllib.request.Request("http://127.0.0.1:8800" + a.path, headers={"x-ns-viewer-token": tok})
                urllib.request.urlopen(req, timeout=40).read()
                res["ok"] = True
            except Exception as e:  # noqa: BLE001
                res["err"] = repr(e)[:120]
        th = threading.Thread(target=probe, daemon=True)
        th.start()
        th.join(a.slow)
        if th.is_alive():                                  # 还没回来 = 正在卡：现场抓
            pid = pid or server_pid()
            if pid and dumps < a.max_dumps:
                f = dump(pid, "stall")
                dumps += 1
                print(time.strftime("%H:%M:%S"), "STALL >", a.slow, "s → dump", f.name, flush=True)
            th.join(45)
        dt = round(time.time() - t0, 3)
        log.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "path": a.path, "s": dt, **res}, ensure_ascii=False) + "\n")
        log.flush()
        if dt > a.slow:
            print(time.strftime("%H:%M:%S"), "slow", dt, res.get("err", ""), flush=True)
            if not res.get("ok"):
                pid = server_pid()                         # 可能重启了
        time.sleep(max(0.0, 1.0 - (time.time() - t0)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
