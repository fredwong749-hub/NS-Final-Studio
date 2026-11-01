## 结论先看（WFLIB，2026-10-31）

- 社区 H3 流的"共识配置"与我们现行默认（official_base 24 步 + 首帧）差在三处：①几乎都用 **两段式**（低分辨率出动作 → 潜空间 3D 放大 → 少步 refine），②加速走 **整模蒸馏**（FastH3 / Singularity / 10Eros / PDD-Acc），而不是在基模上挂 4 步 Turbo LoRA，③ ref2va 一律 `ref_image_size=match`。
- 我们 Turbo 的"4 帧一顿 / 慢动作"在社区有专门的修法：ganloss 2026-09-09「pdd-acc lora correct slow motion」——用阿里 PAI 的 PDD 8 步 Acc LoRA 换掉 4 步 Turbo（官方 README 直接拿 Turbo 4step v1.1 做对照）。权重只有 1.37 GB，但要装节点包。
- gpu33 已有、今天就能跑的社区配方：FastH3-OmniRef 8 步（`fasth3_omniref_8step_pruned_int8_convrot`）+ SelfLift 两段放大（`minimax_h3_latent_upscaler_3d_conv_v1_bf16`），两台 ComfyUI 都已装 SelfLift 与 LBH 放大器节点。gpu36 缺 FastH3 omni 与放大器权重。
- 社区补充（community/ 84 个流，49 个来源）：①Larryvrh Turbo README 原话"4 步遇大动作会拖影/鬼影，Using 6–8 steps largely removes it"，strength 保持 1.0（糊/拖影调 1.05–1.2，过锐调 0.8–0.95）——我们 4 步 Turbo 的鬼影/卡顿应先试 8 步；②sepiablue 给了**竖屏**做法：ref2va 736×1280 出片 → LBH 3D 放大到 1104×1920，零缺节点；③SigmaShift 主流 12/3，少数 12/6（foxydits SEED HUNTER）与 6/3（star7code），可做慢动作 A/B；④gpu33 上已有的 Motion_Repair_V2 LoRA 在 mdkberry 分镜流里以 0.6 与 H3_Combat_V2 叠用。
- 两台都没装的节点包是主要缺口：H3 FaceRefine（脸部跟踪重绘）、PDD-Acc、Motion Context（长镜头接续）、VOSR2、VHS（可替换）。装包需重启 ComfyUI，本次没动。

## 按我们的问题归类的推荐

| 问题 | 社区做法（工作流） | 关键参数 | 现在能否跑 | 证据强度 |
|---|---|---|---|---|
| 身份一致（林晚） | Ref2VA + 角色设定图：`ganloss/2026-10-08 qwen2.1 character sheet` 出四宫格设定图 → `ganloss/2026-10-26 FastH3 omni` / `singularity v2` r2va 吃设定图 | ref_image_size=match（39 个 r2va 流里 37 个）；设定图 Qwen2.1 euler/simple 25 步 cfg1，QI2.1_AnyAngle 0.6，2.2MP；视频 1344×768×124 | 设定图流：能（两台都有模型；AnyAngle 只在 gpu33）。FastH3 omni：gpu33 能 | 中：作者示例 + 社区一致取值；未见量化对比 |
| 身份一致（换人保表演） | `ganloss/2026-10-21 character swap/H3_Character_Swap_v1_Ref2VA.json`（akatz-ai LoRA） | 20 步 res_multistep/simple，LoRA 1.0，Turbo 关，0.4MP 起步、768p 用 0.98MP；源视频须 24fps；17n+5 帧 | 能（gpu33 有 h3_character_swap_v1.5 与 pro4500_1000；底模用我们的 ref2va pruned） | 中：作者 README 明说 V1 长镜头会漂表情/时序 |
| 慢动作 / 4 帧一顿 | `ganloss/2026-09-09 pdd-acc lora correct slow motion`（i2v、r2v 各一） | MiniMaxH3PDDAccApply nfe 8、lora 1、head 1；第一段 8 步 euler，SplitSigmas 4→放大→ManualSigmas 0.9035/0.8/0.6316/0.3158/0；shift 12/3 | 不能：缺 PDD-Acc 节点包 + 2×1.37 GB 权重 | 中高：目录名即"修正慢动作"，官方 README 与 Turbo 4step 并列对比 |
| 慢动作 / 鬼影（最便宜的一刀） | Larryvrh Turbo README：4 步大动作拖影，6–8 步基本消除；`community/Stable_Yogi__…keep_the_same_person…/minimaxH3ReferenceToVideo_turbo8Step.json`（ref2va + fl2v turbo 8step v1.0，res_multistep/simple 8 步，shift 12/3） | 8 步、LoRA 1.0；也可试 shift 12/6、6/3 | 能（gpu33 有 fl2v_turbo_8step_v1.0/v1.1、ref2v_turbo_8step_v1.1；零缺节点） | 中：作者 README 明说 |
| 慢动作（另一路） | FastH3 整模蒸馏：`2026-09-22 fasth3/2 …latent_upscale_fast_motion`（12 步 split 8）vs `1 …raw_bigface_10s`（8 步） | euler/beta；BlockSparse vsa τ10；fast_motion 版给第一段更多步数 | omni 版能（gpu33）；v2 需 22 GB 权重 | 中：作者把"fast motion"单独做成一版 |
| 静止镜头 | 同上；另 `MiniMaxH3AddGuide` 中间帧引导（`2026-10-12 fastH3 trim/…multiframe`，frame_idx 60/160/240） | 用中间关键帧强迫动作发生 | AddGuide 节点已装，能（底模换我们的 fl2va） | 低-中：未见对比 |
| 多腿 / 鬼影 | ①潜空间放大用学习型 3D upscaler 而不是插值（LBH README：避免"重影/双像"）；②长镜头接续时提示词开头先复述上段结尾（Motion Context 作者：否则"两种都渲染"→多出人）；③两段式第一段只 0.2MP 出构图 | LU3D target 1280×704 或 1.0MP；第二段 3 值 ManualSigmas 0.9035/0.6316/0.3158/0 | ①能（gpu33）；②需 Motion Context 包 | 中：机制有作者说明；多腿本身无专门流 |
| 脸部细节 | `community/Carasibana__ComfyUI-H3-FaceRefine`（er_sde 8 步 denoise 0.4、fl2v turbo 8step、768 画布、SAM 脸形遮罩，362 帧长片）；`ganloss/2026-09-11 face refine`（bigface_slow_motion / fast_motion）与 `singularity v2 face_refine`：跟踪裁脸 768² → 第二遍 H3 重绘 → 贴回 + VOSR2 | H3FaceTrackCrop yolov8 conf0.35 crop2.5 canvas768 平滑 21/51；PerFrameDenoise 小脸×1、大脸×0.35；第二遍 beta 8 步 denoise 0.4（fastH3 版 0.5）；Stitch face_only feather24 colour_match 1；VOSR2 wavelet 色彩对齐 | 不能：缺 H3-FaceRefine + VOSR2 包；退而求其次用 SelfLift 放大（能） | 中高：作者连发 3 个版本（09-11、09-22、10-23） |
| 口型 | 保留 H3 原生音频（我们已是 h3）；face refine 里用 `MiniMaxH3NativeAudioLock` 保证重绘时不改音频；LatentSync 1.5（2025 老流，wan1.3B tile）只作兜底 | LatentSync lips_expression 1.5、20 步 | NativeAudioLock 在 FaceRefine 包里；LatentSync 缺节点 | 低：社区 2026 年没有新的口型流，说明 H3 原生口型已是主路 |
| 长镜头 | `ganloss/2026-09-04 …ref2va-motion-context-step1`、`2026-09-28 qwen2.1+fasth3/…contextmontion_longvideo` | context_length "22"、audio_context_length 24（24 帧=1 s 声音，3 的倍数对齐音频格）；变化放在 1.5–2 s 之后；参考图对整段生效、没有时间轴 | 不能：缺 Motion Context 包 | 中高：作者写了"已测"参数 |
| 竖屏高清 | `community/sepiablue-ai__minimax_h3_workflows/minimax_h3_ref2va_LBHupscaler.json` | ref2va 736×1280×124 match，euler/simple 4 步，shift 12/3 → LU3D target 1104×1920 align16 | 能（零缺节点；权重用 gpu33 的 conv_v1_bf16 与 ref2v_turbo_4step_v1.0 代替） | 中 |
| 分镜一致 | `2026-09-28 qwen_image_2_1_storyboard_2kupscale` / `2026-10-13 …character_data`：同一人 3×3 宫格分镜 2.4MP → 切格放大 → 每格做首帧 | Qwen2.1 25 步 cfg1；提示词"Use the adult woman in the image as the sole identity reference… nine panels… same physically buildable stage" | 缺 easy-use 的 forLoop/imageSplitGrid（可用内置裁切替代） | 中 |
| 泛红 / 色偏 | 社区没有专门流。可借：H3FaceStitch colour_match=1、VOSR2 color_alignment=wavelet；Qwen 端 texture_fix_vae（我们已有）；Singularity v2 换 LightVAE 解码 | — | 部分 | 低：都是间接手段，需要我们自己 A/B（对接 LEARNED_SPECS 的脸颊 a* 指标） |

## ep02 实测前 10（按"能马上跑 × 对我们问题的命中"排序）

1. **竖屏 ref2va + 3D 潜空间放大**（`community/sepiablue-ai__minimax_h3_workflows/minimax_h3_ref2va_LBHupscaler.json`）——唯一现成的竖屏高清配方，零缺节点；我们是竖屏短剧，直接对标。权重替换：放大器用 conv_v1_bf16，Turbo 用 ref2v_turbo_4step_v1.0_768p（或改 8 步）。
2. **Turbo 8 步 vs 4 步**（`community/Stable_Yogi__…/minimaxH3ReferenceToVideo_turbo8Step.json`）——零缺节点，最便宜地验证"4 帧一顿/鬼影是步数不够"这一社区结论；同时扫 shift 12/3、12/6、6/3。
3. **FastH3-OmniRef r2va**（`ganloss/2026-10-26 FastH3 omni/fast_h3_omni_base.json`）——gpu33 权重齐，VHS 换 SaveVideo 即可；整模蒸馏 8 步，对比我们 24 步基模的动作量、J4、身份。
4. **FastH3-Omni + SelfLift 放大**（`…/fast_h3_omini_latent_upscale.json`）——gpu33 齐（LoRA 先不挂或用 v1.0）；测脸部细节与鬼影。
5. **官方 r2va 20 步对照**（`ganloss/2026-08-05 minmaxH3/video_minimax_h3_r2v1.json`）——零缺件对照组，判断我们 24 步配方有没有别的偏差。
6. **Qwen 2.1 角色设定图**（`ganloss/2026-10-08 qwen2.1 character sheet/image_qwen_image_2_1_character_sheet_with_clothes.json`）——全齐；给 1–4 当 ref 图，主攻身份一致。
7. **PDD-Acc 修慢动作**（`ganloss/2026-09-09 pdd-acc lora correct slow motion/`）——命中慢动作；权重 2×1.37 GB，但要装 Jalen-Brunson 节点包 → 需批准装包+重启。
8. **项目方示例 Singularity v2 r2va**（`singularity_v2/minimax_h3_singularity_V2_r2va.json`）——项目方点名；缺 21 GB 底模（WAS pruned）+ LightVAE + v2 放大器 → 需批准下载。
9. **H3 Face Refine**（`ganloss/2026-09-11 face refine/…bigface_slow_motion.json` 或 `community/Carasibana__ComfyUI-H3-FaceRefine/H3_Face_Refine_Auto_Select.json`）——脸部细节最强，带 NativeAudioLock 不动口型；需装 H3-FaceRefine（+VOSR2）。
10. **Motion Context 长镜头**（`ganloss/2026-09-04 MiniMax H3 - ref2va -motion-context-step1.json`）——单镜 >6 s 或无缝接续；需装 NikoDemon80 包。

备选：Character Swap v1（脸不像但表演对时二次换脸，LoRA 已有）；ganloss 两段式 r2v latent upscale（0.2MP 出构图压多腿）；fastH3 trim multiframe 的 AddGuide 中间帧（节点已装）。

排序理由：1–6 不需要装任何东西，可以立刻交给 LAB；7/9/10 需要装节点包（一次重启可同时装 PDD-Acc、H3-FaceRefine、VOSR2、Motion Context、VHS），8 需要下载 >5 GB——这两件要总调度批准。泛红/色偏社区没有专门方案，继续用我们自己的脸颊 a* 指标做 A/B。

## 许可登记（已下载权重，2026-10-31，总调度批准）

位置：gpu36 `/root/work/fredw/comfy/ComfyUI/models/`（gpu33 未下）。下载日志：gpu36 `/root/work/fredw/wflib_dl/dl.log`。三个文件均已在 gpu36 全部 3 个实例（:8188/:8189/:8190）的 `/object_info` 中出现。

| 文件（目录） | 大小 | sha256 | 来源（固定版本） | 许可 | 识别节点 |
|---|---|---|---|---|---|
| minimax_h3_ref2v_turbo_4step_v0.1_comfyui_bf16.safetensors（loras） | 1,956,193,000 B | 5b9ab5ade15d0775676d01a907268a69a1468dc6033b3b0d3ded5502f3ebb84c | huggingface.co/Comfy-Org/MiniMax-H3 @912b6e38，loras/ | MiniMax H3 Community License | LoraLoaderModelOnly（内置） |
| minimax_h3_latent_upscaler_3d_conv_v1_fp16.safetensors（latent_upscale_models，新建目录） | 690,592,672 B | 043e5a48e161610ef6c3ea974645220354d06fa618abca15f76d084812eb55c2 | huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler @3f941d5d | Apache-2.0 | SelfLiftH3Sampler、MinimaxH3LatentUpscaler3D（两台已装） |
| Minimax-h3_Singularity_ref2va_v2_pruned_int8_convrot_r2.safetensors（diffusion_models） | 20,967,648,216 B | 21ed960132b4e97ff02e6362d02f9fe4c673cd345f3ffee63be1ef2520c4ed47 | huggingface.co/WAS/Minimax-h3_Singularity_v2_pruned @2c54612f（上游 WarmBloodAban/Minimax-h3_Singularity，Apache-2.0 标注） | MiniMax H3 Community License（衍生模型沿用） | UNETLoader（内置，README：weight_dtype=default） |

<span style="color:red">**许可注意（标红）**：MiniMax H3 Community License 不是非商用许可，但有两条硬限制：①「Applicable Territory」排除 **欧盟、英国、韩国、美国**——在这些地区使用/分发不在许可范围内；②商用产品年收入 >2000 万美元需书面授权，且商用产品界面须显著标注 "MiniMax H3"。gpu36 系统时区是美东，需由总调度确认机器与发行地区不在排除范围。</span>

未下载及原因：
- LightVAE（lightx2v/LightVAE，Apache-2.0）：Lite 编解码器必须用新节点 "Load H3 LightVAE" 加载，现有节点不能直接用 → 按批准范围不下。项目方示例里的 `minimax_h3_lightvae_lite_vae_int8_convrot.safetensors` 在 HF 上找不到同名文件。
- 放大器 "v2"（`minimax_h3_latent_upscaler_3d_fp32_v2.pth`）：官方仓库只发布了 v1（conv_v1），且 .pth 不在批准范围；第三方 KENIC-1 的 "fp16_V2" 没有许可、没有说明，不下。已用官方 conv_v1_fp16 替代，SelfLift README 推荐的就是这个仓库。
- PDD-Acc 两个权重：需要新节点包，节点包安装被权限系统拦截（见下），权重也没下。

## Civitai 补充（CIVIT 第 2 批，详见 docs/ep02_iter/civitai_study.md §3/§5）

- 第二段 ManualSigmas 社区分布：0.9035/0.8/0.6316/0.3158/0 ×11；0.9231 起 ×8；0.9035/0.6316/0.3158/0 ×8；0.85/0.725/0.4219/0 ×8。与 ganloss 取值一致，0.85 起的一档更"轻"，可作为 refine 强度下限对照。
- 社区 LoRA 实际强度中位数：Motion Repair v1 0.25、V2 0.4（低于 EXPERT 手册引用的约 0.9，需 A/B）；Exposure/DayNight 滑杆 0.1；Detail Slider 2.0；电影感 V2 0.85 / V1 0.6；realism-people 0.4。
- 换人配方（Civitai 2942000）：shift 10/3，底图 0.5MP；原人脸 blur_keep_mouth（模糊脸但保留嘴部，利于口型）；脸部特写作为 `<Picture 2>`。
- Spectrum 的 H3 版默认 audio_blend_weight=0，作者称音频混合会导致口吃——口型问题排查时注意不要开音频混合。
- 社区常用而我们缺的节点：SpectrumApplyMiniMaxH3、MiniMaxH3TurboSampler/TurboLoRA、SolAttnPatch、H3SigmaRefiner、H3SLAAttention、SeedVR2 三件套、RTXVideoSuperResolution、RIFE VFI、VHS。
- 缺件线索更新：gpu36 `models/loras/civitai/` 已有 taomate 3step（`minimax_h3_taomate_3step_lora_avg_rank_19_bf16`）、`FastH3_comfyui`（1 GB LoRA，**不是** 22 GB 的 FastH3 v2 整模）、`h3_hard_gravy_6stepturbo_r64_v1.0`、MMH3 Exposure/DayNight/Realism 滑杆等；DMAD+Hyperflow 在 HF silveroxides/MiniMax-H3_tests；VNCCS PoseStudio 在 HF MIUProject。
