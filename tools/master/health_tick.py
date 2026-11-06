"""SELF-HEAL 11-05（项目方原话：“只是个自动化系统，一旦出现异常，系统自动重启，自动解决问题，以及报错”；L-196 / L-198 全自动）。

唯一的“健康一拍”：autoflow_resident（笔记本规范常驻）里起一个独立守护线程，每 ≤60 s 调一次 tick()（见 autoflow_resident.health_thread）。
不另起一套系统：每项自愈都复用现成部件——ops/restart_*.ps1、restart_queue、sop_gate.auto_probe_stale、hold_expiry、计划任务。

检查（每项独立开关 config/master/health_tick.json checks.*）：
  laptop_procs   resident_sync loop / lane_relay serve（配置启用才查）/ monitor :8810 / api :8800 / 守护脚本两份；重复进程只报（kill_duplicates=true 才停多的）
  tunnels        config/netfix/tunnels.json 里 probe_http 的本机端口（含 18290）通否 + tunnel_supervisor 进程
  server         resident_sync.json 里每台 health：记录过期 / producer 心跳 / night 心跳 / VQA 看图守护（vqa_guard.json）
  gpu_idle       某道空闲（util<5 且队列 0）> idle_lane_min 分钟，同时 registry 有 ready 对象 → 报
  holds          hold 没带 expires_at 且挂 >6 h / 暂停挂 >pause_stale_min：报（hold_expiry 已让它失效，这里让人看见；不删）
  stale_prompt   sop_gate 提示词“证据过期” → sop_gate.auto_probe_stale
  deploy_stale   最近一次部署（data/system_versions/deploy_*.json）晚于进程启动 + grace → 重启（笔记本脚本 / 服务器走 restart_queue）
修复统一过 apply_remedy：apply=false（默认）只记 would_*；apply=true 才动手；FIX-ORCH O5：apply_checks 里列的“检查 → 修复”单独放开
（stale_prompt 自动探针、deploy_stale 重启笔记本常驻；服务器 rq_restart 仍随全局 apply），min_gap_s 给同一 key 加最短间隔（deploy_stale 30 分钟）；每个 key 指数退避（60→900 s）+ 每小时最多 max_restarts_per_hour 次，
超了 = 熔断：不再自动重启，登记 P0（需人）。从不静默：新问题连续 confirm_ticks 拍都在 → report_issue + CHANNEL 一行 + 状态文件；报告本身失败写 unreported.jsonl。
硬约束：从不删；从不按名字 pkill（停进程只按 pid，且重复进程默认只报）；不碰 gpu33:2；服务器 producer / night 只经 restart_queue；渲染中不打断（restart_queue 自带排空）。
"""
from __future__ import annotations

import glob
import importlib.util
import json
import os
import re
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG_PATH = ROOT / "config/master/health_tick.json"
WHO = "SELF-HEAL"
NEVER_LANES = ("gpu33:2",)
HOUR = 3600.0

DEFAULT_CFG = {
    "apply": False, "every_s": 45, "confirm_ticks": 2, "max_restarts_per_hour": 3, "backoff_base_s": 60, "backoff_max_s": 900,
    "idle_lane_min": 5, "producer_hb_stale_min": 5, "night_hb_stale_min": 10, "health_stale_min": 15, "pause_stale_min": 30,
    "deploy_grace_min": 5, "kill_duplicates": False, "report_repeat_h": 6, "run_timeout_s": 300,
    "checks": {"laptop_procs": True, "tunnels": True, "server": True, "gpu_idle": True, "holds": True, "stale_prompt": True, "deploy_stale": True},
    "ports": {"monitor": 8810, "api": 8800},
    "guards": {"resident_guard": "NS-Studio-ResidentSync-Guard", "monitor_guard": "NS-Studio-Monitor-Guard"},
    "tunnel_task": "NS-Studio-TunnelSupervisor",
    "ignore_tunnel_ports": [],
    # FIX-ORCH O5（11-06，L-205）：全局 apply 仍可为 false，这几项修复单独放开（分项 apply）；min_gap_s = 同一 key 两次修复的最短间隔
    "apply_checks": {"stale_prompt": ["probe_stale"],
                     "deploy_stale": ["restart_resident_sync", "stop_start_lane_relay", "flag_restart_autoflow"]},
    "min_gap_s": {"deploy_stale": 1800},
}


def _j(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):   # arch-ok: 读不出 = 用默认（调用方按失败关闭处理）
        return default


def _jw(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def load_cfg(path: Path = CFG_PATH) -> dict:
    d = _j(path, {}) or {}
    out = {**DEFAULT_CFG, **{k: v for k, v in d.items() if not k.startswith("_")}}
    out["checks"] = {**DEFAULT_CFG["checks"], **(d.get("checks") or {})}
    return out


def jst_hm(now: float) -> str:
    return time.strftime("%m-%d %H:%M", time.gmtime(now + 9 * 3600))


def _load(name: str, rel: str, root: Path = ROOT):
    sp = importlib.util.spec_from_file_location(name, Path(root) / rel if (Path(root) / rel).is_file() else ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


# ------------------------------------------------------------------ 环境（全部可注入，测试用）
class Env:
    """所有对外读写集中在这里；测试用子类 / 假对象替换"""

    def __init__(self, root: Path = ROOT):
        self.root = Path(root)

    def now(self) -> float:
        return time.time()

    def j(self, rel, default=None):
        return _j(self.root / rel, default)

    def mtime(self, path) -> float | None:
        try:
            return Path(path).stat().st_mtime
        except OSError:
            return None

    def globs(self, pattern: str) -> list[str]:
        return glob.glob(str(self.root / pattern))

    def procs(self) -> list[dict]:
        """[{pid, ppid, cmd, created(epoch)}]（Windows：Get-CimInstance；别处：ps）。读不到 = 空"""
        try:
            if os.name == "nt":
                ps = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^(python|pythonw|powershell|pwsh)\\.exe$' } | "
                      "ForEach-Object { [pscustomobject]@{pid=$_.ProcessId;ppid=$_.ParentProcessId;cmd=$_.CommandLine;"
                      "created=([DateTimeOffset]$_.CreationDate).ToUnixTimeSeconds()} } | ConvertTo-Json -Compress")
                r = subprocess.run(["powershell", "-NoProfile", "-Command", ps], capture_output=True, text=True, encoding="utf-8", timeout=60, stdin=subprocess.DEVNULL)
                d = json.loads(r.stdout or "[]")
                return [x for x in (d if isinstance(d, list) else [d]) if x.get("cmd")]
            r = subprocess.run(["ps", "-eo", "pid=,ppid=,lstart=,args="], capture_output=True, text=True, timeout=30)
            out = []
            for ln in r.stdout.splitlines():
                m = re.match(r"\s*(\d+)\s+(\d+)\s+(\w{3}\s+\w{3}\s+\d+ [\d:]+ \d{4})\s+(.*)", ln)
                if m:
                    out.append({"pid": int(m[1]), "ppid": int(m[2]), "cmd": m[4],
                                "created": time.mktime(time.strptime(re.sub(r"\s+", " ", m[3]), "%a %b %d %H:%M:%S %Y"))})
            return out
        except (OSError, ValueError, subprocess.SubprocessError):   # arch-ok: 列不出进程 = 本拍不判进程类（不凭空重启）
            return []

    def pid_alive(self, pid: int) -> bool:
        return any(p["pid"] == pid for p in self.procs())

    def http_ok(self, url: str, timeout: float = 8) -> bool:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as r:
                return 200 <= r.status < 300
        except (OSError, ValueError):   # arch-ok: 连不上 / 非 2xx / 超时
            return False

    def tcp_ok(self, port: int, timeout: float = 3) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", int(port)), timeout=timeout):
                return True
        except OSError:
            return False

    def run(self, cmd: list[str], timeout: float = 300) -> dict:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, cwd=self.root, stdin=subprocess.DEVNULL)
            return {"ok": r.returncode == 0, "rc": r.returncode, "out": ((r.stdout or "") + (r.stderr or "")).strip()[-300:]}
        except (OSError, subprocess.SubprocessError) as e:
            return {"ok": False, "rc": -1, "out": f"{type(e).__name__}: {e}"[:300]}

    def spawn_detached(self, cmd: list[str], log: str) -> dict:
        """脱离会话 / 作业对象起（和 autoflow_resident.detach 同口径），日志追加到 ops/logs/<log>"""
        try:
            logs = self.root / "ops/logs"
            logs.mkdir(parents=True, exist_ok=True)
            with open(logs / f"{log}.out.log", "a", encoding="utf-8") as o, open(logs / f"{log}.err.log", "a", encoding="utf-8") as e:
                kw = {"cwd": str(self.root), "stdin": subprocess.DEVNULL, "stdout": o, "stderr": e, "close_fds": True, "env": {**os.environ, "PYTHONUTF8": "1"}}
                if os.name == "nt":
                    base = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
                    try:
                        p = subprocess.Popen(cmd, creationflags=base | subprocess.CREATE_BREAKAWAY_FROM_JOB, **kw)
                    except OSError:
                        p = subprocess.Popen(cmd, creationflags=base, **kw)
                else:
                    p = subprocess.Popen(cmd, start_new_session=True, **kw)
            return {"ok": True, "pid": p.pid}
        except OSError as e:
            return {"ok": False, "out": f"{type(e).__name__}: {e}"[:300]}

    def _rq(self):
        if str(self.root / "tools/autopilot") not in sys.path:
            sys.path.insert(0, str(self.root / "tools/autopilot"))
        import restart_queue as RQ
        return RQ

    def rq_pending(self, host: str) -> list:
        return self._rq().pending(host)

    def rq_request(self, host: str, reason: str, mode: str, urgent: bool) -> dict:
        return self._rq().request(host, reason, by=WHO, urgent=urgent, mode=mode)

    def probe_stale(self, run: str, ep: int, missing: list) -> str | None:
        return _load("sop_gate_for_health", "tools/master/sop_gate.py", self.root).auto_probe_stale(run, ep, self.root, missing)

    def stale_prompt_eps(self, run: str) -> list[tuple[int, list]]:
        sg = _load("sop_gate_for_health", "tools/master/sop_gate.py", self.root)
        out = []
        for e in (sg.stage_view(run, self.root).get("episodes") or []):
            if e.get("stage") in ("提示词", "出图"):
                r = sg.judge(run, int(e["episode"]), "出图", None, self.root)
                if sg._is_stale_evidence(r.get("missing") or []):          # O1：过期 / 还没有（新集）/ 探针超时
                    out.append((int(e["episode"]), list(r.get("missing") or [])))
        return out

    def report(self, run: str, step: str, what: str, fix_hint: str, blocking: bool) -> str | None:
        ri = _load("report_issue_for_health", "tools/master/report_issue.py", self.root)
        return ri.report(run=run, episode=0, step=step, who=WHO, what=what, blocking=blocking, fix_hint=fix_hint).get("id")

    def channel(self, level: str, text: str, now: float) -> None:
        line = f"{jst_hm(now)}(JST) | {WHO} | {level} | {text}\n"
        fd = os.open(self.root / "docs/master/CHANNEL.md", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

    def write_json(self, rel: str, d) -> None:
        _jw(self.root / rel, d)


# ------------------------------------------------------------------ 检查：每项 → [finding]
def F(key: str, check: str, what: str, fix_hint: str = "", remedy: dict | None = None, blocking: bool = False, run: str = "-") -> dict:
    return {"key": key, "check": check, "what": what, "fix_hint": fix_hint, "remedy": remedy, "blocking": blocking, "run": run}


def match_procs(procs: list[dict], regex: str) -> list[dict]:
    rx = re.compile(regex)
    return [p for p in procs if rx.search(p.get("cmd") or "")]


def roots(ps: list[dict]) -> list[dict]:
    """venv 转发器 + 真 python 是父子两个进程：只数“父不在同一组里”的根，按创建时间老→新"""
    pids = {p["pid"] for p in ps}
    return sorted((p for p in ps if p.get("ppid") not in pids), key=lambda p: p.get("created") or 0)


def release_busy(env: Env, now: float) -> str | None:
    try:
        r = env.j("data/system_versions/release_lock.json", {}) or {}
        if r.get("pid") and now - float(r.get("t") or 0) < 6 * HOUR and env.pid_alive(int(r["pid"])):
            return f"release_lock pid {r['pid']}"
        c = env.j("data/system_versions/cut_lock.json", {}) or {}
        if c.get("active") and float(c.get("expires_t") or 0) > now:
            return f"cut_lock {c.get('sv')}"
    except (ValueError, TypeError):
        return None
    return None


def primary_run(env: Env) -> str:
    return str((env.j("config/pipeline/runs.json", {}) or {}).get("primary") or "")


def check_laptop_procs(env: Env, cfg: dict, st: dict, now: float, procs: list[dict]) -> list[dict]:
    out = []
    rs = roots(match_procs(procs, r"tools[\\/]autopilot[\\/]resident_sync\.py.*\bloop\b"))
    if not rs:
        out.append(F("proc:resident_sync", "laptop_procs", "resident_sync loop 进程不在", "resident_guard 应在 60 s 内拉起；不然 ops/restart_resident_sync.ps1",
                     {"name": "start_resident_sync"}, blocking=True))
    elif len(rs) > 1:
        out.append(F("dup:resident_sync", "laptop_procs", f"resident_sync loop 有 {len(rs)} 份（pid {[p['pid'] for p in rs]}）", "保留最老的一份",
                     {"name": "stop_duplicates", "pids": [p["pid"] for p in rs[1:]]}))
    lr = _j(env.root / "config/pipeline/lane_relay.json", {}) or {}
    if lr.get("enabled"):
        ls = roots(match_procs(procs, r"tools[\\/]autopilot[\\/]lane_relay\.py.*\bserve\b"))
        if not ls:
            out.append(F("proc:lane_relay", "laptop_procs", "lane_relay serve 不在（借道已启用）", "起 lane_relay serve（脱离会话）", {"name": "start_lane_relay"}))
        elif len(ls) > 1:
            out.append(F("dup:lane_relay", "laptop_procs", f"lane_relay serve 有 {len(ls)} 份（pid {[p['pid'] for p in ls]}）", "保留最老的一份",
                         {"name": "stop_duplicates", "pids": [p["pid"] for p in ls[1:]]}))
    gt = cfg["guards"]
    for name, rx in (("resident_guard", r"resident_guard\.ps1"), ("monitor_guard", r"monitor_guard\.ps1")):
        if not match_procs(procs, rx):
            out.append(F(f"proc:{name}", "laptop_procs", f"守护 {name}.ps1 不在", f"schtasks /run /tn {gt[name]}", {"name": "start_task", "task": gt[name]}, blocking=True))
    if not env.http_ok(f"http://127.0.0.1:{cfg['ports']['monitor']}/"):
        out.append(F("http:monitor", "laptop_procs", f"监控看板 :{cfg['ports']['monitor']} 不通", "monitor_guard 会拉起；不在则 schtasks /run",
                     {"name": "start_task", "task": gt["monitor_guard"]}))
    if not env.http_ok(f"http://127.0.0.1:{cfg['ports']['api']}/api/owner/queue", 15):
        out.append(F("http:api", "laptop_procs", f"API :{cfg['ports']['api']} 不通", "ops/restart_api.ps1 -Force -Revive", {"name": "restart_api"}, blocking=True))
    return out


def check_tunnels(env: Env, cfg: dict, st: dict, now: float, procs: list[dict]) -> list[dict]:
    out = []
    sup = bool(match_procs(procs, r"tunnel_supervisor\.py.*serve"))
    if not sup:
        out.append(F("proc:tunnel_supervisor", "tunnels", "tunnel_supervisor 不在", f"schtasks /run /tn {cfg['tunnel_task']}（该任务每 5 分钟本就重复）",
                     {"name": "start_task", "task": cfg["tunnel_task"]}, blocking=True))
    ign = set(cfg.get("ignore_tunnel_ports") or [])
    dead = []
    for host, v in ((env.j("config/netfix/tunnels.json", {}) or {}).get("hosts") or {}).items():
        for port in v.get("probe_http") or []:
            if port not in ign and not env.tcp_ok(port):
                dead.append(f"{host}:{port}")
    if dead:
        out.append(F("tunnel:ports", "tunnels", f"隧道端口不通：{', '.join(dead)}（18290 = gpu36:2）", "tunnel_supervisor 自己重连；持续不通看 data/netfix/net_status.json；已退役的口写进 health_tick.json ignore_tunnel_ports",
                     None if sup else {"name": "start_task", "task": cfg["tunnel_task"]}))
    return out


def check_server(env: Env, cfg: dict, st: dict, now: float, procs: list[dict]) -> list[dict]:
    out = []
    rs = env.j("data/autopilot/resident_sync.json", {}) or {}
    run = primary_run(env) or "-"
    for host in ("gpu33", "gpu36"):
        h = (rs.get(host) or {}).get("health") or {}
        try:
            age = (now - time.mktime(time.strptime(h["at"], "%Y-%m-%d %H:%M:%S"))) / 60
        except (KeyError, ValueError, TypeError):
            age = None
        if age is None or age > cfg["health_stale_min"]:
            out.append(F(f"srv:{host}:health", "server", f"{host} 健康记录{'没有' if age is None else f' {age:.0f} 分钟没更新'}（resident_sync 探不到 / ssh 断）",
                         "看 resident_sync 日志与隧道；判不了时不动服务器", None, run=run))
            continue
        pa, na = h.get("producer_hb_age_min"), h.get("night_state_age_min")
        if (pa is None or pa > cfg["producer_hb_stale_min"]) and not h.get("producer_paused"):
            urgent = pa is None or pa > 2 * cfg["producer_hb_stale_min"]
            out.append(F(f"srv:{host}:producer", "server", f"{host} producer 心跳{'没有' if pa is None else f' {pa:.0f} 分钟前'}", "经 restart_queue 重启 producer（排空 + 合并）",
                         {"name": "rq_restart", "host": host, "mode": "producer-only", "urgent": urgent}, blocking=True, run=run))
        if na is not None and na > cfg["night_hb_stale_min"]:
            out.append(F(f"srv:{host}:night", "server", f"{host} night 心跳 {na:.0f} 分钟前", "经 restart_queue 重启 night",
                         {"name": "rq_restart", "host": host, "mode": "night-only", "urgent": False}, run=run))
    for k, v in ((env.j("data/autopilot/vqa_guard.json", {}) or {}).items()):
        if isinstance(v, dict) and int(v.get("fails") or 0) >= 2:
            out.append(F(f"srv:vqa:{k}", "server", f"看图守护 {k} 连续失败 {v.get('fails')} 次：{str(v.get('last_error'))[:120]}",
                         "resident_sync W40 已在拉起 / 登记；这里只兜底可见（:8870 :8873 :8874）", None))
    return out


def held_lanes(env: Env) -> set:
    nc = env.j("config/pipeline/night_control.json", {}) or {}
    ret = (env.j("data/state/netfix/partition.json", {}) or {}).get("retired_lanes") or []     # L-209 S2.3：唯一一份
    return {str(x) for x in list(nc.get("hold_lanes") or []) + list(ret)}


def check_gpu_idle(env: Env, cfg: dict, st: dict, now: float, procs: list[dict]) -> list[dict]:
    run = primary_run(env)
    ready = int(((env.j(f"data/producer/runs/{run}/registry.json", {}) or {}).get("counts") or {}).get("ready") or 0)
    rs = env.j("data/autopilot/resident_sync.json", {}) or {}
    held = held_lanes(env)
    idle = st.setdefault("idle", {})
    seen = set()
    for host in ("gpu33", "gpu36"):
        h = (rs.get(host) or {}).get("health") or {}
        for lid, ln in (h.get("lanes") or {}).items():
            lane = f"{host}:{lid}"
            if lane in NEVER_LANES or lane in held or h.get("producer_paused"):
                continue
            seen.add(lane)
            if float(ln.get("util") or 0) < 5 and int(ln.get("queue") or 0) == 0:
                idle.setdefault(lane, now)
            else:
                idle.pop(lane, None)
    for k in [k for k in idle if k not in seen]:
        idle.pop(k)
    stuck = {k: v for k, v in idle.items() if now - v > cfg["idle_lane_min"] * 60}
    if ready > 0 and stuck:
        return [F("gpu:idle_with_work", "gpu_idle", f"{len(stuck)} 条道空闲 > {cfg['idle_lane_min']} 分钟（{', '.join(sorted(stuck))}），registry 还有 {ready} 个 ready 对象",
                  "先看提示词证据（stale_prompt 检查自动 probe）/ hold / 暂停 / canary；都不是 → 总调度排查派单", None, blocking=True, run=run)]
    return []


def check_holds(env: Env, cfg: dict, st: dict, now: float, procs: list[dict]) -> list[dict]:
    out = []
    he = _load("hold_expiry_for_health", "tools/autopilot/hold_expiry.py", env.root)
    run = primary_run(env) or "-"
    nc_path = env.root / "config/pipeline/night_control.json"
    nc = _j(nc_path, {}) or {}
    exp = nc.get("hold_expires") or {}
    stale = []
    for lane in nc.get("hold_lanes") or []:
        ok, why = he.alive(exp.get(lane), env.mtime(nc_path), now)
        if not ok:
            stale.append(f"night_control {lane}：{why}")
    for f in env.globs("data/autopilot/*_hold.json") + env.globs("data/pipeline/*_hold.json"):
        d = _j(f, {}) or {}
        if d and isinstance(d, dict):
            ok, why = he.alive(d.get("expires_at"), env.mtime(f), now)
            if not ok:
                stale.append(f"{Path(f).name}：{why}")
    if stale:
        out.append(F("hold:stale", "holds", f"{len(stale)} 个 hold 没带有效 expires_at 且超期（hold_expiry 已忽略，文件还在）：{'；'.join(stale)[:300]}",
                     "写 expires_at 或由总调度撤掉（本检查不删）", None, run=run))
    rs = env.j("data/autopilot/resident_sync.json", {}) or {}
    pz = st.setdefault("paused_since", {})
    for host in ("gpu33", "gpu36"):
        paused = bool((((rs.get(host) or {}).get("health")) or {}).get("producer_paused"))
        if paused:
            pz.setdefault(host, now)
        else:
            pz.pop(host, None)
        if paused and now - pz[host] > cfg["pause_stale_min"] * 60:
            out.append(F(f"pause:{host}", "holds", f"{host} producer 暂停已 {int((now - pz[host]) / 60)} 分钟（没有到期时间）",
                         "确认是 canary / 排空 / 人工暂停；该撤就撤（先看 producer 日志 POLICY_CANARY）", None, run=run))
    return out


def check_stale_prompt(env: Env, cfg: dict, st: dict, now: float, procs: list[dict]) -> list[dict]:
    run = primary_run(env)
    if not run:
        return []
    return [F(f"prompt:{run}:ep{ep:02d}", "stale_prompt", f"{run} 第{ep}集提示词证据过期 / 还没有 / 探针超时", "自动后台 probe-prompts（锁按 pid 不叠跑；超时退避）",
              {"name": "probe_stale", "run": run, "ep": ep, "missing": missing}, run=run) for ep, missing in env.stale_prompt_eps(run)]


def check_deploy_stale(env: Env, cfg: dict, st: dict, now: float, procs: list[dict]) -> list[dict]:
    out = []
    marks = [t for t in (env.mtime(f) for f in env.globs("data/system_versions/deploy_*.json")) if t]
    if not marks:
        return out
    dep, grace = max(marks), cfg["deploy_grace_min"] * 60
    if now - dep < grace or release_busy(env, now):
        return out
    for key, rx, remedy in (("resident_sync", r"tools[\\/]autopilot[\\/]resident_sync\.py.*\bloop\b", {"name": "restart_resident_sync"}),
                            ("lane_relay", r"tools[\\/]autopilot[\\/]lane_relay\.py.*\bserve\b", {"name": "stop_start_lane_relay"}),
                            ("autoflow", r"tools[\\/]factory[\\/]autoflow_resident\.py", {"name": "flag_restart_autoflow"})):
        rs = roots(match_procs(procs, rx))
        if rs and (rs[0].get("created") or 0) + grace < dep:
            out.append(F(f"deploy:{key}", "deploy_stale", f"{key} 启动于 {jst_hm(rs[0]['created'])}，早于最近部署 {jst_hm(dep)}（跑的是旧代码）", "重启到新版本", remedy))
    rs_ = env.j("data/autopilot/resident_sync.json", {}) or {}
    for host in ("gpu33", "gpu36"):
        lr = (rs_.get(host) or {}).get("last_restart")
        if lr and float(lr) + grace < dep:
            out.append(F(f"deploy:{host}:producer", "deploy_stale", f"{host} 上次重启 {jst_hm(float(lr))}，早于最近部署 {jst_hm(dep)}（producer / night 可能还是旧代码）",
                         "经 restart_queue 排空后重启", {"name": "rq_restart", "host": host, "mode": "all", "urgent": False}))
    return out


CHECKS = {"laptop_procs": check_laptop_procs, "tunnels": check_tunnels, "server": check_server, "gpu_idle": check_gpu_idle,
          "holds": check_holds, "stale_prompt": check_stale_prompt, "deploy_stale": check_deploy_stale}


# ------------------------------------------------------------------ 修复：退避 + 熔断
def gate(rec: dict, cfg: dict, now: float) -> str:
    """→ ok / backoff / breaker。rec = 该 key 的修复记录 {tries: [epoch...], streak, next_try}"""
    rec["tries"] = [t for t in rec.get("tries", []) if now - t < HOUR]
    if len(rec["tries"]) >= int(cfg["max_restarts_per_hour"]):
        return "breaker"
    if now < float(rec.get("next_try") or 0):
        return "backoff"
    return "ok"


def _py(env: Env) -> str:
    p = env.root / ".venv/Scripts/python.exe"
    return str(p) if p.is_file() else sys.executable


def applies(cfg: dict, f: dict) -> bool:
    """全局 apply，或该检查的这项修复在 apply_checks 里（O5 分项放开）"""
    r = f.get("remedy") or {}
    return bool(cfg.get("apply")) or r.get("name") in ((cfg.get("apply_checks") or {}).get(f.get("check")) or [])


def apply_remedy(env: Env, cfg: dict, st: dict, f: dict, now: float, procs: list[dict]) -> dict:
    """一个 finding 的修复。返回 {action: none|dry|backoff|breaker|done|failed|cooldown}；修复记录写进 st['remedy'][key]"""
    r = f.get("remedy")
    if not r:
        return {"action": "none"}
    rec = st.setdefault("remedy", {}).setdefault(f["key"], {})
    g = gate(rec, cfg, now)
    if g != "ok":
        return {"action": g, "tries_1h": len(rec["tries"]), "next_try_in_s": max(0, int(float(rec.get("next_try") or 0) - now))}
    n, t = r["name"], cfg["run_timeout_s"]
    if n == "stop_duplicates" and not cfg.get("kill_duplicates"):
        return {"action": "dry", "would": "stop_duplicates（kill_duplicates=false，只报）"}
    if not applies(cfg, f):
        return {"action": "dry", "would": n}
    ps1 = lambda rel, *a: ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(env.root / rel), *a]   # noqa: E731
    lane_cmd = [_py(env), "-X", "utf8", "tools/autopilot/lane_relay.py", "serve"]
    if n == "restart_resident_sync":       # 脚本自己只停 resident_sync loop 的进程（existing ops 脚本）
        res = env.run(ps1("ops/restart_resident_sync.ps1"), t)
    elif n == "start_resident_sync":       # 进程不在：只起不杀，交给 resident_guard 的同一条命令
        res = env.spawn_detached([_py(env), "-u", "tools/autopilot/resident_sync.py", "loop"], "resident_sync.loop")
    elif n == "restart_api":
        res = env.run(ps1("ops/restart_api.ps1", "-Force", "-Revive"), t)
    elif n == "start_task":
        res = env.run(["schtasks", "/run", "/tn", r["task"]], 60)
    elif n == "start_lane_relay":
        res = env.spawn_detached(lane_cmd, "lane_relay")
    elif n == "stop_start_lane_relay":      # 只按 pid 停 lane_relay 的根进程（含其 venv 子进程），再起一份
        for p in roots(match_procs(procs, r"tools[\\/]autopilot[\\/]lane_relay\.py.*\bserve\b")):
            env.run(["taskkill", "/PID", str(p["pid"]), "/T", "/F"], 30)
        res = env.spawn_detached(lane_cmd, "lane_relay")
    elif n == "stop_duplicates":
        res = {"ok": all(env.run(["taskkill", "/PID", str(p), "/T", "/F"], 30)["ok"] for p in r["pids"])}
    elif n == "rq_restart":
        if str(r.get("host")) not in ("gpu33", "gpu36"):
            return {"action": "none", "why": "只认 gpu33 / gpu36"}
        if env.rq_pending(r["host"]):
            return {"action": "none", "why": "该机已有待办重启请求（restart_queue 合并 / 排空中）"}
        res = {"ok": True, "request": env.rq_request(r["host"], f"SELF-HEAL：{f['what']}"[:200], r["mode"], bool(r.get("urgent"))).get("id")}
    elif n == "probe_stale":
        s = env.probe_stale(r["run"], r["ep"], r.get("missing") or [])
        if s == "cooldown":                # 冷却中不算一次修复尝试
            return {"action": "cooldown"}
        res = {"ok": s == "started", "probe": s}
    elif n == "flag_restart_autoflow":      # 自己不杀自己：写旗，resident_guard 看到旗走 ops/restart_autoflow.ps1（只停锁里 pid）
        env.write_json("data/master/health/want_restart_autoflow.json", {"at": now, "why": f["what"]})
        res = {"ok": True, "flag": True}
    else:
        return {"action": "none", "why": f"不认识的修复 {n}"}
    rec["tries"].append(now)
    rec["streak"] = int(rec.get("streak") or 0) + 1
    rec["next_try"] = now + max(min(float(cfg["backoff_max_s"]), float(cfg["backoff_base_s"]) * 2 ** (rec["streak"] - 1)),
                                float((cfg.get("min_gap_s") or {}).get(f["check"]) or 0))     # O5：deploy_stale 每 key 30 分钟最多一次
    rec["last"] = {"at": now, "name": n, "ok": bool(res.get("ok")), "out": str(res.get("out") or res.get("request") or res.get("probe") or "")[:200]}
    return {"action": "done" if res.get("ok") else "failed", "name": n, **{k: v for k, v in res.items() if k != "ok"}}


# ------------------------------------------------------------------ 报告：永不静默
def report_finding(env: Env, cfg: dict, st: dict, f: dict, act: dict, now: float) -> None:
    rep = st.setdefault("reported", {})
    r = rep.get(f["key"]) or {}
    breaker = act.get("action") == "breaker"
    if r.get("at") and now - r["at"] < cfg["report_repeat_h"] * HOUR and (r.get("breaker") or not breaker):
        return
    what = f["what"] + (f"；自动修复已熔断（1 小时内 {act.get('tries_1h')} 次仍没好），需人处理" if breaker else "")
    hint = f["fix_hint"] + ("" if applies(cfg, f) or not f.get("remedy") else "（health_tick.apply=false：只报不修）")
    issue = None
    try:
        issue = env.report(f.get("run") or "-", f"自愈:{f['check']}", ("【熔断】" if breaker else "") + what, hint, bool(f["blocking"] or breaker))
    except Exception as e:  # noqa: BLE001  登记失败（V2_LIVE 坏字节等）不拖垮，落 unreported.jsonl
        try:
            p = env.root / "data/master/health/unreported.jsonl"
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": now, "key": f["key"], "what": what, "error": repr(e)[:200]}, ensure_ascii=False) + "\n")
        except OSError:   # arch-ok: 最后一道也写不了：只剩 CHANNEL 行
            pass
    try:
        env.channel("ERROR" if breaker else "NOTE", f"[{f['key']}] {what}（动作：{act.get('action')}；卡点 {issue or '登记失败'}）", now)
    except OSError:   # arch-ok: CHANNEL 写不了 = 状态文件里仍有记录
        pass
    rep[f["key"]] = {"at": now, "issue": issue, "breaker": breaker}


def tick(env: Env | None = None, cfg: dict | None = None, state: dict | None = None, save: bool = True) -> dict:
    """一拍。返回 {at, apply, findings, actions, resolved, check_errors}。某项检查自己出错 = 记下来并当 finding 报，不中断别的检查"""
    env = env or Env()
    cfg = cfg or load_cfg(env.root / "config/master/health_tick.json")
    st = state if state is not None else (_j(env.root / "data/master/health/state.json", {}) or {})
    now = env.now()
    procs = env.procs()
    out = {"at": now, "apply": bool(cfg.get("apply")), "findings": [], "actions": {}, "resolved": [], "check_errors": {}}
    all_f: list[dict] = []
    for name, fn in CHECKS.items():
        if not cfg["checks"].get(name, True):
            continue
        if name in ("laptop_procs", "tunnels", "deploy_stale") and not procs:
            out["check_errors"][name] = "进程列表读不出：本拍不判进程类"
            continue
        try:
            all_f += fn(env, cfg, st, now, procs)
        except Exception as e:  # noqa: BLE001
            out["check_errors"][name] = repr(e)[:200]
            all_f.append(F(f"check_error:{name}", "self", f"健康检查 {name} 自己出错：{repr(e)[:160]}", "修 tools/master/health_tick.py", None))
    seen = {f["key"] for f in all_f}
    cnt = st.setdefault("consec", {})
    for k in list(cnt):
        if k in seen:
            continue
        cnt.pop(k)
        if k in (st.get("reported") or {}):
            out["resolved"].append(k)
            st["reported"].pop(k, None)
            (st.get("remedy") or {}).get(k, {}).pop("streak", None)
            try:
                env.channel("NOTE", f"[{k}] 已恢复", now)
            except OSError:   # arch-ok
                pass
    for f in all_f:
        k = f["key"]
        cnt[k] = cnt.get(k, 0) + 1
        out["findings"].append({"key": k, "check": f["check"], "what": f["what"], "consec": cnt[k]})
        if cnt[k] < int(cfg["confirm_ticks"]):
            continue                                   # 单拍抖动不动手
        act = apply_remedy(env, cfg, st, f, now, procs)
        out["actions"][k] = act
        report_finding(env, cfg, st, f, act, now)
    if save:
        try:
            env.write_json("data/master/health/state.json", st)
            env.write_json("data/master/health/health.json",
                           {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": now, "pid": os.getpid(), "apply": out["apply"], "findings": out["findings"],
                            "actions": {k: v.get("action") for k, v in out["actions"].items()}, "check_errors": out["check_errors"]})
        except OSError:   # arch-ok: 写不了状态 = 下拍再来
            pass
    return out


def thread_loop(every_s: float | None = None, stop=None, log=None, tick_fn=None, sleep=time.sleep) -> None:
    """autoflow_resident 里的守护线程：每 every_s（默认 config.every_s，≤60）秒一拍；任何异常记下继续，永不退出"""
    tick_fn = tick_fn or tick
    while not (stop and stop.is_set()):
        t0 = time.time()
        try:
            r = tick_fn()
            if log and (r.get("findings") or r.get("resolved")):
                log(f"health_tick：{len(r['findings'])} 项异常 {sorted(r['actions'])}，恢复 {r['resolved']}")
        except Exception as e:  # noqa: BLE001
            if log:
                log(f"health_tick 一拍异常（已继续）：{e!r}")
        every = min(60.0, float(every_s or load_cfg().get("every_s") or 45))
        sleep(max(5.0, every - (time.time() - t0)))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="SELF-HEAL 健康一拍")
    ap.add_argument("cmd", choices=["once", "status"])
    ap.add_argument("--apply", action="store_true", help="本次强制 apply（覆盖配置）")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(json.dumps(_j(ROOT / "data/master/health/health.json", {}), ensure_ascii=False, indent=1))
        return 0
    cfg = load_cfg()
    if a.apply:
        cfg["apply"] = True
    print(json.dumps(tick(cfg=cfg), ensure_ascii=False, indent=1, default=str))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
