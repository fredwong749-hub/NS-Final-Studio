"""fredw-92/PF：视频基底（official_turbo | pika_flex）。假 ComfyUI 客户端，不碰 GPU。"""
from __future__ import annotations

import pytest

from ns_render import h3_video as HV
from ns_render import pipeline as P
from ns_render import workflows as W

from test_readiness import PNG, env, script  # noqa: F401  复用夹具
from test_video_jobs_v1 import SHOT, FakeComfy, _frame, _wait, fake  # noqa: F401

FLEX = "pika_h3_flex_fl2va_comfy_bf16.safetensors"
FLEX_SIGMAS = "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0"
VBVR = "H3-Licon-VBVR-I2V.safetensors"


def _lane(fc, *names):
    fc.object_info = lambda: {"LoraLoaderModelOnly": {"input": {"required": {
        "lora_name": [[W.H3_TURBO_8STEP_768P, *names]]}}}}


def _ready(data):
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)


def test_config_bases():
    vb = HV.video_bases()
    assert vb["default"] == "pika_flex"     # 项目方 2026-11-01：“把 Flex 设成默认基底”（之前 RR 10-31 = official_base）
    assert HV.base_spec(None)["id"] == "pika_flex" and HV.base_spec("official_turbo")["default_last_frame_mode"] == "use"
    ids = [b["id"] for b in vb["bases"]]
    assert ids[:2] == ["official_turbo", "pika_flex"]
    f = HV.base_spec("pika_flex")
    assert f["lora"] == FLEX and f["steps"] == 6 and f["sampler"] == "lcm" and f["sigmas"] == FLEX_SIGMAS
    assert f["shift"] == [12.0, 3.0] and f["shift_node"] is False and f["lora_strength"] == 1.0
    assert f["source_url"].startswith("https://huggingface.co/Pika-Labs/") and "MiniMax H3" in f["license"]
    assert len(f["sha256"]) == 64
    # sigma 表 = knots/1000 经 shift 12 变换（官方 comfy/README：1000/750/500/250/100/40/0、video shift 12）
    want = [12 * t / (1 + 11 * t) for t in (1.0, .75, .5, .25, .1, .04, 0.0)]
    got = [float(x) for x in f["sigmas"].split(",")]
    assert all(abs(a - b) < 1e-5 for a, b in zip(got, want))
    with pytest.raises(KeyError):
        HV.base_spec("nope")


def test_default_build_unchanged():
    a = HV.build("p", "f.png", "l.png", 158, 1, "x")
    b = HV.build("p", "f.png", "l.png", 158, 1, "x", base="official_turbo")
    assert a == b
    assert a["124"]["class_type"] == "BasicScheduler" and a["150"]["inputs"]["shift_video"] == 6.0
    assert a["123"]["inputs"]["sampler_name"] == "euler"


def test_flex_graph_matches_official_template():
    wf = HV.build("p", "f.png", "l.png", 158, 1, "x", base="pika_flex", steps=8, lora_strength=0.5)
    lo = [v["inputs"] for v in wf.values() if v["class_type"] == "LoraLoaderModelOnly"]
    assert lo == [{"model": ["127", 0], "lora_name": FLEX, "strength_model": 1.0}]   # 无 Turbo；步数/强度不可改
    assert "150" not in wf   # 官方模板没有 SigmaShift
    assert wf["124"] == {"class_type": "ManualSigmas", "inputs": {"sigmas": FLEX_SIGMAS}}
    assert wf["123"]["inputs"]["sampler_name"] == "lcm"
    assert wf["126"]["inputs"]["model"] == ["140", 0] and wf["126"]["class_type"] == "BasicGuider"
    assert wf["131"]["inputs"]["last_frame"] == ["203", 0]


def test_flex_cannot_stack_turbo():
    m = HV.base_model(HV.base_spec("pika_flex"))
    from dataclasses import replace
    with pytest.raises(ValueError, match="Turbo"):
        W.check_h3_model(replace(m, loras=(*m.loras, (W.H3_TURBO_8STEP_768P, 1.0))))
    with pytest.raises(ValueError, match="7"):
        W.check_h3_model(replace(m, sigmas="1.0, 0.5, 0.0"))


def test_api_flex_job_records_params(fake):
    c, data, fc = fake
    _ready(data)
    _lane(fc, FLEX, VBVR)
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"base": "pika_flex", "seed": 11,
                                                       "loras": [{"name": VBVR, "strength": 0.7}]})
    assert r.status_code == 200, r.text
    assert r.json()["params"]["base"] == "pika_flex"
    j = _wait(c, r.json()["job_id"])
    assert j["state"] == "done", j.get("error")
    wf = fc.submitted[0]
    lo = sorted((k for k, v in wf.items() if v["class_type"] == "LoraLoaderModelOnly"), key=int)
    assert [wf[k]["inputs"]["lora_name"] for k in lo] == [FLEX, VBVR]
    assert wf["124"]["class_type"] == "ManualSigmas" and "150" not in wf
    t = next(t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "video")
    p = t["params"]
    assert p["base"] == "pika_flex" and p["steps"] == 6 and p["lora_strength"] == 1.0 and p["seed"] == 11
    bp = p["base_params"]
    assert bp["lora"] == FLEX and bp["sampler"] == "lcm" and bp["sigmas"] == FLEX_SIGMAS
    assert bp["shift"] == [12.0, 3.0] and bp["shift_node"] is False and bp["scheduler"] is None and bp["experimental"]
    assert p["model"]["turbo_lora"] is None and p["model"]["base_lora"] == FLEX


def test_api_default_job_is_flex(fake):
    """项目方 2026-11-01“把 Flex 设成默认基底”：不传 base = pika_flex（6 步、lcm、官方 sigma、首尾帧都给）"""
    c, data, fc = fake
    _ready(data)
    _lane(fc, FLEX)
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={})
    assert r.status_code == 200, r.text
    assert r.json()["params"]["base"] == "pika_flex" and r.json()["params"]["last_frame_mode"] == "use"
    assert _wait(c, r.json()["job_id"])["state"] == "done"
    wf = fc.submitted[0]
    assert [v["inputs"]["lora_name"] for v in wf.values() if v["class_type"] == "LoraLoaderModelOnly"] == [FLEX]
    assert wf["124"] == {"class_type": "ManualSigmas", "inputs": {"sigmas": FLEX_SIGMAS}}
    t = next(t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "video")
    assert t["params"]["base"] == "pika_flex" and t["params"]["steps"] == 6


def test_api_official_base_first_frame_only(fake):
    """RR 2026-10-31 配方（现在要显式 base official_base）：基模 24 步、无蒸馏 LoRA、只给首帧（I2VA 对齐句）"""
    c, data, fc = fake
    _ready(data)
    _lane(fc)
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"base": "official_base"})
    assert r.status_code == 200, r.text
    assert r.json()["params"]["base"] == "official_base" and r.json()["params"]["last_frame_mode"] == "none"
    j = _wait(c, r.json()["job_id"])
    assert j["state"] == "done", j.get("error")
    wf = fc.submitted[0]
    assert not [v for v in wf.values() if v["class_type"] == "LoraLoaderModelOnly"]
    assert wf["124"]["inputs"]["steps"] == 24 and "last_frame" not in wf["131"]["inputs"]
    assert wf["131"]["inputs"]["prompt"].split("\n", 1)[0] == HV.I2V_ALIGN_LINE
    t = next(t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "video")
    assert t["params"]["base"] == "official_base" and t["params"]["last_frame_used"] is False and t["params"]["steps"] == 24


def test_api_old_recipe_still_selectable(fake):
    """旧配方：base official_turbo（Turbo 8 步 + 首尾帧）仍可选"""
    c, data, fc = fake
    _ready(data)
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"base": "official_turbo"})
    assert r.status_code == 200 and r.json()["params"]["base"] == "official_turbo"
    assert r.json()["params"]["last_frame_mode"] == "use"
    j = _wait(c, r.json()["job_id"])
    assert j["state"] == "done", j.get("error")
    t = next(t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "video")
    assert t["params"]["base"] == "official_turbo" and t["params"]["model"]["turbo_lora"] == W.H3_TURBO_8STEP_768P
    assert t["params"]["base_params"]["shift"] == [6.0, 3.0] and t["params"]["base_params"]["sampler"] == "euler"
    assert fc.submitted[0]["124"]["class_type"] == "BasicScheduler"


def test_api_flex_validation(fake):
    c, data, fc = fake
    _ready(data)
    url = f"/api/shots/{SHOT}/video-jobs"
    assert c.post(url, json={"base": "nope"}).status_code == 422
    _lane(fc)                                               # 道上只有 Turbo
    r = c.post(url, json={"base": "pika_flex"})            # 道上没有 Flex LoRA
    assert r.status_code == 422 and FLEX in r.json()["detail"]
    _lane(fc, FLEX)
    assert c.post(url, json={"base": "pika_flex", "steps": 8}).status_code == 422
    assert c.post(url, json={"base": "pika_flex", "lora_strength": 0.8}).status_code == 422
    assert c.post(url, json={"base": "pika_flex", "loras": [{"name": W.H3_TURBO_8STEP_768P, "strength": 1}]}).status_code == 422
    assert c.post(url, json={"base": "pika_flex", "loras": [{"name": FLEX, "strength": 1}]}).status_code == 422
    assert fc.submitted == []
    assert c.post(url, json={"base": "pika_flex", "steps": 6, "lora_strength": 1.0}).status_code == 200


def test_video_bases_route(fake):
    c, _, _ = fake
    d = c.get("/api/video-bases").json()
    assert d["default"] == "pika_flex" and {b["id"] for b in d["bases"]} >= {"official_turbo", "pika_flex"}


def test_official_base_no_lora():
    """MOT：official_base = 不挂蒸馏 LoRA 的基模（RR：24 步、shift 12/3、euler/simple、BasicGuider）"""
    f = HV.base_spec("official_base")
    assert f["lora"] is None and f["no_lora"] is True and f["steps"] == 24 and f["shift"] == [12.0, 3.0]
    wf = HV.build("p", "f.png", "l.png", 158, 1, "x", base="official_base")
    assert not [v for v in wf.values() if v["class_type"] == "LoraLoaderModelOnly"]
    assert wf["150"]["inputs"]["shift_video"] == 12.0 and wf["150"]["inputs"]["shift_audio"] == 3.0
    assert wf["124"]["inputs"]["steps"] == 24 and wf["123"]["inputs"]["sampler_name"] == "euler"
    wf30 = HV.build("p", "f.png", "l.png", 158, 1, "x", base="official_base", steps=30)
    assert wf30["124"]["inputs"]["steps"] == 30   # 步数可调


def test_api_official_base_job(fake):
    c, data, fc = fake
    _ready(data)
    _lane(fc)
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"base": "official_base", "seed": 5})
    assert r.status_code == 200, r.text
    j = _wait(c, r.json()["job_id"])
    assert j["state"] == "done", j.get("error")
    assert not [v for v in fc.submitted[0].values() if v["class_type"] == "LoraLoaderModelOnly"]
    assert fc.submitted[0]["124"]["inputs"]["steps"] == 24 and fc.submitted[0]["150"]["inputs"]["shift_video"] == 12.0
    t = next(t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "video")
    p = t["params"]
    assert p["base"] == "official_base" and p["base_params"]["lora"] is None and p["steps"] == 24
    assert p["model"]["turbo_lora"] is None and p["model"]["base_lora"] is None
    assert p["last_frame_mode"] == "none" and p["last_frame_used"] is False   # 基底默认只给首帧
    assert "last_frame" not in fc.submitted[0]["131"]["inputs"]


def test_api_official_base_keeps_requested_last_frame(fake):
    c, data, fc = fake
    _ready(data)
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"base": "official_base", "last_frame_mode": "use"})
    assert r.status_code == 200, r.text
    assert _wait(c, r.json()["job_id"])["state"] == "done"
    assert "last_frame" in fc.submitted[0]["131"]["inputs"]


def test_timeout_scales_with_base_steps():
    """RR：基模 24 步每镜约 41 min（常排在别人的任务后）→ 等待上限按步数放宽；Turbo 8 步不变"""
    assert HV.timeout_for(192) == HV.timeout_for(192, 8) == HV.TIMEOUT_S
    assert HV.timeout_for(192, 24) == 2 * HV.TIMEOUT_S
    assert HV.timeout_for(294, 24) > HV.timeout_for(294)
    assert HV.default_last_frame_mode(HV.base_spec(None)) == "use"          # 默认 = pika_flex
    assert HV.default_last_frame_mode(HV.base_spec("official_base")) == "none"
    assert HV.default_last_frame_mode(HV.base_spec("official_turbo")) == "use"
    assert HV.default_last_frame_mode(HV.base_spec("pika_flex")) == "use"
    assert HV.default_last_frame_mode(HV.base_spec(None), "auto") == "auto"
