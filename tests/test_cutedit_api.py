"""CUTEDIT 剪辑工程接口：建工程、保存裁切 / 配乐、rev 冲突、镜头重出自动换段且裁切沿用、cut_edit 只带手动裁切、版本列表标定稿。
临时目录合成数据，不碰真数据。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("services/api", "services/render_router", "services/post"):
    sys.path.insert(0, str(ROOT / p))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ns_api import cut_project as CP  # noqa: E402
from ns_api import cuts as CUTS  # noqa: E402
from ns_render import pipeline as P  # noqa: E402


@pytest.fixture()
def env(tmp_path, monkeypatch):
    root = tmp_path / "root"
    data = root / "data"
    fin = data / "renders" / "ep97" / "_final"
    fin.mkdir(parents=True)
    clips = data / "clips"
    clips.mkdir()
    for f in ("s1.mp4", "s2.mp4", "s2_new.mp4"):
        (clips / f).write_bytes(b"x")
    (data / "music" / "series10").mkdir(parents=True)
    (data / "music" / "series10" / "ep97.wav").write_bytes(b"x")
    (data / "music" / "series10" / "ep96.wav").write_bytes(b"x")
    tl = {"duration_s": 10.0, "settings": {"dialogue_source": "h3"},
          "bgm": {"file": "data/music/series10/ep97.wav"},
          "shots": [{"shot": "ep97-S1", "index": 1, "kind": "video", "file": "data/clips/s1.mp4", "source_duration_s": 6.0,
                     "trim_head_s": 0.5, "trim_tail_s": 0.5, "duration_s": 5.0},
                    {"shot": "ep97-S2", "index": 2, "kind": "video", "file": "data/clips/s2.mp4", "source_duration_s": 6.0,
                     "trim_head_s": 0.0, "trim_tail_s": 1.0, "duration_s": 5.0},
                    {"shot": "ep97-S3", "index": 3, "kind": "still", "file": "data/clips/s1.mp4", "duration_s": 4.0,
                     "placeholder": True}],
          "speech": [{"kind": "dialogue", "shot": 1, "speaker_name": "林晚", "text": "嗯。", "start_s": 1.0, "end_s": 2.0,
                      "files": ["data/cache/tts/a.wav"]}]}
    (fin / "ep97_v1.timeline.json").write_text(json.dumps(tl, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(P, "ROOT", root)
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(CP, "current_sources", lambda n: {})
    monkeypatch.setattr(CP, "media_duration", lambda rel: 3.0 if rel.endswith("s2_new.mp4") else 6.0)
    app = FastAPI()
    app.include_router(CP.router)
    app.include_router(CUTS.router)
    return TestClient(app), root, fin


def test_build_and_save_trims_and_bgm(env):
    c, root, fin = env
    j = c.get("/api/episodes/97/cut-project").json()
    assert j["rev"] == 1 and [s["trim_by"] for s in j["segments"]] == ["auto"] * 3
    assert j["segments"][0]["url"] == "/files/clips/s1.mp4" and j["duration_s"] == pytest.approx(14.0)
    assert {m["name"] for m in j["music_choices"]} == {"ep96", "ep97"}
    r = c.put("/api/episodes/97/cut-project", json={"rev": 1, "segments": [{"index": 2, "trim_head_s": 1.0, "trim_tail_s": 9.0}],
                                                   "bgm": {"file": "data/music/series10/ep96.wav", "gain_db": -40, "fade_in_s": 1.5}})
    assert r.status_code == 200
    j = r.json()
    s2 = j["segments"][1]
    assert j["rev"] == 2 and s2["trim_by"] == "owner" and s2["trim_head_s"] == 1.0
    assert 6.0 - s2["trim_head_s"] - s2["trim_tail_s"] == pytest.approx(0.2)      # 夹到至少留 0.2 s
    assert j["bgm"]["file"].endswith("ep96.wav") and j["bgm"]["gain_db"] == -30.0
    assert c.put("/api/episodes/97/cut-project", json={"rev": 1, "segments": []}).status_code == 409
    assert c.put("/api/episodes/97/cut-project", json={"rev": 2, "bgm": {"file": "../x.wav"}}).status_code == 422
    edit = CP.cut_edit_of(json.loads((fin / "cut_project.json").read_text(encoding="utf-8")))
    assert list(edit["trims"]) == ["2"] and edit["bgm"]["fade_in_s"] == 1.5      # 只有动过的镜头带手动入出点


def test_reshot_replaces_segment_and_keeps_trim(env, monkeypatch):
    c, root, fin = env
    c.get("/api/episodes/97/cut-project")
    c.put("/api/episodes/97/cut-project", json={"rev": 1, "segments": [{"index": 2, "trim_head_s": 2.5, "trim_tail_s": 1.0}]})
    monkeypatch.setattr(CP, "current_sources", lambda n: {
        2: {"index": 2, "shot": "ep97-S2", "kind": "video", "file": "data/clips/s2_new.mp4", "chosen": "v2"},
        1: {"index": 1, "shot": "ep97-S1", "kind": "video", "file": "data/clips/s1.mp4", "chosen": "v1"}})
    j = c.get("/api/episodes/97/cut-project").json()
    s1, s2 = j["segments"][0], j["segments"][1]
    assert s1["file"] == "data/clips/s1.mp4" and "replaced_from" not in s1
    assert s2["file"] == "data/clips/s2_new.mp4" and s2["replaced_from"] == "data/clips/s2.mp4"
    assert s2["trim_by"] == "owner" and s2["trim_head_s"] == 2.5 and s2["trim_adjusted"] is True   # 新片 3 s：尾裁收到 0.3
    assert s2["trim_tail_s"] == pytest.approx(0.3) and j["rev"] == 3


def test_export_accepts_immediately_and_reports(env, monkeypatch):
    c, root, fin = env
    c.get("/api/episodes/97/cut-project")

    class FakeProc:
        returncode = None

        def poll(self):
            return None
    monkeypatch.setattr(CP.subprocess, "Popen", lambda *a, **k: FakeProc())
    r = c.post("/api/episodes/97/cut-project/export", json={"by": "owner"})
    assert r.status_code == 202 and r.json()["state"] == "queued" and r.json()["eta_s"] > 0
    assert c.post("/api/episodes/97/cut-project/export", json={}).json()["started_at"] == r.json()["started_at"]   # 不重复起
    assert c.get("/api/episodes/97/cut-project/export").json()["stage"] == "收下"


def test_final_version_tagged_in_cut_list(env):
    c, root, fin = env
    (fin / "ep97_v1.mp4").write_bytes(b"x")
    (fin / "ep97_cut_r2.mp4").write_bytes(b"x")
    (fin / "preview_latest.mp4").write_bytes(b"x")
    c.get("/api/episodes/97/cut-project")
    pj = json.loads((fin / "cut_project.json").read_text(encoding="utf-8"))
    pj["final"] = {"file": "data/renders/ep97/_final/ep97_cut_r2.mp4", "rev": 2}
    (fin / "cut_project.json").write_text(json.dumps(pj), encoding="utf-8")
    cuts = {x["name"]: x for x in c.get("/api/episodes/97/cuts").json()["cuts"]}
    assert set(cuts) == {"ep97_v1.mp4", "ep97_cut_r2.mp4"}
    assert cuts["ep97_cut_r2.mp4"]["tags"][:1] == ["定稿"] and "剪辑" in cuts["ep97_cut_r2.mp4"]["tags"]
    assert "定稿" not in cuts["ep97_v1.mp4"]["tags"]
