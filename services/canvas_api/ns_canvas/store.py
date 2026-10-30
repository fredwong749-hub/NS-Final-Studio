"""重渲队列（只追加的 JSONL）与进度事件。单进程内加锁；渲染器在另一进程只读队列、只追加事件。"""
from __future__ import annotations

import os
import threading
import uuid
from pathlib import Path

from .models import RenderEvent, RerenderRequest
from .sources import read_jsonl

_lock = threading.Lock()


def _append(p: Path, line: str):
    p.parent.mkdir(parents=True, exist_ok=True)
    with _lock, p.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
        f.flush()
        os.fsync(f.fileno())


class Queue:
    def __init__(self, queue_dir: Path):
        self.path = queue_dir / "rerender_queue.jsonl"
        self.events_path = queue_dir / "rerender_events.jsonl"

    def submit(self, req: RerenderRequest) -> RerenderRequest:
        if not req.id:
            req.id = uuid.uuid4().hex[:12]
        _append(self.path, req.model_dump_json(by_alias=True))
        return req

    def append_raw(self, rec: dict) -> dict:
        """按集运行的队列项（nsfs_canvas.run_item/v1）：字段由调用方给定，原样追加。"""
        import json
        _append(self.path, json.dumps(rec, ensure_ascii=False))
        return rec

    def cancel(self, req_id: str) -> RerenderRequest:
        st = self.state().get(req_id)
        if not st:
            raise KeyError(req_id)
        if st["state"] != "queued":
            raise ValueError(f"请求 {req_id} 已是 {st['state']}，不能取消")
        q = st["request"]
        return self.submit(RerenderRequest(op="cancel", target_id=req_id, shot=q["shot"], stage=q.get("stage", "both")))

    def event(self, ev: RenderEvent):
        _append(self.events_path, ev.model_dump_json(by_alias=True))

    def state(self) -> dict[str, dict]:
        """请求 id → {request, state(queued/rendering/done/failed/skipped/cancelled), at, error, takes}。"""
        out: dict[str, dict] = {}
        for q in read_jsonl(self.path):
            if q.get("op") == "cancel":
                t = out.get(q.get("target_id"))
                if t and t["state"] == "queued":
                    t["state"], t["at"] = "cancelled", q.get("at")
                continue
            if q.get("id"):
                out[q["id"]] = {"request": q, "state": "queued", "at": q.get("at"), "error": None, "takes": []}
        for e in read_jsonl(self.events_path):
            t = out.get(e.get("id"))
            if not t or t["state"] == "cancelled":
                continue
            s = e.get("state")
            t["state"] = "rendering" if s in ("started", "image_done", "video_done") else s
            t["at"], t["error"] = e.get("at"), e.get("error")
            if e.get("take"):
                t["takes"].append(e["take"])
        return out
