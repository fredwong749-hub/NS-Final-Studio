# 质量深挖 03 · Qwen-Image 2.1 的胶片 / 时尚大片 / Leica 感 / 皮肤细节 / 色彩

> 日期：2026-10-31。只读调研：没有下载、没有用 GPU、没有改代码。
> 对象：首尾帧链。Qwen-Image 2.1（Turbo int8 出草稿，Base int8 / NoctQ V4 int8 出定稿），约 1.5 MP 出图，再精修到约 768×1344，交 MiniMax H3 FL2VA。身份 LoRA 为 `lin_wan_qi_v1` @0.8。
> 已读未重做：research v8（§2 LoRA 表、§4 后期）、v6（§6 色调与 Leica）、v9、`docs/research_adoption.md` §D、`pipeline.py` 的 REFINE_* 常量、`docs/research/h3_deep/00_summary.md` 的颜色一节。
> 置信度：**高** = 官方或作者原话 / 作者实测；**中** = 多名用户一致；**低** = 单帖或推断。
> 全部未实测。“独立使用人数”指 Civitai 公开 API `/api/v1/images?modelVersionId=` 返回的、作者以外发过图的账号数（2026-10-31 抓取）。这只说明有人在用，不等于好评。

---

## 0. 结论

1. **社区里没有一个 Qwen 2.1 的“Portra / Kodak / Cinestill / ARRI / Leica / Vogue / 时尚大片”专用 LoRA。**
   - 我用 Civitai API 按 `baseModels=Qwen 2.1` 搜了约 50 个关键词，查了 HF，也查了中文站。kodak、leica、editorial、fashion、magazine、vogue、cinestill、arri、anamorphic、polaroid、moody、noir、neon、grade、hdr 全部是 **0 条结果**。
   - 能用的都是“相机 / 胶片 / 电影剧照”类的泛化 LoRA。数量少、上线才 4–6 周，独立反馈极少。**所以排序主要靠作者资料的质量和数据来源，不是社区共识。** 这一点项目方要知道。
2. **对现行 `krea2_film_texture_qwen21` 的一处更正**（作者原话，高）：它的训练集是“2,951 curated cinematic & editorial frames … (filtered from 3,000 generations via automated VLM quality audit)”。
   - 也就是说，它是**从 3,000 张生成图里筛出来的**，不是真实胶片扫描。作者明确写的是 “generations”，至于是哪个模型生成的，原文没说；按名字推测是 Krea2（低）。
   - 它还是 **16:9 的 1920×1088** 训练的，我们出的是 9:16。
   - 这和 v8 停用 `glamour_realism` 的理由（用 AI 图训练）性质相近，只是程度更轻。**它仍可保留，但在 A/B 里需要有一个“真实相机数据训练”的对手。**
3. **最值得 A/B 的“真实相机数据”候选是 Danrisi 的 `Canon UltraReal`（c2n0n）**。作者原话：“trained on my photographs taken with the Canon 1Ds … rich colors, distinctive rendering, and beautiful bokeh”。
   - 它最接近项目方要的“色彩更浓 + 大光圈焦外”。
   - 同一作者的 Lenovo 有 21 万下载、26 个发图账号，是 2.1 写实 LoRA 里用户基础最大的作者。
4. **精修第二遍应考虑加 `Qwen Image 2.1 Restore LoRA`（ausboss）当“身份护栏”。** 作者在 37 张图上测过：不加时 Qwen 重绘会“pores and freckles show up that were not there, faces look older”，脸部相似度 0.79；加上后是 0.88，色彩偏移从 1.9% 降到 0.9%。
   - 这正好对应我们精修的风险（denoise 0.22–0.30 也会加戏）。
   - **注意这是 edit 模式（image_1 + 指令）下测的，我们的精修是 VAE Encode 低 denoise，未必等效（低）。**
5. **颜色要“浓”，靠 LoRA 不如靠确定性调色。**
   - 有“浓色”LoRA：Radiance Chrome 是反转片风格，但作者自述会把女性身材拉向固定体型，**否决**。GrainScape 作者称“boosted color depth”。
   - H3 已知会把颜色往偏暖、偏灰、偏暗拉（h3_deep 00_summary，≥6 人确认）。所以：
     - 首帧上做轻量 ColorMatch，把颜色拉到项目方的调色参考（v6 §6，strength 0.5–0.7）；
     - **真正的“浓色”放在成片阶段，对 H3 输出逐镜校色，再套统一 LUT。**
     - 不建议在首帧上烘重 LUT，否则 H3 会把它再平均一遍，校色基准也会丢。
6. **胶片颗粒类 LoRA（GrainScape、Dot Film、Lenovo）都会把颗粒“烘”进图里。**
   - 这与 v8 / D7 的规则（首帧颗粒 ≤σ2，颗粒只在成片加）冲突。
   - 只能低强度（≤0.4）当“色彩 / 影调”用。**不能用作颗粒来源。**
7. **“Leica 感”目前只有提示词 + 后期一条路**（v6 §6 已写）。新增证据只有两条：
   - Canon UltraReal 作者要求“describe about out-of-focus objects on foreground or background”，即焦外要靠描述前景 / 背景虚化物体来触发。
   - 社区有人建议“single directional light and one film-texture cue instead of stacking many camera terms”，即单一方向光加一个胶片质感词，不要堆砌相机术语（低）。

---

## 1. 候选排名（按“对 P2 目标的契合度 × 证据质量”排序）

| # | 候选 | 类别 | 结论 | 链路位置 | 置信度 |
|---|---|---|---|---|---|
| 1 | Canon UltraReal（Qwen2.1） | 真实相机色彩 / 焦外 | **A/B 首选对手** | 定稿档出图（也可试精修） | 中低 |
| 2 | Qwen Image 2.1 Restore LoRA（ausboss） | 精修身份护栏 | **A/B，精修档** | 精修第二遍 / 放大 | 高（作者实测） |
| 3 | filmstills_qwen2.1（Danrisi，HF） | 电影剧照调色 | A/B（电影感镜头） | 定稿档出图 | 低 |
| 4 | GrainScape UltraReal（Qwen2.1） | 胶片颗粒 + 色彩深度 | 只低强度当色彩用 | 定稿档出图 | 中低 |
| 5 | Cinematic Photography – Qwen Image 2.1（aimann） | 电影光 | 观察；资料几乎为零 | 定稿档出图 | 低 |
| 6 | Dot Film – Hard Flash（_mochi_） | 硬闪光夜景大片 | 只用于“闪光夜景”类镜头 | 定稿档出图 | 中（资料详尽，用户少） |
| 7 | Qwen Image 2.1 Fix v2.0（e-n-v-y） | 细节 / 噪点修复 | 可选，做负对照 | 定稿档出图 | 低 |
| 8 | Qwen 2.1 Tiled Upscale 工作流（ausboss） | 放大（分块保色） | 与 SeedVR2 对比 | 精修 / 4K 前 | 中 |
| 9 | KJNodes ColorMatch → 成片 LUT | 色彩 | **采用（已在 v6）** | 首帧轻量 + 后期 | 高（节点文档）/ 中（H3 漂色） |
| 10 | Detail Daemon（sigma 调整） | 细节 | 只做小幅试验 | 定稿档采样器 | 低 |
| — | 否决 | Radiance Chrome（体型偏好）、Sean Archer 风格 LoRA（在世摄影师明确反对 AI、作者自称非商用）、RAW style photo（目标是中性色，与“浓色”相反）、Casual Snapshot / Lenovo / Samsung（业余手机感，与时尚大片相反）、Asian portrait 600px（608 MB，自拍数据，会拉脸） | — | — |

**时尚大片 / 亮面材质（漆皮、金属首饰、亚克力高跟）**：没有找到 Qwen 2.1 专用 LoRA。gpu3 已有 `latex_megapack_qwen21`（latex / leather / metal，Civitai 2992770，80 MB，许可 RR，禁止衍生）是唯一相关的；作者对亮面效果没有任何说明。建议亮面材质继续靠提示词写光：

> 硬质柔光箱主光 + 条形反光板，在漆皮上形成一条长条高光，金属首饰有小而锐的点状高光，亚克力鞋跟透出背景

---

## 2. 逐个候选

### 2.1 Canon UltraReal（Danrisi）— A/B 首选对手

- **来源**：https://civitai.com/models/2783143 （API：`/api/v1/models/2783143`；镜像 https://civarchive.com/models/2783143?modelVersionId=3352035 ）
- **作者原话**（高）：
  - “--Qwen2.1 Use with 0.7 strength”
  - “trained on my photographs taken with the Canon 1Ds … designed to reproduce its rich colors, distinctive rendering, and beautiful bokeh”
  - “The dataset includes images shot with 28mm, 50mm, 100mm, and 500mm lenses, so the resulting look may vary”
  - “Prompt should be detailed (trigger word is not enough), try to describe about out-of-focus objects on foreground or background”
- **触发词**：`c2n0n`（API trainedWords）。
- **社区**：Qwen2.1 版有 11 张公开图，作者以外 2 个账号（HMNIX 4 张，MistyMystery 2 张）。没有文字评论（civarchive 页面“no user comments”）。同一作者的 Lenovo UltraReal Qwen2.1 版有 166 张图、26 个账号，作者口碑可信（中）。**Canon 本身在 Qwen 2.1 上的效果无独立评价（低）。**
- **文件**：`canon_qwen21.safetensors`，76 MB（civarchive 显示 76.05 MB）。许可：Image / RentCivit / Rent / Sell / SellMerge，allowDerivatives = true。底模仍受 qwen-research 许可约束。**gpu3 没有，笔记本也没有。**
- **与 lin_wan_qi_v1 @0.8 叠加**：Canon 0.5（作者的 0.7 是单独使用时的值），身份 0.8 + Canon 0.5 = 1.3。如果还要保留 krea2，就改为 Canon 0.4 + krea2 0.3。按 v8 原则，写实类合计 ≤1.2，全部 LoRA 合计 ≤ gpu3 `LORA_CAP 1.6`。
- **风险**：
  - 数据集含 500mm 长焦，可能出现长焦压缩感或风光感（低）。
  - 1Ds 是 2002 年的 CCD 相机，色彩偏浓偏暖，叠加 H3 的偏暖漂移可能过头（推断，低）。
  - 对身份 LoRA 的干扰：未知。
- **建议实验**：同镜头、同种子、同身份 LoRA，比较 A = krea2 0.5（现行）、B = Canon 0.5、C = Canon 0.4 + krea2 0.3、D = 无写实 LoRA。提示词按作者要求加前景 / 背景虚化物描述，并加 `c2n0n`。

### 2.2 Qwen Image 2.1 Restore LoRA（ausboss）— 精修身份护栏

- **来源**：https://civitai.com/models/2989697 、 https://huggingface.co/ausboss/Qwen-Image-2.1-Restore-LoRA
- **作者原话**（高，作者实测）：
  - “Without the LoRA Qwen covers her face in pores and freckles that are not in the picture”；
  - “Face match 0.79 without, 0.88 with (on 29 of them; closer on every one)”；
  - “Color and brightness shift 1.9 % without, 0.9 % with”；
  - “Strength works as a dial: 0.5 for a blurry photo, 0.75 for a little more of Qwen's own texture, 1.0 to stay truest”；
  - 文件说明：“step 1,500, start here … Skin comes out a little smooth”，以及 “step 1,250. Draws more fine detail and keeps more skin texture … A little less close”。
- **用法**（作者原话）：“Resize your picture to about 2 MP … Text Encode Qwen Image 2.1: the resized picture as image_1, resolution 0 … KSampler … CFG 1, euler / simple, denoise 1. 8 steps with Viggle Turbo at 1.0, or 25 steps without it.”
- **社区**：Civitai 220 赞、0 踩、9 条评论（评论内容抓不到，API 401）。作者的分块放大工作流有 3,467 下载、160 赞（中）。
- **文件**：`qwen-image-2.1-restore.safetensors` 152 MB；`qwen-image-2.1-restore-1250.safetensors` 152 MB（HF）。rank 32，ComfyUI key 格式。许可为 qwen-research。**gpu3 和笔记本都没有。**
- **链路位置**：精修第二遍。有两种接法：
  - (a) 我们现在的低 denoise 精修上叠 0.5–0.75；
  - (b) 改成作者的 edit 式重绘（image_1 = 初版首帧，denoise 1）。
  - (b) 是作者实测过的路径；(a) 没人测过（低）。
- **叠加**：精修档 = 身份 0.8 + Restore 0.75 + PureLens 0.4 = 1.95，超过 1.6 上限。建议精修档去掉 PureLens，或改为 Restore 0.5 + PureLens 0.3。
- **风险**：皮肤偏光滑，与“毛孔可见”的目标有张力，可以用 1250 版补回一些。H3 本来就会抹平细纹理，所以 Restore 的“少编细节”反而可能减少 H3 闪烁（推断）。
- **建议实验**：在精修档对比 R0 = 现行（PureLens 0.4 @0.22）、R1 = Restore(1500) 0.75 @0.30、R2 = Restore(1250) 0.75 @0.30、R3 = edit 式重绘（作者工作流，25 步）。指标：对 master 的 SFace、拉普拉斯能量（锐度）、颗粒能量（高通方差）。另外要送进 H3 跑 5 秒，测脸部区域的帧间高频闪烁。

### 2.3 filmstills_qwen2.1（Danrisi，HF）— 电影剧照调色

- **来源**：https://huggingface.co/Danrisi/filmstills_qwen2.1
- **作者原话**（高）：“Use it with strength 0.7”。示例提示词以 “film still, 35mm film still from 90s cyberpunk movie … purple and magenta color grading … high contrast with deep shadows” 开头，说明“film still …”句式就是触发方式（推断）。
- **社区**：HF 1,083 下载、8 赞。没有讨论帖，Civitai 上也没有对应页面。**独立评价为零（低）。**
- **文件**：`filmstills_qwen21.safetensors` 76 MB，license other（qwen-research）。**gpu3 和笔记本都没有。**
- **链路位置**：定稿档出图，只用于“电影感”镜头（夜景、霓虹、侧逆光）。
- **叠加**：0.4–0.5，加身份 0.8，合计 ≤1.3。
- **风险**：会套用作者数据集的电影调色，可能是青橙或品红这类强调色。对林晚雾霾蓝发色的影响未知；v9 已提醒暖调下发色会发脏。
- **建议实验**：ep02 镜1（夜间写字楼侧逆光）对比 krea2 0.5 与 filmstills 0.5。另测发色 ΔE。

### 2.4 GrainScape UltraReal（Danrisi）— 只当“色彩 / 影调”低强度用

- **来源**：https://civitai.com/models/1332651 、 https://huggingface.co/Danrisi/grainscape_qwen2.1 、 https://civarchive.com/models/1332651?modelVersionId=3352222
- **作者原话**（高）：
  - “--Qwen2.1 Use at 0.7 strength”；
  - “Authentic film grain – Not some fake digital overlay. This is deep, baked-in texture.”；
  - V2 说明（属于 Flux 版，Qwen2.1 版是否同一数据集未写）：“boosted color depth to make the output feel more vivid and alive”，以及 “Vertical banding on flat textures has been noticeably reduced—while not completely gone”。
- **社区**：Qwen2.1 版 24 张图，作者以外 6 个账号（EnragedAntelope、HMNIX、plectrudecatastrophe、nonemo13、tsolful、ShadowCell）。全模型 1,613 赞、2 踩。是本表里独立使用人数最多的胶片类 LoRA（中）。
- **文件**：`grainscape_qwen21.safetensors` 76 MB。许可 IRRSS，**allowDerivatives = false**。**gpu3 和笔记本都没有。**
- **风险**：
  - 颗粒是“baked-in”的，与 D7 规则冲突；颗粒会在 H3 里闪烁或被抹平（v8 §4.4）。
  - 平坦区域的竖条纹（作者在 V2 说明里承认“not completely gone”）。
- **结论**：只在 0.3–0.4 下试“色彩深度”是否有增益。如果颗粒能量超过 σ2 档，就淘汰。

### 2.5 Cinematic Photography – Qwen Image 2.1（aimann）

- **来源**：https://civitai.com/models/2987424 、 https://civarchive.com/models/2987424
- **作者原话**：说明只有一句，“Cinematic Photography and Lighting for Qwen Image 2.1 No LoRA Trigger needed.” 没有强度、步数和数据说明。评论只有一条问触发词，作者答“Not needed”。
- **社区**：19 张图，作者以外 2 个账号。
- **文件**：`cinematic_qwen21_2_c1-st5000.safetensors` 240 MB。许可 IRR。**gpu3 和笔记本都没有。**
- **结论**：资料不足，不进第一轮 A/B（低）。

### 2.6 Dot Film – Hard Flash & Gritty Film Grain（_mochi_）

- **来源**：https://civitai.com/models/2999989 、 https://civarchive.com/models/2999989
- **作者原话**（高，资料是本表里最规范的）：
  - “Use LoRA strength 1.0, 40 sampler steps, Euler/simple and 1024 x 1024 output. No trigger word is needed.”
  - “Changing the checkpoint can affect the face and clothing … Higher training steps do not consistently give better results”
  - “The demos used a quantized ComfyUI setup with an INT8 DiT and text encoder and a BF16 VAE”（与我们的 int8 一致）。
  - 训练：DiffSynth-Studio、Qwen Image 2.1、64 张图、rank 16。
- **社区**：13 张图，作者以外 2 个账号。有一条评论说“Is there a prompt? I have no effect”，作者回复了提示词。所以**不在提示词里写 flash 时效果弱**（低）。
- **文件**：3 个检查点（step500 / 750 / 1000），各 160 MB。许可 IRRS，另附 Qwen Research License。**gpu3 和笔记本都没有。**
- **用途**：只适合“夜间硬闪光”类时尚镜头（Juergen Teller / Terry Richardson 式直闪是时尚摄影的一种）。不适合通用镜头。
- **风险**：作者承认会影响脸和服装；颗粒粗，H3 会闪烁。强度要压到 0.5 左右，与身份 LoRA 合计 1.3。

### 2.7 Qwen Image 2.1 Fix v2.0（e-n-v-y）

- **来源**：https://civitai.com/models/2957332 、 https://huggingface.co/e-n-v-y/Qwen-Image-2.1-Fix-v2.0
- **说明**：页面只有 sampler 链接（DPMpp-2M-Sharp）和对比图。第三方博客的转述是：“targeting noise and untidy details with little composition change”，而 Opinionated v1.0 “may alter composition”（https://spicyapi.ai/blog/qwen-image-2-1-artifacts-fix ，低）。
- **文件**：`qwen2.1-detail-fix-2.0.safetensors` 52 MB（另有 opinionated 版 480 MB）。v8 列的是 v1.0（112 MB），**v2.0 更小，是更新版**。**gpu3 和笔记本都没有。**
- **社区**：7 张图，作者以外 1 个账号。
- **结论**：可选。不清楚它是否需要专用采样器才有效（作者把采样器放在说明第一行）。

### 2.8 分块放大：ausboss Tiled Upscale 与 SeedVR2

- **来源**：https://civitai.com/models/2988629
- **作者原话**（高）：
  - “Each tile is matched to your picture before the tiles are joined. Grain and color noise do not push the saturation up.”
  - “A picture of 1 megapixel or more has to grow to look better, about 1.6 times per side.”
  - “Fast … 8 steps with the Viggle Turbo LoRA. Click it off for 25 steps … it came out a little closer to the picture.”
- **社区**：3,467 下载、160 赞、0 踩（中）。需要 AusBoss 节点 2.15.0+ 和 ComfyUI 0.38+。
- **对比**：SeedVR2 图像模式已在 D5 采用。两者没有社区横评。只有一个“2-VOSR2 vs SeedVR2”对比工作流（https://civitai.com/models/2974349 ，B 站作者 Astral），没有结论文字。
- **相关风险**（第三方转述 stable-diffusion.cpp issue #2041，低）：“an eight-pixel grid with a four-pixel component at native 2K sizes”，即原生 2K 尺寸下会出现 8 像素网格（含 4 像素分量）。**脸部 8px 网格在 H3 里会变成闪烁的纹理**，所以放大后要放大检查颊部。texture-fix VAE 作者称能改善，但“faces had not been thoroughly tested”。

### 2.9 色彩：ColorMatch → H3 → 逐镜校色 → LUT

- **KJNodes ColorMatch**（https://comfyui-wiki.com/en/custom-nodes/ComfyUI-KJNodes/nodes/color-match ，高）：
  - 方法有 “mkl”, “hm”, “reinhard”, “mvgd”, “hm-mvgd-hm”, “hm-mkl-hm”；
  - strength 默认 1.0，范围 0–10；
  - 需要 `pip install color-matcher`。
- **H3 漂色**（`docs/research/h3_deep/00_summary.md`，中，≥6 人）：会偏暖偏灰、对比度上升、变暗，或肤色发紫。三个项目的共同做法是**后期逐镜校色到我们自己的调色关键帧，不用 LUT 或硬直方图匹配**。768×1344 属于变暗风险区。
- **LUT 节点**：ProPost 的 `ProPostApplyLUT`（.cube，有 strength 和 log 开关，https://comfy.icu/node/ProPostApplyLUT ，中）。有来源提醒：“a LUT designed for log input … will look wrong applied to linear or sRGB data”（低）。
- **建议链路**：
  1. 首帧做 ColorMatch，strength 0.5，向项目方的调色参考靠拢（不做重调色）。
  2. 交给 H3。
  3. 用首帧和尾帧做锚点，逐镜做 LAB 或通道增益校正。
  4. 套统一 3D LUT，这一步才把颜色“做浓”。
  5. 锐化，然后加颗粒 σ2。
  - **不要在首帧上烘重 LUT 或浓色 LoRA**，否则 H3 漂移后基准会丢失。
- **Natural Exposure LoRA**（prithivMLmods，HF，80 MB，edit 用）：作者自称是“experimental preview”，训练只用了 38 对图，而且局限里写了 “Strong color casts”。**不推荐。**

### 2.10 Detail Daemon / sigma 技巧

- **来源**：https://github.com/Jonseed/ComfyUI-Detail-Daemon
- 声称兼容 “SDXL, SD1.5, Qwen, Z-Image”。负值调低 sigma 会增加细节，过量会坏图。
- **没有任何 Qwen 2.1 的实测参数（低）。**
- **结论**：只在定稿档做 detail_amount 0.1 / 0.2 两档小试。同时测颗粒能量，不能超过 σ2 档，否则 H3 会闪烁。

---

## 3. 与 krea2_film_texture / PureLens 的社区对比

**没有找到任何社区横评**（Civitai、HF、reddit 镜像、知乎、B 站、note.com 都没有）。已知事实如下：

| | krea2_film_texture | PureLens |
|---|---|---|
| 数据 | “filtered from 3,000 generations”（生成图），16:9 | 作者自称 “high-quality photographs and images converted from raw formats (DNG, ARW, CR2, NEF...)”，“not studio shoots” |
| 作者对 Qwen2.1 的保留意见 | 无 | “the background gets a bit messy in some images” |
| 独立使用（Qwen2.1 版） | 19 张图，作者以外 2 个账号 | 11 张图，**0 个**独立账号 |
| 下载 / 赞 | 1,127 / 42 | 11,341 / 473（含其他底模版本） |

所以，**两者都没有独立的 Qwen 2.1 好评**。我们的 owner_ab（2026-10-30）选 PureLens 0.4 @0.22，是目前唯一的实测证据。

---

## 4. 叠加上限（与 lin_wan_qi_v1 @0.8）

- v8 原则：写实 LoRA 最多 2 个，合计 ≤1.2；资产 LoRA 同时出现时，写实 LoRA 降到 0.4。gpu3 实际是 `LORA_CAP = 1.6`（全部合计，D4）。
- 建议 A/B 期间统一按“**身份 0.8 + 风格 ≤0.6 + 资产 ≤0.4，总和 ≤1.6**”执行。超出时先降风格 LoRA。
- 风格类（Canon / filmstills / GrainScape / Dot Film）**同时最多 1 个**。都是“画风”类，两两叠加会互相抢色调。

---

## 5. 建议的对比实验（项目方盲选）

**公共设置**：
- 镜头：S1 极近脸部特写、S2 红唇专柜近景、S3 夜间写字楼侧逆光中景（沿用 v8 §7），再加 **S4 亮面材质镜头**（漆皮、金属耳环、亚克力跟）。
- 种子：101 / 202。
- 底模：Base int8，35 步，CFG 3，texture-fix VAE，1.5 MP；lin_wan_qi_v1 @0.8。

| 格 | 定稿档 LoRA | 精修档 | 测什么 |
|---|---|---|---|
| F0 | krea2 0.5 | PureLens 0.4 @0.22（现行） | 基线 |
| F1 | Canon 0.5（+`c2n0n`，写焦外物） | 同 F0 | 真实相机色彩 / 焦外 |
| F2 | Canon 0.4 + krea2 0.3 | 同 F0 | 叠加 |
| F3 | filmstills 0.5 | 同 F0 | 电影调色（S3 为主） |
| F4 | GrainScape 0.35 | 同 F0 | 色彩深度；颗粒能量超标即淘汰 |
| F5 | krea2 0.5 | Restore(1500) 0.75 @0.30 | 精修身份护栏 |
| F6 | krea2 0.5 | Restore(1250) 0.75 @0.30 | 护栏 + 保纹理 |
| F7 | krea2 0.5 | F0 精修 → ColorMatch 0.5 到调色参考 | 首帧色彩 |
| F8（只限 S3 夜景） | Dot Film step500 0.5 + 提示词写 direct flash | 同 F0 | 硬闪光大片 |

**指标**：
- 对 master 的 SFace 余弦（以及 ArcFace，与 v8 一致）。
- 锐度：脸部 ROI 拉普拉斯方差。
- 颗粒能量：高斯高通后皮肤区域的方差，要求 ≤ σ2 加噪参考图。
- 发色 ΔE、脸部 8px 网格（FFT 峰）。
- **每格挑 1 张送 H3 跑 5 秒**：测脸部高频的帧间闪烁，以及首帧与第 60 帧的 LAB 偏移。
- 项目方盲选：P2 维度是“电影感 / 时尚大片 / 色彩 / 像不像林晚”。

**需要下载的文件**（未下载，由 gpu3 / 总调度决定）：

| 文件 | 大小 | 来源 |
|---|---|---|
| `canon_qwen21.safetensors` | 76 MB | Civitai 2783143 |
| `filmstills_qwen21.safetensors` | 76 MB | HF Danrisi |
| `grainscape_qwen21.safetensors` | 76 MB | Civitai 1332651 / HF |
| `qwen-image-2.1-restore.safetensors`、`-1250` | 各 152 MB | HF ausboss |
| `dot-film-v0.1-qwen-image-2.1-step500.safetensors` | 160 MB | Civitai 2999989 |
| `purelens_qwen21` | — | 若 gpu3 要跑 F0，需从笔记本拷贝 |

---

## 6. 没找到 / 不能确认的

1. 任何 Qwen 2.1 的 Portra / Kodak / Cinestill / ARRI / 变形宽银幕 / Leica / Vogue / 时尚大片 / 杂志 / 棚拍布光 LoRA（Civitai API 关键词 0 结果；HF 与 liblib 也没有）。
2. 漆皮、金属首饰、亚克力高跟的专用亮面材质 LoRA（Qwen 2.1）。
3. 上述 LoRA 的**用户文字评价**：Civitai 评论和评测接口返回 401（“Please use the public API instead”）；civarchive 页面多数“no user comments”；reddit / 知乎 / note.com 没有检索到 Qwen 2.1 相关帖子。所以“中”置信度最多只能来自发图人数。
4. Canon、filmstills、GrainScape 与身份 LoRA 叠加后的身份漂移：没有任何人测过。
5. Detail Daemon、Ultimate SD Upscale 在 Qwen 2.1 上的实测参数。
6. Restore LoRA 在“低 denoise 的 VAE Encode 精修”（我们的接法）下是否仍有 0.79→0.88 的身份增益：作者只测了 edit 式重绘。
7. ai-toolkit `arch qwen_image_2` 字段：上述文件都在 Civitai 标注 baseModel = “Qwen 2.1”，或在 HF 卡写 `base_model: Qwen/Qwen-Image-2.1`。Dot Film 写明用 DiffSynth + Qwen Image 2.1 训练，Restore 标 ai-toolkit。我没有读 safetensors 头来核对 key 格式（规则不允许下载）。
8. purelens 在笔记本上的具体路径：任务说明称它只在笔记本 ComfyUI 上，但我在 `D:\kimi-ns-storyboard\ComfyUI\models\loras` 没看到，可能在另一个 ComfyUI 实例。

---

## 来源

- Civitai API（模型、版本、文件、许可、图片计数）：
  - `https://civitai.com/api/v1/models?baseModels=Qwen%202.1&types=LORA&query=…`
  - `https://civitai.com/api/v1/models/{2783143,1332651,2987424,2999989,2957332,2989697,2988629,3010645,2728005,1662740,2323765,1632416,1751076}`
  - `https://civitai.com/api/v1/images?modelVersionId=…`
- civarchive 镜像（评论检查）：https://civarchive.com/models/1332651?modelVersionId=3352222 、 https://civarchive.com/models/1662740?modelVersionId=3349565 、 https://civarchive.com/models/2783143?modelVersionId=3352035 、 https://civarchive.com/models/2728005 、 https://civarchive.com/models/2999989 、 https://civarchive.com/models/2987424
- HF：https://huggingface.co/Danrisi/filmstills_qwen2.1 、 https://huggingface.co/Danrisi/grainscape_qwen2.1 、 https://huggingface.co/ausboss/Qwen-Image-2.1-Restore-LoRA 、 https://huggingface.co/e-n-v-y/Qwen-Image-2.1-Fix-v2.0 、 https://huggingface.co/prithivMLmods/Qwen-Image-2.1-Natural-Exposure-LoRA
- 工作流：https://civitai.com/models/2988629 、 https://civitai.com/models/2974349 、 https://civitai.com/models/2960068
- 节点：https://comfyui-wiki.com/en/custom-nodes/ComfyUI-KJNodes/nodes/color-match 、 https://comfy.icu/node/ProPostApplyLUT 、 https://github.com/Jonseed/ComfyUI-Detail-Daemon
- 伪影（第三方，低）：https://spicyapi.ai/blog/qwen-image-2-1-artifacts-fix
- 提示词（第三方，低）：https://github.com/magiccreator-ai/awesome-qwen-image-2-1-prompts
- 本地：`script play lib/research v8 写实与去AI味参数.md`、`research v6 角色资产与一致性.md`、`docs/research_adoption.md` §D、`docs/research/h3_deep/00_summary.md`、`config/visual_bible.toml` [realism]、`services/render_router/ns_render/pipeline.py` REFINE_*
