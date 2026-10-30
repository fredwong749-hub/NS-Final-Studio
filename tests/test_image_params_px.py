"""fredw-92/PX：画布出图参数（预设 + 覆盖）。假 ComfyUI，不占 GPU。
- 项目方 2026-10-31 选定 C（Turbo 8 步官方 sigma、cfg 1、euler、texture_fix VAE、krea2 0.5 + lin_wan_qi_v1 0.6、768×1344、单遍、
  保留规格词）= frame-jobs 预览档默认；旧 A 仍可选
- 校验 422（中文）、工作流改写、take.params.effective 可复现、锐度后处理字段（sharpen / render_scale / detail_pass）"""
import json
import shutil

import pytest

from ns_render import image_params as IP
from ns_render import pipeline as P
from ns_render import workflows as W

C_LORAS = [("krea2_film_texture_qwen21.safetensors", 0.5), ("lin_wan_qi_v1.safetensors", 0.6)]
TEXTURE_VAE = "texture_fix_vae_for_qwen_image_2.1_bf16.safetensors"


def _loras(wf):
    return [(f, s) for _n, f, s in IP._chain(wf)]


# ---------------------------------------------------------------- 配置 / 校验

def test_config_default_is_owner_choice_c():
    q = IP.quality()
    assert q["default_preset"] == "c_turbo_texture" == IP.default_preset()
    c = IP.find_preset("c_turbo_texture")
    assert c["label"] == "C·Turbo 质感（项目方选定）" and "2026-10-31" in c["note"]
    assert IP.find_preset("preview_turbo")["label"] == "预览·Turbo（旧 A）"
    ab = json.loads((P.DATA / "ab" / "texture_ep02_S4" / "settings.json").read_text(encoding="utf-8"))["variants"]["C"] \
        if (P.DATA / "ab" / "texture_ep02_S4" / "settings.json").exists() else None
    eff = IP.resolve("c_turbo_texture", None)
    assert (eff["unet"], eff["steps"], eff["cfg"], eff["sampler"], eff["vae"]) == ("turbo", 8, 1.0, "euler", "texture_fix")
    assert (eff["width"], eff["height"], eff["two_stage"]["enabled"], eff["spec_words"]) == (768, 1344, False, True)
    if ab:
        p = ab["params"]
        assert IP.UNETS[eff["unet"]] == p["unet"] and IP.VAES[eff["vae"]] == p["vae"] and [eff["width"], eff["height"]] == p["size"]
    # 定稿档预设 = Q1 定稿档值
    fin = IP.resolve("final_base_2pass", None)
    assert fin["tier"] == "final" and fin["steps"] == 35 and fin["two_stage"]["first_size"] == [928, 1632]
    cfg = IP.final_cfg_for(fin)
    assert cfg["pass2_steps"] == 14 and cfg["init_denoise"] == 0.5 and cfg["grade"]["strength"] == 0.6


@pytest.mark.parametrize("over,needle", [
    ({"steps": 0, "unet": "base"}, "步数"),
    ({"cfg": 20, "unet": "base"}, "cfg"),
    ({"unet": "x"}, "unet"),
    ({"vae": "y"}, "VAE"),
    ({"bogus": 1}, "不认识的参数"),
    ({"shift": 3.0}, "Turbo"),
    ({"width": 1000}, "16 的倍数"),
    ({"loras": [{"name": "glamour_realism_qwen21.safetensors", "strength": 0.5}]}, "禁用"),
    ({"loras": [{"name": "../x.safetensors", "strength": 0.5}]}, "不合法"),
    ({"loras": [{"name": "a.safetensors", "strength": 5}]}, "强度"),
    ({"sharpen": {"enabled": True, "radius": 50, "amount": 1}}, "锐化半径"),
    ({"render_scale": 3}, "render_scale"),
    ({"detail_pass": {"enabled": True, "denoise": 0.3, "scale": 1.5},
      "two_stage": {"enabled": True}}, "只能开一个"),
    ({"strength": 2}, "重绘幅度"),
])
def test_resolve_rejects_with_chinese(over, needle):
    with pytest.raises(IP.ParamError) as e:
        IP.resolve(None, over)
    assert needle in str(e.value)


def test_final_constraints_and_lora_list_check():
    with pytest.raises(IP.ParamError, match="Base"):
        IP.resolve("final_base_2pass", {"unet": "turbo"})
    with pytest.raises(IP.ParamError, match="整张出"):
        IP.resolve("final_base_2pass", None, mode="instruct")
    with pytest.raises(IP.ParamError, match="没有这个 LoRA"):
        IP.resolve(None, {"loras": [{"name": "nope.safetensors", "strength": 1}]}, allowed={"loras": ["a.safetensors"]})
    # Turbo：步数 / cfg 固定（只记录真实生效的）
    eff = IP.resolve(None, {"steps": 30, "cfg": 4})
    assert (eff["steps"], eff["cfg"]) == (8, 1.0)


# ---------------------------------------------------------------- 工作流

def test_apply_c_on_t2i_and_describe():
    wf = W.qwen_t2i("p", "n", 1088, 1920, 5, "x", loras=[("lin_wan_qi_v1.safetensors", 0.8), ("pose.safetensors", 0.7)])
    eff = IP.resolve("c_turbo_texture", None)
    IP.apply(wf, eff, {"lin_wan_qi_v1.safetensors"})
    assert wf["10"]["inputs"]["unet_name"].startswith("qwen_image_2.1_turbo") and wf["12"]["inputs"]["vae_name"] == TEXTURE_VAE
    assert _loras(wf) == C_LORAS
    assert wf["37"] == {"class_type": "ManualSigmas", "inputs": {"sigmas": W.TURBO_SIGMAS}}
    assert wf["38"]["inputs"]["cfg"] == 1.0 and wf["36"]["inputs"]["sampler_name"] == "euler"
    assert (wf["34"]["inputs"]["width"], wf["34"]["inputs"]["height"]) == (768, 1344) and "53" not in wf
    d = IP.describe(wf)
    assert d["unet"] == "turbo" and d["vae"] == "texture_fix" and d["steps"] == 8 and d["sigmas"] == W.TURBO_SIGMAS
    assert d["loras"] == [{"name": f, "strength": s} for f, s in C_LORAS] and (d["width"], d["height"]) == (768, 1344)
    # None = 不改
    wf2 = W.qwen_t2i("p", "n", 64, 64, 1, "x")
    assert IP.apply(json.loads(json.dumps(wf2)), None) == wf2


def test_apply_base_shift_two_stage_and_edit_strength():
    eff = IP.resolve(None, {"unet": "base", "steps": 30, "cfg": 3.5, "scheduler": "beta", "shift": 3.1,
                            "sampler": "dpmpp_2m", "two_stage": {"enabled": True, "steps": 10, "denoise": 0.25}})
    wf = W.qwen_t2i("p", "n", 1088, 1920, 9, "x", loras=[("lin_wan_qi_v1.safetensors", 0.8)])
    IP.apply(wf, eff)
    assert wf["14"]["class_type"] == "ModelSamplingAuraFlow" and wf["13"]["inputs"]["model"] == ["14", 0]
    assert wf["37"]["inputs"] == {"model": ["13", 0], "scheduler": "beta", "steps": 30, "denoise": 1.0}
    assert wf["38"]["inputs"]["cfg"] == 3.5 and (wf["34"]["inputs"]["width"], wf["34"]["inputs"]["height"]) == (928, 1632)
    assert wf["53"]["inputs"]["steps"] == 10 and wf["53"]["inputs"]["denoise"] == 0.25
    assert wf["52"]["inputs"]["noise_seed"] == 10 and wf["90"]["inputs"]["images"] == ["55", 0]
    d = IP.describe(wf)
    assert d["shift"] == 3.1 and d["two_stage"]["upscale_size"] == [1152, 2016] and (d["width"], d["height"]) == (1152, 2016)
    # 指令改图：数值重绘幅度覆盖 小/中/大
    ed = W.qwen_edit("x", "", ["a.png"], 1088, 1920, 1, "p", init_image="b.png", denoise=0.55)
    IP.apply(ed, IP.resolve(None, {"strength": 0.42}))
    assert ed["37"]["inputs"]["sigmas"].startswith("0.42, ")
    assert (ed["111"]["inputs"]["width"], ed["111"]["inputs"]["height"]) == (1088, 1920)


def test_render_scale_and_detail_pass_graph():
    eff = IP.resolve(None, {"width": 768, "height": 1344, "render_scale": 1.5,
                            "detail_pass": {"enabled": True, "denoise": 0.2, "scale": 1.25}})
    wf = W.qwen_t2i("p", "n", 1088, 1920, 3, "x")
    IP.apply(wf, eff)
    assert (wf["34"]["inputs"]["width"], wf["34"]["inputs"]["height"]) == (1152, 2016)
    assert (wf["50"]["inputs"]["width"], wf["50"]["inputs"]["height"]) == (1440, 2528)
    assert wf["53"]["inputs"]["sigmas"].startswith("0.2, ")
    assert IP.target_size(eff) == (768, 1344)


# ---------------------------------------------------------------- API（复用 W2 的假 ComfyUI）

from tests.test_frame_jobs_w2 import SHOT, _job, _wait, env  # noqa: E402,F401


@pytest.mark.skipif(not P.SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
def test_default_frame_job_uses_c_and_records_params(env):
    c, data, clients = env
    t = _job(c, {"stage": "first", "mode": "regen", "seed": 11})["take"]
    wf = clients[0][-1].workflows[-1]
    assert wf["10"]["inputs"]["unet_name"] == IP.UNETS["turbo"] and wf["12"]["inputs"]["vae_name"] == TEXTURE_VAE
    assert wf["37"]["inputs"]["sigmas"] == W.TURBO_SIGMAS and wf["38"]["inputs"]["cfg"] == 1.0
    assert wf["36"]["inputs"]["sampler_name"] == "euler" and "53" not in wf
    assert (wf["34"]["inputs"]["width"], wf["34"]["inputs"]["height"]) == (768, 1344)
    assert _loras(wf) == C_LORAS
    e = t["params"]["effective"]
    assert t["params"]["preset"] == "c_turbo_texture" and e["vae"] == "texture_fix" and e["seed"] == 11
    assert e["loras"] == [{"name": f, "strength": s} for f, s in C_LORAS] and (e["width"], e["height"]) == (768, 1344)
    assert e["spec_words"] is True and not e["grade"]["enabled"]
    # 旧 A 仍可选：普通 VAE、1088×1920、LoRA 按剧本
    t2 = _job(c, {"stage": "first", "mode": "regen", "seed": 12, "preset": "preview_turbo"})["take"]
    wf = clients[0][-1].workflows[-1]
    assert wf["12"]["inputs"]["vae_name"] == IP.VAES["plain"] and (wf["34"]["inputs"]["width"], wf["34"]["inputs"]["height"]) == (1088, 1920)
    assert all("krea2" not in f for f, _ in _loras(wf)) and t2["params"]["preset"] == "preview_turbo"
    # 指令改图同样默认 C（尾帧 / 改图都走 frame-jobs 预览档）
    _job(c, {"stage": "first", "mode": "instruct", "instruction": "换个表情", "parent": t["n"]})
    wf = clients[0][-1].workflows[-1]
    assert wf["12"]["inputs"]["vae_name"] == TEXTURE_VAE and wf["37"]["inputs"]["sigmas"].startswith("0.55")


@pytest.mark.skipif(not P.SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
def test_overrides_422_and_post_and_grade(env):
    c, data, clients = env
    r = c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "params": {"steps": "x", "unet": "base"}})
    assert r.status_code == 422 and "出图参数不对" in r.json()["detail"] and "步数" in r.json()["detail"]
    assert c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "preset": "nope"}).status_code == 422
    t = _job(c, {"stage": "first", "preset": "c_turbo_texture",
                 "params": {"render_scale": 1.5, "sharpen": {"enabled": True, "radius": 1.2, "amount": 0.8},
                            "grade": {"enabled": True, "strength": 0.4}, "seed": 77}})["take"]
    wf = clients[0][-1].workflows[-1]
    assert (wf["34"]["inputs"]["width"], wf["34"]["inputs"]["height"]) == (1152, 2016)
    from PIL import Image
    assert t["file"].endswith("_post.png") and Image.open(data / t["file"]).size == (768, 1344)
    assert t["seed"] == 77 and t["raw_file"] and abs(t["grade"]["strength"] - 0.4) < 1e-6
    p = t["params"]
    assert p["overrides"]["render_scale"] == 1.5 and p["post"]["steps"][0].startswith("lanczos")
    assert p["effective"]["sharpen"]["enabled"] and p["effective"]["rendered_size"] == [64, 112]


@pytest.mark.skipif(not P.SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
def test_spec_words_off_strips_system_terms(env):
    c, data, clients = env
    t = _job(c, {"stage": "first", "params": {"spec_words": False}})["take"]
    enc = clients[0][-1].workflows[-1]["20"]["inputs"]["prompt"]
    removed = t["params"]["spec_removed"]
    assert removed and all(x not in enc for x in removed) and t["params"]["effective"]["spec_words"] is False


@pytest.mark.skipif(not P.SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
def test_final_tier_with_overrides(env):
    c, data, clients = env
    t1 = _job(c, {"stage": "first", "seed": 5})["take"]
    j = _wait(c, c.post(f"/api/shots/{SHOT}/frame-jobs", json={
        "stage": "first", "preset": "final_base_2pass", "parent": t1["n"],
        "params": {"steps": 30, "scheduler": "beta", "two_stage": {"steps": 12, "denoise": 0.25},
                   "loras": [{"name": "@identity", "strength": 0.7}]}}).json()["job_id"])
    assert j["state"] == "done", j
    wf = clients[0][-1].workflows[-1]
    assert wf["37"]["inputs"]["steps"] == 30 and wf["37"]["inputs"]["scheduler"] == "beta"
    assert wf["53"]["inputs"]["steps"] == 12 and wf["53"]["inputs"]["denoise"] == 0.25
    assert _loras(wf) == [("lin_wan_qi_v1.safetensors", 0.7)]
    e = j["take"]["params"]["effective"]
    assert e["tier"] == "final" and e["steps"] == 30 and e["two_stage"]["steps"] == 12


@pytest.mark.skipif(not P.SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
def test_presets_endpoint_and_user_presets(env, tmp_path, monkeypatch):
    c, data, clients = env
    cfgp = tmp_path / "rq.json"
    shutil.copy(IP.CONFIG, cfgp)
    monkeypatch.setattr(IP, "CONFIG", cfgp)
    from ns_api import frame_jobs as FJ
    monkeypatch.setattr(FJ, "_ALLOWED", {})
    r = c.get("/api/render/image-presets?gpu=0").json()
    ids = [p["id"] for p in r["presets"]]
    assert {"c_turbo_texture", "preview_turbo", "final_base_2pass"} <= set(ids) and r["default_preset"] == "c_turbo_texture"
    assert r["allowed"]["source"] == "live" and "lin_wan_qi_v1.safetensors" in r["allowed"]["loras"]
    assert r["defaults"]["sharpen"] == {"enabled": False, "radius": 1.0, "amount": 0.5} and "turbo" in r["notes"]
    assert c.get("/api/render/image-presets?gpu=0").json()["allowed"]["source"] == "cache"
    # 缓存了 LoRA 列表 → 提交时按它核对
    bad = c.post(f"/api/shots/{SHOT}/frame-jobs", json={"stage": "first", "gpu": 0,
                                                         "params": {"loras": [{"name": "zz.safetensors", "strength": 1}]}})
    assert bad.status_code == 422 and "没有这个 LoRA" in bad.json()["detail"]
    # 存为我的预设 → 出现在列表 → 能用 → 删
    s = c.post("/api/render/image-presets", json={"label": "我的锐利", "params": {"sharpen": {"enabled": True, "radius": 1, "amount": 1}}})
    assert s.status_code == 200 and s.json()["id"].startswith("user_")
    pid = s.json()["id"]
    assert json.loads(cfgp.read_text(encoding="utf-8"))["user_presets"][0]["label"] == "我的锐利"
    assert c.post("/api/render/image-presets", json={"label": "x", "params": {"steps": -1, "unet": "base"}}).status_code == 422
    assert c.post("/api/render/image-presets", json={"label": "定稿·Base 两段式", "params": {}}).status_code == 422
    t = _job(c, {"stage": "first", "preset": pid})["take"]
    assert t["params"]["preset"] == pid and t["params"]["effective"]["sharpen"]["enabled"]
    assert c.delete(f"/api/render/image-presets/{pid}").status_code == 200
    assert c.delete("/api/render/image-presets/c_turbo_texture").status_code == 404
