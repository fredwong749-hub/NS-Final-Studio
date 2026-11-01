"""DISTILL 11-02（K-OPS-X01–X05）：策略层、统一编排器、判断清单、覆盖率。只读真实仓库，写只写 tmp_path。"""
from __future__ import annotations

import json
import shutil
import sys
import time
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "autopilot"))
import flow as FL  # noqa: E402
import policy as POL  # noqa: E402


# ---------------------------------------------------------------- K-OPS-X01 策略层
def test_policy_drift_clean():
    bad = [d for d in POL.drift_check(ROOT) if not d["ok"]]
    assert not bad, f"策略与代码不一致：{bad}"


def test_policy_refs_exist():
    assert POL.ref_check(ROOT) == []


def _fake_root(tmp_path: Path) -> Path:
    shutil.copytree(ROOT / "config" / "policies", tmp_path / "config" / "policies")
    return tmp_path


def test_drift_detects_change(tmp_path):
    root = _fake_root(tmp_path)
    (root / "tools/autopilot").mkdir(parents=True)
    (root / "tools/autopilot/producer.py").write_text("MAX_TRIES = 5\nLEASE_S = 45 * 60\n", encoding="utf-8")
    it = POL.load(root)["retry"]
    assert POL.drift_one("retry.max_content_tries", it["max_content_tries"], root)["ok"] is False
    assert POL.drift_one("retry.lease_s", it["lease_s"], root)["ok"] is True      # 45 * 60 算术常量


def test_tuple_const(tmp_path):
    root = _fake_root(tmp_path)
    (root / "tools/script_rsi").mkdir(parents=True)
    (root / "tools/script_rsi/hollywood_r5.py").write_text("COST_CAP_USD, EP_CAP_USD, NO_GAIN_STOP = 15.0, 3.0, 1\nTARGET_IMPORT = 48\n", encoding="utf-8")
    b = POL.load(root)["budget"]
    for k in ("writing_total_cap_usd", "writing_episode_cap_usd", "no_gain_stop_rounds", "import_score_min"):
        assert POL.drift_one(k, b[k], root)["ok"], k


# ---------------------------------------------------------------- 判定函数
def test_pause_overdue():
    t0 = time.time()
    iso = lambda dt: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0 - dt))  # noqa: E731
    D = POL.pause_decision
    assert D({"paused": False}, t0) is None
    # 运维暂停：到 expires_at 自动恢复；最多 180 s
    assert D({"paused": True, "paused_by": "NETFIX", "reason_kind": "line_switch", "paused_at": iso(60), "expires_at": iso(-60)}, t0) is None
    assert D({"paused": True, "paused_by": "NETFIX", "reason_kind": "line_switch", "paused_at": iso(120), "expires_at": iso(10)}, t0)["action"] == "resume"
    assert D({"paused": True, "paused_by": "NETFIX", "reason_kind": "deploy", "paused_at": iso(200), "expires_at": iso(-999)}, t0)["action"] == "resume"
    # 显式暂停：不自动恢复，超过 180 s 只告警
    assert D({"paused": True, "paused_by": "master", "reason_kind": "master", "paused_at": iso(60), "expires_at": iso(-60)}, t0) is None
    assert D({"paused": True, "paused_by": "master", "reason_kind": "master", "paused_at": iso(720), "expires_at": iso(-60)}, t0)["action"] == "alert"
    assert D({"paused": True, "paused_by": "owner", "paused_at": iso(9999)}, t0)["action"] == "alert"
    # 缺字段（11-02 00:52 那次）：超过 180 s 只告警、记违规
    od = D({"paused": True, "paused_by": "NETFIX", "paused_at": iso(720)}, t0)
    assert od["action"] == "alert" and od["paused_s"] >= 700 and "缺" in od["why"]


def test_delivery_ratchet(tmp_path):
    fs = lambda t, a1=4.0, a13=True: {"total_50": t, "name": "x", "at": "2026-11-02 03:00:00", "items": {"A1": {  # noqa: E731
        "score": a1, "measured": 3, "conds": [{"id": "A1.3", "pass": a13}]}}}
    assert POL.delivery_check(fs(31), None, 0)["ok"] is True
    assert POL.delivery_check(fs(29.5), None, 0)["ok"] is False             # 低于 30
    r = POL.delivery_check(fs(33), 35, 0)
    assert r["min_line"] == 34 and r["ok"] is False                         # 历史最好 35 − 1
    assert POL.delivery_check(fs(36), 35, 1)["ok"] is False                 # 口型重出单未清
    assert POL.delivery_check(fs(36, a1=0), 35, 0)["ok"] is False
    assert POL.delivery_check(fs(36, a13=False), 35, 0)["ok"] is False
    assert POL.delivery_check(None, None, 0)["ok"] is False                 # 未测 ≠ 通过
    bp = tmp_path / "best.json"
    assert POL.update_best(bp, 1, fs(32)) == 32
    assert POL.update_best(bp, 1, fs(30)) == 32                             # 棘轮只升不降
    assert POL.update_best(bp, 1, fs(33.5)) == 33.5


def test_handback_ok():
    good = {"preflight_dryrun_ok": True, "preflight_dryrun_shots": 42, "refs_match": True, "refs_mismatch": 0, "ready": True,
            "preflight_dryrun_by": "FACTORY tools/factory/sync.py verify"}
    assert POL.handback_ok(good) == (True, [])
    ok, why = POL.handback_ok(dict(good, refs_mismatch=3))
    assert not ok and any("refs" in w for w in why)
    ok, why = POL.handback_ok(dict(good, preflight_dryrun_by="WORKFLOW resident_sync.push_required"))
    assert not ok
    ok, why = POL.handback_ok(good, server_sv="sv-20261101-01")
    assert not ok and any("min_code_sv" in w for w in why)


def test_noise_and_pick_and_post():
    assert POL.noise_stop([[40, 45], [41, 42]])["stop"] is True       # 1/2 不稳 ≥ 0.5
    assert POL.noise_stop([[40, 41], [41, 42]])["stop"] is False
    c = [{"name": "a", "score": 42, "invariants_pass": True, "p4_block_zero": True, "fact_check_zero": True},
         {"name": "b", "score": 44, "invariants_pass": False, "p4_block_zero": True, "fact_check_zero": True}]
    assert POL.pick_import(c, spent_usd=1, rounds_left=3)["pick"] is None
    assert POL.pick_import(c, spent_usd=15, rounds_left=3)["pick"] == "a"
    assert POL.pick_import([dict(c[0], score=48)])["pick"] == "a"
    assert POL.post_better({"total_50": 27.8}, {"total_50": 31.2}) is True
    assert POL.post_better({"total_50": 27.8}, None) is None
    assert POL.score_backlog_max(3, 4) == 24


# ---------------------------------------------------------------- K-OPS-X02 编排器
def test_stage_points_complete():
    assert FL.STAGE_IDS[:4] == ["brief", "chain", "script", "import"] and FL.STAGE_IDS[-1] == "delivery"   # r2：从 P0 Brief 开始
    for s in FL.STAGES:
        assert s["points"], s["id"]
        for p in s["points"] + []:
            assert p["now"] in FL.DECIDERS and p["target"] in FL.DECIDERS, p
            if p["now"] == "claude":
                assert p.get("plan"), f"{s['id']} {p['what']} 是 claude 却没有替代方案"
            if p["now"] in ("claude", "owner"):
                assert p.get("who"), f"{s['id']} {p['what']} 没写负责方"
    # 目标：新剧本 decider 里没有 claude
    assert all(p["target"] != "claude" for s in FL.STAGES for p in s["points"])
    assert all(p["target"] != "claude" for p in FL.OPS_POINTS)


def _fixture_world(root: Path):
    d = root / "data"
    (d / "import").mkdir(parents=True)
    (d / "producer").mkdir(parents=True)
    (d / "autopilot").mkdir(parents=True)
    shots = [{"index": i} for i in (1, 2)]
    (d / "import/script_v2.json").write_text(json.dumps({"episodes": [{"number": 3, "title": "t", "shots": shots}]}), encoding="utf-8")
    mk = lambda sid, f, l, v, hf=True, hl=True: {"shot": sid, "objects": {  # noqa: E731
        "assets": {"status": "passed"}, "first": {"status": f}, "last": {"status": l}, "video": {"status": v}},
        "has": {"first": hf, "last": hl, "video": v == "passed"}}
    reg = {"counts": {"ready": 0, "running": 0}, "episodes": [{"ep": 3, "shots": [
        mk("ep03-S1", "passed", "passed", "passed"), mk("ep03-S2", "passed", "best_effort", "pending")]}]}
    (d / "producer/registry.json").write_text(json.dumps(reg), encoding="utf-8")
    (d / "producer/control.json").write_text(json.dumps({"paused": False}), encoding="utf-8")
    (d / "autopilot/ready_episodes.json").write_text(json.dumps({"episodes": {"3": {"shots": ["ep03-S1", "ep03-S2"]}}}), encoding="utf-8")
    jp = d / "pipeline/runs/series10_v1/assets"
    jp.mkdir(parents=True)
    (jp / "first_frame_jobs.json").write_text(json.dumps({"jobs": [{"shot": "ep03-S1"}, {"shot": "ep03-S2"}]}), encoding="utf-8")


def test_status_all_on_fixture(tmp_path):
    root = _fake_root(tmp_path)
    _fixture_world(root)
    st = FL.status_all(root, write=True)
    r = st["episodes"][0]
    assert r["ep"] == 3 and r["stages"]["import"]["status"] == "done" and r["stages"]["jobs"]["status"] == "done"
    assert r["stages"]["image_gate"]["status"] == "blocked"             # 尽力尾帧 → 卡点，不进合成
    assert r["current"] == "image_gate"
    assert any(b["stage"] == "image_gate" for b in st["blockers"])
    assert (root / "data/autopilot/flow/status.json").exists()
    assert FL.render_all(st) and FL.render_ep(r)


def test_registry_inconsistency_flagged():
    shots = [{"shot": "ep01-S1", "objects": {"first": {"status": "ready"}, "last": {"status": "passed"}}, "has": {"first": False, "last": False}}]
    inc = FL._inconsistent(shots)
    assert len(inc) == 2


def test_drill_and_coverage(tmp_path):
    root = _fake_root(tmp_path)
    _fixture_world(root)
    for rel in ("tools/autopilot/producer.py", "tools/autopilot/episode_pipeline.py"):     # 结构断点用的静态源
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(ROOT / rel, root / rel)
    d = FL.drill(3, root=root, write=True)
    assert d["breakpoints"] and all(b["needs"] in ("claude", "owner") for b in d["breakpoints"])
    assert any(b["stage"] == "delivery" and b["needs"] == "owner" for b in d["breakpoints"])
    c = FL.coverage(root, drill_ep=3, write=True)
    assert c["decision_points"] == sum(len(s["points"]) for s in FL.STAGES) + len(FL.OPS_POINTS)
    assert c["cold_start_breakpoints"]
    assert (root / "data/autopilot/coverage.json").exists()


def test_coverage_counts():
    c = FL.coverage(ROOT, write=False)
    assert sum(c["deciders_now"].values()) == c["decision_points"]
    assert c["deciders_target"].get("claude", 0) == 0


def test_approve_delivery(tmp_path):
    p = FL.approve_delivery(4, root=tmp_path)
    assert json.loads(p.read_text(encoding="utf-8"))["approved"] is True


# ---------------------------------------------------------------- K-OPS-X04 / X05
def test_asset_sheet_prompt_contract():
    t = (ROOT / "config/prompts/asset_sheet_inspect.md").read_text(encoding="utf-8")
    for k in ("## system", "## user", "sleeves_complete", "outer_layer_all_panels", "{wardrobe}", "{panels}", "verdict"):
        assert k in t


def test_decisions_inventory_valid():
    d = yaml.safe_load((ROOT / "config/policies/decisions.yaml").read_text(encoding="utf-8"))
    ids = [x["id"] for x in d["decisions"]]
    assert len(ids) == len(set(ids))
    for x in d["decisions"]:
        assert x["coded"] in ("yes", "partial", "no"), x["id"]
        assert x["decider_now"] in FL.DECIDERS and x["decider_target"] in FL.DECIDERS, x["id"]
        assert x["decider_target"] != "claude", x["id"]
        if x["coded"] != "yes":
            assert x.get("plan"), x["id"]


# ---------------------------------------------------------------- K-OPS-X06 决策 / 配置类数据快照
import state_snapshot as SS  # noqa: E402


def _snap_root(tmp_path: Path) -> Path:
    root = tmp_path / "r"
    (root / "config/policies").mkdir(parents=True)
    (root / "config/pipeline").mkdir(parents=True)
    shutil.copy(ROOT / "config/policies/state_files.yaml", root / "config/policies/state_files.yaml")
    shutil.copy(ROOT / "config/pipeline/video_policy.json", root / "config/pipeline/video_policy.json")
    (root / "config/pipeline/run.json").write_text(json.dumps({"run_id": "demo_run"}), encoding="utf-8")
    for rel, v in {"data/producer/master_rejects.json": {"a": 1}, "data/autopilot/ready_episodes.json": {"episodes": {"1": {}}},
                   "data/pipeline/runs/demo_run/video/recipe_choice.json": {"face_default": "i2va_pika_flex"},
                   "data/autopilot/lookA_hold.json": {"active": False}, "data/producer/registry.json": {"x": 1}}.items():
        (root / rel).parent.mkdir(parents=True, exist_ok=True)
        (root / rel).write_text(json.dumps(v), encoding="utf-8")
    return root


def test_state_snapshot_roundtrip(tmp_path):
    root = _snap_root(tmp_path)
    files = SS.decision_files(root)
    assert "data/producer/master_rejects.json" in files and "data/autopilot/lookA_hold.json" in files
    assert "data/producer/registry.json" not in files                       # 运行状态不进快照
    man = SS.snapshot("sv-t", root=root)
    assert man["tar_sha256"] and all(len(v["sha256"]) == 64 for v in man["files"].values())
    (root / "data/producer/master_rejects.json").write_text("{}", encoding="utf-8")
    r = SS.restore("sv-t", root=root)
    assert [c["file"] for c in r["changes"]] == ["data/producer/master_rejects.json"] and not r["applied"]
    r = SS.restore("sv-t", root=root, apply=True)
    assert r["applied"] and json.loads((root / "data/producer/master_rejects.json").read_text(encoding="utf-8")) == {"a": 1}
    assert list((root / "data/system_versions/sv-t").glob("pre_restore_*/data/producer/master_rejects.json"))   # 恢复前备份


def test_state_snapshot_tamper_refused(tmp_path):
    root = _snap_root(tmp_path)
    SS.snapshot("sv-t", root=root)
    t = root / "data/system_versions/sv-t/state_snapshot.tar"
    t.write_bytes(t.read_bytes() + b"x")
    with pytest.raises(ValueError):
        SS.restore("sv-t", root=root)


def test_init_run_from_config_only(tmp_path):
    root = _snap_root(tmp_path)
    r = SS.init_run("new_show", root=root)
    assert not r["applied"] and r["preview_dir"]
    rc = json.loads((root / "data/autopilot/init_run/new_show/data/pipeline/runs/new_show/video/recipe_choice.json").read_text(encoding="utf-8"))
    assert rc["face_default"] == "i2va_pika_flex"                            # 从 config/pipeline/video_policy.json 派生（L-088）
    r = SS.init_run("new_show", root=root, apply=True)
    assert "data/producer/master_rejects.json（已存在，不覆盖）" in r["skipped"]
    ctrl = json.loads((root / "data/producer/control.json").read_text(encoding="utf-8"))
    assert ctrl["run"] == "new_show"


# ---------------------------------------------------------------- r2：新剧本从 P0 Brief 起的写作段
def test_writing_status_from_brief(tmp_path):
    root = _fake_root(tmp_path)
    brief = tmp_path / "b.json"
    brief.write_text(json.dumps({"schema": "nsfs.brief/1"}), encoding="utf-8")
    rec = FL.start(brief, 2, run_id="t_run", root=root, launch=False)
    d = root / rec["dir"]
    S = FL.writing_status(root, d, 2)
    assert S["brief"]["status"] == "done" and S["chain"]["status"] == "waiting"
    for k, v in FL.WRITE_FILES.items():
        f = d / v.format(ep=2)
        f.write_text("x", encoding="utf-8")
        f.with_name(f.name + ".report.json").write_text(json.dumps({"status": "ok"}), encoding="utf-8")
    S = FL.writing_status(root, d, 2)
    assert S["chain"]["status"] == "done" and S["script"]["needs"] == "claude"     # HOLLYWOOD r8 未交付 = 断点
    (d / "hollywood").mkdir()
    (d / "hollywood/ep02.json").write_text(json.dumps({"candidates": [{"name": "r3", "score": 48.5, "invariants_pass": True,
        "p4_block_zero": True, "fact_check_zero": True}], "spent_usd": 2.1, "rounds_left": 2}), encoding="utf-8")
    S = FL.writing_status(root, d, 2)
    assert S["script"]["status"] == "done" and S["import"]["needs"] == "owner"
    (root / "data/autopilot/imports.jsonl").write_text(json.dumps({"run": "t_run", "ep": 2}) + "\n", encoding="utf-8")
    assert FL.writing_status(root, d, 2)["import"]["status"] == "done"
    rows = FL.runs_status(root)
    assert rows and rows[0]["run_id"] == "t_run" and rows[0]["current"] == "jobs"


def test_new_run_from_registry_without_episode(tmp_path):
    """HOLLYWOOD r8 直接建目录的整季新 run（例 series10_s2，L-104）：从 config/pipeline/runs.json 读到，按目录产物找集号"""
    root = _fake_root(tmp_path)
    (root / "config/pipeline").mkdir(parents=True, exist_ok=True)
    (root / "config/pipeline/runs.json").write_text(json.dumps({"primary": "series10_v1", "runs": {
        "series10_v1": {"priority": 0}, "series10_s2": {"priority": 10, "status": "writing"}}}), encoding="utf-8")
    d = root / "data/pipeline/runs/series10_s2"
    d.mkdir(parents=True)
    (d / "P0_brief.json").write_text("{}", encoding="utf-8")
    rows = FL.runs_status(root)
    assert [(r["run_id"], r["episode"]) for r in rows] == [("series10_s2", 1)] and rows[0]["budget_cap_usd"] == 8.0
    for ep in (1, 2):
        (d / f"P2_ep{ep:02d}_outline.json").write_text("{}", encoding="utf-8")
    rows = FL.runs_status(root)
    assert [r["episode"] for r in rows] == [1, 2] and all(r["current"] == "chain" for r in rows)


# ---------------------------------------------------------------- K-OPS-X07 身份脸逐 run 断言
def test_identity_face_check_catches_inherit_gap():
    sys.path.insert(0, str(ROOT / "tools" / "qa"))
    import identity_face_check as IF
    hd, old = "data/assets/identity_refs/lin_wan/lin_wan_face_hd_A_s202.png", "data/assets/identity_refs/lin_wan/lin_wan_face_ref2va.png"
    faces = {"series10_v1": {"lin_wan": hd, "gu_chen": "g.png"}, "series10_s2": {"lin_wan": old, "gu_chen": "g.png"}}
    cfg = lambda r: {"faces": {"lin_wan": [], "gu_chen": []}}  # noqa: E731
    chain = lambda r: [r, "series10_v1"] if r == "series10_s2" else [r]  # noqa: E731
    res = IF.check(face_of=lambda r, c: faces[r][c], project_cfg=cfg, project_chain=chain,
                   run_ids=["series10_v1", "series10_s2"], pinned={"lin_wan": hd}, sha=lambda p: "x")
    assert not res["ok"] and [(b["run"], b["cid"]) for b in res["bad"]] == [("series10_s2", "lin_wan")]   # 03:0x 那次
    faces["series10_s2"]["lin_wan"] = hd
    faces["series10_s2"]["gu_chen"] = "other.png"
    res = IF.check(face_of=lambda r, c: faces[r][c], project_cfg=cfg, project_chain=chain,
                   run_ids=["series10_v1", "series10_s2"], pinned={"lin_wan": hd}, sha=lambda p: "x")
    assert [(b["run"], b["cid"]) for b in res["bad"]] == [("series10_s2", "gu_chen")]                   # 继承角色不一致



# ---------------------------------------------------------------- sv-05：成片版本读交付记录（SYSARCH 11-02，不按 mtime 猜）
def test_latest_cut_reads_delivery_record_not_mtime(tmp_path):
    root = _fake_root(tmp_path)
    _fixture_world(root)
    eps = root / "data/episodes/series10"
    eps.mkdir(parents=True)
    for n in ("ep03_v1.mp4", "ep03_v2.mp4", "ep03_v9_backup.mp4"):
        (eps / n).write_bytes(b"x")
    w = FL.World(root)
    assert w.latest_cut(3) is None                                   # 没有交付记录 = 未合成（不猜 v9_backup）
    vid = root / "data/pipeline/runs/series10_v1/video"
    vid.mkdir(parents=True)
    (vid / "night_state.json").write_text(json.dumps({"eps": {"3": {"status": "assembled",
        "final": "/root/work/ns/data/episodes/series10/ep03_v1.mp4"}}}), encoding="utf-8")   # 服务器绝对路径也认
    w = FL.World(root)
    assert w.latest_cut(3) == eps / "ep03_v1.mp4"
    (eps / "ep03_v1_post.mp4").write_bytes(b"x")
    (vid / "night_state.json").write_text(json.dumps({"eps": {"3": {"status": "assembled",
        "final": "D:\\x\\data\\episodes\\series10\\ep03_v1_post.mp4"}}}), encoding="utf-8")
    assert FL.World(root).latest_cut(3) == eps / "ep03_v1.mp4"       # 交付后期版 → 原合成版，后期由 post 段判


def test_snapshot_runs_from_registry(tmp_path):
    root = _snap_root(tmp_path)
    (root / "config/pipeline/runs.json").write_text(json.dumps({"primary": "demo_run", "runs": {"demo_run": {}, "s2": {}}}), encoding="utf-8")
    (root / "data/pipeline/runs/s2/video").mkdir(parents=True)
    (root / "data/pipeline/runs/s2/video/recipe_choice.json").write_text("{}", encoding="utf-8")
    assert SS.run_id(root) == "demo_run" and SS.run_ids(root) == ["demo_run", "s2"]
    files = SS.decision_files(root)
    assert "data/pipeline/runs/s2/video/recipe_choice.json" in files and "data/pipeline/runs/demo_run/video/recipe_choice.json" in files



# ---------------------------------------------------------------- r3：L-109 测试期口径 + canary + 写作交稿即推进
def test_canary_is_explicit_pause():
    t0 = time.time()
    iso = lambda dt: time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(t0 - dt))  # noqa: E731
    assert POL.pause_decision({"paused": True, "paused_by": "VQAGATE", "reason_kind": "canary", "paused_at": iso(60), "expires_at": iso(-60)}, t0) is None
    d = POL.pause_decision({"paused": True, "paused_by": "VQAGATE", "reason_kind": "canary", "paused_at": iso(400), "expires_at": iso(-60)}, t0)
    assert d["action"] == "alert"                                            # 不自动恢复


def test_writer_points_testphase_vs_launch():
    wp = [p for s in FL.STAGES for p in s["points"] if p.get("writer")]
    assert len(wp) == 3
    assert all(FL.now_of(p, "claude_agent") == FL.TESTPHASE for p in wp)
    assert all(FL.now_of(p, "api") == "api_model" for p in wp)
    c = FL.coverage(ROOT, write=False)
    assert c["deciders_now_launch"].get(FL.TESTPHASE, 0) == 0                # 上线配置下没有 testphase
    assert "claude_share_launch" in c


def test_autoflow_due_and_memo(tmp_path):
    root = _fake_root(tmp_path)
    d = root / "data/pipeline/runs/s2"
    (d / "writer_tasks").mkdir(parents=True)
    (d / "writer_out").mkdir()
    for name, ep in (("P2_ep06_a1.json", 6), ("P2_ep06_a2.json", 6), ("patch_ep02_a1.json", 2)):
        (d / "writer_tasks" / name).write_text(json.dumps({"episode": ep, "advance_cmd": "echo hi",
            "output": {"done_marker": f"data/pipeline/runs/s2/writer_out/{name}.done"}}), encoding="utf-8")
    assert FL.autoflow_due(root) == []
    (d / "writer_out/P2_ep06_a1.json.done").write_text("", encoding="utf-8")       # 旧包交稿不算（取 a 最大的包）
    assert FL.autoflow_due(root) == []
    (d / "writer_out/P2_ep06_a2.json.done").write_text("", encoding="utf-8")
    (d / "writer_out/P4_ep03_r1.md.done").write_text("", encoding="utf-8")         # 整集重写稿交稿
    due = {(x["episode"], x["package"]) for x in FL.autoflow_due(root)}
    assert due == {(6, "P2_ep06_a2.json"), (3, "P4_ep03_r1.md")}
    (d / "autoflow_ep03.json").write_text(json.dumps({"agent": {"full_p4_done": ["P4_ep03_r1.md"]}}), encoding="utf-8")
    assert {x["episode"] for x in FL.autoflow_due(root)} == {6}
    r = FL.autoflow_tick(root, apply=False)
    assert r["ran"] and r["ran"][0]["dry"]



def test_master_review_autosign_gate():
    """总调度 04:0x：一致率 ≥95% 且漏放 0 才切换；切换后抽检 10%，不一致即退回人工"""
    ok = [{"auto": "pass", "human": "pass"}] * 19 + [{"auto": "fail", "human": "fail"}]
    assert POL.autosign_switch_ok(ok)["ok"] is True
    one_fp = ok[:-1] + [{"auto": "pass", "human": "fail"}]                    # 一致率 95% 但有 1 条漏放
    r = POL.autosign_switch_ok(one_fp)
    assert r["ok"] is False and r["false_pass"] == 1
    strict = ok[:-2] + [{"auto": "fail", "human": "pass"}] * 2                 # 误挡 2 条 → 90%
    assert POL.autosign_switch_ok(strict)["ok"] is False
    assert POL.autosign_switch_ok([])["ok"] is False                           # 没测到 ≠ 通过
    assert POL.autosign_spot_check([{"auto": "pass", "human": "pass"}] * 3, 30)["action"] == "keep"
    assert POL.autosign_spot_check([{"auto": "pass", "human": "pass"}] * 2, 30)["action"] == "wait"
    assert POL.autosign_spot_check([{"auto": "pass", "human": "fail"}], 30)["action"] == "revert"



# ---------------------------------------------------------------- K-OPS-X08 min_code_sv
def test_code_sv_problem_fail_closed(tmp_path):
    root = _fake_root(tmp_path)
    (root / "data").mkdir(exist_ok=True)
    assert "失败关闭" in POL.code_sv_problem(root, want="sv-20261102-03")              # 没有版本文件
    vf = root / "data/system_version.txt"
    vf.write_text(json.dumps({"id": "sv-20261101-01"}), encoding="utf-8")
    assert "低于" in POL.code_sv_problem(root, want="sv-20261102-03")
    vf.write_text(json.dumps({"id": "sv-20261102-10"}), encoding="utf-8")              # 10 > 03（数值比较，不是字符串）
    assert POL.code_sv_problem(root, want="sv-20261102-03") is None
    vf.write_text("garbage", encoding="utf-8")
    assert "格式不对" in POL.code_sv_problem(root, want="sv-20261102-03")
    assert POL._sv_key("sv-20261102-10") > POL._sv_key("sv-20261102-9")
    vf.write_text(json.dumps({"id": "sv-20261102-10"}), encoding="utf-8")
    assert "未配置" in POL.code_sv_problem(root, want="bogus")                        # min_code_sv 配坏了也拒派（失败关闭）


def test_deployed_sv_and_handback(tmp_path):
    root = _fake_root(tmp_path)
    p = root / "data/system_versions/index.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"versions": [{"id": "sv-20261102-01", "deployed": {"gpu36": {"ok": True}}},
                                          {"id": "sv-20261102-02", "deployed": {"gpu36": {"ok": False}, "gpu33": {"ok": True}}}]}), encoding="utf-8")
    assert POL.deployed_sv("gpu36", root) == "sv-20261102-01" and POL.deployed_sv("gpu33", root) == "sv-20261102-02"
    good = {"preflight_dryrun_ok": True, "preflight_dryrun_shots": 5, "refs_match": True, "refs_mismatch": 0,
            "ready": True, "preflight_dryrun_by": "FACTORY"}
    ok, why = POL.handback_ok(good, server_sv=POL.deployed_sv("gpu36", root))
    assert not ok and any("min_code_sv" in w for w in why)                              # sv-01 < sv-03



def test_line3_tick_keeps_dirty_on_failure(tmp_path):
    root = _fake_root(tmp_path)
    d = root / "data/pipeline/runs/s2"
    d.mkdir(parents=True)
    f = d / "line3_dirty.json"
    f.write_text(json.dumps({"episodes": {"2": {"why": "x"}}, "cmd": sys.executable + " -c raise SystemExit(3)"}), encoding="utf-8")
    assert FL.line3_tick(root, apply=False)["ran"][0]["dry"] is True and f.exists()
    r = FL.line3_tick(root, apply=True)
    assert r["ran"][0]["rc"] != 0 and f.exists()                                   # 失败保留，下一拍重试
    f.write_text(json.dumps({"episodes": {"2": {}}, "cmd": sys.executable + " -c pass"}), encoding="utf-8")
    assert FL.line3_tick(root, apply=True)["ran"][0]["rc"] == 0 and not f.exists()  # 成功才删



def test_tick_writes_last_tick(tmp_path):
    root = _fake_root(tmp_path)
    _fixture_world(root)
    FL.tick(root, apply=False)
    st = json.loads((root / "data/autopilot/flow/status.json").read_text(encoding="utf-8"))
    assert st["global"]["last_tick"]["dry"] is True and not (root / "data/autopilot/flow/last_tick.json").exists()
    FL.tick(root, apply=True)
    lt = json.loads((root / "data/autopilot/flow/last_tick.json").read_text(encoding="utf-8"))
    assert lt["dry"] is False and time.time() - lt["t"] < 60



def test_tick_parts_independent(tmp_path):
    """三条线互不依赖：core 在另两条线没跑过时也能写 status / last_tick；之后并入两线结果"""
    root = _fake_root(tmp_path)
    _fixture_world(root)
    r = FL.tick_part("core", root, apply=True)
    st = json.loads((root / "data/autopilot/flow/status.json").read_text(encoding="utf-8"))
    assert r["part"] == "core" and st["global"]["api_restart"]["status"] == "pending"
    assert json.loads((root / "data/autopilot/flow/last_tick.json").read_text(encoding="utf-8"))["mode"] == "parts"
    FL.tick_part("api", root, apply=False)
    FL.tick_part("line3", root, apply=False)
    FL.tick_part("core", root, apply=True)
    st = json.loads((root / "data/autopilot/flow/status.json").read_text(encoding="utf-8"))
    assert st["global"]["api_restart_at"] and st["global"]["line3_tick_at"]
    with pytest.raises(ValueError):
        FL.tick_part("nope", root)
