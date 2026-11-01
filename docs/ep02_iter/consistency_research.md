# 人物一致性：调研、根因、实测（CONSIST，2026-10-31）

项目方原话："这里面是关于 2.1 的，怎么可以做人物的一致性。我觉得类似的社区已经有很多方法可以提升了，我们都没有做好……为什么有这么多开源分享的案例都已经做得很好，但是你还是没有？……我希望你自己学会递增式地学习，不断去寻找更好的 solution。"

"2.1" 已由总调度确认 = **Qwen-Image 2.1**。他给的工作流在 `data/ab/owner_workflows/aisley_char_sheet/`：角色设定图，用多图参考 `<image1>/<image2>/<image3>`，配 QI2.1_AnyAngle LoRA 0.6。

本文只写技术，不评价剧本内容，不做内容检测。config 一律没改，第 6 节只写建议。下一轮从 `docs/ep02_iter/LEARNING_BACKLOG.md` 继续。

---

## 0. 一页结论

1. **度量**：新工具 `tools/identity_metric.py`，用 ArcFace（insightface buffalo_l，w600k_r50）。每帧的脸归给余弦最高的角色，不靠发色猜人。
2. **林晚**：
   - ep02 现在 11 张定稿首帧，对定妆脸（`config/face_reference.json` → `lin_wan.png`）的余弦均值约 **0.53**，范围 0.26–0.69。
   - 进视频后再掉一截：镜头中位均值约 **0.45**，镜内最低到 0.16。
   - S1 最明显：首帧 0.575，视频中位只剩 0.269。
3. **顾沉 / 陈宇**：现有片子里的男性脸对两人的旧参考图余弦全在 0.15–0.26，等于"另一个人"。原因是他们根本没有身份来源。
4. **项目方的 Qwen-Image 2.1 设定图流程，林晚这边一次就做到了**：
   - 设定图左栏脸对定妆脸余弦 **0.926**（A 版，完全照项目方工作流）。
   - 同一流程再挂我们的林晚出图 LoRA（lin_wan_qi_v1 0.6），反而降到 **0.823**。
   - 说明我们现在靠"出图 LoRA + 纯文字"出首帧，本身就在把林晚的脸往别处拉。
5. 社区的成熟做法是三层叠加：参考图（设定图）+ 身份 LoRA/适配器 + 视频侧身份约束或后处理换脸，每一层都用脸向量量化。我们只有"出图 LoRA"这一层，而且没有量化。
6. **实测**：
   - 用设定图当参考出首帧（R 方式），林晚 S1 / S2 分别是 0.575→0.706、0.422→0.579；顾沉 0.43 / 0.57；陈宇 0.56。
   - 但设定图的服装会被带进画面，需要按集出"造型版设定图"。
   - H3 角色替换 LoRA 在 3090 上只能跑 544p、5 秒；会换掉服装，身份只提升 +0.08（v1.5）。暂不采用。
7. 推荐方案和参数建议见第 6 节；没验证完的方法见 `LEARNING_BACKLOG.md`。

---

## 1. Deep Research：社区方法对比

两个调研分支只用了 WebSearch / WebFetch，没有登录、没有付费、没有下载任何执行文件。

注意：WebFetch 返回的是小模型对网页的摘录，所以"原文引用"没有逐字对照原网页。置信度已经按这一点下调过。

### 1.1 视频侧

| 方法 | 原理 | ComfyUI | 显存 / 3090 | 竖屏短剧适用度 | 原文引用 · 链接 | 置信度 |
|---|---|---|---|---|---|---|
| **H3 Ref2VA 多参考图** | 独立的 Ref2VA 权重，最多 9 张参考图作 `<Picture n>`；Multiframe 模板用 Add Guide 把图钉在指定帧 | 原生 MiniMaxH3ReferenceToVideo + MiniMaxH3AddGuide（本机两张卡都有） | int8 剪枝版能在 3090 上跑（我们 X4 实测峰值 22.7 GB） | 高：就是主力模型 | "`<Picture 1>` is both the identity lock and the first frame" [Comfy 文档](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-multiframe)；4 步时"the references may hardly be applied" [digitalcreativeai](https://www.digitalcreativeai.net/en/post/minimax-h3-comfyui-reference-to-video)；"a `<Subject 1>` label carries no identity" [ai-muninn](https://ai-muninn.com/en/blog/minimax-h3-ref2va-two-characters) | 中高 |
| **H3 Character Swap LoRA** | 在 Ref2VA 上训的 LoRA：把 `<Video 1>` 里的人换成 `<Picture 1>` 的人，保留表演和音轨 | LoraLoaderModelOnly + Ref2VA（ref_videos 槽）；本机 gpu33 有 `h3_character_swap_v1.5` 和 `h3_character_swap_pro4500_1000` | 跟 H3 底模一样 | 中高：适合当返修步骤 | "an experimental character-swap model" [akatz HF](https://huggingface.co/akatz-ai/MiniMax-H3-Character-Swap-LoRA)；"not a guaranteed identity-transfer system" [comfyui-wiki](https://comfyui-wiki.com/en/news/2026-10-13-h3-character-swap-live-wallpaper)；推荐配方：8 步、er_sde、cfg 1、Turbo 8step v1.0 | 中 |
| H3 FaceSwap / Head Swap LoRA | 只换脸或头 | Alissonerdx 包，触发词 `head_swap:` | 未找到 | 中 | "no third-party test results had surfaced" [comfyui-wiki](https://comfyui-wiki.com/en/news/2026-09-20-h3-faceswap-lora)；[Alissonerdx](https://huggingface.co/Alissonerdx/Minimax-H3-ComfyUI) | 低 |
| **H3 角色 LoRA 训练** | ai-toolkit 的 minimax_h3 扩展，FL2VA 和 Ref2VA 都能训 | 训练用 ai-toolkit，推理用 LoraLoaderModelOnly | 24 GB 能不能训：未找到 | 高（如果能训） | "T2V and I2V LoRA training for both H3 checkpoints" [comfyui-wiki](https://comfyui-wiki.com/en/news/2026-08-03-ai-toolkit-minimax-h3-training) | 中 |
| Phantom-Wan | 跨模态对齐的主体到视频，≤4 张参考 | WanVideoWrapper / WanPhantomSubjectToVideo | fp8 可以跑；480p 训练 | 中：竖屏 768×1344 超出训练分辨率 | "The number of reference images should be within 4." [HF](https://huggingface.co/bytedance-research/Phantom) | 高（README）/ 低（效果） |
| VACE 参考图 | 参考图经 VAE 编码，拼在控制 latent 前面 | WanVaceToVideo，官方模板 | 14B 要 fp8 / GGUF | 中 | 用 Pose / Depth 控制时会改脸："DW or OpenPose have an issue of altering the face" [r/SD](https://redlib.ssps.io/r/StableDiffusion/comments/1kngs4j/vace_14b_is_phenomenal) | 中 |
| MAGREF | 区域感知 mask，多参考 | WanVideoWrapper | 官方"around 70 GB of VRAM" [HF](https://huggingface.co/MAGREF-Video/MAGREF) | 中低 | — | 中 |
| Stand-In | 只多训约 1% 参数的身份适配器（Wan2.1-14B） | Stand-In_Preprocessor / Wrapper | 未写 | 中：适合正脸中近景 | "implementation differs from the official version" [HF](https://huggingface.co/BowenXue/Stand-In) | 高（卡片） |
| Lynx | 冻结 Wan2.1，训 ID-adapter 和 Ref-adapter | WanVideoAddLynxEmbeds | 未找到 | 中 | 论文脸相似度 insightface 0.699 [arXiv](https://arxiv.org/html/2509.15496v1) | 中 |
| SkyReels-A2 | 多元素组合生成 | ComfyUI-SkyReels-A2 | fp8；480×832 | 低中 | [comfy.icu](https://comfy.icu/extension/Yuan-ManX__ComfyUI-SkyReels-A2) | 低 |
| HunyuanCustom | 混元多模态定制 | 官方 ComfyUI 未完成 | 60–80 GB，**3090 不可行** | 低 | "80GB" [HF](https://huggingface.co/tencent/HunyuanCustom) | 高 |
| MoCha | 视频角色替换（首帧 mask + 参考图） | WanVideoWrapper MochaEmbeds | 未找到 | 中 | [RunComfy](https://www.runcomfy.com/comfyui-workflows/video-character-replacement-mocha-in-comfyui-seamless-character-swap) | 低 |
| Wan2.2 Animate | 角色驱动 / 角色替换两种模式 | 官方模板，有 GGUF | 24 GB 能跑 | 中 | "replaces the character image with the input video" [HF](https://huggingface.co/Wan-AI/Wan2.2-Animate-14B) | 中 |
| EchoShot | 原生多镜头肖像视频（Wan2.1-1.3B） | 未找到 ComfyUI 节点 | 很轻，但只有 832×480 | 思路最贴合多镜，分辨率低 | [arXiv](https://arxiv.org/html/2506.15838v1) | 中 |
| FantasyID / ConsisID | 免调优的身份保持 DiT | 未找到 | — | 低 | ConsisID FaceSim-Arc 0.58 [arXiv](https://arxiv.org/html/2411.17440v3) | 中 |
| Wan 角色 LoRA | 10–30 张图训身份 LoRA | musubi-tuner / ai-toolkit | "720x1280 images with 24GB VRAM" [musubi](https://github.com/kohya-ss/musubi-tuner/blob/main/docs/wan.md) | 高（成熟），但要换视频底模 | 只用静图训会不动 | 中 |

### 1.2 图像侧

| 方法 | 原理 | 和我们的栈兼容吗 | 原文引用 · 链接 | 置信度 |
|---|---|---|---|---|
| **Qwen-Image 2.1 多图参考编辑**（项目方给的就是这个） | 生成和编辑共用一套权重，TextEncodeQwenImage21 最多 16 个参考槽 | 已在用（本机有 `QI2.1_AnyAngle`、`qwen_image_2.1_vae_bf16`） | "accepts up to 16 slots" [docs.comfy.org](https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1)；官方演示"三视图 → 六格分镜"，第三方注明是 company-selected [runtimewire](https://runtimewire.com/article/alibaba-qwen-image-2-1-character-storyboard-editing-preview) | 高 / 中 |
| Qwen-Image-Edit 2509 / 2511 多图 | 多图输入，2511 加强人物一致性 | 同家族，Apache 2.0 | "Optimal performance…with 1 to 3 input images" [HF 2509](https://huggingface.co/Qwen/Qwen-Image-Edit-2509)；"improved character consistency" [HF 2511](https://huggingface.co/Qwen/Qwen-Image-Edit-2511)；社区说只靠提示词一致率约"about 20%" [r/SD 镜像](https://reddit.sentinel-team.org/posts/1rj994t/snapshots/2026-03-04T15%3A30%3A02.949208Z) | 高 / 中 |
| BFS Best Face Swap（Qwen-Edit 换头 LoRA） | 先给身体图，再给脸图 | 同家族，MIT | "send body first, then face"；作者自评"not perfect yet" [HF](https://huggingface.co/chfm/BFS-Best-Face-Swap) | 中 |
| 角色设定表 / turnaround | 先出多视角设定表，同时当多镜参考和 LoRA 数据集 | 同家族（VNCCS 等） | "dataset scaffolding for LoRA training" [RunComfy VNCCS](https://www.runcomfy.com/comfyui-workflows/comfyui-vnccs-character-workflow-qwen-image-seedvr2) | 中 |
| PuLID-Flux（II） | 用对比对齐把 ID 嵌入注入 FLUX | 只能用于 FLUX；依赖 antelopev2（非商用） | "can run on a 16GB graphic card" [GitHub](https://github.com/ToTheBeginning/PuLID) | 高 |
| InstantID / IP-Adapter FaceID | insightface 嵌入 + ControlNet / LoRA | 只能用于 SD1.5 / SDXL，画质和 Qwen 不一致 | "for research purposes only" [InstantID](https://github.com/instantX-research/InstantID) | 高 |
| InfiniteYou / USO / ACE++ / Kontext | FLUX 系身份注入 / 参考编辑 | FLUX 系；InfiniteYou 是 CC BY-NC，Kontext dev 非商用 | [InfiniteYou](https://github.com/bytedance/InfiniteYou)；[USO](https://github.com/bytedance/USO)；[ACE++](https://github.com/ali-vilab/ACE_plus) | 高 |
| Qwen-Image 系 PuLID / InstantID 适配 | — | **未找到** | — | 中 |
| 角色 LoRA 数据集 | 20–200 张，覆盖角度、光照、表情，避免近似重复；用少见的触发词；想固化的特征不写进 caption | musubi：fp8 + blocks_to_swap 16 时 24 GB | "variety of poses, angles, and lighting" [scenario](https://help.scenario.com/en/articles/advanced-captioning)；[musubi qwen_image](https://github.com/kohya-ss/musubi-tuner/blob/main/docs/qwen_image.md) | 高 / 中 |

### 1.3 后处理

| 方法 | 原理 | 问题 | 原文引用 · 链接 | 置信度 |
|---|---|---|---|---|
| ReActor（inswapper_128） | 逐帧换脸，之后接 GFPGAN / CodeFormer | 128 px 输出；逐帧会闪；**内置裸露检测，成人镜头会被拦**；inswapper 非商用 | "Inswapper still has the best similarity" [GitHub](https://github.com/Gourieff/ComfyUI-ReActor) | 高 |
| FaceFusion（hyperswap_1a_256） | 独立工具，逐帧换脸 + 增强，pixel boost 可到 1024 | hyperswap 权重许可未找到 | 默认"hyperswap_1a_256" [docs](https://docs.facefusion.io/usage/cli-arguments/processors/face-swapper.md) | 高 |
| FaceDetailer | 检测脸后局部重绘 | 逐帧重绘闪烁风险大，更适合关键帧 | [Impact Pack](https://github.com/ltdrdata/ComfyUI-Impact-Pack) | 高 |
| CodeFormer / GFPGAN / GPEN | 单帧人脸修复 | 用静图训练，视频会闪 | "trained using still pictures" [videohelp](https://forum.videohelp.com/threads/409142-Stabilize-temporal-flickering) | 中 |
| KEEP | 卡尔曼式跨帧传播的视频人脸修复 | 权重非商用 | [KEEP](https://github.com/jnjaby/KEEP)；[ComfyUI-KEEP](https://github.com/wildminder/ComfyUI-KEEP) | 中 |

### 1.4 客观度量和阈值

| 来源 | 数值 | 链接 | 置信度 |
|---|---|---|---|
| ConsisID 论文 | FaceSim-Arc 0.58 / Cur 0.60；ID-Animator 0.32 | [arXiv](https://arxiv.org/html/2411.17440v3) | 高 |
| Phantom 论文 | Phantom 0.581；Hailuo 0.542（FaceSim-Arc） | [arXiv](https://arxiv.org/html/2502.11079v2) | 高 |
| DeepFace | ArcFace 余弦**距离**阈值 0.68，相当于相似度 ≥0.32 判同人 | [threshold.py](https://raw.githubusercontent.com/serengil/deepface/master/deepface/config/threshold.py) | 高 |
| InsightFace | 官方没有固定阈值，建议在自己的数据上搜 | [issue #2239](https://github.com/deepinsight/insightface/issues/2239) | 中 |

**我们的分档**是推断，不是原文：≥0.50 当同一人（SOTA 视频模型 0.54–0.70）；0.30–0.50 相像，要人工复核；<0.30 判不是。`identity_metric.py` 就用这一档。

许可证提醒：insightface 的 buffalo_l / inswapper / antelopev2 都是"non-commercial research"。度量只在内部 QC 用；要商用的环节不能依赖这些权重。

---

## 2. 为什么开源案例做得好，我们没有：根因清单（逐条核实）

| # | 根因 | 证据（可复查） | 影响 |
|---|---|---|---|
| R1 | **首帧是纯文字出图，没有任何参考图** | `data/renders/ep02/S*/takes.json`：11 张定稿首帧都是 `workflow=qwen_t2i`、`reference=null`（S1 是对 t2i 的轻改）；CHAIN 审计 §0.1 同结论 | 林晚只能靠 LoRA 和文字"像"，每镜 0.26–0.69 浮动 |
| R2 | **我们的林晚出图 LoRA 和定妆脸不是同一张脸** | 同一套设定图流程：不挂 LoRA，设定图对定妆脸 0.926；挂 lin_wan_qi_v1 0.6 后降到 0.823（`data/ab/identity/sheets`）。纯 LoRA 出的首帧均值约 0.53 | LoRA 反而把身份往外拉；"定妆脸"和"生产脸"之间有一条缝 |
| R3 | **顾沉 / 陈宇完全没有身份来源** | 没有 LoRA，没有参考图；提示词只写"34岁成年男性CEO，黑色高定衬衫"，没有族裔和脸部描述（CHAIN 审计）；片中男性脸对旧参考余弦 0.15–0.26 | 男角每镜都是另一个人 |
| R4 | **视频侧没有身份约束，只靠首帧把身份带进去** | 11 镜全是 `h3_fl2va`，没有 Ref2VA、没有身份参考；林晚首帧 → 视频中位平均掉约 0.07，S1 从 0.575 掉到 0.269，S5 镜内最低 0.171 | 人一转头、一动就漂 |
| R5 | **多镜没有统一参考** | 没有设定图 / turnaround；各镜首帧各自从文字采样 | 镜与镜之间只靠 LoRA 收敛 |
| R6 | **没有客观的身份度量，问题靠肉眼发现** | 只有 SFace 闸门 Q-D1（≥0.30），而且 review.py 把所有非蓝发的脸都拿去比顾沉参考，S9/S10 实际是陈宇 → 这个数无效；SFace 余弦和 ArcFace 不是同一把尺子 | 参数靠猜，改了也不知道有没有变好 |
| R7 | **视频身份 LoRA 没有起作用（LAB 的 lin_wan_h3_v1）** | LAB 评测片 tf_lw：无 LoRA 0.677，step250 / 500 / 750 是 0.663 / 0.674 / 0.660（中位），没有提升；tf_generic 都在 0.20 左右 | 训了，但对身份没有增益（详见 §4） |
| R8 | **Ref2VA 试过一次，但用的是 Turbo 8 步，参考图是正脸底板，没有效果** | X4：F2 Ref2VA 20 步 0.42 / 最低 0.156；F1 Ref2VA Turbo 8 步 0.32；FL2VA 对照 A19 0.393 | 社区说少步数 Turbo 下参考几乎不起作用，和这里吻合 |
| R9 | **男角描述太像，彼此分不开** | 草稿外貌两人只差年龄和"宽肩 / 精瘦"；按草稿出的两张设定图，脸互相余弦 0.55（已算同人边缘） | 即便各自锁住，观众也可能分不清——这条要写作方 / 项目方定，Claude 不改外貌 |

没有发现的问题（核实过）：VAE / 校色 / 去抖不改脸；leica 后缀和 USM 对脸影响可以忽略（LEARNED_SPECS B 表）。

---

## 3. 度量工具

`tools/identity_metric.py`

- 模型：insightface buffalo_l，即 RetinaFace det_10g + ArcFace w600k_r50。
- 环境：
  - gpu33 / gpu36 各有自己的 venv `/root/work/fredw/venv_idm`。没装进 gpu36 的 `/root/work/fredw/venv`，因为那是 gpu36 ComfyUI 的 uv 环境，避免动它的依赖；
  - 模型在 `/root/work/fredw/idm_models`，用 `--model-root` 指过去；
  - 笔记本 scratchpad 里也有一份 venv，但笔记本下载太慢，不建议在笔记本上跑。
- 输出：
  - `identity.json`：每镜每角色的均值 / 中位 / 最低 / p10、覆盖率、镜内漂移；
  - `frames.csv`：逐脸明细；
  - `curve_*.png`：曲线；
  - `summary.md`：总表。
- 局限：
  - 背面、侧脸和小于 48 px 的脸检测不到，表现为覆盖率低；
  - 镜头里有一个没有参考的人时，那张脸会被归给余弦最高的参考，所以 <0.3 的归属不可靠。S9 / S10 的"lin_wan"实际多半是陈宇。

---

## 4. 基线（ep02 现状）

数据在 `data/ab/identity/baseline_g33/` 和 `baseline_g36/`（视频文件分别在两台机器上，各自就地测）。参考图：林晚 = `lin_wan.png`（定妆）；顾沉、陈宇 = `assets/characters/*/refs/*/ar-*.png`（旧参考）。

| 镜 | 林晚·定稿首帧 | 林晚·视频中位（最低） | 男角对旧参考 |
|---|---|---|---|
| S1 | 0.575 | **0.269（0.158）** | — |
| S2 | 0.422 | 0.364（0.306） | 0.23（不像） |
| S3 | 0.472 | 0.442（0.180） | 0.19 |
| S4 | 0.325 | 0.470（0.445） | 0.21 |
| S5 | 0.686 | 0.560（0.171） | 0.22 |
| S6 | 0.643 | 0.515（0.454） | — |
| S7 | 0.578 | 0.487（0.431） | 0.26 |
| S8 | 0.448 | 0.416（0.193） | 0.25 |
| S9 | 背对，测不到 | — | 0.21 |
| S10 | 背对（0.257 是误归的男性脸） | — | — |
| S11 | 0.593 | 0.553（0.508） | — |
| **均值（S1–S8、S11）** | **0.527** | **0.453** | **≈0.22** |

对照组：

| 视频 | 林晚中位（最低） | 说明 |
|---|---|---|
| X4 F2 Ref2VA 20 步 + 正脸卡（S2） | 0.420（0.156） | 比同镜 FL2VA 好一点，但最低值很差 |
| X4 F1 Ref2VA Turbo 8 步 | 0.320（0.155） | Turbo 削弱参考 |
| X4 A19 FL2VA | 0.393（0.349） | |
| LAB lin_wan_h3_v1 评测 tf_lw：nolora / 250 / 500 / 750 | 0.677 / 0.663 / 0.674 / 0.660 | **视频 LoRA 没有增益**（R7） |
| LAB 同上 tf_generic | 0.20–0.24 | 提示词不写林晚时 LoRA 不起作用 |

---

## 5. 实测：Qwen-Image 2.1 设定图 → 首帧 → 视频

（见 5.1–5.4；数据在 `data/ab/char_sheets/`、`data/ab/identity/`、`data/ab/consist_swap/`）

### 5.1 设定图候选（不是定妆，交项目方挑）

照项目方工作流：qwen_image_2.1_int8_convrot + QI2.1_AnyAngle 0.6，qwen3vl_8b_int8_convrot（qwen_image），TextEncodeQwenImage21（参考分辨率 2048），qwen_image_2.1_vae_bf16，25 步，cfg 1，euler / simple，1984×1120（16:9，约 2.2 MP）。脚本 `tools/ab/char_sheet_qi21.py`，记录在 `data/ab/char_sheets/runs.jsonl`。

| 角色 | 身份来源 | 候选 | 脸对定妆 / 主观 |
|---|---|---|---|
| 林晚 | `<image1>`=lin_wan.png（face_reference 已确认），`<image2>`=四栏姿势模板，提示词照 Prompt.txt 第二种 | A_s101 / A_s202（纯项目方流程），B_s101 / B_s202（+lin_wan_qi 0.6） | A 0.926、B 0.823；四个视角是同一人，服装取自参考图（粉色裙） |
| 顾沉 | registry_draft 原文"a 34-year-old East Asian man…broad-shouldered build"，服装取剧本原词"黑色高定衬衫"；`<image1>`=姿势模板 | T_s101 / T_s202 | 四栏一致，黑衬衫黑裤 |
| 陈宇 | registry_draft 原文，服装"休闲装" | T_s101 / T_s202 | 脸可用；身体 **两张都失败**：模板人台的灰白皮肤和内衣渗进来，"休闲装"没生效（见 backlog B3） |

### 5.2 用设定图出 ep02 首帧（对照版）

**设置**

- 同一套 Qwen-Image 2.1 + AnyAngle 0.6，25 步，768×1344，参考分辨率 1024，seed 7。
- 镜头：S1（林晚独角）、S2 / S8（林晚 + 顾沉）、S9（陈宇 + 林晚背影）。
- 两种方式：
  - **E**（改定稿首帧）：`<image1..n>` 是在画角色的设定图，最后一张是当前定稿首帧，提示词要求"构图不动，只换身份"。
  - **R**（按剧本重出）：只给设定图，场景文字用定稿首帧那一版的剧本提示词原文。
- 数据：`data/ab/char_sheets/frames/`、`data/ab/identity/frames_sheet/`；接触印样 `data/ab/char_sheets/frames/contact_locked_E_R.jpg`，三列依次是定稿、E、R。

**结果**（ArcFace 余弦。男角参考 = 本轮设定图左栏脸；定稿里的男角本来就没有身份，所以只作对照）

| 镜 | 林晚：定稿 → E → R | 顾沉 / 陈宇：定稿 → E → R |
|---|---|---|
| S1 | 0.575 → 0.674 → **0.706** | — |
| S2 | 0.422 → 0.476 → **0.579** | 顾沉 0.35 → 0.28 → **0.430** |
| S8 | 0.448 → **0.505** → 0.494 | 顾沉 0.29 → 0.32 → **0.571** |
| S9 | 背影 → 0.414 → 0.288（62 px 小脸） | 陈宇 0.50 → 0.43 → **0.561** |

**观感**（看了印样）：

1. **E 太保守。** 画面和定稿几乎一样，林晚只小幅变像（+0.05～+0.10），男角的脸基本没换（顾沉 0.28 / 0.32）。Qwen-Image 2.1 在"保持底图"的指令下，身份替换很弱。
2. **R 身份最好。** 林晚 S1 / S2 分别涨到 0.706 / 0.579；顾沉一眼就是设定图那个人，S8 到 0.571。
3. **R 有两个新问题：**
   - **服装被设定图带过来。** S2 林晚换成了设定图的粉色裙 + 草莓项链；S9 陈宇变成背心，林晚身上也被带偏。提示词写了"不要复制服装"，没用。
   - 构图要重新审。
4. **结论：要出"本集造型版设定图"。** 用项目方第三种模板（角色 + 姿势 + 服装图），给每集每个造型单独出一张，R 就不会再带错衣服。另一个办法是只给左栏脸部裁剪当参考（backlog B4）。
5. **男角设定图区分度不够：**
   - 一张随机男性脸对陈宇设定图也有 0.47–0.50（S2 / S8 定稿）。
   - 顾沉和陈宇两张设定图互相余弦 0.55。
   - 所以光靠"对设定图 ≥0.5"判男角身份不够，必须同时满足"对自己 > 对另一个男角 + 0.1"（见 §6）。

### 5.3 视频后处理：H3 角色替换

**设置**

- 脚本 `tools/ab/consist_swap.py`，记录在 `data/ab/consist_swap/runs.jsonl`。
- 配方照 akatz 模型卡：Ref2VA int8 + swap LoRA 1.0 + FL2V Turbo 8step v1.0 1.0，8 步，er_sde / normal，cfg 1，shift 6/3。
- 源视频：ep02 S1 现行 base24 版（林晚脸从 0.55 漂到 0.17），作为 `<Video 1>`。
- 显存：
  - 768×1344×192 帧 + 参考视频 + 参考音轨：**3090 OOM**（已占 20.2 GB，还要再申请 5.0 GB）。
  - 只把输出降到 544×960 也 OOM（19.7 GB + 5.2 GB）。
  - **最后能跑的配置**：参考视频截成 124 帧、缩到 544×960，不接参考音轨，输出 544×960×124。每条约 9.5 分钟（GPU0）。

**结果**（同时段对比：源视频前 124 帧，林晚中位 0.329，最低 0.181）

| 变体 | `<Picture 1>` | 林晚 均值 / 中位 / 最低 | 观感（`data/ab/consist_swap/*.jpg`） |
|---|---|---|---|
| v1.5 | 设定图整栏（脸 + 上身 + 粉裙） | 0.393 / **0.407** / 0.161 | 动作、构图、机位完全保留；但**整套服装换成了设定图的粉裙 + 项链**，发色变浅 |
| pro4500 | 同上 | 0.371 / 0.341 / 0.165 | 同上，身份更弱 |
| v1.5 | 只裁头部（不带衣服） | 0.371 / 0.295 / 0.151 | 服装保留；身份没有提升 |

**结论**

- 角色替换 LoRA 换的是"整个角色"，衣服跟着参考图走。只给头部时，身份又换不进去。
- 再加上 3090 只能跑 544p、5 秒以内的段落，**现在不作为生产手段**。
- 将来如果有"本集造型版设定图"（衣服正确），整栏参考也许可行，见 backlog B5。
- 注意：S1 后半段林晚转成侧脸，ArcFace 对侧脸天然偏低；544p 的脸也更小。所以这组数字对 swap 偏不利，B16 会做朝向过滤后重算。

---

## 6. 推荐方案和建议写进 config 的参数（只是建议，没改）

按"每层都量化"的思路，分三层。

**第 1 层：身份资产（项目方闸门）**

1. 每个角色一张"定妆设定图"，用项目方 Qwen-Image 2.1 四栏流程，从 `data/ab/char_sheets/` 的候选里由项目方挑。
2. 每集每个造型再出一张"造型版设定图"：用第三种模板（角色 + 姿势 + 服装图），衣服按剧本造型。
3. 男角外貌区分度由写作方 / 项目方补字段，Claude 不自创外貌。

**第 2 层：首帧**

4. 首帧改用"设定图参考出图"（§5.2 的 R 方式），不再纯文字出图。
5. 参数建议（不改 config 时，可以先作为 `image_presets` 里的一个新预设试用）：

```json
{
  "id": "qi21_sheet_ref",
  "label": "设定图参考出图（CONSIST 建议）",
  "tier": "preview",
  "params": {
    "unet": "qwen_image_2.1_int8_convrot.safetensors",
    "steps": 25, "cfg": 1.0, "sampler": "euler", "scheduler": "simple",
    "vae": "qwen_image_2.1_vae_bf16.safetensors",
    "width": 768, "height": 1344,
    "loras": [{"name": "QI2.1_AnyAngle.safetensors", "strength": 0.6}],
    "identity_lora": null,
    "text_encoder": "TextEncodeQwenImage21",
    "ref_resolution": 1024,
    "refs": "@cast_sheets",
    "prompt_prefix": "<imageN> is the character reference sheet of <角色>…; use the sheets only for identity…"
  },
  "note": "林晚首帧 0.575→0.706（S1）、0.422→0.579（S2）；顾沉 0.43/0.57，陈宇 0.56（data/ab/identity/frames_sheet）。用定妆设定图时服装会被带过来，必须用造型版设定图",
  "src": "docs/ep02_iter/consistency_research.md §5.2"
}
```

6. 先不挂 lin_wan_qi_v1：同一流程里挂了它，身份 0.926 → 0.823（R2）。等 B9 用设定图重训以后，再做 A/B。

**第 3 层：视频，加身份闸门**

7. 视频配方暂时照 RR 定的 official_base 24 步 + 只给首帧。Ref2VA 等 LAB 的 X2 结果再定。
8. 新增视频身份闸门：建议加到 `config/render_quality.json`，或者 `packages/qc/ns_qc/thresholds.py` 的新条目。阈值要等 B15 用本角色数据标定后才能锁定，现在是暂定值：

```json
"identity_qc": {
  "metric": "arcface_w600k_r50 (tools/identity_metric.py)",
  "fps": 4, "min_face_px": 48,
  "ref": "每角色定妆设定图左栏脸",
  "pass_median": 0.50,
  "warn_median": 0.40,
  "fail_median": 0.30,
  "min_frame_floor": 0.30,
  "male_margin": 0.10,
  "note": "male_margin：男角对自己设定图的余弦须比对另一男角高 0.10，否则判“分不清”；不合格 → 换 seed 重出或走 Ref2VA，不自动放行"
}
```

9. 现在 review.py 的 SFace 人物检查（Q-D1 ≥0.30）按发色归人，S9 / S10 的数字无效。建议改成调用 identity_metric，按参考归属判人（B14）。

**现在不建议采用**：H3 角色替换 LoRA（§5.3）、Wan 生态换底模、ReActor（会拦成人镜头，逐帧闪烁）。

---

## 7. 项目方选定与登记（2026-10-31 晚）

项目方原话（经总调度 AskUserQuestion）："林晚A-s202 顾沉s101 陈宇s202脸"。

**登记**：走系统已有的资产参考图接口 `POST /api/assets/{id}/refs`，role=identity，note 里写了 by=owner 和项目方原话。没有改 config。

| 角色 | ref_id | 内容 | 说明 |
|---|---|---|---|
| 林晚 | ar-f9519334bc | 设定图 A-s202 整张 | **新增**；定妆脸 `lin_wan.png` / `config/face_reference.json` 不变；整张里有粉裙和项链 |
| 顾沉 | ar-b4e17a82d0 | 设定图 T-s101 整张 | 旧的 ar-98f7c63570 早已作废 |
| 陈宇 | ar-bc97a45f2a | s202 左栏脸部裁切 | 设定图的身体被人台污染，不能用 |

**Ref2VA 用的脸部裁切**

- 位置：`data/assets/identity_refs/<角色>/<角色>_face_ref2va.png`；清单和 sha256 在 `data/assets/identity_refs/manifest.json`。
- 裁法：YuNet 找左栏最大的脸框，向上扩 0.75 个脸高（包住发顶），向下只到下巴，所以不带领口和项链；宽 = 高 × 1.05。脚本 `tools/ab/crop_identity_refs.py`。
- ArcFace 校验：

| 角色 | 裁切对设定图（3 个视角平均） | 其他对照 |
|---|---|---|
| 林晚 | 0.883 | 对定妆 0.901 |
| 顾沉 | 0.822 | 对陈宇 0.369 |
| 陈宇 | 0.843 | 对顾沉 0.386 |

男角用多视角平均后能分开（互相 0.43；单看左栏时是 0.55）。

**造型版设定图**（项目方第三种模板）

- 位置：`data/ab/char_sheets/outfit/`。候选，不是当前定妆。
- 参考：服装取资产库已有的单品图——漆皮超短裙 lw-o09、12cm 透明细跟 lw-s01、顾沉西装外套 lw-o21；"黑色修身长袖上衣"没有单品图，按剧本原词写进提示词。
- 跑在 gpu36 GPU1。用到的 QI2.1_AnyAngle 是从 HF lilylilith/QI_2.1_AnyAngle 下载的，sha256 e4d7a0d4… 与 gpu33 上的副本一致。
- 结果（ArcFace 取左栏大脸，`data/ab/identity/outfit`）：

| 候选 | 对定妆 | 对裁切 | 观感 |
|---|---|---|---|
| `lin_wan_ep02_L1office_img1sheetA202_s301` | 0.867 | 0.948 | 黑长袖、漆皮超短裙、透明细跟都对；没有项链；头发及腰；**推荐** |
| `lin_wan_ep02_L1office_img1facecrop_s301` | 0.871 | 0.948 | 服装对，但头发变短到胸口（裁切图看不到发长） |

- 正侧面那栏的脸只有 0.19–0.26，这是 ArcFace 对纯侧脸的正常表现，不代表换了人。
- 外套披肩版（5 张参考，参考分辨率 2048）在 gpu36 GPU1 上 OOM。降到 1024 重试时，planB 已经把这张卡排满，我把自己的任务从队列里删了，这一版没出（backlog B4c）。
- 顾沉：s101 已经是剧本 ep02 的"黑色高定衬衫"造型，暂不另出。
- 陈宇：被描述卡住，缺的内容见 backlog B3a。

**陈宇造型版**（写作方 W7 补全后，2026-10-31 21:00，gpu36 GPU0 空闲时出）

- 候选：`data/ab/char_sheets/outfit/chen_yu_ep02_W7casual_img1facecrop_s401.png`。
  - `<image1>` 是 s202 的脸部裁切，`<image2>` 是姿势模板。
  - 服装、体型、发型照 W7 英文原文写进提示词（W7 状态是待导入）。
- 观感：浅灰落肩卫衣、深灰蓝抽绳直筒裤、白帆布鞋、左腕黑表都对；四个视角一致；人台的皮肤和内衣没有再渗进来。
- ArcFace（参考 = 陈宇裁切）：
  - 左栏大脸 0.863，对顾沉 0.366，能分开；
  - 正面全身那栏的小脸 0.519；
  - 侧面 0.332，是侧脸的正常偏低。
- seed 402 和林晚外套版由后台脚本等空卡后接着出。
