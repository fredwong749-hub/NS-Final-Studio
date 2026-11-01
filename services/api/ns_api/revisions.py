"""
资产二次修改 P0：资产版本 / 依赖已更新 / 影响面（docs/ux_round5/B_revision.md §5）。全部只读，不提交任务、不改配置。

    GET  /api/revisions/keys?type=           全部依赖键：当前 rev / vN / 账本版本数 / 被多少镜头格子用着
    GET  /api/revisions/{key}                单个键：账本版本列表 + 每个 rev 被多少格用着
    POST /api/revisions/impact               {changes:[{key, to_rev?}], episodes?:[n]} → 影响面（不写任何东西）
    POST /api/revisions/impact-shots         {shots:[id], stages?, label?} → 同口径影响面（UX5：形象 / 单品 / 场景用，只读）
    GET  /api/shots/{shot_id}/deps           本镜每格当前 / 定稿版本的 deps 与“依赖已更新”项

影响面口径：每镜每格看“当前版本”和“定稿版本”；take.deps 里记了该键 = 直接受影响（estimated=false），
旧版本没盖章时按本镜在画人物 / 所用预设 / 基底推断（estimated=true）。已定稿 / 项目方定稿单独计数
（locked / owner_locked），default_selected=false —— 后续批量重出默认不勾已定稿的（C_research §4 #5 / #13）。
GPU 时间 = 近期同类已完成任务耗时中位数（无历史用 jobs.ETA_DEFAULT_S）× 格数，并按可用道数给并行估计。
GET /api/revisions/keys 会顺手调 asset_revs.observe()：账本里没有的当前版本记一行（baseline / observed），只追加。
不做内容检测。
"""
from __future__ import annotations

import json
import re
import statistics
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ns_agent import asset_revs as AR
from ns_agent import asset_revs_p1 as ARP
from ns_render import pipeline as P

router = APIRouter(tags=["revisions"])
STAGES = ("image", "last", "video")
JOB_KIND = {"image": "frame", "last": "frame", "video": "video"}
OWNER_TYPES = {"identity": "换定妆 / 身份参考 = 定妆确认", "loraslot": "换身份 LoRA 指针",
               "voice": "换音色", "preset": "改出图预设内容（会影响已出镜头）", "vbase": "改视频基底配方（会影响已出视频）"}
CHAIN = {"image": ["last", "video"], "last": ["video"], "video": ["cut"]}


# ------------------------------------------------------------------ 扫描镜头版本

def _shot_dirs() -> list[tuple[str, Path]]:
    out = []
    for d in sorted(P.RENDERS.glob("ep*/S*")):
        if d.is_dir() and (d / "takes.json").is_file():
            out.append((f"{d.parent.name}-{d.name}", d))
    return out


def _load(d: Path) -> dict:
    try:
        return json.loads((d / "takes.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _episode(shot_id: str) -> int | None:
    try:
        return int(shot_id.split("-")[0][2:])
    except (ValueError, IndexError):
        return None


def _cells(data: dict):
    """每格（stage）的当前 / 定稿版本（去重）→ (stage, take, is_locked, is_active)"""
    takes = data.get("takes") or []
    act, lk = data.get("active") or {}, data.get("locked") or {}
    for st in STAGES:
        for n in dict.fromkeys(x for x in (act.get(st), lk.get(st)) if x is not None):
            t = next((x for x in takes if x.get("stage") == st and x.get("n") == n), None)
            if t:
                yield st, t, lk.get(st) == n, act.get(st) == n


def _owner_locked(data: dict, stage: str, n: int) -> bool:
    lb = (data.get("locked_by") or {}).get(stage)
    return not (isinstance(lb, dict) and lb.get("by") == "auto" and lb.get("n") == n)


def _estimate_match(key: str, shot_id: str, stage: str, take: dict) -> bool:
    typ, _, rest = key.partition(":")
    params = take.get("params") or {}
    if typ in ("identity", "loraslot"):
        slug = rest.partition(":")[0]
        return stage in ("image", "last") and slug in AR.present_characters(shot_id, P.ROOT)
    if typ == "preset":
        return stage in ("image", "last") and params.get("preset") == rest
    if typ == "vbase":
        return stage == "video" and params.get("base") == rest
    if typ == "vlora":
        return stage == "video" and rest in AR._extra_vloras(params)
    return False


def _used_by() -> dict[str, dict[str, int]]:
    """{key: {rev: 格数}}（只数盖过章的当前 / 定稿版本）"""
    out: dict[str, dict[str, int]] = {}
    for _sid, d in _shot_dirs():
        for _st, t, _lk, _ac in _cells(_load(d)):
            for k, r in (t.get("deps") or {}).items():
                out.setdefault(k, {}).setdefault(r, 0)
                out[k][r] += 1
    return out


# ------------------------------------------------------------------ GPU 时间

def _per_job_s() -> dict[str, float]:
    from ns_api import jobs as J
    out = {}
    try:
        done = J._done_jobs()
    except Exception:  # noqa: BLE001
        done = []
    for kind in ("frame", "video"):
        ds = [float(j["wall_s"]) for j in done if j.get("kind") == kind][:J.ETA_SAMPLES * 4]
        out[kind] = round(statistics.median(ds), 1) if ds else float(J.ETA_DEFAULT_S.get(kind, 70.0))
    return out


def _lane_count() -> int:
    try:
        from ns_api import jobs as J
        return max(1, len([x for x in J.lanes(probe=False) if not x.get("disabled")]))
    except Exception:  # noqa: BLE001
        return 1


# ------------------------------------------------------------------ 接口

@router.get("/api/revisions/keys")
def get_keys(type: str | None = None):   # noqa: A002 — 查询参数名按契约
    try:
        AR.observe(P.ROOT)
    except OSError:
        pass
    led = AR.read_ledger(P.ROOT)
    used = _used_by()
    rows = []
    for k, r in sorted(AR.all_keys(P.ROOT).items()):
        if type and not k.startswith(f"{type}:"):
            continue
        hist = led.get(k) or []
        last = next((h for h in reversed(hist) if h.get("rev") == r), None)
        rows.append({"key": k, "type": k.split(":")[0], "label": AR.label(k, P.ROOT),
                     "current": {"rev": r, "seq": AR.seq_of(k, r, led), "at": (last or {}).get("at"),
                                 "by": (last or {}).get("by")},
                     "versions_count": len({h["rev"] for h in hist}),
                     "used_by_count": sum((used.get(k) or {}).values()),
                     "used_by_current": (used.get(k) or {}).get(r, 0),
                     "unregistered_change": bool(last and last.get("by") == "observed")})
    return {"keys": rows, "types": list(AR.TYPES)}


@router.get("/api/revisions/{key}")
def get_key(key: str):
    cur = AR.current_rev(key, P.ROOT)
    led = AR.read_ledger(P.ROOT)
    hist = led.get(key) or []
    if cur is None and not hist:
        raise HTTPException(404, f"没有这个依赖键：{key}")
    used = _used_by().get(key) or {}
    versions, seen = [], set()
    for h in hist:
        if h["rev"] in seen:
            continue
        seen.add(h["rev"])
        versions.append({**h, "state": "current" if h["rev"] == cur else "superseded", "used_by": used.get(h["rev"], 0),
                         "has_snapshot": ARP.has_snapshot(key, h["rev"], P.ROOT)})
    return {"key": key, "label": AR.label(key, P.ROOT),
            "current": {"rev": cur, "seq": AR.seq_of(key, cur, led)}, "versions": versions,
            "used_by": used, "unregistered": cur is not None and cur not in seen,
            # P1：回滚是否属于项目方闸门（定妆 / 身份 LoRA / 音色）；配置型的回滚只写提议，不直接改 config/
            "gated": ARP.is_gated(key), "gate_label": ARP.GATED.get(key.split(":")[0]),
            "config_backed": key.split(":")[0] in ARP.CONFIG_TYPES}


class Change(BaseModel):
    key: str
    to_rev: str | None = None


class ImpactBody(BaseModel):
    changes: list[Change] = Field(default_factory=list)
    episodes: list[int] | None = None


def impact(body: ImpactBody) -> dict:
    if not body.changes:
        raise HTTPException(422, "changes 不能为空")
    led = AR.read_ledger(P.ROOT)
    cells, seen = [], set()
    for sid, d in _shot_dirs():
        ep = _episode(sid)
        if body.episodes and ep not in body.episodes:
            continue
        data = _load(d)
        for st, t, is_locked, is_active in _cells(data):
            for ch in body.changes:
                deps = t.get("deps") or {}
                if ch.key in deps:
                    if ch.to_rev and deps[ch.key] == ch.to_rev:
                        continue
                    est, frm = False, deps[ch.key]
                elif _estimate_match(ch.key, sid, st, t):
                    est, frm = True, None
                else:
                    continue
                if (sid, st, t["n"]) in seen:
                    continue
                seen.add((sid, st, t["n"]))
                own = is_locked and _owner_locked(data, st, t["n"])
                cells.append({"shot_id": sid, "episode": ep, "stage": st, "take_n": t["n"], "key": ch.key,
                              "from_rev": frm, "from_v": AR.seq_of(ch.key, frm, led) if frm else None,
                              "active": is_active, "locked": is_locked, "owner_locked": own, "estimated": est,
                              "chain": CHAIN[st] if is_locked else [], "default_selected": not is_locked})
    owner = [OWNER_TYPES[t] for t in dict.fromkeys(ch.key.split(":")[0] for ch in body.changes)
             if t in OWNER_TYPES and (t in ("identity", "loraslot", "voice") or cells)]
    changes = [{"key": ch.key, "label": AR.label(ch.key, P.ROOT),
                "current": {"rev": (cur := AR.current_rev(ch.key, P.ROOT)), "seq": AR.seq_of(ch.key, cur, led)},
                "to": {"rev": ch.to_rev, "seq": AR.seq_of(ch.key, ch.to_rev, led)} if ch.to_rev else None}
               for ch in body.changes]
    return _summarize(cells, changes, owner)


def _summarize(cells: list[dict], changes: list[dict], owner: list[str]) -> dict:
    by_ep: dict[str, dict[str, int]] = {}
    by_stage = {st: 0 for st in STAGES}
    for c in cells:
        e = by_ep.setdefault(str(c["episode"]), {st: 0 for st in STAGES})
        e[c["stage"]] += 1
        by_stage[c["stage"]] += 1
    per = _per_job_s()
    lanes = _lane_count()
    # 同一格（镜 + stage）只重出一次：当前版本和定稿版本不同也只算一个任务
    jobs = {(c["shot_id"], c["stage"]) for c in cells}
    sel = {(c["shot_id"], c["stage"]) for c in cells if c["default_selected"]}
    def secs(keys):
        return round(sum(per[JOB_KIND[st]] for _s, st in keys), 1)
    return {
        "changes": changes,
        "cells": cells,
        "counts": {"cells": len(cells), "shots": len({c["shot_id"] for c in cells}),
                   "locked": sum(1 for c in cells if c["locked"]),
                   "owner_locked": sum(1 for c in cells if c["owner_locked"]),
                   "unlocked": sum(1 for c in cells if not c["locked"]),
                   "estimated": sum(1 for c in cells if c["estimated"])},
        "by_episode": by_ep, "by_stage": by_stage,
        "gpu_estimate_s": {"per_job": per, "lanes": lanes,
                           "all": {"jobs": len(jobs), "serial": secs(jobs), "parallel": round(secs(jobs) / lanes, 1)},
                           "default_selected": {"jobs": len(sel), "serial": secs(sel),
                                                "parallel": round(secs(sel) / lanes, 1)}},
        "requires_owner": bool(owner), "owner_reasons": owner,
        "note": "只读预览：不写任何东西、不提交任务；已定稿的格默认不勾（default_selected=false）",
    }


@router.post("/api/revisions/impact")
def post_impact(body: ImpactBody):
    return impact(body)


class ShotsImpactBody(BaseModel):
    shots: list[str] = Field(default_factory=list)
    stages: list[str] | None = None
    label: str | None = None


def impact_shots(body: ShotsImpactBody) -> dict:
    """UX5：形象 / 单品 / 场景底图还没进依赖账本（B §7 P1），前端按“实际编译结果”（集摘要里每镜的人物 + 形象）
    算出用到它的镜头；这里只补每镜每格的当前 / 定稿状态，口径与 impact 相同（estimated=true，已定稿默认不勾）。只读。"""
    if not body.shots:
        raise HTTPException(422, "shots 不能为空")
    stages = [st for st in (body.stages or ["image"]) if st in STAGES]
    if not stages:
        raise HTTPException(422, "stages 只能是 image / last / video")
    key = f"shots:{(body.label or '').strip()[:60]}"
    cells, seen = [], set()
    for sid in dict.fromkeys(body.shots):
        if not re.fullmatch(r"ep\d+-S\d+", sid):
            continue
        d = P.shot_dir(sid)
        if not (d / "takes.json").is_file():
            continue
        data = _load(d)
        for st, t, is_locked, is_active in _cells(data):
            if st not in stages or (sid, st, t["n"]) in seen:
                continue
            seen.add((sid, st, t["n"]))
            cells.append({"shot_id": sid, "episode": _episode(sid), "stage": st, "take_n": t["n"], "key": key,
                          "from_rev": None, "from_v": None, "active": is_active, "locked": is_locked,
                          "owner_locked": is_locked and _owner_locked(data, st, t["n"]), "estimated": True,
                          "chain": CHAIN[st] if is_locked else [], "default_selected": not is_locked})
    return _summarize(cells, [{"key": key, "label": body.label or "所选镜头", "current": {"rev": None, "seq": None},
                               "to": None}], [])


@router.post("/api/revisions/impact-shots")
def post_impact_shots(body: ShotsImpactBody):
    return impact_shots(body)


@router.get("/api/shots/{shot_id}/deps")
def get_shot_deps(shot_id: str):
    if not re.fullmatch(r"ep\d+-S\d+", shot_id):
        raise HTTPException(404, f"unknown shot: {shot_id}")
    d = P.shot_dir(shot_id)
    data = _load(d) if (d / "takes.json").is_file() else {}
    led = AR.read_ledger(P.ROOT)
    try:
        from ns_agent.state_timeline import shot_inputs_sha
        cur_inputs = shot_inputs_sha(shot_id, P.ROOT)
    except Exception:  # noqa: BLE001
        cur_inputs = None
    out = {}
    wv = ARP.waivers(P.ROOT, shot_id)
    for st, t, is_locked, is_active in _cells(data):
        stale = AR.stale_deps(t, P.ROOT, led)
        if st in ("image", "last") and (x := AR.inputs_dep(t, cur_inputs)):
            stale.append(x)
        if st == "video" and (x := AR.vbase_drift(t, P.ROOT)):
            stale.append(x)
        for x in stale:   # P1：“保留旧版”豁免（项目方原话，只对豁免时那一个 rev 生效）
            w = ARP.waived(x, shot_id, st, t["n"], wv)
            x["waived"] = {"by": w["by"], "owner_quote": w["owner_quote"], "at": w["at"]} if w else None
        out.setdefault(st, []).append({
            "n": t["n"], "active": is_active, "locked": is_locked, "stamped": bool(t.get("deps")),
            "deps": [{"key": k, "label": AR.label(k, P.ROOT), "rev": r, "v": AR.seq_of(k, r, led),
                      "current": (c := AR.current_rev(k, P.ROOT)), "current_v": AR.seq_of(k, c, led),
                      "fresh": c == r} for k, r in sorted((t.get("deps") or {}).items())],
            "stale_deps": stale})
    return {"shot_id": shot_id, "stages": out}
