"""fredw-92/B-fix（审计 F3）：资产图片路径越界、上传 20 MB 上限、坏镜头号 404、任务表并发快照 + 内存上限、
episode_edit.json 每集锁、尾帧定稿前置检查在每镜锁内、next_shot_id 不在剧本 → None。"""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from ns_agent.looks import DEFAULT_SCRIPT_JSON
from ns_api import asset_edit as AED
from ns_api import assets as A
from ns_api import jobs as J
from ns_render import pipeline as P
from test_ref_switch_w5 import CLEAR, PNG, S1, env, script  # noqa: F401  复用夹具

needs_script = pytest.mark.skipif(not DEFAULT_SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")


# ---------------------------------------------------------------- 1. _path_ok

def test_path_ok_rejects_absolute_and_drive(tmp_path, monkeypatch):
    root, data = tmp_path / "proj", tmp_path / "proj" / "data"
    (root / "assets").mkdir(parents=True)
    data.mkdir(parents=True)
    (root / "assets" / "ok.png").write_bytes(PNG)
    outside = tmp_path / "x.png"
    outside.write_bytes(PNG)
    monkeypatch.setattr(A, "ROOT", root)
    monkeypatch.setattr(P, "DATA", data)
    assert AED._path_ok("assets/ok.png") == root / "assets" / "ok.png"
    anchor = Path(tmp_path.anchor).as_posix()       # "D:/" 或 "/"
    bad = ["/x.png", "/" + outside.relative_to(tmp_path.anchor).as_posix(), "D:x.png", "C:/x.png",
           anchor + outside.relative_to(tmp_path.anchor).as_posix(), "..\\x.png", "assets/../../x.png", "//srv/x.png", ""]
    for rel in bad:
        with pytest.raises(HTTPException) as e:
            AED._path_ok(rel)
        assert e.value.status_code == 422, rel


# ---------------------------------------------------------------- 2. 上传上限

def test_asset_ref_upload_size_cap(env, monkeypatch):
    c, _store, _root = env
    monkeypatch.setattr(AED, "MAX_UPLOAD_BYTES", 64)
    monkeypatch.setattr(AED, "UPLOAD_CHUNK", 16)
    r = c.post(f"/api/assets/{CLEAR}/refs", files={"file": ("a.png", PNG + b"0" * 100, "image/png")},
               data={"role": "style"})
    assert r.status_code == 413, r.text
    r = c.post(f"/api/assets/{CLEAR}/refs", files={"file": ("a.png", PNG, "image/png")}, data={"role": "style"})
    assert r.status_code == 200, r.text
    assert AED.MAX_UPLOAD_BYTES == 64 and 20 * 1024 * 1024 == 20971520


# ---------------------------------------------------------------- 3. 坏镜头号 → 404

@needs_script
@pytest.mark.parametrize("sid", ["abc", "a-b-c", "ep99-S1"])
def test_bad_shot_ids_404(sid):
    from ns_api import app as app_mod
    c = TestClient(app_mod.app)
    assert c.get(f"/api/shots/{sid}/video-takes").status_code == 404
    assert c.get(f"/api/shots/{sid}/frame-jobs").status_code == 404


# ---------------------------------------------------------------- 4. 任务表：快照 + 内存上限 + 读盘回落

@pytest.fixture()
def jobs_env(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(J, "_jobs", {})
    return tmp_path


def _mk(jid, state, t):
    job = {"id": jid, "job_id": jid, "kind": "frame", "shot_id": "ep01-S1", "gpu": 0, "state": state,
           "created_at": t, "finished_at": t if state in J.FINISHED else None}
    J._jobs[jid] = job
    J.persist(job)
    return job


def test_jobs_return_copies_and_prune_with_disk_fallback(jobs_env, monkeypatch):
    monkeypatch.setattr(J, "MAX_FINISHED", 2)
    for i in range(4):
        _mk(f"f{i}", "done", f"2026-01-0{i + 1}")
    _mk("q0", "queued", "2026-01-01")
    J._prune()
    assert set(J._jobs) == {"f2", "f3", "q0"}          # 最旧的已结束任务淘汰，排队中的不动
    got = J.get("f3")
    got["state"] = "x"
    assert J._jobs["f3"]["state"] == "done"            # 给出去的是副本
    assert J.get("f0")["state"] == "done"              # 淘汰后读盘
    assert J.job_status("f0")["id"] == "f0"
    assert J.get("nope") is None and J.get("../x") is None
    with pytest.raises(HTTPException):
        J.job_status("nope")


def test_jobs_concurrent_mutation_no_dict_changed_size(jobs_env):
    job = _mk("r0", "running", "2026-01-01")
    stop = threading.Event()

    def mutate():
        i = 0
        while not stop.is_set():
            with J._jobs_guard:
                job[f"k{i % 500}"] = i
                if i % 2:
                    job.pop(f"k{(i - 1) % 500}", None)
            i += 1
    t = threading.Thread(target=mutate, daemon=True)
    t.start()
    try:
        for _ in range(2000):
            json.dumps(J.get("r0"))
            J.all_jobs()
            J.pending("ep01-S1")
    finally:
        stop.set()
        t.join(5)


# ---------------------------------------------------------------- 5. 锁

def test_episode_lock_shared_and_used_by_scene_apply(env, monkeypatch):
    c, _store, _root = env
    assert P.episode_lock(2) is P.episode_lock(2) and P.episode_lock(2) is not P.episode_lock(3)
    seen = []
    real_save = P.save_episode_edit

    def spy(ep, ee):
        seen.append(P.episode_lock(ep)._is_owned())
        return real_save(ep, ee)
    monkeypatch.setattr(P, "save_episode_edit", spy)
    r = c.post(f"/api/shots/{S1}/refs/apply",
               json={"scope": "scene", "change": {"characters": {"林晚": {"parts": {"shoes": CLEAR}}}}})
    assert r.status_code == 200, r.text
    assert seen == [True]


@needs_script
def test_episode_edit_put_holds_episode_lock(tmp_path, monkeypatch):
    from ns_api import app as app_mod
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data" / "renders")
    ep = app_mod._script.episodes[0].number
    seen = []
    real_load = app_mod.load_episode_edit

    def spy(n):
        seen.append(P.episode_lock(n)._is_owned())
        return real_load(n)
    monkeypatch.setattr(app_mod, "load_episode_edit", spy)
    r = TestClient(app_mod.app).put(f"/api/episodes/{ep}/edit", json={"boost_first": "x"})
    assert r.status_code == 200, r.text
    assert seen and all(seen)


@needs_script
def test_lock_last_precondition_inside_shot_lock(tmp_path, monkeypatch):
    from ns_api import app as app_mod
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data" / "renders")
    sid = app_mod._script.episodes[0].shots[0].id
    seen = []
    real = P.load_takes

    def spy(shot_id):
        seen.append(P.shot_lock(shot_id)._is_owned())
        return real(shot_id)
    monkeypatch.setattr(P, "load_takes", spy)
    r = TestClient(app_mod.app).post(f"/api/shots/{sid}/takes/last/1/lock")
    assert r.status_code == 409, r.text
    assert seen and seen[-1] is True        # 409 前最后一次读 takes.json（前置检查）在每镜锁内


# ---------------------------------------------------------------- 6. next_shot_id

def test_next_shot_id_unknown_shot_returns_none(script):  # noqa: F811
    ids = [s.id for ep in script.episodes for s in ep.shots]
    assert P.next_shot_id(script, "ep99-S99") is None
    assert P.next_shot_id(script, ids[0]) == ids[1]
    assert P.next_shot_id(script, ids[-1]) is None
