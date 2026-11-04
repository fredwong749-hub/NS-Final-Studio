"""W46（总调度 05:3x 令）：服务器上的 ep 部分预览（data/episodes/<剧>/_partial/）拉回笔记本同路径，给项目方直接点开看。

大文件走 <host>-hk 单独连接（W21 NETFIX-BULK / 运维 FONG-QUICK：Git sftp -F config/netfix/ssh_config，同 rssh.bulk_put 的走法），
清单走命令主连接（rssh.run_retry，小）。只拉本机没有 / 大小不同的；先写 .part 再改名；不删任何文件。

    .venv/Scripts/python.exe tools/master/partial_pull.py --host gpu36 [--run series10_v2] [--loop --every 300]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/factory"))
import hosts as _HOSTS  # noqa: E402


def remote_root(host: str) -> str:
    """服务器仓库根 = 车道表 config/factory/hosts.json 的 repo（不写死；没登记 → HostsError，失败关闭）"""
    return _HOSTS.server_root(host)

GIT_BIN = "C:/Program Files/Git/usr/bin"
EXTS = (".mp4", ".srt", "_manifest.json")


def _rssh():
    sp = importlib.util.spec_from_file_location("rssh_pp", ROOT / "tools/netfix/rssh.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def remote_list(host: str, rel_dir: str, run_fn=None) -> dict[str, int]:
    cmd = f"cd {remote_root(host)} && find {rel_dir} -maxdepth 1 -type f -printf '%f\\t%s\\n' 2>/dev/null; true"
    r = (run_fn or _rssh().run_retry)(host, cmd, timeout=120, tries=2, text=True)
    out = {}
    for ln in (r.stdout or "").splitlines():
        a = ln.split("\t")
        if len(a) == 2 and a[0].endswith(EXTS):
            out[a[0]] = int(a[1])
    return out


def todo(remote: dict[str, int], local_dir: Path) -> list[str]:
    """本机没有 / 大小不同的；manifest / srt 先、mp4 后（mp4 到了说明这一版齐了）"""
    want = [n for n, s in remote.items() if not ((local_dir / n).is_file() and (local_dir / n).stat().st_size == s)]
    return sorted(want, key=lambda n: (n.endswith(".mp4"), n))


def sftp_get(host: str, pairs: list[tuple[str, Path]], timeout: float = 1800, run=subprocess.run) -> subprocess.CompletedProcess:
    """大文件经 <host>-hk 单独连接（同 rssh.bulk_put，FONG-QUICK），故意不走命令主连接；已登记 config/netfix/ssh_callers.txt（K-OPS-N07）"""
    q = lambda x: '"' + str(x).replace("\\", "/").replace('"', '') + '"'
    lines = [f"get {q(rem)} {q(Path(str(loc) + '.part'))}" for rem, loc in pairs]
    return run([f"{GIT_BIN}/sftp.exe", "-F", "config/netfix/ssh_config", "-S", f"{GIT_BIN}/ssh.exe", "-o", "BatchMode=yes", "-b", "-",
                f"{host}-hk"], input=("\n".join(lines) + "\n").encode("utf-8"), capture_output=True, timeout=timeout, cwd=str(ROOT))


def tick(host: str, run_id: str, run_fn=None, get_fn=None) -> dict:
    rel = f"data/episodes/{run_id}/_partial"
    local = ROOT / rel
    local.mkdir(parents=True, exist_ok=True)
    rem = remote_list(host, rel, run_fn)
    names = todo(rem, local)
    res = {"at": time.strftime("%F %T"), "host": host, "remote": len(rem), "todo": names}
    if not names:
        return res
    t0 = time.time()
    r = (get_fn or sftp_get)(host, [(f"{remote_root(host)}/{rel}/{n}", local / n) for n in names])
    got = []
    for n in names:
        part = local / (n + ".part")
        if part.is_file() and part.stat().st_size == rem[n]:
            os.replace(part, local / n)
            got.append(str((local / n).relative_to(ROOT)).replace("\\", "/"))
    left = [n for n in names if str((local / n).relative_to(ROOT)).replace("\\", "/") not in got]
    if left:   # hk 不通（05:31 实测 banner 超时）→ 退回命令主连接逐个 cat（12.7 MB 约 1 分钟），大小对上才落盘
        for n in left:
            rr = (run_fn or _rssh().run_retry)(host, f"cat {remote_root(host)}/{rel}/{n}", timeout=900, tries=2)
            data = rr.stdout or b""
            if rr.returncode == 0 and len(data) == rem[n]:
                part = local / (n + ".part")
                part.write_bytes(data)
                os.replace(part, local / n)
                got.append(str((local / n).relative_to(ROOT)).replace("\\", "/"))
        res["via_cmd"] = len(left)
    res.update(rc=getattr(r, "returncode", None), got=got, secs=round(time.time() - t0, 1),
               err=(getattr(r, "stderr", b"") or b"")[-200:].decode("utf-8", "replace") if getattr(r, "returncode", 0) else "")
    return res


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="gpu36")
    ap.add_argument("--run", default="series10_v2")
    ap.add_argument("--loop", action="store_true")
    ap.add_argument("--every", type=int, default=300)
    a = ap.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    while True:
        try:
            print(json.dumps(tick(a.host, a.run), ensure_ascii=False), flush=True)
        except Exception as e:  # noqa: BLE001  # arch-ok: 一拍失败只记，下拍再试
            print(json.dumps({"at": time.strftime("%F %T"), "error": repr(e)[:300]}, ensure_ascii=False), flush=True)
        if not a.loop:
            return 0
        time.sleep(a.every)


if __name__ == "__main__":
    raise SystemExit(main())
