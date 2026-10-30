# 画质深挖 02：H3 附加 LoRA 与负面引导（VBVR / LMS / Motion Repair / Realism / Turbo 版本 / PDD / NAG / gpu3 杂项）

调研日期：2026-10-31。只读：没下载模型、没跑 GPU、没 ssh、没改代码、没碰 git。
只读取了 HF 模型卡、讨论区（逐帖用 HF API 原文读取）、safetensors **文件头**（HTTP Range 只取前几 KB 的元数据，不是下载权重）、ComfyUI 源码。

置信度：**高** = 官方原文 / 文件元数据 / 源码；**中** = ≥2 个独立用户实测一致；**低** = 单帖或我的推断（会写“推断”）。
引文保留原文语言；“用户数”只数在帖子里说自己实际跑过的人。

当前锁定设置（作为所有 A/B 的基线 **B0**）：`minimax_h3_fl2va_pruned_int8_convrot` + `minimax_h3_fl2v_turbo_8step_v1.1_768p` @1.0，shift 6/3，euler/simple 8 步，cfg 1（BasicGuider），int8 视频 VAE，768×1344，243 帧，24 fps。

---

## 0. 结论速览

| # | 项目 | 一句话结论 | 链路位置 | gpu3 有？ | 最大风险 | 置信度 |
|---|---|---|---|---|---|---|
| 1 | VBVR LoRA | **值得 A/B**：确实是在 FL2VA bf16 上训的，针对物体重复/穿模/动作顺序。但训练数据是**程序生成的 512² 合成推理题视频**（迷宫、数独、积木），只训了 7000 步，rank 16。**没有任何第三方画质反馈** | H3 主生成 | 有 | 可能把画面往“干净 CG”方向推；数据许可是 CC BY-NC 4.0（商用风险） | 高（事实）/ 低（效果） |
| 2 | LMS 锐化 LoRA | **不要单遍用在 FL2V 主生成里**。它是在 **ref2va pruned** 上训的 V2V 精修 LoRA，必须把**整段源视频**接进 `MiniMaxH3AddGuide(frame_idx=0)`。作者自己承认“it can alter color and lighting”，2 个用户报告变暗、改脸 | 后期精修（H3 第二遍） | 有 | 变暗、改脸、塑料感；243 帧 768×1344 加整段 guide，3090 很可能放不下 | 高（用法）/ 中（副作用） |
| 3 | Motion Repair V2 | gpu3 上的 `Motion_Repair_V2` **就是 JOKER141 仓库的同名文件**。作者推荐单独用约 0.9、第二遍 0.2–0.3。目标正是“异常慢动作”。和 v1.3 叠加会坏（1 人），和 v1.2 正常 | H3 主生成 | 有（文件名不同） | 高权重会出现“CG 或 3D 游戏感”，并影响声音（作者原话） | 中（作者）/ 低（独立用户） |
| 4 | fal Realism People | **对我们的配置（pruned int8 + turbo + 首帧锁定）风险最高**。元数据显示它在 FL2VA 底模上训练，但 `training_strategy=text_to_video`、`first_frame_conditioning_p=0.0`，**训练时没有首帧条件**。负面独立用户约 10 人，正面约 4 人 | H3 主生成 | 有 | 黄色偏色、发糊、慢动作、嘴不动、肢体变形、和其他 LoRA 叠加崩坏 | 中 |
| 5 | LightX2V Turbo 版本 | 截至 10-31，**FL2V 8step v1.1 仍然没有任何社区实测反馈**（HF #57–#60、全网搜索都没有）。四个版本的文件结构完全相同（rank 128、alpha 8、同一组模块），差别只在权重本身 | H3 主生成 | 都有 | v1.3 叠其他 LoRA 会坏；v1.2 被说画质和头发变差 | 高（结构）/ 低（画质比较） |
| 6 | alibaba-pai Acc（PDD） | 8 步 PDD 蒸馏，FL2VA/Ref2VA 各一个，ComfyUI 已原生支持（PR #15908）。社区评价“good at 8 steps”，但快速运动会糊手、远处小脸变形。是 Turbo 的**替代品**，不是叠加件 | H3 主生成 | **没有** | 需要下载 1.7 GB；快速运动拖影；不能和 lightx2v 一起叠 | 中 |
| 7 | NAGuidance | **ComfyUI 核心的 NAG 节点对 H3 完全不起作用**（源码确认，两个独立原因）。第三方 `ComfyUI-H3NegativeLab` 专门给 H3 实现了 NAG 式负面引导，但只有 6 个赞和 1 条没人回的报错 | H3 主生成 | 不适用 | 接上核心 NAG 只会白白多算一遍 uncond；第三方节点需要装代码，兼容性没验证 | 高（核心无效）/ 低（第三方） |
| 8 | gpu3 上的 4 个杂项 LoRA | 都**不是画质增强件**：续接防烧脸（只能用于第 2 段以后）、运镜、DMAD 4 步蒸馏（Turbo 替代品）、360° 定格环绕。**正常镜头一个都不要挂** | 不进主链 | 有 | 误挂会改运镜、改色、改动作 | 高 |

**对项目方三个已知问题的直接判断：**
- **颜色偏暖、偏灰、偏暗**：这 8 项里**没有一个是修颜色的**。LMS 和 Realism 反而都有“变暗”或“黄色偏色”的报告。颜色仍然要靠后期以关键帧为参照做校正（见 h3_deep/03 §2.2）。（中）
- **小脸崩**：没有任何 LoRA 被证实能修远景小脸（PDD 有人明确说远处小脸还会变形）。（中）
- **道具重复或穿模**：只有 VBVR 是专门针对这个问题的，但只有作者自己的 6 组对比。（低）
- **慢动作**：Motion Repair V2 是专门针对这个问题的；Realism LoRA 有人反映会**导致**慢动作。（低-中）

---

## 1. VBVR LoRA（LiconStudio/Minimax-H3-VBVR，`H3-Licon-VBVR-I2V.safetensors`）

来源：模型卡 <https://huggingface.co/LiconStudio/Minimax-H3-VBVR>；comfyui-wiki <https://comfyui-wiki.com/en/news/2026-10-23-h3-vbvr-lora>；文件头元数据（Range 读取）。

### 1.1 它修什么（官方）
- 模型卡原文：“It improves object consistency and character action logic, reducing unintended object duplication, clipping, and interpenetration during motion and interactions.”（高）
- 三条要点：“Reduced object duplication”、“Reduced clipping and interpenetration”、“Improved character action logic”。（高）
- 6 组验证样例（validation/1–6）都是**写实室内、手拿物体**的场景。例如 #1 的 prompt：“preserving the vendor, the empty paper bag, and exactly three red apples on the counter … places the first apple into the bag, then the second, then the third.” 所用 prompt 正是 H3 官方的结构化格式（“For the target video, at 0.00 seconds … <Picture 1> … is fully referenced.”）。（高）
- comfyui-wiki：“The two below are 864x480, 384 frames long, 12.25 seconds each.”（高）

### 1.2 训练底模与训练方式（文件元数据，高）
| 字段 | 值 | 含义 |
|---|---|---|
| `ss_minimax_h3_task` / `ss_minimax_h3_base_family` | `fl2va` / `fl2va` | **确实是 FL2VA**，kimi-1424 的说法正确 |
| `ss_sd_model_name` | `minimax_h3_fl2va_bf16.safetensors` | 非 pruned 的 bf16 底模 |
| `ss_network_dim` / `ss_network_alpha` | 16 / 16 | rank 16 |
| 训练层 | `attn.qkv_proj, attn.out_proj, mlp.fc1, mlp.fc2`（50 个 block；**不含 adaln，不含 token_refiner**） | 在 pruned 底模上加载没有形状问题 |
| `ss_steps` / `conversion.source_filename` | 7000 / `VBVR-R16-ffn-step00007000` | 计划的一个 epoch 是 108,724 步，**实际只取了第 7000 步**（约 6%） |
| 数据集 | 185 个子集，全部 `resolution [512,512]`、`target_frames [5]`、`max_frames 345` | 分辨率 512²（comfyui-wiki 写的 “1280x720” 来自 `modelspec.resolution` 这个默认字段，**以数据集字段为准**） |
| 子集名称 | `G-18_grid_shortest_path`、`T023_sudoku_stepwise_completion`、`T019_chess_mate_in_one`、`O-75_communicating_vessels`、`G-26_maintain_object_identity_different_objects` 等 | 全是 **VBVR 程序生成的推理题** |
| `ss_minimax_h3_video_only` / `ss_minimax_h3_audio_loss_weight` | True / 0.0 | 只训视频，不训音频 |
| `ss_minimax_h3_shift_video` | 12.0 | 训练 shift 12（我们推理用 6，属于常态差异） |
| `ss_minimax_h3_guidance_loss_scale` | 4.0 | 用了保持 CFG 蒸馏性质的 guidance loss |

- 数据集卡 <https://huggingface.co/datasets/Video-Reason/VBVR-Pro-SFT-Video>：“1.24M programmatically generated reasoning instances across 250 parameterized tasks”，“Resolution 512 × 512”，16 fps；**数据许可 “Data License CC BY-NC 4.0”**。LoRA 自己标的是 apache-2.0。（高）
- **推断（低）**：训练素材是平面几何图形和棋盘一类的合成画面，不是真人实拍。作者在写实场景上的样例看起来没被带偏，但在我们这种“胶片/时装大片质感”的近景里，强度高时可能把皮肤和布料推向更干净、更平的 CG 观感。这一点需要靠 A/B 验证。

### 1.3 强度、Turbo 兼容性、模式
- **官方没给强度。** comfyui-wiki 原文：“no ablation over LoRA strength, so how far the effect holds at lower strength is not documented.”（高）
- 讨论 #4 有人问训练时的 strength/shift，作者答“不是很明白，能明确一下问题吗”，没有给出数字。<https://huggingface.co/LiconStudio/Minimax-H3-VBVR/discussions/4>（高）
- 唯一出现过的数字：WebSearch 摘要说某合并模型（Asirus NEXORA）用了 VBVR 0.40。但该模型卡现在是 gated，我打开后**没有看到任何 LoRA 系数**，所以无法核实。（低，不采用）
- 模式：作者在 #2 说 “Yes, it works with T2V too … I labeled it as I2V because the VBVR data can only be used in an I2V training setup.” R2V 作者没测（#3：“我自己还没测”）。（高：作者原话）
- **和 Turbo LoRA（v1.1 8step / v1.2 / v1.3）的兼容性：没有任何资料。** 模型卡、comfyui-wiki、4 个讨论帖都没提。样例是否用了 Turbo 也没写。（高：确实没有）

### 1.4 社区反馈（按独立用户数）
- 下载 7,353，赞 146（10-31 API）。
- 4 个讨论帖：#1 “just come to support, not yet test”；#2 问 T2V；#3 问 R2V；#4 问参数。**没有任何一条实测画质反馈。**
- comfyui-wiki 评论区为空。
- 结论：**0 个独立实测用户**。

### 1.5 对我们
- **链路位置**：H3 主生成（挂在 turbo LoRA 旁边）。
- **文件**：`H3-Licon-VBVR-I2V.safetensors`，149,238,584 字节，sha256 `19ba9d18c06eaecebd11c1ca1d27a0277f414d43370124e3cfcb33a113e9f886`。**gpu3 已有**，可以用 sha256 核对是不是同一份。
- **风险**：①和 v1.1 8step 叠加的效果完全未知；②合成数据可能削弱写实质感（推断）；③NC 数据许可的法律风险要交给项目方判断；④只训了 6% 个 epoch，效果可能偏弱，需要较高强度。
- **建议对比实验**（同镜头、同种子、同一 ComfyUI 进程内按固定顺序跑，项目方盲选）：
  - 镜头选**道具多的中景**：手拿杯子或首饰，或者两人交接物体。
  - 组别：B0；B0+VBVR 0.4；B0+VBVR 0.7；B0+VBVR 1.0。每组 2 个种子。
  - 指标：
    - 道具计数：每秒抽 1 帧，人工数首饰和道具数量，记录重复或消失次数。
    - 穿模：人工标记次数。
    - 脸：SFace 相似度曲线（每帧对首帧人脸）。
    - 颜色：全片 ΔE2000 均值，以及首尾各 10 帧对关键帧的 ΔE。
    - 尾帧贴合：最后 12 帧对尾关键帧的 SSIM。
    - 质感：脸部裁切的拉普拉斯方差（防止变“平”）。

---

## 2. LMS 锐化 LoRA（`minimax_h3_lms_v1.0_r64`）

HF 仓库：**Alissonerdx/Minimax-H3-ComfyUI** <https://huggingface.co/Alissonerdx/Minimax-H3-ComfyUI>（文件 `loras/minimax_h3_lms_v1.0_r64.safetensors`）。文档 <https://huggingface.co/Alissonerdx/Minimax-H3-ComfyUI/blob/main/docs/lms.md>；comfyui-wiki 中文页 <https://comfyui-wiki.com/zh/news/2026-09-11-minimax-h3-sharpness-lora>。

### 2.1 设计用途（作者原文，高）
- “a rank-64 LoRA for sharpening a source video while keeping a natural, photorealistic appearance. It is intended mainly as a second pass over an existing clip.”
- “Put the source video into `MiniMaxH3AddGuide`, connect the video VAE, use `frame_idx = 0`, and match the output resolution and frame count to the source. **Start with LoRA strength `1.0`.**”
- 固定 caption：“Enhance this video with sharp, crisp details while preserving a natural photorealistic appearance.”
- “The model was trained primarily for `ref2va` with guide latents alone. Combining Add Guide with additional native references is experimental”
- README：“The LMS, Style Transfer, VFX Edit and Head Swap models use an aligned source-video guide … the guide shares the generated video's spatial and temporal grid.”
- **更正 kimi-1040**：kimi 写的 “about 0.8 strength; 1.0 on both passes is too extreme” 出自 comfyui-wiki（原文：“强度设为 0.8 左右可让皮肤和纹理保持自然；两遍都推到 1.0 会过于极端”）。**作者文档写的是从 1.0 起步**，作者自己贴的样例用 0.9（#2：“strength 0.9”）。两种说法都列出来，以 A/B 为准。
- **补充**：`frame_idx=0` 这一项接的是**整段源视频**（对齐的 guide latent），不是一张首帧图。

### 2.2 文件元数据（高）
- `ss_base_model_version = minimax_h3_ref2va`，`name = minimax_h3_ref2va_sharpness`，ai-toolkit 0.13.4，4000 步，rank 64，F16。
- 训练层**包含 `adaln_proj.linear`**（50 层）和 token_refiner。作者在 #9 说：“The LMS was trained on the ref2va pruned base”。在非 pruned 的 bf16 底模上会报 adaln 形状错误（#9 用户实测）。
- 作者官方工作流（`workflows/minimax_h3_lms_workflow.json`，我解析了节点参数）：
  - LoRA：`minimax_h3_ref2v_turbo_4step_v0.1` @1 + LMS @1
  - 采样：euler、simple 8 步、`MiniMaxH3SigmaShift 12/3`、`CFGGuider 1`
  - 尺寸：`EmptyMiniMaxH3LatentAV 1344×768×124`，`MiniMaxH3AddGuide [0]`
  - 用的是 **ref2va + ref2v turbo**，不是 FL2V。

### 2.3 单遍用在 FL2V 上可行吗
- comfyui-wiki 中文页：“主要用途是作为已生成片段的第二遍处理，不过也可用于直接生成。”同时也写了“它必须配合 Add Guide 节点才能工作，因为训练依赖 guide latent”。（高：转载方原文）
- monstari（#4，FL2VA）：“It works but not as good.”（低：1 人）
- **推断（低）**：我们的 FL2V 单遍生成没有对齐的源视频 guide。LoRA 学到的是“照着 guide 加细节”，没有 guide 时它的行为不在训练分布内。**不建议单遍用。**

### 2.4 副作用（按独立用户数）
| 现象 | 用户 | 原文 |
|---|---|---|
| 玻璃/塑料感、比原视频暗 | MavenDE（#2） | “my look like there would be too strong lora - glass/plastic look … The output seems to be darker than the original video” |
| **作者承认会改颜色和光线** | Alissonerdx（作者，#2） | “If the LoRA is too strong, you can reduce the strength, and yes, it can alter color and lighting.” |
| 明显改脸 + 变暗 | slikvik55（#2） | “it's really changing the faces quite a lot too (along with a bit of darkness)” |
| 当普通 LoRA 用在两段式第二段，效果“mixed” | Dunc4n1dah0（#22） | “results are "mixed" at most.” |
| 不按作者工作流、直接 Load LoRA 效果不好 | safesnail（#15） | “not getting good results”；作者答 “This uses Add Guide and isn't a regular LoRa” |
| 显存/时间：24 GB 做不了 >5 s 或 >0.5 MP | Rkss（#8） | “I have 24gb vram and It's impossible to do any clip that has > 5 seconds length, > 0.5Megapixels.” |
| 16 GB 跑 10 s 1080p 卡死 | liuxingsyue（#8） | “it immediately stalled” |

- **结论（中）**：至少 2 个独立用户加上作者本人都指向“变暗 / 改光线 / 改脸”。这正好和项目方“颜色偏暗、脸要一致”的诉求相冲突。还有 1 个 24 GB 用户说长片段、高分辨率根本跑不动。
- 官方 2K 包：Kijai 的 refiner 拆分说明 “The refiner part ONLY, doesn't include the LMS or the lightx2v turbo.” <https://huggingface.co/Kijai/MiniMax-H3-experimental>。也就是说 Open-H3-Regenerate-2K 本身是“refiner + LMS + turbo”的组合，LMS 在那里是**放大精修那一遍**的组件。（高）
- 许可：#26（10-29）有人问 LMS 的许可，作者还没回答。仓库的 LICENSES.md 只覆盖 Character Swap 和 Motion Transfer。（高：确实未声明）

### 2.5 对我们
- **链路位置**：后期，属于 H3 第二遍 V2V 精修（hero shot 才用），**不进主生成**。
- **文件**：`minimax_h3_lms_v1.0_r64.safetensors`，1,239,664,536 字节，sha256 `16f3195b…acf60c`（完整值见 §9）。**gpu3 已有。**还需要 `minimax_h3_ref2va_pruned_int8_convrot` 底模，gpu3 有没有我没法查，需要确认。可选再加 ref2v turbo（gpu3 有 4step v1.0 / 8step v1.1）。
- **风险**：变暗、改脸、塑料感；243 帧 × 768×1344 再加同尺寸 guide，token 数大约翻倍（约 145k+），3090 很可能 OOM 或极慢（Rkss 的 24 GB 报告）；许可未声明。
- **建议对比实验**：
  - 先用 2 个 hero 近景，每个裁成 124 帧来测（如果 243 帧跑不动就记 OOM）。
  - 组别：原片 / LMS 0.6 / LMS 0.9 / Open-2K refiner 链路（如果已经搭好）。
  - 指标：
    - 脸：SFace，对原片同帧（看是不是改了脸）。
    - 颜色：ΔE2000 对原片，以及对关键帧。
    - 亮度：平均 L* 的差值（看是否变暗）。
    - 锐度：脸部高频能量（拉普拉斯方差），对原片的比值。
    - 成本：显存峰值和耗时。

---

## 3. 动作连续性修复（JOKER141/MiniMax-H3-General-Motion-Continuity-Repair）

来源：<https://huggingface.co/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair>

### 3.1 文件身份
- 仓库里有两个文件：`Motion_Repair.safetensors`（V1，元数据 name=“UFC”，1600 步）和 **`Motion_Repair_V2.safetensors`**（元数据 name=“fixv2”，2400 步，epoch 17）。两者都是 ai-toolkit 1.18.3 训练、rank 16、BF16，训练了 attn + mlp + token_refiner，**不含 adaln**。（高）
- **gpu3 上的 `Motion_Repair_V2` 就是这个仓库的 V2**：155,110,272 字节，sha256 `edfa0e2858caeba7be9108883f61da8525d3c58af998c94ac7a449d9603d7574`，用 sha256 一比就能确认。MBen1986 在 lightx2v #57 里用的也是这个文件名。（高：文件名和大小一致；sha 需要到 gpu3 上核对）
- 底模分区：元数据只写了 `ss_base_model_version = minimax_h3`，**没有写 fl2va 还是 ref2va**，模型卡也没写。（高：确实没写）

### 3.2 它修什么（作者原文，高）
- “Current A/B testing shows improvements in **unwanted slow-motion behavior** / missing motion transitions / abnormal limb trajectories / action coordination / prompt-following / interaction continuity”
- “In scenes where even a Combat LoRA cannot fully suppress H3's slow-motion tendency, Motion Continuity Repair can further pull the sequence back toward a faster real-time motion state.”
- “If H3 already generates the scene correctly, you may barely notice it.”
- 数据：“Only 100 clips were ultimately retained”。素材以跑步、体育、舞蹈、空翻、战斗、武器动作为主。V2 侧重“flips, spins, rolls, inversions”。

### 3.3 强度（作者原文，高）
- “Standalone use: around 0.9 is currently recommended.”
- “With a Combat LoRA: Stage 1 around 0.5–0.7”
- “Stage 2: around 0.2–0.3 is recommended. Higher Stage 2 weights may over-stabilize the sequence and reduce motion intensity / speed / impact.”
- 副作用：“Very high weights are experimental / they may reshape the overall action logic / **introduce stronger CG or 3D-game characteristics** in extreme dynamic scenes / or affect generated audio.”
- 触发词 `bunny_crisp_motion` 是可选的。

### 3.4 和 Turbo 的关系、社区反馈（按独立用户数）
| 用户 | 场景 | 原文 / 结果 |
|---|---|---|
| MBen1986（lightx2v #57） | FL2V 4step **v1.2** + Realism 1.0 + Motion_Repair_V2 **0.9** | v1.2 “works flawlessly with VEDA, Sparse Attention and both additional LoRAs”；换 **v1.3** 后 “I still get broken output”，强度拉到 2.0 也一样。官方回复：“We've noted this issue and will work to improve it in future releases.” |
| Jam747（#1） | 两段式，0.8 / 0.3 | “I don not see any difference”。作者回答：底模本来就做得好的场景差别很小 |
| moe-kill 合并（H3_Larry_Battle_JOKER） | Larry Turbo 1.0 + Combat V2 1.0 + **Motion Repair V2 0.3**，合并成一个 LoRA | 只有作者的 B 站演示，<https://huggingface.co/moe-kill/H3_Larry_Battle_JOKER> |
| seedance 博客 | 只是转述模型卡 | 原文：“Those are creator observations, not an independent benchmark” |

- **和 8step v1.1 叠加：没有任何报告。**（高：确实没有）
- 结论：独立实测 2 人（1 人说配 v1.2 好用，1 人看不出差别）。（低）
- 另外两条线索（不在 gpu3 上，仅供参考）：
  - lightx2v #58 有用户推荐 “Motion-Speed-MMH3-SLIDER v1.1”。
  - RunningHub 有 `rh-minimax-h3-fl2v-8step-motion-enhancer-lora`（1.87 GB，卡片没有任何说明）。

### 3.5 对我们
- **链路位置**：H3 主生成。
- **文件**：`Motion_Repair_V2.safetensors`，**gpu3 已有**（就是 JOKER141 的文件）。
- **风险**：①作者的训练素材是动作戏，我们的短剧多是对话和小动作，作者自己说“做得好的场景几乎看不出差别”；②高权重有 CG 或游戏感，和项目方要的胶片质感正好相反；③和 v1.1 8step 叠加没有先例；④可能影响声音。
- **建议对比实验**：
  - 镜头选**本来就出现慢动作的镜头**：走路、转身、倒水、递东西。
  - 组别：B0；B0+MR 0.5；B0+MR 0.9。每组 2 个种子。
  - 指标：
    - 动作速度：光流平均位移（RAFT 或 Farneback，人物 mask 内），对比同一动作的真实参考视频，或者直接比 B0。
    - 脸：SFace 曲线。
    - 颜色：ΔE。
    - 尾帧：SSIM。
    - 声音：项目方试听 + 口型同步分（SyncNet conf）。
    - 质感：盲选时专门问一句“哪个更像 CG”。

---

## 4. fal/MiniMax-H3-Realism-People-LoRA（`h3-realism-people-t2v-i2v-r2v.safetensors`）

来源：<https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA>，讨论 #1–#12；Comfy-Org/MiniMax-H3 #55；lightx2v #57；文件头元数据。

### 4.1 官方用法（模型卡原文，高）
- 触发词：“**Start the prompt with the trigger word `r34l1sm`**, then describe the scene.”（放在 prompt **最开头**）
- 强度：“Scale 1.0 is the intended strength; 0.6-0.8 for a lighter touch.”
- 模式：“It works on text to video, image to video and reference to video, since the adapter only touches the shared attention projections.” **没提 FL2V（首尾帧）。** 作者在 #1 回答 “work also for i2v”。
- 训练：“176 hand-curated live-action clips … Slow-motion footage was detected and retimed to natural speed, everything normalized to strict 24.000 fps”；“rank 32, 1500 steps, trained at the high resolution bucket”。
- 作者在 #4 说：“the model lora is made normally for fp16 or fp8”。8-19 承诺 “will work on a new version this weekend”。**到 10-31 仍未发布新版本**：commits API 最后一次提交是 08-12，fal 名下没有 v2。MBen1986 用的 `h3-realism-people-t2v-i2v-v2.safetensors` 来源不明，可能是他自己改的名。（高）

### 4.2 文件元数据（高，此前文档都没写）
- `base_model = minimax-h3-fl2va`，`trainer = minimax-h3-trainer`，**`training_strategy = text_to_video`**，**`first_frame_conditioning_p = 0.0`**，`lora_rank = 32`，`global_step = 1500`。
- 训练层：只有 `attn.qkv_proj` 和 `attn.out_proj`（50 个 block 加 2 个 token_refiner），**没有 MLP，没有 adaln**。
- **含义**：它用的是 FL2VA 的权重，但训练时**从来没有给首帧条件**，等于在 FL2VA 底模上做 T2V 训练。在我们“首尾帧锁定”的用法下，它学到的“写实运动和光线”有可能和关键帧争夺控制权。这是推断（低），不过和用户报告的“提示词遵循变差、加了不该有的剪辑”方向一致。
- **更正 h3_deep/03 §3.2 E**：原文写“只写了 T2V / I2V / R2V，没写 FL2V”没错，但应补充：它**是在 FL2VA 底模上训的**，只是训练时没有首帧条件。

### 4.3 与 LightX2V Turbo 的叠加
- MBen1986（lightx2v #57）：配 FL2V 4step **v1.2**（加 Motion Repair 0.9）时正常；配 **v1.3** 时坏掉。（低：1 人，官方已确认）
- dennismc1974（#9）：“love this one so essential to add to a turbo modal”（没写是哪个 turbo）。
- Kalemnor（#6）：“Using it with a turbo lora … It seems to stop following prompt instructions correctly, especially during shot changes, framing shifts, or character actions.”
- Kalemnor（#4）：“So the main issue are the combo of pruned models + turbo loras”
- **和 8step v1.1 叠加：没有报告。**

### 4.4 社区反馈（按独立用户数）
**负面（约 10 人）：**
| 用户 | 配置 | 原文 |
|---|---|---|
| jesleocizi（#4） | **ref2va_pruned_int8_convrot** | “weird glitches such as object disappears even if not prompted” |
| szczypen（#4） | R2V | “people glitching … limbs become deformed” |
| katarasmz（#4） | R2V，官方工作流 32 步 | 约 0.2 MP 时“75% of the time”出问题，1 MP 下没遇到；变通办法 “0.5 strength” |
| Kalemnor（#4/#6/#10） | turbo + pruned | 0.5 也不行（“works bad at 0.5 strength as well”）；叠加其他 LoRA 时 “it often hallucinates, messes up generation (deformations…)” |
| sonnybox（#4） | ComfyUI int8 | “this model doesn't seem to work at all with ComfyUI int8” |
| kingp0dd（#4） | w4a8 / int8 convrot pruned | “glitching on me too” |
| Riotcook、codelion（#4） | nvfp4 | 画质变差 |
| rhradec（#6） | 多镜头 prompt | 会把镜头之间的切换做成连续运动，不切镜头（同时也说 “it does make everything looks much more real”） |
| **llucis（#6）** | 高分辨率近景 | “**adding a tone change/yellow tint and/or blurriness (close-up shots)**”；还会在没要求的地方提前加一个剪辑 |
| **dilectiogames（#12，10-19）** | 0.7 | “now everything is in slow motion … also it prevents the lips talking” |

**正面（约 4 人）：**
- dennismc1974（#5）：“makes the faces in ref2v identical”
- dennismc1974（#9）：适合加在 turbo 上
- hidetaro7（Comfy #55）：能压住红脸颊
- rhradec（#6）：看起来更真
- MBen1986：配 v1.2 时正常

### 4.5 hidetaro7 的“fragile”和红脸颊（Comfy-Org/MiniMax-H3 #55，原文核对，高）
- 环境：**Ref2VA**、`ref2va_pruned_fp8_scaled`、ref2v turbo 4step v0.1、RTX 3080 10 GB、`--lowvram`、res_multistep 8 步、AddGuide 设在第 0/62/123 帧。**不是 FL2V。**
- 原文：“The MiniMax-H3-Realism-People LoRA suppresses it, which is presumably incidental … Relying on it as the only defence is fragile: at some resolutions the artifact appears even at strength 1.0”。
- 测量（768×1344、124 帧、同种子）：强度 1.0 时没有红斑；强度 0.0（仍然挂着 turbo）有红斑；完全不挂 LoRA 也有红斑。短边 256 / 384 / 512 / 768 时，红斑分别是 有 / 无 / 有 / 无（不单调）。
- 他还发现：“the same command run after a different preceding job produces different output … A/B comparisons are only valid inside a single script run.”（`--lowvram` 下）。**这一点对我们所有 A/B 都适用**：同一进程、固定顺序，并且先验证重复跑同一组能逐位一致。
- 对我们的意义：红斑是 Ref2VA 的问题，FL2V 没有报告。lightx2v #53 有人报告 8 s 以上嘴唇变红（没写模式，没人回复）。**不能把 Realism LoRA 当成颜色修复工具。**

### 4.6 对我们
- **链路位置**：H3 主生成（如果要用，只用于近景）。
- **文件**：`h3-realism-people-t2v-i2v-r2v.safetensors`，131,229,656 字节，sha256 `acc52960…5b787e`。**gpu3 已有。**
- **风险**（独立用户数从多到少）：
  - 叠 turbo、pruned int8 时出故障或变形：≥5 人。
  - 提示词遵循变差、乱加剪辑：3 人。
  - 黄色偏色或发糊：1 人。
  - 慢动作、嘴不动：1 人。
  - 训练时没有首帧条件，可能和关键帧打架：推断。
- **建议对比实验**（只用近景对白镜头，因为这是它唯一的强项）：
  - 组别：B0；B0+`r34l1sm` 前缀 + 0.6；B0+`r34l1sm` + 1.0；对照组 B0+只加 `r34l1sm`（不挂 LoRA，排除触发词本身的影响）。
  - 指标：
    - 脸：SFace 曲线，看第 0 帧是否贴合，后段是否漂移。
    - 颜色：ΔE2000；另外单独记录**色温偏移**，即 b* 通道均值对关键帧的差（专门看黄色偏色）。
    - 尾帧：SSIM。
    - 口型：SyncNet conf（针对“嘴不动”）。
    - 动作速度：光流（针对慢动作）。
    - 质感：皮肤区域的高频能量。
  - 项目方盲选时问两件事：“哪个皮肤更像胶片”，以及“哪个更像同一个人”。

---

## 5. LightX2V FL2V Turbo：4step v1.2 / 8step v1.1 / 8step v1.0 / 4step v1.3

来源：<https://huggingface.co/lightx2v/Minimax-h3-Turbo>，讨论 #42 #48 #52 #54 #57 #58 #59 #60（逐帖读过）；文件头元数据。

### 5.1 10-30 以后有没有新的 FL2V 8step v1.1 反馈？
- 讨论区最新一帖是 #60（10-28，问许可证）。**10-30 之后没有新帖。**
- #57（发布帖，11 条回复）里只有 Jazzyman 说 **REF2V** 8 步 v1.1 “incoherent speech and bad prompt following with refmods”，以及 MBen1986 的 v1.3 报告。**没有任何人报告 FL2V 8step v1.1。**
- #59（10-22）dennismc1974：“great stuff thanks i get lifelike videos with these turbos”，没写版本和模式。
- WebSearch（含 comfyui-wiki、reddit 关键词）没有找到 FL2V 8step v1.1 的实测。搜索摘要里“praises the older FL2V 8-step v1.1”是误读：原帖 #48 讲的是 8step **v1.0** 768p。
- **结论：截至 2026-10-31，FL2V 8step v1.1 仍然没有任何社区 FL2V 实测。**（高：确实没有）

### 5.2 四个版本的客观差异（文件头，高）
| 文件 | 日期 | rank / alpha | 训练层 | sha256（前 8 位） |
|---|---|---|---|---|
| fl2v 4step v1.2 768p comfyui | 09-04 | 128 / 8（scale 0.0625） | attn qkv/out + mlp fc1/fc2（50 个 block + token_refiner），无 adaln | c8168ebc |
| fl2v 4step v1.3 768p comfyui | 10-20 | 同上 | 同上 | 70103fd0 |
| fl2v 8step v1.0 768p comfyui | 08-27 | 同上 | 同上 | 08cfe946 |
| fl2v 8step v1.1 768p comfyui | 10-20 | 同上 | 同上 | fb4c0036 |

- 四个文件的元数据都是 `base_model = Comfy-Org/MiniMax-H3 minimax_h3_fl2va_bf16.safetensors`。**格式、rank、层完全相同**，所以 v1.3 叠加会坏不是格式或层的问题，而是权重内容的问题。（高）
- 官方推荐（#57）：“For the new FL2V 4-step and 8-step LoRAs, we recommend using a video flow shift of 6”；“Please use the inference step count matching your checkpoint.”（高）
- 官方 #52：v1.2 “focuses on improving the audio generation quality”。#57 有人问 v1.3 改进了什么，**没人回答**。（高）

### 5.3 画质 vs 音频 vs 叠加安全（社区，按用户数）
| 版本 | 画质（脸、头发、颜色） | 音频 | 叠加其他 LoRA |
|---|---|---|---|
| 4step v1.2 | 负面 3 人：DaviKar（“the quality took a big hit in v1.2”）、g2t2（“His hair is way worse.”）、ApexArtist（#54：“1.2 seems it changes the original too much”） | 官方说改善了 | **正面 1 人（MBen1986）：配 Realism 和 Motion Repair 都正常** |
| 4step v1.3 | 0 人正面；MBen1986：配合使用时 “severely degraded/unusable” | 不明 | **负面 1 人 + 官方确认** |
| 8step v1.0 768p | Aorora12（#48）配 Hybrid 好；h3_deep/02 里有色偏、塑料感的矛盾报告 | 官方说视频和音频都有改善 | yui7854（#48）：“Does not work well with other Loras” |
| 8step v1.1 768p（当前锁定） | **0 人** | **0 人** | **0 人** |
| 4step v1.1 | ApexArtist：“1.1 seems too dark” | — | — |

- 4 步 vs 8 步：h3_deep/02 已经汇总了 ≥8 人认为 4 步有慢动作、拖影、蜡化（中-高），这里不再重复。
- **结论（低-中）**：
  - **画质**：目前没有证据说明哪个版本最好；8 步整体优于 4 步有多人共识。
  - **叠加 LoRA**：唯一有正面实测的是 4step v1.2。
  - **音频**：官方说 v1.2 好于 v1.1（指 4 步线）。
  - 当前锁定的 8step v1.1 是“官方最新、零社区数据”。在没有对比之前，**叠加任何附加 LoRA 时，都应该同时测一组“同样的 LoRA 叠在 4step v1.2 上（4 步）”作为对照**。

### 5.4 对我们
- **链路位置**：H3 主生成。
- **文件**：fl2v 4step v1.2 / v1.3、8step v1.0 / v1.1 **都在 gpu3 上**。完整 sha256 见 §9。
- **风险**：8step v1.1 本身没人验证；v1.3 叠加会坏（1 人 + 官方确认）；v1.2 用户说画质掉了。
- **建议对比实验**（这组要最先跑，因为它决定后面所有叠加测试用哪个底座）：
  - T1：8step v1.1 @1.0，8 步（B0）
  - T2：8step v1.0 768p @1.0，8 步
  - T3：4step v1.2 @1.0，4 步
  - T4：4step v1.2 @0.5，8 步（MrShibari 的做法：步数多于训练步数时用 0.5，见 h3_deep/02 §2.5）
  - 设置：同样的首尾帧，3 类镜头（近景对白、中景道具、远景小脸），每类 2 个种子。
  - 指标：
    - 脸：SFace 曲线，看最小值和斜率。
    - 颜色：ΔE2000，对首尾关键帧；平均 L* 和 b* 的漂移（对应项目方说的偏暖、偏灰、偏暗）。
    - 尾帧：最后 12 帧的 SSIM。
    - 远景：小脸的 SFace。
    - 动作速度：光流。
    - 声音：项目方试听。
  - 然后：在 T1 和 T3 上各叠一次 VBVR 0.7 / Realism 0.6 / Motion Repair 0.9，检查有没有“崩坏”。

---

## 6. alibaba-pai/MiniMax-H3-Acc-LoRAs（PDD）

来源：<https://huggingface.co/alibaba-pai/MiniMax-H3-Acc-LoRAs>，讨论 #1–#6；ComfyUI PR #15908；Kijai 转换版 <https://huggingface.co/Kijai/MiniMax-H3-experimental>。

### 6.1 内容（官方，高）
- “We apply Parallel Decoding Distillation (PDD) to MiniMax-H3, enabling efficient video generation in only a few inference steps.”
- 两个文件：
  - `MiniMax-H3-FL2VA-Acc-8Step.safetensors`：“Official 8 Step Acc LoRA (`rank=64` and `network_alpha=64` in BF16) for MiniMax-H3 (FL2VA)”
  - `MiniMax-H3-Ref2VA-Acc-8Step.safetensors`：Ref2VA 版本
- **是 PDD，不是 DMD。**
- 样例对比的是 FL2VA 基模、lightx2v `fl2v_turbo_4step_v1.1_768p`、Acc-8Step（768p）三方。原文：“Videos are generated with a LoRA weight of 1.0 at both 4 and 8 NFE.” **卡片上没有任何量化画质结论**，只有视频。
- ComfyUI 原生支持（PR #15908，08-28 合并）：“pair a backbone LoRA with a 32-interval bank of output heads … `simple` at 8 steps with shifts 12/3 lands exactly on the 32-grid boundaries, so no custom schedule either.” 用普通 LoRA 加载器就能加载。也就是说，这个 LoRA **会替换 final layer 的输出头**。（高）
- Kijai 提供了 ComfyUI 版，包括 pruned 版：`MiniMax-H3-FL2VA-Acc-8Step_pruned_comfy.safetensors`，1,725,921,392 字节。（高）

### 6.2 社区反馈（按独立用户数）
| 用户 | 原文 |
|---|---|
| simlang（#3） | “Great job on the LoRA! The best out so far for sure!” |
| gaga-lee97（#1/#4） | “the 8 step results look good, although I met some blur hands/ layouts in high-dynamic secnes”；4 步 “not clear” |
| Rkss（#1） | “got smeared hands, legs, bodies in fast motion scenes”；“Both LoRA present ghosting in fast action.” |
| PavCon（#6） | “I still get morphing on far away faces and small face.” |
| SmartyPants1（#1，4070） | 4 步 turbo 跑 5 s 约 11 分钟，Acc 约 20 分钟 |
| Privac（#4） | 4 步本来就不会好看 |

- 结论（中）：8 步时“好看”有 2 人；快速运动拖影或糊手有 2 人；远处小脸变形 1 人。**它不能修我们的小脸问题。**
- Ampere：权重是普通 BF16 LoRA 加输出头，没有 fp8/nvfp4 依赖；在 int8 convrot pruned 底模上要用 Kijai 的 `_pruned_comfy` 版本。**没有找到 3090 上的实测。**（高：格式；3090 实测没找到）
- 叠加：PDD 自己就是加速蒸馏，并且替换输出头，**不应该和 lightx2v turbo 一起叠**（推断，依据是 PR 的机制）。

### 6.3 对我们
- **链路位置**：H3 主生成（作为 turbo 的替代）。
- **文件**：Kijai 的 `MiniMax-H3-FL2VA-Acc-8Step_pruned_comfy.safetensors`（1.73 GB），**gpu3 没有**，需要下载，属于项目方闸门。
- **风险**：快速运动拖影；远处小脸依旧变形；推荐 shift 12/3（和锁定的 6/3 不一样）；速度可能比 4 步 turbo 慢。
- **建议对比实验**（下载获批后再做）：
  - 组别：B0 vs PDD 8 步（shift 12/3、euler/simple、cfg 1、强度 1.0，**不挂 lightx2v**）。
  - 镜头和指标同 §5。
  - 额外记录每步耗时。

---

## 7. NAGuidance（ComfyUI 核心节点）

来源：文档 <https://docs.comfy.org/built-in-nodes/NAGuidance>；源码 `comfy_extras/nodes_nag.py`、`comfy/ldm/minimax/model.py`、`comfy/samplers.py`（master，10-31 抓取）。

### 7.1 它做什么（文档 + 源码，高）
- 文档：“The NAGuidance node applies Normalized Attention Guidance to a model.” 参数默认值：`nag_scale` 5.0、`nag_alpha` 0.5、`nag_tau` 1.5。节点标记为 `is_experimental=True`。
- 源码机制：
  - 节点只做两件事：`m.set_model_attn1_output_patch(nag_attention_output_patch)` 和 `m.disable_model_cfg1_optimization()`。
  - 补丁函数开头有一段判断：
    ```
    if not (1 in cond_or_uncond and 0 in cond_or_uncond):
        return out
    ```
    也就是说，只有当**同一次前向**里同时有 cond 和 uncond 时，它才会用 `z_pos*scale - z_neg*(scale-1)` 加 L1 归一化去改注意力输出。

### 7.2 能不能作用到 H3？**不能。** 原因有两个，都来自源码（高）
1. **H3 的注意力根本不调用 `attn1_output_patch`。**
   - `comfy/ldm/minimax/model.py` 的 `Attention.forward` 直接 `optimized_attention(...)` 然后 `out_proj`。全文件 grep `attn1_output_patch` / `output_patch` / `img_slice` 都是 0 处。
   - 对比：SD 的 `attention.py`、Flux 的 `layers.py`、Qwen-Image 都有 `if "attn1_output_patch" in transformer_patches` 或者设置了 `img_slice`。
   - 所以 NAG 的补丁函数在 H3 上**永远不会被调用**。
2. **H3 强制 batch=1。**
   - `_forward` 里有一行：`if video_x.shape[0] != 1: raise ValueError("MiniMax H3 supports batch size 1")`。
   - 所以即使用 CFGGuider，cond 和 uncond 也只能分开前向，`cond_or_uncond` 永远不会同时包含 0 和 1。
- 副作用：`disable_model_cfg1_optimization()` 会让 CFGGuider 在 cfg=1 时**也去算 uncond**，计算量翻倍，但结果不变（cfg=1 时 `uncond + 1·(cond−uncond) = cond`）。如果用 BasicGuider（我们现在的配置），压根没有负面分支，NAG 节点只是空转。
- 结论：**在 cfg 1 下用核心 NAG 推“不要字幕 / 不要塑料皮肤”这类负面词，行不通。**更正 kimi-1040 里的“未验证”：现在可以从代码层面确定是**无效**的。

### 7.3 H3 专用的第三方方案：ComfyUI-H3NegativeLab（CCP6/H3-Shadow-Negative-Nodes）
- 来源：<https://huggingface.co/CCP6/H3-Shadow-Negative-Nodes>（08-13 发布，v1.0.2，6 个赞）。
- 原文：“This pack patches the H3 DiT blocks to run a shadow attention branch with your negative text while keeping the positive presentation, references, and keyframes intact. NAG-form normalized repulsion is applied to the generated video and audio targets independently.”；“Works with T2V, FL2VA (first/last-frame I2V), and REF2VA.”
- 用法：接一个负面 CONDITIONING，后面照常用 BasicGuider。默认参数 video_scale 3.0、tau 2.5、alpha 0.35、end_percent 0.60。作者说会“roughly 15-30% longer inference”。
- 已知限制（原文）：“This patch replaces H3's DiT double_blocks via `set_model_patch_replace`. Block-level cache nodes … will conflict”。
- 我读过代码（829 行）：确实是通过 `set_model_patch_replace(..., "dit", "double_block", i)` 替换每个 block，并且自己重建负面文本的 RoPE 和调制。代码里**没有** subprocess、网络请求、eval 这类可疑调用。
- 社区：只有 1 个讨论帖 #1（Leon1000，09-21，“I got an error.”，只有截图，没人回复）。**没有任何画质实测**。v1.0.2 是 08-13 的版本，之后 ComfyUI 的 H3 代码改过 RoPE（kitchen split-half）和 prefetch，**兼容性不明**。（低）
- **推断（低）**：负面引导理论上可以压“字幕、塑料皮肤”，但官方 prompt 指南警告过，列禁止词反而可能把那些概念加进画面（见 kimi-1040 §2.4）。要不要试，需要项目方同意装第三方节点（属于改系统，按分工由 Claude 写系统，但仍需项目方点头）。

### 7.4 对我们
- **链路位置**：H3 主生成（模型补丁）。
- **文件**：核心 NAG 不需要文件，但**对 H3 无效**；第三方节点**不在 gpu3 上**，需要装代码。
- **风险**：核心 NAG 只会白白多算；第三方节点可能和当前 ComfyUI 版本不兼容，和其他 block 级补丁冲突，增加 15–30% 时间，还可能把负面词里的概念“召唤”进画面。
- **建议对比实验**（装节点获批后再做）：
  - 镜头选**最容易出字幕的对白镜头**和**皮肤特写**。
  - 组别：B0；H3NegativeLab 用负面词 “subtitles, captions, text, plastic skin, waxy skin”，video_scale 3 / tau 2.5 / alpha 0.35；同参数但负面留空（看节点本身有没有副作用）。
  - 指标：
    - 字幕：OCR 字幕检出率（每秒 1 帧）。
    - 皮肤：高频能量。
    - 颜色：ΔE。
    - 脸：SFace。
    - 成本：耗时。

---

## 8. gpu3 上的 4 个杂项 LoRA（一行识别 + 风险）

| 文件 | 来源 | 一行说明 | 正常镜头该不该挂 |
|---|---|---|---|
| `h3_antiburn_universal_v1` | Imagineer13/H3-Anti-Burn-LoRA <https://huggingface.co/Imagineer13/H3-Anti-Burn-LoRA>（10-14，rank 32，sha256 `8f76dc3c…`） | 用于**续接链**的第 2 段及以后，防止脸“越续越烧”。原文：“**Don't use it on clip 1.** A first clip has nothing to burn from.” 起步 0.5。在 lightx2v 8step v1.0 768p 上把脸部烧糊从 +44% 降到 0%（@0.5）。副作用：“If faces turn soft or waxy, go down”；用 Larry 时 “the colour still drifted warmer and darker”。社区 #1 有 1 人在 DMAD 上用，没效果 | **不挂**。我们每个镜头都是独立的 FL2V 单段 |
| `camera_motion_h3_lora_v1_3000_pruned` | Jojocodex/minimax-h3-Camera-Motion-lora <https://huggingface.co/Jojocodex/minimax-h3-Camera-Motion-lora>（RunningHub 也有镜像，sha256 `9d7d98d7…`） | 运镜 LoRA。触发词 “camera motion” **必须放在 prompt 开头**，强度 0.8–1.0，“>1.2 可能画面不稳”。训练 caption 里大量出现 “cinematic teal-orange grading, sharp 4k”，素材多是武打和动作场面 | **默认不挂**。如果要用，只用在需要明确推、拉、环绕的镜头，而且要测色偏（推断：caption 里的青橙调色可能带偏颜色） |
| `minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16` | Kijai 从 ByteDance DMAD（<https://huggingface.co/ZhengmingYu/DMAD>）秩压缩而来（sha256 `ddfdd94f…`） | **4 步蒸馏加速 LoRA**，相当于 turbo 的替代品，不是画质件。原版在 **T2VA** 底模上训练（下载命令排除了 FL2VA/Ref2VA）。官方用法：“`lcm` sampler and `simple` scheduler … shift 12 / audio shift 2 … ODE samplers such as euler are not their operating point”。10-29 官方新出了 8step_full_critic（gpu3 没有） | **不挂**。不能和 lightx2v 一起叠；它的采样设置和我们锁定的完全不同 |
| `minimax_h3_flf2v_lora_v1` | pablodawson/MiniMax-H3-360-Orbit-LoRA <https://huggingface.co/pablodawson/MiniMax-H3-360-Orbit-LoRA>（FL2VA pruned int8，rank 16，sha256 `14f13e3e…`） | **定格 360° 环绕**专用：首尾帧放同一张图，场景冻结，只有镜头绕一圈；需要逐字使用固定 prompt；768×768、73 帧、28 步 | **绝对不挂**。会让人物冻住 |

---

## 9. 文件核对表（供在 gpu3 上做 sha256 比对，全部来自 HF API）

| 文件 | 字节数 | sha256 |
|---|---|---|
| H3-Licon-VBVR-I2V.safetensors | 149238584 | 19ba9d18c06eaecebd11c1ca1d27a0277f414d43370124e3cfcb33a113e9f886 |
| Motion_Repair_V2.safetensors | 155110272 | edfa0e2858caeba7be9108883f61da8525d3c58af998c94ac7a449d9603d7574 |
| h3-realism-people-t2v-i2v-r2v.safetensors | 131229656 | acc529601d2da117fb81179e76c56e488a3beab1171659d305f04fa3655b787e |
| minimax_h3_lms_v1.0_r64.safetensors | 1239664536 | 16f3195bc6bffa431c0598dc2031e520ba058b4fcbc9f104db9e3fdfdeacf60c |
| h3_antiburn_universal_v1.safetensors | 310168728 | 8f76dc3c63afa8c556c620b4b7f2ffeeb666f0aa9382a9ce3a07fd6120d0f154 |
| camera_motion_h3_lora_v1_3000_pruned.safetensors（Jojocodex） | 155109680 | 9d7d98d7377f56efed3aa7d507f767936112d208906f49908ec9a8ae912be88b |
| minimax_h3_DMAD_4step_full_lora_avg_rank_39_bf16.safetensors | 366647000 | ddfdd94f4c9a0f32bf3649bb8e98ca20db572e4db6bcd9cca546a5b33ea32d11 |
| minimax_h3_flf2v_lora_v1.safetensors | 155111424 | 14f13e3effaf3e729fdc0c97680344aa63f473be0c55963f963d718b3db2a4d4 |
| minimax_h3_fl2v_turbo_4step_v1.2_768p_comfyui_bf16 | 1956193000 | c8168ebc17bbacc4296103dda2fec1ba85b24392fa08cf2bfbcef0cff0dc3cc8 |
| minimax_h3_fl2v_turbo_4step_v1.3_768p_comfyui_bf16 | 1956193000 | 70103fd0d80a947ed4e7fe6f88915863d54ef22c5cab03bd5d2fd649385ffe1e |
| minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16 | 1956193000 | 08cfe946033af7d27719b964b6e0a0e50c32138daabbd6ce4137e23df6bf9980 |
| minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16 | 1956193000 | fb4c00361c94bad47f878d5e096c6cab2f45063b0968bd5756dcb7da6936f53e |
| minimax_h3_ref2v_turbo_4step_v1.0_768p_comfyui_bf16 | 1956193000 | b4da466e43588004097dfbcde245ccc439c34a26bc997cb76a0b53a1d549ea0d |
| minimax_h3_ref2v_turbo_8step_v1.1_768p_comfyui_bf16 | 1956193000 | e56863a7524e0300729cbb7b64cc8b548d90698c1abbf7d83898b0122fbe1e81 |
| （未在 gpu3）MiniMax-H3-FL2VA-Acc-8Step_pruned_comfy.safetensors | 1725921392 | e97b813a6f857b9dab310f31ec30a8334f63a3e7dcb5d07c0c91933d3447a897 |

注：gpu3 上 fl2v 8step v1.0 如果是 544p 版（`..._8step_v1.0_comfyui_bf16`），sha256 是 `2339acdf…`，和 768p 版不同。

---

## 10. 建议的整体 A/B 顺序（项目方盲选；我只设计，不执行）

**通用规则：**
- 同一套首尾关键帧、同一 prompt、同一种子。
- 每一轮都在**同一个 ComfyUI 进程**里按固定顺序跑（依据 hidetaro7 #55：跨任务的显存驻留会让同种子结果不同）。开跑前先把 B0 重复跑两次，确认逐位一致。
- 镜头 3 类：近景对白、中景道具、远景小脸。每类 2 个种子。
- 关掉 EasyCache 和 Spectrum（h3_deep/02 §4.2）。
- 盲选：同一镜头的各组随机编号，拼成并排视频，项目方只选“哪个最像电影或大片”和“哪个最像同一个人”，事后再揭晓编号。

| 轮次 | 目的 | 组别 | 主要指标 |
|---|---|---|---|
| R1 | 定 Turbo 底座 | §5.4 的 T1–T4 | SFace 曲线、ΔE2000（全片 + 首尾）、L*/b* 漂移、尾帧 SSIM、光流 |
| R2 | 道具一致性 | R1 胜者 + VBVR 0 / 0.4 / 0.7 / 1.0 | 道具计数、穿模次数、SFace、ΔE、脸部拉普拉斯方差 |
| R3 | 慢动作 | R1 胜者 + Motion Repair 0 / 0.5 / 0.9 | 光流、SyncNet、“CG 感”盲评 |
| R4 | 近景质感 | R1 胜者 + Realism 0 / 0.6 / 1.0，另加只放触发词的对照 | b* 偏移、SFace、SyncNet、光流、皮肤高频能量 |
| R5 | 叠加稳定性 | R2–R4 中有正收益的项目一起叠，分别叠在 8step v1.1 和 4step v1.2 上 | 有没有崩坏（人工 0/1）加上述全部指标 |
| R6（可选，需获批） | 后期精修 | LMS V2V 0.6 / 0.9（124 帧）；PDD 8 步；H3NegativeLab | 对原片的 SFace / ΔE / 平均 L*、显存、耗时 |

**指标定义建议：**
- **SFace 曲线**：每帧检测人脸，计算和首关键帧人脸的 SFace 余弦相似度，报告最小值、均值、最后 1 秒的均值。
- **ΔE2000**：先把输出和关键帧都转到 Lab，算全帧均值；人物 mask 内和背景分开报告。另外单独报告 L*（明暗）和 b*（冷暖）通道的均值差，直接对应“偏暗”“偏暖”。
- **尾帧 SSIM**：最后 12 帧逐帧对尾关键帧算 SSIM，取均值。
- **光流**：人物 mask 内光流幅值的中位数，按秒画曲线，用来判断慢动作。

---

## 11. 对已有文档的更正

| 文档 | 原说法 | 更正 | 依据 | 置信度 |
|---|---|---|---|---|
| kimi_20261029_1040 §5 | LMS “about 0.8 strength; 1.0 on both passes is too extreme” | 这是 comfyui-wiki 的说法；**作者文档是 “Start with LoRA strength 1.0”**，作者样例用 0.9。另外 LMS 是 **ref2va pruned** 上训的 V2V LoRA，`frame_idx=0` 接的是**整段源视频** | docs/lms.md、#2、#9 | 高 |
| kimi_20261029_1040 §2.4 | NAGuidance 在 H3 上“未验证” | **源码确认对 H3 无效**：H3 注意力不调用 `attn1_output_patch`，并且强制 batch=1 | §7.2 | 高 |
| kimi_20261029_1424 | VBVR “trained on the FL2VA bf16 base … start at 0.6–1.0” | 底模正确。补充：训练数据是 512² 程序生成的推理题视频；只训到第 7000 步；rank 16；只训视频；**数据许可 CC BY-NC 4.0** | 文件元数据、数据集卡 | 高 |
| comfyui-wiki VBVR 页 | “7,000 steps at 1280x720” | 数据集字段是 `[512,512]`；1280x720 只是 `modelspec.resolution` 字段的值 | 文件元数据 | 高 |
| h3_deep/03 §3.2 E | Realism LoRA “只写了 T2V / I2V / R2V，没写 FL2V” | 补充：元数据显示 `base_model=minimax-h3-fl2va`，但 `training_strategy=text_to_video`、`first_frame_conditioning_p=0.0` | 文件元数据 | 高 |
| research_link_coverage | JOKER141 “gpu3 上没有” | gpu3 上的 `Motion_Repair_V2` 就是该仓库的 V2 文件（按文件名和大小判断，sha256 待核对） | §3.1 | 高（判断）/ 待核对 |
| kimi_20261029_1424 | Kijai 的 PDD / Acc | ComfyUI 已原生支持（PR #15908，08-28 合并），设置 8 步、shift 12/3、simple | PR 原文 | 高 |

---

## 12. 没找到或无法核实

- **VBVR**：任何第三方画质反馈；和 lightx2v turbo（任何版本）叠加的结果；官方推荐强度；作者样例是否用了 turbo；NEXORA 合并里 VBVR 0.40 的出处（模型卡 gated，看不到）。
- **LMS**：在 FL2VA 底模上单遍生成的系统测试；3090 上 243 帧 768×1344 加 guide 的显存数据；许可证（#26 未回复）。
- **Motion Repair V2**：训练分区（fl2va 还是 ref2va）；和 8step v1.1 叠加的反馈；对话类镜头的效果。
- **Realism**：fal 承诺的新版本（到 10-31 仍未发布）；MBen1986 用的 “-v2” 文件出处；在 FL2V 首尾帧模式下的任何报告。
- **Turbo**：FL2V 8step v1.1 的任何社区实测；v1.3 相对 v1.2 改了什么（#57 有人问，官方未答）；各版本的定量颜色或脸部评测。
- **PDD**：3090 上的实测速度和画质。
- **NAG**：H3NegativeLab 在当前 ComfyUI 版本上能不能跑；任何画质实测。
- **Reddit / civitai**：本次没有专门绕过限制去读（以前的报告也读不了）。civarchive 上这几个 LoRA 没有搜到条目。X（Twitter）没有查。
- gpu3 上文件的实际 sha256（不允许 ssh），见 §9 的对照表。

## 13. 来源清单
- HF 模型卡和元数据：LiconStudio/Minimax-H3-VBVR（讨论 #1–#4）；Video-Reason/VBVR-Pro-SFT-Video；Alissonerdx/Minimax-H3-ComfyUI（docs/lms.md、README、LMS 工作流 JSON、讨论 #1 #2 #4 #8 #9 #15 #22 #26）；JOKER141/MiniMax-H3-General-Motion-Continuity-Repair（#1 #2）；moe-kill/H3_Larry_Battle_JOKER；RunningHubAI/rh-minimax-h3-fl2v-8step-motion-enhancer-lora；fal/MiniMax-H3-Realism-People-LoRA（#1 #4 #5 #6 #9 #10 #12、commits）；Comfy-Org/MiniMax-H3 #55；lightx2v/Minimax-h3-Turbo（#52 #53 #54 #57 #58 #59、tree/元数据）；zzzDDs、sonnybox 的 MiniMax-H3_experimental；alibaba-pai/MiniMax-H3-Acc-LoRAs（#1 #2 #3 #4 #6）；Kijai/MiniMax-H3-experimental（README、loras 列表）；ZhengmingYu/DMAD；Imagineer13/H3-Anti-Burn-LoRA（#1）；Jojocodex/minimax-h3-Camera-Motion-lora；RunningHubAI/rh-camera-motion-h3-lora-v1-3000-pruned-lora；pablodawson/MiniMax-H3-360-Orbit-LoRA（#6）；CCP6/H3-Shadow-Negative-Nodes（README、代码、#1）；Asirus/MiniMax-H3-Ref2VA-NEXORA（gated）。
- comfyui-wiki：2026-10-23-h3-vbvr-lora（英文）、2026-09-11-minimax-h3-sharpness-lora（中文）。
- seedance 博客：minimax-h3-motion-continuity-repair-lora。
- ComfyUI 源码（master，10-31）：`comfy_extras/nodes_nag.py`、`comfy/ldm/minimax/model.py`、`comfy/samplers.py`、`comfy/model_base.py`、`comfy/ldm/modules/attention.py`、`comfy/ldm/flux/layers.py`、`comfy/ldm/qwen_image/model.py`；PR #15908。
- 文档：docs.comfy.org/built-in-nodes/NAGuidance。
- GitHub：slogonomo/lf-studio PR #92（核对后与 8step v1.1 无关，不采用）。
