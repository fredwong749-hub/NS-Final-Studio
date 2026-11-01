# MiniMax H3 画质调研：静止、4 帧顿挫、腿部重影、慢动作、身份一致性

RES，2026-10-31。用时约 40 分钟的快速调研。方法见 memory「deep research」：逐条给原文引用、链接和置信度。
置信度：**高** = 官方文档或配置文件原文；**中** = 社区实测或作者自述；**低** = 二手转述，或由我推断。
本文只讲系统参数，不涉及内容。

## 0. 结论先行

1. **静止和慢动作的主因是 turbo LoRA，不是 VAE，也不是 fps。** 有独立实验测了运动轨迹与 25 步基座的余弦相似度：LightX2V 4-NFE 约为 0，Base-10 为 0.14，Base-25 为 0.54（见 #12）。少步蒸馏把动作「抹平」了。
2. **4 帧周期的顿挫和腿部重影是同一个机制。** VAE 时间方向压缩 4 倍，一个 latent token 要装 4 帧像素。动作一快，这 4 帧的姿态装不下，就会被抹糊成重影，或者在 token 边界处跳一下（见 #8、#9）。少步 turbo 会加重这个问题（见 #14）。
3. **int8 VAE 不是原因。** 它和精确路径比 PSNR 有 67.7 dB，而 VAE 自身的重建底线只有约 38 dB（见 #10）。不用换 fp16。
4. **cfg 1 + BasicGuider 是对的。** 官方权重本身就是 CFG 蒸馏过的（见 #1）。基座应该用 **20 到 25 步、视频 shift 12、音频 shift 3**（见 #2、#3）。我们现在 turbo 用的 shift 6/3 也正确，因为 768p 的 turbo LoRA 就是按 6/3 训练的。
5. **身份一致性可以试 Ref2VA 的 Multiframe 模板。** 在这个模板里，`<Picture 1>` 同时是身份锁和首帧，尾帧用 Add Guide 钉住，其余槽位放林晚的参考图（见 #17）。注意 Ref2VA 必须用基座 20 到 25 步，4 步 turbo 对参考图的约束弱（见 #16）。

## 1. 发现表

| # | 结论 | 原文（≤15 词） | 链接 | 置信度 |
|---|---|---|---|---|
| 1 | 官方权重已做 CFG 蒸馏，所以 cfg=1 是正确的 | "released checkpoints are CFG-distilled Omni Transformer model weights" | [HF 模型卡](https://huggingface.co/MiniMaxAI/MiniMax-H3) | 高 |
| 2 | 官方 scheduler 的视频 shift 是 12 | `"shift": 12.0` | [scheduler_config.json](https://huggingface.co/MiniMaxAI/MiniMax-H3/raw/main/scheduler/scheduler_config.json) | 高 |
| 3 | 基座默认 20 步，要动作好可以加到 25 步 | "Default 20 steps" / "Raise steps (e.g. 25) for motion quality" | [ComfyUI 官方 H3 Native](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native.md) | 高 |
| 4 | 原生 24 fps，时长 4 到 15 秒，短边默认 768 | "The shorter side is set to 768 pixels by default" | [HF 模型卡](https://huggingface.co/MiniMaxAI/MiniMax-H3) | 高 |
| 5 | 帧数取 17k+5，范围 124 到 362 帧；宽高要能被 32 整除 | "round up to 17*n+5", "within 124–362 after alignment" | [LightX2V H3 脚本 README](https://github.com/ModelTC/LightX2V/blob/main/scripts/minimax_h3/README.md) | 高 |
| 6 | FL2VA 最好用单镜头，从首帧连续过渡到尾帧 | "FL2VA generally favors a single shot so the model can interpolate" | [官方 prompt 指南 base](https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md) | 高 |
| 7 | prompt 只在有意义时才写幅度和速度，中等幅度、正常速度一般不写 | "medium amplitude and normal speed are usually omitted" | 同上 | 高 |
| 8 | 一个 latent token 覆盖 4 帧像素，快动作会被抹糊；重新降噪也救不回来 | "one latent token spans four pixel frames" / "missing poses were never generated" | [H3 Jerk Oracle 节点](https://comfy.icu/node/H3JerkOracle) | 中 |
| 9 | VAE 的时间压缩是 4 倍（f16t4d24），这是上面 4 帧周期的结构来源 | "temporally causal video autoencoder with a spatial compression factor of 16×" | [HF 模型卡](https://huggingface.co/MiniMaxAI/MiniMax-H3) | 高 |
| 10 | int8 VAE 和 fp16 VAE 解码结果一样 | Kijai："decode identically"；int8 对比精确路径为 67.7 dB | [ComfyUI Wiki 0.36 VAE](https://comfyui-wiki.com/en/news/2026-09-19-h3-video-vae-optimization) | 中高 |
| 11 | ComfyUI 中每 17 帧出现暗帧加顿挫；pruned int8 没有这个问题，疑似 `time_embedder(...).to(dtype)` 的 bug；issue 仍是 open | "periodic dark frames and noticeable frame boundary stutter at exactly 17-frame intervals" | [ComfyUI #15426](https://github.com/Comfy-Org/ComfyUI/issues/15426) | 中 |
| 12 | 少步 turbo 和基座的运动轨迹几乎不相关，Base-25 最好 | "LightX2V 4-NFE changes the sampled visual trajectory the most" | [low-NFE 实验 summary](https://cauthyyy-minimax-h3-reference-performance.static.hf.space/data/summary.md) | 中（只测了 2 个 prompt） |
| 13 | 768p 的 FL2V turbo 按 shift 6/3 训练；8step 768p 推荐 8 步 | 表格："768p, 1344×768 \| 6 / 3 \| 8 \| 8" | [ModelTC/Minimax-H3-Turbo](https://github.com/ModelTC/Minimax-H3-Turbo) | 高 |
| 14 | turbo 在大幅快速动作下会抹糊、留残影；6 到 8 步基本能消除；作者承认快速剧烈动作仍是弱项 | "the two areas still being improved are audio and fast, intense motion" | [Larryvrh turbo README](https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo) | 中 |
| 15 | 官方 turbo 路线图自己承认画质和一致性还需改进 | "Improve the visual quality and consistency of Ref2VA and FL2VA Turbo." | [ModelTC/Minimax-H3-Turbo](https://github.com/ModelTC/Minimax-H3-Turbo) | 高 |
| 16 | R2V 的 4 步 turbo 对参考图约束弱；需要守住参考时用 20 到 25 步 | "Prefer 20–25 steps when references must hold" | [ComfyUI H3 Native](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native.md) | 高 |
| 17 | Ref2VA Multiframe 模板：Picture 1 同时做身份锁和首帧，Add Guide 把图钉在任意帧 | "`<Picture 1>` is both the identity lock and the first frame" | [ComfyUI H3 Multiframe](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-multiframe.md) | 高 |
| 18 | 只接在 Add Guide 上的图，文本编码器看不到 | "are not visible to the text encoder" | 同上 | 高 |
| 19 | 4step v1.3 出现退化，换回 v1.2 就恢复；开发者表示已知 | 用户 MBen1986 报告 v1.3 明显退化，换 v1.2 后恢复 | [HF discussion #57](https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/57) | 中 |
| 20 | 4step v1.2 主要改进音频；有用户认为画质下降（头发更差） | "the quality took a big hit in v1.2" | [HF discussion #52](https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/52) | 低到中 |
| 21 | 在量化底模上把 LoRA 合并进权重（low_vram）会让画面变软；int8/fp8 底模必须动态加载 LoRA | "softer on quantized (int8 / fp8 / pruned) bases" | [Larryvrh README](https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo)；[LightX2V README](https://github.com/ModelTC/LightX2V/blob/main/scripts/minimax_h3/README.md) | 中高 |
| 22 | Motion Continuity Repair LoRA：改善非预期的慢动作和异常肢体轨迹；单独使用约 0.9 | "unwanted slow-motion behavior" / "abnormal limb trajectories" | [JOKER141 HF](https://huggingface.co/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair) | 中（作者自述的 A/B） |
| 23 | Licon VBVR LoRA 减少重复物体、穿模和动作崩坏；推荐强度未找到 | "cutting duplicated objects, clipping, and broken motion" | [hermes-ai 转述](https://hermes-ai.net/news/liconstudio-s-licon-vbvr-fixes-minimax-h3-s-worst-motion-failures/) | 低 |
| 24 | 首帧比例不对会被拉伸，尾帧比例不对会被中心裁切 | "an off-aspect image comes out stretched" / last_frame "center-cropped" | [ComfyUI H3 Native](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native.md) | 高 |
| 25 | 新版 ComfyUI 上直接用 stock euler 就行（旧版会把音频步进过头） | "On recent ComfyUI a stock euler also works." | [Larryvrh README](https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo) | 中 |

## 2. 和我们现状对照

| 我们的设置 | 判断 |
|---|---|
| cfg 1 / BasicGuider | ✅ 正确（#1） |
| turbo 8step v1.1 768p @1.0，shift 6/3，8 步 | 参数本身正确（#13）。但 turbo 是静止和慢动作的主要嫌疑（#12、#14、#15） |
| euler + simple | ✅（#25）。官方基座用 rectified-flow euler，eta=0 |
| 768×1344，24 fps，17k+5 | ✅（#4、#5）。另外确认首帧和尾帧的比例与 768×1344 一致，否则会被拉伸或裁切（#24） |
| int8 VAE | ✅ 不是原因（#10） |
| pruned int8 底模 | ✅ 不会触发 #11 的 17 帧 bug。如果看到的周期是 17 帧而不是 4 帧，再查 #11 |
| 项目写作规则「正常或偏慢的速度」（owner_requirements_for_writer H3-A11） | ⚠ 推断（低）：官方说速度一般不写（#7）。prompt 里写 slow/slowly 可能和 turbo 叠加，加重慢动作。建议 A/B 时去掉速度词 |

## 3. 推荐配方（按预期画质排序）

GPU 时间按我们自己在 3090 上的实测推算（来源：gpu3_claude_status.md 和 CHANGELOG_AGENTS.md）：turbo 8 步、243 帧约 28 分钟/镜，基座 20 步、243 帧约 64 分钟/镜，turbo 8 步、124 帧约 9 分钟。推算出每步约 3 分钟（243 帧），固定开销约 4 分钟。

| 排名 | 配方 | 解决什么 | 3090 时间：243 帧（10 s） / 124 帧（5 s） | 置信度 |
|---|---|---|---|---|
| **1** | **FL2VA int8 基座，不挂 turbo**，25 步，euler/simple，shift **12/3**，cfg 1 BasicGuider，首尾帧，prompt 去掉速度词 | 静止、慢动作、残影（多步还原基座的动作分布） | ≈ 79 分钟 / ≈ 40 分钟 | 高（官方参数）；效果幅度中 |
| **2** | **Ref2VA int8 基座 Multiframe**：Picture 1 = 首帧（兼身份锁），Picture 2/3 = 林晚定妆和多角度参考（要接到 ref_images，让文本编码器看到，见 #18），Add Guide 把尾帧钉在最后一帧；25 步，shift 12/3（假设 ref 和 fl 相同，未核实），cfg 1，ref_image_size=match | 身份一致性，同时保留首尾帧 | ≈ 85 到 95 分钟 / ≈ 45 分钟（参考 token 会增加开销，属推算） | 中 |
| 3 | 方案 1 + Motion Repair LoRA 0.5 到 0.9（或 VBVR，强度从 0.5 起试） | 再压腿部重影和慢动作 | 与方案 1 相同 | 中低 |
| 4 | 现有 turbo 8step v1.1，加 Motion Repair 约 0.7 和/或 VBVR；减少单镜内的快速大动作 | 便宜的折中 | ≈ 28 分钟 / ≈ 9 分钟 | 低到中 |
| ✗ | 4step 系列（尤其 v1.3）、low_vram 合并、w4a8 | 已知更差（#19、#21） | 不推荐 | |

**MOT 的最小 A/B（同一 seed、同一镜）**：①现状 turbo；②方案 1；③方案 2。先跑 124 帧以节省时间，看三项：动作幅度、4 帧周期（逐帧差分曲线）、腿部重影。

## 4. 没找到的内容

- 官方基座 FL2VA 和 Ref2VA 各自的推荐步数和 shift（只有 ComfyUI 文档的 20/25 步和 scheduler_config 的 shift 12；Ref2VA 是否同样是 shift 12 未核实）。
- lightx2v turbo 的 v1.1、v1.2、v1.3 官方 changelog（只有讨论区的发布帖）。
- Reddit 上关于「每 4 帧顿挫」的原帖（只找到 GitHub issue #15426 的 17 帧版本和 Jerk Oracle 的机制解释）。
- 本地已有的 antiburn、lms_v1.0、DMAD、camera_motion、pika_h3_flex、open_regenerate_2k_refiner 的官方说明，本轮没查到。
- 3090 单卡的公开基准（上面的时间都是用我们自己的实测推算的）。
