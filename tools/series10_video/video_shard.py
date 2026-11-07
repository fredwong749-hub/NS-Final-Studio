"""视频按镜分片（PLAN_EP01_FINISH §11）。默认关：config/pipeline/video_shard.json enabled=false → 本模块所有函数都返回“没分片”，
调用方走原来的整集一台逻辑。

分片 = 纯函数：(配置, 本集全部镜 id + 时长) → {镜: 主机}。两台服务器的 night 各自算，结果一致（不用互相通信，不用租约文件）：
  · 每台的 jobs.json 里每镜带 host（build_jobs 填），vidgen Runner 本来就只出 host == 本机 的镜 → 两台出的镜互不相交；
  · state_<host>.json 本来就是一台一份、只有那台的 vidgen 写 → 状态天然不互相覆盖；
  · owner（hosts.json / partition 里这一集的归属）负责合成；helper 的 state + 片子由笔记本 shard_relay.py 送到 owner，
    owner 用 merged_shots() 读各台 state 合并出整集视图（只读，不写 helper 的 state）。
登记 takes 仍走 register_takes → P.mutate_takes（加锁），这里不碰 takes.json。
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config" / "pipeline" / "video_shard.json"


def load(path: Path | None = None) -> dict:
    """读不到 / 坏 = 没分片（失败关闭到原行为）"""
    try:
        d = json.loads(Path(path or CONFIG).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 配置读不到 = 不分片（默认关，失败关闭到原行为）
        return {"enabled": False}
    return d if isinstance(d, dict) else {"enabled": False}


def ep_cfg(run: str, ep: int, cfg: dict | None = None) -> dict | None:
    """这一集的分片配置 {"owner","weights","map","hosts"}；没开 / 没配 / 不足两台 → None。
    L-209 S3：cfg 没传（= 读现网配置）且 video_shard.json 没配这一集 → 看调度分片（sched_ep_cfg）"""
    c = _static_ep_cfg(run, ep, load() if cfg is None else cfg)
    if c is None and cfg is None:
        c = sched_ep_cfg(run, int(ep))
    return c


def _static_ep_cfg(run: str, ep: int, cfg: dict) -> dict | None:
    if not cfg.get("enabled"):
        return None
    e = (((cfg.get("runs") or {}).get(run) or {}).get("eps") or {}).get(str(int(ep)))
    if not e:
        return None
    weights = {str(h): float(w) for h, w in (e.get("weights") or {}).items() if float(w) > 0}
    if len(weights) < 2:
        return None
    owner = str(e.get("owner") or "")
    if owner not in weights:
        return None            # owner 必须是分片台之一，否则没人合成：失败关闭到“不分片”
    return {"owner": owner, "weights": weights, "map": {str(k): str(v) for k, v in (e.get("map") or {}).items()},
            "hosts": sorted(weights)}


def plan(c: dict, shots: list[tuple[str, float]]) -> dict[str, str]:
    """shots = [(镜 id, 时长秒)] → {镜: 主机}。显式 map 优先；其余按“时长降序、负载 / 权重最小的台先拿”贪心（确定性，平局按主机名）"""
    out = {sid: h for sid, h in c["map"].items() if h in c["weights"]}
    if c.get("owner_only"):        # L-209 S3 调度分片集：静态计划全归 owner，只有调度器的领取（shard_claims why=sched）改派
        return {**{sid: c["owner"] for sid, _ in shots}, **out}
    load_s = {h: 0.0 for h in c["weights"]}
    for sid, sec in shots:
        if sid in out:
            load_s[out[sid]] += float(sec)
    rest = sorted((x for x in shots if x[0] not in out), key=lambda x: (-float(x[1]), x[0]))
    for sid, sec in rest:
        h = min(sorted(c["weights"]), key=lambda k: (load_s[k] + float(sec)) / c["weights"][k])
        out[sid] = h
        load_s[h] += float(sec)
    return out


def plan_all(run: str, specs: dict, cfg: dict | None = None, claims: dict | None = None, now: float | None = None) -> dict[str, str]:
    """specs = {镜 id: ShotSpec（.episode / .duration_s）} → {镜: 主机}（只含配了分片的集的镜；没开 = {}）。
    claims（动态抢活，FIX-A 11-05）给了就把仍有效的领取叠在静态计划上：镜改派给领取台"""
    by_ep: dict[int, list[tuple[str, float]]] = {}
    for sid, s in specs.items():
        by_ep.setdefault(int(s.episode), []).append((sid, float(s.duration_s)))
    out: dict[str, str] = {}
    for ep, shots in by_ep.items():
        c = ep_cfg(run, ep, cfg)
        if c:
            out.update(plan(c, shots))
    if claims:
        out = apply_claims(out, claims, now)
    return out


def shard_eps(run: str, cfg: dict | None = None) -> dict[int, dict]:
    """{集: 分片配置}（没开 = {}）"""
    use_sched = cfg is None
    cfg = load() if cfg is None else cfg
    out = {}
    if cfg.get("enabled"):
        eps = (((cfg.get("runs") or {}).get(run) or {}).get("eps") or {})
        out = {int(e): c for e in eps if (c := _static_ep_cfg(run, int(e), cfg))}
    if use_sched:
        for e in sched_eps(run):
            if e not in out and (c := sched_ep_cfg(run, e)):
                out[e] = c
    return out


def eps_on_host(run: str, host: str, hosts_map: dict, cfg: dict | None = None) -> list[int]:
    """本机该出的集 = 原来按集归属的 ∪ 分片集里本机是分片台的（owner 本来就在前一项里）"""
    eps = {int(e) for e, h in (hosts_map or {}).items() if h == host}
    eps |= {e for e, c in shard_eps(run, cfg).items() if host in c["hosts"]}
    return sorted(eps)


def helper_hosts(run: str, cfg: dict | None = None) -> set[str]:
    return {h for c in shard_eps(run, cfg).values() for h in c["hosts"] if h != c["owner"]}


def exclude_lanes(host: str, cfg: dict | None = None) -> list[str]:
    """分片开着时本机不派视频的道（gpu33:3 = 看图 + reserve-vram 9）；没开 = []"""
    cfg = load() if cfg is None else cfg
    if not cfg.get("enabled"):
        return []
    return [x for x in ((cfg.get("exclude_lanes") or {}).get(host) or [])]


def merged_shots(vid: Path, ep: int, hosts: list[str], jobs: dict | None = None) -> dict:
    """整集视图：读 hosts 各台的 state_<host>.json，按镜合并成 {镜: 记录}（只读）。
    同一镜两台都有记录（配置中途改过 / 抢活）→ 取 jobs.json 里 host 对得上的那台（FIX-VID D13：shard_claims.json 的领取
    叠在 jobs 的 host 上，领取台的记录优先——两台都出了同一镜时只认一份）；没 jobs → 渲染版本多的那台"""
    jh = {s["shot"]: s.get("host") for s in (jobs or {}).get("shots", [])}
    for sid, c in load_claims(vid).items():
        if sid in jh and c.get("host") in hosts:
            jh[sid] = c["host"]
    out: dict = {}
    src: dict = {}
    for h in hosts:
        try:
            st = json.loads((Path(vid) / f"state_{h}.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):   # arch-ok: 那台的 state 还没送来 = 这些镜暂时算“没出”（调用方据此等待，不会拿缺镜合成）
            continue
        for sid, r in (st.get("shots") or {}).items():
            if int(sid[2:4]) != int(ep):
                continue
            if sid in out:
                cur_ok, new_ok = jh.get(sid) == src[sid], jh.get(sid) == h
                if cur_ok or (not new_ok and len(out[sid].get("renders") or []) >= len(r.get("renders") or [])):
                    continue
            out[sid], src[sid] = r, h
    return out


def ep_hosts(run: str, ep: int, owner: str, cfg: dict | None = None) -> list[str]:
    """读这一集状态要看的主机：分片 → 全部分片台（owner 在前）；否则 [owner]"""
    c = ep_cfg(run, ep, cfg)
    return [owner] + [h for h in c["hosts"] if h != owner] if c else [owner]


# ---------------------------------------------------------------- 动态抢活（FIX-A 11-05，项目方“pipeline 不要漏掉这 2 台 gpu 服务器”）
# 静态分片的缺点：一台先出完，整台空着，另一台还剩一堆镜。改成：静态计划只是“初始偏好”，
# 剩余没开始的镜，任一台空了就能领。仲裁者只有笔记本（shard_relay，唯一写者）——两台服务器互不信任、不互相通信，
# 领取写成 shard_claims.json {镜: {host, from, at}}，由 relay 同时送到两台；两台的 build_jobs 读它叠在静态计划上，
# 所以 jobs.json 里每镜的 host 仍是唯一裁决（vidgen 只出 host == 本机的镜）。领取超时没开工 → 回收（镜回原台）。
CLAIMS_NAME = "shard_claims.json"
CLAIM_LEASE_S = 1800          # 领取后这么久镜还没出现任何渲染记录 → 作废（领取台可能掉线）
SETTLED = ("done", "best_effort", "blocked")


def load_claims(vid: Path) -> dict:
    try:
        d = json.loads((Path(vid) / CLAIMS_NAME).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 没有 / 写坏 = 没有领取（回到静态计划）
        return {}
    return d if isinstance(d, dict) else {}


def save_claims(vid: Path, claims: dict) -> None:
    import os
    p = Path(vid) / CLAIMS_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(claims, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, p)


def _started(rec: dict | None) -> bool:
    """镜在某台已经有渲染记录 / 状态不是待办 = 已开工，不可再被抢（避免两台重复出同一镜）"""
    return bool(rec) and (bool(rec.get("renders")) or rec.get("status") not in (None, "", "pending", "queued"))


def live_claims(claims: dict, merged: dict, now: float, lease_s: float = CLAIM_LEASE_S) -> dict:
    """仍有效的领取：镜已开工 / 已落定 → 保留（主机归属不能再变，否则 jobs.json 的 host 会翻）；
    还没开工且超过 lease_s → 作废（超时回收）。sticky=True 的领取（FIX-VID D1：helper 失联后 owner 收回的镜）不按租约作废，
    镜落定才由调用方清理"""
    out = {}
    for sid, c in (claims or {}).items():
        if c.get("sticky") or _started((merged or {}).get(sid)) or now - float(c.get("at") or 0) <= lease_s:
            out[sid] = c
    return out


HELPER_STALE_S = 900          # FIX-VID D1：helper 的 state 超过这么久没更新（或拉不到）= 失联，owner 收回它名下没落定的镜
STATE_FRESH_S = 300           # state 在这么久内更新过 = “没开工”的判断可信，才允许别台从它名下领镜（D13：避免两台重复出同一镜）


def state_age(vid: Path, host: str, now: float | None = None) -> float:
    """state_<host>.json 的 saved 距今秒数；文件没有 / 坏 / 没 saved = inf（当失联）"""
    import time as _t
    now = _t.time() if now is None else now
    try:
        st = json.loads((Path(vid) / f"state_{host}.json").read_text(encoding="utf-8"))
        return max(0.0, now - float(st.get("saved") or 0)) if st.get("saved") else float("inf")
    except (OSError, ValueError, TypeError):   # arch-ok: 读不到这台 state = 失联（调用方据此收回，不是放行）
        return float("inf")


def effective_mine(host: str, sid: str, jobs_host: str | None, claim: dict | None, started_here: bool,
                   now: float, lease_s: float = CLAIM_LEASE_S) -> bool:
    """vidgen 用（FIX-VID D13）：这一镜现在归不归本机。jobs.json 的 host 是静态裁决，shard_claims.json 的领取不用等重编就生效：
      · 领取台 = 本机（jobs 还写着别台）→ 本机已开工或租约未过 → 归本机；
      · 被领走（from = 本机，jobs 还写着本机）→ 租约内且本机没开工 → 不归本机（别台在出）；本机已开工 → 仍归本机（领取方会被 relay 看到已开工后作废）；
      · 领取已进 jobs（jobs host = 领取台）→ 按 jobs；
      · 没领取 → 按 jobs"""
    if claim and claim.get("host") == host and jobs_host != host:
        return started_here or claim.get("sticky") or now - float(claim.get("at") or 0) <= lease_s
    if claim and claim.get("from") == host and jobs_host == host and claim.get("host") != host:
        if started_here:
            return True
        return not (claim.get("sticky") or now - float(claim.get("at") or 0) <= lease_s)
    return jobs_host == host


def apply_claims(plan_map: dict, claims: dict, now: float | None = None, hosts: set | None = None, lease_s: float = CLAIM_LEASE_S) -> dict:
    """静态计划 + 领取 → 实际 {镜: 主机}。没有 merged 状态可看时只按时间判过期（调用方想精确就先 live_claims）"""
    import time as _t
    now = _t.time() if now is None else now
    out = dict(plan_map)
    for sid, c in (claims or {}).items():
        if sid in out and (hosts is None or c.get("host") in hosts) and c.get("host"):
            out[sid] = c["host"]
    return out


def decide_claims(c: dict, plan_map: dict, merged: dict, claims: dict, busy: dict, now: float,
                  lease_s: float = CLAIM_LEASE_S, per_host: int = 1, claim_from: set | None = None,
                  stale_hosts: set | None = None) -> dict:
    """c = ep_cfg；plan_map = 静态 {镜: 主机}；merged = 整集状态；busy = {主机: 在跑 / 排队的渲染数}（关心的是“空”）。
    返回新的领取表（含旧的有效领取）：空闲台（busy==0 且自己名下没有未开工的镜）从别台名下领“没开工、没被领”的镜，
    每台每轮最多 per_host 个（尾部的镜先领，owner 继续从前往后出）。
    FIX-VID：claim_from = 允许从哪些台名下领（state 新鲜、“没开工”可信的台；None = 全部，D13）；
    stale_hosts = 失联的 helper（state 太久没更新 / 拉不到）→ 它名下所有没落定的镜一次全收回给 owner（sticky，不限 per_host、不看开工；D1）；
    已落定的领取保留（合并视图靠它认领取台的记录；表按集很小）"""
    cl = live_claims(claims, merged, now, lease_s)
    eff = apply_claims(plan_map, cl)
    owner = c.get("owner")
    for h in sorted(stale_hosts or ()):
        if h == owner or owner not in c["hosts"]:
            continue
        for s in sorted(eff):
            if eff[s] == h and (merged or {}).get(s, {}).get("status") not in SETTLED:
                cl[s] = {"host": owner, "from": h, "at": now, "sticky": True, "why": "helper_stale"}
        eff = apply_claims(plan_map, cl)
    for h in sorted(c["hosts"]):
        if h in (stale_hosts or ()) or int(busy.get(h, 0)) > 0:
            continue
        if any(eff.get(s) == h and not _started((merged or {}).get(s)) for s in eff):
            continue                                   # 自己名下还有没开工的镜 = 不算闲（作业会陆续派给它）
        cand = [s for s in sorted(eff, reverse=True) if eff[s] != h and not _started((merged or {}).get(s)) and s not in cl
                and (claim_from is None or eff[s] in claim_from)]
        for s in cand[:per_host]:
            cl[s] = {"host": h, "from": eff[s], "at": now}
    return cl


ROLE_WHY = "lane_roles"


def role_claims(c: dict, plan_map: dict, merged: dict, claims: dict, video_hosts: set | None, now: float,
                lease_s: float = CLAIM_LEASE_S) -> dict:
    """L-206 工位分卡叠在抢活之上（纯函数，relay 在 decide_claims 之后调）。video_hosts = 本集当前阶段有视频道的台
    （None = 不适用，原样返回）。
    · 首尾帧阶段（只有 gpu36:2 出视频）：没有视频道的台（gpu33）名下没开工的镜，整批领给有视频道的台（owner 优先；非 sticky，
      按租约；why=lane_roles），不看 claim_from——它本阶段根本不出视频，“没开工”不靠 state 新鲜度；已开工 / 已落定的不动。
    · 视频阶段（全部台都有视频道）：上一阶段为分卡而领、还没开工的领取作废 → 镜回静态计划（两台按 video_shard 权重 + 正常抢活）。
    · 有视频道的台名下的镜不因分卡改派"""
    if video_hosts is None:
        return claims
    cl = dict(claims or {})
    no_video = [h for h in c["hosts"] if h not in video_hosts]
    takers = [h for h in ([c["owner"]] + sorted(c["hosts"])) if h in video_hosts]
    if not no_video or not takers:
        for s, x in list(cl.items()):
            if str(x.get("why") or "").startswith(ROLE_WHY) and not x.get("sticky") and not _started((merged or {}).get(s)):
                cl.pop(s)
        return cl
    eff = apply_claims(plan_map, cl)
    for s in sorted(eff):
        if eff[s] in no_video and not _started((merged or {}).get(s)) and (s not in cl or cl[s].get("host") in no_video):
            cl[s] = {"host": takers[0], "from": eff[s], "at": now, "why": f"{ROLE_WHY}:frames"}
    return cl


# ---------------------------------------------------------------- L-209 S3 phase 1（W-S3，11-07）：唯一调度器派视频跨台
# 笔记本 tools/sched/assign.py 算 data/pipeline/runs/<run>/sched_assign.json（{道: [对象]}，带 TTL，推两台）。
# config/pipeline/state.json sched=enforce 且决定没过期：有视频对象被派到“非本集视频归属台”的集 = 调度分片集——
#   owner = 分区视频归属台（照旧合成），hosts = 两台，owner_only（静态计划全归 owner）；
#   笔记本 shard_relay 按 sched_claims() 写领取（why=sched）→ 被派台 build_jobs / vidgen 照分片机制出（effective_mine），
#   state + 原片由 shard_relay 送回 owner，首尾帧由 resident_sync relay_video_frames 从出图台送到被派台。
# 决定过期 / 改回 record / off：不再新派；已有 why=sched 领取的集仍按分片集算（已开工的镜跑完、结果照样送回 owner，不重出）。
SCHED_WHY = "sched"
SCHED_MISS_COOLDOWN_S = 3600   # 派过去租约到期都没开工 → 这么久内不再把这镜派给同一台（被派台可能缺输入 / 掉线）
_SCHED_HOSTS = ("gpu33", "gpu36")


def _sched():
    """tools/sched/assign.py（服务器镜像没带 = None → 不看调度器）"""
    try:
        import importlib.util
        import sys as _sys
        m = _sys.modules.get("ns_sched_assign_vs")
        if m is None:
            sp = importlib.util.spec_from_file_location("ns_sched_assign_vs", Path(__file__).resolve().parents[2] / "tools/sched/assign.py")
            m = importlib.util.module_from_spec(sp)
            sp.loader.exec_module(m)
            _sys.modules["ns_sched_assign_vs"] = m
        return m
    except (ImportError, OSError, AttributeError):   # arch-ok: 调度器模块没部署 = 不看调度器（静态分区，原行为）
        return None


def _vid_dir(run: str) -> Path:
    return ROOT / "data" / "pipeline" / "runs" / run / "video"


def _sched_claims_by_ep(run: str) -> dict:
    out: dict = {}
    for sid, c in load_claims(_vid_dir(run)).items():
        if str(c.get("why") or "").startswith(SCHED_WHY) and len(sid) >= 4 and sid[2:4].isdigit():
            out.setdefault(int(sid[2:4]), {})[sid] = c
    return out


def sched_eps(run: str) -> list[int]:
    """调度分片集：enforce 且决定没过期时有跨台视频的集 ∪ 已有 why=sched 领取的集"""
    eps = set(_sched_claims_by_ep(run))
    A = _sched()
    doc = A.enforced(run) if A else None
    if doc:
        eps |= set(A.cross_video_eps(doc))
    return sorted(eps)


def sched_ep_cfg(run: str, ep: int) -> dict | None:
    A = _sched()
    doc = A.enforced(run) if A else None
    owner = (A.cross_video_eps(doc).get(int(ep)) if doc else None)
    if not owner:
        cl = _sched_claims_by_ep(run).get(int(ep)) or {}
        owner = next((c.get("owner") for c in cl.values() if c.get("owner") in _SCHED_HOSTS), None)
    if owner not in _SCHED_HOSTS:
        return None
    return {"owner": owner, "weights": {h: 1.0 for h in _SCHED_HOSTS}, "map": {}, "hosts": sorted(_SCHED_HOSTS),
            "owner_only": True, "sched": True}


def sched_claims(c: dict, plan_map: dict, merged: dict, claims: dict, want: dict, now: float,
                 misses: dict | None = None, lease_s: float = CLAIM_LEASE_S, claim_from=None) -> dict:
    """纯函数（笔记本 shard_relay 调）：调度器要的 {镜: 主机} → 新领取表。
    · 已开工 / 已落定的镜不动（主机归属不能翻）；sticky（失联收回）不动；
    · 调度器要回 owner 的镜：撤掉没开工的 why=sched 领取；
    · 要去别台：写 {host, from, at, why=sched, owner}；同台已领着就不刷新 at（租约照走，到期没开工 = 回 owner）；
    · misses[镜] = {host, t}：派给那台租约到期都没开工 → SCHED_MISS_COOLDOWN_S 内不再派给它（防来回派）"""
    cl = live_claims(claims, merged, now, lease_s)
    for sid, h in sorted((want or {}).items()):
        if sid not in plan_map or h not in c["hosts"] or _started((merged or {}).get(sid)):
            continue
        if claim_from is not None and h != plan_map[sid] and plan_map[sid] not in claim_from:
            continue                                   # 复审 B1：owner 的 state 不新鲜（可能已开工没回报）→ 不从它那里抢，防两台都出 / 翻主机
        cur = cl.get(sid)
        if cur and cur.get("sticky"):
            continue
        if h == plan_map[sid]:
            if cur and str(cur.get("why") or "").startswith(SCHED_WHY):
                cl.pop(sid)
            continue
        if cur and cur.get("host") == h:
            continue
        m = (misses or {}).get(sid) or {}
        if m.get("host") == h and now - float(m.get("t") or 0) < SCHED_MISS_COOLDOWN_S:
            continue
        cl[sid] = {"host": h, "from": plan_map[sid], "at": now, "why": SCHED_WHY, "owner": c["owner"]}
    return cl


def sched_misses(old: dict, new: dict, merged: dict, misses: dict | None, now: float, lease_s: float = CLAIM_LEASE_S) -> dict:
    """上一轮的 why=sched 领取这一轮没了、镜也没开工、且确实是租约到期（不是调度器改主意 / 决定过期撤回，复审 B2）→ 记 miss"""
    out = {s: m for s, m in (misses or {}).items() if now - float(m.get("t") or 0) < SCHED_MISS_COOLDOWN_S}
    for sid, c in (old or {}).items():
        if (str(c.get("why") or "").startswith(SCHED_WHY) and sid not in (new or {}) and not _started((merged or {}).get(sid))
                and now - float(c.get("at") or now) >= lease_s):
            out[sid] = {"host": c.get("host"), "t": now}
    return out
