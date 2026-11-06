"""L-204（项目方 11-06：每镜最多 3 次，过了就用，否则自动采用最好一版继续；绝不停集）—— REVIEW-RUN 审出的 producer / sop_gate 死胡同：
D2 硬上限静默吞单 · D4 换代中尾帧被挡 · D5 作废尾帧账本次数不清 · D6 尾帧只认当前首帧的版本 · D7 用尽 / 采用后驳回记录不清 ·
D8 全部看镜头 / 太像时自动加轮、轮也用尽的兜底（尾帧 I2VA 回退 / 首帧 gaze_waived 采用）· D9 sop_gate Q9 认 review_needed ·
D11 旧首帧视线缺陷补判重出 · 不变量：ready 却派不出 → stuck_object。全部临时目录 + mock，不碰 GPU / 真实数据。"""
import importlib.util
import json
import sys
import threading
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for _p in ("tools/autopilot", "services/render_router", "services/agent", "packages/schema", "services/recipes"):
    if str(ROOT / _p) not in sys.path:
        sys.path.insert(0, str(ROOT / _p))
import producer as PR  # noqa: E402
from ns_render import pipeline as P  # noqa: E402
from ns_render import frame_edit as FE  # noqa: E402

SRC = (ROOT / "tools/autopilot/producer.py").read_text(encoding="utf-8")


# ---------------------------------------------------------------- 夹具
def _pr(tmp_path):
    pr = object.__new__(PR.Producer)
    pr.p = PR.Paths(root=tmp_path, pd=tmp_path / "pd", run_id="tv_l204")
    pr.p.pd.mkdir(parents=True, exist_ok=True)
    pr.mu = threading.RLock()
    pr.events = []
    pr.logf = lambda ev, **kw: pr.events.append((ev, kw))
    pr.inflight = {}
    return pr


def _evs(pr, name):
    return [kw for ev, kw in pr.events if ev == name]


def _it(i, st="fail", **ev):
    return {"id": i, "status": st, "detail": "x", "evidence": ev}


def _pf(ok, *items, model="qwen3-vl"):
    its = list(items)
    if not any(i["id"] == "Q1" for i in its):
        its.append(_it("Q1", "pass", value=0.7))
    if not any(i["id"] == "Q9" for i in its):
        its.append(_it("Q9", "pass", model=model))
    return {"ok": ok, "blocking": [i["id"] for i in its if i["status"] == "fail"], "items": its, "reasons": []}


def _gaze_pf(ok=False, q1=0.5):
    return {"ok": ok, "blocking": [] if ok else ["Q9"], "reasons": [],
            "items": [_it("Q1", "pass", value=q1), _it("Q9", "fail" if not ok else "na", defects=["eye_contact"], model="qwen3-vl")]}


def _take(stage, n, pf, created="2026-11-06T10:00:00", **kw):
    return {"stage": stage, "n": n, "file": f"renders/x/{stage}_{n:03d}.png", "created_at": created, "postflight": pf, **kw}


def _obj(oid, **kw):
    kind, sid = oid.split(":", 1)
    return {"id": oid, "kind": kind, "shot": sid, "ep": 1, "status": "ready", "attempts": 0, **kw}


def _reg(*objs):
    shots = {}
    for o in objs:
        shots.setdefault(o["shot"], {"shot": o["shot"], "index": 1, "objects": {}})["objects"][o["kind"]] = o
    for S in shots.values():
        S["objects"].setdefault("first", _obj(f"first:{S['shot']}", status="passed"))
        S["objects"].setdefault("last", _obj(f"last:{S['shot']}", status="passed"))
    return {"episodes": [{"ep": 1, "shots": list(shots.values())}]}


# ================================================================ D2 硬上限不再静默吞单
def test_d2_retry_yaml_cap_is_30_and_code_default_matches(monkeypatch):
    y = (ROOT / "config/policies/retry.yaml").read_text(encoding="utf-8")
    assert "per_stage_24h: 30" in y and "L-204" in y
    assert PR.HARD_CAP_DEFAULT == 30
    monkeypatch.delenv("NS_PRODUCER_HARD_CAP", raising=False)
    assert PR.hard_cap_per_stage() == 30


def test_d2_dispatch_calls_cap_exhaust_instead_of_silent_continue():
    body = SRC.split("    def dispatch_frames(", 1)[1].split("    def sop_gate_block", 1)[0]
    assert "if self.hard_capped(o):" in body and "self.cap_exhaust(o)" in body
    assert "self.void_reset(o, led)" in body                                 # D5 也在派单循环里


def test_d2_cap_exhaust_marks_best_effort_and_clears_reject(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    oid = "first:ep01-S3"
    pr.led_update(oid, hard_capped={"t": time.time(), "at": PR.iso(), "n": 30, "lim": 30}, tries=1)
    PR.js(pr.p.rejects, {oid: {"reject_n": 4, "plan": [{"preset": "frame_v9"}], "regen": {"by": "x"}}})
    gates = []
    monkeypatch.setattr(P, "mutate_takes", lambda sid, fn, **kw: gates.append((sid, kw.get("op"))))
    assert pr.cap_exhaust(_obj(oid)) is True
    led = pr.ledger()[oid]
    assert led["final"] == "best_effort" and led["redo_exhausted"] is True and "L-204" in led["reason"]
    assert PR.jl(pr.p.rejects)[oid]["cleared"]["by"] == "producer"            # D7：换代 / 驳回记录不再“已在重出中”
    assert gates == [("ep01-S3", "reject_cleared")]
    assert _evs(pr, "hard_cap_exhausted")[0]["obj"] == oid
    assert pr.cap_exhaust(_obj(oid)) is False                                 # 不重复标
    # 用尽 + 尽力 → adopt_best_effort_sweep 的条件满足（FIX-A 口径：redo_exhausted 即可）
    monkeypatch.setattr(PR, "review_adopt_auto", lambda root=ROOT: True)
    monkeypatch.setattr(PR, "review_adopt", lambda p, o, by="", relaxed=False: 7)
    assert pr.adopt_best_effort_sweep(_reg(_obj(oid, status="best_effort")), every_s=0) == [oid]
    assert pr.ledger()[oid]["final"] == "passed" and pr.ledger()[oid]["hard_capped"] is None


def test_d2_cap_blocked_and_registry_not_waiting_for_lane():
    t = time.time()
    assert PR.cap_blocked({"hard_capped": {"t": t - 60}}, t)
    assert not PR.cap_blocked({"hard_capped": {"t": t - 25 * 3600}}, t)                             # 24 小时过了
    assert not PR.cap_blocked({"hard_capped": {"t": t - 60}, "cap_extra": {"t": t - 10}}, t)         # 人工 uncap 之后
    assert PR.cap_blocked({"hard_capped": {"t": t - 60}, "cap_extra": {"t": t - 120}}, t)            # 旧 uncap 不算
    led = {"first:ep01-S3": {"hard_capped": {"t": t - 60, "n": 30, "lim": 30}, "tries": 2, "reason": "封顶"}}
    o = PR._frame_obj("first", "image", "ep01-S3", 1, {"active": {}, "takes": []}, {}, led, {}, {}, False, deps_ok=True)
    assert o["status"] == "best_effort" and o.get("cap_blocked") and o.get("waiting_for") != "空闲道"
    led2 = {"first:ep01-S3": {"hard_capped": {"t": t - 60}, "cap_extra": {"t": t - 10, "n": 3}, "tries": 0}}
    o2 = PR._frame_obj("first", "image", "ep01-S3", 1, {"active": {}, "takes": []}, {}, led2, {}, {}, False, deps_ok=True)
    assert o2["status"] == "ready"                                                                    # uncap 后照常派


# ================================================================ D4 换代中（regen_keep）不挡尾帧
def test_d4_regen_keep_counts_as_first_ok():
    assert PR.first_ok_for_last({"status": "passed"}) and PR.first_ok_for_last({"status": "ready", "regen_keep": "v3"})
    assert not PR.first_ok_for_last({"status": "ready"})
    td = {"active": {"image": 3, "last": 2}, "takes": [_take("image", 3, _pf(True), "2026-11-06T09:00:00"),
                                                       _take("last", 2, _pf(True), "2026-11-06T10:00:00")]}
    lo = {"status": "passed", "take": 2}
    assert PR.last_consistent(td, {"status": "ready", "regen_keep": "v3", "redo": True}, lo) is lo    # 换代中：尾帧不作废
    assert PR.last_consistent(td, {"status": "ready"}, lo)["voided"]                                  # 首帧真没过：照旧作废
    o = PR._frame_obj("last", "last", "ep01-S1", 1, td, {}, {}, {}, {}, False, deps_ok=PR.first_ok_for_last({"status": "ready", "regen_keep": "v3"}))
    assert o["status"] == "passed"
    assert "deps_ok=first_ok_for_last(fo)" in SRC


def test_d4_last_paired_with_first():
    fa = {"n": 3, "file": "renders/x/image_003.png", "created_at": "2026-11-06T09:00:00"}
    assert PR.last_paired({"from_first": 3}, fa) and not PR.last_paired({"from_first": 2, "created_at": "2026-11-06T11:00:00"}, fa)
    assert PR.last_paired({"references": ["data/renders/x/image_003.png"], "created_at": "2026-11-06T01:00:00"}, fa)
    assert PR.last_paired({"created_at": "2026-11-06T09:30:00"}, fa) and not PR.last_paired({"created_at": "2026-11-06T08:00:00"}, fa)
    assert PR.last_paired({"created_at": "2026-11-06T08:00:00"}, None)
    td = {"active": {"image": 3, "last": 1}, "takes": [_take("image", 3, _pf(True), "2026-11-06T09:00:00"),
                                                       _take("last", 1, _pf(True), "2026-11-06T08:00:00", from_first=2)]}
    assert PR.last_consistent(td, {"status": "passed"}, {"status": "passed"})["voided"]               # from_first 指旧首帧 → 作废


# ================================================================ D5 作废尾帧账本清零
def test_d5_void_reset_clears_ledger_tries(tmp_path):
    pr = _pr(tmp_path)
    oid = "last:ep01-S2"
    pr.led_update(oid, tries=3, final="best_effort", history=[{"try": 1, "take": 5}], gaze_rounds=2, last_unavailable=True)
    o = _obj(oid, voided=True, reason="首帧换过，尾帧作废", attempts=0)
    led = pr.void_reset(o, pr.ledger()[oid])
    assert led["tries"] == 0 and led["final"] is None and led["gaze_rounds"] is None and led["last_unavailable"] is None
    assert led["history"][0]["before_void"] and led["voided_at"]
    assert _evs(pr, "last_void_reset")[0]["tries_before"] == 3
    assert max(int(led.get("tries") or 0), int(o["attempts"])) + 1 <= PR.MAX_TRIES                   # 下一次派得出


# ================================================================ D6 尾帧只认由当前首帧做的版本
def test_d6_review_pick_last_only_from_current_first(tmp_path, monkeypatch):
    td = {"active": {"image": 2}, "takes": [
        _take("image", 1, _pf(True), "2026-11-06T08:00:00"), _take("image", 2, _pf(True), "2026-11-06T09:00:00"),
        _take("last", 1, _pf(True, _it("Q1", "pass", value=0.9)), "2026-11-06T08:30:00"),                       # 由旧首帧 v1 做的、分更高
        _take("last", 2, _pf(True, _it("Q1", "pass", value=0.6)), "2026-11-06T09:30:00"),                       # 由当前首帧做的
        _take("last", 3, _pf(False, _it("Q2")), "2026-11-06T09:40:00")]}
    assert PR.review_pick(td, "last") == 2 and PR.review_pick_relaxed(td, "last") == 2
    assert PR.review_pick(td, "image") == 1                                                            # 首帧不受影响（v1 分高）
    pr = _pr(tmp_path)
    monkeypatch.setattr(P, "load_takes", lambda sid: td)
    assert pr._best("ep01-S1", "last", [{"take": 1}, {"take": 2}, {"take": 3}]) == 2
    # review_adopt 指名旧首帧的尾帧 → 拒绝（D6），不 set_active
    acts = []
    monkeypatch.setattr(P, "set_active", lambda *a, **k: acts.append(a))
    monkeypatch.setattr(P, "mutate_takes", lambda *a, **k: acts.append(("mutate",)))
    assert PR.review_adopt(pr.p, "last:ep01-S1", n=1, relaxed=True) is None and acts == []
    assert any(x.get("rule") == "L-204 D6" for x in map(json.loads, pr.p.log.read_text(encoding="utf-8").splitlines()))


def test_d6_last_requeued_clears_history():
    body = SRC.split("def master_approve(", 1)[1].split("\ndef ", 1)[0]
    assert "history=[]" in body and "gaze_rounds=None" in body and "last_unavailable=None" in body


# ================================================================ D7 用尽 / 采用后清驳回记录；驳回重置阶梯
def test_d7_escalate_exhausted_clears_reject(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    oid = "first:ep01-S1"
    PR.js(pr.p.rejects, {oid: {"reject_n": 2, "plan": [{"preset": "frame_v9"}]}})
    pr.led_update(oid, redo_tries=1, ladder_plan=[{"preset": "frame_v9_heavy"}], redo_history=[{"blocking": ["Q9"]}])
    monkeypatch.setattr(PR, "asset_hold_objects", lambda d, *a: set())
    monkeypatch.setattr(PR, "redo_inputs_changed_v2", lambda *a: None)
    monkeypatch.setattr(PR, "job_sig", lambda paths, sid: "S1")
    monkeypatch.setattr(P, "mutate_takes", lambda *a, **k: None)
    reg = _reg(_obj(oid, status="pending", escalate=True))
    assert pr.escalate_exhausted(reg)["best_effort"] == 1
    assert PR.jl(pr.p.rejects)[oid]["cleared"] and pr.ledger()[oid]["final"] == "best_effort"
    assert [ev for ev, _ in pr.events if ev == "reject_cleared"]


def test_d7_master_reject_resets_ladder_state(tmp_path, monkeypatch):
    paths = PR.Paths(root=tmp_path, pd=tmp_path / "pd", run_id="tv_l204")
    paths.pd.mkdir(parents=True, exist_ok=True)
    PR.js(paths.ledger, {"first:ep01-S1": {"redo_exhausted": True, "ladder_plan": [{"preset": "frame_v9_heavy"}], "final": "best_effort"}})
    monkeypatch.setattr(P, "mutate_takes", lambda *a, **k: None)
    assert PR.master_reject(paths, "first:ep01-S1", 0, "换代", ["frame_v9"], None, "T") == 0
    led = PR.jl(paths.ledger)["first:ep01-S1"]
    assert led["redo_exhausted"] is None and led["ladder_plan"] == [] and led["redo_tries"] == 0


# ================================================================ D8 看镜头 / 太像：加轮 → 轮也用尽的兜底
def _gaze_td(stage, n_takes=3, first_n=2):
    takes = [_take("image", first_n, _pf(True), "2026-11-06T09:00:00")] if stage == "last" else []
    takes += [_take(stage, i, _gaze_pf(q1=0.4 + 0.1 * i), f"2026-11-06T1{i}:00:00") for i in range(1, n_takes + 1)]
    return {"active": {"image": first_n} if stage == "last" else {}, "takes": takes}


def test_d8_first_round_grants_fresh_seed_round(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    oid = "first:ep01-S1"
    monkeypatch.setattr(P, "load_takes", lambda sid: _gaze_td("image"))
    pr.led_update(oid, tries=3, final="best_effort", history=[{"take": 1}, {"take": 2}, {"take": 3}])
    assert pr.gaze_fallback(_obj(oid, status="best_effort"), pr.ledger()[oid]) == -1
    led = pr.ledger()[oid]
    assert led["tries"] == 0 and led["final"] is None and led["gaze_rounds"] == 1 and led["cap_extra"]["n"] == PR.MAX_TRIES
    assert all(h["before_gaze_round"] for h in led["history"])
    assert _evs(pr, "gaze_round")[0]["round"] == 1
    # 登记表：ready、带 gaze_round → seed_pick 换种子键
    o = PR._frame_obj("first", "image", "ep01-S1", 1, {"active": {}, "takes": []}, {}, {oid: led}, {}, {}, False, deps_ok=True)
    assert o["status"] == "ready" and o["gaze_round"] == 1
    from ns_agent import asset_refs as AR
    monkeypatch.setattr(AR, "pf_on", lambda k: False)
    s0, _ = pr.seed_pick(_obj(oid), 1)
    s1, _ = pr.seed_pick(_obj(oid, gaze_round=1), 1)
    s2, _ = pr.seed_pick(_obj(oid, gaze_round=2), 1)
    assert len({s0, s1, s2}) == 3


def test_d8_not_triggered_when_adult_or_text_blocks(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    td = {"active": {}, "takes": [_take("image", 1, _pf(False, _it("Q6")))]}       # 成人硬项，不是 never_adopt → 不归 D8
    monkeypatch.setattr(P, "load_takes", lambda sid: td)
    assert pr.gaze_fallback(_obj("first:ep01-S1"), {"tries": 3, "final": "best_effort"}) is None and not pr.events


def test_d8_last_rounds_exhausted_falls_back_to_i2va(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    oid = "last:ep01-S1"
    td = _gaze_td("last", first_n=2)
    written = {}

    def _mut(sid, fn, **kw):
        fn(td)
        written[sid] = kw.get("op")
    monkeypatch.setattr(P, "load_takes", lambda sid: td)
    monkeypatch.setattr(P, "mutate_takes", _mut)
    pr.led_update(oid, tries=3, final="best_effort", gaze_rounds=PR.GAZE_EXTRA_ROUNDS)
    assert pr.gaze_fallback(_obj(oid, status="best_effort"), pr.ledger()[oid]) == 2
    led = pr.ledger()[oid]
    assert led["last_unavailable"] is True and led["last_frame_fallback"] == "i2va" and led["last_fallback_first_n"] == 2 and led["final"] == "best_effort"
    fb = td["last_frame_fallback"]                                      # 视频侧唯一读取点：takes.json 顶层，绑定当时的首帧
    assert fb["mode"] == "i2va" and fb["first_n"] == 2 and fb["rule"] == "L-204 D8" and written == {"ep01-S1": "last_frame_fallback"}
    assert _evs(pr, "last_unavailable")[0]["fallback"] == "i2va"
    iss = json.loads((tmp_path / "data/pipeline/issues.jsonl").read_text(encoding="utf-8").splitlines()[0])
    assert iss["who"] == "PRODUCER" and iss["blocking"] is False and "I2VA" in iss["what"]
    # 登记表：尾帧 best_effort + 回退标记 → 视频对象放行；首帧换了 → 回退作废、尾帧重出（voided）
    o = PR._frame_obj("last", "last", "ep01-S1", 1, td, {}, {oid: led}, {}, {}, False, deps_ok=True)
    assert o["status"] == "best_effort" and o["last_unavailable"] and o["last_frame_fallback"] == "i2va"
    td2 = {**td, "active": {"image": 5}}
    o2 = PR._frame_obj("last", "last", "ep01-S1", 1, td2, {}, {oid: led}, {}, {}, False, deps_ok=True)
    assert o2["status"] == "ready" and o2["voided"]
    # 终态：sweep 不再反复试采用 / 反复写回退
    monkeypatch.setattr(PR, "review_adopt_auto", lambda root=ROOT: True)
    calls = []
    monkeypatch.setattr(PR, "review_adopt", lambda *a, **k: calls.append(1) or None)
    assert pr.adopt_best_effort_sweep(_reg(_obj(oid, status="best_effort")), every_s=0) == [] and calls == []


def test_d8_first_rounds_exhausted_adopts_best_with_gaze_waived(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    oid = "first:ep01-S1"
    td = {"active": {}, "takes": [_take("image", i, _gaze_pf(q1=0.4 + 0.1 * i)) for i in (1, 2, 3)]}
    acts = []

    def _mut(sid, fn, **kw):
        fn(td)
    monkeypatch.setattr(P, "load_takes", lambda sid: td)
    monkeypatch.setattr(P, "mutate_takes", _mut)
    monkeypatch.setattr(P, "set_active", lambda sid, stage, n, **k: acts.append((stage, n)))
    pr.led_update(oid, tries=3, final="best_effort", gaze_rounds=PR.GAZE_EXTRA_ROUNDS)
    assert pr.gaze_fallback(_obj(oid, status="best_effort"), pr.ledger()[oid]) == 3          # 分最高的 v3
    assert acts == [("image", 3)]
    pf3 = td["takes"][2]["postflight"]
    assert pf3["review_needed"] and pf3["ok"] is True and pf3["gaze_waived"]["rule"] == "L-204 D8"
    led = pr.ledger()[oid]
    assert led["final"] == "passed" and led["gaze_waived"] is True
    assert _evs(pr, "passed")[0]["gaze_waived"] is True
    assert (tmp_path / "data/pipeline/issues.jsonl").exists()
    # 没放开 waive 时照旧拒绝（L-200 不变）
    acts.clear()
    td["takes"][2]["postflight"] = _gaze_pf(q1=0.7)
    assert PR.review_adopt(pr.p, oid, n=3, relaxed=True) is None and acts == []


def test_d8_first_prefers_non_gaze_take_when_available(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    oid = "first:ep01-S1"
    fl_pf = {"ok": False, "blocking": ["Q9"], "reasons": [], "items": [_it("Q1", "pass", value=0.9), _it("Q9", "fail", defects=["eye_contact"], model="m")]}
    td = {"active": {}, "takes": [_take("image", 1, fl_pf), _take("image", 2, _gaze_pf(q1=0.5))]}
    monkeypatch.setattr(P, "load_takes", lambda sid: td)
    monkeypatch.setattr(P, "mutate_takes", lambda sid, fn, **kw: fn(td))
    acts = []
    monkeypatch.setattr(P, "set_active", lambda sid, stage, n, **k: acts.append(n))
    # 全部 never_adopt；但 candidates 里没有“不看镜头”的 → 取最好一版 v1（Q1 0.9）
    pr.led_update(oid, tries=3, final="best_effort", gaze_rounds=PR.GAZE_EXTRA_ROUNDS)
    assert pr.gaze_fallback(_obj(oid, status="best_effort"), pr.ledger()[oid]) == 1 and acts == [1]


def test_d8_no_adoptable_pool_logged_and_reported_once(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    oid = "first:ep01-S1"
    pf = _gaze_pf(q1=0.6)
    pf["items"].append(_it("Q6", "fail", model="m"))                       # 看镜头 + 成人硬项：D8 兜底也不能收
    td = {"active": {}, "takes": [_take("image", i, pf) for i in (1, 2)]}
    monkeypatch.setattr(P, "load_takes", lambda sid: td)
    pr.led_update(oid, tries=3, final="best_effort", gaze_rounds=PR.GAZE_EXTRA_ROUNDS)
    for _ in range(3):                                                      # 扫每 2 分钟一次：同一批候选只记一次 + 报一次卡点
        assert pr.gaze_fallback(_obj(oid, status="best_effort"), pr.ledger()[oid]) is None
    assert len(_evs(pr, "gaze_fallback_none")) == 1
    assert len((tmp_path / "data/pipeline/issues.jsonl").read_text(encoding="utf-8").splitlines()) == 1
    td["takes"].append(_take("image", 3, pf))                               # 候选变了 → 再记一次
    pr.gaze_fallback(_obj(oid, status="best_effort"), pr.ledger()[oid])
    assert len(_evs(pr, "gaze_fallback_none")) == 2


def test_d8_sweep_routes_to_gaze_fallback(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    oid = "first:ep01-S1"
    pr.led_update(oid, tries=3, final="best_effort")
    monkeypatch.setattr(PR, "review_adopt_auto", lambda root=ROOT: True)
    monkeypatch.setattr(PR, "review_adopt", lambda *a, **k: None)
    seen = []
    pr.gaze_fallback = lambda o, led: seen.append(o["id"]) or -1
    assert pr.adopt_best_effort_sweep(_reg(_obj(oid, status="best_effort")), every_s=0) == [oid] and seen == [oid]


# ================================================================ D9 sop_gate Q9 认 review_needed
def _sg():
    sp = importlib.util.spec_from_file_location("sop_gate_l204", ROOT / "tools/master/sop_gate.py")
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def test_d9_q9_pass_accepts_review_needed():
    SG = _sg()
    assert SG._q9_pass({"review_needed": True, "items": [{"id": "Q9", "status": "fail"}]})
    assert SG._q9_pass({"review_needed": True, "items": []})
    assert not SG._q9_pass({"items": [{"id": "Q9", "status": "fail"}]})
    assert not SG._q9_pass({"items": [{"id": "Q9", "status": "na", "evidence": {}}]})
    assert SG._q9_pass({"items": [{"id": "Q9", "status": "na", "evidence": {"model": "m"}}]})


def test_d9_shot_frames_reads_last_frame_fallback_from_takes(tmp_path):
    SG = _sg()
    run = "drama_l204"
    (tmp_path / "config/pipeline").mkdir(parents=True)
    (tmp_path / "config/pipeline/runs.json").write_text(json.dumps(
        {"primary": run, "legacy_unprefixed_run": "old_v1", "runs": {run: {"status": "producing"}}}), encoding="utf-8")
    (tmp_path / "data/img").mkdir(parents=True)
    (tmp_path / "data/img/a.png").write_bytes(b"x")
    d = tmp_path / f"data/renders/{run}/ep01/S1"
    d.mkdir(parents=True)
    doc = {"active": {"image": 2}, "takes": [{"stage": "image", "n": 2, "file": "img/a.png",
                                                "postflight": {"ok": True, "review_needed": True, "items": [{"id": "Q9", "status": "fail"}]}}],
           "last_frame_fallback": {"mode": "i2va", "first_n": 2}}
    (d / "takes.json").write_text(json.dumps(doc), encoding="utf-8")
    row = SG.shot_frames(tmp_path, run, 1)[1]
    assert row["checked"] and row["last"] and row["last_fallback"] == "i2va"       # review_needed 过 Q9 + 回退放行尾帧
    doc["last_frame_fallback"]["first_n"] = 1                                       # 绑定的首帧不是当前首帧 → 回退失效
    (d / "takes.json").write_text(json.dumps(doc), encoding="utf-8")
    row = SG.shot_frames(tmp_path, run, 1)[1]
    assert row["checked"] and not row["last"]


# ================================================================ D11 旧首帧视线缺陷补判重出
def test_d11_gaze_regen_sweep_demotes_old_gaze_first(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    oid = "first:ep01-S1"
    bad = {"ok": True, "blocking": [], "reasons": [], "items": [_it("Q1", "pass", value=0.8), _it("Q9", "na", defects=["lineup"], model="m")]}
    td = {"active": {"image": 4}, "takes": [_take("image", 4, bad)]}
    ann, cleared = [], []
    monkeypatch.setattr(P, "load_takes", lambda sid: td)
    monkeypatch.setattr(FE, "annotate", lambda sid, stage, n, **f: ann.append((n, f["postflight"])))
    monkeypatch.setattr(P, "clear_active", lambda sid, stage, reason, actor=None: cleared.append((stage, actor)))
    pr.led_update(oid, tries=2, final="passed")
    reg = _reg(_obj(oid, status="passed", take=4))
    assert pr.gaze_regen_sweep(reg, every_s=0) == [oid]
    assert cleared == [("image", "producer.gaze_regen_sweep")]
    n, pf2 = ann[0]
    assert n == 4 and pf2["ok"] is False and pf2["ok_before_gaze"] is True and "gaze" in pf2["blocking"] and pf2["gaze_rejudged"]
    led = pr.ledger()[oid]
    assert led["final"] is None and led["tries"] == 2 and led["gaze_regen"]["take"] == 4          # 计次：tries 不清
    assert _evs(pr, "gaze_regen")[0]["counted"] is True
    # 已补判 / D8 兜底采用（gaze_waived）/ 定稿锁的不动
    td["takes"][0]["postflight"] = {**bad, "gaze_rejudged": {"at": "x"}}
    assert pr.gaze_regen_sweep(reg, every_s=0) == []
    td["takes"][0]["postflight"] = {**bad, "gaze_waived": {"by": "D8"}}
    assert pr.gaze_regen_sweep(reg, every_s=0) == []
    td["takes"][0]["postflight"] = bad
    assert pr.gaze_regen_sweep(_reg(_obj(oid, status="passed", take=4, owner_locked=True)), every_s=0) == []
    assert len(cleared) == 1


def test_d11_wired_into_tick_before_adopt_sweep():
    body = SRC.split("    def tick(self, dispatch: bool = True)", 1)[1].split("    def hb_counts", 1)[0]
    assert body.index("self.gaze_regen_sweep(reg)") < body.index("self.adopt_best_effort_sweep(reg)")
    assert 'reg["stuck_objects"] = self.stuck_objects(reg)' in body


# ================================================================ 不变量：ready 却派不出 → stuck_object
def test_stuck_objects_logged_after_n_minutes(tmp_path, monkeypatch):
    pr = _pr(tmp_path)
    oid = "last:ep01-S1"
    pr.led_update(oid, tries=3)
    reg = _reg(_obj(oid, status="ready", attempts=3))
    t0 = time.time()
    monkeypatch.setattr(PR, "now", lambda: t0)
    assert pr.stuck_objects(reg) == []                                            # 刚发现：先计时
    monkeypatch.setattr(PR, "now", lambda: t0 + PR.STUCK_MIN * 60 + 1)
    out = pr.stuck_objects(reg)
    assert out and out[0]["obj"] == oid and "用尽" in out[0]["why"]
    assert _evs(pr, "stuck_object")[0]["obj"] == oid and len(_evs(pr, "stuck_object")) == 1
    monkeypatch.setattr(PR, "now", lambda: t0 + PR.STUCK_MIN * 60 + 60)
    pr.stuck_objects(reg)
    assert len(_evs(pr, "stuck_object")) == 1                                     # 30 分钟内不重复记
    # 作废待清零 / 退避 / 只重打分 = 暂时性，不算卡；对象恢复可派后计时清掉
    assert pr.undispatchable_why(_obj(oid, voided=True, attempts=3), {"tries": 3}, {}) is None
    assert pr.undispatchable_why(_obj(oid, waiting_for="基础设施退避到 10:00"), {"tries": 3}, {}) is None
    assert pr.undispatchable_why(_obj(oid, rescore_take=2), {"tries": 3}, {}) is None
    assert "硬上限" in pr.undispatchable_why(_obj(oid), {"hard_capped": {"t": PR.now()}}, {})
    assert "驳回计划" in pr.undispatchable_why(_obj(oid, redo=True), {"redo_tries": 2}, {oid: {"plan": [{}, {}]}})
    assert pr.undispatchable_why(_obj(oid, redo=True), {"redo_tries": 1}, {oid: {"plan": [{}, {}]}}) is None
    pr.led_update(oid, tries=0)
    assert pr.stuck_objects(_reg(_obj(oid, status="ready", attempts=0))) == [] and oid not in pr._stuck_since


def test_last_preflight_failure_counts_and_never_blocks_first_frame():
    """REVIEW-SV 11-06 CRITICAL：尾帧 preflight 不过按次计数、不标 assets blocked、满 3 次退回 I2VA"""
    import re as _re
    s = (Path(__file__).resolve().parents[1] / "tools/autopilot/producer.py").read_text(encoding="utf-8")
    i = s.index('elif k == "preflight" and oid.startswith("last:")')
    branch = s[i:s.index('elif k == "preflight":', i + 10)]
    assert "last_pf_fails" in branch and "MAX_TRIES" in branch
    assert "last_frame_fallback" in branch and "blocked_until=now() + 60" in branch
    assert "led_update(f\"assets:" not in branch         # 不连带挡首帧
    assert "尾帧生成契约" in s[s.index("def last_preflight("):s.index("def take_pf(")]
