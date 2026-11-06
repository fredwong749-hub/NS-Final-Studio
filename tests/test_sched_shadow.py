"""L-209 S1：tools/sched/shadow.py 影子调度——建图 / 坏卡 / 成人 / 终态 / 阶段 / 差异归因 / 去重 / 一拍落盘（全 fake，不连网络）。"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools/sched"))
_spec = importlib.util.spec_from_file_location("sched_shadow_t", ROOT / "tools/sched/shadow.py")
SH = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(SH)
C = SH.C

NOW = 1_800_000_000.0
LANES = {"gpu33:0": {"host": "gpu33", "gpu": 0, "comfy_port": 8188}, "gpu33:1": {"host": "gpu33", "gpu": 1, "comfy_port": 8189},
         "gpu33:2": {"host": "gpu33", "gpu": 2, "comfy_port": 8190},
         "gpu33:3": {"host": "gpu33", "gpu": 3, "comfy_port": 8191}, "gpu36:0": {"host": "gpu36", "gpu": 0, "comfy_port": 8188},
         "gpu36:1": {"host": "gpu36", "gpu": 1, "comfy_port": 8189}, "gpu36:2": {"host": "gpu36", "gpu": 2, "comfy_port": 8190}}
ROLES = {"enabled": True, "from_episode": 1,
         "phases": {"frames": {"image": ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1"], "review": ["gpu33:3"], "video": ["gpu36:2"]},
                    "videos": {"image": [], "review": ["gpu33:3"],
                               "video": ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1", "gpu36:2"]}},
         "review": {"vqa_instances_by_phase": {"frames": 3, "videos": 1}}}


def obj(st, att=0, lu=0):
    return [st, att, 3, 0, lu, "", ""]


def shot(first="passed", last="passed", video="pending", assets="passed", fa=1, la=1, lu=0):
    return {"assets": obj(assets), "first": obj(first, fa), "last": obj(last, la, lu), "video": obj(video)}


def probe(host, reg, only=(), queues=None, events=(), vidgen=(), vstate=None, lrs=None, partition=None, adult_wait=()):
    q = {ln: {"running": [], "pending": 0} for ln, v in LANES.items() if v["host"] == host}
    q.update(queues or {})
    return {"now": NOW, "host": host, "gpus": {}, "queues": q, "reg": reg, "ctrl": {"only": list(only), "hold_lanes": [], "paused": False},
            "hb_age_s": 5, "events": list(events), "adult_wait": list(adult_wait), "first_dispatch": {"2": NOW - 1800},
            "vidgen": list(vidgen), "vstate": vstate or {}, "nctrl": {"yield_s": 30, "video_lanes": ["gpu36:2"]},
            "lrs": lrs or {"2": {"phase": "frames"}, "_active": {"ep": 2, "phase": "frames"}}, "partition": partition or {}}


def two_hosts(reg33, reg36, **kw36):
    only36 = sorted({s for E in reg36.values() for s in E["shots"]})
    return {"gpu33": probe("gpu33", reg33), "gpu36": probe("gpu36", reg36, only=only36, **kw36)}


def ep2(n=4, **over):
    shots = {f"ep02-S{i}": shot(first="ready", last="pending", fa=0, la=0) for i in range(1, n + 1)}
    shots.update(over)
    return {"2": {"asm": None, "shots": shots}}


def build(probes, adult=frozenset(), roles=ROLES, now=NOW):
    eps, div = SH.merge_registry(probes)
    live = SH.live_lanes(probes, {k: v for k, v in LANES.items() if k != "gpu33:2"})
    b, info = SH.build_board(eps, set(adult), live, SH.video_running(probes), SH.recent_gates(probes, now),
                             C.load_config(Path("/nonexistent")), roles, now)
    return b, info, div, live


# ---------------------------------------------------------------- 建图
def test_dag_built_from_snapshot_fixture():
    reg = ep2(3, **{"ep02-S1": shot(video="pending"), "ep02-S2": shot(first="passed", last="ready", la=1)})
    b, info, div, _ = build(two_hosts({}, reg))
    assert info["eps"] == [2] and info["active_ep"] == 2 and info["phase"] == "frames"
    for k in ("first", "last", "video"):
        assert f"{k}:ep02-S3" in b.tasks
    assert "assembly:ep02" in b.tasks
    assert b.tasks["first:ep02-S1"]["state"] == "passed" and b.tasks["last:ep02-S1"]["state"] == "passed"
    assert b.tasks["video:ep02-S1"]["state"] == "ready"          # 首尾帧定下 → 视频就绪（按镜，L-202）
    assert b.tasks["last:ep02-S2"]["state"] == "ready"
    assert b.tasks["first:ep02-S3"]["state"] == "ready" and b.tasks["last:ep02-S3"]["state"] == "blocked"


def test_owner_host_wins_for_frames_and_divergence_recorded():
    stale = ep2(1, **{"ep02-S1": shot(first="best_effort", last="pending")})      # gpu33 旧副本
    live = ep2(1, **{"ep02-S1": shot(first="ready", last="pending", fa=0)})       # gpu36 = control.only 归属台
    eps, div = SH.merge_registry(two_hosts(stale, live))
    assert eps[2]["shots"]["ep02-S1"]["first"]["st"] == "ready"
    assert any(d["obj"] == "first:ep02-S1" and d["used"] == "gpu36" for d in div)


def test_video_takes_most_advanced_across_hosts_and_vstate():
    reg33 = ep2(1, **{"ep02-S1": shot(video="running")})
    reg36 = ep2(1, **{"ep02-S1": shot(video="pending")})
    pr = two_hosts(reg33, reg36, vstate={"ep02-S1": {"status": "done", "renders": []}})
    eps, _ = SH.merge_registry(pr)
    assert eps[2]["shots"]["ep02-S1"]["video"]["st"] == "passed"


# ---------------------------------------------------------------- 坏卡 gpu33:2
def test_never_gpu33_2_even_if_listed_and_idle():
    cfg = C.load_config(Path("/nonexistent"))
    cfg["lanes"]["gpu33:2"] = {"host": "gpu33", "speed": 1.0}
    reg = ep2(8)
    pr = two_hosts({}, reg)
    eps, _ = SH.merge_registry(pr)
    live = SH.live_lanes(pr, LANES)                      # gpu33:2 混进来也空着
    b, info = SH.build_board(eps, set(), live, {}, {}, C.load_config(Path("/nonexistent")), {"enabled": False}, NOW)
    assert "gpu33:2" not in b.lanes
    decs = SH.decide(b, NOW)
    assert decs and all(d["lane"] != "gpu33:2" for d in decs)
    env = FakeEnv(Path("/nonexistent"), pr)
    assert "gpu33:2" not in {ln for ln in env.lanes() if ln in C.load_config(Path("/nonexistent"))["lanes"]}


# ---------------------------------------------------------------- 成人
def test_adult_shots_excluded_from_dag_and_decisions():
    reg = ep2(3)
    b, info, _, _ = build(two_hosts({}, reg), adult={"ep02-S2"})
    assert "first:ep02-S2" not in b.tasks and "video:ep02-S2" not in b.tasks
    assert info["adult_skipped"] == 1
    assert all("ep02-S2" not in d["task"] for d in SH.decide(b, NOW))


def test_all_adult_episode_has_no_assembly_and_is_not_active():
    reg = {"3": {"asm": None, "shots": {"ep03-S1": shot(first="ready", last="pending", fa=0, la=0)}}}
    reg.update(ep2(2, **{"ep02-S1": shot(video="passed")}))
    pr = two_hosts({}, reg)
    eps, _ = SH.merge_registry(pr)
    b, info = SH.build_board(eps, {"ep03-S1"}, SH.live_lanes(pr, LANES), {}, {}, C.load_config(Path("/nonexistent")), ROLES, NOW)
    assert "assembly:ep03" not in b.tasks and info["active_ep"] == 2


def test_adult_wait_events_feed_the_adult_set(tmp_path):
    pr = two_hosts({}, ep2(2))
    pr["gpu36"]["adult_wait"] = ["ep02-S2"]
    r = SH.tick(FakeEnv(tmp_path, pr), seeds=1)
    assert "first:ep02-S2" not in r["row"]["tasks"]


# ---------------------------------------------------------------- 终态
def test_terminal_states_respected():
    reg = ep2(3, **{"ep02-S1": shot(first="best_effort", last="pending", la=0, lu=1),       # 尾帧不可用 → I2VA
                    "ep02-S2": shot(video="best_effort"), "ep02-S3": shot(video="passed")})
    b, info, _, _ = build(two_hosts({}, reg))
    assert b.tasks["first:ep02-S1"]["state"] == "adopted" and b.tasks["last:ep02-S1"]["state"] == "adopted"
    assert b.tasks["video:ep02-S1"]["state"] == "ready"
    assert b.tasks["video:ep02-S2"]["state"] == "adopted" and b.tasks["video:ep02-S3"]["state"] == "passed"
    done = {t for t, x in b.tasks.items() if x["state"] in C.DONE}
    assert not any(d["task"] in done for d in SH.decide(b, NOW))


def test_assembled_episode_skipped():
    reg = {"1": {"asm": "passed", "shots": {"ep01-S1": shot(first="ready", last="pending", fa=0)}}}
    reg.update(ep2(1))
    b, info, _, _ = build(two_hosts({}, reg))
    assert info["eps"] == [2] and "first:ep01-S1" not in b.tasks


def test_gate_and_asset_holds_block_dispatch():
    ev = [[NOW - 60, "sop_gate_block", "first:ep02-S1", None, None, None, "SOP 闸门：提示词证据过期", None, None]]
    reg = ep2(2, **{"ep02-S2": shot(first="ready", last="pending", assets="pending", fa=0, la=0)})
    b, info, _, _ = build(two_hosts({}, reg, events=ev))
    assert "first:ep02-S1" in info["gate_holds"] and "ep02-S2" in info["asset_holds"]
    assert not SH.decide(b, NOW)
    ev2 = [[NOW - 60, "sop_gate_block", "first:ep02-S1", None, None, None, "刷新中，镜 输入未变仍可派", None, None]]
    b2, info2, _, _ = build(two_hosts({}, ep2(1), events=ev2))
    assert not info2["gate_holds"]


# ---------------------------------------------------------------- 阶段 / 工位
def test_frames_phase_roles_and_video_only_on_video_lane():
    reg = ep2(3, **{"ep02-S1": shot(video="pending")})
    b, info, _, _ = build(two_hosts({}, reg))
    decs = {d["lane"]: d for d in SH.decide(b, NOW)}
    assert decs["gpu36:2"]["kind"] == "video"
    assert "gpu33:3" not in decs                                   # 审图位不出图
    assert all(d["kind"] in ("first", "last") for ln, d in decs.items() if ln != "gpu36:2")


def test_c2_fallback_to_videos_when_no_frame_work():
    reg = ep2(2, **{"ep02-S1": shot(video="pending"), "ep02-S2": shot(first="pending", last="pending", assets="pending", fa=0, la=0)})
    b, info, _, _ = build(two_hosts({}, reg))
    assert info["phase"] == "videos"
    assert b.lanes["gpu33:0"]["allow_models"] == ["video"] and b.lanes["gpu33:3"]["vqa_slots"] == 1


def test_live_phase_split_detected():
    pr = two_hosts({}, ep2(1))
    pr["gpu33"]["lrs"] = {"2": {"phase": "videos"}, "_active": {"ep": 2, "phase": "videos"}}
    ph = SH.live_phase_split(pr, 2, "frames")
    assert ph["split"] and ph["differs_from_shadow"]


# ---------------------------------------------------------------- 差异归因
def _dec(lane, task):
    return {"lane": lane, "task": task, "kind": task.split(":")[0], "ep": SH.ep_of(SH.shot_of(task))}


def test_classify_idle_categories():
    pr = two_hosts({}, ep2(2))
    ph = SH.live_phase_split(pr, 2, "frames")
    cat, mech, _ = SH.classify_idle("gpu33:0", _dec("gpu33:0", "first:ep02-S1"), pr, ph, NOW, ROLES)
    assert (cat, mech) == ("partition", "M1")                    # ep02 归 gpu36，gpu33 的 producer 不派
    pr["gpu36"]["lrs"] = {"2": {"phase": "videos"}, "_active": {"ep": 2, "phase": "videos"}}
    ph = SH.live_phase_split(pr, 2, "frames")
    cat, mech, _ = SH.classify_idle("gpu36:0", _dec("gpu36:0", "first:ep02-S1"), pr, ph, NOW, ROLES)
    assert (cat, mech) == ("live_phase_split", "M4")
    pr = two_hosts({}, ep2(2), events=[[NOW - 100, "rescore_dispatch", "first:ep02-S1", None, None, None, "", None, None]])
    ph = SH.live_phase_split(pr, 2, "frames")
    assert SH.classify_idle("gpu36:0", _dec("gpu36:0", "first:ep02-S1"), pr, ph, NOW, ROLES)[0] == "live_waiting_rescore"
    pr = two_hosts({}, ep2(2), partition={"data/state/netfix/partition.json": {"temp_holds": {"gpu36:0": {"active": True, "by": "ASSET-WORKER"}}}})
    assert SH.classify_idle("gpu36:0", _dec("gpu36:0", "first:ep02-S1"), pr, ph, NOW, ROLES)[:2] == ("asset_hold", "M12")


def test_classify_window_categories():
    prev = {"t": NOW - 60, "eps": [2, 3],
            "decisions": [_dec("gpu36:0", "first:ep02-S1"), _dec("gpu36:1", "first:ep02-S2"), _dec("gpu36:2", "video:ep02-S3"),
                          _dec("gpu33:0", "first:ep02-S4"), _dec("gpu33:1", "last:ep02-S5"), _dec("gpu33:3", "first:ep02-S6")],
            "lanes": {ln: {"state": "idle"} for ln in ("gpu36:0", "gpu36:1", "gpu36:2", "gpu33:0", "gpu33:1", "gpu33:3", "gpu99:0", "gpu98:0", "gpu97:0")},
            "instant": {"gpu33:3": {"cat": "partition", "mech": "M1", "why": "x"}},
            "tasks": {"first:ep02-S9": "P", "last:ep02-S8": "X"}}
    live = [{"t": NOW - 30, "lane": "gpu36:0", "task": "first:ep02-S1", "model": "image", "src": "producer@gpu36"},
            {"t": NOW - 30, "lane": "gpu36:1", "task": "video:ep02-S7", "model": "video", "src": "vidgen@gpu36"},
            {"t": NOW - 30, "lane": "gpu36:2", "task": "first:ep02-S10", "model": "image", "src": "producer@gpu36"},
            {"t": NOW - 30, "lane": "gpu33:0", "task": "first:ep03-S1", "model": "image", "src": "producer@gpu33"},
            {"t": NOW - 30, "lane": "gpu33:1", "task": "last:ep02-S6", "model": "image", "src": "producer@gpu33"},
            {"t": NOW - 30, "lane": "gpu99:0", "task": "first:ep02-S9", "model": "image", "src": "x"},
            {"t": NOW - 30, "lane": "gpu98:0", "task": "last:ep02-S8", "model": "image", "src": "x"},
            {"t": NOW - 30, "lane": "gpu97:0", "task": "video:ep01-S3", "model": "video", "src": "vidgen@gpu33"}]
    rows = {r["lane"]: r for r in SH.classify_window(prev, live, prev["tasks"], NOW)}
    assert rows["gpu36:0"]["cat"] == "agree"
    assert rows["gpu36:1"]["cat"] == "shadow_frames_first"
    assert rows["gpu36:2"]["cat"] == "shadow_video_priority"
    assert rows["gpu33:0"]["cat"] == "episode_order"
    assert rows["gpu33:1"]["cat"] == "rank_order"
    assert rows["gpu33:3"]["cat"] == "live_left_idle:partition" and rows["gpu33:3"]["mech"] == "M1"
    assert rows["gpu99:0"]["cat"] == "live_redo_settled"
    assert rows["gpu98:0"]["cat"] == "live_ahead_of_deps"
    assert rows["gpu97:0"]["cat"] == "live_work_on_closed_ep"
    prev2 = dict(prev, decisions=[_dec("gpu36:0", "first:ep02-S1")])
    live2 = [{"t": NOW - 30, "lane": "gpu36:0", "task": "video:ep01-S1", "model": "video", "src": "vidgen@gpu36"}]
    assert SH.classify_window(prev2, live2, {}, NOW)[0]["cat"] == "live_work_on_closed_ep"


def test_not_in_any_control_only():
    pr = two_hosts({}, ep2(2))
    pr["gpu36"]["ctrl"]["only"] = ["ep02-S1"]
    ph = SH.live_phase_split(pr, 2, "frames")
    assert SH.classify_idle("gpu36:0", _dec("gpu36:0", "first:ep02-S2"), pr, ph, NOW, ROLES)[0] == "not_in_control_only"


def test_same_task_other_lane():
    prev = {"t": NOW - 60, "decisions": [_dec("gpu36:0", "first:ep02-S1")], "lanes": {"gpu36:0": {"state": "idle"}}, "tasks": {}}
    live = [{"t": NOW - 30, "lane": "gpu36:1", "task": "first:ep02-S1", "model": "image", "src": "p"}]
    rows = {r["lane"]: r for r in SH.classify_window(prev, live, {}, NOW)}
    assert rows["gpu36:0"]["cat"] == "same_task_other_lane" and rows["gpu36:1"]["cat"] == "lane_freed_midwindow"


def test_video_submits_not_double_counted():
    pr = two_hosts({}, ep2(1), vidgen=[[NOW - 100, "SUBMIT", "ep02-S1", "v1", "gpu36:2", None]],
                   vstate={"ep02-S1": {"status": "rendering", "renders": [["v1", "gpu36:2", NOW - 99, None, "submitted"]]}})
    ds = SH.live_dispatches(pr, NOW - 300, NOW)
    assert [d["task"] for d in ds] == ["video:ep02-S1"]


def test_live_busy_lane_occupies_task():
    q = {"gpu36:1": {"running": [{"agent": "PRODUCER", "obj": "first:ep02-S1", "models": ["qwen_image"]}], "pending": 0}}
    b, info, _, live = build(two_hosts({}, ep2(2), queues=q))
    assert live["gpu36:1"]["state"] == "busy" and b.lanes["gpu36:1"]["busy"] == "first:ep02-S1"
    assert b.tasks["first:ep02-S1"]["state"] == "running"
    assert all(d["task"] != "first:ep02-S1" for d in SH.decide(b, NOW))


# ---------------------------------------------------------------- 一拍落盘 + 窗口
class FakeEnv(SH.Env):
    def __init__(self, root, probes, now=NOW):
        super().__init__(root)
        self.probes, self._now = probes, now

    def now(self):
        return self._now

    def run(self):
        return "series10_v2"

    def sched_cfg(self):
        return C.load_config(Path("/nonexistent"))

    def roles_cfg(self):
        return ROLES

    def lanes(self):
        return dict(LANES)

    def adult_ids(self, run):
        return set()

    def probe(self, host, run, since, lanes, timeout=90):
        return json.loads(json.dumps(self.probes[host]))


def test_tick_writes_decisions_diff_metrics_report(tmp_path):
    pr = two_hosts({}, ep2(3, **{"ep02-S1": shot(video="pending")}))
    r1 = SH.tick(FakeEnv(tmp_path, pr), every_s=60, seeds=1)
    assert r1["row"]["decisions"] and all(d["lane"] != "gpu33:2" for d in r1["row"]["decisions"])
    out = tmp_path / SH.OUT_REL
    assert (out / "decisions.jsonl").exists() and (out / "metrics.json").exists()
    assert (tmp_path / SH.REPORT_REL).read_bytes().count(b"\r\n") > 5          # 新报告 CRLF（docs/master 惯例）
    first = r1["row"]["decisions"][0]
    pr["gpu36"]["events"] = [[NOW + 30, "dispatch", first["task"], first["lane"], 1, None, "", None, None]]
    r2 = SH.tick(FakeEnv(tmp_path, pr, now=NOW + 60), every_s=60, seeds=1)
    cats = {x["lane"]: x["cat"] for x in r2["window"]}
    assert cats[first["lane"]] == "agree"
    M = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert M["ticks"] == 2 and M["minutes"] == 1.0 and M["cats"].get("agree") == 1
    assert len((out / "decisions.jsonl").read_text(encoding="utf-8").splitlines()) == 2
    assert r2["projection"]["ep"] == 2 and r2["projection"]["shadow_remaining_min"] is not None


def test_retro_idle_and_switches():
    ev = [[NOW - 3000, "dispatch", "first:ep02-S1", "gpu36:0", 1, None, "", None, None],
          [NOW - 2700, "rendered", "first:ep02-S1", "gpu36:0", None, 300, "", None, None]]
    vg = [[NOW - 2400, "SUBMIT", "ep02-S2", "v1", "gpu36:0", None], [NOW - 1800, "DONE", "ep02-S2", "v1", "gpu36:0", 600.0]]
    pr = two_hosts({}, ep2(2), events=ev, vidgen=vg)
    w = SH.retro(pr, ["gpu36:0"], NOW - 3600, NOW, {})
    assert w["gpu36:0"]["busy_min"] == 15.0 and w["gpu36:0"]["idle_min"] == 45.0 and w["gpu36:0"]["switches"] == 1
