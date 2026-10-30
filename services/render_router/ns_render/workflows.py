"""
API 格式工作流。

- qwen_t2i：Qwen Image 2.1（Turbo 8 步或 Base），节点结构来自 ComfyUI 官方 2.1 示例（旧系统 config/comfy_templates 已验证）。
- qwen_edit：Qwen Image 2.1 单参考编辑（锁脸），结构同旧系统 qwen_image_2_1_turbo_edit.json：参考图作为
  TextEncodeQwenImage21 的 images.image_1（并接 VAE）。参考图先按画布比例居中裁切（ImageScale crop=center），
  因为画布与参考图比例一致时身份保持最好（research v5：眼距波动 ±3.9% vs ±18.9%）。
- h3_fl2va：MiniMax H3 首帧生视频（含同步音频），节点结构来自旧系统 adapters/video/comfy_h3/workflow.py。
LoRA 统一用 LoraLoaderModelOnly 串在 UNET 后面。
"""
from dataclasses import dataclass, field

TURBO_SIGMAS = "1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0"


@dataclass(frozen=True)
class QwenModel:
    unet: str = "qwen_image_2.1_turbo_int8_convrot.safetensors"
    clip: str = "qwen3vl_8b_int8_convrot.safetensors"
    vae: str = "qwen_image_2.1_vae_bf16.safetensors"
    turbo: bool = True          # Turbo 用官方 8 步 sigma；Base 用 steps/cfg
    steps: int = 25
    cfg: float = 2.5
    sampler: str = "euler"


@dataclass(frozen=True)
class H3Model:
    unet: str = "minimax_h3_fl2va_pruned_w4a8_mixed.safetensors"
    clip: str = "qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors"
    video_vae: str = "minimax_h3_video_vae_int8_convrot.safetensors"
    audio_vae: str = "minimax_h3_audio_vae_fp32.safetensors"
    loras: tuple[tuple[str, float], ...] = (
        ("minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16.safetensors", 1.0),)
    steps: int = 8
    sampler: str = "euler"
    scheduler: str = "simple"
    fps: int = 24


def _lora_chain(wf: dict, model: list, loras, first_id: int) -> list:
    for i, (name, strength) in enumerate(loras):
        nid = str(first_id + i)
        wf[nid] = {"class_type": "LoraLoaderModelOnly",
                   "inputs": {"model": model, "lora_name": name, "strength_model": float(strength)}}
        model = [nid, 0]
    return model


def _qwen_graph(prompt: str, negative: str, width: int, height: int, seed: int, prefix: str,
                m: QwenModel, loras, reference: str | list[str] | None = None, ref_resolution: int = 1024,
                crop: bool = True, init_image: str | None = None, denoise: float = 1.0) -> dict:
    wf: dict = {
        "10": {"class_type": "UNETLoader", "inputs": {"unet_name": m.unet, "weight_dtype": "default"}},
        "11": {"class_type": "CLIPLoader", "inputs": {"clip_name": m.clip, "type": "qwen_image", "device": "default"}},
        "12": {"class_type": "VAELoader", "inputs": {"vae_name": m.vae}},
    }
    model = _lora_chain(wf, ["10", 0], loras, 60)
    enc = {"clip": ["11", 0], "prompt": prompt, "negative_prompt": negative, "resolution": 1024}
    refs = [reference] if isinstance(reference, str) else list(reference or [])
    if refs:
        enc.update({"resolution": ref_resolution, "vae": ["12", 0]})
    for i, ref in enumerate(refs):
        load_id = str(101 + 2 * i)
        wf[load_id] = {"class_type": "LoadImage", "inputs": {"image": ref}}
        src = [load_id, 0]
        if crop:
            # 居中裁到画布比例（同时缩放到画布尺寸；编码器内部再按 ref_resolution 缩放）
            scale_id = str(102 + 2 * i)
            wf[scale_id] = {"class_type": "ImageScale", "inputs": {"image": src, "upscale_method": "lanczos",
                                                                   "width": width, "height": height,
                                                                   "crop": "center"}}
            src = [scale_id, 0]
        enc[f"images.image_{i + 1}"] = src
    wf.update({
        "13": {"class_type": "QwenImage21Cache", "inputs": {"model": model, "device": "auto", "dtype": "default"}},
        "20": {"class_type": "TextEncodeQwenImage21", "inputs": enc},
        "34": {"class_type": "EmptyLatentImage", "inputs": {"width": width, "height": height, "batch_size": 1}},
        "35": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "36": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": m.sampler}},
        "38": {"class_type": "CFGGuider", "inputs": {"model": ["13", 0], "positive": ["20", 0], "negative": ["20", 1],
                                                     "cfg": 1.0 if m.turbo else m.cfg}},
        "40": {"class_type": "SamplerCustomAdvanced",
               "inputs": {"noise": ["35", 0], "guider": ["38", 0], "sampler": ["36", 0], "sigmas": ["37", 0],
                          "latent_image": ["34", 0]}},
        "41": {"class_type": "VAEDecode", "inputs": {"samples": ["40", 0], "vae": ["12", 0]}},
        "90": {"class_type": "SaveImage", "inputs": {"images": ["41", 0], "filename_prefix": prefix}},
    })
    if m.turbo:
        wf["37"] = {"class_type": "ManualSigmas", "inputs": {"sigmas": TURBO_SIGMAS}}
    else:
        wf["37"] = {"class_type": "BasicScheduler",
                    "inputs": {"model": ["13", 0], "scheduler": "simple", "steps": m.steps, "denoise": denoise}}
    if init_image:
        # 低重绘第二遍（research v8 §4）：从已有图的 latent 出发，Base 少步数 denoise≈0.3
        wf["110"] = {"class_type": "LoadImage", "inputs": {"image": init_image}}
        wf["111"] = {"class_type": "ImageScale", "inputs": {"image": ["110", 0], "upscale_method": "lanczos",
                                                            "width": width, "height": height, "crop": "center"}}
        wf["112"] = {"class_type": "VAEEncode", "inputs": {"pixels": ["111", 0], "vae": ["12", 0]}}
        wf["40"]["inputs"]["latent_image"] = ["112", 0]
        del wf["34"]
    return wf


def qwen_t2i(prompt: str, negative: str, width: int, height: int, seed: int, prefix: str,
             m: QwenModel = QwenModel(), loras: list[tuple[str, float]] = ()) -> dict:
    return _qwen_graph(prompt, negative, width, height, seed, prefix, m, loras)


def qwen_edit(prompt: str, negative: str, reference: str | list[str], width: int, height: int, seed: int,
              prefix: str, m: QwenModel = QwenModel(), loras: list[tuple[str, float]] = (),
              ref_resolution: int = 1024, crop: bool = True, init_image: str | None = None,
              denoise: float = 1.0) -> dict:
    """参考编辑。reference: ComfyUI 输入图片名（upload_image 的返回值），或多张（依次为 图1、图2…）。
    crop=False + ref_resolution=0：参考图已在本地预缩放（research v6 §4.2：脸部底板约 768²），原尺寸送入编码器，
    不再裁成画布比例——画面构图只由 EmptyLatentImage 画布和提示词决定。"""
    return _qwen_graph(prompt, negative, width, height, seed, prefix, m, loras,
                       reference=reference, ref_resolution=ref_resolution, crop=crop, init_image=init_image,
                       denoise=denoise)


TEXT_MODEL = "qwen3vl_8b_int8_convrot.safetensors"   # Qwen Image 2.1 的文本编码器本身就是 Qwen3-VL 8B


def text_generate(prompt: str, prefix: str, image: str | None = None, max_length: int = 400,
                  clip: str = TEXT_MODEL) -> dict:
    """本地看图/写作模型：ComfyUI TextGenerate + Qwen3-VL 8B（与出图共用同一个编码器文件，不额外占内存）。
    贪心解码（sampling off），结果由 SaveText 输出（history 里 outputs[\"90\"][\"text\"]）。"""
    wf: dict = {
        "11": {"class_type": "CLIPLoader", "inputs": {"clip_name": clip, "type": "qwen_image", "device": "default"}},
        "20": {"class_type": "TextGenerate", "inputs": {"clip": ["11", 0], "prompt": prompt, "max_length": max_length,
                                                        "sampling_mode": "off"}},
        "90": {"class_type": "SaveText", "inputs": {"text": ["20", 0], "filename_prefix": prefix, "format": "txt"}},
    }
    if image:
        wf["101"] = {"class_type": "LoadImage", "inputs": {"image": image}}
        wf["20"]["inputs"]["image"] = ["101", 0]
    return wf


def h3_fl2va(prompt: str, first_frame: str, width: int, height: int, frames: int, seed: int, prefix: str,
             m: H3Model = H3Model(), loras: list[tuple[str, float]] = (), last_frame: str | None = None) -> dict:
    """first_frame / last_frame: ComfyUI 里的输入图片名（upload_image 的返回值）；last_frame 可选"""
    wf: dict = {
        "127": {"class_type": "UNETLoader", "inputs": {"unet_name": m.unet, "weight_dtype": "default"}},
        "128": {"class_type": "CLIPLoader", "inputs": {"clip_name": m.clip, "type": "minimax", "device": "default"}},
        "119": {"class_type": "VAELoader", "inputs": {"vae_name": m.video_vae}},
        "120": {"class_type": "VAELoader", "inputs": {"vae_name": m.audio_vae}},
        "200": {"class_type": "LoadImage", "inputs": {"image": first_frame}},
    }
    model = _lora_chain(wf, ["127", 0], [*m.loras, *loras], 140)
    wf.update({
        "131": {"class_type": "MiniMaxH3ImageToVideo",
                "inputs": {"clip": ["128", 0], "prompt": prompt, "width": width, "height": height,
                           "length": frames, "vae": ["119", 0], "first_frame": ["200", 0]}},
    })
    if last_frame:
        wf["201"] = {"class_type": "LoadImage", "inputs": {"image": last_frame}}
        wf["131"]["inputs"]["last_frame"] = ["201", 0]
    wf.update({
        "126": {"class_type": "BasicGuider", "inputs": {"model": model, "conditioning": ["131", 0]}},
        "129": {"class_type": "RandomNoise", "inputs": {"noise_seed": seed}},
        "123": {"class_type": "KSamplerSelect", "inputs": {"sampler_name": m.sampler}},
        "124": {"class_type": "BasicScheduler",
                "inputs": {"model": model, "scheduler": m.scheduler, "steps": m.steps, "denoise": 1.0}},
        "125": {"class_type": "SamplerCustomAdvanced",
                "inputs": {"noise": ["129", 0], "guider": ["126", 0], "sampler": ["123", 0], "sigmas": ["124", 0],
                           "latent_image": ["131", 1]}},
        "122": {"class_type": "VAEDecode", "inputs": {"samples": ["125", 0], "vae": ["119", 0]}},
        "121": {"class_type": "VAEDecodeAudio", "inputs": {"samples": ["125", 0], "vae": ["120", 0]}},
        "130": {"class_type": "CreateVideo", "inputs": {"images": ["122", 0], "audio": ["121", 0], "fps": m.fps}},
        "92": {"class_type": "SaveVideo", "inputs": {"video": ["130", 0], "filename_prefix": prefix,
                                                     "format": "mp4", "codec": "auto"}},
    })
    return wf
