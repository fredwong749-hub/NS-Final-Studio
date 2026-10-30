"""
给 gpu3 上 Docker 里的 Qwen 智能体派任务（信箱接口 :8099，规则见 docs/qwen_comms.md）。

自动开 ssh 隧道（ssh gpu33），提交任务原文，等结果，把 Qwen 的回复原样打印，交付物下载到本地。

用法:
    uv run python tools/qwen_task.py "任务原文"                      # 提交并等结果
    uv run python tools/qwen_task.py --file 任务.txt --kind script    # 任务原文从文件读
    uv run python tools/qwen_task.py --no-wait "任务原文"            # 只提交，打印任务编号
    uv run python tools/qwen_task.py --get <任务编号>                 # 查状态 / 取结果
    uv run python tools/qwen_task.py --list                          # 列出所有任务
交付物默认下载到 data/qwen_tasks/<任务编号>/（--out 改目录）。
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def open_tunnel() -> tuple[subprocess.Popen, str]:
    local = free_port()
    p = subprocess.Popen(["ssh", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                          "-o", "ServerAliveInterval=15", "-L", f"{local}:127.0.0.1:8099", "gpu33"])
    base = f"http://127.0.0.1:{local}"
    for _ in range(30):
        try:
            with urllib.request.urlopen(base + "/health", timeout=2):
                return p, base
        except OSError:
            pass
        if p.poll() is not None:
            sys.exit("ssh 隧道没建起来（ssh gpu33 能不能连上？）")
        time.sleep(1)
    p.terminate()
    sys.exit("gpu3 信箱 :8099 没有响应")


def call(base: str, path: str, body: dict | None = None, raw: bool = False):
    req = urllib.request.Request(base + path, json.dumps(body).encode() if body is not None else None,
                                 {"Content-Type": "application/json"} if body is not None else {})
    with urllib.request.urlopen(req, timeout=60) as r:
        data = r.read()
        if raw:  # 交付物原样落盘，.json 交付物也不解析
            return data
        return json.loads(data) if r.headers.get_content_type() == "application/json" else data


def download(base: str, tid: str, out: Path) -> list[Path]:
    try:
        files = call(base, f"/files/{tid}/")
    except urllib.error.HTTPError:
        return []
    got = []
    for rel in files:
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(call(base, f"/files/{tid}/" + urllib.parse.quote(rel), raw=True))
        got.append(dst)
    return got


def show(base: str, tid: str, out_root: Path) -> str:
    t = call(base, f"/tasks/{tid}")
    print(f"任务 {tid}：{t['status']}")
    res = t.get("result") or {}
    if res.get("output"):
        print("\n--- Qwen 回复（原样）---\n" + res["output"].rstrip())
    if res.get("error"):
        print(f"\n错误：{res['error']}")
    if t["status"] in ("done", "failed"):
        got = download(base, tid, out_root / tid)
        if got:
            print(f"\n交付物 {len(got)} 个 → {out_root / tid}")
            for g in got:
                print(f"  {g.relative_to(out_root / tid)}")
    return t["status"]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("text", nargs="?")
    ap.add_argument("--file", help="任务原文从文件读（UTF-8）")
    ap.add_argument("--kind", default="other", help="script / lora / blender / crawl / image_request / other")
    ap.add_argument("--from", dest="sender", default="project-owner")
    ap.add_argument("--no-wait", action="store_true")
    ap.add_argument("--get")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--out", default=str(ROOT / "data" / "qwen_tasks"))
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    out_root = Path(a.out)

    tunnel, base = open_tunnel()
    try:
        if a.list:
            for t in call(base, "/tasks"):
                print(f"{t['id']}  {t['status']:8}  {t['from']}  {t['created_at']}")
            return 0
        if a.get:
            try:
                show(base, a.get, out_root)
            except urllib.error.HTTPError as e:
                print(f"任务 {a.get} 查不到（HTTP {e.code}，可能已被撤到 cancelled）")
                return 1
            return 0
        text = Path(a.file).read_text("utf-8") if a.file else a.text
        if not text or not text.strip():
            ap.error("需要任务原文（参数或 --file）")
        tid = call(base, "/tasks", {"from": a.sender, "text": text, "meta": {"kind": a.kind}})["id"]
        print(f"已提交：{tid}")
        if a.no_wait:
            print(f"之后查结果：uv run python tools/qwen_task.py --get {tid}")
            return 0
        print("等待 Qwen 完成（Ctrl+C 只停止等待，任务继续在 gpu3 上跑）…")
        try:
            while True:
                try:
                    if call(base, f"/tasks/{tid}")["status"] not in ("queued", "running"):
                        break
                except urllib.error.HTTPError as e:  # 封板修复：404 = 任务被撤走，不是断线（HTTPError 是 OSError 的子类）
                    print(f"\n任务 {tid} 查不到了（HTTP {e.code}，可能已被撤到 cancelled）")
                    return 1
                except OSError:  # 跳板机偶尔断线：重开隧道接着等
                    tunnel.terminate()
                    tunnel, base = open_tunnel()
                time.sleep(10)
        except KeyboardInterrupt:
            print(f"\n已停止等待。之后查结果：uv run python tools/qwen_task.py --get {tid}")
            return 0
        return 0 if show(base, tid, out_root) == "done" else 1
    finally:
        tunnel.terminate()


if __name__ == "__main__":
    sys.exit(main())
