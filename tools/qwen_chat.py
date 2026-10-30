"""
在终端里和 gpu3 上的 Qwen 写作模型对话（llama.cpp llama-server，OpenAI 兼容接口）。

自动开 ssh 隧道（ssh gpu33，本地端口 → gpu3 127.0.0.1:<远端端口>），流式输出，保留整段对话历史。

用法（在自己的终端里跑，需要交互输入）:
    uv run python tools/qwen_chat.py                  # 默认连 gpu3 :8097
    uv run python tools/qwen_chat.py --remote-port 8098
    uv run python tools/qwen_chat.py --system "你是短剧编剧"

对话里的命令：/new 清空历史；/system <文本> 换系统提示；/save <文件> 把对话存成 JSON；/quit 退出。
"""
from __future__ import annotations

import argparse
import json
import socket
import subprocess
import sys
import time
import urllib.request

DEFAULT_SYSTEM = "你是短剧项目的写作助手，负责剧本、分镜和画面提示词写作。用中文回答。"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def open_tunnel(remote_port: int) -> tuple[subprocess.Popen, int]:
    local = free_port()
    p = subprocess.Popen(["ssh", "-N", "-o", "BatchMode=yes", "-o", "ExitOnForwardFailure=yes",
                          "-L", f"{local}:127.0.0.1:{remote_port}", "gpu33"])
    for _ in range(30):
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{local}/health", timeout=2) as r:
                if r.status == 200:
                    return p, local
        except OSError:
            pass
        if p.poll() is not None:
            sys.exit("ssh 隧道没建起来（ssh gpu33 能不能连上？）")
        time.sleep(1)
    p.terminate()
    sys.exit(f"gpu3 :{remote_port} 没有响应 /health")


def chat(port: int, messages: list[dict], temperature: float) -> str:
    body = json.dumps({"messages": messages, "stream": True, "temperature": temperature}).encode()
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", body,
                                 {"Content-Type": "application/json"})
    out = []
    with urllib.request.urlopen(req, timeout=3600) as r:
        for line in r:
            line = line.decode("utf-8", "replace").strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            delta = json.loads(line[5:])["choices"][0].get("delta", {})
            piece = delta.get("content") or ""
            if piece:
                out.append(piece)
                print(piece, end="", flush=True)
    print()
    return "".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote-port", type=int, default=8097)
    ap.add_argument("--system", default=DEFAULT_SYSTEM)
    ap.add_argument("--temperature", type=float, default=0.7)
    a = ap.parse_args()
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    tunnel, port = open_tunnel(a.remote_port)
    messages = [{"role": "system", "content": a.system}]
    print(f"已连上 gpu3 Qwen（:{a.remote_port}）。/new 清空  /system <文本>  /save <文件>  /quit")
    try:
        while True:
            try:
                text = input("\n你> ").strip()
            except EOFError:
                break
            if not text:
                continue
            if text == "/quit":
                break
            if text == "/new":
                messages = messages[:1]
                print("（已清空历史）")
                continue
            if text.startswith("/system "):
                messages = [{"role": "system", "content": text[8:].strip()}]
                print("（已换系统提示并清空历史）")
                continue
            if text.startswith("/save "):
                with open(text[6:].strip(), "w", encoding="utf-8") as f:
                    json.dump(messages, f, ensure_ascii=False, indent=1)
                print("（已保存）")
                continue
            messages.append({"role": "user", "content": text})
            print("Qwen> ", end="", flush=True)
            try:
                messages.append({"role": "assistant", "content": chat(port, messages, a.temperature)})
            except KeyboardInterrupt:
                messages.pop()
                print("\n（已中断这条回答）")
    finally:
        tunnel.terminate()
    return 0


if __name__ == "__main__":
    sys.exit(main())
