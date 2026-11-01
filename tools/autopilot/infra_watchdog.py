"""基础设施看门狗（WORKFLOW 11-01，NIGHT_PLAN W7 a/b；规则 K-OPS-W05 / W06）。

起因（总调度 16:18 实测）：笔记本隧道 18188 卡死、18189 断开，没有自动重连；gpu33 4 小时没出片也没人报警。
ops/autostart/tunnel.sh 的 while 循环只在 ssh 退出时重连——ssh 进程活着但转发卡死（经 194relay 跳板常见）时永远不恢复。

本进程（单实例，30 s 一拍）：
  a) 隧道：每条渲染道探测 http://127.0.0.1:<port>/system_stats；连续 2 次失败 → 杀掉持有该 -L 的 ssh 进程
     （tunnel.sh / tunnel_gpu36.sh 的循环 30 s 内自己重连，不另起一套隧道）；循环本身不在 → 按 laptop_autostart.ps1 的方式重新拉起脚本。
  b) 空转报警（写 data/qa/alerts.jsonl，监控看板 :8810 显示）：
     A-IDLE   渲染道全部空闲 ≥ 20 分钟，而 vidgen 状态里有可派的镜（不是 done / best_effort / blocked / waiting_frame）
     A-NIGHT  night.log ≥ 20 分钟没有新行（并且 night_state.json 也 ≥ 20 分钟没更新 → 级别 crit = 卡住或已退出）
     A-PROD   data/producer/heartbeat.json 过期 ≥ 10 分钟（暂停中不报）
     A-TUNNEL 某条隧道重建后仍不通
     报警按“开 / 关”记一次，不每分钟刷屏。
用法：
  .venv/Scripts/python.exe tools/autopilot/infra_watchdog.py serve      # 常驻（laptop_autostart.ps1 拉起）
  .venv/Scripts/python.exe tools/autopilot/infra_watchdog.py once       # 跑一拍（巡检 / 测试）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VID = ROOT / "data/pipeline/runs/series10_v1/video"
ALERTS = ROOT / "data/qa/alerts.jsonl"
STATE = ROOT / "data/qa/infra_watchdog_state.json"
LOG = ROOT / "ops/logs/infra_watchdog.log"
PIDF = ROOT / "ops/logs/infra_watchdog.pid"
BASH = r"C:\Program Files\Git\bin\bash.exe"
# 端口 → (所属隧道脚本, ssh 主机)；与 ops/autostart/tunnel.sh、tunnel_gpu36.sh、laptop_autostart.ps1 的检测列表一致
TUNNELS = {18188: ("tunnel.sh", "gpu33"), 18189: ("tunnel.sh", "gpu33"), 18191: ("tunnel.sh", "gpu33"),
           18288: ("tunnel_gpu36.sh", "gpu36"), 18289: ("tunnel_gpu36.sh", "gpu36"), 18290: ("tunnel_gpu36.sh", "gpu36")}
TICK_S, FAILS_TO_KILL = 30, 2          # 30 s 一拍、连续 2 次（约 60 s）判卡死；加循环 30 s 重连 → 约 90 s 恢复（W7 要求 ≤ 2 分钟）
IDLE_MIN, NIGHT_MIN, PROD_MIN = 10, 20, 10      # 空转线：总调度 16:55 改 10 分钟
ACTIVE = {"done", "best_effort", "blocked", "waiting_frame"}


def log(*a):
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(time.strftime("%F %T ") + " ".join(str(x) for x in a) + "\n")


def jl(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def js(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def probe(port: int, path: str = "/system_stats", timeout: float = 12) -> dict | None:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:  # noqa: BLE001
        return None


def queue_len(port: int) -> int | None:
    d = probe(port, "/queue")
    return None if d is None else len(d.get("queue_running") or []) + len(d.get("queue_pending") or [])


# ---------------------------------------------------------------- 进程（Windows：PowerShell CIM；测试可替换）
def _ps(cmd: str) -> str:
    r = subprocess.run(["powershell.exe", "-NoProfile", "-Command", cmd], capture_output=True, text=True, timeout=60)
    return r.stdout


def ssh_pids_for(port: int) -> list[int]:
    out = _ps("Get-CimInstance Win32_Process -Filter \"Name='ssh.exe'\" | Where-Object { $_.CommandLine -match "
              f"'-L {port}:' -and $_.CommandLine -match ' -N ' }} | ForEach-Object {{ $_.ProcessId }}")
    return [int(x) for x in out.split() if x.strip().isdigit()]


def loop_running(script: str) -> bool:
    out = _ps("Get-CimInstance Win32_Process -Filter \"Name='bash.exe'\" | Where-Object { $_.CommandLine -match "
              f"'{script}' }} | Measure-Object | ForEach-Object {{ $_.Count }}")
    return out.strip() not in ("", "0")


def kill(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=30)


def start_loop(script: str) -> None:
    subprocess.Popen([BASH, f"{ROOT.as_posix()}/ops/autostart/{script}"], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


RELAY = ("sz194.instameta.org", 19422)


def relay_down(st: dict) -> bool:
    """跳板本身 TCP 不通时不杀隧道（16:58 实测：跳板整体不可达，杀 / 重连只会加重跳板负担）；记 A-RELAY 报警。每拍最多测一次"""
    if st.get("_relay_t") == st.get("_tick"):
        return st.get("_relay_down", False)
    import socket
    try:
        socket.create_connection(RELAY, timeout=8).close()
        down = False
    except OSError:
        down = True
    st["_relay_t"], st["_relay_down"] = st.get("_tick"), down
    alert(st, "A-RELAY", down, "crit", f"跳板 {RELAY[0]}:{RELAY[1]} TCP 不通：笔记本到 gpu33 / gpu36 全断（生产应在服务器常驻跑，K-OPS-W07）")
    return down


# ---------------------------------------------------------------- 报警
def alert(st: dict, aid: str, active: bool, level: str = "warn", msg: str = "", **kw) -> None:
    """开 / 关各记一行（data/qa/alerts.jsonl）；st["open"] 记当前开着的报警"""
    opened = st.setdefault("open", {})
    if active and aid not in opened:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "id": aid, "state": "open", "level": level,
               "msg": msg, "by": "infra_watchdog", **kw}
        opened[aid] = rec
        _append(rec)
        log("ALERT", aid, level, msg)
    elif active:
        opened[aid].update(msg=msg, level=level, last=time.time())
    elif not active and aid in opened:
        rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "id": aid, "state": "closed",
               "msg": "已恢复", "by": "infra_watchdog", "opened": opened[aid]["ts"]}
        del opened[aid]
        _append(rec)
        log("CLEAR", aid)


def _append(rec: dict) -> None:
    ALERTS.parent.mkdir(parents=True, exist_ok=True)
    with open(ALERTS, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def dispatchable_shots() -> list[str]:
    out = []
    for h in ("gpu33", "gpu36"):
        d = jl(VID / f"state_{h}.json", {}) or {}
        for sid, r in (d.get("shots") or {}).items():
            if r.get("status") not in ACTIVE:
                out.append(sid)
    return out


# ---------------------------------------------------------------- 一拍
def tick(st: dict, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    st["_tick"] = now
    fails = st.setdefault("fails", {})
    down, busy, reachable = [], False, 0
    from concurrent.futures import ThreadPoolExecutor   # 并行探测：卡死的道每条要等满超时，串行会拖慢判定（注入测试 138 s → 并行）
    with ThreadPoolExecutor(len(TUNNELS)) as ex:
        res = dict(zip(TUNNELS, ex.map(lambda p: (probe(p, timeout=6) is not None) and (queue_len(p) or 0), TUNNELS)))
    for port, (script, _host) in TUNNELS.items():
        ok = res[port] is not False
        k = str(port)
        if ok:
            fails[k] = 0
            reachable += 1
            busy |= bool(res[port])
            continue
        fails[k] = fails.get(k, 0) + 1
        down.append(port)
        # 连续 2 次 → 重建；之后每 4 拍（约 2 分钟）再重建一次——11-01 16:45 实测：重连的 ssh 卡在连接阶段
        # （tunnel*.sh 没有 ConnectTimeout，经 194relay 跳板时一直挂着、端口不监听），只杀一次救不回来
        if fails[k] >= FAILS_TO_KILL and (fails[k] - FAILS_TO_KILL) % 4 == 0 and not relay_down(st):
            pids = ssh_pids_for(port)
            for pid in pids:
                kill(pid)
            if not pids and not loop_running(script):
                start_loop(script)
                log("TUNNEL", port, "循环不在 → 拉起", script)
            else:
                log("TUNNEL", port, "探测连续失败 → 杀 ssh", pids, "（", script, "循环 30 s 内重连）")
            st.setdefault("rebuilds", []).append({"t": now, "port": port, "killed": pids})
            st["rebuilds"] = st["rebuilds"][-50:]
        if fails[k] >= FAILS_TO_KILL + 3:          # 重建后 3 拍仍不通
            alert(st, f"A-TUNNEL-{port}", True, "crit", f"隧道 {port} 重建后仍不通（{fails[k]} 拍）")
    for port in TUNNELS:
        if fails.get(str(port), 0) == 0:
            alert(st, f"A-TUNNEL-{port}", False)
    relay_down(st)                                 # 每拍都测一次跳板（A-RELAY 开 / 关）
    # 常驻模式（K-OPS-W07）：笔记本 producer paused_by=SERVER_RESIDENT、night 不在笔记本跑 → 笔记本侧空转 / night / producer
    # 报警不适用（服务器侧由 resident_sync health 报 A-IDLE-<host> 等），这里关掉，免得误报
    resident = (jl(ROOT / "data/producer/control.json", {}) or {}).get("paused_by") == "SERVER_RESIDENT"
    st["resident"] = resident
    if resident:
        for aid in ("A-IDLE", "A-NIGHT", "A-PROD"):
            alert(st, aid, False)
        st.update(at=time.strftime("%Y-%m-%dT%H:%M:%S"), t=now, down=down, busy=busy, dispatchable=None)
        return st
    # 空转：可派的镜 > 0 且所有能连上的道都空
    cand = dispatchable_shots()
    if busy or not cand or reachable == 0:
        st["idle_since"] = None
    else:
        st["idle_since"] = st.get("idle_since") or now
    idle_min = (now - st["idle_since"]) / 60 if st.get("idle_since") else 0
    alert(st, "A-IDLE", idle_min >= IDLE_MIN, "warn",
          f"渲染道全部空闲 {idle_min:.0f} 分钟，vidgen 还有 {len(cand)} 镜可派（例 {cand[:3]}）")
    nl, ns = VID / "night.log", VID / "night_state.json"
    nl_min = (now - nl.stat().st_mtime) / 60 if nl.exists() else 1e9
    ns_min = (now - ns.stat().st_mtime) / 60 if ns.exists() else 1e9
    alert(st, "A-NIGHT", nl_min >= NIGHT_MIN, "crit" if ns_min >= NIGHT_MIN else "warn",
          f"night.log {nl_min:.0f} 分钟没有新行；night_state.json {ns_min:.0f} 分钟前更新"
          + ("（两者都停 = night.py 卡住或已退出）" if ns_min >= NIGHT_MIN else "（循环在跑，只是没有事件）"))
    hb = jl(ROOT / "data/producer/heartbeat.json", {}) or {}
    hb_min = (now - float(hb.get("t") or 0)) / 60
    alert(st, "A-PROD", bool(hb) and not hb.get("paused") and hb_min >= PROD_MIN, "crit",
          f"producer 心跳 {hb_min:.0f} 分钟没更新（pid {hb.get('pid')}）")
    st.update(at=time.strftime("%Y-%m-%dT%H:%M:%S"), t=now, down=down, busy=busy, dispatchable=len(cand))
    return st


def main(argv) -> int:
    cmd = argv[0] if argv else "once"
    st = jl(STATE, {}) or {}
    if cmd == "once":
        st = tick(st)
        js(STATE, st)
        print(json.dumps({k: st.get(k) for k in ("at", "down", "busy", "dispatchable", "fails")}, ensure_ascii=False))
        print("open alerts:", list((st.get("open") or {})))
        return 0
    if cmd == "serve":
        old = (PIDF.read_text().strip() if PIDF.exists() else "")
        if old.isdigit() and str(os.getpid()) != old and _alive(int(old)):
            print("already running", old)
            return 0
        PIDF.write_text(str(os.getpid()))
        log("start pid", os.getpid())
        while True:
            try:
                st = tick(st)
                js(STATE, st)
            except Exception as e:  # noqa: BLE001
                log("tick error", repr(e)[:300])
            time.sleep(TICK_S)
    print(__doc__)
    return 2


def _alive(pid: int) -> bool:
    out = _ps(f"Get-Process -Id {pid} -ErrorAction SilentlyContinue | ForEach-Object {{ $_.ProcessName }}")
    return "python" in out.lower()


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
