"""
整集出片（fredw-92/EB）：把一集的镜头按镜头拆开，铺到所有渲染道（gpu33 GPU0/1/3 + gpu36 注册的道）并行出。

POST /api/episodes/{n}/produce  {stages:["first","last","video"], mode:"auto_lock"|"review", shots?:[..],
                                 tier_first?:"preview"|"final", force?:bool, by?}
  每镜一条链（DAG）：首帧 → 定稿（→ 定稿档版本，若要）→ 由定稿首帧出尾帧 → 定稿（→ 定稿档）→ 由定稿首尾帧出视频。
  mode=auto_lock：每阶段出完自动定稿，takes.json locked_by[stage] = {by:"auto", n, note:"自动测试定稿，待项目方复审"}
                  （n 与 locked[stage] 相同才算数；项目方在画布重新定稿后它自然失效）。
  mode=review：首帧 / 尾帧出完停下，等项目方在画布定稿（locked[stage] 变了）后自动接着走；视频出完不定稿。
  tier_first：帧的目标档。"final" = 首尾帧都要定稿档版本；"preview" = 只出预览档；不给 = render_quality.json auto_final_on_lock。
  force=true：本次 stages 里的阶段即使已定稿且不过期也重出（新版本，旧版本留在版本链里）；默认跳过“已定稿且不过期”的阶段。
  调度：任务进 ns_api.jobs 的共享按卡队列；本模块只在某道空闲（jobs 里该卡没有 queued / running）时给它派一个镜头的下一步，
  所以 N 个镜头自然铺满 N 条道。出图优先 image 道（render_endpoints.json image.gpu），任何空闲道也可接；视频任何空闲道。
  视频帧数 > 道的 max_frames（h3_video，LS 长镜头方案落地前 192）→ 该镜等待并写明原因，绝不截短。
  失败：隧道超时 / 连不上 / API 重启中断 等可恢复错误最多重试 2 次；OOM → 标记等待（等 LS 方案），不截短不重试。
GET  /api/episodes/{n}/produce   → 每镜每阶段进度、所在道、预计剩余（jobs.estimate 同口径的历史中位数）、失败
POST /api/episodes/{n}/produce/cancel

状态落盘 data/jobs/episodes/epNN.json；API 重启后（startup）自动接着跑（被重启打断的任务按可恢复错误重试）。
不做内容检测；提示词原样（出图 / 视频都走现有 frame-jobs / video-jobs 的同一函数）。
"""
from __future__ import annotations

import copy
import json
import statistics
import threading
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ns_api import jobs as J
from ns_render import pipeline as P

router = APIRouter(tags=["episode-produce"])

SCHEMA = "nsfs.episode_produce/v1"
STAGES = ("first", "last", "video")
ST = {"first": "image", "last": "last", "video": "video"}          # takes.json 的 stage 名
LABEL = {"first": "首帧", "last": "尾帧", "video": "视频"}
MODES = ("auto_lock", "review")
MAX_RETRY = 2                                   # 可恢复错误最多重试 2 次（共 3 次提交）
TICK_S = 3.0
FRESH_TTL_S = 20.0
AUTO_NOTE = "自动测试定稿，待项目方复审"
ACTIVE = ("pending", "ready", "queued", "running", "review")
TERMINAL = ("done", "skipped", "failed", "blocked", "cancelled")
TRANSIENT = ("超时", "timeout", "timed out", "连不上", "unavailable", "connection", "api 重启中断", "隧道",
             "502", "503", "504", "remote end closed", "reset by peer", "urlerror", "broken pipe", "任务记录丢失",
             "temporarily", "eof")
OOM = ("outofmemory", "out of memory", "显存不足", "oom：", "oom:")
ETA_DEFAULT = {"gen": 70.0, "final": 280.0, "video": 840.0}


def is_oom(err: str | None) -> bool:
    e = (err or "").lower().replace(" ", "") if err else ""
    return any(k.replace(" ", "") in e for k in OOM)


def is_transient(err: str | None) -> bool:
    e = (err or "").lower()
    return any(k in e for k in TRANSIENT)


# ------------------------------------------------------------------ 与系统其余部分的接口（测试换成假的）

class Hooks:
    """真实实现：出图 / 视频走 frame_jobs / video_jobs 的同一函数，进 jobs 的共享队列"""

    # ---- 道
    def lanes(self) -> list[dict]:
        """[{gpu, label, url, image_pref, max_frames, ok}]。G36 若在 jobs 里提供 lanes()（多服务器道表），优先用它"""
        from ns_render import endpoints as EP
        from ns_render import h3_video as HV
        g36 = getattr(J, "lanes", None)
        if callable(g36):
            try:
                out = []
                for ln in g36():
                    d = dict(ln)
                    d.setdefault("gpu", d.get("id"))
                    d.setdefault("max_frames", _lane_max(HV, d["gpu"]))
                    d.setdefault("image_pref", d.get("prefers") == "image" or d.get("role") == "image")
                    d.setdefault("label", f"GPU{d['gpu']}")
                    d.setdefault("ok", d.get("reachable", True) and not d.get("disabled"))
                    out.append(d)
                return out
            except Exception:  # noqa: BLE001  G36 的表读不到 → 退回本地道表
                pass
        img = EP.default_gpu("image")
        out = []
        for g in J.GPUS:
            try:
                url = J.comfy_url(g)
            except ValueError:
                continue
            pr = EP.probe(url)
            host = url.split("//", 1)[-1]
            out.append({"gpu": g, "label": f"GPU{g}（{host}）", "url": url, "image_pref": g == img,
                        "max_frames": _lane_max(HV, g), "ok": bool(pr.get("reachable"))})
        return out

    def busy(self, gpu) -> bool:
        """本 API 的任务队列里该卡有 queued / running；或该道 ComfyUI 自己的队列不空（别的会话直接往 gpu 上提交的，
        探测结果缓存 15 s）——不往别人正在用的卡上叠任务"""
        if any(j.get("gpu") == gpu and j.get("state") in ("queued", "running") for j in J.all_jobs()):
            return True
        try:
            from ns_render import endpoints as EP
            pr = EP.probe(J.comfy_url(gpu))
            return bool(pr.get("running") or pr.get("pending"))
        except Exception:  # noqa: BLE001
            return False

    # ---- 任务
    def submit(self, shot_id: str, stage: str, step: str, gpu, parent: int | None = None) -> dict:
        """→ job dict；不能提交（409 等）抛 Blocked(原因)"""
        from fastapi.responses import JSONResponse
        from ns_api import frame_jobs as FJ
        from ns_api import video_jobs as VJ
        try:
            if stage == "video":
                out = VJ.create_video_job(shot_id, VJ.VideoJobRequest(gpu=gpu))
            elif step == "final":
                out = FJ.submit_final(shot_id, ST[stage], parent=parent, gpu=gpu)
            else:
                out = FJ.create_frame_job(shot_id, FJ.FrameJobBody(stage=stage, mode="regen", gpu=gpu))
        except HTTPException as e:
            raise Blocked(str(e.detail))
        if isinstance(out, JSONResponse):
            try:
                raise Blocked(json.loads(out.body).get("detail") or "不能提交")
            except ValueError:
                raise Blocked("不能提交")
        return out

    def job(self, job_id: str) -> dict | None:
        return J.get(job_id)

    def cancel(self, job_id: str):
        try:
            J.job_cancel(job_id)
        except HTTPException:
            pass

    def pending(self, shot_id: str, kind: str) -> list[dict]:
        return J.pending(shot_id, kind)

    # ---- 版本 / 定稿
    def takes(self, shot_id: str) -> dict:
        return P.load_takes(shot_id)

    def lock(self, shot_id: str, stage: str, n: int, by: str, run_id: str):
        from ns_render import frame_edit as FE
        FE.lock(shot_id, ST[stage], n)
        self.mark(shot_id, stage, n, by, run_id)

    def mark(self, shot_id: str, stage: str, n: int, by: str, run_id: str):
        mark_locked_by(shot_id, ST[stage], n, by, run_id)
        _invalidate_summary()

    def fresh(self, shot_id: str) -> dict:
        """{image, last, video}: 已定稿（视频：当前版本）且画布不判过期"""
        from ns_api import app as A
        from ns_render import h3_video as HV
        d = A.shot(shot_id)
        tk = d.get("takes") or {}
        takes, lk, sm = tk.get("takes") or [], tk.get("locked") or {}, tk.get("stale") or {}
        act = tk.get("active") or {}

        def ok(stage, n):
            t = next((x for x in takes if x["stage"] == stage and x["n"] == n), None) if n is not None else None
            return bool(t) and not t.get("stale") and not sm.get(stage) and (P.DATA / t["file"]).is_file()
        vn = act.get("video")
        vt = next((x for x in takes if x["stage"] == "video" and x["n"] == vn), None) if vn is not None else None
        vok = ok("video", vn) and bool((vt.get("params") or {}).get("first")) and not HV.stale_reasons(vt, P.load_takes(shot_id))
        return {"image": ok("image", lk.get("image")), "last": ok("last", lk.get("last")), "video": vok}

    def video_frames(self, shot_id: str) -> int:
        from ns_api import app as A
        from ns_render import h3_video as HV
        from ns_schema.h3_lint import frames_for_seconds
        return frames_for_seconds(HV.shot_seconds(A._script, shot_id))

    def final_wanted(self, tier_first: str | None) -> bool:
        if tier_first in ("preview", "final"):
            return tier_first == "final"
        from ns_render import final_tier as FT
        return bool(FT.auto_final_on_lock())

    def episode_shots(self, n: int) -> list[str] | None:
        from ns_api import app as A
        ep = next((e for e in A._script.episodes if e.number == n), None)
        return None if ep is None else [s.id for s in ep.shots]

    def recent(self, kind: str, gpus) -> list[float]:
        out = []
        for g in gpus:
            out += J.recent_durations(kind, g)
        return out

    def now(self) -> float:
        return time.time()


def _lane_max(HV, gpu) -> int:
    """LS：每道一次能出的 H3 最大帧数 = ns_render.endpoints.max_frames(gpu)（config render_endpoints.json max_frames）"""
    from ns_render import endpoints as EP
    for f in (getattr(EP, "max_frames", None), getattr(HV, "lane_max_frames", None)):
        if callable(f):
            try:
                return int(f(gpu))
            except Exception:  # noqa: BLE001
                continue
    return int(HV.safe_max_frames())


def _invalidate_summary():
    try:
        from ns_api import app as A
        A._summary_cache.invalidate()
    except Exception:  # noqa: BLE001
        pass


def mark_locked_by(shot_id: str, stage: str, n: int, by: str, run_id: str | None = None):
    """takes.json locked_by[stage] = {by, n, at, note, run}；n ≠ locked[stage] 时（项目方后来重新定稿）视为失效"""
    with P.shot_lock(shot_id):
        data = P.load_takes(shot_id)
        data.setdefault("locked_by", {})[stage] = {"by": by, "n": n, "at": P.now(), "run": run_id,
                                                  **({"note": AUTO_NOTE} if by == "auto" else {})}
        P._save_takes(shot_id, data)


class Blocked(Exception):
    pass


# ------------------------------------------------------------------ 调度器

def _rec() -> dict:
    return {"state": "pending", "step": None, "job_id": None, "gpu": None, "lane": None, "take": None,
            "attempts": {}, "error": None, "reason": None, "own": [], "history": [], "started_at": None}


class Producer:
    def __init__(self, hooks: Hooks | None = None, root: Path | None = None, tick_s: float = TICK_S):
        self.h = hooks or Hooks()
        self._root = root
        self.tick_s = tick_s
        self.runs: dict[int, dict] = {}
        self.guard = threading.RLock()
        self._thread: threading.Thread | None = None
        self._fresh: dict[str, tuple[float, dict]] = {}
        self._fresh_tick: dict[str, dict] = {}

    # ---- 落盘
    def dir(self) -> Path:
        return self._root or (P.DATA / "jobs" / "episodes")

    def path(self, n: int) -> Path:
        return self.dir() / f"ep{n:02d}.json"

    def save(self, run: dict):
        run["updated_at"] = P.now()
        try:
            self.dir().mkdir(parents=True, exist_ok=True)
            P._write_json(self.path(run["episode"]), json.loads(json.dumps(run, ensure_ascii=False, default=str)))
        except OSError:
            pass

    def load(self, n: int) -> dict | None:
        with self.guard:
            if n in self.runs:
                return self.runs[n]
        try:
            d = json.loads(self.path(n).read_text(encoding="utf-8"))
            return d if isinstance(d, dict) and d.get("schema") == SCHEMA else None
        except (OSError, ValueError):
            return None

    def resume(self) -> list[int]:
        """API 启动：没跑完的整集出片读回来接着跑（jobs.restore 已把被打断的任务标 failed → 按可恢复错误重试）"""
        out = []
        d = self.dir()
        if not d.is_dir():
            return out
        for f in sorted(d.glob("ep*.json")):
            try:
                run = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if isinstance(run, dict) and run.get("schema") == SCHEMA and run.get("state") in ("running", "waiting"):
                run["resumed_at"] = P.now()
                self._event(run, None, None, "resume")
                with self.guard:
                    self.runs[int(run["episode"])] = run
                out.append(int(run["episode"]))
        if out:
            self.ensure_thread()
        return out

    # ---- 启动 / 取消
    def start(self, n: int, *, stages, mode: str, shots=None, tier_first=None, force=False, by=None) -> dict:
        if not stages or any(s not in STAGES for s in stages):
            raise HTTPException(422, "stages 只能是 first | last | video")
        stages = [s for s in STAGES if s in set(stages)]
        if mode not in MODES:
            raise HTTPException(422, "mode 只能是 auto_lock | review")
        if tier_first not in (None, "preview", "final"):
            raise HTTPException(422, "tier_first 只能是 preview | final")
        all_shots = self.h.episode_shots(n)
        if all_shots is None:
            raise HTTPException(404, "没有这一集")
        if shots:
            bad = [s for s in shots if s not in all_shots]
            if bad:
                raise HTTPException(422, f"不是第 {n} 集的镜头：{', '.join(bad)}")
            all_shots = [s for s in all_shots if s in set(shots)]
        with self.guard:
            cur = self.runs.get(n)
            if cur and cur.get("state") in ("running", "waiting"):
                raise HTTPException(409, f"第 {n} 集已有整集出片在跑（{cur['id']}），先取消再重新开始")
            run = {"schema": SCHEMA, "id": uuid.uuid4().hex[:10], "episode": n, "stages": stages, "mode": mode,
                   "tier_first": tier_first, "final_frames": self.h.final_wanted(tier_first), "force": bool(force),
                   "by": by or "canvas", "state": "running", "created_at": P.now(), "finished_at": None,
                   "shots": all_shots, "items": {s: {st: {**_rec(), "force": bool(force)} for st in stages}
                                                  for s in all_shots}, "events": []}
            self.runs[n] = run
            self._event(run, None, None, "start", stages=stages, mode=mode, shots=len(all_shots))
            self.save(run)
        self.ensure_thread()
        return self.view(n)

    def cancel(self, n: int) -> dict:
        with self.guard:
            run = self.load(n)
            if not run:
                raise HTTPException(404, "这一集没有整集出片")
            if run.get("state") in ("running", "waiting"):
                for sid, stg in run["items"].items():
                    for st, rec in stg.items():
                        if rec.get("job_id"):
                            self.h.cancel(rec["job_id"])
                        if rec["state"] not in ("done", "skipped", "failed"):
                            rec.update(state="cancelled", reason="已取消", job_id=None)
                run.update(state="cancelled", finished_at=P.now())
                self._event(run, None, None, "cancel")
                self.runs[n] = run
                self.save(run)
        return self.view(n)

    # ---- 后台线程
    def ensure_thread(self):
        with self.guard:
            if self._thread and self._thread.is_alive():
                return
            self._thread = threading.Thread(target=self._loop, daemon=True, name="ns-episode-produce")
            self._thread.start()

    def _loop(self):
        while True:
            try:
                alive = self.tick()
            except Exception:  # noqa: BLE001  调度器不退出
                alive = True
            if not alive:
                with self.guard:
                    self._thread = None
                return
            time.sleep(self.tick_s)

    # ---- 一拍
    def tick(self) -> bool:
        """推进所有在跑的整集出片一步；→ 还有没有在跑的"""
        with self.guard:
            if not any(r.get("state") in ("running", "waiting") for r in self.runs.values()):
                return False
        lanes = list(self.h.lanes())          # 探测可达性可能要几秒：不占锁（GET 进度不被卡住）
        with self.guard:
            runs = [r for r in self.runs.values() if r.get("state") in ("running", "waiting")]
            self._fresh_tick = {}
            ready: list[tuple[dict, str, str, dict]] = []
            for run in runs:
                for sid in run["shots"]:
                    for st in run["stages"]:
                        r = self._advance(run, sid, st, lanes)
                        if r:
                            ready.append((run, sid, st, r))
            self._dispatch(ready, lanes)
            for run in runs:
                self._finish_if_done(run)
                self.save(run)
            return any(r.get("state") in ("running", "waiting") for r in runs)

    def _fresh_of(self, sid: str) -> dict:
        c = self._fresh_tick.get(sid)
        if c is not None:
            return c
        hit = self._fresh.get(sid)
        if hit and self.h.now() - hit[0] < FRESH_TTL_S:
            v = hit[1]
        else:
            try:
                v = self.h.fresh(sid)
            except Exception:  # noqa: BLE001
                v = {"image": False, "last": False, "video": False}
            self._fresh[sid] = (self.h.now(), v)
        self._fresh_tick[sid] = v
        return v

    def _forget(self, sid: str):
        self._fresh.pop(sid, None)
        self._fresh_tick.pop(sid, None)

    def _event(self, run, sid, st, ev, **kw):
        run.setdefault("events", []).append({"t": P.now(), "shot": sid, "stage": st, "ev": ev, **kw})
        del run["events"][:-300]

    def _locked_take(self, sid: str, st: str):
        tk = self.h.takes(sid)
        n = (tk.get("locked") or {}).get(ST[st])
        t = next((x for x in tk.get("takes") or [] if x["stage"] == ST[st] and x["n"] == n), None) if n is not None else None
        return n, t, tk

    def _is_fresh(self, run, sid, st) -> bool:
        """已定稿（视频：当前版本）且不过期；本次自己出的版本（及其定稿档）直接算新"""
        rec = run["items"][sid].get(st) if st in run["items"][sid] else None
        own = set((rec or {}).get("own") or [])
        if st == "video":
            act = (self.h.takes(sid).get("active") or {}).get("video")
            if act is not None and act in own:
                return True
            return bool(self._fresh_of(sid).get("video"))
        n, t, _ = self._locked_take(sid, st)
        if n is None:
            return False
        if n in own or (t and t.get("mode") == "final" and t.get("parent") in own):
            return True
        return bool(self._fresh_of(sid).get(ST[st]))

    def _deps(self, run, sid, st) -> tuple[str, str | None]:
        """→ ("ok"|"wait"|"blocked", 原因)"""
        need = {"first": [], "last": ["first"], "video": ["first", "last"]}[st]
        for d in need:
            rec = run["items"][sid].get(d)
            if rec is not None:
                if rec["state"] in ("done", "skipped"):
                    continue
                if rec["state"] in ACTIVE or rec["state"] == "waiting":
                    return "wait", f"等{LABEL[d]}"
                return "blocked", f"{LABEL[d]}未完成（{rec.get('reason') or rec['state']}）"
            if not self._is_fresh(run, sid, d):
                return "blocked", f"{LABEL[d]}未定稿或已过期（本次不出{LABEL[d]}）"
        return "ok", None

    def _advance(self, run, sid, st, lanes) -> dict | None:
        """推进一个镜头的一个阶段；可以派活时返回 {step, parent?, frames?}"""
        rec = run["items"][sid][st]
        if rec["state"] in ("done", "skipped", "failed", "cancelled"):
            return None
        if rec.get("job_id"):
            j = self.h.job(rec["job_id"])
            state = (j or {}).get("state")
            if state in ("queued", "running"):
                if state == "running" and rec["state"] != "running":
                    rec["started_at"] = j.get("started_at") or P.now()
                rec["state"] = state
                rec["eta_s"] = j.get("eta_s")
                return None
            if state == "done":
                self._on_done(run, sid, st, rec, j)
            else:
                self._on_fail(run, sid, st, rec, j, lanes)
                if rec["state"] in ("failed", "waiting"):
                    return None
        dep, why = self._deps(run, sid, st)
        if dep != "ok":
            rec.update(state="pending" if dep == "wait" else "blocked", reason=why)
            return None
        if st == "video":
            return self._decide_video(run, sid, rec, lanes)
        return self._decide_frame(run, sid, st, rec)

    def _decide_frame(self, run, sid, st, rec) -> dict | None:
        n, t, _ = self._locked_take(sid, st)
        if rec.get("review_wait"):
            if n is not None and n != rec.get("lock_before"):
                rec["review_wait"] = False
                rec["own"] = sorted(set(rec["own"]) | {n})
                rec["locked_by"] = "owner"
                self._event(run, sid, st, "owner_locked", n=n)
            else:
                rec.update(state="review", reason=f"等项目方在画布定稿{LABEL[st]}（v{rec.get('take')}）")
                return None
        if not rec.get("force") and self._is_fresh(run, sid, st):
            if run["final_frames"] and t is not None and t.get("mode") != "final" \
                    and t.get("workflow") not in ("upload", "video_last_frame"):
                if self.h.pending(sid, "frame"):
                    rec.update(state="pending", reason="定稿档任务进行中（定稿时自动排的）")
                    return None
                if rec["attempts"].get("final", 0) > MAX_RETRY:
                    rec.update(state="failed", reason="定稿档多次失败")
                    return None
                rec.update(state="ready", step="final", reason=None)
                return {"step": "final", "parent": n}
            rec.update(state="done" if rec["history"] else "skipped", step=None,
                       reason=None if rec["history"] else "已定稿且不过期，跳过", take=n)
            return None
        if self.h.pending(sid, "frame"):
            rec.update(state="pending", reason="本镜已有出图任务在跑")
            return None
        rec.update(state="ready", step="gen", reason=None)
        return {"step": "gen"}

    def _decide_video(self, run, sid, rec, lanes) -> dict | None:
        if not rec.get("force") and self._is_fresh(run, sid, "video"):
            act = (self.h.takes(sid).get("active") or {}).get("video")
            rec.update(state="done" if rec["history"] else "skipped", step=None, take=act,
                       reason=None if rec["history"] else "视频已是当前定稿首尾帧出的，跳过")
            return None
        if self.h.pending(sid, "video"):
            rec.update(state="pending", reason="本镜已有视频任务在跑")
            return None
        need = self.h.video_frames(sid)
        oks = [ln for ln in lanes if ln.get("ok")]
        top = max((int(ln.get("max_frames") or 0) for ln in oks), default=0)
        rec["frames"] = need
        if not oks:
            rec.update(state="waiting", reason="没有可达的渲染道")
            return None
        if rec.get("oom") and top <= int(rec.get("oom_max") or 0):
            rec.update(state="waiting", reason=f"显存不足（OOM，{need} 帧）：等 LS 长镜头方案，不截短")
            return None
        if need > top:
            rec.update(state="waiting", reason=f"需 {need} 帧，所有道上限 {top} 帧：等 LS 长镜头方案，不截短")
            return None
        rec.update(state="ready", step="video", reason=None, oom=False)
        return {"step": "video", "frames": need}

    def _on_done(self, run, sid, st, rec, j):
        take = j.get("take_n") if j.get("take_n") is not None else j.get("take")
        if isinstance(take, dict):
            take = take.get("n")
        step = rec.get("step") or ("video" if st == "video" else "gen")
        rec["history"].append({"job_id": rec["job_id"], "step": step, "gpu": rec["gpu"], "state": "done",
                               "take": take, "wall_s": j.get("wall_s"), "started_at": j.get("started_at"),
                               "finished_at": j.get("finished_at")})
        rec.update(job_id=None, take=take, error=None, last_wall_s=j.get("wall_s"))
        if take is not None:
            rec["own"] = sorted(set(rec["own"]) | {int(take)})
        rec["force"] = False
        self._forget(sid)
        self._event(run, sid, st, "done", step=step, take=take, gpu=rec["gpu"], wall_s=j.get("wall_s"))
        if take is None:
            return
        if run["mode"] == "auto_lock":
            if step == "final":
                n, _, _ = self._locked_take(sid, st)
                if n == take:                      # 定稿档已接替定稿（父版本是定稿版）→ 记 by auto
                    self.h.mark(sid, st, take, "auto", run["id"])
                else:
                    self.h.lock(sid, st, take, "auto", run["id"])
            else:
                self.h.lock(sid, st, take, "auto", run["id"])
            rec["locked_by"] = "auto"
        elif st != "video" and step == "gen":
            n, _, _ = self._locked_take(sid, st)
            rec.update(review_wait=True, lock_before=n)

    def _on_fail(self, run, sid, st, rec, j, lanes):
        err = (j or {}).get("error") or ("任务记录丢失" if j is None else (j or {}).get("state") or "失败")
        state = (j or {}).get("state") or "failed"
        step = rec.get("step") or "gen"
        rec["history"].append({"job_id": rec["job_id"], "step": step, "gpu": rec["gpu"], "state": state,
                               "error": str(err)[:500]})
        rec.update(job_id=None, error=str(err)[:500])
        self._event(run, sid, st, "fail", step=step, gpu=rec["gpu"], error=str(err)[:300])
        if state == "cancelled":
            rec.update(state="cancelled" if run.get("state") == "cancelled" else "failed",
                       reason="任务被取消（画布 / 接口），不自动重出")
            return
        if is_oom(err):
            top = max((int(ln.get("max_frames") or 0) for ln in lanes if ln.get("ok")), default=0)
            rec.update(state="waiting", oom=True, oom_max=top,
                       reason=f"显存不足（OOM，{rec.get('frames') or '?'} 帧）：等 LS 长镜头方案，不截短")
            return
        if is_transient(err) and rec["attempts"].get(step, 0) <= MAX_RETRY:
            rec.update(state="pending", reason=f"可恢复错误，重试（第 {rec['attempts'].get(step, 0)} 次失败）")
            return
        rec.update(state="failed", reason=f"失败：{str(err)[:200]}")

    def _dispatch(self, ready, lanes):
        idle = [ln for ln in lanes if ln.get("ok") and not self.h.busy(ln["gpu"])]
        if not ready or not idle:
            return
        frames = [x for x in ready if x[3]["step"] != "video"]
        videos = [x for x in ready if x[3]["step"] == "video"]

        def fits(item, ln):
            return item[3]["step"] != "video" or int(item[3].get("frames") or 0) <= int(ln.get("max_frames") or 0)

        def give(pool, lns):
            for ln in list(lns):
                item = next((x for x in pool if fits(x, ln)), None)
                if item is None:
                    continue
                pool.remove(item)
                if self._submit(item, ln):
                    idle.remove(ln)
                    lns.remove(ln)
        # 1. 出图 → image 道；2. 视频 → 其余道（上限最大的道留给最长的镜头）；3. 剩下的空闲道谁都接
        give(frames, [ln for ln in idle if ln.get("image_pref")])
        videos.sort(key=lambda x: -int(x[3].get("frames") or 0))
        give(videos, sorted([ln for ln in idle if not ln.get("image_pref")], key=lambda ln: -int(ln.get("max_frames") or 0)))
        give(frames, list(idle))
        give(videos, list(idle))

    def _submit(self, item, ln) -> bool:
        run, sid, st, r = item
        rec = run["items"][sid][st]
        step = r["step"]
        before, _, _ = self._locked_take(sid, st) if st != "video" else (None, None, None)
        try:
            j = self.h.submit(sid, st, step, ln["gpu"], parent=r.get("parent"))
        except Blocked as e:
            rec.update(state="blocked", reason=str(e)[:300])
            self._event(run, sid, st, "blocked", reason=str(e)[:300])
            return False
        except Exception as e:  # noqa: BLE001  提交时连不上等 → 记一次失败，下拍重试
            rec["attempts"][step] = rec["attempts"].get(step, 0) + 1
            if rec["attempts"][step] > MAX_RETRY:
                rec.update(state="failed", reason=f"提交失败：{str(e)[:200]}", error=str(e)[:500])
            else:
                rec.update(state="pending", reason=f"提交失败，重试：{str(e)[:200]}")
            return False
        rec["attempts"][step] = rec["attempts"].get(step, 0) + 1
        rec.update(state="queued", job_id=j.get("job_id") or j.get("id"), gpu=ln["gpu"], lane=ln.get("label"),
                   step=step, reason=None, submitted_at=P.now(), eta_s=j.get("eta_s"), started_at=None,
                   lock_before=before if step == "gen" else rec.get("lock_before"))
        self._event(run, sid, st, "submit", step=step, gpu=ln["gpu"], job=rec["job_id"])
        return True

    def _finish_if_done(self, run):
        recs = [rec for stg in run["items"].values() for rec in stg.values()]
        if any(r["state"] in ACTIVE for r in recs):
            run["state"] = "running"
        elif any(r["state"] == "waiting" for r in recs):
            run["state"] = "waiting"
        elif run.get("state") in ("running", "waiting"):
            run.update(state="done", finished_at=P.now())
            self._event(run, None, None, "finish")

    # ---- 进度
    def _durations(self, lanes) -> dict:
        gpus = [ln["gpu"] for ln in lanes]
        out = dict(ETA_DEFAULT)
        try:
            fr = self.h.recent("frame", gpus)
            vd = self.h.recent("video", gpus)
        except Exception:  # noqa: BLE001
            fr, vd = [], []
        if fr:
            out["gen"] = statistics.median(fr)
            out["final"] = max(out["final"], 4 * out["gen"])
        if vd:
            out["video"] = statistics.median(vd)
        return out

    def _remaining(self, run, st, rec, per) -> float:
        if rec["state"] in TERMINAL or rec["state"] in ("waiting", "review"):
            return 0.0
        steps = ["video"] if st == "video" else (["gen", "final"] if run.get("final_frames") else ["gen"])
        cur = rec.get("step") if rec.get("step") in steps else steps[0]
        i = steps.index(cur)
        rem = sum(per[s] for s in steps[i + 1:])
        if rec["state"] == "running" and rec.get("started_at"):
            try:
                from datetime import datetime
                el = (datetime.now() - datetime.fromisoformat(str(rec["started_at"]))).total_seconds()
            except (ValueError, TypeError):
                el = 0.0
            rem += max(per[cur] * 0.1, per[cur] - el)
        else:
            rem += per[cur]
        return rem

    def view(self, n: int) -> dict:
        with self.guard:
            run = self.load(n)
            if not run:
                return {"episode": n, "state": "none", "shots": [], "lanes": [], "eta_s": 0}
            run = copy.deepcopy(run)
        try:
            lanes = self.h.lanes()
        except Exception:  # noqa: BLE001
            lanes = []
        per = self._durations(lanes) if run["state"] in ("running", "waiting") else dict(ETA_DEFAULT)
        shots, total, chain, failures = [], 0.0, 0.0, []
        lane_use: dict = {}
        for sid in run["shots"]:
            stg = run["items"][sid]
            srem = 0.0
            row = {"shot_id": sid, "stages": {}}
            for st in run["stages"]:
                rec = stg[st]
                rem = self._remaining(run, st, rec, per)
                srem += rem
                row["stages"][st] = {k: rec.get(k) for k in (
                    "state", "step", "job_id", "gpu", "lane", "take", "reason", "error", "attempts", "frames",
                    "locked_by", "started_at")}
                row["stages"][st]["eta_s"] = round(rem, 1)
                if rec["state"] in ("queued", "running") and rec.get("gpu") is not None:
                    lane_use.setdefault(rec["gpu"], []).append({"shot_id": sid, "stage": st, "state": rec["state"],
                                                                "step": rec.get("step")})
                if rec["state"] == "failed" or (rec["state"] == "waiting" and rec.get("oom")):
                    failures.append({"shot_id": sid, "stage": st, "state": rec["state"], "reason": rec.get("reason"),
                                     "error": rec.get("error")})
            row["eta_s"] = round(srem, 1)
            shots.append(row)
            total += srem
            chain = max(chain, srem)
        n_ok = max(1, sum(1 for ln in lanes if ln.get("ok")))
        eta = max(chain, total / n_ok) if run["state"] in ("running", "waiting") else 0.0
        counts: dict = {}
        for s in shots:
            for v in s["stages"].values():
                counts[v["state"]] = counts.get(v["state"], 0) + 1
        return {"episode": n, "id": run["id"], "state": run["state"], "mode": run["mode"], "stages": run["stages"],
                "tier_first": run.get("tier_first"), "final_frames": run.get("final_frames"), "force": run.get("force"),
                "by": run.get("by"), "created_at": run.get("created_at"), "finished_at": run.get("finished_at"),
                "updated_at": run.get("updated_at"), "eta_s": round(eta, 1), "counts": counts,
                "lanes": [{**{k: ln.get(k) for k in ("gpu", "label", "url", "image_pref", "max_frames", "ok")},
                           "busy_with": lane_use.get(ln.get("gpu"), [])} for ln in lanes],
                "shots": shots, "failures": failures, "events": run.get("events", [])[-30:],
                "durations": {k: round(v, 1) for k, v in per.items()}}


PRODUCER = Producer()


class ProduceBody(BaseModel):
    stages: list[str] = list(STAGES)
    mode: str = "auto_lock"
    shots: list[str] | None = None
    tier_first: str | None = None
    force: bool = False
    by: str | None = None


@router.post("/api/episodes/{n}/produce")
def produce(n: int, body: ProduceBody | None = None):
    b = body or ProduceBody()
    return PRODUCER.start(n, stages=b.stages, mode=b.mode, shots=b.shots, tier_first=b.tier_first,
                          force=b.force, by=b.by)


@router.get("/api/episodes/{n}/produce")
def produce_status(n: int):
    return PRODUCER.view(n)


@router.post("/api/episodes/{n}/produce/cancel")
def produce_cancel(n: int):
    return PRODUCER.cancel(n)


def resume_on_startup():
    try:
        PRODUCER.resume()
    except Exception:  # noqa: BLE001
        pass
