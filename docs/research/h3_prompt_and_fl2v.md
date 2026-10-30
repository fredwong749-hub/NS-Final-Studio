# MiniMax H3 FL2VA：官方提示词结构、推荐参数与首尾帧一致性问题调研

调研日期：2026-10-30（只做了资料调研：没装东西，没用 GPU，没改 gpu3）
置信度：**高** = 官方文档或源码直接写明；**中** = 多个社区来源一致，或能从源码推出机制；**低** = 单个社区帖或我自己的推断。

---

## 0. 结论速览（按优先级）

| # | 建议改动 | 置信度 |
|---|---|---|
| 1 | 提示词正文改成**英文**，按官方 FL2VA 格式写：第一行是固定的“图像对齐句”，然后空一行，再写三个字段。对白内容保持中文原文 `<d>[Chinese] …</d>` | 高（官方指南） |
| 2 | 首帧和尾帧在上传前用**同一种方式**裁成 768×1344。ComfyUI 节点对首帧是**拉伸**处理，对尾帧是**居中裁切**，比例不对时两帧几何不一致，容易出现重影或落不到尾帧 | 高（源码）/ 对重影的影响：中 |
| 3 | LoRA 与 shift 要配对：现在用的 `fl2v_turbo_8step_v1.0`（544p 训练，shift 12/3；Kijai 压成 rank-24 的版本）配 768p + 6/3，两者不匹配。改用官方 `minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16`（shift 6/3），或者保留 v1.0 但把 shift 改回 12/3 | 高（官方表格）/ 对效果的影响：中 |
| 4 | 采样用 euler + simple、8 步、cfg 1（BasicGuider），**不加负面提示**。关掉 EasyCache、Spectrum、TeaCache 这类跳步缓存；不用 ancestral/SDE 采样器 | 中-高 |
| 5 | 正文按“首帧状态 → 可观察的中间变化 → 差距逐步收窄 → 落到尾帧状态”写，只写一个镜头、一个主要动作、一个运镜，不复述两张静帧 | 高（官方指南） |
| 6 | 首尾帧差距控制在“一个连续动作能走完”的范围内：同景别、同光照、同机位族。脸要够大，远景人脸是公认弱点 | 中 |
| 7 | 必须经过中间姿态的镜头，可以用 `MiniMaxH3AddGuide` 加中间关键帧 | 中（节点存在，FL2VA+Turbo 场景没实测过） |
| 8 | 243 帧合法（17k+5 网格），**不需要** 4n+1，也没有 context window 问题 | 高（源码） |

---

## 1. 官方提示词结构（H3 / FL2VA）

### 1.1 来源
- 官方提示词指南（HF）：<https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md>
- 官方 GitHub：<https://github.com/MiniMax-AI/MiniMax-H3>。官方“提示词改写器”就是 `skills/h3-prompt-writing/SKILL.md` 加 `references/base-en.txt`，后者和 HF 上的指南逐字节相同。
  - <https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills>
- **没有开源的 prompt enhancer。** 官方改写系统 H3-Context-IR 只在 API 上提供，README 写明 “not included in the open-source release”。所以 SKILL.md 和 base-en.txt 就是唯一公开的“系统提示词”。
- ComfyUI 官方提示词页：<https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide.md>
- 社区改写器（非官方）：Omni-Rewriter <https://github.com/WayneJin0918/Omni-Rewriter>（HF 讨论 #79）。它只做 t2va，参考价值有限。

### 1.2 结构（原文摘录）

FL2VA 的第一行是固定句式，下面是逐字原文：
```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.
```
> “`N` is the index of the actual final shot, and `S.SS` is the effective video duration formatted to exactly two decimal places. The instruction must be the first line of the final prompt, followed by one blank line before the core fields.”

然后依次是三个字段：
```text
integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...
```

FL2VA 专门的规则（原文）：
> “FL2VA generally favors a single shot so the model can interpolate continuously from the first frame to the last frame. Use multiple shots only when they are explicitly specified. The last frame must be reached by the final `[Shot N]` at the end of the video.”
> “Recommended structure: **first-frame state → observable intermediate changes → progressively narrowing differences → last-frame state**.”
> “The body should not repeat two static image descriptions; instead, it should supply the motion path that connects them.”

官方 FL2VA 示例（8 秒单镜头）：
```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a rain-soaked cyclist begins in the position and framing established by Picture 1, holding a closed black umbrella beside a silver bicycle. The camera pulls out with small amplitude at slow speed as she releases the bicycle handle, raises the umbrella above her shoulder, and presses the runner upward until the canopy opens. Water rolls from the expanding fabric while she steps beneath it, rotates the handle into the final angle, and settles into the pose, spacing, and composition established by Picture 2 at the end of the shot.

overall_soundscape: Rain falls steadily on the pavement, followed by the metallic click of the umbrella runner and the soft snap of the canopy opening. Water drips from the bicycle frame as distant traffic passes.

non_diegetic_music: N/A
```

其他要点：
- **语言**：SKILL.md 原文是 “Write rewrite sections in English; preserve dialogue, lyrics, and visible scene text in their original language.” ComfyUI 页面也写了 “Write prompts in English.” 我们现在用中文写动作描述，和训练分布（Context-IR 生成的英文改写）不一致。置信度：高（这是官方要求）；改成英文能否直接修好漂移：中，需要 A/B 验证。
- **开头先写风格**：`[Shot 1]` 开头写风格和初始构图，例如 “Live-action, cinematic, a medium close-up frames…”。第一个镜头不写时间戳。
- **运镜词汇**：运动类型 + 幅度 + 速度。可用的有 Push In/Pull Out、Zoom In/Out、Pan、Truck、Tilt、Pedestal、Arc Shot、Tracking Shot、Static Shot、Shake Slightly/Strongly、POV、Roll。幅度写 `with small amplitude` / `with large amplitude`，速度写 `at slow speed` / `at fast speed`。运镜要写成句子里的自然动作，不要把标签堆在句末。
- **对白语法**：说话人身份、编号 `(S1)`、动作和语气都写在 `<d>` 外面；`<d>` 里只放语言标签和原文台词，例如：
  `The young woman with a soft, low voice (S1) says: <d>[Chinese] 你别走。</d>`
  - 说话人第一次出现时，要描述年龄、性别、是否在画面内、音色、语速。
  - 画外音必须写 `says in an off-screen voiceover`，并在 `</d>` 后注明 “while her lips remain completely closed”。
  - 台词被片尾截断用 `<cutoff>`，跨剪辑的台词用 `<scenetrans>`。
  - ComfyUI 页面补充：每句以标点结束；不要用省略号（会降低清晰度）；不要有装饰性重复和 emoji。
- **overall_soundscape**：1–4 句英文写成一段，内容是环境声、动作声和非语言人声，不重复对白。只有明确要求全片静音时才写 N/A。
- **non_diegetic_music**：1–3 句英文；没有配乐就写 `N/A`。我们现在的写法符合要求。
- **长度**：没有硬性上限（vLLM recipe 给的 API 上限是 7000 字符）。指南要求 “Every detail should correspond to something visible or audible”。HF 讨论 #65 有用户建议高分辨率下用“一个运镜 + 一个主动作 + 一句简短的保持说明”。
- **不要写负面提示，也不要写否定句**：BasicGuider 是 cfg 1，没有负向分支。ComfyUI 页面原文：“a ban list adds the unwanted concepts. Describe what should appear instead.”
- **画面上的文字**写在英文双引号里，原样保留。我们要求无字幕，所以干脆不要提文字。

### 1.3 建议的 FL2VA 模板（243 帧 ≈ 10.12 s）
```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 10.12-second mark of the target video.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, a medium close-up begins in the position, framing and lighting established by Picture 1: <人物/位置/服装/道具锚点，一句话>. The camera pushes in with small amplitude at slow speed as <动作开始> ... <中间可观察变化> ... The young woman with a soft, slightly husky voice (S1) says: <d>[Chinese] 台词原文。</d> <差距逐步收窄的动作>, and she settles into the pose, expression, spacing and composition established by Picture 2 at the end of the shot.

overall_soundscape: <1–4 句英文>

non_diegetic_music: N/A
```
- `S.SS` 用 `f"{frames/24:.2f}"` 算（243 帧时得到 10.12）。
- ComfyUI 节点把 first_frame 和 last_frame 依次传给 Qwen3-VL 文本编码器（`clip.tokenize(prompt, images=images)`），所以 Picture 1 是首帧、Picture 2 是尾帧，这句对齐语是起作用的。置信度：高（源码）。

---

## 2. 官方 / 半官方推荐参数

| 项 | 值 | 来源 | 置信度 |
|---|---|---|---|
| 基模 shift | video 12 / audio 3（写在 FL2VA `model_index.json` 的 `sigma_shift_scales`） | HF `FL2VA/model_index.json`；SGLang cookbook | 高 |
| 基模步数 | 官方参考 50；ComfyUI 模板 20（动作质量建议 25） | SGLang / vLLM / Comfy 文档 | 高 |
| CFG | 权重是 CFG 蒸馏版，单分支，cfg=1，没有负向 | README、vLLM、Comfy | 高 |
| 帧数 | 24 fps，帧数对齐 **17k+5**；训练范围约 124–362 帧（5–15 s）。243 = 17×14+5，合法 | ComfyUI `nodes_minimax_h3.py` | 高 |
| 分辨率 | 短边 768，面积上限 768×1344，宽高是 32 的倍数；9:16 对应 768×1344 正好 | 源码 `adapt_canvas` | 高 |
| 首尾帧强度 | **没有强度参数。** 关键帧作为条件 token 插在文本之后，“re-injected every step (never denoised)”，按 RoPE 时间位置对齐到第 0 帧和最后一帧。Comfy 文档：“denoise does not scale guide strength” | 源码 | 高 |
| noise-aug / latent anchoring | 官方没有这类选项 | 同上 | 高 |
| 中间关键帧 | `MiniMaxH3AddGuide(frame_idx=…)` 可以在任意帧加锚点，负数从片尾往前数。注意：这些图**不进文本编码器** | 源码 / Comfy multiframe 文档 | 高（存在）/ 中（FL2VA+Turbo 下的效果） |
| 首尾帧预处理 | first_frame：`_resize(..., "disabled")`，**直接拉伸**；last_frame：`"center"`，**等比居中裁切** | 源码 | 高 |

### Turbo / 蒸馏 LoRA（LightX2V）
来源：<https://github.com/ModelTC/Minimax-H3-Turbo>、<https://huggingface.co/lightx2v/Minimax-h3-Turbo>（文件列表和讨论 #42/#48/#52/#57）

| 文件 | 训练分辨率 | shift | 步数 |
|---|---|---|---|
| fl2v_turbo_8step_v1.0（**我们正在用的**，Kijai rank-24 压缩版） | 544p，混合宽高比 | **12/3** | 8（或 4） |
| fl2v_turbo_8step_v1.0_768p / **v1.1_768p**（最新） | 768p（1344×768） | **6/3** | 8 |
| fl2v_turbo_4step_v1.3_768p | 768p | 6/3 | 4 |

- 官方 Studio 默认用 8-step 768p，原文 “Recommended settings: 8 NFE, video shift 6, audio shift 3”；讨论 #48 推荐 Euler + Simple。
- **我们的问题**：我在笔记本上的代码副本 `services/render_router/ns_render/workflows.py` 里看到用的是 544p 的 8step v1.0 rank-24 版，graph 里**没有 SigmaShift 节点**。你们说的是 6/3，可能 gpu3 上的版本不一样，需要核对。544p 版是按 12/3 训练的，配 6/3 时 sigma 网格和训练不一致；rank-24 压缩也会再损失一些精度。**建议**：换成 `minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors`，强度 1.0、6/3、euler/simple、8 步；或者继续用 v1.0，但 shift 改回 12/3。置信度：配对规则是高；对首尾帧一致性的提升幅度是中，需要 A/B。
- **兼容性风险**：讨论 #48 有用户（kingp0dd）报告 8-step 768p LoRA 和 Kijai 的 `minimax_h3_fl2va_pruned_w4a8_mixed` 不兼容，只能配 int8 convrot。笔记本代码里 unet 用的正是 w4a8_mixed，要确认 gpu3 实际加载的是 int8 还是 w4a8。置信度：低-中（只有一位用户报告）。
- **竖屏风险**：768p Turbo 是在 1344×768 横屏上训练的，我们跑的是 768×1344 竖屏。讨论 #44 报告 ref2v turbo 在 9:16 下“上半画面容易重影/叠影”，16:9 正常。FL2V 目前没有同类报告，但可能有同样风险。置信度：低-中。建议用固定种子做一次 9:16 对比：Turbo 和基模 20 步各跑一次。

### 8 步蒸馏对尾帧贴合的影响
- **没有官方量化数据。** LightX2V 路线图原文 “Improve the visual quality and consistency of Ref2VA and FL2VA Turbo”，等于承认一致性还在改进。ComfyUI 文档：Turbo 的 “slightly softer motion/audio”，R2V turbo 的参考贴合更弱，需要贴合时用 20–25 步。
- 社区反馈：4 步“forces slow motion”（#36）；8 步运动更顺。8-step v1.0 有用户报告“手持物体自己动”“坐姿人物像瘫痪一样移动”（#16，可能和 Spectrum 节点有关）。
- 推断（中）：关键帧是作为 attention 上下文起作用的，步数少意味着模型校正“末段收敛到 Picture 2”的机会更少。**对必须精确落到尾帧的关键镜头，可以试基模 20–25 步不加 LoRA 作为对照组**，用来区分是蒸馏的问题还是输入或提示词的问题。

---

## 3. 漂移、脸糊、重影、落不到尾帧：已知原因与对策

| 症状 | 已知或可能原因 | 对策 | 置信度 |
|---|---|---|---|
| 尾帧附近重影、双重曝光 | ① 首帧被拉伸、尾帧被居中裁切，比例不是 9:16 时两帧几何不一致；② 首尾帧的景别、机位、光照差距太大，模型只能“溶解”过去；③ 跳步缓存（EasyCache、Spectrum），note.com 的对比实验显示 EasyCache 开启时轮廓变双、画面融化 | ① 两帧都在本地先用同一方式 center-crop 到 768×1344 再上传；② 首尾帧来自同一套 Qwen 生成链，保持同景别、同光照，尽量只改姿态和表情；③ 关掉所有缓存加速 | ①高（机制）/ ②中 / ③中 |
| 脸糊、脸崩 | 官方承认的模型问题（HF #87，MiniMax 员工回复“目前正在系统性解决”）；远景小脸最严重（Comfy #30）；高分辨率时提示词贴合下降（#65） | 少用远景，人物至少中景、脸占画面比例要大；保持约 1MP（768×1344 正好）；固定种子多抽几次挑；关缓存 | 中 |
| 漂离首帧 | 中文正文、不规范的提示词（没有对齐句，又复述静帧描述）；提示词里的动作和尾帧矛盾；运动幅度太大 | 按 §1.3 模板写；只写能连通两帧的路径；一个主动作 | 中-高 |
| 落不到尾帧 | 提示词没写“settles into … established by Picture 2 at the end”；首尾帧差距超过 10 s 内连续动作能完成的范围；Turbo 一致性不足 | 加收敛句；减小首尾差距，或拆成两个镜头；或者加 `MiniMaxH3AddGuide` 中间帧；关键镜头用基模 20–25 步做对照 | 中 |
| 镜头间色调跳变 | Comfy #67 报告高分辨率（≈1.3MP）下中段整体变暗，这是种子相关的色调偏差；我们是 1MP，风险较低。VAE 编解码也会带来色偏（HF #78） | 用 euler（比其他采样器轻）；成片后对相邻镜头做颜色匹配（我们已有 `grade.py`）；关键帧统一调色 | 低-中 |
| 音频破音（顺带） | ancestral/SDE 采样器（ComfyUI issue #15283） | 用 euler | 中 |

需要说明的几点：
- **4n+1 规则不适用于 H3**，它用的是 17k+5，ComfyUI 会自动对齐。
- **context window 不适用**：243 帧一次生成，在训练范围之内。
- **分辨率不匹配**：画布已经是 768×1344，唯一的风险是输入图比例不对（见上面第 ① 条）。

---

## 4. 新变体、LoRA、节点

| 名称 | 说明 | 对我们是否有用 | 置信度 |
|---|---|---|---|
| LightX2V FL2V Turbo 8step **v1.1 768p** / 4step v1.3 768p | 最新官方蒸馏，shift 6/3 | **建议试** | 高 |
| FastH3 8-Step V2（FastVideo，DMD2） | 模型卡写明 FL2VA/Ref2VA “were not distilled”，只支持 T2VA | **不适用** | 高 |
| alibaba-pai **MiniMax-H3-Acc-LoRAs**（PDD，FL2VA 8 步，rank 64，演示用的是 768p） | 另一种 8 步蒸馏；没有贴合度相关数据 | 可以作为备选 A/B | 中 |
| `MiniMaxH3AddGuide`（ComfyUI 原生） | 任意帧锚点，可以加中间关键帧 | 适合“必须经过某个姿态”的镜头 | 中 |
| 把 Ref2V Turbo LoRA 用在 FL2VA 模型上 | 社区意外发现身份更稳（#40；#91 测得 InsightFace 相似度 0.886），代价是画面偏糊 | 可以小规模试 | 低 |
| H3-Regenerate-2K | 未开源，只有 API | 不可用 | 高 |
| `MiniMaxH3LatentUpscaleWithModel`（原生） | latent 放大 | 和一致性无关 | — |
| ComfyUI-ALLinONE-MinimaxH3 “H3 Identity Anchor” | 本质上就是首帧或尾帧锚点，没有额外的身份机制 | 无增益 | 中 |
| Licon VBVR LoRA | 据称修复物体重复和穿模；没找到 HF/GitHub 链接 | 无法核实 | 低 |
| 身份 LoRA（专门针对 FL2VA 的） | **没找到** | — | — |
| ToneCompensate（rkfg） | Comfy #67 提到过；**没找到这个仓库** | — | — |
| WanGP 的 FL2VA 重影 issue | 搜索摘要里提到过，**没能打开或核实** | — | — |

---

## 5. 建议的 A/B 实验顺序（交给 owner 决定，我没有执行）
1. 固定种子和关键帧，只改提示词：中文现格式 vs 官方英文 FL2VA 格式。
2. 输入预处理：原图直接上传 vs 两帧都 center-crop 到 768×1344。
3. LoRA/shift：v1.0-544p@6/3（现状）vs v1.0@12/3 vs v1.1-768p@6/3 vs 基模 20 步无 LoRA。
4. 确认 gpu3 上没有挂任何缓存或加速节点，采样器是 euler/simple。

## 6. 没找到或无法核实的内容
- 官方 Context-IR 的系统提示词（没开源）。
- 官方关于“尾帧强度”或 noise-aug 的任何参数（源码里没有）。
- 8 步蒸馏对尾帧贴合度的量化评测。
- rkfg ToneCompensate 仓库、WanGP 的 FL2VA 重影 issue 原帖、Licon VBVR 的仓库。
- kijai 的 H3 专用 wrapper：没找到 GitHub 仓库；Kijai 在 HF 上只提供 LoRA 和量化文件（`Kijai/MiniMax-H3_comfy`）。

## 7. 来源清单
- 官方：<https://huggingface.co/MiniMaxAI/MiniMax-H3>、<https://github.com/MiniMax-AI/MiniMax-H3>、指南 `docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md`、`FL2VA/model_index.json`
- ComfyUI 源码：<https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py>、`comfy/ldm/minimax/model.py`
- ComfyUI 文档：<https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native.md>、`minimax-h3-multiframe.md`、`minimax-h3-prompt-guide.md`
- SGLang：<https://docs.sglang.io/cookbook/diffusion/MiniMax/MiniMax-H3>；vLLM：<https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3>
- LightX2V：<https://github.com/ModelTC/Minimax-H3-Turbo>、<https://github.com/ModelTC/LightX2V/blob/main/scripts/minimax_h3/README.md>、<https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions>（#16 #36 #40 #42 #44 #48 #52 #57）
- 讨论：MiniMax HF #65 #79 #87 #91 #114；Comfy-Org HF #30 #67；ComfyUI issue #15283
- 其他：<https://huggingface.co/FastVideo/FastVideo-FastH3-8-Step-V2>、<https://huggingface.co/alibaba-pai/MiniMax-H3-Acc-LoRAs>、note.com 融化对比 <https://note.com/seal309midorin/n/nd4744caef27e>、<https://comfyui-wiki.com/news/2026-08-11-minimax-h3-turbo-lightx2v-v1>
