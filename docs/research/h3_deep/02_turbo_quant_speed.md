# H3 深度调研 02：蒸馏/Turbo LoRA、量化与 4×3090 提速

调研日期：2026-10-30。只读调研：没装东西，没用 GPU，没 ssh。
按 owner 2026-10-30 的指示，**以真实用户实跑反馈为主要标准**，官方文档只作背景。每条设置都记了“几个独立用户确认 / 硬件 / 模式 / 反对意见”。

置信度：**高** = 官方原文或源码；**中** = 多个独立社区来源一致；**低** = 只有一个帖子，或是我自己的推断（会注明“推断”）。
引用说明：WebFetch 工具单条引文最多约 125 字符，长帖只能分段摘句；凡是“转述”都已标明。

---

## 0. 结论速览（按社区共识排序）

| # | 结论 | 社区确认情况 | 置信度 |
|---|---|---|---|
| 1 | **步数 ≥6，最好 8。4 步会出现慢动作、拖影、蜡化和音频问题** | ≥8 个独立用户（lightx2v #36/#52、larry #20/#26、两个 GitHub 实测仓库）。反对意见只有“4 步适合做 hires-fix 第二遍” | 中-高 |
| 2 | **3090 用 INT8 ConvRot（pruned 版约 21 GB）**。Ampere 上 FP8 是软件模拟，不要用 | Kijai 和另一位用户直接答 3090 选 “int8”；3090 日志显示 int8 原生、fp8 模拟；两个 4×3090 实测仓库都用 pruned int8。反对：1 条早期 A100 报告说 int8 比 fp8 慢 3 倍 | 中-高 |
| 3 | **4×3090 跑一条视频，最快的已验证路径是序列并行**：ComfyUI 下用 Raylight（USP/Ulysses），或 LightX2V 的 TP2×SP2 | 2 个独立 4×3090 实测：Raylight 87.4→28.0 s/step（3.12×）；LightX2V 双卡 656 s→四卡 451 s 去噪 | 中 |
| 4 | **关掉 EasyCache 和 Spectrum**（会造成重影、融化、画面乱掉）。Sol-Attn 是近似计算，不是无损 | EasyCache 降质 2 人以上；Spectrum 弄坏输出 3 人以上；Sol-Attn 原仓库写明 “approximate” | 中 |
| 5 | Turbo LoRA 强度默认 1.0；**画面偏暗多是强度偏低，过曝/过饱和多是强度偏高** | 1.0 有 4 人以上支持；反对意见很分散（0.5、0.65、1.2–1.3、2.0、2.8 各有 1–2 人） | 中 |
| 6 | **最新的 FL2V 8step v1.1 768p（10-20 发布）还没有任何社区 FL2V 实测反馈**。上一代各版本的颜色评价互相矛盾 | 无 | — |
| 7 | 社区在 3090 上真正跑 FL2V 时，**用得更多的是 larryvrh v4_step600_ema（6–8 步、强度 1.0、shift 12/3）**，口碑是“近景脸更好”，代价是快速运动时拖影、暗场景色带 | 4 人以上说它脸更好；2 个 4×3090 仓库都选了它 | 中 |

**对我们现状的直接判断**：现在用的是 `Kijai .../minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16`。它是 **544p 版 8step v1.0 用 SVD 压到平均 rank 24** 的版本（高，见 §1.3），配的是 6/3 shift。这里叠了三层偏差：分辨率不匹配、shift 不匹配（官方给 v1.0 的是 12/3）、rank 压缩有损。建议 A/B 三个候选（见 §6）。

---

## 1. 官方 Turbo LoRA：版本与参数（背景）

### 1.1 HF 文件列表（实测 API，2026-10-30）
来源：<https://huggingface.co/api/models/lightx2v/Minimax-h3-Turbo/tree/main>

FL2V 相关的文件（`_comfyui_` 是给 ComfyUI 用的版本，约 1.96 GB；不带的是 diffusers/LightX2V 版，约 1.38 GB）：
- `fl2v_turbo_4step_v0.1`
- `4step_v1.0_768p`、`v1.1_768p`、`v1.1_768p_fp8`（34 GB，**这是整个蒸馏模型，不是 LoRA**，见 #55）、`v1.2_768p`、`v1.3_768p`
- `8step_v1.0`（544p）、`8step_v1.0_768p`、**`8step_v1.1_768p`**

各版本发布时间（HF commit API <https://huggingface.co/api/models/lightx2v/Minimax-h3-Turbo/commits/main>）：

| 时间 | 发布内容 |
|---|---|
| 08-07 | 4step v0.1 |
| 08-11 | 8step v1.0（544p）、4step v1.0 768p |
| 08-20 | 4step v1.1 768p |
| 08-27 | 8step v1.0 768p |
| 09-04 | 4step v1.2 768p |
| 09-10 | 4step v1.1 fp8 整模型 |
| **10-20** | “Release updated FL2V and REF2V BF16 and ComfyUI LoRAs”，即 **FL2V 4step v1.3、8step v1.1**、REF2V 4step v1.0 / 8step v1.1 |

### 1.2 官方给的参数
- GitHub 规格表 <https://github.com/ModelTC/Minimax-H3-Turbo>：544p 版的训练 shift 是 12/3，768p（1344×768）版是 6/3。**README 最后一次更新是 08-27，表里还没有 v1.1/v1.2/v1.3。** 原文：“Recommended settings: 8 NFE, video shift 6, audio shift 3”（Studio）。（高）
- 讨论 #57（官方，10-20 新版发布帖）原文：“For the new FL2V 4-step and 8-step LoRAs, we recommend using a video flow shift of 6 during inference.” <https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/57>（高）
- 讨论 #48（8step v1.0 768p 发布帖）：8 步、6/3、Euler、Simple；原文 “These settings produced the best overall balance of video quality, motion consistency, and audio quality in our testing.” <https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/48>（高）
- 讨论 #52（4step v1.2）原文：“Compared with v1.1, this release focuses on improving the audio generation quality”。也就是说 v1.2 只改了音频。（高）
- 讨论 #42（4step v1.1）：6/3、4 步、euler；原文 “These settings are specifically recommended for this v1.1 checkpoint.”（高）
- **官方从来没写过 LoRA 强度。** #48 里 iamXinc 问 “Lora strength = 1.0?”，没人回答。（高：确实没写）
- LightX2V 脚本 README <https://github.com/ModelTC/LightX2V/blob/main/scripts/minimax_h3/README.md>：LoRA 示例是 `infer_steps` 4、`video_flow_shift` 6.0、`audio_flow_shift` 3.0。对量化权重的说明原文是 “Apply the adapter during inference; merging into quantized DiT weights is unsupported.”（高）

### 1.3 Kijai 的转换版（就是我们在用的）
来源：<https://huggingface.co/api/models/Kijai/MiniMax-H3_comfy/tree/main/loras>（高）
- `minimax_h3_fl2v_lightx2v_turbo_8step_v1.0_resized_avg_rank_24_bf16.safetensors`（365 MB）。原版 comfyui 文件是 1.96 GB，所以这是一个 **SVD 重采样到平均 rank 24 的有损压缩版**，源头是 **544p** 的 8step v1.0。
- 另有 `4step_v1.0_768p_resized_avg_rank_31`。**Kijai 没有发布 8step 768p 或 v1.1 以后版本的压缩版。**
- Kijai 模型卡原文：“Not 100% sure of the intended alpha.” 讨论 #3 中 Kijai 说转换做了 “fused QKV / key renaming / add alpha to match peft strength”。<https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/3>
- **更正旧文档**：旧文档说 `minimax_h3_fl2va_pruned_w4a8_mixed` 是“Kijai 的模型”。实际查 `Kijai/MiniMax-H3_comfy` 的文件列表，**里面没有这个文件**。这个说法只来自 #48 里 kingp0dd 的一句 “seems to be not compatible with kijai's model … it only works with int8 convrot”，出处没法核实。（低）

---

## 2. 社区对各 Turbo 版本的实测反馈（主要依据）

### 2.1 步数：4 步 vs 6–8 步 vs 基模 20 步以上

| 用户 / 来源 | 原话 | 硬件 / 模式 |
|---|---|---|
| Rkss，lightx2v #36 | “The lora tends to force slow motion on everything.”；“8 steps loras's motion is smoother” | 未说明 |
| ApexArtist，#36 | “also in fast motion the details become wax melting” | 未说明 |
| g2t2，#52 | “why do we push for 4 step? Can we keep it at 8 step please?”；“His hair is way worse.”（指 v1.2） | — |
| DaviKar，#52 | “When looking at the samples it looks like the quality took a big hit in v1.2.” | — |
| Zuzuus，#52 | “every speedhacks degrade the models quality … why exagerate with just 4 steps?” | — |
| Gamb，larry #20 | “Forget about 4 step. 4 step is bad. Minimum is 6 steps.” | — |
| liuzhf，larry #20 | “The current 4 steps do not work; at least 6 steps are required.” | — |
| kangklx，larry #20 | 4 步“unusable”，6 步仍有色带/posterization（平涂蓝色区域）；后来换成 Turbo Sampler 后明显改善 | 4070 Ti S，pruned int8 |
| kipdg，larry #26 | “audio is bad at 4 steps … At 8 steps audio is perfect.” | — |
| A-M-D-R-3-W README | “the comfort zone for sharpness is 6–8 steps, not 4 (4 comes out softer)” <https://github.com/A-M-D-R-3-W/comfyui-minimax-h3-turbo> | — |
| alesha-pro（4×3090） | 从 20 步降到 6 步，建议 6–8，“stops helping past 8” <https://github.com/alesha-pro/tools> | **3090，1344×768** |
| larryvrh README | “4 steps is the recommended minimum; 4–8 is the useful range”；超过 8 步 “can start to introduce over-sharp artifacts” | 官方（社区 LoRA 作者） |

**反对意见**：TheDivergentAI（#52）用 4 步 LoRA 配 0.25 denoise 做 hires-fix 第二遍；ApexArtist（#54）把 v1.0 用在放大那一遍。也就是说，4 步只适合“精修”这种场景。

**和基模比**：
- 速度：sepiablue 实测 RTX 4070、576×832、124 帧、I2V，基模 20 步 272.97 s；LightX2V 8step v1.0 跑 8 步 131.02 s（2.08×）、跑 4 步 79.36 s（3.44×）；Larry v4 跑 8 步 130.30 s。<https://github.com/sepiablue-ai/minimax-h3-turbo-lora-benchmark>（中：单一来源，但给了实测数字）
- 画质：**找不到任何定量的脸/颜色评测**。jo-nike 的 25 配置评测页 <https://jo-nike.github.io/h3-turbo-eval/> 只有配置和场景，汇总页没写结论。multimodalart 的 H3 Acceleration Arena（盲测约 26 个加速变体，200 条 prompt）是**私有 Space**，排名看不到 <https://huggingface.co/spaces/multimodalart/h3-acceleration-arena>。lightx2v #51 里 kipdg 说 “all top 3 DARETIES turbo loras are at the top”，Meryruizk 说榜上 28 步无 Turbo 的基模排在所有 Turbo 之下。但 mobani 指出 “The benchmark you linked is only for FL2V”。（低：看不到原始数据）
- 社区的折中做法：awesome-H3 性能指南建议“先用 Turbo 出草稿，定稿再用同种子去掉 Turbo 重跑”（这是二手汇总）。

### 2.2 LightX2V 各版本的社区评价（FL2V 模型）

| 版本 | 正面 | 负面 |
|---|---|---|
| 4step v0.1（544p） | durpmen #20：“0.1 is better quality than 1.0”；samsss133：“0.1 works amazing, up to 1.5mega pixel”；kysmodels（larry #39）：只有 “.1 LightX and Larry's 600 EMA” 好看 | m8rr #38：“overcooked” |
| 8step v1.0（544p，我们在用的） | k3soft #16：“much better than 0.1!” | TheVisitorX #16：画质不如旧版、跪坐人物“like a zombie”、手持物自己上下动（同时开了 Spectrum，嫌疑在 Spectrum）；Chinga808 #16：“will you address the face distortion issue?” |
| 4step v1.0 768p | — | Privac #27：“The 544p versions works way better than the 768p, the latter giving an extremely over saturated plastic look, bad audio”（Euler/simple + 官方参数）；m8rr #38：“a bit weaker”，偶尔输出旋转 90° 的视频 |
| 4step v1.1 768p | TheVisitorX #42：“waaaaay better than the old 1.0 version”（强度 1.3、6 步）；gaga-lee97 #47：“minimax_h3_fl2v_turbo_4step_v1.1_768p fixed the color bias!”（v1.0 偏暖） | ApexArtist #42：“dark and high contrast”；ApexArtist #54：“1.1 seems too dark”；hanswurstwerner #42：1MP 下远处人脸 “look like they're in a horror movie”；illsung #42：1MP 4 步 “the audio still gets corrupted, and ghosting artifacts persist” |
| 4step v1.2 768p | MBen1986 #57：可以和 VEDA、稀疏注意力、其他 LoRA 一起用 | ApexArtist #54：“1.2 seems it changes the original too much”；DaviKar、g2t2 #52：画质掉了 |
| 8step v1.0 768p | Aorora12 #48：配 Hybrid 模型效果好 | yui7854 #48：“Does not work well with other Loras, and at lower screen resolutions(lower than 768p).” |
| **4step v1.3 / 8step v1.1（10-20）** | — | MBen1986 #57：v1.3 和 VEDA/稀疏注意力一起用 “severely degraded/unusable”，和其他 LoRA（Realism、Motion Repair）一起用也会坏；官方 gushiqiao 建议强度试 2.0，结果“更稳但不算好”。**8step v1.1 在 FL2V 下没有任何反馈**；Jazzyman 只反馈了 REF2V 8step 语音不连贯 |

**小结**：每一代都有人说更好、有人说更差，**颜色评价正好相反**（v1.1 有人说“修好了偏暖”，有人说“太暗、对比太高”；768p 有人说“过饱和、塑料感”）。没有一个版本在 FL2V 768p 上有压倒性的社区共识。（中：分歧本身是确定的）

### 2.3 larryvrh v4_step600_ema（社区变体）
- 仓库：<https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora>；节点：<https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo>
- 作者原文：“It's the strongest checkpoint we've released: much better static and small-motion shots”；“markedly better micro-detail (faces, fingers, fine texture)”；已知问题：“only at 4 steps with large, fast motion … motion-smear / trailing ghosting”。参数：**shift 12/3、强度 1.0、scheduler simple、4–8 步**。README 写的任务只有 T2V / I2V，**没提 FL2V**，但用的是 FL2VA 底模，社区也在 FL2V 场景下用。（官方→高；FL2V 适用性→中）
- 社区实测：
  - kipdg（larry #26）：“New 600-step V4 fixed my closeup face issues, it's perfect”；有 turbo 8 步 570 s，无 turbo 15 步 40 min
  - moon1143（larry #27）：“This LoRA is much better at rendering faces.”
  - marin73tomas（larry #39）：“the fastest and has the best quality I've seen so far at 6 steps”
  - kysmodels（larry #39）：同意只有它和 lightx2v 0.1 好看
  - 两个 4×3090 仓库（torenyx、alesha-pro）都选它做 FL2VA turbo
- 负面：
  - Sakujo（larry #26）：0.5MP、强度 1、8 步时，昏暗灰墙场景有色带，“like a color pallet is too narrow”
  - Rkss（larry #36，标题 “colorshift and oversharpen”）：1MP euler+simple 下第二个视频没有景深，还加了随机伪影；Rkss 建议 “Stay with 1.0 and Euler + beta”
  - A-2-H（larry #30）：会往画面里加 prompt 没要的东西（围巾、外套），v1 ckpt850 不会
  - ANe5s（larry #30）：low_vram 开着时画质明显下降
  - alesha-pro：stock loader 在多卡环境下 “loads zero keys” 并且静默失败，需要打补丁
- pruned 底模兼容性：Abiray 和 drbaph 都出了 pruned 转换版。Abiray 页面推荐的设置差别很大：video shift 12、audio shift 6、8–12 步、res_multistep、强度 0.8–1.8 <https://huggingface.co/Abiray/MiniMax-H3-Turbo-Lora-ComfyUI>（低）
- joyfox/MiniMax-H3-Turbo：一个 4 步 LoRA，shift 12/3、强度 1.0、Euler/simple、只做 T2V/I2V。它的讨论 #5 有人报告用文档指定的 `minimax_h3_fl2va_pruned_bf16` 会 shape mismatch。没有 FL2V 数据。<https://huggingface.co/joyfox/MiniMax-H3-Turbo>（低）

### 2.4 采样器 / scheduler

| 设置 | 支持者 | 反对或替代 |
|---|---|---|
| euler + simple | 官方 #48；FragmentY #17（“4-8steps（i prefer 6），and im using euler+simple”）；MrShibari #3；kipdg（larry #39）：“euler and simple is good across all turbo LoRAs” | Larry、Rkss 推荐 euler + beta；Meryruizk（#25）用 euler/res_multistep + simple/beta 都正常；rocky533 用 beta57 + er_sde 或 ddim/beta；Kijai 模型卡给的是 er_sde 或 sa_solver（4 步、强度 0.75） |

结论：euler + simple 和 euler + beta 都有 3 人以上在用，没有坏的报告。**要避开的是 ancestral/SDE 和 ClownsharK 系列**：Rkss 说 ClownsharK “shifts audio”、出 “machine-ish voice”（#41）；LCM/Beta 出过“ringing noises”（Comfy #26）。（中）

### 2.5 强度

| 强度 | 支持者 | 场景 |
|---|---|---|
| 1.0 | TawusGames #9：“Turbo LoRAs are used at strength 1.0.”；Larry 作者；alesha-pro；Rkss | 通用 |
| 偏低导致发暗 | sdqq1234 #9：0.75、4 步时颜色变暗；TawusGames：“Using Turbo LoRAs at low power causes the colors to become darker.”“Using them at high power … causes the colors to blow out.” | — |
| 1.2–1.3 | hanswurstwerner、TheVisitorX（#42，4step v1.1） | 1MP |
| 0.5 | MrShibari #3/#6：把 4 步 LoRA 跑 8 步时用 0.5；Meryruizk #16：0.5 和 1.0 都行 | 步数多于训练步数时 |
| 0.65 | inykokso #42：强度 1 时 i2v 几乎不跟 prompt、几乎不从首帧出发，0.65 才正常 | **和首帧贴合直接相关** |
| 2.0 | gushiqiao（官方）#57：建议 v1.3 试 2.0 | — |
| 2.8 | rocky533（Comfy #30）：“2.8 strength lora 4 steps 1.0MP works really well. face is clear” | 4 步 |

结论：**用和训练步数相同的步数时，从 1.0 起步**。如果首尾帧贴合差，就往下试 0.8 / 0.65；如果发糊、重影，就往上试 1.1–1.2。（中）

---

## 3. 量化：3090（Ampere，sm86）该用哪个

### 3.1 硬件事实
- 3090 实机日志（tonyd2wild）原文：“Native ops: convrot_w4a4, int8_tensorwise , emulated ops: float8_e5m2, float8_e4m3fn, nvfp4, mxfp8”；“Weights stay packed at their quantised size; only speed suffers.” <https://github.com/tonyd2wild/minimax-h3-local>（高：日志原文）
- 也就是说，**3090 上 INT8（含 ConvRot）走原生 int8 tensor core，FP8/NVFP4/MXFP8 都是软件模拟**。
- Comfy-Org 官方模型卡原文：“For diffusion models prefer `int8_convrot` if you are able to use pytorch with cu130.”；“`fp8_scaled` should only be used if you cannot use `int8_convrot`.” <https://huggingface.co/Comfy-Org/MiniMax-H3>（高）
- ComfyUI issue #14722（不是 H3 专属）原文：“INT8-ConvRot outperforms traditional FP8 in both speed (especially on RTX 30-series)” <https://github.com/Comfy-Org/ComfyUI/issues/14722>（中）

### 3.2 社区确认
- Comfy-Org #18，enwong 问 “How about my RTX 3090 for running H3? Q4/Q2 or INT8 which version”。azra1l 答 “int8”，**Kijai 答 “Int8 indeed.”** <https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/18>（中-高）
- 两个 4×3090 实测仓库都用 **pruned INT8 ConvRot**：torenyx 原文 “pruned INT8 ConvRot”；alesha-pro 原文 “pruned int8 base”。（中）
- Araskijo（lightx2v #24）：LoRA 在 pruned 的 int8_convrot 和 fp8 上都能用，nvfp4 上不行。
- kingp0dd（#48）：8step 768p 只能配 int8 convrot，配 w4a8_mixed 不行。
- **反对意见**：DavidGuo2024（Comfy #5，08-03，A100 sm80）：“our A100:SM80 is approximately three times slower in int8 convRot compared to fp8.” 这是发布初期的报告，当时 kernel 可能还不完善，3090 上没人复现。（低）
- refaelskira（Comfy #26，4090）：FP8 模型 “slower sampling”。

### 3.3 文件选择（Comfy-Org 文件列表 <https://huggingface.co/api/models/Comfy-Org/MiniMax-H3/tree/main/diffusion_models>）

| 文件 | 大小 | 在 3090 上 |
|---|---|---|
| fl2va_bf16 | 66.3 GB | 放不下 |
| fl2va_int8_convrot（非 pruned） | 34.0 GB | 单卡放不下，要 offload，或多卡 FSDP |
| **fl2va_pruned_int8_convrot** | **21.0 GB** | **单卡能放下，社区 3090 的主流选择** |
| fl2va_pruned_fp8_scaled | 21.0 GB | 能放下但 fp8 是模拟，慢 |
| fl2va_pruned_w6a8 | 16.0 GB | 3090 上没有反馈 |

- **“pruned”具体剪了什么，官方没写**（Comfy-Org 模型卡 “does not explain what pruned … means”）。有用户说 Turbo LoRA 在 pruned 底模上需要处理 adaln 层：alesha-pro 写 “51 adaln at run time” 时要重新注入；Larry 节点写 “works with … the pruned/curve variants”。**pruned 相对 full 的画质损失没有任何定量数据。**（低）
- GGUF：二手汇总说 “Q5_K_M suits 24 GB (RTX 3090 / 4090)” 并且 “closest to full quality on consumer cards”，原始出处我没核实。3090 上的 GGUF 实测速度**没找到**。GGUF 在 3090 上是反量化后再算，通常比原生 int8 慢（推断，低）。
- 视频 VAE 用 int8：zenn 在 3090 上实测（Turbo 8step LoRA 跑 6 步、SageAttention、I2V），整体 95.3 s→80.2 s，VAE 解码 24.9→14.5 s；“Per-frame PSNR against the fp16 output was 56.7dB”，色相变化测不出来。<https://zenn.dev/nanora/articles/20260929-minimax-h3-int8-vae-rtx3090?locale=en>（中：单人，但有定量数据）。**反对**：minanimator（Comfy #30）问 “does kijai's new vae makes the visual kinda weird and plastic looking?”；rzgar（larry #17）建议用 bf16/fp32 VAE。awesome-H3 的指南说 **Audio VAE 必须保持 fp32**，否则音画不同步（二手）。

---

## 4. 4×3090 跑单条视频的提速方案

### 4.1 多卡并行（真正能拆一条视频的）

| 方案 | 实测 | 是否无损 | 置信度 |
|---|---|---|---|
| **Raylight（ComfyUI，USP/Ulysses 序列并行）** | alesha-pro：4×3090、PCIe 3.0 x16、无 NVLink、1344×768、pruned int8、Larry v4。每步耗时：1 卡 87.4 s、2 卡 36.0 s（2.43×）、4 卡 28.0 s（3.12×）；15 s 镜头采样 19 min → 6:41，整体 22:05 → 15:16 | 作者没说。Ulysses 在数学上等价于完整注意力，只有数值舍入差异（推断） | 中（单个实测来源 + Raylight 官方支持表） |
| LightX2V TP2×SP2 | torenyx：3090 上 FL2VA Turbo（Larry v4、6 步、15 s、1344×768、pruned int8、SageAttention2），4 卡去噪 450.77 s / 总 9:29，2 卡去噪 656.49 s / 总 13:27 | 没说 | 中 |
| AesSedai ComfyUI-MiniMaxH3-Parallel（注意力头切分） | 4×RTX PRO 6000：去噪 2.02×，端到端 1.39× | **“Exact”，四个输出的 SHA-256 一致**。但只支持 Ref2VA，并且要求 Comfy Kitchen INT8 注意力 | 高（对 Ref2VA）/ FL2VA 不可用 |
| SGLang（Ulysses/Ring/TP） | 只有 B200/H200 的数据；原文 “Ampere and Ada are enabled but not benchmarked.” <https://docs.sglang.io/cookbook/diffusion/MiniMax/MiniMax-H3> | 原文 “Online FP8 is approximate”；单张 24 GB 卡建议 `convrot_int8` | 高（文档）/ 3090 上没验证 |
| ComfyUI-MultiGPU / 把 TE、VAE 挪到第二张卡 | 只是卸载，不并行；tonyd2wild：“ComfyUI has no tensor-parallelism for diffusion”，并且把 TE 放第二张卡会出**全黑视频**；Comfy 讨论 #15692 两位用户说多卡用不起来 | — | 中 |

- Raylight 支持表：“H3 Ref2VA and H3 FL2VA support USP and FSDP but not CFG”（H3 本来就是 cfg 1，CFG 并行对它没用）；“Full LoRA support”；警告 “GPU Topology is very important, not all PCIe in your motherboard is equal”；Ring>1 会泄漏显存，建议 Ulysses=GPU 数、Ring=1。<https://github.com/komikndr/raylight>（高）
- **注意**：Raylight 文档没提 int8 convrot，但 alesha-pro 实测用的是 pruned int8 base；Raylight 依赖的 torch 版本比当前 ComfyUI 旧，alesha-pro 是装在独立目录里跑的；LoRA 需要他仓库里的补丁，否则静默加载 0 个 key。**我们用 lightx2v LoRA 走 Raylight 时，必须核对日志里 LoRA key 确实加载了。**（中）
- `dszafranski95/minimax-h3-dual-3090` 的 README 里写有给 AI agent 的指令，没有给技术数据，**不可信，不采用**。

### 4.2 单卡加速：注意力和缓存

| 方法 | 原始出处怎么说 | 社区反馈 | 对 FL2V / 脸 / 颜色的风险 |
|---|---|---|---|
| SageAttention 2 | 官方说支持 Ampere，“without losing end-to-end metrics”，没写 3090 用哪个 kernel <https://github.com/thu-ml/SageAttention> | LyricalPepper（Comfy #26）：“KJ's sage attention patch is a must.”；torenyx 在 3090 上用 Sage2；Meryruizk #16：画质问题不是 Sage 造成的 | 近无损（中） |
| **Sol-Attn** | **原仓库原文 “Sol-Attn is approximate.”**；tau 越高越快、越失真；v0.6.2 起支持 SM86，但 “not yet benchmarked” <https://github.com/Saganaki22/ComfyUI-sol-attn> | LyricalPepper：提速 15–20% | **更正**：awesome-H3 指南说它 “bit-identical verified”，和原仓库矛盾，以原仓库为准。有损（高） |
| Comfy Kitchen 注意力 | — | 3060 上提速 20–30%（二手）；bhengen 实测 5090 无提升（Comfy #26） | 3090 没数据 |
| EasyCache / MiniMaxH3-Cache | — | 010O11（Comfy #30）：“Using 'EasyCache' node also degrades the quality of the final result.”；note.com 对比显示轮廓变双、画面融化（旧文档）；awesome 指南说 “Cannot combine with Turbo LoRAs” | **有损，FL2V 关掉**（中） |
| Spectrum | — | UsoAiparalacufa #25：Spectrum 没关干净，把输出全毁了；TheVisitorX #16 出问题时开着 Spectrum；Hellomattieo（Comfy #26）开了反而慢一倍；指南说步数少时几乎没用 | **有损，关掉**（中） |
| Cache-DiT | SGLang 原文 “Cache-DiT skips selected block computation and is approximate.”；二手数据 SSIM 0.881 | — | 有损（高） |
| torch.compile | AesSedai：只快约 1.5%，并且 “diverged substantially from the eager trajectory” | refaelskira：4090 上 OOM | 不建议 |
| 功耗墙 | alesha-pro：220 W → 320 W 让单次运行从 220 s 降到 170 s | — | 无损，**最便宜的提速** |

---

## 5. 已知的颜色、饱和度、脸部问题与对策

| 现象 | 社区来源 | 对策 | 置信度 |
|---|---|---|---|
| 画面整体偏暗、发灰 | sdqq1234 #9（强度 0.75）；ApexArtist #42/#54（4step v1.1） | 强度回到 1.0；换版本做 A/B；用 prompt 写明自然色调（Smite79 #42：“Don't rely on the LoRA alone.”） | 中 |
| 过饱和、塑料感 | Privac #27（4step 768p v1.0）；Larry v1 系（作者自己承认有 “over-sharpening / plastic look”） | 换版本；强度不要超过 1；Larry 用 v4 | 中 |
| 偏暖（相对 20 步基模） | gaga-lee97 #47：自己训练的 4 步 LoRA 和 v1.0 都偏暖，v1.1 修好了 | 用 v1.1 及以后的版本 | 低 |
| 暗场景色带、色阶断层 | Sakujo（larry #26，v4）；kangklx（larry #20，6 步、pruned int8） | 加步数；后期去色带 | 低-中 |
| 8 s 以上嘴唇发红 | hugorejes #53（无人回复）；Comfy #55（Ref2VA 脸颊红斑） | 后期做颜色匹配 | 低 |
| 远景脸崩 | Comfy #30，多人；hanswurstwerner #42 | 中近景；约 1MP；关缓存；面部局部 V2V 重绘（0.15 denoise） | 中 |
| 近景脸 | Larry v4 有 4 人以上说更好；lightx2v 8step v1.0 有人报告脸部扭曲（#16） | A/B Larry v4 | 中 |
| 9:16 上半画面重影 | lvfengchun #44（ref2v turbo），16:9 正常；**反对**：Jam747 #38 说竖屏效果“way better” | 我们是竖屏，务必用固定种子对比 | 低 |
| 量化造成的颜色问题 | int8 VAE 实测 PSNR 56.7 dB，无色差（zenn）；**DiT int8 vs bf16 的颜色对比没找到** | — | 低 |

---

## 6. 给我们的可执行建议（需要 owner 拍板 A/B，我没有执行）

1. **先确认 gpu3 实际加载了什么**：底模是 pruned int8_convrot 还是 w4a8；LoRA 是 Kijai rank-24 的 544p v1.0；shift 节点 `ModelSamplingMiniMaxH3`（旧名 `MiniMaxH3SigmaShift`，见 #42 TheVisitorX：“SigmaShift was the old name”）的实际取值。
2. **LoRA A/B（固定种子，768×1344，243 帧，同一组首尾帧，euler/simple，cfg 1）**：
   - A：现状（Kijai rank-24 8step v1.0 @ 6/3）
   - B：`minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16` @ 6/3、8 步、强度 1.0（官方最新，社区还没验证）
   - C：`minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16` @ 6/3、8 步、强度 1.0（有 1 个多月的社区使用）
   - D：larryvrh `v4_step600_ema`（pruned 底模用 drbaph 或 Abiray 的转换版）@ **12/3**、8 步、强度 1.0、euler/simple 或 beta（3090 社区的实际选择）
   - E：基模 20–25 步、无 LoRA（对照组）
   - 每组看：尾帧贴合（最后几帧和尾帧比 SSIM/PSNR）、脸（InsightFace 相似度）、整体亮度和饱和度均值（对比 E）。首帧不贴合时把强度降到 0.8 / 0.65 再看。
3. **4 步不用于成片**，只可以用作 hires-fix 或草稿。
4. **量化**：3090 上统一用 `fl2va_pruned_int8_convrot`，不用 fp8/nvfp4；视频 VAE 可以用 int8（−16% 时间，无可见差异），音频 VAE 保持 fp32。
5. **多卡**：在一台测试机上试 Raylight（Ulysses=4、Ring=1），先用 bf16/int8 跑一条，和单卡结果比逐帧 PSNR，确认差异只是数值噪声；同时确认 LoRA key 确实加载了。备选方案是 LightX2V TP2×SP2（要脱离 ComfyUI）。另外把 4 卡功耗墙调到 320 W 左右。**如果多卡调不通，退路是 4 张卡各跑一个镜头（数据并行），总吞吐不受影响。**
6. **关掉 EasyCache、Spectrum、Cache-DiT、Sol-Attn 和 torch.compile**；SageAttention 2 可以保留（近无损）。

---

## 7. 没找到或无法核实的内容
- **Reddit 原帖（awesome-H3 指南列的 17 个 r/StableDiffusion 帖子）全部打不开**：工具被 reddit 屏蔽。所以指南里的说法（例如 GGUF Q5_K_M 适合 24 GB、EasyCache 不能和 Turbo 一起用）只能算二手。Civitai 评论也没查。
- Alexey Fateev 在 X 上的 4×3090 指南（x.com 返回 402）。
- H3 Acceleration Arena 的排名（私有 Space）；jo-nike 评测的逐场景结论；sepiablue 的画质对比文件夹。
- **8step v1.1 768p、4step v1.3 在 FL2V 上的任何社区实测**；v1.3 相对 v1.2 改了什么（#57 有人问，官方没回答）。
- 官方 v1.0 → v1.1 的训练差异（#47 没人回答）。
- “pruned” 到底剪了什么，以及 pruned 相对 full 的画质损失。
- 3090 上 GGUF / FP8 / INT8 的速度对比（只有 A100 一条反向报告和一些非 H3 数据）。
- Raylight 或 LightX2V 多卡输出和单卡是否逐位一致（只有 AesSedai 的 Ref2VA 证明了一致）。
- `Abiray` 单独发布的 pruned LoRA 的 rank 和训练来源；`A-M-D-R-3-W` 仓库没写 FL2V 和强度。
- silveroxide 的 DARE-TIES 合并 LoRA（#51 被认为是 Arena 前三）没有找到下载链接。

## 8. 来源清单
- 官方：<https://github.com/ModelTC/Minimax-H3-Turbo>（commits API）、<https://huggingface.co/lightx2v/Minimax-h3-Turbo>（tree/commits API）、LightX2V README 和 commits <https://api.github.com/repos/ModelTC/LightX2V/commits?path=scripts/minimax_h3>
- lightx2v HF 讨论：#2 #3 #6 #9 #16 #17 #20 #22 #23 #24 #25 #27 #32 #36 #38 #40 #41 #42 #44 #46 #47 #48 #51 #52 #53 #54 #55 #57 #58（<https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/N>）
- larryvrh HF 讨论：#17 #20 #26 #27 #30 #36 #39（<https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora/discussions/N>）
- Comfy-Org HF：模型卡、文件列表、讨论 #5 #18 #26 #30 #35 #41 #63
- Kijai：<https://huggingface.co/Kijai/MiniMax-H3_comfy>
- 社区仓库：Larryvrh 节点、A-M-D-R-3-W、joyfox、Abiray、alesha-pro/tools、torenyx/minimax-h3-inference-lab、tonyd2wild/minimax-h3-local、sepiablue 基准、jo-nike 评测、zenn int8 VAE 3090、AesSedai Parallel、komikndr/raylight、Saganaki22 sol-attn、kijai SolAttn_triton、lihaoyun6 Cache、thu-ml SageAttention、SGLang cookbook、ComfyUI issue #14722、ComfyUI discussion #15692
- 二手汇总（只用来找线索）：<https://github.com/wildminder/awesome-minimax-H3> 及其 guides/minimax-h3-performance.md；AlphaSignal / hermes-ai 新闻页
