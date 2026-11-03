"""DELEGATE-O（L-136 代选模式）：全部用临时目录夹具，不碰真实队列 / 配置 / 资产清单。

覆盖：代选走 owner_pick 正规 handler（by=总调度代选、via=delegate:L-136）· 到期 / 撤销后不再代选 · 项目方点修改 / 改选能覆盖代选 ·
成人相关条目永不代选 · 写作闸门分数门槛（≥30 且无 ≤2 才放行；不满足退回补丁环 / owner_direction 下不放行只登记卡点）· 审计记录与汇总页。
"""
from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/post", "services/agent", "services/api"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import auth  # noqa: E402
from ns_api import owner_delegate as OD  # noqa: E402
from ns_api import owner_pick as OP  # noqa: E402
from ns_api import owner_queue as OQ  # noqa: E402

FACE = "pick:face:ch_a"
SCENE = "pick:scene:sk_b"


def _w(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(d if isinstance(d, str) else json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")


def _cfg(root: Path, **kw) -> None:
    c = json.loads((ROOT / OD.CFG_REL).read_text(encoding="utf-8"))
    c.update(enabled=True, enabled_at="2026-11-03T02:30:00", **kw)
    _w(root / OD.CFG_REL, c)


def _face_cand(root: Path, key: str, vlm_ok: list[bool], age="pass", sims=None) -> dict:
    f = f"data/review_pages/v2_assets/r/face-ch_a/{key}.png"
    _w(root / f, "png")
    rec = {"label": {"identity": "na", "count": "pass", "q9": "pass", "prompt_vlm": "pass", "ocr": "pass", "age": age},
           "postflight": {"items": [{"id": "Q1", "status": "pass", "evidence": {"sims": sims or {}, "faces": 1}}, {"id": "Q9", "status": "pass", "evidence": {}}]},
           "vlm": {"items": [{"n": i, "ok": ok} for i, ok in enumerate(vlm_ok, 1)], "age": {"status": age}}}
    _w(root / f.replace(".png", ".json"), rec)
    return {"key": key, "label": f"候选 {key}", "contract_ok": True, "file": f, "thumb": f}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path
    _cfg(root)
    _w(root / "config/pipeline/runs.json", {"primary": "r", "legacy_unprefixed_run": "v1", "runs": {"r": {"status": "preparing", "assets_manifest": "assets_v2/manifest.json"}, "v1": {"status": "archived"}}})
    reqs = [
        {"id": FACE, "kind": "pick", "title": "挑 A 的身份脸", "detail": "d", "recommend": "s1", "run": "r",
         "candidates": [_face_cand(root, "s1", [True, False, True]), _face_cand(root, "s2", [True, True, True]),
                        _face_cand(root, "s3", [True, True, True, True], age="fail")]},
        {"id": SCENE, "kind": "pick", "title": "挑场景 B 的底图", "detail": "d", "run": "r",
         "candidates": [{"key": "a", "label": "a", "contract_ok": True, "checks": {"count": "pass", "q9": "pass", "prompt_vlm": "pass", "age": "na"}},
                        {"key": "b", "label": "b", "contract_ok": True, "checks": {"count": "fail", "q9": "pass", "prompt_vlm": "pass"}}]},
    ]
    _w(root / "data/owner_queue/requests.json", reqs)
    calls = []

    def fake(kind):
        def apply(r, req, choice, by, verify=None):
            calls.append({"kind": kind, "id": req["id"], "choice": choice, "by": by})
            return {"kind": kind, "picked": choice}
        return apply
    for k in ("face", "scene", "voice", "look", "sheet", "item", "golden"):
        monkeypatch.setitem(OP.HANDLERS, k, fake(k))
        OP.HANDLERS[k].wired = True
    monkeypatch.setattr(OP, "READY_HOOK", None)
    monkeypatch.setattr(OP, "REPO", root)
    monkeypatch.setattr(OD, "REPO", root)
    monkeypatch.setattr(OD, "_report", lambda *a, **k: "ISS-TEST")
    return root, calls


def _client(monkeypatch, user):
    app = FastAPI()
    app.include_router(OP.router)
    monkeypatch.setattr(auth, "user_of", lambda request: user)
    return TestClient(app)


def test_delegate_goes_through_owner_pick_handler(env):
    root, calls = env
    out = OD.tick(root, sync_looks=False)
    assert out["active"] is True and not out["errors"]
    by_id = {c["id"]: c for c in calls}
    assert by_id[FACE] == {"kind": "face", "id": FACE, "choice": "s2", "by": "总调度代选"}       # 3 项全过的 s2；s3 年龄不过不可选
    assert by_id[SCENE]["choice"] == "a"                                                           # b 画面里有人（count fail）不可选
    st = OP.state_of(root, FACE)
    assert st["state"] == "done" and st["delegate"]["via"] == "delegate:L-136" and st["delegate"]["choice"] == "s2"
    dec = [d for d in OQ.decisions(root) if d["id"] == FACE]
    assert dec and dec[-1]["via"] == "delegate:L-136" and dec[-1]["by"] == "总调度代选"
    items, _ = OQ.pick_items(root, OQ._closed(root, 0))                                            # 条目保留在通知里，带代选状态
    it = next(i for i in items if i["id"] == FACE)
    assert it["pick_state"]["delegate"]["label"] == "候选 s2"
    OD.tick(root, sync_looks=False)                                                                # 再一拍不重复
    assert len([c for c in calls if c["id"] == FACE]) == 1


def test_audit_log_and_page(env):
    root, _ = env
    OD.tick(root, sync_looks=False)
    rows = [json.loads(x) for x in (root / OD.LOG_REL).read_text(encoding="utf-8").splitlines()]
    pk = next(r for r in rows if r.get("event") == "pick" and r["item"] == FACE)
    assert pk["choice"] == "s2" and pk["score"] is not None and pk["reason"] and pk["at"] and len(pk["scores"]) == 3
    assert any(s["score"] is None and "age" in s["why"] for s in pk["scores"])
    page = (root / OD.PAGE_REL).read_text(encoding="utf-8")
    assert "挑 A 的身份脸" in page and "候选 s2" in page


def test_expired_by_owner_decision_no_more_delegate(env):
    root, calls = env
    _w(root / "data/audit/20261103.jsonl", json.dumps({"at": "2026-11-03T02:40:00", "user": "fred", "role": "owner", "method": "POST",
                                                        "path": "/api/script-autoflow/r/gate", "status": 200}) + "\n")
    out = OD.tick(root, sync_looks=False)
    assert out["active"] is False and calls == []
    cfg = OD.load_cfg(root)
    assert cfg["enabled"] is False and cfg["expiry"]["expired_kind"] == "owner_decision"


def test_owner_decision_before_enable_or_ignored_paths_do_not_expire(env):
    root, calls = env
    rows = [{"at": "2026-11-03T02:17:50", "role": "owner", "method": "POST", "path": "/api/owner/pick", "status": 202},     # 开启之前
            {"at": "2026-11-03T02:41:00", "role": "owner", "method": "POST", "path": "/api/voices/preview", "status": 200},  # 试听不算决定
            {"at": "2026-11-03T02:42:00", "role": "owner", "method": "POST", "path": "/api/owner/pick", "status": 422},     # 没成功
            {"at": "2026-11-03T02:43:00", "role": "agent/未登录", "method": "POST", "path": "/api/owner/pick", "status": 202}]
    _w(root / "data/audit/20261103.jsonl", "\n".join(json.dumps(r) for r in rows) + "\n")
    assert OD.tick(root, sync_looks=False)["active"] is True and calls


def test_revoke_stops_delegate(env, monkeypatch):
    root, calls = env
    c = _client(monkeypatch, None)
    assert c.post("/api/owner/delegate/revoke").status_code == 403                     # 只有登录项目方能一键撤销
    c = _client(monkeypatch, {"name": "fred", "role": "owner"})
    r = c.post("/api/owner/delegate/revoke")
    assert r.status_code == 200 and r.json()["enabled"] is False
    assert OD.tick(root, sync_looks=False)["active"] is False and calls == []
    assert c.get("/api/owner/delegate").json()["label"] is None


def test_owner_revise_and_repick_override_delegate(env, monkeypatch):
    root, calls = env
    OD.tick(root, sync_looks=False)
    c = _client(monkeypatch, {"name": "fred", "role": "owner"})
    r = c.post("/api/owner/pick", json={"id": FACE, "choice": "s1", "reason": "这张更像"})   # 在已代选的条目上改选 = 修改
    assert r.status_code == 202 and r.json()["duplicate"] is False
    st = OP.state_of(root, FACE)
    assert st["state"] == "revise_requested" and st["by"] == "fred" and "改选候选 s1" in st["reason"]
    assert len([x for x in calls if x["id"] == FACE]) == 1                               # 处理器不重跑（原有修改机制）
    r = c.post("/api/owner/pick", json={"id": SCENE, "choice": "revise", "reason": "要更暗"})
    assert OP.state_of(root, SCENE)["state"] == "revise_requested"
    items, _ = OQ.pick_items(root, OQ._closed(root, 0))
    assert {FACE, SCENE} <= {i["id"] for i in items}                                     # 仍在通知里显示“已提修改意见”
    dec = [d for d in OQ.decisions(root) if d["id"] == FACE]
    assert dec[-1]["choice"] == "revise" and dec[-1]["by"] == "fred"
    OD.tick(root, sync_looks=False)                                                     # 代选不再碰项目方动过的条目
    assert len([x for x in calls if x["id"] == FACE]) == 1


def test_adult_items_never_delegated(env):
    root, calls = env
    reqs = json.loads((root / "data/owner_queue/requests.json").read_text(encoding="utf-8"))
    reqs = [{"id": "pick:look:r:ep01:abc", "kind": "pick", "title": "确认第 1 集造型", "run": "r", "episode": 1,
             "people": [{"cid": "x", "ready": True, "thumb_note": "成人造型，网页不显示图"}],
             "candidates": [{"key": "confirm", "label": "确认本集造型", "contract_ok": True}]},
            {"id": "pick:face:ch_z", "kind": "pick", "title": "挑 Z 的成人镜身份脸", "candidates": reqs[0]["candidates"]},
            {"id": "pick:item:ch_z:A_x", "kind": "pick", "title": "单品", "candidates": [{**reqs[0]["candidates"][1], "route": "local_only"}]}]
    _w(root / "data/owner_queue/requests.json", reqs)
    OD.tick(root, sync_looks=False)
    assert calls == []
    rows = [json.loads(x) for x in (root / OD.LOG_REL).read_text(encoding="utf-8").splitlines()]
    assert {r["item"] for r in rows if r.get("event") == "skip"} == {r["id"] for r in reqs}
    assert OD.never_reason({"kind": "decide", "category": "delete"})                     # 拍板类（删除 / 花钱 …）不代


def test_look_confirm_when_assets_ready(env):
    root, calls = env
    _w(root / "data/owner_queue/requests.json", [
        {"id": "pick:look:r:ep02:x", "kind": "pick", "title": "确认第 2 集造型", "people": [{"cid": "a", "ready": True}],
         "candidates": [{"key": "confirm", "label": "确认本集造型", "contract_ok": True}]},
        {"id": "pick:look:r:ep03:y", "kind": "pick", "title": "确认第 3 集造型", "people": [{"cid": "a", "ready": False, "wait": "缺鞋"}],
         "candidates": [{"key": "confirm", "label": "确认本集造型", "contract_ok": True}]}])
    OD.tick(root, sync_looks=False)
    assert [c["id"] for c in calls] == ["pick:look:r:ep02:x"]


def test_voice_score_uses_check(tmp_path):
    root = tmp_path
    sup = []
    for k, cer, ok in (("a", 0.2, True), ("b", 0.0, True), ("c", 0.0, False)):
        d = f"data/assets/voices_v2/zhuo_lin/{k}"
        sup.append({"cand": k, "dir": d})
        _w(root / d / "meta.json", {"checks": {"pass": ok, "items": {"cer": {"value": cer, "pass": True}, "f0_hz": {"pass": ok}}}})
    _w(root / "config/voices_v2.json", {"support_candidates": {"roles": {"zhuo_lin": {"candidates": sup}}}})
    req = {"id": "pick:voice_v2:zhuo_lin", "recommend": "a", "candidates": [{"key": k, "label": k, "contract_ok": True} for k in "abc"]}
    ch = OD.choose(root, "voice", req)
    assert ch["key"] == "b" and next(s for s in ch["scores"] if s["key"] == "c")["score"] is None


# ------------------------------------------------------------------ 写作闸门
def _gate_run(root: Path, verdict: str, totals, items_by_judge: dict, passed: bool, with_direction: bool):
    rd = root / "data/pipeline/runs/r"
    canon = rd / "P1_storyline.json"
    _w(canon, {"title": "t"})
    sha = hashlib.sha256(canon.read_text(encoding="utf-8").encode("utf-8")).hexdigest()[:16]
    _w(rd / "owner_gates.json", {"enabled": True, "gates": {}, "history": []})
    _w(rd / "autoflow.json", {"verdict": verdict})
    rdir = "data/pipeline/runs/r/judge_p1/r5"
    mean = round(sum(totals) / len(totals))
    item_mean = {k: round(sum(j[k] for j in items_by_judge.values()) / len(items_by_judge), 2) for k in next(iter(items_by_judge.values()))}
    _w(root / rdir / "RESULT.json", {"n": 3, "totals": totals, "mean": mean, "item_mean": item_mean, "top_fixes": ["结尾补一个在场画面"]})
    for i, (jid, its) in enumerate(items_by_judge.items(), 1):
        _w(root / rdir / f"judge_{i}" / "out" / "p1_review.json", {"judge_id": jid, "items": [{"id": k, "score": v} for k, v in its.items()]})
    st = {"rounds": [{"n": 5, "sha": sha, "dir": rdir, "passed": passed}]}
    if with_direction:
        st["owner_direction"] = {"at": "2026-11-03T01:00:00", "by": "总调度", "round": 5, "mean": mean, "sha": sha}
    _w(rd / "judge_p1/STATE.json", st)
    return rd


def _og():
    return OD._og()


def test_gate_released_when_mean_ge_30_and_no_low_item(env):
    root, _ = env
    rd = _gate_run(root, "owner_direction", [32, 31, 31], {"j1": {"a": 4, "b": 3}, "j2": {"a": 4, "b": 4}, "j3": {"a": 3, "b": 4}}, False, True)
    spawned = []
    OD.gate_tick(root, spawn=lambda rd_, ep: spawned.append(ep) or {"pid": 0})
    g = _og().get(rd, "P1")
    assert g["status"] == "approved" and g["by"] == "总调度代选" and g["released_by_delegate"] and not g["released_by_owner"]
    h = _og().summary(rd)["history"][-1]
    assert h["via"] == "delegate:L-136" and "总调度代选放行" in h["audit"] and spawned == [1]
    rows = [json.loads(x) for x in (root / OD.LOG_REL).read_text(encoding="utf-8").splitlines()]
    assert any(r.get("event") == "gate_approve" and r["mean"] == 31 for r in rows)


def test_gate_held_below_30_in_owner_direction(env):
    root, _ = env
    rd = _gate_run(root, "owner_direction", [30, 29, 28], {"j1": {"a": 4}, "j2": {"a": 3}, "j3": {"a": 3}}, False, True)
    spawned = []
    OD.gate_tick(root, spawn=lambda rd_, ep: spawned.append(ep))
    assert _og().get(rd, "P1")["status"] == "pending" and spawned == []        # 不放行、不冒充项目方点“修改”
    rows = [json.loads(x) for x in (root / OD.LOG_REL).read_text(encoding="utf-8").splitlines()]
    assert any(r.get("event") == "gate_hold" and r["issue"] == "ISS-TEST" for r in rows)
    OD.gate_tick(root, spawn=lambda rd_, ep: spawned.append(ep))                # 同一稿不重复登记
    assert sum(1 for x in (root / OD.LOG_REL).read_text(encoding="utf-8").splitlines() if "gate_hold" in x) == 1


def test_gate_low_item_sends_back_to_patch_loop(env):
    root, _ = env
    rd = _gate_run(root, "awaiting_owner_p1", [36, 35, 34], {"j1": {"a": 5, "b": 2}, "j2": {"a": 5, "b": 4}, "j3": {"a": 4, "b": 4}}, True, False)
    spawned = []
    OD.gate_tick(root, spawn=lambda rd_, ep: spawned.append(ep))
    g = _og().get(rd, "P1")
    assert g["status"] == "revise_requested" and g["by"] == "总调度代选" and "j1:b=2" in g["note"] and spawned == [1]


def test_gate_owner_already_acted_not_overridden(env):
    root, _ = env
    rd = _gate_run(root, "awaiting_owner_p1", [36, 35, 34], {"j1": {"a": 5}, "j2": {"a": 5}, "j3": {"a": 4}}, True, False)
    _og().act(rd, "P1", "revise", "我要改结尾", "fred")
    OD.gate_tick(root, spawn=lambda rd_, ep: None)
    assert _og().get(rd, "P1")["by"] == "fred"


def test_delegate_cannot_redirect(env):
    root, _ = env
    rd = _gate_run(root, "owner_direction", [32, 31, 31], {"j1": {"a": 4}}, False, True)
    with pytest.raises(PermissionError):
        _og().act(rd, "P1", "redirect", "换方向", "总调度代选", delegate={"via": "delegate:L-136"})


def test_already_auto_picked_notice_not_delegated(env):
    root, calls = env
    reqs = json.loads((root / "data/owner_queue/requests.json").read_text(encoding="utf-8"))
    reqs[0].update(auto_picked="s1", notice=True, title="已自动选用：A（候选 s1），可修改")
    _w(root / "data/owner_queue/requests.json", reqs[:1])
    OD.tick(root, sync_looks=False)
    assert calls == []                                                                  # asset_worker 已登记过，不重复登记


def test_golden_first_frame_delegated_and_revisable(env, monkeypatch):
    root, calls = env
    gid = "pick:golden:r:ep02:S01"
    _w(root / "data/owner_queue/requests.json", [{"id": gid, "kind": "pick", "title": "挑第 2 集 S01 金样首帧", "run": "r",
        "candidates": [_face_cand(root, "g1", [True, False], sims={"ch_a": 0.70}), _face_cand(root, "g2", [True, True], sims={"ch_a": 0.82})]}])
    OD.tick(root, sync_looks=False)
    assert [(c["id"], c["choice"], c["by"]) for c in calls] == [(gid, "g2", "总调度代选")]
    c = _client(monkeypatch, {"name": "fred", "role": "owner"})
    c.post("/api/owner/pick", json={"id": gid, "choice": "revise", "reason": "换一张"})
    assert OP.state_of(root, gid)["state"] == "revise_requested" and gid in {i["id"] for i in OQ.pick_items(root, OQ._closed(root, 0))[0]}


# ---- W29：首帧代选真能代（P1-7 / P2-8 / P2-9）----
def test_w29_real_lane_shapes_only_laptop_is_local_only():
    """P1-7：真实 ep01 takes.json 的 producer.lane 形状是 gpu33:x / gpu36:x（laptop:x 是 L-165 分区后才有）；
    只有 laptop: 前缀判本地专用，gpu 道不误判"""
    for lane, local in (("gpu33:3", False), ("gpu36:0", False), ("gpu33:0", False), ("laptop:0", True)):
        got = OD._cand_lane({"n": 1, "producer": {"lane": lane}}, {})
        assert got == lane
        assert got.startswith(OD.LOCAL_LANE_PREFIX) is local


def test_w29_owner_marks_ignores_rows_before_run_created(tmp_path):
    """P2-8：audit / decisions 无剧名，本剧创建前的行不算；之后的行、无法解析时间的行仍算"""
    a = tmp_path / "data" / "audit"
    a.mkdir(parents=True)
    old = {"at": "2026-11-01T17:37:00", "user": "fred", "method": "POST", "path": "/api/shots/ep01-S1/takes/image/2/lock"}
    new = {"at": "2026-11-03T10:00:00", "user": "fred", "method": "POST", "path": "/api/shots/ep01-S2/takes/image/1/lock"}
    odd = {"user": "fred", "method": "POST", "path": "/api/shots/ep01-S3/takes/image/1/unlock"}
    (a / "x.jsonl").write_text("\n".join(json.dumps(r) for r in (old, new, odd)), encoding="utf-8")
    assert set(OD._owner_marks(tmp_path)) == {"ep01-S1", "ep01-S2", "ep01-S3"}
    assert set(OD._owner_marks(tmp_path, "2026-11-02T18:28:50")) == {"ep01-S2", "ep01-S3"}


def test_w29_auto_locked_summary_recognizes_delegate():
    """P2-9：摘要 _auto_locked 认 locked_by.by=="delegate"（与 auto 同状态）"""
    from ns_api import app as A
    t = {"locked": {"image": 2}, "locked_by": {"image": {"by": "delegate", "n": 2}}}
    assert A._auto_locked(t, {}) == {"image": 2}
    t["locked"]["image"] = 3
    assert A._auto_locked(t, {}) == {}
