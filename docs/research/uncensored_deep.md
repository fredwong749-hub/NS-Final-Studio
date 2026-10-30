# 成人内容限制 · 系统性调研（2026-10-30）

> 范围：MiniMax H3、Qwen Image 2.1、NoctQ、NudeNet / CLIP / Qwen3-VL 检测、H3 官方提示词规则。
> 结论只回答“限制在哪里”：模型权重、托管服务、提示词规则、后置检测器。项目代码的具体闸门见 `docs/UNCENSORED_INVENTORY.md`。

## 0. 结论速览

| # | 结论 | 置信度 | 对本项目的含义 |
|---|---|---|---|
| 1 | **本地 H3-Base 权重本身没有托管的提示词审查**；H3 官方托管 API 会对文本、图像、视频和增强后的提示词做自动审核，色情/违法内容可能被拦。 | 高（MiniMax HF 模型卡原文；Kingy 路由审计） | 我们的 H3 在 gpu3 本地跑，`explicit_content`、`block_explicit`、`held` 等是 **Claude 后置闸门**，不是模型能力。 |
| 2 | **H3 官方提示词指南允许一镜多人发声**：`(S1)`、`(S2)`、`(S1,S2)` 都合法；没有“一镜一人”的规则。 | 高（官方 `base-en.txt` §4.4） | `H3-D7` 的“普通镜一人 / 亲密镜只有林晚 / 不写男声”是项目附加规则，不是 MiniMax 要求。 |
| 3 | **H3 官方指南没有“禁止否定句”的硬规则**；它要求写看得见/听得见的具体细节。`H3-A5` 的“不写 no/not/never”来自项目/社区对 cfg=1 的适配。 | 中—高（官方指南全文；SOP 引用社区 [C]） | 这是提示词风格闸门，不是模型审查；可以删。 |
| 4 | **Qwen Image 2.1 官方本地权重没有 safety checker**；Alibaba 托管服务对 prompt / negative prompt 做审核，返回 `DataInspectionFailed`；官方 HF Demo 也走阿里云。 | 高（`model_index.json` 无 safety checker；阿里云 Model Studio 文档；LaoZhang 核对） | 本机 Image 2.1 本身不拒绝成人图；代码里的“安全衣物 / 防裸露负面词 / 成人参考图授权”是后置限制。 |
| 5 | 社区“Qwen-Image-2.1-Uncensored-GGUF”大多只是**原权重量化**，没有改权重；NoctQ V4 是**改了 transformer 权重**的合并模型，官方 Qwen 文本编码器 + VAE，开箱可生成裸体/成人场景。 | 高（NoctQ 模型卡；0xSojalSec 卡；LaoZhang） | 用 NoctQ 是一条合法路线；用官方 Qwen 2.1 也不需要在代码里加“安全”闸门。 |
| 6 | NudeNet / CLIP 后置检测有明显误报：本项目校准集里 CLIP v1 对 137 张着装图误报 54 张；NudeNet 对手指/特写也会误报。Qwen3-VL 问句校准后 94 张着装图 0 误报，但仍是**后置检测器**。 | 高（`services/render_router/ns_render/qc.py` 注释与校准记录） | 这些检测可以只记录，也可以整个删掉；它们不改变模型能生成什么。 |
| 7 | 人脸相似度、发色 HSV、焦外 Laplacian、VLM facts、连续性、PSNR/SSIM 都是**后置质量/内容检测**；它们能阻止一条成人镜头进入视频，但不是模型审查。 | 高（代码与 `docs/qc_gates.md`） | 按“uncensored”要求可全部关闭；技术尺寸/帧数/哈希仍可保留。 |
| 8 | 本地 H3 的“无服务端过滤”不等于“任何提示词都成功”：权重先验、量化、参考图、时长都会影响结果；社区对成人画面的一致性/解剖仍有争议。 | 中（Kingy 结论；社区报告） | 删闸门后仍应保留技术重试，不要把“检测通过”当成模型保证。 |

## 1. MiniMax H3：限制在路由，不在本地权重

### 1.1 官方模型卡的原文

Hugging Face `MiniMaxAI/MiniMax-H3` 的 **Safety Guardrails** 写的是：

> User-submitted text, images and videos, as well as enhanced prompts, are subject to automated moderation. Content suspected of being unlawful, pornographic, or infringing third-party rights may be blocked.

这说的是 **H3 官方托管服务**（以及 H3-Context-IR / Regenerate-2K 的托管阶段），不是下载到本地的 H3-Base 检查点。模型卡也明确说 H3-Context-IR 与 H3-Regenerate-2K 不在开源发布里：<https://huggingface.co/MiniMaxAI/MiniMax-H3>。

### 1.2 本地权重与托管 API 的区别

Kingy AI 的路线审计把限制拆成五层：权重先验、提示词预处理/编排、官方 API、第三方托管、许可/AUP。它的结论是：

- 本地 H3-Base：默认没有服务端提示词过滤；但“uncensored”没有被标准化验证，行为仍取决于权重。
- 官方 API / Hailuo：明确审核；422 `video description contains sensitive content`。
- 第三方托管：各自的 AUP + 可能的审核。

来源：<https://kingy.ai/blog/is-minimax-h3-really-uncensored-local-weights-api-hosts/>；<https://kingy.ai/blog/can-minimax-h3-generate-uncensored-video-what-local-deployment-actually-changes/>。

### 1.3 官方 H3 提示词规则（只列与“内容限制”有关的）

官方 `skills/h3-prompt-writing/references/base-en.txt`：

- §4.4 Speakers：`(S1)`、`(S2)`、`(S1,S2)` 都合法；**允许多人发声**；说话人首次出现时写年龄、性别、on/off screen、音色、语速。
- §4.6 `overall_soundscape`：1–4 句英文，一段；可以写 breathing / panting 等非语言人声；只有明确要求全片静音才写 `N/A`。
- §4.7 `non_diegetic_music`：1–3 句英文，只写乐器、速度、节奏、强弱；不写抽象情绪词；没有配乐写 `N/A`。
- §4.5 画面文字：可见文字用英文双引号包住；不是内容审查。
- §4.1 风格：`Live-action, cinematic, ...` 是示例，不是强制模板。

官方指南：<https://raw.githubusercontent.com/MiniMax-AI/MiniMax-H3/main/skills/h3-prompt-writing/references/base-en.txt>。

**结论**：`H3-D7` 的“普通镜一人 / 亲密镜只有林晚 / 不写男声”、`H3-A5` 的“不写否定词”、`H3-A9` 的“不写抽象情绪”、`H3-A10` 的“每镜一个运镜 / 官方运镜词”都是**项目/Claude 规则**，其中有些是合理的生成经验，但不是 MiniMax 的硬审查。

## 2. Qwen Image 2.1：本地无 safety checker，托管才审核

### 2.1 官方本地权重

Qwen-Image-2.1 的 `model_index.json` 只有 processor、scheduler、Qwen3-VL text encoder、transformer、VAE；**没有 `safety_checker` 组件**。模型卡也没有内容政策段。官方 HF Demo 的 `app.py` 把请求发到阿里云 `poc-dashscope.aliyuncs.com`，所以 Demo 的拒绝是阿里云平台行为，不是本地权重。

来源：<https://huggingface.co/Qwen/Qwen-Image-2.1>；<https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/model_index.json>；<https://huggingface.co/spaces/Qwen/Qwen-Image-2.1/blob/main/app.py>；<https://www.alibabacloud.com/help/en/model-studio/text-to-image>。

LaoZhang 的核对（2026-09-24）总结：

- 官方权重本地跑：pipeline 无内容过滤器；早期用户报告成人提示词不拒绝。
- Alibaba Cloud Model Studio：prompt / negative prompt 都审核，输出也审核（`DataInspectionFailed`）。
- “Uncensored GGUF” 多为同一权重的量化，不是改了 refusal layer。
- 官方许可仍是 Qwen Research License（研究/评估；商用需另签）。

来源：<https://blog.laozhang.ai/en/posts/qwen-image-2-1-nsfw>。

### 2.2 NoctQ V4

NoctQ 模型卡：基于 Qwen Image 2.1，**修改了 transformer 权重**（`base_model_relation: merge`），使用官方 `qwen3vl_8b_int8_convrot` 文本编码器与 `qwen_image_2.1_vae_bf16` VAE；官方说明“nudes and explicit scenes render without a LoRA”；推荐 25 步、euler、simple、cfg 3（cfg 1 更快但忽略负面提示词）。

来源：<https://huggingface.co/Noctaluna/Noct-Q-Uncensored-Qwen-Image-2.1>；<https://civitai.com/models/2958896>。

**结论**：本机 Qwen 2.1 / NoctQ 不需要代码层面的“安全”闸门；`SAFE_SHOT_TERM`、`NON_ADULT_NEGATIVE_EXTRA`、`NUDITY_NEGATIVE`、`enforce_clothed` 都是后置提示词控制。NoctQ 的 `cfg 3` 需要负面提示词才有意义，但这是模型设置，不是审查。

## 3. 检测器：它们不是模型，能删

### 3.1 NudeNet / CLIP

`services/render_router/ns_render/qc.py` 的校准注释：

- CLIP v1 成对提示词：137 张着装图误报 54 张；男性黑衬衫 0.85–0.95；正面着装女性被“背面赤裸”对子判 0.87。
- NudeNet 手指/拇指特写 0.39–0.64 误报，男性生殖器阈值提到 0.75。
- Qwen3-VL 问句（v3）在 94 张核对过的着装图 0 误报，3 张人工确认的裸露图全部命中；但它需要 ComfyUI 文本生成，仍是后置 VLM。

### 3.2 人脸 / 发色 / 焦外 / facts / 连续性

- `score.py`：SFace/CLIP 人脸相似度、NudeNet 找脸、发色 HSV、躯干 LAB、Laplacian 焦外、VLM facts、真人感 0–10。
- `shot_audit.py`：S3-F1–F8（人脸、焦外、发色、裸露、facts、LoRA 强度、调色、OCR）、S3-K1/K3（首尾帧同景/同装/结束状态）、R-C6/R-C7（帧闸门/连续性）。
- `packages/qc/ns_qc`：YuNet/SFace、发色、躯干颜色、首帧 PSNR、末帧 SSIM、漂移、音频 F0/CLAP。
- `weita_series.py`：`score`、`continuity_check`、`clip_checks`、`readiness`、`regate`。

这些都是**后置检测**；删掉不会改变 H3/Qwen 的生成能力，只会取消自动淘汰/拦截。保留技术项（分辨率、帧数、时长、哈希、文件存在）即可。

## 4. 对代码的含义

1. **模型层**：本地 H3-Base / Qwen 2.1 / NoctQ 没有必须调用的内容过滤器；当前代码里的成年/裸体/敏感词闸门都是项目代码。
2. **提示词层**：安全衣物、防裸露负面词、`shot_rules_safe`、`banned_words`、`minor_guard`、H3 的“一人/男声/无否定/无情绪/运镜词”都可以删；删之前要决定是否保留“项目方的创作规则”（一人一镜、只林晚发声是项目方原话，不是模型要求）。
3. **检测层**：NudeNet/CLIP/VLM/人脸/发色/焦外/连续性/PSNR/SSIM 都可删或改为只记录；技术尺寸/帧数/哈希建议保留。
4. **UI 层**：`explicit_hold`、露骨红标、成人“自动跳过”都是项目代码；API 字段可保留为兼容，但不再影响动作。
5. **gpu3 层**：`explicit_content`、`block_explicit`、`held`、`precheck`、`readiness` 的成人/内容项都是后置闸门；删掉后 gpu3 仍按 H3 参数出片。

## 5. 未决 / 需要项目方确认

- **H3 一镜一人 / 亲密镜只林晚发声**：文档写“项目方 2026-10-30 原话”。如果“全部 uncensored”也包括这条，就删 `H3-D7`；如果只是删 Claude 的审查，就保留。
- **年龄 ≥22 / 虚构成年人确认**：`g2_candidates` 的硬门槛。它是安全规则，不是成人内容过滤器；删不删需要项目方定。
- **minor_guard（未成年人外观）**：始终在负面词里；保留更安全，但与“完全 uncensored”不冲突（它限制的是未成年外观）。
- **H3 官方格式**：对齐句、四块字段、帧数网格、`<d>` 语法是模型输入格式；删了会直接影响 H3 出片，不建议当作“审查”删除。
- **Qwen / H3 许可**：本地权重无服务端过滤，但 Qwen Research License、H3 Community License 仍有地域/商用/AUP 限制；这是法律层，不是代码层。

## 6. 来源

- MiniMax H3 模型卡：<https://huggingface.co/MiniMaxAI/MiniMax-H3>
- H3 官方提示词指南：<https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt>
- H3 local vs API 审计：<https://kingy.ai/blog/is-minimax-h3-really-uncensored-local-weights-api-hosts/>
- H3 本地部署限制：<https://kingy.ai/blog/can-minimax-h3-generate-uncensored-video-what-local-deployment-actually-changes/>
- Qwen Image 2.1 模型卡：<https://huggingface.co/Qwen/Qwen-Image-2.1>
- Qwen Image 2.1 过滤位置核对：<https://blog.laozhang.ai/en/posts/qwen-image-2-1-nsfw>
- NoctQ V4 模型卡：<https://huggingface.co/Noctaluna/Noct-Q-Uncensored-Qwen-Image-2.1>
- Qwen uncensored 变体说明：<https://dev.to/purpledoubled/qwen-image-21-uncensored-text-encoder-finetune-or-gguf-and-what-each-one-changes-m92>
- 本项目 NudeNet/CLIP 校准：`services/render_router/ns_render/qc.py`；`docs/qc_gates.md`；`docs/qa_laptop.md`
