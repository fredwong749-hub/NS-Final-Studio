"""fredw-92/Q1：画布出图两档（预览 / 定稿）+ 成集装配默认逐镜校色。全部假 ComfyUI / 假 ffmpeg 结果，不占 GPU。
- tier 路由：frame-jobs tier=final、lock {final:true}、POST …/final；默认 preview 仍是 Turbo 单遍
- 定稿档图：Base int8、35 步、cfg 3.0、texture-fix VAE、两段式节点（928×1632 → lanczos 1152×2016、denoise 0.30、14 步）、
  预览版作底图 + 图1、LoRA 集合（krea2 0.5 前置、lin_wan_qi_v1 0.8、禁 glamour、上限 1.6）
- 定稿版接替定稿；由预览版做的尾帧不算过期
- 装配：config 默认开校色、按集关、CLI 覆盖；colormatch 先用定稿关键帧"""
import json
import sys
from pathlib import Path

import pytest

from ns_render import final_tier as FT
from ns_render import frame_edit as FE
from ns_render import pipeline as P
from ns_render import workflows as W

sys.path.insert(0, str(P.ROOT / "services" / "post"))
CFG = json.loads((P.ROOT / "config" / "render_quality.json").read_text(encoding="utf-8"))
FINAL = CFG["tiers"]["final"]


# ---------------------------------------------------------------- 配置 = gpu3 生产值

def test_final_tier_values_match_gpu3_production():
    assert FINAL["unet"] == "qwen_image_2.1_int8_convrot.safetensors"
    assert (FINAL["steps"], FINAL["cfg"]) == (35, 3.0)
    assert FINAL["vae"] == "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"
    assert FINAL["pass1_size"] == [928, 1632] and FINAL["pass2_size"] == [1152, 2016]
    assert (FINAL["pass2_denoise"], FINAL["init_denoise"]) == (0.30, 0.5)
    assert FT.pass2_steps(FINAL) == 14                        # WR max(8, int(35 × 0.4))
    assert FINAL["realism_loras"] == [["krea2_film_texture_qwen21.safetensors", 0.5]]
    assert "glamour_realism_qwen21.safetensors" in FINAL["banned_loras"]
    assert FINAL["identity_loras"] == {"lin_wan_qi_v1.safetensors": 0.8} and FINAL["lora_cap"] == 1.6
    assert FINAL["grade"]["strength"] == 0.6 and FINAL["grain"] is False
    assert CFG["default_tier"] == "preview" and CFG["post"]["color_match"]["default"] is True
    for k in ("unet_src", "steps_src", "pass1_src", "pass2_src", "realism_src", "lora_cap_src", "grade_src"):
        assert any(r in FINAL[k] for r in ("D1", "D2", "D3", "D4", "B5")), k


def test_final_loras_set_and_cap():
    avail = {"krea2_film_texture_qwen21.safetensors", "lin_wan_qi_v1.safetensors", "a.safetensors"}
    shot = [("lin_wan_qi_v1.safetensors", 0.6), ("glamour_realism_qwen21.safetensors", 0.5),
            ("a.safetensors", 1.2), ("krea2_film_texture_qwen21.safetensors", 0.9)]
    out = FT.final_loras(shot, avail, FINAL)
    assert out[0] == ("krea2_film_texture_qwen21.safetensors", 0.5)      # 写实 LoRA 前置、配置强度
    names = [f for f, _ in out]
    assert "glamour_realism_qwen21.safetensors" not in names and names.count("krea2_film_texture_qwen21.safetensors") == 1
    rest = dict(out[1:])
    assert abs(sum(rest.values()) - 1.6) < 0.01                          # 0.8 + 1.2 = 2.0 → 按比例到 1.6
    assert abs(rest["lin_wan_qi_v1.safetensors"] / rest["a.safetensors"] - 0.8 / 1.2) < 0.01
    # ComfyUI 没有 krea2 → 不加；身份 LoRA 单独时 0.8 不缩
    assert FT.final_loras([("lin_wan_qi_v1.safetensors", 0.6)], {"lin_wan_qi_v1.safetensors"}, FINAL) == \
        [("lin_wan_qi_v1.safetensors", 0.8)]


def test_qwen_final_graph_two_stage_nodes():
    m = FT.final_model(FINAL)
    wf = W.qwen_final("p", "neg", ["ref.png"], "init.png", 41, "x", m, [("k.safetensors", 0.5)],
                      pass1_size=(928, 1632), pass2_size=(1152, 2016), init_denoise=0.5, pass2_denoise=0.3,
                      pass2_steps=14)
    assert wf["10"]["inputs"]["unet_name"] == "qwen_image_2.1_int8_convrot.safetensors"
    assert wf["12"]["inputs"]["vae_name"] == FINAL["vae"]
    assert wf["38"]["inputs"]["cfg"] == 3.0 and wf["37"]["class_type"] == "BasicScheduler"
    assert wf["37"]["inputs"]["steps"] == 35 and wf["37"]["inputs"]["denoise"] == 0.5
    assert (wf["111"]["inputs"]["width"], wf["111"]["inputs"]["height"]) == (928, 1632)   # 第一遍 ≈1.5 MP
    assert wf["40"]["inputs"]["latent_image"] == ["112", 0] and wf["110"]["inputs"]["image"] == "init.png"
    assert wf["20"]["inputs"]["images.image_1"] == ["101", 0] and wf["101"]["inputs"]["image"] == "ref.png"
    assert wf["20"]["inputs"]["negative_prompt"] == "neg"
    assert wf["50"]["inputs"] == {"image": ["41", 0], "upscale_method": "lanczos", "width": 1152, "height": 2016,
                                  "crop": "disabled"}
    assert wf["53"]["inputs"]["steps"] == 14 and wf["53"]["inputs"]["denoise"] == 0.3
    assert wf["52"]["inputs"]["noise_seed"] == 42 and wf["54"]["inputs"]["latent_image"] == ["51", 0]
    assert wf["90"]["inputs"]["images"] == ["55", 0]
    with pytest.raises(ValueError):
        W.qwen_final("p", "", [], "i", 1, "x", W.QwenModel(), [], pass1_size=(8, 8), pass2_size=(8, 8),
                     init_denoise=0.5, pass2_denoise=0.3, pass2_steps=8)


def test_source_prompt_override_vs_script():
    data = {"takes": [{"stage": "image", "n": 1, "mode": "regen", "prompt": "整段替换原话", "basis_prompt": "编译"},
                      {"stage": "image", "n": 2, "mode": "instruct", "parent": 1, "prompt": "改一下"},
                      {"stage": "image", "n": 3, "mode": "regen", "prompt": "编译"}]}
    assert FT.source_prompt(data, data["takes"][1], "编译") == ("整段替换原话", "override")
    assert FT.source_prompt(data, data["takes"][2], "编译") == ("编译", "script")


def test_first_equivalents():
    data = {"takes": [{"stage": "image", "n": 1}, {"stage": "image", "n": 2, "mode": "final", "parent": 1}]}
    assert FE.first_equivalents(data, 2) == {1, 2} and FE.first_equivalents(data, 1) == {1}


# ---------------------------------------------------------------- API：tier 路由（复用 W2 的假 ComfyUI）

from tests.test_frame_jobs_w2 import SHOT, _job, _wait, env  # noqa: E402,F401




def _avail(monkeypatch):
    """假 ComfyUI 的 LoRA 列表加上 krea2 / glamour（W2 的 FakeComfy 只有林晚 LoRA）"""
    from tests import test_frame_jobs_w2 as T
    orig = T.FakeComfy.object_info

    def object_info(self):
        d = orig(self)
        d["LoraLoaderModelOnly"]["input"]["required"]["lora_name"][0] += [
            "krea2_film_texture_qwen21.safetensors", "glamour_realism_qwen21.safetensors"]
        return d
    monkeypatch.setattr(T.FakeComfy, "object_info", object_info)


@pytest.mark.skipif(not P.SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
def test_tier_routing_and_final_replaces_lock(env, monkeypatch):
    c, data, clients = env
    _avail(monkeypatch)
    # 预览档（默认）：Turbo 单遍
    t1 = _job(c, {"stage": "first", "mode": "regen", "seed": 7})["take"]
    wf = clients[0][-1].workflows[-1]
    assert wf["10"]["inputs"]["unet_name"].startswith("qwen_image_2.1_turbo") and "53" not in wf
    # tier 校验
    assert c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "tier": "x"}).status_code == 400
    assert c.post(f"/api/shots/{SHOT}/frame-jobs",
                  json={"stage": "first", "tier": "final", "mode": "instruct", "instruction": "a"}).status_code == 400
    # 定稿预览版 → 尾帧（由预览版）→ 定稿尾帧
    assert c.post(f"/api/shots/{SHOT}/takes/first/{t1['n']}/lock").status_code == 200
    last = _job(c, {"stage": "last", "mode": "regen"})["take"]
    assert c.post(f"/api/shots/{SHOT}/takes/last/{last['n']}/lock").status_code == 200
    # 出定稿版（tier=final，父版本默认 = 定稿版）
    r = c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "tier": "final"})
    assert r.status_code == 200, r.text
    j = _wait(c, r.json()["job_id"])
    assert j["state"] == "done", j
    tf = j["take"]
    assert (tf["mode"], tf["parent"], tf["seed"], tf["workflow"]) == ("final", t1["n"], t1["seed"], FT.FINAL_WORKFLOW)
    assert tf["params"]["tier"] == "final" and tf["params"]["steps"] == 35 and tf["params"]["pass2_steps"] == 14
    assert tf["raw_file"] and tf["grade"]["strength"] == 0.6 and tf["file"].endswith("_final.png")
    wf = clients[0][-1].workflows[-1]
    assert wf["10"]["inputs"]["unet_name"] == "qwen_image_2.1_int8_convrot.safetensors"
    assert wf["37"]["inputs"]["steps"] == 35 and wf["38"]["inputs"]["cfg"] == 3.0
    assert wf["53"]["inputs"]["denoise"] == 0.3 and wf["50"]["inputs"]["upscale_method"] == "lanczos"
    loras = [(n["inputs"]["lora_name"], n["inputs"]["strength_model"]) for n in wf.values()
             if n["class_type"] == "LoraLoaderModelOnly"]
    assert loras[0] == ("krea2_film_texture_qwen21.safetensors", 0.5)
    assert ("lin_wan_qi_v1.safetensors", 0.8) in loras
    assert all("glamour" not in f for f, _ in loras) and sum(s for f, s in loras[1:]) <= 1.6 + 1e-6
    enc = wf["20"]["inputs"]
    assert enc["prompt"].startswith(FT.FINAL_ROLE) and "images.image_1" in enc
    # 定稿版接替定稿；预览版做的尾帧不过期
    tk = P.load_takes(SHOT)
    assert tk["locked"]["image"] == tf["n"] and tk["active"]["image"] == tf["n"]
    assert "last" not in (tk.get("stale") or {}) and FE.frames_ready(SHOT) == (True, "")
    shot = c.get(f"/api/shots/{SHOT}").json()
    lt = next(t for t in shot["takes"]["takes"] if t["stage"] == "last" and t["n"] == last["n"])
    assert "首帧已换" not in (lt.get("stale") or [])
    # 已是定稿档 → 409
    assert c.post(f"/api/shots/{SHOT}/takes/first/{tf['n']}/final").status_code == 409


@pytest.mark.skipif(not P.SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
def test_lock_with_final_flag_and_explicit_action(env, monkeypatch):
    c, data, clients = env
    _avail(monkeypatch)
    t1 = _job(c, {"stage": "first", "mode": "regen", "seed": 3})["take"]
    # 默认（auto_final_on_lock=false）：定稿不排任务
    r = c.post(f"/api/shots/{SHOT}/takes/first/{t1['n']}/lock").json()
    assert "final_job" not in r
    # lock {final:true} → 排定稿档任务
    t2 = _job(c, {"stage": "first", "mode": "regen", "seed": 4})["take"]
    r = c.post(f"/api/shots/{SHOT}/takes/first/{t2['n']}/lock", json={"final": True}).json()
    j = _wait(c, r["final_job"]["job_id"])
    assert j["state"] == "done" and j["tier"] == "final" and j["take"]["parent"] == t2["n"]
    assert P.load_takes(SHOT)["locked"]["image"] == j["take"]["n"]
    # “出定稿版”在非定稿版本上：出定稿档但不改定稿
    j2 = _wait(c, c.post(f"/api/shots/{SHOT}/takes/first/{t1['n']}/final").json()["job_id"])
    assert j2["state"] == "done" and j2["take"]["parent"] == t1["n"]
    assert P.load_takes(SHOT)["locked"]["image"] == j["take"]["n"]
    assert c.post(f"/api/shots/{SHOT}/takes/first/999/final").status_code == 404


# ---------------------------------------------------------------- 装配：默认逐镜校色

def test_color_match_default_on_and_per_episode_switch(tmp_path):
    from ns_post.assemble import Settings, color_match_enabled
    cfgp = tmp_path / "rq.json"
    cfgp.write_text(json.dumps({"post": {"color_match": {"default": True, "per_episode": {"3": False}}}}),
                    encoding="utf-8")
    assert color_match_enabled(1, Settings(), cfgp) is True
    assert color_match_enabled(3, Settings(), cfgp) is False
    assert color_match_enabled(3, Settings(color_match=True), cfgp) is True        # CLI --color-match
    assert color_match_enabled(1, Settings(color_match=False), cfgp) is False      # CLI --no-color-match
    assert Settings().color_match is None and color_match_enabled(1, Settings()) is True   # 真配置：默认开


def test_assembly_calls_colormatch_by_default(monkeypatch, tmp_path):
    """assemble_episode：Settings 不指定 → 按配置开；视频镜头走 _color_match_source"""
    import ns_post.assemble as A
    called = []
    monkeypatch.setattr(A, "_color_match_source", lambda ff, src, idx, w, log: called.append(idx))

    class Stop(Exception):
        pass

    def stop(*a, **k):
        raise Stop
    monkeypatch.setattr(A, "render_segment", stop)

    class FF:
        def info(self, p):
            return {"duration": 5.0, "width": 768, "height": 1344, "has_audio": True}
    ep = {"number": 1, "shots": [{"index": 1, "duration": 5}]}
    with pytest.raises(Stop):
        A.assemble_episode(ep, tmp_path / "out", tts=None, ff=FF(), cache_dir=tmp_path / "c" / "tts",
                           sources={1: {"kind": "video", "path": str(tmp_path / "v.mp4")}}, log=lambda *_: None)
    assert called == [1]
    called.clear()
    with pytest.raises(Stop):
        A.assemble_episode(ep, tmp_path / "out", tts=None, ff=FF(), cache_dir=tmp_path / "c" / "tts",
                           settings=A.Settings(color_match=False),
                           sources={1: {"kind": "video", "path": str(tmp_path / "v.mp4")}}, log=lambda *_: None)
    assert called == []


def test_colormatch_prefers_locked_keyframes(tmp_path):
    from PIL import Image
    from ns_post.colormatch import keyframe_candidates
    data = tmp_path / "data"
    sd = data / "renders" / "ep01" / "S1"
    (sd / "takes").mkdir(parents=True)
    for name in ("image_001.png", "image_002.png", "last_001.png", "frame.png"):
        Image.new("RGB", (8, 8)).save(sd / "takes" / name if name != "frame.png" else sd / name)
    (sd / "takes" / "video_001.mp4").write_bytes(b"x")
    takes = {"active": {"image": 1, "video": 1, "last": 1}, "locked": {"image": 2, "last": 1},
             "takes": [{"stage": "image", "n": 1, "file": "renders/ep01/S1/takes/image_001.png"},
                       {"stage": "image", "n": 2, "file": "renders/ep01/S1/takes/image_002.png", "mode": "final"},
                       {"stage": "last", "n": 1, "file": "renders/ep01/S1/takes/last_001.png"},
                       {"stage": "video", "n": 1, "file": "renders/ep01/S1/takes/video_001.mp4"}]}
    (sd / "takes.json").write_text(json.dumps(takes), encoding="utf-8")
    k = keyframe_candidates(sd / "takes" / "video_001.mp4", data)
    assert k["first"][0][0] == "locked image take 2" and k["last"][0][0] == "locked last take 1"


def test_upscale_4k_commands_only_when_asked(tmp_path):
    from ns_post import upscale4k as U
    clip = tmp_path / "video_003.mp4"
    cmds = U.commands(clip, 2, 4)
    assert cmds[2][:2] == ["ssh", "gpu33"] and "scripts/upscale_4k.py shot" in cmds[2][2]
    assert cmds[-1][-1] == str(tmp_path / "video_003_4k.mp4")
    ran = []
    assert U.upscale(clip, 2, 4, runner=lambda c: ran.append(c), log=lambda *_: None) is None and ran == []
