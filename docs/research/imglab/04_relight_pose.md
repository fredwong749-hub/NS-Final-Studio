# IMGLAB 04：重打光/融合 与 Pose/景别控制 深度调研

- 日期：2026-11-02
- 调研范围：写实短剧出图链路（主模型 Qwen-Image 2.1 Turbo；ComfyUI；RTX 3090 24GB）
- 方法：逐一读 GitHub README、HuggingFace 模型卡、ComfyUI 官方文档与 wiki、Reddit 帖（经 reddit.sentinel-team.org 快照）。每条结论带英文原文引用、链接、置信度。
- 置信度含义：高=官方一手原文；中=官方原文但信息不全，或可信二手来源；低=单条社区帖或推断。"设计推断"表示没有外部来源，是本文的工程建议。
- 本文只做调研：没有下载，没有改其他文件。

---

## 0. 摘要（10 条）

1. **许可证红线（最重要）**：主模型 Qwen-Image 2.1 / 2.1 Turbo 用的是 **Qwen Research License**，不是 Apache。阿里 PAI 的 2.1 Fun ControlNet Union 同样是 qwen-research。商用要另找 Qwen 签授权。相比之下，Qwen-Image（20B）、Qwen-Image-Edit-2509 和 Edit-2511 都是 Apache-2.0。需要总调度定性：项目算不算商用。
2. **生态不兼容**：现有大部分 relight LoRA 和 pose ControlNet 都是给 **Qwen-Image 20B 或 Qwen-Image-Edit-2509/2511** 训的，包括 dx8152 Light-Migration/Relight、InstantX Union、DiffSynth Union LoRA。Qwen-Image 2.1 是 **7B** 新架构，这些权重原则上不能直接挂上去。2.1 上目前查到的官方 pose 控制只有 `alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union`（约 7GB）。
3. **"像 PS 贴上去"的根治办法：别再把人像合成到场景图上，改成一次生成或用 Edit 模型把人放进场景。** 两条路：
   - 2.1 自带多参考图（官方写 "Support up to 10 reference images"），可以把场景母版和人物参考一起喂进去，一次出图。
   - Qwen-Image-Edit-2509/2511 支持 "person + scene" 多图输入，2511 还写着 "Realistic lighting control is now achievable out-of-the-box"。
4. **如果保留合成，后处理重打光首选**：
   - dx8152/Qwen-Edit-2509-Light-Migration（Apache-2.0）：图 2 的光照和色调迁移到图 1。
   - jasperai/LBM_relighting：一步出图、前景按背景重打光，ComfyUI 有 kijai 的 LBMWrapper。但许可是 **CC BY-NC 4.0**，非商用。
5. **IC-Light v1（SD1.5 fc/fbc）**：代码 Apache-2.0，ComfyUI 有 kijai 的节点。但它基于 SD1.5，写实细节和分辨率跟 Qwen 系差一大截，只适合当光照粗稿或做对比基线。**IC-Light v2（Flux）没开权重**，作者原话是 "the license will be non-commercial only"。
6. **传统颜色迁移**（KJNodes 的 ColorMatch，底层 color-matcher：Reinhard/MKL/MVGD/HM 组合，GPL-3.0）便宜稳定，能修色温和整体亮度，**修不了光照方向和阴影**。只能当最后一道。Harmonizer 是 CC BY-NC-SA 4.0，非商用；PCT-Net 是 MPL-2.0，可商用，但只做颜色协调。
7. **合成感自动指标**：学术上有阴影和光源方向几何一致性（Farid 系列；"Shadows Don't Lie" CVPR 2024），但没有现成可用于我们闸门的开源工具。建议自研轻量指标：人物与背景的色温差和亮度差、人物边缘 halo 带梯度、人物脚下接触阴影的有无。见 A4。
8. **Pose 提取用 DWPose**：IDEA-Research/DWPose 和 yzd-v/DWPose 权重都是 Apache-2.0，yolox_l.onnx 217MB + dw-ll_ucoco_384.onnx 134MB，comfyui_controlnet_aux 也是 Apache-2.0。**避免 OpenPose 原版**：CMU 许可是 "NONCOMMERCIAL RESEARCH USE ONLY"。controlnet_aux 里的 OpenPose 预处理器用的 body_pose_model.pth 是从 CMU caffemodel 直接转换来的，许可同样有风险。
9. **景别退档的主因是 pose 模板画法不对，不是控制强度不够。** 中景模板必须把膝盖以下的关键点放到画布外面（截断骨架），并让头顶到胯的跨度占画面高度的大约 85%。如果把整个人缩小画在画布里，模型就会出全景；如果骨架只有头肩，就会出近景。按景别做"带截断的骨架模板库"，再用 DWPose 对出图做反向判定，就能形成景别闸门。规则见 B3（设计推断）。
10. **控制强度怎么取舍**：InstantX Union（Qwen-Image 20B）官方建议 conditioning_scale 0.8–1.0；2.1 Fun Union 官方写 "control_context_scale = 1.0 is the value the adapter expects"。社区普遍做法是把 end_percent 降到大约 0.8，让最后几步自由补细节，以减少塑料感（来源是二手教程，置信度低）。Qwen Edit 2511 拿 DWPose 图改姿势，社区反馈是 "still not super reliable"。

---

## A. 重打光 / 融合 详述

### A1. IC-Light（lllyasviel）

| 项 | 内容 | 引用 | 链接 | 置信度 |
|---|---|---|---|---|
| 模型 | fc：文本+前景条件，默认模型 | "The default relighting model, conditioned on text and foreground. You can use initial latent to influence the relighting." | https://github.com/lllyasviel/IC-Light | 高 |
| 模型 | fbc：文本+前景+背景条件，**最适合我们"人物+场景"的场景** | "Relighting model conditioned with text, foreground, and background." | 同上 | 高 |
| 模型 | fcon：带 offset noise 训练，用户研究里略逊于 fc | "trained with offset noise" | 同上 | 高 |
| 原理 | HDR 空间里光传输相互独立，训练时强加了一致性约束 | "In HDR space, illumination has a property that all light transports are independent." / "We imposed such consistency (using MLPs in latent space) when training the relighting models." | https://raw.githubusercontent.com/lllyasviel/IC-Light/main/README.md | 高 |
| 提示词 | fbc 不需要精细提示 | "The background conditioned model does not require careful prompting." | 同上 | 高 |
| 许可 | 仓库 Apache-2.0；**但它默认的抠图 BRIA RMBG 1.4 是非商用** | "the original BRIA RMBG 1.4 is for non-commercial use. If you use IC-Light in commercial projects, replace it with other background replacer like BiRefNet." | https://github.com/lllyasviel/IC-Light | 高 |
| 底模 | SD1.5（文件名就是 iclight_sd15_*） | 文件名 iclight_sd15_fc.safetensors 等 | 同上 | 高 |
| 局限 | README 没有局限章节。推断：SD1.5 底模，输出要再走一遍 Qwen 低去噪重绘，否则写实度和脸部 ID 会掉 | — | — | 设计推断 |
| v2（Flux） | **没开权重**，只能用 HF Space 或 fal.ai API；作者声明非商用 | "More inference codes and weights may be released later." / "You can only use the hf space to test for now." / "However, unlike V1, the license will be non-commercial only." | https://github.com/lllyasviel/IC-Light/discussions/98 | 高（截至该帖；没查到后续开权重的公告） |
| ComfyUI | kijai/ComfyUI-IC-Light，Apache-2.0，用 Manager 安装；模型放 models/unet/IC-Light | "Recommended way is to use the manager. There should be no extra requirements needed." / "By default they go to `ComfyUI/models/unet/IC-Light`" / "Some of the example workflows require the very latest features in KJNodes" | https://github.com/kijai/ComfyUI-IC-Light | 高 |
| ComfyUI 局限 | README 没写局限，也没提 SDXL/Flux 支持 | 未查到 | 同上 | — |
| 3090 | SD1.5 体量，3090 很轻松（推断，没查到官方显存数据） | 未查到 | — | 设计推断 |

### A2. DiT 上的重打光

#### A2.1 Qwen-Image-Edit 系 LoRA（dx8152 等）

| 模型 | 要点 | 原文 | 链接 | 置信度 |
|---|---|---|---|---|
| **dx8152/Qwen-Edit-2509-Light-Migration** | Apache-2.0；输入"待改图 + 光照参考图"，把参考图的光照和色调迁移过去。**跟我们"人物贴到场景母版后统一光照"的需求最对口** | "License: apache-2.0"；"It's the first to solve the problem of Qwen-Edit-2509's inability to perform secondary lighting"；默认提示词 "参考色调，移除图1原有的光照并参考图2的光照和色调对图1重新照明"；作者认为配 Lightning 的 Edit 版效果更好 | https://huggingface.co/dx8152/Qwen-Edit-2509-Light-Migration | 高（功能描述）/ 低（效果没有基准，只有作者主观评价） |
| **dx8152/Qwen-Image-Edit-2509-Relight** | Apache-2.0；用文字描述光照来重打光；文件 Qwen-Edit-Relight.safetensors；需配 lightx2v Lightning LoRA | 触发词 "重新照明"；示例 "重新照明,使用窗帘透光（柔和漫射）的光线对图片进行重新照明"；"You also need this lora and use them together" | https://huggingface.co/dx8152/Qwen-Image-Edit-2509-Relight | 高 |
| Light-Migration 在线 Demo | multimodalart 做的 Space | — | https://huggingface.co/spaces/multimodalart/Qwen-Image-Light-Migration | 中 |
| **Qwen-Image-Edit-2511 本体** | Apache-2.0；**已经把热门的光照 LoRA 并进底模**；多人合影一致性有增强 | "Qwen-Image-Edit-2511 integrates selected popular LoRAs directly into the base model" / "Realistic lighting control is now achievable out-of-the-box." / "high-fidelity fusion of two separate person images into a coherent group shot" | https://huggingface.co/Qwen/Qwen-Image-Edit-2511 | 高 |
| QIE-2511-Studio-DeLight | Apache-2.0；去掉原有光照，换成均匀棚拍光。可以用作"人物参考图先去光，再交给 Light-Migration 打新光"的前置步骤 | 触发 "Neutral uniform lighting Preserve identity and composition"；base "Qwen/Qwen-Image-Edit-2511" | https://huggingface.co/mario-d-robot/QIE-2511-Studio-DeLight | 高 |
| LightingRemap Alpha（zooeyy） | 在画面边缘涂色块来指定光源方向和颜色，模型据此重打光并擦掉色块；alpha 版，色块"may not be fully erased" | "solid color blocks near the edge of an image" | https://hapticpaper.github.io/learning_gallery/models/2026-01-17--lightingremap-alpha ；权重 https://huggingface.co/zooeyy/Qwen-Edit-2511_LightingRemap_Alpha0.2 | 中（许可：未查到） |
| 社区：2509 配 Lightning 出坏图 | 更新 ComfyUI 后修好；2511 改单个元素时比 2509 更容易连带改动整个场景 | （帖子摘要，没取到逐字原文） | https://huggingface.co/lightx2v/Qwen-Image-Lightning/discussions/21 | 低 |
| 社区：给保留区域迁移新环境光 | r/comfyui 网友推荐用 Qwen Image Edit / Flux2 Klein / relight LoRA | u/K0owa: "Yes with a relight Lora."；u/jj4379: "Klein does this easy as pie" | https://reddit.sentinel-team.org/posts/1sxuj17/snapshots/2026-05-02T01%3A14%3A58.433553Z | 低 |

**兼容性警告（设计推断，置信度中高）**：上面这些 LoRA 的 base 都是 Qwen-Image-Edit-2509/2511（底模 20B MMDiT。ComfyUI 文档原文："It's a 20B parameter MMDiT ... open-sourced under the Apache 2.0 license"，https://docs.comfy.org/tutorials/image/qwen/qwen-image ）。Qwen-Image-2.1-Turbo 的模型卡写的是 "7B params"（https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo ），**架构不同，LoRA 不能互挂**。可行方案是在 3090 上另起一个 Edit-2509/2511 的重打光后处理节点，fp8 约 20.4GB，要配合 offload，见方案总表。

#### A2.2 Flux Kontext relight

| 项 | 内容 | 链接 | 置信度 |
|---|---|---|---|
| kontext-community/relighting-kontext-dev-lora-v3 | 许可写的是 "License: other"（Flux.1 Kontext dev 本身是非商用许可）；训练集很小："trained on a dataset of 30 synthetically relighted pairs of images"；模型卡没给提示词模板 | https://huggingface.co/kontext-community/relighting-kontext-dev-lora-v3 | 高 |
| Space 代码 | 用 guidance 2.5、LoRA 权重 1.0，用户提示词外面套了固定的光照模板 | https://huggingface.co/spaces/kontext-community/kontext-relight | 中 |
| 结论 | 要多装一套 Flux 底模、许可非商用、训练数据少，**不推荐** | — | 设计推断 |

#### A2.3 LBM relighting（jasperai）

| 项 | 内容 | 原文 | 链接 | 置信度 |
|---|---|---|---|---|
| 功能 | 按给定背景给前景重打光，一步采样 | "This model was trained to relight a foreground object according to a provided background." / `evaluate(model, source_image, num_sampling_steps=1)` | https://huggingface.co/jasperai/LBM_relighting | 高 |
| 底模/大小 | SDXL finetune，约 3B 参数，BF16 | "3B params" | 同上 | 高 |
| 许可 | **CC BY-NC 4.0，非商用** | "This code is released under the Creative Commons BY-NC 4.0 license." | 同上 | 高 |
| ComfyUI | kijai 的 LBMWrapper；模型改名为 LBM_relighting.safetensors 放进 models/diffusion_models；用 ImageCompositeMasked 摆放人物 XY 位置 | （二手教程） | https://comfyui-wiki.com/en/tutorial/advanced/image/relighting/lbm-relighting | 中 |
| 分辨率 | 模型卡没写 | 未查到 | — | — |
| 3090 | 3B、一步采样，速度应该很快（推断） | 未查到官方数据 | — | 设计推断 |

#### A2.4 学术方案（都没开源，或没查到开源）

| 方案 | 要点 | 开源 | 链接 | 置信度 |
|---|---|---|---|---|
| SynthLight（CVPR 2025，Yale + Adobe） | 基于 SD，用 Blender 合成的人头数据训练，按环境贴图重打光人像 | 项目页**没有代码或权重链接** | https://vrroom.github.io/synthlight/ ；https://arxiv.org/abs/2501.09756 | 高（没开源） |
| Relightful Harmonization（CVPR 2024，Adobe） | 光照感知的人像换背景扩散模型。原文 "a lighting-aware diffusion model designed to seamlessly harmonize sophisticated lighting effect"；指出传统方法 "often only focus on adjusting the global color and brightness of the foreground" | arXiv 页**没有代码链接** | https://arxiv.org/abs/2312.06886 | 高（没开源） |
| "Lumina" | 没查到同名的重打光项目。相近的有 LumiNet（CVPR 2025，室内场景重打光，项目页 https://luminet-relight.github.io ，没确认开源）和 UniLumos（https://github.com/alibaba-damo-academy/Lumos-Custom ） | LumiNet 没确认；UniLumos 有仓库 | 见左 | 低（UniLumos 的许可和质量都没核实） |

**对我们的意义**：Relightful Harmonization 那句原文点明了核心问题：颜色协调只修整体色彩和亮度，修不了光照方向。所以颜色迁移类方案只能当最后一道。

### A3. 前景背景协调（harmonization）与"一次生成"替代方案

#### A3.1 传统颜色迁移

| 方案 | 要点 | 原文 | 链接 | 许可 | 置信度 |
|---|---|---|---|---|---|
| KJNodes ColorMatch | 底层是 color-matcher；方法有 Reinhard / MKL / MVGD / HM 组合；有 strength 参数 | "The methods behind the mappings are based on the approach from Reinhard et al., the Monge-Kantorovich Linearization (MKL) as proposed by Pitie et al. and our analytical solution to a Multi-Variate Gaussian Distribution (MVGD) transfer in conjunction with classical histogram matching. As shown below our HM-MVGD-HM compound outperforms existing methods."；函数签名 `colormatch(self, image_ref, image_target, method, strength=1.0, ...)` | https://github.com/kijai/ComfyUI-KJNodes （nodes/image_nodes.py） | KJNodes GPL-3.0；color-matcher GPL-3.0 | 高 |
| 用法建议 | 只对人物 mask 区域做 ColorMatch，参考图取人物周边的背景环带；strength 0.3–0.6，防止脸色发灰 | — | — | — | 设计推断 |
| 局限 | 只改颜色统计量，改不了光照方向和阴影 | 同上方 Relightful Harmonization 原文 | — | — | 高 |

#### A3.2 学习型 harmonization

| 方案 | 要点 | 原文 | 链接 | 许可 | 置信度 |
|---|---|---|---|---|---|
| Harmonizer | 20MB 小模型，最高 8K，1080p 在 GPU 上实时；用 iHarmony4 训练 | "a lightweight (20MB) model enabled image/video harmonization up to 8K resolution" / "With GPUs, Harmonizer has real-time performance at Full HD resolution." | https://github.com/ZHKKKe/Harmonizer | **CC BY-NC-SA 4.0（非商用）** | 高 |
| PCT-Net（CVPR 2023，乐天） | 全分辨率逐像素颜色变换；iHarmony4 | "Full Resolution Image Harmonization Using Pixel-Wise Color Transformations" | https://github.com/rakutentech/PCT-Net-Image-Harmonization | MPL-2.0（可商用，修改过的文件要开源） | 高 |
| ComfyUI-PIH | 基于 "Semi-supervised Parametric Real-world Image Harmonization"；输入背景 + 前景 + mask | （RunComfy/ComfyAI 页面描述） | https://comfyai.run/custom_node/ComfyUI-PIH | 未查到 | 中 |
| ComfyUI 里的 PCT-Net / Harmonizer 节点 | 没查到 | 未查到 | — | — | — |

#### A3.3 "一次生成人物 + 场景"替代合成（**推荐主路线**）

| 方案 | 要点 | 原文 | 链接 | 许可 | 置信度 |
|---|---|---|---|---|---|
| Qwen-Image 2.1（含 Turbo）多参考 | 一个模型同时做文生图和编辑；最多 10 张参考图；Turbo 有 "Multi-Reference Composition" 示例 | "Support up to 10 reference images."；Turbo："text-to-image generation and image editing"，"8 denoising steps"，"CFG=1 by default" | https://huggingface.co/Qwen/Qwen-Image-2.1 ；https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo | **Qwen Research License** | 高 |
| Qwen-Image-Edit-2509 多图 | 支持 "person + scene"，1–3 张图效果最好；原生支持关键点图 | "Optimal performance is currently achieved with 1 to 3 input images." / "Native Support for ControlNet" | https://huggingface.co/Qwen/Qwen-Image-Edit-2509 | Apache-2.0 | 高 |
| Qwen-Image-Edit-2511 | 光照控制已并进底模，多人融合更强 | 见 A2.1 | https://huggingface.co/Qwen/Qwen-Image-Edit-2511 | Apache-2.0 | 高 |
| 建议流程 | 场景母版作为图 2，人物身份参考作为图 1，必要时加 pose 骨架作为图 3。提示词写清人物在场景里的位置、景别、光源方向（例如"窗光从画面左侧打来"）。出图后跑 A4 的合成感闸门；不过的再走 Light-Migration 后处理 | — | — | — | 设计推断（需实测） |

### A4. 合成感的自动评估指标

| 项 | 内容 | 原文 | 链接 | 置信度 |
|---|---|---|---|---|
| 阴影几何一致性（Kee/O'Brien/Farid） | 阴影上的点和投射它的物体点连线，应该汇聚到同一个光源投影点 | "Since light travels in a straight line, a point on the shadow can be tied back to its object" | https://farid.berkeley.edu/downloads/publications/tog14.pdf | 高（方法本身）；需要人工标注点对，不能直接自动化 |
| 低维光照环境估计（WIFS 2010） | 从单图估计 3D 光照低维模型，前景和背景估计结果不一致就判为篡改 | （摘要描述） | https://farid.berkeley.edu/downloads/publications/wifs10.pdf | 中 |
| 眼睛高光 | 用双眼角膜高光估计光源方向，做假设检验 | （摘要描述） | https://www.ic.unicamp.br/~tjose/publications/2011-eye-specular-highlights-forensics-camera-ready.pdf | 中 |
| Shadows Don't Lie（CVPR 2024） | 生成模型不懂射影几何，可以用"物体—阴影关系"分类器识别生成图 | "Generative Models don't know Projective Geometry...for now" | https://arxiv.org/abs/2311.17138 ；https://projective-geometry.github.io | 高（论文）；代码和权重能否直接用：未查到 |
| 人眼局限 | 人很难察觉投射阴影不一致，所以需要自动指标 | （检索摘要） | 同 Farid | 中 |
| **我们可落地的闸门指标**（全部是设计推断） | ① **色温/白平衡差**：人物 mask 内和外圈环带（向外扩 5–10% 的背景带）在 LAB 空间比较 a/b 均值差，阈值待实测。② **亮度和对比度差**：L 通道均值、标准差之比。③ **边缘 halo**：mask 边界内外 3–6px 的环带算亮度梯度峰值，以及边界像素和背景的色差（PS 贴图特有的亮边或暗边）。④ **接触阴影**：人物脚底或座位接触区下方 10–20px 的亮度应低于周围背景，中景以上看不到脚时跳过。⑤ **光照方向粗估**：脸部左右半边亮度比，跟背景亮度梯度方向（大尺度 Sobel 主方向）比符号是否一致。⑥ 兜底用 VLM 审片问"光照方向是否一致、是否像合成"。 | — | — | 设计推断，需实测标定阈值 |

---

## B. Pose / 构图 / 景别 详述

### B1. Pose 提取与模板库

| 项 | 内容 | 原文 | 链接 | 置信度 |
|---|---|---|---|---|
| DWPose 许可 | Apache-2.0 | "Apache-2.0 license" | https://github.com/IDEA-Research/DWPose | 高 |
| DWPose 权重 | yzd-v/DWPose：yolox_l.onnx **217MB**，dw-ll_ucoco_384.onnx **134MB**（还有 pth 版本，最大 407MB）；HF 许可 apache-2.0 | 文件列表 | https://huggingface.co/yzd-v/DWPose/tree/main | 高 |
| DWPose 精度 | DWPose-l 384x288：Whole AP 0.665，10.1 GFLOPS | 表格 | https://github.com/IDEA-Research/DWPose | 高 |
| DWPose ONNX | 不需要 mmcv | "We release a new DWPose with onnx. You can avoid installing mmcv through this." | 同上 | 高 |
| comfyui_controlnet_aux | Apache-2.0；DWPreprocessor 可选 TorchScript 或 ONNXRuntime 加速；能输出 OpenPose 格式 JSON（POSE_KEYPOINT） | "There are two ways to speed-up DWPose: using TorchScript checkpoints (.torchscript.pt) checkpoints or ONNXRuntime (.onnx)." / "bbox_detector: Either yzd-v/DWPose/yolox_l.onnx" / "pose_estimator: Either yzd-v/DWPose/dw-ll_ucoco_384.onnx" / "An array of OpenPose-format JSON corresponsding to each frame in an IMAGE batch" | https://github.com/Fannovel16/comfyui_controlnet_aux | 高 |
| onnxruntime-gpu 坑 | NVIDIA 上 ONNX 加速原文写的是只在 CUDA 11.8 下可用，CUDA 12 要用额外 index 装的版本 | "this method currently can only works on CUDA 11.8" | 同上 | 高（版本可能已经过时，需实测） |
| **OpenPose 原版许可** | **CMU：非商用研究专用** | "a personal, non-exclusive, non-transferable license to use the Software for noncommercial research purposes" / "ACADEMIC OR NON-PROFIT ORGANIZATION NONCOMMERCIAL RESEARCH USE ONLY" | https://github.com/CMU-Perceptual-Computing-Lab/openpose/blob/master/LICENSE | 高 |
| controlnet_aux 的 OpenPose 预处理器权重 | lllyasviel/Annotators 里的 body_pose_model.pth（209MB）、hand_pose_model.pth（147MB），HF 许可标的是 "other"。来源是 Hzzone/pytorch-openpose，原文 "the pytorch model is directly converted from openpose caffemodel by caffemodel2pytorch"，**所以继承了 CMU 权重的许可风险** | 见左 | https://huggingface.co/lllyasviel/Annotators/tree/main ；https://github.com/Hzzone/pytorch-openpose | 高（来源）/ 中（法律定性需要法务） |
| 结论 | **提取一律用 DWPreprocessor（DWPose），禁用 OpenPosePreprocessor** | — | — | 高 |
| 2D 编辑器 | huchenlei/ComfyUI-openpose-editor（GPL-3.0）：读 POSE_KEYPOINT JSON → 编辑 → "Send pose to ControlNet"；依赖 controlnet_aux | "Use pose estimator node to obtain `POSE_KEYPOINT` JSON." | https://github.com/huchenlei/ComfyUI-openpose-editor | 高 |
| 其他 2D 编辑器 | space-nuko/comfyui-openpose-editor（只有 2D）；judian17/ComfyUI-OpenPose-Editor-jd（增加了 pose 存取节点） | （检索摘要） | https://github.com/space-nuko/comfyui-openpose-editor ；https://github.com/judian17/ComfyUI-OpenPose-Editor-jd | 中 |
| 3D 编辑器 | Havlight/ComfyUI-3D-OpenPose-Editor2026_IK：2D 和 3D 在一个节点，能导出相机状态和 2D 投影，还在开发中，许可未写；hinablue/ComfyUI_3dPoseEditor：较老（2024-08） | （检索摘要） | https://github.com/Havlight/ComfyUI-3D-OpenPose-Editor2026_IK ；https://gitee.com/lfjking/ComfyUI_3dPoseEditor | 中/低 |
| 社区替代 | r/StableDiffusion 有人推荐 "Vnccs pose studio and accompanying workflow" | 原文如左 | https://reddit.sentinel-team.org/posts/1umcn4a/snapshots/2026-07-03T17%3A57%3A26.35054Z | 低 |

**模板库建法（设计推断）**：

1. **来源**：从已经通过审片的成片，以及授权参考图里，用 DWPreprocessor 批量提取 POSE_KEYPOINT JSON 入库，不入原图，避免版权和身份泄露。字段：`shot_size`（ECU/CU/MCU/MS/MFS/FS/LS）、`action`（站、坐、走、回头、对视……）、`n_persons`、`facing`、`aspect`（9:16 或 16:9）、`source`。
2. **归一化**：坐标存成画布比例坐标 [0,1]。允许值小于 0 或大于 1，用来表示画外的关节，这是景别的关键。额外存 `head_top_y`、`chin_y`、`hip_y`、`knee_y`、`ankle_y` 等派生量。
3. **按景别定骨架的位置和尺度**（以竖屏 9:16、单人为例，数字是起点值，需实测）：

| 景别 | 画面下边界切在 | 头顶 y | 头高（头顶到下巴）/ 画面高 | 必须在画外的关键点 |
|---|---|---|---|---|
| ECU 大特写 | 眉到下巴之间 | <0 | >0.6 | 肩以下全部 |
| CU 特写 | 锁骨或肩上 | 0.05–0.10 | 0.35–0.5 | 肘、胯以下 |
| MCU 近景 | 胸口中部 | 0.06–0.12 | 0.2–0.3 | 胯、膝、踝 |
| MS 中景 | 腰或胯 | 0.06–0.12 | 0.12–0.18 | 膝、踝 |
| MFS 七分身 | 膝上或膝下 | 0.05–0.10 | 0.09–0.12 | 踝 |
| FS 全景 | 脚下留少量地面 | 0.05–0.12 | 0.06–0.09 | 无（踝必须在画内） |
| LS 远景 | 人物身高 < 画面高的 50% | — | <0.05 | 无 |

4. **画骨架时**：画外的关节直接不画；连到画外关节的骨骼线段延伸到画布边缘再截断。不要把关节"压"到画布边缘上，那会让模型以为肢体在那里折返。
5. **多人**：每个人分别按上表定尺度。正反打镜头里，前景人物可以比 MS 更近，让背影的肩部出画。

### B2. 在 Qwen 系上用 pose 驱动

| 方案 | 适用底模 | 要点 | 原文 | 链接 | 许可 | 置信度 |
|---|---|---|---|---|---|---|
| **alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union** | **Qwen-Image 2.1（跟我们主模型同族）** | 8 种控制含 Pose（DWPose 骨架）；约 7.0GB（磁盘 7.55GB）；官方样例都用 40 步、scale 1.0；ComfyUI 核心已合并（PR #16519，2026-09-28），节点链是 Load Model Patch → Apply Qwen Image DiffSynth ControlNet；没有官方工作流模板。**卡上没提 Turbo（8 步）兼容性** | "`1.0` is the strongest control (used for all results below)" / "`control_context_scale = 1.0` is the value the adapter expects" / "All samples below are generated with `num_inference_steps = 40`" / "keep both sides as multiples of 16 so the control map is not distorted" / "the transformer plus the Qwen3-VL text encoder do not fit a single consumer GPU fully loaded" | https://huggingface.co/alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union ；https://comfyui-wiki.com/ja/news/2026-09-24-qwen-image-2-1-fun-controlnet-union | **qwen-research** | 高（卡）/ 中（ComfyUI 合并信息来自 wiki） |
| InstantX/Qwen-Image-ControlNet-Union | Qwen-Image 20B（**不兼容 2.1**） | 支持 canny、soft edge、depth、pose；2B 参数；pose 建议用 DWPose，scale 0.8–1.0；30 步；ComfyUI 原生支持 | "supports 4 common control types (canny, soft edge, depth, pose)" / "set controlnet_conditioning_scale in [0.8, 1.0]" / "ComfyUI offers native support for Qwen-Image-ControlNet-Union." | https://huggingface.co/InstantX/Qwen-Image-ControlNet-Union | Apache-2.0 | 高 |
| DiffSynth In-Context Control Union LoRA | Qwen-Image 20B | ComfyUI 文档写着支持 "canny, depth, pose, lineart, softedge, normal, openpose"；文件 qwen_image_union_diffsynth_lora.safetensors 放 loras/ | "Image structure control LoRA supporting canny, depth, pose, lineart, softedge, normal, openpose." | https://docs.comfy.org/tutorials/image/qwen/qwen-image | 未查到（HF 卡返回 401） | 中 |
| DiffSynth Blockwise ControlNet | Qwen-Image 20B | 只有 Canny、Depth、Inpaint，**没有 pose** | 模型名列表 | https://github.com/modelscope/DiffSynth-Studio/blob/main/docs/en/Model_Details/Qwen-Image.md | 未查到 | 高 |
| Qwen-Image-Edit-2509 吃关键点图 | Edit-2509（20B） | 官方原生支持 keypoint map | "Native Support for ControlNet" / 包括 "depth maps, edge maps, keypoint maps" | https://huggingface.co/Qwen/Qwen-Image-Edit-2509 | Apache-2.0 | 高（声明）/ 低（实测效果） |
| 社区实测：Edit 2511 + DWPose 改姿势 | 2511 | 用 DWPose 骨架改姿势"works somewhat, but it's still not super reliable"；有人推荐 Klein 9B | "I find that it can be really hard to dial in a pose using just prompting." / "that works somewhat, but it's still not super reliable." | https://reddit.sentinel-team.org/posts/1umcn4a/snapshots/2026-07-03T17%3A57%3A26.35054Z | — | 低（单帖） |
| Qwen-Image 2.1 本体吃 pose 图 | 2.1 | 官方卡**没提 pose / keypoint / ControlNet** | 未查到 | https://huggingface.co/Qwen/Qwen-Image-2.1 | — | 高（确认没写） |

**强度和画质的取舍**：

- 官方推荐强度：InstantX 0.8–1.0；2.1 Fun Union 1.0。来源见上表，置信度高。
- 降低 end_percent：教程原文是让 "the final phase can refine details without constant pressure from the control map"，建议从 1.0 降到大约 0.8。https://eastondev.com/blog/en/posts/ai/20260719-comfyui-controlnet-guide/ ，置信度低，没有针对 Qwen 的实测。
- 设计推断：pose 只决定骨架和景别，不需要全程强控。建议实测网格为 scale ∈ {0.6, 0.8, 1.0} × end_percent ∈ {0.6, 0.8, 1.0}，看两个指标：B3 的景别闸门通过率，以及皮肤纹理和塑料感（现有写实审片打分）。
- Turbo 只有 8 步时，end_percent=0.8 相当于最后 1–2 步不受控，需实测。

### B3. 景别自动判定（闸门）

| 项 | 内容 | 链接 | 置信度 |
|---|---|---|---|
| 学术定义 | 景别按身体截断点定：全景 "barely includes the whole human body"，中景切在膝或腰附近，特写聚焦脸或手；近景（MCU）"frame a subject from mid-chest up" | https://arxiv.org/pdf/2008.03548v1.pdf （MovieShots/SGNet）；https://human.libretexts.org/Bookshelves/Theater%2C_Film%2C_and_Storytelling/Video_Production_Handbook/08%3A_Video_Aesthetics/8.01%3A_Basic_Shot_Sizes | 中 |
| 景别是连续量 | "Shot scales like 'close-up,' however, are determined by the relative size of the predominant figure in the image. And the relative size is continuous." | https://arxiv.org/pdf/2008.03548v1.pdf | 中 |
| 已有学习方法 | SGNet，在 46K 镜头的 MovieShots 数据集上训练（主体/背景双流） | 同上 | 中（权重能否直接用：未查到） |
| 基于关键点可见性的现成方法 | **未查到**。下面是自研规则 | — | — |

**自研闸门规则（设计推断，用 DWPose 133 点 COCO-WholeBody 或 18 点 body）**：

- 关键点"可见" = 置信度 ≥ 0.3，并且坐标在画面内留 2% 边距以内（阈值需实测）。
- 判定顺序：
  - 双踝可见，人物框高 / 画面高 ≥ 0.5 → **FS**；< 0.5 → **LS**
  - 膝可见、踝不可见 → **MFS**
  - 胯（hip）可见、膝不可见 → **MS**
  - 肘或胸中点可见、胯不可见 → **MCU**
  - 只有肩和脸 → **CU**；脸框高 / 画面高 > 0.5 或下巴出画 → **ECU**
- 辅助量：头高比（头顶到下巴 / 画面高；DWPose 没有头顶点，用 鼻—颈距离 × 系数 估算），用来区分同档内的松紧。
- 闸门：允许偏差 ±1 档时只告警；偏差 ≥ 2 档，或"要中景出近景"这种**往近退档**的情况直接打回，换 seed 或提高 pose 强度重出。
- 多人时取镜头主体（脸框最大，或分镜标注的主角）判定。
- 背影或侧脸：脸部点缺失时，用肩宽 / 画面宽替代头高比。
- 成本：DWPose 一张图在 GPU 上是亚秒级（推断），3090 无压力。

### B4. 可行性汇总（3090 / 速度 / 许可 / 权重）

见下节总表。

---

## 方案总表

| 方案 | 解决 | 底模 | 3090 可行性 | 速度 | 许可 | 权重来源/大小 | 推荐度 |
|---|---|---|---|---|---|---|---|
| Qwen-Image 2.1 Turbo 多参考一次生成（人物参考 + 场景母版） | A（根治） | 2.1 7B | 可行（7B BF16 约 14GB+文本编码器，要 offload；推断） | 8 步 | **qwen-research** | 已有主模型 | ★★★★★（许可需定性） |
| Qwen-Image-Edit-2511 多图放置人物 + 内置光照 | A | 20B | fp8 约 20.4GB，要 offload（ComfyUI 文档在 4090D 上：显存 86%，71–94s/张） | 慢 | Apache-2.0 | Comfy-Org/HF，约 20GB | ★★★★ |
| dx8152 Light-Migration（Edit-2509 LoRA） | A（后处理统一光照） | Edit-2509 20B | 同上 | 配 Lightning 4/8 步 | Apache-2.0 | HF dx8152，大小未查到 | ★★★★ |
| dx8152 Relight（Edit-2509 LoRA） | A（文字指定光照） | Edit-2509 | 同上 | 同上 | Apache-2.0 | HF，大小未查到 | ★★★ |
| QIE-2511-Studio-DeLight | A（人物参考图去光，作前置） | Edit-2511 | 同上 | — | Apache-2.0 | HF，大小未查到 | ★★★ |
| LightingRemap Alpha | A（色块指定光源方向） | Edit-2511 | 同上 | — | 未查到 | HF zooeyy | ★★ |
| LBM relighting | A（快速重打光） | SDXL 3B | 可行 | 1 步 | **CC BY-NC 4.0** | HF jasperai，约 3B BF16（约 6GB，推断） | ★★★（非商用限制） |
| IC-Light v1 fbc + kijai 节点 | A（光照粗稿） | SD1.5 | 很轻松 | 快 | Apache-2.0（RMBG 1.4 换成 BiRefNet） | HF lllyasviel/ic-light，大小未查到 | ★★ |
| IC-Light v2 Flux | A | Flux | — | — | 没开权重，非商用 | 无 | ✗ |
| Kontext relight LoRA v3 | A | Flux Kontext dev | fp8 可行 | — | other（Kontext dev 非商用） | HF kontext-community | ★ |
| KJNodes ColorMatch（hm-mvgd-hm/mkl） | A（色调兜底） | 无 | 可行 | 毫秒级 | GPL-3.0 | pip color-matcher | ★★★（只当兜底） |
| PCT-Net | A（色调协调） | 自身 | 可行 | 快 | MPL-2.0 | GitHub pretrained_models | ★★ |
| Harmonizer | A（色调协调） | 自身 20MB | 可行 | 实时 | **CC BY-NC-SA 4.0** | Google Drive | ★（非商用） |
| SynthLight / Relightful Harmonization / LumiNet | A | — | — | — | 没开源，或没确认 | 无 | ✗ |
| DWPose（DWPreprocessor） | B（提取、闸门） | — | 可行 | 亚秒级（推断） | Apache-2.0 | yzd-v/DWPose：yolox_l.onnx 217MB + dw-ll_ucoco_384.onnx 134MB | ★★★★★ |
| OpenPose（CMU / controlnet_aux 的 OpenPose 预处理器） | B | — | 可行 | — | **非商用研究** | lllyasviel/Annotators body_pose_model.pth 209MB 等 | ✗（禁用） |
| Qwen-Image-2.1 Fun ControlNet Union（Pose） | B（主路线） | 2.1 | 卡上写单张消费级卡放不下完整模型，要 offload 或 fp8 | 官方 40 步；Turbo 兼容性未知 | **qwen-research** | alibaba-pai，约 7.0–7.55GB | ★★★★★（需实测 Turbo） |
| InstantX Qwen-Image Union（Pose） | B | 20B | fp8 底模 + 2B CN，较紧 | 30 步 | Apache-2.0 | HF InstantX，2B 参数 | ★★★（换底模才用） |
| DiffSynth Union LoRA | B | 20B | 同上 | — | 未查到 | Comfy-Org repackaged | ★★ |
| Edit-2509/2511 吃 DWPose 图 | B | 20B | 同上 | — | Apache-2.0 | — | ★★（社区反馈不稳定） |
| ComfyUI-openpose-editor（huchenlei） | B（模板编辑） | — | — | — | GPL-3.0 | — | ★★★★ |
| 3D OpenPose Editor 2026_IK | B（3D 摆姿和相机） | — | — | — | 许可未写 | GitHub | ★★（还在开发中） |
| 景别闸门（DWPose + 规则，自研） | B（防退档） | — | 可行 | 亚秒级 | 自研 | 复用 DWPose | ★★★★★ |

---

## 推荐实测项（按优先级）

1. **[许可定性，阻塞项]** 由总调度或本人定：项目是否商用？如果商用，Qwen-Image 2.1 / Turbo / 2.1 Fun ControlNet 都需要 Qwen 的商用授权，否则主模型要换成 Apache 系（Qwen-Image 20B + Edit-2511）。这一条决定下面所有路线。
2. **T1 一次生成对比合成**：同一组镜头（每种景别 5 镜，共 25 张），比较 (a) 现行流程"人物参考 + 场景母版合成"和 (b) 2.1 Turbo 多参考直接生成（图 1 人物身份参考，图 2 场景母版，提示词写光源方向和景别）。评估项：A4 的合成感指标、身份脸相似度（现有身份脸闸门）、人工审片。
3. **T2 pose 控制强度网格**：2.1 Fun Union（Pose）挂在 2.1 Turbo 上，先验证 8 步能不能出正常图。网格为 scale {0.6, 0.8, 1.0} × end_percent {0.6, 0.8, 1.0} × 景别 {CU, MCU, MS, FS}，记录景别闸门通过率、写实分和单张耗时。如果 Turbo 不兼容，回退到 2.1 标准版 40 步做对照。
4. **T3 截断骨架模板对比完整小人骨架**：中景模板分两种画法，一种把膝以下画到画外截断，一种把完整人体缩小放进画布，各跑 20 张，统计实际景别分布，验证摘要第 9 条。
5. **T4 景别闸门标定**：拿已有的 200 张人工标注景别图（没有就先标）跑 DWPose 和 B3 规则，调可见性阈值和头高比阈值，目标准确率 ≥ 90%，并统计退档率。
6. **T5 后处理重打光**：对 T1(a) 里没过合成感指标的图，比较 Light-Migration（Edit-2509 + Lightning）、Edit-2511 原生光照指令、LBM（仅内部对照，非商用）和 ColorMatch（hm-mvgd-hm，strength 0.5）。每种方案记录身份脸漂移、光照方向一致性和耗时。
7. **T6 合成感指标标定**：先实现 A4 的 ①–⑤，用"明显 PS 感"和"自然"两组各 50 张标定阈值，再决定是否接进闸门。
8. **T7 3090 显存实测**：Edit-2511 fp8 + Light-Migration LoRA + Lightning 在 24GB 上的 offload 配置和耗时；2.1 Turbo + Fun Union 同时加载时的峰值显存。

---

## 需下载清单（本轮不下载，仅列出）

| # | 文件 | 来源 | 大小 | 许可 | 用途 | 优先级 |
|---|---|---|---|---|---|---|
| 1 | yolox_l.onnx | https://huggingface.co/yzd-v/DWPose | 217MB | Apache-2.0 | DWPose 检测器 | P0 |
| 2 | dw-ll_ucoco_384.onnx | 同上 | 134MB | Apache-2.0 | DWPose 姿态估计 | P0 |
| 3 | comfyui_controlnet_aux（节点） | https://github.com/Fannovel16/comfyui_controlnet_aux | — | Apache-2.0 | DWPreprocessor | P0（服务器上可能已经装了，需核对） |
| 4 | ComfyUI-openpose-editor（节点） | https://github.com/huchenlei/ComfyUI-openpose-editor | — | GPL-3.0 | 模板编辑 | P1 |
| 5 | Qwen-Image-2.1-Fun-Controlnet-Union | https://huggingface.co/alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union | 约 7.0–7.55GB | qwen-research | 2.1 上的 pose 控制 | P0 |
| 6 | Qwen-Image-Edit-2511（fp8） | https://huggingface.co/Qwen/Qwen-Image-Edit-2511 （或 Comfy-Org 的重打包版） | 约 20GB（按 Qwen-Image fp8 20.4GB 推断） | Apache-2.0 | 多图放置、光照 | P1 |
| 7 | Qwen-Image-Edit-2509（fp8，用来挂 dx8152 LoRA） | https://huggingface.co/Qwen/Qwen-Image-Edit-2509 | 约 20GB（推断） | Apache-2.0 | Light-Migration 底模 | P1（如果 2511 原生效果够，就不用下） |
| 8 | dx8152 Light-Migration LoRA | https://huggingface.co/dx8152/Qwen-Edit-2509-Light-Migration | 未查到 | Apache-2.0 | 后处理统一光照 | P1 |
| 9 | dx8152 Relight LoRA（Qwen-Edit-Relight.safetensors） | https://huggingface.co/dx8152/Qwen-Image-Edit-2509-Relight | 未查到 | Apache-2.0 | 文字指定光照 | P2 |
| 10 | lightx2v Qwen-Image-Lightning（Edit 版） | https://huggingface.co/lightx2v/Qwen-Image-Lightning | 未查到 | 未查到 | Edit 加速 | P1（跟 7/8 配套） |
| 11 | QIE-2511-Studio-DeLight | https://huggingface.co/mario-d-robot/QIE-2511-Studio-DeLight | 未查到 | Apache-2.0 | 人物参考去光 | P2 |
| 12 | color-matcher（pip，KJNodes 依赖） | https://github.com/hahnec/color-matcher | 很小 | GPL-3.0 | 色调兜底 | P1（KJNodes 可能已经装了） |
| 13 | LBM_relighting | https://huggingface.co/jasperai/LBM_relighting | 约 3B BF16 | CC BY-NC 4.0 | 仅内部对照 | P3 |
| 14 | IC-Light iclight_sd15_fbc + 一个 SD1.5 写实底模 | https://huggingface.co/lllyasviel/ic-light | 未查到 | Apache-2.0 | 基线对照 | P3 |
| — | **不要下载**：OpenPose body/hand/face 权重（lllyasviel/Annotators 的 body_pose_model.pth 等）、Harmonizer（非商用）、IC-Light v2（没开权重） | — | — | — | — | 禁 |

---

### 未查到汇总

- IC-Light v2 Flux 权重：截至 discussions/98 都没公开，后续也没查到公告。
- dx8152 各 LoRA 的文件大小和推荐强度；Light-Migration 有没有 Reddit 实测帖。
- LBM relighting 的分辨率。
- 2.1 Fun ControlNet Union 跟 2.1 Turbo（8 步）的兼容性。
- DiffSynth In-Context Control Union LoRA 的许可（HF 返回 401）。
- ComfyUI 的 PCT-Net / Harmonizer 节点，以及 ComfyUI-PIH 的许可。
- 基于关键点可见性的景别判定现成开源实现。
- "Lumina" 重打光项目，以及 SynthLight / Relightful Harmonization 的代码。
- InstantX Union 在 Qwen 上的 Reddit 强度实测帖。
