# 生产参数锁定表（SOP_parameters）

> 参数名后的 `rule_id` 对应 `docs/audit/rule_ids.md`，逐镜审计（SOP ★5）按此编号报告。

> 维护：**claude-sop**（本文件唯一写入者）。其他会话要改参数，请发消息给 SOP 管理员，并附上证据：A/B 图或测量值、项目方决定原话、或已合并且带测试的修复。没有证据的改动不收。
> 阶段顺序与闸门以 `docs/SOP_production.md` 的「★ 阶段闸门与资源优先级」为准。本表只锁“怎么做”，不改“先后顺序”。
> 「待验证」= 有来源但未经 A/B 或项目方确认，或各处写法有冲突；不得当作锁定值引用。
> 来源缩写：
> - **VB** = config/visual_bible.toml
> - **PL** = gpu3 `ns-studio/data/run/weita/PIPELINE_LOCKED.{json,md}`（2026-10-29 16:55Z）
> - **WR** / **WS** / **WA** = gpu3 `ns-studio/scripts/weita_render.py` / `weita_series.py` / `weita_adult.py`
> - **H3R** = docs/research/h3_prompt_and_fl2v.md
> - **AUD** = docs/audit/shot_readiness_and_continuity.md
> - **REQ** = docs/REQUIREMENTS.md
> - **CP** = docs/CONSISTENCY_PLAN.md

---

## 固定约束（任何剧、任何阶段都不可改）

| 参数 | 锁定值 | 来源/证据 | 锁定日期 | 适用剧 |
|---|---|---|---|---|
| GPU 2 | 永不使用 | TASKS 规则 5；PL；SOP ★2 | 2026-10-30 | 全部 |
| 成人内容 | 只用虚构成年人（≥22 岁），且双方自愿；所有负面词必须包含 `未成年人外观`（VB classification.minor_guard） | 项目方硬规则；VB | 2026-10-30 | 全部 |
| 真人肖像 | 不得出现真人长相；不得用真人私密图训练；参考图须登记为 AI 生成或虚构（config/face_reference.json） | 项目方硬规则；REQ B3 | 2026-10-30 | 全部 |
| 项目方画面风格 | 无字幕、无文字、无水印；徕卡级锐利；85mm f/1.2 奶油焦外；浓郁暖色调 | VB [look]；REQ A2–A6 | 2026-10-30 | 全部（风格参数可按剧在 G1 换） |
| 林晚身份 | 以 CM_s1 母版为准：`assets/characters/lin_wan/plates/master.png`，gpu3 侧为 `refs/LW_master.face.png`（sha b8e7b00b…，只用脸部裁切） | TASKS T09（项目方 2026-10-30 选定）；WR `LW_IDENTITY` | 2026-10-30 | 为他而骚 |
| 出图链 | 每镜只有一条 take 链：首帧、尾帧、视频同源；《为他而骚》全部归 gpu3 | SOP ★3；config/shot_ownership.json；CP 二.2 | 2026-10-30 | 为他而骚 |

## S1 剧本

| 参数 | 锁定值 | 来源/证据 | 锁定日期 | 适用剧 |
|---|---|---|---|---|
| 出口要素（每镜） | img、motion、时长、sound、【H3 audio】、【配乐】；每集还须有 配乐/【BGM】 | SOP ★1；AUD §2 | 2026-10-30 | 全部 |
| 校验 | 校验 0 错；原文对白/独白逐字不变；不新增人物；成年且自愿；每镜对白 ≤3.5 字/秒 | SOP §2、§6 | 2026-10-30 | 全部 |
| v3 改写重试 | 失败最多重写 3 次，仍失败保留原文并记录 | SOP §6 | 2026-10-30 | 全部 |
| 采纳 | G3：项目方采纳，须有原话或记录；没有 G3 不算通过 S1 | SOP 总览、★1 | 2026-10-30 | 全部 |
| 剧本写入者 | 只有 claude-gpu3；每次修改留 `.bak-<日期>-<原因>`，并用 sha256 同步到 gpu3 | SOP §2 | 2026-10-30 | 全部 |
| 本地 LLM | gpu3 127.0.0.1:8097，Qwen3.8-27B-Uncensored Q4_K_M（llama.cpp） | gpu3 weita-v3-llm.service（2026-10-30 巡检所见） | 2026-10-30 | 全部 |

## S2 资产与 LoRA

| 参数 | 锁定值 | 来源/证据 | 锁定日期 | 适用剧 |
|---|---|---|---|---|
| S2 出口 | 剧本里每个触发词都在 LORA_REGISTRY 中有已验收的 LoRA；每个场景有底板（项目方确认）；状态表覆盖每一镜 | SOP ★1 | 2026-10-30 | 全部 |
| 身份母版写实配方 | Qwen-Image 2.1 Base，35 步，cfg 3.0；Anything2RealCharacters 0.8 + krea2_film_texture 0.5（只用于把风格化参考做成写实底板） | VB realism.plate_loras；TASKS T09 | 2026-10-30 | 全部 |
| 母版候选 | 3 档写实强度，每档 2 张；灰底、中性服装，不带项链和背景；由项目方在 G2 选定 | SOP §4；TASKS T43 | 2026-10-30 | 全部 |
| 禁用 LoRA | glamour_realism_qwen21（用 AI 图训练，会加重 AI 味） | VB banned_loras | 2026-10-30 | 全部 |
| 禁用词 | 娃娃感、精致完美、完美无瑕、网红脸、网红、纯欲、斩男，以及照搬眼形/五官比例类句子 | VB banned_words | 2026-10-30 | 全部 |
| LoRA 训练数据 | 只用合成图或无人商品图；真人照只能当款式参考 | SOP §5 | 2026-10-30 | 全部 |
| LoRA 验收登记 | 最佳检查点放进 `ComfyUI/models/loras/`，同时登记 LORA_REGISTRY.json，并附 README 与 sha256 | SOP §5 | 2026-10-30 | 全部 |
| LORA_REGISTRY 路径与状态 `R-C4` | 实体文件 gpu3 `nsfs_mirror/data/renders_gpu3/LORA_REGISTRY.json`，以软链挂在 `<REPO>/ComfyUI/models/loras/LORA_REGISTRY.json`；schema `nsfs.lora_registry/v1`。登记流程：训练方写 `training` → 协调看过样图拼图批准后改为 `accepted`。S3 只认 `accepted`。2026-10-30 22:09 建立，当时为空 | WR L323/364；协调回复（巡检 #1）；巡检实测 | 2026-10-30 | 为他而骚 |
| v3 切换闸门 `R-C3` | v3_finish.sh 只把 v3.md 和 v3_changes.md 写到 `owner_scripts/weita_ersao/staging_v3/`，不写进生效目录，SCRIPT_PATH 读不到。只有在 S1 闸门（G3）通过、**并且**渲染器的 s1_gate 检查已合并之后，才可移入生效目录 | 22:20 巡检核实：v3_finish.sh L13–16 写 staging_v3；`weita-v3-finish2` 正在运行修正后的脚本；生效目录只有 v2。22:18 巡检：WR L50–54 已有 S1_GATE（读 `nsfs_mirror/data/import/s1_gate.json`，按 v3 sha 放行，由 fredw-d9 `tools/s1_gate.py --accept` 写）→ 代码已合并；测试情况未见，G3 实际放行时再核 | 2026-10-30 | 为他而骚 |
| 场景底板 | 只能用通过 S1 的 v3 生成的 scenes.json；空景、无人、无字；约 1.5MP 9:16（1152×2016），二次重绘 0.30，再派生 768×1344；配方同 S3 图像；项目方确认后才可用于 S3 | AUD §3.1；SOP ★1；docs/state_timeline.md §五 | 2026-10-30 | 全部 |
| 造型注入 `[looks] inject` | 默认 false。打开前须满足：T06 版本化已就位、只对项目方确认过的集生效、看过 bible_diff 编译差异并至少 A/B 一镜、通知 gpu3 | docs/state_timeline.md §六；SOP ★3 | 2026-10-30 | 全部 |
| 饰品 LoRA 状态 `R-C4` | nprng2、lbrng9、lbrng9_beads = **deferred（等项目方修正）**：项目方指出乳环和阴环位置不对、珠子应为钢色而不是黑色；在修正数据并经项目方批准特写之前不得训练。用到这三个触发词的镜头，S2 不通过 | 协调转达项目方决定（巡检 #4 回复） | 2026-10-30 | 为他而骚 |
| 身份 LoRA 训练时长 | 图像 LoRA 1.5–3 h；H3 身份 LoRA 9–11 h（含评估） | SOP 资源表 | 待验证（估算值） | — |

## S3 首帧 / 尾帧（图像）

| 参数 | 锁定值 | 来源/证据 | 锁定日期 | 适用剧 |
|---|---|---|---|---|
| 定稿模型（一般镜头） | Qwen-Image 2.1 **Base**，真 CFG，35 步，cfg 3.0 | VB realism（final_model=base）；WR L921 注释（research v8）；SOP 已知坑：Turbo cfg1 不认否定约束 | 2026-10-30 | 全部 |
| 定稿模型（露骨/成人镜头） | NoctQ V4 int8_convrot，25 步，cfg 2.5，er_sde/beta | PL first_frame.explicit | 2026-10-29 | 为他而骚 |
| 冲突：步数 | PL `frames_fast` 写 base_steps 28、noct_steps 26，与上两行的 35/25 不一致 → **待验证**，需项目方或协调定 | PL frames_fast（2026-10-30 frames plan） | 待验证 | — |
| 冲突：Turbo | PL 首帧仍写 `qwen_image_2.1_turbo (8 步 cfg 1)`，已被 VB 的 final_model=base 取代；Turbo 只用于预览 | VB preview_model=turbo | 2026-10-30 | 全部 |
| 写实 LoRA | krea2_film_texture_qwen21 0.5 | VB realism.loras；WR `REALISM_IMG_LORA` | 2026-10-30 | 全部 |
| VAE | texture_fix_vae_for_qwen_image_2.1_bf16 | VB；PL；WR | 2026-10-30 | 全部 |
| 两段式分辨率 | 第一遍约 1.5MP（928×1632），lanczos 放大到 1152×2016，第二遍 denoise 0.30 | WR L921–926；VB resolution_mp / second_pass_denoise | 2026-10-30 | 全部 |
| H3 输入尺寸 `P-B2` | 768×1344；首帧与尾帧用**同一种方式** center-crop 后再交给 H3（节点对首帧是拉伸、对尾帧是居中裁切） | PL h3_input；H3R #2（源码，置信度高） | 2026-10-30 | 全部 |
| LoRA 叠加上限 `S3-F6` | 同一张图上所有 LoRA 强度合计 ≤1.6（超出时按比例缩小注册表权重） | WR `LORA_CAP = 1.6` | 2026-10-30 | 全部 |
| 身份参考 | 只用脸部裁切（不带脖子以下）；林晚 = CM_s1 母版脸部裁切 | WR L421–428；REQ B1 | 2026-10-30 | 为他而骚 |
| 色调匹配 `S3-F7` | 用 Reinhard LAB 迁移到 `assets/style/color_reference_01.png`，强度 0.6；暗场/夜景 0.3；剧本写的光源优先；保留未调色原图 | VB color_match_strength / dark_shots / script_light_wins；WR colour_match；REQ A4 | 2026-10-30 | 为他而骚（参考图按剧换） |
| 尾帧调色 | 以定稿首帧为参考迁移，强度 0.7（笔记本链），gpu3 链用 0.6 到参考图 | REQ A4；WA L259–263 | 待验证（两链不一致） | — |
| 焦外闸门 `S3-F2` | 背景/主体 Laplacian 方差比 <1.0（全景、大全景、俯拍豁免）；项目方风格参考图实测为 0.69 | WS `BOKEH_MAX = 1.0`、L725 | 2026-10-30 | 全部 |
| 人脸相似度 `S3-F1` | SFace 余弦 ≥0.40（侧脸或转开的脸 ≥0.30）；SFace 同人阈值为 0.363 | WS `SIM_MIN`、L718；PL 选片 | 2026-10-30 | 全部 |
| 发色闸门（林晚） `S3-F3` | 取人脸上方/两侧发带做 HSV 判断：H∈[85,125] 且 S≥30 的蓝色像素须 ≥15%；亮度须 ≥max(70, 0.6×脸部亮度)。浅冰蓝通过，藏青或黑色判失败 | WS L682–705 | 2026-10-30 | 为他而骚 |
| 发色描述 | 雾霾天蓝色及腰直发（比参考略深、略带灰），齐刘海 | VB characters.lin_wan.hair_color（项目方 2026-10-30 选择） | 2026-10-30 | 为他而骚 |
| 轮数 | 每镜最多 4 轮，任一候选通过即停 | WS L759 | 2026-10-30 | 全部 |
| 冲突：轮数与候选数 | VB 写 3 候选×3 轮（阈值 0.72）；PL 写 2 候选×3 轮；WA（成人）写 2 轮；PL frames_fast 写有 LoRA 时每轮 1 候选 → **待验证**，需统一 | VB [generation]；PL；WA L146 | 待验证 | — |
| VLM 核对 `S3-F5` | 本地 Qwen3-VL 8B 逐条核对 Frame Spec 事实（透明高跟、饰品计数、人数、衣着）；每帧一次调用 | PL 选片、frames_fast | 2026-10-29 | 全部 |
| 裸露 `S3-F4` | 只记录（report_only；2026-10-30 取消成人过滤器） | VB nudity_qc_non_adult | 2026-10-30 | 全部 |
| 尾帧生成 | 以本镜首帧为图 1，编辑到 motion 的结束状态；景别、机位、光线、身份、服装保持不变（VB last_frame_keep） | VB assembly；REQ C3 | 2026-10-30 | 全部 |
| 场景内接力 | 同一场景下一镜的首帧，以上一镜尾帧为参考编辑生成；切换场景时重新锚定 | AUD §3.3；CP 方案 A | 2026-10-30 | 全部（实现中 T47） |
| 衔接检查 `R-C7` | 视觉模型判断同衣、同地、同光；人物区 LAB 直方图距离、背景 CLIP 相似度的阈值 = **待验证**（尚未定数） | AUD §3.4 | 待验证 | — |

## S4 视频（MiniMax H3 FL2VA，官方规范见 SOP_production.md §9A）

> **项目方 2026-10-30 决定：H3 的 A/B 先不做（“先不做”），等 LoRA 与首尾帧完成后再做。** 在此之前，凡标「需 A/B」的项，都按 gpu3 现行代码值执行（加速 LoRA v1.1_768p、6/3、8 步、euler），但不升为锁定，审计只报 warn。
> 状态：**锁定** = 官方原文或源码已在 2026-10-30 抓取核对；**待验证** = 来源未抓到，或 gpu3 实况未核；**需 A/B** = 有候选值，等实测定。
> 官方链接缩写同 SOP_production.md §9A：
> - [G] 官方提示词指南 <https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md>
> - [K] 官方改写技能 <https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/SKILL.md>
> - [C] ComfyUI 提示词页 <https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide>
> - [CN] ComfyUI 原生节点文档 <https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native>
> - [N] ComfyUI 节点源码 <https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py>
> - [M] FL2VA model_index <https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/FL2VA/model_index.json>
> - [L] LightX2V Turbo 规格表 <https://github.com/ModelTC/Minimax-H3-Turbo>
> - [LH] LightX2V HF 文件列表 <https://huggingface.co/lightx2v/Minimax-h3-Turbo/tree/main>

| 参数 | 值 | 来源/证据 | 状态 | 锁定日期 | 适用剧 |
|---|---|---|---|---|---|
| 进入条件 `R-C*` | 逐镜审计 pass（SOP ★5）：8 要素 + 衔接 + 帧闸门 + 提示词符合 H3 官方规范；不满足则 `blocked`/`skipped`，不消耗 GPU | AUD §2；SOP ★1/★3 | 锁定 | 2026-10-30 | 全部 |
| 模型 `P-A1` | `minimax_h3_fl2va_pruned_int8_convrot` | PL h3.dit；ep01-S1 A/B | 锁定 | 2026-10-29 | 全部 |
| 帧率 `P-B3` | 24 fps | [N] `FPS = 24` | 锁定 | 2026-10-30 | 全部 |
| 帧数 `P-B1` | 17k+5 网格，节点向上对齐；默认 243（10.12 s）；范围 124–362；按 `**时长**` 查 SOP §6 对照表 | [N] `align_frame_count`；[CN]；[K]（4–15 s） | 锁定 | 2026-10-30 | 全部 |
| 分辨率 `P-B3` | 768×1344（短边 768、面积 ≤768×1344、边长为 32 的倍数） | [N] `adapt_canvas`；[CN] | 锁定 | 2026-10-30 | 全部 |
| 关键帧预处理 `P-B2` | 首帧和尾帧都在本地用同一种方式 center-crop + lanczos 到 768×1344，断言尺寸并记录 sha | [N]（首帧 `"disabled"` 拉伸、尾帧 `"center"` 裁切）；[CN]；gpu3 WR L1174–1186 已实现 | 锁定 | 2026-10-30 | 全部 |
| 关键帧强度 | 没有这个参数（denoise 不影响 guide） | [CN] | 锁定 | 2026-10-30 | 全部 |
| CFG / 负面 `P-A2` `H3-A5` | cfg 1，BasicGuider，不加负面，不写否定句 | [C] | 锁定 | 2026-10-30 | 全部 |
| 提示词结构 `H3-A1`–`H3-A4` | 对齐句（逐字）→ 空一行 → `integrated_multimodal_description: [Shot 1]` → `overall_soundscape:` → `non_diegetic_music:`；单镜头；首帧状态 → 中间变化 → “settles into … established by Picture 2” | [G][K]；gpu3 WR L1240–1288 已实现 | 锁定（格式）；对一致性的效果 → 需 A/B（H3R 实验 1） | 2026-10-30 | 全部 |
| S.SS `H3-A1` | `f"{frames/24:.2f}"`，两位小数 | [G] | 锁定 | 2026-10-30 | 全部 |
| 语言 `H3-A7` `H3-D1` `H3-D2` `H3-D3` | 正文英文；台词逐字中文放在 `<d>[Chinese] …</d>` 里；说话人编号 (S1)/(S2) 和音色描述写在 `<d>` 外 | [G][K][C] | 锁定 | 2026-10-30 | 全部 |
| 画外音 `H3-D5` `H3-D9` | `says in an off-screen voiceover` + 嘴唇闭合句；截断用 `<cutoff>`，跨切用 `<scenetrans>` | [G] | 锁定 | 2026-10-30 | 全部 |
| overall_soundscape `H3-S1` `H3-S2` | 1–4 句英文，写成一段：环境声、动作声、非语言人声，不重复台词 | [G] | 锁定 | 2026-10-30 | 全部 |
| non_diegetic_music `H3-S3` | `N/A`（配乐交给后期 BGM） | [G] 允许 N/A；PL | 锁定 | 2026-10-30 | 为他而骚 |
| 发声人数 `H3-D7` | 每镜只让一人发声，亲密镜只让林晚发声；普通对话镜暂按官方 (S1)(S2) 双人语法 | intimate_audio.md【未验证】；官方未要求 | 待验证（冲突已报协调，等项目方定） | — | 为他而骚 |
| 运镜 `H3-A10` | 每镜一个运镜，写成自然句子；幅度、速度词按 [G] | [G]；“一镜一运镜”来自 [R] 社区 | 锁定（词汇）/ 待验证（一镜一运镜） | 2026-10-30 | 全部 |
| 提示词长度上限 `H3-A12` | 无官方硬上限；API 7000 字符 | [R] 引 vLLM recipe，未抓取 | 待验证 | — | — |
| 加速 LoRA 版本 `P-A4` | gpu3 现在代码的 t8 = `minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16`（WR L1019，文件已在 loras/）；PL.json 仍写 `v1.0_768p` | gpu3 WR 源码 + loras 目录（22:40 巡检）；[LH] 两个文件都存在 | **需 A/B**（v1.0_768p vs v1.1_768p vs 基模 20 步，固定种子 9:16；H3R 实验 3）；A/B 后 PL 也要同步 | — | — |
| 加速 LoRA shift `P-A3` | 768p 版用 6/3（`MiniMaxH3SigmaShift`，WR `TURBO_SHIFT = (6.0, 3.0)`）；544p 版用 12/3 | [L]（v1.0_768p 行：6/3，“Recommended settings: 8 NFE, video shift 6, audio shift 3”）；v1.1_768p 这一行在 [L] 没抓到 | 配对规则锁定；v1.1 用 6/3 → 待验证 | 2026-10-30（规则） | 全部 |
| 加速步数 `P-A5` | 8 步（t8） | [L] 8step 行 | 锁定（随 LoRA 版本）；画质 → 需 A/B | 2026-10-30 | 全部 |
| 采样器 / 调度器 `P-A6` | euler + simple；不用 ancestral/SDE | [R]（LightX2V 讨论 #48、ComfyUI issue #15283，社区）；WR 视频 Turbo 档用 euler；HF Comfy #67：euler 让变暗约减半（docs/research/h3_deep/03 §2.1） | 待验证（官方未写；**gpu3 基模档 WR L1099 仍是 `res_multistep`** → 补丁 G1 + 实验 X2，见 docs/research_adoption.md）。笔记本 NR 已强制：拒绝 ancestral/SDE，基模档 euler | — | — |
| 缓存加速节点 `P-A7` | 不挂 EasyCache、Spectrum、TeaCache、Cache-DiT、Sol-Attn、torch.compile；不加 `--fast` | [R]（note.com 对比）；h3_deep/00 §二（≥5 人无反对）；gpu3 只读核实（h3_deep/00 §一，2026-10-30 晚：无缓存/Sol/compile/`--fast`） | 锁定（禁用）；笔记本 NR `H3_BANNED_NODES` + 单测 | 2026-10-30 | 全部 |
| 笔记本链对齐（NR） | `services/render_router/ns_render/workflows.py` 的 H3 默认值改为与本表一致：int8_convrot、v1.1 768p @1.0、`MiniMaxH3SigmaShift` 6/3（同时接采样与调度）、首尾帧同一 center-crop、768×1344、17k+5 且 124–362；出图前自检拒绝 w4a8+LoRA、shift 不配对、Turbo <6 步 | docs/research_adoption.md §二；tests/test_research_adoption_params.py | 代码值对齐（不改变上面各行的锁定/待验证状态） | 2026-10-30 | 全部 |
| 基模（升级/重试档） `P-A3` `P-A5` | 基模 20 步（可到 25），shift 12/3，无 LoRA | [CN]（20 默认，25 提高动作质量）；[M]（12/3）；PL fallback 20 步 A/B 通过 | 锁定 | 2026-10-30 | 全部 |
| 中间关键帧 `P-A8` | 必须经过某个姿态的镜头用 `MiniMaxH3AddGuide(frame_idx)`（负数从片尾往前数，没有强度参数） | [N] | 需 A/B | — | — |
| 视频 QC | owner_script_qc（脸/眼/字幕）+ 首帧 PSNR ≥20 dB + 结尾身份 SFace ≥0.30（取 1.5/3.5/5.5/7.5/9.9 s） | PL；WS `SIM_CLIP_MIN`、L883 | 锁定 | 2026-10-29 | 全部 |
| 去重键 `R-C9` | sha256(首帧) + sha256(尾帧) + 提示词哈希 + 参数；同一键不重渲 | TASKS 规则 7；SOP §9 | 锁定 | 2026-10-30 | 全部 |

## S5 成片 / 4K

| 参数 | 锁定值 | 来源/证据 | 锁定日期 | 适用剧 |
|---|---|---|---|---|
| 写 `_final` 的条件 | qa.json 全部 pass；否则只出 `_PREVIEW_未完成` | SOP ★1 | 2026-10-30 | 全部 |
| 转场 | 0.3 s 交叉溶解（项目方 AGENT-3） | AUD §3.5；WR `XFADE = 0.3` | 2026-10-30 | 全部 |
| 输出 | 1080×1920 H.264 CRF18（768×1344 → lanczos 1097×1920 → 裁切）；有 4K 时另出 2160×3840 | PL；SOP §13 | 2026-10-29 | 全部 |
| 响度 | 母带 −14 LUFS / −1 dBTP；独白处场景 −8..−12 dB；Foley −6..−10 dB | SOP §11 | 待验证（未成集实测） | — |
| 4K QC | 身份 ≥0.75、静态闪烁比 ≤1.6、ΔE ≤4.0 | gpu3 scripts/upscale_4k.py QC_LIMITS | 待验证（A/B up4k-test 进行中） | — |
| 4K H.264 成片编码（T38） | x264 CRF 17 + `-maxrate 60M -bufsize 120M -level:v 5.1 -profile:v high -pix_fmt yuv420p`（原 CRF 20 无 VBV） | docs/upscale_4k.md “Notes for T38”（实测 σ2 颗粒 @CRF17 ≈39 Mbit/s）；`services/post/ns_post/assemble.py` Settings.crf_4k/maxrate_4k/bufsize_4k/level_4k | 2026-10-30 | 全部 |
| 视频逐镜校色（PI-19） | `ns_post.colormatch`（LAB gain+bias，首尾关键帧两端插值，strength 0.8，region centre）；**默认关**，等每个 take 的实际首尾帧同步后做 CPU 实验 X10 再定 | h3_deep/00 §二 颜色 1；docs/research_adoption.md B1（ep01 dry-run：6 镜只有 S3 有匹配首帧） | 待验证 | — |
| 声音资产 | 配乐与音效库只用 CPU，可与 S3 并行，不占 GPU 优先级 | SOP ★1 | 2026-10-30 | 全部 |

## 就绪闸门（8 要素 + 衔接）

| 参数 | 锁定值 | 来源/证据 | 锁定日期 | 适用剧 |
|---|---|---|---|---|
| 8 要素 `R-C1` | 首帧、尾帧（同一 take 链且过帧闸门）、img、motion、时长、sound/【H3 audio】（亲密镜头另加 sound_intimate）、本镜配乐 cue、本集 BGM | AUD §2、§4 | 2026-10-30 | 全部 |
| 衔接 `R-C7` | 同一场景内，上一镜尾帧 ↔ 本镜首帧通过衔接检查；每集生成 `continuity_sheet.jpg` | AUD §3.4–3.5 | 2026-10-30 | 全部 |
| 失败记录 | `status.json.blocked_reasons`；超过轮数记 `HARD_SHOTS.jsonl` | AUD §2、§3.4 | 2026-10-30 | 全部 |
| 熔断 | 一集 ≥3 镜失败 → 暂停该集；同类失败跨 3 集 → 判为系统性问题；单镜失败 3 次 → 进入异常队列 | SOP §10 | 2026-10-30 | 全部 |

---

## 变更记录

| 日期 | 改动 | 证据 | 写入者 |
|---|---|---|---|
| 2026-10-30 | P-A7 缓存加速节点改为锁定（禁用）；P-A6 注明 gpu3 基模档仍 res_multistep（待验证不变）；新增“笔记本链对齐（NR）”行、4K H.264 编码行、视频逐镜校色行（待验证）。没有把任何“需 A/B”项升为锁定 | docs/research_adoption.md（逐条来源 + gpu3 只读核实）；tests/test_research_adoption_params.py | agent E（协调派发，研究落地） |
| 2026-10-30 | 记录项目方决定：H3 A/B 推迟到 LoRA 与首尾帧之后；饰品 LoRA nprng2/lbrng9/lbrng9_beads 设为 deferred（等项目方修正） | 协调转达项目方决定 | claude-sop |
| 2026-10-30 | 给各行加上 rule_id（与 docs/audit/rule_ids.md v1 对应） | 项目方指令：逐镜审计硬规则 | claude-sop |
| 2026-10-30 | v3 切换闸门：renderer 的 S1_GATE 已合并（WR L50–54），改为锁定 | gpu3 源码 | claude-sop |
| 2026-10-30 | S4 表按项目方指令重写：逐项附官方链接（2026-10-30 WebFetch 核对 [G][K][C][CN][N][M][L][LH]）并加状态列；加速 LoRA 版本与 v1.1 shift、采样器、缓存、发声人数、长度上限标为待验证或需 A/B | 官方原文与源码抓取；gpu3 WR 源码 | claude-sop |
| 2026-10-30 | v3 切换闸门：暂存目录（staging_v3）已核实并锁定；renderer 的 s1_gate 检查仍待验证 | gpu3 v3_finish.sh 源码 + 目录实测 | claude-sop |
| 2026-10-30 | S2 表更新：LORA_REGISTRY 路径与登记流程；新增 v3 切换闸门一行（待验证：代码未合并） | 协调回复 + 巡检实测 | claude-sop |
| 2026-10-30 | 初版：从 VB、PL、WR/WS/WA 源码常量、H3R、AUD、REQ、CP、SOP 汇总；列出 5 处冲突，标为「待验证」 | 见各行来源 | claude-sop |
