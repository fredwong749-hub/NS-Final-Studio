"""BGM 链接（BGM10 2026-11-01，docs/BGM.md）：brief 校验、时间轴解析、候选闸门、合成格式、配置不变量、界面只给通过的候选。
不调 LLM、不连 GPU。"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools" / "bgm"))
sys.path.insert(0, str(ROOT / "services" / "post"))

import agent as A  # noqa: E402
import bgm_timeline as T  # noqa: E402
import deliver as D  # noqa: E402
from brief_schema import check_brief, lyrics_tags  # noqa: E402

EX = json.loads((ROOT / "config" / "prompts" / "bgm_brief.example.json").read_text(encoding="utf-8"))
CFG = json.loads((ROOT / "config" / "bgm.json").read_text(encoding="utf-8"))

P4 = """## ep07《占位》
**配乐**：占位；【BGM】Sparse piano at 60 BPM.
**镜1｜img**：x
**时长**：4秒
**sound**：x；【配乐】进入，强度1，独白避让；【H3 audio】x
**🎙（林晚，OS）**：一句。
**镜2｜img**：x
**时长**：8秒
**sound**：x；【配乐】延续，强度1，无需避让
**镜3｜img**：x
**时长**：6.5秒
**对白**：（顾沉，低）“一句。”
"""


def rules(iss):
    return sorted({i["rule"] for i in iss})


def test_example_brief_passes():
    assert check_brief(EX) == []


def test_timeline_parse():
    tl = T.parse_p4(P4)
    assert tl["episode"] == 7 and tl["duration_s"] == 18.5 and [s["start_s"] for s in tl["shots"]] == [0, 4, 12]
    assert [s["voice"] for s in tl["shots"]] == [True, False, True]
    assert tl["shots"][0]["music_cue"].startswith("进入") and tl["bgm_en"] == "Sparse piano at 60 BPM."
    assert T.voiced_spans(tl) == [(0.0, 4.0), (12.0, 18.5)]


@pytest.mark.parametrize("mut,rule", [
    (lambda b: b.update(schema="x"), "BGM-B01"),
    (lambda b: b["bpm"].update(min=100), "BGM-B03"),
    (lambda b: b["sections"][0].update(name="chorus"), "BGM-B05"),
    (lambda b: b.update(energy_curve=[[0, 0.1], [5, 2]]), "BGM-B06"),
    (lambda b: b["duck"][0].update(depth_db=3), "BGM-B07"),
    (lambda b: b.update(instrumentation=["piano", "female vocals"]), "BGM-B08"),
    (lambda b: b.update(style_words=["cinematic", "in the style of Hans Zimmer"]), "BGM-B09"),
    (lambda b: b.update(caption_en="短"), "BGM-B10"),
    (lambda b: b.update(negative=["choir", "drums"]), "BGM-B11"),
    (lambda b: b.update(cue_change={"has": True, "at_s": 33, "why": "x"}), "BGM-B12"),
    (lambda b: b.update(per_shot=[1]), "BGM-B14"),
])
def test_brief_rules_fire(mut, rule):
    b = copy.deepcopy(EX)
    mut(b)
    assert rule in rules(check_brief(b))


def test_brief_named_work_rejected_in_caption():
    b = copy.deepcopy(EX)
    b["caption_en"] = "A slow piano underscore that sounds like Interstellar with soft strings and a low warm pad."
    assert "BGM-B09" in rules(check_brief(b))


def test_brief_lowercase_by_is_not_a_named_work():
    """ep09 实跑（11-01）：“led by solo double bass” 被误判具名，写作模型 3 轮改不掉"""
    b = copy.deepcopy(EX)
    b["caption_en"] = ("A sparse minimal cinematic underscore led by solo double bass pizzicato and single piano notes, "
                       "featuring a soft brushed pulse in the middle.")
    assert "BGM-B09" not in rules(check_brief(b))
    b["caption_en"] = "A slow piano underscore by Someone Famous, with strings and a warm pad that rises gently overall."
    assert "BGM-B09" in rules(check_brief(b))


def test_brief_duck_must_cover_voiced_shots():
    tl = T.parse_p4(P4)
    b = copy.deepcopy(EX)
    b.update(episode=7, duration_s=18.5, energy_curve=[[0, .1], [6, .3], [12, .5], [18.5, .2]],
             mood_arc=[{"t0": 0, "t1": 18.5, "mood": "a"}, {"t0": 18.5, "t1": 18.5, "mood": "b"}],
             sections=[{"name": "intro", "t0": 0, "t1": 12}, {"name": "outro", "t0": 12, "t1": 18.5}],
             cue_change={"has": False}, duck=[{"t0": 0, "t1": 4, "depth_db": 12}])
    assert "BGM-B07" in rules(check_brief(b, tl, 7))          # 只盖住了第 1 镜
    b["duck"].append({"t0": 12, "t1": 18.5, "depth_db": 12})
    assert "BGM-B07" not in rules(check_brief(b, tl, 7))


def test_lyrics_tags_instrumental_only():
    s = lyrics_tags(EX)
    assert s.count("[Instrumental]") == len(EX["sections"]) and "[Intro]" in s


M_OK = {"duration_s": 50.0, "lufs_raw": -16, "true_peak_raw": -1, "clip_ratio": 0.0, "longest_gap_s": 0.0, "tempo_bpm": 70,
        "tempo_ok": True, "energy_r": 0.5, "clap": 0.3, "p_vocal": 0.05, "vocal_rel_db": -30.0}


def test_gate_rejects_vocals_silence_short_and_flags_tempo():
    b = dict(EX, duration_s=48)
    assert A.gate(M_OK, b, CFG)[0]
    assert not A.gate(dict(M_OK, vocal_rel_db=-15), b, CFG)[0]
    assert not A.gate(dict(M_OK, vocal_rel_db=-22, p_vocal=0.8), b, CFG)[0]
    assert A.gate(dict(M_OK, vocal_rel_db=-22, p_vocal=0.1), b, CFG)[0]
    assert not A.gate(dict(M_OK, longest_gap_s=4), b, CFG)[0]
    assert not A.gate(dict(M_OK, duration_s=40), b, CFG)[0]
    assert not A.gate({"error": "x"}, b, CFG)[0]
    ok, fails, flags = A.gate(dict(M_OK, tempo_ok=False), b, CFG)
    assert ok and any("tempo_off" in f for f in flags)


def test_candidates_are_instrumental_and_deterministic():
    c1 = A.build_candidates(3, EX, 1, 4, 50.0, {})
    c2 = A.build_candidates(3, EX, 1, 4, 50.0, {})
    assert [c["seed"] for c in c1] == [c["seed"] for c in c2] and len({c["seed"] for c in c1}) == 4
    assert all(c["caption"].endswith("Instrumental only, no vocals.") and len(c["caption"]) <= 512 for c in c1)
    assert all(EX["bpm"]["min"] <= c["bpm"] <= EX["bpm"]["max"] for c in c1)
    assert all("vocals" in c["negative"] for c in c1)


def test_retry_adjust_validates_reviewer_caption():
    tbl = [{"gate_fail": ["vocals（…）"], "flags": []}]
    adj = A.retry_adjust({"retry": {"caption_en": "Sounds like a famous Song by Someone, piano and strings slowly.",
                                    "bpm_target": 66}}, tbl, EX)
    assert "caption_en" not in adj and adj["bpm_target"] == 66 and "voice" in adj["negative_add"]


def test_config_invariants():
    g = CFG["generation"]
    assert 2 not in g["allowed_gpus"] and g["host"] == "gpu33" and g["workdir"].startswith("/root/work/fredw")
    assert g["yield_s"] >= 180 and g["max_rounds"] == 3 and 3 <= g["candidates_round1"] <= 4
    assert all(t["model"].startswith("acestep-") for t in g["tiers"])            # ACE-Step（MIT），本地
    assert g["score_host"] in ("gpu33", "gpu36") and g["score_workdir"].startswith("/root/work/fredw")
    assert A.score_gen(g)["host"] == g["score_host"] and A.score_gen(dict(g, score_host="gpu33")) is None
    assert 10 <= CFG["output"]["duck_dialogue_db"] <= 14 and 10 <= CFG["output"]["duck_vo_db"] <= 14
    assert CFG["output"]["dir"] == "data/music/series10" and CFG["output"]["lufs"] == -16.0


def test_assembly_meta_format(tmp_path):
    tl = T.parse_p4(P4)
    b = dict(EX, episode=7, duration_s=18.5, _timeline=tl,
             sections=[{"name": "intro", "t0": 0, "t1": 5, "note_en": "a"}, {"name": "turn", "t0": 5, "t1": 18.5, "note_en": "b"}],
             cue_change={"has": True, "at_s": 5})
    wav = tmp_path / "ep07.wav"
    wav.write_bytes(b"RIFF")
    c = {"id": "r1_c2", "metrics": {"duration_s": 20.5}, "bpm_param": 70, "model": "m", "seed": 1, "caption": "c"}
    m = D.assembly_meta(7, b, c, CFG, wav)
    assert m["shot_starts"] == [0, 4, 12] and m["duck"] == {"dialogue_db": 12.0, "vo_db": 11.0}
    assert [(x["shot"], x["action"]) for x in m["cues"]] == [(1, "enter"), (2, "continue")]
    assert m["cues"][1]["offset_s"] == 1.0 and "换段" in m["cues"][1]["text"]
    from ns_post.music import resolve_cues, stale_timeline
    assert stale_timeline(m, 3) is None
    cues = resolve_cues([{"index": 1}, {"index": 2}, {"index": 3}], [0.0, 4.0, 12.0], m, {})
    assert [round(x.start_s, 2) for x in cues] == [0.0, 5.0]


def test_assemble_settings_have_music_dir():
    from ns_post.assemble import Settings
    assert Settings().music_dir is None and Settings(music_dir="data/music/series10").music_dir == "data/music/series10"


def test_api_lists_only_passing_candidates(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from fastapi import FastAPI
    import ns_api.bgm_api as B
    d = tmp_path / "data" / "music" / "series10" / "ep01"
    (d / "cands").mkdir(parents=True)
    for cid in ("r1_c1", "r1_c2"):
        (d / "cands" / f"{cid}.flac").write_bytes(b"fLaC")
    st = {"status": "delivered", "chosen": {"id": "r1_c1", "by": "review_llm", "reason": "x"},
          "candidates": [{"id": "r1_c1", "round": 1, "gate_pass": True, "metrics": {"clap": 0.3}},
                         {"id": "r1_c2", "round": 1, "gate_pass": False, "metrics": {}}], "rounds": []}
    (d / "meta.json").write_text(json.dumps(st), encoding="utf-8")
    monkeypatch.setattr(B, "REPO", tmp_path)
    app = FastAPI()
    app.include_router(B.router)
    r = TestClient(app).get("/api/music/1/candidates").json()
    assert [c["id"] for c in r["candidates"]] == ["r1_c1"] and r["hidden_failed"] == 1 and r["candidates"][0]["chosen"]
    assert r["candidates"][0]["url"].startswith("/files/music/series10/ep01/cands/r1_c1.flac?v=")


# ---- 换用接口的身份（UIAUDIT P0，docs/uiaudit/verify_bgm10_r1.md）：没登录 401、查看者 403、项目方 200 且审计记真名；撤销同规则
def _choose_client(tmp_path, monkeypatch, user):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import types
    import ns_api.auth as AU
    import ns_api.bgm_api as B
    d = tmp_path / "data" / "music" / "series10" / "ep01"
    (d / "cands").mkdir(parents=True)
    for cid in ("r1_c1", "r1_c2"):
        (d / "cands" / f"{cid}.flac").write_bytes(b"fLaC")
    st = {"status": "delivered", "chosen": {"id": "r1_c2", "by": "review_llm", "reason": "x", "previous": "r1_c1"},
          "candidates": [{"id": "r1_c1", "round": 1, "gate_pass": True, "metrics": {}},
                         {"id": "r1_c2", "round": 1, "gate_pass": True, "metrics": {}}], "rounds": []}
    (d / "meta.json").write_text(json.dumps(st), encoding="utf-8")
    monkeypatch.setattr(B, "REPO", tmp_path)
    monkeypatch.setattr(AU, "user_of", lambda request: user)
    audits, calls = [], []
    monkeypatch.setattr(AU, "audit_line", lambda rec: audits.append(rec))

    def fake_choose(ep, cid, *, by, reason):
        calls.append((ep, cid, by, reason))
        s = json.loads((d / "meta.json").read_text(encoding="utf-8"))
        s["chosen"] = {"id": cid, "by": by, "reason": reason, "previous": s["chosen"]["id"]}
        (d / "meta.json").write_text(json.dumps(s), encoding="utf-8")
        return s
    monkeypatch.setattr(B, "_deliver", lambda: types.SimpleNamespace(choose=fake_choose))
    app = FastAPI()
    app.include_router(B.router)
    return TestClient(app), audits, calls


@pytest.mark.parametrize("user,code", [(None, 401), ({"name": "查看者（截图检查）", "role": "viewer"}, 403),
                                       ({"name": "x", "role": "agent"}, 403)])
@pytest.mark.parametrize("body", [{"id": "r1_c1"}, {"undo": True}])
def test_choose_rejects_anonymous_and_viewer(tmp_path, monkeypatch, user, code, body):
    c, audits, calls = _choose_client(tmp_path, monkeypatch, user)
    r = c.post("/api/music/1/choose", json=body)
    assert r.status_code == code and calls == [] and audits == []


def test_choose_owner_writes_audit_with_real_user(tmp_path, monkeypatch):
    c, audits, calls = _choose_client(tmp_path, monkeypatch, {"name": "fred", "role": "owner"})
    r = c.post("/api/music/1/choose", json={"id": "r1_c1"})
    assert r.status_code == 200 and r.json()["chosen"]["id"] == "r1_c1"
    assert calls[0][1] == "r1_c1" and "fred" in calls[0][2] and "owner" in calls[0][2]
    assert audits == [{"user": "fred", "role": "owner", "action": "bgm_choose", "episode": 1, "candidate": "r1_c1",
                       "previous": "r1_c2", "undo": False}]


def test_choose_owner_undo(tmp_path, monkeypatch):
    c, audits, calls = _choose_client(tmp_path, monkeypatch, {"name": "fred", "role": "owner"})
    r = c.post("/api/music/1/choose", json={"undo": True})     # previous = r1_c1
    assert r.status_code == 200 and calls[0][1] == "r1_c1" and "撤销" in calls[0][3]
    assert audits[0]["undo"] is True and audits[0]["user"] == "fred"


# ---- 给项目方看的人话（UIAUDIT P2 v2）：源头生成，不靠前端正则
def test_plain_flags_and_dangling_checker():
    import plain as PL
    assert PL.flag_plain("tempo_off（实测 21.0，brief 56–70）").startswith("测出来的速度")
    assert PL.flag_plain("energy_weak（r=-0.07）") == "强弱起伏和说明里的走向贴得不紧"
    assert PL.fail_plain("silence_gap（3.2 s）") == "中间有较长的空白段"
    for bad in ("听感贴合度与最高值 相当。", "r1_c2 的 是 60 的 倍。", "最长空白 ，", "选它因为 energy_r 高。", "相似度 0.36 最高。"):
        assert PL.check_text(bad), bad
    for ok in ("其余三条能量走向都是反的。", "速度每分钟约 68 拍，正合适；r1_c2 中段有两秒空档。"):
        assert PL.check_text(ok) == [], ok


def test_deliver_keeps_reason_plain_on_redeliver(tmp_path, monkeypatch):
    st = {"chosen": {"id": "r1_c2", "reason": "x", "reason_plain": "人话", "reason_evidence": "e"},
          "candidates": [{"id": "r1_c2", "gate_pass": True, "metrics": {"duration_s": 1}, "bpm_param": 1, "model": "m",
                          "seed": 1, "caption": "c"}]}
    monkeypatch.setattr(D, "out_dir", lambda cfg=None: tmp_path)
    monkeypatch.setattr(D, "flac_to_wav", lambda a, b: b.write_bytes(b"RIFF"))
    (tmp_path / "ep01").mkdir()
    (tmp_path / "ep01" / "brief.json").write_text(json.dumps(dict(EX, _timeline=T.parse_p4(P4))), encoding="utf-8")
    D.deliver(1, st, CFG, "r1_c2", "x", "review_llm")
    assert st["chosen"]["reason_plain"] == "人话" and st["chosen"]["reason_evidence"] == "e"
    D.deliver(1, st, CFG, "r1_c2", "项目方在声音页换用", "界面：fred（owner）")
    assert st["chosen"]["reason_plain"] == "项目方在声音页换用"
