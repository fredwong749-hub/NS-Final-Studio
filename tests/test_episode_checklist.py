"""PIPELINE_CHECKLIST 执法（tools/master/episode_checklist.py + episode_lock + asset_worker 让道）单测：全部 mock。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]


def _load(rel, name):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


ER = _load("tools/master/episode_run.py", "er_cl_t")
CL = _load("tools/master/episode_checklist.py", "cl_t")
EL = _load("tools/pipeline/episode_lock.py", "el_t")
T0 = 1_800_000_000.0


class FEnv(ER.Env):
    def __init__(self, tmp, **kw):
        super().__init__("r1", 1, root=tmp, **kw)
        self.t = T0
        self.now = lambda: self.t
        self.log, self.issues = [], []
        self.rfn = lambda host, cmd: (0, b'{"ok": true}', "")

    def root_of(self, h):
        return "/srv"

    def py_of(self, h):
        return "/py"

    def remote(self, host, cmd, timeout=120, tries=2, input=None):
        self.log.append((host, cmd))
        return self.rfn(host, cmd)

    def report_issue(self, step, what, blocking, hint):
        self.issues.append((step, what, blocking))
        return "ISS"


def tb0():
    return {"rows": {}}


def running_first(tb, sid, since, expect=330):
    CL.update_first_rows(tb, [{"shot": sid, "first": "running", "where": "gpu33:0", "since": since}], since + 1, expect)


# ---- 1 任务表
def test_task_table_rows_and_secs(tmp_path):
    tb = tb0()
    running_first(tb, "ep01-S1", T0)
    r = tb["rows"]["first:ep01-S1"]
    assert r["status"] == "running" and r["lane"] == "gpu33:0" and r["timeout_s"] == 660 and r["started"]
    CL.update_first_rows(tb, [{"shot": "ep01-S1", "first": "passed"}], T0 + 100, 330)
    assert r["status"] == "done" and r["secs"] == 100
    CL.note_stage(tb, "import", {"status": "done", "msg": "x"}, T0, None)
    assert tb["rows"]["step1_import"]["status"] == "done" and tb["rows"]["step1_import"]["timeout_s"] == 120
    md = CL.render_table_md(tb)
    assert "首帧 ep01-S1" in md and "导入分镜" in md


def test_save_load_roundtrip(tmp_path):
    env = FEnv(tmp_path)
    tb = tb0()
    running_first(tb, "ep01-S2", T0)
    CL.save_table(env, tb)
    assert (tmp_path / "data/pipeline/runs/r1/episode_run/ep01_tasks.json").is_file()
    assert CL.load_table(env)["rows"]["first:ep01-S2"]["status"] == "running"


# ---- 2 独占
def test_lock_active_expiry_and_clear(tmp_path):
    EL.write(tmp_path, "r1", 1, ttl_s=100, now=T0)
    assert EL.active(tmp_path, now=T0 + 50)["ep"] == 1
    assert EL.active(tmp_path, now=T0 + 101) is None
    assert EL.clear(tmp_path, "r1", 2) is False
    EL.write(tmp_path, "r1", 1, ttl_s=100, now=T0)
    assert EL.clear(tmp_path, "r1", 1) and EL.active(tmp_path, now=T0 + 1) is None


def test_asset_worker_skips_render_when_locked(tmp_path):
    sys.path.insert(0, str(ROOT / "tools" / "pipeline"))
    import asset_worker as AW
    src = (ROOT / "tools/pipeline/asset_worker.py").read_text(encoding="utf-8")
    assert "EL.active(root)" in src and "not lock" in src     # 接线存在
    import time
    EL.write(tmp_path, "r1", 1, ttl_s=600, now=time.time())
    assert AW.EL.active(tmp_path) is not None                  # asset_worker 用的就是这个旗标；root 对得上
    assert AW.EL.active(tmp_path / "other") is None


def test_acquire_applies_control_once_and_release_restores(tmp_path):
    env = FEnv(tmp_path)
    tb = tb0()
    lines = CL.acquire(env, tb, T0)
    assert EL.active(tmp_path, now=T0 + 1) and tb["ctrl_applied"] == {"gpu33": True, "gpu36": True}
    assert any("yield_s" in c and "_ep_lock_backup" in c for _h, c in env.log) and "gpu33:2" in env.log[0][1]
    n = len(env.log)
    CL.acquire(env, tb, T0 + 30)                               # 第二拍只刷新旗标，不再改控制
    assert len(env.log) == n and lines
    CL.release(env, tb)
    assert EL.active(tmp_path, now=T0 + 1) is None and tb["ctrl_applied"] is None
    assert any("_ep_lock_backup" in c and "pop" in c for _h, c in env.log[n:])


def test_control_code_runs_and_restores(tmp_path, monkeypatch):
    """服务器端小脚本本身：真跑一遍（本地临时目录），备份 / 清 hold / 还原"""
    import subprocess
    d = tmp_path / "data/pipeline/runs/r1/video"
    d.mkdir(parents=True)
    ctl = d / "night_control.json"
    ctl.write_text(json.dumps({"yield_s": 180, "hold_lanes": ["gpu33:2", "gpu36:0"], "per_lane": 2}), encoding="utf-8")
    run = lambda code: subprocess.run([sys.executable, "-c", code], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    r = run(CL.CTRL_CODE % {"run": "r1", "prot": json.dumps(CL.PROTECTED_HOLDS)})
    assert r.returncode == 0, r.stderr
    c = json.loads(ctl.read_text(encoding="utf-8"))
    assert c["yield_s"] == 0 and c["hold_lanes"] == ["gpu33:2"] and c["_ep_lock_backup"]["yield_s"] == 180
    run(CL.CTRL_CODE % {"run": "r1", "prot": json.dumps(CL.PROTECTED_HOLDS)})    # 幂等：备份不被覆盖
    assert json.loads(ctl.read_text(encoding="utf-8"))["_ep_lock_backup"]["yield_s"] == 180
    r = run(CL.RESTORE_CODE % {"run": "r1"})
    assert r.returncode == 0, r.stderr
    c = json.loads(ctl.read_text(encoding="utf-8"))
    assert c["yield_s"] == 180 and c["hold_lanes"] == ["gpu33:2", "gpu36:0"] and "_ep_lock_backup" not in c and c["per_lane"] == 2


# ---- 3 超时即重做
def test_first_over_2x_retry_then_adopt_after_3(tmp_path):
    env = FEnv(tmp_path)
    tb = tb0()
    running_first(tb, "ep01-S1", T0)
    assert CL.decide(tb, None, T0 + 600) == []                  # 600 < 2×330
    for k in range(1, 4):
        env.t = T0 + 700 * k
        acts = CL.decide(tb, None, env.t)
        assert [a["kind"] for a in acts] == ["first_retry"]
        CL.execute(env, tb, acts)
        assert tb["rows"]["first:ep01-S1"]["redos"] == k
        assert "retry --obj first:ep01-S1" in env.log[-1][1]
    env.t = T0 + 700 * 4
    acts = CL.decide(tb, None, env.t)
    assert [a["kind"] for a in acts] == ["first_adopt"]
    assert env.issues == []
    CL.execute(env, tb, acts)
    assert "review-adopt --obj first:ep01-S1" in env.log[-1][1] and len(env.issues) == 1      # 只有兜底才 report_issue


def test_turbo_tier_expect_60(tmp_path):
    (tmp_path / "config").mkdir()
    (tmp_path / "config/render_quality.json").write_text(json.dumps({"runs": {"r1": "turbo"}}), encoding="utf-8")
    assert CL.tier_expect_s(FEnv(tmp_path)) == 60
    tb = tb0()
    running_first(tb, "ep01-S1", T0, expect=60)
    assert [a["kind"] for a in CL.decide(tb, None, T0 + 130)] == ["first_retry"]


def test_video_over_900_or_undispatched_120_kicks_night(tmp_path):
    env = FEnv(tmp_path)
    tb = tb0()
    tb["rows"]["first:ep01-S3"] = {"status": "done", "done_at": T0, "step": 4, "shot": "ep01-S3"}
    CL.update_video_rows(tb, {"shots": {"ep01-S3": "pending"}, "renders": {}}, T0 + 100)
    assert CL.decide(tb, None, T0 + 100) == []
    acts = CL.decide(tb, None, T0 + 130)                        # 定稿 130 s 未派
    assert acts and acts[0]["kind"] == "video_kick"
    CL.execute(env, tb, acts)
    assert "night.py --once" in env.log[-1][1] and env.issues == []
    # 在出 > 900 s
    CL.update_video_rows(tb, {"shots": {"ep01-S3": "rendering"}, "renders": {"ep01-S3": [{"lane": "gpu36:0", "t": T0 + 200}]}}, T0 + 300)
    assert CL.decide(tb, None, T0 + 1000) == []                 # 800 s，还没到；且在冷却内
    acts = CL.decide(tb, None, T0 + 1200)
    assert acts and acts[0]["kind"] == "video_kick" and "900" in acts[0]["why"]
    CL.execute(env, tb, acts)
    env.t = T0 + 1500
    acts = CL.decide(tb, None, T0 + 1500)
    assert acts[0]["kind"] == "video_fallback"                  # 重派 2 次后兜底
    CL.execute(env, tb, acts)
    assert len(env.issues) == 1


def test_night_stale_requests_urgent_night_only_restart(tmp_path, monkeypatch):
    env = FEnv(tmp_path)
    tb = tb0()
    CL.update_video_rows(tb, {"shots": {"ep01-S3": "pending"}, "renders": {}}, T0)
    acts = CL.decide(tb, {"night_age_s": 1000}, T0)
    assert [a["kind"] for a in acts] == ["night_restart"]
    calls = []
    fake = SimpleNamespace(request=lambda host, reason, by, urgent=False, mode=None: calls.append((host, by, urgent, mode)))
    monkeypatch.setattr(CL, "_load", lambda rel, name: fake)
    CL.execute(env, tb, acts)
    assert calls == [("gpu36", "CHECKLIST", True, "night-only")] and len(env.issues) == 1
    assert CL.decide(tb, {"night_age_s": 1000}, T0 + 10) == []   # 只请求一次


# ---- 4 连接
def test_conn_health_logs_when_no_master_up(tmp_path):
    env = FEnv(tmp_path)
    (tmp_path / "data/netfix").mkdir(parents=True)
    (tmp_path / "data/netfix/net_status.json").write_text(json.dumps({"hosts": {"gpu33-cmd": {"state": "up"}, "gpu36-cmd": {"state": "down"}}}), encoding="utf-8")
    tb = tb0()
    out = CL.conn_health(env, tb, T0)
    assert len(out) == 1 and "gpu36" in out[0] and "| CHECKLIST | CONN |" in out[0]
    assert CL.conn_health(env, tb, T0 + 60) == []               # 10 分钟内不重复


# ---- 整合：tick + 报告
def test_tick_and_report_table(tmp_path):
    env = FEnv(tmp_path)
    snap = {"shots": [{"shot": "ep01-S1", "first": "running", "where": "gpu33:0", "since": T0 - 1000}]}
    er = SimpleNamespace(remote_py_json=lambda e, h, code: snap, video_snap=lambda e: None)
    tb = tb0()
    res = CL.tick(env, er, tb)
    assert [a["kind"] for a in res["acts"]] == ["first_retry"]
    ev = (tmp_path / "data/pipeline/runs/r1/episode_run/ep01_events.log").read_text(encoding="utf-8")
    assert "| CHECKLIST | ACT |" in ev and "| CHECKLIST | LOCK |" in ev
    rep = {"run": "r1", "episode": 1, "at": "x", "dry_run": False, "status": "wait", "stopped_at": None, "stages": [], "checklist": tb}
    assert "## 清单与耗时" in ER.render_md(rep)


def test_first_snap_code_runs_against_registry(tmp_path):
    import subprocess
    d = tmp_path / "data/producer/runs/r1"
    d.mkdir(parents=True)
    (d / "registry.json").write_text(json.dumps({"episodes": [{"ep": 1, "shots": [{"shot": "ep01-S1", "objects": {"first": {"status": "running", "where": "gpu33:0", "since": 5.0}}}]}]}), encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", CL.FIRST_SNAP % {"run": "r1", "ep": 1}], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert json.loads(r.stdout)["shots"][0] == {"shot": "ep01-S1", "first": "running", "where": "gpu33:0", "since": 5.0}


# ---- FIX-A 11-05：两台都要干活（有排队的活时某台所有道空 > 2 min → 记卡点 + 重新派活）
def _idle_er(by_host):
    return SimpleNamespace(remote_py_json=lambda e, h, code: by_host.get(h))


def test_lane_idle_triggers_after_2min_and_reacts_once(tmp_path):
    env = FEnv(tmp_path, image_host="gpu33", video_host="gpu36")
    er = _idle_er({"gpu33": {"busy": 0, "queued": 4}, "gpu36": {"busy": 2, "queued": 4}})
    tb = tb0()
    assert CL.lane_idle_acts(env, er, tb, T0) == []                    # 刚开始空：先计时
    assert CL.lane_idle_acts(env, er, tb, T0 + 100) == []              # < 2 min
    acts = CL.lane_idle_acts(env, er, tb, T0 + 130)
    assert [(a["kind"], a["host"]) for a in acts] == [("lane_idle", "gpu33")]    # 只有空的那台
    lines = CL.execute(env, tb, acts)
    assert env.issues and env.issues[0][0] == "checklist/lane_idle" and any("night.py --once" in c for h, c in env.log if h == "gpu33")
    assert CL.lane_idle_acts(env, er, tb, T0 + 200) == []              # 10 分钟内不重复
    assert len(CL.lane_idle_acts(env, er, tb, T0 + 130 + CL.LANE_IDLE_REACT_S + 1)) == 1


def test_lane_idle_cleared_when_busy_or_no_queue_or_unreadable(tmp_path):
    env = FEnv(tmp_path, image_host="gpu33", video_host="gpu36")
    tb = tb0()
    CL.lane_idle_acts(env, _idle_er({"gpu33": {"busy": 0, "queued": 3}}), tb, T0)
    assert "gpu33" in tb["idle"]
    CL.lane_idle_acts(env, _idle_er({"gpu33": None}), tb, T0 + 500)    # 读不到：不判也不报
    assert "gpu33" in tb["idle"]
    assert CL.lane_idle_acts(env, _idle_er({"gpu33": {"busy": 0, "queued": 0}}), tb, T0 + 600) == [] and "gpu33" not in tb["idle"]
    CL.lane_idle_acts(env, _idle_er({"gpu33": {"busy": 0, "queued": 3}}), tb, T0 + 700)
    assert CL.lane_idle_acts(env, _idle_er({"gpu33": {"busy": 1, "queued": 3}}), tb, T0 + 900) == []


def test_host_vid_snap_code_counts_busy_and_queued(tmp_path):
    import subprocess
    v = tmp_path / "data/pipeline/runs/r1/video"
    v.mkdir(parents=True)
    (v / "jobs.json").write_text(json.dumps({"shots": [{"shot": f"ep01-S{i}", "ep": 1} for i in (1, 2, 3)]}), encoding="utf-8")
    (v / "state_gpu33.json").write_text(json.dumps({"shots": {"ep01-S1": {"status": "done", "renders": []},
                                                              "ep01-S2": {"status": "rendering", "renders": [{"state": "submitted"}]}}}), encoding="utf-8")
    r = subprocess.run([sys.executable, "-c", CL.HOST_VID_SNAP % {"run": "r1", "ep": 1, "host": "gpu33"}], cwd=tmp_path, capture_output=True, text=True, timeout=120)
    assert json.loads(r.stdout) == {"host": "gpu33", "busy": 1, "queued": 2}
