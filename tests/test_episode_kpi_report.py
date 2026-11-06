"""W-KPI 11-06：每集耗时报告 tools/master/episode_kpi_report.py（L-205）。全部用假日志 + 临时目录，不连服务器。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
from datetime import datetime
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def _load(rel: str, name: str):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


K = _load("tools/master/episode_kpi_report.py", "episode_kpi_report_t")
RUN, EP = "fakerun", 1
D = "2026-11-06"


def _t(hms: str) -> str:
    return f"{D}T{hms}"


def _epoch(hms: str) -> float:
    return datetime.fromisoformat(_t(hms)).replace(tzinfo=K.JST).timestamp()


CHECKLIST = """## 清单
| # | 段 | 步骤 | 输入 → 输出 | 完成标准 | 目标 | 超时 → 动作 |
|---|---|---|---|---|---|---|
| 1 | 准备 | 导入 | a | b | ≤ 1 min | x |
| 2 | 准备 | 同步 | a | b | ≤ 30 s | x |
| 3 | 准备 | 提示词 | a | b | ≤ 1 min | x |
| 4 | ① | 首帧 | a | b | 每张 ≤ 2× 预计（turbo 60 s / base35 330 s）；整集 ≤ 10 min（8 步）/ ≤ 20 min（35 步） | x |
| 5 | ① | 尾帧 | a | b | 整集 ≤ 8 min | x |
| 6 | ① | 审图 | a | b | 每张 ≤ 40 s | x |
| 7 | ①→② | 切段 | a | b | ≤ 2 min | x |
| 8 | ② | 视频 | a | b | 每段 ≤ 2× 预计（≈ 5 min → 上限 10 min）；整集 16 镜 ≤ 15 min | x |
| 9 | ② | 打分 | a | b | 每段 ≤ 60 s | x |
| 10 | ②→③ | 切段 | a | b | ≤ 2 min | x |
| 11 | ③ | 合成 | a | b | ≤ 8 min | x |
| 12 | ③ | 拉回 | a | b | ≤ 3 min | x |
| 13 | ③ | 复盘 | a | b | ≤ 1 min | x |

预算合计 … 每集总预算 ≤ 50 min。
"""


def _producer_rows():
    """两镜 S1 / S2：S1 首帧一次过；S2 首帧第一版契约没过（FL）重出后过；S2 尾帧兜底；起点前 S1 尾帧已复核通过。
    还有一次部署暂停 60 s、一条 infra_error、一次 sop_gate_block 挡住 S2 尾帧派单"""
    R = []

    def ev(hms, e, **kw):
        R.append({"ts": _t(hms), "ev": e, **kw})

    ev("09:00:00", "dispatch", obj="first:ep01-S1", lane="gpu33:0", attempt=1)           # 早先尝试（背景）
    ev("09:05:00", "rendered", obj="first:ep01-S1", lane="gpu33:0", take=1, render_s=300, gpu_s=250)
    ev("09:06:00", "content_fail", obj="first:ep01-S1", blocking=["Q1"], contract_s=50)
    ev("09:30:00", "master_approve", obj="last:ep01-S1", take=3, by="PS-MASTER")           # 起点前已定下
    ev("09:58:00", "imported_staged", path="staging/P4_ep01.md", note="导入稿", episodes=[1])
    ev("10:00:00", "regen", obj="first:ep01-S1", reason="L-204 全集重出", by="PS-MASTER")
    ev("10:00:00", "regen", obj="first:ep01-S2", reason="L-204 全集重出", by="PS-MASTER")
    ev("10:01:00", "dispatch", obj="first:ep01-S1", lane="gpu33:0", attempt=1)            # 起点
    ev("10:01:00", "dispatch", obj="first:ep01-S2", lane="gpu33:1", attempt=1)
    ev("10:02:00", "pause", by="DEPLOY_ATOMIC", reason_kind="deploy", note="部署")
    ev("10:03:00", "resume", by="DEPLOY_ATOMIC", note="部署完成")
    ev("10:04:00", "infra_error", obj="first:ep01-S2", lane="gpu36:0", error="ComfyUnavailable", backoff_s=30)
    ev("10:06:00", "rendered", obj="first:ep01-S1", lane="gpu33:0", take=2, render_s=300, gpu_s=250)
    ev("10:07:00", "passed", obj="first:ep01-S1", take=2, contract_s=60)
    ev("10:07:00", "rendered", obj="first:ep01-S2", lane="gpu33:1", take=2, render_s=360, gpu_s=300)
    ev("10:09:00", "content_fail", obj="first:ep01-S2", blocking=["FL", "Q1"], contract_s=120, why="契约没过")
    ev("10:10:00", "dispatch", obj="first:ep01-S2", lane="gpu33:1", attempt=2, rung="第 2 次：换 seed")
    ev("10:15:00", "rendered", obj="first:ep01-S2", lane="gpu33:1", take=3, render_s=300, gpu_s=250)
    ev("10:16:00", "passed", obj="first:ep01-S2", take=3, contract_s=60)
    ev("10:16:30", "sop_gate_block", obj="last:ep01-S2", why="SOP 闸门：等审图")
    ev("10:20:00", "dispatch", obj="last:ep01-S2", lane="gpu33:3", attempt=1)
    ev("10:25:00", "rendered", obj="last:ep01-S2", lane="gpu33:3", take=1, render_s=300, gpu_s=250)
    ev("10:26:00", "content_fail", obj="last:ep01-S2", blocking=["FL"], contract_s=60)
    ev("10:30:00", "last_unavailable", obj="last:ep01-S2", fallback="i2va", why="尾帧退回只给首帧")
    return R


def _vstate():
    return {"host": "gpu36", "shots": {
        "ep01-S1": {"status": "done", "chosen": "v1", "renders": [
            {"variant": "v1", "recipe": "i2va", "lane": "gpu36:0", "t_sub": _epoch("10:10:00"), "t_done": _epoch("10:17:00"), "gpu_s": 400,
             "state": "scored", "score": {"verdict": "pass", "labels": []}}]},
        "ep01-S2": {"status": "done", "chosen": "s2", "renders": [
            {"variant": "v1", "recipe": "i2va", "lane": "gpu36:1", "t_sub": _epoch("10:31:00"), "t_done": _epoch("10:38:00"), "gpu_s": 400,
             "state": "scored", "score": {"verdict": "fail", "labels": ["多肢"]}},
            {"variant": "s2", "recipe": "i2va", "lane": "gpu36:1", "t_sub": _epoch("10:39:00"), "t_done": _epoch("10:46:00"), "gpu_s": 400,
             "state": "scored", "score": {"verdict": "pass", "labels": []}}]}}}


VIDGEN = """10:09:00 START vidgen gpu36 lanes ['gpu36:0', 'gpu36:1'] lane_mode normal
10:10:00 SUBMIT ep01-S1 v1 i2va 123 gpu36:0 abc
10:17:00 DONE ep01-S1 v1 gpu36:0 420.0s
10:17:30 SCORE ep01-S1 v1 PASS mean 2.0 J4 1.1
10:17:30 SHOT_PASS ep01-S1 v1 renders=1
10:38:00 DONE ep01-S2 v1 gpu36:1 420.0s
10:38:40 SCORE ep01-S2 v1 多肢 mean 2.5
10:46:00 DONE ep01-S2 s2 gpu36:1 420.0s
10:48:00 SCORE ep01-S2 s2 PASS mean 2.0
10:48:00 SHOT_PASS ep01-S2 s2 renders=2
"""

NIGHT = """11-06 10:50:00 RUN fakerun data/pipeline/runs/fakerun/video
11-06 10:50:30 EP_RESOLVED ep01 {'ep01-S1': 'done', 'ep01-S2': 'done'}
11-06 10:51:00 proxies ep01 {"ep": 1}
11-06 10:53:00 assemble ep01 0 ok
11-06 10:54:00 register_takes 1 Traceback json.decoder.JSONDecodeError: Expecting value
11-06 10:58:00 director ep01 0 {"post": "/srv/repo/data/episodes/fakerun/ep01_v3_post.mp4"}
11-06 10:58:30 RETRO ep01 {"episode": 1}
"""


def _night_state():
    return {"eps": {"1": {"host": "gpu36", "status": "assembled", "final": "/srv/repo/data/episodes/fakerun/ep01_v3_post.mp4",
                          "finalized": _epoch("10:58:30"), "assembled_n": 3}}}


@pytest.fixture
def world(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "gpu33__producer_log.jsonl").write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in _producer_rows()), encoding="utf-8")
    (raw / "gpu36__producer_log.jsonl").write_text("", encoding="utf-8")
    (raw / "gpu36__state.json").write_text(json.dumps(_vstate()), encoding="utf-8")
    (raw / "gpu33__state.json").write_text(json.dumps({"host": "gpu33", "shots": {}}), encoding="utf-8")
    (raw / "gpu36__vidgen.log").write_text(VIDGEN, encoding="utf-8")
    (raw / "gpu36__night.log").write_text(NIGHT, encoding="utf-8")
    (raw / "gpu36__night_state.json").write_text(json.dumps(_night_state()), encoding="utf-8")
    (raw / "gpu33__night_state.json").write_text(json.dumps({"eps": {}}), encoding="utf-8")
    (raw / "gpu36__takes_ep01.txt").write_text('=== data/renders/fakerun/ep01/S1/takes.json\n{"active": {"image": 2, "video": 1}, "n": 3, "stages": [["image", 1]]}\n', encoding="utf-8")
    lap = tmp_path / "laptop"
    (lap / "data/pipeline/idle_watch").mkdir(parents=True)
    (lap / "data/brain").mkdir(parents=True)
    (lap / "data/episodes/fakerun").mkdir(parents=True)
    (lap / f"data/producer/runs/{RUN}").mkdir(parents=True)
    (lap / f"data/producer/runs/{RUN}/log.jsonl").write_text("", encoding="utf-8")
    idle = "\n".join(f"{D} 10:{m:02d}:00+09:00 idle=['gpu33:3'] work=ready3/video{{'gpu33': 0, 'gpu36': 1}}/assets0 probe_err=[] acts=[]" for m in range(17, 20))
    (lap / "data/pipeline/idle_watch/events.log").write_text(idle + f"\n{D} 10:19:30+09:00 ACT night_once gpu36 可派视频 1 镜而道空 -> rc=0\n", encoding="utf-8")
    (lap / "data/brain/decisions.jsonl").write_text(json.dumps({"at": f"{D} 10:30:00+09:00", "t": _epoch("10:30:00"), "by": "BRAIN", "kind": "no_action", "dry": True, "result": "x"}) + "\n", encoding="utf-8")
    final = lap / "data/episodes/fakerun/ep01_v3_post.mp4"
    final.write_bytes(b"x" * 10)
    import os
    os.utime(final, (_epoch("11:00:00"), _epoch("11:00:00")))
    cl = tmp_path / "CHECKLIST.md"
    cl.write_text(CHECKLIST, encoding="utf-8")
    return {"raw": raw, "laptop": lap, "checklist": cl, "out": tmp_path / "kpi", "docs": tmp_path / "docs"}


def _run(world, **kw):
    return K.run_report(RUN, EP, raw=world["raw"], checklist=world["checklist"], out_dir=world["out"], docs_dir=world["docs"],
                        laptop=world["laptop"], until=_t("11:05:00"), log=lambda *a: None, **kw)


# ---------------------------------------------------------------- 预算
def test_budget_from_checklist_base_and_turbo():
    b = K.parse_budget(CHECKLIST, "base")
    assert b["import_probe"] == 150 and b["first_frames"] == 1200 and b["last_frames"] == 480
    assert b["videos"] == 900 and b["assembly"] == 480 and b["delivery"] == 180 and b["episode"] == 3000
    assert b["per_image"] == 660 and b["per_video"] == 600 and b["score_image"] == 40 and b["score_video"] == 60
    assert b["notes"] == []
    t = K.parse_budget(CHECKLIST, "turbo")
    assert t["first_frames"] == 600 and t["per_image"] == 120


def test_budget_fallback_when_checklist_missing():
    b = K.parse_budget(None, "base")
    assert b["episode"] == 3000 and b["first_frames"] == 1200 and b["notes"]
    b2 = K.parse_budget("# 没有表\n", "base")
    assert b2["first_frames"] == 1200 and any("first_frames" in n for n in b2["notes"])


# ---------------------------------------------------------------- 起点
def test_find_start_anchors(world):
    src = K.load_sources(RUN, EP, world["raw"], laptop=world["laptop"])
    rows = K.merge_producer(src, EP)
    st, info = K.find_start(rows, EP, "regen")
    assert st == datetime.fromisoformat(_t("10:01:00")) and info["anchor_ev"].startswith("regen")
    st2, _ = K.find_start(rows, EP, "import")
    assert st2 == datetime.fromisoformat(_t("10:01:00"))
    st3, info3 = K.find_start(rows, EP, "first-dispatch")
    assert st3 == datetime.fromisoformat(_t("09:00:00")) and "第一次派单" in info3["anchor_ev"]


# ---------------------------------------------------------------- 整体
def test_report_stages_and_outputs(world):
    res = _run(world)
    assert not res.get("error")
    s = res["stages"]
    assert s["import_probe"]["start"] == datetime.fromisoformat(_t("09:58:00")) and s["import_probe"]["actual_s"] == 180
    # 首帧：10:01 起 → S2 第二版过 10:16 止
    assert s["first_frames"]["status"] == "done" and s["first_frames"]["end"] == datetime.fromisoformat(_t("10:16:00"))
    # 尾帧：S1 起点前已复核通过（不算未定）、S2 兜底 i2va → 全定
    assert s["last_frames"]["status"] == "done" and s["last_frames"]["pending"] == []
    assert res["per_frame"]["last:ep01-S1"]["settled_by"].endswith("（起点前）")
    assert res["per_frame"]["last:ep01-S2"]["fallback"] == "i2va"
    # 视频：S1 SHOT_PASS 10:17:30、S2 SHOT_PASS 10:48 → done
    assert s["videos"]["status"] == "done" and s["videos"]["end"] == datetime.fromisoformat(_t("10:48:00"))
    assert res["videos_summary"]["submitted"] == 3 and res["videos_summary"]["fail"] == 1
    # 合成：EP_RESOLVED 10:50:30 → RETRO 10:58:30；拉回：本机成片 mtime 11:00
    assert s["assembly"]["status"] == "done" and s["assembly"]["actual_s"] == 480 and s["assembly"]["host"] == "gpu36"
    assert s["delivery"]["status"] == "done" and s["delivery"]["end"] == datetime.fromisoformat(_t("11:00:00"))
    assert res["episode_status"] == "done" and res["elapsed_s"] == 59 * 60
    assert res["episode_overrun_s"] == 9 * 60
    # 文件
    out = world["out"]
    assert (out / "ep01_kpi.json").exists() and (out / "latest.json").exists() and (world["docs"] / "KPI_fakerun_ep01.md").exists()
    latest = json.loads((out / "latest.json").read_text(encoding="utf-8"))
    assert latest["status"] == "done" and latest["elapsed_min"] == 59.0 and latest["overrun_min"] == 9.0
    assert sum(latest["attribution_min"].values()) == 9
    assert set(latest["stages"]) == set(K.STAGES)
    md = (world["docs"] / "KPI_fakerun_ep01.md").read_text(encoding="utf-8")
    assert "## 1. 阶段耗时 vs 预算" in md and "| 首帧 |" in md and "归因证据" in md


def test_attribution_sums_and_evidence(world):
    res = _run(world)
    at = res["attribution"]
    for k, s in res["stages"].items():
        alloc = at["per_stage"][k]["alloc_min"]
        assert sum(alloc.values()) == int(round((s.get("overrun_s") or 0) / 60)), k
        assert set(alloc) == set(K.CATS)
    # 首帧超 (15-20) → 0；尾帧 10:20→10:30 = 10 min vs 8 → 2 min：S2 尾帧被 sop_gate 挡 → 逻辑；契约没过重出 → 检测
    ff = at["per_stage"]["last_frames"]
    texts = {c: " ".join(e["text"] for e in ff["evidence"][c]) for c in K.CATS}
    assert "闸门" in texts["逻辑"] and "sop_gate_block" in texts["逻辑"]
    # 视频超 (38-15)=23 min：S2 v1 没过重出 → 检测
    vv = at["per_stage"]["videos"]
    assert any("重出" in e["text"] for e in vv["evidence"]["检测"])
    # 代码：暂停窗 60 s + infra_error 退避 + night register_takes 报错
    code_texts = " ".join(e["text"] for c in at["per_stage"].values() for e in c["evidence"]["代码"])
    assert "暂停派单 60 s" in code_texts and "infra_error" in code_texts and "register_takes" in code_texts
    # 整集：超 9 min 全部分掉
    assert sum(at["episode"]["alloc_min"].values()) == 9


def test_lane_busy_union_and_idle(world):
    res = _run(world)
    lb = res["lane_busy"]
    assert lb["gpu33:0"]["n_first"] == 1 and lb["gpu33:0"]["first"] == 300 and lb["gpu33:0"]["util"] <= 100
    assert lb["gpu33:1"]["n_first"] == 2 and lb["gpu33:1"]["busy_s"] == 360 + 300
    assert lb["gpu36:1"]["n_video"] == 2 and lb["gpu36:1"]["video"] == 840
    assert res["idle_lanes"] == {"gpu33:3": 3}
    assert any("night_once" in a["text"] for a in res["idle_acts"])
    assert res["brain_actions"] and res["brain_actions"][0]["kind"] == "no_action"
    assert "gpu33:3" in res["idle_with_work_s"]


def test_waits(world):
    res = _run(world)
    w = res["waits"]
    r2 = [x for x in w["ready_to_dispatch"] if x["obj"] == "last:ep01-S2"][0]
    assert r2["wait_s"] == 240 and r2["blocked"] and "sop_gate_block" in r2["blocked"]
    p1 = [x for x in w["pair_to_submit"] if x["shot"] == "S1"][0]
    assert p1["wait_s"] == 180            # 首帧过 10:07 → 提交 10:10（尾帧起点前已定）
    p2 = [x for x in w["pair_to_submit"] if x["shot"] == "S2"][0]
    assert p2["wait_s"] == 60 and "兜底" in p2["note"]     # 兜底 10:30 → 提交 10:31
    assert w["settled_to_assembly"]["wait_s"] == 150     # 10:48:00 → 10:50:30


def test_incidents_and_cycles(world):
    res = _run(world)
    kinds = res["incident_counts"]
    assert kinds.get("pause:deploy") == 1 and kinds.get("infra_error") == 1 and kinds.get("night_restart") == 1 and kinds.get("register_takes") == 1
    pause = [i for i in res["incidents"] if i["kind"] == "pause:deploy"][0]
    assert pause["pause_s"] == 60
    assert len(res["cycles"]) == 1 and res["cycles"][0]["end_ev"] == "RETRO" and res["cycles"][0]["resolved"]["ep01-S1"] == "done"
    assert res["context_before_start"]["dispatches"] == 1 and res["context_before_start"]["rendered"] == 1
    assert res["takes"]["gpu36"]["S1"]["n"] == 3


def test_running_episode_open_stages(world):
    """截至时间卡在视频中途：视频 / 合成未完成，实际用时按截至算，阶段 open"""
    res = K.run_report(RUN, EP, raw=world["raw"], checklist=world["checklist"], out_dir=world["out"], docs_dir=world["docs"],
                       laptop=world["laptop"], until=_t("10:40:00"), log=lambda *a: None, write_docs=False)
    s = res["stages"]
    assert res["episode_status"] == "running" and s["videos"]["status"] == "running" and s["videos"]["open"]
    assert s["videos"]["pending"] == ["S2"] and s["videos"]["actual_s"] == 30 * 60
    assert s["assembly"]["status"] == "not_started" and s["delivery"]["status"] == "not_started"
    assert not (world["docs"] / "KPI_fakerun_ep01.md").exists()
    assert sum(res["attribution"]["episode"]["alloc_min"].values()) == int(round(res["episode_overrun_s"] / 60))


def test_manual_start_and_no_dispatch(world):
    res = K.run_report(RUN, EP, raw=world["raw"], checklist=world["checklist"], out_dir=world["out"], docs_dir=world["docs"],
                       laptop=world["laptop"], start=_t("10:10:00"), until=_t("11:05:00"), log=lambda *a: None, write_docs=False)
    assert res["anchor"]["anchor"] == "manual" and res["start"] == datetime.fromisoformat(_t("10:10:00"))
    # 起点前已过的 S1 首帧按“起点前定下”算，不算未定
    assert res["stages"]["first_frames"]["pending"] == []
    res2 = K.run_report(RUN, 9, raw=world["raw"], checklist=world["checklist"], out_dir=world["out"], docs_dir=world["docs"],
                        laptop=world["laptop"], until=_t("11:05:00"), log=lambda *a: None, write_docs=False)
    assert res2.get("error") and "没有本集派单" in res2["error"]
    assert "error" in json.loads((world["out"] / "latest.json").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 拉取（假 runner：网络抖动 → 退避重试由 run_retry 负责，这里只验缓存与失败处理）
def test_fetch_uses_cache_on_failure(tmp_path: Path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / "gpu33__night.log").write_text("old", encoding="utf-8")
    calls = []

    def runner(host, cmd):
        calls.append((host, cmd))
        if "night.log" in cmd:
            return subprocess.CompletedProcess(["ssh"], 255, b"", b"down")
        if cmd.startswith("for f in"):
            return subprocess.CompletedProcess(["ssh"], 0, b"=== data/renders/r/ep01/S1/takes.json\n{\"active\": {}, \"n\": 1, \"stages\": []}\n", b"")
        return subprocess.CompletedProcess(["ssh"], 0, b"{}", b"")

    msgs = []
    rc = K.fetch("r", 1, raw, hosts=("gpu33",), runner=runner, log=msgs.append)
    assert rc["gpu33__night.log"] == 255 and (raw / "gpu33__night.log").read_text(encoding="utf-8") == "old"
    assert any("用缓存：有" in m for m in msgs)
    assert (raw / "gpu33__producer_log.jsonl").read_bytes() == b"{}" and not (raw / "gpu33__producer_log.jsonl.part").exists()
    assert json.loads((raw / "_fetch.json").read_text(encoding="utf-8"))["rc"]["gpu33__state.json"] == 0
    assert all(c[0] == "gpu33" and (c[1].startswith("cat ") or c[1].startswith("for f in")) for c in calls)   # 只读命令
    assert K.parse_takes_dump((raw / "gpu33__takes_ep01.txt").read_text(encoding="utf-8"))["S1"]["n"] == 1


def test_fetch_runner_exception_does_not_raise(tmp_path: Path):
    def runner(host, cmd):
        raise OSError("wsl down")
    rc = K.fetch("r", 1, tmp_path / "raw", hosts=("gpu36",), runner=runner, log=lambda *a: None)
    assert all(v == 1 for v in rc.values())


# ---------------------------------------------------------------- night 钩子
def test_night_hook_is_single_guarded_nonblocking_call():
    src = (ROOT / "tools/series10_video/night.py").read_text(encoding="utf-8")
    i = src.index('log("FINALIZE_DONE"')
    seg = src[i:i + 900]
    assert "episode_kpi_report.py" in seg and "subprocess.Popen" in seg and "--quiet" in seg
    assert "except Exception" in seg and 'log("KPI_SPAWN_ERR"' in seg
    assert src.count("episode_kpi_report.py") == 1     # 只挂一处（reap_finalize）
    assert ".wait()" not in seg and "communicate(" not in seg
