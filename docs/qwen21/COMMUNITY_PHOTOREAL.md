# 社区"真人写实"微调参数调研：Krea 2 / Z-Image / FLUX.2 klein / FLUX.3 Klein / Qwen-Image-Edit-2511 / Qwen-Image 2.1（LoRA）

调研日期：2026-11-01。场景：竖屏写实短剧，中国成年女性主角，ComfyUI 原生节点，单卡 3090 24GB。
方法：用 Civitai 公开 API 按 baseModel 拉取"下载最多"的 LoRA/Checkpoint（`/api/v1/models?types=…&sort=Most Downloaded&baseModels=…`），再逐个拉 `/api/v1/model-versions/<id>` 和 `/api/v1/models/<id>` 读作者原文；官方参数读 HF 模型卡原文、官方 GitHub README、docs.comfy.org 的 .md 原文、Comfy-Org/workflow_templates 的模板 JSON（直接解析节点 widgets_values）、ComfyUI 源码。Reddit 不能直连，只用 reddit.sentinel-team.org 的快照转述。
Qwen-Image 2.1 的官方参数已经在 `docs/qwen21/RESEARCH.md` 里，这里只补 Civitai 写实 LoRA。

Civitai 上实际用的 baseModel 字符串（API 查出）：`Krea 2`、`Krea 2 Turbo`、`ZImageTurbo`、`ZImageBase`、`Flux.2 Klein 9B`、`Flux.2 Klein 9B-base`、`Flux.2 Klein 4B`、`Flux.2 Klein 4B-base`、`Flux.3 Klein`、`Flux.3 Klein-base`、`Flux.3`、`Qwen 2.1`、`Qwen`（Qwen-Image-Edit-2509/2511 的 LoRA 都挂在 `Qwen` 下，没有单独的 "Qwen Image Edit" 基模名，查询返回 0 条）。

置信度：**高** = 官方文档、模板 JSON 或源码原文；**中** = 作者在自己模型页的原文（作者自述，未经我们实测），或多个社区来源一致；**低** = 单个社区帖、博客或推断。

`allowCommercialUse` 字段含义（Civitai）：`Image` = 可出售/商用生成的图片；`RentCivit` = 可在 Civitai 在线生成；`Rent` = 可在其它生成服务上使用；`Sell` = 可出售模型；`SellMerge` = 可出售合并模型。**空数组 = 不允许任何商用**。注意这个字段只代表 LoRA 作者的授权，**底模许可证另算，两者取更严的那个**。

---

## 一、每模型"最佳写实配方"一行汇总

"写实配方"= 我们从官方默认值 + 下载量最高的写实 LoRA/微调作者原话里拼出来的起点，**没有经过我们自己实测**。分辨率一列是按官方支持范围换算的 9:16 竖屏建议值。

| 模型 | 采样器 / 调度 | 步数 | CFG | shift | 竖屏分辨率 | 写实 LoRA + 强度（作者推荐） | 后处理 | 许可（能否商用） | 来源 |
|---|---|---|---|---|---|---|---|---|---|
| **Krea 2 Turbo** | euler / simple（官方模板）；更"脏"的质感用 res_2s/res_2m + beta | 8（官方）；社区写实多用 10–12 | 1（官方 README 写 0 = 关闭 CFG，等效） | mu 1.15（官方推荐值） | 1–2K（官方）。9:16 用 1152×2048 或约 2MP 的 1088×1920 | Lenovo UltraReal（Turbo 上 1.2–2）；或 Realistic Snapshot v1.0（1.5，最高 2.0）；或 UltraReal KR2_V2_Pro（0.6–0.8）；底模也可换 Realism by Stable Yogi v3.0（12 步、CFG 1.5） | SeedVR2（color_correction=lab）放大；需要更多皮肤细节再加低去噪二次采样 | **Krea 2 Community License**：公司年营收 < 100 万美元可商用；要标注 AI 生成、要有内容过滤 | O1–O5, C1–C6, A1, A2 |
| **Krea 2 Raw** | 官方未指定采样器；社区用 res_2m / beta | 52（官方） | 3.5（官方）；Danrisi 用 4 | 自动（按分辨率） | 官方训练到 **1K**，竖屏约 768×1344 | Lenovo UltraReal / NiceGirls 0.6–0.8；作者另一种用法是 Raw + Turbo LoRA、CFG 1 | 同上 | 同上 | O2, C3, C7 |
| **Z-Image Turbo** | res_multistep / simple（官方模板）；社区常用 euler / simple 或 euler / beta | 8（官方模板）；社区 8–12 | 1（官方 diffusers 写 guidance 0） | 3（官方模板 ModelSamplingAuraFlow） | 支持 512²–2048² 面积。社区常用 832×1216、896×1152；9:16 可用 1088×1920 | Realistic Snapshot ZIT v5 0.6–0.7；NiceGirls Asian edition；Lenovo 0.8–0.9；DetailDaemonZ 滑杆：负值 −0.4 到 −1.5 增加细节，正值 0.4–1.2 去油腻和塑料感 | 换脸区低去噪重绘 0.2–0.4；SeedVR2 | **Apache 2.0**（可商用）；LoRA 另看 allowCommercialUse | O7, O9, C8–C13, W5 |
| **Z-Image Base** | 官方未指定；社区用 res_2s | 28–50（官方） | 3–5（官方），负面提示有效 | — | 同上 | Skin Texture ZIB v2.1（触发词 photorealistic / detailed / sharp）；Amateur Photography Zbase | 可接 Z-Image-Fun 蒸馏 LoRA 降到 8 步 | **Apache 2.0** | O8, C14, C15 |
| **FLUX.2 klein 9B（蒸馏版）** | euler + Flux2Scheduler（官方模板）；社区用 res_2s / beta | 4（官方模板）；社区 4–6 | 1 | Flux2Scheduler 按分辨率自动 | 约 1MP（模板 1024²）。社区 832×1216、1152×1728 | UltraReal KL9_V5_Pro 0.6–0.8，提示词开头写 "This is a high-quality photograph of a …"；InstaPic 0.8–1.2（触发词 instapic） | Klein 自己做编辑式放大：UltraReal 用 1.0、Ultimate Upscaler Klein 用 4 步 | **FLUX Non-Commercial License v2.1**：输出可商用，但"用于营收活动"不算非商业用途，**拍商业短剧需要 BFL 商业授权**（见第四节） | O10–O13, C16–C22 |
| **FLUX.2 klein 9B Base** | euler（AI_Characters 引用的 HF 默认值） | 50（社区引用的官方默认）；ComfyUI 模板 20 | 4（社区引用）；模板 5 | — | 1MP | Lenovo UltraReal klein9b-base（作者设置 res2m + beta57、guidance 4、强度 0.85–0.9）；Smartphone Snapshot v13（触发词 casual snapshot）；Better Skin v2（触发词 with skin with textured detail） | — | 同上 | O12, C17, C20, C21 |
| **FLUX.2 klein 4B（蒸馏版）** | euler + Flux2Scheduler | 4 | 1 | 自动 | 约 1–2MP（作者样图用的是 2MP） | Ultra Real Amateur Selfies 1.0–1.25；hinablue Asian Mix v5.0 0.4–0.8（触发词 asian woman） | — | **Apache 2.0**（可商用）；LoRA 另看授权字段 | O10, C23–C26 |
| **FLUX.3 Image Klein（蒸馏版，2026-10）** | er_sde / simple（官方模板） | 4–16，默认 16（模板里是 15） | 1（固定） | — | 最高 4K（官方）。模板用 1MP | 生态太薄：官方说明里没有专门的写实 LoRA；MoreReal F3K 0.6–0.9（不可商用）；Asian Mix v1.0（没写强度） | **必须开 prompt upsampler**（官方原话） | **FLUX Kommunity License**：公司营收 < 500 万美元的"Qualifying User"可以把输出用于商业；模型本身只能非商用 | O14–O18, C27–C29 |
| **FLUX.3 Image Klein Base** | 官方未指定 | 50 | 3.5（BFL 文档表）；图像编辑时 1 | — | 同上 | — | — | 同上 | O14, O15 |
| **Qwen-Image-Edit-2511** | euler / simple | 40（模板）；用 Lightning LoRA 时 4 | 3（模板）；HF 示例 true_cfg 4 | 3.1（模板 ModelSamplingAuraFlow），并加 CFGNorm 1 | 参考图进 VAE 前缩到 **1024×1024 总面积**（源码） | 写实转换用 Anything to Real Characters 2511（触发词 transform the image to realistic photograph）；换头用 BFS V5 Focus Head；皮肤用 qwen-edit-skin（2509 训练） | Qwen Edit Upscale 2K；Lightning 加速 | **Apache 2.0**；BFS / Anything2Real 的 Civitai 字段含 Image | O19–O21, C30–C35, W1 |
| **Qwen-Image 2.1（只看 LoRA）** | Danrisi：res_2m / res_2s / res_multistep + beta | 见 RESEARCH.md | Danrisi：3–4，出图变糊就改回 1 | 见 RESEARCH.md | 见 RESEARCH.md | Lenovo UltraReal Qwen2.1；NiceGirls v1.0 Asians；Canon UltraReal 0.7（触发词 c2n0n）；GrainScape 0.7；Casual Snapshot（触发词 candid_snap）；Asian Mix v3.0 ≤0.8 | 编辑用 Qwen Image 2.1 Consistency LoRA 防漂移 | 底模见 RESEARCH.md；LoRA 授权见第二节 | C36–C44 |

**3090 显存提示**（来自文件大小，置信度高）：Krea 2 bf16 约 25GB（Civitai 镜像 25065.7MB），3090 要用 fp8_scaled（约 12.5–13.5GB）或 int8_convrot。Qwen-Image-Edit-2511 bf16 约 40.9GB、fp8 约 20.5GB（W1），3090 只能用 fp8 或 GGUF Q6（16.8GB；W1 说 Q4"基本不可用"）。klein 9B bf16 微调 checkpoint 约 17.3GB（C22），4B 约 7.4GB（C26）。FLUX.3 Klein 是 5.6B（O15），但 diffusers 版的 upsampler 要额外约 28GB 显存（O15）。ComfyUI 版是 w4a8 量化的 9B upsampler，能不能和主模型一起放进 24GB **没有验证**。

---

## 二、分模型原文引用

### 2.1 Krea 2（Turbo / Raw）

#### 官方参数

- **O2**｜Raw 是"The base undistilled model. Use the full sampler with classifier-free guidance: … The model has been trained to generate upto 1k resolution. … `--checkpoint oss_raw --steps 52 --cfg 3.5`"；Turbo"Distilled for few-step sampling — run with 8 steps and CFG disabled. The model can generate images from 1k ~ 2k resolution. … `--steps 8 --cfg 0.0 --mu 1.15`"；参数表写"`--mu` … Recommended `1.15` for `oss_turbo`"。https://github.com/krea-ai/krea-2 — **高**
- **O4**｜ComfyUI 官方模板 `image_krea2_turbo_t2i.json` 的 KSampler 是 `[seed, 8, 1, 'euler', 'simple', 1]`（8 步、cfg 1、euler、simple、去噪 1）；风格 LoRA 的示例强度是 `LoraLoaderModelOnly ['krea2_darkbrush.safetensors', 0.8]`。https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_krea2_turbo_t2i.json — **高**（直接解析 JSON）
- **O3**｜"Krea 2 supports outputs from 1K to 2K. Set the megapixels value to 2.0 to get 2K resolution."；"The defaults (8 steps, prompt enhancement enabled, no LoRA)"；"train LoRAs on RAW, run inference on Turbo"。https://docs.comfy.org/tutorials/image/krea/krea-2 — **高**
- **O1**｜Comfy-Org/Krea-2 仓库里有 `krea2_turbo_lora_rank_64_bf16.safetensors`（Turbo 蒸馏 LoRA，可以挂在 Raw 上），以及 `krea2_turbo_int8_convrot`、`fp8_scaled`、`nvfp4`、`mxfp8` 等格式；文本编码器是 `qwen3vl_4b`，VAE 是 `qwen_image_vae`。https://huggingface.co/Comfy-Org/Krea-2 — **高**
- **O6**｜官方提示词指南："Long detailed prompts yield best results"；示例里有"A close-up portrait of a young East Asian woman with straight black hair…"。https://github.com/krea-ai/krea-2/blob/main/docs/prompting.md — **高**
- **O5**｜许可证 §2.3："Commercial Use … is permitted only if you … have total company-wide annual revenue of less than one million United States dollars ($1,000,000 USD)"；§4.3："you must clearly disclose that Outputs were generated using artificial intelligence."；§4.2："You must implement reasonable and appropriate Content Filter measures"；§5.3："You own all Outputs you generate"。https://www.krea.ai/krea-2-licensing — **高**（页面经 WebFetch 摘录）

#### Civitai 写实 LoRA / Checkpoint（按下载量排序；dl = 该版本下载数，👍 = 点赞数，API 不返回差评数）

| # | 名称（modelId / modelVersionId） | 类型 / 大小 | 版本 dl / 👍 | 触发词 | 作者推荐（原文） | allowCommercialUse |
|---|---|---|---|---|---|---|
| C1 | Realism Engine Ideogram 4 + Krea 2（2688234 / **3109006**，Krea2 v3.0） | LoRA 1490MB bf16 | 56,508 / 2,769 | 无 | "Sweet spot is between 0.50-0.90."；"Don't go higher than .90"；"res_2s = best definition / res_2m = most realistic and faster than 2s / euler = fastest but less realistic"；"The default settings for the Lora's are 0.8 and 0.3-0.5 for the unconditional. If you like a cleaner image you can increase the unconditional value but it might start to look more plastic."（**大量 NSFW 概念**） | Image, RentCivit, Rent, Sell, SellMerge |
| C2 | Realistic Snapshot（2268008 / **3371723**，Krea2 v1.0） | LoRA 1490MB bf16 | 13,720（v0.5 另有 38,838）/ 780 | 无 | "Up to 2.0 is recommended. 1.5 is the sweet spot. 1.0 does little"；数据集是"real-life smartphone photography: mirror selfies, bedrooms…"；提示词用自然语言描述"Subject… Outfit and pose… Setting… Framing… Lighting" | Image, RentCivit, Rent, Sell, SellMerge |
| C3 | Lenovo UltraReal（1662740 / **3075606**，v1.0 Krea2） | LoRA 109MB fp16 | 40,670 / 1,600 | 无 | "For best quality i use raw with cfg4, for fast result i use raw, but witth cfg1 and turbo lora … recommended weight 0.8 for raw and 1.2-2 for turbo" | RentCivit, Rent, Sell, Image, SellMerge |
| C7 | NiceGirls UltraReal（1862761 / 3075498，v1.0 Krea2） | LoRA | 26,301 | 无 | 同一作者："recommended weight 0.6-0.8" | Image, RentCivit, Rent, Sell, SellMerge |
| C4 | [Krea 2] BloomGirls UltraRealism（2735553 / **3191538**） | LoRA 447.6MB fp32 | 16,300 / 892 | `bl00m` | "Base model Krea 2 (Raw) + Turbo LoRA Steps 12 CFG 1 Sampler er_sde Scheduler simple"（偏"网红光鲜"风格，不是素人风格） | Image, RentCivit, Rent, Sell, SellMerge |
| C5 | UltraReal - Moss, Krea2, Klein9b（2462105 / **3182356**，KR2_V2_Pro） | LoRA 218MB bf16 | 12,870 / 541 | 不需要 | "Weight: 0.6-0.8"；"KR2_V2 is for professionalism, not for candid or amateur quality photos."；Krea_V1"also reduces asian face bias" | Image, RentCivit, Rent, Sell, SellMerge |
| — | [KREA 2] Detail Slider（2729908 / 3068874） | LoRA 11MB | 26,609 / 1,240 | 无 | 只写了"See the examples to understand how to use"（**没有给出数值**） | Image… 全部 |
| — | Famegrid（2088956 / 3248281，Krea 2 Natural V1） | LoRA 1490MB | 4,978 | `Famegrid`（放在提示词开头） | "Recommended range: 0.3–1.0"；"If using with character lora keep strength 0.3-0.6" | Image, RentCivit, Rent |
| — | [Krea2 Turbo] Asian Mix Lora（2746042 / **3203007**，v4.0 TQD） | LoRA 223.8MB | 7,521 / 301 | `asian woman` | "Sampler: er_sde / Scheduler: simple/sgm_uniform/beta / Steps: 8 - 12" | Image, RentCivit |
| — | Realistic Slider Krea-2（2727636 / 3066073） | LoRA 6.9MB | 18,436 / 910 | 无 | "Recommended range: -2 to 3"，效果等同于加强提示词里的"Realistic" | Image, RentCivit |
| C6 | Realism by Stable Yogi Krea2（2786499 / **3329215**，v3.0 INT8+FP8 Extended） | Checkpoint 12.6GB int8 / 13.2GB fp8_scaled | 13,721 / 587 | 无（写 `asian` 会切换成东亚脸） | "Fast: 8 steps · CFG 1 … Best: 12 steps · CFG 1.5 … Range: 8–20 steps · CFG 1–2.5. ⚠️ Do not go above CFG 2.5. Euler · Simple · native 1024²+."；"Put *asian* in your prompt and the model moves to an East Asian face." | Image, RentCivit |
| — | Krea 2 CyberRealistic（2831028 / 3357068，v4.0） | Checkpoint 12.9GB fp8 / 24.5GB bf16 / 7.8GB nvfp4 | 4,989 / 379 | 无 | "full finetune of Krea 2 Turbo"；"More natural skin texture, less plastic rendering"（**没有给出采样参数**） | Image… 全部 |
| — | Krea 2 Raw（Civitai 官方镜像 2732654 / 3072329） | 12.5GB fp8 / 25.1GB bf16 | 10,940 | — | "Krea's recommended starting point is around 52 steps at CFG 3.5. It generates at up to 1024px" | 字段显示全部，但**以 Krea 许可证为准** |
| — | Kera2_WinpicAsianRealism（2789796 / 3399778） | Checkpoint 13.5GB int8 | 1,137 | 无 | 只提到皮肤"too wet or sticky"，推荐叠 Loraholic 的 wetness-slider（**没有采样参数**） | 只有 RentCivit（**不能商用出图**） |
| — | Krealism 写实（2786809 / 3348486，V3.1 Turbo int8） | Checkpoint 13.5GB | 1,261 | 无 | "All images I uploaded are Euler/ simple, 10-12 steps, no LoRAs" | Image, RentCivit |

链接格式：模型页 `https://civitai.com/models/<modelId>?modelVersionId=<vid>`，API `https://civitai.com/api/v1/model-versions/<vid>`。

#### 社区技巧

- **A2**｜RLY（Civitai 文章 31794）："For more texture/detail: res_2s/beta, 4-5 steps / For cleaner generation: er_sde/simple, 4-9 steps"。https://civitai.com/api/v1/articles/31794 — **低**（单人初步测试）
- **A1**｜lonecatone23《Realism: How to achieve it》（Civitai 文章 32409）：同样的写实提示词下对比 "Krea2 Turbo, 12 steps, cfg1.0 / Z-Image Turbo bf16, 8 steps, cfg1.0 / Klein_9b: 20 steps, cfg1.0 … Sampler: Euler Scheduler: Simple"。结论："Look at Krea2 and how the haze gently wraps around her arm, losing the 'cardboard cutout' look"；"Look at Krea. There are no roots and the color is too evenly spread"（发根不自然）；"Look at Z-Image Turbo. Good hair strands as well as realistic roots"。https://civitai.com/api/v1/articles/32409 — **低到中**（单人对比，但样例详细）
- **C1 作者**：Krea 2 的 CFG/unconditional 拉高会"look more plastic"。**中**

#### 身份保持（Krea 2）

- **原生**：官方 ComfyUI 只提供 style reference（`krea2_style_reference` LoRA，参考 1–2 张图的**风格**），**不是身份参考**（O3："referencing the style of 1–2 uploaded images"）。**高**
- **Krea 2 Identity Edit V2**（2761113 / **3409322**；两个 LoRA 各 1743.6MB bf16；另有 r128 0.91GB、r64 0.46GB 版本；v1.2 下载 24,695 次）— O25 / HF 原文：
  - "Requires the ComfyUI-Krea2Edit node pack — the LoRAs are trained with dual conditioning (in-context VAE tokens + image-grounded Qwen3-VL encoding) that stock nodes don't provide."（**不是原生节点**）
  - 设置："Restage one person (single reference) | Turbo | 8 | 1.0 | ref_boost 2 | grounding_px 768 | beside or aligned"；"Add a person to a scene (scene = image 1, person = image 2) … person 2–3, scene 1 … scene aligned, person beside"；"Face-locked portraits … ref_boost 1–2 … aligned"；"Generate at ≤2MP"
  - 提示词写法："Say how much of the person is visible … 'full body' gets the whole person"；"Describe the outfit concretely, and what should be gone"；"Describe light by where it lands"
  - 限制："Clothing from the reference photo can carry over"；"Head swaps tend to become whole-person swaps"；"loading both at strength 1.0 produces pure noise … use about 0.6 each"
  - 许可："free for personal / non-commercial use; commercial use needs a license from me, case by case"
  - https://huggingface.co/conradlocke/krea2-identity-edit — **高**（作者原文），效果**中**（未实测）

---

### 2.2 Z-Image（Turbo / Base，Tongyi-MAI）

#### 官方参数

- **O7**｜Turbo 的 diffusers 示例：`num_inference_steps=9,  # This actually results in 8 DiT forwards`、`guidance_scale=0.0,     # Guidance should be 0 for the Turbo models`；模型对比表里 Turbo 的 CFG 一栏是 ❌、Diversity 是"Low"。https://huggingface.co/Tongyi-MAI/Z-Image-Turbo — **高**
- **O8**｜Base："Resolution: 512×512 to 2048×2048 (total pixel area, any aspect ratio) / Guidance scale: 3.0 – 5.0 / Inference steps: 28 – 50"；"Robust Negative Control: Responds with high fidelity to negative prompting"；对比表里 Negative Prompting 一行是 Z-Image ✅、Turbo ❌；示例用 `height=1280, width=720`（竖屏）。https://huggingface.co/Tongyi-MAI/Z-Image — **高**
- **O9**｜ComfyUI 模板 `image_z_image_turbo.json`：`ModelSamplingAuraFlow [3]`、`KSampler [.., 8, 1, 'res_multistep', 'simple', 1]`、`EmptySD3LatentImage [1024,1024]`。https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_z_image_turbo.json — **高**
- 许可：两个模型的 HF 卡片都是 `license: apache-2.0`（O7、O8）。**高**

#### Civitai 写实 LoRA / Checkpoint

| # | 名称（modelId / vid） | 类型 / 大小 | 版本 dl / 👍 | 触发词 | 作者推荐（原文） | allowCommercialUse |
|---|---|---|---|---|---|---|
| C8 | Realistic Snapshot（2268008 / **2617751**，ZIT v5 Real Life） | LoRA 162.2MB | 42,908 / 2,184 | 无 | "Ensure you keep the strength at around 0.60-0.70, maybe lower." | Image… 全部 |
| C9 | Lenovo UltraReal（1662740 / **2452071**，v1.0 Z-Image Turbo） | LoRA 81.2MB | 31,548 / 1,461 | `l3n0v0` | "Recommend to use with strength 0.80-0.9 / I used euler + sgm_uniform with 4 guidance / P.S: at this moment for ComfyUI u need this pack to load lora properly https://github.com/PGCRT/CRT-Nodes" | RentCivit, Rent, Sell, Image, SellMerge |
| C10 | NiceGirls UltraReal（1862761 / **2526600**，Z-Image Asian edition；另有欧美版 2465980，下载 30,111） | LoRA 648.8MB | 18,976 / 937 | 无 | "I used 40 steps to test the limits, but you can definitely achieve good results with fewer steps like 20" | Image… 全部 |
| C11 | Realistic Skin Texture style（580857 / **2674760**，Skin Texture ZTurbo v4.5） | LoRA 162.2MB | 21,789 / 951 | incredibly lifelike, cinematic, detailed, sharp, fine texture, Hyperrealistic, photorealistic | "Lower or rise lora weight for optimal results. This version is sharper than previous one."（**没写具体数值**） | **只有 RentCivit**（不能商用出图） |
| C12 | [ZIT] Detail Slider（2234266 / 2515203） | LoRA 20.3MB | 26,300 / 1,414 | 无 | "Over 2 it may start to darken the image, and under -2 brighten by a lot. It is very good between -2 and 2." | Image… 全部 |
| C13 | DetailDeamonZ-SliderLoRA（2209262 / **2487375**） | LoRA 133.7MB | 12,066 / 816 | 无 | "负向权重（-0.4~-1.5）：越推细节越多，皮肤纹理、布料纤维…"；"正向权重（0.4~1.2）：越推越干净，油腻感、塑料感、过锐化一键抹平"；"推荐采样步骤：8~12步…推荐权重区间：-1.5 ~ +1.5"；"LoRA不包含全部key，加载时提示部分层丢失请无视" | Image… 全部 |
| — | [Z Image Turbo] Asian Mix Lora（2185778 / 2715206，v4.59） | LoRA 324.4MB | 5,500 | `asian woman` | "Recommend Weight: 0.6-0.8"；v5.0 是"leans towards low-noise presentation, which might give it a very AI-like feel"（作者自己说更 AI 感） | Image, RentCivit |
| — | Famegrid（2088956 / 3018207，ZIT Spicy v2） | LoRA | 7,698 | `Famegrid` | 0.3–1.0 | Image, RentCivit, Rent |
| C14 | Skin Texture ZBase v2.1（580857 / **2965913**，ZImageBase） | LoRA 162.2MB | 12,067 / 406 | photorealistic, detailed, sharp | 同 C11 | 只有 RentCivit |
| C15 | Amateur Photography（652699 / **2772577**，Zbase "Nano banana at home"） | LoRA 558.4MB | 6,765 / 463 | 无 | "res_2s recommended"；可以配"Distill lora for base - … Z-Image-Fun-Lora-Distill-8-Steps … or …4-Steps-2602-ComfyUI" | 只有 RentCivit |
| Ck | BEYOND REALITY 超越真实（1090420 / 2648189，淡妆浓抹 v3.0） | Checkpoint 11.7GB bf16 | 7,034 / 627 | 无 | "CFG:1，10~15步，euler+simple 采样器调度器 / 善用SeedVarianceEnhancer等节点，增加画面的多样性表达" | Image… 全部 |
| Ck | CyberRealistic Z-Image Turbo（2218365 / 3331554，v9.0） | Checkpoint 6.6GB int8/fp8，11.7GB bf16 | 3,548 | 无 | "More natural skin texture with less waxy or overly polished rendering"；"Describe the image instead of building a tag" | Image… 全部 |
| Ck | Zenith（2237711 / 3319176，13.3） | Checkpoint 5.9GB fp8/int8 | 151（整个模型 80,228） | 无 | "Steps: 12 / CFG: 1.0 / Sampler: dpmpp_sde / Scheduler: simple" | Image, RentCivit, SellMerge |
| Ck | IntoRealism（1609320 / 3354988，ZIT V10） | Checkpoint 5.9GB fp8 | 3,412 | 无 | "ZIT Usage: Sampling method: Euler / Beta, Sampling steps: 6/10, Resolution: 896x1152 / 832x1216, CFG: 1"；"Ignore the license tag above (platform limit). My real terms : https://enzinoai.com/license" | RentCivit, Rent（**另有独立许可**） |
| Ck | Moody Real Mix（621441 / 3005060，ZIT V7） | Checkpoint 11.7GB | 7,095 | 无 | XHS 萌妹版作者原话："「皮肤质感太磨皮」…这些都不是缺点"——**不适合写实**，应该用 Global V7 | 只有 RentCivit |
| Ck | 2127 Z Image Asian Utopian（2247533 / 3146189，v4.0 Turbo） | Checkpoint 5.9GB int8 | 2,150 | `asian woman` | v4.6 加入 600 张亚洲脸，"reduce the material performance problem of some faces being too smooth"（**没写采样参数**） | Image, RentCivit |

#### 社区技巧

- **W5**｜Z-Image Turbo 放大 + 细节工作流："second-pass denoise around 0.2 to 0.4"；Next Diffusion 默认 0.3，"drop to 0.2 if the pass changes the composition"。https://www.nextdiffusion.ai/tutorials/z-image-turbo-upscaler-and-detailer-workflow-in-comfyui ；https://www.divyarthinfotech.com/blog/z-image-turbo-upscaler-and-detailer-workflow-in-comfyui — **低到中**（两家教程说法一致）
- **W6**｜HF 讨论：有人反映 Turbo 出现"lizard-like"的皮肤和眼睛纹理，回复建议用 Z-Image 放大或 SeedVR 处理。https://huggingface.co/Comfy-Org/Boogu-Image/discussions/8 — **低**
- **A1**｜"Too many steps overcooks the image and it starts to become plastic-like."；ZIT 12 步比 8 步解剖结构更好；"dpmpp gives a softer feel. I like res_2m as it is sharper"；双采样："set them as normal, then drop the cfg to 1.0 in the second sampler to act as a refiner"；"Clownshark Sampler with Step Overshot: If you want realism, this sampler is the best way to go"（RES4LYF 包）；"Zit sucks at variety in general"。— **低到中**
- **Detail Daemon（O24）**："For Flux or Z-Image models, you'll probably want between 0.1–1.0 range"；start 建议 0.1–0.5，end 建议 0.5–0.9；"work by default with custom sampler nodes such as SamplerCustomAdvanced"。https://github.com/Jonseed/ComfyUI-Detail-Daemon — **高**（README 原文）
- **多样性**：Turbo 官方自己标注 Diversity Low（O7）；BEYOND REALITY 作者建议用 SeedVarianceEnhancer。**高 / 中**

#### 身份保持（Z-Image）

- 官方表里 "Z-Image-Omni-Base … Gen. / Editing … *To be released*"、"Z-Image-Edit … *To be released*"（O7）——**到本文日期，HF 卡片上仍没有官方的参考图/编辑权重**。**高**（以 HF 卡片为准；可能已经发布但卡片没更新，**未证实**）
- 所以 Z-Image 做身份只能靠角色 LoRA（在 Base 上训、Turbo 上用），或者先用 Klein / Qwen-Edit 做身份图再给 Z-Image 做低去噪精修。社区原话："Training a LoRA is the only truly reliable way to produce consistency."（W4 https://reddit.sentinel-team.org/posts/1rvxceo/snapshots/2026-03-20T16%3A21%3A25.533725Z）— **低**
- Famegrid 作者："If using with character lora keep strength 0.3-0.6. You can also try turning down character lora as much as possible to keep likeness and turn up the Famegrid lora more."（C 2088956）— **中**

---

### 2.3 FLUX.2 [klein] 4B / 9B

#### 官方参数

- **O10**｜4B："supports multi-reference editing capabilities"；"Fully open under Apache 2.0. … runs on consumer GPUs like the RTX 3090/4070"；diffusers 示例 `guidance_scale=1.0, num_inference_steps=4`。https://huggingface.co/black-forest-labs/FLUX.2-klein-4B — **高**
- **O11**｜9B 许可证："FLUX Non-Commercial License v2.1"；§2(d)"You may use Output for any purpose (including for commercial purposes), except as expressly prohibited herein."；§1(c) Non-Commercial Purpose 只在"you do not receive any direct or indirect payment"时成立，并且"use (a) for revenue-generating activity"不算非商业用途。https://huggingface.co/black-forest-labs/FLUX.2-klein-9B/blob/main/LICENSE.md — **高**
- **O12**｜ComfyUI 模板解析结果：`image_flux2_klein_text_to_image.json` 里，Base 用 `Flux2Scheduler [20,1024,1024]` + `CFGGuider [5]`，蒸馏版用 `Flux2Scheduler [4,…]` + `CFGGuider [1]`，采样器都是 `KSamplerSelect ['euler']`；编辑模板（4B/9B 蒸馏）用 `ReferenceLatent`（每张参考图一个，串联）、`ImageScaleToTotalPixels ['lanczos'/'nearest-exact', 1, 1]`（参考图缩到 **1MP**）、`EmptyFlux2LatentImage [1024,1024]`、4 步、cfg 1。— **高**
- **O13**｜"distilled ~1.2s (5090) · 8.4GB VRAM; base ~17s (5090) · 9.2GB VRAM"（4B）。https://docs.comfy.org/tutorials/flux/flux-2-klein — **高**
- BFL 帮助中心：klein 多参考"Up to 4 images"，"FLUX.2 [klein] does not include prompt upsampling. Write detailed, descriptive prompts"（WebSearch 摘要，https://help.bfl.ai/articles/8642316687-flux-2-klein-fast-generation-guide）— **中**（没有直接读到原页）

#### Civitai 写实 LoRA（9B）

| # | 名称（modelId / vid） | 基模 / 大小 | 版本 dl / 👍 | 触发词 | 作者推荐（原文） | allowCommercialUse |
|---|---|---|---|---|---|---|
| C16 | UltraReal（2462105 / **2846977** KL9_V4；最新 **3370879** KL9_V5_Pro） | 9B，158MB | 14,053 / 433 | "This is a high-quality photograph of a (your subject...)" | "Weight: 0.6-0.8"；"LoRAs for reducing the soft & smooth AI look"；用于编辑/放大时："Resoluton: 1.5MP - 2MP / Weight: 1.0 For V5, 0.5 for later versions"，提示词"Make this photo high-quality. Preserve subject's face, expression, figure and pose. Preserve overall composition of this photo." | Image… 全部 |
| C17 | Lenovo UltraReal（1662740 / **2682771**，Klein 9b Base） | 9B-base，161MB | 21,796 / 781 | 无 | Flux2 段："I use it with res2m+beta57, guidance 4 … Recommend to use with strength 0.85-0.9" | RentCivit, Rent, Sell, Image, SellMerge |
| — | NiceGirls UltraReal（1862761 / 2682864，Klein 9b Base） | 9B-base | 11,189 | 无 | 同一作者 | Image… 全部 |
| C18 | Realism Engine Klein（2374977 / 2679241 v2.0） | 9B，1040MB | 20,364 / 797 | 无 | "Use the Lora weight of 1 to 1.25"；"doesn't fix Klein limbs issues"（**主要是 NSFW 概念**） | Image, RentCivit, Rent |
| C19 | InstaPic（2168120 / **2998522** F2 Klein 9B V3） | 9B，158MB | 8,205 / 242 | instapic, hard flash, camera flash, smartphone photo, candid, shot on iphone, high detail skin | "Recommended Strength: 0.8 to 1.2 (Start at 1.0…) … CFG : 1" | Image, RentCivit |
| — | Portrait Engine（2067704 / 2998669，V4.0 Flux klein） | 9B，158MB | 8,214 | 无 | 没有给出采样参数 | Image, RentCivit |
| — | Phone Photography 2025（2537408 / 2862425） | 9B，158MB | 3,945 | "This is a candid photograph taken with a smartphone of" | 编辑时在前面加 "Make…" | Image… 全部 |
| C20 | Smartphone Snapshot Photo Reality v13（2381927 / **2916530**） | 9B-base，41.4MB | 5,524 / 229 | `casual snapshot` | "euler (sampler), 50 steps, cfg 4, 1 megapixel resolution … (which are the default settings for the model as per its HuggingFace page)"；提示词："a 'literal, technical' prompt that is about 2 paragraphs long" | Image… 全部 |
| C21 | Better Skin v2（2613362 / **2946217**） | 9B-base，41.4MB | 3,649 | `with skin with textured detail` | 同 C20；"The skin is not perfectly real and it changes the image somewhat" | Image… 全部 |
| — | Realism Slider v2（2401004 / 2758892） | 9B-base，19.8MB | 2,935 | 无 | "Klein can create realistic looking images like ZIT, it just needs a nudge … Use up to strength 6." | Image… 全部 |
| — | Elusarca's Detail Enhancer（2442399 / 2746136） | 9B，632MB | 8,234 | `Enhance this image` | "bad image = high strength(0.7-1.0) / good image = low strength(0.3-0.6)" | RentCivit, Rent（不能商用出图） |
| — | Ultimate Upscaler Klein-9b（2474084 / 2781657） | 9B，237MB | 10,743 | 固定提示词 "restore the image quality, remove any compression artefacts…" | "Use the fast variant with 4 steps … max 12"；"its very good at keeping faces" | RentCivit, Rent（不能商用出图） |
| C22 | FLUXTRAIT Klein_9b_V3（2086049 / 2903822） | Checkpoint 17.3GB bf16 | 5,318 | `Fluxtrait` | 只有营销文字，**没有采样参数** | Image, RentCivit |

#### Civitai 写实 LoRA（4B）

| # | 名称（modelId / vid） | 大小 | 版本 dl | 触发词 | 作者推荐（原文） | allowCommercialUse |
|---|---|---|---|---|---|---|
| C23 | Ultra Real - Amateur Selfies（2233658 / **2666766**） | 88.1MB | 2,880 | 无 | "Flux2klein9b Distilled : Res_2s/Beta 4-6 Steps 832x1216 … strength of 1.25-1.50"；"The 4B settings are similar … 1.0-1.25 is sufficient"；"the sample photos at 9b are in 1mp resolution and at 4b in 2mp" | RentCivit, Image |
| C24 | [Flux.2 Klein 4b] Asian Mix Lora v5.0（2423116 / **3407134**） | 176.3MB | 201 | `asian woman` | "Recommend Weight: 0.4 - 0.8"；推荐前缀"Hyper-realistic photographic, extremely high-resolution details, realism pushed to extreme, fine texture, incredibly lifelike, asian woman"；作者自己说"the limb performance is still not ideal" | Image, RentCivit |
| C25 | Real Skin (Less Synthetic)（2534398 / 2856208） | 367.5MB | 697 | 无 | 只写了"Trained in TF32"（**没有参数**） | Image, RentCivit |
| — | RebelReal（2181922 / 2615376） | 88.1MB | 940 | 无 | "i suggest 0.2 - 0.8 … .4 - .7 is the sweetspot" | Image… 全部 |
| — | Realistic Skin & Face（1426727 / 3108164） | 88.1MB | 629 | 无 | 没有参数 | 只有 RentCivit |
| C26 | unStable Revolution F2K 4b alpha（2355813 / 2650607） | Checkpoint 7.4GB fp16 | 6,929 | 无 | "Sampler Euler / DPM++ 2M SDE, Scheduler Simple / Beta, 4-5 Steps … i like 896x1152 … Not tested with negative Prompts" | 只有 RentCivit |

#### 社区技巧

- **A4**｜FloyoAI《FLUX.2 Klein 9B + Realistic Enhanced Details LoRA》：做 img2img/编辑式写实补强，"LoRA strength runs from 0.5 to 0.8 … Start at 0.65"；"CFG: 3.5–4.5"（看 CFG 值，这是 **Base** 版用法）；"Steps: 20 for final output"；"Plastic faces at high CFG: drop to 3.5 and add 'natural skin texture, avoid over-smoothing'"；负面提示 "plastic skin, over-smoothed, blurry, flat lighting, painterly, cartoon"（**只在 CFG>1 的 Base 版有效**）；"VRAM: needs 24GB+ for full quality"。https://civitai.com/api/v1/articles/27526 — **低**（工作流平台的推广文）
- **A1**｜"Klein_9b … Notice how there is no real DOF?"；"Klein_9b looks like someone used a brown marker"（雀斑像马克笔点上去的）。— **低**

#### 身份保持（klein）

- **原生写法（高）**：参考图 → `ImageScaleToTotalPixels`（1MP）→ VAE 编码 → `ReferenceLatent` 串联到正面条件（多张图就串多个）→ `CFGGuider`（cfg 1）→ `Flux2Scheduler` 4 步（O12）。
- **第一张参考图权重最大（低）**：W2 原话 "klein always gives full attention to first ref image, capturing the identity from it pretty well, but the identity from second ref image is only like 70% there. This behaviour is consistent across many seeds"。→ **身份图放第一张**。https://reddit.sentinel-team.org/posts/1somo2r/snapshots/2026-04-24T22%3A28%3A55.157497Z
- **身份引导节点（低，第三方自定义节点，不是原生）**：ComfyUI-Flux2Klein-Enhancer 的 Identity Guidance："strength: how hard to pull toward the reference. 0.3 to 0.5 is a good range"（同 W2）。
- **单参考图的小技巧（低）**：W3 "If I am only using a single reference image … I use an empty .png image (nothing but a transparent background) for the 2nd reference image"。https://reddit.sentinel-team.org/posts/1ryhz6s/snapshots/2026-03-20T16%3A21%3A25.533725Z
- **换头 LoRA**：BFS F.K. 9b V1 Focus Head（2027766 / **2610018**，632MB rank128 + rank64 zip，10,848 dl，Image… 全部）。触发提示词原文 "head_swap: start with Picture 1 as the base image, keeping its lighting, environment, and background. remove the head from Picture 1 completely and replace it with the head from Picture 2, strictly preserving the hair, eye color, nose structure of Picture 2. copy the direction of the eye, head rotation, micro expressions from Picture 1…"；作者原话："I've done my best so far, but the results aren't as good as with QWEN."— **中**
- **一致性 LoRA**：Consistence Edit Lora Klein 9B lcs（1939453 / **2863285**，332MB，8,276 dl）："Suggested Strength: 0.5-0.7 … More strength means more consistence but it would also hurt edit abilities"；提示词后缀 "Transform the image to realistic photograph. add realistic details to the corrupted image. restore high frequence details from the corrupted image."。**allowCommercialUse 是空数组 = 不可商用**。— **中**

---

### 2.4 FLUX.3 Image Klein（2026-10）

#### 官方参数

- **O15**｜BFL 文档："It runs faster and fits on consumer GPUs, down to an RTX 3090. **Do not use it without its prompt upsampler.**"；参数表：Parameters 5.6B / 5.6B；Max resolution "Up to 4K"；Inference steps 16（Distilled）/ 50（Base）；Guidance (CFG) 1 / 3.5；"[the upsampler] adds about 28 GB of GPU memory"（diffusers 版）。https://docs.bfl.ml/flux_3/flux3_image_klein.md — **高**
- **O14**｜ComfyUI 文档："The step-distilled checkpoint runs at 16 steps with guidance fixed at 1"；"Set steps between 4 and 16 (16 by default) … raising cfg does not help"；"Multi-reference prompting via `<ref_image_0>`, `<ref_image_1>`"；"References are added to both conditionings … add each one to both the positive and the negative prompt"；"The templates resize each reference to roughly 1 megapixel … Keeping references at their native size, which Black Forest Labs' own pipeline does up to about 16 megapixels, keeps more detail"；"Write the result, not the change"；需要 "ComfyUI 0.41.0 or later"；文本编码器用 `CLIPLoader type flux3`；VAE 是 FLUX.2 VAE。https://docs.comfy.org/tutorials/flux/flux-3-klein — **高**
- **O17**｜模板 JSON：`image_flux3_klein_distilled_t2i.json` 的 KSampler 是 `[3, 15, 1, 'er_sde', 'simple', 1]`；编辑模板是 `[.., 16, 1, 'euler', 'simple', 1]` + `ReferenceMultiLatent ['resize', 1]`。— **高**
- **O18**｜BFL 提示词指南：写实要描述 "the era, the camera or film stock, and what that look does to the image (grain, color cast, flash, focus)"；"Name the camera, lens, or film stock instead of writing 'professional photo'"；示例"2000s Digicam: early digital camera, slight noise, flash photography, candid"。https://docs.bfl.ml/guides/prompting_unified_style.md — **高**
- **O16**｜许可证 §1.e："[Qualifying User] if at any time you together with your affiliates' gross annualized revenue is less than US$5,000,000"；§2.a(ii)："solely if you are a Qualifying User, use Outputs … for commercial purposes"；§2.b：模型本身"only … for Non-Commercial Purposes"；§2.e：输出要附 AI 生成标注。https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/LICENSE.md — **高**（WebFetch 摘录）

#### Civitai（发布刚两周多，生态很薄）

| # | 名称（modelId / vid） | 大小 | dl / 👍 | 触发词 | 作者推荐（原文） | allowCommercialUse |
|---|---|---|---|---|---|---|
| C27 | MoreReal F3K（2904424 / **3414035**） | 76.7MB | 638 / 46 | "Convert this image into a photograph" | "Weight : 0.6~0.9"；免责声明 "Do not use it for any commercial activities." | 只有 RentCivit |
| C28 | [Flux3 Klein] Asian Mix Lora v1.0（3006882 / **3411732**） | 153.3MB | 288 | 无 | "Trained on Flux.3 Klein Base … also compatible with distilled versions … the model is sensitive to NSFW content"（**没写强度**） | Image, RentCivit, SellMerge |
| C29 | NexBlend 01 Asian Realistic LoRA（3006241 / 3410941） | 153.3MB | 242 | 无 | 只写了 "Character LoRA" | RentCivit, Rent |

Civitai 上 baseModel 为 `Flux.3 Klein` 的 Checkpoint 只有 3 个、`Flux.3 Klein-base` 的只有 2 个，**都不是写实微调**。**高**（API 结果）

#### 身份保持
官方写法：`Set Reference Multi Latent` 按顺序接参考图，提示词里用 `<ref_image_0>` 指代（ComfyUI，O14）；BFL API 的写法是"image 1 / image 2"（O18 basics："refer to references by position"）；官方原话："reference images anchor content, they do not lock structure"（WebSearch 摘要，来源是第三方教程）——**中**。专门针对 FLUX.3 Klein 的身份/换脸社区 LoRA：**没找到**。

---

### 2.5 Qwen-Image-Edit-2511

#### 官方参数

- **O19**｜HF：`"true_cfg_scale": 4.0, "negative_prompt": " ", "num_inference_steps": 40`；"Qwen-Image-Edit-2511 Enhances Character Consistency … preserving the identity and visual characteristics of the subject"；"integrates selected popular LoRAs directly into the base model"。许可 `apache-2.0`。https://huggingface.co/Qwen/Qwen-Image-Edit-2511 — **高**
- **O20**｜ComfyUI 模板 `image_qwen_image_edit_2511.json`：`ModelSamplingAuraFlow [3.1]`、`CFGNorm [1]`、`FluxKontextMultiReferenceLatentMethod ['index_timestep_zero']`（正负条件各一个）、`TextEncodeQwenImageEditPlus`、`KSampler [.., 40, 3, 'euler', 'simple', 1]`、可选 `Qwen-Image-Edit-2511-Lightning-4steps-V1.0-bf16` LoRA（强度 1）。https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_edit_2511.json — **高**
- **O21**｜ComfyUI 源码 `comfy_extras/nodes_qwen.py`：`TextEncodeQwenImageEditPlus` 只有 `image1`/`image2`/`image3` 三个输入；送给视觉语言模型的图缩到 `384*384` 总面积，送进 VAE 的参考 latent 缩到 `1024*1024` 总面积（边长取 8 的倍数）；提示词前面拼的是 `"Picture {}: <|vision_start|><|image_pad|><|vision_end|>"`。→ **提示词里用 "Picture 1 / Picture 2 / Picture 3" 指代参考图**（BFS 触发词就是这么写的）。https://github.com/comfyanonymous/ComfyUI/blob/master/comfy_extras/nodes_qwen.py — **高**

#### Civitai（基模字符串是 `Qwen`）

| # | 名称（modelId / vid） | 大小 | dl / 👍 | 触发词 | 作者推荐（原文） | allowCommercialUse |
|---|---|---|---|---|---|---|
| C30 | BFS - Best Face Swap（2027766 / **2556739**，QIE 2511 V5 Focus Head） | 293.2MB（rank16 合并版）+ 1291MB zip | 12,099 / 516 | "head_swap: start with Picture 1 as the base image … replace it with the head from Picture 2, strictly preserving the hair, eye color, nose structure of Picture 2 …" | "the merged version performs better, particularly in its ability to reproduce a wider range of expressions"；"If you are going to use Qwen Image Edit 2511, update your comfyui before anything else … The 2511 model has an architecture with a few more layers" | Image… 全部 |
| C31 | Consistence Edit Lora（1939453 / **2585269**，qe2511 alpha） | 585.2MB | 11,168 / 441 | 无 | 同一系列，0.5–0.7 | **空 = 不可商用** |
| C32 | Anything to Real Characters 2511（2294036 / **2581471**） | 337.7MB | 5,090 / 317 | `transform the image to realistic photograph` | "Face Consistency: Significantly improved facial stability"；"Realism Boost: Drastically improved skin textures"；训练用了 "103 high-quality pairs" | Image… 全部 |
| C33 | qwen-edit-skin（2097058 / **2376235**，v1.1） | 281.5MB | 9,276 / 234 | 无 | "Finetuned LoRA for Enhanced Skin Realism in **Qwen-Image-Edit-2509**"（**不是专门为 2511 训练的**，2511 上能不能用**未证实**） | Image… 全部 |
| C34 | Qwen Edit Upscale 2K（2312039 / **2601236**，2511） | 562.7MB | 1,635 | "Upscale this picture to 4K resolution" | "mainly used for losslessly enlarging images to approximately 2K"；"licensed under the Apache 2.0 license" | Image… 全部 |
| C35 | Qwen Edit Reality Transform（1906441 / 2157828） | 562.7MB | 10,318 / 726 | `transform into realistic photography` | "Sampler: Euler / LoRA Weight: 1 / CFG: 1.0 (Using the Qwen-Image-Lightning-8steps-V1.1 …) / Steps: 8"；"high-resolution upscale: 1.5× scale. Denoising set to 0.4. Beta scheduler"（**基于 2509 之前的 Edit 版本**） | 只有 RentCivit |

#### 社区技巧 / 身份

- **W1**｜MyAIForce QIE 2511 深度测评："BF16: ~40.9 GB"、"FP8: ~20.5 GB"、"Q4 is described as basically unusable"、"BF16 and Q6 look extremely similar"；不建议在 FP8-Lightning 合并模型上再叠 4 步 LoRA；不接两个 Edit Model Reference Method 节点时"FP8 Lightning skin becomes 'smooth' in a way that doesn't match the original identity"，接上之后"better identity consistency and cleaner texture"；"2511 keeps identity and edit control significantly better"；采样器除 euler/simple 外，"ER SDE + DDIM Uniform also gives strong results"。https://myaiforce.com/qie-2511/ — **低到中**（单作者，但有对比图）
- 身份图写法（**高**，来自源码和模板）：一次最多 3 张图；身份图放 image1 时提示词写 "Picture 1"；保持模板里的 `index_timestep_zero`。
- 换头/换脸社区首选 BFS V5（C30）。**中**

---

### 2.6 Qwen-Image 2.1（只补 Civitai 写实 LoRA）

| # | 名称（modelId / vid） | 大小 | dl / 👍 | 触发词 | 作者推荐（原文） | allowCommercialUse |
|---|---|---|---|---|---|---|
| C36 | Lenovo UltraReal v1.0 Qwen2.1（1662740 / **3349565**） | 76.0MB fp16 | 18,149 / 407 | 无 | "--Qwen2.1 Me recommendations: 3-4 cfg (but if image become slop, then change to 1) beta scheduler, res_2m / res_2s / res_multistep (2s best quality, multistep the fastest, 2m balance)"（**这一版没写强度**；作者给旧版 Qwen 的经验是"possible (and even have better effect) to use lora with values 1.5 - 2.0"） | RentCivit, Rent, Sell, Image, SellMerge |
| C37 | NiceGirls UltraReal v2 Qwen2.1（1862761 / **3352079**） | 76.0MB | 9,270 / 267 | 无 | "I finally assembled new dataset" | Image… 全部 |
| C38 | NiceGirls UltraReal v1.0 Qwen2.1 **Asians**（1862761 / **3349898**） | 76.0MB | 2,033 / 99 | 无 | "one with slavic girls another with asians. Honestly with asians looks better right now" | Image… 全部 |
| C39 | Qwen Image 2.1 Consistency LoRA（2969143 / **3364470**） | 152.1MB bf16 | 7,315 / 275 | 无 | "the edit happens on the original's frame, so nothing moves"；"Restyles … median 24.3 px without the LoRA, 1.6 px with it"；"Step 1500: stops the drift and keeps Qwen's own look" | **只有 RentCivit** |
| C40 | GrainScape UltraReal v1.0 Qwen2.1（1332651 / **3352222**） | 76.0MB | 2,913 | 无 | "--Qwen2.1 Use at 0.7 strength"（胶片颗粒风格） | Image… 全部 |
| C41 | Casual Snapshot Realism Qwen 2.1（2790570 / **3357747**） | 152.1MB | 2,723 / 126 | `candid_snap` | "harsh flash, bad white balance, soft focus, blown-out windows and awkward framing"；"Qwen works best with natural-language paragraphs" | Image, RentCivit |
| C42 | Canon UltraReal v1.0 Qwen2.1（2783143 / **3352035**） | 76.0MB | 2,249 | `c2n0n` | "Use with 0.7 strength"；"Prompt should be detailed (trigger word is not enough), try to describe about out-of-focus objects on foreground or background" | Image… 全部 |
| C43 | MoreReal Qwen-image-2.1（2904424 / **3374264**） | 152.1MB | 2,023 | `photorealistic` | "Weight : 0.6~0.9"；"Do not use it for any commercial activities." | 只有 RentCivit |
| C44 | [Qwen Image] Asian Mix v3.0 Q21 rank64（1905553 / **3374888**） | 320.1MB | 2,607 | `asian woman` | "It is more stable at a weight below 0.8. Limb/anatomy issues may still occasionally occur" | Image, RentCivit |
| — | BFS Qwen 2.1 Head Swap v1.1（2027766 / 3356102） | — | 7,860 | （同 BFS 系列） | — | Image… 全部 |
| — | SamsungCam UltraReal v1.0 Qwen2.1（1551668 / 3354434） | — | 3,028 | — | 模型标了 NSFW | Image… 全部 |
| Ck | Noct Q V4.0 Base（2958896 / 3372040） | Checkpoint 6.9GB int8/fp8，13.6GB bf16 | 11,800 | 无 | "25 steps, euler, simple, cfg 3 with the negative prompt"；Turbo："6 steps, euler, no CFG, 832x1248"（**以无审查为卖点**） | **空 = 不可商用** |

---

## 三、跨模型通用技巧（第 2 项汇总）

| 技巧 | 原文 / 数值 | 来源 | 置信度 |
|---|---|---|---|
| **cfg=1 时负面提示无效** | ComfyUI `sampling_function`：`if math.isclose(cond_scale, 1.0) and model_options.get("disable_cfg1_optimization", False) == False: uncond_ = None`（cfg=1 时直接不算负向那一遍）。对 Krea Turbo、ZIT、klein 蒸馏版、FLUX.3 Klein 蒸馏版、Qwen-Edit+Lightning 都成立。Z-Image 官方也写 Turbo 的 Negative Prompting ❌ | O21b https://github.com/comfyanonymous/ComfyUI/blob/master/comfy/samplers.py ；O8 | 高 |
| 负面提示有效的情形 | Z-Image Base（"Robust Negative Control"）、Krea Raw（cfg 3.5）、klein Base（cfg 4–5）、Qwen-Edit 不加 Lightning（cfg 3–4）、FLUX.3 Klein Base（cfg 3.5） | O8, O2, O12, O19, O15 | 高 |
| 去塑料感：降低 CFG / unconditional | "increase the unconditional value but it might start to look more plastic"（C1）；"Plastic faces at high CFG: drop to 3.5"（A4）；RunComfy："if pores fade or skin looks plastic, lower guidance"（W5 附带） | C1, A4 | 中 |
| 去塑料感：步数不要太多 | "Too many steps overcooks the image and it starts to become plastic-like."（ZIT） | A1 | 低 |
| 去塑料感：写实风格 LoRA | 下载量最高的几个（Lenovo、NiceGirls、Realistic Snapshot、UltraReal）都是用手机/旧相机真实照片训练的"去 AI 光鲜"LoRA | C2, C3, C5, C8, C9, C16 | 中 |
| 不要用 LoRA 调色 | "There are a few LoRAs out there that try to handle brightness, contrast, temperature, and color grading … they retrain portions of the U-Net weights … Don't use sliders where a simple node work." | A1 | 低 |
| 提示词：写具体的相机、镜头、光线 | "Name the camera, lens, or film stock instead of writing 'professional photo'"（BFL）；Krea Identity Edit："Describe light by where it lands"；Canon UltraReal："describe about out-of-focus objects on foreground or background" | O18, O25, C42 | 高 / 中 |
| 二次放大：SeedVR2 | 3B/7B，有 fp16 / fp8 / GGUF；"High VRAM (24GB+): Use FP16 models"；color_correction 默认 wavelet，"`lab`: … recommended for highest fidelity to original"；单张图 batch_size=1；高分辨率出伪影时 "input_noise_scale … Try 0.1-0.3"，"latent_noise_scale … can soften excessive detail … try 0.05-0.15"；VAE tile 默认 1024、重叠 128；7B 有 `sharp` 变体；已修复"overly plastic/high-specular appearance … with 7b model"（torch.compile 引起） | O22 https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler | 高 |
| SeedVR2 在 3090 上 | "with the 24 GB of VRAM I have, the enlargement is limited to around 2000x2000 pixels … split the image into tiles … The entire process took about 5 minutes on my 3090 for 16 tiles"（2025-07 的旧版本；新版已有 VAE tiling 和 BlockSwap） | A3 https://civitai.com/api/v1/articles/16888 | 低 |
| 低去噪 img2img 二次采样 | ZIT：0.2–0.4，默认 0.3；Qwen Reality Transform：1.5× 放大、去噪 0.4、beta | W5, C35 | 低到中 |
| 局部重绘 / FaceDetailer | Impact Pack 默认值：guide_size 512、max_size 1024、denoise 0.5、feather 5、noise_mask on、bbox_threshold 0.5、bbox_dilation 10、bbox_crop_factor 3.0、steps 20、cycle 1。社区针对 ZIT：只处理脸部区域，提示词加 "detailed skin texture"，去噪按 0.2–0.4 起步（比默认 0.5 低，更不容易改变身份） | O23 https://github.com/ltdrdata/ComfyUI-Impact-Pack/blob/Main/modules/impact/impact_pack.py ；W5 | 默认值高；社区值低 |
| Detail Daemon | Flux / Z-Image 用 detail_amount 0.1–1.0，start 0.1–0.5，end 0.5–0.9，要配 SamplerCustomAdvanced；ZIT 也可以用 DetailDeamonZ 滑杆 LoRA（负值增加细节） | O24, C13 | 高 / 中 |
| 噪声注入 / 胶片颗粒 | 作者们普遍说"颗粒在后期加"：A1 "adding a touch of film grain"；SeedVR2 的 input_noise_scale；Krea Realism Engine 换用 Wan2.1 VAE upscale2x（C1 原文 "a new workflow using ComfyUI-VAE-Utils node and wan 2.1 VAE"）。**没找到针对这几个模型给出具体颗粒强度数值的来源** | A1, O22, C1 | 低 |
| 采样器偏好 | res_2s 细节最多、res_2m 更写实也更快、euler 最快但没那么写实（C1，Krea）；res_2s/beta 质感更强，er_sde/simple 更干净（A2，Krea）；ClownShark + step overshot 写实最好（A1，RES4LYF 包，**不是原生节点**） | C1, A2, A1 | 低到中 |
| 种子多样性 | ZIT 官方标注 Diversity Low；社区用 SeedVarianceEnhancer | O7, BEYOND REALITY | 高 / 中 |

---

## 四、身份保持对照（第 3 项汇总）

| 模型 | 原生参考方式 | 参考图尺寸 | 提示词怎么指代参考图 | 强度怎么调 | 社区建议 | 来源 |
|---|---|---|---|---|---|---|
| Krea 2 | 原生只有风格参考（1–2 张）；身份要用 Identity Edit LoRA + **自定义节点 comfyui-krea2edit** | grounding_px 768；出图 ≤2MP | 两张图时：场景 = image 1，人物 = image 2 | ref_boost：单人 2，加人进场景时人物 2–3、场景 1，锁脸 1–2；LoRA 强度 1.0 | 写清楚露出多少身体、具体服装、光落在哪里 | O3, O25 |
| Z-Image | **没有**（Omni-Base / Edit 在 HF 卡片上仍标 "To be released"） | — | — | — | 用角色 LoRA；配风格 LoRA 时角色 LoRA 降到 0.3–0.6 | O7, W4, Famegrid |
| FLUX.2 klein | `ReferenceLatent` 串联，最多 4 张（BFL help） | 模板 `ImageScaleToTotalPixels` 1MP | 自然语言写 "image 1 / image 2"；BFS 换头写 "Picture 1 / Picture 2" | 原生没有强度旋钮；第三方 Identity Guidance 0.3–0.5；一致性 LoRA 0.5–0.7（不可商用） | 身份图放第一张（第二张只有约 70% 相似）；可以先生成几张不同角度的图再一起作参考；最稳的还是训 LoRA | O12, W2, W3, W4, C 2610018, C 2863285 |
| FLUX.3 Klein | `Set Reference Multi Latent`，最多 10 张 | 模板约 1MP；官方管线最多保留到约 16MP 原尺寸 | `<ref_image_0>`、`<ref_image_1>` | 编辑用蒸馏版 16 步、cfg 1 | 写"结果长什么样"，而不是"要改什么"；参考图同时加到正面和负面条件 | O14, O15 |
| Qwen-Image-Edit-2511 | `TextEncodeQwenImageEditPlus` 的 image1–3 | 视觉语言模型看 384² 面积，VAE 参考 latent 是 1024² 面积（源码固定） | "Picture 1 / Picture 2 / Picture 3" | 加 `FluxKontextMultiReferenceLatentMethod index_timestep_zero`；换头用 BFS V5 | 2511 的身份保持明显好于 2509；用 Lightning/FP8 时一定要接 reference method 节点 | O19, O20, O21, W1, C30 |
| Qwen-Image 2.1 | 见 RESEARCH.md（`<image1>` 写法） | 见 RESEARCH.md | 见 RESEARCH.md | Consistency LoRA（step 1500，不可商用） | — | C39 |

---

## 五、未证实 / 矛盾

1. **FLUX.2 klein 9B 能不能拍商业短剧（矛盾，需要法务判断）**：许可证 §2(d) 说"You may use Output for any purpose (including for commercial purposes)"，但 §1(c) 又规定"revenue-generating activity"不算非商业用途，模型只能用于非商业用途。为商业短剧生产画面，很可能属于"用模型做营收活动"。**稳妥做法：9B 要买 BFL 商业授权，或者改用 4B（Apache 2.0）**。（O11）
2. **Krea 2 Identity Edit 授权矛盾**：Civitai 的 allowCommercialUse 字段含 `Image`，但 HF 许可证写"free for personal / non-commercial use; commercial use needs a license from me"。**按更严的 HF 许可执行（需要单独授权）**。另外它依赖自定义节点，不符合"只用原生节点"的要求。（C 3409322 vs O25）
3. **FLUX.3 Klein Base 模板参数对不上**：我解析 `image_flux3_klein_t2i.json` 得到的 KSampler 是 `15 步 / cfg 1 / er_sde`，和蒸馏版模板一样；但 docs.comfy.org 正文写 "steps (50 by default) and cfg (3.5 by default)"，BFL 文档也写 50 / 3.5。可能是子图里有多个 KSampler，被我的解析脚本漏掉了。**以文档的 50 / 3.5 为准，未核实**。
4. **FLUX.3 Klein 在 3090 上的 upsampler 显存**：官方说"Do not use it without its prompt upsampler"，diffusers 版 upsampler 要多占约 28GB；ComfyUI 是 w4a8 量化的 9B 版本，能不能和主模型同时放进 24GB（还是要分时加载）**没有验证**。
5. **Krea 2 Turbo 的 CFG**：官方 README 写 `--cfg 0.0`，ComfyUI 模板写 cfg 1。两者实际都等于"不算负向"，**不算矛盾**。但社区 checkpoint（Stable Yogi）推荐 CFG 1.5，那就会启用负向并且慢一倍，效果好坏**未证实**。
6. **Lenovo UltraReal 在 Turbo 上的强度**：作者原话 Turbo 上用 1.2–2，Realistic Snapshot 也是 1.5–2.0，比一般 LoRA 的 0.6–0.8 高很多。两位作者独立给出同一结论（Krea Turbo 上的 LoRA 要加大强度），**中**；但 UltraReal KR2 作者给的是 0.6–0.8。不同 LoRA 训练强度不同，需要我们自己扫一遍。
7. **Danrisi 的 ZIT "4 guidance"**：与官方"Turbo guidance 0"矛盾。cfg 4 会启用负向且速度慢一倍，作者自己也说"i'm not sure that my workflow is correct"。**不采用**。
8. **Krea Raw 分辨率**：官方 README 说 Raw "trained to generate upto 1k"，Turbo 是 1–2K；但 Danrisi 认为 Raw + cfg4 画质最好。**竖屏直接出 2K 只能用 Turbo**。
9. **Z-Image 有没有官方编辑 / 参考模型**：HF 卡片上 Omni-Base / Edit 仍是 "To be released"，但卡片可能没及时更新。**未证实**。
10. **qwen-edit-skin 是 2509 训练的**：在 2511 上效果如何**未证实**（2511 的架构多了几层，BFS 作者提醒要更新 ComfyUI）。
11. **评分**：Civitai API 的 thumbsDownCount 返回 None，表里只有点赞数。下载量是"该版本"下载数，模型总下载量更高（例如 Lenovo UltraReal 整个模型 213,286）。
12. **很多高下载 LoRA 同时带大量 NSFW 概念**（Realism Engine、PhotoReal BetterNudes 等），表里没收，已收的也注明了。对 SFW 写实来说，Realism Engine 是否会让服装/身体出现偏差**未证实**。
13. **Reddit 只能通过 reddit.sentinel-team.org 快照读取**，链接可能失效；W2–W4 都是单个用户的说法。
14. **FaceDetailer 的去噪值**：没有找到针对 Krea 2、klein、FLUX.3 Klein、Qwen-Edit 的专门推荐值。0.2–0.4 是 ZIT 教程的说法，其它模型没有出处。
15. **Krea 2 的"湿/黏"皮肤**：只有 WinpicAsianRealism 作者提到，并推荐了 Loraholic 的 wetness-slider（链接在 civitai.red，**没有核实**）。
16. **FLUX.3 Klein 的写实 LoRA**：发布才两周，Civitai 上写实向只有 MoreReal（不可商用）、Asian Mix、NexBlend 三个，都没有给出完整采样参数。**等生态成熟或自己训**。

---

## 来源清单

**官方 / 源码**
- O1 https://huggingface.co/Comfy-Org/Krea-2
- O2 https://github.com/krea-ai/krea-2 （README）
- O3 https://docs.comfy.org/tutorials/image/krea/krea-2
- O4 https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_krea2_turbo_t2i.json
- O5 https://www.krea.ai/krea-2-licensing
- O6 https://github.com/krea-ai/krea-2/blob/main/docs/prompting.md
- O7 https://huggingface.co/Tongyi-MAI/Z-Image-Turbo
- O8 https://huggingface.co/Tongyi-MAI/Z-Image
- O9 https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_z_image_turbo.json
- O10 https://huggingface.co/black-forest-labs/FLUX.2-klein-4B
- O11 https://huggingface.co/black-forest-labs/FLUX.2-klein-9B/blob/main/LICENSE.md
- O12 https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_flux2_klein_text_to_image.json ；…/image_flux2_klein_image_edit_9b_distilled.json ；…/image_flux2_klein_image_edit_4b_distilled.json
- O13 https://docs.comfy.org/tutorials/flux/flux-2-klein
- O14 https://docs.comfy.org/tutorials/flux/flux-3-klein
- O15 https://docs.bfl.ml/flux_3/flux3_image_klein.md
- O16 https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/blob/main/LICENSE.md
- O17 https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_flux3_klein_distilled_t2i.json ；…/image_flux3_klein_t2i.json ；…/image_flux3_klein_distilled_image_edit.json
- O18 https://docs.bfl.ml/guides/prompting_unified_style.md ；https://docs.bfl.ml/guides/prompting_unified_basics.md
- O19 https://huggingface.co/Qwen/Qwen-Image-Edit-2511
- O20 https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511 ；https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_edit_2511.json
- O21 https://github.com/comfyanonymous/ComfyUI/blob/master/comfy_extras/nodes_qwen.py ；O21b https://github.com/comfyanonymous/ComfyUI/blob/master/comfy/samplers.py
- O22 https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler
- O23 https://github.com/ltdrdata/ComfyUI-Impact-Pack/blob/Main/modules/impact/impact_pack.py
- O24 https://github.com/Jonseed/ComfyUI-Detail-Daemon
- O25 https://huggingface.co/conradlocke/krea2-identity-edit

**Civitai（模型页：`https://civitai.com/models/<modelId>?modelVersionId=<vid>`；API：`https://civitai.com/api/v1/model-versions/<vid>`）**：C1–C44 和各表里的 Ck、"—"行，ID 都写在表里。

**社区文章 / 帖子**
- A1 https://civitai.com/api/v1/articles/32409 （lonecatone23，2026-07）
- A2 https://civitai.com/api/v1/articles/31794 （RLY，2026-06）
- A3 https://civitai.com/api/v1/articles/16888 （panorios，2025-07）
- A4 https://civitai.com/api/v1/articles/27526 （FloyoAI，2026-03）
- W1 https://myaiforce.com/qie-2511/
- W2 https://reddit.sentinel-team.org/posts/1somo2r/snapshots/2026-04-24T22%3A28%3A55.157497Z
- W3 https://reddit.sentinel-team.org/posts/1ryhz6s/snapshots/2026-03-20T16%3A21%3A25.533725Z
- W4 https://reddit.sentinel-team.org/posts/1rvxceo/snapshots/2026-03-20T16%3A21%3A25.533725Z
- W5 https://www.nextdiffusion.ai/tutorials/z-image-turbo-upscaler-and-detailer-workflow-in-comfyui ；https://www.divyarthinfotech.com/blog/z-image-turbo-upscaler-and-detailer-workflow-in-comfyui ；https://www.runcomfy.com/comfyui-workflows/z-image-real-skin-workflow-in-comfyui-natural-texture-portraits
- W6 https://huggingface.co/Comfy-Org/Boogu-Image/discussions/8
- BFL 帮助中心（klein 最多 4 张参考图）：https://help.bfl.ai/articles/8642316687-flux-2-klein-fast-generation-guide
