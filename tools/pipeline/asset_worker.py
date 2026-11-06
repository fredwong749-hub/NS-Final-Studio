"""阶段 A 资产作业执行器（M-AUTOPIPE-01；AUTOPIPE-A 11-03）。由常驻服务 tools/factory/autoflow_resident.py 每一拍调一次 tick()，
也可手跑：
    .venv/Scripts/python.exe -X utf8 tools/pipeline/asset_worker.py tick [--dry]        # 一拍：生成作业 + 调度执行
    .venv/Scripts/python.exe -X utf8 tools/pipeline/asset_worker.py run-job --job <作业文件> --lane gpu36:0   # 子进程：出一个作业的候选
    .venv/Scripts/python.exe -X utf8 tools/pipeline/asset_worker.py run-voice --job <作业文件>               # 子进程：音色候选
    .venv/Scripts/python.exe -X utf8 tools/pipeline/asset_worker.py status

每一拍（tick）：单实例锁 data/pipeline/asset_jobs/worker.lock → 只看 runs.json 里 preparing / active / producing 的剧 →
  ① 对该剧当前集（runs.json episode）按 episode_ready 缺口生成作业（tools/pipeline/asset_jobs.generate，幂等；每 ready_every_s 秒或登记后强制）；
  ② 收尸：running 的作业子进程没了 → failed（attempts < max_attempts 下一拍重排），道按 by=ASSET-WORKER 释放；
     超时杀子进程前按作业文件里的 proc（pid + 创建时间 + 命令行指纹）核身份，核不上不杀、定案 failed（why=pid_mismatch，W6b）；
  ③ meta 作业（display_name / 造型骨架 / 造型排期）直接从 P1 写入（apply_meta 开关）；
  ④ face / scene / sheet / item 作业：找空闲 GPU 道（排除坏卡——单一来源 config/factory/hosts.json hosts.<主机>.broken_gpus，L-194 后只剩 gpu33:2；
     再减 config exclude_lanes、别人 hold / lend 的道、队列里有活的道），
     lanes hold --by ASSET-WORKER，起子进程 run-job（每道一个，最多 max_parallel 个），用完 release（render 开关）；
  ⑤ voice 作业：起子进程 run-voice（voice_v2 --roles-file，gpu36 CPU；voice 开关）；
  ⑥ golden 作业（阶段 B）：已停（W6 11-03 / L-151），阶段 B 走 producer，资产线不再生成也不执行；历史 golden-epNN 作业 W6b 标 retired，
     心跳 golden_pending 只列仍是 pending 的遗留（正常应为空）。
开关在 config/pipeline/asset_worker.json；心跳 data/pipeline/asset_jobs/worker.json。
出图走唯一编译入口 frame_job.build_first + preflight（mode=setting_candidate 设定候选模式，I2 / I3 / I5 按规则判 na）+ postflight + Q9（设定候选口径）+ 人数 + 一次合并看图
（逐条 / 年龄 / OCR），四项全过的候选才拷进 data/review_pages/v2_assets/<run>/<job>/ 并投待办通知（owner_pick.pick_detail 文案）。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
import episode_lock as EL  # noqa: E402  清单独占旗标（PIPELINE_CHECKLIST）
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

# ------------------------------------------------------------------ 依赖整组重载（W12 RESIDENT-RELOAD，C-02）
# 常驻服务（autoflow_resident）每拍用 importlib 重新执行本文件，但本文件 import 的依赖会拿 sys.modules 里的旧模块 →
# 新 worker + 旧依赖对不上：11-03 02:17 AttributeError AUTO_PICK_KINDS（asset_jobs）、04:56 AttributeError BACKOFF_S（sop_gate），
# 后一次资产线全停到受控重启。改法 = “版本戳”：下面声明本文件在常驻进程里会用到的、常改的 tools 侧依赖；本文件每次载入、
# 引用依赖符号之前，先比对每个依赖源文件的 (mtime_ns, size) 和模块上记的戳，不一样（或没戳 = 进程早先 import 的、不知新旧）
# 就 importlib.reload（同一模块对象就地更新，常驻里别处持有的引用也一起变新）。
# 为什么放在 worker 里而不是 resident 里：依赖清单和用它的代码在同一文件，加依赖时顺手加声明；任何载入方式（常驻 / CLI / 测试）同一口径。
# 重载失败（新代码语法错 / 顶层抛错）→ 异常原样抛出，本文件载入失败 = 这一拍 asset_tick 失败关闭（不拿半新半旧的代码派作业）；
# 戳只在重载成功后更新，下一拍会再试。ns_* 包（ns_agent / ns_api / ns_schema …）不在清单里：那是库代码，有类身份 / pydantic 模型，
# 就地重载会让 isinstance 失效，改它们按惯例走受控重启。
RELOAD_DEPS: dict[str, str] = {              # sys.modules 名 → 相对仓库的源文件（只重载确实是这个文件的模块；测试替身不碰）
    "asset_jobs": "tools/pipeline/asset_jobs.py",
    "tools.master.sop_gate": "tools/master/sop_gate.py",
    "asset_checks": "tools/pipeline/asset_checks.py",   # AC_bundle 懒加载；已在 sys.modules 里才管
}
# asset_jobs 保持 02:17 修复以来的行为：每次载入无条件重载（不看戳；原有回归 test_worker_reload_keeps_asset_jobs_in_sync 按此口径）
ALWAYS_RELOAD = frozenset({"asset_jobs"})
_STAMP_ATTR = "__ns_reload_stamp__"


def _file_stamp(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:     # arch-ok: 源文件不在（打包 / 测试替身）→ 不判新旧，不重载
        return None
    return (st.st_mtime_ns, st.st_size)


def drop_pyc(src) -> None:
    """W12b（A12 第 27 轮 P1-1）：重载 / 重新执行源文件前删掉它在 __pycache__ 里的字节码。
    CPython 的 pyc 只校验源文件秒级 mtime + size，同秒同 size 的改动会让 reload 执行旧字节码（戳判出变化、代码却是旧的，静默）"""
    try:
        Path(importlib.util.cache_from_source(str(src))).unlink(missing_ok=True)
    except (OSError, NotImplementedError, ValueError):   # arch-ok: 删不掉（只读 / 被占用 / 无缓存约定）→ 照常载入，下一拍再删
        pass


def import_dep(name: str, root: Path = ROOT):
    """懒加载 RELOAD_DEPS 里的依赖（如 asset_checks）：第一次 import 时先删 pyc、记下载入前的戳，
    免得下一拍 sync_deps 因“无戳”多重载一次（A12 P2-2）。已在 sys.modules 里就原样返回（新旧由 sync_deps 管）"""
    m = sys.modules.get(name)
    if m is not None:
        return m
    src = (root / RELOAD_DEPS[name]).resolve()
    stamp = _file_stamp(src)
    drop_pyc(src)
    m = importlib.import_module(name)
    f = getattr(m, "__file__", None)
    if stamp is not None and f and Path(f).resolve() == src:
        setattr(m, _STAMP_ATTR, stamp)
    return m


def sync_deps(deps: dict[str, str] | None = None, root: Path = ROOT, modules: dict | None = None,
              fresh: set[str] | frozenset = frozenset()) -> list[str]:
    """按版本戳重载已载入的依赖；返回本次重载了的模块名。fresh = 本次载入才第一次 import 的（已是当前代码，只记戳不重载）。
    重载抛错原样外抛（失败关闭）"""
    mods = sys.modules if modules is None else modules
    done = []
    for name, rel in (RELOAD_DEPS if deps is None else deps).items():
        m = mods.get(name)
        f = getattr(m, "__file__", None) if m is not None else None
        src = (root / rel).resolve()
        if not f or Path(f).resolve() != src:
            continue
        stamp = _file_stamp(src)
        forced = name in ALWAYS_RELOAD and deps is None
        if not forced and (stamp is None or getattr(m, _STAMP_ATTR, None) == stamp):
            continue
        if name in fresh:               # 本次才第一次 import = 已是当前代码，只记戳
            setattr(m, _STAMP_ATTR, stamp)
            continue
        drop_pyc(src)
        importlib.reload(m)
        setattr(m, _STAMP_ATTR, stamp)
        done.append(name)
    return done


_FRESH = frozenset(n for n in RELOAD_DEPS if n not in sys.modules)
import asset_jobs as AJ  # noqa: E402
import tools.master.sop_gate as _SOP  # noqa: E402  HARNESS-O：SOP 阶段闸门
RELOADED_DEPS = sync_deps(fresh=_FRESH)      # 必须在下面任何 AJ. / _SOP. 顶层引用之前

BY = "ASSET-WORKER"
CONFIG = ROOT / "config" / "pipeline" / "asset_worker.json"
ADVANCE_STATUSES = ("preparing", "active", "producing")     # 与 autoflow_resident.ADVANCE_STATUSES 同口径
DEFAULTS = {"enabled": True, "apply_meta": False, "render": False, "voice": False, "push": True, "golden": False, "max_parallel": 2,
            "exclude_lanes": [], "hold_minutes": 15, "job_timeout_min": 90, "max_attempts": 2, "ready_every_s": 300,   # 坏卡不写这里：broken_lanes() 读 hosts.json（L-194）
            # FIX-ORCH O6（11-06）：道 hold 15 分钟（原 90）+ 作业活着时每拍续期（hold_renew）；worker 死了道最多空挂 15 分钟。作业超时单独 job_timeout_min
            "candidates": {"face": 3, "scene": 2, "sheet": 3, "item": 2}, "voice_host": "gpu36"}
_PROCS: dict[str, subprocess.Popen] = {}


def _load(name: str, rel: str):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def config(root: Path = ROOT) -> dict:
    """开关：配置文件读不出 = 全部关（失败关闭，只生成作业）"""
    p = root / "config" / "pipeline" / "asset_worker.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # arch-ok: 读不出按“全部关”处理并在心跳里报，不放行任何执行
        return {**DEFAULTS, "apply_meta": False, "render": False, "voice": False, "golden": False, "_config_error": f"{p}: {e}"}
    return {**DEFAULTS, **{k: v for k, v in d.items() if not k.startswith("_")}}


# ------------------------------------------------------------------ 单实例锁（与 autoflow_resident 同一套做法）
def lock_path(root: Path) -> Path:
    return root / "data" / "pipeline" / "asset_jobs" / "worker.lock"


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}", "/NH"], capture_output=True, text=True, timeout=30)
        return str(pid) in (r.stdout or "")
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def acquire_lock(root: Path, alive=None) -> bool:
    lk = lock_path(root)
    lk.parent.mkdir(parents=True, exist_ok=True)
    for _ in range(2):
        try:
            fd = os.open(str(lk), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(json.dumps({"pid": os.getpid(), "at": time.time()}))
            return True
        except FileExistsError:
            try:
                pid = int(json.loads(lk.read_text(encoding="utf-8")).get("pid") or 0)
            except (OSError, ValueError):   # arch-ok: 锁文件坏 = 当作陈旧，接管
                pid = 0
            if pid != os.getpid() and (alive or _pid_alive)(pid):
                return False
            lk.unlink(missing_ok=True)
    return False


def release_lock(root: Path) -> None:
    lk = lock_path(root)
    try:
        if int(json.loads(lk.read_text(encoding="utf-8")).get("pid") or 0) == os.getpid():
            lk.unlink(missing_ok=True)
    except (OSError, ValueError):   # arch-ok: 锁已不在 / 坏了 = 没什么可放
        pass


# ------------------------------------------------------------------ 剧 / 集
def active_runs(root: Path = ROOT) -> dict[str, int]:
    """{run: 当前集}：runs.json 状态在 ADVANCE_STATUSES 的剧；登记表读不出 = 一部都不做（失败关闭）"""
    try:
        d = json.loads((root / "config" / "pipeline" / "runs.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 读不出 = 不处理任何剧
        return {}
    out = {}
    for r, v in sorted((d.get("runs") or {}).items()):
        if (v or {}).get("status") in ADVANCE_STATUSES:
            out[r] = int((v or {}).get("episode") or 1)
    return out


def _has_episode(root: Path, run: str, episode: int) -> bool:
    p = AJ._runs_mod().import_path(run, root)
    if not p.is_file():
        return False
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except ValueError:    # arch-ok: 导入稿坏了 = 没有这一集可做，缺口由 episode_ready 自己报 script
        return False
    return any(int(e.get("number") or 0) == episode for e in d.get("episodes") or [])


def _due(root: Path, run: str, episode: int, every_s: float) -> bool:
    d = AJ.jobs_dir(root, run)
    if (d / "_recheck").is_file():
        return True
    p = d / f"_ready_ep{episode:02d}.json"
    if not p.is_file():
        return True
    return time.time() - p.stat().st_mtime >= every_s


# ------------------------------------------------------------------ meta：直接从 P1 写入
def hub_looks_rel() -> str:
    """造型排期文件的相对路径：只认 ns_agent.asset_refs.HUB_EP_LOOKS（资产中心 POST /api/character-hub/{cid}/schedule 写的同一份），不另写死"""
    sys.path.insert(0, str(ROOT / "services" / "agent"))
    from ns_agent import asset_refs as AR
    return str(Path(AR.HUB_EP_LOOKS).relative_to(AR.ROOT)).replace(os.sep, "/")


def apply_meta(root: Path, job: dict, pusher=None, push: bool = True) -> dict:
    spec = job.get("spec") or {}
    op, cid = spec.get("op"), spec.get("cid")
    run, ep = job["run"], int(job["episode"])
    res: dict = {"op": op, "cid": cid}
    touched: list[str] = []
    if op in ("name", "looks"):
        mp = AJ.manifest_path(root, run)
        d, sha0 = AJ._read_manifest(mp)
        entry = d.setdefault("characters", {}).setdefault(cid, {})
        if op == "name":
            entry["display_name"] = spec["display_name"]
            entry.setdefault("source", "P1 人物表（阶段 A meta 作业写入）")
            res["display_name"] = spec["display_name"]
        else:
            looks = entry.setdefault("looks", {})
            added = []
            for l in spec.get("looks") or []:
                if l["id"] in looks:
                    continue
                looks[l["id"]] = {"name": (l.get("slots") or {}).get("服装") or l["id"], "zh": l.get("zh"), "en": l.get("en"), "use": l.get("use"),
                                  "route": "server_ok", "adult": False, "items": {}, "sheet": None, "source": "P1 造型表（阶段 A meta 作业写入）"}
                added.append(l["id"])
            res["looks_added"] = added
        sha1 = AJ._write_manifest(mp, d, sha0)
        res.update(manifest_sha_before=sha0[:12], manifest_sha_after=sha1[:12])
        touched.append(str(mp.relative_to(root)).replace(os.sep, "/"))
    if op in ("schedule", "looks"):
        lid = spec.get("look")
        if lid:
            hrel = hub_looks_rel()
            hp = root / hrel
            d = AJ._read_json(hp, "造型排期 hub_episode_looks.json") if hp.is_file() else {}
            m = d.setdefault(run, {}).setdefault(cid, {})
            if m.get(str(ep)) != lid:
                m[str(ep)] = lid
                m["_by"], m["_at"] = BY, AJ._now()
                AJ.atomic_json(hp, d)
            res["schedule"] = {str(ep): lid}
            touched.append(hrel)
    res["push"] = AJ.push_files(root, touched, pusher=pusher) if (push and touched) else {"skipped": "没有要推的文件" if not touched else "push 关着"}
    return res


# ------------------------------------------------------------------ 道
def _lanes_mod():
    return _load("lanes_for_asset_worker", "tools/debug/lanes.py")


def broken_lanes(hosts_mod=None, d: dict | None = None) -> set[str]:
    """坏卡道 {"gpu33:2", ...}：单一来源 config/factory/hosts.json hosts.<主机>.broken_gpus（REVIEW-C 11-05，L-194：gpu36:2 已归 NS 出图，
    只剩 gpu33:2 坏卡；代码里不再写死任何道）。车道表读不出 / 假车道表没有 load → 直接读文件；仍读不出 = 空集（H.lanes 自己会报错）"""
    if d is None:
        try:
            d = (hosts_mod or _load("hosts_for_asset_worker", "tools/factory/hosts.py")).load()
        except Exception:  # noqa: BLE001  # arch-ok: 测试里的假 hosts 模块没有 load；退回直接读车道表文件
            try:
                d = json.loads((ROOT / "config" / "factory" / "hosts.json").read_text(encoding="utf-8"))
            except (OSError, ValueError):  # arch-ok: 车道表读不出 = 没有坏卡信息（H.lanes 读同一文件会报错，不会静默派单）
                return set()
    return {f"{hn}:{g}" for hn, h in ((d or {}).get("hosts") or {}).items() if isinstance(h, dict) for g in (h.get("broken_gpus") or [])}


def _hold_expired(h: dict, now: float | None = None) -> bool:
    """hold 带 expires_at（ISO 本地时间）且已过 → True；没有 / 读不出 = 不过期"""
    exp = (h or {}).get("expires_at")
    if not exp:
        return False
    try:
        return time.mktime(time.strptime(str(exp)[:19], "%Y-%m-%dT%H:%M:%S")) < (now or time.time())
    except (ValueError, OverflowError):   # arch-ok: 读不出到期时间 = 按没过期（保守，不抢别人的道）
        return False


def lane_roles_policy(root: Path, runs: dict | None) -> dict:
    """C1（L-206 / L-207）：资产作业能借哪些道——读 config/pipeline/lane_roles.json + 各在产剧的 data/pipeline/lane_roles_state.json（producer 写）：
    审图位（gpu33:3）永不借（不往审图卡放出图模型）；某剧有集在占卡：首尾帧段只借该段出图位、视频段一条不借（全卡出视频，资产等）。
    关 / 读不到 = {"allow": None, "deny": []}（旧行为：全部 image 道）"""
    try:
        LRO = _load("lane_roles_for_asset_worker", "tools/autopilot/lane_roles_producer.py")
        cfg = LRO.load_cfg(root)
        if not LRO.enabled(cfg):
            return {"allow": None, "deny": [], "why": "lane_roles 关"}
        acts = [a for a in (LRO.read_active(run, root) for run in (runs or {})) if a]
        if not acts:
            return LRO.asset_lane_policy(cfg, None)
        pols = [LRO.asset_lane_policy(cfg, a) for a in acts]
        allows = [set(p["allow"]) for p in pols if p["allow"] is not None]
        allow = sorted(set.intersection(*allows)) if allows else None
        return {"allow": allow, "deny": sorted({x for p in pols for x in p["deny"]}), "why": "；".join(p["why"] for p in pols)}
    except Exception as e:  # noqa: BLE001  # arch-ok: 分卡读不了 = 旧行为（审图位仍由 exclude_lanes / 总调度 hold 挡），记在 why
        return {"allow": None, "deny": [], "why": f"lane_roles 读不了：{e!r}"[:160]}


def free_lanes(cfg: dict, in_use: set[str], part: dict | None = None, probe=None, hosts_mod=None, by: str = BY,
               policy: dict | None = None) -> list[str]:
    """空闲道：车道表 image 道 − 排除表 − 别人挡着 / 借着 / hold 着的道 − 本 worker 正在用的道；再经 ComfyUI 队列探测确认没活。
    本 worker 自己残留的 hold（作业已不在跑）→ 视为空闲（下面 hold 会覆盖）。by = 借道人（阶段 B 金样用 GOLDEN-WORKER，同一套规则）。
    policy（C1，lane_roles_policy）：allow 不为 None → 只用 allow 里的道（[] = 一条不借）；deny 一律不借（审图位）"""
    H = hosts_mod or _load("hosts_for_asset_worker", "tools/factory/hosts.py")
    LN = _lanes_mod()
    part = part if part is not None else LN._read_live()
    probe = probe or LN.probe_lane
    excl = set(cfg.get("exclude_lanes") or []) | broken_lanes(H)
    pol = policy or {}
    excl |= set(pol.get("deny") or [])
    allow = pol.get("allow")
    lent, holds = part.get("_lent_lanes") or {}, part.get("_temp_holds") or {}
    cand = []
    for lane in sorted(H.lanes(role="image")):
        if lane in excl or lane in in_use or lane in lent:
            continue
        if allow is not None and lane not in allow:
            continue
        h = holds.get(lane)
        if h and _hold_expired(h):
            h = None                                           # PS-MASTER 11-06：过期的临时 hold 不算数（gpu36:1 被 11-04 的 MASTER-WSL hold 挡了两天）
        if h and h.get("by") != by:
            continue
        # PS-MASTER 11-06（L-202 卡不能空）：retired_lanes 只说明笔记本派单层不派这条道（两台服务器各自 producer 派），
        # 不代表道上有活——下面 probe 确认 ComfyUI 队列空才用；以前“retired 且没 hold 就跳过”让 gpu36:2 空转
        cand.append(lane)
    if not cand:
        return []
    # FIX-ORCH O6：各道探针并发（每道一次 rssh 5–40 s；原串行 6 道一拍最多 4 分钟）；顺序按道名不变
    from concurrent.futures import ThreadPoolExecutor

    def _p(lane):
        try:
            return probe(lane) or {}
        except Exception:  # noqa: BLE001  # arch-ok: 探不到 = 这条道这拍不用（与 ok=False 同口径）
            return {"ok": False}
    with ThreadPoolExecutor(max_workers=min(8, len(cand))) as ex:
        sts = list(ex.map(_p, cand))
    return [lane for lane, st in zip(cand, sts) if st.get("ok") and not st.get("busy")]


def hold_renew(LN, j: dict, lane: str, cfg: dict, now: float | None = None) -> bool:
    """O6：作业还活着 → hold 过半就续一次（hold_minutes 短了以后不让道在作业中途到期被别人派单）。返回是否续了"""
    now = time.time() if now is None else now
    mins = float(cfg.get("hold_minutes") or 15)
    if now - float(j.get("lane_held_t") or 0) < mins * 30:
        return False
    LN.hold(lane, mins, f"{BY} {j['id']}（续期）", by=BY)
    j["lane_held_t"] = now
    return True


# ------------------------------------------------------------------ 一拍
def tick(root: Path = ROOT, cfg: dict | None = None, runs: dict | None = None, spawn=None, lanes=None, check=None,
         pusher=None, ln=None, dry: bool = False) -> dict:
    """一拍。测试注入：runs / spawn（起子进程）/ lanes（找空闲道）/ check（episode_ready）/ pusher（推送）/ ln（lanes 模块：hold / release）"""
    cfg = cfg or config(root)
    rec = {"at": AJ._now(), "pid": os.getpid(), "by": "tools/pipeline/asset_worker.py", "runs": {}, "started": [], "meta": [], "failed": [],
           "generated": {}, "golden_pending": [], "config": {k: cfg.get(k) for k in ("apply_meta", "render", "voice", "push", "golden")}}
    if cfg.get("_config_error"):
        rec["config_error"] = cfg["_config_error"]
    if not cfg.get("enabled"):
        rec["skipped"] = "config enabled=false"
        return _hb(root, rec)
    if not acquire_lock(root):
        rec["skipped"] = "另一份 asset_worker 在跑（worker.lock）"
        return _hb(root, rec)
    try:
        runs = runs if runs is not None else active_runs(root)
        LN = ln
        in_use: set[str] = set()
        for run, ep in runs.items():
            if not _has_episode(root, run, ep):
                rec["runs"][run] = {"episode": ep, "note": "导入稿里还没有这一集"}
                continue
            if _due(root, run, ep, float(cfg.get("ready_every_s") or 300)):
                try:
                    g = AJ.generate(run, ep, root, check=check)
                    rec["generated"][run] = {k: g.get(k) for k in ("ready", "gaps", "created", "reopened", "golden", "error")}
                    (AJ.jobs_dir(root, run) / "_recheck").unlink(missing_ok=True)
                except Exception as e:  # noqa: BLE001  生成失败只记心跳，不影响执行已有作业
                    rec["generated"][run] = {"error": f"{type(e).__name__}: {e}"[:300]}
            if not dry:                                # W9：item 作业按新规格收拾（“无”/ 项目方编号收尾；旧规格定案失败的重写规格重排一次）
                try:
                    ri = AJ.refresh_items(root, run)
                    if any(ri.values()):
                        rec.setdefault("item_refresh", {})[run] = ri
                except Exception as e:  # noqa: BLE001  收拾失败只记心跳
                    rec.setdefault("item_refresh_errors", []).append(f"{run}: {type(e).__name__}: {e}"[:200])
            jobs = AJ.list_jobs(root, run)
            counts: dict[str, int] = {}
            for j in jobs:
                counts[j.get("state", "?")] = counts.get(j.get("state", "?"), 0) + 1
            rec["runs"][run] = {"episode": ep, "jobs": counts}
            # ② 收尸：子进程还活着 → 道算在用；退出了 → 作业没收尾就标失败；记过道的作业一律把道放掉（子进程自己放过也无妨，release 幂等）
            for j in jobs:
                lane = j.get("lane")
                if j.get("lane_suspect"):                  # W6c+：核不上身份定案的作业，子进程真正退出前道不放、不接管
                    _watch_suspect(root, j, cfg, rec, in_use, LN, dry)
                    continue
                if j.get("state") == "running":
                    p = _PROCS.get(j["id"])
                    ident, unverified = j.get("proc") or {}, False
                    pid = int(getattr(p, "pid", 0) or j.get("pid") or ident.get("pid") or 0)
                    why = f"子进程退出（pid {pid or None}）但作业没收尾"
                    if p is not None:
                        alive = p.poll() is None
                    elif ident.get("sig") is not None:          # W6b：按 pid + 创建时间判活（_PROCS 每拍重载为空，不能只看 pid 在不在）
                        live_sig = proc_sig(pid)
                        alive = live_sig is not None and live_sig == ident["sig"]
                        if live_sig is not None and not alive:
                            why = f"pid_mismatch：pid {pid} 还在但创建时间对不上（记的 {ident['sig']}，眼前 {live_sig}），原子进程已退出、pid 被复用；未杀"
                    else:
                        alive = _pid_alive(pid)                   # 旧作业没记身份：只能看 pid 在不在（超时也不杀，见下）
                    age, limit = _started_age_s(j), float(cfg.get("job_timeout_min") or 90) * 60     # O6：超时不再跟 hold_minutes 走
                    if alive and age is not None and age > limit and not dry:     # W6：活着但超时 = 僵尸；W6b：核过身份才杀
                        ok, detail = verify_proc(pid, ident)
                        if ok:
                            _kill(pid)
                            why = f"子进程超时（跑了 {age / 60:.0f} 分钟 > {limit / 60:.0f}，pid {pid}），核过身份（{detail}），已杀掉"
                        else:
                            why = f"pid_mismatch：子进程超时（跑了 {age / 60:.0f} 分钟 > {limit / 60:.0f}，pid {pid}）但身份核不上（{detail}），未杀"
                            unverified = True
                        rec.setdefault("timeouts", []).append({"id": j["id"], "pid": pid, "killed": ok, "why": "timeout" if ok else "pid_mismatch"})
                        alive = False
                    if alive:
                        if lane:
                            in_use.add(lane)
                            if not dry:
                                try:
                                    if hold_renew(LN or _lanes_mod(), j, lane, cfg):
                                        AJ.save_job(root, j)
                                except Exception as e:  # noqa: BLE001  续期失败记心跳；下拍再续
                                    rec.setdefault("lane_errors", []).append(f"renew {lane}: {e!r}"[:160])
                        continue
                    j = AJ.load_job(AJ.job_path(root, run, j["id"]))      # 子进程可能刚写完状态
                    if j.get("state") == "running" and unverified:
                        # W6c+（A6b P2）：身份核不上 = 子进程可能还在跑 → 先定案（不重排），不 salvage（子进程还会写候选 / 收尾）、
                        # 道也不放（下面 lane_suspect 分支续 hold），等核验到它真正退出后再放道、再接管已过检候选
                        _fail(root, j, cfg, why, rec, final=True)
                        j.update(lane_suspect=lane or j.get("last_lane"), proc_suspect={"pid": pid, "sig": ident.get("sig"), "at": AJ._now()})
                        AJ.log(j, f"身份核不上的子进程（pid {pid}）可能还在跑：道 {j['lane_suspect']} 暂不放，等它退出后再放道 / 接管候选")
                        AJ.save_job(root, j)
                        _PROCS.pop(j["id"], None)
                        _watch_suspect(root, j, cfg, rec, in_use, LN, dry)
                        continue
                    if j.get("state") == "running" and not try_salvage(root, j, cfg, rec, why):
                        _fail(root, j, cfg, why, rec)
                    _PROCS.pop(j["id"], None)
                if j.get("state") == "failed" and not j.get("final"):      # 子进程自己标的失败：按 attempts 决定重排还是定案
                    _fail(root, j, cfg, str(j.get("error") or "失败"), rec)
                if not lane:
                    continue
                if lane:
                    LN = LN or _lanes_mod()
                    if not dry:
                        try:
                            LN.release(lane, by=BY, kind="hold")
                        except Exception as e:  # noqa: BLE001  放道失败记心跳；到期自动清
                            rec.setdefault("lane_errors", []).append(f"{lane}: {e!r}"[:160])
                    j["lane"] = None
                    j["last_lane"] = lane
                    AJ.save_job(root, j)
            # ②b W-FIX-PIPE #13：已定案失败、还没升级过的旧作业 → 同一条路（换种子重排 / 挑一张 / 需要修改描述），每拍最多 ESCALATE_PER_TICK 个
            if not dry:
                for j in [j for j in jobs if j.get("state") == "failed" and j.get("final") and not j.get("escalated")
                          and not j.get("lane_suspect") and j.get("kind") in AJ.RENDER_KINDS][:ESCALATE_PER_TICK]:
                    try:
                        after_final_fail(root, j, cfg, str(j.get("error") or "失败"), rec)
                    except Exception as e:  # noqa: BLE001  # arch-ok: 升级出错只记心跳，下拍再试
                        rec.setdefault("escalate_errors", []).append(f"{j.get('id')}: {type(e).__name__}: {e}"[:200])
            # ③ meta
            for j in jobs:
                if j.get("kind") != "meta" or j.get("state") != "pending":
                    continue
                if not cfg.get("apply_meta"):
                    rec["meta"].append({"id": j["id"], "skipped": "apply_meta 关着"})
                    continue
                if dry:
                    rec["meta"].append({"id": j["id"], "dry": True})
                    continue
                try:
                    j["attempts"] = int(j.get("attempts") or 0) + 1
                    res = apply_meta(root, j, pusher=pusher, push=bool(cfg.get("push")))
                    j.update(state="done", result=res, done_at=AJ._now())
                    AJ.log(j, f"从 P1 写入：{res.get('op')}")
                    AJ.save_job(root, j)
                    (AJ.jobs_dir(root, run) / "_recheck").write_text(AJ._now(), encoding="utf-8")
                    rec["meta"].append({"id": j["id"], "ok": True})
                except Exception as e:  # noqa: BLE001  写入失败 → failed 带原因
                    _fail(root, j, cfg, f"{type(e).__name__}: {e}"[:300], rec)
            # ④ 出图作业
            # ④0 派生资产（sheet / item）还停在“等项目方挑”的（规则上线前投的）：按分数自动选用（总调度 11-03）
            for j in jobs:
                if j.get("kind") in AJ.AUTO_PICK_KINDS and j.get("state") == "awaiting_pick" and not dry and AJ.delegate_active(root)[0]:
                    try:
                        got = auto_pick_waiting(root, j)
                        if got:
                            rec.setdefault("auto_picked", []).append({"id": j["id"], **got})
                    except Exception as e:  # noqa: BLE001  自动选用失败：留在待选，记心跳
                        rec.setdefault("auto_pick_errors", []).append(f"{j['id']}: {e!r}"[:200])
            # ④a 从设定图裁单品（CPU + 本地看图，不占 GPU 道）：裁不出来的才落到 ④ 出候选
            for j in jobs:
                if not (j.get("kind") == "item" and j.get("state") == "pending" and is_crop_job(j)):
                    continue
                if dry or not cfg.get("crop", True):
                    rec.setdefault("crop_waiting", []).append(j["id"])
                    continue
                try:
                    _start(root, j, None, spawn, rec)
                except Exception as e:  # noqa: BLE001
                    _fail(root, j, cfg, f"起裁图子进程失败：{e!r}"[:300], rec)
            jobs = [j for j in jobs if not (j.get("kind") == "item" and is_crop_job(j))]
            pend = [j for j in jobs if j.get("kind") in AJ.RENDER_KINDS and j.get("state") == "pending"]
            # W6c（A6b P2）：身份核不上的子进程还没确认退出（lane_suspect 还在）——即便被人工 requeue 成 pending，也不起新子进程、不 salvage
            susp = [j["id"] for j in pend if j.get("lane_suspect")]
            if susp:
                rec.setdefault("suspect_waiting", []).extend(susp)
                pend = [j for j in pend if not j.get("lane_suspect")]
            back = [j for j in pend if _backing_off(j)]  # W6c 追加：上次候选没测出（看图服务不可用）→ 退避期内不起子进程
            if back:
                rec.setdefault("unmeasured_backoff", []).extend({"id": j["id"], "retry_after": j.get("retry_after")} for j in back)
                pend = [j for j in pend if j not in back]
            if not dry:                               # W6：上次没收尾留下够数的过检候选 → 直接接管，不占道重出
                pend = [j for j in pend if not try_salvage(root, j, cfg, rec, "上次子进程没收尾")]
            gated = [j for j in pend if j.get("kind") == "sheet" and not AJ.registered_face(root, run, (j.get("spec") or {}).get("cid") or "")]
            if gated:                                  # ISS-1103-004547-ca20：脸没登记，设定图不派
                rec.setdefault("sheet_waiting_face", []).extend(j["id"] for j in gated)
                pend = [j for j in pend if j not in gated]
            pend = sop_filter(root, run, pend, rec)   # HARNESS-O：SOP 阶段闸门（没过导入闸门的集不出资产候选）；ISS-1103-033742-73be：没变就退避
            lock = EL.active(root)                    # 清单独占：一集在跑时（episode_run 旗标），资产 render 不占 GPU 道
            if pend and cfg.get("render") and lock:
                rec.setdefault("render_skipped_episode_lock", {"run": lock.get("run"), "ep": lock.get("ep"), "until": lock.get("until")})
            if pend and cfg.get("render") and not dry and not lock:
                slots = max(0, int(cfg.get("max_parallel") or 1) - len(in_use))
                if slots:
                    LN = LN or _lanes_mod()
                    pol = lane_roles_policy(root, runs)        # C1：按工位分卡 / 占卡集的阶段限道（审图位永不借；视频段不借）
                    if pol.get("allow") is not None or pol.get("deny"):
                        rec["lane_roles_policy"] = pol
                    try:
                        free = (lanes(cfg, in_use) if lanes else free_lanes(cfg, in_use, policy=pol))[:slots]
                    except Exception as e:  # noqa: BLE001  探不到道 = 这拍不派
                        free, rec["lane_errors"] = [], rec.get("lane_errors", []) + [f"free_lanes: {e!r}"[:160]]
                    for j, lane in zip(pend, free):
                        try:
                            LN.hold(lane, float(cfg.get("hold_minutes") or 15), f"{BY} {j['id']}", by=BY)
                            j["lane_held_t"] = time.time()
                            _start(root, j, lane, spawn, rec)
                            in_use.add(lane)
                        except Exception as e:  # noqa: BLE001
                            _fail(root, j, cfg, f"起子进程失败：{e!r}"[:300], rec)
            elif pend:
                rec.setdefault("render_waiting", []).extend(j["id"] for j in pend)
            # ⑤ 音色
            for j in jobs:
                if j.get("kind") != "voice" or j.get("state") != "pending":
                    continue
                if not cfg.get("voice") or dry:
                    rec.setdefault("voice_waiting", []).append(j["id"])
                    continue
                try:
                    _start(root, j, None, spawn, rec)
                except Exception as e:  # noqa: BLE001
                    _fail(root, j, cfg, f"起子进程失败：{e!r}"[:300], rec)
            # ⑥ 阶段 B 已停：只把仍是 pending 的遗留 golden 作业列出来提醒（retired 的不列）
            rec["golden_pending"].extend(f"{run}/{j['id']}" for j in jobs if j.get("kind") == "golden" and j.get("state") == "pending")
    finally:
        release_lock(root)
    return _hb(root, rec)


# ------------------------------------------------------------------ SOP 闸门退避（ISS-1103-033742-73be，WATCHDOG 11-03）
# 事故：导入闸门 reopened 期间，每拍（30 s）每个待出图作业各调一次 sop_gate.require → violations.jsonl 30 分钟 52 条一模一样的
# observe 违规；改 enforce 后会变成每 30 s 两次被挡。根因：worker 不看闸门状态就硬试、按作业而不是按集判、没有退避。
# 改法：按 (run, 集) 调 sop_gate.require_backoff（W8 / A1-5：judge + 退避的唯一实现，producer 派单也用它，L-137）。
# A1-6：签名只用稳定键（缺口阶段名 + 状态码 + 闸门配置），不含“第 N 次”计数 / 时间（原来签 missing 全文，计数一变就重置）。
# 状态放文件不放内存（常驻服务每拍 importlib 重载本文件）：<asset_jobs>/<run>/_sop_backoff.json，键 epNN。
SOP_STAGE = "资产就绪"
SOP_BY = "asset_worker"
SOP_BACKOFF_S = _SOP.BACKOFF_S       # 兼容名：退避阶梯在 sop_gate.BACKOFF_S


def _sop_state_path(root: Path, run: str) -> Path:
    return AJ.jobs_dir(root, run) / "_sop_backoff.json"


def sop_filter(root: Path, run: str, pend: list[dict], rec: dict, now: float | None = None, sop=None) -> list[dict]:
    """按集过 SOP 闸门（sop_gate.require_backoff：退避 + 去重计数）。返回放行的作业；挡掉的写 rec["sop_gate_blocked"]，退避信息写 rec["sop_gate_backoff"]"""
    if not pend:
        return pend
    sop = sop or _SOP
    now = time.time() if now is None else now
    sp = _sop_state_path(root, run)
    eps: dict[int, list[dict]] = {}
    for j in pend:
        eps.setdefault(int(j.get("episode") or 1), []).append(j)
    out: list[dict] = []
    for ep, jobs in sorted(eps.items()):
        key = f"ep{ep:02d}"
        try:
            r = sop.require_backoff(run, ep, SOP_STAGE, root=root, by=SOP_BY, now=now, state_path=sp, key=key)
        except OSError as e:            # arch-ok: 退避状态写不进只记心跳；本集本拍按挡处理（失败关闭）
            rec.setdefault("sop_gate_errors", []).append(repr(e)[:160])
            rec.setdefault("sop_gate_blocked", []).extend(f"{j.get('id')}: 闸门状态读写失败" for j in jobs)
            continue
        if r.get("cleared"):
            rec.setdefault("sop_gate_cleared", []).append(f"{run} {key}")
        if r.get("allow"):
            out += jobs
        else:
            rec.setdefault("sop_gate_blocked", []).extend(f"{j.get('id')}: {r.get('error') or '闸门未过'}"[:300] for j in jobs)
        if r.get("backoff"):
            rec.setdefault("sop_gate_backoff", []).append({"run": run, "ep": ep, **r["backoff"]})
    return out


def _fail(root: Path, j: dict, cfg: dict, why: str, rec: dict, final: bool = False) -> None:
    """final=True：不重排直接定案（W6b：超时但身份核不上的子进程可能还在跑，不能再起一个抢同一条道）"""
    j["attempts"] = int(j.get("attempts") or 0)
    retry = not final and j["attempts"] < int(cfg.get("max_attempts") or 2)
    j.update(state="pending" if retry else "failed", error=why, pid=None, final=not retry)
    AJ.log(j, ("失败，下一拍重排：" if retry else "失败，不再重试：") + why)
    AJ.save_job(root, j)
    rec["failed"].append({"id": j["id"], "why": why[:120], "retry": retry})
    if not retry and not final:                # W-FIX-PIPE #13：定案失败不留死角——换种子重排 / 差一点候选卡 / 需要修改描述卡
        try:
            if after_final_fail(root, j, cfg, why, rec) != "skip":
                return
        except Exception as e:  # noqa: BLE001  # arch-ok: 升级动作出错 → 退回原来的卡点登记（下面），记心跳
            rec.setdefault("escalate_errors", []).append(f"{j.get('id')}: {type(e).__name__}: {e}"[:200])
    if not retry:
        try:
            AJ._report(root, j["run"], j.get("episode") or 0, "8 资产就绪", f"资产作业 {j['id']}（{j.get('who')}）连续失败：{why}", True,
                       ("内容真不过：要项目方挑场景底图（owner_pick 待办 " + str(j.get("pick_id")) + "）；或总调度 asset_jobs.py requeue 重排"
                        if j.get("kind") == "scene" and "张不过" in why and not str(why).startswith("没有候选过检（0 张不过")
                        else "看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state 改回 pending"))
        except Exception:  # noqa: BLE001  登记卡点失败不影响作业状态
            pass


# W-FIX-PIPE #13（SCAN_20261107，L-212）：资产作业定案失败后没人管（item-ch_jiang_yubai-A-outfit1 失败两次，没有卡）。改：
#   ① 定案失败（内容不过，非身份核不上）→ 自动换一批没用过的种子重排，最多 auto_requeue_max 次（config/pipeline/asset_worker.json，默认 2）；
#   ② 用尽 → 待你看“需要修改描述”（owner_queue kind=asset_revise：名字 + 现在的描述 + 一直卡在哪一句大白话 + 唯一动作“修改”）。
#      PS-MASTER 11-07：“只给看通过的图”优先——没过的候选一律不给看。项目方写的一句进作业 owner_notes → _compile 加进提示词 → 重排。
#      不是内容不过（子进程没收尾 / 起不来）→ 原来的“连续失败”卡点交总调度。
#   每个作业只升级一次（job.escalated）；tick 每拍顺带扫已定案没升级的旧作业（每拍最多 ESCALATE_PER_TICK 个）。
AUTO_REQUEUE_MAX = 2
ESCALATE_PER_TICK = 3


def _main_problem(why: str) -> str:
    """一句大白话：这件东西一直卡在哪"""
    m = re.search(r"Q9 报的缺陷：(?:设定候选口径：)?([^（；|｜]+)", str(why))
    if m:
        return m.group(1).strip()[:60]
    m = re.search(r"：(\d+ 张候选里：[^。]+)", str(why))
    return (m.group(1) if m else str(why))[:80]


def escalate(root: Path, j: dict, why: str, rec: dict) -> str:
    """重排用尽 → need_revise（内容不过：待你看“需要修改描述”）/ reported（非内容失败：原“连续失败”卡点）"""
    sp = j.get("spec") or {}
    who = sp.get("name") or j.get("target")
    what = {"face": "身份脸", "scene": "场景底图", "sheet": "造型设定图"}.get(j.get("kind") or "", f"单品“{sp.get('label') or j.get('target')}”")
    tries = int(j.get("auto_requeues") or 0)
    if not any(k in str(why) for k in ("张不过", "preflight 不过", "过检")):
        # 不是内容不过（子进程没收尾 / 起不来 / 写入失败）：改描述没用，按原来的“连续失败”卡点交总调度（不说成要项目方改）
        AJ._report(root, j["run"], j.get("episode") or 0, "8 资产就绪", f"资产作业 {j['id']}（{j.get('who')}）连续失败（自动重排 {tries} 次后）：{why}", True,
                   "看 data/pipeline/asset_jobs/<run>/<job>.json 的 log；修好后把 state 改回 pending")
        j.update(escalated={"at": AJ._now(), "kind": "reported", "why": str(why)[:200]})
        AJ.save_job(root, j)
        rec.setdefault("escalated", []).append({"id": j["id"], "kind": "reported"})
        return "reported"
    prob = _main_problem(why)
    line = f"需要修改描述：{who}的{what}换了 {tries + 1} 批种子都出不来（一直卡在：{prob}）"
    req = {"id": f"rv:{j['id']}", "run": j["run"], "job": j["id"], "episode": j.get("episode"), "asset_kind": j.get("kind"),
           "name": who, "what": what, "spec_text": str(sp.get("label") or sp.get("object") or sp.get("img") or "")[:160], "reason": prob,
           "source": "资产线（自动重排用尽）"}
    try:
        AJ.guard_run(root, j["run"])
        _owner_queue().enqueue_asset_revise(root, req)
        how = "待你看“需要修改描述”"
    except Exception as e:  # noqa: BLE001  # arch-ok: 投不进待你看 → 退回卡点板（不静默），记心跳
        rec.setdefault("escalate_errors", []).append(f"{j['id']}: enqueue_asset_revise {type(e).__name__}: {e}"[:200])
        AJ._report(root, j["run"], j.get("episode") or 0, "8 资产就绪", line, True, "在资产中心改这一项的描述，改完系统自动重出")
        how = "卡点板（待你看投递失败）"
    j.update(escalated={"at": AJ._now(), "kind": "need_revise", "why": line, "card": req["id"]})
    AJ.log(j, f"{line} → {how}")
    AJ.save_job(root, j)
    rec.setdefault("escalated", []).append({"id": j["id"], "kind": "need_revise"})
    return "need_revise"


def _owner_queue():
    AJ._owner_pick()                        # 把 services/api 放进 sys.path（与 post_pick 同一入口）
    from ns_api import owner_queue as OQ   # noqa: PLC0415
    return OQ


def fresh_seeds(job: dict, base: int, n: int) -> list[int]:
    """从 base 起 n 粒本作业没用过的种子（人工 requeue 会把 attempts 归零 → 同一批种子重出，自动重排要真换一批）"""
    used = {c.get("seed") for c in job.get("candidates") or [] if isinstance(c, dict)}
    out, x = [], int(base)
    while len(out) < n:
        if x not in used:
            out.append(x)
        x += 1
    return out


def after_final_fail(root: Path, j: dict, cfg: dict, why: str, rec: dict) -> str:
    """定案失败之后的下一步 → requeued | need_revise | reported | skip（不适用：非出图作业 / 身份核不上 / 已升级过）"""
    if j.get("kind") not in AJ.RENDER_KINDS or j.get("lane_suspect") or j.get("escalated"):
        return "skip"
    k = int(cfg.get("auto_requeue_max", AUTO_REQUEUE_MAX))
    n = int(j.get("auto_requeues") or 0)
    if n < k and "preflight 不过" not in str(why):
        j.update(state="pending", final=False, auto_requeues=n + 1, retry_after=None)
        AJ.log(j, f"定案失败后自动换一批新种子重排（第 {n + 1}/{k} 次）：{str(why)[:160]}")
        AJ.save_job(root, j)
        rec.setdefault("auto_requeued", []).append({"id": j["id"], "n": n + 1})
        return "requeued"
    return escalate(root, j, why, rec)


def _suspect_alive(ps: dict) -> bool:
    """可疑子进程还在不在：记了创建时间就按 pid + 创建时间判（pid 被复用不算），没记只能看 pid"""
    pid = int(ps.get("pid") or 0)
    if not pid:
        return False
    if ps.get("sig") is not None:
        live = proc_sig(pid)
        return live is not None and live == ps["sig"]
    return _pid_alive(pid)


def _watch_suspect(root: Path, j: dict, cfg: dict, rec: dict, in_use: set, LN, dry: bool) -> None:
    """W6c+（A6b P2）：身份核不上而定案的作业——子进程还活着：道算在用、续 hold（不让本 worker / 别人接着用）；
    核验到已退出：放道、清 lane_suspect，再按已落盘的过检候选接管（先核验后 salvage）"""
    lane, ps = j.get("lane_suspect"), j.get("proc_suspect") or {}
    if _suspect_alive(ps):
        if lane:
            in_use.add(lane)
            if not dry:
                try:
                    LN = LN or _lanes_mod()
                    LN.hold(lane, float(cfg.get("hold_minutes") or 90), f"{BY} {j['id']}（身份核不上的子进程未退出）", by=BY)
                except Exception as e:  # noqa: BLE001  续 hold 失败只记心跳（in_use 已挡住本 worker）
                    rec.setdefault("lane_errors", []).append(f"{lane}: {e!r}"[:160])
        rec.setdefault("lane_suspect", []).append({"id": j["id"], "lane": lane, "pid": ps.get("pid")})
        return
    if dry:
        return
    j = AJ.load_job(AJ.job_path(root, j["run"], j["id"]))           # 子进程退出前可能补写过候选
    if lane:
        try:
            (LN or _lanes_mod()).release(lane, by=BY, kind="hold")
        except Exception as e:  # noqa: BLE001  放道失败：到期自动清
            rec.setdefault("lane_errors", []).append(f"{lane}: {e!r}"[:160])
    j.pop("lane_suspect", None)
    j.update(lane=None, last_lane=lane or j.get("last_lane"))
    AJ.log(j, f"身份核不上的子进程（pid {ps.get('pid')}）已确认退出，放道 {lane}")
    AJ.save_job(root, j)
    rec.setdefault("lane_suspect_released", []).append({"id": j["id"], "lane": lane})
    try_salvage(root, j, cfg, rec, f"身份核不上的子进程（pid {ps.get('pid')}）已确认退出")


def _settled_by_tick(root: Path, job: dict) -> dict | None:
    """子进程写盘前看一眼：tick 已把作业定案（failed + final，例如身份核不上）→ 返回盘上那份，子进程不得改它的状态"""
    try:
        disk = AJ.load_job(AJ.job_path(root, job["run"], job["id"]))
    except (OSError, ValueError):   # arch-ok: 读不到盘上作业 = 没被定案，照常写
        return None
    return disk if disk.get("state") == "failed" and disk.get("final") else None


def _child_save(root: Path, job: dict) -> bool:
    """子进程（run_job）写作业：盘上已被 tick 定案时状态只增不改——只并入新候选和新日志，state / error / final / pid 保持盘上的。
    返回 True = 已定案（调用方别再投待办 / 改状态）"""
    disk = _settled_by_tick(root, job)
    if disk is None:
        AJ.save_job(root, job)
        return False
    seen = {(c.get("seed"), c.get("file")) for c in disk.get("candidates") or [] if isinstance(c, dict)}
    for c in job.get("candidates") or []:
        if isinstance(c, dict) and (c.get("seed"), c.get("file")) not in seen:
            disk.setdefault("candidates", []).append(c)
    logs = disk.setdefault("log", [])
    logs.extend(x for x in job.get("log") or [] if x not in logs)
    AJ.save_job(root, disk)
    job.clear()
    job.update(disk)
    return True


def _start(root: Path, j: dict, lane: str | None, spawn, rec: dict) -> None:
    jp = AJ.job_path(root, j["run"], j["id"])
    j.update(state="running", lane=lane, attempts=int(j.get("attempts") or 0) + 1, started_at=AJ._now(), error=None, retry_after=None)
    AJ.log(j, f"起子进程（道 {lane or 'CPU'}，第 {j['attempts']} 次）")
    AJ.save_job(root, j)
    p = (spawn or _spawn)(j, jp, lane)
    pid = getattr(p, "pid", None)
    j2 = AJ.load_job(jp)                      # 子进程可能已经写过状态（跑得快 / 测试同步跑）：只在它还是 running 时补 pid，不覆盖它的收尾
    if j2.get("state") == "running":
        j2["pid"] = pid
        j2["proc"] = proc_identity(p)        # W6b：pid + 创建时间 + 命令行指纹落文件，常驻服务重载后靠它核身份
        AJ.save_job(root, j2)
    _PROCS[j["id"]] = p
    rec["started"].append({"id": j["id"], "lane": lane, "pid": pid})


def root_of_job(jp: Path) -> Path:
    """作业文件 <root>/data/pipeline/asset_jobs/<run>/<id>.json → <root>（子进程按作业所在的数据根干活，不默认真实仓库）"""
    jp = Path(jp).resolve()
    if len(jp.parents) < 5 or jp.parents[1].name != "asset_jobs" or jp.parents[2].name != "pipeline" or jp.parents[3].name != "data":
        raise RuntimeError(f"作业文件不在 <root>/data/pipeline/asset_jobs/<run>/ 下：{jp}")
    return jp.parents[4]


def _spawn(j: dict, jp: Path, lane: str | None):
    """真起子进程。ISS-1103-004549-cb05：测试里不许走到这里（测试必须注入 spawn）；子进程显式带 --root = 作业所在数据根"""
    if os.environ.get("PYTEST_CURRENT_TEST"):
        raise RuntimeError("测试里不许起真实的资产作业子进程（请注入 spawn）")
    root = root_of_job(jp)
    AJ.guard_run(root, j["run"])
    cmd = [sys.executable, "-X", "utf8", str(ROOT / "tools" / "pipeline" / "asset_worker.py")]
    if j.get("kind") == "voice":
        cmd += ["run-voice", "--job", str(jp)]
    elif is_crop_job(j):
        cmd += ["run-crop", "--job", str(jp)]
    else:
        cmd += ["run-job", "--job", str(jp), "--lane", str(lane)]
    cmd += ["--root", str(root)]
    logp = jp.with_suffix(".log")
    with open(logp, "a", encoding="utf-8") as f:          # 子进程继承句柄后父进程这边就关掉（P2：不泄漏句柄）
        return subprocess.Popen(cmd, cwd=str(ROOT), stdout=f, stderr=subprocess.STDOUT,
                                env={**os.environ, "PYTHONUTF8": "1", "NS_RUN": j["run"], "NS_AGENT": BY})


def _hb(root: Path, rec: dict) -> dict:
    AJ.atomic_json(root / "data" / "pipeline" / "asset_jobs" / "worker.json", rec)
    return rec


# ------------------------------------------------------------------ 子进程：出图作业
def script_for(job: dict):
    """作业 spec → 一镜设定候选分镜（V2 中性外壳 asset_jobs.setting_script，L-126：不再拿 V1 夹具当外壳）"""
    from ns_schema.script import ScriptImport
    kind, spec, run = job["kind"], job["spec"], job["run"]
    src = f"{run} asset job {job['id']}"
    if kind in ("face", "sheet"):
        d = AJ.setting_script(run, src, spec["img"], "【现实段】中性背景", name=spec["name"], slots=spec.get("slots") or {},
                              en=spec.get("en") or "", desc=spec["desc"])
    elif kind == "item":                         # W9：场景栏写物件本身（不写 P1 原文的穿戴位置）
        d = AJ.setting_script(run, src, spec["img"], "【现实段】" + (spec.get("object") or spec.get("label") or "影棚"))
    else:
        d = AJ.setting_script(run, src, spec["img"], "【现实段】" + (spec.get("name") or "影棚"))
    return ScriptImport.model_validate(d)


def sheet_big_pieces(spec: dict) -> list[str]:
    """设定图只核大件（总调度 11-03）：按 P1_looks 单品层级（asset_refs.parse_parts）取 outfit / shoes 部件；饰品 / 指甲是 item 作业的事"""
    sys.path.insert(0, str(ROOT / "services" / "agent"))
    from ns_agent import asset_refs as AR
    zh = "｜".join(f"{k}={v}" for k, v in (spec.get("slots") or {}).items() if v)
    out = []
    for part in AR.parse_parts(zh):
        if part.slot in ("outfit", "shoes") and part.label and part.label != "无":
            out += [x.strip() for x in part.label.split("、") if x.strip()]
    return out


def cand_score(r: dict) -> float:
    """派生资产自动选用的分数 = 身份余弦（postflight Q1 evidence.sims 里本人那一项，没有 = 0）+ 看图逐项通过率（0–1）"""
    q1 = next((i for i in (r.get("postflight") or {}).get("items") or [] if i.get("id") == "Q1"), None) or {}
    sims = (q1.get("evidence") or {}).get("sims") or {}
    ident = max([float(v) for v in sims.values() if isinstance(v, (int, float))] or [0.0])
    its = (r.get("vlm") or {}).get("items") or []
    ratio = (sum(1 for x in its if x.get("ok")) / len(its)) if its else 0.0
    return round(ident + ratio, 4)


def pick_what(job: dict) -> str:
    """自动选用告知里的“什么东西”（L-198：身份脸 / 场景底图也由系统代选）"""
    sp = job.get("spec") or {}
    return {"face": "身份脸", "scene": "场景底图", "sheet": f"造型 {sp.get('look')} 的设定图"}.get(job.get("kind") or "", f"单品“{sp.get('label')}”的图")


def auto_pick_waiting(root: Path, j: dict) -> dict | None:
    """待选中的派生资产 pick（项目方还没点、不是自动选用投的）→ 用候选记录（review_dir/<id>_s<seed>.json）算分并自动选用"""
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from ns_api import owner_pick as OP
    if OP.state_of(root, j["pick_id"]).get("state"):
        return None
    req = next((r for r in _read_requests(root) if str(r.get("id")) == j["pick_id"]), None)
    if not req or req.get("auto_picked") or not req.get("candidates"):
        return None
    cands = []
    for c in req["candidates"]:
        if not c.get("contract_ok"):
            continue
        rp = (root / str(c.get("file") or "")).with_suffix(".json")
        r = AJ._read_json(rp, "候选记录") if rp.is_file() else {}
        cands.append({**c, "score": cand_score(r)})
    if not cands:
        return None
    who = j["spec"].get("name") or j.get("target")
    got = AJ.auto_pick(root, j, cands, who, pick_what(j))
    jj = AJ.load_job(AJ.job_path(root, j["run"], j["id"]))
    AJ.log(jj, f"规则上线前投的待选：系统按分数自动选用 {got['picked']}（score {got['score']}），inbox 改为“已自动选用，可修改”")
    AJ.save_job(root, jj)
    return got


def _read_requests(root: Path) -> list:
    p = AJ.requests_path(root)
    rows = AJ._read_json(p, "requests.json") if p.is_file() else []
    return rows.get("items") if isinstance(rows, dict) else rows


LABEL_ZH = {"identity": "身份", "count": "人数", "q9": "本地看图复核（Q9）", "prompt_vlm": "看图逐条核对", "ocr": "读字（OCR）", "age": "年龄观感"}


def reject_reason(r: dict) -> str:
    """一张候选的拒因（写进作业 error / log / 卡点，总调度 11-03：一眼看到卡在哪）。
    W9：写成人话——哪一项不过 + 为什么：看图逐条写“问的是什么 → 模型答了什么”，Q9 写缺陷中文名，OCR 写读到的字"""
    lab = r.get("label") or {}
    bad = [k for k, v in lab.items() if v not in ("pass", "na")]
    parts = []
    if bad:
        parts.append("、".join(f"{k}={lab[k]}（{LABEL_ZH.get(k, k)}）" for k in bad))
    q9 = next((i for i in (r.get("postflight") or {}).get("items") or [] if i.get("id") == "Q9"), None)
    if q9 and q9.get("status") not in ("pass", "na"):
        parts.append(f"Q9 报的缺陷：{str(q9.get('detail') or '')[:120]}")
    vl = r.get("vlm") or {}
    qs = vl.get("questions") or []
    for it in vl.get("items") or []:
        if not it.get("ok"):
            n = int(it.get("n") or 0)
            q = qs[n - 1] if 0 < n <= len(qs) else ""
            parts.append(f"看图第{n}条" + (f"“{q[:40]}”" if q else "") + f"→ {str(it.get('text') or '')[:80]}")
    if lab.get("ocr") == "fail":
        parts.append(f"图里读到了字：{str((vl.get('ocr') or {}).get('text') or '')[:40]}")
    if (r.get("anomaly") or {}).get("status") not in (None, "pass"):
        parts.append(f"人数：{str((r.get('anomaly') or {}).get('note') or (r.get('anomaly') or {}).get('status'))[:60]}")
    return "；".join(parts) or "未知（标签全过但 passed=false）"


def reject_summary(recs: list[dict]) -> str:
    """多张候选的拒因汇总成一句人话（卡点开头）：每一项不过了几张，按张数排"""
    from collections import Counter
    c = Counter()
    for r in recs:
        for k, v in (r.get("label") or {}).items():
            if v not in ("pass", "na"):     # W6c 追加：untested = 没测出（服务没出结论），不写成“不过”
                c[(LABEL_ZH.get(k, k), "没测出" if v == "untested" else "不过")] += 1
        qs = (r.get("vlm") or {}).get("questions") or []
        for it in (r.get("vlm") or {}).get("items") or []:
            n = int(it.get("n") or 0)
            if not it.get("ok") and 0 < n <= len(qs):
                c[(f"“{qs[n - 1][:24]}”", "不过")] += 1
    if not c:
        return ""
    return f"{len(recs)} 张候选里：" + "，".join(f"{k} {verb} {v} 张" for (k, verb), v in c.most_common(6)) + "。逐张："


def q9_queue_timeout(post: dict) -> bool:
    """Q9 没拿到看图结果（服务排队 / 未跑，evidence 里没有 model）= 不是图的问题，应重试"""
    q9 = next((i for i in (post or {}).get("items") or [] if i.get("id") == "Q9"), None)
    missing = bool(q9 and q9.get("status") in ("untested", None) and not (q9.get("evidence") or {}).get("model"))
    if missing and not q9_blocking():          # L-196（项目方 11-05“全自动，不要检测那么多了”）：Q9 不在硬闸 → 没测出只记录，不排队重试
        q9["status"] = "na"
        q9["status_recorded"] = "untested（L-196 只记录）"
        return False
    return missing


def q9_blocking(root: Path = ROOT) -> bool:
    """config/gen_contract.json blocking_items 里有没有 Q9（L-196 硬闸 = Q1 / count / text / adult）；读不到按原口径（挡）"""
    try:
        items = json.loads((root / "config" / "gen_contract.json").read_text(encoding="utf-8")).get("blocking_items")
    except (OSError, ValueError):   # arch-ok: 读不到配置 = 原口径（Q9 挡），失败偏保守
        return True
    return items is None or "Q9" in items


def is_infra_error(e: BaseException) -> bool:
    """基础设施错（出图机连不上 / 隧道断 / 超时）：不是内容不过，作业退避重试、不计 attempts（W31，ISS-1103-155905-9a0f）"""
    return type(e).__name__ in ("ComfyUnavailable", "ConnectionRefusedError", "ConnectionResetError", "TimeoutError") or (
        isinstance(e, OSError) and not isinstance(e, FileNotFoundError))


class Q9Timeout(RuntimeError):
    """本地看图复核排队超时：标 retry，不判 fail"""


def vlm_items(job: dict) -> tuple[list[str], bool]:
    kind, spec = job["kind"], job["spec"]
    if kind == "face":
        return [f"画面里只有一个人，是{spec['sex']}，接近正脸、目光落在画面右侧，胸像构图", f"外观明显是成年人（大约{spec['age']}岁，不像未成年）",
                "没有裸露", "五官清晰自然、没有畸形，手指数量正常"], True   # PS-MASTER 11-06：去掉“背景中性纯色 / 穿着日常”——与角色设定冲突（黎岸设定穿正式西装、身份脸提示词带环境光），ep02 两张身份脸 15/15 被误判；身份脸只核人数 / 成年 / 无裸露 / 五官
    if kind == "sheet":
        big = sheet_big_pieces(spec)
        return [f"画面里只有一个人，是{spec['sex']}，正面全身站立，从头到脚完整入画", f"外观明显是成年人（大约{spec['age']}岁，不像未成年）",
                f"大件穿着大致是：{'、'.join(big) or '日常便装'}（只核上衣 / 外套 / 裤裙 / 鞋这些大件的款式和颜色，饰品、手链、腕带、指甲等小件不核）",
                "背景是中性纯色，没有场景杂物", "没有裸露；五官与四肢自然、没有畸形"], True
    if kind == "scene":
        return ["画面里没有人", f"场景是：{spec.get('space')}", f"光线是：{spec.get('light')}", "画面干净，没有杂物、畸形结构"], False
    return AJ.item_checks(spec), False         # W9：物件契约（无人 / 无人体部位 / 无人脸、单一物件、颜色材质、纯白底无标志）


def count_fallback(an: dict, bundle: dict) -> dict:
    """W-ASSETS 11-06：人数检测器没出结论（rssh / 隧道断、远端无结果）时，用合并看图第 1 条（“画面里只有一个人…”）兜底判人数。
    L-196 人数是硬闸：有结论才放 / 挡；看图本身也没答（error / untested）→ 仍 untested（作业照旧退避重试）。检测器有结论的原样返回"""
    if str(an.get("status")) in ("pass", "fail"):
        return an
    it = next((x for x in (bundle.get("items") or []) if x.get("n") == 1), None)
    if bundle.get("error") or not it or it.get("untested") or not isinstance(it.get("ok"), bool):
        return an
    why = "；".join(str(r) for r in (an.get("reasons") or [])) or str(an.get("status"))
    return {**an, "status": "pass" if it["ok"] else "fail", "fallback": "vlm_item1",
            "note": f"检测器没出结论（{why[:120]}），按看图第 1 条兜底：{str(it.get('text') or '')[:80]}"}


def _compile(job: dict, root: Path = ROOT):
    for p in ("packages/schema", "services/render_router", "services/agent", "packages/qc", "tools/vqa", "tools/gen_contract", ""):
        sys.path.insert(0, str(ROOT / p))
    from ns_agent import frame_job as FJ
    os.environ["NS_RUN"] = job["run"]
    s = script_for(job)
    # 设定图：正面全身站立 → 不加剧情镜的朝向 / 视线句（“四分之三侧脸、眼睛看画内的人或物”与正面站立冲突，MERGE-IMG-O 11-03 第 6 项）
    # W9：单品是白底物件图，同样不要剧情镜的镜头语言段 / L-110 融合句 / 视线句（“人物和环境一起清楚…环境光染到皮肤和衣服上”
    # 整段进了单品提示词，11-03 第二轮 item 候选张张出模特）。frame_job 里“不加这些段”的唯一开关就是 mode="sheet"
    # （单品镜没有 cast，sheet 模式别的分支不触发）
    # W6c+（A9 P1-②）：scene 空镜底图同理——没有人，镜头语言段 / L-110 融合句（“人物和环境一起清楚…环境光染到皮肤”）
    # 进空镜提示词会往底图里长人 → 也走“不加这些段”的 sheet 模式
    # W-ASSETS 11-06：face 身份脸也走 sheet 模式 + prompt_override=spec.img（P1 年龄 / 体型 / 发型 / 标记 / 五官 + 中性纯色背景）。
    # 原来走 shot 模式：提示词模板 v2（11-05 起按剧开 image=v2）把【角色】块去掉、人物只剩“周序（服装），在画面中央……
    # 脸、发型、服装以参考图为准”——身份脸作业本来就没有参考图，年龄 / 长相全丢，再叠 135mm T1.2 光斑段：
    # 周序（25 岁）16/16 出成 40 岁中年、背景成城市夜景光斑。身份脸的唯一来源就是 spec.img（P1 原文不改），再按年龄加编译期锚点
    face = job["kind"] == "face"
    kw = {"prompt_override": face_prompt(job["spec"])} if face else {}
    jc = FJ.build_first(job["run"], s.episodes[0], s.episodes[0].shots[0], s.globals,
                        mode="sheet" if (face or job["kind"] in NO_SHOT_LANGUAGE_KINDS) else "shot", **kw)
    if face:
        jc["negative"] = "，".join(x for x in (jc.get("negative"), face_negative(job["spec"])) if x)
        jc["compile_trace"] = FJ.trace_of(jc)
    if jc.get("adult") or jc.get("route") == "local_only":
        raise RuntimeError(f"拒绝：成人 / 本地专用（{jc.get('adult_reasons') or jc.get('route_reasons')}）")
    if job["kind"] in ("scene", "item"):
        jc = empty_suffix(jc, job["spec"])
        jc["compile_trace"] = FJ.trace_of(jc)
    if job.get("owner_notes"):                    # W-FIX-PIPE #13：项目方在“需要修改描述”写的话，原样加在提示词最后
        jc["prompt"] = with_owner_notes(jc["prompt"], job)
        jc["compile_trace"] = FJ.trace_of(jc)
    if job["kind"] in ("scene", "item"):          # 物件 / 底图类：编译器再往里塞人像段就在出图前拦下（W9 守卫，W6c+ 扩到 scene）
        bad = person_phrases(jc["prompt"])
        if bad:
            what = "单品" if job["kind"] == "item" else "空镜底图"
            raise RuntimeError(f"preflight 不过：{what}提示词里混进了人像 / 镜头语言句（" + "、".join(bad) + "），不出图")
    if job["kind"] == "sheet":
        require_face_ref(root, job, jc)
    return jc


def with_owner_notes(prompt: str, job: dict) -> str:
    notes = [str(x).strip() for x in job.get("owner_notes") or [] if str(x).strip()]
    return f"{prompt}；" + "；".join(notes) if notes else prompt


NO_SHOT_LANGUAGE_KINDS = ("sheet", "item", "scene")     # 编译走 mode="sheet"（不加镜头语言段 / 融合句 / 视线句）；face 走 sheet + prompt_override（见 _compile）


# W-ASSETS 11-06：身份脸年龄锚点（编译期加，不改项目方写的 P1 / spec 原文）。写法按提示词规则用正向描述（要什么写什么），
# 否定项（皱纹 / 发际线后移…）走负面词 face_negative。分档：≤27 青年；28–34 青壮年；35–49 成熟成年；≥50 年长
AGE_ANCHORS = (
    (27, "看起来就是{age}岁的年轻人：皮肤紧致光滑有弹性、肤色均匀，发际线饱满、头发浓密乌黑，眉眼清爽有神，额头和眼周平滑，青年的脸型轮廓"),
    (34, "看起来就是{age}岁的青壮年：皮肤紧致有光泽，发际线饱满、头发浓密，面部干净利落，额头和眼周平滑"),
    (49, "看起来就是{age}岁的成熟成年人：皮肤有成熟质感但紧致，脸部轮廓清晰"),
    (999, "看起来就是{age}岁的年长成年人：面部有岁月感，神态沉稳"),
)
AGE_NEGATIVE = (
    (27, "皱纹、抬头纹、眼袋、法令纹、发际线后移、头发稀疏、白发、胡茬、中年人外观、老年人外观"),
    (34, "深皱纹、发际线后移、头发稀疏、白发、老年人外观"),
    (49, "老年人外观、满脸深皱纹"),
    (999, ""),
)


def _age_band(age: int, table: tuple) -> str:
    return next(t for hi, t in table if int(age) <= hi)


def face_prompt(spec: dict) -> str:
    """身份脸提示词 = spec.img（asset_jobs.spec_face：胸像构图 + P1 年龄 / 体型 / 发型 / 标记 / 五官 + 服装 + 中性纯色背景）
    + 按 spec.age 的年龄锚点（插在“{age}岁，”之后；找不到就接在描述末尾、背景句之前）"""
    img, age = str(spec.get("img") or ""), int(spec.get("age") or 0)
    if not img or age <= 0:
        raise RuntimeError(f"preflight 不过：身份脸作业没有 spec.img / spec.age（{spec.get('cid')}），请重新生成作业")
    anchor = _age_band(age, AGE_ANCHORS).format(age=age)
    if age <= 27:                                     # 胸像外壳句“成熟的五官轮廓”（asset_jobs.PORTRAIT 模板句，不是 P1 原文）对青年是反向锚点
        img = img.replace("成熟的五官轮廓", "清晰的五官轮廓")
    key = f"{age}岁，"
    if key in img:
        return img.replace(key, key + anchor + "，", 1)
    neutral = AJ.NEUTRAL
    return img.replace(neutral, "，" + anchor + neutral, 1) if neutral in img else f"{img}，{anchor}"


def face_negative(spec: dict) -> str:
    return _age_band(int(spec.get("age") or 0), AGE_NEGATIVE)


ITEM_PERSON_PHRASES = ("人物和场景是同一次拍摄", "人物和环境一起清楚", "环境光染到皮肤", "眼睛看", "四分之三侧脸", "人物被闪光打亮", "真实皮肤质感")


def person_phrases(prompt: str) -> list[str]:
    """单品提示词里不该出现的人像 / 剧情镜句（W9 守卫：编译器再往单品里塞人像段就在出图前拦下）"""
    return [x for x in ITEM_PERSON_PHRASES if x in (prompt or "")]


def empty_suffix(jc: dict, spec: dict) -> dict:
    """ISS-1103-004550-8787：空镜底图 / 单品不用人像风格后缀（“人物被闪光打亮 / 真实皮肤质感 / 夜里机顶闪光”），
    把本剧风格后缀整句换成 spec.suffix（时间 / 光线取自 P1 场景表 + EMPTY_SUFFIX），负面词写明不出现人物"""
    from ns_agent.gen_contract import style as ST
    suf = spec.get("suffix")
    if not suf or ST.EMPTY_SUFFIX not in suf:
        raise RuntimeError("preflight 不过：空镜作业没有空镜后缀（spec.suffix），请重新生成作业")
    p, hit = jc["prompt"], False
    for s_ in sorted(ST.run_suffixes(jc.get("framing_project")), key=len, reverse=True):
        if s_ and s_ in p:
            p, hit = p.replace(s_, suf), True
    if not hit:
        raise RuntimeError("preflight 不过：提示词里找不到本剧风格后缀，没法换成空镜后缀")
    neg = "，".join(x for x in (jc.get("negative"), spec.get("negative")) if x)
    return {**jc, "prompt": p, "negative": neg, "suffix_kind": "empty_scene"}


def require_face_ref(root: Path, job: dict, jc: dict) -> dict:
    """ISS-1103-004547-ca20：设定图必须把清单里已登记的身份脸当参考送进去（按 sha 核），否则不出图"""
    cid = job["spec"]["cid"]
    face = AJ.registered_face(root, job["run"], cid)
    if not face:
        raise RuntimeError(f"preflight 不过：{cid} 的身份脸还没登记进清单，设定图不出（先选定身份脸）")
    # 按实际送进去的参考文件算完整 sha256 再比（compile_trace.refs[].sha 是 asset_refs.sha_file 的 16 位短 sha，
    # 拿它和清单的完整 sha 比永远对不上——11-03 01:14 三条 sheet 全失败的根因，不是编译器没送脸）
    shas = set()
    for f in jc.get("refs") or []:
        p = Path(f) if Path(f).is_absolute() else root / f
        if p.is_file():
            shas.add(AJ._sha(p.read_bytes()))
    if face["sha256"] not in shas:
        raise RuntimeError(f"preflight 不过：设定图的参考里没有已登记的身份脸 {face['file']}（编译器没送脸）")
    return face


def _preflight(job: dict, jc: dict, lane: str, sid: str):
    from ns_agent.gen_contract import preflight as PF
    req = {k: jc.get(k) for k in ("model", "cast", "prompt", "refs", "asset_refs", "loras", "compiled_by", "route", "route_reasons")}
    req.update(kind="image", project=job["run"], framing_project=job["run"], shot_id=sid, lane=lane, mode="setting_candidate", asset_stage=job["kind"])
    return PF.check(req)


def review_dir(root: Path, job: dict) -> Path:
    return root / "data" / "review_pages" / "v2_assets" / job["run"] / job["id"]


def _thumb(src: Path, dst: Path, size: int = 360) -> str | None:
    try:
        from PIL import Image
        im = Image.open(src)
        im.thumbnail((size, size))
        im.convert("RGB").save(dst, "JPEG", quality=85)
        return str(dst)
    except Exception:  # noqa: BLE001  # arch-ok: 缩略图失败就用大图（候选照样投，调用方按 None 处理）
        return None


def render_one(job: dict, lane: str, seed: int, root: Path = ROOT) -> dict:
    """出一张候选并做全部检查（与共用验收 ns_agent.gen_contract.accept 同一套 Q9 / 合并看图；设定候选模式）"""
    jc = _compile(job, root)
    sid = f"{job['run']}-asset-{job['id']}"
    pf = _preflight(job, jc, lane, sid)
    if not pf.ok:
        raise RuntimeError("preflight 不过：" + "；".join(pf.reasons()))
    sys.path.insert(0, str(ROOT / "tools" / "factory"))
    import hosts as H
    from ns_render import unified_frame as UF
    from ns_render.comfy_client import ComfyClient
    import ns_render.pipeline as P
    AC = import_dep("asset_checks")
    client = ComfyClient(H.lane_url(lane, from_host="laptop"))
    client.client_id = "assetW-" + client.client_id
    client.server_tag = H.host_of(lane) if H.host_of(lane) != "gpu33" else None
    client.ns_tag = {"agent": BY, "kind": "v2_asset", "label": f"阶段 A {job['kind']} 候选", "obj": job["id"]}
    jc = {**jc, "seed_policy": {"policy": "manual"}, "lane": lane}
    ab = root / "data" / "ab" / "v2_assets" / job["run"] / job["id"]
    ab.mkdir(parents=True, exist_ok=True)
    take, _eff, _ = UF._run(client, sid, "image", jc, seed, rel_dir=ab.relative_to(P.DATA).as_posix(), prefix=f"ns_ab/v2_assets/{job['id']}")
    img = str(P.DATA / take.file)
    host = H.host_of(lane)
    from ns_agent.gen_contract import accept as ACC   # PRODMERGE-O：ensure_q9 已并进共用验收（golden_v2 只剩编译入口）
    post = ACC.ensure_q9(UF._postflight(take.file, jc, host), img, jc)
    if q9_queue_timeout(post):                     # 同步再要一次本地看图结果（排队 / 没跑）
        post = ACC.ensure_q9(post, img, jc)
    if q9_queue_timeout(post):
        raise Q9Timeout(f"seed {seed}：本地看图复核排队超时、没拿到结果（retry，不判 fail）")
    post = AC.q9_asset(post, job["kind"])
    items, person = vlm_items(job)
    if person:
        import anomaly as A
        # W-ASSETS 11-06：face 作业的人就是还没有身份脸的那个人 → refless=True（只数头，不判陌生人；原来 judge 因“在场角色的身份脸缺”
        # 把每张都记 untested，作业永远“没测出”退避）。sheet 的脸已登记，照常按身份参照判
        an = A.check(img, [{"name": job["spec"]["name"], "presence": "在画", "faced": True, "x": "中", "refless": job["kind"] == "face"}], host="gpu36")
    else:
        an = {"status": "pass", "note": "空镜 / 物件，跳过人数检查"}
    bundle = AC.bundle_check(img, items, person)
    bundle["questions"] = items                    # W9：拒因里写“哪一条问的是什么”
    if person:
        an = count_fallback(an, bundle)            # 检测器没跑成（隧道 / rssh 断）→ 用看图第 1 条“只有一个人”兜底，不永远“没测出”
    q9 = str(next((i.get("status") for i in post.get("items") or [] if i.get("id") == "Q9"), "untested"))
    lab = {"identity": "na", "count": {"pass": "pass", "fail": "fail"}.get(str(an.get("status")), "untested"),
           "q9": {"pass": "pass", "na": "pass", "fail": "fail"}.get(q9, "untested"),
           "prompt_vlm": bundle["status"], "ocr": bundle["ocr"]["status"], "age": bundle["age"]["status"]}
    ok = all(v in ("pass", "na") for v in lab.values())
    rec = {"at": AJ._now(), "job": job["id"], "kind": job["kind"], "lane": lane, "seed": seed, "file": take.file, "prompt": take.prompt,
           "refs": jc.get("refs"), "label": lab, "passed": ok, "preflight": pf.to_dict(), "postflight": post, "anomaly": an, "vlm": bundle}
    with (ab / "takes.jsonl").open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
    if ok:
        rd = review_dir(root, job)
        rd.mkdir(parents=True, exist_ok=True)
        dst = rd / f"{job['id']}_s{seed}{Path(take.file).suffix}"
        shutil.copy2(img, dst)
        AJ.atomic_json(rd / f"{job['id']}_s{seed}.json", json.loads(json.dumps(rec, ensure_ascii=False, default=str)))
        th = _thumb(dst, rd / f"{job['id']}_s{seed}_thumb.jpg")
        rec["review_file"] = str(dst.relative_to(root)).replace(os.sep, "/")
        rec["thumb"] = str(Path(th).relative_to(root)).replace(os.sep, "/") if th else rec["review_file"]
        rec["sha256"] = AJ._sha(dst.read_bytes())
    return rec


def deliver(root: Path, jp: Path, job: dict, passed: list[dict]) -> dict:
    """过检候选 → 代选开着且是派生资产：按分数自动登记；否则投待办通知（pick）等项目方挑。run_job 正常收尾与 salvage（子进程没收尾时接管）共用"""
    auto_failed = None
    if job["kind"] in AJ.AUTO_PICK_KINDS and AJ.delegate_active(root)[0]:
        cands = [{"key": f"s{r['seed']}", "label": f"候选 {n}（seed {r['seed']}）", "contract_ok": True, "file": r["review_file"],
                  "thumb": r.get("thumb") or r["review_file"], "sha256": r.get("sha256"), "score": cand_score(r)} for n, r in enumerate(passed, 1)]
        job["review_page"] = str(review_dir(root, job).relative_to(root)).replace(os.sep, "/")
        job.update(state="awaiting_pick", error=None)
        AJ.save_job(root, job)
        who = job["spec"].get("name") or job.get("target")
        try:
            got = AJ.auto_pick(root, job, cands, who, pick_what(job))
            job = AJ.load_job(jp)                                       # after_pick 已把作业标 done
            AJ.log(job, f"{len(cands)} 个候选过检，系统按分数自动选用 {got['picked']}（score {got['score']}），已登记；inbox 发了“已自动选用，可修改”的告知")
        except AJ.RegisterError as e:
            # W-DETECT 11-06（复审 5）：代选登记被拒（例：身份脸已由项目方登记 / 清单被改）→ 不让 run_job 主路径崩：作业照常收尾，
            # 候选改投待办让项目方挑（下面的 pick 路径），原因记进作业日志
            auto_failed = str(e)[:200]
            job = AJ.load_job(jp)
            AJ.log(job, f"代选登记被拒（{auto_failed}），改投待办让项目方挑")
    if auto_failed is not None or not (job["kind"] in AJ.AUTO_PICK_KINDS and AJ.delegate_active(root)[0]):
        cands = [{"key": f"s{r['seed']}", "label": f"候选 {n}（seed {r['seed']}）", "contract_ok": True, "file": r["review_file"],
                  "thumb": r.get("thumb") or r["review_file"], "sha256": r.get("sha256"), "score": n} for n, r in enumerate(passed, 1)]
        who = job["spec"].get("name") or job.get("target")
        title = {"face": f"挑 {who} 的身份脸（{len(cands)} 选 1）", "scene": f"挑场景 {who} 的底图（{len(cands)} 选 1）",
                 "sheet": f"挑 {who} 造型 {job['spec'].get('look')} 的设定图（{len(cands)} 选 1）", "item": f"挑单品 {who} 的图（{len(cands)} 选 1）"}[job["kind"]]
        job["review_page"] = str(review_dir(root, job).relative_to(root)).replace(os.sep, "/")
        AJ.post_pick(root, job, cands, title, pick_detail(f"{who}的{ {'face': '身份脸', 'scene': '场景底图', 'sheet': '造型设定图', 'item': '单品图'}[job['kind']]}", len(cands),
                                                          "都过了出图契约、本地看图、年龄观感和 OCR"), why="契约全过，按出图顺序第一张")
        job.update(state="awaiting_pick", error=None)
        if auto_failed is not None:
            job["auto_pick_failed"] = auto_failed
        AJ.log(job, f"{len(cands)} 个候选过检，已投待办通知 {job['pick_id']}")
    return job


# ------------------------------------------------------------------ 没收尾的作业：接管已过检的候选 / 超时（W6 11-03）
# 事故：sheet-lead_f-O4 03:15 起子进程，出了 2 张过检候选（seed1101/1102）后被 03:30 resident 受控重启连带杀掉（ISS-1103-033131-1efe），
# tick 只会标“子进程退出但作业没收尾”→ pending 重排，已过检的候选白扔，而且排在 item 作业后面一直等道。
# 改法：① 收尸时（子进程死了 / 超时被杀）先看作业里已经落盘、sha 对得上的过检候选，够 salvage_min（默认 2，且不超过本类型要的数量）
# 就直接走 deliver 收尾（投待办 / 代选登记），不再重出；② pending 作业同样先看能不能接管（上次没收尾留下的）；
# ③ 子进程活着但跑过 job_timeout_min（默认 90，O6 起不再跟 hold_minutes）→ 杀掉按“超时”落 failed/重排，不留僵尸 running。
def salvage_records(root: Path, job: dict) -> list[dict]:
    """作业 candidates 里 passed 且复核图在盘上、sha256 对得上的 → run_job 同口径的候选记录（带回 review JSON 里的 postflight / vlm 供打分）"""
    out, seen = [], set()
    for c in job.get("candidates") or []:
        if not (isinstance(c, dict) and c.get("passed") and c.get("sha256") and c.get("file") and c.get("seed") is not None):
            continue
        if c["seed"] in seen or not AJ.is_safe_rel(str(c["file"])):
            continue
        f = root / c["file"]
        try:
            if AJ._sha(f.read_bytes()) != c["sha256"]:
                continue
        except OSError:            # arch-ok: 文件没了 = 这张不能接管
            continue
        try:
            rec = json.loads((review_dir(root, job) / f"{job['id']}_s{c['seed']}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):   # arch-ok: 没有复核 JSON 只影响打分（按 0 分）
            rec = {}
        if rec and not rec.get("passed", True):
            continue
        seen.add(c["seed"])
        out.append({**rec, "seed": c["seed"], "passed": True, "label": c.get("label") or rec.get("label"), "review_file": c["file"],
                    "thumb": c.get("thumb") or c["file"], "sha256": c["sha256"]})
    return out


def salvage_min(cfg: dict, kind: str) -> int:
    need = int((cfg.get("candidates") or {}).get(kind) or 2)
    return max(1, min(int(cfg.get("salvage_min") or 2), need))


def try_salvage(root: Path, j: dict, cfg: dict, rec: dict, why: str) -> bool:
    """够数就接管收尾（deliver），返回 True；不够 / 接管出错返回 False（调用方照旧 _fail）"""
    if j.get("kind") not in AJ.RENDER_KINDS or is_crop_job(j):
        return False
    passed = salvage_records(root, j)
    if len(passed) < salvage_min(cfg, j["kind"]):
        return False
    jp = AJ.job_path(root, j["run"], j["id"])
    AJ.log(j, f"{why}；已有 {len(passed)} 张过检候选（seed {', '.join(str(r['seed']) for r in passed)}），直接接管收尾，不再重出")
    j.update(pid=None, error=None)
    AJ.save_job(root, j)
    try:
        j2 = deliver(root, jp, j, passed)
    except Exception as e:  # noqa: BLE001  接管失败按普通失败处理（重排 / 定案 + 登记卡点）
        rec.setdefault("salvage_errors", []).append(f"{j['id']}: {e!r}"[:200])
        AJ.log(j, f"接管收尾失败：{e!r}"[:200])
        AJ.save_job(root, j)
        return False
    j2["pid"] = None
    AJ.save_job(root, j2)
    if j2 is not j:                    # 代选路径 deliver 会重读作业文件：把调用方手里的那份同步成收尾后的状态
        j.clear()
        j.update(j2)
    rec.setdefault("salvaged", []).append({"id": j2["id"], "state": j2.get("state"), "candidates": len(passed)})
    return True


def _started_age_s(j: dict) -> float | None:
    try:
        return time.time() - time.mktime(time.strptime(str(j.get("started_at"))[:19], "%Y-%m-%dT%H:%M:%S"))
    except (TypeError, ValueError):   # arch-ok: 没有 / 格式不对 = 不判超时
        return None


# ------------------------------------------------------------------ 子进程身份（W6b 11-03，A6 审计 P1-B：pid 复用会杀错进程树）
# 常驻服务每拍重载本模块 → _PROCS 每拍是空的，只剩作业文件里的 pid。起子进程时把 身份 = pid + 创建时间 + 命令行指纹 落进作业文件（job["proc"]），
# 判活 / 超时杀之前都按它核对；创建时间沿用 tools/factory/agent_dispatcher.proc_sig（不另写一套），对不上 = pid 已被复用 → 不杀，作业标失败 why=pid_mismatch。
def _disp():
    return _load("agent_dispatcher_procsig", "tools/factory/agent_dispatcher.py")


def proc_sig(pid: int):
    return _disp().proc_sig(int(pid or 0))


def cmd_fingerprint(args) -> str | None:
    """命令行指纹 = sha1(list2cmdline(args))；Windows 上 = CreateProcess 收到的命令行原文"""
    if not args:
        return None
    if isinstance(args, (str, bytes)):
        args = [args.decode() if isinstance(args, bytes) else args]
    return hashlib.sha1(subprocess.list2cmdline([str(a) for a in args]).encode("utf-8")).hexdigest()


def proc_cmdline(pid: int) -> str | None:
    """在跑进程的命令行（读不到 = None）。Windows：Win32_Process.CommandLine；POSIX：/proc/<pid>/cmdline"""
    if int(pid or 0) <= 0:
        return None
    try:
        if os.name == "nt":
            r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command",
                                f"[Console]::OutputEncoding=[Text.Encoding]::UTF8; (Get-CimInstance Win32_Process -Filter 'ProcessId={int(pid)}').CommandLine"],
                               capture_output=True, timeout=30)
            out = (r.stdout or b"").decode("utf-8", "replace").strip()
            return out or None
        raw = Path(f"/proc/{int(pid)}/cmdline").read_bytes()
        return subprocess.list2cmdline([a.decode("utf-8", "replace") for a in raw.split(b"\0") if a]) or None
    except Exception:  # noqa: BLE001  # arch-ok: 读不到命令行 = None，调用方按“核不了 = 不杀”处理
        return None


def proc_identity(p) -> dict | None:
    pid = getattr(p, "pid", None)
    if not pid:
        return None
    return {"pid": int(pid), "sig": proc_sig(pid), "cmd_sha1": cmd_fingerprint(getattr(p, "args", None))}


def verify_proc(pid: int, ident: dict | None) -> tuple[bool, str]:
    """杀之前核身份：作业文件里记的 pid / 创建时间 / 命令行指纹必须和眼前这个进程全部一致。返回 (一致, 说明)"""
    ident = ident or {}
    if not pid or not ident.get("pid") or int(ident["pid"]) != int(pid):
        return False, f"作业没记子进程身份或 pid 对不上（记的 {ident.get('pid')}，眼前 {pid}）"
    if ident.get("sig") is None:
        return False, "作业没记子进程创建时间，核不了"
    live = proc_sig(pid)
    if live != ident["sig"]:
        return False, f"创建时间对不上（记的 {ident['sig']}，眼前 {live}）"
    if ident.get("cmd_sha1"):
        cl = proc_cmdline(pid)
        if cl is None:
            return False, "读不到该 pid 的命令行，核不了"
        if hashlib.sha1(cl.encode("utf-8")).hexdigest() != ident["cmd_sha1"]:
            return False, "命令行指纹对不上"
    else:
        return False, "作业没记命令行指纹，核不了"
    return True, "pid + 创建时间 + 命令行一致"


def _kill(pid: int) -> None:
    """只在 verify_proc 核过身份之后调用；taskkill /T 连子树一起杀"""
    if not pid:
        return
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, timeout=30)
        else:
            os.kill(pid, 9)
    except Exception:  # noqa: BLE001  # arch-ok: 杀不掉（已退出）也照样落状态
        pass


UNMEASURED_BACKOFF_S = 300     # 没测出（看图 / 人数服务不可用）→ 作业退避 5 分钟再起（W6c 追加）


def _backing_off(j: dict, now: float | None = None) -> bool:
    """作业还在“没测出”退避期内（retry_after 没到）"""
    ra = j.get("retry_after")
    if not ra:
        return False
    try:
        return time.mktime(time.strptime(str(ra)[:19], "%Y-%m-%dT%H:%M:%S")) > (time.time() if now is None else now)
    except (TypeError, ValueError):   # arch-ok: 格式不对 = 不退避
        return False


def run_job(jp: Path, lane: str, root: Path = ROOT, renderer=None, cfg: dict | None = None) -> dict:
    """子进程主体：按需要的候选数出图（最多 2 倍种子），通过的投待办通知；收尾释放道"""
    cfg = cfg or config(root)
    job = AJ.load_job(jp)
    need = int((cfg.get("candidates") or {}).get(job["kind"]) or 2)
    base = 1000 + 100 * int(job.get("attempts") or 1)
    seeds = fresh_seeds(job, base, need * 2)
    passed: list[dict] = []
    errors: list[str] = []
    rejects: list[str] = []
    reject_recs: list[dict] = []
    timeouts = 0
    unmeasured: list[str] = []          # W6c 追加：没测出的候选（看图 / 人数服务没出结论）——不算不过、不计 attempts
    streak = 0                          # 连续没测出的张数：服务挂了就别再烧 GPU 出新种子
    AC = import_dep("asset_checks", root=ROOT)
    try:
        for i in range(need * 2):
            if len(passed) >= need or (job.get("state") == "failed" and job.get("final")):   # 被 tick 定案：不再出新种子
                break
            if streak >= int(cfg.get("unmeasured_streak") or 2):
                AJ.log(job, f"连续 {streak} 张候选没测出（看图服务不可用），不再出新种子，等退避后重试")
                break
            seed = seeds[i]                    # W-FIX-PIPE #13：跳过本作业用过的种子（自动重排 = 真换一批）
            try:
                r = (renderer or render_one)(job, lane, seed, root)
            except Exception as e:  # noqa: BLE001  一张失败记下继续下一粒种子
                infra = isinstance(e, Q9Timeout) or is_infra_error(e)   # W31：ComfyUnavailable（连不上出图机）同口径：未测≠不过
                timeouts += infra
                streak = streak + 1 if infra else streak
                errors.append(f"seed {seed}: {type(e).__name__}: {e}"[:200])
                AJ.log(job, errors[-1])
                _child_save(root, job)
                if "preflight 不过" in str(e):
                    break                                          # 编译 / 前置契约不过 = 换种子也没用
                continue
            um = [] if r.get("passed") else AC.unmeasured_keys(r.get("label"), r.get("vlm"))
            cand = {"seed": seed, "passed": r.get("passed"), "label": r.get("label"), "file": r.get("review_file") or r.get("file"),
                    "thumb": r.get("thumb"), "sha256": r.get("sha256")}
            if um:
                cand["unmeasured"] = um
            job.setdefault("candidates", []).append(cand)
            _child_save(root, job)
            streak = streak + 1 if um else 0
            if r.get("passed"):
                passed.append(r)
            elif um:
                unmeasured.append(f"seed {seed}：{'、'.join(f'{k}=untested（{LABEL_ZH.get(k, k)}）' for k in um)}")
                AJ.log(job, "候选没测出（看图服务没出结论，不算不过）：" + unmeasured[-1])
                _child_save(root, job)
            else:
                reject_recs.append(r)
                rejects.append(f"seed {seed}：{reject_reason(r)}"[:400])
                AJ.log(job, "候选不过：" + rejects[-1])
                _child_save(root, job)
        if _settled_by_tick(root, job) is not None:
            AJ.log(job, "作业已被 tick 定案（身份核不上），子进程只补写候选，不投待办、不改状态；由 tick 核验本进程退出后接管")
        elif passed:
            job = deliver(root, jp, job, passed)
        elif (unmeasured or timeouts) and timeouts == len(errors) and (unmeasured or not rejects):
            # 没拿到结论 = 基础设施问题：回 pending 退避重试，不计 attempts、不判 failed（W6c 追加；与 producer Q9 口径一致）
            back = int(cfg.get("unmeasured_backoff_s") or UNMEASURED_BACKOFF_S)
            if unmeasured and not rejects and not timeouts:
                why = f"看图服务不可用，等待重试（{len(unmeasured)} 张候选没测出，{back // 60} 分钟后重试，不算失败）"
            elif unmeasured:
                why = (f"看图服务不可用，等待重试（{len(unmeasured)} 张没测出" + (f"、{len(rejects)} 张不过" if rejects else "")
                       + (f"、本地看图复核排队超时 {timeouts} 次" if timeouts else "") + f"，{back // 60} 分钟后重试，不算失败）")
            else:
                why = f"本地看图复核排队超时 {timeouts} 次，重排（不算失败）"
            job.update(state="pending", error=why, retry_after=time.strftime(AJ.TS, time.localtime(time.time() + back)))
            job["attempts"] = max(0, int(job.get("attempts") or 1) - 1)
            AJ.log(job, why + " ｜ " + " ｜ ".join((unmeasured + rejects)[-6:])[:800])
        else:
            why = rejects + errors
            job.update(state="failed", error=f"没有候选过检（{len(rejects)} 张不过、{len(errors)} 张出错）：" + reject_summary(reject_recs)
                       + " ｜ ".join(why[-6:])[:1500])
            AJ.log(job, job["error"][:600])
    finally:
        job["pid"] = None
        settled = _child_save(root, job)            # W6c+：tick 已定案 → 状态只增不改（A6b P2）
        if lane and renderer is None and not settled:    # 定案的作业：道由 tick 核验本进程退出后再放（lane_suspect）
            try:
                _lanes_mod().release(lane, by=BY, kind="hold")
            except Exception as e:  # noqa: BLE001  放道失败：到期自动清，tick 收尸时再放一次
                AJ.log(job, f"放道失败：{e!r}"[:160])
                _child_save(root, job)
    return job


# ------------------------------------------------------------------ 子进程：从设定图裁单品（总调度 11-03，参照 SH1 纯裁剪做法）
ZONE_BAND = {"feet": (0.84, 1.0), "lower": (0.42, 0.90), "upper": (0.10, 0.58), "body": (0.10, 0.92), "hand": (0.32, 0.66),
             "neck": (0.06, 0.30), "waist": (0.36, 0.62)}


def is_crop_job(j: dict) -> bool:
    sp = j.get("spec") or {}
    return bool(sp.get("crop") and sp.get("from_sheet") and not sp.get("crop_failed"))


def person_box(im) -> tuple[int, int, int, int] | None:
    """中性纯色背景的全身设定图：边框像素中位色 = 背景，与之色差大的像素 = 人；取行列密度过阈的外框"""
    import numpy as np
    a = np.asarray(im.convert("RGB")).astype(np.int16)
    h, w = a.shape[:2]
    border = np.concatenate([a[:4].reshape(-1, 3), a[-4:].reshape(-1, 3), a[:, :4].reshape(-1, 3), a[:, -4:].reshape(-1, 3)])
    bg = np.median(border, axis=0)
    fg = np.abs(a - bg).sum(axis=2) > 60
    rows = np.where(fg.mean(axis=1) > 0.01)[0]
    cols = np.where(fg.mean(axis=0) > 0.01)[0]
    if len(rows) < h * 0.3 or len(cols) < 8:
        return None
    return int(cols[0]), int(rows[0]), int(cols[-1]) + 1, int(rows[-1]) + 1


def crop_part(sheet: Path, zone: str, out: Path) -> list[int] | None:
    """按部件所在区（asset_refs.zone_of）从人物外框里裁一条带；裁不出来（找不到人 / 区不认识）= None"""
    from PIL import Image
    band = ZONE_BAND.get(zone)
    if not band:
        return None
    im = Image.open(sheet)
    pb = person_box(im)
    if not pb:
        return None
    x0, y0, x1, y1 = pb
    ph, pw = y1 - y0, x1 - x0
    pad = int(pw * 0.08)
    box = [max(0, x0 - pad), max(0, y0 + int(ph * band[0]) - int(ph * 0.02)), min(im.width, x1 + pad), min(im.height, y0 + int(ph * band[1]) + int(ph * 0.02))]
    if box[2] - box[0] < 32 or box[3] - box[1] < 32:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    im.crop(tuple(box)).convert("RGB").save(out, "PNG")
    return box


def crop_items(spec: dict) -> list[str]:
    return [f"画面里能清楚看到这件单品：{spec['label']}，而且它是画面的主体", "画面里没有完整的人脸",
            "单品上没有任何品牌标志、字母和文字"]


def run_crop(jp: Path, root: Path = ROOT, checker=None, pusher=None) -> dict:
    """裁 → 契约（本地看图逐条 + OCR）→ 过了直接登记（不用项目方挑）；裁不出来 / 不过 → spec.crop_failed，回到 pending 改出候选"""
    job = AJ.load_job(jp)
    spec = job["spec"]
    try:
        sheet = root / spec["from_sheet"]["file"]
        if not sheet.is_file() or AJ._sha(sheet.read_bytes()) != spec["from_sheet"]["sha256"]:
            raise RuntimeError(f"设定图 {spec['from_sheet']['file']} 不在或 sha 变了")
        out = review_dir(root, job) / f"{job['id']}_crop.png"
        box = crop_part(sheet, spec.get("zone") or "", out)
        if not box:
            raise RuntimeError(f"裁不出来（区 {spec.get('zone')!r} 找不到人物外框或不认识）")
        chk = (checker or AC_bundle)(str(out), crop_items(spec))
        if chk.get("status") != "pass" or (chk.get("ocr") or {}).get("status") not in ("pass", "na"):
            raise RuntimeError(f"裁图没过契约：看图 {chk.get('status')}，OCR {(chk.get('ocr') or {}).get('status')}")
        on, why_off = AJ.delegate_active(root)
        if on:                                         # L-139：代选开着 → 直接登记
            res = AJ.register_item_auto(root, job, out, box, chk, pusher=pusher, push=bool(config(root).get("push")))
            job.update(state="done", result=res, done_at=AJ._now(), error=None, candidates=[{"key": "crop", "file": res["file"], "sha256": res["sha256"], "passed": True}])
            AJ.log(job, f"从设定图裁出并过契约，代选开着，已直接登记 {res['file']}（框 {box}）")
            (AJ.jobs_dir(root, job["run"]) / "_recheck").write_text(AJ._now(), encoding="utf-8")
        else:                                          # 平时：投 #/queue 等项目方挑（一张裁图 = 1 个候选）
            rel = str(out.relative_to(root)).replace(os.sep, "/")
            cand = {"key": "crop", "label": f"从设定图裁出（框 {box}）", "contract_ok": True, "file": rel, "thumb": rel, "sha256": AJ._sha(out.read_bytes()), "score": 1}
            job.update(state="awaiting_pick", error=None, candidates=[{**cand, "passed": True}], crop_box=box)
            job["review_page"] = str(review_dir(root, job).relative_to(root)).replace(os.sep, "/")
            AJ.save_job(root, job)
            who = spec.get("name") or job.get("target")
            AJ.post_pick(root, job, [cand], f"确认 {who} 的单品图：{spec.get('label')}（从设定图裁出）",
                         pick_detail(f"{who}的单品“{spec.get('label')}”", 1, "从已登记的设定图裁出，过了本地看图和 OCR"), why="从设定图纯裁剪")
            AJ.log(job, f"从设定图裁出并过契约；代选没开（{why_off}），已投待办通知 {job['pick_id']} 等项目方确认")
    except Exception as e:  # noqa: BLE001  裁不出来 = 改出候选（总调度 11-03），不算失败
        spec["crop_failed"] = f"{type(e).__name__}: {e}"[:300]
        job.update(state="pending", error=None, attempts=0)
        AJ.log(job, f"从设定图裁不出来，改为出候选投待办：{spec['crop_failed']}")
    finally:
        job["pid"] = None
        AJ.save_job(root, job)
    return job


def AC_bundle(img: str, items: list[str]) -> dict:
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    import asset_checks as AC
    return AC.bundle_check(img, items, want_person=False)


def pick_detail(who: str, n: int, extra: str = "") -> str:
    """投递文案统一用 owner_pick.pick_detail（CAST-S 卡点 ⑤）"""
    sys.path.insert(0, str(ROOT / "services" / "api"))
    from ns_api import owner_pick as OP
    return OP.pick_detail(who, n, extra)


# ------------------------------------------------------------------ 子进程：音色作业（voice_v2 一条链）
def voice_roles_file(root: Path, job: dict) -> Path:
    spec = job["spec"]
    p = AJ.job_path(root, job["run"], job["id"]).with_suffix(".roles.json")
    AJ.atomic_json(p, {spec["role"]: {"label": spec["label"], "gender": spec["gender"], "char_id": spec["cid"], "persona": spec["persona"],
                                      "cands": [[c[0], c[1], c[2], c[3]] for c in spec["cands"]]}})
    return p


def run_voice(jp: Path, root: Path = ROOT, runner=None, remote_ready=None, cfg: dict | None = None, wait_s: float = 5400) -> dict:
    """plan → push → design（gpu36 CPU）→ 等 ref.wav → clone（gpu36 CPU）→ 等 sample.wav → pull ×2 → check → page --roles（登记 support_candidates）→ 投 pick。
    runner(args) 跑 voice_v2 CLI；remote_ready(host, role, file) 看远端文件齐没齐（测试用假的）"""
    cfg = cfg or config(root)
    job = AJ.load_job(jp)
    role, host = job["spec"]["role"], str(cfg.get("voice_host") or "gpu36")
    AJ.guard_run(root, job["run"])
    if runner is None and Path(root).resolve() != ROOT.resolve():
        # voice_v2 CLI 永远写真实仓库的 config/voices_v2.json：临时目录试跑必须注入 runner（ISS-1103-004549-cb05 的根因之一）
        raise RuntimeError(f"数据根 {root} 不是真实仓库，真实 voice_v2 链不许跑（试跑请注入 runner）")
    picked = ((AJ._read_json(root / "config" / "voices_v2.json", "voices_v2.json").get("roles") or {}).get(role) or {}).get("selected")
    if picked:                                       # 项目方已经选定过这个槽：不重出候选、不写回 support_candidates
        job.update(state="done", error=None, pid=None, result={"skipped": f"voices_v2.json roles.{role} 已选定 {picked}"})
        AJ.log(job, f"{role} 已选定 {picked}，不再出音色候选")
        AJ.save_job(root, job)
        return job
    rf = voice_roles_file(root, job)
    run = runner or (lambda args: subprocess.run([sys.executable, "-X", "utf8", str(ROOT / "tools" / "v2style" / "voice_v2.py"), *args, "--roles", role,
                                                  "--roles-file", str(rf)], cwd=str(ROOT), capture_output=True, text=True, timeout=3600,
                                                 env={**os.environ, "PYTHONUTF8": "1"}))
    ready = remote_ready or _voice_remote_ready

    def step(name, args):
        job["step"] = name
        AJ.log(job, f"voice_v2 {name}")
        AJ.save_job(root, job)
        r = run(args)
        if getattr(r, "returncode", 0):
            raise RuntimeError(f"voice_v2 {name} rc={r.returncode}: {(r.stderr or r.stdout or '')[-300:]}")

    def wait(name, fname):
        t0 = time.time()
        while not ready(host, role, fname, rf):
            if time.time() - t0 > wait_s:
                raise RuntimeError(f"等 {fname} 超时（{name}）")
            time.sleep(30)
    try:
        step("plan", ["plan"])
        step("push", ["push"])
        step("design", ["design"])
        wait("design", "ref.wav")
        step("clone", ["clone", "--host", host])
        wait("clone", "sample.wav")
        step("pull-ref", ["pull", "--host", host, "--file", "ref.wav"])
        step("pull-sample", ["pull", "--host", host, "--file", "sample.wav"])
        step("check", ["check"])
        step("page", ["page"])
        cands = _voice_candidates(root, role)
        if not cands:
            raise RuntimeError("没有过检的音色候选（voices_v2.json support_candidates 为空）")
        who = job["spec"].get("name") or role
        AJ.post_pick(root, job, cands, f"挑一个{who}的声音（{len(cands)} 选 1）",
                     pick_detail(f"{who}（{job['spec'].get('persona', '')[:30]}）", len(cands), "a 标准普通话，b、c 带上海腔"),
                     recommend=next((c["key"] for c in cands if c["key"] != "a"), cands[0]["key"]), why="带上海腔、和人设最贴")
        job.update(state="awaiting_pick", error=None)
        AJ.log(job, f"{len(cands)} 个音色候选过检，已投待办通知 {job['pick_id']}")
    except Exception as e:  # noqa: BLE001  任一步失败 → failed 带原因（tick 按 attempts 重排）
        job.update(state="failed", error=f"{type(e).__name__}: {e}"[:300])
        AJ.log(job, job["error"])
    finally:
        job["pid"] = None
        AJ.save_job(root, job)
    return job


def _voice_candidates(root: Path, role: str) -> list[dict]:
    cfg = AJ._read_json(root / "config" / "voices_v2.json", "voices_v2.json")
    sup = (((cfg.get("support_candidates") or {}).get("roles") or {}).get(role) or {}).get("candidates") or []
    return [{"key": str(c.get("cand")), "label": f"候选 {c.get('cand')}（{'带上海腔' if c.get('shanghai_accent') else '标准普通话'}，f0 {c.get('f0_hz')} Hz）",
             "contract_ok": True, "score": 0, "audio": f"data/review_pages/v2_style/voice/{role}_{c.get('cand')}_sample.wav"} for c in sup]


def _voice_remote_ready(host: str, role: str, fname: str, roles_file: Path) -> bool:
    sys.path.insert(0, str(ROOT / "tools" / "v2style"))
    import voice_v2 as V2
    V2.load_roles_file(roles_file)
    V2.ONLY = {role}
    try:
        for cd, _m in V2.cands():
            if V2.rssh.run_retry(host, f"test -f {V2.rp(cd, fname)}", timeout=120, tries=2).returncode != 0:
                return False
    except Exception:  # noqa: BLE001  远端探不到 = 还没好（由超时兜底）
        return False
    return True


# ------------------------------------------------------------------ CLI
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick")
    t.add_argument("--dry", action="store_true", help="只生成作业、不执行（也不写清单）")
    rj = sub.add_parser("run-job")
    rj.add_argument("--job", required=True)
    rj.add_argument("--lane", required=True)
    rj.add_argument("--root", default="", help="数据根（默认 = 作业文件所在的数据根）")
    rc = sub.add_parser("run-crop")
    rc.add_argument("--job", required=True)
    rc.add_argument("--root", default="", help="数据根（默认 = 作业文件所在的数据根）")
    rv = sub.add_parser("run-voice")
    rv.add_argument("--job", required=True)
    rv.add_argument("--root", default="", help="数据根（默认 = 作业文件所在的数据根）")
    sub.add_parser("status")
    a = ap.parse_args(argv)
    if a.cmd == "tick":
        print(json.dumps(tick(dry=a.dry), ensure_ascii=False, indent=1))
        return 0
    if a.cmd in ("run-job", "run-voice", "run-crop"):
        jroot = root_of_job(Path(a.job))
        if a.root and Path(a.root).resolve() != jroot:
            raise SystemExit(f"--root {a.root} 与作业文件所在的数据根 {jroot} 不一致，不跑")
        AJ.guard_run(jroot, AJ.load_job(Path(a.job))["run"])
    if a.cmd == "run-job":
        j = run_job(Path(a.job), a.lane, jroot)
        print(json.dumps({"id": j["id"], "state": j["state"], "error": j.get("error"), "candidates": len(j.get("candidates") or [])}, ensure_ascii=False))
        return 0 if j["state"] == "awaiting_pick" else 1
    if a.cmd == "run-crop":
        j = run_crop(Path(a.job), jroot)
        print(json.dumps({"id": j["id"], "state": j["state"], "crop_failed": j["spec"].get("crop_failed")}, ensure_ascii=False))
        return 0
    if a.cmd == "run-voice":
        j = run_voice(Path(a.job), jroot)
        print(json.dumps({"id": j["id"], "state": j["state"], "error": j.get("error")}, ensure_ascii=False))
        return 0 if j["state"] == "awaiting_pick" else 1
    hb = ROOT / "data" / "pipeline" / "asset_jobs" / "worker.json"
    print(hb.read_text(encoding="utf-8") if hb.is_file() else "还没有心跳")
    for run in active_runs():
        for j in AJ.list_jobs(ROOT, run):
            print(f"{run} {j['id']:<30} {j.get('kind'):<7} {j.get('state'):<14} {(j.get('error') or '')[:60]}")
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
