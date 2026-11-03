"""ISS-1103-033310-5833（SYSAUDIT-F 11-03，P0）：常驻 producer 必须带 run 身份，run 切换 / 剧归档时自己交接退出。

事故：笔记本 producer（11-02 01:45 起，RUN_ID 进程内缓存 = series10_v1）在 primary 切到 series10_v2、V1 归档后一直为 V1 跑，
心跳写 data/producer/heartbeat.json，V2 没有任何 producer，5 条出图道空转 ≥ 8 小时。临时目录、假 producer，不碰真实数据。
"""
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import producer as PR  # noqa: E402


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _root(tmp_path, run_json="series10_v2", v1="archived", v2="producing"):
    _w(tmp_path / "config/pipeline/run.json", {"run_id": run_json})
    _w(tmp_path / "config/pipeline/runs.json", {"primary": run_json, "legacy_unprefixed_run": "series10_v1",
                                                "runs": {"series10_v1": {"status": v1}, "series10_v2": {"status": v2}}})
    return tmp_path


class FakeProducer:
    """只要 serve / handoff 用到的面：inflight、tick、wait_idle、identity"""

    def __init__(self, paths, inflight=0):
        self.p = paths
        self.inflight = {f"o{i}": {} for i in range(inflight)}
        self.ticks = []
        self.lanes = {}
        paths.pd.mkdir(parents=True, exist_ok=True)

    run_source = "explicit"
    started_at = None
    identity = PR.Producer.identity

    def tick(self, dispatch=True):
        self.ticks.append(dispatch)
        if not dispatch:
            self.inflight.clear()          # 排空：停派单后手上的图做完
        PR.js(self.p.heartbeat, {"ts": PR.iso(), "pid": os.getpid(), "paused": False, **self.identity()})
        return {}

    def wait_idle(self, timeout=0):
        return None


def test_heartbeat_carries_run_identity(tmp_path):
    root = _root(tmp_path)
    paths = PR.Paths(root=root, run_id="series10_v2")
    fp = FakeProducer(paths)
    assert PR.serve(paths, producer=fp, spawn=lambda *a: 0, sleep=lambda s: None, max_ticks=2) == 0
    hb = json.loads(paths.heartbeat.read_text(encoding="utf-8"))
    assert hb["run"] == "series10_v2" and hb["run_source"] == "runs.json:primary"
    assert hb["pd"] == "data/producer/runs/series10_v2"            # V2 心跳不写 V1 的 data/producer/heartbeat.json
    pid = json.loads((paths.pd / "producer.pid").read_text(encoding="utf-8"))
    assert pid["run"] == "series10_v2" and fp.ticks == [True, True]


def test_run_json_switch_drains_exits_and_spawns_successor(tmp_path):
    """V1 进程（没钉 run）启动后 run.json 切到 V2：下一拍停派、排空、心跳写 exiting、放 pid 文件、为 V2 拉起接班"""
    root = _root(tmp_path, run_json="series10_v1", v1="producing")
    paths = PR.Paths(root=root, run_id="series10_v1")
    fp = FakeProducer(paths, inflight=2)
    spawned = []
    calls = {"n": 0}

    def sleep(_s):
        calls["n"] += 1
        if calls["n"] == 1:      # 第 1 拍后：总调度切剧 + V1 归档
            _root(tmp_path, run_json="series10_v2", v1="archived")

    rc = PR.serve(paths, producer=fp, spawn=lambda p, log: spawned.append((p.run_id, log)) or 4242, sleep=sleep, max_ticks=5)
    assert rc == 0
    assert fp.ticks == [True, False]                           # 切换后只做排空拍，不再派单
    hb = json.loads(paths.heartbeat.read_text(encoding="utf-8"))
    assert hb["run"] == "series10_v1" and "exit_reason" in hb and hb["successor"] == {"run": "series10_v2", "pid": 4242}
    assert "archived" in hb["exit_reason"] or "series10_v2" in hb["exit_reason"]
    assert not (paths.pd / "producer.pid").exists()
    assert spawned and spawned[0][1] == root / "data/producer/runs/series10_v2/producer.out"
    log = [json.loads(x) for x in paths.log.read_text(encoding="utf-8").splitlines()]
    assert [x["ev"] for x in log][-2:] == ["run_switch", "exit"]


def test_archived_run_refuses_to_start_and_hands_off(tmp_path):
    """V1 已归档还有人照旧 `producer.py serve`（restart_producer.ps1 / resident_restart.sh 的老命令）：不占 pid、直接交给 V2"""
    root = _root(tmp_path)
    paths = PR.Paths(root=root, run_id="series10_v1")
    fp = FakeProducer(paths)
    spawned = []
    assert PR.serve(paths, producer=fp, spawn=lambda p, log: spawned.append(1) or 7, sleep=lambda s: None, max_ticks=3) == 0
    assert fp.ticks == [] and spawned == [1] and not (paths.pd / "producer.pid").exists()


def test_pinned_run_ignores_run_json_but_exits_when_archived(tmp_path):
    """--run 钉死的额外剧（多剧并行）不跟 run.json 走；本剧归档了才退，而且不拉接班"""
    root = _root(tmp_path, run_json="series10_v2")
    paths = PR.Paths(root=root, run_id="series10_v1")
    _root(tmp_path, run_json="series10_v2", v1="producing")
    assert PR.identity_drift(paths, pinned=True) is None
    assert "series10_v2" in PR.identity_drift(paths, pinned=False)
    _root(tmp_path, run_json="series10_v2", v1="archived")
    spawned = []
    fp = FakeProducer(paths)
    assert PR.serve(paths, pinned=True, producer=fp, spawn=lambda *a: spawned.append(1), sleep=lambda s: None, max_ticks=2) == 0
    assert spawned == [] and fp.ticks == []


def test_successor_not_spawned_for_archived_target(tmp_path):
    root = _root(tmp_path, run_json="series10_v2", v2="archived")
    paths = PR.Paths(root=root, run_id="series10_v1")
    out = PR.handoff(FakeProducer(paths), paths, "测试", pinned=False, spawn=lambda *a: 1, drain_s=0)
    assert out["successor"] is None


def test_spawn_successor_strips_old_run_env(tmp_path, monkeypatch):
    root = _root(tmp_path)
    paths = PR.Paths(root=root, run_id="series10_v1")
    seen = {}

    class P:
        pid = 99

    def fake_popen(cmd, **kw):
        seen.update(cmd=cmd, env=kw["env"])
        return P()

    monkeypatch.setenv("NS_RUN", "series10_s2")
    monkeypatch.setattr(PR.subprocess, "Popen", fake_popen)
    assert PR.spawn_successor(paths, tmp_path / "x/producer.out") == 99
    assert "NS_RUN" not in seen["env"] and seen["cmd"][-1] == "serve" and "--run" not in seen["cmd"]


# ---------------------------------------------------------------- master_check ⑥ / resident health 能看出“为哪部剧在跑”
def _load(name, rel):
    import importlib.util
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_master_check_shows_run_identity_and_stale_archived_process(tmp_path):
    import time
    MC = _load("master_check_t_runid", "tools/master/master_check.py")
    root = _root(tmp_path, v2="preparing")
    now = time.time()
    lines = MC.sec_producers(root, now)
    assert any("producer[series10_v2]" in x and "没有心跳" in x for x in lines)          # 事故现场：V2 没人跑
    _w(root / "data/producer/heartbeat.json", {"t": now - 5, "pid": 13972, "paused": False, "inflight": 0})   # 旧代码：无 run
    lines = MC.sec_producers(root, now)
    assert any("series10_v1" in x and "13972" in x and "旧代码" in x and "⚠" in x for x in lines)
    _w(root / "data/producer/runs/series10_v2/heartbeat.json",
       {"t": now - 5, "pid": 5, "paused": True, "inflight": 0, "run": "series10_v2", "run_source": "runs.json:primary"})
    _w(root / "data/producer/heartbeat.json", {"t": now - 30, "pid": 13972, "run": "series10_v1", "exited": "x", "exit_reason": "归档"})
    lines = MC.sec_producers(root, now)
    assert lines == ["  producer[series10_v2]（preparing）pid 5 在跑·暂停 在途0，心跳 5s 前"]


def test_resident_health_reads_run_dir_and_flags_wrong_run():
    RS = _load("resident_sync_t_runid", "tools/autopilot/resident_sync.py")
    assert RS.producer_rel("series10_v1") == "data/producer"
    assert RS.producer_rel("series10_v2") == "data/producer/runs/series10_v2"
    assert "__PD__" in RS.REMOTE_HEALTH and "data/producer/heartbeat.json" not in RS.REMOTE_HEALTH
    assert RS.producer_run_mismatch({"run": "series10_v2", "t": 1}, "series10_v2") is None
    assert "series10_v1" in RS.producer_run_mismatch({"run": "series10_v1", "t": 1}, "series10_v2")
    assert "旧代码" in RS.producer_run_mismatch({"t": 1, "pid": 3}, "series10_v2")
    assert RS.producer_run_mismatch({}, "series10_v2") is None


# ---------------------------------------------------------------- W8 / A1-1：登记表读坏 = 未知，不动；连续 2 拍一致才交接；交接末尾复核
def test_truncated_runs_json_is_unknown_not_switch(tmp_path):
    """A1 drift_test CASE A / B：runs.json 截断（ValueError），无 run.json 或 run.json 旧指针 v1 → 不判切换（原来回退 series10_v1 误判）"""
    root = _root(tmp_path, run_json="series10_v2")
    paths = PR.Paths(root=root, run_id="series10_v2")
    (root / "config/pipeline/runs.json").write_text('{"primary": "series10_v2", "runs": {"series10_v', encoding="utf-8")
    (root / "config/pipeline/run.json").unlink()
    assert PR.primary_now(root, pause=0) is None
    assert PR.identity_drift(paths, pinned=False) is None                    # CASE A
    _w(root / "config/pipeline/run.json", {"run_id": "series10_v1"})
    assert PR.identity_drift(paths, pinned=False) is None                    # CASE B：run.json 旧指针也不当真
    _root(tmp_path, run_json="series10_v2")
    assert PR.identity_drift(paths, pinned=False) is None                    # CASE C：登记表正常、身份对


def test_runs_json_permission_error_is_unknown(tmp_path, monkeypatch):
    """Windows os.replace 撞上读者 → read_text 抛 PermissionError：不判切换，serve 照常派单、不交接"""
    root = _root(tmp_path, run_json="series10_v2")
    paths = PR.Paths(root=root, run_id="series10_v2")
    real = Path.read_text

    def flaky(self, *a, **k):
        if self.name == "runs.json":
            raise PermissionError(13, "The process cannot access the file because it is being used by another process")
        return real(self, *a, **k)

    monkeypatch.setattr(Path, "read_text", flaky)
    assert PR.primary_now(root, pause=0) is None and PR.identity_drift(paths, pinned=False) is None
    fp = FakeProducer(paths)
    spawned = []
    assert PR.serve(paths, producer=fp, spawn=lambda *a: spawned.append(1) or 1, sleep=lambda s: None, max_ticks=3) == 0
    assert fp.ticks == [True, True, True] and spawned == []


def test_single_tick_blip_does_not_hand_off(tmp_path):
    """drift 只出现 1 拍（登记表被人写错又改回）→ 只停派单 1 拍，不交接、不拉接班"""
    root = _root(tmp_path, run_json="series10_v2")
    paths = PR.Paths(root=root, run_id="series10_v2")
    fp = FakeProducer(paths)
    calls = {"n": 0}

    def sleep(_s):
        calls["n"] += 1
        if calls["n"] == 1:
            _root(tmp_path, run_json="series10_v1", v1="producing")          # 闪一下
        elif calls["n"] == 2:
            _root(tmp_path, run_json="series10_v2")                          # 又改回

    spawned = []
    assert PR.serve(paths, producer=fp, spawn=lambda *a: spawned.append(1) or 1, sleep=sleep, max_ticks=4) == 0
    assert fp.ticks == [True, False, True, True] and spawned == []
    evs = [json.loads(x)["ev"] for x in paths.log.read_text(encoding="utf-8").splitlines()]
    assert "run_switch_suspect" in evs and "run_switch_cleared" in evs and "exit" not in evs


def test_handoff_aborts_when_identity_recovered(tmp_path):
    """排空期间登记表恢复（new == 本剧且未归档）→ 放弃交接，不写 exited、不放 pid、不拉接班"""
    root = _root(tmp_path, run_json="series10_v2")
    paths = PR.Paths(root=root, run_id="series10_v2")
    fp = FakeProducer(paths)
    spawned = []
    out = PR.handoff(fp, paths, "主剧已切到 series10_v1（读坏）", pinned=False, spawn=lambda *a: spawned.append(1), drain_s=0)
    assert out["aborted"] and out["successor"] is None and spawned == []
    assert not paths.heartbeat.exists() or "exited" not in json.loads(paths.heartbeat.read_text(encoding="utf-8"))


# ---------------------------------------------------------------- W8 / A1-2：排空没完不写 exited
class StuckProducer(FakeProducer):
    def tick(self, dispatch=True):
        self.ticks.append(dispatch)
        return {}


def test_drain_overrun_heartbeat_is_draining_not_exited(tmp_path):
    root = _root(tmp_path, run_json="series10_v2")
    paths = PR.Paths(root=root, run_id="series10_v1")
    fp = StuckProducer(paths, inflight=2)
    out = PR.handoff(fp, paths, "v1 归档", pinned=False, spawn=lambda *a: 5, drain_s=0, wait_s=0)
    hb = json.loads(paths.heartbeat.read_text(encoding="utf-8"))
    assert not out["drained"] and hb["state"] == "draining" and "exited" not in hb and hb["inflight"] == 2
    fp.inflight.clear()
    PR.handoff(fp, paths, "v1 归档", pinned=False, spawn=lambda *a: 5, drain_s=0, wait_s=0)
    hb = json.loads(paths.heartbeat.read_text(encoding="utf-8"))
    assert hb["state"] == "exited" and hb.get("exited")


# ---------------------------------------------------------------- W8 / A1-3：pid 文件 O_EXCL + 持有者身份校验
def test_pid_reuse_does_not_block_start(tmp_path, monkeypatch):
    """pid 文件里的 pid 活着但是别的进程（PID 复用：心跳不是它 / 没心跳、文件也不新）→ 认陈旧，照常启动"""
    root = _root(tmp_path, run_json="series10_v2")
    paths = PR.Paths(root=root, run_id="series10_v2")
    pidf = paths.pd / "producer.pid"
    _w(pidf, {"pid": 4242, "started": "2026-11-01T00:00:00", "run": "series10_v2"})
    old = PR.now() - 3600
    os.utime(pidf, (old, old))
    monkeypatch.setattr(PR, "pid_alive", lambda pid: True)
    ok, rec = PR.acquire_pidfile(paths, {"pid": os.getpid(), "started": "x"})
    assert ok and json.loads(pidf.read_text(encoding="utf-8"))["pid"] == os.getpid()


def test_live_holder_with_fresh_heartbeat_blocks_second_start(tmp_path, monkeypatch):
    root = _root(tmp_path, run_json="series10_v2")
    paths = PR.Paths(root=root, run_id="series10_v2")
    _w(paths.pd / "producer.pid", {"pid": 4242, "started": "S1", "run": "series10_v2"})
    _w(paths.heartbeat, {"pid": 4242, "started": "S1", "t": PR.now(), "run": "series10_v2"})
    monkeypatch.setattr(PR, "pid_alive", lambda pid: True)
    ok, rec = PR.acquire_pidfile(paths, {"pid": os.getpid(), "started": "x"})
    assert not ok and rec["pid"] == 4242
    fp = FakeProducer(paths)
    assert PR.serve(paths, producer=fp, spawn=lambda *a: 1, sleep=lambda s: None, max_ticks=2) == 0 and fp.ticks == []
    _w(paths.heartbeat, {"pid": 4242, "started": "S0-另一个进程", "t": PR.now()})   # 心跳 started 对不上 = 不是它
    os.utime(paths.pd / "producer.pid", (PR.now() - 3600, PR.now() - 3600))
    assert PR.acquire_pidfile(paths, {"pid": os.getpid(), "started": "x"})[0]
