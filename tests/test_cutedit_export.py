"""CUTEDIT 导出端到端（测试夹具，V2 还没有成片）：换序 + 手动裁切 + 改过的字幕 → tools/cut_export.py 合成 →
时间线还原剧本镜号、字幕按本镜起点换算进外挂 srt、工程 final = 定稿。ffmpeg 合成素材 + 假 TTS，不碰真数据、不用 GPU。"""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("", "services/api", "services/render_router", "services/post", "services/agent"):
    sys.path.insert(0, str(ROOT / p) if p else str(ROOT))

from ns_api import cut_project as CP  # noqa: E402
from ns_api import run_paths as RP  # noqa: E402
from ns_render import pipeline as P  # noqa: E402


def _ff():
    from ns_post.ffmpeg import FFmpeg, FFmpegError
    try:
        return FFmpeg.discover()
    except FFmpegError:
        pytest.skip("no ffmpeg")


def test_export_reordered_trimmed_with_edited_subtitles(tmp_path, monkeypatch):
    ff = _ff()
    root = tmp_path / "root"
    data = root / "data"
    fin = data / "renders" / "ep97" / "_final"
    fin.mkdir(parents=True)
    clips = data / "fixture" / "clips"
    clips.mkdir(parents=True)
    for k, hue in ((1, 0), (2, 120), (3, 240)):
        ff.run(["-f", "lavfi", "-i", f"testsrc2=s=384x672:r=24:d=3", "-f", "lavfi", "-i", "sine=f=220:r=48000:d=3",
                "-vf", f"hue=h={hue}", "-c:v", "libx264", "-preset", "ultrafast", "-pix_fmt", "yuv420p", "-c:a", "aac",
                "-shortest", str(clips / f"s{k}.mp4")])
    script = data / "fixture" / "script.json"
    script.write_text(json.dumps({"episodes": [{"number": 97, "title": "夹具", "shots": [
        {"index": 1, "duration": 3, "dialogue": [], "voiceover": None},
        {"index": 2, "duration": 3, "dialogue": [{"speaker": "旁白", "text": "测试一句。"}], "voiceover": None},
        {"index": 3, "duration": 3, "dialogue": [], "voiceover": None}]}]}, ensure_ascii=False), encoding="utf-8")
    shots = [{"shot": f"ep97-S{k}", "index": k, "kind": "video", "file": f"data/fixture/clips/s{k}.mp4",
              "source_duration_s": 3.0, "trim_head_s": 0.0, "trim_tail_s": 0.0, "duration_s": 3.0} for k in (1, 2, 3)]
    (fin / "ep97_v1.timeline.json").write_text(json.dumps({
        "duration_s": 9.0, "settings": {"dialogue_source": "tts"}, "bgm": {"used": False}, "shots": shots,
        "speech": [{"kind": "dialogue", "shot": 2, "text": "测试一句。", "start_s": 3.5, "end_s": 4.5, "files": []}]},
        ensure_ascii=False), encoding="utf-8")

    monkeypatch.setattr(P, "ROOT", root)
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(CP, "current_sources", lambda n: {})
    monkeypatch.setattr(RP, "script_path", lambda root=None, run=None: script)
    import ns_post.tts as TTS
    monkeypatch.setattr(TTS, "KokoroBackend", lambda cfg, **k: TTS.FakeTts())
    monkeypatch.setattr(TTS, "SenseVoiceAsr", lambda cfg, **k: None)
    from tools import cut_export as CE
    monkeypatch.setattr(CE, "ROOT", root)

    proj = CP.load_project(97)
    assert proj["bgm"]["file"] is None and CP.music_choices(97, proj) == []   # 没配乐：不写死去找某部剧的配乐目录
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    app = FastAPI()
    app.include_router(CP.router)
    c = TestClient(app)
    r = c.put("/api/episodes/97/cut-project", json={
        "rev": proj["rev"], "order": [3, 1, 2], "segments": [{"index": 1, "trim_head_s": 0.5, "trim_tail_s": 0.0}],
        "subtitles": [{"shot": 2, "text": "改过的字幕", "d0": 0.4, "d1": 1.6}]})
    assert r.status_code == 202, r.text

    assert CE.main(["ep97"]) == 0
    pj = json.loads((fin / "cut_project.json").read_text(encoding="utf-8"))
    rev = pj["rev"]
    assert pj["final"]["file"] == f"data/renders/ep97/_final/ep97_cut_r{rev}.mp4"
    tl = json.loads((fin / f"ep97_cut_r{rev}.timeline.json").read_text(encoding="utf-8"))
    assert [(s["index"], s["cut_position"]) for s in tl["shots"]] == [(3, 1), (1, 2), (2, 3)]
    s1 = next(s for s in tl["shots"] if s["index"] == 1)
    assert s1.get("manual_trim") and s1["trim_head_s"] == 0.5
    s2_start = next(s for s in tl["shots"] if s["index"] == 2)["start_s"]
    srt = (fin / f"ep97_cut_r{rev}.srt").read_text(encoding="utf-8")
    assert "改过的字幕" in srt and "测试一句" not in srt
    first = srt.splitlines()[1]
    ms = int(round((s2_start + 0.4) * 1000))
    assert first.startswith(f"00:00:{ms // 1000 % 60:02d},{ms % 1000:03d}")
    job = json.loads((fin / "_cut_export_job.json").read_text(encoding="utf-8"))
    assert job["state"] == "done" and job["output"].endswith(f"ep97_cut_r{rev}.mp4")
