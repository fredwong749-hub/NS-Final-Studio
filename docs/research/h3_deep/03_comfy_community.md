# H3 深挖 03：ComfyUI 集成 + 真实用户质量反馈（颜色 / 身份 / 镜头一致性）

调研日期：2026-10-30。只读调研：没装东西，没用 GPU，没 ssh。
按 owner 2026-10-30 的指示：**以社区实测反馈为准**，官方文字只作背景。每条建议标注“独立用户数 / 硬件 / 模式 / 反对意见”。

置信度：**高** = 源码或官方明文；**中** = ≥2 个独立用户实测一致；**低** = 单帖或我的推断。

> **重要限制：Reddit 无法访问。** WebFetch 对 reddit.com / old.reddit.com 直接报 “unable to fetch”，WebSearch 对 reddit.com 返回 “domains are not accessible to our user agent”，普通搜索也没有出现任何 r/StableDiffusion、r/comfyui 的帖子。所以本报告的“社区”来源是 **GitHub issues、HuggingFace discussions、note.com、custom node 的 README**。Reddit 和 civitai 评论需要人工打开浏览器补查（见 §8）。

---

## 0. 对 `h3_prompt_and_fl2v.md` 的更正与补充

| 原文说法 | 更正/补充 | 依据 | 置信度 |
|---|---|---|---|
| “镜头间色调跳变……Comfy #67 高分辨率（≈1.3MP）下变暗；我们是 1MP，风险较低” | **说反了。** #67 的原文里，1.3MP 是 FL2V 的“全黑 iris-out”，而“轻度变暗”在 I2V **768×960 及以上**就出现：“A milder version (background dims by ~10–25 luminance levels in the first ~1.5 s and stays dim) happens with I2V at 768x960 and above.” 768×1344 比 768×960 更大，**在风险区内** | <https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/67> | 低-中（单用户，但有具体测量） |
| “ToneCompensate（rkfg）没找到仓库” | **找到了**：<https://github.com/rkfg/ComfyUI-MiniMaxH3-ToneCompensate>。README：“H3 denoiser applies a tone bias to each generated segment”，“tends to run darker than the anchored keyframes” | 同左 | 中（作者 + dntpi 移植后实测） |
| “身份 LoRA 没找到” | musubi-tuner、ai-toolkit、DiffSynth-Studio 都已支持 H3 LoRA 训练，并且 musubi 文档明确有 FL2VA 的身份训练方案（teacher matching `first,last`）。见 §6 | musubi docs | 高（支持）/ 低（效果） |
| “Ref2VA 不能和首尾帧一起用”（原文没写，但默认如此） | **可以。** ComfyUI 官方 multiframe 模板本身就是 ref2va 模型 + Reference to Video 节点 + 串联 Add Guide。见 §4 | docs.comfy.org multiframe | 高 |
| w4a8 + LoRA 兼容性“低-中” | 新增一个**源码级 bug 报告**：W4A8 量化 + LoRA 时，`adaln_proj` 层的 LoRA delta“silently never applies”（ComfyUI #16420，到 v0.42.1 仍在）。加上 kingp0dd 的不兼容报告，**建议直接换 int8_convrot** | <https://github.com/Comfy-Org/ComfyUI/issues/16420> | 中 |

---

## 1. ComfyUI 核心 H3 节点（源码事实）

来源：<https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py>（置信度：高）

- 节点：`EmptyMiniMaxH3LatentAV`、`MiniMaxH3ImageToVideo`（first_frame / last_frame）、`MiniMaxH3AddGuide`、`MiniMaxH3ReferenceToVideo`、`MiniMaxH3SigmaShift`（默认 `shift_video 12.0`、`shift_audio 3.0`）、`MiniMaxH3FunControlNetApply`、`MiniMaxH3LatentUpscaleWithModel`。
- 首尾帧处理：`img = _resize(first_frame[:1], width, height, "disabled")`，注释写 `# geometry anchor: plain stretch to canvas`；`img = _resize(last_frame[:1], width, height, "center")`，注释写 `# follower: aspect-preserving cover-crop`。**和原文一致。**
- 关键帧编码：`kf["latent"] = vae.encode(kf.pop("image"))`，挂到 `cond` 的 `"minimax_keyframes"`。**没有 strength 参数，编码前也没有任何颜色或范围转换**：`_resize` 只取 `image[..., :3]`，然后做 lanczos 缩放。
- AddGuide：没有 strength 参数；多帧 guide 会被截到 17k+5 长度（`while guide_frames % 17 != 5`），少于 5 帧时只用第 1 帧；guide 的缩放方式是 `"center"`。
- Ref2VA：`ref_image_` 最多 9 张，视频、视频音频、独立音频各最多 3 个；`ref_image_size` 可选 `match`（缩到画布面积）或 `max`（短边 2048）。
- latent 形状：24 通道，空间压缩 16，`latent_t = ((frame_count - 5) // 17) * 5 + 2`。
  - **按我们的参数算**：243 帧 → 72 个 latent 帧；768×1344 → 48×84，按 2×2 patch 是 1008 token/帧，总共约 72.6k 视频 token，加两个关键帧约 76k。这个数字**低于** KJ Sage 补丁 int32 溢出的阈值（约 199.7k，见 §2.4）。置信度：中（patch 2×2 依据 Comfy 文档“masks snap to the 2×2 latent patch grid”）。

### 1.1 2026-08-01 以来与质量相关的 commit
来源：<https://github.com/Comfy-Org/ComfyUI/commits/master/comfy/ldm/minimax>、`…/comfy_extras/nodes_minimax_h3.py`

| 日期 | commit | 和我们的关系 |
|---|---|---|
| 08-06 | #15243 Fix sampler issues for audio with minimax | 音频破音 |
| 08-13 | #15439 Add MiniMaxH3AddGuide | 中间关键帧 |
| 08-18 | #15375 per-token noise masks（引出 #15981 网格伪影，09-08 由 #15988 修复） | 确认版本 ≥ 包含 #15988 |
| 09-22 | **#16436 Blend H3 VAE tiles against composited neighbours**（修 tile 交界处的“step”） | 9:16 tile 线（#15885）可能与此有关，需确认 gpu3 版本 ≥ 09-22 |
| 10-10 | **#16881 Decode single images as the first latent of a clip**（单图解码从“dark and banded, ~17 dB”提升到“~31.0 dB”） | 只影响单图**解码**，不影响 FL2V 关键帧编码（PR 没提） |
| 10-15 / 09-29 / 10-28 | LightVAE、LynnReal light VAE、Sol-H3-VAE | 第三方 VAE；Sol-H3-VAE 已经有 issue #17429 报告“faint seams on the 128-px attention-window grid (visible on smooth skin)”，**皮肤特写别用** |
| 10-28 | #17412 latent upscaler model | PR 没有给质量结论 |

**没有找到**任何专门修改“颜色”“关键帧强度”或“FL2V 条件”的 commit。

---

## 2. 颜色：洗白、偏色、变暗、对比度漂移

### 2.1 社区观察（按独立用户数排序）

| 现象 | 独立用户 | 模式 / 硬件 | 原文 |
|---|---|---|---|
| 续接（chain）时**对比度和饱和度逐段上升**，像 CFG 烧糊 | 至少 6 人：Storm2831、tritant（ComfyUI_MiniMax_H3_Extender #15）、SveSop、NikoDemon80（H3-Motion-Context #20）、SG0102（#9）、lesca（#44）、Deelight-fr，另有 Context-Loop #98 | 续接，Euler simple 50 步，**不加 Turbo 也有** | “Each time a clip is generated to extend a video, the contrast of the video increases, like increasing CFG burn-in.” <https://github.com/tritant/ComfyUI_MiniMax_H3_Extender/issues/15> |
| 输出比参考**“slightly hotter and slightly duller”**；暗部压死、高光溢出；作者已排除 VAE、色彩空间和 range | NikoDemon80（维护者，有测量：每个接缝约 4%，第 8 段对比度约 +40%） | 续接 | “That reproduction is not neutral: it comes back slightly hotter and slightly duller than the thing it was copying.” <https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context/issues/20> |
| 生成段**比锚定关键帧暗** | rkfg（README）；dntpi 移植后测得 5.6/255 → 0.3/255 | 续接 | “tends to run darker than the anchored keyframes” <https://github.com/rkfg/ComfyUI-MiniMaxH3-ToneCompensate> |
| 前约 1.5 s 背景变暗 10–25 个亮度级，之后一直偏暗；某些种子在 1.3MP 下全黑 | reasy0000（1 人，RTX 5090，测了 12 个种子） | **FL2V / I2V**，4-step v1.2，res_multistep，shift 12 | 见 §0；同帖还写了 “`euler` instead of `res_multistep` roughly halves the mild I2V dimming” <https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/67> |
| 皮肤发白或偏紫（lilac），黑衣和头发泛紫，画面变暗 | lovemachine100（1 人，有 dE 测量） | 续接 | “pale/lilac skin, purple sheen on black clothes and hair, darker picture” <https://github.com/lovemachine100/ComfyUI-H3-ClipColorAnchor> |
| Ref2VA 自由生成的帧里脸颊出现红斑 | hidetaro7（1 人） | Ref2VA，不加 LoRA 也有；384 正常、512 出现 | “an unnatural, cartoon-like red patch appears on the subject's cheeks.” <https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/55> |
| 图像经 VAE 编码再解码后**颜色有差异**，纯色背景最严重 | 4 人（l13462580123、JBARU、yuxiao11、rocky533）；rocky533 认为“its the add guide node that does this.” | 编码/解码 | <https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/78> |
| 每 17 帧出现一次暗帧（约 -30 亮度）并卡顿 | happy-fuckingday、Bloodwolfb（2 人）；只出现在 **full INT8 / BF16**，**pruned 没有** | 所有模式 | “Frame brightness every 17th frame (VAE clip_length=17 boundary) drops ~30 units” <https://github.com/Comfy-Org/ComfyUI/issues/15426>、<https://github.com/MiniMax-AI/MiniMax-H3/issues/85> |
| Turbo LoRA **强度不对时颜色偏暗或过曝** | sdqq1234（强度 0.75 时偏暗）、TawusGames（“low strength darkens colors and high strength makes them blow out”）；对强度另有分歧（vladulidlo 建议 0.5） | FL2V 4-step v0.1 | <https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/9> |
| 4-step **v1.1 “seems too dark”**，v1.0 最干净，v1.2 改动原图太多 | ApexArtist（1 人，用于 upscale pass） | FL2V 4-step | <https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/54> |
| KJ MemEff Sage 补丁在高分辨率下输出发灰；换 Kitchen 后正常 | sol-zs451（1 人，1088×1920） | — | <https://github.com/kijai/ComfyUI-KJNodes/issues/759> |

**结论（中）**：H3 生成段相对锚帧存在**系统性色调偏差**。方向不完全一致：多数报告是“对比度和饱和度变高，更 hot”，也有“变暗”和“偏紫”。没加 Turbo 也会发生（tritant、NikoDemon80 都确认），**没有任何人从模型侧修好**。NikoDemon80 10-05 的原话：“No one has solved the issue. The problem persists.”（<https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context/issues/44>）。所以社区通行做法是**生成后做颜色校正**。

### 2.2 社区用的校正方法（按共识排序）

1. **以锚帧为参照，做按通道的加性或仿射校正，不用 LUT 或强直方图匹配**。rkfg 的默认模式 `frame_shift`（逐帧逐通道加性偏移），以及 `gain_bias`（“Robust”）；README 说 `lut` 会“overfits regenerated content”。seedance 博客给的结论相同：“per-channel gain and bias is usually safer than a detailed LUT.” joeygambino 的 multishot 包也用**固定参照**（第 1 镜），而不是相邻镜头互相匹配：“matching neighbour-to-neighbour re-accumulates drift”，并且其 `master_normalize=luma+contrast` 同时匹配均值和方差（“matches the spread as well as the mean”）。<https://huggingface.co/joeygambino/MiniMax-H3-Multishot-Workflow>。置信度：中（3 个独立项目方向一致）。
2. **只在人物区域取统计量**（LAB 直方图，`match_lightness: True`）。理由是背景运动或运镜会把统计量带偏：“only safe when the background is static”。实测 dE 从 4.2 降到 1.9。<https://github.com/lovemachine100/ComfyUI-H3-ClipColorAnchor>。置信度：低-中（1 个项目，有测量）。
3. **KJNodes ColorMatch**：**没有找到任何在 H3 上实测 ColorMatch 的帖子。** 通用经验（comfyui-wiki）是 `hm-*` 组合匹配最狠，内容差异大时容易过冲，建议用 `mkl` 或 `reinhard`。置信度：低。
4. **不要用 VHS 加载器做对比或校正**：rkfg README 写“VHS can shift colors and create a false seam”，要用原生 loader。lovemachine100 也说 anchor 和 clip 要走同一个 loader。置信度：中（2 人）。
5. 先排除解码链路问题：“If the source itself changes as soon as it enters the graph, fix the decode path before tuning H3.”（seedance 博客，低）

**对我们的推断（低，需验证）**：FL2V 有首尾两个已调色的锚帧，可以分别测出首帧处和尾帧处的偏差（输出第 0 帧对首帧、最后一帧对尾帧），然后按时间线性插值做 `gain_bias` 校正。`grade.py` 做镜间匹配时，参照应该用**我们自己调好的关键帧**，不要用相邻镜头的输出。

### 2.3 会引起偏色或质量下降的设置（社区共识）
- **跳步缓存（EasyCache / Spectrum / TeaCache）**：010O11（#30，2 个赞）、TheVisitorX + Meryruizk + shadowmonarchforreal（lightx2v #16 怀疑 Spectrum）、NikoDemon80（“I would also avoid using any Turbo LoRA or Spectrum.”，H3-Motion-Context #9）、note.com 的对比实验。**≥5 人，共识：关掉。** 置信度：中-高。
- **`--fast fp16_accumulation` 启动参数**：PlagueKind 关掉后 Ref2VA 参考贴合“got alot better”；Pyrolistical 报告它“caused infinities”；n8704918 关掉后问题仍在。<https://github.com/Comfy-Org/ComfyUI/issues/16589>。2 人支持、1 人存疑。**检查 gpu3 启动参数，如果开着就关掉做对照。** 置信度：低-中。
- **KJ `MiniMaxH3MemoryEfficientSageAttentionPatch`**：超过约 199.7k token 会静默出错（“No NaN, no error, no warning — the output is just wrong”，<https://github.com/kijai/ComfyUI-KJNodes/issues/763>），1088×1920 下发灰（#759）。我们约 76k token，**理论上不受影响**，但如果用了这个补丁，最好和 Kitchen 注意力做一次对照。置信度：低。

---

## 3. 身份漂移（脸、发型、服装）

### 3.1 社区观察
| 现象 | 用户数 | 原文 |
|---|---|---|
| **远景或小脸必崩**；1MP 左右是甜点，更低分辨率噪声多；更远的脸需要更高分辨率 | ≥6 人（LabMike3D、Leon1000、Clivey、rocky533、010O11、UntMods 同意原因是脸占画面太小） | “the faces turn to garbage if it isnt a close up.” / “1.0 MP is the sweet spot.” <https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/30> |
| 官方承认脸崩，“目前正在系统性解决”（08-20），之后没有更新 | 官方 1 条 + 用户 2 人 | <https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/87> |
| 无参考的 I2V，人物背对镜头时会“re-invented him as a narrower-faced man” | 1 人（januscaler PR，有测量） | <https://github.com/januscaler/ComfyUI/pull/10> |
| 多镜头链：**每镜用不同种子**能保住脸；全部共用一个种子反而让脸和声音都漂 | 1 个项目作者 | “per-shot seeds hold the face; a single seed shared across all shots drifted both face and voice.” joeygambino |
| 加速类节点会改变人物长相 | 1 个项目作者 | “Every booster except block cache changes what people look like” joeygambino |

### 3.2 社区用于保持身份的办法（按共识排序）

**A. Ref2VA（参考图）比 FL2VA 更能锁住长相，但画质和运动更差（社区分成两派）**
- 认为 Ref2V 更能保持长相的：k1fry67（“REF2V holds the sheets perfectly and your characters look identical”）、fengjunwei、mkay76（“Without reference model you can sit and play roulette…”）。共 3 人。
- 认为 FL2VA 画质更好的：Rkss（“Ref2v is not superior. The image quality is bad compared to fl2va.”）、Aorora12、pat11、gilly2020（“ref2va turbo LoRAs make things a bit rigid”，见 lightx2v #58）、makpish（运动慢、发飘，后来换回 fl2va）。共 5 人。
- 来源：<https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/48>、`/discussions/58`
- 量化数据：QuantFunc #19 只用参考图时 “Face similarity 0.61–0.70”，第 0 帧和关键帧的平均像素差是 8.4，而原生 loader 加 pin 后是 4.5。<https://github.com/QuantFunc/ComfyUI-QuantFunc/issues/19>

**B. Ref2VA 加首尾帧锁定（AddGuide frame 0 / -1）：两边兼得，这也是官方 multiframe 模板的结构**
- 官方模板用 `minimax_h3_ref2va_pruned_int8_convrot`，加上 Reference to Video 节点和串联的 Add Guide：“`<Picture 1>` is both the identity lock and the first frame of the video”；“Pictures connected only to Add Guide nodes … are not visible to the text encoder. Plug them into extra `ref_images` slots too”。<https://docs.comfy.org/tutorials/video/minimax/minimax-h3-multiframe.md>（高）
- januscaler PR #10 实测（5090，864×480，3 s，20 步，单种子）：只在 prompt 里点名时 21.9 dB / SSIM 0.900；“Ref2VA + pinned frame + character sheets” 达到 33.3 dB / SSIM 0.993；人物背对镜头时，“The pinned Ref2VA render drew the face from his character sheet.”（低-中：1 人，有测量）
- QuantFunc #19 作者也确认：“ComfyUI's native MiniMax-H3 nodes accept keyframes and references together.”
- **注意**：ref2va 的 Turbo LoRA 有一份 9:16 重影报告（lvfengchun：“prone to ghosting or overlapping images in the upper half of the screen”，lightx2v #44，1 人，没人复现也没人反驳）。官方文档也说 R2V Turbo 是“weaker reference/audio”，“Prefer 20–25 steps when references must hold”。

**C. FL2VA 模型配 Ref2V Turbo LoRA（“误用”）**
- 支持：Sikaworld1990（“character preserving and face consistency is 10/10”）、gonztok（“excellet identity preservation”），另有 MiniMax HF #91 的 lorentaken（InsightFace 0.886，见前一份文档）。共 3 人。
- 反对：Rkss，“the image is blurry”。<https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/40>
- 置信度：中（3 人支持，1 人指出代价）。

**D. 混合权重（FL2VA 的 0–19 层 + Ref2VA 的 20–49 层）**
- berryber09 的 w4a8 hybrid，用途是“driven by a first frame _and_ use reference images at the same time”；Aorora12：“Hybrid FL2VA is the winner in my testing.” 共 1–2 人。<https://huggingface.co/berryber09/MiniMax-H3-ref2va-fl2va-hybrid-w4a8>。缺点是它是 **w4a8**（见 §5 的 LoRA bug）。置信度：低。

**E. 写实人物 LoRA**
- fal 的 MiniMax-H3-Realism-People-LoRA：“faces that hold up in close-up, natural skin texture”，强度 1.0。只写了 T2V / I2V / R2V，**没写 FL2V**。hidetaro7 说它能压住红斑，但很“fragile”。<https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA>。MBen1986 报告它和 FL2V 4-step **v1.3** 一起用会坏，v1.2 正常（lightx2v #57，官方 gushiqiao 承认会改进）。置信度：低。

**F. 加密中间关键帧**
- hidetaro7：“Anchoring more densely does suppress it, but only because dense guides freeze the face entirely”；“An intermediate guide spacing did not help.” 也就是说，**中等密度的 guide 不能修身份，太密又会把脸冻住**。置信度：低。

---

## 4. 首尾帧贴合、重影、溶解

| 发现 | 来源 | 置信度 |
|---|---|---|
| 首尾帧之间没有物理上可走通的路径时，模型会做 dissolve（重影来源之一），解决办法是加一个中间动作节拍或延长片长 | minimax3.com 博客（第三方）；joeygambino：“fl2va lands on a supplied frame and ref2va only nudges toward one.” | 低-中 |
| 续接时用尾帧作硬锚会出现“a lot of scene cuts though instead of a smooth transition into the image” | NikoDemon80，H3-Motion-Context #20 | 低 |
| Ripcurlsurf：“I find minimax handles first and last frames so well.” | Comfy HF #30 | 低（正面反馈） |
| vLLM-omni 的“尾帧不受控”最后查明是**接口没实现加参数名写错**，不是模型问题 | <https://github.com/vllm-project/vllm-omni/issues/6391> | 高（与 ComfyUI 无关） |
| 9:16 竖屏有明显的 tile 线（VAE 解码） | zwukong，ComfyUI #15885（无回复）；09-22 #16436 修了 tile 交界的 step | 低 |
| Ref2V Turbo 在 9:16 下上半画面重影 | lightx2v #44（1 人） | 低 |
| AddGuide 中间帧：“put a still at frame 60 of 124 to force a it to hit that frame.” | PR #15439 | 高（机制）/ 效果没有实测报告 |

**没有找到**专门讨论“FL2V 落不到尾帧”的 ComfyUI 或 MiniMax issue。也没有找到 FL2V 重影和竖屏、Turbo 之间关系的第二份报告。

---

## 5. 量化、LoRA 与推荐设置（社区共识排序）

| # | 设置 | 支持者 / 反对者 | 模式 / 硬件 | 置信度 |
|---|---|---|---|---|
| 1 | **关掉 EasyCache / Spectrum / TeaCache** | ≥5 人支持，没有反对 | T2V、FL2V，各种卡 | 中-高 |
| 2 | **不用 w4a8 + LoRA，改用 int8_convrot**：W4A8 下 `adaln_proj` 的 LoRA“silently never applies”，渲染照常完成，看起来像 “the LoRA just isn't very good” | IvenKooLab（源码分析，v0.39 / v0.42.1 都能复现）+ kingp0dd（768p LoRA “only works with int8 convrot”）+ TuTuCSF（Kijai HF #6 标题 “Incompatible with minimax_h3_fl2va_pruned_w4a8_mixed”）。3 人 | FL2V Turbo | 中 |
| 3 | 768p Turbo：8 步，shift 6/3，Euler / Simple | 官方 lightx2v #48、#57；用户报告 “Does not work well with other Loras, and at lower screen resolutions(lower than 768p)”（yui7854） | FL2V | 高（官方）/ 社区没有反对 |
| 4 | Euler 比 res_multistep 少一半变暗 | reasy0000（1 人） | FL2V / I2V | 低 |
| 5 | Turbo LoRA 强度保持 1.0（低了偏暗，高了过曝） | TawusGames、Kinduun 支持；vladulidlo 建议 0.5；Kijai 的卡片写着 0.75。有分歧 | FL2V 4-step v0.1 | 低-中 |
| 6 | 每个镜头用**不同种子** | joeygambino（1 人） | 多镜头 | 低 |
| 7 | 生成分辨率 ≈1MP（768×1344 已满足），脸要大 | rocky533、010O11 | T2V | 中 |
| 8 | 全量 INT8 / BF16 有 17 帧周期暗帧，**pruned 版没有**；修法是删掉 `.to(dtype)`（社区补丁，ComfyUI 还没合并） | 2 人 | 所有模式 | 中 |
| 9 | 4-step v1.3 和其他 LoRA 一起用会坏，v1.2 正常；8-step ref2v v1.1 有人说比 v1.0 差 | MBen1986、Jazzyman（各 1 人），官方承认 | Turbo | 低-中 |

---

## 6. H3 的角色或身份 LoRA 训练

| 工具 | 状态 | 显存 | 身份效果 | 来源 |
|---|---|---|---|---|
| **musubi-tuner**（kohya） | 支持 T2VA / FL2VA / Ref2VA LoRA，标注 experimental。身份方案：“Teacher matching (`ref`: identity + voice; `first,last`: identity, base audio kept)”。**不支持普通的 flow-matching 训练**，“FP8 files and NVFP4 transformers are rejected”；文档没有写多卡 | int8 剪枝版约 21GB，加 `--blocks_to_swap`（最多 48）可以更低；note.com 用户在 4070 12GB 上约 6.5GB 显存，每步 9.9 s，1000 步约 2h45m（单帧图片，t2va） | 混合数据集 1000 步时脸不像，再加 500 步纯脸数据后“結構似てきた”（相当像了） | <https://github.com/kohya-ss/musubi-tuner/blob/main/docs/minimax_h3.md>、<https://note.com/sepiablue/n/nc1ce412d6ea2> |
| **ai-toolkit**（ostris） | `arch: "minimax_h3"`，`partition: "fl2va"`，convrot8 | 4070 12GB 可以训图片（大量 offload 到内存，内存 32–37GB），32 张图 1000 步约 6–7h；作者认为 12GB 训视频基本不可能 | 第一次“didn't look like the subject at all”，改成以脸部为主的数据集后“definitely a passing grade!” | <https://note.com/sepiablue/n/nf0763f854580> |
| **DiffSynth-Studio** | 有 FL2VA 训练脚本 | 维护者：480p、124 帧需要约 78GB，pruned 版约 53GB | 没有身份结果 | <https://github.com/modelscope/DiffSynth-Studio/issues/1624> |
| diffusion-pipe | **没找到** H3 支持 | — | — | — |
| 其他 | bdsqlsz：“Guidance loss is difficult to use… not for training content.”（X，没打开原帖，只看了搜索摘要） | — | 负面 | <https://x.com/bdsqlsz/status/2090412973953368245> |

**对我们（4×3090，每卡 24GB）**：musubi 用 int8 剪枝版加 block swap 可以单卡训练（文档没写多卡）。身份 LoRA 首选 FL2VA 的 `first,last` teacher matching，数据集以林晚的**脸部特写**为主。两位日本用户的经验都是**脸部特写数据集明显更好**。需要留意 §5 第 2 条：自训 LoRA 也要配 int8 底模，否则 adaln 层不生效。整体置信度：低（只有 2 个单用户案例，都不是 FL2V 推理场景）。

---

## 7. Kijai

- Kijai 在 HF 上发布了 `Kijai/MiniMax-H3_comfy`（压缩版 LoRA，卡片原文：“Not 100% sure of the intended alpha, try using this one at lower strength if you get noisy outputs”；推荐“4 steps, 0.75 LoRA strength, er_sde / sa_solver”，这是针对 v0.1 的）、`Kijai/MiniMax-H3-TAE`（只用于预览），以及 KJNodes 里的 MemEff Sage 补丁和 Model Preview Override。
- **没有找到类似 WanVideoWrapper 的独立 H3 wrapper。** H3 走 ComfyUI 原生节点。
- Kijai HF 讨论 #8：“the resized version of 4step degraded camera movement”（kingp0dd）；#16：dennismc1974 认为 v0.1 4step comfy 版“looks ands works best for me”。说明 Kijai 的 rank 压缩版有人认为会掉质量，但只是单帖。
- **没有找到任何在 H3 输出上实测 KJ ColorMatch 的帖子。**

---

## 8. 没找到 / 无法核实
- **Reddit 全部**（r/StableDiffusion、r/comfyui），工具层面被屏蔽。需要人工浏览，搜索词建议：`MiniMax H3 FL2V`、`H3 color shift`、`H3 identity`、`Hailuo 3 open weights`。
- civitai 上 H3 LoRA 的评论区（只找到模型页，没看评论）。
- 专门针对 FL2V 单镜头（非续接）色偏的测量帖。现有色偏报告大多来自续接或 I2V。
- FL2V“尾帧没落到”的专门 issue。
- 在 H3 上用 KJ ColorMatch 的实测。
- diffusion-pipe 对 H3 的支持情况。
- MiniMax HF #78（VAE 色差）、#87（脸崩）都没有官方修复。ComfyUI #15426 和 MiniMax #85 的 `.to(dtype)` 修复也还没合并。

## 9. 来源清单
GitHub：Comfy-Org/ComfyUI `nodes_minimax_h3.py`、commits、issues #15426 #15805 #15885 #16420 #16588 #16589 #17429、PR #15439 #16436 #16881 #17412；MiniMax-AI/MiniMax-H3 issues #84 #85；kijai/ComfyUI-KJNodes #759 #763；NikoDemon80/ComfyUI-H3-Motion-Context #9 #20 #44；tritant/ComfyUI_MiniMax_H3_Extender #15；ethanfel/ComfyUI-MiniMaxH3-Context-Loop（`docs/AUDIO_AND_CONTINUITY.md`、`latent_color_carry.py`）；rkfg/ComfyUI-MiniMaxH3-ToneCompensate；lovemachine100/ComfyUI-H3-ClipColorAnchor；dntpi/ComfyUI-Hand-Tie-Clips；januscaler/ComfyUI PR #10；QuantFunc/ComfyUI-QuantFunc #19；vllm-project/vllm-omni #6391；kohya-ss/musubi-tuner docs；modelscope/DiffSynth-Studio #1624。
HF：Comfy-Org/MiniMax-H3 讨论 #15 #30 #55 #63 #67；MiniMaxAI/MiniMax-H3 #78 #87；lightx2v/Minimax-h3-Turbo #9 #16 #40 #44 #46 #48 #54 #57 #58；Kijai/MiniMax-H3_comfy（卡片 + 讨论列表）；joeygambino/MiniMax-H3-Multishot-Workflow；berryber09/MiniMax-H3-ref2va-fl2va-hybrid-w4a8；fal/MiniMax-H3-Realism-People-LoRA。
文档：docs.comfy.org `minimax-h3-native.md`、`minimax-h3-multiframe.md`。
其他：note.com/sepiablue（两篇）、seedance.tv 博客。
