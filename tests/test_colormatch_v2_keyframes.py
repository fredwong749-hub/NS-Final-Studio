"""V2 keyframe discovery for colormatch: data/pipeline/runs/<run>/video/clips/epNN/<shot>__tag.mp4 -> jobs.json."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "services" / "post"))

from ns_post import colormatch  # noqa: E402


def _mk(tmp_path, jobs=True, shot="ep01-S2", files=(True, True)):
    data = tmp_path / "data"
    vdir = data / "pipeline" / "runs" / "r1" / "video"
    clip = vdir / "clips" / "ep01" / "ep01-S2__v1_s1_sr1080.mp4"
    clip.parent.mkdir(parents=True)
    clip.write_bytes(b"")
    src = data / "renders" / "s" / "ep01" / "S2" / "takes" / "image_001_raw_post.png"
    inp = vdir / "inputs" / "ep01-S2_abc.jpg"
    for f, ok in zip((src, inp), files):
        if ok:
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_bytes(b"x")
    if jobs:
        job = {"shot": shot, "first_frame": inp.relative_to(tmp_path).as_posix(),
               "first_frame_src": src.relative_to(tmp_path).as_posix()}
        (vdir / "jobs.json").write_text(json.dumps({"schema": "series10_video.jobs/1", "shots": [job]}), encoding="utf-8")
    return data, clip, src, inp


def test_v2_first_candidates_order(tmp_path):
    data, clip, src, inp = _mk(tmp_path)
    r = colormatch.keyframe_candidates(clip, data)
    assert [(l, p.resolve()) for l, p in r["first"]] == [
        ("jobs.first_frame_src", src.resolve()), ("jobs.first_frame", inp.resolve())]
    assert r["last"] == []


def test_v2_cc_suffix_clip_still_matches(tmp_path):
    data, clip, src, inp = _mk(tmp_path)
    c2 = clip.with_name("ep01-S2__v1_s1_sr1080_4k.mp4")
    c2.write_bytes(b"")
    assert len(colormatch.keyframe_candidates(c2, data)["first"]) == 2


def test_v2_missing_jobs_json(tmp_path):
    data, clip, *_ = _mk(tmp_path, jobs=False)
    assert colormatch.keyframe_candidates(clip, data)["first"] == []


def test_v2_shot_not_in_jobs(tmp_path):
    data, clip, *_ = _mk(tmp_path, shot="ep01-S9")
    assert colormatch.keyframe_candidates(clip, data)["first"] == []


def test_v2_corrupt_jobs_json(tmp_path):
    data, clip, *_ = _mk(tmp_path)
    (data / "pipeline/runs/r1/video/jobs.json").write_text("{bad", encoding="utf-8")
    assert colormatch.keyframe_candidates(clip, data)["first"] == []


def test_v2_files_missing(tmp_path):
    data, clip, *_ = _mk(tmp_path, files=(False, False))
    assert colormatch.keyframe_candidates(clip, data)["first"] == []


def test_v2_partial_files(tmp_path):
    data, clip, src, inp = _mk(tmp_path, files=(False, True))
    assert [l for l, _ in colormatch.keyframe_candidates(clip, data)["first"]] == ["jobs.first_frame"]


def test_v1_structure_unchanged(tmp_path):
    data = tmp_path / "data"
    sd = data / "renders" / "ep01" / "S1"
    (sd / "takes").mkdir(parents=True)
    clip = sd / "takes" / "video_001.mp4"
    clip.write_bytes(b"")
    (sd / "frame.png").write_bytes(b"x")
    (sd / "takes.json").write_text(json.dumps({"active": {"image": 1}, "takes": []}), encoding="utf-8")
    r = colormatch.keyframe_candidates(clip, data)
    assert r["shot_dir"] == sd.resolve()
    assert [l for l, _ in r["first"]] == ["frame.png"]
    assert r["last"] == []
