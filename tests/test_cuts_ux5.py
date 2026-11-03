"""UX5 成片页接口：/api/episodes/{n}/cuts 与 /api/episodes/{n}/cut-job。

临时项目根；合成子进程用假的 Popen 代替（不真的装配、不碰 GPU），只验证：
列表 / 时间线摘要 / “成片之后哪几镜换了定稿”、命令一律带 --variant（不覆盖原成片）、同集并发 409、参数校验。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ns_render import pipeline as P


def _w(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False), encoding="utf-8")


class FakeProc:
    started: list[list[str]] = []

    def __init__(self, cmd, cwd=None, stdout=None, stderr=None):
        FakeProc.started.append(list(cmd))
        self.returncode = None

    def poll(self):
        return self.returncode


@pytest.fixture
def client(tmp_path, monkeypatch):
    from ns_api import cuts as C
    monkeypatch.setattr(P, "ROOT", tmp_path)
    monkeypatch.setattr(P, "DATA", tmp_path / "data")
    monkeypatch.setattr(P, "RENDERS", tmp_path / "data" / "renders")
    monkeypatch.setattr(C.subprocess, "Popen", FakeProc)
    C.JOBS.clear()
    FakeProc.started.clear()
    ep = tmp_path / "data" / "episodes"
    _w(ep / "ep02_v1.mp4", "x")
    _w(ep / "ep02_v1.timeline.json", {"duration_s": 81.4, "preview": True, "settings": {"dialogue_source": "h3"},
                                      "warnings": ["w1", "w2"], "shots": [
        {"shot": "ep02-S1", "kind": "video", "file": "data/renders/ep02/S1/takes/video_003_aa_cc.mp4"},
        {"shot": "ep02-S2", "kind": "video", "file": "data/renders/ep02/S2/takes/video_001_bb.mp4"},
        {"shot": "ep02-S3", "kind": "still", "placeholder": True, "file": None}]})
    _w(ep / "ep02_PREVIEW_未完成_勿用.mp4", "y")
    _w(ep / "ep12_v1.mp4", "z")                       # 别的集不算
    # S1：定稿还是成片里那一版（_cc 校色副本算同一版）；S2：定稿换成了 #2
    _w(tmp_path / "data" / "renders" / "ep02" / "S1" / "takes.json", {
        "takes": [{"n": 3, "stage": "video", "file": "renders/ep02/S1/takes/video_003_aa.mp4"}],
        "locked": {"video": 3}, "active": {"video": 3}})
    _w(tmp_path / "data" / "renders" / "ep02" / "S2" / "takes.json", {
        "takes": [{"n": 1, "stage": "video", "file": "renders/ep02/S2/takes/video_001_bb.mp4"},
                  {"n": 2, "stage": "video", "file": "renders/ep02/S2/takes/video_002_cc9.mp4"}],
        "locked": {"video": 2}, "active": {"video": 2}})
    app = FastAPI()
    app.include_router(C.router)
    return TestClient(app)


def test_list_cuts_summary_and_changed(client):
    r = client.get("/api/episodes/2/cuts").json()
    names = [c["name"] for c in r["cuts"]]
    assert set(names) == {"ep02_v1.mp4", "ep02_PREVIEW_未完成_勿用.mp4"}
    v1 = next(c for c in r["cuts"] if c["name"] == "ep02_v1.mp4")
    assert v1["url"].startswith("/files/episodes/ep02_v1.mp4")
    assert v1["timeline"]["duration_s"] == 81.4 and v1["timeline"]["warnings"] == 2
    assert v1["timeline"]["missing"] == ["ep02-S3"] and v1["timeline"]["dialogue_source"] == "h3"
    assert [c["shot_id"] for c in v1["changed"]] == ["ep02-S2"]
    assert v1["changed"][0]["current_locked"] is True
    bad = next(c for c in r["cuts"] if c["name"] != "ep02_v1.mp4")
    assert "勿用" in bad["tags"] and "预览" in bad["tags"] and bad["timeline"] is None
    assert r["job"] is None


def test_cut_job_always_variant_and_no_concurrency(client, tmp_path):
    j = client.post("/api/episodes/2/cut-job", json={"dialogue_source": "h3", "by": "owner"}).json()
    assert j["state"] == "running" and j["variant"].startswith("UI")
    cmd = FakeProc.started[0]
    assert cmd[1].endswith("assemble_episode.py") and cmd[2] == "ep02"
    assert cmd[cmd.index("--variant") + 1] == j["variant"]                 # 一律另存对照版，不覆盖原成片
    assert cmd[cmd.index("--dialogue-source") + 1] == "h3"
    assert "--upscale-4k" not in cmd                                        # 不碰 GPU
    again = client.post("/api/episodes/2/cut-job")                           # 同集同时只跑一个：原样返回那个任务（202 收下，不退回）
    assert again.status_code == 202 and again.json()["variant"] == j["variant"] and len(FakeProc.started) == 1
    assert client.post("/api/episodes/3/cut-job").status_code == 202        # 别的集可以
    assert (tmp_path / "data" / "episodes" / "ep02_v1.mp4").read_text(encoding="utf-8") == "x"


def test_cut_job_status_and_validation(client):
    from ns_api import cuts as C
    assert client.get("/api/episodes/2/cut-job").json()["state"] == "none"
    assert client.post("/api/episodes/2/cut-job", json={"dialogue_source": "abc"}).status_code == 422
    client.post("/api/episodes/2/cut-job", json={})
    C.JOBS[2]["proc"].returncode = 0
    assert client.get("/api/episodes/2/cut-job").json()["state"] == "done"
    assert client.post("/api/episodes/2/cut-job").status_code == 202        # 跑完可以再合成
