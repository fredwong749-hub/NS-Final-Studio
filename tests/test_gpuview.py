"""GPUVIEW（K-OPS-G01 / K-OPS-G02）：主要提交方都带 comfy_tag；nvidia-smi 快照解析；报错人话；渲染任务分桶对得上。"""
from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]

SUBMITTERS = [
    "tools/series10_imggen/imggen.py",
    "tools/series10_video/vidgen.py",
    "tools/bakeoff/run.py",
    "tools/pipeline/submit_jobs.py",
    "tools/assetmaster/frames_v2.py",
    "tools/char_assets/asset_gen.py",
    "tools/gen_contract/reflock_validate.py",
    "services/render_router/ns_render/comfy_client.py",
    "services/api/ns_api/jobs.py",
]


@pytest.mark.parametrize("rel", SUBMITTERS)
def test_submitter_carries_tag(rel):
    """K-OPS-G01：每个主要提交方都把标签放进 extra_data.ns_tag（comfy_tag 或同格式 ns_tag）"""
    src = (ROOT / rel).read_text(encoding="utf-8")
    assert "ns_tag" in src or "comfy_tag" in src or "_ct().make(" in src, f"{rel} 没带 GPU 任务标签"


SNAP = """##BEGIN 1793465000
##SMI
0, GPU-a, NVIDIA GeForce RTX 3090, 100, 23355, 24576, 47, 199.06, 200.00, 350.00
1, GPU-b, NVIDIA GeForce RTX 3090, 0, 9000, 24576, 29, 20.5, 200.00, 350.00
##APPS
GPU-a, 475532, 23304
GPU-b, 999, 4000
##PS
475532|root|3600|/root/work/fredw/venv/bin/python main.py --listen 127.0.0.1 --port 8190 --output-directory x
999|flab|120|python train.py --cfg a.yaml
##LOG
8190|3|  50%|#####     | 12/24 [01:10<01:10, 5.8s/it]
##GUARD
boot_id x
level 1
gpu GPU-a 350 200 0
##HB
{"agent": "VOICE10", "label": "试听音色 · 林晚 候选3", "server": "gpu36", "gpu": 1, "updated": 1793465000}
"""


def test_parse_block():
    from ns_api.gpu_live import parse_block
    d = parse_block(SNAP)
    assert d["gpus"][0]["power_limit_w"] == 200.0 and d["gpus"][0]["power_default_w"] == 350.0
    assert d["procs"][0][0]["comfy_port"] == 8190
    assert d["procs"][1][0]["user"] == "flab" and d["procs"][1][0]["comfy_port"] is None
    assert d["comfy_log"][8190]["step"] == 12 and d["comfy_log"][8190]["steps"] == 24
    assert d["guard"]["level"] == 1
    assert d["heartbeats"][0]["agent"] == "VOICE10"


def test_humanize_errno_refcrops():
    from ns_api.render_tasks import humanize_error
    h = humanize_error(r"[Errno 2] No such file or directory: 'D:\\NS-Final Studio\\data\\pipeline\\runs\\series10_v1\\images\\refcrops\\lin_wan_lookA_s202_half_nohead.png'")
    assert "参考裁切图" in h["what"] and "lin_wan_lookA_s202_half_nohead.png" in h["what"]


def test_buckets_reconcile_and_failure_resolved():
    from ns_api import render_tasks as RT
    jobs = [
        {"id": "a", "state": "failed", "stage": "image", "shot_id": "ep01-S1", "gpu": 0, "error": "[Errno 2] No such file or directory: 'x/refcrops/y.png'",
         "created_at": "2026-11-01T01:29:23", "started_at": "2026-11-01T01:29:30", "finished_at": "2026-11-01T01:29:40", "v1": True},
        {"id": "b", "state": "done", "stage": "image", "shot_id": "ep01-S1", "gpu": 0, "take": {"n": 5},
         "created_at": "2026-11-01T01:33:13", "started_at": "2026-11-01T01:33:20", "finished_at": "2026-11-01T01:35:00", "v1": True},
        {"id": "c", "state": "cancelled", "stage": "image", "shot_id": "ep01-S2", "gpu": 0, "created_at": "2026-11-01T01:00:00"},
    ]
    import time
    now = time.time()
    for j in jobs:   # 放进“最近 24 小时”
        for k in ("created_at", "started_at", "finished_at"):
            if j.get(k):
                j[k] = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(now - 600 + (60 if j["id"] == "b" else 0)))
    rows, cancelled = RT._job_rows(jobs, {}, {})
    RT._resolve_and_attempts(rows, {})
    assert cancelled == 1
    a = next(r for r in rows if r["id"] == "job:a")
    assert a["status"] == "done" and a["error"]["resolved_by"] == "job:b" and "#5" in a["error"]["resolved_text"]
    assert a["attempt"] == 1 and next(r for r in rows if r["id"] == "job:b")["attempt"] == 2


def test_brief_outage_is_not_offline():
    """UIAUDIT verify_gpuview_r1 P2：ComfyUI 短暂连不上写“暂时连不上（N 秒）”，沿用断开前的队列；连续超过 2 分钟才算离线"""
    from ns_api import gpu_live as GL
    prev = {"reachable": True, "running": [{"prompt_id": "p1"}], "pending": [], "history": [{"prompt_id": "h"}], "down_since": None}
    r = GL.merge_poll(prev, {"reachable": False, "error": "timed out"}, 1000.0)
    assert r["down_since"] == 1000.0 and r["stale"] and r["running"] == [{"prompt_id": "p1"}] and r["history"]
    r2 = GL.merge_poll(r, {"reachable": False}, 1030.0)
    assert r2["down_since"] == 1000.0 and r2["running"] == [{"prompt_id": "p1"}]
    ls = GL.link_state(r2, 1030.0, 100)
    assert not ls["offline"] and "暂时连不上（30 秒）" in ls["text"] and "卡在忙" in ls["text"] and "离线" not in ls["text"]
    r3 = GL.merge_poll(r2, {"reachable": False}, 1000.0 + GL.OFFLINE_AFTER_S + 1)
    assert "running" not in r3
    assert GL.link_state(r3, 1000.0 + GL.OFFLINE_AFTER_S + 1, 0)["offline"]
    back = GL.merge_poll(r3, {"reachable": True, "running": [], "pending": []}, 1200.0)
    assert back["down_since"] is None and GL.link_state(back, 1200.0, 0) is None


def test_queue_badge_uses_same_filter():
    """UIAUDIT verify_gpuview_r1 P2：底栏“任务队列”标签上的数字与列表同一个筛选（countRows），不再用全剧总数"""
    src = (ROOT / "apps/web/src/components/Drawer.tsx").read_text(encoding="utf-8")
    assert "countRows(" in src and "c.failed ? `失败" not in src
    # PW-019（UIRSI 11-01，GPUVIEW 授权）：countRows 挪到 RenderTasks.helpers.ts，列表组件仍在 RenderTasks.tsx 里调用
    helpers = (ROOT / "apps/web/src/components/RenderTasks.helpers.ts").read_text(encoding="utf-8")
    rt = (ROOT / "apps/web/src/components/RenderTasks.tsx").read_text(encoding="utf-8")
    assert "export function countRows(" in helpers and "countRows(rows" in rt


def test_job_stage_label_not_step_bar():
    """IMGPERF（data/qa/imgperf/gpuview_render_tasks.diff）：job.progress 是阶段记录，行副标题写阶段名 + 本段起点，不当步数条"""
    import time
    from ns_api import render_tasks as RT
    now = time.strftime("%Y-%m-%dT%H:%M:%S", time.localtime(time.time() - 30))
    j = {"id": "x", "state": "running", "stage": "image", "shot_id": "ep01-S3", "gpu": 0, "v1": True, "created_at": now,
         "started_at": now, "progress": {"stage": "comfy_run", "label": "GPU 出图", "step": 5, "total": 8, "since": now}}
    rows, _ = RT._job_rows([j], {}, {})
    r = rows[0]
    assert r["sub"] == "GPU 出图" and r["stage_since"] and r["progress"] is None
    j2 = {**j, "id": "y", "progress": {"stage": "queued", "label": "排队", "since": now}}
    r2 = RT._job_rows([j2], {}, {})[0][0]
    assert r2["sub"] == "渲染中" and r2["stage_since"] is None


def test_known_project_process_is_not_other_user():
    """REFLOCK 的 clip_srv.py（remote_score.postflight_full 起的契约打分服务）是本项目进程：写“契约打分 · REFLOCK（CLIP）”，不写“训练/其他用户”"""
    from ns_api import gpu_live as GL
    k = GL.known_proc("/root/x/venv/bin/python /root/x/clip_srv.py --port 9001")
    assert k == {"label": "契约打分 · REFLOCK（CLIP）", "agent": "REFLOCK"}
    assert GL.known_proc("python train.py") is None


def test_lane_selection_ignores_processes():
    """选卡只看 train.lock 与 ComfyUI 队列：pick_lane / PRODUCER 不读 nvidia-smi 进程表（常驻打分服务不会让道被弃用）"""
    for rel in ("services/api/ns_api/jobs.py", "tools/autopilot/producer.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        assert "query-compute-apps" not in src and "/api/gpu/live" not in src and "other_procs" not in src, rel
