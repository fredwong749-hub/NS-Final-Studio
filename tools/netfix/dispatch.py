"""谁派单（NETFIX 11-01，总调度 fredw-2b 派；规则 K-OPS-N04）。

出图从“笔记本 producer 经隧道派到服务器”改为“每台机器只派本机的出图道”：
  gpu33 / gpu36 各跑一个常驻 producer（服务器上 127.0.0.1:181xx/182xx 经 fwd.py 到本机 ComfyUI，不经跳板），笔记本 producer 只派 laptop:0。
每个 producer 的 control.json 由本模块按同一份规则算（唯一来源，不手写）：
  only       = config/netfix/partition.json images[本机] ∩ data/autopilot/ready_episodes.json（WORKFLOW episode_pipeline 写）的镜；
               交集为空 → ["__none__"]（一个都不派；producer 的 only 为空表示“全部”，所以不能留空）。
               FIX-ORCH O2（L-202 按镜）：ready 里的条目可以是 partial（episode_pipeline.sync_shot_ready 写：整集还没齐、
               但本镜资产 shot_gaps 为空）→ 这些镜照样进 only，不等整集
  hold_lanes = 不属于本机的全部道（服务器上 laptop:0 的地址不通，也要挂住）
  paused     = 跟随笔记本 control.json 的全局暂停（paused_by 属于 global_pause_ignore_by 的不算）
跨机不重叠：分区按集互斥（check_partition 校验），所以两台不会派同一个对象；没有跨机共享锁，不做跨机接手（steal_plan 只出评估）。

用法：
  .venv/Scripts/python.exe tools/netfix/dispatch.py show                 每台机器会派什么
  .venv/Scripts/python.exe tools/netfix/dispatch.py check                分区自检（互斥 / 覆盖 10 集 / 道不重叠）
  .venv/Scripts/python.exe tools/netfix/dispatch.py apply-laptop [--dry] 写笔记本 control.json 的 only / hold_lanes（不动 paused）
  服务器上：<OFF>/venv/bin/python tools/netfix/dispatch.py server-control gpu33 --laptop-ctrl <json 文件> [--write]
            （resident_prep.py 调用；laptop-ctrl 是 resident_sync 推上去的笔记本 control.json 快照）
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools/factory"))
import state_paths as SP  # noqa: E402   ARCH_ROADMAP §10：运行期状态唯一入口（sv-10 兼容期：先新后旧并留痕）
PART_NAME, OV_NAME = "netfix/partition", "netfix/override"
PARTITION = SP.state_path(PART_NAME, ROOT)              # 新位置 data/state/netfix/partition.json（旧 config/netfix/partition.json 兼容期仍可读）
PARTITION_OLD = SP.legacy_path(PART_NAME, ROOT)
READY = ROOT / "data/autopilot/ready_episodes.json"
CONTROL = ROOT / "data/producer/control.json"
NONE = "__none__"


def iso() -> str:
    """笔记本时区（UTC+9）的时间戳：服务器时区是 America/New_York，ts 字段统一按笔记本口径（同 start.sh 的 TZ=Asia/Tokyo）"""
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(time.time() + 9 * 3600))


def jl(p, d=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return d


def js(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".netfix.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)


def migrate_state(root: Path | None = None) -> list[str]:
    """启动时：旧文件在、新文件不在 → 原子复制到新位置（只做一次）。返回复制了哪些"""
    done = []
    for name in (PART_NAME, OV_NAME):
        new, old = SP.state_path(name, root or ROOT), SP.legacy_path(name, root or ROOT)
        if old.is_file() and not new.is_file():
            obj = jl(old, None)
            if obj is not None:
                SP.write_state(name, obj, root or ROOT)
                done.append(name)
    return done


def read_partition(root: Path | None = None) -> dict:
    """兼容期：先新后旧（读旧会在 data/state/legacy_reads.jsonl 留痕）；NS_STATE_STRICT=1（sv-11）时只认新位置，只有旧 → raise"""
    r = root or ROOT
    if os.environ.get("NS_STATE_STRICT") == "1" and not SP.state_path(PART_NAME, r).is_file():
        raise SP.StateError(f"{PART_NAME}：新位置不在（sv-11 起不再读旧位置 {SP.legacy_path(PART_NAME, r)}）")
    return SP.read_state(PART_NAME, default={}, root=r) or {}


def read_override(root: Path | None = None) -> dict:
    if OVERRIDE != _OVERRIDE_DEFAULT:          # 测试换了路径
        return jl(OVERRIDE, {}) or {}
    return SP.read_state(OV_NAME, default={}, root=root or ROOT) or {}


def partition(p: Path | None = None) -> dict:
    return (jl(p, {}) or {}) if p else read_partition()


def check_partition(part: dict | None = None) -> list[str]:
    """[] = 通过。images / video 每集恰好一台；道不重叠；笔记本不出视频"""
    part = part or partition()
    errs = []
    for kind, want in (("images", range(1, 11)), ("video", range(1, 11))):
        seen: dict[int, str] = {}
        for h, eps in (part.get(kind) or {}).items():
            for e in eps:
                if e in seen:
                    errs.append(f"{kind}: ep{e:02d} 同时分给 {seen[e]} 和 {h}（会重复派单）")
                seen[e] = h
        miss = [e for e in want if e not in seen]
        if miss:
            errs.append(f"{kind}: 没分出去的集 {miss}")
    if "laptop" in (part.get("video") or {}):
        errs.append("video: 笔记本道 laptop:0 是 image_only，不能分视频")
    lanes: dict[str, str] = {}
    for h, ls in (part.get("lanes") or {}).items():
        for ln in ls:
            if ln in lanes:
                errs.append(f"lanes: {ln} 同时属于 {lanes[ln]} 和 {h}")
            lanes[ln] = h
    return errs


def ready_shots(ready: dict | None) -> dict[int, list[str]]:
    out = {}
    for ep, rec in ((ready or {}).get("episodes") or {}).items():
        try:
            out[int(ep)] = sorted(set((rec or {}).get("shots") or []))
        except (TypeError, ValueError):
            continue
    return out


RUNS = ROOT / "config/pipeline/runs.json"
LIVE_RUN_STATUS = ("producing",)


def split_obj(s: str) -> tuple[str | None, str]:
    """多剧并行（AUTOPILOT §0.1，L-104）：'<run>/<kind>:<shot>' 或 '<run>/<shot>' → (run, 余下)；无前缀 = primary（返回 None）"""
    if "/" in s:
        run, rest = s.split("/", 1)
        return run, rest
    return None, s


def legacy_run_id() -> str | None:
    """用不带前缀旧路径（data/producer/control.json、data/autopilot/ready_episodes.json）的那部剧 = runs.json legacy_unprefixed_run
    （K-OPS-F24）；没写 → 退回 primary（老登记表 / 测试夹具的旧行为）"""
    d = jl(RUNS, {}) or {}
    return d.get("legacy_unprefixed_run") or d.get("primary")


def extra_runs() -> list[tuple[str, int]]:
    """除旧路径那部剧（legacy，run_id=None 的那一格）外正在生产的 run（按 priority 升序）。
    MERGE-OPS-O（carryover 第 14 项，L-137）：以前按“不是 primary”排除，V2 当上 primary 后既不是 legacy 格、又被这里排除 → 没有专属 control"""
    d = jl(RUNS, {}) or {}
    leg = legacy_run_id()
    out = [(r, int((v or {}).get("priority", 10))) for r, v in (d.get("runs") or {}).items()
           if r != leg and (v or {}).get("status") in LIVE_RUN_STATUS]
    return sorted(out, key=lambda x: x[1])


NO_CONTROL_STATUS = ("archived",)   # 归档的剧不准备 control


def paused_runs() -> list[str]:
    """runs.json 里登记了、但 status 不是 producing 的非 legacy 剧（K-OPS-F20；V2 primary 也在内，MERGE-OPS-O）"""
    d = jl(RUNS, {}) or {}
    leg = legacy_run_id()
    return sorted(r for r, v in (d.get("runs") or {}).items() if r != leg and (v or {}).get("status") not in LIVE_RUN_STATUS)


def pause_run_control(run: str, host: str | None = None, laptop_ctrl: dict | None = None, part: dict | None = None) -> dict | None:
    """K-OPS-F20（总调度 11-02 17:0x）：暂停状态只有一个来源 = runs.json。status 不是 producing 的 run，把它的 control 写成
    paused=true + reason_kind=owner（16:07 gpu36 第二季 control 被重算成 paused=false，暂停后又派单）。
    MERGE-OPS-O（L-137）：开派前就要有 control——没有 control 文件、给了 host、剧没归档 → 按本机分区先算好 only / hold_lanes，
    以 paused=true 写出（status 改成 producing 后下一拍 server-control 直接按分区放开）。没给 host 时保持旧行为：没有文件不写"""
    p = run_control_path(run)
    c = jl(p, None)
    st = ((jl(RUNS, {}) or {}).get("runs") or {}).get(run, {}).get("status")
    if not isinstance(c, dict):
        if host is None or st in NO_CONTROL_STATUS:
            return None
        f = control_for(host, laptop_ctrl or {}, run_ready(run), part, runs=[], run_id=run)
        return apply(p, {**f, "paused": True, "paused_by": "runs.json", "reason_kind": "owner",
                         "note": f"config/pipeline/runs.json status={st}（开派前预备的 control，MERGE-OPS-O）"})
    if c.get("paused") and c.get("reason_kind") == "owner":
        return None
    return apply(p, {"paused": True, "paused_by": "runs.json", "reason_kind": "owner", "note": f"config/pipeline/runs.json status={st}"})


def prepare_run_controls(host: str, laptop_ctrl: dict | None = None, part: dict | None = None) -> dict:
    """本机每部非 legacy、没归档的剧都有一份 control（MERGE-OPS-O）：在产的剧由 server-control 正常写；
    其余（preparing / paused）没有文件时先预备一份 paused 的。→ {run: 是否新写}"""
    out = {}
    for r in paused_runs():
        out[r] = bool(pause_run_control(r, host=host, laptop_ctrl=laptop_ctrl, part=part))
    return out


def laptop_run_controls(laptop_ctrl: dict | None, part: dict | None = None, write: bool = True) -> dict:
    """笔记本侧各剧 control（MERGE-OPS-O，L-137）：在产的非 legacy 剧按分区写 only / hold_lanes；
    之前是 runs.json 暂停的（paused_by=runs.json）在转为 producing 后放开（跟随笔记本全局暂停）；别人（项目方 / 总调度）的暂停不动。
    没在产的剧没有文件时预备一份 paused 的。→ {run: 动作}"""
    part = part or partition()
    lc = laptop_ctrl or {}
    gp, by = global_pause(lc, part)
    out = {}
    for r, _p in extra_runs():
        p = run_control_path(r)
        c = jl(p, {}) or {}
        f = control_for("laptop", lc, run_ready(r), part, runs=[], run_id=r)
        if c.get("paused_by") == "runs.json" or not c:
            f.update(paused=gp, paused_by=(f"GLOBAL:{by}" if gp else None), reason_kind=("global" if gp else None),
                     note=(f"跟随笔记本全局暂停（{by}）" if gp else "runs.json status=producing：按分区派"))
        keys = ("only", "hold_lanes", "paused", "paused_by")
        if any(c.get(k) != {**c, **f}.get(k) for k in keys):     # dispatch_by 的时间戳每拍都变，不算改动
            if write:
                apply(p, f)
            out[r] = "written"
    if write:
        out.update({r: "prepared" for r, v in prepare_run_controls("laptop", lc, part).items() if v})
    return out


def run_ready(run: str) -> dict:
    return jl(ROOT / "data/autopilot/runs" / run / "ready_episodes.json", {}) or {}


RUN_ONLY_PREFIXED = False   # 非主剧 control.only 是否带 "<run>/" 前缀（与 DEBUG-RSI 对齐）


def norm_shot(s: str, run_id: str | None) -> str:
    """ready 里的镜号统一成该 run producer 认的格式：主剧不带前缀；其它 run 按 RUN_ONLY_PREFIXED"""
    r, rest = split_obj(s)
    if run_id is None:
        return rest if r is None else s
    return f"{run_id}/{rest}" if RUN_ONLY_PREFIXED else rest


def run_control_path(run_id: str | None) -> Path:
    return CONTROL if run_id is None else ROOT / "data/producer/runs" / run_id / "control.json"


def verify_run(run_id: str | None, ready: dict, part: dict | None = None, ph: dict | None = None) -> list[str]:
    """[] = 通过：两台服务器的 only 不相交，且并集 = 该 run 全部 ready 镜号（笔记本分区非空时把笔记本也算进来）。
    覆盖期（某台 phase=laptop）只校验不相交（那台本来就是 __none__，由笔记本代派）"""
    part = part or partition()
    ph = ph if ph is not None else phases()
    hosts = [h for h, eps in (part.get("images") or {}).items() if eps]
    sets = {}
    for h in hosts:
        f = control_for(h, {}, ready, part, ph=ph, runs=[], run_id=run_id)
        sets[h] = {x for x in f["only"] if x != NONE}
    errs = []
    hs = sorted(sets)
    for i in range(len(hs)):
        for j in range(i + 1, len(hs)):
            both = sets[hs[i]] & sets[hs[j]]
            if both:
                errs.append(f"{run_id or 'primary'}: {hs[i]} 与 {hs[j]} 重复 {len(both)} 镜（例 {sorted(both)[:3]}）")
    if not any(p in ON_LAPTOP for p in ph.values()):
        want = {norm_shot(x, run_id) for v in ready_shots(ready).values() for x in v}
        got = set().union(*sets.values()) if sets else set()
        if want - got:
            errs.append(f"{run_id or 'primary'}: {len(want - got)} 镜没分出去（例 {sorted(want - got)[:3]}）")
    return errs


def global_pause(laptop_ctrl: dict | None, part: dict | None = None) -> tuple[bool, str | None]:
    part = part or partition()
    c = laptop_ctrl or {}
    by = c.get("paused_by")
    if c.get("paused") and by not in set(part.get("global_pause_ignore_by") or []):
        return True, str(by)
    return False, None


OVERRIDE = SP.state_path(OV_NAME, ROOT)                # 新位置 data/state/netfix/override.json
_OVERRIDE_DEFAULT = OVERRIDE
OVERRIDE_STATE = ROOT / "data/netfix/override_state.json"
ASSETS_READY = ROOT / "data/autopilot/assets_ready.json"
LEASES = ROOT / "data/producer/leases"
ON_LAPTOP = ("laptop", "draining")


def phases(state: dict | None = None) -> dict[str, str]:
    """临时覆盖（总调度 23:3x）每台服务器的阶段：laptop = 它的分区由笔记本经隧道派；draining = 正在交还（笔记本不再派新单、
    等在途完成，服务器仍不派）；server = 正常（服务器自己派）。没有状态文件 = 全部 server"""
    st = state if state is not None else (jl(OVERRIDE_STATE, {}) or {})
    return {h: (st.get("hosts") or {}).get(h, {}).get("phase", "server") for h in ("gpu33", "gpu36")}


def control_for(host: str, laptop_ctrl: dict | None, ready: dict | None, part: dict | None = None,
                ph: dict | None = None, runs: list | None = None, ready_by_run: dict | None = None,
                run_id: str | None = None) -> dict:
    """本机 producer 的 control 字段（只这几个；control.json 其它字段读-改-写保留）。
    run_id=None = 主剧（data/producer/control.json）；否则 = 该 run 的 producer（data/producer/runs/<run>/control.json），
    ready 传该 run 的 ready_episodes，分区规则同主剧（按集），暂停 / hold / 退役道 / 覆盖阶段共用"""
    part = part or partition()
    ph = ph if ph is not None else phases()
    ov = read_override()
    eps = sorted(set(part["images"].get(host) or []))
    taken = []                                   # 笔记本临时代派的服务器分区
    if host == "laptop":
        taken = sorted({e for h, p in ph.items() if p == "laptop" for e in (part["images"].get(h) or [])})
        eps = sorted(set(eps) | set(taken))
    rs = ready_shots(ready)
    ready_eps = [e for e in eps if e in rs]
    only = sorted({norm_shot(s, run_id) for e in ready_eps for s in rs[e]})
    runs_extra = {}
    if run_id is None:                       # 主剧 control：只统计其它 run 在本机的份额（各 run 的镜号写进各自的 control，sv-10）
        for run, _prio in (extra_runs() if runs is None else runs):
            rr = ready_shots(run_ready(run) if ready_by_run is None else ready_by_run.get(run, {}))
            n = sum(len(rr[e]) for e in eps if e in rr)
            if n:
                runs_extra[run] = n
    only = only or [NONE]
    if host == "laptop":
        hold = sorted({ln for h, ls in (part.get("lanes") or {}).items() if h != "laptop" and ph.get(h, "server") != "laptop"
                       for ln in ls} | set(ov.get("laptop_hold") or []) | held_lanes(part))   # L-100（总调度 01:5x）：laptop_hold 无条件生效（笔记本 4080 / gpu36 GPU2 专做看图），不再只在代派阶段生效
    else:
        hold = sorted({ln for h, ls in (part.get("lanes") or {}).items() if h != host for ln in ls} | held_lanes(part))   # 主剧 / 每个 run 同一套
        if ph.get(host, "server") in ON_LAPTOP:  # 本机分区正由笔记本代派（或交还中）：一单都不派，防重复
            only = [NONE]
    gp, by = global_pause(laptop_ctrl, part)
    fields = {"only": only, "hold_lanes": hold,
              "dispatch_by": {"by": "NETFIX dispatch.py", "at": iso(), "host": host,
                              "partition_eps": eps, "ready_eps": ready_eps, "override_phases": ph, "laptop_takes_eps": taken,
                              "extra_runs": runs_extra, "run": run_id or "primary",
                              "partial_eps": sorted(e for e in ready_eps if ((ready or {}).get("episodes") or {}).get(str(e), {}).get("partial")),
                              "rule": "K-OPS-N04 only = 分区 ∩ 已准备好的集（L-202：含按镜就绪的 partial 集）；hold = 别的机器的道；paused 跟随笔记本全局暂停；"
                                      "K-OPS-N06 临时覆盖：phase=laptop 的服务器分区由笔记本经隧道派、服务器 only=__none__"}}
    if host != "laptop":                     # 笔记本的 paused 就是全局开关本身，不改
        lc0 = laptop_ctrl or {}
        fields.update(reason_kind=(lc0.get("reason_kind") or "global") if gp else None, expires_at=lc0.get("expires_at") if gp else None)
        fields.update(paused=gp, paused_by=(f"GLOBAL:{by}" if gp else None),
                      note=(f"跟随笔记本全局暂停（{by}）" if gp else
                            (f"NETFIX 临时覆盖 {ph.get(host)}：本机分区 ep{eps} 由笔记本经隧道派，本机不派" if ph.get(host) in ON_LAPTOP
                             else f"SERVER_RESIDENT {host}：只派 ep{eps} ∩ 已准备好的集 {ready_eps}")))
    return fields


def live_leases(eps: list[int], now_t: float | None = None) -> list[str]:
    """笔记本 producer 在途（租约没到期）的对象里属于这些集的"""
    now_t = now_t or time.time()
    out = []
    for f in (LEASES.glob("*.json") if LEASES.exists() else []):
        d = jl(f, {}) or {}
        if float(d.get("until") or 0) <= now_t:
            continue
        if d.get("pid") and not _pid_alive(int(d["pid"])):     # 01:1x 实测：producer 重启后旧进程的租约 until 还远，但持有者已死 = 不在途
            continue
        name = f.stem
        if any(f"ep{e:02d}-" in name for e in eps):
            out.append(name)
    return out


def _pid_alive(pid: int) -> bool:
    try:
        sys.path.insert(0, str(ROOT / "tools/netfix"))
        import tunnel_supervisor as TS
        return TS.pid_alive(pid)
    except Exception:  # noqa: BLE001
        return True


# K-OPS-F18（FACTORY 11-02 17:1x）：这里只推派单输入数据，不推代码——dispatch.py / state_paths.py 以前随这里推上服务器，绕过发版（又一个双入口）
PUSH_FILES = ["data/netfix/override_state.json", "data/netfix/laptop_ctrl.json", "data/autopilot/ready_episodes.json",
              "data/state/netfix/override.json",
              "data/state/netfix/partition.json", "config/netfix/override.json", "config/netfix/partition.json", "config/pipeline/runs.json"]
PUSHED_DIR = ROOT / "data/netfix/pushed"          # 每台上次推上去的 partition（三方合并的“共同祖先”）
MERGE_FIELDS = ("retired_lanes", "_lent_lanes", "_temp_holds")   # 多写者字段（DEBUG-RSI 兜底进程 / 人工借道会直接改）


def inputs_sig() -> str:
    """派单输入的指纹：任一变了就重推（借道写进 partition 后自动生效，不再等阶段变化）"""
    import hashlib
    h = hashlib.sha256()
    rels = [r for r in PUSH_FILES if not r.startswith("data/netfix/override_state")] + \
        sorted(f.relative_to(ROOT).as_posix() for f in (ROOT / "data/autopilot/runs").glob("*/ready_episodes.json"))
    for rel in rels:
        try:
            h.update(rel.encode() + b"\0" + (ROOT / rel).read_bytes())
        except OSError:   # arch-ok: 文件不在也是一种状态——把“缺失”编进指纹（出现 / 消失都会触发重推）
            h.update(rel.encode() + b"\0<missing>")
    return h.hexdigest()[:16]


def _lst_merge(base: list, mine: list, theirs: list) -> list:
    """集合三方合并：两边都有的留；任一边新加的留；任一边删掉祖先里有的 → 删"""
    b, m, t = set(base or []), set(mine or []), set(theirs or [])
    keep = (m & t) | (m - b) | (t - b)
    order = list(mine or []) + [x for x in (theirs or []) if x not in (mine or [])]
    return [x for x in order if x in keep]


def _dict_merge(base: dict, mine: dict, theirs: dict) -> dict:
    """按键三方合并：本机改了（含删）用本机；否则服务器改了用服务器；两边都改了取 at / until 更晚的那份"""
    base, mine, theirs = base or {}, mine or {}, theirs or {}
    out = {}
    for k in set(base) | set(mine) | set(theirs):
        b, m, t = base.get(k), mine.get(k), theirs.get(k)
        if m != b and t != b and m is not None and t is not None:
            key = lambda v: str((v or {}).get("at") or (v or {}).get("until") or "")   # noqa: E731
            v = m if key(m) >= key(t) else t
        elif m != b:
            v = m
        elif t != b:
            v = t
        else:
            v = b
        if v is not None:
            out[k] = v
    return out


def merge_partition(base: dict | None, mine: dict, theirs: dict | None) -> dict:
    """Top15 #5 多写者：推送前和服务器现有 partition 三方合并；借道相关字段按上面的规则，其余字段以笔记本为准。
    没有祖先（第一次）时，按“服务器那份当祖先”退化为笔记本为准，但借道字段取两边并集（宁可多 hold，不丢借道）"""
    out = json.loads(json.dumps(mine))
    if theirs is None:
        return out
    b = base if base is not None else {}
    for f in MERGE_FIELDS:
        if base is None:
            if isinstance(mine.get(f), list) or isinstance(theirs.get(f), list):
                out[f] = _lst_merge([], mine.get(f) or [], theirs.get(f) or [])
            else:
                out[f] = _dict_merge({}, mine.get(f) or {}, theirs.get(f) or {})
        elif isinstance(mine.get(f, b.get(f)), list) or isinstance(theirs.get(f), list):
            out[f] = _lst_merge(b.get(f) or [], mine.get(f) or [], theirs.get(f) or [])
        else:
            out[f] = _dict_merge(b.get(f) or {}, mine.get(f) or {}, theirs.get(f) or {})
    return out


PARTITION_LOCK = ROOT / "data/netfix/partition.lock"


class partition_lock:
    """partition.json 的跨进程写锁（11-02 DEBUG-RSI：两个归还脚本同时读-改-写丢了 gpu33:3）。
    所有改 config/netfix/partition.json 的写者都要：with dispatch.partition_lock(): 读 → 改 → js 原子写。
    Windows 用 msvcrt，服务器用 fcntl；拿不到锁就等（最多 timeout 秒），超时抛 TimeoutError"""

    def __init__(self, timeout: float = 30, path: Path = PARTITION_LOCK):
        self.timeout, self.path, self.f = timeout, Path(path), None

    def __enter__(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.f = open(self.path, "a+")
        t0 = time.time()
        while True:
            try:
                if os.name == "nt":
                    import msvcrt
                    self.f.seek(0)
                    msvcrt.locking(self.f.fileno(), msvcrt.LK_NBLCK, 1)
                else:
                    import fcntl
                    fcntl.flock(self.f.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
                return self
            except OSError:
                if time.time() - t0 > self.timeout:
                    self.f.close()
                    raise TimeoutError(f"partition 锁 {self.path} 等了 {self.timeout}s 仍被占用")
                time.sleep(0.2)

    def __exit__(self, *a):
        try:
            if os.name == "nt":
                import msvcrt
                self.f.seek(0)
                msvcrt.locking(self.f.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.f.fileno(), fcntl.LOCK_UN)
        finally:
            self.f.close()
        return False


def held_lanes(part: dict, now_t: float | None = None) -> set:
    """所有 producer（主剧 + 每个 run）一律 hold 的道：退役道 + 未到期借出道 + 临时 hold（12:2x DEBUG-RSI：第二季 control 漏了借出道）"""
    from datetime import datetime
    now_t = now_t or time.time()

    def alive(v) -> bool:
        u = (v or {}).get("until") or (v or {}).get("expires_at")
        if not u:
            return True
        try:
            d = datetime.fromisoformat(str(u))
            if d.tzinfo is None:          # AUDIT-PERF 11-05（K-OPS-E18 / I10）：无时区串按项目时区 +09:00 读，与 producer.ts_epoch 同口径
                from datetime import timedelta, timezone   # （以前 mktime 按本机时钟：笔记本美东 → 借出道“到期”判错 14 h）
                d = d.replace(tzinfo=timezone(timedelta(hours=9)))
            return d.timestamp() > now_t
        except ValueError:   # arch-ok: 到期时间写坏 → 当作还在借（失败关闭：宁可多 hold 一条道，也不往借出道派单）
            return True
    # W44 ④（11-04 02:25 gpu33:0 被 hold 到 02:40 之后）：tools/debug/lanes.py hold()/lend() 同时写 retired_lanes 和 _temp_holds/_lent_lanes，
    # 到期后 sweep 没跑，retired_lanes 里那条就永久 hold。有借道 / 临时 hold 记录的道以记录到期时间为准；没有记录的 retired_lanes = 真退役
    rec: dict = {}
    for f in ("_lent_lanes", "_temp_holds"):
        for k, v in (part.get(f) or {}).items():
            rec[k] = rec.get(k, False) or alive(v)
    out = {ln for ln in part.get("retired_lanes") or [] if ln not in rec}
    out |= {k for k, a in rec.items() if a}
    return out


def push_server_control(host: str) -> dict:
    """阶段一变就把覆盖状态 + 派单输入推到该服务器并立刻重算 control（01:1x DEBUG-RSI 报：gpu36 已交还 server，
    服务器上却还是切换前推上去的 draining → only=__none__，两条道空着）。走 rssh 主连接，失败返回错误（下一拍重试）"""
    import io
    import tarfile
    sys.path.insert(0, str(ROOT / "tools/netfix"))
    import rssh
    off = "/root/work/fredw/offline_20261101"
    # Top15 #5 多写者：先取服务器上的 partition，与本机、上次推上去的那份三方合并；合并结果先写回本机（原子）再推，借道记录不丢
    migrate_state()
    part_p = PARTITION
    base_p = PUSHED_DIR / host / "partition.json"
    mine = jl(part_p, {}) or {}
    rr = rssh.run(host, f"cat {off}/repo/data/state/netfix/partition.json 2>/dev/null || cat {off}/repo/config/netfix/partition.json", timeout=60)
    theirs = None
    if rr.returncode == 0:
        try:
            theirs = json.loads(rr.stdout.decode("utf-8", "replace"))
        except ValueError:   # arch-ok: 服务器副本坏 / 空 → 当作“服务器没有”，三方合并退化为以笔记本为准，随后整份推上去修好服务器副本
            theirs = None
    elif rr.returncode == 255:
        return {"rc": 255, "only_n": None, "runs": None, "err": "取服务器 partition 失败（主连接不在），本轮不推"}
    with partition_lock():                         # 读-并-写在锁里：别的写者（DEBUG 借道 / 归还脚本）共用同一把锁
        mine = jl(part_p, {}) or {}                # 锁内重读，取最新
        old_local = jl(PARTITION_OLD, None)        # 兼容期：还没迁的写者（旧位置）晚于新位置写过 → 一并三方合并进来，不丢
        if old_local is not None and PARTITION_OLD.is_file() and part_p.is_file() and \
                PARTITION_OLD.stat().st_mtime > part_p.stat().st_mtime + 1:
            mine = merge_partition(jl(base_p, None), mine, old_local)
        merged = merge_partition(jl(base_p, None), mine, theirs)
        if merged != (jl(part_p, {}) or {}):
            SP.write_state(PART_NAME, merged)      # 只写新位置（ARCH_ROADMAP §10）
        if old_local is not None and old_local != merged:
            js(PARTITION_OLD, merged)              # 兼容期：旧位置镜像成同一份，给还没迁的读方（sv-11 删）
        ov = read_override()
        if ov and not SP.state_path(OV_NAME).is_file():
            SP.write_state(OV_NAME, ov)
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        rels = PUSH_FILES + [f.relative_to(ROOT).as_posix() for f in (ROOT / "data/autopilot/runs").glob("*/ready_episodes.json")]
        for rel in rels:                             # 多剧并行：各 run 的 ready 一起推
            if (ROOT / rel).exists():
                tf.add(str(ROOT / rel), arcname=rel)
    r = rssh.run(host, f"cd {off}/repo && tar xf - && TZ=Asia/Tokyo {off}/venv/bin/python tools/netfix/dispatch.py server-control "
                       f"{host} --laptop-ctrl data/netfix/laptop_ctrl.json --write", input=buf.getvalue(), timeout=180)
    out = r.stdout.decode("utf-8", "replace")
    only, runs = None, None
    for ln in out.strip().splitlines():          # 第一行主剧 control；有多剧时第二行 {"runs": {...}, "rc": n}
        try:
            d = json.loads(ln)
        except ValueError:   # arch-ok: 远端输出里夹杂的非 JSON 行（警告 / 日志）跳过；只认 JSON 行，结果缺失时 only_n=None 上报
            continue
        if "only" in d:
            only = d["only"]
        if "runs" in d:
            runs = d["runs"]
    if r.returncode in (0, 2):                     # 推上去了（rc=2 = 某个 run 校验没过被拒写，partition 本身已到）：记共同祖先
        js(base_p, merged)
    return {"rc": r.returncode, "only_n": len(only) if isinstance(only, list) else None, "runs": runs,
            "merged_from_server": theirs is not None and any(merged.get(f) != mine.get(f) for f in MERGE_FIELDS),
            "err": (r.stderr.decode("utf-8", "replace")[-200:] or out[-300:]) if r.returncode else ""}


def reconcile(now_t: float | None = None, write: bool = True) -> dict:
    """笔记本侧状态机（监管进程每拍调用）：按 data/autopilot/assets_ready.json 逐台交还。
    laptop →（该台 ready=true）→ draining：笔记本 only 去掉该台的集、hold 该台的道，不派新单
    draining →（笔记本在该台集上的租约全部结束）→ server：服务器 only 恢复（server-control 下一拍生效）
    覆盖关闭（override.active=false）同样走 draining 再回 server。开启只由 NETFIX / 总调度手动置 laptop（先确认服务器不在派单）。"""
    now_t = now_t or time.time()
    ov = read_override()
    st = jl(OVERRIDE_STATE, {}) or {"hosts": {}}
    hosts = st.setdefault("hosts", {})
    ar = jl(ASSETS_READY, {}) or {}
    part = partition()
    changed = []
    for h in ("gpu33", "gpu36"):
        rec = hosts.setdefault(h, {"phase": "server"})
        ph = rec.get("phase", "server")
        a = ar.get(h) or {}
        # 总调度 r2：assets_ready 曾是假的（gpu36 缺场景底图、preflight 全挡）→ 交还要两样都有：ready=true 且
        # preflight_dryrun_ok=true（FACTORY 用服务器 producer dryrun 跑 preflight，0 挡才写）
        back = (not ov.get("active")) or (bool(a.get("ready")) and a.get("preflight_dryrun_ok") is True)
        if ph == "laptop" and back:
            rec.update(phase="draining", since=iso(), why=("override 关闭" if not ov.get("active") else f"assets_ready.{h}.ready=true 且 preflight_dryrun_ok=true"))
            changed.append((h, "draining"))
        elif ph == "draining":
            busy = live_leases(part["images"].get(h) or [], now_t)
            rec["waiting_leases"] = busy
            if not busy:
                rec.update(phase="server", since=iso(), why="笔记本在途单已全部结束，交还服务器")
                changed.append((h, "server"))
    if write:
        sig = inputs_sig()
        for h in ("gpu33", "gpu36"):
            rec = hosts[h]
            # 推送触发：阶段变了，或派单输入（partition 借道 / 退役道、override、runs.json、各 run ready）变了。
            # 12:2x DEBUG-RSI：借道写进笔记本 partition 后没人推，第二季 control 缺了借出的 gpu33:1 / gpu33:3 → 往借出道派单
            if any(c[0] == h for c in changed) or rec.get("pushed_phase") != rec.get("phase") or rec.get("pushed_sig") != sig:
                try:
                    pr = push_server_control(h)
                except Exception as e:  # noqa: BLE001
                    pr = {"rc": -1, "err": repr(e)[:200]}
                rec["last_push"] = {**pr, "at": iso()}
                if pr.get("rc") == 0:
                    rec["pushed_phase"], rec["pushed_sig"] = rec.get("phase"), sig
    st["at"] = iso()
    st["active"] = bool(ov.get("active"))
    res = {"changed": changed, "phases": phases(st)}
    if write:
        old = jl(OVERRIDE_STATE, {}) or {}
        if changed or {k: v for k, v in old.items() if k != "at"} != {k: v for k, v in st.items() if k != "at"}:
            js(OVERRIDE_STATE, st)
        lc = jl(CONTROL, {}) or {}
        f = control_for("laptop", lc, jl(READY, {}) or {}, part, phases(st))
        if (lc.get("only"), lc.get("hold_lanes")) != (f["only"], f["hold_lanes"]):
            apply(CONTROL, f)
            res["laptop_control"] = {"only": len(f["only"]), "hold": f["hold_lanes"]}
        try:                                         # MERGE-OPS-O：非 legacy 剧（V2 primary）笔记本侧 control
            rc_ = laptop_run_controls(jl(CONTROL, {}) or {}, part)
            if rc_:
                res["run_controls"] = rc_
        except Exception as e:  # noqa: BLE001  # arch-ok: 各剧 control 写失败不挡主剧派单，结果里上报
            res["run_controls_err"] = repr(e)[:200]
    return res


def apply(ctrl_path: Path, fields: dict, dry: bool = False) -> dict:
    c = jl(ctrl_path, {}) or {}
    new = {**c, **fields}
    if not dry:
        js(ctrl_path, new)
    return new


SNAPSHOT = ROOT / "data/netfix/laptop_ctrl.json"


def snapshot_laptop() -> bool:
    """笔记本 control.json 的全局暂停快照（paused / paused_by / paused_at），变了才写；随 resident_sync 第一级推到服务器，
    resident_prep / server-control 据此决定服务器 producer 是否跟随暂停。监管进程每拍调用。返回是否改写"""
    c = jl(CONTROL, {}) or {}
    snap = {k: c.get(k) for k in ("paused", "paused_by", "paused_at", "note")}
    old = jl(SNAPSHOT, {}) or {}
    if {k: old.get(k) for k in snap} == snap:
        return False
    js(SNAPSHOT, {**snap, "at": iso(), "by": "NETFIX dispatch.snapshot_laptop"})
    return True


def steal_plan(states: dict[str, dict]) -> dict:
    """跨机接手评估（总调度 22:2x 问）。不执行，只说明为什么现在不做 / 什么条件下能做。
    states: {host: {"idle": bool, "unstarted_eps": [ep...]}}（由调用方从 health / attempts 算）"""
    return {"enabled": bool(partition().get("work_stealing")), "safe_now": False,
            "why": ("没有跨机共享锁：两台服务器互不访问、笔记本经跳板时通时断。安全做法只能是笔记本居中的两阶段交接："
                    "① 两台都连得上 ② 把整集从 A 的 only 撤掉、等 A 的 producer 下一拍确认（心跳 only 不含该集、租约里没有该集对象）"
                    " ③ 再把该集加进 B 的 only、partition 记一笔 ④ 并回按新归属收文件。任一步跳板断就停在“两边都不派”（安全侧）。"
                    "粒度只能是“整集且该集一个对象都还没开始”，否则并回会两边改同一集的文件。"),
            "candidates": {h: s.get("unstarted_eps") for h, s in states.items() if s.get("idle")}}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["show", "check", "apply-laptop", "server-control"])
    ap.add_argument("host", nargs="?")
    ap.add_argument("--laptop-ctrl")
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--dry", action="store_true")
    a = ap.parse_args(argv)
    part = partition()
    if a.cmd == "check":
        errs = check_partition(part)
        print("OK" if not errs else "\n".join(errs))
        return 1 if errs else 0
    ready = jl(READY, {}) or {}
    if a.cmd == "show":
        lc = jl(CONTROL, {}) or {}
        for h in part["images"]:
            f = control_for(h, lc, ready, part)
            print(h, "paused" if f.get("paused") else "", "only", len(f["only"]) if f["only"] != [NONE] else 0, "镜",
                  "ready_eps", f["dispatch_by"]["ready_eps"], "hold", f["hold_lanes"])
        return 0
    if a.cmd == "apply-laptop":
        runs_done = laptop_run_controls(jl(CONTROL, {}), part, write=not a.dry)   # MERGE-OPS-O：笔记本侧各剧 control
        if runs_done:
            print(json.dumps({"runs": runs_done}, ensure_ascii=False))
        new = apply(CONTROL, control_for("laptop", jl(CONTROL, {}), ready, part), dry=a.dry)
        print(json.dumps({k: new.get(k) for k in ("paused", "paused_by", "hold_lanes")}, ensure_ascii=False), "only", len(new["only"]))
        return 0
    lc = jl(a.laptop_ctrl, {}) if a.laptop_ctrl else {}
    rc = 0
    out = {}
    for run_id, rd in [(None, ready)] + [(r, run_ready(r)) for r, _p in extra_runs()]:
        errs = verify_run(run_id, rd, part)
        f = control_for(a.host, lc, rd, part, run_id=run_id)
        if errs:                                  # 两台会重复派 / 有镜没人派 → 拒写，留旧 control，报警
            rc = 2
            out[run_id or "primary"] = {"refused": errs}
            continue
        if a.write:
            apply(run_control_path(run_id), f)
        out[run_id or "primary"] = f if run_id is None else {"only_n": len([x for x in f["only"] if x != NONE]), "path": str(run_control_path(run_id))}
    if a.write:
        for r in paused_runs():          # K-OPS-F20：暂停中的 run 不重算 control，但要写成 paused（不留旧的 paused=false）；
            out[r] = {"paused_by_runs_json": bool(pause_run_control(r, host=a.host, laptop_ctrl=lc, part=part))}   # MERGE-OPS-O：没有就预备
    prim = out.get("primary") or {}
    print(json.dumps(prim if "only" in prim else out, ensure_ascii=False))
    if len(out) > 1 or rc:
        print(json.dumps({"runs": {k: v for k, v in out.items() if k != "primary"}, "rc": rc}, ensure_ascii=False))
    return rc


if __name__ == "__main__":
    sys.exit(main())
