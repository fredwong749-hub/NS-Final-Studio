"""Per-shot colour correction of H3 clips to our keyframes (ns_post.colormatch): synthetic colour-shifted ramps
prove the drift drops, an identical clip stays unchanged, dark scenes are never brightened past the keyframe, and
an end-to-end pass writes <clip>_cc.mp4 next to the original with the audio stream copied (CPU, temp dirs)."""
import hashlib
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "post"))

from ns_post import colormatch as C  # noqa: E402
from ns_post.ffmpeg import FFmpeg, FFmpegError  # noqa: E402

W, H, N = 96, 168, 24


def _keyframe(dark: bool = False) -> np.ndarray:
    """Colour ramps + a disc (structure) — a stand-in for a graded keyframe."""
    y, x = np.mgrid[0:H, 0:W].astype(np.float32)
    r = 40 + 170 * x / W
    g = 50 + 150 * y / H
    b = 120 + 60 * np.sin(x / 9.0) * np.cos(y / 13.0)
    disc = ((x - W * 0.5) ** 2 + (y - H * 0.42) ** 2) < (W * 0.22) ** 2
    r[disc], g[disc], b[disc] = 225, 170, 150  # skin-ish
    img = np.stack([r, g, b], -1)
    if dark:
        img *= 0.3
    return np.clip(img, 0, 255).astype(np.uint8)


def _drift(rgb: np.ndarray, t: float, dl=-10.0, da=3.0, db=6.0, contrast=1.15) -> np.ndarray:
    """H3-like drift growing with t ∈ [0, 1]: darker, warmer/lilac, more contrast."""
    lab = C.to_lab(rgb)
    mu = lab[..., 0].mean()
    lab[..., 0] = (lab[..., 0] - mu) * (1 + (contrast - 1) * t) + mu + dl * t
    lab[..., 1] += da * t
    lab[..., 2] += db * t
    return C.to_rgb(lab)


def _mean_de(frames, kf, s=C.CcSettings()):
    ref = C.lab_stats(C.to_lab(kf), s)
    return float(np.mean([C.delta_e(C.lab_stats(C.to_lab(f), s), ref) for f in frames]))


def test_drifted_ramps_are_pulled_back_to_the_keyframes():
    kf = _keyframe()
    frames = [_drift(kf, i / (N - 1)) for i in range(N)]
    s = C.CcSettings(strength=1.0)
    plan = C.make_plan(frames, kf, kf, s)
    assert plan.end_ref_kind == "last_keyframe"
    out = C.correct_frames(frames, plan, s)
    before, after = _mean_de(frames, kf, s), _mean_de(out, kf, s)
    assert before > 4.0
    assert after < 0.35 * before
    end_before = C.delta_e(C.lab_stats(C.to_lab(frames[-1]), s), plan.first_ref)
    end_after = C.delta_e(C.lab_stats(C.to_lab(out[-1]), s), plan.first_ref)
    assert end_before > 10 and end_after < 2.0
    rep = C.drift_report(frames, plan, s)
    assert rep["summary"]["end"]["vs_ref"]["dL"] < -8  # darkening is reported
    assert rep["summary"]["comparable"]["until_frame"] == N - 1


def test_default_strength_and_clamps_limit_the_correction():
    kf = _keyframe()
    frames = [_drift(kf, i / (N - 1), dl=-30.0) for i in range(N)]  # extreme darkening
    plan = C.make_plan(frames, kf, kf, C.CcSettings())
    src = C.average_stats([C.lab_stats(C.to_lab(f)) for f in frames[-C.CcSettings().edge_frames:]])
    shift = (plan.end.gain - 1) * src.mean + plan.end.bias
    assert shift[0] <= C.CcSettings().max_l_shift + 1e-6
    assert np.all(plan.end.gain <= C.CcSettings().gain_max + 1e-9)


def test_identical_clip_is_unchanged():
    kf = _keyframe()
    frames = [kf.copy() for _ in range(N)]
    plan = C.make_plan(frames, kf, kf)
    assert plan.summary()["identity"]
    out = C.correct_frames(frames, plan)
    assert all(np.array_equal(a, b) for a, b in zip(frames, out))


def test_dark_scene_never_brightened_past_the_keyframe():
    kf = _keyframe(dark=True)
    s = C.CcSettings(strength=1.0)
    assert C.lab_stats(C.to_lab(kf), s).mean[0] < s.dark_l
    brighter = [_drift(kf, i / (N - 1), dl=+8.0, da=0, db=0, contrast=1.0) for i in range(N)]
    plan = C.make_plan(brighter, kf, kf, s)
    assert plan.dark and plan.end.gain[0] <= 1.0
    ref_l = plan.first_ref.mean[0]
    out = C.correct_frames(brighter, plan, s)
    for f in out:
        assert C.lab_stats(C.to_lab(f), s).mean[0] <= ref_l + 0.6
    # a darker-than-keyframe night frame is lifted at most to the keyframe, never above it
    m = C.LabMap(np.array([1.0, 1, 1]), np.array([12.0, 0, 0]))
    darker = _drift(kf, 1.0, dl=-4.0, da=0, db=0, contrast=1.0)
    lifted = C.apply_map(darker, m, s, l_cap=float(ref_l))
    assert C.lab_stats(C.to_lab(lifted), s).mean[0] <= ref_l + 0.6


def test_unrelated_keyframe_is_rejected_by_the_structure_gate():
    kf = _keyframe()
    other = np.ascontiguousarray(np.rot90(_keyframe(), 2))
    frames = [_drift(kf, i / (N - 1)) for i in range(N)]
    assert C.structure_match(C.to_lab(frames[0]), C.to_lab(kf)) > 0.95
    assert C.structure_match(C.to_lab(frames[0]), C.to_lab(other)) < C.CcSettings().match_min
    plan = C.make_plan(frames, other, None)
    assert plan.start.is_identity() and plan.end_ref_kind == "hold"


# ---------------- end to end (ffmpeg) ----------------

def _ff() -> FFmpeg:
    try:
        return FFmpeg.discover()
    except FFmpegError:
        pytest.skip("ffmpeg not installed")


def _write_clip(ff: FFmpeg, frames: list[np.ndarray], out: Path) -> None:
    cmd = [ff.ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}", "-r", "24",
           "-i", "-", "-f", "lavfi", "-i", "sine=f=330:r=48000:d=1", "-map", "0:v", "-map", "1:a", "-c:v", "libx264",
           "-preset", "ultrafast", "-crf", "8", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(out)]
    subprocess.run(cmd, input=b"".join(f.tobytes() for f in frames), check=True)


def _sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _audio_packets(ff: FFmpeg, p: Path) -> str:
    return subprocess.run([ff.ffprobe, "-v", "error", "-select_streams", "a:0", "-show_entries",
                           "packet=pts,size", "-of", "csv=p=0", str(p)], capture_output=True, text=True).stdout


def test_end_to_end_writes_cc_clip_next_to_original(tmp_path):
    ff = _ff()
    kf = _keyframe()
    from PIL import Image
    first, last = tmp_path / "frame.png", tmp_path / "last.png"
    Image.fromarray(kf).save(first)
    Image.fromarray(kf).save(last)
    clip = tmp_path / "video_001.mp4"
    _write_clip(ff, [_drift(kf, i / (N - 1)) for i in range(N)], clip)
    sha0 = _sha(clip)
    s = C.CcSettings(strength=1.0, analysis_width=W, preset="ultrafast", crf=8)
    rep = C.correct_clip(clip, first, last, ff=ff, s=s, data=tmp_path, log=lambda *_: None)
    out = tmp_path / "video_001_cc.mp4"
    assert rep["output"] and out.is_file() and _sha(clip) == sha0
    assert out.with_suffix(".json").is_file()
    js = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
    assert js["after"]["summary"]["mean_dE_ref"] < 0.4 * js["before"]["summary"]["mean_dE_ref"]
    assert js["after"]["summary"]["end"]["vs_ref"]["dE"] < 2.5 < js["before"]["summary"]["end"]["vs_ref"]["dE"]
    assert _audio_packets(ff, out) == _audio_packets(ff, clip) != ""  # audio stream copied
    assert ff.count_frames(out) == N
    with pytest.raises(ValueError):
        C.correct_clip(out, first, last, ff=ff, s=s, data=tmp_path)


def test_end_to_end_identical_clip_is_stream_copied(tmp_path):
    ff = _ff()
    kf = _keyframe()
    clip = tmp_path / "video_001.mp4"
    _write_clip(ff, [kf] * N, clip)
    # the keyframe = the clip's own decoded first frame (so the measured drift is exactly zero)
    from PIL import Image
    f0 = next(C.iter_frames(ff, clip))
    Image.fromarray(f0).save(tmp_path / "frame.png")
    s = C.CcSettings(analysis_width=W)
    rep = C.correct_clip(clip, tmp_path / "frame.png", None, ff=ff, s=s, data=tmp_path, log=lambda *_: None)
    assert rep["plan"]["identity"] and rep["encode"].startswith("stream copy")
    a = list(C.iter_frames(ff, clip))
    b = list(C.iter_frames(ff, tmp_path / "video_001_cc.mp4"))
    assert len(a) == len(b) and all(np.array_equal(x, y) for x, y in zip(a, b))


def test_keyframe_discovery_skips_the_videos_own_last_frame(tmp_path):
    data = tmp_path / "data"
    sd = data / "renders_gpu3" / "ep99" / "S1"
    (sd / "takes").mkdir(parents=True)
    from PIL import Image
    for name in ("frame.png", "last.png", "takes/video_001_last.png", "takes/image_001.png"):
        Image.fromarray(_keyframe()).save(sd / name)
    (sd / "takes" / "video_001.mp4").write_bytes(b"")
    (sd / "takes.json").write_text(json.dumps({"takes": [
        {"n": 1, "stage": "image", "file": "renders_gpu3/ep99/S1/takes/image_001.png"},
        {"n": 1, "stage": "video", "file": "renders_gpu3/ep99/S1/takes/video_001.mp4",
         "reference": "/root/x/nsfs_mirror/data/renders_gpu3/ep99/S1/takes/image_001.png",
         "last_frame": "renders_gpu3/ep99/S1/takes/video_001_last.png"}],
        "active": {"image": 1, "video": 1}}), encoding="utf-8")
    kc = C.keyframe_candidates(sd / "takes" / "video_001.mp4", data)
    assert kc["first"][0][0] == "take.reference" and kc["first"][0][1].name == "image_001.png"
    assert kc["last"] == []  # no stage "last": last.png is the video's own frame, not a keyframe



def test_cli_dry_run_accepts_relative_clip_path():
    """封板修复：在仓库根目录用相对路径 --clip（片段在仓库内）时不能因 relative_to 崩溃"""
    import shutil
    import tempfile
    ff = _ff()
    kf = _keyframe()
    from PIL import Image
    root = Path(__file__).resolve().parents[1]
    d = Path(tempfile.mkdtemp(prefix="cc_cli_", dir=root / "tests"))
    try:
        Image.fromarray(kf).save(d / "frame.png")
        _write_clip(ff, [_drift(kf, i / (N - 1)) for i in range(N)], d / "video_001.mp4")
        rel = d.relative_to(root).as_posix()
        r = subprocess.run([sys.executable, "tools/color_match_clips.py", "--clip", f"{rel}/video_001.mp4",
                            "--first", f"{rel}/frame.png", "--dry-run"],
                           cwd=root, capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr[-800:]
        assert "video_001" in r.stdout and "frame0" in r.stdout
    finally:
        shutil.rmtree(d, ignore_errors=True)
