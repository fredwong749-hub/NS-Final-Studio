"""L-209 S2.5（W-S25，11-07）：两台 producer 登记表收成一份 —— run 级合并登记表。

以前：gpu33 / gpu36 各写本机 data/producer/runs/<run>/registry.json，读的人各自合并（ns_api 用 tools/brain/reg_merge“走得最远的赢”，
run_phase 用“归属台为底、别台只补已定下”，大脑 KPI 逐字段取两台最大，影子调度又一套）→ 网页 / 大脑 / KPI / 自查 host_disagree 数字不一。
现在：笔记本 resident_sync 每拍（push_control 前，同 S2.2 / S2.4）用两台拉回的登记表按 merge() 合并一次 → 原子写
data/producer/runs/<run>/registry_merged.json → 经 control_files() 推两台（整文件覆盖，服务器只读）。
所有显示 / 决策读者读它：ns_api.shot_status.merged_registry（网页标签、首尾帧 / 视频页、episode_kpi）、大脑 telemetry.kpi、
自查 host_disagree / kpi_brain、记分卡、影子调度。文件缺 / 过期 → 读者退回本机登记表（旧行为），每 10 分钟记一条。

唯一合并函数 merge(regs, owner)（run_phase.merge_for_phase、reg_merge.merge_registries 都转调它）：
  · 每集以分区 images 归属台的登记表为底（只有它知道本集真实的 ready / running / pending）；归属台没有这一集 → 用别台的，标
    owned_by=<归属台>、owner_missing=true（孤儿集不丢，但标明不是权威来源）；
  · 别台只补“已定下”的对象（passed / best_effort / na：中继、借道出的结果），且底表那份没定下、没带驳回 / 重做标记；
  · 项目方驳回（master_reject）在哪台都赢；底表的 redo / stale / regen 标记挡住别台补；
  · 别台有、底表没有的镜 = 孤儿，丢掉（记进 orphans）；
  · 真冲突（两台都定下但版本不同 / 归属台缺集）记进 conflicts —— 自查 host_disagree 只报这些；
  · 每集 have / counts 按合并后的对象重算（视频只数 passed，口径不变）。
纯函数不读写文件；compute() 读拉回的登记表、写文件（只在笔记本）。

开关：config/pipeline/state.json 键 registry_merged = off | record | enforce（或 {"mode": ..., "max_age_s": ...}），缺省 record。
  off     = 不算不写；读者照旧（本机 / 各自合并）。
  record  = 照算、照写、照推；网页 / 大脑 / KPI 读它（只影响显示）；服务器 producer 只比对、不一致记 registry_merged_disagree（每种 10 分钟一条）。
  enforce = 同 record，另外服务器 producer 可用它取别台事实（cross_host() 返回合并表）。
producer 照旧写本机 registry.json（S3 才改派单）。
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
KEY = "registry_merged"
MODES = ("off", "record", "enforce")
DEFAULT_MODE = "record"
RULE = "L-209 S2.5"
SCHEMA = "nsfs.registry_merged/1"
NAME = "registry_merged.json"
HOSTS = ("gpu33", "gpu36")
MAX_AGE_S = 900            # 超过这么久没更新 = 过期，读者退回本机登记表
REFRESH_S = 300            # 内容没变也每 5 分钟重写一次（让读者判新鲜；同 run_phase）
LOG_EVERY_S = 600
SETTLED = ("passed", "best_effort")
KINDS = ("first", "last", "video")
BASE_MARKS = ("redo", "master_reject", "stale", "regen")   # 底表带这些 → 别台不补
OWNER_MARK = "master_reject"                                 # 项目方驳回：哪台带都赢
MAX_LIST = 60
JST = timezone(timedelta(hours=9))
_mu = threading.Lock()
_logged: dict = {}
_cache: dict = {}          # path → (mtime_ns, doc)
_mods: dict = {}


# ------------------------------------------------------------------ 小工具
def _jl(p: Path, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不到 / 写了一半 = 默认值（调用方退回本机登记表）
        return d


def _atomic_json(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(p.parent), prefix=p.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":")))
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
        sp = importlib.util.spec_from_file_location(f"ns_{name}_reg_merged", Path(__file__).resolve().parent / f"{name}.py")
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _mods[name] = m
    return _mods[name]


def _rate_ok(key: tuple, now: float, every: float = LOG_EVERY_S) -> bool:
    with _mu:
        if now - _logged.get(key, 0.0) < every:
            return False
        _logged[key] = now
        return True


def _log(log, event: str, now: float, key: tuple, **kw) -> None:
    if not log or not _rate_ok(key, now):
        return
    try:
        log(event, rule=RULE, counted=False, **kw)
    except TypeError:
        log(event, *[f"{k}={v}" for k, v in kw.items()])


# ------------------------------------------------------------------ 开关 / 路径
def _cfg(root) -> object:
    return (_jl(_root(root) / CFG_REL, {}) or {}).get(KEY, DEFAULT_MODE)


def mode(root: Path | None = None) -> str:
    v = _cfg(root)
    if isinstance(v, dict):
        v = v.get("mode", DEFAULT_MODE)
    v = str(v or DEFAULT_MODE).strip().lower()
    return v if v in MODES else DEFAULT_MODE


def max_age_s(root: Path | None = None) -> float:
    v = _cfg(root)
    try:
        return float((v or {}).get("max_age_s") or MAX_AGE_S) if isinstance(v, dict) else float(MAX_AGE_S)
    except (TypeError, ValueError):
        return float(MAX_AGE_S)


def rel_path(run: str) -> str:
    return f"data/producer/runs/{run}/{NAME}"


def path(run: str, root: Path | None = None) -> Path:
    return _root(root) / rel_path(run)


# ------------------------------------------------------------------ 唯一合并函数（纯）
def _settled(o) -> bool:
    return isinstance(o, dict) and (o.get("status") in SETTLED or bool(o.get("na")))


def _counts(objs) -> dict:
    c: dict = {}
    for o in objs:
        if isinstance(o, dict):
            st = str(o.get("status") or "")
            c[st] = c.get(st, 0) + 1
    c["total"] = sum(1 for o in objs if isinstance(o, dict))
    return c


def _ep_int(E) -> int | None:
    try:
        return int(E.get("ep"))
    except (TypeError, ValueError, AttributeError):
        return None


def merge(regs: dict, owner: dict | None = None) -> dict:
    """regs = {host: 登记表}（dict 顺序 = 没有归属时的底表优先级）；owner = {ep: 出图归属 host}。→ 新 dict（不改入参）：
    episodes 按口径合并；另加 merged_hosts、conflicts、orphans。见模块说明"""
    hosts = [h for h in regs if isinstance(regs.get(h), dict)]
    if not hosts:
        return {}
    eps_by: dict = {}
    for h in hosts:
        for E in regs[h].get("episodes") or []:
            ep = _ep_int(E)
            if ep is not None:
                eps_by.setdefault(ep, {})[h] = E
    out = {k: copy.deepcopy(v) for k, v in regs[hosts[0]].items() if k != "episodes"}
    out["episodes"] = []
    conflicts, orphan_shots, owner_missing = [], [], []
    for ep in sorted(eps_by):
        per = eps_by[ep]
        own = (owner or {}).get(ep)
        bh = own if own in per else next(iter(per))
        E = copy.deepcopy(per[bh])
        E["phase_base"] = bh
        E["base_host"] = bh
        if own and own != bh:
            E["owned_by"] = own
            E["owner_missing"] = True
            owner_missing.append(ep)
            conflicts.append({"ep": ep, "shot": None, "kind": "episode", "why": "owner_missing", "used": bh, "owner": own})
        shots = {S.get("shot"): S for S in E.get("shots") or [] if isinstance(S, dict)}
        for h, oE in per.items():
            if h == bh:
                continue
            for oS in oE.get("shots") or []:
                if not isinstance(oS, dict):
                    continue
                S = shots.get(oS.get("shot"))
                if S is None:
                    orphan_shots.append({"host": h, "shot": oS.get("shot")})
                    continue
                ob = S.setdefault("objects", {})
                for k in KINDS:
                    b, o = ob.get(k), (oS.get("objects") or {}).get(k)
                    if not isinstance(o, dict):
                        continue
                    if o.get(OWNER_MARK) and not (b or {}).get(OWNER_MARK):      # 项目方驳回：底表没定下时别台带的驳回赢
                        if _settled(b):   # 复审 11-07 BLOCKER：底表已定下（主台已按驳回重出并过）→ 别台陈旧的驳回不盖，记冲突
                            conflicts.append({"ep": ep, "shot": S.get("shot"), "kind": k, "why": "reject_vs_settled", "used": bh,
                                              "views": {bh: [b.get("status"), b.get("take")], h: [o.get("status"), o.get("take")]}})
                            continue
                        ob[k] = {**o, "merged_from": h}
                        continue
                    if not _settled(o):
                        continue
                    if any((b or {}).get(x) for x in BASE_MARKS):
                        continue                                                # 底表驳回 / 重做 / 过期：别台旧的定下版不盖
                    if not _settled(b):
                        if b and b.get("take") is not None and o.get("take") is not None and o.get("take") < b.get("take"):
                            # 复审 11-07：主台在出更新的版本（take 更大）时，别台旧的定下版不填，记冲突
                            conflicts.append({"ep": ep, "shot": S.get("shot"), "kind": k, "why": "older_take_vs_base", "used": bh,
                                              "views": {bh: [b.get("status"), b.get("take")], h: [o.get("status"), o.get("take")]}})
                            continue
                        ob[k] = {**o, "merged_from": h}
                        S.setdefault("has", {})[k] = True
                    elif b.get("take") is not None and o.get("take") is not None and b.get("take") != o.get("take"):
                        conflicts.append({"ep": ep, "shot": S.get("shot"), "kind": k, "why": "take_diff", "used": bh,
                                          "views": {bh: [b.get("status"), b.get("take")], h: [o.get("status"), o.get("take")]}})
            a, oa = (E.get("objects") or {}).get("assembly"), (oE.get("objects") or {}).get("assembly")
            if (oa or {}).get("status") == "passed" and (a or {}).get("status") != "passed":
                E.setdefault("objects", {})["assembly"] = {**oa, "merged_from": h}
        sl = [S for S in E.get("shots") or [] if isinstance(S, dict)]
        if sl:
            hv = E.setdefault("have", {})
            for k in KINDS:
                hv[k] = sum(1 for S in sl if (S.get("has") or {}).get(k))
            hv["passed"] = {k: sum(1 for S in sl if ((S.get("objects") or {}).get(k) or {}).get("status") == "passed") for k in KINDS}
            hv["total"] = len(sl)
            E["counts"] = _counts([o for S in sl for o in (S.get("objects") or {}).values()] + list((E.get("objects") or {}).values()))
        out["episodes"].append(E)
    out["counts"] = _counts([o for E in out["episodes"] for S in E.get("shots") or [] if isinstance(S, dict)
                             for o in (S.get("objects") or {}).values()] + [o for E in out["episodes"] for o in (E.get("objects") or {}).values()])
    out["merged_hosts"] = hosts
    out["conflicts"] = conflicts[:MAX_LIST]
    out["conflicts_n"] = len(conflicts)
    out["orphans"] = {"shots_dropped": orphan_shots[:MAX_LIST], "shots_dropped_n": len(orphan_shots), "eps_owner_missing": owner_missing}
    return out


def ep_have(doc: dict) -> dict:
    """合并表 → {ep(str): {t, f, l, v, asm}}（大脑 / 自查 / 记分卡用的紧凑口径）"""
    out = {}
    for E in (doc or {}).get("episodes") or []:
        hv = E.get("have") or {}
        pz = hv.get("passed") or {}
        out[str(E.get("ep"))] = {"t": int(hv.get("total") or 0), "f": int(pz.get("first") or 0), "l": int(pz.get("last") or 0),
                                 "v": int(pz.get("video") or 0),
                                 "asm": ((E.get("objects") or {}).get("assembly") or {}).get("status") == "passed"}
    return out


# ------------------------------------------------------------------ 算（笔记本）
def owner_map(root: Path | None = None) -> dict:
    d = str(Path(__file__).resolve().parents[1] / "netfix")
    if d not in sys.path:
        sys.path.insert(0, d)
    import partition as PT  # noqa: PLC0415
    out = {}
    for h, eps in ((PT.load(_root(root)) or {}).get("images") or {}).items():
        for e in eps or []:
            try:
                out[int(e)] = h
            except (TypeError, ValueError):
                continue
    return out


def compute(run: str, root: Path | None = None, now: float | None = None, write: bool = True, regs: dict | None = None,
            sources: dict | None = None, owner: dict | None = None, log=None) -> dict | None:
    """笔记本每拍：拉回的两台登记表 → 合并表；内容变了或距上次 ≥ REFRESH_S 才原子写。没有可用登记表 = None（不写，读者退回本机）"""
    if os.environ.get("OFFLINE_SELF"):
        raise RuntimeError(f"registry_merged 只在笔记本算；本机是服务器 {os.environ.get('OFFLINE_SELF')}（OFFLINE_SELF），拒绝")
    r = _root(root)
    t = time.time() if now is None else now
    md = mode(r)
    if md == "off":
        return None
    if regs is None:
        regs, sources = _mod("run_phase").pulled_registries(run, r, t)
    if not regs:
        _log(log, "registry_merged_skip", t, (run, "laptop", "noreg"), run=run, why="两台登记表都没有 / 过期，不写", sources=sources)
        return None
    if owner is None:
        owner = owner_map(r)
    doc = merge({h: regs[h] for h in HOSTS if h in regs} | {h: v for h, v in regs.items() if h not in HOSTS}, owner)
    doc.update(_schema=SCHEMA, run=run, rule=RULE, mode=md, owner={str(k): v for k, v in sorted(owner.items())},
               hosts={h: {k: (regs[h] or {}).get(k) for k in ("heartbeat", "updated", "paused", "counts")} for h in regs},
               _doc="L-209 S2.5：两台登记表在笔记本合并成一份（tools/autopilot/registry_merged.py），推两台只读；"
                    "producer 照旧写本机 registry.json")
    old = load(run, r)
    keep = ("computed_t", "computed_at", "heartbeat", "sources", "hosts")
    _cmp = ("episodes", "conflicts", "orphans")   # 复审 11-07：只比实质内容（顶层 lanes / pid / updated 等每拍都变，会让文件每拍重写重推）
    changed = {k: old.get(k) for k in _cmp} != {k: doc.get(k) for k in _cmp}
    doc.update(computed_t=round(t, 1), computed_at=_iso(t), heartbeat=round(t, 1), sources=sources or {})
    if write and (changed or t - float(old.get("computed_t") or 0) >= REFRESH_S):
        _atomic_json(path(run, r), doc)
        if changed and log:
            try:
                log("registry_merged", run, "hosts", doc["merged_hosts"], "conflicts", doc["conflicts_n"],
                    "orphans", doc["orphans"]["shots_dropped_n"])
            except TypeError:
                pass
    return doc


def tick(runs, root: Path | None = None, log=None) -> dict:
    """笔记本 resident_sync 每拍（push_control 前）调；出错只记日志"""
    out = {}
    for run in runs or ():
        try:
            out[run] = compute(run, root, log=log)
        except Exception as e:  # noqa: BLE001
            if log:
                log("registry_merged", run, "重算失败", repr(e)[:200])
    return out


# ------------------------------------------------------------------ 读（各读者）
def load(run: str, root: Path | None = None) -> dict:
    """按 mtime 缓存的整份文件（不判新鲜）；缺 / 坏 = {}"""
    return load_path(path(run, root))


def load_path(p: Path) -> dict:
    try:
        mt = p.stat().st_mtime_ns
    except OSError:  # arch-ok: 没有 = 空
        return {}
    c = _cache.get(str(p))
    if c and c[0] == mt:
        return c[1]
    d = _jl(p, {}) or {}
    d = d if isinstance(d, dict) else {}
    _cache[str(p)] = (mt, d)
    return d


def staleness(d: dict, root: Path | None = None, now: float | None = None) -> str | None:
    """None = 新鲜；否则原因"""
    t = time.time() if now is None else now
    if not d:
        return "合并登记表不在"
    if d.get("_schema") != SCHEMA:
        return f"合并登记表格式不认识 {d.get('_schema')}"
    age = t - float(d.get("computed_t") or 0)
    if age > max_age_s(root):
        return f"合并登记表 {age / 60:.0f} 分钟没更新（> {max_age_s(root) / 60:.0f}）"
    return None


def fresh(run: str, root: Path | None = None, now: float | None = None, log=None, actor: str = "?") -> dict | None:
    """新鲜的合并表；off / 缺 / 过期 / 坏 = None（记 registry_merged_fallback，每 10 分钟一条：读者退回本机登记表）"""
    return fresh_path(path(run, root), root, now, log, actor, run)


def fresh_path(p: Path, root: Path | None = None, now: float | None = None, log=None, actor: str = "?", run: str = "") -> dict | None:
    """同 fresh()，按文件路径（ns_api 只知道登记表路径：合并表在它旁边 registry_merged.json）"""
    if mode(root) == "off":
        return None
    t = time.time() if now is None else now
    d = load_path(Path(p))
    why = staleness(d, root, t)
    if why:
        _log(log, "registry_merged_fallback", t, (str(p), actor, "fallback"), run=run or Path(p).parent.name, actor=actor, why=why)
        return None
    return d


def read(run: str, local_path: Path | None = None, root: Path | None = None, now: float | None = None, log=None,
         actor: str = "?") -> tuple[dict, str]:
    """读者统一入口：(登记表, 来源 merged | local)。合并表新鲜 → 它；否则本机登记表"""
    d = fresh(run, root, now, log, actor)
    if d is not None:
        return d, "merged"
    lp = local_path or (_root(root) / f"data/producer/runs/{run}/registry.json")
    return (_jl(lp, {}) or {}), "local"


def default_log(actor: str):
    """没有现成日志的读者（API / 大脑 / 记分卡）：退回记录写到 stderr（每 10 分钟一条由 _log 限流）"""
    def _f(event, *a, **kw):
        print(f"[{_iso()}] {actor} {event}", *a, json.dumps(kw, ensure_ascii=False, default=str) if kw else "", file=sys.stderr)
    return _f


# ------------------------------------------------------------------ 服务器 producer：别台事实（开关后）
def diff(local: dict, merged: dict, host: str) -> list[dict]:
    """本机登记表 vs 合并表：只比“定下没定下”和项目方驳回（record 记日志用）→ [{obj, local, merged, from}]"""
    lv = {(S.get("shot"), k): o for E in (local or {}).get("episodes") or [] for S in E.get("shots") or [] if isinstance(S, dict)
          for k, o in (S.get("objects") or {}).items() if k in KINDS and isinstance(o, dict)}
    out = []
    for E in (merged or {}).get("episodes") or []:
        for S in E.get("shots") or []:
            for k in KINDS:
                m = ((S.get("objects") or {}).get(k)) or {}
                lo = lv.get((S.get("shot"), k))
                if not m or lo is None:
                    continue
                if _settled(m) != _settled(lo) or bool(m.get(OWNER_MARK)) != bool(lo.get(OWNER_MARK)):
                    out.append({"obj": f"{k}:{S.get('shot')}", "local": lo.get("status"), "merged": m.get("status"),
                                "from": m.get("merged_from") or E.get("base_host")})
    return out


def cross_host(run: str, local: dict, host: str, root: Path | None = None, now: float | None = None, log=None) -> dict | None:
    """服务器 producer 每拍可调：off → None；record → 比对、不一致记 registry_merged_disagree（每种 10 分钟一条），返回 None（行为不变）；
    enforce → 返回新鲜合并表（调用方只取别台事实）；缺 / 过期 → None（记 registry_merged_fallback）"""
    md = mode(root)
    if md == "off":
        return None
    t = time.time() if now is None else now
    d = fresh(run, root, t, log, actor=host)
    if d is None:
        return None
    dd = diff(local, d, host)
    if dd:
        _log(log, "registry_merged_disagree", t, (run, host, "disagree"), run=run, mode=md, n=len(dd),
             sample=dd[:8], merged_at=d.get("computed_at"))
    return d if md == "enforce" else None


def _cli(argv: list[str]) -> int:
    run = argv[1] if len(argv) > 1 else "series10_v2"
    if argv and argv[0] == "compute":
        d = compute(run, write="--dry" not in argv, log=lambda *a, **k: print(*a, k or ""))
        print(json.dumps({k: (d or {}).get(k) for k in ("mode", "merged_hosts", "conflicts_n", "orphans", "computed_at")},
                         ensure_ascii=False, indent=1))
        print(json.dumps(ep_have(d or {}), ensure_ascii=False))
        return 0
    if argv and argv[0] == "show":
        d = load(run)
        print(json.dumps({k: d.get(k) for k in ("mode", "computed_at", "merged_hosts", "conflicts_n", "conflicts", "orphans")},
                         ensure_ascii=False, indent=1))
        return 0
    print("用法：python tools/autopilot/registry_merged.py compute|show [run] [--dry]")
    return 2


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
