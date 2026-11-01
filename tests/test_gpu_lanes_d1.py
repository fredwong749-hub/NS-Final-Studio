"""fredw-92/D1：卡道从 config/render_endpoints.json 的 gpus 表读（GPU1 = 第二条视频线 18189）；/api/jobs 并入 v1 任务。"""
from __future__ import annotations

import json

import pytest

from ns_api import jobs as J
from ns_render import endpoints as EP


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "render_endpoints.json"
    monkeypatch.setattr(EP, "CONFIG", p)
    for k in ("NS_COMFY_URL", "NS_COMFY_URL_GPU0", "NS_COMFY_URL_GPU1", "NS_COMFY_URL_GPU3"):
        monkeypatch.delenv(k, raising=False)
    return p


def test_default_lanes_without_gpu1(cfg):
    assert tuple(J.GPUS) == (0, 3)
    assert 1 not in J.GPUS and 3 in J.GPUS and 0 in J.GPUS
    assert "x" not in J.GPUS and None not in J.GPUS
    with pytest.raises(ValueError):
        EP.url_for_gpu(1)


def test_gpu1_lane_from_config(cfg, monkeypatch):
    cfg.write_text(json.dumps({"gpus": {"0": "http://127.0.0.1:18188", "1": "http://127.0.0.1:18189",
                                        "3": "http://127.0.0.1:18191"}}), encoding="utf-8")
    assert tuple(J.GPUS) == (0, 1, 3) and 1 in J.GPUS
    assert str(J.GPUS) == "(0, 1, 3)"
    from ns_api import llm_config as LC
    monkeypatch.setattr(LC, "saved_render_url", lambda gpu: None)
    assert J.comfy_url(1) == "http://127.0.0.1:18189"
    assert J.comfy_url(3) == "http://127.0.0.1:18191"


def test_video_job_accepts_gpu1(cfg):
    from fastapi import HTTPException
    from ns_api import video_jobs as VJ
    with pytest.raises(HTTPException):
        VJ._validate(VJ.VideoJobRequest(gpu=1))
    cfg.write_text(json.dumps({"gpus": {"1": "http://127.0.0.1:18189"}}), encoding="utf-8")
    VJ._validate(VJ.VideoJobRequest(gpu=1))   # 不抛
    with pytest.raises(HTTPException):
        VJ._validate(VJ.VideoJobRequest(gpu=2))


def test_api_jobs_lists_v1_jobs(monkeypatch):
    from ns_api import app as A
    fake = [{"id": "v1a", "job_id": "v1a", "kind": "video", "shot_id": "ep02-S1", "gpu": 1, "state": "running",
             "created_at": "2026-10-31T01:00:00", "error": None},
            {"id": "v1b", "job_id": "v1b", "kind": "frame", "stage": "first", "shot_id": "ep02-S3", "gpu": 0,
             "state": "queued", "created_at": "2026-10-31T01:01:00", "error": None}]
    monkeypatch.setattr(A.JOBS, "all_jobs", lambda shot_id=None: [dict(j) for j in fake])
    out = A.jobs()
    by = {j["id"]: j for j in out}
    assert by["v1a"]["v1"] is True and by["v1a"]["stage"] == "video"
    assert by["v1b"]["stage"] == "image"
    assert [j["id"] for j in out][:2] == ["v1b", "v1a"]


def test_h3_frames_not_capped():
    """fredw-92/LS 取代 D1 的 192 帧上限：帧数按剧本时长，超道上限的改派长镜头道（tests/test_longshot_ls.py）"""
    from ns_render import h3_video as HV
    from ns_schema.h3_lint import frames_for_seconds
    assert HV.frames_for(12) == (frames_for_seconds(12), frames_for_seconds(12)) == (294, 294)
