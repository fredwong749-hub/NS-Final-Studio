"""按集运行（项目方选卡）：校验、资格判断与原因码、dry_run 不落盘、lend 文件 / 队列 / run 记录、进度、取消。"""
import hashlib
import json
import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_canvas.app import create_app
from ns_canvas.config import RootCfg, Settings

P = "/api/gpu3/projects/weita/episodes"
H3 = "How the reference pictures align…"
sha = lambda t: hashlib.sha256(t.encode()).hexdigest()


@pytest.fixture
def env(tmp_path: Path):
    base = tmp_path / "data" / "renders_gpu3"

    def shot(ep, n, status, compiled=None, takes=None, last=False):
        d = base / f"ep{ep:02d}" / f"S{n}"
        d.mkdir(parents=True)
        (d / "status.json").write_text(json.dumps(status), encoding="utf-8")
        if compiled:
            (d / "compiled.json").write_text(json.dumps(compiled), encoding="utf-8")
        if takes:
            (d / "takes").mkdir()
            for t in takes["takes"]:
                (d / "takes" / Path(t["file"]).name).write_bytes(b"x")
            (d / "takes.json").write_text(json.dumps(takes), encoding="utf-8")
        if last:
            (d / "last_target.png").write_bytes(b"x")

    good_takes = {"takes": [{"n": 1, "stage": "image", "file": "renders_gpu3/ep01/S1/takes/image_001.png"},
                            {"n": 1, "stage": "video", "file": "renders_gpu3/ep01/S1/takes/video_001.mp4", "prompt": H3}],
                  "active": {"image": 1, "video": 1}}
    shot(1, 1, {"owner": "gpu3", "audit": {"verdict": "pass", "prompt_sha": sha(H3), "failures": []}},
         compiled={"h3_prompt": H3, "h3_prompt_sha256": sha(H3)}, takes=good_takes, last=True)
    shot(1, 2, {"owner": "gpu3", "audit": {"verdict": "fail", "blocked": "explicit_content_not_supported", "failures": []}})
    shot(1, 3, {"owner": "laptop", "audit": {"verdict": "fail", "failures": [
        {"rule_id": "R-C4", "sop_ref": "★1 S2", "detail": "lora"}, {"rule_id": "H3-A1", "sop_ref": "§9A.1 #1"}]}})
    shot(1, 4, {"owner": "gpu3", "audit": {"verdict": "fail", "failures": []}})
    (base / "ep01" / "qa.json").write_text(json.dumps({"verdict": "pass"}))
    shot(2, 1, {"owner": "gpu3", "audit": {"verdict": "pass", "failures": []}})
    script = tmp_path / "script.json"
    script.write_text(json.dumps({"episodes": [
        {"number": 1, "title": "旋转门", "shots": [{"index": i} for i in (1, 2, 3, 4)]},
        {"number": 2, "title": "红", "high_intensity": True, "shots": [{"index": 1}]}]}, ensure_ascii=False), encoding="utf-8")
    tl = tmp_path / "state_timeline.json"
    tl.write_text(json.dumps({"shots": [{"shot_id": "ep01-S4", "needs_review": True, "review_reasons": ["鞋待确认"]},
                                        {"shot_id": "ep01-S1", "needs_review": False}]}, ensure_ascii=False), encoding="utf-8")
    locks = tmp_path / "locks"
    locks.mkdir()
    (locks / "gpu.lock.gpu0").write_text(f"pid:{os.getpid()} owner_script_render:frame:ep05s1:c2")   # 活的进程 → 占用
    (locks / "gpu.lock.gpu1").write_text("pid:999999 owner_script_render:stale")                     # 死进程 → 过期
    s = Settings(queue_dir=base, roots=[RootCfg("renders_gpu3", "takes", base)], cache_dir=tmp_path / "c",
                 script_json=script, renders_base=base, lock_dir=locks, state_timeline=tl)
    return TestClient(create_app(s)), base, locks


def body(**kw):
    b = {"steps": ["frames", "video", "4k"], "gpu": 1, "by": "owner", "note": "补拍 ep01", "dry_run": True}
    b.update(kw)
    return b


def test_validation(env):
    c, _, _ = env
    assert c.post(f"{P}/1/run", json=body(by="fredw-d9")).status_code == 403
    for g in (2, 5, -1):
        assert c.post(f"{P}/1/run", json=body(gpu=g)).status_code == 422
    assert c.post(f"{P}/1/run", json=body(note="  ")).status_code == 422
    r = c.post(f"{P}/1/run", json=body(steps=["frames", "assemble"]))
    assert r.status_code == 422 and "assemble" in r.json()["detail"]
    assert c.post(f"{P}/1/run", json=body(steps=["upscale"])).status_code == 422
    assert c.post(f"{P}/1/run", json=body(steps=[])).status_code == 422
    assert c.post(f"{P}/1/run", json=body(dry_run="yes")).status_code == 422
    assert c.post(f"{P}/9/run", json=body()).status_code == 404


def test_dry_run_eligibility(env):
    c, base, locks = env
    d = c.post(f"{P}/1/run", json=body(gpu=0)).json()                  # dry_run：即使 GPU 0 被占也返回预览
    assert d["dry_run"] is True and d["gpu_holder"]["file"].endswith("gpu.lock.gpu0")
    it = {(x["shot"], x["step"]): x for x in d["shots"]}
    assert it[("ep01-S1", "frames")]["eligible"] and it[("ep01-S1", "video")]["eligible"]
    assert it[("ep01-S2", "frames")]["eligible"]                       # 露骨红标不再拦（2026-10-30）
    assert it[("ep01-S2", "frames")]["detail"]["explicit"] == ["blocked: explicit_content_not_supported"]
    assert set(it[("ep01-S2", "video")]["reasons"]) == {"video_gate_false", "no_keyframes"}
    assert it[("ep01-S3", "frames")]["reasons"] == ["not_s2_ready", "owner_not_gpu3"]
    assert it[("ep01-S3", "frames")]["detail"]["s2_rules"] == ["R-C4"]
    assert it[("ep01-S4", "frames")]["reasons"] == ["needs_review"]
    assert it[("ep01-S4", "frames")]["detail"]["review_reasons"] == ["鞋待确认"]
    assert it[("ep01", "4k")]["eligible"] is True
    assert d["counts"]["total"] == 9 and d["counts"]["eligible"] == 4 and "explicit_hold" not in d["counts"]["reasons"]
    assert d["counts"]["by_step"]["frames"] == {"eligible": 2, "ineligible": 2}
    # dry_run 不落盘
    assert not (locks / "lend.gpu0").exists() and not (base / "rerender_queue.jsonl").exists() and not (base / "runs").exists()
    # 红集 / 无 qa.json
    d2 = c.post(f"{P}/2/run", json=body()).json()
    it2 = {(x["shot"], x["step"]): x for x in d2["shots"]}
    assert it2[("ep02-S1", "frames")]["eligible"] and it2[("ep02-S1", "frames")]["detail"]["explicit"] == ["🔴 本集"]
    assert it2[("ep02", "4k")]["reasons"] == ["qa_not_pass"]


@pytest.mark.skipif(not Path("/proc").exists(), reason="锁持有进程是否已死靠 /proc/<pid> 判断（只在 Linux / gpu3 上有）；Windows 上无法判断，按占用处理")
def test_run_progress_cancel(env):
    c, base, locks = env
    r = c.post(f"{P}/1/run", json=body(gpu=0, dry_run=False))
    assert r.status_code == 409 and r.json()["detail"]["holder"]["text"].startswith("pid:")
    r = c.post(f"{P}/1/run", json=body(gpu=1, dry_run=False))         # gpu.lock.gpu1 的进程已死 → 视为空闲
    assert r.status_code == 200
    d = r.json()
    rid = d["run_id"]
    assert d["dry_run"] is False and [(q["shot"], q["step"]) for q in d["queued"]] == [
        ("ep01-S1", "frames"), ("ep01-S1", "video"), ("ep01-S2", "frames"), ("ep01", "4k")]
    lend = (locks / "lend.gpu1").read_text(encoding="utf-8")
    assert lend == f"owner-run {rid} ep01 frames,video,4k — 补拍 ep01"
    lines = [json.loads(x) for x in (base / "rerender_queue.jsonl").read_text(encoding="utf-8").splitlines()]
    assert {(x["shot"], x["step"]) for x in lines} == {("ep01-S1", "frames"), ("ep01-S1", "video"),
                                                       ("ep01-S2", "frames"), ("ep01", "4k")}
    assert all(x["run_id"] == rid and x["gpu"] == 1 and x["by"] == "owner" and x["at"] and x["id"] for x in lines)
    rec = json.loads((base / "runs" / f"{rid}.json").read_text(encoding="utf-8"))
    assert rec["status"] == "queued" and len(rec["items"]) == 4 and len(rec["skipped"]) == 5
    # 第二次跑同一张卡：lend 已被这次 run 占用 → 409
    assert c.post(f"{P}/1/run", json=body(gpu=1, dry_run=False)).status_code == 409
    # 进度
    first = d["queued"][0]["id"]
    assert c.post("/api/gpu3/queue/events", json={"id": first, "state": "started", "worker": "gpu1"}).status_code == 200
    g = c.get(f"{P}/1/run/{rid}").json()
    assert g["progress"] == {"rendering": 1, "queued": 3} and g["active"] and g["lend_held"]
    assert c.get(f"{P}/1/run/run-ep01-deadbeef").status_code == 404
    # 取消
    assert c.post(f"{P}/1/run/{rid}/cancel", json={"by": "fredw-d9"}).status_code == 403
    x = c.post(f"{P}/1/run/{rid}/cancel", json={"by": "owner"}).json()
    assert len(x["cancelled"]) == 3 and x["still_running"] == [first] and x["lend_released"] is True
    assert not (locks / "lend.gpu1").exists()
    g = c.get(f"{P}/1/run/{rid}").json()
    assert g["status"] == "cancelled" and g["progress"] == {"rendering": 1, "cancelled": 3} and g["lend_held"] is False


def test_cancel_keeps_foreign_lend(env):
    c, _, locks = env
    rid = c.post(f"{P}/1/run", json=body(gpu=3, steps=["frames"], dry_run=False)).json()["run_id"]
    (locks / "lend.gpu3").write_text("weita-v3-llm (someone else now)")
    x = c.post(f"{P}/1/run/{rid}/cancel", json={"by": "owner"}).json()
    assert x["lend_released"] is False and (locks / "lend.gpu3").exists()


def test_train_lock_holds_gpu(env):
    """封板修复：train.lock.gpuN（LoRA 训练 / Qwen 写作模型）算占用；by=*render-reserve 的渲染预留锁不算。"""
    from ns_canvas import runs
    c, base, locks = env
    (locks / "train.lock.gpu3").write_text(json.dumps({"by": "qwen-agent", "gpu": 3}))
    h = runs.lock_holder(locks, 3)
    assert h and h["file"].endswith("train.lock.gpu3")
    (locks / "train.lock.gpu3").write_text(json.dumps({"by": "ep02-render-reserve", "gpu": 3}))
    assert runs.lock_holder(locks, 3) is None
    (locks / "train.lock.gpu3").write_text("not json")
    assert runs.lock_holder(locks, 3)["file"].endswith("train.lock.gpu3")


def test_script_adult_flag_no_longer_holds(tmp_path):
    """2026-10-30 取消成人过滤器：剧本 adult=True 的镜头也可出帧，只把 adult 记进 detail。"""
    from ns_canvas import runs
    d = tmp_path / "S5"
    d.mkdir()
    (d / "compiled.json").write_text("{}", encoding="utf-8")
    (d / "status.json").write_text(json.dumps({"owner": "gpu3"}), encoding="utf-8")
    shots = [{"shot": "ep02-S5", "takes": [], "active": {}, "video_gate": {"video_ok": True}}]
    items = runs.shot_items(2, shots, {"ep02-S5": d}, ["frames"], red_episode=False, reviews={}, qa_pass=False,
                            adult_shots={"ep02-S5"})
    assert items[0]["eligible"] and "explicit_hold" not in items[0]["reasons"]
    assert items[0]["detail"]["explicit"] == ["adult"]


def test_timeline_s2_blocks_frames(tmp_path):
    """封板修复：state_timeline 的 s2_ready=false 要拦首帧（以前桥不读，S2 未放行也显示可出）。"""
    from ns_canvas import runs
    tl = tmp_path / "state_timeline.json"
    tl.write_text(json.dumps({"shots": {"ep02-S1": {"s2_ready": False, "s2_blockers": ["s1_gate_not_passed"]},
                                        "ep02-S2": {"s2_ready": True}, "ep02-S3": {}}}), encoding="utf-8")
    blocked = runs.timeline_s2(tl)
    assert blocked == {"ep02-S1": ["s1_gate_not_passed"]}
    d = tmp_path / "S1"
    d.mkdir()
    shots = [{"shot": "ep02-S1", "takes": [], "active": {}}]
    it = runs.shot_items(2, shots, {"ep02-S1": d}, ["frames"], red_episode=False, reviews={}, qa_pass=False,
                         s2_blocked=blocked)[0]
    assert "not_s2_ready" in it["reasons"] and "timeline:s1_gate_not_passed" in it["detail"]["s2_rules"]
