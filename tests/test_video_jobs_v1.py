"""api_v1_contract §D 视频任务（fredw-92/W3）：假 ComfyUI 客户端，不碰 GPU。"""
from __future__ import annotations

import io
import time

import pytest
from PIL import Image

from ns_api import jobs as J
from ns_api import video_jobs as VJ
from ns_render import h3_video as HV
from ns_render import pipeline as P
from ns_render import workflows as W
from ns_render.comfy_client import ComfyClient
from ns_schema.h3_lint import ALIGN_PREFIX, frames_for_seconds

from test_readiness import PNG, env, script  # noqa: F401  复用夹具

SHOT = "ep01-S2"


def png(color=(120, 90, 60), size=(109, 192)) -> bytes:
    b = io.BytesIO()
    Image.new("RGB", size, color).save(b, "PNG")
    return b.getvalue()


class FakeComfy:
    """记录提交的工作流；/history 立即完成，输出一个 mp4"""

    def __init__(self):
        self.submitted: list[dict] = []
        self.uploads: list[str] = []
        self.interrupted = False

    def object_info(self):
        return {"LoraLoaderModelOnly": {"input": {"required": {"lora_name": [[W.H3_TURBO_8STEP_768P]]}}}}

    def check(self, wf):
        return []

    def upload_image(self, path, subfolder="ns_final"):
        import hashlib
        name = hashlib.sha256(path.read_bytes()).hexdigest()[:16] + path.suffix.lower()
        self.uploads.append(name)
        return f"{subfolder}/{name}"

    def _request(self, path, data=None, headers=None):   # /view?…type=input：已上传过才有
        if path.startswith("/view?") and any(f"filename={n}&" in path for n in self.uploads):
            return b"png"
        raise RuntimeError("404")

    def submit(self, wf):
        self.submitted.append(wf)
        return f"p{len(self.submitted)}"

    def _json(self, path, body=None):
        if path.startswith("/history/"):
            pid = path.rsplit("/", 1)[-1]
            return {pid: {"status": {"completed": True, "status_str": "success"},
                          "outputs": {"92": {"images": [{"filename": f"{pid}.mp4", "subfolder": "", "type": "output"}]}}}}
        if path == "/queue":
            return {"queue_running": [], "queue_pending": []}
        return {}

    def system_stats(self):
        return {"devices": [{"vram_total": 24 * 2**30, "vram_free": 4 * 2**30}]}

    output_files = staticmethod(ComfyClient.output_files)

    def download(self, item, dest):
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"mp4")
        return dest

    def interrupt(self):
        self.interrupted = True


@pytest.fixture()
def fake(env, monkeypatch):
    c, data, _ = env
    fc = FakeComfy()
    monkeypatch.setattr(J, "client_factory", lambda gpu: fc)
    monkeypatch.setattr(P, "extract_last_frame", lambda v, out: None)
    monkeypatch.setattr(HV, "VramSampler", _NoVram)
    return c, data, fc


class _NoVram:
    peak, total = 20.0, 24.0

    def __init__(self, client):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _frame(data, shot, stage, n, content=None, lock=True):
    ep, sn = shot.split("-")
    rel = f"renders/{ep}/{sn}/takes/{stage}_{n:03d}.png"
    (data / rel).parent.mkdir(parents=True, exist_ok=True)
    (data / rel).write_bytes(content or png((40 * n, 80, 120 if stage == "last" else 10)))
    tk = P.load_takes(shot)
    tk["takes"].append({"n": n, "stage": stage, "file": rel, "seed": 1, "prompt": "", "created_at": P.now()})
    tk["active"][stage] = n
    if lock:
        tk.setdefault("locked", {})[stage] = n
    P._save_takes(shot, tk)


def _wait(c, jid, timeout=10):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["state"] not in ("queued", "running"):
            return j
        time.sleep(0.05)
    raise AssertionError("job 未完成")


def test_409_lists_missing_frames(fake):
    c, data, _ = fake
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={})
    assert r.status_code == 409 and set(r.json()["missing"]) == {"first", "last"}
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1, lock=False)          # 尾帧有但没定稿
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={})
    assert r.status_code == 409 and r.json()["missing"] == ["last"] and "尾帧" in r.json()["detail"]


def test_validation(fake):
    c, data, _ = fake
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)
    assert c.post(f"/api/shots/{SHOT}/video-jobs", json={"steps": 4}).status_code == 422
    assert c.post(f"/api/shots/{SHOT}/video-jobs", json={"seconds": 20}).status_code == 422
    assert c.post(f"/api/shots/{SHOT}/video-jobs", json={"gpu": 2}).status_code == 422
    assert c.post(f"/api/shots/{SHOT}/video-jobs", json={"parent": 9}).status_code == 404
    assert c.post("/api/shots/ep99-S1/video-jobs", json={}).status_code == 404


def test_render_chain_params_and_stale(fake):
    c, data, fc = fake
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={})
    assert r.status_code == 200 and r.json()["gpu"] == 3
    j = _wait(c, r.json()["job_id"])
    assert j["state"] == "done", j
    wf = fc.submitted[0]
    # 图：int8 DiT + 8 步 Turbo LoRA 1.0 + shift 6/3（采样和调度都过）+ 首尾帧都在
    assert wf["127"]["inputs"]["unet_name"] == W.H3_DIT_INT8
    assert wf["140"]["inputs"]["lora_name"] == W.H3_TURBO_8STEP_768P and wf["140"]["inputs"]["strength_model"] == 1.0
    assert wf["150"]["inputs"]["shift_video"] == 6.0 and wf["124"]["inputs"]["model"] == ["150", 0]
    assert wf["124"]["inputs"]["steps"] == 8 and wf["131"]["inputs"].get("last_frame")
    secs = P.find_shot(VJ.get_script(), SHOT)[1].duration
    fr = frames_for_seconds(secs)
    assert wf["131"]["inputs"]["length"] == fr
    # 提示词原样 = 编译器的剧本 H3 四块
    c1 = P.compile_with_edits(VJ.get_script(), SHOT, set())
    assert wf["131"]["inputs"]["prompt"] == c1.video_prompt
    t1 = next(t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "video")
    assert t1["params"]["first"]["n"] == 1 and t1["params"]["last"]["n"] == 1 and t1["parent"] is None
    assert t1["params"]["vram_peak_gb"] == 20.0 and t1["params"]["model"]["shift"] == [6.0, 3.0]

    # 改参数重渲：新种子、步数、时长、LoRA 强度、提示词覆盖 → 第 2 版挂在第 1 版下
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"seed": 42, "steps": 10, "seconds": 7, "lora_strength": 0.8,
                                                      "prompt_override": "OWNER TEXT"})
    j = _wait(c, r.json()["job_id"])
    assert j["state"] == "done", j
    wf2 = fc.submitted[1]
    assert wf2["129"]["inputs"]["noise_seed"] == 42 and wf2["124"]["inputs"]["steps"] == 10
    assert wf2["140"]["inputs"]["strength_model"] == 0.8 and wf2["131"]["inputs"]["length"] == frames_for_seconds(7)
    assert wf2["131"]["inputs"]["prompt"] == "OWNER TEXT"
    assert len(fc.uploads) == 2                      # 首尾帧没变：重渲不重复上传
    kf = data / "renders/_h3_keyframes"
    assert {Image.open(f).size for f in kf.glob("*.png")} == {P.VIDEO_SIZE}   # 预缩放到视频画布
    v = c.get(f"/api/shots/{SHOT}/video-takes").json()
    assert [t["n"] for t in v["takes"]] == [1, 2] and v["active"] == 2
    assert v["takes"][1]["parent"] == 1 and v["takes"][1]["params"]["prompt_source"] == "request"
    assert v["takes"][0]["stale"] == [] and v["takes"][1]["stale"] == []

    # 定稿首帧换了 → 两版都过期；尾帧文件内容被改 → 也过期
    _frame(data, SHOT, "image", 2)
    v = c.get(f"/api/shots/{SHOT}/video-takes").json()
    assert all("定稿首帧已换" in t["stale"] for t in v["takes"])
    (data / "renders/ep01/S2/takes/last_001.png").write_bytes(png((1, 2, 3)))
    v = c.get(f"/api/shots/{SHOT}/video-takes").json()
    assert all("定稿尾帧已换" in t["stale"] for t in v["takes"])
    # 镜头详情的过期原因同样带上
    d = c.get(f"/api/shots/{SHOT}").json()
    vt = [t for t in d["takes"]["takes"] if t["stage"] == "video"]
    assert all("定稿首帧已换" in t["stale"] for t in vt)


def test_realign_only_touches_alignment_line():
    p = f"{ALIGN_PREFIX} — old line\n\nbody stays"
    out = HV.realign(p, 175)
    assert out.endswith("\n\nbody stays") and "7.29-second" in out.splitlines()[0]
    assert HV.realign("no h3 structure", 175) == "no h3 structure"


def test_cancel_queued_job(fake, monkeypatch):
    c, data, _ = fake
    gate = __import__("threading").Event()
    J.submit("video", SHOT, 3, lambda cl, job: gate.wait(5) and {})      # 占住道 3
    j2 = J.submit("video", SHOT, 3, lambda cl, job: {"take": 1})
    assert c.post(f"/api/jobs/{j2['id']}/cancel").json()["state"] == "cancelled"
    gate.set()
    time.sleep(0.2)
    assert J.get(j2["id"])["state"] == "cancelled" and J.get(j2["id"])["take"] is None


def test_wait_prompt_cancel_interrupts_own_prompt():
    class C(FakeComfy):
        def _json(self, path, body=None):
            if path == "/queue":
                return {"queue_running": [[0, "mine"]]}
            return {}
    cl = C()
    job = {"cancel_requested": True}
    with pytest.raises(J.Cancelled):
        J.wait_prompt(cl, job, "mine", 5, poll_s=0.01)
    assert cl.interrupted


def test_wait_prompt_survives_tunnel_blips():
    from ns_render.comfy_client import ComfyUnavailable

    class C(FakeComfy):
        calls = 0

        def _json(self, path, body=None):
            C.calls += 1
            if C.calls <= 2:
                raise ComfyUnavailable("/history: timed out")
            return super()._json(path, body)
    job = {}
    entry = J.wait_prompt(C(), job, "p1", 5, poll_s=0.01)
    assert entry["status"]["completed"] and "poll_error" not in job


def test_jobs_persist_and_restart_marks_unfinished(env, monkeypatch):
    import json
    c, data, _ = env
    j = J.submit("video", SHOT, 3, lambda cl, job: {"take": 7})
    t0 = time.time()
    while J.get(j["id"])["state"] != "done" and time.time() - t0 < 5:
        time.sleep(0.02)
    time.sleep(0.1)
    rec = json.loads((data / "jobs" / "v1" / f"{j['id']}.json").read_text(encoding="utf-8"))
    assert rec["state"] == "done" and rec["take"] == 7
    # 模拟上次 API 跑到一半：落盘的 running 任务
    (data / "jobs" / "v1" / "deadbeef0001.json").write_text(json.dumps(
        {"id": "deadbeef0001", "kind": "video", "shot_id": SHOT, "gpu": 3, "state": "running",
         "created_at": "2026-10-30T00:00:00"}), encoding="utf-8")
    monkeypatch.setattr(J, "_jobs", {})
    assert J.restore() == 1
    r = c.get("/api/jobs/deadbeef0001").json()
    assert r["state"] == "failed" and r["error"] == J.RESTART_ERROR
    assert c.get(f"/api/jobs/{j['id']}").json()["state"] == "done"


def test_fresh_video_take_not_stale_in_shot_detail(fake):
    """fredw-92/F4：H3 视频刚出 → 镜头详情里这一版 stale / stale_global 都为空（造型哈希、规则版本、输入哈希已记）；
    剧本提示词真变了照样过期"""
    from ns_api import app as app_mod
    c, data, fc = fake
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)
    j = _wait(c, c.post(f"/api/shots/{SHOT}/video-jobs", json={}).json()["job_id"])
    assert j["state"] == "done", j
    d = c.get(f"/api/shots/{SHOT}").json()
    vt = next(t for t in d["takes"]["takes"] if t["stage"] == "video")
    assert vt["stale"] == [] and vt["stale_global"] == []
    assert vt.get("bible_version") and vt.get("inputs_sha") and vt.get("look_hash")
    _ep, s = P.find_shot(app_mod._script, SHOT)
    edit = P.load_edit(SHOT)
    changed = type("C", (), {"image_prompt": "", "video_prompt": "BRAND NEW SCRIPT PROMPT", "last_prompt": None})()
    act = app_mod._active(SHOT, P.load_takes(SHOT))
    local, glob = app_mod._stale_split(SHOT, vt, s, changed, edit, act, None, "")
    assert local or glob


# ---------------- fredw-92/VB：附加视频 LoRA（VBVR 等） ----------------

VBVR = "H3-Licon-VBVR-I2V.safetensors"


def _with_loras(fc, *names):
    fc.object_info = lambda: {"LoraLoaderModelOnly": {"input": {"required": {
        "lora_name": [[W.H3_TURBO_8STEP_768P, *names]]}}}}


def test_extra_lora_validation(fake):
    c, data, fc = fake
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)
    _with_loras(fc, VBVR)
    url = f"/api/shots/{SHOT}/video-jobs"
    assert c.post(url, json={"loras": [{"name": VBVR, "strength": 1.6}]}).status_code == 422
    assert c.post(url, json={"loras": [{"name": VBVR, "strength": -0.1}]}).status_code == 422
    assert c.post(url, json={"loras": [{"name": "", "strength": 0.5}]}).status_code == 422
    assert c.post(url, json={"loras": [{"name": VBVR, "strength": 0.5}, {"name": VBVR, "strength": 0.7}]}).status_code == 422
    assert c.post(url, json={"loras": [{"name": W.H3_TURBO_8STEP_768P, "strength": 1.0}]}).status_code == 422
    r = c.post(url, json={"loras": [{"name": "nope.safetensors", "strength": 0.5}]})
    assert r.status_code == 422 and "nope.safetensors" in r.json()["detail"]
    assert fc.submitted == []


def test_extra_lora_chained_after_turbo(fake):
    c, data, fc = fake
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)
    _with_loras(fc, VBVR)
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"seed": 7, "loras": [{"name": VBVR, "strength": 0.7}]})
    assert r.status_code == 200, r.text
    assert r.json()["params"]["loras"] == [{"name": VBVR, "strength": 0.7}]
    j = _wait(c, r.json()["job_id"])
    assert j["state"] == "done", j
    wf = fc.submitted[0]
    lo = sorted((k for k, v in wf.items() if v["class_type"] == "LoraLoaderModelOnly"), key=int)
    assert [wf[k]["inputs"]["lora_name"] for k in lo] == [W.H3_TURBO_8STEP_768P, VBVR]
    assert wf[lo[1]]["inputs"]["model"] == [lo[0], 0] and wf[lo[1]]["inputs"]["strength_model"] == 0.7
    assert wf["150"]["inputs"]["model"] == [lo[1], 0] and wf["150"]["inputs"]["shift_video"] == 6.0   # 仍按 Turbo 配对
    t = next(t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "video")
    assert t["params"]["model"]["extra_loras"] == [[VBVR, 0.7]]
    assert t["params"]["loras"] == [{"name": VBVR, "strength": 0.7}]


def test_extra_lora_lane_unreachable_503(fake, monkeypatch):
    from ns_render.comfy_client import ComfyUnavailable
    c, data, fc = fake
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)

    def boom():
        raise ComfyUnavailable("/object_info: down")
    fc.object_info = boom
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"loras": [{"name": VBVR, "strength": 0.7}]})
    assert r.status_code == 503


def test_optional_video_loras_config(fake):
    c, _, _ = fake
    d = c.get("/api/video-loras").json()
    v = next(x for x in d["loras"] if x["id"] == "vbvr")
    assert v["name"] == VBVR and v["license"] == "CC BY-NC" and "非商用" in v["usage"]
    assert 0 <= v["recommended_strength"] <= 1.5 and d["strength_range"] == [0.0, 1.5]


def test_merge_loras_request_overrides_script():
    assert HV.merge_loras([("a", 1.0), (VBVR, 0.3)], [(VBVR, 0.7)]) == [("a", 1.0), (VBVR, 0.7)]
    assert HV.merge_loras([("a", 1.0)], None) == [("a", 1.0)]
