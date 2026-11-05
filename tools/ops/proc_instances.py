"""笔记本常驻进程的“逻辑实例”清单（AUDIT-RULES 11-05；规则 K-OPS-I08）。

起因：11-05 有人看到 tools/autopilot/resident_sync.py loop 与 tools/monitor/server.py 各有“两份”在跑——一份 .venv\\Scripts\\python.exe、
一份 Python312\\python.exe。查实（PID 19180→25584、48428→20812，父子、创建时间差 1 s）：Windows 上 .venv 的 python.exe 是转发器
（venv launcher），它再起一个基础解释器子进程、自己只等着——父子两个 pid = 一份服务，不是重复（ops/restart_api.ps1:313、
K-OPS-F30 证据里已记过一次）。按进程名 / 解释器路径数“份数”会误判，杀掉其中一个 = 杀掉唯一的那份。

用法：
  python tools/ops/proc_instances.py                      # 列出 resident_sync / monitor / sentinel / api 的逻辑实例
  python tools/ops/proc_instances.py --match "resident_sync\\.py.*loop" --json
纯函数 logical_instances(table, pattern) 给测试和别的脚本用；table = [{pid, ppid, exe, cmd, born}]。
只读：不杀任何进程（K-OPS-F30：停进程一律走 ops/restart_*.ps1）。
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MATCHES = {
    "resident_sync": r"tools[\\/]autopilot[\\/]resident_sync\.py.*\bloop\b",
    "monitor8810": r"tools[\\/]monitor[\\/]server\.py",
    "sentinel": r"tools[\\/]sentinel[\\/]sentinel\.py.*serve",
    # api_watchdog.py（包一层，命令行里也带 uvicorn ns_api.app）不算：:8800 = 看门狗 → 转发器 → uvicorn 转发器 → uvicorn，一条链一份服务
    "api8800": r"^(?!.*api_watchdog\.py).*-m uvicorn ns_api\.app",
}


def _args_of(cmd: str) -> str:
    """命令行去掉第一个 token（解释器路径，可能带引号）后的部分 → 转发器父子的这一段完全相同"""
    s = cmd.strip()
    if s.startswith('"'):
        end = s.find('"', 1)
        rest = s[end + 1:] if end > 0 else ""
    else:
        parts = s.split(None, 1)
        rest = parts[1] if len(parts) > 1 else ""
    return " ".join(rest.split())


def is_launcher_child(child: dict, parent: dict) -> bool:
    """child 是 parent（.venv 转发器）起的基础解释器：ppid 对、参数串相同、父 exe 在 .venv 下、子 exe 不在"""
    if int(child.get("ppid") or 0) != int(parent.get("pid") or 0):
        return False
    pexe, cexe = str(parent.get("exe") or "").lower(), str(child.get("exe") or "").lower()
    if ".venv" not in pexe or ".venv" in cexe:
        return False
    return _args_of(str(parent.get("cmd") or "")) == _args_of(str(child.get("cmd") or "")) != ""


def logical_instances(table: list[dict], pattern: str) -> list[dict]:
    """命令行匹配 pattern 的进程 → 逻辑实例列表（转发器父子合并成一条：pid=父、worker_pid=子）"""
    rx = re.compile(pattern)
    hit = [p for p in table if rx.search(str(p.get("cmd") or ""))]
    by_pid = {int(p["pid"]): p for p in hit}
    absorbed: set[int] = set()
    out = []
    for p in hit:
        kids = [c for c in hit if is_launcher_child(c, p)]
        for c in kids:
            absorbed.add(int(c["pid"]))
        out.append({"pid": int(p["pid"]), "exe": p.get("exe"), "cmd": p.get("cmd"), "born": p.get("born"),
                    "worker_pid": int(kids[0]["pid"]) if kids else None, "launcher_pair": bool(kids)})
    out = [x for x in out if x["pid"] not in absorbed and x["pid"] in by_pid]
    return sorted(out, key=lambda x: x["pid"])


def process_table() -> list[dict]:
    """[{pid, ppid, exe, cmd, born}]；Windows 走 CIM（strict=False：别人的命令行可带控制字符），Linux 走 ps"""
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,ExecutablePath,CommandLine,"
              "@{n='Born';e={if($_.CreationDate){$_.CreationDate.ToString('s')}else{''}}} | ConvertTo-Json -Compress")
        r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        d = json.loads(r.stdout.decode("utf-8", "replace") or "[]", strict=False)
        d = [d] if isinstance(d, dict) else d or []
        return [{"pid": int(x.get("ProcessId") or 0), "ppid": int(x.get("ParentProcessId") or 0),
                 "exe": x.get("ExecutablePath") or "", "cmd": x.get("CommandLine") or "", "born": x.get("Born") or ""} for x in d]
    r = subprocess.run(["ps", "-eo", "pid=,ppid=,lstart=,args="], capture_output=True, text=True, timeout=60)
    out = []
    for ln in r.stdout.splitlines():
        parts = ln.split(None, 7)
        if len(parts) < 8:
            continue
        out.append({"pid": int(parts[0]), "ppid": int(parts[1]), "exe": parts[7].split()[0] if parts[7] else "",
                    "cmd": parts[7], "born": " ".join(parts[2:7])})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--match", help="命令行正则；不给 = 常驻四件")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    table = process_table()
    pats = {"custom": a.match} if a.match else DEFAULT_MATCHES
    rep = {k: logical_instances(table, v) for k, v in pats.items()}
    if a.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
        return 0
    for k, rows in rep.items():
        print(f"{k}: {len(rows)} 份" + ("" if len(rows) <= 1 else "  ← 真重复，走 ops/restart_*.ps1 收敛"))
        for x in rows:
            pair = f"（转发器 {x['pid']} → 工作子进程 {x['worker_pid']}，算一份）" if x["launcher_pair"] else ""
            print(f"  pid {x['pid']} {x['born'] or ''} {pair}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
