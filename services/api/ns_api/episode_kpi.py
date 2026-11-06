"""每集进度 / KPI 面板（UIUX-LOOP r3，11-06；L-205 一集 ≤ 50 min、L-207 一集严格三段：首尾帧 → 全卡视频 → 合成）。

GET /api/episodes/kpi?run=
  → {run, at, budget_min, source:{kpi, snapshot_at, snapshot_age_s, registry_age_s},
     episodes:[{ep, title, total, phase, phase_word, state, start, elapsed_min, eta_min, over_min,
                first_done, last_done, fallback_n, video_done, assembled,
                shots:[{id, index, first:{state,url}, last:{state,url,fallback}, video:{state,url}}]}]}
来源（只读、都是本机已有的文件，不在请求里连机器）：
  · 集级数字（起点 / 用时 / 完成数 / 状态）= tools/brain/kpi_core.episodes（和大脑 telemetry.kpi 同一函数，L-212 #9）：
    起点 = max(首派, 最近导入)；首派 = 大脑快照（两台最早，30 分钟内才认）与本机 producer log.jsonl 取早；
    完成数 = 本机登记表 have.passed 与快照两台逐字段取最大（best_effort 不算视频完成）
  · 每镜状态 = 当前剧活的 producer 登记表（shot_status.registry_path，r1 同一来源）：passed / ready / running / pending / failed / best_effort
  · 图 = 每镜 takes.json 的当前版（通过才会是当前）；尾帧兜底（frames_index.last_fallback）单独标 fallback
  · 阶段 = data/pipeline/lane_roles_state.json <run>._active（L-207 run 级唯一排序源）优先；没有就按登记表自算：
    not_started → frames（首尾帧）→ videos（全卡视频）→ assembly（合成）→ done（已合成）
状态词全是大白话；时间 JST。
"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import APIRouter

ROOT = Path(__file__).resolve().parents[3]
router = APIRouter(tags=["episode-kpi"])
JST = timezone(timedelta(hours=9))
BUDGET_MIN = 50
SNAPSHOT = ROOT / "data" / "brain" / "snapshot.json"
SNAPSHOT_FRESH_S = 1800
CACHE_TTL_S = 10.0
PHASE_WORD = {"not_started": "还没开始", "frames": "出首尾帧", "videos": "全部显卡出视频", "assembly": "合成整集", "done": "已合成"}
STATE_WORD = {"passed": "已定下", "ready": "排队", "running": "在出", "pending": "等上一步", "failed": "没出来", "best_effort": "尽力版",
              "fallback": "不用尾帧", "na": "—"}
_cache: dict[str, tuple[float, dict]] = {}


def _jst(t: float | None, fmt: str = "%m-%d %H:%M") -> str | None:
    return datetime.fromtimestamp(t, JST).strftime(fmt) if t else None


def _j(p: Path, default=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 显示层：读不到 = 没有这部分数据，面板写明
        return default


def _budget() -> int:
    """config/pipeline/kpi.json {episode_budget_min} 可调；默认 L-205 的 50"""
    d = _j(ROOT / "config" / "pipeline" / "kpi.json", {}) or {}
    try:
        return int(d.get("episode_budget_min") or BUDGET_MIN)
    except (TypeError, ValueError):  # arch-ok: 配置写坏 = 默认 50
        return BUDGET_MIN


def first_dispatch_local(log: Path) -> dict[str, float]:
    """本机同步回来的 producer log.jsonl：每集第一次 dispatch 的 t（telemetry REMOTE_PROBE 同一算法）"""
    out: dict[str, float] = {}
    try:
        with log.open(encoding="utf-8") as f:
            for ln in f:
                if '"dispatch"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:  # arch-ok: 日志里一行写坏（同步截断）= 跳过这一行，其余照算；显示层不因一行坏就没起点
                    continue
                if d.get("ev") != "dispatch" or not d.get("t"):
                    continue
                ob = str(d.get("obj") or "")
                ep = ob.split(":", 1)[-1].split("-", 1)[0].replace("ep", "").lstrip("0") or "0"
                if ep not in out or d["t"] < out[ep]:
                    out[ep] = float(d["t"])
    except OSError:  # arch-ok: 日志还没同步到本机 = 没有起点，面板按“起点未知”显示（source.kpi=local 时在页面标出）
        pass
    return out


def _obj_state(o: dict | None) -> str:
    st = (o or {}).get("status") if isinstance(o, dict) else None
    return st if st in STATE_WORD else ("na" if not st else "pending")


def _active_phase(run: str) -> dict[str, dict]:
    """lane_roles_state.json <run>._active = {ep, phase}（L-207）；读不到 = {}"""
    d = _j(ROOT / "data" / "pipeline" / "lane_roles_state.json", {}) or {}
    a = ((d.get(run) or {}).get("_active") or {}) if isinstance(d, dict) else {}
    return {str(a.get("ep")): a} if a.get("ep") else {}


def derive_phase(total: int, first_done: int, last_done: int, fallback_n: int, video_done: int, assembled: bool, started: bool) -> str:
    """assembled 但视频没齐（16:56 那种缺镜预览）不算“已合成”，算“合成整集”阶段——L-204 ③ 到点必交的成片是全镜的"""
    if assembled and (not total or video_done >= total):
        return "done"
    if assembled or (total and video_done >= total):
        return "assembly"
    if total and first_done >= total and last_done + fallback_n >= total:
        return "videos"
    if started or first_done or last_done or video_done:
        return "frames"
    return "not_started"


_KC = None


def _kc():
    """tools/brain/kpi_core.py（每集 KPI 唯一口径，L-212 #9）"""
    global _KC
    if _KC is None:
        import importlib.util  # noqa: PLC0415
        sp = importlib.util.spec_from_file_location("kpi_core_for_api", ROOT / "tools" / "brain" / "kpi_core.py")
        m = importlib.util.module_from_spec(sp)
        sp.loader.exec_module(m)
        _KC = m
    return _KC


def build(*, registry: dict, renders: Path, snapshot: dict | None, local_starts: dict[str, float], now: float | None = None,
          budget_min: int = BUDGET_MIN, active: dict[str, dict] | None = None, url=None, vurl=None, imports: dict | None = None,
          film_of=None) -> dict:
    """纯函数（tests 用）。url / vurl：rel → /files 地址（默认 frames_index._url / video_index._url）；
    imports {集: 最近导入 epoch}（kpi_core.import_epochs；默认 {}）——计时起点 = max(首派, 最近导入)（L-212 #9，和大脑同一函数）；
    film_of(ep) → 最新一版整集成片（cuts.latest_film：name / url / at / gate），没有 = None（UIUX-LOOP-3 r12：面板每集一个“最新成片”入口，
    标签诚实：预览版（合成闸门没过：缺 N 镜用占位）/ 成片（闸门通过））"""
    imports = imports or {}
    film_of = film_of or (lambda ep: None)
    from ns_api import frames_index as FI
    from ns_api import video_index as VI
    url = url or (lambda rel: FI._url(rel))
    vurl = vurl or VI._url
    now = time.time() if now is None else now
    snap_t = float((snapshot or {}).get("t") or 0)
    snap_fresh = bool(snapshot) and now - snap_t < SNAPSHOT_FRESH_S
    kpi = (snapshot or {}).get("kpi") or {} if snap_fresh else {}
    eps_out = []
    for E in registry.get("episodes") or []:
        try:
            ep = int(E.get("ep") or 0)
        except (TypeError, ValueError):
            continue
        if not ep:
            continue
        shots = []
        first_done = last_done = video_done = fallback_n = 0
        active_n = 0   # 有任何对象派过（排队 / 在出 / 定下 / 没出来）= 这集已经开始，哪怕起点时间还没同步到
        for S in sorted(E.get("shots") or [], key=lambda s: int(s.get("index") or 0)):
            sid = str(S.get("shot") or "")
            m = re.fullmatch(r"ep(\d+)-S(\d+)", sid)
            if not m:
                continue
            objs = S.get("objects") or {}
            takes = _j(renders / f"ep{ep:02d}" / f"S{m.group(2)}" / "takes.json", {}) or {}
            act = takes.get("active") or {}
            by_n = {(t.get("stage"), t.get("n")): t for t in takes.get("takes") or []}
            fb = FI.last_fallback(takes)
            cell = {}
            for key, stage, mk in (("first", "image", url), ("last", "last", url), ("video", "video", vurl)):
                st = _obj_state(objs.get(key))
                t = by_n.get((stage, act.get(stage))) if act.get(stage) is not None else None
                cell[key] = {"state": st, "url": mk(t.get("file")) if t else None}
            if fb and cell["last"]["url"] is None:
                cell["last"] = {"state": "fallback", "url": None, "fallback": fb}
                fallback_n += 1
            else:
                cell["last"]["fallback"] = None
            active_n += any(cell[k]["state"] in ("ready", "running", "passed", "best_effort", "failed") for k in ("first", "last", "video"))
            first_done += cell["first"]["state"] == "passed"
            last_done += cell["last"]["state"] == "passed"
            video_done += cell["video"]["state"] in ("passed", "best_effort")
            shots.append({"id": sid, "index": int(m.group(2)), **cell})
        # L-212 #9：集级数字（起点 / 用时 / 首尾视频完成数 / 状态）只走 tools/brain/kpi_core（和大脑同一函数）。
        # 完成数 = 登记表 have.passed 与大脑快照（两台最大）逐字段取最大；登记表没有 have（旧格式 / 测试）才用逐镜数
        KC = _kc()
        if E.get("have"):
            have = KC.merge_have(None, **KC.have_from_registry_episode(E))
        else:
            have = KC.merge_have(None, total=len(shots), first=first_done, last=last_done, video=video_done,
                                 assembled=((E.get("objects") or {}).get("assembly") or {}).get("status") == "passed")
        k = kpi.get(str(ep)) or {}
        if "total" in k:
            have = KC.merge_have(have, total=k.get("total"), first=k.get("first_done"), last=k.get("last_done"),
                                 video=k.get("video_done"), assembled=k.get("assembled"))
        elif k.get("assembled"):
            have["assembled"] = True
        fd = [x for x in (local_starts.get(str(ep)), k.get("first_dispatch_t")) if x]
        if k and "first_dispatch_t" not in k and k.get("elapsed_min") is not None:
            fd = [now - float(k["elapsed_min"]) * 60]      # 旧版快照只有用时，没有首派时刻
        rec = KC.episodes(now, {str(ep): min(fd)} if fd else {}, {str(ep): have}, imports, budget_min).get(str(ep)) or {}
        if k and "first_dispatch_t" not in k and k.get("eta_min") is not None:
            rec["eta_min"] = k["eta_min"]
        total = have["total"] or len(shots)
        first_done, last_done, video_done, asm = have["first_done"], have["last_done"], have["video_done"], have["assembled"]
        start, elapsed, eta = rec.get("start"), rec.get("elapsed_min"), rec.get("eta_min")
        ph = (active or {}).get(str(ep), {}).get("phase")
        phase = ph if ph in PHASE_WORD else derive_phase(total, first_done, last_done, fallback_n, video_done, asm, bool(start) or active_n > 0)
        state = rec.get("state") or "not_started"
        if state == "no_registry":
            state = "in_budget" if elapsed is not None and elapsed <= budget_min else "over_budget"
        imp = rec.get("import_t")
        fdt = rec.get("first_dispatch_t")
        before_import = bool(imp and fdt and fdt < imp - 60)      # 本集首派早于本版剧本导入 → 计时已从导入重新算（面板写明）
        eps_out.append({"ep": ep, "title": str(E.get("title") or ""), "total": total, "phase": phase, "phase_word": PHASE_WORD[phase],
                        "state": state, "start": start, "elapsed_min": elapsed, "eta_min": eta,
                        "import_at": _jst(imp), "start_before_import": before_import, "clock_from": rec.get("clock_from"),
                        "over_min": round(elapsed - budget_min, 1) if elapsed is not None and elapsed > budget_min and state != "assembled" else None,
                        "first_done": first_done, "last_done": last_done, "fallback_n": fallback_n, "video_done": video_done,
                        "assembled": asm, "film": _film_brief(film_of(ep)), "shots": shots})
    eps_out.sort(key=lambda e: e["ep"])
    hb = registry.get("heartbeat")
    return {"run": registry.get("run"), "at": _jst(now, "%Y-%m-%d %H:%M:%S"), "budget_min": budget_min,
            "source": {"kpi": "brain" if kpi else "local", "snapshot_at": (snapshot or {}).get("at") if snapshot else None,
                       "snapshot_age_s": int(now - snap_t) if snap_t else None,
                       "registry_age_s": int(now - float(hb)) if hb else None},
            "episodes": eps_out}


def _film_brief(film: dict | None) -> dict | None:
    """面板用的最新成片摘要（cuts.latest_film 的子集 + 一句大白话）"""
    if not film:
        return None
    g = film.get("gate") or {}
    return {"name": film["name"], "version": film.get("version"), "url": film["url"], "at": film["at"],
            "duration_s": film.get("duration_s"), "video_shots": film.get("video_shots"), "placeholder_shots": film.get("placeholder_shots"),
            # r14：timeline 还没同步到本机 = 不知道闸门结论，既不冒充成片也不叫预览版
            "kind": g.get("kind") or "unknown", "kind_word": g.get("kind_word") or "整集成片", "word": g.get("word") or "闸门记录还没同步到本机",
            "missing_n": g.get("missing_n") or 0, "missing": [m.get("shot") for m in (g.get("missing") or [])],
            "post": bool(g.get("post"))}


def _build_live(run: str | None) -> dict:
    from ns_api import run_paths as RP
    from ns_api import shot_status as SS
    from ns_api import cuts as C
    run = run or RP.current_run(ROOT)
    pd = RP.producer_dir(ROOT, run)
    reg = SS.merged_registry(SS.registry_path() if run == RP.current_run(ROOT) else pd / "registry.json") or {}   # W-FIX-PIPE #8：两台按对象合并
    epdir = RP.episodes_dir(ROOT, run)
    return build(registry=reg, renders=RP.renders_root(ROOT, run), snapshot=_j(SNAPSHOT, None),
                 local_starts=first_dispatch_local(pd / "log.jsonl"), budget_min=_budget(), active=_active_phase(run),
                 imports=_kc().import_epochs(ROOT, run),
                 film_of=lambda ep: C.latest_film(epdir, ep, ROOT / "data"))


@router.get("/api/episodes/kpi")
def episodes_kpi(run: str | None = None):
    key = run or ""
    hit = _cache.get(key)
    if hit and time.time() - hit[0] < CACHE_TTL_S:
        return hit[1]
    out = _build_live(run)
    _cache[key] = (time.time(), out)
    return out
