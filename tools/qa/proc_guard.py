"""测试进程守卫（W22 P0，总调度 11-03 15:5x）：测试进程里不许杀“不是本测试创建的”进程。

事故：autoflow_resident pid 25996 在 15:30:15 第 178 拍后无声消失（taskkill /F 级），时间正好是 sv-20261103-02 真 cut 的 pytest
阶段；快照的 data/ 硬链接到真实数据，嫌疑是某条测试从 pid / 锁 / 心跳文件读到了生产进程的 pid 并 taskkill /T /F。

install() 之后，本进程里：
  - os.kill(pid, sig)（sig≠0）、subprocess 起的 taskkill /PID n、powershell Stop-Process -Id n、kill n
    指向的 pid 必须是“本测试的”：本进程 Popen 出来的子进程、它们的子孙、命令行里带 pytest 临时目录（pytest-of- / .pytest_sandbox）
    的进程、或本进程自己；否则抛 RuntimeError 并记账（VIOLATIONS），吞掉异常也会在会话结束报出。
  - 按映像名 / 进程名批量杀（taskkill 的映像名参数、Stop-Process 的名字参数、pkill、kill-all 类命令）一律拦。
本模块只拦截、只读进程表，自己绝不杀任何进程（K-OPS-F30）。
  - 目标 pid 已不存在 = 放行（杀不到任何东西）。
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import traceback

VIOLATIONS: list[dict] = []
_BORN: dict[int, int] = {}          # pid → 创建时间（Windows ticks；Linux 不填）
OWN: set[int] = set()
MARKERS = ("pytest-of-", ".pytest_sandbox", "pytest_sandbox")
_STATE = {"orig": None, "test": None}
_LOCK = threading.Lock()


def _current_test() -> str:
    return _STATE["test"] or os.environ.get("PYTEST_CURRENT_TEST", "?").split(" ")[0]


def _proc_table() -> dict[int, tuple[int, str]] | None:
    """{pid: (ppid, 命令行)}；取不到 = None"""
    orig = _STATE["orig"]
    run = orig["run"] if orig else subprocess.run
    if os.name == "nt":
        ps = ("Get-CimInstance Win32_Process | Select-Object ProcessId,ParentProcessId,CommandLine,"
              "@{n='Born';e={$_.CreationDate.ToUniversalTime().Ticks}} | ConvertTo-Json -Compress")
        try:
            r = run(["powershell.exe", "-NoProfile", "-Command", ps], capture_output=True, timeout=60,
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            # strict=False：别人的进程命令行里带控制字符时整表解析失败 → “认不出”→ 把测试自己起的进程树也拦下（AUDIT-RULES 11-05，
            # test_run_watched_kills_stalled_tree 第二层根因；与 system_version._ident_table 同口径）
            d = json.loads(r.stdout.decode("utf-8", "replace") or "[]", strict=False)
        except (OSError, subprocess.TimeoutExpired, ValueError):  # arch-ok: 进程表取不到 = 按“认不出”处理（拦）
            return None
        d = [d] if isinstance(d, dict) else d or []
        _BORN.clear()
        _BORN.update({int(x.get("ProcessId") or 0): int(x.get("Born") or 0) for x in d})
        return {int(x.get("ProcessId") or 0): (int(x.get("ParentProcessId") or 0), str(x.get("CommandLine") or "")) for x in d}
    out = {}
    for p in os.listdir("/proc"):
        if not p.isdigit():
            continue
        try:
            with open(f"/proc/{p}/stat") as f:
                ppid = int(f.read().rsplit(")", 1)[1].split()[1])
            with open(f"/proc/{p}/cmdline", "rb") as f:
                cl = f.read().replace(b"\0", b" ").decode("utf-8", "replace")
            out[int(p)] = (ppid, cl)
        except (OSError, IndexError, ValueError):  # arch-ok: 进程已退出
            continue
    return out


def pid_is_ours(pid: int, table: dict | None = None) -> tuple[bool, str]:
    pid = int(pid)
    if pid == os.getpid() or pid in OWN:
        return True, "本进程 / 本进程起的子进程"
    t = table if table is not None else _proc_table()
    if t is None:
        return False, "进程表取不到，认不出"
    if pid not in t:
        return True, "进程已不存在"
    seen, cur = set(), pid
    while cur and cur not in seen:
        seen.add(cur)
        if cur == os.getpid() or cur in OWN:
            return True, "本测试进程的子孙"
        cl = t.get(cur, (0, ""))[1]
        if any(m in cl for m in MARKERS):
            return True, "命令行带 pytest 临时目录"
        cur = t.get(cur, (0, ""))[0]
    return False, f"不是本测试创建的进程：{t[pid][1][:160]}"


def _violate(what: str, why: str):
    rec = {"what": what, "why": why, "test": _current_test(), "stack": "".join(traceback.format_stack(limit=12)[:-2])}
    with _LOCK:
        VIOLATIONS.append(rec)
    raise RuntimeError(f"测试里不许杀别人的进程：{what}（{why}；tools/qa/proc_guard.py）")


def _argv(args) -> list[str]:
    if isinstance(args, (str, bytes)):
        s = args.decode() if isinstance(args, bytes) else args
        return [x.strip('"\'') for x in re.findall(r'"[^"]*"|\'[^\']*\'|\S+', s)]
    try:
        return [os.fspath(a) if not isinstance(a, bytes) else a.decode() for a in args]
    except TypeError:
        return [str(args)]


def kill_targets(args) -> tuple[list[int], str | None]:
    """命令里要杀的 pid 列表；按名字批量杀 → (.., 原因)；不是杀进程的命令 → ([], None)"""
    av = _argv(args)
    if not av:
        return [], None
    exe = os.path.basename(av[0]).lower()
    if exe.endswith(".exe"):
        exe = exe[:-4]
    low = [a.lower() for a in av]
    if exe == "taskkill":
        if "/im" in low:
            return [], "taskkill 按映像名杀"
        return [int(av[i + 1]) for i, a in enumerate(low[:-1]) if a == "/pid" and av[i + 1].isdigit()], None
    if exe in ("pkill", "kill" + "all"):
        return [], f"{exe} 按名字杀"
    if exe == "kill":
        return [int(a) for a in av[1:] if a.isdigit()], None
    if exe in ("powershell", "pwsh"):
        text = " ".join(av[1:])
        if not re.search(r"stop-process", text, re.I):
            return [], None
        if re.search(r"stop-process[^;|]*-name\b", text, re.I):
            return [], "Stop-Process 按进程名杀"
        return [int(x) for x in re.findall(r"stop-process[^;|]*?-id\s+(\d+)", text, re.I)], None
    return [], None


def adopted_by_reuse(root: int, table: dict, born: dict) -> list[int]:
    """taskkill /T 会按 ParentProcessId 连带停子孙；Windows 的 pid 会复用——比“父进程”更早出生的“子进程”其实是别人的孤儿
    （父 pid 被复用到了本测试的进程上），/T 会把它一起杀掉。返回这些进程"""
    kids: dict[int, list[int]] = {}
    for pid, (pp, _cl) in table.items():
        kids.setdefault(pp, []).append(pid)
    bad, stack, seen = [], [root], {root}
    while stack:
        par = stack.pop()
        for k in kids.get(par, []):
            if k in seen:
                continue
            seen.add(k)
            if born.get(k) and born.get(par) and born[k] < born[par]:
                bad.append(k)
                continue
            stack.append(k)
    return bad


def check_cmd(args) -> None:
    pids, bad = kill_targets(args)
    what = " ".join(_argv(args))[:200]
    if bad:
        _violate(what, bad)
    if pids:
        t = _proc_table()
        tree = "/t" in [a.lower() for a in _argv(args)]
        for p in pids:
            ok, why = pid_is_ours(p, t)
            if not ok:
                _violate(what, why)
            if tree and t:
                adopted = adopted_by_reuse(int(p), t, dict(_BORN))
                if adopted:
                    _violate(what, f"/T 会连带杀掉 pid 复用领养的别人进程 {adopted}：{t[adopted[0]][1][:120]}")


def install() -> None:
    if _STATE["orig"] is not None:
        return
    P = subprocess.Popen
    orig = {"init": P.__init__, "kill": os.kill, "run": subprocess.run}
    _STATE["orig"] = orig

    def init(self, args, *a, **k):
        check_cmd(args)
        orig["init"](self, args, *a, **k)
        if getattr(self, "pid", None):
            OWN.add(int(self.pid))

    def kill(pid, sig):
        if sig != 0 and int(pid) > 0:
            ok, why = pid_is_ours(pid)
            if not ok:
                _violate(f"os.kill({pid}, {sig})", why)
        elif sig != 0 and int(pid) <= 0:
            _violate(f"os.kill({pid}, {sig})", "进程组 / 全体广播")
        return orig["kill"](pid, sig)
    P.__init__ = init
    os.kill = kill


def uninstall() -> None:
    orig = _STATE["orig"]
    if orig is None:
        return
    subprocess.Popen.__init__ = orig["init"]
    os.kill = orig["kill"]
    _STATE["orig"] = None
