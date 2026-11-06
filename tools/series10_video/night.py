"""VIDEO10 夜间按集推进驱动（笔记本端，项目方 10-31 夜：“按照剧本……把 10 集都做完……每集自查、修、再下一集”）。

每 120 s 一轮：
 1. 资料闸门：一集的每个镜都有“过契约并设为当前”的首帧（build_jobs.passed_frames：takes.json postflight.ok 或
    video/frames_ok.json 的 ASSETMASTER 通知；frames_ok.json 的 "_episodes_done": [n] 也算整集就绪）→ 该集就绪。
    night_control.json 的 "force_eps" 可强制放行（露脸镜走纯 Ref2VA，无人露脸镜没首帧不出）。
 2. 新就绪的集：选主机（两台里“可用道多、排队少”的那台；可用道 = 不在别人手里的道），写 video/hosts.json，
    重新编译 jobs.json（build_jobs，系统编译器），推 jobs + 输入图，control 里加上这一集，编排器没跑就起。
 3. 已派出的集：同步 state；整集每镜都定下（通过 / 尽力 / 等首帧）→ 服务器出 540×960 合成代理 → 拉回 →
    tools/assemble_episode.py（预览模式、剪辑规则 post.edit_rules、旁白 narrator QAg；series10 没有自己的 BGM 时 --no-bgm）
    → data/episodes/series10/epNN_v1.mp4 → episode_report.py 写 docs/series10_video/epNN_review.md 与
    data/review_pages/series10_video/epNN/index.html（不自动打开，交总调度亲审）。
状态：video/night_state.json；日志 video/night.log；对外摘要 docs/series10_video/STATUS.md（总调度看这个）。

    .venv/Scripts/python.exe tools/series10_video/night.py            # 常驻
    .venv/Scripts/python.exe tools/series10_video/night.py --once
    .venv/Scripts/python.exe tools/series10_video/night.py --run series10_v2      # MERGE-VID-O：按剧（不给 = NS_RUN / 当前剧）
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).parent))
import os  # noqa: E402
import run_ctx as RC  # noqa: E402

# MERGE-VID-O（ISS-1103-024206-3737，L-137）：按剧（--run / NS_RUN / 当前剧；没登记 / 没视频政策 → 失败关闭）。
# 子进程（build_jobs / deploy / sync / register_takes / upscale_preview / episode_report / assemble）一律继承 NS_RUN
RUN_ID = RC.resolve()
os.environ["NS_RUN"] = RUN_ID
LEGACY = RC.is_legacy(RUN_ID)
VID_REL = RC.vid_rel(RUN_ID)
VID = ROOT / VID_REL
PIDF = "run/vidgen.pid" if LEGACY else f"run/vidgen_{RUN_ID}.pid"
def _video_root() -> str:
    """PRODMERGE-O 11-03：服务器视频代码根只从 config/factory/hosts.json video_root 取（= 发版部署目录，video10_srv 退役）"""
    import importlib.util as _u
    sp = _u.spec_from_file_location("hosts_video_root", Path(__file__).resolve().parents[2] / "tools" / "factory" / "hosts.py")
    m = _u.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m.video_root()


DEST = _video_root()
PY = str(ROOT / ".venv/Scripts/python.exe")
STATE = VID / "night_state.json"
CTRL = VID / "night_control.json"
LOG = VID / "night.log"
STATUS = ROOT / ("docs/series10_video/STATUS.md" if LEGACY else f"docs/series10_video/{RUN_ID}/STATUS.md")
EPS_OUT = RC.episodes_out(RUN_ID)        # V1 = data/episodes/series10（原样），其它剧 = data/episodes/<剧>
# 道归属（总调度 10-31 夜）：gpu33 三道 = 出图优先（让道模式）；gpu36:0/1 = BAKEOFF（让道模式，可写 hold 文件借用）；gpu36:2 = 视频
DEFAULT_CTRL = {"force_eps": [], "shared_lanes": ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1", "gpu36:2"],
                "hold_lanes": [], "per_lane": 2, "yield_s": 30, "bgm": "auto",   # FIX-VID（L-205 KPI）：让道观察 180→30 s，道空 3 分钟才派太慢
                "poll_s": None}   # SLIM-CDE 11-05 D：轮询间隔（秒）；None = 旧 V1 120 s / V2 默认 15 s（FIX-NIGHT2 #3：45 → 15）


def _host_is_other(host: str) -> bool:
    """FIX-NIGHT2 #7：服务器上（OFFLINE_SELF）目标不是本机 = 另一台。不看 OFFLINE_ALIASES——那只给打分路由（gpu36 上把
    full_score("gpu33") 当本机执行）；night / deploy 若也按别名当本机，gpu36 会把 gpu33 的作业推到自己目录并报 “push gpu33 PUSH_OK”"""
    me = os.environ.get("OFFLINE_SELF")
    return bool(me) and str(host).split("@", 1)[-1] != me


def video_shared(shared, ctrl) -> list:
    """FIX-VID（L-205 KPI）：night_control.json 的 video_lanes = 专用视频道，不受让道（shared_lanes + yield_s）节流"""
    ded = set(ctrl.get("video_lanes") or [])
    return [x for x in shared or [] if x not in ded]


def _LR():
    """L-206 工位分卡模块（config/pipeline/lane_roles.json 唯一来源）；服务器镜像没带 = None → 旧行为"""
    try:
        import lane_roles as LR
        return LR
    except ImportError:   # arch-ok: 没有分卡模块 = 不分卡（旧行为：全部道共享）
        return None


def roles_for_host(host: str, eps_specs: dict, st: dict, rs: dict | None = None) -> dict | None:
    """L-206：本机本轮的工位分卡结论 {"phase", "eps": {集: 阶段}, "lanes": {"video", "hold"}}。
    None = 不适用：关 / 本机没有在出的集 / 本机还有 ep < from_episode 的集在出（ep01 不中途改调度 → 整台旧行为）。
    阶段 = 本机在出的各适用集里只要有一集还在首尾帧阶段就按 frames（只有 gpu36:2 出视频），全部进视频阶段才 videos（5 张视频道）"""
    LR = _LR()
    if LR is None:
        return None
    cfg = LR.load()
    if not cfg.get("enabled"):
        return None
    hosts = jl(VID / "hosts.json", {}) or {}
    ready = {int(e) for e in (rs or {})}
    active = [ep for ep in _eps_on(hosts, host)
              if ep in ready or (st.get("eps", {}).get(str(ep)) or {}).get("status") == "rendering"]
    # W-SCHED 11-06：ep01 的首帧永远在 ready 里 → 以前只要本机 eps 含 1，整台永远“旧行为”（两台 night DISPATCH roles None，
    # ep02 的 L-207 视频段从没生效）。< from_episode 的集只有本机还有没落定的视频时才否决分卡；落定了就不算在出（结论里记 legacy_settled，
    # 阶段 / 视频道变化由 loop_once 的 LANE_ROLES 一行日志记）
    es = RC.episode_state()                     # L-209 S2.2：enforce 下关闭的集不算本机在出（不否决分卡、不占卡）
    cl = es.enforce_closed(RUN_ID, ROOT) if es else set()
    active = [ep for ep in active if ep not in cl]
    legacy = [ep for ep in active if not LR.applies(ep, cfg)]
    if any(legacy_video_open(ep, host) for ep in legacy):
        return None
    active = [ep for ep in active if ep not in legacy]
    if not active:
        return None
    phases = {str(ep): LR.phase_of(RUN_ID, ep, [s.id for s in eps_specs.get(ep) or []], cfg) for ep in active}
    act = LR.active_from_state(RUN_ID) if hasattr(LR, "active_from_state") else None
    if act:
        # L-207：run 级只有一集在占卡（producer 写 _active）——本机视频道按它的阶段取表：videos = 6 张卡全出视频（含 gpu33:3）；
        # 别的集此刻要么已进合成 / 完成（没视频要出），要么还没开首尾帧（不会有 ready 镜），不再按“最保守”取 frames
        phase = act["phase"]
    else:
        phase = "frames" if any(p != "videos" for p in phases.values()) else "videos"
    out = {"phase": phase, "eps": phases, "lanes": LR.control_lanes(host, phase, cfg)}
    if act:
        out["active"] = {"ep": act["ep"], "phase": act["phase"]}
    if legacy:
        out["legacy_settled"] = legacy
    return out


SETTLED_VIDEO = ("done", "best_effort", "blocked")


def legacy_video_open(ep: int, host: str) -> bool:
    """本机这一集还有没落定的视频：jobs.json 归本机、有变体、本机记录没落定的镜，或本机记录（非孤儿）有在出 / 在打分的版本。
    jobs / state 读不到 → True（失败关闭 = 旧行为）。孤儿记录（被别台领走，vidgen repair_orphans 标 orphan）不算"""
    jobs = jl(VID / "jobs.json", None)
    stt = jl(VID / f"state_{host}.json", None)
    if not isinstance(jobs, dict) or not isinstance(stt, dict):
        return True
    try:  # 复审 11-06：坏数据（非 dict 记录 / 缺 shot 键）不抛进主循环，按读不到处理 = 失败关闭
        recs = stt.get("shots") or {}
        for s in jobs.get("shots") or []:
            if s.get("ep") == ep and s.get("host") == host and s.get("variants") \
                    and (recs.get(s["shot"]) or {}).get("status") not in SETTLED_VIDEO:
                return True
        pre = f"ep{int(ep):02d}-"
        return any(sid.startswith(pre) and not r.get("orphan")
                   and any(x.get("state") in ("submitted", "fetched", "scoring") for x in r.get("renders") or [])
                   for sid, r in recs.items())
    except (AttributeError, KeyError, TypeError, ValueError):  # arch-ok: 坏数据 = 旧行为（视作未落定）
        return True


def roles_control(host: str, st: dict, c: dict) -> dict:
    """把工位分卡写进本机 control：video_lanes = 本阶段视频道（专用、不让道，FIX-VID-2 的 video_lanes 键）；
    hold_lanes 并入本机非视频道（出图位 / 审图位不派视频）；shared_lanes 去掉视频道；lane_roles 给 vidgen 做第二道闸。不适用 = 原样"""
    r = (st.get("lane_roles") or {}).get(host)
    if not r:
        return c
    vid = list(r["lanes"]["video"])
    hold = sorted(set(c.get("hold_lanes") or []) | set(r["lanes"]["hold"]))
    vid = [x for x in vid if x not in hold]        # 手工 hold（带到期，K-OPS-I15）/ 借道 hold 仍优先
    c["hold_lanes"] = hold
    c["video_lanes"] = vid
    c["shared_lanes"] = [x for x in c.get("shared_lanes") or [] if x not in vid]
    c["lane_roles"] = {"phase": r["phase"], "eps": r["eps"], "video": vid, "rule": "L-206"}
    return c


def roles_key(st: dict) -> str:
    return json.dumps({h: ((r or {}).get("phase"), sorted((r or {}).get("lanes", {}).get("video") or []))
                       for h, r in sorted((st.get("lane_roles") or {}).items())}, ensure_ascii=False)


def regen_holds_now(eps_specs: dict) -> dict:
    """L-206 hold_regen_downstream：首帧换代中的镜（视频不派）；进就绪签名，变化就重编作业"""
    LR = _LR()
    if LR is None:
        return {}
    try:
        return LR.regen_holds(RUN_ID, [s.id for ss in eps_specs.values() for s in ss])
    except Exception as e:  # noqa: BLE001  # arch-ok: 换代信号读不了 = 不 hold（记日志；build_jobs 同一函数会再算一次）
        log("REGEN_HOLDS_ERR", repr(e)[:160])
        return {}


def log(*a):
    line = time.strftime("%m-%d %H:%M:%S ") + " ".join(str(x) for x in a)
    print(line, flush=True)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return d


def js(p, d):
    Path(p).parent.mkdir(parents=True, exist_ok=True)
    tmp = Path(str(p) + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(p)


_CHILD_PATHS = ("", "services/post", "services/agent", "services/recipes", "services/render_router", "services/api",
                "packages/schema", "packages/qc")


def child_env() -> dict:
    """子进程环境：服务器 venv 没有 pip install -e 本项目（ns_schema / ns_agent / ns_post 导不进）→ 一律把仓库里的包目录
    放进 PYTHONPATH（口径同 tools/ 下各脚本的 sys.path.insert），不依赖安装方式。已有 PYTHONPATH 保留在后面"""
    paths = [str(ROOT / p) if p else str(ROOT) for p in _CHILD_PATHS]
    old = os.environ.get("PYTHONPATH")
    return {**os.environ, "PYTHONUTF8": "1", "PYTHONPATH": os.pathsep.join(paths + ([old] if old else []))}


def heartbeat(step: str) -> None:
    """FIX-NIGHT2（PS-MASTER 17:5x）：night 心跳 VID/night_heartbeat.json——轮开始和每个子步骤（sync / register / trim / build / push）前写。
    以前 resident_sync 只看 night_state.json 的 mtime（一轮结束才写），刚起的第一轮 5–15 min 没心跳 → lifecycle 判死 → 再次重启，自我打败"""
    try:
        VID.mkdir(parents=True, exist_ok=True)
        js(VID / "night_heartbeat.json", {"t": time.time(), "at": time.strftime("%Y-%m-%dT%H:%M:%S"), "step": str(step)[:80],
                                           "pid": os.getpid(), "run": RUN_ID})
    except OSError:   # arch-ok: 心跳写不下不能拦主循环（state 的 mtime 仍是第二路心跳）
        pass


def run(args, timeout=3600):
    heartbeat("run:" + str(args[1] if len(args) > 1 else args[0]).replace("\\", "/").rsplit("/", 1)[-1])
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       cwd=str(ROOT), env=child_env())
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def ssh(host, cmd, timeout=600):
    r = _rssh().run_retry(host, cmd, timeout=timeout, tries=1, text=True)   # 原来不重试：tries=1；返回 stdout + stderr 文本
    return (r.stdout or "") + (r.stderr or "")

def _rssh():
    """K-OPS-N07 / SYSARCH 4-1：远程命令统一走 tools/netfix/rssh.run_retry（笔记本走常驻主连接；服务器上 OFFLINE_SELF 调本机 = 本机执行）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("_rssh_41", Path(__file__).resolve().parents[2] / "tools/netfix/rssh.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod



def lane_load(host) -> dict:
    ports = {"gpu33": [8188, 8189, 8191], "gpu36": [8188, 8189, 8190]}[host]
    cmd = "; ".join(f"printf '{p} '; curl -s -m5 localhost:{p}/queue | python3 -c \"import sys,json;d=json.load(sys.stdin);"
                    f"it=d['queue_running']+d['queue_pending'];m=sum(1 for i in it if str((i[3] or {{}}).get('client_id','')).startswith('video10-'));"
                    f"print(m, len(it)-m)\" 2>/dev/null || echo x x" for p in ports)
    out = {}
    for ln in ssh(host, cmd, 60).splitlines():
        parts = ln.split()
        if len(parts) == 3 and parts[1] != "x":
            out[int(parts[0])] = (int(parts[1]), int(parts[2]))
    return out


def _B():
    import build_jobs as B
    if B.RUN_ID != RUN_ID:
        B.set_run(RUN_ID)
    return B


def specs_by_ep():
    B = _B()
    sp = B.load_specs(source="import")
    eps = {}
    for sid, s in sp.items():
        eps.setdefault(s.episode, []).append(s)
    return eps


def ready_eps(eps_specs, ctrl, pf: dict | None = None) -> list[int]:
    B = _B()
    pf = B.passed_frames() if pf is None else pf     # FIX-NIGHT2 #3：loop_once 算一次传进来
    ok = jl(B.FRAMES_OK, {}) or {}
    done = set(ok.get("_episodes_done") or []) | set(ctrl.get("force_eps") or [])
    for ep in ctrl.get("force_eps") or []:
        led = ROOT / "knowledge/RSI_LEDGER.md"
        mark = f"<!-- VIDEO10 force_eps ep{int(ep):02d} -->"
        if mark not in led.read_text(encoding="utf-8"):
            with open(led, "a", encoding="utf-8") as f:
                f.write(f"\n{mark}\n- VIDEO10 {time.strftime('%Y-%m-%d %H:%M')}：force_eps 强制放行 ep{int(ep):02d}"
                        f"（首帧未全部过契约；night_control.json 设置；没有首帧的无人露脸镜不出）\n")
    return [ep for ep, ss in sorted(eps_specs.items()) if ep in done or all(s.id in pf for s in ss)]


def ready_shots(eps_specs, ctrl, pf: dict | None = None) -> dict[int, list[str]]:
    """→ {集: [首帧已过契约的镜]}（逐镜派单用；force_eps 的集全部镜都算就绪）"""
    B = _B()
    pf = B.passed_frames() if pf is None else pf
    force = set(ctrl.get("force_eps") or [])
    out = {}
    for ep, ss in sorted(eps_specs.items()):
        ids = [s.id for s in ss if s.id in pf or ep in force]
        if ids:
            out[ep] = ids
    return out, {sid: v.get("file") for sid, v in pf.items()}


def pick_host(st) -> str:
    """可用道多、已派镜头少的那台（gpu36:2 视频专用道算 1；让道道只在空闲时算）"""
    score = {}
    for h in _hosts_here():      # A-07：服务器上只管本机（原来 resident_prep 就地改源码）
        busy = ssh(h, f"cd {DEST} 2>/dev/null && [ -f {PIDF} ] && kill -0 $(cat {PIDF}) 2>/dev/null && "
                      f"grep -q validate_jobs {VID_REL}/control_{h}.json && echo VALIDATING", 60)
        if "VALIDATING" in busy:
            continue
        try:
            ll = lane_load(h)
        except Exception:  # noqa: BLE001
            ll = {}
        free = sum(1 for p, (m, f) in ll.items() if f == 0) + (1 if h == "gpu36" else 0)
        pend = sum(n for e, n in st.get("pending_shots", {}).items() if st["eps"].get(e, {}).get("host") == h)
        score[h] = free * 10 - pend
    return max(score, key=score.get) if score else None


def dispatch_hosts(hosts_touched: set, st, ctrl) -> bool:
    """重新编译 jobs.json（只给首帧过契约的镜出变体），推到涉及的主机，更新 control 的集列表，编排器没跑就起"""
    if not ((sys.path.append(str(ROOT)) if str(ROOT) not in sys.path else None) or __import__("tools.master.sop_gate", fromlist=["_"]).video_dispatch_ok(VID_REL, ROOT)): return False  # HARNESS-O：SOP 阶段闸门  # noqa: E701
    rc, out = run([PY, "tools/series10_video/build_jobs.py"], 1800)
    log("build_jobs", rc, out.strip()[-300:].replace("\n", " "))
    if rc:
        return False
    hosts = jl(VID / "hosts.json", {}) or {}
    for host in sorted(hosts_touched):
        # DEBUG-RSI（总调度 FOCUS 第 5 条，11-02 16:1x）：两台各跑一个 night，服务器之间没有 ssh 互信。分给另一台的集推不过去，
        # 以前这里 return False → ready_sig 不更新 → 每轮重推本机 8 MB、另一台那几集永远派不出（ep07 / 09 / 10 视频 31 条卡住）。
        # 现在跳过另一台（它的集由那台自己的 night 派），不算失败。FIX-NIGHT2 #7：按 OFFLINE_SELF 判，不认 OFFLINE_ALIASES
        if _host_is_other(host):
            log("SKIP_OTHER_HOST", host, "服务器之间不推（无互信），这台的集由它自己的 night 派")
            continue
        rc, out = run([PY, "tools/series10_video/deploy.py", "push", host], 3600)
        log("push", host, rc, out.strip()[-200:].replace("\n", " "))
        if rc:
            return False
        eps_on = _eps_on(hosts, host)
        cl = RC.closed_now(RUN_ID)            # L-209 S2.2：enforce 下关闭的集不进编排器 control.eps（vidgen 不再给它出片）
        eps_on = [e for e in eps_on if not (e in cl and RC.closed_skip(RUN_ID, e, f"video:ep{int(e):02d}", "night.control", cl))]
        hold, per_lane, shared = ctrl.get("hold_lanes", []), ctrl["per_lane"], ctrl.get("shared_lanes", [])
        if ctrl.get("ep01_lane") and host == hosts.get("1"):
            hold = [x for x in IMAGE_LANES if x != "gpu33:3"]
            eps_on, per_lane, shared = [1], 1, [x for x in shared if x != "gpu33:3"]
        hold, gate = video_boost(ctrl, hold)
        hold = _shard_hold(host, hold, st)      # L-207：本阶段的视频道不被分片排除表挂住（gpu33:3 视频段出视频）
        c = {"jobs": "jobs.json", "mode": "prod", "eps": eps_on, "per_lane": per_lane, "linger": True,
             "hold_lanes": hold, "shared_lanes": video_shared(shared, ctrl), "yield_s": ctrl["yield_s"]}
        if gate:
            c["vram_gate"] = gate
        roles_control(host, st, c)      # L-206：按阶段分卡（video_lanes / hold_lanes / lane_roles）
        run([PY, "tools/series10_video/deploy.py", "control", host, json.dumps(c, ensure_ascii=False)])
        run([PY, "tools/series10_video/deploy.py", "start", host])
        log("DISPATCH", host, "eps", eps_on, "hold", c["hold_lanes"], "roles", (c.get("lane_roles") or {}).get("phase"), c.get("video_lanes"))
    return True


def dispatch(ep, host, st, ctrl):   # 旧接口（整集派单），保留给手工调用
    hosts = jl(VID / "hosts.json", {}) or {}
    hosts[str(ep)] = host
    js(VID / "hosts.json", hosts)
    rc, out = run([PY, "tools/series10_video/build_jobs.py"], 1800)
    if rc:
        return False
    rc, out = run([PY, "tools/series10_video/deploy.py", "push", host], 3600)
    if rc:
        return False
    eps_on = sorted({int(e) for e, h in hosts.items() if h == host and st["eps"].get(e, {}).get("dispatched")} | {ep})
    c = {"jobs": "jobs.json", "mode": "prod", "eps": eps_on, "per_lane": ctrl["per_lane"], "linger": True,
         "hold_lanes": ctrl.get("hold_lanes", []), "shared_lanes": video_shared(ctrl.get("shared_lanes", []), ctrl), "yield_s": ctrl["yield_s"]}
    run([PY, "tools/series10_video/deploy.py", "control", host, json.dumps(c, ensure_ascii=False)])
    run([PY, "tools/series10_video/deploy.py", "start", host])
    st["eps"][str(ep)] = {"host": host, "dispatched": time.time(), "status": "rendering"}
    log("DISPATCH", f"ep{ep:02d}", "→", host, "eps", eps_on)
    return True


def _VS():
    """视频按镜分片模块（默认关；服务器镜像没带 = None → 全部走原逻辑）"""
    try:
        import video_shard as VS
        return VS
    except ImportError:   # arch-ok: 没有分片模块 = 不分片
        return None


def _shard_cfg(ep) -> dict | None:
    VS = _VS()
    return VS.ep_cfg(RUN_ID, int(ep)) if VS else None


def _eps_on(hosts: dict, host: str) -> list[int]:
    """本机该出的集：按集归属 ∪（开了分片时）分片集里本机是分片台的；分片关 = 原来的 sorted(int(e) for e, h in hosts.items() if h == host)"""
    VS = _VS()
    return VS.eps_on_host(RUN_ID, host, hosts) if VS else sorted(int(e) for e, h in hosts.items() if h == host)


def _eps_on_shard(host: str) -> bool:
    VS = _VS()
    return bool(VS) and any(host in c["hosts"] for c in VS.shard_eps(RUN_ID).values())


def _shard_hold(host: str, hold: list, st: dict | None = None) -> list:
    """分片开着：本机不适合跑 H3 的道（gpu33:3 = 看图 + reserve-vram 9）并进挂道；关 = 原样。
    L-207：lane_roles 本阶段把该道列为视频道（videos 段 gpu33:3 出视频 + 1 个看图实例，ComfyUI --reserve-vram 9 给看图留显存）→ 不挂"""
    VS = _VS()
    ex = VS.exclude_lanes(host) if VS else []
    if ex and st:
        vid = set((((st.get("lane_roles") or {}).get(host) or {}).get("lanes") or {}).get("video") or [])
        ex = [x for x in ex if x not in vid]
    return sorted(set(hold) | set(ex)) if ex and _eps_on_shard(host) else hold


def ep_shots(ep, host) -> dict:
    """这一集的镜状态：没分片 = state_<host>.json 里本集的镜（原行为）；分片 = 各分片台 state 合并（owner 上 helper 的 state 由 shard_relay 送来，只读）"""
    if _shard_cfg(ep):
        VS = _VS()
        return VS.merged_shots(VID, int(ep), VS.ep_hosts(RUN_ID, int(ep), host), jl(VID / "jobs.json", {}) or {})
    stt = jl(VID / f"state_{host}.json", {}) or {}
    return {sid: r for sid, r in (stt.get("shots") or {}).items() if int(sid[2:4]) == int(ep)}


def ep_sig(ep, host) -> str:
    return json.dumps({sid: [r.get("status"), r.get("chosen"), len(r.get("renders") or [])]
                       for sid, r in sorted(ep_shots(ep, host).items())}, ensure_ascii=False)


HOLD_RESOLVE_S = int(os.environ.get("NS_HOLD_RESOLVE_S", "900"))    # MINOR 6（L-205 50 min KPI）：等闸门的镜 45 → 15 min 按落定算


def gate_hold_aged(ep, excl: set, now: float | None = None) -> set:
    """等闸门的镜：记首次看到的时间（VID/_gate_hold_since.json），连续等满 HOLD_RESOLVE_S 的才返回（才可按落定算）"""
    f = VID / "_gate_hold_since.json"
    now = now or time.time()
    d = jl(f, {}) or {}
    key = str(ep)
    cur = {sid: t for sid, t in (d.get(key) or {}).items() if sid in excl}
    for sid in excl:
        cur.setdefault(sid, now)
    if cur != (d.get(key) or {}):
        d[key] = cur
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, f)
    return {sid for sid, t in cur.items() if now - float(t) >= HOLD_RESOLVE_S}


def ep_resolved(ep, host) -> tuple[bool, dict]:
    """整集落定 = jobs 里本集每镜都 done / best_effort / blocked。FIX-VID D10：没过闸门的镜（build_jobs route=hold, gate_excluded）
    按“等闸门”算落定（它出不了，成片用首帧静帧占位；闸门开了 → 重编有变体 → 状态变 → ep_sig 变 → REOPEN 重合成）"""
    shots_st = ep_shots(ep, host)
    jobs = jl(VID / "jobs.json", {}) or {}
    rows = [s for s in jobs.get("shots", []) if s["ep"] == ep]
    ids = [s["shot"] for s in rows]
    excl = {s["shot"] for s in rows if s.get("gate_excluded") and not s.get("variants")}
    # PS-MASTER 11-06 17:0x（ep01 实测）：等首尾帧的镜立刻按“落定”算 → 每来一镜就整集合成一遍预览（finalize 同步阻塞 night 主循环
    # 5–10 min，gpu36 三卡空转）。改：等闸门的镜要连续等满 HOLD_RESOLVE_S（默认 15 min，L-207 前 45 min）才按落定算（真出不来才静帧占位）
    excl = gate_hold_aged(ep, excl)
    recs = {sid: shots_st.get(sid, {}) for sid in ids}
    fin = all(r.get("status") in ("done", "best_effort", "blocked") or sid in excl for sid, r in recs.items()) and ids \
        and any(sid not in excl for sid in ids)   # 整集都没过闸门 = 没开始，不算落定（否则每轮空跑 proxies / sync）
    return bool(fin), recs


def voices_ok() -> bool:
    """总调度 11-01：config/voices.json 还是旧 60 集的 Kokoro 演员表（林晚 = zf_067 等），series10 声音没重做前不合成成片。
    voices.json 顶层 "series" 标成 "series10_v1"（由声音负责方改）后才放行。
    MERGE-VID-O：非 V1 剧按 ns_post.run_media.voice_config(<剧>)（config/voices_v2.json，L-132）——取不到 / sha 不符 → 不合成"""
    if not LEGACY:
        try:
            if str(ROOT / "services" / "post") not in sys.path:
                sys.path.insert(0, str(ROOT / "services" / "post"))
            from ns_post import run_media as RM
            return (RM.voice_config(RUN_ID, ROOT) or {}).get("series") == RUN_ID
        except Exception as e:  # noqa: BLE001  # arch-ok: 音色没登记 = 不合成（hold_voices，失败关闭）
            log("VOICES", RUN_ID, str(e)[:200])
            return False
    v = jl(ROOT / "config/voices.json", {}) or {}
    return v.get("series") == "series10_v1"


def tts_missing() -> str | None:
    """K-OPS-309：合成前检查本机配音解释器（config/voices.json speech_python：环境变量 NS_TTS_PYTHON 或 default 路径）。
    缺 → 返回原因（不合成、不耗版本号，状态 hold_tts，装好后下一轮自动继续）
    VOICE10 11-01（K-EDT-021）：改调 ns_post.tts.tts_preflight，一次查完解释器 + 模型目录 + 每个角色音色 / 参考音频 /
    ref_text / 远端模型；导入失败才退回只查解释器的旧逻辑"""
    import os
    try:
        if str(ROOT / "services" / "post") not in sys.path:
            sys.path.insert(0, str(ROOT / "services" / "post"))
        from ns_post.tts import tts_preflight
        from ns_post import run_media as RM
        # W16 / REVIEW-G4b P0-1：音色表按剧取（C-14；旧写法不传 run → 资产包剧 VoiceRunRequired → 每集永远 hold_tts）
        try:
            cfg = RM.voice_config(RUN_ID, ROOT)
        except (RM.V2MediaError, OSError, ValueError, RuntimeError) as e:  # arch-ok: 音色表读不了 = hold_tts（失败关闭）
            return f"音色表读不了：{e}"
        miss = tts_preflight(cfg, root=ROOT, run=RUN_ID)
        return "；".join(miss) if miss else None
    except ImportError:
        pass
    v = jl(ROOT / "config/voices.json", {}) or {}
    sec = v.get("speech_python") or {}
    cands = [os.environ.get(sec.get("env") or "NS_TTS_PYTHON"), sec.get("default")]
    if any(c and Path(c).exists() for c in cands):
        return None
    return f"没有配音解释器：{sec.get('env') or 'NS_TTS_PYTHON'} 未设，default {sec.get('default')} 不存在"


ASM_RETRY_S, ASM_RETRY_MAX = 1200, 3
# FIX-VID（视频审计 perf）：代码类错误（缺模块 / 语法 / 导入失败）等 20 分钟重试 3 次也不会好 → 不定时重试，当场报告；
# 合成相关代码有变（发版修好了）才再试一次
ASM_FATAL_RE = re.compile(r"ImportError|ModuleNotFoundError|SyntaxError|IndentationError|cannot import name|No module named")
ASM_CODE = ("tools/assemble_episode.py", "services/post/ns_post", "packages/schema/ns_schema", "services/agent/ns_agent")


def asm_code_sig() -> str:
    """合成器相关代码的指纹（各文件 mtime 最大值 + 文件数）；代码类错误后只有它变了才重试"""
    ts, n = 0.0, 0
    for rel in ASM_CODE:
        p = ROOT / rel
        for f in ([p] if p.is_file() else p.glob("*.py") if p.is_dir() else []):
            try:
                ts, n = max(ts, f.stat().st_mtime), n + 1
            except OSError:   # arch-ok: 文件刚被换掉 = 少算一个，指纹下一轮再变
                continue
    return f"{int(ts)}:{n}"


def asm_fatal(err: str | None) -> bool:
    return bool(ASM_FATAL_RE.search(str(err or "")))


def retry_assembly(st) -> None:
    """K-OPS-309：assemble_failed / hold_tts 不是终态。hold_tts：配音解释器到位就回到 rendering；
    assemble_failed：距上次合成 ≥ 20 分钟且自动重试 < 3 次 → 回到 rendering（走同一条 EP_RESOLVED → finalize 流程，
    版本号照常递增）；超过 3 次停在 assemble_failed，交总调度看 assemble_err"""
    for e, x in st["eps"].items():
        s = x.get("status")
        # W46：hold_voices 原来是死胡同（音色资产后到 → 本集永远不合成）；音色到位就回到 rendering
        if s == "hold_voices" and voices_ok():
            x["status"], x["force_finalize"] = "rendering", True
            log("RETRY_ASSEMBLE", f"ep{int(e):02d}", "音色表已到位")
        elif s == "hold_tts" and not tts_missing():
            x["status"], x["force_finalize"] = "rendering", True
            log("RETRY_ASSEMBLE", f"ep{int(e):02d}", "配音解释器已到位")
        elif s == "assemble_failed" and x.get("resolved_sig") and x["resolved_sig"] != ep_sig(int(e), x["host"]):
            # 镜头集合 / 版本变了 = 新输入，值得再试：重置自动重试次数（不论是否已用完）
            x["assemble_retries"] = 0
            x["status"], x["force_finalize"] = "rendering", True
            log("REOPEN", f"ep{int(e):02d}", "合成失败后入选版本 / 镜头集合有变，重置自动重试并重新合成")
        elif s == "assemble_failed" and asm_fatal(x.get("assemble_err")):
            # 代码类错误：不按 20 分钟 × 3 次空等，当场报告（只记一次）；合成代码变了（发版修好）→ 立即再试
            sig = asm_code_sig()
            if x.get("assemble_fatal_sig") is None:
                x["assemble_fatal_sig"] = sig
                log("ASSEMBLE_FATAL", f"ep{int(e):02d}", "代码类错误，不自动重试，等发版修复：", str(x.get("assemble_err") or "")[-200:])
            elif x["assemble_fatal_sig"] != sig:
                x.pop("assemble_fatal_sig", None)
                x["status"], x["force_finalize"] = "rendering", True
                log("RETRY_ASSEMBLE", f"ep{int(e):02d}", "合成相关代码有变，重试代码类错误")
        elif s == "assemble_failed" and int(x.get("assemble_retries", 0)) < ASM_RETRY_MAX \
                and time.time() - float(x.get("finalized") or 0) >= ASM_RETRY_S:
            x["assemble_retries"] = int(x.get("assemble_retries", 0)) + 1
            x["status"], x["force_finalize"] = "rendering", True
            log("RETRY_ASSEMBLE", f"ep{int(e):02d}", f"第 {x['assemble_retries']}/{ASM_RETRY_MAX} 次自动重试",
                str(x.get("assemble_err") or "")[-120:])


REOPEN_MIN_S = int(os.environ.get("NS_REOPEN_MIN_S", "300"))        # FIX-NIGHT2 #2：合成完 ≥ 5 min 才许因版本变化重开
REOPEN_MAX_PER_H = int(os.environ.get("NS_REOPEN_MAX_PER_H", "4"))  # 每集每小时最多重开 N 次（ep01 17:05 两轮各 REOPEN 一次）


def reopen_changed(st, now: float | None = None) -> None:
    """已合成的集，入选版本 / 镜头集合（resolved_sig）变了 → 回 rendering（全部完成则 rendering 分支再起 finalize，版本号递增）。
    FIX-NIGHT2 #2 去抖：距上次合成 < REOPEN_MIN_S 或 1 小时内已重开 ≥ REOPEN_MAX_PER_H 次 → 先不重开（记 reopen_pending，只记一次日志）"""
    now = now or time.time()
    for e, x in st["eps"].items():
        if x.get("status") != "assembled" or not x.get("resolved_sig"):
            continue
        sig = ep_sig(int(e), x["host"])
        if x["resolved_sig"] == sig:
            x.pop("reopen_pending", None)
            continue
        hist = [t for t in x.get("reopen_hist") or [] if now - float(t) < 3600]
        if now - float(x.get("finalized") or 0) < REOPEN_MIN_S or len(hist) >= REOPEN_MAX_PER_H:
            if x.get("reopen_pending") != sig:
                x["reopen_pending"] = sig
                log("REOPEN_DEBOUNCE", f"ep{int(e):02d}", f"版本有变，但距上次合成 {now - float(x.get('finalized') or 0):.0f}s / 1h 内已重开 {len(hist)} 次，先不重开")
            continue
        x["reopen_hist"] = hist + [now]
        x.pop("reopen_pending", None)
        x["status"], x["force_finalize"] = "rendering", True
        log("REOPEN", f"ep{int(e):02d}", "入选版本有变，按新版本号重合成")


def clip_wh(p: Path) -> tuple[int, int]:
    import cv2
    cap = cv2.VideoCapture(str(p))
    try:
        return int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    finally:
        cap.release()


def upscaled_for(src: Path) -> Path | None:
    """原片的放大版（同目录 <名>_sr1080.mp4，tools/series10_video/upscale_preview.py 产出：SeedVR2 或 lanczos+锐化兜底）"""
    p = src.with_name(src.stem + "_sr1080.mp4")
    return p if p.is_file() else None


def jobs_first_frames(ep: int) -> dict:
    """本集 jobs.json 里每镜当前首帧输入（video/inputs/<镜>_<sha8>.jpg）→ {镜: 文件 | None}；镜不在 jobs 里就不出现"""
    jobs = jl(VID / "jobs.json", {}) or {}
    return {s["shot"]: s.get("first_frame") for s in jobs.get("shots", []) if int(s.get("ep") or 0) == int(ep)}


def drop_stale(man: dict, jff: dict) -> list[str]:
    """FIX-VID D10：manifest 里片子首帧 ≠ 当前首帧（jobs.json）的镜去掉代理（不进成片，用静帧占位）。返回去掉的镜。
    manifest 没记 first_frame 的旧条目不判（服务器 vidgen.proxies 已判过一遍，这里是 owner 侧第二道）"""
    out = []
    for s in man.get("shots", []):
        if s.get("proxy") and "first_frame" in s and s["shot"] in jff and (s.get("first_frame") or None) != (jff[s["shot"]] or None):
            s["excluded"] = f"过期片：片子首帧 {s.get('first_frame')} ≠ 当前首帧 {jff[s['shot']]}（D10，不进合成）"
            s["stale"] = True
            s.pop("proxy", None)
            out.append(s["shot"])
    return out


def assembly_sources(man: dict, stills: dict | None = None) -> tuple[dict, list[str]]:
    """K-EDT-V10（项目方 11-01“s5等视频出来很糊”“估计你的参数坏了”）：成片只用原片（manifest.source = video/clips/…，
    768×1344 级）或它的放大版；540×960 代理（manifest.proxy）只给审片页，禁止进成片。
    每条输入的宽高必须 ≥ 原片宽高（放大版必须更大）；不满足的镜列进 bad，整集不合成。
    FIX-VID D8：stills = {镜: 当前首帧文件}——没出片的镜（阻断 / 过期 / 等闸门）给合成器一条 kind=still 的来源，
    合成器用首帧静帧缓推占位（ns_post.assemble PLACEHOLDER_PUSH），不再是黑场；时间线照标 missing，报告列出"""
    shots, bad = [], []
    for s in man.get("shots", []):
        if not s.get("proxy"):
            # 没出片 / 阻断：不进合成（manifest excluded）；尽力版有代理，照进（L-196，VID-LOOP 11-06）
            ff = (stills or {}).get(s.get("shot"))
            if ff and (ROOT / ff).is_file():
                shots.append({"index": s["index"], "kind": "still", "file": str(ff).replace("\\", "/"),
                              "origin": f"VIDEO10 {s['shot']} 首帧静帧占位（{s.get('block_reason') or s.get('excluded') or s.get('status')}）"[:300]})
            continue
        src = ROOT / str(s.get("source") or "")
        if not s.get("source") or not src.is_file():
            bad.append(f"{s['shot']} 原片不在本机（{s.get('source')}）")
            continue
        sw, sh = clip_wh(src)
        use, tag = src, f"原片 {sw}×{sh}"
        dj = src.with_name(src.stem + "_dj.mp4")          # VIDEO-RCA r1：Pika 去抖片（upscale_preview 产出，K-LOOP-004）
        if dj.is_file():
            use, tag = dj, f"去抖版 {sw}×{sh}"
        up = upscaled_for(src)
        if up:
            uw, uh = clip_wh(up)
            if uw >= sw and uh >= sh:
                use, tag = up, f"放大版 {uw}×{uh}（原片 {sw}×{sh}）"
        pw, ph = clip_wh(ROOT / s["proxy"]) if (ROOT / s["proxy"]).is_file() else (0, 0)
        if not sw or (pw and sw * sh <= pw * ph):
            bad.append(f"{s['shot']} 原片分辨率 {sw}×{sh} 不高于代理 {pw}×{ph}")
            continue
        try:   # W46（总调度 05:1x）：进合成前单镜裁到 ≤ 6.0 s（C-08，尾部裁、首帧保留；Pika 79 帧@12 = 6.58 s 的已出片兜底）
            from clip_trim import trim_le
            t6 = trim_le(use)
            if t6 != use:
                use, tag = t6, tag + "，裁到 ≤6 s"
        except (RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            bad.append(f"{s['shot']} 裁到 6 s 失败：{e}"[:200])
            continue
        shots.append({"index": s["index"], "kind": "video", "file": str(use.relative_to(ROOT)).replace("\\", "/"),
                      "origin": f"VIDEO10 {s['shot']} {s.get('chosen')} {s.get('recipe')} seed {s.get('seed')}（{tag}）"})
    return {"shots": shots}, bad


def finalize(ep, host, st, ctrl):
    ver = f"v{int(st['eps'][str(ep)].get('assembled_n', 0)) + 1}"   # 每次重合成递增：已亲审签字的旧版不覆盖
    for k in ("assemble_err", "wait_msg", "hold_why", "assemble_fatal_sig"):   # FIX-VID D12：上一轮的旧错误不带进这一轮（ep01 挂着 11-04 的 ns_schema 报错）
        st["eps"][str(ep)].pop(k, None)
    if not voices_ok():
        st["eps"][str(ep)]["status"] = "hold_voices"
        log("HOLD", f"ep{ep:02d}", "config/voices.json 不是 series10 演员表，暂不合成")
        return
    why = tts_missing()
    if why:   # K-OPS-309：本机没有配音解释器 / 模型（离线时 night.py 跑在服务器副本上，11:11 ep04 TtsUnavailable）→ 等，不耗版本号
        st["eps"][str(ep)].update(status="hold_tts", hold_why=why)
        log("HOLD_TTS", f"ep{ep:02d}", why)
        return
    old_man = jl(VID / "episodes" / f"ep{ep:02d}" / "manifest.json", {}) or {}
    ep_renders = [x for sid, v in ep_shots(ep, host).items()
                  if sid.startswith(f"ep{ep:02d}-") for x in v.get("renders") or []]
    jff = jobs_first_frames(ep)
    if old_man.get("shots") and (old_man.get("t") or 0) >= max([float(x.get("t_done") or 0) for x in ep_renders] + [0]):
        drop_stale(old_man, jff)
        _tl, bad0 = assembly_sources(old_man, jff)
        if bad0:   # K-EDT-V10：原片还没拉回来（每轮 sync 补 4 条）→ 先等，不每轮重做代理
            msg = f"等原片 {len(bad0)} 条：" + "; ".join(bad0)[:200]
            if st["eps"][str(ep)].get("wait_msg") != msg:
                log("ASSEMBLE_WAIT", f"ep{ep:02d}", msg)
            st["eps"][str(ep)].update(status="rendering", wait_msg=msg)
            return
    out = ssh(host, f"cd {DEST} && PYTHONUTF8=1 /root/work/fredw/venv_idm/bin/python tools/series10_video/vidgen.py proxies {host} {ep} --run {RUN_ID}", 1800)
    log("proxies", f"ep{ep:02d}", out.strip()[-200:])
    run([PY, "tools/series10_video/sync.py"], 3600)
    man = jl(VID / "episodes" / f"ep{ep:02d}" / "manifest.json", {}) or {}
    stale = drop_stale(man, jff)   # FIX-VID D10：过期片（首帧换版后的旧片）不进成片
    if stale:
        log("STALE_CLIPS", f"ep{ep:02d}", stale)
    rc_up, out_up = run([PY, "tools/series10_video/upscale_preview.py", f"ep{ep:02d}"], 3600)   # K-EDT-V10：原片放大到 1080 宽
    log("upscale", f"ep{ep:02d}", rc_up, out_up.strip()[-200:].replace("\n", " "))
    tl, bad = assembly_sources(man, jff)
    tlp = VID / "episodes" / f"ep{ep:02d}" / "sources.timeline.json"
    js(tlp, tl)
    # FIX-VID D8：阻断 / 过期 / 等闸门的镜 → 首帧静帧缓推占位，记进 night_state（报告标出），不挡整集按时交付（L-204）
    placeholders = {s["shot"]: str(s.get("block_reason") or s.get("excluded") or s.get("status") or "")[:200]
                    for s in man.get("shots", []) if not s.get("proxy")}
    st["eps"][str(ep)]["placeholder_shots"] = placeholders
    st["eps"][str(ep)]["blocked_shots"] = {s["shot"]: str(s.get("block_reason") or "")[:200] for s in man.get("shots", []) if s.get("status") == "blocked"}
    if placeholders:
        log("PLACEHOLDER_SHOTS", f"ep{ep:02d}", json.dumps(placeholders, ensure_ascii=False)[:400])
    want = sum(1 for s in man.get("shots", []) if s.get("proxy"))
    if not want or sum(1 for s in tl["shots"] if s.get("kind") == "video") < want:
        # 11-01 ep01 首次合成：代理没同步回来，合成器拿全静帧占位也“成功”了 → 必须拦
        # K-EDT-V10：进成片的必须是原片（或原片的放大版），原片没拉回来 / 分辨率低于原片 → 不合成
        log("ASSEMBLE_BLOCKED", f"ep{ep:02d}", f"原片 {sum(1 for s in tl['shots'] if s.get('kind') == 'video')}/{want} 到位", "; ".join(bad)[:300])
        st["eps"][str(ep)]["status"] = "rendering"
        return
    bgm = ctrl.get("bgm", "auto")
    try:
        mdir = RC.music_dir(RUN_ID)     # MERGE-VID-O / L-118：集级 BGM 按剧（V2 = data/music/<剧>，曲库 config/music_v2.json）
    except Exception as e:  # noqa: BLE001  # arch-ok: 曲库校验不过 = 本集不配乐（--no-bgm），不退回 V1 的配乐
        log("BGM", f"ep{ep:02d}", str(e)[:200])
        mdir = None
    music = (mdir / f"ep{ep:02d}.wav") if mdir else Path("/nonexistent")
    args = [PY, "tools/assemble_episode.py", f"ep{ep:02d}", "--out", str(EPS_OUT / "_work"), "--sources-from", str(tlp),
            "--variant", ver, "--dialogue-source", "h3", "--run", RUN_ID]   # W16：合成器按剧取导入稿 / 音色 / 配乐（C-14）
    if bgm == "off" or (bgm == "auto" and not music.exists()):
        args.append("--no-bgm")   # data/music/epNN.wav 是旧剧（《为他而骚》）的 BGM，不能用在 series10
    else:
        args += ["--music-dir", str(mdir.relative_to(ROOT)).replace("\\", "/")]   # 整集 BGM（V1：tools/bgm/agent.py；V2：tools/bgm/bgm_library.py）
    t_asm = time.time()
    rc, out = run(args, 5400)
    log("assemble", f"ep{ep:02d}", rc, out.strip()[-300:].replace("\n", " "))
    # K-OPS-309：合成器非 0 退出 = 失败，不拿 _work 里同版本号的旧残片冒充；只认这次跑出来的文件
    cands = sorted((p for p in (EPS_OUT / "_work").glob(f"ep{ep:02d}_*_{ver}.mp4") if p.stat().st_mtime >= t_asm - 5),
                   key=lambda p: p.stat().st_mtime) if rc == 0 else []
    if rc:
        st["eps"][str(ep)]["assemble_err"] = out.strip()[-300:]
    final = None
    if cands and not LEGACY:
        hr = episode_hard_rules(cands[-1])
        st["eps"][str(ep)]["hard_rules"] = hr
        log("HARD_RULES", f"ep{ep:02d}", ("pass" if hr["ok"] else "FAIL") + (f"（{len(hr.get('warnings') or [])} 条只记）" if hr.get("warnings") else ""),
            json.dumps(hr, ensure_ascii=False)[:400])
        if not hr["ok"]:   # W46：不合硬规矩的合成片不进 data/episodes/<剧>/（sop_gate“整集预览”与复盘只认那里），留在 _work 交人看
            st["eps"][str(ep)]["assemble_err"] = "硬规矩不过：" + "；".join(hr["fails"])[:300]
            cands = []
    if cands:
        final = EPS_OUT / f"ep{ep:02d}_{ver}.mp4"
        shutil.copy2(cands[-1], final)
        tlj = cands[-1].with_suffix(".timeline.json")
        if tlj.exists():
            shutil.copy2(tlj, EPS_OUT / f"ep{ep:02d}_{ver}.timeline.json")
    director = {}
    if final:   # DIRECTOR 11-02（总调度批准，CONSENT VIDEO10/WORKFLOW → DIRECTOR）：调色 + 音效 + 响度、成片分、口型重出单（K-EDT-816 / 805）
        try:   # FIX-VID D12：finish.py 默认 data/import/script_v2.json 是 V1 剧本（post_pass SystemExit“10 镜 vs 16 镜”）→ 传本剧导入稿
            fargs = ["--script", str(RC.script_path(RUN_ID))]
        except Exception as e:  # noqa: BLE001  # arch-ok: 导入稿解析不了 = 不传（finish 照跑 lip_redo / film_score，post_pass 报错记进 errors）
            log("director", f"ep{ep:02d}", "导入稿路径解析失败", str(e)[:200])
            fargs = []
        rc_d, out_d = run([PY, "tools/director/finish.py", str(final), *fargs], 3600)
        try:
            director = json.loads([x for x in out_d.splitlines() if x.startswith("{")][-1])
        except (IndexError, ValueError):
            director = {"errors": [f"finish.py rc={rc_d}: {out_d.strip()[-200:]}"]}
        log("director", f"ep{ep:02d}", rc_d, json.dumps({k: director.get(k) for k in ("post", "film_score", "film_score_post", "lip_redo", "errors")},
                                                       ensure_ascii=False, default=str)[:400])
        if (director.get("delivery_gate") or {}).get("deliver") == "post" and director.get("post") and Path(director["post"]).exists():
            final = Path(director["post"])   # 交付闸门（K-EDT-817，decider=code）放行 → 交付后期版；原合成版 epNN_vN.mp4 保留
        if director.get("lip_redo"):        # K-EDT-805：画内对白 TTS 兜底 → 这几镜送回重出，本集不进定稿
            log("LIP_REDO", f"ep{ep:02d}", [r.get("shot") for r in director["lip_redo"]])
    rc2, out2 = run([PY, "tools/series10_video/episode_report.py", str(ep), host, ver], 1800)
    log("report", f"ep{ep:02d}", rc2, out2.strip()[-200:].replace("\n", " "))
    st["eps"][str(ep)].update(status="assembled" if final else "assemble_failed", final=str(final) if final else None,
                              finalized=time.time(), assembled_n=int(ver[1:]) if final else int(ver[1:]) - 1,
                              resolved_sig=ep_sig(ep, host),
                              director={k: director.get(k) for k in ("film_score", "film_score_post", "lip_redo", "errors", "steps", "delivery_gate")} if director else None,
                              lip_redo=[r.get("shot") for r in director.get("lip_redo") or []] if director else [])
    if final and not LEGACY:
        bgm_after_assembly(ep, ver, used_bgm="--no-bgm" not in args, st=st)
        st["eps"][str(ep)]["retro"] = retro_after_assembly(ep)


EP_SECONDS = (60.0, 120.0)     # L-092：集时长 60–120 秒
SHOT_MAX_S = 6.0               # C-08：单镜 ≤ 6 秒
SHOT_TOL_S = 0.05              # 帧取整余量（24 fps 一帧 0.042 s）


def _ffprobe(p: Path) -> dict:
    """时长 + 流类型。服务器上的 ffprobe 是 offline_20261101/bin/ffprobe 兼容壳（只认 -show_streams -show_format -of json 等两种调用，
    别的写法输出 {}；且只报 Video / Audio 流）→ 用它认得的写法；字幕流另用 ffmpeg -i 的 stderr 判（壳看不见字幕流）"""
    exe = shutil.which("ffprobe") or "ffprobe"
    r = subprocess.run([exe, "-v", "error", "-show_streams", "-show_format", "-of", "json", str(p)],
                       capture_output=True, text=True, timeout=120)
    if r.returncode:
        return {"error": (r.stderr or "")[-200:]}
    try:
        d = json.loads(r.stdout or "{}")
    except ValueError:
        return {"error": f"ffprobe 输出不是 JSON：{(r.stdout or '')[:120]}"}
    if not (d.get("format") or {}).get("duration"):
        return {"error": f"ffprobe 没给时长：{(r.stdout or '')[:120]}"}
    ff = shutil.which("ffmpeg") or "ffmpeg"
    try:
        e = subprocess.run([ff, "-hide_banner", "-i", str(p)], capture_output=True, text=True, errors="replace", timeout=120).stderr or ""
        if re.search(r"Stream #\d+:\d+[^\n]*: Subtitle:", e):
            d.setdefault("streams", []).append({"codec_type": "subtitle"})
    except (OSError, subprocess.TimeoutExpired) as ex:
        return {"error": f"ffmpeg -i 判字幕流失败：{ex!r}"[:200]}
    return d


def episode_hard_rules(mp4: Path, probe=None) -> dict:
    """W46：整集进 data/episodes/<剧>/ 之前的硬规矩（代码判，失败关闭）：
    挡：C-08 每镜 ≤ 6 s（timeline shots[].duration_s，末镜尾帧定格不算）；C-07 / L-002 无字幕流（ffprobe + ffmpeg -i，
        timeline subtitles=false）；有视频流；L-092 集长 60–120 s 按**剧本时长**（shots[].script_duration_s 之和，写作规则口径）。
    只记不挡（warnings，进 night_state / 日志）：合成后实长不在 60–120 s（剪辑规则按运动量 / 对白修头尾，沙箱实测真 Pika 片 5.17→4.0 s，
        11 镜可能掉到 60 s 以下）；合成器 gates.verdict=fail（对白溢出 / 缺镜：“不能当成片”，预览照出）。
    C-06 不看镜头 / L-141 At 只标切镜在视频编译层判（build_jobs / hard_rule_check），成片层不重复"""
    fails, warns = [], []
    pr = (probe or _ffprobe)(mp4)
    if pr.get("error"):
        return {"ok": False, "fails": [f"ffprobe 读不了：{pr['error']}"], "warnings": []}
    dur = float((pr.get("format") or {}).get("duration") or 0)
    kinds = [s.get("codec_type") for s in pr.get("streams") or []]
    if "subtitle" in kinds:
        fails.append("C-07 成片里有字幕流")
    if "video" not in kinds:
        fails.append("没有视频流")
    tl = jl(mp4.with_suffix(".timeline.json"), None)
    script_s = None
    if not tl:
        fails.append("没有 timeline.json（判不了单镜时长）")
    else:
        if tl.get("subtitles"):
            fails.append("C-07 timeline subtitles=true")
        long_shots = [f"{s.get('shot')} {_shot_s(s):.2f}s" for s in tl.get("shots") or [] if _shot_s(s) > SHOT_MAX_S + SHOT_TOL_S]
        if long_shots:
            fails.append("C-08 单镜超 6 秒：" + "、".join(long_shots))
        sd = [float(s["script_duration_s"]) for s in tl.get("shots") or [] if s.get("script_duration_s") is not None]
        script_s = round(sum(sd), 3) if sd else None
        if script_s is not None and not EP_SECONDS[0] <= script_s <= EP_SECONDS[1]:
            fails.append(f"L-092 剧本集长 {script_s:.1f}s 不在 {EP_SECONDS[0]:.0f}–{EP_SECONDS[1]:.0f}s")
        if (tl.get("gates") or {}).get("verdict") == "fail":
            warns.append(f"合成闸门 verdict=fail（预览照出，不能当成片）：{json.dumps(tl.get('gates'), ensure_ascii=False)[:160]}")
    if not EP_SECONDS[0] <= dur <= EP_SECONDS[1]:
        (warns if script_s is not None else fails).append(f"L-092 合成实长 {dur:.1f}s 不在 {EP_SECONDS[0]:.0f}–{EP_SECONDS[1]:.0f}s"
                                                         + ("（剧本 %.1fs；剪辑修头尾所致，交剪辑 / 写手）" % script_s if script_s is not None else ""))
    return {"ok": not fails, "fails": fails, "warnings": warns, "duration_s": round(dur, 3), "script_s": script_s, "streams": kinds,
            "shots": len((tl or {}).get("shots") or []), "max_shot_s": max([_shot_s(s) for s in (tl or {}).get("shots") or []] + [0]),
            "tail_hold_s": (tl or {}).get("tail_hold_s")}


def _shot_s(s: dict) -> float:
    """单镜时长：本镜视频段 duration_s（末镜的尾帧定格 tail_hold 不算镜头本身，assemble 把它并进末镜 picture_s）；没有再用 picture_s"""
    return float(s.get("duration_s") or s.get("picture_s") or 0)


def retro_after_assembly(ep: int) -> dict:
    """W46：整集预览一进 data/episodes/<剧>/ 就走 episode_retro.auto（与 --auto 同一条路：生成 / 登记跟进 / 按配置自动 done）。
    原来写的“常驻 autoflow_resident.retro_tick”从没接上（代码与 git 历史都没有）→ 预览出了复盘也没人跑，第 N+1 集出图永远卡“复盘”。
    在 night 所在机器（服务器：producer video_takeover / night 常驻）跑，写本机 docs/master/RETRO_*.md——服务器 producer 的出图闸门读这一份。
    出错只记日志（复盘不挡成片）"""
    try:
        import importlib.util as _u
        sp = _u.spec_from_file_location("episode_retro_night", ROOT / "tools/master/episode_retro.py")
        m = _u.module_from_spec(sp)
        sp.loader.exec_module(m)
        res = m.auto(RUN_ID, int(ep), ROOT)
    except Exception as e:  # noqa: BLE001  # arch-ok: 复盘出错不影响成片，记进 night_state 交总调度
        res = {"error": repr(e)[:300]}
    log("RETRO", f"ep{int(ep):02d}", json.dumps(res, ensure_ascii=False, default=str)[:300])
    return res


BGM_AUTO_MAX = 2    # 同一份剪辑签名最多自动重合成 2 次（一次确认签名 L5，一次带 BGM）


def bgm_after_assembly(ep: int, ver: str, used_bgm: bool, st: dict) -> dict:
    """MERGE-VID-O（L-118 / L-131）：V2 集级 BGM 的写入点。合成后按本剧时间轴判剪辑锁定（tools/bgm/bgm_library.py，L1–L5）：
    只差 L5（签名要连续两版一致）→ 自动再合成一次确认；锁定且曲库配乐已交付、而这一版没带 BGM → 再合成一次带上 BGM。
    同一签名最多 BGM_AUTO_MAX 次，防循环"""
    x = st["eps"][str(ep)]
    tlj = EPS_OUT / f"ep{ep:02d}_{ver}.timeline.json"
    if not tlj.exists():
        return {}
    rc, out = run([PY, "tools/bgm/bgm_library.py", "--run", RUN_ID, "--ep", str(ep), "--timeline", str(tlj)], 1800)
    try:
        res = json.loads([ln for ln in out.splitlines() if ln.startswith("{")][-1])
    except (IndexError, ValueError):
        res = {"error": f"library.py rc={rc}: {out.strip()[-200:]}"}
    log("BGM_LIB", f"ep{ep:02d}", json.dumps(res, ensure_ascii=False)[:300])
    lock = res.get("lock") or {}
    auto = x.setdefault("bgm_auto", {})
    n = int(auto.get(lock.get("sig") or "-", 0))
    want = (res.get("status") == "delivered" and not used_bgm) or (not lock.get("locked") and lock.get("fails") == ["L5"])
    if want and n < BGM_AUTO_MAX:
        auto[lock.get("sig") or "-"] = n + 1
        x["status"] = "rendering"          # 下一轮 EP_RESOLVED → finalize 重合成（版本号照常递增）
        x["resolved_sig"] = None
        x["force_finalize"] = True         # FIX-NIGHT2 #2：同签名的 finalize 默认不重跑，BGM 确认 / 带 BGM 这两次显式放行（≤ BGM_AUTO_MAX）
        log("BGM_REASSEMBLE", f"ep{ep:02d}", "确认剪辑签名" if res.get("status") != "delivered" else "带上集级 BGM")
    x["bgm"] = res
    return res


def write_status(st):
    rc = jl(VID / "recipe_choice.json", {}) or {}   # 配方口径从 recipe_choice.json 读（D-VID-01 改 Pika Flex 后自动跟着走）
    rtxt = "、".join(f"{k} = {v}" for k, v in rc.items() if k.endswith("_default")) or "（recipe_choice.json 读不到）"
    L = [f"# {RUN_ID} 视频 · 夜间进度（night.py 自动写；交总调度）", "", f"更新：{time.strftime('%Y-%m-%d %H:%M:%S')}", "",
         f"当前配方（{VID_REL}/recipe_choice.json）：{rtxt}", "",
         "成片输入：原片（video/clips/）或其放大版 `_sr1080.mp4`；540×960 代理只给审片页（K-EDT-V10）", "",
         "工位分卡（L-206，config/pipeline/lane_roles.json）：" + "；".join(
             f"{h} {r['phase']} 视频道 {r['lanes']['video']}（集 {r['eps']}）" if r else f"{h} 不适用（旧行为）"
             for h, r in sorted((st.get("lane_roles") or {}).items())), "",
         "| 集 | 主机 | 状态 | 成片 | 审阅 |", "|---|---|---|---|---|"]
    for e in range(1, 11):
        x = st["eps"].get(str(e), {})
        L.append(f"| ep{e:02d} | {x.get('host', '')} | {x.get('status', '等首帧')} | {x.get('final') or ''} | "
                 f"{'docs/series10_video/ep%02d_review.md' % e if x.get('status') == 'assembled' else ''} |")
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text("\n".join(L) + "\n", encoding="utf-8")


IMAGE_LANES = ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1"]
FRAME_BUSY = ("pending", "queued", "running", "waiting", "retry", "submitted", "rendering")


def gated(o: dict) -> bool:
    """K-OPS-305 修订（总调度批准，2026-11-01 离线交接）：等总调度的（master_reject / 等复核）和等 REFLOCK 的 pending 帧
    不是监督能自动派的，不算“帧忙”——否则这几镜一直挂着，视频道永远放不开。能自动派的帧照样优先（让道模式下帧先拿空闲道）"""
    if str(o.get("status")) != "pending":
        return False
    w = str(o.get("waiting_for") or "")
    return bool(o.get("master_reject") and w) or any(k in w for k in ("REFLOCK", "总调度", "复核", "项目方"))


def frames_busy() -> int:
    """PRODUCER 登记表里还在排 / 在跑的首帧、尾帧数（data/producer/registry.json）。读不到按“忙”算（保守，图片优先）"""
    d = jl(ROOT / "data/producer/registry.json", None)
    if d is None:
        return 1
    n = 0

    def walk(o):
        nonlocal n
        if isinstance(o, dict):
            if o.get("kind") in ("first", "last") and str(o.get("status")) in FRAME_BUSY and not gated(o):
                n += 1
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)
    walk(d.get("episodes"))
    return n


def video_boost(ctrl: dict, hold: list) -> tuple[list, dict]:
    """VIDEO-PAR（开关默认关）：night_control.json {"video_boost": {"enabled": true, "vram_gate": {"gpu36:1": 21000}}}。
    开 → gate 里的道从 hold 里摘掉，改由 vidgen 按卡上空闲显存放行（看图 / 人数检测占着就不提交）；关 / 没配 → 原样。
    返回（挂道, vram_gate）"""
    b = ctrl.get("video_boost") or {}
    gate = {str(k): int(v) for k, v in (b.get("vram_gate") or {}).items()} if b.get("enabled") else {}
    return [x for x in hold if x not in gate], gate


def apply_lane_policy(st, ctrl):
    """总调度 11-01 05:4x：首帧 / 尾帧还有在排或在跑的 → 视频只用 gpu36:2，图片道全部挂住（不再让道式插队，
    一条 9 分钟的视频会让刚到的首帧白等整条）；首帧全出完后才恢复让道模式。挂住时撤回本工具在图片道上排队未跑的任务"""
    busy = frames_busy()
    # K-OPS-305 修订（总调度批准 11-01 离线交接）：帧基本出完 → 视频可用 gpu33:0/1/3 + gpu36:0/1/2（让道模式：
    # 帧有真实派单时，空出来的道先给帧——PRODUCER 每 20 s 一轮、编排器要等道空 yield_s 才交）。
    # 要恢复“帧在排就把图片道全挂住”的旧做法：night_control.json 设 "frames_exclusive": true
    mode = "video_lane_only" if busy and ctrl.get("frames_exclusive") else "yield"
    ep01_open = mode == "video_lane_only" and (st["eps"].get("1") or {}).get("status") not in (
        "assembled", "assemble_failed", "hold_voices")
    key = mode + ("+ep01@gpu33:3" if ep01_open else "") + "|hold=" + ",".join(sorted(ctrl.get("hold_lanes", []) or []))   # K-OPS-E20：挂道变了要重算
    key += "|gate=" + json.dumps(video_boost(ctrl, [])[1], sort_keys=True)
    key += "|shard=" + ",".join(f"{e}:{c['owner']}" for e, c in sorted((_VS().shard_eps(RUN_ID) if _VS() else {}).items()))   # 分片开关变了要重算
    key += "|roles=" + roles_key(st)        # L-206：阶段 / 视频道变了要重写 control（一集内每卡至多切换一次：frames → videos）
    if st.get("lane_mode") == mode and st.get("lane_key") == key:
        return ctrl
    hosts = jl(VID / "hosts.json", {}) or {}
    for host in _hosts_here():   # A-07
        eps_on = _eps_on(hosts, host)
        # DEBUG-RSI 11-02（K-OPS-E20，CONSENT VIDEO10 → DEBUG_RSI by 总调度）：video_lane_only 模式原来只挡出图道、不看
        # control 的 hold_lanes → 挂道挡不住视频（gpu36:0 两次重启窗口被 VIDEO10 视频占住）。现在两者合并
        ctl_hold = list(ctrl.get("hold_lanes", []) or [])
        hold = sorted(set(IMAGE_LANES if mode == "video_lane_only" else []) | set(ctl_hold))
        per_lane, shared = ctrl["per_lane"], ctrl.get("shared_lanes", [])
        if ep01_open and host == hosts.get("1"):
            hold = sorted(set(x for x in IMAGE_LANES if x != "gpu33:3") | set(ctl_hold))
            eps_on, per_lane, shared = [1], 1, [x for x in shared if x != "gpu33:3"]
        hold, gate = video_boost(ctrl, hold)
        hold = _shard_hold(host, hold, st)      # L-207：本阶段的视频道不被分片排除表挂住（gpu33:3 视频段出视频）
        c = {"jobs": "jobs.json", "mode": "prod", "eps": eps_on, "per_lane": per_lane, "linger": True,
             "hold_lanes": hold, "shared_lanes": video_shared(shared, ctrl), "yield_s": ctrl["yield_s"]}
        if gate:
            c["vram_gate"] = gate
        roles_control(host, st, c)      # L-206：按阶段分卡
        run([PY, "tools/series10_video/deploy.py", "control", host, json.dumps(c, ensure_ascii=False)])
        if mode == "video_lane_only":
            ports = {"gpu33": [8188, 8189, 8191], "gpu36": [8188, 8189, 8190]}[host]
            py = ("import json,urllib.request\n"
                  f"for p in {ports}:\n"
                  "    d=json.load(urllib.request.urlopen(f'http://127.0.0.1:{p}/queue',timeout=5))\n"
                  "    ids=[i[1] for i in d['queue_pending'] if str((i[3] or {}).get('client_id','')).startswith('video10-')]\n"
                  "    if ids: urllib.request.urlopen(urllib.request.Request(f'http://127.0.0.1:{p}/queue',json.dumps({'delete':ids}).encode(),{'Content-Type':'application/json'}),timeout=5); print(p,len(ids))\n")
            out = ssh(host, f"python3 - <<'EOF'\n{py}EOF", 60)
            log("WITHDRAW", host, out.strip()[-200:])
    st["lane_mode"] = mode
    st["lane_key"] = key
    log("LANE_POLICY", key, f"首帧 / 尾帧在排或在跑 {busy}")
    return ctrl


def _hosts_here() -> tuple:
    """服务器上（OFFLINE_SELF）只处理本机；笔记本两台都管（A-07）"""
    import os as _os
    me = _os.environ.get("OFFLINE_SELF")
    return (me,) if me else ("gpu33", "gpu36")


def partition_hosts(part: dict | None = None) -> dict:
    """K-OPS-F21（总调度 11-02 17:2x，AUDIT-M 查出视频分区 5–6 份来源且不一致）：视频归哪台只有一个来源 =
    data/state/netfix/partition.json 的 video 分区。→ {"<集号>": host}；读不到 → {}（不改 hosts.json）"""
    if part is None:
        try:
            sys.path.insert(0, str(ROOT / "tools/netfix"))
            import dispatch as _D
            part = _D.read_partition()
        except Exception:  # noqa: BLE001  # arch-ok: 分区读不到 → 本轮不改 hosts.json（下一轮再读）
            return {}
    # MERGE-VID-O：分区若按剧登记（partition.runs.<剧>.video）就用本剧的；没有 = 全局 video 分区（按集号分机，同一规则）
    vid = (((part or {}).get("runs") or {}).get(RUN_ID) or {}).get("video") or (part or {}).get("video") or {}
    return {str(e): h for h, eps in vid.items() for e in eps}


def sync_hosts_from_partition(part: dict | None = None) -> dict:
    """video/hosts.json 由 partition.json 生成（不再手改、不再 pick_host 自己挑）；有变化才写，返回写入后的表"""
    want = partition_hosts(part)
    cur = jl(VID / "hosts.json", {}) or {}
    if want and want != cur:
        js(VID / "hosts.json", want)
        log("HOSTS_FROM_PARTITION", json.dumps(want, ensure_ascii=False), "旧", json.dumps(cur, ensure_ascii=False))
        return want
    return cur


def poll_seconds(ctrl: dict) -> float:
    """SLIM-CDE 11-05 D：night 轮询间隔。night_control.json poll_s 优先；没写 = V1 120 s、V2 45 s（逐镜派单本来就按镜判，
    慢的只是这个 sleep：实测 READY→下一轮 build_jobs 间隔 134 s，其中 sleep 120 s，其余 ~14 s 是 build/sync/register）"""
    try:
        v = float(ctrl.get("poll_s")) if ctrl.get("poll_s") is not None else (120.0 if LEGACY else 15.0)   # FIX-NIGHT2 #3：V2 45 → 15 s
    except (TypeError, ValueError):
        v = 120.0
    return min(max(v, 15.0), 600.0)


# ---------------------------------------------------------------- FIX-NIGHT2 #2 / #3 / #7：后台 finalize、固定成本门、单实例锁
REGISTER_EVERY_S = int(os.environ.get("NS_REGISTER_EVERY_S", "1800"))   # 没有新定下的镜时，register / trim 最多每 30 min 兜底跑一次
FINALIZE_WAIT_S = 120            # finalize 子进程以“等原片 / 原片没到位”收尾 → 至少隔这么久再起
FINALIZE_PROCS: dict = {}        # {集: Popen}（本进程起的 finalize 子进程；重启后按 pid 判活）
SETTLED = ("done", "best_effort", "blocked")


def settled_sig(st) -> str:
    """已定下的镜（done / best_effort）+ 其入选片是否已在本机 → 签名。变了 = 有新东西要登记（register_takes / trim_takes）"""
    rows = {}
    for e, x in (st.get("eps") or {}).items():
        if not x.get("host"):
            continue
        for sid, r in ep_shots(int(e), x["host"]).items():
            if r.get("status") in ("done", "best_effort") and r.get("chosen"):
                f = next((y.get("file") for y in r.get("renders") or [] if y.get("variant") == r["chosen"]), None)
                rows[sid] = [r["status"], r["chosen"], bool(f and (ROOT / f).is_file())]
    return json.dumps(rows, sort_keys=True, ensure_ascii=False)


def register_due(st, now: float | None = None) -> bool:
    """FIX-NIGHT2 #3：register_takes（2.5–3 min）/ trim_takes（~1 min）以前每轮都跑——只在定下的镜有变化、或距上次 ≥ REGISTER_EVERY_S 时跑"""
    now = now or time.time()
    try:
        sig = settled_sig(st)
    except Exception as e:  # noqa: BLE001  # arch-ok: 签名算不出 = 照旧每轮跑（退回原行为）
        log("SETTLED_SIG_ERR", repr(e)[:160])
        return True
    if sig == st.get("settled_sig") and now - float(st.get("registered_at") or 0) < REGISTER_EVERY_S:
        return False
    st["settled_sig"], st["registered_at"] = sig, now
    return True


def pid_alive(pid) -> bool:
    """进程还在？Windows 不能用 os.kill(pid, 0)（会 TerminateProcess）→ OpenProcess + GetExitCodeProcess；Linux os.kill 0"""
    try:
        pid = int(pid)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    if os.name == "nt":
        import ctypes
        k = ctypes.windll.kernel32
        h = k.OpenProcess(0x1000, False, pid)        # PROCESS_QUERY_LIMITED_INFORMATION
        if not h:
            return False
        try:
            code = ctypes.c_ulong()
            return bool(k.GetExitCodeProcess(h, ctypes.byref(code))) and code.value == 259   # STILL_ACTIVE
        finally:
            k.CloseHandle(h)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def finalize_sync(ctrl: dict) -> bool:
    """旧路径（同步 finalize，阻塞主循环）：night_control.json "finalize_sync": true 或 NS_FINALIZE_SYNC=1"""
    return bool(ctrl.get("finalize_sync")) or os.environ.get("NS_FINALIZE_SYNC") == "1"


def start_finalize(ep: int, host: str, st: dict, ctrl: dict, spawn=None) -> bool:
    """FIX-NIGHT2 #2：整集落定 → finalize 放到后台子进程（night.py --finalize <集>），主循环继续派单（原来代理 / 同步 / 放大 / 合成 /
    导演 11–14 min 同步阻塞，gpu36 三卡空转）。同一 resolved_sig 已合成过（finalize_done_sig）且没有显式放行（force_finalize：
    REOPEN / 重试 / BGM 确认）→ 不再起；上一次以“等原片”收尾 → 至少隔 FINALIZE_WAIT_S。返回是否起了"""
    x = st["eps"][str(ep)]
    if finalize_sync(ctrl):
        finalize(ep, host, st, ctrl)
        x["finalize_done_sig"] = x.get("resolved_sig")
        x.pop("force_finalize", None)
        return True
    sig = ep_sig(ep, host)
    now = time.time()
    if x.get("finalize_done_sig") == sig and not x.get("force_finalize"):
        if x.get("finalize_skip_sig") != sig:
            x["finalize_skip_sig"] = sig
            log("FINALIZE_SKIP", f"ep{ep:02d}", "同一入选版本已合成过，不重跑（版本变 / 重试 / BGM 确认才重跑）")
        return False
    if now < float(x.get("finalize_wait_until") or 0):
        return False
    job = {"id": f"{ep}:{int(now)}", "pid": None, "sig": sig, "started": now}
    args = [PY, "tools/series10_video/night.py", "--finalize", str(ep), "--job", job["id"], "--run", RUN_ID]
    try:
        if spawn is not None:
            job["pid"] = spawn(args)
        else:
            out = open(VID / f"finalize_ep{ep:02d}.out", "ab")
            p = subprocess.Popen(args, cwd=str(ROOT), env=child_env(), stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
            FINALIZE_PROCS[str(ep)] = p
            job["pid"] = p.pid
    except OSError as e:   # arch-ok: 子进程起不来 = 当场按合成失败记（retry_assembly 20 min 后再试），主循环不阻塞
        x.update(status="assemble_failed", assemble_err=f"finalize 子进程起不来：{e}"[:300], finalized=now)
        log("FINALIZE_SPAWN_ERR", f"ep{ep:02d}", repr(e)[:200])
        return False
    x.pop("force_finalize", None)
    x.pop("finalize_skip_sig", None)
    x.update(status="finalizing", finalize_job=job)
    log("FINALIZE_BG", f"ep{ep:02d}", "pid", job["pid"], "sig", sig[:60])
    return True


def reap_finalize(e: str, x: dict, st: dict) -> bool:
    """后台 finalize 结束了 → 把子进程写的结果（VID/finalize_epNN.result.json）并回 night_state；还在跑 → False"""
    job = x.get("finalize_job") or {}
    proc = FINALIZE_PROCS.get(str(e))
    alive = (proc.poll() is None) if proc is not None else pid_alive(job.get("pid"))
    if alive:
        return False
    FINALIZE_PROCS.pop(str(e), None)
    ep = int(e)
    res = jl(VID / f"finalize_ep{ep:02d}.result.json", None)
    if not isinstance(res, dict) or res.get("id") != job.get("id"):
        x.update(status="assemble_failed", assemble_err=f"finalize 子进程无结果（pid {job.get('pid')}，看 {VID_REL}/finalize_ep{ep:02d}.out）",
                 finalized=time.time())
        x.pop("finalize_job", None)
        log("FINALIZE_NO_RESULT", f"ep{ep:02d}", x["assemble_err"])
        return True
    nx = dict(res.get("x") or {})
    nx["host"] = x.get("host") or nx.get("host")
    nx.pop("finalize_job", None)
    if res.get("err"):
        nx["assemble_err"] = str(res["err"])[:300]
        if nx.get("status") in ("rendering", "finalizing", None):
            nx["status"] = "assemble_failed"
            nx["finalized"] = time.time()
    if nx.get("status") in ("assembled", "assemble_failed"):
        nx["finalize_done_sig"] = job.get("sig")
    elif nx.get("status") == "rendering":          # 以“等原片 / 原片没到位”收尾：下一轮还要起，但别每轮都起
        nx["finalize_wait_until"] = time.time() + FINALIZE_WAIT_S
    st["eps"][str(e)] = nx
    log("FINALIZE_DONE", f"ep{ep:02d}", nx.get("status"), nx.get("final") or nx.get("assemble_err") or nx.get("wait_msg") or "")
    try:   # W-KPI 11-06：合成收尾 → 后台起每集耗时报告（L-205；不等、不阻塞主循环，起不来只记日志）
        subprocess.Popen([PY, str(ROOT / "tools/master/episode_kpi_report.py"), "--run", RUN_ID, "--episode", str(ep), "--quiet"],
                         cwd=str(ROOT), env=child_env(), stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL)
    except Exception as ex:  # noqa: BLE001  # arch-ok: KPI 报告只是旁路，任何失败都不能影响 night 收尾
        log("KPI_SPAWN_ERR", f"ep{ep:02d}", repr(ex)[:200])
    return True


def finalize_child(ep: int, job_id: str) -> int:
    """night.py --finalize <集> --job <id>：子进程里跑 finalize（只读 night_state，结果写 finalize_epNN.result.json，由主循环并回）"""
    st = jl(STATE, None) or {"eps": {}}
    x = dict((st.get("eps") or {}).get(str(ep)) or {})
    host = x.get("host") or (jl(VID / "hosts.json", {}) or {}).get(str(ep))
    if not host:
        log("FINALIZE_CHILD_ERR", f"ep{ep:02d}", "没有主机")
        return 2
    x.pop("finalize_job", None)
    x["status"] = "rendering"
    local = {"eps": {str(ep): x}, "pending_shots": {}}
    ctrl = expire_holds({**DEFAULT_CTRL, **(jl(CTRL, {}) or {})})
    err = None
    try:
        finalize(int(ep), host, local, ctrl)
    except Exception as e:  # noqa: BLE001  # arch-ok: 子进程里的任何异常都要落到结果文件（主循环按合成失败处理），不能静默
        err = repr(e)[:300]
        log("FINALIZE_CHILD_ERR", f"ep{ep:02d}", err)
    js(VID / f"finalize_ep{ep:02d}.result.json", {"id": job_id, "ep": ep, "done": time.time(), "err": err, "x": local["eps"][str(ep)]})
    return 0 if not err else 1


def resident_pid() -> int | None:
    """常驻 night 的 pid（VID/night.pid，还活着才算）"""
    d = jl(VID / "night.pid", None)
    pid = (d or {}).get("pid") if isinstance(d, dict) else None
    return int(pid) if pid and pid_alive(pid) else None


def acquire_lock() -> bool:
    """FIX-NIGHT2 #7：night 单实例（同一台两个 night 写同一份 night_state / control 会互相覆盖）"""
    rp = resident_pid()
    if rp and rp != os.getpid():
        return False
    js(VID / "night.pid", {"pid": os.getpid(), "started": time.time(), "host": os.environ.get("OFFLINE_SELF"), "run": RUN_ID})
    return True


def expire_holds(ctrl: dict) -> dict:
    """K-OPS-I15（SLIM-CDE 11-05）：night_control.json 的 hold_lanes 必须带 expires_at（hold_expires: {道: iso} 或整串 iso）；
    没带的挂满 6 h 自动忽略并记日志（11-05 10:3x 视频基准加的 gpu36:0 hold 没撤 → 21:1x 六卡全空）"""
    hl = list(ctrl.get("hold_lanes") or [])
    if not hl:
        return ctrl
    try:
        _ap = str(ROOT / "tools" / "autopilot")
        if _ap not in sys.path:
            sys.path.insert(0, _ap)
        import hold_expiry as HX
        he = ctrl.get("hold_expires") or ctrl.get("hold_expires_at")
        exp = {x: he for x in hl} if isinstance(he, str) else dict(he or {})
        kept = HX.filter_lane_holds(hl, exp, VID / "night_hold_seen.json",
                                    log=lambda ln, why: log("HOLD_EXPIRED_IGNORED", ln, why, "night_control.json hold_lanes"))
    except Exception as e:  # noqa: BLE001  # arch-ok: 过期判断出错 = 原样挂着（失败关闭，不凭空放开），记日志
        log("HOLD_EXPIRY_ERR", repr(e)[:160])
        return ctrl
    return {**ctrl, "hold_lanes": kept}


def loop_once(st):
    heartbeat("loop_start")
    sync_hosts_from_partition()
    ctrl = expire_holds({**DEFAULT_CTRL, **(jl(CTRL, {}) or {})})
    eps_specs = specs_by_ep()
    pf = _B().passed_frames()                      # FIX-NIGHT2 #3：每轮只算一次（原来 ready_eps / ready_shots 各算一遍）
    ready_eps(eps_specs, ctrl, pf)                 # 只为 force_eps 入账
    rs, files = ready_shots(eps_specs, ctrl, pf)
    closed = RC.closed_now(RUN_ID)                 # L-209 S2.2：关闭的集不再派视频（enforce）；record 只记 ep_closed_skip
    rs = {ep: ids for ep, ids in rs.items() if not (ep in closed and RC.closed_skip(RUN_ID, ep, f"video:ep{int(ep):02d}", "night", closed))}
    # L-206 工位分卡：每台一个结论（阶段 + 视频道），进 lane_key / 就绪签名；阶段翻转（frames → videos）就重写 control + 重编作业
    old_roles = roles_key(st)
    st["lane_roles"] = {h: roles_for_host(h, eps_specs, st, rs) for h in _hosts_here()}
    if roles_key(st) != old_roles:
        log("LANE_ROLES", roles_key(st))
    apply_lane_policy(st, ctrl)
    if st.get("lane_mode") == "video_lane_only":
        ctrl = {**ctrl, "hold_lanes": IMAGE_LANES}
        if "+ep01@gpu33:3" in str(st.get("lane_key")):
            ctrl["ep01_lane"] = True
    try:   # W46：尾帧过契约才过逐镜“视频”闸门（hf-08）→ 尾帧变了也要重编作业（原来只看首帧，S4 / S6 尾帧到了也不进 jobs.json）
        lasts = {k: (v.get("file") if isinstance(v, dict) else v) for k, v in (_B().passed_lasts() or {}).items()}
    except Exception as e:  # noqa: BLE001  # arch-ok: 尾帧清单读不了 = 签名不含尾帧（退回原口径），记日志
        log("LASTS_SIG", repr(e)[:160])
        lasts = {}
    regen = regen_holds_now(eps_specs)             # L-206 hold_regen_downstream：换代中的镜进签名（hold 出现 / 解除都重编）
    sig = json.dumps({"shots": rs, "files": files, "lasts": lasts, "roles": roles_key(st), "regen": sorted(regen)},
                     sort_keys=True, ensure_ascii=False)
    if rs and sig != st.get("ready_sig"):
        hosts = jl(VID / "hosts.json", {}) or {}
        touched = set()
        for ep, ids in rs.items():
            if str(ep) not in hosts:
                # K-OPS-F21：分区里没有这一集 = 没人负责，不自己挑主机（以前 pick_host 写 hosts.json，和 partition.json 打架）
                log("NO_PARTITION", f"ep{ep:02d}", "partition.json video 分区里没有这一集，跳过")
                continue
            touched.add(hosts[str(ep)])
            sc = _shard_cfg(ep)
            if sc:   # 分片集：另一台（helper）也要派；本机不是 owner = helper，只出镜、不合成（owner 那台合成）
                touched |= set(sc["hosts"])
            x = st["eps"].setdefault(str(ep), {"host": hosts[str(ep)], "dispatched": time.time(), "status": "rendering"})
            if sc:
                me = os.environ.get("OFFLINE_SELF")
                x["shard_helper"] = bool(me) and me != sc["owner"]
            x["ready_shots"] = ids
            st.setdefault("pending_shots", {})[str(ep)] = len(eps_specs[ep])
        if touched and dispatch_hosts(touched, st, ctrl):
            st["ready_sig"] = sig
            log("READY", {f"ep{e:02d}": len(v) for e, v in rs.items()})
    run([PY, "tools/series10_video/sync.py"], 1800)
    # DATAALIGN 11-01：过门的镜登记进 takes.json（/api/progress、集摘要、画布才读得到）；按 sha256 去重，重复调无害
    # FIX-NIGHT2 #3：只在有新定下的镜（settled_sig 变）或距上次 ≥ REGISTER_EVERY_S 时跑（原来每轮固定 3.5–4 min）
    if register_due(st):
        rc, out = run([PY, "tools/pipeline/register_takes.py", "--video10", VID_REL,
                       "--label", "VIDEO10 预览片"], 1800)
        if rc:
            log("register_takes", rc, out.strip()[-200:].replace("\n", " "))
        if not LEGACY and st.get("eps"):   # W46（总调度 05:4x）：已登记的当前视频 > 6 s → _le6 版登记并设为当前（原版保留）
            rc_t, out_t = run([PY, "tools/series10_video/trim_takes.py", "--run", RUN_ID, "--eps", ",".join(sorted(st["eps"]))], 1800)
            if rc_t or '"changed": []' not in out_t:
                log("TRIM_TAKES", rc_t, out_t.strip()[-300:].replace("\n", " "))
    retry_assembly(st)
    reopen_changed(st)
    for e, x in list(st["eps"].items()):
        if x.get("status") == "finalizing" and reap_finalize(e, x, st):   # FIX-NIGHT2 #2：后台 finalize 收尾
            apply_lane_policy(st, ctrl)
            x = st["eps"][e]
        if x.get("status") == "rendering" and not x.get("shard_helper"):
            fin, recs = ep_resolved(int(e), x["host"])
            st["pending_shots"][e] = sum(1 for r in recs.values() if r.get("status") not in SETTLED)
            if fin:
                if x.get("finalize_done_sig") != ep_sig(int(e), x["host"]) or x.get("force_finalize"):
                    log("EP_RESOLVED", f"ep{int(e):02d}", {k: v.get("status") for k, v in recs.items()})
                if start_finalize(int(e), x["host"], st, ctrl):
                    apply_lane_policy(st, ctrl)
    js(STATE, st)
    write_status(st)


def main(argv):
    sys.stdout.reconfigure(encoding="utf-8")
    if "--finalize" in argv:                       # FIX-NIGHT2 #2：后台 finalize 子进程入口
        ep = int(argv[argv.index("--finalize") + 1])
        job = argv[argv.index("--job") + 1] if "--job" in argv else ""
        return finalize_child(ep, job)
    log("RUN", RUN_ID, VID_REL)
    st = jl(STATE, None) or {"eps": {}, "pending_shots": {}, "started": time.time()}
    if "--once" in argv:
        rp = resident_pid()
        if rp:                                     # FIX-NIGHT2 #7：常驻在跑 → --once 只读（不写 night_state / control / jobs）
            log("ONCE_READONLY", f"常驻 night pid {rp} 在跑，--once 不写状态")
            print(json.dumps({"resident_pid": rp, "eps": {e: {k: x.get(k) for k in ("host", "status", "final", "ready_shots")}
                                                         for e, x in st["eps"].items()}}, ensure_ascii=False, indent=1))
            return 0
        try:
            loop_once(st)
        except Exception as e:  # noqa: BLE001
            log("LOOP_ERR", repr(e)[:300])
        return 0
    if not acquire_lock():
        log("ALREADY_RUNNING", f"常驻 night pid {resident_pid()} 在跑，本实例退出（单实例锁 {VID_REL}/night.pid）")
        return 1
    heartbeat("start")
    while True:
        try:
            loop_once(st)
        except Exception as e:  # noqa: BLE001
            log("LOOP_ERR", repr(e)[:300])
        time.sleep(poll_seconds({**DEFAULT_CTRL, **(jl(CTRL, {}) or {})}))


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
