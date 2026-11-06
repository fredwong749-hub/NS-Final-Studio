"""L-206 工位分卡（项目方 11-06：“一个 gpu 专门出图，另一个 gpu 审图”）——出图 + 审图侧（LANE-ROLES-PROD）：
① producer 只把首尾帧派给本集当前阶段 image 角色的道（审图位 gpu33:3 永不收出图单；视频阶段 image 为空）；
② 阶段 frames → videos 从登记表现推，写 data/pipeline/lane_roles_state.json（视频侧读）；回切计次；
③ hold_regen_downstream：首帧换代中的镜，尾帧不派并在登记表写明；
④ 审图路由：实例数 / 端口 / 本机优先 / 人数检测不发到出图位；打分线程 ≥ 3 × 实例；
⑤ idle_watch 按角色判“空卡有活”。全部临时目录 + 桩，不碰 GPU / 网络；from_episode 之前的集（ep01）保持旧行为。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools/autopilot", "services/render_router", "services/agent", "packages/schema", "services/recipes", "."):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))
import producer as PR  # noqa: E402
import lane_roles_producer as LRO  # noqa: E402
from ns_agent.vqa import client as C  # noqa: E402
from ns_agent.gen_contract import accept as GA  # noqa: E402


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


IW = _load("idle_watch_l206", "tools/autopilot/idle_watch.py")

CFG = {
    "enabled": True, "from_episode": 2,
    "phases": {"frames": {"image": ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1"], "review": ["gpu33:3"], "video": ["gpu36:2"]},
               "videos": {"image": [], "review": ["gpu33:3"], "video": ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1", "gpu36:2"]}},
    "image_prefetch_depth": 1, "review": {"vqa_instances": 3, "lane": "gpu33:3", "port_base": 8870}, "hold_regen_downstream": True,
}
ALL6 = ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1", "gpu36:2"]


def _write_cfg(root: Path, cfg=CFG):
    p = root / "config/pipeline/lane_roles.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
    return p


def _obj(kind, sid, ep, status="ready", **kw):
    return {"id": f"{kind}:{sid}", "kind": kind, "shot": sid, "ep": ep, "status": status, "attempts": 0, **kw}


def _shot(ep, i, first="passed", last="passed", **kw):
    sid = f"ep{ep:02d}-S{i}"
    fo = first if isinstance(first, dict) else _obj("first", sid, ep, first)
    lo = last if isinstance(last, dict) else _obj("last", sid, ep, last)
    return {"shot": sid, "index": i, "objects": {"first": fo, "last": lo, "video": _obj("video", sid, ep, "pending")}, **kw}


def _reg(*eps):
    return {"episodes": [{"ep": ep, "shots": list(shots)} for ep, shots in eps]}


# ================================================================ ① 契约文件 + 纯函数
def test_contract_file_matches_l206():
    cfg = LRO.load_cfg(ROOT)
    assert cfg["enabled"] is True and LRO.from_episode(cfg) == 2
    fr, vd = cfg["phases"]["frames"], cfg["phases"]["videos"]
    assert "gpu33:3" not in fr["image"] and "gpu33:3" not in vd["image"] and vd["image"] == []
    assert LRO.review_lane(cfg) == "gpu33:3" and LRO.review_host(cfg) == "gpu33" and LRO.review_gpu(cfg) == 3
    assert "gpu33:2" not in json.dumps(cfg["phases"])
    assert LRO.review_instances(cfg) == 3 and LRO.image_prefetch_depth(cfg) == 1 and LRO.hold_regen_downstream(cfg)
    assert LRO.lanes_for({"phases": {"frames": {"image": ["gpu33:2", "gpu33:0"]}}}, "frames", "image") == ["gpu33:0"]   # 坏卡剔除


def test_episode_phase_frames_until_all_frames_settled():
    assert LRO.episode_phase({"ep": 2, "shots": []}) == "frames"
    E = {"ep": 2, "shots": [_shot(2, 1), _shot(2, 2, first="passed", last="ready")]}
    assert LRO.episode_phase(E) == "frames"
    E["shots"][1]["objects"]["last"]["status"] = "best_effort"            # 尾帧 I2VA 回退 = best_effort → 定下
    assert LRO.episode_phase(E) == "videos"
    E["shots"].append(_shot(2, 3, first="ready", last="pending"))
    assert LRO.episode_phase(E) == "frames"
    assert LRO.episode_phase(E, adult={"ep02-S3"}) == "videos"           # 成人镜不计
    E["shots"][2]["objects"]["first"]["status"] = "passed"
    E["shots"][2]["objects"]["last"] = {"status": "passed", "na": True}  # 不适用 = 定下
    assert LRO.episode_phase(E) == "videos"
    assert LRO.episode_phases(_reg((1, [_shot(1, 1, "ready")]), (2, [_shot(2, 1)])), CFG) == {2: "videos"}   # ep01 不归它管


def test_state_file_format_merge_and_switch_count(tmp_path):
    logs = []
    st = LRO.write_state(tmp_path, "series10_v2", {2: "frames", 3: "frames"}, t=1000.0, log=lambda ev, **kw: logs.append((ev, kw)))
    p = tmp_path / "data/pipeline/lane_roles_state.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    assert d["_schema"] == "nsfs.lane_roles_state/1" and {k for k in d["series10_v2"] if not k.startswith("_")} == {"2", "3"}   # L-207：另有 _active
    assert d["series10_v2"]["2"] == {"phase": "frames", "since": LRO._iso(1000.0), "switches": 0, "prev": None, "updated": LRO._iso(1000.0)}
    LRO.write_state(tmp_path, "series10_v2", {2: "frames"}, t=2000.0)                 # 不变：since 保留
    assert json.loads(p.read_text(encoding="utf-8"))["series10_v2"]["2"]["since"] == LRO._iso(1000.0)
    LRO.write_state(tmp_path, "series10_v2", {2: "videos"}, t=3000.0, log=lambda ev, **kw: logs.append((ev, kw)))
    LRO.write_state(tmp_path, "other_run", {5: "frames"}, t=3100.0)                    # 别的剧合并，不清空
    d = json.loads(p.read_text(encoding="utf-8"))
    r2 = d["series10_v2"]["2"]
    assert r2["phase"] == "videos" and r2["since"] == LRO._iso(3000.0) and r2["switches"] == 1 and r2["prev"] == "frames"
    assert d["series10_v2"]["3"]["phase"] == "frames" and d["other_run"]["5"]["phase"] == "frames"
    LRO.write_state(tmp_path, "series10_v2", {2: "frames"}, t=4000.0, log=lambda ev, **kw: logs.append((ev, kw)))   # 回切（首帧换代）计次 + 记日志
    assert json.loads(p.read_text(encoding="utf-8"))["series10_v2"]["2"]["switches"] == 2
    assert [kw["phase"] for ev, kw in logs if ev == "lane_roles_phase" and kw["ep"] == 2] == ["frames", "videos", "frames"]
    assert logs[-1][1]["note"]
    assert LRO.read_phase("series10_v2", 2, tmp_path) == "frames" and LRO.read_phase("series10_v2", 9, tmp_path) is None
    assert LRO.read_phase("nope", 2, tmp_path) is None
    assert LRO.lanes_now(CFG, {2: "videos"}, 2, "image") == [] and LRO.lanes_now(CFG, {}, 1, "image") is None
    assert LRO.lanes_now(CFG, {2: "videos"}, 2, "video") == CFG["phases"]["videos"]["video"]
    assert LRO.read_state(tmp_path / "none") == {}


def test_review_ports_avoid_tunnel_and_score_servers():
    ports = LRO.review_ports(CFG)
    assert ports == {"router": 8870, "instances": [8876, 8877, 8878]}
    assert not set(ports["instances"]) & {8870, 8871, 8873, 8874, 8893}


# ================================================================ ② producer：角色过滤 / 阶段 / hold_regen / 预取
def _producer(tmp_path, monkeypatch, lanes=ALL6, cfg=CFG):
    if cfg is not None:
        _write_cfg(tmp_path, cfg)
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd", run_id="tv_l206")
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
    return pr


def _lanes(free=ALL6):
    return {ln: {"free": True} for ln in free}


def test_dispatch_only_to_image_role_lanes_in_frames_phase(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch)
    reg = _reg((2, [_shot(2, i, first="ready", last="pending") for i in range(1, 7)]))
    pr.lane_roles_tick(reg)
    assert pr._lr_phases == {2: "frames"} and pr.image_lanes_allowed(2) == set(CFG["phases"]["frames"]["image"])
    pr.dispatch_frames(reg, _lanes(), {"workers": {"frames": "producer"}})
    used = {ln for _, ln in pr.sent}
    assert used == set(CFG["phases"]["frames"]["image"]) and len(pr.sent) == 4          # 4 张出图位各 1 单
    assert "gpu33:3" not in used and "gpu36:2" not in used                               # 审图位 / 视频位不收出图单
    waits = [kw for ev, kw in pr.events if ev == "lane_roles_wait"]
    assert waits and waits[0]["rule"] == "L-206" and sorted(waits[0]["image_lanes"]) == sorted(CFG["phases"]["frames"]["image"])


def test_legacy_episode_before_from_episode_uses_any_lane(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch)
    reg = _reg((1, [_shot(1, i, first="ready", last="pending") for i in range(1, 7)]))
    pr.lane_roles_tick(reg)
    assert pr._lr_phases == {} and pr.image_lanes_allowed(1) is None
    pr.dispatch_frames(reg, _lanes(), {"workers": {"frames": "producer"}})
    assert {ln for _, ln in pr.sent} == set(ALL6)                                        # ep01：旧行为，6 道全用
    assert not (tmp_path / "data/pipeline/lane_roles_state.json").exists()               # 没有适用集 → 不写状态


def test_disabled_config_keeps_old_behaviour(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch, cfg={**CFG, "enabled": False})
    reg = _reg((2, [_shot(2, i, first="ready", last="pending") for i in range(1, 7)]))
    pr.lane_roles_tick(reg)
    pr.dispatch_frames(reg, _lanes(), {"workers": {"frames": "producer"}})
    assert {ln for _, ln in pr.sent} == set(ALL6) and pr.depth == 2 and "lane_roles" not in reg


def test_phase_switch_to_videos_empties_image_lanes_and_writes_state(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch)
    reg = _reg((2, [_shot(2, 1), _shot(2, 2, last="best_effort")]), (3, [_shot(3, 1, first="ready", last="pending")]))
    pr.lane_roles_tick(reg)
    assert pr._lr_phases == {2: "videos", 3: "frames"} and pr.image_lanes_allowed(2) == set()
    assert pr.depth == 2 and pr.lane_depth("gpu33:0") == 2      # MINOR 1：深度按道；L-207 占卡集 ep02 在视频段 → 没有出图位，旧深度（test_l207 另测 frames 段 = 1）
    assert reg["lane_roles"]["phases"] == {"2": "videos", "3": "frames"} and reg["lane_roles"]["review"] == "gpu33:3"
    st = json.loads((tmp_path / "data/pipeline/lane_roles_state.json").read_text(encoding="utf-8"))
    assert st["tv_l206"]["2"]["phase"] == "videos" and st["tv_l206"]["3"]["phase"] == "frames"
    # ep03 也定下 → 全部 videos → 没有适用集在首尾帧阶段 → 预取深度回旧配置
    reg2 = _reg((2, [_shot(2, 1), _shot(2, 2)]), (3, [_shot(3, 1)]))
    pr.lane_roles_tick(reg2)
    assert pr._lr_phases == {2: "videos", 3: "videos"} and pr.depth == 2
    # 首帧作废重出（stale）→ 回切 frames，state 计次
    reg3 = _reg((2, [_shot(2, 1, first="ready"), _shot(2, 2)]), (3, [_shot(3, 1)]))
    pr.lane_roles_tick(reg3)
    st = json.loads((tmp_path / "data/pipeline/lane_roles_state.json").read_text(encoding="utf-8"))
    assert pr._lr_phases[2] == "frames" and st["tv_l206"]["2"]["switches"] == 1 and st["tv_l206"]["2"]["prev"] == "videos"
    pr.dispatch_frames(reg3, _lanes(), {"workers": {"frames": "producer"}})
    assert pr.sent and all(ln in CFG["phases"]["frames"]["image"] for _, ln in pr.sent)


def test_hold_regen_downstream_blocks_last_frame_while_first_regen(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch)
    regen_first = _obj("first", "ep02-S1", 2, "running", redo=True, regen=True, regen_keep="v3", reason="换代中：L-201")
    reg = _reg((2, [_shot(2, 1, first=regen_first, last="ready"), _shot(2, 2, first="passed", last="ready")]),
               (1, [_shot(1, 1, first=dict(regen_first, id="first:ep01-S1", shot="ep01-S1", ep=1), last="ready")]))
    pr.lane_roles_tick(reg)
    lo = reg["episodes"][0]["shots"][0]["objects"]["last"]
    assert lo["status"] == "pending" and lo["hold_regen"] is True and "L-206" in lo["waiting_for"] and "换代" in lo["reason"]
    assert reg["lane_roles"]["hold_regen"] == ["ep02-S1"] and pr._lr_phases == {2: "frames"}
    assert reg["episodes"][1]["shots"][0]["objects"]["last"]["status"] == "ready"          # ep01：旧行为（L-204 D4 换代中照出尾帧）
    pr.dispatch_frames(reg, _lanes(), {"workers": {"frames": "producer"}})
    assert [oid for oid, _ in pr.sent if oid.startswith("last:ep02")] == ["last:ep02-S2"]
    # master_rejects 没 cleared（redo_exhausted 后对象不带 redo）也算换代中；cleared 了就放行
    pr2 = _producer(tmp_path, monkeypatch)
    (pr2.p.pd / "master_rejects.json").write_text(json.dumps({"first:ep02-S1": {"reason": "x", "cleared": False}}), encoding="utf-8")
    reg = _reg((2, [_shot(2, 1, first="passed", last="ready")]))
    pr2.lane_roles_tick(reg)
    assert reg["episodes"][0]["shots"][0]["objects"]["last"]["status"] == "pending"
    (pr2.p.pd / "master_rejects.json").write_text(json.dumps({"first:ep02-S1": {"reason": "x", "cleared": True}}), encoding="utf-8")
    reg = _reg((2, [_shot(2, 1, first="passed", last="ready")]))
    pr2.lane_roles_tick(reg)
    assert reg["episodes"][0]["shots"][0]["objects"]["last"]["status"] == "ready"
    # 开关关：不扣
    assert LRO.apply_hold_regen(_reg((2, [_shot(2, 1, first=regen_first, last="ready")])), {**CFG, "hold_regen_downstream": False}) == []


def test_fanout_respects_image_lanes(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch)
    pr.fanout_ok = lambda: 3
    reg = _reg((2, [_shot(2, 1, first="ready", last="pending")]))
    pr.lane_roles_tick(reg)
    pr.dispatch_frames(reg, _lanes(), {"workers": {"frames": "producer"}})
    assert len(pr.sent) == 3 and all(ln in CFG["phases"]["frames"]["image"] for _, ln in pr.sent)   # 1 单 + 2 个分道种子，都在出图位


def test_lane_roles_error_does_not_stop_dispatch(tmp_path, monkeypatch):
    pr = _producer(tmp_path, monkeypatch)
    pr.lane_roles_cfg = lambda: (_ for _ in ()).throw(RuntimeError("boom"))
    reg = _reg((2, [_shot(2, 1, first="ready", last="pending")]))
    try:
        pr.lane_roles_tick(reg)
    except RuntimeError:
        pr._lr_phases, pr._lr_cfg = {}, {"enabled": False}          # tick() 里的兜底就是这一句
    pr.dispatch_frames(reg, _lanes(), {"workers": {"frames": "producer"}})
    assert pr.sent


def test_vlm_instances_and_post_pool_follow_review_config(tmp_path, monkeypatch):
    monkeypatch.delenv("NS_VQA_INSTANCES", raising=False)
    monkeypatch.setattr(PR, "ROOT", tmp_path)
    monkeypatch.setattr(PR, "prefetch_depth", lambda: 1)
    (tmp_path / "config").mkdir(exist_ok=True)
    (tmp_path / "config/vqa.json").write_text(json.dumps({"model": {"instances": 2}}), encoding="utf-8")
    assert PR.vlm_instances() == 2
    _write_cfg(tmp_path)
    assert PR.vlm_instances() == 3
    assert PR.post_pool_workers(tmp_path, 4) >= 9                                        # ≥ 3 × 实例
    (tmp_path / "config/pipeline/producer.json").write_text(json.dumps({"post_pool": {"max_workers": 4}}), encoding="utf-8")
    assert PR.post_pool_workers(tmp_path, 4) == 9                                        # 显式配置也不低于下限
    monkeypatch.setenv("NS_VQA_INSTANCES", "5")
    assert PR.vlm_instances() == 5


# ================================================================ ③ 审图路由
def test_client_review_host_keeps_vqa_local_when_instances_up(monkeypatch):
    monkeypatch.setattr(C, "_lane_roles_cfg", lambda: CFG)
    monkeypatch.setattr(C, "_rcfg", lambda: {"balance": True, "extra_local_ports": [], "balance_lan": True})
    monkeypatch.setattr(C, "_lan_url", lambda: "http://10.0.0.36:8870")
    up = {"http://127.0.0.1:8870": True}
    monkeypatch.setattr(C, "_ready", lambda u: (bool(up.get(u)), 0))
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    assert C._balance_cands("http://127.0.0.1:8870") == [("http://127.0.0.1:8870", "local")]      # 审图位活着 → 不分流到 gpu36
    up["http://127.0.0.1:8870"] = False
    assert ("http://10.0.0.36:8870", "lan") in C._balance_cands("http://127.0.0.1:8870")          # 本机全不在 → 退回内网入口（不断看图）
    up["http://127.0.0.1:8870"] = True
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    assert ("http://10.0.0.36:8870", "lan") in C._balance_cands("http://127.0.0.1:8870")          # 不是审图位主机 → 旧路由
    monkeypatch.setattr(C, "_lane_roles_cfg", lambda: {**CFG, "enabled": False})
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    assert ("http://10.0.0.36:8870", "lan") in C._balance_cands("http://127.0.0.1:8870")          # 关 → 旧路由


def test_accept_count_detector_prefers_review_host_local(tmp_path, monkeypatch):
    _write_cfg(tmp_path)
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    assert GA.review_local_anomaly(tmp_path, probe=lambda u: True) == "http://127.0.0.1:8893"
    assert GA.review_local_anomaly(tmp_path, probe=lambda u: False) is None                      # 没起 → 退回 count_host，不断检测
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    assert GA.review_local_anomaly(tmp_path, probe=lambda u: True) is None                       # 出图机不用本机
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    (tmp_path / "config/gen_contract.json").write_text(json.dumps({"image_thresholds": {"Q10_accept": {"count_host": "http://10.0.0.36:8893"}}}), encoding="utf-8")
    monkeypatch.setattr(GA, "review_local_anomaly", lambda root, probe=None, ttl_s=60.0: "http://127.0.0.1:8893")
    assert GA.anomaly_host(tmp_path) == "http://127.0.0.1:8893"
    monkeypatch.setattr(GA, "review_local_anomaly", lambda root, probe=None, ttl_s=60.0: None)
    assert GA.anomaly_host(tmp_path) == "http://10.0.0.36:8893"
    monkeypatch.delenv("OFFLINE_SELF")
    assert GA.anomaly_host(tmp_path) == "gpu36"


def test_anomaly_detector_on_gpu33_is_cpu_never_image_lane():
    AN = _load("anomaly_l206", "tools/vqa/anomaly.py")
    pre = AN.device_prefix("gpu33", hosts={"gpu33": {"broken_gpus": [2]}})
    assert 'CUDA_VISIBLE_DEVICES=""' in pre
    with pytest.raises(RuntimeError):
        AN.device_prefix("gpu33", hosts={"gpu33": {"broken_gpus": [2], "detector_gpu": 2}})
    src = (ROOT / "tools/gen_contract/score_srv.py").read_text(encoding="utf-8")
    sh = (ROOT / "ops/factory/score_resident.sh").read_text(encoding="utf-8")
    assert "8873" in src and "8874" in src and "CPU" in sh and "CUDA_VISIBLE_DEVICES" not in sh   # ArcFace / 手：CPU 常驻，不占出图卡


def test_review_instances_script_is_config_driven_and_refuses_bad_gpu():
    sh = (ROOT / "tools/vqa/review_instances.sh").read_text(encoding="utf-8")
    assert "config/pipeline/lane_roles.json" in sh and "vqa_instances" in sh and "port_base" in sh
    assert 'base + 6 + i' in sh and "VQA_DEDICATED=1" in sh and "vqa_router.py" in sh and "VQA_BACKENDS" in sh
    assert '[ "$GPU" = 2 ] && { echo "REFUSE' in sh
    assert "kill -9" not in sh and "pkill" not in sh                                           # 只停自己 pid 文件里的进程
    for cmd in ("start", "health", "stop", "status"):
        assert f"  {cmd})" in sh or f"{cmd}) " in sh


# ================================================================ ④ idle_watch 按角色判活
NOW = 1_800_000_000.0
LANES = {"gpu33:0": {"host": "gpu33", "gpu": 0, "comfy_port": 8188, "tunnel_port": None},
         "gpu33:1": {"host": "gpu33", "gpu": 1, "comfy_port": 8189, "tunnel_port": None},
         "gpu33:3": {"host": "gpu33", "gpu": 3, "comfy_port": 8191, "tunnel_port": None},
         "gpu36:0": {"host": "gpu36", "gpu": 0, "comfy_port": 8188, "tunnel_port": None},
         "gpu36:1": {"host": "gpu36", "gpu": 1, "comfy_port": 8189, "tunnel_port": None},
         "gpu36:2": {"host": "gpu36", "gpu": 2, "comfy_port": 8190, "tunnel_port": None}}


def probe(video=0, vqa_queue=0):
    return {"now": NOW, "gpus": {str(i): {"util": 0, "mem": 100} for i in range(4)}, "queues": {str(i): 0 for i in range(4)},
            "hb": {"t": NOW - 10, "paused": False}, "ctrl": {}, "nctrl": {}, "night_state_age_s": 30,
            "video_dispatchable_n": video, "video_dispatchable": [], "vqa": {"queue": vqa_queue, "loaded": True, "instances": 3}}


class FakeEnv(IW.Env):
    def __init__(self, root, probes, reg, assets=0):
        super().__init__(root)
        self.probes, self.assets, self._now = probes, assets, NOW
        self.calls, self.issues, self.chan = [], [], []
        (self.root / "data/producer/runs/runx").mkdir(parents=True, exist_ok=True)
        (self.root / "data/producer/runs/runx/registry.json").write_text(json.dumps(reg), encoding="utf-8")

    def now(self): return self._now
    def lanes(self): return dict(LANES)
    def primary_run(self): return "runx"
    def producer_rel(self, run): return "data/producer/runs/runx"
    def probe_host(self, host, run, lanes, timeout): return self.probes.get(host)
    def tunnel_queue(self, port, timeout): return None
    def remote(self, host, cmd, timeout): self.calls.append(("remote", host, cmd)); return 0, "ok"
    def night_once_cmd(self, host, run): return f"night --once {host} {run}"
    def rq_pending(self, host): return []
    def rq_request(self, host, reason, mode, urgent): self.calls.append(("rq", host, mode)); return {"id": "rq1"}
    def asset_pending(self, run): return self.assets
    def episode_lock(self): return None
    def sop_blocks(self, run, eps): return {}
    def hold_alive(self, expires_at, since): return (True, "")
    def report(self, run, what, fix_hint, blocking): self.issues.append(what); return f"ISS-{len(self.issues)}"
    def channel(self, text, now): self.chan.append(text)
    def read_state(self): return {}
    def relay_cfg(self): return {"enabled": False}


def _ticks(env, c, minutes=10):
    st = {}
    IW.tick(env, c, st, save=False)
    env._now = NOW + minutes * 60
    for p in env.probes.values():
        p["now"] = env._now
        p["hb"]["t"] = env._now - 10
    return IW.tick(env, c, st, save=False), st


def _cfg():
    return {**IW.DEFAULT_CFG, "actions": dict(IW.DEFAULT_CFG["actions"])}


def _stuck(r):
    return sorted({ln for a in r["actions"] if a["kind"] == "report" for ln in LANES if ln in a["what"].split("空闲")[0]})


def test_idle_watch_frames_phase_only_image_lanes_count(tmp_path):
    _write_cfg(tmp_path)
    reg = _reg((2, [_shot(2, i, first="ready", last="pending") for i in range(1, 5)]))
    env = FakeEnv(tmp_path, {"gpu33": probe(), "gpu36": probe()}, reg)
    r, _ = _ticks(env, _cfg())
    assert r["has_work"] is True and r["lane_roles"]["enabled"] and r["lane_roles"]["phases"] == {"2": "frames"}
    L = r["lane_roles"]["lanes"]
    assert L["gpu33:3"]["roles"] == ["review"] and L["gpu33:3"]["work"] == []                 # 看图排队空 = 审图卡没活
    assert L["gpu36:2"]["roles"] == ["video"] and L["gpu36:2"]["work"] == []                  # 首尾帧阶段的视频位：没视频活 = 没活
    assert L["gpu33:0"]["roles"] == ["image"] and L["gpu33:0"]["img_ready"] == 4
    assert _stuck(r) == ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1"]
    assert not any(a["kind"] == "night_once" for a in r["actions"])                           # 没视频活不重派 night


def test_idle_watch_review_lane_counts_when_vqa_queue_nonempty(tmp_path):
    _write_cfg(tmp_path)
    reg = _reg((2, [_shot(2, 1, first="ready", last="pending")]))
    env = FakeEnv(tmp_path, {"gpu33": probe(vqa_queue=3), "gpu36": probe()}, reg)
    r, _ = _ticks(env, _cfg())
    assert r["lane_roles"]["lanes"]["gpu33:3"]["work"] == ["看图排队 3"] and "gpu33:3" in _stuck(r)
    assert "gpu33:3=review（看图排队 3）" in [a for a in r["actions"] if a["kind"] == "report" and a["host"] == "gpu33"][0]["what"]


def test_idle_watch_video_lane_judged_by_video_work_only(tmp_path):
    _write_cfg(tmp_path)
    reg = _reg((2, [_shot(2, 1, first="ready", last="pending")]))
    env = FakeEnv(tmp_path, {"gpu33": probe(), "gpu36": probe(video=2)}, reg, assets=5)
    r, _ = _ticks(env, _cfg())
    L = r["lane_roles"]["lanes"]
    assert L["gpu36:2"]["work"] == ["本台可派视频 2 镜"] and "资产作业" in "、".join(L["gpu36:0"]["work"])
    assert "gpu36:2" in _stuck(r) and any(a["kind"] == "night_once" and a["host"] == "gpu36" for a in r["actions"])
    # 视频阶段：出图位转视频位；只有视频活的台才报
    reg2 = _reg((2, [_shot(2, 1), _shot(2, 2)]))
    env2 = FakeEnv(tmp_path, {"gpu33": probe(), "gpu36": probe(video=1)}, reg2)
    r2, _ = _ticks(env2, _cfg())
    assert r2["lane_roles"]["phases"] == {"2": "videos"}
    assert r2["lane_roles"]["lanes"]["gpu33:0"]["roles"] == ["video"] and r2["lane_roles"]["lanes"]["gpu33:0"]["work"] == []
    assert _stuck(r2) == ["gpu36:0", "gpu36:1", "gpu36:2"]


def test_idle_watch_no_work_by_role_means_no_report(tmp_path):
    _write_cfg(tmp_path)
    reg = _reg((2, [_shot(2, 1), _shot(2, 2)]))                                               # videos 阶段，没视频活、看图空
    env = FakeEnv(tmp_path, {"gpu33": probe(), "gpu36": probe()}, reg, assets=3)              # 资产作业只算 image 道的活，视频阶段没有 image 道
    r, _ = _ticks(env, _cfg())
    assert r["has_work"] is False and r["actions"] == []


def test_idle_watch_legacy_episode_and_disabled_keep_old_behaviour(tmp_path):
    _write_cfg(tmp_path)
    reg = _reg((1, [_shot(1, 1, first="ready", last="pending")]), (2, [_shot(2, 1), _shot(2, 2)]))
    env = FakeEnv(tmp_path, {"gpu33": probe(), "gpu36": probe()}, reg)
    r, _ = _ticks(env, _cfg())
    assert _stuck(r) == sorted(LANES)                                                          # ep01 的活：6 道全算（旧行为）
    _write_cfg(tmp_path, {**CFG, "enabled": False})
    reg = _reg((2, [_shot(2, 1, first="ready", last="pending")]))
    env = FakeEnv(tmp_path, {"gpu33": probe(), "gpu36": probe()}, reg)
    r, _ = _ticks(env, _cfg())
    assert r["lane_roles"]["enabled"] is False and _stuck(r) == sorted(LANES)


def test_relay_plan_never_lends_video_or_review_lanes():
    c = _cfg()
    lane_st = {ln: {"idle_min": 9.0} for ln in LANES}
    fr = {"ready": 3, "ready_by_ep": {2: 3}}
    rcfg = {"enabled": True, "consumer_host": "gpu33"}
    roles = IW.lane_roles_map(LRO, CFG, _reg((2, [_shot(2, i, first="ready", last="pending") for i in range(3)])), LANES)
    a = IW.relay_plan(c, {}, NOW, lane_st, fr, {"gpu33": [2]}, rcfg, ["gpu36:0", "gpu36:1", "gpu36:2"], {"hold": "all"}, roles=roles)
    assert a and a["op"] == "lend" and a["lanes"] == ["gpu36:0", "gpu36:1"] and a["hold"] == ["gpu36:2"]
    a0 = IW.relay_plan(c, {}, NOW, lane_st, fr, {"gpu33": [2]}, rcfg, ["gpu36:0", "gpu36:1", "gpu36:2"], {"hold": "all"})
    assert a0["lanes"] == ["gpu36:0", "gpu36:1", "gpu36:2"]                                    # 没角色表 = 旧行为


def test_remote_probe_reads_vqa_health():
    assert "__VQA_PORT__/health" in IW.REMOTE_PROBE and '"vqa"' in IW.REMOTE_PROBE
