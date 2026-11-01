# IMGLAB-03｜ComfyUI 自动修手、修脸方案研究（主模型 Qwen-Image 2.1 Turbo，RTX 3090 24GB）

> 研究日期：2026-11-02。方法：逐条读官方 README、源码、issue、HF 模型卡和社区帖。每条都附英文原文、链接和置信度（高/中/低）。查不到的写“未查到”。
> 范围：只做研究，不下载、不改代码。所有参数都只是“起点”，必须在本机按 GEN_CONTRACT 做 A/B 后才能进链路。

---

## 0. 摘要（10 条）

1. **Impact Pack 的 Detailer 与模型无关，接 Qwen-Image 2.1 可以用，但有坑。** `enhance_detail` 走通用的 `impact_sampling.ksampler_wrapper`，源码里没有任何 qwen 分支。社区已在“standard Qwen 2.1 workflow”里接 DetailerDebug(SEGS)，碰到的 `'Tensor' object has no attribute 'copy'` 已在 2026-10-31 由 PR #1243 修好。视频 VAE 的 5D 张量崩溃在 v8.21.2 修好。必须用 **≥ 2026-10-31 的 Main**。（中高）
2. **默认参数不能照搬到 Turbo。** FaceDetailer 默认 `cfg 8.0 / steps 20 / denoise 0.5`。Qwen-Image 2.1 Turbo 官方是“8 denoising steps”“CFG=1 by default”，而且 schedule 写在 checkpoint 里，“other schedules are untested”。detailer 里要改成 cfg 1、steps 8，denoise 从 0.30–0.40 起步。Turbo 在部分去噪下表现如何，**官方和社区都没有数据**，必须本机 A/B。（中）
3. **修脸防贴片感，四个开关最关键**：①`feather`（贴回边缘的高斯羽化，默认 5）；②`noise_mask_feather`（默认 20，会自动套 Differential Diffusion）；③denoise ≤ 0.4（社区说法：0.4 能保住身份，超过 0.6 就是换了一张脸）；④贴回后做色彩匹配（KJNodes ColorMatch，或 VNCCS 那类 Reinhard + Poisson）。作者自己提醒 noise_mask_feather 有时“may create artifacts along the edges”。（中）
4. **修手没有现成的 DiT 版 HandRefiner。** HandRefiner 和 MeshGraphormer 预处理器配套的 ControlNet `control_sd15_inpaint_depth_hand_fp16` 只能用在 SD1.5 上。Qwen 这边能用的组合是：MeshGraphormer 出手部深度图和 mask → **Qwen-Image 2.1 Fun ControlNet Union**（支持 Depth 和 inpaint，2026-09-28 已并入 ComfyUI core）。这个组合**没有找到任何人实测过**。（低）
5. **最稳的修手主路是 Crop & Stitch。** 用 hand_yolov9c 检测 + SAM 精 mask → 按 crop_factor 放大重绘 → 羽化贴回，Impact 的 DetailerForEach 本身就是“Crop-n-Stitch algorithm”。0.3–0.45 的低去噪只能修“轻度畸形、糊、指甲细节”。多一根手指、手指粘连这类拓扑错误，要么高去噪（0.6–0.8）配深度控制，要么整张重抽。（中）
6. **手部畸形自动闸门不能单靠 MediaPipe。** 2026 年的论文实测：MediaPipe 在合成图上检出率只有 0.314（真实图 0.414）；对检出的手，“anatomical-pass”还高达 0.997，说明它会把坏手也拟合成 21 个正常点。可以做“YOLO 看到手、MediaPipe 拟合不上，或 presence 低”的**可疑标记**，最后交本地看图模型复核。HADM 是现成的人体伪影检测器，但 AP50 只有 43.3、不写许可证，还要求 PyTorch 1.12 老环境，不建议进主链。（中）
7. **修完脸必须过身份闸门**：直接复用项目里已有的 `tools/identity/id_gate.py`（buffalo_l ArcFace），对 detailer 前后各打一次分，分数下降或跌破线就回退到原图。注意 insightface 预训练权重写的是“non-commercial research purposes only”。（高）
8. **许可证**：Impact Pack 是 GPL-3.0；Impact Subpack 是 AGPL-3.0；Bingsu/adetailer 权重卡标 Apache-2.0，但 Ultralytics 的立场是“trained models fall under AGPL-3.0”，有争议。comfyui_controlnet_aux 是 Apache-2.0；HandRefiner 代码是 MIT；MeshGraphormer 代码 MIT，但 MANO 是“non-commercial scientific research”。MediaPipe Apache-2.0；SAM Apache-2.0；Inpaint-CropAndStitch GPL-3.0；Qwen-Image 2.1 Turbo 和 Fun ControlNet 都是 Qwen Research License。（中高）
9. **Qwen 接 Detailer 有一个已知的偶发黑图问题**（issue #1144）：“all images become black and it never recovers until ComfyUI is restarted”。社区的绕法是在 Detailer 前加 VRAM 清理节点，或删掉断开的节点后重启。服务端要有黑图检测，检测到就重启进程。（中）
10. **3090 速度：未查到**任何 Qwen-Image detailer 的实测数字。估算：Turbo 每张脸 8 步，裁图约 1024²，大概几秒到十几秒；加 Fun ControlNet（约 7 GB）后显存紧张，大概率要 fp8 或卸载。要本机计时。（低，估算）

---

## 1. 详述

### 1.1 Impact Pack / Impact Subpack

**1.1.1 节点分工与许可**
- Impact Pack 的许可证：“GPL-3.0 license”。https://github.com/ltdrdata/ComfyUI-Impact-Pack — 高
- UltralyticsDetectorProvider 已拆出去单独装：“The UltralyticsDetectorProvider node is not part of the ComfyUI-Impact-Pack.” 需另装 ComfyUI-Impact-Subpack。同上 — 高
- Subpack 的许可证：“AGPL-3.0 license”。节点作用：“Loads the Ultralystics model to provide SEGM_DETECTOR, BBOX_DETECTOR.” 模型放在 `models/ultralytics/bbox` 和 `models/ultralytics/segm`。https://github.com/ltdrdata/ComfyUI-Impact-Subpack — 高
- Subpack 的安全说明：“Loading model files can involve executing code”。PyTorch 2.6+ 改成默认 weights_only，老 .pt 可能加载失败；受信任的模型要写进 `ComfyUI/user/default/ComfyUI-Impact-Subpack/model-whitelist.txt`。同上 — 高
- DetailerForEach 的工作方式：只在 mask 区域做高分辨率重绘，再贴回原图。FaceDetailer = 检测器 + detailer。SAMDetector：“Utilizes the SAM technology to extract the segment at the location indicated by the input SEGS”。Impact README — 高
- 对 DiT 的支持：README 写着 Flux.1 支持是 V6.0 加的，并说“Models like FLUX.1 do not use Negative Conditioning”。BASIC_PIPE 把 model、clip、vae 和 conditioning 打包在一起，可选不必用。同上 — 高

**1.1.2 关键参数（FaceDetailer 源码默认值）**
来源：`modules/impact/impact_pack.py`（WebFetch 读源码转述）https://raw.githubusercontent.com/ltdrdata/ComfyUI-Impact-Pack/Main/modules/impact/impact_pack.py — 高
| 参数 | 默认 | 含义 |
|---|---|---|
| guide_size | 512 | “This is the reference size for the Detailer.”“Target images in SEGS smaller than `guide_size` are enlarged to match `guide_size`” |
| guide_size_for | bbox | “When set to `bbox`, it uses the bbox detected by the detector as the reference.” |
| max_size | 1024 | “restricts the longer side of the target image to be smaller than `max_size`” |
| steps / cfg / denoise | 20 / 8.0 / 0.5 | **对 Turbo 必须改** |
| feather | 5 | 贴回时 `mask = utils.tensor_gaussian_blur_mask(mask, feather)`，再 `utils.tensor_paste(...)` |
| noise_mask | True | “whether to apply a noise mask during the inpainting process” |
| force_inpaint | True | “Prevents skipping the detailing process based on `guide_size`” |
| bbox_threshold / bbox_dilation / bbox_crop_factor | 0.5 / 10 / 3.0 | crop_factor 是检测框外扩的上下文倍数，作者警告“the size of the enlarged image based on the crop_factor can be several times larger than the guide_size” |
| sam_threshold / sam_detection_hint | 0.93 / center-1 | SAM 精细 mask |
| drop_size | 10 | 小于这个尺寸的检测结果丢弃 |
| cycle | 1 | “the number of iterations for applying sampling” |
| noise_mask_feather | 20 | `noise_mask = utils.tensor_gaussian_blur_mask(noise_mask, noise_mask_feather)`，大于 0 时会自动 `apply_differential_diffusion(model)`（core.py）。作者警告：“This option does not guarantee a more natural image; in fact, it may create artifacts along the edges.” |
| inpaint_model | False | “When using an inpaint model, this option needs to be enabled to ensure proper inpainting at denoise values below 1.0.” |

参数解释的出处：https://github.com/ltdrdata/ComfyUI-extension-tutorials/blob/Main/ComfyUI-Impact-Pack/tutorial/detailers.md — 高

**1.1.3 能不能接 Qwen-Image（DiT）**
- 源码：`enhance_detail` 通过 `impact_sampling.ksampler_wrapper(model, seed, steps, cfg, ...)` 采样，没有 qwen 或 flux 的模型分支。唯一的特例是“# workaround: support WAN as an i2i model”对 5D 输出做 squeeze。https://raw.githubusercontent.com/ltdrdata/ComfyUI-Impact-Pack/Main/modules/impact/core.py — 高（机制）
- PR #1240（2026-10-31）：报告者“add 'DetailerDebug (SEGS)' in standard Qwen 2.1 workflow”时报错“'Tensor' object has no attribute 'copy'”，用的是 V8.28.3。维护者回复“The same `tensor_convert_rgb` error has now been fixed by #1243”，修法是对 tensor 用 clone()，已合入 Main（e8483bc）。https://github.com/ltdrdata/ComfyUI-Impact-Pack/pull/1240 ；https://github.com/ltdrdata/ComfyUI-Impact-Pack/pull/1243 — 高（说明 Qwen 2.1 + Detailer 已有人在用，并修过一次 bug）
- PR #1231：FaceDetailer 遇到 Wan、Qwen-Image、Krea 2 的视频 VAE 会报“Expected NHWC tensor, but found 5 dimensions”，“Already fixed upstream by 48a8143”（v8.21.2）。https://github.com/ltdrdata/ComfyUI-Impact-Pack/pull/1231 — 高
- issue #1208：用 Qwen Image Edit 2511 做 detailer 时脸会变成另一张。回复：“Detailers is Crop-n-Stitch algorithm.”“Of course, they work well with Edit models too.” 回复里附了一个 Qwen Image 2.1 工作流（NKD Crop-n-Stitch），注明“you need latest fix to work with Qwen 2.1”。https://github.com/ltdrdata/ComfyUI-Impact-Pack/issues/1208 ；https://github.com/Nekodificador/ComfyUI-NKD-Basic-Tools/issues/2 — 中（参数在附件 JSON 里，未读到）
- issue #1104：“Detailer (SEGS), qwen model cannot use it”，没有正文也没有回复。https://github.com/ltdrdata/ComfyUI-Impact-Pack/issues/1104 — 低
- issue #1144（黑图）：“all images become black and it never recovers until ComfyUI is restarted.” 维护者：“It looks like the output is already corrupted before it even reaches the Impact Pack/Subpack.” 社区绕法：“adding VRAM-Cleanup node to offload cache before using Detailer (SEGS) would eliminate this cast error … But it would add penalty for the next generation.” 另一位反馈：“Deleting the disconnected nodes and restarting ComfyUI always fixes it.” https://github.com/ltdrdata/ComfyUI-Impact-Pack/issues/1144 — 中
- issue #1225（未关闭）：“FaceDetailer permanently poisons subsequent Z-Image Turbo BF16 renders on Blackwell. --fp32-unet prevents it”。这是 Blackwell 架构的问题，3090 是 Ampere，**可能不受影响，未验证**。https://github.com/ltdrdata/ComfyUI-Impact-Pack/issues?q=qwen — 低
- 专门给 Qwen-Edit 做的 detailer：VNCCS QWEN Detailer，自带 `color_match_method`（默认 `kornia_reinhard`）和 `seam_fix`（“Poisson blending on paste”）。页面说“Drift is the model, not the node”，并建议起点“steps=4, cfg=1.0, denoise=1.0, target_size=1024”（这是针对 Edit 模型的）。https://comfy.icu/node/VNCCS_QWEN_Detailer — 中（第三方页，repo 名前后不一致）

**1.1.4 检测器权重（Bingsu/adetailer）**
- 许可证“apache-2.0”；“All models were created and saved using the official ultralytics library”。https://huggingface.co/Bingsu/adetailer — 高
- mAP 和大小（大小来自 tree 页面）：
  - face_yolov8m.pt：mAP50 0.737，52 MB
  - hand_yolov8s.pt：0.794，22.5 MB
  - hand_yolov9c.pt：0.810，51.6 MB
  - person_yolov8m-seg.pt：bbox 0.849 / mask 0.831，54.8 MB

  https://huggingface.co/Bingsu/adetailer/tree/main — 高
- 训练数据：手部用 AnHDet 和 hand-detection-fuao9，人脸用 WIDER FACE 等。同上 — 高
- Ultralytics 的许可立场：“all Ultralytics YOLO trained models fall under the AGPL-3.0 License by default”，“even if you train your own model from scratch”。商用要买 Enterprise License。社区（r/computervision）认为权重不一定受约束。https://www.ultralytics.com/request-license — 中（法律上有争议；我们只在本地推理用，不分发，AGPL 的网络条款要看是否对外提供服务）

### 1.2 手部修复

**1.2.1 HandRefiner（论文和官方仓库）**
- “HandRefiner employs a conditional inpainting approach to rectify malformed hands”；基模“the base model used in this project is sd1.5”；建议“a smaller control strength (e.g. 0.4 - 0.8)”，示例用 0.55。https://github.com/wenquanlu/HandRefiner — 高
- 局限：“hands with size at least 60px × 60px is recommended”；对认不出形状的手，“it is pretty much impossible for neural networks to fit a reasonable mesh”；“we do not rectify the hand size”。许可证“MIT license”。同上 — 高
- MeshGraphormer：“Our research code is released under the MIT license.”；“any use of SMPL models and MANO models are subject to … Software Copyright License for non-commercial scientific research purposes”。https://github.com/microsoft/MeshGraphormer — 高

**1.2.2 comfyui_controlnet_aux 的 MeshGraphormer 节点**
- 仓库许可“Apache-2.0”。预处理器 `depth_hand_refiner`，配套 ControlNet 是“control_sd15_inpaint_depth_hand_fp16”。https://github.com/Fannovel16/comfyui_controlnet_aux — 高
- 源码参数（`node_wrappers/mesh_graphormer.py`）：`mask_bbox_padding` 默认 30；`mask_type` 可选 `based_on_depth / tight_bboxes / original`；`mask_expand` 默认 5；`detect_thr` 0.6；`presence_thr` 0.6；输出 `("IMAGE", "MASK")`。缺 mediapipe 时会自动 pip 安装。另有 `Mesh_Graphormer_With_ImpactDetector_Depth_Map_Preprocessor`，可以直接吃 Impact 的 `BBOX_DETECTOR`（bbox_threshold 0.5、bbox_dilation 10、bbox_crop_factor 3.0）。https://raw.githubusercontent.com/Fannovel16/comfyui_controlnet_aux/main/node_wrappers/mesh_graphormer.py — 高
- 权重（hr16/ControlNet-HandRefiner-pruned，卡标 apache-2.0）：
  - graphormer_hand_state_dict.bin：856 MB
  - hrnetv2_w64_imagenet_pretrained.pth：513 MB
  - control_sd15_inpaint_depth_hand_fp16.safetensors：723 MB（**只能用于 SD1.5，Qwen 用不上**）

  https://huggingface.co/hr16/ControlNet-HandRefiner-pruned/tree/main — 高
- 社区 SD1.5 的用法：denoise 约 0.75，配深度 ControlNet。https://stable-diffusion-art.com/?p=12754 — 中

**1.2.3 Qwen 侧有没有深度 / inpaint ControlNet**
- **Qwen-Image 2.1 Fun ControlNet Union**（alibaba-pai）：八种控制“Canny, Depth, Grayscale, HED, Lineart, MLSD, Pose, Scribble”，外加“image inpainting”；`control_context_scale` 建议 1.0；“about 7.0 GB”；许可证“qwen-research”；**没有专门的手部控制**；卡上**没说是否兼容 Turbo**。https://huggingface.co/alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union — 高
- ComfyUI 支持：“ComfyUI support merged into core on September 28, 2026”（PR #16519），通过 Load Model Patch 加载，用 Apply Qwen Image DiffSynth ControlNet 节点。显存：“the transformer plus the Qwen3-VL text encoder do not fit a single consumer GPU fully loaded”。https://comfyui-wiki.com/en/news/2026-09-24-qwen-image-2-1-fun-controlnet-union — 中（二手转述）
- 官方节点文档：mask 对 DiffSynth / Z-Image 补丁会内部取反；对“Qwen Image 2.1 Fun ControlNet patch”则“as given”（不取反）。有 `start_percent / end_percent`。节点标为 experimental。https://docs.comfy.org/built-in-nodes/QwenImageDiffsynthControlnet — 高
- Qwen-Image 1.x 的旧件：InstantX Union（canny/soft edge/depth/pose，深度用 depth-anything，scale 0.8–1.0，Apache-2.0）https://huggingface.co/InstantX/Qwen-Image-ControlNet-Union ；InstantX Inpainting（Apache-2.0，示例 30 步、true CFG 4.0）https://huggingface.co/InstantX/Qwen-Image-ControlNet-Inpainting ；DiffSynth 的 depth/inpaint 补丁，每个 2.27 GB https://huggingface.co/Comfy-Org/Qwen-Image-DiffSynth-ControlNets 。这些都是**为 Qwen-Image 1.x 训练的，2.1 能不能用未查到**，大概率不兼容。— 中
- Qwen-Image 2.1 / Flux 专门的 hand depth ControlNet：**未查到**。MeshGraphormer 深度图喂给 DiT 的通用 depth CN，这个组合**未查到实测**。

**1.2.4 Inpaint-CropAndStitch（lquesada）**
- 许可证 GPL-3.0。“enable inpainting only on masked area very easily”；`mask_blend_pixels`：“Grows the stitch mask and blurs it … no seams”；`context_from_mask_extend_factor`、`mask_expand_pixels`、`output_resize_to_target_size`（“Forces that the cropped image has a specific resolution”）。README 有 Flux 示例，**没提 Qwen**。https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch — 高
- 它和 Impact Detailer 是同一类思路（裁剪 → 放大 → 重绘 → 羽化贴回）。区别是 Impact 自带检测器循环，Crop&Stitch 要你自己给 mask。我们已经用 Impact 做检测，**不必再装 Crop&Stitch**，除非要用它的固定目标分辨率（Qwen 要求边长是 16 的倍数）。— 中（推断）

### 1.3 手部畸形自动检测（闸门）
- MediaPipe Hand Landmarker：“detects the keypoint localization of 21 hand-knuckle coordinates”；`min_hand_detection_confidence` 和 `min_hand_presence_confidence` 默认都是 0.5；`num_hands` 默认 1（要改成 2 或 4）。代码 Apache-2.0。https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker ；https://github.com/google-ai-edge/mediapipe — 高
- MediaPipe 在生成图上不可靠：真实图检出率 0.414、合成图 0.314；已检出的手 anatomical-pass 率分别是 0.947 和 0.997。https://arxiv.org/pdf/2606.01896 — 中（数字来自搜索摘要，全文未读）。含义：MediaPipe 输出的永远是 21 个点，**数不出“六根手指”**。它只能当“拟合失败 / presence 低”的弱信号。
- HADM（人体伪影检测，EVA-02-L / ViTDet）：HADM-L 全域 AP50 43.3，SDXL 上 39.5；“our models take JPEG images as input”；依赖 PyTorch 1.12.1 + mmcv 1.7.1；**仓库页面没写许可证**；权重放在 Dropbox。https://github.com/wangkaihong/HADM — 中。结论：精度低、环境太老、许可不明，**不进主链**，最多离线抽检。
- ViT-HD（Distortion-5K）：README 说论文“has been withdrawn from arXiv”，权重和许可都没写。https://github.com/TheRoadQaQ/Predicting-Distortion — 低，不可用
- 社区现成的“bad hands 分类器”：**未查到**有维护、可直接用的版本。
- 论文“Detecting and Restoring Non-Standard Hands”（2312.04236）用微调的 YOLOv8 检测非标准手，权重**未查到**公开。— 低

### 1.4 防合成感
- denoise：“At 0.4 you nudge the face cleaner while keeping the identity. Push past 0.6 and you are generating a new face that happens to sit in the same spot.” https://www.runflow.io/blog/comfyui-face-detailer — 中（单篇教程）
- Reddit 的共识是 face detailer 的 denoise 太高会导致脸和身体不搭；有人建议“Face detailer denoise too high.”，并主张先整图放大再 detail。https://reddit.sentinel-team.org/posts/1rl9rf8/ 等镜像 — 低到中
- 色差和框痕：ComfyUI 论坛报告“I can literally see the box shape around them”，detailer 会让深色皮肤的脸变亮。反馈有效的做法是“matching the original CFG, steps, and sampler/scheduler”，以及把 bbox dilation 拉大。https://forum.comfy.org/t/skin-color-mismatch/3840 — 低到中
- Buumcode 的建议：inpaint 时用“the same model (and same settings) as was in GENERATE this image”。https://github.com/Nekodificador/ComfyUI-NKD-Basic-Tools/issues/2 — 中。对我们来说就是 **detailer 用回同一个 Qwen-Image 2.1 Turbo、同 sampler/scheduler、同正向提示词（加脸部描述）**。
- 色彩匹配：KJNodes ColorMatch 支持 mkl、hm、reinhard、mvgd、hm-mvgd-hm、hm-mkl-hm，依赖 `color-matcher`。https://comfyui-wiki.com/en/custom-nodes/ComfyUI-KJNodes/nodes/color-match — 中；KJNodes 许可证 GPL-3.0 https://github.com/kijai/ComfyUI-KJNodes — 高
- Differential Diffusion（ComfyUI 内置）：Impact 在 noise_mask_feather > 0 时会自动套用，不必另加。https://docs.comfy.org/built-in-nodes/DifferentialDiffusion ；core.py — 高
- 在什么分辨率重绘：Impact 的机制是把裁图按 guide_size 放大后重绘，再缩回原尺寸贴回（`upscale = guide_size / min(bbox_w, bbox_h)`，上限 max_size）。所以“放大后重绘”是内建的，不需要先放大整张图。Qwen 2.1 训练和出图都在 1.3K–2.5K，guide_size 设 1024 左右比 512 更接近模型的舒适区。— 中（推断，需 A/B）
- 身份校验：项目里已有 `tools/identity/id_gate.py`（buffalo_l ArcFace）。insightface 的说明是“ALL models are available for non-commercial research purposes only”。第三方测过的余弦中位数：同一人约 0.68，不同人约 0.01。https://github.com/deepinsight/insightface/blob/master/model_zoo/README.md ；https://huggingface.co/nynxz/Zentrainer — 中

### 1.5 速度（RTX 3090）
- Qwen-Image detailer 在 3090 上的实测：**未查到**。唯一能参考的是一个 4090 + Flux 的供应商数字，称 face detailer“+1.5 s”。https://gigagpu.com/?p=34157 — 低
- 估算：Turbo 8 步。denoise 0.35 时 ComfyUI 会按 steps/denoise 算 sigma，仍然跑 8 次前向。1024² 的裁图在 3090 上每张脸约 5–15 s，YOLO 检测小于 0.1 s，SAM vit_b 小于 1 s，MeshGraphormer 每只手约 1–3 s（全是估算，低）。

---

## 2. 方案总表

| 方案 | 修什么 | 能否用 Qwen-Image 2.1 Turbo | 优点 | 风险 | 许可 | 置信度 |
|---|---|---|---|---|---|---|
| A. Impact FaceDetailer（face_yolov8m + SAM，可选） | 脸糊、小脸、身份轻漂 | 能（需 ≥ 2026-10-31 Main） | 检测、裁剪、羽化贴回一体；已有 Qwen 2.1 用户 | Turbo 部分去噪未验证；偶发黑图 #1144 | GPL-3.0 / Subpack AGPL / 权重 Apache（有 AGPL 争议） | 中高 |
| B. Impact Detailer(SEGS) + hand_yolov9c + SAM（低去噪） | 手糊、轻度畸形、指甲 | 同上 | 主路；改动小，不伤其他区域 | 修不了多指或缺指（拓扑错误） | 同上 | 中 |
| C. MeshGraphormer 深度 + Qwen 2.1 Fun ControlNet（Depth + inpaint）高去噪 | 多指、缺指、错位 | **理论可行，未见实测** | 唯一能“按正常手结构重画”的路 | MANO 非商用；Fun CN 是 Research License，约 7 GB，和 Turbo 的兼容性未知；手太小（< 60 px）或形状认不出时拟合失败 | aux Apache / Graphormer MIT + MANO 非商用 / Qwen Research | 低 |
| D. 原 HandRefiner（SD1.5 inpaint depth hand CN） | 多指 | 不能直接用；要另起一个 SD1.5 局部模型 | 论文方法，有实测 | 风格和质感和 Qwen 图不一致，贴片感最强 | MIT + MANO | 中（结论：不选） |
| E. Inpaint-CropAndStitch + Qwen 2.1 inpaint | 任意局部 | 能（通用） | 目标分辨率可控 | 要自己给 mask；和 A/B 功能重复 | GPL-3.0 | 中 |
| F. 整张重抽（换 seed） | 一切 | — | 零合成感 | 费时；新图可能又坏在别处 | — | 高 |
| G. 闸门：hand_yolov9c + MediaPipe 21 点 + 本地看图复核 | 检出疑似坏手 | 与模型无关 | 便宜、可解释 | MediaPipe 会把坏手也拟合成 21 个点，漏检率高 | Apache / AGPL 争议 | 中 |
| H. 闸门：HADM | 检出伪影 | 与模型无关 | 专门针对 AI 伪影 | AP50 43、许可不明、环境太老 | 未写 | 低（不选） |

---

## 3. 推荐流水线（出图后自动修脸修手）

### 3.1 节点链
```
Qwen-Image 2.1 Turbo 出图（原分辨率，例如 1696×2528）
 │
 ├─[闸门0] 黑图/NaN 检测 → 黑图则重启 ComfyUI 进程并重跑（#1144）
 │
 ├─[修脸] UltralyticsDetectorProvider(face_yolov8m.pt) ─┐
 │        SAMLoader(sam_vit_b，可选)                     ├→ FaceDetailer
 │        同一套 MODEL/CLIP/VAE（Qwen-Image 2.1 Turbo）  ─┘   （VRAM 清理节点放在 Detailer 前）
 │        → ColorMatch(KJNodes，reference=原图，image=修后图，method=hm-mvgd-hm 或 mkl)
 │          用“脸 mask 羽化”把调色结果再合回原图，只作用在脸区
 │        → id_gate 打分：修后分数 ≥ 修前分数 − 0.02，且 ≥ 景别线，否则回退原图
 │
 ├─[手部闸门] hand_yolov9c 检测（conf ≥ 0.35，边长 ≥ 60px 才处理）
 │        → 每只手裁图跑 MediaPipe（num_hands=2，presence_thr 0.5）
 │        → 标记 suspect：YOLO 看到手但 MediaPipe 拟合不上 / presence < 0.5 / handedness 冲突
 │        → suspect 和所有近景手交本地看图模型（项目已有的本地看图复核）判“手指数量、粘连、扭曲”
 │
 ├─[修手-轻] 判为“糊/轻度变形”：Detailer(SEGS)，hand_yolov9c + SAM，低去噪
 │
 ├─[修手-重] 判为“多指/缺指/错位”：
 │        方案 C（试验，过 A/B 前不进主链）：Mesh_Graphormer_With_ImpactDetector 出深度图和 mask
 │          → Apply Qwen Image DiffSynth ControlNet(Fun Union, depth 图, mask) → Detailer 高去噪
 │        否则 → F 整张重抽（换 seed，最多 N 次）
 │
 └─[终检] 手部闸门再跑一遍 + id_gate + GEN_CONTRACT 人工亲审
```

### 3.2 参数起点（必须 A/B）
| 项 | 修脸（FaceDetailer） | 修手-轻（Detailer SEGS） | 修手-重（方案 C） |
|---|---|---|---|
| detector / threshold | face_yolov8m / 0.5 | hand_yolov9c / 0.35 | hand_yolov9c / 0.35 |
| bbox_dilation / crop_factor | 10 / 2.5–3.0 | 10 / 3.0 | 20 / 3.0 |
| guide_size / max_size | 1024 / 1536（**边长须为 16 的倍数**） | 1024 / 1536 | 1024 / 1536 |
| steps / cfg / sampler | **8 / 1.0**，与主出图相同 sampler/scheduler | 同左 | 同左 |
| denoise | 0.30 起，最高 0.40 | 0.35 起，最高 0.45 | 0.65–0.80 |
| feather（贴回） | 8–15 | 8–12 | 12–20 |
| noise_mask / noise_mask_feather | True / 20 | True / 15 | True / 20 |
| SAM | vit_b，threshold 0.93，可选 | vit_b，开（防止改到相邻物体，社区建议） | 用 MeshGraphormer 的 mask（based_on_depth，padding 30） |
| prompt | 原正向提示词 + 角色脸部描述（与出图一致） | 原正向提示词 + “natural hands, five fingers” | 同左；control_context_scale 1.0 起 |
| cycle | 1 | 1 | 1 |

### 3.3 回退条件
1. 修脸后 id_gate 分数下降超过 0.02，或低于景别线 → 用原图。
2. 修后与修前在 mask 外的像素差 L1 > 1/255（贴回逻辑异常）→ 用原图并报警。
3. 修后脸区与周围皮肤在 Lab 色差 ΔE 均值上比修前高 > 3（贴片感）→ 先换 ColorMatch 方法重试 1 次，仍不过则用原图。
4. 手部闸门在修后仍判坏 → 修手-重 → 仍坏 → 整张重抽（最多 3 次）→ 都失败就标记交人工，**不交付**。
5. 输出全黑、全灰或含 NaN → 重启进程重跑（#1144）。
6. 手小于 60 px → 不修，必要时改分镜让手出画（HandRefiner 的建议下限）。

---

## 4. 需下载清单（只列出，不下载）

| 类型 | 名称 | 大小 | 许可证 | 来源 | 必需度 |
|---|---|---|---|---|---|
| 插件 | ComfyUI-Impact-Pack（≥ Main e8483bc，2026-10-31） | 小 | GPL-3.0 | https://github.com/ltdrdata/ComfyUI-Impact-Pack | 必需 |
| 插件 | ComfyUI-Impact-Subpack | 小 | AGPL-3.0 | https://github.com/ltdrdata/ComfyUI-Impact-Subpack | 必需 |
| 权重 | face_yolov8m.pt → models/ultralytics/bbox | 52 MB | Apache-2.0（Ultralytics 主张 AGPL） | https://huggingface.co/Bingsu/adetailer | 必需 |
| 权重 | hand_yolov9c.pt → models/ultralytics/bbox | 51.6 MB | 同上 | 同上 | 必需 |
| 权重 | hand_yolov8s.pt（备选，更快） | 22.5 MB | 同上 | 同上 | 可选 |
| 权重 | person_yolov8m-seg.pt → models/ultralytics/segm | 54.8 MB | 同上 | 同上 | 可选 |
| 权重 | SAM sam_vit_b_01ec64.pth → models/sams | 约 375 MB（常见值，未逐一核对） | Apache-2.0 | https://github.com/facebookresearch/segment-anything | 推荐 |
| 插件 | ComfyUI-KJNodes（ColorMatch，pip color-matcher） | 小 | GPL-3.0 | https://github.com/kijai/ComfyUI-KJNodes | 推荐 |
| pip | mediapipe（手部闸门，可在 ComfyUI 外独立跑） | 约数十 MB | Apache-2.0 | https://github.com/google-ai-edge/mediapipe | 推荐 |
| 插件 | comfyui_controlnet_aux（MeshGraphormer） | 小 | Apache-2.0 | https://github.com/Fannovel16/comfyui_controlnet_aux | 试验 |
| 权重 | graphormer_hand_state_dict.bin + hrnetv2_w64_imagenet_pretrained.pth | 856 MB + 513 MB | 卡标 Apache-2.0；MANO 非商用科研 | https://huggingface.co/hr16/ControlNet-HandRefiner-pruned | 试验 |
| 权重 | Qwen-Image-2.1-Fun-Controlnet-Union.safetensors → models/model_patches | 约 7.0 GB | Qwen Research License | https://huggingface.co/alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union | 试验（需确认 Turbo 兼容性和 3090 显存） |
| 插件 | ComfyUI-Inpaint-CropAndStitch | 小 | GPL-3.0 | https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch | 不必（与 Impact 重复） |
| 已有 | insightface buffalo_l（id_gate） | 已在服务器 | 非商用科研 | 项目已部署 | 复用 |

**注意**：Subpack 在 PyTorch ≥ 2.6 下加载 .pt 可能失败，需要把上面这些 Bingsu 权重的路径写进 `ComfyUI/user/default/ComfyUI-Impact-Subpack/model-whitelist.txt`（只放可信来源）。

## 5. 未查到 / 待本机验证
- Qwen-Image 2.1 **Turbo** 在 denoise < 1 的局部重绘中的质量（官方说“other schedules are untested”）。
- Fun ControlNet Union 是否兼容 Turbo，以及 3090 上的显存占用和速度。
- MeshGraphormer 深度图驱动 DiT depth ControlNet 修多指的实际效果。
- Qwen detailer 在 3090 上的单脸、单手耗时。
- 有维护、可直接用的“bad hands”分类器。
