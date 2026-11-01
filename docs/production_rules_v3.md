# NS-Final Studio 生产规则 v3（production_rules_v3）

> 2026-10-31 · fredw-92/R2 · 状态：**现行规则总表**（写作 → 资产 → 首尾帧 → H3 视频 → 后期 → 本地实现）。
> 范围：只规定**字段、结构、格式、流水线逻辑和机检**；不写、不改、不评任何剧情、画面或台词内容（内容由写作模型或项目方给出，系统原样传）。
> 主要输入：docs/rules_gap_analysis.md（下称 GAP，采纳其全部“必须”项和建议的规则写法）、config/script_chat_rules.md（下称 R）+ config/script_chat_rules_appendix.md（RA）、docs/qwen_writing_contract.md（QWC）、config/qwen_writer_system_prompt.txt（WP）、docs/SOP_production.md §9A、docs/h3_prompt_guide_base_en.txt（官方指南副本，G）、docs/TODO_v1_close.md、docs/api_v1_contract.md、docs/USER_GUIDE_v1.md、docs/canvas-ui-spec-v3-merge.md，以及第四部分列出的代码。
> 和其它文件的关系：本文件是**总表**；R / RA / QWC / WP 是给写作模型的压缩版，必须与本文件一致（不一致处按第五部分改）。代码里的常量与本文件不一致时，以本文件为准，按第五部分落地。
> 规则编号：沿用现有编号（QW-*、S1-W*、R-C1、IMG-*、H3-*、P-B1、QW-SC*）；本次新增的编号在表里标 **新**；改了判定的标 **改**。级别：**block** = 不过不能送导入 / 不出视频；**warn** = 只提示。
> **过渡**：本文件新增的写作字段（人物表、出场人物、用到的场景、造型、人物、衔接）在剧本创作严格模式（`validate_script_strict`，与现有 `REQUIRE_SCENES` 同一开关方式）下按表中级别执行；导入旧剧本（没有这些字段）时一律降为 warn，旧剧本照常导入。

---

## 0. 本版已定的决定（fredw-92，2026-10-31）

| 代号 | 决定 | 落到哪里 |
|---|---|---|
| K1 | 镜数和总时长按 R:44 机检：镜数 6 ≤ n ≤ max(8, 说话轮次 + 独白段数, ⌈总时长 ÷ 6⌉)；总时长 50–75 秒通过，75 < 总时长 ≤ 90 秒 warn，> 90 秒或 < 50 秒 block | QW-E2 / QW-E3（改），第五部分 3.1 |
| K4 | 镜头时长统一为 **4–15 秒整数**（MiniMax 官方 H3：“`MiniMax-H3`: `4`–`15`”）；每镜必须写 `**时长**`，缺了 = block，系统不再默认 10 秒 | S1-W2（改）、H3-A11（改）、P-B1（改）；帧表加 4 秒 = 107 帧 |
| K2 / K3 / K6 | 旧文档里的过时写法作废：【配乐】的“推高 / 点题”（K2）、模板里的 `**负面追加**`（K3）、“一镜最多两位说话人 / >1 人只报 warn”（K6）。需要改的文件和行见 §1.7 | 第五部分 2.x |
| K10 | **保留有意偏离**：官方 G §4.5 让画面文字放进英文双引号，本项目 H3 全文禁止双引号（H3-D4，会被烧成字幕）。画面文字一律不写进 H3 | §1.5 H3-D4 注 |
| K12 | 负面提示词：保留字段（剧本全局头 `基础负面`、编译器的 image_negative / video_negative），标注“**CFG=1 下是否生效待实测**”，任何质量要求（含“不要字幕”）都不依赖它。写作侧仍不写否定词、不写 `**负面追加**`；H3 没有 negative 输入（官方：no `negative_prompt`），video_negative 不进 H3 | §3.2、§3.6 |
| C2 | img 长度上限 = **待实测**（Image 2.1 Turbo 的文本编码器 qwen3vl_8b 没找到官方上限）；实测前 IMG-C2 只做统计、不提示 | IMG-C2（新，warn，阈值待定） |
| K5 | **不在本文件决定**（林晚发色说法，属内容）→ 见 §0.1 | — |

### 0.1 待项目方决定（本文件不解决）

| 代号 | 问题 | 出处 |
|---|---|---|
| K5 | 林晚发色说法：REQUIREMENTS.md:21 B1 写“浅冰蓝及腰直发”；R §6A 规定逐字写“雾霾天蓝色及腰直发…”并且不写浅冰蓝。这是内容决定，请项目方定一个（R 里标“待项目方确认 Q16”）。定了之后只改 R §6A 与 REQUIREMENTS 其中一处的文字，本文件的结构规则不变 | REQUIREMENTS.md:21；R §6A |
| K9 | 写作模型：config/llm_providers.json 五个用途全部指向 abliteration large-flash（TODO §0）；记忆与 REQUIREMENTS G8 写“还是用 qwen 写 / abliteration 仅可选”。以项目方最新原话为准，由总调度统一（本文件只描述配置怎么切，见 §4.6） | TODO_v1_close.md:7；REQUIREMENTS.md:84 |
| F3 | 片尾字卡（SOP §13）算不算“字幕”（RA:89 项目方要求不要字幕） | SOP_production.md:384 |
| P-A7 | GPU3 视频卡 ComfyUI 以 `--cache-none` 启动，每版重载模型（6 秒视频 12–14 min）；去掉需重启 gpu3 该进程，待项目方同意 | USER_GUIDE_v1.md |
| GPU1 | gpu3 GPU1 上的千问服务（:8098、qwen-agent）停用，待项目方确认（会中断信箱任务） | TODO §5 |

---

# 第一部分 写作规则（提纲 → 分集 → 镜头）

## 1.0 整体骨架（写作模型的完整输出格式）

`｜` 一律全角；`**标签**：值` 一行写完（空行结束字段，QW-F0）；尖括号是占位符。全局头在**第一个** `## ep` 之前，只在全剧第一次输出（或项目方贴入的剧本头）时出现；之后每集从 `## ep` 开始。

~~~text
（全局头：剧本头原有部分，项目方 / 系统维护）
**每条prompt统一前缀**：
```
【林晚】<系统角色锁>
【顾沉】<系统角色锁>
```
**LoRA 触发词表**：
```
图像LoRA
  <trigger>  <说明>
视频LoRA
  <trigger>  <说明>
```
**全剧人物表**：
| 角色 | 角色id | 中文外貌句 | EN外貌短语 | VOICE声线短语 |
|---|---|---|---|---|
| <角色名> | <slug> | <年龄段>｜<体型>｜<发型发色>｜<服装主色>｜<标志物>｜<不可变特征> | <English identity phrase> | <English voice phrase> |

**全剧场景表**：
| 场景id | 名称 | 空间描述 | 时段 | 光线 | 固定陈设 |
|---|---|---|---|---|---|
| sk_<id> | <名称> | <空间描述> | <时段> | <光线> | <固定陈设> |

## ep<NN>《<集标题>》<含亲密镜加 🔴>
**剧情**：<一句话 logline>
**出场人物**：<角色名>、<角色名>
**用到的场景**：sk_<id>、sk_<id>
**造型｜<角色名>**：服装=<…>｜鞋=<…>｜妆=<…>｜发=<…>｜甲=<…>｜饰品=<…>｜EN=<English outfit phrase>
**造型｜<角色名>｜镜<N>起**：<只写变了的槽位>｜EN=<English outfit phrase>
**配乐**：<本集配乐中文说明>；【BGM】<English BGM prompt>
**本集人物表**：            ← 只在本集有新登场角色时写，格式同全剧人物表
**本集场景表**：            ← 只在本集有新场景时写，格式同全剧场景表（S-back 已实现）

**镜1｜img（<备注>）**：<首帧提示词>
**场景**：sk_<id>｜<本镜场景细节>
**人物**：<角色名>（在画｜<左/中/右>｜<前/中/后>）、<角色名>（画外）
**衔接**：<接力 / 同场换机位 / 换场 / 接上一集>｜承：<延续项>
**motion**：<lnwan01，><english camera move> <中文运镜词>，<动作过程，含表情短句>——<结束状态>
**时长**：<N>秒
**sound**：<中文声音>；【亲密声】<…>；【配乐】<动作>，强度<0–3>，<避让>；【H3 audio】<English 1–4 句>
**对白**：（<角色名>，<语气/画外标记>）“<台词>”／（<角色名>，<…>）“<台词>”
**🎙（<角色名>，<说明>）**：<内心独白>
**H3提示词**：
```text
<四块，见 §1.5>
```

**镜2｜img**：…
---
~~~

字段顺序：集头 = 剧情 → 出场人物 → 用到的场景 → 造型（可多行）→ 配乐 → 本集人物表 → 本集场景表；每镜 = img → 场景 → 人物 → 衔接 → motion → 时长 → sound → 对白 → 🎙 → H3提示词（H3提示词 永远最后，S1-W7）。没有台词 / 独白时整行省略，不写“无”（S1-W4）。

## 1.1 全局头

| 字段 | 写法（逐字） | 用途 | 消费方（代码） | 机检 | 级别 |
|---|---|---|---|---|---|
| 角色锁 | `**每条prompt统一前缀**` 后的代码块，每行 `【角色名】描述` | 首帧 / 尾帧最前面的角色 DNA 锁（系统前置，写作者不抄） | importer/script_md.py `_parse_globals` → `ScriptGlobals.character_locks`；agent/compiler.py `compile_shot`（locks） | QW-G1 **新**：代码块存在且至少一行 `【…】` | warn（项目方维护，写作模型不输出） |
| LoRA 触发词表 | `**LoRA 触发词表**` 后的代码块；`图像LoRA` / `视频LoRA` 分段，每行缩进 `<trigger>  <说明>` | 首帧 img / motion 开头可用的触发词白名单；LoRA 文件与强度由系统按表配 | `_parse_globals` → `ScriptGlobals.lora_triggers`；compiler `loras_for`（强度缺省 0.8）；IMG-T1 | QW-G2 **新**：分段名只取 图像LoRA / 视频LoRA，trigger 是 `[A-Za-z0-9_]+`；IMG-T1（已有）：img 开头的触发词 ∈ 表 ∪ `pose_<名称>` | QW-G2 warn；IMG-T1 warn |
| 身份 LoRA | 写作者**不写**；`config/auto_lora_triggers.json`：林晚 → `lnwan_qi` / `lin_wan_qi_v1.safetensors` / 0.8，入镜即由系统补在触发词最前 | 出图身份一致 | compiler `identity_triggers`、frame_edit `identity_lora_files` | — | — |
| **全剧人物表**（人物登记） | `**全剧人物表**：` 单独一行，下一行起表头 `\| 角色 \| 角色id \| 中文外貌句 \| EN外貌短语 \| VOICE声线短语 \|` + 分隔行 + 每人一行 | 每个角色的固定外貌（中文，给出图 / 角色卡）、H3 英文身份短语、H3 英文声线短语的**唯一存放处**；之后各镜逐字复用 | **待实现**：importer 解析为 `ScriptGlobals.character_registry`（复用 `scene_tables` 的表格解析）；compiler（人物识别）、h3_lint（H3-X1/X3）、ns_post TTS（声线）、资产角色卡 | QW-P1…P6 见下 | 见下 |
| **全剧场景表** | `**全剧场景表**：` + 表头 `\| 场景id \| 名称 \| 空间描述 \| 时段 \| 光线 \| 固定陈设 \|`（S-back 已实现） | 场景资产的唯一文字来源；首帧【场景】段；场景底图生成 | importer `scene_tables` / `build_scene_library` → `ScriptGlobals.scene_library`；state_timeline `_apply_script_scenes`；render scene_plate | QW-SC2/SC4/SC5（已有）；QW-SC8 **新** | block |

**人物表各列**

| 列 | 写法 | 规则 |
|---|---|---|
| 角色 | 角色中文名（与角色锁、对白括号同一写法） | 全剧唯一（QW-P2） |
| 角色id | 已有角色用 ns_schema/looks.py `CHARACTERS` 的 slug（series10：lin_wan、gu_chen、chen_yu、ch_a_lan）；新角色写 `ch_<小写英文数字下划线>` | 资产目录 `assets/characters/<id>`、data/looks 用同一个 id（QW-P2） |
| 中文外貌句 | 六项，用全角 `｜` 分隔、按序：年龄段｜体型｜发型发色｜服装主色｜标志物｜不可变特征（官方 3d-animation skill 角色卡六项：“age range, body type, hairstyle, outfit colors, signature props, and do-not-change traits”）。有系统角色锁的角色（林晚、顾沉、陈宇）写 `系统锁` | QW-P6 |
| EN外貌短语 | 一条英文名词短语：年龄、性别、发色长度与刘海、脸 / 肤色 / 体型。**只写身份，不写服装**（服装每集变，写在造型行的 EN=，见 §1.2）。不写人名、触发词、否定词、双引号 | QW-P3；H3 锚点句逐字包含它（H3-X1） |
| VOICE声线短语 | 一条英文短语，含 `voice`，写音色、音区、语速（林晚：22 岁成年女性、普通话、中高音区、甜而带气声、自然语速（项目方 2026-10-31 原话“改成正常节奏”）、尾音软——RA A4 的要素，由写作者写成一条英文） | QW-P4；说话人首次出现的描述逐字包含它（H3-X3） |

**本集人物表**：某角色在全剧人物表里没有、本集第一次出场时，在本集写 `**本集人物表**：`（位置同本集场景表：`**配乐**` 之后、镜1 之前），格式与列同上；之后各集不再写（再写时各格须与第一次逐字相同，QW-P5）。

| 编号 | 规则 | 级别 |
|---|---|---|
| QW-G1 **新** | 全局头有角色锁代码块 | warn |
| QW-G2 **新** | 触发词表分段与 trigger 格式 | warn |
| QW-P1 **新** | 人物表 = 标签行 + 表头（5 列，列名逐字）+ 分隔行 + 每人一行 5 格，格内不用 ASCII `\|` | block |
| QW-P2 **新** | 角色名全剧唯一；角色id 是 CHARACTERS 的 slug 或 `ch_[a-z0-9_]+`，一个 id 只对应一个角色名 | block |
| QW-P3 **新** | EN外貌短语非空、无 CJK 字符、无 H3-A5 否定词、无双引号、不含任何已登记角色名和触发词 | block |
| QW-P4 **新** | VOICE声线短语非空、无 CJK、含 `voice`、无否定词和双引号；对白或 🎙 里出现过的每个说话人都必须有 | block |
| QW-P5 **新** | 同一角色再次出现在人物表时各格与第一次逐字相同（同 QW-SC5 的机制） | block |
| QW-P6 **新** | 中文外貌句恰好 6 项（`｜` 分隔），或逐字 `系统锁` | warn |
| QW-SC8 **新**（GAP E1） | 场景表的 空间描述、固定陈设 两格里不出现已登记角色名、“她 / 他”；固定陈设 1–3 件（中文逗号或顿号分隔）。底图必须是空场景（官方：“Scene cards must show environments only”） | block |

## 1.2 集头（每集）

| 字段 | 写法（逐字） | 用途 | 消费方 | 机检 | 级别 |
|---|---|---|---|---|---|
| 集标题 | `## ep<NN>《<标题>》`，含亲密镜在行内任意处加 🔴 | 集号、成人整集标记 | importer `EP_RE` → `Episode.number/title/high_intensity`；adult_overrides | QW-E1（已有） | block |
| logline | `**剧情**：<一句话>` 紧接标题 | 画布集头、A/B 对比 | `Episode.synopsis` | QW-E1（已有） | block |
| 出场人物 | `**出场人物**：<角色名>、<角色名>…`（顿号分隔） | 本集要准备哪些人物资产 / 造型确认；资产页“出现集数” | **待实现** `Episode.cast`；looks.seed、ref_switch、资产页 | QW-E4 **新** | block |
| 用到的场景 | `**用到的场景**：sk_<id>、sk_<id>…` | 本集要准备 / 定稿哪些场景底图（S2 闸门） | **待实现** `Episode.scene_ids`；state_timeline、场景资产页 | QW-E5 **新** | block |
| 造型表 | 每个在画角色一行：`**造型｜<角色名>**：服装=<…>｜鞋=<…>｜妆=<…>｜发=<…>｜甲=<…>｜饰品=<件数+部位>｜EN=<English outfit phrase>`；可选槽位 `其他=<…>`。本集中途换装：`**造型｜<角色名>｜镜<N>起**：<只写变化的槽位>｜EN=<换装后的完整英文服装短语>` | 每集造型资产（data/looks schedule 的集计划）；首帧造型片段；H3 锚点句服装 | **待实现** `Episode.looks: [{character, from_shot, slots, en}]`；ns_agent/looks.py `seed`（取代 schedule.json 的“服装/鞋未设”needs_review）；compiler `look_fragments` | QW-E6、QW-E7 **新** | 见下 |
| 本集配乐 | `**配乐**：<中文说明>；【BGM】<English>`，在镜1 之前 | 整集 BGM（后期）与 H3 配乐的最后一级回退 | `Episode.music/music_bgm`；h3_prompt `resolve_music`；ns_post.music | R-C1（已有） | block |
| 本集人物表 / 本集场景表 | 见 §1.1；S-back 场景表语法 | 新角色 / 新场景登记 | 同 §1.1 | QW-P*、QW-SC* | block |

造型槽位中英对照（固定，取自 ns_schema/looks.py `SLOTS`）：服装 = outfit，鞋 = shoes，妆 = makeup，发 = hair，甲 = nails，饰品 = accessory，其他 = other。槽位值：已有单品照抄 data/looks/wardrobe.json 的 `name`；新单品写 `新：<颜色+款式+材质>`（GAP E3）；`沿用` = 与上一集结束时相同（第一次出场的集不能写沿用）。身体装饰（D 状态：乳环等）由全局头 decor_schedule 管，写作者不写。

| 编号 | 规则 | 级别 |
|---|---|---|
| QW-E4 **新** | 出场人物行存在；每个名字已登记（人物表或角色锁）；集合 = 本集各镜人物行里所有角色的并集 | block |
| QW-E5 **新** | 用到的场景行存在；每个 id 在场景表里；集合 = 本集各镜 `**场景**` id 的集合 | block |
| QW-E6 **新** | 本集任一镜人物行里“在画 / 局部”的角色都有一行 `**造型｜<角色名>**`；槽位名只能是上表 7 个中文名 + `EN`；服装、鞋、妆、发、EN 五项必填；EN 无 CJK、无否定词、无双引号 | block |
| QW-E6b **新**（GAP E3） | `新：` 以外的单品名能在 wardrobe.json 找到（字符串比对） | warn |
| QW-E7 **新** | 换装行的 `镜<N>` 存在于本集；该镜 img 备注或 motion 写了换装（R §6A“动作接力”已要求） | block（镜号）/ warn（换装说明） |
| QW-E2 **改**（K1） | 镜号从 1 连续；镜数 6 ≤ n ≤ max(8, 说话轮次 + 独白段数, ⌈总时长 ÷ 6⌉) | block |
| QW-E3 **改**（K1） | 各镜时长之和 50–75 通过；75 < 和 ≤ 90 warn；> 90 或 < 50 block | block / warn |

## 1.3 每镜字段

### 1.3.1 字段表

| 字段 | 写法（逐字） | 用途 | 消费方 | 机检 | 级别 |
|---|---|---|---|---|---|
| 镜头行 + 首帧 img | `**镜N｜img（<备注>）**：<中文一行>`，按序：①触发词 ②景别词与机位 ③人物（角色名 + 本镜造型单品）④朝向 / 视线 / 姿势 / 表情 ⑤场景（照抄场景表名称与本镜看得到的固定陈设）⑥光线 ⑦材质（R §3） | 首帧提示词正文 | importer `SHOT_RE` → `Shot.img_prompt/img_note/img_triggers`；compiler `compile_shot`（image_prompt） | QW-C2（景别，warn，严格升 block）、IMG-N1（否定词 block）、IMG-T1、QW-Q1、QW-SC7 **新**、IMG-C2 **新**、QW-CH4 **新** | 见 §1.3.2 |
| 场景行 | `**场景**：sk_<id>｜<本镜场景细节>`，紧接 img 行；细节写本镜机位看到的部分、道具状态（S-back 已实现） | 首帧带场景定稿底图；首帧【场景】段；场景分组 | importer `split_scene_line` → `Shot.scene_id/scene_detail`；state_timeline `_apply_script_scenes`；ns_render/scene_plate `shot_plate`；pipeline `render_image(scene_ref)` | QW-SC1、SC3（block），SC6（warn） | block |
| 人物行 | `**人物**：<角色名>（<在画｜左/中/右｜前/中/后> / <局部｜部位｜左/中/右> / <画外>）、…`；只列本镜入镜或发声的人；不写“她 / 他” | 入镜判断（取代关键词猜测）→ 身份 LoRA、造型注入、时间线人物状态、H3 说话人对人 | **待实现** `Shot.cast: [{name, presence, x, depth}]`；compiler `present_characters`（有人物行就用它，不再猜）；looks `Resolver.characters`；state_timeline `character_state` | QW-CH1…CH5 **新** | block |
| 衔接行 | `**衔接**：<接力 / 同场换机位 / 换场 / 接上一集>｜承：<上一镜结束状态延续下来的 1–3 项：位置、手持物、视线>`；镜1 只能写 `换场` 或 `接上一集` | 决定下一镜首帧是否由上一镜尾帧编辑（接力）；时间线分段 | **待实现** `Shot.link/link_carry`；state_timeline `group_scenes`（取代换段词猜测）；pipeline 首帧来源（接力 = 上一镜定稿尾帧作 图1） | QW-LK1…LK3 **新** | block |
| 景别 / 运镜 / 镜头 | **不单设字段**：景别 = img 触发词后第一个景别词（R §6A 词表）；运镜 = motion 触发词后的英文运镜；机位 / 镜头 = img 第②项 | 画布行“景别 · 运镜”；首尾景别差检查 | validate_qwen_script（QW-C1/C2）、h3_lint `camera_moves` | QW-C1 **改**、QW-C4 **新**、QW-K2 **新** | 见下 |
| motion | `**motion**：<lnwan01，><english camera move> <中文运镜词>，<分步动作过程（含 1–2 个表情短句）>——<结束状态>` | 画布“剧本原文 / 运镜 / 表情”；结束状态 = 尾帧 | `Shot.motion_prompt/motion_triggers`；compiler `split_camera`、`end_state`（last_prompt） | S1-W1（block）、QW-C1、QW-C3 | 见下 |
| 结束状态（尾帧） | motion 最后一个 `——` 之后：以**景别词开头**，再写入镜人物 → 朝向姿势手位 → 视线表情 → 衣物饰品此刻状态 → 光落点 → 画面中心（RA A6）；≥8 字中文，一张能单独出图的静帧 | 尾帧编辑提示词（由定稿首帧编辑） | compiler `end_state` → `last_prompt`（`LAST_FRAME_KEEP` + 结束状态） | IMG-L1、IMG-L2（block）、QW-K1/K2/K3 **新** | block |
| 表情 | 写在 motion 动作过程里：1–2 个可观察短句（脸部特写 1 个），每句 ≤28 字，含 R §4 的线索词（眼神、嘴角、睫毛、呼吸、抿、笑…）；眨眼写次数 | 画布“表情”；H3 动作路径 | validate_qwen_script QW-C3 | QW-C3（warn，严格升 block） | warn/block |
| 时长 | `**时长**：<N>秒`，N 为 **4–15** 整数（K4）；超过 15 秒拆镜；远景 / 快动作 / 大位移 5–6 秒 | 帧数（17k+5 网格）、对齐句 S.SS、字数上限 | importer → `Shot.duration`（缺 = None，不再默认 10）；h3_lint `frames_for_seconds`；h3_video `shot_seconds` | S1-W2 **改** | block |
| sound | `**sound**：<中文>；【亲密声】<…，非亲密镜整段省略>；【配乐】<动作>，强度<0–3>，<避让>；【H3 audio】<English 1–4 句>` | 中文 → 后期拟音；【亲密声】判定亲密镜；【配乐】→ 后期 cue / 静默判定；【H3 audio】= overall_soundscape | importer `_sound_blocks` → `Shot.sound_intimate/sound_h3/music_cue`；h3_prompt `resolve_music`（静默 cue → N/A）；ns_post | R-C1、S1-W3、QW-S1、QW-M1 **新** | block |
| 对白 | `**对白**：（<角色名>，<语气 / 画外标记>）“<台词>”／…`；括号**以角色名开头**；画外标记只用 画外 / 电话 / 语音 / OS / VO（RA A4b） | H3 `<d>` 逐字来源；TTS / 字幕外的说话人对人 | importer `_split_dialogue` → `Shot.dialogue[].speaker_note`；h3_lint H3-D3 | S1-W4（已有）、QW-D1 **新** | block |
| 独白 / VO | `**🎙（<角色名>，<说明>）**：<独白>`；永不进 H3 | 后期 TTS，用该角色 VOICE | `Shot.voiceover.note/text`；ns_post TTS；h3_lint H3-D6 | H3-D6（已有）、QW-D2 **新** | block |
| H3提示词 | 标签单独一行，正文在 ```` ```text ```` 代码块里；见 §1.5 | 视频提示词（原样传 H3） | importer（H3 收集）→ `Shot.h3_prompt`；h3_video `resolve_prompt` | S1-W7 + H3-* 全部 | block |

**字数上限**（已有，R §2）：对白（不计标点）≤ 3.5×N；🎙 ≤ 3.5×(N−0.3)。

### 1.3.2 每镜规则

| 编号 | 规则（只查结构 / 字符串） | 级别 |
|---|---|---|
| QW-CH1 **新** | 每镜有 `**人物**` 行；每项为 `<名>（<在画｜x｜depth>｜<局部｜部位｜x>｜<画外>）`，x ∈ 左 / 中 / 右，depth ∈ 前 / 中 / 后；行内不出现“她 / 他” | block |
| QW-CH2 **新** | 人物行里的名字都在人物表或角色锁里 | block |
| QW-CH3 **新** | 在画 + 局部 ≤ 3 人（官方 shot-table-spec：“no more than three important characters”；RA A2） | block |
| QW-CH4 **新** | img 与结束状态里出现的已登记角色名 ⊆ 人物行（在画或局部）；人物行在画的人在 img 里出现（名字比对） | block / warn |
| QW-CH5 **新** | 对白和 🎙 的说话人 ⊆ 人物行；人物行标“画外”的人在对白里必须带画外标记 | block |
| QW-LK1 **新** | 衔接行存在；取值 ∈ {接力, 同场换机位, 换场, 接上一集}；镜1 只能是 换场 / 接上一集；`承：` 在接力时必填 | block |
| QW-LK2 **新** | 接力 / 同场换机位：场景 id 与上一镜相同；接力时本镜 img 景别与上一镜结束状态景别相差 ≤1 档 | block（场景）/ warn（景别） |
| QW-LK3 **新** | 换场：场景 id 与上一镜不同，或 img 备注 / motion 里有 R §6A 的换段词（次日、第二天、翌日、闪回、回忆、梦境、数日后、几天后、一周后、当晚、句首“周X”） | block |
| QW-C1 **改**（K14） | motion 触发词后的英文运镜只从 `camera push in / pull out / zoom in / zoom out / pan left / pan right / truck left / truck right / tilt up / tilt down / pedestal up / pedestal down / arc shot / tracking shot`、`static shot` 中选（`static camera` 改为 `static shot`，与官方 §4.3 同形；旧写法过渡期仍认） | warn（严格升 block） |
| QW-C4 **新**（GAP B5） | motion 的运镜类型 = h3_lint `camera_moves` 从 H3 正文解析出的类型 | warn |
| QW-K1 **新**（GAP B4） | 结束状态第一个词在景别词表里 | block |
| QW-K2 **新** | 结束状态景别与 img 景别相差 ≤1 档；运镜为 static / pan / tilt / truck 时相差 0 档（RA A6）；档位：大远景 < 远景 < 全景 < 全身 < 中景 < 中近景 < 近景 < 特写 < 大特写 | block |
| QW-K3 **新**（GAP B4/C3） | 朝向只用 ns_render/refs.py 认得的词（背影、背对、背抵、后脑；侧脸、侧影、侧面）；img 与结束状态朝向词一致，除非 motion 主动作含“转身” | warn |
| QW-SC7 **新**（GAP C1） | img 第⑤项包含场景表里该场景的“名称”或至少一件“固定陈设”（字符串包含） | warn |
| IMG-C2 **新**（C2） | img 长度统计；上限 X 字待一次 A/B 实测确定，确定前不提示 | warn（待实测） |
| S1-W2 **改**（K4） | `**时长**：<整数>秒` 必须存在，4 ≤ N ≤ 15；缺失或越界 block（导入器不再默认 10） | block |
| QW-M1 **新**（GAP B7） | 【配乐】动作 ∈ {进入, 延续, 渐强, 推到高点, 撤到静默, 落下, 重音}；强度 ∈ 0–3（可省略 = 沿用上一条；撤到静默省略 = 0）；避让 ∈ {对白避让, 独白避让, 无需避让}；有对白必须写“对白避让”，有 🎙 必须写“独白避让” | block |
| QW-D1 **新**（GAP B6） | 对白括号第一个词是已登记角色名；括号里的画外标记 ∈ {画外, 电话, 语音, OS, VO} | block |
| QW-D2 **新** | 🎙 标签括号第一个词是已登记角色名，且该角色有 VOICE | block |

已有、不变（继续执行）：QW-F0、R-C1、S1-W1、S1-W3、S1-W4、S1-W7、QW-C2、QW-C3、QW-Q1、QW-S1、IMG-N1、IMG-L1、IMG-L2、IMG-T1、QW-SC1–SC6。

## 1.4 时长 → 帧数 → S.SS（K4 后的唯一对照表）

帧数 = ceil(N×24) 向上取 17k+5（h3_lint `frames_for_seconds`）；S.SS = `f"{帧数/24:.2f}"`。

| N（秒） | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 帧数 | **107** | 124 | 158 | 175 | 192 | 226 | 243 | 277 | 294 | 328 | 345 | 362 |
| S.SS | **4.46** | 5.17 | 6.58 | 7.29 | 8.00 | 9.42 | 10.12 | 11.54 | 12.25 | 13.67 | 14.38 | 15.08 |

注：4 秒档要求把 h3_lint `MIN_FRAMES` 与 workflows `H3_FRAMES_MIN` 从 124 降到 107（第五部分 3.3）。代码注释写 124–362 是“训练范围”，4 秒档的画质未实测，先按官方范围放开，出片后在 §4.7 记录结果。

## 1.5 H3提示词（四块）

~~~text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the <S.SS>-second mark of the target video.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, <景别> begins in the position, framing and lighting established by Picture 1, <锚点句>. The camera <运镜> <幅度> <速度> as <动作起点>. <中间变化>. <收窄>, and <主语> settles into the <pose/expression/spacing/composition> established by Picture 2 at the end of the shot.

overall_soundscape: <与【H3 audio】逐字相同>

non_diegetic_music: <1–3 句英文，或逐字 N/A>
~~~

| 部分 | 规则 | 机检 | 级别 |
|---|---|---|---|
| 对齐句 | 第一行逐字（含 `—`）；`Picture 2 (from Shot 1)`；S.SS 按 §1.4 表照抄；之后恰好空一行 | H3-A1、H3-A2；P-B1 **改**（网格下限 107） | block |
| 结构 | 三字段顺序固定、各空一行、各一段；只有一个 `[Shot 1]`，不写时间戳 | H3-A2、H3-A3 | block |
| 开场与首尾句 | `[Shot 1]` 后紧接 `Live-action, cinematic, shallow depth of field,`；首句含 `established by Picture 1`；末句 `settles into … established by Picture 2 at the end of the shot.` | H3-A8、H3-A4 | block |
| 锚点句 | 只一句，按序：可见人数 → 每人 **EN外貌短语（逐字照抄人物表）+ 本集造型 EN（逐字照抄造型行）** → 屏幕位置（与人物行一致）→ 场景 1–2 个元素 → 光源色温（与 img 同一组词）；可写 `preserving <her> appearance, clothing, <饰品与数量>` | H3-X1 **新**；H3-A6 | block |
| 正文 | 写连接两帧的动作路径，不复述两张静帧；英文；无否定词；无画质词；无抽象词 | H3-A5、A6、A7、A8b、A9 | block（A6/A9 按现有级别） |
| 运镜 | 只用官方子集：Zoom In/Out、Push In/Pull Out、Pan、Truck、Tilt、Pedestal、Arc Shot、Tracking Shot、Static Shot；幅度 `with small/large amplitude`，速度 `at slow/fast speed`；每镜一个、句中动作。**有意不用** 官方的 Shake Slightly/Strongly、POV、Roll（GAP D4，项目决定） | H3-A10、QW-C4 | block / warn |
| 对白 | `(S<n>)` 在每个 `<d>` 前；`<d>[Chinese] 原文</d>` 与 `**对白**` 逐条逐字逐标点一致；说话人首次出现在编号之前写齐年龄、性别、on-screen/off-screen、voice、语速，且**逐字包含该角色的 VOICE 声线短语**；画外 `says in an off-screen voiceover` + 嘴唇闭合句；首句和末句不放 `<d>` | H3-D1、D2、D3、D5、D8；H3-X3 **新**；H3-X2 **新** | block（X2 warn） |
| 说话人数 | 普通对话镜只有 (S1)；亲密镜只有 (S1) = 林晚，soundscape 不出现男性词 | H3-D7 | block |
| 独白 | 🎙 永不进 H3 | H3-D6 | block |
| 双引号 / 人名 | 全文无双引号、无人名、无触发词。**有意偏离官方**（G §4.5 画面文字用双引号）：双引号会被烧成字幕（K10），画面文字不写进 H3 | H3-D4 | block |
| soundscape | 与【H3 audio】逐字相同；1–4 句英文；不写 `<d>`、N/A | H3-S1、H3-S2、QW-S1 | block |
| 配乐 | 1–3 句英文（乐器、速度、节奏、强弱）或逐字 `N/A`；不写情绪词；与【配乐】一致（撤到静默 → N/A） | H3-S3 | block |
| 长度 | 全文 ≤ 7000 字符（官方 API 硬上限：“maximum of 7000 characters per `text`”） | H3-A12 **改**（warn → block） | block |
| 时长 | 4–15 s | H3-A11 **改**（判定区间 4–15.1 s 不变，但随 MIN_FRAMES 124 → 107 才真正放开 4 秒档；与 S1-W2 同口径） | block |

| 编号 | 规则 | 级别 |
|---|---|---|
| H3-X1 **新**（GAP A3/D1） | 锚点句（首句）逐字包含本镜每个“在画”角色的 EN外貌短语，以及该角色当前造型（含 `镜N起` 换装）的 EN 服装短语 | block |
| H3-X2 **新**（GAP B8） | 首句与末句里没有 `<d>`（H3 片头约 0.5 s 乱语；成片 0.3 s 交叉溶解吃掉首尾） | warn |
| H3-X3 **新**（扩展 H3-D8） | 每个说话人第一次出现的描述句逐字包含其 VOICE 声线短语 | block |

## 1.6 规则一览与计数

| 类别 | 已有、不变 | 改 | 新 |
|---|---|---|---|
| 全局头 / 人物 / 场景表 | QW-SC2、SC4、SC5、IMG-T1（4） | — | QW-G1、G2、P1–P6、SC8（9） |
| 集头 | QW-E1、R-C1（2） | QW-E2、E3（2） | QW-E4、E5、E6、E6b、E7（5） |
| 每镜 | QW-F0、S1-W1、S1-W3、S1-W4、S1-W7、QW-C2、C3、Q1、S1、IMG-N1、L1、L2、QW-SC1、SC3、SC6（15） | S1-W2、QW-C1（2） | QW-CH1–CH5、LK1–LK3、C4、K1–K3、SC7、IMG-C2、QW-M1、D1、D2（17） |
| H3 | H3-A1–A10、A8b、D1–D9、S1–S3（23） | H3-A11、A12、P-B1（3） | H3-X1、X2、X3（3） |
| 合计 | **44** | **7** | **34** |

写作规则共 85 条（44 + 7 + 34）。新增 34 条中主级别 block 25 条、warn 9 条（QW-G1、G2、P6、E6b、C4、K3、SC7、IMG-C2、H3-X2）；QW-CH4、QW-LK2、QW-E7 各有一项子判定只报 warn（按 block 计）。

## 1.7 旧文档要改的地方（K2 / K3 / K6 及本版其它决定）

| 决定 | 文件:行 | 现写法 | 改成 |
|---|---|---|---|
| K2 | config/qwen_writer_system_prompt.txt:14 | 【配乐】“进入/延续/推高/落下/点题” | R §6A 的 7 个动作词 + 强度 + 避让 |
| K2 | docs/qwen_writing_contract.md:134 | R-C1 说明里“进入/延续/推高/落下/点题” | 同上 |
| K2 | packages/schema/ns_schema/script.py:100（注释） | “进入/延续/推高/落下/点题” | 同上 |
| K3 | docs/qwen_writing_contract.md:48 | 模板里 `**负面追加**：<可选>` | 删除 |
| K3 | docs/SOP_production.md:133 | 格式清单里有 `**负面追加**` | 删除（导入器仍认旧剧本的这个标签，services/agent/ns_agent/importer/script_md.py:510 保留） |
| K6 | config/script_chat_rules_appendix.md:27 | “非亲密多人镜一镜最多两位说话人” | “普通对话镜每镜一个说话人（H3-D7 block），A→B→A 拆镜” |
| K6 | config/script_chat_rules_appendix.md:69 | “非亲密镜一镜 ≤2 位说话人（机检对 >1 人只报 warn）” | 同上 |
| K1 | docs/qwen_writing_contract.md:46、:60、:61；config/qwen_writer_system_prompt.txt:7 | 固定 6–8 镜、50–75 秒 | 按 R:44 与 §0 K1 |
| K4 | config/script_chat_rules.md:45（及帧表）；docs/qwen_writing_contract.md:125；config/qwen_writer_system_prompt.txt:13；docs/SOP_production.md:181（及 :185 表）、:220、:339 | 5–15 秒 / ≥124 帧 | 4–15 秒；帧表加 4 → 107 / 4.46 |
| K7 | config/qwen_writer_system_prompt.txt:25；docs/qwen_writing_contract.md:145 | 说话人“角色名或 她/他” | 只写角色名（QW-D1） |
| K8 | config/qwen_writer_system_prompt.txt:23；docs/qwen_writing_contract.md:120 | 表情“至少一个” | 1–2 个，首选 1 个 |
| K11 | services/agent/ns_agent/state_timeline.py:68 | 换段词含“转场” | 去掉（R 不允许写“转场”）；有衔接行后换段以衔接行为准 |
| K13 | docs/qwen_writing_contract.md:176 | 造型资产“不从剧本解析” | 造型行 → data/looks 集计划（§2.1） |
| K14 | config/script_chat_rules.md:80；docs/qwen_writing_contract.md:117；config/qwen_writer_system_prompt.txt:23；tools/validate_qwen_script.py:59、:128 | `static camera` | `static shot`（旧写法过渡期仍认） |
| GAP A3 | config/script_chat_rules.md §5“外貌短语”条（R:90 附近） | 外貌短语含“主要服装”，同集逐字 | 身份短语（人物表 EN，全剧逐字）+ 服装短语（造型行 EN，本集逐字），两者都照抄进锚点句 |
| RA A4 声线 | config/script_chat_rules_appendix.md:65 | “第一次出现时写成一条英文短语，之后逐字复用” | 写进人物表 VOICE 列 |

---

# 第二部分 资产生成逻辑

## 2.0 总原则

- 资产 = 人物（身份底板、造型、单品）+ 场景（底图与变体）+ 道具（暂无独立类型）。全部跨集复用，以剧本里的 **id** 关联：角色id（人物表）、场景id `sk_*`（场景表）、单品 id（wardrobe.json）。
- 资产生成只用 gpu3 GPU0 的 Image 2.1（t2i / 单参考编辑 / 多参考编辑）；提示词原样传，不做内容检测、不评分、不否决（frame_edit / asset_edit 模块头）。
- 每次生成 = 一条生成记录 + 一个新版本，挂父版本形成修改链；“定稿”是显式动作；定稿变化按 §2.5 让下游过期。

## 2.1 人物

| 层 | 数据 | 来源 / 写入 | 代码 |
|---|---|---|---|
| 身份 | 角色锁（文字）；身份底板 `assets/characters/<id>/plates/manifest.json`（angle F/34L/34R/P/B，按妆容 M0–M6）；林晚母版脸 `assets/characters/lin_wan/lin_wan.png`（AI 生成，face_reference.json） | 项目方 / 资产会话；人物表中文外貌句是配角底板的文字来源（GAP E2） | ns_render/refs.py `face_plate`、`_manifests` |
| 单品（衣橱） | data/looks/wardrobe.json items（槽位 SLOTS、keywords、trigger、图片版本） | 造型行的单品名对上 `name`；`新：` 单品由资产生成新建 | ns_agent/looks.py `Wardrobe`；asset_edit（asset_id = 单品 id） |
| 造型（look） | data/looks/looks.json：命名造型 = 一组槽位单品 | 资产编辑存为新造型 | looks.py `LookStore.upsert_look` |
| 排期 | data/looks/schedule.json：角色默认造型 → 每集集计划（evidence、needs_review）→ 本镜覆盖；`look_confirmed` 项目方确认 | **今后由剧本造型行生成集计划**（`seed` 读 `Episode.looks`），项目方确认后注入 | looks.py `seed`、`confirm_episodes`、`Resolver.layers` |

**image2img 生成**（asset_edit `plan_gen` / `run_gen`，契约 §E W5 ⑦）：
1. 输入：`base`（底图：ref_id / "current" / 路径，可省）+ `refs: [{ref_id, role}]` + `prompt` + `strength`（small / medium / large → denoise 0.35 / 0.55 / 0.75，`frame_edit.EDIT_DENOISE`，或 0–1）。
2. 参考图带**用途标签** role ∈ identity（取人物 / 脸）、item（取这一件）、style（取风格）、color（取色彩）；排列：图1 = 底图，其后按 `ROLE_ORDER` identity → item → style → color。
3. 有底图 = init_image + denoise；无底图 = 纯多参考编辑。输出 1088×1920（`GEN_SIZE`）。
4. 存版本（`POST /api/assets/{id}/versions`）：默认**新建资产** `<asset_id>-vN`（原资产不动、不让镜头过期）；`in_place:true` 才在原资产上加版本（用到它的镜头过期）。人物 slug 不能存版本。

**定稿与一致性规则**

| 编号 | 规则 | 由谁执行 |
|---|---|---|
| AS-1 | 每集每个在画角色的造型 = 剧本造型行（槽位逐字）；项目方确认（`looks confirm`）前编译器只注入画布换过的槽位 | compiler `look_fragments(confirmed_only)` |
| AS-2 | 同一集内同一角色造型不变，除非有 `造型｜…｜镜N起`；换装镜之后用新造型 | looks `Resolver`（待接 `Episode.looks`） |
| AS-3 | 身份参考每人每镜只带 1 张身份底板（不用成品定妆图：会照搬姿势 / 服装 / 背景，research v6） | refs.py `REF_MODE="plate"` |
| AS-4 | 参考图总数：代码 `MAX_REFS = 4`（Qwen 上限），RA A6“出图调度”写 ≤3 张。**以代码 4 张为上限**；RA 那句在第五部分 2.2 改成“≤4（人物底板 + 单品 + 场景底图）” | refs.py |
| AS-5 | 身份 LoRA 与参考同时用：林晚 `lin_wan_qi_v1` 0.8 + 身份底板；触发词 LoRA 同图合计强度 ≤1.6（RA A6） | compiler、gpu3 LORA_REGISTRY |
| AS-6 | 配角（无角色锁）第一次出场前，人物表必须有六项中文外貌句，才能生成多角度底板（SOP §4） | QW-P6 + 资产页“缺底板”提示 |

## 2.2 场景

| 项 | 规则 | 代码 |
|---|---|---|
| id | `sk_<小写英文数字下划线>`，全剧唯一，剧本场景表定义；与 data/scenes.json、assets/scenes/<id>/ 同一套 | importer `SCENE_ID_RE`；state_timeline `_apply_script_scenes` |
| 底图（plate） | **空场景**：生成提示词只用场景表的 空间描述 + 时段 + 光线 + 固定陈设（QW-SC8 保证无人物）；9:16 | 场景资产生成（S2，复用 asset_edit 流程，kind = scene，**S-back 进行中**；前端 scenes_api.ts 已按 `GET /api/assets/scenes`、`/api/assets/scenes/{id}` 调用） |
| 变体 | 同一场景的机位 / 时段变体存 manifest `variants{stem: {file…}}`，stem = `plate_<variant>`；剧本场景表一行 = 一个主时段，其它时段作变体 | ns_render/scene_plate.py |
| 定稿 | manifest `locked{by, at, sha256, version, variant, file}` / `locked_variants`；或项目方确认 `owner_confirmed_at/ref + plate_sha256`。“已定稿” = 记录 sha = 文件当前 sha（换了图自动退回 candidate） | scene_plate `lock_record`；state_timeline `plate_info` |
| 跨集复用 | 同 id 跨集描述逐字相同（QW-SC5）；后面的集只引用 id，不重写；底图跨集共用一张定稿 | importer `build_scene_library` |
| 参考用途 | 场景参考 role：空间 / 风格 / 色彩 / 道具（TODO §6 S2）；进首帧时用途说明固定为 `图{i}只取场景空间与陈设，不取人物。`（refs.py `ROLE_SCENE`） | refs.py |

## 2.3 道具

- 现状：资产系统没有道具类型（asset_edit 只有 单品 / 造型 / 人物）。规则：常驻道具写进场景表“固定陈设”（1–3 件，物件 + 数量 + 材质颜色），本镜道具状态写在 `**场景**` 行细节里；角色随身物件写进造型行“饰品”或“其他”槽。
- 道具独立资产（kind = prop，id `pr_*`，图片版本 + 用到的镜头）属**建议项**（GAP B9/E4），等场景资产 S2 落地后再加，不阻塞本版。

## 2.4 三层参考解析（集 → 场景 → 镜头）

解析顺序（契约 §E W5 ②）：默认造型 → **集计划**（schedule，项目方确认）→ **场景层**（`episode_edit.json scene_overrides[<scene_id>]`）→ 本镜覆盖（schedule）→ **画布本镜**（`edits.json ref_overrides`）。

- 每层只记与下一层不同的部分；只能选已有资产（造型 / 单品 / 场景底图），否则 422。
- change：`{characters: {<slug|中文名>: {look?, parts?: {slot: item_id|null}, reset?}}, scene?: plate_id|"none"|"inherit", reset?, copy_from?}`；给 look 不给 parts = 整套换掉；`null` = 该件恢复继承。
- 范围 scope = shot / scene / episode；episode 必须 `by=owner`，会撤销该人物本集造型确认（`look_confirmed:false`），且不能改底图。
- 应用前 preview 返回 affected（解析会变的镜头）/ stale（其中已有版本的）/ continuity_warnings（`look_differs` / `plate_differs`，与同场景上一镜比）。
- 场景 id 的来源：剧本写了 `**场景**` 就用剧本 id；否则 state_timeline `group_scenes` 推断（旧剧本）。
- 代码：services/api/ns_api/ref_switch.py、services/agent/ns_agent/looks.py `Resolver.layers/scene_of/canvas_slots`、ns_render/scene_plate.py `shot_plate`。

## 2.5 参考与 LoRA 怎样进入 Image 2.1 任务

1. 编译（compiler `compile_shot`）：
   - 入镜角色（今后以人物行为准，现为 `present_characters` 关键词判定）→ `identity_triggers`：林晚 → `lnwan_qi` 放在所有触发词最前；本机 / gpu3 有 `lin_wan_qi_v1.safetensors` 时进 `image_loras`，强度 0.8。
   - img 开头的其它触发词按触发词表配 LoRA（强度缺省 0.8）；文件不存在则去掉触发词、保留描述（`dropped_triggers`）。
   - 首帧提示词 = 触发词 → 角色锁 → 造型片段 → img 正文 → 纠正器条目（特写、暗场、安全镜）→ 材质条目（鞋跟、漆皮、脚趾甲）→ 导演加强 → 镜头词 → 风格后缀（`image_suffix` 或 visual_bible fallback）。**场景段**：TODO §6 S3 要求把场景表这一行 + 本镜场景细节并入（目前编译器尚未实现，第五部分 4.3）。
2. 参考计划（refs.py `RefPlan`）：身份底板（face）→ 单品（look / nails / shoes）→ 场景底图（scene，最后）；每张的用途说明（`ROLE_FACE` 等）拼在提示词最前，结尾 `画面内容完全按以下描述：`。
3. 工作流（workflows.py）：有参考 → `qwen_edit`（多参考，图1、图2…）；plate 模式有身份底板 → 两段式（`qwen_two_stage`）；无参考 → `qwen_t2i`。LoRA 一律 `LoraLoaderModelOnly` 串在 UNET 后。Turbo：官方 8 步 sigma、cfg 1.0、euler；尺寸 768×1344。
4. 负面（K12）：`image_negative` 仍拼（基础负面 + 风格负面 + 安全镜负面），**CFG=1 下是否生效待实测**，不依赖。

## 2.6 过期（staleness）规则

| 触发 | 过期对象 | 记录 | 代码 |
|---|---|---|---|
| 定稿首帧换版本 / 取消定稿 | 本镜尾帧、视频 | takes.json `stale:{last?, video?}:{reason, at, first}`；新尾帧（`from_first == locked.image`）自动清 stale.last | frame_edit `lock/unlock` |
| 定稿尾帧换版本或文件 sha 变 | 本镜视频 | 视频 take `stale_reasons`：“定稿尾帧已换” | h3_video `stale_reasons` |
| 场景底图换版本 | 用到它的首帧 | take.scene_plate（含 sha）≠ 当前 → “场景底图已改” | scene_plate `stale_reasons` |
| 参考切换 apply | preview 的 stale 列表 | 镜头造型哈希 / 底图变化 | ref_switch `preview/apply` |
| 资产 in_place 新版本 | 用到该资产的镜头 | affected | asset_edit `save_version` |
| 剧本 `**H3提示词**` 改了 | 项目方 H3 覆盖失效（不再使用） | `h3_prompt_override.script_sha` ≠ 当前 h3 sha | h3_video `resolve_prompt` |
| visual_bible 改了 | 编译结果（bible_version 不同） | take.bible_version | compiler |
| 造型行改了（新） | 本集用到该角色的镜头首帧；集造型确认作废 | looks 确认哈希 `confirmation_hash` | looks.py |

---

# 第三部分 视频生成逻辑

## 3.1 顺序（闸门）

首帧（出 → 审 → 定稿）→ 尾帧（**只能由定稿首帧编辑**，首帧未定稿 409）→ 定稿尾帧 → H3 FL2VA（首尾帧都定稿且尾帧未过期，否则 409 `{missing:[first|last]}`，`frame_edit.frames_ready`）→ 审视频 → 不满意改参数重渲 → 定稿视频 → 后期装配。

## 3.2 首帧与尾帧

| 项 | 规则 | 代码 |
|---|---|---|
| 首帧 | 编译后的 image_prompt + 参考计划（§2.5）+ 场景定稿底图（`SCENE_PLATE_REFS=True`）；画布出图每任务 1 张、不评分 | ns_render/pipeline `render_image`；frame_edit `regen` |
| 接力首帧（新） | 衔接 = 接力 时，上一镜**定稿尾帧**作 图1（底图）编辑出本镜首帧（R §6A“系统会用上一镜尾帧编辑出下一镜首帧”）；同场换机位 / 换场照常出 | 待实现（第五部分 4.4） |
| 尾帧 | `last_prompt` = `LAST_FRAME_KEEP`（“图1是本镜头的首帧画面。保持图1的场景、机位、景别、光线、人物身份、发型与服装完全不变…只把画面改为这个镜头动作结束时的瞬间：”）+ 结束状态 + 角色锁 + 造型片段 + 首帧同一套规格词；定稿首帧作 图1（768×1344 预缩放），向首帧调色 | compiler `last_prompt`；pipeline `render_last_frame`；frame_edit |
| 改图三法 | regen（整张重出）/ instruct（父版本作图1 + 底图，denoise 按幅度）/ refs（父版本 + 新参考；给幅度时同 instruct） | frame_edit `edit_frame`、`EDIT_DENOISE` |
| 尾帧另两种来源 | 视频版本抽帧（`from_stage:"video"`）或 gpu3 链（`chain:"gpu3"`）登记成 stage=last 新版本并定稿 | frame_edit `lock_last_from` |
| 首尾一致性 | 同景别族、同光、同机位族、同服装；景别差 ≤1 档（写作侧 QW-K2 保证）；两帧同法 center-crop + lanczos 到 768×1344（P-B2） | h3_video `keyframe_file` / 图内 ImageScale |

## 3.3 H3 提示词组装（优先级）

1. 请求里的 `prompt_override`（本次重渲临时提示词，source=`request`）；
2. 项目方覆盖 `edits.json h3_prompt_override`，且未过期（`script_sha` = 当前剧本 H3 的 sha，source=`owner_edit`）；
3. 剧本 `**H3提示词**` 原文（source=`script`）；配乐字段按 `resolve_music`：本镜人工 > 剧本 H3 自带（含明确 N/A）> 【配乐】强度 0 / 撤到静默 → N/A > 本集【BGM】英文（须过 H3-S3，否则 N/A）> N/A；
4. 剧本没写 H3 时的系统拼接（source=`laptop`，旧剧本兜底）。
- 对齐句：时长改了时只把第一行系统对齐句按新帧数重算（`realign`），其余一字不动。
- 中文（【配乐】后期提示、中文 BGM、video_negative、VIDEO_STYLE）都**不进** H3。

## 3.4 帧数与参数

| 参数 | 值 | 来源 / 代码 |
|---|---|---|
| 帧数 | §1.4 表，17k+5，107（K4 后）–362；24 fps | h3_lint `frames_for_seconds`；P-B1、P-B3 |
| 时长来源 | 请求 `seconds` > 剧本 `**时长**`；**剧本没写 = 报错**（K4，去掉 `or 10` 兜底） | h3_video `shot_seconds`、h3_prompt.py:167/189/215 |
| 分辨率 | 768×1344（9:16） | P-B3 |
| DiT | `minimax_h3_fl2va_pruned_int8_convrot.safetensors`（不用 w4a8：LoRA adaln_proj 失效） | workflows `H3Model` |
| 文本编码器 | `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors` | 同上 |
| VAE | 视频 `minimax_h3_video_vae_int8_convrot.safetensors`；音频 `minimax_h3_audio_vae_fp32.safetensors`（必须 fp32） | 同上 |
| Turbo LoRA | `minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16.safetensors`，强度 1.0（低 → 暗，高 → 过曝；可在重渲时改） | 同上 |
| 步数 | 8（Turbo ≥ 6，`check_h3_model`）；升级档 H3_BASE：无 LoRA、20 步 | 同上 |
| shift | (6, 3)（768p Turbo）；无 Turbo / 544p → (12, 3)；按 LoRA 自动配对（`expected_shift`） | 同上 |
| 采样 | euler / simple（不用 ancestral / SDE：音频破音）；cfg 1（BasicGuider，无负向分支） | 同上；P-A2、P-A6 |
| 种子 | 请求给定；否则 `seed_for(shot_id + "/v", n)`（确定性） | h3_video `render` |
| 额外视频 LoRA | motion 开头触发词（视频 LoRA 表）→ `video_loras`，同样按配对规则算 shift | compiler、workflows `h3_fl2va` |
| 禁用节点 | EasyCache、LazyCache、MiniMaxH3Cache、Spectrum*、TeaCache、CacheDiT、SolAttention、TorchCompileModel… | workflows `H3_BANNED_NODES`（P-A7） |
| 中间关键帧 | `MiniMaxH3AddGuide` 只在需 A/B 的难镜用；写作侧暂无字段（GAP B10 建议项） | SOP §9A.3 P-A8 |

## 3.5 音频与配乐

- H3 原生音频：overall_soundscape（= 【H3 audio】）+ `<d>` 台词 + non_diegetic_music。
- 普通对话镜只 (S1)；亲密镜只林晚发声（H3-D7）。
- 🎙 独白：后期 TTS，声线 = 该角色 VOICE（今后从人物表取；现为固定林晚声线）。
- 后期：每集 BGM；H3 已带配乐的镜头装配时不再叠 BGM（`ns_post.music.h3_music_shots`）；中文 sound / 【亲密声】给后期拟音。

## 3.6 审片 → 改参数重渲

- 每版视频 = take（stage=video）：`params` 记 seed、steps、seconds、frames、lora_strength、prompt_source、prompt_override、首尾帧 {n, file, sha}、模型全名、shift、render_s、upload_s、显存峰值；`parent` 默认 = 当时的当前视频版本（版本链）；`from_first`。
- 可改：种子、步数、时长（帧数）、Turbo LoRA 强度、提示词覆盖（`POST /api/shots/{id}/video-jobs`）；对比：`GET /api/shots/{id}/video-takes`（含过期原因）。
- 去重键（SOP §9）：sha256(首帧) + sha256(尾帧) + 提示词哈希 + 参数；同键不重渲。
- 过期：§2.6。视频不评分、不做内容检测。

## 3.7 装配与后期

- 4K 放大（2160×3840，时序一致视频超分）→ 混音（Foley −6..−10 dB、独白处场景 −8..−12 dB、母带 −14 LUFS / −1 dBTP）→ `tools/assemble_episode.py`：0.3 s 交叉溶解 + 片尾字卡（F3 待定）→ 1080×1920 与 2160×3840 两版（SOP §11–§13）。
- 实际片长以 H3 输出为准（S.SS），不按剧本秒数裁切。

---

# 第四部分 本地实现

## 4.1 机器与卡

| 位置 | 用途 | 进程 / 端口 | 状态 |
|---|---|---|---|
| gpu3 GPU0（RTX 3090） | **出图卡**：Image 2.1 Turbo（首帧、尾帧、改图、资产、场景底图） | ComfyUI :8188 | 在用 |
| gpu3 GPU3（RTX 3090） | **视频卡**：MiniMax H3 FL2VA | ComfyUI :8191（`--cache-none`，见 §0.1 P-A7） | 在用 |
| gpu3 GPU1（RTX 3090） | Qwen LLM（:8098、qwen-agent） | — | 待项目方确认后停用 |
| gpu3 GPU2 | — | — | 损坏，不调度 |
| 笔记本 | API ns_api :8800、前端 :5173、编译 / 导入 / 校验、TTS、混音、装配 | — | — |

## 4.2 模型文件

| 卡 | 文件 |
|---|---|
| GPU0 出图 | UNET `qwen_image_2.1_turbo_int8_convrot.safetensors`；文本编码器 `qwen3vl_8b_int8_convrot.safetensors`；VAE `qwen_image_2.1_vae_bf16.safetensors`；身份 LoRA `lin_wan_qi_v1.safetensors`（0.8）；其余 LoRA 按 gpu3 `LORA_REGISTRY.json`（status=accepted） |
| GPU3 视频 | §3.4 表中 DiT / 文本编码器 / 两个 VAE / Turbo LoRA |

## 4.3 网络与上传

- 笔记本经跳板机 SSH 隧道：`127.0.0.1:18188 → gpu3:8188`（出图）、`127.0.0.1:18191 → gpu3:8191`（视频）；另有 15180 渲染桥、18099 信箱。地址存 config/render_endpoints.json，`PUT /api/render/endpoints/{id}` 改了立即生效；解析优先级：该文件 image/video 的地址 > 环境变量 `NS_COMFY_URL_GPU<n>` / `NS_COMFY_URL` > gpus 表 > 内置默认（jobs.comfy_url）。
- 上行只有 8–25 KB/s，所以**尽量不上传**（comfy_client 模块头，F1）：
  1. 下载输出时按内容 sha256 记进 RemoteIndex（take.remote）；之后同一实例要用这张图，LoadImage 直接写 `subfolder/name.png [output]`，需要缩放的在图里补 ImageScale；
  2. 两个 ComfyUI 实例输入目录共用：上传前先查输入目录有没有同内容文件，有就跳过；
  3. 真要上传：不透明图转 JPEG q95、按 sha 命名、超时 ≥ 900 s；
  4. 提交时 LoadImage 报文件没了 → 自动改上传再提交一次；
  5. 视频首尾帧先本地 center-crop + lanczos 到 768×1344（按 sha 缓存在 data/renders/_h3_keyframes/）；
  6. 下载视频遇隧道抖动重试 3 次（prompt 已跑完，不重渲）。

## 4.4 任务队列

- services/api/ns_api/jobs.py：**每张卡一条道**（道 0 = GPU0，道 3 = GPU3），每道一个后台线程**串行**；出图（frame-jobs）、资产生成（asset_gen）、视频（video-jobs）都用 `submit()`，不另建队列。
- 状态 queued / running / done / failed / cancelled；`GET /api/jobs/{id}`、`POST /api/jobs/{id}/cancel`（只中断自己的 prompt）。
- 持久化：`data/jobs/v1/<id>.json`（入队、开跑、拿到 prompt_id、结束、取消时写）；API 重启时未完成任务标 `failed`、`error:"API 重启中断"`、`interrupted:true`。
- ETA：同类同卡最近 5 次完成任务耗时中位数；无历史时视频 840 s、出图 70 s。
- ComfyUI 连不上（ComfyUnavailable）：不重试、不换种子，整批停。

## 4.5 实测耗时（2026-10-30/31，3090，经跳板隧道）

| 步骤 | 耗时 |
|---|---|
| 首帧 | 55–140 s（GPU 本身约 15–95 s，其余是传输） |
| 指令改图 | 63–76 s |
| 尾帧 | 133–161 s |
| H3 视频 6 s（158 帧） | 12–14 min / 版（`--cache-none` 每版重载模型；去掉需项目方同意） |
| 写作 1 集（7 镜） | 约 43 s、约 $0.04（abliteration large-flash） |

## 4.6 语言模型配置

- config/llm_providers.json（无密钥）：服务商 abliteration（`https://api.abliteration.ai/v1`，large-flash / large-v2）、deepseek、minimax（后两家未配 key）；用途 purposes：script_write（剧本写作）、script_repair（格式返修）、director_boost（导演加强）、lora_llm（LoRA 打标 / 规划）、prompt_rewrite（首帧提示词改写），现全部 = abliteration large-flash（K9 待统一）。
- 密钥：环境变量 `key_env`（如 `ABLITERATION_API_KEY`）> `config/llm_providers.local.json` > 旧文件 `key_files`（`config/abliteration.local.json`）；接口只回 `has_key`，错误信息里的密钥替换为 `***`；`*.local.json` 已 gitignore。
- 每处 ⚙ 覆盖：请求带 `llm:{provider?, model?, params?}`，只改这一次。推理开关按各家官方 `reasoning_body`；不支持的模型不发字段并提示。费用估计：单价读 abliteration `/models`，拿不到 = 未知。
- 代码：services/api/ns_api/llm_config.py（`resolve`、`chat_request`、`complete_text`）。

## 4.7 什么在哪里跑 / 已知限制

| 任务 | 在哪 |
|---|---|
| 写作、返修、导演加强 | 笔记本 API → 云端 LLM（llm_config） |
| 导入、校验、编译、时间线 | 笔记本（确定性，不出图） |
| 首帧 / 尾帧 / 改图 / 资产 / 场景底图 | gpu3 GPU0（道 0） |
| H3 视频 | gpu3 GPU3（道 3） |
| TTS、混音、装配 | 笔记本；BGM / 分层 / 4K 在 gpu3（SOP §11–12） |

已知限制：局部重绘（蒙版）未实现；跨实例输出不能 `[output]` 引用时仍要上传一次；“我是项目方”只是界面勾选 + 请求字段，无身份鉴权（API 只听本机）；4 秒镜头画质未实测；负面词在 CFG=1 下效果未实测（K12）；img 长度上限未实测（C2）；编译器尚未把场景描述并入首帧（S3 文字部分）；场景资产后端 S2 进行中。

---

# 第五部分 落地计划（按顺序；每步测试全过再进下一步）

> 顺序原则（GAP 末节）：导入器不认识的标签会落进 extras，所以**先改导入器**，再让写作模型开始写新字段。

### 1. 导入器与数据结构（先做）
1.1 packages/schema/ns_schema/script.py：`ScriptGlobals.character_registry: list[CharacterEntry]`（name, char_id, zh, en, voice, defined_in, conflicts）；`Episode.cast / scene_ids / looks`；`Shot.cast / link / link_carry`；`Shot.duration: int | None`（去掉默认 10，注释改 4–15）；script.py:100 注释改 cue 词表（K2）。
1.2 services/agent/ns_agent/importer/script_md.py：把 `scene_tables` 泛化为通用登记表解析，新增 `全剧人物表 / 本集人物表`；解析 `**出场人物**`、`**用到的场景**`、`**造型｜…**`（含 `｜镜N起`）、`**人物**`、`**衔接**`、🎙 括号角色名；`MIN_SHOT_SECONDS = 4`；时长缺失 → None + 警告；`SHOTS_PER_EPISODE / EPISODE_SECONDS` 警告按 K1；保留旧标签兼容（`负面追加` 等）。
1.3 tests：tests/test_scenes_s1.py 同风格新增人物表 / 造型 / 人物行 / 衔接行用例；旧剧本导入哈希不变。

### 2. 规则与契约文件
2.1 config/script_chat_rules.md：新增“2P 人物表与集头”“2C 每镜人物 / 衔接”两节（格式同 §1.1–1.3）；时长 4–15 + 帧表；外貌短语拆为 EN + 造型 EN；static shot；“H3 限制 → 写法”汇总一节（GAP D2，只引用已有规则号）；注明 K10 有意偏离、D4 有意不用 Shake/POV/Roll。注意 ≤6000 token 预算，超出部分移到附录。
2.2 config/script_chat_rules_appendix.md：:27、:69 改 K6；:65 声线改为人物表 VOICE；A6“参考图 ≤3”改 ≤4（AS-4）。
2.3 docs/qwen_writing_contract.md：模板加新字段、删 :48 负面追加；:46/:60/:61（K1）、:117（K14）、:120（K8）、:125（K4）、:134（K2）、:145（K7）、:176（K13）。
2.4 config/qwen_writer_system_prompt.txt：:7、:13、:14、:23、:25 同上。
2.5 docs/SOP_production.md：:133（K3）、:181/:185 表、:220、:339（K4）。

### 3. 校验器
3.1 tools/validate_qwen_script.py：RULE_TEXT 加 QW-G1/G2、P1–P6、SC7/SC8、E4–E7、CH1–CH5、LK1–LK3、C4、K1–K3、M1、D1、D2、IMG-C2；改 QW-E2/E3（K1，:56–57、:281–287）、S1-W2（4–15，缺失 block，:65、:188–190）、QW-C1（static shot，:59、:128）；新开关 `REQUIRE_V3`（严格模式置 True，旧剧本降 warn）。
3.2 tools/validate_script_strict.py：`ESCALATE` 加 QW-C1/C2/C3 已有；新规则按 §1 级别；`REQUIRE_V3=True`。
3.3 packages/schema/ns_schema/h3_lint.py：`MIN_FRAMES = 107`；H3-A11 文案 4–15；H3-A12 改 block；新增 H3-X1（需要传入登记表与造型）、H3-X2、H3-X3；P-B1 下限同步。services/render_router/ns_render/workflows.py:34 `H3_FRAMES_MIN = 107`、注释改 4–15 s。
3.4 测试：每条新规则至少一个通过、一个失败用例。

### 4. 编译器与下游消费者
4.1 services/agent/ns_agent/compiler.py：`present_characters` 有人物行时直接用人物行（在画 + 局部），无则沿用关键词判定；`look_fragments` 读当前造型（含镜N起）。
4.2 services/agent/ns_agent/looks.py：`seed` 从 `Episode.looks` 生成集计划（取代“服装/鞋未设”），wardrobe 名称匹配，`新：` 单品建候选；造型行变化 → 集确认作废（AS-1/AS-2）。
4.3 compiler：首帧提示词并入【场景】段（场景表一行 + 本镜场景细节，TODO §6 S3 文字部分）。
4.4 ns_render/pipeline.py + frame_edit.py：衔接 = 接力 时首帧以上一镜定稿尾帧作 图1 编辑（§3.2）。
4.5 services/agent/ns_agent/state_timeline.py：分段以 `Shot.link` 为准；:68 去掉“转场”（K11）。
4.6 services/render_router/ns_render/h3_video.py:161、services/agent/ns_agent/h3_prompt.py:167/189/215：去掉 `or 10`，缺时长报错（K4）。
4.7 ns_post TTS：🎙 声线按人物表 VOICE。
4.8 场景资产 S2（S-back）：`/api/assets/scenes*`，空场景底图生成提示词只取场景表文字（§2.2）。
4.9 画布：审片行 / 精修显示人物行（位置）、衔接线（接力 / 换场）、造型行、人物表；剧本创作页显示人物表与场景表（canvas-ui-spec-v3 §2、§4、TODO §6 S4）。

### 5. 验收
5.1 用 large-flash（或 K9 定下的模型）按新规则写 1 集 → 严格校验 0 block → 导入 → 首帧 / 尾帧 / H3 一镜全链路；记录 4 秒档、IMG-C2 长度、K12 负面词的实测结果回填本文件 §0。
5.2 全量测试、tsc；CHANGELOG 记一行。
