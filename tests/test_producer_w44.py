"""W44 PRODUCER-AUTONOMY（11-04）：今天 4 个“要人推一把”的坑写进代码。全部临时目录 + 打桩，不连网、不起进程。

① 误 canary 不自动恢复：结论记 code_sha；canary 只数本进程 / 本代码；pid / code_sha 变了自动恢复；到点重评估
② rescore 无上限：每镜每小时 ≤3 次，超了 rescore_cap 退避 30 分钟；看图 health loaded 后清零
③ 阶段接力：视频 ready 但没人跑 night → producer 接手；night finalize 的 epNN_vN.mp4 = 整集预览
④ hold_lanes：本机道的过期 hold 快照不挡派单；坏卡永远 hold；dispatch.held_lanes 到期记录不再永久 hold
"""
import json
import os
import subprocess
import sys
import threading
import time
import types
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
sys.path.insert(0, str(ROOT / "services" / "agent"))
import producer as PR  # noqa: E402
import pytest  # noqa: E402


@pytest.fixture(autouse=True)
def _keep_ns_run(monkeypatch):
    """W-FIX-PIPE：接力测试里的 VideoBridge 会 setdefault NS_RUN=tv_w44 / OFFLINE_SELF，不还原就漏进后面的 test_fix_night2（run_ctx 判剧名失败）"""
    for k in ("NS_RUN", "OFFLINE_SELF"):
        if k in os.environ:
            monkeypatch.setenv(k, os.environ[k])
        else:
            monkeypatch.delenv(k, raising=False)
            monkeypatch.setenv(k, "")
            monkeypatch.delenv(k)
    yield


def _paths(tmp_path):
    p = PR.Paths(root=tmp_path, pd=tmp_path / "pd", run_id="tv_w44")
    p.pd.mkdir(parents=True, exist_ok=True)
    return p


def _ev(paths, name=None):
    evs = [json.loads(x) for x in paths.log.read_text(encoding="utf-8").splitlines() if x.strip()] if paths.log.exists() else []
    return [e for e in evs if name is None or e["ev"] == name]


def _ctrl(paths):
    return json.loads(paths.ctrl.read_text(encoding="utf-8"))


HIT = {"item": "QB", "frac": 1.0, "n": 6, "version": "k", "shots": ["ep01-S1", "ep01-S2"]}


# ------------------------------------------------------------------ ① canary
def test_code_sha_cached_per_process_and_changes_with_content(tmp_path):
    d = tmp_path / "tools" / "autopilot"
    d.mkdir(parents=True)
    (d / "a.py").write_text("x = 1\n", encoding="utf-8")
    s1 = PR.code_sha(tmp_path)
    (d / "a.py").write_text("x = 2\n", encoding="utf-8")
    assert PR.code_sha(tmp_path) == s1                 # 启动时算一次：磁盘热推了、进程没加载 = 仍是旧代码
    assert PR.code_sha(tmp_path, fresh=True) != s1     # 重启（重新算）才变
    assert len(s1) == 16


def test_canary_key_scopes_by_code_pid_epoch(tmp_path):
    p = _paths(tmp_path)
    k = PR.canary_key(p, "v1", pid=1, sha="aaa")
    assert k != PR.canary_key(p, "v1", pid=2, sha="aaa") != PR.canary_key(p, "v1", pid=1, sha="bbb")
    p.ctrl.write_text(json.dumps({"canary_epoch": 3}), encoding="utf-8")
    assert PR.canary_key(p, "v1", pid=1, sha="aaa").endswith("+e3")


def test_canary_counts_only_current_code(tmp_path, monkeypatch):
    """旧进程（旧 code_sha）判的 6 个 QB fail 不进新进程的计数：新键从 0 数"""
    from ns_agent.vqa import canary as CN
    monkeypatch.setattr(CN, "STATE", tmp_path / "canary_state.json")
    monkeypatch.setattr(CN, "ALERTS", tmp_path / "alerts.jsonl")
    p = _paths(tmp_path)
    old = PR.canary_key(p, "v", pid=204016, sha="old")
    fail = {"ok": False, "blocking": ["QB"], "reasons": []}
    hits = [CN.observe(f"ep01-S{i}", "image", fail, key=old) for i in range(1, 7)]
    assert hits[-1] and hits[-1]["item"] == "QB"
    new = PR.canary_key(p, "v", pid=278513, sha="new")
    assert all(CN.observe(f"ep01-S{i}", "image", {"ok": True, "blocking": []}, key=new) is None for i in range(1, 7))
    assert json.loads(CN.STATE.read_text(encoding="utf-8"))["decided"]["action"] == "ok"


def test_postflight_stamps_code_sha_and_uses_scoped_key():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    body = src.split("    def _postflight(self", 1)[1].split("    def activate(", 1)[0]
    assert 'pf["code_sha"] = code_sha()' in body and "key=canary_key(self.p" in body and "canary_pause(self.p, hit)" in body
    tick = src.split("    def tick(self", 1)[1].split("    def hb_counts", 1)[0]
    assert tick.index("canary_tick(self.p)") < tick.index("pause_tick(self.p)")


def test_canary_pause_records_pid_sha_and_expiry(tmp_path):
    p = _paths(tmp_path)
    c = PR.canary_pause(p, HIT, pid=11, sha="s1")
    assert c["paused"] and c["reason_kind"] == "canary" and c["canary"]["pid"] == 11 and c["canary"]["code_sha"] == "s1"
    left = PR.ts_epoch(c["expires_at"]) - time.time()
    assert PR.CANARY_EXPIRE_S - 60 < left <= PR.CANARY_EXPIRE_S + 1
    assert PR.canary_tick(p, pid=11, sha="s1") is None            # 同进程同代码、未到点：不动
    assert _ctrl(p)["paused"]


def test_canary_auto_resume_on_new_code_or_pid_or_legacy(tmp_path):
    p = _paths(tmp_path)
    PR.canary_pause(p, HIT, pid=11, sha="s1")
    r = PR.canary_tick(p, pid=11, sha="s2")                       # 热修后重启：代码变了
    assert r["action"] == "canary_auto_resume" and not _ctrl(p)["paused"] and _ctrl(p)["canary_epoch"] == 1
    e = _ev(p, "canary_auto_resume")[-1]
    assert "s1" in e["why"] and e["was"]["pid"] == 11
    PR.canary_pause(p, HIT, pid=11, sha="s1")
    assert PR.canary_tick(p, pid=12, sha="s1")["action"] == "canary_auto_resume"   # 只换 pid 也失效
    # W44 之前写的 canary（没有 pid / code_sha，如 11-04 02:30 那条）
    PR.set_paused(p, True, by="POLICY_CANARY", kind="canary", note="旧 canary")
    assert PR.canary_tick(p, pid=12, sha="s1")["action"] == "canary_auto_resume"
    assert not _ctrl(p)["paused"]
    PR.set_paused(p, True, by="MASTER", kind="master")            # 别的暂停不碰
    assert PR.canary_tick(p, pid=12, sha="s1") is None and _ctrl(p)["paused"]


def test_canary_expiry_reevaluates_with_backoff(tmp_path):
    p = _paths(tmp_path)
    PR.canary_pause(p, HIT, pid=11, sha="s1")
    r = PR.canary_tick(p, pid=11, sha="s1", t=time.time() + PR.CANARY_EXPIRE_S + 5)
    c = _ctrl(p)
    assert r["action"] == "canary_reeval" and not c["paused"] and c["canary_epoch"] == 1 and c["canary_strikes"] == 1
    assert _ev(p, "canary_reeval")
    c2 = PR.canary_pause(p, HIT, pid=11, sha="s1")                # 同一份代码再触发：暂停翻倍
    assert PR.ts_epoch(c2["expires_at"]) - time.time() > PR.CANARY_EXPIRE_S * 2 - 60


# ------------------------------------------------------------------ ② rescore 上限
def _pr(tmp_path, ledger=None):
    paths = _paths(tmp_path)
    if ledger:
        paths.ledger.write_text(json.dumps(ledger, ensure_ascii=False), encoding="utf-8")
    pr = PR.Producer(paths, script=object(), lanes={}, lane_probe=lambda u: {"ok": True, "n": 0},
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)
    return pr, paths


def _reg(*objs):
    return {"episodes": [{"ep": 1, "shots": [{"shot": o["shot"], "index": 1, "objects": {"first": o}} for o in objs]}]}


def _o(sid):
    return {"id": f"first:{sid}", "kind": "first", "shot": sid, "ep": 1, "status": "ready", "waiting_for": "空闲道"}


def test_rescore_hourly_cap_then_backoff(tmp_path):
    pr, paths = _pr(tmp_path, {"first:ep01-S7": {"rescore_take": 3}})
    pr._rescore_one = lambda o, n: None
    for _ in range(3):
        assert pr.dispatch_rescores(_reg(_o("ep01-S7"))) == 1
        pr.rescore_pool.submit(lambda: None).result()
        with pr.mu:
            pr._rescore_futs.clear()
            pr.inflight.clear()
        pr.leases.release("first:ep01-S7")
    assert len(pr.ledger()["first:ep01-S7"]["rescore_times"]) == 3
    assert pr.dispatch_rescores(_reg(_o("ep01-S7"))) == 0          # 第 4 次：封顶
    led = pr.ledger()["first:ep01-S7"]
    assert led["rescore_capped"] and led["backoff_until"] > time.time() + PR.RESCORE_CAP_BACKOFF_S - 30
    e = _ev(paths, "rescore_cap")[-1]
    assert e["obj"] == "first:ep01-S7" and e["n_1h"] == 3
    assert pr.dispatch_rescores(_reg(_o("ep01-S7"))) == 0          # 退避期不派
    pr.rescore_pool.shutdown(wait=True)


def test_rescore_times_older_than_hour_dont_count(tmp_path):
    old = time.time() - 3700
    pr, _ = _pr(tmp_path, {"first:ep01-S2": {"rescore_take": 1, "rescore_times": [old, old, old]}})
    gate = threading.Event()
    pr._rescore_one = lambda o, n: gate.wait(5)
    assert pr.dispatch_rescores(_reg(_o("ep01-S2"))) == 1
    assert len(pr.ledger()["first:ep01-S2"]["rescore_times"]) == 1
    gate.set()
    pr.rescore_pool.shutdown(wait=True)


def test_rescore_cap_reset_when_vlm_loaded(tmp_path):
    pr, paths = _pr(tmp_path, {"first:ep01-S7": {"rescore_take": 3, "rescore_capped": True, "backoff_until": time.time() + 1800,
                                                 "rescore_times": [time.time()] * 3},
                               "first:ep01-S8": {"rescore_take": 2}})
    assert pr.rescore_cap_reset(health_fn=lambda: {"loaded": False}) == []
    assert pr.ledger()["first:ep01-S7"]["rescore_capped"]
    pr._cap_health_at = 0
    assert pr.rescore_cap_reset(health_fn=lambda: {"loaded": True, "url": "x"}) == ["first:ep01-S7"]
    led = pr.ledger()["first:ep01-S7"]
    assert not led["rescore_capped"] and led["backoff_until"] == 0 and led["rescore_times"] == []
    assert _ev(paths, "rescore_cap_reset")
    called = []
    assert pr.rescore_cap_reset(health_fn=lambda: called.append(1) or {"loaded": True}) == [] and not called   # 没封顶的不探
    pr.rescore_pool.shutdown(wait=True)


def test_tick_calls_cap_reset_before_rescore_dispatch():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    tick = src.split("    def tick(self", 1)[1].split("    def hb_counts", 1)[0]
    assert tick.index("self.rescore_cap_reset()") < tick.index("self.dispatch_rescores(reg)")


# ------------------------------------------------------------------ ③ 阶段接力
def _vreg(status="ready"):
    return {"episodes": [{"ep": 1, "shots": [{"shot": "ep01-S1", "objects": {"video": {"status": status}}},
                                             {"shot": "ep01-S2", "objects": {"video": {"status": "pending"}}}]}]}


def test_night_stalled_and_takeover_runs_loop_once(tmp_path, monkeypatch):
    p = _paths(tmp_path)
    vb = PR.VideoBridge(p)
    ran = threading.Event()
    part = {"1": "gpu33"}
    fake = types.SimpleNamespace(RUN_ID="tv_w44", STATE=p.vid / "night_state.json", loop_once=lambda st: ran.set(),
                                 partition_hosts=lambda: part)
    monkeypatch.setitem(sys.modules, "night", fake)
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    monkeypatch.setenv("NS_RUN", os.environ.get("NS_RUN", ""))  # PS-MASTER 11-06：VideoBridge 会 setdefault NS_RUN=tv_w44，测完由 monkeypatch 还原，免得污染后面的测试
    if not os.environ.get("NS_RUN"):
        monkeypatch.delenv("NS_RUN")
    assert vb.night_stalled(_vreg(), night_alive=True) is None          # night 在跑：不接
    assert vb.night_stalled(_vreg("pending"), night_alive=False) is None  # 没有等派的视频：不接
    why = vb.night_stalled(_vreg(), night_alive=False)
    assert why and "ep01-S1" in why and "不存在" in why
    p.vid.mkdir(parents=True, exist_ok=True)
    (p.vid / "night_state.json").write_text("{}", encoding="utf-8")
    assert vb.night_stalled(_vreg(), night_alive=False) is None          # night 刚写过状态：不接
    assert vb.night_stalled(_vreg(), night_alive=False, t=time.time() + PR.NIGHT_STALE_S + 5)
    (p.vid / "night_state.json").unlink()
    part["1"] = "gpu36"                                                  # 总调度 05:1x：分区不归本机 → 不接（不和 gpu36 的 night 抢）
    assert vb.night_stalled(_vreg(), night_alive=False) is None
    part["1"] = "gpu33"
    monkeypatch.delenv("OFFLINE_SELF")
    assert vb.night_stalled(_vreg(), night_alive=False) is None          # 笔记本（无 OFFLINE_SELF）不接
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    logs = []
    vb.tick(_vreg(), {"workers": {"video": "VIDEO10"}, "auto_force_eps": False}, False, lambda ev, **kw: logs.append((ev, kw)))
    vb._takeover_th.join(5)
    assert ran.is_set() and logs[0][0] == "video_takeover"
    ran.clear()
    vb.tick(_vreg(), {"workers": {"video": "VIDEO10"}, "auto_force_eps": False, "video_takeover": False}, False, lambda ev, **kw: None)
    time.sleep(0.05)
    assert not ran.is_set()                                              # 开关关掉不接


def test_night_module_wrong_run_refused(tmp_path, monkeypatch):
    p = _paths(tmp_path)
    vb = PR.VideoBridge(p)
    monkeypatch.setitem(sys.modules, "night", types.SimpleNamespace(RUN_ID="series10_v1", loop_once=lambda st: None))
    logs = []
    assert vb.takeover("x", lambda ev, **kw: logs.append((ev, kw)))
    vb._takeover_th.join(5)
    assert logs[-1][0] == "video_err" and "series10_v1" in logs[-1][1]["error"]


def test_preview_object_recognises_night_finalize_output():
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert 'glob(f"ep{n:02d}_v*.mp4")' in src
    body = src.split('po = obj("preview"', 1)[1].split("E[\"objects\"].update", 1)[0]
    assert "if final.exists():" in body


# ------------------------------------------------------------------ ④ hold_lanes
PART = {"lanes": {"gpu33": ["gpu33:0", "gpu33:1", "gpu33:3"], "gpu36": ["gpu36:0", "gpu36:1"], "laptop": ["laptop:0"]},
        "retired_lanes": ["gpu36:2", "gpu33:0"],
        "_temp_holds": {"gpu33:0": {"by": "ASSET-WORKER", "expires_at": "2026-11-04T02:40:33"}}, "_lent_lanes": {}}
CTRL = {"hold_lanes": ["gpu33:0", "gpu36:0", "gpu36:1", "gpu36:2", "laptop:0"],
        "dispatch_by": {"by": "NETFIX dispatch.py", "at": "2026-11-04T02:25:54", "host": "gpu33"}}


def test_expired_temp_hold_on_own_lane_released():
    after = PR.ts_epoch("2026-11-04T02:41:00")
    hold, rel = PR.effective_holds(CTRL, PR.IMAGE_LANES, PART, t=after)
    assert "gpu33:0" not in hold and "gpu33:0" in rel
    assert {"gpu36:0", "gpu36:1", "laptop:0", "gpu33:2", "gpu36:2"} <= hold      # 别的机器的道 + 坏卡照 hold
    before = PR.ts_epoch("2026-11-04T02:30:00")
    hold, rel = PR.effective_holds(CTRL, PR.IMAGE_LANES, PART, t=before)     # 临时 hold 没到期：照 hold
    assert "gpu33:0" in hold and not rel


def test_manual_and_retired_and_unknown_kept():
    after = PR.ts_epoch("2026-11-04T03:00:00")
    c = {**CTRL, "lane_notes": {"gpu33:0": {"held_by": "MASTER"}}}
    assert "gpu33:0" in PR.effective_holds(c, PR.IMAGE_LANES, PART, t=after)[0]          # 人工显式 hold
    part = {**PART, "retired_lanes": ["gpu33:0"], "_temp_holds": {}}
    assert "gpu33:0" in PR.effective_holds(CTRL, PR.IMAGE_LANES, part, t=after)[0]       # 真退役（无到期记录）
    assert "gpu33:0" in PR.effective_holds(CTRL, PR.IMAGE_LANES, None, t=after)[0]       # 读不到分区：失败关闭
    c2 = {**CTRL, "dispatch_by": {}}
    assert "gpu33:0" in PR.effective_holds(c2, PR.IMAGE_LANES, PART, t=after)[0]         # 不知道本机：失败关闭
    assert "gpu33:2" in PR.effective_holds({}, PR.IMAGE_LANES, None)[0]   # L-194（11-05 项目方授权）：gpu36:2 不再写死坏卡；只剩 gpu33:2


def test_probe_lanes_uses_effective_holds_and_logs_once(tmp_path):
    (tmp_path / "config/netfix").mkdir(parents=True)
    part = {**PART, "_temp_holds": {"gpu33:0": {"by": "ASSET-WORKER", "expires_at": "2000-01-01T00:00:00"}}}
    (tmp_path / "config/netfix/partition.json").write_text(json.dumps(part), encoding="utf-8")
    paths = _paths(tmp_path)
    pr = PR.Producer(paths, script=object(), lanes={"gpu33:0": "u0", "gpu33:1": "u1"}, lane_probe=lambda u: {"ok": True, "n": 0},
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda l: False)
    out = pr.probe_lanes({**CTRL, "hold_lanes": ["gpu33:0", "gpu33:1"],
                          "lane_notes": {"gpu33:1": {"held_by": "W41"}}})
    assert out["gpu33:0"]["free"] and not out["gpu33:1"]["free"]
    pr.probe_lanes({**CTRL, "hold_lanes": ["gpu33:0"]})
    assert len(_ev(paths, "hold_stale_release")) == 1


def test_dispatch_held_lanes_expired_record_not_permanent():
    code = ("import sys,json; sys.path.insert(0, r'%s'); import dispatch as D; "
            "p=json.loads(sys.argv[1]); print(json.dumps(sorted(D.held_lanes(p, float(sys.argv[2])))))") % (ROOT / "tools/netfix")
    after = str(PR.ts_epoch("2026-11-04T02:41:00"))
    r = subprocess.run([sys.executable, "-c", code, json.dumps(PART), after], capture_output=True, text=True, timeout=60,
                       cwd=str(ROOT), env={**os.environ, "NS_SSH_SHIM": "off"})
    assert r.returncode == 0, r.stderr[-500:]
    held = json.loads(r.stdout.strip().splitlines()[-1])
    assert "gpu33:0" not in held and "gpu36:2" in held
    before = str(PR.ts_epoch("2026-11-04T02:30:00"))
    r = subprocess.run([sys.executable, "-c", code, json.dumps(PART), before], capture_output=True, text=True, timeout=60,
                       cwd=str(ROOT), env={**os.environ, "NS_SSH_SHIM": "off"})
    assert "gpu33:0" in json.loads(r.stdout.strip().splitlines()[-1])
