# 调研链接覆盖与采纳审计（MiniMax H3 / 加速 / 质感 / 一致性）

> 2026-10-31，只读审计（没有改代码、没有动 git、没有抓新网页）。
> 回答项目方的问题：“我给的 MiniMax 相关链接有没有做 deep research，有没有用上？”
>
> **扫描范围**
> - 仓库文档：`docs/research/**`、`docs/research_adoption.md`、`docs/REQUIREMENTS.md`、`docs/TASKS.md`、`docs/SOP_parameters.md`、`docs/upscale_4k.md`、`docs/gpu_speedups.md`、`docs/intimate_audio.md`、`script play lib/design v2 research.md`、`research v3–v9`。
> - Claude 记忆目录：只有方法类笔记 `deep-research-method.md`，里面没有链接。
> - 本机所有 Claude 会话记录（`~/.claude/projects/*/*.jsonl`）：用来找项目方**亲手发的**链接，以及只在会话里出现、没写进仓库的调研报告。
>
> **现状对照的两条链**
> - **画布链**：笔记本 `services/render_router/ns_render/{frame_edit.py,h3_video.py,workflows.py}`，加后期 `services/post/ns_post`。
> - **gpu3 批量链**：`weita_render.py` / `weita_series.py` / `upscale_4k.py`。状态以 `docs/research_adoption.md`（2026-10-30）为准，本次没有登录 gpu3 复核。
>
> **状态写法**：✅ 已用 · ◐ 部分（只在一条链 / 默认关 / 只告警）· ✗ 未用 · ⊘ 调研后决定不用 · — 不适用（背景资料）

---

## 0. 结论先行

1. **项目方亲手发的模型链接只找到 1 批，共 5 个**（2026-10-29 13:34，同一段话发给了两个会话），另有 1 个 gpu-unlock 链接（10-30）。它们分别是：
   - Comfy-Org/Qwen-Image-2.1
   - facok/comfyui-SelfLift
   - FastVideo/FastH3-Omni-Comfy
   - OliviaRossi/…PRISM
   - lilylilith/QI_2.1_AnyAngle

   这 5 个都在 `script play lib/design v2 research.md` §1.2–1.7 里调研过，但都**没有进入 `docs/research/h3_deep/` 的社区实测深挖**。除 Qwen-Image-2.1 以外，**全部没有用上**。

   本机会话记录里找不到“加速 LoRA / 质感 / 衔接”的其他链接。如果项目方是在手机或网页版 claude.ai 上发的，那部分本机看不到，需要项目方补发。
2. **h3_deep 深挖（10-30）覆盖面足够**：官方、LightX2V 加速、ComfyUI 社区，约 120 个来源。加速与参数类结论已在**两条链都落地**：int8 pruned、8step v1.1 768p、shift 6/3、euler 8 步、768×1344、首尾帧同裁切、禁用有损缓存。
3. **缺口一：10-29 kimi 会话的 3 份调研报告没有写进仓库。** 报告时间是 08:55、10:40、14:24，下表标为“kimi-0829 报告”。里面约 30 个链接只存在于会话记录里，`research_adoption.md` 也没有收录。其中几条正好是“质感”类：
   - H3-FaceRefine
   - VBVR LoRA
   - LMS sharpness LoRA
   - Singularity V2
   - LightX2V v1.2 / v1.3 对比
   - Combined Image+Ref 节点
4. **缺口二：质感与一致性类调研结论基本都停在“待 A/B”。** 画布链目前**不挂任何视频质感或身份 LoRA**：`config/auto_lora_triggers.json` 里只有 1 条 image LoRA，没有 video LoRA。逐镜校色默认关。写实精修（texture-fix VAE + purelens）只在批量工具里，画布不调用。4K SeedVR2 只在 gpu3。

---

## 1. 项目方亲手发的链接（原话出处）

| # | 链接 | 发送时间 / 会话 | 原话 |
|---|---|---|---|
| O1 | https://huggingface.co/Comfy-Org/Qwen-Image-2.1 | 10-29 13:34（C--Users-fredw 62b016b8）＋13:36（kimi 7785c2ec） | “模型可以research …” / “你research这些模型,看看能不能修复” |
| O2 | https://github.com/facok/comfyui-SelfLift | 同上（原文重复粘贴 3 次） | 同上 |
| O3 | https://huggingface.co/FastVideo/FastH3-Omni-Comfy | 同上 | 同上 |
| O4 | http://huggingface.co/OliviaRossi/Minimax-h3_Singularity-x-10Eros-Max_PRISM | 同上 | 同上 |
| O5 | https://huggingface.co/lilylilith/QI_2.1_AnyAngle | 同上 | 同上 |
| O6 | https://github.com/Zagitta/gpu-unlock | 10-30 02:22（kimi） | “你是采取这个吗?” → 之后“批准安装 gpu-unlock” |

另有几条 abliteration / deepseek API 地址，属于写作 LLM，不在本审计范围。

**O1–O5 的去向**：
- 研究记录：`design v2 research.md` §1.2–1.7、§9。
- 10-29 14:24 kimi 报告（未入库）进一步指出：PRISM、Singularity、FastH3-Omni 都是 **Ref2VA 系**，首帧锁定弱。joeygambino 实测关键帧保真度 FL2VA 26.35 dB，Ref2VA 只有 16.15 dB。所以这几个不适合当我们“首帧 → 视频”的主底模。

---

## 2. 逐条表

列说明：
- **研究出处**：`文件:§`。`spl/` = `script play lib/`；`h3/0x` = `docs/research/h3_deep/0x_*.md`。
- **画布 / gpu3**：采纳状态，见文首“状态写法”。

### 2.1 加速（26 行）

| 链接 | 是什么 | 研究出处 | 关键结论 | 画布 | gpu3 | 下一步 |
|---|---|---|---|---|---|---|
| https://github.com/ModelTC/Minimax-H3-Turbo · https://github.com/ModelTC/LightX2V/blob/main/scripts/minimax_h3/README.md · api.github.com/repos/ModelTC/LightX2V/commits?path=scripts/minimax_h3 | 官方加速 LoRA 仓库 / 规格表 | h3/02 §1.2；h3_prompt_and_fl2v §2 | 768p Turbo 训练 shift 6/3、8 NFE；544p 是 12/3 | ✅ `SHIFT_768P_TURBO` | ✅ | — |
| https://huggingface.co/lightx2v/Minimax-h3-Turbo（含 /tree/main、/discussions、api tree/commits） | 加速 LoRA 权重 | h3/02 §1.1 | 文件时间线；10-20 发布 FL2V 4step v1.3 和 8step v1.1 | ✅ 8step v1.1 768p @1.0 | ✅ | X1 定版本 |
| …/discussions/57 | 官方 10-20 发布帖 | h3/02 §1.2、§2.2 | 新版推荐 shift 6；v1.3 叠其他 LoRA 后严重劣化，v1.2 正常（1 人，官方承认） | ✅（没用 v1.3） | ✅ | 叠 Realism 等 LoRA 前先确认版本 |
| …/discussions/52 · https://comfyui-wiki.com/en/news/2026-09-06-minimax-h3-fl2v-turbo-v1-2（后者只在 kimi-0829 报告里） | 4step v1.2 | h3/02 §1.2、§2.2 | v1.2 只改进音频；多人说画质和头发变差 | ⊘ | ⊘ | — |
| …/discussions/48 · /54 · /3 · /9 · /40 | 社区参数讨论 | h3/02 §1.2；h3/03 §2.1、§3.2 | 强度 1.0（低→暗，高→过曝）；v1.1 4step 偏暗；#40：FL2VA 挂 Ref2V turbo 身份更好 | ✅ 强度 1.0 | ✅ | #40 见 2.3 |
| https://comfyui-wiki.com/news/2026-08-11-minimax-h3-turbo-lightx2v-v1 | v1 新闻 | h3_prompt_and_fl2v §7 | 背景 | — | — | — |
| https://github.com/Larryvrh/ComfyUI-MiniMax-H3-Turbo · https://huggingface.co/larryvrh/MiniMax-H3-Turbo-Lora | 社区加速 LoRA v4_step600_ema | h3/02 §2.3 | 3090 上 FL2V 实际在用；≥4 人说近景脸更好；shift 12/3；代价是快动作拖影、暗场色带；`low_vram` 会变糊 | ✗ | ✗（gpu3 没有这个文件） | **X1 组 D**（下载约 1 GB） |
| https://huggingface.co/joyfox/MiniMax-H3-Turbo · https://huggingface.co/Abiray/MiniMax-H3-Turbo-Lora-ComfyUI | Larry 的转换版 / pruned 版 | h3/02 §2.3 | 给 pruned int8 底模用的转换版 | ✗ | ✗ | 随 X1 |
| https://github.com/A-M-D-R-3-W/comfyui-minimax-h3-turbo · https://github.com/sepiablue-ai/minimax-h3-turbo-lora-benchmark · https://jo-nike.github.io/h3-turbo-eval/ · https://huggingface.co/spaces/multimodalart/h3-acceleration-arena | 步数对比实测 | h3/02 §2.1 | 4 步会出现慢动作、蜡化、音频差；6–8 步是舒适区（≥8 人） | ✅ 8 步，<6 步拒绝 | ✅ | — |
| https://huggingface.co/Kijai/MiniMax-H3_comfy（含 api loras） | Kijai 转换版 rank-24 544p v1.0 | h3/02 §1.3 | 有损、配错 shift → 不用 | ✅ 已从画布默认中移除 | ✅ 没用 | — |
| https://huggingface.co/Comfy-Org/MiniMax-H3（含 api diffusion_models、/discussions/18） | 官方 Comfy 打包 | h3/02 §3.1–3.3 | 3090 用 `fl2va_pruned_int8_convrot` | ✅ | ✅ | — |
| https://github.com/Comfy-Org/ComfyUI/issues/16420 | w4a8 + LoRA 时补丁静默失效 | h3/03 §0、§5 | 不用 w4a8 | ✅ `check_h3_model` 拦截 | ✅（adapter 默认值仍是 w4a8 → G3） | 合 G3 |
| https://zenn.dev/nanora/articles/20260929-minimax-h3-int8-vae-rtx3090?locale=en | int8 VAE 实测 | h3/02 §3.3 | 视频 VAE 用 int8（PSNR 56.7 dB）；音频 VAE 必须 fp32 | ✅ | ✅ | — |
| https://comfyui-wiki.com/en/news/2026-09-19-h3-video-vae-optimization · https://huggingface.co/Kijai/MiniMax-H3-experimental/discussions/13 | VAE 精度 | 只在 kimi-0829 报告 | int8 VAE 67.7 dB，不是脸崩的原因 | ✅（结论一致） | ✅ | 补进文档 |
| https://github.com/tonyd2wild/minimax-h3-local · https://github.com/Comfy-Org/ComfyUI/issues/14722 | 3090 硬件事实 | h3/02 §3.1 | Ampere 上 FP8 / NVFP4 是软件模拟 → 选 INT8 | ✅ | ✅ | 文本编码器仍是 nvfp4_awq（A25，P3） |
| https://github.com/Comfy-Org/ComfyUI/issues/16589 | `--fast fp16_accumulation` | h3/03 §2.3 | 不加 `--fast` | — | ✅ | — |
| https://github.com/komikndr/raylight · https://github.com/alesha-pro/tools | 多卡序列并行 | h3/02 §4.1 | 4×3090 一条视频 3.12× 提速；LoRA 可能静默 0 key | ✗ | ✗（P3） | X8，低优先 |
| https://github.com/thu-ml/SageAttention | 注意力加速 | h3/02 §4.2；gpu_speedups §6 | 无损，可留 | ✗ | ◐ 装了没用 | X7 |
| https://github.com/Saganaki22/ComfyUI-sol-attn · https://github.com/cicalooo/ComfyUI-SolAttn-Ampere · https://comfylab.dev/blog/workflows/minimax-h3-comfyui-speed-vram-rtx-3090/（后两个只在 kimi-0829 报告） | Sol-Attn | h3/02 §4.2 | 近似计算，同种子构图会变 → 禁用 | ✅ 在 `H3_BANNED_NODES` 里 | ✅ | — |
| https://comfyui-wiki.com/en/news/2026-10-11-spark-h3 | Spark-H3 | 只在 kimi-0829 报告 | 只支持 SM89 / SM120，3090 不能用 | ⊘ | ⊘ | — |
| https://huggingface.co/FastVideo/FastH3-Omni-Comfy **（O3）** · https://huggingface.co/FastVideo/FastVideo-FastH3-Omni-8-Step-V1 · https://huggingface.co/FastVideo/FastVideo-FastH3-8-Step-V2 | Ref2VA 8 步 PDD + VSA | spl/design v2 §1.3；h3/01 §5 | 设计成“整集快速预演”档；Ref2VA 不能硬锁首帧；编码器 nvfp4 只适合 Blackwell | ✗ | ✗ | 想要预演档再做 A/B；否则正式关闭 |
| https://github.com/facok/comfyui-SelfLift **（O2）** · https://comfyui-wiki.com/en/news/2026-09-19-comfyui-selflift | 免训练的渐进分辨率采样 | spl/design v2 §1.5；spl/v5 §4 | H3 支持是实验性的；没有许可证声明 | ✗ | ✗ | 许可不明 → 先问作者，暂不进生产 |
| https://github.com/Zagitta/gpu-unlock **（O6）** | 解除 3090 张量核半速限制 | gpu_speedups §8；TASKS T50 | BF16 约 +64% | —（只在 gpu3 有效） | ✅ 已生效 | — |
| https://huggingface.co/alibaba-pai/MiniMax-H3-Acc-LoRAs · https://huggingface.co/Wuli-art/MiniMax-H3-Turbo · https://huggingface.co/lilcheaty/MiniMax-H3-NVFP4 · https://huggingface.co/DmitryDB/MiniMax-H3-ComfyUI-Quants · https://ai-muninn.com/en/blog/minimax-h3-nvfp4-rtx5090 | 其他加速 / 量化 | 只列了名字（h3_prompt_and_fl2v §7、spl/design v2 §9、intimate_audio） | **没有深挖**；NVFP4 不适合 Ampere | ✗ | ✗ | 不追 |
| https://docs.sglang.io/cookbook/diffusion/MiniMax/MiniMax-H3 · https://recipes.vllm.ai/MiniMaxAI/MiniMax-H3 | 其他推理后端 | h3_prompt_and_fl2v §7 | 与 ComfyUI 输出有差异，同一集内不要混用 | — | — | — |
| https://github.com/wildminder/awesome-minimax-H3 | 资源汇总 | h3/02 §8 | 作为索引用 | — | — | — |

### 2.2 质感（23 行）

| 链接 | 是什么 | 研究出处 | 关键结论 | 画布 | gpu3 | 下一步 |
|---|---|---|---|---|---|---|
| https://huggingface.co/fal/MiniMax-H3-Realism-People-LoRA | 人物写实 LoRA（rank 32，触发词 r34l1sm） | h3/03 §3.2；spl/v3 §4；kimi-0829 | 作者称近景脸、皮肤纹理更好；能压红脸漂移，但 “fragile”；**卡片没写支持 FL2V**；与 v1.3 一起用会坏 | ✗ | ✗（文件在 gpu3，research_adoption 没收录） | **A/B：0.6 / 1.0 × 近景镜头** |
| https://github.com/Carasibana/ComfyUI-H3-FaceRefine | H3 视频的脸部重绘（检测 → 裁 768 → H3 denoise 0.40 → 羽化回贴，保留音频） | **只在 kimi-0829 报告**（08:55、10:40、14:24 都排第一） | 专治远景小脸、动作中的眼睛；成本按 canvas² × 帧数增长 | ✗ | ✗ | **补调研入库 + A/B**（只需约 50 MB 检测器） |
| https://github.com/ryukbk/ComfyUI-VideoFaceDetailer | 通用视频脸部精修 | 只在 kimi-0829 报告 | 作者说没经过大量实战 | ✗ | ✗ | FaceRefine 的备选 |
| https://comfyui-wiki.com/en/news/2026-10-23-h3-vbvr-lora | LiconStudio VBVR I2V LoRA（约 149 MB，基于 FL2VA 训练） | 只在 kimi-0829 报告 | 针对物体重复、道具穿模、动作顺序错（与首饰数量直接相关）；只有作者的 6 组对比 | ✗ | ✗ | 补调研 + A/B 0.6–1.0 |
| https://comfyui-wiki.com/zh/news/2026-09-11-minimax-h3-sharpness-lora | LMS sharp v1.0 r64 | 只在 kimi-0829 报告；upscale_4k §1 提到在 regenerate 包里 | 约 0.8 强度；1.0 过度 | ✗ | ◐ 只在 regenerate 包里 | 跟 hero-shot 精修一起测 |
| https://huggingface.co/Efficient-Large-Model/Open-H3-Regenerate-2K · https://github.com/rdh9616/ComfyUI-Open-H3-Regenerate · https://huggingface.co/Kijai/MiniMax-H3-experimental/tree/main/loras | 2K 再生成（refiner r384） | spl/v3、v5 §4；upscale_4k §1–2；h3/01 §1 | σ 0.9 会重画脸（包内测试狐狸变成狼）；≤0.8 只适合 hero-shot；3090 跑 4K 不现实 | ✗ | ⊘ 默认不用，只作 hero-shot 选项 | 身份 A/B 后再决定 |
| https://huggingface.co/LBH-123-AI/Minimax_h3_latent_Upscaler · https://comfyui-wiki.com/en/news/2026-08-25-mmh3-ultimate-upscale | latent 放大 / 分块放大 | spl/design v2 §1.6；spl/v5 §4；upscale_4k | 后面必须接一次 refine；有重画风险 | ✗ | ⊘ | — |
| https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler · https://github.com/ByteDance-Seed/SeedVR · https://docs.comfy.org/tutorials/utility/seedvr2 | SeedVR2 3B 一步修复 | upscale_4k §1–3；spl/v8 §4 | 不改身份；batch 21、overlap 4、LAB 校色；颗粒 σ2 | ◐ 笔记本只做 lanczos + 4K 编码参数（D6） | ✅ `upscale_4k.py` | 测 3090 耗时（进行中） |
| https://github.com/OpenImagingLab/FlashVSR · https://github.com/lihaoyun6/ComfyUI-FlashVSR_Ultra_Fast · forum.comfy.org/t/…flashvsr…/4609 | FlashVSR | upscale_4k §1、§7 | 脸偏软；作为后备 | ✗ | ◐ 后备 | — |
| https://github.com/NJU-PCALab/STAR · https://github.com/sczhou/Upscale-A-Video · https://github.com/Vchitect/VEnhancer · https://github.com/ckkelvinchan/RealBasicVSR | 其他视频超分 | upscale_4k §1 | 显存放不下 / 改身份 / 油画感 | ⊘ | ⊘ | — |
| https://huggingface.co/WarmBloodAban/Minimax-h3_Singularity · https://huggingface.co/WAS/Minimax-h3_Singularity_v2_pruned · https://comfyui-wiki.com/en/news/2026-09-07-h3-singularity · https://comfyui-wiki.com/en/news/2026-10-22-h3-singularity-v2 | Singularity（Ref2VA 合并 + 微调） | spl/design v2 §1.7；spl/v3 §3；V2 只在 kimi-0829 报告 | 作者称中远景脸更稳、油光更少；但它是 Ref2VA，首帧锁定弱 | ✗ | ✗ | 只考虑作身份参考通道，不作主底模 |
| http://huggingface.co/OliviaRossi/Minimax-h3_Singularity-x-10Eros-Max_PRISM **（O4）** | PRISM 合并 | spl/design v2 §1.7；kimi-0829 14:24 | 没有评测，许可链不清；>0.5 MP 会出现人物重复；Ref2VA 不适合锁首帧 | ✗ | ✗ | ⊘ 建议正式关闭 |
| https://huggingface.co/TenStrip/10Eros-Max（含 /discussions/7、/40、/63）· https://huggingface.co/DmitryDB/MiniMax-H3-10Eros-Max-Quants · https://huggingface.co/LokkenJP/TenEros_Max_optimized_learned · https://civarchive.com/models/2851079?modelVersionId=3294059 | 10Eros-Max（FL2VA 微调，beta5 / beta7） | spl/v3 §3；intimate_audio §1.3；kimi-0829 | beta7 推荐 shift 12/3、8 步；单次采样背景闪烁，需要两段式；作者自认“不比底模更 NSFW” | ✗ | ✗ | 低优先 A/B |
| https://huggingface.co/SexGod1979/PinkCherry-NSFW_MiniMax-H3（含 /discussions/26）· https://civarchive.com/models/2877206（DaSiWa） | 其他 FL2VA / hybrid 微调 | 只在 kimi-0829 报告 | 效果与底模相近，没有用户评价 | ✗ | ✗ | 不追 |
| https://note.com/truenorthai/n/ndb31c47d18e7?hl=en | w4a8 比 bf16 噪声更多 | 只在 kimi-0829 报告 | 支持换 int8 | ✅ | ✅ | — |
| https://huggingface.co/madebyollin/texture-fix-vae-for-qwen-image-2.1 · https://comfyui-wiki.com/en/news/2026-09-24-texture-fix-vae-qwen-image-2-1 | 首帧纹理修复 VAE | spl/v8 §4；kimi-0829 | 去棋盘格（rFID 3.38→2.07） | ◐ 只在 `pipeline.refine_image`（批量 / `ab_refine`）；画布 `frame_edit` 不调用 | ✅（v8 精修链） | 画布加一个“写实精修”按钮 |
| https://github.com/rkfg/ComfyUI-MiniMaxH3-ToneCompensate · https://github.com/lovemachine100/ComfyUI-H3-ClipColorAnchor · https://comfyui-wiki.com/en/custom-nodes/ComfyUI-KJNodes/nodes/color-match | 视频校色 | h3/03 §2.2；spl/v6 | ≥6 人确认 H3 会偏离锚帧颜色；逐镜 gain+bias 校正 dE 4.2→1.9 | ◐ `ns_post.colormatch` 默认关 | ✗（G2 闸门未做） | **X10 → 默认开** |
| https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/67 · /discussions/55 | 变暗 / 红脸 | h3/03 §0、§2.1 | euler 让变暗约减半 | ✅ euler | ◐ 基模档仍是 res_multistep（G1） | X2 |
| https://www.seedance.tv/blog/best-minimax-h3-settings | 设置博客 | 只在 kimi-0829 报告 | 基模 res_multistep、cfg 1 | — | — | — |
| https://huggingface.co/iamkaikai/MiniMax-H3-Single-Frame-VAE-500K | 单帧 VAE | **只出现在会话里，没有任何调研** | 用途不明 | ✗ | ✗ | 需要时再查官方卡 |
| https://huggingface.co/JOKER141/MiniMax-H3-General-Motion-Continuity-Repair | 动作连续性修复 LoRA | spl/v3 §4（**只列了名字**） | 针对假慢动作；与 v1.3 叠加会坏 | ✗ | ✗ | 补调研 |
| https://huggingface.co/TaoLiveAIGC/TaoMate-H3 · https://huggingface.co/vpakarinen/natural-face-speech-h3-lora · https://huggingface.co/alibaba-pai/MiniMax-H3-Fun-Controlnet-Union-2.0 | 其他 H3 衍生 | spl/v3 §7（只列了名字） | 口型 LoRA 只标注英文 | ✗ | ✗ | 不追 |
| https://huggingface.co/Lightricks/LTX-2.5（含 /discussions/25）· https://huggingface.co/frtertaer/LTX-2.5-uncensored-v1.1-FP8 · https://comfy.icu/node/CCTechLTX25FaceIdentityReinforcer · https://comfyui-wiki.com/news/2026-10-06-kandinsky-6-0 · https://www.scriptbyai.com/best-open-ai-video-generation-models/ · https://github.com/Anil-matcha/awesome-uncensored-ai-video-models/blob/main/UNCENSORED-MODELS.md | 替代视频引擎 | 只在 kimi-0829 报告 | 磁盘空间不够、没有证据、无音频 | ⊘ | ⊘ | — |

### 2.3 一致性与衔接（18 行）

| 链接 | 是什么 | 研究出处 | 关键结论 | 画布 | gpu3 | 下一步 |
|---|---|---|---|---|---|---|
| https://docs.comfy.org/tutorials/video/minimax/minimax-h3-multiframe · https://github.com/januscaler/ComfyUI/pull/10 · https://github.com/QuantFunc/ComfyUI-QuantFunc/issues/19 | 官方 Ref2VA + AddGuide 首尾帧 + 角色卡模板 | h3/03 §3.2；adoption A18 | 33.3 dB / SSIM 0.993；人物转身后能从角色卡恢复脸 | ✗ | ✗ | **X4 组 F** |
| https://comfy.icu/node/MiniMaxH3CombinedImageAndReferenceToVideo · https://www.instasd.com/post/minimax-h3-r2v-reference-to-video-comfyui | 首 / 中 / 尾帧锁定 + 最多 10 张参考 | 只在 kimi-0829 报告 | 需要能读参考的模型（hybrid） | ✗ | ✗ | 并入 X4 |
| https://github.com/Comfy-Org/ComfyUI/pull/15439 | `MiniMaxH3AddGuide` 中间关键帧 | h3_prompt_and_fl2v §2；SOP P-A8 | 引导帧放太密会冻住脸 | ✗ | ✗ | X6 |
| https://huggingface.co/lightx2v/Minimax-h3-Turbo/discussions/40 | FL2VA 挂 Ref2V turbo LoRA | h3/03 §3.2；adoption A19 | InsightFace 0.886；1 人说更糊 | ✗ | ✗（文件已在 gpu3） | X4 加一组，零下载 |
| https://huggingface.co/joeygambino/MiniMax-H3-Multishot-Workflow | 多镜头实测包 | h3/03 §2.2、§3.1；kimi-0829 | 关键帧保真 FL2VA 26.35 dB vs Ref2VA 16.15 dB；每镜独立种子；角色描述逐字重复 | ✅ 每镜种子 | ✅ | 描述重复属写作侧（abliteration） |
| https://huggingface.co/Comfy-Org/MiniMax-H3/discussions/30 · https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/87 · /discussions/78 | 小脸崩坏 | h3/03 §3.1；h3/01 §2.4 | 约 1 MP，脸要大 | ✅ 768×1344 | ✅；脸大小闸门只告警（G6） | 合 G6 |
| https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/91 | 音频参考 | h3/01 §2.4；spl/v5 §1 | 加音频参考后身份相似度掉到 0.09 | ✅ 不用音频参考 | ✅ | — |
| https://github.com/kohya-ss/musubi-tuner/blob/main/docs/minimax_h3.md · https://note.com/sepiablue/n/nf0763f854580 · https://note.com/sepiablue/n/nc1ce412d6ea2 · https://civitai.com/articles/36097/training-h3-loras-on-small-datasets-what-ive-learned-so-far · https://comfyui-wiki.com/en/news/2026-08-03-ai-toolkit-minimax-h3-training | H3 身份 LoRA 训练 | h3/03 §6；adoption C8 | 24 GB 显存可训；数据集用脸部特写 | ✗ 画布没有 video LoRA 触发词 | ◐ 训练中（`tools/lw_lora`） | 训完接进 `auto_lora_triggers`（kind=video） |
| https://huggingface.co/akatz-ai/MiniMax-H3-Character-Swap-LoRA | Ref2VA 换人 v1.5 | spl/v3、v5；kimi-0829 | 实验性，会漂移 | ✗ | ✗（gpu3 有 v1） | 兜底，不急 |
| https://huggingface.co/berryber09/MiniMax-H3-ref2va-fl2va-hybrid-w4a8 | hybrid 底模 | h3/03 §3.2 | w4a8 版本 → 不适用 | ⊘ | ⊘ | — |
| https://ai-muninn.com/en/blog/qwen-image-21-same-face-8-outfits-rtx-5090 | 首帧编辑身份 | spl/v5 §1 | 画布与参考图比例一致时眼距波动 ±3.9%，不一致时 ±18.9% | ✅ `qwen_edit` 先中心裁切 | ✅ | — |
| https://ai-muninn.com/en/blog/minimax-h3-ref2va-two-characters | 双人 Ref2VA | spl/v5 §3 | 多人同框 | ✗ | ✗ | — |
| https://huggingface.co/lilylilith/QI_2.1_AnyAngle **（O5）** · https://comfyui-wiki.com/news/2026-09-28-qwen-image-2-1-anyangle-lora · https://civitai.com/models/2970214 | 首帧转角度 LoRA | spl/design v2 §1.2；spl/v6 §1 | v6 复核：需要先有 3D 渲染图作输入，不适合本项目 | ⊘ | ⊘ | 回复项目方已否决 |
| https://comfyui-wiki.com/en/news/2026-10-01-qwen-image-2-1-consistency-lora · https://comfyui-wiki.com/en/news/2026-10-07-qwen-image-2-1-multiple-angles-lora · https://civitai.com/models/2969143 · https://civarchive.com/models/2995608 | Qwen 一致性 / 多角度 LoRA | spl/v6 | 用物体训练的，对人脸效果不明 | ✗ | ✗ | — |
| https://github.com/omnichar/ComfyUI-Omnichar · https://github.com/Luisacaotica/ComfyUI-MiniMaxH3Mod | 角色打包 / 参考缓存 | spl/design v2 §1.8 | 对衍生 checkpoint 未验证 | ✗ | ✗ | — |
| https://github.com/ali-vilab/VACE · https://comfy.org/workflows/video_wan_vace_flf2v-45c0ce6bcf2e/ · https://github.com/yihao-meng/HoloCine · https://github.com/WeChatCV/Stand-In · https://huggingface.co/ByteDance/lynx | 备用引擎 / ID 注入 | seedance_consistency §3 | 没有音频；两个引擎风格不统一 | ⊘ P3 | ⊘ | — |
| https://dreamina.capcut.com/ai-video/same-character-across-ai-video-scenes · https://pixo.video/zh/blog/seedance-2-first-frame-reference-image · https://huggingface.co/Qwen/Qwen-Image-Edit-2511 · seed.bytedance.com（多个页面） | Seedance / 即梦方法 | seedance_consistency §1–4 | 场景母版回锚；用视频解码出的**真实末帧**接下一镜 | ◐ 笔记本存了 `video_NNN_last.png` | ◐ C1、C2 | 核对 gpu3 下一镜的 reference_sha |
| https://minimax3.com/blog/minimax-h3-first-last-frame · https://www.seedance.tv/blog/minimax-h3-first-and-last-frame | 首尾帧指南 | spl/v6 | 首尾帧之间要有合理的物理路径 | ◐ 首尾帧差距闸门只告警（C3） | ◐ | 合 C3 |
| https://github.com/NikoDemon80/ComfyUI-H3-Motion-Context/issues/20、/44 · https://github.com/tritant/ComfyUI_MiniMax_H3_Extender/issues/15 · https://github.com/MiniMax-AI/MiniMax-H3/issues/85 · https://github.com/Comfy-Org/ComfyUI/issues/15426 · https://github.com/kijai/ComfyUI-KJNodes/issues/759、/763 · https://github.com/modelscope/DiffSynth-Studio/issues/1624 · https://github.com/vllm-project/vllm-omni/issues/6391 | 社区问题证据 | h3/03 §2.1–2.3 | 用于“颜色 / 质量”共识计数 | — | — | — |

### 2.4 提示词与音频（10 行）

| 链接 | 是什么 | 研究出处 | 关键结论 | 画布 | gpu3 | 下一步 |
|---|---|---|---|---|---|---|
| https://github.com/MiniMax-AI/MiniMax-H3（README、skills、`base-en.txt`、SKILL.md、issues/17）· https://huggingface.co/MiniMaxAI/MiniMax-H3（`FL2VA/model_index.json`、LICENSE、`VIDEO_PROMPT_WRITING_GUIDE_base_en.md`） | 官方仓库 / 提示词规则 | h3_prompt_and_fl2v §1–2；h3/01 | 英文结构化提示词；台词用 `<d>`；写 `overall_soundscape`；FL2VA 对齐句 | ✅ `h3_prompt.py` / 编译器透传 + `script_chat_rules` | — | — |
| https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_ref_en.md | Ref 模式提示词指南 | **没有调研**（只出现在 10-15 会话摘要里） | 做 X4（Ref2VA）时需要 | ✗ | ✗ | X4 前读一遍 |
| https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/47 · https://github.com/teskor-hub/minimax-h3-skill/blob/main/portable-prompt.md | I2VA 对齐句 | kimi-0829 10:40；spl/v5 §2 | 只有首帧时（I2VA）的原文模板 | ◐（写作侧） | — | 由写作侧确认 |
| https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide · …/minimax-h3-native · https://comfyui-wiki.com/en/tutorial/advanced/video/minimax/minimax-h3-prompt-writing · …/minimax-h3 · https://huggingface.co/datasets/malcolmrey/various/blob/main/h3-center/docs/MINIMAX_H3_PROMPTING_GUIDE.md | Comfy 官方指南 | h3_prompt_and_fl2v；SOP S4；intimate_audio §1 | 引号里的字会被画成屏幕字幕；首帧按拉伸方式缩放 | ✅ center-crop | ✅ | — |
| https://github.com/colorAi/ComfyUI-Minimax-H3-Prompt-Engineer · https://www.seedance.tv/blog/minimax-h3-negative-prompt-comfyui · https://docs.comfy.org/built-in-nodes/NAGuidance · https://x.com/alexfredo87/status/2085467476431622435 · https://www.atlascloud.ai/blog/tips/minimax-h3-chinese-dialogue-accuracy | `[Chinese]` 标签、负面提示词、NAG、res_2s、中文台词准确率 | 只在 kimi-0829 报告 | cfg 1 没有负面分支；中文台词 ≤3.5 字/秒（约 83% 准确） | ✗ | ✗ | 中文语速规则交写作侧 |
| https://github.com/WayneJin0918/Omni-Rewriter | 提示词改写 | h3_prompt_and_fl2v §7 | 背景 | — | — | — |
| https://platform.minimax.io/docs/api-reference/video-generation-v2-create · …/v2-h3-context-ir · …/v2-regeneration · …/t2v · https://platform.minimax.cn/docs/…（pricing、v2-create）· https://www.minimax.io/blog/minimax-h3 · https://www.minimax.io/news/video-agent | 官方 API | h3/01 §4 | 可以用 API 把 768p 片段再生成到 2K，但只适合非成人镜头；Context-IR 不开源 | ✗ | ✗ | 需要时花钱试（要项目方点头） |
| https://apimaster.ai/blog/minimax-h3-1-api · https://blog.fal.ai/introducing-h3-max-by-fal/ · https://www.orcarouter.ai/de/blog/minimax-h3-vs-hailuo-2-3 · kingy.ai（2 篇） · https://www.runpod.io/blog/minimax-h3-… | 版本 / 托管情况 | kimi-0829；uncensored_deep；spl/v7 | H3.1 未发布；H3 Max 只有 API | — | — | — |
| https://github.com/hkchengrex/MMAudio · https://github.com/QwenAudio/ThinkSound · https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley · https://github.com/phazei/ComfyUI-HunyuanVideo-Foley · https://github.com/xiaomi-research/controlfoley · https://github.com/reeleehq/foley/pull/174 · https://huggingface.co/fishaudio/s2-pro · TTS-Audio-Suite COSYVOICE3 指南 | 拟音 / TTS | intimate_audio §3–4 | Foley XL 做接触声；标志性音效用素材库 | ◐ `ns_post` 有 tts / music / speakers，没有 Foley | ✗ | 按 intimate_audio §6 做 A/B |
| https://github.com/lebao-arch/comfyui-h3-audio-drive-auto · https://comfy.icu/node/MiniMaxH3LatentLabLipSyncSetup · https://github.com/starsFriday/ComfyUI-MiniMax-H3-LegacySampling/blob/main/README.md · https://github.com/Comfy-Org/embedded-docs/…/MiniMaxH3SigmaShift/en.md · https://github.com/Comfy-Org/ComfyUI_frontend/issues/15040 · https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/64 · https://discuss.huggingface.co/t/…/190009 · https://civarchive.com/models/2925394 · https://civitai.com/models/2821932/minimax-h3 · https://zenn.dev/nekod/articles/c9505022fb8661 · https://huggingface.co/pottokao/MiniMax-H3-TextEncoder-Qwen3VL-32B-abliterated-GGUF | 音频驱动 / 口型 / 音频 LoRA / 去审查编码器 | intimate_audio §1、§5；spl/v3 | 先出音频再驱动视频，可以锁住林晚的声线 | ✗ | ✗ | 等项目方定声线方案 |

### 2.5 其他（Qwen 首帧栈、UI 调研等，只列出处，与 H3 质感无直接关系）

**Qwen 首帧栈**
- 链接：
  - Qwen-Image-2.1 系列：https://huggingface.co/Qwen/Qwen-Image-2.1、https://huggingface.co/Qwen/Qwen-Image-2.1-Turbo、https://huggingface.co/Comfy-Org/Qwen-Image-2.1 **（O1）**、https://huggingface.co/Noctaluna/Noct-Q-Uncensored-Qwen-Image-2.1
  - Qwen LoRA 文章：https://www.orcarouter.ai/blog/qwen-image-2-1-lora、https://note.com/sepiablue/n/n9372886b9e5d
  - 其余 Qwen 相关：uncensored_deep §6、spl/v6、v8、v9 的来源清单
- 现状：O1 已用（`qwen_image_2.1_turbo_int8_convrot`、Base int8）。

**界面 / 平台调研**
- 链接：
  - xiaoyunque、runway、huobao-drama、Toonflow、flora 等
  - 文件：`docs/canvas_research*.md`、`docs/research/short_drama_platform_ui.md`
- 现状：与模型无关，不在本表展开。

---

## 3. 没有调研的链接 / 只停在会话里的调研

**A. 出现在项目方能看到的材料（会话报告）里，但没写进仓库文档，也没进采纳表。** 来源是 kimi-0829 三份报告，约 30 个，其中与质感 / 一致性直接相关的有：
- Carasibana H3-FaceRefine
- VBVR LoRA
- LMS sharpness LoRA
- Singularity V2（WAS pruned）
- FL2V turbo v1.2 新闻
- Combined Image+Ref 节点
- VideoFaceDetailer
- NAGuidance
- colorAi Prompt-Engineer
- HF H3 #47
- atlascloud 中文台词测试
- seedance 两篇
- comfylab 3090 测速
- SolAttn-Ampere、Spark-H3
- h3-video-vae-optimization、Kijai experimental #13
- PinkCherry、DaSiWa、LTX-2.5 系列、Kandinsky 6

建议：把这三份报告原样存为 `docs/research/h3_kimi_20261029.md`，再把 FaceRefine、VBVR、LMS sharp 补进 `research_adoption.md`。

**B. 完全没有调研。**
- `VIDEO_PROMPT_WRITING_GUIDE_ref_en.md`
- `iamkaikai/MiniMax-H3-Single-Frame-VAE-500K`

**C. 只列了名字、没有深挖。**
- JOKER141 Motion-Continuity-Repair
- alibaba-pai Acc-LoRAs / Fun-Controlnet
- Wuli-art turbo
- TaoMate-H3
- natural-face-speech LoRA
- lilcheaty NVFP4
- DmitryDB quants

**D. 项目方原话要求“research 这些模型，看看能不能修复”的 5 个链接（O1–O5）。**
- 只在 design v2 做过单页阅读，没有按 deep-research 方法（社区实测、逐条原文引用）深挖。
- 后续只在 kimi-0829 14:24 报告里顺带给了“Ref2VA 系不适合锁首帧”的结论。
- 没有给项目方一个明确的“用 / 不用”回复记录。

---

## 4. 调研过、定位为提质，但现在两条链都没用的项目（按对质感 / 衔接的预期影响排序）

| 排名 | 项目 | 目标问题 | 证据强度 | 阻塞点 | 建议动作 |
|---|---|---|---|---|---|
| 1 | 逐镜视频校色到首 / 尾关键帧（`ns_post.colormatch`，ToneCompensate 思路） | 偏暖、偏灰、变暗（PI-19） | ≥6 人确认；3 个项目都这么做 | 画布默认关；gpu3 的首尾帧没同步回来 | 跑 X10（只用 CPU）→ 默认开 |
| 2 | Ref2VA + AddGuide 首尾帧 + 林晚角色卡（官方 multiframe 模板）／ FL2VA + Ref2V turbo LoRA | 镜内和跨镜身份（PI-01） | 官方模板；实测 33.3 dB、InsightFace 0.886 | 要 GPU A/B；Ref2V turbo 已在 gpu3 | X4（F 组 + Ref2V LoRA 组） |
| 3 | H3-FaceRefine 脸部重绘 | 远景小脸、动作中的眼睛 | 3 份 kimi 报告都排第一，但只有作者自证 | 没入库，没下载 | 补调研入库 → 拿 ep01 坏片 A/B |
| 4 | fal Realism-People LoRA（0.6–1.0） | 近景皮肤 / 脸的写实质感、红脸 | 作者 19 组对比；社区说 “fragile”；没写 FL2V | 画布没有 video LoRA 触发；要避开 v1.3 | 近景镜头 A/B，然后加进 `auto_lora_triggers`（kind=video） |
| 5 | larryvrh v4_step600_ema 加速 LoRA | 近景脸清晰度（相对官方 v1.1） | ≥4 人；3090 用户实际在用 | gpu3 没有这个文件 | X1 组 D |

其后依次是：
- VBVR LoRA（首饰数量、道具穿模）
- 画布接入写实精修（texture-fix VAE + purelens，目前只在批量链）
- H3 身份 LoRA 训完后接成 video LoRA
- AddGuide 中间关键帧（X6）
- 4K SeedVR2 接回笔记本成片链
