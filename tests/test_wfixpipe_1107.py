"""W-FIX-PIPE（L-212，SCAN_20261107 #6 / #7 / #8 / #13）：全 fixture，不碰真实数据 / 服务器。

#6  过了导入闸门、提示词证据过期的集 → lifecycle_tick 自动起 probe-prompts（每集去抖）
#7  producer 视频对象假“在跑”：镜归另一台 → 显示归那台；本机没排没出超 30 分钟 → 退回 ready
#8  两台登记表按对象合并（走得最远的状态赢，驳回标记优先）；网页标签 / KPI 读合并后的
#13 资产作业定案失败 → 换种子重排 ≤K 次 → 差一点候选卡（只能本人挑）/ 需要修改描述
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/autopilot", "tools/pipeline", "services/api", "services/agent", "services/post"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

import resident_sync as RS  # noqa: E402
import producer as PR  # noqa: E402
import asset_worker as AW  # noqa: E402
from tools.brain import reg_merge as RM  # noqa: E402

STAGES = ["剧本", "导入闸门", "资产就绪", "提示词", "出图", "出图检测", "尾帧", "视频", "整集预览"]
RUN = "tv_fixpipe"


def _w(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False), encoding="utf-8")


def _eps(*pairs):
    return [{"episode": e, "stage": s, "stage_index": STAGES.index(s)} for e, s in pairs]


# ------------------------------------------------------------------ #6
STALE = {"ok": False, "why": "证据过期（11-07 01:00 之后导入稿或资产清单变了，重跑 probe-prompts）"}


def test_auto_probe_only_past_import_gate_and_debounced(tmp_path):
    _w(tmp_path / "config/pipeline/sop_gate.json", {"auto_probe_tick_min": 5})
    calls = []
    probe = lambda run, ep, root, missing, now: calls.append((ep, now)) or "started"  # noqa: E731
    eps = _eps((1, "导入闸门"), (2, "提示词"), (3, "出图"))
    check = lambda root, run, ep: STALE if ep == 2 else {"ok": True, "why": "16/16"}  # noqa: E731
    out = RS.auto_probe_tick(tmp_path, RUN, eps, 1000.0, False, probe_fn=probe, check_fn=check)
    assert calls == [(2, 1000.0)] and out == {"ep02": {"why": STALE["why"][:160], "action": "started"}}   # ep1 没过导入闸门不探；ep3 证据有效
    st = json.loads((tmp_path / "data/autopilot/auto_probe.json").read_text(encoding="utf-8"))
    assert st[f"{RUN}:ep02"]["t"] == 1000.0
    out = RS.auto_probe_tick(tmp_path, RUN, eps, 1000.0 + 120, False, probe_fn=probe, check_fn=check)
    assert out["ep02"]["action"] == "debounce" and len(calls) == 1                       # 5 分钟内不再触发
    out = RS.auto_probe_tick(tmp_path, RUN, eps, 1000.0 + 301, False, probe_fn=probe, check_fn=check)
    assert out["ep02"]["action"] == "started" and len(calls) == 2


def test_auto_probe_dry_and_running_do_not_stamp(tmp_path):
    eps = _eps((2, "资产就绪"))
    check = lambda root, run, ep: {"ok": False, "why": "还没有逐镜编译 + preflight 证据（跑 sop_gate.py probe-prompts）"}  # noqa: E731
    out = RS.auto_probe_tick(tmp_path, RUN, eps, 1e9, True, probe_fn=lambda *a: pytest.fail("dry 不许起"), check_fn=check)
    assert out["ep02"]["action"] == "would_probe"
    out = RS.auto_probe_tick(tmp_path, RUN, eps, 1e9 + 10, False, probe_fn=lambda *a: "running", check_fn=check)
    assert out["ep02"]["action"] == "running" and not (tmp_path / "data/autopilot/auto_probe.json").exists()   # 在跑不记去抖（下一拍再看）


def test_auto_probe_ignores_non_stale_prompt_failures(tmp_path):
    check = lambda root, run, ep: {"ok": False, "why": "15/16 镜过；镜3：preflight I12 缺资产"}  # noqa: E731
    out = RS.auto_probe_tick(tmp_path, RUN, _eps((2, "提示词")), 1.0, False, probe_fn=lambda *a: pytest.fail("不该探"), check_fn=check)
    assert out == {}


def test_lifecycle_tick_runs_auto_probe_even_when_no_target(tmp_path):
    """证据过期 → 阶段停在“提示词” → 没有 producer 目标：以前这里直接 return，没人重探（死锁）"""
    _w(tmp_path / "config/pipeline/runs.json", {"primary": RUN, "runs": {RUN: {"status": "producing"}}})
    _w(tmp_path / "config/pipeline/sop_gate.json", {"lifecycle": {"apply": True}})
    _w(tmp_path / "config/netfix/partition.json", {"images": {"gpu36": [2]}, "video": {"gpu36": [2]}})
    seen = []
    stage = lambda root, run: {"status": "producing", "legacy": False, "stages": STAGES, "episodes": _eps((2, "提示词"))}  # noqa: E731
    out = RS.lifecycle_tick(tmp_path, stage_fn=stage, now=1e9, probe_fn=lambda run, ep, root, missing, now: seen.append(ep) or "started")
    assert "没有任何一集到“出图”" in out["skip"]
    # 夹具根没有证据文件 → 真 check_prompts 判“还没有证据”= 要探
    assert seen == [2] and out["auto_probe"]["ep02"]["action"] == "started"


# ------------------------------------------------------------------ #7
def _world(vstate=None, night=None, jobs_host=None, claims=None):
    return SimpleNamespace(vstate=vstate or {"gpu33": {}, "gpu36": {}}, night=night or {}, vjobs_host=jobs_host or {},
                           vclaims=claims or {}, video_reconciled=[])


PASSED = {"status": "passed"}


def test_video_owned_by_other_host_is_not_running(monkeypatch):
    """gpu33 实况：ep01-S7 jobs.json host=gpu36 + shard_claims 领给 gpu36，gpu33 state 里 pending 无渲染"""
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    now = PR.now()
    w = _world(vstate={"gpu33": {"ep01-S7": {"status": "pending", "renders": []}}, "gpu36": {}},
               night={"eps": {"1": {"host": "gpu33", "dispatched": now - 60, "status": "rendering"}}},
               jobs_host={"ep01-S7": "gpu36"}, claims={"ep01-S7": {"host": "gpu36", "from": "gpu33", "at": now - 99999}})
    o = PR._video_obj(w, "ep01-S7", 1, {}, PASSED, PASSED, {}, {}, True)
    assert o["status"] == "pending" and o["owned_by"] == "gpu36" and "gpu36" in o["waiting_for"]
    assert w.video_reconciled == [{"obj": "video:ep01-S7", "kind": "other_host", "owner": "gpu36", "age_min": None}]


def test_video_fake_running_resets_to_ready_after_30_min(monkeypatch):
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    now = PR.now()
    vs = {"gpu33": {"ep01-S9": {"status": "pending", "renders": []}, "ep01-S2": {"status": "done", "renders": [{"state": "scored"}]}}}
    night = {"eps": {"1": {"host": "gpu33", "dispatched": now - 31 * 60, "status": "rendering"}}}
    w = _world(vstate=vs, night=night, jobs_host={"ep01-S9": "gpu33"})
    o = PR._video_obj(w, "ep01-S9", 1, {}, PASSED, PASSED, {}, {}, True)
    assert o["status"] == "ready" and o["reconciled"] == "fake_running" and "退回" in o["waiting_for"]
    assert w.video_reconciled[0]["kind"] == "stale"


def test_video_running_kept_when_fresh_or_ep_busy(monkeypatch):
    monkeypatch.setenv("OFFLINE_SELF", "gpu33")
    now = PR.now()
    fresh = _world(vstate={"gpu33": {"ep01-S9": {"status": "pending"}}}, jobs_host={"ep01-S9": "gpu33"},
                   night={"eps": {"1": {"host": "gpu33", "dispatched": now - 10 * 60}}})
    assert PR._video_obj(fresh, "ep01-S9", 1, {}, PASSED, PASSED, {}, {}, True)["status"] == "running"     # 刚派出：照旧在跑
    busy = _world(vstate={"gpu33": {"ep01-S9": {"status": "pending"}, "ep01-S3": {"status": "pending", "renders": [{"state": "submitted"}]}}},
                  jobs_host={"ep01-S9": "gpu33", "ep01-S3": "gpu33"},
                  night={"eps": {"1": {"host": "gpu33", "dispatched": now - 90 * 60}}})
    assert PR._video_obj(busy, "ep01-S9", 1, {}, PASSED, PASSED, {}, {}, True)["status"] == "running"      # 本机这集还有镜在出 = 在排队
    assert busy.video_reconciled == []


# ------------------------------------------------------------------ #8
def _reg(host_objs: dict, ep=1, hb=None):
    return {"run": RUN, "heartbeat": hb, "episodes": [{"ep": ep, "have": {"total": len(host_objs)}, "objects": {},
                                                       "shots": [{"shot": sid, "objects": objs} for sid, objs in host_objs.items()]}]}


def test_merge_most_advanced_wins_and_recounts():
    base = _reg({"ep01-S1": {"first": {"status": "passed"}, "video": {"status": "running"}},
                 "ep01-S2": {"first": {"status": "ready"}, "video": {"status": "pending"}}})
    g36 = _reg({"ep01-S1": {"first": {"status": "ready"}, "video": {"status": "passed"}},
                "ep01-S2": {"first": {"status": "passed"}, "video": {"status": "best_effort"}}})
    m = RM.merge_registries(base, {"gpu36": g36})
    s1, s2 = (S["objects"] for S in m["episodes"][0]["shots"])
    assert s1["first"]["status"] == "passed" and "merged_from" not in s1["first"]          # 本机更远：保留
    assert s1["video"] == {"status": "passed", "merged_from": "gpu36"}
    assert s2["first"]["status"] == "passed" and s2["video"]["status"] == "best_effort"
    assert m["episodes"][0]["have"]["passed"] == {"first": 2, "last": 0, "video": 1} and m["merged_hosts"] == ["gpu36"]
    assert base["episodes"][0]["shots"][0]["objects"]["video"]["status"] == "running"     # 不改入参


def test_merge_keeps_rejected_object_and_adds_missing_episode():
    base = _reg({"ep01-S1": {"first": {"status": "ready", "redo": True, "master_reject": "脸不对"}}})
    other = {"episodes": [{"ep": 1, "shots": [{"shot": "ep01-S1", "objects": {"first": {"status": "passed"}}}]},
                          {"ep": 2, "shots": [{"shot": "ep02-S1", "objects": {"first": {"status": "passed"}}}]}]}
    m = RM.merge_registries(base, {"gpu33": other})
    assert m["episodes"][0]["shots"][0]["objects"]["first"]["status"] == "ready"           # 驳回优先，不被别台旧的 passed 盖
    assert [E["ep"] for E in m["episodes"]] == [1, 2] and m["episodes"][1]["merged_from"] == "gpu33"


def test_shot_status_reads_merged_host_copies(tmp_path, monkeypatch):
    import time as _t
    from ns_api import shot_status as SS
    monkeypatch.setattr(SS, "ROOT", tmp_path)
    rel = Path("data/producer/runs") / RUN / "registry.json"
    _w(tmp_path / rel, _reg({"ep01-S1": {"video": {"status": "running"}}}))
    _w(tmp_path / "data/_offline_pull/gpu36" / rel, _reg({"ep01-S1": {"video": {"status": "passed"}}}, hb=_t.time()))
    _w(tmp_path / "data/_offline_pull/gpu33" / rel, _reg({"ep01-S1": {"video": {"status": "passed"}}}, hb=_t.time() - 7 * 3600))
    m = SS.merged_registry(tmp_path / rel)
    assert m["episodes"][0]["shots"][0]["objects"]["video"] == {"status": "passed", "merged_from": "gpu36"}
    assert m["merged_hosts"] == ["gpu36"]                                                  # 心跳 7 小时前的那台不参与
    monkeypatch.setattr(SS, "registry_path", lambda: tmp_path / rel)
    monkeypatch.setitem(SS._reg, "mt", None)
    assert SS._registry()["ep01-S1"]["video"]["status"] == "passed"


# ------------------------------------------------------------------ #13
@pytest.fixture()
def aj(monkeypatch, tmp_path):
    q = SimpleNamespace(cards=[], reports=[])
    monkeypatch.setattr(AW.AJ, "guard_run", lambda root, run: None)
    monkeypatch.setattr(AW, "_owner_queue", lambda: SimpleNamespace(enqueue_asset_revise=lambda root, req: q.cards.append(req) or req))
    monkeypatch.setattr(AW.AJ, "_report", lambda root, run, ep, step, what, blocking, hint="": q.reports.append(what))
    return q


def _job(**kw):
    j = {"id": "item-x-A-outfit1", "run": RUN, "episode": 1, "kind": "item", "target": "ch_x:A_outfit1", "state": "failed",
         "attempts": 2, "pick_id": "pick:item:ch_x:A_outfit1", "spec": {"name": "江予白", "label": "驼色皮夹克、黑色圆领T恤"},
         "candidates": [{"seed": 1100, "passed": False, "label": {"q9": "fail"}, "file": "ab/x.png"}], "log": []}
    j.update(kw)
    return j


WHY = "没有候选过检（4 张不过）：seed 1200：q9=fail；Q9 报的缺陷：设定候选口径：鞋 / 服装 / 饰品上出现品牌字母或 logo 造型（brand_logo）；只记录"


def test_final_fail_auto_requeues_then_need_revise_card_without_failed_images(tmp_path, aj):
    cfg = {"max_attempts": 2, "auto_requeue_max": 2}
    j, rec = _job(state="running"), {"failed": []}
    for n in (1, 2):
        AW._fail(tmp_path, j, cfg, WHY, rec)
        assert j["state"] == "pending" and j["auto_requeues"] == n and not j["final"]
        j["attempts"] += 1
    AW._fail(tmp_path, j, cfg, WHY, rec)
    assert j["state"] == "failed" and j["escalated"]["kind"] == "need_revise" and not aj.reports
    card = aj.cards[-1]
    assert card["id"] == "rv:item-x-A-outfit1" and card["job"] == j["id"] and card["name"] == "江予白"
    assert card["reason"] == "鞋 / 服装 / 饰品上出现品牌字母或 logo 造型" and "驼色皮夹克" in card["spec_text"]
    assert not any(k in json.dumps(card, ensure_ascii=False) for k in ("candidates", "contract_ok", ".png"))   # 没过的图一张都不给看
    assert AW.after_final_fail(tmp_path, j, cfg, WHY, rec) == "skip"     # 只升级一次


def test_non_content_failure_goes_to_master_not_owner(tmp_path, aj):
    j = _job(auto_requeues=2, final=True)
    assert AW.after_final_fail(tmp_path, j, {"auto_requeue_max": 2}, "子进程退出但作业没收尾", {"failed": []}) == "reported"
    assert "连续失败" in aj.reports[0] and not aj.cards


def test_preflight_failure_skips_requeue_and_suspect_untouched(tmp_path, aj):
    assert AW.after_final_fail(tmp_path, _job(), {}, "seed 1100: RuntimeError: preflight 不过：I12", {"failed": []}) == "need_revise"
    assert AW.after_final_fail(tmp_path, _job(lane_suspect="gpu33:0"), {}, WHY, {"failed": []}) == "skip"
    assert AW.after_final_fail(tmp_path, _job(kind="meta"), {}, WHY, {"failed": []}) == "skip"


def test_fresh_seeds_and_owner_notes_in_prompt():
    assert AW.fresh_seeds({"candidates": [{"seed": 1300}, {"seed": 1302}]}, 1300, 3) == [1301, 1303, 1304]
    assert AW.with_owner_notes("单品物件图：驼色皮夹克", {"owner_notes": ["不要任何字母", " "]}) == "单品物件图：驼色皮夹克；不要任何字母"
    assert AW.with_owner_notes("x", {}) == "x"


def test_owner_queue_card_shows_and_revise_requeues(tmp_path, monkeypatch):
    from ns_api import owner_queue as OQ
    seen = []
    OQ.enqueue_asset_revise(tmp_path, {"id": "rv:item-x", "run": RUN, "job": "item-x", "asset_kind": "item", "name": "江予白",
                                       "what": "单品“驼色皮夹克”", "spec_text": "驼色皮夹克、黑色圆领T恤", "reason": "鞋 / 服装上出现品牌字母或 logo 造型"})
    it = next(x for x in OQ.build(tmp_path)["items"] if x["id"] == "rv:item-x")
    assert it["kind"] == "asset_revise" and it["block_level"] == "red" and it["media"] == [] and it["options"] == [{"key": "revise", "label": "修改"}]
    assert it["say_what"] == "需要你改一句描述：江予白的单品“驼色皮夹克”" and "一直卡在：鞋 / 服装上出现品牌字母或 logo 造型" in it["why"]
    assert [a["label"] for a in it["actions"]] == ["修改"] and it["actions"][0]["needs_reason"]                  # 只有“修改”（L-123）
    with pytest.raises(OQ.HTTPException):
        OQ.decide(tmp_path, "rv:item-x", "revise", "  ", "owner", revise_fn=lambda *a: pytest.fail("空话不改"))
    r = OQ.decide(tmp_path, "rv:item-x", "revise", "衣服上不要任何字母和标志", "owner", revise_fn=lambda *a: seen.append(a) or {"state": "pending"})
    assert seen == [(tmp_path, RUN, "item-x", "衣服上不要任何字母和标志", "owner")] and r["decision"]["applied"] == {"state": "pending"}
    assert all(x["id"] != "rv:item-x" for x in OQ.build(tmp_path)["items"])                                  # 改了就收起
    OQ.enqueue_asset_revise(tmp_path, {"id": "rv:item-x", "run": RUN, "job": "item-x", "name": "江予白", "what": "x", "reason": "还是有字"})
    assert any(x["id"] == "rv:item-x" for x in OQ.build(tmp_path)["items"])                                    # 重排后仍不过 → 重新出现


def test_asset_jobs_owner_revise_appends_note_and_requeues(tmp_path, monkeypatch):
    AJ = AW.AJ
    monkeypatch.setattr(AJ, "guard_run", lambda root, run: None)
    j = _job(final=True, auto_requeues=2, escalated={"kind": "need_revise"}, owner_notes=["先前一句"])
    AJ.save_job(tmp_path, j)
    out = AJ.owner_revise(tmp_path, RUN, j["id"], "衣服上不要任何字母", "owner")
    j2 = AJ.load_job(AJ.job_path(tmp_path, RUN, j["id"]))
    assert out["owner_notes"] == ["先前一句", "衣服上不要任何字母"] and j2["state"] == "pending" and j2["attempts"] == 0
    assert not j2["final"] and j2["escalated"] is None and j2["auto_requeues"] == 0
    with pytest.raises(AJ.RegisterError):
        AJ.owner_revise(tmp_path, RUN, j["id"], " ", "owner")


# ------------------------------------------------------------------ L-212 #10：owner_pick / owner_queue 页面时间 JST；自查 pick 年龄不靠读的人的时区
def test_pick_state_view_and_queue_at_are_jst(tmp_path):
    import time as _t
    from ns_api import clock as CK
    from ns_api import owner_pick as OP
    from ns_api import owner_queue as OQ
    local = _t.strftime("%Y-%m-%dT%H:%M:%S")                               # 笔记本 API 写的裸串（本机时区）
    v = OP.state_view({"state": "done", "updated": local, "choice": "s1", "delegate": {"at": local, "by": "x"}})
    assert v["updated"] == CK.local_naive_to_jst(local) == v["delegate"]["at"] and v["choice"] == "s1"
    assert OP.state_view(None) is None
    OQ.enqueue_asset_revise(tmp_path, {"id": "rv:t", "run": RUN, "job": "t", "name": "甲", "what": "乙", "at": local})
    q = OQ.build(tmp_path)
    jst_now = CK.jst_now_str("%Y-%m-%dT%H:%M")
    assert q["at"][:16] == jst_now and next(x for x in q["items"] if x["id"] == "rv:t")["at"] == CK.local_naive_to_jst(local)


def test_invariants_pick_age_independent_of_reader_tz(tmp_path):
    import os
    import time as _t
    from tools.brain import invariants as INV
    now = _t.time()
    est = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(now - 5 * 3600 - 45 * 60))     # 美东写的、45 分钟前
    fresh = _t.strftime("%Y-%m-%dT%H:%M:%S", _t.gmtime(now - 5 * 3600 - 60))         # 同文件刚写的另一条（= 文件 mtime）
    p = tmp_path / "data/owner_queue/pick_state.json"
    _w(p, {"pick:a": {"state": "accepted", "updated": est}, "pick:b": {"state": "done", "updated": fresh}})
    os.utime(p, (now - 60, now - 60))
    assert INV.writer_offset_s(json.loads(p.read_text(encoding="utf-8")), now - 60) == -5 * 3600
    v = INV.check_picks(tmp_path, now)
    stuck = [x for x in v if "pick:a" in json.dumps(x, ensure_ascii=False)]
    assert stuck and "45 分钟" in json.dumps(stuck[0], ensure_ascii=False)
    assert INV.pick_ts("2026-11-07T01:00:00+09:00", -5 * 3600) == INV._local_ts("2026-11-07T01:00:00+09:00")
