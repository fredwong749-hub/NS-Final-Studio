"""GPU 道卡死自愈（MASTER-WSL 11-03 ASSIGN D）：自己人的单超时 → 定向打断；别人的单只登记；过期锁 / 读不到锁登记；计数给 master_check ⑦"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sp = importlib.util.spec_from_file_location("lane_heal_t", ROOT / "tools/autopilot/lane_heal.py")
LH = importlib.util.module_from_spec(sp)
sp.loader.exec_module(LH)


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setattr(LH, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(LH, "LOG", tmp_path / "heal.jsonl")
    monkeypatch.setattr(LH, "CFG", tmp_path / "none.json")
    calls = {"cancel": [], "report": []}
    def report(what, hint):
        calls["report"].append(what)
        return f"ISS-T{len(calls['report'])}"
    return calls, report


def q(pid, agent=None, kind="first_frame"):
    tag = {"agent": agent, "kind": kind} if agent else {}
    return {"queue_running": [[1, pid, {}, {"ns_tag": tag} if tag else {}, []]], "queue_pending": []}


def run(env, lanes_q, t, **kw):
    calls, report = env
    return LH.tick({k: f"http://{k}" for k in lanes_q}, now=t, queue_fn=lambda u: lanes_q[u.split("//")[1]],
                   cancel_fn=lambda u, p: calls["cancel"].append((u, p)), report_fn=report, **kw)


def test_own_job_over_limit_interrupted_once(env):
    calls, _ = env
    lanes = {"gpu33:3": q("p1", "PRODUCER")}
    assert run(env, lanes, 1000.0) == []                       # 第一次看到：记起点
    assert run(env, lanes, 1000.0 + 899) == []                 # 300×3=900 s 以内不动
    acts = run(env, lanes, 1000.0 + 901)
    assert acts[0]["event"] == "healed" and calls["cancel"] == [("http://gpu33:3", "p1")]
    assert len(calls["report"]) == 1 and "已定向打断" in calls["report"][0]
    assert LH.healed_count(now=1e12)["healed"] == 0            # 日志按墙钟，远未来窗口外
    assert LH.healed_count()["healed"] == 1


def test_new_prompt_resets_clock(env):
    calls, _ = env
    run(env, {"gpu33:0": q("a", "PRODUCER")}, 0.0 + 1e9)
    acts = run(env, {"gpu33:0": q("b", "PRODUCER")}, 1e9 + 2000)   # 换了一单：重新计时
    assert acts == [] and calls["cancel"] == []


def test_foreign_job_only_reported(env):
    calls, _ = env
    lanes = {"gpu36:1": q("v1", "VIDEO10", "video")}
    run(env, lanes, 1e9)
    acts = run(env, lanes, 1e9 + 5401)                         # 视频 1500×3 → 夹到 hard_cap 5400
    assert acts[0]["event"] == "stuck_foreign" and calls["cancel"] == []
    run(env, lanes, 1e9 + 6000)
    assert len(calls["report"]) == 1                           # 同一事件只登记一次


def test_orphan_untagged_job_interrupted(env):
    calls, _ = env
    lanes = {"gpu33:1": q("o1")}
    run(env, lanes, 1e9)
    assert run(env, lanes, 1e9 + 2701)[0]["agent"] == "无标签（孤儿）"   # other 900×3
    assert calls["cancel"] == [("http://gpu33:1", "o1")]


def test_stale_lock_reported_not_reclaimed_by_default(env):
    calls, _ = env
    idle = {"queue_running": [], "queue_pending": []}
    g = {"gpu33:3": {"procs": ["python main.py ComfyUI :8191"], "util": 0}}
    reclaimed = []
    kw = dict(gpus=g, locks={"gpu33:3": True}, reclaim_fn=reclaimed.append)
    run(env, {"gpu33:3": idle}, 1e9, **kw)
    acts = run(env, {"gpu33:3": idle}, 1e9 + 1801, **kw)
    assert acts[0]["event"] == "stale_lock" and reclaimed == []
    g["gpu33:3"]["procs"].append("python train_lora.py")       # 有训练进程 → 不算过期
    assert run(env, {"gpu33:3": idle}, 1e9 + 4000, **kw) == []


def test_stale_lock_reclaim_when_enabled(env, tmp_path):
    LH.CFG.write_text(json.dumps({"stale_lock_action": "reclaim"}), encoding="utf-8")
    idle = {"queue_running": [], "queue_pending": []}
    reclaimed = []
    kw = dict(gpus={"gpu33:0": {"procs": [], "util": 0}}, locks={"gpu33:0": True}, reclaim_fn=reclaimed.append)
    run(env, {"gpu33:0": idle}, 1e9, **kw)
    assert run(env, {"gpu33:0": idle}, 1e9 + 1801, **kw)[0]["event"] == "healed" and reclaimed == ["gpu33:0"]


def test_unknown_lock_reported(env):
    calls, _ = env
    idle = {"queue_running": [], "queue_pending": []}
    run(env, {"gpu33:3": idle}, 1e9, locks={"gpu33:3": None})
    acts = run(env, {"gpu33:3": idle}, 1e9 + 901, locks={"gpu33:3": None})
    assert acts[0]["event"] == "lock_unknown" and "读不到" in calls["report"][0]


def test_disabled(env):
    LH.CFG.write_text(json.dumps({"enabled": False}), encoding="utf-8")
    assert run(env, {"gpu33:3": q("p", "PRODUCER")}, 1e9) == []
