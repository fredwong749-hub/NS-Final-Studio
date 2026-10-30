# 写作规则缺口分析（提纲 → 分集 → 镜头 → 首尾帧 → H3 → 资产 → 后期）

> 2026-10-31，Claude 只读调研（只写系统、不写不评内容）。本文只讨论**写作模型必须输出哪些字段、按什么结构和格式输出**，让下游系统拿得到它需要的东西；不涉及任何剧情或画面内容。
> 方法：逐个读源文件和官方页面。每条结论都给出出处（`文件:行` 或 URL）、不超过 15 词的原文引用，以及置信度：**官方** = MiniMax 官方原文；**实测** = 仓库代码或数据里的实际行为（读代码得出）；**推测** = 我的推断，需要 A/B 或项目方确认。
> 级别：**必须** = 缺了下游会断或只能靠关键词猜；**建议** = 能提高稳定性和一致性。
> 已读的仓库文件：config/script_chat_rules.md（下称 R）、config/script_chat_rules_appendix.md（下称 RA）、config/qwen_writer_system_prompt.txt（下称 WP）、docs/qwen_writing_contract.md（下称 QWC）、docs/SOP_production.md §4/§9A/§11/§13、docs/h3_prompt_guide_base_en.txt（下称 G，官方指南副本）、docs/research/h3_deep/00、01、packages/schema/ns_schema/{h3_lint.py,script.py,looks.py}、tools/validate_qwen_script.py（下称 VAL）、tools/validate_script_strict.py、docs/REQUIREMENTS.md、docs/canvas-ui-spec-v3-merge.md、docs/TODO_v1_close.md §6、services/agent/ns_agent/{compiler.py,state_timeline.py}、services/render_router/ns_render/{h3_video.py,frame_edit.py,refs.py}、services/api/ns_api/asset_edit.py、data/looks/*.json。
> 另一个 agent 正在做场景表和每镜“场景”行（TODO §6 S1），本文按“已计划”处理，只补充它需要对齐的细节。

## 官方来源（本次逐页读过）

| 代号 | URL | 用到的原文 |
|---|---|---|
| OG | https://github.com/MiniMax-AI/MiniMax-H3 → skills/h3-prompt-writing/references/base-en.txt（仓库副本 = docs/h3_prompt_guide_base_en.txt） | 见下文各条 |
| OS | https://raw.githubusercontent.com/MiniMax-AI/MiniMax-H3/main/skills/h3-prompt-writing/SKILL.md | “match the total duration of the description to the requested video length (4–15 seconds)”；“clearly state how the first and/or last frame connects to the timeline”；“Prefer concrete visual and audio details over abstract words like "cinematic"” |
| OR | …/h3-prompt-writing/references/ref-en.txt | §2.1 参考对象类别：“Scenes, backgrounds, or environments”、“Clothing, props, interfaces, or visual effects” |
| O3 | …/skills/3d-animation-short-generator/SKILL.md | “Scene cards must show environments only”；“Continuity landmarks (fixed objects whose screen position must persist…)”；角色卡 “age range, body type, hairstyle, outfit colors, signature props, and do-not-change traits” |
| OT | …/3d-animation-short-generator/references/shot-table-spec.md | “how this shot naturally continues from the previous shot’s ending image”；“screen-relative position (left/center/right, top/mid/bottom, foreground/midground/background)”；“no shot exceeds 15 seconds. If a beat needs more, split it”；“no more than three important characters” |
| OA | https://platform.minimax.io/docs/api-reference/video-generation-v2-create | “`MiniMax-H3`: `4`–`15`”；“maximum of 7000 characters per `text`”；“Image-to-video and reference-to-video are mutually exclusive” |
| OH | https://platform.minimax.io/docs/api-reference/video-generation-t2v（旧 Hailuo 模型） | 方括号运镜指令 “`[Push in]`”，“recommends a maximum of 3 combined commands”，提示词上限 2000 字符。**只适用于 Hailuo-02/2.3，不适用于 H3** |
| HF | docs/research/h3_deep/01_official.md 汇总的 HF 讨论 #32/#76/#86/#87/#96 | 官方：“除了需要生成的文字和对白内容 其他的都要用英文描述”（#32）；脸崩 “目前正在系统性解决”（#87）；其余为社区帖 |

---

## A. 提纲 → 分集（集级字段）

现状：集头只有 `## ep<NN>《…》`、`**剧情**`、`**配乐**`（R:28-30、QWC:47-56）；数据结构 `Episode` 只有 title/tag/synopsis/music/music_bgm/negative_extra（packages/schema/ns_schema/script.py:95-106）。**没有本集场景、出场人物、造型、时间衔接、节拍**。

| # | 缺什么 | 下游为什么需要（file:line） | 依据（引用 · 置信度） | 建议规则写法（只规定格式） | 建议机检（只查结构） | 级别 |
|---|---|---|---|---|---|---|
| A1 | **本集场景表**（已计划，TODO §6 S1） | 场景现在靠词表猜：state_timeline.py:32-63 是固定的地点和房间词表，没命中时编号为 `ep{NN}_sc{NN}`（state_timeline.py:198 `sid = f"sk_{kind}" if kind else …`），新地点永远没法归到资产；底板路径按 scene_id 找（state_timeline.py:301-302 `assets/scenes/<scene_id>`）；画布行首要显示“地点”（canvas-ui-spec-v3-merge.md:23） | O3 “Scene cards must show environments only” · 官方；01_official.md:70 引 model-selection.md “Use scene cards as the authoritative environment source” · 官方；TODO_v1_close.md:45 · 项目方原话 | `**配乐**` 之后、镜1 之前，每个场景一行：`**场景｜<scene_id>**：<名称>｜<所属（谁家/哪栋楼）>｜<时段>｜<主光源、方向、色温>｜<固定陈设 1–3 件，逗号分隔>｜<空间描述>`。scene_id 用小写拼音或英文加下划线，全剧复用；已在前面集出现过的场景只写 `**场景｜<scene_id>**：沿用`，不改内容 | ①每镜的场景 id 都在表里；②表里每个 id 至少被一镜用到；③同一 id 跨集的“名称、所属、固定陈设”逐字相同（不同就报冲突，让写作者改成新 id 或改成“沿用”）；④空间描述里不出现角色名、她/他（见 E1） | 必须 |
| A2 | **本集造型表**（人物 × 部件） | data/looks/schedule.json:42 每集都标了 “服装/鞋未设：剧本只有逐镜描述，没有整集服装定义”（needs_review=true）；编译器只能在集确认后注入造型片段（compiler.py:383-421、:478）；QWC:176 写着造型资产 “不从剧本解析”，所以写作者写的服装从来进不了资产系统；REQUIREMENTS.md:24 B4 “每集切换人物资产” 状态 ⚠ | O3 角色卡要列 “outfit colors, signature props, and do-not-change traits” · 官方；REQUIREMENTS B4 · 项目方 | 集头每个入镜角色一行：`**造型｜<角色名>**：服装=<…>｜鞋=<…>｜妆=<…>｜发=<…>｜甲=<…>｜饰品=<件数+部位>`，槽位名固定取 ns_schema/looks.py:27 的 SLOTS（outfit/shoes/makeup/hair/nails/accessory/other）对应的中文；本集中途换装写第二行 `**造型｜<角色名>｜镜<N>起**：…` | ①在镜头里出现的每个角色都有造型行；②槽位名只能从固定集合里选；③换装行的镜号存在，并且该镜的 img 备注或 motion 写了换装（R:111 已经要求写明）；④每镜 img 的服装短语与本人当前造型行的 服装/鞋 字符串逐字包含（只做字符串比对） | 必须 |
| A3 | **人物登记**（固定外貌句、H3 英文外貌短语、英文声线短语） | R:90 要求 “每个角色一条固定英文外貌短语… 同集每镜逐字相同”，RA:65 要求声线短语 “全剧逐字相同”，但两者都没有存放位置，机检也没法核对是否逐字相同；data/looks/looks.json 中 alex/ryan/kai/leo 都是 `needs_review`，备注 “造型待人工填写”；RA:25 要求配角 “第一次出场时…定一条固定外貌描述”，同样没有字段 | O3 “Identity lock repeated in the prompt” · 官方（01_official.md:68）；OG §4.4 “provide enough information… to establish a stable identity” · 官方 | 某角色在本剧第一次出场那一集，在集头写一行：`**人物｜<角色名>**：<中文固定外貌句>｜EN=<英文外貌短语>｜VOICE=<英文声线短语>`；以后各集不再重写（系统从剧本库取）。林晚的中文锁由系统前置，只写 EN 和 VOICE | ①H3 正文里该角色的锚点短语必须逐字包含已登记的 EN（新增 H3-X1）；②每个说话人第一次出现的描述必须逐字包含已登记的 VOICE（扩展 H3-D8）；③同一角色名不能登记两次 | 必须 |
| A4 | **时间衔接** | 时段和换段都靠关键词猜（state_timeline.py:60-68 TIMES / TRANSITIONS）；集首没写地点时直接接上一集最后的地点（state_timeline.py:194 `"prev_episode"`）；R:111 的换段词只在 img 备注或 motion 里，位置不固定 | OT “Continuity Handoff” 要求写明承接上一镜 · 官方 | 集头一行：`**时间**：<与上一集的关系：同一时段 / 当晚 / 次日 / 数日后 / 闪回>｜<本集起始时段：早晨/白天/黄昏/夜晚>`，取值都来自 R:111 的换段词表和 RA:112 的时段词表 | 取值必须在词表里；本集第一个场景的时段要和 `**时间**` 一致 | 建议 |
| A5 | **节拍表**（提纲事件 → 镜号） | 项目方要求模型能“生成之前缺乏的内容（比如之前没有的场景）”，但现在没有任何结构说明提纲里的哪件事落在哪几镜，新增的场景和镜头也无从核对；R:21 只允许新增亲密场次 | 推测（官方没有对应文档；O3/OT 的分镜表按“beat”拆镜：“If a beat needs more, split it” · 官方） | 集头一行：`**节拍**：B1 <提纲事件短句>→镜1–2｜B2 …→镜3｜…`；大纲之外新增的节拍以 `B+` 开头 | ①所有镜号都被某个节拍覆盖，且不重叠；②节拍编号连续 | 建议 |
| A6 | 装饰（D）状态 | 已由全局头 `decor_schedule` 维护（script.py:27-42），排期在 schedule.json `d_state` | — | 不需要新增字段；写作者不改 | — | 已有 |

---

## B. 分集 → 镜头（每镜字段）

现有每镜八个字段：img / motion / 时长 / sound（含【亲密声】【配乐】【H3 audio】）/ 对白 / 🎙 / H3提示词（R:31-40；R:53）。`Shot` 结构里没有 scene_id、入镜人物、衔接方式这些字段（script.py:64-88）。

| # | 缺什么 | 下游为什么需要 | 依据 | 建议规则写法 | 建议机检 | 级别 |
|---|---|---|---|---|---|---|
| B1 | **场景行**（已计划） | 首帧任务要带上本镜场景的定稿底图（TODO:47 S3）；场景分组目前按 img 关键词猜（state_timeline.py:92 `shot_place`） | TODO_v1_close.md:45 · 项目方；OT 锚点块要用 “exact approved scene card name” · 官方 | 放在 `**镜N｜img**` 下面一行：`**场景**：<scene_id>｜<时段>｜<本镜机位能看到的 1–2 件固定陈设>｜<本镜道具状态>` | id 在场景表里；时段在词表里；“能看到的陈设”必须是该场景固定陈设的子集（字符串包含） | 必须 |
| B2 | **入镜人物行** | 入镜判断靠猜：先匹配名字，再看“他”，再看“她”+lnwan01（compiler.py:551-566）；猜的结果决定身份 LoRA（compiler.py:462）、造型注入（:478）、时间线的人物状态（state_timeline.py:417），猜错就会漏 LoRA 或多注入造型 | OT 每个角色要写 “facing direction, and initial pose”，以及位置 · 官方；OT “no more than three important characters” · 官方 | `**人物**：<角色名>（<在画/画外声/只露手或肩>｜<屏幕位置：左/中/右，前/中/后景>）、…`，不写“她/他”；只列本镜真正入镜或发声的人 | ①角色名都已登记（A3）或有角色锁；②在画的人数 ≤3（RA:21）；③img 里出现的角色名 ⊆ 人物行；④对白里的说话人 ⊆ 人物行 | 必须 |
| B3 | **衔接行**（接上一镜还是另起） | R:111 写着 “系统会用上一镜尾帧编辑出下一镜首帧”，但同一场景里换机位、换景别、换时段时不应该接力；系统现在没有字段区分，只能看换段词 | OT Continuity Handoff 要记录 “prop position, eyeline, character posture, sound bridge” · 官方；SOP_production.md:357 “首尾帧同景别、同光、同机位族” · 实测 | `**衔接**：<接力/同场换机位/换场>｜承：<上一镜结束状态里延续下来的 1–3 项：位置、手持物、视线>`；镜1 写 `换场` 或 `接上一集` | ①取值在三选一的词表里；②写“接力”时，本镜 img 的景别与上一镜结束状态的景别相差不超过一档；③写“换场”时，场景 id 必须与上一镜不同，或者时间行有换段词 | 必须 |
| B4 | **结束状态的景别和朝向机检** | R:70 和 RA:94 规定首尾景别最多差一档、朝向不变，但 VAL 只检查 img 里有没有景别词（validate_qwen_script.py:59、:198，非严格模式只报 warn），从不检查结束状态；refs.py:121-127 按 “背影/背对/侧脸/侧面” 选身份底板的角度 | SOP_production.md:357 “落不到尾帧：…缩小首尾差距或拆镜” · 实测/社区 | 结束状态必须以景别词开头（RA:94 已有这个要求，升级为机检）；人物背对或侧对镜头时，只用 refs.py 认得的词：背影、背对、侧脸、侧面 | ①结束状态的第一个词在景别词表里；②与 img 的景别差 ≤1 档（static/pan/tilt/truck 要求差 0 档，R:94）；③img 和结束状态里的朝向词一致 | 必须 |
| B5 | **运镜：motion 和 H3 要一致** | motion 开头的英文运镜（QW-C1）和 H3 正文的运镜（H3-A10）是分别写的，没有机检核对它们一致；motion 用 `static camera`，H3 用 `static shot`，叫法不同 | OG §4.3 运镜 = 类型 + 幅度 + 速度 · 官方 | 两处用同一个运镜类型；motion 里也改写成 `static shot`（与 OG 相同） | 从 motion 解析出的运镜类型 = h3_lint.camera_moves（h3_lint.py:440）解析出的类型 | 建议 |
| B6 | **对白说话人必须写角色名** | `DialogueLine.speaker_note` 是自由文本（script.py:49）；WP:156 允许 “角色名或她/他 + 语气”，导致 TTS 和声线短语对不上人 | OG §4.4 “A speaker keeps the same ID” · 官方；SOP §11 “TTS（独白/对白，固定声线）” · 实测 | 说话人括号以角色名开头：`（<角色名>，<语气/画外标记>）“…”`；🎙 改成 `**🎙（<角色名>，<说明>）**` | 括号里第一个词是已登记的角色名；画外标记只能从 RA:73 的词表里选 | 必须 |
| B7 | **【配乐】cue 词表没有机检** | VAL 里查不到对 cue 动作词的检查（grep 进入/延续/推到高点 无结果）；schema 的注释还是旧词表（script.py:75 “推高/落下/点题”） | R:112 · 项目方规则 | 不新增规则，只把 R:112 落实成机检 | 动作词 ∈ {进入, 延续, 渐强, 推到高点, 撤到静默, 落下, 重音}；强度是 0–3；避让 ∈ 三选一；有对白时必须写“对白避让”，有 🎙 时必须写“独白避让” | 必须 |
| B8 | **镜头开头和结尾的说话位置** | H3 片头约 0.5 s 会出现乱语（00_summary.md:60，HF#76）；成片装配有 0.3 s 交叉溶解（SOP_production.md:384），会吃掉镜头首尾 | HF#76 建议写 overall_soundscape、台词以句号结尾 · 社区（低-中）；SOP:384 · 实测 | H3 正文第一句（锚点句）不放 `<d>`；最后一句（settles into…）不放 `<d>`。对白只写在中间的动作句里 | 第一句和最后一句里没有 `<d>`（新增 H3-X2） | 建议 |
| B9 | **道具清单** | R:60 规定 “饰品与道具一件一句”，但没有道具 id；资产系统只有 item/look/character 三种（asset_edit.py:90-99），槽位里也没有道具（looks.py:27） | OR §2.1 “Clothing, props, interfaces” 是一类参考对象 · 官方；OT 要求衔接时记录 “prop position” · 官方 | 场景表里加 `道具=<名称：颜色+材质+数量>`；镜头场景行写 `道具状态：<名称>@<位置>` | 镜头里引用的道具名都在场景表的道具列表里 | 建议 |
| B10 | **中间关键帧申请** | SOP:347 P-A8 写着 AddGuide “只在‘必须经过某个中间姿态’的镜头上用”，但写作者没有字段可以提出申请 | SOP_production.md:347 · 实测；00_summary.md:56 “加中间关键帧或加长片段” · 社区（低） | 可选：`**中间帧**：<秒数>｜<一句静帧描述>`（格式同结束状态） | 秒数在 (0, N) 范围内；描述长度和禁用词规则与结束状态相同 | 建议 |
| B11 | 景别、表情、时长、首帧、尾帧、【H3 audio】、触发词 | 已有：QW-C2、QW-C3、S1-W2、IMG-T1、S1-W1/IMG-L1/L2、S1-W3/QW-S1 | — | 保持不变 | 已有 | 已有 |

---

## C. 首尾帧提示词（Image 2.1 Turbo）

| # | 缺什么 | 下游为什么需要 | 依据 | 建议规则写法 | 建议机检 | 级别 |
|---|---|---|---|---|---|---|
| C1 | **img 里场景要用场景表的同一组词** | TODO:47 S3 要求编译器 “把场景描述并入首帧提示词”，并把底图作为 图N；如果 img 自己写的场景说法和场景表不一致，提示词里就会出现两套描述 | O3 “Continuity landmarks… must persist across shots” · 官方 | img 第 ⑤ 项“场景”只写场景表里的名称 + 本镜看得到的固定陈设（逐字照抄），不另外描述这个空间 | img 包含场景名称或至少一件固定陈设（字符串比对） | 必须 |
| C2 | **img 长度预算** | 首帧提示词 = 触发词 + 角色锁 + 造型片段 + img + 纠正条目 + 材质条目 + 导演加强 + 镜头词 + 风格后缀（compiler.py:485-487），img 是其中唯一可变的大头；以后接入场景描述还会更长 | 推测（没找到 Image 2.1 / qwen3vl 文本编码器的官方长度上限；需要实测） | img 建议 ≤ <X> 字（X 由一次 A/B 实测确定，在确定之前只报 warn） | 超过上限报 warn | 建议 |
| C3 | **朝向词固定** | refs.py:32-33、:121-127 只认 背影/背对/背抵/后脑 和 侧脸/侧影/侧面 这几个词，用来选背面或侧面的身份底板 | 实测 | 见 B4，朝向只用这些词 | 同 B4 | 建议 |
| C4 | 否定词 / CFG=1 | R:59 规定不写否定词，理由是 “CFG=1 时否定无效”；但编译器仍然拼了 image_negative（compiler.py:537），REQUIREMENTS.md:12 A3 写着靠 “负面词” 保证 “不要字幕”。见冲突 K12 | R:59 标注 “默认值，待项目方确认 Q6” | 写作侧保持不写否定词；系统侧需要定下 negative 到底生不生效（这是系统问题，不是写作规则） | — | 建议（需决定） |

---

## D. H3 提示词

四块结构、对齐句、帧网格、<d> 格式、亲密镜单人发声、配乐 N/A 都已有规则和 block 级机检（R:72-96；h3_lint.py H3-A1…S3）。下面是剩下的缺口。

| # | 缺什么 | 下游为什么需要 | 依据 | 建议规则写法 | 建议机检 | 级别 |
|---|---|---|---|---|---|---|
| D1 | **外貌短语和声线短语逐字复用的机检** | R:90 和 RA:65 只是文字规则，没有机检；H3 的身份全靠这句锚点短语 | O3 “Identity lock repeated in the prompt” · 官方；OG §3.1 “Character identity, clothing, colors… should remain consistent” · 官方 | 见 A3 | H3-X1：锚点句包含已登记的 EN 短语；H3-D8 扩展：包含已登记的 VOICE 短语 | 必须 |
| D2 | **“H3 做不到的事”没有集中写成规则** | 现在散在 R、RA:104-107、SOP:353-359、00_summary:60，写作者看不全 | 远景小脸崩，HF#87 “目前正在系统性解决” · 官方；首尾帧用同一张图几乎不动（HF#54） · 社区；凭空加戒指（GH#86） · 社区（低-中）；几乎不眨眼（HF#96） · 社区（低）；漂移时 “shorten the shot to ≤6s”（01_official.md:69） · 官方 | 在 R 里加一节“H3 限制 → 写法”，每条一行，只引用已有的规则编号：远景 5–6 秒且不说话（RA:106）；首尾必须有可见差异（R:70）；手上的饰品写明件数和位置（preserving 列表，R:86）；眨眼写次数（R:67）；同一场景里漂移的镜头先拆到 ≤6 秒 | 不新增机检，只汇总（已有：S1-W1、H3-A4、A11） | 建议 |
| D3 | **开场风格句与官方 skill 有分歧** | R:85 强制写 `Live-action, cinematic, shallow depth of field,` | OS “Prefer concrete… over abstract words like "cinematic"” · 官方（外部贡献者 PR，中）；OG Case 3 本身就写了 “Live-action, cinematic” · 官方 | 保持现有写法（官方示例也这样写）；不另加风格形容词。不改 | — | 记录 |
| D4 | **运镜词表与官方的差别** | R:89 只取了 OG §4.3 的一部分；OG 还有 `Shake Slightly/Strongly`、`POV`、`Roll` | OG §4.3 · 官方 | 维持子集（这是项目决定）；在 R 里写明“故意不用 Shake/POV/Roll”，免得写作者以为是漏了 | — | 记录 |
| D5 | 时长与帧数 | 写作侧已有规则（R:45-50，S1-W2/H3-A1/A11），但各处范围不一致，见 K4 | OA “`MiniMax-H3`: `4`–`15`” · 官方；OS 4–15 · 官方 | 统一成 5–15 秒的整数 | 把 schema、导入器、h3_lint 的范围统一（系统修改） | 必须（系统） |
| D6 | 长度上限 | WP:185 规定 ≤7000 字符；h3_lint 的 H3-A12 只报 warn（h3_lint.py:27、:212） | OA “maximum of 7000 characters per `text`” · 官方 | 已有 | 可以把 H3-A12 升为 block（官方硬上限） | 建议 |

---

## E. 资产（写作者要提供哪些文字，资产才生成得出来、保持得住一致）

| # | 缺什么 | 下游为什么需要 | 依据 | 建议规则写法 | 建议机检 | 级别 |
|---|---|---|---|---|---|---|
| E1 | **场景卡文字**：空间、时段变体、光线基准、固定陈设、机位 | TODO:46 S2 要生成“多机位 / 多时段变体”的底图；底图必须是空场景，因为 S3 规定只取空间，“不取人物” | O3 “Scene cards must show environments only: do not include characters” · 官方；OT 光线基准 “inherited key/fill/rim direction from the scene card” · 官方 | 场景表（A1）的空间描述只写空间、陈设、材质、光源，不写人；时段变体写成 `时段=<早晨/夜晚…>`，同一 id 可以有多个时段 | 空间描述里不出现角色名、她/他、人物词；固定陈设 1–3 件 | 必须 |
| E2 | **角色卡文字**：配角的外貌（年龄段、体型、发型、服装颜色、标志物、不可变特征） | looks.json 里 alex/ryan/kai/leo 都是 `needs_review`；SOP:151 的多角度底板需要文字描述才能生成 | O3 角色卡 “age range, body type, hairstyle, outfit colors, signature props, and do-not-change traits” · 官方 | 见 A3，`**人物｜…**` 行的中文固定外貌句按这六项的顺序写，用“｜”分隔 | 六项都有，项数固定 | 必须 |
| E3 | **单品名称对上 wardrobe** | wardrobe.json 的单品靠 keywords 和 trigger 匹配（wardrobe.json items[].keywords）；写作者自造的说法匹配不上，单品就进不了造型 | REQUIREMENTS B6 “林晚的衣服、鞋子、美甲都要用 image 模型生成” · 项目方 | 造型表（A2）里的单品：已有的照抄 wardrobe 的 `name`；新单品前面加 `新：`，按“颜色+款式+材质”写（RA:33） | `新：` 以外的单品名必须能在 wardrobe.json 里找到 | 建议 |
| E4 | 道具资产 | 资产系统没有道具类型（asset_edit.py:90-99） | OR §2.1 · 官方 | 见 B9 | — | 建议（另需系统支持） |

---

## F. 视频后期

| # | 缺什么 | 下游为什么需要 | 依据 | 建议规则写法 | 建议机检 | 级别 |
|---|---|---|---|---|---|---|
| F1 | 独白（🎙）的 TTS 声线 | 独白走后期 TTS，用的是 “林晚声线”（RA:66）；其他角色的独白没有声线 | SOP_production.md §11 “TTS（独白/对白，固定声线）” · 实测 | 见 B6，🎙 括号里写角色名；声线取 A3 登记的 VOICE | 🎙 的角色名已登记 | 建议 |
| F2 | 镜头首尾被交叉溶解吃掉 | SOP:384 “0.3s 交叉溶解” | 实测 | 见 B8 | H3-X2 | 建议 |
| F3 | 字幕 | 项目方要求不要字幕（RA:89）；H3 全文禁止双引号（H3-D4）；但 SOP:384 写了 “片尾字卡” | — | 写作侧不需要规则；片尾字卡算不算字幕要项目方确认（K10） | — | 记录 |
| F4 | 本集 BGM 与镜头配乐 | 已有：R-C1、H3-S3，并且 resolve_music 规定 “H3 已带配乐的镜头不再叠加 BGM”（SOP:376） | — | 已有 | B7 的 cue 机检 | 已有 |

---

## K. 现有规则之间的冲突，以及与 H3 官方指南的冲突

| # | 冲突 | 出处 | 建议 |
|---|---|---|---|
| K1 | 镜数和总时长：R:44 允许放宽到 “max(8, 说话轮次 + 独白段数) 镜、总时长 ≤ 90 秒”；但 VAL 按 6–8 镜、50–75 秒 block（validate_qwen_script.py:273-278），WP:138 和 QWC:53-54 也没有放宽条款 | R / VAL / WP / QWC | 机检按 R:44 改：镜数上限 = max(8, 轮次+独白)，总时长超过 75 秒只报 warn、上限 90 秒 |
| K2 | 【配乐】动作词：WP:145 写 “进入/延续/推高/落下/点题”，script.py:75 的注释同样如此；R:112 明确规定不写 “推高或点题” | WP / schema / R | WP 改成 R:112 的词表 |
| K3 | 负面追加：QWC 第 1 节模板里有 `**负面追加**：<可选>`，R:59 规定 “不写 `**负面追加**`” | QWC / R | 从 QWC 模板里删掉 |
| K4 | 时长范围不一致：schema 默认 10、允许 3–15（script.py:84）；VAL 的报错信息写 “3–15”，实际判定 5–15（validate_qwen_script.py:179-181）；h3_lint 允许 4–15.1（h3_lint.py:209）；R、SOP 写 5–15；官方是 4–15（OA，Max 版是 5–15）；h3_video 缺时长时按 10 秒（h3_video.py:161） | 多处 | 统一为 5–15 整数；缺时长时报错，不再默认 10 |
| K5 | 林晚发色：REQUIREMENTS.md:21 B1 写 “浅冰蓝及腰直发”；R:107 规定写 “雾霾天蓝色…”，并且不写浅冰蓝 | REQ / R | 需要项目方定一个（Q16 待确认） |
| K6 | 说话人数：R:94 规定普通对话镜每镜最多一个说话人（block，h3_lint.py:300）；RA:26 和 RA:69 还写着 “一镜最多两位说话人”，“>1 人只报 warn” | R / RA | RA:26、RA:69 改成与 R:94 一致 |
| K7 | 说话人写法：WP:156 允许写 “她/他 + 语气”；R:57 规定人物写角色名，不写她/他 | WP / R | 统一写角色名（B6） |
| K8 | 表情条数：WP:154 写 “至少一个”；R:67 写 “1–2 个，首选 1 个” | WP / R | WP 跟 R |
| K9 | 写作模型：TODO_v1_close.md:7 说默认模型是 abliteration，千问 “撤下”；REQUIREMENTS.md:84 G8 和记忆里的分工都写 “还是用qwen写” | TODO / REQ | 以项目方最新原话为准，统一 |
| K10 | 画面文字：OG §4.5 规定画面上的文字放在英文双引号里；我们的 H3-D4 禁止一切双引号（R:88，理由是会被烧成字幕）。属于有意偏离；另外 SOP:384 有 “片尾字卡” | OG / R / SOP | 保留偏离，在 R 里注明“有意偏离官方”；片尾字卡请项目方确认 |
| K11 | 换段词：state_timeline.py:68 把 “转场” 当换段词；R:66 规定不写 “转场”，R:111 的换段词表里也没有它 | 代码 / R | 系统侧去掉 “转场”，或者 R 加上（建议系统侧去掉） |
| K12 | 负面提示词：R:59 说 CFG=1 时否定无效；编译器仍然拼 image_negative（compiler.py:537）和 video_negative；H3 官方说 “no `negative_prompt`”（01_official.md:179） · 官方 | R / 代码 / 官方 | H3 的 negative 确定无效；Image 2.1 Turbo 在 CFG=1 下是否生效需要实测；REQUIREMENTS A3 依赖负面词去字幕的说法要复核 |
| K13 | 造型来源：QWC:176 写造型资产 “不从剧本解析”；TODO §6、REQUIREMENTS B4 要求写作者给出场景和造型 | QWC / TODO | 按 A1、A2 新增字段后改 QWC 第 3 节 |
| K14 | 运镜写法：motion 用 `camera push in`、`static camera`（R:65），H3 用 `Static Shot`（OG §4.3）；方括号 `[Push in]` 只是旧 Hailuo-02/2.3 的语法（OH），H3 不用 | R / OG / OH | motion 的英文运镜只给画布显示用，词形与 H3 统一（B5） |
| K15 | 官方 skill 说避免 “cinematic” 这类抽象词（OS），我们的开场强制写 “cinematic”（R:85） | OS / R | 官方示例 Case 3 也写了，保留；记录在案 |

## 建议的落地顺序（系统侧，供总调度排期）
1. 先做必须项里的格式：A1 场景表 + B1 场景行（已在做）→ A3 人物登记 → A2 造型表 → B2 人物行 → B3 衔接行。
2. 再补机检：B4（结束状态的景别和朝向）、B7（cue 词表）、D1（H3-X1 / D8 逐字核对）、K1/K4 的范围统一。
3. 每新增一个字段，同步改 R、WP、QWC 的模板，导入器加解析，Shot/Episode 加字段。按 R:43，未知标签会被当作附加字段（extras），所以必须先改导入器，再让写作者开始写新字段。
