"""W2（fredw-92）：画布出图走 gpu3 ComfyUI + 精修循环（api_v1_contract §C）。
假 ComfyClient，全部在临时 data 目录：任务队列、修改链 parent、定稿 / 过期、按卡路由、Turbo 低重绘 sigma、
LoRA 编进首帧、owner=canvas 放行、画布出图不评分不质检。"""
import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from ns_agent.looks import DEFAULT_SCRIPT_JSON
from ns_api import app as app_mod
from ns_api import jobs as J
from ns_render import endpoints as EP
from ns_render import frame_edit as FE
from ns_render import pipeline as P
from ns_render import workflows as W

pytestmark = pytest.mark.skipif(not DEFAULT_SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
SHOT = "ep02-S1"
LORA = "lin_wan_qi_v1.safetensors"


def _png(path: Path, color=(120, 90, 80)):
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", (64, 112), color).save(path)


class FakeComfy:
    """有 ComfyClient 接口的假客户端：记下提交的工作流，立即完成，下载写一张小 PNG"""

    def __init__(self, gpu=0, block: threading.Event | None = None):
        self.gpu, self.block = gpu, block
        self.workflows, self.uploads, self.deleted, self.interrupted = [], [], [], 0
        self.object_info_calls = 0

    def object_info(self):
        self.object_info_calls += 1
        return {"LoraLoaderModelOnly": {"input": {"required": {"lora_name": [[LORA, "other.safetensors"]]}}}}

    def check(self, wf):
        return []

    def upload_image(self, path, subfolder="ns_final"):
        self.uploads.append(Path(path).name)
        return f"{subfolder}/{Path(path).name}"

    def submit(self, wf):
        self.workflows.append(wf)
        return f"p{len(self.workflows)}"

    def _json(self, path, body=None):
        if path.startswith("/history/"):
            if self.block is not None and not self.block.is_set():
                return {}
            pid = path.split("/")[-1]
            return {pid: {"status": {"completed": True}, "outputs": {
                "90": {"images": [{"filename": f"{pid}.png", "subfolder": "", "type": "output"}]}}}}
        if path == "/queue":
            if body:
                self.deleted += body.get("delete", [])
                return {}
            return {"queue_running": [], "queue_pending": []}
        return {}

    def run(self, wf, timeout_s):
        pid = self.submit(wf)
        return self._json(f"/history/{pid}")[pid], 1.0

    def interrupt(self):
        self.interrupted += 1

    output_files = staticmethod(P.ComfyClient.output_files)

    def download(self, item, dest):
        _png(Path(dest))
        return dest


@pytest.fixture()
def env(tmp_path, monkeypatch):
    data = tmp_path / "data"
    (data / "renders").mkdir(parents=True)
    monkeypatch.setattr(P, "DATA", data)
    monkeypatch.setattr(P, "RENDERS", data / "renders")
    own = tmp_path / "shot_ownership.json"
    own.write_text(json.dumps({"projects": {"weita": {"owner": "canvas"}}}), encoding="utf-8")
    monkeypatch.setattr(P, "OWNERSHIP", own)
    from ns_api import readiness as RD
    monkeypatch.setattr(RD, "OWNERSHIP_FILE", own)
    clients = {}

    def factory(gpu):
        clients.setdefault(gpu, []).append(FakeComfy(gpu))
        return clients[gpu][-1]
    monkeypatch.setattr(J, "client_factory", factory)
    yield TestClient(app_mod.app), data, clients


def _wait(c, jid, timeout=30):
    t0 = time.time()
    while time.time() - t0 < timeout:
        j = c.get(f"/api/jobs/{jid}").json()
        if j["state"] in ("done", "failed", "cancelled"):
            return j
        time.sleep(0.05)
    raise AssertionError(f"任务没结束：{j}")


def _job(c, body):
    r = c.post(f"/api/shots/{SHOT}/frame-jobs", json=body)
    assert r.status_code == 200, r.text
    return _wait(c, r.json()["job_id"])


def test_endpoints_gpu_routing(tmp_path, monkeypatch):
    for k in ("NS_COMFY_URL", "NS_COMFY_URL_GPU0", "NS_COMFY_URL_GPU3"):
        monkeypatch.delenv(k, raising=False)
    cfg = tmp_path / "re.json"
    assert EP.url_for_gpu(0, cfg) == "http://127.0.0.1:18188" and EP.url_for_gpu(3, cfg) == "http://127.0.0.1:18191"
    cfg.write_text(json.dumps({"image": {"url": "http://h:1", "gpu": 0}}), encoding="utf-8")
    assert EP.image_url(cfg) == "http://h:1" and EP.url_for_gpu(3, cfg) == "http://127.0.0.1:18191"
    monkeypatch.setenv("NS_COMFY_URL", "http://env:2")
    assert EP.url_for_gpu(0, cfg) == "http://env:2"
    monkeypatch.setenv("NS_COMFY_URL_GPU3", "http://env:3")
    assert EP.url_for_gpu(3, cfg) == "http://env:3"
    with pytest.raises(ValueError):
        EP.url_for_gpu(1, cfg)
    real = json.loads((P.ROOT / "config" / "render_endpoints.json").read_text(encoding="utf-8"))
    assert real["image"]["url"].endswith(":18188") and real["video"]["url"].endswith(":18191")


def test_turbo_low_denoise_sigmas():
    assert W.turbo_sigmas(0.35) == "0.35, 0"
    assert W.turbo_sigmas(0.75).startswith("0.75, 0.704534, 0.414568")
    assert W.turbo_sigmas(1.0) == W.TURBO_SIGMAS
    wf = W.qwen_edit("x", "", ["a.png"], 64, 64, 1, "p", init_image="b.png", denoise=FE.EDIT_DENOISE["small"])
    assert wf["37"]["inputs"]["sigmas"] == "0.35, 0" and wf["40"]["inputs"]["latent_image"] == ["112", 0]
    assert W.qwen_t2i("x", "", 64, 64, 1, "p")["37"]["inputs"]["sigmas"] == W.TURBO_SIGMAS
    assert FE.EDIT_DENOISE == {"small": 0.35, "medium": 0.55, "large": 0.75}


def test_canvas_owner_allows_render(env):
    assert P.gpu3_owns(SHOT) is None and P.project_gate_message() is None
    assert json.loads((P.ROOT / "config" / "shot_ownership.json").read_text(encoding="utf-8"))[
        "projects"]["weita"]["owner"] == "canvas"
    assert not hasattr(P, "AdultShotRejected")


def test_chain_regen_instruct_lock_last_stale(env):
    c, data, clients = env
    # 1) 首帧整张重出：1 张、文生图 + 林晚 LoRA、不评分不质检
    j1 = _job(c, {"stage": "first", "mode": "regen", "seed": 7})
    assert j1["state"] == "done", j1
    t1 = j1["take"]
    assert t1["mode"] == "regen" and t1["score"] is None and t1["qc"] is None and t1["gpu"] == 0
    fake = clients[0][-1]
    assert len(fake.workflows) == 1
    wf = fake.workflows[0]
    assert any(n["class_type"] == "LoraLoaderModelOnly" and n["inputs"]["lora_name"] == LORA for n in wf.values())
    assert "lnwan_qi" in next(n for n in wf.values() if n["class_type"] == "TextEncodeQwenImage21")["inputs"]["prompt"]
    # 2) 指令改图：父版本 = 图1 + 底图，denoise 小
    j2 = _job(c, {"stage": "first", "mode": "instruct", "instruction": "保持构图，提高画面清晰度", "strength": "small"})
    assert j2["state"] == "done", j2
    t2 = j2["take"]
    assert (t2["parent"], t2["mode"], t2["strength"], t2["instruction"]) == (t1["n"], "instruct", "small",
                                                                              "保持构图，提高画面清晰度")
    wf2 = clients[0][-1].workflows[-1]
    assert wf2["37"]["inputs"]["sigmas"] == "0.35, 0" and "110" in wf2
    enc = next(n for n in wf2.values() if n["class_type"] == "TextEncodeQwenImage21")["inputs"]
    assert enc["prompt"] == "保持构图，提高画面清晰度" and "images.image_1" in enc
    takes = P.load_takes(SHOT)
    assert takes["active"]["image"] == t2["n"]
    # 3) 尾帧：首帧没定稿 → 409
    assert c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "last", "mode": "regen"}).status_code == 409
    # 4) 定稿 v1（不是当前 v2）→ 设为当前；尾帧由定稿首帧得到
    r = c.post(f"/api/shots/{SHOT}/takes/first/{t1['n']}/lock")
    assert r.status_code == 200 and r.json()["locked"] == {"image": t1["n"]} and r.json()["active"]["image"] == t1["n"]
    j3 = _job(c, {"stage": "last", "mode": "regen"})
    assert j3["state"] == "done", j3
    assert j3["take"]["stage"] == "last" and j3["take"]["from_first"] == t1["n"]
    assert c.post(f"/api/shots/{SHOT}/takes/last/{j3['take']['n']}/lock").status_code == 200
    assert FE.frames_ready(SHOT) == (True, "")
    # 5) 换定稿首帧 → 尾帧过期，出视频前不就绪
    r = c.post(f"/api/shots/{SHOT}/takes/first/{t2['n']}/lock").json()
    assert r["stale"]["last"]["first"] == t2["n"]
    ok, why = FE.frames_ready(SHOT)
    assert not ok and "过期" in why
    # 6) 由新定稿首帧重做尾帧 → 过期清掉
    j4 = _job(c, {"stage": "last", "mode": "regen"})
    assert j4["take"]["from_first"] == t2["n"] and "last" not in P.load_takes(SHOT).get("stale", {})
    # 7) 解锁
    r = c.post(f"/api/shots/{SHOT}/takes/first/{t2['n']}/unlock").json()
    assert "image" not in r["locked"]
    shot = c.get(f"/api/shots/{SHOT}").json()
    assert any(t.get("parent") == t1["n"] and t.get("mode") == "instruct" for t in shot["takes"]["takes"])


def test_refs_mode_and_validation(env):
    c, data, clients = env
    assert c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "instruct",
                                                         "instruction": "x"}).status_code == 409   # 还没有首帧
    _job(c, {"stage": "first", "mode": "regen"})
    assert c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "instruct"}).status_code == 422
    assert c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "refs",
                                                         "instruction": "x"}).status_code == 422
    assert c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "regen", "gpu": 2}).status_code == 400
    assert c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "x"}).status_code == 400
    assert c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "instruct", "instruction": "x",
                                                         "parent": 99}).status_code == 404
    ref = data / "uploads" / "r.png"
    _png(ref, (10, 20, 30))
    bad = c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "refs", "instruction": "x",
                                                        "refs": [{"path": "../x.png", "role": "item"}]})
    assert bad.status_code == 422
    j = _job(c, {"stage": "first", "mode": "refs", "instruction": "原话", "refs": [{"path": "uploads/r.png",
                                                                                    "role": "item"}], "gpu": 3})
    assert j["state"] == "done", j
    assert j["gpu"] == 3 and 3 in clients and j["take"]["refs"] == [{"path": "uploads/r.png", "role": "item"}]
    enc = next(n for n in clients[3][-1].workflows[-1].values()
               if n["class_type"] == "TextEncodeQwenImage21")["inputs"]
    assert "images.image_1" in enc and "images.image_2" in enc
    assert "110" not in clients[3][-1].workflows[-1]     # 没给幅度：不以父版本作底图


def test_cancel_queued_and_running(env, monkeypatch):
    c, data, clients = env
    gate = threading.Event()
    made = []

    def factory(gpu):
        made.append(FakeComfy(gpu, block=gate))
        return made[-1]
    monkeypatch.setattr(J, "client_factory", factory)
    from ns_api import frame_jobs as FJ
    monkeypatch.setattr(FJ, "POLL_S", 0.02)
    a = c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "regen"}).json()
    b = c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "regen"}).json()
    assert b["state"] == "queued" and b["eta_s"] >= a["eta_s"]
    t0 = time.time()
    while c.get(f"/api/jobs/{a['job_id']}").json()["state"] != "running" or not (made and made[0].workflows):
        assert time.time() - t0 < 30
        time.sleep(0.02)
    assert c.post(f"/api/jobs/{b['job_id']}/cancel").json()["state"] == "cancelled"
    c.post(f"/api/jobs/{a['job_id']}/cancel")
    ja = _wait(c, a["job_id"])
    assert ja["state"] == "cancelled" and made[0].deleted == ["p1"]
    gate.set()
    assert _wait(c, b["job_id"])["state"] == "cancelled"
    assert not [t for t in P.load_takes(SHOT)["takes"]]


def test_legacy_render_queue_uses_single_candidate(env, monkeypatch):
    """旧 /render 队列（首帧）也走画布规则：1 张、不评分不质检"""
    c, data, clients = env
    fake = FakeComfy()
    job = {"id": "x", "shot_id": SHOT, "stage": "image", "seed": 3, "state": "running"}
    app_mod._run_job(fake, job)
    assert job["state"] == "done", job
    t = P.load_takes(SHOT)["takes"][-1]
    assert len(fake.workflows) == 1 and t["score"] is None and t["qc"] is None and t["mode"] == "regen"


def test_lock_last_from_video_take(env):
    """尾帧挂在视频版本上（视频抽帧 / gpu3 链）时，定稿也要在顶层 locked 里单独记 last"""
    c, data, clients = env
    _job(c, {"stage": "first", "mode": "regen"})
    c.post(f"/api/shots/{SHOT}/takes/first/1/lock")
    rel = f"renders/ep02/S1/takes/video_001_last.png"
    _png(data / rel)
    P._add_take(SHOT, P.Take(n=1, stage="video", file="renders/ep02/S1/takes/video_001.mp4", seed=1, prompt="",
                             created_at=P.now(), last_frame=rel), activate=False)
    r = c.post(f"/api/shots/{SHOT}/takes/last/1/lock", json={"from_stage": "video"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["locked"]["last"] >= 1 and j["locked"]["image"] == 1
    assert j["locked_src"]["last"] == {"stage": "video", "n": 1, "chain": "canvas", "file": rel}
    g3 = data / "renders_gpu3" / "ep02" / "S1" / "last.png"
    _png(g3)
    j = c.post(f"/api/shots/{SHOT}/takes/last/0/lock", json={"chain": "gpu3",
                                                           "file": "renders_gpu3/ep02/S1/last.png"}).json()
    assert j["locked_src"]["last"]["chain"] == "gpu3"
    assert c.post(f"/api/shots/{SHOT}/takes/last/0/lock", json={"chain": "gpu3", "file": "../x.png"}).status_code == 404
    assert FE.frames_ready(SHOT)[0]


def test_refs_asset_id_resolved_by_w5(env, monkeypatch):
    """refs[].asset_id 经 W5 的 assets.resolve_asset_ref 解析；解析不到时把 asset_id 当路径兜底；都不行 422"""
    from ns_api import assets as AS
    c, data, clients = env
    _job(c, {"stage": "first", "mode": "regen"})
    _png(data / "uploads" / "shoe.png", (5, 5, 5))
    asked = []
    monkeypatch.setattr(AS, "resolve_asset_ref",
                        lambda aid: (asked.append(aid), "uploads/shoe.png" if aid == "lin_wan:shoes:b" else None)[1])
    j = _job(c, {"stage": "first", "mode": "refs", "instruction": "原话",
                 "refs": [{"asset_id": "lin_wan:shoes:b", "role": "item"}]})
    assert j["state"] == "done", j
    assert j["take"]["refs"] == [{"asset_id": "lin_wan:shoes:b", "path": "uploads/shoe.png", "role": "item",
                                  "resolved_from": "asset"}] and asked == ["lin_wan:shoes:b"]
    j = _job(c, {"stage": "first", "mode": "refs", "instruction": "原话",
                 "refs": [{"asset_id": "uploads/shoe.png", "role": "style"}]})
    assert j["take"]["refs"][0]["resolved_from"] == "path"
    r = c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "mode": "refs", "instruction": "x",
                                                      "refs": [{"asset_id": "nope", "role": "item"}]})
    assert r.status_code == 422 and "nope" in r.json()["detail"]
