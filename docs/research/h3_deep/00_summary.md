# H3 深度调研汇总（以社区实测为准）

> 2026-10-30。三份原始报告：01_official.md（官方）、02_turbo_quant_speed.md（加速 LoRA / 量化 / 多卡）、03_comfy_community.md（ComfyUI 与社区反馈）。
> 排序标准：项目方要求“以社区反馈为准”，按独立用户实测数量排序；官方只作背景。
> **缺口**：Reddit、Civitai 评论、X 工具无法访问，社区证据来自 GitHub issue、HF 讨论区、note.com、节点 README。Reddit 需浏览器补读。
> 本文只是调研结论，未在 gpu3 上执行任何改动；所有改动需项目方点头后由 gpu3 会话做 A/B。

## 一、先查清：gpu3 实际加载的是什么（最可能的现成 bug）

| # | 疑点 | 社区证据 | 置信度 |
|---|---|---|---|
| 1 | 我们的 turbo LoRA 是 Kijai 的 `8step_v1.0_resized_avg_rank_24`：来自 544p v1.0、训练 shift 12/3 却跑 6/3、rank 压缩有损，Kijai 自己写“不确定 alpha” | 02 | 高 |
| 2 | 底模若是 `w4a8_mixed`：ComfyUI #16420 代码级分析，LoRA 的 adaln_proj 补丁**静默不生效**；另 2 人说 768p turbo LoRA 只在 int8 convrot 上有效 | 03 | 中 |
| 3 | 多卡 Raylight 的原版 LoRA loader 曾静默加载 0 个 LoRA key，必须看日志确认 | 02 | 低-中 |
| 4 | 完整 INT8/BF16 权重每 17 帧暗一帧（约 −30 亮度）；pruned 版无此问题 | 01、03（2 人） | 中 |

**gpu3 核实结果（2026-10-30 晚，claude-gpu3 只读汇报）：疑点 1、2 不成立。** 底模是 `minimax_h3_fl2va_pruned_int8_convrot`（非 w4a8，#16420 不适用；pruned 版也避开了疑点 4）；turbo LoRA 今天起是官方 `8step_v1.1_768p_comfyui_bf16` 强度 1.0（ep01 旧片用官方 `8step_v1.0_768p`，不是 Kijai rank-24 544p 版），shift 6/3 与官方表一致；euler 8 步（无 turbo 时 res_multistep 20 步）；ComfyUI 0.42.0（2026-10-28，含 #16436）；无 `--fast`、无任何缓存/Sol-Attn/torch.compile；SageAttention 2.2 已装未用。仍未核实：LoRA 实际加载的 key 数（日志级别不打印）。
→ 因此剩下的真实问题集中在：颜色偏离锚帧、远景小脸、10 秒镜头漂移，以及 v1.1 尚无社区 FL2V 实测。

原请 gpu3 报告的清单：底模文件名、LoRA 文件名与强度、ModelSampling shift 值、采样器/步数、ComfyUI 启动参数（是否 `--fast fp16_accumulation`）、是否开了 EasyCache/Spectrum/TeaCache/Sol-Attn/torch.compile、ComfyUI 版本是否 ≥ 2026-09-22（VAE 分块接缝修复 PR #16436）、日志里 LoRA 加载的 key 数。

## 二、按社区共识排序的改动建议

### 速度 / 稳定（共识强）
1. **步数至少 6，建议 8**；4 步慢动作、“蜡融化”、重影、音频差（8+ 人）。
2. **关掉 EasyCache / Spectrum / Cache-DiT / Sol-Attn（有损）/ torch.compile**；SageAttention 2 可留（5+ 人一致，无反对）。
3. **3090 用 `minimax_h3_fl2va_pruned_int8_convrot`**（21 GB，单卡放得下）：3090 日志显示 INT8 原生、FP8/NVFP4 是软件模拟（慢）；Kijai 回答“Int8 indeed”；两台公开 4×3090 机器都用它。视频 VAE 可用 int8（95→80 s，PSNR 56.7 dB），音频 VAE 必须 fp32。
4. **4×3090 出一条视频：序列并行（Raylight / Ulysses）**：一位 4×3090 用户 87.4→28.0 s/步（3.12×），15 s 镜头采样 19 分钟→6 分 41 秒。我们只有 3 张好卡（GPU2 故障），按 2–3 卡估算（2 卡约 2.4×）。
5. 显卡功耗上限 220→320 W：一次 220 s→170 s（1 人）。
6. 先用低分辨率（352–576p）试构图，满意再出 768p：多人报告低分辨率下贴首尾帧反而更好（HF#65，中）。

### 加速 LoRA 版本（社区未定论，需 A/B）
- 3090 用户实际用于 FL2V 的是 larryvrh `v4_step600_ema`：6–8 步、强度 1.0、shift 12/3、euler simple/beta；≥4 人说近景脸更好；代价是快速运动拖影、暗场色带。
- 官方最新 FL2V `8step v1.1 768p`（2026-10-20 发布）**还没有任何社区 FL2V 实测**；官方参数 shift 6/3、8 步、euler/simple。
- 强度从 1.0 开始；首尾帧贴合差时试 0.8 → 0.65（1 人 0.65 修好）。

### 颜色（≥6 人确认 H3 会偏离锚定帧：偏暖偏灰、对比上升、变暗或肤色发紫，非 turbo 也有，模型侧无人解决）
1. **后期逐镜校色到我们自己的调色关键帧**（三个项目一致的做法）：逐通道增益+偏移，或人物区域 LAB 统计匹配（一项目测 dE 4.2→1.9）；不用 LUT / 硬直方图匹配。FL2V 可按首帧、尾帧两端偏差线性插值校正（推断，待验证）。
2. 768×1344 属于变暗风险区（HF#67：768×960 以上 I2V 前 1.5 s 起变暗 10–25 亮度）；rkfg ToneCompensate 节点 README 也承认“H3 会比锚帧暗”。
3. 采样器优先 euler（1 人测得变暗减半）；turbo 强度保持 1.0（低→暗、高→过曝，有分歧）。
4. 去掉 `--fast fp16_accumulation` 试一次（2 人说参考保真度变好，1 人无效）。
5. 不用 Sol-H3-VAE 做皮肤近景（128 px 网格接缝 issue 未关）。
6. 对比/校色时用 ComfyUI 原生视频加载，不用 VHS（2 个来源）。

### 人物一致性
1. **脸要大**：远景、小脸、快动作脸崩（≥6 人；官方 8 月说在修，至今无更新）。保持中景及以上，约 1 MP。
2. **镜头可缩短到 6 秒内**（官方 skill 的漂移对策）；我们现在每镜 10 秒。
3. **Ref2VA + AddGuide 锁首尾帧 + 角色卡参考**：官方 ComfyUI multiframe 模板就是这个结构（高）；一用户测 33.3 dB / SSIM 0.993，人物转身后脸能从角色卡恢复。参考图用 20–25 步。风险：9:16 上半部重影（1 人）、Ref2V turbo 动作僵（多人）。不要加音频参考（HF#91：相似度掉到 0.09）。
4. 更便宜的试法：FL2VA 模型挂 Ref2V turbo LoRA（3 人说身份更好，1 人测 InsightFace 0.886；1 人说更糊）。
5. 每镜单独种子比全剧共用一个种子更保脸（1 个项目）。
6. 引导帧放太密会冻住脸（1 人）。
7. **H3 身份 LoRA 已可训练**：musubi-tuner 支持 FL2VA/Ref2VA LoRA（实验性），int8 pruned + block swap 可在 24 GB 3090 上训；数据集用脸部特写才像（2 位 12 GB 用户）。

### 首尾帧 / 镜头衔接
- 没找到“落不到尾帧”的 ComfyUI / MiniMax issue。
- 首尾帧之间没有合理的物理路径时会重影/溶解；对策是加中间关键帧或加长片段（低）。
- 首尾帧用同一张图会几乎不动（多人）。

### 其它已知限制（多人）
片头约 0.5 s 乱语（写 overall_soundscape、台词句号结尾可缓解）；同性别多人对话串音；几乎不眨眼；暗场色带；会凭空加戒指类饰品；8 s 片段偶见嘴唇全红（1 人）。

## 三、建议的 A/B（项目方批准后由 gpu3 执行）
固定：同种子、768×1344、243 帧、同一对首尾帧、euler/simple、cfg 1，选 ep01 三个镜头（近景脸 / 中景动作 / 暗场）。

| 组 | 设置 |
|---|---|
| A | 现状 |
| B | 官方 8step v1.1 768p，shift 6/3，8 步，强度 1.0 |
| C | 官方 8step v1.0 768p，shift 6/3，8 步，强度 1.0 |
| D | larryvrh v4_step600_ema（pruned 转换版），shift 12/3，8 步，强度 1.0 |
| E | 底模 20–25 步，不挂 LoRA（画质上限参照） |
| F | Ref2VA + AddGuide 首尾帧 + 林晚角色卡（20–25 步） |

指标：尾帧 SSIM、InsightFace 人脸相似度（对林晚母版）、平均亮度与饱和度相对首尾帧的偏差、每条耗时。另一路：后期逐镜校色对 A–F 都套一次再比。
