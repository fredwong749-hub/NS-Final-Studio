"""“做完”记分卡（W-E2E，L-214）：用活数据算每集和整体离“系统做完”还差多少，项目方一眼看得懂。

每集：
  全自动        这一集从导入起项目方要不要动手（成人镜触发、修改、挑选、待你看里还挂着的卡）——不要 = 是
  用时          KPI 时钟（kpi_core 同口径：导入 / 首派里晚的那个起算）到第一次合成；还没合成 = 到现在（L-205 ≤ 50 分钟）
  首帧一次过率  每镜导入后第一版首帧就过契约（postflight.ok）的比例，目标 ≥ 70%
  尾帧 / 视频   导入后所有版本里过的比例，另给一次过率
整体：
  空卡率        影子调度实测（data/sched/shadow/metrics.json）：现网空闲道·分 / (分钟 × 道数)，目标 < 5%
  项目方撞上的 bug（24 小时，CHANNEL 里项目方报的，尽力识别）
  系统自查未关项（issues.jsonl 里 inv_key 的 open）

数据源都是本机已同步的文件（不连服务器）：data/brain/snapshot.json（KPI）、data/renders/<剧>/epNN/SN/takes.json（首尾帧）、
data/pipeline/runs/<剧>/video/state_<台>.json（视频）、data/episodes/<剧>/（合成时间）、data/sched/shadow/metrics.json、
docs/master/CHANNEL.md、data/pipeline/issues.jsonl、data/owner_queue、owner_adult_triggers.jsonl、frame_edit_requests.json。
输出：docs/master/SCORECARD.md、data/brain/scorecard.json，并在 data/brain/snapshot.md 第二行放一行摘要（大脑快照每拍也会带上）。
  python tools/qa/scorecard.py [--run series10_v2] [--no-write]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
JST = timezone(timedelta(hours=9))
BUDGET_MIN = 50
FIRST_PASS_TARGET = 0.70
IDLE_TARGET = 0.05
OUT_MD = "docs/master/SCORECARD.md"
OUT_JSON = "data/brain/scorecard.json"
SNAP_MD = "data/brain/snapshot.md"
LINE_TAG = "## 记分卡"
# “项目方 …（12 字内）撞上 / 怒 / 点了没… / 原话”——项目方报问题的说法；“项目方批 / 同意 / 选 A”是决定，不算
OWNER_BUG_RE = re.compile(r"项目方[^；。，,]{0,12}?(怒|撞上|撞到|点了|点出|反复|没记录|看不到|没反应|是黑|发现|指出|抱怨|不满|报了|报的|报告|原话)")
NOT_OWNER_AGENTS = ("IDLE-WATCH", "SELF-HEAL", "SELF-CHECK")


def _load(name: str, rel: str):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _j(p: Path, default=None):
    try:
        return json.loads(Path(p).read_text(encoding="utf-8"))
    except (OSError, ValueError):   # arch-ok: 没有 / 坏 = 该项“无数据”（报告里写明）
        return default


def jst_epoch(s) -> float | None:
    """服务器写的时间（JST，裸串或带时区）→ epoch"""
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace(" ", "T"))
    except ValueError:
        return None
    return (d if d.tzinfo else d.replace(tzinfo=JST)).timestamp()


def jst(t: float | None, fmt: str = "%m-%d %H:%M") -> str:
    return datetime.fromtimestamp(t, JST).strftime(fmt) if t else "—"


def pct(x: float | None) -> str:
    return "无数据" if x is None else f"{round(x * 100)}%"


# ------------------------------------------------------------------ 首尾帧（takes.json）
def take_ok(t: dict) -> bool:
    pf = (t or {}).get("postflight") or (t or {}).get("contract") or {}
    return bool(pf.get("ok"))


def frame_rates(takes_by_shot: dict, stage: str, since: float | None) -> dict:
    """takes_by_shot {shot: takes 列表} → 导入后：一次过率（每镜第一版）、总过率（全部版本）"""
    first_n = first_ok = all_n = all_ok = 0
    for _sid, takes in takes_by_shot.items():
        rows = sorted((t for t in takes or [] if t.get("stage") == stage and not t.get("quarantined")
                       and (since is None or (jst_epoch(t.get("created_at")) or 0) >= since)),
                      key=lambda t: (jst_epoch(t.get("created_at")) or 0, int(t.get("n") or 0)))
        if not rows:
            continue
        first_n += 1
        first_ok += take_ok(rows[0])
        all_n += len(rows)
        all_ok += sum(take_ok(t) for t in rows)
    return {"shots": first_n, "first_pass": (first_ok / first_n) if first_n else None,
            "takes": all_n, "pass": (all_ok / all_n) if all_n else None}


def load_takes(root: Path, run: str, ep: int) -> dict:
    RUNS = _load("runs_for_score", "tools/autopilot/runs.py")
    d = Path(RUNS.renders_dir(run, root)) / f"ep{ep:02d}"
    out = {}
    if d.is_dir():
        for sd in sorted(d.iterdir()):
            tj = _j(sd / "takes.json", {}) or {}
            if tj.get("takes"):
                out[f"ep{ep:02d}-{sd.name}"] = tj["takes"]
    return out


# ------------------------------------------------------------------ 视频（state_<台>.json）
def video_rates(states: list[dict], ep: int, since: float | None) -> dict:
    by_shot: dict = {}
    for st in states:
        for sid, r in ((st or {}).get("shots") or {}).items():
            if not str(sid).startswith(f"ep{ep:02d}-"):
                continue
            for x in r.get("renders") or []:
                v = ((x.get("score") or {}).get("verdict"))
                if v is None or (since is not None and float(x.get("t_sub") or 0) < since):
                    continue
                by_shot.setdefault(sid, []).append((float(x.get("t_sub") or 0), str(v).lower() == "pass"))
    n = sum(len(v) for v in by_shot.values())
    ok = sum(p for v in by_shot.values() for _t, p in v)
    firsts = [sorted(v)[0][1] for v in by_shot.values() if v]
    return {"shots": len(firsts), "first_pass": (sum(firsts) / len(firsts)) if firsts else None,
            "renders": n, "pass": (ok / n) if n else None}


# ------------------------------------------------------------------ 用时
def assembled_at(root: Path, run: str, ep: int, since: float | None) -> float | None:
    """导入后第一次合成成片的时间（data/episodes/<剧>/epNN_v*.mp4 的 mtime）"""
    d = root / "data/episodes" / run
    if not d.is_dir() or not since:
        return None
    ts = sorted(p.stat().st_mtime for p in d.glob(f"ep{ep:02d}_v*.mp4") if p.stat().st_mtime >= since)   # arch-ok: 要的就是合成时刻本身（取最早一次），不是“猜最新一份”
    return ts[0] if ts else None


def minutes(k: dict, asm_t: float | None, now: float) -> tuple[float | None, str]:
    """做完 = 合成且每镜都有视频；预览合成（缺镜）不算做完，按到现在算"""
    t0 = k.get("start_t")
    if not t0:
        return None, "没开始"
    complete = bool(asm_t) and int(k.get("video_done") or 0) >= int(k.get("total") or 1)
    if complete:
        return round((asm_t - t0) / 60, 1), "到合成"
    miss = int(k.get("total") or 0) - int(k.get("video_done") or 0)
    return round((now - t0) / 60, 1), (f"预览合成缺 {miss} 镜，到现在" if asm_t else "还在做，到现在")


# ------------------------------------------------------------------ 全自动（项目方要不要动手）
def owner_actions(root: Path, run: str, ep: int, since: float | None, adult_listing: dict | None, open_items: list[dict]) -> list[str]:
    why = []
    tag = f"ep{ep:02d}-"
    for e in (adult_listing or {}).get("episodes") or []:
        if int(e.get("ep") or 0) != ep:
            continue
        n = e.get("counts") or {}
        if e.get("waiting"):
            why.append(f"{e['waiting']} 个成人镜等项目方点")
        if sum(int(n.get(k) or 0) for k in ("triggered", "rendering", "done")):
            why.append("成人镜由项目方触发（按规矩只能他点）")
    fe = _j(root / "data/state/frame_edit_requests.json", []) or []
    n_edit = sum(1 for r in fe if str(r.get("shot", "")).startswith(tag) and (jst_epoch(r.get("at")) or 0) >= (since or 0))
    if n_edit:
        why.append(f"项目方点了 {n_edit} 次首尾帧“修改”")
    n_open = sum(1 for it in open_items if int(it.get("episode") or 0) == ep)
    if n_open:
        why.append(f"待你看还挂着 {n_open} 张这一集的卡")
    return why


# ------------------------------------------------------------------ 整体
def idle_lane(root: Path, lanes: int = 6) -> dict:
    m = _j(root / "data/sched/shadow/metrics.json", {}) or {}
    last = _j(root / "data/sched/shadow/last.json", {}) or {}
    n = len(((last.get("row") or {}).get("lanes")) or {}) or lanes
    mins = float(m.get("minutes") or 0)
    if not mins:
        return {"pct": None, "why": "没有影子调度数据（data/sched/shadow/metrics.json）"}
    idle = float(m.get("live_idle_lane_min") or 0)
    work = float(m.get("live_idle_with_work_lane_min") or 0)
    return {"pct": idle / (mins * n), "with_work_pct": work / (mins * n), "lanes": n, "minutes": round(mins), "since": m.get("since"),
            "shadow_pct": float(m.get("shadow_idle_lane_min") or 0) / (mins * n)}


_CH = re.compile(r"^(\d{2})-(\d{2}) (\d{2}):(\d{2})(?:\(JST\))? \| ([^|]+?) \| (.*)$")


def owner_bugs(channel_text: str, now: float, hours: float = 24) -> list[str]:
    """CHANNEL 里 24 小时内“项目方 + 撞上 / 报 / 怒…”的行（尽力识别，宁多勿漏；IDLE-WATCH / SELF-HEAL 这类机器行不算）"""
    out = []
    yr = datetime.fromtimestamp(now, JST).year
    for ln in channel_text.splitlines():
        m = _CH.match(ln.strip())
        if not m:
            continue
        mo, d, h, mi, who, what = m.groups()
        try:
            t = datetime(yr, int(mo), int(d), int(h), int(mi), tzinfo=JST).timestamp()
        except ValueError:
            continue
        if now - t > hours * 3600 or t - now > 3600 or any(a in who for a in NOT_OWNER_AGENTS):
            continue
        if OWNER_BUG_RE.search(what):
            out.append(f"{mo}-{d} {h}:{mi} {who.strip()}：{what.strip()[:90]}")
    return out


def open_selfcheck(root: Path) -> list[dict]:
    INV = _load("invariants_for_score", "tools/brain/invariants.py")
    return [i for i in INV.load_issues(root / INV.ISSUES_REL) if i.get("inv_key") and i.get("status") == "open"]


# ------------------------------------------------------------------ 汇总
def compute(root: Path = ROOT, run: str | None = None, now: float | None = None, adult_listing=None, open_items=None) -> dict:
    now = now or time.time()
    RUNS = _load("runs_for_score_c", "tools/autopilot/runs.py")
    run = run or RUNS.primary_run(root)
    snap = _j(root / "data/brain/snapshot.json", {}) or {}
    kpi = snap.get("kpi") or {}
    vdir = root / "data/pipeline/runs" / run / "video"
    states = [_j(p, {}) for p in sorted(vdir.glob("state_*.json"))] if vdir.is_dir() else []
    if adult_listing is None:
        try:
            sys.path.insert(0, str(root / "services/api"))
            from ns_api import adult_trigger as AT  # noqa: PLC0415
            adult_listing = AT.listing(run, root)
        except Exception as e:  # noqa: BLE001  # arch-ok: 读不到成人镜清单 = 全自动判定里注明
            adult_listing = {"error": repr(e)[:120]}
    if open_items is None:
        try:
            sys.path.insert(0, str(root / "services/api"))
            from ns_api import owner_queue as OQ  # noqa: PLC0415
            open_items = list(OQ.build(root).get("items") or [])
        except Exception:  # noqa: BLE001  # arch-ok: 队列读不到 = 不计“挂着的卡”（报告里注明）
            open_items = []
    try:   # L-209 S2.5：完成数以唯一合并登记表为准（新鲜才用；缺 / 过期 = 大脑快照 KPI，旧口径）
        RM = _load("registry_merged_for_score", "tools/autopilot/registry_merged.py")
        mhave = RM.ep_have(RM.fresh(run, root, now, log=RM.default_log("scorecard"), actor="scorecard") or {})
    except Exception:  # noqa: BLE001  # arch-ok: 合并表模块读不到 = 用快照 KPI
        mhave = {}
    eps = []
    for ep_s, k in sorted(kpi.items(), key=lambda kv: int(kv[0]) if str(kv[0]).isdigit() else 0):
        mh = mhave.get(str(ep_s))
        if mh:
            k = {**k, "total": mh["t"] or k.get("total"), "first_done": mh["f"], "last_done": mh["l"], "video_done": mh["v"]}
        ep = int(ep_s)
        since = k.get("start_t") or k.get("import_t")
        asm = assembled_at(root, run, ep, k.get("start_t")) if k.get("assembled") else None
        mins, mins_how = minutes(k, asm, now)
        takes = load_takes(root, run, ep)
        win = "本次导入后"
        fr = frame_rates(takes, "image", since)
        if not fr["shots"] and takes:          # 重新导入后没重出（沿用旧版）→ 按这一集全程算，表里注明
            since, win = None, "全程"
            fr = frame_rates(takes, "image", since)
        lr, vr = frame_rates(takes, "last", since), video_rates(states, ep, since)
        why = owner_actions(root, run, ep, since, adult_listing, open_items)
        eps.append({"ep": ep, "total": k.get("total"), "first_done": k.get("first_done"), "last_done": k.get("last_done"),
                    "video_done": k.get("video_done"), "assembled": bool(k.get("assembled")), "state": k.get("state"),
                    "start": k.get("start"), "minutes": mins, "minutes_how": mins_how, "in_budget": (mins is not None and mins <= BUDGET_MIN and mins_how == "到合成"), "window": win,
                    "counts_src": "registry_merged" if mh else "snapshot", "full_auto": not why, "owner_needed": why, "first": fr, "last": lr, "video": vr})
    fp_shots = sum(e["first"]["shots"] for e in eps)
    fp = (sum((e["first"]["first_pass"] or 0) * e["first"]["shots"] for e in eps) / fp_shots) if fp_shots else None
    ch = (root / "docs/master/CHANNEL.md")
    bugs = owner_bugs(ch.read_text(encoding="utf-8", errors="replace") if ch.is_file() else "", now)
    sc = open_selfcheck(root)
    started = [e for e in eps if e["minutes"] is not None]
    return {"schema": "nsfs.scorecard/1", "at": jst(now, "%Y-%m-%d %H:%M:%S+09:00"), "run": run, "budget_min": BUDGET_MIN, "episodes": eps,
            "overall": {"full_auto": f"{sum(e['full_auto'] for e in started)}/{len(started)}",
                        "in_budget": f"{sum(e['in_budget'] for e in started)}/{len(started)}",
                        "first_pass": fp, "first_pass_target": FIRST_PASS_TARGET, "idle": idle_lane(root), "idle_target": IDLE_TARGET,
                        "owner_bugs_24h": bugs, "selfcheck_open": [{"id": i.get("id"), "key": i.get("inv_key"), "what": str(i.get("what") or "")[:100]} for i in sc]}}


def summary_line(d: dict) -> str:
    o = d["overall"]
    idle = o["idle"].get("pct")
    return (f"{LINE_TAG}（{d['at'][5:16]}）：全自动 {o['full_auto']} 集 · 50 分钟内 {o['in_budget']} 集 · 首帧一次过 {pct(o['first_pass'])}（目标 70%）"
            f" · 空卡 {pct(idle)}（目标 <5%）· 项目方 24h 撞上 {len(o['owner_bugs_24h'])} 个 · 自查未关 {len(o['selfcheck_open'])} 项"
            f" → {OUT_MD}")


def to_md(d: dict) -> str:
    o = d["overall"]
    L = [f"# “做完”记分卡（{d['at']}，剧 {d['run']}）", "", "> tools/qa/scorecard.py 用活数据现算；目标：全自动、每集 ≤ 50 分钟、首帧一次过 ≥ 70%、空卡 < 5%、项目方不再撞 bug。", "",
         "## 整体", "",
         f"- 全自动（项目方不用动手）：**{o['full_auto']}** 集",
         f"- 50 分钟内做完：**{o['in_budget']}** 集",
         f"- 首帧一次过率：**{pct(o['first_pass'])}**（目标 ≥ 70%）"]
    idle = o["idle"]
    if idle.get("pct") is None:
        L.append(f"- 空卡率：无数据（{idle.get('why')}）")
    else:
        L.append(f"- 空卡率：**{pct(idle['pct'])}**（目标 < 5%；其中有活却空着 {pct(idle['with_work_pct'])}；影子调度同期 {pct(idle['shadow_pct'])}；"
                 f"{idle['lanes']} 道 × {idle['minutes']} 分钟，自 {idle.get('since')}）")
    L.append(f"- 项目方 24 小时撞上的问题：**{len(o['owner_bugs_24h'])}** 个（CHANNEL 尽力识别）")
    L += [f"  - {b}" for b in o["owner_bugs_24h"][:12]]
    L.append(f"- 系统自查未关：**{len(o['selfcheck_open'])}** 项")
    L += [f"  - {x['id']} {x['what']}" for x in o["selfcheck_open"][:12]]
    L += ["", "## 每集", "", "| 集 | 全自动 | 用时（分钟） | 首帧一次过 | 首帧总过率 | 尾帧一次过 / 总过率 | 视频一次过 / 总过率 | 进度 | 项目方要做的 |",
          "|---|---|---|---|---|---|---|---|---|"]
    for e in d["episodes"]:
        m = "—" if e["minutes"] is None else f"{e['minutes']}（{e['minutes_how']}）{' ✅' if e['in_budget'] else ' ❌' if e['minutes'] > BUDGET_MIN else ''}"
        L.append(f"| ep{e['ep']:02d} | {'是' if e['full_auto'] else '否'} | {m} | {pct(e['first']['first_pass'])}（{e['first']['shots']} 镜{'，全程' if e.get('window') == '全程' else ''}） | "
                 f"{pct(e['first']['pass'])}（{e['first']['takes']} 版） | {pct(e['last']['first_pass'])} / {pct(e['last']['pass'])} | "
                 f"{pct(e['video']['first_pass'])} / {pct(e['video']['pass'])}（{e['video']['renders']} 条） | "
                 f"首 {e['first_done']}/{e['total']} 尾 {e['last_done']}/{e['total']} 视频 {e['video_done']}/{e['total']}{' 已合成' if e['assembled'] else ''} | "
                 f"{'；'.join(e['owner_needed']) or '—'} |")
    L += ["", "口径：一次过 = 导入后这一镜第一版就过契约（首尾帧 postflight.ok / 视频打分 pass）；用时 = KPI 时钟（kpi_core）到导入后第一次合成，没合成 = 到现在；"
          "全自动 = 导入后没有成人镜触发 / 首尾帧修改 / 挂着的待你看卡。"]
    return "\n".join(L) + "\n"


def _atomic(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name(p.name + f".{os.getpid()}.tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, p)


def put_snapshot_line(md: str, line: str) -> str:
    """snapshot.md 第二行放（替换）记分卡摘要"""
    L = [x for x in md.splitlines() if not x.startswith(LINE_TAG)]
    return "\n".join(L[:1] + [line] + L[1:]) + "\n"


def write(d: dict, root: Path = ROOT) -> None:
    _atomic(root / OUT_MD, to_md(d))
    _atomic(root / OUT_JSON, json.dumps({**d, "line": summary_line(d)}, ensure_ascii=False, indent=1))
    sp = root / SNAP_MD
    if sp.is_file():
        _atomic(sp, put_snapshot_line(sp.read_text(encoding="utf-8"), summary_line(d)))


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="“做完”记分卡（活数据）")
    ap.add_argument("--run", default="")
    ap.add_argument("--no-write", action="store_true")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    d = compute(ROOT, a.run or None)
    if not a.no_write:
        write(d)
    print(json.dumps(d, ensure_ascii=False, indent=1) if a.json else to_md(d))
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
