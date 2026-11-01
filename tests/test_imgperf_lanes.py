"""IMGPERF（11-01）：项目方“image rendering 肯定有 bugs，怎么这么慢”。

1. 自动选道 = 最空的道：出图卡上已有出图任务时，新出图任务去空闲道（原规则按每张 70 s 算，三张全排在 gpu33:0）
2. 道负载按同类最近实测耗时算（per_job_s），不是固定 70 s
3. gpu33 GPU2 永不派活；gpu36:2（long_only 视频道）不接出图；训练锁道不派
4. 任务记录有 progress（当前阶段 + step）和 timing（每段秒数、gpu_s、total_s）
"""
from __future__ import annotations

import json
import time

import pytest

from ns_api import jobs as J
from ns_render import endpoints as EP

CFG = {"image": {"url": "http://127.0.0.1:18188", "gpu": 0}, "video": {"url": "http://127.0.0.1:18191", "gpu": 3},
       "gpus": {"0": "http://127.0.0.1:18188", "1": "http://127.0.0.1:18189", "3": "http://127.0.0.1:18191"},
       "lanes": {"gpu36:0": "http://127.0.0.1:18288", "gpu36:1": "http://127.0.0.1:18289",
                 "gpu36:2": {"url": "http://127.0.0.1:18290", "long_only": True, "max_frames": 362}}}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "render_endpoints.json"
    p.write_text(json.dumps(CFG), encoding="utf-8")
    monkeypatch.setattr(EP, "CONFIG", p)
    from ns_api import llm_config as LC
    monkeypatch.setattr(LC, "RENDER_FILE", p)
    for k in ("NS_COMFY_URL", "NS_COMFY_URL_GPU0", "NS_COMFY_URL_GPU1", "NS_COMFY_URL_GPU3", "NS_COMFY_URL_GPU36_0"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(J, "_jobs", {})
    monkeypatch.setattr(J, "reachable_fn", lambda url: {"reachable": True, "running": 0, "pending": 0})
    monkeypatch.setattr(J, "train_lock_fn", lambda server: set())
    monkeypatch.setattr(J, "_train_cache", {})
    monkeypatch.setattr(J, "per_job_s", lambda kind: 840.0 if kind == "video" else 400.0)
    yield p
    J._jobs.clear()


def _job(gpu, kind="frame", state="running"):
    jid = f"j{len(J._jobs)}"
    J._jobs[jid] = {"id": jid, "gpu": gpu, "kind": kind, "state": state}


def test_three_frames_spread_over_free_lanes(cfg):
    """01:50 现场：ep01-S1/S2/S3 三张首帧全排在 gpu33:0，gpu33:1/:3、gpu36:0 空着"""
    got = []
    for _ in range(3):
        g = J.pick_lane("image")
        got.append(g)
        _job(g, "frame", "running" if not got[:-1] else "queued")
    assert got[0] == 0                                   # 出图卡空闲 → 出图卡
    assert len(set(got)) == 3                            # 后两张去别的空闲道，不排队
    assert "gpu36:2" not in got                          # long_only 视频道不接出图


def test_all_busy_picks_least_expected_wait(cfg):
    for g in (0, 1, 3, "gpu36:0", "gpu36:1"):
        _job(g, "frame")
    _job(0, "frame", "queued")
    _job(1, "video", "queued")
    _job(3, "frame", "queued")
    _job("gpu36:0", "frame", "queued")
    assert J.pick_lane("image") == "gpu36:1"             # 只有它只排着一张图


def test_external_queue_depth_counts(cfg, monkeypatch):
    """真实 /queue 深度（别人直接投的任务）算负载"""
    busy = {"18188": 2, "18189": 1, "18191": 1, "18288": 1, "18289": 3}
    monkeypatch.setattr(J, "reachable_fn", lambda url: {"reachable": True, "running": 1 if busy.get(url[-5:]) else 0,
                                                        "pending": max(0, busy.get(url[-5:], 0) - 1)})
    g = J.pick_lane("image")
    assert g in (1, 3, "gpu36:0")                        # 各 1 个外部任务，最少；不是排 2 个的出图卡


def test_load_uses_measured_duration(cfg):
    _job(0, "frame")
    by = {ln["id"]: ln for ln in J.lanes()}
    assert by["gpu33:0"]["load_s"] == 400.0              # per_job_s（实测中位数），不是 70


def test_gpu33_gpu2_never(cfg, monkeypatch):
    cfg2 = dict(CFG, gpus={**CFG["gpus"], "2": "http://127.0.0.1:18190"})
    cfg.write_text(json.dumps(cfg2), encoding="utf-8")
    for g in (0, 1, 3, "gpu36:0", "gpu36:1"):
        _job(g, "frame")
    assert J.pick_lane("image") != 2                     # 就算配置里有、而且空闲
    assert J.pick_lane("video") != 2
    with pytest.raises(ValueError):
        J.resolve_lane(2, "image")


def test_train_locked_lane_skipped(cfg, monkeypatch):
    monkeypatch.setattr(J, "train_lock_fn", lambda server: {0, 1} if server == "gpu33" else set())
    assert J.pick_lane("image") == 3


def test_per_job_s_median_of_recent(monkeypatch):
    monkeypatch.setattr(J, "_per_cache", {})
    monkeypatch.setattr(J, "_done_jobs", lambda: [{"kind": "frame", "wall_s": s} for s in (300, 600, 860, 50, 40, 9)])
    assert J.per_job_s("frame") == 300                   # 最近 5 个：300 600 860 50 40 → 中位数 300


# ------------------------------------------------------------------ progress / timing
def test_progress_and_timing_fields(monkeypatch):
    monkeypatch.setattr(J, "persist", lambda job: None)
    job = {"id": "t1", "state": "running"}
    J.progress(job, "prepare")
    J.progress(job, "upload", step=1)
    J.progress(job, "upload", step=2)
    assert job["progress"]["stage"] == "upload" and job["progress"]["step"] == 2
    J.progress(job, "comfy_run")
    time.sleep(0.05)
    J.progress(job, "post")
    job["state"] = "done"
    J._close_timing(job, 1.0)
    st = [s["stage"] for s in job["timing"]["stages"]]
    assert st == ["prepare", "upload", "comfy_run", "post"]          # 同一阶段只记一段
    assert job["timing"]["stages"][2]["s"] >= 0.0 and job["timing"]["total_s"] == 1.0
    assert job["progress"]["stage"] == "done" and job["progress"]["label"] == "完成"
    assert "_stage_t" not in job and "t1" not in J._stage_t


def test_gpu_seconds_from_history():
    entry = {"status": {"messages": [["execution_start", {"timestamp": 1000}],
                                     ["execution_cached", {"timestamp": 1001}],
                                     ["execution_success", {"timestamp": 32000}]]}}
    assert J.gpu_seconds(entry) == 31.0
    assert J.gpu_seconds({"status": {}}) is None


def test_frame_timing_check_ratio():
    """K-OPS-P01：墙钟 ≤ 2 × GPU。01:50 现场 655a3f4c9079：墙钟 1243 s / GPU 约 35 s → 违规"""
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "tools" / "perf" / "frame_timing_check.py"
    spec = importlib.util.spec_from_file_location("frame_timing_check", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    jobs = [{"id": "old", "kind": "frame", "state": "done", "timing": {"gpu_s": 35.0, "total_s": 1243.4,
                                                                       "stages": [{"stage": "post", "s": 1180}]}},
            {"id": "new", "kind": "frame", "state": "done", "timing": {"gpu_s": 35.8, "total_s": 55.6}},
            {"id": "legacy", "kind": "frame", "state": "done", "wall_s": 300}]
    r = m.check(jobs)
    assert [v["id"] for v in r["violations"]] == ["old"] and r["violations"][0]["slowest"] == "post 1180 s"
    assert r["measured"] == 2 and r["untested"] == 1


def test_frame_timing_check_runner_logs():
    """K-OPS-P01 也查 PRODUCER / ASSETMASTER（今晚真正出图的执行方）：墙钟 vs ComfyUI 秒数（GPU 没记时作上界）+ 各道分布"""
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "tools" / "perf" / "frame_timing_check.py"
    spec = importlib.util.spec_from_file_location("frame_timing_check2", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    prod = m.from_producer([
        {"ev": "dispatch", "obj": "first:ep02-S1", "lane": "gpu33:1", "attempt": 1, "t": 1000.0},
        {"ev": "rendered", "obj": "first:ep02-S1", "lane": "gpu33:1", "secs": 77.3, "t": 1077.3},
        {"ev": "passed", "obj": "first:ep02-S1", "t": 1902.5},
        {"ev": "dispatch", "obj": "first:ep02-S2", "lane": "gpu33:3", "attempt": 1, "t": 1000.0},
        {"ev": "rendered", "obj": "first:ep02-S2", "lane": "gpu33:3", "secs": 60.0, "t": 1062.0},
        {"ev": "passed", "obj": "first:ep02-S2", "t": 1070.0}])
    r = m.check_runner(prod)
    assert [v["id"] for v in r["violations"]] == ["first:ep02-S1#1"]
    assert r["violations"][0]["contract_s"] == 825.2 and r["violations"][0]["proxy"] is True
    assert r["lanes"] == {"gpu33:1": 1, "gpu33:3": 1} and r["gpu_logged"] is False
    # PRODUCER 04:00 起：rendered 带 gpu_s，契约在道放出后算 → 判占道时长（dispatch→rendered），契约另报
    prod2 = m.from_producer([
        {"ev": "dispatch", "obj": "first:ep03-S1", "lane": "gpu33:0", "attempt": 1, "t": 0.0},
        {"ev": "rendered", "obj": "first:ep03-S1", "lane": "gpu33:0", "secs": 50.0, "gpu_s": 36.0, "t": 50.0},
        {"ev": "passed", "obj": "first:ep03-S1", "contract_s": 30.4, "gpu_s": 36.0, "t": 81.0}])
    r2 = m.check_runner(prod2)
    assert r2["violations"] == [] and r2["gpu_logged"] and prod2[0]["lane_s"] == 50.0 and prod2[0]["contract_s"] == 30.4
    log = "\n".join(["03:51:37 jobs 80 preflight 阻断 []",
                     "03:52:20 image ep01-S1 seed 1 gpu33:0 不过 ['Q5']",
                     "03:53:00 image ep01-S2 seed 1 gpu33:0 通过 []",
                     "03:52:30 image ep01-S3 seed 1 gpu33:1 通过 []"])
    st = {"ep01-S1": {"image": {"attempts": [{"seed": 1, "lane": "gpu33:0", "secs": 40.0}]}},
          "ep01-S2": {"image": {"attempts": [{"seed": 1, "lane": "gpu33:0", "secs": 38.0}]}},
          "ep01-S3": {"image": {"attempts": [{"seed": 1, "lane": "gpu33:1", "secs": 10.0}]}}}
    rows = m.from_assetmaster(log, st)
    assert [x["total_s"] for x in rows] == [43, 40, 53]           # 同道相邻结束的间隔；每道第一次从本轮启动算
    a = m.check_runner(rows)
    assert [v["id"] for v in a["violations"]] == ["ep01-S3/image/1"] and a["lanes"] == {"gpu33:0": 2, "gpu33:1": 1}
    # run9 起 ASSETMASTER 自带 started_at / finished_at / gpu_s：用实测
    st["ep01-S3"]["image"]["attempts"][0].update(started_at="2026-11-01T03:51:40", finished_at="2026-11-01T03:52:30",
                                                  gpu_s=30.0, score_s=5.0)
    rows = m.from_assetmaster(log, st)
    assert rows[2]["timed"] and rows[2]["total_s"] == 50.0 and rows[2]["gpu_s"] == 30.0
    a = m.check_runner(rows)
    assert a["violations"] == [] and a["gpu_logged"] is True


def test_remote_score_single_ssh(tmp_path, monkeypatch):
    """K-OPS-P02：postflight 远端打分一次 ssh 往返（原来 6 次 ssh + 1 次 scp，实测 130 s）"""
    import subprocess
    import sys
    from pathlib import Path
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools" / "gen_contract"))
    import remote_score as RS
    calls = []

    class R:
        stdout = json.dumps({"items": {"x": {"faces": []}}, "cross": {}, "hands": {"x": {"hands": 0}}, "refs": []})
        stderr = ""
    monkeypatch.setattr(RS, "ssh", lambda host, cmd, stdin=None, timeout=900: calls.append((host, cmd, stdin)) or R())
    monkeypatch.setattr(subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("不许再 scp")))
    monkeypatch.setattr(RS, "face_refs", lambda host, project="series10_v1": {"lin_wan": "/r/id_x.png"})   # 身份脸已在机器上
    img = tmp_path / "a.png"
    img.write_bytes(b"\x89PNG fake")
    m = RS.score_local_files("gpu33", {"x": img})
    assert len(calls) == 1 and m["hands"]["x"] == {"hands": 0}
    payload = json.loads(calls[0][2])
    assert list(payload["files"]) == ["x"] and payload["files"]["x"][0] == "a.png"


def test_slow_lock_read_overlaps_prepare_but_gates_submit(monkeypatch):
    """训练锁 ssh 慢（实测 10.4 s）：准备阶段先做，向 ComfyUI 投图前必须等到锁读完；锁着 → 不投图、任务失败带“训练锁”"""
    import threading
    gate = threading.Event()
    monkeypatch.setattr(J, "LOCK_WAIT_S", 0.05)

    class C:
        submitted = []

        def submit(self, wf):
            self.submitted.append(wf)
            return "pid"
    for locked, expect in ((True, False), (False, True)):
        gate.clear()
        box: dict = {}

        def read(locked=locked):
            gate.wait(2)
            box["locked"] = locked
        lt = threading.Thread(target=read, daemon=True)
        lt.start()
        c = C()
        C.submitted = []
        J._gate_submit(c, lt, box, 1)
        threading.Timer(0.1, gate.set).start()
        if expect:
            assert c.submit({"w": 1}) == "pid" and C.submitted == [{"w": 1}]
        else:
            with pytest.raises(J.TrainLocked) as e:
                c.submit({"w": 1})
            assert J.TRAIN_LOCKED_ERR in str(e.value) and C.submitted == []


class _FakeClient:
    def __init__(self):
        self.calls = 0

    def _json(self, path, body=None):
        self.calls += 1
        if path == "/queue":
            return {"queue_running": [[0, "other"]], "queue_pending": [[1, "pid"]]} if self.calls < 3 else \
                {"queue_running": [[0, "pid"]], "queue_pending": []}
        if self.calls < 5:
            return {}
        return {"pid": {"status": {"completed": True, "status_str": "success", "messages": [
            ["execution_start", {"timestamp": 0}], ["execution_success", {"timestamp": 2500}]]}, "outputs": {}}}


def test_wait_prompt_reports_queue_then_run(monkeypatch):
    monkeypatch.setattr(J, "persist", lambda job: None)
    seen = []
    orig = J.progress

    def spy(job, stage, *a, **k):
        seen.append((stage, k.get("step")))
        return orig(job, stage, *a, **k)
    monkeypatch.setattr(J, "progress", spy)
    job = {"id": "w1", "state": "running"}
    J.wait_prompt(_FakeClient(), job, "pid", timeout_s=5, poll_s=0)
    assert ("comfy_queue", 1) in seen                    # 前面 1 个（别人的在跑）
    assert ("comfy_run", None) in seen
    assert job["timing"]["gpu_s"] == 2.5
    J._stage_t.pop("w1", None)
