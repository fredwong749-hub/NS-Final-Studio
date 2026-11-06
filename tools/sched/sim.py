"""SCHED-CORE 离散事件模拟器（11-06）：用今天 ep01 的实测耗时重放，比较四种调度方式对 50 min KPI（L-205）的差距。

实测来源（只读，11-06 JST 取自两台服务器）：
  · gpu33 data/producer/runs/series10_v2/log.jsonl：rendered.gpu_s 中位 首帧 331 / 尾帧 326 s（gpu33 道 ≈ 310、gpu36 道 ≈ 400，base35）；
    render_s（含排队）中位 ≈ 610 s（预取深度 2 → 等待 ≈ 一倍）；passed.contract_s 中位 91 s；
    首帧每次不过率 redo_fail/rendered = 71/92 = 77%，尾帧 content_fail/rendered = 31/54 = 57%。
  · vidgen_gpu33/36.log：DONE 404 s（gpu33）/ 410–480 s（gpu36）；DONE→SCORE ≈ 65 s；视频不过（身份偏离 / 泛红）≈ 30%。
  · night.log：EP_RESOLVED→assemble→director ≈ 11 min（合成 ≈ 4 min 在关键路径上）。
场景：
  a_today      今天的方式：每台各自 producer（预取 2 深 → 同卡两活对半分）、gpu33:3 既出图又看图、视频等整集首尾帧、
               视频道只 gpu36:0/1/2 + gpu33:0/1、每落定一镜 night 主循环被同步 / 预览阻塞 ≈ 5 min 不派活
  b_stations   L-206/L-207 固定工位：首尾帧阶段 出图 4 + 审图 1（×3 实例）+ 视频 1；首尾帧全部定下 → 6 卡视频（审图缩 1 实例）
  c_affinity   新调度：6 道一个工作板、拉式派单、按镜就绪、换模型计代价、看图独立队列（审图位同 b）
  d_turbo      c + 首尾帧 8 步 turbo（≈ 75 / 95 s）
  e_turbo_vqa6 d + 审图 6 实例（gpu33:3 ×3 + gpu36:2 ×3，视频阶段再转视频）——看 turbo 后的瓶颈是不是看图
  f_turbo_vqa6_gates  e + 检测修好（首帧过率 60% / 尾帧 70%、看图 45 s）——KPI 50 min 需要什么条件
用法：python tools/sched/sim.py [--seeds 3] [--json out.json] [--fetch]   （--fetch = 从两台服务器重新量一遍，只读）
"""
from __future__ import annotations

import argparse
import heapq
import json
import math
import os
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core as C  # noqa: E402

MEASURED = {
    "date": "2026-11-06",
    "shots": [f"S{i}" for i in range(1, 17)],
    "frame_gpu_s": {"gpu33": 310, "gpu36": 400},
    "frame_turbo_s": {"gpu33": 75, "gpu36": 95},
    "frame_score_s": 90,
    "frame_pass_p": {"first": 0.23, "last": 0.43},
    "video_gpu_s": {"gpu33": 404, "gpu36": 415},
    "video_score_s": 65,
    "video_pass_p": 0.70,
    "assembly_s": 360,
    "switch_s": 90,
    "today_actual_min": 150,
    "legacy": {"prefetch_depth": 2, "night_block_s": 120, "video_gate": "episode"},
    "fixed_gates": {"frame_pass_p": {"first": 0.6, "last": 0.7}, "frame_score_s": 45},
    "noise_sigma": 0.12,
}

GPU_LANES = ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1", "gpu36:2"]
SCENARIOS = ["a_today", "b_stations", "c_affinity", "d_turbo", "e_turbo_vqa6", "f_turbo_vqa6_gates"]
TURBO = ("d_turbo", "e_turbo_vqa6", "f_turbo_vqa6_gates")
VQA6 = ("e_turbo_vqa6", "f_turbo_vqa6_gates")


def _cfg(scn: str, m: dict) -> dict:
    cfg = C.load_config(Path("/nonexistent"))          # 默认值，不读真实配置
    cfg["lanes"] = {lid: {"host": lid.split(":")[0], "speed": 1.0} for lid in GPU_LANES}
    cfg["switch_penalty_s"] = {k: m["switch_s"] for k in cfg["switch_penalty_s"]}
    turbo = scn in TURBO
    fr = m["frame_turbo_s"] if turbo else m["frame_gpu_s"]
    cfg["duration_prior_s"].update({"first": fr["gpu33"], "last": fr["gpu33"], "video": m["video_gpu_s"]["gpu33"],
                                    "assembly": m["assembly_s"]})
    cfg["score_prior_s"] = {"image": m["frame_score_s"], "video": m["video_score_s"]}
    for lid in GPU_LANES:
        host = lid.split(":")[0]
        cfg["lanes"][lid]["speed"] = round((fr[host] / fr["gpu33"] + m["video_gpu_s"][host] / m["video_gpu_s"]["gpu33"]) / 2, 3)
    cfg["policies"]["lane_stale_s"] = 0
    return cfg


class Sim:
    def __init__(self, scn: str, m: dict, seed: int = 1106):
        if scn == "f_turbo_vqa6_gates":              # 检测修好：不过率降、看图提速（看 KPI 要什么条件）
            m = dict(m, **m["fixed_gates"])
        self.scn, self.m, self.rng = scn, m, random.Random(seed)
        self.board = C.Board(_cfg(scn, m))
        b = self.board
        self.legacy = scn == "a_today"
        self.turbo = scn in TURBO
        self.phase = "frames"
        self.night_block_until = 0.0
        self.events: list = []
        self.seq = 0
        self.lane_log: dict[str, list] = {lid: [] for lid in GPU_LANES}
        if self.legacy:
            # 预取 2 深：同一张卡两个活同时跑、各占一半 → 两条虚拟道、速度减半；gpu33:3 既出图又看图（互相拖慢 ×1.2）
            b.lanes = {}
            for lid in GPU_LANES:
                sp = 1.0 if lid.startswith("gpu33") else 1.25
                if lid == "gpu33:3":
                    sp *= 1.2
                for k in range(m["legacy"]["prefetch_depth"]):
                    vq = 3 if (lid == "gpu33:3" and k == 0) else 0
                    b.add_lane(f"{lid}{'ab'[k]}", host=lid.split(":")[0], speed=sp * m["legacy"]["prefetch_depth"],
                               vqa_slots=vq, allow_models=["image"] if lid == "gpu33:3" else ["image", "video"])
            b.add_lane("cpu:0", host="cpu", allow_models=["cpu"], loaded_model="cpu")
            b.pol["phase_gate"] = "off"
        elif scn == "b_stations":
            for lid in ("gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1"):
                b.set_lane_role(lid, allow_models=["image"])
            b.set_lane_role("gpu33:3", render_capacity=0, vqa_slots=3, allow_models=["video"])
            b.set_lane_role("gpu36:2", allow_models=["video"])
        else:
            b.set_lane_role("gpu33:3", render_capacity=0, vqa_slots=3)
            if scn in VQA6:
                b.set_lane_role("gpu36:2", render_capacity=0, vqa_slots=3)
        C.build_episode(b, 1, m["shots"])
        if self.legacy:
            for t in b.tasks.values():            # 视频等整集首尾帧（今天 night 的整集闸）
                if t["kind"] == "video":
                    t["deps"] = sorted({d for x in b.tasks.values() if x["kind"] in ("first", "last") for d in [x["id"]]})

    # ---- 工具 ----
    def _push(self, t: float, kind: str, payload: dict | None = None) -> None:
        self.seq += 1
        heapq.heappush(self.events, (t, self.seq, kind, payload or {}))

    def _noise(self) -> float:
        return math.exp(self.rng.gauss(0, self.m["noise_sigma"]))

    def _dur(self, kind: str, lane_id: str) -> float:
        """实测基准（按台）× 噪声；今天的方式：预取 2 深 → 同卡两活对半分，单活耗时 ×2（gpu33:3 再 ×1.2：看图同卡）"""
        host = "gpu33" if lane_id.startswith("gpu33") else ("gpu36" if lane_id.startswith("gpu36") else "cpu")
        m = self.m
        if kind in ("first", "last"):
            base = (m["frame_turbo_s"] if self.turbo else m["frame_gpu_s"])[host]
        elif kind == "video":
            base = m["video_gpu_s"][host]
        elif kind == "assembly":
            base = m["assembly_s"]
        else:
            base = 150
        mult = 1.0
        if self.legacy and host != "cpu":
            mult = m["legacy"]["prefetch_depth"] * (1.2 if lane_id.startswith("gpu33:3") else 1.0)
        return base * mult * self._noise()

    def _pass(self, kind: str) -> bool:
        p = self.m["frame_pass_p"].get(kind, self.m["video_pass_p"]) if kind != "video" else self.m["video_pass_p"]
        return self.rng.random() < p

    def _phys(self, lane_id: str) -> str:
        return lane_id[:-1] if self.legacy and lane_id[-1] in "ab" else lane_id

    # ---- 主循环 ----
    def run(self, horizon_s: float = 6 * 3600) -> dict:
        b = self.board
        now = 0.0
        self._push(0.0, "tick")
        while self.events:
            now, _, kind, p = heapq.heappop(self.events)
            if now > horizon_s:
                break
            if kind == "tick":
                self._dispatch(now)
                if b.episode_phase(1) == "done":
                    break
            elif kind == "done":
                self._on_done(now, p)
            elif kind == "scored":
                self._on_scored(now, p)
        return self._report(now)

    def _switch_phase_if_needed(self, now: float) -> None:
        b = self.board
        if self.phase == "frames" and not self.legacy and b.episode_phase(1) in ("videos", "assembly", "done"):
            self.phase = "videos"
            self.t_frames_done = now
            for lid in GPU_LANES:
                b.set_lane_role(lid, allow_models=None if self.scn != "b_stations" else ["video"])
            b.set_lane_role("gpu33:3", render_capacity=1, vqa_slots=1)    # L-207：审图位转视频 + 1 看图实例
            if self.scn in VQA6:
                b.set_lane_role("gpu36:2", render_capacity=1, vqa_slots=0)
        if self.legacy and not hasattr(self, "t_frames_done") and b.episode_phase(1) in ("videos", "assembly", "done"):
            self.t_frames_done = now

    def _dispatch(self, now: float) -> None:
        b = self.board
        b.refresh(now)
        self._switch_phase_if_needed(now)
        if self.legacy:                                # night 主循环被同步 / 预览阻塞时不派视频（今天实测 5–10 min / 镜）
            blocked = now < self.night_block_until
            for t in b.tasks.values():
                if t["kind"] == "video" and blocked and t["state"] == "ready":
                    b.hold(t["id"], "night_block", now)
                elif t["kind"] == "video" and not blocked and t["hold"] == "night_block":
                    b.release(t["id"], now)
        for lane in sorted(b.lanes.values(), key=lambda x: x["id"]):          # 出图 / 视频道（拉式）
            if not b.lane_free(lane):
                continue
            prev = lane["loaded_model"]
            lease = b.next_for_lane(lane["id"], now)
            if not lease:
                continue
            pen = self.m["switch_s"] if (prev != lease["model"] and lease["model"] != "cpu") else 0.0
            dur = self._dur(lease["kind"], lane["id"])
            b.start(lease["token"], now)
            ph = self._phys(lane["id"])
            if ph in self.lane_log:
                self.lane_log[ph].append((now, now + pen + dur, lease["kind"], pen))
            self._push(now + pen + dur, "done", {"token": lease["token"], "secs": dur, "kind": lease["kind"]})
        for lane in sorted(b.lanes.values(), key=lambda x: x["id"]):          # 看图工位（独立队列）
            while lane["vqa_slots"] > len(lane["vqa_busy"]):
                job = b.next_score_job(lane["id"], now)
                if not job:
                    break
                sdur = (self.m["frame_score_s"] if job["model"] == "image" else self.m["video_score_s"]) * self._noise()
                self._push(now + sdur, "scored", {"token": job["token"], "kind": job["kind"], "secs": sdur})

    def _on_done(self, now: float, p: dict) -> None:
        st = self.board.rendered(p["token"], now, p["secs"])
        if self.legacy and p["kind"] == "video":
            self.night_block_until = max(self.night_block_until, now) + self.m["legacy"]["night_block_s"]
            self._push(self.night_block_until + 0.01, "tick")
        self._push(now, "tick")

    def _on_scored(self, now: float, p: dict) -> None:
        ok = self._pass(p["kind"])
        self.board.scored(p["token"], now, ok, score=self.rng.random(), secs=p["secs"])
        self._push(now, "tick")

    # ---- 报表 ----
    def _report(self, now: float) -> dict:
        b = self.board
        done_t = lambda kinds: max((t["t_done"] or 0) for t in b.tasks.values() if t["kind"] in kinds)  # noqa: E731
        frames_end = done_t(("first", "last"))
        videos_end = done_t(("video",))
        total = done_t(("assembly",)) if b.episode_phase(1) == "done" else now
        util, switches = {}, {}
        for lid, segs in self.lane_log.items():
            busy = sum(e - s for s, e, _, _ in segs)
            depth = self.m["legacy"]["prefetch_depth"] if self.legacy else 1       # 预取 2 深 = 两条虚拟道合成一张卡
            util[lid] = round(100 * busy / (total * depth), 1) if total else 0.0
            switches[lid] = sum(1 for s in segs if s[3] > 0)
        vqa_busy = sum(l_["vqa_busy_s"] for l_ in b.lanes.values())
        vqa_slots = {"frames": 3, "videos": 1} if self.scn not in VQA6 else {"frames": 6, "videos": 1}
        attempts = {k: sum(t["attempts"] for t in b.tasks.values() if t["kind"] == k) for k in ("first", "last", "video")}
        adopted = sum(1 for t in b.tasks.values() if t["state"] == "adopted")
        first_video_start = min((s for lid in self.lane_log for s, e, k, _ in self.lane_log[lid] if k == "video"), default=0)
        return {"scenario": self.scn, "finished": b.episode_phase(1) == "done", "total_min": round(total / 60, 1),
                "frames_min": round(frames_end / 60, 1), "videos_min": round((videos_end - frames_end) / 60, 1),
                "videos_end_min": round(videos_end / 60, 1), "assembly_min": round((total - videos_end) / 60, 1),
                "first_video_start_min": round(first_video_start / 60, 1), "gpu_util_pct": util,
                "gpu_util_mean_pct": round(sum(util.values()) / len(util), 1), "switches": switches,
                "vqa_busy_min": round(vqa_busy / 60, 1), "vqa_slots": vqa_slots, "attempts": attempts, "adopted": adopted,
                "kpi_ok": total <= 3000}


def run_scenarios(m: dict | None = None, seeds: list | None = None, scenarios: list | None = None) -> list:
    m = m or MEASURED
    seeds = seeds or [1106, 1107, 1108]
    rows = []
    for scn in scenarios or SCENARIOS:
        rs = [Sim(scn, m, seed=s).run() for s in seeds]
        agg = {"scenario": scn, "finished": all(r["finished"] for r in rs), "seeds": len(rs)}
        for k in ("total_min", "frames_min", "videos_min", "assembly_min", "first_video_start_min", "gpu_util_mean_pct", "vqa_busy_min"):
            agg[k] = round(sum(r[k] for r in rs) / len(rs), 1)
        agg["total_min_range"] = [min(r["total_min"] for r in rs), max(r["total_min"] for r in rs)]
        agg["gpu_util_pct"] = {lid: round(sum(r["gpu_util_pct"][lid] for r in rs) / len(rs), 1) for lid in GPU_LANES}
        agg["switches"] = {lid: round(sum(r["switches"][lid] for r in rs) / len(rs), 1) for lid in GPU_LANES}
        agg["attempts"] = {k: round(sum(r["attempts"][k] for r in rs) / len(rs), 1) for k in ("first", "last", "video")}
        agg["kpi_ok"] = agg["total_min"] <= m.get("kpi_min", 50)
        rows.append(agg)
    return rows


def table(rows: list, m: dict | None = None) -> str:
    m = m or MEASURED
    hdr = f"{'场景':<14}{'总分钟':>8}{'首尾帧':>8}{'视频':>8}{'合成':>6}{'首视频起':>9}{'GPU均用':>8}{'看图忙':>8}{'KPI≤50':>8}  各道利用率% / 切换次"
    out = [hdr, "-" * len(hdr)]
    for r in rows:
        lanes = " ".join(f"{lid.split(':')[0][-2:]}:{lid.split(':')[1]}={r['gpu_util_pct'][lid]:.0f}/{r['switches'][lid]:.0f}" for lid in GPU_LANES)
        out.append(f"{r['scenario']:<14}{r['total_min']:>8}{r['frames_min']:>8}{r['videos_min']:>8}{r['assembly_min']:>6}"
                   f"{r['first_video_start_min']:>9}{r['gpu_util_mean_pct']:>8}{r['vqa_busy_min']:>8}{'是' if r['kpi_ok'] else '否':>8}  {lanes}")
    out.append(f"（实测今天 ep01 ≈ {m['today_actual_min']} min；a_today 为按今天调度方式重放的模拟值；每格为 {rows[0]['seeds']} 个种子均值）")
    return "\n".join(out)


def fetch_measured(timeout: float = 60) -> dict:
    """从两台服务器只读重量一遍（需要笔记本 rssh 主连接在）。失败 → 返回 MEASURED 副本并带 fetch_error"""
    import statistics as st
    sys.path.insert(0, str(C.ROOT / "tools/netfix"))
    import rssh  # noqa: E402
    m = json.loads(json.dumps(MEASURED))
    repo = os.environ.get("NS_SCHED_SIM_REPO") or C.load_config().get("sim", {}).get("server_repo", "")
    if not repo:
        m["fetch_error"] = "没配服务器仓库路径（config/pipeline/sched.json sim.server_repo 或 NS_SCHED_SIM_REPO）"
        return m
    try:
        r = rssh.run("gpu33", f"cd {repo} && grep -E '\"ev\": \"(rendered|passed|redo_fail|content_fail)\"' "
                     f"data/producer/runs/series10_v2/log.jsonl | tail -600", timeout=timeout)
        ev = [json.loads(x) for x in r.stdout.decode("utf-8", "replace").splitlines() if x.strip()]
        g = {"gpu33": [], "gpu36": []}
        cnt = {"first": [0, 0], "last": [0, 0]}
        cs = []
        for e in ev:
            kind = str(e.get("obj", "")).split(":")[0]
            if e["ev"] == "rendered" and e.get("gpu_s") and e.get("lane", "")[:5] in g:
                g[e["lane"][:5]].append(e["gpu_s"])
                if kind in cnt:
                    cnt[kind][0] += 1
            if e["ev"] in ("redo_fail", "content_fail") and kind in cnt:
                cnt[kind][1] += 1
            if e.get("contract_s"):
                cs.append(e["contract_s"])
        for h in g:
            if g[h]:
                m["frame_gpu_s"][h] = round(st.median(g[h]))
        if cs:
            m["frame_score_s"] = round(st.median(cs))
        for k, (n, f) in cnt.items():
            if n:
                m["frame_pass_p"][k] = round(max(0.05, 1 - f / n), 2)
        for host in ("gpu33", "gpu36"):
            r = rssh.run(host, f"cd {repo} && grep ' DONE ' data/pipeline/runs/series10_v2/video/vidgen_{host}.log | tail -60", timeout=timeout)
            secs = [float(x.split()[-1][:-1]) for x in r.stdout.decode("utf-8", "replace").splitlines() if x.strip().endswith("s")]
            secs = [s for s in secs if s > 100]
            if secs:
                m["video_gpu_s"][host] = round(st.median(secs))
        m["fetched"] = True
    except (OSError, ValueError, KeyError) as e:  # arch-ok: 量不到就用内置实测值并标出来，模拟照跑
        m["fetch_error"] = str(e)[:200]
    return m


def main(argv: list | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--seeds", type=int, default=3)
    ap.add_argument("--json", type=Path, default=None)
    ap.add_argument("--fetch", action="store_true")
    ap.add_argument("--scenario", action="append", default=None)
    a = ap.parse_args(argv)
    m = fetch_measured() if a.fetch else MEASURED
    rows = run_scenarios(m, seeds=[1106 + i for i in range(a.seeds)], scenarios=a.scenario)
    print(table(rows, m))
    if a.json:
        a.json.parent.mkdir(parents=True, exist_ok=True)
        tmp = a.json.with_suffix(".tmp")
        tmp.write_text(json.dumps({"measured": m, "rows": rows}, ensure_ascii=False, indent=1), encoding="utf-8")
        tmp.replace(a.json)
    return 0


if __name__ == "__main__":
    sys.exit(main())
