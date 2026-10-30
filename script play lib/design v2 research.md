# NS-Final Studio · 深度调研 v2：新模型栈、创作页与多 GPU 渲染阵列

> 本文是 `design md file.md` 的增量升级。原文中的资产版本化、Temporal 工作流、QC、成本、合规等结论继续有效；本文只写**新增模型带来的变化**，以及**创作页、Agent 资产识别、多 GPU 渲染**的落地设计。
>
> 调研日期：2026-10-29。所有模型信息来自各仓库模型卡/README；模型卡没写的数字（显存、速度、时长）本文一律标为“未公布，需实测”，不做臆测。

---

## 0. 结论摘要（先看这一节）

1. **全部走本地 ComfyUI 是对的，而且对这个剧几乎是唯一选项。** 《为他而骚》是成人向内容；MiniMax 官方模型卡写明对提交内容做自动审核，色情内容可能被拦截；百炼等托管 API 同理。所以云端只能做非敏感镜头的对照，主生产必须本地。
2. **但本地 Qwen Image 2.1 是 Qwen Research License（仅研究）。** Comfy-Org 的打包版也标的是 `qwen-research`。要商业发行，必须先拿到阿里的商用授权，否则整条首帧链路有法律风险。这是第一优先级的非技术阻塞项。
3. **新模型的定位**：

   | 模型 / 节点 | 在系统中的角色 | 默认启用？ |
   |---|---|---|
   | Comfy-Org/Qwen-Image-2.1（base + turbo + turbo LoRA + Fun ControlNet + PE） | 资产库母版（base）、镜头首帧（turbo）、姿势控制（ControlNet） | ✅ 主力 |
   | lilylilith/QI_2.1_AnyAngle（LoRA） | 角色转面图、场景反打/多机位 | ✅ 资产阶段 |
   | FastVideo/FastH3-Omni-Comfy（8 步 Ref2VA） | 整集**快速预演**、多角色参考镜头 | ✅ 预演档 |
   | MiniMax-H3 Base FL2VA（原版） | **首帧锁定**的正式视频 | ✅ 正式档 |
   | facok/comfyui-SelfLift + TST | H3 渐进分辨率加速 + 时序修正 | ⚠️ A/B 通过后启用 |
   | LBH-123-AI H3 Latent Upscaler | 两段式采样（低分辨率→latent 放大→精修） | ⚠️ A/B 通过后启用 |
   | OliviaRossi/…PRISM（Singularity × 10Eros-Max 合并） | 风格/质感实验通道 | ❌ 仅实验，不进默认 |
   | Omnichar `.char` + MiniMaxH3Mod RefMod | 角色打包与参考缓存 | ✅ 沿用原方案，但对新 checkpoint 需重新验证 |

4. **最大的技术缺口**：快模型（FastH3-Omni、PRISM 合并、Singularity）都是 **Ref2VA（参考生视频）**，不能“硬锁首帧”。而你的流程是“Qwen 首帧 → 图生视频”，首帧锁定只有 **FL2VA** 能做到。所以必须分两档：**预演用快 Ref2VA，正式用 FL2VA**。10Eros-Max 模型卡声称支持 I2V，可能是快速 FL2VA 候选，需验证其 checkpoint 血统。
5. **多 GPU 阵列**：ComfyUI 一个进程基本只用一张卡。正确做法是**每卡一个 headless ComfyUI 实例 + 模型亲和调度**（让 H3 卡常驻 H3、Qwen 卡常驻 Qwen，避免 33B 模型反复加载），而不是试图让一个任务跑满 8 卡。单任务多卡（Ulysses 序列并行）只在 SGLang / FastVideo UniServe 路径存在。

---

## 1. 模型逐个核查

### 1.1 Comfy-Org/Qwen-Image-2.1（ComfyUI 打包版）

文件（放到 `ComfyUI/models/` 对应目录）：

| 目录 | 文件 | 用途 |
|---|---|---|
| diffusion_models | `qwen_image_2.1_bf16` / `_int8_convrot` | Base，高质量，40 步级别 |
| diffusion_models | `qwen_image_2.1_turbo_bf16` / `_int8_convrot` | Turbo，**8 步、cfg 1** |
| loras | `qwen_image_2.1_turbo_lora_avg_rank_178_bf16` | 从 base 提取的 Turbo LoRA（base + 此 LoRA ≈ turbo，可与其他 LoRA 叠加） |
| model_patches | `qwen_image_2.1_fun_controlnet_union_bf16` / `_int8_convrot` | 统一 ControlNet（姿势/深度等，具体控制类型以官方模板为准） |
| text_encoders | `qwen3vl_8b_bf16` / `_int8_convrot` / `_w4a8` | 文本+视觉编码器 |
| text_encoders | `qwen3.5_9b_qwen_image_2.1_pe_t2i` / `_pe_i2i`（int8 / w4a8） | **提示词增强器**，通过 `Generate Text` 节点使用 |
| vae | `qwen_image_2.1_vae_bf16` | VAE |

官方模板：T2I、Image Edit、Turbo T2I、Turbo Image Edit、Remove Background。

能力要点（Qwen/Qwen-Image-2.1 模型卡）：最多 **10 张参考图**；可在编辑中保持人物/产品身份；9:16 推荐 **1536×2752**。

对本系统的用法：

- **Base（40 步）只用于资产母版**：角色定妆照、衣服平铺、鞋/美甲特写。数量少、质量要求最高，慢一点无所谓。
- **Turbo（8 步、cfg 1）用于 360 镜首帧批量**。注意 cfg=1 意味着负面提示词基本无效——现有提示词里的“基础负面”要改写成正向约束（这点原设计文档已指出）。
- **PE 提示词增强器在生产模式关闭**。你的剧本提示词是锁定的创作内容，PE 会改写；只在“资产草稿”阶段可选开启，且改写前后都存档。
- **Turbo LoRA 的意义**：需要叠加 AnyAngle 等 LoRA 时，用 “base + turbo LoRA + AnyAngle LoRA” 比直接用 turbo 模型更可控。需实测两种组合。
- **Fun ControlNet union**：双人镜站位、特定姿势（如背影、坐姿）可用 OpenPose/深度图约束构图，替代“抽卡”。

许可：`qwen-research`。**商用前必须取得授权。**

### 1.2 lilylilith/QI_2.1_AnyAngle（LoRA，Apache-2.0）

- 功能：改变图像相机角度，同时保持风格。比固定方位角/仰角的编辑更不容易风格漂移。
- **不是一句提示词就能转角度**。作者流程：原图 → 高斯泼溅（Tripo Splat）或 3D 模型（Trellis2 / Pixal3D）→ 导入 Blender 设新相机 → 导出粗渲染图 → 粗渲染 + 原图一起喂给 Qwen 2.1 + LoRA。
- 编辑提示词：`Change the camera angle from <image2> to <image1>.`
- 推荐：LoRA 强度 1、**CFG 3.0、20 步以上**（基于 base）；可用 turbo，质量略降。
- 局限：3D 粗模不准时出现空间错误；**原图脸部细节不足或分辨率低时会出现崩脸**。

在本系统中的两个用途：

1. **角色转面图（face/body 槽位）**：从一张确认的正面定妆照生成 45°/侧面/背面。崩脸风险 → 转面后必须再用 Qwen Edit + 正脸参考做一次脸部修复，并走人脸相似度 QC。
2. **场景多机位（场景锁 SK-*）**：这是 AnyAngle 最大的价值。办公室、电梯、出租屋、小巷等固定场景，一张确认的场景图 → 3D 粗模 → 一次性产出正打/反打/俯拍/侧拍全套场景参考。解决同场景反打不一致的老问题。场景 3D 粗模可以复用到全剧。

### 1.3 FastVideo/FastH3-Omni-Comfy（MiniMax-H3 社区许可）

- 基于 MiniMax-H3 的 **8 步** 衍生模型；guidance 1.0；**video shift 12.0、audio shift 3.0**。
- 文件：`fasth3_omniref_8step_pruned_bf16` / `_int8_convrot`；文本编码器 `qwen3vl_32b_minimax_h3_*`（bf16 / int8 / nvfp4_awq——**nvfp4 仅 Blackwell**）；视频 VAE + **音频 VAE（要出声必须装）**。
- 模式：**参考生视频（Ref2VA）**。最多 9 图、3 视频、3 音频，合计 ≤12；**至少需要 1 张图或 1 段视频**；提示词用 `<Picture 1>` `<Video 1>` `<Audio 1>` 按顺序引用。
- ComfyUI 节点：原生 `MiniMax H3 Reference to Video` 条件节点。
- FastVideo 原版说明本地 profile **默认 480p**；时长、显存、加速倍数**均未公布**。
- 注意：ComfyUI 输出与 FastVideo/UniServe 运行时会有差异。

定位：**整集预演（Animatic）+ 多角色参考镜头**。把首帧作为 `<Picture 1>`、角色参考作为 `<Picture 2..n>`，可以快速看到 6 镜连起来的节奏、走位和台词时长，确认后再花正式算力。

### 1.4 MiniMax-H3 原版（复核）

- 33B 稠密单流 Omni-Transformer，其中约 13B 是 AdaLN 分支，推理时可预计算缓存。
- 两个 checkpoint：**FL2VA**（文生、首帧/首尾帧生音视频）与 **Ref2VA**（参考生音视频），是**两套不同权重**。
- 768p、24fps、32kHz 立体声、4–15 秒；2K 再生成模块未开源。
- 多卡示例只出现在 SGLang（`--num-gpus 4 --ulysses-degree 4`）。
- ComfyUI 原生支持（社区教程称 2026-08 合入，ComfyUI ≥0.30.0），有 T2V/R2V/首尾帧模板——但部分模板调用的是 MiniMax API 节点，部署时要确认用的是本地模型节点。

**许可（MiniMax H3 Community License）关键条款**：

- 可商用；年营收超 2000 万美元需书面授权。
- 商业产品 UI 需**显著展示 “MiniMax H3”**；分发需附 NOTICE。
- **适用地域排除欧盟、英国、韩国、美国**，在这些地区使用不在授权范围内。如果发行渠道面向这些地区，需法务评估。
- 禁止项包括：伤害未成年人、未经同意冒充他人。条款本身未单独禁止成人内容，但发行平台规则另算。
- 衍生模型不得附加与本许可不同的条款。

### 1.5 facok/comfyui-SelfLift（渐进分辨率采样，未声明许可）

- 原理：前几步在低分辨率去噪，然后“抬升”到全分辨率完成。
- 节点：
  - `SelfLift Progressive Sampler (Image)`：针对 rectified-flow 图像模型（论文示例为 Z-Image-Turbo、FLUX.2-Klein，**未提 Qwen**）。参数 `transition_step=6`、`lowres_scale=0.5`、`rho=0.3` 等。
  - `SelfLift Progressive Sampler (MiniMax H3)`：**实验性**，可接 H3 latent upscaler，支持 `highres_tiling`。
  - `H3 Temporal State Transport (TST)`：MODEL→MODEL 补丁，`tau=0.2` 推荐，时序注意力修正。
- 限制：只支持标准 Euler（`s_churn=0`）；TST 与 tiling 不兼容；tiling 只保留第一块的音频；H3 低分辨率短边 384px 可能超出训练分布；作者自称 H3 证据只有单 seed。
- **仓库未声明许可证**——商业使用前需联系作者或自己实现等效逻辑。

定位：正式档 FL2VA 的**提速候选**。必须在金标镜头上与“原版直接 768p”做同 seed 对比（身份、闪烁、音频），通过才启用。

### 1.6 LBH-123-AI/Minimax_h3_latent_Upscaler（Apache-2.0）

- 直接在 H3 的 24 通道 VAE latent 上做空间放大，1.0×–4.0×（默认 2×），保持时间维度不变。
- 约 345M 参数，bf16/fp16 约 691MB。
- 配套节点 `Comfyui_Minimax_h3_latent_Upscaler`，放 `models/latent_upscale_models/`。SelfLift 的 H3 采样器会自动识别文件名含 “h3” 的放大模型。
- 意义：**两段式采样**——低分辨率出动作 → latent 放大 → 高分辨率少步精修，省掉 VAE 解码/再编码。这也是 10Eros 作者建议的“2-pass 消除闪烁”的实现方式。还可以探索本地“伪 2K”（768p → 1.5–2× latent → 精修），但显存和质量都要实测，不等同官方 2K 再生成。

### 1.7 OliviaRossi/Minimax-h3_Singularity-x-10Eros-Max_PRISM（许可 other）

- **两个 H3 衍生模型的合并**：
  - A：`WarmBloodAban/Minimax-h3_Singularity`（Ref2VA v2）——作者称增强 HDR 锐度、中远景脸部稳定、降低皮肤油光、动作戏。
  - B：`TenStrip/10Eros-Max`（8 步 TURBO beta6/7）——“shifted base H3”，推荐 shift 12/3、8 步、Euler/Simple。
- PRISM 是作者自定义合并算法（随机 SVD 分离差异、SLERP 方向插值、符号冲突调和、范数重锚），不是 mergekit，也不是 abliteration。
- 主文件 `…PRISM_b_fp16.safetensors`；另有两个 int8 测试版。**无推荐参数、无评测、无已知问题说明**。
- 来源模型的已知问题：10Eros **单次采样易背景/latent 闪烁**（需 2-pass）；需要约 90% 稀疏度的 VSA，SLA 会破坏 beta6；**参考工作流不能用 cache/Spectrum 加速**；turbo 音频比全步数差。
- **许可链很乱**：Singularity 自称 Apache-2.0，但 H3 许可规定衍生模型不得附加不同条款；10Eros 声明含 LTX 2.3、Wan 2.2、Krea 2 的成分，各自许可同时适用；合并版只写“跟随来源模型”。**商用基本不可审计。**

定位：**仅作为实验通道**。在 POC 里与 FastH3-Omni、原版 Ref2VA 同参考、同 prompt、同 seed 比较。即使效果最好，也只在“许可审计通过”后才能用于发行版本；所有产物要标记来源 checkpoint 哈希，便于日后替换。

### 1.8 Omnichar 与 MiniMaxH3Mod（复核）

- Omnichar：`.char` = 参考图 + 锁定描述 + 可选 LoRA + 约 30 秒声音；face/body/cloths 各 3 槽。官方列出支持 MiniMax H3、Krea 2、FLUX.2，**未列 Qwen Image**。声音只能得到“相似音色”。
- MiniMaxH3Mod（v0.2.6，仍 under construction）：RefMod 用 VAE 提取参考，不训练 H3。视觉 token = T×(H/2)×(W/2)，`max_tokens` 默认 5120；音频约 80 token/秒。**对 FastH3、10Eros、PRISM 等衍生/8 步 checkpoint 的兼容性未声明**——POC 必须覆盖。

---

## 2. 三档渲染路由（新模型落位）

```
                       ┌───────────────── 资产阶段（一次性） ─────────────────┐
  定妆照/衣服/鞋/美甲 ──► Qwen 2.1 Base(40步) ──► AnyAngle 转面/场景多机位 ──► 人工确认锁定
                       └─────────────────────────────────────────────────────┘
                                              │
  剧本+分镜+图生视频脚本 ──► Agent 解析+资产绑定 ──► 每镜参考清单（有序、带职责）
                                              │
         ┌────────────────────────────────────┼─────────────────────────────────┐
   T0 预演档                             T1 正式档                          T2 精修档
   Qwen Turbo 1张首帧                    Qwen Turbo 2候选 → QC选优          T1结果
   + FastH3-Omni 8步 Ref2VA 480p         + H3 FL2VA 768p（首帧锁定）         + latent 放大 + 精修 pass
   整集 6 镜快速串片                       (可选 SelfLift+TST 提速)            或云端 2K（仅非敏感镜）
   用途：节奏/走位/TTS时长确认             用途：成片                          用途：重点镜/宣传物料
         └──────────── 预演确认后才进入 T1，避免在正式算力上抽卡 ──────────────┘
```

| 镜头类型 | 推荐路径 | 原因 |
|---|---|---|
| 单人、首帧构图重要（大部分镜） | T1：Qwen 首帧 → FL2VA | 首帧锁定，服装/装饰细节由图片保证 |
| 动作有明确结束状态（脱外套、转身） | FL2VA 首帧 + 尾帧 | 首尾帧约束中间动作 |
| 双人/多人且无明确首帧需求 | Ref2VA（FastH3-Omni 或原版 Ref2VA）+ 每人参考图 | 首帧不必锁时，参考模式对多人身份更友好 |
| 镜面、暗场、复杂饰品（纠正器里标记的高危镜） | T1 + 2-pass 精修，额外候选 | 高失败率镜头多给预算 |
| 跨场景跟拍 | 先拆镜 | H3 单镜跨场景容易崩 |

---

## 3. 人物资产与衣橱系统（结合你的剧本）

### 3.1 从现有剧本资料直接映射

你现有的五层锁可以一对一转成数据库对象：

| 现有资料 | 系统对象 | 说明 |
|---|---|---|
| 角色 DNA 锁：林晚/顾沉/陈宇/Alex/Ryan/Kai/Leo | `Character` | 身份，跨集不变 |
| REF-LW-01 素颜通勤态 / 02 浓妆女王态 / 03 全套态 | `CharacterLook` | 剧情阶段形象 |
| 装饰锁 D0–D10、DN | `AdornmentState`（装饰状态版本） | 按集生效，带“可见/隐藏/在匣”状态 |
| 装饰状态总表（ep01-08:D0 …） | `LookSchedule` | 集 → Look + 装饰状态的时间轴 |
| 场景锁 SK-* | `SceneAsset` + AnyAngle 多机位参考组 | |
| 漆皮束腰、黑丝、风衣等（剧本中出现的服装） | `WardrobeItem` + `OutfitSet` | 单品 + 套装 + 穿着层次 |

### 3.2 资产插槽与参考图生产配方

每个插槽说明“谁来生成参考图”，这是用户上传之外的补全手段：

| 插槽 | 用户上传 | 系统补全方式 | QC |
|---|---|---|---|
| face | 正脸定妆照 1–3 张 | AnyAngle 转面 → Qwen Edit 脸部修复 | 人脸 embedding 与正脸比对 |
| body | 全身正面照 | Fun ControlNet（OpenPose）出正/侧/背站姿 | 比例一致性人工确认 |
| hair | 正/侧/背 | AnyAngle 转面 | 长度/刘海/发色标签比对 |
| makeup | 妆面近景 | Qwen Edit：同一张脸换妆（素颜↔浓妆） | 身份不变 + 妆面差异 |
| nails | 手部近景（左右手） | Qwen Edit：手部模板 + 甲面参考 | 甲形/颜色/图案 VLM 检查 |
| shoes | 鞋子平拍、侧面 | Qwen Edit：人物全身 + 鞋参考（上脚图） | 鞋型/颜色 |
| outfit | 平铺图（正/背）+ 材质细节 | Qwen Edit 多参考：人物 + 服装平铺 → 上身三视图 | 版型/颜色/层次 |
| adornment（装饰） | 设计图 | 按 D 状态生成局部特写参考 | 数量、位置（按镜头可见性检查） |
| scene | 场景图 | Trellis2/Tripo 粗模 → Blender 机位 → AnyAngle | 空间锚点一致 |

**关键规则（沿用原设计）**：每镜不要把所有参考都塞进去。Reference Planner 按景别选 3–6 张：脸部特写 = face + hair + makeup；全身 = Look 上身三视图 + shoes；手部特写 = nails + 袖口；双人镜每人各 1–2 张身份图 + 站位 ControlNet。

### 3.3 衣橱库数据结构（示例）

```json
{
  "wardrobe_item": {
    "id": "WI-CORSET-PATENT-01",
    "slot": "outfit.top",
    "name": "漆皮束腰",
    "refs": [
      {"file": "sha256:…", "view": "front_flat", "role": "garment_shape"},
      {"file": "sha256:…", "view": "detail", "role": "material"},
      {"file": "sha256:…", "view": "on_body_front", "role": "fit", "look": "LW-LOOK-QUEEN"}
    ],
    "attributes": {"color": "黑", "material": "漆皮", "closure": "后系带"},
    "layer": 2,
    "conflicts_with": ["WI-COAT-*"],
    "version": 3,
    "status": "approved"
  }
}
```

---

## 4. Agent 自动识别：每集对应哪些人物资产

### 4.1 两阶段：先确定性解析，再 LLM 补全

你的剧本格式非常规整，**80% 的绑定可以不用 LLM**：

1. **确定性解析器**（正则/语法）：
   - `## epNN《标题》` → Episode；`**镜N｜img**` / `**motion**` / `**sound**` / `**对白**` / `**🎙**` → Shot 字段。
   - `【林晚】` 等角色锁前缀、人名出现 → 角色候选。
   - 装饰状态总表 → 每集 D 状态；`scene_lock` / `decor_lock` 字段 → 直接绑定。
   - 🔴 标记 → 高敏感/高难度镜。
2. **LLM 结构化抽取**（只处理确定性解析无法覆盖的部分）：
   - 代称消解（“她”“男性”“黑色高定衬衫中年男经理” → 顾沉）。
   - 本镜**可见**的单品和身体部位（“低机位仰拍高跟鞋” → shoes visible_required；“极近特写侧脸” → face + hair）。
   - 剧情状态变化（穿上/脱下/戴上/取下）。
   - 每个绑定都必须输出**证据原文片段 + 置信度**，低置信度进入人工确认列表。

成人内容注意：主流托管 LLM 会拒绝或删改露骨文本，导致抽取失败或静默遗漏。本项目 Agent 统一使用 **abliteration.ai API**（见 4.4），本地 Qwen3-VL 仅作离线备份；无论哪个后端，都要检查每镜都有输出，缺失即报错而不是跳过。

### 4.2 抽取输出契约

```json
{
  "ep": "ep01", "shot": "S2",
  "characters": [
    {"character_id": "GU-CHEN", "evidence": "黑色高定衬衫中年男总经理", "confidence": 0.96,
     "look_id": "GC-LOOK-CEO", "visible": ["face", "outfit.top"]},
    {"character_id": "LIN-WAN", "evidence": "蓝发齐刘海女性", "confidence": 0.98,
     "look_id": "LW-LOOK-COMMUTE", "adornment_state": "D0",
     "visible": ["face", "hair", "outfit.top"], "hidden": ["shoes", "nails"]}
  ],
  "scene_id": "SK-ELEVATOR", "camera": "static",
  "state_changes": [],
  "unresolved": []
}
```

### 4.3 冲突检查（锁定前必须清零）

- 装饰状态与剧情冲突（例如 ep17 的 D4 礼服例外是否被正确应用）。
- 镜头要求可见但资产库缺参考图。
- 同一镜同角色出现两种 Look。
- 服装互斥（外套与束腰同时“外层可见”）。
- 角色外观年龄：所有角色必须是明确成年人外观，资产 QC 中加入年龄外观检查（现有负面词已有“未成年人外观”，这里变成硬门槛）。

### 4.4 Agent LLM：abliteration.ai API

文档：https://docs.abliteration.ai/api/introduction

**接口**：Base URL `https://api.abliteration.ai/v1`，`Authorization: Bearer $ABLIT_KEY`。同时兼容 OpenAI SDK（`/v1/chat/completions`、`/v1/responses`、`/v1/models`）和 Anthropic SDK（`/v1/messages`、`/v1/messages/count_tokens`）。改 `base_url` 即可接入，后端可以直接用 OpenAI Python SDK。

**模型（截至 2026-10-29 文档）**：

| 模型 ID | 上下文 | 图片输入 | 价格（USD / 1M tokens，输入 / 缓存输入 / 输出） | 本项目用途 |
|---|---|---|---|---|
| `abliterated-model-large-flash` | 1,048,576 | ✅ | $1.00 / $0.10 / $2.00 | **默认**：剧本解析、资产绑定、提示词编译、图片 QC |
| `abliterated-model` | 262,144 | ✅ | $1.00 / $0.10 / $3.00 | 备选（effort 最高 xhigh） |
| `abliterated-model-large-v2` | 1,000,000 | ❌ 纯文本 | $3.00 / $0.30 / $5.00 | 全剧连续性审查等难推理任务（推理不可关闭） |
| `abliterated-model-large` | 1,000,000 | ❌ | $3.00 / $0.30 / $5.00 | 已弃用，不使用 |

**按任务拆分调用方式**：

| Agent 任务 | 模型 | 调用要点 |
|---|---|---|
| 剧本→分镜结构化、代称消解、可见资产抽取 | large-flash | Chat Completions + `response_format: json_schema`；`reasoning_effort: "low"` 或 `"none"` |
| 全剧连续性/装饰状态冲突审查 | large-flash（或 large-v2） | 1M 上下文可一次放入 60 集剧本 + 资产目录 + 装饰状态表 |
| Qwen 首帧提示词、H3 视频提示词编译（四段式、`<d>` 对白、`<Picture N>` 引用） | large-flash | JSON schema 输出各字段，由代码拼装最终提示词，不让模型直接拼长字符串 |
| 首帧图片 QC（服装/美甲/鞋/装饰是否与参考一致） | large-flash / abliterated-model | **每次请求（含历史）最多 4 张图、单张 ≤12MB**：1 张候选 + 最多 3 张参考；视频不支持，需先抽帧 |
| 异常诊断（失败原因分类 → 选择修复动作） | large-flash | 用 function calling，工具即“换候选/换 seed/拆镜/改参考组”等确定性动作 |

**工程约束**：

- **结构化输出只在 `/v1/chat/completions` 上有文档支持**（`json_object` / `json_schema`）；Responses 和 Messages 接口的兼容表里没有这一项。所以抽取类任务固定走 Chat Completions。文档没提 `strict`，返回结果必须在本地用 Pydantic/JSON Schema 再校验一次，失败重试，最终失败进入异常队列。
- **提示词缓存**：三个接口都支持自动缓存，缓存输入只按十分之一计价。把“系统提示 + 资产目录 + 装饰状态表 + 本集剧本”放在消息前部且保持不变，逐镜变化的内容放在最后，以命中缓存。
- **限流**：按 key 计，Free 60 RPM / 并发 4，Tier 5 900 RPM / 并发 32。调度器给 LLM 单独设令牌桶（与 GPU 队列分开），遵守 `Retry-After`，读取 `x-ratelimit-remaining-*` 提前降速；401/402/403 不重试，直接告警（key 失效或余额不足）。
- **成本量级（估算）**：360 镜逐镜抽取，若每镜约 4k 输入（大部分命中缓存）+ 1k 输出，flash 模型总计在几美元级别；图片 QC 的图片按 token 计费，需以实测账单为准。
- **密钥管理**：`ABLIT_KEY` 只存在于后端密钥管理/环境变量，不进前端、画布、日志、提示词和 Git；按环境（开发/生产）分 key，可用其管理接口设置花费上限。
- **数据与合规**：文档未说明请求数据的保留和日志策略。上传的人脸、身体参考图属于敏感数据，只发送 QC 必需的裁切图，接入前阅读其服务条款与隐私政策。平台“基础防护”的范围文档也未说明，所以不能假设所有内容都会被放行——抽取结果缺失或被拒时要能识别并报警。
- **版本锁定**：每次调用把模型 ID、`reasoning_effort`、提示词模板版本和 `request_id` 写入生成血缘。弃用会提前至少 30 天在 release notes 通知，模型切换前需要用金标剧本跑回归。
- **离线备份**：保留本地 Qwen3-VL 作为降级路径，接口抽象成同一个 `LLMProvider`，API 不可用时 Agent 不阻断生产。

---

## 5. 创作页设计

### 5.1 页面布局

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│ 项目: 为他而骚 │ ep01 ▾ │ 资产包 v3 🔒 │ 9:16 │ 档位: T0预演 ▾ │ 预算 ¥…/GPU·h … │ [锁定资产] [开始生产] │
├────────────┬──────────────────────────────────────────────────┬──────────────────┤
│ 剧集树      │  [剧本分镜] [资产衣橱] [画布] [渲染农场] [异常队列]   │ 检查器            │
│ ▾ ep01 ●●●○ │                                                  │                  │
│   S1 ✅     │  （中央工作区，按标签切换，见 5.2–5.5）              │ 当前选中对象的     │
│   S2 ⏳     │                                                  │ 属性/版本/引用影响 │
│   S3 ⚠️     │                                                  │                  │
│ ▸ ep02      │                                                  │ Agent 绑定证据     │
│ 筛选:       │                                                  │ 置信度/待确认      │
│ ☐缺资产     │                                                  │                  │
│ ☐冲突      │                                                  │ GPU/队列状态       │
│ ☐QC失败    │                                                  │                  │
└────────────┴──────────────────────────────────────────────────┴──────────────────┘
```

### 5.2 标签一：剧本分镜

- 粘贴或导入现有 Markdown（三份 v2 文件直接导入），原文作只读快照。
- 表格每行一镜：img / motion / camera / sound / 对白 / 🎙 / 时长 / 角色 / Look / 装饰状态 / 场景 / 可见资产 / 档位。
- 角色列显示头像缩略图——错绑一眼可见。
- `@林晚` `@SK-ELEVATOR` `@WI-CORSET` 引用资产，落为真实 ID。
- **TTS 预演按钮**：先用固定音色把独白/对白念一遍，按真实音频时长标红超时镜。

### 5.3 标签二：资产衣橱

- 左栏分类：人物 / Look / 服装 / 鞋 / 美甲 / 发型 / 妆面 / 身材 / 装饰状态 / 场景 / 道具。
- 中间网格：拖拽上传、批量上传；上传后自动：去背景（Qwen Remove Background 模板）、裁切建议、视角/部位标签、质量检查（分辨率、模糊、遮挡）。
- 每个单品卡：参考图组、属性标签、版本、被多少镜头引用、是否锁定。
- **“补全参考”按钮**：按 3.2 表的配方调用 Qwen Base / AnyAngle / ControlNet 生成缺失视角，结果作为候选，必须人工批准。
- **“试穿”**：选人物 Look + 若干单品 → Qwen Edit 多参考生成上身三视图 → 并排比较 → 批准为 Look 的一部分。
- 装饰状态时间轴：横轴 ep01–ep60，纵轴 D 状态，直接编辑装饰状态总表。

### 5.4 标签三：画布（剧本 + 图片）

建议用 React Flow（`@xyflow/react`）实现节点画布，节点就是资产和镜头，连线就是引用：

- **资产节点**：Character → Look → 各单品；场景 → 机位。
- **镜头节点**：显示首帧候选、选中帧、视频预览、QC 徽章。
- **连线 = 参考关系**，线上标注顺序和职责（`Picture 1: 身份`、`Picture 2: 服装`）。拖一条线就是给镜头加参考，Reference Planner 的自动选择也画成线，可手动改。
- **镜头链**：上一镜尾帧 → 下一镜首帧的连续性连线（需要时）。
- 每集一个画布分组，可折叠；画布状态存数据库（不是 localStorage），多人协作时可见同一版本。

### 5.5 标签四：渲染农场

- GPU 卡片墙：每张卡显示当前常驻模型（Qwen / H3-FL2VA / H3-Ref2VA / QC）、显存、当前任务、队列长度。
- 任务队列：按档位（T0/T1/T2）、集、优先级筛选；可暂停/提升某集。
- 吞吐与成本：每镜 GPU 秒、重试次数、预计完成时间（基于实测速率，不是估算常数）。
- 熔断状态：某个模型/配方连续失败时自动停用并在这里显示。

### 5.6 标签五：异常队列

每条异常给明确动作：换候选 / 修资产 / 改镜头 / 拆镜 / 降级到其他模型 / 阻断该集导出。

### 5.7 技术栈建议

| 层 | 选择 | 理由 |
|---|---|---|
| 前端 | Next.js + React + `@xyflow/react`（画布）+ TanStack Table（分镜表） | 画布与大表格都有成熟组件 |
| 后端 API | Python FastAPI | 与 ComfyUI、模型工具链同语言 |
| Agent LLM | abliteration.ai（OpenAI SDK，`base_url=https://api.abliteration.ai/v1`），默认 `abliterated-model-large-flash` | 见 4.4 |
| 工作流 | Temporal | 长任务、重试、崩溃恢复（原设计已选） |
| 数据 | PostgreSQL（真相）+ MinIO/S3（文件）+ Redis（队列/缓存） | |
| 渲染执行 | headless ComfyUI（`POST /prompt`、`GET /history/{id}`、`/ws` 进度） | 工作流 JSON 模板化，参数由后端注入 |
| 实时推送 | WebSocket（后端转发 ComfyUI 进度到前端） | 渲染农场与镜头卡实时更新 |

---

## 6. 多 GPU 渲染阵列

### 6.1 基本形态：每卡一个 ComfyUI，模型常驻

```
                  ┌────────────────────────────┐
  Temporal 工作流 ─►│  调度器 (Render Router)      │
                  │  - 按模型亲和选卡              │
                  │  - 按档位/优先级排队            │
                  └──┬──────────┬──────────┬───┘
                     │          │          │
        ┌────────────▼┐  ┌──────▼─────┐  ┌─▼───────────┐
        │ Qwen 池       │  │ H3-FL2VA 池 │  │ H3-Ref2VA 池  │   + QC 池 + 后期(CPU/NVENC)
        │ GPU0 ComfyUI  │  │ GPU2 ComfyUI│  │ GPU5 ComfyUI │
        │ GPU1 ComfyUI  │  │ GPU3 ComfyUI│  │ (FastH3/实验)  │
        │ 常驻 Qwen     │  │ GPU4 ComfyUI│  │              │
        └──────────────┘  └────────────┘  └──────────────┘
```

- 每张卡一个 ComfyUI 进程：`python main.py --listen --port 8188+N --cuda-device N`（或 `CUDA_VISIBLE_DEVICES=N`）。
- **模型亲和**是吞吐的关键：H3 文本编码器是 Qwen3-VL-32B、DiT 33B，切换模型的加载时间可能比生成还长。调度器只把 FL2VA 任务发给常驻 FL2VA 的卡；池子大小按队列长度动态调整，但调整频率要低（按小时，不按任务）。
- 每个 worker 启动后先跑一次预热任务，再注册到调度器。
- 同一集的 6 镜可以分发到不同卡并行，前提是锁定了同一资产版本、同一工作流版本、同一 checkpoint 哈希（原设计已论证：一致性来自版本锁定，不来自串行）。

### 6.2 显存与硬件分档（需实测）

模型卡均**未公布完整工作流峰值显存**。已知信息：

- H3：33B 参数，其中约 13B AdaLN 可预计算；社区 NVFP4 量化 DiT 文件约 11.9GB（仅 Blackwell 原生）；ComfyUI 可把放不下的部分流式卸载（以速度为代价）。
- FastH3 编码器有 nvfp4（仅 Blackwell）/ int8 / bf16 三档；FastVideo 列出的支持硬件：GB200/B200、RTX PRO 6000 Blackwell、H100/H200、DGX Spark、RTX 5090（32GB）；有 RTX 4090 的 FP8 + 分层卸载方案。

建议的 POC 硬件分档：

| 档 | 卡 | 用途假设 |
|---|---|---|
| A | H100/H200 80GB+ 或 RTX PRO 6000 96GB | H3 FL2VA 正式档，int8/bf16，少卸载 |
| B | RTX 5090 32GB | Qwen Turbo 首帧、FastH3 预演（int8/nvfp4 + 卸载） |
| C | RTX 4090 24GB | Qwen、QC、RefMod 构建；H3 仅在 FP8+卸载可行时使用 |

每个档必须实测：冷启动、5/10/15 秒、9:16、480p/768p、单任务峰值显存、主机内存、每镜耗时。

### 6.3 单任务多卡

- ComfyUI 原生路线以单卡为主。单个 H3 任务跨多卡（Ulysses 序列并行）的官方示例在 **SGLang**；FastVideo 提供 **UniServe** 运行时。
- 何时需要：单镜延迟是瓶颈（如需要快速返工某一镜）。对批量生产而言，**多卡各跑一镜的总吞吐通常更好**，所以默认不做单任务多卡。
- 如果引入 SGLang/UniServe 作为第二后端：它们与 ComfyUI 输出会有差异（FastH3 模型卡明确说明），所以同一集内不要混用后端。

### 6.4 调度策略

- 队列优先级：T0 预演 > 异常重试 > T1 正式 > T2 精修（预演要快速反馈创作）。
- 云端 API（若用于非敏感镜对照）有独立令牌桶，不占本地 GPU。
- 规模到多节点后，再按原设计引入 Kubernetes + Kueue；单机 8 卡阶段用 Temporal + Redis 队列足够。

---

## 7. POC 计划（2 周）

### 7.1 测试镜头（取自现有剧本）

ep01-S1（低机位高跟鞋上摇——鞋+全身+脸）、ep01-S2（电梯双人+金属倒影）、ep01-S3（极近特写）、ep01-S6（暗场眼部特写）、ep06（妆面变化）、ep21（高密度装饰）、ep28（漆皮束腰上身）、ep59（多场景）。共 12–18 镜。

### 7.2 对比矩阵

| 实验 | 变量 | 指标 |
|---|---|---|
| 首帧 | Qwen Base vs Turbo vs Base+TurboLoRA；参考图 2/4/6/10 张 | 人脸相似度、单品保真、耗时 |
| 转面 | AnyAngle（base 20 步 vs turbo）+ 脸部修复 | 崩脸率、身份保持 |
| 场景多机位 | AnyAngle + Trellis2 vs Tripo Splat | 空间一致性 |
| 视频主路径 | H3 FL2VA 原版 vs 10Eros-Max（若确认为 I2V/FL2VA 血统） | 首帧保持、身份漂移、动作、音频 |
| 参考路径 | 原版 Ref2VA vs FastH3-Omni vs Singularity vs PRISM 合并 | 同上 + 速度 |
| 提速 | 直接 768p vs SelfLift(+TST) vs 2-pass latent 放大 | 闪烁、细节、耗时 |
| 角色打包 | 无 RefMod vs Full RefMod vs `.char`，在**每个**候选 checkpoint 上 | 身份、串扰 |

所有实验固定 seed、固定工作流哈希，结果进入金标集，作为后续节点升级的回归基线。

### 7.3 通过门

- 资产锁定后，ep01 的 6 镜在 T0 → T1 全自动跑通，无需逐镜人工操作。
- 未通过镜头正确进入异常队列并给出原因。
- 得到每档每镜的实测 GPU 秒，替换本文所有“需实测”项。

---

## 8. 风险与许可清单

| 风险 | 严重度 | 对策 |
|---|---|---|
| Qwen 2.1 仅研究许可，本地生产不能商用 | 🔴 高 | 先联系阿里获取商用授权；未解决前项目定位为研究/内部 |
| H3 许可排除美/欧/英/韩地区 | 🔴 高 | 确认公司主体与发行地域；法务评估 |
| PRISM 合并/10Eros/Singularity 许可链不可审计 | 🟠 中 | 仅实验；产物标记来源 checkpoint，可替换 |
| SelfLift 无许可证声明 | 🟠 中 | 联系作者或自行实现等效逻辑 |
| 成人内容被云端图片/视频 API 拒绝 | 🟠 中 | 图片/视频主链路全本地 |
| Agent LLM（abliteration.ai）的数据保留策略未公开、图片每请求限 4 张 | 🟠 中 | 只发必要裁切图；QC 分批；本地 Qwen3-VL 做降级；抽取结果做完整性检查 |
| 发行平台对成人内容的规则 | 🔴 高 | 量产前确认目标渠道；平台审查独立于模型能力 |
| 快模型只有 Ref2VA，首帧不能硬锁 | 🟠 中 | 两档路由；正式档用 FL2VA |
| MiniMaxH3Mod 节点接口仍在变 | 🟡 低 | 固定 commit，升级前跑金标回归 |
| 社区模型无评测数据 | 🟡 低 | 一切以自己的金标集为准 |
| 真人肖像/声音授权 | 🔴 高 | 上传时记录授权；禁止未经同意仿冒真人（H3 许可也禁止） |

---

## 9. 来源

- Comfy-Org/Qwen-Image-2.1：https://huggingface.co/Comfy-Org/Qwen-Image-2.1
- Qwen/Qwen-Image-2.1：https://huggingface.co/Qwen/Qwen-Image-2.1
- lilylilith/QI_2.1_AnyAngle：https://huggingface.co/lilylilith/QI_2.1_AnyAngle
- FastVideo/FastH3-Omni-Comfy：https://huggingface.co/FastVideo/FastH3-Omni-Comfy
- FastVideo/FastVideo-FastH3-Omni-8-Step-V1：https://huggingface.co/FastVideo/FastVideo-FastH3-Omni-8-Step-V1
- MiniMaxAI/MiniMax-H3：https://huggingface.co/MiniMaxAI/MiniMax-H3 （LICENSE：https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/LICENSE）
- facok/comfyui-SelfLift：https://github.com/facok/comfyui-SelfLift
- LBH-123-AI/Minimax_h3_latent_Upscaler：https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler
- OliviaRossi/Minimax-h3_Singularity-x-10Eros-Max_PRISM：https://huggingface.co/OliviaRossi/Minimax-h3_Singularity-x-10Eros-Max_PRISM
- TenStrip/10Eros-Max：https://huggingface.co/TenStrip/10Eros-Max
- WarmBloodAban/Minimax-h3_Singularity：https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity
- omnichar/ComfyUI-Omnichar：https://github.com/omnichar/ComfyUI-Omnichar
- Luisacaotica/ComfyUI-MiniMaxH3Mod：https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod
- abliteration.ai API：https://docs.abliteration.ai/api/introduction （模型 /models.md、价格 /pricing.md、限流 /api/rate-limits.md、兼容矩阵 /compatibility-matrix.md、图片 /capabilities/images.md）
- ComfyUI H3 教程（社区）：https://comfyui-wiki.com/en/tutorial/advanced/video/minimax/minimax-h3
- H3 社区量化（显存参考）：https://huggingface.co/lilcheaty/MiniMax-H3-NVFP4 、https://huggingface.co/DmitryDB/MiniMax-H3-ComfyUI-Quants
