"""可选出图基座的 ComfyUI 图构建（IMGLAB，项目方 11-02 11:2x：FLUX 3 Image Klein、MOSS-Image 作为可选基底）。
生产仍用 S★ R0（ns_render.unified_frame.build_graph，Qwen-Image 2.1 Turbo，L-087 不改）；这里只给 A/B / 画布可选基座用。

节点与默认参数取自服务器 ComfyUI 自带官方模板（comfyui_workflow_templates_json/templates/）：
  klein：image_flux3_klein_distilled_image_edit.json —— UNETLoader flux3-image-klein-int8-convrot + CLIPLoader(qwen3vl_4b_int8, flux3) +
         flux2-vae；KSampler 16 步 cfg 1 euler/simple；参考图走 ReferenceMultiLatent（resize 1 MP）；负向 ConditioningZeroOut
  moss： image_moss_image_t2i.json —— UNETLoader moss_image_sft_int8_convrot + CLIPLoader(qwen3.5_9b, moss_image) + flux2-vae_small；
         KSampler 25 步 cfg 2.5 er_sde/simple；SkipLayerGuidanceDiTSimple 单层 22，0–0.5；负向“nsfw, worst quality, bad anatomy, watermark, jpeg artifact”

    from bases import build
    wf = build("klein", prompt, ref_names, seed, prefix, params={"steps": 16})
"""
from __future__ import annotations

BASES = {
    "klein": {"label": "FLUX 3 Image Klein（BFL，FLUX Kommunity License）", "unet": "flux3-image-klein-int8-convrot.safetensors",
              "clip": "qwen3vl_4b_int8_convrot.safetensors", "clip_type": "flux3", "vae": "flux2-vae.safetensors",
              "steps": 16, "cfg": 1.0, "sampler": "euler", "scheduler": "simple", "max_refs": 10, "ref_mp": 1.0,
              "width": 864, "height": 1536, "negative": None},
    "moss": {"label": "MOSS-Image SFT（OpenMOSS，Apache-2.0）", "unet": "moss_image_sft_int8_convrot.safetensors",
             "clip": "qwen3.5_9b_int8_convrot.safetensors", "clip_type": "moss_image", "vae": "flux2-vae_small.safetensors",
             "steps": 25, "cfg": 2.5, "sampler": "er_sde", "scheduler": "simple", "max_refs": 0, "slg_layers": "22", "slg_end": 0.5,
             "width": 864, "height": 1536, "negative": "nsfw, worst quality, bad anatomy, watermark, jpeg artifact",
             "edit_lora": "moss_image_edit_lora_rank_64_bf16.safetensors"},
}


def params_for(base: str, params: dict | None = None) -> dict:
    return {**BASES[base], **(params or {})}


def build(base: str, prompt: str, ref_names: list[str], seed: int, prefix: str, params: dict | None = None) -> dict:
    """→ ComfyUI API 图。ref_names = 已上传到 ComfyUI input 的参考图名（klein 用；moss 本体文生图，refs 只在 edit_lora 臂用）"""
    p = params_for(base, params)
    g: dict = {
        "1": {"class_type": "UNETLoader", "inputs": {"unet_name": p["unet"], "weight_dtype": "default"}},
        "2": {"class_type": "CLIPLoader", "inputs": {"clip_name": p["clip"], "type": p["clip_type"], "device": "default"}},
        "3": {"class_type": "VAELoader", "inputs": {"vae_name": p["vae"]}},
        "10": {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": prompt}},
        "20": {"class_type": "EmptyFlux2LatentImage", "inputs": {"width": int(p["width"]), "height": int(p["height"]), "batch_size": 1}},
    }
    model = ["1", 0]
    if base == "klein":
        g["11"] = {"class_type": "ConditioningZeroOut", "inputs": {"conditioning": ["10", 0]}}
        pos, neg = ["10", 0], ["11", 0]
        refs = list(ref_names or [])[: int(p["max_refs"])]
        if refs:
            inp = {"positive": pos, "negative": neg, "vae": ["3", 0], "resolution": "resize", "resolution.megapixels": float(p["ref_mp"])}
            for i, name in enumerate(refs, 1):
                g[f"5{i:02d}"] = {"class_type": "LoadImage", "inputs": {"image": name}}
                inp[f"images.image{i}"] = [f"5{i:02d}", 0]
            g["12"] = {"class_type": "ReferenceMultiLatent", "inputs": inp}
            pos, neg = ["12", 0], ["12", 1]
    else:  # moss
        if p.get("use_edit_lora") and ref_names:
            g["4"] = {"class_type": "LoraLoaderModelOnly", "inputs": {"model": model, "lora_name": p["edit_lora"], "strength_model": float(p.get("edit_lora_strength", 1.0))}}
            model = ["4", 0]
        g["6"] = {"class_type": "SkipLayerGuidanceDiTSimple", "inputs": {"model": model, "double_layers": "", "single_layers": p["slg_layers"],
                                                                        "start_percent": 0.0, "end_percent": float(p["slg_end"])}}
        model = ["6", 0]
        g["11"] = {"class_type": "CLIPTextEncode", "inputs": {"clip": ["2", 0], "text": p["negative"] or ""}}
        pos, neg = ["10", 0], ["11", 0]
        if p.get("use_edit_lora") and ref_names:
            g["501"] = {"class_type": "LoadImage", "inputs": {"image": ref_names[0]}}
            g["502"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["501", 0], "vae": ["3", 0]}}
            g["13"] = {"class_type": "ReferenceLatent", "inputs": {"conditioning": pos, "latent": ["502", 0]}}
            pos = ["13", 0]
    g["30"] = {"class_type": "KSampler", "inputs": {"model": model, "positive": pos, "negative": neg, "latent_image": ["20", 0], "seed": int(seed),
                                                    "steps": int(p["steps"]), "cfg": float(p["cfg"]), "sampler_name": p["sampler"],
                                                    "scheduler": p["scheduler"], "denoise": 1.0}}
    g["40"] = {"class_type": "VAEDecode", "inputs": {"samples": ["30", 0], "vae": ["3", 0]}}
    g["90"] = {"class_type": "SaveImage", "inputs": {"images": ["40", 0], "filename_prefix": prefix}}
    return g
