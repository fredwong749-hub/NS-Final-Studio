"""视频按镜分片（PLAN_EP01_FINISH §11，默认关）：分片表确定性 / 两台互不相交 / 关 = 原行为 / 合并只读 / night 接线 / relay 清单。
全部写入在 tmp_path；不连服务器。"""
from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/post", "services/agent", "tools", "tools/series10_video", ""):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import video_shard as VS  # noqa: E402

RUN = "series10_v2"
ON = {"enabled": True, "runs": {RUN: {"eps": {"1": {"owner": "gpu36", "weights": {"gpu36": 1, "gpu33": 2}, "map": {}}}}},
      "exclude_lanes": {"gpu33": ["gpu33:3"]}}
OFF = {**ON, "enabled": False}


def _specs(n=16, ep=1, dur=4.0):
    return {f"ep{ep:02d}-S{i}": SimpleNamespace(episode=ep, duration_s=dur) for i in range(1, n + 1)}


def test_shipped_config_ep01_shard_on():
    # cut L（11-05）开分片；L-194：权重按道数 gpu36 三道（0/1/2）: gpu33 两道（0/1）；gpu33:3 仍排除
    c = VS.load()
    assert c.get("enabled") is True
    e = VS.ep_cfg(RUN, 1, c)
    assert e and e["owner"] == "gpu36" and e["weights"] == {"gpu36": 3.0, "gpu33": 2.0}
    assert VS.exclude_lanes("gpu33", c) == ["gpu33:3"]
    assert VS.ep_cfg(RUN, 2, c) is None


def test_off_means_no_plan_no_extra_eps_no_exclude():
    assert VS.plan_all(RUN, _specs(), OFF) == {}
    assert VS.eps_on_host(RUN, "gpu33", {"1": "gpu36", "3": "gpu33"}, OFF) == [3]
    assert VS.exclude_lanes("gpu33", OFF) == []
    assert VS.helper_hosts(RUN, OFF) == set()


def test_bad_config_fails_closed():
    assert VS.load(Path("/nonexistent/x.json")) == {"enabled": False}
    bad = {"enabled": True, "runs": {RUN: {"eps": {"1": {"owner": "gpu99", "weights": {"gpu36": 1, "gpu33": 2}}}}}}
    assert VS.ep_cfg(RUN, 1, bad) is None                     # owner 不在分片台里 = 没人合成 = 不分片
    one = {"enabled": True, "runs": {RUN: {"eps": {"1": {"owner": "gpu36", "weights": {"gpu36": 1}}}}}}
    assert VS.ep_cfg(RUN, 1, one) is None                     # 一台不叫分片
    assert VS.ep_cfg(RUN, 2, ON) is None                      # 没配的集不动


def test_plan_deterministic_disjoint_weighted():
    sp = _specs(16)
    a = VS.plan_all(RUN, sp, ON)
    b = VS.plan_all(RUN, dict(reversed(list(sp.items()))), ON)   # 输入顺序不影响（两台各自算也一致）
    assert a == b and set(a) == set(sp)
    n36 = sum(1 for h in a.values() if h == "gpu36")
    n33 = sum(1 for h in a.values() if h == "gpu33")
    assert (n36, n33) == (5, 11)                                 # 权重 1:2
    mine = {h: {s for s, x in a.items() if x == h} for h in ("gpu33", "gpu36")}
    assert not (mine["gpu33"] & mine["gpu36"]) and mine["gpu33"] | mine["gpu36"] == set(sp)


def test_plan_balances_by_duration_and_honours_map():
    sp = {f"ep01-S{i}": SimpleNamespace(episode=1, duration_s=d) for i, d in enumerate([6, 6, 6, 2, 2, 2, 2, 2], 1)}
    c = VS.ep_cfg(RUN, 1, ON)
    pl = VS.plan(c, [(k, v.duration_s) for k, v in sp.items()])
    load = {h: sum(sp[s].duration_s for s, x in pl.items() if x == h) for h in ("gpu33", "gpu36")}
    assert abs(load["gpu33"] / 2 - load["gpu36"]) <= 4          # 按权重归一后大致均衡
    cfg = json.loads(json.dumps(ON))
    cfg["runs"][RUN]["eps"]["1"]["map"] = {"ep01-S1": "gpu36", "ep01-S2": "gpu36", "ep01-S3": "gpu36"}
    pl2 = VS.plan_all(RUN, sp, cfg)
    assert [pl2[f"ep01-S{i}"] for i in (1, 2, 3)] == ["gpu36"] * 3


def test_eps_on_host_and_exclude_lanes():
    hosts_map = {"1": "gpu36", "3": "gpu33"}
    assert VS.eps_on_host(RUN, "gpu36", hosts_map, ON) == [1]
    assert VS.eps_on_host(RUN, "gpu33", hosts_map, ON) == [1, 3]   # helper 台多出分片集
    assert VS.helper_hosts(RUN, ON) == {"gpu33"}
    assert VS.exclude_lanes("gpu33", ON) == ["gpu33:3"] and VS.exclude_lanes("gpu36", ON) == []


def _state(vid: Path, host: str, shots: dict):
    (vid / f"state_{host}.json").write_text(json.dumps({"host": host, "shots": shots}), encoding="utf-8")


def test_merged_shots_read_only_and_prefers_planned_host(tmp_path):
    vid = tmp_path
    _state(vid, "gpu36", {"ep01-S1": {"status": "done", "renders": [{"variant": "a"}]}, "ep02-S1": {"status": "done", "renders": []}})
    _state(vid, "gpu33", {"ep01-S2": {"status": "pending", "renders": []},
                          "ep01-S1": {"status": "best_effort", "renders": [{"variant": "x"}, {"variant": "y"}]}})
    before = {h: (vid / f"state_{h}.json").read_text(encoding="utf-8") for h in ("gpu33", "gpu36")}
    jobs = {"shots": [{"shot": "ep01-S1", "host": "gpu36"}, {"shot": "ep01-S2", "host": "gpu33"}]}
    m = VS.merged_shots(vid, 1, ["gpu36", "gpu33"], jobs)
    assert set(m) == {"ep01-S1", "ep01-S2"}                       # 只含本集
    assert m["ep01-S1"]["status"] == "done"                      # 重复镜取 jobs 里计划的那台
    assert before == {h: (vid / f"state_{h}.json").read_text(encoding="utf-8") for h in ("gpu33", "gpu36")}
    assert VS.merged_shots(vid, 1, ["gpu36", "gpu99"], jobs).keys() == {"ep01-S1"}   # 缺的台 = 暂时没有（等 relay）


# ---------------------------------------------------------------- night 接线
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


def _jobs(vid: Path, n=4):
    shots = [{"shot": f"ep01-S{i}", "ep": 1, "host": "gpu36" if i % 2 else "gpu33"} for i in range(1, n + 1)]
    (vid / "jobs.json").write_text(json.dumps({"shots": shots}), encoding="utf-8")


def test_night_off_is_original_behaviour(night_v2, monkeypatch):
    N = night_v2
    monkeypatch.setattr(VS, "CONFIG", Path("/nonexistent"))     # 关
    _jobs(N.VID)
    _state(N.VID, "gpu36", {f"ep01-S{i}": {"status": "done", "chosen": "v", "renders": [{}]} for i in (1, 3)})
    _state(N.VID, "gpu33", {f"ep01-S{i}": {"status": "done", "chosen": "v", "renders": [{}]} for i in (2, 4)})
    fin, recs = N.ep_resolved(1, "gpu36")
    assert fin is False and recs["ep01-S2"] == {}               # 关：只看 owner 本机 state（gpu33 的不算）
    assert N._eps_on({"1": "gpu36", "3": "gpu33"}, "gpu33") == [3]
    assert N._shard_hold("gpu33", ["gpu33:0"]) == ["gpu33:0"]


def test_night_on_merges_helper_state_and_waits_for_relay(night_v2, monkeypatch, tmp_path):
    N = night_v2
    cfgp = tmp_path / "vs.json"
    cfgp.write_text(json.dumps(ON), encoding="utf-8")
    monkeypatch.setattr(VS, "CONFIG", cfgp)
    _jobs(N.VID)

    def done():
        return {"status": "done", "chosen": "v", "renders": [{}]}
    _state(N.VID, "gpu36", {"ep01-S1": done(), "ep01-S3": done()})
    fin, _ = N.ep_resolved(1, "gpu36")
    assert fin is False                                         # helper 的 state 还没送来 = 等，不会拿缺镜去合成
    sig0 = N.ep_sig(1, "gpu36")
    _state(N.VID, "gpu33", {"ep01-S2": done(), "ep01-S4": done()})   # relay 送到
    fin, recs = N.ep_resolved(1, "gpu36")
    assert fin is True and all(r["status"] == "done" for r in recs.values())
    assert N.ep_sig(1, "gpu36") != sig0                          # 合并后签名变 -> reopen / 重合成逻辑能感知
    assert N._eps_on({"1": "gpu36", "3": "gpu33"}, "gpu33") == [1, 3]
    assert N._shard_hold("gpu33", ["gpu33:0"]) == ["gpu33:0", "gpu33:3"]   # 分片台才挂 gpu33:3
    assert N._shard_hold("gpu36", ["gpu36:1"]) == ["gpu36:1"]


# ---------------------------------------------------------------- build_jobs / relay
def test_build_jobs_shard_hosts_helper(monkeypatch, tmp_path):
    import build_jobs as B
    cfgp = tmp_path / "vs.json"
    cfgp.write_text(json.dumps(ON), encoding="utf-8")
    monkeypatch.setattr(VS, "CONFIG", cfgp)
    monkeypatch.setattr(B, "RUN_ID", RUN)
    out = B._shard_hosts(_specs(16))
    assert set(out.values()) == {"gpu33", "gpu36"} and len(out) == 16
    cfgp.write_text(json.dumps(OFF), encoding="utf-8")
    assert B._shard_hosts(_specs(16)) == {}


def test_relay_payload_only_chosen_and_local(tmp_path):
    import shard_relay as SR
    rel = "data/pipeline/runs/series10_v2/video"
    vid = tmp_path / rel
    (vid / "clips").mkdir(parents=True)
    (vid / "scores").mkdir()
    (vid / "clips" / "a.mp4").write_bytes(b"1")
    (vid / "scores" / "ep01-S2__v1.json").write_text("{}", encoding="utf-8")
    st = {"shots": {"ep01-S2": {"chosen": "v1", "renders": [{"variant": "v1", "file": f"{rel}/clips/a.mp4"},
                                                            {"variant": "v0", "file": f"{rel}/clips/old.mp4"}]},
                    "ep02-S1": {"chosen": "v1", "renders": [{"variant": "v1", "file": f"{rel}/clips/b.mp4"}]}}}
    (vid / "state_gpu33.json").write_text(json.dumps(st), encoding="utf-8")
    got = SR.helper_payload(vid, rel, "gpu33", 1, root=tmp_path)
    assert got == [f"{rel}/state_gpu33.json", f"{rel}/clips/a.mp4", f"{rel}/scores/ep01-S2__v1.json"]
    full = SR.helper_payload(vid, rel, "gpu33", 1, root=tmp_path, only_local=False)
    assert f"{rel}/clips/old.mp4" not in full and f"{rel}/clips/b.mp4" not in full
    assert SR.helper_payload(vid, rel, "gpu36", 1, root=tmp_path) == []     # 没有 state = 没东西
