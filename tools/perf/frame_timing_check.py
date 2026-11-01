"""IMGPERF（11-01）：出图任务时长检查——frame 任务墙钟 ≤ 2 × GPU 执行时间（K-OPS-P01）。

读 data/jobs/v1/*.json 里带 timing（ns_api.jobs.progress / _close_timing 写的）的 done frame 任务，
total_s > RATIO × gpu_s + SLACK_S 的列为违规，并给出最慢的阶段。没有 timing 的旧任务不算（记“未测”数）。

  .venv/Scripts/python.exe tools/perf/frame_timing_check.py [--last 50] [--json]
退出码：0 = 全部达标；1 = 有违规；2 = 一个带 timing 的任务都没有（未测 ≠ 通过）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RATIO = 2.0
SLACK_S = 5.0


def check(jobs: list[dict], ratio: float = RATIO, slack: float = SLACK_S) -> dict:
    measured, bad, untested = [], [], 0
    for j in jobs:
        if j.get("kind") != "frame" or j.get("state") != "done":
            continue
        tm = j.get("timing") or {}
        gpu, total = tm.get("gpu_s"), tm.get("total_s") or j.get("wall_s")
        if not gpu or not total:
            untested += 1
            continue
        row = {"id": j.get("id"), "shot_id": j.get("shot_id"), "gpu": j.get("gpu"), "total_s": total, "gpu_s": gpu,
               "ratio": round(total / gpu, 2)}
        st = tm.get("stages") or []
        if st:
            worst = max(st, key=lambda s: s.get("s") or 0)
            row["slowest"] = f"{worst.get('stage')} {worst.get('s')} s"
        measured.append(row)
        if total > ratio * gpu + slack:
            bad.append(row)
    return {"measured": len(measured), "untested": untested, "violations": bad, "rows": measured}


def load(last: int) -> list[dict]:
    d = ROOT / "data" / "jobs" / "v1"
    files = sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime)[-last:] if d.is_dir() else []
    out = []
    for f in files:
        try:
            out.append(json.loads(f.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass
    return out


# ---------------------------------------------------------------- 其他出图执行方（总调度 11-01：今晚真正出图的是它们）
# 两家都没记 GPU 执行秒数（ComfyUI execution_start→success），只记了 client.run 的秒数（投图→完成，含 ComfyUI 排队）。
# 这里把它当 GPU 时间的上界用：比值 = 墙钟 / comfy_s 只会偏小（偏乐观）；gpu_s 字段为 None，并在 notes 里写明。
PRODUCER_LOG = ROOT / "data" / "producer" / "log.jsonl"
ASSET_LOG = ROOT / "data" / "assetmaster" / "frames_v2" / "frames_v2.log"
ASSET_STATE = ROOT / "data" / "assetmaster" / "frames_v2" / "state.json"
TERMINAL = ("passed", "content_fail", "content_error", "failed", "best_effort", "infra_error")


def from_producer(lines: list[dict]) -> list[dict]:
    """PRODUCER log.jsonl：dispatch(obj, lane, attempt, t) → rendered(secs, t) → passed / content_fail / content_error(t)。
    一次尝试的墙钟 = dispatch → 终态（没有终态时到 rendered）；出图段 = dispatch → rendered；契约段 = rendered → 终态"""
    open_: dict = {}
    out = []
    for e in lines:
        ev, obj = e.get("ev"), e.get("obj")
        if ev == "dispatch" and obj:
            if obj in open_:
                out.append(open_.pop(obj))
            open_[obj] = {"source": "producer", "id": f"{obj}#{e.get('attempt')}", "shot_id": obj, "gpu": e.get("lane"),
                          "t0": e.get("t"), "comfy_s": None, "render_s": None, "contract_s": None, "total_s": None,
                          "gpu_s": None, "end": None}
        elif obj in open_ and ev == "rendered":
            r = open_[obj]
            r["comfy_s"], r["render_s"], r["t_r"] = e.get("secs"), round(e["t"] - r["t0"], 1), e["t"]
            r["gpu_s"] = e.get("gpu_s") or r["gpu_s"]          # PRODUCER 04:00 起记 gpu_s（ns_api.jobs.gpu_seconds）
        elif obj in open_ and ev in TERMINAL:
            r = open_.pop(obj)
            r["end"] = ev
            r["total_s"] = round(e["t"] - r["t0"], 1)
            if r.get("t_r"):
                r["contract_s"] = round(e["t"] - r["t_r"], 1)
            for k in ("gpu_s", "contract_s"):
                if e.get(k) is not None:
                    r[k] = e[k]
            out.append(r)
    out += list(open_.values())
    for r in out:
        r.pop("t_r", None)
        r["total_s"] = r["total_s"] or r["render_s"]
        # PRODUCER 04:00 起契约在道放出之后算（不占卡）→ K-OPS-P01 判“占道时长”= dispatch→rendered；契约另报
        if r.get("gpu_s") and r.get("render_s"):
            r["lane_s"] = r["render_s"]
    return out


def from_assetmaster(log_text: str, state: dict) -> list[dict]:
    """ASSETMASTER frames_v2：log 行 “HH:MM:SS stage shot seed N lane 通过/不过 [...]” 是每次尝试的结束时刻；
    state.json 每次尝试有 secs（client.run）。同一条道上相邻两次结束的间隔 = 这次尝试的墙钟（该道上它串行跑）"""
    import re
    secs, full = {}, {}
    for sid, v in (state or {}).items():
        for st, o in (v or {}).items():
            for a in (o or {}).get("attempts", []) if isinstance(o, dict) else []:
                k = (sid, st, str(a.get("seed")), a.get("lane"))
                secs[k] = a.get("secs")
                full[k] = a
    rows, last_on_lane, run_start, day = [], {}, None, 0
    for ln in log_text.splitlines():
        s = re.match(r"^(\d\d):(\d\d):(\d\d) jobs \d+ ", ln)      # 每次启动一批（“jobs N preflight …”）= 新一轮：道的起点重置为启动时刻
        if s:
            t = int(s.group(1)) * 3600 + int(s.group(2)) * 60 + int(s.group(3))
            run_start, last_on_lane = t, {}
            continue
        m = re.match(r"^(\d\d):(\d\d):(\d\d) (\w+) (ep\d+-S\d+) seed (\d+) (\S+) (通过|不过)", ln)
        if not m:
            continue
        hh, mm, ss, st, sid, seed, lane, res = m.groups()
        t = int(hh) * 3600 + int(mm) * 60 + int(ss)
        prev = last_on_lane.get(lane, run_start)
        if prev is not None and t < prev and prev - t > 43200:
            t += 86400
        last_on_lane[lane] = t
        a = full.get((sid, st, seed, lane)) or {}
        row = {"source": "assetmaster", "id": f"{sid}/{st}/{seed}", "shot_id": sid, "gpu": lane, "end": res,
               "comfy_s": secs.get((sid, st, seed, lane)), "gpu_s": a.get("gpu_s"), "score_s": a.get("score_s"),
               "total_s": round(t - prev, 1) if prev is not None and 0 < t - prev < 3600 else None, "timed": False}
        # ASSETMASTER run9 起每次尝试自带 started_at / finished_at / gpu_s / score_s → 用实测，不再用相邻间隔估
        d = _span(a.get("started_at"), a.get("finished_at"))
        if d is not None:
            row.update(total_s=d, timed=True, render_s=_span(a.get("started_at"), a.get("rendered_at")))
        rows.append(row)
        full.pop((sid, st, seed, lane), None)
    # 日志里还没写到（或写法对不上）的、自带计时的尝试也算进来
    for (sid, st, seed, lane), a in full.items():
        d = _span(a.get("started_at"), a.get("finished_at"))
        if d is None:
            continue
        rows.append({"source": "assetmaster", "id": f"{sid}/{st}/{seed}", "shot_id": sid, "gpu": lane, "end": a.get("status"),
                     "comfy_s": a.get("secs"), "gpu_s": a.get("gpu_s"), "score_s": a.get("score_s"), "total_s": d,
                     "render_s": _span(a.get("started_at"), a.get("rendered_at")), "timed": True})
    return rows


def _span(a, b):
    from datetime import datetime
    if a is None or b is None:
        return None
    try:
        if isinstance(a, (int, float)) and isinstance(b, (int, float)):
            return round(float(b) - float(a), 1)
        return round((datetime.fromisoformat(str(b)) - datetime.fromisoformat(str(a))).total_seconds(), 1)
    except (TypeError, ValueError):
        return None


def check_runner(rows: list[dict], ratio: float = RATIO, slack: float = SLACK_S) -> dict:
    """墙钟 ≤ ratio × GPU（GPU 没记 → 用 comfy_s 作上界并标 proxy）；另统计每条道的尝试数（分散度）"""
    import statistics
    lanes: dict = {}
    measured, bad, cached = [], [], 0
    for r in rows:
        lanes[r.get("gpu")] = lanes.get(r.get("gpu"), 0) + 1
        if r.get("gpu_s") == 0:      # ComfyUI 整图命中缓存（同图同种子重投），GPU 没干活 → 不算 K-OPS-P01 样本，单独计数
            cached += 1
            continue
        g = r.get("gpu_s") or r.get("comfy_s")
        w = r.get("lane_s") or r.get("total_s")
        if not g or not w:
            continue
        row = {**r, "ratio": round(w / g, 2), "proxy": r.get("gpu_s") is None}
        measured.append(row)
        if w > ratio * g + slack:
            bad.append(row)
    tot = [r["total_s"] for r in measured]
    gs = [r.get("gpu_s") or r.get("comfy_s") for r in measured]
    n = sum(lanes.values()) or 1
    return {"attempts": len(rows), "measured": len(measured), "violations": bad, "lanes": lanes, "cache_hits": cached,
            "max_lane_share": round(max(lanes.values()) / n, 2) if lanes else None,
            "median_total_s": statistics.median(tot) if tot else None,
            "median_gpu_or_comfy_s": statistics.median(gs) if gs else None,
            "gpu_logged": any(r.get("gpu_s") for r in rows)}


def load_runner(source: str) -> list[dict]:
    if source == "producer":
        lines = []
        if PRODUCER_LOG.is_file():
            for ln in PRODUCER_LOG.read_text(encoding="utf-8").splitlines():
                try:
                    lines.append(json.loads(ln))
                except ValueError:
                    pass
        return from_producer(lines)
    if source == "assetmaster":
        txt = ASSET_LOG.read_text(encoding="utf-8") if ASSET_LOG.is_file() else ""
        try:
            st = json.loads(ASSET_STATE.read_text(encoding="utf-8")) if ASSET_STATE.is_file() else {}
        except ValueError:
            st = {}
        return from_assetmaster(txt, st)
    raise ValueError(source)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--last", type=int, default=50)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--source", default="ns_api", choices=("ns_api", "producer", "assetmaster", "all"),
                    help="ns_api = data/jobs/v1；producer = data/producer/log.jsonl；assetmaster = frames_v2 日志 + state")
    a = ap.parse_args(argv)
    try:   # 重定向到文件时 Windows 默认 cp1252，中文会炸
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    srcs = ("ns_api", "producer", "assetmaster") if a.source == "all" else (a.source,)
    report, rc = {}, 0
    for s in srcs:
        if s == "ns_api":
            r = check(load(a.last))
            report[s] = r
            if not a.json:
                print(f"[ns_api] 带 timing 的 frame 任务 {r['measured']} 个，未测 {r['untested']} 个，违规 {len(r['violations'])} 个")
                for v in r["violations"]:
                    print(f"  {v['id']} {v['shot_id']} 道 {v['gpu']}：墙钟 {v['total_s']} s / GPU {v['gpu_s']} s = {v['ratio']}×，最慢 {v.get('slowest')}")
            rc = max(rc, 1 if r["violations"] else (0 if r["measured"] else 2))
            continue
        r = check_runner(load_runner(s))
        report[s] = r
        if not a.json:
            print(f"[{s}] 尝试 {r['attempts']} 次，可测 {r['measured']} 次，违规 {len(r['violations'])} 次；"
                  f"墙钟中位 {r['median_total_s']} s / {'GPU' if r['gpu_logged'] else 'ComfyUI（GPU 未记，作上界）'} 中位 "
                  f"{r['median_gpu_or_comfy_s']} s；各道 {r['lanes']}（最大占比 {r['max_lane_share']}）")
            for v in r["violations"][:10]:
                print(f"  {v['id']} 道 {v['gpu']}：墙钟 {v['total_s']} s / {v.get('gpu_s') or v.get('comfy_s')} s = {v['ratio']}×"
                      + (f"（出图 {v.get('render_s')} s，契约 {v.get('contract_s')} s）" if v.get("contract_s") is not None else ""))
        rc = max(rc, 1 if r["violations"] else (0 if r["measured"] else 2))
    if a.json:
        print(json.dumps(report, ensure_ascii=False, indent=1, default=str))
    return rc


if __name__ == "__main__":
    sys.exit(main())
