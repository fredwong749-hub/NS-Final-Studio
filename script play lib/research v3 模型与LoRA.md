# NS-Final Studio · 调研 v3：按剧本需求选模型与 LoRA

> 日期：2026-10-29。在 `design v2 research.md` 的基础上，先从剧本抽取视觉需求，再到 Hugging Face / Civitai 找对应的底模和 LoRA。
> 数字（下载量、日期）为当天抓取值；“效果”均为作者自述，**没有任何一项经过我们自己的测试**，最终以 gpu3 上的金标镜头 A/B 为准。

---

## 0. 结论

1. **图片端不缺“无审查”**：社区实测 Qwen Image 2.1 原版几乎不拒绝，但 NSFW 场景身体结构错误明显增多。NoctQ V4（Qwen 2.1 无审查合并模型）已在 gpu3 上，是旧系统的默认关键帧模型。
2. **视频端主力候选是 10Eros-Max**：它是 H3 的 FL2VA 微调（只改了 0–31 层的 QKV），beta7 是一天前刚发布的 8 步 Turbo 版。再配合 Mystic XXX v5（同时支持 FL2VA 和 Ref2VA）等 LoRA。PRISM 合并版是 Ref2VA，只适合参考生视频的镜头。
3. **全剧最难的元素没有现成 LoRA**：乳环、阴环、九串铁珠、舌钉、曼陀罗/黑蛇/“沉”字纹身——在 Qwen 2.1 和 H3 上都搜不到对应 LoRA。这些必须**自己训练**，或者用“首帧编辑 + FL2VA 首帧锁定”来保证。
4. **剧本最露骨的段落本来就多用剪影和局部裁切**（剪影 67 处、含蓄/裁切 17 处）。所以模型选择的重点是**饰品与服装一致性 + 写实质感 + 中文口型**，而不是露骨程度本身。
5. **gpu3 只有 3 张可用的 3090**：Ampere 架构不支持 NVFP4/FP8，所以只能用 INT8 或 w4a8，并卸载到 503GB 内存。H3 的 LoRA 训练在 24GB 卡上能否进行没有公开数据，大概率需要租用 80GB 卡。

---

## 1. 剧本视觉需求（全文 60 集统计）

| 类别 | 关键词出现次数 | 生成难点 |
|---|---|---|
| 身体饰品 | 铁珠 87、珠链 35、乳环 43、舌钉 26、阴环 14 | 数量与位置要跨镜头一致（D0–D10 状态表，如“九串，左 5 右 4”），金属反光，晃动物理，碰撞声 |
| 材质 / 服装 | 漆皮 80、束腰 51、风衣 53、高跟 47、丁字裤 31、黑丝 17、背羽 7 | 漆皮高光、束腰版型、丝袜质感 |
| 纹身 | 纹身 39、曼陀罗 21、黑蛇 14、“沉”字 | 图案固定；汉字要渲染正确 |
| 人物 | 蓝发 24、齐刘海 20；男角色 顾沉 / 陈宇 / Alex / Ryan / Kai / Leo | 女主身份一致；多人同框时身份不串 |
| 景别 | 特写 121、极近 29、双人 31、三人 15 | 皮肤质感、塑料感、面部细节 |
| 运镜 | slow motion 90、push in 85、static 82、handheld 38、orbit 10 | 慢动作不要“假慢”、推镜稳定 |
| 光线 / 场景 | 暗 64、剪影 67、浴 31、床 49、电梯 41、手机 86 | 暗场噪点、剪影轮廓、手机屏幕内容 |
| 情绪 | 泪 34、汗 14 | 泪痕、湿发 |
| 声音 | 独白 🎙 189、对白 182、铁珠碰撞声 | 中文口型；独白时嘴唇闭合 |

---

## 2. 图片端（定妆、资产、首帧）

### 2.1 底模

| 模型 | 状态 | 适用 | 备注 |
|---|---|---|---|
| Qwen Image 2.1 Base / Turbo（Comfy-Org int8） | gpu3 已有 | 资产母版、多参考编辑、AnyAngle 转面 | 社区称原版基本不拒绝；NSFW 时身体结构错误增多 |
| **NoctQ V4（Noct-Q-Uncensored-Qwen-Image-2.1）** | gpu3 已有（int8） | 涉及裸露 / 饰品的首帧 | 旧系统设置：25 步、CFG 2.5、er_sde/beta、可用负面提示词。许可 qwen-research |
| abenzerps/Qwen-Image-2.1-Uncensored-Quantized | 未下载 | 对照 | 来源可追溯（固定 commit + SHA256）；声称无内置安全过滤 |
| AtomicChat Qwen-2.1-Turbo-Uncensored | 不推荐 | — | 只改了文本编码器；作者自测文字拒答大幅下降，但**图像无变化** |

### 2.2 Qwen 2.1 LoRA（按剧本需求）

| 需求 | LoRA | Civitai ID | 设置 | 状态 |
|---|---|---|---|---|
| 通用 NSFW 解剖 | NSFW LORA \| Qwen Image 2.1 | 2958918 | 0.8–1.0，25+ 步，CFG 3–6，er_sde/beta | 未下载 |
| 女性解剖细节 | FemaledVaginus-NSFW v1.3 | 2986844 | 0.7–1.0，CFG 3，20 步 | gpu3 已有 |
| 漆皮 / 束腰 / 金属 / 皮具 | BDSM Leather/Metal/Latex Gear Megapack | 2992770 | 0.9–1.2 | gpu3 已有（latex_megapack_qwen21） |
| 黑丝 | RealStockings | 2463208 | 0.7，强度高时会糊脸 | 未下载 |
| 亚洲面孔 | [Qwen Image] Asian Mix Lora | 1905553 | ≤0.8，触发词 “asian woman” | 未下载 |
| 写实质感 | NiceGirls UltraReal / Lenovo UltraReal | 1862761 / 1662740 | 约 0.6 / 1.5–2.0 | glamour_realism、film_texture 已有类似 |
| 编辑时不跑位 | Qwen Image 2.1 Consistency LoRA | 2969143 | 1.0，仅编辑；测过 8 步 Turbo | 未下载，**改服装/饰品时很关键** |
| 换装一致性 | Qwen Image 2.1 Outfit Swap Consistency LoRA | 搜索列表中出现，详情待查 | — | 待核实 |
| 角色设定图 | [Qwen Image 2.1] Character Design Sheet Maker（工作流） | — | — | 用于定妆三视图 |
| 转角度 | lilylilith/QI_2.1_AnyAngle | HF | 强度 1，CFG 3，20+ 步 | 未下载 |

注意：Qwen-Image 1.0 / 2512 的 LoRA（20B 架构）**不能用于 2.1**（7B 新架构）。例如 “BFS Best Face Swap” 标注的是 Qwen Image Edit 2509，不适用。

---

## 3. 视频端（H3）

### 3.1 底模

| 模型 | 模式 | 状态 | 说明 |
|---|---|---|---|
| MiniMax-H3 FL2VA int8（Comfy-Org） | FL2VA | gpu3 已有 | 基线 |
| **10Eros-Max**（TenStrip） | FL2VA（Turbo 系列为 “shifted base”） | 未下载 | beta7 8 步 Turbo（`8stepTURBO_beta7_int8HQ` 22.9GB，一天前发布）为推荐版本；另有 fl2va_beta2、ref2va_beta2、hybrid_beta5。只改 0–31 层 QKV。单次采样易闪烁，建议两段式；参考工作流禁用 cache。许可链含 LTX 2.3 / Wan 2.2 / Krea 2 成分 |
| DmitryDB/MiniMax-H3-10Eros-Max-Quants | FL2VA | 未下载 | INT8 ConvRot 20.9GB，标注适合 24GB / RTX 30·40；**只验证了转换精度，没测画面** |
| PRISM（Singularity × 10Eros） | Ref2VA | 旧系统正在下载 | 无评测，许可链不清 |
| Singularity v2（WarmBloodAban） | Ref2VA | 未下载 | 作者称中远景脸更稳、皮肤油光更少 |
| FastH3-Omni 8 步 | Ref2VA | 未下载 | 预演档 |

### 3.2 H3 LoRA（按剧本需求）

| 需求 | LoRA | 来源 | 设置 | 状态 |
|---|---|---|---|---|
| 解剖 + 写实（主力） | **[MMH3] Mystic XXX v5**（FL2VA & Ref2VA 双版本） | Civitai 2856467，12.8 万下载，10-19 更新 | 0.2–1；Turbo LoRA 会改变观感 | gpu3 有 V4，**建议升级到 v5** |
| 裸露 / 露骨 | MiniMax H3 NSFW Unlocked V2.1 | Civitai 2925727 | 0.3–1，从 0.5 起；配 4–8 步 Turbo | gpu3 已有 |
| 性行为动作 | HMNSFW AIO V2.5 | Civitai 2834417 | 0.5–0.9；Turbo 0.5 | gpu3 已有 |
| 胸部细节 | Polyhedron: Breasts & Nipples | Civitai 2913543 | 低权重 | 未下载 |
| 束腰领口 | Polyhedron: Deep Cleavage (Corsets) | Civitai 2930745 | — | 未下载 |
| 漆皮服装 | Latex clothes Minimax H3 | Civitai 2985007 | 触发词 latex | 未下载 |
| 黑丝 | Stockings_wearing_MiniMax-H3 | Civitai 3012696 | — | 未下载 |
| 人物写实 | fal/MiniMax-H3-Realism-People-LoRA | HF | 1.0（0.6–0.8 减弱），触发词 r34l1sm | gpu3 已有 |
| 去塑料感 / 电影质感 | Minimax H3 Cinematic V2 / Cinematic Official | Civitai 2890588 / 2937713 | 0.85 / 0.7（大动作 0.5） | 未下载 |
| 慢动作 / 肢体修复 | JOKER141 General-Motion-Continuity-Repair | HF | 单独用 0.9；第二阶段 0.2–0.3 | 未下载；针对“假慢动作”“动作缺失” |
| 运镜 | Jojocodex/minimax-h3-Camera-Motion-lora、pablodawson 360-Orbit | HF | — | 未下载；对应 push in / orbit |
| 换人 / 身份修正 | akatz-ai Character-Swap v1.5（Ref2VA） | HF | 1.0 + 8 步 Turbo，er_sde | gpu3 有 v1，可升级 |
| 加速 | FL2V/Ref2V Turbo 4/8 步、DMAD 4 步、LMS | — | — | gpu3 已有 |
| 2K | Open-H3-Regenerate-2K refiner + latent upscaler + SelfLift | HF | 3 步 Euler，CFG 1 | gpu3 已有 |
| 防过饱和 | Imagineer13/H3-Anti-Burn-LoRA | HF | — | 未下载 |

### 3.3 中文口型与声音

- 没找到中文口型 LoRA。`natural-face-speech-h3-lora` 只标注英文。
- Civitai 上有两个 H3 口型工作流（2935228 Nova_v2 可选中文音频编码器；2876401 基于 Ref2VA）。可以测试“TTS 音频作为 `<Audio 1>` → Ref2VA 对口型”这条路线。
- 189 处独白的“嘴唇闭合”主要靠提示词（H3 官方提示词规范），不需要 LoRA。

### 3.4 文本编码器“去审查”：不需要

H3 的 Qwen3-VL-32B 有社区去审查（abliterated）版本（pottokao），但作者没有给出任何效果数据。类似做法在 Qwen 2.1 上的测试结果是：文字拒答下降，**图像没有变化**。扩散模型的文本编码器不会“拒答”，真正决定能画什么的是 DiT 权重和 LoRA。所以不建议替换编码器。

---

## 4. 缺口：必须自己训练的 LoRA

| LoRA | 用途 | 训练数据来源 | 底模 |
|---|---|---|---|
| 林晚身份 | 全剧女主一致 | 你提供的 2 张图 → Qwen 编辑 + AnyAngle 生成 20–40 张多角度/多景别 → 人工筛选 | Qwen 2.1；H3（可选） |
| 饰品 D 状态（乳环、阴环 ×9、铁珠串、舌钉） | 数量、位置、材质一致 | 先用 Qwen 编辑 + 局部重绘逐张做“正确”的参考图，人工核对数量 | Qwen 2.1 为主 |
| 纹身（曼陀罗、黑蛇 +“沉”字） | 图案一致 | 设计稿 + 上身贴图 | Qwen 2.1（汉字渲染是 Qwen 的强项，也可以不训练，直接编辑首帧） |
| 男角色身份（顾沉 / 陈宇 / Alex…） | 多人戏不串脸 | 生成定妆照后同上 | Qwen 2.1 |

**训练工具**：
- ai-toolkit（ostris）自 2026-08-03 起内置 `minimax_h3` 扩展，支持 FL2VA / Ref2VA 的 T2V、I2V LoRA；社区经验是 50–200 段带字幕的短视频。
- Qwen 系列 LoRA 可以用 ai-toolkit 或 musubi-tuner 训练，但**是否支持 Qwen 2.1 还没找到明确资料**，需要核实。
- **显存**：Qwen-Image 系列在 24GB 卡上训练 LoRA 很紧张（低显存模式 + 缓存文本嵌入）；H3（33B）在 24GB 卡上没有公开数据，NVFP4 训练优化只在 Blackwell 上有效。**建议图片 LoRA 在 gpu3 上试训，H3 LoRA 租用 80GB 卡训练。**

**策略**：视频端的饰品一致性优先靠 **FL2VA 首帧锁定**（首帧里饰品是对的，H3 就从这一帧开始动），再加 QC 抽帧检查。只有当 QC 发现饰品在动作中频繁丢失时，才训练 H3 饰品 LoRA。

---

## 5. 在 gpu3（3 × 3090）上的推荐组合（待 A/B 验证）

| 环节 | 默认组合 | 对照组 |
|---|---|---|
| 林晚定妆 / 资产 | Qwen 2.1 Base + 林晚参考图（多参考编辑）+ AnyAngle + Consistency LoRA | NoctQ V4 |
| 首帧（日常戏） | Qwen 2.1 Turbo + Asian Mix + 写实 LoRA | NoctQ V4 |
| 首帧（裸露 / 饰品戏） | NoctQ V4 + Latex Megapack / RealStockings + 自训饰品 LoRA | Qwen 2.1 + NSFW LORA 2958918 |
| 视频（日常戏） | H3 FL2VA int8 + Realism-People + Cinematic V2 + 8 步 Turbo | 10Eros beta7 |
| 视频（成人戏） | 10Eros-Max beta7 int8 + Mystic XXX v5（低权重起）+ Motion Repair | H3 FL2VA + NSFW Unlocked V2.1 + HMNSFW |
| 多人参考镜 | Ref2VA + Character-Swap v1.5 / PRISM | FastH3-Omni |
| 精修 | latent upscaler 两段式 → Open-H3-Regenerate-2K | SelfLift |

**金标测试镜头**：ep01-S1（高跟上摇）、ep03（电梯吻）、ep05（漆皮束腰）、ep09（乳环）、ep21（九串铁珠）、ep27（黑蛇 +“沉”字纹身）、ep29（舌钉）、ep30（黑丝）、ep38（剪影三人）、ep59（多场景）。

**吞吐估算（未实测，仅量级）**：旧系统实测 576×1024、124 帧、20 步单段 561.6 秒。按 8 步 Turbo 粗估每段 4–6 分钟；360 镜 × 1.4 次尝试 ÷ 3 卡，约 12–20 小时跑一遍全剧（768×1344 会更慢）。

---

## 6. 许可提醒

- Qwen 2.1 / NoctQ：qwen-research（非商用）。
- H3 及所有衍生模型、LoRA：MiniMax H3 社区许可（排除美 / 欧 / 英 / 韩）。
- 10Eros 还附带 LTX 2.3 / Wan 2.2 / Krea 2 的许可；Civitai LoRA 各有许可，部分禁止衍生或商用。
- 所有下载记录来源 URL、版本和 SHA256，进入许可审计表（旧系统已有 `config/model_licenses.json` 可参照）。

---

## 7. 来源

- Hugging Face 模型搜索：https://huggingface.co/api/models?search=minimax-h3
- TenStrip/10Eros-Max：https://huggingface.co/TenStrip/10Eros-Max
- DmitryDB/MiniMax-H3-10Eros-Max-Quants：https://huggingface.co/DmitryDB/MiniMax-H3-10Eros-Max-Quants
- fal/MiniMax-H3-Realism-People-LoRA：https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA
- akatz-ai/MiniMax-H3-Character-Swap-LoRA：https://huggingface.co/akatz-ai/MiniMax-H3-Character-Swap-LoRA
- Efficient-Large-Model/Open-H3-Regenerate-2K：https://huggingface.co/Efficient-Large-Model/Open-H3-Regenerate-2K
- JOKER141/MiniMax-H3-General-Motion-Continuity-Repair：https://huggingface.co/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair
- alibaba-pai/MiniMax-H3-Fun-Controlnet-Union-2.0：https://huggingface.co/alibaba-pai/MiniMax-H3-Fun-Controlnet-Union-2.0
- TaoLiveAIGC/TaoMate-H3：https://huggingface.co/TaoLiveAIGC/TaoMate-H3
- pottokao 去审查编码器：https://huggingface.co/pottokao/MiniMax-H3-TextEncoder-Qwen3VL-32B-abliterated-GGUF
- vpakarinen/natural-face-speech-h3-lora：https://huggingface.co/vpakarinen/natural-face-speech-h3-lora
- Noctaluna/Noct-Q：https://huggingface.co/Noctaluna/Noct-Q-Uncensored-Qwen-Image-2.1
- Qwen 2.1 无审查构建综述：https://www.orcarouter.ai/blog/qwen-image-2-1-uncensored
- H3 本地部署与审查分析：https://kingy.ai/blog/can-minimax-h3-generate-uncensored-video-what-local-deployment-actually-changes/
- Civitai API 查询：https://civitai.com/api/v1/models （baseModels = MiniMax H3 / Qwen 2.1；关键词 piercing、latex、tattoo、asian、stockings、nipple、jewelry、corset、cinematic、lip sync）
- ai-toolkit H3 训练支持：https://comfyui-wiki.com/en/news/2026-08-03-ai-toolkit-minimax-h3-training
