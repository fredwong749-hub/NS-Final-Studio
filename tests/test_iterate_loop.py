"""自动迭代 Loop（ARCH）：规则表、dry-run 全流程（不提交真实任务）、3 次上限、暂停 / 恢复、作业丢失、写回、导演接口、下一版沿用。"""
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
for p in (ROOT / "services" / "recipes", ROOT / "tools" / "iterate_loop"):
    sys.path.insert(0, str(p))

import loop as LP  # noqa: E402
import postproc  # noqa: E402
import reviewer as RV  # noqa: E402
import rules as RU  # noqa: E402
import submitter as SB  # noqa: E402
import writeback as WB  # noqa: E402
from ns_recipes import registry as R  # noqa: E402
from ns_schema.shot_spec import Audio, SpeechSeg  # noqa: E402
from store import Store  # noqa: E402
from test_recipes_engine import mk  # noqa: E402


@pytest.fixture
def env(tmp_path):
    learned = tmp_path / "learned.yaml"
    docs = tmp_path / "docs"

    def make(specs, scenario=None, run_id="t1", submitter=None, rules=None):
        store = Store(run_id, base=tmp_path / "runs")
        reg = R.load(learned_path=learned)
        lp = LP.Loop(store, specs=specs, registry=reg, submitter=submitter or SB.DryRunSubmitter(),
                     reviewer=RV.ScriptedReviewer(scenario or {}), post=postproc.DryPostRunner(),
                     rules=rules or RU.load(), assembler=LP.make_assembler(True), learned_path=learned,
                     docs_dir=docs, log=lambda *a: None)
        return lp
    return make, learned, docs


def run(lp, n=100):
    return lp.run(poll_s=0, max_ticks=n, sleep=lambda s: None)


# ---- 规则表 ----
def test_rules_cond_and_order():
    rules = RU.load()
    m = {"J4": 1.3, "J4_z": 3.5, "still_frac": 0.1}
    assert [r["id"] for r in RU.matching(rules, m)] == ["R-J4"]
    assert not RU.matching(rules, {"J4": 1.22, "J4_z": 5})              # 任务阈值 J4>1.25
    m2 = {"cheek_a_drift": 7.0, "still_frac": 0.6}
    assert [r["id"] for r in RU.matching(rules, m2)][:2] == ["R-RED", "R-STILL"]
    assert RU.matching(rules, {"_acceptance_failed": True})[-1]["id"] == "R-DEFAULT"


def test_pre_render_overflow():
    rules = RU.load()
    act = RU.pre_render(rules, [{"rule": "SS-A3", "severity": "block"}])
    assert act["rule"] == "R-OVERFLOW" and act["action"] == "fail"
    assert RU.pre_render(rules, [{"rule": "SS-A3", "severity": "warn"}]) is None


def test_failures_against_acceptance():
    acc = {"still_frac_max": 0.5, "j4_max": 1.2, "j4_z_max": 3.0, "sface_ref_min": 0.3, "lipsync_corr_min": None}
    f = RV.failures({"still_frac": 0.6, "J4": 1.3, "J4_z": 1.0, "sface_ref_min": 0.2, "lipsync_corr": 0.0}, acc)
    assert {x["metric"] for x in f} == {"still_frac", "sface_ref_min"}


# ---- dry-run 全流程 ----
def test_dry_run_retry_then_pass(env):
    make, learned, docs = env
    lp = make([mk()], {"ep99-S1": [{"still_frac": 0.8}, {}]})
    lp.init(99)
    st = run(lp)
    sh = st["shots"]["ep99-S1"]
    assert st["status"] == "version_done"
    assert sh["status"] == "passed" and sh["renders"] == 2
    assert sh["actions"][0]["rule"] == "R-STILL" and sh["actions"][0]["action"] == "reseed"
    eff = st["versions"]["1"]["effects"]
    assert eff and eff[0]["ok"] is True and eff[0]["kind"] == "ladder"
    assert (docs / "v1_review.md").exists() and (docs / "v1_director_queue.md").exists()
    assert "ep99-S1" in (docs / "v1_review.md").read_text(encoding="utf-8")
    assert st["versions"]["1"]["assemble"]["dry_run"]
    kinds = [e["kind"] for e in lp.store.events()]
    assert "init" in kinds and "action" in kinds and "version_done" in kinds
    assert "effect" in kinds and "error" not in kinds   # V2：effect 事件曾因 kind 撞名抛 TypeError


def test_max_three_renders_then_owner(env):
    make, *_ = env
    lp = make([mk()], {"ep99-S1": [{"still_frac": 0.9}]})
    lp.init(99)
    st = run(lp)
    sh = st["shots"]["ep99-S1"]
    assert sh["renders"] == 3 and sh["status"] == "owner"
    acts = [a["action"] for a in sh["actions"]]
    assert acts == ["reseed", "override"]                    # last_frame_mode 已是 none → 跳过；第 3 步加 Motion Repair
    assert sh["overrides"]["loras.motion_repair"]["enabled"] is True


def test_overflow_goes_to_writer_without_render(env):
    make, *_ = env
    sp = mk(audio=Audio(soundscape_en="x", dialogue=[SpeechSeg(speaker="林晚", text="x", t0=1, t1=5.95,
                                                               t_source="script")]))
    lp = make([sp])
    lp.init(99)
    st = run(lp)
    sh = st["shots"]["ep99-S1"]
    assert sh["status"] == "needs_writer" and sh["renders"] == 0 and "R-OVERFLOW" in sh["note"]


def test_pause_resume_and_persistence(env):
    make, *_ = env
    lp = make([mk(), mk(id="ep99-S2", index=2)], {"ep99-S1": [{"J4": 1.5, "J4_z": 4}, {}]})
    lp.init(99)
    run(lp, n=2)
    assert lp.state["status"] == "running"
    lp.store.pause("test")
    assert lp.tick() is False
    lp.store.resume()
    lp2 = make([mk(), mk(id="ep99-S2", index=2)], {"ep99-S1": [{"J4": 1.5, "J4_z": 4}, {}]})   # 新进程：从磁盘恢复
    assert lp2.state["shots"]["ep99-S1"]["status"] != "pending"
    lp2.sub.jobs = lp.sub.jobs                                 # 同一个假 API（模拟 API 进程没重启）
    st = run(lp2)
    assert st["status"] == "version_done"
    assert all(s["status"] == "passed" for s in st["shots"].values())


class LosingSubmitter(SB.DryRunSubmitter):
    """第一次轮询返回“丢失”（模拟 API 重启）"""
    def __init__(self):
        super().__init__()
        self.lost_once = False

    def poll(self, job_id, plan=None):
        if not self.lost_once:
            self.lost_once = True
            return {"state": "lost"}
        return super().poll(job_id, plan)


def test_lost_job_resubmitted_not_counted(env):
    make, *_ = env
    lp = make([mk()], submitter=LosingSubmitter())
    lp.init(99)
    st = run(lp)
    sh = st["shots"]["ep99-S1"]
    assert sh["status"] == "passed" and sh["renders"] == 1 and sh["lost"] == 1


def test_needs_api_for_ref2va_with_api_submitter(env):
    make, *_ = env

    class FakeApi(SB.DryRunSubmitter):
        dry = False
    lp = make([mk()], submitter=FakeApi(graph_passthrough=False))
    lp.init(99)
    lp.state["shots"]["ep99-S1"]["recipe_override"] = "two_person_ref2va"
    st = run(lp)
    assert st["shots"]["ep99-S1"]["status"] == "needs_api"


def test_writeback_promotes_and_registry_applies(tmp_path):
    learned = tmp_path / "learned.yaml"
    md = tmp_path / "LEARNED_SPECS.md"
    md.write_text("# x\n", encoding="utf-8")
    cfg = RU.load()
    ef = {"kind": "param", "recipe": "walk_fullbody", "path": "loras.motion_repair.enabled", "value": True,
          "rule": "R-STILL", "ok": True, "shot": "s", "run": "r", "version": 1, "before": {}, "after": {}, "plans": []}
    ch = []
    for i in range(5):   # 5 个不同的镜：前 3 个是“学到它的镜”，s3、s4 是留出镜（ITERAUDIT 留出复核）
        ch += WB.record([{**ef, "shot": f"s{i}"}], cfg, learned_path=learned, specs_md=md)
    assert [c["status"] for c in ch] == ["建议", "确认"]
    data = yaml.safe_load(learned.read_text(encoding="utf-8"))
    assert data["entries"][0]["n_ok"] == 5
    assert "D. 自动迭代写回" in md.read_text(encoding="utf-8")
    reg = R.load(learned_path=learned)
    rc = reg.resolve("walk_fullbody")
    assert rc["loras"]["motion_repair"]["enabled"] is True
    assert rc["provenance"]["loras.motion_repair.enabled"]["learned"] is True
    assert reg.validate() == []


def test_director_verdict_reseeds(env):
    make, *_ = env
    lp = make([mk()])
    lp.init(99)
    run(lp)
    assert lp.state["shots"]["ep99-S1"]["status"] == "passed"
    lp.state["status"] = "running"
    lp.store.verdicts_path.parent.mkdir(parents=True, exist_ok=True)
    lp.store.verdicts_path.write_text(json.dumps({"ep99-S1": {"verdict": "fail", "issues": ["鬼影"], "action": "reseed"}}),
                                      encoding="utf-8")
    st = run(lp)
    sh = st["shots"]["ep99-S1"]
    assert sh["renders"] == 2 and sh["actions"][-1]["rule"] == "R-DIRECTOR" and sh["status"] == "passed"


def test_next_version_carries_unchanged(env):
    make, *_ = env
    lp = make([mk()])
    lp.init(99)
    run(lp)
    n_jobs = lp.sub.n
    lp.next_version()
    st = run(lp)
    assert st["version"] == 2 and st["shots"]["ep99-S1"]["status"] == "passed"
    assert lp.sub.n == n_jobs                                  # 计划没变 → 不重出


def test_recipe_plan_body_for_api():
    from test_recipe_plan_api import _plan
    p = _plan()
    rp = SB.recipe_plan_body(p, with_graph=False)
    assert rp == {"plan_hash": p["plan_hash"], "recipe_id": "static_emotion"}
    ref = _plan(recipe_id="two_person_ref2va")
    rp2 = SB.recipe_plan_body(ref, with_graph=True)
    from ns_agent import asset_refs as _AR    # 总调度 19:5x：期望从 face_of 取（K-OPS-E29 身份脸唯一入口），不写死任何脸
    import importlib.util as _u
    _sp = _u.spec_from_file_location("runs_for_iter_test", ROOT / "tools" / "autopilot" / "runs.py")
    _RN = _u.module_from_spec(_sp)
    _sp.loader.exec_module(_RN)
    assert rp2["graph"] == ref["graph"] and rp2["images"] == {"@ref:林晚": _AR.face_of(_RN.primary_run(), "lin_wan")}
    assert ref["lane"]["only"] == ["0", "1", "3"]                # Ref2VA 只在 gpu33
    off = SB.ApiSubmitter("http://127.0.0.1:1", graph_passthrough=False)
    assert off.submit(ref, 0)["state"] == "needs_api"           # 接入点没开：不提交


# ---- V2 2026-10-31：与 LAB / CONSIST 共用道，外部负载 ≥2 的道不派 ----
def test_lane_allocator_respects_external_load():
    la = SB.LaneAllocator()
    # 不给外部负载 = 旧行为
    assert la.pick(False, {}) == 0
    # gpu33:0 已有 2 个（别人的），gpu33:1 有 1 个 → 派到负载最小的空道
    ext = {"0": 2, "1": 1, "3": 0, "gpu36:0": 2, "gpu36:1": 2}
    assert la.pick(False, {}, ext) == 3
    # 全满 → 不派
    full = {"0": 2, "1": 2, "3": 2, "gpu36:0": 3, "gpu36:1": 2, "gpu36:2": 2}
    assert la.pick(False, {}, full) is None
    assert la.pick(True, {}, full) is None
    assert la.pick(True, {}, {"gpu36:2": 1}) == "gpu36:2"


def test_lane_load_counts_comfy_queue_and_api_queued():
    jobs = [{"gpu": "gpu36:1", "state": "running"}, {"gpu": "gpu36:1", "state": "queued"},
            {"gpu": 0, "state": "done"}, {"gpu": 3, "state": "running"}]
    # gpu36:1 ComfyUI 里 1 个在跑（就是 API 那个）+ API 还有 1 个排队 = 2；gpu33:3 ComfyUI 查不到 → 用 API running
    ll = SB.lane_load(jobs, {"gpu36:1": 1, "3": None, "1": 2})
    assert ll["gpu36:1"] == 2 and ll["3"] == 1 and ll["1"] == 2 and ll.get("0", 0) == 0


def test_loop_skips_lanes_full_by_others(env):
    make, _, _ = env

    class Busy(SB.DryRunSubmitter):
        def lane_load(self):
            return {"0": 2, "1": 2, "3": 2, "gpu36:0": 2, "gpu36:1": 2, "gpu36:2": 2}

    lp = make([mk()], submitter=Busy())
    lp.init(2)
    run(lp, 5)
    assert lp.state["shots"]["ep99-S1"]["status"] == "queued"   # 道全满，没提交


def test_lane_only_restricts_ref2va_to_gpu33():
    la = SB.LaneAllocator()
    assert la.pick(False, {}, {"0": 2, "1": 0}, only=["0", "1", "3"]) == 1
    assert la.pick(False, {}, {"0": 2, "1": 2, "3": 2, "gpu36:0": 0}, only=["0", "1", "3"]) is None


def test_other_face_not_in_identity_gate():
    shot = {"identity": {"people": {"lin_wan": {"n": 10, "ref_cos_med": 0.41, "self_cos_min": 0.7},
                                    "other": {"n": 10, "ref_cos_med": 0.12, "self_cos_min": 0.8}}}}
    assert RV.flatten(shot)["sface_ref_min"] == 0.41


def test_post_only_step_marks_same_source(env):
    """V2 20:50：R-RED 第 1 步只改后处理（skin_guard）→ 新 plan_hash 但视频源不变；结果里记 post_only_of，
    避免把“后处理版”误当成新出片 / 新提示词出片（PROMPT 发现两份 md5 相同）"""
    make, _, _ = env
    lp = make([mk()], {"ep99-S1": [{"cheek_red_max": 0.6}, {"cheek_red_max": 0.6}, {}]})
    lp.init(99)
    run(lp)
    import json as _j
    res = sorted((lp.store.dir / "results" / "ep99-S1").glob("*.json")) if (lp.store.dir / "results" / "ep99-S1").exists() \
        else sorted(lp.store.dir.glob("results/*ep99-S1*.json"))
    evs = [e for e in lp.store.events() if e["kind"] == "action"]
    assert evs[0]["action"] == "post"
    sh = lp.state["shots"]["ep99-S1"]
    assert sh["renders"] == 2 and "post_only_of" not in sh       # 第 2 次是真出片，标记清掉


# ---- ITERAUDIT 2026-11-01：未测 ≠ 通过；learned 自动确认要留出复核 ----
def test_missing_metric_with_threshold_is_untested_not_pass():
    acc = {"still_frac_max": 0.5, "sface_ref_min": 0.3, "j4_max": 1.2, "lipsync_corr_min": None}
    f = RV.failures({"still_frac": 0.2}, acc)          # 没检测到脸、没有 J4
    got = {x["metric"]: x for x in f}
    assert set(got) == {"sface_ref_min", "J4"}
    assert all(x["untested"] and x["value"] is None for x in f)
    assert "lipsync_corr" not in got                    # 阈值 None = 不适用，不算未测


def test_flatten_records_untested_metrics():
    m = RV.flatten({"motion": {"still_frac": 0.1}, "identity": {"people": {}}})
    assert m["still_frac"] == 0.1 and "sface_ref_min" not in m
    assert "sface_ref_min" in m["_untested"] and "J4" in m["_untested"]
    assert RV.failures(m, {"sface_ref_min": 0.3})[0]["untested"] is True


def test_dry_run_missing_identity_not_passed(env):
    make, *_ = env
    lp = make([mk()], {"ep99-S1": [{"sface_ref_min": None}]})
    lp.init(99)
    st = run(lp)
    sh = st["shots"]["ep99-S1"]
    assert sh["status"] != "passed"                      # 每次身份都没测到 → 永远不算通过（以前直接 passed）
    assert any(f.get("untested") for f in sh["last_failures"])


def test_writeback_same_shot_never_auto_confirms(tmp_path):
    learned, md = tmp_path / "learned.yaml", tmp_path / "LEARNED_SPECS.md"
    md.write_text("# x\n", encoding="utf-8")
    cfg = RU.load()
    ef = {"kind": "param", "recipe": "walk_fullbody", "path": "loras.motion_repair.enabled", "value": True,
          "rule": "R-STILL", "ok": True, "shot": "s", "run": "r", "version": 1, "before": {}, "after": {}, "plans": []}
    ch = []
    for _ in range(8):                                   # 同一镜成功 8 次：只到“建议”
        ch += WB.record([ef], cfg, learned_path=learned, specs_md=md)
    assert [c["status"] for c in ch] == ["建议"]
    e = yaml.safe_load(learned.read_text(encoding="utf-8"))["entries"][0]
    assert e["holdout"]["n"] == 0
    # 留出镜上失败多 → 仍不确认
    for i, ok in enumerate([True, False, False]):
        ch += WB.record([{**ef, "shot": f"h{i}", "ok": ok}], cfg, learned_path=learned, specs_md=md)
    assert all(c["status"] != "确认" for c in ch)
    # 留出镜成功够数、成功率够 → 确认
    for i in range(10):
        ch += WB.record([{**ef, "shot": f"g{i}"}], cfg, learned_path=learned, specs_md=md)
    assert ch[-1]["status"] == "确认"
