"""提交器：把 RenderPlan 交给 :8800 API（POST /api/shots/{id}/video-jobs），轮询 GET /api/jobs/{id}，取回 take 文件。

- ApiSubmitter：真提交。只提交 plan.api.compatible 的计划（API 能表达的参数）；Ref2VA / 两段式 / 改分辨率等
  需要 API 接入点（plan.api.unsupported 列出），在接入前返回 needs_api，不偷偷绕过 API 直连 ComfyUI。
- DryRunSubmitter：不提交任何真实任务；按计划生成一个假 take（文件不存在），用于 dry-run 和测试。
作业丢失（API 重启，GET 404）：按 seed + 提示词哈希到 /api/shots/{id}/video-takes 里找回已出的 take（chain_audit E6）。
"""
from __future__ import annotations

import hashlib
import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API = "http://127.0.0.1:8800"


def prompt_sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


class SubmitError(Exception):
    pass


class LaneAllocator:
    """6 道：gpu33:0/1/3（API 道 id 0/1/3）、gpu36:0/1（"gpu36:0"/"gpu36:1"）、gpu36:2 只接长镜头。
    每道同时只放 1 个本 loop 的作业（API 每道本来就串行；这样各道均衡）。"""

    def __init__(self, normal=(0, 1, 3, "gpu36:0", "gpu36:1"), long=("gpu36:2",), per_lane: int = 1,
                 lane_cap: int = 2):
        self.normal, self.long, self.per_lane, self.lane_cap = list(normal), list(long), per_lane, lane_cap

    def pick(self, long: bool, busy: dict, external: dict | None = None, only=None) -> object | None:
        """external：每道的总负载（含别的会话 / LAB / CONSIST 的 API 作业和直连 ComfyUI 的队列），
        ≥ lane_cap 的道不再派（V2 2026-10-31：与 LAB/CONSIST 共用 6 道，每道排队 ≤2）。None = 不查（dry-run / 旧行为）"""
        ext = external or {}
        cands = self.long if long else self.normal
        if only:   # 配方 lane.only：只有这些道有权重（例：Ref2VA 只在 gpu33:0/1/3）
            cands = [g for g in cands if str(g) in {str(x) for x in only}]
        free = [g for g in cands if busy.get(str(g), 0) < self.per_lane
                and (external is None or ext.get(str(g), 0) < self.lane_cap)]
        if not free:
            return None
        return min(free, key=lambda g: (busy.get(str(g), 0), ext.get(str(g), 0), cands.index(g)))


def _comfy_urls() -> dict[str, str]:
    """道 id（"0"/"1"/"3"/"gpu36:N"）→ ComfyUI 地址（config/render_endpoints.json gpus / lanes）"""
    try:
        cfg = json.loads((ROOT / "config" / "render_endpoints.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    out = {str(k): v for k, v in (cfg.get("gpus") or {}).items()}
    out.update({str(k): (v or {}).get("url") for k, v in (cfg.get("lanes") or {}).items() if (v or {}).get("url")})
    return out


def lane_load(api_jobs: list[dict], comfy_queues: dict) -> dict[str, int]:
    """每道负载 = ComfyUI 队列（running + pending，含直连提交）+ API 里还没送到 ComfyUI 的 queued 作业。
    ComfyUI 查不到（None）时退回 API 的 queued + running。"""
    api_q, api_r = {}, {}
    for j in api_jobs or []:
        g = str(j.get("gpu"))
        if j.get("state") == "queued":
            api_q[g] = api_q.get(g, 0) + 1
        elif j.get("state") == "running":
            api_r[g] = api_r.get(g, 0) + 1
    out = {}
    for g in set(api_q) | set(api_r) | set(comfy_queues):
        cq = comfy_queues.get(g)
        out[g] = api_q.get(g, 0) + (cq if cq is not None else api_r.get(g, 0))
    return out


class DryRunSubmitter:
    dry = True

    def __init__(self, graph_passthrough: bool = True):
        """graph_passthrough（默认开）：演练时假定 API 已有 recipe_plan.graph 接入点，Ref2VA / 两段式也走通"""
        self.n = 0
        self.jobs: dict[str, dict] = {}
        self.graph_passthrough = graph_passthrough

    def submit(self, plan: dict, lane) -> dict:
        if not plan["api"]["compatible"] and not self.graph_passthrough:
            return {"state": "needs_api", "unsupported": plan["api"]["unsupported"]}
        self.n += 1
        jid = f"dry-{self.n:04d}"
        sid = plan["spec"]["id"]
        ep, s = sid.split("-")
        take = {"take": 900 + self.n, "file": f"renders/{ep}/{s}/takes/DRYRUN_{plan['plan_hash'][:10]}.mp4"}
        body = plan["api"]["body"] | {"gpu": lane,
                                      "recipe_plan": recipe_plan_body(plan, with_graph=not plan["api"]["compatible"])}
        self.jobs[jid] = {"id": jid, "state": "done", "gpu": lane, **take,
                          "request": {"endpoint": plan["api"]["endpoint"], "body": body}}
        return {"state": "queued", "job_id": jid, "lane": lane, "dry_run": True}

    def poll(self, job_id: str, plan: dict | None = None) -> dict:
        j = self.jobs.get(job_id)
        if not j:
            return {"state": "lost"}
        return {"state": "done", "take": j["take"], "file": j["file"], "local_path": str(ROOT / "data" / j["file"])}

    def cancel(self, job_id: str) -> None:
        self.jobs.pop(job_id, None)


def recipe_plan_body(plan: dict, with_graph: bool) -> dict:
    """VideoJobRequest.recipe_plan（ns_api.video_jobs.RecipePlan）：plan_hash / recipe_id 溯源；with_graph = 原样出图"""
    rp = {"plan_hash": plan["plan_hash"], "recipe_id": plan["recipe"]["id"]}
    if with_graph:
        rp["graph"] = plan["graph"]
        rp["images"] = {f"@ref:{s['character']}": s["path"] for s in plan.get("ref_slots") or []
                        if s.get("role") == "identity" and s.get("path")}
        # @look:<角色>（Ref2VA 造型槽，K-REN-303）：与 tools/series10_video/build_jobs.py 同一来源——计划的 outfit 槽
        # （ns_recipes.compiler.look_slots：首帧 contract.asset_refs 的造型，缺了再 asset_refs.resolve_shot）
        rp["images"].update({f"@look:{s['character']}": s["path"] for s in plan.get("ref_slots") or []
                             if s.get("role") == "outfit" and s.get("path")})
    return rp


class ApiSubmitter:
    dry = False

    def __init__(self, base: str = API, timeout: float = 180.0, graph_passthrough: bool = False):
        """graph_passthrough：API 已重启、带 recipe_plan.graph 接入点（ns_api.recipe_render）后打开，
        API 参数表达不了的配方（Ref2VA / 两段式等）按图原样出片；关着时这类计划返回 needs_api"""
        self.base, self.timeout, self.graph_passthrough = base.rstrip("/"), timeout, graph_passthrough

    def _req(self, method: str, path: str, body: dict | None = None) -> tuple[int, dict]:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8") if body is not None else None
        req = urllib.request.Request(self.base + path, data=data, method=method,
                                     headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, json.loads(r.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8") or "{}")
            except ValueError:
                return e.code, {}
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            raise SubmitError(f"API 不可达：{e}") from e

    def submit(self, plan: dict, lane) -> dict:
        compat = plan["api"]["compatible"]
        if not compat and not self.graph_passthrough:
            return {"state": "needs_api", "unsupported": plan["api"]["unsupported"]}
        body = dict(plan["api"]["body"])
        body["gpu"] = lane
        body["recipe_plan"] = recipe_plan_body(plan, with_graph=not compat)
        code, js = self._req("POST", plan["api"]["endpoint"], body)
        if code == 409:
            return {"state": "blocked", "detail": js.get("detail"), "missing": js.get("missing")}
        if code >= 300:
            return {"state": "error", "code": code, "detail": js.get("detail")}
        jid = js.get("id") or js.get("job_id")
        return {"state": "queued", "job_id": jid, "lane": js.get("gpu", lane), "warnings": js.get("warnings")}

    def _recover(self, plan: dict) -> dict | None:
        sid = plan["spec"]["id"]
        code, js = self._req("GET", f"/api/shots/{sid}/video-takes")
        if code != 200:
            return None
        want = prompt_sha(plan["prompt"]["text"])
        for t in js.get("takes", []):
            pr = t.get("params") or {}
            if (pr.get("recipe") or {}).get("plan_hash") == plan["plan_hash"] or pr.get("seed") == plan["seed"] and prompt_sha(t.get("prompt") or pr.get("prompt") or "") == want:
                return {"state": "done", "take": t["n"], "file": t["file"],
                        "local_path": str(ROOT / "data" / t["file"]), "recovered": True}
        return None

    def poll(self, job_id: str, plan: dict | None = None) -> dict:
        code, js = self._req("GET", f"/api/jobs/{job_id}")
        if code == 404:
            rec = self._recover(plan) if plan else None
            return rec or {"state": "lost"}
        st = js.get("state")
        if st == "done":
            res = js.get("result") or js
            n = res.get("take")
            sid = (plan or {}).get("spec", {}).get("id")
            f = None
            if sid is not None and n is not None:
                c2, tk = self._req("GET", f"/api/shots/{sid}/video-takes")
                f = next((t["file"] for t in tk.get("takes", []) if t.get("n") == n), None) if c2 == 200 else None
            return {"state": "done", "take": n, "file": f, "local_path": str(ROOT / "data" / f) if f else None,
                    "job": {k: js.get(k) for k in ("id", "gpu", "state", "started_at", "finished_at")}}
        if st in ("failed", "cancelled"):
            return {"state": st, "error": js.get("error")}
        return {"state": st or "unknown"}

    def cancel(self, job_id: str) -> None:
        self._req("POST", f"/api/jobs/{job_id}/cancel", {})

    def lane_load(self) -> dict[str, int] | None:
        """各道总负载（见 lane_load）；API 查不到 → None（不按外部负载限流）"""
        try:
            code, jobs = self._req("GET", "/api/jobs")
        except SubmitError:
            return None
        if code != 200 or not isinstance(jobs, list):
            return None
        qs: dict = {}
        for g, url in _comfy_urls().items():
            try:
                with urllib.request.urlopen(url.rstrip("/") + "/queue", timeout=8) as r:
                    d = json.loads(r.read().decode("utf-8"))
                qs[g] = len(d.get("queue_running") or []) + len(d.get("queue_pending") or [])
            except (urllib.error.URLError, TimeoutError, ConnectionError, ValueError, OSError):
                qs[g] = None
        return lane_load(jobs, qs)
