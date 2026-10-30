# MiniMax H3 官方来源逐一核查（GitHub / HF / MiniMax API 文档）

调研日期：2026-10-30。只读调研：没装东西，没用 GPU，没 ssh。
范围：只看官方来源（MiniMax-AI GitHub、MiniMaxAI HF 组织、MiniMax 官网/开放平台文档），外加官方 README 指向的 diffusers / SGLang 文档。社区帖只在官方讨论区内出现时引用，并标注置信度。
置信度：**高** = 官方原文；**中** = 多个社区来源一致，或从官方配置/源码可直接推出；**低** = 单个帖子或我的推断。
前置文档：`docs/research/h3_prompt_and_fl2v.md`（以下简称“前文”）。本文不重复前文内容，只补充和更正。

---

## 0. 结论速览

| # | 结论 | 置信度 |
|---|---|---|
| 1 | **8 月以来官方没有发布任何新权重。** HF `MiniMaxAI/MiniMax-H3` 最后一次提交是 2026-08-13，内容是改 README。GitHub 8 月 15 日之后只合并了文档和依赖修复（10-28），没有 Release。没有 Ref2VA 新版、官方蒸馏、稀疏注意力、Regenerate-2K 或 1080p 权重 | 高 |
| 2 | 稀疏注意力：README 写“will be released in a future update”。GitHub issue #89（10-10）和 HF #48 问进度，**官方都没回复** | 高 |
| 3 | Regenerate-2K：官方 8-04 回复“once this set of technologies becomes stable”，8-20 回复“Still working on it”，之后没有新消息。API 侧可以把**本地生成的 768p 视频**作为 `base_video` 传给 `/v2/video_regeneration` 放大到 2K | 高 |
| 4 | API 新增了 `MiniMax-H3-Highspeed / -Lite / -Max` 三个变体，**只有 API，没有开源权重** | 高（API 文档） |
| 5 | API 层面，**首尾帧（I2V）和参考图（Ref2V）互斥，不能在同一请求里混用**。但开源 Ref2VA 的官方提示词指南支持把 `<Picture N>` 当作首帧、关键帧或尾帧（“keyframe completion”），可以和 `<Subject N>` 参考同时使用 | 高（两份文档各自原文）/ 本地实际效果：低-中 |
| 6 | diffusers 官方文档：Ref2VA 的参考图“**do not bind the generated geometry**”。参考图锁的是外观和身份，**不锁构图**；构图要靠关键帧 | 高 |
| 7 | 官方给的推荐参数只有：shift video 12 / audio 3、CFG 蒸馏（无负向、无 guidance）、24 fps、17n+5 帧、短边 768、宽高为 32 的倍数。**官方仓库没写步数、采样器**（50 步来自 SGLang/vLLM 示例） | 高 |
| 8 | 官方权重是“mixed BF16/FP32”，时间嵌入、patch 和输出投影保留 FP32。ComfyUI master 仍有 `t_emb = self.time_embedder(t_vals).to(dtype)`，社区报告**完整版（非 pruned）权重**会出现每 17 帧一次的周期性亮度跳变 | 机制：高；现象：低-中 |
| 9 | 身份一致性方面，官方只做过一次表态：HF #87 回复“目前正在系统性解决”。官方 skill 的做法是：角色卡加“identity lock repeated in the prompt”加不可变特征清单；镜头漂移时缩短到 ≤6 s | 高 |
| 10 | 提示词语言：官方人员回复“除了需要生成的文字和对白内容 其他的都要用英文描述”，印证前文第 1 条 | 高 |

**对前文的更正和补充**
- 前文的 FL2VA 对齐句、I2VA 句、三字段结构，和 GitHub `skills/h3-prompt-writing/references/base-en.txt` 逐字一致，**无需更正**。
- 补充 1：README 里那个“Reproducible 768p **FL2VA**”示例脚本（`scripts/readme/reproducible-768p-fl2va-request.sh`）其实只传了一张首帧，用的是 **I2VA** 对齐句（`For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`）。官方**没有**“首帧+尾帧”的可复现请求示例，双关键帧的写法只能参照指南里的文字示例。
- 补充 2：前文说“基模步数官方参考 50”。准确地说，50 来自 SGLang cookbook 和 vLLM recipe；MiniMax 自己的 README 和 HF 模型卡没给步数。
- 补充 3：前文把 H3-Regenerate-2K 写成“不可用”。准确地说，开源权重没有，但 API 接受本地 768p 结果作为 `base_video`，见 §4。不过 API 会做内容审核，而且我们的成人镜头只在本地生成，所以这条路只适合普通镜头。

---

## 1. GitHub `MiniMax-AI/MiniMax-H3`

### 1.1 仓库结构（git tree API）
- 仓库里**没有 `docs/`、`examples/`、`configs/` 目录**。实际有：`FL2VA/`、`Ref2VA/`（各含 model_index.json、processor、text_encoder、tokenizer、transformer、video_vae、audio_vae 的代码和配置）、`scripts/readme/*.sh`、`skills/`（9 个）、`.claude/skills` 和 `.agents/skills`（h3-prompt-writing 的副本）、`assets/`、以及 README 的中、日、韩版本。
- README 原文：“Prompting guidance documents from the HuggingFace release are not copied into this repository to keep the markdown layout minimal.” 提示词指南在 HF 的 `docs/` 下，GitHub 上对应的是 `skills/h3-prompt-writing/references/base-en.txt` 和 `ref-en.txt`（字节数分别为 15773 和 23553，和 HF 的 `docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md` / `_ref_en.md` 一致）。
- 根目录有个奇怪的文件 `astra_gist_final_v2_2.py (2).html`，是 2026-09-25 外部 PR #83 上传、10-28 被合并的，和模型无关。

### 1.2 提交与 Release（`/commits?since=2026-08-01`，共 46 条；`/releases` 为空）
- 08-05 到 08-06：初始化、加 skills、加 README。
- 08-09 到 08-15：多语言 README、requirements.txt、`dac_utils.py` 的 init_weights 修复、本地 `file://` 路径支持、skill 兼容性说明，以及 `a107547f` 在 SKILL.md 里加的“Tips for Better Results”（见 §1.4）。
- 09-25 / 10-28：上面提到的无关 html，以及合并依赖修复 PR #37。
- **结论：没有 Release，也没有任何新模型、新代码、新参数。** 置信度：高。
  来源：<https://api.github.com/repos/MiniMax-AI/MiniMax-H3/commits?since=2026-08-01>、<https://api.github.com/repos/MiniMax-AI/MiniMax-H3/releases>

### 1.3 README 的关键原文（<https://github.com/MiniMax-AI/MiniMax-H3>）
- 规格：“Output duration | 4–15 seconds”；“The shorter side is set to 768 pixels by default. 2K generation can be achieved with H3-Regenerate-2K”；“Output frame rate | 24 FPS”。
- Ref2VA 输入：“**Images:** ≤ 9 images … **Videos:** ≤ 3 clips; each clip must be 2–15 seconds long; total duration ≤ 15 seconds … **Audio:** ≤ 3 clips … **Mixed inputs:** Maximum number of files across all input types is 12”。
- FL2VA：“Supports zero, one, or two input images … Two image inputs: First-and-last-frame-to-video generation”。
- Context-IR：“**H3-Context-IR is critical to the quality of the final output, so we strongly recommend incorporating it into your generation pipeline or following the ‘Prompting Guidance’ to build your own context-processing system.**”另有“it is not included in this open-source release”。
- 稀疏注意力：“H3 natively supports sparse-attention training and inference. The initial open-source release provides inference with full attention only. Our sparse-attention implementation will be released in a future update.”以及“During the final stage of training, we introduce native sparse attention”。
  → 训练末期用了稀疏注意力，但我们推理时用的是全注意力，这一点值得记住。“训练和推理不一致是否影响画质”官方没有说明（低，推断）。
- 权重：“The released checkpoints are CFG-distilled Omni Transformer model weights.”
- Regenerate-2K：“**Due to the complexity of the system, this module is not yet open-sourced. We will release it once it is ready.**”
- VAE：“After training its encoder, we additionally train a ViT-based decoder to reduce decoding costs and further improve reconstruction quality.”
- 示例里 Context-IR 的 Ref2VA 输出明确写了“`<Subject 1> (appears in [Shot 1]): fully_preserved - the man retains his identity, wavy blonde hair, pink suit …`”，这是官方系统做身份保持时的写法样本。

### 1.4 skills/
- `h3-prompt-writing/SKILL.md`（<https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/SKILL.md>）在 8-11 新增了：
  > “Always match the total duration of the description to the requested video length (4–15 seconds).”
  > “Prefer concrete visual and audio details over abstract words like "cinematic" or "beautiful".”
  > “When using keyframes (I2VA / FL2VA / L2VA), clearly state how the first and/or last frame connects to the timeline.”
  注意：这段是外部贡献者的 PR（GyArmyBrat，#44），由维护者 RyanLee 合并，不是模型团队的实验结论。置信度：中。
  另外，它和官方指南的写法有点矛盾：官方示例本身就写了“Live-action, cinematic”。我的理解是：风格词保留，后面必须跟具体的画面和声音细节。
- `base-en.txt` §3.1（I2VA）原文：“Character identity, clothing, colors, key objects, and spatial relationships should remain consistent.” 这是官方指南里**唯一直接提到颜色和身份**的句子。置信度：高。
- 官方 Hub skill `3d-animation-short-generator` 里和身份、漂移相关的做法（是给 Hub 平台用的，但思路可以借鉴）：
  - 角色卡要有“Main 3/4 view; Front / side / back views; Expressions; Material / costume / prop details … **Identity lock repeated in the prompt** … A short visual-ID note listing age range, body type, hairstyle, outfit colors, signature props, and **do-not-change traits**”。
  - `references/fallback-policy.md`：“H3 fallback ladder when a clip fails or drifts: 1. First retry: regenerate the same clip with the H3 prompt prefix strengthened by quoting the exact `Reference Anchors` block … 2. Second retry: **shorten the shot to ≤6s** and split the dropped seconds into a new adjacent row”。
  - `references/model-selection.md`：“Use character cards as the authoritative identity source. Use scene cards as the authoritative environment source.”
  - 置信度：高（官方原文）；对本地 FL2VA 是否同样有效：中。

### 1.5 GitHub Issues（`/issues?state=all`，共 96 条，**官方没有在任何技术 issue 下回复**）
| Issue | 内容 | 置信度 |
|---|---|---|
| #85（10-05）“full INT8/BF16 are unstable in ComfyUI; pruned is fine” | 原文：“These full checkpoints show periodic brightness dips / flashing … `minimax_h3_fl2va_int8_convrot` / `minimax_h3_fl2va_bf16` … This checkpoint does not: `minimax_h3_fl2va_pruned_int8_convrot`”；“The dips/spikes were periodic at a 17-frame cadence”；修复方法是把 `t_emb = self.time_embedder(t_vals).to(dtype)` 去掉 `.to(dtype)`。我核对了 ComfyUI master 的 `comfy/ldm/minimax/model.py`，第 751 行**仍然是 `.to(dtype)`**，还没修 | 现象：低-中（单人报告，另一人用 diffusers 对照后支持）；代码现状：高 |
| #84（09-28）Ref2VA 在本地 ComfyUI 中参考保真度下降 | “Another H3 user reported that removing the `--fast fp16_accumulation` startup flag … made reference adherence substantially better.” | 低 |
| #86（10-06）每次都给角色加婚戒 | “This happens both through the official MiniMax API and through local/open-weight H3 Ref2VA workflows.” 说明这是模型先验压过了参考图 | 低-中 |
| #17 多人声音串音 | 原文：“Visual subject binding works extremely well … However, the audio branch can fail to keep different voice identities attached”；FL2VA 也能复现；闭源付费版也会串。绕过办法：A→B→A 时第三句用新 ID S3 并复制 A 的音频参考；稍微改一下时长（例如 12.5→14 s）也可能修好 | 中（多人复现） |
| #74 高动态画面糊 | “肢体人脸衣服全部破碎…50步都救不了” | 低-中 |
| #60 I2V/首尾帧二次采样或 latent 放大失败 | “只要是i2v或首尾幀都沒辦法二採或放大latent” | 低 |
| #46 VAE tile 参数 | 官方配置“`vae_clip_length = 17`, `vae_tile_size = 256`, `vae_tile_overlap_min = 64`”，改 tile 会出现块状伪影；无官方回复 | 中（配置值）/ 低 |
| #89 稀疏注意力发布计划 | 无回复 | 高（无回复本身） |

---

## 2. Hugging Face `MiniMaxAI`

### 2.1 组织内的 H3 相关仓库
`/api/models?author=MiniMaxAI` 的结果中，H3 只有 **`MiniMaxAI/MiniMax-H3`** 一个仓库（createdAt 07-28，lastModified 08-13）。**没有** Ref2VA 单独仓库、没有蒸馏版、没有 Turbo、没有 sparse、没有 2K/1080p 仓库。
三个月内的新仓库只有 `MiniMax-M3.1-Flash`（LLM，10-17）。置信度：高。

### 2.2 MiniMax-H3 的提交历史（`/api/models/MiniMaxAI/MiniMax-H3/commits/main`）
08-03 “Init” → 08-04 加 model_index → 08-05 “Make model_index the public entry” → 08-06 改 diffusers 链接 → 08-06 改 `docs/QA-about-License.md` → 08-09 到 08-13 都是改 README。**权重自 08-03 后没变过。** 置信度：高。

### 2.3 文件与配置（官方权威参数）
- `FL2VA/model_index.json` 和 `Ref2VA/model_index.json`：`"sigma_shift_scales": {"video": 12.0, "audio": 3.0}`；FL2VA 的 `"tasks": ["t2va", "fl2va"]`，Ref2VA 的 `"tasks": ["ref2va"]`。
- `scheduler/scheduler_config.json`：`"shift": 12.0`；`audio_scheduler/scheduler_config.json`：`"shift": 3.0`。
- 根目录的 `model_index.json` 有 `transformer`（FL2VA）和 `transformer_ref`（Ref2VA）**两个独立的 transformer**。也就是说 Ref2VA 是另一套权重，不是 FL2VA 加适配器。
- `FL2VA/transformer/config.json`：50 层，hidden 5376，56 头，latents_dim 24，audio_latents_dim 32，patch [1,2,2]。
- `docs/`：只有 `QA-about-License.md`、`VIDEO_PROMPT_WRITING_GUIDE_base_en.md`、`VIDEO_PROMPT_WRITING_GUIDE_ref_en.md` 三个文件。
- HF 模型卡和 GitHub README 正文相同，只多了 tags 和一行“News: Offical skills to improve prompt writing”。
- 置信度：高。

### 2.4 HF 讨论区（共 120 条，我逐条打开了与颜色、身份、尾帧、Ref2VA、稀疏、新权重相关的帖子）
官方账号只有 `ryanlee-dev`（isOrgMember=true）回复过。

**官方回复（高）**
- #87 “脸崩的如此厉害，何时修复”：ryanlee-dev（08-20）：“**感谢反馈，目前正在系统性解决**”。10-10 有人追问 fix 时间，没有回复。<https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/87>
- #92 Regenerate-2K：ryanlee-dev（08-20）：“**Still working on it**”。10-24 仍有人追问，没有回复。<https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/92>
- #39：ryanlee-dev（08-04）：“We will open‑source H3‑Regenerate‑2K once this set of technologies becomes stable.”
- #14：ryanlee-dev：“H3-Context-IR 由于是一系列模型的组合，技术上无法开源。我们后续会尝试用新的技术架构解决”；并确认 Regenerate-2K 是“用 ref2va 的模型来参考原视频生成”的思路：“是的 H3-Regenerate-2K之后稳定了会开源”。
- #32 中文提示词：ryanlee-dev：“**除了需要生成的文字和对白内容 其他的都要用英文描述**”。
- #54 首尾帧用同一张图（做循环）：ryanlee-dev：“这个问题还没研究过”。
- 稀疏注意力（#48）、非蒸馏权重（#22、#44、#88、#97）、官方蒸馏加速版（#89）：**均无官方回复**。

**社区内容（中/低），与我们直接相关**
- #91 身份：同一张参考图，走“FL2VA 检查点 + Ref2V Turbo LoRA + ImageToVideo、8 步、1344×768、124 帧”时，InsightFace 平均相似度 **0.8855**；走“ReferenceToVideo + 音频参考”时只有 **0.0884**（基本换了一个人）。换原生 Ref2VA、18 步也没救回来。另一位用户 rocky533 反驳说 Ref2VA 保持身份“the best i have seen for any local model”。→ **用首帧锁脸比纯参考图稳**，这一点和我们的 FL2VA 路线一致。置信度：低-中。<https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/91>
- #78 颜色：“the result obtained by encoding and then decoding the image showed color differences compared to the original image”；有人跟帖说“it becomes serious on a pure background”；rocky533 认为是“the add guide node that does this”。**官方没有回复。** → 首帧经过 VAE 编解码本身就可能偏色，纯色背景最明显。置信度：低-中。<https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/78>
- #65 分辨率与贴合度：多人报告 352p/416p/576p 下的构图和首帧贴合明显好于 768p；有人的做法是“fire off a few low-res ones, pick the best, and use that as the reference for the high resolution”。置信度：中（多人一致，无官方解释）。
- #60 Ref2VA 换人：社区建议把“身份图”和“分镜/构图图”分开写，例如“`<Picture 2>` is a storyboard reference for Shot 2. Only its camera angle, framing and subject placement are referenced. The identity and appearance of the person visible in Picture 2 are not referenced.” 置信度：低（未验证）。
- #71 ref 指南答疑（Asakura，**非组织成员**，HF 资料无所属机构）：“`partially_preserved` means that some defined reference characteristics are changed … It does not mean that only part of the Subject is visible”；三个段落里重复描述“Some repetition is therefore intentional”。置信度：低-中。
- #54 循环镜头：最初发帖的人后来写道“我现在基本使用ref2va模型了，配合comfyui官方的‘Add Guide for MiniMax H3’节点，可以锁定任意关键帧，轻松实现首尾帧功能…而且可以添加各种参考来增强一致性”。→ **“Ref2VA 加参考图，再用 AddGuide 锁首尾帧”是有人在用的组合**。置信度：低（单人经验）。
- #57 / #87 小脸崩坏：“when the face is small, it can become distorted … I tried generating a video on the official website in 2K mode, but the problem still persists”。置信度：中。
- #96 几乎不眨眼：建议在提示词里写明第几秒眨眼。置信度：低。
- #74 帧率：写实视频也有“almost identical 2 frames problems”，动漫风格最严重。置信度：低-中。
- #76 / GH#95 片头 0.5 s 乱语：建议写 `overall_soundscape`（模型“does NOT do silence well”）；台词以句号结尾；声音参考控制在约 4 s。置信度：低-中。
- #85 VAE 慢：“hard‑coded highly conservative 256‑chunk setting”。置信度：低。

---

## 3. ComfyUI 侧与官方实现的差异（官方 README 指向 Comfy，所以一并核对）
- SGLang cookbook 原文：“Full model | **Official mixed BF16/FP32**, CFG-distilled … Lossless reference and consistency GT path”；“MiniMax-H3 preserves the original FP32 dtype of its patch, time, and output projections”。<https://docs.sglang.io/cookbook/diffusion/MiniMax/MiniMax-H3>（高）
  “Pruned, quantized, compact-encoder, and LoRA routes are outside that baseline”（高）。也就是说，我们用的 pruned + 量化 + LoRA 组合**本来就不在官方一致性基线内**。
- ComfyUI `comfy/ldm/minimax/model.py` 第 751 行 `t_emb = self.time_embedder(t_vals).to(dtype)` 会把时间嵌入降到 bf16/fp16，和上面的官方精度策略不一致。GH#85 显示**只有完整版（非 pruned）权重**会受影响，表现为每 17 帧的亮度跳变。我们用的 pruned 权重（前文提到的 w4a8_mixed / int8 pruned）按这份报告应该不受影响。如果以后换成完整版权重，需要先确认这个问题修了没有。置信度：机制中，影响低-中。

---

## 4. MiniMax 官网与开放平台 API

### 4.1 `/v2/video_generation`（<https://platform.minimax.io/docs/api-reference/video-generation-v2-create>）
- 模型（原文）：
  - “`MiniMax-H3`: the variant for high-quality video creation … `768P` / `2K` resolution, 4–15s duration.”
  - “`MiniMax-H3-Highspeed`: balances generation quality and speed … `768P` resolution, `2K` is not supported”
  - “`MiniMax-H3-Lite`: the lightweight variant … `480P` / `768P`”
  - “`MiniMax-H3-Max`: the fast generation variant … `480P` / `768P` … 5–15s duration”
  - 这三个变体在 HF 上都**没有权重**。置信度：高。
- 首尾帧和参考图互斥（原文）：“**Image-to-video and reference-to-video are mutually exclusive**: if any `reference_image` / `reference_video` / `reference_audio` role appears in content, then `first_frame` / `last_frame` must not appear (and vice versa); the two cannot be mixed.” 置信度：高。
- 数量限制：“first frame ≤ 1, last frame ≤ 1, reference images ≤ 9”；参考视频 ≤3 个，单个 2–15 s，总长 ≤15 s；音频同样。
- 比例：“Image-to-video … the aspect ratio is determined by the input image and `ratio` is always `adaptive`”。→ 官方 I2V 的画幅完全由输入图决定，这印证了前文“上传前先裁成 768×1344”的做法。
- 提示词增强：只有 H3-Max 有 `extra.prompt_expansion_mode`（`disabled` / `balanced` / `quality`）。**API 没有 seed、negative、cfg、steps 这类参数**，也没有专门的人脸或角色参数。原文：subject 引导只能通过 `reference_image/video/audio` 实现。置信度：高。
- 文本上限：“a maximum of 7000 characters per `text`”。

### 4.2 `/v2/h3_context_ir`（<https://platform.minimax.io/docs/api-reference/video-generation-v2-h3-context-ir>）
- “This endpoint only returns an enhanced video prompt. It does not create a video generation task.”
- “H3-Context-IR is a complex system and its implementation is not open sourced. This API can be used both to validate the official Full 2K-Workflow results and in production workflows.”
- → 可以把**非敏感镜头**的原始描述和首帧发给 Context-IR，拿回官方格式的提示词，作为我们自己改写器的“标准答案”样本。注意 README 原文：“User-submitted text, images and videos, as well as enhanced prompts, are subject to automated moderation”。成人镜头不能走这条路。置信度：高。

### 4.3 `/v2/video_regeneration`（<https://platform.minimax.io/docs/api-reference/video-generation-v2-regeneration>）
- “Regenerate a source video that meets the MiniMax-H3 768P output specifications into a 2K video.”
- 两种方式：`source_task_id`（需要白名单）或 `base_video`：“provide exactly one `type=video_url`, `role=base_video` source-video item in `content`, along with the other inputs used to generate that 768P video”。
- “It does not perform general-purpose processing of arbitrary videos.” → 输入必须是符合 H3 768P 规格的视频；**本地 H3-Base 的结果可以用**（README 的 Full 2K Workflow 就是这么做的）。置信度：高。

### 4.4 官方博客（<https://www.minimax.io/blog/minimax-h3>）
只有理念层面的介绍（“generalized reference and editing”、“Contextual Omni Representation”、2K 用 in-context regeneration），**没有参数、颜色或身份方面的指导**。官网新闻页抓取不到带日期的条目。置信度：高（我确认页面里没有这些内容）。

---

## 5. 专题问答

### 5.1 最近 3 个月有没有新的官方 checkpoint？
**没有。** Ref2VA、蒸馏版、稀疏注意力、Regenerate-2K、1080p 的官方开源权重都没发布。（HF 提交历史、组织模型列表、GitHub Releases 均为空。）置信度：高。
官方讨论区里出现的“新权重”全部是第三方的：LightX2V Turbo、FastVideo FastH3 / FastH3-Omni（Ref2VA 8 步 PDD + VSA，SGLang 文档有介绍）、alibaba-pai PDD、Singularity、FL/Ref hybrid 等。这些不属于本文范围，交给其他调研文档。

### 5.2 官方推荐的 steps / cfg / shift / sampler / 分辨率 / fps
| 项 | 官方值 | 出处 | 置信度 |
|---|---|---|---|
| shift | video 12 / audio 3 | HF `model_index.json`、scheduler_config | 高 |
| cfg | 无（CFG 蒸馏，一步只做一次前向，没有 negative） | README；diffusers 文档原文：“guidance is baked into the weights, there is no guider, no `negative_prompt` and no `guidance_scale`” | 高 |
| steps | **MiniMax 没给**；SGLang/vLLM 示例用 50 | SGLang cookbook | 中 |
| sampler | **MiniMax 没给**（官方调度器是 `MiniMaxH3Scheduler`，flow-matching） | — | — |
| 分辨率 | 短边 768（训练画布 1344×768），宽高为 32 的倍数；diffusers：“960x544 runs about 2.3x faster per step than the trained 1344x768” | README、diffusers 文档 | 高 |
| fps / 时长 | 24 fps；4–15 s（diffusers 写 5–15 s）；帧数取 17n+5 | README、diffusers | 高 |
| seed | diffusers：“A request draws the keyframe or reference conditioning noise first, then the video noise, then the audio noise”。→ 关键帧也带条件噪声抽样，所以同一个 seed 在换了关键帧之后不保证结果可比 | diffusers | 高 |

### 5.3 Ref2VA（最多 9 张图）能不能跨镜头锁定脸和服装？能不能和首尾帧一起用？
- **能锁外观，不锁构图。** diffusers 原文：“Unlike the keyframes above, references do not bind the generated geometry: they are encoded at their own resolution and the target canvas defaults to MiniMax-H3's 16:9.” 官方 ref 指南的写法：`<Subject 1> is the young woman in <Picture 1>, with long dark hair, a blue cardigan, and a thin silver necklace.`，加 `retention_analysis` 里的 `fully_preserved - … identity … retained`。一个主体可以由多张图共同定义：“One subject may be defined by multiple reference assets”。服装可以单独定义成一个 Subject，再写明“worn by `<Subject 3>`”（#71，社区）。置信度：高（文档）/ 实际跨镜头稳定性：中（#17 说视觉绑定“works extremely well”，#91 说加了音频后身份崩掉，#86 说会凭空加戒指）。
- **和首尾帧一起用**：
  - API：**不行**（原文明确互斥）。高。
  - 开源模型的提示词格式：**支持**。ref 指南原文：“Use a standalone `<Picture N>` when the reference image itself serves as a shot's first frame, keyframe, last frame …”，任务类型写 `keyframe completion`，示例“`[video continuation + keyframe completion]`”，镜头里写“the shot begins from `<Picture 1>` / the shot ends on `<Picture 3>`”。高。
  - 但是在开源推理里，Ref2VA 的参考图走的是参考通道，本身不绑定几何。要让它真正当首帧或尾帧用，ComfyUI 里要配合 `MiniMaxH3AddGuide` 打关键帧（#54 有用户这样用）。效果：低-中，需要我们自己 A/B。
- **可以采用的方案（推断，低-中）**：主线保持 FL2VA（首尾帧锁脸最稳，#91 的数据支持）。对首尾帧本身来自不同生成、人脸容易漂的镜头，另外跑一组 A/B：“Ref2VA + 林晚角色卡（正面、3/4 侧、全身服装），在 ComfyUI 里用 AddGuide 在第 0 帧和最后一帧放首尾帧”，提示词按 ref 指南的六段格式写。尽量不加音频参考（#91 显示加音频后身份崩坏）。

### 5.4 官方关于身份和颜色的指导
- 身份：①提示词全英文，台词保留原语言（官方 #32 回复）；②I2VA/FL2VA 中“Character identity, clothing, colors … should remain consistent”；③Hub skill 的做法：角色卡、提示词里重复写 identity lock、列出不可变特征清单；漂移时引用锚点块重跑，还不行就把镜头缩短到 ≤6 s；④脸崩是已知问题，官方称“正在系统性解决”。
- 颜色：**官方没有任何关于颜色、调色、色偏的指导或参数。** 唯一能用的是提示词手段：ref 指南示例在开头用一句风格句写色调（“with soft lighting and a slightly desaturated color palette”）；base 指南说关键帧任务的风格“derive the style from the reference image”。→ 建议每个镜头的开头风格句固定同一套色调描述，并且和首帧实际的色调一致（中，推断）。

### 5.5 已知限制（官方承认或官方讨论区里多人报告的）
1. 小脸、远景、高速运动时脸部崩坏（官方回复“系统性解决中”）。
2. 768p 下的提示词和构图贴合度不如低分辨率（#65，多人报告）。
3. VAE 编解码偏色，纯色背景最明显（#78）。
4. 片头约 0.5 s 乱语；多人对话串音，同性别的声音最容易串（#76、GH#17）。
5. 几乎不眨眼（#96）；有重复帧或半帧率现象（#74）。
6. 首尾帧用同一张图时容易几乎静止（#54）。
7. I2V/FL2V 结果再做二次采样或 latent 放大容易失败（GH#60）；15 s 用 Ref2VA 做 2K 重生成会崩（#14 用户实测）。
8. 凭空添加饰品，例如戒指（GH#86，API 版也有）。

---

## 6. 没找到或无法核实的内容
- 官方开源的稀疏注意力实现、发布时间表（README 只说 future update，issue 没有回复）。
- 官方 Regenerate-2K 权重、官方蒸馏或 Turbo、非 CFG 蒸馏的 base 权重、1080p 权重：都不存在。
- 官方推荐的步数和采样器（MiniMax 自己的文档里没有）。
- 官方关于颜色、色偏、VAE 编解码偏色的任何说明或修复。
- 官方技术报告（#44 有人问，没有回复；我也没找到）。
- `MiniMax-H3-Highspeed / Lite / Max` 和开源 H3-Base 是什么关系（是不是蒸馏或稀疏版），API 文档没说明，官网也没有发布文章。
- GH#82 提到的“H3.1（Higgsfield 平台）”在 MiniMax 官方文档里**查不到**，可能是第三方平台的叫法。
- “Ref2VA + AddGuide 首尾帧”组合的官方说明：没有，只有社区经验。
- 官网新闻列表页抓取不到带日期的条目。

## 7. 来源清单
- GitHub：<https://github.com/MiniMax-AI/MiniMax-H3>（README、`skills/h3-prompt-writing/{SKILL.md,references/base-en.txt,references/ref-en.txt}`、`skills/3d-animation-short-generator/{SKILL.md,references/*.md}`、`scripts/readme/*.sh`）；API：`/commits?since=2026-08-01`、`/releases`、`/issues?state=all`；issue #17 #46 #60 #74 #84 #85 #86 #89
- HF：<https://huggingface.co/MiniMaxAI/MiniMax-H3>（README、`model_index.json`、`FL2VA/model_index.json`、`Ref2VA/model_index.json`、`scheduler/`、`audio_scheduler/`、`FL2VA/transformer/config.json`、`docs/`）；讨论 #14 #22 #32 #39 #44 #48 #54 #57 #60 #64 #65 #71 #74 #76 #78 #81 #83 #85 #87 #88 #89 #91 #92 #95 #96 #97 #105 #106 #114
- MiniMax：<https://platform.minimax.io/docs/api-reference/video-generation-v2-create>、`…-h3-context-ir`、`…-regeneration`；<https://www.minimax.io/blog/minimax-h3>
- README 指向的官方推理文档：diffusers `docs/source/en/api/pipelines/minimax_h3.md`；SGLang <https://docs.sglang.io/cookbook/diffusion/MiniMax/MiniMax-H3>
- ComfyUI 源码核对：<https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/ldm/minimax/model.py>（第 751 行）
