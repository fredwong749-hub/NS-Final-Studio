"""L-202 ②：tools/autopilot/idle_watch.py 空卡巡检——空闲判定、有活门控、动作节流、dry-run、永不碰 gpu33:2、常驻线程挂接（全 fake，不碰网络 / 服务器）。"""
import importlib.util
import json
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sys.modules[name] = m
    sp.loader.exec_module(m)
    return m


IW = _load("idle_watch_t", "tools/autopilot/idle_watch.py")
NOW = 1_800_000_000.0
LANES = {"gpu33:0": {"host": "gpu33", "gpu": 0, "comfy_port": 8188, "tunnel_port": 18188},
         "gpu33:1": {"host": "gpu33", "gpu": 1, "comfy_port": 8189, "tunnel_port": 18189},
         "gpu33:3": {"host": "gpu33", "gpu": 3, "comfy_port": 8191, "tunnel_port": 18191},
         "gpu36:0": {"host": "gpu36", "gpu": 0, "comfy_port": 8188, "tunnel_port": 18288},
         "gpu36:1": {"host": "gpu36", "gpu": 1, "comfy_port": 8189, "tunnel_port": 18289},
         "gpu36:2": {"host": "gpu36", "gpu": 2, "comfy_port": 8190, "tunnel_port": 18290}}


def probe(util=0, queue=0, hb_age_s=10, paused=False, night_age_s=30, video=0, ctrl=None, nctrl=None):
    gpus = {str(i): {"util": util, "mem": 1000} for i in range(4)}
    return {"now": NOW, "gpus": gpus, "queues": {str(i): queue for i in range(4)},
            "hb": {"t": NOW - hb_age_s, "paused": paused, "inflight": 0}, "ctrl": ctrl or {}, "nctrl": nctrl or {},
            "night_state_age_s": night_age_s, "video_dispatchable_n": video, "video_dispatchable": []}


def registry(ready=0, running=0):
    shots = []
    for i in range(ready):
        shots.append({"shot": f"ep02-S{i + 1}", "objects": {"first": {"status": "ready"}}})
    for i in range(running):
        shots.append({"shot": f"ep01-S{i + 1}", "objects": {"first": {"status": "passed"}, "last": {"status": "running", "where": "gpu33:0"}}})
    return {"counts": {"ready": ready}, "episodes": [{"ep": 2, "shots": shots}]}


class FakeEnv(IW.Env):
    def __init__(self, root, probes=None, tq=None, reg=None, assets=0, now=NOW):
        super().__init__(root)
        self.probes = probes if probes is not None else {"gpu33": probe(), "gpu36": probe()}
        self.tq, self.assets, self._now = tq or {}, assets, now
        self.calls, self.issues, self.chan, self.pending, self.state = [], [], [], {}, {}
        self.sop = {}
        (self.root / "data/producer/runs/runx").mkdir(parents=True, exist_ok=True)
        (self.root / "data/producer/runs/runx/registry.json").write_text(json.dumps(reg or registry()), encoding="utf-8")

    def now(self): return self._now
    def lanes(self): return dict(LANES)
    def primary_run(self): return "runx"
    def producer_rel(self, run): return "data/producer/runs/runx"
    def probe_host(self, host, run, lanes, timeout): return self.probes.get(host)
    def tunnel_queue(self, port, timeout): return self.tq.get(port)
    def remote(self, host, cmd, timeout): self.calls.append(("remote", host, cmd)); return 0, "ok"
    def night_once_cmd(self, host, run): return f"night --once {host} {run}"
    def rq_pending(self, host): return self.pending.get(host, [])
    def rq_request(self, host, reason, mode, urgent): self.calls.append(("rq", host, mode, urgent)); return {"id": "rq1"}
    def asset_pending(self, run): return self.assets
    def episode_lock(self): return None
    def sop_blocks(self, run, eps): return dict(self.sop)
    def hold_alive(self, expires_at, since): return (False, "过期") if expires_at == "dead" else (True, "")
    def report(self, run, what, fix_hint, blocking): self.issues.append((what, blocking)); return f"ISS-{len(self.issues)}"
    def channel(self, text, now): self.chan.append(text)
    def read_state(self): return self.state


def cfg(**kw):
    c = {**IW.DEFAULT_CFG, "actions": dict(IW.DEFAULT_CFG["actions"])}
    c.update(kw)
    return c


def run_ticks(env, c, minutes):
    """同一份 state 连续拍：先 0 分钟（起算），再推进 minutes 分钟"""
    st = {}
    r0 = IW.tick(env, c, st, save=False)
    env._now = NOW + minutes * 60
    for p in env.probes.values():
        if p:
            p["now"] = env._now
            p["hb"]["t"] = env._now - 10
    return r0, IW.tick(env, c, st, save=False), st


# ---------------------------------------------------------------- 空闲判定
def test_idle_detection_util_and_queue(tmp_path):
    env = FakeEnv(tmp_path, probes={"gpu33": probe(util=0, queue=0), "gpu36": probe(util=80, queue=0)}, tq={18188: 0, 18189: 3})
    r = IW.tick(env, cfg(), {}, save=False)
    L = r["lanes"]
    assert L["gpu33:0"]["idle"] is True and L["gpu33:0"]["queue_src"] == "tunnel"
    assert L["gpu33:1"]["idle"] is False and L["gpu33:1"]["queue"] == 3          # 隧道队列有单 = 忙
    assert L["gpu33:3"]["idle"] is True and L["gpu33:3"]["queue_src"] == "server"  # 隧道探不到 → 退回服务器本机队列
    assert all(L[ln]["idle"] is False for ln in ("gpu36:0", "gpu36:1", "gpu36:2"))  # util 80 = 忙
    assert "gpu33:2" not in L


def test_probe_failure_is_unknown_not_idle(tmp_path):
    env = FakeEnv(tmp_path, probes={"gpu33": None, "gpu36": probe()}, reg=registry(ready=5))
    c = cfg()
    _r0, r1, _st = run_ticks(env, c, 10)
    assert all(r1["lanes"][ln]["idle"] is None and r1["lanes"][ln]["idle_min"] == 0 for ln in ("gpu33:0", "gpu33:1", "gpu33:3"))
    assert r1["probe_errors"] == ["gpu33"]
    assert not any(a["host"] == "gpu33" for a in r1["actions"])          # 探不到 = 不判，不凭空报 gpu33


# ---------------------------------------------------------------- 有活门控 + 空闲时长
def test_idle_without_work_no_action(tmp_path):
    env = FakeEnv(tmp_path, reg=registry(ready=0), assets=0)
    _r0, r1, _st = run_ticks(env, cfg(), 30)
    assert r1["has_work"] is False and r1["actions"] == [] and env.issues == [] and env.calls == []
    assert r1["lanes"]["gpu33:0"]["idle_min"] == 30.0                    # 空闲照记，只是不动作


def test_idle_with_work_reports_after_idle_min(tmp_path):
    env = FakeEnv(tmp_path, reg=registry(ready=4), probes={"gpu33": probe(ctrl={"only": ["__none__"], "hold_lanes": ["gpu33:0", "laptop:0"]}),
                                                           "gpu36": probe(nctrl={"hold_lanes": ["gpu36:1"], "hold_expires": {"gpu36:1": "dead"}})})
    c = cfg(idle_min=5)
    r0, r1, _st = run_ticks(env, c, 6)
    assert r0["actions"] == []                                             # 第一拍刚起算
    kinds = sorted((a["kind"], a["host"]) for a in r1["actions"])
    assert kinds == [("report", "gpu33"), ("report", "gpu36")]
    what33 = next(a["what"] for a in r1["actions"] if a["host"] == "gpu33")
    assert "only=__none__" in what33 and "hold_lanes ['gpu33:0']" in what33 and "ready 首尾帧 4" in what33
    what36 = next(a["what"] for a in r1["actions"] if a["host"] == "gpu36")
    assert "已过期" in what36 and "gpu36:1" in what36
    assert len(env.issues) == 2 and len(env.chan) == 2 and env.chan[0].startswith("🔴")


def test_assets_pending_counts_as_work(tmp_path):
    env = FakeEnv(tmp_path, reg=registry(ready=0), assets=2)
    _r0, r1, _st = run_ticks(env, cfg(), 6)
    assert r1["has_work"] and [a["kind"] for a in r1["actions"]] == ["report", "report"]


def test_video_work_triggers_night_once_only_on_that_host(tmp_path):
    env = FakeEnv(tmp_path, reg=registry(ready=0), probes={"gpu33": probe(video=2), "gpu36": probe(video=0)})
    _r0, r1, _st = run_ticks(env, cfg(), 6)
    acts = {(a["kind"], a["host"]) for a in r1["actions"]}
    assert ("night_once", "gpu33") in acts and ("night_once", "gpu36") not in acts
    assert ("remote", "gpu33", "night --once gpu33 runx") in env.calls
    assert not any(c[0] == "rq" for c in env.calls)                        # 心跳新鲜：不请求重启、不起 producer once


# ---------------------------------------------------------------- 节流
def test_action_throttling(tmp_path):
    env = FakeEnv(tmp_path, reg=registry(ready=3), probes={"gpu33": probe(video=1), "gpu36": probe()})
    c = cfg(act_gap_s=600, report_repeat_min=60)
    _r0, r1, st = run_ticks(env, c, 6)
    assert {a["kind"] for a in r1["actions"] if a["host"] == "gpu33"} == {"night_once", "report"}
    n_remote, n_issue = len([x for x in env.calls if x[0] == "remote"]), len(env.issues)
    env._now = NOW + 8 * 60                                                 # 2 分钟后再拍：都在节流期内
    r2 = IW.tick(env, c, st, save=False)
    assert r2["actions"] == [] and len(env.issues) == n_issue and len([x for x in env.calls if x[0] == "remote"]) == n_remote
    env._now = NOW + 17 * 60                                                # night_once 过了 600 s，卡点还没到 60 分钟
    r3 = IW.tick(env, c, st, save=False)
    assert [a["kind"] for a in r3["actions"]] == ["night_once"] and len(env.issues) == n_issue


def advance(env, fresh=("gpu36",)):
    """探针跟着时钟走：fresh 里的机器 producer 心跳保持新鲜，其它机器的心跳按原样变老"""
    for h, p in env.probes.items():
        p["now"] = env._now
        if h in fresh:
            p["hb"]["t"] = env._now - 10


def test_restart_request_when_heartbeat_stale_once_per_30min(tmp_path):
    env = FakeEnv(tmp_path, reg=registry(ready=3), probes={"gpu33": probe(hb_age_s=20 * 60), "gpu36": probe(video=1, night_age_s=40 * 60)})
    c = cfg()
    st = {}
    IW.tick(env, c, st, save=False)
    env._now = NOW + 6 * 60
    advance(env)
    r1 = IW.tick(env, c, st, save=False)
    rq = sorted((a["host"], a["mode"], a["urgent"]) for a in r1["actions"] if a["kind"] == "restart_request")
    assert rq == [("gpu33", "producer-only", True), ("gpu36", "night-only", True)]
    assert ("rq", "gpu33", "producer-only", True) in env.calls and ("rq", "gpu36", "night-only", True) in env.calls
    assert not any(a["kind"] == "night_once" for a in r1["actions"])      # night 心跳过期：不去 --once，走重启
    env._now = NOW + 20 * 60
    advance(env)
    r2 = IW.tick(env, c, st, save=False)
    assert not any(a["kind"] == "restart_request" for a in r2["actions"])  # 30 分钟内不再请求
    env._now = NOW + 40 * 60
    advance(env)
    env.pending["gpu33"] = [{"id": "x"}]
    r3 = IW.tick(env, c, st, save=False)
    gpu33 = [a for a in r3["actions"] if a["kind"] == "restart_request" and a["host"] == "gpu33"]
    assert gpu33 and "不重复" in gpu33[0]["result"]                          # 已有待办请求：不重复发


def test_paused_producer_not_restarted(tmp_path):
    env = FakeEnv(tmp_path, reg=registry(ready=3), probes={"gpu33": probe(hb_age_s=20 * 60, paused=True), "gpu36": probe()})
    _r0, r1, _st = run_ticks(env, cfg(), 6)
    assert not any(a["kind"] == "restart_request" for a in r1["actions"])
    assert any("paused" in a["what"] for a in r1["actions"] if a["kind"] == "report" and a["host"] == "gpu33")


# ---------------------------------------------------------------- dry-run / 永不碰 gpu33:2
def test_dry_run_decides_but_does_not_act(tmp_path):
    env = FakeEnv(tmp_path, reg=registry(ready=3), probes={"gpu33": probe(video=1, hb_age_s=3600), "gpu36": probe()})
    c = cfg()
    st = {}
    IW.tick(env, c, st, dry=True, save=False)
    env._now = NOW + 6 * 60
    r1 = IW.tick(env, c, st, dry=True, save=False)
    assert {a["kind"] for a in r1["actions"]} == {"night_once", "restart_request", "report"}
    assert all("dry-run" in a["result"] for a in r1["actions"]) and env.calls == [] and env.issues == [] and env.chan == []
    assert st["last_act"] == {} and st["reported"] == {}                    # dry 不消耗节流窗口


def test_never_gpu33_2_lane_table_and_commands(tmp_path):
    H = _load("hosts_t_iw", "tools/factory/hosts.py")
    assert "gpu33:2" not in IW.lane_table(H)                                  # 真实 hosts.json
    d = json.loads(json.dumps(H.load()))
    d["hosts"]["gpu33"]["lanes"]["gpu33:2"] = {"gpu": 2, "comfy_port": 8190, "tunnel_port": 18190, "roles": ["image"], "enabled": True}
    d["hosts"]["gpu33"]["broken_gpus"] = []                                   # 就算有人把坏卡写回启用表
    assert "gpu33:2" not in IW.lane_table(H, d)
    env = FakeEnv(tmp_path)
    st = {"last_act": {}, "reported": {}}
    bad = [{"kind": "night_once", "key": "k", "host": "gpu33", "why": "hold gpu33:2"}, {"kind": "night_once", "key": "k2", "host": "laptop", "why": "x"}]
    out = IW.execute(env, cfg(), st, bad, NOW, "runx", dry=False)
    assert all("拒绝" in r["result"] for r in out) and env.calls == []


def test_status_and_events_written(tmp_path):
    env = FakeEnv(tmp_path, reg=registry(ready=1))
    r = IW.tick(env, cfg(), {}, save=True)
    sp = tmp_path / "data/pipeline/idle_watch/status.json"
    assert json.loads(sp.read_text(encoding="utf-8"))["run"] == "runx" and r["lanes"]["gpu36:2"]["idle"] is True
    assert (tmp_path / "data/pipeline/idle_watch/events.log").read_text(encoding="utf-8").count("\n") == 1


# ---------------------------------------------------------------- 常驻线程
def test_thread_loop_respects_enabled_and_never_exits_on_error():
    calls, sleeps, stop = [], [], threading.Event()
    cfgs = iter([{"enabled": False, "interval_s": 60}, {"enabled": True, "interval_s": 60}, {"enabled": True, "interval_s": 60}])

    def tick_fn(cfg=None):
        calls.append(cfg)
        if len(calls) == 1:
            raise RuntimeError("boom")
        return {"actions": [{"kind": "report", "host": "gpu33"}]}

    def sleep(s):
        sleeps.append(s)
        if len(sleeps) == 3:
            stop.set()
    logs = []
    IW.thread_loop(stop=stop, log=logs.append, tick_fn=tick_fn, sleep=sleep, cfg_fn=lambda: next(cfgs))
    assert len(calls) == 2 and len(sleeps) == 3 and all(s >= 5 for s in sleeps)
    assert any("异常" in m for m in logs) and any("report:gpu33" in m for m in logs)


def test_autoflow_resident_hook(tmp_path):
    AR = _load("autoflow_resident_t_iw", "tools/factory/autoflow_resident.py")
    spawned = []

    class T:
        def __init__(self, target=None, kwargs=None, name=None, daemon=None):
            spawned.append((target, name, daemon))

        def start(self): pass

    class Mod:
        def __init__(self, enabled): self.enabled = enabled
        def load_cfg(self): return {"enabled": self.enabled}
        def thread_loop(self, **kw): pass
    assert AR.idle_watch_start(loader=lambda n, rel: Mod(False), spawn=T) is None and spawned == []
    t = AR.idle_watch_start(loader=lambda n, rel: Mod(True), spawn=T)
    assert t is not None and spawned[0][1] == "idle_watch" and spawned[0][2] is True
    assert AR.idle_watch_start(loader=lambda n, rel: (_ for _ in ()).throw(ImportError("x")), spawn=T) is None
