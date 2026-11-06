"""L-206 工位分卡——视频侧（LANE-ROLES-VID 11-06）：config/pipeline/lane_roles.json 唯一来源。
① 阶段：producer 阶段表优先；没有就按 takes / registry 算（首帧 + 尾帧都定下 / 尾帧 i2va 回退 → videos）；
② night：按阶段给每台写 video_lanes（专用、不让道）/ hold_lanes（非视频道）/ lane_roles；ep01（< from_episode）旧行为；
③ vidgen：lane_roles.video 之外的道不派；video_lanes 不受 yield_s；
④ 分片抢活：首尾帧阶段没有视频道的台不抢、名下没开工的镜领给有视频道的台；视频阶段还回；
⑤ hold_regen_downstream：首帧换代中（master_gate.image / master_rejects 未 cleared）的镜视频不派；
⑥ 视频打分看图路由到审图位（review.lane / lan_url），client 只认 10. 内网地址。全部在 tmp_path；不连服务器。"""
from __future__ import annotations

import importlib
import json
import os
import sys
import threading
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/post", "services/agent", "tools", "tools/series10_video", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import lane_roles as LR  # noqa: E402
import video_shard as VS  # noqa: E402
import vidgen as VG  # noqa: E402

RUN = "series10_v2"
CFG = {"enabled": True, "from_episode": 2,
       "phases": {"frames": {"image": ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1"], "review": ["gpu33:3"], "video": ["gpu36:2"]},
                  "videos": {"image": [], "review": ["gpu33:3"], "video": ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1", "gpu36:2"]}},
       "review": {"vqa_instances": 3, "lane": "gpu33:3", "port_base": 8870, "lan_url": "http://10.0.0.33:8870"},
       "hold_regen_downstream": True}
OFF = {**CFG, "enabled": False}


def _take(stage, n, ok=True, at="2026-11-06T10:00:00", **kw):
    return {"stage": stage, "n": n, "file": f"renders/{stage}{n}.png", "created_at": at, "postflight": {"ok": ok}, **kw}


def _takes(root: Path, sid: str, d: dict):
    ep, _, s = sid.partition("-")
    p = root / "data/renders" / RUN / ep / s / "takes.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    return p


def _done(first_at="2026-11-06T10:00:00", **top):
    return {"active": {"image": 3, "last": 2}, "takes": [_take("image", 3, at=first_at), _take("last", 2)], **top}


# ---------------------------------------------------------------- ① 配置 / 道 / 阶段
def test_shipped_config_contract():
    c = LR.load()
    assert c["enabled"] is True and int(c["from_episode"]) == 1   # L-208 ⑤A
    assert LR.lanes("frames", "video", c) == ["gpu36:2"]
    assert LR.lanes("videos", "video", c) == ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0", "gpu36:1", "gpu36:2"]   # L-207：视频阶段 6 卡全上
    assert "gpu33:2" not in json.dumps(c["phases"])                              # 坏卡不在任何道清单里
    assert str(c["review"]["lan_url"]).startswith("http://10.") and c["review"]["lane"] == "gpu33:3"
    import deploy as D
    assert "config/pipeline/lane_roles.json" in D.CODE_FILES


def test_load_fails_closed_and_applies(tmp_path):
    assert LR.load(tmp_path / "missing.json") == {"enabled": False}
    bad = tmp_path / "bad.json"
    bad.write_text("[1,2]", encoding="utf-8")
    assert LR.load(bad) == {"enabled": False}
    assert LR.applies(1, CFG) is False and LR.applies(2, CFG) is True and LR.applies(9, CFG) is True
    assert LR.applies(2, OFF) is False and LR.applies(None, CFG) is False


def test_control_lanes_per_host_and_phase(tmp_path):
    assert LR.control_lanes("gpu33", "frames", CFG) == {"video": [], "hold": ["gpu33:0", "gpu33:1", "gpu33:3"]}
    assert LR.control_lanes("gpu36", "frames", CFG) == {"video": ["gpu36:2"], "hold": ["gpu36:0", "gpu36:1"]}
    assert LR.control_lanes("gpu33", "videos", CFG) == {"video": ["gpu33:0", "gpu33:1"], "hold": ["gpu33:3"]}
    assert LR.control_lanes("gpu36", "videos", CFG) == {"video": ["gpu36:0", "gpu36:1", "gpu36:2"], "hold": []}
    assert LR.host_lanes("gpu33", tmp_path / "nohosts.json") == ["gpu33:0", "gpu33:1", "gpu33:3"]   # 车道表读不到 = 内置表，坏卡不出现
    assert LR.host_can_video("gpu33", "frames", CFG) is False and LR.host_can_video("gpu36", "frames", CFG)


def test_phase_state_file_then_computed(tmp_path):
    st = tmp_path / "state.json"
    assert LR.phase_from_state(RUN, 2, st) is None
    st.write_text(json.dumps({RUN: {"2": {"phase": "videos", "since": "x"}, "3": {"phase": "bogus"}}}), encoding="utf-8")
    assert LR.phase_from_state(RUN, 2, st) == "videos" and LR.phase_from_state(RUN, 3, st) is None
    assert LR.phase_of(RUN, 2, ["ep02-S1"], CFG, tmp_path, st) == "videos"
    assert LR.phase_of(RUN, 1, ["ep01-S1"], CFG, tmp_path, st) is None            # ep01 不适用
    # 没有阶段表 → 按 takes 算：没有 takes = frames
    assert LR.phase_of(RUN, 2, ["ep02-S1"], CFG, tmp_path, tmp_path / "none.json") == "frames"


def test_compute_phase_from_takes(tmp_path):
    ids = ["ep02-S1", "ep02-S2", "ep02-S3"]
    _takes(tmp_path, "ep02-S1", _done())
    _takes(tmp_path, "ep02-S2", {"active": {"image": 1}, "takes": [_take("image", 1)], "last_frame_fallback": "i2va"})   # 尾帧回退 = 定下
    _takes(tmp_path, "ep02-S3", {"active": {"image": 1}, "takes": [_take("image", 1)]})
    ph, pend = LR.compute_phase(RUN, 2, ids, tmp_path)
    assert ph == "frames" and list(pend) == ["ep02-S3"] and "尾帧未定" in pend["ep02-S3"]
    _takes(tmp_path, "ep02-S3", {"active": {"image": 1}, "takes": [_take("image", 1)],
                                 "last_frame_fallback": {"mode": "i2va", "first_n": 1}})
    assert LR.compute_phase(RUN, 2, ids, tmp_path)[0] == "videos"
    # 回退绑定的首帧换了 → 回退作废 → frames
    _takes(tmp_path, "ep02-S3", {"active": {"image": 2}, "takes": [_take("image", 2)],
                                 "last_frame_fallback": {"mode": "i2va", "first_n": 1}})
    assert LR.compute_phase(RUN, 2, ids, tmp_path)[0] == "frames"
    # 首帧换代中 → frames（即使 takes 当前版过契约）
    _takes(tmp_path, "ep02-S3", _done(master_gate={"image": {"at": "2026-11-06T12:00:00", "reason": "regen"}}))
    ph, pend = LR.compute_phase(RUN, 2, ids, tmp_path)
    assert ph == "frames" and "换代中" in pend["ep02-S3"]
    assert LR.compute_phase(RUN, 2, [], tmp_path)[0] == "frames"                   # 没有镜清单 = 保守


def test_compute_phase_registry_fallback(tmp_path):
    reg = tmp_path / "data/producer/runs" / RUN / "registry.json"
    reg.parent.mkdir(parents=True)
    objs = [{"id": f"{k}:ep02-S1", "kind": k, "shot": "ep02-S1", "ep": 2, "status": s} for k, s in (("first", "passed"), ("last", "best_effort"))]
    reg.write_text(json.dumps({"run": RUN, "episodes": [{"ep": 2, "objects": objs}]}), encoding="utf-8")
    assert LR.registry_status(RUN, 2, tmp_path) == {"ep02-S1": {"first": "passed", "last": "best_effort"}}
    assert LR.compute_phase(RUN, 2, ["ep02-S1"], tmp_path)[0] == "videos"
    assert LR.compute_phase(RUN, 2, ["ep02-S1", "ep02-S2"], tmp_path)[0] == "frames"


# ---------------------------------------------------------------- ⑤ hold_regen_downstream
def test_first_under_regen_signals(tmp_path):
    # 闸门比当前首帧新（换代中，新版还没换上）→ hold；当前首帧是闸门之后换上的新版 → 不 hold
    _takes(tmp_path, "ep02-S1", _done(first_at="2026-11-06T10:00:00", master_gate={"image": {"at": "2026-11-06T12:00:00", "reason": "r"}}))
    assert "换代中" in (LR.first_under_regen(RUN, "ep02-S1", tmp_path) or "")
    _takes(tmp_path, "ep02-S1", _done(first_at="2026-11-06T13:00:00", master_gate={"image": {"at": "2026-11-06T12:00:00", "reason": "r"}}))
    assert LR.first_under_regen(RUN, "ep02-S1", tmp_path) is None
    _takes(tmp_path, "ep02-S1", _done(master_gate={"last": {"at": "2026-11-06T12:00:00"}}))           # 只挂尾帧闸门 → 首帧不算
    assert LR.first_under_regen(RUN, "ep02-S1", tmp_path) is None
    # master_rejects：regen 未 cleared → hold；cleared → 不 hold；旧驳回（比当前首帧旧、非 regen）→ 不 hold
    rj = tmp_path / "data/producer/runs" / RUN / "master_rejects.json"
    rj.parent.mkdir(parents=True, exist_ok=True)
    rj.write_text(json.dumps({"first:ep02-S1": {"regen": True, "at": "2026-11-06T09:00:00"}}), encoding="utf-8")
    assert "regen" in (LR.first_under_regen(RUN, "ep02-S1", tmp_path) or "")
    rj.write_text(json.dumps({"first:ep02-S1": {"regen": True, "at": "2026-11-06T09:00:00", "cleared": {"by": "producer"}}}), encoding="utf-8")
    assert LR.first_under_regen(RUN, "ep02-S1", tmp_path) is None
    rj.write_text(json.dumps({"first:ep02-S1": {"at": "2026-11-02T01:00:00", "reason": "old"}}), encoding="utf-8")
    assert LR.first_under_regen(RUN, "ep02-S1", tmp_path) is None
    rj.write_text(json.dumps({"first:ep02-S1": {"at": "2026-11-06T12:00:00", "reason": "new reject"}}), encoding="utf-8")
    assert "未 cleared" in (LR.first_under_regen(RUN, "ep02-S1", tmp_path) or "")
    assert LR.first_under_regen(RUN, "ep02-S9", tmp_path) is None                   # 没有 takes = 不 hold


def test_regen_holds_only_from_episode(tmp_path):
    for sid in ("ep01-S1", "ep02-S1", "ep02-S2"):
        _takes(tmp_path, sid, _done(master_gate={"image": {"at": "2026-11-06T12:00:00", "reason": "r"}}))
    h = LR.regen_holds(RUN, ["ep01-S1", "ep02-S1", "ep02-S2"], CFG, tmp_path)
    assert set(h) == {"ep02-S1", "ep02-S2"} and all(v.startswith("regen：") for v in h.values())
    assert LR.regen_holds(RUN, ["ep02-S1"], {**CFG, "hold_regen_downstream": False}, tmp_path) == {}
    assert LR.regen_holds(RUN, ["ep02-S1"], OFF, tmp_path) == {}


def test_build_jobs_merges_regen_holds(monkeypatch):
    import build_jobs as B
    monkeypatch.setattr(LR, "regen_holds", lambda run, ids, cfg=None, root=None: {"ep02-S1": "regen：x"} if "ep02-S1" in ids else {})
    assert B.regen_holds(["ep02-S1", "ep02-S2"]) == {"ep02-S1": "regen：x"}
    assert B.regen_holds(["ep02-S2"]) == {}


# ---------------------------------------------------------------- ② night
@pytest.fixture
def night_v2(monkeypatch, tmp_path):
    orig = os.environ.get("NS_RUN")
    import night as N
    os.environ["NS_RUN"] = RUN
    N = importlib.reload(N)
    vid = tmp_path / "run" / RUN / "video"
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


def _specs(ep, n=4):
    return {ep: [SimpleNamespace(id=f"ep{ep:02d}-S{i}", episode=ep) for i in range(1, n + 1)]}


def test_night_roles_for_host(night_v2, monkeypatch):
    N = night_v2
    (N.VID / "hosts.json").write_text(json.dumps({"1": "gpu36", "2": "gpu36", "3": "gpu33"}), encoding="utf-8")
    monkeypatch.setattr(LR, "load", lambda path=None: CFG)
    phases = {2: "frames", 3: "videos"}
    monkeypatch.setattr(LR, "phase_of", lambda run, ep, ids, cfg=None, root=None, state_path=None: phases.get(int(ep)))
    monkeypatch.setattr(N, "_VS", lambda: None)
    st = {"eps": {}}
    assert N.roles_for_host("gpu36", _specs(2), st, {}) is None                   # 没有在出的集
    r = N.roles_for_host("gpu36", _specs(2), st, {2: ["ep02-S1"]})
    assert r["phase"] == "frames" and r["eps"] == {"2": "frames"} and r["lanes"] == {"video": ["gpu36:2"], "hold": ["gpu36:0", "gpu36:1"]}
    st = {"eps": {"3": {"status": "rendering"}}}
    r = N.roles_for_host("gpu33", _specs(3), st, {})
    assert r["phase"] == "videos" and r["lanes"]["video"] == ["gpu33:0", "gpu33:1"] and r["lanes"]["hold"] == ["gpu33:3"]
    # 本机混着 ep01（< from_episode）在出 → 整台旧行为（L-206：ep01 不中途改调度）
    st = {"eps": {"1": {"status": "rendering"}, "2": {"status": "rendering"}}}
    assert N.roles_for_host("gpu36", {**_specs(1), **_specs(2)}, st, {}) is None
    st = {"eps": {"1": {"status": "assembled"}, "2": {"status": "rendering"}}}
    assert N.roles_for_host("gpu36", {**_specs(1), **_specs(2)}, st, {})["phase"] == "frames"   # ep01 已成片 = 不算在出
    monkeypatch.setattr(LR, "load", lambda path=None: OFF)
    assert N.roles_for_host("gpu36", _specs(2), st, {}) is None


def test_night_roles_control_and_key(night_v2):
    N = night_v2
    st = {"lane_roles": {"gpu36": {"phase": "frames", "eps": {"2": "frames"}, "lanes": {"video": ["gpu36:2"], "hold": ["gpu36:0", "gpu36:1"]}},
                         "gpu33": None}}
    c = {"hold_lanes": ["gpu36:1"], "shared_lanes": ["gpu36:0", "gpu36:1", "gpu36:2"], "yield_s": 30}
    N.roles_control("gpu36", st, c)
    assert c["hold_lanes"] == ["gpu36:0", "gpu36:1"] and c["video_lanes"] == ["gpu36:2"] and c["shared_lanes"] == ["gpu36:0", "gpu36:1"]
    assert c["lane_roles"] == {"phase": "frames", "eps": {"2": "frames"}, "video": ["gpu36:2"], "rule": "L-206"}
    c2 = {"hold_lanes": [], "shared_lanes": ["gpu33:0"]}
    assert N.roles_control("gpu33", st, dict(c2)) == c2                            # 不适用 = 原样
    # 手工 hold（带到期）优先于分卡：视频道被 hold 就不算视频道
    c3 = {"hold_lanes": ["gpu36:2"], "shared_lanes": []}
    N.roles_control("gpu36", st, c3)
    assert c3["video_lanes"] == [] and "gpu36:2" in c3["hold_lanes"]
    k1 = N.roles_key(st)
    st["lane_roles"]["gpu36"]["phase"] = "videos"
    assert N.roles_key(st) != k1 and N.roles_key({}) == "{}"


def test_night_apply_lane_policy_writes_roles(night_v2, monkeypatch):
    N = night_v2
    (N.VID / "hosts.json").write_text(json.dumps({"2": "gpu36"}), encoding="utf-8")
    monkeypatch.setattr(N, "_hosts_here", lambda: ("gpu36",))
    monkeypatch.setattr(N, "frames_busy", lambda: 0)
    monkeypatch.setattr(N, "_VS", lambda: None)
    sent = []
    monkeypatch.setattr(N, "run", lambda args, timeout=3600: (sent.append(args), (0, ""))[1])
    st = {"eps": {"2": {"status": "rendering", "host": "gpu36"}},
          "lane_roles": {"gpu36": {"phase": "videos", "eps": {"2": "videos"}, "lanes": {"video": ["gpu36:0", "gpu36:1", "gpu36:2"], "hold": []}}}}
    ctrl = dict(N.DEFAULT_CTRL)
    N.apply_lane_policy(st, ctrl)
    c = json.loads([a for a in sent if a[1:3] == ["tools/series10_video/deploy.py", "control"]][-1][4])
    assert c["video_lanes"] == ["gpu36:0", "gpu36:1", "gpu36:2"] and c["lane_roles"]["phase"] == "videos"
    assert not any(x.startswith("gpu36") for x in c["shared_lanes"])            # 视频道不让道
    assert "roles=" in st["lane_key"]
    n0 = len(sent)
    N.apply_lane_policy(st, ctrl)
    assert len(sent) == n0                                                       # 没变不重写
    st["lane_roles"]["gpu36"] = {"phase": "frames", "eps": {"2": "frames"}, "lanes": {"video": ["gpu36:2"], "hold": ["gpu36:0", "gpu36:1"]}}
    N.apply_lane_policy(st, ctrl)
    c = json.loads([a for a in sent if a[1:3] == ["tools/series10_video/deploy.py", "control"]][-1][4])
    assert c["video_lanes"] == ["gpu36:2"] and set(c["hold_lanes"]) >= {"gpu36:0", "gpu36:1"}


# ---------------------------------------------------------------- ③ vidgen
class _Lane:
    def __init__(self, name):
        self.name, self.down, self.last_foreign, self.busy_s = name, False, 0.0, 0.0

    def queue(self):
        return [], 0


def _runner(monkeypatch, lanes, ctrl):
    monkeypatch.setattr(VG, "log", lambda host, *a: None)
    R = object.__new__(VG.Runner)
    R.host, R.lanes, R.lock, R.hold_long, R.lane_mode = "gpu36", {n: _Lane(n) for n in lanes}, threading.Lock(), False, "normal"
    R.st = {"shots": {}, "events": []}
    R.ctrl = lambda: ctrl
    sent = []
    R.dispatch = lambda sh, v, lane: sent.append((sh["shot"], v, lane.name))
    return R, sent


def test_vidgen_only_role_video_lanes_and_dedicated_ignore_yield(monkeypatch):
    shots = {f"ep02-S{i}": {"shot": f"ep02-S{i}", "ep": 2, "variants": {"v1": {"frames": 100}}} for i in range(1, 7)}
    todo = [(sid, "v1") for sid in shots]
    ctrl = {"mode": "prod", "per_lane": 1, "hold_lanes": [], "shared_lanes": ["gpu36:0", "gpu36:1", "gpu36:2"], "yield_s": 999,
            "video_lanes": ["gpu36:2"], "lane_roles": {"phase": "frames", "video": ["gpu36:2"]}}
    R, sent = _runner(monkeypatch, ["gpu36:0", "gpu36:1", "gpu36:2"], ctrl)
    R.pending = lambda shots, validate: list(todo)
    R.submit_round(shots, ctrl)
    assert sent == [("ep02-S1", "v1", "gpu36:2")]                               # 只有视频位派；专用道不等 yield_s
    ctrl2 = {**ctrl, "video_lanes": [], "lane_roles": {"phase": "videos", "video": ["gpu36:0", "gpu36:1", "gpu36:2"]}, "shared_lanes": []}
    R, sent = _runner(monkeypatch, ["gpu36:0", "gpu36:1", "gpu36:2"], ctrl2)
    R.pending = lambda shots, validate: list(todo)
    R.submit_round(shots, ctrl2)
    assert [x[2] for x in sent] == ["gpu36:0", "gpu36:1", "gpu36:2"]
    ctrl3 = {**ctrl, "video_lanes": [], "lane_roles": {"phase": "frames", "video": []}}
    R, sent = _runner(monkeypatch, ["gpu36:0", "gpu36:1", "gpu36:2"], ctrl3)
    R.pending = lambda shots, validate: list(todo)
    R.submit_round(shots, ctrl3)
    assert sent == []                                                            # 本阶段本机没有视频位 = 不派
    ctrl4 = {"mode": "prod", "per_lane": 1, "hold_lanes": [], "shared_lanes": ["gpu36:0"], "yield_s": 999}   # 没写 = 旧行为（让道等 yield）
    R, sent = _runner(monkeypatch, ["gpu36:0"], ctrl4)
    R.lanes["gpu36:0"].last_foreign = __import__("time").time()
    R.pending = lambda shots, validate: list(todo)
    R.submit_round(shots, ctrl4)
    assert sent == []


# ---------------------------------------------------------------- ④ 分片抢活
C2 = {"owner": "gpu36", "hosts": ["gpu33", "gpu36"], "weights": {"gpu36": 3, "gpu33": 2}, "map": {}}


def test_role_claims_frames_then_videos():
    plan = {"ep02-S1": "gpu36", "ep02-S2": "gpu33", "ep02-S3": "gpu33", "ep02-S4": "gpu33"}
    merged = {"ep02-S3": {"status": "rendering", "renders": [{"state": "submitted"}]}}
    cl = VS.role_claims(C2, plan, merged, {}, {"gpu36"}, now=100.0)
    assert set(cl) == {"ep02-S2", "ep02-S4"}                                    # 已开工的 S3 不动
    assert all(c["host"] == "gpu36" and c["from"] == "gpu33" and c["why"] == "lane_roles:frames" and not c.get("sticky") for c in cl.values())
    assert VS.apply_claims(plan, cl)["ep02-S2"] == "gpu36"
    # 视频阶段：没开工的分卡领取还回；gpu36 已开工的保留
    merged2 = {**merged, "ep02-S4": {"status": "rendering", "renders": [{"state": "submitted"}]}}
    cl2 = VS.role_claims(C2, plan, merged2, cl, {"gpu33", "gpu36"}, now=200.0)
    assert set(cl2) == {"ep02-S4"}
    assert VS.role_claims(C2, plan, merged, cl, None, now=200.0) == cl           # 不适用 = 原样
    # 普通抢活的领取（没有 why）在视频阶段不动
    other = {"ep02-S2": {"host": "gpu36", "from": "gpu33", "at": 1.0}}
    assert VS.role_claims(C2, plan, {}, other, {"gpu33", "gpu36"}, now=2.0) == other
    # owner 没有视频道（配置极端情况）→ 领给有视频道的台
    cl3 = VS.role_claims(C2, {"ep02-S1": "gpu36"}, {}, {}, {"gpu33"}, now=1.0)
    assert cl3["ep02-S1"]["host"] == "gpu33"


def test_relay_arbitrate_marks_no_video_host_busy(tmp_path, monkeypatch):
    import shard_relay as SR
    rel = "x/video"
    vid = tmp_path / rel
    vid.mkdir(parents=True)
    shots = [{"shot": f"ep02-S{i}", "ep": 2, "host": "gpu33" if i % 2 else "gpu36", "variants": {"v1": {}}} for i in range(1, 5)]
    (vid / "jobs.json").write_text(json.dumps({"shots": shots}), encoding="utf-8")
    now = 1000.0
    for h in ("gpu33", "gpu36"):
        (vid / f"state_{h}.json").write_text(json.dumps({"host": h, "shots": {}, "saved": now}), encoding="utf-8")
    seen = {}
    monkeypatch.setattr(SR, "role_video_hosts", lambda run, ep, ids: {"gpu36"})
    real = VS.decide_claims

    def spy(c, plan_map, merged, claims, busy, now, **kw):
        seen["busy"] = dict(busy)
        return real(c, plan_map, merged, claims, busy, now, **kw)
    monkeypatch.setattr(VS, "decide_claims", spy)
    cl = SR.arbitrate_claims(RUN, vid, rel, C2, 2, now=now)
    assert seen["busy"]["gpu33"] >= 1                                            # 没视频道的台当它忙（不抢）
    assert {s for s, c in cl.items() if c.get("why") == "lane_roles:frames"} == {"ep02-S1", "ep02-S3"}
    assert all(c["host"] == "gpu36" for c in cl.values())
    assert json.loads((vid / VS.CLAIMS_NAME).read_text(encoding="utf-8")) == cl


def test_relay_role_video_hosts_uses_phase(monkeypatch):
    import shard_relay as SR
    monkeypatch.setattr(LR, "load", lambda path=None: CFG)
    monkeypatch.setattr(LR, "phase_of", lambda run, ep, ids, cfg=None, root=None, state_path=None: "frames" if ep == 2 else None)
    assert SR.role_video_hosts(RUN, 2, ["ep02-S1"]) == {"gpu36"}
    assert SR.role_video_hosts(RUN, 1, ["ep01-S1"]) is None


# ---------------------------------------------------------------- ⑥ 审图位路由
def test_review_env_by_host():
    assert LR.review_env(CFG, "gpu33") == {"VQA_URL": "http://127.0.0.1:8870", "VQA_LAN_URL": ""}
    assert LR.review_env(CFG, "gpu36") == {"VQA_LAN": "1", "VQA_LAN_URL": "http://10.0.0.33:8870", "VQA_REVIEW_ONLY": "1"}
    assert LR.review_env(CFG, "") == {} and LR.review_env(OFF, "gpu36") == {}
    bad = {**CFG, "review": {**CFG["review"], "lan_url": "http://8.8.8.8:8870"}}
    assert LR.review_env(bad, "gpu36") == {}                                     # 非内网地址 = 不改路由（K-REV-V01）
    env = {"OFFLINE_SELF": "gpu36", "VQA_LAN_URL": "http://10.0.0.99:1"}
    assert LR.apply_review_env(env, CFG) == {"VQA_LAN": "1", "VQA_REVIEW_ONLY": "1"} and env["VQA_LAN_URL"] == "http://10.0.0.99:1"


def test_client_lan_override_and_review_only(monkeypatch):
    from ns_agent.vqa import client as VC
    monkeypatch.setattr(VC, "cfg", lambda: {"model": {"host": "gpu36", "port": 8870, "lan_url": "http://10.0.0.36:8870"}, "route": {}})
    monkeypatch.setattr(VC, "_local_up", lambda u: True)
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    monkeypatch.delenv("VQA_LAN_URL", raising=False)
    assert VC._lan_url() is None                                                 # 原口径：本机就是看图主机
    monkeypatch.setenv("VQA_LAN_URL", "http://10.0.0.33:8870")
    assert VC._lan_url() == "http://10.0.0.33:8870"
    monkeypatch.setenv("VQA_LAN_URL", "http://1.2.3.4:8870")
    assert VC._lan_url() is None                                                 # 只认 10. 内网
    monkeypatch.setenv("VQA_LAN_URL", "")
    assert VC._lan_url() is None
    monkeypatch.setenv("VQA_LAN_URL", "http://10.0.0.33:8870")
    monkeypatch.setenv("VQA_REVIEW_ONLY", "1")
    monkeypatch.setattr(VC, "_ready", lambda u: (True, 0))
    assert VC._pick("http://127.0.0.1:8870", 1.0) == ("http://10.0.0.33:8870", "lan", 0, "")
    monkeypatch.setattr(VC, "_local_up", lambda u: False)
    assert VC._pick("http://127.0.0.1:8870", 1.0)[1] == "none"                  # 审图位不通 = 未测，不回本机


def test_score_clip_review_route_wired(monkeypatch):
    import score_clip as SC
    calls = []
    monkeypatch.setattr(LR, "apply_review_env", lambda env=None, cfg=None: calls.append(1) or {"VQA_REVIEW_ONLY": "1"})
    assert SC.review_route() == {"VQA_REVIEW_ONLY": "1"} and calls == [1]
    src = (ROOT / "tools/series10_video/score_clip.py").read_text(encoding="utf-8")
    assert "review_route()" in src.split("def v9_vlm", 1)[1].split("def ", 1)[0]


def test_night_roles_legacy_ep_settled_does_not_veto(night_v2, monkeypatch):
    """W-SCHED 11-06：ep01 首帧永远在 ready 里 → 两台 night 一直 roles None（ep02 的 L-207 从没生效）。
    < from_episode 的集只有本机还有没落定的视频才否决；孤儿记录（被别台领走的 pending）不算；读不到 jobs / state = 否决（旧行为）"""
    N = night_v2
    (N.VID / "hosts.json").write_text(json.dumps({"1": "gpu36", "2": "gpu36"}), encoding="utf-8")
    monkeypatch.setattr(LR, "load", lambda path=None: CFG)
    monkeypatch.setattr(LR, "phase_of", lambda run, ep, ids, cfg=None, root=None, state_path=None: "videos")
    monkeypatch.setattr(LR, "active_from_state", lambda run: None, raising=False)
    monkeypatch.setattr(N, "_VS", lambda: None)
    specs = {**_specs(1), **_specs(2)}
    rs = {1: ["ep01-S1", "ep01-S2"], 2: ["ep02-S1"]}
    st = {"eps": {"1": {"status": "assembled"}, "2": {"status": "rendering"}}}
    assert N.roles_for_host("gpu36", specs, st, rs) is None                       # jobs / state 读不到 → 旧行为（失败关闭）
    var = {"v1": {"status": "ready"}}
    jobs = {"shots": [{"shot": "ep01-S1", "ep": 1, "host": "gpu36", "variants": var},
                      {"shot": "ep01-S2", "ep": 1, "host": "gpu33", "variants": var},
                      {"shot": "ep02-S1", "ep": 2, "host": "gpu36", "variants": var}]}
    (N.VID / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    state = {"shots": {"ep01-S1": {"status": "done", "renders": [{"state": "scored"}]},
                       "ep01-S2": {"status": "pending", "renders": [], "orphan": True},     # 孤儿：别台的镜
                       "ep02-S1": {"status": "pending", "renders": []}}}
    (N.VID / "state_gpu36.json").write_text(json.dumps(state), encoding="utf-8")
    r = N.roles_for_host("gpu36", specs, st, rs)
    assert r and r["phase"] == "videos" and r["eps"] == {"2": "videos"} and r["legacy_settled"] == [1]
    assert r["lanes"]["video"] == ["gpu36:0", "gpu36:1", "gpu36:2"]
    # ep01 本机还有没落定的镜（重开 / 重出）→ 整台旧行为（L-206：ep01 不中途改调度）
    state["shots"]["ep01-S1"] = {"status": "pending", "renders": []}
    (N.VID / "state_gpu36.json").write_text(json.dumps(state), encoding="utf-8")
    assert N.roles_for_host("gpu36", specs, st, rs) is None
    # 本机记录（非孤儿）有在出的版本（领取来的镜，jobs 还写着别台）→ 也否决
    state["shots"]["ep01-S1"] = {"status": "done", "renders": []}
    state["shots"]["ep01-S2"] = {"status": "rendering", "renders": [{"state": "submitted"}]}
    (N.VID / "state_gpu36.json").write_text(json.dumps(state), encoding="utf-8")
    assert N.roles_for_host("gpu36", specs, st, rs) is None
