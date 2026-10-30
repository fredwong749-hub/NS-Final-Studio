# 写作链端到端实测日志（fredw-92/D2）

目标：提纲 → 剧本 → 分镜（H3 提示词 + 场景）用写作模型 abliteration `abliterated-model-large-flash` 跑通；
导入只做沙盒（不进生产，项目方闸门）。提纲 = data/import/script_v2.json 第 4 集 synopsis 原文（不另写内容），集数 [4,4]。

沙盒检查脚本（不进仓库）：scratchpad `sandbox_check.py`：tools/import_script.py `--merge-base data/import/script_v2.json -o <scratch> --no-timeline`
→ 对 ep04 每镜 `compiler.compile_shot` → 查 首帧提示词 / 尾帧提示词 / H3 提示词 + `h3_lint` block 规则 / 时长 4–15 / 对白说话人 /
sound 与【H3 audio】/【配乐】cue / 场景 id 在场景库且首帧含【场景】段 / 场景细节非空。

## 第 1 轮（2026-10-31 01:09–01:30）

会话 `20261031-010935-86d929`（data/script_chat/20261031-010935-86d929/）。S-back 场景格式已在（规则 §2S、QW-SC1–SC6、compiler scene_segment）。

| 步骤 | 结果 / 失败 | 根因 | 处理 | 文件:行 | 结果 |
|---|---|---|---|---|---|
| 1 新建会话 | 通过，pending = 提纲原文 + 集数 | — | — | — | — |
| 2 写作（生成 #1，50 s） | ep04《汤还热着》🔴 8 镜、62 秒、本集场景表 1 行（sk_guchen_dining）、每镜 `**场景**` 行齐；校验 blocking 2 / warn 2 / 附加提示 0 | — | — | — | — |
| 2a | ep04-S4 H3-D3 block：`**对白**` 1 句，H3 里 0 个 `<d>` | 模型漏格式（H3 正文没写台词句） | 走返修；对应 v3 第三部分 H3 表“对白”行（H3-D1/D2/D3/D5/D8） | — | 返修后通过 |
| 2b | ep04-S5 H3-A4 block：末句写成 `settles against … established by Picture 2 …`，不是 `settles into` | 模型漏格式 | 走返修；对应 v3 H3 表“开场与首尾句”行（H3-A8、H3-A4） | — | 返修后通过 |
| 2c | warn：S5 H3-A9 `inner`（来自 “inner calf”，词表误伤，只提示）；S6 H3-A10 两个运镜（pull out + tilt） | 模型 / 词表 | 只记录（warn，不阻断） | — | 未处理 |
| 3 返修（/repair → /chat，生成 #2，13 s） | blocking 0、warn 1（S6 H3-A10）、hints 0、can_send=true | — | — | — | 通过 |
| 3a | 返修消息自相矛盾：每镜段（校验器原文）说“请输出 ep04 镜4 的完整 Markdown…其它镜头不要输出”，结尾（script_chat.repair_message）说“请重新输出完整的 ep04”。本次模型输出了整集，没出事；若模型只回单镜，回复里没有 `## ep`，`record_reply` 什么都不并入、`done.episodes=[]`，返修**静默丢失** | 系统 bug（API）：record_reply 只认整集 | `merge_shot_reply`：回复没有 `## ep` 但有 `**镜N｜img` 块，且最近一条用户消息只点名一集、镜号都在该集草稿里 → 按镜号并入该集（不新增镜，partial 不并）。校验器那句文字属格式规则文件，按协调要求不改，留给 v3 接入 | services/api/ns_api/script_chat.py:764（merge_shot_reply）、:791（record_reply 调用）；tests/test_script_chat.py `test_shot_only_repair_reply_merged` | 测试通过；API 进程未重启，下次重启生效 |
| 4 送导入（/to-inbox） | candidate:true，validate_qwen_script 摘要 ok、blocking 0、warn 1 | — | 未导入生产 | — | 通过 |
| 5 沙盒导入 | import_script --merge-base → 60 集 368 镜，替换 ep04，scene_library 合并出 sk_guchen_dining | — | — | — | 通过 |
| 6 沙盒编译 | 8/8 镜：首帧 / 尾帧 / H3 非空，H3 = 剧本原文逐字，h3_lint 无 block，时长 5–12，说话人齐，【配乐】cue 齐，场景 id 在库、首帧含【场景】段（逐字取场景表 + 本镜细节） | — | — | — | **PASS 8/8** |
| 6a | 场景分组：8 镜同一剧本场景 sk_guchen_dining，`group_scenes` 却切成 6 段（S2/S3/S4/S6/S8 transition=place） | 系统 bug：`_apply_script_scenes` 保留了关键词推断的段首（img 里“桌下”“餐桌边缘”等被推断成换地点），剧本场景 id 相同也开新段；段首影响上一镜尾帧 → 下一镜首帧的接力 | 前后两镜都写了剧本场景 id 时，推断出的 transition=place 不再开新段（清掉该 transition）；转场词 / 时段变化照旧开段；旧剧本（无场景 id）不变 | services/agent/ns_agent/state_timeline.py:236–244；tests/test_scene_segments_d2.py | ep04 8 镜 = 1 段；全量测试通过 |
| 7 全量测试 | 751 passed, 6 skipped | — | — | — | 通过 |

### 只记录、未改（按协调：规则文件 / 契约 / 校验器 / 导入器格式部分留给 v3 接入 agent）

- config/qwen_writer_system_prompt.txt:14 【配乐】动作词仍写“进入/延续/推高/落下/点题”，与 rules §6A（“不写推高或点题”）冲突 → v3 K2（第五部分已列）。本轮模型用的是 §6A 词表，没触发。
- config/qwen_writer_system_prompt.txt 每镜字段顺序里没有 `**场景**` 行（只在 rules §2S 里有）；本轮模型照 §2S 写了 → v3 第一部分“场景行”。
- config/qwen_writer_system_prompt.txt 仍写“6–8 个镜头 / 50–75 秒”与末段“只输出被要求的那一段”，rules §1/§2 已放宽 / 覆盖 → v3 K1。
- 校验器返修文字“其它镜头不要输出”与 repair_message 结尾“重新输出完整的 epNN”矛盾（见 3a）；API 侧已兜底。

### 花费

| 生成 | prompt | completion（含 reasoning） | 费用（$1/M 提示、$2/M 输出） |
|---|---|---|---|
| #1 写作 | 10,715 | 17,757（11,762） | ≈ $0.046 |
| #2 返修 | 20,686 | 6,363（316） | ≈ $0.033 |
| 合计 | 31,401 | 24,120 | ≈ $0.08 |

### 下一轮

等协调通知 v3（人物表、集头造型、人物行、衔接行、说话人必填等）接入后，用同一提纲再跑一轮（剩余预算约 4 次生成）。

## 第 2 轮：v3 规则（R3 接入后），ep03 / ep04 / ep05 重写（2026-10-31 02:18–02:45）

API 02:18 已重启（新代码，含第 1 轮的 merge_shot_reply 与 R3 的 compact_header）。每集一个会话，提纲 = script_v2.json 该集 synopsis 原文，集数单集：
ep03 `20261031-021828-d01334`、ep04 `20261031-021820-feaa45`、ep05 `20261031-021820-fb6a6d`。目标：tools/validate_script_strict.py --episode N block=0。

| 集 | 首稿（关口 block / warn） | 返修 1 | 返修 2 | 严格校验终稿 block / warn 条目 |
|---|---|---|---|---|
| ep03 | 5 / 11 | 关口 0（严格仍 1：S6 QW-C3） | 0（严格 0） | 0 / 6（QW-E6b×2、H3-D8×4） |
| ep04 | 15 / 2（其中 QW-CH4×3 为误报，修后 12） | 3（S6–S8 H3-X1） | 0 | 0 / 2（QW-E6b×2） |
| ep05 | 7 / 8 | 0 | — | 0 / 4（QW-E6b×2、QW-LK2、QW-SC7） |

严格校验另有 13 条 QW-G2 warn 落在系统给的全局头（data/staging_v3 v3.1 的 LoRA 触发词表分段名 / 行格式），不是模型输出，未改（内容属剧本维护方）。

### 失败 → 根因 → 处理

| 步骤 | 失败 | 根因 | 处理 | 文件:行 | 结果 |
|---|---|---|---|---|---|
| 首稿 ep03/04 | QW-P4 / QW-D2 block：说话人没有 VOICE（整集没写本集人物表） | 规则歧义（系统）：2P 说“全局头的全剧人物表是已登记角色、表里没有才写本集人物表”，但全局头里**没有**全剧人物表，模型把有角色锁的林晚 / 顾沉当成已登记；校验器只认人物表里的 VOICE | 2P 补一句格式说明：“已登记”只看全剧人物表 / 前面各集人物表，角色锁不算；没有全剧人物表时每个出场角色（含林晚、顾沉、陈宇）都写本集人物表。写作提示词第 10 行同步 | config/script_chat_rules.md:80；config/qwen_writer_system_prompt.txt:10 | 返修后两集都补了人物表；下一次写作生效 |
| 首稿 ep03/04 | QW-SC8 block：固定陈设 4 件 | 规则文件漏项（系统）：校验器 / 契约 / v3 都要求 1–3 件、两格不写人物，但写作模型看到的 config/script_chat_rules.md §2S 没写 | §2S 补一行 QW-SC8 格式要求 | config/script_chat_rules.md:74 | 返修后通过 |
| 首稿 ep04 | QW-CH4 block ×3：“img 里出现了人物行没有的角色：顾沉” | 校验器误报（系统 bug）：img 写的是场景名“顾沉家餐厅”，按子串算成顾沉入镜 | 判断入镜前先去掉所有格地点（人名 + 家 / 公寓 / 卧室…，与 compiler.without_possessive_places 同口径） | tools/validate_qwen_script.py:42、:687–690 | ep04 QW-CH4 消失；全量测试通过 |
| 首稿 ep04/05 | H3-X1 block：锚点句没有逐字包含人物表 EN外貌短语 / 造型 EN（模型改写了措辞、插了修饰语） | 模型漏格式 → v3 H3 表 H3-X1（production_rules_v3 §1.5；rules §5 第 135 行） | 走 /repair（ep05 一次、ep04 两次） | — | 通过 |
| 首稿 ep03 | H3-D3 block：S5 台词没写进 H3 | 模型漏格式 → v3 H3 表“对白”行（H3-D3） | /repair | — | 通过 |
| 返修 1 后 ep03 | 严格 QW-C3 block（S6 只有腰腹 / 手的局部镜，没有表情短句），关口同一条是 warn；API 的提示列表把它去重吞掉，/repair 返回空（关口没有返修文字），返修路径走不到严格 block | 系统 bug（API）：严格与关口同一条按 (规则, 字段, 详情) 去重时不看级别；repair_message 只用关口返修文字 | 关口 warn、严格 block 的条目也列为提示（带 block 级）；有 block 级提示的镜 / 集带 hint_repair（严格校验返修原文），/repair 在关口没有返修时用它；can_send 仍只看关口（不改 fredw-92 的口径） | services/api/ns_api/script_chat.py:510（_hint_new）、:532–545、repair_message；tests/test_script_chat.py `test_repair_uses_strict_block_hints` | API 未重启：本次用新代码离线生成同一条返修消息、经 /chat 发送；ep03 严格 0 block |
| 沙盒链式合并（ep03→04→05 依次 --merge-base） | 合并后 ep03 7/8、ep04 8/8 镜 H3-X1/X3 不过；单集各自合并都 8/8 通过 | 系统问题：三个会话各自写本集人物表，林晚 / 顾沉的 EN / VOICE 三集各不相同；merge_globals 人物表“新稿优先”静默覆盖，前面集 H3 逐字引用的旧短语对不上 | ① import_script 合并时比对底稿已登记的人物 / 场景，文字不同且定义它的集没被替换 → 警告“登记冲突”（只提示，不改合并口径）② 根治需要写作时带全剧人物表（见下“待定”） | tools/import_script.py:44（registry_drift）、:32；tests/test_scene_segments_d2.py `test_registry_drift_warns_on_merge` | 链式合并现在给出 2 条登记冲突警告 |

### 沙盒结果（终稿）

- 每集单独 --merge-base data/import/script_v2.json：ep03 / ep04 / ep05 都 **PASS 8/8**。逐镜查：首帧 / 尾帧 / H3 非空，H3 = 剧本原文，h3_lint 无 block，时长 4–15，speaker 齐，sound /【H3 audio】/【配乐】齐，场景 id 在场景库、首帧有【场景】段、场景细节非空，人物行、衔接行、结束状态齐，在画角色的 EN + 造型 EN 逐字在锚点句（H3-X1），说话人 VOICE 逐字在首次开口句（H3-X3）；集头：出场人物、用到的场景、造型行、人物表（EN + VOICE）、场景表齐。
- 三集链式合并：ep05 PASS 8/8；ep03 / ep04 因人物表被后一集覆盖而 H3-X1/X3 不过（见上表最后一行）。
- 场景分组：ep03 1 段，ep04 2 段（餐厅 → 卧室，衔接行“换场”），ep05 1 段，与每镜衔接行一致。
- 三份草稿已 /to-inbox（candidate:true，关口 blocking 0），**未导入生产**。

### 只记录、未改

- H3-D8 warn ×4（ep03）：说话人首次出现没写 on-screen / off-screen → v3 H3 表“对白”行（H3-D8）。
- QW-E6b warn（各集 2 条）：造型槽位不是 wardrobe.json 的名称（妆 / 发 / 甲 / 饰品槽也按单品名比对）→ v3 QW-E6b。
- QW-LK2 / QW-SC7 warn（ep05）。
- QW-C3 严格 block 对“只拍腰腹 / 手、没有脸”的局部镜也要求表情短句；规则如此，模型已按返修补上，是否对局部镜放宽由规则方定。
- **待定（需要协调定）**：写作时的全局头没有全剧人物表 / 全剧场景表（header_sources = data/staging_v3 v3.1 原稿，没有这两张表），每个会话各自登记角色，同一角色 EN / VOICE 每集不同、跨集无法逐字复用。建议由系统把已导入的登记（data/import/script_v2.json 的 character_registry / scene_library）按全剧人物表 / 全剧场景表格式并进写作全局头（script_header），表格内容来自已导入剧本、不由系统写。

### 花费（第 2 轮，8 次生成）

| 集 | 生成 | prompt | completion |
|---|---|---|---|
| ep03 | 首稿 / 返修 1 / 返修 2 | 13,330 / 25,351 / 32,785 | 20,654 / 10,011 / 7,586 |
| ep04 | 首稿 / 返修 1 / 返修 2 | 13,138 / 26,158 / 33,771 | 22,587 / 9,526 / 7,592 |
| ep05 | 首稿 / 返修 1 | 13,144 / 26,178 | 13,831 / 9,722 |
| 合计 | 8 | 183,855（≈ $0.18） | 101,509（≈ $0.20） |

第 2 轮约 $0.39；两轮累计约 $0.47。全量测试 837 passed, 6 skipped。

## 第 3 轮：人物表 / 场景表全剧一份、逐集继承（fredw-92 2026-10-31 定），以 ep03 为登记来源重写 ep04 / ep05（02:45–02:52）

### 实现（系统；表格内容全部来自已有剧本 / 草稿，系统不写）

| 项 | 做法 | 文件:行 |
|---|---|---|
| 继承登记并进写作全局头 | `registry_tables`：生产 data/import/script_v2.json globals 登记 → 会话 `registry_from`（会话 id / 剧本 md，按顺序）→ 本会话集号 < 起始集的各集；同名 / 同 id 先登记为准；`script_header` 在全局头后原样附 `**全剧人物表**` / `**全剧场景表**`（全局头原文已有的不重复），compact_header 照留。系统提示词按会话（`session_cfg` → `session_registry`）；草稿文件 `write_draft` 只附外部来源（本会话各集本来就在文件里，按集号先登记为准） | services/api/ns_api/script_chat.py:111、:125、:142、:194、:209；write_draft、validate_episode_text(registry=) |
| 接口 | `POST /sessions`、`POST /ab` 新增 `registry_from: [会话id / 路径]`，建会话时校验存在（不存在 400） | 同上 NewBody / ABBody / new_session |
| 写作规则（格式） | 2S / 2P：全剧表是系统并入的已登记条目，各格 / EN / VOICE 逐字照抄、不改写、不再写进本集表，只登记新角色 / 新场景；写作提示词第 10 行同步；契约加 QW-P7 / QW-SC9 行 | config/script_chat_rules.md:64、:80；config/qwen_writer_system_prompt.txt:10；docs/qwen_writing_contract.md:108、:130 |
| 校验 | 全剧表（继承）登记在本集表里被改写 → QW-P7（人物）/ QW-SC9（场景）block，详情附要照抄的原文全文（不截断）；集与集之间的改写仍是 QW-P5 / QW-SC5 | tools/validate_qwen_script.py:93–95、:391、:580 |
| 合并导入 | 登记冲突保留先登记的、不覆盖（定义它的集全部被这次替换时才用新稿的），并警告“登记冲突…保留先登记的” | tools/import_script.py:44（base_registered）、:68（merge_globals 的 registry） |
| 批量写作（剩余 55 集） | `tools/script_chat_batch.py --episodes 6-60 --registry-from <ep03 会话id>`：默认按集号顺序一集一集写（workers=1），写 epN 时系统提示词与单集校验都带 生产登记 + 登记来源 + 本会话 ep<N 的登记；`--no-inherit` 恢复并行 | tools/script_chat_batch.py:146（reg_for / vet）、ask、主循环 |
| 测试 | test_script_chat `test_registry_inherited_into_header`；test_scene_segments_d2 `test_merge_globals_keeps_first_registration`；按新决定改期望：test_scenes_s1（SC9 / SC5）、test_rules_v3（P7、合并先登记为准）、test_script_chat_batch 假校验函数接 registry | tests/ |

API 在 /api/jobs 空闲时（02:49，D1 的 ep02-S11 视频已 done）按 ops/autostart 同参数重启，新代码已生效。

### 重跑

| 集 | 会话 | 生成 | 关口 block / warn | 严格 block / warn 条目 |
|---|---|---|---|---|
| ep03（登记来源，第 2 轮终稿） | 20261031-021828-d01334 | — | 0 / 6 | 0 / 6（QW-E6b×2、H3-D8×4） |
| ep04（继承 ep03） | 20261031-024934-95bbaf | 1（无返修） | 0 / 2 | 0 / 2（QW-E6b×2） |
| ep05（继承 ep03） | 20261031-024934-44e771 | 1（无返修） | 0 / 6 | 0 / 6（QW-E6b×2、QW-K3×3、QW-SC7） |

- ep04 只在本集表登记了新出场的陈宇和新场景 sk_guchen_dining，林晚 / 顾沉 / 电梯场景全部照用全剧表；ep05 只登记新场景。
- 三份都已 /to-inbox（未导入生产）。沙盒依次合并（script_v2.json → ep03 → ep04 → ep05）：**无登记冲突警告**；整批 23 镜（ep03 8、ep04 7、ep05 8）编译**全部通过**，H3-X1（锚点句含人物表 EN + 造型 EN）/ H3-X3（说话人首句含 VOICE）逐字对上，集头、场景 / 人物 / 衔接行、结束状态、说话人齐。
- 花费：2 次生成，prompt 27,380 + completion 43,828 ≈ $0.12（三轮累计约 $0.59）。全量测试 839 passed, 6 skipped。
- 注意：ep04、ep05 并行写，都只继承 ep03；按 4) 的用法逐集写时 ep05 会再继承 ep04 新登记的陈宇 / 餐厅。
