"""FIX-ORCH 11-06（L-202 / L-205 编排瓶颈）：提示词证据自探（O1）、按镜派单（O2）、跨机借道自动开关（O3）、帧中继提速（O4）、
自愈分项 apply（O5）、资产作业道释放（O6）、复盘并行（O8）。夹具全在临时根目录，不碰真实数据 / 网络 / 进程。"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


SG = _load("tools/master/sop_gate.py", "sop_gate_fix_orch")
RUN = "drama_x"


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _root(tmp_path, shots=(1, 2), eps=(1,), cfg=None):
    r = tmp_path
    _w(r / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "old_v1", "runs": {RUN: {"status": "producing"}}})
    _w(r / "config/pipeline/sop_gate.json", cfg or {"enabled": True, "observe_stages": []})
    _w(r / "data/import/runs" / RUN / "script_v2.json",
       {"globals": {"style": "s"}, "episodes": [{"number": e, "cast": ["a"], "shots": [{"index": n, "text": f"t{n}"} for n in shots]} for e in eps]})
    for e in eps:
        _w(r / f"data/pipeline/runs/{RUN}/P4_ep{e:02d}.md", "# P4\n")
        _w(r / f"data/pipeline/runs/{RUN}/autoflow_ep{e:02d}.json",
           {"stages": [{"id": "gate", "status": "ok"}, {"id": "import", "status": "imported", "sha256": "abc"}]})
        _w(r / f"data/pipeline/asset_jobs/{RUN}/_ready_ep{e:02d}.json", {"ready": True, "gaps": 0, "at": "t"})
    return r


def _probe(r, ep=1, rows=None):
    rows = rows or {"1": {"ok": True, "manifest_keys": []}, "2": {"ok": True, "manifest_keys": []}}
    return SG.probe_prompts(RUN, ep, root=r, runner=lambda run, e, root, cfg: json.loads(json.dumps(rows)))


def _import_sha(r, sha, ep=1):
    p = r / f"data/pipeline/runs/{RUN}/autoflow_ep{ep:02d}.json"
    d = json.loads(p.read_text(encoding="utf-8"))
    d["stages"][1]["sha256"] = sha
    p.write_text(json.dumps(d), encoding="utf-8")


def _lock(r, pid, t=None, ep=1):
    _w(SG._probe_lock(r, RUN, ep), {"pid": pid, "t": time.time() if t is None else t, "nonce": "x"})


# ---------------------------------------------------------------- O1(a)(b) 触发
def test_o1_stale_markers_include_missing_and_timeout_but_not_import_block():
    assert SG._is_stale_evidence(["提示词：还没有逐镜编译 + preflight 证据（跑 sop_gate.py probe-prompts）"])
    assert SG._is_stale_evidence(["提示词：0/2 镜过；镜1：探针超时（900 s），自动退避重试"])
    assert SG._is_stale_evidence(["提示词：证据过期（t 之后…）"])
    assert not SG._is_stale_evidence(["导入闸门：gate=reopened", "提示词：还没有逐镜编译 + preflight 证据"])
    assert not SG._is_stale_evidence(["资产就绪：缺口"])


def test_o1_new_episode_self_probes(tmp_path, monkeypatch):
    """新集还没有证据 → 自动后台 probe（不再只认“证据过期”）"""
    r = _root(tmp_path)
    miss = SG.judge(RUN, 1, "出图", 1, r)["missing"]
    assert SG._is_stale_evidence(miss)
    monkeypatch.setattr(SG, "ROOT", r)
    started = []
    import subprocess

    class P:
        pid = 424242
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (started.append(a[0]), P())[1])
    assert SG.auto_probe_stale(RUN, 1, r, miss) == "started" and "probe-prompts" in started[0]
    assert json.loads(SG._probe_lock(r, RUN, 1).read_text(encoding="utf-8"))["pid"] == 424242


# ---------------------------------------------------------------- O1(c) 锁按 pid
def test_o1_lock_alive_pid_means_running_no_piling(tmp_path, monkeypatch):
    r = _root(tmp_path)
    monkeypatch.setattr(SG, "ROOT", r)
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: pytest.fail("不该再起探针"))
    _lock(r, os.getpid(), t=time.time() - 600)           # 10 分钟前起、进程还活着、没超过 probe_timeout_s + 120 → 在跑
    assert SG.auto_probe_stale(RUN, 1, r, ["提示词：证据过期"]) == "running"


def test_o1_dead_pid_after_written_evidence_retries_after_30s(tmp_path, monkeypatch):
    r = _root(tmp_path)
    monkeypatch.setattr(SG, "ROOT", r)
    import subprocess

    class P:
        pid = 1
    calls = []
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: (calls.append(1), P())[1])
    monkeypatch.setattr(SG, "_pid_alive", lambda pid: False)
    t0 = time.time() - 100
    _lock(r, 999999, t=t0)
    _probe(r)                                           # 探针写完证据（mtime > 锁时间）
    _import_sha(r, "new")
    assert SG.probe_wait_s(RUN, 1, r) == SG.AUTO_PROBE_MIN_GAP_S
    assert SG.auto_probe_stale(RUN, 1, r, ["提示词：证据过期"], now=t0 + 10) == "cooldown"
    assert SG.auto_probe_stale(RUN, 1, r, ["提示词：证据过期"], now=t0 + 40) == "started" and calls


def test_o1_dead_pid_without_evidence_waits_cooldown(tmp_path, monkeypatch):
    r = _root(tmp_path)
    monkeypatch.setattr(SG, "_pid_alive", lambda pid: False)
    _lock(r, 999999, t=time.time() + 60)                 # 锁比证据新 = 上次没写成
    assert SG.probe_wait_s(RUN, 1, r) == SG.AUTO_PROBE_COOLDOWN_S


# ---------------------------------------------------------------- O1(b) 超时写证据 + 退避
def test_o1_probe_timeout_writes_evidence_and_backs_off(tmp_path):
    r = _root(tmp_path)
    _probe(r)                                            # 上次两镜都过
    _w(r / "data/import/runs" / RUN / "script_v2.json",  # 镜 2 改了，镜 1 没变
       {"globals": {"style": "s"}, "episodes": [{"number": 1, "cast": ["a"], "shots": [{"index": 1, "text": "t1"}, {"index": 2, "text": "changed"}]}]})

    def boom(*a):
        raise SG.ProbeTimeout("探针超时（900 s）")
    ev = SG.probe_prompts(RUN, 1, root=r, runner=boom)
    assert ev["probe_timeout"] and ev["probe_timeouts"] == 1
    assert ev["shots"]["1"]["ok"] and ev["shots"]["1"].get("carried")           # 输入没变：沿用
    assert not ev["shots"]["2"]["ok"] and "探针超时" in ev["shots"]["2"]["why"]
    c = SG.check_prompts(r, RUN, 1)
    assert not c["ok"] and "探针超时" in c["why"] and SG._is_stale_evidence([f"提示词：{c['why']}"])
    assert SG.check_prompts(r, RUN, 1, shot=1)["ok"]
    ev2 = SG.probe_prompts(RUN, 1, root=r, runner=boom)
    assert ev2["probe_timeouts"] == 2
    _lock(r, None, t=time.time())
    assert SG.probe_wait_s(RUN, 1, r) == SG.AUTO_PROBE_COOLDOWN_S * 2


def test_o1_probe_subprocess_timeout_raises_probe_timeout(tmp_path, monkeypatch):
    import subprocess
    r = _root(tmp_path)

    def run(*a, **k):
        raise subprocess.TimeoutExpired(a[0], k.get("timeout"))
    monkeypatch.setattr(SG.subprocess, "run", run)
    with pytest.raises(SG.ProbeTimeout, match="探针超时"):
        SG._probe_subprocess(RUN, 1, r, {"probe_timeout_s": 5})


# ---------------------------------------------------------------- O1(d) manifest_keys 总是写
def test_o1_manifest_keys_always_written(tmp_path):
    r = _root(tmp_path)
    ev = _probe(r, rows={"1": {"ok": True, "manifest_keys": ["characters/a"]}, "2": {"ok": False, "why": "编译出错"}})
    assert ev["manifest_keys"] == ["characters/a"] and ev["unkeyed"] == ["2"] and ev["fingerprint"] == ev["fingerprint_scoped"]
    assert all(r_.get("input_fp") for r_ in ev["shots"].values())


# ---------------------------------------------------------------- O1(e) 刷新中按镜沿用
def test_o1_refresh_running_keeps_unchanged_ok_shots_dispatchable(tmp_path, monkeypatch):
    r = _root(tmp_path, cfg={"enabled": True, "observe_stages": [], "whole_episode_prompts": False, "whole_episode_assets": False})
    _probe(r)
    _import_sha(r, "new")                                # 整集证据过期
    assert not SG.check_prompts(r, RUN, 1, shot=1)["ok"]               # 没在刷新：照旧挡（先触发探针）
    _lock(r, os.getpid())                                # 刷新中
    assert SG.check_prompts(r, RUN, 1, shot=1)["ok"] and SG.check_prompts(r, RUN, 1, shot=1).get("sticky")
    whole = SG.check_prompts(r, RUN, 1)
    assert not whole["ok"] and "证据过期" in whole["why"] and whole["ready_shots"] == [1, 2]   # 整集判仍报过期（自动探针照常）
    _w(r / "data/import/runs" / RUN / "script_v2.json",
       {"globals": {"style": "s"}, "episodes": [{"number": 1, "cast": ["a"], "shots": [{"index": 1, "text": "t1"}, {"index": 2, "text": "new"}]}]})
    assert SG.check_prompts(r, RUN, 1, shot=1)["ok"] and not SG.check_prompts(r, RUN, 1, shot=2)["ok"]
    assert SG.judge(RUN, 1, "出图", 1, r)["ok"]


# ---------------------------------------------------------------- O8 复盘并行
def test_o8_retro_parallel_default_lets_next_episode_start(tmp_path):
    r = _root(tmp_path, eps=(1, 2, 3))
    for e in (1, 2, 3):
        _probe(r, ep=e)
    assert SG.config(r).get("retro_parallel") is True
    assert SG.require(RUN, 2, "出图", shot=1, root=r)["ok"]                 # 第 1 集复盘没 done，第 2 集照样开工
    with pytest.raises(SG.SopGateError, match="第1集复盘"):                  # 第 3 集要等第 1 集复盘
        SG.require(RUN, 3, "出图", shot=1, root=r)
    _w(r / "docs/master/RETRO_ep01.md", "<!-- retro_status: done -->\n")
    assert SG.require(RUN, 3, "出图", shot=1, root=r)["ok"]


def test_o8_repo_config_documents_retro_parallel():
    c = json.loads((ROOT / "config/pipeline/sop_gate.json").read_text(encoding="utf-8"))
    assert c["retro_parallel"] is True and "L-205" in c["_retro_parallel"]


# ---------------------------------------------------------------- O2 按镜派单（ready 里写 partial 条目）
def test_o2_shot_ready_partial_episode_enters_only(tmp_path, monkeypatch):
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    import episode_pipeline as EP
    import runs as RN
    monkeypatch.setattr(EP, "ROOT", tmp_path)
    monkeypatch.setattr(EP, "OUT", tmp_path / "out")
    monkeypatch.setattr(RN, "ROOT", tmp_path)
    monkeypatch.setattr(EP, "owner_of_ep", lambda ep: "gpu36")
    monkeypatch.delenv("NS_PRIMARY_RUN", raising=False)                  # 测试夹具登记表自己的 primary
    _w(tmp_path / "config/pipeline/runs.json", {"primary": "rv2", "legacy_unprefixed_run": "v1", "runs": {"rv2": {"status": "producing"}}})
    _w(tmp_path / "data/import/runs/rv2/script_v2.json",
       {"episodes": [{"number": 1, "shots": [{"index": 1}, {"index": 2}]}, {"number": 2, "shots": [{"index": n} for n in (1, 2, 3)]},
                     {"number": 3, "shots": [{"index": 1}]}]})
    rp = tmp_path / "data/autopilot/runs/rv2/ready_episodes.json"
    _w(rp, {"episodes": {"1": {"ready_at": "t", "shots": ["ep01-S1", "ep01-S2"]}}})          # ep01 整集已准备
    aj = tmp_path / "data/pipeline/asset_jobs/rv2"
    _w(aj / "_ready_ep01.json", {"ready": False, "gaps": 1, "shot_gaps": {"2": ["脸"]}})
    _w(aj / "_ready_ep02.json", {"ready": False, "gaps": 1, "shot_gaps": {"2": ["[face] 黎岸"]}})
    _w(aj / "_ready_ep03.json", {"ready": False, "gaps": 1, "shot_gaps": {"*": ["场景底图"]}})
    pushed = []
    ch = EP.sync_shot_ready("rv2", push=pushed.append)
    d = json.loads(rp.read_text(encoding="utf-8"))
    assert ch == {2: 2} and pushed == ["gpu36"]
    assert d["episodes"]["2"]["shots"] == ["ep02-S1", "ep02-S3"] and d["episodes"]["2"]["partial"]
    assert d["episodes"]["1"] == {"ready_at": "t", "shots": ["ep01-S1", "ep01-S2"]}         # 整集已准备的不动
    assert "3" not in d["episodes"]                                                          # 全集缺口（*）= 一镜都不放
    assert EP.sync_shot_ready("rv2", push=pushed.append) == {} and pushed == ["gpu36"]      # 没变化不重写 / 不重推
    _w(aj / "_ready_ep02.json", {"ready": True, "gaps": 0, "shot_gaps": {}})                 # 资产补齐 → 自动放行
    assert EP.sync_shot_ready("rv2", push=pushed.append) == {2: 3}
    D = _load("tools/netfix/dispatch.py", "dispatch_fix_orch")
    part = {"images": {"gpu36": [2], "gpu33": [1, 3]}, "lanes": {"gpu36": ["gpu36:0"], "gpu33": ["gpu33:1"]}}
    f = D.control_for("gpu36", {}, json.loads(rp.read_text(encoding="utf-8")), part, ph={}, runs=[], run_id="rv2")
    assert f["only"] == ["ep02-S1", "ep02-S2", "ep02-S3"] and f["dispatch_by"]["partial_eps"] == [2]


# ---------------------------------------------------------------- O3 跨机借道自动开 / 还
IW = _load("tools/autopilot/idle_watch.py", "idle_watch_fix_orch")


def _lane_st(idle_min):
    return {ln: {"idle_min": m, "idle": m > 0} for ln, m in idle_min.items()}


def test_o3_relay_lend_idle_lanes_when_consumer_has_backlog_and_return_after():
    cfg = {**IW.DEFAULT_CFG, "actions": dict(IW.DEFAULT_CFG["actions"])}
    rcfg = {"enabled": True, "consumer_host": "gpu33"}
    lanes = ["gpu36:0", "gpu36:1", "gpu36:2"]
    images = {"gpu33": [1, 3], "gpu36": [2]}
    st = {}
    hold = {"hold": ["gpu36:1", "gpu36:2"]}                                    # 人工阶段交接：1/2 还给 gpu36 视频
    fr = {"ready_by_ep": {1: 4, 2: 9}}
    a = IW.relay_plan(cfg, st, 0, _lane_st({"gpu36:0": 0, "gpu36:1": 6, "gpu36:2": 2}), fr, images, rcfg, lanes, hold)
    assert a["op"] == "lend" and a["lanes"] == ["gpu36:1"] and a["hold"] == ["gpu36:2"] and a["host"] == "gpu36"
    st["relay"] = {"lent": ["gpu36:1"], "prev_hold": ["gpu36:1", "gpu36:2"]}
    assert IW.relay_plan(cfg, st, 0, _lane_st({"gpu36:1": 0, "gpu36:2": 1}), fr, images, rcfg, lanes, {"hold": ["gpu36:2"]}) is None
    b = IW.relay_plan(cfg, st, 0, _lane_st({}), {"ready_by_ep": {2: 9}}, images, rcfg, lanes, {"hold": ["gpu36:2"]})
    assert b["op"] == "return" and b["hold"] == ["gpu36:1", "gpu36:2"]           # gpu33 没 ready 了 → 还原人工 hold
    assert IW.relay_plan(cfg, {}, 0, _lane_st({"gpu36:1": 9}), fr, images, {"enabled": False}, lanes, hold) is None
    assert IW.relay_plan(cfg, {}, 0, _lane_st({"gpu36:1": 9}), {"ready_by_ep": {2: 5}}, images, rcfg, lanes, hold) is None   # gpu33 没活不借


def test_o3_tick_writes_hold_file_and_never_touches_gpu33_2(tmp_path):
    TW = _load("tests/test_idle_watch.py", "test_idle_watch_for_fix_orch")
    reg = {"episodes": [{"ep": 1, "shots": [{"shot": "ep01-S1", "objects": {"first": {"status": "ready"}}}]}]}

    class E(TW.FakeEnv):
        written = []
        def relay_cfg(self): return {"enabled": True, "consumer_host": "gpu33"}
        def relay_lanes(self, rcfg): return ["gpu36:0", "gpu36:1", "gpu36:2"]
        def relay_hold_read(self): return {"hold": "all"}
        def relay_hold_write(self, d): self.written.append(d)
        def partition_images(self): return {"gpu33": [1], "gpu36": [2]}
    env = E(tmp_path, reg=reg, probes={"gpu33": TW.probe(util=90, queue=1), "gpu36": TW.probe(util=0, queue=0)})
    c = TW.cfg(idle_min=5)
    _r0, r1, st = TW.run_ticks(env, c, 6)
    acts = [a for a in r1["actions"] if a["kind"] == "lane_relay"]
    assert acts and acts[0]["op"] == "lend" and env.written[-1]["hold"] == [] and st["relay"]["lent"] == ["gpu36:0", "gpu36:1", "gpu36:2"]
    assert st["relay"]["prev_hold"] == "all" and "gpu33:2" not in json.dumps(env.written)


def test_o3_partition_has_gpu36_2_lane():
    for rel in ("config/netfix/partition.json", "data/state/netfix/partition.json"):
        p = ROOT / rel
        if p.is_file():
            d = json.loads(p.read_text(encoding="utf-8"))
            assert d["lanes"]["gpu36"] == ["gpu36:0", "gpu36:1", "gpu36:2"] and "gpu33:2" not in json.dumps(d["lanes"])


# ---------------------------------------------------------------- O4 帧中继：60 s + 回执事件触发
def test_o4_relay_every_60s_and_outbox_event_triggers():
    RS = _load("tools/autopilot/resident_sync.py", "rs_fix_orch")
    assert RS.RELAY_EVERY_S == 60 and RS.RELAY_POLL_S == 15 and RS.LINK_KBPS >= 1000
    assert RS.relay_due(100.0, 0.0, {"gpu33": 1}, None) == "timer"
    assert RS.relay_due(100.0, 90.0, {"gpu33": 1}, {"gpu33": 1}) is None
    assert RS.relay_due(100.0, 90.0, {"gpu33": 2}, {"gpu33": 1}) == "outbox"
    sigs = iter([{"gpu33": 1}, {"gpu33": 1}, {"gpu33": 2}, {"gpu33": 2}])
    ticks, sleeps = [], []
    RS.relay_thread(every_s=3600, poll_s=15, sleep=sleeps.append, ticks=4, sig_fn=lambda: next(sigs), tick_fn=lambda: ticks.append(1))
    assert len(ticks) == 2 and sleeps == [15, 15, 15, 15]          # 第 1 拍定时 + 第 3 拍回执变了；中间不空跑


# ---------------------------------------------------------------- O6 资产作业道：15 分钟 hold + 续期 + 并发探针
def test_o6_hold_15min_renew_and_parallel_probe(monkeypatch):
    sys.path[:0] = [str(ROOT / "tools/pipeline"), str(ROOT)]
    import asset_worker as AW
    c = json.loads((ROOT / "config/pipeline/asset_worker.json").read_text(encoding="utf-8"))
    assert c["hold_minutes"] == 15 and c["job_timeout_min"] == 90 and AW.DEFAULTS["hold_minutes"] == 15

    class LN:
        calls = []

        @staticmethod
        def hold(lane, minutes, why, by=""):
            LN.calls.append((lane, minutes, by))
    j = {"id": "face-x", "lane_held_t": 1000.0}
    assert not AW.hold_renew(LN, j, "gpu36:0", {"hold_minutes": 15}, now=1000.0 + 400)
    assert AW.hold_renew(LN, j, "gpu36:0", {"hold_minutes": 15}, now=1000.0 + 460) and LN.calls == [("gpu36:0", 15.0, AW.BY)]
    import threading

    class H:
        @staticmethod
        def lanes(role="image"):
            return ["gpu33:0", "gpu33:1", "gpu36:0", "gpu36:1"]
    monkeypatch.setattr(AW, "broken_lanes", lambda h: set())
    monkeypatch.setattr(AW, "_lanes_mod", lambda: None)
    gate = threading.Barrier(4, timeout=5)

    def probe(lane):                                       # 4 道同时在探才放行：串行会在 Barrier 超时
        gate.wait()
        return {"ok": True, "busy": lane == "gpu33:1"}
    assert AW.free_lanes({}, set(), part={}, probe=probe, hosts_mod=H) == ["gpu33:0", "gpu36:0", "gpu36:1"]
