"""tools/master/episode_run.py 单测：全部 mock（无 SSH、无子进程、无真实卡点登记）。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("episode_run", ROOT / "tools/master/episode_run.py")
ER = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ER)


class FakeEnv(ER.Env):
    def __init__(self, tmp: Path, **kw):
        super().__init__("r1", 1, root=tmp, **kw)
        self.t = 1_800_000_000.0
        self.now = lambda: self.t
        self.sleeps = []
        self.sleep = lambda s: (self.sleeps.append(s), setattr(self, "t", self.t + s))
        self.remote_log, self.local_log, self.issues = [], [], []
        self.remote_fn = lambda host, cmd: (1, b"", "no fake")
        self.local_fn = lambda args: (0, "", "")

    def root_of(self, host):
        return "/srv/repo"

    def py_of(self, host):
        return "/srv/venv/bin/python"

    def remote(self, host, cmd, timeout=120, tries=2, input=None):
        self.remote_log.append((host, cmd))
        return self.remote_fn(host, cmd)

    def local(self, args, timeout=600):
        self.local_log.append(args)
        return self.local_fn(args)

    def report_issue(self, step, what, blocking, fix_hint):
        self.issues.append((step, what, blocking, fix_hint))
        return f"ISS-{len(self.issues)}"


def args(**kw):
    d = dict(p4=None, compare_to=None, watch=False, interval=30, kick_night=False)
    d.update(kw)
    return SimpleNamespace(**d)


def write_p4(tmp: Path, name="P4_ep01.A.md", text="x"):
    d = tmp / "data/pipeline/runs/r1/staging"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(text, encoding="utf-8")
    return d / name


def write_script(tmp: Path, n=2):
    p = tmp / "data/import/runs/r1/script_v2.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"episodes": [{"number": 1, "shots": [{}] * n}]}), encoding="utf-8")
    return p


def snap(shots, **kw):
    d = {"shots": [{"shot": k, "first": v, "why": ""} for k, v in shots.items()], "paused": False, "hold_lanes": [], "pause_hold": [],
         "runaway_hold": [], "heartbeat": "2026-11-05T10:00:00", "server_now": "2026-11-05T10:01:00"}
    d.update(kw)
    return (0, (json.dumps(d) + "\n").encode(), "")


def test_import_detect_done_and_todo(tmp_path):
    env = FakeEnv(tmp_path)
    p4 = write_p4(tmp_path)
    write_script(tmp_path)
    st = {"import": {}, "regen": {}, "blockers": {}, "stage_started": {}}
    r = ER.check_import(env, st, args())
    assert r["status"] == "todo" and "import-staged" in r["plan"]
    st["import"] = {"sha": ER.sha256_file(p4)}
    assert ER.check_import(env, st, args())["status"] == "done"
    p4.write_text("changed", encoding="utf-8")                 # 稿变了 → 要重导
    assert ER.check_import(env, st, args())["status"] == "todo"


def test_latest_p4_picks_newest(tmp_path):
    env = FakeEnv(tmp_path)
    a = write_p4(tmp_path, "P4_ep01.A.md")
    b = write_p4(tmp_path, "P4_ep01.B.md")
    import os
    os.utime(a, (1, 1))
    assert ER.latest_p4(env).name == "P4_ep01.B.md"


def test_act_import_failure_is_blocked_and_state_untouched(tmp_path):
    env = FakeEnv(tmp_path)
    p4 = write_p4(tmp_path)
    env.local_fn = lambda a: (1, "", "rubric gate fail")
    st = {"import": {}, "regen": {}, "blockers": {}, "stage_started": {}}
    res = ER.check_import(env, st, args())
    r = ER.act_import(env, st, args(), res)
    assert r["status"] == "blocked" and not st["import"]
    assert "import-staged" in env.local_log[0] and "--run" in env.local_log[0]
    assert p4.name in " ".join(env.local_log[0])


def test_first_stage_done_wait_owner_blocked(tmp_path):
    env = FakeEnv(tmp_path)
    st = {}
    env.remote_fn = lambda h, c: snap({"s1": "passed", "s2": "passed"})
    assert ER.check_first(env, st, args())["status"] == "done"
    env.remote_fn = lambda h, c: snap({"s1": "passed", "s2": "running"})
    assert ER.check_first(env, st, args())["status"] == "wait"
    env.remote_fn = lambda h, c: snap({"s1": "passed", "s2": "best_effort"})
    r = ER.check_first(env, st, args())
    assert r["status"] == "owner" and r["shots"] == ["s2"] and "queue" in r["link"]
    env.remote_fn = lambda h, c: snap({"s1": "passed", "s2": "ready"}, pause_hold=[{"shot": "s2", "expires_at": "2026-11-05T12:00:00"}])
    r = ER.check_first(env, st, args())
    assert r["status"] == "blocked" and "pause_shots" in r["msg"]
    # 已过期的暂停不算
    env.remote_fn = lambda h, c: snap({"s1": "passed", "s2": "ready"}, pause_hold=[{"shot": "s2", "expires_at": "2026-11-05T09:00:00"}])
    assert ER.check_first(env, st, args())["status"] == "wait"
    # 心跳停
    env.remote_fn = lambda h, c: snap({"s2": "ready"}, heartbeat="2026-11-05T08:00:00")
    assert ER.check_first(env, st, args())["status"] == "blocked"


def test_hold_lanes_all_held_blocks(tmp_path):
    env = FakeEnv(tmp_path)
    hosts = tmp_path / "config/factory/hosts.json"
    hosts.parent.mkdir(parents=True)
    hosts.write_text(json.dumps({"hosts": {"gpu33": {"lanes": {"gpu33:0": {"roles": ["image"]}, "gpu33:1": {"roles": ["image"]}}}}}), encoding="utf-8")
    env.remote_fn = lambda h, c: snap({"s": "ready"}, hold_lanes=["gpu33:0", "gpu33:1"])
    r = ER.check_first(env, {}, args())
    assert r["status"] == "blocked" and "hold_lanes" in r["msg"]
    env.remote_fn = lambda h, c: snap({"s": "ready"}, hold_lanes=["gpu33:0"])
    assert ER.check_first(env, {}, args())["status"] == "wait"        # 只封一部分 → 照常等


def vsnap(shots, night, age=10, size=None):
    return 0, (json.dumps({"night": night, "night_age_s": age, "shots": shots, "final_size": size}) + "\n").encode(), ""


def test_video_and_finalize(tmp_path):
    env = FakeEnv(tmp_path)
    write_script(tmp_path, n=2)
    env.remote_fn = lambda h, c: vsnap({"a": "done"}, {"status": "rendering"})
    assert "1/2" in ER.check_video(env, {}, args())["msg"] and ER.check_video(env, {}, args())["status"] == "wait"
    env.remote_fn = lambda h, c: vsnap({"a": "done", "b": "rendering"}, {"status": "rendering"})
    assert ER.check_video(env, {}, args())["status"] == "wait"
    env.remote_fn = lambda h, c: vsnap({"a": "done", "b": "best_effort"}, {"status": "rendering"})
    assert ER.check_video(env, {}, args())["status"] == "done"
    env.remote_fn = lambda h, c: vsnap({"a": "done", "b": "rendering"}, {"status": "rendering"}, age=2000)
    assert ER.check_video(env, {}, args())["status"] == "blocked"
    env.remote_fn = lambda h, c: vsnap({"a": "done", "b": "done"}, {"status": "assembled", "final": "data/episodes/r1/ep01_v7.mp4", "assembled_n": 7}, size=99)
    r = ER.check_finalize(env, {}, args())
    assert r["status"] == "done" and r["final_size"] == 99
    env.remote_fn = lambda h, c: vsnap({"a": "done", "b": "done"}, {"status": "assemble_failed", "assemble_err": "boom"})
    r = ER.check_finalize(env, {}, args())
    assert r["status"] == "blocked" and "boom" in r["msg"]


def test_regen_waits_for_sync_then_todo_then_done(tmp_path):
    env = FakeEnv(tmp_path)
    s = write_script(tmp_path)
    st = {"import": {"sha": "abc"}, "regen": {}}
    env.remote_fn = lambda h, c: (0, b"deadbeef  data/import/runs/r1/script_v2.json\n", "")
    assert ER.check_regen(env, st, args())["status"] == "wait"
    sha = ER.sha256_file(s)
    env.remote_fn = lambda h, c: (0, (sha + "  x\n").encode(), "")
    r = ER.check_regen(env, st, args())
    assert r["status"] == "todo" and "regen" in r["plan"]
    r = ER.act_regen(env, st, args(), r)
    assert r["status"] == "done" and st["regen"]["sha"] == "abc"
    assert "OFFLINE_SELF=gpu33" in env.remote_log[-1][1] and "regen" in env.remote_log[-1][1]
    assert ER.check_regen(env, st, args())["status"] == "done"       # 幂等：不再重复下达


def test_pull_idempotent_and_size_check(tmp_path):
    env = FakeEnv(tmp_path)
    st = {"final": {"path": "/srv/repo/data/episodes/r1/ep01_v7.mp4", "size": 4}}
    assert ER.check_pull(env, st, args())["status"] == "todo"
    loc = tmp_path / "data/episodes/r1/ep01_v7.mp4"
    loc.parent.mkdir(parents=True)
    loc.write_bytes(b"12")                                              # 大小不对 → 还要拉
    assert ER.check_pull(env, st, args())["status"] == "todo"
    loc.write_bytes(b"1234")
    assert ER.check_pull(env, st, args())["status"] == "done"
    loc.unlink()
    env.sftp_pull = lambda host, remote, part: False                    # hk 不通 → 退回 cat
    env.remote_fn = lambda h, c: (0, b"1234", "") if c.startswith("cat") and c.endswith(".mp4") else (1, b"", "")
    r = ER.act_pull(env, st, args(), {})
    assert r["status"] == "done" and loc.read_bytes() == b"1234" and not loc.with_name(loc.name + ".part").exists()


def test_compare_page_generated_and_idempotent(tmp_path):
    env = FakeEnv(tmp_path)
    d = tmp_path / "data/episodes/r1"
    d.mkdir(parents=True)
    (d / "ep01_v3.mp4").write_bytes(b"a")
    new = d / "ep01_v7.mp4"
    new.write_bytes(b"b")
    import os
    os.utime(d / "ep01_v3.mp4", (1, 1))
    st = {"pulled": {"local": str(new)}}
    assert ER.check_compare(env, st, args())["status"] == "todo"
    r = ER.act_compare(env, st, args(), {})
    html = (tmp_path / "data/review_pages/r1_ep01_compare/index.html").read_text(encoding="utf-8")
    assert "ep01_v3.mp4" in html and "ep01_v7.mp4" in html and r["status"] == "done"
    assert ER.check_compare(env, st, args())["status"] == "done"


def test_orchestrate_stops_on_blocker_registers_once(tmp_path):
    env = FakeEnv(tmp_path)
    write_p4(tmp_path)
    write_script(tmp_path)
    p4sha = ER.sha256_file(tmp_path / "data/pipeline/runs/r1/staging/P4_ep01.A.md")
    ER.save_state(env, {"stage_started": {}, "blockers": {}, "import": {"sha": p4sha}, "regen": {"sha": "x"}})
    env.local_fn = lambda a: (0, json.dumps({"ready": True, "shots": []}), "")
    shaw = ER.sha256_file(import_p := tmp_path / "data/import/runs/r1/script_v2.json")
    env.remote_fn = lambda h, c: (0, (shaw + " x\n").encode(), "") if "sha256sum" in c else snap({"s": "ready"}, pause_hold=[{"shot": "s"}])
    rep = ER.orchestrate(env, args(), ER.STAGES)
    assert rep["status"] == "blocked" and rep["stopped_at"] == "first" and rep["exit"] == 2
    assert len(env.issues) == 1 and env.issues[0][2] is True
    rep = ER.orchestrate(env, args(), ER.STAGES)                        # 同一原因不重复登记
    assert len(env.issues) == 1


def test_stage_timeout_registers_blocker(tmp_path):
    env = FakeEnv(tmp_path)
    ER.save_state(env, {"stage_started": {"first": ER.now_iso(env.t - ER.TIMEOUT_S["first"] - 60)}, "blockers": {}, "import": {}, "regen": {}})
    env.remote_fn = lambda h, c: snap({"s": "running"})
    rep = ER.orchestrate(env, args(), ["first"])
    assert rep["status"] == "blocked" and "超时" in rep["stages"][0]["msg"] and env.issues


def test_watch_polls_with_interval_then_completes(tmp_path):
    env = FakeEnv(tmp_path)
    seq = iter([snap({"s": "running"}), snap({"s": "running"}), snap({"s": "passed"})])
    env.remote_fn = lambda h, c: next(seq)
    rep = ER.orchestrate(env, args(watch=True, interval=5), ["first"])
    assert rep["status"] == "done" and env.sleeps == [30, 30]           # 间隔下限 30 s，不紧循环


def test_dry_run_has_no_side_effects(tmp_path):
    env = FakeEnv(tmp_path, dry=True)
    write_p4(tmp_path)
    shaw = ER.sha256_file(write_script(tmp_path))
    env.local_fn = lambda a: (0, json.dumps({"ready": True, "shots": []}), "")
    env.remote_fn = lambda h, c: ((0, (shaw + " x").encode(), "") if "sha256sum" in c else vsnap({}, {}) if "night_state" in c
                                  else snap({"s": "ready"}, pause_hold=[{"shot": "s"}]))
    rep = ER.orchestrate(env, args(), ER.STAGES)
    assert rep["dry_run"] and env.issues == []
    assert not (tmp_path / "data/pipeline/runs/r1/episode_run").exists()
    # 只有读命令：没有 import-staged / regen / producer 写命令
    assert all("import-staged" not in " ".join(a) for a in env.local_log)
    assert all(" regen " not in c and "import-staged" not in c for _, c in env.remote_log)   # status --json 是只读，允许
    assert rep["stages"][0]["status"] == "todo" and rep["stopped_at"] == "first"


def test_render_md_marks_downstream(tmp_path):
    rep = {"run": "r1", "episode": 1, "at": "t", "dry_run": True, "status": "blocked", "stopped_at": "first", "exit": 2,
           "stages": [{"stage": "first", "status": "blocked", "msg": "x"}, {"stage": "video", "status": "done", "msg": "y"}]}
    assert "上游未完成" in ER.render_md(rep)


# ---------------------------------------------------------------- CODER-RES：status --json / regen --json / 无人值守 / 常驻
def test_image_snap_prefers_producer_status_json(tmp_path):
    env = FakeEnv(tmp_path)
    d = {"run": "r1", "episodes": [{"ep": 1, "headline": "h", "shots": [{"shot": "s1", "first": "passed", "why": ""}]}],
         "paused": False, "hold_lanes": [], "pause_hold": [], "runaway_hold": [], "heartbeat": "2026-11-05T10:00:00", "server_now": "2026-11-05T10:01:00"}
    env.remote_fn = lambda h, c: (0, (json.dumps(d) + "\n").encode(), "")
    s = ER.image_snap(env)
    assert s["shots"][0]["shot"] == "s1" and s["heartbeat"] and len(env.remote_log) == 1
    assert "producer.py status" in env.remote_log[0][1] and "--json" in env.remote_log[0][1]


def test_image_snap_falls_back_when_producer_has_no_json(tmp_path):
    env = FakeEnv(tmp_path)
    env.remote_fn = lambda h, c: (2, b"", "unrecognized --json") if "producer.py status" in c else snap({"s1": "passed"})
    s = ER.image_snap(env)
    assert s["shots"][0]["first"] == "passed" and len(env.remote_log) == 2


def test_act_regen_uses_json_and_records_shots(tmp_path):
    env = FakeEnv(tmp_path)
    env.remote_fn = lambda h, c: (0, b'ts line\n{"regen": ["ep01-S1", "ep01-S2"], "skipped": {}, "dry": false, "at": "2026-11-05T12:00:00"}\n', "")
    st = {"import": {"sha": "abcdef12"}, "regen": {}, "blockers": {}, "stage_started": {}}
    r = ER.act_regen(env, st, args(), {})
    assert r["status"] == "done" and "--json" in env.remote_log[0][1]
    assert st["regen"]["shots"] == ["ep01-S1", "ep01-S2"] and st["regen"]["at"] == "2026-11-05T12:00:00"


def test_unattended_metric(tmp_path):
    env = FakeEnv(tmp_path)
    p = tmp_path / "data/producer/runs/r1/log.jsonl"
    p.parent.mkdir(parents=True)
    ev = [dict(ts="2026-11-05T09:00:00", ev="regen", obj="first:ep01-S1", by="PS-MASTER"),
          dict(ts="2026-11-05T09:01:00", ev="resume", by="PS-MASTER"),
          dict(ts="2026-11-05T09:02:00", ev="regen", obj="first:ep01-S2", by="总调度 episode_run"),
          dict(ts="2026-11-05T09:03:00", ev="master_approve", obj="first:ep01-S2", by="owner"),
          dict(ts="2026-11-05T09:04:00", ev="pause", by="CANARY_AUTO"),
          dict(ts="2026-11-05T09:05:00", ev="rendered", obj="first:ep01-S1"),
          dict(ts="2026-11-05T09:06:00", ev="rendered", obj="first:ep01-S2"),
          dict(ts="2026-11-05T09:07:00", ev="dispatch", obj="first:ep02-S1"),
          dict(ts="2026-11-04T09:00:00", ev="regen", obj="first:ep01-S1", by="PS-MASTER")]
    p.write_text("\n".join(json.dumps(e) for e in ev) + "\nbad line\n", encoding="utf-8")
    m = ER.unattended_metric(env, "2026-11-05T00:00:00")
    assert m["manual"] == 2 and m["manual_by"] == {"PS-MASTER": 2} and m["owner_actions"] == 1 and m["orchestrated"] == 1
    assert m["auto"] == 2 and m["ratio"] == 0.5
    assert ER.unattended_metric(FakeEnv(tmp_path / "nope"))["available"] is False


def test_tick_once_writes_status_with_unattended(tmp_path):
    env = FakeEnv(tmp_path)
    env.remote_fn = lambda h, c: (1, b"", "x")
    env.local_fn = lambda a: (0, json.dumps({"ready": True, "shots": []}), "")
    r = ER.tick_once("r1", 1, env=env)
    assert r["status"] == "blocked" and r["stopped_at"] == "import"          # 没有 P4
    sj = json.loads((tmp_path / "data/pipeline/runs/r1/episode_run/ep01_status.json").read_text(encoding="utf-8"))
    assert "unattended" in sj
    r2 = ER.tick_once("r1", 1, env=env)                                      # 同一卡点第二拍不重复登记
    assert len(env.issues) == 1 and r2["status"] == "blocked"


def test_resident_thread_tick(tmp_path):
    spec2 = importlib.util.spec_from_file_location("rs_t", ROOT / "tools/autopilot/resident_sync.py")
    import sys
    sys.path.insert(0, str(ROOT / "tools/autopilot"))
    RS = importlib.util.module_from_spec(spec2)
    spec2.loader.exec_module(RS)
    calls = []

    def fake(run, ep):
        calls.append((run, ep))
        if ep == 2:
            raise RuntimeError("boom")
        return {"status": "wait", "stopped_at": "first", "exit": 3, "msg": "m"}
    hb = tmp_path / "hb.json"
    cfg = {"enabled": True, "interval_s": 300, "targets": [{"run": "r1", "ep": 1}, {"run": "r1", "ep": 2}]}
    out = RS.episode_run_tick_once(cfg, tick_fn=fake, hb_path=hb)
    assert calls == [("r1", 1), ("r1", 2)] and out["targets"]["r1/ep01"]["status"] == "wait" and out["targets"]["r1/ep02"]["status"] == "error"
    assert json.loads(hb.read_text(encoding="utf-8"))["enabled"] is True
    calls.clear()                                                             # 关闭开关 = 不调用
    out = RS.episode_run_tick_once({**cfg, "enabled": False}, tick_fn=fake, hb_path=hb)
    assert calls == [] and out["targets"] == {}
    c = tmp_path / "c.json"
    c.write_text(json.dumps({"enabled": True, "interval_s": 5, "targets": [{"run": "a", "ep": 1}, {"run": "b"}]}), encoding="utf-8")
    assert RS.episode_run_cfg(c)["interval_s"] == 60 and len(RS.episode_run_cfg(c)["targets"]) == 1
    assert RS.episode_run_cfg(ROOT / "config/pipeline/episode_run.json")["enabled"] is True
