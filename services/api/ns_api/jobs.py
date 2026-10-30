"""
v1 共享任务队列（docs/api_v1_contract.md §C / §D）：按 GPU 分道，每道一个后台线程串行跑。

- 道 0 = gpu3 GPU0 ComfyUI（出图，NS_COMFY_URL_GPU0 → NS_COMFY_URL → 127.0.0.1:18188）
- 道 3 = gpu3 GPU3 ComfyUI（H3 视频，NS_COMFY_URL_GPU3 → 127.0.0.1:18191）

出图（W2 frame-jobs）与视频（W3 video-jobs）都用 submit() 入队；状态统一走 GET /api/jobs/{job_id}，
取消走 POST /api/jobs/{job_id}/cancel。任务函数签名 run(client, job) -> dict（并入 job，通常含 take）。
任务函数在长时间等待时应检查 cancelled(job)，并把 ComfyUI prompt_id 写到 job["prompt_id"]，取消时才能精确中断。

W3（fredw-92/W3）最先需要，按契约“如需改动在变更记录说明”建在这里；W2 出图任务直接复用 submit()。
"""
from __future__ import annotations

import os
import queue
import threading
import time
import uuid
from typing import Callable

from fastapi import APIRouter, HTTPException

from ns_render import pipeline as P
from ns_render.comfy_client import ComfyClient, ComfyError, ComfyUnavailable

DEFAULT_URLS = {0: "http://127.0.0.1:18188", 3: "http://127.0.0.1:18191"}


class _Gpus:
    """fredw-92/D1：可用的卡 = 内置 0 / 3 ∪ config/render_endpoints.json 的 gpus 表（如 "1" → 18189 第二条视频线）。
    每次判断都重读配置（加卡不用改代码）；行为同 tuple：`gpu in GPUS`、迭代、f"{GPUS}"。"""

    def _ids(self) -> tuple:
        from ns_render import endpoints as EP
        return EP.gpu_ids()

    def __contains__(self, gpu) -> bool:
        """G36：道 id 可以是 int（gpu33）或 "server:n"（如 "gpu36:1"）；"gpu33:0" 等同 0"""
        from ns_render import endpoints as EP
        try:
            return EP.norm_lane(gpu) in self._ids()
        except (TypeError, ValueError):
            return False

    def __iter__(self):
        return iter(self._ids())

    def __len__(self):
        return len(self._ids())

    def __repr__(self):
        return repr(self._ids())

    __str__ = __repr__


GPUS = _Gpus()
STATES = ("queued", "running", "done", "failed", "cancelled")


def norm(gpu):
    """道 id 归一（ns_render.endpoints.norm_lane）；不合法 → ValueError"""
    from ns_render import endpoints as EP
    return EP.norm_lane(gpu)


def comfy_url(gpu) -> str:
    """W2：同样的环境变量优先级，另读 config/render_endpoints.json（PUT /api/render/endpoints 改了立即生效）"""
    if gpu not in GPUS:
        raise ValueError(f"gpu 只能是 {GPUS}")
    gpu = norm(gpu)
    if not isinstance(gpu, int):            # G36：其他服务器的道只在 lanes 表里
        from ns_render import endpoints as EP
        return EP.url_for_gpu(gpu)
    # W1（fredw-92 定）：优先「模型与 API」页保存的地址（ns_api.llm_config，config/render_endpoints.json），
    # 没保存过才按环境变量 / 内置默认（ns_render.endpoints）兜底
    from ns_api import llm_config as LC
    saved = LC.saved_render_url(gpu)
    if saved:
        return saved
    from ns_render import endpoints as EP
    return EP.url_for_gpu(gpu)


# 测试可替换：client_factory(gpu) -> 有 ComfyClient 接口的对象
def _make_client(gpu):
    from ns_render import endpoints as EP
    c = ComfyClient(comfy_url(gpu), gpu=gpu)
    srv = EP.server_of(gpu)
    if srv != EP.HOME_SERVER:     # G36：实例标识带上服务器名（不同服务器的输出目录不互通，F1 的 [output] 引用按实例分开）
        c.server = srv
    return c


client_factory: Callable[[object], object] = _make_client

_jobs: dict[str, dict] = {}
_runs: dict[str, Callable] = {}
_lanes: dict = {}
_lanes_guard = threading.Lock()
# fredw-92/B-fix：_jobs 的增删 / 遍历 / 状态切换都在这把锁里；对外只给快照副本（worker 线程同时在改 job，
# 直接序列化原 dict 可能“dictionary changed size during iteration”→ 500）。已结束任务内存里最多留 MAX_FINISHED 个
# （按结束时间淘汰最旧的），淘汰后 GET /api/jobs/{id} 回落读盘（data/jobs/v1/<id>.json，落盘不变）
_jobs_guard = threading.RLock()
MAX_FINISHED = 500
FINISHED = ("done", "failed", "cancelled")
router = APIRouter()


class Cancelled(Exception):
    pass


def cancelled(job: dict) -> bool:
    return bool(job.get("cancel_requested"))


RESTART_ERROR = "API 重启中断"
_persist_guard = threading.Lock()


def jobs_dir():
    return P.DATA / "jobs" / "v1"   # data/jobs 下已有编排器的 queue/running/done 等，v1 任务单独一层


def persist(job: dict):
    """任务状态落盘 data/jobs/<id>.json（失败不影响任务）；API 重启后 GET /api/jobs/{id} 仍可查"""
    try:
        import json
        d = jobs_dir()
        d.mkdir(parents=True, exist_ok=True)
        snap = snapshot(job)
        with _persist_guard:
            P._write_json(d / f"{snap['id']}.json", json.loads(json.dumps(snap, ensure_ascii=False, default=str)))
    except Exception:  # noqa: BLE001
        pass


def restore(limit: int = 500) -> int:
    """API 启动时调用：读回最近的任务；上次没跑完的（queued / running）标 failed，error = “API 重启中断”。
    → 标记的个数。只在 app 的 startup 事件里调（测试 / 脚本导入 app 不会动真数据里的任务）"""
    import json
    d = jobs_dir()
    if not d.is_dir():
        return 0
    marked = 0
    files = sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime)
    for f in files[-limit:]:
        try:
            job = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(job, dict) or "id" not in job:
            continue
        if job.get("state") in ("queued", "running"):
            job.update(state="failed", error=RESTART_ERROR, finished_at=P.now(), interrupted=True)
            persist(job)
            marked += 1
        with _jobs_guard:
            _jobs.setdefault(job["id"], job)
    _prune()
    return marked


def snapshot(job: dict) -> dict:
    """浅拷贝（dict.copy 在 GIL 下一次完成，不会遇到别的线程正在加键）；params / take 等子 dict 是整体替换的"""
    with _jobs_guard:
        return dict(job)


def _prune():
    """已结束任务超过 MAX_FINISHED → 按结束时间淘汰最旧的（盘上的 json 保留）"""
    with _jobs_guard:
        fin = [j for j in list(_jobs.values()) if j.get("state") in FINISHED]
        extra = len(fin) - MAX_FINISHED
        if extra <= 0:
            return
        fin.sort(key=lambda j: str(j.get("finished_at") or j.get("created_at") or ""))
        for j in fin[:extra]:
            _jobs.pop(j.get("id"), None)


def _load_disk(job_id: str) -> dict | None:
    import json
    if not job_id or not job_id.isalnum() or len(job_id) > 64:
        return None
    f = jobs_dir() / f"{job_id}.json"
    try:
        job = json.loads(f.read_text(encoding="utf-8")) if f.is_file() else None
    except (OSError, ValueError):
        return None
    return job if isinstance(job, dict) and job.get("id") == job_id else None


def _lane(gpu) -> "queue.Queue[str]":
    with _lanes_guard:
        q = _lanes.get(gpu)
        if q is None:
            q = _lanes[gpu] = queue.Queue()
            threading.Thread(target=_worker, args=(gpu, q), daemon=True, name=f"ns-jobs-gpu{gpu}").start()
        return q


def submit(kind: str, shot_id: str | None, gpu, run: Callable[[object, dict], dict | None],
           params: dict | None = None, eta_s: float | None = None, **meta) -> dict:
    """入队；返回 job（含 job_id）。run 在该 GPU 道的线程里执行（gpu = 道 id：int 或 "gpu36:n"）"""
    comfy_url(gpu)   # 校验 gpu
    gpu = norm(gpu)
    jid = uuid.uuid4().hex[:12]
    job = {"id": jid, "job_id": jid, "kind": kind, "shot_id": shot_id, "gpu": gpu, "state": "queued",
           "created_at": P.now(), "started_at": None, "finished_at": None, "params": params or {},
           "eta_s": eta_s, "take": None, "error": None, **meta}
    with _jobs_guard:
        _jobs[jid] = job
        _runs[jid] = run
    persist(job)
    _lane(gpu).put(jid)
    _prune()
    return snapshot(job)


def get(job_id: str) -> dict | None:
    """快照副本；内存里没有（已淘汰 / 重启前）→ 读盘"""
    with _jobs_guard:
        job = _jobs.get(job_id)
        if job is not None:
            return dict(job)
    return _load_disk(job_id)


def all_jobs(shot_id: str | None = None) -> list[dict]:
    with _jobs_guard:
        js = [dict(j) for j in list(_jobs.values()) if shot_id is None or j.get("shot_id") == shot_id]
    return sorted(js, key=lambda j: str(j.get("created_at") or ""), reverse=True)


def pending(shot_id: str, kind: str | None = None) -> list[dict]:
    with _jobs_guard:
        return [dict(j) for j in list(_jobs.values()) if j.get("shot_id") == shot_id
                and j.get("state") in ("queued", "running") and (kind is None or j.get("kind") == kind)]


def _worker(gpu, q: "queue.Queue[str]"):
    while True:
        jid = q.get()
        with _jobs_guard:
            job, run = _jobs.get(jid), _runs.pop(jid, None)
            if not job or run is None or job["state"] != "queued":
                continue
            job.update(state="running", started_at=P.now())
        persist(job)
        t0 = time.monotonic()
        try:
            out = run(client_factory(gpu), job) or {}
            with _jobs_guard:
                job.update(out)
                job["state"] = "cancelled" if cancelled(job) and not out.get("take") else "done"
        except Cancelled:
            with _jobs_guard:
                job["state"] = "cancelled"
        except Exception as e:  # noqa: BLE001  任何错误记到任务上，线程不退出
            with _jobs_guard:
                job.update(state="cancelled" if cancelled(job) else "failed", error=str(e)[:2000])
        finally:
            with _jobs_guard:
                job["finished_at"] = P.now()
                job["wall_s"] = round(time.monotonic() - t0, 1)
            persist(job)
            _prune()


def wait_prompt(client, job: dict, prompt_id: str, timeout_s: float, poll_s: float = 3) -> dict:
    """等 ComfyUI 跑完；期间响应取消（只中断自己的 prompt，不碰 GPU 上别人的任务）"""
    job["prompt_id"] = prompt_id
    persist(job)
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if cancelled(job):
            _abort(client, prompt_id)
            raise Cancelled()
        try:
            entry = client._json(f"/history/{prompt_id}").get(prompt_id)
            job.pop("poll_error", None)
        except (ComfyUnavailable, ValueError) as e:   # 隧道抖动 / 空响应：prompt 仍在 gpu3 上跑，继续等到截止
            job["poll_error"] = str(e)[:300]
            time.sleep(poll_s)
            continue
        if entry:
            status = entry.get("status", {})
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                raise ComfyError("执行失败: " + (msgs[0][1].get("exception_message", "") if msgs else "").strip()[:1000])
            if status.get("completed"):
                return entry
        time.sleep(poll_s)
    _abort(client, prompt_id)
    raise ComfyError(f"超时 {timeout_s}s")


def _abort(client, prompt_id: str):
    """排队中 → 从队列删除；正在跑且是自己的 → /interrupt；别人的不动"""
    try:
        q = client._json("/queue")
        running = {str(x[1]) for x in q.get("queue_running", []) if len(x) > 1}
        if prompt_id in running:
            client.interrupt()
        else:
            client._json("/queue", {"delete": [prompt_id]})
    except Exception:  # noqa: BLE001
        pass


# ------------------------------------------------------------------ 预计耗时（fredw-92/F4）
ETA_DEFAULT_S = {"video": 840.0, "frame": 70.0}   # 没有历史时：H3 视频 GPU3 实测约 14 min；出图约 1 min
ETA_SAMPLES = 5                                   # 取同类同卡最近几次完成任务的耗时中位数
ETA_DISK_SCAN = 300                               # 只看盘上最近这么多个任务文件
ETA_MIN_WALL_S = 1.0                              # 小于它的（假客户端 / 秒退）不算样本


def recent_durations(kind: str, gpu: int, n: int = ETA_SAMPLES) -> list[float]:
    """同 kind + gpu 最近 n 个 done 任务的 wall_s（新 → 旧）：内存 + 盘上 data/jobs/v1（重启后也有历史）"""
    import json
    seen: dict[str, dict] = {}
    d = jobs_dir()
    try:
        files = sorted(d.glob("*.json"), key=lambda f: f.stat().st_mtime)[-ETA_DISK_SCAN:] if d.is_dir() else []
    except OSError:
        files = []
    for f in files:
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(j, dict) and j.get("id"):
            seen[j["id"]] = j
    with _jobs_guard:
        for j in list(_jobs.values()):
            seen[j["id"]] = dict(j)
    done = [j for j in seen.values() if j.get("kind") == kind and j.get("gpu") == gpu and j.get("state") == "done"
            and isinstance(j.get("wall_s"), (int, float)) and j["wall_s"] >= ETA_MIN_WALL_S]
    done.sort(key=lambda j: str(j.get("finished_at") or j.get("created_at") or ""), reverse=True)
    return [float(j["wall_s"]) for j in done[:n]]


def estimate(kind: str, gpu: int, default: float | None = None) -> float:
    """新任务的预计秒数 = 单个耗时 ×（本卡排在前面的任务数 + 1）；单个耗时 = 最近同类同卡完成任务的中位数，没有历史用默认"""
    import statistics
    ds = recent_durations(kind, gpu)
    per = statistics.median(ds) if ds else (default if default is not None else ETA_DEFAULT_S.get(kind, 70.0))
    with _jobs_guard:
        ahead = sum(1 for j in _jobs.values() if j.get("gpu") == gpu and j.get("state") in ("queued", "running"))
    return round(per * (ahead + 1), 1)


@router.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    job = get(job_id)
    if not job:
        raise HTTPException(404, "没有这个任务")
    return job


@router.post("/api/jobs/{job_id}/cancel")
def job_cancel(job_id: str):
    with _jobs_guard:
        job = _jobs.get(job_id)
        if not job:
            old = _load_disk(job_id)          # 已结束并从内存淘汰：无可取消，原样返回
            if old:
                return old
            raise HTTPException(404, "没有这个任务")
        if job["state"] == "queued":
            job.update(state="cancelled", cancel_requested=True, finished_at=P.now())
        elif job["state"] == "running":
            job["cancel_requested"] = True      # 任务函数在 wait_prompt 里中断自己的 prompt
    persist(job)
    return snapshot(job)


# ------------------------------------------------------------------ 道表与自动分配（fredw-92/G36）
# 项目方：“当 gpu 不做 image 的时候也可以转成 rendering video 啊”——卡不再固定成出图卡 / 视频卡，都能跑两类，按偏好和空闲分：
#   出图：先找空闲道，偏好 image 道（render_endpoints.json image.gpu，即 gpu33:0），没有就任意空闲道（含 gpu36）；都忙 → 排最短的队。
#   视频：任何空闲道都能接；image 道接视频前要确认出图队列是空的（没有排队的出图任务）；都忙 → 排非 image 道里最短的队。
#   image 道在跑视频时它不空闲 → 新出图任务自然改派到别的空闲道，不会排在一段 13 分钟的视频后面。
#   同一张卡一次一个任务（本模块按道串行，不变）。
# “忙”= 本 API 在这条道上有 queued / running 任务，或该 ComfyUI 的 /queue 里有别人的任务（LS / 夜间脚本直接投的）。
# 队长按预计秒数算（视频 ≈ 840 s、出图 ≈ 70 s，外部任务每个按 300 s），不是按个数。
reachable_fn: Callable[[str], dict] | None = None    # 测试换成假的：url -> {reachable, running?, pending?}
EXTERNAL_TASK_S = 300.0
IMAGE_KINDS = ("frame", "asset_gen", "scene", "scene_plate")


def _probe_url(url: str) -> dict:
    if reachable_fn is not None:
        return reachable_fn(url) or {}
    from ns_render import endpoints as EP
    return EP.probe(url)


def _kind_of(job: dict) -> str:
    return "video" if job.get("kind") == "video" else "image"


def lanes(probe: bool = True) -> list[dict]:
    """全部道（gpu33 + gpu36 …）的状态：[{gpu, id, server, label, url, reachable, ok, detail, image_pref, role,
    max_frames, activity: image|video|external|idle, status_text, queued, load_s, comfy_running, comfy_pending}]。
    探测并行（每个地址 15 s 缓存，ns_render.endpoints.probe）"""
    from concurrent.futures import ThreadPoolExecutor
    from ns_render import endpoints as EP
    ids = list(GPUS)
    img = EP.default_gpu("image")
    urls = {}
    for g in ids:
        try:
            urls[g] = comfy_url(g)
        except ValueError:
            continue
    probes: dict = {}
    if probe and urls:
        with ThreadPoolExecutor(max_workers=min(8, len(urls))) as ex:
            for g, res in zip(urls, ex.map(lambda u: _safe_probe(u), urls.values())):
                probes[g] = res
    with _jobs_guard:
        active = [dict(j) for j in _jobs.values() if j.get("state") in ("queued", "running")]
    out = []
    for g, url in urls.items():
        mine = [j for j in active if j.get("gpu") == g]
        run = next((j for j in mine if j.get("state") == "running"), None)
        pr = probes.get(g, {})
        c_run, c_pend = int(pr.get("running") or 0), int(pr.get("pending") or 0)
        external = max(0, c_run + c_pend - len(mine))
        load = sum(ETA_DEFAULT_S["video" if _kind_of(j) == "video" else "frame"] for j in mine) + external * EXTERNAL_TASK_S
        act = _kind_of(run) if run else ("image" if any(_kind_of(j) == "image" for j in mine) else
                                         "video" if mine else "external" if external else "idle")
        name = EP.lane_name(g)
        word = {"image": "正在出图", "video": "出视频", "external": "外部任务", "idle": "空闲"}[act]
        reach = bool(pr.get("reachable")) if probe else True
        out.append({"gpu": g, "id": name, "server": EP.server_of(g), "label": EP.lane_label(g), "url": url,
                    "reachable": reach, "ok": reach, "detail": pr.get("detail"), "image_pref": g == img,
                    "role": "image" if g == img else "any", "max_frames": EP.max_frames(g),
                    "activity": act, "status_text": f"{name} · {word}", "queued": len(mine),
                    "load_s": round(load, 1), "comfy_running": c_run, "comfy_pending": c_pend,
                    "vram_total_mb": pr.get("vram_total_mb"), "gpu_name": pr.get("gpu")})
    return out


def _safe_probe(url: str) -> dict:
    try:
        return _probe_url(url)
    except Exception as e:  # noqa: BLE001
        return {"reachable": False, "detail": str(e)[:200]}


def auto_pick_enabled() -> bool:
    """真客户端（或测试给了 reachable_fn）才自动分配；测试换了 client_factory 而没给探测 → 旧行为（默认道）"""
    return reachable_fn is not None or client_factory is _make_client


def pick_lane(kind: str, frames: int | None = None, lane_list: list[dict] | None = None):
    """自动选道。kind = "image" | "video"；frames = 视频帧数（只选 max_frames 够的道）。→ 道 id（int 或 "gpu36:n"）"""
    from ns_render import endpoints as EP
    kind = "video" if kind == "video" else "image"
    default = EP.default_gpu("image" if kind == "image" else "video")
    if lane_list is None and not auto_pick_enabled():
        return default
    lns = [ln for ln in (lane_list if lane_list is not None else lanes()) if ln.get("ok")]
    if not lns:
        return default
    order = {ln["gpu"]: i for i, ln in enumerate(lns)}
    idle = [ln for ln in lns if not ln.get("load_s")]
    if kind == "image":
        if idle:
            return sorted(idle, key=lambda ln: (not ln.get("image_pref"), order[ln["gpu"]]))[0]["gpu"]
        return min(lns, key=lambda ln: (ln.get("load_s") or 0, not ln.get("image_pref"), order[ln["gpu"]]))["gpu"]
    if frames:
        fit = [ln for ln in lns if int(ln.get("max_frames") or 0) >= int(frames)]
        lns = fit or lns
        idle = [ln for ln in idle if ln in lns]
    with _jobs_guard:
        images_waiting = any(j.get("state") == "queued" and _kind_of(j) == "image" for j in _jobs.values())
    others = [ln for ln in idle if not ln.get("image_pref")]
    if others:
        return others[0]["gpu"]
    if idle and not images_waiting:          # 出图道空闲且没有排队的出图任务 → 接视频
        return idle[0]["gpu"]
    pool = [ln for ln in lns if not ln.get("image_pref")] or lns
    return min(pool, key=lambda ln: (ln.get("load_s") or 0, order[ln["gpu"]]))["gpu"]


def resolve_lane(gpu, kind: str, frames: int | None = None):
    """接口里的 gpu 参数：None / "auto" → pick_lane；否则归一并校验（不合法 → ValueError）"""
    if gpu is None or (isinstance(gpu, str) and gpu.strip().lower() in ("", "auto")):
        return pick_lane(kind, frames)
    if gpu not in GPUS:
        raise ValueError(f"gpu 只能是 {GPUS}")
    return norm(gpu)


@router.get("/api/render/lanes")
def render_lanes():
    """全部渲染道（gpu33 + gpu36）的可达性与当前在做什么（顶栏胶囊用 status_text）"""
    return {"lanes": lanes(), "image_default": _default_lane_name("image"), "video_default": _default_lane_name("video")}


def _default_lane_name(eid: str) -> str:
    from ns_render import endpoints as EP
    return EP.lane_name(EP.default_gpu(eid))
