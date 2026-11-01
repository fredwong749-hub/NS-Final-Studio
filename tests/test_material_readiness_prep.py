"""PREP 出片前资料闸门（ns_api/material_readiness.py）+ 整集出片 / 出片接口的拦截。不碰 GPU、不碰真实 data。"""
from __future__ import annotations

import hashlib
import json

import pytest
from fastapi import HTTPException

from ns_api import episode_produce as EPR
from ns_api import material_readiness as MR
from ns_schema.script import (CastEntry, CharacterEntry, CharacterLock, DialogueLine, Episode, LookLine,
                              SceneEntry, ScriptGlobals, ScriptImport, Shot)
from test_episode_produce_eb import FakeHooks, run_until_idle

H3 = ("How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second "
      "mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.\n\n"
      "integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, a medium shot "
      "begins in the position, framing and lighting established by Picture 1, one woman, AAA EN, BBB OUTFIT. "
      "The woman with VVV voice (S1) says: <d>[Chinese] 你好。</d> She settles into the pose established by "
      "Picture 2 at the end of the shot.\n\noverall_soundscape: Soft hum.\n\nnon_diegetic_music: N/A")


def _shot(full: bool) -> Shot:
    base = dict(episode=99, index=1, img_prompt="中景，林晚坐在桌前", source_line=1,
                motion_prompt="lnwan01，camera push in 缓推，林晚抬眼——中景，林晚坐在桌前抬眼看向镜头",
                sound="空调声；【配乐】进入，强度1，对白避让；【H3 audio】Soft hum.", sound_h3="Soft hum.",
                music_cue="进入，强度1，对白避让", h3_prompt=H3, duration=8, duration_source="script",
                dialogue=[DialogueLine(speaker_note="林晚，轻声", text="你好。", speaker="林晚")])
    if full:
        base.update(scene_id="sk_t", scene_detail="桌前", link="换场", link_carry="林晚坐着",
                    cast=[CastEntry(name="林晚", presence="在画", x="中", depth="中", raw="林晚（在画｜中｜中）")])
    else:
        base.update(duration_source="default", dialogue=[DialogueLine(speaker_note="她慌", text="你好。")])
    return Shot(**base)


def _script(full: bool) -> ScriptImport:
    g = ScriptGlobals(character_locks=[CharacterLock(name="林晚", description="22岁中国成年女性")])
    ep = Episode(number=99, title="t", music="配乐；【BGM】x", music_bgm="x", source_line=1, shots=[_shot(full)])
    if full:
        g.character_registry = [CharacterEntry(name="林晚", char_id="lin_wan", zh="系统锁", en="AAA EN",
                                               voice="VVV voice")]
        g.scene_library = [SceneEntry(scene_id="sk_t", name="书房")]
        ep.cast, ep.scene_ids = ["林晚"], ["sk_t"]
        ep.looks = [LookLine(character="林晚", slots={"服装": "a", "鞋": "b", "妆": "c", "发": "d", "甲": "e",
                                                       "饰品": "f"}, en="BBB OUTFIT")]
    return ScriptImport(sources=[], globals=g, episodes=[ep])


def _root(tmp_path, plate=True, face=True):
    if face:
        p = tmp_path / "assets" / "characters" / "lin_wan" / "lin_wan.png"
        p.parent.mkdir(parents=True)
        p.write_bytes(b"face")
    if plate:
        d = tmp_path / "assets" / "scenes" / "sk_t"
        d.mkdir(parents=True)
        (d / "plate.png").write_bytes(b"plate")
        sha = hashlib.sha256(b"plate").hexdigest()
        (d / "manifest.json").write_text(json.dumps({"plate": "plate.png", "locked": {"by": "canvas", "sha256": sha}}),
                                         encoding="utf-8")
    return tmp_path


def test_old_format_shot_lists_missing(tmp_path):
    r = MR.episode_check(_script(False), 99, root=_root(tmp_path))
    keys = {i["key"] for i in r["shots"][0]["missing"]}
    assert {"cast_line", "link", "scene_line", "char_entry", "char_en", "look", "duration"} <= keys
    assert {i["key"] for i in r["episode_items"]} == {"ep_cast", "ep_scenes"}
    assert r["ready"] == 0 and not r["shots"][0]["ready"]
    assert any(i["key"] == "speaker" for i in r["shots"][0]["conflicts"])     # “她慌”认不出说话人
    assert r["shots"][0]["people_from"] == "按 img 推断"


def test_full_v3_shot_is_ready(tmp_path):
    r = MR.episode_check(_script(True), 99, root=_root(tmp_path))
    s = r["shots"][0]
    assert s["missing"] == [] and s["ready"] and r["ready"] == 1, s
    assert s["conflicts"] == [], s["conflicts"]


def test_assets_missing_block(tmp_path):
    r = MR.episode_check(_script(True), 99, root=_root(tmp_path, plate=False, face=False))
    keys = {i["key"] for i in r["shots"][0]["missing"]}
    assert keys == {"scene_plate", "identity_ref"}


def test_ethnicity_and_anchor(tmp_path):
    sc = _script(True)
    sc.globals.character_locks = [CharacterLock(name="林晚", description="22岁成年女性")]
    sc.globals.character_registry[0].en = "a 22-year-old woman"           # 没写族裔；锚点句也对不上
    s = MR.episode_check(sc, 99, root=_root(tmp_path))["shots"][0]
    assert any(i["key"] == "char_ethnicity" for i in s["missing"])
    assert any(i["key"] == "h3_anchor" for i in s["conflicts"])


def test_h3_alignment_conflicts(tmp_path):
    sc = _script(True)
    sh = sc.episodes[0].shots[0]
    sh.duration = 6
    sh.dialogue[0].text = "您好。"
    s = MR.episode_check(sc, 99, root=_root(tmp_path))["shots"][0]
    why = " ".join(i["reason"] for i in s["conflicts"] if i["key"] == "h3_align")
    assert "6.58" in why and "您好" in why


def test_job_gate_auto_refuses_manual_warns(monkeypatch):
    monkeypatch.setattr(MR, "shot_gate", lambda script, sid, root=None: {"ready": False, "reasons": ["场景行：没有"],
                                                                          "missing_count": 1})
    with pytest.raises(HTTPException) as e:
        MR.job_gate(None, "ep02-S1", "episode_produce")
    assert e.value.status_code == 409 and "资料不全" in e.value.detail
    w = MR.job_gate(None, "ep02-S1", None)
    assert w and "项目方手动出" in w[0]
    monkeypatch.setattr(MR, "shot_gate", lambda script, sid, root=None: {"ready": True, "reasons": [],
                                                                          "missing_count": 0})
    assert MR.job_gate(None, "ep02-S1", "auto") == []


def test_produce_skips_not_ready_shots(tmp_path):
    h = FakeHooks()
    h.not_ready = {"ep09-S2": ["场景行：没有 **场景** 行"]}
    pr = EPR.Producer(hooks=h, root=tmp_path / "episodes")
    pr.ensure_thread = lambda: None
    plan = pr.plan(9, stages=["first", "last", "video"], mode="auto_lock")
    assert [x["shot_id"] for x in plan["not_ready"]] == ["ep09-S2"]
    assert plan["steps"]["first"]["run"] == 2
    pr.start(9, stages=["first", "last", "video"], mode="auto_lock")
    run_until_idle(h, pr)
    assert all(sid != "ep09-S2" for sid, *_ in h.order)
    v = pr.view(9)
    run = pr.load(9)
    rec = run["items"]["ep09-S2"]["first"]
    assert rec["state"] == "blocked" and rec["gate"] == "materials" and "资料不全" in rec["reason"]
    assert v["not_ready"][0]["shot_id"] == "ep09-S2"
    assert run["state"] == "done"


def test_produce_gate_error_fails_closed(tmp_path):
    class Boom(FakeHooks):
        def materials(self, n, shots):
            raise RuntimeError("x")
    h = Boom()
    pr = EPR.Producer(hooks=h, root=tmp_path / "episodes")
    plan = pr.plan(9, stages=["first"], mode="review")
    assert len(plan["not_ready"]) == 3 and plan["jobs"] == 0


def test_checklist_route():
    from fastapi.testclient import TestClient
    from ns_api import app as A
    c = TestClient(A.app)
    r = c.get("/api/readiness/checklist").json()
    assert {"scene_plate", "identity_ref", "look", "char_ethnicity", "h3_anchor"} <= {i["key"] for i in r["items"]}
    assert c.get("/api/episodes/987/readiness").status_code == 404


def test_lane_allow_list(tmp_path):
    assert EPR.lane_allowed({"gpu": 0}, ["gpu33:0"]) and not EPR.lane_allowed({"gpu": 1}, ["gpu33:0", "gpu36:0"])
    assert EPR.lane_allowed({"gpu": "gpu36:2", "id": "gpu36:2"}, ["gpu36:2"]) and EPR.lane_allowed({"gpu": 1}, None)
    h = FakeHooks()
    pr = EPR.Producer(hooks=h, root=tmp_path / "episodes")
    pr.ensure_thread = lambda: None
    pr.start(9, stages=["first"], mode="auto_lock", lanes_only=["gpu33:0", "gpu33:3"])
    run_until_idle(h, pr)
    assert h.order and {g for *_, g in h.order} <= {0, 3}
    assert pr.plan(9, stages=["first"], force=True, lanes_only=["gpu33:3"])["lanes"][0]["gpu"] == 3
