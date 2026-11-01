# Qwen-Image 2.1 / Turbo 调参与提示词调研

调研日期：2026-11-01。方法：逐一读官方模型卡、GitHub README、diffusers 与 ComfyUI 源码、官方提示词改写器的系统提示词、ComfyUI 官方文档与工作流模板、Civitai 模型页（API 拉取的原文）、HF 讨论区和 GitHub issues。
**Reddit 无法直接访问**（WebFetch 被拒，JSON 接口返回 Blocked），Reddit 内容只能通过转述站拿到，所以社区部分主要来自 HF 讨论区、GitHub issues 和 Civitai。
**没有找到 Qwen-Image 2.1 的 arXiv 技术报告**（搜索只找到 2.0 报告 arXiv 2605.10730）。官方博客 qwen.ai 页面要靠 JS 渲染，抓不到正文，改用阿里云国际站的同文博客。

置信度：**高** = 官方文档或源码原文直接说明；**中** = 官方间接说明、多个社区来源一致，或从源码推断；**低** = 单个社区帖或个人经验。

---

## 一、可执行结论

| # | 结论（一句话） | 置信度 | 来源 |
|---|---|---|---|
| 1 | 我们的 Turbo 采样（8 步 ManualSigmas `1.0,0.978453,…,0.414568,0`、euler、cfg 1）和官方完全一致，**不要改步数或调度**。只加步数没用，官方也说其他调度"未评估"。 | 高 | S2 S7 S12 S10 |
| 2 | 参考图在提示词里**按官方写法用 `<image1>`、`<image2>`（尖括号加英文）**，不要写"图1"。编码器模板在用户文本前面拼的就是字面的 `<image1><视觉块> <image2><视觉块>…`，官方编辑改写器也明令禁止"图1"写法。 | 高 | S5 S13 S14 S10 S12 S6 |
| 3 | **身份靠指向参考图，不靠文字描述五官**。官方改写器原话：用文字描述长相会让模型重新生成并降低相似度；要保留的东西描述得越具体越容易漂移，只说"保持 `<image1>` 的面部特征不变"即可。 | 高（官方规则）／效果未自测 | S5 S6 |
| 4 | **cfg 1 时负面提示完全不生效**（ComfyUI 直接跳过负向这一遍，diffusers 也会忽略）。要排除什么，就用肯定句写"要什么"，不要写"不要…"。官方改写器同样要求用肯定句而不是禁止句。 | 高 | S8 S10 S12 S5 S4 |
| 5 | **提示词没有长度截断**（ComfyUI 的 Qwen3-VL 分词器 max_length=99999999，diffusers 不截断）。官方改写器把每条 T2I 提示词都写成约 20 句、400–500 词，所以写长没问题。 | 高 | S14 S8 S4 |
| 6 | **ComfyUI 里 `(词:1.2)` 这类权重语法对 Qwen 2.1 无效**：Qwen3-VL 分词器调用时强制 `disable_weights=True`，括号会原样当成文字送进去。 | 高 | S14 |
| 7 | 官方改写器明确**不写质量助推词**（"masterpiece、8K、highly detailed、award-winning"），要求直接描述看得见的东西。我们后缀里的"焦点锐利、皮肤纹理清晰、微反差强"属于同一类，建议换成具体的光源、方向、材质和镜头描述。 | 中 | S4 S26 S23(#11) |
| 8 | 官方原生 2K。9:16 的官方尺寸是 **1536×2752**。我们出 1152×2016（约 2.3MP），在范围内但低于原生。官方推理默认就是 2048 档；远超 2K（如 4K）会降低提示词遵循度。 | 高（尺寸）／中（对质感的影响） | S1 S3 S10 |
| 9 | 参考图会被 `TextEncodeQwenImage21` 按 `resolution`²（默认 1024² ≈ 1MP）等比缩放到 32 的倍数，**同时送进视觉编码器和 VAE（作为参考 latent 拼进序列）**。脸只占小部分的参考图，脸的有效像素会很少。身份脸图建议裁成脸部特写再送入。 | 高（机制）／中（建议） | S13 S8 |
| 10 | **krea2_film_texture_qwen21 是在 base 上训练的**，作者推荐 40 步、CFG 2.0，强度 I2I 0.50、T2I 0.50–0.65。我们在 Turbo 8 步 cfg1 上用，重档 0.8 已超出作者推荐范围，属于未经验证的用法。 | 中 | S16 |
| 11 | cfg：官方路径是 1（diffusers 注释说"meant to be sampled without guidance"）。ComfyUI 官方文档说 cfg 2 遵循更紧但边缘过锐，cfg 5 严重劣化。社区在 **base** 上用 cfg 3–4 加负面提示修偏黄、手指和质感。**Turbo 上 cfg>1 没有任何官方评估。** | 中 | S8 S10 S22 S23 S25 |
| 12 | 换 base 是否能改善塑料感，目前没有官方对比。社区说 Turbo 和 25 步 base 基本持平。Viggle 有一种"加速 7 步 + base 收尾 2 步"的混合方案，作者称细节更细（只在 diffusers 里有）。值得做 A/B：Turbo 出图后用 base 低噪声段收尾。 | 低–中 | S20 S25 S30 |
| 13 | 官方 VAE 在写实、浅肤色人脸上有细棋盘格，用 texture_fix VAE 能修（我们已在用）。**不要用分块 VAE 解码**，否则会出现紫绿竖条。 | 高 | S10 S21 S22(#12) S24(#5 #14) |
| 14 | 参考图如果是本模型用种子 X 生成的，**生成新镜头时不要再用同一个种子 X**，否则会过饱和、照搬构图或出现碎块。 | 中–高 | S22(#61) S24(#9) |
| 15 | 服装要**逐件写出名称、颜色和材质**。社区实测只写"image 2 的衣服"时 18 次里有 7 次没换上，逐件命名后 18 次全成。官方改写器也要求每件衣服写颜色和材质，材质要具体（如 coarse linen、brushed metal）。 | 中 | S19 S4 |
| 16 | 官方人物描述规则：写体态、**视线方向（where they are looking）**、表情、发型、肤色，以及每件衣服的颜色和材质。年龄只写人生阶段或年代（如 in her thirties），不写具体岁数。脸转开或被裁掉时要明确写出来。 | 高（官方规则） | S4 |
| 17 | 官方 T2I 提示词结构是**先写媒介、风格和主体**（"A vertical realistic photograph of …"），然后写背景、姿势与画面位置、头脸、身体与服装、手持物、边缘，**单独一句写光线**，最后一句写整体构图。也就是主体在前，镜头和摄影词嵌在描述里。 | 中–高 | S4 S26 S27 |
| 18 | 语言：官方 T2I 改写器一律输出英文；编辑改写器遇到中文指令就写中文。官方中文示例："将<image1>中的人物和<image2>中的人物置入…保持两位人物的面部特征、发型和服装外观完全不变。"中文提示词加 `<imageN>` 是官方认可的写法。 | 中–高 | S4 S5 S6 |
| 19 | 用 Qwen 自身做重绘或放大会**过度造纹理**（凭空出现毛孔、雀斑，显老），社区专门训练了 Restore LoRA 来压制。所以细节重绘这一步要低强度，或配合 Restore LoRA，不要指望"皮肤纹理/毛孔"类提示词。 | 中 | S19 |
| 20 | 不要在 Turbo 上叠加其它加速 LoRA（社区实测会出现皮革感和颗粒）。普通 KSampler 设 8 步（不用官方 sigmas）"出来是颗粒感的"。 | 中 | S19(2994247) S23(#22) |

---

## 二、分主题引用

### A. 步数、调度、cfg、shift

**[S2] HF Qwen/Qwen-Image-2.1-Turbo 模型卡**：https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo （高）
> "an accelerated checkpoint of Qwen-Image-2.1 for text-to-image generation and image editing with **8 denoising steps**."
> "The checkpoint includes its recommended sampling schedule … Generation uses CFG=1 by default, and prefix KV caching reuses the text and reference-image context across denoising steps."
> "Setting `num_inference_steps` alone does not override it. For experiments, an explicit call-time `sigmas` argument overrides the saved schedule; other schedules have not been evaluated for this checkpoint."

**[S7] Turbo 的 model_index.json 和 scheduler_config.json**：https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo/blob/main/model_index.json （高）
> `"sample_sigmas": [1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568]`；Turbo 的 scheduler `"use_dynamic_shifting": false`。base 的 scheduler 为 `"use_dynamic_shifting": true, "base_shift": 0.5, "max_shift": 0.9, "shift_terminal": 0.02, "time_shift_type": "exponential"`。
→ 我们的 ManualSigmas 是这 8 个值加末尾的 0，**与官方逐位一致**。HF 讨论里也有人解释："diffusers adds an implicit 0 but comfy doesn't"（S23 Turbo#4）。

**[S3] GitHub QwenLM/Qwen-Image-2.1 README**：https://github.com/QwenLM/Qwen-Image-2.1 （高）
> "Both calls use the saved **8-step schedule** and the default CFG=1 setting."
> 默认参数表："`num_inference_steps` | 40"；"`width` / `height` | 2048 × 2048 | Native 2K resolution"
> SGLang 示例："--num-inference-steps 40 --guidance-scale 1"

**[S8] diffusers `pipeline_qwenimage21.py`**：https://github.com/huggingface/diffusers/blob/main/src/diffusers/pipelines/qwenimage21/pipeline_qwenimage21.py （高）
> "`true_cfg_scale` … Classifier-free guidance scale. Enabled by `true_cfg_scale > 1` together with a negative prompt. **Qwen-Image 2.1 is meant to be sampled without guidance, hence the default of 1.0.**"
> "negative_prompt … Ignored when `true_cfg_scale` is not greater than 1."

**[S10] docs.comfy.org Qwen-Image-2.1 教程**：https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1 （中文版 https://docs.comfy.org/zh/tutorials/image/qwen/qwen-image-2-1 ）（高）
> "At `cfg` 1 ComfyUI skips the negative conditioning pass, so a negative prompt has no effect on these workflows. The template keeps `cfg` 1, which is the path Qwen-Image-2.1 is published for; raise it only when you want the negative prompt to take effect. `cfg` 2 follows dense prompts more closely, including small text and numbers, at the cost of over-sharpened edges. Higher values shift exposure toward over-bright or over-dim, `cfg` 5 degrades quality badly, and `cfg` 0.5 breaks the image."
> 中文版："基础工作流使用 `steps` 25、`cfg` 1、`euler` sampler 和 `simple` scheduler … 两个 Turbo 模板改为 8 步采样，使用 `cfg` 1、`euler` sampler 以及随蒸馏 checkpoint 一同提供的固定 `ManualSigmas` 调度，因此只有在更换调度时才应提高步数。"
> "Qwen-Image-2.1 发布的推理流程使用 `euler` sampler 和约 40 到 50 步 … 手部、手指这类难处理的细节大约在 30 步时收敛，而从 25 步提到 40 步可以减少细节区域的杂乱噪点。"
> "ComfyUI 的平移按 1024x1024 拟合，输出尺寸偏离该分辨率后两者的贴合度会下降。"（这句话针对 base 加 simple 调度，ManualSigmas 不受影响）

**[S15] ComfyUI `supported_models.py`**：https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/supported_models.py （高）
> `# scheduler mu at 1024x1024 (base 0.5 @ 256 tokens, max 0.9 @ 8192)` → `"shift": 0.69`
→ 用 base 加 simple 调度时，ComfyUI 的 shift 固定为 1024² 时的 mu。diffusers 则按分辨率动态计算，2K 时 mu 更大。Turbo 用 ManualSigmas，不受影响。

**[S12] Comfy-Org 官方工作流模板里的注释**：https://github.com/Comfy-Org/workflow_templates/blob/main/templates/image_qwen_image_2_1_turbo_t2i.json （高）
> "steps: this template runs the Turbo checkpoint, which is distilled for **8 steps**; the schedule is fixed in the ManualSigmas node (`1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0`) and is what makes 8 steps enough. Raise the step count only together with a different schedule."
> "negative_prompt: unused while cfg is 1."
> 模板节点实际值：`ManualSigmas`、`KSamplerSelect ["euler"]`、`CFGGuider [1]`；base 模板为 `KSampler [.., 25, 1, "euler", "simple", 1]`。

**[S25] stablediffusion.fr 指南（第三方，自称测了约一千张图）**：https://stablediffusion.fr/guide/qwen-image-2-1 （中低）
> "At CFG 1 the image is flatter and loses fine texture."
> "Do not try to help the Turbo with more steps." / "The distilled checkpoint wants its 8 sigmas."
> "On every non-photographic prompt of the ten seeds, the distilled model drifted towards photographic realism."
> "On the ten seeds the LoRA on the base checkpoint gave the same images as the Turbo checkpoint, only slower."

**[S22] HF Qwen/Qwen-Image-2.1 讨论区**（中低，个人经验）
- #14 https://huggingface.co/Qwen/Qwen-Image-2.1/discussions/14 ："生图可以提高cfg并使用负面提示词，但编辑不要提高cfg"
- #10 https://huggingface.co/Qwen/Qwen-Image-2.1/discussions/10 ："set cfg to 3-5 & Use negative prompt to remove some of its artifacts."
- #29 https://huggingface.co/Qwen/Qwen-Image-2.1/discussions/29 （手脚问题）："提高CFG，在负面提示词中加入手指畸形等相关词"
- #56 https://huggingface.co/Qwen/Qwen-Image-2.1/discussions/56 ："Muddy, overprocessed images can come from a CFG that is too high or a different scheduler."

**[S23] HF Comfy-Org/Qwen-Image-2.1 讨论区**（中低）
- #22 https://huggingface.co/Comfy-Org/Qwen-Image-2.1/discussions/22 ：用官方 sigmas 后 "night and day difference. before images were muddy and ugly, now they are good"；"mathematically no simple isn't close to the correct sigmas."
- #7 https://huggingface.co/Comfy-Org/Qwen-Image-2.1/discussions/7 （base）："8-12 steps with cfg 1.5 - 3.5 and the remaining steps with cfg1 … with cfg1 the prompt follow and the quality of the images suffer a lot."
- #14 https://huggingface.co/Comfy-Org/Qwen-Image-2.1/discussions/14 ："出现人物畸形或者昏暗泛黄等问题，去提高CFG值以及在负面提示词中加入需要解决的"；"without it [turbo lora] and cfg 4 does pretty well"
- #11 https://huggingface.co/Comfy-Org/Qwen-Image-2.1/discussions/11 ："bump steps to 35–40 … Artifact disappeared completely at 40"；之后又说 "changed a bit my prompt which was too 'high definition' so the model was going wild"；最后换成 texture-fix VAE 后 "fully addressed and fixed the issue … as little as 20 steps"。

**[S18] Civitai 2958738 "Qwen 2.1 Turbo LoRas"（转载 Viggle/Pruna 声明）**：https://civitai.com/models/2958738 （中）
> Viggle v0.1："On complicated image editing (multi-reference composition, face swaps, identity-preserving edits, instructions with several constraints) it is clearly worse than the 40-step base model."
> Pruna v0.1："does not yet match the visual quality of the base model."
> 作者经验："Best settings for Viggle/PrunaAI 4-step: er_sde/beta … 5-8 steps, cfg 1-2 (+ lenovo/zjourney refiner lora to remove some of the overbaked, high-contrast, yellow tint)"
注意：以上说的是**社区加速 LoRA**，不是官方 Turbo checkpoint。

**[S20] Viggle/Qwen-Image-2.1-viggle-turbo**：https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo （中）
> "**New 9-step mode:** 7 turbo steps, then the LoRA is switched off and the base model finishes the last two. Finer detail …"
> "We think 6 steps is close to its capacity … sharper came with more grain, less grain came with a softer look. Beyond this point, quality most likely has to be paid for with steps"
> "To change the step count, add or remove steps at the high-noise end only … Moving the low-noise nodes makes images softer; plain `num_inference_steps` without `sigmas=` and CFG do not help."
> 已知局限："identity-preserving edits … can still fall short of the base model: duplicated or ghosted figures, identity drift."

**[S30] Civitai 2998097 Turbo 8 步对 25 步对比工作流**：https://civitai.com/models/2998097 （低）
> "Proves the turbo LoRA 8-step schedule holds almost par with the original 25-step pipeline"（base 一侧用 "CFG 3.5"）

### B. 分辨率与长宽比

**[S1] HF Qwen/Qwen-Image-2.1 模型卡**：https://huggingface.co/Qwen/Qwen-Image-2.1 （高）
> `"9:16": (1536, 2752)`，`"2:3": (1696, 2528)`，`"1:1": (2048, 2048)` …
**[S3]** "Qwen-Image-2.1 natively supports 2K resolution." "both checkpoints default to the 2048 resolution level."
**[S10]** "远超模型 2K 训练尺寸的目标（例如 4K）会降低提示词遵循度。"；"降低 `resolution` 是通过生成更小的结果提速，并不会增加细节。"
**[S5] PE-I2I 系统提示词**："For output resolution, always use 2K-level resolution regardless of whether the user says '2K', '4K', or '8K'."
**[S20] Viggle**（加速 LoRA）："About 1 MP is the sweet spot; up to about 4 MP works."（中低，只适用于该 LoRA）
**[S16] krea2 LoRA 训练分辨率**："Trained at Native 1920×1088 (16:9 FHD)"，推荐 "1920×1088 / 2752×1536 (2K)"。

### C. 参考图：数量、顺序、引用写法、缩放、身份

**[S1][S3][S9] 官方数量** （高）
> "Support up to **10 reference images** … and preserve identity for people and products."（S1）
> 阿里云博客 https://alibabacloud.com/blog/qwen-image-2-1-compact-efficient-and-unified-image-creation_603586 ："For portraits, the model better preserves facial features so that a person's identity remains more consistent across edits."（S9）
> ComfyUI 节点支持 16 个槽位（S10）："The Text Encode Qwen Image 2.1 node accepts up to 16 slots (`image_1` to `image_16`)"

**[S5] PE-I2I 系统提示词（官方改写器训练时用的规则）**：https://huggingface.co/Qwen/Qwen-Image-2.1-PE-I2I/blob/main/system_prompt.txt （高）
> "For Multi-Image Input (N >= 2), the rewritten instruction MUST use `<image1>`, `<image2>`, ... to refer to each input image. **Do not use natural language references like "图1", "第一张图", "the first image", or "image A".** This tagging format is mandatory and non-negotiable. For single-image input (N = 1), do NOT use tags"
> "State each image's role explicitly — which one is the canvas … and which supply material to transfer … For scene generation with no canvas (合影/合照 and the like), all images serve as identity sources. Describe every referenced image individually"
> "**Identity is the hardest invariant.** … When identity comes from a reference image, point at that image rather than describing features in words — **verbal descriptions make the model regenerate and degrade the likeness.**"
> "**Say what stays, without repainting it.** … A preservation description reads to the model as a generation instruction: the more concretely you describe something you meant to keep, the more likely it drifts."

**[S6] 官方 prompt_rewrite 示例数据**：https://github.com/QwenLM/Qwen-Image-2.1/blob/main/prompt_rewrite/data/edit_example.jsonl （高）
> `"prompt": "将<image1>中的人物和<image2>中的人物置入一个现代抖音直播间的场景中，生成一张两人并排坐在直播桌后共同面向镜头介绍产品的合影照片。保持两位人物的面部特征、发型和服装外观完全不变。"`
> README："Every image is sent in order, because the system prompt tells the model to address them as `<image1>`, `<image2>`, ... -- reorder them and every reference in the rewrite silently re-points."

**[S14] ComfyUI `comfy/text_encoders/qwen_image21.py`**：https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/text_encoders/qwen_image21.py （高）
> `refs = " ".join("<image{}>{}".format(i + 1, VISION_BLOCK) for i in range(len(images)))`，`llama_template = T2I_TEMPLATE.replace("{}", refs + "{}", 1)`
→ 实际送进编码器的是 `<image1><|vision_start|>…<|vision_end|> <image2>…` 加上你的提示词，所以提示词里写 `<image1>` 和模板标签是同一个字面 token。diffusers 的模板相同（S8）。
> 系统提示词固定为 `"Comprehend and analyze the provided prompt."`，编码后会被丢掉（S8、S14）。

**[S13] ComfyUI `comfy_extras/nodes_qwen.py` TextEncodeQwenImage21**：https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_qwen.py （高）
> resolution 提示："Reference images are resized to about resolution x resolution pixels, at multiples of 32, preserving aspect ratio. 0 keeps each reference at its own size"
> images 提示："Reference images, seen by the text encoder and **spliced into the sequence as VAE latents**."
> latent 输出提示："Empty latent on the first reference image's size, to match with sampling as any other size shifts the edit."
> 代码：按 `image_N` 的数字排序；同一份缩放图既送视觉编码器也做 `vae.encode`；接了 VAE 时视觉 token 会被丢掉，由参考 latent 代替（S14："vision tokens are replaced by reference latents in the DiT"）；正负两路都带同样的参考图。

**[S10] ComfyUI 文档的编辑提示词示例** （高）
> "Keep the character and pose in <image1> unchanged, put this light blue denim shirt from <image2> on the character, preserve the original facial features, hair, body shape and pose"

**[S20] Viggle**："Reference order decides which image `image 1` / `image 2` in the prompt refers to. Without `height`/`width`, the output aspect ratio follows the **last** reference (in ComfyUI: the **first**)."（中）

**[S19] ausboss（Civitai）**（中）
- Consistency LoRA https://civitai.com/models/2969143 ："Sample on that latent: a latent of any other size makes Qwen zoom by the size ratio, and no LoRA can undo that."（只针对编辑）
- Multi-Image Edit https://civitai.com/models/3000002 ："The boxes do the naming. 'The outfit from image 2' alone changed nothing in 7 of my 18 test swaps; with each piece named, all 18 went through."

**[S22] #11 中文用户反馈** https://huggingface.co/Qwen/Qwen-Image-2.1/discussions/11 ："脸不变能力相比2.0稍微有些进步，但仍不达预期。"（低）

### D. 提示词写法（官方改写器规则）

**[S4] PE-T2I 系统提示词**：https://huggingface.co/Qwen/Qwen-Image-2.1-PE-T2I/blob/main/system_prompt.txt （高，这是官方 T2I 改写器的写法规范；社区称模型就是用这类输出训练的，见第三节）
> 开头句："`The image is a ⟨vertical / wide / square / tall⟩ ⟨style⟩ ⟨photograph · …· portrait · …· close-up …⟩ of ⟨subject⟩, ⟨the background and its palette⟩.` … or a bare `A vertical realistic photograph of …` … The medium noun is the one part that is never omitted."
> 单主体顺序："**If one subject fills the frame** — a portrait, a close-up … walk the subject instead: the background and how far it falls off, then the subject's pose and where it is placed in the frame, then head and face, then body and each garment or surface, then what is held or touching it, then whatever little is left at the edges."
> 光线："Every image has light in it … the source, its direction, its quality, and the shadows and highlights it leaves … give it a sentence of its own — `The lighting is …`"
> 长度："about twenty sentences and four to five hundred words … a thin brief never buys a thin description."
> "**Observe, don't instruct.** Present tense, third person, declarative. No 'you', no 'create', no 'make sure' … **No quality boosters — no 'masterpiece', '8K', 'highly detailed', 'award-winning'.**"
> "**People get their observable surface.** Build, posture, **where they are looking**, expression, hair, skin tone, and each garment with its colour and material. Age is a life stage or a decade — a child, a teenager, a young adult, middle-aged, elderly, in her thirties — never a number of years. If a face is turned away or cropped, say that instead of describing it."
> "**Give the material, not just the noun.** Brushed metal, matte plastic, glossy ceramic, coarse linen …"；"**Name colours with a modifier, almost never bare.**"
> "Photographic and design vocabulary is welcome: shallow depth of field, bokeh, backlit, close-up, negative space"
> "Never write a ratio, a resolution, or a pixel count into the description itself."
> "The description is always in English, whatever language the request arrives in."

**[S5] PE-I2I 系统提示词** （高）
> 语言："User instruction is in Chinese → write the description in Chinese."
> "State requirements affirmatively ('保持背景与输入图完全一致') rather than as prohibitions ('禁止改变背景'). Standard preservation phrasing '保持/保留[X]不变' is fine."
> "**Write it as an instruction.** Lead with the operation, not a description of the finished picture"
> 单图生成新场景（写真）："If the task generates a new scene from scratch using the input image only as an identity reference (e.g., '拍一套写真'…), do NOT follow the input image's ratio"

**[S6] prompt_rewrite 输出格式**：`"negative_prompt": ""`，官方改写器不产出负面提示。（高）

**[S3][S11][S12] 官方推荐用改写器** （高）
> "For best results, we recommend using the official **prompt rewriting models** to expand short prompts into detailed, high-quality descriptions."（S3）
> 模板注释："`thinking_mode`: … The checkpoint was trained with a reasoning block and loses quality without it."；官方 max_new_tokens 为 16256（T2I）和 24000（编辑）；T2I 的 presence_penalty 为 1.5（S10、S12）。

**[S14] 权重语法** （高）
> `qwen3vl.py`：`tokens = super().tokenize_with_weights(llama_text, …, disable_weights=True, **kwargs)`；max_length 为 `max_length=99999999`。
**[S26] kjranyone 提示词指南（第三方）** https://github.com/kjranyone/qwen-image-2.1-prompt-guide/blob/main/skills/qwen-image-prompt-en/SKILL.md （中低）
> "Front-load the subject."；"Natural sentences, never tag lists."；"Write descriptive prompts in English, whatever language the user speaks."
**[S27] Runware Pro API 提示词指南（第三方）** https://runware.ai/docs/models/alibaba-qwen-image-2-1-pro/guides/prompting （中低）
> "Lead with the subject and its purpose."；顺序为 subject、camera、composition、detail、props、lighting、style；"anything left vague is something the model will decide on its own."

**透明图专用格式（官方，供参考）**（S3）：`This is an RGBA image with transparency. <your description>. The image has alpha channel and the background is transparent.`

### E. 写实、质感、塑料感

**[S1][S9] 官方定位** （高）
> "**Realistic Textures and Refined Aesthetics** — Improved typography, portrait lighting, and fine details"（S1）
> "For portraits, improved lighting and fine details give generated images a more realistic appearance."（S9，官方没提到皮肤）
> RunningHub 转述 https://www.runninghub.ai/post/2101686169661693953 ："Optimized portrait lighting, skin/material details"（S29，中）

**[S16] Civitai 3010645 krea2 35mm Film Texture LoRA**：https://civitai.com/models/3010645 （中，作者自述）
> "Vanilla Qwen-Image 2.1 … often produces **overly smooth plastic skin, synthetic surface sheen, or a digital yellow-green cast**."
> 推荐："LoRA Strength (I2I / Edit) | 0.50 | … (locks 100% facial identity)"；"LoRA Strength (T2I) | 0.50 – 0.65"；"Steps / CFG | 40 steps / CFG 2.0 | Use ModelSamplingFlux (max_shift: 0.693548, base_shift: 0.5)"；"Base Model | Qwen-Image 2.1 | Fully compatible with both bf16 and int8_convrot"；"Connect right after Load Diffusion Model (before QwenImage21Cache / ModelSamplingFlux)"
> 训练："Rank 64 … timestep_bias: low_noise … Trained on 2,951 VLM-audited cinematic stills at native 1920×1088"
→ 作者**没提 Turbo**；训练偏低噪声段，理论上主要影响后几步的细节。

**[S17] Civitai 2986100 Glamour Realism LoRA**：https://civitai.com/models/2986100 （中低）
> "It aims to reduce the plastic-skin and washed-out look … recommended strength is 0.6 … At 0.8 and above, outfit and pose may start to drift"；"It keeps a soft, polished glamour finish. It is not a raw or gritty skin-texture LoRA"

**[S19] ausboss Restore LoRA**：https://civitai.com/models/2989697 （中）
> "Qwen Image 2.1 can upscale a small or worn picture without this LoRA, but it overdoes it. **Skin turns gritty, pores and freckles show up that were not there, faces look older**, and the picture shifts a few pixels."
> "Face match 0.79 without, 0.88 with"
**[S19] ausboss Turbo Generate + Edit**：https://civitai.com/models/2994247 （中）
> "A plain KSampler set to 8 steps came out gritty in my tests"；"Do not add a speed LoRA. Viggle Turbo on top of this checkpoint broke the picture: leathery skin and grit."；"The Consistency LoRA … Left on for a new picture it makes the result softer"

**[S28] Reddit 帖转述（agihunt 转述站）**：https://agihunt.info/en/p/1a15cad38191520b9f7fe0e0822 → 原帖 https://www.reddit.com/r/StableDiffusion/comments/1xbdawd/qwenimage_21_edit_plastic_skin/ （低，原帖未能读到）
> 转述："overly smooth, plastic-looking skin on nearly every human image"；"plastic skin" 加进负面提示无效（这和 cfg1 时负面提示不生效一致）；讨论提到 "default beautification bias"。

**[S22] HF #10** "Please remove images with ugly GPT image piss filter and grain from your dataset."（低，反映偏黄问题）；**[S23] #10** 偏黄有专门的后处理节点 ComfyUI-Bleachery，也有人说"提高CFG，并加入负面提示词就可以解决"（低）。

### F. VAE、伪影、种子

**[S10]** "Qwen-Image-2.1 自带的 VAE 会在细节丰富的写实类输出上留下细密的棋盘状纹理。这类伪影来自解码器而不是采样过程，所以提高步数并不能消除它。"（高）
**[S21] texture-fix VAE**：https://huggingface.co/madebyollin/texture-fix-vae-for-qwen-image-2.1 （高）
> "finetuned to produce cleaner textures with no checkerboard artifacts"；"makes perceptual quality metrics (rFID) better and reconstruction accuracy metrics (LPIPS/PSNR) slightly worse"；"I haven't done thorough tests on faces"（S22#12 原作者回复）
**[S22] #12** https://huggingface.co/Qwen/Qwen-Image-2.1/discussions/12 ："It's more noticeable when you generate a high-resolution image that has people with light skin tones and zoom in on their faces."（中）
**[S24] GitHub issue #5、#14** https://github.com/QwenLM/Qwen-Image-2.1/issues/5 ："使用了VAE解码（分块）会导致出现这个问题 … 不使用VAE解码（分块）即可"；"Diffusers VAE 开启默认分块解码（tile 256、stride 192）… 完整解码没有条纹"（中–高）
**[S24] #9** https://github.com/QwenLM/Qwen-Image-2.1/issues/9 ："用生成参考图的 seed 时，每次都没有生成新场景，而是过饱和地照搬了参考图的构图 … 临时解决办法：使用与生成输入图不同的 seed（或尺寸）。"（中）
**[S22] #61** https://huggingface.co/Qwen/Qwen-Image-2.1/discussions/61 ："the editing path reused a noise pattern strongly correlated with the reference image. Changing the second seed resolves this problem."（中）

---

## 三、未证实或矛盾

1. **cfg 的取值有矛盾**：官方（diffusers 注释、ComfyUI 模板）说 2.1 设计上就是 cfg 1；ComfyUI 文档说 cfg 2 更遵循但过锐；krea2 LoRA 作者推荐 CFG 2.0；社区在 base 上用 3–5 加负面提示修偏黄、手指和质感；stablediffusion.fr 说 "At CFG 1 the image is flatter and loses fine texture"。**Turbo 上 cfg>1 没有任何官方或可信的测试**，Turbo 是 CFG 蒸馏模型，提高 cfg 大概率过曝或过锐（推测）。
2. **"图1"和 `<image1>` 的实际效果差异没有量化数据**。官方改写器强制用 `<image1>`，模板里也是字面 `<image1>`，所以 `<image1>` 是训练分布内的写法。但"图1"是否明显更差，没有人做过对照。Viggle 卡片用的是 "image 1"。
3. **"Qwen 2.1 是用 PE 改写器的输出训练的"** 只是 HF 讨论里的一条社区说法（Comfy-Org 讨论 #4，mcfadyeni），官方没有确认。官方只说"推荐使用改写器"。
4. **中文景别词（近景、特写、中景）和英文 close-up 的效果对比：没找到任何资料**。官方 T2I 改写器把一切改写成英文，并把 "close-up"、"portrait" 列为媒介名词；编辑改写器接受中文。中文景别词是否被准确执行，需要我们自己固定种子做 A/B。
5. **否定句是否会反向**：官方只要求"用肯定句"（S5）和"描述画面里有什么"（S4），没说否定句会反向。第三方说写 "no laptop" 会把 laptop 带进画面，但没有给出测试。
6. **Turbo 和 Base 在塑料感、身份保持上的差异：官方没有对比**。社区说法互相矛盾：一方说 Turbo 和 base 基本持平（S25、S30），另一方说社区加速 LoRA 在身份保持上明显不如 base（S18、S20，针对的不是官方 Turbo）。
7. **krea2 LoRA 在 Turbo 上的适用性**：作者只在 base 40 步 CFG2 上给了推荐，Turbo 和高强度（0.8）的用法未经验证。作者说 "locks 100% facial identity" 只是自述。
8. **"1.5 倍出图、缩回、USM 锐化"对塑料感和油光的影响：没找到任何资料**。我们推测：缩小会抹掉微纹理，USM 会放大高光边缘，可能加重"油"和"磨皮"感；原生出 1536×2752 后不锐化，或改用轻度颗粒，可能更好。需要自测。
9. **系统后缀里"自然高光、微反差强、暖调通透"会不会导致"油、偏黄"：没有资料**。krea2 作者和社区都说原模型本身就有 "synthetic surface sheen" 和偏黄倾向，"暖调"可能叠加偏黄（推测）。
10. **"皮肤纹理、毛孔"类提示词有没有用：没有官方说法**。官方规则是不写质量助推词，改写可观察的材质。社区有反例：提示词太 "high definition" 时 "the model was going wild"（S23#11）；Qwen 自己重绘时会凭空造毛孔、显老（S19）。所以这类词可能过度，也可能无效，需要 A/B。
11. **Reddit r/StableDiffusion 和 r/comfyui 原帖都没能直接读到**（站点拒绝抓取），所以 Reddit 相关内容只来自转述站，置信度低。
12. **diffusers 默认 `output_resolution=1024`，README 却写默认 2048**：调用 diffusers 时不传 width/height 只会得到 1024 档，README 示例都显式传了 2048 档。ComfyUI 不受影响。
13. **官方没有说参考图最多几张身份图最稳**。只说"up to 10"，Comfy 节点支持 16 张；Viggle 说超过 3 张参考图"只肉眼检查过"。我们用 3–4 张，在官方范围内。

---

## 来源索引

- S1 https://huggingface.co/Qwen/Qwen-Image-2.1
- S2 https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo
- S3 https://github.com/QwenLM/Qwen-Image-2.1 （README）
- S4 https://huggingface.co/Qwen/Qwen-Image-2.1-PE-T2I （含 system_prompt.txt）
- S5 https://huggingface.co/Qwen/Qwen-Image-2.1-PE-I2I （含 system_prompt.txt）
- S6 https://github.com/QwenLM/Qwen-Image-2.1/tree/main/prompt_rewrite （README、data/edit_example.jsonl）
- S7 https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo/blob/main/model_index.json ，以及两个仓库的 scheduler/scheduler_config.json
- S8 https://github.com/huggingface/diffusers/blob/main/src/diffusers/pipelines/qwenimage21/pipeline_qwenimage21.py
- S9 https://alibabacloud.com/blog/qwen-image-2-1-compact-efficient-and-unified-image-creation_603586
- S10 https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1 （和 /zh/ 版）
- S11 https://huggingface.co/Comfy-Org/Qwen-Image-2.1
- S12 https://github.com/Comfy-Org/workflow_templates/tree/main/templates （image_qwen_image_2_1_*.json）
- S13 https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_qwen.py
- S14 https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/text_encoders/qwen_image21.py 、qwen3vl.py
- S15 https://github.com/Comfy-Org/ComfyUI/blob/master/comfy/supported_models.py
- S16 https://civitai.com/models/3010645
- S17 https://civitai.com/models/2986100
- S18 https://civitai.com/models/2958738
- S19 https://civitai.com/models/2989697 、https://civitai.com/models/2969143 、https://civitai.com/models/2994247 、https://civitai.com/models/3000002
- S20 https://huggingface.co/Viggle/Qwen-Image-2.1-viggle-turbo
- S21 https://huggingface.co/madebyollin/texture-fix-vae-for-qwen-image-2.1
- S22 https://huggingface.co/Qwen/Qwen-Image-2.1/discussions （#10 #11 #12 #14 #29 #56 #61）
- S23 https://huggingface.co/Comfy-Org/Qwen-Image-2.1/discussions （#4 #7 #10 #11 #14 #22）、https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo/discussions/4
- S24 https://github.com/QwenLM/Qwen-Image-2.1/issues （#5 #9 #14）
- S25 https://stablediffusion.fr/guide/qwen-image-2-1
- S26 https://github.com/kjranyone/qwen-image-2.1-prompt-guide
- S27 https://runware.ai/docs/models/alibaba-qwen-image-2-1-pro/guides/prompting
- S28 https://agihunt.info/en/p/1a15cad38191520b9f7fe0e0822
- S29 https://www.runninghub.ai/post/2101686169661693953
- S30 https://civitai.com/models/2998097
