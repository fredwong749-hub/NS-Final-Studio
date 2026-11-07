"""L-209 S2.5（W-S25）：两台登记表收成一份 registry_merged.json —— 唯一合并函数、笔记本原子写、推两台只读、各读者读它、缺 / 过期退回本机。"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "services" / "api"))
import registry_merged as RM  # noqa: E402

RUN = "rmt_run"


def _w(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _o(st, **kw):
    return {"status": st, **kw}


def _shot(sid, f, l, v="pending"):
    return {"shot": sid, "objects": {"first": f if isinstance(f, dict) else _o(f), "last": l if isinstance(l, dict) else _o(l),
                                     "video": v if isinstance(v, dict) else _o(v)}}


def _reg(eps: dict, hb=None):
    return {"run": RUN, "heartbeat": hb, "episodes": [{"ep": ep, "objects": {}, "have": {}, "shots": shots} for ep, shots in eps.items()]}


def _shots(m, ep):
    E = next(E for E in m["episodes"] if E["ep"] == ep)
    return {S["shot"]: S["objects"] for S in E["shots"]}, E


@pytest.fixture()
def root(tmp_path, monkeypatch):
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    _w(tmp_path / "config/pipeline/state.json", {"registry_merged": {"mode": "record"}})
    RM._logged.clear()
    RM._cache.clear()
    return tmp_path


# ------------------------------------------------------------------ 唯一合并函数
def test_merge_owner_base_settled_only_and_marks():
    g33 = _reg({2: [_shot("ep02-S1", "ready", "pending"), _shot("ep02-S2", "passed", _o("passed", take=2)),
                    _shot("ep02-S3", "passed", "pending"), _shot("ep02-S4", _o("ready", master_reject="脸不对"), "pending"),
                    _shot("ep02-S9", "passed", "passed")]})
    g36 = _reg({2: [_shot("ep02-S1", "pending", "pending"), _shot("ep02-S2", "pending", _o("passed", take=1)),
                    _shot("ep02-S3", _o("ready", redo=True), "pending"), _shot("ep02-S4", "passed", "pending")]})
    before = json.dumps([g33, g36], sort_keys=True)
    m = RM.merge({"gpu33": g33, "gpu36": g36}, {2: "gpu36"})
    S, E = _shots(m, 2)
    assert E["base_host"] == "gpu36" and E["phase_base"] == "gpu36"
    assert S["ep02-S1"]["first"]["status"] == "pending"                       # 别台 ready 残影不改底表
    assert S["ep02-S2"]["first"] == {"status": "passed", "merged_from": "gpu33"}   # 别台定下的补进来
    assert S["ep02-S3"]["first"]["status"] == "ready"                          # 底表 redo：别台旧 passed 不盖
    assert S["ep02-S4"]["first"]["status"] == "passed" and "master_reject" not in S["ep02-S4"]["first"]   # 复审 11-07：底表已定下 → 别台陈旧驳回不盖
    assert "ep02-S9" not in S and m["orphans"]["shots_dropped_n"] == 1         # 孤儿镜丢掉
    assert sorted(c["why"] for c in m["conflicts"]) == ["reject_vs_settled", "take_diff"]
    assert E["have"]["passed"] == {"first": 2, "last": 1, "video": 0} and E["have"]["total"] == 4
    assert json.dumps([g33, g36], sort_keys=True) == before                   # 不改入参


def test_merge_owner_missing_episode_marked_owned_by():
    m = RM.merge({"gpu33": _reg({1: [_shot("ep01-S1", "passed", "passed")], 2: [_shot("ep02-S1", "passed", "pending")]}),
                  "gpu36": _reg({})}, {1: "gpu33", 2: "gpu36"})
    _, E2 = _shots(m, 2)
    assert E2["owned_by"] == "gpu36" and E2["owner_missing"] and E2["base_host"] == "gpu33"
    assert m["orphans"]["eps_owner_missing"] == [2] and any(c["why"] == "owner_missing" for c in m["conflicts"])


def test_reg_merge_and_run_phase_use_the_same_function():
    from tools.brain import reg_merge
    import run_phase as RP
    a = _reg({2: [_shot("ep02-S1", "ready", "pending")]})
    b = _reg({2: [_shot("ep02-S1", "passed", "pending")]})
    assert RP.merge_for_phase({"gpu33": a, "gpu36": b}, {2: "gpu33"})["episodes"] == RM.merge({"gpu33": a, "gpu36": b}, {2: "gpu33"})["episodes"]
    m = reg_merge.merge_registries(a, {"gpu36": b})
    assert m["episodes"][0]["shots"][0]["objects"]["first"] == {"status": "passed", "merged_from": "gpu36"} and m["merged_hosts"] == ["gpu36"]


# ------------------------------------------------------------------ 笔记本写
def test_compute_atomic_refresh_off_and_server_refuses(root, monkeypatch):
    t = time.time()
    regs = {"gpu33": _reg({1: [_shot("ep01-S1", "passed", "passed")]}, t), "gpu36": _reg({2: [_shot("ep02-S1", "passed", "ready")]}, t)}
    d = RM.compute(RUN, root, now=t, regs=regs, owner={1: "gpu33", 2: "gpu36"})
    p = RM.path(RUN, root)
    on = json.loads(p.read_text(encoding="utf-8"))
    assert on["_schema"] == RM.SCHEMA and on["computed_t"] == round(t, 1) and [E["ep"] for E in on["episodes"]] == [1, 2]
    assert d["owner"] == {"1": "gpu33", "2": "gpu36"} and not list(p.parent.glob("*.tmp"))
    mt = p.stat().st_mtime_ns
    RM.compute(RUN, root, now=t + 10, regs=regs, owner={1: "gpu33", 2: "gpu36"})
    assert p.stat().st_mtime_ns == mt                                          # 没变、不到刷新间隔 → 不重写
    RM.compute(RUN, root, now=t + RM.REFRESH_S + 1, regs=regs, owner={1: "gpu33", 2: "gpu36"})
    assert json.loads(p.read_text(encoding="utf-8"))["computed_t"] == round(t + RM.REFRESH_S + 1, 1)
    _w(root / "config/pipeline/state.json", {"registry_merged": "off"})
    assert RM.compute(RUN, root, now=t, regs=regs) is None
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    with pytest.raises(RuntimeError):
        RM.compute(RUN, root, now=t, regs=regs)


def test_compute_reads_pulled_registries(root):
    t = time.time()
    rel = Path("data/producer/runs") / RUN / "registry.json"
    _w(root / "data/_offline_pull/gpu33" / rel, _reg({1: [_shot("ep01-S1", "passed", "pending")]}, t))
    _w(root / "data/_offline_pull/gpu36" / rel, _reg({1: [_shot("ep01-S1", "pending", "passed")]}, t - 7200))   # 心跳过期 = 不用
    d = RM.compute(RUN, root, now=t, owner={1: "gpu33"})
    assert d["merged_hosts"] == ["gpu33"] and d["sources"]["gpu36"]["used"] is False


# ------------------------------------------------------------------ 读者：新鲜 / 退回
def test_fresh_fallback_logged_once_per_10min(root):
    logs = []
    lg = lambda ev, **kw: logs.append((ev, kw))  # noqa: E731
    t = time.time()
    assert RM.fresh(RUN, root, t, lg) is None and RM.fresh(RUN, root, t + 60, lg) is None
    assert [e for e, _ in logs] == ["registry_merged_fallback"]
    RM.compute(RUN, root, now=t, regs={"gpu33": _reg({1: [_shot("ep01-S1", "passed", "pending")]}, t)}, owner={})
    assert RM.fresh(RUN, root, t + 5, lg)["_schema"] == RM.SCHEMA
    assert RM.fresh(RUN, root, t + RM.MAX_AGE_S + 1, lg) is None               # 过期
    reg, src = RM.read(RUN, None, root, t + RM.MAX_AGE_S + 1)
    assert src == "local" and reg == {}


def test_cross_host_record_logs_enforce_returns(root):
    t = time.time()
    RM.compute(RUN, root, now=t, regs={"gpu33": _reg({2: [_shot("ep02-S1", "ready", "pending")]}, t),
                                       "gpu36": _reg({2: [_shot("ep02-S1", "passed", "pending")]}, t)}, owner={2: "gpu36"})
    local = _reg({2: [_shot("ep02-S1", "ready", "pending")]})
    logs = []
    lg = lambda ev, **kw: logs.append((ev, kw))  # noqa: E731
    assert RM.cross_host(RUN, local, "gpu33", root, t, lg) is None             # record：行为不变
    assert logs[0][0] == "registry_merged_disagree" and logs[0][1]["sample"][0]["obj"] == "first:ep02-S1"
    _w(root / "config/pipeline/state.json", {"registry_merged": {"mode": "enforce"}})
    assert RM.cross_host(RUN, local, "gpu33", root, t, lg)["_schema"] == RM.SCHEMA
    _w(root / "config/pipeline/state.json", {"registry_merged": "off"})
    assert RM.cross_host(RUN, local, "gpu33", root, t, lg) is None


def test_shot_status_reads_merged_file_then_falls_back(tmp_path, monkeypatch):
    from ns_api import shot_status as SS
    monkeypatch.setattr(SS, "ROOT", tmp_path)
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    rel = Path("data/producer/runs") / RUN / "registry.json"
    _w(tmp_path / rel, _reg({1: [_shot("ep01-S1", "ready", "pending")]}))
    t = time.time()
    RM_ = SS._rm()
    RM_.compute(RUN, tmp_path, now=t, regs={"gpu33": _reg({1: [_shot("ep01-S1", "passed", "pending")]}, t)}, owner={1: "gpu33"})
    m = SS.merged_registry(tmp_path / rel)
    assert m["_schema"] == RM.SCHEMA and m["episodes"][0]["shots"][0]["objects"]["first"]["status"] == "passed"
    monkeypatch.setattr(SS, "registry_path", lambda: tmp_path / rel)
    monkeypatch.setitem(SS._reg, "mt", None)
    assert SS._registry()["ep01-S1"]["first"]["status"] == "passed"
    _w(RM_.path(RUN, tmp_path), {**m, "computed_t": t - 3 * 3600})            # 过期 → 本机
    RM_._cache.clear()
    assert SS.merged_registry(tmp_path / rel)["episodes"][0]["shots"][0]["objects"]["first"]["status"] == "ready"


# ------------------------------------------------------------------ 大脑 / 自查 / 影子 / 记分卡
def _doc(t):
    return RM.merge({"gpu33": _reg({2: [_shot("ep02-S1", "passed", _o("passed", take=2))]}, t),
                     "gpu36": _reg({2: [_shot("ep02-S1", "passed", _o("passed", take=1)), _shot("ep02-S2", "passed", "pending")]}, t)},
                    {2: "gpu36"}) | {"computed_t": t, "computed_at": "x"}


def test_brain_kpi_and_selfcheck_use_merged():
    sys.path.insert(0, str(ROOT / "tools" / "brain"))
    import telemetry as T
    import invariants as INV
    t = time.time()
    mv = T.merged_view(_doc(t), t)
    assert mv["have"]["2"] == {"t": 2, "f": 2, "l": 1, "v": 0, "asm": False} and mv["conflicts_n"] == 1
    probes = {"gpu33": {"log": {"first_dispatch": {"2": t - 600}}, "registry": {"episodes": {"2": {"have": {"t": 16, "f": 0, "l": 0, "v": 0}}}}},
              "gpu36": {"log": {}, "registry": {"episodes": {"2": {"have": {"t": 16, "f": 14, "l": 9, "v": 0}}}}}}
    k = T.kpi(t, probes, merged=mv["have"])["2"]
    assert (k["first_done"], k["last_done"], k["total"]) == (2, 1, 2)
    host = lambda f, l: {"registry": {"episodes": {"2": {"have": {"t": 16, "f": f, "l": l, "v": 0}}}}}  # noqa: E731
    snap = {"kpi": {"2": {"first_done": 2, "last_done": 1}}, "hosts": {"gpu33": host(0, 0), "gpu36": host(14, 9)},
            "registry_merged": mv, "lanes": {}, "idle_watch": {}, "assets": {}}
    ks = {v["key"] for v in INV.check_snapshot(snap, t)}
    assert "host_disagree:ep2:l" in ks and "host_disagree:ep2:f" not in ks and "kpi_brain:ep2" not in ks   # 只报真冲突
    snap["registry_merged"] = {**mv, "conflicts": [], "conflicts_n": 0}
    assert not {k for k in (v["key"] for v in INV.check_snapshot(snap, t)) if k.startswith(("host_disagree", "kpi_brain"))}


def test_shadow_uses_merged_registry():
    sys.path.insert(0, str(ROOT / "tools" / "sched"))
    import shadow as SH
    t = time.time()
    probes = {"gpu33": {"reg": {"2": {"shots": {"ep02-S1": {"first": ["ready", 0, 3, 0, 0, "", ""]}}}}, "ctrl": {"only": ["ep02-S1"]}},
              "gpu36": {"reg": {}, "ctrl": {}}}
    eps, div = SH.merge_registry(probes, _doc(t))
    assert eps[2]["shots"]["ep02-S1"]["first"]["st"] == "passed" and eps[2]["shots"]["ep02-S1"]["first"]["src"] == "merged"
    assert [d["why"] for d in div] == ["take_diff"]


def test_scorecard_counts_from_merged(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools" / "qa"))
    import scorecard as SC
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    t = time.time()
    _w(tmp_path / "data/brain/snapshot.json", {"kpi": {"2": {"total": 16, "first_done": 0, "last_done": 0, "video_done": 0, "start_t": t - 600}}})
    d = SC.compute(tmp_path, RUN, t, adult_listing={}, open_items=[])
    assert d["episodes"][0]["counts_src"] == "snapshot"
    RM.compute(RUN, tmp_path, now=t, regs={"gpu36": _doc(t)}, owner={2: "gpu36"})
    d = SC.compute(tmp_path, RUN, t, adult_listing={}, open_items=[])
    e = d["episodes"][0]
    assert e["counts_src"] == "registry_merged" and (e["first_done"], e["last_done"], e["total"]) == (2, 1, 2)


def test_resident_sync_pushes_and_never_pulls_merged(tmp_path, monkeypatch):
    import resident_sync as RS
    assert "registry_merged.json" in RS.SKIP_NAMES
    monkeypatch.setattr(RS, "ROOT", tmp_path)
    monkeypatch.setattr(RS, "run_sync_runs", lambda: [RUN])
    fs = RS.control_files()
    assert any(f.endswith(f"/{RUN}/registry_merged.json") and f.startswith("data/producer/runs/") for f in fs)
    assert 'rel.endswith("/registry_merged.json")' in RS.REMOTE_MERGE                 # 服务器整文件覆盖


def test_stale_reject_on_other_host_does_not_override_settled_base():
    """复审 11-07 BLOCKER：主台已定下（passed），别台还挂着陈旧的驳回 ready → 底表保留、记 reject_vs_settled 冲突"""
    import registry_merged as RMG
    base = {"episodes": [{"ep": 2, "shots": [{"shot": "ep02-S1", "objects": {"first": {"status": "passed", "take": 5}}}]}]}
    other = {"episodes": [{"ep": 2, "shots": [{"shot": "ep02-S1", "objects": {"first": {"status": "ready", "redo": True, "master_reject": "x", "take": 4}}}]}]}
    out = RMG.merge({"gpu36": base, "gpu33": other}, {2: "gpu36"})
    o = out["episodes"][0]["shots"][0]["objects"]["first"]
    assert o["status"] == "passed" and any(c.get("why") == "reject_vs_settled" for c in out.get("conflicts") or [])


def test_older_take_does_not_fill_rerendering_base():
    """复审 11-07：主台在出 take 6，别台旧 passed take 5 不填"""
    import registry_merged as RMG
    base = {"episodes": [{"ep": 2, "shots": [{"shot": "ep02-S1", "objects": {"first": {"status": "running", "take": 6}}}]}]}
    other = {"episodes": [{"ep": 2, "shots": [{"shot": "ep02-S1", "objects": {"first": {"status": "passed", "take": 5}}}]}]}
    out = RMG.merge({"gpu36": base, "gpu33": other}, {2: "gpu36"})
    assert out["episodes"][0]["shots"][0]["objects"]["first"]["status"] == "running"
