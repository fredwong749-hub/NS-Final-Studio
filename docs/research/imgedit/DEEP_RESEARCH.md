# 图像编辑 Deep Research（IMGEDIT-RESEARCH，2026-11-02，向总调度 fredw-2b 汇报）

> 项目方原话（11-02 16:5x）：“http://127.0.0.1:5173/#/image-edit 这个系统现在非常混乱，交互也非常糟糕。这个东西主要是为了人物和场景的修改来做的……”；“这个页面我不接受，非常糟糕。你 Deep Research 一下相关的 image editing 应该怎么做，然后怎么把交互做好，细节做好，还有一些提示词做好。”

本轮只做调研和文档：不改代码、不出图、不发版，图片没有上传到任何外部服务。ASSETUX R3（data/review_pages/assetux/path.html）已经做过一轮产品调研，本文不重复，重点补模型层、提示词层和产品细节。

**置信度**
- 高：直接读过官方原文，包括 HF 模型卡、GitHub 原始文件、ComfyUI 源码、Comfy-Org 官方模板 JSON 和官方帮助页。
- 中：官方页面抓取被拒（403）或经抓取工具转述，引文来自搜索摘要或可信媒体的实测。
- 低：只有一篇社区帖或个人文章。

“没查到”就是没查到，不做推测。标“推断”的是我的判断，不是查来的结论。

**配套文件**
- 给 UI/UX 设计 agent 的 brief：docs/research/imgedit/UIUX_BRIEF.md
- 本文 §E：提示词规则改进清单
- 本文 §F：模型、工作流与 A/B 清单

---

## 0. 结论先行（给总调度）

1. **现在“修改”做的其实不是指令编辑，而是低重绘的图生图，这是效果差的根因。**（高，读代码得出）
   - 现状：services/api/ns_api/edits.py 的 `_generate()` 只把原图当底图 latent（init_image），按 denoise 0.35 / 0.55 / 0.75 低重绘；编码器的图像槽 image_1…image_N 放的是 asset_refs 规划的身份脸、设定图和场景，**模型的视觉编码器根本没看到要改的那张图**。
   - Turbo 下 `turbo_sigmas(0.35)` 等于 “0.35, 0”，只走 1 步；0.55 只走 2 步。
   - 官方用法正相反：ComfyUI 的 Qwen-Image 2.1 编辑模板写明 “image_1 is the edit target. The rest are references.”，“Output follows image_1.”，并且是满步数去噪（高，见 A1-4）。
   - 后果：步数少时改不动（姿势、换装都改不动），步数多时整张漂（脸、肤质、光线全变）。
2. **局部修改只是“矩形框 + 整张改完再羽化贴回”，模型并不知道要改哪里。**
   - 提示词里只追加了一句中文“只改需要修改的区域”。
   - Qwen-Image 2.1 官方支持画圈、涂抹标注和独立 mask 来指定区域（高，A1-4）。
   - 官方 Edit Enhancer 还规定局部重绘要用固定模板 “Perform inpainting on this image. The original caption is: ”（高，C1）。
3. **提示词层有四处和官方规则直接冲突。**（高，C 与 D）
   1. 每次都把“雾霾天蓝及腰长直发”这类外貌描述和整段风格后缀（W 杂志质感、预设后缀）写进编辑提示词。Qwen-Image 2.1 官方改写器明确说：“A preservation description reads to the model as a generation instruction: the more concretely you describe something you meant to keep, the more likely it drifts.”；身份要 “point at that image rather than describing features in words”。
   2. 一条提示词里中英文混写，还用自然语言写“图1是…”。官方规定多图时 “MUST use <image1>, <image2> … Do not use natural language references like "图1"”。
   3. 改写模型只看文字、看不到图（K-REV-V01），没法做官方要求的 “choose a reasonable area based on composition”。
   4. `negative_add` 在 Turbo（cfg = 1）下根本不生效：workflows.negative_for() 在 cfg ≤ 1 时直接丢掉负面词，ComfyUI 官方模板也写了 “negative_prompt: unused while cfg is 1”。所以场景图规则里“负面词写 people, text”实际没有作用。
4. **同一件事有五条后端通路，是“混乱”在系统层的根源。**（高，读代码）
   - edits.py（EDITDEL，edit_plan 规划器加 Qwen 低重绘）
   - asset_edit.py gen-jobs（提示词原样传）
   - frame_edit_queue.py（producer reject --edit-file）
   - image_workshop.py 加 ImageEditPage（只能换 seed 重出，提示词只读，没有遮罩）
   - asset_actions / character_hub 的再生成（prompt_rewrite）
   - 两套 LLM 提示词（edit_planner.md 和 regen/edit_prompt_rewrite.md）规则各写各的。
5. **模型选型**（详见 §F）
   - 人物编辑主力仍然是 Qwen 家族：2.1 已经是生成编辑一体的模型，最多 10 张参考图、支持区域标注；2511 官方主打角色一致性和多人合影。
   - FLUX 3 Image Klein 是 BFL 正式的编辑模型（5.6B，10 张参考图，蒸馏版 16 步），值得 A/B，但官方要求 “Do not use Klein without the prompt upsampler”。
   - **MOSS-Image 底模只做文生图**，编辑能力来自一个社区实验性 LoRA（chinoll/Moss-Image-Edit，代码 GPLv3，ComfyUI 节点标 experimental），不适合做人物编辑。
6. **许可证风险需要总调度知情**：Qwen-Image 2.1 的 HF 卡写的是 license_name: qwen-research，不是 Apache-2.0（高）。现在生产在用，商用前要确认（🔴 见“需要决定”）。
7. **交互结论**
   - ASSETUX R3 定的“一个入口、一个抽屉、版本带、只有正向动作”方向正确，本轮不推翻，只补细节。
   - 要补的细节：点选或自动识别主体的选区、恢复笔、反选（保人换景）、在图上画标注、给参考图打角色角标、提示词扩写的开关和可见可改、在满意的版本上“再来几张相似的”、多轮编辑提醒、给每种编辑配一张快捷动作卡。
   - 产品调研里**没有一家**有滑杆式前后对比和分支树。滑杆对比是我们自己的增量，可以做，但不能说成“竞品都有”。

---

## A. 模型层

### A1. Qwen 编辑家族

| 模型 | 擅长 | 多图 | 分辨率 | 步数 / cfg | 身份漂移风险 | ComfyUI 节点 |
|---|---|---|---|---|---|---|
| Qwen-Image-Edit（2508） | 语义编辑和外观编辑、中英文字 | 只能 1 张 | 约 1MP | 50 步 / true_cfg 4.0；Lightning 4 或 8 步 / cfg 1 | 高 | TextEncodeQwenImageEdit、ModelSamplingAuraFlow、CFGNorm |
| Edit-2509 | 多图组合（人+人、人+物、人+场景）、原生 ControlNet（关键点、深度、边缘） | 1–3 张最好 | VAE 支路约 1MP，视觉支路约 384² | 40 步 / true_cfg 4.0；Lightning 4 或 8 步 | 中 | TextEncodeQwenImageEditPlus（image1–3） |
| Edit-2511 | 角色一致性、多人合影、内置光照 LoRA 和新视角 | 同 2509 | 同 2509 | 40 步 / 4.0；Lightning 只有 4 步版 | 中偏低（官方自评） | 同 2509，另加 FluxKontextMultiReferenceLatentMethod |
| **Qwen-Image 2.1 / Turbo（生产在用）** | 生成编辑一体、≤10 张参考、画圈/涂抹/mask 局部编辑、人物和商品保真 | ≤10 张，写 `<image1>`… | 原生 2K；编辑时输出跟随 image_1 | 官方 40–50 步 euler、cfg 1；Turbo 固定 8 步、cfg 1 | 官方称保持身份；社区测到轻微收缩和偏色 | TextEncodeQwenImage21、QwenImage21Cache；PE 用 TextGenerate + qwen3.5_9b pe_i2i |

**A1-1 2508**
- 官方建议直接用 2509：“it is recommended to use Qwen-Image-Edit-2509 directly，for both single image input and multiple image inputs”。https://github.com/QwenLM/Qwen-Image/blob/main/README.md （高）
- 官方参数：`"true_cfg_scale": 4.0, "num_inference_steps": 50`。https://huggingface.co/Qwen/Qwen-Image-Edit （高）

**A1-2 2509**
- 多图：“It supports various combinations such as "person + person," "person + product," and "person + scene." Optimal performance is currently achieved with 1 to 3 input images.”
- ControlNet：“Native Support for ControlNet: Including depth maps, edge maps, keypoint maps, and more.”
- 人脸：“Better preservation of facial identity, supporting various portrait styles and pose transformations”。
- 改姿势要把关键点图作为另一张输入：“multi-image input also supports commonly used ControlNet keypoint maps—for example, changing a person's pose”。
- 出处：https://huggingface.co/Qwen/Qwen-Image-Edit-2509 （高）
- 管线会自动给每张图加前缀 `"Picture {}: <|vision_start|>…"`，源码 `CONDITION_IMAGE_SIZE = 384 * 384`、`VAE_IMAGE_SIZE = 1024 * 1024`。https://github.com/huggingface/diffusers/blob/main/src/diffusers/pipelines/qwenimage/pipeline_qwenimage_edit_plus.py （高）

**A1-3 2511**
- 改进点：“mitigate image drift, improved character consistency”；“enabling high-fidelity fusion of two separate person images into a coherent group shot”。
- 内置 LoRA：“integrates selected popular LoRAs directly into the base model”；“Realistic lighting control is now achievable out-of-the-box”；“generating new viewpoints can now be done directly with the base model”。
- 出处：https://huggingface.co/Qwen/Qwen-Image-Edit-2511 （高）
- 官方 Space 默认 40 步、true_guidance 4.0、`rewrite_prompt=True`。https://huggingface.co/spaces/Qwen/Qwen-Image-Edit-2511/blob/main/app.py （高）

**A1-4 Qwen-Image 2.1（重点，生产在用）**
- 官方简介：“a unified text-to-image generation and image editing model”；“Support up to **10 reference images**, specify local edits via circles, painted annotations, or separate masks, and preserve identity for people and products.”。https://github.com/QwenLM/Qwen-Image-2.1 、https://huggingface.co/Qwen/Qwen-Image-2.1 （高）
- Turbo：“image editing with **8 denoising steps**”；“Setting `num_inference_steps` alone does not override Turbo's saved schedule.”；“Generation uses CFG=1 by default”。https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo （高）
- ComfyUI 官方编辑模板 image_qwen_image_2_1_image_edit.json，**本人复核过原文**（高）：https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_2_1_image_edit.json
  - “image_1 is the edit target. The rest are references.”
  - “Output follows image_1. Extra refs can differ in size or aspect.”
  - “Mention them in the prompt as `<image1>`, `<image2>`, ...”
  - “cfg: keep 1 for the Qwen Image 2.1 official path. Raise it only if you use a negative prompt.”；“negative_prompt: unused while cfg is 1.”
  - “steps: Qwen Image 2.1 official pipeline uses about 40-50 with euler. This template starts at 25.”
  - “custom_size on: … Keep it close to the resized image_1 size, or the edit can shift.”；“resolution is a total pixel budget … Official default is 1024. The model supports up to 2048.”；“This template starts at 0: no resize beyond a multiple of 32.”
  - PE：“`refine_prompt`: on runs the rewrite and feeds it to the edit model”；“`thinking`: turn this on together with the enhancer. The checkpoint was trained with a reasoning block and loses quality without it.”
- 节点源码：resolution “0 keeps each reference at its own size, rounded to a multiple of 32”；latent 输出 “Empty latent on the first reference image's size, to match with sampling as any other size shifts the edit.”。https://github.com/comfyanonymous/ComfyUI/blob/master/comfy_extras/nodes_qwen.py （高）
- 局部编辑（docs.comfy.org 2.1 教程，中）：
  - “Paint Pen strokes go on the image's RGB layer rather than into the mask”
  - “Naming the mark's color in the prompt points the instruction at that region”
  - “Simple localized edits hold up at 4 to 8 steps”
  - “`cfg` 5 degrades quality badly”
  - VAE “can leave a fine checkerboard texture”
  - 出处：https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1
- 许可证：HF 卡头部写 license_name: qwen-research（高）。第三方：“The weights use the Qwen Research License rather than the Apache 2.0 license of earlier Qwen-Image models”（中，eesel 测评）。

**A1-5 Qwen 家族已知问题**
1. **画面偏移、缩放**
   - 2509/2511 的 TextEncodeQwenImageEditPlus 接 vae 时会把参考图强制缩到约 1MP、按 8 取整（源码，高）。社区修法是不接 vae，改用 VAEEncode → ReferenceLatent，尺寸对齐到 16 的倍数（低：https://lilting.ch/en/articles/qwen-image-edit-pixel-perfect-referencelatent 、https://www.reddit.com/r/StableDiffusion/comments/1o01e6i/ ）。
   - 2.1 默认设置下左右各偏约 7–8px，把原图对齐到 32 的倍数并设好 resolution 后约 0.1px（低：https://lilting.ch/en/articles/qwen-image-2-1-edit-pixel-perfect-output-resolution ）。
2. **只改衣服颜色，脸也变了**：原文 “even the face changed”。缓解办法有两个：用改写器；拆成多步，原文 “If you need to modify multiple attributes simultaneously, you can split them up”。https://github.com/QwenLM/Qwen-Image/issues/88 （低）
3. **连续多轮编辑会退化**：“from around the 5th round” 开始出现噪声（低，https://github.com/QwenLM/Qwen-Image/issues/200 ）。BFL 对 Kontext 也自认 “After six iterative edits, the generation is visually degraded”（中，https://bfl.ai/announcements/flux-1-kontext ）。
4. **偏色、细节不完全一致**：“Colors and fine detail are also not bit-identical”（低）。官方模板的解决办法是用 ImageCompositeMasked 贴回原像素：“with ImageCompositeMasked, we can paste the original pixels back”（高，InstantX 模板备注）。
5. **塑料皮肤**：“That's just the qwen thing, plastic”，开 Lightning 更明显（低）。本项目已有 Restore LoRA 和肤质调研（docs/research/realism_tuning_20261101.md N5）。
6. **Lightning 配官方 fp8 会出网格纹**：“qwen_image_fp8_e4m3fn.safetensors ... results in the grid artifacts”。https://github.com/ModelTC/Qwen-Image-Lightning （高）
7. **mask 方案**
   - 2508/2509/2511 本身没有 mask 输入。
   - InstantX Qwen-Image-ControlNet-Inpainting 是给文生图底模用的，模型卡原文：“Please use descriptive prompt instead of instructive prompt.”。https://huggingface.co/InstantX/Qwen-Image-ControlNet-Inpainting （高）
   - Comfy 官方有 crop_and_stitch 模板（2509 + Fusion LoRA，只用 core 节点）（高）。
   - lquesada 的 Inpaint Crop/Stitch 节点会 “stitches the inpainted image back into the original image without altering unmasked areas”（高）。

### A2. FLUX.1 Kontext

- 12B 指令改图，示例 `guidance_scale=2.5`，非商用许可。https://huggingface.co/black-forest-labs/FLUX.1-Kontext-dev （高）
- 官方称多轮编辑 “Robust consistency … with minimal visual drift”（高，属自评）。
- API 输出 “~1MP total”，宽高按 32 取整，比例 3:7 到 7:3。https://docs.bfl.ml/kontext/kontext_image_editing.md （高）
- ComfyUI 节点：FluxKontextImageScale（缩到训练尺寸）、ReferenceLatent、FluxGuidance。多图输入要先拼成一张（低）。官方 inpaint：没查到。
- **BFL 原版 Kontext prompting guide 页面已经 404，原文没拿到。** 下面几条取自 ComfyUI 官方教程的转载（https://docs.comfy.org/tutorials/flux/flux-1-kontext-dev ；相对 ComfyUI 是高，相对 BFL 原文是中）：
  - 不用代词，直接点名人物，并锁定五官：“The woman with short black hair … while maintaining the same facial features, hairstyle, and expression”
  - 动词：“Use "change", "replace" rather than "transform"”
  - 换装：“Change the clothes to be a viking warrior while preserving facial features”
  - 换背景：“Change the background to a beach while keeping the person in the exact same position, scale, and pose”
  - 分步：“Step-by-step modifications: Change background first, then actions”
  - 写明保留什么：“Explicit Preservation - State what should remain unchanged”
- 512 token 上限：BFL 官方没查到。

### A3. FLUX.2 与 FLUX 3 Image Klein（项目已装 flux3-image-klein）

- FLUX.2 klein（2026-01-15）
  - 4B 版 Apache-2.0，9B 版非商用；9B 示例 4 步、cfg 1。https://huggingface.co/black-forest-labs/FLUX.2-klein-9B （高）
  - 参考图上限：klein 4 张，pro/max 通过 API 8 张。https://docs.bfl.ml/flux_2/flux2_overview.md （高）
  - “FLUX.2 [klein] does not include prompt upsampling. Write detailed, descriptive prompts”。https://docs.bfl.ai/flux_2 （高）
- **FLUX 3 Image Klein**
  - 原文 “a 5.6B open weights model for text-to-image generation and image editing”，文本编码器 Qwen3-VL-4B，许可证 FLUX Kommunity License（年收入低于 500 万美元可商用），“up to 10 reference images”。https://huggingface.co/black-forest-labs/flux-3-image-klein （高）
  - 蒸馏版 16 步、CFG 1；Base 版 50 步、CFG 3.5。https://docs.bfl.ml/flux_3/flux3_image_klein.md （高）
  - 官方要求必须用扩写器：“Do not use Klein without the prompt upsampler”，“a prompt sent as typed gives noticeably weaker results”（同上，高）。
  - ComfyUI 官方模板叫 `image_flux3_klein_distilled_image_edit`，节点有 Set Reference Multi Latent、Empty Flux 2 Latent、Create Bounding Boxes，扩写器文件 `qwen3.5_9b_flux3_prompt_upsampler_w4a8`。https://docs.comfy.org/zh/tutorials/flux/flux-3-klein.md （高）
  - 编辑没有 mask，也没有强度参数：“Edits have no mask or strength setting”，靠 bbox 指定区域。https://docs.bfl.ml/guides/prompting_editing_overview.md （高）
  - 提示词规则（https://docs.bfl.ml/guides/prompting_editing_single_reference.md 、…multi_reference.md ，高）：
    - “Name the target precisely enough that only one thing matches”
    - “The preserve list names every major element of the scene, not only "the rest of the image"”
    - “Use a hex code to specify a target color”
    - “Refer to each image by position”、“Specify what each image supplies”、“Put the base image first”
  - ComfyUI 中文文档的写法：“编辑提示词应描述最终结果的完整画面，而不是写‘把这里改一下’”。
- 注意两家的保留写法正好相反：FLUX 3 要求把保留项一项项列全；Qwen 2.1 要求用一句总括，不要具体描写外观。所以**提示词模板必须按模型分开**（§E-0）。

### A4. MOSS-Image（OpenMOSS / 复旦）

- 底模只做文生图：原文 “a supervised fine-tuned text-to-image model”，Apache-2.0，约 5B，推荐 50 步 Euler、CFG 3、shift 5；只提到 layout 可以做 “controlled editing”，指的是改 JSON 布局后重新生成。https://huggingface.co/OpenMOSS-Team/MOSS-Image-SFT （高）
- 技术报告的卖点是文字渲染和布局（“average text coverage of 96.3%”），**没有编辑跑分**。https://arxiv.org/abs/2610.23374 （高）。GEdit / ImgEdit 跑分：没查到。
- 编辑能力来自社区 LoRA：Comfy-Org 仓库写明 edit LoRA 来自 “chinoll/Moss-Image-Edit”，并且**没有官方编辑模板**。https://huggingface.co/Comfy-Org/MOSS-Image （高）
  - LoRA 卡原文：“Edit colors, outfits, lighting, seasons, and visual style with text instructions”、“up to four images”、“Project code is available under GPLv3”。https://huggingface.co/chinoll/Moss-Image-Edit （高）
  - 节点 TextEncodeMOSSImageEdit “marked as experimental”，参考图在编码器里最大 384²。https://docs.comfy.org/built-in-nodes/TextEncodeMOSSImageEdit （高）
  - 原文 “not a general-purpose editor”，节点包默认 512²、30 步、CFG 4（中，https://comfyui-wiki.com/en/news/2026-10-22-moss-image-edit-lora ）。
- 结论（推断）：MOSS 适合做带文字的海报、布局类场景图，**不进人物编辑主路径**。

### A5. 各编辑类型 × 模型（证据汇总）

| 编辑 | Qwen 2.1 | Qwen 2511 | FLUX 3 Klein | MOSS+LoRA |
|---|---|---|---|---|
| 换装 | 支持；PE 规则写换装时画布是人物图（高） | 支持（高） | 有官方换装、试穿用例（FLUX.2 文档，高） | 卡上写了 outfits（高） |
| 换背景、保人 | 支持；保留写法要用总括句（高） | 2508 规则：“emphasize maintaining subject consistency at first”（高） | 支持，保留项要列全（高） | 没查到 |
| 改姿势 | 没查到专门说明 | 2509 用关键点图作第 2 张图（高）；内置新视角（高） | 有官方姿势和布局页（只看到目录，中） | 没写 |
| 改光线 | 没查到专门说明 | 光照内置（高） | 有官方光照用例页（只看到目录，中） | 卡上写了 lighting（高） |
| 修手 | 官方写法没查到 | 没查到 | 没查到 | 没查到 |
| 局部重绘 | 画圈、涂抹、mask（高） | 没有 mask，靠文字或画框（高） | 靠 bbox（高） | 没查到 |
| 身份漂移 | 官方称保持；社区测到收缩、偏色（低） | 官方称减轻漂移（自评） | 官方说法只到 “keep recognizable”；社区对 klein 的评价两边都有（低） | 没查到 |

**独立的保脸对比跑分（FLUX 3 Klein 或 MOSS 对 Qwen 2.1 / 2511）：没查到。** 选型只能靠我们自己做 A/B，见 §F。

---

## B. 产品层（只写 ASSETUX R3 之外的补充）

ASSETUX R3 已覆盖：Midjourney Vary Region、Krea Edit、Leonardo Canvas、Photoshop Generative Fill、Runway References、Ideogram Studio、小云雀、即梦截帧注释。下面只记新发现。OpenAI、Adobe helpx、Midjourney docs 抓取一律返回 403，这三家的引文来自搜索摘要，标“中”。

**B1. 千问 / 通义万相**
- 千问 App 是在对话里编辑：“用户只需在千问 App 对话界面输入指令，即可自动调用 Qwen-Image 系列模型”。https://www.ithome.com/0/901/812.htm （中）
- 多图用“图1/图2”指代：阿里云 API 文档写 “进行多图像编辑时，编辑指令中需要使用"图1"、"图2"、"图3"等描述”。https://help.aliyun.com/zh/model-studio/qwen-image-edit （中）
  - 注意：这条和 2.1 本地模型的 `<image1>` 标签规则不同。这是 API 产品层的约定，本地 ComfyUI 跟 2.1 模型卡走。
- chat.qwen.ai 网页版没有选区：“Not yet. The model edits the entire image based on your prompt”（低，analyticsvidhya，2025-08）。
- 圈选和涂抹在开发者平台：Qwen-Image 2.1 “支持通过圈选、涂抹和独立掩码明确编辑区域”。https://www.donews.com/news/detail/1/6736766.html （中）
- 万相的局部重绘用白色涂抹蒙版：“输入原图和涂抹区域图，其中白色部分为涂抹区域”。https://help.aliyun.com/zh/model-studio/wanx-image-edit-api-reference （中）
- 万相网页版的界面和提示词建议：没查到。

**B2. BFL Playground**
- 上传原图 → 写提示词 → 迭代：“View the result and iterate as needed”。https://help.bfl.ai/articles/8667153955-what-is-the-bfl-playground （高）
- 每张结果都能复制复现参数：“Click API Code on any successful generation”（高）。
- 用户可按速度选模型：klein 被称为 “great for rapid iteration”（高）。
- 历史面板和对比：没查到。

**B3. Gemini / Nano Banana 与 ChatGPT（这两家决定了用户对“说一句话就改”的预期）**
- Gemini Markup：点图就进标注，“By adding drawings with a pen or circling specific areas”（中，https://jetstream.blog/en/gemini-doodle-image-editing-markup-rollout/ ）。
- Nano Banana Pro：“up to 14 images”、能保持 “up to 5 people” 的一致性，“Select, refine and transform any part of an image with improved localized editing”。https://blog.google/technology/ai/nano-banana-pro/ （高）
- Gemini 在菜单里有“用 Pro 重做”（「Pro でやり直す」）。https://gemini.google/overview/image-generation/ （高）
- ChatGPT：在对话或 Images 里选图打开编辑器，Select 笔刷可调大小，有 Undo/Redo。官方提醒 “Highlights are not always precise, and edits may extend beyond the area you selected.”（中，https://help.openai.com/en/articles/11084440 ）。
  - 这条提醒说明：只靠模型尊重选区不够，**框外像素必须用合成贴回来保证**。

**B4. Photoshop / Firefly**
- 第三方模型的规则不同：“Partner models such as Gemini 2.5 or Flux Kontext Pro use instructional editing prompts and work best with the entire image selected”；“New partner models generate only one image. Firefly models generate multiple image variations”（中，https://jkost.com/blog/?p=23500 ）。
  - 启示：**不同模型的提示词写法不同（描述式 vs 指令式），界面要按模型变化**。
- Generate Similar：在满意的那个变体上再出几张相似的。https://helpx.adobe.com/photoshop/web/edit-images/retouch/get-similar-variations-with-generative-ai.html （中）
- Harmonize：贴入的元素一键融合光影，出 3 个变体。https://www.adobe.com/learn/photoshop/web/blend-subjects-with-harmonize （中）
- Firefly AI Markup：用文字、画笔或框标出几块区域，每块写一句，再选模型。https://helpx.adobe.com/firefly/web/edit-images/prompt-to-edit/use-ai-markup.html （中）
- 参考图选项在第三方模型下是灰的（低，Adobe 社区帖）。

**B5. Krea（官方文档已读，高）** https://www.krea.ai/docs/user-guide/features/edit.md
- Change Lighting：“add, move, or adjust light sources directly on the canvas”
- Change Camera Angle：“three controls that work together”，并建议 “Subtle changes often produce the most coherent”
- Annotate：“define specific regions and assign a separate text prompt to each one”
- Draw：“the shape and placement of your brushstrokes act as a guide”
- 历史：底部缩略图用来 “compare it with a previous version or revert”

**B6. 即梦 / 可灵 / 美图**
- 即梦参考图有“人物长相”这一角色（低）；有“智能参考”（中，https://news.aibase.com/zh/news/18749 ）；接 DeepSeek 写提示词（中，https://news.aibase.com/zh/news/15966 ）；智能画布含局部重绘、消除、1.5x/2x/3x 扩图、抠图（低）。
- 可灵图像 O1：“上传最多10张参考图进行融合再创作”，有主体库（中，https://www.qbitai.com/2025/12/360022.html ）。

**B7. Ideogram Magic Prompt（高）** https://docs.ideogram.ai/create/image-settings
- “Enhances your prompt to improve image variety and richness. It can also translate your prompt into English.”
- “Turn it off when you want the model to follow your exact words.”
- 挂了参考图后，这个开关隐藏。

**B8. Midjourney V7 Editor（中）**
- Smart Select 选完后可以 “Erase Selection” 或 “Erase Background”；Erase 和 Restore 两支笔共用尺寸滑块。https://docs.midjourney.com/docs/the-web-editor
- 带 Omni 参考的图 “not compatible with Vary Region”。https://docs.midjourney.com/hc/en-us/articles/36285124473997

**B9. 全程没查到**：滑杆式前后对比、显式分支历史树、生成进度和 ETA 的官方说明（任何一家都没有）；LibLib 的局部重绘；千问 App 内是否有涂抹工具。

**B10. 值得照搬的交互模式**（每条注明来源，按人物 / 场景分组的落地写法见 UIUX_BRIEF.md）

| # | 模式 | 来源 |
|---|---|---|
| 1 | 点图即进编辑；选区可有可无：有选区就只改选区，没有就整张按一句话改 | ChatGPT、Gemini Markup、Krea |
| 2 | 悬停自动识别主体、点选主体，可加点和排除点 | Krea Auto Mask、MJ Smart Select |
| 3 | 反选：“除了人都重画”（保人换景） | MJ Erase Background |
| 4 | 恢复笔：涂回原图像素，保护脸部 | MJ Restore |
| 5 | 参考图编号角标，并在提示词里显式引用 | 千问 API、Qwen 2.1 `<imageN>` |
| 6 | 参考图标角色（人物长相、服装、场景、风格） | 即梦、可灵主体库 |
| 7 | 在图上画箭头或草图指示姿势、朝向 | Gemini Markup、Krea Draw |
| 8 | 分区写提示词：每块区域一句 | Krea Annotate、Firefly Markup |
| 9 | 在满意的版本上“再来几张相似的” | Photoshop Generate Similar |
| 10 | 菜单里放“换更强模型重做这张” | Gemini 用 Pro 重做 |
| 11 | 当前模型的能力边界直接体现在界面上（不支持的选项隐藏） | Photoshop、Ideogram |
| 12 | 编到第 5、6 轮时提醒“建议从原图或某版本重开” | BFL 官方自认、Qwen issue #200 |
| 13 | 在画布上摆光源重打光 | Krea Change Lighting |
| 14 | 机位用控件转，并默认小幅度 | Krea Camera Angle |
| 15 | 贴入道具后一键融合光影，出 3 个变体 | Photoshop Harmonize |
| 16 | 常用改法做成快捷动作卡 | Leonardo Blueprints、即梦智能画布 |
| 17 | 提示词扩写可开关、默认开，结果可见可改 | Ideogram、即梦、MJ Conversational |
| 18 | 多候选一屏排开，点选后就地继续改 | Photoshop 3 个变体、MJ 4 宫格 |
| 19 | 底部缩略图时间线，可对比、可回退 | Krea |
| 20 | 每张结果都能复制复现参数 | BFL API Code |

---

## C. 提示词层：从口语思路到模型提示词

### C1. 官方改写器原文（Apache-2.0，可直接参考）

**C1-a Qwen「Edit Prompt Enhancer」（2511 / GitHub 当前版，`polish_edit_prompt`）**
- 出处：https://github.com/QwenLM/Qwen-Image/blob/main/src/examples/tools/prompt_utils.py ；和 2511 官方 Space 的 SYSTEM_PROMPT 逐行比对一致（高）。
- 官方 README：“We have observed that editing results may become unstable if prompt rewriting is not used. Therefore, we strongly recommend applying prompt rewriting”（高）。

关键段落：
```
- Keep the core intention of the original instruction unchanged, only enhancing its clarity, rationality, and visual feasibility.
- All added objects or modifications must align with the logic and style of the edited input image's overall scene.
### 1. Add, Delete, Replace Tasks
- If the description is vague, supplement with minimal but sufficient details (category, color, size, orientation, position, etc.).
- For replacement tasks, specify "Replace Y with X" and briefly describe the key visual features of X.
### 3. Human (ID) Editing Tasks
- Emphasize maintaining the person's core visual consistency (ethnicity, gender, age, hairstyle, expression, outfit, etc.).
- If modifying appearance (e.g., clothes, hairstyle), ensure the new element is consistent with the original style.
- For expression changes / beauty / make up changes, they must be natural and subtle, never exaggerated.
    > Rewritten: "Replace the man's hat with a dark brown beret; keep smile, short hair, and gray jacket unchanged"
### 4. Style Conversion or Enhancement Tasks
- If there are other changes, place the style description at the end.
### 5. Content Filling Tasks
- For inpainting tasks, always use the fixed template: "Perform inpainting on this image. The original caption is: ".
- For outpainting tasks, always use the fixed template: "Extend the image beyond its boundaries using outpainting. The original caption is: ".
### 6. Multi-Image Tasks
- Rewritten prompts must clearly point out which image's element is being modified.
## 3. Rationale and Logic Checks
- Add missing key information: e.g., if position is unspecified, choose a reasonable area based on composition
# Output Format Example  { "Rewritten": "..." }
```

**C1-b 2509 Space 版对人物的补充**（https://huggingface.co/spaces/Qwen/Qwen-Image-Edit-2509/blob/main/app.py ，高）
```
### 3. Human Editing Tasks
- Make the smallest changes to the given user's prompt.
- If changes to background, action, expression, camera shot, or ambient lighting are required, please list each modification individually.
- Edits to makeup or facial features / expression must be subtle, not exaggerated, and must preserve the subject's identity consistency.
```

**C1-c 2508 Space 版，换背景规则**（https://huggingface.co/spaces/Qwen/Qwen-Image-Edit/blob/main/app.py ，高）
```
- If deletion is not specifically emphasized, the most important subject in the original image (e.g., a person, an animal) should be preserved.
    - For background change tasks, emphasize maintaining subject consistency at first.
```

**C1-d Qwen-Image-2.1-PE-I2I 系统提示词**（https://huggingface.co/Qwen/Qwen-Image-2.1-PE-I2I ，高；qwen-research 许可，只摘原则段）
```
The Governing Principle — Attribute Disentanglement at Full Strength
Edit exactly the attribute(s) the user named, push each to a strong and unmistakable degree, and hold everything else at input fidelity.
- Leakage — touching what the user did not name (... a style change that drifts a face, an outfit swap that drops an accessory, ...).
- Under-editing — an output a viewer could mistake for the unedited input ...
Preservation locks content, never edit strength.
Say what stays, without repainting it. Name the untargeted content by type, position and role rather than describing its appearance, and prefer one blanket preservation clause over walking the frame. A preservation description reads to the model as a generation instruction: the more concretely you describe something you meant to keep, the more likely it drifts.
Identity is the hardest invariant. ... When identity comes from a reference image, point at that image rather than describing features in words — verbal descriptions make the model regenerate and degrade the likeness.
Only what was asked. Do not add operations the user did not request, and do not clean up unmentioned defects ...
For Multi-Image Input (N >= 2), the rewritten instruction MUST use <image1>, <image2>, ... Do not use natural language references like "图1", "第一张图", "the first image" ... For single-image input (N = 1), do NOT use tags.
State each image's role explicitly — which one is the canvas ... and which supply material to transfer.
| Clothing swap ("换衣服", "换装") | The person image | ... | Face/head swap ("换脸", "换头") | The body image |
- The entire rewritten prompt must be a single continuous paragraph
- Never include any resolution or aspect ratio information in rewritten_prompt
- State requirements affirmatively ("保持背景与输入图完全一致") rather than as prohibitions ("禁止改变背景"). Standard preservation phrasing "保持/保留[X]不变" is fine.
```
- 调用参数：`enable_thinking=True`，`temperature=1.0, top_p=0.95, top_k=20`，输出 JSON `{"rewritten_prompt","wh_ratio","ratio_follow"}`（高）。

**C1-e BFL（Kontext 经 ComfyUI 转载；FLUX 3 为官方原文）**：要点见 A2、A3。FLUX 3 编辑的要求是“描述最终完整画面 + 列全保留项 + 颜色用 hex”。

### C2. 综合出来的编辑指令结构（按模型分两套）

| 位置 | Qwen 2.1（主力） | Qwen 2509 / 2511 | FLUX 3 Klein |
|---|---|---|---|
| 引用 | 多图写 `<image1>`…，单图不写标签；写明哪张是画布、每张参考提供什么 | “Picture 1 / image 1” | “image 1…”，底图放第一位，写明每张图提供什么 |
| 改什么 | 动词开头（Replace / Change / Add / Remove），只写点名的属性，并且改到位 | 同左；多处改动逐项列 | 描述**最终画面**，目标写到唯一可指认 |
| 保留什么 | **一句总括**，按类型和位置写（“保持 `<image1>` 中人物的身份、姿势、构图和背景不变”），不描写外观；身份指向参考图 | 逐项列出要保留的属性（“keep smile, short hair… unchanged”） | 保留项**列全**（身份、头部位置、姿势、光线、其余场景） |
| 区域 | 有标注就点出标注颜色（“红圈内”）；有 mask 就走 mask 支路 | 写位置词（right hand、lower-left） | bbox |
| 风格 | 只在用户要求改风格时写，放最后 | 同左 | 可写完整场景描述 |
| 禁用 | 分辨率、比例、否定句（改成肯定句）、没被要求的修补 | 同左 | 同左 |
| 语言 | 一段连贯的话，单一语言 | 同左 | 同左 |

### C3. 身份保持关键词（只收有出处的）
- “keep [具体属性] unchanged”：Qwen 2509/2511 改写器（高）
- “while maintaining the same facial features, hairstyle, and expression”、“while preserving facial features”：Kontext（经 ComfyUI 转载）
- “keeping the person in the exact same position, scale, and pose”：Kontext 换背景
- “Preserve its identity, head position, … pose, lighting and the rest of the scene”：FLUX 3 单图编辑
- “保持/保留[X]不变”、“保持背景与输入图完全一致”：Qwen 2.1 PE
- 反面教材：用文字逐项描写五官和发色来“保持”。Qwen 2.1 PE 原文说这样会 “degrade the likeness”（高）。

---

## D. 对照本项目：现在的做法和最佳实践差在哪

读过的文件：docs/master/EDITOR_INTEGRATION.md、data/review_pages/assetux/path.html、services/api/ns_api/prompt_rewrite.py、config/recipes/regen_prompt_rewrite.md、config/recipes/edit_prompt_rewrite.md、services/api/ns_api/image_workshop.py、edits.py，另加 services/render_router/ns_render/workflows.py、frame_edit.py、frame_edit_queue.py、asset_edit.py、config/edit_engines.json、apps/web/src/v3/pages/ImageEditPage.tsx。

| # | 现状（位置） | 最佳实践（出处） | 差距 / 影响 | 严重度 |
|---|---|---|---|---|
| D1 | edits._generate：原图只当 init latent，denoise 0.35/0.55/0.75；编码器图像槽放 asset_refs 的身份脸、设定图、场景；只有没有槽位规划时，原图才作图1 | 2.1 模板：“image_1 is the edit target”、输出跟随 image_1，满步数去噪（A1-4，高） | 模型看不到要改的图。低重绘改不动结构，高重绘整张漂。**根因** | 致命 |
| D2 | Turbo + 低重绘：turbo_sigmas(0.35) 等于“0.35, 0”，1 步；0.55 是 2 步 | Turbo 官方固定 8 步编辑；docs 说局部编辑 4–8 步够（A1-4） | 步数过少，细节糊、改不到位 | 高 |
| D3 | 局部修改 = 矩形框 → 整张改完 → 高斯羽化贴回（composite_region）；模型不知道区域，只多一句中文“只改需要修改的区域” | 2.1 支持画圈、涂抹、mask（高）；docs 说点出标注颜色就能指向区域（中）；Enhancer 的 inpaint 固定模板（高）；贴回原像素 ImageCompositeMasked（高） | 框内改的内容和框外光影接不上；改脸、改手时模型不知道该改哪儿 | 高 |
| D4 | compose_instruction：英文改写结果 + 中文“保持角色锁定外貌：{锁段}” + 中文“只改…”；contract_inputs 再拼 asset_refs 的“图N是…”前缀 + 整段风格后缀 image_suffix() | 2.1 PE：“MUST use `<image1>`…Do not use "图1"”；单段、单一语言；风格只在用户要求时写、放最后（C1） | 中英混写、两种图片引用方式并存、风格后缀导致整张图被“重新风格化”（Leakage） | 高 |
| D5 | regen/edit_prompt_rewrite.md 要求每次都写 identity unchanged + 雾霾天蓝及腰长直发 + W 杂志质感 | 2.1 PE：“Say what stays, without repainting it”；身份指向参考图（C1-d） | 越具体描写要保留的东西越容易漂；画风句每次都写会把整张图拉向“杂志风” | 高 |
| D6 | 改写器只看文字（K-REV-V01 text_only_guard） | 官方改写器都是 VL 模型，能看图（qwen-vl-max / PE-I2I），会 “choose a reasonable area based on composition” | 改写器不知道图里有什么、在哪；“左手”“桌上那杯”只能盲写 | 中高 |
| D7 | negative_add 被写进规则（scene_plate 每次写 people, text…） | Turbo cfg = 1 时负面词不生效（workflows.negative_for；2.1 模板 “negative_prompt: unused while cfg is 1”，高） | 场景图“不能有人物”实际上没有保障 | 中 |
| D8 | 五条通路：edits.py、asset_edit gen-jobs（提示词原样传）、frame_edit_queue（producer）、image_workshop（只能换 seed）、asset_actions/character_hub 再生成；两套 LLM 规则（edit_planner.md 和 *_prompt_rewrite.md） | 一个编辑器、一个编辑执行器、一套提示词编译器（ASSETUX R3 二之二；EDITOR_INTEGRATION §3-1 一本账） | 规则修一处漏四处，体验不一致；是项目方说“混乱”在系统层的根因 | 高 |
| D9 | ImageEditPage：提示词只读、不能写修改意见；没有遮罩；只能换 seed 重出；左栏摆出未接通的基座；页面上有 “P1 / 一本账 / sv-11 / takes.json” 等技术话；采用按钮灰着并附解释 | ASSETUX R3 已定：只有正向动作、不放灰按钮、不说技术话；B10 的 1–20 条 | 页面上能做的“编辑”是零，正是项目方说的“非常糟糕” | 致命 |
| D10 | 改法拆分：一句话里改三件事，一次出图 | issue #88：“split them up”；2509 规则 “list each modification individually”；Kontext “Step-by-step” | 多处改动一次做完，漂移概率叠加 | 中 |
| D11 | 版本链可以无限次在修改版上继续改 | 约 5–6 轮后退化（Qwen #200，低；BFL 自认，中） | 越改越糊、越塑料 | 中 |
| D12 | 自动重出按 seed → 框外扩 25% → 换模型轮换 | 官方建议的第一手段是改写器和拆步（A1-5） | 重试维度里没有“拆步”和“降强度”；外扩框会扩大漂移面 | 低 |
| D13 | edit_engines.json 写的是 “FLUX.2 Klein”；IMGLAB 装的是 FLUX 3 Image Klein；MOSS 被列为可选编辑基座 | FLUX 3 Klein 是 5.6B、16 步，要配扩写器；MOSS 编辑只有社区实验性 LoRA（A3、A4） | 名字和权重对不上；MOSS 能力被高估 | 中 |
| D14 | 编辑分辨率：_fit_size(…, 1920)，ImageScale center-crop 到画布 | 2.1：resolution = 0，宽高为 32 的倍数，画布等于 image_1 尺寸，否则 “the edit can shift”（高） | 要实测有没有偏移；偏移会让贴回出现重影 | 中 |
| D15 | Q1 身份闸门（锚分 ≥ 原版 − 0.03）、GEN_CONTRACT postflight | 官方没给阈值，需要自己标定（A1） | 这一项**我们做得比官方多**，保留 | 已有 |
| D16 | Qwen-Image 2.1 生产在用 | HF 卡写 license_name: qwen-research（高） | 商用合规风险 | 🔴 需决定 |

---

## E. 提示词规则改进清单（可以直接写进 config/recipes/regen_prompt_rewrite.md 和 edit_prompt_rewrite.md）

> 写法约定：每条前面的方括号标适用文件（R = regen_prompt_rewrite.md，E = edit_prompt_rewrite.md），后面写出处。凡是改变现行写法的条目（E-3、E-4、E-9）都要先过 §F 的 A/B 再上线（研究必须闭环）。

**E-0 [R][E] 按目标模型分模板。** 输入里加一行“目标模型：qwen21 / qwen2511 / klein3”。改写器按模型选 C2 表里的那一列。出处：C2；A3 与 C1-d 的保留写法相反。

**E-1 [E] 先判断任务类型，再套写法。** 类型分为：替换（Replace Y with X）、增加、删除、换装、换背景、改姿势、改光线、改表情或妆容、修手、局部重绘、风格。出处：C1-a 1–6 节。

**E-2 [R][E] 只改项目方点名的属性，并且要改到位，不能一眼看不出改了。** 没被要求的修补一律不做（例如“顺手修一下手”）。出处：C1-d “Edit exactly the attribute(s) the user named, push each to a strong and unmistakable degree”、“Only what was asked”；C1-a “Keep the core intention … unchanged”。

**E-3 [R][E]（qwen21）保留用一句总括，不描写外观。**
- 写法：“保持 `<image1>` 中人物的身份、发型、姿势与构图，以及其余画面与输入图完全一致。”
- 删掉现行第 3 条里每次都写的“haze sky-blue waist-length straight hair”外观描述，改成“发型和发色与 `<image1>` 保持一致”。
- 锁定外貌的保障交给参考图槽和 Q1 闸门。
- 出处：C1-d “Say what stays, without repainting it … the more concretely you describe something you meant to keep, the more likely it drifts”。
- **注意**：这一条和 HC-07 外貌锚点的现行写法冲突，需要 A/B 定（§F A/B-3）。

**E-4 [R][E] 画风句只在项目方要求改质感时才写，并放在最后。**
- 现行“每次都写 W Magazine editorial 质感”改为：只在原话涉及质感、肤质、色彩时写。
- 编辑提示词不再拼 image_suffix() 整段风格后缀（这一改动在代码 contract_inputs 里，由 IMGFIX 改）。
- 出处：C1-a “If there are other changes, place the style description at the end”；C1-d Leakage “a style change that drifts a face”。

**E-5 [E] 多图引用。**
- qwen21：N ≥ 2 时一律写 `<image1>`、`<image2>`…；N = 1 不写标签；绝不写“图1”或“the first image”。
- 写明每张图的角色：`<image1>` 是要修改的画布；`<image2>` 提供人物身份；`<image3>` 提供服装……
- 换装时，画布是人物图。
- 出处：C1-d Image Reference Rules；2.1 ComfyUI 模板（高）。
- 2509/2511 用 “Picture N / image N”（A1-2）。

**E-6 [E] 局部修改。**
- 有遮罩时：写“只修改 `<image1>` 中[标注颜色或位置]区域的[对象]”，后接改成什么。
- 改写器拿到的区域描述应当是可视化的位置词（右手、左下角的杯子），由系统把框坐标转换好（见 E-12）。
- 走 InstantX / crop-stitch 这类描述式 inpaint 支路时，提示词改成描述框内**最终的样子**，不写指令。
- 出处：docs.comfy.org 2.1 “Naming the mark's color in the prompt points the instruction at that region”（中）；InstantX “Please use descriptive prompt instead of instructive prompt”（高）；C1-a 第 5 节。

**E-7 [E] 一句话里有多处改动时，逐条列出；超过 2 处，建议拆成多步。**
- 改写器输出 `steps: [...]`，由界面问“分 N 步做？”。
- 出处：C1-b “please list each modification individually”；issue #88 “split them up”；Kontext “Step-by-step modifications”。

**E-8 [R][E] 表情、妆容、五官的改动要“自然、轻微”。**
- 示例写法：“Slightly … with little change, look natural.”
- 出处：C1-a 第 3 节、C1-b。

**E-9 [E] 身份：指向参考图，不用文字描写五官。**
- 写法：“`<image1>` 中人物的面部身份与 `<image2>`（身份脸）一致”。
- 不写 “same face, delicate features …” 这类描写。
- 出处：C1-d “point at that image rather than describing features in words”。

**E-10 [R][E] 用肯定句，不用禁止句。**
- 写“保持背景与输入图完全一致”，不写“不要改背景”。
- cfg = 1 时负面词不生效，不再输出 negative_add（或者只在 cfg > 1 的模型上用）。
- 场景图“无人物、无文字”写成正向描述：“空无一人的[场景]，画面中没有任何文字”。
- 出处：C1-d；2.1 模板 “negative_prompt: unused while cfg is 1”；workflows.negative_for。

**E-11 [R][E] 输出约束。**
- 单一语言、一段连贯的话。
- 不写分辨率和比例。
- 替换类写成 “Replace Y with X” 并简述 X 的关键视觉特征（品类、颜色、材质、长度、位置）。
- 颜色要求精确时可以给 hex（FLUX 3）。
- 出处：C1-a、C1-d、A3。

**E-12 [E] 改写器的输入要补“图里有什么”。**
- 系统先用本地 Qwen3-VL 8B（workflows.text_generate，已经有了）给底图生成一段**文字**事实描述：人物、服装、手的位置、主要物体和方位。
- 这段文字和项目方原话一起发给外部写作 API。
- 图片本身不出本机，符合 K-REV-V01，因为发出去的只有文字。
- 出处：官方改写器都看图（C1-a 调用 qwen-vl-max；C1-d 是 VL 模型）；“choose a reasonable area based on composition” 需要知道构图。

**E-13 [E] 换背景先锁主体。**
- 写法：“保持 `<image1>` 中人物的位置、大小、姿势与光照方向不变，把背景替换为……”
- 出处：C1-c “For background change tasks, emphasize maintaining subject consistency at first”；Kontext “keeping the person in the exact same position, scale, and pose”。

**E-14 [E] 改光线写光源和方向。**
- 写法：“改为从画面左侧来的柔和窗光，人物面部和衣服上的明暗随之变化，其余内容保持不变。”
- 现行 scene_plate 规则里“写具体光源和方向”保留，并推广到人物图。
- 出处：现行规则；Krea Change Lighting 把光源当对象。

**E-15 [E] 改姿势。**
- qwen2511：附关键点图作第 2 张图，写“让 `<image1>` 中的人物摆出 `<image2>` 骨架图的姿势，身份、服装、背景保持不变”。
- 出处：A1-2（2509 原文）。2.1 的姿势用法：没查到，要实测。

**E-16 [E] 修手（没有官方写法，标为推断，需要实测）。**
- 走局部支路：遮罩只盖手 → “只修改 `<image1>` 中红框内的右手：自然的五根手指，指甲为[锁定的钻石水晶甲]，手势……”
- 出处：现行 edit_prompt_rewrite 第 2 条；官方没查到。

**E-17 [R][E] zh_summary 改成“改什么 / 保留什么 / 分几步”三段。**
- 界面上显示“它理解的改动”时直接用。
- 出处：ASSETUX R3“它理解的改动”。

**E-18 [E] 连续编辑超过 4 次时，改写器在 zh_summary 里提示“建议从第 N 版重开”。**
- 出处：A1-5 第 3 条。

---

## F. 模型与工作流建议，以及 A/B 清单

### F1. 编辑类型 → 模型 / 工作流（初稿，按 A/B 结果定稿）

| 编辑类型 | 首选 | 工作流 / 关键参数 | 备选 |
|---|---|---|---|
| 整张小改（质感、表情、换小件） | Qwen 2.1 Turbo **指令编辑** | 官方 image_qwen_image_2_1_image_edit：image_1 = 底图，满步 8，cfg 1，resolution 0，底图对齐到 32 的倍数，不开 custom_size | 2.1 Base 25–40 步 |
| 换装（保脸） | Qwen 2.1 | image_1 = 人物底图，image_2… = 设定图或单品，`<imageN>` 写明角色 | 2511（40 步 / cfg 4 或 Lightning 4 步） |
| 换背景（保人） | Qwen 2.1 | 同上 + 主体锁定句；结果用人物分割 mask 贴回原人物像素（ImageCompositeMasked） | FLUX 3 Klein（列全保留项） |
| 局部重绘（手、脸、道具） | Qwen 2.1 + 区域标注或 mask | 官方 2.1 区域编辑（画圈、涂抹、mask）+ crop & stitch（只送框外扩后的裁片，贴回时框外像素不变） | InstantX Inpainting（描述式提示词）；FaceDetailer / HandDetailer（docs/research/imglab/03） |
| 改姿势 | Qwen 2511 + 关键点图 | 2509/2511 原生 ControlNet 输入（image_2 = 骨架图） | 2511 新视角 |
| 改光线 | Qwen 2511（光照内置） | 2511 模板 | 2.1 指令；IMGLAB 04_relight |
| 场景底图修改 | Qwen 2.1 | 同“整张小改”，无人物要求写成正向描述 | FLUX 3 Klein |
| 带文字的海报、道具 | MOSS-Image 文生图 / Qwen | — | 不做人物编辑 |
| 人物编辑：不用 | MOSS + edit LoRA | 实验性，GPLv3 | — |

### F2. 提示词改写的位置
- 外部写作 API（现行，项目方要求）负责“懂项目方的意思”。
- 本地 VL caption（E-12）负责“知道图里有什么”。
- 本地 Qwen-Image-2.1-PE-I2I 不替代外部改写，只作 A/B 臂（A/B-5）。原因是项目方说过“不能用系统本地来写”。

### F3. 要实测验证的 A/B 清单
固定样本：林晚 6 张（特写、中景、全身各 2）+ 双人镜 2 张 + 场景底图 2 张。每张跑 5 类编辑：换鞋、换背景、改光线、修右手、改表情。
度量：Q1 锚分（对 L-086）、框外像素差（LPIPS 或 SSIM，只算框外）、改动到位率（VQA 判“是否改了点名的属性”）、Q4 肤质。每格 2 个 seed。

| # | A | B | 要回答的问题 |
|---|---|---|---|
| A/B-1 | 现行：init latent + denoise 0.55，槽位 = 身份脸 / 设定图 | 官方：image_1 = 底图，满 8 步，槽位后移 | D1 是否根因：Q1 和改动到位率是否同时提升 |
| A/B-2 | 矩形整张改 + 羽化贴回 | 2.1 区域标注 / mask + crop & stitch + ImageCompositeMasked | 框外是否零改动、接缝是否消失 |
| A/B-3 | 提示词写外貌锚点（发色、发型描写） | 一句总括 + 指向参考图（E-3 / E-9） | C1-d 的说法在我们的数据上是否成立；HC-07 是否受影响 |
| A/B-4 | 拼风格后缀 | 不拼（E-4） | 整张“被重新风格化”的程度、Q4 |
| A/B-5 | 外部 API 改写（文字） | 外部 API + 本地 VL caption（E-12） | 位置类改动（左手、桌上的杯子）是否命中 |
| A/B-6 | 外部 API 改写 | 本地 PE-I2I（thinking on） | 只作参考：差多少；**不自动替换** |
| A/B-7 | Qwen 2.1 Turbo | Qwen 2.1 Base 25 / 40 步 | 编辑的步数收益和时间成本 |
| A/B-8 | Qwen 2.1 | Qwen 2511（40 步 / Lightning 4 步） | 换装、改光、改姿势哪个更好 |
| A/B-9 | Qwen 2.1 | FLUX 3 Klein 蒸馏 16 步 + 官方扩写器 | 保脸和肤质；扩写器在本机跑，不违反“写作走外部”吗？要总调度定 |
| A/B-10 | 一次改三处 | 拆成三步 | E-7 是否值得做进界面 |
| A/B-11 | 连续编辑 1/3/5/7 轮 | — | 我们的退化轮数，定 E-18 的阈值 |
| A/B-12 | resolution 0 + 32 对齐 | 现行 _fit_size(1920) + center-crop | 有没有偏移（D14） |

---

## 需要决定（给总调度）

1. 🔴 **Qwen-Image 2.1 是 qwen-research 许可**（HF 卡原文）。生产在用，要不要找人确认商用条款，或者同时让 2511（Apache-2.0）进 A/B 作为后备？
2. 🔴 **E-3（不再用文字写外貌锚点）和 HC-07 现行写法冲突。** 建议先做 A/B-3，按数据定；在此之前规则文件不改这一条。
3. 🟡 **FLUX 3 Klein 官方要求配本地扩写器**，PE-I2I 也是本地模型，这和“写作不能用本地”冲突。建议：只作为模型内部的扩写，放在外部改写之后，并且只在 A/B 中使用。由总调度定口径。
4. 🟢 MOSS-Image 不进人物编辑主路径（证据见 A4）。
