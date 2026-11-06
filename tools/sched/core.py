"""SCHED-CORE（11-06）：跨两台服务器的全局 GPU 工作板（lease board）。

背景：今天慢的根因是 5–6 个各自为政的调度器（每台一个 producer 出图、每台 night + vidgen 出视频、笔记本 asset_worker、
lane_relay、video_shard）靠 hold / yield / 分片互相让道 → 卡空转、模型来回切、重复 / 过期活。
目标（L-205）：一集 ≤ 50 min；（L-206）一卡一模型、少切换；（L-207）首尾帧 → 全卡视频 → 合成 → 下一集。

本文件 = 纯算法 + 状态（不碰 producer / night / vidgen，不连服务器）：
  · 任务 DAG：资产(face/sheet/scene) → first(镜) → last(镜) → video(镜) → assembly(集)；按镜判就绪（L-202）；
    首帧换代（regen）使下游 last / video / assembly 失效（版本号 +1，旧结果到达即丢弃）。
  · 道池：gpu33:0/1/3 + gpu36:0/1/2（gpu33:2 坏卡永不出现），每道 loaded_model（image/video/vqa/none）、容量 1、健康。
  · 拉式派单：道空了来问“下一个做什么”——在 (任务, 道) 对上取 argmax [ rank − cost ]：
      rank = HEFT 向上秩（本任务及其下游的关键路径剩余时间，EWMA 估计 × 期望尝试次数）− 集序惩罚（早的集优先）
      cost = 本道预计耗时 + 换模型代价（道上已载模型 == 任务模型 则 0）
    看图 / 打分走独立队列，由 VQA 工位消费；出图 / 视频道从不等打分。
  · 状态：blocked / ready / leased / running / scoring / passed / failed / best_effort / adopted；
    尝试 ≤ max_attempts（默认 3）后自动采用最好一版（L-196 / L-204）→ 下游放行；租约 TTL + 心跳，超时换道重排；
    事件带 id、幂等（重放安全）；单写者；状态可 JSON 序列化、确定性（同输入同输出）。
  · ETA：对 50 min KPI 的剩余时间估计。
接入方式见 tools/sched/README.md。配置 config/pipeline/sched.json（enabled 默认 false）。
"""
from __future__ import annotations

import json
import os
from collections import deque
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG = ROOT / "config/pipeline/sched.json"

BAD_LANES = ("gpu33:2",)                      # 坏卡（CLAUDE.md 红线 / L-194）
KINDS = ("face", "sheet", "scene", "first", "last", "video", "assembly")
MODEL_OF = {"face": "image", "sheet": "image", "scene": "image", "first": "image", "last": "image",
            "video": "video", "assembly": "cpu"}
SCORED_KINDS = {"first": "image", "last": "image", "video": "video"}     # 出完要打分的类型 → 打分模型
DONE = ("passed", "adopted")
ACTIVE = ("leased", "running", "scoring")
STATES = ("blocked", "ready", "leased", "running", "scoring", "passed", "failed", "best_effort", "adopted")


class SchedError(ValueError):
    pass


DEFAULT_CONFIG = {
    "enabled": False,
    "kpi": {"episode_s": 3000},
    "lanes": {"gpu33:0": {"host": "gpu33", "speed": 1.0}, "gpu33:1": {"host": "gpu33", "speed": 1.0},
              "gpu33:3": {"host": "gpu33", "speed": 1.0, "vqa_slots": 3},
              "gpu36:0": {"host": "gpu36", "speed": 1.25}, "gpu36:1": {"host": "gpu36", "speed": 1.25},
              "gpu36:2": {"host": "gpu36", "speed": 1.25}},
    "switch_penalty_s": {"image->video": 90, "video->image": 90, "none->image": 60, "none->video": 90,
                         "vqa->image": 60, "vqa->video": 90, "image->vqa": 45, "video->vqa": 45},
    "duration_prior_s": {"first": 310, "last": 310, "video": 410, "assembly": 360, "face": 120, "sheet": 180, "scene": 200},
    "score_prior_s": {"image": 90, "video": 65},
    "expected_attempts": {"first": 2.4, "last": 1.9, "video": 1.4},
    "ewma_alpha": 0.3,
    "policies": {"max_attempts": 3, "auto_adopt": True, "phase_gate": "strict", "assets_bypass_phase_gate": True,
                 "episode_order_penalty_s": 100000, "lease_ttl_s": 1500, "score_lease_ttl_s": 600, "heartbeat_s": 30,
                 "lane_stale_s": 120, "lane_down_after_timeouts": 2, "requeue_avoid_same_lane": True},
}


def load_config(path: Path | None = None) -> dict:
    """读配置；缺文件 / 坏 JSON → 默认值（enabled=false，等于没开），并剔除坏卡"""
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))
    p = path or CONFIG
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):  # arch-ok: 配置缺失 = 默认关（enabled=false），调用方按 enabled 判断
        raw = {}
    for k, v in raw.items():
        if k.startswith("_"):
            continue
        if isinstance(v, dict) and isinstance(cfg.get(k), dict):
            cfg[k].update({kk: vv for kk, vv in v.items() if not str(kk).startswith("_")})
        else:
            cfg[k] = v
    for bad in BAD_LANES:
        cfg["lanes"].pop(bad, None)
    return cfg


def task_id(kind: str, ep: int, shot: str | None = None, name: str | None = None) -> str:
    if kind in ("first", "last", "video"):
        return f"{kind}:ep{ep:02d}-{shot}"
    if kind == "assembly":
        return f"assembly:ep{ep:02d}"
    return f"{kind}:{name}"


class Board:
    """全局工作板。单写者：所有改动走 apply(event) 或下面的方法（方法内部也产生事件 id 去重）。"""

    def __init__(self, cfg: dict | None = None):
        self.cfg = cfg or load_config()
        self.pol = self.cfg["policies"]
        self.tasks: dict[str, dict] = {}
        self.lanes: dict[str, dict] = {}
        self.ewma: dict[str, float] = {}
        self.score_queue: list[str] = []
        self.seen: deque = deque(maxlen=20000)
        self._seen_set: set[str] = set()
        self.seq = 0
        self.rev = 0                      # 任何状态改动 +1（rank 缓存失效）
        self._rank_cache: tuple = (-1, {})
        self.log: deque = deque(maxlen=2000)
        for lid, spec in self.cfg.get("lanes", {}).items():
            if lid.startswith("_"):
                continue
            self.add_lane(lid, **spec)
        if not any(l_["allow_models"] and "cpu" in l_["allow_models"] for l_ in self.lanes.values()):
            self.add_lane("cpu:0", host="cpu", allow_models=["cpu"], loaded_model="cpu")   # 合成在 CPU（不占卡）

    def gpu_lanes(self) -> list:
        return [l_ for l_ in sorted(self.lanes.values(), key=lambda x: x["id"]) if not (l_["allow_models"] == ["cpu"])]

    # ---------------- 道 ----------------
    def add_lane(self, lane_id: str, host: str | None = None, speed: float = 1.0, vqa_slots: int = 0,
                 render_capacity: int = 1, allow_models: list | None = None, loaded_model: str = "none") -> dict:
        if lane_id in BAD_LANES:
            raise SchedError(f"坏卡 {lane_id} 永不入道池（L-194 / CLAUDE.md）")
        lane = {"id": lane_id, "host": host or lane_id.split(":")[0], "speed": float(speed), "loaded_model": loaded_model,
                "render_capacity": int(render_capacity), "vqa_slots": int(vqa_slots), "allow_models": allow_models,
                "health": "ok", "busy": None, "vqa_busy": [], "last_seen": None, "timeouts": 0, "switches": 0,
                "busy_s": 0.0, "vqa_busy_s": 0.0}
        self.lanes[lane_id] = lane
        return lane

    def set_lane_role(self, lane_id: str, render_capacity: int | None = None, vqa_slots: int | None = None,
                      allow_models: list | None = "keep", loaded_model: str | None = None, health: str | None = None,
                      event_id: str | None = None) -> None:
        """工位角色（L-206/L-207 两段：首尾帧阶段 gpu33:3 只审图 3 实例；视频阶段改出视频 + 1 实例）"""
        if event_id and not self._first(event_id):
            return
        lane = self.lanes[lane_id]
        if render_capacity is not None:
            lane["render_capacity"] = int(render_capacity)
        if vqa_slots is not None:
            lane["vqa_slots"] = int(vqa_slots)
        if allow_models != "keep":
            lane["allow_models"] = allow_models
        if loaded_model is not None:
            lane["loaded_model"] = loaded_model
        if health is not None:
            lane["health"] = health

    def lane_seen(self, lane_id: str, now: float, loaded_model: str | None = None) -> None:
        lane = self.lanes[lane_id]
        lane["last_seen"] = now
        if loaded_model:
            lane["loaded_model"] = loaded_model
        if lane["health"] == "down" and lane["timeouts"] == 0:
            lane["health"] = "ok"

    def lane_free(self, lane: dict, now: float | None = None) -> bool:
        if lane["health"] != "ok" or lane["busy"] is not None or lane["render_capacity"] <= 0:
            return False
        stale = self.pol.get("lane_stale_s")
        if now is not None and stale and lane["last_seen"] is not None and now - lane["last_seen"] > stale:
            return False
        return True

    # ---------------- 任务 / DAG ----------------
    def add_task(self, tid: str, kind: str, ep: int, shot: str | None = None, deps: list | None = None,
                 hold: str | None = None, est_s: float | None = None, max_attempts: int | None = None) -> dict:
        if kind not in KINDS:
            raise SchedError(f"未知任务类型 {kind}")
        if tid in self.tasks:
            return self.tasks[tid]
        t = {"id": tid, "kind": kind, "ep": int(ep), "shot": shot, "model": MODEL_OF[kind], "deps": list(deps or []),
             "state": "blocked", "attempts": 0, "max_attempts": int(max_attempts or self.pol["max_attempts"]),
             "version": 1, "lease": None, "score_lease": None, "hold": hold, "best": None, "results": [],
             "est_s": est_s, "avoid_lanes": [], "t_ready": None, "t_done": None, "last_lane": None}
        self.tasks[tid] = t
        self.rev += 1
        return t

    def add_shot(self, ep: int, shot: str, assets: list | None = None, hold: str | None = None, video: bool = True) -> list:
        """一镜三任务：first → last → video；资产边：每个资产 → first（按镜判就绪，L-202）"""
        a = list(assets or [])
        f = self.add_task(task_id("first", ep, shot), "first", ep, shot, deps=a, hold=hold)
        l_ = self.add_task(task_id("last", ep, shot), "last", ep, shot, deps=[f["id"]] + a)
        out = [f, l_]
        if video:
            out.append(self.add_task(task_id("video", ep, shot), "video", ep, shot, deps=[f["id"], l_["id"]]))
        return out

    def add_asset(self, kind: str, name: str, ep: int, deps: list | None = None) -> dict:
        return self.add_task(task_id(kind, ep, name=name), kind, ep, deps=deps)

    def add_assembly(self, ep: int) -> dict:
        vids = [t["id"] for t in self.tasks.values() if t["ep"] == ep and t["kind"] == "video"]
        return self.add_task(task_id("assembly", ep), "assembly", ep, deps=vids)

    def succs(self, tid: str) -> list:
        return [t["id"] for t in self.tasks.values() if tid in t["deps"]]

    def is_done(self, tid: str) -> bool:
        return self.tasks[tid]["state"] in DONE

    def episode_phase(self, ep: int) -> str:
        ts = [t for t in self.tasks.values() if t["ep"] == ep]
        if not ts:
            return "none"
        if all(t["state"] in DONE for t in ts):
            return "done"
        if any(t["kind"] in ("first", "last") and t["state"] not in DONE for t in ts):
            return "frames"
        if any(t["kind"] == "video" and t["state"] not in DONE for t in ts):
            return "videos"
        return "assembly"

    def _episodes(self) -> list:
        return sorted({t["ep"] for t in self.tasks.values()})

    def _phase_gate_ok(self, t: dict, idle_fill: bool = False) -> bool:
        """L-207：下一集的首尾帧要等本集视频全部落定。strict / fill_idle / off"""
        mode = self.pol.get("phase_gate", "strict")
        if mode == "off" or t["kind"] in ("assembly",):
            return True
        if t["kind"] in ("face", "sheet", "scene") and self.pol.get("assets_bypass_phase_gate", True):
            return True
        for ep in self._episodes():
            if ep >= t["ep"]:
                break
            ph = self.episode_phase(ep)
            if ph in ("frames", "videos"):
                if t["kind"] == "video" and ph == "videos":
                    continue                 # 上集已在视频阶段：本集视频可以并入（视频同模型，不抢首尾帧）
                return bool(idle_fill and mode == "fill_idle")
        return True

    def refresh(self, now: float) -> None:
        """blocked → ready（依赖齐 + 不在 hold）；ready → blocked（依赖被换代）"""
        for t in sorted(self.tasks.values(), key=lambda x: x["id"]):
            if t["state"] in ("blocked", "ready"):
                ok = all(self.is_done(d) for d in t["deps"]) and not t["hold"]
                if ok and t["state"] == "blocked":
                    t["state"], t["t_ready"] = "ready", now
                    self.rev += 1
                elif not ok and t["state"] == "ready":
                    t["state"] = "blocked"
                    self.rev += 1

    def ready_tasks(self, now: float, idle_fill: bool = False) -> list:
        self.refresh(now)
        return [t for t in sorted(self.tasks.values(), key=lambda x: x["id"])
                if t["state"] == "ready" and self._phase_gate_ok(t, idle_fill)]

    # ---------------- 估计 ----------------
    def est(self, kind: str, lane_id: str | None = None, task: dict | None = None) -> float:
        if task and task.get("est_s"):
            base = float(task["est_s"])
        else:
            key = f"{kind}|{lane_id}"
            if key in self.ewma:
                return self.ewma[key]
            base = float(self.cfg["duration_prior_s"].get(kind, 300))
        sp = self.lanes[lane_id]["speed"] if lane_id in self.lanes else 1.0
        return base * sp

    def est_mean(self, kind: str, task: dict | None = None) -> float:
        model = MODEL_OF.get(kind, "image")
        lanes = [l_ for l_ in self.lanes.values() if l_["health"] == "ok" and l_["render_capacity"] > 0
                 and (l_["allow_models"] is None or model in l_["allow_models"])] or list(self.lanes.values())
        if not lanes:
            return self.est(kind, None, task)
        return sum(self.est(kind, l_["id"], task) for l_ in lanes) / len(lanes)

    def observe(self, kind: str, lane_id: str, secs: float) -> None:
        key, a = f"{kind}|{lane_id}", float(self.cfg.get("ewma_alpha", 0.3))
        self.ewma[key] = secs if key not in self.ewma else (1 - a) * self.ewma[key] + a * secs
        self.rev += 1

    def _work(self, t: dict) -> float:
        """任务剩余期望工作量（出图 × 期望尝试 + 打分）"""
        att = float(self.cfg["expected_attempts"].get(t["kind"], 1.0))
        rem = max(1.0, att - t["attempts"]) if t["state"] not in DONE else 0.0
        score = self.cfg["score_prior_s"].get(SCORED_KINDS.get(t["kind"], ""), 0)
        return (self.est_mean(t["kind"], t) + score) * rem

    def ranks(self) -> dict:
        """HEFT 向上秩：rank(t) = work(t) + max(rank(succ))；拓扑逆序，确定性"""
        succ = {tid: [] for tid in self.tasks}
        for t in self.tasks.values():
            for d in t["deps"]:
                if d in succ:
                    succ[d].append(t["id"])
        if self._rank_cache[0] == self.rev:
            return self._rank_cache[1]
        memo: dict[str, float] = {}

        def r(tid: str) -> float:
            if tid in memo:
                return memo[tid]
            t = self.tasks[tid]
            own = 0.0 if t["state"] in DONE else self._work(t)
            memo[tid] = own + max((r(s) for s in succ[tid]), default=0.0)
            return memo[tid]
        for tid in sorted(self.tasks):
            r(tid)
        self._rank_cache = (self.rev, memo)
        return memo

    def switch_penalty(self, lane: dict, model: str) -> float:
        cur = lane["loaded_model"] or "none"
        if cur == model or model == "cpu":
            return 0.0
        return float(self.cfg["switch_penalty_s"].get(f"{cur}->{model}", 90))

    def cost(self, t: dict, lane: dict) -> float:
        return self.est(t["kind"], lane["id"], t) + self.switch_penalty(lane, t["model"])

    def _can(self, t: dict, lane: dict) -> bool:
        if t["model"] == "cpu":
            return lane["allow_models"] is not None and "cpu" in lane["allow_models"]
        if lane["allow_models"] is not None and t["model"] not in lane["allow_models"]:
            return False
        if lane["id"] in t["avoid_lanes"] and len(self.lanes) > 1:
            return False
        return True

    # ---------------- 派单 ----------------
    def plan(self, now: float, lane_ids: list | None = None, idle_fill: bool | None = None) -> list:
        """全局贪心：在 (空道, 就绪任务) 对上反复取 argmax[rank − 集序惩罚 − cost]。返回 [(lane_id, task_id, score)]，不落租约"""
        free = [l_ for l_ in sorted(self.lanes.values(), key=lambda x: x["id"])
                if self.lane_free(l_, now) and (lane_ids is None or l_["id"] in lane_ids)]
        if not free:
            return []
        fill = idle_fill if idle_fill is not None else self.pol.get("phase_gate") == "fill_idle"
        ready = self.ready_tasks(now, idle_fill=False)
        if not ready and fill:
            ready = self.ready_tasks(now, idle_fill=True)
        if not ready:
            return []
        rank = self.ranks()
        ep0 = min(t["ep"] for t in ready)
        pen = float(self.pol.get("episode_order_penalty_s", 0))
        out, taken = [], set()
        while free and len(taken) < len(ready):
            best = None
            for lane in free:
                for t in ready:
                    if t["id"] in taken or not self._can(t, lane):
                        continue
                    s = rank[t["id"]] - pen * (t["ep"] - ep0) - self.cost(t, lane)
                    key = (-s, t["id"], lane["id"])
                    if best is None or key < best[0]:
                        best = (key, lane, t, s)
            if best is None:
                break
            _, lane, t, s = best
            out.append((lane["id"], t["id"], round(s, 1)))
            taken.add(t["id"])
            free = [l_ for l_ in free if l_["id"] != lane["id"]]
        return out

    def next_for_lane(self, lane_id: str, now: float, token: str | None = None) -> dict | None:
        """拉式：道来问下一个任务。只给这条道落租约；别的空道的规划结果不落（它们自己来问）"""
        lane = self.lanes[lane_id]
        lane["last_seen"] = now
        for lid, tid, _ in self.plan(now):
            if lid == lane_id:
                return self.lease(tid, lane_id, now, token)
        return None

    def lease(self, tid: str, lane_id: str, now: float, token: str | None = None, ttl: float | None = None) -> dict:
        t, lane = self.tasks[tid], self.lanes[lane_id]
        if t["state"] != "ready":
            raise SchedError(f"{tid} 不是 ready（{t['state']}）")
        if not self.lane_free(lane):
            raise SchedError(f"{lane_id} 不空闲")
        self.seq += 1
        token = token or f"L{self.seq}"
        t["lease"] = {"lane": lane_id, "token": token, "t0": now, "hb": now, "ttl": float(ttl or self.pol["lease_ttl_s"]),
                      "version": t["version"]}
        t["state"], t["last_lane"] = "leased", lane_id
        self.rev += 1
        if lane["loaded_model"] != t["model"] and t["model"] != "cpu":
            lane["switches"] += 1
            lane["loaded_model"] = t["model"]
        lane["busy"] = tid
        self._log(now, "lease", tid, lane_id, token)
        return {"task": tid, "kind": t["kind"], "ep": t["ep"], "shot": t["shot"], "lane": lane_id, "token": token,
                "attempt": t["attempts"] + 1, "version": t["version"], "model": t["model"],
                "est_s": round(self.est(t["kind"], lane_id, t), 1)}

    def start(self, token: str, now: float, event_id: str | None = None) -> bool:
        if event_id and not self._first(event_id):
            return True
        t = self._by_token(token)
        if not t:
            return False
        t["state"], t["lease"]["hb"] = "running", now
        return True

    def heartbeat(self, token: str, now: float) -> bool:
        t = self._by_token(token)
        if not t:
            return False
        t["lease"]["hb"] = now
        self.lanes[t["lease"]["lane"]]["last_seen"] = now
        return True

    def rendered(self, token: str, now: float, secs: float | None = None, event_id: str | None = None,
                 result: dict | None = None) -> str:
        """道报告“出完了”：→ 打分队列（出图 / 视频）或直接 passed（资产 / 合成）。返回新状态；过期租约（换代后）→ 'stale'"""
        if event_id and not self._first(event_id):
            return "dup"
        t = self._by_token(token, include_stale=True)
        if not t:
            return "unknown"
        lane = self.lanes[t["lease"]["lane"]]
        dur = float(secs if secs is not None else now - t["lease"]["t0"])
        lane["busy"], lane["busy_s"] = None, lane["busy_s"] + dur
        if t["lease"]["version"] != t["version"]:
            t["lease"] = None
            self._log(now, "stale_result", t["id"], lane["id"])
            if t["state"] in ("leased", "running"):
                t["state"] = "blocked"          # refresh 再判依赖（换代后的上游多半还没定）
            self.rev += 1
            return "stale"
        self.observe(t["kind"], lane["id"], dur)
        t["attempts"] += 1
        self.rev += 1
        t["results"].append({"attempt": t["attempts"], "lane": lane["id"], "secs": round(dur, 1), "t": now,
                             "result": result or {}, "score": None, "ok": None})
        t["lease"] = None
        if t["kind"] in SCORED_KINDS:
            t["state"] = "scoring"
            self.score_queue.append(t["id"])
            self._log(now, "to_score", t["id"])
            return "scoring"
        return self._finish(t, now, True, score=1.0)

    # ---------------- 打分队列（VQA 工位） ----------------
    def next_score_job(self, worker_lane: str, now: float, token: str | None = None) -> dict | None:
        lane = self.lanes[worker_lane]
        if len(lane["vqa_busy"]) >= lane["vqa_slots"]:
            return None
        self._expire_scores(now)
        rank = self.ranks() if len(self.score_queue) > 1 else {}
        order = sorted(self.score_queue, key=lambda tid: (self.tasks[tid]["ep"], -rank.get(tid, 0), tid))
        for tid in order:
            t = self.tasks[tid]
            if t["score_lease"] is None:
                self.seq += 1
                token = token or f"S{self.seq}"
                t["score_lease"] = {"lane": worker_lane, "token": token, "t0": now, "hb": now,
                                    "ttl": float(self.pol["score_lease_ttl_s"]), "version": t["version"]}
                lane["vqa_busy"].append(tid)
                return {"task": tid, "kind": t["kind"], "token": token, "model": SCORED_KINDS[t["kind"]],
                        "attempt": t["attempts"], "version": t["version"]}
        return None

    def scored(self, token: str, now: float, ok: bool, score: float = 0.0, why: str = "", event_id: str | None = None,
               secs: float | None = None) -> str:
        if event_id and not self._first(event_id):
            return "dup"
        t = next((x for x in self.tasks.values() if x["score_lease"] and x["score_lease"]["token"] == token), None)
        if not t:
            return "unknown"
        sl = t["score_lease"]
        lane = self.lanes[sl["lane"]]
        if t["id"] in lane["vqa_busy"]:
            lane["vqa_busy"].remove(t["id"])
        lane["vqa_busy_s"] += float(secs if secs is not None else now - sl["t0"])
        if t["id"] in self.score_queue:
            self.score_queue.remove(t["id"])
        t["score_lease"] = None
        if sl["version"] != t["version"]:
            return "stale"
        if t["results"]:
            t["results"][-1].update({"score": score, "ok": bool(ok), "why": why})
        return self._finish(t, now, ok, score, why)

    def _finish(self, t: dict, now: float, ok: bool, score: float = 0.0, why: str = "") -> str:
        self.rev += 1
        if t["best"] is None or score > t["best"]["score"]:
            t["best"] = {"attempt": t["attempts"], "score": score, "ok": bool(ok)}
        if ok:
            t["state"], t["t_done"] = "passed", now
            self._log(now, "passed", t["id"], t["attempts"])
        elif t["attempts"] < t["max_attempts"]:
            t["state"] = "ready"            # failed → 立刻可重排（换种子）
            self._log(now, "failed_retry", t["id"], t["attempts"], why)
        else:
            t["state"] = "best_effort"
            self._log(now, "best_effort", t["id"], t["attempts"], why)
            if self.pol.get("auto_adopt", True):
                self.adopt(t["id"], now)
        return t["state"]

    def adopt(self, tid: str, now: float, event_id: str | None = None) -> bool:
        """采用最好一版（自动 L-196 或项目方 / 总调度手工）→ 下游放行"""
        if event_id and not self._first(event_id):
            return True
        t = self.tasks[tid]
        if t["state"] not in ("best_effort", "failed"):
            return False
        t["state"], t["t_done"] = "adopted", now
        self.rev += 1
        self._log(now, "adopted", tid, (t["best"] or {}).get("attempt"))
        return True

    # ---------------- 换代 / 失效 / hold ----------------
    def regen(self, tid: str, now: float, reason: str = "", event_id: str | None = None, reset_attempts: bool = True) -> list:
        """首帧（或任一任务）换代：本任务回 ready/blocked、版本 +1；下游全部失效（含已 passed 的 last / video / assembly）。返回被失效的任务 id"""
        if event_id and not self._first(event_id):
            return []
        t = self.tasks[tid]
        affected = self._invalidate(t, now, reset_attempts)
        self._log(now, "regen", tid, reason, affected)
        self.refresh(now)
        return affected

    def _invalidate(self, t: dict, now: float, reset_attempts: bool) -> list:
        t["version"] += 1
        self.rev += 1
        if t["lease"] and t["lease"]["lane"] in self.lanes:
            lane = self.lanes[t["lease"]["lane"]]
            if lane["busy"] == t["id"]:
                pass                        # 道上还在跑：结果到达时按版本号丢弃（rendered → stale），道随之释放
        if t["id"] in self.score_queue:
            self.score_queue.remove(t["id"])
        if t["score_lease"]:
            lane = self.lanes[t["score_lease"]["lane"]]
            if t["id"] in lane["vqa_busy"]:
                lane["vqa_busy"].remove(t["id"])
            t["score_lease"] = None
        if reset_attempts:
            t["attempts"], t["best"] = 0, None
        t["t_done"] = None
        if t["state"] not in ("leased", "running"):
            t["state"] = "blocked"
        affected = [t["id"]]
        for s in self.succs(t["id"]):
            affected += self._invalidate(self.tasks[s], now, True)
        return affected

    def hold(self, tid: str, reason: str, now: float) -> None:
        t = self.tasks[tid]
        t["hold"] = reason
        self.rev += 1
        if t["state"] == "ready":
            t["state"] = "blocked"

    def release(self, tid: str, now: float) -> None:
        self.tasks[tid]["hold"] = None
        self.rev += 1
        self.refresh(now)

    # ---------------- 租约超时 ----------------
    def expire(self, now: float) -> list:
        """租约过期（心跳断）→ 回 ready、尽量换道（avoid_lanes）；道超时计数到阈值标 down。返回过期任务 id"""
        out = []
        for t in sorted(self.tasks.values(), key=lambda x: x["id"]):
            le = t["lease"]
            if t["state"] in ("leased", "running") and le and now - le["hb"] > le["ttl"]:
                lane = self.lanes.get(le["lane"])
                if lane:
                    if lane["busy"] == t["id"]:
                        lane["busy"] = None
                    lane["timeouts"] += 1
                    if lane["timeouts"] >= int(self.pol.get("lane_down_after_timeouts", 2)):
                        lane["health"] = "down"
                    if self.pol.get("requeue_avoid_same_lane", True) and lane["id"] not in t["avoid_lanes"]:
                        t["avoid_lanes"].append(lane["id"])
                t["lease"], t["state"] = None, "ready"
                self.rev += 1
                out.append(t["id"])
                self._log(now, "lease_timeout", t["id"], le["lane"])
        self._expire_scores(now)
        return out

    def _expire_scores(self, now: float) -> None:
        for t in self.tasks.values():
            sl = t["score_lease"]
            if sl and now - sl["hb"] > sl["ttl"]:
                lane = self.lanes.get(sl["lane"])
                if lane and t["id"] in lane["vqa_busy"]:
                    lane["vqa_busy"].remove(t["id"])
                t["score_lease"] = None
                if t["id"] not in self.score_queue and t["state"] == "scoring":
                    self.score_queue.append(t["id"])

    # ---------------- 幂等事件入口 ----------------
    def apply(self, ev: dict):
        """统一事件入口（HTTP / 文件重放都走这里）。ev = {id, type, t, ...}；同 id 只生效一次"""
        eid = ev.get("id")
        if eid is not None and eid in self._seen_set:
            return "dup"
        if eid is not None:
            self._first(eid)
        typ, now = ev["type"], float(ev.get("t", 0))
        if typ == "lane_seen":
            return self.lane_seen(ev["lane"], now, ev.get("loaded_model"))
        if typ == "next":
            return self.next_for_lane(ev["lane"], now, ev.get("token"))
        if typ == "start":
            return self.start(ev["token"], now)
        if typ == "heartbeat":
            return self.heartbeat(ev["token"], now)
        if typ == "rendered":
            return self.rendered(ev["token"], now, ev.get("secs"), result=ev.get("result"))
        if typ == "next_score":
            return self.next_score_job(ev["lane"], now, ev.get("token"))
        if typ == "scored":
            return self.scored(ev["token"], now, bool(ev.get("ok")), float(ev.get("score", 0)), ev.get("why", ""), secs=ev.get("secs"))
        if typ == "regen":
            return self.regen(ev["task"], now, ev.get("reason", ""), reset_attempts=ev.get("reset_attempts", True))
        if typ == "adopt":
            return self.adopt(ev["task"], now)
        if typ == "hold":
            return self.hold(ev["task"], ev.get("reason", "hold"), now)
        if typ == "release":
            return self.release(ev["task"], now)
        if typ == "lane_role":
            return self.set_lane_role(ev["lane"], ev.get("render_capacity"), ev.get("vqa_slots"), ev.get("allow_models", "keep"),
                                      ev.get("loaded_model"), ev.get("health"))
        if typ == "expire":
            return self.expire(now)
        raise SchedError(f"未知事件 {typ}")

    def _first(self, eid: str) -> bool:
        if eid in self._seen_set:
            return False
        if len(self.seen) == self.seen.maxlen:
            self._seen_set.discard(self.seen[0])
        self.seen.append(eid)
        self._seen_set.add(eid)
        return True

    def _by_token(self, token: str, include_stale: bool = False):
        for t in self.tasks.values():
            le = t["lease"]
            if le and le["token"] == token and (include_stale or le["version"] == t["version"]):
                return t
        return None

    def _log(self, now: float, *a) -> None:
        self.log.append([round(now, 1)] + [x for x in a])

    # ---------------- ETA / 报表 ----------------
    def eta(self, now: float, ep: int | None = None) -> dict:
        """剩余时间估计 vs KPI：max(关键路径, 剩余工作量 / 健康出图道数) + 打分"""
        eps = self._episodes()
        if ep is None:
            ep = next((e for e in eps if self.episode_phase(e) != "done"), eps[-1] if eps else 0)
        ts = [t for t in self.tasks.values() if t["ep"] == ep and t["state"] not in DONE]
        rank = self.ranks()
        cp = max((rank[t["id"]] for t in ts), default=0.0)
        work = sum(self._work(t) for t in ts)
        lanes = [l_ for l_ in self.gpu_lanes() if l_["health"] == "ok" and l_["render_capacity"] > 0]
        n = max(1, len(lanes))
        kpi = float(self.cfg["kpi"]["episode_s"])
        per = {}
        for t in ts:
            per[t["kind"]] = per.get(t["kind"], 0) + 1
        remaining = max(cp, work / n)
        return {"episode": ep, "phase": self.episode_phase(ep), "remaining_s": round(remaining), "critical_path_s": round(cp),
                "work_s": round(work), "lanes": n, "kpi_s": kpi, "on_track": remaining <= kpi, "pending": per}

    def snapshot(self, now: float) -> dict:
        states = {}
        for t in self.tasks.values():
            states[t["state"]] = states.get(t["state"], 0) + 1
        return {"t": now, "states": states, "score_queue": len(self.score_queue),
                "lanes": {k: {"model": v["loaded_model"], "busy": v["busy"], "health": v["health"], "vqa": len(v["vqa_busy"]),
                              "switches": v["switches"]} for k, v in sorted(self.lanes.items())},
                "eta": self.eta(now) if self.tasks else None}

    # ---------------- 序列化（单写者、原子写） ----------------
    def to_dict(self) -> dict:
        return {"v": 1, "seq": self.seq, "tasks": {k: self.tasks[k] for k in sorted(self.tasks)},
                "lanes": {k: self.lanes[k] for k in sorted(self.lanes)}, "ewma": dict(sorted(self.ewma.items())),
                "score_queue": list(self.score_queue), "seen": list(self.seen), "log": list(self.log)}

    @classmethod
    def from_dict(cls, d: dict, cfg: dict | None = None) -> "Board":
        b = cls(cfg or load_config())
        b.lanes = {}
        for k, v in d.get("lanes", {}).items():
            if k not in BAD_LANES:
                b.lanes[k] = v
        b.tasks = d.get("tasks", {})
        b.ewma = d.get("ewma", {})
        b.score_queue = list(d.get("score_queue", []))
        b.seq = int(d.get("seq", 0))
        for e in d.get("seen", []):
            b._first(e)
        for row in d.get("log", []):
            b.log.append(row)
        return b

    def save(self, path: Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text(json.dumps(self.to_dict(), ensure_ascii=False, sort_keys=True, indent=0), encoding="utf-8")
        os.replace(tmp, path)

    @classmethod
    def load(cls, path: Path, cfg: dict | None = None) -> "Board":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")), cfg)


def build_episode(board: Board, ep: int, shots: list, assets: dict | None = None, holds: dict | None = None) -> None:
    """按剧本建一集 DAG：shots = ["S1", ...]；assets = {"S1": ["face:林晚", "scene:sk_attic"], ...}（资产任务 id；不存在的自动建）；
    holds = {"S12": "成人镜等项目方"}"""
    assets, holds = assets or {}, holds or {}
    for s in shots:
        deps = []
        for a in assets.get(s, []):
            kind, name = a.split(":", 1)
            deps.append(board.add_asset(kind, name, ep)["id"])
        board.add_shot(ep, s, deps, hold=holds.get(s))
    board.add_assembly(ep)
