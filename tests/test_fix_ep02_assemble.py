"""FIX（ep02_iter v0）合成硬规则 + 泛红限幅 + bt709 标记 + 整集 BGM 模式。合成素材，不碰真数据、不用 GPU。"""
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from ns_post import assemble as A  # noqa: E402
from ns_post.assemble import Placement, Settings, plan_timeline  # noqa: E402
from ns_post.speakers import SpokenLine  # noqa: E402


def _p(kind, shot, length, line=0):
    return Placement(SpokenLine(kind, shot, line, "lin_wan", "x", ""), [], length)


def _takes(d: Path, takes, locked=None, active=None):
    (d / "takes").mkdir(parents=True, exist_ok=True)
    for t in takes:
        (d.parents[2] / t["file"]).parent.mkdir(parents=True, exist_ok=True)
        (d.parents[2] / t["file"]).write_bytes(b"x")
    (d / "takes.json").write_text(json.dumps({"takes": takes, "locked": locked or {}, "active": active or {}}),
                                  encoding="utf-8")


def _vt(n, verdict, shot="S1", **kw):
    return {"n": n, "stage": "video", "file": f"renders/ep09/{shot}/takes/video_{n:03d}.mp4",
            "qc": {"motion": {"verdict": verdict, "labels": ["静止·不合格"] if verdict == "fail" else []}}, **kw}


# ---------------- P0 ① 只用合格定稿 take

def test_qualified_take_rules(tmp_path):
    d = tmp_path / "data" / "renders" / "ep09" / "S1"
    _takes(d, [_vt(1, "pass"), _vt(2, "fail"), _vt(3, "warn")], locked={"video": 3}, active={"video": 1})
    p, take, why = A.qualified_take(d)
    assert take["n"] == 3 and why == "定稿 v3"                 # active 是 1，但成片用定稿 3
    _takes(d, [_vt(1, "pass"), _vt(2, "fail")], locked={"video": 2}, active={"video": 1})
    p, take, why = A.qualified_take(d)
    assert p is None and "运动质检 fail" in why                 # 定稿是废片 → 标缺，不退回 active
    p, take, why = A.qualified_take(d, allow_unlocked_qc_pass=True)
    assert take["n"] == 1 and "未定稿" in why
    _takes(d, [_vt(1, "pass", bad="坏图：x")], locked={"video": 1})
    assert A.qualified_take(d)[0] is None
    _takes(d, [_vt(1, "pass")], locked={}, active={"video": 1})
    assert A.qualified_take(d)[2] == "没有定稿版本"


def test_find_source_marks_missing(tmp_path):
    data = tmp_path / "data"
    d = data / "renders" / "ep09" / "S1"
    _takes(d, [_vt(1, "fail")], locked={"video": 1}, active={"video": 1})
    src = A.find_source(9, 1, data=data, allow_laptop_video=True)
    assert src["kind"] == "black" and src["missing"] and "fail" in src["missing_reason"]
    _takes(d, [_vt(1, "fail"), _vt(2, "pass")], locked={"video": 2}, active={"video": 1})
    src = A.find_source(9, 1, data=data, allow_laptop_video=True)
    assert src["kind"] == "video" and src["take"]["n"] == 2 and src["take"]["locked"] is True
    legacy = A.find_source(9, 1, data=data, allow_laptop_video=True, settings=Settings(take_policy="active_legacy"))
    assert legacy["take_policy"] == "active_legacy" and legacy["path"].name == "video_001.mp4"   # 旧行为会用废片


# ---------------- 剪定住段 / 长镜拆刀

def test_freeze_trims():
    fps = 24
    d = [0.1] * 12 + [2.0] * 100 + [0.1] * 30          # 开头 0.5 s、结尾 1.25 s 定住
    assert A.freeze_trims(d, fps) == (12, 30)
    assert A.freeze_trims([0.1] * 5 + [2.0] * 100 + [0.1] * 5, fps) == (0, 0)   # <0.3 s 不剪
    h, t = A.freeze_trims([0.1] * 100 + [2.0] * 10 + [0.1] * 50, fps)
    assert 161 - h - t >= 36                              # 至少留 1.5 s
    h, t = A.freeze_trims([0.1] * 150, fps)
    assert h == 0 and 151 - t >= 36


def test_split_pieces_and_frames():
    assert A.split_pieces(5.0, max_s=6, min_piece_s=2, zoom=1.15) == [(0.0, 5.0, 1.0)]
    ps = A.split_pieces(12.25, max_s=6, min_piece_s=2, zoom=1.15)
    assert len(ps) == 3 and [p[2] for p in ps] == [1.0, 1.15, 1.0] and ps[-1][1] == 12.25
    ps = A.split_pieces(10.0, max_s=6, min_piece_s=2, zoom=1.15, busy=[(4.0, 6.5)])
    assert ps[0][1] in (4.0, 6.5)                         # 切点挪到句间，不切在台词中间
    fr = A.piece_frames(ps, 240, 24)
    assert sum(fr) == 240 and all(f > 0 for f in fr)


# ---------------- 对白 / 独白溢出判不通过

def test_voiceover_overflow_fails_instead_of_covering_next_shot():
    vo, d2 = _p("voiceover", 1, 10.0), _p("dialogue", 2, 3.0)
    _, tail, warns = plan_timeline([10, 10], [vo, d2])
    assert vo.end_s <= 10.0 and vo.overflow_s > 0 and tail == 0
    assert d2.start_s >= 10.0 and not any("moved" in w for w in warns) and any("判不通过" in w for w in warns)


def test_dialogue_cut_records_overflow():
    ps = [_p("dialogue", 1, 8.0, 0), _p("dialogue", 1, 8.0, 1)]
    plan_timeline([10], ps, Settings(max_tempo=1.2))
    assert any(p.overflow_s > 0 for p in ps)


# ---------------- 底噪 / 交叉淡化 / bt709

def test_fill_silence_removes_digital_silence():
    sr = 48000
    x = np.zeros((sr, 2), np.float32)
    x[: sr // 2] = 0.1 * np.sin(np.linspace(0, 2000, sr // 2))[:, None]
    assert A.min_window_dbfs(x, sr) < -150
    y, rep = A.fill_silence(x, sr, -50.0, 0.1)
    assert A.min_window_dbfs(y, sr) >= -52.0 and rep["filled_windows"] >= 5
    assert np.allclose(y[: sr // 4], x[: sr // 4], atol=1e-6)   # 有声处不动


def test_defaults_crossfade_and_color_tags():
    s = Settings()
    assert s.edge_fade_s == pytest.approx(0.12)
    vf = A._vf(s, 100, 1080, 1920)
    assert "out_color_matrix=bt709" in vf and "color_primaries=bt709" in vf
    assert "scale=1242:2208" in A._vf(s, 100, 1080, 1920, zoom=1.15)
    assert A.COLOR_TAGS == ["-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709"]


# ---------------- 配置解析 + h3_music（整集统一 BGM）

def test_resolve_settings_reads_config(tmp_path):
    cfg = tmp_path / "rq.json"
    cfg.write_text(json.dumps({"post": {"edit_rules": {"max_shot_s": 5.0, "overflow_policy": "spill"},
                                        "h3_music": {"default": "duck_under_bgm", "duck_db": 9.0},
                                        "skin_guard": {"enabled": True, "per_episode": {"3": False}}}}),
                   encoding="utf-8")
    s = A.resolve_settings(Settings(), 2, cfg)
    assert (s.max_shot_s, s.overflow_policy, s.h3_music, s.h3_music_duck_db, s.skin_guard) == \
        (5.0, "spill", "duck_under_bgm", 9.0, True)
    assert A.resolve_settings(Settings(), 3, cfg).skin_guard is False
    s = A.resolve_settings(Settings(h3_music="keep", h3_music_duck_db=12.0, max_shot_s=8.0), 2, cfg)   # CLI 优先
    assert (s.h3_music, s.h3_music_duck_db, s.max_shot_s) == ("keep", 12.0, 8.0)
    s = A.resolve_settings(Settings(), 2, tmp_path / "none.json")
    assert s.take_policy == "locked_qc" and s.h3_music == "keep"


def test_real_config_h3_music_is_duck_under_bgm():
    s = A.resolve_settings(Settings(), 2)
    assert s.h3_music == "duck_under_bgm" and s.take_policy == "locked_qc" and s.overflow_policy == "fail"


def test_bgm_duck_mode_replaces_h3_silence_cues_and_reports_regen():
    from ns_post.music import Cue
    cues = [Cue(shot=k + 1, start_s=8.0 * k, action="drop", intensity=0, source="h3_music",
                text="撤到静默（H3 已带配乐）") for k in range(3)]
    meta = {"shot_starts": [0, 8, 14], "duration_s": 84.0}
    out, why = A.bgm_cues_for_duck_mode(cues, meta, [0.0, 8.0, 14.58], [8.0, 6.58, 6.58])
    assert [c.action for c in out] == ["enter", "continue", "continue"] and all(c.intensity for c in out)
    assert any("撤到静默" in w for w in why) and any("偏差" in w for w in why) and any("BGM 长" in w for w in why)
    keep = [Cue(shot=1, start_s=0.0, action="drop", intensity=0, source="script", text="撤到静默")]
    assert A.bgm_cues_for_duck_mode(keep, {}, [0.0], [8.0])[0][0].action == "drop"   # 剧本自己的 drop 不动


# ---------------- 端到端：定住段被剪、拆刀、bt709、gates

def _ff():
    from ns_post.ffmpeg import FFmpeg, FFmpegError
    try:
        return FFmpeg.discover()
    except FFmpegError:
        pytest.skip("no ffmpeg")


def test_assemble_trims_frozen_tail_and_splits(tmp_path):
    from ns_post.tts import FakeTts
    ff = _ff()
    data = tmp_path / "data"
    d = data / "renders_gpu3" / "ep98" / "S1"
    (d / "takes").mkdir(parents=True)
    clip = d / "takes" / "video_001.mp4"
    # 6 s 运动 + 2 s 定住（tpad clone）→ 8 s；有音轨
    ff.run(["-f", "lavfi", "-i", "testsrc2=s=384x672:r=24:d=6", "-f", "lavfi", "-i", "sine=f=220:r=48000:d=8",
            "-vf", "tpad=stop_mode=clone:stop_duration=2", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(clip)])
    (d / "takes.json").write_text(json.dumps({"takes": [
        {"n": 1, "stage": "video", "file": "renders_gpu3/ep98/S1/takes/video_001.mp4",
         "qc": {"motion": {"verdict": "warn"}}}], "locked": {"video": 1}, "active": {"video": 1}}), encoding="utf-8")
    ep = {"number": 98, "title": "t", "shots": [{"index": 1, "duration": 8, "dialogue": [], "voiceover": None}]}
    tl = A.assemble_episode(ep, tmp_path / "out", tts=FakeTts(), ff=ff, data=data, cache_dir=tmp_path / "c" / "tts",
                            settings=Settings(preset="ultrafast", deliver_4k="off", bgm=False, max_shot_s=3.0,
                                              split_min_piece_s=1.0, skin_guard=False, color_match=False,
                                              dialogue_source="tts", pace_tighten=False),   # V2 节奏收紧另测（test_v2_pace）
                            log=lambda *_: None)
    sh = tl["shots"][0]
    assert sh["trim_tail_s"] == pytest.approx(2.0, abs=0.15) and sh["duration_s"] == pytest.approx(6.0, abs=0.15)
    assert sh["pieces"] and len(sh["pieces"]) == 2 and sh["take"]["n"] == 1
    assert tl["gates"]["verdict"] == "pass" and tl["room_tone"]["min_window_dbfs_after"] >= -51
    out = ROOT / tl["output"] if not Path(tl["output"]).is_absolute() else Path(tl["output"])
    pr = json.loads(subprocess.run([ff.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=color_space,color_primaries,color_transfer", "-of", "json", str(out)],
                                   capture_output=True, text=True).stdout)["streams"][0]
    assert (pr["color_space"], pr["color_primaries"], pr["color_transfer"]) == ("bt709", "bt709", "bt709")


# ---------------- 泛红限幅（纯函数）

def test_skin_guard_compresses_cheek_blob_but_not_lips():
    pytest.importorskip("cv2")
    from ns_post import skin_guard as SG
    import cv2
    H, W = 400, 300
    img = np.full((H, W, 3), (225, 190, 175), np.uint8)          # 肤色
    cv2.circle(img, (110, 230), 28, (235, 120, 120), -1)          # 脸颊红斑
    cv2.ellipse(img, (150, 300), (30, 12), 0, 0, 360, (200, 70, 80), -1)   # 嘴唇
    face = np.array([75, 120, 150, 210, 115, 200, 185, 200, 150, 250, 125, 300, 175, 300, 0.9], np.float32)
    s = SG.settings(config=Path("missing.json"))
    lab0 = SG.lab_of(img)
    out, frac = SG.guard_frame(img, face, 25.0, s)
    lab1 = SG.lab_of(out)
    assert frac > 0
    assert lab1[230, 110, 1] < lab0[230, 110, 1] - 5                 # 红斑 a* 明显下降
    assert abs(float(lab1[300, 150, 1]) - float(lab0[300, 150, 1])) < 2.0   # 嘴唇不褪色
    s_nolips = dict(s, exclude_lips=False)
    out2, _ = SG.guard_frame(img, face, 25.0, s_nolips)
    assert SG.lab_of(out2)[300, 150, 1] < lab0[300, 150, 1] - 5     # 不排除时嘴唇会被压（原型的已知问题）


# ---------------- dejudder：bt709 矩阵 + 标记

def test_dejudder_writes_bt709_tags(tmp_path):
    pytest.importorskip("cv2")
    ff = _ff()
    src, dst = tmp_path / "in.mp4", tmp_path / "out.mp4"
    ff.run(["-f", "lavfi", "-i", "testsrc2=s=96x160:r=24:d=1", "-c:v", "libx264", "-preset", "ultrafast",
            "-pix_fmt", "yuv420p", str(src)])
    r = subprocess.run([sys.executable, str(ROOT / "tools" / "dejudder.py"), str(src), str(dst)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    pr = json.loads(subprocess.run([ff.ffprobe, "-v", "error", "-select_streams", "v:0", "-show_entries",
                                    "stream=color_space,color_primaries,color_transfer", "-of", "json", str(dst)],
                                   capture_output=True, text=True).stdout)["streams"][0]
    assert (pr["color_space"], pr["color_primaries"], pr["color_transfer"]) == ("bt709", "bt709", "bt709")
