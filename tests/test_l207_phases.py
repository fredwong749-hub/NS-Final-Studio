"""L-207（项目方 11-06：“首尾帧一旦做完，下一步就是全部显卡做视频”）+ L-206 复审 C1 / C2 / MINOR 1 / 3 / 6（L207-PHASES）：
① 一集严格三段：frames → videos（6 张卡含 gpu33:3）→ assembly → 下一集 frames；run 级唯一排序源 lane_roles_state.json <run>._active（粘性）；
② C2：首尾帧阶段没有可派 / 在跑的首尾帧活 → videos；定下数 20 min 没变 → videos；视频侧 / 巡检镜像同一口径；
③ 阶段钩子：审图实例 frames 3 ↔ videos 1（review_instances.sh scale N；后台线程、幂等、失败不炸）；
④ C1：资产作业不借审图位、视频段一条不借、首尾帧段只借出图位；
⑤ MINOR 1 预取深度按道（ep01 旧行为不受影响）；MINOR 3 审图位连续没结论 → 看图退旧路由；MINOR 6 night 等闸门 15 min；
⑥ 视频打分路由 / gpu33 审图位内网入口脚本 / 分片排除表不挡视频段的 gpu33:3。全部临时目录 + 桩，不碰 GPU / 网络。"""
from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools/autopilot", "tools/pipeline", "tools/series10_video", "tools", "services/render_router", "services/agent",
           "services/post", "packages/schema", "services/recipes", "."):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))
import producer as PR  # noqa: E402
import lane_roles_producer as LRO  # noqa: E402
import lane_roles as LR  # noqa: E402
import asset_worker as AW  # noqa: E402
from ns_agent.vqa import client as C  # noqa: E402


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


IW = _load("idle_watch_l207", "tools/autopilot/idle_watch.py")

RUN = "tv_l207"
ALL6 = ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1", "gpu36:2"]
IMG4 = ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1"]
CFG = {
    "enabled": True, "from_episode": 2,
    "phases": {"frames": {"image": IMG4, "review": ["gpu33:3"], "video": ["gpu36:2"]},
               "videos": {"image": [], "review": ["gpu33:3"], "video": ALL6}},
    "image_prefetch_depth": 1,
    "review": {"vqa_instances": 3, "lane": "gpu33:3", "port_base": 8870, "lan_url": "http://10.0.0.33:8870",
               "vqa_instances_by_phase": {"frames": 3, "videos": 1}},
    "hold_regen_downstream": True, "frames_idle_fallback_s": 1200,
}


def _write_cfg(root: Path, cfg=CFG):
    p = root / "config/pipeline/lane_roles.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return p


def _obj(kind, sid, ep, status="ready", **kw):
    return {"id": f"{kind}:{sid}", "kind": kind, "shot": sid, "ep": ep, "status": status, "attempts": 0, **kw}


def _shot(ep, i, first="passed", last="passed", video="pending", **kw):
    sid = f"ep{ep:02d}-S{i}"
    return {"shot": sid, "index": i, "objects": {"first": _obj("first", sid, ep, first), "last": _obj("last", sid, ep, last),
                                                 "video": _obj("video", sid, ep, video)}, **kw}


def _ep(ep, shots, assembly="pending"):
    return {"ep": ep, "shots": list(shots), "objects": {"assembly": _obj("assembly", f"ep{ep:02d}", ep, assembly)}}


def _reg(*eps, run=RUN):
    return {"run": run, "episodes": [E if "objects" in E else _ep(E["ep"], E["shots"]) for E in eps]}


# ================================================================ ① 契约 + 纯函数
def test_shipped_config_l207_contract():
    cfg = LRO.load_cfg(ROOT)
    assert LRO.lanes_for(cfg, "videos", "video") == ALL6                               # 视频段 6 张卡，含审图位 gpu33:3
    assert LRO.lanes_for(cfg, "videos", "image") == [] and LRO.lanes_for(cfg, "frames", "review") == ["gpu33:3"]
    assert LRO.vqa_instances_for(cfg, "frames") == 3 and LRO.vqa_instances_for(cfg, "videos") == 1
    assert LRO.vqa_instances_for({**cfg, "review": {**cfg["review"], "vqa_instances_by_phase": {"videos": 9}}}, "videos") == 3   # 不超上限
    assert LRO.frames_idle_fallback_s(cfg) == 1200.0 and LRO.frames_idle_fallback_s({}) == LRO.FRAMES_IDLE_S
    lp = cfg["review"]["lan_proxy"]
    assert lp["enabled"] is False                                                     # PS-MASTER 11-06 21:xx：内网入口要项目方批准才开（审图内网入口）
    assert lp["bind"].startswith("10.") and lp["allow"] == ["10.0.0.36"] and lp["port"] == 8870   # 参数仍只许内网地址 / 白名单
    assert "gpu33:2" not in json.dumps(cfg["phases"])
    assert LRO.review_scale_cmd(cfg, 1, "/root/repo") == "cd /root/repo && bash tools/vqa/review_instances.sh scale 1"


def test_c2_phase_rules():
    # 全定下 → videos；0 定下 → frames（不管别的）
    assert LRO.episode_phase(_ep(2, [_shot(2, 1), _shot(2, 2)])) == "videos"
    assert LRO.episode_phase(_ep(2, [_shot(2, 1, first="pending", last="pending"), _shot(2, 2, first="failed", last="pending")])) == "frames"
    # ≥1 定下 + 其余只有 pending（等资产 / 导入）/ failed（卡死）→ 没有可派的首尾帧活 → videos（不再卡在 frames、视频只用 1 张卡）
    stuck = _ep(2, [_shot(2, 1), _shot(2, 2, first="pending", last="pending"), _shot(2, 3, first="failed", last="pending")])
    assert LRO.episode_phase(stuck) == "videos"
    assert LRO.frame_work_left(stuck) == {"ready": 0, "running": 0}
    # 还有 ready / running 的首尾帧 → frames（回切也走这条：卡住的镜就绪了）
    busy = _ep(2, [_shot(2, 1), _shot(2, 2, first="ready", last="pending")])
    assert LRO.episode_phase(busy) == "frames"
    run_ = _ep(2, [_shot(2, 1), _shot(2, 2, first="passed", last="running")])
    assert LRO.episode_phase(run_) == "frames"
    # 时间兜底：定下数 20 min 没变、没有 running → videos；有 running 不兜底；定下数变了（settled_at 刷新）不兜底
    t0 = 1_000_000.0
    prev = {"settled_n": 1, "settled_at": t0}
    assert LRO.episode_phase(busy, prev=prev, now=t0 + 600) == "frames"
    assert LRO.episode_phase(busy, prev=prev, now=t0 + 1201) == "videos"
    assert LRO.episode_phase(run_, prev=prev, now=t0 + 5000) == "frames"
    assert LRO.episode_phase(busy, prev={"settled_n": 0, "settled_at": t0}, now=t0 + 5000) == "frames"
    assert LRO.episode_phase(busy, prev=prev, now=t0 + 5000, idle_s=9999) == "frames"
    # 成人镜不计：成人镜 ready 不算活、不挡切段
    adult = _ep(2, [_shot(2, 1), _shot(2, 2, first="ready", last="pending")])
    assert LRO.episode_phase(adult, adult={"ep02-S2"}) == "videos"
    assert LRO.settled_count(adult, adult={"ep02-S2"}) == 1


def test_stage_and_active_sticky():
    reg = _reg(_ep(2, [_shot(2, 1, video="passed"), _shot(2, 2, video="best_effort")]),                  # 视频全定下，合成没出 → assembly
               _ep(3, [_shot(3, 1, video="running"), _shot(3, 2, video="ready")]),                           # 首尾帧全定下，视频在出 → videos
               _ep(4, [_shot(4, 1, first="ready", last="pending")]),                                          # frames
               _ep(5, [_shot(5, 1, video="passed")], assembly="passed"),                                      # done
               _ep(6, []),                                                                                    # 没导入 → frames（排队）
               _ep(1, [_shot(1, 1, first="ready")]))                                                          # ep01 不归它管
    stg = LRO.episode_stages(reg, CFG)
    assert stg == {2: "assembly", 3: "videos", 4: "frames", 5: "done", 6: "frames"}
    assert LRO.episode_stage(_ep(2, [_shot(2, 1, first="ready")]), adult={"ep02-S1"}) == "done"              # 全是成人镜 = 没活
    act = LRO.active_episode(stg)
    assert act["ep"] == 3 and act["phase"] == "videos" and act["stages"]["2"] == "assembly"                    # 最小的在占卡的集
    # 粘性：上一拍 active 是 4（frames），3 回切到 videos 也不抢
    assert LRO.active_episode(stg, {"ep": 4, "phase": "frames"})["ep"] == 4
    assert LRO.active_episode(stg, {"ep": 2, "phase": "videos"})["ep"] == 3                                  # 2 已进合成 → 换最小的
    assert LRO.active_episode({2: "assembly", 5: "done"}) is None
    assert LRO.active_episode({}) is None


def test_write_state_active_settled_and_read_back(tmp_path):
    logs = []
    log = lambda ev, **kw: logs.append((ev, kw))  # noqa: E731
    st = LRO.write_state(tmp_path, RUN, {2: "frames", 3: "frames"}, t=1000.0, log=log, active={"ep": 2, "phase": "frames", "stages": {"2": "frames", "3": "frames"}},
                         settled={2: 0, 3: 0}, stages={2: "frames", 3: "frames"})
    a = st[RUN]["_active"]
    assert a["ep"] == 2 and a["phase"] == "frames" and a["switches"] == 0 and a["prev_ep"] is None and a["since"] == LRO._iso(1000.0)
    assert st[RUN]["2"]["settled_n"] == 0 and st[RUN]["2"]["settled_at"] == 1000.0 and st[RUN]["2"]["stage"] == "frames"
    assert LRO.read_active(RUN, tmp_path) == {**a, "ep": 2} and LRO.read_phase(RUN, 2, tmp_path) == "frames"
    # 定下数变了：阶段不变也要更新 settled_n / settled_at（C2 时间兜底的依据）
    LRO.write_state(tmp_path, RUN, {2: "frames", 3: "frames"}, t=1500.0, active={"ep": 2, "phase": "frames"}, settled={2: 1, 3: 0})
    r2 = json.loads((tmp_path / "data/pipeline/lane_roles_state.json").read_text(encoding="utf-8"))[RUN]["2"]
    assert r2["settled_n"] == 1 and r2["settled_at"] == 1500.0 and r2["since"] == LRO._iso(1000.0)
    # 阶段切换：settled 没变 → settled_at 保留；active 切 → since / 计次 / prev
    LRO.write_state(tmp_path, RUN, {2: "videos", 3: "frames"}, t=2000.0, log=log, active={"ep": 2, "phase": "videos"}, settled={2: 1, 3: 0})
    d = json.loads((tmp_path / "data/pipeline/lane_roles_state.json").read_text(encoding="utf-8"))[RUN]
    assert d["2"]["phase"] == "videos" and d["2"]["settled_at"] == 1500.0
    assert d["_active"] == {**d["_active"], "ep": 2, "phase": "videos", "switches": 1, "prev_ep": 2, "prev_phase": "frames"}
    LRO.write_state(tmp_path, RUN, {2: "videos", 3: "frames"}, t=3000.0, log=log, active={"ep": 3, "phase": "frames"})
    d = json.loads((tmp_path / "data/pipeline/lane_roles_state.json").read_text(encoding="utf-8"))[RUN]
    assert d["_active"]["ep"] == 3 and d["_active"]["switches"] == 2 and d["_active"]["prev_ep"] == 2
    LRO.write_state(tmp_path, RUN, {2: "videos", 3: "videos"}, t=4000.0, log=log, active=None)
    d = json.loads((tmp_path / "data/pipeline/lane_roles_state.json").read_text(encoding="utf-8"))[RUN]
    assert d["_active"] is None and LRO.read_active(RUN, tmp_path) is None
    acts = [kw for ev, kw in logs if ev == "lane_roles_active"]
    assert [(x["ep"], x["phase"]) for x in acts] == [(2, "frames"), (2, "videos"), (3, "frames"), (None, None)]
    assert LR.active_from_state(RUN, tmp_path / "data/pipeline/lane_roles_state.json") is None       # 视频侧读同一文件
    assert LRO.read_active("nope", tmp_path) is None


def test_lanes_now_strict_phasing():
    act = {"ep": 2, "phase": "videos"}
    assert LRO.lanes_now(CFG, {2: "videos", 3: "frames"}, 3, "image", act) == []           # 下一集首尾帧等 ep02 视频全定下
    assert LRO.lanes_now(CFG, {2: "videos", 3: "frames"}, 2, "image", act) == []           # 视频段出图位为空
    assert LRO.lanes_now(CFG, {2: "videos", 3: "frames"}, 3, "video", act) == ALL6         # 视频道按 active 段
    act = {"ep": 2, "phase": "frames"}
    assert LRO.lanes_now(CFG, {2: "frames", 3: "frames"}, 2, "image", act) == IMG4
    assert LRO.lanes_now(CFG, {2: "frames", 3: "frames"}, 3, "image", act) == []
    assert LRO.lanes_now(CFG, {2: "frames"}, 1, "image", act) is None                       # ep01 旧行为
    assert LRO.lanes_now(CFG, {3: "frames"}, 3, "image", None) == IMG4                      # 没有 active（旧 L-206）
    assert "ep02" in LRO.wait_reason(act, 3) and "L-207" in LRO.wait_reason(act, 3)
    assert "视频阶段" in LRO.wait_reason({"ep": 2, "phase": "videos"}, 2)


def test_asset_lane_policy_c1():
    assert LRO.asset_lane_policy({"enabled": False}, None) == {"allow": None, "deny": [], "why": "lane_roles 关"}
    p = LRO.asset_lane_policy(CFG, None)
    assert p["allow"] is None and p["deny"] == ["gpu33:3"]                                   # 没有集在占卡：只禁审图位
    p = LRO.asset_lane_policy(CFG, {"ep": 2, "phase": "frames"})
    assert p["allow"] == IMG4 and "gpu33:3" in p["deny"]
    p = LRO.asset_lane_policy(CFG, {"ep": 2, "phase": "videos"})
    assert p["allow"] == [] and "视频段" in p["why"]


def test_review_scale_tick_idempotent_and_failure_safe(tmp_path):
    calls, logs = [], []
    log = lambda ev, **kw: logs.append((ev, kw))  # noqa: E731

    def runner(cfg, root, n, timeout_s):
        calls.append(n)
        return (0, f"scaled {n}") if n == 1 else (3, "VRAM_TOO_LOW")
    assert LRO.review_scale_tick({"enabled": False}, tmp_path, "videos", runner=runner) is None
    assert LRO.review_scale_tick({**CFG, "review": {**CFG["review"], "vqa_instances_by_phase": None}}, tmp_path, "videos", runner=runner) is None
    assert LRO.review_scale_tick(CFG, tmp_path, None, runner=runner) is None
    r = LRO.review_scale_tick(CFG, tmp_path, "videos", log=log, runner=runner, now=1000.0, wait=True)
    assert r["launched"] and r["want"] == 1 and calls == [1]
    sc = LRO.read_scale(tmp_path)
    assert sc["want"] == 1 and sc["ok"] and sc["rc"] == 0 and sc["phase"] == "videos"
    assert LRO.review_scale_tick(CFG, tmp_path, "videos", log=log, runner=runner, now=1001.0, wait=True)["skipped"] == "already"   # 幂等
    assert calls == [1]
    r = LRO.review_scale_tick(CFG, tmp_path, "frames", log=log, runner=runner, now=2000.0, wait=True)   # 下一集首尾帧：3，失败不炸
    assert r["launched"] and calls == [1, 3]
    sc = LRO.read_scale(tmp_path)
    assert sc["want"] == 3 and sc["ok"] is False and sc["rc"] == 3 and "VRAM" in sc["tail"]
    assert LRO.review_scale_tick(CFG, tmp_path, "frames", log=log, runner=runner, now=2100.0, wait=True)["skipped"] == "retry_wait"
    assert LRO.review_scale_tick(CFG, tmp_path, "frames", log=log, runner=runner, now=sc["done_t"] + 601, wait=True)["launched"]  # 10 min 后再试
    assert calls == [1, 3, 3]
    evs = [kw for ev, kw in logs if ev == "review_scale"]
    assert [(e["want"], e["ok"]) for e in evs] == [(1, True), (3, False), (3, False)] and evs[0]["rule"] == "L-207"

    def boom(cfg, root, n, timeout_s):
        raise RuntimeError("ssh down")
    r = LRO.review_scale_tick(CFG, tmp_path / "b", "videos", log=log, runner=boom, now=5000.0, wait=True)
    assert r["launched"] and LRO.read_scale(tmp_path / "b")["rc"] == -1 and "ssh down" in LRO.read_scale(tmp_path / "b")["tail"]


def test_default_scale_runner_refuses_other_server(monkeypatch, tmp_path):
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    rc, tail = LRO.default_scale_runner(CFG, tmp_path, 1, 10)
    assert rc == -2 and "gpu36" in tail                                                       # 服务器之间无互信：不是审图台不跑


# ================================================================ ② producer：严格分段派单 / 阶段钩子 / 按道深度 / 审图退路
def _producer(tmp_path, monkeypatch, lanes=ALL6, cfg=CFG):
    if cfg is not None:
        _write_cfg(tmp_path, cfg)
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd", run_id=RUN)
    paths.pd.mkdir(parents=True, exist_ok=True)
    pr = PR.Producer(paths, script=object(), lanes={ln: f"http://x/{ln}" for ln in lanes}, lane_probe=lambda u: {"ok": True, "n": 0},
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)
    pr.events = []
    pr.logf = lambda ev, **kw: pr.events.append((ev, kw))
    pr.sent = []
    pr.pool.submit = lambda fn, o, lane, attempt, rung, tag: pr.sent.append((o["id"], lane))
    pr.leases.acquire = lambda oid, **kw: True
    monkeypatch.setattr(PR, "higher_priority_busy", lambda p: {})
    monkeypatch.setattr(PR, "decision_file_problems", lambda run=None: [])
    monkeypatch.setattr(PR, "asset_hold_objects", lambda *a, **k: set())
    monkeypatch.setattr(PR, "local_only_shots", lambda s: set())
    monkeypatch.setattr(PR, "adult_shot_ids", lambda s: set())
    monkeypatch.setattr(PR, "owner_trigger_ids", lambda p: set())
    monkeypatch.setattr(PR, "prefetch_depth", lambda: 2)
    for name, val in (("sop_gate_block", False), ("hard_capped", False), ("obj_rate_exceeded", False)):
        setattr(pr, name, lambda o, *a, _v=val, **k: _v)
    pr.rung_strategy = lambda o, a, led: None
    pr.rung_ab = lambda o, a: None
    pr.rung = lambda o, a: {"name": "t", "seed": 1}
    pr.scale_calls = []
    pr._scale_runner = lambda cfg, root, n, timeout_s: (pr.scale_calls.append(n), (0, "ok"))[1]
    return pr


def _lanes(free=ALL6):
    return {ln: {"free": True} for ln in free}


def _join_scale(root):
    th = LRO._SCALE_THREADS.get(str(root))
    if th:
        th.join(10)


def test_producer_strict_phasing_next_episode_waits(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch)
    ctrl = {"workers": {"frames": "producer"}}
    # ep02 首尾帧全定下、视频在出（videos）；ep03 首尾帧 ready → 不派（等 ep02 视频全定下），钩子 scale 1
    reg = _reg(_ep(2, [_shot(2, 1, video="running"), _shot(2, 2, video="ready")]),
               _ep(3, [_shot(3, i, first="ready", last="pending") for i in range(1, 5)]))
    pr.lane_roles_tick(reg)
    _join_scale(tmp_path)
    lr = reg["lane_roles"]
    assert lr["active"]["ep"] == 2 and lr["active"]["phase"] == "videos" and lr["stages"] == {"2": "videos", "3": "frames"}
    assert pr.image_lanes_allowed(3) == set() and pr.image_lanes_allowed(2) == set() and pr.image_lanes_allowed(1) is None
    pr.dispatch_frames(reg, _lanes(), ctrl)
    assert pr.sent == []
    w = [kw for ev, kw in pr.events if ev == "lane_roles_wait"]
    assert w and w[0]["active"] == {"ep": 2, "phase": "videos"} and "ep02" in w[0]["why"] and "L-207" in w[0]["why"]
    assert pr.scale_calls == [1]
    st = json.loads((tmp_path / "data/pipeline/lane_roles_state.json").read_text(encoding="utf-8"))[RUN]
    assert st["_active"]["ep"] == 2 and st["_active"]["phase"] == "videos" and st["2"]["stage"] == "videos" and st["3"]["settled_n"] == 0
    # ep02 视频全定下（合成另跑）→ active 换到 ep03 frames → 4 张出图位各 1 单；钩子 scale 3；审图位 / 视频位不收出图单
    reg = _reg(_ep(2, [_shot(2, 1, video="passed"), _shot(2, 2, video="best_effort")]),
               _ep(3, [_shot(3, i, first="ready", last="pending") for i in range(1, 7)]))
    pr.lane_roles_tick(reg)
    _join_scale(tmp_path)
    assert reg["lane_roles"]["active"] == {**reg["lane_roles"]["active"], "ep": 3, "phase": "frames"} and reg["lane_roles"]["stages"]["2"] == "assembly"
    pr.dispatch_frames(reg, _lanes(), ctrl)
    assert {ln for _, ln in pr.sent} == set(IMG4) and len(pr.sent) == 4
    assert pr.scale_calls == [1, 3]
    st = json.loads((tmp_path / "data/pipeline/lane_roles_state.json").read_text(encoding="utf-8"))[RUN]
    assert st["_active"]["ep"] == 3 and st["_active"]["prev_ep"] == 2 and st["_active"]["switches"] == 1
    # 再一拍没变 → 钩子不重复（幂等）
    pr.lane_roles_tick(reg)
    _join_scale(tmp_path)
    assert pr.scale_calls == [1, 3]
    # ep03 进视频段：全部 6 张卡是视频道（含 gpu33:3）
    reg = _reg(_ep(2, [_shot(2, 1, video="passed")], assembly="passed"), _ep(3, [_shot(3, i, video="ready") for i in range(1, 4)]))
    pr.lane_roles_tick(reg)
    _join_scale(tmp_path)
    assert reg["lane_roles"]["active"]["phase"] == "videos" and reg["lane_roles"]["stages"]["2"] == "done"
    assert LRO.lanes_now(CFG, pr._lr_phases, 3, "video", pr._lr_active) == ALL6 and pr.scale_calls == [1, 3, 1]
    # 全部进合成 / 完成 → active None，钩子保持（没有阶段）
    reg = _reg(_ep(2, [_shot(2, 1, video="passed")], assembly="passed"), _ep(3, [_shot(3, i, video="passed") for i in range(1, 4)]))
    pr.lane_roles_tick(reg)
    assert reg["lane_roles"]["active"] is None and LRO.read_active(RUN, tmp_path) is None


def test_producer_c2_stuck_shots_do_not_block_videos(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch)
    reg = _reg(_ep(2, [_shot(2, 1), _shot(2, 2, first="pending", last="pending", waiting_for="资产"), _shot(2, 3, first="failed", last="pending")]))
    pr.lane_roles_tick(reg)
    assert pr._lr_phases == {2: "videos"} and pr._lr_active["phase"] == "videos"
    # 卡住的镜就绪 → 回切 frames（计次）
    reg = _reg(_ep(2, [_shot(2, 1), _shot(2, 2, first="ready", last="pending"), _shot(2, 3, first="failed", last="pending")]))
    pr.lane_roles_tick(reg)
    st = json.loads((tmp_path / "data/pipeline/lane_roles_state.json").read_text(encoding="utf-8"))[RUN]
    assert pr._lr_phases == {2: "frames"} and st["2"]["switches"] == 1 and st["_active"]["phase"] == "frames"


def test_producer_scale_hook_failure_does_not_break_tick(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch)
    pr._scale_runner = lambda cfg, root, n, timeout_s: (_ for _ in ()).throw(RuntimeError("rssh 255"))
    reg = _reg(_ep(2, [_shot(2, 1, video="ready")]))
    assert pr.lane_roles_tick(reg) == {2: "videos"}
    _join_scale(tmp_path)
    sc = LRO.read_scale(tmp_path)
    assert sc["ok"] is False and "rssh 255" in sc["tail"]
    assert any(ev == "review_scale" and not kw["ok"] for ev, kw in pr.events) and pr._lr_active["ep"] == 2


def test_lane_depth_per_lane_keeps_ep01_old_behaviour(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch)
    reg = _reg(_ep(1, [_shot(1, 1, first="ready")]), _ep(2, [_shot(2, 1, first="ready", last="pending")]))
    pr.lane_roles_tick(reg)
    assert pr.depth == 2                                                                      # 全局深度 = 旧配置（MINOR 1）
    assert pr.lane_depth("gpu33:0") == 1 and pr.lane_depth("gpu36:1") == 1                    # 出图位：每卡 1 单
    assert pr.lane_depth("gpu33:3") == 2 and pr.lane_depth("gpu36:2") == 2                    # 审图位 / 视频位（ep01 旧行为的道）：旧深度
    lanes = pr.probe_lanes({})
    assert lanes["gpu33:0"]["prefetch"] == 1 and lanes["gpu36:2"]["prefetch"] == 2
    reg = _reg(_ep(2, [_shot(2, 1, video="ready")]))
    pr.lane_roles_tick(reg)
    assert pr.lane_depth("gpu33:0") == 2                                                       # 视频段：没有出图位
    pr2 = _producer(tmp_path, monkeypatch, cfg={**CFG, "enabled": False})
    pr2.lane_roles_tick(_reg(_ep(2, [_shot(2, 1, first="ready")])))
    assert pr2.lane_depth("gpu33:0") == 2


def test_review_fallback_after_n_infra_rounds(tmp_path, monkeypatch):
    monkeypatch.delenv("VQA_REVIEW_FALLBACK", raising=False)
    pr = _producer(tmp_path, monkeypatch)
    pr._lr_cfg = CFG
    assert pr.review_fallback(3, "first:ep02-S1") is False and "VQA_REVIEW_FALLBACK" not in os.environ
    assert pr.review_fallback(PR.REVIEW_FALLBACK_ROUNDS, "first:ep02-S1") is True and os.environ["VQA_REVIEW_FALLBACK"] == "1"
    on = [kw for ev, kw in pr.events if ev == "review_fallback"]
    assert len(on) == 1 and on[0]["on"] and on[0]["rounds"] == PR.REVIEW_FALLBACK_ROUNDS
    pr.review_fallback(PR.REVIEW_FALLBACK_ROUNDS + 1, "x")
    assert len([kw for ev, kw in pr.events if ev == "review_fallback"]) == 1                 # 只记一次
    # client：退路开着 → 不再只认审图位（本机 / 隧道 / 内网入口照旧路由）
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    monkeypatch.setattr(C, "_lane_roles_cfg", lambda: CFG)
    monkeypatch.setattr(C, "_ready", lambda u: (True, 0))
    assert C._review_local_only([("http://127.0.0.1:8870", "local")]) is False
    monkeypatch.setenv("VQA_REVIEW_ONLY", "1")
    monkeypatch.setattr(C, "_lan_url", lambda: None)
    monkeypatch.setattr(C, "_balance_cands", lambda url: [])
    monkeypatch.setattr(C, "_rcfg", lambda: {})
    monkeypatch.setattr(C, "_ready", lambda u: (False, 0))
    assert C._pick("http://127.0.0.1:8870", 1)[3] == "服务不可用"                              # 走了旧路由（不是“审图位不可达”）
    # 拿到结论 → 撤回退路，恢复只认审图位
    assert pr.review_fallback(0, "first:ep02-S1") is False and "VQA_REVIEW_FALLBACK" not in os.environ
    assert C._pick("http://127.0.0.1:8870", 1)[3] == "审图位不可达"
    monkeypatch.setattr(C, "_ready", lambda u: (True, 0))
    assert C._review_local_only([("http://127.0.0.1:8870", "local")]) is True
    # lane_roles 关 → 退路机制不动
    pr._lr_cfg = {"enabled": False}
    assert pr.review_fallback(99, "x") is False and "VQA_REVIEW_FALLBACK" not in os.environ


# ================================================================ ③ 视频侧：阶段表 _active / C2 镜像 / night 全卡视频 / 分片排除表让位
def _registry(root: Path, ep: int, shots: dict[str, dict[str, str]]):
    eps = {"run": RUN, "episodes": [{"ep": ep, "shots": [
        {"shot": sid, "objects": {k: {"kind": k, "shot": sid, "ep": ep, "status": v} for k, v in st.items()}} for sid, st in shots.items()]}]}
    p = root / "data/producer/runs" / RUN / "registry.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(eps), encoding="utf-8")


def test_vid_phase_of_prefers_run_level_active(tmp_path):
    sp = tmp_path / "data/pipeline/lane_roles_state.json"
    LRO.write_state(tmp_path, RUN, {2: "videos", 3: "frames"}, t=1000.0, active={"ep": 2, "phase": "videos", "stages": {"2": "videos", "3": "frames"}})
    a = LR.active_from_state(RUN, sp)
    assert a["ep"] == 2 and a["phase"] == "videos" and a["stages"] == {"2": "videos", "3": "frames"}
    assert LR.phase_of(RUN, 2, ["ep02-S1"], CFG, tmp_path, sp) == "videos" and LR.phase_of(RUN, 3, ["ep03-S1"], CFG, tmp_path, sp) == "frames"
    assert LR.phase_of(RUN, 1, ["ep01-S1"], CFG, tmp_path, sp) is None
    sp.write_text(json.dumps({RUN: {"_active": {"ep": "x", "phase": "videos"}}}), encoding="utf-8")
    assert LR.active_from_state(RUN, sp) is None
    sp.write_text("{bad", encoding="utf-8")
    assert LR.active_from_state(RUN, sp) is None


def test_vid_compute_phase_c2_mirror(tmp_path):
    ids = ["ep02-S1", "ep02-S2", "ep02-S3"]
    # 没有登记表：只按 takes（没有）→ 一镜没定 = frames（看不到活，不猜）
    assert LR.compute_phase(RUN, 2, ids, tmp_path, CFG, now=1000.0)[0] == "frames"
    # 登记表：1 镜定下，其余 pending / failed → 没活 → videos
    _registry(tmp_path, 2, {"ep02-S1": {"first": "passed", "last": "best_effort"}, "ep02-S2": {"first": "pending", "last": "pending"},
                            "ep02-S3": {"first": "failed", "last": "pending"}})
    ph, pend = LR.compute_phase(RUN, 2, ids, tmp_path, CFG, now=1000.0)
    assert ph == "videos" and "C2" in pend["_"] and set(pend) == {"_", "ep02-S2", "ep02-S3"}
    # 还有 ready → frames；20 min 没变且没 running → videos（本机 settle 记录）；有 running 不兜底
    _registry(tmp_path, 2, {"ep02-S1": {"first": "passed", "last": "passed"}, "ep02-S2": {"first": "ready", "last": "pending"},
                            "ep02-S3": {"first": "failed", "last": "pending"}})
    assert LR.compute_phase(RUN, 2, ids, tmp_path, CFG, now=2000.0)[0] == "frames"
    assert LR.compute_phase(RUN, 2, ids, tmp_path, CFG, now=2000.0 + 1199)[0] == "frames"
    assert LR.compute_phase(RUN, 2, ids, tmp_path, CFG, now=2000.0 + 1201)[0] == "videos"
    _registry(tmp_path, 2, {"ep02-S1": {"first": "passed", "last": "passed"}, "ep02-S2": {"first": "running", "last": "pending"},
                            "ep02-S3": {"first": "failed", "last": "pending"}})
    assert LR.compute_phase(RUN, 2, ids, tmp_path, CFG, now=9000.0)[0] == "frames"
    # 定下数变了 → 重新计时
    _registry(tmp_path, 2, {"ep02-S1": {"first": "passed", "last": "passed"}, "ep02-S2": {"first": "passed", "last": "passed"},
                            "ep02-S3": {"first": "ready", "last": "pending"}})
    assert LR.compute_phase(RUN, 2, ids, tmp_path, CFG, now=9100.0)[0] == "frames"
    rec = json.loads((tmp_path / "data/pipeline" / f"lane_roles_settle_{RUN}.json").read_text(encoding="utf-8"))["2"]
    assert rec == {"settled_n": 2, "settled_at": 9100.0}
    assert LR.compute_phase(RUN, 2, ids, tmp_path, CFG, now=9100.0 + 1300)[0] == "videos"
    # 全定下 / 0 定下
    _registry(tmp_path, 2, {s: {"first": "passed", "last": "passed"} for s in ids})
    assert LR.compute_phase(RUN, 2, ids, tmp_path, CFG)[0] == "videos"
    _registry(tmp_path, 2, {s: {"first": "pending", "last": "pending"} for s in ids})
    assert LR.compute_phase(RUN, 2, ids, tmp_path, CFG, now=99999.0)[0] == "frames"


@pytest.fixture
def night_v2(monkeypatch, tmp_path):
    orig = os.environ.get("NS_RUN")
    import night as N
    os.environ["NS_RUN"] = "series10_v2"
    N = importlib.reload(N)
    vid = tmp_path / "run" / "series10_v2" / "video"
    vid.mkdir(parents=True)
    monkeypatch.setattr(N, "VID", vid)
    monkeypatch.setattr(N, "LOG", vid / "night.log")
    try:
        yield N
    finally:
        monkeypatch.undo()
        if orig is None:
            os.environ.pop("NS_RUN", None)
        else:
            os.environ["NS_RUN"] = orig
        importlib.reload(N)


def _specs(ep, n=3):
    return {ep: [SimpleNamespace(id=f"ep{ep:02d}-S{i}", episode=ep) for i in range(1, n + 1)]}


def test_night_roles_follow_run_level_active_all_six_video_lanes(night_v2, monkeypatch):
    N = night_v2
    (N.VID / "hosts.json").write_text(json.dumps({"2": "gpu36", "3": "gpu33"}), encoding="utf-8")
    monkeypatch.setattr(LR, "load", lambda path=None: CFG)
    phases = {2: "videos", 3: "frames"}
    monkeypatch.setattr(LR, "phase_of", lambda run, ep, ids, cfg=None, root=None, state_path=None: phases.get(int(ep)))
    monkeypatch.setattr(N, "_VS", lambda: None)
    st = {"eps": {"2": {"status": "rendering"}, "3": {"status": "rendering"}}}
    # 没有 run 级 active（旧 L-206）：gpu33 有 ep03 在 frames → 最保守 frames → gpu33 没视频道
    monkeypatch.setattr(LR, "active_from_state", lambda run, path=None: None)
    r = N.roles_for_host("gpu33", {**_specs(2), **_specs(3)}, st, {2: ["ep02-S1"]})
    assert r is None or r["phase"] == "frames"
    # run 级 active = ep02 videos → 两台都按 videos：gpu33 三道（含 gpu33:3）全是视频道、不挂
    monkeypatch.setattr(LR, "active_from_state", lambda run, path=None: {"ep": 2, "phase": "videos", "stages": {}})
    r = N.roles_for_host("gpu33", _specs(3), st, {})
    assert r["phase"] == "videos" and r["lanes"] == {"video": ["gpu33:0", "gpu33:1", "gpu33:3"], "hold": []} and r["active"] == {"ep": 2, "phase": "videos"}
    r = N.roles_for_host("gpu36", _specs(2), st, {2: ["ep02-S1"]})
    assert r["phase"] == "videos" and r["lanes"]["video"] == ["gpu36:0", "gpu36:1", "gpu36:2"]
    # active 换到 ep03 frames → gpu33 回到出图位 + 审图位挂住、gpu36 只剩 gpu36:2
    monkeypatch.setattr(LR, "active_from_state", lambda run, path=None: {"ep": 3, "phase": "frames", "stages": {}})
    assert N.roles_for_host("gpu33", _specs(3), st, {})["lanes"] == {"video": [], "hold": ["gpu33:0", "gpu33:1", "gpu33:3"]}
    assert N.roles_for_host("gpu36", _specs(2), st, {2: ["ep02-S1"]})["lanes"]["video"] == ["gpu36:2"]


def test_night_shard_exclude_yields_to_lane_roles_video_lane(night_v2, monkeypatch):
    N = night_v2
    VS = SimpleNamespace(exclude_lanes=lambda host: ["gpu33:3"] if host == "gpu33" else [],
                         shard_eps=lambda run: {2: {"owner": "gpu36", "hosts": ["gpu36", "gpu33"]}})
    monkeypatch.setattr(N, "_VS", lambda: VS)
    assert N._shard_hold("gpu33", []) == ["gpu33:3"]                                                             # 旧：分片排除 gpu33:3
    st_v = {"lane_roles": {"gpu33": {"phase": "videos", "eps": {"2": "videos"}, "lanes": {"video": ["gpu33:0", "gpu33:1", "gpu33:3"], "hold": []}}}}
    assert N._shard_hold("gpu33", [], st_v) == []                                                                # 视频段：lane_roles 列为视频道 → 不挂
    st_f = {"lane_roles": {"gpu33": {"phase": "frames", "lanes": {"video": [], "hold": ["gpu33:0", "gpu33:1", "gpu33:3"]}}}}
    assert N._shard_hold("gpu33", ["gpu33:0"], st_f) == ["gpu33:0", "gpu33:3"]                                   # 首尾帧段照旧排除
    assert N._shard_hold("gpu33", [], {"lane_roles": {"gpu33": None}}) == ["gpu33:3"]
    c = {"hold_lanes": [], "shared_lanes": ["gpu33:0", "gpu33:1", "gpu33:3"], "yield_s": 30}
    N.roles_control("gpu33", st_v, c)
    assert c["video_lanes"] == ["gpu33:0", "gpu33:1", "gpu33:3"] and c["hold_lanes"] == [] and c["shared_lanes"] == []
    if not os.environ.get("NS_HOLD_RESOLVE_S"):
        assert N.HOLD_RESOLVE_S == 900                                                                             # MINOR 6：15 min


# ================================================================ ④ 巡检 / 资产工人
LANES = {ln: {"host": ln.split(":")[0]} for ln in ALL6}


def test_idle_watch_roles_follow_active(tmp_path):
    reg = _reg(_ep(2, [_shot(2, 1, video="ready")]), _ep(3, [_shot(3, i, first="ready", last="pending") for i in range(1, 4)]))
    m = IW.lane_roles_map(LRO, CFG, reg, LANES, active={"ep": 2, "phase": "videos"})
    assert m["gpu33:3"]["roles"] == {"review", "video"} and all("video" in m[ln]["roles"] for ln in ALL6)
    assert all("image" not in m[ln]["roles"] for ln in ALL6) and sum(r["img_ready"] for r in m.values()) == 0     # 下一集 ready 不算活
    assert m["gpu33:0"]["phases"] == {2: "videos", 3: "videos"}
    m = IW.lane_roles_map(LRO, CFG, reg, LANES, active={"ep": 3, "phase": "frames"})
    assert m["gpu33:0"]["roles"] == {"image"} and m["gpu33:0"]["img_ready"] == 3 and m["gpu33:3"]["roles"] == {"review"}
    assert m["gpu36:2"]["roles"] == {"video"}
    m0 = IW.lane_roles_map(LRO, CFG, reg, LANES)                                                                    # 没有 active：旧 L-206 逐集
    assert m0["gpu33:0"]["img_ready"] == 3 and m0["gpu33:0"]["phases"] == {2: "videos", 3: "frames"}
    # C2 同口径：prev 记录让巡检也判 videos
    reg2 = _reg(_ep(2, [_shot(2, 1), _shot(2, 2, first="ready", last="pending")]))
    m = IW.lane_roles_map(LRO, CFG, reg2, LANES, prev={"2": {"settled_n": 1, "settled_at": time.time() - 5000}})
    assert m["gpu33:0"]["phases"] == {2: "videos"}


class _H:
    @staticmethod
    def lanes(role="image"):
        return ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1", "gpu36:2"]


def test_asset_worker_free_lanes_policy_c1(tmp_path, monkeypatch):
    monkeypatch.setattr(AW, "broken_lanes", lambda h: {"gpu33:2"})
    monkeypatch.setattr(AW, "_lanes_mod", lambda: None)
    probe = lambda l: {"ok": True, "busy": False}  # noqa: E731
    assert AW.free_lanes({}, set(), part={}, probe=probe, hosts_mod=_H) == _H.lanes()                              # 没政策：旧行为
    assert AW.free_lanes({}, set(), part={}, probe=probe, hosts_mod=_H, policy={"allow": None, "deny": ["gpu33:3"]}) == \
        ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1", "gpu36:2"]
    assert AW.free_lanes({}, set(), part={}, probe=probe, hosts_mod=_H, policy={"allow": IMG4, "deny": ["gpu33:3"]}) == IMG4
    assert AW.free_lanes({}, set(), part={}, probe=probe, hosts_mod=_H, policy={"allow": [], "deny": ["gpu33:3"]}) == []
    # lane_roles_policy：读配置 + 状态文件
    assert AW.lane_roles_policy(tmp_path, {RUN: 2})["allow"] is None                                             # 没配置 = 关
    _write_cfg(tmp_path)
    assert AW.lane_roles_policy(tmp_path, {RUN: 2}) == {"allow": None, "deny": ["gpu33:3"], "why": "没有集在占卡：只禁审图位"}
    LRO.write_state(tmp_path, RUN, {2: "videos"}, t=1.0, active={"ep": 2, "phase": "videos"})
    pol = AW.lane_roles_policy(tmp_path, {RUN: 2, "other": 1})
    assert pol["allow"] == [] and "视频段" in pol["why"]
    LRO.write_state(tmp_path, RUN, {3: "frames"}, t=2.0, active={"ep": 3, "phase": "frames"})
    assert AW.lane_roles_policy(tmp_path, {RUN: 3})["allow"] == IMG4
    LRO.write_state(tmp_path, RUN, {3: "videos"}, t=3.0, active=None)
    assert AW.lane_roles_policy(tmp_path, {RUN: 3})["allow"] is None


# ================================================================ ⑤ 脚本 / 文档契约
def test_review_instances_scale_and_review_lan_proxy_scripts():
    sh = (ROOT / "tools/vqa/review_instances.sh").read_text(encoding="utf-8")
    assert "scale)" in sh and "stop_ports" in sh and "start_instances" in sh and "server_$p.pid" in sh
    assert "pkill" not in sh and "killall" not in sh                                                              # 只停自己 pid 文件里的
    assert '"$K" -le "$N"' in sh and "unload_models" in sh                                                        # K ≤ N；起实例前让 ComfyUI 卸模型
    px = (ROOT / "tools/netfix/review_lan_proxy.sh").read_text(encoding="utf-8")
    assert "lan_proxy.py" in px and "review.lan_proxy" in px and "10.*" in px and "DISABLED" in px
    rs = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    assert "def review_lan_proxy_keepalive" in rs and "review_lan_proxy.sh" in rs
    import score_clip as SC
    assert callable(SC.review_route)
    env = LR.review_env(CFG, offline_self="gpu36")
    assert env == {"VQA_LAN": "1", "VQA_LAN_URL": "http://10.0.0.33:8870", "VQA_REVIEW_ONLY": "1"}                # gpu36 打分 → gpu33 审图位内网入口
    assert LR.review_env(CFG, offline_self="gpu33") == {"VQA_URL": "http://127.0.0.1:8870", "VQA_LAN_URL": ""}
    vs = json.loads((ROOT / "config/pipeline/video_shard.json").read_text(encoding="utf-8-sig"))
    assert "L-207" in vs["exclude_lanes"]["_why"]


def test_checklist_doc_three_stages():
    doc = (ROOT / "docs/master/PIPELINE_CHECKLIST.md").read_text(encoding="utf-8")
    for k in ("L-207", "L-206", "首尾帧", "全部 6", "gpu33:3", "合成", "50", "scale", "review_instances.sh", "lane_roles_state.json"):
        assert k in doc, k
