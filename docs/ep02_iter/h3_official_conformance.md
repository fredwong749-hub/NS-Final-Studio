# H3 提示词：官方规范对照（CHAIN，2026-10-31）

官方来源：项目方给的 `github.com/MiniMax-AI/MiniMax-H3/tree/main/skills`（提交 199b7d0e），本地副本在 `data/ab/owner_workflows/minimax_h3_official_skills/`。其中 `h3-prompt-writing/references/base-en.txt` 和我们仓库里的 `docs/h3_prompt_guide_base_en.txt` 逐字相同（diff 为空）。`ref-en.txt` 是 Ref2VA（全参考模式）指南，我们仓库里之前没有。

我们这边对照了：编译 `services/agent/ns_agent/h3_prompt.py`、`compiler.py`；提交 `services/render_router/ns_render/h3_video.py`（`realign` / `align_first_only`）；校验 `packages/schema/ns_schema/h3_lint.py`（项目的 H3 规则 H3-A*/D*/S*/X*）。仓库里没有 `config/h3_ir.json`。实验脚本：`tools/lab_ep02/ref2va_prompt.py`、`ref2va_run.py`。

ep02 证据：
- 11 镜 `data/renders/ep02/S*/compiled.json` 的 `video_prompt`（FL2VA，等于剧本 H3 原文）；
- 各镜最新视频版本 `takes.json` 的 prompt（I2VA，`last_frame_mode=none`）。
- 我用项目自己的 `lint_h3` 跑了一遍：FL2VA 11/11 全部通过；I2VA 11/11 只报 H3-A1（“第一行必须是 FL2VA 对齐句”），也就是**把官方 I2VA 句判成了错**，而真正的问题它没报出来。

判定：✗ 不符合、△ 部分符合、✓ 符合、⊘ 本地有意偏离（不和官方冲突，或者是加严）、N/A 不适用。

## 1. base-en（T2VA / I2VA / FL2VA / L2VA）

| # | 官方条文（base-en） | 我们的实现 | ep02 证据 | 判定 | 影响 / 修法 |
|---|---|---|---|---|---|
| B1 | §2.1 FL2VA 第一行逐字：`How the reference pictures align … Picture 2 (from Shot N) aligns with the S.SS-second mark …`，S.SS 为有效时长，两位小数 | `h3_lint.alignment_line(frames)`，S.SS = 帧数/24；提交时 `realign()` 按实际帧数换秒数 | 11 镜都对，例如 S2 158 帧 → 6.58，S8 294 帧 → 12.25 | ✓ | “有效时长”按帧数/24 计算，最后一帧时间戳是 (帧数−1)/24（S2 为 6.54）。官方没说清楚，目前保持现状，记作待验证 |
| B2 | §2.1 I2VA 第一行逐字：`For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.` | `h3_video.I2V_ALIGN_LINE` | 11 镜最新版本都对 | ✓ | — |
| B3 | §3.1 / Case 2：I2VA 正文先用 `<Picture 1>` 锚定首帧（主体、构图、场景，“preserving her appearance, clothing…”），再**向前发展**；全文不再有第二张图 | `align_first_only()` **只换第一行**，注释写“正文原样不动” | 11 镜 I2VA 正文仍以 `…begins in the position, framing and lighting established by Picture 1`（FL2VA 写法，Picture 1 不带尖括号）开头，以 `settles into the pose, spacing, and composition established by Picture 2 at the end of the shot` 结尾，引用了一张没有送进去的图 | ✗ | 模型拿到互相矛盾的指令。修法：编译器出两套正文模板（FL2VA / I2VA），I2VA 删掉 Picture 2 收尾句，开头改成官方 `the … shown in <Picture 1> remains …, preserving …`，见 §4 F1 |
| B4 | §2.1 末：指令行之后空一行，再接三个字段 | `assemble()`；剧本原文 | 11/11（lint H3-A2 通过） | ✓ | — |
| B5 | §2.2 / §4.6 / §4.7 三个字段：integrated_multimodal_description / overall_soundscape / non_diegetic_music | 同上 | 11/11 | ✓ | — |
| B6 | §4.1 `[Shot 1]` 开头写整体风格（`Live-action, cinematic`），关键帧任务的风格从参考图推出 | lint H3-A8 强制 `Live-action, cinematic, shallow depth of field,` | 11/11 | ✓（⊘ 多了 shallow depth of field，属于本地风格） | — |
| B7 | §4.2 第一个镜头不写时间戳；切镜才用 `[Shot 2] At 00:03.500` | 单镜头，lint H3-A3 | 11/11 | ✓ | — |
| B8 | §3.2 / Case 3：FL2VA 正文“不应重复两张静态图的描述，而是给出连接两者的**运动路径**” | 剧本原样；编译和 lint 都不检查 | S3/S4/S6/S7/S10 的正文主要是状态描写（`She maintains her flushed expression and focused gaze, and settles into…`），几乎没有路径；再加上首尾帧差只有 4–7，这 5 镜都是静止镜头 | △ | 这是内容问题，交给写作方；系统可以加一条提示：正文动作动词少于 N 个、或者“maintain/remain”占主体时提醒 |
| B9 | §4.3 运镜 = 类型 + 幅度 + 速度，用自然英文写在镜头里（Push In / Pull Out / Truck / Static Shot / Tracking Shot…） | 剧本原样；lint 不检查运镜词表 | S1 `The camera pulls out at slow speed` ✓；S11 `pushes in at slow speed` ✓；S10 `holds a static shot` ✓；S9 `trucks right at slow speed`，但剧本原文是“镜头缓慢推向厨房方向”（应为 push in）✗；`visual_spec.camera_move` 没识别 S9 的 `tracking shot` | △ | 剧本中文运镜 → 官方词表的映射要确定性完成（编译器维护对照表），S9 这类不一致应提示 |
| B10 | §4.4 说话人用稳定 ID `(S1)`；首次出现时给出角色类型、年龄、性别、是否在画、音高、音色、语速、**口音**；说明写在 `<d>` 外 | 剧本原样；构建器 `dialogue_sentences()` | 女声：`…young woman in her twenties with a sweet, breathy, mid-high Mandarin voice…` ✓；男声：`The on-screen adult man in his mid-thirties with a low, calm, unhurried voice…` **没有语种 / 口音**，人物描述也没有族裔 | △ | 男声可能不是普通话口音，族裔也会漂移（审计 A1/B1）。修法：VOICE 短语从人物表取，必须含 `Mandarin`；锚点句含 EN 外貌短语 |
| B11 | §4.4 `<d>` 里**只放语言标签和原话**，逐字、带原标点 | lint H3-D1 / D3 | 11/11 逐字一致（含“——”“……”） | ✓ | 剧本层面符合。但我的写作模型重放显示，LLM 会把“顾沉，声音低沉克制：”写进 `<d>`（审计 B4）。以后 LLM 生成正文时，D1/D3 必须作为硬闸门 |
| B12 | §4.4 构建器（剧本没写 H3 时的兜底） | `dialogue_sentences()`：`lead = 剧本括号原文`，例如 `她慌 (S1) says: <d>…</d>` | ep02 没走这条路（全部 `source=script`） | ✗（代码路径） | `<d>` 外出现中文舞台提示（违反 §4.4 “说明写在 `<d>` 外且为英文”；lint H3-A7 会拦下，所以这条兜底路径实际产出的都是不合格提示词）。修法：兜底时说话人短语从人物表 VOICE 取，舞台提示不进 H3 |
| B13 | §4.4 画外音：`says in an off-screen voiceover`，每个画外 `<d>` 后**紧接**“…lips remain completely closed” | 内心独白 🎙 一律不进 H3（lint H3-D6，后期 TTS）；画外台词用 `VO_PHRASE` + 常量 `The on-screen character's lips remain closed.` 单独成句 | S8（独白 25.6 s）、S11 的 H3 正文里没有任何 lips closed 描述 | ⊘ / △ | 不放独白进 H3 是本地设计。但官方明确给了画外音写法，而且能让 H3 自己出独白声、保持嘴型闭合，一镜一声，正好对应审计 D2（独白盖镜）和“男声生硬”的问题。建议：①至少在纯独白镜正文里加 `her lips remain closed`；②做对照：把独白按官方写法放进 H3。常量写法改成官方句式 `while her lips remain completely closed`，紧跟在 `</d>` 后 |
| B14 | §4.4 跨切镜的台词用 `<scenetrans>`，被视频结尾截断用 `<cutoff>` | 未实现 | 单镜头，ep02 没有用到 | N/A | 以后多镜头（`[Shot 2]`）时要补 |
| B15 | §4.5 画面里**真实可见**的文字（招牌、字幕、霓虹）用英文双引号括起来，原文逐字 | lint **H3-D4 禁止一切双引号**（理由：“会被烧成字幕”） | ep02 没有可见文字；但 S5 成片里冒出了“冷”字（审计 C6） | ✗（规则冲突） | 剧本真有屏幕文字、招牌的镜头会被 lint 拦下，或者被迫删掉。修法：D4 改成“`<d>` 里的台词不加引号；可见文字按官方格式用引号”，并在 Shot Spec 里显式列出 `on_screen_text` |
| B16 | §4.6 soundscape 1–4 句英文，不重复台词；只有全片静音才写 N/A | lint H3-S1 / S2（S2 禁止 N/A，比官方严） | 11/11 通过 | ✓ / ⊘ | — |
| B17 | §4.7 配乐写乐器、速度、节奏、强弱变化；**不写抽象情绪词，不解释配乐的作用** | `resolve_music()`：剧本 H3 自带的配乐**原样采用、不过 H3-S3**；只有回退到本集 BGM 时才查情绪词 | 10/11 镜都是 `…, providing a restrained / rising / sustained background layer.`（在解释作用）；lint H3-S3 也放过了（MOOD_EN_RE 没有 restrained、background layer 这类模式） | ✗（轻） | 修法：剧本自带的配乐也走 H3-S3；MOOD_EN_RE 加入 `providing … layer`、`restrained`、`atmosphere` 等“作用 / 情绪”模式。另外 11 镜各写一段配乐，切镜就会跳变（审计 D5），官方 3D 短片管线也规定“不要逐镜生成 BGM”（见 refactor_proposal §7） |
| B18 | §3.1 I2VA：人物身份、服装、颜色、关键物体、空间关系要保持一致 | H3 正文只来自剧本 | 顾沉在 H3 里只有 `a man in a black tailored shirt`，没有族裔、发型；陈宇只有 `a young man` | △ | 和 B10 一起修：锚点句由人物表 EN 短语确定性生成 |
| B19 | 字符上限（官方 API 每段文本 7000 字符） | lint H3-A12 | 最长约 1400 字符 | ✓ | — |
| B20 | 官方格式**没有负面词字段** | `compiled.video_negative` 照样生成，提交时 `negative=""`（cfg=1） | 11/11 | △ | 死字段，会误导人；删掉，或标成“不生效” |
| B21 | 本地加严规则：H3-X2（首尾句不放台词）、H3-D7（普通镜头每镜一人发声）、H3-A5（禁止否定词）、H3-A11（4–15 s） | lint | 11/11 通过 | ⊘ | 官方没有这些规则，但也不冲突，可以保留。H3-A5 和官方 Case 4 `ending immediately after…` 这类写法不冲突 |
| B22 | **我们的 lint 本身只认 FL2VA**：H3-A1 用 ALIGN_RE 只匹配 FL2VA 句；H3-A4 要求最后一句必须是 `…established by Picture 2 at the end of the shot` | `h3_lint.py:29、:166–174` | I2VA 11/11 被 A1 误报；A4 反而**强制**写上不存在的 Picture 2 | ✗ | 修法：lint 按模式分支（T2VA / I2VA / FL2VA / L2VA），各自校验官方指令行和收尾要求；I2VA 禁止出现 `Picture 2` |

## 2. ref-en（Ref2VA，全参考模式）

现状：生产里**完全没有用 Ref2VA**，H3 只用 `MiniMaxH3ImageToVideo`（FL2VA / I2VA）。今天另一路实验 `tools/lab_ep02/ref2va_run.py` 已经接上了 `MiniMaxH3ReferenceToVideo` 节点，但配套的 `ref2va_prompt.py` 用的提示词格式不是官方格式。

| # | 官方条文（ref-en） | 我们（lab 的 ref2va_prompt.py） | 判定 | 说明 / 修法 |
|---|---|---|---|---|
| R1 | §1 六个段，按顺序：`subject_definitions` / `summary` / `retention_analysis` / `detailed_description` / `overall_soundscape` / `non_diegetic_music`，全部英文 | 自定义段：`SCENE / ACTION AND TIMING / CAMERA / SOUND / STYLE / CONSTRAINTS` | ✗ | 换成官方六段 |
| R2 | §2 标签：`<Subject N>` 是可复用的可见内容（人、场景、服装）；`<Picture N>` 只在作为具体帧（首帧、关键帧、尾帧）时单独成条；只用来定义人物的图，写在 Subject 定义里 | 没有标签，只有一句自由文本 `refs_note`；还用正则删掉所有 `Picture N` | ✗ | 林晚、顾沉、陈宇各自是一个 `<Subject N>`，定义里引用各自的身份参考图；场景底图是另一个 Subject。这正是官方解决多人身份一致的办法（对应审计 A1 / C1） |
| R3 | §2.4 `<Audio N>` 可以作为说话人音色参考：`<Audio 1> is the voice-timbre reference for <Subject 2> (S1).` | lab 有 `--audio` 参数，但提示词里不标 `<Audio N>` | ✗ | 顾沉声音生硬（QC §6 VOX）可以走官方音色参考，不用后期变声 |
| R4 | §3 `summary` 用方括号写任务类型，例如 `[reference generation]`，有首帧时是 `[keyframe completion + reference generation]` | 没有 | ✗ | — |
| R5 | §4 `retention_analysis`：每个标签一行，写 `fully_preserved / partially_preserved / attribute_transfer / weak_reference`，音频写 `fully_copy / partially_copy / reference / weak_reference` | 没有 | ✗ | 身份写 `fully_preserved`，场景按需要选 |
| R6 | §1 / §5 正文和段名全部英文；只有 `<d>` 里的台词和画面里的文字保留原语言 | `SCENE:` 段直接放 `compiled.image_body`（**中文**） | ✗ | 中文场景描述要先转成英文（由写作模型受约束完成并校验，或从场景表 EN 字段取） |
| R7 | §5.2 风格句写在 `[Shot 1]` **之前**，一到两句 | `STYLE:` 段放在最后 | ✗ | — |
| R8 | §5.2 生成任务的 `detailed_description` 一般 350–500 个英文词 | 只有 H3 正文去掉 Picture 子句后的一段（约 100–150 词） | △ | 官方要求“尽可能详细”：构图、主体外貌与位置、环境光线、动作和状态变化、运镜、声音，以及参考内容在哪里生效 |
| R9 | §5.4 引用的主体说话时写 `<Subject N> (Sx)`；`(Sx)` 按目标视频里实际发声的顺序全局分配 | 没有 | ✗ | — |
| R10 | §5.4 引用参考音频里的台词时，标点统一成 `, . ? !` | N/A（我们的台词来自剧本，不是参考音频） | N/A | 剧本台词仍按 base-en 逐字 |

结论：如果要走 Ref2VA（官方解决“多人身份 + 音色”的路径），提示词必须由编译器按六段格式确定性生成：Subject 由 Shot Spec 的在画角色和场景得出，Picture 只放真正的首帧。现在 lab 的格式拿不到官方训练时的格式红利，实验结论（好或坏）都不能代表 Ref2VA 的真实能力。

## 3. 汇总

- **立刻要修（会直接进生成）**：B3 I2VA 正文还写着 Picture 2（11/11）；B22 lint 只认 FL2VA，并且强制 Picture 2 收尾；B15 lint 禁止引号，和官方可见文字写法冲突；B17 剧本自带配乐不过 H3-S3；B12 兜底构建器把中文舞台提示放进正文；B13 画外音的 lips closed 句式不对、位置不对。
- **要靠资料补全**：B10 / B18 男角色的族裔、口音和外貌锚点（依赖人物表，审计 A1）。
- **内容问题，交写作方**：B8 FL2VA 正文缺运动路径、B9 S9 运镜不一致。系统只做提示，不改内容。
- **结构性缺口**：Ref2VA 完全没有按官方格式接入（R1–R9），建议进重构 P2 / P4（见 `refactor_proposal.md` §7）。
- 可以马上修的清单已发给 FIX 会话，并入它的 P0（见 §4）。

## 4. 发给 FIX 的可立即修复清单（P0 增补）

| ID | 位置 | 改法 | 验收 |
|---|---|---|---|
| F1 | `ns_render/h3_video.py: align_first_only` | 除了换第一行，正文也要改成 I2VA：删掉 `, and settles into the pose, spacing, and composition established by Picture 2 at the end of the shot` 子句（以及其他含 `Picture 2` 的子句）；把 `established by Picture 1` 改成 `established by <Picture 1>`。更彻底的做法是由编译器产出 I2VA 正文，提交时不再做字符串替换 | 对 ep02 11 镜最新 I2VA prompt 重新生成后，不含 `Picture 2`；新增单测 |
| F2 | `ns_schema/h3_lint.py` H3-A1 / A4 | 按模式分支：识别 I2VA 指令行（逐字）；I2VA 时 A4 改成“第一句锚定 `<Picture 1>`，全文不得出现 `Picture 2`”；FL2VA 维持现状；T2VA 不要指令行 | ep02 I2VA 11/11 通过；人为插入 Picture 2 时报 block |
| F3 | 提交路径 | `video_jobs` / `h3_video.render` 提交前，按实际模式跑 `lint_h3`，block 级就拒绝提交（现在只有剧本导入时跑） | 有 block 的提交返回 409 和中文原因 |
| F4 | `h3_lint.py` H3-D4 | 只检查 `<d>` 内外的台词引号；`<d>` 外、用来表示画面可见文字的英文双引号放行（官方 §4.5） | 可见文字示例 `A red neon sign reading "营业中" glows…` 不报错 |
| F5 | `ns_agent/h3_prompt.resolve_music` + `h3_lint.MOOD_EN_RE` | 剧本自带的配乐也要过 H3-S3；MOOD_EN_RE 增加 `providing … layer`、`restrained`、`atmosphere`、`background layer` 等“作用 / 情绪”模式（只报 warn，不改剧本文字） | ep02 10 镜报 warn |
| F6 | `ns_agent/h3_prompt.dialogue_sentences` | 兜底构建器不再把中文舞台提示（剧本括号原文）放进 `<d>` 外；说话人短语用人物表 VOICE 英文，查不到就留 `(Sx) says:` 并让 lint 报缺 VOICE | 构建器产出的提示词过 H3-A7 |
| F7 | `h3_prompt.LIPS_CLOSED` | 改成官方句式，紧跟 `</d>`：`… <d>[Chinese] …</d> while her/his lips remain completely closed.`（按说话人性别）；纯独白镜（S8、S11 这类）在正文加一句 `her lips remain closed`（这一条要不要上线，需项目方确认，因为会改变剧本正文） | 单测 |
| F8 | `compiler.py` | cfg=1 时 `video_negative` 设为空并标注 `ignored_cfg1`，不再展示成好像生效 | compiled.json 字段为空 |
