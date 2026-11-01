# IMGLAB-02：Flux 系列结构化控制工具调研（身份 / 手 / 光照 / 姿势）

- 日期：2026-11-02
- 范围：FLUX.1 dev / Kontext dev / Fill dev / Redux / Depth / Canny、FLUX.2（dev / klein 4B / klein 9B）、PuLID-Flux、InfiniteYou、ACE++、USO/UNO、IP-Adapter（XLabs / InstantX）、ControlNet Union Pro 2.0、XLabs ControlNet、Inpaint Crop&Stitch、nunchaku
- 背景：主模型 Qwen-Image 2.1 Turbo，RTX 3090 24GB，**商业短剧**
- 方法：逐条读官方 HF 模型卡、GitHub README、ComfyUI 官方 docs/blog、BFL 官网、Reddit（经 reddit.sentinel-team.org 快照镜像）；HF 文件名与大小来自 HF API `/api/models/<repo>/tree/main` 实测。每条结论都标了置信度（高/中/低）。
- 本次只调研，没有下载，也没有改其他文件。

---

## 0. 摘要（10 条）

1. **许可证是第一道闸门，结论：FLUX.1 [dev] 全家（dev / Fill / Kontext / Redux / Depth / Canny）以及所有基于 dev 的插件权重（Union Pro 2.0、InstantX IP-Adapter、PuLID-Flux、ACE++、InfiniteYou），都不能直接用在商业短剧的生产链路里。** 许可证 2(d) 写的是"产出物可以商用"，但 2(a) 授权范围是 "solely for your Non-Commercial Purposes"，1(c) 又明确把 "use (a) for revenue-generating activity" 排除在 Non-Commercial 之外。也就是说，拿模型跑商业生产本身就超出了授权，产出物条款救不了这一步。置信度：高。
2. BFL 官方自助商业授权页（bfl.ai/licensing）**现在只列 FLUX.2 [dev]、FLUX.2 [klein] 9B 和 FLUX 3 Image Klein**，没有 FLUX.1 dev / Kontext dev 的自助档，要授权只能找销售。价格页面上没写。置信度：中（页面抓取结果）。
3. **唯一可以直接商用的 Flux 本地权重是 FLUX.2 [klein] 4B（Apache 2.0）**。它在一个模型里同时做文生图和多参考编辑，fp8 文件 4.07GB，官方说 "~13GB VRAM… accessible on NVIDIA RTX 3090"，蒸馏版只要 4 步。FLUX.1 schnell 也是 Apache，但没有编辑和控制能力，对我们的四类问题帮助很小。置信度：高。
4. 身份一致性方面，社区口碑最好的是 PuLID-Flux（零样本）和 Kontext（编辑保脸）。InfiniteYou 只有官方自己的对比说它更好，社区评价两极。2026 年的帖子普遍认为 **Qwen Image Edit 保脸好于 Klein，Klein 的写实质感和速度更好**。都是个例，置信度：低到中。另外，几乎所有零样本身份方案都依赖 InsightFace antelopev2（非商用）。PuLID_Flux_ll 提供了 FaceNet 替代。
5. 手部方面，Flux 没有专门修手的模型。Fill dev 加 Crop&Stitch 是社区公认的局部重绘方案，但有人原话评价 "far from good"。ACE++ 官方自己承认手部有伪影。Klein 也被多次吐槽手。**没有证据表明 Flux 修手明显强于 Qwen-Image-Edit 局部重绘。**置信度：中。
6. 光照和贴图感：Kontext 可以用提示词重打光，libcom 有 Kontext 的 blending / harmonization LoRA（论文级，许可未查到）。社区做专门重打光更推荐 Qwen Edit 2509 relight LoRA 或 LBM relighting。置信度：中低。
7. 姿势和构图：Union Pro 2.0（canny / softedge / depth / pose / gray，pose 推荐 scale 0.9、end 0.65）是 Flux 上最完整的 ControlNet，但许可是 flux-1-dev-non-commercial。官方的 Depth / Canny dev **已被 BFL 标为 deprecated**。XLabs 的 ControlNet 没有 pose。置信度：高。
8. 3090 可行性：FLUX.1 系 12B 用 fp8 / GGUF Q8（约 12GB）或 nunchaku INT4（6.77GB，官方支持 sm_86 也就是 3090）都能跑。FLUX.2 dev 32B 只能用 GGUF Q4（19.3GB），偏慢。klein 4B 很轻松。置信度：高（文件大小）/ 中（速度）。
9. 串联：Inpaint Crop&Stitch 跟模型无关，"Qwen 出图 → 任意编辑或重绘模型修局部 → 原图回贴，未遮罩区域不过 VAE" 这套流程技术上成立。换成 Flux 只是把采样那一段换掉。置信度：高。
10. **总结论：不建议把 FLUX.1 dev 系引入生产，因为没有许可。可以把 FLUX.2 klein 4B（Apache）作为"局部编辑 / 换脸二次精修 / 重打光"的候选做一次对照实验，和 Qwen-Image-Edit 同题对比后再决定。如果要用 Kontext、PuLID 这类 dev 系工具，必须先买 BFL 商业授权**（这一步需要项目方拍板）。

---

## 1. 许可证（最重要，先读）

### 1.1 FLUX.1 [dev] Non-Commercial License v1.1.1（同时覆盖 dev / Fill / Kontext / Redux / Depth / Canny）

来源：https://huggingface.co/black-forest-labs/FLUX.1-dev/blob/main/LICENSE.md

- 2(a) 授权范围："grants you a non-exclusive, worldwide, non-transferable, limited license to access, use, create Derivatives of, and Distribute the FLUX.1 [dev] Models **solely for your Non-Commercial Purposes**." 置信度：高
- 1(c) 定义："For clarity, use (a) for revenue-generating activity, (b) in direct interactions with or that has impact on end users, or (c) to train, fine tune or distill other models for commercial use, in each case is not a Non-Commercial Purpose." 置信度：高
- 1(c)(ii)：允许 "use by commercial or for-profit entities for testing, evaluation, or non-commercial research and development in a non-production environment"。也就是说，**我们可以在非生产环境里测试和评估，但不能拿它出成片**。置信度：高
- 2(b)：commercial activity 必须 "request a license from Company"，"Please see www.bfl.ai if you would like a commercial license." 置信度：高
- 2(d) 产出物："We claim no ownership rights in and to the Outputs." "You may use Output for any purpose (including for commercial purposes), except as expressly prohibited herein." 以及 "You may not use the Output to train, fine-tune or distill a model that is competitive with the FLUX.1 [dev] Model or the FLUX.1 Kontext [dev] Model." 置信度：高
- Fill / Kontext / Redux 的模型卡都写着 "This model falls under the FLUX.1 [dev] Non-Commercial License"，并且 "Generated outputs can be used for personal, scientific, and commercial purposes"。来源：https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev 、https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev 、https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev 。置信度：高
- Kontext 模型卡还要求："Filters or manual review must be used with the model under the terms of the FLUX.1 [dev] Non-Commercial License." 置信度：高

**结论（明确）**：2(d) 只回答了"产出物归谁、能不能用"，没有扩大 2(a) 的授权范围。商业短剧属于 revenue-generating activity，在生产里运行 FLUX.1 dev 系模型本身就不在授权内。社区里流传的"dev 出的图可以商用"，只在**模型的使用本身是非商业的**前提下才成立，比如个人爱好者偶然把作品卖了。我们这种持续商业生产的场景**必须拿商业授权**。置信度：高（条款原文明确）。注意：这是条款阅读结论，不是法律意见。如果要买授权或有争议，请法务确认。

### 1.2 FLUX Non-Commercial License v2.1（FLUX.2 [dev]、FLUX.2 [klein] 9B）

来源：https://huggingface.co/black-forest-labs/FLUX.2-dev/blob/main/LICENSE.md 、https://huggingface.co/black-forest-labs/FLUX.2-klein-9B

- 结构和 v1.1.1 一样。2(a) "solely for your Non-Commercial Purposes"；1(c) 同样排除 "(a) for revenue-generating activity, (b) in direct interactions with or that has impact on end users"；2(d) "You may use Output for any purpose (including for commercial purposes), except as expressly prohibited herein."；"You may not use the Output to train, fine-tune, or distill a model that is competitive with a FLUX Model." 置信度：高
- klein 9B 模型卡："falls under the FLUX Non-Commercial License"。置信度：高
- 结论和 1.1 相同：**生产要用就得买授权**。

### 1.3 Apache 2.0：FLUX.2 [klein] 4B、FLUX.1 [schnell]

- klein 4B："Fully open under Apache 2.0." 来源：https://huggingface.co/black-forest-labs/FLUX.2-klein-4B 。置信度：高
- schnell 是 Apache 2.0。这是业界共识，本轮**没有逐字打开 schnell 的 LICENSE 文件**。置信度：中高。schnell 没有 Fill / Kontext / Control 变体，对本项目价值低。

### 1.4 BFL 自助商业授权（bfl.ai/licensing，2026-11 抓取）

来源：https://bfl.ai/licensing

- Builder：FLUX 3 Image Klein + FLUX.2 [klein]，"Fine-tuning and LoRA rights, 10K images/month, and commercial use within a single domain"
- Platform：FLUX 3 Image Klein、FLUX.2 [klein] Base 9B、FLUX.2 [dev]，"100K images/month"
- Professional（联系销售）："creative agencies and studios producing images on behalf of named clients"，最多 3 个 domain
- **页面上没有价格，也没有 FLUX.1 dev / Kontext dev 的自助档**。置信度：中（抓取摘要）。FLUX.1 系要授权只能找销售，或者确认是否已经停售。
- BFL API 出图自带商用权（第三方转述了 BFL help center，原页面我们抓的时候 404）。置信度：低。

### 1.5 插件和周边权重的许可（容易被忽略）

| 组件 | 许可 | 来源 | 置信度 |
|---|---|---|---|
| Shakker Union Pro 2.0 | flux-1-dev-non-commercial-license | HF 模型卡 | 高 |
| InstantX IP-Adapter | flux-1-dev-non-commercial-license | HF 模型卡 | 高 |
| PuLID（代码与权重） | Apache-2.0，但底座是 FLUX.1 dev，并依赖 EVA-CLIP 和 InsightFace | GitHub ToTheBeginning/PuLID | 中 |
| InsightFace antelopev2 | 非商用（ComfyUI_PuLID_Flux_ll README 原文："InsightFace (non-commercial/research)"） | GitHub lldacing | 高 |
| InfiniteYou 权重 | "Creative Commons Attribution-NonCommercial 4.0"，"for academic research purposes only" | GitHub bytedance/InfiniteYou | 高 |
| USO 权重 | HF 标 apache-2.0，但写着 "open-sourced for academic research"，并且套在 FLUX.1 dev 上 | HF bytedance-research/USO | 中 |
| ACE++ | 仓库没有写明许可；依赖 FLUX.1-Fill-dev | GitHub ali-vilab/ACE_plus | 中 |
| nunchaku（引擎） | Apache-2.0（量化后的权重仍然继承底模许可） | GitHub nunchaku-tech/nunchaku | 高 |

---

## 2. 身份 / 人物一致性

### 2.1 PuLID-Flux（v0.9.1）与 ComfyUI_PuLID_Flux_ll
- 来源：https://github.com/ToTheBeginning/PuLID 、https://github.com/lldacing/ComfyUI_PuLID_Flux_ll
- 原文："PuLID-FLUX can run on a 16GB graphic card"；v0.9.1 相比 v0.9.0 的 ID 相似度约高 5 个百分点；v0.9.0 的已知问题是 "ID fidelity is not high enough for some male inputs"。置信度：高
- 显存（_ll README）："8bit gguf (~12GB VRAM)"，fp8 约 12GB，"32bit/16bit (~22GB VRAM)"。3090 可以跑。置信度：高
- 权重：`guozinan/PuLID` → `pulid_flux_v0.9.1.safetensors`（1.14GB）。另外需要 `EVA02_CLIP_L_336_psz14_s6B.pt`（QuanSun/EVA-CLIP），以及 antelopev2 或 FaceNet 二选一。置信度：高（HF API）
- 可商用的人脸分析替代：README 原文 "FaceNet-based face analysis option, described as an alternative to InsightFace for commercial use"（`PulidFluxFaceNetLoader`）。不过底模 FLUX.1 dev 的许可问题依然存在。置信度：高
- 社区评价："PuLID the king for face transfer"、"PuliD has always been the best so far, with multiple reference images it's even better"（r/comfyui，https://lr.eu.psf.lt/r/comfyui/comments/1kkd9k3/ ）。置信度：低（个例）
- 已知缺点（InfiniteYou 官方对比，可能有立场）："PuLID-FLUX… suffers from poor text-image alignment"、"the face copy-paste issue of PuLID-FLUX is evident"。置信度：中

### 2.2 InfiniteYou（ByteDance，ICCV 2025）
- 来源：https://github.com/bytedance/InfiniteYou
- 底座 FLUX.1-dev。有 `aes_stage2`（"Better text-image alignment and aesthetics"）和 `sim_stage1`（"Higher identity similarity"）两个变体。置信度：高
- 显存原文：bf16 约 43GB；offload 约 30GB；"8-bit quantization… around 24GB"；"offloading plus 8-bit… around 16GB"。3090 需要 8bit 加 offload，速度会受影响。置信度：高
- 权重：`ByteDance/InfiniteYou` → `infu_flux_v1.0/aes_stage2/infusenet_aes_fp8e4m3fn.safetensors`（2.95GB）、`image_proj_model.bin`（0.34GB）。置信度：高
- 许可：权重是 **CC BY-NC 4.0**，不能商用。置信度：高
- 社区：有人说 "InfiniteYou fails to produce likeness in the character"，也有人说 "looked pulid level"（https://redlib.ssps.io/r/StableDiffusion/comments/1jgamm6/ ）。置信度：低

### 2.3 Kontext dev 保脸
- 来源：https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev ，原文 "Have character, style and object reference without any finetuning"、"refine an image through multiple successive edits with minimal visual drift"。置信度：高
- 社区（r/StableDiffusion《Which model is best for image editing maintaining identity consistency》，2026-05，https://reddit.sentinel-team.org/posts/1tdi287/snapshots/2026-05-15T21%3A30%3A42.175693Z ）："The best one in maintaining identity consistency until now is Flux Kontext"；"For identity consistency I'd still lean Flux Kontext too, even if the posing can be annoying"；也有人说 "FireRed Image Edit has the best identity consistency of all the image-editing models I've tried"。置信度：低到中
- 官方 Kontext 提示词指南（docs.bfl.ai）两次抓取都 404，**原文未查到**。第三方普遍建议写 "while preserving his exact facial features…"。置信度：低
- 权重：`flux1-kontext-dev.safetensors` 23.8GB；GGUF `QuantStack/FLUX.1-Kontext-dev-GGUF`（Q8_0 12.71GB / Q5_K_M 8.42GB / Q4_K_M 6.93GB）；nunchaku `svdq-int4_r32-flux.1-kontext-dev.safetensors` 6.77GB。置信度：高

### 2.4 IP-Adapter Flux（XLabs / InstantX）
- InstantX 原文："is not for fine-grained style transfer or character consistency"（https://huggingface.co/InstantX/FLUX.1-dev-IP-Adapter ），图像编码器 siglip-so400m，`ip-adapter.bin` 5.29GB。**明确不适合做身份**。置信度：高
- XLabs：README 原文 "We do not guarantee that you will get a good result right away"（beta），`XLabs-AI/flux-ip-adapter-v2/ip_adapter.safetensors` 1.06GB。置信度：高
- 结论：IP-Adapter 在 Flux 上只适合做风格或氛围参考，**不能用来做身份**。

### 2.5 InstantID
- InstantID 基本只在 SDXL 上有。本轮**没有查到官方的 FLUX 版 InstantID**。置信度：中

### 2.6 ACE++（ali-vilab）
- 来源：https://github.com/ali-vilab/ACE_plus 。原文 "ACE++ depends on FLUX.1-Fill-dev as its base model"。Portrait LoRA 用来保身份，Local Editing LoRA 用来做遮罩重绘。置信度：高
- 权重：`portrait/comfyui_portrait_lora64.safetensors` 0.61GB、`subject/...lora16` 0.15GB、`local_editing/...lora16` 0.15GB。置信度：高
- 官方承认的局限："The generated results may contain artifacts, especially when it comes to the generation of hands"；而且 Flux 方向已经 "must be suspended"，后续转向 Wan。**项目已停更**。置信度：高

### 2.7 USO / UNO（ByteDance）
- USO：主题、身份加风格的统一框架。原文 "The peak memory usage will be 16GB (Single reference) ~ 18GB (Multi references)"（fp8 加 offload）。ComfyUI 0.3.57 起原生支持。权重 `uso_flux_v1.0/dit_lora.safetensors` 0.48GB。来源：https://github.com/bytedance/USO 。置信度：高
- UNO：`bytedance-research/UNO/dit_lora.safetensors` 1.91GB。本轮没有细读 README，**社区身份分未查到**。置信度：低
- 两者都写着 academic research，底座是 FLUX.1 dev。

### 2.8 Redux
- 原文 "Outputs are heavily influenced by the input image"。它做的是图像变体或重新风格化，**不是专门的身份工具**。`flux1-redux-dev.safetensors` 0.13GB，加 sigclip 编码器约 0.86GB。来源：https://huggingface.co/black-forest-labs/FLUX.1-Redux-dev 。置信度：高

### 2.9 FLUX.2（dev / klein）多参考身份
- FLUX.2 dev 原文："Character, object, and style reference without additional training"，支持多参考编辑。置信度：高
- klein 社区意见（个例）："Qwen is way more consistent than Klein March anno 2026!!"，并建议 "Use Klein to faceswap with the 2048x2048 faceID made outta your reference image"（r/comfyui，https://reddit.sentinel-team.org/posts/1rj994t/snapshots/2026-03-04T15%3A30%3A02.949208Z ）。另有帖子总结 "Qwen edit= better face ID, better anatomy / Flux Klein = better image quality, better realism, faster"（https://reddit.sentinel-team.org/posts/1r7kx8s/snapshots/2026-02-18T18%3A41%3A23.566375Z ，这条是搜索摘要转述，没有逐字核对）。置信度：低

### 2.10 与 LoRA 对比
- 本轮**没有查到有量化身份分（如 ArcFace 相似度）的 PuLID / InfiniteYou 对 LoRA 公开对比**。社区的共识是：零样本方案方便，但脸型容易"贴脸"或漂移；角色 LoRA 更稳但需要训练。置信度：低（未查到一手数据）

---

## 3. ControlNet / 姿势构图

### 3.1 Shakker-Labs FLUX.1-dev-ControlNet-Union-Pro-2.0
- 来源：https://huggingface.co/Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0
- 支持模式：canny、soft edge、depth、pose、gray。**v2 去掉了 tile**。置信度：高
- 推荐参数：canny 0.7/0.8；softedge 0.7/0.8；depth 0.8/0.8；**pose（DWPose）0.9 / end 0.65**；gray 0.9/0.8。原文 "For better stability, we highly suggest to use detailed prompt." 置信度：高
- 权重 `diffusion_pytorch_model.safetensors` 4.28GB（2B 参数，6 个 double block）。许可：flux-1-dev-non-commercial-license。nunchaku 支持 Union Pro 2.0。置信度：高
- 模型卡没写 ComfyUI 用法，原生 ControlNet 加载器可以用（社区通行做法）。置信度：中

### 3.2 XLabs ControlNet
- 来源：https://github.com/XLabs-AI/x-flux-comfyui 。有 Canny、Depth、HED，**没有 pose**。低显存模式原文："launch Flux utilizing 12GB VRAM memory usage"。110 个 open issue，维护状态不明。置信度：高

### 3.3 官方 FLUX.1 Depth / Canny dev
- 来源：https://bfl.ai/announcements/24-11-21-tools 。**页面写明 FLUX.1 Depth 和 FLUX.1 Canny 已 deprecated**，开源权重只是 "for reference only"。有完整模型和 LoRA 两种形式：`flux1-depth-dev-lora.safetensors` 1.24GB、`flux1-canny-dev-lora.safetensors` 1.24GB。没有 pose。置信度：高
- 结论：要做姿势控制，Flux 上只能用 Union Pro 2.0，而且许可受限。

---

## 4. Fill：局部重绘（手 / 脸 / 换背景）与 outpaint

### 4.1 FLUX.1 Fill dev
- 来源：https://huggingface.co/black-forest-labs/FLUX.1-Fill-dev 、https://docs.comfy.org/tutorials/flux/flux-1-fill-dev
- 示例参数：`guidance_scale=30`、`num_inference_steps=50`、`max_sequence_length=512`。置信度：高
- 官方局限原文："There may be slight-color shifts in areas that are not filled in"、"Filling in complex textures may produce lines at the edges of the filled-area." 后一条正好对应我们关心的贴图感和接缝风险，**必须配合 Crop&Stitch 把原图回贴**。置信度：高
- ComfyUI 需要的文件：`flux1-fill-dev.safetensors`（23.8GB）、`t5xxl_fp16.safetensors`、`clip_l.safetensors`、`ae.safetensors`（0.34GB）。GGUF：`YarvixPA/FLUX.1-Fill-dev-GGUF`（Q8_0 12.73GB / Q5_K_S 8.29GB / Q4_K_S 6.81GB）。nunchaku：`mit-han-lab/nunchaku-flux.1-fill-dev/svdq-int4_r32-flux.1-fill-dev.safetensors` 6.77GB。置信度：高
- 增强版：`bytedance-research/OneReward` 里有 flux.1-fill-dev-OneReward transformer（约 23.8GB，分片），以及 object-removal LoRA（0.26GB）。社区说它 "bringing Fill up to Pro-level quality"（个例）。底座许可同样是 dev。置信度：低到中
- 社区（2026，搜索摘要，https://reddit.sentinel-team.org/posts/1s4iyr7/snapshots/2026-03-28T05%3A33%3A01.316841Z 等）：有人说 Flux Fill 是自己试过最强的 inpaint，"but far from good"；修手的建议是"只遮手，denoise 0.55–0.65"、用 YOLO 检测手再局部重绘，也有人推荐改用 Qwen Image Edit 修手。置信度：低

### 4.2 Inpaint Crop & Stitch（lquesada）
- 来源：https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch
- 原文："does not modify the unmasked part of the image, not even passing it through VAE encode and decode"。关键参数有 `context_from_mask_extend_factor`、`output_resize_to_target_size`（Flux 建议 1024×1024）、`mask_blend_pixels`、`output_padding`。denoise 小于 1 时建议用 InpaintModelConditioning。置信度：高
- **这套节点跟模型无关**。现在的 Qwen 链路可以直接套上，用 Qwen-Image-Edit 或 Qwen inpaint 做局部，不一定需要 Flux。置信度：高
- 注意：README 参数表写的 device 默认是 GPU，但 2026-05-25 的 changelog 说默认改成了 CPU，**两处冲突，需要看代码确认**。置信度：中

### 4.3 串联：Qwen 出图 → Flux Fill 修手
- 技术上可行：Qwen 出图 → YOLO 或 SAM 出手部遮罩 → Crop（扩 1.5–2 倍上下文，缩放到 1024）→ Fill dev（guidance 30）→ Stitch（blend 16–32px）。两个模型在同一个 ComfyUI 里切换，3090 上需要先卸载 Qwen（`--lowvram` 或手动 unload）。置信度：中（拼装推断，没有社区现成的 Qwen→Fill 帖子，**未查到**）
- 许可上仍然受 1.1 的限制。

---

## 5. Kontext 用作编辑 / 重打光 / 融合

- Kontext 官方能力是指令编辑和多轮编辑，漂移小（见 2.3）。置信度：高
- 重打光或融合：libcom 训练了 Kontext 的两个 LoRA，"image blending" 和 "image harmonization"（"adjusting its foreground illumination to be consistent with the background"），来源 https://libcom.readthedocs.io/en/latest/kontext.html 。**名字、许可和 HF 链接页面上都没写，未查到**。置信度：中
- 提示词做法（第三方教程 magichour.ai）：一次只做一种变换（先修图，再重打光，再换背景），并写明 "keep subject unchanged"，同时匹配光照方向和色温。置信度：低
- 替代方案：RunComfy 做专门重打光推荐 **Qwen Edit 2509 relight LoRA**；LBM relighting 也是专门的重打光模型。r/StableDiffusion（2026-05）建议用 Qwen Edit、HiDream 或 Klein，并把主体、前景、背景分层处理。来源：https://www.remoteopenclaw.com/skills/runcomfy-com/skills/relight 、https://reddit.sentinel-team.org/posts/1tbige1/snapshots/2026-05-15T21%3A47%3A52.126906Z 。置信度：低到中
- Kontext 换脸工作流（RunComfy）：先用 InsightFace 对齐贴脸，再用 Kontext 重生成融合，依赖一个 Kontext 专用 LoRA。置信度：低（是厂商页面）

---

## 6. FLUX.2 现状（截至 2026-11）

- FLUX.2 [dev]：32B，HF 仓库创建于 2025-11-22。`flux2-dev.safetensors` 64.45GB；GGUF `city96/FLUX.2-dev-gguf`（Q4_K_S 19.3GB / Q4_K_M 20.08GB / Q5_K_S 23.22GB）。文本编码器很大（Mistral 系，10 个分片约 48GB，Comfy 有 fp8 版，本轮没有核对文件名）。**3090 实际只能用 Q4 加 offload**，有第三方估计"几十秒每张"，没有查到受控基准。许可：Non-Commercial v2.1。置信度：文件大小高，速度低
- FLUX.2 [klein] 4B（Apache 2.0）：`black-forest-labs/FLUX.2-klein-4b-fp8/flux-2-klein-4b-fp8.safetensors` 4.07GB，bf16 版 7.75GB；文本编码器 `qwen_3_4b.safetensors`（Comfy-Org/flux2-klein-4B）；VAE `flux2-vae.safetensors`（Comfy-Org/flux2-dev）。ComfyUI 官方 blog 测 5090 上蒸馏版 4 步约 1.2s、8.4GB；base 版 50 步约 17s、9.2GB。官方模板有 `image_flux2_klein_image_edit_4b_distilled` 等。置信度：高
- FLUX.2 [klein] 9B（非商用）：fp8 版 9.43GB，模型卡写 "~29GB VRAM… RTX 4090 and above"；Comfy blog 测 9B 蒸馏版 19.6GB。3090 勉强能跑。置信度：中
- klein 的缺点（社区个例）："sometimes even 9B gives some weird hands"、"Klein still mangles hands and fingers"；有人认为 9B 光照好于 4B，4B 有轻微的 "digital sheen"。置信度：低
- FLUX 3：2026-07-23 发布（视频优先），open-weight Dev 版"later in 2026"，**截至 9 月底没有确认已发布**（二手来源）。置信度：低

---

## 7. 3090 显存与速度（汇总）

| 模型 | 推荐格式（3090） | 主模型文件大小 | 速度 | 置信度 |
|---|---|---|---|---|
| FLUX.1 dev / Fill / Kontext（12B） | nunchaku INT4（支持 sm_86）或 GGUF Q8 / fp8 | 6.77GB（INT4）/ 12.7GB（Q8）/ 23.8GB（bf16） | 4090 上 INT4 "3.0× faster than the NF4 W4A16 baseline"；3090 具体秒数未查到 | 文件大小高，速度低 |
| PuLID-Flux | fp8 或 GGUF Q8 加 PuLID | 底模加 1.14GB | 约 12GB 显存（README） | 高 |
| InfiniteYou | 8bit 加 offload | 2.95GB（fp8 InfuseNet）加底模 | 约 16GB，偏慢 | 高 |
| Union Pro 2.0 | 加在 fp8 底模上 | 4.28GB | 未查到 | 中 |
| FLUX.2 dev（32B） | GGUF Q4_K_S 加 offload | 19.3GB 加大型文本编码器 | 推测每张几十秒，未查到实测 | 低 |
| FLUX.2 klein 4B | fp8 | 4.07GB | 5090 上 4 步 1.2s（3090 推测约 3–5s，未实测） | 中 |

nunchaku 原文："only runnable on NVIDIA GPUs with architectures sm_86 (Ampere: RTX 3090, A6000), sm_89 (Ada: RTX 4090), and sm_80 (A100)"（https://huggingface.co/mit-han-lab/svdq-int4-flux.1-dev ）；FP4 只支持 50 系。nunchaku 同时也支持 Qwen-Image 和 Qwen-Image-Edit。置信度：高

---

## 8. 方案总表

| 方案 | 解决的问题 | 节点 / 插件 | 权重与大小（HF） | 3090 可行性 / 速度 | 许可证 | 置信度 |
|---|---|---|---|---|---|---|
| PuLID-Flux v0.9.1 | 身份 | ComfyUI_PuLID_Flux_ll | guozinan/PuLID `pulid_flux_v0.9.1.safetensors` 1.14GB，加 EVA02-CLIP，加 antelopev2 或 FaceNet | 可行，约 12GB（fp8 / Q8） | 底模 dev 非商用；antelopev2 非商用 | 高 |
| InfiniteYou | 身份 | ComfyUI_InfiniteYou（官方） | ByteDance/InfiniteYou `infusenet_aes_fp8e4m3fn.safetensors` 2.95GB | 勉强，8bit 加 offload 约 16GB | **CC BY-NC 4.0** 加 dev | 高 |
| Kontext dev | 身份保持编辑 / 重打光 / 融合 | 原生 | `flux1-kontext-dev.safetensors` 23.8GB；Q8 12.71GB；INT4 6.77GB | 可行 | dev 非商用 | 高 |
| ACE++ Portrait / Local | 身份 / 局部重绘 | 官方 workflow 加 Fill dev | ali-vilab/ACE_Plus portrait 0.61GB 等 | 可行 | 依赖 Fill dev 非商用；已停更 | 高 |
| USO / UNO | 主体 / 身份加风格 | 原生（≥0.3.57） | USO dit_lora 0.48GB；UNO 1.91GB | 可行，16–18GB | 学术用途，底座 dev | 中 |
| IP-Adapter（InstantX / XLabs） | 风格参考（**不能做身份**） | ComfyUI-IPAdapter-Flux / x-flux-comfyui | 5.29GB / 1.06GB | 可行 | dev 非商用 | 高 |
| Redux | 变体 / 风格 | 原生 | 0.13GB 加 sigclip 0.86GB | 可行 | dev 非商用 | 高 |
| Union Pro 2.0 | 姿势 / 构图（含 pose） | 原生 ControlNet | 4.28GB | 可行 | dev 非商用 | 高 |
| XLabs ControlNet | 构图（canny / depth / hed，无 pose） | x-flux-comfyui | flux-controlnet-collections | 可行，12GB 模式 | dev 非商用 | 高 |
| FLUX.1 Depth / Canny dev | 构图 | 原生 | LoRA 各 1.24GB | 可行 | dev 非商用；**已 deprecated** | 高 |
| Fill dev 加 Crop&Stitch | 手 / 脸 / 换背景 / outpaint | 原生加 Inpaint-CropAndStitch | 23.8GB；Q8 12.73GB；INT4 6.77GB | 可行 | dev 非商用 | 高 |
| OneReward Fill | 同上，质量更高 | 原生 | 约 23.8GB | 可行（需自己量化） | dev 非商用 | 低到中 |
| FLUX.2 dev | 多参考身份 / 编辑 | 原生 | Q4_K_S 19.3GB | 慢，勉强 | 非商用 v2.1（可买 Platform 档） | 中 |
| **FLUX.2 klein 4B** | 编辑 / 多参考 / 换脸精修 / 重打光（试） | 原生模板 | `flux-2-klein-4b-fp8.safetensors` 4.07GB 加 qwen_3_4b 加 flux2-vae | **很轻松**，4 步 | **Apache 2.0，可商用** | 高（许可）/ 低（效果） |
| FLUX.2 klein 9B | 同上，质量更高 | 原生模板 | fp8 9.43GB 加 qwen_3_8b_fp8mixed | 勉强，约 20GB | 非商用（可买 Platform 档） | 中 |

---

## 9. 是否值得引入 Flux：结论

1. **FLUX.1 dev 全家及其插件：不引入生产。** 理由是授权范围排除了 revenue-generating 用途，而 BFL 自助授权页已经不卖 FLUX.1 dev 系。按 1(c)(ii)，只能在"非生产环境测试评估"。置信度：高
2. **作为替代 Qwen-Image 的主模型：不值得。** 我们的四类问题里，Flux 系没有一项有明确优于 Qwen-Image / Qwen-Image-Edit 的一手证据。社区对保脸的普遍看法是 Qwen Edit ≥ Klein，手部方面两边都被吐槽。置信度：中
3. **值得做一次对照实验的只有 FLUX.2 klein 4B（Apache）**，用途限定在：
   - (a) 局部精修：Crop&Stitch 抠出手或脸后，用 klein 4B 编辑重绘，和 Qwen-Image-Edit 同遮罩同题对比；
   - (b) 换脸精修："Qwen 摆姿势 → Klein 用高清身份脸做 faceswap"，这是社区个例做法，要和 L-086 身份脸配合测试；
   - (c) 重打光和去贴图感：给出参考光照提示，和 Qwen Edit relight LoRA 对比。
   成本低（4GB 权重，3090 上几秒一张），许可干净。置信度：中
4. **如果实验证明 Kontext、PuLID 或 klein 9B / FLUX.2 dev 有明显优势**：要么买 BFL Platform 授权（覆盖 FLUX.2 dev 和 klein 9B，100K 张/月），要么联系销售问 FLUX.1 Kontext。这属于花钱事项，需要项目方拍板。
5. **不管用不用 Flux，都建议马上做**：把 Inpaint Crop&Stitch 接进现有的 Qwen 链路做局部修手修脸，因为它跟模型无关，而且未遮罩区域不过 VAE，能直接降低接缝和贴图感。
6. 人脸检测组件要选可商用的（FaceNet 或其他可商用检测器），**避开 InsightFace antelopev2**（非商用）。这一条同样适用于 Qwen 链路里所有用到 InsightFace 的地方，需要另外排查。

---

## 10. 需下载清单（仅列出，本次未下载）

**A. 推荐（许可干净，用于对照实验）**
1. `black-forest-labs/FLUX.2-klein-4b-fp8` → `flux-2-klein-4b-fp8.safetensors`（4.07GB）→ `models/diffusion_models/`
2. `Comfy-Org/flux2-klein-4B` → `split_files/text_encoders/qwen_3_4b.safetensors`（大小未查到，估计约 8GB）→ `models/text_encoders/`
3. `Comfy-Org/flux2-dev` → `split_files/vae/flux2-vae.safetensors`（约 0.34GB，未核对）→ `models/vae/`
4. 自定义节点 `lquesada/ComfyUI-Inpaint-CropAndStitch`（跟模型无关）
5. （可选，Base 版用于更高质量编辑）`black-forest-labs/FLUX.2-klein-base-4b-fp8` → `flux-2-klein-base-4b-fp8.safetensors`

**B. 只有在买到商业授权后才下（或仅用于非生产评估）**
6. `mit-han-lab/nunchaku-flux.1-kontext-dev` → `svdq-int4_r32-flux.1-kontext-dev.safetensors`（6.77GB）
7. `mit-han-lab/nunchaku-flux.1-fill-dev` → `svdq-int4_r32-flux.1-fill-dev.safetensors`（6.77GB），或 `YarvixPA/FLUX.1-Fill-dev-GGUF` → `flux1-fill-dev-Q8_0.gguf`（12.73GB）
8. `guozinan/PuLID` → `pulid_flux_v0.9.1.safetensors`（1.14GB），加 `QuanSun/EVA-CLIP` → `EVA02_CLIP_L_336_psz14_s6B.pt`，节点 `lldacing/ComfyUI_PuLID_Flux_ll`（用 FaceNet 加载器）
9. `Shakker-Labs/FLUX.1-dev-ControlNet-Union-Pro-2.0` → `diffusion_pytorch_model.safetensors`（4.28GB）
10. FLUX.1 共用组件：`comfyanonymous/flux_text_encoders` → `clip_l.safetensors`、`t5xxl_fp8_e4m3fn.safetensors`；`ae.safetensors`（0.34GB）
11. `black-forest-labs/FLUX.2-klein-9b-fp8` → `flux-2-klein-9b-fp8.safetensors`（9.43GB）加 `qwen_3_8b_fp8mixed.safetensors`

**C. 不建议下载**
- InfiniteYou（CC BY-NC）、InstantX / XLabs IP-Adapter（不能做身份）、FLUX.1 Depth / Canny dev（已 deprecated）、ACE++（已停更、手部有伪影）、FLUX.2 dev GGUF（3090 太慢，许可也受限）

---

## 附：未查到 / 待核实
- BFL 官方 Kontext 提示词指南原文（两个 URL 都 404）
- BFL 各授权档价格；FLUX.1 dev / Kontext 是否还能买到商业授权
- 3090 上 Kontext、Fill、klein 4B 的实测秒数
- PuLID、InfiniteYou 和角色 LoRA 的量化身份分对比
- libcom Kontext harmonization LoRA 的权重地址与许可
- Qwen → Flux Fill 串联的现成社区帖
- FLUX.1 schnell LICENSE 原文（本轮没有逐字打开）
