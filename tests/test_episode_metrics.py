"""tools/master/episode_metrics.py：集级指标（METRICS_SPEC §B）。全部用临时目录夹具，不读不写真实 data/。"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load(name, rel):
    spec = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


EM = _load("episode_metrics", "tools/master/episode_metrics.py")
RUN = "fx_run"


def _w(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, str):
        p.write_text(obj, encoding="utf-8")
    elif isinstance(obj, list):
        p.write_text("".join(json.dumps(o, ensure_ascii=False) + "\n" for o in obj), encoding="utf-8")
    else:
        p.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _take(at, lane, passed, *, q1="pass", q9="untested", sim=None, items=None, text=None, age=False, ocr=False, shot=None, job=None, cid=None, seed=1):
    ev = {"per_face": [{"sim": sim}]} if sim is not None else {}
    r = {"at": at, "lane": lane, "seed": seed, "file": f"ab/x/{cid or job or shot}_{seed}.png", "passed": passed,
         "postflight": {"items": [{"id": "Q1", "status": q1, "evidence": ev}, {"id": "Q9", "status": q9}]},
         "anomaly": {"status": "pass", "reasons": ["finger_ratio"] if seed % 2 else []},
         "vlm": {"status": "pass", "items": items} if items is not None else {"status": "pass", "text": text or "1. 符合，a\n2. 不符合，b\n总结：有不符合"}}
    if age:
        r["age"] = {"status": "pass", "text": "成年"}
    if ocr:
        r["ocr"] = {"status": "pass", "text": "无"}
    if shot:
        r["compile_trace"] = {"shot": shot}
        r["pass"] = r.pop("passed")
    if job:
        r["job"] = job
    if cid:
        r["id"] = cid
    return r


def fixture_root(tmp_path: Path, *, with_cross=True) -> Path:
    root = tmp_path / "repo"
    rd = root / "data" / "pipeline" / "runs" / RUN
    _w(rd / "autoflow.json", {
        "episode": 1, "started": "2026-11-02 19:00:00",
        "stages": [{"id": "P0", "status": "ok", "decider": "code"}, {"id": "P1", "status": "reused", "decider": "code", "attempt": 2},
                   {"id": "P1G", "status": "approved", "decider": "owner"}, {"id": "P2", "status": "reused", "decider": "code", "attempt": 1},
                   {"id": "P3", "status": "reused", "decider": "code", "attempt": 1}, {"id": "P4", "status": "reused", "decider": "code", "attempt": 2},
                   {"id": "factcheck", "status": "ok", "decider": "api_model", "deviations": []}, {"id": "import", "status": "imported", "decider": "code"}],
        "agent_history": [{"step": "patch_ep01_a1", "accepted": False, "note": "没变少"}, {"step": "patch_ep01_a2", "accepted": True, "note": ""},
                          {"step": "patch_ep01_a3", "accepted": None, "note": "排队"}]})
    _w(rd / "autoflow.log", [
        {"at": "2026-11-02T19:00:00", "source": "daemon", "episode": 1, "verdict": None, "note": "开始"},
        {"at": "2026-11-02T19:30:00", "source": "daemon", "episode": 1, "verdict": "p1_review_failed", "note": "x"},
        {"at": "2026-11-02T19:40:00", "source": "cli", "episode": 1, "verdict": "owner_direction", "note": "总调度转项目方"},
        {"at": "2026-11-02T20:00:00", "source": "web", "episode": 1, "verdict": "awaiting_writer", "note": "y"},
        {"at": "2026-11-02T21:00:00", "source": "daemon", "episode": 1, "verdict": "import_failed", "note": "z"},
        {"at": "2026-11-02T21:30:00", "source": "web", "episode": 1, "verdict": "imported", "note": "ok"},
        {"at": "2026-11-02T22:00:00", "source": "cli", "episode": 2, "verdict": "owner_direction", "note": "别的集，不算"},
    ])
    _w(rd / "owner_gates.json", {"gates": {"P1": {"status": "approved", "at": "2026-11-02T20:10:00", "released_by_owner": True, "below_threshold": True}},
                                 "history": [{"at": "2026-11-02T19:50:00", "key": "P1", "action": "revise", "by": "fred"},
                                             {"at": "2026-11-02T20:10:00", "key": "P1", "action": "approve", "by": "fred"}]})
    _w(rd / "judge_p1" / "STATE.json", {"rounds": [
        {"n": 1, "passed": False, "result": {"mean": 30, "judge_ids": ["J1-fable", "J2-opus", "J3-sonnet"]}},
        {"n": 2, "passed": False, "result": {"mean": 32, "judge_ids": ["r2-fable", "r2-opus", "r2-sonnet"]}}],
        "owner_direction": {"round": 2}})
    for stem, role in (("P1_a1", "writer"), ("P1_a2", "writer"), ("P2_ep01_a1", "writer"), ("facts_ep01_a1", "reviewer"), ("patch_ep01_a1", "writer")):
        _w(rd / "writer_tasks" / f"{stem}.json", {"role": role, "episode": 1, "step": stem.rsplit("_a", 1)[0]})
        _w(rd / "writer_out" / f"{stem}.json", {"x": 1})
        _w(rd / "writer_out" / f"{stem}.json.done", "done\n" + ("model: claude-fable-5-1\n" if stem == "P1_a2" else ""))
    _w(rd / "writer_out" / "P4_ep01_a1.md", "# p4")
    _w(rd / "writer_out" / "P4_ep01_a1.md.done", "done")
    _w(rd / "writer_out" / "P1_ep02_a1.json", {"other": "episode"})
    _w(rd / "writer_tasks" / "P1_ep02_a1.json", {"role": "writer", "episode": 2})
    _w(rd / "writer_out_void" / "P1_looks_a1.void1.json", {})
    _w(rd / "_rejected_L1" / "writer_out_P1_a1.json", {})
    _w(root / "data" / "import" / "runs" / RUN / "script_v2.json", {"episodes": [{"number": 1, "shots": [{}, {}, {}]}]})
    # 资产作业
    aj = root / "data" / "pipeline" / "asset_jobs" / RUN
    _w(aj / "face-ch_a.json", {"schema": "nsfs.asset_job/1", "id": "face-ch_a", "kind": "face", "target": "ch_a", "episodes": [1], "state": "done", "attempts": 0,
                               "created_at": "2026-11-02T22:00:00", "updated_at": "2026-11-02T22:30:00", "adopted_from": "CAST-S",
                               "log": ["2026-11-02T22:00:00 接管已有的待办通知 v2cast-ch_a", "2026-11-02T22:30:00 项目方选定 ch_a#1，已登记"]})
    _w(aj / "scene-sk_x.json", {"schema": "nsfs.asset_job/1", "id": "scene-sk_x", "kind": "scene", "target": "sk_x", "episodes": [1], "state": "done", "attempts": 0,
                                "created_at": "2026-11-02T22:00:00", "updated_at": "2026-11-02T22:20:00", "adopted_from": "CAST-S",
                                "log": ["2026-11-02T22:00:00 接管已有的待办通知 v2cast-sk_x", "2026-11-02T22:20:00 项目方选定 sk_x#2，已登记"]})
    _w(aj / "meta-name-ch_a.json", {"schema": "nsfs.asset_job/1", "id": "meta-name-ch_a", "kind": "meta", "target": "ch_a", "episodes": [1], "state": "done", "attempts": 1,
                                    "created_at": "2026-11-02T22:00:00", "updated_at": "2026-11-02T22:05:00", "log": []})
    _w(aj / "sheet-ch_a-A.json", {"schema": "nsfs.asset_job/1", "id": "sheet-ch_a-A", "kind": "sheet", "target": "ch_a:A", "episodes": [1], "state": "awaiting_pick", "attempts": 2,
                                  "created_at": "2026-11-02T22:40:00", "updated_at": "2026-11-02T23:30:00",
                                  "log": ["2026-11-02T22:41:00 seed 1100: RuntimeError: preflight 不过：I4", "2026-11-02T22:41:00 没有候选过检：seed 1100: RuntimeError: preflight 不过：I4",
                                          "2026-11-02T22:50:00 重新排队（attempts 归零）：根因已修", "2026-11-02T23:30:00 3 个候选过检，已投待办通知 pick:sheet:ch_a:A"]})
    _w(aj / "sheet-ch_b-A.json", {"schema": "nsfs.asset_job/1", "id": "sheet-ch_b-A", "kind": "sheet", "target": "ch_b:A", "episodes": [2], "state": "pending", "attempts": 0,
                                  "created_at": "2026-11-03T00:00:00", "updated_at": "2026-11-03T00:00:00", "log": []})
    _w(aj / "_ready_ep01.json", {"ready": False})
    _w(root / "data" / "pipeline" / "asset_jobs" / "worker.json", {"config": {"golden": False}})
    # 候选
    _w(root / "data" / "ab" / "v2_cast" / "takes.jsonl", [
        _take("2026-11-02T21:50:00", "gpu33:0", True, cid="ch_a", sim=0.8, q9="pass", age=True, ocr=True, seed=1),
        _take("2026-11-02T21:55:00", "gpu33:1", False, cid="ch_a", sim=0.6, q9="fail", age=True, ocr=True, seed=2),
        _take("2026-11-02T21:56:00", "gpu36:0", True, cid="sk_x", q1="na", age=True, ocr=True, seed=3),
        _take("2026-11-02T21:57:00", "gpu36:0", True, cid="ch_zzz", seed=4),       # 不属于本集任何作业
    ])
    _w(root / "data" / "ab" / "v2_assets" / RUN / "sheet-ch_a-A" / "takes.jsonl", [
        _take("2026-11-02T23:00:00", "gpu33:0", False, job="sheet-ch_a-A", sim=0.7, items=[{"n": 1, "ok": True}, {"n": 2, "ok": False}], seed=5),
        _take("2026-11-02T23:10:00", "gpu33:0", True, job="sheet-ch_a-A", sim=0.9, q9="pass", items=[{"n": 1, "ok": True}, {"n": 2, "ok": True}], seed=6),
    ])
    # PRODMERGE-O：首帧只记 takes.json 一本账（producer 主干）；共用验收结论在 postflight 的 QB 项里
    def _frame(n, at, ok, sim, seed):
        t = _take(at, "gpu33:3", ok, sim=sim, seed=seed)
        qb = {"id": "QB", "status": "pass" if ok else "fail", "evidence": {"anomaly": t["anomaly"], "bundle": t["vlm"]}}
        return {"n": n, "stage": "image", "seed": seed, "created_at": at, "producer": {"lane": "gpu33:3"},
                "postflight": {"ok": ok, "items": t["postflight"]["items"] + [qb]}}
    _w(root / "data" / "renders" / RUN / "ep01" / "S1" / "takes.json",
       {"takes": [_frame(1, "2026-11-02T20:30:00", False, 0.75, 7), _frame(2, "2026-11-02T20:45:00", True, 0.85, 8)]})
    _w(root / "data" / "renders" / RUN / "ep02" / "S1" / "takes.json",
       {"takes": [_frame(1, "2026-11-02T20:50:00", True, None, 9)]})
    if with_cross:
        _w(root / "data" / "pipeline" / "issues.jsonl", [
            {"id": "ISS-1", "event": "open", "time": "2026-11-02 23:00:00", "run": RUN, "episode": 1, "who": "A", "blocking": True, "what": "x"},
            {"id": "ISS-2", "event": "open", "time": "2026-11-02 23:01:00", "run": RUN, "episode": 1, "who": "B", "blocking": False, "what": "y"},
            {"id": "ISS-1", "event": "close", "time": "2026-11-02 23:30:00", "sop_updated": True},
            {"id": "ISS-9", "event": "open", "time": "2026-11-02 23:02:00", "run": "other", "episode": 1, "who": "C", "blocking": True, "what": "z"},
        ])
        _w(root / "data" / "ops" / "api_lifecycle.jsonl", [
            {"at": "2026-11-02T18:00:00", "event": "started", "by": "项目方"},                 # 窗外
            {"at": "2026-11-02T21:10:00", "event": "started", "by": "项目方"},
            {"at": "2026-11-02T21:20:00", "event": "started", "by": "pytest"},
            {"at": "2026-11-02T21:25:00", "event": "started", "by": "X-sim"},
            {"at": "2026-11-02T22:10:00", "event": "started", "by": "总调度（恢复）", "managed": True},
            {"at": "2026-11-02T22:11:00", "event": "api_startup"},
        ])
        _w(root / "data" / "debug" / "lane_loans.jsonl", [
            {"ts": "2026-11-02T20:00:00", "ev": "lend", "lane": "gpu33:3", "to": "PROMPTFIX", "by": "PROMPTFIX", "until": "2026-11-02T21:00:00"},
            {"ts": "2026-11-02T21:00:00", "ev": "release", "lane": "gpu33:3"},
            {"ts": "2026-11-02T21:40:00", "ev": "hold", "lane": "gpu33:0", "by": "CAST-S", "why": "候选", "expires_at": "2026-11-02T23:40:00"},
            {"ts": "2026-11-02T22:00:00", "ev": "release", "lane": "gpu33:0", "by": "CAST-S", "cleared": ["_temp_holds"]},
            {"ts": "2026-11-02T22:40:00", "ev": "hold", "lane": "gpu33:0", "by": "ASSET-WORKER", "why": "sheet", "expires_at": "2026-11-03T00:10:00"},
            {"ts": "2026-11-02T23:10:00", "ev": "release", "lane": "gpu33:0", "by": "ASSET-WORKER", "cleared": ["_temp_holds"]},
            {"ts": "2026-11-02T23:10:05", "ev": "release_noop", "lane": "gpu33:0", "by": "ASSET-WORKER", "cleared": []},
            {"ts": "2026-11-02T23:20:00", "ev": "hold", "lane": "gpu33:1", "by": "ASSET-WORKER", "why": "sheet2", "expires_at": "2026-11-03T05:00:00"},   # 没 release：到窗尾
        ])
        _w(root / "data" / "state" / "netfix" / "partition.json", {"lanes": {"gpu33": ["gpu33:0", "gpu33:1", "gpu33:3"], "gpu36": ["gpu36:0"]}})
        _w(root / "docs" / "master" / "V2_LIVE.md", "标题\n01:00 X：手工重排了一次\n01:10 Y：正常\n01:20 Z：项目方接手\n")
    return root


def test_collect_model_calls_and_interventions(tmp_path):
    root = fixture_root(tmp_path)
    s = EM.collect(root, RUN, 1)
    mc = s["model_calls"]
    assert mc["writer"]["calls"] == 5 and mc["reviewer"]["calls"] == 1           # P1×2 P2 patch P4.md；facts
    assert mc["writer"]["voided"] == 2 and mc["writer"]["calls_total_with_voided"] == 7
    assert mc["writer"]["models"] == {"unknown": 4, "claude-fable-5-1": 1}        # .done 第 2 行 model: 被读到
    assert "model" in mc["reviewer"] and mc["reviewer"]["model"] is None
    assert mc["judges"]["calls"] == 6 and mc["judges"]["by_model"] == {"fable": 2, "opus": 2, "sonnet": 2}
    assert mc["judges"]["released_by_owner"] is True
    assert mc["agent_calls_total"] == 12
    # VLM：cast 3 条各 (vlm 1 + age 1 + ocr 1 + Q9 判了的 1) → 4+4+3 = 11；sheet 2 条 → 1 + 2；golden 2 条 → 1 + 1 ⇒ 16
    assert mc["vlm"]["calls"] == 16 and mc["vlm"]["calls_estimated"] is True
    it = s["interventions"]
    assert it["manual_cli"] == 1 and it["rejected_deliverables"] == 1 and it["requeue_after_fix"] == 1
    assert it["api_restarts"] == 2 and it["manual_lane_holds"] == 2 and it["total"] == 7     # PROMPTFIX lend + CAST-S hold；ASSET-WORKER 不算
    assert it["issues"] == {"opened": 2, "blocking": 1, "closed": 1, "by_who": {"A": 1, "B": 1}}
    assert it["v2_live_mentions"]["lines"] == 2
    assert s["shots"] == 3


def test_collect_time_success_quality(tmp_path):
    root = fixture_root(tmp_path)
    s = EM.collect(root, RUN, 1)
    t = s["time"]
    assert t["writing_p1"]["seconds"] == 70 * 60 and t["writing_p2_to_import"]["seconds"] == 80 * 60
    assert t["owner_wait_writing"]["seconds"] == 10 * 60                               # 19:40 owner_direction → 19:50 revise
    assert t["stage_a_assets"]["status"] == "in_progress" and t["stage_a_assets"]["end"] is None and t["stage_a_assets"]["elapsed_so_far_s"] > 0
    a = t["owner_wait_stage_a"]
    assert a["sum_s"] == 30 * 60 + 20 * 60 and a["seconds"] == 30 * 60                   # 并行等待只算并集
    assert a["open"] == 1 and any(seg["open"] for seg in a["segments"])
    assert t["stage_b_golden"]["status"] == "done" and t["stage_b_golden"]["seconds"] == 15 * 60 and t["stage_b_golden"]["source"] == "takes.json"
    w = s["success"]["writing"]
    assert w["p1_judges"]["rounds"] == 2 and w["p1_judges"]["first_pass"] is False and w["p1_judges"]["released_by_owner_below_threshold"] is True
    assert w["P2"]["first_pass"] is True and w["P4"]["first_pass"] is False
    assert w["patch_loop"] == {"attempts": 2, "accepted": 1, "first_pass": False}
    assert w["import"] == {"failed_attempts": 1, "first_pass": False}
    im = s["success"]["images"]
    assert im["cast_face"]["takes"] == 2 and im["scene"]["takes"] == 1 and im["sheet"]["takes"] == 2 and im["golden"]["takes"] == 2
    assert im["all"]["takes"] == 7 and im["all"]["passed"] == 4 and im["all"]["takes_per_pass"] == 1.75
    assert im["sheet"]["preflight_blocked_attempts"] == 1 and im["all"]["preflight_blocked_attempts"] == 1
    q = s["quality"]
    assert q["all"]["q1_identity"]["cos_n"] == 6 and abs(q["all"]["q1_identity"]["cos_mean"] - round((0.8 + 0.6 + 0.7 + 0.9 + 0.75 + 0.85) / 6, 4)) < 1e-6
    assert q["sheet"]["vlm_items"] == {"ok": 3, "total": 4, "pass_rate": 0.75}
    assert q["golden"]["vlm_items"]["pass_rate"] == 0.5                                     # 文本行首 符合 / 不符合
    assert q["all"]["anomaly"]["with_reasons"] == 4
    assert q["hollywood"]["mean"] is None and any(n["key"] == "quality.hollywood" for n in s["nulls"])
    aj = s["success"]["asset_jobs"]
    assert aj["n"] == 4 and aj["by_kind"]["sheet"]["first_try_done"] == 0 and aj["by_kind"]["meta"]["first_try_done"] == 1


def test_automation_and_gpu(tmp_path):
    root = fixture_root(tmp_path)
    s = EM.collect(root, RUN, 1)
    au = s["automation"]
    # 写作 8 段（1 owner）+ 作业 4（face/scene 由 agent 出候选 → agent 2，meta/sheet system 2）+ 挑选 3（owner）+ 介入 7（agent 6 + 项目方手起 1）
    assert au["total_steps"] == 22 and au["by_actor"] == {"system": 7 + 2, "owner": 1 + 3 + 1, "agent": 2 + 6}
    assert au["ratio"] == round(9 / 22, 4)
    g = s["gpu"]
    assert g["lanes"] == ["gpu33:0", "gpu33:1", "gpu33:3", "gpu36:0"]
    assert g["window"]["start"] == "2026-11-02T20:30:00"                                    # 金样试跑比阶段 A 早
    end = g["window"]["end"]
    assert end == s["time"]["total_wall"]["end"]
    # gpu33:3：lend 20:00→21:00 裁到窗 20:30 → 1800 s；gpu33:0：CAST-S 21:40→22:00 + ASSET-WORKER 22:40→23:10 = 3000 s
    assert g["per_lane"]["gpu33:3"]["busy_s"] == 1800 and g["per_lane"]["gpu33:0"]["busy_s"] == 3000
    assert g["per_lane"]["gpu33:0"]["by_actor_s"] == {"CAST-S": 1200, "ASSET-WORKER": 1800}
    assert g["per_lane"]["gpu33:1"]["busy_s"] == EM.secs(EM.ts("2026-11-02T23:20:00"), EM.ts(end))   # 没 release 的 hold 算到窗尾
    assert g["per_lane"]["gpu36:0"]["busy_s"] == 0
    assert g["overall"] == round(sum(l["busy_s"] for l in g["per_lane"].values()) / (g["window_s"] * 4), 4)


def test_nulls_when_sources_missing(tmp_path):
    root = fixture_root(tmp_path, with_cross=False)
    s = EM.collect(root, RUN, 1)
    keys = {n["key"] for n in s["nulls"]}
    assert {"interventions.api_restarts", "interventions.manual_lane_holds", "interventions.v2_live_mentions", "gpu.lanes", "gpu.busy"} <= keys
    assert s["interventions"]["api_restarts"] == 0 and s["gpu"]["overall"] is None
    s2 = EM.collect(root, RUN, 7)                                                           # 没有这一集
    assert any(n["key"] == "writing" for n in s2["nulls"]) and s2["time"]["writing_p1"]["seconds"] is None
    assert s2["success"]["images"]["all"]["takes"] == 0 and s2["time"]["stage_a_assets"]["status"] == "no_jobs"


def test_write_summary_compare_and_html(tmp_path):
    root = fixture_root(tmp_path)
    s1 = EM.collect(root, RUN, 1)
    outs = EM.write_summary(root, RUN, 1, s1)
    assert outs["json"] == root / "data" / "pipeline" / "runs" / RUN / "metrics" / "ep01_summary.json" and outs["json"].is_file()
    html = outs["html"].read_text(encoding="utf-8")
    assert outs["html"].parent == root / "data" / "review_pages" / "metrics" and "集级指标" in html and "quality.hollywood" in html
    s2 = json.loads(json.dumps(s1))
    s2["episode"] = 2
    s2["model_calls"]["writer"]["calls"] = 2
    s2["time"]["writing_p1"]["h"] = 9.9
    s2["automation"]["ratio"] = 0.9
    s2["quality"]["hollywood"]["mean"] = None
    EM.write_summary(root, RUN, 2, s2)
    out, rows = EM.write_compare(root, RUN, 1, 2)
    by = {r["path"]: r for r in rows}
    assert by["model_calls.writer.calls"]["verdict"] == "better" and by["model_calls.writer.calls"]["delta"] == -3
    assert by["time.writing_p1.h"]["verdict"] == "worse"
    assert by["automation.ratio"]["verdict"] == "better"
    assert by["quality.hollywood.mean"]["verdict"] == "n/a"
    assert by["model_calls.reviewer.calls"]["verdict"] == "same"
    assert out.name == f"{RUN}_ep01_vs_ep02.html" and "更好" in out.read_text(encoding="utf-8")
    assert (root / "data" / "pipeline" / "runs" / RUN / "metrics" / "compare_ep01_ep02.json").is_file()
    try:
        EM.write_compare(root, RUN, 1, 3)
    except FileNotFoundError as e:
        assert "ep03" in str(e)
    else:
        raise AssertionError("缺 summary 应报错")


def test_hollywood_read_only_from_ledger(tmp_path):
    """好莱坞分只读 hollywood_tick 写的账本（总调度 1c46 ①：episode_metrics 不现场跑看图）"""
    root = fixture_root(tmp_path)
    P = EM.Paths(root, RUN)
    assert not hasattr(EM, "hollywood_score") and not hasattr(EM, "HOLLYWOOD_RUBRIC")
    _w(P.hollywood(1), [
        {"file": "ab/x/a.png", "source": "golden", "model": "fake-vlm", "scores": {"composition": 7, "lighting": 8, "texture": 6, "performance": 7, "consistency": 9}, "mean": 7.4},
        {"file": "ab/x/b.png", "source": "sheet", "model": "fake-vlm", "scores": {"composition": 5, "lighting": 5, "texture": 5, "performance": 5, "consistency": 5}, "mean": 5.0},
        {"file": "ab/x/c.png", "source": "sheet", "error": "看图模型输出不是 JSON"},
    ])
    s = EM.collect(root, RUN, 1)
    h = s["quality"]["hollywood"]
    assert h["n"] == 2 and h["mean"] == 6.2 and h["by_item"]["consistency"] == 7.0 and h["by_source"] == {"golden": 7.4, "sheet": 5.0}
    assert h["failed_attempts"] == 1 and h["calls"] == 3 and h["models"] == ["fake-vlm"]
    assert s["model_calls"]["hollywood_vlm"]["calls"] == 3
    assert not any(n["key"] == "quality.hollywood" for n in s["nulls"])
    assert "6.2" in EM.render_single(s)


def test_main_cli(tmp_path, capsys):
    root = fixture_root(tmp_path)
    assert EM.main(["--run", RUN, "--episode", "1", "--root", str(root), "--no-html"]) == 0
    out = capsys.readouterr().out
    assert "agent 调用" in out and "json:" in out and "html:" not in out
    assert EM.main(["compare", "--run", RUN, "--a", "1", "--b", "1", "--root", str(root)]) == 0
    assert "对比页" in capsys.readouterr().out
