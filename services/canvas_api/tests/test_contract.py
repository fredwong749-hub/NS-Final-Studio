"""gpu3 渲染桥契约测试：take 布局读取、旧布局兼容、weita 对照、队列只追加 + 取消 + 事件、Range、抽尾帧。"""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_canvas.app import create_app
from ns_canvas.config import RootCfg, Settings

FFMPEG = os.environ.get("NSC_FFMPEG") or shutil.which("ffmpeg")
P = "/api/gpu3"


@pytest.fixture
def env(tmp_path: Path):
    data = tmp_path / "data"
    rg = data / "renders_gpu3"
    s1 = rg / "ep01" / "S1"
    (s1 / "takes").mkdir(parents=True)
    for n in (1, 2):
        (s1 / "takes" / f"image_00{n}.png").write_bytes(b"\x89PNG" + bytes(range(200)))
    takes = {"takes": [
        {"n": 1, "stage": "image", "file": "renders_gpu3/ep01/S1/takes/image_001.png", "seed": 11, "prompt": "旧",
         "created_at": "2026-10-30T01:00:00Z", "workflow": "qwen_t2i"},
        {"n": 2, "stage": "image", "file": "renders_gpu3/ep01/S1/takes/image_002.png", "seed": 22, "prompt": "新",
         "created_at": "2026-10-30T02:00:00Z", "workflow": "qwen_t2i", "request_id": "abc", "input_hash": "h2",
         "qc": {"face": {"verdict": "pass", "score": 0.93}, "text": "fail"}},
    ], "active": {"image": 2, "video": None}}
    if FFMPEG:
        subprocess.run([FFMPEG, "-v", "error", "-f", "lavfi", "-i", "testsrc=size=64x112:rate=24:duration=1",
                        "-pix_fmt", "yuv420p", str(s1 / "takes" / "video_001.mp4")], check=True)
        takes["takes"].append({"n": 1, "stage": "video", "file": "renders_gpu3/ep01/S1/takes/video_001.mp4", "seed": 5,
                               "prompt": "v", "created_at": "2026-10-30T03:00:00Z", "frames": 24})
        takes["active"]["video"] = 1
    (s1 / "takes.json").write_text(json.dumps(takes, ensure_ascii=False), encoding="utf-8")
    s2 = rg / "ep01" / "S2"
    s2.mkdir(parents=True)
    (s2 / "frame.png").write_bytes(b"\x89PNG legacy")
    (s2 / "status.json").write_text(json.dumps({"image": {"ok": True, "seed": 77, "seconds": 30}, "video": {"ok": False, "error": "OOM"}}))
    weita = tmp_path / "weita"
    (weita / "ep01" / "frames").mkdir(parents=True)
    (weita / "ep01" / "frames" / "ep01s1.png").write_bytes(b"\x89PNG w")
    (weita / "ep01" / "frames" / "ep01s1.last.png").write_bytes(b"\x89PNG wl")
    (weita / "manifest.jsonl").write_text("\n".join(json.dumps(x) for x in [
        {"kind": "frame_locked", "shot_id": "ep01s1", "candidate": "c3", "seed": 999, "at": "2026-10-29T14:00:00Z"},
        {"kind": "frame_scores", "shot_id": "ep01s1", "scores": {"ep01s1_c3": {"qc": "pass", "qc_reasons": [], "similarity": 0.9}}},
    ]))
    script = data / "import" / "script_v2.json"
    script.parent.mkdir(parents=True)
    script.write_text(json.dumps({"episodes": [{"number": 1, "shots": [{"index": i} for i in (1, 2, 3)]}]}))
    settings = Settings(queue_dir=rg, roots=[RootCfg("renders_gpu3", "takes", rg), RootCfg("weita", "weita", weita)],
                        cache_dir=tmp_path / "cache", script_json=script, ffmpeg=FFMPEG or "ffmpeg")
    return TestClient(create_app(settings)), tmp_path


def test_takes_layout(env):
    c, _ = env
    s = c.get(f"{P}/shots/ep01-S1").json()
    imgs = [t for t in s["takes"] if t["source"] == "renders_gpu3" and t["stage"] == "image"]
    assert [t["n"] for t in imgs] == [1, 2] and [t["active"] for t in imgs] == [False, True]
    t2 = imgs[1]
    assert t2["file"] == "renders_gpu3/ep01/S1/takes/image_002.png"
    assert t2["url"] == f"{P}/media/renders_gpu3/ep01/S1/takes/image_002.png"
    assert t2["thumb"].startswith(f"{P}/thumb/") and t2["seed"] == 22 and t2["input_hash"] == "h2"
    assert {(q["check"], q["verdict"]) for q in t2["qc"]} == {("face_eyes", "pass"), ("text", "fail")}
    assert s["active"]["image"] == 2 and s["status"] == "done"
    w = [t for t in s["takes"] if t["source"] == "weita"]
    assert w[0]["seed"] == 999 and w[0]["last_target_url"].endswith("ep01s1.last.png") and w[0]["qc"][0]["score"] == 0.9


def test_legacy_layout_and_episode(env):
    c, _ = env
    ep = c.get(f"{P}/episodes/1").json()
    assert [x["shot"] for x in ep] == ["ep01-S1", "ep01-S2", "ep01-S3"]
    s2 = ep[1]
    assert s2["takes"][0]["file"] == "renders_gpu3/ep01/S2/frame.png" and s2["takes"][0]["seed"] == 77
    assert s2["error"] == "视频: OOM"
    assert ep[2]["takes"] == [] and ep[2]["status"] == "none"


def test_queue_contract(env):
    c, tmp = env
    r = c.post(f"{P}/rerender", json={"shot": "ep1-s1", "stage": "video", "keep_seed": True, "seed": 5,
                                      "edit": {"camera": "camera push in"}, "compiled": {"video_prompt": "x"},
                                      "input_hash": "h9", "overrides": {"frames": 158}}).json()
    assert not r["errors"]
    rid = r["requests"][0]["id"]
    line = json.loads((tmp / "data/renders_gpu3/rerender_queue.jsonl").read_text(encoding="utf-8").splitlines()[-1])
    assert line["schema"] == "nsfs_canvas.rerender/v1" and line["shot"] == "ep01-S1" and line["stage"] == "video"
    assert line["keep_seed"] and line["seed"] == 5 and line["edit"]["camera"] == "camera push in" and line["input_hash"] == "h9"
    assert c.get(f"{P}/shots/ep01-S1").json()["status"] == "queued"
    b = c.post(f"{P}/rerender", json=[{"shot": "ep01-S2", "stage": "image"}, {"shot": "ep01-S9", "stage": "image"}]).json()
    assert len(b["requests"]) == 1 and b["errors"][0]["shot"] == "ep01-S9"
    c.post(f"{P}/queue/{b['requests'][0]['id']}/cancel")
    st = {x["id"]: x["state"] for x in c.get(f"{P}/queue").json()}
    assert st[b["requests"][0]["id"]] == "cancelled"
    assert c.post(f"{P}/queue/{b['requests'][0]['id']}/cancel").status_code == 422
    c.post(f"{P}/queue/events", json={"id": rid, "state": "started", "worker": "gpu0"})
    assert c.get(f"{P}/shots/ep01-S1").json()["status"] == "rendering"
    assert c.post(f"{P}/queue/{rid}/cancel").status_code == 422
    c.post(f"{P}/queue/events", json={"id": rid, "state": "done", "take": {"stage": "video", "n": 2}})
    q = c.get(f"{P}/queue", params={"shot": "ep01-S1"}).json()[0]
    assert q["state"] == "done" and q["takes"] == [{"stage": "video", "n": 2}]
    assert c.post(f"{P}/queue/events", json={"id": "nope", "state": "done"}).status_code == 404
    events = (tmp / "data/renders_gpu3/rerender_events.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(events) == 2


def test_media_range_and_safety(env):
    c, _ = env
    r = c.get(f"{P}/media/renders_gpu3/ep01/S1/takes/image_002.png", headers={"Range": "bytes=0-9"})
    assert r.status_code == 206 and len(r.content) == 10
    assert c.get(f"{P}/media/renders_gpu3/../../etc/passwd").status_code in (403, 404)
    assert c.get(f"{P}/media/unknown/x.png").status_code == 404


@pytest.mark.skipif(not FFMPEG, reason="没有 ffmpeg")
def test_last_frame_from_video(env):
    c, _ = env
    s = c.get(f"{P}/shots/ep01-S1").json()
    v = next(t for t in s["takes"] if t["stage"] == "video" and t["source"] == "renders_gpu3")
    assert v["last_frame_url"] == f"{P}/shots/ep01-S1/takes/renders_gpu3/video/1/last.png"
    r = c.get(v["last_frame_url"])
    assert r.status_code == 200 and r.content[:4] == b"\x89PNG"
    assert c.get(v["last_frame_url"], params={"w": 32}).content[:2] == b"\xff\xd8"
    assert c.get(v["url"], headers={"Range": "bytes=0-99"}).status_code == 206
    assert c.get(f"{P}/shots/ep01-S1/takes/renders_gpu3/video/9/last.png").status_code == 404


def test_parse_qc_real_shapes():
    from ns_canvas.sources import parse_qc
    q = {"face": {"verdict": "warn", "score": 0.908, "reasons": ["1 sampled frame(s) with broken-face evidence"]},
         "decoration": {"clothed": {"ok": True, "answer": "{\"衣着完整\": true}"}},
         "drift": {"first_frame_psnr": 33.41, "end_identity": 0.091},
         "fail": ["QC: 2 sampled frame(s) with broken-face evidence"], "override": "VLM facing=false overruled",
         "text": "pass", "heels": {"heels": "透明高跟 true"}, "empty": []}
    got = {x.check: x for x in parse_qc(q)}
    assert got["face_eyes"].verdict == "warn" and got["face_eyes"].score == 0.908
    assert got["decoration"].verdict == "pass"
    assert got["drift"].verdict == "unknown" and any("end_identity" in r for r in got["drift"].reasons)
    assert got["fail"].verdict == "fail" and got["text"].verdict == "pass"
    assert got["override"].verdict == "unknown" and "overruled" in got["override"].reasons[0]
    assert got["heels"].verdict == "unknown" and "empty" not in got
    assert parse_qc({"decoration": {"clothed": {"ok": False}}})[0].verdict == "fail"
    assert parse_qc(None) == [] and parse_qc("x") == []
