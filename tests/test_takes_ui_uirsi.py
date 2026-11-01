"""UIRSI：画布候选版本 + 撤销“用这张”（假数据目录）。"""
import json
import sys
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/agent"):
    sys.path.insert(0, str(ROOT / p))

from ns_api import takes_ui as T  # noqa: E402
from ns_render import pipeline as P  # noqa: E402


def test_candidates_and_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    d = tmp_path / "renders" / "ep02" / "S1"
    (d / "takes").mkdir(parents=True)
    (d / "takes" / "image_001_pipeline.png").write_bytes(b"x" * 10)
    take = {"n": 1, "stage": "image", "file": "renders/ep02/S1/takes/image_001_pipeline.png", "source": "pipeline",
            "params": {"tentative": True, "label": "旧配方"}}
    (d / "takes.json").write_text(json.dumps({"takes": [take], "active": {}}), encoding="utf-8")
    monkeypatch.setattr(P, "bad_reason", lambda t: None)
    app = FastAPI()
    app.include_router(T.router)
    c = TestClient(app)
    r = c.get("/api/candidates?ep=2").json()["shots"]["ep02-S1"]["image"]
    assert r["active"] is None and r["takes"][0]["label"] == "旧配方" and r["takes"][0]["tentative"] is True
    assert r["takes"][0]["ok"] is False and "不合格" in r["takes"][0]["why_not"]  # 项目方判过不合格的配方不作候选
    assert r["takes"][0]["url"].startswith("/files/renders/ep02/S1/takes/image_001_pipeline.png?v=")
    # 用这张之后撤销：当前不是 expect 时 409，是时清掉
    data = json.loads((d / "takes.json").read_text(encoding="utf-8"))
    data["active"]["image"] = 1
    (d / "takes.json").write_text(json.dumps(data), encoding="utf-8")
    (d / "frame.png").write_bytes(b"x")
    assert c.post("/api/shots/ep02-S1/takes/image/unset", json={"expect": 2}).status_code == 409
    assert c.post("/api/shots/ep02-S1/takes/image/unset", json={"expect": 1}).json()["active"] == {}
    assert not (d / "frame.png").exists()
    assert c.post("/api/shots/ep02-S1/takes/video/unset", json={"expect": 1}).status_code == 400
    assert c.get("/api/candidates?ep=9").json()["shots"] == {}
    # 新配方、质检通过 → ok；质检 ok=false → 不给挑
    (d / "takes" / "image_002_pipeline.png").write_bytes(b"x" * 10)
    (d / "takes" / "image_003_pipeline.png").write_bytes(b"x" * 10)
    data = json.loads((d / "takes.json").read_text(encoding="utf-8"))
    data["takes"] += [dict(take, n=2, file="renders/ep02/S1/takes/image_002_pipeline.png", params={"tentative": True, "label": "新配方"}),
                      dict(take, n=3, file="renders/ep02/S1/takes/image_003_pipeline.png", params={"label": "新配方", "origin": {"qc": {"ok": False}}})]
    (d / "takes.json").write_text(json.dumps(data), encoding="utf-8")
    ok = {x["n"]: x["ok"] for x in c.get("/api/candidates?ep=2").json()["shots"]["ep02-S1"]["image"]["takes"]}
    assert ok == {1: False, 2: True, 3: False}


def test_reject_and_undo(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(P, "bad_reason", lambda t: None)
    d = tmp_path / "renders" / "ep01" / "S2"
    (d / "takes").mkdir(parents=True)
    takes = []
    for n in (1, 2):
        (d / "takes" / f"image_00{n}.png").write_bytes(b"x" * 10)
        takes.append({"n": n, "stage": "image", "file": f"renders/ep01/S2/takes/image_00{n}.png", "params": {"label": "新配方"}})
    takes[1]["gen_contract"] = {"post": {"status": "pass"}}
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": {"image": 2}}), encoding="utf-8")
    monkeypatch.setattr(P, "set_active", lambda shot, st, n, **kw: _set(d, st, n))   # K-OPS-Q23：set_active 多了 reason / actor
    app = FastAPI()
    app.include_router(T.router)
    c = TestClient(app)
    row = c.get("/api/candidates?ep=1").json()["shots"]["ep01-S2"]["image"]
    assert [x["contract"] for x in row["takes"]] == [None, "pass"]
    r = c.post("/api/shots/ep01-S2/takes/image/2/reject", json={"reason": "脸不像"}).json()
    assert r == {"was_active": True, "active": 1}
    row = c.get("/api/candidates?ep=1").json()["shots"]["ep01-S2"]["image"]
    assert row["takes"][1]["ok"] is False and "脸不像" in row["takes"][1]["why_not"] and row["takes"][1]["rejected"]
    c.post("/api/shots/ep01-S2/takes/image/2/unreject", json={"restore_active": True})
    row = c.get("/api/candidates?ep=1").json()["shots"]["ep01-S2"]["image"]
    assert row["active"] == 2 and row["takes"][1]["ok"] is True


def _set(d, st, n):
    data = json.loads((d / "takes.json").read_text(encoding="utf-8"))
    data["active"][st] = n
    (d / "takes.json").write_text(json.dumps(data), encoding="utf-8")


def _regen_setup(tmp_path, monkeypatch, takes, active=None, locked=None):
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    d = tmp_path / "renders" / "ep03" / "S2"
    (d / "takes").mkdir(parents=True)
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": active or {}, "locked": locked or {}}), encoding="utf-8")
    app = FastAPI()
    app.include_router(T.router)
    return TestClient(app)


def test_regen_endpoint_goes_through_frame_jobs(tmp_path, monkeypatch):
    """↻ 再生成：走 /frame-jobs 的同一条校验和提交（mode=regen、parent=当前版、新 seed），不在这里设当前（G3）"""
    from ns_api import frame_jobs as FJ
    from ns_api import jobs as J
    from ns_api import material_readiness as MR
    c = _regen_setup(tmp_path, monkeypatch, [
        {"n": 4, "stage": "image", "file": "renders/ep03/S2/takes/image_004.png", "seed": 111, "path": "unified_frame（K-REN-134）"},
    ], active={"image": 4})
    monkeypatch.setattr(FJ, "_shot", lambda s: None)
    monkeypatch.setattr(MR, "job_gate", lambda *a, **k: None)
    monkeypatch.setattr(FJ, "_lane", lambda g: "gpu33:0")
    seen = {}

    def fake_submit(kind, shot, gpu, run, params=None, **kw):
        seen.update(kind=kind, shot=shot, params=params, kw=kw)
        return {"job_id": "j1", "status": "queued"}
    monkeypatch.setattr(J, "submit", fake_submit)
    r = c.post("/api/shots/ep03-S2/takes/image/4/regen", json={}).json()
    assert r["job_id"] == "j1" and r["regen_of"] == 4 and r["mode"] == "regen" and r["seed"] != 111
    assert seen["kind"] == "frame" and seen["shot"] == "ep03-S2"
    p = seen["params"]
    assert p["mode"] == "regen" and p["parent"] == 4 and p["stage"] == "first" and p["seed"] == r["seed"]
    assert "prompt" not in p   # 唯一出图路径：提示词按剧本重新编译，不拿旧版本的整段提示词覆盖
    data = json.loads((tmp_path / "renders/ep03/S2/takes.json").read_text(encoding="utf-8"))
    assert data["active"] == {"image": 4}   # 提交时不动当前版本
    # 没有的版本 / 视频阶段
    assert c.post("/api/shots/ep03-S2/takes/image/9/regen", json={}).status_code == 404
    assert c.post("/api/shots/ep03-S2/takes/video/4/regen", json={}).status_code == 400


def test_regen_last_needs_locked_first(tmp_path, monkeypatch):
    from ns_api import frame_jobs as FJ
    from ns_api import material_readiness as MR
    c = _regen_setup(tmp_path, monkeypatch, [{"n": 1, "stage": "last", "file": "x.png", "seed": 5}])
    monkeypatch.setattr(FJ, "_shot", lambda s: None)
    monkeypatch.setattr(MR, "job_gate", lambda *a, **k: None)
    monkeypatch.setattr(FJ, "_lane", lambda g: "gpu33:0")
    r = c.post("/api/shots/ep03-S2/takes/last/1/regen", json={})
    assert r.status_code == 409 and "首帧还没定稿" in r.json()["detail"]


def test_regen_body_follows_edit_mode():
    """改图来的版本：同父版本、同修改要求、同幅度、同参考，再改一次；整张替换过提示词的旧路径版本照原提示词"""
    t = {"n": 7, "stage": "image", "mode": "refs", "parent": 5, "instruction": "换成红色高跟鞋", "strength": "large", "seed": 9,
         "refs": [{"path": "assets/x.png", "role": "item"}, {"role": "style"}]}
    b = T.regen_body(t, "image", 7, 42)
    assert b == {"stage": "first", "mode": "refs", "parent": 5, "instruction": "换成红色高跟鞋", "seed": 42, "strength": "large",
                 "refs": [{"path": "assets/x.png", "role": "item"}]}
    b = T.regen_body({"n": 3, "stage": "last", "basis_prompt": "编译版", "prompt": "改过的整段", "params": {"preset": "C"}}, "last", 3, 8)
    assert b == {"stage": "last", "mode": "regen", "parent": 3, "seed": 8, "prompt": "改过的整段", "preset": "C"}


def test_regen_with_requirement_and_gear(tmp_path, monkeypatch):
    """弹窗写了要求 / 传了装备图：在这一版上改图（refs / instruct），父版本 = 这一版"""
    from ns_api import frame_jobs as FJ
    from ns_api import jobs as J
    from ns_api import material_readiness as MR
    from ns_render import frame_edit as FE
    c = _regen_setup(tmp_path, monkeypatch, [{"n": 2, "stage": "image", "file": "renders/ep03/S2/takes/image_002.png", "seed": 1}],
                     active={"image": 2})
    monkeypatch.setattr(FJ, "_shot", lambda s: None)
    monkeypatch.setattr(MR, "job_gate", lambda *a, **k: None)
    monkeypatch.setattr(FJ, "_lane", lambda g: "gpu33:0")
    monkeypatch.setattr(FE, "resolve_ref_path", lambda d: d)
    seen = {}
    monkeypatch.setattr(J, "submit", lambda kind, shot, gpu, run, params=None, **kw: seen.update(params=params) or {"job_id": "j2"})
    r = c.post("/api/shots/ep03-S2/takes/image/2/regen",
               json={"refs": [{"path": "assets/characters/lin_wan/wardrobe/lw-shoes-1_v1.png", "role": "item", "label": "鞋"}]}).json()
    p = seen["params"]
    assert r["mode"] == "refs" and p["mode"] == "refs" and p["parent"] == 2
    assert "鞋（图2）" in p["instruction"] and p["refs"][0]["path"].endswith("lw-shoes-1_v1.png")
    c.post("/api/shots/ep03-S2/takes/image/2/regen", json={"instruction": "手里换成咖啡杯"})
    assert seen["params"]["mode"] == "instruct" and seen["params"]["instruction"] == "手里换成咖啡杯" and seen["params"]["parent"] == 2


def test_old_script_versions_are_history_not_candidates(tmp_path, monkeypatch):
    """UIRSI r40（项目方 11-02 00:0x：“我…看到很多错误的图”）：本集最后一次导入之前出的版本 = 旧剧本版本，不作候选；
    原来的“不合格 / 脸不像”原因仍在 why_not 里；没有出图时间的不藏；现行剧本 sha 的照常是候选"""
    monkeypatch.setattr(P, "DATA", tmp_path)
    monkeypatch.setattr(P, "RENDERS", tmp_path / "renders")
    monkeypatch.setattr(P, "bad_reason", lambda t: None)
    log = tmp_path / "import_log.jsonl"
    log.write_text(json.dumps({"at": "2026-11-01T23:21:45", "rc": 0, "path": "data/staging_v3/merged/x_series10_v1_hwd_ep06_v3.md"}) + "\n", encoding="utf-8")
    script = tmp_path / "script_v2.json"
    script.write_text("{}", encoding="utf-8")
    monkeypatch.setattr(T, "IMPORT_LOG", log)
    monkeypatch.setattr(T, "SCRIPT", script)
    T._imp_cache.update(mt=None)
    T._sha_cache.update(mt=None)
    import hashlib
    sha = hashlib.sha256(b"{}").hexdigest()
    d = tmp_path / "renders" / "ep06" / "S1"
    (d / "takes").mkdir(parents=True)
    takes = []
    for n, ca, prm in ((1, "2026-11-01T08:00:00", {"rejected": {"reason": "脸不像"}}), (2, "2026-11-01T09:00:00", {}),
                       (3, None, {}), (4, "2026-11-01T23:40:00", {}), (5, "2026-11-01T10:00:00", {"prompt_source": {"sha256": sha}})):
        (d / "takes" / f"image_00{n}.png").write_bytes(b"x")
        takes.append({"n": n, "stage": "image", "file": f"renders/ep06/S1/takes/image_00{n}.png", "created_at": ca, "params": prm})
    (d / "takes.json").write_text(json.dumps({"takes": takes, "active": {}}), encoding="utf-8")
    r = T.candidates(6)["shots"]["ep06-S1"]["image"]["takes"]
    by = {x["n"]: x for x in r}
    assert by[1]["script"] == "old" and by[1]["ok"] is False and "脸不像" in by[1]["why_not"] and "旧剧本版本" in by[1]["why_not"]
    assert by[2]["script"] == "old" and by[2]["ok"] is False and by[2]["why_not"].startswith("旧剧本版本")
    assert by[3]["script"] == "unknown" and by[3]["ok"] is True
    assert by[4]["script"] == "current" and by[4]["ok"] is True
    assert by[5]["script"] == "current" and by[5]["ok"] is True       # 带现行剧本 sha 的以 sha 为准
    assert T.cutoff_for(6) == "2026-11-01T23:21:45" and T.cutoff_for(5) is None
