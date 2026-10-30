# H3 脸部与身份：六项深度调研（FaceRefine / Singularity V2 / Combined 节点 / #47 / 单帧 VAE / Ref 提示词指南）

> 2026-10-31，只读调研。没有下载模型、没有跑 GPU、没有改代码。
> 方法：逐个读官方卡片、README、节点 Python 源码（raw.githubusercontent / HF raw），再读 GitHub issue、HF 讨论区。Reddit 被屏蔽（www.reddit.com 与 old.reddit.com 都拿不到），所以 Reddit 帖子只记录了标题，见文末“没找到 / 没读到”。
> 置信度：高 = 官方文档或源码；中 = 多名用户一致；低 = 单人帖子或我的推断。
> 背景：我们的 H3 定档参数是 `minimax_h3_fl2va_pruned_int8_convrot` + `minimax_h3_fl2v_turbo_8step_v1.1_768p` @1.0，shift 6/3，euler/simple 8 步，cfg 1，int8 视频 VAE，fp32 音频 VAE，每镜单独种子，768×1344，243 帧。

## 0. 结论速览

| # | 项目 | 结论 | 链路位置 | gpu3 是否已有 | 置信度 |
|---|---|---|---|---|---|
| 1 | Carasibana H3-FaceRefine v1.1.2 | **值得 A/B，排第一**。它的官方模板用的正是我们的 FL2VA int8 底模 + FL2V turbo 8 步。默认的大脸倍率 0.35 会让近景几乎不变，所以只对远景、小脸有效 | 后期（H3 出片后再跑一遍 H3） | 缺：节点、NativeAudioLock、Impact-Pack、VHS、YOLO 检测器、pip 依赖。H3 模型都有 | 机制：高；效果：低-中（作者以外只有 1 人说 “okay”） |
| 2 | Singularity V2 | **不作主底模**。文件名就是 `ref2va`，社区（≥5 人）说 V2 的参考图保持比 V1.3 差，而且偏灰。只配当 X4 身份通道里的一个候选 | H3 | 没有（21 GB 需下载） | 中 |
| 3 | Combined Image+Ref 节点 / 官方 multiframe 模板 | 核心 ComfyUI 已经原生支持“关键帧 + 参考图”同时出现在一个 PackedLayout 里，所以 **Combined 节点不是必需的**。官方模板（Ref2VA + ReferenceToVideo + AddGuide）用现有节点就能搭。**关键坑（源码）：只要接了参考图，首尾帧就不再进入文本编码器**，`<Picture N>` 只按 ref 槽位编号 | H3 | 官方模板需要的文件都在（ref2va int8、ref2v turbo）；Combined 节点没有 | 高（源码） |
| 4 | HF #47 | **不是官方帖**，是用户 cushycrux 整理的 I2VA 系统提示词。其中的 I2VA 对齐句和官方 `base_en.md` 逐字一致。I2VA 只给首帧；FL2VA 给首帧加尾帧，对齐句不同 | 提示词（H3 输入） | 不涉及文件 | 高 |
| 5 | iamkaikai Single-Frame VAE 500K | **与我们无关**。它只有解码器，只解单帧，卡片原文写着不能当视频解码器用 | 不进链路 | 没有，也不需要 | 高 |
| 6 | 官方 `VIDEO_PROMPT_WRITING_GUIDE_ref_en.md` | 做 Ref2VA 身份实验（X4）前必须照它写六段式提示词。规则见 §6 | 提示词（H3 输入） | 不涉及文件 | 高 |

**对旧报告（kimi 0855/1040/1424）的更正**
- “#47 是官方 I2VA 对齐句”：句子本身是官方的（来自 `base_en.md`），但 #47 这个帖子不是官方发的。
- “Singularity V2 只有 31.7 GB int8”：现在已经有 pruned int8，约 21 GB（WarmBloodAban 和 WAS 两个仓库都有）。
- “FaceRefine 默认 canvas = auto_capped_768”：代码里的默认值是 `manual` 768。`auto_capped_768`、`crop_factor 3.0`、`feather 24` 是示例模板里的取值。
- “Combined 节点需要 hybrid 底模”：节点代码不检查底模，核心 ComfyUI 本身就能合并关键帧和参考图。不过官方 FL2VA 权重的训练任务只有 `t2va`/`fl2va`（见 h3_deep/01_official.md），喂参考图给 FL2VA 属于训练外用法。

---

## 1. Carasibana/ComfyUI-H3-FaceRefine

来源：README <https://github.com/Carasibana/ComfyUI-H3-FaceRefine>；源码 `nodes.py`（3477 行）、`requirements.txt`、`pyproject.toml`（version = "1.1.2"）；示例 `example_workflows/H3_Face_Refine_Auto_Select.json`；issues #1–#19（共 16 条，含 PR）；Discussions（4 条，只有标题可读）。GitHub 页面显示 554 星、46 fork。许可证 MIT。

### 1.1 原理（高）
- README 原文：“A ComfyUI custom node set to refine and improve the quality of small faces in MiniMax H3 video.”
- 流程：逐帧检测人脸 → 平滑跟踪 → 裁成方形画布 → `H3 Inject Video Latent` 把真实帧编码进 AV latent 的视频半边 → H3 以低 denoise 重绘 → `H3 Face Stitch Back` 只把脸框区域贴回原片。
- README 原文：“**Only the face region composites.** The wide crop exists to give the sampler *context*.”
- 图示（README “How it fits together”）里用的条件节点是 `MiniMaxH3ReferenceToVideo`（refs + prompt），模型路径是 `UNETLoader ► turbo LoRA ► MiniMaxH3NativeAudioLock ► H3 Per-Frame Denoise ► BasicGuider`。

### 1.2 示例模板的实际取值（高，读的是 JSON）
| 节点 | 取值 |
|---|---|
| UNETLoader | `minimax_h3_fl2va_pruned_int8_convrot.safetensors`（**和我们完全相同**） |
| LoraLoaderModelOnly | `minimax_h3_fl2v_turbo_8step_v1.0_comfyui_bf16.safetensors` @1.0 |
| BasicScheduler | simple, 8 步, denoise **0.4** |
| KSamplerSelect | **er_sde**（我们用 euler） |
| MiniMaxH3ReferenceToVideo | 768×768, length 362（由 frame_count 自动接线）, ref_image_size `match`；两个 LoadImage：`character_reference.png`、`second_reference.png` |
| H3FaceTrackCrop | `face_yolov8m.pt`, confidence 0.35, **crop_factor 3**, 768×768, **auto_capped_768**, smooth 21/51 gaussian, per_frame, identity_track True, 0.28, largest_face, fallback `person_yolov8m-seg.pt`, insightface |
| H3PerFrameDenoise | small 1.0 / large 0.35, absolute_px, 30 / 120 px, gamma 1, smooth 9 |
| H3FaceStitch | face_only, mask_dilation 24, feather 24, colour_match 1, blend 1, fade_out |
| VAE | `minimax_h3_video_vae_fp16` + `minimax_h3_audio_vae_fp32` |
| 文本编码器 | `qwen3vl_32b_minimax_h3_nvfp4_awq` |
| 静音（不启用）的节点 | GGUF 加载器、SAMLoader/H3FaceMaskSAM、独立人声音轨加载 |

模板里**没有** `MiniMaxH3SigmaShift`，所以 shift 走模型默认值 12。README 的 denoise 表也是按 shift 12 算的。

### 1.3 各节点的输入和默认值（高，源码 `INPUT_TYPES` + README 节点参考）
- **H3 Face Track + Crop**
  - `crop_factor` 默认 2.5（范围 1.2–8.0）。tooltip 原文：“2.5 puts the face at ~40% of the crop … 2.0-3.0 is the useful range.”
  - `canvas_width/height` 默认 768；`canvas_mode` 默认 **manual**，可选 `auto_no_downscale` 和 `auto_capped_768`。两种 auto 模式最小 512：“Both auto modes clamp UP to a minimum of 512x512”。
  - 其余默认：`smooth_window` 21，`size_smooth_window` 51，`identity_threshold` 0.28，`select` largest_face，`fallback_head_frac` 0.5，`absent_shots` off。
  - 输出 `frame_count`、`canvas_w/h`，直接接到 H3 节点上。
- **H3 Per-Frame Denoise**：`denoise_multiplier_small_face` 1.0，`denoise_multiplier_large_face` 0.35，`face_px_small` 30，`face_px_large` 120，`smooth_frames` 9。它**必须串在 MODEL 路径上**。README 原文：“Route the unpatched model straight past it and the mask still applies but the held frames come back nearly clean … with no error to tell you.”
- **H3 Face Stitch Back**：`paste_region` face_only，`mask_dilation` 16，`feather` 6（README：“Use ~24 with a rect mask, 4-8 with SAM”），`colour_match` 1.0（“Match the crop's per-channel mean/std to the region it replaces”），`blend` 1.0，`undetected_frames` fade_out。
- **H3 Face Mask (SAM)**：threshold 0.93。README 自己也说常常不值得用：“**Is it worth it?** Often not. A rect mask frequently beats SAM here.”
- **denoise 与 shift 的换算**（README）：`sigma = shift * t / (1 + (shift - 1) * t)`，“At the default shift of 12, `0.25` … lands at an effective sigma of **0.800** and rewrites the frame.”
  - 我的推算（低）：如果在 shift 6 下跑，denoise 0.4 → σ≈0.80；在 shift 12 下，denoise 0.4 → σ≈0.89。所以接入时必须先定 refine 这一遍用哪个 shift，模板默认是 12。

### 1.4 身份从哪里来（高）
有两条完全独立的通道，旧报告把它们混在一起了：
1. **选人和跟踪**：`identity_model` = insightface `buffalo_l`、clip_vision 或 ccip，只决定“跟哪张脸”，不参与生成。README 原文：“`identity_reference` … A picture of the person to refine. Each shot picks the face matching it”。
2. **生成**：`MiniMaxH3ReferenceToVideo` 的 ref 图（README 原文：“`Ref 1` is the identity; `Ref 2` is optional, for wardrobe or a second look”）加上原脸裁切本身（img2img，denoise 0.4）。

注意：官方 FL2VA 权重的 task 只有 `t2va`/`fl2va`。模板在 FL2VA 权重上接 ReferenceToVideo，属于训练外用法；实际起作用的大概主要是原脸 latent（推断，低）。

### 1.5 音频直通（高）
- 模板的 lipsync 路径依赖第三方节点 `MiniMaxH3NativeAudioLock`（来自 Shrek3OnVH5/MiniMax-H3-NativeAudio-MusicVideo-Workflow）。README 原文：“sets `noise_mask` to ones for video and zeros for audio so only video denoises, and the video branch cross-attends to that fixed audio.”
- 原声单独接到保存节点：“The **original** audio goes separately into the save node.”
- 作者在 #19 的回复：没有 AudioLock 时，Per-Frame Denoise 也会把音频那一半锁住（“the node also writes a full lock over the audio half of the latent”）。

### 1.6 依赖和坑（高 / 中）
- `requirements.txt`：ultralytics、scipy、insightface、scenedetect>=0.7。dghs-imgutils 故意不列，原文：“it pins numpy<2 and pulls opencv-contrib-python, which shadows the OpenCV build ComfyUI ships”。
- onnxruntime：README 警告不要同时装 `onnxruntime` 和 `onnxruntime-gpu`，否则 “`CUDAExecutionProvider` disappears, and identity matching” 会静默跑在 CPU 上。PR #13（caoddgao，未合并）专门加了这个警告。
- PyTorch 2.6+ 下旧版 ultralytics 加载 YOLO .pt 会失败（#18，作者回复“Updating ultralytics should be all it takes”）。
- 模板还要 ComfyUI-VideoHelperSuite、ComfyUI-Impact-Pack（README：“the templates' detector values use the model-folder naming its subpack registers”）、NativeAudioLock。
- 帧数会补齐到 17k+5。我们的 243 帧正好在网格上（243 = 17×14+5），不会多算。

### 1.7 显存和耗时（中，1 位用户实测）
PR #13 里 caoddgao 用 16 GB RTX 4070 Ti SUPER、同一段 **243 帧**素材测的：

| 画布 | 显存峰值 | 采样耗时 |
|---|---|---|
| 512×512 | ~13550 MB | 80.9 s |
| 768×768 | ~13550 MB | 173.7 s |
| 1024×1024 | ~13550 MB | 339.3 s |

- 原文：“画布面积涨到 4 倍，耗时涨到 4.2 倍（几乎与面积严格成正比），额外显存占用为零。”
- 原因：权重共 38 GB，分段暂存（dynamic VRAM loading），所以显存峰值反映的是卡的容量，不是工作量。
- 人脸检测：243 帧从 11.20 s 降到 7.72 s（批处理 PR）。
- 3090 上的耗时：没有人报告。按 4070 Ti S 的数推，768 画布、8 步、每镜每张脸约 3–5 分钟，另加 VAE 编解码（推断，低）。

### 1.8 已知失败模式（按 issue）
| 问题 | 来源 | 状态 | 置信度 |
|---|---|---|---|
| **大脸几乎不变**：脸高 198–207 px 时，scheduler denoise 设成 0.4、0.65、1.0，输出都一样（ROI 平均差 1.61） | #19 lexyaowork（环境和我们几乎一样：fl2va int8 + turbo 8step v1.0） | 作者解释这是设计行为：超过 120 px 时倍率是 0.35，“Expect to go well above 0.35 before large faces visibly move”，并建议把 `face_px_large` 提到 400 | 高（作者确认） |
| 硬切以后框跟错位置 | #1 | v1.1.0 加了 PySceneDetect 修复 | 高 |
| 主体转身后跟到别人身上 | #14（designloves2，作者确认） | v1.1.2 修复，用户复测通过 | 高 |
| 片尾出现纯噪声（帧数不在 17k+5 网格上） | #11 | 已关闭 | 中 |
| “Small face not modified” | #4 | 用户没有回复，已关闭 | 低 |
| 一次只能处理一个主体（多人要跑多遍）；SAM 边缘容易露馅；整段视频只定一次画布尺寸（远景近景混剪时按近景定） | README Limitations | — | 高 |

**对我们的含义（推断，中）**：768×1344 下，中景及以上的脸高大多超过 120 px，模板默认只改约 1/3。FaceRefine 真正帮得上忙的是远景、小脸镜头。近景要改，就得把大脸倍率提到 0.6–1.0，这时又会碰到 README 说的“head drifts relative to the body”。

### 1.9 社区评价（按独立用户计数）
- 正面：Edw1nd（Singularity HF #3）原文：“The effect was okay.” 他还建议：“I recommend first using latent upscale to enlarge the video, and then using this one.”（1 人，低）
- 能跑通的实际使用：lexyaowork（#19）、designloves2（#14）、golfingelk-collab（#11）、caoddgao（#13）。共 4 人有完整日志，但都没有给出质量对比。
- Reddit 有 5 个相关帖子（“Testing ComfyUI-H3-FaceRefine node”、“OK this is cool, Minimax H3 Face detailer!”、“Anyone use MMH3 FaceDetailer?”、“Help Fixing the H3 Face Detailer”、“Face detailer or deroping to fix faces in MM H3?”，链接见 trendshift.io/repositories/146054），**正文都没读到**。

### 1.10 和另外两个方案对比
| | Carasibana FaceRefine | ryukbk/ComfyUI-VideoFaceDetailer | T8 Face Refine（comfyui-minimax-h3-audio-T8） |
|---|---|---|---|
| 成熟度 | 554 星，16 个 issue，作者回复快 | 1 星；作者原话：“functional and unit-tested, but not yet widely battle-tested in the wild.” | 1.2k 星（整个节点包）；README 首页**没有提到** face refine；RunComfy 页面标的是 Advanced/Experimental |
| 原理 | 逐帧跟踪 + 重绘 + 只贴脸框 | 只处理脸小于门限的帧（area 0.1–0.5%），目标尺寸 768，padding 1.5，EMA 平滑，冻结尺寸 | 分镜感知的裁切计划、parity stitch、per-frame denoise、最多 3 张脸合成 |
| 默认颜色匹配 | 1.0 | 0.0 | 有 colour_match（默认值没看到） |
| 许可 | MIT | AGPL-3.0 | GPL-3.0+ |
| 结论 | 首选 | 备选；它的“按门限只处理小脸帧”正好对口远景 | 资料不足，暂不考虑 |

### 1.11 链路位置、文件、风险、实验
- **链路位置**：后期。H3 出片后，对选中的镜头再跑一遍（又是一次 H3 采样）。
- **需要的文件**
  - 自定义节点：ComfyUI-H3-FaceRefine、ComfyUI-H3-NativeAudioLock、ComfyUI-Impact-Pack（加 Subpack）、ComfyUI-VideoHelperSuite。gpu3 一个都没有。
  - 模型：`face_yolov8m.pt`（Bingsu/adetailer，约 52 MB）；`person_yolov8m-seg.pt`（约 55 MB，可选）；insightface `buffalo_l`（首次使用自动下载，约 280 MB，可选）。大小是常见值，没有逐个核对（低）。
  - pip：ultralytics、scipy、insightface、scenedetect、onnxruntime-gpu（只装 GPU 版）。
  - H3 权重：gpu3 已有（fl2va int8、ref2va int8、两种 turbo）。
- **风险**
  - 默认参数对大脸基本不起作用。
  - 改动太大时脸和身体错位、边缘露馅。
  - 装 insightface/onnxruntime 可能弄坏 gpu3 的 ComfyUI 环境（numpy/opencv 冲突），建议用独立的 venv 或独立的 ComfyUI 实例。
  - turbo v1.1 配 refine 这一遍没有任何人测过。
  - 每镜增加约 3–5 分钟（推断）。
- **建议实验**：取 ep01 三个已知坏镜头（远景小脸、中景走动、近景快速转头），同种子，项目方盲选。

| 组 | 设置 |
|---|---|
| A | 原片 |
| B | 模板原样：fl2va int8 + fl2v turbo 8step v1.1，shift 12，8 步 euler，denoise 0.40，crop 2.5，auto_capped_768，rect feather 24，colour_match 1，Ref1 = 林晚母版 |
| C | 同 B，但 shift 6/3（和主链一致） |
| D | 同 B，大脸倍率 0.7、`face_px_large` 400 |
| E | 同 B，但 refine 这一遍换成 `minimax_h3_ref2va_pruned_int8_convrot` + ref2v turbo 8step v1.1（让参考图走训练过的通道） |

指标：
- SFace/ArcFace 与林晚母版的相似度（每 0.5 s 取一帧）；
- 脸部 ROI 相邻帧平均差（衡量闪烁）；
- 贴边处目检；
- 口型同步目检；
- 每镜耗时。

---

## 2. Singularity V2

来源：
- <https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity>（卡片、文件树 API、讨论 #1–#42，读了其中 14 个）
- <https://huggingface.co/WAS/Minimax-h3_Singularity_v2_pruned>（卡片、文件树、讨论 #1）
- <https://comfyui-wiki.com/en/news/2026-10-22-h3-singularity-v2>

### 2.1 它是什么（高）
- 卡片原文：“a comprehensive fine-tuned fusion model designed to enhance the capabilities of **MiniMax-H3**”，由 “`ref`, `fl`, and `b25-49`” 等检查点融合而成，之后再微调。
- **所有文件名都是 `ref2va`**，推荐的加速 LoRA 是 `minimax_h3_ref2v_turbo_4step_v0.1`。comfyui-wiki 写的是支持 T2V / I2V / R2V / V2V，**没有任何地方声称支持 FL2V 首尾帧**。
- 结论：它是 Ref2VA 系，首尾帧锁定只能靠 AddGuide（见 §3），没有官方说明，也没有社区实测。

### 2.2 文件（高，HF tree API，2026-10-31）
| 仓库 | 文件 | 大小 |
|---|---|---|
| WarmBloodAban | `Minimax-h3_Singularity_ref2va_v2_pruned_int8.safetensors` | 20.97 GB |
| WarmBloodAban | `Minimax-h3_Singularity_ref2va_v2_int8.safetensors` | 34.0 GB |
| WarmBloodAban | `Minimax-h3_Singularity_ref2va_v2_bf16.safetensors` | 66.28 GB |
| WarmBloodAban | `..._ref2va_Pruned_v1.3_int8` / `..._v1.3_Pruned_w4a8` / `..._v1.3_int8` | 20.97 / 11.77 / 34.0 GB |
| WAS | `Minimax-h3_Singularity_ref2va_v2_pruned_int8_convrot_r2.safetensors` | 20.97 GB |
| WAS | `..._v2_pruned_w6a8_r2` / `..._v2_pruned_w4a8` | 15.98 / 11.77 GB |

3090 上只考虑 int8 convrot（w4a8 有 LoRA adaln 静默失效的问题，见 h3_deep/03 #16420）。

### 2.3 推荐设置（高 / 低）
- 作者卡片只给出 LoRA：`minimax_h3_ref2v_turbo_4step_v0.1`（“Enables 4-step fast inference”）。#7 里作者原话：“I think a balanced scheduler works better, like simple.” #1 里建议 4 步 LoRA 用 0.75–1.0。
- V2 卡片：提示词 “approximately **5,000 characters**”。风格词（来自 comfyui-wiki）：`photorealistic, natural lighting, realistic textures`。
- WAS 的测试设置（不是推荐值）：1344×768，124 帧，euler/simple 6 步，DMAD 4-step LoRA 0.7，int8 convrot 视频 VAE。
- 注意：gpu3 上的 ref2v turbo 是 4step v1.0 和 8step v1.1，**没有** v0.1。

### 2.4 WAS 的 PSNR 表（高，原样）
四个种子，相对 bf16 的平均 PSNR（dB）：

| 文件 | 42 | 43 | 44 | 45 | 平均 |
|---|---|---|---|---|---|
| int8 convrot r2 | 23.3 | 24.9 | 28.2 | 28.0 | **26.1** |
| w6a8 r2 | 23.5 | 24.2 | 24.3 | 25.8 | 24.4 |
| w4a8 | 21.9 | 21.1 | 21.7 | 21.4 | 21.5 |

r2 把 int8 权重误差从 1.30–1.48% 降到 0.87–1.10%。这张表只说明量化损失，不说明画质好不好。

### 2.5 社区反馈（按独立用户计数）
| 观点 | 人数 | 代表原文 | 置信度 |
|---|---|---|---|
| **V2 参考图保持比 V1.3 差**（身份变“generic”、换了参考图还出旧人物、双人重复） | 6（anitman, neophoeus, agentcoulson, povgeek37, bad2928, MyNameIsDillon / starckyx） | povgeek37 #32：“V2 basically destroys identity preservation from reference images… It's a real step backwards for Ref2va.” | 中 |
| 规避办法：提示词里删掉人种和外貌属性，只写图上看得见的东西 | 2（agentcoulson, EllipsesMark） | “v2 will try to adhere more towards your prompt description than your reference” | 低-中 |
| V2 皮肤和头发更自然，近景好 | 3（anitman, hieulebui, agentcoulson） | anitman：“in specific scenarios, such as face close-ups, V2 may well be better, since it stays closer to the original skin texture.” | 中 |
| V2 画面蒙一层模糊、比例被压扁 | 3（anitman, neophoeus, kakaxi #37） | “there's a layer of blur over the image” | 中 |
| **偏灰、降饱和**（V1.x 起就有） | 2 人加作者本人承认 | 作者 #18：“the model lowers video saturation to avoid oversaturation”；Emplares 实测：写实远景饱和度 −45%，20 步 −27% | 中-高 |
| 首帧不贴：用 I2VA 首帧对齐句，V2 不从首帧开始 | 1（ktgff #32）；V1 时期 mystifying #1 也说 “ref image got transformed before animation even begun”，作者解释是 “more aggressive noise diffusion strategy in the early inference stages” | 中 |
| 中远景脸更好（作者自称），但特效变糊 | ManyOtherFunctions #7：“it technically DOES refine distance faces a little better” | 低 |

Emplares（#23）做过同种子 A/B，对比的是 V1.3 和官方 FL2VA bf16：turbo 下 “Faces/skin: clearly nicer on Singularity … At 20 steps the two were about even”。

### 2.6 链路位置、文件、风险、实验
- **链路位置**：H3（换底模）。只适合作为 Ref2VA 身份通道（X4）里的候选，**不能替换 FL2VA 主线**。
- **需要的文件**：`Minimax-h3_Singularity_ref2va_v2_pruned_int8_convrot_r2.safetensors`（WAS，20.97 GB）或 WarmBloodAban 的 pruned int8（20.97 GB），**gpu3 都没有**。另外最好有 `minimax_h3_ref2v_turbo_4step_v0.1`（没有）。PRISM 的 UPD1（beta7×SingV2）在 gpu3 上只是不完整的 .part 文件。
- **风险**
  - 首帧锁定弱（Ref2VA 本身的问题，加上作者承认前几步扩散很激进）；
  - V2 身份保持倒退（6 人）；
  - 偏灰，和项目方“色彩更丰富”的要求正好相反；
  - 要下载 21 GB（花钱/占盘，需项目方点头）。
- **建议实验**：先跑 §3 的 F 组（官方 ref2va，gpu3 已有），**F 组赢了**再考虑下载 Singularity。

| 组 | 设置 |
|---|---|
| F | 官方 ref2va int8 + ref2v turbo 8step v1.1 + AddGuide 首/尾帧 + 林晚角色卡 |
| S | 同 F，只把底模换成 Singularity V2 pruned int8 r2 |

指标：
- 第 0 帧 PSNR（对首帧）和最后一帧 PSNR（对尾帧）；
- ArcFace 曲线；
- 相对首帧的平均饱和度差；
- 项目方盲选（质感、色彩）。

---

## 3. Combined Image+Reference 节点、核心 AddGuide、官方 multiframe 模板

来源：
- <https://github.com/entropicnoise/MiniMax-H3-Combined-Image-And-Reference-to-Video>（README，源码 `minimax_h3_combined_image_and_reference.py` 920 行，8 星，最后推送 2026-09-08，0 个 issue）
- comfy.icu 节点页
- Comfy-Org/ComfyUI master：`comfy_extras/nodes_minimax_h3.py`、`comfy/ldm/minimax/model.py`（PackedLayout）、`comfy/model_base.py`（MiniMaxH3.extra_conds）、`comfy/text_encoders/minimax.py`
- <https://docs.comfy.org/tutorials/video/minimax/minimax-h3-multiframe>

### 3.1 Combined 节点做了什么（高，源码）
- docstring 原文：“Union of MiniMaxH3ImageToVideo (fl2va keyframes) and MiniMaxH3ReferenceToVideo (ref2va references) inputs, in one node.”
- `first_frame` → `resolved_frame_index 0`（拉伸到画布）；`middle_frame` → `frame_count // 2`；`last_frame` → `frame_count - 1`（cover 裁切）。这些都写进 `minimax_keyframes`。
- `ref_images` 最多 10 张，另有 ref_videos 4 个、ref_audios 4 个，写进 `minimax_refs`。
- **没有 strength 参数，也不检查底模类型。**
- 节点里的两个 monkey-patch 只在旧版 ComfyUI 上启用。源码原文：“native v0.34+ keyframe/reference merge detected”。我们的 ComfyUI 0.42.0 不需要这些补丁。

### 3.2 核心 ComfyUI 原生就支持“关键帧 + 参考图”（高，源码）
- `model_base.MiniMaxH3.extra_conds` 会同时读 `minimax_keyframes` 和 `minimax_refs`，顺序是 “condition latents in packed-layout order: keyframes, then references”。
- `PackedLayout.__init__(…, keyframes=None, refs=None)`：refs 排在文本和目标之间，关键帧按 `cursor + FRAME_RESCALE * resolved_frame_index` 放到目标时间轴上（注释原文：“fl2va: keyframe cond rows right after text”）。
- 所以 **ReferenceToVideo → AddGuide(frame 0) → AddGuide(frame -1)** 和 Combined 节点在 DiT 里是同一种东西。
- 两者的差别只在 Combined 节点额外支持 middle_frame 和几种尺寸模式。核心的 AddGuide 本来就能放任意帧，还能放短片段、音频。

### 3.3 关键坑：接了参考图，首尾帧就进不了文本编码器（高，源码）
`comfy/text_encoders/minimax.py` 的 `tokenize_with_weights` 是 if/else 结构：
```
if minimax_ref_items:   # 只给 ref 编号 <Picture i>
    ...
else:
    for i, img in enumerate(images):   # 只有没有 ref 时，首尾帧才成为 <Picture 1>/<Picture 2>
```
- Combined 节点调用的是 `clip.tokenize(prompt, images=images, minimax_ref_items=ref_items)`。**只要接了任何 ref，首尾帧就不会被 Qwen 看到**，提示词里的 `<Picture 1>` 指的是第一张 ref。
- 官方模板也写了同样的话：“Pictures connected only to Add Guide nodes pin compositions at specific frames but are not visible to the text encoder.” 并建议把它们也插进 `ref_images` 槽位。
- 所以做 X4 时，首帧要同时接 AddGuide(0) 和 `ref_image_1`。官方原文：“`<Picture 1>` is both the identity lock and the first frame of the video”。

### 3.4 官方 multiframe 模板（高）
- 底模 `minimax_h3_ref2va_pruned_int8_convrot`；文本编码器 nvfp4 awq；视频 VAE int8 convrot；音频 VAE fp32；可选 `minimax_h3_ref2v_turbo_4step_v0.1`（Lightning 开关，原文：“slightly lower audio and motion quality”）。
- AddGuide 串联；`frame_idx = round(seconds*24)`；负数表示从片尾往前数。
- 约束原文：“The index plus the guide length must stay inside the generated duration.”
- 提示词按 full-reference 六段式写（见 §6）。
- 文档没有写 sampler、shift、步数。

### 3.5 AddGuide 的细节（高，源码）
- 没有 strength 参数。
- 单张图按 `"center"` 方式缩放。注意：ImageToVideo 的首帧用的是 `"disabled"` 直接拉伸，两者不同，首帧比例不一致时会被裁。
- 不少于 5 帧的批次按片段处理，并截到 17k+5 帧。
- 可以附带音频，用 audio_vae 编码。

### 3.6 需要什么底模
- 节点不限制。官方权重：FL2VA 的 `"tasks": ["t2va","fl2va"]`，Ref2VA 的 `"tasks": ["ref2va"]`（h3_deep/01_official.md，高）。所以“关键帧 + 参考图”只有在 Ref2VA 权重上才都算训练内用法：Ref2VA 指南明确把 `<Picture N>` 当首帧/关键帧（“keyframe completion”）。
- FL2VA 权重接 ref：属于训练外用法。FaceRefine 模板、kimi 提到的 hybrid 都这么用，但都没有对照数据（低）。

### 3.7 社区结果
- Combined 节点：**一份用户实测也没找到**（8 星，0 issue，搜索也没有）。
- Ref2VA + AddGuide 首尾帧：
  - h3_deep 已记录：HF #54 有 1 人在用；januscaler PR #10 有 1 人测得 33.3 dB / SSIM 0.993；joeygambino 测关键帧保真度 FL2VA 26.35 dB 对 Ref2VA 16.15 dB（原文：“fl2va lands on a supplied frame, ref2va only nudges”）。
  - 结论互相矛盾，需要我们自己做 A/B（低-中）。

### 3.8 链路位置、文件、风险、实验
- **链路位置**：H3。
- **需要的文件**：官方模板的东西 gpu3 都有（`minimax_h3_ref2va_pruned_int8_convrot`，ref2v_turbo 4step v1.0 / 8step v1.1）。Combined 节点不需要装。只有想要“中间帧 + 尺寸模式”时才装，它是单个 py 文件，没有 pip 依赖。
- **风险**
  - Ref2VA 首帧贴合弱；
  - 首尾帧对 Qwen 不可见，提示词编号写错就会对不上；
  - 9:16 上半部重影（1 人）；
  - Ref2V turbo 动作发僵（多人）；
  - 引导帧太密会冻脸（1 人）。
- **建议实验**（同种子、同首尾帧，ep01 近景脸、中景动作、暗场各一镜）

| 组 | 设置 |
|---|---|
| A | 现状 FL2VA |
| F1 | ref2va int8 + ReferenceToVideo（ref1 = 首帧，ref2 = 林晚角色卡）+ AddGuide(首帧, 0) + AddGuide(尾帧, -1)，ref2v turbo 8step v1.1 |
| F2 | 同 F1，不挂 turbo，20–25 步（质量上限） |
| F3 | FL2VA int8 + 现 turbo + ReferenceToVideo(ref1 = 林晚角色卡) + AddGuide 首尾帧（检验 FL2VA 能不能吃参考图） |

指标：第 0 帧 / 最后一帧 PSNR，ArcFace 曲线，上半部重影目检，项目方盲选动作自然度。

---

## 4. HF MiniMaxAI/MiniMax-H3 讨论 #47

来源：
- <https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/47>（HF API 读取）
- 官方 <https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md>（15773 字节）

### 4.1 #47 的真实情况（高）
- 标题：“The actual correct system prompt for IT2V - (Took me a while)”。发帖人 **cushycrux（isOwner False，普通用户）**，2026-08-04。之后只有一条回复（shadow-key：“just tested it and it works perfect”，用于 LM Studio）。
- 帖子内容是一份 I2VA 系统提示词，其中对齐句原文：
  `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.`
- **这句和官方 `base_en.md` §2.1 “I2VA always uses:” 逐字一致**，所以句子是官方的，帖子不是。

### 4.2 和 FL2VA 对齐句的区别（高，官方 base_en.md）
| 模式 | 官方第一行 | 含义 |
|---|---|---|
| I2VA（只有首帧） | `For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.` | 首帧锚定，之后“develop forward” |
| FL2VA（首 + 尾） | `How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.` | 两端都对齐，中间“progressively narrowing differences” |
| L2VA（只有尾帧） | `How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.` | 收敛到尾帧 |

- 写法细节：I2VA 句里有尖括号 `<Picture 1>` 和方括号 `[Shot 1]`；FL2VA 句里是 `Picture 1 (from Shot 1)`，**不带括号**（官方原样）。我们 h3_prompt_and_fl2v.md 的模板和官方一致，不需要改。
- 官方要求：“The instruction must be the first line of the final prompt, followed by one blank line before the core fields.”
- I2VA 的推荐结构：“first-frame anchor → action onset → continuous development → result or reaction”。
- 社区补充（低）：Singularity #32 里 ktgff 把 I2VA 句用在 Ref2VA 模型上，结果不从首帧开始；agentcoulson 回复：“try formatting your prompt as a Ref2VA instead of FL2VA”。也就是说，Ref2VA 模型要用 §6 的六段式，不能用 I2VA 句。

### 4.3 链路位置、文件、风险、实验
- **链路位置**：H3 提示词（写作系统的模板层）。
- **需要的文件**：无。
- **风险**：只有首帧的镜头如果套了 FL2VA 双图句，会写出 `Picture 2` 却没有尾帧，属于模板错配（推断）。
- **建议实验**（低优先级）：对只有首帧的镜头比较两组，项目方盲选，指标是第 0 帧 PSNR 和动作是否按剧本走。
  - I1：用 I2VA 句；
  - I2：错用 FL2VA 句。

---

## 5. iamkaikai/MiniMax-H3-Single-Frame-VAE-500K

来源：<https://huggingface.co/iamkaikai/MiniMax-H3-Single-Frame-VAE-500K>

- 它是什么（高）：**只有解码器**的实验检查点，基于 Mamad8/MiniMax-H3-Image-VAE 微调。卡片原文：“does not include an encoder or transformer, and it is not used in production”。训练数据是 50 万张图像重建样本（47.5 万来自 pd12m，另有 2.5 万张图表、文档类难例），在 256–1024 px 上训练，共 62,500 次更新。
- 适用范围原文：“Do **not** treat it as a replacement decoder for MiniMax H3 video”，“Full video decoding is unsupported.”
- 指标（288 个留出样本）：

| 解码器 | PSNR | SSIM | LPIPS ↓ |
|---|---|---|---|
| 官方 H3 VAE | 30.35 | 0.9258 | 0.0323 |
| 本检查点 | 31.12 | 0.9208 | 0.0454 |

  卡片原文：“the official H3 decoder remains better on SSIM, LPIPS, DISTS, and Edge F1”，而且在自然照片上最弱（“weakest on natural photographs”）。
- 文件：`minimax_h3_single_frame_decoder_500k.safetensors`，约 9 GB，只能用 diffusers 加 `load_decoder.py`，卡片没有提到 ComfyUI。
- **和我们的关系**：没有。它不碰编码器，所以和首帧编码无关；它只解单帧，所以和视频质感也无关，而且在照片质感上比官方差。
- 链路位置：不进链路。需要的文件：无。风险：无（不采用）。实验：不做。

---

## 6. 官方 VIDEO_PROMPT_WRITING_GUIDE_ref_en.md（Ref2VA 提示词规则）

来源：<https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md>（23553 字节，全文读完）

### 6.1 关键规则（高，均为原文）
1. **六段，按顺序**：`subject_definitions` → `summary` → `retention_analysis` → `detailed_description` → `overall_soundscape` → `non_diegetic_music`。全部用英文；`<d>` 里的台词保留原语言。
2. **四种标签**：`<Subject N>`（可复用的可见内容，比如人、场景、服装）、`<Picture N>`（“a concrete target frame or shot-planning anchor”）、`<Video N>`、`<Audio N>`。标签一旦定义，全文含义不变。
3. **身份图不单独列 Picture**。原文：“If an image is used only to define a character, scene, costume, or style, do not create a standalone picture entry. Instead, cite the image source inside the corresponding `<Subject N>` definition.” 例句：`<Subject 1> is the young woman in <Picture 1>, with long dark hair, a blue cardigan, and a thin silver necklace.`
4. **首帧图要单独列**：`<Picture 2> is the first frame of [Shot 1], showing …`。正文里自然地写：“the shot begins from <Picture 1>”、“the shot ends on <Picture 3>”。
5. **summary 要带任务类型前缀**。首尾帧锁定属于 `keyframe completion`，身份参考属于 `reference generation`，两者合在一起写成 `[keyframe completion + reference generation]`。
6. **retention_analysis** 用固定标记：`fully_preserved` / `partially_preserved` / `attribute_transfer` / `weak_reference`；音频用 `fully_copy` / `partially_copy` / `reference` / `weak_reference`。这一段不写 `(Sx)`。
7. **detailed_description**：在 `[Shot 1]` 之前先用一两句英文交代风格；生成任务“normally 350-500 English words”；第一次出现主体时写清它的参考特征、在画面中的位置和动作；说话时写 `<Subject N> (Sx)`。
8. 镜头、运镜、`<d>`、`[Shot N] At MM:SS.mmm` 这些格式沿用 base 指南。

### 6.2 和社区经验的冲突（记录，不裁决）
- 官方要求第一次出现时“describe its referenced characteristics”。
- Singularity V2 用户（2 人）说提示词里写人种或外貌会把参考图“拉向”泛化的样子，建议只写图上看得见的特征，不写人种。这只针对微调模型，在官方 Ref2VA 上没有验证（低）。

### 6.3 链路位置、文件、风险、实验
- **链路位置**：H3 提示词。只在 X4（Ref2VA 身份通道）里用。按项目分工，内容由 Qwen 写，系统侧只需要提供六段式模板和格式校验。
- **需要的文件**：无。
- **风险**
  - 六段式比 FL2VA 三段式长很多（350–500 词），写作系统要新增模板；
  - `<Picture N>` 的编号必须和 ref 槽位顺序一致（§3.3），否则身份图和首帧会对调。
- **建议实验**：在 §3 的 F1 组里比较两种提示词写法，指标是 ArcFace 加项目方盲选。
  - P1：官方六段式；
  - P2：FL2VA 三段式硬套。

---

## 7. 没找到 / 没读到
- Reddit 上 5 个 FaceRefine 帖子和 Singularity V2 的 Reddit 讨论：被 Reddit 屏蔽，只有标题（来自 trendshift.io）。
- FaceRefine 在 3090 上的耗时：没人报告。在 FL2V turbo **v1.1** 上用 FaceRefine：没人报告。FaceRefine 前后的身份相似度量化：没人做过。
- FaceRefine 的 Releases 页是空的，版本信息只来自 README 和 pyproject。GitHub Discussions 只看到标题。
- Combined 节点：没有任何用户实测，也没有 issue。
- Singularity V2 上做首尾帧（AddGuide）：没有报告。WAS pruned r2 的画质评价：没有（只有 PSNR）。`ref2v_turbo_4step_v0.1` 为什么比新版更适合：作者没回答（#7 g2t2 问过）。
- T8 Face Refine：README 首页没提到，没读源码（节点包有 163 个以上的节点，版本 1.104.0），只有 RunComfy 的自动生成页。
- comfyui-wiki 2026-09-07 Singularity V1 文章：没读（V2 文章已经覆盖）。
- note.com 和 civarchive 上关于这六项的帖子：没搜到。

## 8. 来源清单
- FaceRefine
  - <https://github.com/Carasibana/ComfyUI-H3-FaceRefine>
  - raw `nodes.py`、`README.md`、`requirements.txt`、`pyproject.toml`、`example_workflows/H3_Face_Refine_Auto_Select.json`
  - issues API #1 #2 #4 #6 #9 #11 #13 #14 #18 #19
  - <https://github.com/Carasibana/ComfyUI-H3-FaceRefine/discussions>
  - <https://trendshift.io/repositories/146054>
- 对比方案：<https://github.com/ryukbk/ComfyUI-VideoFaceDetailer>；<https://github.com/T8mars/comfyui-minimax-h3-audio-T8>
- Singularity
  - <https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity>（讨论 #1 #3 #7 #11 #13 #14 #18 #23 #31 #32 #34 #37 #40 #41）
  - <https://huggingface.co/WAS/Minimax-h3_Singularity_v2_pruned>
  - <https://comfyui-wiki.com/en/news/2026-10-22-h3-singularity-v2>
- Combined 节点 / 核心 ComfyUI
  - <https://github.com/entropicnoise/MiniMax-H3-Combined-Image-And-Reference-to-Video>
  - <https://comfy.icu/node/MiniMaxH3CombinedImageAndReferenceToVideo>
  - Comfy-Org/ComfyUI master：`comfy_extras/nodes_minimax_h3.py`、`comfy/ldm/minimax/model.py`、`comfy/model_base.py`、`comfy/text_encoders/minimax.py`
  - <https://docs.comfy.org/tutorials/video/minimax/minimax-h3-multiframe>
- 提示词：<https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/47>；HF `docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md`、`docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`
- 单帧 VAE：<https://huggingface.co/iamkaikai/MiniMax-H3-Single-Frame-VAE-500K>
