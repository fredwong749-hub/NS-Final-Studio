"""笔记本端口转发监管进程（NETFIX 11-01，总调度 fredw-2b 派；规则 K-OPS-N01 / N02）。

起因：项目方 22:1x 原话“gpu连接是大问题,现在全部修复连接问题”。原来是 tunnel.sh / tunnel_gpu36.sh 两个 bash 循环加看门狗杀 ssh，
22:08 gpu36 三条全断、跳板却是通的：循环不在，看门狗只会杀 ssh，于是永远修不好；手动起的孤儿 ssh 没人管。

本进程（单实例，文件锁 data/netfix/supervisor.lock）一个人负责全部转发，类似 autossh：
  · 每台服务器一条 ssh，挂 config/netfix/tunnels.json 里该机的全部 -L；ProxyCommand 自带 ConnectTimeout / ServerAlive（跳那一跳也保活）；
    ssh 带 -o Tag=nsnetfix-<host>，监管进程重启后按 Tag 认领自己的 ssh，不打断。
  · 跳板 TCP 不通：不起 ssh（白白握手只会加重跳板负担），每拍（5 s）测一次；跳板一恢复，退避清零、立刻重连。
  · ssh 退出：按 backoff_s 指数退避重连（3/6/12/24/30 s）。
  · ssh 活着但卡死：15 s 一轮 HTTP 探测；该机全部探测口都“超时 / 本地不监听”连续 hang_rounds 轮 → 杀掉重起。
    只是个别口回“对端拒绝”（ssh 通、服务器那头 ComfyUI 没起）→ 记 remote_down，不杀隧道。
    起了 listen_grace_s 秒还没监听（卡在握手）→ 杀掉重起。
  · 接管：起 ssh 前，占着本机这些端口、但不带本进程 Tag 的 ssh（孤儿、旧 tunnel*.sh 循环起的）一律杀掉；旧 bash 循环也杀掉。
  · 每拍写 data/netfix/net_status.json（字段见 STATUS_DOC；UIRSI r38 / 看门狗 / 看板读它）。
看门狗（tools/autopilot/infra_watchdog.py）在本进程心跳新鲜时只探测、只报警，不再修。
本进程自己的保活：Windows 计划任务 NS-Studio-TunnelSupervisor 每 5 分钟跑一次 `ensure`（不在就拉起），laptop_autostart.ps1 登录时也跑 `ensure`。

用法：
  .venv/Scripts/python.exe tools/netfix/tunnel_supervisor.py serve [--conf X] [--state-dir D]   常驻
  .venv/Scripts/python.exe tools/netfix/tunnel_supervisor.py ensure                             不在就后台拉起（计划任务用）
  .venv/Scripts/python.exe tools/netfix/tunnel_supervisor.py status                             打印状态
  .venv/Scripts/python.exe tools/netfix/tunnel_supervisor.py stop                               停监管进程（ssh 留着，下次认领）
"""
from __future__ import annotations

import argparse
import ctypes
import http.client
import json
import os
import socket
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONF = ROOT / "config/netfix/tunnels.json"
STATE_DIR = ROOT / "data/netfix"
RESIDENT = ROOT / "data/autopilot/resident_sync.json"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
STATUS_DOC = {
    "schema": "netfix.net_status.v1",
    "at / t": "本拍写入时间（ISO / epoch 秒）；t 超过 90 s 没更新 = 监管进程不在（一拍探测最长约 25 s）",
    "supervisor": "{pid, started_t, conf}",
    "relay": "{up, checked_t, last_ok_t, down_since_t（不通时）, last_change_t}",
    "hosts.<连接名>": "每条 ssh 一项（00:0x 起按道分连接：gpu33-l0 / gpu33-l1 / gpu33-l3 / gpu36-l0 / gpu36-l1 / gpu36-l2；server 字段 = 所属服务器）{state: up|connecting|backoff|relay_down|stopped, pid, since_t（本条 ssh 起的时间）, up_since_t（端口全部通的时间）, "
                 "restarts, last_restart: {t, reason}, next_try_t, ports: {<本机口>: {remote, ok, why: ok|timeout|refused|remote_down, checked_t}}}",
    "dispatch_mode": "派单模式（K-OPS-N06）：{override_active: 临时覆盖是否生效, phases: {gpu33|gpu36: laptop=该台分区由笔记本经隧道代派 | draining=正在交还 | server=服务器自己派}, checked_t}",
    "transfer": "传图队列（K-OPS-N09，puller 写）：{hosts: {gpu33|gpu36: {reachable, backlog_items 积压条数, backlog_bytes, throughput_kBps, latency_p50_s / p90_s 产出→落地, acked_total}}}；界面例：“传图队列：积压 12 张，约 3 分钟”",
    "rssh": "命令通道成功率（总调度 14:2x，目标 > 99%）：{1h|10m: {gpu33|gpu36: {n, ok, rate, p50_s}}, target}；数据 = rssh.run 每次调用 + 每分钟合成探测（data/netfix/rssh_calls.jsonl）",
    "tunnels_up / tunnels_total": "出图 / 视频道（probe_http）通的条数 / 总数",
    "servers.<h>": "服务器自主生产：{last_health_t, last_pull_t, last_push_t, sync_age_min（最后一次并回距今分钟，界面“最后一次同步 xx 分钟前”用它）, producer_hb_age_min, producer_paused, night_state_age_min, dispatchable, autonomous: 跳板断时 true}（取自 resident_sync.json，跳板断时停在最后一次）",
}


def now() -> float:
    return time.time()


def iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t if t is not None else now()))


def jl(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def js(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    for _ in range(5):
        try:
            os.replace(tmp, p)
            return
        except PermissionError:      # Windows：读的人正开着文件
            time.sleep(0.2)
    tmp.unlink(missing_ok=True)


# ---------------------------------------------------------------- Windows 进程（不依赖 psutil）
PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259


def pid_alive(pid: int | None) -> bool:
    if not pid:
        return False
    if os.name != "nt":
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False
    k = ctypes.windll.kernel32
    h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return False
    try:
        code = ctypes.c_ulong()
        return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == STILL_ACTIVE
    finally:
        k.CloseHandle(h)


class _IO(ctypes.Structure):
    _fields_ = [(n, ctypes.c_ulonglong) for n in ("ReadOps", "WriteOps", "OtherOps", "ReadBytes", "WriteBytes", "OtherBytes")]


def io_bytes(pid: int | None) -> int | None:
    """进程累计读写字节（Windows GetProcessIoCounters）。ssh 在搬数据 = 没卡死，只是跳板慢（23:44 实测：笔记本经隧道派图时
    探测 20 s 超时，按“卡死”杀掉会打断正在传的参考图 / 结果图）"""
    if not pid or os.name != "nt":
        return None
    k = ctypes.windll.kernel32
    h = k.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, int(pid))
    if not h:
        return None
    try:
        c = _IO()
        return (c.ReadBytes + c.WriteBytes + c.OtherBytes) if k.GetProcessIoCounters(h, ctypes.byref(c)) else None
    finally:
        k.CloseHandle(h)


def kill(pid: int) -> None:
    subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True, timeout=30, creationflags=NOWIN)


WSL = ["C:/Windows/System32/wsl.exe", "-d", "Ubuntu-24.04", "--exec"]


def mux_check(sock: str, host: str, timeout: float = 20) -> bool:
    """WSL 命令主连接活着（ssh -O check，只问本机 master，不走网络）"""
    try:
        r = subprocess.run(WSL + ["ssh", "-S", sock, "-O", "check", host], capture_output=True, timeout=timeout, creationflags=NOWIN)
        return r.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _route_of(cmd: str) -> str:
    c = cmd.rstrip().strip('"')
    return "t" if (c.endswith("-t") or c.endswith("-tb") or c.endswith("-tc")) else "hk" if c.endswith("-hk") else "direct"


def _base_of(cmd: str) -> str | None:
    c = cmd.rstrip().strip('"')
    return "base-b" if c.endswith("-tb") else "base-c" if c.endswith("-tc") else "base-a" if c.endswith("-t") else None


def ssh_banner(port: int, timeout: float = 10) -> bool:
    """底座隧道端口能读到服务器 sshd 的 banner（SSH-2.0…）= 隧道通到服务器"""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=timeout) as sk:
            sk.settimeout(timeout)
            return sk.recv(64).startswith(b"SSH-")
    except OSError:
        return False


def _alert(aid: str, msg: str) -> None:
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": time.time(), "id": aid, "state": "open", "level": "crit", "msg": msg,
           "by": "tunnel_supervisor"}
    try:
        with open(ROOT / "data/qa/alerts.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError:
        pass


def list_procs(names=("ssh.exe", "bash.exe", "wsl.exe")) -> list[tuple[int, str, str]]:
    """[(pid, name, cmdline)]；PowerShell CIM（约 1–2 s，只在接管时用）"""
    flt = " or ".join(f"Name='{n}'" for n in names)
    cmd = (f"Get-CimInstance Win32_Process -Filter \"{flt}\" | ForEach-Object {{ \"$($_.ProcessId)`t$($_.Name)`t$($_.CommandLine)\" }}")
    try:
        raw = subprocess.run(["powershell.exe", "-NoProfile", "-Command",
                              "[Console]::OutputEncoding=[Text.Encoding]::UTF8; " + cmd], capture_output=True,
                             timeout=60, creationflags=NOWIN).stdout or b""
        out = raw.decode("utf-8", "replace")   # 22:21 实测：命令行里有非 UTF-8 字节时 text=True 的读线程崩、stdout=None
    except (OSError, subprocess.TimeoutExpired):
        return []
    res = []
    for ln in out.splitlines():
        p = ln.split("\t", 2)
        if len(p) == 3 and p[0].strip().isdigit():
            res.append((int(p[0]), p[1], p[2]))
    return res


# ---------------------------------------------------------------- 探测
def tcp_ok(host: str, port: int, timeout: float = 5) -> bool:
    try:
        socket.create_connection((host, int(port)), timeout=timeout).close()
        return True
    except OSError:
        return False


def probe_http(port: int, timeout: float) -> str:
    """ok | timeout | refused（本机没监听）| remote_down（ssh 接了但对端服务不在：通道打开失败，连接被立刻关掉）"""
    c = http.client.HTTPConnection("127.0.0.1", port, timeout=timeout)
    try:
        c.request("GET", "/system_stats")
        r = c.getresponse()
        r.read()
        return "ok" if r.status < 500 else "remote_down"
    except ConnectionRefusedError:
        return "refused"
    except (socket.timeout, TimeoutError):
        return "timeout"
    except (http.client.RemoteDisconnected, ConnectionResetError, ConnectionAbortedError, http.client.BadStatusLine):
        return "remote_down"
    except OSError as e:
        return "refused" if getattr(e, "winerror", None) == 10061 else "timeout"
    finally:
        c.close()


# ---------------------------------------------------------------- 监管
class Supervisor:
    def __init__(self, conf_path: Path = CONF, state_dir: Path = STATE_DIR):
        self.conf_path = Path(conf_path)
        self.c = jl(self.conf_path, {})
        self.dir = Path(state_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.status_p = self.dir / "net_status.json"
        self.log_p = self.dir / "supervisor.log"
        self.tag = self.c.get("tag_prefix", "nsnetfix")
        self.started = now()
        old = jl(self.status_p, {}) or {}
        self.hosts = {}
        for h in self.c["hosts"]:
            o = (old.get("hosts") or {}).get(h) or {}
            self.hosts[h] = {"state": "stopped", "pid": None, "since_t": None, "up_since_t": None, "restarts": o.get("restarts", 0),
                             "last_restart": o.get("last_restart"), "next_try_t": 0.0, "fails": 0, "hang": 0, "probe_t": 0.0,
                             "ports": {}}
        self.relay = {"up": None, "checked_t": None, "last_ok_t": (old.get("relay") or {}).get("last_ok_t"),
                      "down_since_t": None, "last_change_t": None}
        self.legacy_done = False
        self.route_bad_until: dict[str, float] = {}
        self.route_fails: dict[str, int] = {}

    # ---- 日志
    def log(self, *a) -> None:
        with open(self.log_p, "a", encoding="utf-8") as f:
            f.write(iso() + " " + " ".join(str(x) for x in a) + "\n")

    # ---- ssh 命令行
    def host_tag(self, h: str) -> str:
        return f"{self.tag}-{h}"

    def ssh_cmd(self, h: str) -> list[str]:
        hc = self.c["hosts"][h]
        route = self.lane_route(h)                  # r5：道配了 route（hk）就固定走它（独立连接，不挂底座）；该路被判坏时临时走 pick_route
        target = hc.get("ssh_host", h) + (self.c.get("routes") or {}).get(route, {}).get("suffix", "")
        if hc.get("kind") == "base":                # r2/r3：底座隧道连跳板本身；base-a 固定香港、base-b 固定直连（互为备份，不再一条单点）
            target = (self.c.get("routes") or {}).get(hc.get("route") or route, {}).get("relay", "194relay")
        elif hc.get("via") == "t":                  # 在底座隧道里直连服务器 sshd，不在跳板上握手；挂哪条底座见 pick_base
            b = self.pick_base(h) or hc.get("base", "base-a")
            target = hc.get("ssh_host", h) + self.c["hosts"][b].get("alias_suffix", "-t")
        cfg = self.c.get("ssh_config")
        if hc.get("kind") == "wsl_mux":            # P0 11-02：WSL OpenSSH 命令主连接（ControlMaster），远程命令 / 文件都复用它
            # 14:2x：命令主连接也要放宽保活（15 s × 6 = 90 s；-o 放在 -F 读到的配置之前生效），底座卡顿 ~60 s 时不再整批掉线（14:23 一次掉 6 条）
            return WSL + ["ssh", "-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=6",
                          *(["-F", self.c["ssh_config_wsl"]] if cfg else []), "-o", "BatchMode=yes", "-M", "-S", hc["sock"],
                          "-o", "ControlPersist=no", "-N", "-o", f"Tag={self.host_tag(h)}", target]
        extra = ["-o", "LogLevel=VERBOSE"] if hc.get("kind") == "base" else []   # r3：底座记通道开关明细，查 no_banner 根因
        if hc.get("via") == "t":                    # 内层经底座：保活放宽到 15 s × 6 = 90 s，底座短暂卡顿不连带把道杀掉（13:2x 抖动事故）
            extra += ["-o", "ServerAliveInterval=15", "-o", "ServerAliveCountMax=6"]
        elif self.is_lane(h):                       # r5 运维 FONG-QUICK：独立跳板连接保活 15 s × 3（extra 在 ssh_opts 前，先出现的生效）
            ka, kn = self.c.get("lane_keepalive") or [15, 3]
            extra += ["-o", f"ServerAliveInterval={ka}", "-o", f"ServerAliveCountMax={kn}"]
        if cfg:                                     # K-OPS-N08：项目 ssh 配置（香港中转主路 / 直连备用），相对路径 + cwd=ROOT（路径有空格）
            cmd = [self.c["ssh_exe"], "-F", cfg, *extra, *self.c["ssh_opts"], "-o", f"Tag={self.host_tag(h)}"]   # extra 在前：ssh 同名选项先出现的生效
        else:
            cmd = [self.c["ssh_exe"], *self.c["ssh_opts"], "-o", f"Tag={self.host_tag(h)}",
                   "-o", "ProxyCommand=" + self.c["relay"]["proxy_cmd"].replace("Tag=nsnetfix-proxy", f"Tag={self.tag}-proxy-{h}")]
        for lp, rp in hc["forwards"]:
            cmd += ["-L", f"127.0.0.1:{lp}:{rp}" if isinstance(rp, str) else f"127.0.0.1:{lp}:127.0.0.1:{rp}"]
        return cmd + [target]

    def is_lane(self, h: str) -> bool:
        """r5：自己在跳板上握手的道连接（不是底座、不挂底座、不是 WSL 主连接）"""
        hc = self.c["hosts"][h]
        return hc.get("kind") not in ("base", "wsl_mux") and hc.get("via") != "t"

    def lane_route(self, h: str) -> str:
        r = self.c["hosts"][h].get("route")
        if r and r in (self.c.get("routes") or {}) and now() >= self.route_bad_until.get(r, 0):
            return r
        return self.pick_route()

    def bases(self) -> list[str]:
        return [k for k, v in self.c["hosts"].items() if v.get("kind") == "base"]

    def pick_base(self, h: str) -> str | None:
        """内层连接挂哪条底座：优先自己配置的那条（按道分摊），它不通就挂另一条通的；都不通 → None"""
        pref = self.c["hosts"][h].get("base") or (self.bases() or [None])[0]
        order = [pref] + [b for b in self.bases() if b != pref]
        ups = [b for b in order if b and (self.hosts.get(b) or {}).get("state") == "up"]
        good = [b for b in ups if not self.degraded(b)]    # 11:5x 实测：base-b（直连，丢包 16%）banner 20 s、其上道反复超时 → 劣化的底座不优先
        return (good or ups or [None])[0]

    def degraded(self, b: str) -> bool:
        """底座劣化：最近连续 ≥ degraded_after 次 banner 慢（> 5 s）或读不到"""
        return bool((self.hosts.get(b) or {}).get("degraded"))

    def pick_route(self) -> str:
        """K-OPS-N08：按 route_order 选第一条“入口 TCP 通且没被判坏”的路；都不行用 direct"""
        rs = self.c.get("routes") or {}
        for r in self.c.get("route_order") or ["direct"]:
            info = self.relay.get("routes", {}).get(r, {})
            if r in rs and info.get("up") and now() >= self.route_bad_until.get(r, 0):
                return r
        return "direct"

    def ports(self, h: str) -> list[int]:
        return [lp for lp, _ in self.c["hosts"][h]["forwards"]]

    # ---- 接管：孤儿 ssh、旧循环、上一个监管进程留下的 ssh
    def adopt(self, h: str | None = None) -> None:
        procs = list_procs()
        hosts = [h] if h else list(self.hosts)
        if not self.legacy_done:
            for pid, name, cmd in procs:
                if name.lower() == "bash.exe" and any(s in cmd for s in self.c.get("legacy_loops", [])):
                    kill(pid)
                    self.log("ADOPT kill legacy loop", pid, cmd[-60:])
            self.legacy_done = True
        for hh in hosts:
            mine = f"Tag={self.host_tag(hh)}"
            st = self.hosts[hh]
            mux = self.c["hosts"][hh].get("kind") == "wsl_mux"
            for pid, name, cmd in procs:
                if name.lower() != ("wsl.exe" if mux else "ssh.exe"):
                    continue
                if mux:
                    tgt = self.c["hosts"][hh].get("ssh_host", hh)
                    if any(cmd.rstrip().endswith(f'{mine} {tgt}{suf}') for suf in ("", "-hk", "-t", "-tb", "-tc")):   # 精确匹配（-cmd 是 -cmd2 的前缀）
                        if st["pid"] is None and pid_alive(pid):
                            st.update(pid=pid, since_t=now() - 60, state="up", up_since_t=now(),
                                      route=_route_of(cmd), base=_base_of(cmd))
                            self.log("ADOPT own mux", hh, pid)
                        # 同一条 wsl.exe --exec 在 Windows 上是两个同命令行的进程（00:32 实测：杀“重复”的那个 = 杀掉主连接），不杀
                    continue
                if mine in cmd:
                    want = [f"127.0.0.1:{lp}:{rp}" if isinstance(rp, str) else f"127.0.0.1:{lp}:127.0.0.1:{rp}"
                            for lp, rp in self.c["hosts"][hh]["forwards"]]   # r3 修：底座 "10.0.0.36:22" 规格原先永远不匹配 → 每次重载都杀底座
                    if not all(w in cmd for w in want):              # 配置加了转发（例：8871 收编）→ 旧 ssh 不认领，杀掉按新配置重起
                        kill(pid)
                        self.log("ADOPT kill own ssh with stale forwards", hh, pid)
                        continue
                    want_r = self.c["hosts"][hh].get("route")
                    if self.is_lane(hh) and want_r and _route_of(cmd) not in (want_r, "direct"):   # r5：配置改成独立香港连接，旧的经底座（-t）道不认领，按新配置重起
                        kill(pid)
                        self.log("ADOPT kill own ssh on stale route", hh, pid, _route_of(cmd), "→", want_r)
                        continue
                    if st["pid"] is None and pid_alive(pid):          # 上一个监管进程起的：认领，不打断
                        st.update(pid=pid, since_t=now() - self.c.get("listen_grace_s", 45), state="up", up_since_t=now(),
                                  route=_route_of(cmd), base=_base_of(cmd))   # 认领时按命令行目标认路 / 认底座   # 认领的按“通”算，卡死要连续 hang_rounds 轮（23:44 一轮就杀的教训）
                        self.log("ADOPT own ssh", hh, pid)
                    elif st["pid"] != pid:                            # 同 Tag 多出来的：杀
                        kill(pid)
                        self.log("ADOPT kill duplicate", hh, pid)
                    continue
                if f"Tag={self.tag}-proxy-{hh}" in cmd:
                    continue
                if any(f"-L {p}:" in cmd or f"-L 127.0.0.1:{p}:" in cmd or f"-L{p}:" in cmd for p in self.ports(hh)):
                    kill(pid)
                    self.log("ADOPT kill orphan ssh", hh, pid, cmd[:160])

    # ---- 起 / 停
    def spawn(self, h: str, reason: str) -> None:
        st = self.hosts[h]
        try:
            self.adopt(h)
        except Exception as e:  # noqa: BLE001   接管失败不能挡住重连
            self.log("adopt error", h, repr(e)[:200])
        if st["pid"] and pid_alive(st["pid"]):
            return
        hc = self.c["hosts"][h]
        if hc.get("kind") == "wsl_mux":            # 上次残留的 socket 会让新 master 起不来
            subprocess.run(WSL + ["rm", "-f", hc["sock"]], capture_output=True, timeout=30, creationflags=NOWIN)
        cmd = self.ssh_cmd(h)
        p = subprocess.Popen(cmd, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, cwd=str(ROOT),
                             stderr=open(self.dir / f"ssh_{h}.err.log", "ab"), creationflags=NOWIN)
        st["route"] = "t" if hc.get("via") == "t" else (hc.get("route") or self.pick_route()) if hc.get("kind") == "base" else self.lane_route(h)
        if hc.get("via") == "t":
            st["base"] = self.pick_base(h) or hc.get("base")
        st.update(pid=p.pid, since_t=now(), up_since_t=None, state="connecting", hang=0, probe_t=0.0, _io=None)
        st["_popen"] = p
        self.log("SPAWN", h, p.pid, reason)

    def stop_host(self, h: str, reason: str, count: bool = True) -> None:
        st = self.hosts[h]
        if st["pid"]:
            kill(st["pid"])
            self.log("KILL", h, st["pid"], reason)
        st.update(pid=None, since_t=None, up_since_t=None, state="backoff")
        st["restarts"] += 1
        st["last_restart"] = {"t": now(), "reason": reason}
        self.schedule(h, count)

    def schedule(self, h: str, count: bool = True) -> None:
        st = self.hosts[h]
        r = st.get("route")
        if count and r and r in (self.c.get("routes") or {}) and r != "direct" and self.c["hosts"][h].get("kind") == "base":    # 只算底座在主路上的真实失败：计数，≥ route_fail_max 判坏 10 分钟，退回直连
            self.route_fails[r] = self.route_fails.get(r, 0) + 1
            if self.route_fails[r] >= self.c.get("route_fail_max", 4):
                self.route_bad_until[r] = now() + self.c.get("route_bad_s", 600)
                self.route_fails[r] = 0
                self.log("ROUTE bad", r, f"连续失败 → {self.c.get('route_bad_s', 600)} s 内走备用")
        if self.c["hosts"][h].get("kind") == "base" or self.is_lane(h):   # r5：独立道连接同样在跳板握手 → 同一退避规则。运维 FONG-QUICK：快速失败 15 s 起翻倍、最多 5 分钟；跑够 60 s 再断 = 重置 15 s；不许更快
            up_s = st.get("_last_up_s", 0)
            st["_wait"] = 15 if (up_s >= 60 or not st.get("_wait")) else min(st["_wait"] * 2, 300)
            st["next_try_t"] = now() + st["_wait"]
            st["fails"] += 1
            return
        bo = self.c.get("backoff_s", [3, 6, 12, 24, 30])
        st["next_try_t"] = now() + bo[min(st["fails"], len(bo) - 1)]
        st["fails"] += 1

    # ---- 一拍
    def check_relay(self) -> bool:
        routes = self.c.get("routes")
        if routes:                                  # K-OPS-N08：每条路的入口各测一次 TCP；任一条通 = “跳板通”
            info = self.relay.setdefault("routes", {})
            for r, rc in routes.items():
                x = info.setdefault(r, {})
                # r3：不再每拍 TCP 探跳板（03:2x 实测：监管进程 5 s 一次的裸 TCP 探测是跳板“新建连接”的主要来源，
                # 跳板看来是只连不握手的可疑连接）。走这条路的底座 up = 这条路通；底座不在时才探，且每条路 ≥ 60 s 一次
                bup = any(v.get("kind") == "base" and v.get("route") == r and (self.hosts.get(k) or {}).get("state") == "up"
                          for k, v in self.c["hosts"].items())
                if bup:
                    x["up"], x["how"] = True, "base_up"
                elif now() - x.get("probe_t", 0) >= self.c.get("relay_probe_min_s", 60) or "up" not in x:
                    x["up"], x["how"], x["probe_t"] = tcp_ok(*rc["check"], timeout=5), "tcp", now()
                x["bad_until"] = self.route_bad_until.get(r, 0) or None
            up = any(v["up"] for v in info.values())
            cur = self.pick_route()
            if cur != self.relay.get("route"):
                self.log("ROUTE", self.relay.get("route"), "->", cur)
                self.relay["route_changed_t"] = now()
            self.relay["route"] = cur
        else:
            rh, rp = self.c["relay"]["check"]
            up = tcp_ok(rh, rp, timeout=5)
        t = now()
        if up != self.relay["up"]:
            self.relay["last_change_t"] = t
            self.log("RELAY", "up" if up else "DOWN")
            if up:                                  # 跳板恢复：内层退避清零；底座隧道仍守自己的退避（运维：不许更快）
                for hh, st in self.hosts.items():
                    if self.c["hosts"][hh].get("kind") != "base":
                        st["fails"], st["next_try_t"] = 0, 0.0
        self.relay.update(up=up, checked_t=t)
        if up:
            self.relay["last_ok_t"], self.relay["down_since_t"] = t, None
        else:
            self.relay["down_since_t"] = self.relay["down_since_t"] or t
        return up

    def probe_round(self, h: str) -> None:
        st = self.hosts[h]
        hc = self.c["hosts"][h]
        if hc.get("kind") == "base":
            inner_ok = [x for x, y in self.hosts.items() if y.get("base") == h and y["state"] == "up"
                        and any(v.get("ok") for v in y["ports"].values())]
            if st["state"] == "up" and inner_ok and now() - st.get("banner_t", 0) < self.c.get("banner_every_s", 300):
                st["probe_t"] = now()            # 12:1x：其上内层都在正常干活就不探 banner（每次探都是服务器 sshd 一条只连不握手的连接，
                return                           # gpu36 auth.log 刷 kex_exchange_identification，还占 MaxStartups 名额）；至少 5 分钟探一次
            st["banner_t"] = now()
            t0 = now()
            res = [ssh_banner(lp) for lp, _ in hc["forwards"]]
            t = now()
            st["banner_s"] = round(t - t0, 1)
            slow = t - t0 > 5 or not all(res)
            st["slow_streak"] = st.get("slow_streak", 0) + 1 if slow else 0
            st["good_streak"] = 0 if slow else st.get("good_streak", 0) + 1
            if slow:
                self.log("BASE banner slow", h, f"{t - t0:.1f}s", res)
            # 滞回：连续 degraded_after 次慢 → 劣化；连续 recover_after 次正常（约 90 s）才算恢复，恢复后再等 migrate_after_s 才迁回（11:57 实测一次好就迁回 → 来回抖）
            if not st.get("degraded") and st["slow_streak"] >= self.c.get("degraded_after", 2):
                st["degraded"], st["degraded_t"] = True, t
                self.log("BASE degraded", h, f"slow_streak={st['slow_streak']}")
            elif st.get("degraded") and st["good_streak"] >= self.c.get("recover_after", 6):
                st["degraded"], st["recovered_t"] = False, t
                self.log("BASE recovered", h, f"good_streak={st['good_streak']}")
            st["probe_t"] = t
            st["ports"] = {str(lp): {"remote": rp, "ok": ok, "why": "ok" if ok else "no_banner", "checked_t": t}
                           for (lp, rp), ok in zip(hc["forwards"], res)}
            age = t - (st["since_t"] or t)
            if any(res):
                st["hang"], st["fails"] = 0, 0
                if st["state"] != "up":
                    st["up_since_t"] = t
                    self.log("UP", h, st["pid"], "base", st.get("route"), f"{age:.0f}s after spawn")
                st["state"] = "up"
            elif age >= self.c.get("listen_grace_s", 45) or st["state"] == "up":
                prev, cur = st.get("_io"), io_bytes(st["pid"])
                st["_io"] = cur
                moving = prev is not None and cur is not None and cur > prev + 4096
                inner_ok = [x for x, y in self.hosts.items() if y.get("base") == h and y["state"] == "up"
                            and any(v.get("ok") for v in y["ports"].values())]
                if st["state"] == "up" and (moving or inner_ok):
                    st["hang"] = 0
                    for v in st["ports"].values():
                        v["why"] = "banner_slow_but_alive"
                    self.log("BASE banner slow but alive", h, "io moving" if moving else f"inner ok {len(inner_ok)}")
                    return
                st["hang"] += 1
                self.log("PROBE fail", h, st["pid"], "no_banner", f"round {st['hang']}")
                if st["hang"] >= self.c.get("hang_rounds", 3) or st["state"] != "up":
                    self.stop_host(h, f"底座隧道读不到服务器 sshd banner、也没在搬数据（{age:.0f}s）")
            return
        if hc.get("kind") == "wsl_mux":
            ok = mux_check(hc["sock"], hc.get("ssh_host", h))
            t = now()
            st["probe_t"] = t
            st["ports"] = {"mux": {"remote": None, "ok": ok, "why": "ok" if ok else "no_master", "checked_t": t}}
            age = t - (st["since_t"] or t)
            if ok:
                st["hang"], st["fails"] = 0, 0
                if st["state"] != "up":
                    st["up_since_t"] = t
                    self.log("UP", h, st["pid"], "mux", f"{age:.0f}s after spawn")
                st["state"] = "up"
            elif age >= self.c.get("listen_grace_s", 45):
                self.stop_host(h, f"WSL 主连接 {age:.0f}s 仍不可用")
            return
        pp = hc.get("probe_http") or self.ports(h)
        to = self.c.get("probe_timeout_s", 8)
        with ThreadPoolExecutor(len(pp)) as ex:
            res = dict(zip(pp, ex.map(lambda p: probe_http(p, to), pp)))
        t = now()
        rmap = dict(hc["forwards"])
        st["ports"] = {str(p): {"remote": rmap.get(p), "ok": r == "ok", "why": r, "checked_t": t} for p, r in res.items()}
        st["probe_t"] = t
        age = t - (st["since_t"] or t)
        prev, cur = st.get("_io"), io_bytes(st["pid"])
        st["_io"] = cur
        moving = prev is not None and cur is not None and cur > prev + 4096
        if any(r in ("ok", "remote_down") for r in res.values()):   # ssh 通（至少一条通道打得开）
            st["hang"] = 0
            st["fails"] = 0
            self.route_fails[st.get("route") or "direct"] = 0
            if st["state"] != "up":
                st["up_since_t"] = t
                self.log("UP", h, st["pid"], {p: r for p, r in res.items()}, f"{age:.0f}s after spawn")
            st["state"] = "up"
        elif moving:                                     # 探测超时但 ssh 在搬数据（> 4 KB / 轮）：跳板慢，不是卡死
            st["hang"] = 0
            for v in st["ports"].values():
                v["why"] = "busy" if v["why"] == "timeout" else v["why"]
            self.log("PROBE slow but ssh moving data", h, st["pid"], res)
        elif age >= self.c.get("listen_grace_s", 45) or st["state"] == "up":
            st["hang"] += 1
            self.log("PROBE fail", h, st["pid"], res, f"round {st['hang']}")
            if st["hang"] >= self.c.get("hang_rounds", 2) or (st["state"] != "up" and age >= self.c.get("listen_grace_s", 45)):
                self.stop_host(h, f"卡死：{res}（ssh 活着 {age:.0f}s）")

    def tick(self) -> None:
        relay_up = self.check_relay()
        t = now()
        due = []
        for h, st in self.hosts.items():
            alive = pid_alive(st["pid"])
            if st["pid"] and not alive:
                pop = st.pop("_popen", None)
                rc = pop.poll() if pop else None
                self.log("EXIT", h, st["pid"], f"rc={rc}")
                st["_last_up_s"] = t - (st.get("since_t") or t)
                try:
                    tail = (self.dir / f"ssh_{h}.err.log").read_bytes()[-4000:].decode("utf-8", "replace")
                except OSError:
                    tail = ""
                if "REMOTE HOST IDENTIFICATION HAS CHANGED" in tail:    # 运维：遇到就停，不删 known_hosts、不关指纹校验
                    st.update(pid=None, state="hostkey_changed", next_try_t=float("inf"))
                    self.log("HOSTKEY CHANGED", h, "停止重连，等人处理（不删 known_hosts）")
                    _alert("A-HOSTKEY", f"{h}: REMOTE HOST IDENTIFICATION HAS CHANGED，已停止重连，找运维核对指纹")
                    continue
                st.update(pid=None, since_t=None, up_since_t=None, state="backoff")
                st["restarts"] += 1
                st["last_restart"] = {"t": t, "reason": f"ssh 退出 rc={rc}"}
                if self.c["hosts"][h].get("kind") == "base":   # 底座断了：只清挂在它上面的内层，立刻改挂另一条底座（r3：≤30 s 恢复）
                    moved = []
                    for hh, x in self.hosts.items():
                        if self.c["hosts"][hh].get("via") == "t" and x["pid"] and x.get("base") in (h, None):
                            kill(x["pid"])
                            x.update(pid=None, since_t=None, up_since_t=None, state="wait_base", fails=0, next_try_t=0.0, hang=0)
                            x.pop("_popen", None)
                            moved.append(hh)
                    self.log("BASE down", h, "→ 清掉其上内层", moved, "改挂另一条底座")
                self.schedule(h)
                if not relay_up:
                    st["next_try_t"] = 0.0
            if st.get("state") == "hostkey_changed":
                continue
            if self.c["hosts"][h].get("via") == "t" and st["pid"] and st.get("base") and \
                    (self.hosts.get(st["base"]) or {}).get("state") not in ("up",) and self.pick_base(h):
                kill(st["pid"])                      # 它挂的底座已经不在、另一条在：立刻改挂
                self.log("REHOME", h, st.get("base"), "→", self.pick_base(h))
                st.update(pid=None, since_t=None, up_since_t=None, state="wait_base", fails=0, next_try_t=0.0, hang=0)
                st.pop("_popen", None)
            if not st["pid"] and self.c["hosts"][h].get("via") == "t" and not self.pick_base(h):
                st["state"] = "wait_base"            # 两条底座都没通，内层连接不起
                continue
            if not st["pid"]:
                if not relay_up:
                    st["state"] = "relay_down"
                    st["ports"] = {str(p): {"remote": r, "ok": False, "why": "relay_down", "checked_t": t}
                                   for p, r in self.c["hosts"][h]["forwards"] if p in (self.c["hosts"][h].get("probe_http") or [])}
                    continue
                connecting = sum(1 for x in self.hosts.values() if x["state"] == "connecting" and x["pid"])
                lim = self.c.get("max_connecting_inner", 4) if self.c["hosts"][h].get("via") == "t" else self.c.get("max_connecting", 2)
                if t >= st["next_try_t"] and connecting < lim:   # 新建连接全局串行：同时握手 ≤2（跳板 MaxStartups 10:30:100）
                    self.spawn(h, "跳板通、ssh 不在")
                elif t >= st["next_try_t"]:
                    st["state"] = "queued"
                else:
                    st["state"] = "backoff"
                continue
            every = self.c.get("probe_every_s", 15) if st["state"] == "up" and not st["hang"] else self.c.get("tick_s", 5)   # 一轮失败后改 5 s 复测
            if t - st["probe_t"] >= every:
                due.append(h)
        pref = self.pick_route()
        for h, st in self.hosts.items():             # 内层不在首选底座（或还连旧路由）、首选底座已稳定 ≥ migrate_after_s → 每拍迁一条（滚动）
            hc = self.c["hosts"][h]
            if hc.get("via") != "t" or not st["pid"] or st["state"] != "up":
                continue
            want = self.pick_base(h)                 # 首选底座；首选劣化时 = 另一条健康的
            wb = self.hosts.get(want) or {}
            # 13:2x 事故：两条底座交替“劣化 / 恢复”，按劣化主动迁移 = 不停杀掉正在干活的道（13:07–13:21 迁了 20+ 次，总调度看到 6 道全 refused）。
            # 改为：劣化只影响新起连接挑哪条；已在跑的连接只在底座死了（EXIT / REHOME）才换；回首选要首选连续健康 ≥ migrate_back_s，
            # 且全局每 migrate_gap_s 最多迁一条
            healthy_for = t - max(wb.get("up_since_t") or t, wb.get("recovered_t") or 0, wb.get("degraded_t") or 0)
            if want and want == hc.get("base") and st.get("base") != want and wb.get("state") == "up" and not self.degraded(want) and \
                    healthy_for >= self.c.get("migrate_back_s", 600) and t - getattr(self, "_last_mig_t", 0) >= self.c.get("migrate_gap_s", 60):
                self._last_mig_t = t
                self.stop_host(h, f"迁回首选底座 {st.get('base')} → {want}（首选已连续健康 {healthy_for:.0f}s）", count=False)
                st["fails"], st["next_try_t"] = 0, 0.0
                break
        if due:                                     # 两台并行探测：一拍最长约一个探测超时（20 s），心跳不拖过 90 s 线
            with ThreadPoolExecutor(len(due)) as ex:
                list(ex.map(self.probe_round, due))
        if self.conf_path == CONF:                  # 生产实例顺带写笔记本全局暂停快照（K-OPS-N04；测试实例不写）
            try:
                sys.path.insert(0, str(Path(__file__).resolve().parent))
                import dispatch
                if dispatch.snapshot_laptop():
                    self.log("SNAPSHOT laptop_ctrl 已更新")
                pt = getattr(self, "_rssh_probe_thread", None)
                if t - getattr(self, "_rssh_probe_t", 0) >= 60 and not (pt and pt.is_alive()):   # 命令通道合成探测：每台 1 次 / 分钟
                    self._rssh_probe_t = t
                    import threading

                    def _probe():
                        try:
                            import rssh
                            for hh in ("gpu33", "gpu36"):
                                try:
                                    rssh.run(hh, "true", timeout=20)
                                except Exception:  # noqa: BLE001  超时已由 rssh._note 记成失败
                                    pass
                        except Exception as e:  # noqa: BLE001
                            self.log("rssh probe error", repr(e)[:150])
                    self._rssh_probe_thread = threading.Thread(target=_probe, daemon=True)
                    self._rssh_probe_thread.start()
                if t - getattr(self, "_pull_t", 0) >= 60:         # K-OPS-N09：puller 常驻保活（拿得到它的锁 = 不在跑 → 拉起）
                    self._pull_t = t
                    self.ensure_puller()
                rt = getattr(self, "_rec_thread", None)
                if t - getattr(self, "_rec_t", 0) >= 30 and not (rt and rt.is_alive()):   # K-OPS-N06：30 s 一次
                    self._rec_t = t
                    import threading

                    def _rec(t=t):                        # 12:4x：reconcile 里会推送（经主连接取 / 推 partition，可达分钟级），
                        try:                              # 放后台线程，不拖住主循环心跳（否则 net_status 过期 → 看门狗报 A-SUPERVISOR）
                            r = dispatch.reconcile()
                            self.mode = {"override_active": bool((dispatch.read_override() or {}).get("active")),
                                         "phases": r["phases"], "checked_t": t}
                            if r.get("changed") or r.get("laptop_control"):
                                self.log("DISPATCH", r)
                        except Exception as e:  # noqa: BLE001
                            self.log("reconcile error", repr(e)[:200])
                    self._rec_thread = threading.Thread(target=_rec, daemon=True)
                    self._rec_thread.start()
            except Exception as e:  # noqa: BLE001
                self.log("snapshot error", repr(e)[:200])
        self.write_status()

    def ensure_puller(self) -> None:
        if (self.dir / "PULLER_OFF").exists():
            return
        import msvcrt
        try:
            f = open(self.dir / "puller.lock", "a+")
            msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
            msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            f.close()
        except OSError:
            return                                   # 锁被占 = puller 在跑
        pyw = ROOT / ".venv/Scripts/pythonw.exe"
        subprocess.Popen([str(pyw if pyw.exists() else sys.executable), "-u", str(ROOT / "tools/netfix/puller.py"), "serve"], cwd=str(ROOT),
                         stdin=subprocess.DEVNULL, stdout=open(self.dir / "puller.out.log", "ab"), stderr=subprocess.STDOUT,
                         creationflags=NOWIN | getattr(subprocess, "DETACHED_PROCESS", 0))
        self.log("PULLER started")

    def servers_view(self) -> dict:
        """服务器自主生产视图（取自 resident_sync.json；跳板断时这些值停在最后一次同步）"""
        rs = jl(RESIDENT, {}) or {}
        out = {}
        for h in sorted({self.c["hosts"][c].get("ssh_host", c) for c in self.hosts}):
            d = rs.get(h) or {}
            hl = d.get("health") or {}
            try:
                ht = time.mktime(time.strptime(hl.get("at", ""), "%Y-%m-%d %H:%M:%S")) if hl.get("at") else None
            except ValueError:
                ht = None
            lp = d.get("last_pull")
            out[h] = {"last_health_t": ht, "last_pull_t": lp, "last_push_t": d.get("last_push"),
                      "sync_age_min": round((now() - float(lp)) / 60, 1) if lp else None,
                      "producer_hb_age_min": hl.get("producer_hb_age_min"), "producer_paused": hl.get("producer_paused"),
                      "night_state_age_min": hl.get("night_state_age_min"), "dispatchable": hl.get("dispatchable"),
                      "autonomous": self.relay["up"] is False}
        return out

    def write_status(self) -> None:
        pub = {h: {**{k: v for k, v in st.items() if not k.startswith("_") and k not in ("fails", "hang", "probe_t")},
                   "server": self.c["hosts"][h].get("ssh_host", h)} for h, st in self.hosts.items()}
        total = sum(len(self.c["hosts"][h].get("probe_http") or []) for h in self.hosts)
        up = sum(1 for st in self.hosts.values() for k, p in st["ports"].items() if p.get("ok") and k != "mux")
        js(self.status_p, {"schema": STATUS_DOC["schema"], "at": iso(), "t": now(),
                           "supervisor": {"pid": os.getpid(), "started_t": self.started, "conf": str(self.conf_path)},
                           "relay": self.relay, "hosts": pub, "tunnels_up": up, "tunnels_total": total,
                           "servers": self.servers_view(), "dispatch_mode": getattr(self, "mode", None),
                           "transfer": jl(self.dir / "puller_status.json", None), "rssh": self.rssh_stats(), "_doc": STATUS_DOC})

    def rssh_stats(self) -> dict | None:
        """命令通道成功率（rssh.run 每次调用一行 data/netfix/rssh_calls.jsonl + 每分钟合成探测）：最近 1 小时 / 10 分钟。
        成功 = 连接层没出错（rc != 255 且未超时）；目标 > 99%（总调度 14:2x）。文件超过 5 MB 只留后半"""
        if now() - getattr(self, "_rssh_stat_t", 0) < 30 and getattr(self, "_rssh_stat", None) is not None:
            return self._rssh_stat
        p = self.dir / "rssh_calls.jsonl"
        try:
            raw = p.read_bytes()
        except OSError:   # arch-ok: 还没有任何调用记录 → 指标为空（None），不是 0%
            return None
        if len(raw) > 5_000_000:
            raw = raw[len(raw) // 2:]
            raw = raw[raw.find(b"\n") + 1:]
            tmp = p.with_suffix(".jsonl.tmp")
            tmp.write_bytes(raw)
            os.replace(tmp, p)
        t = now()
        out = {}
        for win, sec in (("1h", 3600), ("10m", 600)):
            agg = {}
            for ln in raw.splitlines()[-20000:]:
                try:
                    d = json.loads(ln)
                except ValueError:   # arch-ok: 并发追加偶有半行，跳过
                    continue
                if t - float(d.get("t") or 0) > sec:
                    continue
                a = agg.setdefault(d.get("host", "?"), {"n": 0, "ok": 0, "durs": []})
                a["n"] += 1
                a["ok"] += 1 if d.get("ok") else 0
                a["durs"].append(float(d.get("dur") or 0))
            out[win] = {h: {"n": a["n"], "ok": a["ok"], "rate": round(a["ok"] / a["n"], 4) if a["n"] else None,
                            "p50_s": sorted(a["durs"])[len(a["durs"]) // 2] if a["durs"] else None} for h, a in agg.items()}
        out["target"] = 0.99
        self._rssh_stat, self._rssh_stat_t = out, t
        return out

    def serve(self, max_s: float | None = None) -> None:
        self.log("START pid", os.getpid(), "conf", self.conf_path)
        try:
            self.adopt()
        except Exception as e:  # noqa: BLE001
            self.log("adopt error", repr(e)[:200])
        t0 = now()
        while max_s is None or now() - t0 < max_s:
            try:
                self.tick()
            except Exception as e:  # noqa: BLE001
                self.log("tick error", repr(e)[:300])
            if (self.dir / "STOP").exists():
                self.log("STOP file → exit（ssh 留着，下次认领）")
                break
            time.sleep(self.c.get("tick_s", 5))


# ---------------------------------------------------------------- 单实例 / 保活
def lock(state_dir: Path):
    import msvcrt
    f = open(state_dir / "supervisor.lock", "a+")
    try:
        msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
    except OSError:
        f.close()
        return None
    return f


def heartbeat_fresh(state_dir: Path = STATE_DIR, max_age: float = 90) -> bool:
    d = jl(state_dir / "net_status.json", {}) or {}
    return now() - float(d.get("t") or 0) < max_age and pid_alive((d.get("supervisor") or {}).get("pid"))


def ensure(conf: Path, state_dir: Path) -> str:
    if heartbeat_fresh(state_dir):
        return "running"
    f = lock(state_dir)                       # 拿得到锁 = 没有活着的监管进程
    if f is None:
        return "locked (starting or hung)"
    f.close()
    pyw = ROOT / ".venv/Scripts/pythonw.exe"
    exe = str(pyw if pyw.exists() else sys.executable)
    env = {**os.environ, "PYTHONUTF8": "1"}
    subprocess.Popen([exe, "-u", str(Path(__file__).resolve()), "serve", "--conf", str(conf), "--state-dir", str(state_dir)],
                     cwd=str(ROOT), stdin=subprocess.DEVNULL, stdout=open(state_dir / "supervisor.out.log", "ab"),
                     stderr=subprocess.STDOUT, env=env,
                     creationflags=NOWIN | getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0))
    return "started"


def _dry(conf: Path, status: dict) -> "Supervisor":
    """plan 用：只读配置 + 现状快照，不起 ssh、不写日志 / 状态（假定各路入口通、底座按快照）"""
    s = Supervisor.__new__(Supervisor)
    s.conf_path, s.c = Path(conf), jl(Path(conf), {})
    s.tag, s.route_bad_until, s.route_fails = s.c.get("tag_prefix", "nsnetfix"), {}, {}
    s.relay = {"routes": {r: {"up": True} for r in (s.c.get("routes") or {})}}
    sh = status.get("hosts") or {}
    s.hosts = {h: {"state": (sh.get(h) or {}).get("state", "up") if s.c["hosts"][h].get("kind") == "base" else "up"} for h in s.c["hosts"]}
    return s


def plan(new_conf: Path, cur_conf: Path = CONF, state_dir: Path = STATE_DIR) -> list[str]:
    """r5 dry：新配置相对当前配置（+ 运行快照）会变更哪些连接。只打印，不动任何进程 / 文件"""
    status = jl(Path(state_dir) / "net_status.json", {}) or {}
    cur, new = _dry(cur_conf, status), _dry(new_conf, status)
    run = status.get("hosts") or {}
    out, relay_n = [], {}
    for tag, s in (("cur", cur), ("new", new)):
        relay_n[tag] = sorted(h for h, v in s.c["hosts"].items() if v.get("kind") == "base" or s.is_lane(h))
    for h in list(cur.c["hosts"]) + [h for h in new.c["hosts"] if h not in cur.c["hosts"]]:
        r = run.get(h) or {}
        now_s = f"[运行中 {r.get('state')} route={r.get('route')} base={r.get('base')} pid={r.get('pid')}]"
        if h not in new.c["hosts"]:
            out.append(f"REMOVE  {h} {now_s}")
            continue
        nc = new.ssh_cmd(h)
        if h not in cur.c["hosts"]:
            out.append(f"ADD     {h} → {nc[-1]}")
            continue
        cc = cur.ssh_cmd(h)
        if cc == nc:
            out.append(f"KEEP    {h} → {nc[-1]} {now_s}")
            continue
        def _ka(cmd):                                # ssh 同名选项先出现的生效
            eff = {}
            for i, x in enumerate(cmd[:-1]):
                k = cmd[i + 1].split("=", 1)
                if x == "-o" and k[0] in ("ServerAliveInterval", "ServerAliveCountMax"):
                    eff.setdefault(k[0], k[1])
            return f"{eff.get('ServerAliveInterval')}s×{eff.get('ServerAliveCountMax')}"
        out.append(f"RESPAWN {h}: {cc[-1]} → {nc[-1]}  保活 {_ka(cc)} → {_ka(nc)} {now_s}")
    out.append(f"跳板上握手的长连接：{len(relay_n['cur'])} → {len(relay_n['new'])}（{', '.join(relay_n['new'])}）；"
               f"同时握手上限 max_connecting={new.c.get('max_connecting', 2)}")
    out.append("切换（总调度，producer 空闲时）：cp <新配置> config/netfix/tunnels.json → tunnel_supervisor.py stop → 等心跳过期 → ensure；"
               "新实例认领 KEEP 的连接不打断，RESPAWN 的旧 ssh（经底座 -t）在 adopt 时被杀并按新配置重起")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["serve", "ensure", "status", "stop", "plan"])
    ap.add_argument("--conf", default=str(CONF))
    ap.add_argument("--state-dir", default=str(STATE_DIR))
    ap.add_argument("--max-s", type=float, default=None)
    a = ap.parse_args(argv)
    sd = Path(a.state_dir)
    sd.mkdir(parents=True, exist_ok=True)
    if a.cmd == "plan":                              # r5 dry：--conf = 新配置；对照当前生产配置 + 运行快照
        print("\n".join(plan(Path(a.conf), CONF, sd)))
        return 0
    if a.cmd == "serve":
        f = lock(sd)
        if f is None:
            print("already running")
            return 0
        (sd / "STOP").unlink(missing_ok=True)
        (sd / "supervisor.pid").write_text(str(os.getpid()))
        Supervisor(Path(a.conf), sd).serve(a.max_s)
        return 0
    if a.cmd == "ensure":
        print(ensure(Path(a.conf), sd))
        return 0
    if a.cmd == "stop":
        (sd / "STOP").write_text(iso())
        print("STOP written")
        return 0
    d = jl(sd / "net_status.json", {}) or {}
    print(json.dumps({k: d.get(k) for k in ("at", "relay", "tunnels_up", "tunnels_total")}, ensure_ascii=False))
    for h, st in (d.get("hosts") or {}).items():
        print(h, st.get("state"), "pid", st.get("pid"), "restarts", st.get("restarts"),
              {p: v.get("why") for p, v in (st.get("ports") or {}).items()})
    print("fresh" if heartbeat_fresh(sd) else "STALE")
    return 0


if __name__ == "__main__":
    sys.exit(main())
