"""VOICE10：series10 角色音色候选。候选只来自 data/assets/voices/<cid>_cand/（过检的才列）；A = 现在配置的音色念同样两句、
带时长；没挑之前状态是“待你挑”；用 B 要登录的项目方，只改这一个人物、改前备份、可撤销；不是 series10 的人物 / 没过检的候选拒绝。"""
import json
import wave

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _wav(p, seconds=2.0, sr=24000):
    p.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(b"\0\0" * int(seconds * sr))


def _cand(root, cid, name, ok=True):
    d = root / "data" / "assets" / "voices" / f"{cid}_cand" / name
    _wav(d / "ref.wav", 9.0)
    _wav(d / "sample.wav", 3.2)
    (d / "meta.json").write_text(json.dumps({
        "cid": cid, "cand": name, "ref_text": "参考。", "sample_text": "第一句。第二句。",
        "design": {"instruct": "female, 22 years old, x", "seed": 1},
        "checks": {"pass": ok, "ref_f0_hz": 240.0, "items": {"cer": {"value": 0.0, "asr": "第一句第二句", "pass": ok}}}},
        ensure_ascii=False), encoding="utf-8")


@pytest.fixture
def env(tmp_path, monkeypatch):
    from ns_api import voice_preview as V
    tts = V._post()
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "voices.json").write_text(json.dumps({"characters": {
        "lin_wan": {"name": "林晚", "gender": "female", "sid": 36, "voice": "zf_067", "speed": 1.0, "vo_speed": 1.0},
        "gu_chen": {"name": "顾沉", "gender": "male", "sid": 68, "voice": "zm_029", "speed": 1.0, "vo_speed": 0.95,
                    "speed_owner_decision": "原话：改成正常节奏"},
        "piercer": {"name": "穿孔师", "gender": "female", "sid": 22, "voice": "zf_036", "speed": 1.0}}},
        ensure_ascii=False), encoding="utf-8")
    run = tmp_path / "data" / "pipeline" / "runs" / "series10_v1"
    (run / "ep01").mkdir(parents=True)
    (run / "P1_storyline.json").write_text(json.dumps({"characters": [
        {"name": "林晚", "char_id": "lin_wan", "gender": "女", "age": 22, "voice_phrase": "a mid-high sweet breathy voice"},
        {"name": "阿岚", "char_id": "ch_a_lan", "gender": "女", "age": 26, "voice_phrase": "a low husky alto voice"},
        {"name": "路人", "char_id": "extra", "gender": "男", "age": 30}]}, ensure_ascii=False), encoding="utf-8")
    (run / "ep01" / "P3_ep01_screenplay.json").write_text(json.dumps({"episode": 1, "scenes": [{"no": 1, "lines": [
        {"kind": "dialogue", "speaker": "林晚", "text": "第一句。"}, {"kind": "dialogue", "speaker": "阿岚", "text": "好了。"},
        {"kind": "action", "speaker": None, "text": "路人走过"}]}]}, ensure_ascii=False), encoding="utf-8")
    _cand(tmp_path, "lin_wan", "c1")
    _cand(tmp_path, "lin_wan", "c2", ok=False)
    _cand(tmp_path, "lin_wan", "c3")
    _cand(tmp_path, "ch_a_lan", "c1")
    monkeypatch.setattr(V, "REPO", tmp_path)
    monkeypatch.setattr(V, "_s10_run", lambda: run)
    monkeypatch.setattr(tts, "KokoroBackend", lambda cfg, **kw: tts.FakeTts())
    monkeypatch.setattr(tts, "load_voice_config", lambda *a, **k: {})
    orig = tts.synthesize_cached
    monkeypatch.setattr(tts, "synthesize_cached", lambda b, req: orig(b, req, cache_dir=tmp_path / "data" / "cache" / "tts"))
    app = FastAPI()
    app.include_router(V.router)
    return TestClient(app), tmp_path


def test_list_only_s10_cands_and_current_plays(env):
    c, _ = env
    rows = {r["cid"]: r for r in c.get("/api/voices/s10").json()["characters"]}
    assert set(rows) == {"lin_wan", "ch_a_lan"}                      # 没台词的路人、旧剧本的穿孔师都不在
    lw = rows["lin_wan"]
    assert [k["cand"] for k in lw["candidates"]] == ["c1", "c3"]     # 没过检的 c2 不列
    assert lw["status"] == "待你挑" and rows["ch_a_lan"]["status"] == "待你挑"
    cur = lw["current"]
    assert cur["kind"] == "kokoro" and cur["text"] == "第一句。第二句。" and cur["url"].startswith("/files/cache/tts/")
    assert cur["seconds"] and cur["seconds"] > 0
    assert rows["ch_a_lan"]["current"]["kind"] == "none"


def test_pick_owner_only_writes_one_char_and_undo(env):
    c, tmp = env
    p = tmp / "config" / "voices.json"
    assert c.post("/api/voices/lin_wan/pick", json={"cand": "c1"}).status_code == 403
    assert c.post("/api/voices/lin_wan/pick", json={"cand": "c2", "by": "owner"}).status_code == 404   # 没过检
    assert c.post("/api/voices/piercer/pick", json={"cand": "c1", "by": "owner"}).status_code == 404   # 不是 series10
    r = c.post("/api/voices/lin_wan/pick", json={"cand": "c3", "by": "owner"})
    assert r.status_code == 200, r.text
    cfg = json.loads(p.read_text(encoding="utf-8"))
    lw = cfg["characters"]["lin_wan"]
    assert lw["engine"] == "cosyvoice3_zs" and lw["voice"] == "lin_wan_cand/c3" and "sid" not in lw
    assert lw["ref_wav"] == "data/assets/voices/lin_wan_cand/c3/ref.wav" and len(lw["ref_sha256"]) == 64
    assert lw["speed"] == 1.0 and "vo_speed" not in lw          # 旧 Kokoro 语速没有项目方语速决定 → 不沿用
    assert lw["owner_selections"][-1]["from"]["voice"] == "zf_067" and lw["series"] == "series10_v1"
    assert lw["owner_decision"]["by"] == "owner" and not lw["owner_decision"].get("auto")
    assert cfg["characters"]["piercer"]["voice"] == "zf_036"                                          # 别的条目不动
    assert list((tmp / "data" / "assets" / "voice_backups").glob("voices_*.json"))
    row = next(x for x in c.get("/api/voices/s10").json()["characters"] if x["cid"] == "lin_wan")
    assert row["status"] == "已选" and row["current"]["cand"] == "c3" and row["current"]["seconds"] == 3.2
    assert c.post(f"/api/voices/pick-undo/{r.json()['undo_id']}", json={}).status_code == 403
    assert c.post(f"/api/voices/pick-undo/{r.json()['undo_id']}", json={"by": "owner"}).status_code == 200
    lw = json.loads(p.read_text(encoding="utf-8"))["characters"]["lin_wan"]
    assert lw["voice"] == "zf_067" and lw["sid"] == 36


def test_pick_adds_new_s10_char_and_undo_removes(env):
    c, tmp = env
    r = c.post("/api/voices/ch_a_lan/pick", json={"cand": "c1", "by": "owner"})
    assert r.status_code == 200
    ch = json.loads((tmp / "config" / "voices.json").read_text(encoding="utf-8"))["characters"]["ch_a_lan"]
    assert ch["name"] == "阿岚" and ch["gender"] == "female" and ch["voice"] == "ch_a_lan_cand/c1"
    c.post(f"/api/voices/pick-undo/{r.json()['undo_id']}", json={"by": "owner"})
    assert "ch_a_lan" not in json.loads((tmp / "config" / "voices.json").read_text(encoding="utf-8"))["characters"]


def test_auto_pick_shows_auto_status_and_owner_can_switch(env):
    from ns_api import voice_preview as V
    c, tmp = env
    V.apply_pick("lin_wan", "c1", note="按自动检查自动选", decision={"by": "owner", "auto": True, "quote": V.OWNER_AUTO_QUOTE, "reason": "x"})
    row = next(x for x in c.get("/api/voices/s10").json()["characters"] if x["cid"] == "lin_wan")
    assert row["status"] == "自动选" and row["decision"]["quote"] == V.OWNER_AUTO_QUOTE
    assert [k["cand"] for k in row["candidates"]] == ["c1", "c3"]                                     # 其余候选还在
    assert c.post("/api/voices/lin_wan/pick", json={"cand": "c3", "by": "owner"}).status_code == 200
    row = next(x for x in c.get("/api/voices/s10").json()["characters"] if x["cid"] == "lin_wan")
    assert row["status"] == "已选" and row["current"]["cand"] == "c3"


def test_owner_speed_decision_is_carried_over(env):
    from ns_api import voice_preview as V
    c, tmp = env
    _cand(tmp, "gu_chen", "c1")
    run = V._s10_run()
    p1 = json.loads((run / "P1_storyline.json").read_text(encoding="utf-8"))
    p1["characters"].append({"name": "顾沉", "char_id": "gu_chen", "gender": "男", "age": 34})
    (run / "P1_storyline.json").write_text(json.dumps(p1, ensure_ascii=False), encoding="utf-8")
    p3 = run / "ep01" / "P3_ep01_screenplay.json"
    d = json.loads(p3.read_text(encoding="utf-8"))
    d["scenes"][0]["lines"].append({"kind": "dialogue", "speaker": "顾沉", "text": "别洗。"})
    p3.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    assert c.post("/api/voices/gu_chen/pick", json={"cand": "c1", "by": "owner"}).status_code == 200
    g = json.loads((tmp / "config" / "voices.json").read_text(encoding="utf-8"))["characters"]["gu_chen"]
    assert g["vo_speed"] == 0.95 and g["speed_owner_decision"]


def test_cer_canonicalises_numerals():
    """ASR 把“九 / 百分之十二 / 两个”写成“9 / 12% / 2个”不算错字（VOICE10：林晚候选 CER 0.182 全是这个）"""
    from ns_post.tts import _int_zh, canon_numerals, char_error_rate
    assert [_int_zh(n) for n in (10, 12, 105, 1010, 20005, 123456)] == ["十", "十二", "一百零五", "一千零一十", "二万零五", "十二万三千四百五十六"]
    assert canon_numerals("下降12%，3.5倍") == "下降百分之十二，三点五倍"
    ref = "九个点，一条线。第三季度渠道成本下降百分之十二。两个人。"
    assert char_error_rate(ref, "9个点一条线，第三季度渠道成本下降12%。2个人") == 0.0
    assert char_error_rate("坐稳，别绷着。", "坐文，别绷扯。") > 0       # 真错字照样算
