"""远程命令闸门（NETFIX P0 11-02，总调度 fredw-2b 派；规则 K-OPS-N07）。

项目方 00:0x 原话：“服务器连接的问题还蛮严重的，一直在断……找一个更 stable 的方法……这个问题是 P0”。
根因（总调度 00:07 实测）：笔记本上 26 个 ssh.exe，到跳板 ESTABLISHED 13 / TIME_WAIT 12——十几个后台程序各自每次新建 ssh，
每次要 6–7 s 握手；跳板 sshd MaxStartups 默认 10:30:100，同时握手 > 10 就随机丢 → Connection reset / banner timeout。

做法：远程命令 / 文件传输一律复用 WSL OpenSSH 的常驻主连接（ControlMaster，由 tunnel_supervisor 的 gpu33-cmd / gpu36-cmd 托着）：
  wsl.exe -d Ubuntu-24.04 --exec ssh -S <sock> -o ControlMaster=no -o ProxyCommand=false <host> <命令>
ProxyCommand=false = 只许复用：主连接不在时 0.1 s 内失败，绝不新建握手（11-02 00:2x 实测）。
  · rssh.run(host, cmd, input=..., timeout=...)：显式调用（新代码用这个）
  · rewrite(argv)：把一条 ["ssh", ..., host, cmd...] 改写成上面的形式；venv 的 sitecustomize 用它拦截所有 subprocess 起的 ssh
    （只拦 ssh 到 gpu33 / gpu36、且不带 -L/-R/-D/-W/-N/-M/-f/-S/-O 的命令调用；scp 不拦；别的不碰）
安全阀：环境变量 NS_SSH_SHIM=off → 一律不改写（直接调 ssh）。监管进程心跳过期（> 90 s）也不改写（退回直接 ssh，免得全断）。
服务器上的 venv 不装 shim（只在笔记本）。
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATUS = ROOT / "data/netfix/net_status.json"
WSL = ["C:/Windows/System32/wsl.exe", "-d", "Ubuntu-24.04", "--exec"]
SOCK = {"gpu33": "/home/fredw/.ssh/nsnf/gpu33-cmd.sock", "gpu36": "/home/fredw/.ssh/nsnf/gpu36-cmd.sock"}
POOL = {h: [f"/home/fredw/.ssh/nsnf/{h}-{k}.sock" for k in ("cmd", "cmd2", "cmd3", "cmd4")] for h in SOCK}   # 每台 4 条（服务器 MaxSessions 10）


def pick_sock(host: str) -> str:
    """在监管进程报“up”的主连接里随机挑一条分摊会话；读不到状态就用第一条"""
    import random
    try:
        hs = json.loads(STATUS.read_text(encoding="utf-8")).get("hosts") or {}
        up = [hs[k]["sock"] if "sock" in hs[k] else f"/home/fredw/.ssh/nsnf/{k}.sock" for k in hs
              if k.startswith(host + "-cmd") and hs[k].get("state") == "up"]
    except (OSError, ValueError, KeyError):
        up = []
    return random.choice(up) if up else SOCK[host]
ARG_OPTS = set("bcDEeFIiJLlmOoPpQRSWwB")          # 带参数的 ssh 选项
SKIP_OPTS = set("LRDWNMfSO")                        # 出现就不改写（转发 / 主连接 / 控制命令）
DROP_O = ("controlmaster", "controlpath", "controlpersist", "proxyjump", "proxycommand", "identityfile", "identitiesonly",
          "userknownhostsfile", "stricthostkeychecking", "hostkeyalias")
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def enabled() -> bool:
    if os.environ.get("NS_SSH_SHIM", "").lower() in ("off", "0", "no"):
        return False
    try:
        return time.time() - STATUS.stat().st_mtime < 90       # 监管进程在岗（主连接由它托着）
    except OSError:
        return False


def rewrite(argv) -> list[str] | None:
    """→ 改写后的 argv；不该拦的返回 None"""
    if not isinstance(argv, (list, tuple)) or not argv:
        return None
    exe = os.path.basename(str(argv[0])).lower()
    if exe not in ("ssh", "ssh.exe"):
        return None
    kept: list[str] = []
    i, host = 1, None
    a = [str(x) for x in argv]
    while i < len(a):
        x = a[i]
        if x == "--":
            i += 1
            break
        if x.startswith("-") and len(x) > 1:
            flags = x[1:]
            for j, ch in enumerate(flags):
                if ch in SKIP_OPTS:
                    return None
                if ch in ARG_OPTS:
                    val = flags[j + 1:] or (a[i + 1] if i + 1 < len(a) else "")
                    if not flags[j + 1:]:
                        i += 1
                    if ch == "o":
                        if not val.split("=", 1)[0].strip().lower() in DROP_O:
                            kept += ["-o", val]
                    elif ch in "lp":                # 用户 / 端口对复用无意义但保留无害：丢掉，免得和主连接不一致
                        pass
                    # -i / -F / -J / 其它带参选项：主连接已认证，丢弃
                    break
                kept.append("-" + ch)               # 无参数标志（-T -n -q -t -v -4 -C ...）
            i += 1
            continue
        host = x
        i += 1
        break
    if host is None:
        return None
    if "@" in host:
        user, h = host.split("@", 1)
        if user != "root":
            return None
        host = h
    if host not in SOCK:
        return None
    rest = a[i:]
    if not rest:                                     # 交互式登录不拦
        return None
    return WSL + ["ssh", "-S", pick_sock(host), "-o", "ControlMaster=no", "-o", "ProxyCommand=false", "-o", "BatchMode=yes",
                  *kept, host, *rest]


def run(host: str, cmd: str, input: bytes | None = None, timeout: float = 900, check: bool = False) -> subprocess.CompletedProcess:
    """显式复用主连接执行远程命令（主连接不在 → 立刻失败 rc=255，不新建握手）"""
    argv = rewrite(["ssh", host, cmd]) if enabled() else None
    argv = argv or ["ssh", "-o", "BatchMode=yes", host, cmd]
    return subprocess.run(argv, input=input, capture_output=True, timeout=timeout, check=check, creationflags=NOWIN)


def status() -> dict:
    try:
        d = json.loads(STATUS.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return {h: (d.get("hosts") or {}).get(f"{h}-cmd", {}).get("state") for h in SOCK}
