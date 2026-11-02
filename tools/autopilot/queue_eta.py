"""排队位置与预计完成时间（总调度 11-02 17:1x：项目方要求界面上每一条修改都看到“排在第几、预计几点完成”；DEBUG-RSI 出后端，ASSETUX 接前端）。

只读已同步到笔记本的状态，不新开 ssh：
  首帧 / 尾帧  data/producer/registry.json（status ready / running；排序同 producer 派单 K-OPS-E30 episode_order_key）
  视频         data/pipeline/runs/<主剧>/video/state_<host>.json + jobs.json（按 集 → 镜，vidgen pending 同口径）
  道数         data/state/netfix/partition.json 的 lanes（出图道 = images 有集的主机的道；视频道 = video 有集的主机的道）
  时长         历史中位数：首帧 / 尾帧每次尝试 data/_offline_pull/*/data/producer/log.jsonl 的 render_s + contract_s；
               视频每版 state 里 t_done − t_sub；视频每镜按平均出片版数（已定的镜）放大
预计完成 = 现在 + ⌈(前面的单数 + 1) / 可用道数⌉ × 每单中位时长（running 的按已用时间扣掉）。

  .venv/Scripts/python.exe tools/autopilot/queue_eta.py            # 写 data/autopilot/queue_eta.json 并打印摘要
接口（给 ASSETUX）：compute(root) → {"generated_at", "basis": {...}, "objects": {对象 id: {status, pos, ahead, ahead_n, eta, eta_s, pool}}}
对象 id：first:epNN-SN / last:epNN-SN / video:epNN-SN；pos = 0 表示正在出
"""
from __future__ import annotations

import glob
import json
import math
import statistics
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "autopilot" / "queue_eta.json"
FRAME_DEFAULT_S, VIDEO_DEFAULT_S, VIDEO_SCORE_S = 112.0, 751.0, 80.0


def _jl(p: Path, d=None):
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return d


def _primary(root: Path) -> str:
    sys.path.insert(0, str(root / "tools" / "autopilot"))
    import runs as RUNS
    return RUNS.primary_run(root)


def frame_median_s(root: Path) -> float:
    xs = []
    for f in glob.glob(str(root / "data/_offline_pull/*/data/producer/log.jsonl")):
        with open(f, encoding="utf-8", errors="replace") as fh:
            for ln in fh:
                if '"render_s"' not in ln:
                    continue
                try:
                    d = json.loads(ln)
                except ValueError:   # arch-ok: 日志里半行（拉取截断）跳过，只影响样本数
                    continue
                if d.get("ev") in ("passed", "content_fail", "redo_fail") and d.get("render_s"):
                    xs.append(float(d["render_s"]) + float(d.get("contract_s") or 0))
    return statistics.median(xs) if len(xs) >= 20 else FRAME_DEFAULT_S


def video_stats(states: dict) -> tuple[float, float]:
    """→ (每版中位秒数, 已定的镜平均出片版数)"""
    dur, per = [], []
    for st in states.values():
        for rec in (st.get("shots") or {}).values():
            rs = rec.get("renders") or []
            dur += [x["t_done"] - x["t_sub"] for x in rs if x.get("t_done") and x.get("t_sub")]
            if rec.get("status") in ("done", "best_effort") and rs:
                per.append(len(rs))
    return (statistics.median(dur) if len(dur) >= 10 else VIDEO_DEFAULT_S), (statistics.mean(per) if per else 1.7)


STALE_S = 15 * 60


def pick_registry(root: Path, part: dict, now: float) -> tuple[dict, str, bool]:
    """出图主机的 registry（puller 拉回 data/_offline_pull/<host>/data/producer/registry.json）优先；超过 15 分钟没更新
    → 退回笔记本 data/producer/registry.json（笔记本按本地 takes 副本推导，和服务器实况可能不同），并标 stale"""
    best = None
    for h, eps in (part.get("images") or {}).items():
        if not eps or h == "laptop":
            continue
        p = root / "data/_offline_pull" / h / "data/producer/registry.json"
        if p.exists() and now - p.stat().st_mtime < STALE_S:
            d = _jl(p, {}) or {}
            if best is None or str(d.get("updated")) > str(best[0].get("updated")):
                best = (d, str(p.relative_to(root)))
    if best:
        return best[0], best[1], False
    return _jl(root / "data/producer/registry.json", {}) or {}, "data/producer/registry.json（笔记本推导，非服务器实况）", True


def episode_order_key(c: tuple) -> tuple:
    """和 producer.episode_order_key 同一口径（K-OPS-E30）：(集, 驳回优先, 尾帧先, 镜序)"""
    ep, k, idx, o = c
    return (ep, 0 if o.get("redo") else 1, k, idx)


def _eta(pos: int, lanes: int, per_s: float, now: float, running_since: float | None = None) -> float:
    if pos == 0:
        used = max(0.0, now - running_since) if running_since else 0.0
        return now + max(30.0, per_s - used)
    return now + math.ceil((pos + 1) / max(1, lanes)) * per_s


def compute(root: Path = ROOT, now: float | None = None) -> dict:
    now = now or time.time()
    run = _primary(root)
    part = _jl(root / "data/state/netfix/partition.json", {}) or {}
    reg, reg_src, stale = pick_registry(root, part, now)
    lanes = part.get("lanes") or {}
    img_hosts = [h for h, eps in (part.get("images") or {}).items() if eps and h != "laptop"]
    vid_hosts = [h for h, eps in (part.get("video") or {}).items() if eps]
    retired = set(part.get("retired_lanes") or [])
    n_img = sum(1 for h in img_hosts for ln in lanes.get(h) or [] if ln not in retired) or 1
    vdir = root / "data/pipeline/runs" / run / "video"
    states = {h: _jl(vdir / f"state_{h}.json", {}) or {} for h in vid_hosts}
    jobs = {m["shot"]: m for m in (_jl(vdir / "jobs.json", {}) or {}).get("shots") or []}
    f_s = frame_median_s(root)
    v_s, v_per = video_stats(states)
    v_shot_s = v_per * (v_s + VIDEO_SCORE_S)
    out: dict = {}
    # 首帧 / 尾帧
    running, cands = [], []
    for E in reg.get("episodes") or []:
        for S in E.get("shots") or []:
            for k in ("last", "first"):
                o = (S.get("objects") or {}).get(k) or {}
                if o.get("status") == "running":
                    running.append(o)
                elif o.get("status") == "ready":
                    cands.append((E.get("ep") or 99, 0 if k == "last" else 1, S.get("index") or 99, o))
    cands.sort(key=episode_order_key)
    for o in running:
        out[o["id"]] = {"status": "running", "pos": 0, "ahead": [], "ahead_n": 0, "pool": "frames",
                        "eta_s": round(_eta(0, n_img, f_s, now, o.get("since")))}
    for i, (_e, _k, _x, o) in enumerate(cands):
        pos = i + 1
        ahead = [c[3]["id"] for c in cands[max(0, i - 10):i]]
        out[o["id"]] = {"status": "ready", "pos": pos, "ahead": ahead, "ahead_n": i + len(running), "pool": "frames",
                        "eta_s": round(_eta(pos + len(running), n_img, f_s, now))}
    # 视频（按主机分池：帧和视频在同一台，K-OPS-E30）
    for h, st in states.items():
        n_v = sum(1 for ln in lanes.get(h) or [] if ln not in retired) or 1
        rows = []
        for sid, rec in (st.get("shots") or {}).items():
            if (jobs.get(sid) or {}).get("host") not in (None, h):
                continue
            s = rec.get("status")
            if s in ("done", "best_effort", "blocked"):
                continue
            busy = any(x.get("state") in ("submitted", "fetched", "scoring") for x in rec.get("renders") or [])
            rows.append((int(sid[2:4]), int(sid.rsplit("S", 1)[-1]), sid, s, busy, rec))
        rows.sort(key=lambda r: (0 if r[4] else 1, r[0], r[1]))
        q = [r for r in rows if not r[4] and r[3] != "waiting_frame"]
        for r in rows:
            vid = f"video:{r[2]}"
            if r[4]:
                t0 = max([x.get("t_sub") or 0 for x in r[5].get("renders") or []] or [0])
                out[vid] = {"status": "rendering", "pos": 0, "ahead": [], "ahead_n": 0, "pool": f"video@{h}",
                            "eta_s": round(_eta(0, n_v, v_s + VIDEO_SCORE_S, now, t0 or None))}
            elif r[3] == "waiting_frame":
                out[vid] = {"status": "waiting_frame", "pos": None, "ahead": [], "ahead_n": None, "pool": f"video@{h}",
                            "eta_s": None, "waiting_for": "首帧（和尾帧）通过检查后进队"}
            else:
                i = q.index(r)
                nb = sum(1 for x in rows if x[4])
                out[vid] = {"status": r[3] or "pending", "pos": i + 1, "ahead": [f"video:{x[2]}" for x in q[max(0, i - 10):i]],
                            "ahead_n": i + nb, "pool": f"video@{h}", "eta_s": round(_eta(i + 1 + nb, n_v, v_shot_s, now))}
    for v in out.values():
        v["eta"] = time.strftime("%Y-%m-%dT%H:%M", time.localtime(v["eta_s"])) if v.get("eta_s") else None
    return {"generated_at": time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now)), "run": run,
            "basis": {"frame_s_per_try": round(f_s), "video_s_per_render": round(v_s), "video_renders_per_shot": round(v_per, 2),
                      "image_lanes": n_img, "video_hosts": vid_hosts, "registry_updated": reg.get("updated"),
                      "registry_source": reg_src, "stale": stale,
                      "note": "只读已同步到笔记本的状态；首帧 / 尾帧按每次尝试估（重出会顺延），视频按平均出片版数估"},
            "objects": out}


def main() -> int:
    d = compute()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    tmp = OUT.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(OUT)
    objs = d["objects"]
    print(json.dumps({"generated_at": d["generated_at"], "basis": d["basis"], "n": len(objs),
                      "sample": {k: {x: v.get(x) for x in ("status", "pos", "ahead_n", "eta")} for k, v in list(objs.items())[:6]}},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
