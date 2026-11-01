# 双人镜属性串扰：多人分区控制与逐人身份注入（IMGLAB 调研，2026-11-02）

> 范围：只看“多人分区控制 + 逐人身份注入”。Qwen ControlNet / Flux 通用控制另有子 agent 在查，这里不重复。
> 实例：ep06-S2，顾沉长出林晚的“雾霾天蓝长直发”；要求“特写”却出了双人中景。编译层的根因见同目录 `05_ep06S2_bleeding_rca.md`，本文只讲模型层和出图结构层。
> 主模型：Qwen-Image 2.1 Turbo（ComfyUI 原生，`TextEncodeQwenImage21` 用 `<imageN>` 引用参考图），RTX 3090 24GB。
> 置信度：**高** = 官方文档 / 源码 / 论文摘要原文；**中** = 社区 README、模型卡或二手汇总；**低** = 单条用户帖、商业博客或推断。
> 方法：WebSearch + WebFetch 逐条读。没查到的写“未查到”。没下载任何东西，也没跑任何实测。

---

## 一、摘要（10 条）

1. **串扰是 DiT 的结构性问题，不是我们独有的 bug。** 多篇论文把多主体混淆归到联合注意力：文本 token 和图像 token 在同一个注意力空间里竞争，一个主体的属性会流到另一个主体（Bounded Attention、EnMMDiT、DreamRenderer、MOSAIC）。光靠一句全局提示，管不住每个主体各自的属性（EliGen）。置信度：高。
2. **Qwen-Image 2.1 的参考图有两条通路。** 参考图同时进文本编码器（Qwen3-VL），在 VAE 接上时还会作为 latent 拼进序列。官方没有“逐张参考图关掉某条通路”的开关。所以林晚的设定图只要接进这一镜，她的发色信息就对画面里的每个人都“可见”。置信度：高（官方节点文档）。
3. **ComfyUI 原生的 Conditioning (Set Mask)/Combine/area 不是注意力分区。** 源码里，mask 只是在模型跑完以后给各条件的噪声预测按像素加权平均（`out_conds += output * mult`）。每条条件仍然看得到全部参考图和整张画布，挡不住参考图层面的串扰。置信度：高（源码）。
4. **attention couple 类节点（cgem156 / ComfyCouple）都是 SD1.5/SDXL 时代的 UNet 交叉注意力补丁**，作者自己说 “not quite actual regional prompting”。没查到任何能在 Qwen-Image 上用的证据。RES4LYF 的区域条件只支持 HiDream/Flux/Chroma/SD3.5/AuraFlow/WAN，没有 Qwen。置信度：中到高。
5. **Qwen 系可用的真正的“区域注意力”只有 EliGen。** 它是 DiffSynth 给 **Qwen-Image（20B v1）** 训练的 LoRA，Apache-2.0，0.2B 参数。ComfyUI 封装（QwenImageWanBridge）被作者自己标为 “likely not working or deprecated”。**没查到适配 Qwen-Image 2.1（7B 单流）的版本。** Flux 有 Regional-Prompting-FLUX（Fluxtapoz 封装，GPL-3.0）。置信度：高。
6. **对我们最直接可用的开关是 Qwen-Image 2.1 Reference Strength。**（capitan01R 的 qwen_img_2_1_enhancer，MIT。原仓库 URL 现在 404，fork 在 deng232。）它能把某张参考图的注意力权重设成 0，也就是 “0.0 blocks direct attention to that reference's latent tokens”；还能用 mask 只放行参考图里的某些区域。不过作者也说明，文本编码器那条通路里的信息可能还在。置信度：中（社区 README，未实测）。
7. **两步法是社区对“两张脸互相漂移”的主流解法：先放 A，再单独一遍加 B / 重绘 B。** Krea 2 identity-edit 模型卡原话：“Two-person inputs keep outfits distinct but faces drift toward each other”，给的 workaround 是 “chain single-ref inserts”。Qwen-Image 2.1 在 ComfyUI 下可以用 `SetLatentNoiseMask` 做 mask 局部重绘（RunComfy 工作流），LanPaint 也明确支持 Qwen Image 2.1 的 mask 模式。置信度：中。
8. **多图提示写法有官方依据。** Qwen-Image-Edit-2509/2511（diffusers 源码）给每张图自动加 `Picture N:` 前缀；Qwen-Image 2.1 官方文档用 `<image1>` 这样按序号指代。官方示例都是“角色 + 位置”的写法（“…is on the left, …is on the right”）。没查到“哪种写法串扰最少”的对照实测。置信度：高（写法本身）/ 未查到（对照实测）。
9. **专门的 multi-ID 模型（UMO、XVerse、UniPortrait、MIP-Adapter、PuLID 多脸、InstantID 多 ID）都绑在别的底模上**（UNO/OmniGen2/FLUX.1-dev/SDXL），没有 Qwen-Image 2.1 版本。只能作为“Flux 支线”或研究参考，不建议进主链。置信度：高。
10. **镜头语法可以直接当编译规则用。** 单人镜（single）的定义就是 “only one character featured within the frame”。过肩镜是 “back of the head and shoulder in the foreground (typically out of focus)”，而且 “one of the most common framing devices for conversation scenes”。所以“特写 = 单人入画 + 只挂一张参考图”“过肩 = 前景背影虚焦 + 前景人物的参考图压低或不接”有电影学依据。置信度：中（StudioBinder 等）。

---

## 二、详述

### 2.1 为什么 DiT / MMDiT 会串属性

| # | 结论 | 英文原文 | 链接 | 置信度 |
|---|---|---|---|---|
| 1.1 | 注意力层会把不同主体的视觉特征混在一起，交叉注意力和自注意力都会泄漏，语义上不相近的主体之间也会 | “attention layers … tend to blend the visual features of different subjects”；leakage “occurs in both cross-attention and self-attention layers” | https://arxiv.org/abs/2403.16990 ；https://omer11a.github.io/bounded-attention | 高（摘要） |
| 1.2 | Bounded Attention 也只能缓解，不能根除 | 作者承认方法 “does not completely eliminate semantic leakage” | 同上 | 中（二手摘要转述） |
| 1.3 | MMDiT（SD3）描述多个相似主体时仍会漏画或混画；作者归纳了三种歧义，其中语义歧义最难消 | “still suffers from subject neglect or mixing” | https://arxiv.org/abs/2411.18301 | 高 |
| 1.4 | FLUX 同样有实例间属性泄漏 | “Even state-of-the-art models like FLUX and 3DIS face challenges, such as attribute leakage between instances” | https://arxiv.org/abs/2503.12885 | 高 |
| 1.5 | 现有多主体个性化方法普遍有身份混合和属性泄漏，超过 3 个主体就明显变差 | “Existing methods often suffer from identity blending and attribute leakage”；“typically degrade beyond 3 subjects” | https://arxiv.org/abs/2509.01977 （MOSAIC） | 高 |
| 1.6 | 只靠全局文本，管不住单个实体 | “global text prompts alone remain insufficient for achieving fine-grained control over individual entities” | https://arxiv.org/abs/2501.01097 （EliGen） | 高 |
| 1.7 | 多参考图会让身份互相混淆，限制模型能处理的身份数 | “preserving consistent identity while avoiding identity confusion with multi-reference images” | https://github.com/bytedance/UMO | 高 |
| 1.8 | IP-Adapter 类方法在多参考图时会出现物体混淆 | MIP-Adapter：“the current decoupled cross-attention mechanism encounters the object confusion problem” | https://github.com/hqhQAQ/MIP-Adapter | 中（搜索摘要） |
| 1.9 | 编辑模型做多人融合，2509 版本身就弱，2511 才专门加强 | 2511 卡：“further enhances consistency in multi-person group photos” | https://huggingface.co/Qwen/Qwen-Image-Edit-2511 | 高 |
| 1.10 | **Qwen-Image 2.1 机制**：参考图同时走文本编码器和 latent 两条路，并且 “spliced into the sequence”；positive 和 negative 共用同一组参考 latent；没有逐张开关 | “Reference images, seen by the text encoder and spliced into the sequence as VAE latents.”；“When omitted [vae], the reference images condition the result through the text encoder only.” | https://docs.comfy.org/built-in-nodes/TextEncodeQwenImage21 | 高 |
| 1.11 | Qwen-Image 2.1 是 7B、32 层单流 DiT，Qwen3-VL 8B 同时读文字和条件图 | “32 Single-Stream Diffusion Transformer (DiT) layers”；Qwen3-VL 8B “ingests both textual instructions and conditional images concurrently” | https://braindetox.kr/en/posts/qwen_image_2_1_unified_generation_2026.html | 中（第三方技术分析） |

**对我们的推论**（推断，置信度中）：顾沉长出蓝发有三个叠加原因：① 编译层把“雾霾天蓝长直发”写成了无主语句（05 号文已定位）；② 林晚的设定图通过文本编码器和参考 latent 两条路，对全画面的 token 都可见；③ 单流 DiT 里没有任何结构性的“这张参考图只属于左边这个人”的约束。①是确定性 bug，先修。②③只能靠“不把她的图接进来”“把她的图权重压成 0”或者“分区域分遍生成”来解决。

“特写变双人中景”：两个人都要露脸，而 9:16 特写装不下两张脸，模型就退回到 medium two-shot 这种双人的标准景别。社区词汇表把 two-shot 描述为通常是 medium 或 wide（MasterClass）。置信度：中。

### 2.2 ComfyUI 中的分区控制，以及在 Qwen-Image 上是否有效

| # | 方案 | 实现机制 | 支持的模型 | 在 Qwen-Image 2.1 上 | 原文 / 链接 | 置信度 |
|---|---|---|---|---|---|---|
| 2.1 | 原生 Conditioning (Set Mask) / Combine / SetArea | 模型跑完以后，按 mask 把各条件的噪声预测**加权平均**，不碰注意力 | 所有模型 | 能运行，但只是“各画各的再按 mask 拼”。每条条件仍然看得到全部参考图，挡不住参考图串扰，交界处容易出缝或长出“两个人的融合体”。**没查到 Qwen 社区实测** | 源码 `mult = mask * strength`；`out_conds[cond_index] += output[o] * mult[o]`；`out_conds[i] /= out_counts[i]`：https://github.com/comfyanonymous/ComfyUI/blob/master/comfy/samplers.py 。官方讨论：ComfyUI 用 “explicit spatial masks … rather than splitting prompts across attention regions”：https://github.com/Comfy-Org/ComfyUI/discussions/13741 | 高（机制）/ 未查到（Qwen 实测） |
| 2.2 | attention couple（laksjdjf → Danand/ComfyCouple） | UNet 交叉注意力补丁 | SD1.5/SDXL（示例是 MeinaMix） | 没有证据能用（Qwen 没有 UNet 的 attn2） | “not quite actual regional prompting”：https://github.com/Danand/ComfyUI-ComfyCouple （GPL-3.0）。另一处说 Attention Couple 是 “SDXL-era form of regional prompting”：https://comfy.icu/node/PromptChain_AttentionCouple | 中 |
| 2.3 | Regional-Prompting-FLUX（InstantX） | 把 FLUX 的联合注意力拆成 4 块（img→txt、txt→img、img self、txt self），分别加 mask | FLUX.1-dev（README 只写 “Diffusion Transformers (i.e., FLUX)”） | 不适用 | 参数：`mask_inject_steps` “recommended between 5-10”；`double_inject_blocks_interval` “1 means strongest control”；`base_ratio` “smaller means stronger control”（示例 0.1–0.3）。分割 mask 的精确约束是 “experimental… not perfectly constrained”：https://github.com/instantX-research/Regional-Prompting-FLUX ；论文 https://arxiv.org/abs/2411.02395 | 高 |
| 2.4 | ComfyUI-Fluxtapoz（logtd） | 2.3 的 ComfyUI 实现 | Flux | 不适用 | “You can combine it with Redux, but Redux is so powerful it dominates the generation.” 示例 `example_flux_regional.json`，GPL-3.0：https://github.com/logtd/ComfyUI-Fluxtapoz | 高 |
| 2.5 | RES4LYF regional conditioning | 自带采样器 | “HiDream, Flux, Chroma, SD3.5, SD1.5, SDXL, AuraFlow, and WAN” | **不支持 Qwen**；节点在普通采样器上 “No effect on a stock sampler” | https://github.com/ClownsharkBatwing/RES4LYF ；https://comfy.icu/node/ClownRegionalConditioning_ABC | 高 / 中 |
| 2.6 | Dense Diffusion（ComfyUI_densediffusion） | 调制 UNet 注意力 | SD 系 | 没有 Qwen 证据 | Reddit 上有人被推荐去用它：https://redlib.belloworld.it/r/comfyui/comments/1glt8ly/flux_regional_prompting_in_comfyui_today/lvwzst1/ | 低 |
| 2.7 | **EliGen（DiffSynth）** | 微调过的区域注意力 LoRA：每个实体一段 prompt + 一张任意形状 mask | **Qwen-Image（20B v1）**，也有 FLUX 版 | **2.1 没有对应权重**（底模不同：20B 双流 vs 7B 单流）。要用只能切回 Qwen-Image 20B | “enables control over the position and shape of each entity”；`eligen_entity_prompts` / `eligen_entity_masks`；Apache-2.0；0.2B：https://huggingface.co/DiffSynth-Studio/Qwen-Image-EliGen | 高 |
| 2.8 | EliGen 的 ComfyUI 封装（fblissjr/ComfyUI-QwenImageWanBridge） | 每个实体 mask + prompt + 权重，最多 4 个 | Qwen-Image | 作者把它列在 “Experimental Nodes (Available but likely not working or deprecated)” | https://github.com/fblissjr/ComfyUI-QwenImageWanBridge （MIT） | 高 |
| 2.9 | ComfyUI-Krea2-Regional（januspluto） | 单遍联合注意力 mask：“a joint attention mask keeps each region's image tokens attending only to their own prompt”；LoRA 按 token 门控 | Krea 2（用 Qwen-Image VAE 和 Qwen3.5 VL 编码器） | **不是 Qwen-Image 2.1**；可以作为“在单流 DiT 上做区域注意力”的参考实现，将来移植。作者承认 “Some soft bleed through the shared base prompt is inherent to single-pass regional attention.” | https://github.com/januspluto/ComfyUI-Krea2-Regional （MIT） | 高（README） |
| 2.10 | **Qwen Image 2.1 Reference Strength / Masked**（capitan01R → fork deng232） | 在原生 Qwen Image 2.1 注意力里，对某张参考图的全部 key 加 `log(w)`；w=0 就把直接注意力屏蔽掉；Masked 版本按参考图坐标系里的 mask 逐 token 调权 | **原生 Qwen Image 2.1** | **可用，而且正对我们的问题**。不过它是“按参考图”调，不是“按输出区域”调：README 写 mask 选的是 “source reference tokens, not output pixels”。另有提醒 “Information about it can remain elsewhere in the conditioning”（文本编码器那条路） | https://github.com/deng232/ComfyUI-qwen_img_2_1_enhancer （MIT；原仓库 github.com/capitan01R/ComfyUI-qwen_img_2_1_enhancer 本次访问 404）。要求 “Attention backends must support additive masks.” | 中（README，未实测） |
| 2.11 | Flux 在 ComfyUI 里的常见失效原因 | Flash Attention 会把补丁替换掉；方框 mask 重叠就会泄漏，建议用 SAM 分割 mask | — | 对 2.10 同样适用：要确认注意力后端支持 additive mask | https://zanno.se/enhanced-regional-prompting-with-comfyui/ ；https://www.runflow.io/blog/comfyui-regional-prompting | 低到中 |

**小结：** Qwen-Image 2.1 上，目前查到的唯一“原生可插”的控制是 2.10（按参考图调权），没有可用的“按输出区域分 prompt / 分参考图”的节点。真正的区域注意力要么换底模（Qwen-Image 20B + EliGen；Flux + Regional Prompting），要么自己移植（参考 2.9）。社区里**没查到** “Qwen-Image + Conditioning Set Mask 双人” 的实测帖。

### 2.3 两步法（先构图，再逐人局部重绘，各挂单人参考）

| # | 结论 | 英文原文 | 链接 | 置信度 |
|---|---|---|---|---|
| 3.1 | 双人同时输入时脸会互相漂移，衣服不会；分辨率越高越容易融合，建议 1–1.5MP | “Two-person inputs keep outfits distinct but faces drift toward each other.”；“the two identities may blend together” | https://huggingface.co/Ty6666667/krea2-identity-edit （Krea 2 社区 LoRA，不是 Qwen） | 中 |
| 3.2 | 当前可行的 workaround 是串行单参考插入 | “chain single-ref inserts (place person A, then a second edit pass adding person B from their reference)” | 同上 | 中 |
| 3.3 | 也有相反意见：krea2edit 节点作者认为一遍同时放两人比串行可靠 | 节点 wiki：simultaneous placement “currently more reliable than chaining”（转述）；InstaSD 指南则说串行 “slow, but it keeps faces distinct” | https://github.com/lbouaraba/comfyui-krea2edit/wiki ；https://www.instasd.com/post/krea-2-identity-edit-comfyui-guide | 中 / 低，**需要我们自己 A/B** |
| 3.4 | Qwen Image 2.1 局部重绘链：`LoadImage(mask) → GrowMaskWithBlur → SetLatentNoiseMask → TextEncodeQwenImage21(参考) → KSamplerAdvanced → VAEDecode` | “Applies a noise mask so new signal is introduced primarily inside the region you painted”；unmasked 区域 “not frozen at the pixel level” | https://www.runcomfy.com/comfyui-workflows/qwen-image-2-1-inpainting-in-comfyui-no-offset-edits | 中 |
| 3.5 | Qwen Image 2.1 官方的局部编辑方式：画圈、画笔标记、mask 节点；可以在提示里点名标记的颜色 | “Local edits can be aimed with a circle, a painted annotation or a mask node.”；“Naming the mark's color in the prompt points the instruction at that region” | https://comfyui-wiki.com/en/news/2026-09-21-qwen-image-2-1 ；https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1.md | 高 / 中 |
| 3.6 | LanPaint 支持 Qwen Image 2.1 / Edit 2509/2511 的 mask 重绘，质量更高但更慢 | Qwen Image 2.1 edit “now works under a LanPaint mask”；默认 5 次 thinking “5 times slower”；对蒸馏模型 “degraded performance”；GPL-3.0 | https://github.com/scraed/LanPaint | 高（README） |
| 3.7 | 裁切—重绘—缝回：Inpaint Crop (Improved) / Stitch 只在 mask 附近按目标分辨率采样，再无缝贴回 | “stitches the inpainted image back into the original image without altering unmasked areas”；`mask_blend_pixels` 用来消缝 | https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch | 高 |
| 3.8 | 人物分割：Impact Subpack 的 `UltralyticsDetectorProvider` + `segm/person_yolov8m-seg.pt` → SEGM Detector 出 mask；方框 mask 重叠会泄漏，优先用分割 mask | Subpack “no longer installed automatically” since V8.0 | https://github.com/ltdrdata/ComfyUI-Impact-Pack ；https://comfyonline.app/comfyui-nodes/nodes/UltralyticsDetectorProvider | 中 |
| 3.9 | 用编辑模型做 inpaint 的好处：结果会参照原图 | LanPaint 建议用 Qwen Image Edit 来 inpaint，“when you want the result to reference the original image”（转述） | https://github.com/scraed/LanPaint | 中 |

**社区工作流链接：** RunComfy “Qwen Image 2.1 Inpainting”（3.4）；LanPaint 仓库里的 Qwen Edit 2509 inpaint 示例；MyAIForce “LanPaint + Qwen Image Edit 2509” https://myaiforce.com/lanpaint-qwen-image-edit-2509/ （限制 1MP、先裁再贴回）。**没查到**“SAM/YOLO 人物分割 → Qwen 编辑模型单人参考重绘 → 双人”的完整现成工作流，需要自己拼。

### 2.4 逐人参考注入

| # | 结论 | 英文原文 | 链接 | 置信度 |
|---|---|---|---|---|
| 4.1 | Qwen-Image-Edit-2509/2511（diffusers）每张图自动加前缀 `Picture N:`；送进文本编码器的图约 384×384 面积，送进 VAE 的约 1024×1024 | `"Picture {}: <\|vision_start\|><\|image_pad\|><\|vision_end\|>"`；`CONDITION_IMAGE_SIZE = 384 * 384`；`VAE_IMAGE_SIZE = 1024 * 1024` | https://github.com/huggingface/diffusers/blob/main/src/diffusers/pipelines/qwenimage/pipeline_qwenimage_edit_plus.py | 高（源码） |
| 4.2 | Qwen-Image 2.1 按序号写 `<image1>`…，参考图 “spliced into the text encoder in slot order”；节点最多 16 槽，官方说法是最多 10 张；第一张图决定 latent 尺寸 | “the prompt addresses them by index, for example `image_1` is written as `<image1>`”；示例 “Keep the character and pose in <image1> unchanged, put this light blue denim shirt from <image2> on the character” | https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1.md | 高 |
| 4.3 | 官方多人示例用“角色 + 位置”的写法 | “The magician bear is on the left, the alchemist bear is on the right, facing each other in the central park square.” | https://huggingface.co/Qwen/Qwen-Image-Edit-2511 | 高 |
| 4.4 | 2511 宣称加强了多人合影的一致性；2.1 宣称能把 6 张人像合成一张合影 | “further enhances consistency in multi-person group photos”；“One group photograph generated from six portrait references.” | 2511 卡；https://comfyui-wiki.com/en/news/2026-09-21-qwen-image-2-1 | 高（厂商自述，没有独立评测） |
| 4.5 | 社区写法 “Figure 1 / Figure 2” 指代输入图 | dx8152 的 2509 工作流示例 | https://huggingface.co/dx8152/Qwen-Edit-2509-workflow/blob/main/README.md | 中 |
| 4.6 | Kontext 多参考的建议：给每张参考图写明分工；不要用互相冲突的参考，除非写明以哪张为准 | Dev Multi “reference 1 for face identity and reference 2 for hairstyle”（转述） | https://wavespeed.ai/docs/docs-api/wavespeed-ai/flux-kontext-dev-multi | 低（API 厂商文档） |
| 4.7 | 拼图（side-by-side）技巧：**没查到**能说明它对 Qwen-Image 2.1 降串扰有效的来源。2509 官方是 “trained via image concatenation”，但那是训练方式，不是用法建议 | — | Qwen-Image-Edit-2509 模型卡 | 未查到 |
| 4.8 | “哪种写法串扰最少”：**没查到**对照实测 | — | — | 未查到 |
| 4.9 | PuLID-Flux（balazik）的 `attn_mask` 不工作；lldacing 的 PuLID Flux II 有 attn_mask，双人时 Load Image 顺序有影响 | balazik changelog：attn_mask “not working”（转述） | https://github.com/balazik/ComfyUI-PuLID-Flux ；https://www.runcomfy.com/comfyui-workflows/pulid-flux-ii-in-comfyui-identity-preserving-ai-generation | 中 / 低 |
| 4.10 | PuLID-Flux-Chroma 多脸融合（mean/concat/max）是把身份**合起来**，不是分区 | — | https://github.com/PaoloC68/ComfyUI-PuLID-Flux-Chroma | 中 |
| 4.11 | InstantID 双人：两个 InstantID 节点各配一张 mask；cubiq 仓库只支持 SDXL，据称已进入维护模式 | “enables the creation of images featuring two individuals by using two InstantIDs” | https://runcomfy.com/comfyui-workflows/comfyui-instantid-workflow ；https://github.com/cubiq/ComfyUI_InstantID | 中 / 低 |
| 4.12 | UMO（ByteDance）：底模 UNO / OmniGen2，有 ComfyUI 工作流，代码 Apache-2.0 | “The ComfyUI workflows of UMO are released” | https://github.com/bytedance/UMO ；https://huggingface.co/bytedance-research/UMO | 高 |
| 4.13 | XVerse：FLUX.1-dev，开 `use_low_vram` 后 24GB 能跑两张条件图；**没有 ComfyUI 实现**（还在 TODO）；代码 Apache-2.0 | “can run the XVerse model in 24GB VRAM”；TODO “Release ComfyUI implementation” | https://github.com/bytedance/XVerse | 高 |
| 4.14 | MOSAIC：ICLR 2026 论文，**没查到公开代码** | — | https://arxiv.org/abs/2509.01977 | 中 |
| 4.15 | UniPortrait：ID routing 给每个人脸区域分配唯一 ID，防止 ID 特征混合（SD 系） | routing “to prevent feature mixing between IDs”（转述） | https://arxiv.org/abs/2408.05939 | 中 |
| 4.16 | OmniGen2：ComfyUI 原生支持，Qwen2.5-VL 3B + 4B DiT，Omni-RoPE 支持 “identity distinction”；许可证本轮没查到 | — | https://docs.comfy.org/tutorials/image/omnigen/omnigen2.md ；https://blog.comfy.org/p/omnigen2-native-support-in-comfyui | 中 |

### 2.5 镜头设计层面的规避（编译规则依据）

| # | 规则依据 | 英文原文 | 链接 | 置信度 |
|---|---|---|---|---|
| 5.1 | 单人镜：任何景别都可以，只要画面里只有一个人 | single shots “can be set and framed in any shot size you like, just as long as there is only one character featured within the frame” | StudioBinder 框架指南（经第三方转载）；https://www.studiobinder.com/camera-shots/framing/over-the-shoulder-shot/ 同站 | 中 |
| 5.2 | 过肩镜：前景是后脑和肩膀，通常虚焦；是对话戏最常用的构图 | “including the back of the head and shoulder in the foreground (typically out of focus)”；“one of the most common framing devices for conversation scenes” | https://www.studiobinder.com/camera-shots/framing/over-the-shoulder-shot/ | 高 |
| 5.3 | 过肩镜是单人镜和双人镜的混合；对话里正反打交替使用 | OTS “fusing a single shot (or one-shot) with a two shot” | https://www.masterclass.com/articles/over-the-shoulder-shot | 中 |
| 5.4 | 双人镜通常是中景或全景，这解释了“特写 + 两人露脸”为什么会塌成中景 | two shot “usually uses a medium shot or a wide shot angle” | 同上；https://en.wikipedia.org/wiki/Two_shot | 中 |

据此写编译规则（推断，置信度中）：
- 特写 / 近景 = 单人镜：只写在画的这一个人，只接这一个人的参考图。另一个人只能以“画外”“手部入画（不露头发和脸）”的方式出现。
- 过肩：前景人物写成“后脑和肩膀，虚焦，占画面边缘”。参考图只接焦点人物；前景人物的参考图不接，或者 Reference Strength ≤ 0.3。前景人物的发色要在文本里明确写给他本人，因为背影最容易被认成焦点人物的发型。
- 双人露脸：最低近景双人（medium close two-shot），禁止叫“特写”。左右位置要固定，每人一段描写（05 号文的 F2）。

---

## 三、方案总表

| 方案 | 能解决什么 | Qwen-Image 2.1 上可用 | 3090 可行性 | 速度（相对单张出图） | 许可证 | 权重 / 来源 |
|---|---|---|---|---|---|---|
| S0 编译层：单人镜规则 + 每人一段 + 只接在画人物的参考图 | 特写塌景别、参考图串扰的大部分 | 是（不改模型） | — | 1× | — | — |
| S1 Reference Strength（=0 屏蔽不在画/背影人物的参考图） | 参考 latent 那条路的串扰 | **是**（原生 2.1 补丁） | 可以，无额外显存（推断） | ≈1×（推断） | MIT | 纯代码，无权重：github.com/deng232/ComfyUI-qwen_img_2_1_enhancer |
| S2 两步法：先整图构图 → YOLO/SAM 人物分割 → 每人一遍 SetLatentNoiseMask 重绘，只挂单人参考（可加 Crop&Stitch） | 双人露脸的串扰（主解法） | **是** | 可以（主模型复用；bf16 DiT 约 14.2GB，text encoder 用 int8） | 约 3×（1 遍构图 + 2 遍重绘；局部裁切后每遍更快）。估算，需实测 | Qwen-Image 2.1：**Qwen Research License（非商用，商用要单独授权）**；节点 GPL/MIT | person_yolov8m-seg.pt（ComfyUI-Manager 下载）；可选 SAM2 |
| S2' 同 S2，重绘用 LanPaint | 边缘融合更好 | 是 | 可以 | 每遍约 5×（README 原文） | GPL-3.0 | 无权重 |
| S3 EliGen 区域注意力 | 单遍分区 prompt | **否**（只有 Qwen-Image 20B 版本） | 20B 需要 fp8/GGUF + offload，偏紧（推断） | 约 1–1.3×（推断） | Apache-2.0 | DiffSynth-Studio/Qwen-Image-EliGen（0.2B） |
| S4 Flux 支线：Regional-Prompting-FLUX（Fluxtapoz）+ PuLID/Redux 逐人 | 单遍分区 | 否（换底模） | FLUX.1-dev fp8 可以 | 约 1.2–1.5×（推断） | FLUX.1-dev 非商用；Fluxtapoz GPL-3.0 | black-forest-labs/FLUX.1-dev |
| S5 Krea2-Regional 思路移植到 Qwen 2.1 | 单遍分区 prompt + LoRA 门控 | 需要二次开发 | — | ≈1× | MIT（参考代码） | — |
| S6 UMO（OmniGen2/UNO）、XVerse（FLUX） | 多 ID 一次出 | 否 | XVerse 24GB 能跑两张条件图；UMO 显存未查到 | 未查到 | 代码 Apache-2.0；底模各有许可 | bytedance-research/UMO；bytedance/XVerse |
| S7 原生 Conditioning Set Mask / attention couple | — | 能运行但**挡不住参考串扰** | 可以 | 2×（每条条件各跑一次） | GPL-3.0（ComfyUI） | — |

> 许可证提醒（置信度中，多个二手来源一致）：Qwen-Image 2.1 是 **Qwen Research License**（非商用研究），不是 Apache；Qwen-Image-Edit-2511 / 2512 是 Apache-2.0。正式上线前这条需要项目方确认。

---

## 四、推荐给我们的 A/B 方案（按优先级）

前提：05 号文的 F1–F3（删句保主语、逐人绑定、特写 + 两人露脸判冲突）先合入。下面是合入以后的模型层 A/B。

### A 方案（默认链，先上）：单人镜规则 + 参考图按镜筛选 + Reference Strength

1. **编译层（确定性）**
   - 镜头人数 = 1（特写 / 近景 / 单人中景）：`TextEncodeQwenImage21.images` 只接这个人的身份图，另一个人的图**不接**。提示里只出现这一个名字。
   - 过肩：焦点人物的图放 `image_1`；前景人物的图要么不接，要么放 `image_2` 并压低权重（见第 3 步）。文本写“画面左下前景：顾沉的后脑和右肩，黑色短发，虚焦”。
   - 双人露脸：最低“近景双人”。每人一段：“画面左侧：<image1> 中的林晚，雾霾天蓝及腰直发…；画面右侧：<image2> 中的顾沉，黑色短发向后梳…”，左右位置在全集固定。发色、发长要在每人自己那段里正面写出来，不要只靠参考图。
2. **参数起点**：Turbo 8 步，cfg 1，euler，ManualSigmas（官方 Turbo 模板）。`resolution` 1024（参考图）。输出约 1.0–1.5MP（Krea 社区经验：分辨率高了双人身份更容易融合，Qwen 上待验证）。
3. **Reference Strength 节点**（deng232 fork）：放在 `TextEncodeQwenImage21` 和采样器之间。
   - 过肩前景人物：strength 0.0–0.3。
   - 双人露脸：两张都是 1.0 作为基线，再做 A/B：给每个人的参考图配一张 Reference Strength Masked 的 mask，只放行设定图里**脸 + 头发**区域的 token（`zero_unmasked_tokens`），减少服装、背景信息外流。
   - 先确认注意力后端支持 additive mask，ComfyUI 不要开 flash-attention 的强制参数。
4. **闸门**：逐人属性探针（发色、发长、指甲）对双人镜阻断（05 号文 F4）。不通过就自动进入 B 方案。

### B 方案（双人露脸、A 不过闸时）：两步法 —— 构图 → 分割 → 逐人单参考重绘

节点链：
```
[第1遍 构图]
TextEncodeQwenImage21(prompt=双人布局+中性占位描述, images=无 或 仅场景图)
  → KSampler(Turbo 8步, cfg1) → VAEDecode → IMG0
  * 占位写法：两人的发色/服装写中性（如“深灰色头发”）或者干脆不写，只写站位、姿态、景别、光
    也可以只接一张“场景/姿态参考”，不接任何身份图

[分割]
UltralyticsDetectorProvider(segm/person_yolov8m-seg.pt) → SEGM Detector(SEGS)
  → 按 bbox 中心 x 排序，取左 = 林晚，右 = 顾沉（位置与编译层一致）
  → SEGS to Mask → GrowMaskWithBlur(expand 16–24px, blur 8–12)
  * 双人贴得很近、遮挡时：改用 SAM2 点提示（bbox 中心）细化

[第2遍 重绘林晚]
Inpaint Crop (Improved)(IMG0, mask_L, context_from_mask_extend_factor≈1.5–2.0, target≈1024)
  → TextEncodeQwenImage21(prompt="<image1> 是重绘底图；把蒙版内人物替换为 <image2> 中的林晚，保持姿态和光线，蒙版外保持不变",
                          images=[crop底图, 林晚身份图], vae=接)
  → SetLatentNoiseMask(mask_L_crop)
  → KSamplerAdvanced(Turbo 8步, cfg1；denoise 0.6–0.8 起步，脸/发色不到位再升到 0.9)
  → VAEDecode → Inpaint Stitch(mask_blend_pixels 16–32) → IMG1

[第3遍 重绘顾沉] 同上，用 IMG1 + mask_R + 顾沉身份图。prompt 里写出“黑色短发”
  * 重绘顾沉时，林晚的身份图绝对不接

[可选] 最后整图 denoise 0.15–0.25 低强度统一光色（不接任何身份图），或用 LanPaint（NumSteps 5）替换第 2、3 遍以改善边缘
```
A/B 对照项（IMGLAB 实测时一起跑）：
- B1 串行（如上） vs B0 单遍两张参考图同时接（现状）。Krea 社区两种意见都有，以我们的闸门数据为准。
- 重绘底模用 Qwen-Image 2.1 Edit 流程（接 crop 底图作 `<image1>`） vs 纯 SetLatentNoiseMask 不接底图。
- denoise 0.6 / 0.75 / 0.9 × 重绘遍数顺序（先林晚 / 先顾沉）。
- mask 用方框还是分割：社区经验是方框重叠会泄漏，默认用分割。

### C 方案（研究储备，不进主链）
- C1 移植 Krea2-Regional 的“联合注意力 mask + LoRA 按 token 门控”到 Qwen Image 2.1 的单流注意力（MIT 参考代码），配合 Reference Strength 实现“某张参考图只对某个区域的图像 token 可见”。这才是根治单遍串扰的结构，需要开发工作量。
- C2 Qwen-Image 20B + EliGen（Apache-2.0）做单遍分区的对照基线。ComfyUI 封装被作者标为可能不可用，需要用 DiffSynth 原生管线跑。
- C3 Flux 支线（Regional-Prompting-FLUX + PuLID）只作对照；许可证（FLUX.1-dev 非商用）和画风统一都是问题。

---

## 五、需下载清单（本次没下载）

| # | 物品 | 用途 | 方案 | 来源 | 大小 / 许可 |
|---|---|---|---|---|---|
| D1 | ComfyUI-qwen_img_2_1_enhancer（deng232 fork；原 capitan01R 仓库 404，先确认新地址） | Reference Strength / Masked | A | https://github.com/deng232/ComfyUI-qwen_img_2_1_enhancer | 纯代码，MIT |
| D2 | ComfyUI-Impact-Pack + **ComfyUI-Impact-Subpack** | YOLO 人物分割 | B | https://github.com/ltdrdata/ComfyUI-Impact-Pack （Subpack 同作者） | 代码 GPL-3.0 |
| D3 | `segm/person_yolov8m-seg.pt` | 人物 mask | B | ComfyUI-Manager 模型列表（Ultralytics） | 约 50MB（知识，本轮未核验）；Ultralytics 权重是 AGPL-3.0，商用需留意（知识，未核验） |
| D4 | ComfyUI-Inpaint-CropAndStitch（v3.0.17+，用 Improved 节点） | 裁切—重绘—缝回 | B | https://github.com/lquesada/ComfyUI-Inpaint-CropAndStitch | 纯代码（GPL-3.0，知识） |
| D5 | KJNodes（GrowMaskWithBlur），多数环境已经有 | mask 扩边羽化 | B | https://github.com/kijai/ComfyUI-KJNodes | 纯代码 |
| D6（可选） | LanPaint | 高质量 mask 重绘 | B 变体 | https://github.com/scraed/LanPaint | 纯代码，GPL-3.0 |
| D7（可选） | SAM2 节点 + sam2.1_hiera_large | 贴身 / 遮挡时细化 mask | B 变体 | 例如 kijai/ComfyUI-segment-anything-2 | 约 0.9GB（知识，未核验），Apache-2.0 |
| D8（研究） | ComfyUI-Krea2-Regional 源码（只读来参考移植） | C1 | C | https://github.com/januspluto/ComfyUI-Krea2-Regional | MIT |
| D9（研究） | Qwen-Image 20B + Qwen-Image-EliGen LoRA + DiffSynth-Studio | C2 | C | https://huggingface.co/DiffSynth-Studio/Qwen-Image-EliGen | LoRA 0.2B 参数，Apache-2.0；20B 底模 bf16 约 40GB（知识） |

主模型权重（Qwen-Image 2.1 Turbo / VAE / Qwen3-VL 8B int8）已在用，不需要新下。

---

## 附：没查到的项目（如实记录）
- Qwen-Image / Qwen-Image 2.1 上原生 Conditioning Set Mask、attention couple 的双人实测帖：未查到。
- `<image1>的男人 / <image2>的女人` 和“左/右位置写法”、拼图写法三者的串扰对照实测：未查到。
- Qwen-Image 2.1 Turbo 在 3090 上的单张耗时：官方没给，未查到。
- 现成的“SAM/YOLO 分割 → Qwen 编辑模型单人参考重绘 → 双人”完整工作流：未查到，需要自己拼（B 方案）。
- MOSAIC 代码、OmniGen2 许可证、UMO 显存：未查到。
- RPG（Recaptioning, Planning, and Generating, arXiv 2401.11708）：本轮没打开原文，只按已知信息归类为“LLM 先规划区域再做区域扩散”的 UNet 时代方法，对 Qwen 2.1 不适用（置信度低）。
