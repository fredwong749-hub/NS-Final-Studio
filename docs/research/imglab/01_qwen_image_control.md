# 01 Qwen-Image 系列在 ComfyUI 的结构化控制工具调研

- 调研日期：2026-11-02（IMGLAB 研究子 agent）
- 目标链路：Qwen-Image 2.1 Turbo + ComfyUI + RTX 3090 24GB
- 要解决：①人物一致性/身份保持 ②手部畸形 ③人物与背景光照不一致（像 PS 贴图） ④姿势/构图不对
- 方法：逐一读 HF 模型卡、ComfyUI 官方文档/模板/源码、GitHub PR、HF 讨论区、comfyui-wiki 新闻。文件大小由 HF API（`/api/models/<repo>/tree/main`）实时查得。
- **局限**：Reddit（reddit.com）对本工具的抓取器屏蔽（WebSearch 返回 "domains are not accessible"，curl 返回反爬页），**Reddit 帖子全部未能读到**；社区实测改用 HF 讨论区、note.com、GitHub 等替代来源，并在每条上注明。
- 置信度：高 = 官方卡/官方源码/官方模板原文；中 = 第三方新闻站或社区实测单例；低 = 推断或单一非官方说法。

---

## 一、摘要（最重要的 10 条）

1. **许可证红线（高）**：Qwen-Image **2.1 / 2.1 Turbo** 本体、alibaba-pai 的 2.1 Fun ControlNet Union、2.1 Fun-Acc LoRA 都是 **Qwen Research License（研究许可，非商用）**，原文："You shall not use the Materials for any commercial purpose without obtaining a separate commercial license from us."。而 v1 家族（Qwen-Image / 2512 / Edit / Edit-2509 / Edit-2511、InstantX、DiffSynth、lightx2v Lightning、dx8152 系列 LoRA）都是 **Apache-2.0**。短剧如果商用，要么向 Qwen 申请商业许可（model-business@notice.qwencloud.com），要么把控制链路切回 Apache 家族。这是需要上报总调度的决策点。
2. **2.1 唯一的官方结构控制 = alibaba-pai `Qwen-Image-2.1-Fun-Controlnet-Union`（高）**：一个文件包含 Canny/Depth/Grayscale/HED/Lineart/MLSD/Pose(DWPose)/Scribble 8 种控制加 mask 局部重绘。ComfyUI 原生支持在 PR #16519（2026-09-28 合并）。用法：`ModelPatchLoader`（Load Model Patch）加 **`ZImageFunControlnet`（显示名 "Apply Fun ControlNet"）**，输入有 image / inpaint_image / mask / strength / start_percent / end_percent。Comfy-Org 提供 int8 版 3.78 GB。
3. **v1 的 ControlNet 不能用在 2.1 上（中-高，基于架构推断）**：2.1 是 "32 single-stream DiT layers"、文本编码器换成 Qwen3-VL、VAE 也换了；InstantX Union/Inpainting、DiffSynth Blockwise、Union Control LoRA 都是给 Qwen-Image（v1，Qwen2.5-VL 编码器）训练的。ComfyUI 源码对 2.1 Fun CN 走的是单独的 `QwenImage21FunControl` 分支。
4. **Turbo 和 Fun ControlNet 能不能一起用：未查到（低）**。官方卡、T8 节点仓库、comfyui-wiki 都没提 Turbo；官方样例都是 40 步。佐证：Fun CN 卡写的是 "CFG-distilled fast sampling ... guidance_scale = 1.0"，而 Turbo 也是 CFG1；v1 家族的官方模板里，Fun CN 2512、InstantX 都和 Lightning 4 步 LoRA 一起用。**这一项必须实测。**
5. **身份保持：Qwen 上没有查到 PuLID 或 IP-Adapter 的移植（中）**。现成做法是用模型自带的多参考图：2.1 卡原文 "Support up to 10 reference images ... preserve identity for people and products"，ComfyUI 的 `TextEncodeQwenImage21` 支持 image_1 到 image_16 自动增长；Edit-2511 卡原文 "notably better consistency"。
6. **手部畸形：Qwen 2.1 没有专门的手部工具（中）**。HF 讨论 #29 用户原话 "就是手指脚趾的问题"，社区给的办法是 "提高CFG，在负面提示词中加入手指畸形"，但 Turbo 是 CFG1，这条在 Turbo 上基本用不了。可行的方向是用 Fun CN 的 mask 局部重绘加 Pose/Depth 约束，或者走专门的手脸修复链路（见 03_hand_face_detailer.md）。
7. **光照不一致/PS 贴图感（高）**：成熟的现成工具都在 **Edit-2509** 上，而且都是 Apache：dx8152 的 Relight、Light Migration（按参考图换光）、Fusion（"纠正产品透视角度和光影并使产品融入背景"）、Light_restoration（去光影）。ComfyUI 有两个官方模板：`image_qwen_image_edit_2509_relight` 和 `templates-qwen_image_edit-crop_and_stitch-fusion`。2.1 上**没有查到** relight LoRA，但 2.1 自带编辑能力能换光，官方 Turbo 编辑模板的示例 prompt 就是 "Relight the scene as a clear moonlit night"。
8. **姿势/构图（高）**：2.1 只有 Fun CN Pose/Depth 这一条路。Apache 家族可选的更多：Edit-2509 原生支持 "depth maps, edge maps, keypoint maps"；AnyPose LoRA（2511，参考图换姿势，不需要 OpenPose）；Multiple-Angles LoRA（2509、2511、2.1 都有版本）。
9. **分区提示（中）**：没有查到 Qwen 专用的 regional prompting 或 attention couple 节点。只有两个接近的：社区 `ComfyUI-qwen_img_2_1_enhancer`（按 mask 调参考图 token 的注意力强度），以及给 Krea 2 做的单流 DiT 分区节点，可作移植参考。
10. **3090 显存（中）**：2.1 int8 DiT 7.26 GB。4060 Ti 16GB 实测峰值约 15 GB，文生图约 20 s、编辑约 60 s。加上 Fun CN 后，4090 实测 "22GB VRAM + 18GB shared memory"、60 s 一张，所以 **3090 能跑但很紧**，需要 int8 加文本编码器卸载，必要时用 GGUF Q8（7.64 GB）。

---

## 二、分节详述

### 1. ControlNet

#### 1.1 Qwen-Image 2.1 Fun ControlNet Union（alibaba-pai）：2.1 唯一官方结构控制
- 支持类型：原文 "The 16-block control branch supports Canny, Depth, Grayscale, HED, Lineart, MLSD, Pose, and masked inpainting."（t8star 转换卡）；alibaba-pai 卡写 Pose 是 DWPose 骨架。注意："The mode label does not generate a map from a photograph"，控制图要自己预处理（comfyui_controlnet_aux）。
  - 链接：https://huggingface.co/alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union ，https://huggingface.co/t8star/Qwen-Image-2.1-Fun-Controlnet-Union-Comfy — 置信度 高
- 架构：控制分支挂在 32 个 block 中的每第 2 个上（control_layers = [0,2,…,30]），`control_in_dim = 129` = "control latents (64) | mask (1) | masked-image latents (64)"。所以**控制和局部重绘在同一个文件里，可以同时用**。— 高
- 强度：原文 "`1.0` is the strongest control (used for all results below)"，"`control_context_scale = 1.0` is the value the adapter expects"。样例全部 40 步。— 高
- 显存：原文 "the transformer plus Qwen3-VL do not fit a single consumer GPU fully loaded"，推荐 `model_group_offload`。— 高（官方），但这是 diffusers 的说法，ComfyUI 会自动卸载。
- ComfyUI 支持：PR https://github.com/Comfy-Org/ComfyUI/pull/16519 "Support Qwen-Image 2.1 union fun controlnet"，2026-09-28 合并。已核对当前 master 源码 `comfy_extras/nodes_model_patch.py`：
  - `ModelPatchLoader`（显示名 "Load Model Patch"）通过 `control_img_in.weight` 键识别出 2.1 Fun CN（源码注释 "# Qwen Image 2.1 Fun ControlNet"）；
  - 应用节点用 `ZImageFunControlnet`（显示名 "Apply Fun ControlNet"），原文 DESCRIPTION "Applies a Z-Image or Qwen Image 2.1 Fun ControlNet loaded with Load Model Patch."。可选输入 image / inpaint_image / mask / start_percent / end_percent。`QwenImageDiffsynthControlnet` 也能接 2.1 patch，但它的界面上没有 inpaint_image 口。
  - 链接：https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_model_patch.py — 高（源码）
- 官方模板：Comfy-Org/workflow_templates 里**没有** 2.1 ControlNet 模板（已列出全部 qwen 模板确认）。只有 PR 附带的测试工作流，作者 Kijai 自评 "workflow is suboptimal"。另有社区节点 T8（https://github.com/T8mars/Comfyui-Qwen-Image-2.1-Fun-Controlnet-Union-T8），提供 "Apply Qwen Image 2.1 UNION" 节点。— 高
- 社区实测（note.com，非 Reddit）：RTX 4090，int8 DiT + int8 TE + int8 CN，"22GB VRAM + 18GB shared memory"，"It took 60 seconds to generate one image"，质量评价是 "it's a standard ControlNet model"，测了 OpenPose/Depth/Canny/inpaint。链接：https://note.com/kongo_jun/n/n24bd62787f12 — 中
- Turbo 兼容：**未查到**。官方卡、comfyui-wiki、T8 仓库都没有提到。— 低
- 许可证：qwen-research（非商用）。— 高

#### 1.2 InstantX Qwen-Image-ControlNet-Union（只适用 v1 / 2512 / Edit）
- 原文 "supports 4 common control types (canny, soft edge, depth, pose)"，"controlnet_conditioning_scale in [0.8, 1.0]"，"ComfyUI offers native support"。局限："unable to preserve some details without explicit 'TEXT' in prompt"。Apache-2.0，2B 参数。
  - https://huggingface.co/InstantX/Qwen-Image-ControlNet-Union — 高
- ComfyUI 用法：放到 `models/controlnet/`，用 `Load ControlNet Model` 加标准 ControlNetApply。官方文档原文 "This is a ControlNet model, so you can use it as normal ControlNet."。模板 `image_qwen_image_instantx_controlnet.json`。https://docs.comfy.org/tutorials/image/qwen/qwen-image — 高
- 文件：`Comfy-Org/Qwen-Image-InstantX-ControlNets/split_files/controlnet/Qwen-Image-InstantX-ControlNet-Union.safetensors` 3.54 GB — 高
- 用在 2.1 上：不兼容（架构不同，推断）— 中

#### 1.3 DiffSynth Qwen-Image Blockwise ControlNet（Canny / Depth / Inpaint，只适用 v1）
- 原文 "It can control the structure of generated images using edge detection (Canny) maps"，"trained based on Qwen-Image, with the ControlNet architecture"，Apache-2.0。https://huggingface.co/DiffSynth-Studio/Qwen-Image-Blockwise-ControlNet-Canny — 高
- ComfyUI：`ModelPatchLoader` 加 **`QwenImageDiffsynthControlnet`**（显示名 "Apply Qwen Image DiffSynth ControlNet"），文件放 `models/model_patches/`。做 inpaint 时把 Load Image 的 mask 接到 mask 口。模板 `image_qwen_image_controlnet_patch.json`。— 高
- 文件（Comfy-Org/Qwen-Image-DiffSynth-ControlNets/split_files/model_patches/）：canny、depth、inpaint 各 2.27 GB。— 高

#### 1.4 DiffSynth Union Control LoRA（v1）
- 官方文档原文 "supports canny, depth, pose, lineart, softedge, normal, openpose controls"，用 `LoraLoaderModelOnly` 加载，控制图通过 `ReferenceLatent` 喂入。文件 `qwen_image_union_diffsynth_lora.safetensors` 944 MB。官方模板里和 `Qwen-Image-Lightning-4steps-V1.0` 叠加使用（4 步 CFG1）。— 高

#### 1.5 Qwen-Image-2512 Fun ControlNet Union（v1 系，Apache）
- 原文控制类型 "Canny, HED, Depth, Pose, MLSD, Scribble, and Gray"，2602 版 "trained longer"，推荐 `control_context_scale` 0.70–0.95，支持 inpaint。Apache-2.0，每个文件 3.51 GB。https://huggingface.co/alibaba-pai/Qwen-Image-2512-Fun-Controlnet-Union — 高
- 官方模板 `image_qwen_Image_2512_controlnet.json` 用 `ControlNetLoader` 加 `ControlNetApplyAdvanced`，**并叠了 Lightning 4 步 LoRA**。这说明 v1 家族里蒸馏 LoRA 和 Fun CN 同时用是官方做法。— 高

#### 1.6 Qwen-Image-Edit-2509 原生吃控制图
- 卡原文 "native support for ... depth maps, edge maps, keypoint maps, and more"。https://huggingface.co/Qwen/Qwen-Image-Edit-2509 — 高
- 用法：把 pose/depth/canny 图作为 image2 喂给 `TextEncodeQwenImageEditPlus`（ComfyUI 核心节点，源码 `comfy_extras/nodes_qwen.py` 有 image1/image2/image3 三个口）。**没有查到官方的 pose 迁移工作流**，只有第三方提及。— 中

#### 1.7 和蒸馏/加速 LoRA 的兼容性小结
- v1 家族：InstantX Inpainting、Union LoRA、2512 Fun CN 的官方模板都叠了 Lightning 4 步 LoRA，可以确定兼容。— 高
- v1 原版注意点：官方文档原文 "The distilled model and the 8-step acceleration LoRA by lightx2v do not seem to be compatible for simultaneous use."（指非官方 distill 底模和 Lightning 叠加）。— 高
- 2.1：Turbo 有 checkpoint 和 LoRA 两种形态（`qwen_image_2.1_turbo_lora_avg_rank_178_bf16` 0.91 GB），comfyui-wiki 原文 "keeps the same 7B visual generation model and the same editing pipeline"。和 Fun CN 叠加**未查到**。— 低

### 2. Inpaint（局部重绘）

- **2.1 路线 A：Fun CN 的 mask 重绘**。原文 "white mask pixels mark the area to regenerate"，可以和控制图同时输入（例如手部区域 mask 加 Pose 骨架）。ComfyUI 用 "Apply Fun ControlNet"，接 inpaint_image（原图）和 mask。— 高
- **2.1 路线 B：模型自带的局部编辑**。卡原文 "specify local edits via circles, painted annotations, or separate masks"，但**没写 mask 怎么传进去**。第三方说 mask 模式 "needs exactly one reference"（runcomfy/weshop 等，未经官方确认）。ComfyUI 的 `TextEncodeQwenImage21` 没有专门的 mask 口，只有参考图口。— 卡原文 高 / 具体用法 低
- **2.1 社区**：`KENIC-1/Turbo-Qwen-Image-2.1-Turbo-Inpaint-LORA` 模型卡是空的，不建议用。— 低
- **v1：InstantX Qwen-Image-ControlNet-Inpainting**。原文 "supports mask-based image inpainting and outpainting"，"slightly sensitive to user prompts"，建议用描述整图的 prompt，需要 ComfyUI ≥0.3.59。Apache，4.23 GB（Comfy-Org 版）。官方模板 `image_qwen_image_instantx_inpainting_controlnet.json` 的节点链：`ControlNetInpaintingAliMamaApply` + `SetLatentNoiseMask` + `GrowMask`/`ImageBlur` + `ImageCompositeMasked`，叠 Lightning 4 步。https://huggingface.co/InstantX/Qwen-Image-ControlNet-Inpainting — 高
- **v1：DiffSynth inpaint patch**（2.27 GB），见 1.3。— 高
- **Edit 模型加 mask 裁切拼回**：官方模板 `templates-qwen_image_edit-crop_and_stitch-fusion.json`（Edit-2509 + Fusion LoRA + Lightning 4 步）。— 高

### 3. 参考图编辑 / 多图 / 一致性与打光 LoRA

#### 3.1 模型自带能力
- **Qwen-Image 2.1**：原文 "Support up to 10 reference images"，"preserve identity for people and products"，展示图 "Group photograph generated from six portrait references"。ComfyUI `TextEncodeQwenImage21` 用 Autogrow 提供 image_1 到 image_16，tooltip 原文 "Reference images, seen by the text encoder and spliced into the sequence as VAE latents."。另一个 tooltip 提醒输出 latent 要用第一张参考图的尺寸："Empty latent on the first reference image's size, to match with sampling as any other size shifts the edit."（**做一致性时要注意：图1 应该放要保持的主图**）。https://huggingface.co/Qwen/Qwen-Image-2.1 — 高
- 第三方建议 "keeping the reference count at four or fewer when identity or logos must stay sharp"（runcomfy 等）。— 低
- **Edit-2509**：原文 "Optimal performance is currently achieved with 1 to 3 input images"，"Better preservation of facial identity"。— 高
- **Edit-2511**：原文 "notably better consistency"，"Multi-Person Consistency: High-fidelity fusion of multiple person images into coherent group shots"，并把 "lighting enhancement and new viewpoint generation" 等社区 LoRA 内置进了底模。ComfyUI 模板需要 `FluxKontextMultiReferenceLatentMethod`（index_timestep_zero）加 `CFGNorm`。Apache。https://huggingface.co/Qwen/Qwen-Image-Edit-2511 — 高

#### 3.2 2.1 社区 LoRA（底模许可都继承 qwen-research）
| LoRA | 作用 | 原文要点 | Turbo | 大小 | 置信度 |
|---|---|---|---|---|---|
| ausboss/Qwen-Image-2.1-Consistency-LoRA | 编辑时画面不位移、不重画未编辑区 | "same prompt, same edit, nothing moves"；已知问题 "may ignore movement such as a new pose or turned head" | 卡写在 8 步 Turbo、约 2MP 下测过 | 0.16 GB | 高（卡） |
| ausboss/Qwen-Image-2.1-Outfit-Swap-Consistency-LoRA | 换装时保脸保背景 | 脸部像素变化 "14.1% without ... 1.7% with"，脸部 PSNR 29.8→37.8 dB（**像素指标，不是人脸识别指标**） | 用 Viggle Turbo 8 步测过 | — | 高（卡） |
| akhaliq/Qwen-Image-2.1-Turbo-Character-Swap-LoRA | 用参考图里的角色替换画面里的人，保场景 | "Swap the person in Picture 1 with the character in Picture 2"；卡**没有承诺保身份** | 基于 Turbo | 0.17 GB | 中 |
| akhaliq/Qwen-Image-2.1-Multiple-Angles-LoRA | 机位/视角控制 | `<mva> {azimuth}, {elevation}`，强度 0.8–1.0 | 未说明 | v2 0.32 GB | 高 |
| akhaliq/Qwen-Image-2.1-Next-Scene-LoRA | 按导演指令生成下一镜（分镜连贯） | "Next Scene:" 开头，强度 0.7–0.9 | 未说明 | 0.34 GB | 高 |
| 2.1 relight / 打光 LoRA | — | HF 搜索 "Qwen-Image-2.1 relight / light" **没有结果** | — | — | 未查到 |

#### 3.3 Edit-2509 / 2511 社区 LoRA（Apache-2.0）
- **dx8152/Qwen-Image-Edit-2509-Relight**（`Qwen-Edit-Relight.safetensors` 0.24 GB）：按文字重新打光。Replicate 预设强度 0.9；第三方 Floyo 说满强度会让皮肤身份漂移，建议约 0.7（未经原作者证实）。ComfyUI 官方模板 `image_qwen_image_edit_2509_relight.json`。— 卡 高 / 强度建议 低
- **dx8152/Qwen-Edit-2509-Light-Migration**（`参考色调.safetensors` 0.24 GB）：输入两张图，把图 2 的光照和色调迁移到图 1。原 prompt "参考色调，移除图1原有的光照并参考图2的光照和色调对图1重新照明"；作者原话 "I feel the Edit version [of Lightning] performs better"。— 高
- **dx8152/Qwen-Image-Edit-2509-Fusion**（`溶图.safetensors` 0.24 GB）：触发词 "溶图,纠正产品透视角度和光影并使产品融入背景"，**直接针对"PS 贴图感"**。卡上示例是产品，用在人物上的效果未查到。— 高（卡）/ 人物效果 未查到
- **dx8152/Qwen-Image-Edit-2509-Light_restoration**（V2 0.24 GB）：去掉光影、改成柔光，作者定位是给打光 LoRA 造训练数据。— 高
- **dx8152/Qwen-Edit-2509-Multiple-angles**（`镜头转换.safetensors` 0.24 GB）、**fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA**（0.3 GB，96 个机位，`<sks> front view eye-level shot medium shot`，强度 0.8–1.0）。— 高
- **lilylilith/AnyPose**（2511，base + helper 两个文件，各 0.3 GB，强度都设 0.7，配 2511 Lightning 4 步）：原 prompt "Make the person in image 1 do the exact same pose of the person in image 2"。已知问题：背景会串、多人时出问题。— 高
- **peteromallet/Qwen-Image-Edit-InScene**（只适配初版 Qwen-Image-Edit，0.59 GB）：同一场景换镜头，保角色和场景，"Show a different image in the same scene of:"，仍是 Beta。— 高
- **lightx2v Lightning**：Edit-2511 有 4/8 步 bf16 LoRA，各 0.85 GB。HF 讨论里有人反映 4 步质量差、8 步更好；fp8 版出现过偏色，有人回复说 2511 需要 `FluxKontextMultiReferenceLatentMethod` 节点。— 中

### 4. 身份保持现成方案
- **PuLID / IP-Adapter / InstantID 的 Qwen 版：未查到**。搜索结果只有 SD/SDXL 的 FaceID 和 Flux 的 PuLID。ComfyUI 的 ModelPatchLoader 里有 SigLIP 投影（给 USO 用的，属 Flux 系），和 Qwen 无关。— 中（查不到的结论）
- **现成可用的保脸手段**（按证据强度排序）：
  1. 2.1 或 Edit-2511 的**原生多参考**：把身份脸作为参考图喂入（官方卡原文支持身份保持）。— 高
  2. **参考图权重调节**：社区节点 `ComfyUI-qwen_img_2_1_enhancer`（原仓库 capitan01R 已 404，现存 fork https://github.com/deng232/ComfyUI-qwen_img_2_1_enhancer），有 "Qwen Image 2.1 Reference Strength (Masked)" 节点，可以按单张参考图或按 mask 区域调注意力。仓库**没有声称**专门保身份。— 中
  3. 2.1 的 Outfit-Swap / Consistency LoRA，减少非编辑区漂移（像素指标）。— 高（卡）
  4. 回到 Apache 家族用 Edit-2511 加 AnyPose 或 Multiple-Angles，做"同一人换姿势/换机位"。— 高（卡）
- **Reddit 保脸实测：未查到**（Reddit 无法访问）。HF 讨论 #64 有 "keep the woman's facial identity" 的压测帖，但正文**没有给结论**（RTX A6000，"~45 seconds per Image"）。— 低

### 5. 分区提示 / 区域控制
- Qwen 专用的 regional prompting 或 attention couple：**未查到**。ComfyUI 讨论 #13741 里 `Conditioning (Set Mask)` 的实现机制没人回答，也没有提到 Qwen。— 中
- 可参考的实现：
  - `januspluto/ComfyUI-Krea2-Regional`：给单流 DiT（Krea 2）做的联合注意力 mask 分区，作者原话 "Regional prompting + per-region LoRA for Krea 2"。2.1 也是单流 DiT，有移植可能（推断）。— 低
  - `Acly/comfyui-tooling-nodes` 的 Regions 节点：通用注意力 mask，**没写 Qwen 支持**。— 低
- 结论：目前分区控制在 Qwen 上**没有可直接落地的方案**。替代做法是按区域分步出图：用 Fun CN 的 mask 重绘逐区修，或者用多参考图加位置描述。

### 6. 显存 / 速度 / 文件
- 3090 跑 2.1 Turbo：
  - 文件：int8 DiT 7.26 GB；bf16 14.23 GB；GGUF Q8_0 7.64 GB、Q6_K 6.27 GB、Q4_K_M 4.2 GB（unsloth）。— 高（HF API）
  - 实测：4060 Ti 16GB 跑 int8 DiT + int8 TE，峰值约 15 GB，"~20 seconds" 文生图（1024²、25 步）、"~60 seconds" 编辑（HF 讨论 #35）。Turbo 只要 8 步，理论上更快。— 中
  - 加 Fun CN int8（3.78 GB）：4090 实测 22 GB VRAM + 18 GB 共享，60 s。**3090 能跑但贴着上限**，建议：TE 用 int8 或 w4a8 并在编码后卸载，`QwenImage21Cache` 的 dtype 设 int8（tooltip 原文 "int8 halves the cache at about bf16 accuracy"），必要时 DiT 改用 GGUF。— 中
  - Turbo 采样：社区确认要用 `SamplerCustomAdvanced` 加 `ManualSigmas`（"1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0.0"），官方 Turbo t2i 模板已内置这组值。原话 "no simple isn't close to the correct sigmas"（HF Comfy-Org 讨论 #22）。— 高
- INT8 ConvRot 在 Turing（2×T4）上能跑（讨论 #8 标题），所以 Ampere（3090）应该也能跑（推断）。3090 没有 fp8 硬件加速，fp8 权重会被升精度计算：这条本次**没有找到官方原文**，属于推断。— 低
- v1 家族：Qwen-Image / Edit-2509 fp8 约 20.4 GB，Edit-2511 GGUF Q4_K_M 12.84 GB、Q5_K_M 15.4 GB、Q8_0 22.35 GB。ComfyUI 文档的 4090D 表：fp8 占显存 86%，第二次跑约 71 s；加 8 步 LoRA 约 34 s。— 高

---

## 三、方案总表

| 方案 | 解决哪个问题 | ComfyUI 节点/插件 | 权重与大小 | 3090 可行 / 速度 | 许可证 | 置信度 |
|---|---|---|---|---|---|---|
| 2.1 Fun ControlNet Union（Pose/Depth/Canny 等 8 种 + inpaint） | ④姿势构图；②手部（mask+pose 重绘） | 核心：ModelPatchLoader + Apply Fun ControlNet（ZImageFunControlnet） | Comfy-Org int8 3.78 GB / bf16 7.55 GB | 可行但紧（4090 实测 22GB+共享，60 s/张）；**Turbo 兼容未查到** | qwen-research 非商用 | 高（支持）/ 低（Turbo） |
| 2.1 原生多参考编辑（≤10 张，节点 16 口） | ①身份；③合成光照（让模型重绘而不是贴图） | 核心：TextEncodeQwenImage21 + QwenImage21Cache | 用已有 2.1 Turbo | 可行；16GB 卡编辑约 60 s | qwen-research | 高 |
| 2.1 Reference Strength（Masked） | ①身份权重调节 | 社区：deng232/ComfyUI-qwen_img_2_1_enhancer | 无权重 | 可行 | 仓库未标 | 中 |
| 2.1 Consistency / Outfit-Swap LoRA | ①编辑时不漂移 | LoraLoaderModelOnly | 0.16 GB 等 | 可行，Turbo 测过 | qwen-research | 高（卡） |
| 2.1 Multiple-Angles / Next-Scene LoRA | ④机位、分镜连贯 | LoraLoaderModelOnly | 0.32 / 0.34 GB | 可行，Turbo 未说明 | 卡标 apache，底模受限 | 高（卡） |
| 2.1 Turbo Character-Swap LoRA | ①换角色进场景 | LoraLoaderModelOnly | 0.17 GB | 可行（基于 Turbo） | other | 中 |
| InstantX Union CN | ④（只适用 v1/2512） | Load ControlNet + ControlNetApply | 3.54 GB | 可行，fp8 底模约 20 GB | Apache | 高 |
| InstantX Inpainting CN | ②局部重绘（v1） | ControlNetInpaintingAliMamaApply | 4.23 GB | 可行，配 Lightning 4 步 | Apache | 高 |
| DiffSynth Blockwise canny/depth/inpaint | ④②（v1） | ModelPatchLoader + QwenImageDiffsynthControlnet | 各 2.27 GB | 可行 | Apache | 高 |
| DiffSynth Union Control LoRA | ④（v1，7 种控制） | LoraLoaderModelOnly + ReferenceLatent | 944 MB | 可行，配 Lightning 4 步 | Apache | 高 |
| 2512 Fun CN Union 2602 | ④②（2512） | ControlNetLoader + ControlNetApplyAdvanced | 3.51 GB | 可行，官方配 Lightning | Apache | 高 |
| Edit-2509 Relight / Light-Migration / Fusion / Light_restoration | ③光照一致、去 PS 感 | LoraLoaderModelOnly + TextEncodeQwenImageEditPlus；官方模板 relight、crop_and_stitch-fusion | 各 0.24 GB；Edit-2509 fp8 20.44 GB | 可行（fp8 吃满，或用 GGUF） | Apache | 高 |
| Edit-2511 + AnyPose | ④按参考图换姿势、①保人 | LoraLoaderModelOnly ×2 + FluxKontextMultiReferenceLatentMethod | 2×0.3 GB；2511 GGUF Q4_K_M 12.84 GB | 可行 | Apache | 高（卡） |
| Edit-2511 原生多图 + Multiple-Angles | ①多人一致、④机位 | 同上 | 0.3 GB | 可行 | Apache | 高 |
| PuLID / IP-Adapter for Qwen | ① | — | — | — | — | 未查到 |
| Regional prompting / attention couple for Qwen | 构图分区 | —（Krea2-Regional 可作移植参考） | — | — | — | 未查到 |

---

## 四、建议优先实测的 5 项

1. **2.1 Turbo + Fun CN Union（int8）的 Pose/Depth 控制**。这是 2.1 唯一的结构控制，对姿势和构图问题最直接，但 Turbo 兼容性没有任何文档。测试项：Apply Fun ControlNet 的 strength 设 0.6/0.8/1.0，end_percent 设 0.6/1.0，8 步 ManualSigmas；记录 3090 峰值显存和秒数，并和 2.1 base 25 步对照。
2. **2.1 Turbo 原生多参考保脸**：图1 放镜头构图或场景，后面放身份脸（项目已有身份脸），可选加 Reference Strength 节点提高身份图权重。直接对应身份一致性，零额外权重，最便宜。要测参考图数量（1/2/4）对身份的影响。
3. **Fun CN 的 mask 重绘修手**：手部 mask，inpaint_image 接原图，再加 DWPose 手部骨架或 Depth。Turbo 下 CFG 和负面提示词基本失效，这几乎是 2.1 链路里唯一能在原模型内修手的手段。同时和 03_hand_face_detailer.md 的外部修复方案对比。
4. **合成光照：先用 2.1 编辑把人物和场景作为多参考"一次生成"，失败的镜头再走 Edit-2509 Fusion/Light-Migration**。2.1 官方模板已经演示 relight；Fusion 是唯一明确针对"融入背景、纠正光影"的 LoRA，而且是 Apache，商用也能落地。
5. **备选 Apache 链路：Edit-2511 GGUF Q4/Q5 + AnyPose + Lightning 8 步**。用于姿势迁移和许可证兜底。如果项目方确认商用而又拿不到 Qwen 商业授权，这条线要能接住。

---

## 五、需下载清单（只列出，未下载）

| 用途 | HF 仓库 | 文件 | 大小 | 许可证 | 放置目录 |
|---|---|---|---|---|---|
| 2.1 结构控制 | Comfy-Org/Qwen-Image-2.1 | split_files/model_patches/qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors | 3.78 GB | qwen-research | models/model_patches/ |
| （可选，质量对照） | Comfy-Org/Qwen-Image-2.1 | split_files/model_patches/qwen_image_2.1_fun_controlnet_union_bf16.safetensors | 7.55 GB | qwen-research | models/model_patches/ |
| 2.1 Turbo LoRA 形态（若和 CN 冲突，可改用 base+LoRA 对照） | Comfy-Org/Qwen-Image-2.1 | split_files/loras/qwen_image_2.1_turbo_lora_avg_rank_178_bf16.safetensors | 0.91 GB | qwen-research | models/loras/ |
| 2.1 低显存 DiT 备选 | unsloth/Qwen-Image-2.1-Turbo-GGUF | qwen-image-2.1-turbo-Q8_0.gguf | 7.64 GB | 继承 qwen-research | models/unet/（需 ComfyUI-GGUF） |
| 预处理（DWPose/Depth） | GitHub Fannovel16/comfyui_controlnet_aux | 节点自带模型 | 视模型 | Apache-2.0（插件） | custom_nodes |
| 2.1 编辑不漂移 | ausboss/Qwen-Image-2.1-Consistency-LoRA | qwen-image-2.1-consistency.safetensors | 0.16 GB | qwen-research | models/loras/ |
| 2.1 机位 | akhaliq/Qwen-Image-2.1-Multiple-Angles-LoRA | checkpoints_v2/…multiple_angles_v2_000001500.safetensors | 0.32 GB | 卡 apache（底模受限） | models/loras/ |
| 参考权重节点 | GitHub deng232/ComfyUI-qwen_img_2_1_enhancer | 代码 | — | 未标注 | custom_nodes |
| Apache 兜底：融合/打光 | dx8152/Qwen-Image-Edit-2509-Fusion；dx8152/Qwen-Edit-2509-Light-Migration；dx8152/Qwen-Image-Edit-2509-Relight | 溶图.safetensors；参考色调.safetensors；Qwen-Edit-Relight.safetensors | 各 0.24 GB | Apache-2.0 | models/loras/ |
| Apache 兜底：Edit-2509 底模和加速 | lightx2v/Qwen-Image-Lightning | Qwen-Image-Edit-2509/qwen_image_edit_2509_fp8_e4m3fn_scaled.safetensors；Qwen-Image-Edit-2509-Lightning-8steps-V1.0-bf16.safetensors | 20.44 GB；0.85 GB | Apache-2.0 | diffusion_models / loras |
| Apache 兜底：姿势 | lilylilith/AnyPose + unsloth/Qwen-Image-Edit-2511-GGUF + lightx2v/Qwen-Image-Edit-2511-Lightning | 2511-AnyPose-base-000006250 + helper-00006000；qwen-image-edit-2511-Q5_K_M.gguf；…-8steps-V1.0-bf16 | 0.3+0.3 GB；15.4 GB；0.85 GB | Apache-2.0 | loras / unet / loras |
| （2.1 不需要）v1 ControlNet | Comfy-Org/Qwen-Image-InstantX-ControlNets；Comfy-Org/Qwen-Image-DiffSynth-ControlNets | Union 3.54 GB / Inpainting 4.23 GB；canny/depth/inpaint 各 2.27 GB；union lora 944 MB | — | Apache-2.0 | 只在切回 v1 时下载 |

另外：Edit-2509 / 2511 的文本编码器（qwen_2.5_vl_7b_fp8_scaled）和 VAE（qwen_image_vae）跟 2.1 不通用，走 Apache 兜底链路要另外下载，大小本次未查。

---

## 六、主要来源
- https://huggingface.co/Qwen/Qwen-Image-2.1 ；LICENSE：https://huggingface.co/Qwen/Qwen-Image-2.1/blob/main/LICENSE
- https://huggingface.co/Comfy-Org/Qwen-Image-2.1 （文件大小来自 HF API）
- https://huggingface.co/alibaba-pai/Qwen-Image-2.1-Fun-Controlnet-Union ；https://huggingface.co/t8star/Qwen-Image-2.1-Fun-Controlnet-Union-Comfy
- https://github.com/Comfy-Org/ComfyUI/pull/16519 ；https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_model_patch.py ；https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_qwen.py
- https://github.com/Comfy-Org/workflow_templates （templates/ 下的 qwen 模板）
- https://comfyui-wiki.com/en/news/2026-10-09-qwen-image-2-1-turbo ；https://comfyui-wiki.com/en/news/2026-09-24-qwen-image-2-1-fun-controlnet-union
- https://docs.comfy.org/tutorials/image/qwen/qwen-image ；https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit ；https://docs.comfy.org/tutorials/image/qwen/qwen-image-edit-2511
- HF 讨论：Qwen/Qwen-Image-2.1 #29（手脚）、#35（4060Ti 实测）、#40/#41（商用争议）、#64（压测）；Comfy-Org/Qwen-Image-2.1 #16、#22
- https://note.com/kongo_jun/n/n24bd62787f12 （Fun CN 4090 实测）
- 模型卡：InstantX/Qwen-Image-ControlNet-Union、InstantX/Qwen-Image-ControlNet-Inpainting、DiffSynth-Studio/Qwen-Image-Blockwise-ControlNet-Canny、alibaba-pai/Qwen-Image-2512-Fun-Controlnet-Union、Qwen/Qwen-Image-Edit-2509、Qwen/Qwen-Image-Edit-2511、lightx2v/Qwen-Image-2.1-Lightning、lightx2v/Qwen-Image-Edit-2511-Lightning、alibaba-pai/Qwen-Image-2.1-Fun-Acc-LoRAs、ausboss/*、akhaliq/*、dx8152/*、lilylilith/AnyPose、fal/Qwen-Image-Edit-2511-Multiple-Angles-LoRA、peteromallet/Qwen-Image-Edit-InScene
- https://github.com/deng232/ComfyUI-qwen_img_2_1_enhancer ；https://github.com/T8mars/Comfyui-Qwen-Image-2.1-Fun-Controlnet-Union-T8 ；https://github.com/januspluto/ComfyUI-Krea2-Regional
