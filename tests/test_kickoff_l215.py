"""L-215 / L-216（W-KICKOFF 11-07，PLAN_5H 块 J）：开项目确认单 + 开工后零等待 + 每镜“重做”。"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("tools/autopilot", "tools/pipeline", "services/api", "services/agent", "tools/series10_video"):
    if str(ROOT / p) not in sys.path:
        sys.path.insert(0, str(ROOT / p))

import kickoff as KO  # noqa: E402
import asset_worker as AW  # noqa: E402

RUN = "tv_kick"


def _cfg(root: Path, policy: dict | None = None) -> None:
    p = root / "config" / "pipeline" / "kickoff.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"defaults": dict(KO.DEFAULTS), "runs": {RUN: {"policy": policy or {}}}}, ensure_ascii=False), encoding="utf-8")


# ------------------------------------------------------------------ 规则
def test_policy_defaults_zero_wait_and_record_validates(tmp_path):
    assert not KO.configured(tmp_path) and not KO.is_on("picks", RUN, tmp_path)          # 没有确认单 = 旧行为
    _cfg(tmp_path)
    assert KO.policy(RUN, tmp_path) == KO.DEFAULTS and KO.is_on("look_confirm", RUN, tmp_path)
    with pytest.raises(ValueError):
        KO.record(RUN, {"adult_authorization": "maybe"}, "项目方", root=tmp_path)
    out = KO.record(RUN, {"look_confirm": "ask", "characters": "确认，祁念头发再蓝一点"}, "项目方", "原话", root=tmp_path)
    assert out["policy"]["look_confirm"] == "ask" and not KO.is_on("look_confirm", RUN, tmp_path)
    rr = KO.load(tmp_path)["runs"][RUN]
    assert rr["answers"]["characters"].startswith("确认") and rr["history"][-1]["quote"] == "原话" and rr["confirmed_at"]


def test_repo_config_is_zero_wait_for_series10_v2():
    pol = KO.policy("series10_v2", ROOT)
    assert pol == KO.DEFAULTS and KO.configured(ROOT)


# ------------------------------------------------------------------ 成人镜常设授权（只按 id）
class FakeAT:
    KINDS = ("first", "last", "video")

    def __init__(self, shots, trig, reg=None, tmp=None):
        """shots = 导入稿 shot.adult 镜；reg = 登记表里因成人资产被拦的普通镜（adult_trigger.adult_shots 也算进去）"""
        self.shots, self.reg, self.trig, self.calls, self.pushed = shots, reg or {}, set(trig), [], 0
        import tempfile
        self.sp = Path(tmp or tempfile.mkdtemp()) / "script_v2.json"
        eps: dict = {}
        for sid, m in {**self.reg, **shots}.items():
            eps.setdefault(m["ep"], []).append({"index": m["index"], "adult": sid in shots})
        self.sp.write_text(json.dumps({"episodes": [{"number": e, "shots": v} for e, v in eps.items()]}), encoding="utf-8")

    def script_path(self, run, root=None):
        return self.sp

    def adult_shots(self, run, root=None):
        return {**self.reg, **self.shots}

    def triggered(self, run, root=None):
        return set(self.trig)

    def apply(self, run, objs, by, note, root=None, via="web"):
        self.calls.append((run, list(objs), by, via))
        added = [o for o in objs if o not in self.trig]
        self.trig |= set(objs)
        return {"added": added, "total": len(self.trig)}

    def push_now(self, root=None):
        self.pushed += 1


def test_sync_adult_adds_new_adult_shots_as_owner_standing_authorization(tmp_path):
    _cfg(tmp_path)
    at = FakeAT({"ep03-S2": {"ep": 3, "index": 2}, "ep04-S1": {"ep": 4, "index": 1}}, {"first:ep03-S2", "last:ep03-S2", "video:ep03-S2"})
    r = KO.sync_adult(RUN, tmp_path, AT=at)
    assert r["added"] == ["first:ep04-S1", "last:ep04-S1", "video:ep04-S1"]
    assert at.calls[0][2] == "项目方（开项目常设授权 L-216）" and at.calls[0][3] == "kickoff" and at.pushed == 1
    assert KO.sync_adult(RUN, tmp_path, AT=at)["added"] == [] and len(at.calls) == 1                   # 幂等：都在清单里就不写
    assert KO.sync_adult(RUN, tmp_path, dry=True, AT=FakeAT({"ep05-S1": {"ep": 5, "index": 1}}, set()))["would_add"][0] == "first:ep05-S1"


def test_standing_authorization_only_script_adult_not_registry_adult_asset(tmp_path):
    _cfg(tmp_path)
    at = FakeAT({"ep04-S1": {"ep": 4, "index": 1}}, set(), reg={"ep04-S2": {"ep": 4, "index": 2}}, tmp=tmp_path)
    r = KO.sync_adult(RUN, tmp_path, AT=at)
    assert r["added"] == ["first:ep04-S1", "last:ep04-S1", "video:ep04-S1"]
    assert not any("ep04-S2" in o for o in at.trig)                       # 普通镜碰到成人资产：不自动触发（要项目方本人）


def test_kickoff_does_not_grow_sys_path(tmp_path):
    _cfg(tmp_path)
    KO.is_on("picks", RUN, tmp_path)
    n = len(sys.path)
    for _ in range(5):
        KO._runs()
        KO.live_runs(ROOT)
    assert len(sys.path) == n


def test_sync_adult_respects_none_and_missing_config(tmp_path):
    at = FakeAT({"ep04-S1": {"ep": 4, "index": 1}}, set())
    assert KO.sync_adult(RUN, tmp_path, AT=at)["added"] == [] and not at.calls                          # 没有确认单
    _cfg(tmp_path, {"adult_authorization": "none"})
    assert "skipped" in KO.sync_adult(RUN, tmp_path, AT=at) and not at.calls


def test_checklist_covers_all_kickoff_topics_and_only_ids_for_adult():
    at = FakeAT({"ep03-S2": {"ep": 3, "index": 2}}, set())
    md = KO.checklist("series10_v2", ROOT, AT=at)
    for h in ("角色与身份脸", "造型", "场景", "画风", "声音与音乐", "成人镜授权", "代选规则", "出不来时怎么兜底", "kickoff.py record"):
        assert h in md
    assert "ep03 1 镜" in md and "祁念" in md


# ------------------------------------------------------------------ 资产失败兜底（不投卡）
@pytest.fixture()
def aj(monkeypatch, tmp_path):
    q = SimpleNamespace(cards=[], picks=[], jobs=[])
    _cfg(tmp_path)
    monkeypatch.setattr(AW, "kickoff_on", lambda key, run, root: KO.is_on(key, RUN, root))
    monkeypatch.setattr(AW.AJ, "guard_run", lambda root, run: None)
    monkeypatch.setattr(AW.AJ, "save_job", lambda root, j: None)
    monkeypatch.setattr(AW.AJ, "list_jobs", lambda root, run: q.jobs)
    monkeypatch.setattr(AW, "_owner_queue", lambda: SimpleNamespace(enqueue_asset_revise=lambda root, req: q.cards.append(req) or req))
    monkeypatch.setattr(AW.AJ, "_report", lambda *a, **k: pytest.fail("不该登记卡点"))
    return q


WHY = "没有候选过检（4 张不过）：seed 1200：q9=fail；Q9 报的缺陷：设定候选口径：鞋上出现品牌字母或 logo 造型（brand_logo）；图里读到了字：NIKE"


def _job(**kw):
    j = {"id": "item-x-B-shoe", "run": RUN, "episode": 1, "kind": "item", "state": "failed", "final": True, "attempts": 2, "auto_requeues": 2,
         "pick_id": "pick:item:ch_x:B_shoe", "spec": {"cid": "ch_x", "name": "江予白", "look": "B", "slot": "shoes", "label": "侧面带金色logo的白色球鞋"},
         "log": []}
    j.update(kw)
    return j


def test_ladder_simplify_then_reseed_then_best_effort_notice(tmp_path, aj):
    j, rec, cfg = _job(), {"failed": []}, {"auto_requeue_max": 2}
    assert AW.after_final_fail(tmp_path, j, cfg, WHY, rec) == "fallback_simplify"
    assert j["state"] == "pending" and j["drop_terms"] == ["logo"] and not j.get("escalated")
    j.update(state="failed", final=True)
    assert AW.after_final_fail(tmp_path, j, cfg, WHY, rec) == "fallback_reseed" and j["seed_offset"] == AW.FAR_SEED_OFFSET
    j.update(state="failed", final=True)
    assert AW.after_final_fail(tmp_path, j, cfg, WHY, rec) == "best_effort"                       # 没有别的造型可借
    assert j["escalated"]["kind"] == "best_effort" and j["fallback_steps"] == ["simplify", "reseed", "borrow"]
    card = aj.cards[-1]
    assert card["notice"] is True and "尽力版" in card["source"] and ".png" not in json.dumps(card, ensure_ascii=False)
    assert AW.after_final_fail(tmp_path, j, cfg, WHY, rec) == "skip"


def test_ladder_borrows_closest_passing_variant_of_other_look(tmp_path, aj, monkeypatch):
    f = tmp_path / "assets_v2" / "a.png"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    aj.jobs += [{"id": "item-x-A-shoe", "kind": "item", "state": "done", "spec": {"cid": "ch_x", "look": "A", "slot": "shoes", "label": "白色球鞋"},
                 "result": {"file": "assets_v2/a.png"}},
                {"id": "item-x-A-bag", "kind": "item", "state": "done", "spec": {"cid": "ch_x", "look": "A", "slot": "bag", "label": "白色球鞋"},
                 "result": {"file": "assets_v2/a.png"}}]
    monkeypatch.setattr(AW.AJ, "auto_pick", lambda root, j, cands, who, what: aj.picks.append(cands) or {"picked": cands[0]["key"]})
    monkeypatch.setattr(AW.AJ, "load_job", lambda p: dict(_job(fallback_steps=["simplify", "reseed"])))
    monkeypatch.setattr(AW.AJ, "job_path", lambda root, run, jid: tmp_path / f"{jid}.json")
    j = _job(fallback_steps=["simplify", "reseed"])
    assert AW.after_final_fail(tmp_path, j, {"auto_requeue_max": 2}, WHY, {"failed": []}) == "best_effort_borrow"
    assert aj.picks[0][0]["key"] == "borrow-item-x-A-shoe" and aj.picks[0][0]["contract_ok"] and not aj.cards


def test_drop_clauses_keeps_negations():
    p = "单品物件图：白色球鞋，侧面带金色logo，纯白背景，没有任何标志、字母和文字"
    assert AW.drop_clauses(p, ["logo", "标志"]) == "单品物件图：白色球鞋，纯白背景，没有任何标志、字母和文字"
    assert AW.drop_terms_for({"spec": {"img": "没有任何标志、字母和文字", "label": "黑色皮包"}}, "x") == []


def test_owner_queue_asset_revise_becomes_after_notice(tmp_path):
    from ns_api import owner_queue as OQ
    _cfg(tmp_path)
    OQ.enqueue_asset_revise(tmp_path, {"id": "rv:item-x", "run": RUN, "job": "item-x", "asset_kind": "item", "name": "江予白",
                                       "what": "单品“白色球鞋”", "reason": "鞋上出现 logo"})
    q = OQ.build(tmp_path)
    assert all(x["id"] != "rv:item-x" for x in q["items"]) and q["count"] == 0                 # 不进待办、不挡
    it = next(x for x in q["delegated"] if x["id"] == "rv:item-x")
    assert it["block_level"] == "grey" and it["say_what"].startswith("事后可改") and [a["label"] for a in it["actions"]] == ["修改"]
    r = OQ.decide(tmp_path, "rv:item-x", "revise", "不要任何字母", "owner", revise_fn=lambda *a: {"state": "pending"})
    assert r["decision"]["applied"] == {"state": "pending"}                                          # 事后仍可改


# ------------------------------------------------------------------ 代选一直开 / 造型自动确认
def test_delegate_always_ignores_owner_decision_expiry_but_honours_revoke(tmp_path, monkeypatch):
    from ns_api import owner_delegate as OD
    monkeypatch.setattr(OD, "_kickoff", lambda: SimpleNamespace(is_on=lambda key, run, root: KO.is_on(key, RUN, root)))
    p = tmp_path / "config" / "pipeline" / "owner_delegate.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"enabled": False, "expiry": {"expired_kind": "owner_decision"}}), encoding="utf-8")
    assert OD.active(tmp_path)[0] is False                                                            # 没确认单 = 旧规则
    _cfg(tmp_path)
    assert OD.active(tmp_path) == (True, "")
    p.write_text(json.dumps({"enabled": False, "expiry": {"expired_kind": "revoked", "expired_reason": "项目方撤销"}}), encoding="utf-8")
    assert OD.active(tmp_path)[0] is False                                                            # 他明确撤销仍算数


def test_look_confirm_auto_confirms_without_card(tmp_path, monkeypatch):
    from ns_api import look_confirm as LC
    _cfg(tmp_path)
    sc = SimpleNamespace(episodes=[SimpleNamespace(number=3)])
    st = {"people": [{"cid": "lead_f"}], "ready": True, "confirmed": False, "pick_id": "pick:look:x:ep03:abc", "episode": 3}
    done = []
    monkeypatch.setattr(LC, "current_run", lambda root: RUN)
    monkeypatch.setattr(LC, "_script", lambda root, run: sc)
    monkeypatch.setattr(LC, "episode_state", lambda root, run, ep: st)
    monkeypatch.setattr(LC, "_open_look_picks", lambda root: [])
    monkeypatch.setattr(LC, "look_auto", lambda root, run: KO.is_on("look_confirm", RUN, root))
    monkeypatch.setattr(LC, "confirm", lambda root, run, ep, by, quote="", via="": done.append((ep, by, via)))
    assert LC.sync_picks(tmp_path) == [] and done == [(3, LC.AUTO_BY, "kickoff")]


# ------------------------------------------------------------------ 重做按钮
def test_owner_redo_frames_go_through_producer_reject_and_video_through_master_rejects(tmp_path, monkeypatch):
    from ns_api import owner_redo as RD
    calls = []
    monkeypatch.setattr(RD, "_at", lambda: SimpleNamespace(adult_shots=lambda run, root=None: {"ep03-S2": {}},
                                                           producer_dir=lambda run, root=None: tmp_path / "pd", triggered=lambda run, root=None: set()))
    r = RD.redo(RUN, "ep02-S5", "first", tmp_path, reject_fn=lambda run, oid, why, root: calls.append((run, oid, why)) or {"ok": True})
    assert calls == [(RUN, "first:ep02-S5", "项目方点了“重做首帧”")] and r["ok"] and r["adult"] is False and "重做" in r["say"]
    r = RD.redo(RUN, "ep03-S2", "video", tmp_path)
    rj = json.loads((tmp_path / "pd" / "master_rejects.json").read_text(encoding="utf-8"))
    e = rj["video:ep03-S2"]
    assert r["adult"] is True and e["by"] == "项目方（重做按钮）" and e["owner_redo"] and e["at"]
    for bad in (("ep2-S5", "first"), ("ep02-S5", "accept")):
        with pytest.raises(ValueError):
            RD.redo(RUN, *bad, tmp_path, reject_fn=lambda *a: pytest.fail("不该派"))


def test_owner_redo_api_owner_only(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from ns_api import auth, owner_redo as RD
    app = FastAPI()
    app.include_router(RD.router)
    monkeypatch.setattr(auth, "user_of", lambda req: {"name": "agent", "role": "viewer"})
    assert TestClient(app).post("/api/owner/redo", json={"shot": "ep02-S5", "kind": "first"}).status_code == 403


def test_vidgen_reads_owner_video_redo(tmp_path, monkeypatch):
    import vidgen as VG
    pd = tmp_path / "pd"
    pd.mkdir()
    (pd / "master_rejects.json").write_text(json.dumps({"video:ep02-S5": {"owner_redo": True, "at": "2026-11-07T05:00:00", "by": "项目方（重做按钮）"},
                                                        "first:ep02-S5": {"by": "x"}}), encoding="utf-8")
    monkeypatch.setattr(VG.RC, "_runs_mod", lambda: SimpleNamespace(producer_dir=lambda run: pd))
    q = VG.owner_redo_requests("ep02-S5")
    assert q[0]["owner_redo"] and q[0]["timeline"] == "owner-redo" and VG.owner_redo_requests("ep02-S6") == []


def test_sheet_never_borrows_goes_best_effort(tmp_path, aj, monkeypatch):
    aj.jobs.append({"id": "sheet-x-A", "kind": "sheet", "state": "done", "spec": {"cid": "ch_x", "look": "A"}, "result": {"file": "assets_v2/a.png"}})
    monkeypatch.setattr(AW.AJ, "auto_pick", lambda *a, **k: pytest.fail("设定图不借"))
    j = _job(id="sheet-x-B", kind="sheet", spec={"cid": "ch_x", "name": "江予白", "look": "B", "label": "整套"}, fallback_steps=["simplify", "reseed"])
    assert AW.after_final_fail(tmp_path, j, {"auto_requeue_max": 2}, WHY, {"failed": []}) == "best_effort"
    assert j["fallback_steps"] == ["simplify", "reseed"] and aj.cards[-1]["notice"]


def test_best_effort_marker_api_plain_words():
    from ns_api import best_effort_assets as BE
    jobs = [{"id": "item-x", "kind": "item", "target": "ch_x:B_shoe", "who": "江予白（ch_x）", "spec": {"label": "白色球鞋"},
             "escalated": {"kind": "best_effort"}},
            {"id": "item-y", "kind": "item", "escalated": {"kind": "need_revise"}}]
    out = BE.items("r", jobs=jobs)
    assert len(out) == 1 and out[0]["mark"] == "尽力版" and out[0]["who"] == "江予白" and "ch_x" not in out[0]["say"]


def test_revoke_works_under_delegate_always_and_status_reports_active(tmp_path, monkeypatch):
    from ns_api import owner_delegate as OD
    monkeypatch.setattr(OD, "_kickoff", lambda: SimpleNamespace(is_on=lambda key, run, root: KO.is_on(key, RUN, root)))
    monkeypatch.setattr(OD, "render_page", lambda root: None)
    _cfg(tmp_path)
    p = tmp_path / "config" / "pipeline" / "owner_delegate.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"enabled": False, "expiry": {"expired_kind": "owner_decision"}}), encoding="utf-8")
    st = OD.status(tmp_path)
    assert st["enabled"] is True and st["always"] is True
    OD.revoke(tmp_path, by="项目方 fred")
    assert OD.active(tmp_path)[0] is False and OD.status(tmp_path)["enabled"] is False


def test_owner_video_redo_does_not_use_lip_budget_and_reads_cached(tmp_path, monkeypatch):
    import vidgen as VG
    pd = tmp_path / "pd"
    pd.mkdir()
    f = pd / "master_rejects.json"
    f.write_text(json.dumps({"video:ep02-S5": {"owner_redo": True, "at": "2026-11-07T05:00:00", "by": "项目方（重做按钮）"}}), encoding="utf-8")
    monkeypatch.setattr(VG.RC, "_runs_mod", lambda: SimpleNamespace(producer_dir=lambda run: pd))
    monkeypatch.setattr(VG, "LIP_REDO", tmp_path / "none.json")
    monkeypatch.setattr(VG, "log", lambda *a, **k: None)
    reads = []
    real = VG.jload
    monkeypatch.setattr(VG, "jload", lambda p, d=None: reads.append(str(p)) or real(p, d))
    VG._OWNER_RJ.update(key=None, data={})
    for _ in range(3):
        VG.owner_redo_requests("ep02-S5")
    assert sum("master_rejects" in x for x in reads) == 1                    # 文件没变只读一次
    runner = SimpleNamespace(lock=__import__("threading").Lock(), host="h", event=lambda *a, **k: None)
    r = {"renders": [{"variant": "a", "state": "done"}], "status": "done", "lip_redo_n": 9}
    VG.Runner.check_lip_redo(runner, "ep02-S5", r)
    assert r["status"] == "pending" and r["renders"] == [] and r["lip_redo_n"] == 9      # 到了上限也重出，不占次数


def test_redo_say_for_untriggered_adult(tmp_path, monkeypatch):
    from ns_api import owner_redo as RD
    monkeypatch.setattr(RD, "_at", lambda: SimpleNamespace(adult_shots=lambda run, root=None: {"ep03-S2": {}},
                                                           triggered=lambda run, root=None: set()))
    r = RD.redo(RUN, "ep03-S2", "first", tmp_path, reject_fn=lambda *a: {"ok": True})
    assert r["waiting_trigger"] and "触发清单" in r["say"] and "自动换上" not in r["say"]
