# MiniMax H3 最新模型调研：FastH3 / Trim / Flex（2026-10-31）

> 项目方原话：“minimax fasth3 trim 那些最新模型，你看了吗？结论是什么”
> 范围：只补充 `h3_deep/*`、`h3_prompt_and_fl2v.md`（FastH3 一行）、`research_adoption.md`、`research_link_coverage.md`、`quality_deep/*` **没有覆盖**的内容。已经写过的结论（v1.1 768p @1.0 + 6/3、w4a8 不吃 LoRA、ToneCompensate/调色、DMAD 4step 不挂、Realism People、Ref2V LoRA 用在 FL2VA 上）这里不再重复。
> 置信度三档：**官方**（模型卡、官方文档、作者 README）/ **实测**（第三方贴了数据）/ **推测**（我的推断，没人测过）。日期是页面日期；只有相对时间的，按今天 10-31 倒推，标“约”。
> 我们的链路：FL2VA，首尾帧都锁，来自 Image 2.1；`minimax_h3_fl2va_pruned_int8_convrot` + `minimax_h3_fl2v_turbo_8step_v1.1_768p` @1.0，shift 6/3，euler 8 步，768×1344，24 fps，RTX 3090 24 GB（`--reserve-vram 1` 下约 192 帧就到 OOM 边缘）。

---

## 0. 一句话结论

- **“Trim” 确实存在**，就是 **FastVideo FastH3 Trim**（10-03 至 10-06 发布）。它把 50 个 block 剪到 42 个，做 8 步 DMD2 蒸馏，是一个**完整的替换底模，不是 LoRA**。ComfyUI 只给了**文生视频（T2V）模板**，模型卡没有提首尾帧。官方原话是“costs some quality”，速度只比 V2 快 10–20%。**对我们的 FL2VA 链没用，不建议试。**
- **FastH3 8-Step V2 / Omni** 这两个也都**接不进我们的链**。V2 的模型卡写“FL2VA … not distilled”，Comfy 文档却说支持首尾帧，两边说法冲突。Omni 只做 Ref2VA。
- 这两周**真正值得 A/B 的新东西只有一个**：**Pika H3 Flex 的 FL2VA adapter**（10-29 发布）。它是挂在**我们现有的 `fl2va_pruned_int8_convrot` 底模**上的一个 1.96 GB LoRA，6 步，官方声称画质分高于 H3 原版。它用来替换 lightx2v Turbo，不能和 Turbo 叠加。问题是太新：社区还没有 FL2VA 实测，竖屏 768×1344 也没人测过。
- MiniMax 官方在 10-20 以后**没有新权重**：没有 v1.2，没有新节点，也没有 lite 版。lightx2v 最新一批是约 10-21 的 FL2V 8step **v1.1**，**就是我们正在用的这版**，没有更新的。

---

## 1. FastVideo FastH3 家族

| 型号 | 日期 | 蒸馏了哪些模式 | 注意力 / 采样 | ComfyUI | 24 GB 显存 | 能不能接我们的 FL2VA |
|---|---|---|---|---|---|---|
| FastH3-8-Step-V2 | 约 9 月；Comfy 模板 09-15 | 模型卡：只做 T2VA，“FL2VA and Ref2VA were not distilled”；Comfy 文档：T2V + 首尾帧（**冲突**） | VSA 80% 稀疏，keep 10；res_multistep/simple 8 步；shift 10/3 | 原生，`video_fastvideo_fasth3_i2v.json` | 4090 上 FP8 可以跑（blog） | **有条件**：要整个换底模，首尾帧没训练过 |
| **FastH3-Trim-8-Step**（就是“trim”） | 10-03 至 10-06 | 只有 T2V 模板 | 42 个 block，rank-16 AdaLN，VSA 保留 20% tile，res_multistep 8 步，shift 10/3 | 原生 T2V 模板（≥0.36.0） | int8_convrot 18.9 GB；FP8 卡写“for RTX 4090, RTX 3090” | **否** |
| FastH3-Omni-8-Step-V1 / FastH3-Omni-Comfy（OmniRef） | 10-20 | 只做 Ref2VA（图、视频、音频参考） | 8 步，shift 12/3 | 原生 `video_fasth3_ominiref_r2v` | int8 22.2 GB；4090 只走 FP8 + 逐层 offload | **否**（Ref2VA 不能把首帧锁死，已写在 link_coverage） |
| 社区：rzgar Trim-Motion-Enhanced / TaoMate FL2VA-3Step-FastH3Trim | 未注明 | 文件名带 FL2VA，卡片没解释 | er_sde/beta 8 步 | 有 LoRA 文件 | 未说明 | **否**（NSFW 方向，没有测量数据） |
| 社区：barelymining `fasth3_vsa_v5` + gate | 未注明 | 设计给 **fl2va_pruned_int8_convrot** 用 | 4 步，要自定义节点注入 gate | 要装自定义节点 | 3090 Ti 实测 | **有条件**，但它属于 4 步加速，不提升画质 |

### 证据

**FastH3 V2**
- “FL2VA and Ref2VA were not distilled.” <https://huggingface.co/FastVideo/FastVideo-FastH3-8-Step-V2>（官方，约 9 月）
- “Difficult motion, fine detail, and some audio may remain below the base” 同上（官方）
- “Its video scheduler shift is 10, not the base model's 12” 同上（官方）
- 与模型卡冲突：“supports text-to-video and first/last-frame image-to-video only.” <https://docs.comfy.org/tutorials/video/minimax/minimax-h3-fastvideo.md>（官方，Comfy 文档，没写日期）
- “covers text-to-video-and-audio and first/last-frame conditioning only” <https://comfyui-wiki.com/en/news/2026-09-16-fasth3-comfyui-templates>（官方转述，09-15）
- “sol-attn and sla sparse methods are not compatible” 同上
- 我的判断（**推测**）：ComfyUI 的 `MiniMaxH3ImageToVideo` 节点可以把首尾帧接进去，但学生模型在蒸馏时没见过首尾帧条件。所以“能跑”，不等于“尾帧能落准”。没找到任何人对 V2 首尾帧贴合度的实测。

**FastH3 Trim**
- “experimental pruned FastH3 model”；“42 transformer blocks instead of 50”；“rank-16 timestep conditioning” <https://huggingface.co/FastVideo/FastVideo-FastH3-Trim-Comfy>（官方，约 10-19 更新）
- 文件：`fastvideo_fasth3_trim_8step_int8_convrot.safetensors` 18.9 GB；fp8 19.7 GB；nvfp4 11.9 GB；bf16 37.5 GB。出处同上（官方）
- 模型卡只写“eight-step text-to-video with synchronized audio”，没有首尾帧。<https://huggingface.co/FastVideo/FastVideo-FastH3-Trim-8-Step>（官方）
- “Removing blocks … costs some quality; use FastH3 V2 when quality matters most.” 同上（官方）
- 有用户问“is it hybrid model?”（是 FL2VA 还是 REF2VA），**没人回答**。<https://huggingface.co/FastVideo/FastVideo-FastH3-Trim-Comfy/discussions/2>（社区，约 10-14）
- blog：“Busy scenes can show less detail than V2” <https://haoailab.com/blogs/fasth3-rtx/>（官方，10-06）
- blog 速度：4090 24 GB，768p 5 s 片段，V2 154.6 s，Trim 132.8 s，只快约 14%。同上（官方实测）。**blog 没测 3090**。
- FP8 卡：“for the RTX 4090, RTX 3090 and smaller GPUs”，但正文只写 4090 加逐层 offload。<https://huggingface.co/FastVideo/FastVideo-FastH3-Trim-8-Step-FP8>（官方）。3090 没有 FP8 张量核，**推测**要走 int8_convrot。

**FastH3 Omni**
- “final BF16 release checkpoint of FastH3 Omni”；“At least one image or video is required.” <https://huggingface.co/FastVideo/FastVideo-FastH3-Omni-8-Step-V1>（官方，10-20）
- Comfy 版：“video shift 12.0, audio shift 3.0”，int8 22.2 GB。<https://huggingface.co/FastVideo/FastH3-OmniRef-Comfy>、<https://comfyui-wiki.com/en/news/2026-10-20-fasth3-omni>（官方）
- “matched qualitative comparisons, not evidence of output parity with base H3” 同上（官方）

**VSA 在 3090 上**
- Comfy 的 `BlockSparseAttention` 节点：vsa 模式“requires FastH3 model weights” <https://docs.comfy.org/zh/built-in-nodes/BlockSparseAttention.md>（官方）
- 没找到任何 VSA 在 sm_86 上的实测。sol-attn 在 3090 Ti 上验证过，但 V2 明确不兼容 sol-attn。（推测：VSA 在 3090 上要么跑不了，要么退回慢路径）

**barelymining VSA LoRA**
- “you can't load these with a normal LoRA loader alone”；`fasth3_vsa_v5.safetensors` 2.05 GB + `fasth3_vsa_gate.safetensors` 3.6 GB；“Tested on one machine (RTX 3090 Ti)”；5 s、0.8 MP 片段，“from ~8 minutes (base, 20 steps)”降到草稿 <1 分钟、最佳约 2.5 分钟。<https://huggingface.co/barelymining/ComfyUI-MiniMax-H3-FastVideo>（作者自测，日期未注明）
- 作者自己也建议：图省事就用 lightx2v 的 8 步 Turbo。

---

## 2. “trim / 剪枝 / lite” 全量排查

| 搜索项 | 结果 |
|---|---|
| HF / 网页：“H3 trim”“minimax h3 trimmed” | **只有 FastVideo FastH3 Trim 这一个**（见 §1）。MiniMax 官方和 Comfy-Org 都没有叫 trim 的东西 |
| Comfy-Org/MiniMax-H3 `diffusion_models/` | 12 个文件。最新的是约 10-01 的 `minimax_h3_fl2va_pruned_w6a8`（16 GB）和 ref2va 版。**近两周没有新文件**，也没有 fasth3、trim、flex、nvfp4。<https://huggingface.co/Comfy-Org/MiniMax-H3/tree/main/diffusion_models>（官方） |
| “pruned” 的含义 | Comfy-Org 的 pruned 只是把 AdaLN 投影压到可达秩，**block 数没减**。Trim 才是真正少了 8 个 block |
| 社区更小的版本 | Abiray / unsloth 的 pruned GGUF（8.9–21.6 GB）；multimodalart/MiniMax-H3-Pruned。都是量化格式，不是新模型 |
| “lite” | 没有找到 |

**结论**：我们链上能用的“最小可用底模”还是 Comfy-Org 的 `fl2va_pruned_int8_convrot`（21 GB）。w6a8（16 GB）以前已经评估过，结论是 LoRA 兼容性没验证，见 `research_adoption.md`，这里不重复。

---

## 3. 10-20 以后的官方更新

| 来源 | 内容 | 证据 | 置信度 |
|---|---|---|---|
| MiniMaxAI/MiniMax-H3 HF | 没有带日期的更新，没有 v1.1 / v1.2。还在说“sparse-attention implementation will be released in a future update” | <https://huggingface.co/MiniMaxAI/MiniMax-H3> | 官方 |
| MiniMax-AI GitHub | 10-28 合并了两个 PR（#83、#37 依赖修复），没有 tag | <https://github.com/MiniMax-AI/MiniMax-H3/commits/main> | 官方 |
| lightx2v Turbo | 约 10-21 发布“updated FL2V and REF2V”：FL2V 8step **v1.1_768p**（我们在用）、4step v1.3、REF2V 8step v1.1、REF2V 4step v1.0。**没有 v1.4，也没有 1080p** | <https://huggingface.co/lightx2v/Minimax-h3-Turbo/tree/main>，#57 | 官方 |
| lightx2v #57 回帖 | 4step v1.3 叠其他 LoRA 会坏，作者回复“We've noted this issue”（约 10-24）。**8step v1.1 没有任何负面回帖** | <https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/57> | 社区 |
| Comfy-Org | 约 10-30 加了 Pika Flex 的 LoRA 和 3 个模板（#70/#71）。AddGuide / multiframe **没有更新** | <https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/71> | 官方 |
| DMAD | 10-29 发布 `dmad_minimax_h3_8step_full_critic`（Comfy 版 2.0 GB）。采样用 lcm，shift 12/2，“ODE samplers such as euler are not their operating point”。**训练用的是 T2VA 下载路径** | <https://huggingface.co/ZhengmingYu/DMAD> | 官方（作者） |

---

## 4. Pika H3 Flex：这两周唯一的强候选

- 是什么：“not a new architecture”；“arrives as two LoRA adapters in native MiniMax H3 module layout”。蒸馏到 6 步，又做了 reward learning。<https://comfyui-wiki.com/en/news/2026-10-29-pika-h3-flex>（官方转述，10-29）
- **FL2VA adapter 覆盖** T2V、首帧、尾帧、首+尾帧。同上（官方）
- Comfy 模板的底模就是 **`minimax_h3_fl2va_pruned_int8_convrot.safetensors`**，LoRA 是 `pika_h3_flex_fl2va_v1_bf16.safetensors`。<https://docs.comfy.org/tutorials/video/pika/pika-h3-flex>（官方）
  - HF 上的原始文件名是 `comfy/loras/pika_h3_flex_fl2va_comfy_bf16.safetensors`，1.96 GB。<https://huggingface.co/Pika-Labs/Pika-H3-Flex/tree/main/comfy/loras>（官方）
  - Comfy 模板 PR 里记录过 LoRA 下载 404（Comfy-Org/workflow_templates #1384）。**下载前要核对文件名。**
- 采样：lcm + `ManualSigmas`（1000/750/500/250/100/40/0），CFG 1，BasicGuider，强度 1.0，shift 12/3。“Picking six steps in a generic sampler does not reproduce that contract.” 出处同 wiki（官方）
- 禁忌：“do not stack a turbo or Lightning LoRA on top”；“lowering the sigma list below seven values breaks the schedule”。出处同 Comfy 文档（官方）
- 自报分数（768p）：画面技术分 12.3，H3 原版 11.7；美学分 5.41，原版 5.28。音画对齐 0.212，**输给** Fal H3 Max 的 0.216。出处同 wiki（官方自评）
- 输出 480p / 768p，**11 种宽高比，含 9:16**；5–15 s。<https://huggingface.co/Pika-Labs/Pika-H3-Flex>（官方）
- “no end-to-end ComfyUI render was verified as part of the upload”（wiki 转述 Pika 原话）。“Exact reproduction with the released package is not guaranteed”（HF 卡）。（官方自认）
- 社区：WAS 报告 4 步时细节“popping”，建议用 6 步；Kijai 说一个 T2V 例子 DMAD 失败、Flex 成功。出处同 wiki（社区，样本很小）
- 3090 数据点：media-lab PR 用 1344×768、5 s 测 T2V 351 s、I2V 345 s，“~10 GB peak VRAM”。<https://github.com/Xainner/media-lab/pull/12>（实测，10-29）。这是 Pika 自家的 diffusers 包，用了 offload，**不是 ComfyUI 的数据**，不能直接和我们的出片时间比。
- Pika 官方说，物理、多场景叙事、光照材质、动作密集的参考任务，还是其他系统更好。（官方自认）
- **身份、皮肤、色彩**：模型卡**一句都没提**，没有任何证据。

---

## 5. 近两周社区 LoRA / 工作流（身份、质感、色彩、时长）

| 方向 | 新东西 | 结论 |
|---|---|---|
| 身份一致性 | 没有新的 FL2VA 身份 LoRA。Ref2V LoRA 用在 FL2VA 上（#40/#91）、UntMods FaceSwap（只给 ref2va）都是旧的，已覆盖 | 没有新增 |
| 皮肤 / 质感 | fal Realism People 是 08-10 的旧件，已覆盖。没有找到 10 月的新质感 LoRA | 没有新增 |
| 色彩 | Comfy #67（约 10-12，reasy0000）：FL2VA 在 1024×1280 下 12 个种子里 4 个片中“iris-out”变黑，0.5 MP 正常，“A failing seed fails with every setting I tried”。这已经引用进 `h3_deep/00_summary.md`。新信息只有一条：**euler 比 res_multistep 的轻度变暗少一半**，我们本来就用 euler | 不改动 |
| 时长 >8 s / 24 GB | acecloud 博客：3090 跑 832×480、362 帧，峰值约 19.8 GB，关掉 pinned memory 才没有主机 OOM。ComfyUI #15453：16 GB 卡超过约 209 帧时死在 VAE decode。都**没有**给出 768×1344 超过 192 帧的方案 | 没有能直接用的；见下面 A/B 4 |

链接：<https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/67>、<https://acecloud.ai/blog/minimax-h3-gpu-requirements/>、<https://github.com/Comfy-Org/ComfyUI/issues/15453>（社区，置信度低到中）

Reddit 和 X：我能搜到的范围里，**没有** FastH3 Trim 或 H3 Flex 的 r/StableDiffusion、r/comfyui 讨论帖（搜索没有命中）。中文社区也没有找到。

---

## 6. 结论：逐个候选

| 候选 | 能不能接 FL2VA 链 | 预期收益 | 风险 | 要下载的文件 | A/B（同镜头、同种子） |
|---|---|---|---|---|---|
| **Pika H3 Flex FL2VA adapter** | **能**，同一个底模 | 速度：6 步对 8 步，**推测**快约 20%；画质：官方自评分略高；身份、色彩：没有证据 | 10-29 才发布，0 个 FL2VA 实测；竖屏 9:16 没人验证；shift 12/3 + lcm 和我们锁定的 6/3 + euler 完全不同；不能叠 Turbo；下载出过 404 | `pika_h3_flex_fl2va_*_bf16.safetensors` 1.96 GB | **A/B-1**：ep01 S1（有尾帧锚点），种子 1101683047，192 帧，768×1344。A = 现链（v1.1 @1.0、6/3、euler 8 步）；B = Flex（官方 FL2VA 模板，lcm、ManualSigmas 7 值、12/3、强度 1.0）。比较：尾帧贴合（和尾帧图的 SSIM/dE）、脸部相似度、肤质、色偏、耗时。**项目方挑** |
| FastH3 8-Step V2（Comfy i2v 模板） | **有条件**，要整个换底模；首尾帧没蒸馏过（模型卡和 Comfy 文档冲突） | 速度：推测和现链差不多；画质：官方说细节不如原版 | VSA 在 3090 上没验证；尾帧可能落不准；不能用我们的 LoRA | `fastvideo_fasth3_8step_v2_pruned_int8_convrot` 约 21 GB（推测） | 优先级低。真要试：A/B-2 = 同一镜头，V2 i2v 模板（res_multistep 8 步、10/3、vsa keep 10）对比现链，**只看尾帧贴合** |
| **FastH3 Trim**（项目方问的 “trim”） | **否**：只有 T2V，没有首尾帧 | 只有速度（比 V2 快约 14%） | 官方自认掉画质 | int8_convrot 18.9 GB | **不建议做 A/B**。结论：不接 |
| FastH3 Omni | 否：只做 Ref2VA，不能锁首帧 | — | — | int8 22.2 GB | 不做（link_coverage 里已经关闭） |
| barelymining VSA LoRA | 有条件：底模对得上，但要装自定义节点，4 步 | 速度：草稿档推测很快 | 作者只测过一台机器；4 步画质低于 8 步 | 2.05 + 3.6 GB | 只在需要“草稿预览档”时才做 |
| DMAD 8step full critic（10-29） | 推测**否**：按 T2VA 训练，lcm、12/2 | 作者说音画质量比 4 步明显好 | 不在 FL2VA 上训练 | Comfy 版 2.0 GB | 不做；维持 `research_adoption` E13“不挂” |
| lightx2v 新版本 | 现链已经是最新的 8step v1.1 | — | — | — | 不用动 |
| 时长 >192 帧 | 不是模型问题 | 时长 | 主机 / VAE OOM | 不用下载 | **A/B-4**（零下载）：同一镜头 243 帧，加 `--disable-pinned-memory`，decode 前加 Clear VRAM，看能不能过；过了再看画质 |

### 我的推荐顺序（项目方定）
1. **A/B-1：Pika Flex 对现链**。只下载 1.96 GB，底模不换，最值得测。
2. **A/B-4：长时长的显存设置**。零下载，零风险。
3. Trim、Omni、DMAD：**不接**。V2 和 VSA LoRA 只在想要“预演档”时再考虑。

## 7. 没查到 / 没核实的
- Pika Flex 的 FL2VA 在 9:16、768×1344 下的真实效果，以及 ComfyUI 里的显存和耗时。
- FastH3 V2 首尾帧模式的尾帧贴合度：两份官方说法冲突，没人实测。
- FastH3 Trim 有没有 FL2VA 权重：discussion #2 问了，没人回答。
- Reddit、X、中文社区：没搜到相关帖子。X 页面也没法直接抓取。
