"""
gpu3 渲染桥（FastAPI）。所有接口在 /api/gpu3/ 下，便于并进 ns_api 或由 ns_api 反向代理。
    uvicorn --factory ns_canvas.app:create_app --host 127.0.0.1 --port 5180
接口与契约：docs/canvas.md。
"""
from __future__ import annotations

import re
from pathlib import Path

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from . import audit, media, progress, rules, runs
from .config import Settings
from .models import H3EditBody, OverrideBody, RunBody, RunCancelBody, now, RenderEvent, RerenderRequest, SeriesControl, ShotRenders
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
        main = proots[0]
        if hasattr(main, "shot_dir"):
            d = main.shot_dir(ep, s)
            if d.is_dir():
                extra = audit.shot_audit(d, [], out.active)
                out.audit, out.h3, out.shot_state, out.active_video, out.video_gate = (
                    extra["audit"], extra["h3"], extra["shot_state"], extra["active_video"], extra["video_gate"])
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

    @app.get(f"{P}/projects/{{slug}}/episodes/{{ep}}")
    def project_episode(slug: str, ep: int):
        shots = episode(ep, slug)
        main = proj(slug).roots[0]
        dirs = [main.shot_dir(ep, int(x["shot"].split("-S")[1])) for x in shots] if hasattr(main, "shot_dir") else []
        dirs = [d for d in dirs if d.is_dir()]
        return {"project": slug, "ep": ep, "audit_summary": audit.episode_audit_summary(dirs), "shots": shots}

    @app.get(f"{P}/projects/{{slug}}/shots/{{sid}}")
    def project_shot(slug: str, sid: str):
        return shot(sid, slug)

    def shot_dir_for(slug: str, sid: str) -> Path:
        ep, s = parse_shot_id(sid)
        known = script_shots(ep, slug)
        if known is not None and s not in known:
            raise KeyError(sid)
        main = proj(slug).roots[0]
        d = main.shot_dir(ep, s)
        if not d.is_dir():
            raise KeyError(f"{sid}（{d} 不存在）")
        return d

    @app.post(f"{P}/projects/{{slug}}/shots/{{sid}}/h3_edit")
    def h3_edit(slug: str, sid: str, body: H3EditBody):
        if body.by != "owner":
            raise HTTPException(403, "H3 提示词只能由项目方改（by 必须是 owner）")
        if not body.text.strip():
            raise ValueError("text 不能为空")
        d = shot_dir_for(slug, sid)
        try:
            rec = audit.write_h3_edit(d, body.text, body.by, body.base_sha)
        except audit.ConflictError as e:
            raise HTTPException(409, str(e))
        st = load_json(d / "status.json", {}) or {}
        ovs = {o.get("rule_id") for o in ((st.get("audit") or {}).get("overrides") or []) if isinstance(o, dict)}
        try:
            res = audit.lint(settings.h3_lint, body.text, d, ovs)
        except FileNotFoundError as e:
            res = {"ok": None, "error": str(e)}
        return {"shot": sid, "saved": rec, "lint": res, "rendered": False}

    @app.post(f"{P}/projects/{{slug}}/shots/{{sid}}/override")
    def add_override(slug: str, sid: str, body: OverrideBody):
        ids = audit.rule_ids(settings.rule_ids)
        if not ids:
            raise HTTPException(503, f"规则表不可读：{settings.rule_ids}")
        if body.rule_id not in ids:
            raise ValueError(f"rule_id {body.rule_id} 不在 docs/audit/rule_ids.md 里")
        if not ids[body.rule_id]:
            raise ValueError(f"rule_id {body.rule_id} 已作废，不能豁免")
        if not body.owner_quote.strip():
            raise ValueError("owner_quote 必须是项目方原话，不能为空")
        if body.by != "owner":
            raise HTTPException(403, "豁免只能凭项目方原话提出（by 必须是 owner）")
        return {"shot": sid, **audit.add_override_request(shot_dir_for(slug, sid), body.rule_id, body.owner_quote.strip(), body.by)}

    # ------------------------------------------------------------ 按集运行（项目方选卡）
    runs_dir = settings.base / "runs"

    def run_file(run_id: str) -> Path:
        if not re.fullmatch(r"run-ep\d+-[0-9a-f]{8}", run_id):
            raise KeyError(run_id)
        p = runs_dir / f"{run_id}.json"
        if not p.exists():
            raise KeyError(run_id)
        return p

    @app.post(f"{P}/projects/{{slug}}/episodes/{{ep}}/run")
    def run_episode(slug: str, ep: int, body: RunBody):
        if body.by != "owner":
            raise HTTPException(403, "只有项目方能按集运行（by 必须是 owner）")
        allowed = sorted(set(settings.run_gpus) - set(settings.faulty_gpus))
        if body.gpu not in allowed:
            raise HTTPException(422, f"gpu 只能是 {allowed}（GPU 2 故障，永不使用）")
        if not body.note.strip():
            raise HTTPException(422, "note 必填（写清这次为什么跑）")
        steps = list(dict.fromkeys(body.steps))
        if "assemble" in steps:
            raise HTTPException(422, "assemble 不在这里跑：成集装配由 fredw-d9 在笔记本做（tools/assemble_episode.py）")
        bad = [x for x in steps if x not in runs.STEPS]
        if bad or not steps:
            raise HTTPException(422, f"steps 只能是 {list(runs.STEPS)} 的非空子集；不认识：{bad}")
        pj = proj(slug)
        shots = episode(ep, slug)
        if not shots:
            raise KeyError(f"{slug} ep{ep:02d}")
        main = pj.roots[0]
        dirs = {x["shot"]: main.shot_dir(ep, int(x["shot"].split("-S")[1])) for x in shots} if hasattr(main, "shot_dir") else {}
        dirs = {k: v for k, v in dirs.items() if v.is_dir()}
        sc = load_json(pj.script, {}) if pj.script else {}
        e = next((x for x in (sc or {}).get("episodes", []) if x.get("number") == ep), {}) or {}
        tl = settings.state_timeline if slug == settings.default_slug else (
            settings.projects_root / slug / "data" / "state_timeline.json" if settings.projects_root else None)
        qa = load_json(pj.dir / f"ep{ep:02d}" / "qa.json", {}) or {}
        adult_shots = {f"ep{ep:02d}-S{int(s['index'])}" for s in e.get("shots") or [] if s.get("adult")}
        items = runs.shot_items(ep, shots, dirs, steps, red_episode=bool(e.get("high_intensity")),
                                reviews=runs.timeline_reviews(tl), qa_pass=(qa.get("verdict") == "pass"),
                                adult_shots=adult_shots, s2_blocked=runs.timeline_s2(tl))
        holder = runs.lock_holder(settings.lock_dir, body.gpu)
        run_id = runs.new_run_id(ep)
        resp = {"run_id": run_id, "dry_run": body.dry_run, "project": slug, "ep": ep, "gpu": body.gpu, "steps": steps,
                "gpu_holder": holder, "shots": items, "counts": runs.counts(items)}
        if body.dry_run:
            return resp
        if holder:
            raise HTTPException(409, {"message": f"GPU {body.gpu} 已被占用", "holder": holder})
        at = now()
        lend = settings.lock_dir / f"lend.gpu{body.gpu}"
        lend.parent.mkdir(parents=True, exist_ok=True)
        lend.write_text(f"owner-run {run_id} ep{ep:02d} {','.join(steps)} — {body.note.strip()}", encoding="utf-8")
        queued = []
        for it in items:
            if not it["eligible"]:
                continue
            rec = {"schema": "nsfs_canvas.run_item/v1", "id": f"{run_id}-{len(queued) + 1:02d}", "op": "run",
                   "run_id": run_id, "project": slug, "shot": it["shot"], "step": it["step"], "gpu": body.gpu,
                   "by": body.by, "note": body.note.strip(), "at": at}
            queue.append_raw(rec)
            queued.append({"id": rec["id"], "shot": it["shot"], "step": it["step"]})
        record = {"schema": "nsfs_canvas.run/v1", "run_id": run_id, "project": slug, "ep": ep, "gpu": body.gpu,
                  "steps": steps, "by": body.by, "note": body.note.strip(), "at": at, "status": "queued",
                  "lend_file": str(lend), "items": queued, "skipped": [i for i in items if not i["eligible"]],
                  "counts": resp["counts"]}
        runs.write_json(runs_dir / f"{run_id}.json", record)
        return {**resp, "queued": queued, "lend_file": str(lend), "record": str(runs_dir / f"{run_id}.json")}

    @app.get(f"{P}/projects/{{slug}}/episodes/{{ep}}/run/{{run_id}}")
    def get_run(slug: str, ep: int, run_id: str):
        rec = load_json(run_file(run_id), {})
        its = runs.item_states(rec, queue.state())
        c: dict[str, int] = {}
        for i in its:
            c[i["state"]] = c.get(i["state"], 0) + 1
        return {**{k: rec.get(k) for k in ("run_id", "project", "ep", "gpu", "steps", "by", "note", "at", "status",
                                           "cancelled_at", "skipped")},
                "items": its, "progress": c, "active": any(i["state"] in ("queued", "rendering") for i in its),
                "lend_held": runs.lend_names_run(settings.lock_dir, rec.get("gpu", -1), run_id)}

    @app.post(f"{P}/projects/{{slug}}/episodes/{{ep}}/run/{{run_id}}/cancel")
    def cancel_run(slug: str, ep: int, run_id: str, body: RunCancelBody):
        if body.by != "owner":
            raise HTTPException(403, "只有项目方能取消（by 必须是 owner）")
        p = run_file(run_id)
        rec = load_json(p, {})
        qs = queue.state()
        cancelled = []
        for it in rec.get("items", []):
            if (qs.get(it["id"]) or {}).get("state") == "queued":
                queue.cancel(it["id"])
                cancelled.append(it["id"])
        released = False
        if runs.lend_names_run(settings.lock_dir, rec.get("gpu", -1), run_id):
            (settings.lock_dir / f"lend.gpu{rec['gpu']}").unlink(missing_ok=True)
            released = True
        rec.update(status="cancelled", cancelled_at=now(), cancelled_items=cancelled)
        runs.write_json(p, rec)
        return {"run_id": run_id, "cancelled": cancelled, "lend_released": released,
                "still_running": [i["id"] for i in rec.get("items", [])
                                  if (qs.get(i["id"]) or {}).get("state") == "rendering"]}

    @app.get(f"{P}/rules")
    def list_rules():
        try:
            return rules.parse_table(settings.rule_ids)
        except rules.RuleError as e:
            raise HTTPException(e.status, e.detail)

    @app.get(f"{P}/rules/{{rule_id}}")
    def explain_rule(rule_id: str):
        try:
            return rules.explain(rule_id, table=settings.rule_ids, python=settings.shot_audit_python,
                                 script=settings.shot_audit, timeout=settings.explain_timeout,
                                 cwd=settings.shot_audit.parent.parent if settings.shot_audit else None)
        except rules.RuleError as e:
            raise HTTPException(e.status, e.detail)

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
