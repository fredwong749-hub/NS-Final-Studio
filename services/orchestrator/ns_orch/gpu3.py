"""
gpu3 桥客户端（canvas_api on gpu3，经隧道 ssh -N -L 15180:127.0.0.1:5180 gpu33 → http://127.0.0.1:15180）。

约定（lead 2026-10-30，docs/canvas.md 上线后以其为准）：
  GET  /api/gpu3/projects/{slug}/episodes  → {project, control, eta, episodes:[{ep, frames, videos, qa, audio,
       upscale_4k, final, eta_s, errors[]}]}（docs/canvas.md §7.1）
  POST /api/gpu3/projects/{slug}/series    {action: start|pause|stop, episodes?, by, note, adult_content}（§7.2）
       → 写 data/renders_gpu3/[<slug>/]series_control.json（桥不可达时笔记本直接写同名文件）
  GET  /api/gpu3/gpus                      → [{id, busy_by, task, vram_used_mb, util, lock_file, lend_file}]，GPU 2 标坏卡
slug "weita" = 《为他而骚》（renders_gpu3 下不带 slug 目录）。

桥不可达时一律优雅降级：读笔记本镜像里的 status.json / 文件；series 控制写本地文件。
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from ns_api.project_ctx import REPO, ProjectContext, now, read_json, write_json

BRIDGE_URL = os.environ.get("NS_GPU3_BRIDGE", "http://127.0.0.1:15180")
TIMEOUT = float(os.environ.get("NS_GPU3_TIMEOUT", "2"))
GPU3_KEYS = ("frames", "videos", "qa", "audio", "upscale_4k", "final")


def normalize(v) -> dict:
    """gpu3 状态字段 → {status, done, total}。接受 "done"/"running"/… 、{done,total}、"3/6"、0–1 小数、bool"""
    if v is None:
        return {"status": "pending", "done": 0, "total": 0}
    if isinstance(v, bool):
        return {"status": "done" if v else "pending", "done": int(v), "total": 1}
    if isinstance(v, (int, float)):
        f = float(v)
        return {"status": "done" if f >= 1 else ("running" if f > 0 else "pending"), "done": f, "total": 1}
    if isinstance(v, str):
        if "/" in v:
            a, _, b = v.partition("/")
            try:
                return normalize({"done": int(a), "total": int(b)})
            except ValueError:
                pass
        s = v.lower()
        status = {"ok": "done", "pass": "done", "passed": "done", "complete": "done", "completed": "done",
                  "rendering": "running", "in_progress": "running", "queued": "waiting", "fail": "failed",
                  "error": "failed"}.get(s, s)
        return {"status": status, "done": int(status == "done"), "total": 1}
    if isinstance(v, dict) and "verdict" in v:                 # qa.json（docs/canvas.md §7.4）
        return normalize({"state": v["verdict"]})
    if isinstance(v, dict) and "state" in v and "done" not in v:   # 桥 §7.1：qa / upscale_4k 的 state
        s = str(v.get("state") or "none").lower()
        status = {"pass": "done", "auto_pass": "done", "done": "done", "ok": "done", "complete": "done",
                  "hold": "waiting", "blocked_shots": "waiting", "paused": "waiting", "partial": "running",
                  "running": "running", "fail": "failed", "failed": "failed", "stale": "failed"}.get(s, "pending")
        if status == "pending" and v.get("file"):
            status = "done"
        return {"status": status, "done": int(status == "done"), "total": 1, "issues": v.get("issues") or []}
    if isinstance(v, dict) and ("voiceover" in v or "music" in v):  # 桥 §7.1 audio
        parts = [bool(v.get("voiceover")), bool(v.get("music"))]
        status = "done" if all(parts) else ("running" if any(parts) or v.get("stems_shots") else "pending")
        return {"status": status, "done": sum(parts), "total": 2}
    if isinstance(v, dict) and "exists" in v:                       # 桥 §7.1 final
        return {"status": "done" if v.get("exists") else "pending", "done": int(bool(v.get("exists"))), "total": 1}
    if isinstance(v, dict):
        done, total = v.get("done", 0) or 0, v.get("total", 0) or 0
        status = v.get("status") or ("done" if total and done >= total else "running" if done else "pending")
        if v.get("failed"):
            status = "failed"
        return {"status": status, "done": done, "total": total}
    return {"status": "pending", "done": 0, "total": 0}


class Gpu3Bridge:
    def __init__(self, base_url: str | None = None, timeout: float | None = None):
        self.base = (base_url or BRIDGE_URL).rstrip("/")
        self.timeout = TIMEOUT if timeout is None else timeout

    # ---------------------------------------------------------------- http
    def _get(self, path: str):
        with urllib.request.urlopen(self.base + path, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8"))

    def _post(self, path: str, body: dict):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                                     headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.loads(r.read().decode("utf-8") or "{}")

    def reachable(self) -> bool:
        try:
            self._get("/api/gpu3/health")
            return True
        except (urllib.error.URLError, OSError, ValueError):
            return False

    # ---------------------------------------------------------------- 状态
    def episodes(self, ctx: ProjectContext) -> dict[int, dict]:
        """{ep: {frames, videos, qa, audio, upscale_4k, final, eta_s, errors, source}}；桥优先，镜像兜底"""
        try:
            data = self._get(f"/api/gpu3/projects/{ctx.slug}/episodes")
            rows = data.get("episodes", []) if isinstance(data, dict) else data
            return {int(r["ep"]): {**r, "source": "bridge"} for r in rows}
        except (urllib.error.URLError, OSError, ValueError, KeyError, TypeError):
            return self.local_episodes(ctx)

    @staticmethod
    def local_episodes(ctx: ProjectContext) -> dict[int, dict]:
        out = {}
        for base in ctx.renders_gpu3_dirs:
            if not base.is_dir():
                continue
            for d in sorted(base.glob("ep[0-9]*")):
                if not d.is_dir() or not d.name[2:].isdigit():
                    continue
                n = int(d.name[2:])
                st = read_json(d / "status.json", {})
                if not isinstance(st, dict):
                    st = {}
                shots = [s for s in d.iterdir() if s.is_dir() and s.name.startswith("S")]
                rec = {k: st.get(k) for k in GPU3_KEYS}
                qa = read_json(d / "qa.json", None)          # §7.4 逐集 QA 结论优先
                if isinstance(qa, dict) and qa.get("verdict"):
                    rec["qa"] = qa
                if rec["videos"] is None and shots:      # 没有集状态文件：按文件数推
                    rec["videos"] = {"done": sum((s / "video.mp4").exists() for s in shots), "total": len(shots)}
                if rec["frames"] is None and shots:
                    rec["frames"] = {"done": sum((s / "frame.png").exists() for s in shots), "total": len(shots)}
                if rec["upscale_4k"] is None and shots:
                    k4 = sum(any((s / "takes").glob("video_*_4k.mp4")) for s in shots if (s / "takes").is_dir())
                    if k4:
                        rec["upscale_4k"] = {"done": k4, "total": len(shots)}
                out.setdefault(n, {**rec, "eta_s": st.get("eta_s"), "errors": st.get("errors", []),
                                   "source": "mirror"})
        return out

    def gpus(self) -> dict:
        try:
            return {"reachable": True, "gpus": self._get("/api/gpu3/gpus")}
        except (urllib.error.URLError, OSError, ValueError) as e:
            return {"reachable": False, "gpus": [], "error": f"gpu3 桥不可达（{self.base}）：{str(e)[:120]}"}

    # ---------------------------------------------------------------- 控制
    @staticmethod
    def control_file(ctx: ProjectContext) -> Path:
        base = REPO / "data" / "renders_gpu3"
        return (base / ctx.gpu3_subdir if ctx.gpu3_subdir else base) / "series_control.json"

    def series(self, ctx: ProjectContext, action: str, episodes: list[int] | None, *, adult_content: bool,
               requested_by: str) -> dict:
        note = "T42 编排器"
        # 桥 §7.2 的 adult_content 字段保留；2026-10-30 起 gpu3 不再据此跳过成人镜头
        body = {"action": action, "episodes": episodes, "by": requested_by, "note": note,
                "adult_content": bool(adult_content)}
        try:
            r = self._post(f"/api/gpu3/projects/{ctx.slug}/series", body)
            return {"via": "bridge", "response": r}
        except (urllib.error.URLError, OSError, ValueError) as e:
            p = self.control_file(ctx)
            cur = read_json(p, {})
            eps = sorted(set(cur.get("episodes") or []) | set(episodes or [])) if action == "start" else (episodes or [])
            rec = {"schema": "nsfs_canvas.series_control/v1", "project": ctx.slug, "action": action,
                   "episodes": eps, "by": requested_by, "at": now(), "adult_content": bool(adult_content),
                   "note": f"{note}；桥不可达（{str(e)[:80]}），笔记本直接写文件"}
            write_json(p, rec)
            with (p.parent / "series_control.log.jsonl").open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            return {"via": "file", "file": str(p), "record": rec}


class SimulatedGpu3:
    """dry-run / 测试用：不连网、不写真实 series_control。交接后的集每次 tick 前进一档：
    frames → videos → qa → audio → upscale_4k → final(装配交给笔记本，不在这里)"""
    ORDER = ("frames", "videos", "qa", "audio", "upscale_4k")

    def __init__(self, state: dict):
        self.state = state.setdefault("sim_gpu3", {"started": [], "progress": {}})

    def reachable(self) -> bool:
        return True

    def series(self, ctx, action, episodes, *, adult_content, requested_by):
        if action == "start":
            for e in episodes or []:
                if e not in self.state["started"]:
                    self.state["started"].append(e)
        return {"via": "simulated", "episodes": episodes}

    def advance(self):
        for e in self.state["started"]:
            k = str(e)
            self.state["progress"][k] = min(self.state["progress"].get(k, 0) + 1, len(self.ORDER))

    def episodes(self, ctx) -> dict[int, dict]:
        out = {}
        for e in self.state["started"]:
            p = self.state["progress"].get(str(e), 0)
            out[e] = {k: ("done" if i < p else "running" if i == p else "pending") for i, k in enumerate(self.ORDER)}
            out[e].update(eta_s=(len(self.ORDER) - p) * 600, errors=[], source="simulated")
        return out

    def gpus(self) -> dict:
        return {"reachable": True, "simulated": True, "gpus": [
            {"id": 0, "busy_by": "series", "task": "dry-run", "vram_used_mb": 0, "util": 0},
            {"id": 1, "busy_by": None, "task": None, "vram_used_mb": 0, "util": 0},
            {"id": 2, "faulty": True},
            {"id": 3, "busy_by": None, "task": None, "vram_used_mb": 0, "util": 0}]}
