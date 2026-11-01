"""实时推送 + 分段进度（UIRSI 2026-11-01，总调度任务）。

项目方原话：“这个页面实时更新最新状态，我一直看着这个页面的对应素材是否更新，进度条等细节，这个页面应该自动刷新，
或者对应素材更新，自动更新该板块，用 flash 渐变来代表该区域更新了，进行中的，采取好看的进度条。”

  GET /api/events    SSE。服务端每 1.5 s 按 mtime 扫一遍（不装 watchdog），有变化就推一条：
                     {type: frame|lastframe|video|voice|asset|stage|job|cut, run, episode, shot, field, ts, seq}
                     · frame / lastframe / video ：data/renders/epNN/SK/takes.json 里该阶段的版本数 / 当前 / 定稿变了（field=new|active|lock）；
                       流水线出图 / 出视频目录（runs/<run>/images|video/**）有新文件 → field=draft
                     · stage ：runs/<run>/** 写作产物（P0–P4、run.json、决定记录）变了，field = 文件名
                     · voice ：config/voices.json、data/cache/tts（新合成的句子）
                     · asset ：data/assets 下的登记表（*.json，三层以内）
                     · job   ：任务队列（/api/jobs 同一份：旧渲染队列 + v1 任务）状态 / 进度变了
                     · cut   ：成片文件（data/episodes、data/ab/plan*）
                     首条为 {type:"hello"}；每 15 s 一条注释心跳；断线后浏览器按 retry 3 s 自动重连，带 Last-Event-ID 续传。
  GET /api/progress?run=series10_v1
                     每集 + 整季的分段进度：剧本 → 分镜 → 首帧 → 尾帧 → 视频 → 声音 → 成片，
                     每段 {done, total, running, failed, reasons[], eta_s}；数字与集摘要（/api/episodes/summary）同一口径：
                     首帧 = 有当前首帧的镜数，尾帧 = 有当前尾帧，视频 = 有当前视频；声音 = 本机已合成（缓存里有）的句数 / 全部句数；
                     成片 = 这一集有比最近一次换剧本更新的成片。
只读；不改任何生产数据。
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import threading
import time
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

REPO = Path(__file__).resolve().parents[3]
DATA = REPO / "data"
router = APIRouter(tags=["live"])
# 每次进程启动一个新 id：前端发现 boot 变了 = 后端重启过，重连后全量重取一次（PAGEWATCH PW-008）
BOOT = f"{int(time.time() * 1000):x}-{os.getpid()}"

SKIP_DIRS = {"_thumbs", "raw", "v1_snapshot", "prompts", "_preview", "__pycache__", "v2_hc_false_positive", "v2_pre_fixpass"}
SHOT_RE = re.compile(r"ep(\d{2,3})[-_]?S(\d{1,3})", re.I)
EP_RE = re.compile(r"(?:^|[/\\])ep(\d{2,3})(?:[/\\]|$)", re.I)
STAGE_TYPE = {"image": "frame", "last": "lastframe", "video": "video"}


# ----------------------------------------------------------------------------- 扫描器（单例线程）
VERSION: dict[str, int] = {}
_memo: dict[tuple, tuple[float, object]] = {}


def _cached(key: tuple, ttl: float, fn):
    """小缓存：key 里带相关事件类型的版本号（有事件就失效），另加 ttl 兜底"""
    hit = _memo.get(key)
    now = time.time()
    if hit and now - hit[0] < ttl:
        return hit[1]
    v = fn()
    _memo[key] = (now, v)
    if len(_memo) > 200:
        for k in sorted(_memo, key=lambda k: _memo[k][0])[:100]:
            _memo.pop(k, None)
    return v


class Watcher:
    def __init__(self, interval: float = 1.5, roots: dict | None = None):
        self.interval = interval
        self.roots = roots or {}
        self.lock = threading.Lock()
        self.events: list[dict] = []     # 环形缓冲（最近 500 条）
        self.seq = 0
        self.prev: dict[str, float] | None = None
        self.prev_takes: dict[str, dict] = {}
        self.prev_jobs: dict[str, tuple] = {}
        self.thread: threading.Thread | None = None
        self.last_scan = 0.0

    # -- 路径 --
    def _r(self, k: str, default: Path) -> Path:
        return Path(self.roots.get(k, default))

    def runs_dir(self) -> Path:
        return self._r("runs", DATA / "pipeline" / "runs")

    def renders_dir(self) -> Path:
        return self._r("renders", DATA / "renders")

    # -- 快照 --
    def _walk(self, root: Path, depth: int, out: dict[str, float], pred=None) -> None:
        if depth < 0 or not root.is_dir():
            return
        try:
            with os.scandir(root) as it:
                for e in it:
                    if e.name in SKIP_DIRS or e.name.startswith("."):
                        continue
                    if e.is_dir(follow_symlinks=False):
                        self._walk(Path(e.path), depth - 1, out, pred)
                    elif pred is None or pred(e.name):
                        try:
                            st = e.stat()
                            out[e.path] = st.st_mtime + st.st_size * 1e-9
                        except OSError:
                            pass
        except OSError:
            pass

    def snapshot(self) -> dict[str, float]:
        out: dict[str, float] = {}
        rd = self.renders_dir()
        if rd.is_dir():
            for ep in rd.iterdir():
                if ep.is_dir() and ep.name.startswith("ep"):
                    for sh in ep.iterdir():
                        p = sh / "takes.json"
                        try:
                            out[str(p)] = p.stat().st_mtime
                        except OSError:
                            pass
        rr = self.runs_dir()
        if rr.is_dir():
            for run in rr.iterdir():
                if run.is_dir():
                    self._walk(run, 5, out, lambda n: not n.endswith((".tmp", ".log", ".out", ".err", ".pid")))
        for k, p in (("voices", REPO / "config" / "voices.json"), ("tts", DATA / "cache" / "tts")):
            p = self._r(k, p)
            try:
                out[str(p)] = p.stat().st_mtime
            except OSError:
                pass
        self._walk(self._r("assets", DATA / "assets"), 2, out, lambda n: n.endswith(".json"))
        for k, p in (("episodes", DATA / "episodes"), ("ab", DATA / "ab")):
            self._walk(self._r(k, p), 2, out, lambda n: n.endswith(".mp4"))
        return out

    # -- 分类 --
    def classify(self, path: str) -> dict | None:
        p = Path(path)
        s = str(p).replace("\\", "/")
        m = SHOT_RE.search(p.name) or SHOT_RE.search(s)
        shot = f"ep{int(m.group(1)):02d}-S{int(m.group(2))}" if m else None
        em = EP_RE.search(s)
        ep = int(em.group(1)) if em else (int(m.group(1)) if m else None)
        rr = str(self.runs_dir()).replace("\\", "/")
        if s.startswith(rr + "/"):
            rest = s[len(rr) + 1:]
            run, _, sub = rest.partition("/")
            if sub.startswith("images/"):
                kind = "lastframe" if re.search(r"(last|尾)", p.name, re.I) else "frame"
                return {"type": kind, "run": run, "episode": ep, "shot": shot, "field": "draft"}
            if sub.startswith("video/"):
                return {"type": "video", "run": run, "episode": ep, "shot": shot, "field": "draft"}
            if sub.startswith("assets/"):
                return {"type": "asset", "run": run, "episode": ep, "shot": None, "field": p.name}
            return {"type": "stage", "run": run, "episode": ep, "shot": None, "field": p.name}
        if p.name == "voices.json" or s.endswith("/cache/tts"):
            return {"type": "voice", "run": None, "episode": None, "shot": None, "field": "voices" if p.name == "voices.json" else "tts"}
        if p.suffix == ".mp4":
            return {"type": "cut", "run": None, "episode": ep, "shot": None, "field": p.name}
        if p.suffix == ".json" and "/assets/" in s:
            return {"type": "asset", "run": None, "episode": None, "shot": None, "field": p.name}
        return None

    def _takes_state(self, path: Path) -> dict:
        try:
            d = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        out = {}
        for st in STAGE_TYPE:
            ts = [t for t in d.get("takes") or [] if t.get("stage") == st]
            out[st] = (len(ts), (d.get("active") or {}).get(st), (d.get("locked") or {}).get(st))
        return out

    def _takes_events(self, path: str) -> list[dict]:
        p = Path(path)
        m = re.search(r"ep(\d{2,3})[/\\]S(\d{1,3})[/\\]takes\.json$", path)
        if not m:
            return []
        shot = f"ep{int(m.group(1)):02d}-S{int(m.group(2))}"
        new = self._takes_state(p)
        old = self.prev_takes.get(path, {})
        self.prev_takes[path] = new
        evs = []
        for st, typ in STAGE_TYPE.items():
            a, b = old.get(st), new.get(st)
            if a == b:
                continue
            field = "new" if (b and (not a or b[0] > a[0])) else "active" if (not a or a[1] != (b or (0, None, None))[1]) else "lock"
            evs.append({"type": typ, "run": None, "episode": int(m.group(1)), "shot": shot, "field": field})
        return evs

    def _jobs(self) -> list[dict]:
        try:
            from ns_api.app import jobs as _jobs_fn  # noqa: PLC0415
            return _jobs_fn()
        except Exception:  # noqa: BLE001
            return []

    def _job_events(self) -> list[dict]:
        evs = []
        cur = {}
        for j in self._jobs():
            jid = str(j.get("id") or j.get("job_id"))
            sig = (j.get("state"), j.get("progress"), j.get("queue_pos"))
            cur[jid] = sig
            if self.prev_jobs.get(jid) != sig:
                shot = j.get("shot_id")
                m = SHOT_RE.search(shot or "")
                evs.append({"type": "job", "run": None, "episode": int(m.group(1)) if m else None, "shot": shot,
                            "field": str(j.get("state")), "stage": j.get("stage"), "job": jid})
        first = not self.prev_jobs and not evs
        self.prev_jobs = cur
        return [] if first else evs

    # -- 一轮 --
    def scan_once(self) -> list[dict]:
        snap = self.snapshot()
        evs: list[dict] = []
        if self.prev is None:          # 第一次只记基线（含 takes 状态），不推
            self.prev = snap
            for k in snap:
                if k.endswith("takes.json"):
                    self.prev_takes[k] = self._takes_state(Path(k))
            self.prev_jobs = {str(j.get("id") or j.get("job_id")): (j.get("state"), j.get("progress"), j.get("queue_pos")) for j in self._jobs()}
            return []
        changed = [k for k, v in snap.items() if self.prev.get(k) != v]
        self.prev = snap
        seen = set()
        for k in changed:
            if k.endswith("takes.json"):
                evs += self._takes_events(k)
                continue
            e = self.classify(k)
            if e:
                key = (e["type"], e.get("run"), e.get("episode"), e.get("shot"), e.get("field"))
                if key not in seen:
                    seen.add(key)
                    evs.append(e)
        evs += self._job_events()
        if evs:
            self.push(evs)
        return evs

    def push(self, evs: list[dict]) -> None:
        now = time.time()
        with self.lock:
            for e in evs:
                VERSION[e["type"]] = VERSION.get(e["type"], 0) + 1   # 进度里各段的缓存按事件类型失效
                self.seq += 1
                self.events.append({**e, "ts": round(now, 3), "seq": self.seq})
            del self.events[:-500]

    def since(self, seq: int) -> list[dict]:
        with self.lock:
            return [e for e in self.events if e["seq"] > seq]

    def _loop(self) -> None:
        while True:
            try:
                self.scan_once()
            except Exception:  # noqa: BLE001 — 扫描出错不影响接口
                pass
            self.last_scan = time.time()
            time.sleep(self.interval)

    def ensure(self) -> None:
        if self.thread and self.thread.is_alive():
            return
        self.thread = threading.Thread(target=self._loop, name="live-watcher", daemon=True)
        self.thread.start()


WATCHER = Watcher()


@router.get("/api/events")
async def events(request: Request):
    WATCHER.ensure()
    try:
        last = int(request.headers.get("last-event-id") or request.query_params.get("since") or 0)
    except ValueError:
        last = 0
    if not last:
        last = WATCHER.seq

    async def gen():
        nonlocal last
        yield "retry: 3000\n\n"
        yield f"event: hello\ndata: {json.dumps({'type': 'hello', 'seq': last, 'boot': BOOT, 'ts': time.time()})}\n\n"
        beat = time.time()
        while True:
            if await request.is_disconnected():
                return
            for e in WATCHER.since(last):
                last = e["seq"]
                yield f"id: {e['seq']}\ndata: {json.dumps({**e, 'boot': BOOT}, ensure_ascii=False)}\n\n"
            if time.time() - beat > 10:
                beat = time.time()
                # 真正的事件（不是 SSE 注释）：前端看门狗靠它判断连接还活着（PAGEWATCH PW-008）
                yield f"data: {json.dumps({'type': 'ping', 'seq': WATCHER.seq, 'boot': BOOT, 'ts': round(time.time(), 3)})}\n\n"
            await asyncio.sleep(0.5)

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# ----------------------------------------------------------------------------- 分段进度
SEGS = ["script", "board", "first", "last", "video", "voice", "cut"]
SEG_LABEL = {"script": "剧本", "board": "分镜", "first": "首帧", "last": "尾帧", "video": "视频", "voice": "声音", "cut": "成片"}
JOB_SEG = {"image": "first", "first": "first", "last": "last", "video": "video"}
_pcache: dict = {"key": None, "at": 0.0, "val": None}


def _seg() -> dict:
    return {"done": 0, "total": 0, "running": 0, "failed": 0, "reasons": [], "eta_s": None}


def _script_stages(run: str | None) -> dict[int, dict]:
    if not run:
        return {}
    try:
        from ns_api import story_runs as SR  # noqa: PLC0415
        d = SR._run_dir(run)
        s = SR._summary(d)
        running = s.get("status") in ("running", "queued")
        out = {}
        for x in s.get("series_eps") or []:
            out[int(x["ep"])] = {"P3": x["stages"].get("P3"), "P4": x["stages"].get("P4"), "running": running}
        return out
    except Exception:  # noqa: BLE001
        return {}


def _voice_counts(ep: dict) -> tuple[int, int]:
    try:
        from ns_api import shot_audio as SA  # noqa: PLC0415
        by = SA._resolved(ep)
        cache = SA._cache_dir()
        tot = done = 0
        for lines in by.values():
            for ln, vs, _cfg in lines:
                tot += 1
                if len(vs) == 1 and SA._clip(ln.text, vs[0], cache).is_file():
                    done += 1
        return done, tot
    except Exception:  # noqa: BLE001
        return 0, 0


def _cut_done(n: int) -> bool:
    try:
        from ns_api import cuts as C  # noqa: PLC0415
        return any(not c.get("old_script") for c in C.list_cuts(n).get("cuts") or [])
    except Exception:  # noqa: BLE001
        return False


def compute_progress(run: str | None, summary_eps: list[dict], jobs: list[dict], script: dict, now: float | None = None) -> dict:
    now = now or time.time()
    stages = _cached(("stages", run, VERSION.get("stage", 0)), 30, lambda: _script_stages(run))
    sc_eps = {int(e.get("number") or 0): e for e in script.get("episodes") or []}
    eps_out = []
    for e in summary_eps:
        n = int(e.get("number") or 0)
        shots = e.get("shots") or []
        ids = {s.get("id") for s in shots}
        seg = {k: _seg() for k in SEGS}
        st = stages.get(n) or {}
        for k, node in (("script", "P3"), ("board", "P4")):
            v = st.get(node)
            seg[k]["total"] = 1
            if v in ("ok", "unchecked", "reused"):
                seg[k]["done"] = 1
            elif v in ("needs_writer", "budget_stop", "error"):
                seg[k]["failed"] = 1
                seg[k]["reasons"].append("要返修" if v == "needs_writer" else "预算停" if v == "budget_stop" else "出错")
            elif st.get("running") and v not in (None, "pending"):
                seg[k]["running"] = 1
            elif not st and shots:      # 不是整季运行：剧本已导入画布就算有
                seg[k]["done"] = 1
        for k, f in (("first", "first_frame"), ("last", "last_frame_target"), ("video", "video")):
            seg[k]["total"] = len(shots)
            seg[k]["done"] = sum(1 for s in shots if s.get(f))
        # 任务：进行中 / 失败（失败只算还没有成品的镜头），ETA = 进行中 + 排队的剩余预计
        latest: dict[tuple, dict] = {}
        for j in jobs:
            sid = j.get("shot_id")
            if sid not in ids:
                continue
            k = JOB_SEG.get(str(j.get("stage") or ("video" if j.get("kind") == "video" else "")))
            if not k:
                continue
            key = (sid, k)
            if key not in latest or str(j.get("created_at") or "") > str(latest[key].get("created_at") or ""):
                latest[key] = j
        have = {(s.get("id"), k): bool(s.get(f)) for s in shots for k, f in (("first", "first_frame"), ("last", "last_frame_target"), ("video", "video"))}
        for (sid, k), j in latest.items():
            state = j.get("state")
            if state in ("queued", "running"):
                seg[k]["running"] += 1
                eta = j.get("eta_s")
                if eta:
                    left = float(eta)
                    if state == "running" and j.get("started_at"):
                        try:
                            started = time.mktime(time.strptime(str(j["started_at"])[:19], "%Y-%m-%dT%H:%M:%S"))
                            left = max(0.0, float(eta) - (now - started))
                        except ValueError:
                            pass
                    seg[k]["eta_s"] = round((seg[k]["eta_s"] or 0) + left, 1)
            elif state == "failed" and not have.get((sid, k)):
                err = str(j.get("error") or "没出成").splitlines()[0][:80]
                if INFRA_ERR.search(str(j.get("error") or "")):
                    # UIRSI r43（OVERVIEW_REDESIGN K4）：连不上 / API 重启中断是生产问题，进生产健康，不算内容进度的“失败”
                    seg[k]["infra_failed"] = seg[k].get("infra_failed", 0) + 1
                    continue
                seg[k]["failed"] += 1
                seg[k]["reasons"].append(f"{sid.split('-')[1]}：{err}")
        vd, vt = _cached(("voice", n, VERSION.get("voice", 0)), 30, lambda: _voice_counts(sc_eps.get(n) or {})) if sc_eps.get(n) else (0, 0)
        seg["voice"].update(done=vd, total=vt)
        seg["cut"].update(total=1, done=1 if _cached(("cut", n, VERSION.get("cut", 0)), 30, lambda: _cut_done(n)) else 0)
        eps_out.append({"episode": n, "title": e.get("title"), "segs": seg})
    tot = {k: _seg() for k in SEGS}
    for e in eps_out:
        for k in SEGS:
            a, b = tot[k], e["segs"][k]
            for f in ("done", "total", "running", "failed"):
                a[f] += b[f]
            a["reasons"] += [f"第 {e['episode']} 集 {r}" for r in b["reasons"]][: max(0, 8 - len(a["reasons"]))]
            if b["eta_s"] is not None:
                a["eta_s"] = round((a["eta_s"] or 0) + b["eta_s"], 1)
    _mark_regressions(eps_out, tot, now)
    return {"run": run, "labels": SEG_LABEL, "order": SEGS, "episodes": eps_out, "total": tot, "ts": round(now, 3)}


# 进度倒退要说明原因（PAGEWATCH PW-012：演员表一换，声音缓存按音色计，条子变短却没说为什么，项目方会以为丢数据）
_hw: dict[tuple, tuple[int, float]] = {}       # (集 / total, 段) → (见过的最高完成数, 时间)
REGRESS_KEEP_S = 1800                           # 说明保留 30 分钟（或补回到原来的数）
# r43（K4）：基础设施错误（连接被拒、超时、API 重启打断）不算内容失败
INFRA_ERR = re.compile(r"WinError 10061|actively refused|Connection refused|ConnectionRefused|timed out|URLError|RemoteDisconnected|API 重启|重启打断|重启中断")
# r43（K5）：r40 / r41 有意隔离旧剧本版本后数字变少，不算“倒退”
QUARANTINE_LOG = REPO / "data" / "_quarantine_20261102_oldscript" / "moves.jsonl"


def _why_down(seg: str) -> str:
    if seg == "voice":
        try:
            mt = (REPO / "config" / "voices.json").stat().st_mtime
            return f"演员表 / 音色 {time.strftime('%H:%M', time.localtime(mt))} 改了，这些句子要按新音色重配"
        except OSError:
            return "音色改了，这些句子要重配"
    if seg in ("first", "last", "video"):
        return "有版本被撤下 / 标了不要 / 换剧本后作废，要重出"
    if seg in ("script", "board"):
        return "写作产物被返修或重写"
    if seg == "cut":
        return "成片在换剧本后作废"
    return "数字变少了"


def _quarantined_since(t0: float) -> bool:
    """高点之后做过旧剧本版本隔离（moves.jsonl 比高点新）→ 这次减少是有意的"""
    try:
        return QUARANTINE_LOG.stat().st_mtime >= t0 - 5
    except OSError:
        return False


def _mark_regressions(eps_out: list[dict], tot: dict, now: float) -> None:
    rows = [((e["episode"],), e["segs"]) for e in eps_out] + [(("total",), tot)]
    for key, segs in rows:
        for k, v in segs.items():
            hk = key + (k,)
            hi, at = _hw.get(hk, (v["done"], now))
            if v["done"] >= hi:
                _hw[hk] = (v["done"], now)
                continue
            if now - at > REGRESS_KEEP_S:      # 太久之前的高点不再提（当作新基线）
                _hw[hk] = (v["done"], now)
                continue
            if k in ("first", "last", "video") and _quarantined_since(at):   # 有意隔离造成的减少：重设基线，不标 ↓
                _hw[hk] = (v["done"], now)
                continue
            v["regressed"] = {"from": hi, "to": v["done"], "reason": _why_down(k)}



def _live_run(summary_eps: list[dict]) -> str | None:
    """没指定 run 时：找画布里正式剧本对应的整季运行（集数和每集标题都对得上的、最新的那个）"""
    titles = [str(e.get("title") or "") for e in sorted(summary_eps, key=lambda e: int(e.get("number") or 0))]
    best = None
    root = DATA / "pipeline" / "runs"
    for d in sorted(root.iterdir(), key=lambda x: -x.stat().st_mtime) if root.is_dir() else []:
        try:
            p1 = json.loads((d / "P1_storyline.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        t1 = [str(x.get("title") or "") for x in sorted(p1.get("episodes") or [], key=lambda x: int(x.get("episode") or 0))]
        if t1 and t1 == titles:
            best = d.name
            break
    return best


@router.get("/api/progress")
def progress(run: str | None = None):
    now = time.time()
    if _pcache["key"] == run and now - _pcache["at"] < 1.0 and _pcache["val"]:
        return _pcache["val"]
    from ns_api.app import _summary_cache, jobs as _jobs_fn  # noqa: PLC0415
    data, _at = _summary_cache.get()
    try:
        script = json.loads((DATA / "import" / "script_v2.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        script = {}
    val = compute_progress(run or _live_run(data), data, _jobs_fn(), script, now)
    _pcache.update(key=run, at=now, val=val)
    return val
