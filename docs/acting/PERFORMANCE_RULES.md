# 表演 / 视线 / 节奏规则（ACTING，2026-11-01；R11-2 / R11-3 / R11-6 / R11-8 / R11-9）

项目方原话：
- R11-2 “演员的眼睛不要看镜头……参看 cinecrew(github) 的一些提示词和演员拍戏的规则……剧情镜头还是很慢”
- R11-6 “一个演员要完成剧本故事要做什么……演员的眼神，表情，语气等应该怎么做才合理有画面感”
- R11-8 “每个镜头第一帧，演员都看着镜头，而且停顿 1 秒多……写入规则去掉”；“字幕不是要求不加么?”
- R11-9 “当画面出现超过一个人……他们面部表情，眼神是没有……按照 minimax h3 的镜头提示词写”

本文只收规则与出处，不写剧本内容。剧本由写作模型按 `config/recipes/writer_knowledge.md`（由 `knowledge/rules/writer_iteration.yaml` 编译）改写。
原始抓取件（调研子 agent 用 curl 拉下来的原文）放在会话临时目录，没有进仓库；引文都可以按下面的链接复查。

## 0. 调研结论（先看）

| 结论 | 置信度 |
|---|---|
| 读得到的来源里（CineCrew、MiniMax-H3 全部 skills），没有一条明文写“不许看镜头”。两家都用同一个办法：**每个角色都写出具体的视线落点**（看谁、看什么）。写了落点，模型就不会默认对镜头。 | 高 |
| H3 里唯一出现“looking at camera”的地方是游戏菜单角色的定格摆拍（co-op-game-intro-generator），属于有意设计。电影常规里，直视镜头 = 打破第四面墙，是刻意的手法，不是默认状态。 | 高 |
| H3 不认否定句（官方：否定会把概念写进去；本仓库已有 `prompt.no_negative` + RL-N1）。所以“不看镜头”在 H3 正文里只能写成**正向落点**，不能写“not looking at the camera”。出图走 Qwen Image，cfg 1，负面分支不参与采样（`ns_render.workflows.negative_for`），同样只能写正向句。 | 高 |
| H3 的时间写法是镜内时间码 `At 00:02.000,`（I2VA 镜内分拍，本仓库已在用），不是 `[0-2s]`。逐秒 `0–1s` 只出现在 3D 动画分镜表规范里。 | 高 |

## 1. 规则表

每条规则都对应落地位置：W = 写作规则（writer_text + QW lint），S = 系统层（编译器固定句），D = 检测器。

### 视线（eyeline）

| # | 规则 | 出处 | 原文 | 落地 |
|---|---|---|---|---|
| E1 | 每一拍都写出视线落点：画内的人（写名字或部位）或物件，或画外有名有姓的声源 / 方向。不写空的“看着前方” | CineCrew technical_director.yaml https://github.com/Ironieser/CineCrew/blob/main/src/agents/technical_director/technical_director.yaml | “t2i_template MUST describe: - Who looks at whom (eyelines)” | W：QW-W5 / K-WRT-Q06 |
| E2 | 视线落点写具体方向或物件 | CineCrew cinematographer.yaml https://github.com/Ironieser/CineCrew/blob/main/src/agents/cinematographer/cinematographer.yaml | “action_state: … e.g. "gesturing_forward", "leaning_back", "looking_offscreen_left"” | W：QW-W5 |
| E3 | 视线变化当动作写：从 A 移到 B | MiniMax-H3 base-en https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt | “she lifts her gaze from the folded letter toward the passing city lights” | W：QW-W5；S：H3 视线句 |
| E4 | 不写“看向镜头 / 直视镜头 / 看着观众”。直视镜头是打破第四面墙的手法，要用得有理由，不能当默认 | Wikipedia Fourth wall https://en.wikipedia.org/wiki/Fourth_wall | Jerry Lewis：“usually I have my actors, in a single, look direct into the camera at least once in a film, if a point is to be served.” | W：QW-W6 / K-WRT-Q07；D：G1 |
| E5 | 视线对着对手方（对手在画外时也一样）。观众想看角色看到的东西 | Wikipedia Eyeline match https://en.wikipedia.org/wiki/Eyeline_match | “placing the other actors off camera but sometimes by giving the on-camera actor a mark to look at”；“an audience will want to see what the character on-screen is seeing” | W：QW-W5；S |
| E6 | 近景视线贴近镜头一侧，但绝不正对镜头（⤴ D-SCR-07 统一口径：对生成模型不写“贴近镜头 / 镜头一侧”，一律写成画外具体的人或物，见 §3 A-01/A-02） | StageMilk https://www.stagemilk.com/a-guide-to-eyelines/（页面 403，引文取自搜索摘要，**置信度中**） | “keep the eyeline as close to camera as you possibly can. BUT never look straight down the lens!” | S：出图 / H3 视线句 |
| E7 | 跨镜视线方向保持连续，翻转要写明 | MiniMax-H3 shot-table-spec https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/3d-animation-short-generator/references/shot-table-spec.md | “Any shot that flips eyeline, character position, prop state, or lighting must mark the flip explicitly” | W：writer_text（Q06 附注） |
| E8 | 每句台词都配具体的视线和身体变化，不能定住盯着 | 同上 shot-table-spec | “describe concrete eye-line and body-action changes for each dialogue line.” | W：QW-W5 |

### 多人镜头（R11-9）

| # | 规则 | 出处 | 原文 | 落地 |
|---|---|---|---|---|
| M1 | 画里每个人都写动作、表情、视线，以及对别人的反应 | CineCrew technical_director.yaml（同上链接） | “Each visible character's action and reaction to others”；“i2v_template MUST describe: - How they react to each other's micro-movements” | W：QW-W9 / K-WRT-Q10；S：RL-E1 |
| M2 | H3 多人写法：每人各自一句，主语是这个人，后面跟视线、表情、动作；说话人带 (Sx) ID | MiniMax-H3 ref-en https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/ref-en.txt | “Her annoyance softens as she looks toward the Samoyed. <Subject 3> (S1) replies …”；“He closes his mouth into an apologetic smile and strokes the dog's thick white fur.” | W：writer_text；S：RL-E1（H3 正文视线短语数 ≥ 露脸人数） |
| M3 | 一镜里重要角色不超过 3 个 | 同上 shot-table-spec | “no shot contains more than three important characters” | 已有 RL-D7（max_speakers） |

### 表情 / 语气（R11-6）

| # | 规则 | 出处 | 原文 | 落地 |
|---|---|---|---|---|
| X1 | 表情写成具体、可看见的复合标签或面部微动作，不写“很激动 / 很戏剧”这类空词 | CineCrew emotion_inference.yaml https://github.com/Ironieser/CineCrew/blob/main/src/agents/vo_director/emotion_inference.yaml；story_editor.yaml https://github.com/Ironieser/CineCrew/blob/main/src/agents/story_editor/story_editor.yaml | “Use descriptive cinematic labels (e.g., 'restrained rage', 'melancholic hope', 'cold determination').”；“avoid vague terms like "dramatic" or "intense".” | W：QW-W8 / K-WRT-Q09 |
| X2 | 情绪在相邻拍之间连续变化，不跳 | CineCrew dialogue_emotion.md https://github.com/Ironieser/CineCrew/blob/main/configs/knowledge/rules/agents/dialogue_emotion.md | “Continuity: consider the previous 3 beats; changes must be logical (grief → desperation → anger), never abrupt.” | W：writer_text |
| X3 | 近景的情绪靠眼睑和面部小肌肉，不靠瞪眼 | Backstage https://www.backstage.com/magazine/article/4-ways-to-act-with-your-eyes-in-a-close-up-65653/ | “with just the smallest amount of tension, the lifting or relaxing of your eyelids can speak volumes to the viewer.” | W：writer_text |
| X4 | 导演给可演的动词，不给结果形容词 | Judith Weston 访谈 https://filmcourage.com/?p=181776（书原文没读到，**置信度中**） | “Result direction is directing the actor by telling them how you want, what effect you want them to have on the audience.” | W：writer_text（动作栏写动词） |
| X5 | 注意力放在对手身上，做反应 | Wikipedia Meisner technique https://en.wikipedia.org/wiki/Meisner_technique | “instead concentrate on the other actors in the scene” | W：QW-W9（反应） |
| X6 | 语气（音高、音色、语速、腔调）写在 `<d>` 外 | MiniMax-H3 base-en（同上） | “Place the speaker's identifying phrase, ID, action, and delivery outside `<d>`.” | 已有（H3-D 规则）；writer_text 提醒 |
| X7 | 口型：在画说话人张嘴，其他人闭嘴 | CineCrew technical_director.yaml；H3 base-en | “"Mouth remains tightly closed. No speaking."”；“state that the corresponding on-screen character's lips remain closed” | 已有 K-WRT-Q04 / QW-W3 |

### 开头与节奏（R11-2 第二点、R11-8）

| # | 规则 | 出处 | 原文 | 落地 |
|---|---|---|---|---|
| P1 | 首帧画的是动作发生前的一刹那；视频从第 0 帧起就在做动作 | CineCrew technical_director.yaml | “Describe the scene at the SPLIT SECOND BEFORE the main action occurs.”；“✅ GOOD (setup state): "The glass is tilting off the table edge, liquid starting to spill."” | W：QW-W7（第一拍有动作）；S：open_motion_cue；D：首秒定格 |
| P2 | I2VA 镜内顺序：首帧锚点 → 动作起势 → 连续发展 → 结果或反应 | MiniMax-H3 h3-prompt-writing SKILL.md https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/SKILL.md | “first-frame anchor → action onset → continuous development → result or reaction” | S：open_motion_cue 放在第一个时间码前 |
| P3 | 永远不要完全静止，低情绪镜头也要有微动作 | CineCrew technical_director.yaml | “IDLE RULE: Never pure static. Always include ambient motion.” | 已有 K-WRT-Q03 / QW-W2；S：min_motion_cue |
| P4 | 一拍一个主动作；分拍不留空 | H3 minimalist-product-ad SKILL.md https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/minimalist-product-ad-generator/SKILL.md；shot-table-spec | “Keep one main action per beat; secondary layers appear with slight delay.”；“avoid vague timing such as "continues moving" without body, camera, or prop detail.” | W：QW-W7（拍长 ≤ 2.5 s、不连着两拍静止） |
| P5 | 镜长按戏走，对白镜一般 2–6 秒 | CineCrew cinematographer.yaml | “Dialogue-heavy shots: often 2–6s for a single clear exchange.” | W：writer_text |
| P6 | 晚进早出 | No Film School https://nofilmschool.com/start-late-leave-early | “enter a scene as late as possible, and exit it as early as possible.” | W：writer_text |
| P7 | 结尾落在能接下一镜的姿态上 | CineCrew technical_director.yaml | “End each i2v on a pose/angle that leads naturally into the next shot.” | 已有 SS-M7 下镜 |
| P8 | 审片要查定格帧，以及写的动作有没有真出现 | CineCrew visual_judge.yaml https://github.com/Ironieser/CineCrew/blob/main/src/agents/dailies_reviewer/visual_judge.yaml | “(video) morphing / flicker / frozen frames.” | D：score_clip first_sec |

### 字幕（R11-8）

| # | 规则 | 出处 | 原文 | 落地 |
|---|---|---|---|---|
| T1 | 不加字幕和文字，除非明确要求（项目方：永不加） | MiniMax-H3 3d-animation-short-generator SKILL.md https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/3d-animation-short-generator/SKILL.md | “Do not add subtitles or text unless explicitly requested.” | S：assemble 硬默认 subtitles=False + 测试；D：caption 带检测；已有 Q6（出图 OCR） |
| T2 | H3 里只有“画面里真看得见的字”才用英文引号写，所以正文不要出现引号文字 | MiniMax-H3 base-en | “Place any banner, sign, label, subtitle, or neon text that is actually visible on screen in English double quotation marks.” | 写作方：不写招牌字，除非剧情需要 |

## 2. 系统层落点（Claude 写的系统，不涉及内容）

- 出图（frame_v9，唯一出图路径）：`asset_refs.EYELINE_NOTE`（固定句，进 `TEXT_NOTE_RES`）。只有正文没写视线时，`frame_job` 才补这一句，落点取本镜第一拍的 `视线=`。
- H3（services/recipes `build_base`）：`prompt.eyeline_cue`（正向句，不含否定词）和 `prompt.open_motion_cue`（第 0 帧起就在动，不停顿），都放在第一个时间码之前。
- 字幕：`ns_post.assemble` 写定 `subtitles: False`，并有测试 `tests/test_acting_no_subtitles.py`。
- 检测：`packages/qc/ns_qc/gaze.py`，接到出图 postflight 的 G1 和 VIDEO10 score_clip 的 `acting` 字段（像素旁证）。看镜头已转拦截（项目方 11-01 16:10，D-VQA-01，enforce=true）：由本地看图闸门 Q9 eye_contact / posed_stiff 拦，命中就重出，闸门先于视频。标定见 `docs/acting/CALIBRATION.md`。

## 3. 三套规则总表（SCRIPT-RSI 2026-11-01，D-SCR-07）

项目方原话（11-01 18:2x）：“2. 演员表现：所有图片不要看镜头，不要看镜头！因为这是按剧本来的，所以你可以看一看关于演员该怎么做。3. 规则与剧本：……你把演员的演戏规则、导演的规则、镜头的规则都做上去，把剧本改一下，重新更新一下规则。”

已有的复用（来源见 §1），缺的补；每条都有 check。置信度：高 = 有原文 + 本仓数据；中 = 只有一边。

### 3.1 表演（演员）

| id | 规则 | 出处 | check | 置信度 |
|---|---|---|---|---|
| A-01 | 每拍 视线= 写落点（人 / 物；画外写有名有姓的人或声源，不只写“对面 / 画外 / 一旁”） | E1 E2 E5（CineCrew、Eyeline match） | QW-A1（K-WRT-A01，本轮补方向词） | 高 |
| A-02 | 任何字段不写看镜头 | E4（Fourth wall） | QW-A2、RL-E2（K-WRT-A02） | 高 |
| A-03 | 朝向不写“正面朝镜头 / 面向镜头 / 正对镜头”，写朝向某人某物 | VIDEO-RCA 49/54；Qwen-Image 贴头像角度（中） | **QW-A6 新**（K-WRT-A06）、RL-E3 | 高 |
| A-04 | img（首帧）里每个在画的人写视线落点 | CineCrew “Who looks at whom”；首帧→片头 91% | **QW-A7 新**（K-WRT-A07） | 高 |
| A-05 | H3 首帧锚点句写开场视线 | H3 SKILL.md “first-frame anchor → action onset” | **QW-A8 新**（K-WRT-A08）、RL-E1 | 中 |
| A-06 | 表情写具体面部动作，相邻拍连续；语气在 `<d>` 外 | X1–X4、X6 | QW-A4（K-WRT-A04） | 高 |
| A-07 | 反应：注意力在对手身上 | X5（Meisner） | QW-A5 | 高 |
| A-08 | 身体动作：每 2 秒一个看得见的变化，不全静止 | P3 P4 | QW-W2、QW-A3 | 高 |
| A-09 | 开场即在动作中（首帧 = 动作前一刹那） | P1 P2 | QW-A3、open_motion_cue | 高 |
| A-10 | 口型：在画说话人张嘴、其他人闭嘴；独白镜嘴闭 | X7 | QW-W3、K-WRT-Q04 | 高 |

### 3.2 导演（调度 / 多人 / 节奏）

| id | 规则 | 出处 | check | 置信度 |
|---|---|---|---|---|
| D-01 | 多人镜每个在画的人每拍写“名字：视线 + 表情”；H3 每人一句 | M1 M2（CineCrew、H3 ref-en） | QW-A5、RL-E1（K-WRT-A05） | 高 |
| D-02 | 一镜重要角色 ≤3 | M3 | QW-CH3、RL-D7 | 高 |
| D-03 | 单镜无台词 ≤6 秒、有台词 ≤ max(6, 字数÷4.5+1.5)；总时长靠加镜 | P5 P6；R11-2/3；D-SCR-06 | QW-T1 / QW-T2（K-WRT-Q07） | 高 |
| D-04 | 返修重切：系统算新时长与插镜位置，写作方改写，台词逐字、总时长不变 | D-SCR-06 / 07 | **K-WRT-T03 新**、tools/script_rsi/full_repair.py、tests/test_script_rsi_full_repair.py | 中 |
| D-05 | 每拍 ≤2.5 秒、一拍一个主动作；不连着两拍静止 | P4 | QW-A3 | 高 |
| D-06 | 调度：首帧写清每人站位朝向，首尾朝向一致 | 附录 [已知问题预防] PI-07 | QW-K3 | 中 |
| D-07 | 结尾落在能接下一镜的姿态 | P7 | SS-M7 / K-WRT-I01 | 高 |

### 3.3 镜头（景别 / 机位 / 运动 / 视线轴线 / 提示词写法）

| id | 规则 | 出处 | check | 置信度 |
|---|---|---|---|---|
| C-01 | 每镜景别 + 机位 + 一个官方运镜，一镜一个连续镜头 | K-WRT-101/103、K-PRM-101 | QW-C1 / QW-C2、H3-A10 | 高 |
| C-02 | 正反打不越轴：同场相邻两镜两人左右不互换，越轴写明 | E7（H3 shot-table-spec）；180° 规则（K-WRT-104） | **QW-AX1 新**（原只有写法） | 高 |
| C-03 | 视线匹配切：上一镜看向哪，下一镜就是哪 | K-EDT-102 | 审片导演 K-WRT-I01 | 中 |
| C-04 | H3 只写正向落点，不写否定 | H3 不认否定（RL-N1） | RL-N1、RL-E2 | 高 |
| C-05 | H3 镜内时间码 `At 00:0x.000`，不是 `[0-2s]` | H3 base-en | H3 lint | 高 |
| C-06 | 系统句（出图双人句、H3 锚点 / 站位词表、配方 cue）永不写朝向镜头 | K-REN-702 / 703 | RL-E3、tests/test_video_rca.py、**tests/test_script_rsi_eyeline.py** | 高 |
| C-07 | 出图视线补句逐人覆盖 | K-REN-G06（新） | tests/test_script_rsi_eyeline.py | 中 |
| C-08 | 所有视频配方（含 Pika 三个）继承 eyeline_cue / open_motion_cue | K-REN-G05（新） | tests/test_script_rsi_eyeline.py | 高 |

### 3.4 编译器视线句覆盖（11-01 实查）

| 环节 | 现状 | 本轮 |
|---|---|---|
| 出片 H3（build_base，I2VA / FL2VA / Ref2VA） | jobs.json（16:56 编译）420/420 变体带 eyeline_cue + open_motion_cue；Pika i2va_pika_flex 305/305 | 加测试锁住全部配方（含 dialogue_closeup_pika / static_emotion_pika） |
| 出片重试锚点句 | 16:56 前的 alt 稿 “facing the camera” 仍在 jobs.json（K-REN-702 已改 FACING_EN） | WORKFLOW 重编即清（全量重做前置） |
| 出图视线补句（frame_job.eyeline_note） | 只补第一个人；正文有任何视线词就不补 → 双人镜第二个人漏 | 改为逐人覆盖（K-REN-G06） |
| 出图双人系统句（framing.two_shot_clause） | “各自至少四分之三侧脸朝向镜头（… toward the camera）” | 改为正向视线落点（K-REN-703 落实） |
| 身份参考图 | 林晚等身份脸是正面、看镜头的头像；Qwen-Image 可能连视线一起贴（VIDEO-RCA，中） | 未动（REFLOCK / VIDEO-RCA 范围），报总调度 |

### 3.5 ⤴ 统一口径

- E6“近景视线贴近镜头一侧” ⤴ 对生成模型一律写画外具体的人或物（A-01/A-02）。
- K-REN-G01“正文有视线词就不补、只补第一个人” ⤴ K-REN-G06 逐人覆盖。
- K-WRT-Q07“QW-T1 / T2 只在写初稿时生效、返修不能改镜数 / 时长” ⤴ K-WRT-T03 返修重切。
- framing.two_shot_clause“朝向镜头” ⤴ K-REN-703 正向落点（已改）。
- 轴线规则编号：本轮初版误用 QW-D1（与对白说话人 QW-D1 撞号），⤴ 统一为 QW-AX1。
