"""T38 post-production: speaker resolution, timeline planning, BGM cues, and an end-to-end assembly on
synthetic inputs (ffmpeg test patterns and tones in temp dirs; fake TTS — no speech model, no GPU)."""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post.assemble import Placement, Settings, assemble_episode, gain_envelope, plan_timeline  # noqa: E402
from ns_post.ffmpeg import FFmpeg, FFmpegError  # noqa: E402
from ns_post.music import Cue, ignored_edits, level_curve, parse_cue_text, resolve_cues  # noqa: E402
from ns_post.speakers import SpokenLine, resolve_episode, tts_text  # noqa: E402
from ns_post.tts import FakeAsr, FakeTts, load_voice_config, voice_for  # noqa: E402


def _dl(note, text):
    return {"speaker_note": note, "text": text, "stage": None}


def _shot(idx, dialogue=(), vo=None, duration=10, **kw):
    return {"episode": 99, "index": idx, "dialogue": list(dialogue), "duration": duration,
            "voiceover": {"note": None, "text": vo} if vo else None, "img_prompt": kw.get("img", ""),
            "motion_prompt": kw.get("motion", ""), "dialogue_raw": None, "music_cue": kw.get("cue", "")}


# ---------------- speakers ----------------

def test_tts_text_cleanup():
    assert tts_text("“方案——第三页……错了。”") == "方案，第三页…错了。"
    assert tts_text("（她，笑）好。") == "好。"


def test_resolve_named_he_action_continuation_and_alternation():
    ep = {"number": 99, "shots": [
        _shot(1, [_dl("顾沉低声", "蓝头发。"), _dl("她小声", "染了三年。"), _dl("他", "很大胆。"),
                  _dl("合上盒子", "然后上珠。")]),
        _shot(2, [_dl(None, "（她，一口气）“我分不清，"), _dl(None, "到底是为谁。”"), _dl(None, "（沉默三秒）"),
                  _dl("陈宇，温柔", "晚晚。"), _dl(None, "嗯？"), _dl(None, "没事。")], vo="汤是热的。"),
        _shot(3, [_dl("他，不抬头", "五毫米的球。")], img="陈宇家客厅"),
        _shot(4, [_dl(None, "（她）完了。（他）这是什么？")]),
    ]}
    lines = resolve_episode(ep)
    got = [(ln.key, ln.speaker) for ln in lines]
    assert got == [
        ("S1#0", "gu_chen"), ("S1#1", "lin_wan"), ("S1#2", "gu_chen"), ("S1#3", "gu_chen"),
        ("S2#0", "lin_wan"), ("S2#1", "lin_wan"), ("S2#2", "chen_yu"), ("S2#3", "lin_wan"), ("S2#4", "chen_yu"),
        ("S2#vo", "lin_wan"),
        ("S3#0", "chen_yu"),
        ("S4#0", "lin_wan"), ("S4#1", "chen_yu"),  # 他 → last male of the episode
    ]
    assert lines[4].text == "我分不清，"


def test_resolve_overrides_and_every_script_speaker_has_a_voice():
    cfg = load_voice_config()
    script = json.loads((ROOT / "data" / "import" / "script_v2.json").read_text(encoding="utf-8"))
    for ep in script["episodes"]:
        for ln in resolve_episode(ep, cfg.get("line_overrides")):
            assert voice_for(cfg, ln.speaker), ln
    ep = {"number": 99, "shots": [_shot(1, [_dl(None, "你好。")])]}
    assert resolve_episode(ep, {"ep99-S1#0": "gu_chen"})[0].speaker == "gu_chen"


def test_voice_config_is_fixed_and_distinct():
    cfg = load_voice_config()
    sids = [c["sid"] for c in cfg["characters"].values()]
    assert len(sids) == len(set(sids))
    lw = voice_for(cfg, "lin_wan")[0]
    assert lw.sid == cfg["characters"]["lin_wan"]["sid"] and lw.speed < 1.0  # slow per the 声音规则
    assert voice_for(cfg, "lin_wan", voiceover=True)[0].speed <= lw.speed
    assert len(voice_for(cfg, "chorus_men")) == 4


# ---------------- timeline ----------------

def _p(kind, shot, length, line=0, note=""):
    return Placement(SpokenLine(kind, shot, line, "lin_wan", "x", note), [], length)


def test_dialogue_fits_inside_its_shot():
    ps = [_p("dialogue", 1, 2.0, 0), _p("dialogue", 1, 3.0, 1)]
    starts, tail, warns = plan_timeline([10, 10], ps)
    assert starts == [0, 10] and tail == 0 and warns == []
    assert ps[0].start_s == pytest.approx(0.3) and ps[1].start_s == pytest.approx(2.65)


def test_dialogue_too_long_is_sped_up_then_cut():
    ps = [_p("dialogue", 1, 5.0, 0), _p("dialogue", 1, 5.0, 1)]
    _, _, warns = plan_timeline([10], ps)
    assert ps[0].tempo > 1.0 and ps[1].end_s <= 10.0 and any("sped up" in w for w in warns)
    ps = [_p("dialogue", 1, 8.0, 0), _p("dialogue", 1, 8.0, 1)]
    _, _, warns = plan_timeline([10], ps, Settings(max_tempo=1.2))
    assert ps[0].tempo == pytest.approx(1.2)
    assert ps[1].end_s <= 10.0 and any("cut at the shot end" in w for w in warns)


def test_voiceover_spans_shot_boundary_and_moves_next_dialogue():
    vo, d2 = _p("voiceover", 1, 10.0), _p("dialogue", 2, 3.0)
    _, tail, warns = plan_timeline([10, 10], [vo, d2])
    assert vo.end_s > 10.0  # spans into S2
    assert d2.start_s >= vo.end_s + 0.2 - 1e-6 and d2.end_s <= 20.0
    assert any("into S2" in w for w in warns) and any("moved" in w for w in warns)


def test_voiceover_past_episode_end_holds_last_frame():
    vo = _p("voiceover", 1, 12.0)
    _, tail, warns = plan_timeline([10], [vo])
    assert vo.end_s + 0.6 - 10 <= tail < vo.end_s + 0.6 - 10 + 1 / 24 + 1e-9
    assert (tail * 24) == pytest.approx(round(tail * 24)) and any("held" in w for w in warns)


def test_gain_envelope_gates_with_ramps():
    g = gain_envelope(48000, 1000, [(10.0, 20.0, 40.0)], 0.1)
    assert g[5000] == pytest.approx(1.0)
    assert g[15000] == pytest.approx(0.01, rel=1e-3)
    assert 0.01 < g[9950] < 1.0


# ---------------- music ----------------

def test_parse_cue_text():
    c = parse_cue_text("进入，强度2，压低")
    assert (c.action, c.intensity, c.duck_db) == ("enter", 2, 6.0)
    assert parse_cue_text("swell to 3").action == "swell" and parse_cue_text("swell to 3").intensity == 3
    assert parse_cue_text("落下").action == "drop"
    assert parse_cue_text("点题 stinger").action == "stinger"
    assert parse_cue_text("") is None
    c = parse_cue_text("撤到静默：只留极轻微的合成器呼吸声和心跳般的低频脉冲，无需避让")
    assert (c.action, c.intensity, c.duck_db) == ("drop", 0, 0.0)
    c = parse_cue_text("渐强：加入轻微的弦乐颤音，强度2，对白避让（在顾沉说话时声音压低）")
    assert (c.action, c.intensity, c.duck_db) == ("swell", 2, 6.0)
    c = parse_cue_text("延续：电子钢琴单音重复，强度1，无需避让")
    assert (c.action, c.intensity, c.duck_db) == ("continue", 1, 0.0)
    assert parse_cue_text("转换：温暖的大提琴长音进入，强度2，独白避让").action == "enter"


def test_json_cue_timeline_wins_over_edits_and_script():
    shots = [_shot(1, cue="进入，强度1"), _shot(2, cue="推高"), _shot(3)]
    starts = [0.0, 10.0, 20.0]
    meta = {"shot_starts": [0.0, 8.0, 16.0],
            "cues": [{"shot": "S1", "action": "enter", "intensity": 2},
                     {"shot": 2, "start_s": 9.0, "action": "swell", "intensity": 3},  # 1 s into S2 (json timing)
                     {"start_s": 25.0, "action": "drop"}]}
    cues = resolve_cues(shots, starts, meta, {3: "强度3"})
    assert [(c.start_s, c.action, c.source) for c in cues] == [
        (0.0, "enter", "music_json"), (11.0, "swell", "music_json"), (25.0, "drop", "music_json")]
    assert ignored_edits(meta, {3: "强度3"}) == {3: "强度3"}
    edit_and_script = resolve_cues(shots, starts, {}, {3: "强度3"})
    assert [(c.action, c.source) for c in edit_and_script] == [("enter", "script"), ("swell", "script"),
                                                                ("continue", "edit")]
    assert resolve_cues([_shot(1)], [0.0], {}, {})[0].source == "default"


def test_stale_json_cue_timeline_falls_back_to_script_cues():
    """封板修复：epXX.json 按另一版剧本（6 镜）生成、本集现在 7 镜 → 不再按镜号套用旧时间轴，改用剧本 / 修改的提示"""
    from ns_post.music import stale_timeline
    shots = [_shot(i, cue="进入，强度1" if i == 1 else "") for i in range(1, 8)]
    starts = [i * 8.0 for i in range(7)]
    meta = {"shot_starts": [i * 10.0 for i in range(6)], "cues": [{"shot": 6, "action": "drop"}]}
    assert stale_timeline(meta, 7) and not stale_timeline(meta, 6) and not stale_timeline({}, 7)
    cues = resolve_cues(shots, starts, meta, {7: "强度3"})
    assert [(c.shot, c.action, c.source) for c in cues] == [(1, "enter", "script"), (7, "continue", "edit")]
    assert ignored_edits(meta, {7: "强度3"}, 7) == {} and ignored_edits(meta, {7: "强度3"}) == {7: "强度3"}

def test_level_curve_fades_in_swells_and_drops():
    sr = 100
    cues = [Cue(1, 0.0, "enter", 1), Cue(2, 10.0, "swell", 3), Cue(3, 20.0, "drop")]
    g = level_curve(cues, 3000, sr, 30.0, fade_out_s=0.0)
    assert g[0] == pytest.approx(0.0, abs=1e-3) and g[500] == pytest.approx(10 ** (-10 / 20), rel=1e-3)
    assert g[1990] > g[1100] > g[900]
    assert g[2900] < 1e-3


# ---------------- end to end (ffmpeg, synthetic media) ----------------

def _ff() -> FFmpeg:
    try:
        return FFmpeg.discover()
    except FFmpegError:
        pytest.skip("ffmpeg not installed")


def _make(ff: FFmpeg, args: list[str]):
    ff.run(args)


@pytest.fixture()
def synthetic(tmp_path):
    ff = _ff()
    data = tmp_path / "data"
    g = data / "renders_gpu3" / "ep99"
    for i in (1, 3):
        (g / f"S{i}" / "takes").mkdir(parents=True)
    (data / "renders" / "ep99" / "S2").mkdir(parents=True)
    # S1: H3-like clip 768x1344, longer than the shot, with an audio tone; active take + a 4K version
    clip = g / "S1" / "takes" / "video_002.mp4"
    _make(ff, ["-f", "lavfi", "-i", "testsrc2=s=768x1344:r=24:d=3.125", "-f", "lavfi",
               "-i", "sine=f=220:r=32000:d=3.125", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p",
               "-c:a", "aac", "-shortest", str(clip)])
    _make(ff, ["-f", "lavfi", "-i", "testsrc2=s=2160x3840:r=24:d=3.125", "-c:v", "libx264", "-preset",
               "ultrafast", "-pix_fmt", "yuv420p", str(g / "S1" / "takes" / "video_002_4k.mp4")])
    (g / "S1" / "takes.json").write_text(json.dumps({"takes": [
        {"n": 2, "stage": "video", "file": "renders_gpu3/ep99/S1/takes/video_002.mp4"}],
        "active": {"video": 2}}), encoding="utf-8")
    # S2: no video anywhere → placeholder still from the laptop's first frame
    _make(ff, ["-f", "lavfi", "-i", "color=c=blue:s=1080x1920", "-frames:v", "1",
               str(data / "renders" / "ep99" / "S2" / "frame.png")])
    # S3: a clip without audio + gpu3 stems
    _make(ff, ["-f", "lavfi", "-i", "testsrc=s=768x1344:r=24:d=2", "-c:v", "libx264", "-preset", "ultrafast",
               "-pix_fmt", "yuv420p", str(g / "S3" / "video.mp4")])
    (g / "S3" / "audio").mkdir()
    for name, f in (("h3_vocals", 300), ("h3_rest", 80), ("foley", 1000)):
        _make(ff, ["-f", "lavfi", "-i", f"sine=f={f}:r=48000:d=3", "-ac", "2", str(g / "S3" / "audio" / f"{name}.wav")])
    (g / "S3" / "audio" / "stems.json").write_text(json.dumps({"stems": {
        "foley": {"gain_db": -8, "offset_s": 0.5}}}), encoding="utf-8")
    # BGM shorter than the episode (looped) + cue timeline
    (data / "music").mkdir()
    _make(ff, ["-f", "lavfi", "-i", "sine=f=440:r=44100:d=4", "-ac", "2", str(data / "music" / "ep99.wav")])
    (data / "music" / "ep99.json").write_text(json.dumps({"bpm": 90, "model": "test", "seed": 1,
        "duck_spans": [{"shot": 3, "start_s": 6.5, "end_s": 7.5, "duck_db": 6.0, "why": "H3 vocals"}], "cues": [
        {"shot": 1, "action": "enter", "intensity": 1}, {"shot": 3, "action": "swell", "intensity": 3}]}),
        encoding="utf-8")
    episode = {"number": 99, "title": "test", "shots": [
        _shot(1, [_dl("顾沉", "你好。"), _dl("她", "嗯，你好。")], duration=3),
        _shot(2, vo="这是一段比较长的内心独白，会跨过镜头边界一直说下去。", duration=3),
        _shot(3, [_dl("陈宇", "晚安。")], duration=3, cue="推高"),
    ]}
    return ff, data, episode, tmp_path


def test_assemble_episode_end_to_end(synthetic):
    ff, data, episode, tmp = synthetic
    out = tmp / "episodes"
    tl = assemble_episode(episode, out, tts=FakeTts(), asr=FakeAsr(), ff=ff, data=data,
                          cache_dir=tmp / "cache" / "tts", settings=Settings(preset="ultrafast", deliver_4k="auto"),
                          log=lambda *_: None)
    # S2 是占位静帧 → 只能是预览：不叫 final、没有 epXX 别名
    mp4 = out / "ep99_PREVIEW_未完成.mp4"
    assert mp4.is_file() and tl["preview"] is True
    assert not (out / "ep99_final.mp4").exists() and not (out / "ep99.mp4").exists()
    info = ff.info(mp4)
    assert (info["width"], info["height"], info["video_codec"], info["audio_codec"]) == (1080, 1920, "h264", "aac")
    assert info["fps"] == pytest.approx(24.0)
    # G13：有视频的镜头按 H3 片段实际时长，占位静帧按剧本秒数（3 s）
    durs = [s["duration_s"] for s in tl["shots"]]
    assert [s["duration_from"] for s in tl["shots"]] == ["h3_video", "script", "h3_video"]
    assert durs[1] == 3.0
    assert all(d == pytest.approx(s["source_duration_s"], abs=1e-3)
               for d, s in zip(durs, tl["shots"]) if s["kind"] == "video")
    total = sum(durs) + tl["tail_hold_s"]
    assert tl["frames"] == ff.count_frames(mp4) == sum(round(d * 24) for d in durs) + round(tl["tail_hold_s"] * 24)
    assert info["duration"] == pytest.approx(total, abs=0.1)
    assert tl["loudness"]["measured"]["integrated_lufs"] == pytest.approx(-14.0, abs=1.0)
    assert tl["subtitles"] is False
    kinds = [(s["kind"], s.get("audio")) for s in tl["shots"]]
    assert kinds == [("video", "h3_track"), ("still", "none"), ("video", "stems")]
    assert tl["shots"][0]["trimmed_s"] == 0 and tl["shots"][0]["script_duration_s"] == 3.0
    assert {s["name"] for s in tl["shots"][2]["stems"]} == {"h3_vocals", "h3_rest", "foley"}
    assert tl["bgm"]["used"] and tl["bgm"]["looped"] and [c["action"] for c in tl["bgm"]["cues"]] == ["enter", "swell"]
    sp = tl["speech"]
    assert [x["speaker"] for x in sp] == ["gu_chen", "lin_wan", "lin_wan", "chen_yu"]
    for x in sp:
        if x["kind"] == "dialogue":
            shot = tl["shots"][x["shot"] - 1]
            assert shot["start_s"] <= x["start_s"] and x["end_s"] <= shot["start_s"] + shot["duration_s"] + 1e-6
    assert any("placeholder" in w for w in tl["warnings"])
    # 4K delivery: S1 from its 4K clip, the others upscaled
    k4 = tl["deliveries"]["4k"]
    assert k4["size"] == [2160, 3840] and k4["frames"] == tl["frames"]
    assert [s["picture_4k"] for s in tl["shots"]] == ["4k_clip", "upscaled_lanczos", "upscaled_lanczos"]
    saved = json.loads((out / "ep99.timeline.json").read_text(encoding="utf-8"))
    assert saved["deliveries"]["1080p"]["file"].endswith("ep99_PREVIEW_未完成.mp4") and saved["preview"] is True
    assert saved["deliveries"]["4k"]["file"].endswith("ep99_PREVIEW_未完成_4k.mp4")
    assert saved["bgm"]["duck_spans"] == 1 and saved["bgm"]["cue_source"] == "music_json"


def test_assemble_without_music_warns_and_skips(synthetic):
    ff, data, episode, tmp = synthetic
    for f in (data / "music").iterdir():
        f.unlink()
    tl = assemble_episode(episode, tmp / "ep2", tts=FakeTts(), ff=ff, data=data, cache_dir=tmp / "cache" / "tts",
                          settings=Settings(preset="ultrafast", deliver_4k="off"), log=lambda *_: None)
    assert tl["bgm"] == {"used": False, "reason": "no file"}
    assert any("no BGM" in w for w in tl["warnings"]) and "4k" not in tl["deliveries"]


def test_qa_gate(tmp_path):
    import hashlib
    from ns_post.assemble import qa_gate
    v = tmp_path / "v1.mp4"
    v.write_bytes(b"clip-1")
    sha = hashlib.sha256(b"clip-1").hexdigest()
    srcs, src_list = [{"index": 1}], [{"kind": "video", "path": str(v)}]
    qa = tmp_path / "qa.json"
    ok, why = qa_gate(qa, srcs, src_list)
    assert not ok and "没有 qa.json" in why[0]
    qa.write_text(json.dumps({"verdict": "pass", "shots": {"S1": {"verdict": "pass", "video_sha256": "x"}}}), "utf-8")
    ok, why = qa_gate(qa, srcs, src_list)
    assert not ok and any("sha256" in w for w in why)
    qa.write_text(json.dumps({"verdict": "pass", "shots": {"S1": {"verdict": "pass", "video_sha256": sha}}}), "utf-8")
    assert qa_gate(qa, srcs, src_list) == (True, [])
    qa.write_text(json.dumps({"verdict": "rework", "shots": {"S1": {"verdict": "pass", "video_sha256": sha}}}), "utf-8")
    assert qa_gate(qa, srcs, src_list)[0] is False



def test_h3_music_shots_follow_compiler_rule():
    """X-4 / E8（项目方 2026-10-30）：H3 已带配乐的镜头后期不再叠 BGM；判断与编译器同一个 resolve_music"""
    from ns_agent import h3_prompt as H3
    from ns_post.music import h3_music_shots
    from ns_schema.h3_lint import frames_for_seconds
    body = ("Live-action, cinematic, shallow depth of field, a medium shot begins in the position, framing and lighting "
            "established by Picture 1. She looks up. She settles into the pose and composition established by "
            "Picture 2 at the end of the shot.")
    h3 = lambda music: H3.assemble(frames_for_seconds(10), body, "Quiet room tone.", music)  # noqa: E731
    shots = [{"index": 1, "h3_prompt": h3("N/A")},                                 # 剧本明写 N/A
             {"index": 2, "h3_prompt": h3("Soft piano, slow tempo, quiet dynamics.")},  # 剧本自带配乐
             {"index": 3},                                                          # 没写 → 本集默认
             {"index": 4, "music_cue": "落下，强度0"},                                 # 静默提示
             {"index": 5}]
    ep = {"music_bgm": "Sparse piano, slow tempo, soft dynamics."}
    got = h3_music_shots(shots, ep, {5: "N/A"})
    assert got == {2: "script", 3: "episode"}
    assert h3_music_shots(shots, {}, {}) == {2: "script"}       # 没有本集默认时只剩剧本自带的
