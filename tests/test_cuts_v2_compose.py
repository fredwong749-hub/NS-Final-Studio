"""成片页“合成新版本”（POST /api/episodes/{n}/cut-job）在 V2（资产包模式）下走 tools/assemble_series.py → build → compose，
配乐 / 音色只按 V2 取（run_media），不碰 V1 的 data/music/series10 和 voices.json；V1 照旧 assemble_episode.py。不碰真数据、不用 GPU。"""
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for p in ("", "services/api", "services/render_router", "services/post", "services/agent"):
    sys.path.insert(0, str(ROOT / p) if p else str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from ns_api import cut_project as CP  # noqa: E402
from ns_api import cuts as C  # noqa: E402
from ns_api import run_paths as RP  # noqa: E402
from ns_render import pipeline as P  # noqa: E402


class FakeProc:
    started: list = []

    def __init__(self, cmd, **kw):
        FakeProc.started.append(list(cmd))
        self.returncode = None

    def poll(self):
        return self.returncode


@pytest.fixture()
def v2(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    (tmp_path / "data").mkdir()
    monkeypatch.setattr(C.subprocess, "Popen", FakeProc)
    monkeypatch.setattr(RP, "current_run", lambda root=None: "series10_v2")
    RM = CP._rm()
    monkeypatch.setattr(RM, "is_asset_pack_run", lambda run, root=None: run == "series10_v2")
    C.JOBS.clear()
    FakeProc.started.clear()
    app = FastAPI()
    app.include_router(C.router)
    yield TestClient(app)
    C.JOBS.clear()


def test_v2_cut_job_runs_assemble_series_compose(v2):
    r = v2.post("/api/episodes/1/cut-job", json={"dialogue_source": "auto", "by": "owner"})
    assert r.status_code == 202
    j = r.json()
    assert j["state"] == "running" and j["engine"] == "compose" and j["variant"].startswith("UI")
    cmd = FakeProc.started[0]
    assert cmd[1].replace("\\", "/").endswith("tools/assemble_series.py") and cmd[2] == "ep01"
    assert cmd[cmd.index("--variant") + 1] == j["variant"]
    assert "--dialogue-source" not in cmd                                   # “自动” = assemble_series 的默认
    assert not any("assemble_episode" in str(x) for x in cmd)              # 不再调 V1 的旧命令行
    again = v2.post("/api/episodes/1/cut-job", json={"dialogue_source": "tts"})
    assert again.status_code == 202 and again.json()["variant"] == j["variant"] and len(FakeProc.started) == 1
    v2.post("/api/episodes/2/cut-job", json={"dialogue_source": "tts"})
    c2 = FakeProc.started[1]
    assert c2[c2.index("--dialogue-source") + 1] == "tts"


def test_v1_cut_job_unchanged(v2, monkeypatch):
    monkeypatch.setattr(RP, "current_run", lambda root=None: "series10_v1")
    j = v2.post("/api/episodes/1/cut-job", json={"dialogue_source": "auto"}).json()
    assert j["engine"] == "assemble_episode" and FakeProc.started[0][1].endswith("assemble_episode.py")


def test_cli_argv_reaches_build(monkeypatch):
    """start_cut 拼的命令行能被 assemble_series 接住，进 build（再由 build 调 compose）"""
    from tools import assemble_series as AS
    seen = {}

    def fake_build(ep, variant="v1", **kw):
        seen.update(ep=ep, variant=variant, **kw)
        return {"output": "x", "complete": False, "video_shots": 0, "best_effort_shots": 0, "placeholder_shots": 0, "duration_s": 0}
    monkeypatch.setattr(AS, "build", fake_build)
    monkeypatch.setattr(sys, "argv", ["assemble_series.py", "ep03", "--variant", "UI1102-210000", "--dialogue-source", "tts"])
    assert AS.main() == 0
    assert seen["ep"] == 3 and seen["variant"] == "UI1102-210000" and seen["dialogue_source"] == "tts" and seen["preview"] is False


def test_compose_v2_takes_media_by_run_not_v1(monkeypatch, tmp_path):
    """compose 在 V2 下：音色 load_voice_config(run=series10_v2)、配乐 run_media.music_dir(series10_v2)，不读 V1 的配乐目录 / 音色表"""
    from tools import assemble_series as AS
    import ns_post.tts as TTS
    from ns_post import run_media as RM
    calls = []

    class Stop(Exception):
        pass

    def fake_voices(*a, run=None, **k):
        calls.append(("voices", run))
        return {"characters": {}}

    def fake_music_dir(run, root=None):
        calls.append(("music_dir", run))
        return tmp_path / "music" / str(run)

    def fake_check(run, ep, mdir, edit_file=None, root=None):
        calls.append(("check_music", run, Path(mdir).name))
        return {"checked": True, "track": None}

    def stop(*a, **k):
        raise Stop
    monkeypatch.setattr(AS, "RUN_ID", "series10_v2")
    monkeypatch.setattr(TTS, "load_voice_config", fake_voices)
    monkeypatch.setattr(RM, "music_dir", fake_music_dir)
    monkeypatch.setattr(RM, "check_episode_music", fake_check)
    monkeypatch.setattr(TTS, "KokoroBackend", stop)          # 拿到媒体后就停（不真的合成）
    with pytest.raises(Stop):
        AS.compose(1, {}, tmp_path / "w", "UI1102-210000")
    assert ("voices", "series10_v2") in calls and ("music_dir", "series10_v2") in calls
    assert ("check_music", "series10_v2", "series10_v2") in calls
    assert not any(c[1] in ("series10_v1", None) for c in calls)
    assert not any("series10" == str(c[-1]) for c in calls)                  # 没走 V1 的 data/music/series10


def test_preview_plan_without_hosts_json_uses_own_active_first(monkeypatch, tmp_path):
    """W41（11-04）：V2 还没派过视频（没有 video/hosts.json）→ 不抛 FileNotFoundError；占位首帧取本剧 takes.json 当前首帧，
    当前首帧不在本剧前缀下（跨剧 V1 版本，C-14）→ 不用"""
    import json
    from tools import assemble_series as AS
    vid = tmp_path / "vid"
    vid.mkdir()
    monkeypatch.setattr(AS, "VID", vid)
    monkeypatch.setattr(AS, "RUN", tmp_path / "run")
    monkeypatch.setattr(AS, "ROOT", tmp_path)
    monkeypatch.setattr(AS, "RUN_ID", "series10_v2")
    rd = tmp_path / "data/renders/series10_v2"
    monkeypatch.setattr(AS.RUNS, "renders_dir", lambda run, root=None: rd)
    sp = tmp_path / "script_v2.json"
    sp.write_text(json.dumps({"episodes": [{"number": 1, "shots": [{"index": 1}, {"index": 2}]}]}), encoding="utf-8")
    monkeypatch.setattr(AS.RUNS, "script_path", lambda run, root=None: sp)
    for s, f in (("S1", "renders/series10_v2/ep01/S1/takes/image_001.png"), ("S2", "renders/ep01/S2/takes/image_006.png")):
        (tmp_path / "data" / f).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / "data" / f).write_bytes(b"x")
        (rd / "ep01" / s).mkdir(parents=True, exist_ok=True)
        (rd / "ep01" / s / "takes.json").write_text(json.dumps(
            {"active": {"image": 1}, "takes": [{"stage": "image", "n": 1, "file": f}]}), encoding="utf-8")
    assert AS.hosts_all() == [] and AS.host_of(1) is None
    rows = AS.plan(1, AS.merged_state(False), best_effort_video=True)
    assert rows[0]["kind"] == "placeholder" and rows[0]["file"] == "data/renders/series10_v2/ep01/S1/takes/image_001.png"
    assert rows[1]["file"] is None          # V1 前缀的当前首帧不拿来占位


def test_cli_out_dir_reaches_build(monkeypatch):
    from tools import assemble_series as AS
    seen = {}

    def fake_build(ep, variant="v1", **kw):
        seen.update(kw)
        return {"output": "x", "complete": False, "video_shots": 0, "best_effort_shots": 0, "placeholder_shots": 0, "duration_s": 0}
    monkeypatch.setattr(AS, "build", fake_build)
    monkeypatch.setattr(sys, "argv", ["assemble_series.py", "ep01", "--preview", "--no-pull", "--out-dir", "data/_w41_trial/x"])
    assert AS.main() == 0
    assert str(seen["out_dir"]).replace("\\", "/").endswith("data/_w41_trial/x") and seen["preview"] is True
