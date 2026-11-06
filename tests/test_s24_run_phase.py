"""L-209 S2.4（W-S234）：run 级阶段只在笔记本算一次（两台登记表合并）→ run_phase.json → 服务器读（record 只比对 / enforce 用中心）。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import run_phase as RP  # noqa: E402

RUN = "rpt_run"


def _w(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _shot(sid, f, l, v="pending"):
    return {"shot": sid, "objects": {"first": {"status": f}, "last": {"status": l}, "video": {"status": v}}}


def _reg(eps, hb, active_ep=None):
    return {"run": RUN, "heartbeat": hb, "episodes": [{"ep": ep, "shots": shots, "objects": {}} for ep, shots in eps.items()],
            "lane_roles": {"active": {"ep": active_ep, "phase": "frames"} if active_ep else None}}


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    _w(tmp_path / "config/pipeline/lane_roles.json", {"enabled": True, "from_episode": 1, "phases": {}})
    _w(tmp_path / "config/pipeline/state.json", {"run_phase": {"mode": "record"}})
    _w(tmp_path / "data/state/netfix/partition.json", {"images": {"gpu33": [1, 3], "gpu36": [2, 4]}})
    RP._logged.clear()
    return tmp_path


def _pull(root, host, reg):
    _w(root / "data/_offline_pull" / host / "data/producer/runs" / RUN / "registry.json", reg)


def test_merge_uses_owner_base_and_only_settled_from_others():
    # gpu33 的 ep02 是“ready”残影；gpu36（归属台）真实：S1 定下、S2 pending（等上游）
    g33 = _reg({2: [_shot("ep02-S1", "ready", "pending"), _shot("ep02-S2", "ready", "pending")]}, 0)
    g36 = _reg({2: [_shot("ep02-S1", "passed", "passed"), _shot("ep02-S2", "pending", "pending")]}, 0)
    m = RP.merge_for_phase({"gpu33": g33, "gpu36": g36}, {2: "gpu36"})
    S = {s["shot"]: s["objects"] for s in m["episodes"][0]["shots"]}
    assert S["ep02-S2"]["first"]["status"] == "pending"           # 不拿别台的 ready 改阶段
    assert m["episodes"][0]["phase_base"] == "gpu36"
    # 别台已定下的结果（中继 / 借道）补进来
    g36b = _reg({2: [_shot("ep02-S1", "passed", "ready"), _shot("ep02-S2", "pending", "pending")]}, 0)
    g33b = _reg({2: [_shot("ep02-S1", "passed", "passed"), _shot("ep02-S2", "ready", "pending")]}, 0)
    m2 = RP.merge_for_phase({"gpu33": g33b, "gpu36": g36b}, {2: "gpu36"})
    assert m2["episodes"][0]["shots"][0]["objects"]["last"]["merged_from"] == "gpu33"


def test_compute_writes_atomic_and_resolves_split(root):
    t = time.time()
    # 两台对 ep02 看法不同的复现：gpu33 残影 ready → frames；gpu36 真实没活可派 → C2 videos
    _pull(root, "gpu33", _reg({1: [_shot("ep01-S1", "passed", "passed")], 2: [_shot("ep02-S1", "ready", "pending"), _shot("ep02-S2", "ready", "pending")]}, t, 2))
    _pull(root, "gpu36", _reg({1: [_shot("ep01-S1", "ready", "pending")], 2: [_shot("ep02-S1", "passed", "passed"), _shot("ep02-S2", "pending", "pending")]}, t, 2))
    d = RP.compute(RUN, root, now=t)
    assert d["phases"] == {"1": "videos", "2": "videos"}
    assert d["active"]["ep"] == 2                                  # 第一次算沿用两台一致的粘性 active
    on_disk = json.loads(RP.path(RUN, root).read_text(encoding="utf-8"))
    assert on_disk["active"]["ep"] == 2 and on_disk["_schema"] == RP.SCHEMA
    assert not list(RP.path(RUN, root).parent.glob("*.tmp"))
    # 内容不变、不到刷新间隔 → 不重写
    mt = RP.path(RUN, root).stat().st_mtime_ns
    RP.compute(RUN, root, now=t + 10)
    assert RP.path(RUN, root).stat().st_mtime_ns == mt
    RP.compute(RUN, root, now=t + RP.REFRESH_S + 1)
    assert json.loads(RP.path(RUN, root).read_text(encoding="utf-8"))["computed_t"] > on_disk["computed_t"]


def test_compute_skips_stale_registries_and_refuses_on_server(root, monkeypatch):
    t = time.time()
    _pull(root, "gpu33", _reg({1: [_shot("ep01-S1", "ready", "pending")]}, t - 10 * 3600))
    assert RP.compute(RUN, root, now=t) is None
    assert not RP.path(RUN, root).exists()
    monkeypatch.setenv("OFFLINE_SELF", "gpu36")
    with pytest.raises(RuntimeError):
        RP.compute(RUN, root, now=t)


def test_off_mode_no_write(root):
    _w(root / "config/pipeline/state.json", {"run_phase": "off"})
    t = time.time()
    _pull(root, "gpu33", _reg({1: [_shot("ep01-S1", "ready", "pending")]}, t))
    assert RP.compute(RUN, root, now=t) is None
    assert RP.apply(RUN, {1: "frames"}, {1: "frames"}, None, root)[3] == "local"


def _central(root, t, active_ep=2, phase="videos", phases=None):
    doc = {"_schema": RP.SCHEMA, "run": RUN, "computed_t": t, "computed_at": RP._iso(t),
           "active": {"ep": active_ep, "phase": phase, "stages": {}}, "phases": phases or {"2": phase}, "stages": phases or {"2": phase}}
    _w(RP.path(RUN, root), doc)


def test_apply_record_logs_disagreement_without_changing(root):
    t = time.time()
    _central(root, t)
    logs = []
    lg = lambda ev, **k: logs.append((ev, k))  # noqa: E731
    local = ({2: "frames"}, {2: "frames"}, {"ep": 2, "phase": "frames", "stages": {}})
    ph, st, act, src = RP.apply(RUN, *local, root=root, log=lg, actor="gpu33", now=t)
    assert src == "local" and ph == {2: "frames"} and act["phase"] == "frames"
    assert logs and logs[0][0] == "run_phase_disagree" and logs[0][1]["diff"]["phases"]["2"] == {"local": "frames", "central": "videos"}
    RP.apply(RUN, *local, root=root, log=lg, actor="gpu33", now=t + 5)
    assert len(logs) == 1                                          # 同一种不一致 10 分钟一条
    logs.clear()
    RP.apply(RUN, {2: "videos"}, {2: "videos"}, {"ep": 2, "phase": "videos"}, root=root, log=lg, actor="gpu33", now=t)
    assert logs == []                                              # 一致不记


def test_apply_enforce_uses_central_and_falls_back_when_stale(root):
    _w(root / "config/pipeline/state.json", {"run_phase": {"mode": "enforce", "max_age_s": 600}})
    t = time.time()
    _central(root, t)
    logs = []
    lg = lambda ev, **k: logs.append(ev)  # noqa: E731
    ph, st, act, src = RP.apply(RUN, {2: "frames"}, {2: "frames"}, None, root=root, log=lg, actor="gpu36", now=t)
    assert src == "central" and ph == {2: "videos"} and act == {"ep": 2, "phase": "videos", "stages": {}}
    assert RP.enforced(RUN, root, now=t)["active"]["ep"] == 2
    # 过期 → 本机自算，记一次 fallback（10 分钟内不重复）
    ph, st, act, src = RP.apply(RUN, {2: "frames"}, {2: "frames"}, None, root=root, log=lg, actor="gpu36", now=t + 601)
    RP.apply(RUN, {2: "frames"}, {2: "frames"}, None, root=root, log=lg, actor="gpu36", now=t + 700)
    assert src == "local" and ph == {2: "frames"} and logs.count("run_phase_fallback") == 1
    RP.path(RUN, root).unlink()
    assert RP.enforced(RUN, root, now=t) is None


def test_lane_roles_readers_follow_central_in_enforce(root, monkeypatch):
    """lane_roles_producer.read_active / series10_video.lane_roles.active_from_state：enforce + 新鲜 → 中心；record → 本机状态文件"""
    import lane_roles_producer as LRO  # noqa: PLC0415
    sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
    import lane_roles as LR  # noqa: PLC0415
    t = time.time()
    _central(root, t, 3, "frames", {"3": "frames"})
    _w(root / LRO.STATE_REL, {RUN: {"_active": {"ep": 2, "phase": "videos"}, "2": {"phase": "videos"}}})
    assert LRO.read_active(RUN, root)["ep"] == 2                  # record：本机
    _w(root / "config/pipeline/state.json", {"run_phase": "enforce"})
    assert LRO.read_active(RUN, root)["ep"] == 3
    assert LRO.read_phase(RUN, 3, root) == "frames"
    monkeypatch.setattr(LR, "ROOT", root)
    monkeypatch.setattr(LR, "STATE", root / LRO.STATE_REL)
    assert LR.active_from_state(RUN)["ep"] == 3
    assert LR.phase_from_state(RUN, 3) == "frames"
    assert LR.active_from_state(RUN, root / LRO.STATE_REL)["ep"] == 2   # 显式给路径 = 只读那份文件（旧接口）


def test_control_files_and_overwrite_include_run_phase():
    src = (ROOT / "tools/autopilot/resident_sync.py").read_text(encoding="utf-8")
    assert "run_phase.json" in src and 'rel.endswith("/run_phase.json")' in src
