"""W-E2E（L-214）：真机冒烟 tools/qa/e2e_smoke.py 的流程逻辑（全 fake，不连服务器、不起进程）：
段落顺序 / 计时、前一段不过后面不跑、30 分钟预算、成人镜中止、收尾总会跑且只隔离不删、只停自己记录的进程。"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location("e2e_smoke_t", ROOT / "tools/qa/e2e_smoke.py")
M = importlib.util.module_from_spec(sp)
sys.modules["e2e_smoke_t"] = M
sp.loader.exec_module(M)


def _reg(first, last):
    return {"episodes": [{"ep": 1, "shots": [{"shot": f"ep01-S{i}", "objects": {"first": {"status": first[i - 1]}, "last": {"status": last[i - 1]}}}
                                             for i in range(1, len(first) + 1)]}]}


class FakeEnv(M.Env):
    def __init__(self, root, script):
        super().__init__(root)
        self.t = 1000.0
        self.script = script            # [(匹配串, 返回)]，按调用顺序消费
        self.cmds: list = []
        self.pushed: list = []

    def now(self):
        return self.t

    def sleep(self, s):
        self.t += s

    def rssh(self, host, cmd, timeout=120):
        self.cmds.append((host, cmd))
        self.t += 1
        for key, fn in self.script:
            if key in cmd:
                return fn(self, host)
        return 0, ""

    def push_files(self, rels):
        self.pushed.append(list(rels))
        return {h: {"ok": True} for h in M.HOSTS}


def _smoke(tmp_path, script, budget=1800):
    s = M.Smoke(FakeEnv(tmp_path, script), budget_s=budget, poll_s=30)
    s.state = {"shots": 2, "stamp": "20261107-050000", "pids": {}}
    return s


def test_registry_and_video_progress():
    p = M.registry_progress(_reg(["passed", "running"], ["pending", "pending"]), "first")
    assert p == {"shots": 2, "done": 1, "failed": [], "running": 1}
    p = M.registry_progress(_reg(["passed", "best_effort"], ["x", "x"]), "first")
    assert p["failed"] and "ep01-S2" in p["failed"][0]
    v = M.video_progress([{"shots": {"ep01-S1": {"status": "done"}}}, {"shots": {"ep01-S2": {"status": "waiting_frame"}}}], 2)
    assert v == {"shots": 2, "done": 1, "failed": []}
    assert M.adult_shots({"episodes": [{"shots": [{"index": 1}, {"index": 2, "adult": True}]}]}) == ["ep01-S2"]
    assert "smoke_e2e" in M.seed_text("剧 smoke_v2 ") and "smoke_v2" not in M.seed_text("smoke_v2")


def test_frames_wait_until_all_passed_and_time_counted(tmp_path):
    seq = iter([_reg(["running", "pending"], ["pending"] * 2), _reg(["passed", "running"], ["pending"] * 2), _reg(["passed", "passed"], ["pending"] * 2)])
    cur = {"r": None}

    def reg(env, host):
        if host == "gpu33":
            cur["r"] = next(seq, cur["r"])
        return 0, json.dumps(cur["r"])
    s = _smoke(tmp_path, [("registry.json", reg)])
    assert s.frames("first").startswith("2/2")
    assert s.env.t > 1000 + 60          # 等了两轮


def test_frames_best_effort_is_a_failure_with_reason(tmp_path):
    s = _smoke(tmp_path, [("registry.json", lambda e, h: (0, json.dumps(_reg(["passed", "best_effort"], ["x", "x"]))))])
    with pytest.raises(M.SmokeAbort, match="ep01-S2"):
        s.frames("first")


def test_budget_exhaustion(tmp_path):
    s = _smoke(tmp_path, [("registry.json", lambda e, h: (0, json.dumps(_reg(["running", "running"], ["x", "x"]))))], budget=120)
    with pytest.raises(M.SmokeAbort, match="30 分钟预算用完"):
        s.frames("first")


def test_run_stops_after_failure_and_always_cleans_up_by_quarantine(tmp_path):
    s = _smoke(tmp_path, [])
    s.preflight = lambda: "ok"
    s.setup = lambda: "建好"
    s.import_ = lambda: "2 镜"

    def bad():
        raise M.SmokeAbort("资产没就绪：缺脸")
    s.assets = bad
    s.state["backups"] = {M.CFG_VIDEO: {"scope_runs": ["series10_v2"]}, M.CFG_STYLE: {"runs": {"series10_v2": {}}}}
    rep = s.run()
    assert [r["stage"] for r in rep["stages"]] == M.STAGES
    assert rep["failed_stage"] == "assets" and not rep["ok"]
    assert [r["ok"] for r in rep["stages"]] == [True, True, True, False, False, False, False]
    assert rep["stages"][4]["why"] == "前一段没过，没跑"
    cmds = " ".join(c for _h, c in s.env.cmds)
    assert "mv " in cmds and "data/_quarantine/smoke_e2e/20261107-050000" in cmds
    assert "rm " not in cmds and "pkill" not in cmds
    assert "grep -q 'smoke_e2e' /proc/$p/cmdline" in cmds                     # 只停命令行里带本剧名、pid 文件里记的进程
    assert M.CFG_PUSH in s.env.pushed and M.CFG_STYLE in M.CFG_PUSH
    assert json.loads((tmp_path / M.CFG_VIDEO).read_text(encoding="utf-8")) == {"scope_runs": ["series10_v2"]}   # 按备份恢复
    assert json.loads((tmp_path / M.CFG_STYLE).read_text(encoding="utf-8")) == {"runs": {"series10_v2": {}}}
    assert (tmp_path / M.OUT_DIR).is_dir()


def test_preflight_failure_creates_nothing(tmp_path):
    s = _smoke(tmp_path, [])

    def nope():
        raise M.SmokeAbort("gpu33 连不上")
    s.preflight = nope
    rep = s.run()
    assert rep["failed_stage"] == "preflight" and s.env.cmds == [] and s.env.pushed == []
    assert rep["cleanup"] == ["预检没过，什么都没建，不用收尾"]


def test_import_aborts_on_adult_shot(tmp_path):
    s = _smoke(tmp_path, [])
    rel = "data/import/runs/smoke_e2e/script_v2.json"
    out = tmp_path / rel

    class RunsStub:
        @staticmethod
        def import_path(run, root):
            return ROOT / rel

    def sh(cmd, timeout):
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({"episodes": [{"shots": [{"index": 1}, {"index": 2, "adult": True}]}]}), encoding="utf-8")
        return 0, "ok"
    s.env.runs = lambda: RunsStub
    s.env.sh = sh
    with pytest.raises(M.SmokeAbort, match="成人"):
        s.import_()


def test_video_starts_night_with_pid_and_waits(tmp_path):
    n = {"k": 0}

    def state(env, host):
        n["k"] += 1
        done = {"ep01-S1": {"status": "done"}, "ep01-S2": {"status": "done" if n["k"] > 2 else "waiting_frame"}}
        return 0, json.dumps({"shots": done if host == "gpu36" else {}})
    s = _smoke(tmp_path, [("night.py", lambda e, h: (0, "4242")), ("state_", state)])
    assert s.video().startswith("2/2")
    starts = [c for h, c in s.env.cmds if "night.py --run smoke_e2e" in c]
    assert len(starts) == 2 and all("night_e2e.pid" in c and "OFFLINE_SELF=" in c for c in starts)
    assert "gpu33:night" in s.state["pids"] and "gpu36:night" in s.state["pids"]


def test_plan_writes_nothing(tmp_path):
    s = M.Smoke(FakeEnv(tmp_path, []), dry=True)
    s.preflight = lambda: "plan"
    rep = s.run()
    assert rep["dry"] and len(rep["plan"]) >= 10 and s.env.cmds == [] and s.env.pushed == []
    assert not any(tmp_path.rglob("*"))
