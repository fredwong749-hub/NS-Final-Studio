# RSI 账本：每一次尝试 = 假设 → 实验 → 结果 → 结论 → 落到哪条规则

每行一个尝试，按主题分组。各列含义：
- **结论**：✅ 对 / ❌ 错 / ⏳ 待定（证据不够或还没跑）/ ◐ 部分对。
- **规则**：写入 `knowledge/rules/` 的条目 id。`tools/knowledge/compile.py` 会检查这一列引用的 id 都存在。
- **来源**：可以直接打开的报告；数字照原文。

只记技术与流程，不评价剧本内容。

## A. 运动、静止、卡顿

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| A1 | Turbo 8 步是 4 帧一顿和脚重影的主因 | ep02-S1，Turbo 8 步对照基模 24 步、只给首帧 | J4 1.34（z 3.6）→ 1.12（z 0.7），脚重影消失；S2 运动 0.18 → 0.51 px/帧 | ✅ | K-REN-002 | config/render_quality.json video_bases.default_decision |
| A2 | 首尾帧几乎一样 → 必然静止 | 读源码 + 统计 11 镜 | 尾帧每一步都被硬注入；改成只给首帧后，静止镜从 7/11 降到 2/11 | ✅ | K-REN-004 | docs/ep02_iter/h3_comfy_expert.md §0 第 3 条；LEARNED_SPECS.md §B |
| A3 | 后期去抖能消除 4 帧一顿 | 用 tools/dejudder.py 处理 Turbo / Pika 的 S1 | J4 1.34–1.52 → 1.08–1.09 | ✅ | K-LOOP-004 | docs/ep02_iter/LEARNED_SPECS.md §B |
| A4 | 32 步比 24 步动作更好 | R2，S2 基模 32 步 | mean 0.67，24 步是 0.75–0.90；泛红 0.29 | ❌ | K-REN-R10 | docs/ep02_iter/lab_recipes.md 批 2 补充 |
| A5 | Motion Repair 0.9 能改善动作 | D1，S1 基模 24 加 Motion_Repair_V2 0.9 | J4 1.14 → 1.35，动作量没有增加 | ❌ | K-REN-012、K-REN-R11 | docs/ep02_iter/lab_recipes.md 批 2 补充 |
| A6 | 736×1312（宽高 ≡32 mod 64）能减轻顿挫 | E2，S1 基模 24 | J4 1.393（z 4.6）；同镜 768×1344 的 t3 是 1.136 | ❌（只测了 1 镜） | K-REN-006 | data/ab/lab/scores/scores.md E2_S1_b24_736x1312 |
| A7 | 正文删掉 Picture 2 分句能救静止镜 | R7，S6 基模 24 加 I2VA 修正 | mean 0.33，仍然 fail | ❌（正确性要修，但救不了静止） | K-PRM-001、K-REN-R01 | docs/ep02_iter/lab_recipes.md 批 2 补充 |
| A8 | 静止情绪镜换 FL2VA/I2VA 配方能救回 | S6 / S10 跑遍 Turbo、基模 24 / 32、Pika、两个 seed | 全部 fail 或 warn（≤0.49） | ❌ | K-REN-R01 | docs/ep02_iter/lab_recipes.md 推荐表 |
| A9 | 基模 24 一定不卡顿 | 同配方不同 seed | S2 t5 J4 1.62，t6 1.11 | ❌（随 seed 变） | K-REV-R06 | data/ab/lab/scores/scores.md |
| A10 | 换 seed 能消掉镜内硬切 | S2 t5、S11 t3 | 新 seed 出的 14 条都是 0 处硬切 | ✅ | K-REV-R05 | docs/ep02_iter/lab_recipes.md 通用 |
| A11 | 长镜头用基模 24 + I2VA 修正走长道 | R9，S11（10 s） | pass，mean 2.74，J4 1.01，没有硬切 | ✅ | K-REN-R13 | docs/ep02_iter/lab_recipes.md 批 3 |
| A12 | 结尾落定 / 定住段 → 剪辑自动剪掉 | v1 合成 | v0 有 10/11 镜结尾定住；v1 起自动剪 | ◐（⑤ 剪辑仍是 3 分） | K-EDT-003、K-EDT-004 | docs/ep02_iter/v2a_review.md §2 |
| A-V2a | 收紧对白前后空档 + 无对白镜 ≤4 s 能把节奏提到短剧水平 | v1 同一批 take 试合成（pace_tighten，尾留 0.4 s、无每镜下限） | 81.4 s → 52.5 s（-35%，超目标）；S5 只有 0.25 s 台词被收到 1.5 s → 加每镜 ≥3 s、尾留 0.5 s | ◐（参数已调，planA 复测） | K-EDT-010 | data/ab/v2_iter/pace_test/ep02.timeline.json |
| A-PB1 | 静止情绪镜在保首帧路线（I2VA）上也能动起来：新提示词按秒分拍 + PDD 两段式 | PLANB B2：S6 / S3 / S8（同 seed 20261101，PROMPTv2 i2va） | S6 mean 0.84（v1 0.475；LAB 所有 FL2VA 配方 ≤0.49），S3 1.76（v1 0.48），S8 2.06（v1 0.98）；J4 1.12–1.16；S10 0.59 | ◐（变量是提示词 + 配方一起变的；S10 身份 0.19 不过） | K-REN-019、K-REN-R01 | docs/ep02_iter/planB_report.md §3 |

## B. 身份与人物一致性

| # | 假设 | 实验 | 结果 | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| B1 | Ref2VA 能救回身份、动作和泛红 | X1（S6）、X2（S1）、X3（S2）用 Ref2VA 两段式 | S6 mean 0.31 → 1.28；SFace 0.48 → 0.70；S1 SFace 0.24 → 0.53；S2 cheek_red 0.52 → 0.10 | ✅ | K-REN-011、K-REN-R02 | docs/ep02_iter/lab_recipes.md 批 2 |
| B2 | 用脸部裁切图代替整张定妆图，可以去掉服装渗漏 | X4，S2 | 服装恢复成剧本里的白衬衫；SFace 0.75 → 0.81；cheek_red 0.08；J4 1.03 | ✅ | K-AST-R03 | docs/ep02_iter/lab_recipes.md 批 3 |
| B3 | E5 multiframe（首帧 + 脸部参考）能同时保住构图和身份 | E5，S6 / S2 | 构图保住了；但 SFace 0.70 → 0.49、0.81 → 0.35，S6 mean 0.39 | ❌（身份跟着首帧走） | K-REN-R04 | docs/ep02_iter/lab_recipes.md 批 4 |
| B4 | Ref2VA 不给首帧时，构图仍会跟剧本走 | X1，S6 | 剧本是坐姿，出片变成站姿；台灯暖光和披外套都丢了 | ❌ | K-REN-R03、K-PRM-R01、K-WRT-R02 | docs/ep02_iter/lab_recipes.md 批 2 观察 2 |
| B5 | 项目方设定图流程能保住身份 | Qwen-Image 2.1 四栏设定图 | 左栏对定妆脸 0.926 | ✅ | K-AST-R05 | docs/ep02_iter/consistency_research.md |
| B6 | 叠加林晚出图 LoRA 能加强身份 | 同流程挂 lin_wan_qi_v1 0.6 | 0.926 → 0.823 | ❌ | K-AST-R04 | docs/ep02_iter/consistency_research.md R2 |
| B7 | 用设定图作参考出首帧（R 方式）能提升身份 | B4 R 方式 | 林晚 0.575 → 0.706；男角有了身份来源 | ✅ | K-AST-R01 | docs/ep02_iter/LEARNING_BACKLOG.md B4 |
| B8 | 只改定稿首帧、构图不动（E 方式）能换身份 | B4 E 方式 | 几乎换不动，男角换不动 | ❌ | K-AST-R02 | docs/ep02_iter/LEARNING_BACKLOG.md B4 |
| B9 | 视频身份 LoRA lin_wan_h3_v1 有增益 | B8 对照 | 0.66–0.67，不挂 LoRA 是 0.677 | ❌ | K-AST-R07 | docs/ep02_iter/LEARNING_BACKLOG.md B8 |
| B10 | 两个男角纯文字设定图能区分开 | B3 | 两人互相余弦 0.55；陈宇被人台外观污染 | ❌ | K-WRT-R04、K-AST-R06 | docs/ep02_iter/LEARNING_BACKLOG.md B3 |
| B11 | 按发色归人的 SFace 可以当身份闸门 | S9 / S10 审片 | 归错了人；和 ArcFace 不是同一把尺子 | ❌ | K-REV-R01 | docs/ep02_iter/LEARNING_BACKLOG.md B14 |
| B12 | 换脸后处理（character swap）可用 | B5 | 3090 上 768p 显存不够（OOM）；整栏参考 +0.08，但服装被换 | ⏳ 暂不用 | K-REN-R16 | docs/ep02_iter/LEARNING_BACKLOG.md B5 |
| B13 | 修脸（FaceRefine）能提升身份 | PLANB B2_S2_fr | SFace 0.331 → 0.365 | ⏳（只测了 1 镜） | K-REV-R09、K-REN-R19 | data/ab/planB/ep02/scores/scores.md |
| B-V2a | 纯 Ref2VA + 项目方挑定脸部裁切 + PROMPTv2 新提示词，身份和泛红比 v1 基模好 | 方案 A（loop ep02_v2 + fanout）：S2 t12、S4 t9、S6 t10/t11、S10 t6（gpu33，单段 24 步） | SFace S2 0.356→0.504、S4 0.457→0.718、S6 0.482→0.678、S10 0.176→0.289；cheek_red 全部 ≤0.076（v1 0.42–0.51）；S2 t12 全部验收项通过；S4 t9 后半段静止 54% | ✅（4 镜 / 5 条，各 1–2 seed；全集未跑，21:35 中止） | K-REN-011 | docs/ep02_iter/planA_report.md §2 |
| B-V2b | E5 multiframe（首帧作 Picture 1 + AddGuide）能同时保构图和身份 | 方案 A 19:27 旧组 S2/S3/S4（旧提示词 + 旧林晚裁切） | self 余弦 0.33–0.43；S2 脸颊 a* 漂移 20.6、S4 16.7；S4 中途跳切 3 处、结尾定住 1.4 s | ❌（与 LAB 批 4 一致） | K-REN-011 | data/iterate_loop/ep02_v2/events.jsonl；data/ab/v2_iter/cut_check.json |
| B14 | 造型版设定图（第三种模板：角色 + 姿势 + 服装单品图 / 写作方服装原文）能同时保身份、防服装渗漏和人台污染 | CONSIST：林晚 O1（lw-o09 + lw-s01 + 剧本原词），陈宇 O1（W7 补全原文），gpu36 GPU0/1 | 林晚对定妆 0.867、服装正确无项链；陈宇大脸对裁切 0.863、对顾沉 0.366，人台污染消失；项目方选"a"（林晚-O1 + 陈宇-O1，顾沉沿用 s101），已登记 role=item | ✅ | K-AST-004、K-AST-R01 | docs/ep02_iter/consistency_research.md §7；data/assets/identity_refs/manifest.json |
| B-PB1 | H3 FaceRefine（基模 10 步 denoise 0.42，无身份参考）能提高身份分 | PLANB：S2 / S3 / S4 修前对修后 | SFace 0.331→0.365、0.339→0.342、0.318→**0.257**（S4 下降，丢弃修脸版）、S10 0.187→0.188；10 步约 8 min | ◐（3/4 微升、1/4 下降；无身份参考时收益很小） | K-REV-R09 | data/ab/planB/ep02/scores/scores.md（B2_S*_fr） |

## C. 脸部泛红与调色

| # | 假设 | 实验 | 结果 | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| C1 | 泛红是 Pika 独有的 | 批 1：30 个版本加 S2 三个配方 | 基模 24 有 0.52，Turbo 有 0.41；Pika 0.5–0.67 最重 | ❌（所有配方都有，Pika 最重） | K-REN-R06、K-REN-013 | docs/ep02_iter/lab_recipes.md 批 1 |
| C2 | 泛红跟着提示词里的脸红类词走 | 按有无 flush 类词把镜头分组 | 有这类词：0.08–0.67；没有：≤0.08 | ✅ | K-WRT-R01 | docs/ep02_iter/lab_recipes.md 批 1 |
| C3 | 只给首帧会让泛红随时间加重 | S2 对照 | 只给首帧 0.41–0.67；首尾帧 t4 0.16 | ✅ | K-REN-R07 | docs/ep02_iter/lab_recipes.md 批 1 结论 3 |
| C4 | antiburn 0.7 或林晚 LoRA 能压住泛红 | R3、R6 | 0.65、0.67，Pika 本身是 0.61 | ❌ | K-REN-R09 | docs/ep02_iter/lab_recipes.md 批 1 |
| C5 | realism-people 1.0 能压住泛红 | D2，S2 同 seed | cheek_red 0.28 → 0.08；代价是动作量 0.90 → 0.64 | ⏳（1 个 seed） | K-REN-R08 | docs/ep02_iter/lab_recipes.md 批 3 |
| C6 | skin guard 能把泛红压到及格 | v2a 整集 | 峰值降 2.4～8.0 a*，泛红面积几乎不降（51% → 48%） | ◐ | K-LOOP-003、K-REV-R04 | docs/ep02_iter/v2a_review.md §2 |
| C7 | 编码 / 后期链路会加红 | 追踪去抖、校色、成片编码 | 前后都在 ±2 a* 内；dejudder 的 BT.601 标记问题已修 | ❌（后期不加红） | K-EDT-008 | docs/ep02_iter/LEARNED_SPECS.md §B |
| C8 | 关键帧 krea2 降到 0.25 能减轻首帧偏红 | leica_sharp S4 | 39.7 → 29.7（去掉 krea2）；质感是否受影响还没 A/B | ⏳ | K-REN-015 | docs/ep02_iter/LEARNED_SPECS.md §B |
| C-V2a | 合成时 skin guard（默认开）能让 ⑦ 调色及格 | v2a：v1 同一批 take 只改 skin_guard | 脸颊 a*p95 max 降 2.4–8.0；a*≥25 占比 S2 51%→48%、S3 49%→50%、S4 42%→43%；导演分 ⑦ 3→4 | ◐（压峰值不压面积） | K-LOOP-003 | docs/ep02_iter/v2a_review.md |
| C-PB1 | 新提示词（sysimpl-v2，去掉 flush 词）在同配方同 seed 下压住泛红 | PLANB：S2 PDD 两段式 seed 20261101，旧编译提示词（B1）对照 PROMPTv2 i2va（B2） | cheek_red 0.39 → 0.09，cheek_a95 漂移 +6.4 → +1.4；S3 / S4 / S6 新提示词 0.08–0.09；S8 长镜头 294 帧仍 0.29（a95 20.5→38.4） | ✅（短镜 4 镜）；长镜头 ❌ | K-WRT-R01 | data/ab/planB/ep02/scores/scores.md（B1_S2、B2_S2/S3/S4） |

## D. 提示词、写作与声音

| # | 假设 | 实验 | 结果 | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| D1 | 对白用 H3 原声比 TTS 更同步 | v0 两版对照 | TTS 版偏差约 2.5 s；H3 版相关系数 0.19–0.70 | ✅ | K-EDT-001 | docs/ep02_iter/v0_baseline_review.md §1 ⑥ |
| D2 | 独白可以超出镜长 | v0 S8 | 25.6 s 独白盖住 S9–S11 | ❌（一律判失败） | K-LOOP-001、K-EDT-006 | docs/ep02_iter/v0_baseline_review.md |
| D3 | 写作 LLM 会把舞台提示写进 <d> | 写作模型重放 | 4 次里有 3 次 S2 失败 | ✅（已加 llm_output_check 闸门） | K-PRM-010 | docs/ep02_iter/chain_audit.md §4 |
| D4 | I2VA 正文还引用 Picture 2，会造成矛盾 | 官方规范对照 | 11/11 镜存在；已修 | ✅ | K-PRM-001 | docs/ep02_iter/h3_official_conformance.md §1 B3 |
| D5 | 配乐写“作用 / 情绪”词不规范 | 规范对照 | 10/11 镜写了 “providing … layer” | ✅ | K-PRM-008 | docs/ep02_iter/h3_official_conformance.md §1 B17 |
| D6 | 节奏慢的原因在写作动作量太少和偏慢词 | v1 归因 | 每秒 11–22 词；4 镜写了 slowly 一类的词；VOICE 写了 slow pace | ◐（规则已确认，效果待 v2 成片） | K-EDT-I01 | docs/ep02_iter/prompt_bug_v1.md §5 |
| D7 | 按秒时间码 `At 00:SS.mmm` 能改善时间轴 | v1 归因：11/11 镜没有时间码；风险：官方 base-en 里这个写法是“切镜”标记 | 硬切风险已有 4 个样本：Ref2VA 3 镜（V2：S4/S6/S10）+ I2VA PDD 1 镜（PLANB：S2）都是 0 处硬切；时间轴本身的改善（动作是否按拍落点）还没测；方案 C 的 S2/S5 在跑 | ◐（硬切风险 ✅ 无；改善 ⏳） | K-PRM-I01、K-WRT-102 | data/ab/v2_iter/cut_check.json；data/ab/planB/ep02/scores/scores.md；docs/ep02_iter/prompt_bug_v1.md |
| D8 | 分拍写视线 / 表情 / 反应能改善眼神戏 | v1 归因 | 规则已确认，还没出片验证 | ⏳ | K-WRT-I02 | docs/ep02_iter/prompt_bug_v1.md |
| D9 | 有“下镜”的接力镜头切换更顺 | v1 归因：RL-T5 / T6 各 11 次 | 规则已确认，还没出片验证 | ⏳ | K-WRT-I01 | docs/ep02_iter/prompt_bug_v1.md |
| D10 | Ref2VA 加 <Audio> 能锁住音色 | X3 S2 | ASR 字全对，但 4.6 s 才开口 | ◐ | K-REV-R08、K-AST-R09 | docs/ep02_iter/lab_recipes.md 批 2 |
| D11 | 旁白显老是音色选错了 | 项目方 v1 审片 | 规则：独立 narrator 音色，具体音色等项目方挑 | ✅（项目方第二轮选定 QAg，见 D13） | K-EDT-I02、K-EDT-013 | docs/ep02_iter/writer_requests.md |
| D13 | 换成年轻的“电台主播”式设计音色能解决旁白显老 | 两轮挑选页：Kokoro 55 个中文女声初筛 → 16 条；Qwen3-TTS VoiceDesign 4 音色 × 2 语气 + CosyVoice3 → 17 条 | 项目方原话“oag音色”“QAg（深夜电台·温柔）”“采取”；QAg 基频 226 Hz（旧 zf_067 约 273 Hz、HNR 8.3 dB 偏沙），回听 CER 0 / 0.04 | ✅ | K-EDT-013 | data/review_pages/narrator_pick/index.html；data/assets/proposals/narrator_voice_candidates.json |
| D14 | 设计音色要先固定参考再复刻，才能 60 集同一个声音 | 同一参考 ref.wav，3 句剧本旁白原文，CAM++ 说话人相似度 | CosyVoice3 zero-shot 0.951–0.957（均值 0.954）；Qwen3-Base 克隆 0.934；每句重新 VoiceDesign 0.73；管线实测 ep01-S7 0.954、CER 0.057、−15.9 LUFS | ✅ | K-EDT-014 | data/assets/voices/narrator_qag/voice.json |
| D15 | CosyVoice3 能直接装进 Qwen3-TTS 的同一个 venv | gpu36 venv_tts（transformers 4.57.3） | 4.57.3 下输出乱码（ASR 回听“他作带我这笔…”）；换 4.51.3 叠加目录后正常；自由描述的 instruct 会失控 | ◐（同 venv 可以，但 transformers 要单独叠加） | K-EDT-015 | data/review_pages/narrator_pick/_tools/r2/ |
| D12 | 音频三条硬规则（`</d>` 前句号、写 soundscape、不说话的人写 silently）能减少乱语 | E10 | 还没跑 | ⏳ | K-PRM-002、K-PRM-003、K-PRM-004 | docs/ep02_iter/h3_comfy_expert.md §8 |
| D-V2a | 新提示词 `At 00:SS.mmm` 分拍会让 H3 在时间码处硬切 | cut_check（motion_qc 跳切 + HSV 直方图硬切，对照时间码 ±0.5 s），新提示词 Ref2VA 前 2 镜 | 新组 S2 t12、S4 t9、S6 t10/t11、S10 t6：0 处硬切（6 条 / 4 镜）；旧组（无时间码）S3 1 处、S4 3 处、S8（基模）1 处 | ✅（Ref2VA 线，6 条；I2VA 线看 PLANB） | K-EDT-011 | data/ab/v2_iter/cut_check.json |
| D-V2b | ep02 去掉 S8/S11 内心独白，S8 不再溢出 | 合成开关 post.voiceover_drop {"2":[8,11]}（项目方原话“A. 去掉”） | 测试通过；成片待 planA | ⏳ | K-EDT-012 | config/render_quality.json post.voiceover_drop；tests/test_v2_pace.py |
| D16 | ep04 合成失败是 TTS 坏了 / 缺音色 | 读 night.log 16:09 报错 + data/cache/tts 文件时间 + `assemble_episode.py ep04 --lines-only` | 报错的 fd441690….tmp.wav 对应的 .wav 16:09 已写出；ep04-S1#0 与 S2#0 都是陈宇同一句 → synthesize_cached 去重拿 .wav 比 .tmp.wav 永不相等，同一 tmp 入队两次 | ❌（根因是去重 bug，不是音色 / 模型；VOICE10 11-01 修） | K-EDT-019 | data/pipeline/runs/series10_v1/video/night.log 第 379 行；tests/test_voice10_fix.py |
| D17 | 合成前只查解释器不够 | tts_preflight 逐项查解释器 / 模型目录 / 每角色参考音频 sha / ref_text / 远端模型 | 笔记本实测缺项 0（tests/test_voice10_fix.py::test_tts_preflight_on_this_project_config）；speakers.py 旧剧称呼隔离后全 10 集说话人都有音色 | ✅ | K-EDT-020、K-EDT-021 | services/post/ns_post/tts.py tts_preflight；services/post/ns_post/speakers.py LEGACY_60EP_TITLES |

## E. 参数、算力与工程

| # | 假设 | 实验 | 结果 | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| E1 | comfy kitchen INT8 注意力有画质损失 | X1 对照 X5，S6 同 seed | mean 1.28 / 1.30，J4 1.38 / 1.40，SFace 0.70 / 0.71 | ❌（没有测到损失） | K-REN-R12、K-REN-005 | docs/ep02_iter/lab_recipes.md 批 4 |
| E2 | res_multistep 比 euler 好 | E4 | 还没跑 | ⏳ | K-REN-003 | docs/ep02_iter/h3_comfy_expert.md §8 |
| E3 | 两段式（0.52 MP → 3D 放大）省时间又保质量 | E1 / PLANB pdd2 | PLANB B2_S2：cheek_red 0.09，SFace 0.33，mean 0.86；加修脸约 22.7 min（gpu_s 1362） | ⏳（上采样器待许可登记） | K-REN-010、K-REN-R02 | data/ab/planB/ep02/scores/scores.md；data/ab/planB/ep02/logs/B2_S2.log |
| E4 | 3090 能跑 260 帧以上 | ep02-S8 | 243 / 260 帧可以；277 / 294 帧 OOM，改走 gpu36:2 novram | ✅ | K-REN-008、K-OPS-001 | config/render_endpoints.json |
| E5 | API 重启会丢作业 | chain_audit E6 | 9 个作业中断，4 个已出片的结果丢了 | ✅（loop 已改为结果先落盘、丢了能找回） | K-OPS-002 | docs/ep02_iter/chain_audit.md §2 E6 |
| E6 | Ref2VA 用 Turbo 少步数也够 | 社区 + 官方 | 参考图几乎不起作用 | ❌ | K-REN-R14 | docs/ep02_iter/h3_comfy_expert.md §4 |
| E7 | 缓存 / 加速节点无害 | 社区多帖 | 会改变长相、带来背景杂音 | ❌ | K-REN-007 | docs/ep02_iter/h3_comfy_expert.md §2 |
| E-V2a | 派单只数本 loop 的作业就够 | 与 LAB/CONSIST 共用 6 道 | 单道会排到 3–4 个；改为数 ComfyUI /queue + API queued，总负载 ≥2 不派 | ✅ | K-REN-018 | tools/iterate_loop/submitter.py；tests/test_iterate_loop.py |
| E-V2b | 30 s 提交超时够用 | Ref2VA 经 :8800 上传参考图 | 20:24 三次提交 30 s 超时但服务端已收下（S2/S6/S10 seed 变体）；改 180 s + 按 seed 找回后无重复提交 | ✅ | K-REN-018 | tools/ep02_iter/fanout.py；data/ab/v2_iter/fanout/run.log |
| E-V2c | “新提示词组”两份文件 md5 相同 = 取错源 | 核对作业 recipe.plan_hash → 计划提示词 | 相同的是 R-RED 第 1 步只开 skin_guard 的同一次出片；loop 现记 post_only_of / source_file | ✅（不是取错源，记录不清） | K-REN-018 | tools/iterate_loop/loop.py；tests/test_iterate_loop.py::test_post_only_step_marks_same_source |
| E-PB1 | PDD-Acc 8NFE 两段式在同 seed 下与基模 24 单段质量相当、耗时约 1/4 | PLANB：S2 新提示词 seed 20261101，B2（PDD 两段式）对照 R0（基模 24 单段），gpu36 限 200 W | mean 0.86 / 0.87，J4 1.06 / 1.13，cheek_red 0.09 / 0.08，SFace 0.33 / 0.35；生成约 9 min / 44 min（gpu_s R0 2637.7） | ✅（1 镜同 seed，继续逐镜） | K-REN-019、K-REN-010 | docs/ep02_iter/planB_report.md §1；data/ab/planB/ep02/scores/scores.md |
| E-V2d | Ref2VA 单段 24 步在 3090 上的时间 | gpu33:0/1/3，158 帧 768×1344 | render_s 1961–2643 s（33–44 min / 条），上传 3–30 s；S8 294 帧基模 24 在 gpu36:2 novram 5720 s | ✅（6 条） | K-REN-011 | data/renders/ep02/S*/takes.json params.render_s；docs/ep02_iter/planA_report.md |


## F. 上游写作链条：规模化 10 集新剧（SERIES，series10_v1，2026-10-31）

| # | 假设 | 实验 | 结果 | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| F1 | 写作模型能一次把 60 集逐集梗概压成 10 集 Brief，并遵守人物 ≤4、场景 ≤6 的规模约束 | P0，约束写进系统提示词 | 1 轮通过（$0.0055）；4 人、6 场景 | ✅ | K-WRT-201 | data/pipeline/runs/series10_v1/P0_brief.report.json |
| F2 | 现行 P1-P2 / P2-P3 规则够用，不需要加新约束 | v1 + v2 各 10 集 | P1-P2 20 次里 19 次一轮过（ep02 一次 EO-04）；P2-P3 20/20 一轮过 | ✅ | — | data/pipeline/runs/series10_v1/drive_log.jsonl |
| F3 | 剧情里出现表外人名会一路带到 P4 修不掉，应在 P1 就拦 | P1 v2 加机检 HC-05 | 第 0 轮拦下 ep8 “Alex”，第 1 轮改为画外 / 不点名后通过；v1 没拦，P4 镜6 LK34-04 两轮修不掉 | ✅ | K-WRT-201 | data/pipeline/runs/series10_v1/P1_rev2.report.json |
| F4 | 写作模型默认每镜 6 秒，8 镜上限只有 48 秒，是 QW-E3 的主因；输入里给“镜数 → 平均秒数”表能解决 | P3-P4 第 1 次（无表）→ 第 2 次（有表）→ v2 | 总时长 <50 秒：7/10 → 3/10 → 0/9（v2 全部 50–57 秒） | ✅ | K-WRT-203 | data/pipeline/runs/series10_v1/v1_snapshot/ep07/attempt1/P4_ep07.md.report.json |
| F5 | 返修改镜长时不补分拍是 SS-M2 的来源；返修消息点名同步改就能消掉 | 第 1 次 → 第 2 次 | 终稿 SS-M2：5/10 → 0/10；v2 又在 3 集出现（ep02 / 03 / 05，只差最后 0.5–2 秒） | ◐ | K-WRT-204 | data/pipeline/runs/series10_v1/v1_snapshot/ep05/attempt2/P4_ep05.md.report.json |
| F6 | 登记每人 2–3 套固定造型并要求 P4 照抄，能把跨集造型收敛到可复用的设定图 | v1（无登记）对照 v2（P1_looks + 输入附本集登记造型） | v1 林晚 10 集 10 套服装、顾沉 7 套；v2 只有 2 集造型 EN 偏离登记（HC-06 warn） | ◐（待出片验证设定图复用） | K-WRT-202 | data/pipeline/runs/series10_v1/P1_looks.json |
| F7 | 成年硬约束的英文禁词可以包含 minor | v2 P3-P4 | 配乐 “68 BPM, A minor,” 和 “minor key” 两次误判 HC-02，返修轮次全耗在它上面；去掉 minor 后不再误报 | ❌（已改：英文 minor 不进禁词表） | K-WRT-205 | data/pipeline/runs/series10_v1/ep04/v2_hc_false_positive/P4_ep04.md.report.json |
| F8 | P3-P4 每次 ≤2 轮返修就能清零 | v1 两次 + v2，各 10 集 | 通过 0/10 → 1/10 → v2 1/10（剩余 block 合计 35 条：H3-X1 9、H3-X4 7、SS-M2 6、H3-X3 6、其他 7）；剩下的多是 H3-X3（说话人首句缺 VOICE）、H3-X4（不在画角色外貌进正文）、LK34-01/03（台词 / 独白逐字） | ⏳（这几类需要像 F4 一样写成更具体的输入句） | K-WRT-204 | data/review_pages/series10_v1/index.html |

## G. PROMPT：提示词时间轴、镜头语言、出图景别（2026-10-31）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| G1 | 写作模型按 sysimpl-v2 规则重写 H3 提示词层，台词逐字不变 | rewrite_ep02：abliteration 共 2 次调用（1 次首稿 + 1 轮返修），llm_output_check 校验 + lint_timeline 严格模式 | 11/11 机检通过；台词 8/8 逐字一致；正文 106–142 词 → 258–334 词；偏慢词 4 镜 → 0；拍长 1.6–2.1 s；花费 $0.14 | ✅（格式；出片效果见 D6–D9） | K-PRM-I01、K-WRT-108 | data/ab/prompt_v2/ep02/manifest.json |
| G2 | 时间轴 lint 一上来就设成 error，能逼写作方 | RL-T1/T3/T5/T6 默认 error 上线 | 现有剧本提示词全部不过，方案 A 的 loop 把 S1/S5/S7/S9 标成 needs_writer，gpu33 险些空转 | ❌（改成开关：默认 warn，导入 v2 稿的集才设 error） | K-PRM-I01 | config/recipes/timing_lint.json |
| G3 | 写作模型开着推理也能一次写完 9 镜 | 方案 C 导演稿转写，max_tokens 24000 | 3/3 次在 24000 token 处截断（推理 19–24k）；关推理后 11k token 一次写完 | ❌（默认关推理） | K-WRT-108 | data/pipeline/runs/ep02_claude_director_v1/ledger.json |
| G4 | 返修消息只列错误码，写作模型就会改 | 方案 C 转写，validate 的 block 原样回给写作模型 | H3-X3（VOICE 没逐字照抄）连续 3 轮 7 处不变；返修消息里给了逐字模板句之后，1 轮清零（block 35 → 2，剩下 2 个是导演稿本身的设计） | ✅（返修要给模板句，不只给错误码） | K-WRT-108 | data/pipeline/runs/ep02_claude_director_v1/run5.log |
| G5 | 出图提示词拼上整套造型不影响景别 | 方案 C 预览：S1 导演稿要求手部特写起手，提示词含 12cm 细跟、漆皮短裙；修正后按景别取舍再出 S1、S2 | 修正前 S1 出成全身坐姿（_wrong_framing/S1_1_fullbody.png）。修正后：S1 是胸部以上、双手放在键盘上（离手部特写还差一档）；S2（中景过肩）构图对上导演稿，前景是林晚背影、顾沉正面拿方案，鞋没有入画。只出了 2/9 张就按项目方指令停了 | ◐（2 张样本里景别都比修正前更接近设计；特写还要更强的首句约束） | K-REN-101、K-REN-102 | data/pipeline/runs/ep02_claude_director_v1/preview/；data/review_pages/ep02_planC/index.html |
| G6 | 纯 Ref2VA 正文里可以留“established by <Picture 1>” | 方案 C 编译检查 | 参考图只是脸部身份，不是首帧；这句会让模型去对齐一个不存在的首帧 → 编译器删掉该子句，构图写进第一句 | ⏳（修正已上线，效果待出片） | K-PRM-103 | services/recipes/ns_recipes/prompt.py build_ref2va |
| G7 | 分拍解析按“；”切开就能对上每一拍 | 写作模型在一拍里用“；”分隔两个人（ep02 S2） | 拍被截断，视线 / 表情 / 反应三个槽位丢了一半（S2 只解析出 2/4 拍）；改成“；”后面跟时间段才断拍 → 4/4 | ✅ | K-PRM-I01 | services/recipes/ns_recipes/spec_import.py parse_beats |

## H. 界面：前后端连接（UIDEBUG，2026-10-31）

| # | 假设 | 实验 | 结果 | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| H1 | 前端 /api 调用和后端路由能靠人工对齐，不需要机检 | check_wiring.py 静态比对 159 处调用 × 代码现算 OpenAPI（192 条路由） | 路由 / 方法 / 必填字段 E 级 0 个；但旧组件删掉后 74 条后端路由前端没有入口、27 个接口封装已无调用方 | ◐（对齐靠得住，下线功能没人记账 → 进 CI，unused 列给 UIRSI 确认） | K-UI-007 | docs/uirsi/debug_wiring.md §2 |
| H2 | 代码里加了路由，页面就能用 | 同一脚本对运行中的 :8800 openapi | /api/story-runs 8 条只在代码里，新建剧本页 404（“写作记录暂时读不到”） | ❌（有任务在出片不能重启 → 交付写“待重启生效”，前端 404 降级） | K-UI-008 | docs/uirsi/debug_wiring.md W-01 |
| H3 | 渲染道 / 出图参数接口慢是前端问题 | 无头 Chrome 记网络 + 单独计时 | lanes 页面里 4–10 s、单打 8 s（6 个隧道探测 2.4–4.4 s + 缓存 15 s 一过期就现探）；image-presets 页面里 36–40 s、单打 0.04 s（object_info 缓存过期才慢） | ✅（后端展示路径改先给旧值后台刷新；选卡 / 校验仍现取） | K-UI-009 | tests/test_uidebug_lanes_swr.py |
| H4 | 一个页面同一接口只请求一次 | 运行时网络记录 | ep02 加载 /api/episodes/2/produce 并发 4 次，render-backend / lanes 各 2 次（StrictMode 开发态翻倍） | ◐（共享读取，交给 UIRSI） | K-UI-010 | docs/uirsi/debug_wiring.md W-09 |

## UI. 界面（UIRSI，2026-10-31；分数见 docs/uirsi/rounds/）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| U1 | “新建剧本”入口消失是被删了 | 查 UX5/UX6 日志与 TopBarV3 注释 | 没删：UX5 D2 把步骤①改去资料清单 + v3 顶栏把“剧本▾”收进工具▾；顶栏常驻后找到它 2 次点击 → 1 次（N） | ✅（入口要常驻顶栏） | K-UI-001 | docs/uirsi/STATE.md §2 |
| U2 | 写作链每段产物放进界面能让 P0→P4 可确认 | 新建剧本页 + /api/story-runs，mock 写作模型 8 条测试 | R1 3→7、R2 4→7（r0→r4）；改原文 / 返修 / 下游挪 superseded 均测试通过 | ✅ | K-UI-002, K-UI-003 | docs/uirsi/rounds/r1-r4.md |
| U3 | 删旧壳不丢功能 | unreachable.mjs 可达性 + 人物登记并入资产中心 | 31 个文件归档、构建不到 0；tsc / build / 测试全过；R5 5→7 | ✅ | K-UI-011 | docs/uirsi/rounds/r5-r7.md |
| U4 | 排版问题能自动量化 | audit.js 计算样式统计 24 张截图 | 间距离网格 1753→116、非 token 字号 96→0、对比度不达标 197→21、单字成行 16→2；R14–R17 6.7/8.5/4.6/3.9 → 9.5/9.7/9.6/9.2 | ✅ | K-UI-012, K-UI-013, K-UI-014 | docs/uirsi/rounds/r5-r7.md |
| U5 | 白字在 #5b8cff 上可读 | 对比度计算 | 3.16:1（不达标）→ #3f6fe6 4.54:1 | ❌→改 token | K-UI-013 | apps/web/src/theme.css |
| U6 | 最新成果能直接在页面上看到 | series10_v1 / 方案成片 / identity_refs 接入 | 整季 10 集可按集看（P4 通过 1/10）；资产卡显示挑定设定图 + 身份参考；方案 A/B/C 成片出来后自动列出（测试） | ✅ | K-UI-015 | tests/test_cuts_plans_uirsi.py |
| G8 | 方案 C（导演稿 → 写作模型转写 → Ref2VA）能在一晚出 9 镜 × 2 seed 的对照成片 | 21:00–21:40 在 gpu36:0 和 gpu33:3 插队出预览图 / 视频 | 21:40 项目方指令全部卡转去新 10 集剧本，方案 C 停止：预览图出了 2/9；视频 0 条（gpu33:3 的 S2 official 在 21:25 提交，被中断）；转写和编译产物齐全（P4_ep02.md、prompts/ 9 镜 Ref2VA + I2VA、validate blocking 2 个且都是导演稿设计）。硬切结论只能用 V2 / PLANB 的 4 个样本（0 处硬切，见 D7） | ⏳（停止；产物留在审片页） | K-WRT-101–108、K-PRM-101–103、K-EDT-101/102 | data/pipeline/runs/ep02_claude_director_v1/report.json；data/review_pages/ep02_planC/index.html |
| G9 | 卡只靠“队列空才交”能插进 A/B 的排队 | 预览图第一张：gpu36:0 等空队列 | PLANB 道上一直有 4 个排队，26 分钟才轮到第一张；改用 front=true 插队首后，每张约 1.5 分钟 | ✅（总调度批准插队时用 front=true，每道同一时间只占 1 个） | K-WRT-108 | data/pipeline/runs/ep02_claude_director_v1/preview.log |
| F9 | 返修消息不带镜号也能修好 | 读 writer_prompt.repair_message：只发规则号 + 消息，丢了 field | SS-M2 只说“分拍只写到 6.0s，镜长 7.0s”，写作模型不知道是哪一镜；加上镜号 + 预拼片段后，ep01/02/04/06/08 第一轮就清零（之前 2 轮修不好） | ❌（已修：repair_message 带 field） | K-WRT-206 | data/pipeline/runs/series10_v1/ep02/P4_ep02.md.report.json |
| F10 | H3-X1 / X3 / X4 让写作模型自己逐字照抄就行 | v2 终稿 22/35 条是这三类；逐镜读原文 | 根因三种：a 被改成 one、VOICE 被意译（voice → tone）、画外说话人为满足 D8 写了全外貌；改为系统预拼片段（经真实 lint 验证同时满足 X1/X3/X4/D8） | ❌（改为系统预拼，写作模型照抄） | K-WRT-206 | tests/test_p4_fragments.py |
| F11 | LK34-03 “拼接后不相等”足够让写作模型找到问题 | ep03 / ep05 返修 2 轮未过 | 实际原因：同一镜写了两条 🎙（导入器只认一条）、同一独白跨镜重复；返修消息改为点明原因后 ep03 一轮清零 | ❌（已改：speech_lines 点明原因） | K-WRT-206 | data/pipeline/runs/series10_v1/ep03/P4_ep03.md.report.json |
| F12 | 修 “A minor” 误判只能把 minor 移出禁词表 | 改为排除音乐调式上下文 | A minor / C# minor / minor key / minor chord 不报；she is a minor / minors 照拦；测试 tests/test_hard_constraints.py | ✅（成年人校验没有变弱） | K-WRT-205 | tests/test_hard_constraints.py |
| F13 | 剧情可以改锁定角色的发色（ep03 “为他改换发色”） | 项目方决定改掉；加 HC-07 机检 | storyline 第 0 轮被 HC-07 拦在 owner_line（来自 P0 Brief），先改 Brief 再改 storyline 后通过；ep03 P2–P4 重跑通过 | ❌（项目方：形象一致优先） | K-WRT-207、K-AST-202 | data/pipeline/runs/series10_v1/P1_hairfix.report.json |
| F14 | 新标志物（左耳后小痣）可以加到已定妆角色上 | 项目方决定不要 | 改为钻石水晶甲；P1_looks、5 集 P3、9 集 P4 由写作模型替换，台词 / 独白逐字核对不变 | ❌（标志物只用已定妆里有的东西） | K-AST-202 | data/pipeline/runs/series10_v1/owner_decisions.json |
| F15 | 返修时转述规则号 + 校验消息就够了 | series10_v1 P4 第 1–2 轮 vs 确定性点名（镜号、原文、目标镜、枚举值） | 转述时 2 轮清零 0–1/10；确定性点名后：35 条 → 一轮清 6 集，再一轮清 1 集；剩余 2 集（ep09 / ep10）是“台词放哪一镜 / 拆镜”的内容决定 → 待人工；ep05 【配乐】避让枚举由系统确定性修正 | ❌（返修指引必须确定性点名；点名后仍不过不再找写作模型） | K-WRT-208、K-WRT-206 | data/pipeline/runs/series10_v1/ep05/P4_ep05.md.report.json |
| G10 | sysimpl-v2 新提示词（按秒分拍、视线 / 表情 / 反应、去掉偏慢词）让动作更多 | PLANB 用新提示词 S*.i2va.txt，PDD 两段式 seed 20261101，出了 S2/S3/S4/S10，外加 S6、S8 的生成版 | 运动 mean 对比 v1 成片：S3 0.48→1.76，S6 0.475→0.84，S8 0.98→2.06。同配方同 seed 新旧提示词对照只有 S2 一组：泛红 0.39→0.09（见 C-PB1），运动另记在 planB_report §3 | ◐（与 v1 的对比混入了配方变化：v1 是基模 24 / Pika，新组是 PDD；同配方的动作量对照只有 S2 一组） | K-PRM-I01、K-EDT-I01 | data/ab/planB/ep02/scores/scores.md；docs/ep02_iter/planB_report.md §3 |
| F16 | 漏台词 / 一镜两人这类结构问题，让写作模型自己决定放哪、怎么拆就能修好 | 前两轮放手给写作模型 vs 系统先算候选（p4_fragments.missing_line_options / split_two_speaker_plan），写作模型只调用 1 次、只在选项里选 | 放手时 ep09 / ep10 修 3 轮都不过（还把镜数拆到超上限）；给选项后 ep10 一次清零，ep09 从 3 条降到 1 条（剩锚点句漏造型 EN） | ◐（结构问题由系统给确定选项有效；锚点片段仍会漏） | K-WRT-208 | data/pipeline/runs/series10_v1/ep10/P4_ep10.md.report.json |
| U7 | 不删数据也能让界面“只剩最新” | 资产中心默认“当前剧本”范围、成片按最近 replace 导入折叠、新图接口先显示 | 资产中心隐藏 87 个当前剧本没用到的旧资产；成片按 replace 导入切分（测试）；R10 8→9、R17 9.2→9.7（r10 直连 :8800 实测） | ✅ | K-UI-016 | docs/uirsi/rounds/r8-r10.md |
| F17 | 剩下的锚点句问题要人点头才能由系统补 | 写成 p4_fragments.auto_fix 自动步骤（run_chain 返修用完后自动执行，block 变少才采用） | ep09 的真因是合并镜后造型切换行仍写旧镜号“镜5起”（不是锚点句漏写）；auto_fix 只改这 1 行 → 0 block。10/10 集 0 block | ✅ | K-WRT-209 | data/pipeline/runs/series10_v1/ep09/P4_ep09.md.report.json |
| F18 | 首帧作业照抄 img 原文就行 | PROMPT 用 audit_framing 审 80 条 | 景别取舍 80/80 合规；但 graph 不加载 LoRA，提示词混入触发词（lnwan01 16、hh12clear 6、ptxcorset 2、pose_ 1）→ 出图前去掉 | ◐（已改：作业生成时去掉触发词） | K-WRT-210、K-REN-101 | data/pipeline/runs/series10_v1/assets/first_frame_jobs.json |
| G11 | 流水线 / IMGGEN 自己拼出图提示词也能符合系统规则 | 审核 series10_v1 的 80 条首帧作业（SERIES 自拼） | 视频触发词 lnwan01 混入 16 条（SERIES 事后手工剥掉，连同应保留的出图触发词 lnwan_qi / LoRA 一起剥掉）；没有角色锁、【场景】段、材质 / 纠正器条目、剧本统一后缀。改由 tools/pipeline/image_jobs.py 经 ns_agent.compiler 重建：80/80 = 编译器输出，lin_wan_qi_v1 0.8 挂进作业图，首句景别构图全部合规，0 处视频触发词；submit_jobs 加“提示词 == 编译器输出”闸门 | ❌（自拼绕开规则）→ ✅（统一走编译器） | K-REN-103、K-REN-101 | data/pipeline/runs/series10_v1/assets/framing_audit.json；tests/test_image_jobs.py |

| UIA1 | 按"对象 × 操作"契约逐格实测，比看报告更能发现缺口 | UIAUDIT r1：detect.mjs 真实点击 23 页 + 10 任务 + 40 滚动组合 | 契约覆盖率 34%（43/125）；任务分 47/100；EditButton/DeleteButton 全站 0 处挂载、删旧剧本 0 分，此前报告未提 | ✅ | K-UI-021 | docs/uiaudit/detect_r1.md §0 §4 |
| UIA2 | 滚动问题能用"真实滚轮 + 量最后一块内容是否进视口"自动查出 | scroll.js：内容区滚轮 25×600px，1440×900 与 1280×720 | 查出剧本阅读页每镜定高 518px 内滚 ×8（两种尺寸都滚不到底）；资产页开测时整页崩溃 → 修后 25/26 过 | ✅ | K-UI-022 | docs/uiaudit/detect_r1.md §3 |
| UIA3 | 声音能不能播是前端缺口，不是后端缺文件 | HEAD /files/music/ep02.wav、/files/assets/voices/narrator_qag/ref.wav、narrator_pick/*.mp3；mp_demo 实机播放 | 全部 200 + Range；r1 开始时全站 0 个 audio；ds/MediaPlayer 自测：播放、波形 320 柱、A/B 同位置切换都通过 | ✅ | K-UI-023 | docs/uiaudit/detect_r1.md §5 |
| UIA4 | 列表与大图读同一个"当前版"，否则"看不到最新" | ep02 镜 1：卡片 / 大图 / 阅读页三处对比 | 卡片"新图·未登记"、大图"还没有首帧 · 0 版"、阅读页有图 | ✅ | K-UI-024 | docs/uiaudit/detect_r1.md P0-1 |
| UIA5 | 只查"缺什么"抓不到"少了什么"，必须拿改版前的功能清单做基线逐项比 | UIAUDIT 功能回退检查：git e66903c + data/_archive 归档 22 个文件 → 35 条基线；regress.mjs 静态比对 + flows_regress.json 真实界面比对 | 静态比对：基线里有、现在代码里没有的操作文字 276 条；人工复核后确认 P0 回退 6 条（剧本页前后帧 / 视频 / 细节、锁种、新造型、剧本 A/B、全部集总览、向导设置）、P1 9 条；r1–r3 的 detect 一条都没抓到 | ✅ | K-UI-030 | docs/uiaudit/regress_r1.md |
| UIA6 | 用 JS 合成事件就能测交互（悬停、Alt+点、Esc） | 同一页同一批小图，先用合成 mouseover / click(altKey) 测，再用 CDP Input.dispatchMouseEvent（mousePressed/Released 带 modifiers）和 dispatchKeyEvent 复测 | 合成事件：林晚页 1/5、悬停 0/5；真实输入：5/5、悬停 5/5（g11_detect.json 对 g11b_detect.json） | ❌（合成事件会冤枉被测方；交互检查一律用真实 CDP 输入） | — | docs/uiaudit/verify_uimaster_r2_g11.md |
| UIA7 | "#root 有字"就算页面加载完 | r5–r8 多轮复测：判断加载完的条件从"#root 有字"改成"正文（去掉顶栏 / 导航）超过 60 字且不是加载中 / 正在读取"，人物页另等 .hub-anchors-st 出现，项目设置页另等数据回来 | 改之前每轮出 4–13 条假 P0（顶栏文字让判断以为已加载完，其实正文还是空的，或者 ⋯ 菜单在数据到之前就被点开了）；改之后 r8g3 P0 = 0 | ✅ | K-UI-030 | apps/web/e2e/uiaudit/r8g3_regress.md |
| UIA8 | 首帧格“属于这一镜”就说明界面 = 后端 | 旧 parity_check（只看首帧文件名含镜号）对新 parity2_check（首帧 / 尾帧 / 视频逐格比文件 + 版号 + 候选标记 + 镜头列表），10 集 | 旧口径 30/30 全过；新口径 9 s 取样 14 格写“未出”而后端有合格候选，25 s 取样 180/181 | ❌（旧口径太松；逐格比 + 等候选接口回来再取样） | K-UI-038 | docs/uiaudit/verify_uirsi_r35_r36.md §0、§1 P1-2 |
| UIA9 | data_parity 全过 = 界面数据没问题 | 离线并回后：data_parity PASS 1663 项，同时 /api/shots/{id}/refs 74/80 镜 500 | 7 张设定图被并回成半截文件（备份前缀），data_parity 不读图、不调 /refs，查不出；detect apiErrors + trunc_scan 查出 | ❌（加完整性扫描、页面接口 5xx 计入复核） | 草案 Q20（knowledge/inbox/2026-11-01_uiaudit_r20.yaml，收编后改回规则号；RSI 11-01 代改：账本只能引用已收编的规则，否则 compile 全库失败） | docs/uiaudit/verify_uirsi_r35_r36.md §1 P0-A |
| UIA10 | 合成 click 能打开 = 鼠标能打开 | 候选格：真实 CDP 鼠标点图 vs 合成 .click() | 真实鼠标被 ZoomLayer 截走开大图框；合成 click 打开候选弹窗 | ❌（再次印证 UIA6：入口类检查一律真实输入） | — | docs/uiaudit/verify_uirsi_r35_r36.md §1 P1-1 |

## I. 运行层：服务器资源利用（INFRA，2026-10-31；数字见 docs/infra/utilization.md）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| I1 | GPU 没用满，是因为模型每张都从盘里重新加载（--cache-none） | 对比 6 道 ComfyUI /history 的执行时间 | 首帧 cache-none 42.8–48.0 s，cache-ram 41.3–41.7 s，差别不到 5 s（热模型本来就在页缓存里）；真正的空转来自笔记本链路：Wi-Fi 约 270 KB/s，1.3 MB PNG 取一次 7–37 s，图出完 56 s 后才记 done | ❌（瓶颈在链路，不在加载） | K-OPS-I05、K-OPS-I06 | docs/infra/utilization.md §1 |
| I2 | gpu36:2 的 --novram 只影响长镜头 | 同一首帧作业在各道的执行时间 | --novram 首帧 100–116 s、设定图 635–650 s；改 normal 后首帧 43.9 s（中位数），快 2.4 倍 | ❌→改为 long / normal 两种模式 | K-OPS-I03 | docs/infra/utilization.md §3 |
| I3 | --cache-ram 140 200 已经用上了大内存 | 读 ComfyUI 0.42 的 execution.py | 两个数是“剩余可用内存门槛”：503 GB 机器剩 200 GB 就开始丢缓存（只用一半）；改为 64 96 / 56 88，上限约 80–87% | ❌（参数理解反了） | K-OPS-I01 | docs/infra/utilization.md §2 |
| I4 | 视频权重都在页缓存里，从出图切到出片不用读盘 | 用 fincore 查各模型在页缓存中的比例，并给锁定计时 | gpu33 的 fl2va 只有 11.3/21 GB、ref2va 14.4/21 GB、32b TE 13.9/27.1 GB 在缓存里（实验用模型反而整个在）；锁定后读 21 GB 只要 2.0–2.2 s，冷盘约 1.3–1.5 GB/s | ❌→锁定热权重 | K-OPS-I02 | docs/infra/utilization.md §3 |
| I5 | 队列一空就可以安全重启 ComfyUI | 6 道滚动重启（hold_lanes） | 6 道都没有打断正在跑的任务，恢复用时 9–26 s；但有 2 张已出完、还没取回的图因为 /history 随进程丢失，被判 LOST 重出（约 2 × 45 s GPU） | ◐（还要等“未取回 = 0”） | K-OPS-I04 | docs/infra/utilization.md §2 |
| I6 | 两台的视频权重是对齐的 | 对照锁定清单逐个查；缺的从原始 HF 来源补，sha256 三方核对 | gpu36 缺 ref2va pruned int8（21 GB）和 Motion_Repair_V2，gpu33 缺 latent upscaler fp16；已补齐，sha 与 HF LFS 及另一台现有文件一致；gpu36 锁住部分 104→125 GB | ❌→已补齐 | K-OPS-I07 | docs/infra/utilization.md §3 |

## IMG. 十集出图（IMGGEN，2026-10-31；series10_v1，6 卡；证据 data/pipeline/runs/series10_v1/images/findings.json）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| I1 | 6 道在一个循环里串行轮询就能把卡喂满 | 21:44–22:11 单线程调度 | 22:06 只有 3/6 道在出图：一条隧道 /view 慢（笔记本约 270 KB/s，一张 PNG 7–35 s）卡住全部；改为每道一个提交线程 + 一个取图线程、按服务器队列补交后，6 道都在出图（利用率 0.6–0.98） | ❌→改 | K-OPS-121 | data/pipeline/runs/series10_v1/images/imggen.log |
| I2 | 质检可以下载到笔记本再传上 gpu36 | 21 张 6.5 MB 走 scp | 3 分钟以上仍没传完；改为在出图机器上原地读输出目录打分，一批 14 s | ❌→改 | K-OPS-122 | tools/series10_imggen/score_remote.py |
| I3 | “与他人 <0.40”对所有角色都适用 | 顾沉 / 陈宇脸部参考互相余弦 | 两张参考本身就有 0.429，顾沉的每张图都会被判“像陈宇”；门槛改为 max(0.40, 参考互余弦 + 0.05) 后，顾沉 3 个造型都通过（本人 0.92） | ❌→改 | K-REV-121 | data/assets/identity_refs/manifest.json |
| I4 | 景别按经验档位（全身 <0.055）判 | 首批 48 张人工对照 | 全身站姿脸高约 0.088，被判成“中景”；按实测改档位，允许差一档 | ❌→改 | K-REN-122 | tools/series10_imggen/imggen.py |
| I5 | 换 seed 能修好大部分不合格首帧 | 80 镜，首次不合格 37 镜，每镜最多换 3 次 seed | 首次通过 43/80（54%），最终通过 55/80（69%），共出 171 张首帧。按原因救回：身份 7/28、景别 6/14、文字 1/1。剩下 25 镜取最好一张标“尽力”：其中 10 镜是双人镜第二个人没出脸，6 镜是要特写出成中景，7 镜是男主身份 <0.5 | ◐（换 seed 对身份几乎无效 → 双人缺脸早停；特写和男主身份要从提示词 / LoRA 侧修） | K-REV-122、K-REN-123、K-AST-223 | data/pipeline/runs/series10_v1/images/findings.json |
| I6 | 新角色纯文字设定图能直接用 | 阿岚 3 造型 × 2 seed，A 造型重出 1 次 | A 造型前两个 seed 与陈宇 0.61、与顾沉 0.46，第 3 个 seed（1108）降到 0.32 才通过；B、C 与 A 的余弦 0.57–0.61，判同一人；A 的脸裁出来作身份参考后，ep05 的 4 镜才能出 | ◐（必须做“与他人”检查，并用 A 的脸约束 B、C） | K-AST-221、K-AST-222 | data/pipeline/runs/series10_v1/images/findings.json |
| U8 | 静态排版分高 = 项目方用着顺 | 按 7 个真实任务在真界面上点击计时（tasks.mjs） | 排版分 9.3–9.8 时，T3“挑设定图”在界面上根本做不到；画布首屏 3–4.6 s；精修页一开 41 MB 原图 | ❌（改成任务分 + 技术分为主） | K-UI-017 | docs/uirsi/rounds/r14-r18.md |
| U9 | 缩略图 + 首屏外请求延后能显著提速 | /api/thumb + 推迟 SOP / 进度 / 探测 / 卡状态 | 最大一页图片 41 MB→2.6 MB、>400 KB 图 195→2；慢请求 14→1；首屏平均 1.39 s；镜头行 2.1→1.2 s | ✅ | K-UI-018 | docs/uirsi/rounds/r14-r18.md |
| U10 | 设定图挑选要在系统里做 | 资产中心挑设定图页 + 项目方闸门记录 | T3 从“做不到”到 3 次点击到选定确认框（8.1 分） | ✅ | K-UI-019 | tests/test_story_runs_uirsi.py |
| F19 | replace 导入新剧本就等于“旧东西清零” | 导入后逐镜查 /api/readiness | 剧本换了，但同号镜头仍挂着旧 60 集的版本 / 定稿锁（data/renders/epNN/SN、renders_gpu3 镜像、ref_overrides 索引）；把 ep01–ep60 挪进 _archive_60ep_20261031（可还原）并重建索引后，80 镜 frames_source 全为 none | ❌（换剧本要连同号镜头的版本目录一起归档） | K-AST-203 | data/renders/_archive_60ep_20261031/MANIFEST.json |
| F20 | 合并稿里每集保留自己的规则版本章注释 | 导入关口校验 10 集合并稿 | 集间注释 11 处 QW-F0（无法归属）；集中到文件头后 0 block | ❌（多集合并时注释放文件头） | K-AST-203 | data/staging_v3/merged/漆皮之下·十日_series10_v1_ep01-10.md |
| U11 | 闸门要“原话”才算项目方本人 | 项目方实际使用：几百个镜头逐个打字确认 | 项目方原话“那岂不是我敲几百次字？……系统是在我 login 的” → 改成登录会话认定身份、点选即生效 + 10 秒撤销 + 自动审计 | ❌（推翻 K-UI-019 的原话门） | K-UI-020 | tests/test_auth_uirsi.py |
| U12 | 后端 takes 的 label 是给人看的 | 读 /api/candidates?ep=2 全部标签 + 画布截图 | 50 张无标签；17 张标签是“ASSETMASTER 已出（PRODUCER 接手登记）”（流水线内部登记记录），画布直接显示“暂定 · ASS…”；改为按段过滤后只剩“暂定”，“新配方”照常 | ❌（label 是流水线记录，前端必须过人话层） | K-UI-037 | docs/uirsi/rounds/r35.md |
| U13 | 全站放大层按 cursor 猜“可不可点”够用 | UIAUDIT 真实鼠标点候选格（verify_uirsi_r35_r36.md P1-1）；r37 加 data-zoom-own 后复测 | 改前：点图出放大框、候选对比弹窗打不开；改后：真实鼠标 → 候选弹窗、Alt+点 → 大图、悬停 → 放大镜 | ❌（格子有自己的点击要显式声明，不能靠 cursor 猜） | K-UI-040 | docs/uirsi/rounds/r37.md |
| U14 | 服务器上的图每次经隧道现取就行 | /api/gpu/thumb 取 ep05-S3_image_v9_00002_：改前经隧道 vs 改后先找本镜 takes.json 里登记的同名一版 | 改前隧道断时 30 s 没回、前端裂图；改后 0.09 s 用笔记本文件；笔记本没有的写占位字 | ❌（先用本机已登记的副本，隧道只是兜底） | K-UI-042 | docs/uirsi/rounds/r38.md |

## AM. 资产补全（ASSETMASTER，2026-11-01；证据 data/assetmaster/）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| AM1 | P1 造型登记 + 设定图就够锁住服装 / 鞋 / 饰品 | scan.py 扫 10 集 80 镜 × 4 角色 × 3 造型，对照衣橱 | 已登记单品里 48 件没有产品图，只有 13 件有；顾沉、陈宇、阿岚的全部单品都只有设定图 | ❌（设定图不是单品参考，I4 会挡）→ 补产品图 | K-AST-251 | data/assetmaster/inventory.json |
| AM2 | 写作稿的造型都按登记写 | 同一次扫描的矛盾判定 | 未登记 / 跨造型 / 同造型不同鞋 / 表头偏离共 4 集：ep04 C 配透明高跟；ep07 镜1–6 用了未登记造型；ep09 换 C 后仍写 B 的铁珠；ep10 B 混进细银链 / 红绳 | ❌ → 写作模型（关推理）按登记返修 4 集，台词逐字不变，chain block 0，单集 merge 导入 | K-AST-252 | data/assetmaster/look_fix_log.jsonl |
| AM3 | 返修核对把 sound 也锁成逐字更安全 | ep09 返修 | 3 轮都没过（"衣料摩擦"→"漆皮摩擦"是随造型的合理改动）；只锁台词类后 1 轮通过 | ❌ → 只锁对白 / 独白 / 时长 / 镜数，拟音改动进日志 | K-AST-227 | data/assetmaster/look_fix_log.jsonl |
| AM4 | 名字模糊匹配就能把登记单品对上衣橱 | 首版 scan 的库匹配 | 细银链 → 草莓水晶项链，A 的鞋 → 美甲 T1（名字里有"透明高跟"），林晚短款外套 → 顾沉男式外套 | ❌ → 按槽位过滤、只认主名词、颜色 / 材质不同判缺图，再加人工覆盖 lib_map.json | K-AST-228 | tools/assetmaster/scan.py |
| AM5 | 剧情前提单品（长风衣 / 腰侧九环）应交写作删掉 | 看 ep07 / ep08 剧名与动作 | 两集剧情都以该单品为前提，删掉会改剧情 | ❌ → 暂定登记为造型外搭 / 身体装饰（总调度批） | K-AST-226 | data/assetmaster/look_extras.json |

## R. 资产参考锁定 / 生成契约（REFLOCK 2026-10-31 ~ 11-01）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| RL1 | 首帧只挂脸部裁切、服装 / 鞋 / 饰品靠文字，也能保持造型一致 | 查 series10 80 条首帧作业的 refs + 项目方审片 | 80 条 refs 只有 face_ref2va / sheet2；项目方原话“不同地方的鞋子都不一样” | ❌ → 资产参考锁定：身份脸 > 造型设定图 > 景别单品 > 场景，缺图阻断 | K-AST-230 | data/pipeline/runs/series10_v1/assets/first_frame_jobs.json |
| RL2 | 3 个参考槽装得下“脸 + 造型 + 单品” | 解析器在 80 镜上排槽（Qwen 2.1 = 3 槽） | 80 镜无一超槽：超出时同角色设定图 + 单品拼参考板，场景先让位；双人镜脸槽恒为 1 | ✅ | K-REN-130 | data/review_pages/asset_reflock/look_audit.json |
| RL3 | 系统角色锁只写身份 | 读编译后的首帧提示词 | 顾沉角色锁“黑色高定衬衫”与造型 A“黑色高领毛衣配深灰西装”同句出现（ep01-S4） | ❌ → 资产模式下去掉角色锁服装分句 | K-AST-232 | data/pipeline/runs/series10_v1/assets/first_frame_jobs.json |
| RL4 | CLIP 区域滑窗能区分“对的鞋 / 错的鞋” | 已知答案图：设定图 A/B、S01 上脚 vs 其它造型的鞋 | 正例 0.782 / 0.807 / 0.896；反例最高 0.762（黑短靴），其余 ≤0.720；颜色直方图对透明鞋无效（≈0） | ◐ 鞋线 0.775 可用但余量小；直方图不作判据 | K-REV-231 | data/review_pages/asset_reflock/calibration.json |
| RL5 | 剧本里的造型都按登记写 | look_audit 扫系统剧本 | 首次：ep04 C 配透明高跟、ep07 镜1–6 造型未登记；返修后：ep03-S3 正文已穿 B 的束腰但登记 A（写作模型判“改登记”，$0.0018） | ❌ → 审计 + 写作模型返修 + 系统登记 shot_looks.json | K-AST-231 | data/pipeline/runs/series10_v1/assets/look_revisions.json |
| RL8 | 画布按钮和批量出图走同一条路 | 查项目方从画布点的重出作业 ab6a65ccd8f5 | 画布走旧 qwen_two_stage 换脸：图1 = 旧首帧，参考 = 旧母版 master_face（ar-c2351c9dcf），绕开 v9、槽位与契约；REFLOCK 配置里林晚身份脸也误用了同一张旧母版 | ❌ → 唯一出图路径（frame_job + unified_frame），身份脸改回项目方挑定的 A-s202 face_ref2va，测试锁逐字段一致 | K-REN-134 | tests/test_unified_frame.py |
| RL7 | Q4 / Q7 能用整图统计 / CLIP 直接判“质感 / 场景对不对” | 80 张首帧分布 + 场景参考比对 | 场景：办公室 0.439–0.581 vs 其它 0.372–0.636，分不开；质感只能按分布尾部抓离群 | ◐ 线只挡离群，待改区域化 | K-REV-232 | data/review_pages/asset_reflock/calibration.json |
| RL6 | 造型设定图带脸进槽位无害 | IMGGEN imgfix v10 对照 | 设定图的娃娃感脸会和身份脸抢 | ❌ → 造型图一律去头 | K-AST-233 | tools/series10_imggen/refkit.py |

## AX. 人物资产页（ASSETUX，2026-11-01；证据 docs/assetux/、apps/web/e2e/assetux/）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| AX1 | 选设定图要项目方原话才算数 | 旧“选这张…”框 vs 登录后点选 | 旧：2 次确认 + 必填原话；新：1 次点击 + 10 秒撤销，操作人自动记账 | ❌ → 点一下即生效 | K-UI-025 | apps/web/e2e/assetux/before_sheet_pick_modal_1440_dark.png |
| AX2 | 卡片网格总览比人物页好用 | 对比旧资产库（项目方认为更好）与 UI5/UIRSI 版 | 旧版 1 屏看到人 + 大图 + 造型槽；新版 1 屏只有 3 张角色卡，造型 / 衣橱要 3–4 屏 | ❌ → 回到“人物为中心” | K-UI-026 | docs/assetux/compare.md |
| AX3 | 上传单品得先建单品再传图 | 新上传接口一步完成 | 鞋 1 件 + 身体饰品 4 件（其中 1 件 2 张图）一次一步登记；解析器即刻认（测试 6 例） | ✅ | K-UI-027 | tests/test_character_hub_assetux.py |
| AX4 | 页面滚不动是因为卡片定高 | 查计算样式 | 实际是 class 前缀 ph- 撞了 v3.css 旧弹层（max-height 70vh、overflow:auto） | ❌ → 改前缀 hub-；真实滚轮 3 档宽高 nested=0、lastInView=true | K-UI-028 | apps/web/e2e/assetux/r3w_wheel_*.png |
| I7 | 第一轮首帧的“塑料 / 糊 / 油”是 seed 问题 | 4 镜 × 12 变体同 seed 对照（gpu33，imgfix_ab.py） | 不是 seed：旧统一后缀（f/1.2 奶油柔焦、浓郁饱和）+ Base 25 步 plan_c 图。S★ 路径清晰度 ×2–4、脸部高频 +40–90%、油光≈0；cfg 2.5 林晚身份跌到 0.45–0.72 | ❌→改（首帧走 S★ 出图路径，cfg 1） | K-REN-124 | data/pipeline/runs/series10_v1/images/imgfix/results.json |
| I8 | 只挂脸参考就能保住服装 | 同上，ep01-S5（造型 A） | 只挂脸的变体全部服装漂移（露肩 / 吊带）；挂去头造型图后穿对；带脸的造型图与身份脸抢脸（娃娃感回流）→ 去头 | ❌→改 | K-AST-251 | data/pipeline/runs/series10_v1/images/imgfix/contact_sheet.jpg |
| I9 | 写实越强越好 | krea2 0.3 / 0.5 / 0.8 | 林晚身份 0.87→0.77→0.72（ep01-S5），顾沉 0.80→0.78→0.66；项目方定“脸不动，写实只在质感” → 三档给项目方挑 | ◐ 待项目方选 | K-REV-124 | 同上 |
| I10 | 局部特写写清“只拍手”就不会出脸 | ep05-S5（手 + 针） | 12 个变体全部出林晚正脸 | ❌ 待定策略 | K-REN-125 | 同上 |
| I11 | 场景只靠文字能保持连续 | 项目方 / 总调度亲审 ep01 四张：布局各不同 | 6 场景出空镜底图登记后 I5 阻断 66→0；首帧带底图的 v9 林晚 0.94/0.89 | ✅（底图作场景参考） | K-AST-252 | data/pipeline/runs/series10_v1/images/scenes/scenes.json |
| F21 | 流水线出的图放在 runs 目录里就够了，界面能看到 | UIAUDIT：界面只认 takes.json 版本，没法选定 / 对比 / 回滚 | 新登记器 tools/pipeline/register_takes.py 走 pipeline._add_take：80 张 v1 首帧登记为候选 take（标“旧配方”、暂定、不设当前、不加锁、记来源与 sha256）；重复执行 80 条全部跳过；坏图 0 | ✅ | K-AST-203 | data/pipeline/runs/series10_v1/images/register_takes.log |
| AX5 | 重复上传报个错就够了 | 项目方 11-01 截图：添加单品弹红字“这张图已经是单品…了” | 项目方不知道怎么办；那件在“以前登记的单品 84 件”折叠区里；名称框填的是文件名 O12_flatlay_dark_s0 | ❌ → 选图先查库：已在库里给“用这件，挂到造型”一键；新图看图起名（abliteration 关推理，约 250 token / 次）；全站 46 处只报错的提示列给各页 | K-UI-029 | docs/assetux/error_ways_out.md |

## V10. 十集出片（VIDEO10，2026-10-31 夜–11-01；series10_v1；报告 docs/series10_video/S10V1_report.md）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| V1 | Ref2VA + PDD Ref2VA-Acc 8 步两段式能兼得“Ref2VA 的身份”和“PDD 的速度” | S10V-1：ep01-S5 单人近景 / ep01-S6 双人对白 / ep10-S5 走动全身 × seed 20261101/02，对照纯 Ref2VA 24 步 | 速度：PDD 495–579 s/条，24 步 1980–2222 s（约 3.5–4 倍）。动作 / J4 / 泛红 / 硬切：两组都过（PDD mean 0.71–3.45、J4 1.02–1.06、cheek_red ≤0.125、0 硬切）。**景别**：PDD 5 条里有 4 条从近景 / 中近景退成全景 / 中全景（脸高 0.09–0.10）；同 seed 的 ep01-S5，24 步脸高 0.22（近景，符合）。**男角身份**：同 seed 的 ep10-S5 陈宇，24 步 0.439 / PDD 0.292；顾沉在 PDD 下 0.467 / 0.289 | ❌ 不作默认（景别和男角身份两项都输） | K-REN-301 | docs/series10_video/S10V1_report.md |
| V2 | LAB 闸门（动作 / J4 / 泛红 / 硬切 / 身份）够判视频 | 同上，加测景别（K-REN-122 档位） | 原闸门下 PDD 5 条里 3 条“通过”，加景别后只剩 0 条通过 | ❌→加景别闸门 | K-REV-301 | tools/series10_video/score_clip.py |
| V3 | 推到服务器的文件不用核 | gpu33 推 SFace onnx | 文件损坏（sha 不符），OpenCV 解析失败；gpu36 上传实测约 17 KB/s，38 MB 断线一次，按字节续传后 sha 对上 | ❌→推完核 sha、能本机复制就不从笔记本推 | K-OPS-302 | tools/series10_video/deploy.py |
| V4 | 纯 Ref2VA 可以当首帧路线的兜底 | 生成契约 preflight（REFLOCK）对 355 个变体 | Ref2VA 变体全部被 I3 挡下：没有造型参考，服装只靠文字 | ◐ 兜底要先给 Ref2VA 加造型参考槽（编译器 ref_slots role=outfit）；在此之前正式出片只走首帧路线 | K-REN-301 | data/pipeline/runs/series10_v1/video/jobs.json |
| V5 | 闸门全过的镜可以叫“通过”进成片 | 总调度 11-01 决定（项目方只授权预览） | V6 多肢 / V7 口型没有检测器 → 只能“预览·V6/V7 未测”；尽力版不进合成 | ◐ 预览 ≠ 成片 | K-REV-302 | docs/ITERATION_PROTOCOL.md §3 |
| V5-R | VIDEO10 越界改的 services/recipes（graph.py 的 pdd_conf / _upscale_tail / Ref2VA 两段式；放大器输入 enable_chunking → enable_temporal_chunking；ref2va_pdd2.yaml、i2va_pdd2.yaml）和服务器节点一致、和 LAB 实跑图同构 | ITERAUDIT 独立复核（总调度 11-01 指派）：tools/qa/graph_schema_check.py 把三个配方编成 API 图，逐节点对照 gpu 两台 :18188 / :18288 的 /object_info；再与 tools/lab_ep02/planb_run.py、ref2va_run.py 逐节点比对；负例：把输入名改回 enable_chunking | 6/6（3 配方 × 2 台）一致：节点、输入名、必填、COMBO 取值（Ref2VA-Acc / FL2VA-Acc-8Step、upscaler conv_v1_fp16、comfy kitchen attention、nfe "8"）、输出序号（PDD 输出 1 = σ 表）全对；MinimaxH3LatentUpscaler3D 真实输入是 enable_temporal_chunking（/object_info input_order），旧名 enable_chunking 会被判“没有输入”→ 改名是修 bug；模型链 UNET→LoRA→PDD→SigmaShift→attention 与 planb_run 一致；Ref2VA 两段同一条件、第二段 guider 126 与 ref2va_run 一致；tests/test_recipes_engine.py + test_recipe_plan_api.py 24 passed | ✅ 通过（改动正确）；遗留：越界改动本身违反所有权（services/recipes 属 AUTOPILOT），以后走 LOCKS 登记；add_guide_first_frame 与两段式同开时引导图在 pass1 尺寸，LAB 没测过这一组合（配方里目前是关的） | K-OPS-Q01 | data/qa/iter_gate/VIDEO10_graph_review.txt |

- VIDEO10 越界自报（ITERATION_PROTOCOL O1）：services/recipes/ns_recipes/graph.py（PDD-Acc、Ref2VA 两段式、upscaler 参数名 enable_temporal_chunking）和 recipes/ref2va_pdd2.yaml、i2va_pdd2.yaml 归 AUTOPILOT，VIDEO10 10-31 夜改动；11-01 已请 ITERAUDIT 复核（经总调度转达），复核结果待记。
| AX6 | 资产中心的数据源都已经是当前剧的 | 11-01 RECALL 隔离后实测 /api/assets/characters、/api/loras | characters 仍列 alex/ryan/kai/leo；LoRA 总表仍列已隔离的 lin_wan_qi_v1（8 行中 1 行）；场景已只剩 6 个 | ❌ → 前端按演员表 + 隔离区清单过滤（GET /api/asset-quarantine，测试 test_asset_quarantine_list） | K-UI-033 | data/qa/assetux_r11_parity.json |
| V6 | （V1 补数）纯 Ref2VA 24 步的景别是否可靠 | S10V-1 补齐 ep01-S6 seed 20261102 纯 24 步 | 顾沉 0.562（同 seed PDD 0.289）、林晚 0.686；但景别也从中近景退成中全景（脸高 0.098），J4 1.412。纯 24 步组景别 2/3，PDD 组 1/5 | ◐ 双人镜两条 Ref2VA 路线都不跟剧本景别 → 首帧路线为默认（K-REN-301 不变），Ref2VA 只作身份兜底 | K-REN-301 | docs/series10_video/S10V1_report.md |

## PERF. 出图任务性能（IMGPERF，2026-11-01；报告 docs/imgperf/r1.md）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| PF1 | 画布出图慢在 ComfyUI | 对照 655a3f4c9079 的 /history 与 takes.json 写盘时间 | ComfyUI 约 35 s；take 01:51:29 已写盘；任务 02:11:09 才结束（墙钟 1243 s），其余 1180 s 是同步 postflight | ❌ → postflight 移出出图道（REFLOCK 后台线程）；任务记录加 progress / timing | K-OPS-P01 | data/jobs/v1/655a3f4c9079.json |
| PF2 | postflight 慢在远端打分 | 独立进程逐段计时（同一张 image_006） | 远端 129.5 s（6 次 ssh 各 10–13 s + scp 60 s）；本机 CLIP 加载 39.9 s；本机 CLIP 滑窗 772.9 s（约 205 个窗 × ViT-L/14 CPU，与 calibrate_imgfix / reflock_v9 抢 CPU） | ◐ 远端改一次 ssh → 60.0 s；本机 CLIP 滑窗仍是大头（归 REFLOCK） | K-OPS-P02 | tests/test_imgperf_lanes.py |
| PF3 | 出发前现读训练锁不花时间 | 重启后首个任务 d1669a7b6e0c 的 timing | lane_check 10.4 s / 57.2 s | ❌ → 后台读、投图前再等（_gate_submit） | K-OPS-P02 | data/jobs/v1/d1669a7b6e0c.json |
| PF4 | “自动”会把出图任务分到空闲道 | 01:50 S1/S2/S3 三个 auto 任务 | 全部 gpu 0；gpu33:1 / :3、gpu36:0 空闲。pick_lane 规则“出图卡 ≤ 2×70 s 就仍用出图卡”，实测每张 300–860 s | ❌ → 空闲道优先、都忙取预计等待最短（实测中位数 + /queue 深度） | K-OPS-P03 | tests/test_imgperf_lanes.py |

## GV. GPU 实时面板 + 渲染任务中心（GPUVIEW，2026-11-01；报告 docs/gpuview/r1.md，说明 docs/GPU_STATUS.md）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| GV1 | 面板写“其他任务占用”是因为读不到别人的任务 | 直接读 6 条道 /queue 第 4 项 extra_data | 各 agent 都有 client_id 前缀（imggen-s10- / video10- / bakeoff-），但没有“谁 · 哪集哪镜 · 第几次”；ns_api 只认自己的 job | ✅ → 投任务带 extra_data.ns_tag（comfy_tag），没带的按 client_id + 输出前缀 + 模型推断 | K-OPS-G01 | apps/web/e2e/gpuview/crosscheck.json |
| GV2 | gpu36 温度 / 显存读不到是硬件读不了 | ssh gpu36 nvidia-smi --query-gpu（只读） | 一次约 12 s 能读到；原面板只 ssh gpu33。gpu36 功耗墙 200/350 W，/var/lib/gpu36-dimm-guard/state level 1 | ❌ → 每台机器一条常驻 ssh，远端 5 s 一段只读快照；温控守护状态标在卡上 | K-OPS-G01 | docs/GPU_STATUS.md §4 |
| GV3 | 顶栏“生成中 1”反映全系统渲染量 | 同一时刻对照 /api/render-tasks 与各道 /queue、/api/jobs | 顶栏只数 ns_api 队列；同刻全系统渲染中 3、等待 237（含计划中）、失败 6 | ❌ → 渲染任务中心一份登记表，顶栏与底栏同一行组件；render_tasks_parity P1/P2/P3 通过 | K-OPS-G02 | data/qa/render_tasks_parity/ |
| V7 | （总调度亲审 ep01-S5 v1）发色变深变灰是 PDD / 3D 放大造成的 | score_clip 新增发色测量：蓝色发丝像素 HSV 中位，首帧 vs 片子；整帧 Lab 首帧 vs 第 0 帧；另测林晚身份参考和 lookA 设定图 | 片子 vs 首帧：dH +2、dS −2、dV +2（V 59 vs 57），第 0 帧整帧 ΔE 1.74 → **视频没有改颜色**。首帧本身就暗：首帧发丝 HSV (106, 82, 57)，身份参考 (106, 95, 154)，lookA 设定图 (106, 106, 152) → 首帧比参考暗 97 个 V 级 | ❌ 不是 PDD / 放大器；不加视频侧校色（校到首帧也还是暗）。根因在出图阶段 → 交 ASSETMASTER / REFLOCK：首帧 postflight 加“发色对身份参考”项 | K-REV-303 | data/pipeline/runs/series10_v1/video/scores/ep01-S5__v1.json |
| GV4 | 一次 /queue 读失败 = 卡离线；标签数字可以用全剧数 | UIAUDIT 复核 r1（docs/uiaudit/verify_gpuview_r1.md 第 30、42 行） | gpu33:3 100% / 345 W 时被写“离线”，约 1 分钟后自己恢复；标签“失败 5”对列表“失败 0” | ❌ → 2 分钟内写“暂时连不上（N 秒）”并沿用断开前队列；标签与列表同一 filterRows / countRows | K-OPS-G01 | tests/test_gpuview.py |
| V8 | （MASTER_PICTURE G6）能用现有本机模型补上 V6 多肢 / V7 口型检测器 | gpu33/gpu36 都有 venv_hand（MediaPipe 手 / 骨架）和 venv_idm（insightface buffalo_l 含 106 点）；在 10 条已出片上标定 | V6：多手 0–0.031、同侧重复 0–0.034、闪变 0–8；2D 手指骨长在背身远景下 0.68–0.80，不可靠 → 只记录。V7：正对镜头对白 corr 0.33–0.80；顾沉说话嘴不动的一条 0.156（判不通过，符合观感）；远景小脸噪声 → 90 px 下限 | ◐ 两个检测器已接进 score_clip（不过 → 阶梯换 seed；测不到 → 未测）；只有负例标定，正例待收集，暂不据此放行成片 | K-REV-304、K-REV-305 | data/pipeline/runs/series10_v1/video/calib_v67_*.json |

## UM. 界面点击爬虫与总控（UIMASTER，2026-11-01；日志 docs/uimaster/log/，问题库 docs/uimaster/issues.json，轮次 docs/uimaster/rounds/）

| # | 教训 | 证据 | 落到哪 | 结论 |
|---|---|---|---|---|
| UM1 | “复爬没再出现”≠已修：同一元素、同一尺寸主题、点了有正向反应才记 verified；元素已不存在记 gone，不算修好 | docs/uimaster/rounds/r2.md 第 3 步；ITERATION_PROTOCOL H4 | apps/web/e2e/uimaster/crawl.mjs（passKey / seenAll） | ✅ iter_003 起按正向断言记 verified |
| UM2 | 爬虫自己的状态残留会制造大批假问题：串播全屏层没关 → 34 条“被盖住”；about:blank 导航没落地 → “白屏”；报错层期间被盖住的控件逐个记成问题 | docs/uimaster/issues.json 里 wontfix 的 history；docs/uimaster/runs/iter_003.out | crawl.mjs restore()（全屏层签名）、导航失败不记白屏、报错层时跳过本页 | ✅ 34+6+1 条误报已标 wontfix 并修爬虫 |
| UM3 | 半成品落盘会让全站 vite 报错层（UM-0001）；safe_write 只查语法，漏 import 只有 tsc 抓得到 | docs/uimaster/rounds/r2.md、r3.md | K-UI-M02 → apps/web/e2e/uimaster/safe_edit.sh | ◐ 规则 + 脚本已上，靠各 agent 遵守 |
| UM4 | 小图放大要在全站一处做（ZoomLayer），不靠逐个组件改；测法必须用真实 CDP 鼠标（合成 click 测不到 Alt / 悬停） | docs/uiaudit/verify_uimaster_r2_g11.md 第 1 版误判 → 第 2 版通过 | K-UI-M01 → crawl.mjs zoomCheck | ✅ UIAUDIT realzoom 13/13 通过 |
| UM5 | 焦点回位要扛住 StrictMode 双 effect、按钮重渲染、按钮收进 ⋯ 菜单三种情况：用按下时记下的触发控件，不用 effect 时的 activeElement | docs/uiaudit/verify_uimaster_r3.md | apps/web/src/ds/index.tsx useFocusTrap；crawl.mjs focus_return 断言 | ✅ UIAUDIT verify_uimaster_r3b 通过 |
| RL9 | 在标定集上 14/14 判对的 Q4 阈值（整图 Laplacian ≥175）能用 | BAKEOFF 留出复核 46 张（总调度亲标，不在标定集里） | 留出判对 0.59、AUC 0.41（比随机差）；挡 11 张可接受暗场 / 中景、放 8 张娃娃脸 | ❌ 留出复核推翻已标定阈值 → Q4 改只记录；换脸部度量留一 CV：face_hf 0.581、p_plastic 0.847（饱和、混杂，不开阻断） | K-REV-232 | data/review_pages/asset_reflock/heldout_bakeoff.json |
| RL10 | 鞋单线 0.775 能分对错 | 同一留出复核 14 张 | 判对 0.714，对 / 错分数重叠 0.71–0.78，加装饰款 0.780 被放过 | ◐ → 三段（<0.70 挡 / 0.70–0.78 鞋待目检 / ≥0.78 过）+ 加装饰探针 0.7：14 张 0 误挡 0 误放 | K-REV-231 | data/review_pages/asset_reflock/q4_face_calibration.json |
| RL11 | Q5“肢体比例可疑”能抓坏肢体 | 同一留出复核 18 张 | 7 次触发全是误报（坐姿、手臂被遮）；“手型”0 误判；留出集无坏手样本，召回未知 | ❌ → 停用“肢体比例”子规则，“手型”保留 | K-REV-231 | data/review_pages/asset_reflock/heldout_bakeoff.json |

## BK. 出图模型对决（BAKEOFF，2026-11-01 第 1 轮；工具 tools/bakeoff/，报告 docs/ep02_iter/image_bakeoff.md）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| BK1 | 换写实底模（Klein 4B / Z-Image / Krea 2）就能同时解决“塑料”和“脸不像” | 8 镜 × 12 个模型 / 组，同提示词语义，统一 1.5 倍出图后缩到 768×1344；Q1 用契约 postflight | Klein 4B 契约组：质感 +0.58，Q1 过线 12%（林晚 0.43）；Z-Image Turbo：+0.11 / 0%；Krea2 Identity Edit：+0.25 / 0%；Qwen 2.1 S★ 只挂脸：−0.20 / 73%（0.72）；现行出图：−0.61 | ❌（两项没有一个模型同时赢）→ 第 2 轮测“Qwen 出图 + 写实底模第二段加工” | K-REN-B01 | data/ab/image_bakeoff/summary.json |
| BK2 | 有身份参考会牺牲质感 | 同模型 text / face / contract 三组对照 | Qwen 2.1 林晚：0.19 / 0.72 / 0.66，质感 −0.17 / −0.20 / −0.39；Klein 4B：0.16 / 0.43 / 0.43，质感 +0.61 / +0.63 / +0.58 | ◐（Qwen 契约组质感降 0.2，Klein 几乎不降） | K-REN-B04 | 同上 |
| BK3 | 契约 Q4 的整图 Laplacian ≥175 能判出“塑料 / 糊” | 留出集 46 张，标签由总调度给出 | 判对率 0.587（lap+sat 口径）/ 0.500（config 口径），AUC 0.41；脸部 Laplacian AUC 0.93（只有 2 个反例） | ❌ → 改为只记录，改用脸部区域 | K-REV-B02 | data/review_pages/asset_reflock/heldout_bakeoff.json |
| BK4 | 契约 Q2 鞋线 0.775 可靠 | B4 中全景 14 张留出 | 判对率 0.714；正例 0.710–0.861，反例 0.641–0.780，有重叠 | ◐（要扩充样本或加判别） | K-REV-B03 | 同上 |
| BK5 | 契约 Q5（含林晚指长比 ≤4.6 豁免）不会误报 | 18 张留出（没有坏手样本） | 判对率 0.611，7 张误报全是“肢体比例可疑” | ◐（只能报误报；召回率测不了） | K-REV-B03 | 同上 |
| BK6 | Qwen 2.1 的 edit 不行，换编辑模型会更好 | ep05-S5 不合格帧 × E1 换脸 / E2 去油 / E3 换背景 × 6 个模型 | E1 林晚：Qwen 2.1 0.753 > FireRed 0.711 > Klein 0.682 > Krea2 IdEdit 0.628 > 2511 0.564（源图 0.534）；E2 脸部高频：Klein 2.12，其他 1.35–1.65，但 Klein 的林晚余弦掉到 0.39 | ◐（换脸 2.1 本身最好；去油换 Klein，但要过身份闸门） | K-REN-B05 | data/ab/image_bakeoff/results.json E1–E3 |
| BK7 | 只看队列里有没有别人的任务，就算在让道 | 11-01 02:27，GPUVIEW 看到 BAKEOFF 占满 gpu36:0/1，出帧方在等空道 | 改成 hold 文件 + 空闲 180 秒 + 每道 1 个任务 + comfy_tag | ❌ → 修复 | K-OPS-B06 | tests/test_bakeoff.py |
| AM7 | FLUX.2 klein 4B 能把全部资产（场景 / 单品 / 设定图）一起重出 | ASSETMASTER 11-01：同一批资产 Qwen 2.1 与 Klein 4B 各出一版，按契约自动选（choose.py）；BAKEOFF 第 1 轮对照 | 场景 18/18、单品 38/38 Klein 版都过（0 脸 0 字），全部选 Klein；设定图 Klein 版 Q1 0.84–0.93 能过，但目检单品不一致（林晚 B 束腰成连衣裙式、鞋不对）、脸偏娃娃感 → 12/12 选 Qwen v2。BAKEOFF r1：Klein 4B 带脸参考林晚 ArcFace ≈0.43（Q1 过线 12%），质感综合 +0.58；Qwen 2.1 S★ 0.72（73%），质感 −0.20 | ◐（不带脸的资产用 Klein，带脸的设定图 / 首帧仍用 Qwen，等项目方看对照页定首帧主模型） | K-AST-260、K-REN-132 | data/assetmaster/final_choice.json；docs/ep02_iter/bakeoff_r1.md |
| AM6 | 双人镜参考板（两脸 + 两人设定图 / 单品 / 场景）能兼顾身份与服装 | frames_v2 run5 全量（frame_v9），Q4 两次不过 → 第 3 次换“两脸 + 林晚造型图” | 首帧通过 16、不合格 3；尾帧通过 7；variant 胜出 {'plan': 19, 'both_faces+board': 1} / 尝试 {'plan': 51, 'both_faces+board': 14}；Q2/Q5 重打分救回 0 | ⏳ 见数字（REFLOCK 阈值仍待 BAKEOFF 留出集验证；⏳ 由 ITERAUDIT 按原文“仍待验证”补标，ASSETMASTER 可改） | K-AST-260、K-REN-132 | data/assetmaster/frames_v2/summary.md |
| AM8 | 笔记本编排 + 断点续跑足够喂满 6 卡 | frames_v2 run1–run13（IMGPERF data/qa/imgperf/runner_timing_gpu.txt） | 续跑会把已出图的尝试重新提交：9 次缓存命中 0 GPU 秒，仍各付 38–163 s 打分；早期打分在出图道线程里串行，占道 2.6–>7× GPU 时长；本机 CPU measure_local 223 s/张 → 改 gpu33 postflight_full 后 30–61 s；PRODUCER“出完即释放道、后台打分”实测 1.46–1.5× | ❌ → 续跑必须跳过已出图的尝试（按文件 / sha 判，已出图只补打分）；出完图先释放道再打分；打分在 GPU 机器原地做；单一出图编排者（交 PRODUCER） | K-OPS-P01 | data/qa/imgperf/runner_timing_gpu.txt；data/assetmaster/frames_v2/state.json |
| V9 | 镜头一旦“通过”就不会再变 | ep03-S6：派单时首帧 image #2 ok=true，出片通过后 ASSETMASTER 把 #2 改为 ok=false、撤当前 | 视频仍标通过、且被登记为当前（DATAALIGN 发现 from_first 对不上） | ❌→编排器加过期检查：首帧换版 / 被撤即作废旧片 | K-OPS-304 | data/renders/ep03/S6/takes.json |
| V10 | 过了 postflight 的首帧就能出视频 | 总调度亲审打回 ep03-S7 v2、ep02-S1 v2（特写塑料感）、ep03-S6 v2/v3（男角不像顾沉），PRODUCER 在 takes.json 写 master_reject | 这些帧的 postflight.ok 仍是 true；ep03-S7 v1 视频就是用 #2 出的、已通过并登记为当前 | ❌→ master_reject 视同撤销：passed_frames 不认、编排器作废旧片、请 DATAALIGN 撤当前 | K-OPS-304 | data/renders/ep03/S7/takes.json |
| V11 | 让道模式（别人空 3 分钟才交、每道 ≤1）就不会挡图片 | 总调度统计 ep06-S1 首帧排队 | 911 s 等待对 65 s 计算；一条视频约 9 分钟，首帧赶在视频刚提交后到就要等整条 | ❌→ 首帧 / 尾帧未出完前视频只用 gpu36:2；排队中的视频撤回；被删的任务编排器记 lost 后重派 | K-OPS-305 | data/producer/registry.json |
| BK8 | 多参考输入时模型会出成参考板拼图，现有契约项抓不到 | 总调度 11-01 亲审 #05（Krea2 ref 契约组）；新增 ref_copy 检查后在 188 张上回测 | 该组 6 张全是拼图，检查抓到 4 张，其余 182 张 0 误报 | ✅（检查已上线，整组不计分） | K-REV-B07 | data/ab/image_bakeoff/results.json |
| BK9 | 阿岚各列不一致是因为参考图用错了 | 核对两张参考的 sha256 + 比较 B6 各列对阿岚的余弦 | 两张 sha 相同；Qwen 系 0.91–0.94，Krea2 IdEdit 0.66，2511 0.60，Klein 0.46–0.57，只给文字 0.00–0.37（Z-Image 出成男性） | ❌（参考图没错，是模型保身份能力不同） | K-REN-B08 | data/ab/image_bakeoff/results.json B6_* |
| BK10 | Qwen 首帧 + Klein 4B 低去噪（脸部掩码）能补上质感 | 第 2 轮 24 张：去噪 0.30 / 0.45 加掩码，0.30 不加掩码作对照 | 质感综合分 −0.34 到 −0.42，第一段为 −0.335；整图 Laplacian B1 从 121 降到 91；身份变化 ±0.01 | ❌（脸受保护就没变化，整图略软）→ 换成“身份引导的脸部细节重绘” | K-REN-B09 | data/ab/image_bakeoff/summary.json |
| BK11 | 排名用的 Q5 是旧口径 | REFLOCK 复核：32 条不过里有 19 条只因已停用的“肢体比例”规则；用 postflight_full 重打 188 张 | 例：Klein 4B 契约组 75%→100%，Qwen 2.1 只挂脸组 64%→91% | ✅（已重打，排名改用新口径） | K-REV-B03 | data/ab/image_bakeoff/rescore_pf33.json |

## BGM. 整集配乐链接（BGM10，2026-11-01；说明 docs/BGM.md，报告 docs/bgm/r1.md，结果 docs/bgm/r1_results.md）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| B1 | 写作模型能按 nsfs.bgm_brief/1 一次写对 | 10 集各调一次 music_brief（large-flash） | 9/10 第 0 轮通过；ep09 被校验器误判（“led by solo” 命中 by+大写的忽略大小写正则）3 轮改不掉 | ✅ 格式可行；❌ 校验器有假阳性 → 改成大小写敏感 + 回归测试 | K-EDT-B01 | data/music/series10/ep09/brief.report.json；tests/test_bgm.py::test_brief_lowercase_by_is_not_a_named_work |
| B2 | ACE-Step 候选直接可用 | 每集 4 条，度量 + 闸门 | 静音段（>2.5–3 s）与能量反向是主要淘汰原因；无一条因人声淘汰（vocal_rel_db −21…−46） | ✅ 闸门有效；◐ energy_r 多数偏弱（模型不跟能量曲线），只作提示 | K-EDT-B03 | docs/bgm/r1_results.md |
| B3 | 打分可以和生成放同一台 | gpu33 上 CPU 打分（nice 15） | gpu33 负载 400–1200 时一条 40+ 分钟；挪到 gpu36 一条约 1 分钟 | ❌ → score_host = gpu36 | K-EDT-B05 | config/bgm.json generation.score_host |
| B4 | ACE-Step 默认超时够用 | CPU 回退 + 高负载 | ep04 第一次 4/4 “timed out after 600 seconds”，旧代码还把空表交给审听模型、占掉一轮 | ❌ → CPU 3600 s；生成失败按基础设施重投、不占审听轮次 | K-EDT-B05、K-EDT-B06 | data/music/series10/ep04/meta.json infra_failures |
| B5 | 共享 GPU 上让道可行 | 每条候选之间查 ComfyUI 队列 | ep04 在 gpu33:0 生成时 ComfyUI 增长到 15.4 GB，本工具第 1 条 OOM、其余 3 条记 yielded 重投 | ✅ 让道生效（自己 OOM，不是对方）；残余风险：一条候选生成期间（约 1–2 分钟）不能中途让出 | K-EDT-B05 | gpu33 jobs/ep04_r1_1793481097/result.json |
| V12 | 合成器“成功退出”= 合成对了 | ep01 第一次合成（07:10） | 代理没同步回来（sync.py 只扫 2 层，episodes/ep01/*.mp4 在第 3 层），sources 为空，合成器全部用静帧占位也返回 0 | ❌→ sync 改 3 层；night.finalize 代理到位数 < manifest 有代理的镜数就拦（ASSEMBLE_BLOCKED）；07:14 重合：5 镜视频 + 2 镜（尽力，不进合成）静帧 | K-OPS-301 | data/episodes/series10/ep01_v1.timeline.json |
| V13 | 换 seed 能救“动作不足” | ep01-S2 固定机位微表演，4 个 seed | mean 0.34–0.44，全部不过 → 换 seed 无效 | ◐ 加系统最低动作提示（mot 变体，K-REN-302），对 S2 用 force_next 验证中；总调度签字的 ep01_v1 不覆盖，重合成出 ep01_v2 | K-REN-302 | docs/series10_video/ep01_review.md |
| V14 | ep01 造型前后不一致（S1–S3 无外套、S4/S5/S7 有）是剧本安排 | 对照 P4 造型行 / 分拍 / 设定图 | 造型 A 含短款西装外套、全集无脱穿动作，S3 分拍还写“拉平西装外套下摆”；S1–S5 的 img 行没写外套 → 首帧丢单品；S5 首帧是黑外套 + 黑长裤（设定图是灰短外套 + 深灰铅笔裙） | ❌ 首帧问题 → 交 PRODUCER 按 Q2 重出 S1/S2/S3（S5、S4 核对）；建议出图编译器补外层单品 | K-OPS-304 | data/pipeline/runs/series10_v1/ep01/P4_ep01.md |
| V15 | 纯 Ref2VA 兜底能过契约 | REFLOCK 审 VIDEO10 造型槽补丁（改为与首帧同源的造型 id 后落地，services/recipes 三个文件，越界改动已报） | ep01-S6 r24 preflight I1–I10 全过（此前所有 Ref2VA 变体被 I3 挡）；S6 已 force_next r24、S2 force_next mot 在 gpu33:3 验证 | ◐ 待出片验证 | K-REN-303 | services/recipes/ns_recipes/compiler.py |
| V16 | 离线循环里一张坏图 / 缺模型只影响那一镜 | 11-01 离线 night.log 逐条归因（PROD fredw-2b 派） | 10:44–10:52 三次 LOOP_ERR 'image file is truncated'、10:46/10:48 build_jobs FaceModels(*None) 都让整轮中断，所有集派不出 | ❌ → 截断首帧本轮跳过该镜、缺模型只跳过新裁 | K-OPS-306 / K-OPS-307 | tests/test_video10_resilience.py |
| V17 | 合成失败会被下一轮自动重来 | ep04 11:11 TtsUnavailable（night.py 跑在 gpu36 副本）后到 16:04 一直 assemble_failed | finalize 只处理 rendering，assemble_failed 是死状态；16:04 重启后第 1 次自动重试仍 TtsError（偶发），同参数手动诊断 rc=0 | ❌ → 合成前查配音解释器（hold_tts）、20 分钟自动重试 ≤3 次、rc≠0 不认旧残片 | K-OPS-309 | data/pipeline/runs/series10_v1/video/night.log |
| V18 | 离线合并回来的数据是完整的 | 16:14 全量解码 data/_offline_pull 与现行文件 | 7 张已选设定图（林晚 lookA/B/C 等）被截断副本覆盖；master_rejects.json 按整文件 mtime 丢了 gpu33 上 ep05-S3/S5 的 unwait | ❌ → 从 _backup 恢复、坏图隔离；deploy 推图先解码；merge_pull 根因交 owner | K-OPS-311 / K-OPS-308 | data/_quarantine/prod_20261101_truncated_sheets/ |
| V19 | 手部局部大特写换 seed 能救（ep05-S3/S5 驳回 8 次） | 对比 ep10-S8 v8（成功）与 ep05-S3/S5 v8 的提示词 / 参考槽（data/renders/ep05/S3/takes.json、ep10/S8） | 成功镜只送 1 张指甲图、正文只写手；失败镜送了以围裙为主的“手套”裁切（torso_share 0.499）、正文写胸口 / 肩头 / 锁骨、林晚锁去掉了发色 | ❌ 换 seed 无效 → 手部重裁（0.0）、局部扩为手与肩颈 + 保留发色、P4 lint QW-W10；待网络恢复用 ep05-S3 验证 | K-AST-V10 / K-REN-V11 / K-WRT-V10 | tests/test_video10_resilience.py |

### V10 越界登记（ITERATION_PROTOCOL O1；services/recipes/** 归 AUTOPILOT，VIDEO10 改动，待 ITERAUDIT 复核）

- ✅ 10-31 夜｜`services/recipes/ns_recipes/graph.py`：pdd_conf / PDD-Acc 节点；ref2va 两段式；_upscale_tail；upscaler 输入名 enable_chunking → enable_temporal_chunking。原因：S10V-1 对照要 PDD + Ref2VA 两段式；旧输入名节点不认。复核：ITERAUDIT 11-01 ✅——两台 /object_info 逐节点一致，真实输入名就是 enable_temporal_chunking（旧名会被拒），模型链与 LAB 实跑图同构，见上方 V5-R（证据 data/qa/iter_gate/VIDEO10_graph_review.txt）
- ✅ 10-31 夜｜`services/recipes/recipes/ref2va_pdd2.yaml、i2va_pdd2.yaml`：新配方。原因：同上；i2va_pdd2 现为默认（K-REN-301）。复核：ITERAUDIT 11-01 ✅——PDD 文件 / 放大模型 / attention / nfe 取值都在两台服务器选项里，编出的图 6/6 一致（证据 data/qa/iter_gate/VIDEO10_graph_review.txt）
- ✅ 11-01｜`services/recipes/ns_recipes/prompt.py`：prompt.min_motion_cue（第一个分拍时间码前插最低动作提示）。原因：ep01-S2 动作不足，总调度要求系统层修（K-REN-302）。复核：ITERAUDIT 11-01 ✅——默认关，只在 mot 变体开（43 镜）；129 条全部插在第一个 “At 00:0x.000” 之前、0 条退到句末；只加物理提示，不改写作方正文（证据 data/qa/iter_gate/VIDEO10_graph_review.txt）
- ◐ 11-01｜`services/recipes/ns_recipes/compiler.py`：ref_slots → look_slots（Ref2VA 造型槽，造型 id 与首帧同源，missing 进计划）；ref_slots 计划保留 missing、图 / 提示词只用有路径的槽。原因：契约 I3（K-REN-303）。复核：REFLOCK 11-01 审过（改一处后落地）；待 ITERAUDIT
- ✅ 11-01｜`services/recipes/ns_recipes/prompt.py`：build_ref2va：outfit 槽的 subject / retention 句（含 “its missing head”）。原因：同上。复核：ITERAUDIT 11-01 ✅——82 个 Ref2VA 变体里 <Picture N> 编号与图里 ref_image 槽逐一对上（身份句 / 造型句），0 处错号（证据 data/qa/iter_gate/VIDEO10_graph_review.txt）
- ✅ 11-01｜`services/recipes/ns_recipes/graph.py`：ref2va：outfit 槽占位符 @look:<角色>。原因：同上。复核：ITERAUDIT 11-01 ✅（VIDEO10 路径）——82 个 @look 都有带路径的 outfit 槽，598 次 schema 核对 0 错；局限：只有 build_jobs.py 替换 @look，API recipe_render 会以“未知占位符”拒收、iterate_loop submitter 不映射，走那两条路要 AUTOPILOT 补（证据 data/qa/iter_gate/VIDEO10_graph_review.txt）
| AX7 | 资产页启动慢（12–14 秒）要靠前端缓存解决 | 后端首屏改成磁盘缓存后，在 1440×900 重新量人物页、人物登记页各 2 次 | 1.1–1.9 秒 / 0.8–1.1 秒；7 个“慢接口”逐个 curl，都 <0.2 秒 | ❌ → 后端缓存已解决，前端不改；以后报“慢”先重新量 | — | apps/web/e2e/assetux/boot_log.json |

<!-- K-OPS-305 amendment 2026-11-01 OFFLINE -->
- K-OPS-305 修订（2026-11-01 离线交接，总调度批准）：night.py 的 frames_busy 只数监督能自动派的帧；等总调度的（master_reject / 等复核）和等 REFLOCK 的 pending 帧不算“帧忙”。帧基本出完后，视频改用让道模式，可用 gpu33:0/1/3 和 gpu36:0/1/2；帧有真实派单时，先拿下一条空出来的道。要恢复旧做法，在 night_control.json 里设 "frames_exclusive": true。代码：tools/series10_video/night.py gated() / apply_lane_policy。

## DH. 内容缺陷猎捕（RSI / ITERAUDIT，2026-11-01；清单 docs/rsi/DEFECT_HUNT.md，状态 data/qa/defect_hunt/state.json）

| # | 假设 | 做法 | 数字 | 结论 | 规则 | 证据 |
|---|---|---|---|---|---|---|
| DH1 | R11-2 / R11-8 看镜头是剧本写出来的 | 剧本字段查看镜头 / 首拍无视线（DH-S01 / S02）对照总调度看镜头标签（DH-F18 / V21） | 剧本 0 / 0；首帧标签 71/100 看镜头，片头 56/72 看镜头（10 条带定格） | ❌ 不是剧本，是出图 / 出片模型默认行为；修在渲染侧 | K-OPS-Q14 | data/acting/gaze_labels.json |
| DH2 | 多手只出在被淘汰的尝试里 | 成片 timeline origin 对照现评分（DH-X03） | ep01_v2 的 S2（mot 3 手 / 1 人）、S4（s2 5 手 / 2 人）进了成片，V6 都判通过 | ❌ 进了成片；闸门放行 | K-REV-Q06、K-REV-Q05 | data/episodes/series10/ep01_v2.timeline.json |
| DH3 | 首轮视频缺陷数代表成片质量 | 改为全部尝试 / 现行版两个数 | 景别 106 / 38、身份 82 / 24、多手 45 / 14、坏手指 91 / 40 | ❌ 全部尝试的数偏大 2–3 倍；只用现行版分派 | K-REV-Q03 | data/qa/defect_hunt/state.json |
| DH4 | 口型缺陷 32 条 | 拆开 V7 不通过和未测 | 不通过 26（现行 4）、未测 6 | ✅ 已改口径 | K-REV-Q04 | data/qa/defect_hunt/state.json |
| DH5 | 鞋子 lint VQ-W1 在写作链路里跑 | grep 加载链路 + 测试逐条核对规则 lint 号 | 原来 0 处加载；接上后 VQ-W1 ∈ validate_qwen_script.RULES；现稿命中 0 | ✅ 已接线 | K-OPS-Q15 | tests/test_defect_hunt.py |
| DH6 | 看图类能借空闲卡跑完 | defect_vlm 试跑 2 条 | 1 条 OOM（ComfyUI 同卡涨到 16 GB），1 条视频输出不是 JSON | ⏳ 没跑完，交 VQA / VQAGATE 在空闲窗口跑 | K-REV-Q06 | data/qa/defect_hunt/vlm_results.jsonl |
| DH7 | 节奏慢是剧本把镜头写长了 | 查时长来源：80 镜 duration_source 都是 script；H3 帧数 = h3_lint.frames_for_seconds(时长)；写作模型拿到的输入是“总时长目标 60 ±5、镜数 6–上限” | 目标 60–65 秒 ÷ 镜数上限 8 → 平均镜长下限 7.5 秒；K-WRT-203 原文“7–9 秒常见”；QW-T1 37 处 | ◐ 根子在合同（镜数上限 × 6 秒 < 50 秒下限），写作侧规则已落、结构性冲突交总调度（MASTER_PICTURE G29） | K-WRT-Q07 | tools/qa/writer_lints.py |
| DH8 | 7 条红测试互不相关 | 逐条看断言 | 2 条（身份脸）同一个根因：face_overrides 指向整张设定图 A-s202（10:58 fred 点选）；1 条作业清单过期（10:32 生成，11:14 编译器加了视线句，24/80 一致）；1 条断言过期（framing 11:10 改成正向句）；1 条测试复制真实 data/looks；1 条写真实 refboards（已改成临时目录）；1 条已知 | ✅ 已归因，越界的写进 MASTER_PICTURE G20–G24 | — | docs/master/MASTER_PICTURE.md |

## RS. 真人写实调参（RESEARCH，fredw-2b 派，R11-12 / R11-13，2026-11-01；调研 docs/research/realism_tuning_20261101.md）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| RS1 | S★ / frame_v9 的后处理锐化让脸更像真人 | 生产当前首帧原图（ep01-S1 / S2 / S5，非亲密）CPU 重做三档：R0 USM 1.2/60/2（复现交付图，像素差 0.0）、R1 不锐化、R2 0.8/30/3 | lap_full R1/R0 = 0.477–0.494；halo R0/R1 = 1.53–1.71；p_plastic 三档 0.9994–0.9999 不变 | ❌ 锐化只抬指标和白边，不改变塑料脸 → 不再加锐化；减弱要项目方看图定 | K-REN-X02 | data/ab/realism_ab/metrics.json |
| RS2 | 契约 Q4 lap_full ≥175 量的是皮肤质感 | 同上三镜 + leica_sharp ep02 三镜 Sstar_g→Sstar | 去掉 USM 后 3/3 由过变不过；ep02 ×2.05–2.14 | ❌ 量的是“有没有锐化”，解释 BK3 AUC 0.41 → 质感指标在未锐化图上测 | K-REV-X01 | 同上 |
| RS3 | 写作方 img 光线已经有方向 | series10 + ep02 r3 63 条人物镜 img | 62/63 有方向 / 落点，1 条“暖黄居家灯光” | ✅ 加 QW-W9 守住 | K-WRT-X05 | tools/qa/writer_lints.py |

## WF. 生产工作流结构缺口（WORKFLOW / AUTOPILOT，fredw-2b 派，2026-11-01）

| # | 假设 | 实验 | 结果 | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| WF1 | 并回服务器结果时“新者为准”就安全 | 查 11-01 离线并回后 asset_refs.sheet_crop 报错的 7 张设定图 | 服务器副本都是笔记本原图的字节前缀（例 2035200 / 2857960 字节），按新者为准覆盖了好图；tests/test_gen_contract.py 5 例因此失败 | ❌→ 覆盖前验完整性 + 截断前缀不覆盖；离线 / 远端运行前跑依赖自检 | K-OPS-W02 | data/_offline_pull/_backup/ |
| WF2 | 拿底稿跑 R11-3 返修再 merge 导入即可 | 查 data/import/script_v2.json sources | 各集来自 6 份 md；用 10-31 23:14 底稿会把 lookfix / qwch6 的修改整集覆盖回旧版 | ❌→ 按集取现行来源拼输入、只含目标集；桩自检 ep07–10 35 镜进出一致 | K-OPS-W04 | data/autopilot/repair_chain/20261101-162428/verify.json |
| WF3 | tunnel.sh 的 while 循环足以保证隧道可用 | 注入：挂起 gpu36 隧道 ssh（进程活着、转发卡死） | 循环不会重连；看门狗 109.4 s 恢复，断线注入 42.6 s | ❌→ 看门狗探测 + 杀 ssh 交循环重连；跳板 TCP 不通时不杀 | K-OPS-W05 | data/qa/infra_inject.jsonl |
| WF4 | 笔记本经跳板派单可以撑满 7 张卡 | 总调度 16:55 实测 + 16:58 起跳板 TCP 整体不通 | 7 张卡只有 1–2 张在跑，producer 日志全是 10054 / ComfyUnavailable | ❌→ 生产默认服务器常驻，笔记本只做控制面 | K-OPS-W07 | docs/overnight/OFFLINE_20261101.md |
| WF5 | series10 首帧路线改 Pika 后 flush 防护自动生效 | build_jobs 直接按 id 编译、不走选择器 | overlay 的 block_recipes 只在选择器回退链里生效，显式指定时不拦 | ❌→ compiler.blocked_swap：被禁且有替身 → 换 i2va_pdd2 并记进计划；80 镜干跑 79 Pika / 1 换回（ep05-S4，已 done） | K-REN-301 | tests/test_recipe_pika_default.py |

## VR. 视频根因（VIDEO-RCA，W11，2026-11-01；报告 docs/video_rca/RCA_r1.md，实验 data/ab/video_rca/，审片页 data/review_pages/video_rca/）

| # | 假设 | 实验 | 结果（数字） | 结论 | 规则 | 来源 |
|---|---|---|---|---|---|---|
| VR1 | 片头看镜头主要继承首帧 | 人工标签交叉表（首帧 × 片头） | 首帧看 → 片头看 49/54；首帧没看 → 4/10；Ref2VA（无首帧）3/10 | ✅ 根在首帧 | K-REV-704 | tools/video_rca/rates.py |
| VR2 | 系统句自己在要求看镜头 | 读代码 + 编译稿 | framing.two_shot_clause “朝向镜头 / toward the camera”；重试锚点句 127/538 条 facing the camera | ✅ | K-REN-702（已改）、K-REN-703（交 REFLOCK） | services/agent/ns_agent/framing.py；video/prompts/ |
| VR3 | 双人出图系统句改“互相看着对方、眼睛不看镜头”能去掉看镜头 | ep01-S4 同参考同 seed × 2，只换一句 | 4 张脸看镜头 3 → 0 | ✅（2 seed） | K-REN-703 | data/ab/video_rca/r1_img_gaze/faces.jpg |
| VR4 | 单人出图加“不看镜头”句即可 | ep01-S3 × 2 seed | 2/2 仍看镜头；只加“图1 只取身份”角色句 2/2 仍看；角色 + 四分之三侧脸句 S3/S5 4 张里 2 张不看 | ◐ 正脸参考图是残余主因 | K-REN-703 | data/ab/video_rca/r4_img_single/faces.jpg |
| VR5 | Pika 比 PDD 两段式更清楚 | 同首帧同 seed 同提示词，sharp.py | S5 中段/首帧 0.658 → 0.784；S3 0.541 → 0.469 | ◐（近景改善，大动作镜都降） | — | data/ab/video_rca/r1_base_cue/*.sharp.json |
| VR6 | Pika 没有 4 帧一顿 | 同上 J4 | Pika S2/S4/S5 J4 1.23–1.40、z 4.5–10.8；PDD z 0.35–1.35 | ❌ Pika 也有，靠后期去抖 | K-LOOP-004 | r1_base_cue/results.json |
| VR7 | Pika 必然泛红 | ep01 五镜（无脸红词） | cheek_red 0.043–0.095 全过 | ❌ 无脸红词不泛红（与 C2 一致） | K-WRT-R01 | r1_base_cue/results.json |
| VR8 | 景别退档出在视频 | 首帧脸高 vs 视频脸高 | 现行 55 条：比要求远 21，其中首帧本就远 17；视频比首帧再远 ≥1 档 11 | ◐ 主要在首帧 | K-REV-704、K-REN-701 | data/ab/video_rca/ff_size.json |
| VR9 | 首帧不看镜头时 Pika 会转头看镜头 | ep01-S4 用“两人互看”首帧 A / B 出 Pika，抽 5 帧 × 2 脸 | 20 个样本 0 个看镜头 | ❌ 不会；开关在首帧 | K-REN-703 | data/ab/video_rca/r4_pika/faces_vid.jpg |
| VR10 | 外套消失靠换 seed / 系统句 / 去 cropped 能消 | ep01-S3 同首帧，Pika ×5 + PDD ×1 | 6/6 消失再穿回 | ❌ | 写作草案（knowledge/inbox/2026-11-01_video_rca_writer.yaml，外套动作） | r1_base_cue、r4_pika、r7_outfit_text |
| VR11 | 外套消失是“对衣服的动作”那一拍造成 | 只把“smooths the hem of her blazer”换成不碰衣服的动作 / 保留动作补 staying on | 换掉 0/2 消失；补 staying on 2/2 消失 | ✅ | 写作草案（knowledge/inbox/2026-11-01_video_rca_writer.yaml，外套动作） | r8_outfit_action、r9_outfit_keep |
| VR12 | 正向双人句和实测句一样有效 | ep01-S5 / ep03-S4 × 3 seed（本机道） | 旧 8/10、正向 0–1/10、实测 0/12 | ✅ 改回正向句 | K-REN-703 | data/ab/video_rca/r5_img_twoshot/ |
| VR13 | 正脸 + 侧脸双参考能去掉单人看镜头 | 单人 3 镜 × 2 seed（本机道） | 看镜头 3–4/6 → 3/6；sface 0.885 → 0.843；1 张多半个头 | ❌ | — | data/ab/video_rca/r2_dualref/ |
| VR14 | 删画外造型分句能防 Pika 拉远 | 复用 r1 原编译稿同 seed，S4/S5/S6 | 脸高几乎不变，印样一致 | ❌ Pika 本来不拉远 | K-REN-701 | data/ab/video_rca/r3_hide_offframe/ |
| VR15 | Pika 没有 4 帧一顿 | judder.py 量 r1 七条 + 冒烟 | 慢动作镜 J4 1.24–1.35（z 3.9–10.8，第 3 相位跳）；大动作镜 2 帧交替；去抖慢动作镜代价 ≤3%，快动作 −25% | ❌ 有，门槛 1.2 去抖 | K-REV-705 | data/ab/video_rca/r6_dejudder/ |
| VR16 | Pika 口型不过是随机的 | 3 seed × 6 组（复用 r1 原编译稿，V7 用旧镜头信息重跑） | 林晚说话 3/3 过（开合 0.016–0.020）；顾沉说话 6/15 过（开合 0.006–0.011，张嘴帧 0） | ❌ 是男主说话时嘴几乎不动 | 写作草案（knowledge/inbox/2026-11-01_video_rca_writer.yaml，台词那拍别低头） | docs/video_rca/RCA_r3.md §1.1 |
| VR17 | 改 VOICE 短语 / 补系统口型句 / 台词那拍不低头能救口型 | 各 3 seed | 0/3、1/3、2/3（corr 均值 0.24 → 0.41） | ◐ 只有“不低头”有方向性改善 | 写作草案（同上 inbox） | data/ab/video_rca/r14a_voiceword、r14b_lipcue、r15_headup_* |
| VR18 | 去掉整理动作外套就完整 | r8 2.4–4.0 s 逐帧（AUDIT 限定） | 不整件消失，但成无袖短马甲 2/2 | ◐ 第二根因：坐→站大幅姿态 | K-WRT-702 限定（交 ITERAUDIT） | data/ab/video_rca/r8_outfit_action/*_kf.jpg |
| VR19 | 去抖要按动作幅度分档 | 全分辨率 4 条 | 4 帧型 −1.5 ~ −3.7%（含大动作 S6）；2 帧交替 −25.6%（门槛自然排除） | ❌ 不分档 | K-REV-705 | docs/video_rca/RCA_r3.md §1.3 |

