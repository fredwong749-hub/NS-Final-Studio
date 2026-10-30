"""
gpu3 渲染桥（FastAPI）。所有接口在 /api/gpu3/ 下，便于并进 ns_api 或由 ns_api 反向代理。
    uvicorn --factory ns_canvas.app:create_app --host 127.0.0.1 --port 5180
接口与契约：docs/canvas.md。
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import media, progress
from .config import Settings
from .models import RenderEvent, RerenderRequest, SeriesControl, ShotRenders
from .sources import load_json, make_roots, parse_shot_id, shot_id
from .store import Queue

P = "/api/gpu3"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings.from_env()
    roots = make_roots(settings.roots)
    queue = Queue(settings.queue_dir)
    media_roots: dict[str, Path] = {r.label: r.cfg.path for r in roots}
    app = FastAPI(title="NS-Final gpu3 渲染桥", version="1")

    @app.exception_handler(KeyError)
    async def _nf(_, e):
        return JSONResponse({"detail": f"找不到 {e}"}, status_code=404)

    @app.exception_handler(ValueError)
    async def _ve(_, e):
        return JSONResponse({"detail": str(e)}, status_code=422)

    def proj(slug: str | None) -> progress.Project:
        return progress.project(settings, slug or settings.default_slug, roots)

    def script_shots(ep: int, slug: str | None = None) -> list[int] | None:
        pj = proj(slug)
        data = load_json(pj.script, None) if pj.script else None
        if not data:
            return None
        e = next((x for x in data.get("episodes", []) if x["number"] == ep), None)
        return [s["index"] for s in e["shots"]] if e else []

    def url_for(p: Path | None) -> str | None:
        if p is None:
            return None
        for label, base in media_roots.items():
            try:
                return f"{P}/media/{label}/{p.relative_to(base).as_posix()}"
            except ValueError:
                continue
        return None

    def renders(ep: int, s: int, qstate: dict, slug: str | None = None) -> ShotRenders:
        sid = shot_id(ep, s)
        out = ShotRenders(shot=sid)
        slug = slug or settings.default_slug
        proots = proj(slug).roots
        for r in proots:
            found, active, err = r.takes(ep, s)
            if r is proots[0]:
                out.active, out.error = active, err
            for t, paths in found:
                t.url = url_for(paths.get("file"))
                if t.url and t.stage == "image":
                    t.thumb = t.url.replace(f"{P}/media/", f"{P}/thumb/", 1)
                t.last_target_url = url_for(paths.get("last_target"))
                if t.stage == "video":
                    q = "" if slug == settings.default_slug else f"?project={slug}"
                    t.last_frame_url = url_for(paths.get("last_frame")) or f"{P}/shots/{sid}/takes/{r.label}/video/{t.n}/last.png{q}"
                out.takes.append(t)
        mine = sorted((x for x in qstate.values() if x["request"]["shot"] == sid
                       and x["request"].get("project", settings.default_slug) == slug), key=lambda x: x["request"]["at"])
        out.queue = [{"id": x["request"]["id"], "stage": x["request"].get("stage"), "state": x["state"], "at": x["at"],
                      "error": x["error"], "takes": x["takes"]} for x in mine[-10:]]
        live = [x for x in mine if x["state"] != "cancelled"]
        last = live[-1]["state"] if live else None
        if last in ("queued", "rendering", "failed"):
            out.status = last
        elif out.takes:
            out.status = "done"
        return out

    def find_take(sid: str, label: str, stage: str, n: int, slug: str | None = None) -> dict[str, Path]:
        ep, s = parse_shot_id(sid)
        r = next((r for r in proj(slug).roots if r.label == label), None)
        if not r:
            raise KeyError(label)
        for t, paths in r.takes(ep, s)[0]:
            if t.stage == stage and t.n == n:
                return paths
        raise KeyError(f"{sid} {label} {stage} #{n}")

    @app.get(f"{P}/health")
    def health():
        return {"ok": True, "queue": str(queue.path), "events": str(queue.events_path),
                "roots": [{"label": r.label, "kind": r.cfg.kind, "path": str(r.cfg.path), "exists": r.cfg.path.exists()}
                          for r in roots]}

    @app.get(f"{P}/episodes/{{ep}}")
    def episode(ep: int, project: str | None = None):
        shots = script_shots(ep, project)
        if shots is None or not shots:
            shots = sorted({n for r in proj(project).roots for n in r.shot_numbers(ep)}) or (shots or [])
        qs = queue.state()
        return [renders(ep, s, qs, project).model_dump() for s in shots]

    @app.get(f"{P}/shots/{{sid}}")
    def shot(sid: str, project: str | None = None):
        ep, s = parse_shot_id(sid)
        return renders(ep, s, queue.state(), project).model_dump()

    @app.get(f"{P}/shots/{{sid}}/takes/{{label}}/{{stage}}/{{n}}/last.png")
    def last_png(sid: str, label: str, stage: str, n: int, request: Request, w: int | None = None,
                 project: str | None = None):
        paths = find_take(sid, label, stage, n, project)
        p = paths.get("last_frame")
        if not p:
            if "file" not in paths or stage != "video":
                raise HTTPException(404, "这个版本没有视频")
            p = media.extract_last_frame(settings.ffmpeg, paths["file"], settings.cache_dir)
            if not p:
                raise HTTPException(500, "ffmpeg 抽尾帧失败")
        if w:
            p = media.thumbnail(settings.ffmpeg, p, settings.cache_dir, w) or p
        return media.file_response(p, request)

    @app.get(f"{P}/media/{{label}}/{{rel:path}}")
    def media_file(label: str, rel: str, request: Request):
        return media.file_response(_safe(label, rel), request)

    @app.get(f"{P}/thumb/{{label}}/{{rel:path}}")
    def thumb(label: str, rel: str, request: Request, w: int = 360):
        p = _safe(label, rel)
        return media.file_response(media.thumbnail(settings.ffmpeg, p, settings.cache_dir, w) or p, request)

    def _safe(label: str, rel: str) -> Path:
        base = media_roots.get(label)
        if base is None:
            raise HTTPException(404)
        p = (base / rel).resolve()
        if not p.is_relative_to(base.resolve()):
            raise HTTPException(403)
        return p

    @app.post(f"{P}/rerender")
    def rerender(body: RerenderRequest | list[RerenderRequest] = Body(...)):
        reqs = body if isinstance(body, list) else [body]
        out, errors = [], []
        for r in reqs:
            try:
                ep, s = parse_shot_id(r.shot)
                known = script_shots(ep, r.project)
                if known is not None and s not in known:
                    raise KeyError(r.shot)
                if r.op != "render":
                    raise ValueError("取消请用 POST /api/gpu3/queue/{id}/cancel")
                r.shot = shot_id(ep, s)
                out.append(queue.submit(r).model_dump(by_alias=True))
            except (KeyError, ValueError) as e:
                errors.append({"shot": r.shot, "error": str(e)})
        return {"requests": out, "errors": errors}

    # ------------------------------------------------------------ 项目进度 / 系列控制 / GPU
    @app.get(f"{P}/projects/{{slug}}/episodes")
    def project_episodes(slug: str):
        return progress.episodes_progress(settings, proj(slug))

    @app.get(f"{P}/projects/{{slug}}/series")
    def get_series(slug: str):
        return load_json(proj(slug).control_paths[0], None) or {"action": None}

    @app.post(f"{P}/projects/{{slug}}/series")
    def post_series(slug: str, body: SeriesControl):
        if body.episodes is not None and any(e < 1 for e in body.episodes):
            raise ValueError("集号从 1 开始")
        return progress.write_control(proj(slug), body.action, sorted(set(body.episodes)) if body.episodes else None,
                                      body.by, body.note, body.adult_content)

    @app.get(f"{P}/gpus")
    def gpus():
        return progress.gpus(settings)

    @app.get(f"{P}/scheduler")
    def scheduler():
        """T46 阶段调度器的完整计划（scheduler_plan.json，只读）；没有时返回 {"mode": null}。"""
        return progress.scheduler_plan(settings) or {"mode": None}

    @app.post(f"{P}/queue/{{req_id}}/cancel")
    def cancel(req_id: str):
        return queue.cancel(req_id).model_dump(by_alias=True)

    @app.get(f"{P}/queue")
    def list_queue(shot: str | None = None, state: str | None = None, limit: int = 200):
        items = sorted(queue.state().values(), key=lambda x: x["request"]["at"], reverse=True)
        if shot:
            items = [x for x in items if x["request"]["shot"] == shot]
        if state:
            items = [x for x in items if x["state"] == state]
        return [{"id": x["request"]["id"], "shot": x["request"]["shot"], "stage": x["request"].get("stage"),
                 "keep_seed": x["request"].get("keep_seed"), "seed": x["request"].get("seed"),
                 "priority": x["request"].get("priority"), "batch": x["request"].get("batch"),
                 "state": x["state"], "requested_at": x["request"]["at"], "updated_at": x["at"],
                 "error": x["error"], "takes": x["takes"]} for x in items[:limit]]

    @app.post(f"{P}/queue/events")
    def post_event(ev: RenderEvent):
        if ev.id not in queue.state():
            raise KeyError(ev.id)
        queue.event(ev)
        return {"ok": True}

    return app
