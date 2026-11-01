# ComfyUI + MiniMax H3 调参专家手册（EXPERT，2026-10-31）

项目方原话：“你需要成为这方面的专家。”本文只讲系统参数和工作流，不涉及剧本内容。

**方法**：逐一读了以下来源，凡是能读源码的地方都以源码为准。
- 一手来源：ComfyUI master 源码（`comfy_extras/nodes_minimax_h3.py`、`comfy/ldm/minimax/model.py`、`comfy/model_base.py`、`comfy/supported_models.py`、`comfy/model_sampling.py`、`comfy_extras/nodes_model_advanced.py`、`comfy_extras/nodes_resolution.py`、`comfy_api/latest/_input_impl/video_types.py`）、Comfy 官方文档（native / multiframe / prompt guide / FastH3）、官方模板 JSON（`video_minimax_h3_i2v.json`、`video_minimax_h3_r2v.json`）、MiniMax HF 模型卡和两份 prompt guide、官方 skills（`base-en.txt`）。
- 第三方：lightx2v、ModelTC、alibaba-pai、LBH 3D 上采样器源码、JOKER141、fal、Carasibana FaceRefine。
- 社区讨论：HF 四个讨论区共 40 帖（lightx2v / Comfy-Org / Kijai / MiniMaxAI）、GitHub issue（ComfyUI #15426、#15978，WanGP #2279，Context-Loop #96）。
- YouTube：14 个视频的描述和章节（通过页面元数据读取，没有字幕）。

**避免重复**：前人调研 `docs/h3_research_quality.md`、`docs/research/h3_deep/01–03`、`docs/QC_ep02_20261031.md`、`docs/ep02_iter/v0_baseline_review.md` 已经覆盖的内容只引用结论；本文重点写**新的证据**和**“为什么这样设”**。WFLIB 的工作流参数表见 `docs/ep02_iter/workflow_library.md`（写作时还没生成）。

**置信度**：高 = 源码、官方文档或官方配置原文；中 = 社区多人一致或作者有测量；低 = 单人报告或我的推断。

---

## 0. 结论先行（12 条）

1. **shift 12/3 就是 ComfyUI 对 H3 的默认值。** `supported_models.py` 的 `MiniMaxH3.sampling_settings = {"shift": 12.0, "audio_shift": 3.0}`，所以官方模板里根本没有 SigmaShift 节点。只有挂 768p 的 lightx2v turbo（按 6/3 训练）时才需要显式加节点。置信度高。
2. **官方模板的采样器是 `res_multistep` + `simple`，不是 euler**：基模 20 步；I2V 打开 turbo 时 6 步，R2V 打开 turbo 时 4 步。我们一直用 euler，从没和 res_multistep 做过 A/B。另一方面，社区有人报告 euler 能让 I2V 变暗减半（Comfy HF #67），PDD 也强制要求 euler。所以这是一个**待测项**，不是“我们错了”。置信度：高（模板）/ 中（对比）。
3. **首尾帧是“硬钉”。** 源码 docstring 写的是 “re-injected every step (never denoised)”，条件行的时间步固定在 0.999。尾帧被钉在 `frame_count-1`，`first_frame` 直接拉伸到画布，`last_frame` 中心裁切；而且这两张图**也送进 Qwen3-VL 文本编码器**（`clip.tokenize(prompt, images=images)`）。所以首尾帧一旦几乎相同，视频必然静止，结尾也必然“落定”冻结。这是结构性结果，不是偶然。置信度高。
4. **4 帧顿挫的结构来源是 `FRAME_PER_TOKEN = (1, 4, 4, 4, 4)`**：每 17 帧是 5 个 latent，第一个 latent 只管 1 帧，后面每个管 4 帧。“17k+5”就是这么来的。turbo 让 latent 内部的过渡更“平”，跨 latent 的跳变因此更明显。置信度高（结构）/ 中（turbo 加重）。
5. **新线索：分辨率可能和顿挫有关。** okkazoo 在 ComfyUI + 3090 上测到，宽高都是 64 的倍数（包括 1344×768）时平移会顿挫，宽高都 ≡32 (mod 64) 时干净。我们的 768×1344 正好都是 64 的倍数。等价的 9:16 候选是 **736×1312**（0.97 MP）。置信度低到中（单人，但测了 7 种尺寸、5 组采样器）。
6. **项目方工作流是“低分辨率第一段 + 3D latent 上采样 + 高分辨率精修”的两段式。** 20 步、在第 10 步切，对应 σ≈0.923，也就是 shift-12 基础网格的中点：第一段决定构图和动作，第二段补细节。社区一致把第二段起点放在 σ 0.90–0.92；还有人测到“第一段分辨率几乎不影响结果”。**我们从没用过两段式。** 置信度：高（源码与数值）/ 中（效果）。
7. **`comfy kitchen attention` 是 INT8 量化注意力**（源码 tooltip：“uses quantized INT8 attention”）。项目方工作流和 ganloss 的工作流都用它（为了提速）。画质代价没有公开测量，需要和 `pytorch attention` 做 A/B。置信度：高（机制）/ 低（画质影响）。
8. **慢动作的根因按强弱排**：
   - 蒸馏 LoRA（turbo）强制慢动作（lightx2v #36：“force slow motion on everything”）；
   - 提示词没写动作力度；
   - 尾帧太像首帧。

   社区的修法（按证据排）：基模多步；在提示词里写力度（“energetic and rapid …”）；Motion Repair LoRA 约 0.9；速度滑块 LoRA；PDD 8NFE 替代 turbo；Singularity V2 微调权重（许可未核）。置信度中。
9. **红脸**：我们 v0 审片的结论（提示词里的 flush 触发、Pika 放大、只给首帧给了它变红的时间、krea2 让首帧本身偏红）与社区 #55 描述的“temporal colour drift”一致。补充两条：
   - **编码链路已被源码排除**：ComfyUI SaveVideo 用 `dst_colorspace=BT709_NCL` 转换并打 bt709 标记，ffprobe 实测 H3 原片是 bt709/bt709/sRGB-trc。
   - 社区的新思路是“time-controlled realism”：写实或肤色 LoRA 只在低 σ 段生效。

   置信度：高（编码）/ 中（漂移）。
10. **音频和口型的三条硬规则**（MiniMax HF #76，多人确认）：
    - `overall_soundscape` 一定要写（“It does NOT do silence well”）；
    - `</d>` 前一定要有句号；
    - 不说话的人写 “silently”。

    参考音频只用约 4 s，太长会让开头 0.5 s 出现乱语。少步数时音频先坏（YouTube jsqHFgbjL08：“audio doesn't [hold] at lower step counts”）。置信度中。
11. **长片拼接时只能单段采样**：“latent upscale or a second sampling stage both shift pixels at the joins”（YouTube jsqHFgbjL08）。也就是说，两段式适合**独立镜头**，不适合尾帧续接链。置信度中。
12. **项目方的提示词格式（SCENE / ACTION AND TIMING / CAMERA / … / CONSTRAINTS + “Avoid …”）不是官方格式。** 官方是三字段（Ref2VA 是六字段），并且明确说：“Ban lists add the unwanted concepts”（cfg 1，没有负分支）。项目方的 prompt 里也没写 `<Picture 1>` 标签。建议做“项目方格式 vs 官方格式”的 A/B，由项目方看片定。置信度：高（官方原文）/ 效果未测。

---

## 1. 机制速览（读源码得到，后面所有参数解释都以此为依据）

| 机制 | 源码事实 | 对调参意味着什么 |
|---|---|---|
| 潜空间 | 视频 `[B,24,T,H/16,W/16]`，音频 `[B,32,2,T40]`，二者打成 NestedTensor 一起采样 | 宽高必须是 32 的倍数（DiT 的 2×2 patch × VAE 16 倍压缩）。音频跟着视频走同一个 σ 表，但内部按 audio_shift 换算 |
| 帧网格 | `align_frame_count`：一直 +1，直到 `n % 17 == 5`；`latent_t = (n-5)//17*5+2`；`FRAME_PER_TOKEN=(1,4,4,4,4)` | 帧数只能取 124/141/…/243/…/362；训练范围是 124–362（tooltip：“longer is untested”） |
| 音频 | 40 Hz latent，32 kHz 立体声；音频 VAE 必须 fp32 | 时长 = 帧数/24，音频长度由此自动确定 |
| shift | `ModelSamplingAV`：视频 σ 由 shift_video 决定；DiT 把 σ_v 反推回基础网格，再用 audio_shift 算出 σ_a（`time_shift_sigma`） | 改 shift_video 会同时改变音频的有效时间表。**音频 shift 一般不动** |
| 默认 shift | `supported_models.MiniMaxH3.sampling_settings`：12 / 3 | 不加节点就是 12/3 |
| 关键帧 | I2V 节点里，首帧拉伸、尾帧中心裁切；VAE 编码后作为条件行每一步重新注入；条件时间步 `max(t_v, 0.999)` | 关键帧就是硬约束，**没有强度可调**（AddGuide 的 denoise 也不能缩放强度，官方文档原话：“does not scale guide strength”） |
| 关键帧给文本编码器 | `clip.tokenize(prompt, images=images)` | Qwen3-VL 能看到首尾帧。提示词要和图一致，否则两路条件会打架 |
| Ref2VA 参考 | match：按面积缩到与生成画布等面积，只缩不放；max：短边 2048。参考 token 每一步都参与计算 | max 会慢好几倍（tooltip：“'max' can be several times slower”）；参考图**不锁构图** |
| 条件噪声 | `visual_cond_noise_aug` 默认 0.999，按 seed 生成 | 换了关键帧，同一个 seed 的结果就不再可比 |
| 去噪掩码 | 视频按 2×2 patch、音频按整帧对齐，被保留的行跑在条件时间步上 | 可以做局部重绘 / 口型重做（只重采音频轨或嘴部区域） |
| CFG | 权重是 CFG 蒸馏的；BasicGuider 只做一次前向，没有负分支 | negative prompt 无效；否定清单只会把被否定的词“写进去” |
| 注意力 | `ModelAttentionBackend`：可选 `pytorch` 或 `comfy kitchen`（INT8 量化），实验性节点 | kitchen 更快，但有损 |
| 保存 | SaveVideo：RGB → YUV 时显式用 BT709 矩阵，并打 bt709 primaries / trc 标记 | H3 原片的颜色标记没问题 |

来源：<https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py>、<https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/ldm/minimax/model.py>、<https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/model_base.py>、<https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/supported_models.py>、<https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_model_advanced.py>、<https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_api/latest/_input_impl/video_types.py>。全部置信度：高。

### 1.1 σ 表（shift 12，simple 调度，用 ComfyUI 同一算法计算）

| 步数 | σ 序列 |
|---|---|
| 20 | 1.0 .996 .991 .986 .980 .973 .966 .957 .947 .936 **.923** .908 .889 .866 .837 **.800** .750 .679 .571 .387 0 |
| 24 | 1.0 .996 .993 .988 .984 .979 .973 .967 .960 .952 .944 .934 **.923** .911 .896 .878 .858 .832 **.800** .760 .706 .632 .524 .345 0 |
| 8（shift 12） | 1.0 .988 .973 .952 .923 .878 .800 .632 0（**与 alibaba-pai PDD 的训练 σ `12t/(1+11t)` 完全相同**） |
| 8（shift 6，768p turbo） | 1.0 .977 .947 .909 .857 .783 .667 .462 0 |

**解读**：
- shift 12 下，20 步里有一半的步落在 σ>0.92。这一段决定构图和运动，所以“运动要好就加步数”的建议主要作用在高 σ 段。
- 最后一步从 0.387 直接跳到 0，细节阶段的步子很粗。这正是两段式把第二段专门用来补细节的理由。
- 常见的切点：项目方工作流在第 10/20 步切，σ=0.923；Pika Flex 表在 0.923 也有一个节点；LBH 和 ganloss 的第二段从 0.9035 起，接着是 .8 / .6316 / .3158 / 0。三家互相印证。

---

## 2. 参数手册（逐节点）

| 节点 · 参数 | 推荐值 | 范围 / 可选 | 作用和理由 | 证据 | 置信度 |
|---|---|---|---|---|---|
| UNETLoader | FL2VA：`minimax_h3_fl2va_pruned_int8_convrot`；Ref2VA：`minimax_h3_ref2va_pruned_int8_convrot` | fp8_scaled / w4a8 / 社区 hybrid / Singularity | pruned int8 在 3090 上又快又稳，**而且不会触发 17 帧暗帧 bug**（full int8 和 bf16 会）。w4a8 加 LoRA 有已知问题 | ComfyUI #15426（Bloodwolfb：“pruned INT8 clean”）；Kijai HF #6 | 中高 |
| CLIPLoader | `qwen3vl_32b_minimax_h3_nvfp4_awq`，type=`minimax` | int8_convrot | 官方模板就是这个文件。3090 没有 FP4 硬件，只是编码慢一点，对画质没影响 | 官方模板 | 高 |
| VAELoader（视频） | int8_convrot 或 fp16 | sol_vae / lightvae（画质更差） | int8 和 fp16 解码结果等价（我们 MOT 实测，加社区 PSNR）。项目方用 fp16，不必跟 | MOT；Comfy HF #69 | 高 |
| VAELoader（音频） | `minimax_h3_audio_vae_fp32` | — | 音频 VAE 必须 fp32 | 官方模板 | 高 |
| MiniMaxH3SigmaShift | 基模、PDD、Pika：12/3（等于默认，可以不加）；768p lightx2v turbo：6/3 | video 0.01–100 | video shift 越大，高 σ 段停得越久，构图和运动越“定”，细节步越少。不要动 audio | supported_models；lightx2v #42/#48/#57；Pika README | 高 |
| ModelAttentionBackend | 成片先用 `pytorch attention`；`comfy kitchen` 进入 A/B | pytorch / comfy kitchen（INT8） | kitchen 是 INT8 量化注意力，提速但有损。mdkberry 在 3060 上测得比 Sage 快 | 源码 tooltip；YouTube d1h5-E7NpuY | 高（机制）/ 低（画质） |
| BlockSparseAttention（VSA） | 只配 FastH3 权重（keep 10%，从 20% 处开始） | — | 需要权重里带 `to_gate_compress`，**基模权重没有** | Comfy FastH3 文档 | 高 |
| KSamplerSelect | 基模：`euler` 或 `res_multistep`（待 A/B）；PDD：必须 `euler` | lcm（Pika）、er_sde、res_2m | 官方模板用 res_multistep；有人报告 euler 让 I2V 变暗减半。PDD 只在训练 σ 上评估，多阶采样器会落到网格外 | 官方模板；Comfy HF #67；Jalen-Brunson PDD README | 中 |
| BasicScheduler | `simple`；基模 20–25 步 | beta（社区）；ManualSigmas | 官方文档原话：“Default 20 steps / Raise steps (e.g. 25) for motion quality” | Comfy 文档 | 高 |
| Guider | `BasicGuider`（cfg 1） | — | 权重已做 CFG 蒸馏，CFGGuider 只会双倍耗时 | HF 模型卡 | 高 |
| SplitSigmas | 两段式时在 σ≈0.92 切（20 步的第 10 步，24 步的第 12 步） | 0.80–0.95 | 切得越早（σ 越高），第二段改动越大、越接近重画；切得越晚，越像只做锐化 | 项目方工作流；LBH 和 ganloss 的 ManualSigmas | 中 |
| 第一段分辨率（ResolutionSelector） | 0.3–0.5 MP（9:16 时 0.5 MP = 544×960） | 0.2–0.7 | 只用来定构图和运动。aifuturetech 实测“resolution of the first pass barely matters” | YouTube RXZtimmlrng；HF lightx2v #41（Leetbeck：0.3→1.2 MP） | 中 |
| MinimaxH3LatentUpscaler3D | fp16；mode=megapixels 或 target dimensions；align=32；短片关掉 chunking | megapixels 0.1–16 | 必须先用 LTXVSeparateAVLatent 把音频拆出来（ganloss 说明原话：“3D 倍率节点必须配合音视频分离/合并节点”）。它省的是时间，不省显存 | LBH 源码与 README | 高 |
| 第二段目标尺寸 | **3090 上 ≤1.03 MP（768×1344 或 736×1312）** | 项目方用 1.4 MP（9:16 时约 928×1600） | 1.4 MP 时 token 数约是 768×1344 的 1.44 倍，注意力开销约 2 倍。我们 768×1344、243 帧时峰值已经 22.7 GB，1.4 MP 必然 OOM（推断）。官方说法：更大尺寸“render slower without adding detail”（FastH3 单段） | 计算；QC_ep02 MOT；Comfy FastH3 文档 | 中 |
| MiniMaxH3ImageToVideo · length | 17k+5，124–362 | — | 用 `ComfyMathExpression max(5, round(a*24)) + (5 - … % 17) % 17` 把秒数换成帧数 | 官方模板 | 高 |
| · width/height | 9:16 用 768×1344；顿挫 A/B 候选 736×1312 | 32 的倍数 | 见 §0 第 5 条 | WanGP #2279 | 低到中 |
| · first_frame / last_frame | 先在图外裁成画布比例（我们的 keyframe_crop 已经做了） | — | 首帧比例不对会被拉伸，尾帧会被裁 | 源码 | 高 |
| MiniMaxH3ReferenceToVideo · ref_image_size | `match` | max（短边 2048，慢好几倍） | #91 实测 max 并没有救回身份 | 源码；MiniMaxAI HF #91 | 中 |
| · ref_images | ≤9 张；身份图放在 slot 0，对应 `<Picture 1>` | — | 只接在 AddGuide 上的图，文本编码器看不见（官方原话：“not visible to the text encoder”） | Comfy multiframe 文档 | 高 |
| · ref_audios | 4–5 s 干声 | 官方 2–15 s | 太长时开头 0.5 s 会乱语 | MiniMaxAI HF #76（rocky533） | 低到中 |
| MiniMaxH3AddGuide · frame_idx | 0 = 首帧，-1 = 尾帧，`round(秒*24)` = 中间帧 | -9999–9999 | 给一段 22 帧的视频可以续接画面和声音；密集打点会“冻脸” | Comfy 文档；Comfy HF #55 | 高 / 中 |
| LoRA（turbo） | 成片不用；预览可用 lightx2v FL2V 8step v1.1 768p @1.0、6/3、8 步、euler/simple | 社区 0.6–1.3 | v1.3 4step 和其他 LoRA 叠加时会坏（官方承认）；强度低会偏暗 | lightx2v #48、#57、#42 | 中高 |
| LoRA（Motion Repair） | 单段约 0.9；两段式时第一段 0.5–0.7、第二段 0.2–0.3 | — | 修慢动作和异常肢体轨迹；强度过高会出 CG 感，还会影响音频 | JOKER141 HF | 中（作者自测） |
| LoRA（Realism-People） | 1.0（作者原话：“the intended strength”），轻用 0.6–0.8；触发词 `r34l1sm` | — | 页面没写 FL2V。和 v1.3 turbo 叠加会坏 | fal HF；lightx2v #57 | 中 |
| PDD Acc（alibaba-pai） | 8 NFE、euler、shift 必须 12/3、强度 1.0；**不能和 turbo 叠加** | nfe 4/6/8 | 官方 8 步蒸馏。普通 LoRA 加载器读不到它的 head bank，必须用专用节点 | alibaba-pai HF；Jalen-Brunson README | 中 |
| 缓存 / 加速节点 | 全部关闭（EasyCache、Spectrum、TeaCache、MiniMaxH3Cache 等） | — | 会改变人物长相和画面质感，H3Cache 还会产生背景杂音 | Comfy HF #30、#51；前人 03 §2.3 | 中高 |
| CreateVideo / SaveVideo | 24 fps；codec auto（自带 bt709） | VHS crf 19 | 保持 24 fps，不要改 16 fps | Comfy HF #37；源码 | 高 |

---

## 3. 项目方参考工作流逐节点解读（`data/ab/owner_workflows/Realistic AI Video MiniMax H3.json`）

**数据流**：

```
LoadImage(角色图) → MiniMaxH3ReferenceToVideo(clip, vae fp16, audio_vae fp32, ref_image_0, prompt, W/H ← ResolutionSelector 16:9 0.5MP, length ← 秒数×24 对齐 17k+5, ref_image_size=match)
UNET ref2va_pruned_int8 → SigmaShift(12,3) → AttentionBackend(comfy kitchen) → BasicGuider
BasicScheduler(simple, 20, 1.0) → SplitSigmas(10) → [高 σ 段] SamplerCustomAdvanced #1（euler，960×544）
  → LTXVSeparateAVLatent → 视频 latent → MinimaxH3LatentUpscaler3D(megapixels 1.4, align 32, fp16) → LTXVConcatAVLatent(放大后的视频 + 第一段音频)
  → [低 σ 段] SamplerCustomAdvanced #2（同一个 guider、同一个 noise 节点）→ VAEDecode / VAEDecodeAudio → VHS_VideoCombine(24 fps, h264, yuv420p, crf 19)
```

| 节点 | 值 | 为什么这样设 | 还能怎么调（对我们） |
|---|---|---|---|
| 56 LoadImage | 一张角色图 | Ref2VA 用参考图锁身份，不锁构图 | 林晚用定妆照或角色卡（正面 + 3/4 侧）；需要首帧构图时另外加 AddGuide frame 0 |
| 57 CLIPLoader | qwen3vl_32b nvfp4_awq, minimax | 官方文件 | 和我们一致 |
| 58 VAELoader | **video_vae_fp16** | 精确路径 | 我们用 int8，实测等价，不必改 |
| 59 VAELoader | audio_vae_fp32 | 必须 fp32 | 一致 |
| 60 ReferenceToVideo | 宽高由 67 接入；`match` | match 把参考图缩到与第一段画布（0.52 MP）等面积，参考 token 少、速度快 | 参考图是在**第一段的小分辨率**下编码的，第二段沿用同一份条件。这是两段式的副作用：身份细节由低分辨率参考决定（推断，低）。可以 A/B 改成 `max` |
| 61 SigmaShift | 12/3 | 等于默认值，只是显式写出 | 不挂 turbo 时可以删 |
| 76 AttentionBackend | comfy kitchen | 提速（INT8 注意力） | 成片前和 pytorch 做 A/B（E3） |
| 62 BasicGuider | — | CFG 蒸馏模型 | 一致 |
| 63 KSamplerSelect | euler | 两段共用 | 和 res_multistep 做 A/B（E4） |
| 64 BasicScheduler | simple, 20, denoise 1 | 官方默认 20 步 | 24/12 切分更接近我们现在的基模 24 步 |
| 65 SplitSigmas | 10 | σ=0.923，正好是基础网格中点：前 10 步定运动，后 10 步定细节 | 0.92 附近是共识；后面可以试 0.88（第二段改动更小、更保守） |
| 67 ResolutionSelector | 16:9, 0.5 MP, multiple 32 → 960×544 | 第一段只负责运动，用小分辨率省时间 | 我们 9:16 → 544×960。注意 960 ≡ 0 (mod 64)，544 ≡ 32；可以试 0.4 MP（480×864，两边都 ≡32） |
| 81 MathExpression | 秒 → 17k+5 帧 | 官方公式 | 一致（我们用 frames_for_seconds） |
| 69 Sampler #1 | 高 σ 段 | — | — |
| 72 / 73 Separate / Concat AV | 只放大视频，音频原样传回 | 3D 上采样只认 24 通道视频 latent | 音频在第一段（低分辨率、10 步）就基本定型了，第二段还会再精修 10 步 |
| 80 LatentUpscaler3D | fp16, megapixels 1.4, align 32, cuda, chunking on, force_unload on | 学习型 3D 上采样，比三线性插值少重影；1.4 MP 由 1.4×1024² 换算，16:9 时约 1600×928 | **3090 上改成 target dimensions 768×1344（或 736×1312）**，否则 10 s 必然 OOM（推断）；不足 32 个 latent 帧（<5 s）时可以关 chunking |
| 75 Sampler #2 | 低 σ 段，同一个 noise 节点 | 同 seed，但分辨率不同，所以噪声张量本身也不同 | 第二段可以单独挂 realism / Motion Repair 0.2–0.3（社区说法：“time-controlled realism”） |
| 78 / 70 Decode | — | — | — |
| 90 VHS_VideoCombine | 24 fps, crf 19, yuv420p | VHS 编码 | 我们用 SaveVideo（自带 bt709 标记），更稳。rkfg 原话：“VHS can shift colors” |
| 85 Prompt | 自由结构（SCENE / ACTION AND TIMING 按秒分拍 / CAMERA / LIGHTING / PERFORMANCE / STYLE / CONSTRAINTS / Avoid …） | 作者按秒写动作节拍、写明镜头幅度、写物理接触 | **与官方格式不一致**：没有 `<Picture 1>` 标签、没有三字段或六字段、末尾有否定清单。按秒分拍、镜头幅度、物理接触这几点值得学；否定清单按官方说法会适得其反。A/B 见 E9 |

### 3.1 对照 WFLIB 解析的 ganloss 30+ 个工作流（`data/ab/owner_workflows/_meta/parsed.json`），解释“为什么”

| 社区取值（WFLIB） | 为什么（本文的机制解释） |
|---|---|
| SigmaShift 一律 12/3；Singularity、FastH3-omni、10eros 不接这个节点 | 12/3 是默认值。蒸馏或微调模型把调度写进了自己的权重或 σ 表，所以不需要 |
| 基模 20 步 res_multistep/simple；turbo 底模 8 步 euler + beta/simple；PDD 必须 euler | res_multistep 是官方模板的默认。蒸馏模型只在训练 σ 上准，多阶采样器会评估到网格外的点（PDD README） |
| 两段式第二段 ManualSigmas “0.9035, 0.6316, 0.3158, 0” | 第二段从基础网格中点（σ≈0.92）附近开始，只补细节、不改运动；3 步就够，是因为高 σ 段已经在第一段跑过了 |
| 第一段 0.2 MP → 放大到 1280×704 或 1.0 MP | 第一段只决定构图和运动，分辨率影响很小（aifuturetech 原话：“barely matters”）；第二段不超过训练面积 1.03 MP |
| SelfLift：transition_step 4、lowres_scale 0.4、rho 0 | 同一个思路做成单个节点：前 4 步在 0.4 倍分辨率下跑，然后升到全尺寸 |
| BlockSparseAttention sol-attn tau 1.3，start 0.2，end 0.9–1 | 前 20% 的高 σ 步用全注意力定构图，之后用稀疏注意力省算力；YouTube n0qavGLdKNE 原话：“0.2–0.9 eliminates end-stage noise”，意思是最后 10% 也回到全注意力 |
| Turbo 4step 强度 0.75（早期）→ v1.1 起 1.0 | v1.1 以后的版本是按 1.0 训练的；强度不够时画面偏暗、提示词跟随变差（lightx2v #42、#9） |
| 慢动作的解法是 PDD-Acc 8 步，不是调 shift | turbo 的慢动作来自蒸馏本身。PDD 换了一种蒸馏方法（parallel decoding head），而且 σ 网格和基模一致 |
| 长镜头用 Motion Context 22 帧续接，提示词先复述上一段的结尾 | 22 帧 = 17×1+5，是最短的合法多帧引导（AddGuide tooltip：“5, 22, 39…”），能同时续接画面和声音 |
| 脸部重绘第二遍 denoise 0.4–0.5 | shift 12 下，denoise 0.4 对应的起始 σ 约 0.89，接近“补细节”的起点；FaceRefine 的默认值也是 0.40 |

**WFLIB 第 2 批（160 个流的参数分布）补充解释：**
- **shift 少数用 12/6、6/3、10/3。** video shift 越低，高 σ 段的步数越少、越早进入细节。这可能减轻“过度定型”造成的慢动作，但运动结构也会变弱。音频 shift 从 3 改到 6，音频会更早定型（推断，低）。LAB 已经在跑这三档。
- **refine 的 denoise 多数用 0.4，其次 0.45、0.2。** shift 12 下，denoise 0.4 的起点约 σ0.89，0.2 约 σ0.75：前者能修脸和细节，后者基本只是锐化。
- **ref_image_size：match 79 次，max 19 次**，与官方“推荐 match”一致。
- **竖屏放大：sepiablue 用 736×1280 → 3D 放大到 1104×1920。** 736 ≡ 32 (mod 64)，可以和 E2 的 736×1312 一起看。但 1104×1920 约 2.1 MP，3090 上只适合短镜头（推断）。
- **turbo 4 步拖影，6–8 步基本消除**（Larryvrh README 原话）。强度 1.05–1.2 修糊，0.8–0.95 修过锐。

**一句话总结**：这个工作流 = Ref2VA 身份锁 + 两段式（0.5 MP 定运动 → 3D latent 放大 → 高分辨率补细节）+ INT8 注意力提速。我们缺两样东西：两段式和 Ref2VA 身份锁。

---

## 4. 各模式推荐配方（3090、9:16）

| 模式 | 质量档（成片） | 快档（预览） | 证据 |
|---|---|---|---|
| I2VA（只给首帧，现默认） | int8 pruned FL2VA，24 步，euler/simple，12/3，cfg 1，768×1344，提示词第一行写 I2VA 对齐句 | lightx2v 8step v1.1 768p @1.0，6/3，8 步；或 PDD 8NFE（12/3，euler） | MOT；lightx2v #48；alibaba-pai |
| FL2VA（首尾帧） | 同上，但**尾帧必须和首帧有明显差异**（我们 QCV 用首尾帧差 ≥10），提示词写清中间路径，单镜头 | 同上 | 官方 guide；QCV |
| Ref2VA（身份） | ref2va pruned int8，**20–25 步**（官方原话：“Prefer 20–25 steps when references must hold”），match，ref slot 0 放身份图；需要构图时加 AddGuide frame 0（首帧），并把首帧也接到 ref slot（官方 multiframe 结构） | 不推荐 turbo（官方原话：“weaker on references and audio”；有人报告 9:16 上半画面重影） | Comfy 文档；lightx2v #44 |
| 两段式（任一模式） | 0.5 MP（544×960）跑高 σ 段 → 3D 放大到 768×1344 → 低 σ 段；在 24 步的第 12 步切（σ .923） | 第一段 PDD 8NFE 或 turbo，第二段 3–4 步 ManualSigmas（.9035 .8 .6316 .3158 0） | 项目方工作流；ganloss；LBH |
| T2VA | 本项目不用 | — | — |

GPU 时间粗估（推断，低）：基模 24 步、192 帧约 41 min/镜。两段式第一段在 0.52 MP 时每步约 0.3–0.4 倍开销，12 + 12 步约合 16 个全分辨率步，**预计每镜省约 30%**。

---

## 5. 问题 → 解法对照表

| 问题 | 机制或原因（证据） | 解法（按证据强弱） | 置信度 |
|---|---|---|---|
| **卡顿 / judder（每 4 帧一顿）** | `FRAME_PER_TOKEN=(1,4,4,4,4)`；turbo 加重（MOT：turbo J4 1.34 → 基模 24 步只给首帧 1.12）；另有成对重复帧（MiniMaxAI HF #74：“almost identical 2 frames”） | ① 基模多步 ② `tools/dejudder.py`（J4 → 1.08）③ A/B 736×1312 ④ 不要用 Spectrum / 缓存 | 高 / 中 / 低 |
| **每 17 帧暗帧加卡顿** | full int8 / bf16 的 time_embedder dtype 问题（ComfyUI #15426） | 用 pruned int8（我们正是这样） | 中 |
| **每秒（24 帧）一跳的平移顿挫** | WanGP 的实现问题；但 ComfyUI 下 1344×768 也有人测到（okkazoo） | 宽高取 ≡32 (mod 64) | 低到中 |
| **动作慢 / 漂浮** | turbo（lightx2v #36/#39/#58）；提示词没写力度；训练数据偏慢（推断） | ① 不用 turbo ② 动词带力度：“makes an energetic and rapid jump”（gilly2020），官方允许写 `at fast speed` ③ Motion Repair 0.9 ④ 速度滑块 LoRA（“3 to 4 is the sweet spot”）⑤ PDD 替代 turbo（ganloss 的“correct slow motion”工作流）⑥ 去掉写作规则里的“偏慢速度”和“语速偏慢”（推断） | 中 |
| **静止不动** | 首尾帧几乎一样，硬钉（源码）；turbo | ① 只给首帧（QCV 实测 ×2–5）② 尾帧要有明显差异，并写出中间路径（MiniMaxAI HF #81）③ 出片前做首尾差闸门（QCV 已上线） | 高 |
| **结尾冻结** | 尾帧在 `frame_count-1` 被每步注入，模型会提前“落定” | ① 不给尾帧 ② 尾帧取“动作仍在进行中”的瞬间，而不是动作结束后 ③ 剪辑时自动剪掉定住段（DIR 已建议） | 高（机制）/ 中 |
| **鬼影 / 多肢 / 走路多腿** | turbo 把两个姿态叠进一个 latent（MOT 实测）；Ref2V turbo 在 9:16 下上半画面重影（lightx2v #44） | ① 基模多步 ② Motion Repair（“abnormal limb trajectories”）③ 学习型 3D 上采样，不用插值放大（LBH 原话：“avoids the ghosting”）④ ClownShark 采样器（社区 2 人报告“solves the ghosting”，低） | 高 / 中 / 低 |
| **手部** | 远景、小手、快动作 | ① 提示词写物理接触和手指动作（项目方 prompt 的做法）② 两段式第二段补细节 ③ 近景 | 低 |
| **脸漂移 / 小脸崩** | 头占画面太小时 H3 画不好（Carasibana 原话：“renders faces poorly when the head occupies a small fraction”）；官方承认，称“系统性解决中” | ① 中近景；远景写 5–6 s、不说话（已在写作规则里）② Ref2VA + 角色卡 + AddGuide ③ FaceRefine（裁脸 → H3 重绘 → 贴回，denoise 0.40，crop 2.5）④ v2v 低 denoise（0.15）精修 ⑤ 1 MP 是甜点 | 中 |
| **身份不一致（跨镜）** | FL2VA 只靠首帧和 LoRA；男角色没有参考（chain_audit C1） | ① 每个角色都要有参考图 ② Ref2VA multiframe ③ 每镜用不同 seed（joeygambino：同一个 seed 反而让脸和声音都漂）④ 提示词里逐字复用身份短语 | 中 |
| **脸部突然泛红 / 红斑** | ① 提示词含 flush 类词（v0 审片，强）② Pika 放大（强）③ 只给首帧，有时间漂移（中；#55 原话“intensifies frame by frame”）④ krea2 让首帧偏红（强）⑤ 8 s 以上嘴唇变红（lightx2v #53，单人）⑥ VAE 编解码偏色（#78，4 人）。**已排除**：编码矩阵（源码加 ffprobe）、cfg（=1，没有可调空间）、shift（#55 改步数无效；shift 没人测过） | ① 关键帧去掉 krea2 或降到 0.25 ② flush 类镜头不用 Pika ③ skin guard（DIR 的 R1）④ Realism-People LoRA 1.0（#55 说能压住，但“fragile”）⑤ 中间 AddGuide 打肤色锚点（会冻脸，不推荐）⑥ 后期以首帧为锚做 gain_bias 校色 | 高（排除项）/ 中 |
| **过饱和 / 对比度升高 / 发暗** | turbo 强度低 → 暗、高 → 过曝；4step v1.1 偏暗；续接时逐段累积（6 人以上）；I2V 前 1.5 s 背景变暗（#67） | ① turbo 强度 1.0 ② 不用续接链 ③ 以锚帧为参照做按通道 gain/bias 校色（不要用 LUT）④ euler 代替 res_multistep（#67 原话：“roughly halves” I2V 变暗） | 中 |
| **tiled decode 色带或拼缝** | 9:16 有 tile 线（ComfyUI #15885，单人）；09-22 已修 | 用最新版 ComfyUI；VAEDecode 不手动分块 | 低 |
| **口型不同步** | ①合成时用 TTS 盖掉了 H3 原声（已修，dialogue_source=h3）② VO 驱动了画面里的嘴 | ① 用 H3 原声 ② VO 写 “Female narrator voice, saying …” 并加 “lips remain closed”，不要写“the man”（Comfy HF #44）③ 一镜一位说话人 ④ 必要时用去噪掩码只重做音频轨（rocky533：“latent noise masking the audio channel”） | 中 |
| **开头乱语 / 杂音 / 机器声** | 没写 soundscape、`</d>` 前没句号、参考音频太长、步数少 | ① 三条硬规则（§0 第 10 条）② 参考音频约 4 s ③ ≥8 步 ④ 关掉 H3Cache（#51） | 中 |
| **音色不一致** | 没用 ref_audios | Ref2VA 加 `<Audio 1> is the voice-timbre reference for <Subject N>`，加 retention 标记 `reference`。注意 #91：加音频参考后身份崩了（单人） | 低到中 |
| **环境音太小** | 说话时模型压低环境声（#40、#82） | 后期用整集 BGM 加 ducking；H3 没有分轨 | 中 |
| **闪烁** | 3D 上采样末尾闪烁（LBH 已修，用 chunking）；缓存节点 | 开 `enable_temporal_chunking`；不用缓存 | 低 |
| **中途全黑 / 光圈收拢** | 和 seed、分辨率有关，1.3 MP 时 4/12 个 seed 出现（#67） | 换 seed；≤1 MP | 低到中 |

---

## 6. 提示词写法（官方为最高置信）

| 规则 | 官方原文（<15 词） | 来源 | 置信度 |
|---|---|---|---|
| 除台词和画面文字外一律用英文 | “Write rewrite sections in English” | skills/h3-prompt-writing SKILL.md | 高 |
| 结构 | base：三字段；Ref2VA：六字段（subject_definitions…） | base-en / ref-en | 高 |
| 对齐句放第一行，后面空一行 | “must be the first line of the final prompt” | base-en | 高 |
| I2VA 对齐句 | “at 0.00 seconds … <Picture 1> (from [Shot 1]) is fully referenced.” | base-en | 高 |
| FL2VA 单镜头 | “FL2VA generally favors a single shot” | base-en | 高 |
| FL2VA 写路径 | 首帧状态 → 中间变化 → 差距收窄 → 尾帧 | 官方 guide；MiniMaxAI HF #81 | 高 |
| 幅度和速度只在有意义时写 | “medium amplitude and normal speed are usually omitted” | base-en | 高 |
| 运镜写成句中动作 | “natural English action within the shot” | base-en | 高 |
| 切镜用单一时间戳 | “At 00:03.500, the camera cuts to …” | Comfy prompt guide | 高 |
| 不写否定清单 | “Ban lists add the unwanted concepts” | Comfy prompt guide | 高 |
| 台词格式 | `(S1) says: <d>[Chinese] 原话。</d>`，`</d>` 前有句号 | base-en；HF #76 | 高 / 中 |
| 省略号会伤清晰度 | “Ellipses often hurt intelligibility” | Comfy prompt guide | 高 |
| VO 写法 | 加 “says in an off-screen voiceover”，后面接 “lips remain closed” | base-en | 高 |
| soundscape 1–4 句，不写 N/A | “N/A only … complete silence” | base-en | 高 |
| Ref2VA 的长度 | “normally 350–500 English words” | ref guide | 高 |
| 画面文字用英文双引号原样写 | “A red neon sign reading "营业中"” | Comfy prompt guide | 高 |
| 动作要写力度 | “energetic and rapid jump” 比 “jumps” 有效 | lightx2v #58（gilly2020） | 中 |
| 格式对了画面就更清晰（单人测量 26 → 367） | “Treat 26 vs 367 as a direction” | YouTube 8fKyrKevEcw | 低 |
| 按秒分拍（项目方 prompt 的做法） | 官方用 `[Shot N] At MM:SS` 切镜；同一镜内按秒分拍**官方没写** | 项目方工作流 | 低（需 A/B） |

**对我们写作规则的提醒**（由总调度转写作方，系统不改内容）：
- “动作量以正常或偏慢速度做完”（H3-A11）和林晚声线里的“语速偏慢”，可能会和模型本身的慢动作倾向叠加（推断，低）。
- 只给首帧时，正文里仍然出现 “Picture 2”（CHAIN C5）。

---

## 7. 后处理与长片

| 项 | 建议 | 证据 | 置信度 |
|---|---|---|---|
| 插帧 / 去抖 | 我们的 `tools/dejudder.py`（光流插帧后按真实时间重排）已经针对“4 帧一顿”和“成对重复帧”。社区对重复帧的做法是 GIMM-VFI / RIFE 只补重复帧；**不要把 24 fps 插到 30/60 后交付**（H3 原生 24） | MiniMaxAI HF #74；MOT | 中 |
| 超分 | ① H3 自己做 v2v 低 denoise 精修（mdkberry：1–2 MP，“fixes faces at distance”）② 局部 FaceRefine ③ 非 H3 的超分（RTX VSR、SeedVR2）只做像素放大。**两段式 latent 放大只用在独立镜头上** | YouTube d1h5-E7NpuY、VtHC45Zen30；Carasibana | 中 |
| 去闪烁 | 上采样器开 chunking；不用缓存节点 | LBH changelog | 低 |
| 调色统一 | 以**我们自己的定稿关键帧**为参照，按通道做 gain/bias（不用 LUT、不和相邻镜互相匹配）；只在人物区域取统计量 | 前人 03 §2.2（3 个独立项目） | 中 |
| 长视频拼接 | ① 镜头独立生成（我们的做法）是首选 ② 一定要续接时，用 AddGuide 把上一段最后 22 帧（17k+5）放在 frame 0，画面和声音都能接上（官方文档原话：“22 frames at frame_idx 0 continue both streams”）③ 续接链只能单段采样 ④ 续接会累积对比度，要以固定锚帧校色 | Comfy 文档；YouTube jsqHFgbjL08；前人 03 | 中高 |
| 多镜一致性 | 每个角色一份参考图和固定身份短语；Ref2VA multiframe；每镜用不同 seed；同一场戏用同一组光线和色温描述 | §5 | 中 |
| 音频 | H3 原声做对白；整集 BGM 在对白下 duck；独白用 TTS 时要按镜时长截短 | QC_ep02 §5 | 高 |

---

## 8. ep02 A/B 实验清单（交 LAB，按收益和成本排序）

**统一条件**：同一镜（ep02-S1 走路，S2 对白近景，S4 静态镜头）、同一张定稿首帧、同一份提示词正文、同一个 seed，只改一个变量。指标沿用现有工具：
- 运动：`motion_qc`（平均帧差、静止帧占比）；
- 顿挫：`motion_judder.py`（J4、z）；
- 腿部：条带图；
- 泛红：`review.py` 的脸颊 a*p95 和漂移；
- 身份：SFace 余弦；
- 音频：SenseVoice CER；
- 时间：秒/镜。

先跑 124 帧省时间，结论稳定后再跑全长。

| # | 改什么 | 对照 | 预期 | 怎么测 |
|---|---|---|---|---|
| E1 | **两段式**：544×960 跑 24 步里的前 12 步（σ 1→.923）→ LBH 3D 放大到 768×1344（target dimensions）→ 后 12 步 | 现默认：基模 24 步单段 768×1344 | 时间约 -30%；细节相当或更好；运动相当 | 时间、J4、腿部条带、脸部 Laplacian 方差、a*p95 |
| E2 | **分辨率**：736×1312 | 768×1344（同为基模 24 步） | 如果 mod-64 假说成立，平移顿挫减轻 | J4、光流节奏；要选有平移或推拉的镜（S1） |
| E3 | **注意力**：pytorch vs comfy kitchen | 同配方 | kitchen 更快，画质可能略降 | 时间、PSNR/SSIM（逐帧对照）、a*p95、肉眼 |
| E4 | **采样器**：res_multistep vs euler（基模 24 步） | euler | 官方模板默认 res_multistep；#67 说 euler 变暗少 | 亮度曲线（外圈均值）、J4、细节 |
| E5 | **Ref2VA multiframe**：ref2va int8，`<Picture 1>` = 定稿首帧（slot 0）+ 林晚角色卡（slot 1/2），AddGuide frame 0 = 首帧，24 步，match，六字段提示词 | FL2VA 基模 24 步只给首帧 | 身份更稳；画质可能略降（社区分歧） | SFace 余弦（逐帧最小值）、印样、a*p95 |
| E6 | **Motion Repair LoRA 0.9**（基模 24 步） | 不挂 | 动作更像实时，肢体轨迹更顺 | 平均帧差、光流节奏、腿部条带 |
| E7 | **PDD Acc 8NFE**（需要先装节点和权重，许可核查交总调度） | 基模 24 步 | 时间约 1/3，运动接近基模（未知） | 全部指标 |
| E8 | **FL2VA 尾帧取“动作进行中”**（首尾差 ≥15，由写作方或出图出新尾帧）+ 提示词写中间路径 | 只给首帧 | 既能对上尾帧，又不冻结 | 结尾定住秒数、首尾差、motion_qc |
| E9 | **提示词格式**：项目方结构（按秒分拍加 CAMERA 等段，**去掉 Avoid 清单**）vs 官方三字段（内容相同，由写作方改写） | 官方格式 | 未知；按秒分拍可能让动作更饱满 | 运动指标、CER、项目方看片 |
| E10 | **音频硬规则**：soundscape 必写、`</d>` 前加句号、不说话的人写 silently | 现提示词 | 开头乱语和杂音减少 | SenseVoice 前 1 s 有无乱语、CER |
| E11 | **第二段 realism**：两段式只在低 σ 段挂 Realism-People 1.0（触发词） | E1 | 皮肤更真，红斑受压 | 脸部 Laplacian、a*p95 |
| E12 | **ref_image_size max** vs match（只在 E5 有效时做） | match | 身份略好，慢好几倍 | SFace、时间 |

**不建议做**：4step 系列（尤其 v1.3）、w4a8 加 LoRA、任何缓存节点、1.4 MP 第二段（3090 显存不够，推断）、CFGGuider 或 negative prompt。

---

## 9. 建议写进 `config/render_quality.json` 的默认值（只是建议，没有改 config）

```jsonc
// video_bases 新增两个基底（是否设为 default 由总调度看 E1/E5 结果后决定）
{
  "id": "official_base_2stage",
  "label": "基模24步·两段式（试验）",
  "no_lora": true,
  "steps": 24, "split_step": 12,                 // σ 0.923
  "pass1_size": [544, 960],                      // 9:16, 0.52 MP
  "pass2_size": [768, 1344],                     // 3090 上不超过 1.03 MP；E2 通过后改成 [736, 1312]
  "upscaler": {"node": "MinimaxH3LatentUpscaler3D", "model": "minimax_h3_latent_upscaler_3d_fp16.safetensors",
               "mode": "target dimensions", "align": 32, "temporal_chunking": "auto(T>32)"},
  "sampler": "euler", "scheduler": "simple", "shift": [12.0, 3.0], "shift_node": false,
  "cfg": 1.0, "guider": "BasicGuider", "attention": "pytorch",
  "default_last_frame_mode": "none",
  "license_check": "LBH 上采样器 MIT（gpu33 文档标注“来源和许可都还没确认”，需总调度登记）"
},
{
  "id": "ref2va_multiframe",
  "label": "参考图锁身份·首帧钉住（试验）",
  "unet": "minimax_h3_ref2va_pruned_int8_convrot.safetensors",
  "steps": 24, "sampler": "euler", "scheduler": "simple", "shift": [12.0, 3.0],
  "ref_image_size": "match", "ref_slots": ["first_frame", "character_sheet_front", "character_sheet_34"],
  "add_guides": [{"image": "first_frame", "frame_idx": 0}],
  "prompt_format": "ref_six_field"
}
```

其他建议：
- `official_base.attention` 写明 `pytorch`（防止以后有人顺手加上 kitchen）。
- `official_base.sampler_ab` 记下 res_multistep 待测。
- `motion_qc` 加一项 `j4_warn: 1.2`（DIR 已在 review.py 定标）。
- 新增 `h3_prompt_lint`：soundscape 不为空、`</d>` 前有句号、只给首帧时正文不含 “Picture 2”（交 CHAIN 实现）。

---

## 10. 我们之前“只做了一半”的地方（对照本地文档）

| # | 只做了一半的点 | 本地现状 | 缺的另一半 |
|---|---|---|---|
| 1 | **两段式 / latent 放大** | 关键帧出图有两遍（pass1 → pass2），视频始终单段 768×1344；FASTH3 文档“两段式已实现，默认关” | 视频两段式从没跑过（项目方工作流的核心就是它）→ E1 |
| 2 | **采样器** | 一直用 euler（理由是“euler 变暗约减半”） | 没和官方模板默认的 res_multistep 做过 A/B → E4 |
| 3 | **shift 的理解** | 把 12/3 当作“要显式加节点的参数” | 它就是默认值；真正需要关心的是 turbo 的 6/3 |
| 4 | **首尾帧机制** | 用统计发现了“首尾差小 → 静止” | 源码层面的原因（每步硬注入加 Qwen 也看图）→ 尾帧应该取动作进行中的瞬间（E8），而不只是去掉尾帧 |
| 5 | **Ref2VA** | 调研多次推荐 multiframe，但生产只用 FL2VA；男角色没有任何参考（CHAIN C1） | 从没实测 → E5；角色参考资产闸门 |
| 6 | **顿挫** | 找到了 latent 结构原因，用 dejudder 后处理 | 分辨率 mod-64 假说没测 → E2 |
| 7 | **慢动作** | 把原因归到 turbo，换成基模 | 提示词力度、Motion Repair、PDD、写作规则里的“偏慢”都没处理 → E6/E7、转写作方 |
| 8 | **注意力后端** | 只禁了缓存类节点 | kitchen INT8 注意力的画质影响没测 → E3 |
| 9 | **红脸** | DIR 已追到 krea2、flush 提示词、Pika；编码链路做了实测 | 源码确认 SaveVideo 是 bt709（本文补上）；“低 σ 段才挂写实 LoRA”的思路没试 → E11 |
| 10 | **音频** | 改用 H3 原声 | 三条提示词硬规则和 ref_audios 音色锁没用上 → E10 |
| 11 | **提示词格式** | 严格按官方格式（这是对的） | 没吸收项目方 prompt 里有用的部分：按秒分拍、物理接触描述 → E9 |
| 12 | **长镜头** | 294 帧靠 1e-4 强度的 LoRA 绕过 OOM | 正解是两段式（第一段小分辨率），或者拆成 ≤243 帧再用 AddGuide 22 帧续接 |
| 13 | **种子可比性** | A/B 时换关键帧仍用同一个 seed | diffusers 原话：换了关键帧之后，同一个 seed 不保证可比（条件噪声先抽）→ A/B 时关键帧固定，或每组多 seed |

---

## 11. 没找到或不确定的内容

- shift_video 对泛红有没有影响：没人测过。
- 1.4 MP 第二段在 3090 上的实际显存：没有公开数据，“必然 OOM”是我按 token 数推算的。
- comfy kitchen INT8 注意力对画质的定量影响：没有公开测量。
- res_multistep 和 euler 在基模 24 步下的系统对比：只有 #67 一条间接证据。
- Singularity V2、Hybrid 等社区微调权重：许可没核，本文只列不推荐。
- YouTube 只读到了描述和章节，没有拿到字幕，视频里口头讲的参数没有覆盖。
- Reddit：搜索引擎没有收录到相关帖子（只拿到一个 r/comfyui 帖子标题，“BGM disappears at 480p”，没读到正文）。

---

## 12. 来源清单（本文新增；前人文档里已有的不重复列）

**官方 / 源码**
- ComfyUI 源码：nodes_minimax_h3.py、ldm/minimax/model.py、model_base.py、supported_models.py、model_sampling.py、nodes_model_advanced.py、nodes_resolution.py、comfy_api video_types.py — <https://github.com/Comfy-Org/ComfyUI>
- Comfy 文档：<https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native.md>、`…/minimax-h3-multiframe.md`、`…/minimax-h3-prompt-guide.md`、`…/minimax-h3-fastvideo.md`、`…/minimax-h3.md`
- 官方模板：<https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_minimax_h3_i2v.json>、`video_minimax_h3_r2v.json`
- MiniMax：<https://huggingface.co/MiniMaxAI/MiniMax-H3>、VIDEO_PROMPT_WRITING_GUIDE_base_en.md / ref_en.md、<https://github.com/MiniMax-AI/MiniMax-H3/tree/main/skills>（本地副本：`data/ab/owner_workflows/minimax_h3_official_skills/`）
- ModelTC：<https://github.com/ModelTC/Minimax-H3-Turbo>；lightx2v：<https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/42>、`/48`、`/57`
- alibaba-pai PDD：<https://huggingface.co/alibaba-pai/MiniMax-H3-Acc-LoRAs>、<https://github.com/Jalen-Brunson/ComfyUI-MiniMax-H3-PDD-Acc>

**第三方节点 / LoRA**
- LBH 3D 上采样器：<https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler>（源码 nodes/minimax_h3_latent_upscaler_3d.py、示例 workflow3）
- Motion Repair：<https://huggingface.co/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair>
- Realism People：<https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA>
- FaceRefine：<https://github.com/Carasibana/ComfyUI-H3-FaceRefine>
- ganloss 工作流库：<https://github.com/amao2001/ganloss-latent-space/tree/main/workflow>（读了 pdd-acc correct slow motion、latent upscale 两份的作者说明和关键参数）

**社区讨论**
- Comfy-Org HF：#30、#35、#37、#40、#44、#48、#51、#55、#67、#69 — <https://huggingface.co/Comfy-Org/MiniMax-H3/discussions>
- lightx2v HF：#26、#32、#36、#39、#41、#42、#44、#48、#53、#54、#57、#58
- Kijai HF：#5、#6、#8、#9、#16、#18 — <https://huggingface.co/Kijai/MiniMax-H3_comfy/discussions>
- MiniMaxAI HF：#74、#76、#78、#81、#82、#83、#84、#85、#87、#91、#96、#106
- GitHub：ComfyUI #15426、#15978；<https://github.com/deepbeepmeep/WanGP/issues/2279>；<https://github.com/ethanfel/ComfyUI-MiniMaxH3-Context-Loop/issues/96>

**YouTube（读了描述和章节）**
- RXZtimmlrng（aifuturetech：split-sigma 多段采样，“first pass barely matters”）
- 0tTrR_NA8aA（快动作：8 低 + 4 高 + 1 refiner，速度滑块 3–4）
- n0qavGLdKNE（ganloss 作者：Singularity V2 + SelfLift lowres_scale 0.4、transition_step 4）
- IlVPJI9ceKM（De-RoPE 修运动拖影）
- hHoMM2NSF1Y（速度 LoRA、RefMods）
- 8fKyrKevEcw（六字段格式）
- wLSUEQ2l3EE（turbo + TaoMate）
- jsqHFgbjL08（长片单段采样、8 步保音频）
- zLxdMrUkfUk（长片）
- d1h5-E7NpuY 和 cTVXNlHqfAI（mdkberry：v2v 修远景脸，kitchen 比 Sage 快，2 MP 最好）
- VtHC45Zen30（time-controlled realism，3090 实测）
- HJteqahyEKM（双采样修塑料皮肤）
- 5MdcbDv8Pcc（VLM 自动改写提示词）
- 2lgXmEBzzrs 和 b63rw1KfcTM（中文短剧全流程，YZ 金鱼多合一工作流）
