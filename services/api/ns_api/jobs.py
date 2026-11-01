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
        c.server_tag = srv
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


# ------------------------------------------------------------------ 分段进度与计时（IMGPERF 11-01）
# 项目方：“image rendering 肯定有 bugs，怎么这么慢”——画布只显示“渲染中 6:36”看不出卡在哪。任务记录里加两个字段：
#   job["progress"] = {stage, label, step, total, since}   当前阶段（界面显示“label · step/total”，不是光秒表）
#   job["timing"]   = {stages: [{stage, label, s}], gpu_s, total_s}   每段实际秒数；gpu_s = ComfyUI 执行耗时
# 阶段名（stage）固定：queued · lane_check · prepare · upload · comfy_queue · comfy_run · download · post · finish
STAGE_LABEL = {"queued": "排队", "lane_check": "检查训练锁", "prepare": "准备（编译提示词 / 参考图）",
               "upload": "上传参考图", "comfy_queue": "ComfyUI 排队", "comfy_run": "GPU 出图",
               "download": "下载结果", "post": "后处理 / 契约质检", "finish": "写入版本"}


_stage_t: dict = {}   # 任务 id → 当前阶段开始的 monotonic 时间（不进任务记录）


def progress(job: dict, stage: str, step: int | None = None, total: int | None = None,
             label: str | None = None, save: bool = True) -> None:
    """切换 / 更新当前阶段：同一阶段只更新 step；换阶段时把上一段的秒数记进 timing.stages"""
    now = time.monotonic()
    with _jobs_guard:
        cur = _stage_t.get(job.get("id"))
        prev = (job.get("progress") or {}).get("stage")
        if prev != stage:
            if cur is not None and prev:
                tm = job.setdefault("timing", {"stages": []})
                tm.setdefault("stages", []).append({"stage": prev, "label": STAGE_LABEL.get(prev, prev),
                                                     "s": round(now - cur, 1)})
            _stage_t[job.get("id")] = now
            since = P.now()
        else:
            since = (job.get("progress") or {}).get("since") or P.now()
        job["progress"] = {"stage": stage, "label": label or STAGE_LABEL.get(stage, stage),
                           "step": step, "total": total, "since": since}
    if save:
        persist(job)


def _close_timing(job: dict, wall_s: float) -> None:
    """任务结束：收尾最后一段，算 total_s；progress 清成终态"""
    now = time.monotonic()
    with _jobs_guard:
        cur, prev = _stage_t.pop(job.get("id"), None), (job.get("progress") or {}).get("stage")
        tm = job.setdefault("timing", {"stages": []})
        if cur is not None and prev:
            tm.setdefault("stages", []).append({"stage": prev, "label": STAGE_LABEL.get(prev, prev),
                                                 "s": round(now - cur, 1)})
        tm["total_s"] = wall_s
        job["progress"] = {"stage": job.get("state"), "label": {"done": "完成", "failed": "失败",
                                                                "cancelled": "已取消"}.get(job.get("state"), job.get("state")),
                           "step": None, "total": None, "since": P.now()}


def gpu_seconds(entry: dict) -> float | None:
    """ComfyUI /history 条目 → 执行耗时（execution_start → execution_success / error 的时间戳差，秒）"""
    try:
        ts = {m[0]: m[1].get("timestamp") for m in (entry.get("status") or {}).get("messages") or []}
        a, b = ts.get("execution_start"), ts.get("execution_success") or ts.get("execution_error")
        return round((b - a) / 1000.0, 1) if a is not None and b is not None else None
    except Exception:  # noqa: BLE001
        return None


RESTART_ERROR = "API 重启中断"
DATA_ROOT_CHANGED = "数据目录在排队期间变了（测试残留任务），没有执行"
_roots: dict = {}   # 任务 id → 提交时的 P.DATA（fredw-92/UXF1，见 _worker）
_in_worker: set = set()   # 正在 worker 线程里执行的任务 id（drain 只等这些；测试手工塞进 _jobs 的假任务不算）


def drain(timeout_s: float = 60.0) -> list[str]:
    """fredw-92/UXF1：测试收尾用（tests/conftest.py）——排队的任务取消、正在跑的等它结束，
    免得测试的 monkeypatch 撤掉后后台线程把结果写进真数据目录（ep02-S1 首帧 #5 坏图就是这么来的）。
    → 超时还没结束的任务 id"""
    deadline = time.monotonic() + timeout_s
    with _jobs_guard:
        for j in _jobs.values():
            if j.get("state") == "queued":
                j["cancel_requested"] = True
                j.update(state="cancelled", finished_at=P.now())
                _runs.pop(j["id"], None)
    while time.monotonic() < deadline:
        with _jobs_guard:
            busy = sorted(_in_worker)
        if not busy:
            return []
        time.sleep(0.02)
    return busy
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
    progress(job, "queued", save=False)
    with _jobs_guard:
        _runs[jid] = run
        _roots[jid] = P.DATA
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


_NS_KIND = {("frame", "first"): "first_frame", ("frame", "image"): "first_frame", ("frame", "last"): "last_frame",
            ("frame", "edit"): "edit", ("video", None): "video", ("asset_gen", None): "sheet"}


def _ns_tag(job: dict) -> dict | None:
    """本任务的 GPU 面板标签（ns_agent.comfy_tag.make 同格式）：agent ns_api、kind 按任务类型/阶段、集/镜按 shot_id"""
    import re
    from ns_agent import comfy_tag as CT
    kind, stage = job.get("kind"), job.get("stage")
    k = _NS_KIND.get((kind, stage)) or _NS_KIND.get((kind, None)) or (
        "first_frame" if kind == "frame" else "other")
    sid = str(job.get("shot_id") or "")
    m = re.search(r"ep(\d{1,3})[-_ ]?(S\d{1,3})", sid, re.I)
    label = " ".join(str(x) for x in (stage if kind == "frame" else None, job.get("mode")) if x) or None
    return CT.make("ns_api", k, episode=int(m.group(1)) if m else None, shot=m.group(2).upper() if m else (sid or None),
                   label=label, job=job.get("id"))


def _worker(gpu, q: "queue.Queue[str]"):
    while True:
        jid = q.get()
        with _jobs_guard:
            job, run, root = _jobs.get(jid), _runs.pop(jid, None), _roots.pop(jid, None)
            if not job or run is None or job["state"] != "queued":
                continue
            if root is not None and root != P.DATA:
                # fredw-92/UXF1：排队时和现在的数据目录不同（测试结束后残留的任务）→ 不执行，免得写进别的数据目录
                job.update(state="failed", error=DATA_ROOT_CHANGED, finished_at=P.now())
                continue
        progress(job, "lane_check", save=False)
        # IMGPERF（11-01）：出发前现读训练锁要经跳板 ssh，实测 10.4 s（d1669a7b6e0c 的 lane_check 段），每个任务都付。
        # 改成后台读：LOCK_WAIT_S 内读完 → 和原来一样在出发前拦；没读完 → 先做准备 / 上传，第一次向 ComfyUI 投图前
        # 等读完再拦（_gate_submit），GPU 上不会先跑起来。
        lock_box: dict = {}

        def _read_lock():
            try:
                lock_box["locked"] = lane_train_locked_now(gpu)
            except Exception:  # noqa: BLE001  道 id 解析不了等 → 不拦（后面照常报错）
                lock_box["locked"] = False
        lt = threading.Thread(target=_read_lock, daemon=True, name=f"ns-lockcheck-{jid}")
        lt.start()
        lt.join(LOCK_WAIT_S)
        locked = bool(lock_box.get("locked")) if not lt.is_alive() else False
        with _jobs_guard:
            if job["state"] != "queued":
                continue
            if locked:
                job.update(state="failed", finished_at=P.now(),
                           error=f"{TRAIN_LOCKED_ERR}：{gpu} 上有训练锁，未派出，请换道重提")
            else:
                job.update(state="running", started_at=P.now())
                _in_worker.add(jid)
        if locked:
            _close_timing(job, 0.0)
        else:
            progress(job, "prepare", save=False)
        persist(job)
        if locked:
            continue
        t0 = time.monotonic()
        try:
            client = client_factory(gpu)
            try:   # GPU 任务归属标签（K-OPS-G01）：客户端投 /prompt 时带 extra_data.ns_tag；打标签出错不影响任务
                client.ns_tag = _ns_tag(job)
            except Exception:  # noqa: BLE001
                pass
            if lt.is_alive():
                _gate_submit(client, lt, lock_box, gpu)
            out = run(client, job) or {}
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
            try:
                _close_timing(job, job["wall_s"])
            except Exception:  # noqa: BLE001
                pass
            persist(job)
            with _jobs_guard:
                _in_worker.discard(jid)
            _prune()


LOCK_WAIT_S = 1.0          # 训练锁读取在出发前最多同步等这么久，超过就转后台、投图前再等（_gate_submit）
LOCK_GATE_TIMEOUT_S = 60.0


class TrainLocked(Exception):
    pass


def _gate_submit(client, lt: threading.Thread, box: dict, gpu) -> None:
    """IMGPERF：客户端第一次 submit 前等训练锁读完；锁着 → 抛错（任务失败，原因带“训练锁”，EB 当可恢复错误重派）"""
    orig = client.submit
    state = {"ok": False}

    def submit(workflow, *a, **k):
        if not state["ok"]:
            lt.join(LOCK_GATE_TIMEOUT_S)
            if box.get("locked"):
                raise TrainLocked(f"{TRAIN_LOCKED_ERR}：{gpu} 上有训练锁，未派出，请换道重提")
            state["ok"] = True
        return orig(workflow, *a, **k)
    client.submit = submit


def wait_prompt(client, job: dict, prompt_id: str, timeout_s: float, poll_s: float = 3) -> dict:
    """等 ComfyUI 跑完；期间响应取消（只中断自己的 prompt，不碰 GPU 上别人的任务）"""
    job["prompt_id"] = prompt_id
    progress(job, "comfy_queue", save=False)
    persist(job)
    deadline = time.monotonic() + timeout_s
    running = False
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
            gs = gpu_seconds(entry)
            if gs is not None:   # IMGPERF：GPU 实际执行秒数（同一任务多次投图累加）
                with _jobs_guard:
                    tm = job.setdefault("timing", {"stages": []})
                    tm["gpu_s"] = round(float(tm.get("gpu_s") or 0) + gs, 1)
            if status.get("status_str") == "error":
                msgs = [m for m in status.get("messages", []) if m[0] == "execution_error"]
                raise ComfyError("执行失败: " + (msgs[0][1].get("exception_message", "") if msgs else "").strip()[:1000])
            if status.get("completed"):
                return entry
        elif not running:
            # IMGPERF：还没开始跑 → 看 /queue 自己排第几（ComfyUI 上别人的任务也算）；开始跑后不再查
            try:
                q = client._json("/queue")
                if any(len(x) > 1 and str(x[1]) == prompt_id for x in q.get("queue_running", [])):
                    running = True
                    progress(job, "comfy_run")
                else:
                    ahead = len(q.get("queue_running", []))
                    for x in q.get("queue_pending", []):
                        if len(x) > 1 and str(x[1]) == prompt_id:
                            break
                        ahead += 1
                    progress(job, "comfy_queue", step=ahead, label=f"ComfyUI 排队（前面 {ahead} 个）", save=False)
            except Exception:  # noqa: BLE001  进度是附加信息
                pass
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
    done = [j for j in _done_jobs() if j.get("kind") == kind and j.get("gpu") == gpu]
    return [float(j["wall_s"]) for j in done[:n]]


def _done_jobs() -> list[dict]:
    """内存 + 盘上最近 ETA_DISK_SCAN 个任务里已完成、wall_s ≥ ETA_MIN_WALL_S 的（新 → 旧）"""
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
    done = [j for j in seen.values() if j.get("state") == "done"
            and isinstance(j.get("wall_s"), (int, float)) and j["wall_s"] >= ETA_MIN_WALL_S]
    done.sort(key=lambda j: str(j.get("finished_at") or j.get("created_at") or ""), reverse=True)
    return done


def eta_table(lane_ids: list) -> dict:
    """fredw-92/UXF4（审查 N5）：画布“预计约 N”用的单次耗时——与 estimate() 同口径（同类同卡最近 5 次中位数，
    没有样本 = ETA_DEFAULT_S），一次扫盘算全部道。→ {kind: {道名: {per_s, samples}}}，kind = frame | video | asset_gen"""
    import statistics
    from ns_render import endpoints as EP
    key = tuple(map(str, lane_ids))
    hit = _eta_cache.get(key)
    if hit and time.monotonic() - hit[0] < ETA_TABLE_TTL_S:      # 扫盘 300 个文件：道表 15 s 轮询一次，缓存 30 s
        return hit[1]
    done = _done_jobs()
    out: dict = {}
    for kind in ("frame", "video", "asset_gen"):
        row = {}
        for g in lane_ids:
            ds = [float(j["wall_s"]) for j in done if j.get("kind") == kind and j.get("gpu") == g][:ETA_SAMPLES]
            per = statistics.median(ds) if ds else ETA_DEFAULT_S.get(kind, ETA_DEFAULT_S["frame"])
            row[EP.lane_name(g)] = {"per_s": round(per, 1), "samples": len(ds)}
        out[kind] = row
    _eta_cache.clear()
    _eta_cache[key] = (time.monotonic(), out)
    return out


ETA_TABLE_TTL_S = 30.0
_eta_cache: dict = {}
_per_cache: dict = {}


def per_job_s(kind: str) -> float:
    """IMGPERF：选道用的单个任务耗时 = 同类（不分道）最近 ETA_SAMPLES 次完成任务 wall_s 的中位数，没样本用默认；缓存 30 s"""
    import statistics
    kind = "video" if kind == "video" else "frame"
    hit = _per_cache.get(kind)
    if hit and time.monotonic() - hit[0] < ETA_TABLE_TTL_S:
        return hit[1]
    try:
        ds = [float(j["wall_s"]) for j in _done_jobs() if j.get("kind") == kind][:ETA_SAMPLES]
    except Exception:  # noqa: BLE001
        ds = []
    per = statistics.median(ds) if ds else ETA_DEFAULT_S[kind]
    _per_cache[kind] = (time.monotonic(), per)
    return per


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
            _close_timing(job, 0.0)
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
# 训练锁（fredw-92 定）：服务器上有 train.lock.gpuN 的卡不派活。gpu33 读 /root/.local/state/NS-Studio/，
# gpu36 读 /root/work/fredw/locks/；每台服务器一次 ssh 列目录，缓存 30 s；读不到按“无锁”处理并记日志
TRAIN_LOCK_DIRS = {"gpu33": "/root/.local/state/NS-Studio", "gpu36": "/root/work/fredw/locks"}
TRAIN_LOCK_TTL_S = 30.0
train_lock_fn: Callable[[str], set] | None = None    # 测试换成假的：server -> {被锁的卡号 int}
_train_cache: dict = {}
_train_guard = threading.Lock()
EXTERNAL_TASK_S = 300.0
NEVER_LANES = {("gpu33", 2)}   # 硬规则：gpu33 GPU2 永不派活（就算有人把它加进 render_endpoints.json）
IMAGE_KINDS = ("frame", "asset_gen", "scene", "scene_plate")


def _probe_url(url: str) -> dict:
    if reachable_fn is not None:
        return reachable_fn(url) or {}
    from ns_render import endpoints as EP
    return EP.probe(url)


# UIDEBUG（docs/uirsi/debug_wiring.md W-07）：GET /api/render/lanes 是顶栏 / 精修 / 场景页每 15 s 轮询的展示接口，
# 探测缓存（15 s）一过期就要经隧道现探 6 个地址（实测每个 2.4–4.4 s），整页加载时这个请求 4–10 s。
# 展示用“先给上次结果、后台刷新”（最旧 LANES_VIEW_STALE_S 秒）；提交任务时的选卡（pick_lane / resolve_lane）不走这里，照旧现探。
LANES_VIEW_STALE_S = 120.0
_view_probe_threads: dict = {}
_view_probe_guard = threading.Lock()


VIEW_PROBE_TIMEOUT_S = 3.0      # IMGPERF / PAGEWATCH：展示用探测的单地址超时（隧道正常时 < 1 s）
VIEW_FIRST_WAIT_S = 3.0         # 从没探过的地址：请求里最多等这么久（各道并行，所以整页也只等这么久）


def _view_probe(url: str) -> None:
    from ns_render import endpoints as EP
    try:
        EP.probe(url, timeout=VIEW_PROBE_TIMEOUT_S, ttl=0)
    except Exception:  # noqa: BLE001
        pass


def _probe_for_view(url: str) -> dict:
    """IMGPERF（11-01，PAGEWATCH：/api/render/lanes 10–14 s）：展示接口永远先给缓存、后台刷新（同 /api/render-backend）。
    原来缓存旧于 LANES_VIEW_STALE_S 就在请求里现探 6 个地址（每个经隧道 2–4 s，超时更久）。
    现在：过了 PROBE_TTL_S → 起后台探测（每个地址同一时间只有一个，single-flight），立即回上次结果并标 stale；
    从没探过 → 最多等 VIEW_FIRST_WAIT_S，还没结果就回 {reachable: False, probing: True}"""
    if reachable_fn is not None:            # 测试的假探测：照旧同步
        return _safe_probe(url)
    from ns_render import endpoints as EP
    hit = EP.peek(url)
    now = time.monotonic()
    if hit is not None and now - hit[0] < EP.PROBE_TTL_S:
        return {**hit[1], "cached": True, "age_s": round(now - hit[0], 1)}
    with _view_probe_guard:
        t = _view_probe_threads.get(url)
        if t is None or not t.is_alive():
            t = _view_probe_threads[url] = threading.Thread(target=_view_probe, args=(url,), daemon=True,
                                                            name=f"ns-lane-probe-{url[-5:]}")
            t.start()
    if hit is None:
        t.join(VIEW_FIRST_WAIT_S)
        hit = EP.peek(url)
        if hit is None:
            return {"url": url, "reachable": False, "probing": True, "detail": "正在探测"}
        now = time.monotonic()
    age = round(now - hit[0], 1)
    return {**hit[1], "cached": True, "age_s": age, "stale": age > LANES_VIEW_STALE_S, "refreshing": t.is_alive()}


def _ssh_train_locks(server: str) -> set:
    import subprocess
    d = TRAIN_LOCK_DIRS.get(server)
    if not d:
        return set()
    git_ssh = r"C:\Program Files\Git\usr\bin\ssh.exe"   # 与隧道同一个 ssh（读 ~/.ssh/config 的 ProxyJump）
    exe = git_ssh if os.path.exists(git_ssh) else "ssh"
    r = subprocess.run([exe, "-o", "BatchMode=yes", "-o", "ConnectTimeout=10", server,
                        f"ls -1A {d} 2>/dev/null; true"], capture_output=True, text=True, timeout=25,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if r.returncode != 0:
        raise RuntimeError((r.stderr or "").strip()[:200] or f"ssh rc={r.returncode}")
    return parse_train_locks(r.stdout)


def parse_train_locks(listing: str) -> set:
    """目录列表 → 被锁卡号。fredw-92：隐藏文件 .train.lock.gpuN 也算锁（训练方常用点开头的写法；
    2026-10-31 曾因 ls 不列隐藏文件，往 fredw-0b 训练中的 gpu33 GPU1 派了视频）；改名带后缀的（已释放）不算"""
    import re
    return {int(m.group(1)) for m in re.finditer(r"^\.?train\.lock\.gpu(\d+)$", listing, re.M)}


def train_locks(server: str, wait: bool = True) -> set:
    """该服务器上有训练锁的卡号（缓存 30 s）。读不到 → 空集（按无锁）+ 日志。
    wait=False（展示接口用）：从没读到过也不等 ssh，后台读、先回空集"""
    fn = train_lock_fn
    if fn is None:
        if client_factory is not _make_client:      # 测试换了客户端又没给锁读取 → 不去连真服务器
            return set()
        return _train_locks_async(server, wait=wait)
    now = time.monotonic()
    with _train_guard:
        hit = _train_cache.get(server)
        if hit and now - hit[0] < TRAIN_LOCK_TTL_S:
            return set(hit[1])
    locks = _read_locks(fn, server)
    with _train_guard:
        _train_cache[server] = (now, locks)
    return set(locks)


def _read_locks(fn, server: str) -> set:
    """读不到 → 沿用上次读到的锁（fredw-92 2026-10-31：原来按无锁处理，ssh 一抖就会往训练中的卡派活）；从没读到过才按无锁"""
    import logging
    try:
        return set(fn(server))
    except Exception as e:  # noqa: BLE001
        with _train_guard:
            hit = _train_cache.get(server)
        logging.getLogger("ns_api.jobs").warning("读不到 %s 的训练锁，沿用上次结果 %s：%s", server,
                                                 sorted(hit[1]) if hit else "（无，按无锁）", e)
        return set(hit[1]) if hit else set()


TRAIN_LOCKED_ERR = "训练锁"


def lane_train_locked_now(gpu) -> bool:
    """任务出发前现读一次该道所在服务器的训练锁（不走缓存，顺带刷新缓存）。
    fredw-92 2026-10-31：选道用的是后台刷新的缓存（可能旧到一两分钟），fredw-0b 20:41:14 上锁、
    EB 20:42:01 仍往 gpu33:1 派了视频 → 训练 OOM。出发前这一读是最后一道闸"""
    from ns_render import endpoints as EP
    fn = train_lock_fn
    if fn is None:
        if client_factory is not _make_client:      # 测试换了客户端又没给锁读取 → 不去连真服务器
            return False
        fn = _ssh_train_locks
    srv = EP.server_of(gpu)
    idx = gpu if isinstance(gpu, int) else int(str(gpu).split(":", 1)[1])
    locks = _read_locks(fn, srv)
    with _train_guard:
        _train_cache[srv] = (time.monotonic(), locks)
    return idx in locks


_train_threads: dict = {}


def _train_locks_async(server: str, wait: bool = True) -> set:
    """真服务器：ssh 经跳板一次约 5–15 s，不能卡住选卡 → 后台线程刷新，选卡用上次结果；
    第一次（还没有结果）最多等 20 s"""
    now = time.monotonic()
    with _train_guard:
        hit = _train_cache.get(server)
        if hit and now - hit[0] < TRAIN_LOCK_TTL_S:
            return set(hit[1])
        t = _train_threads.get(server)
        if t is None or not t.is_alive():
            def work():
                locks = _read_locks(_ssh_train_locks, server)
                with _train_guard:
                    _train_cache[server] = (time.monotonic(), locks)
            t = _train_threads[server] = threading.Thread(target=work, daemon=True, name=f"ns-trainlock-{server}")
            t.start()
    if hit is None and wait:
        t.join(20)
        with _train_guard:
            hit = _train_cache.get(server)
    return set(hit[1]) if hit else set()


def _kind_of(job: dict) -> str:
    return "video" if job.get("kind") == "video" else "image"


def lanes(probe: bool = True, view: bool = False) -> list[dict]:
    """全部道（gpu33 + gpu36 …）的状态：[{gpu, id, server, label, url, reachable, ok, detail, image_pref, role,
    max_frames, activity: image|video|external|idle, status_text, queued, load_s, comfy_running, comfy_pending}]。
    探测并行（每个地址 15 s 缓存，ns_render.endpoints.probe）；view=True（只给展示接口用）= 先用上次探测结果、后台刷新"""
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
            for g, res in zip(urls, ex.map(_probe_for_view if view else _safe_probe, urls.values())):
                probes[g] = res
    with _jobs_guard:
        active = [dict(j) for j in _jobs.values() if j.get("state") in ("queued", "running")]
    locks: dict = {}
    if probe:
        srvs = sorted({EP.server_of(g) for g in urls})
        with ThreadPoolExecutor(max_workers=max(1, len(srvs))) as ex:
            locks = dict(zip(srvs, ex.map(lambda s: train_locks(s, wait=not view), srvs)))
    out = []
    for g, url in urls.items():
        mine = [j for j in active if j.get("gpu") == g]
        run = next((j for j in mine if j.get("state") == "running"), None)
        pr = probes.get(g, {})
        c_run, c_pend = int(pr.get("running") or 0), int(pr.get("pending") or 0)
        external = max(0, c_run + c_pend - len(mine))
        # IMGPERF：每个任务按“同类最近实测耗时中位数”算（原来出图固定 70 s，实测 300–860 s → 出图卡看起来永远不忙）
        load = sum(per_job_s("video" if _kind_of(j) == "video" else "frame") for j in mine) + external * EXTERNAL_TASK_S
        act = _kind_of(run) if run else ("image" if any(_kind_of(j) == "image" for j in mine) else
                                         "video" if mine else "external" if external else "idle")
        name = EP.lane_name(g)
        srv = EP.server_of(g)
        idx = g if isinstance(g, int) else int(str(g).split(":", 1)[1])
        locked = (probe and idx in locks.get(srv, set())) or (srv, idx) in NEVER_LANES
        if locked and act == "idle":
            act = "train"
        word = {"image": "正在出图", "video": "出视频", "external": "外部任务", "idle": "空闲", "train": "训练占用"}[act]
        reach = bool(pr.get("reachable")) if probe else True
        hold = EP.held(g)                  # LOCALGPU：道就绪但等总调度开派 → 不算 ok（自动选道 / 整集制作都不派）
        if hold and act == "idle":
            word = "待开派"
        out.append({"gpu": g, "id": name, "server": EP.server_of(g), "label": EP.lane_label(g), "url": url,
                    "reachable": reach, "ok": reach and not locked and not hold, "train_locked": bool(locked),
                    "image_only": EP.image_only(g), "hold": hold,
                    "detail": pr.get("detail"), "image_pref": g == img,
                    "role": "image" if g == img else "long" if EP.long_only(g) else "any",
                    "max_frames": EP.max_frames(g), "long_only": EP.long_only(g),
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
    lns = [ln for ln in (lane_list if lane_list is not None else lanes()) if ln.get("ok") and not ln.get("hold")]
    if kind == "video":                       # LOCALGPU：image_only 道（laptop:0）不接视频
        lns = [ln for ln in lns if not (ln.get("image_only") or EP.image_only(ln.get("gpu")))]
    # fredw-92/LS：long_only 道（gpu36:2 --novram）只接别的道一次出不了的长视频；出图、短视频不派过去
    short = [ln for ln in lns if not ln.get("long_only")]
    if kind == "image" or not frames or any(int(ln.get("max_frames") or 0) >= int(frames) for ln in short):
        lns = short
    if not lns:
        return default
    order = {ln["gpu"]: i for i, ln in enumerate(lns)}
    idle = [ln for ln in lns if not ln.get("load_s")]
    if kind == "image":
        # IMGPERF（11-01，项目方“怎么这么慢”）：自动 = 最空的道。原规则“出图卡上不超过两张图的活就仍用出图卡”
        # 按每张 70 s 算，实测每张 300–860 s，三张图全排在 gpu33:0 后面而 gpu33:1/:3、gpu36:0 空着。
        # 现在：有空闲道 → 空闲道（出图卡优先）；都忙 → 预计等待最短的道（同分偏好出图卡）。
        # 冷道换模型约 1 分钟，远小于排在一张图后面的等待，所以不再为“模型常驻”而排队
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
    g = norm(gpu)
    from ns_render import endpoints as EP
    if (EP.server_of(g), g if isinstance(g, int) else int(str(g).split(":", 1)[1])) in NEVER_LANES:
        raise ValueError(f"{EP.lane_name(g)} 永不派活（硬规则）")
    if kind == "video" and EP.image_only(g):
        raise ValueError(f"{EP.lane_name(g)} 只出图（image_only），不接视频")
    return g


@router.get("/api/render/lanes")
def render_lanes():
    """全部渲染道（gpu33 + gpu36）的可达性与当前在做什么（顶栏胶囊用 status_text）。
    只读展示：可达性用上次探测结果（后台刷新，见 _probe_for_view）；队列 / 活动每次现算"""
    lns = lanes(view=True)
    # fredw-92/UXF4（审查 N5 / N7）：“自动”现在会落到哪条道（与提交时同一个 pick_lane）+ 每条道的单次预计（jobs.estimate 同口径）
    auto = {}
    for kind in ("image", "video"):
        try:
            g = pick_lane(kind, lane_list=lns) if lns else None
        except Exception:  # noqa: BLE001
            g = None
        auto[kind] = g
    try:
        eta = eta_table([ln["gpu"] for ln in lns])
    except Exception:  # noqa: BLE001
        eta = {}
    return {"lanes": lns, "image_default": _default_lane_name("image"), "video_default": _default_lane_name("video"),
            "auto": auto, "eta": eta, "eta_default": ETA_DEFAULT_S}


def _default_lane_name(eid: str) -> str:
    from ns_render import endpoints as EP
    return EP.lane_name(EP.default_gpu(eid))
