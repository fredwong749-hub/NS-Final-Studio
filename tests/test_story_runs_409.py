"""L-159 双入口：旧单集接口（retry / resume / edit）对自动写作流程管着的剧一律 409，且拒绝前不动任何文件。

09:57 事故复现：series10_v2 根目录有 autoflow_ep02.json + P4_ep02.md，网页点“重试”→ P4 被挪进 superseded、状态卡 queued。
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


def _mkrun(root: Path, autoflow: bool) -> Path:
    d = root / "series_x"
    d.mkdir(parents=True)
    (d / "P0_brief.json").write_text("{}", encoding="utf-8")
    (d / "P4_ep02.md").write_text("## ep02\n现行稿", encoding="utf-8")
    (d / "P4_ep02.md.report.json").write_text(json.dumps({"status": "needs_writer"}), encoding="utf-8")
    if autoflow:
        (d / "autoflow_ep02.json").write_text(json.dumps({"run": "series_x", "episode": 2}), encoding="utf-8")
    return d


def _snapshot(d: Path) -> dict:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


@pytest.fixture
def client(tmp_path, monkeypatch):
    from ns_api import story_runs as SR
    monkeypatch.setattr(SR, "RUNS", tmp_path / "runs")
    started = []
    monkeypatch.setattr(SR, "_start", lambda run_id: started.append(run_id))
    app = FastAPI()
    app.include_router(SR.router)
    return TestClient(app), SR, tmp_path / "runs", started


@pytest.mark.parametrize("call", [
    lambda c: c.post("/api/story-runs/series_x/retry", json={"link": "P3-P4"}),
    lambda c: c.post("/api/story-runs/series_x/retry"),
    lambda c: c.post("/api/story-runs/series_x/resume"),
    lambda c: c.put("/api/story-runs/series_x/artifact/P4", json={"text": "改过的稿"}),
])
def test_autoflow_run_refused_without_side_effects(client, monkeypatch, call):
    c, SR, runs, started = client
    monkeypatch.setattr(SR, "writer_backend", lambda: "api")
    d = _mkrun(runs, autoflow=True)
    before = _snapshot(d)
    r = call(c)
    assert r.status_code == 409, r.text
    assert "自动写作流程" in r.json()["detail"]
    assert _snapshot(d) == before            # 一个文件都没挪、没写（含 ui_state.json 没生成）
    assert not (d / "superseded").exists()
    assert started == []


@pytest.mark.parametrize("path", ["retry", "resume"])
def test_claude_agent_backend_refused_before_moving(client, monkeypatch, path):
    """测试期写作走写手：原来 _start 里才 409，retry 已把稿挪进 superseded（09:57 的第二个根因）"""
    c, SR, runs, started = client
    monkeypatch.setattr(SR, "writer_backend", lambda: "claude_agent")
    d = _mkrun(runs, autoflow=False)
    before = _snapshot(d)
    r = c.post(f"/api/story-runs/series_x/{path}", json={"link": "P3-P4"})
    assert r.status_code == 409
    assert _snapshot(d) == before
    assert started == []


def test_plain_ui_run_still_retries(client, monkeypatch):
    """没有 autoflow 的普通网页运行，api 后端下照旧能重试（不误伤）"""
    c, SR, runs, started = client
    monkeypatch.setattr(SR, "writer_backend", lambda: "api")
    d = _mkrun(runs, autoflow=False)
    monkeypatch.setattr(SR, "_episode_of", lambda d, st: 2)
    r = c.post("/api/story-runs/series_x/retry", json={"link": "P3-P4"})
    assert r.status_code == 200, r.text
    assert started == ["series_x"]
    assert not (d / "P4_ep02.md").exists() and any((d / "superseded").rglob("P4_ep02.md"))
