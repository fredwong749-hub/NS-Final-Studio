"""FIX-A 11-05（REVIEW-A 复审问题的回归）：sweep 采用 redo_exhausted / heavy_cannot_fix 按时间 / IMAGE_LANES / night shared_lanes /
expire_holds 不重复插 path / sop_gate 关日志句柄 / resident_sync 心跳 +09:00 / 重启带 vidgen / regen 空清单 rc 0"""
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
sys.path.insert(0, str(ROOT / "tools" / "series10_video"))
import producer as PR  # noqa: E402


def _load(rel, name):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


class FakeProd:
    """只借 adopt_best_effort_sweep（用真实方法绑到最小对象上）"""
    adopt_best_effort_sweep = PR.Producer.adopt_best_effort_sweep
    clear_reject = PR.Producer.clear_reject          # FIX-PROD-2 D7：采用后清驳回记录

    def __init__(self, led):
        self.p = type("P", (), {"root": ROOT})()
        self._led, self.updates, self.events = led, [], []

    def ledger(self):
        return self._led

    def led_update(self, oid, **kw):
        self.updates.append((oid, kw))

    def logf(self, *a, **k):
        self.events.append((a, k))


def _reg(*ids):
    return {"episodes": [{"shots": [{"objects": {"first": {"id": i, "status": "best_effort"}, "last": {"id": "last:x", "status": "passed"}}}
                                    for i in ids]}]}


def _sweep(monkeypatch, led, oid="first:ep01-S1"):
    adopted = []
    monkeypatch.setattr(PR, "review_adopt_auto", lambda root=ROOT: True)
    monkeypatch.setattr(PR, "review_adopt", lambda p, o, by="", relaxed=False: adopted.append(o) or 3)
    fp = FakeProd(led)
    out = fp.adopt_best_effort_sweep(_reg(oid), every_s=0)
    return out, adopted


def test_sweep_adopts_when_tries_exhausted(monkeypatch):
    out, ad = _sweep(monkeypatch, {"first:ep01-S1": {"final": "best_effort", "tries": PR.MAX_TRIES}})
    assert out == ["first:ep01-S1"] and ad == ["first:ep01-S1"]


def test_sweep_adopts_when_redo_exhausted_even_if_tries_low(monkeypatch):
    out, ad = _sweep(monkeypatch, {"first:ep01-S1": {"final": "best_effort", "tries": 1, "redo_exhausted": True}})
    assert out == ["first:ep01-S1"] and ad == ["first:ep01-S1"]


def test_sweep_does_not_adopt_unexhausted(monkeypatch):
    out, ad = _sweep(monkeypatch, {"first:ep01-S1": {"final": "best_effort", "tries": 1}})
    assert out == [] and ad == []


def test_heavy_cannot_fix_uses_latest_by_timestamp_not_list_order():
    led = {"redo_history": [{"at": "2026-11-05T10:00:00+09:00", "ok": False, "blocking": ["Q9"]}],
           "history": [{"at": "2026-11-05T12:00:00+09:00", "ok": False, "blocking": ["Q1"]}]}      # history 里的更新
    assert PR.heavy_cannot_fix(led, {"skip_heavy_on": ["Q1"]}) == ["Q1"]
    led2 = {"redo_history": [{"at": "2026-11-05T13:00:00+09:00", "ok": False, "blocking": ["Q9"]}],
            "history": [{"at": "2026-11-05T12:00:00+09:00", "ok": False, "blocking": ["Q1"]}]}
    assert PR.heavy_cannot_fix(led2, {"skip_heavy_on": ["Q1"]}) is None


def test_image_lanes_has_gpu36_2_not_gpu33_2():
    assert PR.IMAGE_LANES["gpu36:2"] == "http://127.0.0.1:18290" and "gpu33:2" not in PR.IMAGE_LANES


def test_regen_empty_list_is_rc0(tmp_path, monkeypatch, capsys):
    from unittest.mock import MagicMock
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd")
    paths.pd.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(PR, "Paths", lambda *a, **k: paths)
    monkeypatch.setattr(PR, "default_run", lambda: "r")
    monkeypatch.setattr(PR, "_runs", lambda: MagicMock())
    monkeypatch.setattr(PR, "regen_cmd", lambda *a, **k: {"regen": [], "skipped": {"ep01-S1": "没有当前首帧"}})
    assert PR.main(["regen", "--episode", "1"]) == 0
    monkeypatch.setattr(PR, "regen_cmd", lambda *a, **k: {"regen": [], "error": "登记表里找不到第 9 集的镜"})
    assert PR.main(["regen", "--episode", "9"]) == 1


def test_night_shared_lanes_include_gpu36_2():
    N = _load("tools/series10_video/night.py", "night_fix_a")
    assert "gpu36:2" in N.DEFAULT_CTRL["shared_lanes"] and "gpu33:2" not in N.DEFAULT_CTRL["shared_lanes"]


def test_expire_holds_does_not_grow_sys_path(tmp_path, monkeypatch):
    N = _load("tools/series10_video/night.py", "night_fix_a2")
    monkeypatch.setattr(N, "VID", tmp_path)
    monkeypatch.setattr(N, "log", lambda *a: None)
    ctrl = {"hold_lanes": ["gpu36:0"], "hold_expires": {"gpu36:0": "2999-01-01T00:00:00+09:00"}}
    N.expire_holds(dict(ctrl))
    n1 = sys.path.count(str(ROOT / "tools" / "autopilot"))
    N.expire_holds(dict(ctrl))
    N.expire_holds(dict(ctrl))
    assert sys.path.count(str(ROOT / "tools" / "autopilot")) == n1


def test_sop_gate_auto_probe_closes_log_handle(tmp_path, monkeypatch):
    SG = _load("tools/master/sop_gate.py", "sop_gate_fix_a")
    monkeypatch.setattr(SG, "ROOT", tmp_path)
    opened = []
    import subprocess
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: opened.append(k["stdout"]))
    r = SG.auto_probe_stale("r1", 1, root=tmp_path, missing=["提示词证据过期"], now=1_800_000_000.0)
    assert r == "started" and opened and opened[0].closed


def test_resident_sync_heartbeat_ts_has_jst_offset(tmp_path):
    RS = _load("tools/autopilot/resident_sync.py", "rs_fix_a")
    out = RS.episode_run_tick_once({"enabled": False, "interval_s": 60, "targets": []}, tick_fn=lambda *a: {}, hb_path=tmp_path / "hb.json")
    assert out["ts"].endswith("+09:00") and len(out["ts"]) == 25


def test_restart_night_only_and_all_restart_vidgen_but_producer_only_does_not(monkeypatch):
    RS = _load("tools/autopilot/resident_sync.py", "rs_fix_a2")
    sh, vid = [], []
    monkeypatch.setattr(RS, "ssh", lambda host, cmd, *a, **k: (sh.append(cmd), b"ok")[1])
    monkeypatch.setattr(RS, "log", lambda *a: None)
    monkeypatch.setattr(RS, "restart_vidgen", lambda host: (vid.append(host), "vidgen ok")[1])
    assert "vidgen ok" in RS.restart("gpu36", "night-only")
    assert "vidgen ok" in RS.restart("gpu36", "all")
    RS.restart("gpu36", "producer-only")
    assert vid == ["gpu36", "gpu36"]


def test_restart_vidgen_calls_deploy_stop_then_start(monkeypatch):
    RS = _load("tools/autopilot/resident_sync.py", "rs_fix_a3")
    calls = []
    monkeypatch.setattr(RS.subprocess, "run", lambda args, **k: (calls.append(args[-2:]),
                                                                  type("R", (), {"stdout": b"ok", "stderr": b""})())[1])
    RS.restart_vidgen("gpu36")
    assert calls == [["stop", "gpu36"], ["start", "gpu36"]]


# ---- 视频分片动态抢活
VS = _load("tools/series10_video/video_shard.py", "video_shard_fix_a")
C = {"owner": "gpu36", "weights": {"gpu36": 3, "gpu33": 2}, "map": {}, "hosts": ["gpu33", "gpu36"]}
PLAN = {"ep01-S1": "gpu36", "ep01-S2": "gpu33", "ep01-S3": "gpu36", "ep01-S4": "gpu36"}


def test_idle_host_claims_unstarted_shot_from_other_host_tail_first():
    merged = {"ep01-S2": {"status": "done", "renders": [{}]}}          # gpu33 的镜出完了，gpu36 还有 S1/S3/S4 没开工
    cl = VS.decide_claims(C, PLAN, merged, {}, {"gpu33": 0, "gpu36": 2}, 1000.0)
    assert cl == {"ep01-S4": {"host": "gpu33", "from": "gpu36", "at": 1000.0}}   # 每台每轮 1 个，尾部先领
    eff = VS.apply_claims(PLAN, cl)
    assert eff["ep01-S4"] == "gpu33" and eff["ep01-S1"] == "gpu36"


def test_busy_host_or_host_with_own_unstarted_shots_does_not_claim():
    assert VS.decide_claims(C, PLAN, {}, {}, {"gpu33": 1, "gpu36": 1}, 1.0) == {}                 # 都在忙
    assert VS.decide_claims(C, PLAN, {}, {}, {"gpu33": 0, "gpu36": 1}, 1.0) == {}                 # gpu33 名下 S2 还没开工 = 不算闲


def test_started_shots_cannot_be_claimed_and_claim_not_duplicated():
    merged = {"ep01-S2": {"status": "done", "renders": [{}]}, "ep01-S4": {"status": "rendering", "renders": [{"state": "submitted"}]}}
    cl = VS.decide_claims(C, PLAN, merged, {}, {"gpu33": 0, "gpu36": 2}, 1.0)
    assert list(cl) == ["ep01-S3"]                                       # S4 已开工，跳过
    cl2 = VS.decide_claims(C, PLAN, merged, cl, {"gpu33": 0, "gpu36": 2}, 2.0)
    assert cl2 == cl                                                     # 已领的镜还没开工 = 领取台名下有活，不算闲，不再多领


def test_unstarted_claim_expires_after_lease_started_claim_stays():
    claims = {"ep01-S3": {"host": "gpu33", "from": "gpu36", "at": 0.0}, "ep01-S4": {"host": "gpu33", "from": "gpu36", "at": 0.0}}
    merged = {"ep01-S4": {"status": "rendering", "renders": [{"state": "submitted"}]}}
    live = VS.live_claims(claims, merged, VS.CLAIM_LEASE_S + 1)
    assert list(live) == ["ep01-S4"]                                     # S3 超时没开工 → 回收；S4 开工了 → 归属不翻


def test_plan_all_overlays_claims(tmp_path):
    cfg = {"enabled": True, "runs": {"r1": {"eps": {"1": {"owner": "gpu36", "weights": {"gpu36": 1, "gpu33": 1}}}}}}
    specs = {f"ep01-S{i}": type("S", (), {"episode": 1, "duration_s": 5.0})() for i in (1, 2)}
    base = VS.plan_all("r1", specs, cfg)
    sid = next(s for s, h in base.items() if h == "gpu36")
    out = VS.plan_all("r1", specs, cfg, claims={sid: {"host": "gpu33", "from": "gpu36", "at": 1.0}})
    assert out[sid] == "gpu33" and VS.plan_all("r1", specs, cfg)[sid] == "gpu36"


def test_relay_arbitrate_writes_claims_file_only_for_idle_host(tmp_path):
    SR = _load("tools/series10_video/shard_relay.py", "shard_relay_fix_a")
    # 本测试只测 FIX-A 的空闲领活仲裁，不测 L-206 工位分卡。以前靠 lane_roles.json from_episode=2 让 ep01“不适用”；
    # L-208 ⑤（sv-20261106-11 起 from_episode=1，卡位规则 ep01 起生效）后 ep01 在首尾帧阶段 gpu33 没有视频道 → 被当忙、不领。
    # 固定为“不适用”（None），不读真实仓库的 lane_roles 配置 / 阶段表（分卡下的领活另由 test_l206_lane_roles_vid 覆盖）
    SR.role_video_hosts = lambda run, ep, shot_ids: None
    vid = tmp_path / "video"
    vid.mkdir()
    (vid / "jobs.json").write_text(json.dumps({"shots": [{"shot": s, "ep": 1, "host": h, "variants": {"v1": {}}} for s, h in PLAN.items()]}), encoding="utf-8")
    (vid / "state_gpu33.json").write_text(json.dumps({"saved": 100.0, "shots": {"ep01-S2": {"status": "done", "renders": [{"state": "done"}]}}}), encoding="utf-8")
    (vid / "state_gpu36.json").write_text(json.dumps({"saved": 100.0, "shots": {"ep01-S1": {"status": "rendering", "renders": [{"state": "submitted"}]}}}), encoding="utf-8")
    # FIX-VID D1 / D13：state 带 saved（新鲜才可领、失联才收回）；只有有变体的镜进静态计划
    cl = SR.arbitrate_claims("r1", vid, "video", C, 1, now=100.0)
    assert list(cl) == ["ep01-S4"] and cl["ep01-S4"]["host"] == "gpu33"
    assert VS.load_claims(vid) == cl
    # 领取已体现在 jobs.json 的 host 后再仲裁一轮：还原静态计划，不会把领取固化 / 重复领
    jobs = json.loads((vid / "jobs.json").read_text(encoding="utf-8"))
    for s in jobs["shots"]:
        s["host"] = VS.apply_claims(PLAN, cl)[s["shot"]]
    (vid / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    cl2 = SR.arbitrate_claims("r1", vid, "video", C, 1, now=200.0)
    assert cl2["ep01-S4"]["from"] == "gpu36" and "ep01-S3" in cl2 or list(cl2) == ["ep01-S4"]
