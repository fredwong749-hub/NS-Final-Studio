"""fredw-92/LS：长镜头不截短（项目方“长镜头长度模型决定，不限定时长”）。

- 帧数一律按剧本时长（frames_for_seconds，最长 362）；
- 每条道的实测上限在 config/render_endpoints.json（gpus 道写 "max_frames": {"3": 243}，其他服务器道写在 lanes 记录里）；
- 超过本道上限 → video_jobs.route_long 改派长镜头道（params.route 记 rerouted_from）；一条都没有 → 409；
- h3_video.render 在道上限不够时报错（不偷偷出短版），take.params 记 method / lane_max_frames。
假 ComfyUI，不碰 GPU。
"""
from __future__ import annotations

import json

import pytest
from fastapi import HTTPException

from ns_api import jobs as J
from ns_api import video_jobs as VJ
from ns_render import endpoints as EP
from ns_render import h3_video as HV
from ns_render import pipeline as P
from ns_render.comfy_client import ComfyError
from ns_schema.h3_lint import frames_for_seconds

from test_readiness import env, script  # noqa: F401  复用夹具
from test_video_jobs_v1 import SHOT, FakeComfy, _NoVram, _frame, _wait

CFG = {"image": {"url": "http://127.0.0.1:18188", "gpu": 0}, "video": {"url": "http://127.0.0.1:18191", "gpu": 3},
       "gpus": {"0": "http://127.0.0.1:18188", "1": "http://127.0.0.1:18189", "3": "http://127.0.0.1:18191"},
       "max_frames": {"0": 243, "1": 243, "3": 243},
       "lanes": {"gpu36:0": "http://127.0.0.1:18288",
                 "gpu36:2": {"url": "http://127.0.0.1:18290", "max_frames": 362, "label": "长镜头道 --novram"}}}


@pytest.fixture
def cfg(tmp_path, monkeypatch):
    p = tmp_path / "render_endpoints.json"
    p.write_text(json.dumps(CFG), encoding="utf-8")
    monkeypatch.setattr(EP, "CONFIG", p)
    from ns_api import llm_config as LC
    monkeypatch.setattr(LC, "RENDER_FILE", p)
    for k in ("NS_COMFY_URL", "NS_COMFY_URL_GPU0", "NS_COMFY_URL_GPU1", "NS_COMFY_URL_GPU3"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setattr(J, "lanes", lambda probe=True: [{"gpu": g, "ok": True, "load_s": 0} for g in J.GPUS])
    return p


def test_frames_never_capped():
    for s in (8, 10, 12, 15):
        assert HV.frames_for(s) == (frames_for_seconds(s), frames_for_seconds(s))
    assert HV.frames_for(12) == (294, 294) and HV.frames_for(15) == (362, 362)
    assert not hasattr(HV, "safe_max_frames")          # 192 帧硬上限已删


def test_lane_max_frames_and_long_lanes(cfg):
    assert EP.max_frames(3) == 243 and EP.max_frames("gpu36:2") == 362
    assert EP.max_frames("gpu36:0") == EP.DEFAULT_MAX_FRAMES == 192      # 没测过的道按保守值
    assert EP.long_lanes(294) == ["gpu36:2"]
    assert EP.long_lanes(243)[:3] == [0, 1, 3] and EP.long_lanes(243)[-1] == "gpu36:2"   # 够用就不占最长的
    assert EP.long_lanes(363) == []


def test_route_long(cfg, monkeypatch):
    assert VJ.route_long(3, 243) == {"lane": 3, "lane_max_frames": 243}
    r = VJ.route_long(3, 294)
    assert r == {"lane": "gpu36:2", "lane_max_frames": 362, "rerouted_from": "gpu33:3"}
    # 长镜头道探测不到也照样按配置派（不挡提交）
    monkeypatch.setattr(J, "lanes", lambda probe=True: (_ for _ in ()).throw(RuntimeError("tunnel down")))
    assert VJ.route_long(1, 362)["lane"] == "gpu36:2"
    # 没有长镜头道 → 409，不截短
    cfg.write_text(json.dumps({k: v for k, v in CFG.items() if k != "lanes"}), encoding="utf-8")
    with pytest.raises(HTTPException) as e:
        VJ.route_long(3, 294)
    assert e.value.status_code == 409 and "没有长镜头道" in e.value.detail


@pytest.fixture()
def fake36(env, cfg, monkeypatch):
    c, data, _ = env
    fc = FakeComfy()
    monkeypatch.setattr(J, "client_factory", lambda gpu: fc)
    monkeypatch.setattr(P, "extract_last_frame", lambda v, out: None)
    monkeypatch.setattr(HV, "VramSampler", _NoVram)
    _frame(data, SHOT, "image", 1)
    _frame(data, SHOT, "last", 1)
    return c, data, fc


def test_12s_shot_full_length_on_long_lane(fake36):
    c, data, fc = fake36
    # base 写明 official_base：本测验的是 RR 配方（24 步只给首帧）；项目方 2026-11-01 起默认基底 = pika_flex
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"seconds": 12, "gpu": 3, "base": "official_base"})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["gpu"] == "gpu36:2" and job["params"]["frames"] == 294
    assert job["params"]["route"]["rerouted_from"] == "gpu33:3" and job["params"]["method"] == "single"
    j = _wait(c, job["job_id"])
    assert j["state"] == "done", j.get("error")
    wf = fc.submitted[-1]
    assert wf["131"]["inputs"]["length"] == 294                       # 剧本 12 s，一帧不少
    # RR 2026-10-31：默认 = 基模 24 步只给首帧 → 第一行是 I2VA 对齐句（正文不动）
    assert wf["131"]["inputs"]["prompt"].split("\n", 1)[0] == HV.I2V_ALIGN_LINE
    assert wf["124"]["inputs"]["steps"] == 24 and "last_frame" not in wf["131"]["inputs"]
    t = next(t for t in P.load_takes(SHOT)["takes"] if t["stage"] == "video")
    assert t["params"]["frames"] == t["params"]["frames_requested"] == 294
    assert t["params"]["frames_capped"] is False and t["params"]["method"] == "single"
    assert t["params"]["lane_max_frames"] == 362 and t["gpu"] == "gpu36:2"


def test_short_shot_stays_on_requested_lane(fake36):
    c, data, fc = fake36
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"seconds": 10, "gpu": 1})
    assert r.status_code == 200 and r.json()["gpu"] == 1 and "rerouted_from" not in r.json()["params"]["route"]
    assert _wait(c, r.json()["job_id"])["state"] == "done"
    assert fc.submitted[-1]["131"]["inputs"]["length"] == 243


def test_render_refuses_over_lane_limit_instead_of_capping(fake36):
    c, data, fc = fake36
    with pytest.raises(ComfyError, match="不截短"):
        HV.render(fc, VJ.get_script(), SHOT, seconds=12, gpu=3)
    assert fc.submitted == []


def test_timeout_scales_with_frames():
    assert HV.timeout_for(192) == HV.TIMEOUT_S
    assert HV.timeout_for(362) > 2 * HV.TIMEOUT_S


def test_long_only_lane_not_used_for_images_or_short_video(cfg):
    import copy
    c2 = copy.deepcopy(CFG)
    c2["lanes"]["gpu36:2"]["long_only"] = True
    cfg.write_text(json.dumps(c2), encoding="utf-8")
    assert EP.long_only("gpu36:2") and not EP.long_only("gpu36:0") and not EP.long_only(3)
    busy = {0, 1, 3, "gpu36:0"}
    lst = [{"gpu": g, "ok": True, "load_s": 840 if g in busy else 0, "max_frames": EP.max_frames(g),
            "long_only": EP.long_only(g), "image_pref": g == 0} for g in J.GPUS]
    assert J.pick_lane("image", lane_list=lst) != "gpu36:2"            # 只有长镜头道空闲也不派出图
    assert J.pick_lane("video", 243, lane_list=lst) != "gpu36:2"       # 短视频排别的道
    assert J.pick_lane("video", 294, lane_list=lst) == "gpu36:2"       # 长视频才去


def test_long_shot_no_lora_base_gets_patch_lora(fake36):
    """RR：无 LoRA 基底 294 帧 → 自动挂 long_patch_lora（1e-4，走 LoRA 补丁路径防 --novram OOM）；短镜头不挂"""
    from ns_render import workflows as W
    c, data, fc = fake36
    lp = HV.base_spec("official_base")["long_patch_lora"]
    fc.object_info = lambda: {"LoraLoaderModelOnly": {"input": {"required": {
        "lora_name": [[W.H3_TURBO_8STEP_768P, lp["name"]]]}}}}
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"seconds": 12, "gpu": 3, "base": "official_base"})
    assert r.status_code == 200, r.text
    assert _wait(c, r.json()["job_id"])["state"] == "done"
    lo = [v["inputs"] for v in fc.submitted[-1].values() if v["class_type"] == "LoraLoaderModelOnly"]
    assert [(x["lora_name"], x["strength_model"]) for x in lo] == [(lp["name"], lp["strength"])]
    r = c.post(f"/api/shots/{SHOT}/video-jobs", json={"seconds": 8, "gpu": 3, "base": "official_base"})
    assert _wait(c, r.json()["job_id"])["state"] == "done"
    assert not [v for v in fc.submitted[-1].values() if v["class_type"] == "LoraLoaderModelOnly"]
