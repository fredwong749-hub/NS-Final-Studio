"""SELF-HEAL 11-05：tools/master/health_tick.py 每项检查 + 修复 + 退避 / 熔断 + 报告（全 mock，不碰真进程 / 网络 / 服务器）。"""
import importlib.util
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("health_tick_t", ROOT / "tools/master/health_tick.py")
H = importlib.util.module_from_spec(spec)
sys.modules["health_tick_t"] = H
spec.loader.exec_module(H)

NOW = 1_800_000_000.0
RS_CMD = r'"D:\NS\.venv\Scripts\python.exe" -u tools/autopilot/resident_sync.py loop'


def P(pid, cmd, ppid=1, created=NOW - 7200):
    return {"pid": pid, "ppid": ppid, "cmd": cmd, "created": created}


GUARDS = [P(90, "powershell -File ops/autostart/resident_guard.ps1"), P(91, "powershell -File ops/autostart/monitor_guard.ps1")]
TUN = [P(80, r"pythonw tools\netfix\tunnel_supervisor.py serve --conf x")]
RSP = [P(10, RS_CMD), P(11, RS_CMD.replace(".venv\\Scripts\\python.exe", "Python312\\python.exe"), ppid=10)]
ALL_UP = RSP + GUARDS + TUN


class FakeEnv(H.Env):
    def __init__(self, root, procs=None, http=True, tcp=True, now=NOW):
        super().__init__(root)
        self._procs, self.http, self.tcp, self._now = list(procs if procs is not None else ALL_UP), http, tcp, now
        self.calls, self.chan, self.issues, self.pending = [], [], [], {}
        self.stale, self.probe_ret, self.report_exc, self.run_ok = [], "started", None, True
        self.mt = {}

    def now(self): return self._now
    def procs(self): return list(self._procs)
    def http_ok(self, url, timeout=8): return self.http if not callable(self.http) else self.http(url)
    def tcp_ok(self, port, timeout=3): return self.tcp if not callable(self.tcp) else self.tcp(port)
    def run(self, cmd, timeout=300): self.calls.append(("run", cmd)); return {"ok": self.run_ok, "rc": 0 if self.run_ok else 1, "out": "x"}
    def spawn_detached(self, cmd, log): self.calls.append(("spawn", cmd, log)); return {"ok": self.run_ok, "pid": 1}
    def rq_pending(self, host): return self.pending.get(host, [])
    def rq_request(self, host, reason, mode, urgent): self.calls.append(("rq", host, mode, urgent)); return {"id": "rq1"}
    def probe_stale(self, run, ep, missing): self.calls.append(("probe", run, ep)); return self.probe_ret
    def stale_prompt_eps(self, run): return self.stale
    def report(self, run, step, what, fix_hint, blocking):
        if self.report_exc:
            raise self.report_exc
        self.issues.append((step, what, blocking)); return f"ISS-{len(self.issues)}"
    def channel(self, level, text, now): self.chan.append((level, text))
    def mtime(self, path):
        return self.mt.get(Path(path).name, super().mtime(path))


def wj(root, rel, d):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(d), encoding="utf-8")


def base(tmp_path, **kw):
    wj(tmp_path, "config/pipeline/runs.json", {"primary": "r1"})
    wj(tmp_path, "config/netfix/tunnels.json", {"hosts": {"gpu36-l2": {"probe_http": [18290]}, "gpu33-l0": {"probe_http": [18188]}}})
    if not (Path(tmp_path) / "data/autopilot/resident_sync.json").exists():
        srv(tmp_path)          # 默认两台服务器健康（check_server 后加；没有健康记录 = 会报 srv:*:health）
    return FakeEnv(tmp_path, **kw)


def cfg(**kw):
    c = H.load_cfg(Path("/nonexistent.json"))
    c.update(kw)
    return c


def run_ticks(env, c, n=2, st=None):
    st = st if st is not None else {}
    out = None
    for _ in range(n):
        out = H.tick(env, c, st, save=False)
    return out, st


# ---------------------------------------------------------------- 进程类
def test_healthy_no_findings(tmp_path):
    out, _ = run_ticks(base(tmp_path), cfg(), 2)
    assert out["findings"] == [] and out["actions"] == {}


def test_resident_sync_missing_dry_then_apply(tmp_path):
    procs = GUARDS + TUN
    e = base(tmp_path, procs=procs)
    out, st = run_ticks(e, cfg(), 2)                       # 默认 apply=false：只报
    assert out["actions"]["proc:resident_sync"]["action"] == "dry" and not e.calls
    assert e.issues and e.chan and e.chan[0][0] == "NOTE"   # 从不静默
    e2 = base(tmp_path, procs=procs)
    out, st = run_ticks(e2, cfg(apply=True), 2)
    assert out["actions"]["proc:resident_sync"]["action"] == "done"
    assert e2.calls[0][0] == "spawn" and e2.calls[0][1][-2:] == ["resident_sync.py".replace("resident_sync.py", "tools/autopilot/resident_sync.py"), "loop"][-2:] or "loop" in e2.calls[0][1]


def test_single_tick_flap_does_not_act(tmp_path):
    e = base(tmp_path, procs=GUARDS + TUN)
    out, _ = run_ticks(e, cfg(apply=True), 1)
    assert out["findings"] and out["actions"] == {} and not e.calls


def test_venv_shim_pair_is_not_duplicate_but_two_roots_are(tmp_path):
    e = base(tmp_path, procs=ALL_UP)
    out, _ = run_ticks(e, cfg(), 2)
    assert not [f for f in out["findings"] if f["key"].startswith("dup:")]
    extra = ALL_UP + [P(20, RS_CMD, created=NOW - 100)]
    e2 = base(tmp_path, procs=extra)
    out, _ = run_ticks(e2, cfg(apply=True), 2)
    assert out["actions"]["dup:resident_sync"]["action"] == "dry"      # kill_duplicates=false：只报，不停
    assert not [c for c in e2.calls if c[0] == "run"]
    e3 = base(tmp_path, procs=extra)
    out, _ = run_ticks(e3, cfg(apply=True, kill_duplicates=True), 2)
    kills = [c[1] for c in e3.calls if c[0] == "run"]
    assert kills == [["taskkill", "/PID", "20", "/T", "/F"]]           # 只停新的那份，按 pid


def test_lane_relay_only_when_enabled(tmp_path):
    e = base(tmp_path)
    assert not run_ticks(e, cfg(), 2)[0]["findings"]
    wj(tmp_path, "config/pipeline/lane_relay.json", {"enabled": True})
    e = base(tmp_path)
    out, _ = run_ticks(e, cfg(apply=True), 2)
    assert out["actions"]["proc:lane_relay"]["action"] == "done" and e.calls[0][2] == "lane_relay"
    lr = "tools/autopilot/lane_relay.py serve"
    two = ALL_UP + [P(30, lr), P(32, lr, created=NOW - 50)]
    out, _ = run_ticks(base(tmp_path, procs=two), cfg(), 2)
    assert "dup:lane_relay" in out["actions"]


def test_guard_dead_restarted_via_task(tmp_path):
    e = base(tmp_path, procs=RSP + TUN + [GUARDS[1]])
    out, _ = run_ticks(e, cfg(apply=True), 2)
    assert out["actions"]["proc:resident_guard"]["action"] == "done"
    assert ("run", ["schtasks", "/run", "/tn", "NS-Studio-ResidentSync-Guard"]) in e.calls


def test_monitor_and_api_down(tmp_path):
    e = base(tmp_path, http=lambda u: False)
    out, _ = run_ticks(e, cfg(apply=True), 2)
    assert {"http:monitor", "http:api"} <= set(out["actions"])
    assert any(c[0] == "run" and "restart_api.ps1" in " ".join(c[1]) and "-Revive" in c[1] for c in e.calls)


def test_empty_process_list_is_not_a_failure(tmp_path):
    e = base(tmp_path, procs=[])
    e._procs = []
    out = H.tick(e, cfg(apply=True), {}, save=False)
    assert "laptop_procs" in out["check_errors"] and not out["actions"]


# ---------------------------------------------------------------- 隧道
def test_tunnel_18290_dead_and_ignore_list(tmp_path):
    e = base(tmp_path, tcp=lambda p: p != 18290)
    out, _ = run_ticks(e, cfg(), 2)
    f = [x for x in out["findings"] if x["key"] == "tunnel:ports"]
    assert f and "gpu36-l2:18290" in f[0]["what"]
    out, _ = run_ticks(base(tmp_path, tcp=lambda p: p != 18290), cfg(ignore_tunnel_ports=[18290]), 2)
    assert not out["findings"]


def test_tunnel_supervisor_missing(tmp_path):
    e = base(tmp_path, procs=RSP + GUARDS)
    out, _ = run_ticks(e, cfg(apply=True), 2)
    assert out["actions"]["proc:tunnel_supervisor"]["action"] == "done"
    assert ("run", ["schtasks", "/run", "/tn", "NS-Studio-TunnelSupervisor"]) in e.calls


# ---------------------------------------------------------------- 服务器
def srv(tmp_path, g33=None, g36=None):
    at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - 30))
    ok = {"at": at, "producer_hb_age_min": 0.1, "night_state_age_min": 0.5, "lanes": {}}
    wj(tmp_path, "data/autopilot/resident_sync.json", {"gpu33": {"health": {**ok, **(g33 or {})}}, "gpu36": {"health": {**ok, **(g36 or {})}}})


def test_server_producer_dead_goes_through_restart_queue(tmp_path):
    srv(tmp_path, g33={"producer_hb_age_min": 20})
    e = base(tmp_path)
    out, _ = run_ticks(e, cfg(apply=True), 2)
    assert out["actions"]["srv:gpu33:producer"]["action"] == "done"
    assert e.calls == [("rq", "gpu33", "producer-only", True)]          # 死了 20 分钟 = 紧急；没有任何 ssh / kill
    e = base(tmp_path)
    e.pending = {"gpu33": [{"id": "x"}]}
    out, _ = run_ticks(e, cfg(apply=True), 2)
    assert out["actions"]["srv:gpu33:producer"]["action"] == "none" and not e.calls


def test_server_paused_producer_not_restarted_and_stale_health_untouched(tmp_path):
    srv(tmp_path, g33={"producer_hb_age_min": None, "producer_paused": True}, g36={"at": "2020-01-01 00:00:00"})
    e = base(tmp_path)
    out, _ = run_ticks(e, cfg(apply=True), 2)
    assert "srv:gpu33:producer" not in out["actions"]
    assert out["actions"]["srv:gpu36:health"]["action"] == "none" and not e.calls   # 判不了就不动服务器


def test_night_stale_and_vqa_guard(tmp_path):
    srv(tmp_path, g36={"night_state_age_min": 30})
    wj(tmp_path, "data/autopilot/vqa_guard.json", {"vqa:stuck": {"fails": 3, "last_error": "61 分钟没出结论"}, "vqa:health": {"fails": 0}})
    e = base(tmp_path)
    out, _ = run_ticks(e, cfg(apply=True), 2)
    assert ("rq", "gpu36", "night-only", False) in e.calls and "srv:vqa:vqa:stuck" in out["actions"]
    assert "srv:vqa:vqa:health" not in out["actions"]


# ---------------------------------------------------------------- GPU 空闲 + 有活
def test_gpu_idle_with_ready_work(tmp_path):
    lanes = {"0": {"util": 0, "queue": 0}, "1": {"util": 100, "queue": 1}, "2": {"util": 0, "queue": 0}}
    srv(tmp_path, g33={"lanes": lanes})
    wj(tmp_path, "data/producer/runs/r1/registry.json", {"counts": {"ready": 7}})
    e = base(tmp_path)
    st = {}
    H.tick(e, cfg(), st, save=False)
    e._now = NOW + 6 * 60
    srv_at = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW + 6 * 60 - 30))
    d = json.loads((tmp_path / "data/autopilot/resident_sync.json").read_text(encoding="utf-8"))
    for h in d.values():
        h["health"]["at"] = srv_at
    wj(tmp_path, "data/autopilot/resident_sync.json", d)
    H.tick(e, cfg(), st, save=False)
    out = H.tick(e, cfg(), st, save=False)
    f = [x for x in out["findings"] if x["key"] == "gpu:idle_with_work"]
    assert f and "gpu33:0" in f[0]["what"] and "gpu33:1" not in f[0]["what"] and "gpu33:2" not in f[0]["what"]   # gpu33:2 永不碰


def test_gpu_idle_ignores_held_and_no_work(tmp_path):
    srv(tmp_path, g33={"lanes": {"0": {"util": 0, "queue": 0}}})
    wj(tmp_path, "config/pipeline/night_control.json", {"hold_lanes": ["gpu33:0"]})
    wj(tmp_path, "data/producer/runs/r1/registry.json", {"counts": {"ready": 7}})
    e = base(tmp_path)
    st = {"idle": {"gpu33:0": NOW - 3600}}
    assert not [f for f in H.check_gpu_idle(e, cfg(), st, NOW, e.procs())]
    wj(tmp_path, "config/pipeline/night_control.json", {})
    wj(tmp_path, "data/producer/runs/r1/registry.json", {"counts": {"ready": 0}})
    assert not H.check_gpu_idle(e, cfg(), {"idle": {"gpu33:0": NOW - 3600}}, NOW, e.procs())


# ---------------------------------------------------------------- hold / 暂停 / 证据 / 版本
def test_stale_hold_without_expiry_reported_not_deleted(tmp_path):
    nc = tmp_path / "config/pipeline/night_control.json"
    wj(tmp_path, "config/pipeline/night_control.json", {"hold_lanes": ["gpu36:0"]})
    e = base(tmp_path)
    e.mt["night_control.json"] = NOW - 7 * 3600
    out, _ = run_ticks(e, cfg(), 2)
    assert "hold:stale" in out["actions"] and nc.exists()
    wj(tmp_path, "config/pipeline/night_control.json", {"hold_lanes": ["gpu36:0"], "hold_expires": {"gpu36:0": "2099-01-01T00:00:00"}})
    assert not [f for f in run_ticks(base(tmp_path), cfg(), 2)[0]["findings"] if f["key"] == "hold:stale"]


def test_pause_without_expiry_after_threshold(tmp_path):
    srv(tmp_path, g33={"producer_paused": True})
    e = base(tmp_path)
    st = {"paused_since": {"gpu33": NOW - 31 * 60}}
    f = H.check_holds(e, cfg(), st, NOW, e.procs())
    assert any(x["key"] == "pause:gpu33" for x in f)
    f = H.check_holds(e, cfg(), {"paused_since": {"gpu33": NOW - 5 * 60}}, NOW, e.procs())
    assert not any(x["key"] == "pause:gpu33" for x in f)


def test_stale_prompt_triggers_probe_and_cooldown_not_counted(tmp_path):
    e = base(tmp_path)
    e.stale = [(2, ["提示词: 证据过期"])]
    out, st = run_ticks(e, cfg(apply=True), 2)
    assert out["actions"]["prompt:r1:ep02"]["action"] == "done" and ("probe", "r1", 2) in e.calls
    e = base(tmp_path)
    e.stale, e.probe_ret = [(2, ["x"])], "cooldown"
    out, st = run_ticks(e, cfg(apply=True), 3)
    assert out["actions"]["prompt:r1:ep02"]["action"] == "cooldown" and not st["remedy"]["prompt:r1:ep02"]["tries"]


def test_deploy_newer_than_process_restarts(tmp_path):
    srv(tmp_path)
    d = tmp_path / "data/system_versions/deploy_sv-1.json"
    wj(tmp_path, "data/system_versions/deploy_sv-1.json", {})
    e = base(tmp_path)
    e.mt["deploy_sv-1.json"] = NOW - 600                       # 10 分钟前部署；进程 2 小时前起 = 旧代码
    af = [P(40, r"python tools/factory/autoflow_resident.py --interval 30")]
    e._procs = ALL_UP + af
    out, st = run_ticks(e, cfg(apply=True), 2)
    assert out["actions"]["deploy:resident_sync"]["action"] == "done"
    assert any("restart_resident_sync.ps1" in " ".join(c[1]) for c in e.calls if c[0] == "run")
    assert out["actions"]["deploy:autoflow"]["action"] == "done"
    assert (tmp_path / "data/master/health/want_restart_autoflow.json").exists()      # 自己不杀自己：写旗给 guard
    assert d.exists()


def test_o5_stale_prompt_probe_applies_with_global_apply_false(tmp_path):
    """FIX-ORCH O5：全局 apply=false 时 stale_prompt 的自动探针仍动手（apply_checks 分项放开）"""
    e = base(tmp_path)
    e.stale = [(3, ["提示词：还没有逐镜编译 + preflight 证据"])]
    out, _ = run_ticks(e, cfg(), 2)
    assert out["actions"]["prompt:r1:ep03"]["action"] == "done" and ("probe", "r1", 3) in e.calls
    e2 = base(tmp_path)
    e2.stale = [(3, ["提示词：证据过期"])]
    out, _ = run_ticks(e2, cfg(apply_checks={}), 2)                  # 分项没放开 = 只报（dry）
    assert out["actions"]["prompt:r1:ep03"]["action"] == "dry" and not e2.calls


def test_o5_deploy_stale_restarts_laptop_residents_once_per_30min_server_stays_dry(tmp_path):
    srv(tmp_path)
    d = json.loads((tmp_path / "data/autopilot/resident_sync.json").read_text(encoding="utf-8"))
    d["gpu36"]["last_restart"] = NOW - 7200
    wj(tmp_path, "data/autopilot/resident_sync.json", d)
    wj(tmp_path, "data/system_versions/deploy_sv-1.json", {})
    e = base(tmp_path)
    e.mt["deploy_sv-1.json"] = NOW - 600
    st = {}
    run_ticks(e, cfg(), 2, st)                                       # 全局 apply=false
    runs = [c for c in e.calls if c[0] == "run" and "restart_resident_sync.ps1" in " ".join(c[1])]
    assert len(runs) == 1 and not [c for c in e.calls if c[0] == "rq"]          # 笔记本常驻重启；服务器 rq 仍 dry
    for k in range(1, 6):                                            # 25 分钟内仍旧代码（进程没换）：不再重启
        e._now = NOW + k * 300
        H.tick(e, cfg(), st, save=False)
    assert len([c for c in e.calls if c[0] == "run" and "restart_resident_sync.ps1" in " ".join(c[1])]) == 1
    e._now = NOW + 1900
    H.tick(e, cfg(), st, save=False)
    assert len([c for c in e.calls if c[0] == "run" and "restart_resident_sync.ps1" in " ".join(c[1])]) == 2


def test_o5_repo_config_applies_only_two_checks():
    c = H.load_cfg(ROOT / "config/master/health_tick.json")
    assert c["apply"] is False and set(c["apply_checks"]) == {"stale_prompt", "deploy_stale"}
    assert "rq_restart" not in c["apply_checks"]["deploy_stale"] and c["min_gap_s"]["deploy_stale"] == 1800


def test_deploy_check_waits_for_release_lock_and_grace(tmp_path):
    srv(tmp_path)
    wj(tmp_path, "data/system_versions/deploy_sv-1.json", {})
    wj(tmp_path, "data/system_versions/cut_lock.json", {"active": True, "expires_t": NOW + 600, "sv": "S"})
    e = base(tmp_path)
    e.mt["deploy_sv-1.json"] = NOW - 600
    assert not [f for f in H.check_deploy_stale(e, cfg(), {}, NOW, e.procs()) if f["check"] == "deploy_stale"]
    wj(tmp_path, "data/system_versions/cut_lock.json", {})
    e.mt["deploy_sv-1.json"] = NOW - 60                       # 刚部署（< grace）：不判
    assert not H.check_deploy_stale(e, cfg(), {}, NOW, e.procs())


def test_server_deploy_stale_non_urgent_and_dedup(tmp_path):
    srv(tmp_path)
    d = json.loads((tmp_path / "data/autopilot/resident_sync.json").read_text(encoding="utf-8"))
    d["gpu36"]["last_restart"] = NOW - 7200
    wj(tmp_path, "data/autopilot/resident_sync.json", d)
    wj(tmp_path, "data/system_versions/deploy_sv-1.json", {})
    e = base(tmp_path)
    e.mt["deploy_sv-1.json"] = NOW - 600
    out, _ = run_ticks(e, cfg(apply=True), 2)
    assert ("rq", "gpu36", "all", False) in e.calls


# ---------------------------------------------------------------- 退避 / 熔断 / 报告
def test_backoff_then_breaker_reports_error_and_stops_restarting(tmp_path):
    e = base(tmp_path, procs=GUARDS + TUN)
    c = cfg(apply=True, max_restarts_per_hour=3)
    st = {}
    acts = []
    for i in range(12):
        e._now = NOW + i * 70
        out = H.tick(e, c, st, save=False)
        acts.append(out["actions"].get("proc:resident_sync", {}).get("action"))
    assert "backoff" in acts and "breaker" in acts
    assert sum(1 for c_ in e.calls if c_[0] == "spawn") == 3         # 熔断前最多 3 次
    assert any(l == "ERROR" and "熔断" in t for l, t in e.chan)
    assert any("【熔断】" in w and b for _, w, b in e.issues)       # P0 阻断


def test_failed_remedy_counts_and_reports(tmp_path):
    e = base(tmp_path, procs=GUARDS + TUN)
    e.run_ok = False
    out, st = run_ticks(e, cfg(apply=True), 2)
    assert out["actions"]["proc:resident_sync"]["action"] == "failed" and st["remedy"]["proc:resident_sync"]["last"]["ok"] is False


def test_report_failure_goes_to_unreported_not_silent(tmp_path):
    e = base(tmp_path, procs=GUARDS + TUN)
    e.report_exc = UnicodeDecodeError("utf-8", b"\xff", 0, 1, "bad")
    run_ticks(e, cfg(), 2)
    assert (tmp_path / "data/master/health/unreported.jsonl").read_text(encoding="utf-8").strip()
    assert e.chan                                                    # CHANNEL 行仍写


def test_report_repeats_only_after_window_and_recovery_line(tmp_path):
    e = base(tmp_path, procs=GUARDS + TUN)
    st = {}
    for i in range(6):
        e._now = NOW + i * 45
        H.tick(e, cfg(), st, save=False)
    assert len([1 for _, t in e.chan if "proc:resident_sync" in t and "已恢复" not in t]) == 1       # 不刷屏
    e._procs = ALL_UP
    out = H.tick(e, cfg(), st, save=False)
    assert "proc:resident_sync" in out["resolved"] and any("已恢复" in t for _, t in e.chan)


def test_check_exception_isolated_and_reported(tmp_path):
    e = base(tmp_path)
    boom = lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom"))   # noqa: E731
    e.stale_prompt_eps = boom
    out, _ = run_ticks(e, cfg(), 2)
    assert "stale_prompt" in out["check_errors"] and "check_error:stale_prompt" in out["actions"]
    assert any("boom" in w for _, w, _ in e.issues)


def test_state_files_written(tmp_path):
    e = base(tmp_path, procs=GUARDS + TUN)
    H.tick(e, cfg(), {}, save=True)
    hb = json.loads((tmp_path / "data/master/health/health.json").read_text(encoding="utf-8"))
    assert hb["apply"] is False and hb["findings"]
    assert (tmp_path / "data/master/health/state.json").exists()


def test_config_file_default_is_dry_and_load_merges():
    c = H.load_cfg(ROOT / "config/master/health_tick.json")
    assert c["apply"] is False and c["max_restarts_per_hour"] == 3 and c["checks"]["tunnels"] is True
    assert H.load_cfg(Path("/nope"))["every_s"] == 45


def test_thread_loop_survives_exceptions_and_logs():
    import threading
    n, logs, stop = [0], [], threading.Event()

    def tk():
        n[0] += 1
        if n[0] == 1:
            raise RuntimeError("x")
        stop.set()
        return {"findings": [1], "actions": {"a": {}}, "resolved": []}
    H.thread_loop(stop=stop, log=logs.append, tick_fn=tk, sleep=lambda s: None)
    assert n[0] == 2 and any("异常" in l for l in logs) and any("1 项异常" in l for l in logs)


# ---------------------------------------------------------------- 接线：autoflow 线程 / report_issue 坏字节 / guard 脚本
def test_autoflow_starts_health_thread_and_survives_load_failure():
    spec2 = importlib.util.spec_from_file_location("af_t", ROOT / "tools/factory/autoflow_resident.py")
    af = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(af)
    started = []

    class T:
        def __init__(self, **kw): self.kw = kw
        def start(self): started.append(self.kw["target"])
    mod = type("M", (), {"thread_loop": staticmethod(lambda **k: None)})
    assert af.health_start(loader=lambda n, r: mod, spawn=T) is not None and started
    def bad(n, r): raise ImportError("x")
    assert af.health_start(loader=bad, spawn=T) is None


def test_report_issue_survives_corrupt_live_bytes(tmp_path):
    spec3 = importlib.util.spec_from_file_location("ri_t", ROOT / "tools/master/report_issue.py")
    ri = importlib.util.module_from_spec(spec3)
    spec3.loader.exec_module(ri)
    live = tmp_path / "V2_LIVE.md"
    live.write_bytes("# live\nold\n".encode() + b"\xff\xfe tail\n")
    ri._insert_live("new line", live)
    b = live.read_bytes()
    assert b"new line" in b and b.endswith(b"\xff\xfe tail\n")         # 坏字节原样保留，不崩不丢


def test_guard_scripts_peer_and_health_hooks():
    rg = (ROOT / "ops/autostart/resident_guard.ps1").read_text(encoding="utf-8-sig")
    mg = (ROOT / "ops/autostart/monitor_guard.ps1").read_text(encoding="utf-8-sig")
    assert "Start-ScheduledTask -TaskName \"NS-Studio-Monitor-Guard\"" in rg and "PeerGuard" in rg.split("while ($true) {", 1)[1]
    assert "Start-ScheduledTask -TaskName \"NS-Studio-ResidentSync-Guard\"" in mg and "PeerGuard" in mg.split("while ($true) {", 1)[1]
    assert r"data\master\health\health.json" in rg and "want_restart_autoflow.json" in rg and "Move-Item" in rg and "Remove-Item" not in rg.split("function AutoflowWanted", 1)[1].split("Log \"守护启动", 1)[0]
    for f in ("register_resident_guard.ps1", "register_monitor_guard.ps1"):
        assert "-RepetitionInterval (New-TimeSpan -Minutes 5)" in (ROOT / "ops/autostart" / f).read_text(encoding="utf-8-sig")
