"""PRODMERGE-O 11-03（PLAN_V2_MASTER v4 阶段一 1-3 / 1-4 / 1-5，L-151 / L-152）。夹具全在临时根，不出图、不读真实生产数据。

1-3 单一来源：runs.json 是“当前剧”唯一来源（run.json 派生、run_env 收口）；sop_gate.stage_view 是唯一阶段模型（sop.py / scorecard / v2_live 读它）；
    wizard 生产导入改走 import-staged。
1-4 提示词探针：build_first + preflight（不再调 golden_v2）；成人镜 pending_owner（REVIEW-A P1④：出图 / 尾帧 / 视频也不算未通过）。
1-5 出图并回 producer：RUN_ID 不在导入时定；preparing → producing 按 sop_gate.promote；派单过闸门；共用验收（bundle + 三态）；
    一镜多种子分道；V2 媒体路径按剧；帧只记 takes.json（sop_gate / episode_metrics 不读 ab 账）；定稿档挂在共用验收之后；golden_v2 只剩两个入口。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools/autopilot", "services/agent", "services/render_router", "packages/schema", "services/api", "tools/promptfix"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


SG = _load("sop_gate_pm", "tools/master/sop_gate.py")
RN = _load("runs_pm", "tools/autopilot/runs.py")
RUN = "drama_x"


def _w(p: Path, obj) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    return p


def _root(tmp_path, *, status="preparing", shots=(1, 2, 3), adult=(3,), cfg=None, manifest=True, prompts_ok=True):
    r = tmp_path
    reg = {RUN: {"status": status, "priority": 0}}
    if manifest:
        reg[RUN]["assets_manifest"] = "assets_x/manifest.json"
        _w(r / "assets_x/manifest.json", {"characters": {}})
    _w(r / "config/pipeline/runs.json", {"primary": RUN, "legacy_unprefixed_run": "old_v1", "runs": {**reg, "old_v1": {"status": "archived"}}})
    _w(r / "config/pipeline/run.json", {"run_id": RUN})
    _w(r / "config/pipeline/sop_gate.json", cfg or {"enabled": True, "observe_stages": []})
    _w(r / f"data/import/runs/{RUN}/script_v2.json",
       {"episodes": [{"number": 1, "shots": [{"index": n, "adult": n in adult} for n in shots]}]})
    _w(r / f"data/pipeline/runs/{RUN}/P4_ep01.md", "# P4\n")
    _w(r / f"data/pipeline/runs/{RUN}/autoflow_ep01.json",
       {"stages": [{"id": "gate", "status": "ok"}, {"id": "import", "status": "imported", "sha256": "abc"}]})
    _w(r / f"data/pipeline/runs/{RUN}/autoflow.json", {})
    _w(r / f"data/pipeline/asset_jobs/{RUN}/_ready_ep01.json", {"ready": True, "gaps": 0, "at": "t"})
    if prompts_ok:
        rows = {str(n): ({"ok": None, "pending_owner": True} if n in adult else {"ok": True}) for n in shots}
        SG.probe_prompts(RUN, 1, root=r, runner=lambda run, ep, root, c: rows)
    return r


def _frame(r, n, *, q9="pass", last=False, video=False):
    (r / "data/img").mkdir(parents=True, exist_ok=True)
    (r / f"data/img/s{n}.png").write_bytes(b"x")
    takes = [{"stage": "image", "n": 1, "file": f"img/s{n}.png", "postflight": {"ok": True, "items": [{"id": "Q9", "status": q9}]}}]
    act = {"image": 1}
    if last:
        takes.append({"stage": "last", "n": 1, "file": f"img/s{n}.png", "postflight": {"ok": True}})
        act["last"] = 1
    _w(r / f"data/renders/{RUN}/ep01/S{n}/takes.json", {"takes": takes, "active": act})
    if video:
        _w(r / f"data/pipeline/runs/{RUN}/video/clips/ep01/ep01-S{n}__v1.mp4", "mp4")


# ====================================================================== 1-3 当前剧只认 runs.json
def test_run_ptr_is_derived_from_runs_json(tmp_path):
    r = _root(tmp_path)
    _w(r / "config/pipeline/run.json", {"run_id": "stale_run"})
    assert "不一致" in RN.run_ptr_drift(r)
    d = RN.sync_run_ptr(r)
    assert d["run_id"] == RUN and RN.run_ptr_drift(r) is None
    assert json.loads((r / "config/pipeline/run.json").read_text(encoding="utf-8"))["derived_from"].startswith("config/pipeline/runs.json")


def test_set_status_writes_history_and_syncs_ptr(tmp_path):
    r = _root(tmp_path)
    _w(r / "config/pipeline/run.json", {"run_id": "stale_run"})
    e = RN.set_status(RUN, "producing", by="t", why="why", root=r)
    assert e["status"] == "producing" and e["status_history"][-1]["from"] == "preparing"
    assert RN.run_ptr_drift(r) is None
    with pytest.raises(ValueError):
        RN.set_status(RUN, "bogus", by="t", why="", root=r)
    with pytest.raises(RN.RunNotRegistered):
        RN.set_status("nope", "producing", by="t", why="", root=r)


def test_run_env_only_for_registered_runs(tmp_path):
    r = _root(tmp_path)
    assert RN.run_env("old_v1", r) == {}
    env = RN.run_env(RUN, r)
    assert env["NS_RUN"] == RUN and env["NS_RENDERS_DIR"].endswith(str(Path("data/renders") / RUN))
    with pytest.raises(RN.RunNotRegistered):
        RN.run_env("ghost_run", r)


def test_producer_reads_runs_json_not_run_json(tmp_path):
    import producer as PR
    r = _root(tmp_path)
    _w(r / "config/pipeline/run.json", {"run_id": "stale_run"})          # 派生指针过期：producer 仍按 runs.json
    assert PR._run_id_from_config(root=r) == RUN == PR.default_run(r)
    assert PR.Paths(root=r).run_id == RUN                                  # 不给 run_id = 现取，不用导入时缓存
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert 'run_id: str = RUN_ID' not in src and '"run": RUN_ID' not in src


def test_producer_main_rejects_unregistered_run(capsys):
    import producer as PR
    assert PR.main(["status", "--run", "ghost_run_pm"]) == 2
    assert "不在 config/pipeline/runs.json" in capsys.readouterr().err


def test_v2_media_paths_are_per_run(tmp_path):
    import producer as PR
    r = _root(tmp_path)
    p = PR.Paths(root=r, run_id=RUN)
    assert p.music == r / "data/music" / RUN and p.eps_out == r / "data/episodes" / RUN
    assert p.voices.name == "voices_v2.json" and "series10" not in str(p.review)
    v1 = PR.Paths(root=r, run_id="old_v1")
    assert v1.music == r / "data/music/series10" and v1.voices.name == "voices.json"


# ====================================================================== 1-3 唯一阶段模型
def test_stage_view_and_consumers(tmp_path, monkeypatch):
    r = _root(tmp_path)
    for n in (1, 2):
        _frame(r, n)
    v = SG.stage_view(RUN, r)
    e = v["episodes"][0]
    assert e["stage"] == "尾帧" and e["legacy_stage"] == "S3" and e["pending_owner"] == [3]
    assert v["stage"] == "尾帧" and v["counts"]["尾帧"] == 1
    assert SG.stage_view("old_v1", r)["legacy"] is True
    # v2_live：读同一份视图
    VL = _load("v2_live_pm", "tools/monitor/v2_live.py")
    rows = VL.sop_stage_rows(RUN, view=v)
    assert rows["出图"]["state"] == "done" and rows["尾帧"]["state"] == "doing" and rows["视频"]["state"] == "todo"
    # ns_api/sop.py：资产包剧的阶段读 sop_gate（S1–S5 自判只给 V1）
    from ns_api import sop as SOPM
    monkeypatch.setattr(SOPM, "sop_gate_view", lambda root: v)
    monkeypatch.setattr(SOPM, "_project_summary_v1", lambda *a: {"stage": "S1", "stage_label": "剧本", "episodes": [{"episode": 1, "stage": "S1"}]})
    out = SOPM.project_summary("x", "x", {"shots": []}, NS(timeline=None, root=r))
    assert out["stage"] == "S3" and out["stage_source"] == "sop_gate" and out["episodes"][0]["sop_stage"] == "尾帧"
    # scorecard：非 legacy 剧读 sop_gate（stage_status.json 退役）
    from tools.sentinel import scorecard as SC
    from tools.master import sop_gate as SGM
    from tools.autopilot import runs as RUNS
    monkeypatch.setattr(RUNS, "is_legacy", lambda run, root=None: False)
    monkeypatch.setattr(SGM, "stage_view", lambda run, root=None: v)
    st, info = SC.stage_of(RUN)
    assert st == "S3" and info["source"] == "sop_gate"


# ====================================================================== 1-4 / REVIEW-A P1④ 成人镜 pending_owner
def test_adult_shots_pending_owner_not_failing(tmp_path):
    r = _root(tmp_path, adult=(3,))
    for n in (1, 2):
        _frame(r, n, last=True, video=True)
    assert SG.check_prompts(r, RUN, 1)["ok"] and SG.check_prompts(r, RUN, 1)["pending_owner"] == [3]
    for chk in (SG.check_images, SG.check_image_qc, SG.check_lasts):
        res = chk(r, RUN, 1)
        assert res["ok"] and res["pending_owner"] == [3] and "等项目方触发" in res["why"], chk.__name__
    v = SG.check_video(r, RUN, 1)
    assert v["ok"] and v["pending_owner"] == [3]
    assert SG.judge(RUN, 1, "整集预览", root=r)["ok"]          # 成人镜不挡到整集预览
    # 非成人镜缺视频照样不过
    (r / f"data/pipeline/runs/{RUN}/video/clips/ep01/ep01-S2__v1.mp4").unlink()
    assert not SG.check_video(r, RUN, 1)["ok"] and SG.check_video(r, RUN, 1)["bad"] == [2]


def test_only_takes_json_counts_no_ab_ledger(tmp_path):
    r = _root(tmp_path)
    _w(r / "data/ab/v2_golden_ep01/takes.jsonl", json.dumps({"file": "ab/S1/x.png", "pass": True}) + "\n")
    assert SG.shot_frames(r, RUN, 1) == {}
    assert "v2_golden" not in (ROOT / "tools/master/sop_gate.py").read_text(encoding="utf-8")


def test_probe_uses_build_first_preflight_not_golden(tmp_path):
    r = _root(tmp_path, prompts_ok=False)
    cfg = json.loads((ROOT / "config/pipeline/sop_gate.json").read_text(encoding="utf-8"))
    assert cfg["prompt_probe"] == "build_first+preflight"
    seen = {}

    def runner(run, ep, root, c):
        seen.update(run=run, ep=ep)
        return {"1": {"ok": True}, "2": {"ok": False, "why": "I3"}, "3": {"ok": None, "pending_owner": True}}
    ev = SG.probe_prompts(RUN, 1, root=r, runner=runner)
    assert seen == {"run": RUN, "ep": 1} and ev["probe"] == "build_first+preflight"
    res = SG.check_prompts(r, RUN, 1)
    assert not res["ok"] and res["bad"] == [2] and res["pending_owner"] == [3]
    src = (ROOT / "tools/master/sop_gate.py").read_text(encoding="utf-8")
    assert "FJ.build_first(" in src and "PF.check(" in src and "golden_v2.py" not in src


# ====================================================================== 1-5 preparing → producing
def test_promote_rule_aligned_with_sop_gate(tmp_path):
    r = _root(tmp_path, prompts_ok=False)
    res = SG.promote_check(RUN, r)
    assert not res["promote"] and "提示词" in res["why"]
    SG.probe_prompts(RUN, 1, root=r, runner=lambda *a: {"1": {"ok": True}, "2": {"ok": True}, "3": {"ok": None, "pending_owner": True}})
    assert SG.promote_check(RUN, r)["promote"] and SG.promote_check(RUN, r)["episodes"] == [1]
    assert not SG.promote(RUN, r, apply=False).get("applied")
    assert json.loads((r / "config/pipeline/runs.json").read_text(encoding="utf-8"))["runs"][RUN]["status"] == "preparing"
    res = SG.promote(RUN, r, by="t", apply=True)
    reg = json.loads((r / "config/pipeline/runs.json").read_text(encoding="utf-8"))["runs"][RUN]
    assert res["applied"] and reg["status"] == "producing" and "sop_gate.promote" in reg["status_history"][-1]["why"]
    assert SG.promote_check(RUN, r)["promote"] is False                    # 只提升 preparing


def _producer(r, **kw):
    import producer as PR
    paths = PR.Paths(root=r, run_id=RUN)
    pr = PR.Producer(paths, lanes={}, lane_probe=lambda url: {"ok": True, "n": 0}, run_summary_fn=lambda: None,
                     train_locks_fn=lambda s: set(), lock_now_fn=lambda lane: False, **kw)
    pr.logf = lambda ev, **k: pr.__dict__.setdefault("_logs", []).append((ev, k))
    return PR, pr


def test_producer_ctrl_promotes_only_when_auto(tmp_path):
    r = _root(tmp_path, cfg={"enabled": True, "observe_stages": [], "promote": {"auto": False, "stage": "出图"}})
    PR, pr = _producer(r)
    c = pr.ctrl()
    assert c["paused"] and c["paused_by"] == "runs.json" and c["run"] == RUN
    assert any(ev == "promote_ready" for ev, _ in pr._logs)
    _w(r / "config/pipeline/sop_gate.json", {"enabled": True, "observe_stages": [], "promote": {"auto": True, "stage": "出图"}})
    PR._SG_MODS.clear()
    pr._promote_t = 0
    c = pr.ctrl()
    assert not c.get("paused") and PR.run_status(r, RUN) == "producing"
    assert any(ev == "run_promoted" for ev, _ in pr._logs)


def test_producer_dispatch_goes_through_sop_gate(tmp_path):
    r = _root(tmp_path, status="producing", prompts_ok=False)
    PR, pr = _producer(r)
    o = {"id": f"{RUN}/first:ep01-S1", "shot": "ep01-S1", "kind": "first"}
    assert pr.sop_gate_block(o) is True                                     # 提示词没证据 → enforce 挡
    assert any(ev == "sop_gate_block" for ev, _ in pr._logs)
    SG.probe_prompts(RUN, 1, root=r, runner=lambda *a: {"1": {"ok": True}, "2": {"ok": True}, "3": {"ok": None, "pending_owner": True}})
    PR._SG_MODS.clear()
    assert pr.sop_gate_block(o) is False
    assert pr.sop_gate_block({**o, "kind": "last", "id": "x/last:ep01-S1"}) is True   # 尾帧要先有过检首帧
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    assert "if self.sop_gate_block(o):" in src


def test_fanout_spreads_seeds_over_free_lanes(tmp_path):
    r = _root(tmp_path, status="producing")
    _w(r / "config/pipeline/producer.json", {"fanout": {"enabled": True, "max_per_obj": 3}})
    PR, pr = _producer(r)
    sub = []
    pr.pool = NS(submit=lambda fn, *a: sub.append(a))
    pr.rung = lambda o, a: {"name": f"第 {a} 次", "seed": 100 + a}
    pr.rung_strategy = lambda *a: None
    pr.rung_ab = lambda *a: None
    o = {"id": f"{RUN}/first:ep01-S1", "shot": "ep01-S1", "kind": "first", "ep": 1, "attempts": 0}
    pr.inflight[o["id"]] = {"lane": "gpu33:0"}                             # 主单已在 gpu33:0
    free = ["gpu33:1", "gpu36:0", "gpu36:1"]
    pr.dispatch_fanout([(1, 1, 1, o)], free)
    keys = [a[3]["fanout"] for a in sub]
    assert keys == [f"{o['id']}#2", f"{o['id']}#3"] and free == ["gpu36:1"]   # 每对象 ≤3 在途、每次一个种子算一次尝试（≤3）
    assert [a[1] for a in sub] == ["gpu33:1", "gpu36:0"] and {a[3]["seed"] for a in sub} == {102, 103}
    _w(r / "config/pipeline/producer.json", {"fanout": {"enabled": False}})
    assert pr.fanout_ok() == 1                                               # 默认关 = 老行为
    cfg = json.loads((ROOT / "config/pipeline/producer.json").read_text(encoding="utf-8"))
    # W13 CUTB-PREP 11-03：断言跟着决定走（K-OPS-C02），不是放宽。L-155（PS 侧，已作废）开 fanout → 总调度 L-161（11:40）进版关：
    # 一镜多种子分道未经 A/B、A1-11 前提未修。改断言为 L-161 口径；共用验收 accept 仍开不变
    assert cfg["fanout"]["enabled"] is False and "L-161" in cfg["fanout"]["_note"] and cfg["accept"]["enabled"] is True   # L-161 进版关
    sg = json.loads((ROOT / "config/pipeline/sop_gate.json").read_text(encoding="utf-8"))
    assert sg["promote"]["auto"] is True and "L-154" in sg["promote"]["_decision"] and sg["whole_episode_prompts"] is True   # L-154 / L-140


# ====================================================================== 1-5 共用验收
ACC = _load("accept_pm", "services/agent/ns_agent/gen_contract/accept.py")


def _post(q1="pass", q9="pass", q2="na"):
    return {"ok": True, "items": [{"id": "Q1", "status": q1}, {"id": "Q2", "status": q2},
                                  {"id": "Q9", "status": q9, "evidence": {"model": "m"} if q9 != "untested" else {}}]}


def _bundle(ok=True, status=None):
    return {"status": status or ("pass" if ok else "fail"), "items": [{"n": 1, "ok": True}, {"n": 2, "ok": ok}],
            "age": {"status": "pass"}, "ocr": {"status": "pass"}}


def _job():
    return {"cast": [{"name": "甲", "presence": "在画"}], "prompt": "p",
            "asset_refs": {"characters": [{"name": "甲", "character": "ch_a", "look": "L1", "presence": "在画"}]}}


def _eval(post, bundle, an="pass"):
    return ACC.evaluate("img.png", post, _job(), {"scene_id": "sc", "img_prompt": "x"}, RUN, q9_fn=lambda p, i, j: p,
                        anomaly_fn=lambda *a, **k: {"status": an}, bundle_fn=lambda *a: bundle, looks={})


def test_accept_three_states():
    assert _eval(_post(), _bundle())["status"] == "pass"
    rej = _eval(_post(), _bundle(ok=False))
    assert rej["status"] == "reject" and any("看图第2条" in x for x in rej["reasons"])
    rt = _eval(_post(q9="untested"), _bundle())
    assert rt["status"] == "retry" and ACC.q9_timeout(rt["post"])           # Q9 排队超时：retry，不判 fail
    assert _eval(_post(), _bundle(status="untested"))["status"] == "retry"   # 合并看图没答
    assert _eval(_post(q1="fail"), _bundle())["status"] == "reject"


def test_accept_apply_into_postflight():
    pf = ACC.apply(_post(), _eval(_post(), _bundle(ok=False)))
    assert pf["ok"] is False and "QB" in pf["blocking"] and pf["accept"]["status"] == "reject"
    pf = ACC.apply(_post(), _eval(_post(q9="untested"), _bundle()))
    assert pf["ok"] is True and pf["score_infra"] and pf["accept_retry"]   # retry → 只重打分、不计次
    pf = ACC.apply(_post(), _eval(_post(), _bundle()))
    assert pf["ok"] and next(i for i in pf["items"] if i["id"] == "QB")["status"] == "pass"


def test_accept_only_for_asset_bundle_runs(tmp_path):
    r = _root(tmp_path)
    assert ACC.enabled(RUN, r) and not ACC.enabled("old_v1", r)
    r2 = _root(tmp_path / "b", manifest=False)
    assert not ACC.enabled(RUN, r2)


def test_producer_shared_accept_hook(tmp_path, monkeypatch):
    import producer as PR
    from ns_render import pipeline as P
    r = _root(tmp_path, status="producing")
    paths = PR.Paths(root=r, run_id=RUN)
    monkeypatch.setattr(P, "find_shot", lambda script, sid: (None, {"scene_id": "s"}))
    ev = lambda img, pf, job, shot, run: _eval(_post(), _bundle(ok=False))   # noqa: E731
    pf = PR.shared_accept(paths, None, "ep01-S1", "x.png", _job(), _post(), evaluate_fn=ev)
    assert pf["ok"] is False and pf["accept"]["status"] == "reject"

    def boom(*a):
        raise RuntimeError("vlm down")
    pf = PR.shared_accept(paths, None, "ep01-S1", "x.png", _job(), _post(), evaluate_fn=boom)
    assert pf["accept_retry"] and pf["score_infra"]                          # 验收服务出错 = retry，不放行
    src = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    i = src.index("vlm = vqa_gate(sid, stage, file_rel, job, pf)")
    assert src.index("shared_accept(self.p", i) < src.index("pf[\"current\"] = AC.on_contract", i)   # 写回 takes / 设当前之前


def test_postflight_exports_accept_and_golden_is_thin(capsys):
    from ns_agent.gen_contract import postflight as PO
    assert callable(PO.accept)
    GV = _load("golden_v2_pm", "tools/promptfix/golden_v2.py")
    assert GV.main(["--render", "--shot", "1"]) == 3 and "已退役" in capsys.readouterr().err
    assert GV.main(["--rejudge", "--shot", "1"]) == 3
    src = (ROOT / "tools/promptfix/golden_v2.py").read_text(encoding="utf-8")
    for w in ("takes.jsonl", "UF._run(", "shutil", "ComfyClient", 'names != {"祁念"}'):
        assert w not in src, w


# ====================================================================== 1-5 定稿档挂在共用验收之后（L-147）
def test_final_tier_waits_for_shared_accept(monkeypatch):
    from ns_render import final_tier as FT
    from ns_render import pipeline as P
    monkeypatch.setattr(FT, "_current_run", lambda: RUN)
    monkeypatch.setattr(P, "find_shot", lambda script, sid: (NS(), NS()))
    import ns_agent.frame_job as FJ
    monkeypatch.setattr(FJ, "build_first", lambda *a, **k: _job())
    monkeypatch.setattr(FT, "ACCEPT_FN", lambda f, j, h, sh, run: {"ok": False, "accept": {"status": "reject"}})
    assert FT.final_accept(NS(globals=None), "ep01-S1", "image", "x.png")["ok"] is False
    monkeypatch.setattr(FT, "ACCEPT_FN", lambda f, j, h, sh, run: {"ok": True, "accept_retry": True})
    assert FT.final_accept(NS(globals=None), "ep01-S1", "image", "x.png")["ok"] is False   # retry 也不接替定稿
    src = (ROOT / "services/render_router/ns_render/final_tier.py").read_text(encoding="utf-8")
    body = src.split("def render_final(", 1)[1]
    assert body.index("final_accept(script") < body.index("FE.lock(shot_id, stage, take.n)")


# ====================================================================== 1-3 wizard 不绕闸门
def test_wizard_production_import_goes_through_import_staged(tmp_path):
    from ns_api import wizard as W
    from ns_api.project_ctx import REPO
    R = W._runs_mod()
    sandbox = NS(script_json=tmp_path / "projects/x/data/import/script_v2.json")
    assert W.production_import_run(sandbox) is None                          # 向导沙箱照旧
    prim = R.registry(REPO)["primary"]
    prod = NS(script_json=R.import_path(prim, REPO))
    assert W.production_import_run(prod) == prim
    legacy = NS(script_json=REPO / "data/import/script_v2.json")
    assert W.production_import_run(legacy) == R.legacy_run(REPO)
    assert not W.import_staged(Path(__file__), R.legacy_run(REPO))["ok"]    # V1 冻结：拒绝
    seen = []
    res = W.import_staged(Path(__file__), prim, runner=lambda cmd: seen.append(cmd) or (0, '{"ok": true}'))
    assert res["ok"] and "import-staged" in seen[0] and seen[0][seen[0].index("--run") + 1] == prim
    src = (ROOT / "services/api/ns_api/wizard.py").read_text(encoding="utf-8")
    assert src.index("production_import_run(ctx)") < src.index("ctx.script_json.write_text(")


# ====================================================================== 1-5 episode_metrics 读 takes.json
def test_episode_metrics_reads_takes_json(tmp_path):
    EM = _load("episode_metrics_pm", "tools/master/episode_metrics.py")
    r = _root(tmp_path)
    _w(r / f"data/renders/{RUN}/ep01/S1/takes.json", {"takes": [
        {"stage": "image", "n": 1, "created_at": "2026-11-03T01:00:00", "postflight": {"ok": False}},
        {"stage": "image", "n": 2, "created_at": "2026-11-03T01:10:00", "postflight": {"ok": True}},
        {"stage": "last", "n": 1, "created_at": "2026-11-03T01:20:00", "postflight": {"ok": True}}]})
    _w(r / "data/ab/v2_golden/takes.jsonl", json.dumps({"compile_trace": {"shot": "ep01-S9"}, "pass": True}) + "\n")
    rows = EM.frame_takes(EM.Paths(r, RUN), 1)
    assert [x["pass"] for x in rows] == [False, True] and {x["source"] for x in rows} == {"takes.json"}
    assert EM.load_takes(EM.Paths(r, RUN), 1, [])["golden"] == rows             # 不再读 ab 金样账


def test_accept_retry_is_capped_on_rescore(tmp_path, monkeypatch):
    """retry 不判 fail，但复核次数有上限（producer.json accept.max_rechecks），满了按没过处理，不无限复核"""
    from ns_render import pipeline as P
    from ns_render import unified_frame as UF
    import ns_agent.frame_job as FJ
    r = _root(tmp_path, status="producing")
    _w(r / "config/pipeline/producer.json", {"accept": {"max_rechecks": 1}})
    PR, pr = _producer(r, script=NS(globals=None))
    pr._fixed_script = True
    pr.script = lambda: NS(globals=None)
    monkeypatch.setattr(P, "find_shot", lambda s, sid: (NS(), NS()))
    monkeypatch.setattr(P, "load_takes", lambda sid: {"takes": [{"stage": "image", "n": 1, "file": "x.png"}]})
    monkeypatch.setattr(UF, "project_for", lambda s: RUN)
    monkeypatch.setattr(FJ, "build_first", lambda *a, **k: _job())
    pr.frames = NS(_postflight=lambda *a: {"ok": True, "accept_retry": True, "score_infra": True})
    o = {"id": f"{RUN}/first:ep01-S1", "shot": "ep01-S1", "kind": "first"}
    pr._rescore_one(o, 1)
    assert "score_infra" in [ev for ev, _ in pr._logs][-2:]                 # 第 1 次：retry，不计次（W20 之后紧跟一条 score_chain_down 熔断记录）
    pr._score_down_until = 0                                                 # W20 熔断期不派只重打分：测试里手动解除，验证第 2 次的计次口径
    pr._rescore_one(o, 1)
    led = pr.ledger()[o["id"]]
    assert [ev for ev, _ in pr._logs][-1] == "rescore" and led["accept_rechecks"] == 2 and led["reason"].startswith("重打分后") and led.get("final") != "passed"


# ====================================================================== 部署前脚本（总调度 11-03 第 2 轮）
def test_register_run_defaults_to_preparing(tmp_path):
    r = _root(tmp_path)
    e = RN.register_run("new_show", source="import", root=r)
    assert e["status"] == "preparing"                                      # 新剧不绕过 SOP
    assert RN.register_run(RUN, root=r)["status"] == "preparing"          # 已有剧 status 不动
    RN.set_status(RUN, "producing", by="t", why="", root=r)
    assert RN.register_run(RUN, root=r)["status"] == "producing"


def test_restart_scripts_run_scoped():
    ps = (ROOT / "ops/autostart/restart_producer.ps1").read_text(encoding="utf-8")
    bs = chr(92)
    assert f"data{bs}producer{bs}control.json" not in ps and f"data{bs}producer{bs}heartbeat.json" not in ps   # 不再写死 V1 目录
    assert ps.count("--run") >= 3 and f"data{bs}producer{bs}runs{bs}$Run" in ps and "legacy_unprefixed_run" in ps
    sh = (ROOT / "ops/offline/resident_restart.sh").read_text(encoding="utf-8")
    assert "producer.py serve --run $RUN" in sh and "night.py --run $RUN" in sh and '"primary"' in sh
    for f in ("ops/offline/resident_restart.sh", "ops/offline/ensure_runs.sh"):
        assert "video10_srv/models_cache" not in (ROOT / f).read_text(encoding="utf-8"), f


def test_video_root_is_deploy_dir_single_source():
    H = _load("hosts_pm", "tools/factory/hosts.py")
    d = json.loads((ROOT / "config/factory/hosts.json").read_text(encoding="utf-8"))
    assert H.video_root(d=d) == d["hosts"]["gpu33"]["repo"] and H.video_code_managed("gpu36", d)
    bad = {"hosts": {"a": {"video_root": "/x", "repo": "/x"}, "b": {"video_root": "/y", "repo": "/y"}}}
    with pytest.raises(H.HostsError):
        H.video_root(d=bad)
    for f in ("tools/series10_video/night.py", "tools/series10_video/deploy.py", "tools/series10_video/sync.py",
              "tools/vqa/after_network.py"):
        assert 'DEST = "/root/work/fredw/video10_srv"' not in (ROOT / f).read_text(encoding="utf-8"), f
        assert "DEST = _video_root()" in (ROOT / f).read_text(encoding="utf-8"), f
    assert "video10_srv" not in json.dumps(json.loads((ROOT / "config/v2style.json").read_text(encoding="utf-8")))
    assert "video10_srv" not in json.dumps(d)


def test_deploy_push_skips_code_when_deploy_dir(monkeypatch):
    monkeypatch.setenv("NS_RUN", "series10_v2")
    DP = _load("deploy_pm", "tools/series10_video/deploy.py")
    files = list(DP.CODE_FILES) + ["data/pipeline/runs/x/video/jobs.json", "data/img/a.png"]
    f2, dirs = DP.push_plan("gpu33", files, managed=True)
    assert dirs == [] and not set(DP.CODE_FILES) & set(f2) and "data/img/a.png" in f2   # 不覆盖已发版代码
    f3, dirs3 = DP.push_plan("gpu33", files, managed=False)
    assert f3 == files and dirs3 == list(DP.CODE_DIRS)


def test_golden_worker_quarantined_with_manifest():
    q = ROOT / "data/_quarantine_20261103_golden_o"
    assert not (ROOT / "tools/pipeline/golden_worker.py").exists() and (q / "tools/pipeline/golden_worker.py").is_file()
    m = (q / "MANIFEST.md").read_text(encoding="utf-8")
    assert "dispatch_fanout" in m and "L-151" in m and "W1" in m


def test_w38_accept_anomaly_host_server_uses_http(tmp_path, monkeypatch):
    """W38（11-04）：服务器上（OFFLINE_SELF）共用验收的人数检测走 Q10 常驻检测服务 HTTP（两台之间无 ssh 互信，host=gpu36 恒 rc=255）"""
    from ns_agent.gen_contract import accept as A
    (tmp_path / "config").mkdir()
    (tmp_path / "config/gen_contract.json").write_text(
        json.dumps({"image_thresholds": {"Q10_accept": {"count_host": "http://10.0.0.36:8893"}}}), encoding="utf-8")
    monkeypatch.delenv("OFFLINE_SELF", raising=False)
    assert A.anomaly_host(tmp_path) == "gpu36"                       # 笔记本：照旧经常驻主连接
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    assert A.anomaly_host(tmp_path) == "http://10.0.0.36:8893"
    (tmp_path / "config/gen_contract.json").write_text(json.dumps({"image_thresholds": {"Q10_accept": {"count_host": ""}}}), encoding="utf-8")
    assert A.anomaly_host(tmp_path) == "gpu36"                       # 没配 HTTP 入口 = 原口径
    assert A.anomaly_host(ROOT) == json.loads((ROOT / "config/gen_contract.json").read_text(encoding="utf-8"))[
        "image_thresholds"]["Q10_accept"]["count_host"]             # 真实配置的位置（防夹具与真配置层级不一致）
    seen = {}
    (tmp_path / "config/gen_contract.json").write_text(
        json.dumps({"image_thresholds": {"Q10_accept": {"count_host": "http://10.0.0.36:8893"}}}), encoding="utf-8")
    A.evaluate("x.png", {"items": [{"id": "Q9", "status": "pass", "evidence": {"model": "m"}}]},
               {"asset_refs": {"characters": [{"name": "甲"}]}, "cast": [{"name": "甲"}]}, None, "r",
               q9_fn=lambda p, i, j: p, anomaly_fn=lambda img, cast, host: seen.setdefault("host", host) and {"status": "pass"},
               bundle_fn=lambda img, items, on: {"status": "pass"}, looks={}, root=tmp_path)
    assert seen["host"] == "http://10.0.0.36:8893"


def test_w38_last_frame_checks_use_end_state():
    """W38（ep01 S11）：尾帧的共用验收 / Q10 提示词核对用结束状态（compiler.end_state），首帧仍用 img_prompt"""
    from ns_agent.gen_contract import accept as A
    shot = {"img_prompt": "江予白的左手撑在环形灯架的横杆上，右手从卡槽抽出存储卡",
            "motion_prompt": "camera push in 小幅推近，江予白从相机卡槽抽出存储卡，再把拳头伸进包口夹层——近景，江予白的左手拎着相机包，"
                             "握着存储卡的拳头伸在包口夹层里，视线落在包口，嘴唇抿紧"}
    assert A.shot_description(shot) == shot["img_prompt"]
    end = A.shot_description(shot, "last")
    assert "左手拎着相机包" in end and "撑在环形灯架" not in end
    assert A.shot_description({"img_prompt": "x"}, "last") == "x"                 # 没有运动描述 = 退回首帧描述
    items = A.check_items({"stage": "last", "asset_refs": {}}, shot, looks={}, run="r")
    assert any("左手拎着相机包" in i for i in items) and not any("撑在环形灯架" in i for i in items)
    items1 = A.check_items({"asset_refs": {}}, shot, looks={}, run="r")
    assert any("撑在环形灯架" in i for i in items1)


def test_w38_q10_prompt_check_last_uses_end_state(monkeypatch):
    import importlib
    VA = importlib.import_module("tools.vqa.accept")
    from ns_agent.vqa import client as VC
    from ns_agent.vqa import continuity as CT
    shot = {"img_prompt": "左手撑在横杆上", "motion_prompt": "推近，抽卡——近景，左手拎着相机包"}
    monkeypatch.setattr(CT, "shot_rec", lambda sid: shot)
    seen = []
    monkeypatch.setattr(VC, "generate", lambda req, **k: seen.append(req["text"]) or {"text": '{"people_count":"符合"}'})
    VA.prompt_check("ep01-S11", "x.png", stage="last")
    VA.prompt_check("ep01-S11", "x.png")
    assert "左手拎着相机包" in seen[0] and "撑在横杆" not in seen[0] and "撑在横杆" in seen[1]


def test_l183_description_row_record_only_both_stages():
    """L-183：共用验收“与分镜描述一致”那条首帧 / 尾帧都只记录；其它条不过照样 fail；没答（untested）不改"""
    from ns_agent.gen_contract import accept as A
    items = ["画面里恰好 1 个人", A.DESC_PREFIX + "左手拎包", "画面里没有文字"]
    b = {"status": "fail", "items": [{"n": 1, "ok": True}, {"n": 2, "ok": False, "text": "不符合"}, {"n": 3, "ok": True}]}
    r = A.description_record_only(b, items)
    assert r["status"] == "pass" and r["items"][1]["record_only"] and r["record_only_rows"] == [2]
    b2 = {"status": "fail", "items": [{"n": 1, "ok": False}, {"n": 2, "ok": False}, {"n": 3, "ok": True}]}
    assert A.description_record_only(b2, items)["status"] == "fail"
    assert A.description_record_only({"status": "untested", "items": []}, items)["status"] == "untested"
    st, why = A.verdict({}, {"identity": "pass", "prompt": "pass"}, r)
    assert st == "pass" and not why


def test_l183_qb_count_reuses_q10_count():
    """L-183 c：QB 人数以 Q10 count 为准（last:S6 t9 两路口径打架）；Q10 没结论才自己测"""
    from ns_agent.gen_contract import accept as A
    post = {"items": [{"id": "Q9", "status": "pass", "evidence": {"model": "m"}},
                      {"id": "Q10", "status": "pass", "evidence": {"count": {"status": "pass", "heads": "1/1"}}}]}
    called = []
    res = A.evaluate("x.png", post, {"asset_refs": {"characters": [{"name": "甲"}]}, "cast": [{"name": "甲"}]}, None, "r",
                     q9_fn=lambda p, i, j: p, anomaly_fn=lambda *a, **k: called.append(1) or {"status": "fail"},
                     bundle_fn=lambda img, items, on: {"status": "pass", "items": []}, looks={})
    assert not called and res["label"]["count"] == "pass" and res["anomaly"]["source"] == "Q10 count"
    post["items"][1]["evidence"]["count"] = {"status": "untested"}
    A.evaluate("x.png", post, {"asset_refs": {"characters": [{"name": "甲"}]}, "cast": [{"name": "甲"}]}, None, "r",
               q9_fn=lambda p, i, j: p, anomaly_fn=lambda *a, **k: called.append(1) or {"status": "pass"},
               bundle_fn=lambda img, items, on: {"status": "pass", "items": []}, looks={})
    assert called == [1]


def test_l183_q10_prompt_record_only_on_last(monkeypatch):
    import importlib
    VA = importlib.import_module("tools.vqa.accept")
    monkeypatch.setattr(VA, "prompt_check", lambda sid, image, via, stage="image": {"status": "fail", "why": "action不符"})
    monkeypatch.setattr(VA, "count_check", lambda *a, **k: {"status": "pass"})
    monkeypatch.setattr(VA, "identity", lambda pf: {"status": "pass"})
    monkeypatch.setattr(VA, "outfit", lambda pf, sid, image: {"status": "pass"})
    last = VA.label("ep01-S6", "last", "x.png", {})
    assert last["ok"] == "pass" and last["prompt"]["record_only"] and last["prompt"]["would"] == "fail"
    first = VA.label("ep01-S6", "image", "x.png", {})
    assert first["ok"] == "fail"                                                   # 首帧 Q10 prompt 仍阻断
