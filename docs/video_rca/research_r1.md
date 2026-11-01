# VIDEO-RCA 研究 R1：看镜头 / 多肢 / 糊 / Pika Flex / 顿挫定格 / 双人与跨镜漂移

调研日期：2026-11-01。只做资料调研：没改代码和配置，没用 GPU，没花钱。
置信度：**高** = 官方文档、模型卡或源码明文；**中** = ≥2 个独立来源一致，或 1 个来源但有测量数据；**低** = 单帖，或我的推断（推断都标了“推断”）。
“来源数”指独立来源的个数，不是帖子数。

**已读、不重复的前序文件**：`docs/research/h3_deep/00_summary.md`、`03_comfy_community.md`、`docs/research/h3_prompt_and_fl2v.md`、`docs/ep02_iter/h3_official_conformance.md`、`docs/ep02_iter/h3_comfy_expert.md`（目录和 §0、§5）、`docs/research/quality_deep/01_h3_face_identity.md` §0、`docs/acting/PERFORMANCE_RULES.md`。
这些文件已经有的内容，本文只引用编号，不再展开：首尾帧硬钉、`FRAME_PER_TOKEN=(1,4,4,4,4)` 造成 4 帧顿挫、64 倍数分辨率顿挫（okkazoo）、turbo 慢动作、Comfy #55 红斑、#30 小脸、#78 VAE 偏色、视线要写正向落点（E1–E8）、多人每人一句（M1–M2）。

**访问限制**：Reddit 不可达（WebFetch 对 old.reddit.com 报 “unable to fetch”）；X 未尝试。社区证据来自 GitHub issue、HF 讨论区、厂商和第三方指南。

---

## 0. 结论速览

| Q | 最重要的新证据 | 置信度 |
|---|---|---|
| Q1 看镜头 | MiniMax 自家 Hailuo 指南：首帧（master image）是眼睛的 “ground truth”；要看镜头就让首帧已经看镜头，要不看镜头就用侧脸或 3/4 首帧，再用提示词把视线钉在交互点上。Qwen-Image 2.1 基模会把参考头像“贴”过去（连头部角度和视线一起），所以图1正脸参考很可能直接造出看镜头的首帧。Pika 官方示例里凡是要看镜头都会明写 “looks straight into the lens”。也就是说：成因主要是首帧，提示词里的 camera 字样是第二个开关。 | 中 |
| Q2 多肢 | PDD 和 turbo 一旦叠加跳步缓存，会出现“duplicated bodies”；Split Upscale 作者说高 denoise 加快速运动会把运动物体“切断”（broken limbs）；refine 首 σ 过高时出现双下唇。Flex 官方：精细接触约束不可靠；人体解剖是 Flex 的强项，但动作密集类不占优。 | 低-中 |
| Q3 糊 | **新发现**：我们 i2va_pdd2 第二段从 σ≈0.923 开始（planb_run.py 注释），会把放大后 latent 的大部分信号扔掉重画。社区同种子实测（535gfx）显示，refine 从 0.9035 开始时嘴部更糊、双下唇、平面闪烁，眉部表情被抹平成中性脸；从 0.6316 开始最好。上采样器本身被多人说“fuzzy”。Flex：步数加了也不会更清晰（6 步是训练好的调度）。 | 中 |
| Q4 Pika Flex | 官方支持只给首帧（`i2va`），I2VA 指令句和 H3 的一致。768×1344、175/192 帧都在官方桶里。我们的 7 值 sigma 和官方 1000/750/500/250/100/40/0 加 shift 12 的换算完全一致，lcm 等于官方的“fresh noise 重加噪”。已知问题：运镜只是建议、精细接触不可靠、“wide shot” 会变中景。**没找到**任何泛红、偏色报告。 | 高（参数）/ 未找到（泛红） |
| Q5 顿挫定格 | Flex 和 PDD 的 4 帧一顿没有专门的社区报告（**未找到**）。补到的证据：WanGP #2279 的作者说 turbo 开不开都一样顿，所以分辨率是独立变量；AddGuide 钉首帧时前约 5 帧闪烁，原版 20 步、PDD、turbo 都有（1 人）。 | 低 |
| Q6 双人与跨镜 | 社区 H3 指南：同框的非说话人要写 “listening and reacting physically”，每次同框都要复述各自的服装和外貌锚点，并写明各自的站位。refine 的 σ 太高会把表情洗成中性（同 Q3）。 | 低-中 |

---

## Q1 看镜头 / 开头定格

| 结论 | 原文引用 | 链接 | 置信度 | 来源数 | 对我们的含义 |
|---|---|---|---|---|---|
| 1. 图生视频的视线主要由首帧决定。MiniMax（H3 的出品方）自家 Hailuo 指南：要看镜头就让首帧已经看镜头；要不看镜头，首帧就用侧脸，再用提示词把视线固定在交互点上，防止“飘向镜头” | “your master image should feature the subject already looking toward the camera. In the text prompt, you then "animate" that gaze with minimal movement.” / “the master image might be a profile shot. Here, the prompt should focus on "eyeline continuity," ensuring the character's gaze remains fixed on the interaction point (e.g., a laptop screen) rather than wandering toward the camera.” / “The master reference image provides the "ground truth" for the eyes.” | https://hailuoai.video/pages/knowledge/control-eye-contact-ai-video-brand-hooks | 中（厂商营销页，结论和我们的数据一致：首帧看镜头的片子 48/52 开头也看镜头） | 1（厂商）+ 我们自己的数据 | **先修首帧，再修提示词。** 视线闸门前移到首帧验收：首帧看镜头的直接重出，不送视频。这和我们 48/52 的数据吻合。 |
| 2. 用 “looking at the camera lens” 这类镜头术语反而容易出问题；视线写成“意图 / 方位 / 落点” | “A common mistake … is the use of overly specific directional language like "looking at the camera lens." Paradoxically, this can confuse generative models, occasionally leading to cross-eyed results or subjects that appear to be staring through the viewer.” 示例：“Three-quarter view, subject's gaze directed downward toward the hands.” | 同上 | 低-中 | 1 | 正向写法模板：`three-quarter view, her gaze directed down toward <物件> / toward <对手> off-screen left`。H3 正文和 Qwen 首帧提示词都**不要出现 camera / lens 加视线动词的组合**，否定句也不行，因为会把概念写进去。 |
| 3. 模型会照提示词里的“看镜头”去做。Pika 官方示例凡是要看镜头都明写了，而且写在镜头末尾或一个特定节拍 | “She looks at the camera and sighs.”（sitcom 示例）；“the rabbit looks straight into the lens”；“she lifts her eyes to the camera for a moment of eye contact”；官方 Ref2VA 示例 5：“turns toward the camera, pauses and says …” | https://huggingface.co/Pika-Labs/Pika-H3-Flex （widget 提示词）；https://pika.art/blog/pika-h3-flex-research ；https://github.com/Pika-Labs/Pika-H3-Flex/blob/main/docs/prompt-guidance.md | 中（官方示例，说明文本里的 camera 视线指令是有效开关） | 2（模型卡 + 提示词指南） | 系统 lint 加一条检查（只查词，不评内容）：H3 正文或首帧提示词里出现 `toward the camera / into the lens / at the camera / at the viewer` 就报 warn。写作方的“转向镜头”这类写法也会触发看镜头。 |
| 4. 首帧无人看镜头时，5/11 的视频仍会看镜头：除了提示词，“I2VA 正文仍引用 Picture 2”这类结构问题也会让模型自由发挥 | （本条为推断，没有外部原文） | — | 低（推断） | 0 | 先排除 conformance B3（I2VA 正文还写着 Picture 2）和提示词里的 camera 字样，再看剩下的样本。 |
| 5. **Qwen-Image 2.1 基模会把参考头像“贴”到身体上**，所以参考图的头部角度和视线容易被原样带进生成图。BFS 头像替换 LoRA 作者：不靠专门训练的“跟随姿态”通路，LoRA 就退化成直接贴参考头，“和基模不加 LoRA 时差不多” | “The early-block MLP path is what makes the LoRA copy head rotation, eye direction and expression from `<image1>`. Removing `img_mlp.gate_up` everywhere … the LoRA then stops following the source pose and degenerates into pasting the reference head onto the body, which is close to what the base model already does without any LoRA.” | https://huggingface.co/Alissonerdx/BFS-Best-Face-Swap/blob/main/docs/qwen-image-2.1.md | 中（作者有 5 组固定种子的测量；针对的正是 Qwen-Image 2.1） | 1 | 我们的图1是**正脸**脸部参考，基模倾向于把这张正脸（包括正视镜头的眼睛）贴过去。这很可能就是首帧看镜头的根源。 |
| 6. Qwen Edit 社区：脸部参考图的角度和表情会强烈影响输出 | “the angle and expression from this image strongly influence the final result.” | https://myaiforce.com/face-consistency-qwen-edit/ | 中 | 2（和第 5 条独立） | 对策 A：脸部参考换成 **3/4 侧脸、视线不对镜头** 的定妆图（同一张 AI 脸再生成一张），或者正脸和 3/4 各给一张。对策 B：提示词明确各图的分工，例如 BFS 的写法 “copy the direction of the eye, head rotation … from <image N>”。我们的写法是“图1只提供脸的身份；头部角度和视线按正文：three-quarter view, eyes toward …”。对策 C：给一张姿态骨架图（官方支持 keypoint 多图输入）来定头部朝向。 |
| 7. 参考图整张喂进去，会把发型、脸、背景、道具一起带过来；社区的做法是遮掉参考图的头部，或者只用骨架 | “If you feed the model a full pose reference photo, it may unintentionally copy: …” / “I don't want the face shape from the reference to leak into the final result.” | https://myaiforce.com/qwen-image-edit-pose-transfer/ | 中 | 2（myaiforce 两篇 + BFS） | 我们的图2本来就是去头的造型设定图，方向是对的；图3参考板里如果有正脸人物，也会泄漏朝向，要检查。 |
| 8. 开头 1 秒停顿和定格：H3 社区指南把“开头或结尾的静止凝视”列为典型 AI 痕迹，对策是用具体的身体动作填满 | “a character just stands silent and stares off-camera or smiles looks like a frozen, robotic AI glitch.” / “fill those final seconds with **concrete physical movement** … rather than a static gaze into or off camera.” | https://huggingface.co/datasets/malcolmrey/various/blob/main/h3-center/docs/MINIMAX_H3_PROMPTING_GUIDE.md （Rule 9） | 低-中 | 1 | 和 PERFORMANCE_RULES P1/P3 一致，属于补充证据。第 0 帧的动作句要放在第一个时间码之前（已有 open_motion_cue）。 |

**未找到**：H3、Wan、LTX、Kling 的 GitHub issue 或 HF 讨论里，没有专门讨论“图生视频人物盯镜头”机制的帖子；Qwen 方面也没有针对“正脸参考导致输出看镜头”的 issue。Reddit 不可达。

---

## Q2 多手 / 多肢 / 手指坏

| 结论 | 原文引用 | 链接 | 置信度 | 来源数 | 对我们的含义 |
|---|---|---|---|---|---|
| 1. PDD 或 turbo 再叠加跳步（step skipping、缓存），会出现重复身体 | 用户：“My results are weird,duplicated bodies.” 回复：“If you use a step skipping option while also using a turbo lora or when using pdd you can get the sort of issues you mentioned” | https://github.com/deepbeepmeep/WanGP/issues/2239 | 低 | 2 人（WanGP） | 核对 gpu3 上 pdd2 和 Flex 的图里没有任何 EasyCache、TeaCache、Spectrum、step-skip（前序文件已要求关掉，这里补上“和 PDD 叠加也会多身”的证据）。同一帖里 2 人认为 PDD 比 6 步 turbo 质量更好。 |
| 2. 两段式或分块重采样在高 denoise 加快速运动时会把运动物体“切断” | “under high denoise + fast motion, moving objects are no longer sliced ("broken limbs")”（Split Upscale 新版声称修复了旧版的这个问题） | https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler （README 2026-08-28） | 低-中（作者自述） | 1 | pdd2 的第二段如果 σ 起点高、动作快，多肢风险更大。见 Q3 第 1 条的 σ 实验。 |
| 3. refine 首 σ 过高会在快速表情里造出双重结构（双下唇），并带来平面闪烁 | “We had blamed the refine for a doubled lower lip on a fast smile … Both turned out to be the first sigma.” | https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler/issues/28#issuecomment-5601709403 | 中（1 人，同种子三档测量） | 1 | 双下唇和多手指是同一类“结构重画了两遍”的失败。pdd2 第二段的 σ 起点是首要怀疑对象。 |
| 4. 少步 LoRA 下手部糊，快速运动时更糊 | “This lora messes the hands, they become blurry.” / “"blurs" hands for me as well” / “All other versions seems blurry specially when there's a fast motion in the scene.” | https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/33 | 中 | 3 人 | 手部特写镜头避免快速手部动作，写成单一、连续的手部动作（Flex 指南：一拍一个主动作）。 |
| 5. 4 步 FL2V turbo 加在 Ref2VA 上，打斗镜头严重变形；对白镜头正常 | “fight‑scene outputs suffer from severe artifacts, body distortion and blurring.” | https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/13 | 低 | 1 | 运动幅度大是多肢的放大器，和前序文件“turbo 把两个姿态叠进一个 latent”的结论一致。 |
| 6. Pika Flex 官方：精细接触约束不可靠；人体解剖在人类评测里领先，但“动作密集”类不占优 | “Fine contact constraints are unreliable. A hand that should stop a few centimetres away usually makes contact, so keep the beat working even if it does.” / 博客：“Pika H3 Flex leads on human anatomy, complex composition, and audio synchronization … Other systems remain preferred in physics, multi-scene narrative, lighting and materials, and action-heavy or control-video reference tasks.” | https://docs.comfy.org/tutorials/video/pika/pika-h3-flex ；https://pika.art/blog/pika-h3-flex-research | 高（官方） | 2 | 剧本里“手停在离脸几厘米处”这类精细接触不要指望能做到。动作密集的镜头 Flex 不是优选，可以考虑基模多步。 |
| 7. 景别与小手：H3 小脸、小手在远景会崩（前序文件 ≥6 人）；Flex 还会把 “wide shot” 画成中景 | “"Wide shot" alone tends to render as a medium shot; saying the subject is small inside a large empty room holds the wide framing better.” | https://docs.comfy.org/tutorials/video/pika/pika-h3-flex | 高（官方） | 1 | 我们如果走 Flex，剧本写的“全景”可能变成中景，手反而会变大。要真远景就用内容描述。 |

**未找到**：H3 在 4/6/8 步、LCM、PDD、DMD 下多肢发生率的量化对比；分辨率和多肢关系的直接测量（只有“小脸崩”的间接证据）。

---

## Q3 糊 / 软 / 越往后越糊

| 结论 | 原文引用 | 链接 | 置信度 | 来源数 | 对我们的含义 |
|---|---|---|---|---|---|
| 1. **两段式 refine 的首 σ 决定清晰度和表演。** 同种子实测：refine 从 0.9035 开始（t=0.44，扔掉约 90% 的放大信号）时，嘴部锐度最差（最差帧 0.74），平面闪烁 0.098，眉部表情被洗成中性；从 0.6316 开始时锐度 0.93、闪烁 0.056（接近原生），保留约 95% 细节；从 0.3158 开始最锐，但会漏出上采样器自己的瑕疵 | “that first step is t = 0.44, so the refine throws away 90 percent of the upscaled latent's signal at step one.” / “So for faces the useful range on our material is a first sigma around 0.63, not 0.9 and not 0.3.” / “the 0.9035 ladder also changes the acting. The brow lift and the forehead lines of the source get softened toward a neutral face” / “Nobody in this thread refines above 0.75.” | https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler/issues/28#issuecomment-5601709403 | 中（1 人，表格加视频；同帖其他人用 denoise 0.1–0.2，对应 σ 0.57–0.75） | 2（535gfx + xyzDist 的设置） | **我们的 i2va_pdd2 第二段从 σ≈0.923 开始**（`tools/lab_ep02/planb_run.py:106` `SplitSigmas step 4 # σ .923`），比实测最差的 0.9035 还高。项目方说的“糊”和“表情呆”很可能有一部分来自这里。注意：前序 expert §0-6 引用的“社区第二段起点 0.90–0.92”说法，和这条实测**冲突**，需要我们自己 A/B。PDD 是固定网格（`on_off_grid: error`），所以只能在网格上挪 split（例如 step 5/6），或者第二段改用基模 sigma。见实验 E2。 |
| 2. 学习型 latent 上采样器的直接输出偏软，必须靠第二段补细节 | “the output tends to look a bit "fuzzy", not fully sharp/clear.”（JohnAlcatraz，对 LBH 3D 上采样器）；另一款上采样器卡片：“a direct decode of its output can look softer than the original.” / “It does not make a finished render sharper” | https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler/issues/28 ；https://comfyui-wiki.com/en/news/2026-08-08-minimax-h3-latent-upscaler | 中 | 2 | 两段式的清晰度上限取决于第二段，所以第 1 条的 σ 是关键。 |
| 3. 我们的放大倍率 544×960 → 768×1344 约 1.41×，不在 LBH 上采样器的主训练倍率上（2× 占 40%，1.5/2.5/3/4× 各 10%，任意小数 10%） | 模型卡训练分布表：“2× | 40% | Dominant real-world factor” | https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler | 高（事实）/ 低（对画质的影响，推断） | 1 | 可以试 pass1 = 384×672（2×）或 512×896（1.5×）。另有 1 人报告（带条件缩放时）“A 1.6x downscale looks way better than 2x”（#41 m8rr），方向不一致，需实测。 |
| 4. 旧版上采样器的时间分块会造成**片尾**亮度和颜色闪烁，已修；仍然开着 temporal chunking 时要确认节点版本 ≥ 2026-08-23 | “I seem to always get significant brightness/color flickering towards the end of the video.” 作者：“the temporal chunking logic wasn't handled properly … I've already addressed this in the latest update.” | https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler/issues/26 | 中（报告者确认修复） | 2 | 这是唯一找到的“越往后越不对”的具体机制。我们 `temporal_chunking: true`，要核对 gpu3 上节点的 commit 日期。 |
| 5. 两段式在 FL2VA/I2VA 下，关键帧条件必须按高分辨率重新编码，不能直接用低分辨率条件（会报错或画质很差） | “The video latent was enlarged but the keyframe condition was not.”（#41）；“using the add guide twice is better”（m8rr）；#29：低分辨率条件配放大后的 latent 会崩 | https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler/issues/41 ；/issues/29 | 高（源码分析） | 2 | 我们 planb_run 用了两个 `MiniMaxH3ImageToVideo`（544×960 和 768×1344 各编码一次首帧），**做法正确**，不是糊的原因。 |
| 6. Pika Flex：6 步是训练好的调度，加步数不会更清晰；sigma 少于 7 个值会坏；不要叠 turbo 或 Lightning | “Six steps is the trained schedule, so raising the step count does not add detail, and lowering the sigma list below seven values breaks the schedule.” / “do not stack a turbo or Lightning LoRA on top” | https://docs.comfy.org/tutorials/video/pika/pika-h3-flex | 高 | 1（官方） | Flex 的糊没法靠加步数解决。官方的更高清路线是 Pika API 的单步像素上采样器（“We will opensource the upsampler model.”，尚未开源）。 |
| 7. Flex 的强化目标里有“清晰度” | “ReFL targets aesthetic quality and visual clarity through differentiable reward feedback” | https://pika.art/blog/pika-h3-flex-research | 高（官方说法） | 1 | 理论上 Flex 应该比 PDD 两段式更清楚。如果实测更糊，先查 LoRA 有没有真的加载（key 数）和 sigma 表是否对。 |
| 8. 少步 LoRA 在快速运动时丢细节 | “fast motion details like hair flowing in the wind lacks details” | https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/33 | 中 | 3 人 | 动作快的镜头要预期会糊，近景脸部镜头少写大幅动作。 |

**未找到**：H3 原片（非续接）“越往后越糊”的专门报告；Pika Flex 清晰度的社区反馈（发布仅几天，HF 讨论区只有 3 帖，与清晰度无关）。

---

## Q4 Pika H3 Flex 官方说明

| 结论 | 原文引用 | 链接 | 置信度 | 来源数 | 对我们的含义 |
|---|---|---|---|---|---|
| 1. **支持只给首帧**（FL2VA adapter 的 `i2va` 任务），也支持只给尾帧（`l2va`） | “First-frame conditioning | Prompt and one opening frame | FL2VA / `i2va`” | https://huggingface.co/Pika-Labs/Pika-H3-Flex | 高 | 2（模型卡 + GitHub README） | 只给首帧是官方用法，不是误用。（ComfyUI 文档页只列了 T2V、Ref2VA、FL2VA 三个模板，没写 i2v。） |
| 2. I2VA 提示词指令句和 H3 官方一致；正文写 “Begin from <Picture 1>.” | “For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.” / “[Shot 1] Begin from <Picture 1>. ...” / “Use the first image as the video's opening state and develop the action forward from it.” | https://github.com/Pika-Labs/Pika-H3-Flex/blob/main/docs/prompt-guidance.md | 高 | 1 | 和 conformance F1 一样：I2VA 正文不能再引用 Picture 2。官方 FL2VA 写法是 “Begin aligned with <Picture 1>. … End aligned with <Picture 2>.” |
| 3. 场景描述用英文；台词和画面文字保持原语言 | “Write scene descriptions in English; keep dialogue and on-screen text in their intended language.” | 同上 | 高 | 1 | 与 H3 一致，已在用。 |
| 4. 分辨率和帧数：768×1344 是官方 9:16 的 768p 桶；帧网格 17n+5，**175 和 192 都在官方帧表里**；时长 5–15 s | buckets.yaml：`[768, 1344]  # 9:16`；`frames: [56, 73, 90, 107, 124, 141, 158, 175, 192, …, 362]` | https://github.com/Pika-Labs/Pika-H3-Flex/blob/main/src/pika_h3/core/buckets.yaml | 高（源码） | 1 | 参数合规。官方实测矩阵只有 768p 的 5 s，没有 7–8 s 的竖屏测试（“Coverage does not establish support for every input combination”）。 |
| 5. **采样：我们的 sigma 表和 lcm 与官方等价。** 官方 knots 1000/750/500/250/100/40/0，video shift 12、audio shift 3，每步“fresh intermediate noise” | “Both adapters use six denoising forwards with knots 1000/750/500/250/100/40/0, video shift12 and audio shift3, with fresh intermediate noise. Generic six-step Euler sampling is not equivalent.” | https://github.com/Pika-Labs/Pika-H3-Flex （README）；sampling.py：“Six-step consistency re-noising with fresh noise and terminal clean prediction.” | 高 | 2 | 按 shift 12 换算：t=0.75→0.97297，0.5→0.92308，0.25→0.8，0.1→0.57143，0.04→0.33333，和我们的 ManualSigmas 逐位一致。ComfyUI 的 lcm 就是“预测 x0 再重加噪”。**不要换成 euler。** HF #1 Pika 员工也确认是 12/3。 |
| 6. 强度 1.0，不叠加速 LoRA | “Keep the sigma list and the adapter strength at 1.0, and do not stack a turbo or Lightning LoRA on top” | https://docs.comfy.org/tutorials/video/pika/pika-h3-flex | 高 | 1 | 已合规。 |
| 7. 已知问题（官方）：运镜幅度只是建议，时间可能偏 0.2–0.3 s 甚至方向反；“wide shot” 变中景；精细接触不可靠 | “Camera amplitude is advisory. … Explicit degrees and cut timestamps can land 0.2 to 0.3 seconds off, or in the opposite direction.” | 同上 | 高 | 1 | 镜内时间码 `At 00:02.000` 也可能有 0.2–0.3 s 误差，验收时要放宽。 |
| 8. 官方承认的弱项：物理、多场景一致性、复杂参考控制 | “Physics, multi-scene consistency, and complex reference control remain areas for further improvement.” | https://pika.art/blog/pika-h3-flex-research | 高 | 1 | 跨镜一致性不能指望 Flex 解决，要靠首帧和参考图。 |
| 9. 泛红、颜色漂移、动作幅度：**官方和社区都未找到报告**。官方只说训练数据按美学筛选，并做了美学与清晰度的奖励优化 | “an internally curated dataset selected for aesthetic quality”；“ReFL targets aesthetic quality and visual clarity” | https://pika.art/blog/pika-h3-flex-research | 未找到（泛红）/ 低（推断：美学奖励可能偏向更暖、更饱和的肤色，这只是推断，没有出处） | 0 | 我们自测 Pika a*p95 43.9/43.2（LEARNED_SPECS B）仍是唯一证据。保持 flush_risk overlay。 |
| 10. 官方展示提示词大量使用大写否定（“NO slow motion”“never frozen”“SPEED IS CRITICAL …”），而官方提示词指南本身没有提倡否定写法 | “SPEED IS CRITICAL: everything moves at normal real-time speed, like 24fps footage played back at 24fps - natural motion, NO slow motion.” | https://huggingface.co/Pika-Labs/Pika-H3-Flex （widget） | 低（这些是服务端展示，卡片写明 “Exact reproduction with the released package is not guaranteed”，服务端可能还有 prompt enhancement） | 1 | 不改我们“禁止否定句”的规则。可以把“正常实时速度”的正向句（“everything moves at normal real-time speed, like 24fps footage played back at 24fps”）作为系统固定句做一次 A/B（实验 E5）。 |
| 11. 官方 AdaLN 在 FP32 下激活；diffusers 原注释说低精度舍入会“在整个去噪轨迹上一致地累积”成偏差 | “a rounding applied before the activation biases every block's modulation parameters identically at every sampling step, which accumulates coherently over the denoising trajectory.” | https://github.com/Pika-Labs/Pika-H3-Flex/blob/main/patches/0001-h3-adaln-fp32.patch | 高（事实）/ 低（与 ComfyUI int8 色调偏差是否有关：推断） | 1 | 仅作线索：ComfyUI 侧 AdaLN 的精度路径没有核实。 |

---

## Q5 4 帧一顿 / 脚重影 / 结尾定住 / 开头定格

| 结论 | 原文引用 | 链接 | 置信度 | 来源数 | 对我们的含义 |
|---|---|---|---|---|---|
| 1. 分辨率造成的周期顿挫和 turbo 无关（对前序 okkazoo 证据的补充）：同一作者说开不开 turbo 都一样 | “using turbo, or not, doesn't seem to have any impact on this. The stutter is the same with and without.”（每 24 帧一跳；宽高都是 64 的倍数时出现） | https://github.com/deepbeepmeep/WanGP/issues/2279 | 低-中 | 1 | 768×1344 两边都是 64 的倍数。736×1312 这个 A/B 和步数、LoRA 是独立变量，Flex 和 PDD 都要测（Flex 官方桶只有 768×1344，换尺寸属于桶外用法）。 |
| 2. AddGuide 钉首帧时，前约 5 帧局部亮度和颜色快速闪烁，原版 20 步、PDD 8 步、ref2v turbo 8 步都会出现 | “生成视频前几帧会发生轻微闪烁 … 都会发生类似前面5帧快速轻微闪烁一下” | https://github.com/flywhale-666/ComfyUI-H3-upgrade-kit/issues/3 | 低 | 1 | 第一个 latent 只管 1 帧，后面每个管 4 帧（前序文件），前 5 帧正好是第 1 个 latent 加第 2 个 latent。开头那“1 秒多的定格”，以及开头的闪烁，都可以在剪辑时裁掉前 5 帧作为兜底（属于后期，不是修复）。 |
| 3. 少步时，refine 首 σ 过高会带来平面闪烁 | 见 Q3-1 表：0.9035 档闪烁 0.098，原生 0.061 | https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler/issues/28#issuecomment-5601709403 | 中 | 1 | pdd2 第二段的闪烁和“不连贯”可能也和这有关。 |
| 4. 动作慢、飘、定住：提示词不具体时 H3 会默认慢动作；ref2va turbo 更僵；写有力度的动词有帮助 | “Minimax is know to put videos in super slow motion if you aren't descriptive.” / “ref2va turbo loras does make things a bit rigid.” / “prompting for fast motion helps a lot.” | https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/58 | 中 | 3 人 | 前序文件已有，这里补上原帖。 |
| 5. FL2VA 里尾帧会让对应元素保持静止；如果尾帧不是必须的，建议改成只给首帧 | “avoid describing them as a preserved/static subject.” 以及建议测试只给首帧 | https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/81 | 低 | 1 | 和前序“结尾冻结 = 尾帧硬钉”一致。Flex recipe 现在是“有定稿尾帧就送”（`last_frame_mode: use`），结尾定住的风险会回来，要单独统计。 |
| 6. Flex 和 PDD 下的 4 帧一顿、脚重影、开头定格 | — | — | **未找到** | 0 | 只能靠我们自己测 J4（dejudder 指标），见实验 E4。 |

---

## Q6 双人镜第二人呆滞 / 跨镜服装发色漂移

| 结论 | 原文引用 | 链接 | 置信度 | 来源数 | 对我们的含义 |
|---|---|---|---|---|---|
| 1. 同框非说话人必须写静默和反应，并写明站位 | “Every non-speaking subject still in frame must carry an explicit silence mandate (e.g. `<Subject 2> remains completely silent with his mouth closed, speaking no dialogue, while listening and reacting physically`)” / “Explicitly describe each subject's position relative to the frame and to each other” | https://huggingface.co/datasets/malcolmrey/various/blob/main/h3-center/docs/MINIMAX_H3_PROMPTING_GUIDE.md （Rule 16） | 低-中（社区长期实践指南，单一来源） | 1 | 和 PERFORMANCE_RULES M1/M2 一致。补充两点：站位要写明（left of frame / three feet to his right）；非说话人的反应要写成可见动作，并带视线落点。 |
| 2. 同框人数：2 人最好，3 人要错开纵深，超过 3 人融合风险急剧上升 | “Prefer 2 subjects sharing a frame. 3 is usable with clearly staggered depth/positioning. Avoid more than 3 characters visible simultaneously” | 同上 | 低-中 | 1（与 H3 官方 shot-table-spec “不超过 3 个重要角色”一致，共 2） | 已有 RL-D7。 |
| 3. 跨镜服装、发型、肤色漂移：每个镜头都完整复述外貌和服装锚点，包括族裔、发型、发色 | “MiniMax-H3 can subtly alter character hair, skin tone, ethnicity, or costume colors between shots if the prompt relies on generic terms” / “Always explicitly restate complete physical descriptors in every shot description.” | 同上（Rule 17） | 低-中 | 1（与 conformance B10/B18 的结论同向） | 锚点句由人物表 EN 短语确定性生成，逐字复用（已在 conformance F 系列里）。 |
| 4. 表情被洗成中性：两段式 refine 首 σ 过高会抹平眉部和额纹的表演 | “The brow lift and the forehead lines of the source get softened toward a neutral face, while 0.6316 keeps most of them” | https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler/issues/28#issuecomment-5601709403 | 中 | 1 | 第二人“呆滞”除了提示词没写，pdd2 第二段的重画也可能在抹表情。实验 E2 会顺带测到。 |
| 5. 官方：把多参考、多场景一致性列为 Flex 待改进项 | 见 Q4-8 | — | 高 | 1 | 跨镜一致性主要靠首帧（Qwen 多参考）和固定锚点句。 |
| 6. H3 用 Ref2VA 写 subject 定义锁多人身份（官方六段式） | 前序 conformance R1–R9 已有 | — | 高 | — | 不重复。 |

**未找到**：H3、Kling、Veo、Wan 里“双人镜第二人表情呆滞”的专门 issue 或测量。

---

## 建议的控制变量实验（交 LAB；固定种子、固定首帧、固定提示词，每次只动一个变量）

每组至少 3 个镜头：近景单人有表情、双人对话中景、手部动作镜。指标用现有的：视线检测 G1（首帧、第 0–1 s、全程）、J4 顿挫、首秒定格、嘴和眉的 Laplacian 锐度、平面闪烁、cheek a* 漂移、多肢人工标注。

| # | 要验证的假设 | 组别（只变一个量） | 预期 / 判定 |
|---|---|---|---|
| E1 | 看镜头主要来自 Qwen 首帧的正脸参考（Q1-5/6） | A 现状（图1正脸）；B 图1换成同一张 AI 脸的 3/4 侧脸、视线不对镜头；C 正脸和 3/4 各给一张，提示词写“头部角度和视线按正文”；D 现状加一张姿态骨架图 | 统计首帧看镜头比例。B、C 明显下降 → 把首帧视线闸门和 3/4 参考固化成规则 |
| E1b | 提示词里的 camera 字样会触发看镜头（Q1-3） | 同一首帧（不看镜头）：A 原提示词；B 删掉所有 camera / lens / viewer 加视线的写法，换成具体落点 | 对照 5/11 那批片子，看 B 是否降到接近 0 |
| E2 | **pdd2 第二段从 σ 0.923 开始导致糊、双结构、表情变平**（Q3-1） | A split_step 4（σ≈0.923，现状）；B split_step 5；C split_step 6（都在 PDD 网格上，先从 `MiniMaxH3PDDAccApply` 的 sigma 输出读出实际值）；D 第二段改用基模 BasicScheduler、首 σ≈0.63、3 步（离开 PDD 网格，作为对照） | 比较嘴部锐度、闪烁、眉部表情、多肢。B、C、D 优于 A → 改 recipe 的 split |
| E3 | 放大倍率不在训练主分布（Q3-3） | pass1 544×960（1.41×）/ 512×896（1.5×）/ 384×672（2×） | 看第二段之后的清晰度和耗时 |
| E4 | Flex 和 PDD 的顿挫有一部分来自 64 倍数分辨率（Q5-1） | 768×1344 对 736×1312，分别在 Flex 和 pdd2 上测 | J4 下降 → 记入 K-REN（Flex 换尺寸是桶外用法，要另看画质） |
| E5 | Flex 慢动作和定格可以用正向“实时速度”句缓解（Q4-10） | A 现状；B 系统在第一个时间码前加 “everything moves at normal real-time speed, like 24fps footage played back at 24fps” | 看首秒定格和动作速度 |
| E6 | Flex 下尾帧导致结尾定住（Q5-5） | 同镜头：Flex 只给首帧 / 首尾帧都给 | 统计结尾定住的秒数 |
| E7 | 上采样节点版本（Q3-4） | 核对 gpu3 上 LBH 节点的 commit 日期 ≥ 2026-08-23；关掉 temporal chunking 跑一次对照 | 片尾闪烁是否消失 |

---

## 来源清单（本文新增）

- Pika 官方：HF 模型卡 https://huggingface.co/Pika-Labs/Pika-H3-Flex ；HF 讨论 #1 https://huggingface.co/Pika-Labs/Pika-H3-Flex/discussions/1 ；GitHub https://github.com/Pika-Labs/Pika-H3-Flex （README、docs/prompt-guidance.md、docs/hardware.md、src/pika_h3/core/buckets.yaml、sampling.py、patches/0001-h3-adaln-fp32.patch、examples/prompts/i2va.txt）；技术博客 https://pika.art/blog/pika-h3-flex-research
- ComfyUI：https://docs.comfy.org/tutorials/video/pika/pika-h3-flex ；模板 https://github.com/Comfy-Org/workflow_templates/blob/main/templates/video_pika_h3_flex_fl2va.json （lcm、ManualSigmas `1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0`、LoRA 1.0、模板时长 5 s）；Comfy-Org HF 讨论 #71
- 上采样器：https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler ；https://github.com/LBH-123-AI/Comfyui_Minimax_h3_latent_Upscaler （README、issues #25 #26 #28 #29 #41 #64）；https://github.com/Tr1dae/ComfyUI-MiniMaxH3_LatentUpscaler ；https://comfyui-wiki.com/en/news/2026-08-08-minimax-h3-latent-upscaler
- PDD 和 turbo：https://huggingface.co/alibaba-pai/MiniMax-H3-Acc-LoRAs ；https://github.com/deepbeepmeep/WanGP/issues/2239 ；https://github.com/deepbeepmeep/WanGP/issues/2279 ；lightx2v HF 讨论 #13 #33 #46 #58；MiniMaxAI HF 讨论 #81；https://github.com/flywhale-666/ComfyUI-H3-upgrade-kit/issues/3
- 视线与首帧：https://hailuoai.video/pages/knowledge/control-eye-contact-ai-video-brand-hooks ；https://huggingface.co/Alissonerdx/BFS-Best-Face-Swap/blob/main/docs/qwen-image-2.1.md ；https://myaiforce.com/face-consistency-qwen-edit/ ；https://myaiforce.com/qwen-image-edit-pose-transfer/ ；https://myaiforce.com/head-swapping-with-qwen-image-2-1/
- 社区 H3 写法：https://huggingface.co/datasets/malcolmrey/various/blob/main/h3-center/docs/MINIMAX_H3_PROMPTING_GUIDE.md
- 不可达：Reddit（old.reddit.com 无法抓取）。
