"""AUD（2026-10-31）：对白来源 = H3 原声（dialogue_source="h3"）、独白提速选项、对照版命名。
合成素材（ffmpeg 测试图 + 正弦音）+ FakeTts/FakeAsr，不用语音模型、不用 GPU。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ns_post.assemble import (Placement, Settings, assemble_episode, dialogue_source_for,  # noqa: E402
                              plan_timeline)
from ns_post.h3_dialogue import check_shot, split_lines  # noqa: E402
from ns_post.speakers import SpokenLine  # noqa: E402
from ns_post.tts import FakeAsr, FakeTts  # noqa: E402
from test_post import synthetic  # noqa: E402,F401  (fixture)


def _p(kind, shot, length, line=0):
    return Placement(SpokenLine(kind, shot, line, "lin_wan", "x", ""), [], length)


def _det(text, t0=1.0, step=0.2):
    toks = list(text)
    return {"text": text, "tokens": toks, "timestamps": [t0 + k * step for k in range(len(toks))], "event": "<|BGM|>"}


def test_split_and_check_single_and_multi_line():
    rows = split_lines(_det("同事借的。明天还。"), ["同事借的。明天还。"])
    assert rows[0]["heard"] == "同事借的。明天还。" and rows[0]["t0"] == 1.0
    rows = split_lines(_det("你好嗯你好"), ["你好。", "嗯，你好。"])
    assert [r["heard"] for r in rows] == ["你好", "嗯你好"] and rows[1]["t0"] == pytest.approx(1.4)
    ok, rows, why = check_shot(_det("对不起，我马上赶。"), ["对不起，我马上改，"], 0.35)
    assert ok and rows[0]["cer"] == pytest.approx(0.143)
    ok, _, why = check_shot(_det("。"), ["冷。"], 0.35)
    assert not ok and why == "no speech detected"
    ok, _, why = check_shot(_det("完全不同的一句话"), ["同事借的。明天还。"], 0.35)
    assert not ok and why.startswith("CER")
    assert check_shot(None, ["冷。"], 0.35)[0] is False


def test_fixed_h3_line_is_not_moved_and_voiceover_avoids_it():
    d = _p("dialogue", 2, 2.0)
    d.fixed, d.source, d.start_s = True, "h3", 11.0
    vo = _p("voiceover", 1, 8.0)
    plan_timeline([10, 10], [vo, d])
    assert d.start_s == 11.0
    assert vo.end_s <= 11.0 - 0.2 + 1e-6 or vo.start_s >= 13.0


def test_voiceover_speed_up_is_opt_in():
    vo = _p("voiceover", 1, 12.0)
    plan_timeline([10, 10], [vo])
    assert vo.tempo == 1.0  # 现状：不提速
    vo = _p("voiceover", 1, 12.0)
    _, _, warns = plan_timeline([10, 10], [vo], Settings(vo_max_tempo=1.2))
    assert vo.tempo == pytest.approx(1.2) and any("sped up" in w for w in warns)


def test_dialogue_source_config(tmp_path):
    cfg = tmp_path / "rq.json"
    assert dialogue_source_for(2, config=cfg) == "tts"
    cfg.write_text(json.dumps({"post": {"dialogue_source": {"default": "tts", "per_episode": {"2": "h3"}}}}), "utf-8")
    assert dialogue_source_for(2, config=cfg) == "h3" and dialogue_source_for(3, config=cfg) == "tts"
    assert dialogue_source_for(3, Settings(dialogue_source="h3"), config=cfg) == "h3"
    with pytest.raises(ValueError):
        dialogue_source_for(3, Settings(dialogue_source="x"), config=cfg)


def test_assemble_h3_mode_keeps_h3_dialogue_and_falls_back(synthetic):
    ff, data, episode, tmp = synthetic
    out = tmp / "episodes"
    # S1 有 H3 音轨：回听对得上 → H3 原声；S3 没有 H3 音轨（只有分轨）→ TTS 兜底 + warning
    asr = FakeAsr(details={"S1.wav": _det("你好嗯你好", t0=0.5)})
    tl = assemble_episode(episode, out, tts=FakeTts(), asr=asr, ff=ff, data=data, cache_dir=tmp / "cache" / "tts",
                          settings=Settings(preset="ultrafast", deliver_4k="off", dialogue_source="h3",
                                            # 剪定住段 / 按对白收紧节奏（pace_tighten，config 默认可能开）另测；
                                            # 这里断言 H3 原声句的时间戳 = 回听时间戳，不让剪头改变它
                                            trim_frozen=False, pace_tighten=False),
                          log=lambda *_: None, variant="H3原声")
    assert (out / "ep99_PREVIEW_未完成_H3原声.mp4").is_file()
    assert (out / "ep99_PREVIEW_未完成_H3原声.timeline.json").is_file()
    assert not (out / "ep99.timeline.json").exists()
    assert tl["settings"]["dialogue_source"] == "h3"
    src = {x["key"]: x["source"] for x in tl["speech"]}
    assert src == {"ep99-S1#0": "h3", "ep99-S1#1": "h3", "ep99-S2#vo": "tts", "ep99-S3#0": "tts"}
    s1 = next(x for x in tl["speech"] if x["key"] == "ep99-S1#0")
    assert s1["start_s"] == pytest.approx(0.5) and s1["h3_asr"]["cer"] == 0.0
    assert any(w.startswith("S3:") and "TTS 兜底" in w for w in tl["warnings"])
    rows = {r["shot"]: r for r in tl["h3_dialogue"]}
    assert rows[1]["dialogue"] == "h3" and rows[1]["music"]["music_detected"] is True
    assert rows[3]["dialogue"] == "tts_fallback"
    vo = next(x for x in tl["speech"] if x["kind"] == "voiceover")
    assert "vo_fit" in vo and isinstance(vo["vo_fit"]["overlaps_dialogue"], list)
