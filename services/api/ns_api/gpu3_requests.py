"""
「请 gpu3 重出」的请求进度（docs/canvas.md §2–§3）：画布按镜头看每条请求的状态。

GET /api/gpu3/requests?shots=ep01-S1,ep01-S2[&limit=20]
  → [{id, shot, stage, state, at, requested_at, error, takes, source: "bridge"|"mirror"}]   新→旧，每镜最多 limit 条
  state ∈ queued | started | image_done | video_done | done | failed | skipped | cancelled
来源：桥可达 → GET /api/gpu3/queue（≤5 s；桥把 started/image_done/video_done 合成 rendering，这里按产出的 take 还原）；
     桥不可达 → 读镜像 renders_gpu3/rerender_queue.jsonl + rerender_events.jsonl（逐行事件，原样状态）。
只读，不写任何队列文件。
"""
from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from pathlib import Path

from fastapi import APIRouter

from ns_api import project_ctx as PJC
from ns_api import readiness as RD

router = APIRouter()
TIMEOUT_S = 5.0
_SHOT = re.compile(r"^ep(\d+)-S(\d+)$", re.I)


def norm_shot(s: str) -> str:
    m = _SHOT.match(s.strip())
    return f"ep{int(m.group(1)):02d}-S{int(m.group(2))}" if m else s.strip()


def _jsonl(p: Path) -> list[dict]:
    out = []
    try:
        for ln in p.read_text(encoding="utf-8").splitlines():
            try:
                x = json.loads(ln)
                if isinstance(x, dict):
                    out.append(x)
            except ValueError:
                continue
    except OSError:
        pass
    return out


def from_mirror(root: Path, project: str) -> list[dict]:
    """镜像里的队列 + 事件 → 每条请求最新状态（事件原样，不合并成 rendering）"""
    reqs: dict[str, dict] = {}
    for q in _jsonl(root / "rerender_queue.jsonl"):
        if q.get("op") == "cancel":
            t = reqs.get(q.get("target_id"))
            if t and t["state"] == "queued":
                t["state"], t["at"] = "cancelled", q.get("at")
            continue
        if q.get("id") and (q.get("project") or PJC.DEFAULT_SLUG) == project:
            reqs[q["id"]] = {"id": q["id"], "shot": norm_shot(str(q.get("shot", ""))), "stage": q.get("stage"),
                             "state": "queued", "at": q.get("at"), "requested_at": q.get("at"), "error": None,
                             "takes": []}
    for e in _jsonl(root / "rerender_events.jsonl"):
        t = reqs.get(e.get("id"))
        if not t or t["state"] == "cancelled":
            continue
        if e.get("take"):
            t["takes"].append(e["take"])
        st = e.get("state") or t["state"]
        st = _unfold("rendering", t["takes"]) if st == "running" else st   # 封板修复：runner 写 running
        t["state"], t["at"], t["error"] = st, e.get("at"), e.get("error")
    return list(reqs.values())


def _unfold(state: str | None, takes: list) -> str | None:
    """桥的 rendering（或 runner 原样的 running）→ started / image_done / video_done（按已产出的 take）"""
    if state not in ("rendering", "running"):
        return state
    stages = {(t or {}).get("stage") for t in takes or []}
    return "video_done" if "video" in stages else "image_done" if "image" in stages else "started"


def from_bridge(limit: int = 500) -> list[dict]:
    if RD.bridge_down():
        raise urllib.error.URLError("gpu3 桥刚才不可达")
    try:
        with urllib.request.urlopen(f"{RD.BRIDGE_URL}/api/gpu3/queue?limit={limit}", timeout=TIMEOUT_S) as r:
            items = json.loads(r.read().decode("utf-8") or "[]")
    except urllib.error.HTTPError:
        RD.mark_bridge(True)
        raise
    except (urllib.error.URLError, OSError):
        RD.mark_bridge(False)
        raise
    RD.mark_bridge(True)
    return [{"id": x.get("id"), "shot": norm_shot(str(x.get("shot", ""))), "stage": x.get("stage"),
             "state": _unfold(x.get("state"), x.get("takes")), "at": x.get("updated_at") or x.get("requested_at"),
             "requested_at": x.get("requested_at"), "error": x.get("error"), "takes": x.get("takes") or []}
            for x in items if isinstance(x, dict)]


@router.get("/api/gpu3/requests")
def requests(shots: str = "", limit: int = 20):
    want = {norm_shot(s) for s in shots.split(",") if s.strip()}
    try:
        items, source = from_bridge(), "bridge"
    except (urllib.error.URLError, OSError, ValueError):
        items = from_mirror(RD.gpu3_root(PJC.DEFAULT_SLUG), RD.current_slug())
        source = "mirror"
    if want:
        items = [x for x in items if x["shot"] in want]
    items.sort(key=lambda x: x.get("requested_at") or x.get("at") or "", reverse=True)
    # 每镜最多 limit 条
    seen: dict[str, int] = {}
    out = []
    for x in items:
        seen[x["shot"]] = seen.get(x["shot"], 0) + 1
        if seen[x["shot"]] <= max(1, limit):
            out.append({**x, "source": source})
    return out
