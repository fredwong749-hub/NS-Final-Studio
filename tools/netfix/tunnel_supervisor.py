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
    return "t" if c.endswith("-t") else "hk" if c.endswith("-hk") else "direct"


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
        route = self.pick_route()
        target = hc.get("ssh_host", h) + (self.c.get("routes") or {}).get(route, {}).get("suffix", "")
        if hc.get("kind") == "base":                # r2：底座隧道连跳板本身（香港 194relay-hk / 直连 194relay），只转发两台 sshd
            target = (self.c.get("routes") or {}).get(route, {}).get("relay", "194relay")
        elif hc.get("via") == "t":                  # r2：在底座隧道里直连服务器 sshd（127.0.0.1:22360 / 22330），不在跳板上握手
            target = hc.get("ssh_host", h) + "-t"
        cfg = self.c.get("ssh_config")
        if hc.get("kind") == "wsl_mux":            # P0 11-02：WSL OpenSSH 命令主连接（ControlMaster），远程命令 / 文件都复用它
            return WSL + ["ssh", *(["-F", self.c["ssh_config_wsl"]] if cfg else []), "-o", "BatchMode=yes", "-M", "-S", hc["sock"],
                          "-o", "ControlPersist=no", "-N", "-o", f"Tag={self.host_tag(h)}", target]
        if cfg:                                     # K-OPS-N08：项目 ssh 配置（香港中转主路 / 直连备用），相对路径 + cwd=ROOT（路径有空格）
            cmd = [self.c["ssh_exe"], "-F", cfg, *self.c["ssh_opts"], "-o", f"Tag={self.host_tag(h)}"]
        else:
            cmd = [self.c["ssh_exe"], *self.c["ssh_opts"], "-o", f"Tag={self.host_tag(h)}",
                   "-o", "ProxyCommand=" + self.c["relay"]["proxy_cmd"].replace("Tag=nsnetfix-proxy", f"Tag={self.tag}-proxy-{h}")]
        for lp, rp in hc["forwards"]:
            cmd += ["-L", f"127.0.0.1:{lp}:{rp}" if isinstance(rp, str) else f"127.0.0.1:{lp}:127.0.0.1:{rp}"]
        return cmd + [target]

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
                    if any(cmd.rstrip().endswith(f'{mine} {tgt}{suf}') for suf in ("", "-hk", "-t")):   # 精确匹配（-cmd 是 -cmd2 的前缀）
                        if st["pid"] is None and pid_alive(pid):
                            st.update(pid=pid, since_t=now() - 60, state="up", up_since_t=now(),
                                      route=_route_of(cmd))
                            self.log("ADOPT own mux", hh, pid)
                        # 同一条 wsl.exe --exec 在 Windows 上是两个同命令行的进程（00:32 实测：杀“重复”的那个 = 杀掉主连接），不杀
                    continue
                if mine in cmd:
                    want = [f"127.0.0.1:{lp}:127.0.0.1:{rp}" for lp, rp in self.c["hosts"][hh]["forwards"]]
                    if not all(w in cmd for w in want):              # 配置加了转发（例：8871 收编）→ 旧 ssh 不认领，杀掉按新配置重起
                        kill(pid)
                        self.log("ADOPT kill own ssh with stale forwards", hh, pid)
                        continue
                    if st["pid"] is None and pid_alive(pid):          # 上一个监管进程起的：认领，不打断
                        st.update(pid=pid, since_t=now() - self.c.get("listen_grace_s", 45), state="up", up_since_t=now(),
                                  route=_route_of(cmd))   # 认领时按命令行目标认路   # 认领的按“通”算，卡死要连续 hang_rounds 轮（23:44 一轮就杀的教训）
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
        st["route"] = self.pick_route()
        st.update(pid=p.pid, since_t=now(), up_since_t=None, state="connecting", hang=0, probe_t=0.0, _io=None)
        st["_popen"] = p
        self.log("SPAWN", h, p.pid, reason)

    def stop_host(self, h: str, reason: str) -> None:
        st = self.hosts[h]
        if st["pid"]:
            kill(st["pid"])
            self.log("KILL", h, st["pid"], reason)
        st.update(pid=None, since_t=None, up_since_t=None, state="backoff")
        st["restarts"] += 1
        st["last_restart"] = {"t": now(), "reason": reason}
        self.schedule(h)

    def schedule(self, h: str) -> None:
        st = self.hosts[h]
        r = st.get("route")
        if r and r != "direct" and self.c.get("routes"):    # 主路上连续失败：计数，≥ route_fail_max 判坏 10 分钟，退回直连
            self.route_fails[r] = self.route_fails.get(r, 0) + 1
            if self.route_fails[r] >= self.c.get("route_fail_max", 4):
                self.route_bad_until[r] = now() + self.c.get("route_bad_s", 600)
                self.route_fails[r] = 0
                self.log("ROUTE bad", r, f"连续失败 → {self.c.get('route_bad_s', 600)} s 内走备用")
        if self.c["hosts"][h].get("kind") == "base":   # 运维 FONG-QUICK：快速失败 15 s 起翻倍、最多 5 分钟；跑够 60 s 再断 = 重置 15 s；不许更快
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
                info.setdefault(r, {})["up"] = tcp_ok(*rc["check"], timeout=5)
                info[r]["bad_until"] = self.route_bad_until.get(r, 0) or None
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
            res = [ssh_banner(lp) for lp, _ in hc["forwards"]]
            t = now()
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
                st["hang"] += 1
                if st["hang"] >= self.c.get("hang_rounds", 3) or st["state"] != "up":
                    self.stop_host(h, f"底座隧道读不到服务器 sshd banner（{age:.0f}s）")
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
                self.schedule(h)
                if not relay_up:
                    st["next_try_t"] = 0.0
            if st.get("state") == "hostkey_changed":
                continue
            if not st["pid"] and self.c["hosts"][h].get("via") == "t" and (self.hosts.get("base") or {}).get("state") != "up":
                st["state"] = "wait_base"            # 底座隧道没通，内层连接不起
                continue
            if not st["pid"]:
                if not relay_up:
                    st["state"] = "relay_down"
                    st["ports"] = {str(p): {"remote": r, "ok": False, "why": "relay_down", "checked_t": t}
                                   for p, r in self.c["hosts"][h]["forwards"] if p in (self.c["hosts"][h].get("probe_http") or [])}
                    continue
                connecting = sum(1 for x in self.hosts.values() if x["state"] == "connecting" and x["pid"])
                if t >= st["next_try_t"] and connecting < self.c.get("max_connecting", 2):   # 新建连接全局串行：同时握手 ≤2（跳板 MaxStartups 10:30:100）
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
        if self.c.get("routes") and t - self.relay.get("route_changed_t", 0) > self.c.get("migrate_after_s", 120):
            for h, st in self.hosts.items():         # 回到主路：每拍最多迁一条（逐条断开重连，不一次全断）
                if st["pid"] and st["state"] == "up" and self.c["hosts"][h].get("kind") == "base" and st.get("route", "direct") != pref:
                    self.stop_host(h, f"迁回主路 {st.get('route', 'direct')} → {pref}")
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
                if t - getattr(self, "_rec_t", 0) >= 30:          # K-OPS-N06 临时覆盖：逐台交还状态机，30 s 一次
                    self._rec_t = t
                    r = dispatch.reconcile()
                    self.mode = {"override_active": bool((dispatch.jl(dispatch.OVERRIDE, {}) or {}).get("active")),
                                 "phases": r["phases"], "checked_t": t}
                    if r.get("changed") or r.get("laptop_control"):
                        self.log("DISPATCH", r)
            except Exception as e:  # noqa: BLE001
                self.log("snapshot error", repr(e)[:200])
        self.write_status()

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
                           "servers": self.servers_view(), "dispatch_mode": getattr(self, "mode", None), "_doc": STATUS_DOC})

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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["serve", "ensure", "status", "stop"])
    ap.add_argument("--conf", default=str(CONF))
    ap.add_argument("--state-dir", default=str(STATE_DIR))
    ap.add_argument("--max-s", type=float, default=None)
    a = ap.parse_args(argv)
    sd = Path(a.state_dir)
    sd.mkdir(parents=True, exist_ok=True)
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
