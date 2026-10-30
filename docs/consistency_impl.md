# 一致性方案在 gpu3 的实现（claude-gpu3，2026-10-30）

> 对应：协调转达的“3 个 bug + 方案 A + 方案 D”，以及与 fredw-d9 的 `docs/CONSISTENCY_PLAN.md`、`docs/state_timeline.md` 的分工。
> 代码：gpu3 `ns-studio/scripts/weita_render.py`（WR）、`weita_series.py`（WS）、`weita_adult.py`（WA）。
> 现状：**全部只在 CPU 上改完并通过单元测试（14 项），没有出任何图或视频**；等项目方放行后用 ep01 验证。

## 一、三个 bug

### 1. H3 首尾帧提示词改成官方格式（WR `h3_prompt`）
- 第一行固定对齐句：
  `How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark …; Picture 2 (from Shot 1) aligns with the S.SS-second mark …`，S = 本镜帧数 / 24，保留两位小数（243 帧 = 10.12）。没有尾帧时只写 Picture 1。
- 空一行后依次写三个字段：`integrated_multimodal_description: [Shot 1] …`、`overall_soundscape: …`、`non_diegetic_music: N/A`。
- 正文用英文、只写一个连续镜头，结构是：Picture 1 的起始状态 → 运镜（类型 + 幅度 + 速度）→ 可观察的中间动作 → “settles into the pose, expression, spacing and composition established by Picture 2 at the end of the shot”。不复述两张静帧，不写否定句。
- 中译英用本地 LLM（127.0.0.1:8097，系统提示照官方 skill 的规则写），结果按输入哈希缓存在 `data/run/weita/h3_prompt_cache.json`。LLM 忙或输出不合格（含中文、含否定词、缺 Picture 2）时，退回**确定性模板**：官方结构不变，动作句用剧本原文。
- 对白放在收尾句之前，中文原文写在 `<d>[Chinese] …</d>` 里；说话人 (S1)/(S2) 和音色描述写在标签外。按 ComfyUI 页面的要求，“……”改成逗号，句末补“。”。
- `overall_soundscape` 优先用 v3 的【H3 audio】段，没有时用剧本 sound 行；她穿高跟走路时加 “12cm stiletto heels clicking on marble”。**按官方“不写否定”要求，去掉了上一版加的 “no background music, no score”**，不要配乐只靠 `non_diegetic_music: N/A` 表达。
- 每镜实际用的提示词存在 `epXX/keyframes/<镜>.prompt.txt`。

### 2. 首尾帧几何一致（WR `h3_keyframe`）
- 首帧和尾帧送进 H3 之前，都用同一种方式处理：先居中裁成 4:7，再用 lanczos 缩放到 768×1344，然后用 ffprobe 断言尺寸。尺寸不对就直接报错，不渲染。
- 处理后的文件在 `epXX/keyframes/<镜>.first.h3.png` 和 `.last.h3.png`，上传给 H3 的就是这两张。

### 3. 蒸馏 LoRA 与 shift（核对结果）
- gpu3 实际加载：UNet 是 `minimax_h3_fl2va_pruned_int8_convrot`（**不是** w4a8_mixed）；t8 用的是完整的 `fl2v_turbo_8step_v1.0_768p`（1.96 GB，**不是** 544p rank-24），配 shift 6/3，按官方表这两者是匹配的。
- 已改用官方最新的 `minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16`（gpu3 上已有，无需下载），保持 shift 6/3、euler + simple、8 步、BasicGuider cfg 1。
- 图里没有 EasyCache、Spectrum、TeaCache 或其他缓存节点，也没有 ancestral/SDE 采样器（只有在 `FastGraph` 里才会加，而我们不用 FastGraph）。

## 二、方案 A：锚点与闸门（gpu3 负责的部分）
- **链条按 segment 断开**：用 fredw-d9 的 `data/state_timeline.json` 里的 `segment_id` 和 `segment_start` 判断。同一 segment 的下一镜首帧，以编辑方式生成，参考图有三张：
  1. 上一镜的真实视频解码末帧（有视频时；否则用上一镜尾帧）；
  2. 场景底板 `assets/scenes/<scene_id>/plate.png`；
  3. 角色身份由二段式身份重绘提供（CM_s1 母版脸部裁切）。
  `segment_start`（切镜）时不接上一镜，只用底板和身份重新锚定。镜像里没有时间线时，退回我自己按地点分的场景。
- **底板缺失时**：照常出图，但不带底板，并把缺什么写进 `status.json` 的 `chain.edit_refs`，可以在画布上看到。底板由 fredw-d9 生成，gpu3 只读。
- **衔接闸门（帧）**：把上一镜尾帧和本镜首帧左右拼成一张，让 Qwen3-VL 判断“同一套衣服、同一地点、同一光线”；同时比较人物区域的 LAB a/b 直方图（Bhattacharyya 距离 ≤ 0.55）。不通过就扣掉本轮。不做 CLIP（协调已同意）。
- **衔接表**：`epXX/continuity_sheet.jpg`，相邻两镜按“上一镜尾帧 | 下一镜首帧”拼接。
- **视频闸门**：
  - 首帧对齐：PSNR ≥ 20 dB；
  - **落到尾帧（新增）**：解码末帧与给定尾帧的 SSIM ≥ 0.55；
  - 身份：沿片子在 1.5 / 3.5 / 5.5 / 7.5 / 9.9 秒各取一帧，SFace 中位数 ≥ 0.30（防溶解）；
  - 另有 owner_script_qc 的脸、眼、字幕检查。
- **status.json 字段（已与 fredw-d9 约定）**：`continuity {verdict, prev_shot, checks {outfit, place, light}, reasons[]}`、`scene_id`、`segment_id`、`chain {first_from, edit_refs[]}`、`bible_version`、`owner: "gpu3"`。每个 take 也写 `bible_version`。
- 镜头之间按项目方 AGENT-3 规定用 0.3 秒溶解。
- 大动作镜头加中间关键帧（`MiniMaxH3AddGuide`）：暂未接入，等 ep01 验证后再看是否需要。

## 三、方案 D：每镜人物状态（读 fredw-d9 的文件）
- 读取 `data/state_timeline.json`（随导入一起镜像到 gpu3）和 `data/scenes.json`，不自己另做一份。
- `needs_review`（造型待确认）的镜头：首尾帧不出，`status.json` 写 `state: blocked` 和原因。
- `bible_version` 优先取 state_timeline 顶层的值，没有时调用 `ns_agent.compiler.bible_version`。
- 帧闸门已用：共享 Frame Spec 的 must-facts、D 码（D0 时“无穿环”）、透明高跟或赤脚、日常穿搭里的漆皮超短裙、挂着不穿的道具。state_timeline 的单品 `items`（含参考图）接入提示词和 VLM 检查，是下一步。

## 四、其他已对齐的参数（SOP_parameters）
- 定稿出图：Qwen-Image 2.1 Base，35 步，cfg 3.0（原来是 4.0）；露骨镜头用 NoctQ V4，25 步（原来是 30）。两者都是两段式（928×1632 → 1152×2016，第二遍 0.30），叠 krea2 0.5，用 texture-fix VAE。
- 候选数按 visual_bible：每轮 3 张，最多 3 轮。`frames_fast`（每轮 1 张、28 步等提速项）与 SOP 冲突，**默认关闭**，等批准。
- 安全镜头的保底词按 B10 改为“衣装完整、无裸露”，不再写“保守/职业装”。
- 裸露质检 v3：用 fredw-d9 `ns_render.qc` 里校准过的看图问句（gpu3 没装 NudeNet 和 CLIP，看图模型就是裁决依据）。
- LoRA：只加载 `LORA_REGISTRY.json`（nsfs.lora_registry/v1）里 `status: accepted` 的条目；多个 LoRA 叠加时总强度不超过 1.6。
- v3 剧本只在 `data/import/s1_gate.json` 采纳了该剧本的 sha 后才启用，否则继续用 v2。

## 五、ep01 验证计划（放行后）
1. 用 v3 的 ep01 和 state_timeline 出 6 镜首尾帧。同一 segment 内按顺序接力；所有帧都过闸门。
2. 6 镜都 ready 后出视频：t8 用 v1.1 768p，官方提示词格式，首尾帧都经过同一几何处理。
3. 出衔接表、REPORT.md、qa.json（每镜 video_sha256）；全部通过后才合成 `ep01_final.mp4`。
