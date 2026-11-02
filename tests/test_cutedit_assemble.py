"""CUTEDIT（成片页剪辑器）：assemble_episode(cut_edit=...) —— 手动入出点优先于自动裁切、配乐换曲 / 起点 / 音量 / 淡入淡出；
cut_edit=None 时装配行为完全不变（回归）。合成素材，不碰真数据、不用 GPU。"""
import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post import assemble as A  # noqa: E402
from ns_post.assemble import Settings  # noqa: E402


# ---------------- 纯函数

def test_normalise_cut_trims_drops_bad_values():
    assert A.normalise_cut_trims(None) == {}
    assert A.normalise_cut_trims({"trims": {"3": [0.5, "1.25"], "4": [-1, 0], "x": [1, 1], "5": [1]}}) == \
        {3: (0.5, 1.25), 4: (0.0, 0.0)}


def test_clamp_trim_keeps_minimum_and_fits_shorter_source():
    assert A.clamp_trim(0.5, 1.0, 8.0) == (0.5, 1.0)
    h, t = A.clamp_trim(3.0, 4.0, 5.0)            # 镜头重出、新片更短：入点保留，出点收到片尾
    assert h == 3.0 and 5.0 - h - t == pytest.approx(0.2)
    h, t = A.clamp_trim(9.0, 0.0, 5.0)
    assert 5.0 - h - t >= 0.2 - 1e-9


def test_bgm_edit_envelope_gain_and_fades():
    sr, n = 1000, 10000
    g = A.bgm_edit_envelope(n, sr, {"gain_db": -6.0, "fade_in_s": 1.0, "fade_out_s": 2.0})
    lvl = 10 ** (-6 / 20)
    assert g[0] == pytest.approx(0.0) and g[-1] == pytest.approx(0.0, abs=1e-6)
    assert g[5000] == pytest.approx(lvl, rel=1e-4)
    assert g[500] == pytest.approx(lvl * 0.5, rel=0.01) and g[9000] == pytest.approx(lvl * 0.5, rel=0.01)
    assert np.allclose(A.bgm_edit_envelope(10, sr, {}), 1.0)


# ---------------- 端到端（ffmpeg 合成素材）

def _ff():
    from ns_post.ffmpeg import FFmpeg, FFmpegError
    try:
        return FFmpeg.discover()
    except FFmpegError:
        pytest.skip("no ffmpeg")


def _episode(tmp_path, ff):
    data = tmp_path / "data"
    d = data / "renders_gpu3" / "ep98" / "S1"
    (d / "takes").mkdir(parents=True)
    clip = d / "takes" / "video_001.mp4"
    # 6 s 运动 + 2 s 定住 → 8 s：自动裁切会剪掉结尾 2 s
    ff.run(["-f", "lavfi", "-i", "testsrc2=s=384x672:r=24:d=6", "-f", "lavfi", "-i", "sine=f=220:r=48000:d=8",
            "-vf", "tpad=stop_mode=clone:stop_duration=2", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)])
    (d / "takes.json").write_text(json.dumps({"takes": [
        {"n": 1, "stage": "video", "file": "renders_gpu3/ep98/S1/takes/video_001.mp4",
         "qc": {"motion": {"verdict": "warn"}}}], "locked": {"video": 1}, "active": {"video": 1}}), encoding="utf-8")
    return data, {"number": 98, "title": "t", "shots": [{"index": 1, "duration": 8, "dialogue": [], "voiceover": None}]}


def _run(tmp_path, ff, data, ep, cut_edit=None, out="out", **kw):
    from ns_post.tts import FakeTts
    st = dict(preset="ultrafast", deliver_4k="off", bgm=False, max_shot_s=20.0, skin_guard=False, color_match=False,
              dialogue_source="tts", pace_tighten=True)
    st.update(kw)
    return A.assemble_episode(ep, tmp_path / out, tts=FakeTts(), ff=ff, data=data, cache_dir=tmp_path / "c" / "tts",
                              settings=Settings(**st), log=lambda *_: None, cut_edit=cut_edit)


def test_no_cut_edit_keeps_auto_trim(tmp_path):
    ff = _ff()
    data, ep = _episode(tmp_path, ff)
    tl = _run(tmp_path, ff, data, ep)
    sh = tl["shots"][0]
    assert sh["trim_tail_s"] == pytest.approx(2.0, abs=0.15)          # 自动裁定住段照旧
    assert "manual_trim" not in sh and "cut_edit" not in tl and "cut_edit" not in tl["bgm"]


def test_manual_trim_overrides_auto_trims(tmp_path):
    ff = _ff()
    data, ep = _episode(tmp_path, ff)
    tl = _run(tmp_path, ff, data, ep, cut_edit={"trims": {"1": [0.5, 1.0]}})
    sh = tl["shots"][0]
    assert sh["manual_trim"] is True
    assert (sh["trim_head_s"], sh["trim_tail_s"]) == (0.5, 1.0)       # 不是自动的 0 / 2.0，也没加节奏裁切
    assert sh["duration_s"] == pytest.approx(6.5, abs=0.06)
    assert tl["duration_s"] == pytest.approx(6.5, abs=0.1)
    assert tl["cut_edit"]["trims"] == {"1": [0.5, 1.0]}


def test_manual_trim_clamped_when_source_shorter(tmp_path):
    ff = _ff()
    data, ep = _episode(tmp_path, ff)
    tl = _run(tmp_path, ff, data, ep, cut_edit={"trims": {"1": [7.0, 3.0]}})
    sh = tl["shots"][0]
    assert sh["trim_head_s"] == 7.0 and sh["duration_s"] == pytest.approx(0.2, abs=0.06)


def test_bgm_edit_switches_file_and_records(tmp_path):
    ff = _ff()
    data, ep = _episode(tmp_path, ff)
    mdir = tmp_path / "music"
    mdir.mkdir()
    ff.run(["-f", "lavfi", "-i", "sine=f=330:r=48000:d=12", "-ac", "2", str(mdir / "ep98.wav")])
    alt = tmp_path / "alt.wav"
    ff.run(["-f", "lavfi", "-i", "sine=f=440:r=48000:d=12", "-ac", "2", str(alt)])
    base = _run(tmp_path, ff, data, ep, bgm=True, music_dir=str(mdir), out="o1")
    assert base["bgm"]["used"] and base["bgm"]["file"].endswith("ep98.wav") and "cut_edit" not in base["bgm"]
    edit = {"file": str(alt), "offset_s": 2.0, "gain_db": -3.0, "fade_in_s": 1.0, "fade_out_s": 1.5}
    tl = _run(tmp_path, ff, data, ep, cut_edit={"bgm": edit}, bgm=True, music_dir=str(mdir), out="o2")
    assert tl["bgm"]["used"] and tl["bgm"]["file"].replace("\\", "/").endswith("alt.wav")
    assert tl["bgm"]["cut_edit"] == edit
    missing = _run(tmp_path, ff, data, ep, cut_edit={"bgm": {"file": str(tmp_path / "none.wav")}}, bgm=True,
                   music_dir=str(mdir), out="o3")
    assert missing["bgm"]["file"].endswith("ep98.wav") and any("找不到" in w for w in missing["warnings"])
