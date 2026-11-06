"""L-209 S2.4（W-S234，11-07）：L-207 run 级占卡集 / 每集阶段只算一次。

以前：gpu33 / gpu36 的 producer 各按本机登记表算 lane_roles_state.json（_active + 每集 phase），两台说法不一（自查 phase_disagree:ep2：
gpu33 说 ep02 frames、gpu36 说 videos——gpu33 的登记表里 ep02 是别台分区的“ready”残影）。
现在：笔记本 resident_sync 每拍（push_control 前，同 S2.2 episode_state）用两台拉回的登记表合并后算一次 → 原子写
data/pipeline/runs/<run>/run_phase.json → 经 control_files() 推两台（整文件覆盖）。服务器 producer / night（经 series10_video/lane_roles）/
lane_roles_producer 读它。

合并口径（merge_for_phase）：每集以分区 images 归属那台的登记表为底（只有它知道本集真实的 ready / running / pending）；
别台只补“已定下”的对象（passed / best_effort / na：首尾帧中继、借道出的结果），不拿别台的 ready / pending 残影改阶段。
阶段 / 段 / active 用 lane_roles_producer 原函数（episode_phases / episode_stages / active_episode / apply_hold_regen），与 producer 同口径。

开关：config/pipeline/state.json 键 run_phase = off | record | enforce（或 {"mode": ...}），缺省 record。
  off     = 不算不写；读者一律本机自算（旧行为）。
  record  = 照算、照写、照推；服务器照旧本机自算，和中心结果不一致时记 run_phase_disagree（每种不一致 10 分钟一条），行为不变。
  enforce = 服务器用中心结果（producer 写进本机 lane_roles_state，night / vidgen / 巡检随之一致）。
  中心文件缺 / 超过 max_age_s（默认 15 分钟）没更新 → 退回本机自算，记 run_phase_fallback（每 10 分钟一条）。
只有笔记本算（OFFLINE_SELF 有值 = 服务器 → compute 拒绝）。

文件格式：
  {"_schema": "nsfs.run_phase/1", "run", "rule": "L-209 S2.4", "mode", "computed_t", "computed_at"(JST),
   "active": {"ep", "phase", "since", "stages"} | null, "phases": {ep: phase}, "stages": {ep: stage},
   "eps": {ep: {"phase", "stage", "settled_n", "settled_at", "since"}}, "owner": {ep: host}, "sources": {host: {"age_s", "used"}}}
"""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG_REL = "config/pipeline/state.json"
KEY = "run_phase"
MODES = ("off", "record", "enforce")
DEFAULT_MODE = "record"
RULE = "L-209 S2.4"
SCHEMA = "nsfs.run_phase/1"
HOSTS = ("gpu33", "gpu36")
MAX_AGE_S = 900            # 中心文件超过这么久没更新 = 过期，读者退回本机自算
REFRESH_S = 300            # 内容没变也每 5 分钟重写一次（让服务器判新鲜）
REG_MAX_AGE_S = 900        # 拉回的登记表心跳超过这么久 = 不用那台
LOG_EVERY_S = 600
SETTLED = ("passed", "best_effort")
KINDS = ("first", "last", "video")
JST = timezone(timedelta(hours=9))
_mu = threading.Lock()
_logged: dict = {}         # (run, actor, kind, sig) → 上次记日志时刻
_mods: dict = {}


# ------------------------------------------------------------------ 小工具
def _jl(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不到 / 写了一半 = 默认值（调用方退回本机自算）
        return d


def _atomic_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, indent=1))
        for i in range(5):              # Windows：读者正开着文件时 os.replace 偶发 PermissionError → 重试
            try:
                os.replace(tmp, p)
                break
            except PermissionError:
                if i == 4:
                    raise
                time.sleep(0.2 * (i + 1))
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def _iso(t: float | None = None) -> str:
    return datetime.fromtimestamp(time.time() if t is None else t, JST).strftime("%Y-%m-%dT%H:%M:%S")


def _root(root) -> Path:
    return Path(root or ROOT)


def _mod(name: str):
    if name not in _mods:
        import importlib.util
        sp = importlib.util.spec_from_file_location(f"ns_{name}_run_phase", Path(__file__).resolve().parent / f"{name}.py")
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _mods[name] = m
    return _mods[name]


def _LRO():
    return _mod("lane_roles_producer")


def _ES():
    return _mod("episode_state")


def _partition(root: Path) -> dict:
    d = str(Path(__file__).resolve().parents[1] / "netfix")
    if d not in sys.path:
        sys.path.insert(0, d)
    import partition as PT  # noqa: PLC0415
    return PT.load(root)


# ------------------------------------------------------------------ 开关 / 路径
def mode(root: Path | None = None) -> str:
    v = (_jl(_root(root) / CFG_REL, {}) or {}).get(KEY, DEFAULT_MODE)
    if isinstance(v, dict):
        v = v.get("mode", DEFAULT_MODE)
    v = str(v or DEFAULT_MODE).strip().lower()
    return v if v in MODES else DEFAULT_MODE


def max_age_s(root: Path | None = None) -> float:
    v = (_jl(_root(root) / CFG_REL, {}) or {}).get(KEY)
    try:
        return float((v or {}).get("max_age_s") or MAX_AGE_S) if isinstance(v, dict) else float(MAX_AGE_S)
    except (TypeError, ValueError):
        return float(MAX_AGE_S)


def rel_path(run: str) -> str:
    return f"data/pipeline/runs/{run}/run_phase.json"


def path(run: str, root: Path | None = None) -> Path:
    return _root(root) / rel_path(run)


def load(run: str, root: Path | None = None) -> dict:
    d = _jl(path(run, root), {}) or {}
    return d if isinstance(d, dict) else {}


def _rate_ok(key: tuple, now: float, every: float = LOG_EVERY_S) -> bool:
    with _mu:
        if now - _logged.get(key, 0.0) < every:
            return False
        _logged[key] = now
        return True


# ------------------------------------------------------------------ 合并（笔记本）
def _settled(o) -> bool:
    return isinstance(o, dict) and (o.get("status") in SETTLED or bool(o.get("na")))


def merge_for_phase(regs: dict, owner: dict | None = None) -> dict:
    """regs = {host: 登记表}；owner = {ep: 出图归属 host}。→ 一份登记表（不改入参）：每集取归属台的那份为底，
    别台只补已定下（passed / best_effort / na）而底表没定下、且底表没有驳回 / 重做标记的对象"""
    hosts = [h for h in regs if isinstance(regs.get(h), dict)]
    if not hosts:
        return {}
    eps_by: dict = {}
    for h in hosts:
        for E in regs[h].get("episodes") or []:
            try:
                eps_by.setdefault(int(E.get("ep")), {})[h] = E
            except (TypeError, ValueError):
                continue
    first = regs[hosts[0]]
    out = {k: v for k, v in first.items() if k != "episodes"}
    out["episodes"] = []
    for ep in sorted(eps_by):
        per = eps_by[ep]
        own = (owner or {}).get(ep)
        bh = own if own in per else next(iter(per))
        E = copy.deepcopy(per[bh])
        E["phase_base"] = bh
        shots = {S.get("shot"): S for S in E.get("shots") or []}
        for h, oE in per.items():
            if h == bh:
                continue
            for oS in oE.get("shots") or []:
                S = shots.get(oS.get("shot"))
                if S is None:
                    continue
                ob = S.setdefault("objects", {})
                for k in KINDS:
                    b, o = ob.get(k), (oS.get("objects") or {}).get(k)
                    if _settled(o) and not _settled(b) and not any((b or {}).get(x) for x in ("redo", "master_reject", "stale", "regen")):
                        ob[k] = {**o, "merged_from": h}
            a, oa = (E.get("objects") or {}).get("assembly"), (oE.get("objects") or {}).get("assembly")
            if (oa or {}).get("status") == "passed" and (a or {}).get("status") != "passed":
                E.setdefault("objects", {})["assembly"] = {**oa, "merged_from": h}
        out["episodes"].append(E)
    return out


def pulled_registries(run: str, root: Path | None = None, now: float | None = None) -> tuple[dict, dict]:
    """→ ({host: 登记表}, {host: {age_s, used}})：resident_sync.pull 拉回的两台登记表（data/_offline_pull/<host>/...）"""
    r = _root(root)
    t = time.time() if now is None else now
    rel = (_ES().producer_dir(run, r) / "registry.json").relative_to(r)
    regs, src = {}, {}
    for h in HOSTS:
        d = _jl(r / "data" / "_offline_pull" / h / rel, None)
        if not isinstance(d, dict):
            src[h] = {"age_s": None, "used": False}
            continue
        age = t - float(d.get("heartbeat") or 0)
        ok = age <= REG_MAX_AGE_S
        src[h] = {"age_s": round(age, 1), "used": ok}
        if ok:
            regs[h] = d
    return regs, src


def adult_blocked_shots(run: str, root: Path | None = None) -> set:
    """同 producer.lane_roles_tick：导入稿 adult=true 的镜 − 项目方已触发的镜（L-128 / L-210）"""
    r = _root(root)
    try:
        sp = _mod("runs").script_path(run, r)          # 按剧取导入稿的唯一入口（K-OPS-F24）
    except Exception:  # noqa: BLE001  # arch-ok: 剧目表读不到 = 不排除成人镜（阶段只会更保守地留在 frames）
        sp = None
    sc = (_jl(sp, {}) if sp else {}) or {}
    adult = {S.get("id") for E in sc.get("episodes") or [] for S in E.get("shots") or [] if isinstance(S, dict) and S.get("adult")}
    trig = set((_jl(_ES().producer_dir(run, r) / "owner_triggers.json", {}) or {}).get("objects") or [])
    shots = set()
    for x in trig:
        kind, _, sid = str(x).rsplit("/", 1)[-1].partition(":")
        if kind in ("first", "last") and sid:
            shots.add(sid)
    return {a for a in adult if a} - shots


# ------------------------------------------------------------------ 算（笔记本）
def compute(run: str, root: Path | None = None, now: float | None = None, write: bool = True, regs: dict | None = None,
            sources: dict | None = None, log=None) -> dict | None:
    """算一次 run 级阶段；write=True 时内容变了或距上次 ≥ REFRESH_S 才原子写。没有可用登记表 = None（不写，服务器自算）"""
    if os.environ.get("OFFLINE_SELF"):
        raise RuntimeError(f"run_phase 只在笔记本算；本机是服务器 {os.environ.get('OFFLINE_SELF')}（OFFLINE_SELF），拒绝")
    r = _root(root)
    t = time.time() if now is None else now
    md = mode(r)
    if md == "off":
        return None
    if regs is None:
        regs, sources = pulled_registries(run, r, t)
    if not regs:
        if log and _rate_ok((run, "laptop", "noreg", ""), t):
            log("run_phase", run, "两台登记表都没有 / 过期，不算（服务器自算）", sources)
        return None
    LRO = _LRO()
    cfg = LRO.load_cfg(r)
    if not LRO.enabled(cfg):
        return None
    part = _partition(r)
    owner = {}
    for h, eps in (part.get("images") or {}).items():
        for e in eps or []:
            try:
                owner[int(e)] = h
            except (TypeError, ValueError):
                continue
    reg = merge_for_phase(regs, owner)
    reg["run"] = run
    old = load(run, r)
    prev = {k: v for k, v in (old.get("eps") or {}).items()}
    prev_active = old.get("active") if isinstance(old.get("active"), dict) else None
    if prev_active is None and not old:      # 第一次算：沿用两台一致的 L-207 粘性 active 集（否则从最小集重排，旧集回切会抢走在跑的集）
        seen = {((g.get("lane_roles") or {}).get("active") or {}).get("ep") for g in regs.values()}
        if len(seen) == 1 and None not in seen:
            prev_active = {"ep": seen.pop()}
    adult = adult_blocked_shots(run, r)
    held = LRO.apply_hold_regen(reg, cfg, _jl(_ES().producer_dir(run, r) / "master_rejects.json", {}) or {})
    phases = LRO.episode_phases(reg, cfg, adult, prev, t)
    stages = LRO.episode_stages(reg, cfg, adult, prev, t)
    settled = LRO.settled_counts(reg, cfg, adult)
    act = LRO.active_episode(stages, prev_active)
    eps = {}
    for ep, ph in phases.items():
        k = str(ep)
        o = prev.get(k) or {}
        sn = int(settled.get(ep, 0))
        eps[k] = {"phase": ph, "stage": stages.get(ep), "settled_n": sn,
                  "settled_at": o.get("settled_at") if o.get("settled_n") == sn and o.get("settled_at") else t,
                  "since": o.get("since") if o.get("phase") == ph and o.get("since") else _iso(t)}
    if act:
        same = prev_active and (prev_active.get("ep"), prev_active.get("phase")) == (act["ep"], act["phase"])
        act = {"ep": act["ep"], "phase": act["phase"], "stages": act.get("stages") or {},
               "since": prev_active.get("since") if same and prev_active.get("since") else _iso(t)}
    doc = {"_schema": SCHEMA, "run": run, "rule": RULE, "mode": md, "active": act,
           "phases": {str(k): v for k, v in phases.items()}, "stages": {str(k): v for k, v in stages.items()},
           "eps": eps, "owner": {str(k): v for k, v in sorted(owner.items())}, "hold_regen": held,
           "_doc": "L-209 S2.4：run 级阶段只在笔记本算一次（两台登记表合并），推两台；服务器 producer / night / lane_roles 读它（enforce），"
                   "record 只比对记 run_phase_disagree。口径见 tools/autopilot/run_phase.py"}
    keep = ("computed_t", "computed_at", "sources")
    changed = {k: v for k, v in old.items() if k not in keep} != doc
    doc.update(computed_t=round(t, 1), computed_at=_iso(t), sources=sources or {})
    if write and (changed or t - float(old.get("computed_t") or 0) >= REFRESH_S):
        _atomic_json(path(run, r), doc)
        if changed and log:
            log("run_phase", run, "active", (act or {}).get("ep"), (act or {}).get("phase"), "phases", doc["phases"])
    return doc


def tick(runs, root: Path | None = None, log=None) -> dict:
    """笔记本 resident_sync 每拍（push_control 前）调；出错只记日志"""
    out = {}
    for run in runs or ():
        try:
            out[run] = compute(run, root, log=log)
        except Exception as e:  # noqa: BLE001
            if log:
                log("run_phase", run, "重算失败", repr(e)[:200])
    return out


# ------------------------------------------------------------------ 读（服务器 / 各读者）
def central(run: str, root: Path | None = None, now: float | None = None, log=None, actor: str = "?") -> dict | None:
    """新鲜的中心结果；off / 缺 / 过期 / 坏 = None（缺和过期记 run_phase_fallback，每 10 分钟一条）"""
    r = _root(root)
    if mode(r) == "off":
        return None
    t = time.time() if now is None else now
    d = load(run, r)
    why = None
    if not d:
        why = "中心 run_phase.json 不在"
    elif d.get("_schema") != SCHEMA:
        why = f"中心文件格式不认识 {d.get('_schema')}"
    else:
        age = t - float(d.get("computed_t") or 0)
        if age > max_age_s(r):
            why = f"中心文件 {age / 60:.0f} 分钟没更新（> {max_age_s(r) / 60:.0f}）"
    if why:
        if log and _rate_ok((run, actor, "fallback", ""), t):
            try:
                log("run_phase_fallback", run=run, why=why, rule=RULE, counted=False)
            except TypeError:
                log("run_phase_fallback", run, why)
        return None
    return d


def central_active(d: dict | None) -> dict | None:
    a = (d or {}).get("active")
    if not isinstance(a, dict) or a.get("phase") not in ("frames", "videos"):
        return None
    try:
        return {**a, "ep": int(a["ep"])}
    except (TypeError, ValueError, KeyError):
        return None


def diff(local_active: dict | None, local_phases: dict | None, d: dict | None) -> dict:
    """本机自算 vs 中心：{} = 一致；只比 active(ep, phase) 和每集 phase"""
    if not d:
        return {}
    out = {}
    la = (int(local_active["ep"]), local_active["phase"]) if local_active else None
    ca = central_active(d)
    cak = (ca["ep"], ca["phase"]) if ca else None
    if la != cak:
        out["active"] = {"local": list(la) if la else None, "central": list(cak) if cak else None}
    cp = d.get("phases") or {}
    lp = {str(k): v for k, v in (local_phases or {}).items()}
    eps = {k: {"local": lp.get(k), "central": cp.get(k)} for k in sorted(set(lp) | set(cp)) if lp.get(k) != cp.get(k)}
    if eps:
        out["phases"] = eps
    return out


def apply(run: str, phases: dict, stages: dict, active: dict | None, root: Path | None = None, log=None, actor: str = "?",
          now: float | None = None) -> tuple[dict, dict, dict | None, str]:
    """服务器 producer 每拍：本机自算结果 → (phases, stages, active, 来源 local | central)。
    record：比对、不一致记 run_phase_disagree（每种 10 分钟一条），返回本机的；enforce：返回中心的（缺 / 过期退回本机）"""
    r = _root(root)
    md = mode(r)
    if md == "off":
        return phases, stages, active, "local"
    t = time.time() if now is None else now
    d = central(run, r, t, log, actor)
    if d is None:
        return phases, stages, active, "local"
    dd = diff(active, phases, d)
    if dd and log and _rate_ok((run, actor, "disagree", json.dumps(dd, sort_keys=True)), t):
        try:
            log("run_phase_disagree", run=run, mode=md, diff=dd, central_at=d.get("computed_at"), rule=RULE, counted=False)
        except TypeError:
            log("run_phase_disagree", run, md, dd)
    if md != "enforce":
        return phases, stages, active, "local"
    cph = {int(k): v for k, v in (d.get("phases") or {}).items()}
    cst = {int(k): v for k, v in (d.get("stages") or {}).items()}
    ca = central_active(d)
    if ca is not None:
        ca = {"ep": ca["ep"], "phase": ca["phase"], "stages": ca.get("stages") or {}}
    return cph, cst, ca, "central"


def enforced(run: str, root: Path | None = None, now: float | None = None, log=None, actor: str = "?") -> dict | None:
    """读者（lane_roles 状态读法 / night）：enforce 且中心新鲜 → 中心文件；否则 None（照旧读本机）"""
    if mode(root) != "enforce":
        return None
    return central(run, root, now, log, actor)


def _cli(argv: list[str]) -> int:
    run = argv[1] if len(argv) > 1 else "series10_v2"
    if argv and argv[0] == "compute":
        d = compute(run, write="--dry" not in argv, log=lambda *a, **k: print(*a, k or ""))
        print(json.dumps({k: (d or {}).get(k) for k in ("mode", "active", "phases", "stages", "owner", "sources", "computed_at")},
                         ensure_ascii=False, indent=1))
        return 0
    if argv and argv[0] == "show":
        print(json.dumps(load(run), ensure_ascii=False, indent=1))
        return 0
    print("用法：python tools/autopilot/run_phase.py compute|show [run] [--dry]")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
