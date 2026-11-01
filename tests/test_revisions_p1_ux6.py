"""UX6：资产二次修改 P1（B_revision §7 P1）+ 资产中心 B6–B10（A_assets_ia §5）。

全部在临时项目根里跑：不碰真实 data/ 与 config/，不提交任务。验证：
快照（observe 自动留 / 覆盖前自动留）、set-current 闸门 403、回滚恢复母版、配置型只写提议不改 config、
保留旧版豁免只对一个 rev 生效、成片落后 N 镜 + 音色改动、LoRA registry 扩展（视频 LoRA 带 sha 与定妆 rev）、
版本链 vs 另存为新资产、历史复制映射、道具 / 音色提议 / 提示词模板作者闸门。
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_agent import asset_revs as AR
from ns_agent import asset_revs_p1 as ARP
from ns_agent import lora_registry as LR
from ns_render import pipeline as P

QUOTE = "项目方原话：回到上一版定妆"


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, bytes):
        p.write_bytes(obj)
    else:
        p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


@pytest.fixture
def root(tmp_path: Path, monkeypatch) -> Path:
    r = tmp_path
    _w(r / "assets" / "characters" / "lin_wan" / "plates" / "master.png", b"master-v1")
    _w(r / "assets" / "characters" / "lin_wan" / "lin_wan.png", b"face-v1")
    _w(r / "config" / "face_reference.json", {"reference": "assets/characters/lin_wan/lin_wan.png"})
    _w(r / "config" / "auto_lora_triggers.json",
       {"characters": {"林晚": [{"trigger": "lnwan_qi", "kind": "image", "file": "lin_wan_qi_v1.safetensors",
                                "strength": 0.8}]}})
    _w(r / "data" / "renders_gpu3" / "LORA_REGISTRY.json",
       {"loras": [{"file": "lin_wan_qi_v1.safetensors", "sha256": "s1", "status": "accepted", "kind": "image"}]})
    _w(r / "comfy" / "models.lock", {"loras": [{"file": "lin_wan_h3_v1.safetensors", "kind": "video_lora",
                                                "status": "training", "sha256": None,
                                                "triggers": [{"trigger": "lnwan01"}]}]})
    _w(r / "config" / "voices.json", {"tts_model": {"id": "kokoro"},
                                      "characters": {"lin_wan": {"name": "林晚", "sid": 36, "voice": "zf_067", "speed": 0.9}}})
    _w(r / "config" / "render_quality.json", {
        "image_presets": [{"id": "leica_sstar", "label": "徕卡 S★", "tier": "preview", "params": {"steps": 8}}],
        "user_presets": [], "video_bases": {"bases": [{"id": "official_base", "steps": 24}]},
        "optional_video_loras": [], "prompt_guard": {"video_identity_enabled": False}})
    _w(r / "training" / "lora_lin_wan" / "dataset_manifest.json", {"trigger": "lnwan_qi", "count": 1, "images": [
        {"file": "m.png", "source": "plates/master.png", "source_sha256": hashlib.sha256(b"master-v1").hexdigest()}]})
    monkeypatch.setattr(P, "ROOT", r)
    monkeypatch.setattr(P, "DATA", r / "data")
    monkeypatch.setattr(P, "RENDERS", r / "data" / "renders")
    monkeypatch.setattr(AR, "RACY_S", 0)        # 测试里同一秒内反复改文件：不走 mtime 缓存
    return r


@pytest.fixture
def client(root):
    from ns_api import cuts, revisions, revisions_p1
    app = FastAPI()
    for rt in (revisions.router, revisions_p1.router, cuts.router):
        app.include_router(rt)
    return TestClient(app)


def _config_bytes(root: Path) -> dict:
    return {p.name: p.read_bytes() for p in (root / "config").glob("*.json")}


# ------------------------------------------------------------------ 快照 + set-current

def test_observe_snapshots_every_current_rev(root):
    AR.observe(root)
    r1 = AR.current_rev("identity:lin_wan", root)
    man = ARP.read_snapshot("identity:lin_wan", r1, root)
    assert man and man["copied"]["master"]["from"] == "assets/characters/lin_wan/plates/master.png"
    assert (ARP.snap_dir("identity:lin_wan", r1, root) / "master.png").read_bytes() == b"master-v1"
    assert ARP.has_snapshot("voice:lin_wan", AR.current_rev("voice:lin_wan", root), root)
    assert str(ARP.snap_dir("identity:lin_wan", r1, root)).replace("\\", "/").count("data/assets/snapshots/identity/lin_wan/")


def test_set_current_identity_gate_403_and_rollback(client, root):
    client.get("/api/revisions/keys")                       # baseline + 快照 v1
    v1 = AR.current_rev("identity:lin_wan", root)
    _w(root / "assets" / "characters" / "lin_wan" / "plates" / "master.png", b"master-v2")   # 有人直接覆盖
    client.get("/api/revisions/keys")                       # observed v2 + 快照 v2
    v2 = AR.current_rev("identity:lin_wan", root)
    assert v1 != v2
    det = client.get("/api/revisions/identity:lin_wan").json()
    assert det["gated"] is True and all(v["has_snapshot"] for v in det["versions"])
    url = "/api/revisions/identity:lin_wan/set-current"
    assert client.post(url, json={"rev": v1, "by": "canvas"}).status_code == 403
    assert client.post(url, json={"rev": v1, "by": "owner"}).status_code == 403          # 没原话
    assert client.post(url, json={"rev": v1, "by": "owner", "owner_quote": "  "}).status_code == 403
    r = client.post(url, json={"rev": v1, "by": "owner", "owner_quote": QUOTE})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["applied"] is True and j["restored"] == ["assets/characters/lin_wan/plates/master.png"]
    assert (root / "assets" / "characters" / "lin_wan" / "plates" / "master.png").read_bytes() == b"master-v1"
    led = AR.read_ledger(root)["identity:lin_wan"]
    assert led[-1]["rev"] == v1 and led[-1]["by"] == "owner" and led[-1]["owner_quote"] == QUOTE
    assert led[-1]["rollback"] is True and led[-1]["seq"] == 1
    assert AR.observe(root) == []                            # 回滚已登记，不会再被当成“未登记的改动”
    # 被覆盖掉的 v2 内容还在快照里，能再回去
    assert (ARP.snap_dir("identity:lin_wan", v2, root) / "master.png").read_bytes() == b"master-v2"
    acts = client.get("/api/revisions/identity:lin_wan/actions").json()["actions"]
    assert acts[-1]["applied"] and acts[-1]["owner_quote"] == QUOTE


def test_set_current_without_snapshot_409(client, root):
    AR.observe(root)
    r = client.post("/api/revisions/identity:lin_wan/set-current",
                    json={"rev": "deadbeef0000", "by": "owner", "owner_quote": QUOTE})
    assert r.status_code == 409 and "快照" in r.json()["detail"]


def test_config_backed_rollback_writes_proposal_not_config(client, root):
    client.get("/api/revisions/keys")
    old = AR.current_rev("preset:leica_sstar", root)
    q = json.loads((root / "config" / "render_quality.json").read_text(encoding="utf-8"))
    q["image_presets"][0]["params"]["steps"] = 12
    _w(root / "config" / "render_quality.json", q)
    client.get("/api/revisions/keys")
    before = _config_bytes(root)
    r = client.post("/api/revisions/preset:leica_sstar/set-current", json={"rev": old, "by": "canvas"})
    assert r.status_code == 200, r.text                      # 预设不是身份类闸门；但只写提议
    j = r.json()
    assert j["applied"] is False and j["proposal"]["kind"] == "set_current"
    ch = j["proposal"]["changes"]["config"]
    assert ch["config"] == "config/render_quality.json" and ch["to"]["params"]["steps"] == 8
    assert ch["from"]["params"]["steps"] == 12
    assert _config_bytes(root) == before                     # config/ 一个字节没动
    assert (root / j["proposal"]["file"]).is_file()
    # 音色 = 闸门类：没原话 403
    assert client.post("/api/revisions/voice:lin_wan/set-current",
                       json={"rev": "x", "by": "owner"}).status_code == 403


def test_snapshot_before_overwrite_helper(root):
    done = ARP.snapshot_before_overwrite("assets/characters/lin_wan/plates/master.png", root)
    assert done == ["identity:lin_wan"]
    assert ARP.has_snapshot("identity:lin_wan", AR.current_rev("identity:lin_wan", root), root)


# ------------------------------------------------------------------ 保留旧版（kept）

def _takes(root: Path, deps: dict) -> None:
    _w(root / "data" / "renders" / "ep02" / "S1" / "takes.json", {
        "takes": [{"n": 1, "stage": "image", "file": "renders/ep02/S1/takes/image_001.png", "deps": deps}],
        "active": {"image": 1}, "locked": {"image": 1}})


def test_keep_old_requires_owner_and_only_one_rev(client, root):
    r1 = AR.current_rev("preset:leica_sstar", root)
    _takes(root, {"preset:leica_sstar": r1})
    q = json.loads((root / "config" / "render_quality.json").read_text(encoding="utf-8"))
    q["image_presets"][0]["params"]["steps"] = 9
    _w(root / "config" / "render_quality.json", q)
    d = client.get("/api/shots/ep02-S1/deps").json()["stages"]["image"][0]
    assert d["stale_deps"][0]["key"] == "preset:leica_sstar" and d["stale_deps"][0]["waived"] is None
    body = {"stage": "image", "key": "preset:leica_sstar", "n": 1}
    assert client.post("/api/shots/ep02-S1/deps/keep", json={**body, "by": "canvas", "owner_quote": "x"}).status_code == 403
    assert client.post("/api/shots/ep02-S1/deps/keep", json={**body, "by": "owner"}).status_code == 403
    w = client.post("/api/shots/ep02-S1/deps/keep", json={**body, "by": "owner", "owner_quote": "这镜保留旧版"}).json()
    assert w["rev_at_waiver"] == AR.current_rev("preset:leica_sstar", root)
    d = client.get("/api/shots/ep02-S1/deps").json()["stages"]["image"][0]
    assert d["stale_deps"][0]["waived"]["owner_quote"] == "这镜保留旧版"
    q["image_presets"][0]["params"]["steps"] = 10            # 依赖再变一次 → 豁免失效，重新提示
    _w(root / "config" / "render_quality.json", q)
    d = client.get("/api/shots/ep02-S1/deps").json()["stages"]["image"][0]
    assert d["stale_deps"][0]["waived"] is None
    assert len(client.get("/api/shots/ep02-S1/deps/waivers").json()["waivers"]) == 1


# ------------------------------------------------------------------ 成片过期

def test_cut_deps_behind_and_voice(client, root):
    ep = root / "data" / "episodes"
    _w(ep / "ep02_v1.mp4", "x")
    _w(ep / "ep02_v1.timeline.json", {"shots": [
        {"shot": "ep02-S1", "kind": "video", "file": "data/renders/ep02/S1/takes/video_001.mp4"}]})
    _w(root / "data" / "renders" / "ep02" / "S1" / "takes.json", {
        "takes": [{"n": 1, "stage": "video", "file": "renders/ep02/S1/takes/video_001.mp4"},
                  {"n": 2, "stage": "video", "file": "renders/ep02/S1/takes/video_002.mp4"}],
        "locked": {"video": 2}, "active": {"video": 2}})
    import os
    os.utime(ep / "ep02_v1.mp4", (1, 1))                     # 成片很早就合成了
    AR.observe(root)
    v = json.loads((root / "config" / "voices.json").read_text(encoding="utf-8"))
    v["characters"]["lin_wan"]["speed"] = 1.0
    _w(root / "config" / "voices.json", v)
    AR.observe(root)                                         # 记一条 voice observed（时间在成片之后）
    j = client.get("/api/episodes/2/cut/deps").json()
    assert j["stale"] is True and j["behind"] == 1 and j["changed"][0]["shot_id"] == "ep02-S1"
    assert [x["key"] for x in j["voices_changed"]] == ["voice:lin_wan"]
    assert client.get("/api/episodes/3/cut/deps").json()["cut"] is None


# ------------------------------------------------------------------ LoRA registry 扩展

def test_lora_registry_video_entry_sha_and_identity(client, root):
    _w(root / "data" / "ab" / "lora" / "lin_wan_h3_v1.safetensors", b"weights")
    body = {"file": "lin_wan_h3_v1.safetensors", "kind": "video", "character": "lin_wan", "step": 250,
            "local_path": "data/ab/lora/lin_wan_h3_v1.safetensors", "by": "agent:train",
            "dataset_manifest": "training/lora_lin_wan/dataset_manifest.json"}
    e = client.post("/api/loras/registry", json=body).json()
    assert e["status"] == "candidate" and e["sha256"] == hashlib.sha256(b"weights").hexdigest()
    assert e["from_identity_rev"] == AR.current_rev("identity:lin_wan", root) and e["dataset_sha"]
    assert client.post("/api/loras/registry", json={**body, "status": "accepted"}).status_code == 403
    assert client.post("/api/loras/registry", json=body).status_code == 422          # 同一 lora_id 不重复登记
    assert AR.current_rev("loraslot:lin_wan:video", root) is None                    # 还没采用 → 指针没有
    url = f"/api/loras/registry/{e['lora_id']}/status"
    assert client.post(url, json={"status": "accepted", "by": "owner"}).status_code == 403
    assert client.post(url, json={"status": "accepted", "by": "owner", "owner_quote": "用 step250"}).status_code == 200
    rv = AR.current_rev("loraslot:lin_wan:video", root)
    assert rv and "loraslot:lin_wan:video" in AR.all_keys(root)
    assert AR.label("loraslot:lin_wan:video") == "林晚 视频身份 LoRA"
    t = client.get("/api/loras").json()
    row = next(x for x in t["loras"] if x["file"] == "lin_wan_h3_v1.safetensors")
    assert row["kind"] == "video" and row["status"] == "accepted" and row["owner"] == "林晚"
    assert {"comfy/models.lock", "登记扩展"} <= set(row["sources"])
    assert row["versions"][0]["identity_outdated"] is False
    img = next(x for x in t["loras"] if x["file"] == "lin_wan_qi_v1.safetensors")
    assert img["slot"] == "loraslot:lin_wan:image" and img["sha256"] == "s1"
    assert t["datasets"][0]["identity_outdated"] == {"lin_wan": False}
    # 定妆母版换了 → 训练数据 / 视频 LoRA 标“来自旧定妆”
    _w(root / "assets" / "characters" / "lin_wan" / "plates" / "master.png", b"master-v2")
    t = client.get("/api/loras").json()
    row = next(x for x in t["loras"] if x["file"] == "lin_wan_h3_v1.safetensors")
    assert row["versions"][0]["identity_outdated"] is True
    assert t["datasets"][0]["identity_outdated"] == {"lin_wan": True}
    # 这些写入都没碰 gpu3 registry / models.lock / config
    assert json.loads((root / "comfy" / "models.lock").read_text(encoding="utf-8"))["loras"][0]["sha256"] is None


# ------------------------------------------------------------------ B6–B10（需要 LookStore）

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 32


@pytest.fixture
def center(root, monkeypatch):
    from ns_agent.looks import LookStore
    from ns_api import asset_center_p1 as ACP
    from ns_api import asset_edit as AED
    from ns_api import assets as A
    from ns_api.looks import get_store
    from ns_schema.looks import Look
    store = LookStore(root / "data" / "looks")
    store.upsert_look(Look(id="lw-look-b", character="lin_wan", name="通勤 B", label="B", items={}))
    monkeypatch.setattr(A, "ROOT", root)
    monkeypatch.setattr(A, "ASSETS_DIR", root / "assets")
    app = FastAPI()
    for rt in (ACP.router, AED.router):
        app.include_router(rt)
    app.dependency_overrides[get_store] = lambda: store
    for n in (1, 2, 3):
        _w(root / "assets" / "characters" / "lin_wan" / "src" / f"g{n}.png", PNG + bytes([n]))
    return TestClient(app), store


def test_b6_version_chain_vs_save_as_and_history_copies(center, root):
    c, store = center
    n0 = len(store.lookbook().looks)
    f = lambda n: f"assets/characters/lin_wan/src/g{n}.png"   # noqa: E731
    v = c.post("/api/assets/lw-look-b/versions", json={"file": f(1), "label": "a", "mode": "version"}).json()
    assert v["asset_id"] == "lw-look-b" and v["in_place"] is True
    v = c.post("/api/assets/lw-look-b/versions", json={"file": f(2), "label": "b", "mode": "version"}).json()
    assert v["asset_id"] == "lw-look-b" and store.get_look("lw-look-b").version == 3
    assert len(store.lookbook().looks) == n0                 # 新版本不复制新资产
    k = c.post("/api/assets/lw-look-b/fork", json={"file": f(3), "label": "另一套"}).json()
    assert k["asset_id"].startswith("lw-look-b-v") and k["in_place"] is False
    assert c.post("/api/assets/lw-look-b/versions", json={"file": f(3), "mode": "bogus"}).status_code == 422
    ch = c.get("/api/assets/lw-look-b/chain").json()
    assert [x["version"] for x in ch["versions"] if x["kind"] == "in_place"] == [3, 2]
    assert ch["versions"][0]["current"] is True
    assert [x["asset_id"] for x in ch["copies"]] == [k["asset_id"]] and ch["copies"][0]["mapped"] == "历史复制"
    assert store.get_look(k["asset_id"])                      # 映射只显示：复制出的资产还在
    # 回到链上的 v2
    old = next(x["file"] for x in ch["versions"] if x["version"] == 2)
    r = c.post("/api/assets/lw-look-b/chain/set-current", json={"file": old, "by": "canvas"}).json()
    assert r["changed"] is True and store.get_look("lw-look-b").preview_image == old
    assert c.post("/api/assets/lw-look-b/chain/set-current", json={"file": "assets/x.png"}).status_code == 422


def test_b7_b8_b10_props_voices_templates(center, root):
    c, _store = center
    before = _config_bytes(root)
    assert c.post("/api/props", json={"name": " "}).status_code == 422
    p = c.post("/api/props", json={"name": "手机", "kind": "product", "lora_file": "phone_v1.safetensors"}).json()
    assert c.put(f"/api/props/{p['id']}", json={"name": "手机 2"}).json()["name"] == "手机 2"
    assert c.put("/api/props/lora-nprng2", json={"name": "x"}).status_code == 404
    assert any(x["id"] == p["id"] and x["editable"] for x in c.get("/api/props").json()["props"])
    vs = c.get("/api/voices").json()
    assert vs["characters"][0]["cid"] == "lin_wan" and vs["characters"][0]["sid"] == 36
    assert c.post("/api/voices/lin_wan/proposals", json={"changes": {"pitch": 1}}).status_code == 422
    pr = c.post("/api/voices/lin_wan/proposals", json={"changes": {"speed": "1.0"}, "by": "canvas"}).json()
    assert pr["to"] == {"speed": 1.0} and pr["from"] == {"speed": 0.9} and pr["requires_owner"] is True
    assert pr["owner_confirmed"] is False and (root / pr["file"]).is_file()
    assert c.get("/api/voices").json()["characters"][0]["pending"][0]["proposal_id"] == pr["proposal_id"]
    assert _config_bytes(root) == before                     # 音色提议不改 config
    # 模板：正文只能项目方 / 写作方写
    assert c.post("/api/prompt-templates", json={"name": "立绘", "text": "x", "by": "claude"}).status_code == 403
    t = c.post("/api/prompt-templates", json={"name": "立绘", "kind": "portrait", "text": "T1", "by": "owner"}).json()
    assert t["id"] == "pt-001" and t["current_v"] == 1
    t = c.put(f"/api/prompt-templates/{t['id']}", json={"text": "T2", "by": "writer:qwen"}).json()
    assert t["current_v"] == 2 and t["versions"][0]["text"] == "T1"
    assert c.post(f"/api/prompt-templates/{t['id']}/refs", json={"target": "asset:lw-look-b", "v": 9}).status_code == 422
    c.post(f"/api/prompt-templates/{t['id']}/refs", json={"target": "asset:lw-look-b"})
    assert c.get(f"/api/prompt-templates/{t['id']}/usage").json()["refs"][0]["v"] == 2
