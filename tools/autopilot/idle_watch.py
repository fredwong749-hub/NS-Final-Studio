"""空卡巡检（L-202 ②，项目方 11-06 08:0x：“依然 gpu 没有全开，我说过很多遍 gpu 资源不能空闲”；11-06 早上六卡空了 1 h+ 而活还在）。

每拍（config/pipeline/idle_watch.json interval_s，默认 60 s）：
  探测  每台服务器一次远程探针（经 tools/netfix/rssh 复用主连接，python3 - 读 nvidia-smi / 本机 ComfyUI 队列 / producer 心跳 + control.json /
        night_control.json / night_state.json / state_<host>.json 可派镜）+ 笔记本隧道 /queue（hosts.json tunnel_port）。
        道 = config/factory/hosts.json 启用的出图道（gpu33:0/1/3 + gpu36:0/1/2）；gpu33:2 坏卡永远不在表里（NEVER_LANES 双保险）。
  判定  idle = util < util_idle_pct 且队列 running+pending == 0（探不到 = 不判，不凭空报）；
        有活 = 登记表 data/producer/runs/<run>/registry.json 有 ready 首尾帧（按镜判，L-202 ①）/ 该台有可派视频镜 / 资产作业 pending。
        L-206 工位分卡（config/pipeline/lane_roles.json，tools/autopilot/lane_roles_producer.py）：归它管的集按该集阶段给每条道定角色——
        image 道只对 ready 首尾帧 / 资产作业算有活；video 道（首尾帧阶段的 gpu36:2）只对本台可派视频算有活；review 道（gpu33:3）
        只在看图分发器 /health queue > 0 时算有活（看图排队空 = 审图卡该空着，不报）。不归它管的集（ep01）= 旧行为。
  动作  某道空闲 ≥ idle_min 分钟且有活：
        a) 卡点：tools/master/report_issue.report（who=IDLE-WATCH，附证据：哪些道空、什么活、为什么没派——暂停 / hold / only / yield_s /
           episode_lock / sop_gate 阻断 / 心跳过期）；同一台 report_repeat_min 内只记一次；CHANNEL 一行。
        O3（FIX-ORCH 11-06）跨机借道：gpu36 的借道空闲 ≥ idle_min 且 gpu33 分区有 ready 首尾帧 → 改 lane_relay 阶段交接开关
           （data/pipeline/lane_relay_hold.json）把这几条道借给 gpu33；gpu33 分区没 ready 了 → 还原借之前的 hold（relay_plan）。
        b) 现成的安全动作（每项可关）：该台 night.py --once 重派（和 episode_checklist lane_idle 同一条命令；act_gap_s 一次）；
           过期 hold 点名（hold_expiry.alive；读方已自动忽略，这里只让人看见，不改文件）；producer / night 心跳过期 →
           restart_queue.request（urgent，restart_gap_s = 30 分钟一台一次；已有待办请求不重复）。
           producer 心跳新鲜时不另起 producer once（它每 20 s 自己 tick；并行 once 会和常驻 serve 争同一份登记表）。
        从不：杀进程、碰 gpu33:2、nvidia-smi -pl、删文件。
  落盘  data/pipeline/idle_watch/events.log 一拍一行 + 动作各一行；status.json（每道 util / 队列 / 空闲分钟 / 最近动作）给网页和报告用。
常驻：autoflow_resident.idle_watch_start 起守护线程跑 thread_loop（线程永不退出；resident 挂了由 resident_guard 拉起）；
也可独立跑 `idle_watch.py loop`（单实例锁 data/pipeline/idle_watch/lock.json，两份只有一份动手）。
用法：
  .venv/Scripts/python.exe tools/autopilot/idle_watch.py once [--dry-run]   # 一拍（--dry-run 只打印决定不动手）
  .venv/Scripts/python.exe tools/autopilot/idle_watch.py loop
  .venv/Scripts/python.exe tools/autopilot/idle_watch.py status
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG_PATH = ROOT / "config/pipeline/idle_watch.json"
OUT_REL = "data/pipeline/idle_watch"
WHO = "IDLE-WATCH"
NEVER_LANES = ("gpu33:2",)          # 坏卡（CLAUDE.md 红线）：无论 hosts.json 怎么写都不探、不派、不出现在任何命令里
SERVERS = ("gpu33", "gpu36")
VIDEO_INACTIVE = ("done", "best_effort", "blocked", "waiting_frame")

DEFAULT_CFG = {
    "enabled": True, "interval_s": 60, "idle_min": 5, "util_idle_pct": 5, "dry_run": False, "act_gap_s": 600, "restart_gap_s": 1800,
    "report_repeat_min": 60, "issue_blocking": False, "producer_stale_min": 5, "night_stale_min": 10, "probe_timeout_s": 40,
    "queue_timeout_s": 6, "night_once_timeout_s": 180,
    "actions": {"night_once": True, "restart_request": True, "report_issue": True, "channel": True, "lane_relay": True},
}
RELAY_HOLD_REL = "data/pipeline/lane_relay_hold.json"     # lane_relay.HOLD_FILE 同一个文件（producer 每轮现读）

# 服务器侧探针（只读；__RUN__ / __LANES__ / __HOST__ / __PD__ 由 Env.probe_host 填）
REMOTE_PROBE = r"""
import json, os, subprocess, time, urllib.request
LANES = json.loads('__LANES__'); RUN = "__RUN__"; HOST = "__HOST__"; PD = "__PD__"
out = {"now": time.time(), "gpus": {}, "queues": {}}
try:
    for ln in subprocess.run(["nvidia-smi", "--query-gpu=index,utilization.gpu,memory.used", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=20).stdout.splitlines():
        i, u, m = [x.strip() for x in ln.split(",")]
        out["gpus"][i] = {"util": int(u), "mem": int(m)}
except Exception as e:
    out["gpus_error"] = repr(e)[:120]
for g, port in LANES.items():
    try:
        q = json.loads(urllib.request.urlopen("http://127.0.0.1:%d/queue" % int(port), timeout=5).read())
        out["queues"][g] = len(q.get("queue_running") or []) + len(q.get("queue_pending") or [])
    except Exception:
        out["queues"][g] = None
def J(p):
    try:
        return json.load(open(p, encoding="utf-8"))
    except Exception:
        return None
out["hb"] = J(PD + "/heartbeat.json")
out["ctrl"] = J(PD + "/control.json") or {}
V = "data/pipeline/runs/" + RUN + "/video/"
out["nctrl"] = J(V + "night_control.json") or {}
try:
    out["night_state_age_s"] = time.time() - os.stat(V + "night_state.json").st_mtime
except OSError:
    out["night_state_age_s"] = None
st = J(V + "state_" + HOST + ".json") or {}
jobs = J(V + "jobs.json") or {}
pol = (J("config/pipeline/video_policy.json") or {}).get("pika_only") or {}
allowed = set(pol.get("allowed") or [])
readyv = set()
for m in jobs.get("shots") or []:
    for v in (m.get("variants") or {}).values():
        if str(v.get("status")) in ("ready", "lint_error") and (not allowed or v.get("recipe") in allowed):
            readyv.add(m.get("shot"))
disp = [sid for sid, r in (st.get("shots") or {}).items() if r.get("status") not in ("done", "best_effort", "blocked", "waiting_frame") and sid in readyv and not r.get("orphan")]   # W-SCHED 11-06：被别台领走的孤儿记录（status 停在 pending）不是本机的活
out["video_dispatchable"] = sorted(disp)[:40]
out["video_dispatchable_n"] = len(disp)
try:                                       # L-206 审图位：本机看图分发器 /health（queue = 在审的张数；空 = 审图卡没活，不算“空卡有活”）
    h = json.loads(urllib.request.urlopen("http://127.0.0.1:__VQA_PORT__/health", timeout=3).read())
    out["vqa"] = {"queue": h.get("queue"), "loaded": h.get("loaded"), "instances": h.get("instances")}
except Exception:
    out["vqa"] = None
print(json.dumps(out))
"""


def _j(p, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):   # arch-ok: 读不出 = 用默认；调用方按“探不到 = 不判”处理
        return default


def _jw(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def _load(name: str, rel: str, root: Path = ROOT):
    src = Path(root) / rel if (Path(root) / rel).is_file() else ROOT / rel
    sp = importlib.util.spec_from_file_location(name, src)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def load_cfg(path: Path = CFG_PATH) -> dict:
    d = _j(path, {}) or {}
    out = {**DEFAULT_CFG, **{k: v for k, v in d.items() if not k.startswith("_")}}
    out["actions"] = {**DEFAULT_CFG["actions"], **(d.get("actions") or {})}
    return out


def jst(now: float, fmt: str = "%m-%d %H:%M") -> str:
    return time.strftime(fmt, time.gmtime(now + 9 * 3600))


def lane_table(hosts_mod=None, d: dict | None = None) -> dict:
    """{lane: {host, gpu, comfy_port, tunnel_port}}：hosts.json 启用的出图道，去掉 broken_gpus 与 NEVER_LANES（双保险）"""
    H = hosts_mod or _load("hosts_for_idle_watch", "tools/factory/hosts.py")
    d = d or H.load()
    out = {}
    for host in SERVERS:
        broken = {int(x) for x in ((d.get("hosts") or {}).get(host) or {}).get("broken_gpus") or []}
        for lane, rec in H.lanes(host, role="image", d=d).items():
            if lane in NEVER_LANES or int(rec.get("gpu", -1)) in broken:
                continue
            out[lane] = {"host": host, "gpu": int(rec["gpu"]), "comfy_port": int(rec["comfy_port"]), "tunnel_port": rec.get("tunnel_port")}
    assert not any(ln in NEVER_LANES for ln in out)
    return out


# ------------------------------------------------------------------ 环境（真机实现；测试全部覆盖，不碰网络）
class Env:
    def __init__(self, root: Path = ROOT):
        self.root = Path(root)
        self._hosts = None

    def now(self) -> float:
        return time.time()

    def j(self, rel, default=None):
        return _j(self.root / rel, default)

    def hosts(self):
        if self._hosts is None:
            self._hosts = _load("hosts_for_idle_watch", "tools/factory/hosts.py", self.root)
        return self._hosts

    def lanes(self) -> dict:
        return lane_table(self.hosts())

    def primary_run(self) -> str:
        return str((self.j("config/pipeline/runs.json", {}) or {}).get("primary") or "")

    def producer_rel(self, run: str) -> str:
        if str(self.root / "tools/autopilot") not in sys.path:
            sys.path.insert(0, str(self.root / "tools/autopilot"))
        import runs as R
        return R.for_root(self.root).producer_dir(run, self.root).relative_to(self.root).as_posix()

    def _rssh(self):
        return _load("rssh_for_idle_watch", "tools/netfix/rssh.py", self.root)

    def probe_host(self, host: str, run: str, lanes: dict, timeout: float) -> dict | None:
        """服务器侧探针 → dict；连不上 / 解析不了 = None（本拍该台不判）"""
        H = self.hosts()
        ports = {str(v["gpu"]): v["comfy_port"] for v in lanes.values() if v["host"] == host}
        try:
            vqa_port = int(self.lane_roles_mod().review_ports(self.lane_roles_cfg())["router"])
        except Exception:  # noqa: BLE001  # arch-ok: lane_roles 读不到 = 看图分发器默认端口
            vqa_port = 8870
        code = (REMOTE_PROBE.replace("__LANES__", json.dumps(ports)).replace("__RUN__", run).replace("__HOST__", host)
                .replace("__PD__", self.producer_rel(run)).replace("__VQA_PORT__", str(vqa_port)))
        cmd = f"cd {H.server_root(host)} && python3 -"
        try:
            r = self._rssh().run_retry(host, cmd, input=code.encode("utf-8"), timeout=timeout, tries=1)
            txt = (r.stdout or b"").decode("utf-8", "replace")
            return json.loads([ln for ln in txt.splitlines() if ln.startswith("{")][-1])
        except (OSError, ValueError, IndexError, AttributeError):   # arch-ok: 探针失败 = 本拍该台不判（status 里记 probe_error）
            return None

    def tunnel_queue(self, port: int, timeout: float) -> int | None:
        try:
            with urllib.request.urlopen(f"http://127.0.0.1:{int(port)}/queue", timeout=timeout) as r:
                q = json.loads(r.read())
            return len(q.get("queue_running") or []) + len(q.get("queue_pending") or [])
        except (OSError, ValueError):   # arch-ok: 隧道不通 = None，判定退回服务器本机队列
            return None

    def remote(self, host: str, cmd: str, timeout: float) -> tuple[int, str]:
        r = self._rssh().run_retry(host, cmd, timeout=timeout, tries=1)
        out = (r.stdout or b"").decode("utf-8", "replace") + (r.stderr or b"").decode("utf-8", "replace")
        return int(r.returncode), out[-300:]

    def night_once_cmd(self, host: str, run: str) -> str:
        H = self.hosts()
        root = H.video_root(host)
        return f"cd {root} && OFFLINE_SELF={host} NS_RUN={run} {H.python(host)} {root}/tools/series10_video/night.py --once"

    def _rq(self):
        if str(self.root / "tools/autopilot") not in sys.path:
            sys.path.insert(0, str(self.root / "tools/autopilot"))
        import restart_queue as RQ
        return RQ

    def rq_pending(self, host: str) -> list:
        return self._rq().pending(host)

    def rq_request(self, host: str, reason: str, mode: str, urgent: bool) -> dict:
        return self._rq().request(host, reason, by=WHO, urgent=urgent, mode=mode)

    def asset_pending(self, run: str) -> int:
        AJ = _load("asset_jobs_for_idle_watch", "tools/pipeline/asset_jobs.py", self.root)
        return sum(1 for j in AJ.list_jobs(self.root, run) if j.get("state") in ("pending", "failed") and not j.get("final"))

    def episode_lock(self) -> dict | None:
        return _load("episode_lock_for_idle_watch", "tools/pipeline/episode_lock.py", self.root).active(self.root, self.now())

    def sop_blocks(self, run: str, eps: list[int]) -> dict:
        """{ep: missing[]}：sop_gate 出图阶段的阻断（只读；sop_gate 正在被别人改 → 读不了就空）"""
        out = {}
        try:
            sg = _load("sop_gate_for_idle_watch", "tools/master/sop_gate.py", self.root)
            for ep in eps:
                r = sg.judge(run, int(ep), "出图", None, self.root)
                if not r.get("ok") and r.get("missing"):
                    out[int(ep)] = [str(m)[:80] for m in r["missing"]][:4]
        except Exception as e:  # noqa: BLE001  # arch-ok: 只是证据之一；sop_gate 读不了写进证据，不影响判定
            out["_error"] = repr(e)[:120]
        return out

    # ---- L-206 工位分卡（tools/autopilot/lane_roles_producer.py 唯一读法；配置缺 = 关 = 旧行为）
    def lane_roles_mod(self):
        return _load("lane_roles_for_idle_watch", "tools/autopilot/lane_roles_producer.py", self.root)

    def lane_roles_cfg(self) -> dict:
        return self.lane_roles_mod().load_cfg(self.root)

    # ---- O3 跨机借道（复用 tools/autopilot/lane_relay.py：配置 + 阶段交接开关文件；不新增通道、不做跨机接手）
    def relay_cfg(self) -> dict:
        return _j(self.root / "config/pipeline/lane_relay.json", {}) or {"enabled": False}

    def relay_lanes(self, rcfg: dict) -> list[str]:
        """配置里合格的借道（lane_relay.valid_lanes：非坏卡、image 角色、上游只许回环）"""
        LR = _load("lane_relay_for_idle_watch", "tools/autopilot/lane_relay.py", ROOT)
        return sorted(LR.valid_lanes(rcfg))

    def relay_hold_read(self) -> dict | None:
        return _j(self.root / RELAY_HOLD_REL, None)

    def relay_hold_write(self, d: dict) -> None:
        _jw(self.root / RELAY_HOLD_REL, d)

    def partition_images(self) -> dict:
        p = self.j("data/state/netfix/partition.json", None) or self.j("config/netfix/partition.json", {}) or {}
        return p.get("images") or {}

    def hold_alive(self, expires_at, since) -> tuple[bool, str]:
        return _load("hold_expiry_for_idle_watch", "tools/autopilot/hold_expiry.py", self.root).alive(expires_at, since, self.now())

    def report(self, run: str, what: str, fix_hint: str, blocking: bool) -> str | None:
        ri = _load("report_issue_for_idle_watch", "tools/master/report_issue.py", self.root)
        return ri.report(run=run, episode=0, step="空卡巡检", who=WHO, what=what, blocking=blocking, fix_hint=fix_hint).get("id")

    def channel(self, text: str, now: float) -> None:
        line = f"{jst(now)} | {WHO} | {text}\n"
        fd = os.open(self.root / "docs/master/CHANNEL.md", os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
        try:
            os.write(fd, line.encode("utf-8"))
        finally:
            os.close(fd)

    def log(self, line: str) -> None:
        p = self.root / OUT_REL / "events.log"
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8") as f:
            f.write(line + "\n")

    def write_status(self, d: dict) -> None:
        _jw(self.root / OUT_REL / "status.json", d)

    def read_state(self) -> dict:
        return (self.j(f"{OUT_REL}/status.json", {}) or {}).get("_state") or {}


# ------------------------------------------------------------------ 纯逻辑
def frames_ready(reg: dict) -> dict:
    """登记表 → {ready: n, ready_eps: [...], running_idle_candidates: [{obj, where, since}]}：ready 首尾帧 = 按镜可派（L-202 ①）"""
    ready, eps, running, by_ep = 0, set(), [], {}
    for E in reg.get("episodes") or []:
        for S in E.get("shots") or []:
            for k in ("first", "last"):
                o = (S.get("objects") or {}).get(k) or {}
                if o.get("status") == "ready":
                    ready += 1
                    eps.add(int(E.get("ep") or 0))
                    by_ep[int(E.get("ep") or 0)] = by_ep.get(int(E.get("ep") or 0), 0) + 1
                elif o.get("status") == "running":
                    running.append({"obj": f"{S.get('shot')}/{k}", "where": o.get("where"), "since": o.get("since")})
    return {"ready": ready, "ready_eps": sorted(eps), "running": running, "ready_by_ep": by_ep}


ALL_ROLES = {"image", "video"}          # 旧行为：每条道什么活都算（lane_roles 关 / 集不归它管）


def lane_roles_map(LRO, lr: dict, reg: dict, lanes: dict, adult: set | None = None, active: dict | None = None,
                   prev: dict | None = None) -> dict:
    """L-206：每条道此刻的角色与它能做的首尾帧活 {lane: {roles: set, img_ready: n, legacy: bool, phases: {ep: phase}}}。
    不归 lane_roles 管的集（关 / ep < from_episode / 登记表没集）= 旧行为：每条道 image+video、ready 首尾帧全算；
    归它管的集按该集阶段的三张表：image 道算该集 ready 首尾帧，video 道只算视频活，review 道只算看图排队。
    L-207：给了 active（run 级占卡集 {ep, phase}）→ 适用集一律按 active 的阶段取表，ready 首尾帧只算 active 集的
    （下一集的 ready 首尾帧不算“有活”：它按序等 active 集的视频全定下）；prev = 状态文件本剧记录（C2 时间兜底同口径）"""
    out = {ln: {"roles": set(), "img_ready": 0, "legacy": False, "phases": {}} for ln in lanes}
    eps = reg.get("episodes") or []
    if not eps:
        for r in out.values():
            r["roles"], r["legacy"] = set(ALL_ROLES), True
        return out
    for E in eps:
        try:
            ep = int(E.get("ep") or 0)
        except (TypeError, ValueError):
            continue
        n_ready = sum(1 for S in E.get("shots") or [] for k in ("first", "last")
                      if ((S.get("objects") or {}).get(k) or {}).get("status") == "ready")
        if not LRO.applies(lr, ep):
            for r in out.values():
                r["roles"] |= ALL_ROLES
                r["img_ready"] += n_ready
                r["legacy"] = True
            continue
        rec = (prev or {}).get(str(ep)) if isinstance(prev, dict) else None
        try:
            ph = LRO.episode_phase(E, adult, rec)
        except TypeError:   # arch-ok: 旧版分卡模块没有 prev 参数
            ph = LRO.episode_phase(E, adult)
        if active:
            if int(active["ep"]) != ep:
                n_ready = 0            # L-207：不是占卡集 → 它的 ready 首尾帧此刻不算活
            ph = active["phase"]
        for role in LRO.ROLES:
            for ln in LRO.lanes_for(lr, ph, role):
                if ln in out:
                    out[ln]["roles"].add(role)
                    out[ln]["phases"][ep] = ph
                    if role == "image":
                        out[ln]["img_ready"] += n_ready
    return out


def lane_work(rec: dict, host: str, work: dict, probes: dict) -> list[str]:
    """这条道按角色有没有活（人话列表；空 = 没活 → 空着不算“空卡有活”）"""
    out = []
    roles = rec.get("roles") or set()
    if "image" in roles:
        if rec.get("img_ready", 0) > 0:
            out.append(f"ready 首尾帧 {rec['img_ready']}")
        if work.get("assets_pending", 0) > 0:
            out.append(f"资产作业 {work['assets_pending']}")
    if "video" in roles and (work.get("video") or {}).get(host, 0) > 0:
        out.append(f"本台可派视频 {work['video'][host]} 镜")
    if "review" in roles:
        q = ((probes.get(host) or {}).get("vqa") or {}).get("queue")
        if q:
            out.append(f"看图排队 {q}")
    return out


def default_roles(lanes: dict, fr: dict) -> dict:
    return {ln: {"roles": set(ALL_ROLES), "img_ready": fr.get("ready", 0), "legacy": True, "phases": {}} for ln in lanes}


def relay_plan(cfg: dict, st: dict, now: float, lane_st: dict, fr: dict, images: dict, rcfg: dict, relay_lanes: list[str],
               hold: dict | None, roles: dict | None = None) -> dict | None:
    """FIX-ORCH O3（L-202 ②“GPU 不能空闲”）：跨机借道的自动开 / 还，复用 lane_relay 的阶段交接开关文件（producer 每轮现读）。
      借：借道配置开着、消费机（consumer_host，gpu33）分区里有 ready 首尾帧、某条借道（gpu36:x）空闲 ≥ idle_min → 从 hold 里拿掉这条道；
      还：消费机分区没有 ready 了 → 把本巡检借出去的道放回 hold（恢复借之前的 hold，人工 hold 原样还原）。
    只动开关文件，不起 / 停进程，不碰 gpu33:2（valid_lanes 已排除），不做跨机接手（work_stealing=false 照旧）。→ 动作 dict 或 None"""
    if not cfg["actions"].get("lane_relay") or not rcfg.get("enabled") or not relay_lanes:
        return None
    cons = str(rcfg.get("consumer_host") or "")
    cons_eps = {int(e) for e in images.get(cons) or []}
    backlog = sum(n for e, n in (fr.get("ready_by_ep") or {}).items() if int(e) in cons_eps)
    rs = st.setdefault("relay", {})
    lent = [ln for ln in rs.get("lent") or [] if ln in relay_lanes]
    h = (hold or {}).get("hold") if isinstance(hold, dict) else None
    cur = set(relay_lanes) if h == "all" else ({str(x) for x in h if str(x) in relay_lanes} if isinstance(h, list) else set())
    lender = sorted({ln.split(":", 1)[0] for ln in relay_lanes})
    host = lender[0] if lender else "gpu36"
    if backlog > 0:
        take = sorted(ln for ln in cur if (lane_st.get(ln) or {}).get("idle_min", 0) >= cfg["idle_min"]
                      and (roles is None or "image" in (roles.get(ln) or {}).get("roles", ALL_ROLES)))   # L-206：视频位 / 审图位不借去出图
        if take:
            return {"kind": "lane_relay", "key": "lane_relay", "host": host, "op": "lend", "lanes": take,
                    "hold": sorted(cur - set(take)), "prev_hold": rs.get("prev_hold", h) if lent else h,
                    "why": f"{cons} 分区 ready 首尾帧 {backlog} 个，{take} 空闲 ≥ {cfg['idle_min']} 分钟 → 借给 {cons}（lane_relay）"}
        return None
    if lent:
        prev = rs.get("prev_hold")
        back = set(relay_lanes) if prev == "all" else ({str(x) for x in prev if str(x) in relay_lanes} if isinstance(prev, list) else set())
        new = sorted(cur | (set(lent) & back))
        return {"kind": "lane_relay", "key": "lane_relay", "host": host, "op": "return", "lanes": sorted(set(lent) & back),
                "hold": new, "prev_hold": None, "why": f"{cons} 分区没有 ready 首尾帧了 → 借出的道还原 hold（{sorted(set(lent) & back) or '原本就不挡'}）"}
    return None


def blockers(env: Env, probe: dict | None, run: str, lanes_of_host: list[str], cfg: dict) -> list[str]:
    """该台“为什么没派”的证据（人话短句列表）；读不到的项不猜"""
    out = []
    if not probe:
        return ["探针失败：读不到服务器状态"]
    ctrl = probe.get("ctrl") or {}
    if ctrl.get("paused"):
        out.append(f"producer 暂停（{ctrl.get('paused_by')}，{ctrl.get('reason_kind') or ''}）")
    only = ctrl.get("only") or []
    if only == ["__none__"]:
        out.append("control.json only=__none__（本台不分集）")
    hl = [x for x in (ctrl.get("hold_lanes") or []) if x in lanes_of_host]
    if hl:
        out.append(f"control.json hold_lanes {sorted(hl)}（dispatch {((ctrl.get('dispatch_by') or {}).get('at') or '?')} 快照）")
    nc = probe.get("nctrl") or {}
    nh = [x for x in (nc.get("hold_lanes") or []) if x in lanes_of_host]
    if nh:
        exp = nc.get("hold_expires") or {}
        dead = [x for x in nh if not env.hold_alive(exp.get(x) if isinstance(exp, dict) else exp, nc.get("hold_at") or nc.get("at"))[0]]
        out.append(f"night_control hold_lanes {sorted(nh)}" + (f"，其中已过期（读方自动忽略）{sorted(dead)}" if dead else ""))
    if nc.get("yield_s") not in (None, 0, 180):
        out.append(f"night_control yield_s={nc.get('yield_s')}")
    hb = probe.get("hb") or {}
    if hb:
        age = (probe.get("now") or env.now()) - float(hb.get("t") or 0)
        if age > cfg["producer_stale_min"] * 60:
            out.append(f"producer 心跳 {age / 60:.0f} 分钟没更新")
        elif hb.get("paused"):
            out.append("producer 心跳 paused")
    else:
        out.append("producer 没有心跳文件")
    nsa = probe.get("night_state_age_s")
    if nsa is None:
        out.append("night_state.json 不存在")
    elif nsa > cfg["night_stale_min"] * 60:
        out.append(f"night 心跳 {nsa / 60:.0f} 分钟没更新")
    return out


def probe_lanes(env: Env, lanes: dict, probes: dict, cfg: dict) -> dict:
    """每道 {host, util, mem, queue, queue_src, idle: True/False/None}"""
    ports = {ln: v["tunnel_port"] for ln, v in lanes.items() if v.get("tunnel_port")}
    tq = {}
    if ports:
        with ThreadPoolExecutor(max(1, len(ports))) as ex:
            tq = dict(zip(ports, ex.map(lambda p: env.tunnel_queue(p, cfg["queue_timeout_s"]), ports.values())))
    out = {}
    for ln, v in lanes.items():
        pr = probes.get(v["host"]) or {}
        g = (pr.get("gpus") or {}).get(str(v["gpu"])) or {}
        util = g.get("util")
        q, src = tq.get(ln), "tunnel"
        if q is None:
            q, src = (pr.get("queues") or {}).get(str(v["gpu"])), "server"
        idle = None if (util is None or q is None) else (float(util) < cfg["util_idle_pct"] and int(q) == 0)
        out[ln] = {"host": v["host"], "util": util, "mem": g.get("mem"), "queue": q, "queue_src": src if q is not None else None, "idle": idle}
    return out


def decide(env: Env, cfg: dict, st: dict, now: float, lanes: dict, lane_st: dict, work: dict, probes: dict, run: str,
           roles: dict | None = None) -> list[dict]:
    """→ 动作列表（kind: night_once / restart_request / report）；st 持久（idle_since / last_act / reported），由调用方落盘。
    roles（L-206，lane_roles_map）：每条道只按自己的角色判“有活”——审图位看图排队空 = 没活；首尾帧阶段的视频位只看视频活；None = 旧行为"""
    acts = []
    roles = roles or default_roles(lanes, work["frames"])
    lane_has = {ln: lane_work(roles.get(ln) or {"roles": set(ALL_ROLES), "img_ready": work["frames"]["ready"]}, v["host"], work, probes)
                for ln, v in lanes.items()}
    idle_since = st.setdefault("idle_since", {})
    for ln, s in lane_st.items():
        if s["idle"] is True:
            idle_since.setdefault(ln, now)
        else:                       # 忙、或探不到（None）：都不算空闲（失败关闭：不凭空报空卡）
            idle_since.pop(ln, None)
    for ln in [k for k in idle_since if k not in lane_st]:
        idle_since.pop(ln)
    for ln, s in lane_st.items():
        s["idle_min"] = round((now - idle_since[ln]) / 60, 1) if ln in idle_since else 0.0
    has_work = any(lane_has.values())
    if not has_work:
        return acts
    last_act = st.setdefault("last_act", {})
    reported = st.setdefault("reported", {})
    for host in SERVERS:
        mine = [ln for ln, v in lanes.items() if v["host"] == host]
        stuck = [ln for ln in mine if lane_st[ln]["idle_min"] >= cfg["idle_min"] and lane_has[ln]]   # L-206：按角色有活才算“空卡有活”
        if not stuck:
            continue
        pr = probes.get(host)
        why = blockers(env, pr, run, mine, cfg)
        role_txt = "" if all((roles.get(x) or {}).get("legacy") for x in stuck) else \
            "；工位（L-206）：" + "、".join(f"{x}={'/'.join(sorted((roles.get(x) or {}).get('roles') or [])) or '-'}（{'、'.join(lane_has[x])}）" for x in stuck)
        evid = (f"{host} 道 {stuck} 空闲 {max(lane_st[x]['idle_min'] for x in stuck):.0f} 分钟（全台空：{len(stuck) == len(mine)}）；"
                f"活：ready 首尾帧 {work['frames']['ready']}（ep {work['frames']['ready_eps']}）/ 本台可派视频 {work['video'].get(host, 0)} 镜 / "
                f"资产作业 {work['assets_pending']}{role_txt}；原因线索：{'；'.join(why) or '没探到明确阻断（看 producer 日志 / sop_gate）'}")
        stuck_video = any("video" in ((roles.get(x) or {}).get("roles") or ALL_ROLES) for x in stuck)
        if work.get("sop"):
            evid += f"；sop_gate 出图阻断 {work['sop']}"
        if work.get("episode_lock"):
            el = work["episode_lock"]
            evid += f"；episode_lock {el.get('run')} ep{el.get('ep')} by {el.get('by')}"
        hb = (pr or {}).get("hb") or {}
        hb_age = ((pr or {}).get("now") or now) - float(hb.get("t") or 0) if pr else None
        # a) 心跳过期 → restart_queue（30 分钟一台一次；已有待办不重复）
        if pr and cfg["actions"].get("restart_request"):
            mode = None
            if (not hb or hb_age > cfg["producer_stale_min"] * 60) and not hb.get("paused") and (pr.get("ctrl") or {}).get("paused_by") != "LAPTOP_IMAGES":
                mode = "producer-only"
            nsa = pr.get("night_state_age_s")
            if work["video"].get(host, 0) > 0 and (nsa is None or nsa > cfg["night_stale_min"] * 60):
                mode = "all" if mode else "night-only"
            key = f"restart:{host}"
            if mode and now - float(last_act.get(key) or 0) >= cfg["restart_gap_s"]:
                acts.append({"kind": "restart_request", "key": key, "host": host, "mode": mode, "urgent": True,
                             "why": f"{host} 心跳过期（producer {hb_age / 60 if hb_age is not None else '?'} min / night {nsa}）且道空有活"})
        # b) 该台有可派视频且 night 心跳新鲜 → night --once 重派（act_gap_s 一次）
        key = f"night_once:{host}"
        if (pr and cfg["actions"].get("night_once") and work["video"].get(host, 0) > 0 and stuck_video
                and (pr.get("night_state_age_s") or 0) <= cfg["night_stale_min"] * 60
                and now - float(last_act.get(key) or 0) >= cfg["act_gap_s"]):
            acts.append({"kind": "night_once", "key": key, "host": host, "why": f"{host} 可派视频 {work['video'][host]} 镜而道空"})
        # c) 卡点 + CHANNEL（report_repeat_min 一台一次）
        key = f"report:{host}"
        if cfg["actions"].get("report_issue") and now - float(reported.get(key) or 0) >= cfg["report_repeat_min"] * 60:
            acts.append({"kind": "report", "key": key, "host": host, "what": evid,
                         "fix_hint": "按清单派活：当前集逐镜 → 下一集 → 资产作业；看 control.json only / hold、night_control hold、sop_gate；"
                                     "心跳过期走 restart_queue（本巡检已自动请求）"})
    return acts


def execute(env: Env, cfg: dict, st: dict, acts: list[dict], now: float, run: str, dry: bool) -> list[dict]:
    done = []
    last_act, reported = st.setdefault("last_act", {}), st.setdefault("reported", {})
    for a in acts:
        rec = {**a, "at": jst(now, "%Y-%m-%d %H:%M:%S"), "dry": dry}
        if a.get("host") not in SERVERS or any(x in json.dumps(a, ensure_ascii=False) for x in NEVER_LANES):
            rec["result"] = f"拒绝：动作涉及不许碰的机器 / 道 {NEVER_LANES}"     # 双保险：坏卡永远不进任何命令
            done.append(rec)
            continue
        try:
            if dry:
                rec["result"] = "dry-run（没动手）"
            elif a["kind"] == "night_once":
                rc, tail = env.remote(a["host"], env.night_once_cmd(a["host"], run), cfg["night_once_timeout_s"])
                rec["result"] = f"rc={rc} {tail[-120:].strip()}"
                last_act[a["key"]] = now
            elif a["kind"] == "restart_request":
                if env.rq_pending(a["host"]):
                    rec["result"] = "已有待办重启请求，不重复"
                else:
                    rec["result"] = "request " + str(env.rq_request(a["host"], f"{WHO}：{a['why']}"[:200], a["mode"], bool(a.get("urgent"))).get("id"))
                last_act[a["key"]] = now
            elif a["kind"] == "lane_relay":
                rs = st.setdefault("relay", {})
                env.relay_hold_write({"hold": a["hold"], "by": WHO, "at": jst(now, "%Y-%m-%dT%H:%M:%S+09:00"), "why": a["why"][:200]})
                if a["op"] == "lend":
                    rs.update(lent=sorted(set(rs.get("lent") or []) | set(a["lanes"])), prev_hold=a.get("prev_hold"), at=now)
                else:
                    rs.update(lent=[], prev_hold=None, at=now)
                rec["result"] = f"lane_relay_hold → {a['hold']}"
                if cfg["actions"].get("channel"):
                    env.channel(f"🟢 借道 {a['op']} {a['lanes']}：{a['why'][:200]}", now)
            elif a["kind"] == "report":
                iid = env.report(run, a["what"][:900], a["fix_hint"], bool(cfg["issue_blocking"])) if cfg["actions"].get("report_issue") else None
                rec["result"] = f"卡点 {iid}"
                if cfg["actions"].get("channel"):
                    env.channel(f"🔴 空卡有活 {a['what'][:400]}（卡点 {iid}）", now)
                reported[a["key"]] = now
        except Exception as e:  # noqa: BLE001  一个动作失败只记，不影响其它动作 / 下一拍
            rec["result"] = f"失败 {e!r}"[:200]
        done.append(rec)
    return done


def tick(env: Env | None = None, cfg: dict | None = None, state: dict | None = None, dry: bool | None = None, save: bool = True) -> dict:
    """一拍。返回 {at, run, lanes, work, actions, probe_errors}；save=True 写 status.json + events.log"""
    env = env or Env()
    cfg = cfg or load_cfg()
    dry = bool(cfg.get("dry_run")) if dry is None else bool(dry)
    now = env.now()
    st = state if state is not None else env.read_state()
    run = env.primary_run()
    lanes = env.lanes()
    with ThreadPoolExecutor(len(SERVERS)) as ex:
        probes = dict(zip(SERVERS, ex.map(lambda h: env.probe_host(h, run, lanes, cfg["probe_timeout_s"]), SERVERS)))
    lane_st = probe_lanes(env, lanes, probes, cfg)
    reg = env.j(f"{env.producer_rel(run)}/registry.json", {}) or {}
    fr = frames_ready(reg)
    work = {"frames": fr, "video": {h: int((probes.get(h) or {}).get("video_dispatchable_n") or 0) for h in SERVERS},
            "assets_pending": 0, "sop": {}, "episode_lock": None}
    try:
        work["assets_pending"] = env.asset_pending(run)
    except Exception as e:  # noqa: BLE001  # arch-ok: 资产作业读不了只记，不影响首尾帧 / 视频的判定
        work["assets_error"] = repr(e)[:120]
    try:
        work["episode_lock"] = env.episode_lock()
    except Exception as e:  # noqa: BLE001  # arch-ok: 同上，证据项
        work["episode_lock_error"] = repr(e)[:120]
    if fr["ready_eps"]:
        work["sop"] = env.sop_blocks(run, fr["ready_eps"][:3])
    roles, lr_info = None, {"enabled": False}
    try:                                   # L-206：每条道按角色判活（配置缺 / 读不了 = 旧行为）
        LRO = env.lane_roles_mod()
        lr = env.lane_roles_cfg()
        active = LRO.read_active(run, env.root) if hasattr(LRO, "read_active") else None     # L-207：run 级占卡集（producer 写）
        prev = (LRO.read_state(env.root).get(str(run)) or {}) if hasattr(LRO, "read_state") else None
        roles = lane_roles_map(LRO, lr, reg, lanes, active=active, prev=prev)
        lr_info = {"enabled": LRO.enabled(lr), "from_episode": LRO.from_episode(lr), "active": active,
                   "phases": {str(e): r["phases"].get(e) for r in roles.values() for e in r.get("phases") or {}}}
    except Exception as e:  # noqa: BLE001  # arch-ok: 分卡读不了只记，判定退回旧行为
        work["lane_roles_error"] = repr(e)[:120]
        roles = None
    acts = decide(env, cfg, st, now, lanes, lane_st, work, probes, run, roles=roles)
    try:                                   # O3：跨机借道自动开 / 还（读不到配置 = 不动）
        rcfg = env.relay_cfg()
        if rcfg.get("enabled"):
            ra = relay_plan(cfg, st, now, lane_st, fr, env.partition_images(), rcfg, env.relay_lanes(rcfg), env.relay_hold_read(), roles=roles)
            if ra:
                acts.append(ra)
    except Exception as e:  # noqa: BLE001  # arch-ok: 借道判定出错只记，不影响别的动作
        work["relay_error"] = repr(e)[:120]
    done = execute(env, cfg, st, acts, now, run, dry)
    idle_lanes = sorted(ln for ln, s in lane_st.items() if s["idle"])
    rl = roles or default_roles(lanes, fr)
    has_work = any(lane_work(rl.get(ln) or {}, v["host"], work, probes) for ln, v in lanes.items())
    res = {"at": jst(now, "%Y-%m-%d %H:%M:%S+09:00"), "t": now, "run": run, "dry_run": dry, "has_work": has_work, "lanes": lane_st,
           "lane_roles": {**lr_info, "lanes": {ln: {"roles": sorted(r.get("roles") or []), "img_ready": r.get("img_ready", 0),
                                                   "work": lane_work(r, lanes[ln]["host"], work, probes)} for ln, r in rl.items()}},
           "work": {k: v for k, v in work.items() if k != "sop" or v}, "idle_lanes": idle_lanes,
           "probe_errors": [h for h in SERVERS if probes.get(h) is None], "actions": done,
           "_state": {"idle_since": st.get("idle_since", {}), "last_act": st.get("last_act", {}), "reported": st.get("reported", {}),
                      "relay": st.get("relay", {})}}
    if save:
        env.write_status(res)
        env.log(f"{res['at']} idle={idle_lanes} work=ready{fr['ready']}/video{work['video']}/assets{work['assets_pending']} "
                f"probe_err={res['probe_errors']} acts={[a['kind'] + ':' + a['host'] for a in done]}" + (" DRY" if dry else ""))
        for a in done:
            env.log(f"{res['at']} ACT {a['kind']} {a['host']} {a.get('why') or a.get('what', '')[:160]} -> {a.get('result')}")
    return res


# ------------------------------------------------------------------ 常驻
def thread_loop(every_s: float | None = None, stop=None, log=None, tick_fn=None, sleep=time.sleep, cfg_fn=load_cfg) -> None:
    """autoflow_resident 里的守护线程：每 interval_s 一拍；enabled=false 时只睡不探；任何异常记下继续，永不退出"""
    tick_fn = tick_fn or tick
    while not (stop and stop.is_set()):
        t0 = time.time()
        cfg = cfg_fn()
        try:
            if cfg.get("enabled"):
                r = tick_fn(cfg=cfg)
                if log and r.get("actions"):
                    log(f"idle_watch：{[a['kind'] + ':' + a['host'] for a in r['actions']]}")
        except Exception as e:  # noqa: BLE001
            if log:
                log(f"idle_watch 一拍异常（已继续）：{e!r}")
        every = max(20.0, float(every_s or cfg.get("interval_s") or 60))
        sleep(max(5.0, every - (time.time() - t0)))


def main(argv=None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description="空卡巡检（L-202 ②）")
    ap.add_argument("cmd", choices=["once", "loop", "status"])
    ap.add_argument("--dry-run", action="store_true", help="只打印决定不动手（不登记卡点、不发命令）")
    a = ap.parse_args(argv)
    if a.cmd == "status":
        print(json.dumps(_j(ROOT / OUT_REL / "status.json", {}), ensure_ascii=False, indent=1))
        return 0
    if a.cmd == "once":
        r = tick(dry=a.dry_run or None)
        print(json.dumps({k: v for k, v in r.items() if k != "_state"}, ensure_ascii=False, indent=1))
        return 0
    thread_loop(log=lambda m: print(time.strftime("%F %T"), m, flush=True))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
