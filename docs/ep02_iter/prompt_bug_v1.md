# ep02 v1 提示词 bug：时间轴、眼神表情互动、镜间衔接、节奏（PROMPT，2026-10-31）

项目方原话（总调度转）：“镜头切换生硬……镜头 1 和镜头 2 之间的 transition 非常生硬，不连贯”“每个镜头里面的眼神互动、表情互动都没有描写好”“MiniMax H3 的官方说明是按秒来计算动作的，但目前提示词写得不好，时间轴也没有写好”“整个片子里的节奏很慢，画面也很慢，很不 smooth，很不真实”。

边界：PROMPT 只管提示词的**结构、时间轴格式、必填槽位、编译和校验**。剧情、谁看谁、什么表情、台词都由写作模型决定，本文不评价内容。

## 1. 学到的写法（原文出处）

| 要点 | 出处 | 原文 / 写法 | 我们怎么用 |
|---|---|---|---|
| 时间写法 | base-en §4.2 | `[Shot 2] At 00:03.500, the camera cuts to…`；第一个镜头不写时间戳 | 官方的时间格式只有 `At MM:SS.mmm,`。镜内分拍沿用这个格式，`[Shot 1]` 本身仍不写时间，全文仍只有一个 `[Shot 1]` |
| 关键帧衔接 | base-en §3.1 | I2VA：first-frame anchor → action onset → continuous development → result or reaction | 锚点句之后的第一句写“第 0 秒已经在进行中的动作”（already / still / mid-） |
| 运镜幅度、速度 | base-en §4.3 | 运镜 = 类型 + 幅度 + 速度；“medium amplitude and normal speed are usually omitted” | 默认不写速度。`at slow speed` 只在 **镜头运动** 行写了“速度=慢”时才用 |
| 说话人、对白 | base-en §4.4、ref-en §5.4 | `(S1)`；身份短语和语气写在 `<d>` 外；`<d>` 里只放原文 | 不变。台词时段起点那一拍放 `<d>` |
| 表演细节 | ref-en 开头 | “as detailed and explicit as possible… actions and state changes… Avoid reducing the description to a plot summary”；Ref2VA 正文 350–500 词 | 每拍都写视线、表情和对方反应 |
| 按秒分拍 | 项目方工作流 `Realistic AI Video MiniMax H3.json` 的 Prompt 节点 | `ACTION AND TIMING: 0–3 seconds: … 3–6 seconds: …`，另有 PERFORMANCE 段：“Natural blinking… realistic eye movement” | 采用按秒分拍，格式换成官方的 `At 00:SS.mmm,`，每 1.5–2 s 一拍 |
| 双人对白 | binwu1 drama-series-agent `dialogue-facing-bind.md` | 每句台词都要写朝向（Facing）、视线（Eyeline）、对方反应（Partner reaction），并锁定说话人（Speaker lock：“only <Subject N>'s lips open; <Subject M> listens with lips closed”） | 台词拍写说话人看着对方，同一拍或下一拍写听者反应和 `listens with lips closed` |
| 反面意见 | binwu1 `timed-motion-template.md` | “禁止再写 0-3秒 秒区间标签”，改用前段 / 中段 / 后段 | 与项目方要求冲突。按项目方要求按秒写，但用官方时间格式，不用中文秒区间标签。效果要靠 A/B 验证（见 §4） |
| 镜间衔接 | runninghub_study §7 第 4–5 条（焦点接力、Next Scene） | “上一镜结尾的动作要成为下一镜开头的画面”；Next Scene 要写“动作表情是上一镜的自然推进” | **下镜** 行（上一镜结尾仍在进行的动作）对接下一镜的开头衔接句 |
| 慢动作倾向 | h3_comfy_expert §5 | 动作慢 / 漂浮；“动词带力度”；建议去掉规则里的“偏慢” | 正文去掉 slowly / gently / gradually / at slow speed；按每秒 18–25 词写动作 |

## 2. v1 实际送出的提示词逐镜对照

数据来源：v1 成片每镜所用 take 的 `takes.json.prompt`，存档在 `data/ab/prompt_v2/ep02/old/S*.sent.txt`。指标由 `lint_timeline` 机检得出。“视线 / 表情”是正文中视线词、表情部位词出现的次数。

| 镜 | 秒 | 词数 | 分拍 | 视线 | 表情 | 偏慢词 | 主要问题 |
|---|---|---|---|---|---|---|---|
| S1 | 8.00 | 136 | 1（无时间） | 1 | 0 | at slow speed | 4 个动作挤在一段里，没有时间；没有表情变化；开头从静止起（没有衔接句）；结尾 settles。成片 S1→S2 切点 ΔE 13.2 |
| S2 | 6.58 | 142 | 1 | 2 | 2 | — | 台词没有时间点（成片 4.6 s 才开口）；男方只有“finger points”，没写他的视线和表情；听者没写 lips closed；结尾 settles + flush |
| S3 | 6.58 | 136 | 1 | 2 | 2 | — | **正文和 S2 几乎逐句相同**（“Her chest rises in a shallow breath… She swallows, her gaze locking onto his…”），三镜复用一段描述，所以表情看起来一样；男方没有任何反应 |
| S4 | 6.58 | 134 | 1 | 3 | 2 | — | 同上（S2/S3/S4 共用一段描述）；“maintains her flushed expression” = 让表情保持不变 |
| S5 | 8.00 | 117 | 1 | 2 | 0 | — | 男方只有一句画外的“retreating figure”，说话拍没有写他；“remains rigid”；8 s 只写了 2 个动作 |
| S6 | 6.58 | 139 | 1 | 3 | 2 | — | 结构又是 S2 那段描述；“maintains … focused gaze”；对方没有反应 |
| S7 | 8.00 | 129 | 1 | 2 | 1 | — | 说话人“turns his head slightly”，只有一个动作；林晚“maintains”，没变化 |
| S8 | 12.25 | 138 | 1 | 3 | 1 | slowly | 12 s 只写了约 5 个动作，平均 2.4 s 一个；最慢的一镜 |
| S9 | 6.58 | 125 | 1 | 0 | 1 | at slow speed | 没有任何视线描写；林晚“maintains her stance” |
| S10 | 6.58 | 127 | 1 | 1 | 0 | — | 没有表情；“maintains her stance”；男方没有反应 |
| S11 | 10.12 | 106 | 1 | 0 | 1 | at slow speed, gently | 10 s 只有 106 词，4 个动作 |

共性问题，对应项目方提的 4 条：
1. **时间轴缺失**：11/11 镜正文没有任何时间点。所有动作写成一段，H3 只能自己均摊，台词时间也是猜的（S2 Ref2VA 4.6 s 才开口）。规则第 5 节（第 130 行）原本写着“不写时间戳”，这是成因。
2. **眼神、表情没有逐秒变化**：S1、S5、S10 表情词为 0；S9、S11 视线词为 0。S3、S4、S6、S7、S9、S10 用了“maintains / remains”，等于告诉模型脸不要动。
3. **没有对方反应**：双人镜 S2–S7、S9、S10 共 8 镜，另一个人基本只是道具，听者也没写 lips closed（嘴型可能串到听者身上）。
4. **没有上下镜衔接**：11/11 镜开头都从静止的首帧状态起步，没有“已经在进行中”的动作；结尾都是 `settles into … Picture 2`（只给首帧时这句被系统删掉，剩下的最后一个动作也是定住）。于是每镜都是“静 → 动 → 静”，切点两边都是静止画面，看起来就是生硬的切换。
5. **动作量少、节奏慢**：正文 106–142 词，平均每秒 11–22 词，8 s 以上的镜头每秒不到 17 词；有 4 镜写了 at slow speed / slowly / gently；VOICE 短语写了 slow pace。

## 3. 系统改造（已完成，带测试）

| 改动 | 文件 |
|---|---|
| sysimpl-v2 附录：每镜必须分拍，每拍 1.5–2 s；正文用 `At 00:SS.mmm,` 分拍；每拍必写视线、表情、对方反应（双人镜）；台词拍写听者 `lips closed`；开头衔接句；结尾留进行中的动作；速度默认正常偏快，每秒 18–25 词。只加格式规则，不写剧情 | `config/script_chat_rules.md` 末尾附录（只在附录区追加，没碰第 131 行） |
| lint RL-T1–T7：时间格式（递增、在镜长内、拍长 ≤2.5 s）、视线、表情、双人反应 / 听者闭嘴、开头衔接、结尾定住、偏慢词 / 词密度。没有露脸角色的镜头（手部特写）不查视线和表情 | `services/recipes/ns_recipes/lint.py`（`lint_timeline`、`split_beats`），由 `lint_prompt` → `compile_shot` 调用 |
| 级别开关：`timing_lint_level` 默认 warn（总调度要求，不拦现有剧本）；写作规则 ≥ sysimpl-v2 并且开关为 error（或该集在 `episodes_error` 里）时才 block | `config/recipes/timing_lint.json`；`ns_schema.shot_spec.timing_lint_level / rules_at_least` |
| Shot Spec：Beat 增加 gaze / expression / reaction；SS-M1（v2 起每镜必须分拍）、SS-M4（拍长）、SS-M5（视线 / 表情）、SS-M6（双人反应）、SS-M7（下镜） | `packages/schema/ns_schema/shot_spec.py` |
| 解析器：分拍读取 `视线= / 表情= / 反应=`；只有“；”后面紧跟下一拍的时间时才断拍（ep02 S2 实测，写作模型在一拍里用“；”分隔两个人） | `services/recipes/ns_recipes/spec_import.py` |
| `rules_version()` 取最后一个附录版本（v1 + v2 → sysimpl-v2） | 同上 |
| bug：I2VA 删掉整句 “She settles into … Picture 2 …” 后会留下 “..” | `services/recipes/ns_recipes/prompt.py` `to_i2va_body` |
| 测试 | `tests/test_prompt_timeline_v2.py`（13 个，含“写作模型提示词组装带 v2”）；`tests/test_writer_rules_addendum.py` 改为断言 sysimpl-v2 |

## 4. 写作模型重写（第 3 步）

- 工具：`tools/prompt_v2/rewrite_ep02.py`。系统提示词 = `script_chat` 的组装（带 sysimpl-v2）+ 本次任务说明，任务说明只讲格式；资料来自 Shot Spec、img、motion、对白和 v1 原提示词。机检不过时，把错误原样回给写作模型，最多返修 2 轮。总调度加派的 W1 / W3 / W5 并在这一步一起做。
- 校验：`llm_output_check`（D1 / D2 台词逐字、N1 角色名、A1 锚点短语、P1 局部角色的外貌）+ `lint_timeline(strict)` + soundscape 与【H3 audio】逐字一致 + 分拍行可解析。
- 结果：**11/11 通过**。台词逐字一致；拍长 1.6–2.1 s；正文 258–334 词（v1 是 106–142）；偏慢词 0；表情词 5–12、视线词 4–10。剩下 2 条 warn：S6、S9 台词拍没写听者 lips closed。
- 输出：`data/ab/prompt_v2/ep02/`（fl2va / i2va / ref2va / beats / manifest.json / old/），不覆盖生产数据。
- 正规链路：`tools/prompt_v2/build_staging_ep02.py` 把修订字段机械合并成新稿 `data/staging_v3/为他而骚_ep02_补全候选_PROMPTv2_20261031.md`，其余行一字不动。
  - `validate_qwen_script`：blocking 29，全部是底稿原有的（PREP 底稿 42，少了 H3-X1/X3 共 13 条），没有新增。
  - 干跑：import `--merge-base` 到 scratchpad，再生成 spec 并编译 → 11 镜全部 ready，rules_version = rules_v2+sysimpl-v2；strict 模式下 SS-M 全过。
  - **导入要项目方在画布上勾选**：`/import` 要求 by=owner + confirm，PROMPT 不代点。
- 花费：写作模型 6 次调用，$0.277（`ledger.json`），预算 $10。

## 5. 实测（第 4 步）——进行中

GPU 分配已变更：gpu33 给方案 A（V2），gpu36 给方案 B（PLANB），PROMPT 不占卡。A、B 两边会在项目方导入后用同一份新提示词出 11 镜；旧提示词组用 v1 成片和 A 的旧组（`data/iterate_loop/ep02_v2/`）。对比方法：
- 量化：`tools/lab_ep02/lab_score.py data/ab/prompt_v2/ep02/scores old_S2=… new_S2=…`（运动 mean / 静止、J4、镜内硬切、脸红），以及 `tools/ep02_director/review.py`（切点 ΔE、嘴型相关、头尾定住秒数）。重点看三项：S1→S2 切点（v1 ΔE 13.2）、S2 开口时间与嘴型（v1 4.6 s 开口，0 偏移相关 0.18）、S5 动作量（v1 mean 1.31）。
- 主观：看接触印样，重点看眼神是否在两人之间往返、表情有没有逐拍变化、结尾是否还在动。
- 结论出来后补在本节，并写进 LEARNED_SPECS。

## 6. 风险 / 待验证

- 按秒分拍在官方文档里没有写，置信度低。binwu1 的社区模板反对秒区间。所以 §5 的 A/B 是这次改动能不能保留的依据。如果新组反而更碎、更抖，退路是去掉 `At` 时间，保留每拍的视线 / 表情 / 反应槽位。
- 正文从约 130 词增加到约 300 词，Ref2VA 官方建议 350–500 词，没有超出；I2VA 官方没有给长度。
- W3：写作模型在 S2 结尾仍写了 “a deeper tone spreading over her cheekbones”。泛红风险由后期限幅兜底，措辞属于内容，系统不改。
