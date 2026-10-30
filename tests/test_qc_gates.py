"""ns_qc gates (docs/qc_gates.md): thresholds/verdicts, colour & structure maths, keyframe gate on synthetic clips,
audio pitch/music heuristics, provenance (bible_version stamps, heartbeat, path mapping) and an end-to-end run over a
tiny synthetic mirror. CPU only; ffmpeg-dependent tests skip when ffmpeg is absent."""
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "packages" / "qc"))

from ns_qc import audio_gates as A  # noqa: E402
from ns_qc import media as M  # noqa: E402
from ns_qc import provenance as P  # noqa: E402
from ns_qc import thresholds as TH  # noqa: E402
from ns_qc import video_gates as V  # noqa: E402

FF = shutil.which("ffmpeg")
needs_ff = pytest.mark.skipif(not FF, reason="ffmpeg not installed")


# ---------------- thresholds ----------------

def test_every_gate_has_source_and_valid_level():
    for g, r in TH.T.items():
        assert r["source"] and r["pi"], g
        assert r["on_breach"] in ("fail", "warn", "info"), g
        if r["status"] in ("suggested", "pending"):  # G-rules: undocumented / unlocked numbers never fail
            assert r["on_breach"] != "fail", g


def test_judge_verdicts_and_unchecked_is_not_pass():
    assert TH.judge("Q-K2", 25.0)["verdict"] == "pass"
    assert TH.judge("Q-K2", 12.0)["verdict"] == "fail"
    assert TH.judge("Q-K4", 9.0)["verdict"] == "warn"
    assert TH.judge("Q-A2", -13.8)["verdict"] == "warn"
    assert TH.judge("Q-A2", -20.0)["verdict"] == "pass"
    assert TH.judge("Q-K6", 0.4)["verdict"] == "info"
    u = TH.judge("Q-D1", None, unchecked="no model")
    assert u["verdict"] == "unchecked"
    assert TH.worst(["pass", "unchecked"]) == "unchecked"
    assert TH.worst(["pass", "info"]) == "pass"
    assert TH.worst(["warn", "fail", "pass"]) == "fail"


# ---------------- maths ----------------

def test_de2000_reference_pair():
    # Sharma, Wu & Dalal (2005) test data, pair 1
    assert abs(M.de2000((50.0, 2.6772, -79.7751), (50.0, 0.0, -82.7485)) - 2.0425) < 1e-3
    assert M.de2000((60, 10, 10), (60, 10, 10)) == 0.0


def test_psnr_ssim_identity_and_degradation():
    rng = np.random.default_rng(0)
    a = rng.integers(0, 255, (120, 80, 3), dtype=np.uint8)
    assert M.psnr(a, a) == 99.0
    assert M.ssim(a, a) == pytest.approx(1.0, abs=1e-6)
    y, x = np.mgrid[0:120, 0:80]
    g = np.repeat(((x * 2 + y) % 256).astype(np.uint8)[..., None], 3, -1)  # smooth ramp
    b = np.clip(g.astype(int) + rng.integers(-60, 60, g.shape), 0, 255).astype(np.uint8)
    assert M.psnr(g, b) < 20 and M.ssim(g, b) < 0.5


def test_h3_geometry_centre_crop_to_target():
    img = np.zeros((2016, 1300, 3), np.uint8)  # wider than 4:7
    out = M.h3_geometry(img, (768, 1344))
    assert out.shape == (1344, 768, 3)


# ---------------- synthetic clips ----------------

def _clip(tmp: Path, name="c.mp4", size="768x1344", tone=None, seconds=3) -> Path:
    p = tmp / name
    cmd = [FF, "-y", "-v", "error", "-f", "lavfi", "-i", f"testsrc2=size={size}:rate=24:duration={seconds}"]
    if tone:
        cmd += ["-f", "lavfi", "-i", tone]
    cmd += ["-pix_fmt", "yuv420p", "-c:v", "libx264", "-crf", "12"]
    if tone:
        cmd += ["-c:a", "aac", "-shortest"]
    subprocess.run(cmd + [str(p)], check=True)
    return p


def _png(arr: np.ndarray, p: Path) -> Path:
    from PIL import Image
    Image.fromarray(arr).save(p)
    return p


@needs_ff
def test_keyframe_gate_passes_on_own_frames_and_flags_colour_shift(tmp_path):
    clip = _clip(tmp_path)
    info = M.video_info(clip)
    f0 = M.decode_indices(clip, [0], info)[0]
    fl = M.last_frame(clip, info)
    r = V.keyframe_gate(clip, _png(f0, tmp_path / "f.png"), _png(fl, tmp_path / "l.png"), info=info)
    g = {(x["gate"], x.get("edge")): x for x in r["gates"]}
    assert g[("Q-K1", None)]["verdict"] == "pass"
    assert g[("Q-K2", None)]["value"] > 35
    assert g[("Q-K3", None)]["value"] > 0.9
    assert g[("Q-K4", "first")]["verdict"] == "pass"
    shifted = np.clip(f0.astype(int) + [40, 0, -40], 0, 255).astype(np.uint8)
    r2 = V.keyframe_gate(clip, _png(shifted, tmp_path / "s.png"), None, info=info)
    g2 = {(x["gate"], x.get("edge")): x for x in r2["gates"]}
    assert g2[("Q-K4", "first")]["verdict"] == "warn"
    assert g2[("Q-K3", None)]["verdict"] == "unchecked"  # missing last keyframe is never a pass


@needs_ff
def test_wrong_size_and_aspect_fail(tmp_path):
    clip = _clip(tmp_path, size="720x1280", seconds=1)
    kf = _png(np.zeros((1000, 1000, 3), np.uint8), tmp_path / "sq.png")
    r = V.keyframe_gate(clip, kf, None)
    g = {x["gate"]: x for x in r["gates"]}
    assert g["Q-K1"]["verdict"] == "fail"
    assert g["Q-K1b"]["verdict"] == "fail"


@needs_ff
def test_drift_gate_without_models_is_unchecked(tmp_path):
    clip = _clip(tmp_path, seconds=2)
    r = V.drift_gate(clip, models=None)
    g = {x["gate"]: x for x in r["gates"]}
    assert g["Q-D1"]["verdict"] == "unchecked"
    assert g["Q-D5"]["verdict"] in ("pass", "warn")  # centre-box clothing proxy still measured


# ---------------- audio ----------------

def _harmonic(f0, sr=16000, s=2.0):
    t = np.arange(int(sr * s)) / sr
    return (0.3 * sum(np.sin(2 * np.pi * f0 * k * t) / k for k in range(1, 6))).astype(np.float32)


@pytest.mark.parametrize("f0", [110.0, 220.0])
def test_f0_track_recovers_pitch(f0):
    t, f = A.f0_track(_harmonic(f0))
    v = f[f > 0]
    assert len(v) > 0.8 * len(f)
    assert abs(np.median(v) - f0) / f0 < 0.05


def test_prompt_music_parsing():
    assert A.prompt_music("x\n\nnon_diegetic_music: N/A") == "N/A"
    assert A.prompt_music("Soundscape: lobby") == "unspecified"
    assert A.prompt_music("non_diegetic_music: soft piano, slow tempo.") .startswith("soft piano")


def test_clap_evidence_rejected_when_stems_made_from_another_video():
    st = {"video_sha256": "aaa", "h3_rest_tags": {"piano music": 0.7, "background music": 0.2, "silence": 0.1}}
    assert A.clap_music(st, "aaa")[0] == pytest.approx(0.9)
    assert A.clap_music(st, "bbb")[0] is None


def test_tonal_ratio_tone_vs_noise():
    rng = np.random.default_rng(1)
    assert A.tonal_ratio(_harmonic(220, s=3)) > 0.8
    assert A.tonal_ratio((0.1 * rng.standard_normal(48000)).astype(np.float32)) < 0.2


@needs_ff
def test_audio_gate_male_voice_warns_only_without_male_speaker(tmp_path):
    clip = _clip(tmp_path, tone="sine=frequency=120:sample_rate=48000", seconds=3)
    r = A.audio_gate(clip, prompt="non_diegetic_music: N/A", h3_dialogue_genders=set(), has_dialogue=False)
    g = {x["gate"]: x for x in r["gates"]}
    assert g["Q-A3"]["verdict"] == "warn" and g["Q-A3"]["value"] > 0.5
    assert g["Q-A5"]["verdict"] == "warn"
    assert g["Q-A1"]["verdict"] == "unchecked"  # no CLAP evidence → not a pass
    assert g["Q-A2"]["value"] is not None
    r2 = A.audio_gate(clip, prompt=None, h3_dialogue_genders={"male"}, has_dialogue=True)
    g2 = {x["gate"]: x for x in r2["gates"]}
    assert g2["Q-A3"]["verdict"] == "unchecked"


# ---------------- provenance ----------------

def test_stamp_states():
    assert P.stamp_state({}, "v1") == "unstamped"
    assert P.stamp_state({"bible_version": "v0"}, "v1") == "stale"
    assert P.stamp_state({"bible_version": "v1"}, "v1") == "current"


def test_heartbeat_age(tmp_path):
    hb = tmp_path / ".last_sync_gpu3"
    now = time.time()
    hb.write_text(str(int(now - 3600)))
    r = P.heartbeat(hb, now)
    assert r["verdict"] == "warn" and 59 <= r["value"] <= 61
    hb.write_text(str(int(now - 60)))
    assert P.heartbeat(hb, now)["verdict"] == "pass"
    assert P.heartbeat(tmp_path / "missing", now)["verdict"] == "unchecked"


def test_local_path_maps_gpu3_mirror_paths(tmp_path):
    data = tmp_path / "data"
    f = data / "renders_gpu3" / "ep01" / "S1" / "frame.png"
    f.parent.mkdir(parents=True)
    f.write_bytes(b"x")
    p, how = P.local_path("/root/x/nsfs_mirror/data/renders_gpu3/ep01/S1/frame.png", data, f.parent)
    assert p == f and how == "gpu3 mirror path"
    p2, how2 = P.local_path("/root/x/ns-studio/data/run/weita/ep01/frames/ep01s1.png", data, f.parent)
    assert p2 is None and "not in the local mirror" in how2


@needs_ff
def test_run_episode_end_to_end(tmp_path):
    from ns_qc.runner import run_episode
    root = tmp_path
    (root / "data").mkdir()
    (root / "data" / "state_timeline.json").write_text(json.dumps({"bible_version": "cur"}), encoding="utf-8")
    sd = root / "data" / "renders_gpu3" / "ep01" / "S1"
    (sd / "takes").mkdir(parents=True)
    clip = _clip(sd / "takes", "video_001.mp4", tone="sine=frequency=300:sample_rate=48000", seconds=2)
    shutil.copy(clip, sd / "video.mp4")
    f0 = M.decode_indices(clip, [0])[0]
    _png(f0, sd / "takes" / "image_001.png")
    _png(f0, sd / "frame.png")
    takes = {"active": {"image": 1, "video": 1}, "takes": [
        {"n": 1, "stage": "image", "file": "renders_gpu3/ep01/S1/takes/image_001.png", "bible_version": "old"},
        {"n": 1, "stage": "video", "file": "renders_gpu3/ep01/S1/takes/video_001.mp4", "created_at": "2026-10-29T10:00:00Z",
         "reference": "/root/x/nsfs_mirror/data/renders_gpu3/ep01/S1/takes/image_001.png", "bible_version": "cur",
         "prompt": "non_diegetic_music: N/A"}]}
    (sd / "takes.json").write_text(json.dumps(takes), encoding="utf-8")
    (sd.parent.parent / ".last_sync_gpu3").write_text(str(int(time.time())))
    r = run_episode(1, root=root, out_dir=tmp_path / "out", log=lambda *a: None)
    s = r["shots"]["S1"]
    g = {(x["gate"], x.get("edge")): x for x in s["gates"]}
    assert g[("Q-K2", None)]["verdict"] == "pass"
    assert g[("Q-P1", None)]["verdict"] == "fail"  # active image take stamped with an old bible_version
    assert g[("Q-P4", "first")]["verdict"] == "pass"
    assert g[("Q-P5", None)]["verdict"] == "pass"
    assert g[("Q-P6", None)]["verdict"] == "pass"
    assert [x["state"] for x in r["stale"]] == ["stale"]
    md = (tmp_path / "out" / "qc_ep01.md").read_text(encoding="utf-8")
    assert "Q-P1" in md and "过期" in md
    assert json.loads((tmp_path / "out" / "qc_ep01.json").read_text(encoding="utf-8"))["episode"] == 1
