"""ns_agent.comfy_tag：GPU 任务归属标签（GPUVIEW，K-OPS-G01）"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "services" / "agent"))

from ns_agent import comfy_tag as CT  # noqa: E402


def test_make_drops_empty_fields():
    t = CT.make("VIDEO10", "video", episode=1, shot="S6", label="Ref2VA 24 步", attempt=2, obj="", job=None)
    assert t["agent"] == "VIDEO10" and t["kind"] == "video" and t["episode"] == 1 and t["shot"] == "S6"
    assert t["attempt"] == 2 and t["label"] == "Ref2VA 24 步"
    assert "obj" not in t and "job" not in t


def test_attach_keeps_client_id_and_existing_extra():
    body = {"prompt": {}, "client_id": "video10-abc", "extra_data": {"foo": 1}}
    tag = CT.make("VIDEO10", "video")
    out = CT.attach(body, tag)
    assert out is body
    assert body["client_id"] == "video10-abc"
    assert body["extra_data"] == {"foo": 1, "ns_tag": tag}
    b2 = {"prompt": {}, "client_id": "x"}
    CT.attach(b2, None)
    assert "extra_data" not in b2


def test_read():
    tag = CT.make("BAKEOFF", "bakeoff", idx=212, total=391)
    assert CT.read({"client_id": "x", "ns_tag": tag}) == tag
    assert CT.read({"client_id": "x"}) is None
    assert CT.read({"ns_tag": {"kind": "video"}}) is None     # 没 agent 不算
    assert CT.read(None) is None


def _video_prompt():
    return {"1": {"class_type": "UNETLoader", "inputs": {"unet_name": "minimax_h3_ref2va_fp8.safetensors"}},
            "2": {"class_type": "BasicScheduler", "inputs": {"steps": 24}},
            "3": {"class_type": "SaveVideo", "inputs": {"filename_prefix": "video10/ep01-S6/b24"}}}


def test_infer_video10():
    t = CT.infer(_video_prompt(), {"client_id": "video10-1234abcd"})
    assert t["agent"] == "VIDEO10" and t["kind"] == "video"
    assert t["episode"] == 1 and t["shot"] == "S6"
    assert t["inferred"] is True and t["family"] == "Ref2VA"


def test_tag_of_prefers_ns_tag_and_adds_steps():
    tag = CT.make("VIDEO10", "video", episode=1, shot="S6", attempt=2)
    t = CT.tag_of(_video_prompt(), {"client_id": "video10-x", "ns_tag": tag})
    assert t["agent"] == "VIDEO10" and "inferred" not in t and t["steps"] == 24 and t["family"] == "Ref2VA"


def test_describe():
    s = CT.describe(CT.make("IMGGEN", "first_frame", episode=3, shot="S4", attempt=3))
    assert s == "出首帧 · 第3集 S4 · 第2次重试"
    s = CT.describe(CT.make("BAKEOFF", "bakeoff", idx=212, total=391))
    assert "模型对比 BAKEOFF" in s and "第 212/391 张" in s
    s = CT.describe(CT.tag_of(_video_prompt(), {"client_id": "video10-x"}))
    assert s.startswith("未标记任务") and "第1集 S6" in s


def test_heartbeat_roundtrip(tmp_path):
    p = CT.heartbeat("VOICE10", "试听音色 · 林晚 候选3", kind="voice", server="gpu36", gpu=1, step=3, steps=10,
                     hb_id="t1", directory=tmp_path)
    assert p.exists()
    CT.heartbeat_done("VOICE10", hb_id="t1", directory=tmp_path)
    assert not p.exists()


def test_ns_api_job_tag():
    sys.path.insert(0, str(ROOT / "services" / "api"))
    sys.path.insert(0, str(ROOT / "services" / "render_router"))
    from ns_api import jobs as J
    t = J._ns_tag({"id": "abc123", "kind": "frame", "stage": "last", "shot_id": "ep02-S4", "mode": "regen"})
    assert t["agent"] == "ns_api" and t["kind"] == "last_frame" and t["episode"] == 2 and t["shot"] == "S4"
    assert t["job"] == "abc123"
    t = J._ns_tag({"id": "v", "kind": "video", "shot_id": "ep01-S2"})
    assert t["kind"] == "video" and t["episode"] == 1
