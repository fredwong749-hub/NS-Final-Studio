"""渲染任务中心（GPUVIEW 2026-11-01，顶栏“渲染任务”与画布底栏“任务队列”共用的唯一登记表）。

项目方原话：“顶部我需要一个rendering任务tasks,告知我现在整个系统需要rendering的任务(剧本,镜头,图片,视频等细节)
一个all,pending,rending状态对应的objects”；底栏：“这里uiux设计头不喜欢,展示内容也很快,你思考重构”。

GET /api/render-tasks[?run=series10_v1]
  → {at, counts:{all,pending,rendering,failed,done}, rows:[…], sources:{…各来源条数…}, parity:{…}}
  每行 {id, type(剧本/分镜/首帧/尾帧/视频/音色/资产图/对比/训练/其他), episode, shot, obj, title, agent, lane,
        status: pending|rendering|failed|done, sub(排队/计划中/需重出/已重试成功…), progress{step,steps,pct}, eta_s,
        elapsed_s, started, attempt, max_attempts, error{text,what,next,raw,resolved_by}, thumb, full, link,
        source(ns_api|comfy|heartbeat|story|plan), ids{job_id,prompt_id,seed}, at}
  分桶：每行只在一个桶里，all = pending + rendering + failed + done。
    · 失败后同一镜同一阶段已有成品（或后面一次成功）= done（sub“失败后已重试成功”，error.resolved_by 指向成功那次）；
    · 已取消的 ns_api 任务不算渲染任务（不进任何桶，sources.cancelled 记条数）；
    · 剧本 / 分镜只列进行中 / 等待 / 要返修（写完的不进“已完成（最近）”）。
来源（全部只读）：ns_api 任务队列（/api/jobs 同一份，不截 50 条）、各 ComfyUI 道的队列与最近历史（gpu_live 缓存，
  标签 extra_data.ns_tag / 推断）、GPU 心跳（data/gpu_heartbeats）、写作流水线 P3/P4（story_runs）、
  计划中（集摘要里缺当前首帧 / 尾帧 / 视频、或首帧因剧本已改过期的镜头）。
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

from fastapi import APIRouter

from ns_agent import comfy_tag as CT

router = APIRouter(tags=["render-tasks"])
REPO = Path(__file__).resolve().parents[3]
SOURCE = "inproc"          # alt 只读实例（apps/web/e2e/gpuview/alt_api.py）改成 "http"：任务表 / 集摘要从 :8800 读
HTTP_BASE = "http://127.0.0.1:8800"
DEFAULT_RUN = "series10_v1"
DONE_WINDOW_S = 24 * 3600
STAGE_TYPE = {"image": "首帧", "first": "首帧", "last": "尾帧", "video": "视频", "asset": "资产图", "asset_gen": "资产图",
              "frame": "首帧"}
TYPE_FIELD = {"首帧": "first_frame", "尾帧": "last_frame_target", "视频": "video"}
_cache: dict = {"at": 0.0, "key": None, "val": None}
RECENT_FAIL_H = 6     # UIRSI r42 → r43 → r44（总调度 r44：顶栏失败口径改成“近 6 小时”）：只挂最近 6 小时、且后来没成功过的失败


# ---------------------------------------------------------------- 来源
def _viewer() -> str:
    try:
        return (REPO / "data" / "auth" / "viewer_token").read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _http(path: str, timeout: float = 30):
    req = urllib.request.Request(HTTP_BASE + path, headers={"x-ns-viewer-token": _viewer()})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def ns_jobs() -> list[dict]:
    if SOURCE == "http":
        try:
            return _http("/api/jobs") or []
        except Exception:  # noqa: BLE001
            return []
    from ns_api import jobs as JOBS  # noqa: PLC0415
    from ns_api.app import _jobs as legacy  # noqa: PLC0415
    v1 = [{**j, "v1": True, "stage": {"first": "image"}.get(j.get("stage"), j.get("stage")) or (
        "video" if j.get("kind") == "video" else j.get("kind"))} for j in JOBS.all_jobs()]
    return list(legacy.values()) + v1


def summary_eps() -> list[dict]:
    if SOURCE == "http":
        try:
            return (_http("/api/episodes/summary", timeout=60) or {}).get("episodes") or []
        except Exception:  # noqa: BLE001
            return []
    from ns_api.app import _summary_cache  # noqa: PLC0415
    data, _at = _summary_cache.get()
    return data or []


def story_stages(run: str | None) -> dict[int, dict]:
    from ns_api.live import _script_stages  # noqa: PLC0415
    return _script_stages(run)


# ---------------------------------------------------------------- 人话
def _t(s) -> float | None:
    if s in (None, ""):
        return None
    if isinstance(s, (int, float)):
        return float(s)
    try:
        return time.mktime(time.strptime(str(s)[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def _ep_shot(shot_id: str | None) -> tuple[int | None, str | None]:
    m = re.match(r"ep(\d+)-(S\d+)", str(shot_id or ""))
    return (int(m.group(1)), m.group(2)) if m else (None, None)


def humanize_error(raw: str | None) -> dict:
    """原始报错 → {what 发生了什么, next 接下来会怎样}（原文另放 raw，界面收在“技术详情”）"""
    e = str(raw or "")
    if not e:
        return {"what": "没出成（没有报错原文）", "next": "可以重试"}
    m = re.search(r"No such file or directory: '([^']+)'", e)
    if m:
        name = re.split(r"[\\/]", m.group(1))[-1]
        if re.search(r"refcrops", m.group(1), re.I):
            return {"what": f"参考裁切图刚好在重建（{name} 当时被删掉重做）", "next": "重建完成后重试即可"}
        if re.search(r"_cache|cache|_thumbs", m.group(1), re.I):
            return {"what": f"缓存文件当时不在（{name}）", "next": "重试即可"}
        return {"what": f"找不到文件 {name}", "next": "文件补上后重试"}
    if re.search(r"out of memory|CUDA OOM|OutOfMemory|allocation on device", e, re.I):
        return {"what": "显存不够（同一张卡上还有别的任务）", "next": "等卡空了重试，或换一张卡"}
    if re.search(r"训练锁", e):
        return {"what": "这张卡被 LoRA 训练锁着", "next": "训练结束后自动可用"}
    if re.search(r"API 重启|interrupted|中断", e, re.I):
        return {"what": "API 重启时被打断（不是画面问题）", "next": "重试即可"}
    if re.search(r"timed? ?out|超时", e, re.I):
        return {"what": "超时：卡太忙或隧道慢", "next": "重试即可"}
    if re.search(r"connection|refused|unreachable|连不上", e, re.I):
        return {"what": "连不上出图卡（隧道断了？）", "next": "隧道恢复后重试"}
    if re.search(r"validation error for|errors\.pydantic\.dev", e, re.I):
        return {"what": "存版本失败（系统问题，不是画面问题）", "next": "已记录，重试即可"}
    if re.search(r"坏图|契约|contract", e, re.I):
        return {"what": e.splitlines()[0][:80], "next": "换 seed 重出"}
    first = e.strip().splitlines()[0]
    return {"what": first[:80] + ("…" if len(first) > 80 else ""), "next": "可以重试"}


# ---------------------------------------------------------------- 组装
def _row(**kw) -> dict:
    base = {"id": None, "type": "其他", "episode": None, "shot": None, "obj": None, "title": "", "agent": None,
            "lane": None, "status": "pending", "sub": None, "progress": None, "eta_s": None, "elapsed_s": None,
            "started": None, "attempt": None, "max_attempts": None, "error": None, "thumb": None, "full": None,
            "link": None, "source": None, "ids": {}, "at": None}
    base.update(kw)
    ep, sh = base["episode"], base["shot"]
    if not base["link"]:
        if ep and sh:
            base["link"] = f"#ep{int(ep):02d}-{sh}"
        elif ep:
            base["link"] = f"#ep{int(ep):02d}"
        elif base["type"] == "资产图":
            base["link"] = "#/assets"
    return base


def _title(typ: str, ep, sh, obj=None, extra=None) -> str:
    parts = [typ]
    if ep:
        parts.append(f"第{int(ep)}集" + (f" {sh}" if sh else ""))
    if obj:
        parts.append(str(obj))
    if extra:
        parts.append(str(extra))
    return " · ".join(parts)


def _comfy_rows(lanes: dict, ns_prompt_ids: set) -> list[dict]:
    from ns_api import gpu_live as GL  # noqa: PLC0415
    rows = []
    now = time.time()
    for name, ln in lanes.items():
        if not ln.get("reachable") and not ln.get("stale"):   # 短暂断开（2 分钟内）沿用断开前的队列
            continue
        items = GL.lane_items(ln)
        for st, lst in (("rendering", items["running"]), ("pending", items["pending"])):
            for pos, it in enumerate(lst):
                if it["prompt_id"] in ns_prompt_ids:
                    continue
                t = it["tag"]
                typ = CT.KIND_TYPE.get(t.get("kind"), "其他")
                ep, sh = t.get("episode"), t.get("shot")
                rows.append(_row(
                    id=f"comfy:{it['prompt_id']}", type=typ, episode=ep, shot=sh, obj=t.get("obj"),
                    title=_title(typ, ep, sh, t.get("obj"), t.get("label") or (
                        f"{t.get('family')} {t['steps']} 步" if typ == "视频" and t.get("steps") else None)),
                    agent=t.get("agent") + ("（推断）" if t.get("inferred") else ""), lane=name, status=st,
                    sub="排队第 %d 位" % (pos + 1) if st == "pending" else "渲染中",
                    progress=it.get("progress"), eta_s=it.get("eta_s") if st == "rendering" else it.get("starts_in_s"),
                    elapsed_s=it.get("elapsed_s"), started=it.get("started"), attempt=t.get("attempt"),
                    max_attempts=t.get("max_attempts"), source="comfy", at=it.get("created"),
                    ids={"prompt_id": it["prompt_id"], "client_id": it.get("client_id"), "job": t.get("job")},
                    batch={"idx": t.get("idx"), "total": t.get("total")} if t.get("idx") else None))
        for h in items["recent"]:
            if h["prompt_id"] in ns_prompt_ids or not h.get("end") or now - h["end"] > DONE_WINDOW_S:
                continue
            t = h["tag"]
            typ = CT.KIND_TYPE.get(t.get("kind"), "其他")
            ep, sh = t.get("episode"), t.get("shot")
            img = (h.get("images") or [None])[0]
            err = None
            if not h.get("ok"):
                err = {**humanize_error(h.get("error")), "raw": h.get("error")}
            rows.append(_row(
                id=f"comfy:{h['prompt_id']}", type=typ, episode=ep, shot=sh, obj=t.get("obj"),
                title=_title(typ, ep, sh, t.get("obj"), t.get("label")), agent=t.get("agent") + ("（推断）" if t.get("inferred") else ""),
                lane=name, status="done" if h.get("ok") else "failed", sub="完成" if h.get("ok") else "失败",
                elapsed_s=round(h["end"] - h["start"], 1) if h.get("start") else None, started=h.get("start"),
                attempt=t.get("attempt"), max_attempts=t.get("max_attempts"), error=err, source="comfy", at=h.get("end"),
                thumb=GL._thumb_url(name, img, 200) if img else None, full=GL._thumb_url(name, img) if img else None,
                ids={"prompt_id": h["prompt_id"], "client_id": h.get("client_id"), "job": t.get("job")}))
    return rows


def _job_rows(jobs: list[dict], shots: dict, lane_running: dict) -> tuple[list[dict], int]:
    rows = []
    cancelled = 0
    now = time.time()
    for j in jobs:
        state = j.get("state")
        if state == "cancelled":
            cancelled += 1
            continue
        sid = j.get("shot_id")
        typ = STAGE_TYPE.get(str(j.get("stage") or ""), "视频" if j.get("kind") == "video" else "资产图" if str(sid or "").startswith("asset:") else "首帧")
        ep, sh = _ep_shot(sid)
        obj = str(sid)[6:] if str(sid or "").startswith("asset:") else None
        st = {"queued": "pending", "running": "rendering", "failed": "failed", "done": "done"}.get(state, "pending")
        created, started, finished = _t(j.get("created_at")), _t(j.get("started_at")), _t(j.get("finished_at"))
        if st == "done" and finished and now - finished > DONE_WINDOW_S:
            continue
        lane = None
        try:
            from ns_render import endpoints as EP  # noqa: PLC0415
            lane = EP.lane_name(j.get("gpu")) if j.get("gpu") is not None else None
        except Exception:  # noqa: BLE001
            lane = None
        el = (finished or now) - started if started else None
        eta = None
        if st == "rendering" and j.get("eta_s") and el is not None:
            eta = max(0.0, float(j["eta_s"]) - el)
        prog = None
        live = lane_running.get(j.get("prompt_id")) if j.get("prompt_id") else None
        if live:
            prog = live.get("progress")
            eta = live.get("eta_s") if live.get("eta_s") is not None else eta
        jp = j.get("progress") if isinstance(j.get("progress"), dict) else None
        # IMGPERF（data/qa/imgperf/gpuview_render_tasks.diff）：job.progress 是阶段记录 {stage,label,step,total,since}，
        # 不是步数条——只有带 steps / pct 时才给进度条
        if jp and (jp.get("steps") or jp.get("pct") is not None):
            prog = prog or jp
        take = j.get("take")
        tn = take.get("n") if isinstance(take, dict) else take
        err = {**humanize_error(j.get("error")), "raw": j.get("error")} if st == "failed" else None
        sub = {"pending": "排队", "rendering": "渲染中", "failed": "失败", "done": f"完成{f' → #{tn}' if tn else ''}"}[st]
        stage_since = None
        if jp and jp.get("label") and st in ("pending", "rendering") and jp.get("stage") not in ("queued", "done", "failed", "cancelled"):
            sub = jp["label"]                      # 例：“GPU 出图” / “ComfyUI 排队（前面 2 个）” / “上传参考图 2”
            stage_since = _t(jp.get("since"))
        if st == "pending" and j.get("comfy_wait"):
            w = j["comfy_wait"]
            sub = f"等卡：{w.get('who')} 在用" if w.get("who") != "offline" else "等卡：ComfyUI 没启动"
        s = shots.get(sid) or {}
        thumb = None
        if st == "done" and typ in TYPE_FIELD and s.get(TYPE_FIELD[typ]) and typ != "视频":
            thumb = s.get(TYPE_FIELD[typ])
        rows.append(_row(
            id=f"job:{j.get('id')}", type=typ, episode=ep, shot=sh, obj=obj, title=_title(typ, ep, sh, obj),
            agent="画布" if j.get("v1") else "画布（旧队列）", lane=lane, status=st, sub=sub, progress=prog, eta_s=eta,
            elapsed_s=round(el, 1) if el is not None else None, started=started, error=err, source="ns_api",
            at=finished or started or created, thumb=thumb, full=thumb,
            ids={"job_id": j.get("id"), "prompt_id": j.get("prompt_id"), "seed": j.get("seed") or (j.get("params") or {}).get("seed"),
                 "take": tn}, stage=j.get("stage"), shot_id=sid, stage_since=stage_since))
    return rows, cancelled


def _resolve_and_attempts(rows: list[dict], shots: dict) -> None:
    """同一 镜头×类型：按时间排，算第几次；失败后有成功 / 已有成品 → 记 resolved_by，归 done 桶"""
    groups: dict[tuple, list] = {}
    for r in rows:
        if r["episode"] and r["shot"] and r["type"] in ("首帧", "尾帧", "视频"):
            groups.setdefault((r["episode"], r["shot"], r["type"]), []).append(r)
    for (ep, sh, typ), lst in groups.items():
        lst.sort(key=lambda r: r.get("at") or 0)
        att = 0
        for r in lst:
            if r["source"] in ("ns_api", "comfy"):
                att += 1
                if r["attempt"] is None:
                    r["attempt"] = att
        for i, r in enumerate(lst):
            if r["status"] != "failed":
                continue
            nxt = [x for x in lst[i + 1:] if x["status"] == "done"]
            later = next((x for x in nxt if x["source"] == r["source"]), None) or (nxt[0] if nxt else None)
            sid = f"ep{int(ep):02d}-{sh}"
            have = (shots.get(sid) or {}).get(TYPE_FIELD[typ])
            if later or have:
                r["status"] = "done"
                r["sub"] = "失败后已重试成功"
                tk = (later or {}).get("ids", {}).get("take")
                by = f"{typ} #{tk}" if tk else f"{typ}新的一张（{later['agent']}）" if later else ""
                r["error"] = {**(r["error"] or {}), "resolved_by": later["id"] if later else None,
                              "resolved_text": f"已自动重试成功 → {by}" if later else "这一镜现在已有成品，不用处理",
                              "next": "不用处理"}


def _plan_rows(eps: list[dict], active: set, run: str | None) -> list[dict]:
    rows = []
    for e in eps:
        n = int(e.get("number") or 0)
        for s in e.get("shots") or []:
            sid = s.get("id")
            _ep, sh = _ep_shot(sid)
            if not sh:
                continue
            stale = [x for x in ((s.get("stale") or {}).get("image") or []) if x]
            for typ, f in TYPE_FIELD.items():
                if (n, sh, typ) in active:
                    continue
                have = s.get(f)
                if have and not (typ == "首帧" and stale):
                    continue
                if not have and typ != "首帧" and not s.get("first_frame"):
                    sub = "计划中 · 等首帧"
                elif have:
                    sub = f"需重出：{'、'.join(stale)}"
                else:
                    sub = "计划中（还没提交）"
                thumb = have if have and typ != "视频" else None
                rows.append(_row(id=f"plan:{sid}:{typ}", type=typ, episode=n, shot=sh, title=_title(typ, n, sh),
                                 status="pending", sub=sub, source="plan", thumb=thumb, full=thumb, shot_id=sid))
    for n, st in sorted(story_stages(run).items()):
        for typ, node in (("剧本", "P3"), ("分镜", "P4")):
            v = st.get(node)
            if v in ("ok", "unchecked", "reused"):
                continue
            if v in ("needs_writer", "budget_stop", "error"):
                status, sub = "failed", {"needs_writer": "要返修", "budget_stop": "预算停", "error": "出错"}[v]
                err = {"what": {"needs_writer": "写作检查没过，要写作模型返修", "budget_stop": "写作预算用完停了",
                                "error": "写作出错"}[v], "next": "写作流水线会返修" if v == "needs_writer" else "需要处理", "raw": v}
            elif st.get("running") and v not in (None, "pending"):
                status, sub, err = "rendering", "写作中", None
            else:
                status, sub, err = "pending", "等待", None
            rows.append(_row(id=f"story:{run}:{n}:{node}", type=typ, episode=n, title=_title(typ, n, None, None, node),
                             agent="写作模型", status=status, sub=sub, error=err, source="story",
                             link=f"#/script-create?run={run}"))
    return rows


def _hb_rows(hbs: list[dict]) -> list[dict]:
    rows = []
    for b in hbs:
        typ = CT.KIND_TYPE.get(b.get("kind"), "其他")
        st = b.get("step")
        prog = {"step": st, "steps": b.get("steps")} if st is not None and b.get("steps") else (
            {"pct": b.get("pct")} if b.get("pct") is not None else None)
        lane = f"{b.get('server')}:{b.get('gpu')}" if b.get("server") is not None and b.get("gpu") is not None else b.get("server")
        rows.append(_row(id=f"hb:{b.get('agent')}:{b.get('pid')}:{b.get('label')}", type=typ, episode=b.get("episode"),
                         shot=b.get("shot"), title=b.get("label") or typ, agent=b.get("agent"), lane=lane,
                         status="rendering", sub="渲染中", progress=prog, eta_s=b.get("eta_s"),
                         elapsed_s=round(time.time() - float(b["started"]), 1) if b.get("started") else None,
                         started=b.get("started"), source="heartbeat", at=b.get("updated")))
    return rows


PRODUCER_REGISTRY = REPO / "data" / "producer" / "registry.json"
PROD_TYPE = {"first": "首帧", "last": "尾帧", "video": "视频"}


def _producer_rows(active: set, shots: dict) -> list[dict]:
    """PRODUCER 登记表（data/producer/registry.json，docs/uimaster/LOCKS.md 接口说明）：它排着、还没投到 ComfyUI 的对象。
    已经在 ComfyUI / 画布队列里的（同镜同类有“等待 / 渲染中”行）不重复列；passed 由 ComfyUI 历史 / 画布任务体现，不再列"""
    try:
        reg = json.loads(PRODUCER_REGISTRY.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    rows = []
    for t in reg.get("tasks") or []:
        typ = PROD_TYPE.get(str(t.get("kind")), "其他")
        ep, sh = _ep_shot(t.get("shot"))
        ep = ep or t.get("ep")
        st = str(t.get("status") or "")
        if st == "passed" or (ep, sh, typ) in active:
            continue
        # PRODUCER 的 running 包括“别的 agent 的批次在做”（如 ASSETMASTER frames_v2）；此刻真在卡上的已由 ComfyUI 行列出
        # （上面 active 去重），剩下的并不占卡 → 算等待，写清楚在谁的批次里（11-01：曾显示“渲染中 79”而只有 6 张卡）
        status = {"failed": "failed", "best_effort": "done"}.get(st, "pending")
        sub = {"ready": f"就绪 · 等{t.get('waiting_for') or '空闲道'}", "pending": f"等{t.get('waiting_for') or '上游'}",
               "running": f"在 {t.get('where') or '别的 agent'} 的批次里，还没上卡" + (f"（{t['reason']}）" if t.get("reason") else ""),
               "failed": "失败", "best_effort": "尽力（3 次都没全过契约）"}.get(st, st)
        err = None
        if st in ("failed", "best_effort") and (t.get("last_error") or t.get("reason")):
            err = {**humanize_error(t.get("last_error")), "raw": t.get("last_error")}
            if t.get("reason"):
                err["what"] = t["reason"]
        rows.append(_row(id=f"producer:{t.get('id')}", type=typ, episode=ep, shot=sh, title=_title(typ, ep, sh),
                         agent="PRODUCER", lane=t.get("where"), status=status, sub=sub, error=err, source="producer",
                         attempt=t.get("attempts") or None, max_attempts=t.get("max_attempts"),
                         started=_t(t.get("since")), at=_t(t.get("since")), ids={"job": t.get("id")},
                         shot_id=t.get("shot")))
    return rows


ORDER = {"rendering": 0, "pending": 1, "failed": 2, "done": 3}


def build(run: str | None = DEFAULT_RUN) -> dict:
    from ns_api import gpu_live as GL  # noqa: PLC0415
    lanes = GL.lanes_cache()
    jobs = ns_jobs()
    eps = summary_eps()
    shots = {s.get("id"): s for e in eps for s in e.get("shots") or []}
    ns_pids = {j.get("prompt_id") for j in jobs if j.get("prompt_id")}
    lane_running = {}
    for ln in lanes.values():
        for it in GL.lane_items(ln)["running"]:
            lane_running[it["prompt_id"]] = it
    comfy = _comfy_rows(lanes, ns_pids)
    jrows, cancelled = _job_rows(jobs, shots, lane_running)
    snap = GL.snapshot()
    hb = _hb_rows([b for c in snap["cards"] for b in c["heartbeats"]] + snap["heartbeats"])
    rows = comfy + jrows + hb
    _resolve_and_attempts(rows, shots)
    active = {(r["episode"], r["shot"], r["type"]) for r in rows if r["status"] in ("pending", "rendering") and r["shot"]}
    prod = _producer_rows(active, shots)
    active |= {(r["episode"], r["shot"], r["type"]) for r in prod}
    plan = _plan_rows(eps, active, run)
    rows += prod + plan
    rows.sort(key=lambda r: (ORDER[r["status"]], -(r.get("at") or 0) if r["status"] == "done" else (r.get("at") or 0)))
    counts = {k: sum(1 for r in rows if r["status"] == k) for k in ORDER}
    counts["all"] = len(rows)
    # UIRSI r42（总调度：“渲染任务 1 跑 · 301 等 · 30 失败”口径要查清）：顶栏按钮只数眼下的事——
    # 等 = 真在排队的（producer 待派 + ComfyUI / 画布排队），不含“计划”（还没到能派的镜，plan 行另计 planned）；
    # 失败 = 最近 RECENT_FAIL_H 小时内的失败（更早的是 jobs/v1 落盘的历史，留在列表里可筛，不再挂在按钮上）
    now_ = time.time()
    counts["planned"] = sum(1 for r in rows if r["source"] == "plan")
    counts["queued"] = sum(1 for r in rows if r["status"] == "pending" and r["source"] != "plan")
    ok_after: dict[tuple, float] = {}
    for r in rows:
        if r["status"] in ("done", "rendering") and r.get("at"):
            k_ = (r.get("episode"), r.get("shot"), r.get("type"))
            ok_after[k_] = max(ok_after.get(k_, 0.0), float(r["at"]))
    counts["failed_recent"] = sum(
        1 for r in rows if r["status"] == "failed" and r.get("at") and now_ - float(r["at"]) < RECENT_FAIL_H * 3600
        and ok_after.get((r.get("episode"), r.get("shot"), r.get("type")), 0.0) <= float(r["at"]))   # 后来同一镜同一步成功过 = 已解决
    counts["recent_fail_h"] = RECENT_FAIL_H
    src = {k: sum(1 for r in rows if r["source"] == k) for k in ("ns_api", "comfy", "heartbeat", "story", "producer", "plan")}
    src["cancelled_jobs_excluded"] = cancelled
    lane_q = {name: {"running": len(ln.get("running") or []), "pending": len(ln.get("pending") or []),
                     "reachable": ln.get("reachable")} for name, ln in lanes.items()}
    return {"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "ts": time.time(), "run": run, "counts": counts, "rows": rows,
            "sources": src, "lanes": lane_q, "episodes": sorted({r["episode"] for r in rows if r["episode"]}),
            "types": sorted({r["type"] for r in rows}), "warming": not lanes}


@router.get("/api/render-tasks")
def render_tasks(run: str | None = DEFAULT_RUN):
    now = time.time()
    if _cache["key"] == run and now - _cache["at"] < 3 and _cache["val"]:
        return _cache["val"]
    val = build(run)
    _cache.update(key=run, at=now, val=val)
    return val
