"""UIRSI B4：对白逐句试听 + 配乐接口（假 TTS，不碰真缓存）。"""
import json
import sys
import wave
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "api"))
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_api import shot_audio as A  # noqa: E402
from ns_post import tts as T  # noqa: E402

SCRIPT = {"episodes": [{"number": 1, "shots": [
    {"index": 1, "dialogue": [], "voiceover": {"speaker": "林晚", "text": "第一天。", "note": "林晚，自语"}},
    {"index": 2, "dialogue": [{"speaker": "顾沉", "speaker_note": "顾沉，低声", "text": "别洗。", "stage": None}],
     "voiceover": None},
]}]}
VOICES = {"tts_model": {"id": "kokoro-multi-lang-v1_1"}, "voiceover_speaker": "narrator",
          "characters": {"lin_wan": {"name": "林晚", "sid": 36}, "gu_chen": {"name": "顾沉", "sid": 68},
                         "narrator": {"name": "旁白", "engine": "cosyvoice3_zs", "ref_sha256": "ab" * 32}}}


def _wav(p: Path, sec=0.5):
    with wave.open(str(p), "wb") as w:
        w.setnchannels(1), w.setsampwidth(2), w.setframerate(24000), w.writeframes(b"\0\0" * int(24000 * sec))


class FakeKokoro:
    name = "kokoro"
    calls = 0

    def __init__(self, *a, **k):
        pass

    def synthesize(self, items):
        FakeKokoro.calls += 1
        for _, _, p in items:
            _wav(p)


@pytest.fixture()
def client(tmp_path, monkeypatch):
    (tmp_path / "import").mkdir()
    (tmp_path / "import" / "script_v2.json").write_text(json.dumps(SCRIPT, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(A, "_script", lambda: SCRIPT)
    monkeypatch.setattr(T, "load_voice_config", lambda *a, **k: VOICES)
    monkeypatch.setattr(T, "CACHE_DIR", tmp_path / "tts")
    monkeypatch.setattr(T, "KokoroBackend", FakeKokoro)
    monkeypatch.setattr(A, "_music_dir", lambda: tmp_path / "music")
    from ns_api import bgm_api  # BGM10 之后图址由 bgm_api.file_url 生成（要求在 data/ 下）；测试目录在临时盘，换成固定写法
    monkeypatch.setattr(bgm_api, "file_url", lambda w: f"/files/music/{Path(w).name}")
    app = FastAPI()
    app.include_router(A.router)
    return TestClient(app), tmp_path


def test_lines_and_play(client):
    c, tmp = client
    r = c.get("/api/shots/ep01-S2/audio").json()
    [ln] = r["lines"]
    assert ln["speaker_name"] == "顾沉" and ln["label"] == "对白" and ln["play"] and not ln["cached"]
    FakeKokoro.calls = 0
    w = c.get(ln["play"])
    assert w.status_code == 200 and w.headers["content-type"] == "audio/wav"
    assert c.get(ln["play"]).status_code == 200 and FakeKokoro.calls == 1  # 第二次走缓存
    assert c.get("/api/shots/ep01-S2/audio").json()["lines"][0]["cached"] is True
    # 旁白（远端音色）没合成过：不给播放地址、给原因，直接请求是 409
    [vo] = c.get("/api/shots/ep01-S1/audio").json()["lines"]
    assert vo["label"] == "旁白" and vo["play"] is None and vo["reason"]
    assert c.get("/api/shots/ep01-S1/audio/0.wav").status_code == 409
    assert c.get("/api/shots/ep01-S9/audio").status_code == 404
    assert c.get("/api/shots/bad/audio").status_code == 404
    e = c.get("/api/sound/lines?ep=1").json()
    assert [len(s["lines"]) for s in e["shots"]] == [1, 1] and e["shots"][1]["lines"][0]["cached"] is True
    assert c.get("/api/sound/lines?ep=7").status_code == 404


def test_music(client):
    c, tmp = client
    assert c.get("/api/music").json() == {"episodes": []}
    d = tmp / "music"
    d.mkdir()
    _wav(d / "ep01.wav")
    (d / "ep01.json").write_text(json.dumps({"duration_s": 10, "shot_starts": [0, 4.5], "shot_durations": [4.5, 5.5],
                                             "cues": [{"shot": 2, "start_s": 4.5, "action": "in", "text": "起"}]}),
                                 encoding="utf-8")
    m = c.get("/api/music/1").json()
    assert m["url"] == "/files/music/ep01.wav" and [s["start_s"] for s in m["shots"]] == [0, 4.5]
    assert m["shots"][1]["shot"] == "ep01-S2" and m["cues"][0]["action"] == "in"
    assert len(c.get("/api/music").json()["episodes"]) == 1
    assert c.get("/api/music/3").status_code == 404
