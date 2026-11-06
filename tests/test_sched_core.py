"""SCHED-CORE（11-06）：全局工作板 tools/sched/core.py 的纯函数测试（不读真实 data/、不连服务器）。"""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("sched_core_t", ROOT / "tools/sched/core.py")
C = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(C)


def cfg(**pol):
    c = C.load_config(Path("/nonexistent"))
    c["policies"]["lane_stale_s"] = 0
    c["policies"].update(pol)
    return c


def board(**pol):
    b = C.Board(cfg(**pol))
    for lid in b.lanes:
        b.lane_seen(lid, 0.0)
    return b


def run_to_pass(b, tid, now, lane="gpu33:0", ok=True, score=0.8):
    """把一个 ready 任务在某道上走完：lease → rendered → 打分"""
    b.refresh(now)
    le = b.lease(tid, lane, now)
    b.start(le["token"], now)
    st = b.rendered(le["token"], now + 100, secs=100)
    if st == "scoring":
        job = b.next_score_job("gpu33:3", now + 100)
        assert job["task"] == tid
        return b.scored(job["token"], now + 150, ok, score)
    return st


# ---------- DAG 就绪（按镜判，L-202） ----------
def test_dag_readiness_per_shot():
    b = board()
    C.build_episode(b, 1, ["S1", "S2"], assets={"S1": ["face:林晚"], "S2": ["face:林晚", "scene:attic"]})
    r = {t["id"] for t in b.ready_tasks(0)}
    assert r == {"face:林晚", "scene:attic"}                       # 镜都等资产；资产本身可做
    assert run_to_pass(b, "face:林晚", 0) == "passed"
    r = {t["id"] for t in b.ready_tasks(200)}
    assert "first:ep01-S1" in r and "first:ep01-S2" not in r       # S1 的资产齐了就放行，S2 还等底图
    assert "last:ep01-S1" not in r and "video:ep01-S1" not in r
    assert run_to_pass(b, "first:ep01-S1", 200) == "passed"
    assert "last:ep01-S1" in {t["id"] for t in b.ready_tasks(400)}
    assert run_to_pass(b, "last:ep01-S1", 400) == "passed"
    assert "video:ep01-S1" in {t["id"] for t in b.ready_tasks(600)}
    assert b.tasks["assembly:ep01"]["state"] == "blocked"


def test_never_gpu33_2():
    b = board()
    assert "gpu33:2" not in b.lanes
    with pytest.raises(C.SchedError):
        b.add_lane("gpu33:2")
    tmp = ROOT / "tests/fixtures/_sched_bad_lane.json"
    try:
        tmp.write_text(json.dumps({"lanes": {"gpu33:2": {"host": "gpu33"}, "gpu33:0": {"host": "gpu33"}}}), encoding="utf-8")
        assert "gpu33:2" not in C.load_config(tmp)["lanes"]
    finally:
        tmp.unlink(missing_ok=True)
    d = b.to_dict()
    d["lanes"]["gpu33:2"] = dict(d["lanes"]["gpu33:0"], id="gpu33:2")
    assert "gpu33:2" not in C.Board.from_dict(d, cfg()).lanes


# ---------- 换代失效 ----------
def test_regen_invalidates_downstream_and_drops_stale_result():
    b = board()
    C.build_episode(b, 1, ["S1"])
    assert run_to_pass(b, "first:ep01-S1", 0) == "passed"
    assert run_to_pass(b, "last:ep01-S1", 200) == "passed"
    b.refresh(400)
    le = b.lease("video:ep01-S1", "gpu36:0", 400)          # 视频在跑
    affected = b.regen("first:ep01-S1", 500, reason="L-203 首尾太像")
    assert set(affected) == {"first:ep01-S1", "last:ep01-S1", "video:ep01-S1", "assembly:ep01"}
    assert b.tasks["last:ep01-S1"]["state"] == "blocked" and b.tasks["last:ep01-S1"]["attempts"] == 0
    assert {t["id"] for t in b.ready_tasks(500)} == {"first:ep01-S1"}
    # 旧首帧的视频出完了 → 按版本号丢弃，道释放，任务回 ready/blocked 不算尝试
    assert b.rendered(le["token"], 900, secs=400) == "stale"
    assert b.lanes["gpu36:0"]["busy"] is None
    assert b.tasks["video:ep01-S1"]["attempts"] == 0 and b.tasks["video:ep01-S1"]["state"] == "blocked"
    b.refresh(900)
    assert b.tasks["video:ep01-S1"]["state"] == "blocked"


# ---------- 亲和（换模型代价） ----------
def test_affinity_prefers_loaded_model_when_rank_gap_small():
    b = board()
    C.build_episode(b, 1, ["S1", "S2"])
    for s in ("S1",):
        run_to_pass(b, f"first:ep01-{s}", 0)
        run_to_pass(b, f"last:ep01-{s}", 200)
    b.refresh(400)
    # 现在 ready：first:S2（image，rank 大）与 video:S1（video）。video 道该拿 video，image 道该拿 first
    b.lanes["gpu36:2"]["loaded_model"] = "video"
    b.lanes["gpu33:1"]["loaded_model"] = "image"
    plan = dict((lid, tid) for lid, tid, _ in b.plan(400, lane_ids=["gpu36:2", "gpu33:1"]))
    assert plan["gpu36:2"] == "video:ep01-S1" and plan["gpu33:1"] == "first:ep01-S2"
    # 只有一个 video 任务、道上载的是 image、换模型代价 ≥ 任务本身的秩差 → 仍然按秩（rank − cost）决定；代价设成极大则不切
    b2 = board()
    C.build_episode(b2, 1, ["S1"])
    run_to_pass(b2, "first:ep01-S1", 0)
    run_to_pass(b2, "last:ep01-S1", 200)
    b2.refresh(400)
    b2.lanes["gpu33:0"]["loaded_model"] = "image"
    assert b2.plan(400, lane_ids=["gpu33:0"])[0][1] == "video:ep01-S1"      # 没别的活：切也要切（不空卡，L-202）


def test_switch_penalty_in_cost():
    b = board()
    C.build_episode(b, 1, ["S1"])
    t = b.tasks["video:ep01-S1"]
    b.lanes["gpu33:0"]["loaded_model"] = "image"
    b.lanes["gpu33:1"]["loaded_model"] = "video"
    assert b.cost(t, b.lanes["gpu33:0"]) - b.cost(t, b.lanes["gpu33:1"]) == pytest.approx(b.cfg["switch_penalty_s"]["image->video"])
    assert b.est("first", "gpu36:0") > b.est("first", "gpu33:0")         # gpu36 慢（speed 1.25）


# ---------- 关键路径优先 ----------
def test_critical_path_priority_first_before_last_before_video():
    b = board()
    C.build_episode(b, 1, ["S1", "S2"])
    r = b.ranks()
    assert r["first:ep01-S1"] > r["last:ep01-S1"] > r["video:ep01-S1"] > r["assembly:ep01"]
    # 两镜同时 ready 的 first：秩相同 → 按 id 确定性；完成一镜后其下游优先于别的集
    b.refresh(0)
    plan = b.plan(0, lane_ids=["gpu33:0", "gpu33:1"])
    assert {tid for _, tid, _ in plan} == {"first:ep01-S1", "first:ep01-S2"}
    assert plan == b.plan(0, lane_ids=["gpu33:0", "gpu33:1"])             # 确定性


def test_episode_order_earlier_first():
    b = board(phase_gate="off")
    C.build_episode(b, 2, ["S1"])
    C.build_episode(b, 1, ["S1"])
    b.refresh(0)
    plan = b.plan(0, lane_ids=["gpu33:0"])
    assert plan[0][1] == "first:ep01-S1"


# ---------- 尝试 → 采用 ----------
def test_attempts_then_adopt_best_unblocks_downstream():
    b = board()
    C.build_episode(b, 1, ["S1"])
    for i, sc in enumerate((0.3, 0.9, 0.5)):
        b.refresh(i * 1000)
        assert b.tasks["first:ep01-S1"]["state"] == "ready"
        st = run_to_pass(b, "first:ep01-S1", i * 1000, ok=False, score=sc)
    assert st == "adopted" and b.tasks["first:ep01-S1"]["best"]["attempt"] == 2
    assert b.tasks["first:ep01-S1"]["attempts"] == 3
    b.refresh(5000)
    assert b.tasks["last:ep01-S1"]["state"] == "ready"
    # auto_adopt 关 → 停在 best_effort，等手工 adopt
    b2 = board(auto_adopt=False)
    C.build_episode(b2, 1, ["S1"])
    for i in range(3):
        b2.refresh(i * 1000)
        st = run_to_pass(b2, "first:ep01-S1", i * 1000, ok=False, score=0.1 * i)
    assert st == "best_effort"
    b2.refresh(5000)
    assert b2.tasks["last:ep01-S1"]["state"] == "blocked"
    assert b2.adopt("first:ep01-S1", 5000)
    b2.refresh(5001)
    assert b2.tasks["last:ep01-S1"]["state"] == "ready"


# ---------- 租约超时换道 ----------
def test_lease_timeout_requeues_on_another_lane():
    b = board(lease_ttl_s=100, lane_down_after_timeouts=2)
    C.build_episode(b, 1, ["S1"])
    b.refresh(0)
    le = b.lease("first:ep01-S1", "gpu33:0", 0)
    assert b.heartbeat(le["token"], 50)
    assert b.expire(120) == []                              # 心跳在 50，120−50 < 100
    assert b.expire(200) == ["first:ep01-S1"]
    t = b.tasks["first:ep01-S1"]
    assert t["state"] == "ready" and t["attempts"] == 0 and t["avoid_lanes"] == ["gpu33:0"]
    assert b.lanes["gpu33:0"]["busy"] is None and b.lanes["gpu33:0"]["health"] == "ok"
    plan = b.plan(200)
    assert plan and plan[0][0] != "gpu33:0"
    # 再超时一次 → 道标 down，不再派
    le = b.lease("first:ep01-S1", "gpu33:0", 200)           # 显式派回同道（avoid 只是软约束 plan 用）
    b.expire(400)
    assert b.lanes["gpu33:0"]["health"] == "down"
    assert all(lid != "gpu33:0" for lid, _, _ in b.plan(400))


# ---------- 三段策略（L-207） ----------
def test_phase_policy_strict_blocks_next_episode_frames_until_videos_settle():
    b = board(phase_gate="strict")
    C.build_episode(b, 1, ["S1"])
    C.build_episode(b, 2, ["S1"], assets={"S1": ["face:黎岸"]})
    ids = {t["id"] for t in b.ready_tasks(0)}
    assert "first:ep01-S1" in ids and "first:ep02-S1" not in ids and "face:黎岸" in ids   # 资产不受三段限制
    run_to_pass(b, "first:ep01-S1", 0)
    run_to_pass(b, "last:ep01-S1", 200)
    run_to_pass(b, "face:黎岸", 300)
    b.refresh(400)
    assert b.episode_phase(1) == "videos"
    assert "first:ep02-S1" not in {t["id"] for t in b.ready_tasks(400)}
    run_to_pass(b, "video:ep01-S1", 400, lane="gpu36:2")
    b.refresh(1000)
    assert b.episode_phase(1) == "assembly"
    assert "first:ep02-S1" in {t["id"] for t in b.ready_tasks(1000)}
    # fill_idle：道空且没别的活 → 放行下一集首尾帧
    b3 = board(phase_gate="fill_idle")
    C.build_episode(b3, 1, ["S1"])
    C.build_episode(b3, 2, ["S1"])
    b3.refresh(0)
    b3.lease("first:ep01-S1", "gpu33:0", 0)
    assert {tid for _, tid, _ in b3.plan(0)} == {"first:ep02-S1"}
    b4 = board(phase_gate="strict")
    C.build_episode(b4, 1, ["S1"])
    C.build_episode(b4, 2, ["S1"])
    b4.refresh(0)
    b4.lease("first:ep01-S1", "gpu33:0", 0)
    assert b4.plan(0) == []


# ---------- 幂等事件 / 序列化 / ETA ----------
def test_idempotent_events_and_roundtrip(tmp_path):
    b = board()
    C.build_episode(b, 1, ["S1"])
    le = b.apply({"id": "e1", "type": "next", "lane": "gpu33:0", "t": 0})
    assert le["task"] == "first:ep01-S1"
    assert b.apply({"id": "e1", "type": "next", "lane": "gpu33:0", "t": 0}) == "dup"
    assert b.apply({"id": "e2", "type": "rendered", "token": le["token"], "t": 100, "secs": 100}) == "scoring"
    assert b.apply({"id": "e2", "type": "rendered", "token": le["token"], "t": 100, "secs": 100}) == "dup"
    assert b.tasks["first:ep01-S1"]["attempts"] == 1
    p = tmp_path / "board.json"
    b.save(p)
    b2 = C.Board.load(p, cfg())
    assert b2.to_dict() == b.to_dict()
    assert b2.apply({"id": "e2", "type": "rendered", "token": le["token"], "t": 100}) == "dup"   # 重放安全
    job = b2.apply({"id": "e3", "type": "next_score", "lane": "gpu33:3", "t": 100})
    assert job["task"] == "first:ep01-S1"
    assert b2.apply({"id": "e4", "type": "scored", "token": job["token"], "t": 190, "ok": True, "score": 0.9}) == "passed"
    assert b2.ewma["first|gpu33:0"] == 100


def test_eta_vs_kpi():
    b = board()
    C.build_episode(b, 1, [f"S{i}" for i in range(1, 17)])
    e = b.eta(0)
    assert e["kpi_s"] == 3000 and e["remaining_s"] >= e["critical_path_s"] > 0 and e["on_track"] is False
    assert e["pending"] == {"first": 16, "last": 16, "video": 16, "assembly": 1} and e["lanes"] == 6
    b2 = board()
    b2.cfg["expected_attempts"] = {"first": 1.0, "last": 1.0, "video": 1.0}
    C.build_episode(b2, 1, ["S1"])
    e2 = b2.eta(0)
    assert e2["on_track"] is True and e2["remaining_s"] == e2["critical_path_s"]     # 一镜一次过：≈ 400+400+475+360 < 3000
