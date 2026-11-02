# 可选基座权重登记（IMGLAB，项目方 11-02 11:2x 授权下载免费模型，总调度转；抄送 FACTORY）

定位：作为可选基底。第一季、第二季生产仍用 S★ R0（Qwen-Image 2.1 Turbo，L-087 不改），换不换由项目方看 A/B 后决定。
脚本：tools/imglab/install_bases.sh（只下权重；两台 ComfyUI 已原生支持 Flux3 与 MOSS-Image，不装节点）。
下载经代理 http://10.0.0.101:7190，按 revision 固定，逐个核对 sha256。

| 机器 | ComfyUI 根 |
|---|---|
| gpu33 | /root/claude-kimi-ns-studio-v1/ComfyUI（8e3feba，10-28；含 comfy/model_base.Flux3、comfy/text_encoders/moss_image.py） |
| gpu36 | /root/work/fredw/comfy/ComfyUI |

## MOSS-Image（OpenMOSS / 复旦，Apache-2.0，不 gated）

来源：Comfy-Org/MOSS-Image@530a4c94f92c35ef6818b1b035a983fe9dcf5f54（官方 ComfyUI 打包；原始权重 OpenMOSS-Team/MOSS-Image-SFT@f972bd4b）

| 文件 | 大小 | sha256 | 目标 |
|---|---|---|---|
| diffusion_models/moss_image_sft_int8_convrot.safetensors | 5.41 GB | b4d1475bc7eeffd7b809e82ea13a1fba1fb85c4e18365af3813722faa5c0fe4f | models/diffusion_models/ |
| text_encoders/qwen3.5_9b_int8_convrot.safetensors | 9.75 GB | 32e3787472f708fa5f83624acbf5ef23f7fc89c439e05065ea57cfe5a97f025a | models/text_encoders/ |
| vae/flux2-vae_small.safetensors | 0.25 GB | d8d52ba036475f5fb07c8b435e176d3d97ebfa82f0d1a1c317f9cc1e25bd013b | models/vae/ |
| loras/moss_image_edit_lora_rank_64_bf16.safetensors | 0.30 GB | 17a48b8c605dcffdedb92a2b887d18cf316505be90802717669fb6556098dcdf | models/loras/ |

模型卡要点：5B DiT；50 步，cfg 3，shift 5；跳层引导用 layer 22；flow-matching Euler；本体只做文生图，参考图编辑要靠 edit LoRA；支持布局 JSON。

## FLUX 3 Image Klein（Black Forest Labs，FLUX Kommunity License v1.0，gated）

来源：black-forest-labs/flux-3-image-klein-comfy@feef60b0aaf63a4773ace96636ebbcf43b881312。
gated 仓库的 sha256 由脚本在下载后计算（11-02 21:3x 服务器时间，两台结果一致，全部 OK）。
许可证由项目方本人在 HF 上点同意。只读 token 放在笔记本的 HF 标准位置，经 rsh 推到两台服务器的 ~/.cache/huggingface/token（权限 600，不打印、不进日志、不进仓库）。

| 文件 | 大小 | sha256 | 目标 |
|---|---|---|---|
| diffusion_models/flux3-image-klein-int8-convrot.safetensors | 5.83 GB | 847d8933548afd93df4af2cac2498e70891bf28d9dae06d695f536992e168fe2 | models/diffusion_models/ |
| text_encoders/qwen3vl_4b_int8_convrot.safetensors | 4.86 GB | 32de113cbf8282b02cbff0794b637b9d6676da09314a1db5a30bcea9bf4ee01c | models/text_encoders/ |
| text_encoders/qwen3.5_9b_flux3_prompt_upsampler_int8_convrot.safetensors | 9.75 GB | cb8cb9b9dcd2569509de755dca54d96fd93a16a7aabfd2f4051f0a144230620f | models/text_encoders/ |
| vae/flux2-vae.safetensors | 0.34 GB | 868fe7b343cc8f3a19dbcfcafbc3d5f888802be3f89bd81b65b3621a066ce8f3（与 Comfy-Org/MOSS-Image 同名文件一致） | models/vae/ |
| workflows/flux3_klein_int8_{t2i,i2i,mi2i}.json | — | — | /root/work/fredw/imglab_bases/workflows/ |

模型卡要点：
- 5.6B 图像 transformer，文本编码器 Qwen3-VL-4B；
- 蒸馏版 16 步、无 guidance、flow-map 采样；
- 最多 10 张参考图；
- 必须配提示词扩写器（“Do not use the model without a prompt upsampler”）；
- int8 版可在 RTX 30 系上跑。

许可证原文：“commercial output generation by Qualifying Users with less than US$5M in gross annualized revenue”。

## 回退

删除上表文件即可，两台机器都不涉及节点和 pip 改动。
