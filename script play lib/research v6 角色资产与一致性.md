# NS-Final Studio · 调研 v6：角色资产与一致性（B1 B2 A2 A4 C1 C3 E5 E6）

> 日期：2026-10-30。v3 列了 LoRA，v5 讲了训练 LoRA 和 FL2VA 锁首帧；这些本篇不再重复。本篇回答三件事：角色资产怎么做、资产怎么驱动出图、首尾帧和色调怎么做。
> 均未实测。⚠ = 单一来源、二手来源或推断。

## 0. 结论

1. **“照搬姿势、服装、背景”的根因：喂进去的参考图本身就是成品照。** Qwen 2.1 的编辑把参考图当作内容来源，图里有什么，模型就倾向画什么。
   - 官方文档：`image_1` 是编辑对象，其余参考图提供内容。
   - 解决办法：不改参数，改参考图。把林晚做成**中性身份底片**：灰底、素衣、无饰品、中性表情、手不碰脸。姿势、服装、背景都交给剧本文本和单独的单品参考图。
2. **资产要分两层：**
   - 身份层：脸 / 角度 / 发型，跨集不变。
   - 造型层：Look A/B/C 的上身全身照，以及衣、鞋、甲单品图。
   - 每镜按景别和文本**自动挑 1–4 张**参考图，不再“一张定妆图打天下”。
3. **多角度这样出：**
   - 首选：Qwen 2.1 **Base**（不能用 Turbo）+ Character Sheet LoRA，一张站姿照出 3×2 灰底设定图。
   - 兜底：Klein 4B 用句式提示词逐个视角编辑，配合旧系统的 `angle_guard` 查“没转过去”和“方向反了”。
   - AnyAngle 需要先有 3D 重建渲染图作为输入，不适合本项目。Multiple-Angles LoRA 是用物体训练的，人脸效果不明 ⚠。
4. **尾帧：用定稿首帧做编辑（Base 25 步）。**
   - 小幅变化：加 Consistency LoRA，构图像素级不动。
   - 大动作：不加 LoRA，另附脸部底片补身份。
   - 运镜较大的镜头不做尾帧。
5. **色调（A4）：** 不要把林晚定妆图当风格参考图（会把人带进去）。改为对首帧和尾帧做确定性颜色迁移（KJNodes ColorMatch，`hm-mvgd-hm` / `mkl`），再给成片套同一套 3D LUT。
6. **Leica 锐度（A2）：** 提示词写光学特征（焦平面锐利、微反差、f/1.4 焦外），不要写质量形容词。真正的锐度在超分之后用 CAS / unsharp 做，颗粒最后加。

## 1. 平台怎么做角色资产

| 平台 | 资产结构 | 怎么回喂到镜头 |
|---|---|---|
| 小云雀 | 角色节点下挂子形象（不同妆造），工具有“角色三视图 / 光影控制 / 镜头控制”。视角规格未公开 ⚠ | 故事板里用 `@角色` 自动调用；节点图作为参考图；上一镜尾帧可作为下一镜参考 |
| 可灵 主体库 3.0 | 每个主体 2–4 张：1 张主图（建议正面）+ 1–3 张“不同角度或细节”；也可用 3–8 秒多角度视频建主体 | `@主体`；Video 3.0 首帧或首尾帧最多绑 3 个主体，且主体须出现在帧里 |
| LTX Studio Elements | 正面、均匀柔光、中性正面肖像、简单服装 | 先用 Element 出图，再图生视频 |
| Higgsfield Soul ID | 训练式：20–80 张，多角度、多表情，至少 1 张全身，≥960px | 以 ID 方式调用（训练 LoRA 路线，对应 v5） |
| 通用设定表 ⚠ | 正面肖像、3/4、侧面、全身、表情表；用独特发型或配饰做身份锚点 | 参考图 + 固定文字描述 |

**共识：**
- 主参考图一律是**干净的正面图**。
- 辅助图只补角度和细节，总数 2–4 张。
- 造型（子形象）挂在角色下面单独管理。
- 镜头生成时按需引用，而不是把所有图都塞进去。

## 2. Qwen Image 2.1 在 ComfyUI 中的事实

- **节点：** `TextEncodeQwenImage21`，输入 `images.image_1 … image_16`，官方编辑模板只接了 10 个。提示词里用 `<image1>` `<image2>` 引用参考图。
- **`resolution` 参数：**
  - 设为 0：每张参考图保持原像素（取 32 的倍数）。
  - 大于 0：`image_1` 缩放到约 resolution² 像素。
  - 未开 `custom_size` 时，输出尺寸跟随 `image_1`。
- **耗时：** 画布越大越慢，多参考图会增加 token 和单步耗时（双参考时每步约 17 s → 19 s）。
- **Base / Turbo：**
  - Base：25 步、CFG 1、euler/simple。
  - Turbo：8 步固定 `ManualSigmas`，不能加步数。
  - CFG 1 时负面提示词无效。
- **我们的关键帧模板**（旧系统 `keyframe_qwen_image_2_1_edit_1/2/3.json`）：`EmptyLatentImage` + `TextEncodeQwenImage21(resolution 1024)`。
  - 构图并不来自参考图的 latent，照搬发生在语义层。所以中性底片是最直接的解法。
- **角色设定表 LoRA**（ladaagency，CivArchive 2995608）：
  - 输入一张站姿照（头到至少大腿中部），输出 3×2 灰底网格：脸部特写 + 正 / 背 / 侧 / 3/4 前 / 3/4 后。
  - 设置：强度 1.0、25 步、CFG 1。**只支持 Base**，Turbo 会把网格画坏。
  - 配套工作流需要 KJNodes（自动 padding），另有放大并回贴原图眼睛的流程。
  - 训练数据不含 NSFW；许可为 Qwen Research（非商用）。
- **Consistency LoRA**（ausboss，Civitai 2969143 / HF）：
  - 用法：`LoraLoaderModelOnly` 强度 1.0，`TextEncodeQwenImage21` 的 `resolution=0`，在编码器输出的 latent 上采样（换 latent 尺寸会导致缩放）。设置为 25 步、CFG 1、euler/simple，输出接 VAE Decode → Split Image with Alpha。
  - 效果：重绘时角落偏移从 24 px 降到 1.6 px。
  - **限制：** 不适合转头、换姿势这类“需要移动”的编辑；8 步 Turbo 未测。
  - v3 写的“测过 8 步 Turbo”需更正。
- **Multiple-Angles LoRA**（akhaliq，2.1 版）：
  - 用法：`<mva> {方位}, {俯仰}[, close-up]`，共 72 种机位，强度 0.8–1.0。
  - 训练集是渲染的物体，没有人像数据 ⚠。
- **AnyAngle**（lilylilith）：
  - 触发词 `Change the camera angle from <image2> to <image1>`，其中一张是 3D 重建（高斯泼溅或网格）的新视角渲染图。
  - 需要 3D 流程，暂不采用。
- **角色化提示词（商用指南）：**
  - 句首先声明每张图的角色，例如“Figure 1: Outfit, Figure 2: Adult model …”，顺序固定。
  - 再写“Preserve the facial identity, hairstyle, skin tone… of Figure 2”。
  - 再写 “Do not add or change: …”。
- **参考图数量与画质：**
  - 官方没有给出数量与画质的关系。
  - 社区报告：在 Qwen-Edit-2511 上用 3 张参考，部分人物组合出现串脸和纹理崩坏，单参考始终干净 ⚠。
  - 建议：每次只放 1 张身份参考，总数 ≤4。

## 3. FLUX.2 Klein 4B

- **文件：** `flux-2-klein-4b-fp8.safetensors`（蒸馏版）/ `flux-2-klein-base-4b-fp8`，文本编码器 `qwen_3_4b`，VAE `flux2-vae`。
- **显存：** 官方实测蒸馏版约 8.4 GB、Base 约 9.2 GB（5090 上测得），12 GB 卡可跑。
- **官方编辑模板：** 只有 2 个 `LoadImage`，参考图经 `ReferenceLatent` 串联注入。
- **参考图数量：** 4B 的上限没有官方数字。社区说法从“≤3”到“底图 + 3 张参考”不等 ⚠。按 **≤3 张**用。
- **提示词：**
  - 写法示例：“The subject from image 1 wearing the jacket from image 2, in the environment of image 3”。
  - 单属性编辑最稳。
  - 先写需要保持的内容，例如 “Keep the woman's pose unchanged”。
- **旧系统实测（2026-10-17 / 20）：**
  - Klein 用句式提示词能正确出脸部特写。
  - Qwen 8 步 Turbo 编辑会照抄参考图的姿势和角度，所以写了 `angle_guard` 去拦截。

## 4. 推荐的角色资产流水线（林晚；男主同法）

### 4.1 资产清单（每张图都登记血缘、seed、sha256）

| ID | 内容 | 规格 | 制作方法 |
|---|---|---|---|
| **LW-ID-F** 正脸底片 | 头肩、正面、中性表情、刘海和冰蓝直发自然垂下，素色灰 T，无饰品，手不入画 | 1024×1024，#808080 无缝灰底，柔光均匀 | ① 从 assets/linwan 选最清晰的正脸，Base 编辑 + Consistency LoRA：“背景换成纯灰，衣服换成素灰 T 恤，去掉项链和花”；② 不加 LoRA：“手从脸上移开，头摆正，平视镜头” |
| LW-ID-34L / 34R | 3/4 侧脸，左右各一张（方向按“脸朝画面左 / 右”命名，沿用旧系统 S14/S20 的教训） | 同上 | 由全身底片出设定表后裁出；或 Klein 句式编辑 |
| LW-ID-P | 正侧面 | 同上 | 同上；**不要镜像翻转**（刘海和发缝不对称） |
| LW-ID-B | 后脑和发长（及腰） | 768×1344 | 设定表的背面格 |
| **LW-BODY-F/S/B** 身体底片 | 全身正 / 侧 / 背，贴身素色基础款（灰色连体衣）、赤脚或中性平底，站姿 | 768×1344 灰底 | 用 LW-ID-F 编辑出正面全身 → Character Sheet LoRA（Base）出 3×2 → 裁格，再用 Base 放大 |
| LW-EXP-×6 | 平静 / 微笑 / 哭 / 怒 / 惊 / 媚眼 | 768×768 头肩灰底 | 用 LW-ID-F 编辑，只改表情（加 Consistency LoRA） |
| LW-MU-素颜 / 浓妆 | 妆面变体（对应 REF-LW-01/02） | 同正脸底片 | 用 LW-ID-F 编辑，只改妆面（加 Consistency LoRA） |
| **Look A/B/C 上身照** | 穿好全套造型的全身正 / 背 / 3/4 | 768×1344 灰底 | Qwen Base 多参考：`<image1>` 身体底片 + `<image2>` 服装 + `<image3>` 鞋 |
| 单品：服装 | 平铺图或隐形人台图，**不要有人穿** | ≤768 长边，白底或浅灰底 | 抠图或网店图（assets/clothes） |
| 单品：鞋 | 侧面 45° 产品图 | 512–768，白底 | assets/high heels 现成图 |
| 单品：美甲 | 手背特写，五指自然张开，中性肤色背景 | 768×768 | Qwen 编辑或实拍贴图 |
| 单品：发型 | 发型变体就做成 ID-F / ID-B 的变体 | 同底片 | 编辑，只改发型 |

**质检门（只保留这一道人工门）：**
- 每张资产对 LW-ID-F 算 ArcFace，阈值按金标集校准（v5 约 0.8 ⚠）。
- 角度图过 `angle_guard`（SSIM 判“没转过去”，关键点判方向）。
- 人工锁定后不可覆盖，只能出新版本。
- 合格资产（约 30 张）同时作为 v5 林晚 LoRA 的训练集。

**男主（顾沉、陈宇、Alex 等）：**
- 没有项目方原图。先用文生图出 3 张正面全身候选，由人选 1 张，再走同样的流程。
- 外貌差异要拉大（发型、肤色、脸型），以降低多人同框时串脸的风险。

### 4.2 每镜怎么选参考图（确定性规则，写进镜头绑定清单）

1. **脸部底片每镜必带，且只带 1 张。** 按镜头的机位或朝向选 F / 34L / 34R / P；背影镜头改用 ID-B。按当集妆面选素颜或浓妆版。**禁止**再用原定妆图（file_…92c081…png）。
2. **按景别加图：**
   - 特写、近景：只用脸部底片，表情靠文字。
   - 中景：加当集 Look 的上身照（按角度选正 / 背）。
   - 全景、全身：加 Look 全身照。
3. **单品按需加：**
   - 鞋：只在镜头文本出现脚、鞋、全身、走路，且脚在画内时才加。
   - 美甲：只在手部特写、近景且手有动作时才加。
   - 服装单品：只在 Look 上身照里看不清该件时才加。
4. **上限：** Qwen 最多 4 张，Klein 最多 3 张。双人镜头每人 1 张脸部底片，加 ≤1 张造型图。超出上限按“脸 > Look > 鞋 > 甲”的优先级截断。
5. **提示词骨架**（C1 拼装公式的垫图段改写成这样，DNA 锁、场景锁、装饰锁、分镜内容照旧透传）：

```
<image1>只提供林晚的脸部身份：五官、浅冰蓝及腰直发、齐刘海、冷白皮、妆容；
不要沿用<image1>的姿势、表情、服装、背景、构图和光线。
<image2>只提供服装款式与材质；<image3>只提供鞋子款式。
画面内容完全按以下分镜描述：……
```

   - `<image1>` 与 “图1 / Figure 1” 两种写法哪个更有效未验证 ⚠，见 §7 的 A/B 测试。
6. **参考图分辨率：**
   - `resolution` 设为 0，自己预先缩放：脸部底片 768²，单品 512–768，Look 图 768×1344。
   - 输出用 `EmptyLatentImage` 竖屏画布。
   - “参考图越小越不主导构图”是推断 ⚠。

## 5. 首尾帧（C3）

- **哪些镜头做尾帧：** 只给结束状态明确的动作镜头做（起身、转身、伸手、走近、揭示）。对白和静态镜头只用首帧。推、拉、摇、移较大的镜头不做尾帧，或拆成两镜。
- **尾帧怎么出：**
  - `image_1` 用定稿首帧（`resolution=0`，同尺寸），用 Qwen **Base** 25 步编辑。
  - 小变化（表情、视线、手部、半步位移）：加 Consistency LoRA，在编码器 latent 上采样，背景和机位像素级不动。
  - 大动作（转身、坐下）：不加 LoRA。`<image2>` 放对应角度的脸部底片补身份，提示词写“保持<image1>的场景、机位、光线、服装不变，只把人物改为……”。
- **尾帧后处理：** 对首帧做 ColorMatch，并校验尺寸与比例一致。ArcFace 对比底片，背景区域 SSIM 要高。
- **H3 提示词：**
  - 首行写对齐句（图1 = 0.00 s，图2 = 10.00 s）。
  - 写中间路径，**不要复述两张图**；在动作句里重复关键身份细节。
  - 一镜只放一个动作，最后约 1 秒留给收势。
- **常见失败：**
  - 两帧差异无法物理到达 → 出溶解或形变。
  - 光线或白平衡跳变 → 闪烁。
  - 尾帧景别或主体比例与首帧不同 → 结尾跳一下。
- **调试顺序：** 先跑单首帧版，确认动作自然，再加尾帧。
- **相邻镜头衔接：** 上一镜的尾帧可作为下一镜首帧的候选（同场景连续动作时），这是小云雀的做法。

## 6. 色调（A4）与 Leica 质感（A2）

**色调：**
- **把定妆图当风格参考图（不推荐）：**
  - 编辑模型分不开“色调”和“人、玫瑰、项链”，非林晚镜头也会被带进粉色元素和林晚的脸 ⚠。
  - 若要试，只喂**色卡图**：从定妆图用 k-means 提取 6–8 个色块拼成无内容的色板，提示词写“<imageN>仅为色彩参考”。
- **确定性迁移（推荐）：**
  1. 首帧、尾帧出图后，过 KJNodes `ColorMatch`（color-matcher 库，方法 `mkl` / `hm-mvgd-hm` / `reinhard`），参考图就是项目方给的色调参考图（assets/style/color_reference_01.png）。效果由 strength 控制，建议 0.5–0.7，避免肤色偏粉 ⚠。
  2. H3 会延续首尾帧的颜色。
  3. 成片阶段：在一张代表性帧上拟合 `mkl` 或 `reinhard` 线性变换（线性变换可以无损烘成 LUT），套到 ffmpeg `haldclutsrc` 生成的单位 Hald 图上，导出 `.cube`。全集统一用 `lut3d` 套。直方图类方法（hm）不能精确烘成 LUT，只适合逐帧处理。
- **结论：** 确定性迁移更可靠（可复现，不会把人带进画面）。文字调色描述保留，作为第一层。

**Leica 锐度：**
- **提示词：**
  - 写光学特征，不写“8K、杰作、照片级真实”。旧系统实测：Qwen 2.1 写 “photorealistic” 和质量形容词会出塑料皮。
  - 可用写法：`shot on a Leica M with a Summilux 50mm at f/1.4, razor-thin focus plane, crisp micro-contrast on the eyes and lashes, creamy smooth bokeh, natural skin pores`。效果未在 Qwen 2.1 上验证 ⚠。
  - f/1.4 和“全画面锐利”互相冲突，要写成“焦平面锐、焦外柔”。
- **后期**（在 v5 超分之后）：先锐化，再套 LUT，最后加颗粒，例如 `ffmpeg -vf "cas=0.5,lut3d=ep.cube,noise=alls=4:allf=t+u"`。
  - 锐化在模型之外做，更稳定，也不会触发 H3 的“平均化”。
- **可选：** 官方文档提到社区版 texture-fix VAE，可以减少写实图的棋盘格伪影 ⚠。

## 7. A/B 测试计划（只用非成人镜头）

**测试设置：**
- 选 6 个镜头：面部特写、中景对白、全身行走、背影、手部特写（美甲）、林晚 + 顾沉双人。
- 每个变体用 2 个固定 seed。

| 变体 | 参考图组合 | 模型 |
|---|---|---|
| A（基线） | 原定妆图 | Turbo |
| B | 脸部底片 | Turbo |
| C | 脸部底片 | Base |
| D | 脸部底片 + Look 图 + 按需单品 | Base |
| E | D 的组合，提示词写法改为“图1”或“Figure 1” | Base |
| F | D 的组合，参考图预缩放 512 / 768 / 1024 | Base |
| G | 同样参考图 | Klein 4B 蒸馏 |

**指标：**
- 身份：ArcFace 余弦（对比 LW-ID-F）。
- 照搬分数：对参考图算 `angle_guard` 的 SSIM。
- 剧本遵从：VLM 检查姿势、服装、背景、鞋是否与剧本一致。
- 发色 ΔE。
- 耗时与显存峰值。

**通过线：** 身份不低于 A，照搬分数明显低于 A，剧本遵从 ≥5/6。

**附加测试：**
- 尾帧：3 个动作镜头 × 有无 Consistency LoRA，对比 ArcFace 和背景 SSIM，再跑 H3 FL2VA，人工看是否溶解或跳帧。
- 色调：纯文字 / ColorMatch strength 0.5 / ColorMatch strength 1.0 / 色卡参考，各 3 镜，由项目方盲选。

## 来源

- ComfyUI Qwen-Image 2.1 教程：https://docs.comfy.org/zh/tutorials/image/qwen/qwen-image-2-1.md
- Qwen-Image-2.1 模型卡：https://huggingface.co/Qwen/Qwen-Image-2.1
- Consistency LoRA：https://comfyui-wiki.com/en/news/2026-10-01-qwen-image-2-1-consistency-lora ｜ https://civitai.com/models/2969143
- Multiple-Angles LoRA：https://comfyui-wiki.com/en/news/2026-10-07-qwen-image-2-1-multiple-angles-lora
- AnyAngle：https://comfyui-wiki.com/news/2026-09-28-qwen-image-2-1-anyangle-lora ｜ https://civitai.com/models/2970214
- Character Sheet LoRA：https://civarchive.com/models/2995608
- 多参考工作流：https://www.runcomfy.com/comfyui-workflows/qwen-image-2-1-multi-image-editing
- 参考尺寸与漂移：https://lilting.ch/en/articles/qwen-image-2-1-edit-pixel-perfect-output-resolution
- 角色化提示词：https://www.weshop.ai/solutions/models/qwen-image-2-1-ai-image-generation-and-editing-guide
- 多参考串脸 ⚠：https://discuss.huggingface.co/t/multi-image-edit-3-refs-artifacts-at-true-cfg-fine-on-lightning-reference-content-dependent/175726
- FLUX.2 Klein：https://docs.comfy.org/tutorials/flux/flux-2-klein ｜ https://docs.bfl.ai/guides/usecases_editing_character_consistency ｜ https://fal.ai/learn/devs/flux-2-klein-prompt-guide ｜ https://www.datacamp.com/tutorial/flux-2-klein-tutorial
- 小云雀画布：https://www.xiaoyunque.com/tutorials/short-drama-agent-canvas
- 可灵主体库：https://kling.ai/quickstart/klingai-element-library-3-user-guide
- LTX Elements：https://ltx.studio/blog/how-to-create-a-consistent-character
- Higgsfield Soul ID：https://www.frankx.ai/guides/higgsfield-soul-id-character-consistency
- H3 首尾帧：https://minimax3.com/blog/minimax-h3-first-last-frame ｜ https://www.seedance.tv/blog/minimax-h3-first-and-last-frame ｜ https://dreamina.capcut.com/ai-video/ai-video-motion-control-predictable-animations
- ColorMatch：https://comfyui-wiki.com/en/custom-nodes/ComfyUI-KJNodes/nodes/color-match
- Hald CLUT / ffmpeg：https://docs.rs/lutgen
- 旧系统（只读）：D:\NSFW Drama system\ns-studio\adapters\image\character_assets\（plan.py、angle_guard.py、workflows.py）、config\comfy_templates\keyframe_qwen_image_2_1_edit_*.json
