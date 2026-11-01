# 核心总纲（2026-10-31）

这份文件把 ep01–ep02 迭代中所有 RSI 的结果整理成一页，给项目方读。每条都附源文件，数字照原文抄录。
- 更细的“尝试 → 结论 → 规则”逐条记录在 [knowledge/RSI_LEDGER.md](../knowledge/RSI_LEDGER.md)，共 52 条。
- 系统规则的唯一来源是 [knowledge/rules/](../knowledge/rules/)（约 170 条，且还在增加；用 `tools/knowledge/compile.py --check` 校验）。
- 系统怎么自动跑，见 [AUTOPILOT.md](AUTOPILOT.md)。

## ① 产品与流水线（P0 → P12）

```
提纲 P0 ─▶ storyline P1 ─▶ 单集大纲 P2 ─▶ 剧本 P3 ─▶ 分镜/Shot Spec P4 ─▶ 资产 P5 ─▶ 首帧 P6 ─▶ 配方/提示词 P7 ─▶ 视频 P8 ─▶ 声音 P9 ─▶ 剪辑 P10 ─▶ 审片 P11 ─▶ 成片 P12
└────────── 写作网关 + 链条校验（run_chain）──────────┘   [闸门:身份图] [闸门:首帧]  └── 配方引擎 + 出片 Loop（6×3090）──┘  合成       审片模型    [闸门:交付]
                                                                                       ▲                                         │
                                                                                       └──────── 规则阶梯重出 / 归因（P11-RETRY）───┘
```

| 段 | 负责代码 | 规则来源 | 需要人吗 |
|---|---|---|---|
| P0→P4 写作 | [tools/pipeline/run_chain.py](../tools/pipeline/run_chain.py)、[config/pipeline/chain.yaml](../config/pipeline/chain.yaml)、[tools/autopilot/writer.py](../tools/autopilot/writer.py)（逐镜自检返修） | 写作规则 [config/script_chat_rules.md](../config/script_chat_rules.md)（附录 sysimpl-vN），加上知识包 [config/recipes/writer_knowledge.md](../config/recipes/writer_knowledge.md) | storyline / 大纲两处闸门可选，默认关 |
| P4→P5 身份资产 | [tools/ab/char_sheet_qi21.py](../tools/ab/char_sheet_qi21.py)、[tools/identity_metric.py](../tools/identity_metric.py) | K-AST-* | **挑身份图** |
| P5→P6 首帧 | API `frame-jobs` | K-AST-R01 / R03 | **定稿首帧** |
| P6→P8 配方与出片 | [services/recipes/ns_recipes](../services/recipes/ns_recipes)（选配方、编译）、[tools/iterate_loop/loop.py](../tools/iterate_loop/loop.py) | K-REN-*、K-PRM-*、[rules.yaml](../tools/iterate_loop/rules.yaml)（由知识库生成） | 许可登记、开新实验 |
| P8→P10 声音与剪辑 | [tools/assemble_episode.py](../tools/assemble_episode.py)、[services/post/ns_post](../services/post/ns_post) | K-EDT-* | **挑音色** |
| P10→P11 审片 | [tools/ep02_director/review.py](../tools/ep02_director/review.py)、[tools/autopilot/director.py](../tools/autopilot/director.py)（审片模型） | K-REV-*，提示词 [director_system_prompt.md](../config/recipes/director_system_prompt.md) | 低置信度的镜头人工复看 |
| P11→P12 交付 | `tools/autopilot/run.py approve --gate delivery` | — | **交付确认** |

每个角色怎么干活、对应哪段代码，见 [docs/playbooks/](playbooks/)。

## ② 已确认有效的做法

| 做法 | 证据（数字） | 规则 | 来源 |
|---|---|---|---|
| 成片用**基模 24 步 + 只给首帧**（不挂 Turbo） | S1 J4 1.34 → 1.12，脚重影消失；静止镜从 7/11 降到 2/11 | K-REN-002、K-REN-004 | [LEARNED_SPECS §B](ep02_iter/LEARNED_SPECS.md)、[render_quality.json](../config/render_quality.json) |
| **Ref2VA 两段式**（20 步，第 10 步切；544×960 → 3D 放大 → 768×1344），用于静止情绪镜、对白近景、双人镜 | S6 mean 0.31 → 1.28（不合格 → 通过）；S1 SFace 0.24 → 0.53；S2 cheek_red 0.52 → 0.10 | K-REN-011、K-REN-R02 | [lab_recipes 批 2](ep02_iter/lab_recipes.md) |
| **Ref2VA 参考用脸部裁切图**（不用整张定妆图） | S2 SFace 0.29（FL2VA 基模）→ 0.81；服装不再渗漏；cheek_red 0.08；J4 1.03 | K-AST-R03 | [lab_recipes 批 3](ep02_iter/lab_recipes.md) |
| **项目方设定图流程**（Qwen-Image 2.1 四栏）定身份 | 设定图对定妆脸余弦 0.926；项目方已选林晚 A-s202 / 顾沉 s101 / 陈宇 s202 | K-AST-R05、K-AST-002 | [consistency_research](ep02_iter/consistency_research.md)、[identity_refs/manifest.json](../data/assets/identity_refs/manifest.json) |
| **首帧用设定图作参考出图**（R 方式） | 林晚 0.575 → 0.706；男角从此有身份来源 | K-AST-R01 | [LEARNING_BACKLOG B4](ep02_iter/LEARNING_BACKLOG.md) |
| 长镜头（≥10 s）用基模 24 + 只给首帧 + I2VA 正文修正，派到长镜头道 | S11 通过：mean 2.74、J4 1.01、无硬切 | K-REN-R13 | [lab_recipes 批 3](ep02_iter/lab_recipes.md) |
| 后期去抖（dejudder，bt709） | J4 1.34–1.52 → 1.08–1.09 | K-LOOP-004、K-EDT-008 | [LEARNED_SPECS §B](ep02_iter/LEARNED_SPECS.md) |
| 对白用 **H3 原声**，不用 TTS | TTS 版嘴型偏差约 2.5 s；H3 原声相关系数 0.19–0.70 | K-EDT-001 | [v0 审片 §1⑥](ep02_iter/v0_baseline_review.md) |
| 出现镜内硬切就换 seed | 新 seed 的 14 条都是 0 处硬切 | K-REV-R05 | [lab_recipes 通用](ep02_iter/lab_recipes.md) |
| comfy kitchen INT8 注意力可以保留 | S6 同 seed：mean 1.28 / 1.30，SFace 0.70 / 0.71，各项一致 | K-REN-R12 | [lab_recipes 批 4](ep02_iter/lab_recipes.md) |
| H3 提示词严格按官方格式（I2VA 指令行、三字段 / 六字段、soundscape 必写、不写否定清单） | conformance：B3 / B17 等问题 11/11 镜存在，已修 | K-PRM-001…012 | [h3_official_conformance](ep02_iter/h3_official_conformance.md) |
| 系统化：Shot Spec → 配方引擎 → 出片 Loop → 规则阶梯 → 写回 | 同样的输入编译出同样的 plan_hash；dry-run 下 ep02 11 镜整条链能走通 | K-LOOP-*、K-OPS-002 | [refactor_proposal](ep02_iter/refactor_proposal.md)、[AUTOPILOT](AUTOPILOT.md) |

## ③ 已证伪 / 无效的做法（不要再试）

| 做法 | 结果 | 规则 | 来源 |
|---|---|---|---|
| E5 multiframe（定稿首帧作 `<Picture 1>` + 脸部参考） | 构图保住了，但身份退回首帧水平：SFace 0.81 → 0.35、0.70 → 0.49；S6 又几乎不动（0.39） | K-REN-R04 | [lab_recipes 批 4](ep02_iter/lab_recipes.md) |
| 32 步替代 24 步 | S2 mean 0.67，24 步是 0.75–0.90，没有收益 | K-REN-R10 | [lab_recipes 批 2 补充](ep02_iter/lab_recipes.md) |
| Motion Repair V2 0.9 | J4 1.14 → 1.35，把 4 帧一顿带了回来，动作量没增加 | K-REN-R11 | 同上 |
| 736×1312 治顿挫（E2） | S1 J4 1.393（z 4.6），同镜 768×1344 是 1.136（只测了 1 镜） | K-REN-006 | [scores.md](../data/ab/lab/scores/scores.md) |
| 写了脸红的近景镜头用 Pika | cheek_red 0.5–0.67，是所有配方里最红的 | K-REN-013、K-REN-R06 | [lab_recipes 批 1](ep02_iter/lab_recipes.md) |
| 设定图流程叠加林晚出图 LoRA（lin_wan_qi_v1） | 身份把脸拉偏：0.926 → 0.823 | K-AST-R04 | [consistency_research R2](ep02_iter/consistency_research.md) |
| 视频身份 LoRA lin_wan_h3_v1 | 0.66–0.67，不挂 LoRA 是 0.677，没有增益 | K-AST-R07 | [LEARNING_BACKLOG B8](ep02_iter/LEARNING_BACKLOG.md) |
| antiburn 0.7 / 林晚 LoRA 0.8 压泛红 | 0.65 / 0.67，和不加一样 | K-REN-R09 | [lab_recipes 批 1](ep02_iter/lab_recipes.md) |
| 只删 Picture 2 分句来救静止镜 | S6 0.33，仍然不合格（这项修正本身是对的，但救不了静止） | K-REN-R01 | [lab_recipes 批 2 补充](ep02_iter/lab_recipes.md) |
| 只改定稿首帧、构图不动来换身份（E 方式） | 身份基本换不动，男角完全换不动 | K-AST-R02 | [LEARNING_BACKLOG B4](ep02_iter/LEARNING_BACKLOG.md) |
| skin guard 单独解决泛红 | 只压了峰值（−2.4～−8 a*），泛红面积没降（51% → 48%） | K-LOOP-003 | [v2a_review](ep02_iter/v2a_review.md) |
| 按发色归人的 SFace 当身份闸门 | S9 / S10 归错人 | K-REV-R01 | [LEARNING_BACKLOG B14](ep02_iter/LEARNING_BACKLOG.md) |
| 缓存 / 加速节点、CFGGuider / 负面词 | 会改长相、带来杂音；cfg=1 时负面词无效 | K-REN-007 | [h3_comfy_expert](ep02_iter/h3_comfy_expert.md) |

## ④ 还没验证的（按价值排序）

| 待验 | 为什么重要 / 风险 | 规则 | 来源 |
|---|---|---|---|
| **按秒时间码 `At 00:SS.mmm` 会不会被当成切镜** | 已确认写进规则，但官方 base-en 里这是“切镜”标记；应先在 1–2 镜上实测，再对新稿强制 | K-PRM-I01、K-WRT-102 | [prompt_bug_v1](ep02_iter/prompt_bug_v1.md)、[base-en](../data/ab/owner_workflows/minimax_h3_official_skills/h3-prompt-writing/references/base-en.txt) |
| 分拍写视线 / 表情 / 反应、加“下镜”后，眼神戏和切换是否改善 | v1 项目方指出的问题，需要在 v2 成片里验证 | K-WRT-I01、K-WRT-I02 | [prompt_bug_v1](ep02_iter/prompt_bug_v1.md) |
| 节奏改快（每拍至少一个完整动作，正文每秒 18–25 词）是否让成片变快 | 项目方原话“把节奏改得稍微快一点” | K-EDT-I01 | 同上 |
| realism-people 1.0 压泛红 | 1 个 seed：0.28 → 0.08，但动作量下降 | K-REN-R08 | [lab_recipes 批 3](ep02_iter/lab_recipes.md) |
| 两段式 + PDD（PLANB），速度和质量 | **耗时：两段式生成每镜 8–10 分钟；加修脸约 23 分钟（B2_S2 实测 1362 s）；基模 24 单段 158 帧约 42 分钟**（都是在三卡限 200 W 降频的条件下测的）。质量：B2 S2 cheek_red 0.09，SFace 0.33。上采样器许可还没登记 | K-REN-010 | [planB_report §1](ep02_iter/planB_report.md)、[planB scores](../data/ab/planB/ep02/scores/scores.md)、[B2_S2.log](../data/ab/planB/ep02/logs/B2_S2.log) |
| 修脸（FaceRefine）提升身份 | B2：0.331 → 0.365，只测了 1 镜 | K-REV-R09 | 同上 |
| res_multistep 对比 euler（E4）；音频三条硬规则（E10）；ref_image_size max（E12） | 官方默认 / 社区建议，都还没 A/B | K-REN-003、K-PRM-003、K-REN-R15 | [h3_comfy_expert §8](ep02_iter/h3_comfy_expert.md) |
| 男角先出正脸再出设定图；两男互相余弦 0.55 怎么拉开 | 两个男角区分不开 | K-AST-R06、K-WRT-R04 | [LEARNING_BACKLOG B3](ep02_iter/LEARNING_BACKLOG.md) |
| 用设定图数据重训林晚 LoRA（B9）；H3 角色 LoRA（B10） | 属于长任务，要先问总调度 | — | 同上 |
| 合镜（同场 2–3 镜一次生成）、best-of-k 自动挑选、按场先跑金丝雀镜 | 竞品流程，我们还没做 | K-REN-R18、K-REV-R10、K-OPS-R09 | [competitor_flows](ep02_iter/competitor_flows.md) |

## ⑤ 项目方已做的决定（摘要）

这里只摘约 30 条最关键的。完整约 95 条（原话、日期、出处，被覆盖的已标注）见 [CORE_appendix.md §A](CORE_appendix.md)。

| 主题 | 决定（原话 · 日期） | 出处 |
|---|---|---|
| 画面 | “真人效果” = 画面质感接近实拍，角色全部合成（10-29）；“高清级别，leica 镜头锐利度，电影级别的调色”（10-29）；不要字幕，大光圈、背景虚化（10-29） | [REQUIREMENTS A1–A6](REQUIREMENTS.md)、[owner_requirements §A6](owner_requirements_for_writer.md) |
| 画面 | 林晚长相以项目方给的参考图为准，写实感只加在质感上（10-30）；默认出图预设用徕卡 S★：“leica_sharp 效果最好，用他”（10-31） | [render_quality.json](../config/render_quality.json) `default_preset_note`、[CHANGELOG](CHANGELOG_AGENTS.md) |
| 人物 | 林晚身份母版定为 CM_s1：“这个最好，决定用这个”（10-30）；男角“要小鲜肉样子”（10-29） | `assets/characters/lin_wan/plates/master.provenance.json`、owner_requirements §A2 |
| 人物 | **身份参考定为“林晚A-s202 顾沉s101 陈宇s202脸”**（10-31）；顾沉、陈宇的夜间候选“全部作废，按新描述重出”（10-31） | [identity_refs/manifest.json](../data/assets/identity_refs/manifest.json)、`data/assets/asset_refs.json` |
| 视频 | “video 太差了……你采取任何方式都要搞定”，授权全权处理 → 默认改为基模 24 步 + 只给首帧（10-31） | render_quality.json `video_bases.default_decision` |
| 视频 | 撤销 ep02 五镜（S2/S4/S6/S9/S10）的自动定稿：“撤销定稿”（10-31） | CHANGELOG L377 |
| 视频 | 一镜只有一人说话（10-30）；VBVR LoRA “加，不商用，纯粹自己研究技术”（10-31） | owner_requirements §3 Q9、render_quality.json `optional_video_loras` |
| 声音 | 对白用 H3 原声：“声音好一些，男生的声音有点生硬”（10-31）；“不接受 S6 念成了‘明天还你’”（10-31） | render_quality.json `post.dialogue_source`、CHANGELOG L363/L367 |
| 声音 | “整集统一 BGM”，H3 自带的音乐压低（10-31）；TTS 语速“改成正常节奏”（10-31） | render_quality.json `post.h3_music`、[voices.json](../config/voices.json) |
| 声音 | 旁白“一定要更加年轻，语气和描写都要更好一点”；具体音色等项目方挑（10-31） | [writer_requests W6](ep02_iter/writer_requests.md)、[narrator_pick 页](../data/review_pages/narrator_pick/) |
| 节奏与剪辑 | “整个片子里的节奏很慢”，要“把节奏改得稍微快一点”（10-31）；镜与镜之间“避免跳的离谱……这是最大 bug”（10-30） | [prompt_bug_v1](ep02_iter/prompt_bug_v1.md)、owner_requirements §A7 |
| 提示词 | “按秒来计算动作”，镜间衔接、眼神和表情互动要写好（10-31） | prompt_bug_v1 L3 |
| 流程 | Claude 只写系统，不参与、也不评价内容（10-30）；只问本人闸门、花钱、删除、推翻旧决定（10-30） | REQUIREMENTS G2/G5、Claude 记忆 |
| 流程 | 资料齐全才渲染：“不具备资料的，会不要 render”（10-31）；闸门不因全自动而取消（10-31） | CHANGELOG L45、[RSI_PLAN](ep02_iter/RSI_PLAN.md) |
| 流程 | 学到的东西都变成本地系统和一对 prompt，以后新剧本不靠 Claude 驱动（10-31）；整条流水线逐段定格式、规则、校验器、闸门（10-31） | [PIPELINE_CHAIN](PIPELINE_CHAIN.md)、[AUTOPILOT](AUTOPILOT.md) |
| 流程 | 审片页在本地打开，不跳 claude.ai（10-31）；只对 ep02 迭代，目标“比 Seedance 更强大”（10-31） | Claude 记忆、RSI_PLAN L3 |
| 写作 | 写作方先是 Qwen，后改为外部 abliteration 网关（10-30 夜撤下千问） | REQUIREMENTS G8、[USER_GUIDE](USER_GUIDE_v1.md) |
| 许可 | 成人画面只用本地模型，不走闭源 API；社区权重许可未登记前不设默认 | REQUIREMENTS D2、`community_pending.yaml` |
| 视频 | 撤销夜间自动定稿：“撤销定稿 (Recommended)”（10-31）。所以 `auto_final_on_lock` 以配置里的 false 为准 | config/render_quality.json、[CHANGELOG 21:30 更正](CHANGELOG_AGENTS.md) |
| 品牌 | momoso 标识选“候选 2 · 双环”（10-31 晚） | 来源：总调度会话记录；[brand_logo 页](../data/review_pages/brand_logo/) |
| 花钱 | “Fresh 的 API 已经付费了，我再充了 50 美金进去”（10-31 下午；Fresh 就是 abliteration 写作网关） | 来源：总调度会话记录 |
| 剧本 | 10 集新剧按链条新剧 series10_v1 推进（“重新建一个剧本”）；生产库《为他而骚》ep01–10 不再算“最新 10 集” | 来源：总调度会话记录 |

**整理时发现的记录不一致，已经处理**：
- `auto_final_on_lock` 以配置 false 为准，CHANGELOG 已追加更正。
- 10-30 写作方切换的先后，以较新的 memory / CHANGELOG 为准，附录里已标注。
- momoso 和充值两条已经补上原话，来源是总调度会话记录。

## ⑥ 人物与资产现状

| 项 | 现状 | 出处 |
|---|---|---|
| 身份参考（已定） | 林晚、顾沉、陈宇各有一张脸部裁切图，Ref2VA 用。ArcFace 对设定图分别是 0.883 / 0.822 / 0.843，林晚对定妆图 0.901；两男互相 0.37–0.39，区分得开 | [identity_refs/manifest.json](../data/assets/identity_refs/manifest.json) |
| 设定图 | 林晚 A/B 各两个 seed（选 A-s202）；顾沉 T-s101 / T-s202（选 s101）；陈宇（选 s202，只用脸）。林晚 ep02 造型版候选在 outfit/ | `data/ab/char_sheets/`、[挑选页](../data/review_pages/char_sheets_pick/index.html) |
| 定妆 | 林晚有定妆图和母版 CM_s1；顾沉、陈宇没有定妆图，以设定图为准；Alex / Ryan / Kai / Leo 只有候选（⤴ 旧 60 集配角已撤：series10 演员表只有 林晚 / 顾沉 / 陈宇 / 阿岚，CLEANUP 11-01） | `assets/characters/` |
| 身份 LoRA | 只登记了林晚出图 LoRA lnwan_qi 0.8；它会把设定图流程的脸拉偏（0.926 → 0.823），设定图流程里不要叠 | [auto_lora_triggers.json](../config/auto_lora_triggers.json)、K-AST-R04 |
| 音色 | 13 个角色都有 Kokoro 音色，语速已改为正常节奏。对白默认用 H3 原声；旁白候选还没挑 | [voices.json](../config/voices.json)、[narrator_pick](../data/review_pages/narrator_pick/) |
| 场景 | 剧本场景库 3 个（都是深夜）：办公区、出租车后座、出租屋玄关。`assets/scenes/` 7 个目录，其中 4 个作废、3 个待复审。两边 id 不同（sk_office ↔ sk_office_night），对照表在 [config/scene_aliases.json](../config/scene_aliases.json)，`compile.py` 会检查一致性；ep02 场景底图没有定稿 | [CORE_appendix §B6](CORE_appendix.md) |

## ⑦ UI 现状与入口

| 入口 | 地址 | 用途 |
|---|---|---|
| 工作台（画布） | http://127.0.0.1:5173/ （:8800 也托管打包版） | 一镜一行审片模式，加精修模式 |
| 剧本创作 | http://127.0.0.1:5173/#/script-create | 新建剧本：从提纲自动写到 P4 → 送导入；`?tab=import` 是导入页 |
| 资产中心 | http://127.0.0.1:5173/#/assets | 角色、形象、衣橱、道具、场景、风格、音色、提示词模板 |
| 成片 | http://127.0.0.1:5173/#/cut | 版本、播放、对比、合成 |
| 模型与 API | http://127.0.0.1:5173/#/models | 模型和网关配置 |
| 监控看板 | http://127.0.0.1:8810 | GPU、作业 |
| 本地审片页 | [data/review_pages/latest/](../data/review_pages/latest/index.html) | 最新版本总览（本页在第一行）、ep02 各版、设定图挑选、旁白挑选、UI/UX 进展 |

顶栏步骤：S1 剧本 → S2 资产 → S3 出图 → S4 视频 → S5 成片。UI 规范在 [canvas-ui-spec-v3-merge](canvas-ui-spec-v3-merge.md) 和 [canvas-ui-fixes-v3.1](canvas-ui-fixes-v3.1.md)；UI 规则在 `knowledge/rules` 的 K-UI-*。

## ⑧ 10 集新剧本

**最新 10 集 = 链条新剧《漆皮之下·十日》**（项目方定：“重新建一个剧本”，SERIES agent 在推进），由 CHAINSPEC 的 P0→P4 自动写作完成，规则版本 `rules_v2+sysimpl-v3`：[data/pipeline/runs/series10_v1/](../data/pipeline/runs/series10_v1/)
- 每集都有 P2 大纲、P3 剧本和 P4 分镜 Markdown（`epNN/P4_epNN.md`），每镜都有 H3 提示词。
- 截至 21:00：10 集的 P3-P4 都跑满 3 轮返修，仍是 needs_writer（剩余格式问题 2–13 个）；写作累计花费约 $1.80；**还没导入生产库**。这批还在跑，数字可能会变。

生产库《为他而骚》ep01–10（[data/import/script_v2.json](../data/import/script_v2.json)）不再算“最新 10 集”，只作为 ep01–ep02 迭代的历史记录保留。

逐集清单和其他全本稿见 [CORE_appendix §D](CORE_appendix.md)。
