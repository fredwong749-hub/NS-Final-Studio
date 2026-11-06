"""L-206 工位分卡（项目方 11-06）——视频侧读者。唯一来源 config/pipeline/lane_roles.json：每条道一个角色
（image 出图 / review 审图 / video 视频），按本集阶段（frames 首尾帧阶段 / videos 视频阶段）取表。

本模块只做三件事，全部纯函数 + 只读：
  1. 阶段：先读 producer（LANE-ROLES-PROD）写的 data/pipeline/lane_roles_state.json {run: {ep: {phase, since}}}；
     没有这份文件（视频机上 data/pipeline 顶层不同步）就按同一口径自己算：本集每镜 首帧 + 尾帧 都已定下
     （takes.json 当前版本过契约 / 尽力采用，或 registry passed / best_effort，或尾帧回退 last_frame_fallback=i2va）
     → videos；否则 frames。
  2. 道：phase + role → 道清单；给 night 的控制文件算 video_lanes（专用视频道，不受让道 yield）/ hold_lanes（本机非视频道）。
  3. hold_regen_downstream：某镜首帧在换代（takes.json master_gate.image 还挂着、当前首帧没换成闸门之后的新版；或
     master_rejects.json first:<镜> 未 cleared 且 regen / 比当前首帧新）→ 该镜视频不派（build_jobs 按镜 hold）。
     这两个信号在视频机上都有：takes.json 由 resident_sync W46 relay 合并同步（master_gate 随出图机那份走），
     master_rejects.json 由 push_control 按对象合并推到两台。

enabled=false 或 ep < from_episode = 旧行为（所有函数返回“不适用”：lanes 为 None / holds 为空 / 阶段 None）。
坏卡 gpu33:2 永不出现（配置里没有；这里也不生成）。
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))   # run_ctx（同目录）
CONFIG = ROOT / "config" / "pipeline" / "lane_roles.json"
STATE = ROOT / "data" / "pipeline" / "lane_roles_state.json"
PHASES = ("frames", "videos")
ROLES = ("image", "review", "video")
# 本机全部道（和 vidgen.PORTS 同一张表；config/factory/hosts.json 读得到就以它为准）
HOST_LANES = {"gpu33": ["gpu33:0", "gpu33:1", "gpu33:3"], "gpu36": ["gpu36:0", "gpu36:1", "gpu36:2"]}
BROKEN = {"gpu33:2"}
DONE_FRAME = ("passed", "best_effort")


def load(path: Path | None = None) -> dict:
    """读不到 / 坏 / 不是对象 = 关（失败关闭到旧行为：全部道共享）"""
    try:
        d = json.loads(Path(path or CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 配置读不到 = 工位分卡关（旧行为），不凭空分卡
        return {"enabled": False}
    return d if isinstance(d, dict) else {"enabled": False}


def applies(ep: int | None, cfg: dict | None = None) -> bool:
    """这一集走不走工位分卡：enabled 且 ep ≥ from_episode（L-206：ep01 不中途改调度）"""
    cfg = load() if cfg is None else cfg
    if not cfg.get("enabled") or ep is None:
        return False
    try:
        return int(ep) >= int(cfg.get("from_episode") or 1)
    except (TypeError, ValueError):
        return False


def lanes(phase: str, role: str, cfg: dict | None = None) -> list[str]:
    """phase + role → 道清单（去坏卡、去重、保序）；没配 = []"""
    cfg = load() if cfg is None else cfg
    raw = (((cfg.get("phases") or {}).get(phase) or {}).get(role) or [])
    return [str(x) for x in dict.fromkeys(raw) if str(x) not in BROKEN]


def hosts_with(phase: str, role: str, cfg: dict | None = None) -> set[str]:
    return {x.split(":")[0] for x in lanes(phase, role, cfg)}


def host_lanes(host: str, hosts_file: Path | None = None) -> list[str]:
    """本机全部道：config/factory/hosts.json（enabled 的）→ 读不到用 HOST_LANES"""
    try:
        h = json.loads(Path(hosts_file or ROOT / "config/factory/hosts.json").read_text(encoding="utf-8"))["hosts"][host]
        out = [n for n, v in (h.get("lanes") or {}).items() if v.get("enabled", True)]
    except (OSError, ValueError, KeyError, TypeError):   # arch-ok: 车道表读不到 = 用内置表（同 vidgen.PORTS）
        out = list(HOST_LANES.get(host) or [])
    return [x for x in out if x not in BROKEN]


# ---------------------------------------------------------------- 阶段
_RP_MOD = None


def _run_phase_central(run: str) -> dict | None:
    """L-209 S2.4：run_phase=enforce 且笔记本推来的中心 run_phase.json 新鲜 → 它；否则 None（照旧读本机 lane_roles_state / 自算）"""
    global _RP_MOD
    try:
        if _RP_MOD is None:
            import importlib.util
            sp = importlib.util.spec_from_file_location("ns_run_phase_lr", Path(__file__).resolve().parents[1] / "autopilot" / "run_phase.py")
            m = importlib.util.module_from_spec(sp)
            sp.loader.exec_module(m)
            _RP_MOD = m
        return _RP_MOD.enforced(run, ROOT, log=_rp_log, actor="night")
    except Exception as e:  # noqa: BLE001  # arch-ok: 中心阶段读不了 = 旧行为（本机），原因记一行
        _rp_log("run_phase_fallback", run=run, why=f"run_phase 模块读不了 {e!r}"[:200])
        return None


_RP_LOGGED = {"t": 0.0}


def _rp_log(ev: str, **k) -> None:
    """退回本机自算的原因：每 10 分钟最多一行到 stderr（night.log）"""
    if time.time() - _RP_LOGGED["t"] < 600:
        return
    _RP_LOGGED["t"] = time.time()
    print(f"LANE_ROLES {ev} {json.dumps(k, ensure_ascii=False)}", file=sys.stderr, flush=True)


def phase_from_state(run: str, ep: int, path: Path | None = None) -> str | None:
    """producer 写的阶段表；没有 / 坏 / 没这一集 / 值不合法 = None（调用方自己算）。
    L-209 S2.4：不给 path 时先认笔记本算的中心 run_phase.json（enforce 且新鲜）"""
    if path is None:
        c = _run_phase_central(run)
        if c is not None:
            ph = (c.get("phases") or {}).get(str(int(ep)))
            if ph in PHASES:
                return ph
    try:
        d = json.loads(Path(path or STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 阶段表没有 = 本模块按 takes / registry 自己算（compute_phase）
        return None
    e = ((d.get(run) or {}) if isinstance(d, dict) else {}).get(str(int(ep)))
    ph = (e or {}).get("phase") if isinstance(e, dict) else e
    return ph if ph in PHASES else None


def active_from_state(run: str, path: Path | None = None) -> dict | None:
    """L-207 run 级占卡集（producer 写的 lane_roles_state.json <run>._active = {ep, phase, ...}）；没有 / null / 不合法 = None。
    有它 = 整个剧此刻只有这一集在占卡：本机视频道按它的阶段取表（不再逐集取“最保守”）。
    L-209 S2.4：不给 path 时先认中心 run_phase.json（enforce 且新鲜；中心说没有集占卡 = None）"""
    if path is None:
        c = _run_phase_central(run)
        if c is not None:
            a = c.get("active")
            if not isinstance(a, dict) or a.get("phase") not in PHASES:
                return None
            try:
                return {"ep": int(a.get("ep")), "phase": a["phase"], "since": a.get("since"), "stages": a.get("stages") or {}}
            except (TypeError, ValueError):
                return None
    try:
        d = json.loads(Path(path or STATE).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 阶段表没有 = 没有 run 级排序（逐集算，旧 L-206 行为）
        return None
    a = ((d.get(run) or {}) if isinstance(d, dict) else {}).get("_active")
    if not isinstance(a, dict) or a.get("phase") not in PHASES:
        return None
    try:
        return {"ep": int(a.get("ep")), "phase": a["phase"], "since": a.get("since"), "stages": a.get("stages") or {}}
    except (TypeError, ValueError):
        return None


def _renders_dir(run: str, root: Path) -> Path:
    try:
        import run_ctx as RC
        return Path(RC.renders_dir(run)) if root == ROOT else root / Path(RC.renders_dir(run)).relative_to(ROOT)
    except Exception:  # noqa: BLE001  # arch-ok: 服务器镜像没有 runs.py = 按 K-OPS-F24 口径拼（非 legacy 剧 = data/renders/<剧>）
        return root / "data" / "renders" / run


def _producer_dir(run: str, root: Path) -> Path:
    return root / "data" / "producer" / "runs" / run


def takes_of(run: str, sid: str, root: Path | None = None) -> dict | None:
    """镜 id epNN-SK → takes.json；没有 / 坏 = None"""
    root = ROOT if root is None else root
    ep, _, s = sid.partition("-")
    try:
        return json.loads((_renders_dir(run, root) / ep / s / "takes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 这一镜没有 takes = 没出过图（阶段按 frames 算，hold 不生效）
        return None


def _active_take(d: dict, stage: str) -> dict | None:
    n = (d.get("active") or {}).get(stage)
    if n is None:
        return None
    return next((t for t in d.get("takes") or [] if t.get("stage") == stage and t.get("n") == n), None)


def _take_ok(t: dict | None) -> bool:
    if not t or t.get("master_reject") or t.get("bad"):
        return False
    pf = t.get("postflight") or t.get("contract") or {}
    return bool(pf.get("ok") or pf.get("review_needed") or t.get("locked"))


def _fallback_i2va(d: dict) -> bool:
    """build_jobs.last_frame_fallbacks 同一口径：顶层或 active.last_frame_fallback；{mode, first_n} 绑定首帧，首帧换了就作废"""
    v = d.get("last_frame_fallback") or (d.get("active") or {}).get("last_frame_fallback")
    if isinstance(v, dict):
        fa = (d.get("active") or {}).get("image")
        if v.get("first_n") is not None and fa is not None and v["first_n"] != fa:
            return False
        v = v.get("mode")
    return bool(v)


def registry_status(run: str, ep: int, root: Path | None = None) -> dict[str, dict[str, str]]:
    """producer 登记表 → {镜: {first: 状态, last: 状态}}；没有登记表 / 没这一集 = {}（视频机上登记表不同步，照常为空）"""
    root = ROOT if root is None else root
    out: dict[str, dict[str, str]] = {}
    for p in (_producer_dir(run, root) / "registry.json", root / "data" / "producer" / "registry.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):   # arch-ok: 登记表没有 = 只按 takes 判
            continue
        if d.get("run") not in (None, run):
            continue

        def walk(o):
            if isinstance(o, dict):
                if o.get("kind") in ("first", "last") and o.get("shot") and int(o.get("ep") or 0) == int(ep):
                    out.setdefault(str(o["shot"]), {})[o["kind"]] = str(o.get("status") or "")
                for v in o.values():
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(d.get("episodes"))
        if out:
            break
    return out


def shot_frames_done(run: str, sid: str, root: Path | None = None, reg: dict | None = None) -> tuple[bool, bool, str]:
    """→ (首帧定下, 尾帧定下, 说明)。定下 = takes 当前版本过契约 / 尽力采用（且不在换代中），或 registry passed / best_effort；
    尾帧另认 last_frame_fallback=i2va（尾帧用尽改 I2VA，不再等）"""
    d = takes_of(run, sid, root)
    r = (reg or {}).get(sid) or {}
    first = r.get("first") in DONE_FRAME
    last = r.get("last") in DONE_FRAME
    why = []
    if d:
        if first_under_regen(run, sid, root, d):
            first = False
            why.append("首帧换代中")
        elif _take_ok(_active_take(d, "image")):
            first = True
        if _take_ok(_active_take(d, "last")) or _fallback_i2va(d):
            last = True
    elif not r:
        why.append("没有 takes / 登记")
    return first, last, "；".join(why)


FRAME_ACTIVE = ("ready", "running")     # C2（同 lane_roles_producer.FRAME_ACTIVE）：登记表里还可派 / 在跑的首尾帧
FRAMES_IDLE_S = 1200                     # C2 时间兜底（同 producer 侧；config frames_idle_fallback_s 可改）


def _settle_file(run: str, root: Path | None) -> Path:
    return (ROOT if root is None else root) / "data" / "pipeline" / f"lane_roles_settle_{run}.json"


def _settle_track(run: str, ep: int, n_done: int, root: Path | None, now: float) -> dict:
    """C2 时间兜底的本机记录 {settled_n, settled_at}：定下数变了就刷新时刻（只在没有 producer 阶段表的机器上才会用到）"""
    p = _settle_file(run, root)
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 没有记录 = 从现在开始计
        d = {}
    rec = d.get(str(ep)) if isinstance(d.get(str(ep)), dict) else None
    if not rec or int(rec.get("settled_n") or -1) != n_done:
        rec = {"settled_n": n_done, "settled_at": now}
        d[str(ep)] = rec
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
            tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, p)
        except OSError:
            pass
    return rec


def compute_phase(run: str, ep: int, shot_ids: list[str], root: Path | None = None, cfg: dict | None = None,
                  now: float | None = None) -> tuple[str, dict]:
    """同 producer 口径：本集全部镜 首帧 + 尾帧 都定下 → videos；否则 frames。没有镜清单 = frames（保守：只有 gpu36:2 出视频）。
    C2（镜像 lane_roles_producer.episode_phase）：≥1 镜定下 且 登记表里没有 ready / running 的首尾帧（其余在等上游 / 卡死）→ videos；
    或 定下数连续 frames_idle_fallback_s 没变 且 没有 running → videos。两条都要本机有登记表（没有登记表 = 看不到活，不猜，仍 frames）。
    返回 (阶段, {未定下的镜: 说明})"""
    if not shot_ids:
        return "frames", {"_": "没有镜清单"}
    reg = registry_status(run, ep, root)
    pend = {}
    for sid in shot_ids:
        f, l, why = shot_frames_done(run, sid, root, reg)
        if not (f and l):
            pend[sid] = (("首帧未定 " if not f else "") + ("尾帧未定 " if not l else "") + why).strip()
    if not pend:
        return "videos", pend
    n_done = len(shot_ids) - len(pend)
    if n_done > 0 and reg and all(sid in reg for sid in pend):   # 没定下的镜登记表里都有（没登记 = 看不到它的活，不猜）
        left = {"ready": 0, "running": 0}
        for sid in pend:
            for k in ("first", "last"):
                stt = (reg.get(sid) or {}).get(k)
                if stt in left:
                    left[stt] += 1
        if left["ready"] == 0 and left["running"] == 0:
            pend["_"] = "C2：没有可派 / 在跑的首尾帧活 → videos"
            return "videos", pend
        cfg = load() if cfg is None else cfg
        try:
            idle_s = max(60.0, float(cfg.get("frames_idle_fallback_s") or FRAMES_IDLE_S))
        except (TypeError, ValueError):
            idle_s = float(FRAMES_IDLE_S)
        t = time.time() if now is None else now
        rec = _settle_track(run, ep, n_done, root, t)
        if left["running"] == 0 and t - float(rec.get("settled_at") or t) >= idle_s:
            pend["_"] = f"C2：定下数 {n_done} 连续 {int(idle_s)} s 没变且没有在跑 → videos"
            return "videos", pend
    return "frames", pend


def phase_of(run: str, ep: int, shot_ids: list[str] | None = None, cfg: dict | None = None,
             root: Path | None = None, state_path: Path | None = None) -> str | None:
    """这一集现在的阶段；不适用（关 / ep < from_episode）= None。先读阶段表（L-207：run 级 _active 的集按它的阶段），没有再算"""
    cfg = load() if cfg is None else cfg
    if not applies(ep, cfg):
        return None
    act = active_from_state(run, state_path)
    if act and act["ep"] == int(ep):
        return act["phase"]
    ph = phase_from_state(run, ep, state_path)
    if ph:
        return ph
    return compute_phase(run, ep, list(shot_ids or []), root, cfg)[0]


# ---------------------------------------------------------------- 道（night 控制文件）
def control_lanes(host: str, phase: str, cfg: dict | None = None, hosts_file: Path | None = None) -> dict:
    """本机在该阶段的道：{"video": 本机视频道, "hold": 本机非视频道}（video 为空 = 本机本阶段不出视频，全部挂住）"""
    cfg = load() if cfg is None else cfg
    mine = host_lanes(host, hosts_file)
    vid = [x for x in lanes(phase, "video", cfg) if x in mine]
    return {"video": vid, "hold": [x for x in mine if x not in vid]}


def host_can_video(host: str, phase: str, cfg: dict | None = None) -> bool:
    return bool(lanes(phase, "video", cfg)) and host in hosts_with(phase, "video", cfg)


# ---------------------------------------------------------------- hold_regen_downstream
def first_under_regen(run: str, sid: str, root: Path | None = None, d: dict | None = None) -> str | None:
    """首帧是否在换代 / 被驳回重出中（视频机本地信号）→ 原因串；不在 = None。
    ① takes.json master_gate.image 还挂着（producer D7 cleared 时才撤），且当前首帧不是闸门之后换上的新版
       （没有当前版 / 当前版被驳回 / 当前版 created_at < gate.at）；
    ② master_rejects.json first:<镜> 未 cleared，且 regen 或 at 比当前首帧新。
    当前首帧已是闸门之后换上的、过契约的新版 = 换代完成（即使 gate 还没撤），不 hold"""
    root = ROOT if root is None else root
    d = takes_of(run, sid, root) if d is None else d
    if not d:
        return None
    cur = _active_take(d, "image")
    cur_at = str((cur or {}).get("created_at") or "")
    cur_ok = _take_ok(cur)
    g = (d.get("master_gate") or {}).get("image")
    if isinstance(g, dict) and not (cur_ok and cur_at and cur_at >= str(g.get("at") or "")):
        return f"首帧换代中（takes.json master_gate.image {g.get('at') or ''} {str(g.get('reason') or '')[:60]}）"
    for p in (_producer_dir(run, root) / "master_rejects.json", root / "data" / "producer" / "master_rejects.json"):
        try:
            rj = json.loads(p.read_text(encoding="utf-8")).get(f"first:{sid}")
        except (OSError, ValueError, AttributeError):   # arch-ok: 驳回表没有 = 只看 takes.json 的 master_gate
            continue
        if not isinstance(rj, dict) or rj.get("cleared"):
            continue
        at = str(rj.get("at") or "")
        if rj.get("regen") or not (cur_ok and cur_at and cur_at >= at):
            return f"首帧换代中（master_rejects first:{sid} {at} {'regen' if rj.get('regen') else '未 cleared'}）"
        break
    return None


def regen_holds(run: str, shot_ids: list[str], cfg: dict | None = None, root: Path | None = None) -> dict[str, str]:
    """build_jobs 用：{镜: 原因}——hold_regen_downstream 开、该集适用、首帧换代中的镜（视频不派，等新首帧定下）"""
    cfg = load() if cfg is None else cfg
    if not cfg.get("hold_regen_downstream", True):
        return {}
    out = {}
    for sid in shot_ids:
        try:
            ep = int(sid[2:4])
        except ValueError:
            continue
        if not applies(ep, cfg):
            continue
        why = first_under_regen(run, sid, root)
        if why:
            out[sid] = "regen：" + why
    return out


# ---------------------------------------------------------------- 审图位（视频打分的看图路由）
def review_env(cfg: dict | None = None, offline_self: str | None = None) -> dict[str, str]:
    """score_clip（视频 V9 看图 + 身份）该连哪个看图服务：lane_roles.review = {lane: "gpu33:3", port_base, lan_url}。
    打分进程在审图位那台（OFFLINE_SELF == 审图台）→ VQA_URL=127.0.0.1:port_base，不走内网；
    在别台（gpu36 出视频、gpu33:3 审图）→ VQA_LAN_URL=review.lan_url（必须 10. 内网地址，K-REV-V01）且只去审图位
    （VQA_REVIEW_ONLY=1：本机 8870 是视频卡上的看图，不用）。关 / 没配 = {}（旧路由）"""
    cfg = load() if cfg is None else cfg
    rv = cfg.get("review") or {}
    if not cfg.get("enabled") or not rv.get("lane"):
        return {}
    host = str(rv["lane"]).split(":")[0]
    port = int(rv.get("port_base") or 8870)
    me = os.environ.get("OFFLINE_SELF") if offline_self is None else offline_self
    if not me:
        return {}                        # 不在服务器上（笔记本 / 测试）：10. 内网不可达，旧路由
    if me == host:
        return {"VQA_URL": f"http://127.0.0.1:{port}", "VQA_LAN_URL": ""}
    lan = str(rv.get("lan_url") or "")
    if not lan.split("//", 1)[-1].startswith("10."):
        return {}                        # 没有合规的内网入口 = 不改路由（旧行为），不往外网发图
    return {"VQA_LAN": "1", "VQA_LAN_URL": lan, "VQA_REVIEW_ONLY": "1"}


def apply_review_env(env: dict | None = None, cfg: dict | None = None) -> dict[str, str]:
    """把 review_env 写进 os.environ（已有显式 VQA_URL / VQA_LAN_URL 的不覆盖）；返回实际写入的键值"""
    env = os.environ if env is None else env
    out = {}
    for k, v in review_env(cfg, env.get("OFFLINE_SELF") or "").items():
        if k in ("VQA_URL", "VQA_LAN_URL") and env.get(k):
            continue
        env[k] = v
        out[k] = v
    return out


def summary(run: str, ep: int, shot_ids: list[str], cfg: dict | None = None, root: Path | None = None) -> dict:
    """看板 / 日志用一行：{applies, phase, source, pending}"""
    cfg = load() if cfg is None else cfg
    if not applies(ep, cfg):
        return {"applies": False}
    ph = phase_from_state(run, ep)
    if ph:
        return {"applies": True, "phase": ph, "source": "state", "t": time.time()}
    ph, pend = compute_phase(run, ep, shot_ids, root)
    return {"applies": True, "phase": ph, "source": "computed", "pending": pend, "t": time.time()}
