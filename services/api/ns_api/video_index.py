"""“视频”页的索引（NAVIA；顶栏“视频”tab 的圆点也读 summary）。

GET /api/videos/overview?ep=&state=
  → {summary:{total, final, rendering, queued, pending_review, need_frames, todo, failed, eta_all, median_s},
     episodes:[{ep, shots:[{id, index, state, video_url, n, progress, queue_pos, eta, missing[], candidates}]}]}
state：rendering 出视频中 | queued 排队 | pending_review 待你看（含被打回待改）| final 已定稿（review.json passed）
       | need_frames 缺首 / 尾帧 | todo 帧齐了还没出视频 | failed 最近一次视频任务失败且没有视频
预计时间（后端算，前端只显示）：每条视频的耗时 = 同类已完成视频任务最近 ETA_SAMPLES 次 wall_s 中位数（jobs._done_jobs，含盘上历史），
  没样本用 jobs.ETA_DEFAULT_S["video"]；rendering 的 eta = started_at + max(job.eta_s, median)；
  queued 的 eta = 本道在跑那条的预计结束 + median × 排队序号。读的是同一份任务表（jobs.all_jobs），不另连任何机器。
只读：不写任何文件。
"""
from __future__ import annotations

import json
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

router = APIRouter(tags=["videos-overview"])
STATES = ("rendering", "queued", "pending_review", "final", "need_frames", "todo", "failed")


def _url(rel: str | None) -> str | None:
    from ns_api import v1_guard
    from ns_render import pipeline as _P
    rel = v1_guard.scoped(rel, data_dir=_P.DATA)   # V1 的文件不给 V2 页面（L-126）
    if not rel:
        return None
    r = rel.replace("\\", "/")
    return "/files/" + (r[5:] if r.startswith("data/") else r.lstrip("/"))


def _ts(s) -> float | None:
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
        if d.tzinfo is None:
            d = d.astimezone()
        return d.timestamp()
    except ValueError:
        return None


def _iso(t: float) -> str:
    return datetime.fromtimestamp(t, tz=timezone.utc).astimezone().isoformat(timespec="seconds")


def _video_jobs() -> list[dict]:
    from ns_api import jobs as J
    try:
        allj = J.all_jobs()
    except Exception:  # noqa: BLE001  # arch-ok: 任务表读不到：只是不显示生成状态，状态仍按文件算
        return []
    return [j for j in allj if j.get("shot_id") and (j.get("kind") == "video" or j.get("stage") == "video")]


def _median_s() -> float:
    from ns_api import jobs as J
    try:
        ds = [float(j["wall_s"]) for j in J._done_jobs() if j.get("kind") == "video"][: J.ETA_SAMPLES]
    except Exception:  # noqa: BLE001  # arch-ok: 没有历史样本就用默认耗时，预计时间标为估计
        ds = []
    return float(statistics.median(ds)) if ds else float(J.ETA_DEFAULT_S["video"])


def build(ep: int | None = None, state: str | None = None, *, renders: Path | None = None, now: float | None = None,
          jobs: list[dict] | None = None, median_s: float | None = None) -> dict:
    from ns_render import pipeline as P
    from ns_api import shot_status as SS
    base = renders or P.RENDERS
    now = now if now is not None else time.time()
    vj = _video_jobs() if jobs is None else jobs
    per = median_s if median_s is not None else _median_s()
    live = [j for j in vj if j.get("state") in ("queued", "running")]
    # 每条道的预计：在跑的结束时间 + 排队序号 × per
    eta: dict[str, tuple[str, float | None, int]] = {}   # job id → (state, eta_ts, queue_pos)
    lanes: dict[str, list[dict]] = {}
    for j in live:
        lanes.setdefault(str(j.get("gpu")), []).append(j)
    for js in lanes.values():
        run_end = now
        for j in (x for x in js if x["state"] == "running"):
            st = _ts(j.get("started_at")) or now
            end = st + max(float(j.get("eta_s") or 0), per)
            eta[str(j.get("job_id") or j.get("id"))] = ("running", max(end, now + 5), 0)
            run_end = max(run_end, end)
        qs = sorted((x for x in js if x["state"] == "queued"), key=lambda x: str(x.get("created_at")))
        for i, j in enumerate(qs, 1):
            eta[str(j.get("job_id") or j.get("id"))] = ("queued", run_end + per * i, i)
    by_shot: dict[str, dict] = {}
    for j in sorted(live, key=lambda x: (x["state"] != "running", str(x.get("created_at")))):
        by_shot.setdefault(j["shot_id"], j)
    last_fail: dict[str, dict] = {}
    for j in sorted(vj, key=lambda x: str(x.get("created_at"))):
        if j.get("state") in ("failed", "error"):
            last_fail[j["shot_id"]] = j
        elif j.get("state") == "done":
            last_fail.pop(j["shot_id"], None)
    eps: dict[int, list[dict]] = {}
    summ = {"total": 0, "final": 0, "rendering": 0, "queued": 0, "pending_review": 0, "need_frames": 0, "todo": 0, "failed": 0}
    all_eta: list[float] = []
    for d in sorted(base.glob("ep*/S*")):
        m, s = re.fullmatch(r"ep(\d+)", d.parent.name), re.fullmatch(r"S(\d+)", d.name)
        if not (m and s and (d / "takes.json").is_file()):
            continue
        n_ep, idx = int(m.group(1)), int(s.group(1))
        if ep is not None and n_ep != ep:
            continue
        try:
            takes = json.loads((d / "takes.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):  # arch-ok: 单镜 takes.json 读不到只跳过这一镜，不影响其它镜；总数里少一镜可见
            continue
        sid = f"ep{n_ep:02d}-S{idx}"
        act = takes.get("active") or {}
        vids = [t for t in takes.get("takes") or [] if t.get("stage") == "video" and not t.get("quarantined") and not t.get("void")]
        cur = next((t for t in vids if t.get("n") == act.get("video")), None)
        missing = [k for k, st in (("first", "image"), ("last", "last")) if act.get(st) is None]
        job = by_shot.get(sid)
        row = {"id": sid, "index": idx, "state": "todo", "video_url": _url(cur.get("file")) if cur else None,
               "n": act.get("video") if cur else None, "progress": None, "queue_pos": None, "eta": None, "missing": [], "candidates": len(vids)}
        if job:
            e = eta.get(str(job.get("job_id") or job.get("id")))
            row["state"] = "rendering" if job["state"] == "running" else "queued"
            if e:
                row["eta"], row["queue_pos"] = _iso(e[1]), (e[2] or None)
                all_eta.append(e[1])
                if job["state"] == "running":
                    st = _ts(job.get("started_at")) or now
                    row["progress"] = round(max(0.0, min(0.95, (now - st) / max(e[1] - st, 1))), 2)
        elif missing and not cur:
            row["state"], row["missing"] = "need_frames", missing
        elif cur:
            try:
                rv = SS._reviewed(sid, takes)
            except Exception:  # noqa: BLE001  # arch-ok: 审核结论读不到按“待你看”处理（保守，不会误判已定稿）
                rv = None
            row["state"] = "final" if rv == "passed" else "pending_review"
        elif sid in last_fail:
            row["state"] = "failed"
        if state and row["state"] != state:
            continue
        summ["total"] += 1
        summ[row["state"]] += 1
        eps.setdefault(n_ep, []).append(row)
    for rows in eps.values():
        rows.sort(key=lambda r: r["index"])
    summ["eta_all"] = _iso(max(all_eta)) if all_eta else None
    summ["median_s"] = round(per, 1)
    return {"summary": summ, "episodes": [{"ep": n, "shots": rows} for n, rows in sorted(eps.items())]}


@router.get("/api/videos/overview")
def videos_overview(ep: int | None = None, state: str | None = None):
    if state and state not in STATES:
        raise HTTPException(422, f"state 只能是 {' | '.join(STATES)}")
    return build(ep, state)
