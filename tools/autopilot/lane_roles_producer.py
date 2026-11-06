"""L-206 工位分卡（项目方 11-06：“一个 gpu 专门出图，另一个 gpu 审图”）——单一来源 config/pipeline/lane_roles.json 的读取、
每集阶段推导、阶段状态文件（出图 / 审图 / 巡检侧；视频侧读者是 tools/series10_video/lane_roles.py，同名不同目录，故本文件带 _producer 后缀避开 K-OPS-Q11 歧义守卫）。出图调度（producer）、视频调度（night / vidgen）、看图路由（vqa client / accept）、空卡巡检（idle_watch）
都只经这里读，不各自解析。

契约（config/pipeline/lane_roles.json，schema 不在这里改）：
    enabled            false = 旧行为（全部道共享，本模块所有 *_allowed 返回 None）
    from_episode       只对 ep ≥ from_episode 的集生效；之前的集（ep01）照旧
    phases.frames      首尾帧阶段：image / review / video 三张表
    phases.videos      视频阶段：image 为空（出图位全部转视频位）
    image_prefetch_depth   出图位每道 ComfyUI 队列深度（L-206：每卡只排 1 个任务）
    review             {vqa_instances, lane, port_base}：审图位 = 一张卡上 N 个 Qwen3-VL nf4 实例 + 人数 / 身份检测
    hold_regen_downstream  某镜首帧换代中（master_reject 未 cleared / redo 在跑）不派它的尾帧 / 视频

阶段（每集一个，从登记表现推，不另存一份真相）：
    frames  本集还有非成人镜的首帧或尾帧没定下（定下 = passed / best_effort（含尾帧 I2VA 回退）/ 不适用 na）
    videos  非成人镜的首尾帧全部定下
    成人镜（adult）不计（只由项目方触发，L-128 不变项）；没导入镜的集 = frames。

状态文件 data/pipeline/lane_roles_state.json（producer 每拍写，视频侧 night / vidgen 读；格式）：
    {
      "_schema": "nsfs.lane_roles_state/1",
      "_updated": "<ISO 本地时间>",
      "<run>": {
        "<ep>": {"phase": "frames" | "videos", "since": "<ISO：进入该阶段的时刻>", "switches": <int：本集切换次数>,
                 "prev": "<上一阶段 | null>", "updated": "<ISO>"}
      }
    }
    以 "_" 开头的键是元数据；按剧 / 集读用 read_phase(run, ep, root)。文件里没有的集 = 不适用 lane_roles（旧行为）。
    多台 producer（gpu33 / gpu36）各自只合并自己推出的集，不互相清空。

L-207（项目方 11-06：“首尾帧一旦做完，下一步就是全部显卡做视频”）——一集严格三段，run 级唯一排序源：
    "<run>": {"_active": {"ep": 2, "phase": "frames" | "videos", "since", "updated", "prev_ep", "switches"} | null, "<ep>": {...}}
    · active = 正在占卡的那一集：最小的、阶段还在 frames / videos 的适用集；粘性——它没到 assembly / done 前不换（旧集回切不抢）。
    · 只有 active 集且 phase=frames 才派首尾帧；下一集的首尾帧等 active 集的视频全部定下（stage → assembly，合成是 CPU，可与下一集首尾帧重叠）。
      成人镜（项目方触发）不计入“定下”，不挡切段。
    · 每集记录另带 settled_n / settled_at（已定下首尾帧的镜数与最近一次变化时刻）：C2 兜底用——
      首尾帧阶段没有可派的首尾帧活（没有 ready / running 的首 / 尾帧）且 ≥1 镜定下 → 直接进 videos；
      或 settled_n 连续 frames_idle_fallback_s（默认 20 min）没变、且没有在跑的首 / 尾帧 → 进 videos（卡住的镜就绪后照常回切）。
    · 阶段切换钩子：写状态的进程（producer）在 active phase 变化时跑 tools/vqa/review_instances.sh scale N
      （N = review.vqa_instances_by_phase[phase]），审图台本机 subprocess / 笔记本 rssh，带超时、幂等、后台线程；失败只记日志，
      调度照用活着的实例。结果记 data/pipeline/review_scale.json。

用法：
    .venv/Scripts/python.exe tools/autopilot/lane_roles_producer.py status        # 配置 + 状态文件
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG_REL = "config/pipeline/lane_roles.json"
STATE_REL = "data/pipeline/lane_roles_state.json"
SCALE_REL = "data/pipeline/review_scale.json"      # L-207：审图实例伸缩钩子的结果（幂等依据）
SCHEMA = "nsfs.lane_roles_state/1"
ROLES = ("image", "review", "video")
PHASES = ("frames", "videos")
STAGES = ("frames", "videos", "assembly", "done")   # L-207：集的三段 + 完成（assembly / done 不占卡）
FRAME_DONE = ("passed", "best_effort")
FRAME_ACTIVE = ("ready", "running")                 # C2：还有可派 / 在跑的首尾帧活（pending = 等上游；failed = 卡死，不算活）
FRAMES_IDLE_S = 1200                                # C2 兜底：定下数 20 min 没变 → 进 videos（config frames_idle_fallback_s 可改）
REVIEW_SCALE_TIMEOUT_S = 300
REVIEW_SCALE_RETRY_S = 600                          # 伸缩失败后多久再试一次（第 1 次）
REVIEW_SCALE_RETRY_MAX_S = 3600                     # W-INFRA 11-06：连续失败翻倍 600 → 1200 → 2400 → 3600 封顶（PS-MASTER：rc=1 每 10 min 刷屏）
BAD_LANES = ("gpu33:2",)            # 坏卡（CLAUDE.md 红线）：配置里写了也剔除


def scale_retry_wait_s(fails: int) -> float:
    """第 fails 次连续失败后等多久再试：600 × 2^(fails-1)，封顶 3600；成功归零"""
    n = max(1, int(fails or 1))
    return float(min(REVIEW_SCALE_RETRY_S * (2 ** (n - 1)), REVIEW_SCALE_RETRY_MAX_S))
REVIEW_PORT_OFFSET = 6              # 审图实例端口 = port_base + 6 + i（8876…）：避开 8871（笔记本隧道）、8873 / 8874（gpu33 打分常驻）


def _j(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):   # arch-ok: 读不出 = 默认（配置缺 = 旧行为；状态缺 = 空）
        return default


def load_cfg(root: Path | None = None) -> dict:
    d = _j(Path(root or ROOT) / CFG_REL, None)
    return d if isinstance(d, dict) else {"enabled": False}


def enabled(cfg: dict) -> bool:
    return bool(cfg.get("enabled"))


def from_episode(cfg: dict) -> int:
    try:
        return max(1, int(cfg.get("from_episode") or 1))
    except (TypeError, ValueError):
        return 1


def applies(cfg: dict, ep) -> bool:
    """这一集归 lane_roles 管吗（enabled 且 ep ≥ from_episode）"""
    try:
        return enabled(cfg) and int(ep) >= from_episode(cfg)
    except (TypeError, ValueError):
        return False


def lanes_for(cfg: dict, phase: str, role: str) -> list[str]:
    tbl = ((cfg.get("phases") or {}).get(phase) or {}).get(role) or []
    return [str(ln) for ln in tbl if str(ln) not in BAD_LANES]


def role_of(cfg: dict, phase: str, lane: str) -> set[str]:
    return {r for r in ROLES if lane in lanes_for(cfg, phase, r)}


def review_lane(cfg: dict) -> str:
    ln = str((cfg.get("review") or {}).get("lane") or "")
    if not ln:
        rl = lanes_for(cfg, "frames", "review")
        ln = rl[0] if rl else ""
    return "" if ln in BAD_LANES else ln


def review_host(cfg: dict) -> str:
    return review_lane(cfg).split(":", 1)[0]


def review_gpu(cfg: dict) -> int | None:
    ln = review_lane(cfg)
    try:
        return int(ln.split(":", 1)[1]) if ":" in ln else None
    except ValueError:
        return None


def review_instances(cfg: dict) -> int:
    """审图实例上限（端口数 / 首尾帧阶段的实例数）"""
    try:
        return max(1, int((cfg.get("review") or {}).get("vqa_instances") or 1))
    except (TypeError, ValueError):
        return 1


def vqa_instances_for(cfg: dict, phase: str) -> int:
    """L-207：该阶段该开几个看图实例——review.vqa_instances_by_phase[phase]（frames 3 / videos 1）；没配 = vqa_instances；不超上限"""
    by = (cfg.get("review") or {}).get("vqa_instances_by_phase") or {}
    try:
        n = int(by.get(phase)) if by.get(phase) is not None else review_instances(cfg)
    except (TypeError, ValueError):
        n = review_instances(cfg)
    return max(1, min(review_instances(cfg), n))


def frames_idle_fallback_s(cfg: dict) -> float:
    try:
        return max(60.0, float(cfg.get("frames_idle_fallback_s") or FRAMES_IDLE_S))
    except (TypeError, ValueError):
        return float(FRAMES_IDLE_S)


def review_ports(cfg: dict) -> dict:
    """{router: 8870, instances: [8876, 8877, 8878]}：分发器占 port_base（client 不用改），实例从 port_base+6 起连号"""
    try:
        base = int((cfg.get("review") or {}).get("port_base") or 8870)
    except (TypeError, ValueError):
        base = 8870
    return {"router": base, "instances": [base + REVIEW_PORT_OFFSET + i for i in range(review_instances(cfg))]}


_RESIDENT_CACHE: dict = {}
REVIEW_RESIDENT_TTL_S = 30


def review_probe_urls(cfg: dict) -> list[str]:
    """看图进程驻留探测地址（/health）：审图台本机 → 127.0.0.1 的分发器 + 各实例口；笔记本 → review.laptop_probe_urls
    （默认 http://127.0.0.1:8871/health，tunnels.json gpu36-vqa 8871 → gpu33:8870）；别的服务器 → review.lan_url（10.0.0.33:8870）"""
    r = cfg.get("review") or {}
    me = os.environ.get("NS_FACTORY_HOST") or os.environ.get("OFFLINE_SELF") or ""
    host = review_host(cfg)
    if me and me == host:
        ports = review_ports(cfg)
        return [f"http://127.0.0.1:{ports['router']}/health"] + [f"http://127.0.0.1:{p}/health" for p in ports["instances"]]
    if me:
        u = str(r.get("lan_url") or "").rstrip("/")
        return [u + "/health"] if u else []
    return [str(u) for u in (r.get("laptop_probe_urls") or ["http://127.0.0.1:8871/health"])]


def review_resident(cfg: dict, now: float | None = None, probe=None, ttl_s: float = REVIEW_RESIDENT_TTL_S) -> bool:
    """审图卡上此刻是否有看图进程驻留（分发器或任一实例 /health 应答 = 驻留，不管它加载没加载——懒加载实例来单就要 7.5 GB）。
    PS-MASTER 11-06 20:41 实况：ep01（不归 lane_roles 管，from_episode=2）的 last:ep01-S8 被派到 gpu33:3 出图 → 看图实例 CUDA OOM。
    规则：看图进程在卡上就不往这张卡派出图单，不管空闲兜底怎么说。探测结果缓存 ttl_s；探不到 / 出错 = 不驻留（不挡）"""
    t = time.time() if now is None else now
    key = review_lane(cfg)
    c = _RESIDENT_CACHE.get(key)
    if c and t - c["t"] < ttl_s:
        return c["resident"]
    urls = review_probe_urls(cfg)
    res = False
    for u in urls:
        try:
            if probe is not None:
                ok = bool(probe(u))
            else:
                import urllib.request
                with urllib.request.urlopen(u, timeout=2) as r:
                    ok = 200 <= r.status < 500
        except Exception:  # noqa: BLE001  # arch-ok: 探不到 = 该口没进程
            ok = False
        if ok:
            res = True
            break
    _RESIDENT_CACHE[key] = {"t": t, "resident": res, "urls": urls}
    return res


def block_renders_when_resident(cfg: dict) -> bool:
    v = (cfg.get("review") or {}).get("block_renders_when_resident")
    return True if v is None else bool(v)


def lanes_minus_resident_review(lanes, cfg: dict, now: float | None = None, probe=None) -> tuple[list, str | None]:
    """→ (去掉驻留审图卡后的道, 被去掉的道 | None)。lane_roles 关 / 没配审图道 / 开关关 / 没驻留 → 原样"""
    ln = review_lane(cfg) if isinstance(cfg, dict) else ""
    lanes = list(lanes)
    if not ln or not enabled(cfg) or not block_renders_when_resident(cfg) or ln not in lanes:
        return lanes, None
    if not review_resident(cfg, now=now, probe=probe):
        return lanes, None
    return [x for x in lanes if x != ln], ln


def image_prefetch_depth(cfg: dict) -> int:
    try:
        return max(1, min(4, int(cfg.get("image_prefetch_depth") or 1)))
    except (TypeError, ValueError):
        return 1


def hold_regen_downstream(cfg: dict) -> bool:
    return bool(cfg.get("hold_regen_downstream", True))


# ------------------------------------------------------------------ 阶段推导（纯函数，输入 = producer 登记表）
def frame_done(o: dict | None) -> bool:
    """首 / 尾帧“定下”：passed / best_effort（含尾帧 I2VA 回退 last_frame_fallback）/ 不适用 na"""
    o = o or {}
    return o.get("status") in FRAME_DONE or bool(o.get("na"))


def shot_frames_done(S: dict) -> bool:
    ob = S.get("objects") or {}
    return frame_done(ob.get("first")) and frame_done(ob.get("last"))


def _shots(E: dict, adult: set | None) -> list:
    return [S for S in (E.get("shots") or []) if S.get("shot") not in (adult or set())]


def settled_count(E: dict, adult: set | None = None) -> int:
    return sum(1 for S in _shots(E, adult) if shot_frames_done(S))


def frame_work_left(E: dict, adult: set | None = None) -> dict:
    """C2：本集还有没有可派 / 在跑的首尾帧活 {"ready": n, "running": n}（只数没定下的镜的首 / 尾帧）"""
    out = {"ready": 0, "running": 0}
    for S in _shots(E, adult):
        ob = S.get("objects") or {}
        for k in ("first", "last"):
            o = ob.get(k) or {}
            if frame_done(o):
                continue
            if o.get("status") in out:
                out[o["status"]] += 1
    return out


def episode_phase(E: dict, adult: set | None = None, prev: dict | None = None, now: float | None = None,
                  idle_s: float = FRAMES_IDLE_S) -> str:
    """集的阶段（L-206 + C2 兜底）：
    videos = 非成人镜首尾帧全部定下；
    或（C2）≥1 镜定下 且 没有 ready / running 的首尾帧（其余都在等上游 / 卡死 → 首尾帧阶段没活可干，不该让 5 张卡等）；
    或（C2 时间兜底）≥1 镜定下 且 定下数连续 idle_s 没变 且 没有在跑的首尾帧（ready 但被闸门 / 限速挡住的算卡住）。
    prev = 状态文件里本集记录（settled_n / settled_at）；没有 = 不用时间兜底。卡住的镜之后真的出图 / 定下 → 回切 frames（计次、记日志）"""
    shots = _shots(E, adult)
    if not shots:
        return "frames"
    n_done = settled_count(E, adult)
    if n_done >= len(shots):
        return "videos"
    if n_done == 0:
        return "frames"
    left = frame_work_left(E, adult)
    if left["ready"] == 0 and left["running"] == 0:
        return "videos"
    if prev and left["running"] == 0 and int(prev.get("settled_n") or 0) == n_done and prev.get("settled_at"):
        t = time.time() if now is None else now
        if t - float(prev["settled_at"]) >= idle_s:
            return "videos"
    return "frames"


def video_done(o: dict | None) -> bool:
    o = o or {}
    return o.get("status") in FRAME_DONE or bool(o.get("na"))


def episode_videos_settled(E: dict, adult: set | None = None) -> bool:
    shots = _shots(E, adult)
    return bool(shots) and all(video_done((S.get("objects") or {}).get("video")) for S in shots)


def episode_stage(E: dict, adult: set | None = None, prev: dict | None = None, now: float | None = None,
                  idle_s: float = FRAMES_IDLE_S) -> str:
    """L-207 三段：frames → videos → assembly（视频全定下，合成中 / 等合成，不占卡）→ done（成片已出）。
    有镜但全是成人镜 = done（没活）；没导入镜 = frames（等导入，按集序排队）"""
    if (E.get("shots") or []) and not _shots(E, adult):
        return "done"
    ph = episode_phase(E, adult, prev, now, idle_s)
    if ph != "videos" or not episode_videos_settled(E, adult):
        return ph
    asm = ((E.get("objects") or {}).get("assembly") or {})
    return "done" if asm.get("status") == "passed" else "assembly"


def episode_phases(reg: dict, cfg: dict, adult: set | None = None, prev: dict | None = None, now: float | None = None) -> dict[int, str]:
    """{ep: phase}，只含 applies 的集；prev = 状态文件里本剧的记录 {ep: rec}（C2 时间兜底）"""
    out = {}
    idle = frames_idle_fallback_s(cfg)
    for E in reg.get("episodes") or []:
        try:
            ep = int(E.get("ep"))
        except (TypeError, ValueError):
            continue
        if applies(cfg, ep):
            out[ep] = episode_phase(E, adult, (prev or {}).get(str(ep)) if isinstance(prev, dict) else None, now, idle)
    return apply_override(out, reg.get("run"), now)


OVERRIDE_REL = "data/pipeline/lane_roles_override.json"     # BRAIN-FW：大脑的阶段覆盖（带到期；tools/brain/actions.py lane_roles_phase_override 写）


def read_override(run, root: Path | None = None, now: float | None = None) -> dict[int, str]:
    """{ep: phase}：data/pipeline/lane_roles_override.json[run][ep] = {phase, expires_at}；过期 / 坏值 = 不覆盖（失败关闭）"""
    d = _j(Path(root or ROOT) / OVERRIDE_REL, None)
    recs = (d or {}).get(str(run)) if isinstance(d, dict) and run else None
    out = {}
    now = time.time() if now is None else now
    for ep, rec in (recs or {}).items():
        if not isinstance(rec, dict) or rec.get("phase") not in PHASES:
            continue
        try:
            from datetime import datetime
            exp = datetime.fromisoformat(str(rec.get("expires_at")).replace(" ", "T")).timestamp()
            if exp <= now:
                continue
            out[int(ep)] = rec["phase"]
        except (TypeError, ValueError):
            continue
    return out


def apply_override(phases: dict, run, now: float | None = None, root: Path | None = None) -> dict:
    """只覆盖 phases 里已有（applies）的集"""
    for ep, ph in read_override(run, root, now).items():
        if ep in phases:
            phases[ep] = ph
    return phases


def episode_stages(reg: dict, cfg: dict, adult: set | None = None, prev: dict | None = None, now: float | None = None) -> dict[int, str]:
    """{ep: stage}（frames / videos / assembly / done），只含 applies 的集；大脑的阶段覆盖（apply_override）对 frames / videos 两段同样生效"""
    out = {}
    idle = frames_idle_fallback_s(cfg)
    for E in reg.get("episodes") or []:
        try:
            ep = int(E.get("ep"))
        except (TypeError, ValueError):
            continue
        if applies(cfg, ep):
            out[ep] = episode_stage(E, adult, (prev or {}).get(str(ep)) if isinstance(prev, dict) else None, now, idle)
    for ep, ph in read_override(reg.get("run"), None, now).items():
        if out.get(ep) in ("frames", "videos"):
            out[ep] = ph
    return out


def settled_counts(reg: dict, cfg: dict, adult: set | None = None) -> dict[int, int]:
    out = {}
    for E in reg.get("episodes") or []:
        try:
            ep = int(E.get("ep"))
        except (TypeError, ValueError):
            continue
        if applies(cfg, ep):
            out[ep] = settled_count(E, adult)
    return out


def active_episode(stages: dict, prev_active: dict | None = None) -> dict | None:
    """L-207 run 级 active 集：阶段还在 frames / videos 的最小适用集；粘性——上一拍的 active 集还没到 assembly / done 就继续是它
    （旧集首帧换代回切不抢在跑的集；它排到后面再做）。None = 没有集在占卡（全部 assembly / done / 没有适用集）"""
    busy = {int(e): s for e, s in (stages or {}).items() if s in ("frames", "videos")}
    if not busy:
        return None
    pe = (prev_active or {}).get("ep")
    try:
        pe = int(pe) if pe is not None else None
    except (TypeError, ValueError):
        pe = None
    ep = pe if pe in busy else min(busy)
    return {"ep": ep, "phase": busy[ep], "stages": {str(k): v for k, v in sorted((stages or {}).items(), key=lambda kv: int(kv[0]))}}


def first_in_regen(fo: dict | None, sid: str, rejects: dict | None = None) -> bool:
    """首帧在换代 / 驳回重出中：登记对象带 redo / regen，或 master_rejects[first:<sid>] 还没 cleared"""
    fo = fo or {}
    if fo.get("redo") or fo.get("regen"):
        return True
    rj = (rejects or {}).get(f"first:{sid}") or {}
    return bool(rj) and not rj.get("cleared")


def apply_hold_regen(reg: dict, cfg: dict, rejects: dict | None = None) -> list[str]:
    """L-206 hold_regen_downstream：适用集里首帧换代中的镜，ready 的尾帧改 pending（waiting_for 写明），不派。→ 被扣住的镜号"""
    held = []
    if not hold_regen_downstream(cfg):
        return held
    for E in reg.get("episodes") or []:
        if not applies(cfg, E.get("ep")):
            continue
        for S in E.get("shots") or []:
            ob = S.get("objects") or {}
            fo, lo = ob.get("first") or {}, ob.get("last") or {}
            sid = S.get("shot") or ""
            if lo.get("status") != "ready" or lo.get("na") or not first_in_regen(fo, sid, rejects):
                continue
            lo.update(status="pending", hold_regen=True,
                      waiting_for="首帧换代中（L-206 hold_regen_downstream）：等新首帧定下再出尾帧",
                      reason="首帧 " + str(fo.get("reason") or "驳回 / 换代重出中") + "；尾帧不跟着白跑（L-206）")
            held.append(sid)
    return held


# ------------------------------------------------------------------ 状态文件
def _iso(t: float | None = None) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t if t is not None else time.time()))


def read_state(root: Path | None = None) -> dict:
    d = _j(Path(root or ROOT) / STATE_REL, None)
    return d if isinstance(d, dict) else {}


def read_phase(run: str, ep, root: Path | None = None) -> str | None:
    """视频侧读：None = 该集不归 lane_roles 管（旧行为）"""
    rec = ((read_state(root).get(str(run)) or {}).get(str(int(ep))) or {}) if run else {}
    ph = rec.get("phase")
    return ph if ph in PHASES else None


def read_active(run: str, root: Path | None = None) -> dict | None:
    """L-207 run 级 active 集 {ep, phase, since, ...}；没有 / null = 没有集在占卡（或不适用）"""
    a = ((read_state(root).get(str(run)) or {}).get("_active")) if run else None
    if not isinstance(a, dict) or a.get("phase") not in PHASES:
        return None
    try:
        return {**a, "ep": int(a.get("ep"))}
    except (TypeError, ValueError):
        return None


def write_state(root: Path | None, run: str, phases: dict, t: float | None = None, log=None,
                active: dict | None = None, settled: dict | None = None, stages: dict | None = None) -> dict:
    """按集合并写入（只动本次推出的集；since 在阶段不变时保留；切换计次 + 回切记日志）。→ 写入后的整份状态。
    L-207：active（run 级 {ep, phase}；None = 写 null）、settled（{ep: 已定下镜数}，变化时更新 settled_n / settled_at）、stages（{ep: 段}）"""
    root = Path(root or ROOT)
    t = t if t is not None else time.time()
    st = read_state(root)
    runs = st.setdefault(str(run), {})
    if not isinstance(runs, dict):
        runs = st[str(run)] = {}
    changed = False
    for ep, ph in sorted(phases.items(), key=lambda kv: int(kv[0])):
        k = str(int(ep))
        old = runs.get(k) if isinstance(runs.get(k), dict) else None
        sn = (settled or {}).get(int(ep), (settled or {}).get(k))
        stg = (stages or {}).get(int(ep), (stages or {}).get(k))
        if old and old.get("phase") == ph:
            if sn is not None and int(old.get("settled_n") if old.get("settled_n") is not None else -1) != int(sn):
                old.update(settled_n=int(sn), settled_at=t, updated=_iso(t))
                changed = True
            if stg and old.get("stage") != stg:
                old.update(stage=stg, updated=_iso(t))
                changed = True
            continue
        rec = {"phase": ph, "since": _iso(t), "switches": int((old or {}).get("switches") or 0) + (1 if old else 0),
               "prev": (old or {}).get("phase"), "updated": _iso(t)}
        if sn is not None:
            keep = old and int(old.get("settled_n") if old.get("settled_n") is not None else -1) == int(sn) and old.get("settled_at")
            rec.update(settled_n=int(sn), settled_at=old["settled_at"] if keep else t)
        if stg:
            rec["stage"] = stg
        runs[k] = rec
        changed = True
        if log:
            try:
                log("lane_roles_phase", run=run, ep=int(ep), phase=ph, prev=rec["prev"], switches=rec["switches"], counted=False,
                    note=("回切（首帧换代 / 作废重出）" if rec["prev"] == "videos" and ph == "frames" else None))
            except Exception:  # noqa: BLE001  # arch-ok: 日志失败不影响状态文件
                pass
    # L-207 run 级 active：{ep, phase} 变了才改 since / 计次；None = 没有集在占卡
    olda = runs.get("_active") if isinstance(runs.get("_active"), dict) else None
    if active is None:
        if olda is not None or "_active" not in runs:
            runs["_active"] = None
            changed = True
            if olda and log:
                try:
                    log("lane_roles_active", run=run, ep=None, phase=None, prev_ep=olda.get("ep"), counted=False, note="没有集在占卡（全部进合成 / 完成）")
                except Exception:  # noqa: BLE001  # arch-ok: 日志失败不影响状态文件
                    pass
    else:
        key = (int(active["ep"]), active["phase"])
        if not olda or (olda.get("ep"), olda.get("phase")) != key:
            runs["_active"] = {"ep": key[0], "phase": key[1], "since": _iso(t), "updated": _iso(t),
                               "prev_ep": (olda or {}).get("ep"), "prev_phase": (olda or {}).get("phase"),
                               "switches": int((olda or {}).get("switches") or 0) + (1 if olda else 0),
                               "stages": active.get("stages") or {}}
            changed = True
            if log:
                try:
                    log("lane_roles_active", run=run, ep=key[0], phase=key[1], prev_ep=(olda or {}).get("ep"),
                        prev_phase=(olda or {}).get("phase"), counted=False, rule="L-207")
                except Exception:  # noqa: BLE001  # arch-ok: 日志失败不影响状态文件
                    pass
        elif (active.get("stages") or {}) != (olda.get("stages") or {}):
            olda.update(stages=active.get("stages") or {}, updated=_iso(t))
            changed = True
    if not changed and st.get("_schema") == SCHEMA:
        return st
    st["_schema"] = SCHEMA
    st["_updated"] = _iso(t)
    p = root / STATE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return st


def lanes_now(cfg: dict, phases: dict, ep, role: str, active: dict | None = None) -> list[str] | None:
    """这一集此刻 role 可用的道；None = 不归 lane_roles 管（旧行为：全部道）。
    L-207：给了 active（run 级占卡集）→ 出图道只给 active 集且它在 frames 阶段；别的适用集 = []（等它的视频全定下）"""
    if not applies(cfg, ep):
        return None
    if active is not None:
        if int(ep) != int(active["ep"]):
            return [] if role == "image" else lanes_for(cfg, active["phase"], role)
        return lanes_for(cfg, active["phase"], role)
    return lanes_for(cfg, phases.get(int(ep), "frames"), role)


def wait_reason(active: dict | None, ep) -> str:
    """lane_roles_wait 日志 / 登记表用的人话"""
    if not active:
        return "不归 lane_roles 管"
    if int(ep) != int(active["ep"]):
        return f"L-207 严格分段：等 ep{int(active['ep']):02d} {active['phase']} 段结束（视频全定下）再出本集首尾帧"
    return "L-206 视频阶段：出图位已转视频位" if active["phase"] == "videos" else "等空闲出图位"


def asset_lane_policy(cfg: dict, active: dict | None) -> dict:
    """C1：资产作业（asset_worker）此刻能借的道 {"allow": [道] | None（= 不限）, "deny": [道], "why"}。
    关 = 不限 / 不禁（旧行为：全部 image 道）。开：审图位永不借（不往 gpu33:3 放出图模型）；
    有集在占卡 → frames 段只能用 frames.image 道，videos 段 allow=[]（视频卡不借给资产，等这一段过去）；没有集在占卡 → 只禁审图位"""
    if not enabled(cfg):
        return {"allow": None, "deny": [], "why": "lane_roles 关"}
    review = sorted((set(lanes_for(cfg, "frames", "review")) | set(lanes_for(cfg, "videos", "review")) | {review_lane(cfg)}) - {""})
    if active is None:
        return {"allow": None, "deny": review, "why": "没有集在占卡：只禁审图位"}
    if active["phase"] == "frames":
        return {"allow": [ln for ln in lanes_for(cfg, "frames", "image") if ln not in review], "deny": review,
                "why": f"ep{int(active['ep']):02d} 首尾帧段：只借出图位"}
    return {"allow": [], "deny": review, "why": f"ep{int(active['ep']):02d} 视频段：全卡出视频，资产等（L-207）"}


# ------------------------------------------------------------------ L-207 审图实例伸缩钩子（阶段切换时跑 review_instances.sh scale N）
_SCALE_LOCK = threading.Lock()
_SCALE_THREADS: dict = {}


def read_scale(root: Path | None = None) -> dict:
    d = _j(Path(root or ROOT) / SCALE_REL, None)
    return d if isinstance(d, dict) else {}


def _write_scale(root: Path, rec: dict) -> None:
    p = Path(root) / SCALE_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(rec, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def review_scale_cmd(cfg: dict, n: int, repo: str | None = None) -> str:
    rp = (repo or ".").rstrip("/")
    return f"cd {rp} && bash tools/vqa/review_instances.sh scale {int(n)}"


def _remote_repo(host: str, root: Path) -> str:
    d = _j(root / "config" / "factory" / "hosts.json", {}) or {}
    return str(((d.get("hosts") or {}).get(host) or {}).get("repo") or ".")


def default_scale_runner(cfg: dict, root: Path, n: int, timeout_s: float) -> tuple[int, str]:
    """审图台本机（OFFLINE_SELF == review host）→ 本机 bash；笔记本（没有 OFFLINE_SELF）→ rssh.run_retry；别的服务器 → 不跑（rc=-2，服务器间无互信）"""
    host = review_host(cfg)
    me = os.environ.get("OFFLINE_SELF") or ""
    if me and me != host:
        return -2, f"本机 {me} 不是审图台 {host}，伸缩由审图台 / 笔记本做"
    if me == host:
        try:
            r = subprocess.run(["bash", "tools/vqa/review_instances.sh", "scale", str(int(n))], cwd=str(root), capture_output=True,
                               text=True, timeout=timeout_s, env={**os.environ, "NS_REPO": str(root)})
            return r.returncode, (r.stdout + r.stderr)[-1500:]
        except (OSError, subprocess.TimeoutExpired) as e:
            return -3, f"{type(e).__name__}: {e}"[:300]
    sys.path.insert(0, str(root / "tools" / "netfix"))
    import rssh  # noqa: PLC0415
    r = rssh.run_retry(host, review_scale_cmd(cfg, n, _remote_repo(host, root)), timeout=timeout_s, tries=2)
    out = r.stdout if isinstance(r.stdout, str) else (r.stdout or b"").decode("utf-8", "replace")
    err = r.stderr if isinstance(r.stderr, str) else (r.stderr or b"").decode("utf-8", "replace")
    return int(r.returncode), (out + err)[-1500:]


def review_scale_tick(cfg: dict, root: Path | None, phase: str | None, log=None, runner=None, now: float | None = None,
                      wait: bool = False) -> dict | None:
    """阶段钩子（幂等、不阻塞、不抛）：want = vqa_instances_by_phase[phase]；和上次成功应用的一样 → 不动；在跑 → 不动；
    上次失败 → REVIEW_SCALE_RETRY_S 后再试。跑在后台线程（wait=True 测试用同步）；结果写 data/pipeline/review_scale.json
    {want, phase, started, done, rc, tail, ok}。rc≠0 只记日志——调度照用活着的实例（client 按 /health 挑）。
    关 / 没配 by_phase / phase=None → None"""
    try:
        if not enabled(cfg) or phase not in PHASES or not (cfg.get("review") or {}).get("vqa_instances_by_phase"):
            return None
        if (cfg.get("review_scale") or {}).get("enabled") is False:
            return None
        root = Path(root or ROOT)
        t = time.time() if now is None else now
        want = vqa_instances_for(cfg, phase)
        rec = read_scale(root)
        with _SCALE_LOCK:
            th = _SCALE_THREADS.get(str(root))
            if th is not None and th.is_alive():
                return {"skipped": "running", "want": want}
            if rec.get("want") == want and rec.get("ok"):
                return {"skipped": "already", "want": want}
            prev_fails = int(rec.get("fails") or 0) if rec.get("want") == want and rec.get("done") and not rec.get("ok") else 0
            if prev_fails and t - float(rec.get("done_t") or 0) < scale_retry_wait_s(prev_fails):
                return {"skipped": "retry_wait", "want": want, "fails": prev_fails, "wait_s": scale_retry_wait_s(prev_fails)}
            timeout_s = float((cfg.get("review_scale") or {}).get("timeout_s") or REVIEW_SCALE_TIMEOUT_S)
            rec = {"want": want, "phase": phase, "started": _iso(t), "started_t": t, "done": None, "rc": None, "ok": False, "tail": "",
                   "fails": prev_fails}
            _write_scale(root, rec)

            def job():
                try:
                    rc, tail = (runner or default_scale_runner)(cfg, root, want, timeout_s)
                except Exception as e:  # noqa: BLE001  # arch-ok: 伸缩钩子任何异常只记结果，不影响 producer
                    rc, tail = -1, repr(e)[:300]
                t2 = time.time()
                rec.update(done=_iso(t2), done_t=t2, rc=rc, ok=(rc == 0), tail=str(tail)[-1500:],
                           fails=0 if rc == 0 else int(rec.get("fails") or 0) + 1)   # W-INFRA 11-06：连续失败次数 → 重试间隔翻倍（刷屏止血）
                try:
                    _write_scale(root, rec)
                except OSError:
                    pass
                if log:
                    try:
                        log("review_scale", phase=phase, want=want, rc=rc, ok=(rc == 0), tail=str(tail)[-300:], counted=False, rule="L-207")
                    except Exception:  # noqa: BLE001  # arch-ok: 日志失败不影响
                        pass
            th = threading.Thread(target=job, name=f"review_scale_{want}", daemon=True)
            _SCALE_THREADS[str(root)] = th
            th.start()
        if wait:
            th.join(timeout_s + 5)
        return {"launched": True, "want": want, "phase": phase}
    except Exception as e:  # noqa: BLE001  # arch-ok: 钩子出错 = 不伸缩（用活着的实例），记日志
        if log:
            try:
                log("review_scale_err", error=repr(e)[:200], counted=False)
            except Exception:  # noqa: BLE001
                pass
        return {"error": repr(e)[:200]}


def main(argv=None) -> int:
    cfg = load_cfg()
    print(json.dumps({"cfg": {k: v for k, v in cfg.items() if not k.startswith("_")}, "review_ports": review_ports(cfg),
                      "state": read_state(), "review_scale": read_scale()}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
