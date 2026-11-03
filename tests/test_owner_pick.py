"""INBOXPICK-S：待办通知中心里直接挑选并生效（POST /api/owner/pick）。全部用临时目录和夹具，不碰真实 config/voices_v2.json 和真实队列文件。"""
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
from ns_api import owner_pick as OP  # noqa: E402
from ns_api import owner_queue as OQ  # noqa: E402
from ns_post import run_media as RM  # noqa: E402

RID = "pick:voice_v2:zhuo_lin"


def _sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _w(p: Path, d) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(d if isinstance(d, bytes) else (d if isinstance(d, str) else json.dumps(d, ensure_ascii=False, indent=1)).encode("utf-8"))


def _cand(root: Path, role: str, k: str, gender: str) -> dict:
    d = f"data/assets/voices_v2/{role}/{k}"
    ref = f"ref-{role}-{k}".encode()
    _w(root / d / "ref.wav", ref)
    _w(root / d / "sample.wav", f"sample-{role}-{k}".encode())
    _w(root / d / "meta.json", {"gender": gender, "ref_text": "x", "clone": {"engine": "cosyvoice3_zs"}})
    return {"cand": k, "dir": d, "accent": "x", "ref_sha256": _sha(ref), "f0_hz": 250.0, "enabled": False, "status": "待选"}


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path
    lead = {"cand": "b", "dir": "data/assets/voices_v2/lead_f/b", "ref_wav": "data/assets/voices_v2/lead_f/b/ref.wav", "enabled": True, "selected": True}
    ref = b"lead-ref"
    _w(root / lead["dir"] / "ref.wav", ref)
    _w(root / lead["dir"] / "meta.json", {"gender": "female"})
    lead["ref_sha256"] = _sha(ref)
    cfg = {"enabled": True, "status": "owner_picked",
           "roles": {"lead_f": {"persona": "p", "candidates": [lead], "selected": "b"}},
           "cast_voice": {"map": {"lead_f": "lead_f"}, "why": {}, "unvoiced_note": "卓琳还没有"},
           "support_candidates": {"status": "待选", "roles": {"zhuo_lin": {
               "persona": "35 岁经纪人", "char_id": "ch_zhuo_lin", "selected": None,
               "candidates": [_cand(root, "zhuo_lin", k, "female") for k in "abc"]}}}}
    _w(root / "config" / "voices_v2.json", cfg)
    _w(root / "config" / "voices.json", {})
    # 音色挑选对应的剧从 runs.json 取（owner_pick.voice_run，不再写死 series10_v2）
    _w(root / "config" / "pipeline" / "runs.json", {"primary": "series10_v2", "legacy_unprefixed_run": "series10_v1", "runs": {
        "series10_v2": {"status": "preparing", "assets_manifest": "assets_v2/manifest.json"}, "series10_v1": {"status": "archived"}}})
    _w(root / "data/review_pages/v2_style/voice/zhuo_lin_b_sample.wav", b"sample-review-b")
    _w(root / "data" / "owner_queue" / "requests.json", [{
        "id": RID, "kind": "pick", "title": "挑一个卓琳的声音", "detail": "d", "source": "VOICE-S", "recommend": "b", "why": "带上海腔",
        "candidates": [{"key": k, "label": f"候选 {k}", "contract_ok": True, "score": 0} for k in "abc"]}])
    # voice_config 用真实代码跑，只把“这是 V2 剧”和“说话人表”换成夹具
    monkeypatch.setattr(RM, "is_asset_pack_run", lambda run, root=ROOT: True)
    monkeypatch.setattr(RM, "_speaker_cast", lambda run, root: {"names": {"祁念": "lead_f", "卓琳": "ch_zhuo_lin"}, "male": [], "female": ["lead_f", "ch_zhuo_lin"], "lead": "lead_f", "source": "fixture"})
    monkeypatch.setattr(OP, "REPO", root)
    return root


def _client(monkeypatch, user):
    app = FastAPI()
    app.include_router(OP.router)
    monkeypatch.setattr(auth, "user_of", lambda request: user)
    return TestClient(app)


def _cfg(root: Path) -> dict:
    return json.loads((root / "config" / "voices_v2.json").read_text(encoding="utf-8"))


def test_pick_item_carries_audio_and_recommend(env):
    items, auto = OQ.pick_items(env, set())
    assert auto == [] and len(items) == 1
    it = items[0]
    assert it["pick_api"] == "/api/owner/pick" and it["recommend"]["choice"] == "b"
    assert not any(o["key"] == "later" for o in it["options"])                        # L-123：没有“不要 / 稍后”，只有用这个 / 修改
    byk = {c["key"]: c for c in it["candidates"]}
    assert byk["b"]["audio"].startswith("/files/review_pages/v2_style/voice/zhuo_lin_b_sample.wav")   # 试听页副本
    assert byk["a"]["audio"].startswith("/files/assets/voices_v2/zhuo_lin/a/sample.wav")              # 没有副本 → 资产目录的 sample
    assert all(m["kind"] == "audio" and m["url"] for m in it["media"])


def test_pick_applies_roles_cast_voice_and_voice_config_loads(env, monkeypatch):
    c = _client(monkeypatch, {"name": "项目方", "role": "owner"})
    r = c.post("/api/owner/pick", json={"id": RID, "choice": "b", "by": "someone_else"})
    assert r.status_code == 202 and r.json()["accepted"] is True
    cfg = _cfg(env)
    role = cfg["roles"]["zhuo_lin"]
    assert role["selected"] == "b"
    sel = [x for x in role["candidates"] if x.get("selected") and x.get("enabled")]
    assert [x["cand"] for x in sel] == ["b"] and sel[0]["ref_wav"].endswith("zhuo_lin/b/ref.wav") and sel[0]["picked_by"] == "项目方"   # by 取登录会话
    assert all(x.get("archived") and not x["enabled"] for x in role["candidates"] if x["cand"] != "b")
    assert cfg["cast_voice"]["map"]["ch_zhuo_lin"] == "zhuo_lin" and "unvoiced_note" not in cfg["cast_voice"]
    assert "zhuo_lin" not in cfg["support_candidates"]["roles"]
    vc = RM.voice_config("series10_v2", env)                                   # 每个槽恰好 1 个启用音色 → 能正常加载
    assert vc["characters"]["ch_zhuo_lin"]["voice"] == "zhuo_lin/b" and not vc["unvoiced"]
    assert OP.state_of(env, RID)["state"] == "done"
    assert OQ.pick_items(env, set()) == ([], [])                                # 通知从页面上消失
    assert any(d.get("via") == "owner_pick" and d["by"] == "项目方" for d in OQ.decisions(env))


def test_duplicate_submit_processed_once(env, monkeypatch):
    calls = []
    real = OP.apply_voice_v2
    def counting(root, req, choice, by, verify=None):
        calls.append(choice)
        return real(root, req, choice, by, verify)
    counting.wired = True
    monkeypatch.setitem(OP.HANDLERS, "voice", counting)
    c = _client(monkeypatch, {"name": "项目方", "role": "owner"})
    r1 = c.post("/api/owner/pick", json={"id": RID, "choice": "b"})
    r2 = c.post("/api/owner/pick", json={"id": RID, "choice": "c"})
    assert r1.status_code == r2.status_code == 202
    assert r1.json()["duplicate"] is False and r2.json()["duplicate"] is True
    assert calls == ["b"] and _cfg(env)["roles"]["zhuo_lin"]["selected"] == "b"


def test_not_logged_in_or_not_owner_403_and_nothing_changes(env, monkeypatch):
    before = (env / "config" / "voices_v2.json").read_bytes()
    for user in (None, {"name": "查看者", "role": "viewer"}):
        r = _client(monkeypatch, user).post("/api/owner/pick", json={"id": RID, "choice": "b", "by": "owner"})
        assert r.status_code == 403
    assert (env / "config" / "voices_v2.json").read_bytes() == before and OP.state_of(env, RID) == {}


def test_bad_choice_400_and_unwired_image_501(env, monkeypatch):
    c = _client(monkeypatch, {"name": "项目方", "role": "owner"})
    assert c.post("/api/owner/pick", json={"id": RID, "choice": "z"}).status_code == 400
    reqs = json.loads((env / "data/owner_queue/requests.json").read_text(encoding="utf-8"))
    # AUTOPIPE-A 11-03：face / scene / sheet / item 已接线（统一入口）；没接的类型（例 music）仍 501、仍走旧的 /decide
    reqs.append({"id": "pick:music:ep01", "kind": "pick", "candidates": [{"key": "1", "contract_ok": True}, {"key": "2", "contract_ok": True}]})
    _w(env / "data/owner_queue/requests.json", reqs)
    assert c.post("/api/owner/pick", json={"id": "pick:music:ep01", "choice": "1"}).status_code == 501
    assert OQ.pick_items(env, set())[0][-1]["pick_api"] is None
    assert OP.wired("pick:face:ch_x") and OP.wired("v2cast-sk_white_cyc")


def test_failed_verify_rolls_back_and_item_reappears(env, monkeypatch):
    before = (env / "config" / "voices_v2.json").read_bytes()
    (env / "data/assets/voices_v2/zhuo_lin/b/ref.wav").write_bytes(b"tampered")                              # sha 不符
    c = _client(monkeypatch, {"name": "项目方", "role": "owner"})
    assert c.post("/api/owner/pick", json={"id": RID, "choice": "b"}).status_code == 202
    st = OP.state_of(env, RID)
    assert st["state"] == "failed" and "sha" in st["error"]
    assert (env / "config" / "voices_v2.json").read_bytes() == before                                         # 没写
    assert [i["id"] for i in OQ.pick_items(env, set())[0]] == [RID]                                           # 通知还在，可再点


def test_voice_config_failure_after_write_restores_file(env):
    before = (env / "config" / "voices_v2.json").read_bytes()
    def bad(root):
        raise OP.PickError("加载不通过")
    with pytest.raises(OP.PickError):
        OP.apply_voice_v2(env, {"id": RID}, "a", "项目方", verify=bad)
    assert (env / "config" / "voices_v2.json").read_bytes() == before


def test_revise_keeps_item_and_changes_no_config(env, monkeypatch):
    before = (env / "config" / "voices_v2.json").read_bytes()
    c = _client(monkeypatch, {"name": "项目方", "role": "owner"})
    assert c.post("/api/owner/pick", json={"id": RID, "choice": "revise", "reason": "想要再甜一点"}).status_code == 202
    assert (env / "config" / "voices_v2.json").read_bytes() == before
    it = OQ.pick_items(env, set())[0][0]
    assert it["pick_state"]["state"] == "revise_requested" and "甜" in it["pick_state"]["reason"]


def test_replay_old_decision_once(env):
    """旧入口（/decide）留下的选择：补执行一次，by 取原记录，标 replayed_from；重复跑不重复写"""
    OQ._record(env, {"id": RID, "kind": "pick", "choice": "c", "by": "fred"})
    OQ._record(env, {"id": "pick:voice_v2:other", "kind": "pick", "choice": "a", "by": "POLICY"})        # 系统自动选的不补
    r = OP.replay(env)
    assert [(x["id"], x["choice"], x["by"], x["state"]) for x in r] == [(RID, "c", "fred", "done")]
    cfg = _cfg(env)
    assert cfg["roles"]["zhuo_lin"]["selected"] == "c" and cfg["cast_voice"]["map"]["ch_zhuo_lin"] == "zhuo_lin"
    assert RM.voice_config("series10_v2", env)["characters"]["ch_zhuo_lin"]["voice"] == "zhuo_lin/c"
    # RESTARTFIX-O（ISS-1103-011049-7420）：补执行写 via=owner_pick:cli（API 启动补执行 = owner_pick:startup）+ pid，分得清是哪个进程补的
    import os as _os
    rec = [d for d in OQ.decisions(env) if d.get("via") == "owner_pick:cli"][-1]
    assert rec["by"] == "fred" and rec["applied"]["replayed_from"].endswith(RID) and rec["pid"] == _os.getpid()
    assert OP.state_of(env, RID).get("via") is None or OP.state_of(env, RID)["via"] == "owner_pick:cli"
    before = (env / "config" / "voices_v2.json").read_bytes()
    assert OP.replay(env) == [] and (env / "config" / "voices_v2.json").read_bytes() == before            # 再跑不重复（via 以 owner_pick 开头的不再补）
    assert sum(1 for d in OQ.decisions(env) if str(d.get("via") or "").startswith("owner_pick")) == 1


def test_replay_failure_rolls_back_then_retry_ok(env):
    OQ._record(env, {"id": RID, "kind": "pick", "choice": "b", "by": "fred"})
    (env / "data/assets/voices_v2/zhuo_lin/b/ref.wav").write_bytes(b"tampered")
    before = (env / "config" / "voices_v2.json").read_bytes()
    assert OP.replay(env)[0]["state"] == "failed" and (env / "config" / "voices_v2.json").read_bytes() == before
