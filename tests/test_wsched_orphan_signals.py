"""W-SCHED 11-06：vidgen 孤儿记录（镜被别台领走，repair_orphans 标 orphan、status 停在 pending、0 渲染）不是本机的活。
ep01 S7/S9/S11/S12/S14 在 gpu33 state 里 pending 1.5 h、其实都已在 gpu36 done → 被当成“视频饿死”。
① idle_watch 服务器探针 video_dispatchable 不数孤儿；② episode_checklist 合并各台 state 时孤儿不盖掉领取台的 done。
探针 / 片段在 tmp_path 里真跑（不连服务器、不碰显卡）。"""
from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUN = "series10_v2"


def _load(name, rel):
    sp = importlib.util.spec_from_file_location(name, ROOT / rel)
    m = importlib.util.module_from_spec(sp)
    sp.loader.exec_module(m)
    return m


def _fixture(tmp_path):
    vid = tmp_path / "data/pipeline/runs" / RUN / "video"
    vid.mkdir(parents=True)
    var = {"v1": {"status": "ready", "recipe": "i2va_pika_flex"}}
    jobs = {"shots": [{"shot": "ep01-S7", "ep": 1, "host": "gpu36", "variants": var},
                      {"shot": "ep01-S8", "ep": 1, "host": "gpu33", "variants": var}]}
    (vid / "jobs.json").write_text(json.dumps(jobs), encoding="utf-8")
    (vid / "state_gpu33.json").write_text(json.dumps({"shots": {
        "ep01-S7": {"status": "pending", "renders": [], "orphan": True},
        "ep01-S8": {"status": "pending", "renders": []}}}), encoding="utf-8")
    (vid / "state_gpu36.json").write_text(json.dumps({"shots": {
        "ep01-S7": {"status": "done", "renders": [{"state": "scored"}]}}}), encoding="utf-8")
    return vid


def _run(code, cwd):
    r = subprocess.run([sys.executable, "-c", code], cwd=cwd, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr[-800:]
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_idle_watch_probe_skips_orphans(tmp_path):
    IW = _load("idle_watch_wsched", "tools/autopilot/idle_watch.py")
    _fixture(tmp_path)
    code = (IW.REMOTE_PROBE.replace("__LANES__", "{}").replace("__RUN__", RUN).replace("__HOST__", "gpu33")
            .replace("__PD__", "nope").replace("__VQA_PORT__", "1"))
    out = _run(code, tmp_path)
    assert out["video_dispatchable"] == ["ep01-S8"] and out["video_dispatchable_n"] == 1


def test_checklist_snap_orphan_does_not_mask_done(tmp_path):
    EC = _load("episode_checklist_wsched", "tools/master/episode_checklist.py")
    _fixture(tmp_path)
    out = _run(EC.HOST_VID_SNAP % {"run": RUN, "ep": 1, "host": "gpu33"}, tmp_path)
    assert out == {"host": "gpu33", "busy": 0, "queued": 1}          # 只有 ep01-S8；S7 按 gpu36 的 done 算
