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
          "bgm": {"used": True, "file": "data/music/series10/ep97.wav"},
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
    assert r.status_code == 202
    j = r.json()
    s2 = j["segments"][1]
    assert j["rev"] == 2 and s2["trim_by"] == "owner" and s2["trim_head_s"] == 1.0
    assert 6.0 - s2["trim_head_s"] - s2["trim_tail_s"] == pytest.approx(0.2)      # 夹到至少留 0.2 s
    assert j["bgm"]["file"].endswith("ep96.wav") and j["bgm"]["gain_db"] == -30.0
    r = c.put("/api/episodes/97/cut-project", json={"rev": 1, "segments": [{"index": 1, "trim_head_s": 0.25, "trim_tail_s": 0.5}]})
    assert r.status_code == 202 and r.json()["rev"] == 3                     # 旧版本的改动不退回，合并到最新
    assert r.json()["segments"][1]["trim_head_s"] == 1.0 and "合并到第 3 版" in r.json()["history"][-1]["what"]
    assert c.put("/api/episodes/97/cut-project", json={"rev": 2, "bgm": {"file": "../x.wav"}}).status_code == 422
    edit = CP.cut_edit_of(json.loads((fin / "cut_project.json").read_text(encoding="utf-8")))
    assert sorted(edit["trims"]) == ["1", "2"] and edit["bgm"]["fade_in_s"] == 1.5      # 只有动过的镜头带手动入出点


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


def test_order_and_subtitles_saved_and_mapped(env):
    c, root, fin = env
    j = c.get("/api/episodes/97/cut-project").json()
    assert j["subtitles_edited"] is False and j["subtitles"][0]["shot"] == 1 and j["subtitles"][0]["text"] == "嗯。"
    assert j["subtitles"][0]["d0"] == pytest.approx(1.0)       # 基准：S1 从 0 开始，对白 1.0–2.0
    assert c.put("/api/episodes/97/cut-project", json={"rev": 1, "order": [1, 2]}).status_code == 422   # 少镜头
    r = c.put("/api/episodes/97/cut-project", json={"rev": 1, "order": [3, 1, 2],
                                                   "subtitles": [{"shot": 1, "text": " 改过的 ", "d0": 0.5, "d1": 1.8},
                                                                 {"shot": 9, "text": "x", "d0": 0, "d1": 1}]})
    assert r.status_code == 422                                  # 挂在不存在的镜头上
    r = c.put("/api/episodes/97/cut-project", json={"rev": 1, "order": [3, 1, 2],
                                                   "subtitles": [{"shot": 1, "text": " 改过的 ", "d0": 0.5, "d1": 1.8}]})
    j = r.json()
    assert [s["index"] for s in j["segments"]] == [3, 1, 2] and j["segments"][1]["start_s"] == pytest.approx(4.0)
    assert j["subtitles_edited"] and j["subtitles"] == [{"shot": 1, "text": "改过的", "d0": 0.5, "d1": 1.8}]
    pj = json.loads((fin / "cut_project.json").read_text(encoding="utf-8"))
    assert CP.cut_edit_of(pj)["order"] == [3, 1, 2]
    # 导出时间线（新顺序位置 1..3）→ 还原剧本镜号 + 字幕按本镜起点换算
    tl = {"duration_s": 14.0, "shots": [{"index": 1, "shot": "ep97-S1", "start_s": 0.0}, {"index": 2, "shot": "ep97-S2", "start_s": 4.0},
                                        {"index": 3, "shot": "ep97-S3", "start_s": 9.0}],
          "speech": [{"shot": 2, "key": "ep97-S2#d0", "start_s": 5.0, "end_s": 6.0, "text": "嗯。"}]}
    CP.relabel_timeline(tl, {1: 3, 2: 1, 3: 2}, "ep97")
    assert [(s["index"], s["cut_position"], s["shot"]) for s in tl["shots"]] == [(3, 1, "ep97-S3"), (1, 2, "ep97-S1"), (2, 3, "ep97-S2")]
    assert tl["speech"][0]["shot"] == 1 and tl["speech"][0]["key"] == "ep97-S1#d0"
    assert CP.srt_cues(tl, pj) == [(4.5, 5.8, "改过的")]
    pj["subtitles"] = None
    assert CP.srt_cues(tl, pj) == [(5.0, 6.0, "嗯。")]


def test_renumber_for_order():
    ep = {"number": 97, "shots": [{"index": 1, "dialogue": [{"text": "a"}]}, {"index": 2}, {"index": 3}]}
    src = {1: {"path": "a"}, 2: {"path": "b"}, 3: {"path": "c"}}
    e2, s2, ce2, back = CP.renumber_for_order(ep, src, {"trims": {"1": [0.5, 0]}, "order": [3, 1, 2], "bgm": {}})
    assert [s["index"] for s in e2["shots"]] == [1, 2, 3] and e2["shots"][1]["dialogue"] == [{"text": "a"}]
    assert s2 == {1: {"path": "c"}, 2: {"path": "a"}, 3: {"path": "b"}} and ce2["trims"] == {"2": [0.5, 0]} and "order" not in ce2
    assert back == {1: 3, 2: 1, 3: 2} and ep["shots"][0]["index"] == 1          # 原剧集不被改
    same = CP.renumber_for_order(ep, src, {"trims": {}})
    assert same[0] is ep and same[3] == {1: 1, 2: 2, 3: 3}
    with pytest.raises(ValueError):
        CP.renumber_for_order(ep, src, {"order": [1, 2]})


def test_three_way_merge_keeps_other_window_changes(env):
    """OVERSIGHT-F r7：A 改字幕、B 停在旧版本上只改顺序 → 合并后 A 的字幕保留、B 的顺序生效；同一字段两边都改 → 后到为准并记下覆盖了谁"""
    c, root, fin = env
    j = c.get("/api/episodes/97/cut-project").json()
    base = j["rev"]
    a = c.put("/api/episodes/97/cut-project", json={"rev": base, "by": "A", "subtitles": [{"shot": 1, "text": "A 的字幕", "d0": 0.2, "d1": 1.2}],
                                                   "segments": [{"index": 2, "trim_head_s": 1.0, "trim_tail_s": 0.5}]}).json()
    assert a["rev"] == base + 1
    b = c.put("/api/episodes/97/cut-project", json={"rev": base, "by": "B", "order": [2, 1, 3]}).json()   # B 只发了顺序
    assert [s["index"] for s in b["segments"]] == [2, 1, 3]
    assert b["subtitles"] == [{"shot": 1, "text": "A 的字幕", "d0": 0.2, "d1": 1.2}] and b["subtitles_edited"]
    s2 = next(s for s in b["segments"] if s["index"] == 2)
    assert (s2["trim_head_s"], s2["trim_tail_s"], s2["trim_by"]) == (1.0, 0.5, "owner")
    assert "overrode" not in b["history"][-1] and b["history"][-1]["base_rev"] == base
    # 同一字段（字幕）两边都改：后到的为准，history 写清覆盖了第几版谁的改动
    cc = c.put("/api/episodes/97/cut-project", json={"rev": base, "by": "B", "subtitles": [{"shot": 3, "text": "B 的字幕", "d0": 0.1, "d1": 1.0}]}).json()
    assert cc["subtitles"] == [{"shot": 3, "text": "B 的字幕", "d0": 0.1, "d1": 1.0}]
    ov = cc["history"][-1]["overrode"]
    assert len(ov) == 1 and f"第 {base + 1} 版" in ov[0]["text"] and "A" in ov[0]["text"] and ov[0]["field"] == "subtitles"
    assert ov[0]["prev_value"] == [{"shot": 1, "text": "A 的字幕", "d0": 0.2, "d1": 1.2}]      # 被覆盖的完整旧值
    # 配乐只发改了的字段：别的配乐字段不被旧值盖回
    c.put("/api/episodes/97/cut-project", json={"rev": cc["rev"], "by": "A", "bgm": {"fade_in_s": 2.0}})
    d = c.put("/api/episodes/97/cut-project", json={"rev": cc["rev"], "by": "B", "bgm": {"gain_db": -6}}).json()
    assert d["bgm"]["fade_in_s"] == 2.0 and d["bgm"]["gain_db"] == -6.0 and d["bgm"]["file"].endswith("ep97.wav")


def test_renumber_updates_shot_ids():
    ep = {"number": 97, "shots": [{"index": 1, "id": "ep97-S1", "tag": "原 S1"}, {"index": 2, "id": "ep97-S2", "tag": "原 S2"}]}
    e2, _, _, back = CP.renumber_for_order(ep, {}, {"order": [2, 1]})
    assert [(s["index"], s["id"], s["tag"]) for s in e2["shots"]] == [(1, "ep97-S1", "原 S2"), (2, "ep97-S2", "原 S1")]
    assert back == {1: 2, 2: 1}
    assert [s["id"] for s in ep["shots"]] == ["ep97-S1", "ep97-S2"]


def test_restore_brings_back_overridden_subtitles(env):
    """OVERSIGHT-F r9 P1-9b：A 改的字幕被 B 覆盖后，用 restore 找回 A 的原文；恢复记成一次新改动，也能再恢复回去"""
    c, root, fin = env
    base = c.get("/api/episodes/97/cut-project").json()["rev"]
    a_subs = [{"shot": 1, "text": "A 写的第一句", "d0": 0.2, "d1": 1.2}, {"shot": 2, "text": "A 写的第二句", "d0": 0.1, "d1": 2.0}]
    c.put("/api/episodes/97/cut-project", json={"rev": base, "by": "A", "client": "tabA", "subtitles": a_subs})
    b = c.put("/api/episodes/97/cut-project", json={"rev": base, "by": "B", "client": "tabB",
                                                   "subtitles": [{"shot": 3, "text": "B 的", "d0": 0.1, "d1": 1.0}]}).json()
    hid = b["history"][-1]["id"]
    r = c.post("/api/episodes/97/cut-project/restore", json={"history_id": hid, "by": "A", "client": "tabA"})
    assert r.status_code == 202
    j = r.json()
    assert j["subtitles"] == a_subs                                         # A 的原文回来了
    last = j["history"][-1]
    assert last["restored_from"] == hid and last["what"].startswith("恢复被覆盖的改动")
    assert last["overrode"][0]["prev_value"] == [{"shot": 3, "text": "B 的", "d0": 0.1, "d1": 1.0}]   # B 的也存着
    src = next(h for h in j["history"] if h.get("id") == hid)
    assert src["restored"][0]["history_id"] == last["id"]
    j2 = c.post("/api/episodes/97/cut-project/restore", json={"history_id": last["id"], "by": "B"}).json()
    assert j2["subtitles"] == [{"shot": 3, "text": "B 的", "d0": 0.1, "d1": 1.0}]
    assert c.post("/api/episodes/97/cut-project/restore", json={"history_id": "nope"}).status_code == 404


def test_resend_with_old_base_from_same_window_is_not_an_override(env):
    """P2：同一个窗口拿旧基线重发 / 连改，不记假的“覆盖”；别的窗口才算"""
    c, root, fin = env
    base = c.get("/api/episodes/97/cut-project").json()["rev"]
    c.put("/api/episodes/97/cut-project", json={"rev": base, "client": "tabA", "subtitles": [{"shot": 1, "text": "一", "d0": 0.2, "d1": 1.2}]})
    same = c.put("/api/episodes/97/cut-project", json={"rev": base, "client": "tabA",
                                                      "subtitles": [{"shot": 1, "text": "一（改）", "d0": 0.2, "d1": 1.2}]}).json()
    assert "overrode" not in same["history"][-1]
    again = c.put("/api/episodes/97/cut-project", json={"rev": base, "client": "tabA",
                                                       "subtitles": [{"shot": 1, "text": "一（改）", "d0": 0.2, "d1": 1.2}]}).json()
    assert again["rev"] == same["rev"]                                       # 原样重发 = 没有新改动，不多记一条
    other = c.put("/api/episodes/97/cut-project", json={"rev": base, "client": "tabB",
                                                       "subtitles": [{"shot": 2, "text": "二", "d0": 0.2, "d1": 1.2}]}).json()
    assert other["history"][-1]["overrode"][0]["prev_value"][0]["text"] == "一（改）"
