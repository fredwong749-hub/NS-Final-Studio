"""venv 级 ssh 闸门（NETFIX P0 11-02，K-OPS-N07）：由 .venv/Lib/site-packages/ns_netfix_ssh_shim.pth 在每个 venv Python 进程启动时加载。
subprocess.Popen 起 ssh 到 gpu33 / gpu36 的命令调用 → tools/netfix/rssh.rewrite 改走 WSL 常驻主连接（不新建握手）。
关掉：NS_SSH_SHIM=off。只在笔记本装（服务器 venv 不装）。任何异常都吞掉、按原样执行。"""
import os
import subprocess

_orig_init = subprocess.Popen.__init__
_R = None


def _rssh():
    global _R
    if _R is None:
        import importlib.util
        spec = importlib.util.spec_from_file_location("ns_netfix_rssh", os.path.join(os.path.dirname(os.path.abspath(__file__)), "rssh.py"))
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        _R = m
    return _R


def _init(self, args, *a, **kw):
    try:
        if isinstance(args, (list, tuple)) and args and os.path.basename(str(args[0])).lower() in ("ssh", "ssh.exe") \
                and os.environ.get("NS_SSH_SHIM", "").lower() not in ("off", "0", "no"):
            R = _rssh()
            if R.enabled():
                new = R.rewrite(args)
                if new:
                    args = new
    except Exception:  # noqa: BLE001
        pass
    _orig_init(self, args, *a, **kw)


if not getattr(subprocess.Popen.__init__, "_ns_netfix", False):
    _init._ns_netfix = True
    subprocess.Popen.__init__ = _init
