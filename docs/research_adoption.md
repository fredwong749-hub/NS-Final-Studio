# 调研方法落地表（research adoption）

> 2026-10-30，agent E（只做系统/参数，G1–G6：不写提示词与剧情、不判审美）。
> 读过：docs/research/h3_deep/00–03、docs/research/h3_prompt_and_fl2v.md、docs/research/seedance_consistency.md、`script play lib/research v3–v9`、docs/SOP_parameters.md、SOP_production.md、gpu_speedups.md、upscale_4k.md、CONSISTENCY_PLAN.md、production_issues.md。
> 现状核对方法：grep 笔记本 `services/ packages/ config/ tools/`；gpu3 只读（`ssh gpu33`：weita_render.py / weita_series.py / comfy_h3/workflow.py / journalctl / nvidia-smi / loras 目录）。gpu3 上没有改任何东西，也没有起 GPU 任务。
> 缩写：WR/WS = gpu3 `ns-studio/scripts/weita_render.py` / `weita_series.py`；NR = 笔记本 `services/render_router/ns_render/`；PI-xx = docs/production_issues.md。
> 现状：**已采用** = 代码里就是这个值；**部分** = 一条链有、另一条没有，或只有 warn；**未采用** = 没有。
> 优先级：P0 = 低风险且直接对应 Top-10 问题；P1 = 需要 gpu3 补丁或 CPU 侧工作；P2 = 需要 GPU A/B 才能定；P3 = 远期/研究。

## 一、逐条落地表

### A. H3 视频参数（S4）

| # | 方法 / 参数 | 来源（文件 § + 外部原文） | 解决 | 现状 | 落地位置 | 风险 | 验证 | 优先级 |
|---|---|---|---|---|---|---|---|---|
| A1 | 底模用 `minimax_h3_fl2va_pruned_int8_convrot`，不用 w4a8（w4a8 + LoRA 时 `adaln_proj` 的 LoRA delta “silently never applies”） | 03 §0、§5 #2；<https://github.com/Comfy-Org/ComfyUI/issues/16420> | PI-01、PI-20、PI-23 | **已采用**（gpu3 WR `H3_DIT`）；**笔记本今天补上**（NR 原为 w4a8） | WR L1052；NR `workflows.H3_DIT_INT8` / `H3Model.unet` | 无（gpu3 已在用；笔记本 ComfyUI `D:\kimi-ns-storyboard` 也有该文件） | 测试 `test_h3_defaults_match_locked_sop_values`；**注意 gpu3 `comfy_h3/workflow.py` L49 `H3_FL2VA_FILES` 默认仍是 w4a8**，WR 用 `dataclasses.replace` 覆盖，其他调用者会踩坑 → 补丁 G3 | P0 |
| A2 | 加速 LoRA = 官方 `fl2v_turbo_8step_v1.1_768p_comfyui_bf16`，强度 1.0（低→偏暗，高→过曝） | 00 §二“加速 LoRA”；02 §2.5（TawusGames：“low power causes the colors to become darker”） | PI-23、PI-19 | **已采用**（WR `TURBO["t8"]`）；**笔记本今天补上**（NR 原为 Kijai rank-24 544p v1.0，且本机 loras 目录里没有这个文件 → 本机出视频本来就会失败） | NR `H3_TURBO_8STEP_768P` | v1.1 尚无社区 FL2V 实测（02 §0 #6） | A/B 组 B vs C vs D（§三 X1） | P0（对齐）/ P2（版本定稿） |
| A3 | shift 与 LoRA 配对：768p Turbo → 6/3；基模或 544p → 12/3；shift 节点同时接采样模型和调度器 | h3_prompt_and_fl2v §2 Turbo 表；LightX2V 原文 “Recommended settings: 8 NFE, video shift 6, audio shift 3” <https://github.com/ModelTC/Minimax-H3-Turbo> | PI-23 | **已采用**（WR L1101–1106）；**笔记本今天补上**（NR 原图没有 `MiniMaxH3SigmaShift`，等于用节点默认 12/3 配 6/3 训练的 LoRA） | NR `expected_shift()`、`h3_fl2va` 节点 150 | 无 | `test_shift_node_feeds_both_guider_and_scheduler`、`test_lora_shift_pairing` | P0 |
| A4 | 加速步数 ≥6，用 8；4 步慢动作/蜡化/音频差 | 02 §2.1（≥8 人；Gamb：“Forget about 4 step… Minimum is 6 steps.”） | PI-14、PI-20 | **已采用**（两链 8 步）；笔记本加了 <6 步拒绝 | NR `check_h3_model` | 无 | 单测 | P0 |
| A5 | 采样器 euler/simple，不用 ancestral/SDE；euler 让 I2V 变暗约减半 | 03 §2.1（reasy0000：“`euler` instead of `res_multistep` roughly halves the mild I2V dimming” <https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/67>）；ComfyUI #15283（音频破音） | PI-19、PI-14 | **部分**：Turbo 档两链都是 euler；**gpu3 基模档（无 LoRA，20 步）用 `res_multistep`**（WR L1099） | WR L1099；NR `H3_BASE.sampler="euler"`（已改） | 1 人报告，基模档画质可能变 | X2：基模 20 步 euler vs res_multistep，测前 1.5 s 亮度落差 | P1（gpu3 补丁 G1，A/B 后合） |
| A6 | 不挂 EasyCache / Spectrum / TeaCache / Cache-DiT / Sol-Attn / torch.compile；SageAttention 2 可留 | 00 §二 速度 2（≥5 人无反对）；03 §2.3；Sol-Attn 原仓库 “Sol-Attn is approximate.” | PI-01、PI-20 | **已采用**（gpu3 核实无缓存/compile/Sol；笔记本图里也没有）；笔记本加了禁用节点清单 | NR `H3_BANNED_NODES` + `test_no_lossy_accelerators_in_graph` | 无 | 单测；gpu3 巡检 | P0 |
| A7 | 帧数 17k+5、24 fps、124–362 帧 | h3_prompt_and_fl2v §2（源码 `align_frame_count`） | PI-08 | **已采用**（两链）；笔记本加了范围钳制和图构建前断言 | NR `pipeline.render_video`、`workflows.h3_fl2va` | 无 | `test_frames_must_be_on_grid_and_in_range` | P0 |
| A8 | 画布 768×1344（短边 768、≈1 MP；“1.0 MP is the sweet spot”） | 03 §3.1（<https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/30>）；SOP P-B3 | PI-01 | **已采用**（gpu3）；**笔记本今天由 576×1024 改为 768×1344** | NR `pipeline.VIDEO_SIZE` | 笔记本 12 GB 显存跑 21 GB int8 要靠 dynamic VRAM 卸载，会慢；未实测（不起 GPU 任务） | 下次本机出视频时记录耗时与峰值显存 | P0 |
| A9 | 首尾帧用**同一种** center-crop + lanczos 到 768×1344（节点对首帧拉伸、对尾帧居中裁） | h3_prompt_and_fl2v §0 #2（源码 `_resize(..., "disabled")` / `"center"`） | PI-08 | **已采用**（gpu3 `h3_keyframe` + 断言）；**笔记本今天补上**（图里两帧都先过 `ImageScale crop=center`） | NR `h3_fl2va` 节点 202/203 | 无 | `test_both_keyframes_get_the_same_centre_crop` | P0 |
| A10 | 不加 `--fast fp16_accumulation` | 03 §2.3（ComfyUI #16589，2 人支持 1 人存疑）；gpu_speedups §2.4（对 bf16/int8 无作用） | PI-19 | **已采用**（gpu3 启动参数无 `--fast`） | `deploy/gpu3/comfy-launch.sh` | 无 | 巡检 | — |
| A11 | Turbo LoRA key 实际加载数核对 | 00 §一 “仍未核实”；02 §4.1（Raylight 曾静默加载 0 key） | PI-23 | **部分**：今天只读查 journald（10-29 起 3.2 万行）`lora key not loaded` = **0 条**；但 10-30 起视频暂停，v1.1 还没在日志窗口里跑过 | gpu3 journald | — | 恢复视频后第一条 take：查 `lora key not loaded` = 0 且 `Requested to load` 正常 → 写进 take 记录（补丁 G4） | P1 |
| A12 | 不用 full INT8/BF16（每 17 帧暗一帧），用 pruned | 01 #85、03 §2.1（2 人） | PI-19 | **已采用**（pruned） | — | — | — | — |
| A13 | ComfyUI ≥ 2026-09-22（#16436 VAE 分块接缝修复） | 03 §1.1 | PI-20 | **已采用**（0.42.0） | — | — | — | — |
| A14 | 不用 Sol-H3-VAE 做皮肤近景（128 px 网格接缝） | 03 §1.1（#17429） | PI-20 | **已采用**（视频 VAE = `minimax_h3_video_vae_int8_convrot`） | — | — | — | — |
| A15 | 每镜独立种子（共用种子会让脸和声音一起漂） | 03 §3.1（joeygambino，1 项目） | PI-01、PI-13 | **已采用**（WR `seed_for("video", s.id)`；NR `seed_for(shot_id+"/v", n)`） | — | — | — | — |
| A16 | 失败重试时缩短时长（官方 skill：漂移时 ≤6 s） | 01 #9；00 §二 人物一致性 2 | PI-01 | **部分**：笔记本第 3 次重试缩到 158 帧（6.6 s）；gpu3 未见。**镜头时长本身属剧本内容（Qwen/项目方）**，Claude 不改 | NR `render_video` plans | 时长改变会影响对白时长（PI-16） | X5 | P2 |
| A17 | 中间关键帧 `MiniMaxH3AddGuide`（必须经过某姿态的镜头；太密会冻脸） | h3_prompt_and_fl2v §2；03 §3.2（hidetaro7）；PR #15439 | PI-22、PI-08 | **未采用**（WR/WS 中 0 处；只有 shot_audit 提到） | gpu3 `h3_graph` | 中间帧要由 Qwen 链出图；密度不当冻脸 | X6 | P2 |
| A18 | Ref2VA + AddGuide 锁首尾帧 + 角色卡（官方 multiframe 模板；33.3 dB / SSIM 0.993） | 03 §3.2（<https://docs.comfy.org/tutorials/video/minimax/minimax-h3-multiframe>；januscaler PR #10） | PI-01、PI-04 | **未采用**（WR 无 ref2va FL2V 路线） | gpu3 新 variant | R2V Turbo 9:16 上半重影（1 人）、动作僵（多人）；20–25 步慢 | X4（组 F） | P2 |
| A19 | FL2VA 挂 Ref2V Turbo LoRA（InsightFace 0.886；1 人说更糊） | 00 §二 人物一致性 4；03 §3.2 | PI-01 | **未采用**（文件 `ref2v_turbo_8step_v1.1_768p` 已在 gpu3 loras） | gpu3 variant token | 偏糊 | X4 加一组 | P2 |
| A20 | larryvrh `v4_step600_ema`（shift 12/3，近景脸更好，≥4 人） | 02 §0 #7、§2.3 | PI-01 | **未采用**（gpu3 loras 目录里没有该文件） | 下载后作 variant | 快动作拖影、暗场色带 | X1 组 D | P2 |
| A21 | 序列并行（Raylight Ulysses）：4×3090 87.4→28.0 s/步 | 02 §4.1（alesha-pro，<https://github.com/komikndr/raylight>） | PI-27 | **未采用** | gpu3 独立 ComfyUI | 依赖旧 torch；LoRA 需补丁否则 0 key；GPU2 故障只剩 3 卡；与“每卡独立任务”调度冲突 | X8（只测速度+key 数） | P3 |
| A22 | 功耗上限 220→320 W | 02 §4.2 | PI-27 | **已采用**（nvidia-smi：4 卡均 350 W） | — | — | — | — |
| A23 | `--cache-none` → `--cache-ram 140 200` + systemd MemoryHigh/Max | gpu_speedups §5.2 | PI-27 | **未采用**（3 个实例仍 `--cache-none`） | `deploy/gpu3/comfy-launch.sh` | 要重启实例 | 重启后看 Qwen 每图 1–4 s 收益 | P1（补丁 G5，等约定重启） |
| A24 | H3 加 `ModelAttentionBackend(comfy kitchen attention)` 或 Sage | gpu_speedups §6、§7.2 | PI-27 | **未采用**（只在 ref2va 两段式图） | gpu3 `comfy_h3/workflow.py build_workflow` | 收益预计 0–10%；需比脸 | X7（`/root/build_sage/chain.sh` 已排好） | P2 |
| A25 | 文本编码器 nvfp4_awq 在 Ampere 上是软件模拟 | 02 §3.1（3090 日志：fp8/nvfp4 模拟） | PI-27 | **待查**：两链都用 `qwen3vl_32b_minimax_h3_nvfp4_awq`；TE 只占约 1.7 s/任务，收益小 | — | 换 TE 可能改变提示词编码 | 低优先级测速 | P3 |
| A26 | 低分辨率（352–576p）先试构图，满意再出 768p | 00 §二 速度 6（HF#65，中） | PI-27、PI-08 | **未采用** | 调度层 preview tier | 低分辨率与 768p 结果不等价 | X9 | P3 |

### B. 颜色（PI-18、PI-19）

| # | 方法 / 参数 | 来源 | 解决 | 现状 | 落地位置 | 风险 | 验证 | 优先级 |
|---|---|---|---|---|---|---|---|---|
| B1 | 视频逐镜校色到**我们自己的**首/尾关键帧：逐通道 gain+bias，首尾两端线性插值，不用 LUT / 硬直方图 | 00 §二 颜色 1（≥6 人确认偏色）；03 §2.2（rkfg：“tends to run darker than the anchored keyframes” <https://github.com/rkfg/ComfyUI-MiniMaxH3-ToneCompensate>；lovemachine100 dE 4.2→1.9） | PI-19 | **部分**：笔记本 `ns_post.colormatch`（lab_gain_bias_lerp_v1）已实现，**默认关**（`--color-match`）。今天 CPU dry-run ep01：6 镜只有 S3 找到匹配的首帧（其余 SKIP：没有匹配 frame 0 的本地关键帧）；S3 首段 dE 1.03→预计 0.43，尾段 dE 8.25 无尾帧参考无法校 | `services/post/ns_post/colormatch.py`、`tools/color_match_clips.py` | 关键帧没同步就无法校（PI-08）；尾帧插值是推断 | X10（CPU，可随时跑）：有关键帧后 dry-run 全集，before/after dE 写报告；**默认打开要等关键帧同步 + 项目方点头** | P1 |
| B2 | 只在人物区域取统计量（背景运动会带偏） | 03 §2.2 #2 | PI-19 | **部分**：`region="centre"` 高斯权重近似人物区，不是检测人物 | colormatch `CcSettings.region` | 人物不在中央时偏 | X10 里比 centre vs full | P2 |
| B3 | 对比/校色时不用 VHS 加载器（会偏色、造假接缝） | 03 §2.2 #4（2 人） | PI-19 | **已采用**（colormatch 用 ffmpeg rgb24 解码） | — | — | — | — |
| B4 | 视频颜色闸门：前/后 0.5 s 与首/尾帧人物区 ΔE2000 ≤ 4，全片 L* 漂移 ≤ 8 | PI-19 建议检查 | PI-19 | **未采用**（WS 只有 PSNR/SSIM/SFace） | gpu3 WS 视频 QC（补丁 G2）；笔记本可复用 colormatch 的测量 | 阈值未校准 | 用 ep01 已有片子在 CPU 上算分布后定阈值 | P1 |
| B5 | 首帧 Reinhard LAB 迁移到色调参考图，强度 0.6、暗场 0.3 | research v6 §6；SOP S3-F7 | PI-18 | **已采用**（NR `grade.STRENGTH=0.6`、`DARK_SHIFT_SHARE`；VB `color_match_strength`；WR colour_match） | — | — | — | — |
| B6 | 尾帧调色参考：笔记本 0.7 迁移到定稿首帧；gpu3 0.6 迁移到参考图 | SOP S3“尾帧调色”（待验证） | PI-19 | **两链不一致**（SOP 已标待验证） | NR `LAST_GRADE_STRENGTH`；WA L259 | 由 SOP 管理员定，不在本次范围 | X11（CPU：首尾帧 LAB 距离对比） | P2 |

### C. 一致性 / 锚点（Seedance 方案、PI-01/04/07/08/22）

| # | 方法 | 来源 | 解决 | 现状 | 落地位置 | 风险 | 验证 | 优先级 |
|---|---|---|---|---|---|---|---|---|
| C1 | 场景母版（不可变）+ 三图编辑 `[上一镜尾帧, 场景母版, 角色定妆]`；切镜回锚，不链式编辑 | seedance §4 方案 1；Dreamina 指南（“回到最早源头修”） | PI-04、PI-02 | **部分**：CONSISTENCY_PLAN 方案 A 由 gpu3 实现中（T47），SOP 写“场景内接力”；场景底板闸门已锁 | gpu3 | 链式误差累积 | ep01 衔接表（continuity_sheet）+ R-C7 | P1（gpu3 已在做） |
| C2 | 接续用**视频解码出的真实末帧**，不用计划尾帧（Seedance `return_last_frame`） | seedance §1.5、§4 方案 1.2 | PI-08 | **部分**：笔记本 `extract_last_frame` 存 `video_NNN_last.png`；gpu3 是否用真实末帧接下一镜未见代码 | NR pipeline；gpu3 relay | — | 核对 gpu3 下一镜首帧的 reference_sha | P1 |
| C3 | 首尾帧差距闸门（人物框位移/尺度、姿态、yaw ≤60° 除非写了转身） | seedance §4 方案 1.3；PI-22 建议 | PI-22、PI-08 | **部分**：S3-K1（同景同光同衣）有；S3-K3 朝向只有 warn；yaw 未实现 | gpu3 WS / shot_audit | 阈值要校准 | 用 ep01 已知坏片当负样本 | P1 |
| C4 | 人脸足够大（最大人脸 ≥200 px 或 ≥2% 面积）→ block | 00 §二 人物一致性 1（≥6 人）；PI-01 建议 | PI-01 | **部分**：WR 记录 `max_face_px`，S3-K2 只 warn | gpu3 WS 帧闸门（补丁 G6） | 远景镜头会被大量拦下（景别属剧本内容 → 交 Qwen 改景别） | 统计 v3 剧本景别分布后再开 | P1 |
| C5 | 视频内身份曲线：每 0.5 s SFace，中位 ≥0.30、任意 2 s 最小 ≥0.20 | seedance §4 方案 1.4；PI-01 建议 | PI-01 | **部分**：WS 只取 5 个点（1.5/3.5/5.5/7.5/9.9 s） | gpu3 WS L1000 | CPU 时间 ×4 | 三条已知坏片必须 FAIL（golden 负样本） | P1 |
| C6 | 镜内服装/道具漂移（0/25/50/75/100% 取帧，LAB ≤0.45 + VLM） | seedance §4 方案 1.4；PI-04 | PI-04 | **未采用** | gpu3 视频 QC | VLM 成本 | golden | P2 |
| C7 | 角色形象时间轴（looks × 集内状态 → 提示词/VLM/闸门） | seedance 方案 4；CONSISTENCY_PLAN 方案 D | PI-04、PI-05 | **部分**：`state_timeline.py` 已有；`[looks] inject=false`（SOP 门槛） | services/agent（他人范围） | — | bible_diff + A/B 一镜 | — |
| C8 | 身份 LoRA（H3：musubi FL2VA teacher matching；图像：ai-toolkit qwen_image_2） | 03 §6；v5 §1 | PI-01 | **进行中**（GPU 正在训 LoRA） | gpu3 `tools/lw_lora` | — | eval_h3.py | — |
| C9 | musubi 训练加 `--use_pinned_memory_for_block_swap`（预计每步快 10–20%） | gpu_speedups §5.3 | PI-27 | **未采用**（`train.sh` L37 只有 `--blocks_to_swap $SWAP --block_swap_h2d_only`） | gpu3 `tools/lw_lora/train.sh` | 多 pin ~15 GB RAM；**当前训练中不要改** | 下一次训练起跑时对比 s/it | P1（补丁 G7，等当前训练结束） |
| C10 | Wan VACE 多关键帧备用引擎、HoloCine 多镜头联合 | seedance 方案 3、5 | PI-22 | **未采用**（不建议近期） | — | 双引擎风格不统一、无音频 | — | P3 |

### D. 图像端（S3）与 4K（S5）

| # | 方法 / 参数 | 来源 | 解决 | 现状 | 落地位置 | 风险 | 验证 | 优先级 |
|---|---|---|---|---|---|---|---|---|
| D1 | 定稿 Base 30–40 步、真 CFG；Turbo 只做预览 | v8 §0.2 | PI-20 | **gpu3 已采用**（35 步 cfg 3.0）；**笔记本仍 Turbo**（本机 A/B：Base 慢 3.8×、不减裸露；笔记本已不为《为他而骚》出帧） | WR；NR `QWEN_BASE` steps 25 | 笔记本链与锁定值不一致，但已不出生产帧 | — | — |
| D2 | 两段式：≈1.5 MP 出图 + lanczos 放大 + denoise 0.30 第二遍（>0.4 脸漂） | v8 §0.5、§4 | PI-20 | **已采用**（gpu3；笔记本精修 0.22，项目方 A/B） | WR L921–926 | — | — | — |
| D3 | krea2_film_texture 0.5；停用 glamour_realism | v8 §2 | PI-20 | **已采用**（VB realism / banned_loras） | — | — | — | — |
| D4 | 写实 LoRA 最多叠 2 个、总强度 ≤1.2；资产 LoRA 叠加时写实降到 0.4 | v8 §2 原则 | PI-20、PI-06 | **部分**：gpu3 `LORA_CAP = 1.6`（全部 LoRA 合计） | WR | 改上限会改画面 → 需 A/B | X12 | P2 |
| D5 | 4K：SeedVR2 3B，batch 21 / overlap 4 / LAB colour correction，先锐化后颗粒 σ2，不重绘（不用 H3 regenerate） | upscale_4k §2–3；v5 §4；v6 §6 | PI-20 | **已采用**（gpu3 `upscale_4k.py`） | gpu3 | 3090 4K 耗时未测 | up4k-test 进行中 | — |
| D6 | 4K H.264 成片：CRF 16–17 + `-maxrate 60M -bufsize 120M -level 5.1` | upscale_4k “Notes for T38” | PI-17（交付） | **今天采用**（原 crf_4k 20、无 VBV） | `services/post/ns_post/assemble.py Settings.crf_4k/maxrate_4k/bufsize_4k/level_4k`、`render_segment` | 码率上升（σ2 颗粒 @CRF17 ≈39 Mbit/s） | `test_4k_delivery_encode_settings`；出 4K 成片时记录码率 | P0 |
| D7 | 首帧颗粒 ≤σ2 或不加（H3 会平均化/闪烁），颗粒只在成片加 | v8 §4.4 | PI-20 | **已采用**（颗粒只在 upscale_4k finish） | — | — | — | — |

## 二、今天在笔记本落地的改动（只改参数/配置/检查）

| 文件 | 改动 | 依据 |
|---|---|---|
| `services/render_router/ns_render/workflows.py` | `H3Model` 默认：底模 w4a8 → `pruned_int8_convrot`；LoRA Kijai rank-24 544p v1.0 → 官方 `8step_v1.1_768p` @1.0；新增 `shift=(6,3)` 并在图里插 `MiniMaxH3SigmaShift`（同时接 BasicGuider 与 BasicScheduler，同 gpu3 WR L1101）；新增 `keyframe_crop`（首尾帧都先 `ImageScale lanczos crop=center` 到画布）；新增 `H3_BASE`（无 LoRA、20 步、12/3、euler）；`expected_shift()` 配对规则；`check_h3_model()` 出图前拒绝 w4a8+LoRA、shift 不配对、Turbo <6 步、ancestral/SDE；帧数不在 17k+5 或 124–362 直接报错；`H3_BANNED_NODES` 清单 | A1–A9 |
| `services/render_router/ns_render/pipeline.py` | `VIDEO_SIZE` 576×1024 → 768×1344；`render_video` 帧数钳到 124–362 | A7、A8 |
| `services/post/ns_post/assemble.py` | 4K 交付 `crf_4k` 20 → 17，加 `maxrate_4k 60M / bufsize_4k 120M / level_4k 5.1`（只用于 4K） | D6 |
| `tests/test_research_adoption_params.py`（新）、`tests/test_render_workflows.py`（首尾帧节点号随 crop 更新） | 上述参数的单测 | — |

没有改：`config/visual_bible.toml`（编译器不读任何 H3 采样参数，无可加的技术键）、颜色校正默认开关（B1 依赖关键帧同步）、图像链（D1 属项目方 A/B 决定）、任何 gpu3 文件。

## 三、gpu3 补丁提案（只读核对后写的，**未执行**；由 claude-gpu3 / SOP 管理员决定）

- **G1（A5，A/B 后合）** `weita_render.py` L1099：
  ```diff
  - g = build_workflow(seg, uploaded, files, SamplerParams(steps=steps, fps=FPS, sampler="euler" if turbo else
  -                                                          "res_multistep"), filename_prefix=prefix)
  + g = build_workflow(seg, uploaded, files, SamplerParams(steps=steps, fps=FPS, sampler="euler"),
  +                    filename_prefix=prefix)
  ```
  并在 L1101 的 `if turbo:` 之外，对基模档也显式插 `MiniMaxH3SigmaShift(12.0, 3.0)`（现在靠节点默认值，换节点版本会悄悄变）。
- **G2（B4）** `weita_series.py` 视频 QC（L994–1033 附近）新增颜色漂移：取前 12 帧/后 12 帧，人物区（人脸框扩 2×）LAB 均值，与 `h3_keyframe` 产出的首/尾帧比 ΔE2000；`> 4` 或全片 L* 漂移 `> 8` → `fails.append("colour drift …")`。先只记录（warn）一周，拿分布定阈值后再 block。
- **G3（A1）** `ns-studio/adapters/video/comfy_h3/workflow.py` L49：`H3_FL2VA_FILES` 的 unet 改为 `minimax_h3_fl2va_pruned_int8_convrot.safetensors`（现为 w4a8；WR 用 replace 覆盖了，但别的调用者——eval_h3.py、FastGraph——会拿到 w4a8 + LoRA 的组合）。
- **G4（A11）** 每个视频 take 记录里加 `lora_keys_unloaded`：take 完成后 `journalctl -u ns-comfy@<inst> --since <start>` 统计 `lora key not loaded` 行数，>0 → take 标 `fail`。
- **G5（A23）** 下次约定重启时 `deploy/gpu3/comfy-launch.sh` L10：`--cache-none` → `--cache-ram 140 200`，加 `/etc/systemd/system/ns-comfy@.service.d/memory.conf`（`MemoryHigh=80G`、`MemoryMax=110G`），原文见 gpu_speedups §5.2。
- **G6（C4）** S3-K2 人脸大小：`max_face_px < 200` 且面积 <2% 时由 warn 改 block（只对剧本写了林晚正脸的镜头；远景镜头的景别修改交给 Qwen）。
- **G7（C9）** **当前训练结束后**，`tools/lw_lora/train.sh` L37 加 `--use_pinned_memory_for_block_swap`。
- **G8（C5）** `weita_series.py` L1000：采样点由 5 个改为每 12 帧一个（0.5 s），判定改为中位 ≥0.30 且任意连续 2 s 最小值 ≥0.20；用 ep01s3_a2、ep01s6_a1 当负样本回归。

## 四、排好的 A/B 实验（等 GPU 空出来；固定：同种子、768×1344、243 帧、同一对首尾帧、cfg 1；ep01 三镜：近景脸 / 中景动作 / 暗场）

| # | 实验 | 组 | 指标 | 对应 |
|---|---|---|---|---|
| X1 | 加速 LoRA 版本 | A 现状（v1.1 768p 6/3 8 步）· C v1.0 768p 6/3 · D larryvrh v4 12/3 · E 基模 20–25 步无 LoRA（上限参照） | 尾帧 SSIM、对林晚母版 InsightFace/SFace、相对首尾帧的亮度/饱和度偏差、每条耗时 | A2、A20 |
| X2 | 基模档采样器 | euler vs res_multistep（20 步，12/3） | 前 1.5 s 平均亮度落差、全片 L* 漂移 | A5、G1 |
| X3 | Turbo 强度 | 1.0 vs 0.8 vs 0.65（仅在首尾帧贴合差的镜头） | 尾帧 SSIM、首帧 PSNR、亮度偏差 | 02 §2.5 |
| X4 | 身份通道 | F Ref2VA + AddGuide 首尾帧 + 林晚角色卡（20–25 步）· FL2VA + Ref2V Turbo LoRA | SFace 曲线（每 0.5 s）、9:16 上半重影目检 | A18、A19 |
| X5 | 时长 | 10 s vs ≤6 s（同一动作；只测漂移，镜头时长改不改由 Qwen/项目方定） | SFace 中段最小值、尾帧 SSIM | A16 |
| X6 | 中间关键帧 | 无 vs AddGuide 1 张（中点）vs 2 张 | 朝向跳变 yaw、脸是否被冻住 | A17 |
| X7 | H3 注意力后端 | SDPA vs kitchen int8 vs Sage（`/root/build_sage/chain.sh` 已排） | s/步、脸部 PSNR | A24 |
| X8 | 多卡序列并行 | Raylight Ulysses 2 卡 vs 1 卡 | s/步、LoRA key 数 | A21 |
| X9 | 低分辨率试构图 | 576p 草稿 vs 768p 定稿的构图一致率 | 构图 IoU、首尾帧贴合 | A26 |
| X10 | 视频校色（**CPU，不占 GPU，关键帧同步后可随时跑**） | 不校 / centre 0.8 / full 0.8 / centre 1.0 | before/after dE（首、中、尾）、L* 漂移 | B1、B2 |
| X11 | 尾帧调色参考（CPU） | 笔记本 0.7→首帧 vs gpu3 0.6→参考图 | 首尾帧 LAB 距离、视频首尾 dE | B6 |
| X12 | LoRA 叠加上限 | cap 1.6 vs 1.2 | SFace、项目方盲选（审美由项目方定） | D4 |

## 五、按影响排序的采纳计划

1. **（已做，P0）笔记本 H3 图对齐锁定值**：int8 + v1.1 768p + 6/3 shift 节点 + 同一 center-crop + 768×1344 + 参数自检。原图三处错（w4a8、544p rank-24 LoRA 不在本机、没有 shift 节点）会让笔记本出的任何视频要么失败要么 LoRA 不生效。
2. **（P1，gpu3）G3 + G4**：把 adapter 默认 w4a8 改掉，并在每个 take 记录 LoRA 未加载 key 数——把 PI-23 从“靠人核对”变成自动拦截。零画质风险。
3. **（P1，gpu3 + 笔记本）关键帧同步 → X10 → B1 默认开**：PI-19 是 Top-10 第 10，社区共识最强（≥6 人偏色、3 个项目都用后期校色）；阻塞点只是 gpu3 没把每个 take 的实际首尾帧同步过来（PI-08 同一根因）。
4. **（P1，gpu3）G2、G6、G8 闸门**：颜色漂移、人脸大小、身份曲线。都是 CPU 检查，先 warn 后 block。
5. **（P2，等 GPU）X1/X2/X4**：决定加速 LoRA 版本、基模采样器、是否引入 Ref2VA 身份通道——对 PI-01（Top-10 第 3）影响最大，但必须实测。
6. **（P1，等重启/训练结束）G5、G7**：纯提速，无画质风险。
7. **（P3）** Raylight 多卡、Wan VACE 备用引擎、多镜头联合生成：暂不进生产。

## 六、画质 P2 补充调研（2026-10-31）

> **背景**：项目方把画质定为 P2（P1 是系统跑通），目标是电影级、时尚大片、徕卡级质感，人物一致，颜色更丰富。本节只做调研，不下载、不跑 GPU、不改代码。
>
> **原始材料**：
> - 10-29 kimi 会话的三份报告，原样存档：`docs/research/kimi_20261029_{0855,1040,1424}.md`
> - 本次深挖，每条结论都附原文引用、链接和可信度：
>   - `docs/research/quality_deep/01_h3_face_identity.md`（下文简称 Q1）
>   - `02_h3_loras_guidance.md`（Q2）
>   - `03_image21_film_look.md`（Q3）
>
> **“在 gpu3”一列**：2026-10-31 只读 `ls gpu33:/root/claude-kimi-ns-studio-v1/ComfyUI/models/{loras,diffusion_models,vae,latent_upscale_models}` 和 `custom_nodes` 得到；sha256 还没上机核对（Q2 附有对照表）。
>
> **链路位置**：定稿出图 = 首尾帧 Qwen 2.1；精修 = 首帧低重绘第二遍；H3 = 视频主生成；后期 = 视频生成后处理。
>
> 所有对比实验固定同一镜头、同一种子、同一身份 LoRA，由项目方盲选；审美判断归项目方。

### E. 新增条目

#### H3 脸部与身份

| # | 方法 / 文件 | 来源 | 链路 | 需要的文件，是否在 gpu3 | 结论 | 风险 | 建议对比 | 可信度 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|
| E1 | **H3-FaceRefine v1.1.2**：脸部检测，裁到 768，用 H3 以 denoise 0.40 重绘，再羽化贴回；音频由 NativeAudioLock 锁住 | Q1 §1 | 后期 | 节点、NativeAudioLock、Impact-Pack、VHS、`face_yolov8m.pt`（约 52 MB）、pip 包 ultralytics / insightface / scenedetect（只装 onnxruntime-gpu）：**都不在 gpu3** | 作者的示例模板就用我们的底模 `fl2va_pruned_int8_convrot` 加 turbo 8step；**脸高超过 120 px 时倍率 0.35，几乎不改**（#19，作者确认），所以主要救远景小脸 | 模板 shift 为 12，和我们的 6/3 不配对；4070 Ti S 上 243 帧需 81–339 s，3090 未测；可能跟错人 | R-FR：原片 / 模板原样 / 改 shift 6/3 / 大脸倍率 0.7 + face_px_large 400 / refine 这一遍换 ref2va 权重；看 ArcFace 曲线、脸部闪烁、耗时 | 机制高，效果低-中 | P2（需装节点和依赖，属新增依赖） |
| E2 | **官方 multiframe**：Ref2VA + ReferenceToVideo + AddGuide 首尾帧 + 林晚角色卡 | Q1 §3 | H3 | 用到的文件 **gpu3 都有**（ref2va pruned int8、ref2v turbo 8step v1.1）；**Combined 节点不用装**，核心 PackedLayout 原生支持 | **源码确认的坑**：只要接了参考图，首尾帧就不进文本编码器，`<Picture N>` 只按参考槽位编号。所以首帧要同时接 AddGuide(0) 和 ref_image_1；提示词按 `VIDEO_PROMPT_WRITING_GUIDE_ref_en` 的六段式写 | 9:16 上半部重影（1 人）；Ref2V turbo 下动作僵；官方 FL2VA 权重没训练过参考图 | 即 X4 细化为 A 现状 / F1 ref2va + turbo 8step v1.1 / F2 不挂 turbo 跑 20–25 步 / F3 FL2VA 加参考图；看首尾帧 PSNR、ArcFace、重影 | 机制高，效果低-中 | P2 |
| E3 | Singularity V2（WAS pruned int8 约 21 GB） | Q1 §2 | H3 | 不在 gpu3 | 只有 ref2va 版本；6 人说参考身份保持比 V1.3 差；2 人加作者承认偏灰、降饱和 | 偏灰，与“颜色更丰富”相反 | 只有 E2 的 F 组胜出后才下载对比 | 中 | P3 |
| E4 | HF H3 #47 的 I2VA 对齐句 | Q1 §4 | 提示词 | — | 是普通用户发的帖，不是官方；内容与官方 base_en 一致。现有 FL2VA 模板正确，不用改 | — | — | 高 | 已符合 |
| E5 | iamkaikai Single-Frame-VAE | Q1 §5 | — | — | 只能解单帧，不能当视频解码器用 | — | — | 高 | 不采用 |

#### H3 LoRA 与引导

| # | 方法 / 文件 | 来源 | 链路 | 需要的文件，是否在 gpu3 | 结论 | 风险 | 建议对比 | 可信度 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|
| E6 | **Turbo 版本定底座** | Q2 §5 | H3 | 4step v1.2 / v1.3、8step v1.0 / v1.1 **都在 gpu3** | 截至 10-31，8step v1.1 在 FL2V 上仍无任何社区实测；四个版本的文件结构完全相同，所以 v1.3 叠加会坏是权重本身的问题；4step v1.2 是唯一实测“叠其他 LoRA 正常”的版本，但 3 人说画质和头发变差 | 叠 E7–E9 前必须先定版本 | R1（并入 X1）：8step v1.1 / 8step v1.0 / 4step v1.2 跑 4 步 / 4step v1.2 @0.5 跑 8 步 | 中 | **P2 第一个跑** |
| E7 | fal **Realism-People** LoRA（触发词 r34l1sm 放在最前，强度 0.6–1.0） | Q2 §4 | H3（只用于近景） | `h3-realism-people-t2v-i2v-r2v.safetensors` **在 gpu3** | 元数据显示训练时 `first_frame_conditioning_p=0.0`，即没有首帧条件；卡片没写支持 FL2V；负面约 10 人（int8 + turbo 下变形、偏黄、发糊、慢动作），正面约 4 人 | 偏黄（会加重 H3 本来就有的偏暖）；嘴不动 | R2：0 / 0.6 / 1.0 / 只放触发词不挂 LoRA；看 b* 偏移、SyncNet、光流、近景脸 | 中 | P2 |
| E8 | **VBVR** I2V LoRA | Q2 §1 | H3 | `H3-Licon-VBVR-I2V.safetensors` **在 gpu3** | 在 fl2va 上训练，针对物体重复、穿模、动作顺序；但训练数据是 512² 程序生成的推理题视频，只取了第 7000 步；数据许可 CC BY-NC 4.0；第三方实测 0 人 | 画面可能被推向 CG 感（推断）；**商用许可风险** | R3：0 / 0.4 / 0.7 / 1.0；看道具计数、SFace、ΔE、拉普拉斯方差 | 事实高，效果低 | P2；**许可已定（项目方 2026-10-31 原话：“加，不商用，纯粹自己研究技术”）：CC BY-NC，仅非商用技术研究**；已接为可选附加视频 LoRA（config/render_quality.json optional_video_loras，推荐 0.7，默认不加），A/B 见 data/ab/vbvr/（fredw-92/VB） |
| E9 | **Motion_Repair_V2**（JOKER141） | Q2 §3 | H3 | **在 gpu3**（文件名和大小与官方一致，sha256 待核对） | 针对异常慢动作；单独用约 0.9，第二遍用 0.2–0.3；作者承认高权重会有“CG or 3D-game characteristics”，还会影响声音；配 v1.3 会坏 | CG 感；声音变化 | R4：0 / 0.5 / 0.9；看光流、SyncNet，盲评问“哪个更像 CG” | 低-中 | P2（只用于慢动作镜头） |
| E10 | **LMS** sharpness r64 | Q2 §2 | 后期，只做 hero 镜头精修 | `minimax_h3_lms_v1.0_r64` **在 gpu3**；需要 ref2va 底模（gpu3 有 pruned int8） | 是 V2V 精修 LoRA：要把整段源视频接进 AddGuide(0)，强度从 1.0 起步（作者原话）；作者自己说 “it can alter color and lighting”，2 人说变暗、改脸；单遍用在 FL2V 上不行 | 变暗、改脸；24 GB 卡跑不了超过 5 s 或 0.5 MP | 与 Regenerate-2K 的 hero 精修一起做身份 A/B | 用法高，副作用中 | P3 |
| E11 | alibaba-pai **Acc-LoRAs**（PDD 蒸馏 8 步） | Q2 §6 | H3（替代 turbo） | 不在 gpu3，要下载（项目方闸门） | ComfyUI 已原生支持（shift 12/3，simple 8 步）；评价两极：好看 2 人，拖影或糊手 2 人 | 不能和 LightX2V 叠加 | E6 定版之后，若不满意再加组 | 中 | P3 |
| E12 | **NAGuidance** | Q2 §7 | — | — | **源码确认对 H3 无效**：H3 注意力不调用 `attn1_output_patch`，且强制 batch=1。第三方 H3NegativeLab 无人维护 | — | — | 高 | 不采用；“无字幕 / 无塑料皮肤”只能靠正向描述 |
| E13 | gpu3 上的杂项 LoRA：antiburn（第 2 段以后才用）、camera_motion（训练数据青橙调色）、DMAD 4step（T2VA，要用 lcm 采样）、flf2v_lora_v1（360° 定格） | Q2 §8 | — | 都在 gpu3 | 正常镜头一个都不要挂 | 误挂会冻住人物或偏色 | — | 中 | 加进“禁止默认挂载”清单 |

#### 首帧质感（Image 2.1）

| # | 方法 / 文件 | 来源 | 链路 | 需要的文件，是否在 gpu3 | 结论 | 风险 | 建议对比 | 可信度 | 优先级 |
|---|---|---|---|---|---|---|---|---|---|
| E14 | **Canon UltraReal**（作者用 Canon 1Ds 实拍训练，触发词 c2n0n，强度 0.5） | Q3 | 定稿出图 | `canon_qwen21.safetensors`（76 MB，可商用）：gpu3 和笔记本**都没有** | 唯一用真实相机照片训练、主打 “rich colors … beautiful bokeh” 的 Qwen 2.1 LoRA。注意：现用的 krea2_film_texture 是从 3000 张生成图里筛出来训的，不是真实胶片 | 与 H3 的偏暖漂移叠加后可能过暖；作者以外只有 2 人发过图 | F 组（见下） | 中低 | P2（需下载）；**已下载**（项目方原话：“用真实照片训练的 LoRA 看看效果”）：gpu33 `/root/claude-kimi-ns-studio-v1/ComfyUI/models/loras/canon_qwen21.safetensors`，79,743,888 B，sha256 `5d59914dfaf18dee544862f5c41b333005fdeb11233f04cc44607beac08f9b1a`（与 Civitai 版本 3352035 公布值一致），底模 Qwen 2.1（头部 ss_base_model_version=qwen_image_2，ai-toolkit，key 格式同 lin_wan_qi_v1）；Civitai 许可：可商用（Image/RentCivit/Rent/Sell/SellMerge）、允许衍生、需署名，底模另受 qwen-research 许可约束；A/B 见 data/ab/realphoto_lora/（fredw-92/RL） |
| E15 | **Restore LoRA**（ausboss，强度 0.5–0.75）作为精修护栏 | Q3 | 精修 | `qwen-image-2.1-restore`（1500 版和 1250 版各 152 MB，qwen-research 许可）：两台机器都没有 | 作者实测：脸部相似度 0.79→0.88，色彩偏移 1.9%→0.9%；能避免精修时凭空加出毛孔、雀斑和老态 | 皮肤偏光滑；作者测的是 edit 式重绘，和我们的低 denoise 接法不同 | F 组 | 高（作者实测） | P2；**已下载**（同上项目方原话）：gpu33 同目录 `qwen-image-2.1-restore.safetensors`（1500 版），159,436,584 B，sha256 `65de4f6c2468071d5aa6ffbd82c76bfee7cc8ac28fe960e91bbca4a58f43c08c`（与 HF LFS 及 Civitai 2989697/3390033 公布值一致），HF 卡 base_model Qwen/Qwen-Image-2.1，头部 qwen_image_2；许可 qwen-research-license（HF），Civitai 商用仅 RentCivit；1250 版未下载；A/B 见 data/ab/realphoto_lora/（fredw-92/RL） |
| E16 | filmstills_qwen2.1（0.4–0.5）、GrainScape（0.3–0.4）、Dot Film（硬闪光夜景） | Q3 | 定稿出图（按镜头类型选用） | 都不在 gpu3 | 没有任何 Qwen 2.1 的 Portra、ARRI、Leica、Vogue、亮面材质 LoRA（约 50 个关键词，0 结果）；GrainScape 的颗粒烘在图里，会在 H3 里闪烁 | 发色变脏；颗粒闪烁；Dot Film 会影响脸 | F 组 | 低-中 | P3 |
| E17 | **颜色做浓放到最后**：首帧 ColorMatch 0.5 → H3 → 以首尾帧为锚逐镜校色（B1）→ 全集统一 LUT → 颗粒 σ2 | Q3；00_summary 颜色 | 精修 + 后期 | KJNodes 在 gpu3；笔记本有 `ns_post.colormatch` | 首帧不要用浓色 LoRA 或重 LUT，因为 H3 会把颜色拉暖、拉灰、拉暗；浓色只在后期统一做 | LUT 的选择属审美，由项目方定 | X10 + 1 组 LUT 盲选 | 中 | P2 |

**F 组首帧对比**（Q3 §A/B）：
- **镜头与固定条件**：S1–S3 加一个亮面材质镜头 S4；种子 101 和 202；身份 LoRA @0.8。
- **各组设置**：
  - F0 现行：krea2 0.5，精修 PureLens 0.4 @0.22
  - F1 Canon 0.5
  - F2 Canon 0.4 + krea2 0.3
  - F3 filmstills 0.5
  - F4 GrainScape 0.35
  - F5 / F6 精修改用 Restore（1500 版 / 1250 版）0.75 @0.30
  - F7 首帧 ColorMatch 0.5
  - F8 Dot Film（只用于夜景）
- **指标**：对 master 的 SFace、脸部锐度、颗粒能量、发色 ΔE；每格送 H3 跑 5 秒，测脸部闪烁和颜色漂移；最后项目方盲选。
- **叠加上限**：身份 0.8 + 风格不超过 0.6 + 资产不超过 0.4，总和不超过 1.6；风格类 LoRA 一次只用一个。

### 按预计对质感 / 一致性影响排序（P2 执行顺序）

1. **B1 / X10 逐镜校色默认开，加 E17 的“浓色放到最后”**：颜色偏移是 ≥6 人确认的唯一强共识；Q2 的 8 项 H3 LoRA 都修不了颜色。只用 CPU。
2. **E6 先定 turbo 底座**：后面所有 H3 LoRA 都叠在它上面。文件都在 gpu3，零下载。
3. **E2 Ref2VA 加首尾帧加角色卡**：针对一致性。文件都在 gpu3；提示词按 ref_en 写；注意首帧要双接。
4. **E15 Restore 精修护栏，加 E14 Canon 实拍质感**：首帧质感决定 H3 的上限；需下载 228 MB（项目方闸门）。
5. **E1 FaceRefine**：只救远景小脸；需要装节点和依赖。
6. **E7 Realism-People 用于近景**：在 gpu3；必须先过偏黄和嘴不动这两关。
7. **E8 VBVR**：首饰和道具数量；在 gpu3；许可已定：仅非商用技术研究（项目方 2026-10-31：“加，不商用，纯粹自己研究技术”）；已接为可选附加视频 LoRA，A/B 在 data/ab/vbvr/。
8. **E9 Motion_Repair**：只用于慢动作镜头；在 gpu3。

不采用：E4（已符合）、E5、E12（无效）、E13（禁止默认挂载）。延后：E3、E10、E11、E16。
