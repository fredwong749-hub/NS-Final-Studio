"""W-PICK 11-07（项目方 11-07 01:1x：“需要我点击的有 bug，我点了好几次，它好像没有记录下来”）：
已有登记时项目方点选 = 同一张就确认（no-op）、不同就替换（旧图隔离 + replaced[] + 下游重做）；失败带一句人话；
已点过的挑选补执行幂等；系统 / 代选已选用的告知不进“待你看”。全部用临时目录（夹具复用 test_asset_pipeline）。"""
from __future__ import annotations

import json

import pytest

from test_asset_pipeline import AJ, OP, RUN, _j, _sha, _w, root  # noqa: F401  root 是夹具

from ns_api import owner_queue as OQ  # noqa: E402

SCENE = "pick:scene:sk_white_cyc"


def _scene_req(root, keys=("s1", "s2")):
    cands = []
    for k in keys:
        _w(root / f"data/review_pages/x/{k}.png", f"scene-{k}".encode())
        cands.append({"key": k, "label": k, "file": f"data/review_pages/x/{k}.png", "contract_ok": True, "sha256": _sha(f"scene-{k}".encode())})
    req = {"id": SCENE, "kind": "pick", "title": "已自动选用：影棚白幕 场景底图（s1），可修改", "run": RUN, "episode": 1, "candidates": cands,
           "auto_picked": "s1", "notice": True}
    OP.enqueue_pick(root, req)
    return req


def test_same_sha_is_noop_and_manifest_untouched(root):
    req = _scene_req(root)
    AJ.register_pick(root, "scene", req, "s1", AJ.AUTO_BY, push=False)               # 系统先代选 s1
    mp = root / "assets_v2/manifest.json"
    before = mp.read_bytes()
    res = AJ.register_pick(root, "scene", req, "s1", "fred", push=False)               # 项目方点的就是这张
    assert res["noop"] == "已是这张" and res["confirmed"] and mp.read_bytes() == before
    OP.accept(root, SCENE, "s1", "", "fred")
    row = OP.process(root, SCENE, "s1", "fred")
    assert row["state"] == "done" and row["result"]["noop"] == "已是这张"
    assert SCENE in OP.hidden_ids(root)                                                  # 点过就消失


def test_different_sha_replaces_with_quarantine_and_history(root):
    req = _scene_req(root)
    AJ.register_pick(root, "scene", req, "s1", AJ.AUTO_BY, push=False)
    old = _j(root / "assets_v2/manifest.json")["scenes"]["sk_white_cyc"]["base"]
    res = AJ.register_pick(root, "scene", req, "s2", "fred", push=False)
    base = _j(root / "assets_v2/manifest.json")["scenes"]["sk_white_cyc"]["base"]
    assert base["file"].endswith("_s2.png") and base["picked_by"] == "fred" and base["sha256"] == _sha(b"scene-s2")
    h = base["replaced"][0]
    assert h["original_file"] == old["file"] and h["sha256"] == old["sha256"] and h["file"].startswith("data/_quarantine/")
    assert (root / h["file"]).read_bytes() == b"scene-s1" and not (root / old["file"]).exists()          # 隔离不删
    assert res["replaced"]["quarantined_to"] == h["file"]
    # 系统 / 代选不能推翻项目方的选择
    with pytest.raises(AJ.RegisterError, match="只有项目方本人能换"):
        AJ.register_pick(root, "scene", req, "s1", "总调度代选", push=False)


def test_replace_rolls_back_quarantine_when_manifest_changed_underneath(root, monkeypatch):
    req = _scene_req(root)
    AJ.register_pick(root, "scene", req, "s1", AJ.AUTO_BY, push=False)
    old = _j(root / "assets_v2/manifest.json")["scenes"]["sk_white_cyc"]["base"]["file"]
    real = AJ._read_manifest

    def racing(p):
        d, sha = real(p)
        p.write_text(p.read_text(encoding="utf-8") + " ", encoding="utf-8")
        return d, sha
    monkeypatch.setattr(AJ, "_read_manifest", racing)
    with pytest.raises(AJ.RegisterError, match="被别人改了"):
        AJ.register_pick(root, "scene", req, "s2", "fred", push=False)
    assert (root / old).read_bytes() == b"scene-s1"                                      # 旧图回到原处


def test_face_replace_redoes_sheets_and_reports(root):
    for k in ("f1", "f2"):
        _w(root / f"data/review_pages/x/{k}.png", k.encode())
    req = {"id": "pick:face:ch_tang_yao", "run": RUN, "episode": 1, "candidates": [
        {"key": k, "file": f"data/review_pages/x/{k}.png", "contract_ok": True} for k in ("f1", "f2")]}
    AJ.register_pick(root, "face", req, "f1", AJ.AUTO_BY, push=False)
    mp = root / "assets_v2/manifest.json"
    d = _j(mp)
    _w(root / "assets_v2/characters/ch_tang_yao/looks/s.png", b"sheet")
    d["characters"]["ch_tang_yao"]["looks"] = {"A": {"sheet": {"file": "assets_v2/characters/ch_tang_yao/looks/s.png", "sha256": _sha(b"sheet")},
                                                     "items": {"A_shoes1": {"file": "x.png", "source": "assets_v2/characters/ch_tang_yao/looks/s.png"}}}}
    _w(mp, d)
    _w(AJ.job_path(root, RUN, "sheet-ch_tang_yao-A"), {"id": "sheet-ch_tang_yao-A", "run": RUN, "kind": "sheet", "state": "done", "attempts": 2,
                                                       "spec": {"cid": "ch_tang_yao", "look": "A"}, "pick_id": "pick:sheet:ch_tang_yao:A"})
    res = AJ.register_pick(root, "face", req, "f2", "fred", push=False)
    lk = _j(mp)["characters"]["ch_tang_yao"]["looks"]["A"]
    assert "sheet" not in lk and lk["sheets_replaced"][0]["file"].endswith("s.png") and lk["items_replaced"][0]["iid"] == "A_shoes1"
    assert res["redo_jobs"] == ["sheet-ch_tang_yao-A"] and AJ.load_job(AJ.job_path(root, RUN, "sheet-ch_tang_yao-A"))["state"] == "pending"
    assert "身份脸被fred换了" in (root / "data/pipeline/issues.jsonl").read_text(encoding="utf-8")       # 大声记卡点


def test_frozen_run_refused_with_clear_reason(root):
    req = _scene_req(root)
    cfg = _j(root / "config/pipeline/runs.json")
    cfg["runs"][RUN]["status"] = "frozen"
    _w(root / "config/pipeline/runs.json", cfg)
    with pytest.raises(AJ.RegisterError, match="已冻结"):
        AJ.register_pick(root, "scene", req, "s1", "fred", push=False)


def test_failed_pick_shows_human_reason_not_silent(root):
    _scene_req(root)
    OP.accept(root, SCENE, "s2", "", "fred")

    def boom(*a, **k):
        raise PermissionError("[WinError 5] Access is denied: 'manifest.json.tmp' -> 'manifest.json'")
    row = OP.process(root, SCENE, "s2", "fred", apply_fn=boom)
    assert row["state"] == "failed" and "再点一次" in row["error"] and "WinError" in row["error_raw"]
    assert "\n" not in row["error"] and len(row["error"]) <= 120
    items, _ = OQ.pick_items(root, set())
    it = next(i for i in items if i["id"] == SCENE)
    assert it["pick_state"]["state"] == "failed" and not it["delegated_notice"]          # 失败的卡片在“待你看”里，带原因


def test_auto_picked_notice_goes_to_delegated_section(root):
    req = _scene_req(root)
    AJ.register_pick(root, "scene", req, "s1", AJ.AUTO_BY, push=False)
    q = OQ.build(root)
    assert SCENE not in {i["id"] for i in q["items"]}
    d = next(i for i in q["delegated"] if i["id"] == SCENE)
    assert d["block_level"] == "grey" and d["pick_api"] == "/api/owner/pick"            # 仍可在卡片里改选


def test_repeat_click_on_done_is_duplicate_not_revise(root):
    _scene_req(root)
    OP._set_state(root, SCENE, state="done", choice="s1", by="总调度代选", delegate={"at": OP._now(), "by": "总调度代选", "choice": "s1"})
    OP._set_state(root, SCENE, state="done", choice="s1", by="fred")
    r = OP.accept(root, SCENE, "s1", "", "fred")
    assert r["duplicate"] and OP.state_of(root, SCENE)["state"] == "done"


def test_reapply_recorded_owner_picks_is_idempotent(root):
    req = _scene_req(root)
    AJ.register_pick(root, "scene", req, "s1", AJ.AUTO_BY, push=False)
    OP._set_state(root, SCENE, state="failed", choice="s2", by="fred", error="场景 sk_white_cyc 已经有底图，不重复登记")
    plan = OP.reapply(root)                                                              # dry-run
    assert [(p["id"], p["action"], p["before_sha"], p["chosen_sha"]) for p in plan] == [(SCENE, "replace", _sha(b"scene-s1"), _sha(b"scene-s2"))]
    assert OP.state_of(root, SCENE)["state"] == "failed"                                 # dry-run 不写
    out = OP.reapply(root, apply=True)
    assert out[0]["after"] == "done" and _j(root / "assets_v2/manifest.json")["scenes"]["sk_white_cyc"]["base"]["sha256"] == _sha(b"scene-s2")
    assert OP.reapply(root, apply=True) == []                                            # 再跑：没有要补的
    dec = [d for d in OQ.decisions(root) if d["id"] == SCENE]
    assert len(dec) == 1 and dec[0]["via"] == "owner_pick:reapply" and dec[0]["by"] == "fred"


def test_reapply_skips_owner_vs_owner_conflict_and_restores_bogus_revise(root):
    req = _scene_req(root)
    AJ.register_pick(root, "scene", req, "s1", "fred", push=False)                      # 项目方早先选了 s1
    OP._set_state(root, SCENE, state="failed", choice="s2", by="fred", error="x")       # 后来又点了 s2 但失败
    look = "pick:look:r:ep02:abc"
    OP.enqueue_pick(root, {"id": look, "title": "确认第 2 集造型", "candidates": [{"key": "confirm", "label": "确认", "contract_ok": True}]})
    OQ._record(root, {"id": look, "kind": "pick", "choice": "confirm", "by": "fred", "via": "owner_pick", "applied": {"ok": 1}})
    OP._set_state(root, look, state="revise_requested", choice="revise", by="fred", reason="改选候选 confirm（推翻代选的 confirm）")
    plan = {p["id"]: p for p in OP.reapply(root)}
    assert plan[SCENE]["action"] == "replace" and plan[SCENE]["conflict"] is True and plan[look]["action"] == "restore_done"
    out = {p["id"]: p for p in OP.reapply(root, apply=True)}
    assert out[SCENE]["after"] == "skipped" and OP.state_of(root, SCENE)["state"] == "failed"     # 推翻他自己的旧选择：交总调度确认
    assert out[look]["after"] == "done" and OP.state_of(root, look)["state"] == "done"
    out = {p["id"]: p for p in OP.reapply(root, apply=True, include_conflicts=True)}
    assert out[SCENE]["after"] == "done" and look not in out


def test_atomic_json_retries_permission_error(tmp_path, monkeypatch):
    """W-SCAN #1：os.replace 偶发 PermissionError（WinError 5）要重试，不让点卡 500；最终失败清掉 tmp"""
    import os
    from ns_api import owner_pick as OP
    calls = {"n": 0}
    real = os.replace
    def flaky(a, b):
        calls["n"] += 1
        if calls["n"] < 3:
            raise PermissionError("WinError 5")
        return real(a, b)
    monkeypatch.setattr(OP.os, "replace", flaky)
    OP._atomic_json(tmp_path / "s.json", {"a": 1})
    assert (tmp_path / "s.json").exists() and calls["n"] == 3
    monkeypatch.setattr(OP.os, "replace", lambda a, b: (_ for _ in ()).throw(PermissionError("x")))
    monkeypatch.setattr(OP.time, "sleep", lambda s: None)
    import pytest
    with pytest.raises(PermissionError):
        OP._atomic_json(tmp_path / "t.json", {"b": 2})
    assert not list(tmp_path.glob("t.json.*.tmp"))
