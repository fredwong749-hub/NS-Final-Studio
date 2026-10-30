# NS-Final Studio · 调研 v8：写实与去 AI 味参数（A1 A2 A6 B1）

> 日期：2026-10-30。对象：本机 RTX 4080 Laptop 12GB / ComfyUI 0.39 / Qwen Image 2.1 Turbo·Base int8 / FLUX.2 Klein 4B fp8。
> 全部未实测。⚠ = 单一来源、作者自述或推断。v3/v5/v6 已写过的内容不再重复。

## 0. 结论

1. **假的根源首先在参考图和提示词，其次才是参数。**
   - assets/linwan 原图和 M0–M6 都是“AI 美颜照”：瞳孔放大、上下睫毛浓密、腮红大面积、无毛孔的瓷皮、嘟唇。
   - M0–M6 的编辑提示词写了“**严格保持图1的…眼睛形状、五官比例**”，外加“娃娃感”“精致”“美妆摄影布光”。这等于命令模型复制娃娃比例。只换采样器救不回来。
   - **先做一张“同一人的写实底板”（§5），后续所有镜头只用它当身份参考。**
2. **Turbo 不适合出写实首帧。**
   - Turbo 是 8 步固定 `ManualSigmas`，不能加步数，CFG 1 时负面词无效。
   - 同类蒸馏模型（Qwen 2512 + Turbo LoRA）的社区实测是“皮肤更塑料” ⚠。
   - 建议：Turbo 只做构图预览，**定稿用 Base 30–40 步**。
3. **本机现有的 `glamour_realism_qwen21` 方向不对。**
   - 作者自述：训练集是 45 张 AI 生成的美女图，效果是“soft, polished glamour finish，不是 raw 皮肤纹理 LoRA”。
   - 它会强化 AI 美颜感，建议停用，只在 A/B 里当反面对照。
4. **更对路的 Qwen 2.1 LoRA（均已确认有 Qwen 2.1 版本）：**
   - `krea2_film_texture`：毛孔、35mm 颗粒、高光滚降。
   - **PureLens**：用 RAW 实拍训练，非棚拍。
   - **NiceGirls 的 Asians 版**。
   - 转写实用 **Anything2RealCharacters** 或 **Turn2Real**。
5. **分辨率也是主因之一。**
   - Qwen 2.1 官方示例原生约 4MP（如 2:3 为 1696×2528，3:4 为 1792×2400）。我们用约 1MP 出图，皮肤细节天然不够。
   - 建议：1.5MP 出图，再做一次低重绘第二遍，或用 SeedVR2 放大。
6. **texture-fix VAE 保留，但它不治塑料皮。**
   - 它只消除解码器造成的棋盘格和抖点（rFID 3.37→2.08，PSNR 略降）。
   - 官方对比图是风景，没有人像数据。

## 1. Qwen 2.1 采样参数（社区报告）

| 项 | 官方 / 默认 | 写实向报告 | 来源 |
|---|---|---|---|
| 采样器 / 调度 | euler / simple，25 步（官方 pipeline 40–50） | res_2s / beta（质量最好），res_2m 折中，res_multistep 最快；也有人用 res_2s_rkmk2e + beta57 ⚠。需安装 RES4LYF 节点 | Lenovo UltraReal 作者 ⚠ |
| | | seeds_2 / sgm_uniform，20 步，CFG 3，加 APG(1,10,0.3) + FreSca(1,2,8)，1200×1600。配 Qwen-Image-2.1-Fix LoRA，针对色块、发灰和手部 ⚠ | comfyui-wiki 9-23 |
| | | er_sde / beta，25 步，CFG 2.5（旧系统 NoctQ 的设置，见 v3） | 旧系统 |
| 步数 | 25 | 改全画面的编辑约需 25 步，手指约 30 步才收敛，25→40 步细节区“嘶嘶感”减少 | ComfyUI 官方文档 |
| CFG | 1 | 2 时贴合度更高但边缘过锐，≥5 明显劣化。Lenovo 作者建议 3–4，出现脏图就退回 1 ⚠ | 官方文档 / Civitai |
| 负面词 | CFG 1 时**不生效** | CFG ≥2 才生效，单步耗时约 ×2 | 官方文档 |
| Shift | ComfyUI 按 1024² 自动拟合 | 官方：base 0.5 / max 0.9 / stretch terminal ON；Turbo：10/10。有参考图时 shift 调高更稳 ⚠。krea2 作者写的是 ModelSamplingFlux max 0.6935 / base 0.5 ⚠。两处数值不一致 | note.com robai104 / Civitai 3010645 |
| 分辨率 | 编辑时输出跟随 image_1 | 参考图建议 1024–2048 白底大图，太小会照抄或出拼贴感 ⚠。>2K 后提示词遵从下降 | note.com / 官方文档 |
| 二次精修 | — | 低重绘第二遍（Qwen Edit 2511 社区建议）⚠ | Reddit 快照 |

**本机取值：** Base 30 步，euler/simple，CFG 1；输出 1024×1536（约 1.57MP）。第二组试 res_2s/beta + CFG 2.5 + 负面词。Shift 先不动。12GB 卡上每张耗时需实测。

## 2. Qwen 2.1 写实 LoRA

只有这些已确认有 Qwen 2.1 版本。1.0/2512 版不能用于 2.1。

| LoRA | Civitai | 文件 / 大小 | 强度 | 修什么 | 与身份锁的冲突 |
|---|---|---|---|---|---|
| **Krea2 35mm Film Texture** | 3010645 | krea2_film_texture_qwen21_r64_000002500，304MB | 编辑 0.50；文生图 0.50–0.65 | 毛孔、细发、织物、35mm 颗粒、高光滚降，去黄绿色偏；无触发词 | 作者称 0.5 时“100% 保脸” ⚠。作者推荐 40 步 / CFG 2 |
| **PureLens Realism** | 2728005 | purelens_qwen21，152MB，触发词 `p3r4l4ns` | 0.5–0.8 ⚠ | RAW 实拍，毛孔与锐度 | 作者称背景偶尔变脏（10-26 新版） |
| **NiceGirls UltraReal – Asians** | 1862761（版本“v1.0 Qwen2.1 Asians”） | niceasians_qwen21，76MB | 0.6–0.8 | 真人亚洲女性脸部质感 | 会把脸往数据集脸型拉 ⚠ |
| Lenovo UltraReal | 1662740 | lenovo_qwen21，76MB | 0.6–1.0 ⚠ | 通用写实，可与 NiceGirls 叠用 | — |
| glamour_realism | 2986100 | 76MB | 0.6 | “柔光精修美颜” | **不推荐**（见 §0.3） |
| **Anything2RealCharacters** | 2808492 | Qwen2.1_Anything2RealCharacters，304MB，触发词 `transform the image to realistic photograph` | 0.7–1.0 ⚠ | 风格化 → 写实，保角色特征 | 专为转写实设计，只用于做底板 |
| Turn2Real（Qwen 2.1 版） | 2406218 | qwen21-t2r-v1，80MB | 0.5–1.0 | 同上。作者提示可加 “make their heads smaller” 防大头；1K 有时优于 2K | 同上 |
| Qwen-Image-2.1-Fix | HF e-n-v-y | 112MB | 1.0 | 色块、发灰、手部；必须配作者的工作流 | 可选 |

**原则：**
- 生产时最多叠 2 个写实 LoRA，总强度 ≤1.2。
- 转写实类 LoRA 只用于做底板，不用于生产镜头。
- 美甲、服装等资产 LoRA 叠加时，写实 LoRA 降到 0.4。

## 3. 提示词去 AI 味（Qwen）

**删除：**
- 精致、完美、网红、娃娃感、瓷肌、白皙无瑕、美颜、高清 8K、杰作、photorealistic、flawless、beautiful。
- 旧系统实测 “photorealistic” 会出塑料皮（v6）。
- B1 的“精致妆容”改为具体描述，例如“薄粉底、细内眼线、正红哑光唇”。

**加入**（中文主体 + 英文器材词。中英哪种更有效无证据 ⚠，可后续 A/B）：

```
真实人像摄影，未修图的原片，无美颜滤镜无磨皮；
皮肤：可见毛孔与细小绒毛，鼻翼和T区轻微出油反光，眼下自然细纹与淡青色，脸颊极轻微的不均匀肤色，左右脸轻微不对称；
眼睛：真实成年亚洲女性的眼睛大小与眼裂，不放大瞳孔，不戴美瞳，睫毛自然根根分明，眼神光是窗/灯形状的小高光；
头发：浅冰蓝色及腰直发，有碎发与飞丝，发根略深（染发的真实感）；
shot on Leica M11, Summilux 50mm f/1.4, Kodak Portra 400 film look, natural light falloff, focus on the near eye, creamy bokeh
```

**负面词**（只在 CFG ≥2 时生效）：

```
磨皮, 塑料皮肤, 蜡像, 瓷娃娃, 大眼睛, 美瞳, 动漫比例, 网红脸, 过度化妆, 过锐, CGI, 3D render, airbrushed, doll
```

## 4. 后期（12GB 可行）

1. **第二遍低重绘**（首选，便宜）：
   - 像素放大：`4xNomosWebPhoto_RealPLKSR`（CC-BY-4.0，用实拍退化训练），缩回 1.5×。
   - VAE Encode 后用 Base 跑 12 步，denoise 0.25–0.35；同提示词、同参考图、同 LoRA。
   - denoise >0.4 时脸会漂。
2. **SeedVR2 图像模式**：
   - 3B int8，放大 2×，ComfyUI 有官方模板。
   - 显存：模板称 8–12GB 可跑，另有用户称需 24GB ⚠。
   - 可能过锐；7B 的 FP16/FP8 有竖条纹 ⚠。
   - int8 出黑图时，关掉 FlashAttention。
3. **脸部精修**：
   - Inpaint-CropAndStitch 裁脸到 1024，denoise 0.3，加 krea2 0.5。
   - Qwen 2.1 编辑条件能否接 FaceDetailer 未验证 ⚠。
4. **颗粒 / 色差 / 光晕**：
   - 首帧只加极轻颗粒（σ≈2）或不加。H3 会把颗粒“平均化”或带来闪烁。
   - 正式颗粒在成片阶段统一加（v5/v6 的 ffmpeg 链）。
   - 色差 ≤0.5px，只在边缘；光晕只用于逆光、霓虹镜头。
   - ColorMatch 见 v6。

## 5. 把风格化参考变成“同一人的写实版”

1. **输入**：M0（灰底正面，最干净）放大到 1536 长边，作为 `image_1`；`resolution=0`。
2. **Base 编辑**：35 步，CFG 1，euler/simple，texture-fix VAE；Anything2Real 0.8 + krea2 0.5。提示词：

   > transform the image to realistic photograph。把<image1>转为真实人像摄影：同一个人，保持脸型轮廓、鼻型、唇形、浅冰蓝及腰直发和齐刘海、冷白肤色、整体辨识度；**把眼睛改为真实成年亚洲女性的正常大小**，去掉美瞳和夸张睫毛，腮红减到很淡，唇部自然；皮肤有毛孔和细绒毛，无磨皮。灰色无缝背景，柔和窗光，Leica 50mm f/2，真实照片。

   **不要再写“严格保持眼睛形状和五官比例”。**
3. **对照组**：Turn2Real 0.7（加 “make the eyes realistic size”）；纯提示词无 LoRA；Klein 4B（见 §6）。
4. **选片**：
   - 对原图的 ArcFace 余弦为 0.45–0.7 的区间较合理（太高说明仍是娃娃脸，太低说明换了人）⚠。
   - 眼宽 / 脸宽比用关键点测，应比原图下降约 10–20% ⚠。
   - 由项目方盲选。
5. **定版后**：重做 LW-ID-F 正脸底片、M0–M6 妆面和 v6 的全部身份资产。它也是 v5 林晚 LoRA 训练集的源头，这会彻底断开娃娃脸的“遗传”。

## 6. FLUX.2 Klein 4B

- **显存**：蒸馏版约 8.4GB，12GB 可用。设置为 4 步，CFG 1。
- **质感**：没有 Klein 4B 对 Qwen 2.1 的皮肤对比。仅有一篇博客比较 Klein 9B 与 Qwen 2512：一例 Klein “略蜡”，一例 Qwen 更写实 ⚠。
- **4B 可用写实 LoRA**（均在 base 4B 上训练，用于蒸馏版时效果 ⚠）：
  - Real Skin (Less Synthetic)，Civitai 2534398，368MB。
  - Realistic Skin & Face，Civitai 1426727，88MB（许可最严，仅 RentCivit）。
- **转写实提示词**：沿用 Turn2Real 的句式 “reskin this into a 35mm film (Kodak Portra 400) photo; keep her face, hair and pose”。Turn2Real LoRA 本身只有 9B / Qwen 版本。
- **定位**：做底板的对照组，以及快速第二意见。

## 7. A/B 测试矩阵（12 格）

**镜头**（均非成人）：
- **S1**：ep03 镜2，极近脸部特写，湿睫毛。
- **S2**：ep06 镜1，化妆品专柜涂红唇的极近特写。
- **S3**：ep02 镜1，深夜写字楼加班，中景或全景，侧逆光。

**公共设置：**
- 每格 2 个 seed（101、202），输出 1024×1536。
- 除 C1 外，身份参考一律用 P 步选出的写实底板（预缩放到 1024²）。
- texture-fix VAE；提示词用 §3 去 AI 版。
- 凡 Base 格都对**同一 latent 再用原版 VAE 解码一次**，免费得到 VAE 对比。

**P 步（先跑）：** 底板 3 选 1，各 4 个 seed。
- P1：Anything2Real 0.8 + krea2 0.5。
- P2：Turn2Real 0.7 + krea2 0.5。
- P3：Klein 4B + RealSkin 0.7。

参数见 §5。

| 格 | 模型 / 步数 / 采样 | CFG / 负面 | LoRA | 后期 | 测什么 |
|---|---|---|---|---|---|
| C1 | Turbo 8 步（现行），**原参考图 + 现行提示词** | 1 / 无 | 无 | 无 | 基线 |
| C2 | Turbo 8 步 | 1 / 无 | 无 | 无 | 只换底板和提示词的收益 |
| C3 | Base 30 步，euler/simple | 1 / 无 | 无 | 无 | Turbo 对 Base |
| C4 | Base 30 步，euler/simple | 1 / 无 | krea2 0.5 | 无 | 胶片纹理 LoRA |
| C5 | 同 C3 | 1 / 无 | PureLens 0.6（加触发词 p3r4l4ns） | 无 | RAW 实拍 LoRA |
| C6 | 同 C3 | 1 / 无 | niceasians 0.6 | 无 | 亚洲真人脸 LoRA |
| C7 | 同 C3 | 1 / 无 | krea2 0.4 + niceasians 0.5 | 无 | 叠加 |
| C8 | 同 C3 | 1 / 无 | glamour_realism 0.6 | 无 | 反面对照（预期更假） |
| C9 | Base 40 步，res_2s/beta（RES4LYF） | 2.5 / §3 负面词 | krea2 0.5 | 无 | 高 CFG + 负面词 |
| C10 | C4 的组合 + 第二遍：4xNomosWebPhoto → 1.5×（1536×2304），Base 12 步，denoise 0.30 | 1 | krea2 0.5 | 无 | 低重绘精修 |
| C11 | C4 的组合 | 1 | krea2 0.5 | SeedVR2 3B int8 2×，颗粒 σ2，色差 0.4px | 后期链 |
| C12 | Klein 4B 蒸馏 4 步，底板参考 | 1 | RealSkin 0.7 | 无 | Klein 对 Qwen |

**指标：**
- 项目方盲评“真人感”（1–5 分）。
- ArcFace 对底板 ≥0.75 ⚠。
- 眼宽 / 脸宽比。
- 发色 ΔE。
- 每张耗时与显存峰值。

**决策：** C3 比 C2 好，则定稿用 Base；在 C4–C7 中取最优 LoRA；C10、C11 中的胜者进入首帧链。

## 8. 需要下载的文件（未下载）

| 文件 | 来源 | 大小 | 许可（Civitai 标记 / 卡片） |
|---|---|---|---|
| krea2_film_texture_qwen21_r64_000002500.safetensors | civitai.com/models/3010645 | 304MB | 可商用（图 / 租 / 售），允许衍生。gpu3 若已有则拷贝 ⚠ |
| texture_fix_vae_for_qwen_image_2.1_bf16.safetensors | huggingface.co/madebyollin/texture-fix-vae-for-qwen-image-2.1（gpu3 已有，本机 asset_gen 已默认使用） | 未查到 ⚠ | 未注明 ⚠ |
| purelens_qwen21.safetensors | civitai.com/models/2728005 | 152MB | 图 / 租 / 售 |
| niceasians_qwen21.safetensors | civitai.com/models/1862761 | 76MB | 图 / 租 / 售；**禁止衍生**（不能合并进自训 LoRA） |
| Qwen2.1_Anything2RealCharacters.safetensors | civitai.com/models/2808492 | 304MB | 标记可售；作者要求商用另询 ⚠ |
| qwen21-t2r-v1.safetensors | civitai.com/models/2406218 | 80MB | 仅图 / 租 |
| RealSkin.safetensors（Klein 4B） | civitai.com/models/2534398 | 368MB | 仅图 / Civitai 租 |
| SeedVR2 3B int8 + seedvr2_ema_vae_fp16 | ComfyUI 模板 utility_seedvr2_image_upscale | 约 3–4GB ⚠ | Apache 2.0 ⚠ |
| 4xNomosWebPhoto_RealPLKSR | openmodeldb.info/models/4x-NomosWebPhoto-RealPLKSR | 小于 100MB ⚠ | CC-BY-4.0 |
| RES4LYF 节点包（res_2s / beta57） | github.com/ClownsharkBatwing/RES4LYF | — | 需核实 ⚠ |
| 可选：qwen-image-2.1-fix-1.0-comfy.safetensors | huggingface.co/e-n-v-y/Qwen-Image-2.1-Fix | 112MB | 未注明 |

底模本身是 qwen-research（非商用）。上述 LoRA 的商用许可不能改变这一点。

## 来源

- ComfyUI Qwen 2.1 文档：https://docs.comfy.org/tutorials/image/qwen/qwen-image-2-1
- 模型卡：https://huggingface.co/Qwen/Qwen-Image-2.1
- Texture-Fix VAE：https://comfyui-wiki.com/en/news/2026-09-24-texture-fix-vae-qwen-image-2-1
- 2.1 Fix LoRA：https://comfyui-wiki.com/en/news/2026-09-23-qwen-image-2-1-fix
- Shift 设置 ⚠：https://note.com/robai104/n/n569e844bb0f7
- Civitai API：https://civitai.com/api/v1/models/{3010645, 2986100, 1862761, 1662740, 2728005, 2808492, 2406218, 2534398, 1426727}
- Lenovo 设置：https://civarchive.com/models/1662740?modelVersionId=3349565
- Turbo 与塑料皮（2512）⚠：https://aistudynow.com/qwen-image-2512-comfyui-workflow/
- 低重绘第二遍 ⚠：https://reddit.sentinel-team.org/posts/1t0xbcd/snapshots/2026-05-08T22%3A27%3A28.91308Z
- Klein 与 Qwen 对比 ⚠：https://diffusiondoodles.substack.com/p/flux2-klein-shrinking-flux2-dev
- SeedVR2：https://docs.comfy.org/tutorials/utility/seedvr2
- Nomos 放大模型：https://openmodeldb.info/models/4x-NomosWebPhoto-RealPLKSR
- 本地：tools/char_assets/asset_gen.py、assets/characters/lin_wan/items/makeup/manifest.json
