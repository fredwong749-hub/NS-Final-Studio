"""两台 producer 登记表按对象合并（W-FIX-PIPE #8，SCAN_20261107，L-212 只做读侧）。

事故：首尾帧 / 视频结果只在出它的那台登记表里，另一台永远不知道 → 同一集两台数字不一（ep01 视频 10 / 14，ep02 首帧 0 / 14），
网页 / KPI 读哪台就是哪台的残缺版。单一登记表（L-209 S2.5）之前，读的人一律先合并：
  · 每个对象（每镜 first / last / video / assets，每集 objects）取各台里“走得最远”的那份：
    passed > best_effort > running > ready > failed > pending > 其它 / 缺；同级保留底表（本机）那份；
  · 底表对象带驳回 / 重做 / 过期标记（redo / master_reject / stale / regen）→ 不被别台盖（项目方 / 总调度驳回优先）；
  · 被换上的对象带 merged_from=<host>；每集 have.passed 按合并后的对象重算（视频含 best_effort 的口径不变：只数 passed）。
纯函数，不读写文件；读文件的是调用方（ns_api.shot_status.merged_registry、ns_api.episode_kpi）。KPI 计数口径仍是
tools/brain/kpi_core（telemetry.kpi 两台逐字段取最大，W-SCAN）——本模块不重复它。
"""
from __future__ import annotations

import copy

RANK = {"passed": 6, "done": 6, "best_effort": 5, "running": 4, "ready": 3, "failed": 2, "pending": 1}
KEEP_MARKS = ("redo", "master_reject", "stale", "regen")
KINDS = ("first", "last", "video")


def rank(o: dict | None) -> int:
    return RANK.get(str((o or {}).get("status") or ""), 0) if isinstance(o, dict) else -1


def pick(base: dict | None, other: dict | None, host: str) -> dict | None:
    """一个对象：other 比 base 走得远且 base 没有驳回 / 重做标记 → 用 other（标 merged_from）；否则 base"""
    if not isinstance(other, dict):
        return base
    if isinstance(base, dict) and any(base.get(k) for k in KEEP_MARKS):
        return base
    if any(other.get(k) for k in KEEP_MARKS):     # 复审 11-07：别台带驳回 / 重做标记 → 它赢（不让本机旧的 passed 盖掉项目方的驳回）
        return {**other, "merged_from": host}
    if rank(other) > rank(base):
        return {**other, "merged_from": host}
    return base


def merge_registries(base: dict | None, others: dict[str, dict]) -> dict:
    """base = 本机登记表；others = {host: 那台登记表}。返回新 dict（不改入参）；加 merged_hosts=[参与合并且有内容的台]"""
    out = copy.deepcopy(base or {})
    eps = out.setdefault("episodes", [])
    by_ep = {int(E.get("ep") or 0): E for E in eps if isinstance(E, dict)}
    used = []
    for host, reg in (others or {}).items():
        if not isinstance(reg, dict) or not reg.get("episodes"):
            continue
        used.append(host)
        for OE in reg.get("episodes") or []:
            ep = int(OE.get("ep") or 0)
            E = by_ep.get(ep)
            if E is None:
                E = {**copy.deepcopy(OE), "merged_from": host}
                eps.append(E)
                by_ep[ep] = E
                continue
            eo = E.setdefault("objects", {})
            for k, o in (OE.get("objects") or {}).items():
                eo[k] = pick(eo.get(k), o, host)
            shots = {S.get("shot"): S for S in E.setdefault("shots", []) if isinstance(S, dict)}
            for OS in OE.get("shots") or []:
                S = shots.get(OS.get("shot"))
                if S is None:
                    E["shots"].append({**copy.deepcopy(OS), "merged_from": host})
                    continue
                so = S.setdefault("objects", {})
                for k, o in (OS.get("objects") or {}).items():
                    so[k] = pick(so.get(k), o, host)
    for E in eps:
        shots = [S for S in E.get("shots") or [] if isinstance(S, dict)]
        if shots:
            hv = E.setdefault("have", {})
            hv["passed"] = {k: sum(1 for S in shots if ((S.get("objects") or {}).get(k) or {}).get("status") == "passed") for k in KINDS}
            hv["total"] = max(int(hv.get("total") or 0), len(shots))
    eps.sort(key=lambda E: int(E.get("ep") or 0))
    out["merged_hosts"] = used
    return out
