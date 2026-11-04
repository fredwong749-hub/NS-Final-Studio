"""LCA：项目方 2026-10-31 选定 徕卡 S★ 为默认出图预设（“leica_sharp效果最好，用他”；“S★ 全套组合”）。
S★ = C 原样 + 1.5 倍出图 → PIL lanczos 缩回 768×1344 + PIL UnsharpMask(1.2, 60, 2) + 风格后缀候选1（前加“，”原样）。
假 ComfyUI，不占 GPU。"""
import json
import re
from pathlib import Path

import pytest

from ns_render import image_params as IP
from ns_render import pipeline as P
from ns_render import workflows as W

ROOT = Path(__file__).resolve().parents[1]
AB = ROOT / "data" / "ab" / "leica_sharp"
SUFFIX1 = "专业电影画面，徕卡M 50mm f/2镜头，焦点锐利，微反差强，皮肤纹理清晰，自然高光，暖调通透，干净真实"
# 项目方 2026-10-31“默认出图预设里的林晚出图 LoRA（0.6）还要不要用？—— A. 去掉”：S★ 只剩 krea2 0.5（REFLOCK）
C_LORAS = [("krea2_film_texture_qwen21.safetensors", 0.5)]


def _candidate1() -> str:
    txt = (AB / "style_suffix_candidates.md").read_text(encoding="utf-8")
    return {int(m.group(1)): m.group(2).strip() for m in re.finditer(r"^候选(\d)：(.+)$", txt, re.M)}[1]


# ---------------------------------------------------------------- 配置

def test_default_is_leica_sstar_and_matches_experiment():
    q = IP.quality()
    assert q["default_preset"] == "leica_sstar" == IP.default_preset()
    assert "leica_sharp效果最好，用他" in q["default_preset_note"] and "2026-10-31" in q["default_preset_note"]
    assert IP.find_preset("c_turbo_texture") is not None           # C 仍可选
    pr = IP.find_preset("leica_sstar")
    assert pr["label"] == "徕卡 S★" and pr["tier"] == "preview"
    eff = IP.resolve("leica_sstar", None)
    assert (eff["unet"], eff["steps"], eff["cfg"], eff["sampler"], eff["vae"]) == ("turbo", 8, 1.0, "euler", "texture_fix")
    assert (eff["width"], eff["height"], eff["render_scale"]) == (768, 1344, 1.5)
    assert eff["sharpen"] == {"enabled": True, "radius": 1.2, "amount": 0.6, "threshold": 2}
    assert eff["style_suffix"] == SUFFIX1 == IP.LEICA_SUFFIX
    if (AB / "style_suffix_candidates.md").exists():
        assert eff["style_suffix"] == _candidate1()                  # 写作模型原文，一字不改
    if (AB / "settings.json").exists():
        s = json.loads((AB / "settings.json").read_text(encoding="utf-8"))
        assert s["unsharp"] == {"radius": 1.2, "percent": 60, "threshold": 2}
        assert IP.VAES[eff["vae"]] == s["model"]["vae"] and IP.UNETS[eff["unet"]] == s["model"]["unet"]
        assert W.TURBO_SIGMAS == s["model"]["sigmas"]


def test_fallback_has_sstar_when_config_lost(tmp_path):
    cfg = tmp_path / "rq.json"
    cfg.write_text(json.dumps({"tiers": {}}), encoding="utf-8")
    assert IP.default_preset(cfg) == "leica_sstar"
    assert IP.resolve("leica_sstar", None, path=cfg)["style_suffix"] == SUFFIX1


@pytest.mark.parametrize("over,needle", [
    ({"style_suffix": 3}, "风格后缀"),
    ({"style_suffix": "字" * 501}, "风格后缀"),
    ({"sharpen": {"enabled": True, "radius": 1, "amount": 1, "threshold": 999}}, "锐化阈值"),
])
def test_new_fields_validated(over, needle):
    with pytest.raises(IP.ParamError) as e:
        IP.resolve(None, over)
    assert needle in str(e.value)


# ---------------------------------------------------------------- 工作流

def test_apply_t2i_scales_and_appends_suffix_verbatim():
    prompt = "lnwan_qi，作者原文，无字幕、无文字、无水印"
    wf = W.qwen_t2i(prompt, "n", 1088, 1920, 5, "x", loras=[("lin_wan_qi_v1.safetensors", 0.8)])
    eff = IP.resolve("leica_sstar", None)
    IP.apply(wf, eff, {"lin_wan_qi_v1.safetensors"})
    assert (wf["34"]["inputs"]["width"], wf["34"]["inputs"]["height"]) == (1152, 2016)
    assert wf["37"]["inputs"]["sigmas"] == W.TURBO_SIGMAS and "53" not in wf
    assert [(f, s) for _n, f, s in IP._chain(wf)] == C_LORAS
    # 同 tools/ab/leica_sharp.py variant_prompt：prompt + "，" + 后缀
    assert wf["20"]["inputs"]["prompt"] == prompt + "，" + SUFFIX1
    IP.apply(wf, eff, {"lin_wan_qi_v1.safetensors"})            # 同一张图再改一次不重复接
    assert wf["20"]["inputs"]["prompt"] == prompt + "，" + SUFFIX1
    assert IP.target_size(eff) == (768, 1344)
    d = IP.describe(wf)
    s = IP.summary(eff, d, {"seed": 5})
    assert s["style_suffix"] == SUFFIX1 and s["style_suffix_applied"] and s["render_scale"] == 1.5
    assert s["sharpen"]["threshold"] == 2


def test_apply_edit_with_base_image_keeps_delivery_size():
    ed = W.qwen_edit("改图原话", "", ["a.png"], 1088, 1920, 1, "p", init_image="b.png", denoise=0.35,
                     ref_resolution=0, crop=False)
    eff = IP.resolve("leica_sstar", None, mode="instruct")
    IP.apply(ed, eff)
    assert (ed["111"]["inputs"]["width"], ed["111"]["inputs"]["height"]) == (768, 1344)   # 不放大
    assert ed["20"]["inputs"]["prompt"] == "改图原话，" + SUFFIX1                          # 后缀照接
    s = IP.summary(eff, IP.describe(ed), {})
    assert s["render_scale"] == 1.0 and s["render_scale_requested"] == 1.5 and s["render_scale_note"]
    assert s["sharpen"]["enabled"]


def test_post_file_equals_experiment_pipeline(tmp_path):
    from PIL import Image, ImageFilter
    import random
    rnd = random.Random(3)
    im = Image.new("RGB", (1152, 2016))
    im.putdata([(rnd.randrange(256), rnd.randrange(256), rnd.randrange(256)) for _ in range(1152 * 2016)])
    raw = tmp_path / "x.png"
    im.save(raw)
    post = IP.post_file(raw, IP.resolve("leica_sstar", None), film_cfg={"enabled": False})   # L-188 生产默认走胶片（关 USM）；本测验 USM 老链路
    assert raw.exists() and post["rendered_size"] == [1152, 2016] and post["size"] == [768, 1344]
    assert post["unsharp"] == {"radius": 1.2, "percent": 60, "threshold": 2}
    # 实验脚本：down() 存盘 → usm() 再开
    down = tmp_path / "down.png"
    Image.open(raw).convert("RGB").resize((768, 1344), Image.LANCZOS).save(down)
    ref = Image.open(down).convert("RGB").filter(ImageFilter.UnsharpMask(radius=1.2, percent=60, threshold=2))
    assert Image.open(post["path"]).convert("RGB").tobytes() == ref.tobytes()


# ---------------------------------------------------------------- API（复用 W2 的假 ComfyUI）

from tests.test_frame_jobs_w2 import SHOT, _job, env  # noqa: E402,F401


@pytest.mark.skipif(not P.SCRIPT_JSON.exists(), reason="data/import/script_v2.json missing")
def test_default_frame_job_is_sstar(env):
    c, data, clients = env
    t = _job(c, {"stage": "first", "mode": "regen", "seed": 11})["take"]
    wf = clients[0][-1].workflows[-1]
    assert (wf["34"]["inputs"]["width"], wf["34"]["inputs"]["height"]) == (1152, 2016)
    assert wf["20"]["inputs"]["prompt"].endswith("，" + SUFFIX1)
    from PIL import Image
    assert t["file"].endswith("_post.png") and Image.open(data / t["file"]).size == (768, 1344)
    p = t["params"]
    assert p["preset"] == "leica_sstar" and (data / p["post"]["from"]).exists()        # 放大原图保留
    e = p["effective"]
    assert (e["width"], e["height"], e["render_scale"]) == (768, 1344, 1.5)
    assert e["sharpen"] == {"enabled": True, "radius": 1.2, "amount": 0.6, "threshold": 2}
    assert e["style_suffix"] == SUFFIX1 and e["style_suffix_applied"] is True
    assert p["prompt_sent"].endswith("，" + SUFFIX1) and not t["prompt"].endswith(SUFFIX1)  # take.prompt = 原文
    # 指令改图：底图用父版本后处理前的原图，不放大，后缀 + 锐化照做
    t2 = _job(c, {"stage": "first", "mode": "instruct", "instruction": "换个表情", "parent": t["n"]})["take"]
    wf2 = clients[0][-1].workflows[-1]
    assert (wf2["111"]["inputs"]["width"], wf2["111"]["inputs"]["height"]) == (768, 1344)
    assert wf2["20"]["inputs"]["prompt"] == "换个表情，" + SUFFIX1
    e2 = t2["params"]["effective"]
    assert e2["render_scale"] == 1.0 and e2["sharpen"]["enabled"] and t2["file"].endswith("_post.png")


def test_asset_gen_with_sstar(tmp_path, monkeypatch):
    from tests.test_ref_switch_w5 import FakeComfy
    from ns_api import asset_edit as AED
    from PIL import Image

    class FC(FakeComfy):
        def download(self, item, dest):
            dest.parent.mkdir(parents=True, exist_ok=True)
            Image.new("RGB", (1152, 2016), (120, 90, 60)).save(dest)
            return dest

    fc = FC()
    eff = IP.resolve("leica_sstar", None)
    plan = {"asset": {"id": "scene_x", "kind": "scene"}, "base": None, "refs": [], "images": [], "denoise": 1.0,
            "gpu": 0, "prompt": "场景原话", "negative": "", "seed": 3, "strength": "medium", "size": (768, 1344),
            "parent": None, "eff": eff, "identity": [], "label": ""}
    monkeypatch.setattr(AED, "_ref_dir", lambda asset: tmp_path / "refs")
    monkeypatch.setattr(AED, "_read", lambda name: {})
    monkeypatch.setattr(AED, "_write", lambda name, d: None)
    monkeypatch.setattr(AED.A, "rel", lambda p: Path(p).relative_to(tmp_path).as_posix())
    monkeypatch.setattr(AED.A, "file_url", lambda r: "/x/" + r)
    from ns_api import jobs as J
    monkeypatch.setattr(J, "wait_prompt", lambda client, job, pid, timeout: {"outputs": {}})
    monkeypatch.setattr(fc, "output_files", lambda entry: [{"filename": "a.png"}], raising=False)
    out = AED.run_gen(fc, {"job_id": "j"}, plan)
    wf = fc.submitted[0]
    assert wf["20"]["inputs"]["prompt"] == "场景原话，" + SUFFIX1
    assert (wf["34"]["inputs"]["width"], wf["34"]["inputs"]["height"]) == (1152, 2016)
    rec = out["result"]
    assert rec["file"].endswith("_post.png") and rec["raw_file"] and rec["size"] == [768, 1344]
    assert Image.open(tmp_path / rec["file"]).size == (768, 1344)
    e = rec["effective"]
    assert e["style_suffix_applied"] and e["sharpen"]["threshold"] == 2 and e["rendered_size"] == [1152, 2016]


def test_image_check_uses_post_size_not_rendered_size():
    from ns_render import image_check as IC
    t = {"stage": "image", "file": "x_post.png",
         "params": {"effective": {"width": 768, "height": 1344, "rendered_size": [1152, 2016]},
                    "post": {"file": "x_post.png", "from": "x.png", "size": [768, 1344], "rendered_size": [1152, 2016]}}}
    assert IC.expected_size(t) == (768, 1344)
    t["file"] = "x.png"                                   # 没用后处理文件 → 按原逻辑
    assert IC.expected_size(t) == (1152, 2016)
