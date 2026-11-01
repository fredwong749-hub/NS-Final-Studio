"""UX5-B P0（docs/ux_round5/B_revision.md）：资产版本 rev、Take.deps 盖章、“依赖已更新”、影响面接口。

全部在临时项目根里跑，不碰真实数据 / 配置；不提交任务。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_agent import asset_revs as AR
from ns_render import pipeline as P
from ns_schema.edits import Take

PRESETS = [{"id": "leica_sstar", "label": "徕卡 S★", "tier": "preview", "params": {"unet": "turbo", "steps": 8}},
           {"id": "preview_turbo", "label": "预览", "tier": "preview", "params": {"unet": "turbo"}}]
BASES = [{"id": "official_base", "label": "官方基模", "lora": None, "no_lora": True, "steps": 24, "cfg": 4.0,
          "guider": "CFGGuider", "sampler": "euler", "note": "说明"},
         {"id": "official_turbo", "label": "官方 8 步", "lora": "turbo.safetensors", "steps": 8}]


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def _quality(root: Path, presets=None, bases=None, default_preset="leica_sstar", default_base="official_base"):
    _w(root / "config" / "render_quality.json", {
        "default_preset": default_preset, "image_presets": presets or PRESETS, "user_presets": [],
        "video_bases": {"default": default_base, "bases": bases or BASES},
        "optional_video_loras": [{"id": "vbvr", "name": "VBVR.safetensors", "label": "VBVR", "sha256": "aa"}]})


def _take(stage="image", n=1, **kw) -> dict:
    return {"n": n, "stage": stage, "file": f"renders/ep02/S1/takes/{stage}_{n:03d}.png", "seed": 1, "prompt": "p",
            "created_at": "2026-10-31T10:00:00", **kw}


@pytest.fixture
def root(tmp_path: Path) -> Path:
    r = tmp_path
    _w(r / "assets" / "characters" / "lin_wan" / "plates" / "master.png", "master-v1")
    _w(r / "assets" / "characters" / "lin_wan" / "lin_wan.png", "face-v1")
    _w(r / "config" / "face_reference.json", {"reference": "assets/characters/lin_wan/lin_wan.png"})
    _w(r / "config" / "auto_lora_triggers.json",
       {"characters": {"林晚": [{"trigger": "lnwan_qi", "kind": "image", "file": "lin_wan_qi_v1.safetensors",
                                "strength": 0.8}]}})
    _w(r / "data" / "renders_gpu3" / "LORA_REGISTRY.json",
       {"loras": [{"file": "lin_wan_qi_v1.safetensors", "sha256": "s1", "status": "accepted"}]})
    _w(r / "config" / "voices.json", {"tts_model": {"id": "kokoro"},
                                      "characters": {"lin_wan": {"sid": 36, "voice": "zf_067", "speed": 0.9}}})
    _quality(r)
    _w(r / "data" / "state_timeline.json", {"shots": [
        {"shot_id": "ep02-S1", "characters": {"lin_wan": {"present": True}}},
        {"shot_id": "ep02-S2", "characters": {"lin_wan": {"present": True}}},
        {"shot_id": "ep02-S3", "characters": {"lin_wan": {"present": False}}}]})
    return r


# ------------------------------------------------------------------ 指纹

def test_rev_stable_and_key_order_independent(root):
    a = AR.current_rev("preset:leica_sstar", root)
    assert a and a == AR.current_rev("preset:leica_sstar", root)
    pr = [dict(reversed(list(p.items()))) for p in PRESETS]          # 同内容、键顺序不同
    pr[0]["params"] = {"steps": 8, "unet": "turbo"}
    _quality(root, presets=pr + [{"id": "zz", "params": {}}])        # 文件长度也变了（避免 mtime 缓存同键）
    assert AR.current_rev("preset:leica_sstar", root) == a


def test_all_keys_cover_types(root):
    keys = AR.all_keys(root)
    for k in ("identity:lin_wan", "loraslot:lin_wan:image", "voice:lin_wan", "preset:leica_sstar",
              "vbase:official_base", "vlora:VBVR.safetensors"):
        assert k in keys, k
    assert "identity:gu_chen" not in keys          # 没有母版 / 参考 → 不列


# ------------------------------------------------------------------ 盖章

def test_stamp_image_pydantic_and_dict(root):
    t = Take(**_take())
    AR.stamp("ep02-S1", t, root)
    assert set(t.deps) == {"identity:lin_wan", "loraslot:lin_wan:image"}
    d = _take(params={"preset": "leica_sstar"})
    AR.stamp("ep02-S3", d, root)                   # 林晚不在画 → 只有预设
    assert set(d["deps"]) == {"preset:leica_sstar"}


def test_stamp_video_and_inherit_does_not_override(root):
    v = _take("video", params={"base": "official_base", "model": {"extra_loras": [["VBVR.safetensors", 0.7]]}})
    AR.stamp("ep02-S1", v, root)
    assert set(v["deps"]) == {"vbase:official_base", "vlora:VBVR.safetensors"}
    inherited = _take(deps={"identity:lin_wan": "old000000000"})
    AR.stamp("ep02-S1", inherited, root)
    assert inherited["deps"]["identity:lin_wan"] == "old000000000"   # 派生版本继承父版本，不被当前覆盖


def test_pipeline_stamp_versions_adds_deps(root, monkeypatch):
    monkeypatch.setattr(P, "ROOT", root)
    t = P.stamp_versions("ep02-S1", Take(**_take()))
    assert t.deps and "identity:lin_wan" in t.deps


def test_image_params_stamp_preset(root, monkeypatch):
    from ns_render import image_params as IP
    monkeypatch.setattr(P, "ROOT", root)
    t = _take(deps={"identity:lin_wan": "x", "preset:old": "y"})
    IP._stamp_preset(t, "leica_sstar")
    assert t["deps"] == {"identity:lin_wan": "x", "preset:leica_sstar": AR.preset_rev(root, "leica_sstar")}


# ------------------------------------------------------------------ 依赖已更新 / 回滚

def test_identity_change_flags_and_rollback_clears(root):
    t = _take()
    AR.stamp("ep02-S1", t, root)
    assert AR.stale_deps(t, root) == []
    m = root / "assets" / "characters" / "lin_wan" / "plates" / "master.png"
    m.write_text("master-v2-new", encoding="utf-8")
    s = AR.stale_deps(t, root)
    assert [x["key"] for x in s] == ["identity:lin_wan"]
    assert s[0]["text"].startswith(AR.DEP_PREFIX) and "林晚" in s[0]["text"]
    m.write_text("master-v1", encoding="utf-8")                      # 回到旧内容 → rev 相同 → 自动恢复
    assert AR.stale_deps(t, root) == []


def test_face_reference_image_and_lora_pointer(root):
    t = _take()
    AR.stamp("ep02-S1", t, root)
    (root / "assets" / "characters" / "lin_wan" / "lin_wan.png").write_text("face-v2!!", encoding="utf-8")
    assert [x["key"] for x in AR.stale_deps(t, root)] == ["identity:lin_wan"]
    _w(root / "config" / "auto_lora_triggers.json",
       {"characters": {"林晚": [{"trigger": "lnwan_qi", "kind": "image", "file": "lin_wan_qi_v2_s1500.safetensors",
                                "strength": 0.8}]}})
    assert "loraslot:lin_wan:image" in {x["key"] for x in AR.stale_deps(t, root)}


def test_preset_content_vs_default_pointer(root):
    t = _take(params={"preset": "leica_sstar"})
    AR.stamp("ep02-S3", t, root)
    _quality(root, default_preset="preview_turbo")                    # 只换默认：本版用的预设没变
    assert AR.stale_deps(t, root) == []
    pr = json.loads(json.dumps(PRESETS))
    pr[0]["params"]["steps"] = 12
    _quality(root, presets=pr, default_preset="preview_turbo")
    s = AR.stale_deps(t, root)
    assert [x["key"] for x in s] == ["preset:leica_sstar"] and "徕卡 S★" in s[0]["text"]


def test_vbase_recipe_vs_label_vs_default(root):
    v = _take("video", params={"base": "official_base"})
    AR.stamp("ep02-S1", v, root)
    b = json.loads(json.dumps(BASES))
    b[0]["label"] = "官方基模（改了名字）"
    b[0]["note"] = "说明改了"
    _quality(root, bases=b, default_base="official_turbo")            # 说明字段 + 默认指针 → 不算
    assert AR.stale_deps(v, root) == []
    b[0]["steps"] = 30
    _quality(root, bases=b)
    assert [x["key"] for x in AR.stale_deps(v, root)] == ["vbase:official_base"]


def test_vbase_drift_for_old_unstamped_video(root):
    old = _take("video", params={"base": "official_base", "base_params": {
        "id": "official_base", "lora": None, "cfg": 4.0, "guider": "CFGGuider", "sha256": None, "steps": 99}})
    assert AR.vbase_drift(old, root) is None                          # steps 是请求值，不比
    b = json.loads(json.dumps(BASES))
    b[0]["cfg"] = 5.0
    _quality(root, bases=b)
    d = AR.vbase_drift(old, root)
    assert d and d["fields"] == ["cfg"]
    assert AR.vbase_drift({**old, "deps": {"vbase:official_base": "x"}}, root) is None   # 盖过章的走 deps


def test_unstamped_take_has_no_dep_stale(root):
    (root / "assets" / "characters" / "lin_wan" / "plates" / "master.png").write_text("changed!!", encoding="utf-8")
    assert AR.stale_deps(_take(), root) == []


def test_inputs_dep_g1_independent_of_prompt():
    t = _take(inputs_sha="aaaa1111")
    assert AR.inputs_dep(t, "aaaa1111") is None
    assert AR.inputs_dep(t, None) is None
    assert AR.inputs_dep(_take(), "bbbb") is None
    d = AR.inputs_dep(t, "bbbb2222")
    assert d and d["key"] == AR.INPUTS_KEY and d["text"].startswith(AR.DEP_PREFIX)


def test_app_dep_stale_g1_and_no_duplicate(root, monkeypatch):
    """G1：提示词没变、inputs_sha 变了 → “依赖已更新”；已报「本镜输入已改」的不重复；不并入 stale"""
    import ns_agent.state_timeline as ST
    from ns_api import app as A
    monkeypatch.setattr(P, "ROOT", root)
    monkeypatch.setattr(ST, "shot_inputs_sha", lambda sid, r=None: "new00000")
    t = _take(inputs_sha="old00000")
    assert [x["key"] for x in A._dep_stale("ep02-S1", t, [])] == [AR.INPUTS_KEY]
    assert A._dep_stale("ep02-S1", t, ["本镜输入已改"]) == []
    assert A._dep_stale("ep02-S1", _take("video", inputs_sha="old00000"), []) == []   # 视频不按 inputs 判


# ------------------------------------------------------------------ 账本

def test_observe_baseline_observed_and_rollback_seq(root):
    first = AR.observe(root)
    assert {r["by"] for r in first} == {"baseline"} and all(r["seq"] == 1 for r in first)
    assert AR.observe(root) == []                                      # 没变化不重复记
    m = root / "assets" / "characters" / "lin_wan" / "plates" / "master.png"
    m.write_text("master-v2-new", encoding="utf-8")
    new = AR.observe(root)
    assert [(r["key"], r["by"], r["seq"]) for r in new] == [("identity:lin_wan", "observed", 2)]
    t = {"deps": {"identity:lin_wan": first[[r["key"] for r in first].index("identity:lin_wan")]["rev"]}}
    assert AR.stale_deps(t, root)[0]["text"].endswith("v1→v2")
    m.write_text("master-v1", encoding="utf-8")
    back = AR.observe(root)
    assert back[0]["seq"] == 1 and back[0]["rollback"] is True


# ------------------------------------------------------------------ 接口

@pytest.fixture
def client(root, monkeypatch):
    from ns_api import revisions as RV
    monkeypatch.setattr(P, "ROOT", root)
    monkeypatch.setattr(P, "RENDERS", root / "data" / "renders")
    monkeypatch.setattr(RV, "_per_job_s", lambda: {"frame": 60.0, "video": 600.0})
    monkeypatch.setattr(RV, "_lane_count", lambda: 2)
    # S1：首帧已定稿（项目方）且盖过章；S2：首帧未盖章（旧版本，按在画人物推断）；S3：林晚不在画
    t1 = _take()
    AR.stamp("ep02-S1", t1, root)
    v1 = _take("video", params={"base": "official_base"})
    AR.stamp("ep02-S1", v1, root)
    _w(root / "data" / "renders" / "ep02" / "S1" / "takes.json",
       {"takes": [t1, v1], "active": {"image": 1, "video": 1}, "locked": {"image": 1}})
    _w(root / "data" / "renders" / "ep02" / "S2" / "takes.json",
       {"takes": [_take()], "active": {"image": 1}, "locked": {}})
    _w(root / "data" / "renders" / "ep02" / "S3" / "takes.json",
       {"takes": [_take()], "active": {"image": 1}, "locked": {}})
    app = FastAPI()
    app.include_router(RV.router)
    return TestClient(app)


def test_impact_counts_locked_separately(client, root):
    r = client.post("/api/revisions/impact", json={"changes": [{"key": "identity:lin_wan"}]}).json()
    cells = {(c["shot_id"], c["stage"]): c for c in r["cells"]}
    assert set(cells) == {("ep02-S1", "image"), ("ep02-S2", "image")}
    assert cells[("ep02-S1", "image")]["estimated"] is False and cells[("ep02-S1", "image")]["locked"] is True
    assert cells[("ep02-S1", "image")]["default_selected"] is False
    assert cells[("ep02-S1", "image")]["chain"] == ["last", "video"]
    assert cells[("ep02-S2", "image")]["estimated"] is True and cells[("ep02-S2", "image")]["default_selected"]
    assert r["counts"] == {"cells": 2, "shots": 2, "locked": 1, "owner_locked": 1, "unlocked": 1, "estimated": 1}
    g = r["gpu_estimate_s"]
    assert g["all"] == {"jobs": 2, "serial": 120.0, "parallel": 60.0}
    assert g["default_selected"]["jobs"] == 1
    assert r["requires_owner"] is True
    assert not (root / "data" / "assets" / "revisions.jsonl").exists()   # 影响面只读


def test_impact_to_rev_already_current_and_video_key(client, root):
    cur = AR.current_rev("identity:lin_wan", root)
    r = client.post("/api/revisions/impact", json={"changes": [{"key": "identity:lin_wan", "to_rev": cur}]}).json()
    assert [c["shot_id"] for c in r["cells"]] == ["ep02-S2"]            # S1 已是目标版本
    r = client.post("/api/revisions/impact", json={"changes": [{"key": "vbase:official_base"}]}).json()
    assert [(c["shot_id"], c["stage"]) for c in r["cells"]] == [("ep02-S1", "video")]
    assert client.post("/api/revisions/impact", json={"changes": []}).status_code == 422


def test_keys_and_key_detail_and_shot_deps(client, root):
    ks = client.get("/api/revisions/keys").json()["keys"]
    row = next(k for k in ks if k["key"] == "identity:lin_wan")
    assert row["current"]["seq"] == 1 and row["used_by_current"] == 1
    assert client.get("/api/revisions/keys?type=preset").json()["keys"][0]["type"] == "preset"
    (root / "assets" / "characters" / "lin_wan" / "plates" / "master.png").write_text("master-v2-new", encoding="utf-8")
    d = client.get("/api/revisions/identity:lin_wan").json()
    assert d["unregistered"] is True and d["used_by"]
    client.get("/api/revisions/keys")                                     # 观察到新版本 → v2
    d = client.get("/api/revisions/identity:lin_wan").json()
    assert [v["seq"] for v in d["versions"]] == [1, 2] and d["versions"][1]["state"] == "current"
    sd = client.get("/api/shots/ep02-S1/deps").json()["stages"]
    img = sd["image"][0]
    assert img["locked"] and img["stamped"]
    assert [x["text"] for x in img["stale_deps"]] == ["依赖已更新：林晚 定妆 / 身份参考 v1→v2"]
    assert client.get("/api/shots/..-x/deps").status_code == 404
    assert client.get("/api/revisions/nope:x").status_code == 404


def test_cache_sees_same_length_rewrite_with_identical_mtime(root):
    """回归：同一时钟刻度内重写同长度文件（mtime_ns + size 都不变）也必须读到新内容"""
    import os
    q = root / "config" / "render_quality.json"
    before = AR.current_rev("vbase:official_base", root)
    st = q.stat()
    q.write_text(q.read_text(encoding="utf-8").replace('"cfg": 4.0', '"cfg": 5.0'), encoding="utf-8")
    os.utime(q, ns=(st.st_atime_ns, st.st_mtime_ns))                  # 人为做成 mtime 完全相同
    assert q.stat().st_size == st.st_size and q.stat().st_mtime_ns == st.st_mtime_ns
    assert AR.current_rev("vbase:official_base", root) != before
    m = root / "assets" / "characters" / "lin_wan" / "plates" / "master.png"
    before = AR.current_rev("identity:lin_wan", root)
    st = m.stat()
    m.write_text("master-v9", encoding="utf-8")                        # 与 master-v1 同长度
    os.utime(m, ns=(st.st_atime_ns, st.st_mtime_ns))
    assert AR.current_rev("identity:lin_wan", root) != before
