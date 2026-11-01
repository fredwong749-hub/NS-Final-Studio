# Qwen 剧本写作格式契约（qwen_writing_contract）

> 版本：`qwen_contract/v1` + v3 字段（2026-10-31，fredw-92/R3，按 `docs/production_rules_v3.md` 落地：人物表、集头出场人物 / 用到的场景 / 造型、每镜人物 / 衔接；K1 镜数与总时长、K4 时长 4–15 必写、K14 static shot）。维护：Claude（只管格式与校验，REQUIREMENTS G：内容一律由 Qwen 写）。
> 本文件只规定**格式**：字段、标签、顺序、可解析性、机检规则。所有 `<…>` 尖括号内容都是格式占位符，不是剧情文本。
> 依据（按实际代码，不按愿望）：导入器 `services/agent/ns_agent/importer/script_md.py`、数据结构 `packages/schema/ns_schema/script.py`、
> H3 机检 `packages/schema/ns_schema/h3_lint.py`、画布解析 `services/api/ns_api/shotinfo.py`、`docs/SOP_production.md` §6（S1-W1–W9）与 §9A、
> `docs/audit/rule_ids.md`、官方指南 `docs/h3_prompt_guide_base_en.txt`。
> 校验器：`tools/validate_qwen_script.py`（见文末）。
>
> **2026-10-30 项目方新规（覆盖 SOP §9A / H3-S3 旧写法“固定 N/A”）**：`non_diegetic_music` 进入 H3 提示词——
> 本镜有配乐时写 1–3 句英文，只写乐器、速度、节奏、强弱变化，不写抽象情绪词；本镜没有配乐时才写 `N/A`。

规则编号：有 `rule_ids.md` 编号的直接用（block/warn 同该表）；没有编号的用本契约本地编号 `QW-*`。

---

## 1. 整体结构

一份剧本 = 全局头（角色锁、统一后缀、触发词表，由剧本维护方给定，Qwen 不改）+ 若干集。Qwen 每次输出**一集**，结构固定：

~~~text
## ep<NN>《<集标题>》<可选：🔴 或标签>

**剧情**：<一句话剧情>

**出场人物**：<角色名>、<角色名>

**用到的场景**：sk_<id>、sk_<id>

**造型｜<角色名>**：服装=<…>｜鞋=<…>｜妆=<…>｜发=<…>｜甲=<…>｜饰品=<…>｜EN=<English outfit phrase>

**造型｜<角色名>｜镜<N>起**：<只写变了的槽位>｜EN=<English outfit phrase>

**配乐**：<本集配乐中文说明>；【BGM】<English BGM prompt for the music model>

**本集人物表**：
| 角色 | 角色id | 中文外貌句 | EN外貌短语 | VOICE声线短语 |
|---|---|---|---|---|
| <角色名> | <slug 或 ch_<id>> | <六项｜分隔 或 系统锁> | <English identity phrase> | <English voice phrase> |

**本集场景表**：
| 场景id | 名称 | 空间描述 | 时段 | 光线 | 固定陈设 |
|---|---|---|---|---|---|
| sk_<id> | <名称> | <空间描述> | <时段> | <光线> | <固定陈设> |

**镜1｜img**：<首帧画面中文提示词>
**场景**：<场景id>｜<本镜场景细节>
**人物**：<角色名>（在画｜<左/中/右>｜<前/中/后>）、<角色名>（画外）
**衔接**：<接力 / 同场换机位 / 换场 / 接上一集>｜承：<延续项>
**motion**：<视频动作中文提示词>
**时长**：<N>秒
**sound**：<中文声音原文>；【亲密声】<可选>；【配乐】<动作>，强度<0–3>，<避让>；【H3 audio】<English soundscape>
**对白**：（<角色名>，<语气/画外标记>）“<台词>”／（<角色名>，<…>）“<台词>”
**🎙（<角色名>，<说明>）**：<内心独白>
**H3提示词**：
```text
<四块 FL2VA 全文，见 §4>
```

**镜2｜img**：…
…（6 ≤ 镜数 ≤ max(8, 说话轮次 + 独白段数, ⌈总时长 ÷ 6⌉)）

---
~~~

`**本集人物表**` / `**本集场景表**` 只在本集有新角色 / 新场景时写，否则整段省略。旧标签 `**负面追加**` 已作废（K3，不要写；导入器仍认旧剧本里的这个标签）。

### 1.1 集级规则

| 编号 | 规则 |
|---|---|
| QW-E1 | 集标题行逐字为 `## ep<数字>《<标题>》`，书名号必须是全角 `《》`；数字可补零。标题后可跟 `🔴`（高强度集）或标签。 |
| QW-E1 | `**剧情**：` 一行，非空。 |
| R-C1 | `**配乐**：` 必须写在**镜1 之前**（写在某镜之后会被导入器当成该镜的附加字段，画布看不到本集 BGM）。行内必须有 `【BGM】` 段，后接英文 BGM 提示。 |
| QW-E2 | 镜号从 1 连续递增；镜数 6 ≤ n ≤ max(8, 说话轮次 + 独白段数, ⌈总时长 ÷ 6⌉)（K1，block）。 |
| QW-E3 | 各镜 `**时长**` 之和 60–120 秒通过，超出 block（D-SCR-08，项目方 11-01）。 |
| — | 集与集之间用单独一行 `---` 分隔。`# ` / `## ` 开头的其它标题会终止当前集，集内不要写额外标题。 |
| QW-SC4 | `**本集场景表**`（有本集新场景时）写在 `**配乐**` 之后、镜1 之前，格式见 §1.2。 |
| QW-E4 | `**出场人物**：` 顿号分隔；每个名字已登记（人物表或角色锁）；集合 = 本集各镜 `**人物**` 行里所有角色（block）。 |
| QW-E5 | `**用到的场景**：` 顿号分隔；每个 id 在场景表里；集合 = 本集各镜 `**场景**` 的 id（block）。 |
| QW-E6 | 本集任一镜“在画 / 局部”的角色都有 `**造型｜<角色名>**：` 行；槽位名只用 服装 / 鞋 / 妆 / 发 / 甲 / 饰品 / 其他 + `EN`，写成 `槽位=值`，`｜` 分隔；服装、鞋、妆、发、EN 必填；EN 无中文、无否定词、无双引号（block）。单品值：已有单品照抄 `data/looks/wardrobe.json` 的名称，新单品 `新：<颜色+款式+材质>`，与上一集相同 `沿用`（QW-E6b warn：名称对不上衣橱）。 |
| QW-E7 | 换装行 `**造型｜<角色名>｜镜<N>起**：` 只写变了的槽位 + 换装后完整 EN；镜N 必须存在（block）；镜N 的 img 备注或 motion 写明换装（warn）。 |

**v3 字段的兼容规则**（与 S-back 场景规则同一机制）：导入关口（`validate_qwen_script.py`）在剧本里一个 v3 字段（人物表、出场人物、用到的场景、造型、人物、衔接）都没有时，这些规则整段不查（旧剧本照常导入）；写了任一 v3 字段 = 声明 v3 格式，按上表级别查。剧本创作严格校验（`validate_script_strict.py`）总按上表级别查。

### 1.2 场景表（S1，2026-10-31 新增；fredw-92/S-back）

场景表登记本剧用到的每个场景，供场景底图资产、首帧提示词【场景】段和跨集一致性使用。两处可写，格式相同：

- **全剧场景表**：写在全局头（第一个 `## ep` 之前），由剧本维护方给定，写作模型不改；
- **本集场景表**：写在集内 `**配乐**` 之后、镜1 之前，**只登记全剧场景表和前面各集都还没有的新场景**；没有新场景时整段省略。

~~~text
**全剧场景表**：
| 场景id | 名称 | 空间描述 | 时段 | 光线 | 固定陈设 |
|---|---|---|---|---|---|
| sk_<id> | <名称> | <空间描述> | <时段> | <光线> | <固定陈设> |
~~~

| 编号 | 级别 | 规则 |
|---|---|---|
| QW-SC4 | block | 标签行逐字 `**全剧场景表**：` / `**本集场景表**：`（单独一行）；下一行（可空一行）是表头，逐字 `\| 场景id \| 名称 \| 空间描述 \| 时段 \| 光线 \| 固定陈设 \|`；再下一行是分隔行 `\|---\|---\|---\|---\|---\|---\|`；之后每个场景一行，正好 6 格，格内不用 `\|`（需要分隔时用 `／`），表格结束后空一行。 |
| QW-SC4 | warn | 6 格都要填；空格只提示。 |
| QW-SC2 | block | 场景 id 写成 `sk_<小写英文、数字、下划线>`，如 `sk_office_lobby`、`sk_gu_chen_bedroom`；与 `data/scenes.json` / `assets/scenes/<场景id>/` 同一套 id（已有场景沿用已有 id）。 |
| QW-SC5 | block | 同一 id 只定义一次；在别的场景表里再次出现时，各格要么留空、要么与第一次定义逐字相同（结构一致性检查，不评内容）。 |

| QW-SC8 | block | 空间描述、固定陈设两格不写人物（不出现已登记角色名、她、他）；固定陈设 1–3 件，中文逗号或顿号分隔（场景底图必须是空场景）。 |
| QW-SC9 | block | （同上）全局头 `**全剧场景表**` 里已登记的场景在本集场景表里被改写 → block，返修附原文全文。 |

字段含义（只说格式去向，内容由写作模型写）：`名称` → 资产页场景卡标题；`空间描述`、`时段`、`光线`、`固定陈设` → 场景资产描述，并原样并入使用该场景的每镜首帧提示词【场景】段（§2.7）。

### 1.3 人物表（R3，2026-10-31 新增；docs/production_rules_v3.md §1.1）

人物表是每个角色固定外貌（中文）、H3 英文身份短语、H3 英文声线短语的唯一存放处。两处可写，格式相同：全局头的 `**全剧人物表**`（剧本维护方给定），集内 `**本集人物表**`（`**配乐**` 之后、镜1 之前，只登记本集第一次出场的新角色）。

~~~text
**全剧人物表**：
| 角色 | 角色id | 中文外貌句 | EN外貌短语 | VOICE声线短语 |
|---|---|---|---|---|
| <角色名> | <slug 或 ch_<id>> | <年龄段>｜<体型>｜<发型发色>｜<服装主色>｜<标志物>｜<不可变特征> | <English identity phrase> | <English … voice …> |
~~~

| 编号 | 级别 | 规则 |
|---|---|---|
| QW-P1 | block | 标签行逐字 `**全剧人物表**：` / `**本集人物表**：`；表头逐字 `\| 角色 \| 角色id \| 中文外貌句 \| EN外貌短语 \| VOICE声线短语 \|`；分隔行；每人一行正好 5 格，格内不用 `\|`。 |
| QW-P2 | block | 角色名全剧唯一；角色id 是已有 slug（series10：lin_wan、gu_chen、chen_yu、ch_a_lan，与 `ns_schema/looks.py` CHARACTERS 同一套）或 `ch_<小写英文数字下划线>`；一个 id 只对应一个角色名。 |
| QW-P3 | block | EN外貌短语：一条英文名词短语，只写身份（年龄、性别、发色长度与刘海、脸 / 肤色 / 体型），不写服装；无中文、无否定词、无双引号、不含人名和触发词。 |
| QW-P4 | block | VOICE声线短语：英文、含 `voice`（音色、音区、语速），无否定词、无双引号；对白或 🎙 里出现的每个说话人都必须有。 |
| QW-P5 | block | 同一角色再次出现在人物表里时各格与第一次逐字相同（留空 = 沿用）。 |
| QW-P7 | block | （fredw-92 2026-10-31，全剧一份、逐集继承）全局头 `**全剧人物表**` 里已登记的角色（系统从已导入剧本 / 本批前面各集原样并入）在本集人物表里被改写 → block，返修消息附要照抄的原文全文；已登记的不再写。 |
| QW-P6 | warn | 中文外貌句恰好 6 项（全角 `｜` 分隔），或逐字 `系统锁`（有系统角色锁的角色）。 |
| QW-G1 | warn | 全局头有角色锁代码块（`**每条prompt统一前缀**`），至少一行 `【…】`。 |
| QW-G2 | warn | `**LoRA 触发词表**` 代码块只分 `图像LoRA` / `视频LoRA` 两段，trigger 是 `[A-Za-z0-9_]+`。 |

系统用法：EN外貌短语 + 造型行 EN 逐字进 H3 锚点句（H3-X1）；VOICE 逐字进说话人首次出现的描述（H3-X3），并作 🎙 后期 TTS 声线；`**人物**` 行的在画角色决定身份 LoRA 与造型注入（编译器不再按关键词猜）。

## 2. 每镜字段（标签逐字，顺序固定）

通用写法：标签用 `**标签**：值`，冒号用全角 `：`；值写在同一行，可以用一对反引号整段包住（导入器会去掉）。值里不要再用 `**加粗**`。
字段值续行会被接到上一个字段，但**空行会结束字段**——除 `**H3提示词**` 外，每个字段写成一行。

| 顺序 | 标签（逐字） | 必须 | 存入 | 画布显示 | 规则 |
|---|---|---|---|---|---|
| 1 | `**镜<N>｜img**：` 或 `**镜<N>｜img（<备注>）**：` | 是 | `img_prompt`、`img_note` | 首帧提示词 | R-C1；`｜` 必须是全角竖线 |
| 1a | `**场景**：<场景id>｜<本镜场景细节>` | 是（S1） | `scene_id`、`scene_detail` | 场景小卡、首帧【场景】段 | QW-SC1/SC2/SC3/SC6，§2.7 |
| 1b | `**人物**：<角色名>（在画｜左/中/右｜前/中/后）、<角色名>（局部｜部位｜左/中/右）、<角色名>（画外）` | 是（v3） | `cast[]`（name / presence / x / depth / part） | 本镜人物、位置 | QW-CH1–CH5，§2.8 |
| 1c | `**衔接**：<接力/同场换机位/换场/接上一集>｜承：<延续项>` | 是（v3） | `link`、`link_carry` | 衔接线 | QW-LK1–LK3，§2.8 |
| 2 | `**motion**：` | 是 | `motion_prompt` | 视频/动作提示词、运镜、表情 | R-C1、S1-W1、S1-W6 |
| 3 | `**时长**：<N>秒` | 是 | `duration` | 时长、帧数 | S1-W2 |
| 4 | `**sound**：` | 是 | `sound`、`sound_h3`、`music_cue`、`sound_intimate` | 声音、本镜配乐 cue | R-C1、S1-W3 |
| 5 | `**对白**：` | 有台词时 | `dialogue` | 台词 | S1-W4 |
| 6 | `**🎙（<角色名>，<说明>）**：` | 有独白时 | `voiceover`（`speaker` = 括号第一个词） | 独白 | S1-W4、H3-D6、QW-D2 |
| 7 | `**H3提示词**：` + 代码块 | 是 | `h3_prompt` | H3提示词 | S1-W7、S1-W8 |
| 8 | `**H3校验**：` | 否 | `h3_check` | 红标 | 只由项目方/流程写，Qwen 不写 |

可选附加字段（导入器认得，挂在镜头上）：`**对白屏幕上**`、`**motion补充**`、`**口型**`、`**口型内容**`、`**字幕卡**`。其它未知标签在镜头里会进 `extras`，画布不显示，**不要自造标签**。

### 2.1 img（首帧）

- 开头可写触发词，用中文逗号连接：`<trigger>，<trigger>，<画面…>`；触发词只能用全局触发词表里的词或 `pose_<名称>`。
- `QW-C2`（warn）写出景别词，画布据此显示“景别”：大远景/远景/大全景/全景/中全景/全身/中景/中近景/近景/极近特写/大特写/特写/极近；机位词可选（低机位仰拍、俯拍、过肩、背影…）。
- 人物用剧本角色名或角色锁里的识别词写（画布据此判断“本镜人物”）；不写台词，不用双引号包台词（S1-W4；校验器对 img/motion 里的引号文字报 `QW-Q1` warn，画面里真实可见的文字可保留）。
- 不写否定词（不/无/没/别；v3 规则 V3-N1）。

### 2.2 motion（视频动作）

- 有林晚入镜：以 `lnwan01，` 开头（视频 LoRA 触发词 + 画布人物识别）。
- `QW-C1`（warn，严格校验 block）触发词之后紧跟**英文运镜指令**，再接中文运镜词，用中文逗号结束；只从 `camera push in / pull out / zoom in / zoom out / pan left / pan right / truck left / truck right / tilt up / tilt down / pedestal up / pedestal down / arc shot / tracking shot`、`static shot` 中选（K14：`static camera` 改为 `static shot`，旧写法过渡期仍认）。画布的“运镜”取自这里。`QW-C4`（warn）这里的运镜与 H3 正文的运镜是同一种。
- `S1-W6`（warn）运镜要能映射到官方词汇：Zoom In/Out、Push In/Pull Out、Pan Left/Right、Truck Left/Right、Tilt Up/Down、Pedestal Up/Down、Arc Shot、Tracking Shot、Static Shot。
- `S1-W1`（block）一个连续镜头：只有一个主动作、一个运镜；不写 切/转场/cut/剪辑；**最后一个 `——` 之后写结束状态**（= 尾帧 Picture 2 的样子）。
- `QW-C3`（warn）1–2 个可观察的表情线索短句（首选 1 个；≤28 字，含 眼神/嘴角/睫毛/呼吸/抿/笑/脸红… 之类），画布的“表情”取自这里。
- 结束状态（v3）：`QW-K1`（block）以景别词开头；`QW-K2`（block）与 img 景别最多差一档，static / pan / tilt / truck 运镜不差档（档位：大远景 < 远景 < 全景 < 全身 < 中景 < 中近景 < 近景 < 特写 < 大特写）；`QW-K3`（warn）朝向只用 背影 / 背对 / 背抵 / 后脑 / 侧脸 / 侧影 / 侧面，首尾一致（motion 写了转身除外）。
- 不写台词，不用双引号（S1-W4）。

### 2.3 时长

- `S1-W2`（block）`**时长**：<整数>秒`，4–15，每镜必写（K4：缺了 block，系统不再默认 10 秒）。超过 15 秒拆镜。帧数由系统查表（§4.2），Qwen 不写帧数字段。

### 2.4 sound（一行，四段，段名逐字）

```text
**sound**：<中文声音原文>；【亲密声】<中文，可省略整段>；【配乐】<本镜配乐 cue>；【H3 audio】<English sentences>
```

- 段标记必须是 `【亲密声】`、`【配乐】`、`【H3 audio】`（H3 与 audio 之间一个半角空格），段之间用 `；`。
- `R-C1`（block）`【配乐】` 段非空：`<动作>，强度<0–3>，<避让>`。
- `QW-M1`（v3 block）动作只用 进入 / 延续 / 渐强 / 推到高点 / 撤到静默 / 落下 / 重音（K2：不写推高、点题）；强度 0–3（省略 = 沿用上一条；撤到静默省略 = 0）；避让只用 对白避让 / 独白避让 / 无需避让；有台词必须写对白避让，有 🎙 必须写独白避让。
- `S1-W3`（block）`【H3 audio】`：1–4 句英文，一段；只写环境声、动作声、非语言人声；不写台词、不写 `<d>`、无否定词、无中文。
- `QW-S1`（warn）`【H3 audio】` 与 H3 提示词里的 `overall_soundscape` 逐字一致（画布“声音”显示的是 H3 的 soundscape）。
- `【亲密声】` 有内容即视为亲密镜：H3 里只能有一个说话人 (S1)，soundscape 不写男性声音（H3-D7 block）。

### 2.5 对白

```text
**对白**：（<说话人说明>）“<台词>”／（<说话人说明>）“<台词>”
```

- `S1-W4`（block）每句台词前都有全角括号说话人说明；台词用中文弯引号 `“ ”`；多句之间用全角 `／`。
- `QW-D1`（v3 block，K7）括号**以已登记的角色名开头**（不写 她/他），再写语气：`（<角色名>，<语气>）`。
- 画外声：括号里写 `画外` / `电话` / `语音` / `OS` / `VO` 之一（只用这 5 个；H3 里要按画外音写，见 §4.3）。
- 台词原文逐字（含标点），H3 的 `<d>` 必须与这里逐条、逐字、同顺序一致（H3-D3）。
- 无台词的镜头整行省略，不要写 `**对白**：无`（会被当成一句台词）。

### 2.6 🎙 独白

- 单独一行 `**🎙（<角色名>，<说明>）**：<独白>`。独白**不进** H3 提示词（H3-D6 block），由后期 TTS（声线 = 人物表 VOICE）。
- `QW-D2`（v3 block）括号第一个词是已登记角色名，且该角色在人物表里有 VOICE。

### 2.7 场景（S1）

```text
**场景**：<场景id>｜<本镜场景细节>
```

- 紧跟在 `**镜N｜img**` 那一行之后，一行写完；`｜` 是全角竖线，左边是场景 id，右边是本镜场景细节（本镜机位看到的部分、道具状态）。
- `QW-SC1`（block）每镜都有 `**场景**`。导入关口兼容旧剧本：整份剧本没有任何场景表和 `**场景**` 行时不报；剧本创作（严格校验）总是 block。
- `QW-SC2`（block）id 格式同 §1.2；`QW-SC3`（block）id 必须在全剧场景表或本集场景表（本集或前面各集）里。
- `QW-SC6`（warn）`｜` 之后的本镜场景细节非空。
- 系统用法（写作模型不用写）：首帧提示词自动追加一段 `【场景】名称：…；空间描述：…；时段：…；光线：…；固定陈设：…；本镜场景：…`，冒号后都是场景表 / 本行原文；首帧出图自动带上该场景的定稿底图作参考图（“只取场景空间与陈设，不取人物”）。

### 2.8 人物行与衔接行（R3，v3）

```text
**人物**：<角色名>（在画｜<左/中/右>｜<前/中/后>）、<角色名>（局部｜<部位>｜<左/中/右>）、<角色名>（画外）
**衔接**：<接力 / 同场换机位 / 换场 / 接上一集>｜承：<上一镜结束状态延续下来的 1–3 项>
```

| 编号 | 级别 | 规则 |
|---|---|---|
| QW-CH1 | block | 每镜有 `**人物**`（紧跟 `**场景**`）；每项格式如上；只列本镜入镜或发声的人；行内不写“她 / 他”。 |
| QW-CH2 | block | 名字都已登记（人物表或角色锁）。 |
| QW-CH3 | block | 在画 + 局部 ≤ 3 人。 |
| QW-CH4 | block / warn | img 与结束状态里出现的已登记角色名都在人物行（在画或局部）（block）；在画的人在 img 里写出名字（warn）。 |
| QW-CH6 | warn | 人物行写“局部”的角色，img 里不写他的脸 / 五官 / 头发；脸或头发入画就在人物行写“在画”（系统按脸可见处理：挂身份脸、Q1 按其阈值判，K-AST-236）。 |
| QW-SZ1 | warn | 特写 / 大特写只容一张脸为主体：两人都在画写近景或中近景；脸部特写不同时写鞋踩地 / 鞋尖鞋跟（要拍鞋就写鞋的特写）。出图会退成中近景、景别检查（Q3）连续不过。 |
| QW-SZ2 | warn | 局部特写（手 / 脚 / 腰…）只写这个局部：不写靠近脸的部位（肩头 / 锁骨 / 颈 / 下颌 / 胸口）和脸部写实套话；要写就写清画面上沿停在哪里（例：画面上沿在锁骨以下，不出现脸）。否则出图常拍成带脸的近景，Q3“局部特写出了脸”不过。 |
| QW-CH5 | block | 对白和 🎙 的说话人都在人物行；标“画外”的人台词括号里带画外标记。 |
| QW-LK1 | block | 每镜有 `**衔接**`（紧跟 `**人物**`）；取值四选一；镜1 只能写 换场 / 接上一集；接力必写 `承：`。 |
| QW-LK2 | block / warn | 接力 / 同场换机位：场景 id 与上一镜相同（block）；接力时 img 景别与上一镜结束状态景别最多差一档（warn）。 |
| QW-LK3 | block | 换场：场景 id 与上一镜不同，或 img 备注 / motion 写了换段词（次日、第二天、翌日、闪回、回忆、梦境、数日后、几天后、一周后、当晚、句首“周X”）。 |
| QW-SC7 | warn | img 第⑤项照抄场景表的名称或至少一件固定陈设。 |
| IMG-C2 | — | img 长度只统计（校验报告 `shots[].img_chars`），上限待实测（C2），暂不提示。 |

系统用法：人物行的在画 + 局部角色 = 编译器的入镜角色（身份 LoRA、造型注入）；衔接 = 接力时下一镜首帧由上一镜定稿尾帧编辑（待接入，production_rules_v3 第五部分 4.4）。

## 3. 画布字段对照（每镜必须能取到）

| 画布字段 | 来源 | 本契约条目 |
|---|---|---|
| 首帧 / 尾帧 | 渲染产物（img + motion 结束状态） | §2.1、§2.2 `——` 后结束状态 |
| img 提示词 | `**镜N｜img**` | §2.1 |
| 视频提示词 | `**motion**` | §2.2 |
| 时长 | `**时长**` | §2.3 |
| 剧本原文 | img 备注 + motion 动作部分 | §2.1–2.2 |
| 人物 | `**人物**` 行（v3）；旧剧本：角色名 / 识别词 / `lnwan01` | §2.8、§2.1、§2.2 |
| 造型资产 | 集头 `**造型｜…**` 行（v3，K13：今后由它生成 data/looks 集计划）；旧剧本：`data/looks/*.json` | §1.1 |
| 表情 | motion 表情线索 | QW-C3 |
| 景别 / 运镜 | img 景别词；motion 开头英文运镜 | QW-C2、QW-C1 |
| 台词 / 独白 | `**对白**` / `**🎙**` | §2.5、§2.6 |
| 声音 | H3 `overall_soundscape`（= `【H3 audio】`） | §2.4 |
| 本镜配乐 | `【配乐】` | §2.4 |
| 本集 BGM | `**配乐**` 的 `【BGM】` | §1.1 |
| H3提示词 | `**H3提示词**` | §4 |
| 场景 / 场景底图 | `**场景**` + 场景表 | §1.2、§2.7 |

## 4. `**H3提示词**`（S1-W7 必有；S1-W8 必须过全部 H3 机检）

### 4.1 字段写法

~~~text
**H3提示词**：
```text
<四块全文>
```
~~~

- 标签单独一行，正文放在 ```` ```text ```` 代码块里（导入器会去掉围栏，保留中间所有行和空行）。
- `**H3提示词**` 放在该镜最后；它之后出现的任何 `**标签**` 行、下一镜、`---` 都会结束它。

### 4.2 四块结构（逐字，H3-A1/A2/A3）

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the <S.SS>-second mark of the target video.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, <English body …> established by Picture 1 … settles into the <…> established by Picture 2 at the end of the shot.

overall_soundscape: <1–4 English sentences, one paragraph>

non_diegetic_music: <1–3 English sentences on instrumentation, tempo, rhythm, dynamics — or N/A>
```

- `H3-A1`（block）第一行逐字（含破折号 `—`）；两处都是 `Shot 1`；`<S.SS>` 按 `**时长**` 查表（`frames_for_seconds`，帧数/24 保留两位）：

| 时长（秒） | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 | 12 | 13 | 14 | 15 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 帧数 | 107 | 124 | 158 | 175 | 192 | 226 | 243 | 277 | 294 | 328 | 345 | 362 |
| S.SS | 4.46 | 5.17 | 6.58 | 7.29 | 8.00 | 9.42 | 10.12 | 11.54 | 12.25 | 13.67 | 14.38 | 15.08 |

- `H3-A2`（block）对齐句后恰好空一行；三个字段名逐字、按上面顺序、各空一行；每个字段值是**一段**（值内不换行、不空行）；不加其它字段。
- `H3-A3`（block）正文以 `[Shot 1]` 开头，只有一个 `[Shot …]`，`[Shot 1]` 后不写时间戳。
- `H3-A8`（block）`[Shot 1] ` 后紧跟 `Live-action, cinematic, shallow depth of field,`；全文不出现图像风格/画质词（8K、85mm、f/1.2、Leica、bokeh、photorealistic、masterpiece…）。
- `H3-A4`（block）第一句含 `established by Picture 1`；最后一句含 `settles into … established by Picture 2 at the end of the shot.`
- `H3-A6`（warn）正文写连接两帧的动作路径，不复述两张静帧；人物/场景锚点只写一句。
- `H3-A10`（warn）运镜写成句中自然动作，用官方词汇；幅度/速度只用 `with small amplitude` / `with large amplitude` / `at slow speed` / `at fast speed`；每镜一个运镜。
- `H3-A11`（block）时长 4–15 s；`H3-A12`（block，官方 API 硬上限）全文 ≤7000 字符。
- `H3-X1`（v3 block）锚点句（第一句）逐字包含每个在画角色的人物表 EN外貌短语 + 当前造型行 EN（含 `镜N起` 换装）。
- `H3-X2`（warn）首句与末句不放 `<d>`。

### 4.3 正文与对白

- `H3-A7`（block）`<d>…</d>` 之外全部英文，不出现任何中文字符。
- `H3-A5`（block）不写否定句：`<d>` 外不出现 no / not / never / without / don't / doesn't / avoid / nothing / none / nobody / neither / nor / n't（`N/A` 除外）。改成“画面里有什么”的正向写法。
- `H3-A9`（warn）只写看得见、听得见的东西；不写剧情概述、心理、抽象情绪词（feel、realize、remember、secret、longing、because…）。
- `H3-D4`（block）不写人名、不写触发词（lnwan01、hh12clear、pose_… 等），人物用 `(S1)` 编号 + 外貌（年龄、性别、发型、服装）指代；全文不出现双引号 `"` `“ ”`（K10：有意偏离官方“画面文字放双引号”，双引号会被烧成字幕，画面文字不写进 H3）。
- `H3-D1`（block）台词格式：`<d>[Chinese] <剧本台词原文></d>`，`<d>` 里只有语言标签和原文。
- `H3-D2`（block）每个 `<d>` 前写说话人编号，按本镜首次开口顺序 `(S1)`、`(S2)`；音色、语气写在 `<d>` 外；不发声的人没有编号：
  `The on-screen young woman with a <timbre> voice, speaking at a <pace> pace (S1) says: <d>[Chinese] <台词></d>`
- `H3-D8`（warn）说话人第一次出现时写清：年龄、性别、是否在画面内（on-screen / off-screen）、音色（… voice）、语速。
- `H3-X3`（v3 block）第 n 个说话人 (Sn) 第一次出现的那一句逐字包含其人物表 VOICE 声线短语。
- `H3-D3`（block）`<d>` 的条数、顺序、文字（含标点）与 `**对白**` 逐字一致。
- `H3-D5`（block）画外台词：`(S<n>) says in an off-screen voiceover: <d>[Chinese] <台词></d>`，`</d>` 后紧跟一句 `… lips remain closed.`
- `H3-D6`（block）🎙 独白不进 H3。
- `H3-D7`（亲密镜 block，其余 warn）亲密镜只有 (S1)；soundscape 不写 man/male/he/his/him 等男性声音词。
- `H3-D9`（warn）`<cutoff>` / `<scenetrans>` 只在剧本标注时使用。

### 4.4 声音字段

- `H3-S1`（block）`overall_soundscape`：1–4 句英文、一段、不含 `<d>`、不复述台词。
- `H3-S2`（block）`overall_soundscape` 不写 `N/A`。
- `H3-S3`（block，**2026-10-30 新规**）`non_diegetic_music`：本镜有配乐 → 1–3 句英文，只写乐器、速度（tempo）、节奏、强弱变化，一段，无中文、无 `<d>`、无否定词、无抽象情绪词（sad、romantic、tense、mysterious、emotional、sensual、dreamy、melancholic、mood… 见校验器 `MOOD_WORDS`）；本镜没有配乐 → 逐字 `N/A`。

### 4.5 官方格式参照（逐字引自 `docs/h3_prompt_guide_base_en.txt` Case 3 / §4.7，只作格式参照）

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a rain-soaked cyclist begins in the position and framing established by Picture 1, holding a closed black umbrella beside a silver bicycle. The camera pulls out with small amplitude at slow speed as she releases the bicycle handle, raises the umbrella above her shoulder, and presses the runner upward until the canopy opens. Water rolls from the expanding fabric while she steps beneath it, rotates the handle into the final angle, and settles into the pose, spacing, and composition established by Picture 2 at the end of the shot.

overall_soundscape: Rain falls steadily on the pavement, followed by the metallic click of the umbrella runner and the soft snap of the canopy opening. Water drips from the bicycle frame as distant traffic passes.

non_diegetic_music: N/A
```

```text
non_diegetic_music: Sparse piano notes at a slow tempo, joined by sustained low strings that gradually increase in volume before fading out.
```

> 与本项目的差别：官方示例开场是 `Live-action, cinematic,`，本项目必须写 `Live-action, cinematic, shallow depth of field,`（H3-A8）。

## 5. 校验与返修

```text
.venv\Scripts\python.exe tools\validate_qwen_script.py <script.md> [--episode N] [--json] [--repair-dir DIR] [--names "A,B"] [--require-scenes] [--require-v3]
.venv\Scripts\python.exe tools\validate_script_strict.py <script.md> [--episode N] [--json] [--repair-dir DIR]     ← 剧本创作：场景 + v3 字段总按 block 查
```

- 用真实导入器解析、真实 `h3_lint` 机检（H3-S3 按新规替换），逐镜列出 `rule_id / level / 问题`。
- 退出码：0 = 无 block；1 = 有 block；2 = 文件解析不出任何集。
- 每个不通过的镜头生成一段“返修请求”（只引用失败的格式规则，不提内容）。报告里的 `repair` 文本不写输出范围；剧本创作对话框统一追加“重新输出完整的那一集”，单镜返修工具（tools/qwen_repair_loop.py）用 `repair_request(..., scope=True)` 追加“只输出这一镜”。
- Qwen 的系统提示词：`config/qwen_writer_system_prompt.txt`。
