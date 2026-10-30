"""项目进度 / 系列控制标记 / GPU 状态 / 新项目路径。"""
import json
import stat
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_canvas.app import create_app
from ns_canvas.config import RootCfg, Settings

P = "/api/gpu3"


def jl(p: Path, rows):
    p.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8")


def take(stage, n, file, active=True):
    return {"n": n, "stage": stage, "file": file, "seed": 1, "prompt": "", "created_at": "2026-10-30T00:00:00Z"}


@pytest.fixture
def env(tmp_path: Path):
    data = tmp_path / "data"
    base = data / "renders_gpu3"
    out = tmp_path / "weita"                      # 系列渲染器工作目录
    # ep01：S1 首帧+视频（take 布局，带 4K take），S2 只有首帧（旧布局）+ weita clips 里有视频
    s1 = base / "ep01" / "S1" / "takes"
    s1.mkdir(parents=True)
    for f in ("image_001.png", "video_001.mp4", "video_001_4k.mp4"):
        (s1 / f).write_bytes(b"x")
    (s1.parent / "takes.json").write_text(json.dumps({"takes": [
        take("image", 1, "renders_gpu3/ep01/S1/takes/image_001.png"),
        take("video", 1, "renders_gpu3/ep01/S1/takes/video_001.mp4")], "active": {"image": 1, "video": 1}}))
    (base / "ep01" / "S2").mkdir(parents=True)
    (base / "ep01" / "S2" / "frame.png").write_bytes(b"x")
    (base / "ep01" / "S2" / "errors.json").write_text(json.dumps({"last": "CUDA OOM"}))
    (base / "ep01" / "S1.superseded_x").mkdir()
    (base / "ep01" / "ep01_final.mp4").write_bytes(b"final")
    (base / "ep01" / "S1" / "audio").mkdir()
    (base / "ep01" / "S1" / "audio" / "stems.json").write_text("{}")
    (data / "episodes").mkdir(parents=True)
    (data / "episodes" / "ep03_4k.mp4").write_bytes(b"x")
    (base / "ep01" / "ep01_4k.mp4").write_bytes(b"4k")
    (out / "ep01" / "clips").mkdir(parents=True)
    (out / "ep01" / "clips" / "ep01s2.mp4").write_bytes(b"x")
    (out / "ep01" / "assembly").mkdir()
    (out / "ep01" / "assembly" / "voiceover.json").write_text("[]")
    (out / "ep01" / "assembly" / "vo_ep01-S1_0.wav").write_bytes(b"x")
    (out / "ep01" / "QA_PASS").write_text("ok")
    (base / "ep02").mkdir()
    (base / "ep02" / "qa.json").write_text(json.dumps({"verdict": "fail", "issues": ["S3 鞋不对"], "by": "qa-agent"}))
    (out / "STATUS.log").write_text("[ep01] ⚠️ 出图6/6 | first\n[ep01] ✅ 出图6/6(重试0) | 视频6/6\n[ep02] ⛔ 暂停\n", encoding="utf-8")
    jl(out / "HARD_SHOTS.jsonl", [{"shot": "ep02-S5", "wrong": ["VLM back_view false"]}])
    jl(out / "BLOCKED.jsonl", [{"shot": "ep02-S6", "reason": "身份相似度 0.2"}])
    jl(out / "WORKER_ERRORS.jsonl", [{"item": "ep02-S1", "slot": "gpu3", "error": "RuntimeError: boom"}])
    music = data / "music"
    music.mkdir()
    (music / "ep01.wav").write_bytes(b"x")
    script = data / "import" / "script_v2.json"
    script.parent.mkdir(parents=True)
    script.write_text(json.dumps({"episodes": [{"number": n, "title": f"第{n}集", "shots": [{"index": i} for i in range(1, 7)]}
                                               for n in (1, 2, 3)]}, ensure_ascii=False), encoding="utf-8")
    bench = tmp_path / "bench.csv"
    bench.write_text("at,shot,kind,route,slot,gpu_seconds,vram_peak_mb,size,frames,steps,ok\n"
                     "t,ep01-S1,frame,turbo,gpu0,30,1,x,,8,True\nt,ep01-S1,frame,turbo,gpu0,10,1,x,,8,True\n"
                     "t,ep01-S2,frame,turbo,gpu0,60,1,x,,8,True\nt,ep01-S2,frame,turbo,gpu0,999,1,x,,8,False\n"
                     "t,ep01-S1,video,h3,gpu0,1000,1,x,243,8,True\n")
    locks = tmp_path / "locks"
    locks.mkdir()
    (locks / "gpu.lock.gpu3").write_text("pid:999999 owner_script_render:frame:ep05s1:c2")
    (locks / "gpu.lock.gpu0").write_text("pid:999998 weita-v3-llm (v3 script LLM, lend.gpu0)")
    (locks / "lend.gpu0").write_text("weita-v3-llm (GPU0 for the v3 script LLM)")
    (locks / "train.lock.1").write_text("lw-lora-train.service")
    smi = tmp_path / "fake-smi"
    smi.write_text("#!/bin/sh\ncase \"$1\" in\n"
                   "  --query-gpu*) printf '0, GPU-a, RTX 3090, 20000, 24576, 97\\n1, GPU-b, RTX 3090, 100, 24576, 0\\n"
                   "2, GPU-c, RTX 3090, 18, 24576, 0\\n3, GPU-d, RTX 3090, 23000, 24576, 100\\n';;\n"
                   "  --query-compute-apps*) printf 'GPU-d, 4242, /usr/bin/python3, 22000\\n';;\nesac\n")
    smi.chmod(smi.stat().st_mode | stat.S_IEXEC)
    # 新项目
    nd = base / "newdrama"
    (nd / "ep01" / "S1" / "takes").mkdir(parents=True)
    (nd / "ep01" / "S1" / "takes" / "image_001.png").write_bytes(b"\x89PNG")
    (nd / "ep01" / "S1" / "takes.json").write_text(json.dumps({"takes": [take("image", 1, "renders_gpu3/newdrama/ep01/S1/takes/image_001.png")],
                                                               "active": {"image": 1}}))
    (nd / "script.json").write_text(json.dumps({"episodes": [{"number": 1, "title": "新剧", "shots": [{"index": 1}, {"index": 2}]}]}))
    # projects/<slug>/data/import/script_v2.json 优先于 renders_gpu3/<slug>/script.json
    projects = tmp_path / "projects"
    (projects / "newdrama" / "data" / "import").mkdir(parents=True)
    (projects / "newdrama" / "data" / "import" / "script_v2.json").write_text(json.dumps({"episodes": [
        {"number": 1, "title": "新剧（向导导入）", "shots": [{"index": 1}, {"index": 2}, {"index": 3}]}]}, ensure_ascii=False), encoding="utf-8")
    (base / "fallback").mkdir()
    (base / "fallback" / "script.json").write_text(json.dumps({"episodes": [{"number": 1, "title": "回退", "shots": [{"index": 1}]}]}, ensure_ascii=False), encoding="utf-8")
    settings = Settings(queue_dir=base, projects_root=projects, roots=[RootCfg("renders_gpu3", "takes", base)], cache_dir=tmp_path / "cache",
                        script_json=script, renders_base=base, series_out=out, bench_csv=bench, music_dir=music,
                        lock_dir=locks, nvidia_smi=str(smi), comfy={0: "http://127.0.0.1:9", 1: "http://127.0.0.1:9", 3: "http://127.0.0.1:9"})
    return TestClient(create_app(settings)), tmp_path


def test_project_episodes_weita(env):
    c, _ = env
    d = c.get(f"{P}/projects/weita/episodes").json()
    assert [e["ep"] for e in d["episodes"]] == [1, 2, 3]
    e1, e2, e3 = d["episodes"]
    assert e1["frames"] == {"done": 2, "total": 6} and e1["videos"] == {"done": 2, "total": 6}
    assert e1["final"]["exists"] and e1["eta_s"] == 0
    assert e1["upscale_4k"]["state"] == "done" and e1["upscale_4k"]["shots_4k"] == 1
    assert e1["audio"]["voiceover"] and e1["audio"]["voiceover_wavs"] == 1 and e1["audio"]["music"].endswith("ep01.wav")
    assert e1["audio"]["stems_shots"] == 1 and e1["audio"]["music_cues"] is False
    assert e3["upscale_4k"]["state"] == "done" and e3["upscale_4k"]["file"].endswith("ep03_4k.mp4")
    assert e1["qa"]["state"] == "pass"                                  # QA_PASS 优先于 STATUS.log
    assert e1["status_line"].startswith("[ep01] ✅")                     # 取该集最后一行
    assert any("CUDA OOM" in x for x in e1["errors"])
    assert e2["qa"]["state"] == "fail" and e2["qa"]["issues"] == ["S3 鞋不对"]   # qa.json 优先
    assert e2["hard_shots"] == 1 and e2["blocked"] == 1
    assert any(x.startswith("WORKER ep02-S1") for x in e2["errors"])
    # ETA：每镜首帧 =(40+60)/2=50，视频=1000（bench 实测），正在出片的卡 1 张（gpu3；gpu0 是 LLM）
    per = d["eta"]["per_shot"]
    assert per["frame"]["seconds_per_shot"] == 50 and per["video"]["seconds_per_shot"] == 1000
    assert d["eta"]["active_gpus"] == 1
    assert e3["eta_s"] == 6 * 50 + 6 * 1000 and e3["qa"]["state"] == "none"
    assert d["eta"]["total_s"] == e2["eta_s"] + e3["eta_s"]


def test_series_control(env):
    c, tmp = env
    base = tmp / "data" / "renders_gpu3"
    r = c.post(f"{P}/projects/weita/series", json={"action": "pause", "episodes": [3, 2, 3], "by": "fredw-d9"}).json()
    assert r["action"] == "pause" and r["episodes"] == [2, 3]
    for p in (base / "weita" / "series_control.json", base / "series_control.json"):
        m = json.loads(p.read_text(encoding="utf-8"))
        assert m["action"] == "pause" and m["by"] == "fredw-d9" and m["at"]
    assert c.get(f"{P}/projects/weita/series").json()["action"] == "pause"
    assert c.get(f"{P}/projects/weita/episodes").json()["control"]["action"] == "pause"
    c.post(f"{P}/projects/newdrama/series", json={"action": "start"})
    assert json.loads((base / "newdrama" / "series_control.json").read_text())["episodes"] is None
    assert len((base / "series_control.log.jsonl").read_text().splitlines()) == 1
    assert m["adult_content"] is False
    r = c.post(f"{P}/projects/newdrama/series", json={"action": "start", "adult_content": True}).json()
    assert r["adult_content"] is True
    assert json.loads((base / "newdrama" / "series_control.json").read_text())["adult_content"] is True
    assert json.loads((base / "newdrama" / "series_control.log.jsonl").read_text().splitlines()[-1])["adult_content"] is True
    for bad in ("yes", 1, "true", None):
        assert c.post(f"{P}/projects/newdrama/series", json={"action": "start", "adult_content": bad}).status_code == 422
    assert c.post(f"{P}/projects/weita/series", json={"action": "explode"}).status_code == 422
    assert c.post(f"{P}/projects/Bad Slug/series", json={"action": "stop"}).status_code == 422
    assert c.post(f"{P}/projects/nosuch/series", json={"action": "stop"}).status_code == 404


def test_new_project_paths(env):
    c, tmp = env
    ep = c.get(f"{P}/episodes/1", params={"project": "newdrama"}).json()
    assert [x["shot"] for x in ep] == ["ep01-S1", "ep01-S2", "ep01-S3"]
    t = ep[0]["takes"][0]
    assert t["file"] == "renders_gpu3/newdrama/ep01/S1/takes/image_001.png"
    assert t["url"] == f"{P}/media/renders_gpu3/newdrama/ep01/S1/takes/image_001.png"
    assert c.get(t["url"]).status_code == 200
    d = c.get(f"{P}/projects/newdrama/episodes").json()
    assert d["episodes"][0]["frames"] == {"done": 1, "total": 3} and d["episodes"][0]["title"] == "新剧（向导导入）"
    fb = c.get(f"{P}/projects/fallback/episodes").json()["episodes"][0]
    assert fb["title"] == "回退" and fb["shots"] == 1
    r = c.post(f"{P}/rerender", json={"project": "newdrama", "shot": "ep01-S2", "stage": "image"}).json()
    assert not r["errors"] and r["requests"][0]["project"] == "newdrama"
    assert c.post(f"{P}/rerender", json={"project": "newdrama", "shot": "ep01-S5"}).json()["errors"]
    assert c.get(f"{P}/shots/ep01-S2", params={"project": "newdrama"}).json()["status"] == "queued"
    assert c.get(f"{P}/shots/ep01-S2").json()["status"] != "queued"        # 默认项目不受影响


@pytest.mark.skipif(sys.platform.startswith("win"), reason="假 nvidia-smi 是 sh 脚本")
def test_gpus(env):
    c, _ = env
    g = {x["id"]: x for x in c.get(f"{P}/gpus").json()}
    assert sorted(g) == [0, 1, 2, 3]
    assert g[2]["faulty"] and "never used" in g[2]["note"] and g[2]["busy_by"] is None
    assert g[3]["busy_by"] == "owner_script_render:frame:ep05s1:c2" and g[3]["vram_used_mb"] == 23000 and g[3]["util"] == 100
    assert g[3]["processes"][0]["pid"] == 4242 and g[3]["lock_file"]["pid_alive"] is False
    assert g[0]["busy_by"] == "weita-v3-llm" and g[0]["lend_file"]["text"].startswith("weita-v3-llm")
    assert g[1]["train_lock"]["text"] == "lw-lora-train.service" and g[1]["busy_by"] == "lw-lora-train.service"
    assert g[0]["comfy"]["error"] == "unreachable"


def test_scheduler_plan_read_only(env):
    c, tmp = env
    assert c.get(f"{P}/scheduler").json() == {"mode": None}
    g = {x["id"]: x for x in c.get(f"{P}/gpus").json()}
    assert g[0]["scheduler"] is None
    lock_dir = tmp / "locks"
    plan = {"schema": "ns_sched.plan/v1", "at": "2026-10-30T02:16:51Z", "mode": "dry-run",
            "gpus": [{"gpu": 0, "assigned": "weita-v3", "stage": "S1", "locked": True, "why": "持锁",
                      "next_at_boundary": ["lw-img-lora", "pose-lora", "lw-lora", "x"]}]}
    (lock_dir / "scheduler_plan.json").write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
    assert c.get(f"{P}/scheduler").json()["mode"] == "dry-run"
    s0 = {x["id"]: x for x in c.get(f"{P}/gpus").json()}[0]["scheduler"]
    assert s0["planned"] == "weita-v3" and s0["next"] == ["lw-img-lora", "pose-lora", "lw-lora"] and s0["assign"] is None
