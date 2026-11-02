"""统一远程命令入口（NETFIX 11-02，K-OPS-N07/N08）：复用监管进程托管的 WSL 常驻主连接（香港线路优先），不新建握手。
  .venv/Scripts/python.exe tools/netfix/rsh.py gpu33 "nvidia-smi"            # stdout / stderr / 退出码原样
  tar cf - x | .venv/Scripts/python.exe tools/netfix/rsh.py gpu36 "tar xf - -C /tmp"   # stdin 二进制直通
主连接不在 → 立刻失败（rc 255），不会自己去握手；NS_SSH_SHIM=off 时退回直接 ssh（Git ssh + 用户 ~/.ssh/config）。
注意：Windows 自带 OpenSSH 不能用 -F config/netfix/ssh_config（那是 Git ssh / WSL 语法），统一用本入口。"""
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import rssh  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) < 3 or sys.argv[1] not in rssh.SOCK:
        print(__doc__)
        sys.exit(2)
    host, cmd = sys.argv[1], " ".join(sys.argv[2:])
    argv = (rssh.rewrite(["ssh", host, cmd]) if rssh.enabled() else None) or ["ssh", "-o", "BatchMode=yes", host, rssh.with_tz(cmd)]
    sys.exit(subprocess.call(argv, stdin=sys.stdin.buffer if not sys.stdin.isatty() else None))
