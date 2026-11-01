"""fredw-92/UXF1：UX 审查 #6 / #8 的后端部分。
- 坏图检查（ns_render.image_check）：太小 / 文件太小 / 尺寸与请求不符 → take.bad，不设为当前、不能定稿（409）
- 根因：任务线程在测试 monkeypatch 撤掉后还在跑 → jobs 记提交时的数据目录，变了就不执行；conftest 收尾先 drain
- 项目方在画布里拍板：POST /api/sop/owner-decision 必须 by=owner + 原话，记录与命令行同一份逻辑
- 「待你决定」标题用中文名"""
import json
import queue
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image

from ns_api import app as app_mod
from ns_api import jobs as J
from ns_render import frame_edit as FE
from ns_render import image_check as IC
from ns_render import pipeline as P

SHOT = "ep02-S1"


def _img(path: Path, size=(768, 1344), noise=True):
    path.parent.mkdir(parents=True, exist_ok=True)
    if noise:
        import os
        Image.frombytes("RGB", size, os.urandom(size[0] * size[1] * 3)).save(path)
    else:
        Image.new("RGB", size, (120, 90, 80)).save(path)
    return path


@pytest.fixture()
def data(tmp_path, monkeypatch):
    d = tmp_path / "data"
    (d / "renders").mkdir(parents=True)
    monkeypatch.setattr(P, "DATA", d)
    monkeypatch.setattr(P, "RENDERS", d / "renders")
    monkeypatch.setattr(IC, "ENABLED", True)
    monkeypatch.setattr(P, "stamp_versions", lambda sid, t: t)
    return d


def _take(n, rel, **kw):
    return P.Take(n=n, stage="image", file=rel, seed=1, prompt="", created_at=P.now(), **kw)


def test_check_file_rules(tmp_path):
    assert IC.check_file(_img(tmp_path / "ok.png")) is None
    tiny = IC.check_file(_img(tmp_path / "tiny.png", (64, 112), noise=False))
    assert tiny.startswith("坏图") and "64×112" in tiny and "字节" in tiny
    # 尺寸够、文件够，但与请求的尺寸差 > 10 %
    why = IC.check_file(_img(tmp_path / "wrong.png", (768, 1344)), (1152, 2016))
    assert why and "不符" in why
    assert IC.check_file(_img(tmp_path / "near.png", (768, 1344)), (800, 1400)) is None
    assert IC.check_file(tmp_path / "nope.png") == "坏图：文件不存在"
    (tmp_path / "junk.png").write_bytes(b"x" * 20000)
    assert IC.check_file(tmp_path / "junk.png") == "坏图：打不开"
    assert IC.expected_size({"params": {"pass2_size": [1152, 2016]}}) == (1152, 2016)
    assert IC.expected_size({"params": {"effective": {"rendered_size": [768, 1344]}}}) == (768, 1344)
    assert IC.expected_size({"params": None}) is None


def test_bad_take_never_active_or_locked(data):
    rel_ok, rel_bad = "renders/ep02/S1/takes/image_001.png", "renders/ep02/S1/takes/image_002.png"
    _img(data / rel_ok)
    _img(data / rel_bad, (64, 112), noise=False)
    P._add_take(SHOT, _take(1, rel_ok))
    assert P.load_takes(SHOT)["active"]["image"] == 1
    FE.lock(SHOT, "image", 1)
    P._add_take(SHOT, _take(2, rel_bad))                     # activate=True 也不设为当前
    tk = P.load_takes(SHOT)
    bad = next(t for t in tk["takes"] if t["n"] == 2)
    assert bad["bad"].startswith("坏图") and tk["active"]["image"] == 1 and tk["locked"]["image"] == 1
    assert (P.shot_dir(SHOT) / "frame.png").stat().st_size == (data / rel_ok).stat().st_size
    with pytest.raises(P.BadImage):
        P.set_active(SHOT, "image", 2)
    with pytest.raises(P.BadImage):
        FE.lock(SHOT, "image", 2)
    assert P.load_takes(SHOT)["locked"]["image"] == 1
    # 尺寸与请求不符（定稿档 1152×2016，实际 768×1344）
    rel_w = "renders/ep02/S1/takes/image_003_final.png"
    _img(data / rel_w)
    P._add_take(SHOT, _take(3, rel_w, params={"pass2_size": [1152, 2016]}))
    assert "不符" in next(t for t in P.load_takes(SHOT)["takes"] if t["n"] == 3)["bad"]
    assert P.load_takes(SHOT)["active"]["image"] == 1


@pytest.mark.skipif(not P.SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
def test_lock_endpoint_409_and_summary_flags(data):
    rel_ok, rel_bad = "renders/ep02/S1/takes/image_001.png", "renders/ep02/S1/takes/image_002.png"
    _img(data / rel_ok)
    _img(data / rel_bad, (64, 112), noise=False)
    P._add_take(SHOT, _take(1, rel_ok))
    P._add_take(SHOT, _take(2, rel_bad))
    c = TestClient(app_mod.app)
    r = c.post(f"/api/shots/{SHOT}/takes/first/2/lock")
    assert r.status_code == 409 and "坏图" in r.json()["detail"]
    assert c.post(f"/api/shots/{SHOT}/takes/image/2/activate").status_code == 409
    d = c.get(f"/api/shots/{SHOT}").json()
    t2 = next(t for t in d["takes"]["takes"] if t["n"] == 2)
    assert t2["bad"].startswith("坏图")
    assert d["summary"]["bad"]["image"] is None and d["summary"]["first_frame_take"] == 1


def test_quarantine_tool_moves_and_restores(data):
    import importlib.util
    spec = importlib.util.spec_from_file_location("qbt", P.ROOT / "tools" / "quarantine_bad_takes.py")
    Q = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(Q)
    rel_ok, rel_bad = "renders/ep02/S1/takes/image_004.png", "renders/ep02/S1/takes/image_005_x_final.png"
    _img(data / rel_ok)
    P._add_take(SHOT, _take(4, rel_ok))
    FE.lock(SHOT, "image", 4)
    # 模拟事故：坏图被写进 takes.json 且成了当前（坏图检查上线前）
    _img(data / rel_bad, (64, 112), noise=False)
    tk = P.load_takes(SHOT)
    tk["takes"].append(_take(5, rel_bad, mode="final", parent=1).model_dump())
    tk["active"]["image"] = 5
    P._save_takes(SHOT, tk)
    bad = Q.scan(SHOT)
    assert [(b["n"], b["active"]) for b in bad] == [(5, True)]
    Q.repair(SHOT, bad)
    tk = P.load_takes(SHOT)
    t5 = next(t for t in tk["takes"] if t["n"] == 5)
    assert "/_quarantine/" in t5["file"] and (data / t5["file"]).is_file() and not (data / rel_bad).exists()
    assert t5["bad"] and t5["quarantined"] and tk["active"]["image"] == 4 and tk["locked"]["image"] == 4
    log = (data / "logs" / "quarantine_bad_takes.jsonl").read_text(encoding="utf-8").splitlines()
    assert [json.loads(x)["action"] for x in log] == ["quarantine", "set_active"]
    assert Q.scan(SHOT) == []


def test_job_skips_when_data_root_changed(tmp_path, monkeypatch):
    """根因：任务排队时的数据目录 ≠ 开跑时的 → 不执行（测试残留任务不会写进真数据）"""
    monkeypatch.setattr(P, "DATA", tmp_path / "a")
    q: "queue.Queue[str]" = queue.Queue()
    monkeypatch.setattr(J, "_lane", lambda gpu: q)
    ran = []
    job = J.submit("frame", SHOT, 0, lambda c, j: ran.append(1) or {})
    monkeypatch.setattr(P, "DATA", tmp_path / "b")
    monkeypatch.setattr(J, "client_factory", lambda gpu: None)
    threading.Thread(target=J._worker, args=(0, q), daemon=True).start()
    t0 = time.time()
    while J.get(job["id"])["state"] == "queued" and time.time() - t0 < 5:
        time.sleep(0.02)
    j = J.get(job["id"])
    assert j["state"] == "failed" and j["error"] == J.DATA_ROOT_CHANGED and ran == []


def test_drain_cancels_queued(monkeypatch):
    q: "queue.Queue[str]" = queue.Queue()
    monkeypatch.setattr(J, "_lane", lambda gpu: q)
    job = J.submit("frame", SHOT, 0, lambda c, j: {})
    assert J.drain(timeout_s=1) == []
    assert J.get(job["id"])["state"] == "cancelled"


# ---------------------------------------------------------------- 项目方在画布里拍板

class FakeStore:
    def __init__(self):
        self.calls = []

    def confirm_episodes(self, episodes, char, ref, at=None, revoke=False):
        if not ref.strip():
            raise ValueError("确认必须写项目方原话/消息引用")
        self.calls.append((episodes, char, ref))
        return [int(episodes)]


@pytest.fixture()
def owner(tmp_path, monkeypatch):
    root = tmp_path / "proj"
    (root / "data" / "sop").mkdir(parents=True)
    monkeypatch.setattr(app_mod, "SOP_ROOT", root)
    store = FakeStore()
    from ns_api import looks as LK
    monkeypatch.setattr(LK, "get_store", lambda: store)
    return TestClient(app_mod.app), root, store


def test_owner_decision_requires_owner_and_quote(owner):
    c, root, store = owner
    body = {"gate": "look", "character": "lin_wan", "episodes": "2", "quote": "就用这套"}
    assert c.post("/api/sop/owner-decision", json=body).status_code == 403               # 没 by=owner
    assert c.post("/api/sop/owner-decision", json={**body, "by": "agent"}).status_code == 403
    assert c.post("/api/sop/owner-decision", json={**body, "by": "owner", "gate": "x"}).status_code == 400
    assert store.calls == []
    # UIRSI 2026-10-31（项目方：“不需要每个东西都要打上一个字”）：登录的项目方不填原话也通过，自动记“登录点选”
    r = c.post("/api/sop/owner-decision", json={**body, "by": "owner", "quote": "  "})
    assert r.status_code == 200 and store.calls and "登录点选" in store.calls[-1][2]


def test_owner_decision_look_records_like_cli(owner):
    c, root, store = owner
    r = c.post("/api/sop/owner-decision", json={"gate": "look", "character": "lin_wan", "episodes": "2",
                                                "by": "owner", "quote": " 第二集就用这套造型 "})
    assert r.status_code == 200, r.text
    assert store.calls == [("2", "lin_wan", "第二集就用这套造型")]
    log = [json.loads(x) for x in (root / "data" / "sop" / "owner_ui_log.jsonl").read_text(encoding="utf-8").splitlines()]
    assert log[-1]["gate"] == "look" and log[-1]["quote"] == "第二集就用这套造型" and log[-1]["via"] == "canvas"


def test_owner_decision_g4_g5_use_cli_rules(owner):
    c, root, store = owner
    # G4：qa.json 不是 pass → 命令行同样的拒绝原因，409
    r = c.post("/api/sop/owner-decision", json={"gate": "G4", "episode": 1, "by": "owner", "quote": "锁"})
    assert r.status_code == 409 and "qa.json" in r.json()["detail"]
    assert not (root / "data" / "sop" / "owner_gates.json").exists()
    # G5 返工：不要求成片；记录与 tools/sop_owner.py g5 --rework 相同
    r = c.post("/api/sop/owner-decision", json={"gate": "G5", "episode": 3, "rework": True, "by": "owner",
                                                "quote": "节奏太慢，返工"})
    assert r.status_code == 200, r.text
    rec = json.loads((root / "data" / "sop" / "owner_gates.json").read_text(encoding="utf-8"))
    g = rec["g5"]["3"]
    assert (g["decision"], g["ref"], g["by"]) == ("rework", "节奏太慢，返工", "项目方")
    # G5 发布：没有成片 → 409
    r = c.post("/api/sop/owner-decision", json={"gate": "G5", "episode": 4, "by": "owner", "quote": "发"})
    assert r.status_code == 409 and "成片" in r.json()["detail"]


def test_owner_action_titles_use_chinese_names():
    from ns_api import sop as SOP
    assert SOP.char_name("lin_wan") == "林晚" and SOP.char_name("gu_chen") == "顾沉" and SOP.char_name("x") == "x"
