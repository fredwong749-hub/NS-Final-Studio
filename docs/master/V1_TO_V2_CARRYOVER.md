# V1 → V2 继承审计（CARRYOVER-F，11-03 03:xx，只读）

项目方 11-03 02:5x 原话：“虽然 V2 是说从零开始自动化迭代，但其实我们在 V1 的时候，有非常多的规则、提示词和模型，很多东西都还蛮有用的。master agent，你要看懂，不要瞎搞。”

口径（L-125 / L-126）：切掉的只有 **内容**（剧本、人物、身份脸、资产、BGM 曲目、画风方向）；**代码、流程规则、检查规则、模型选择和参数** 应全部延续到 V2。本表按这个口径逐项判定。

## 一、判定方法
- 按剧开关的根：`tools/autopilot/runs.py:152` `is_legacy(run) = run == legacy_unprefixed_run(series10_v1)`；`runs.py:216` `asset_manifest(run)` 非空 = 资产包模式（V2）。`services/agent/ns_agent/run_paths.py:38-55` 非 legacy 剧解析到 V1 路径直接 `V1PathError`。写作侧 `tools/script_rsi/autoflow_agent.py:95-97` 有 `CLEAN_CUT.json` 才算 clean_cut。
- 出图侧亲自只读编译了 V2 第 1 集第 8 镜（`NS_RUN=series10_v2 tools/promptfix/golden_v2.py --compile --shot 8`，另用脚本打印 preflight 逐项）。结果摘要见 §三。
- 视频侧：V2 一条视频都没出过（`data/pipeline/runs/series10_v2/video/` 空），只能看调用链。
- 状态四类：**生效** / **存在但 V2 没调用或非 strict** / **只限 V1（被按剧开关挡住）** / **已删 / 丢失**。
- 优先级：P0 = 直接影响画面质感、一致性、成功率或时间轴；P1 = 影响流程完整性、规则有效性；P2 = 文案 / 过时 / 死配置。

## 二、P0 / P1 缺口清单（已登记的 ISS 号在表里）
**P0**（已登记：1 → ISS-1103-024205-8856，2 → ISS-1103-024206-c8c0，3 → ISS-1103-024206-4b21，4 → ISS-1103-024206-3737，5 → ISS-1103-024206-0474，6 → ISS-1103-024206-9974）
1. 近景 / 特写镜服装信息全丢：第 8 镜编译后提示词里没有任何服装词、没有造型参考、没有漆皮材质句（框架规则 K-REN-707 + V2 清单单件“全身装”标签含“裙”→ zone=lower）。
2. Q1a 逐人头发 / 性别属性闸门对 V2 失效：`gen_contract.json Q1a_attr.cards` 只有 lin_wan / gu_chen / chen_yu，V2 四人无卡 → 恒 na。
3. 本地看图闸门没有挡在视频之前：`config/vqa.json gate.video_requires_q9 = false`。
4. V2 视频链不存在：build_jobs / vidgen / night 写死 series10_v1；video_policy scope 只认 series10_v1；recipes / H3 官方写法 / lint / 不看镜头 / ≤6 秒在 V2 视频链没有任何检查点。
5. 运镜词表按剧条目在视频端拿到 run=None：V2 专属运镜（bolt_push_settle 等）会被改回 static。
6. CLEAN_CUT“交稿须 v1_leak scan 0 命中”没有代码执行点：V2 ep01 `P4_ep01.final.md` 带 V1 全局头（林晚 11 处、lnwan01 2 处、顾沉 3 处），导入稿 `globals.lora_triggers` 全是 V1 道具触发词（nprng2 / lbrng9 / hh12* / ptx*）。

**P1**
7. 集级 BGM（L-118）V2 没有写入方：`tools/bgm/agent.py:31`、`deliver.py:29` 写死 `data/music/series10`。
8. 归因 `tools/pipeline/attribute_bug.py:90` 写死读 V1 导入稿，V2 失败无归因落盘。
9. 写作校验 `tools/pipeline/p4_adapter.py:47-55` 调 validate 不传 run → QW-C1 用 V1 运镜词表，V2 专属运镜被判“不在词表”（且只是 warn）。
10. Q1 主角 0.70 线按 `lin_wan` 键，V2 主角 lead_f 退到 default 0.60。
11. 负面词：`frame_job.py:290` 把 job.negative 覆盖成 brand_negative（空），编译器的“未成年人外观”硬负面词不进作业；Turbo（cfg 1）负面词本就无效，定稿档 final_base_2pass（cfg 3）又因 `auto_final_on_lock=false` 没启用 → V2 只有预览档。
12. `config/s2_waivers.json` 只按集号匹配不带 run，V2 ep02 走到 plate 闸门会误用 V1 豁免。
13. shot_spec_v2 → 固定顺序英文句、L-110 融合契约句、L-111 灯光规则：写作闸门有、出图 / 视频生产链没接（已登记 ISS-1103-023528-2869）。
14. asset_worker `golden=false / voice=false`，常驻进程 tick_golden TypeError 未重载（已登记 ISS-1103-023528-dd39）。
15. RL-T1–T7 时间轴 lint：写作交稿 / 导入 / 视频提交三处都不跑；TIMELINE-O 在修，不重复登记。
16. 运维：partition / repart_check 与 dispatch 写死 V1 根（V2 开派前没有 control、过不了 repart_check）；SENTINEL S8 / producer 心跳探针看不到 V2，S6 探针持续报错；owner_decisions.yaml 缺 L-127、L-129～L-136 共 9 条，D-CLN-05 ❌ 会拦下一次发版；本机 system_version.txt 停在 sv-04 导致计分 sv 标签全错。
17. IMGLAB 四类结构化控制（ControlNet / Detailer / PuLID / IC-Light）无一进生产图，V2 金样只走 qwen_edit 多参考 + 预设；按 TRACK 现状这是研究未闭环，不是漏接。

## 三、V2 ep01 第 8 镜只读编译证据
- refs = `assets_v2/characters/lead_f/face/lead_f_face_v1.png`、`assets_v2/scenes/sk_white_cyc/..._2.png`（只有脸 + 场景，无造型 / 单品）。
- preflight I1–I13 全 pass；但 I3 = “造型 O4；设定图 0 张”、I4 = “单品参考 0 件”，I7 文案仍写“预设 leica_sstar 后缀”（实际用的是 v2_editorial_reality_c2，文案过时）。
- 提示词：有视线句、四分之三侧脸、图1/图2 标注、近景首句、【场景】段、“面部清晰对焦，五官锐利”、“衣装完整”、v2_editorial_reality_c2 风格句、无字幕句；**没有**“黑色漆皮抹胸紧身短裙、黑色薄透丝袜”任何一字，也没有漆皮材质句。
- job：model qwen_image_2.1，preset v2_editorial_reality_c2（Turbo），loras = krea2_film_texture 0.5，negative = ""，trace.rules = K-REN-950/951/952/953/954/955/957。
- style_warning：“本镜没有幻想 / 现实段标记，按缺省 reality 段出”（写作侧未标【现实段】）。

## 四、总表

### A. 写作规则
| 规则或资产 | 来源文件 | V2 状态 | 证据 | 建议 | 优先级 |
|---|---|---|---|---|---|
| 写作核心规则 script_chat_rules.md | config/script_chat_rules.md | 生效（P3–P4 包） | services/api/ns_api/script_chat.py:476-481；P4_ep01_a1 system 段含 31/35 节 | 已生效 | — |
| 附录（A3–A8、H3 限制，按触发词注入） | config/script_chat_rules_appendix.md | 生效（P4） | script_chat.py:374-393、:492-505；P4 包带 11 节 | 已生效 | — |
| RL-T* 时间轴规则（sysimpl-v2） | script_chat_rules.md sysimpl-v2 节；services/recipes/ns_recipes/lint.py:158-226 | 存在但 V2 写作链 / 视频提交不调用（出图编译时对 V2 strict） | p4_adapter.py 11-03 00:59 导入时只调 missing_fields；shot_spec.py:383-398 run_strict；h3_video.submit_lint 只跑 ns_schema.h3_lint | TIMELINE-O 在修，不重复 | P0（已有人修） |
| V1 专属写作规则 | config/script_chat_runs/series10_v1*.md | 只限 V1（run_parts 按剧） | script_chat.py:363-371；V2 包命中 0 | 保持只限 V1 | — |
| 格式契约提示词 | config/qwen_writer_system_prompt.txt | 生效（P4、patch 包） | script_chat.py:476；tools/script_rsi/hollywood.py:135-137 | 已生效 | — |
| production_rules_v3 / qwen_writing_contract | docs/production_rules_v3.md、docs/qwen_writing_contract.md | 文件不是输入，内容已落到 qwen 提示词 + validate | 只在注释 / 出处行引用 | 已生效（间接） | — |
| knowledge/rules → writer_knowledge.md | knowledge/rules/*.yaml（44 文件 667 条）→ config/recipes/writer_knowledge.md | 生效 | tools/knowledge/compile.py:294；ep02 包用 kb-20261102-a89b9d31 与当前一致；ep01 包是旧快照 | 编译不自动触发，建议接到 autoflow 出包前 | P2 |
| 按段注入的 K 规则（link + writer_text） | knowledge/rules/*.yaml | 生效 | tools/pipeline/chainlib.py:52-56；P4 包 60 个 K-id | 已生效 | — |
| knowledge/prompts/writer/pack.md | 同左 | 存在但 V2 没调用 | 无加载点 | 清理或接上 | P2 |
| chain.yaml SL-/EO-/SP-/LK-/P4-GATE 规则 | config/pipeline/chain.yaml:151-193、:429-547 | 生效（block 级） | tools/pipeline/run_chain.py:87-122；P1–P3 报告 0 阻断 | 已生效 | — |
| 好莱坞写作模板 / Pika 参考 | config/prompts/hollywood_writer.md、hollywood_pika_reference.md | 生效 | tools/script_rsi/autoflow.py:249-254；hollywood.py:39 | 已生效 | — |
| 好莱坞评审（LLM 评审） | config/prompts/hollywood_judge.md | 存在但 V2 第 1 集没走（测试期 code_only） | autoflow_agent.py:1061；hollywood/ep01.json score_basis=code_only_27 | 测试期设计；注意 hollywood_judge.md:162 含“第二季是林晚”V1 内容 | P2 |
| P1 三评委 | config/prompts/hollywood_p1_judge.md、hollywood_p1_review.yaml | 生效 | judge_agent.py:273-280；judge_p1/RESULT.json | 已生效 | — |
| 事实表 / FACTCHECK | config/prompts/hollywood_facts.md | 生效 | hollywood_r5.py:34；facts_ep01 0 偏差 | 已生效 | — |
| PERFORMANCE_RULES.md | docs/acting/PERFORMANCE_RULES.md | 文件不是输入；规则已落到 acting_lints + 附录 A8 + knowledge | 只在注释引用 | 已生效（间接） | — |
| QW-W* 写作 lint | tools/qa/writer_lints.py | 生效（写作链 block；导入闸门 warn） | tools/validate_qwen_script.py:40-42；p4_adapter.py:27；full_repair.py:404-409 | 导入闸门也应 block | P1 |
| QW-A1–A8 表演 lint | tools/qa/acting_lints.py | 生效 | validate_qwen_script.py:44-46、:834-837 | 已生效 | — |
| QW-C1 运镜词表校验 | validate_qwen_script.py:458-483 | 生效但非 strict，且按 V1 词表判 | p4_adapter.py:47-55 写 _tmp 不传 run → run_of_path 退到 series10_v1；QW-C1 只 warn | 传 run；升 block | P1 |
| QW-T1 单镜 ≤6 秒 | writer_lints.py:252-259 | 生效但只 warn | V2 ep01 镜 6 = 7 秒 | 升 block 或在视频提交处检查 | P1 |
| 导入关口校验 validate_qwen_script | tools/validate_qwen_script.py | 生效（非 strict：P3–P4 ≤6 条阻断也收稿） | autoflow_agent.py:867、:1386 | 收稿阈值应为 0 | P1 |
| validate_script_strict / script_chat.validate_draft | tools/validate_script_strict.py；script_chat.py:895-1136 | 存在但 V2 没调用（只在 UI / autopilot writer） | 无 V2 报告 | 保持 | P2 |
| assert_no_v1 + v1_guard.json | script_chat.py:520-597；config/v1_guard.json；tools/script_rsi/v1_leak.py | 只在出包口生效；交稿 / 闸门 / 导入三处没调 | autoflow_agent.py:107-111 出包；:865 / :1384 交稿、:1067-1070 闸门、:1127 导入都没调；P4_ep01.final.md 林晚 11 处；script_v2.json lora_triggers = V1 触发词 | 三处接 v1_leak scan，0 命中才放行；重新导入 ep01 | **P0** |
| repair_chain | tools/pipeline/repair_chain.py | 拼稿部分只限 V1（episode_sources 读 V1 导入稿） | :60；V2 只用 _rel / split_doc | 按剧参数化或保持 | P2 |
| rubric_code / rubric_audit.gate / owner_gate / scene_lock | tools/script_rsi/* | 生效 | autoflow_agent.py:1067-1070；scene_locks_ep01.json | 已生效 | — |
| shot_spec_v2 写作闸门（构图 / 灯光 / 运镜 / 分拍） | config/director/shot_spec_v2.yaml；rubric_code.py:414-432 | 写作闸门生效 | autoflow_agent.py:1398 .md.v2 触发；P4 含各段 | 已生效 | — |
| 规则版本盖章 | services/recipes/ns_recipes/spec_import.py:35-64 | 生效 | P4_ep01.md 第 1 行 rules_v2+sysimpl-v3 | 已生效 | — |

### B. 出图：编译器 / 契约 / 看图
| 规则或资产 | 来源文件 | V2 状态 | 证据 | 建议 | 优先级 |
|---|---|---|---|---|---|
| 唯一编译入口 build_first → compile_shot | services/agent/ns_agent/frame_job.py:264；compiler.py:671 | 生效 | 第 8 镜 compiled_by 字段；trace.rules K-REN-950–957 | 已生效 | — |
| 按剧路径 run_paths（不读 V1 looks / 导入稿 / renders） | ns_agent/run_paths.py | 生效（strict，V1PathError） | :38-55 | 已生效 | — |
| V2 编译规则文件（技术纠正规则） | config/compile/bible_series10_v2.toml（经 run_style.json runs.series10_v2.bible） | 生效 | bible.py:259-277 V1BibleRefused | 已生效 | — |
| 近景面部对焦 / 暗场细节 / 安全镜衣装 / 漆皮材质 | bible_series10_v2.toml [[shot_rules]] [[materials]] | 生效 | 第 8 镜含“面部清晰对焦，五官锐利”“衣装完整” | 已生效 | — |
| [realism] banned_words 去 AI 味 | visual_bible.toml:66 有 9 条；V2 bible 只有 7 条 | 部分丢失：“严格保持图1的眼睛形状”“五官比例完全一致”两条没迁 | 文件对比 | 补回（通用，与画风无关） | P2 |
| [look.video] negative“画风变为动漫” | visual_bible.toml:41 有；V2 bible 没有 | 丢失 | 文件对比 | 补回 | P2 |
| style_negative“画面发灰 / 低饱和 / 暗沉 / 过曝” | visual_bible.toml:28 有；V2 bible 只留字幕类 | 丢失（被当画风切掉） | 文件对比；但 V2 导入稿 base_negative 自带“灰暗脏乱的色调” | 等 STYLE-V2 定；Turbo 负面词本就无效 | P2 |
| [generation] 多轮评分参数 | visual_bible.toml:156 | 死配置（无代码读 candidates_per_round） | grep 0 命中 | 不用迁 | — |
| V1 内容规则（林晚脚趾甲、针形细跟、角色表、makeup_states） | visual_bible.toml [[materials]] toenails/needle_heel、[characters.*] | 只限 V1 | V2 bible [characters] 为空 | 保持只限 V1 | — |
| 风格后缀机制（按剧 / 按段取预设 + I7 禁用词） | config/compile/run_style.json；gen_contract/style.py:104-127；render_quality.json v2_editorial_* | 生效（strict，StyleMissing） | 第 8 镜 preset v2_editorial_reality_c2；v1_style_hits 阻断 | 已生效；I7 pass 文案“预设 leica_sstar”过时 | P2（文案） |
| 段落标记【幻想段】/【现实段】→ 预设 | style.py:segment_of | 生效，但写作侧没标 | style_warning 按缺省 reality | 写作规则加“每镜标段” | P1 |
| 契约 preflight I1–I13 | gen_contract/preflight.py | 生效 | 第 8 镜 13 项 pass | 已生效 | — |
| I3 / I4 造型 / 单品参考 | preflight.py:228-246；asset_refs.py:166-179 zone_of、:1613 | **规则生效但对 V2 清单失真**：O4 单件“日常全身装…短裙…”→ zone=lower → 近景不送；I3 显示“设定图 0 张”仍 pass | 第 8 镜 refs 无造型图 | 清单单件拆 upper/lower 两件或 zone 标 body；近景无造型参考应 fail | **P0** |
| K-REN-707 近景不注入下半身 / K-REN-901 删句保主语 | framing.py:137-147 filter_parts、HIDE:23 | 生效但副作用：整句“穿黑色漆皮抹胸紧身短裙、黑色薄透丝袜”被删，抹胸（上身）一起丢 | 第 8 镜提示词无服装词 | 分句按单品拆后再过滤；或保留含上身件的分句 | **P0** |
| 漆皮材质句 patent_gloss | bible_series10_v2.toml [[materials]] | 生效但第 8 镜未触发（服装句被删 → 无“漆皮”可匹配） | 同上 | 随上条修复 | P0（同上） |
| 身份脸只经 face_of + 清单（I2 / I11，L-126） | asset_refs.py:1062；preflight.py:141-147、:364-381 | 生效（strict） | 第 8 镜 refs 在清单内 | 已生效 | — |
| 只要可能露脸就送身份脸 K-REN-950 / 尾帧 K-REN-953 | image_framing.json promptfix.face_exposure_guard、last_face_guard | 生效 | trace.rules 含 950/953 | 已生效 | — |
| 站位契约 K-REN-952、局部不送整套板 K-REN-951、手部单品 K-REN-955 | image_framing.json promptfix | 生效 | trace.rules | 已生效 | — |
| 景别开关 per_project | image_framing.json per_project.__default__.off_episodes=[2] | 生效；V2 传 framing_project=series10_v2 不受 __default__ 影响 | framing.py:62-68 | __default__ 的 ep02 关闭是 V1 决定，建议挪到 series10_v1 键下 | P2 |
| 确定性种子流 K-REN-954 | ns_render/seed_stream.py；golden_v2.py:348-358；golden_worker.py:132-139 | 生效 | trace.rules 含 954；账本 data/ab/v2_golden/takes.jsonl | 已生效 | — |
| LoRA 白名单 / 禁用（I8） | gen_contract.json lora_allow / lora_banned | 生效 | 第 8 镜 loras 只有 krea2 0.5 | 已生效 | — |
| 自动身份 LoRA | config/auto_lora_triggers.json | 存在但为空（林晚 LoRA 已撤） | characters={} | 保持 | — |
| 成年人 / HC-07 硬约束（I10） | tools/pipeline/hard_constraints.py；preflight.py:404-407 | 生效 | 第 8 镜 I10 pass | 已生效 | — |
| 未成年人外观硬负面词 / base_negative | compiler.py MINOR_GUARD、_negative；frame_job.py:290 | 编译器产出但作业被覆盖：job.negative = brand_negative → "" | 第 8 镜 negative="" | frame_job 合并而不是覆盖；Turbo 无效但定稿档需要 | P1 |
| 品牌字样 I13 / brand_words | config/compile/brand_words.json；asset_refs.py:841-855 | 生效 | I13 pass | 已生效 | — |
| 本地专用资产路由 I12 / K-REN-958 | asset_refs.plan_route | 生效 | route server_ok | 已生效 | — |
| postflight Q1 身份（三段线 + 身份库 + 复核带） | gen_contract.json Q1_identity；postflight.py:342-459 | 生效；但“主角 0.70”只对 lin_wan 键，V2 lead_f 用 default 0.60 | 配置键名 | 加 lead_f: 0.70 或按清单 primary 取主角线 | P1 |
| Q1a 逐人头发 / 性别属性（K-REV-V19） | gen_contract.json Q1a_attr.cards；postflight.py:93-99 | **只限 V1**：cards 仅 lin_wan/gu_chen/chen_yu，V2 角色无卡 → 恒 na | 代码 `todo = {c for c in boxes if c in cards}` | 从 assets_v2 清单 / P1 人物表自动生成 cards | **P0** |
| Q1x 同场跨镜一致 | Q1x_scene enabled | 生效（不分剧） | 配置 | 已生效 | — |
| Q1d anomaly detector | Q1d_anomaly enabled=false | 存在但关着（V1 也关） | 配置 | 保持 | P2 |
| Q10 出图后验收（identity/outfit/prompt/count） | Q10_accept enabled；tools/vqa/accept.py | 生效；outfit 子项含“lin_wan 水晶甲”V1 逻辑（accept.py:112） | 配置 | V1 逻辑不影响 V2 | — |
| Q2 造型一致 | Q2_outfit；postflight.py:474-549 | 生效但第 8 镜无造型参考 → na（随 P0-1） | 第 8 镜 slots 无 sheet/item | 随 P0-1 修复 | P0（同上） |
| Q3 景别 / Q5 坏手 / Q6 文字 / Q4 质感 / Q7 场景 | gen_contract.json | 生效（Q4/Q7 record_only，V1 决定） | 配置 | Q4/Q7 复判是否对 V2 开阻断 | P2 |
| Q8 林晚发色 | postflight.py:635-658 | 只限 V1（lead_id 按剧） | 代码 | 保持 | — |
| Q9 本地看图闸门（judge.enforce / gate.enforce） | config/vqa.json:260-268 | 生效（enforce=true，hair_primary=true） | 配置 | 已生效 | — |
| 看图闸门挡在视频之前 | vqa.json gate.video_requires_q9=false；vqa/contract.py:817 | **存在但关着**（V1 D-VQA-02 的打开条件没走完） | 配置 | V2 直接 true | **P0** |
| vqa.json 24 项检查 + eye_contact / underage 阻断 | config/vqa.json checks | 生效（通用；zh 文案举 V1 例） | 配置 | 已生效 | — |
| anomaly 人数 / 头数 / 手数 | tools/vqa/anomaly.py | 生效（经 Q10 count） | golden_v2.evaluate | 已生效 | — |
| 导演加强 director_boost（owner_only） | config/director_boost_rules.md（空）；build_first 不传 boost | 存在但 V2 没调用（项目方手填内容，属 V1 内容） | 文件 6 行注释 | 保持 | P2 |
| IMGMASTER 分段编译 / plugins.yaml K 挂点 | config/compile/imgmaster.yaml（enabled=false）、plugins.yaml | 存在但 V2 没调用；同名逻辑以内联形式在 build_first 里跑 | frame_job.py:397-430 | 保持或决定切换 | P2 |
| 出图模型 Qwen-Image 2.1 Turbo + texture_fix VAE + krea2 0.5 | render_quality.json tiers / v2_editorial_* | 生效 | 第 8 镜 model/preset/loras | 已生效 | — |
| 定稿档 final_base_2pass（Base 35 步 cfg 3 两段式） | render_quality.json auto_final_on_lock=false | 存在但 V2 没调用 | 配置 note（等“徕卡锐利”方案 = V1 决定） | V2 要不要定稿档，总调度定 | P1 |
| ComfyUI 工作流 | comfy/workflows/（空）；ns_render/workflows.py:18-23 代码拼图 | 代码工作流生效；json 工作流已删 / 丢失 | takes workflow=frame_v9_unified | 保持（代码即工作流） | — |
| 车道表 hosts.json / 渲染端点 | config/factory/hosts.json；config/render_endpoints.json | hosts 生效；render_endpoints 只给 API 画布用 | golden_v2.py:366-375 | 已生效 | — |
| 资产作业执行器（阶段 A / B） | config/pipeline/asset_worker.json | 生效但 golden=false、voice=false；常驻进程 tick_golden TypeError | worker.json 心跳 | 重启常驻、开 golden（ISS-1103-023528-dd39） | P1 |
| 场景底图 / 场景别名 | config/scene_aliases.json；asset_refs.py:1128-1129 | 只限 V1（V2 走清单） | 代码 | 保持 | — |
| S2 豁免 | config/s2_waivers.json；state_timeline.py:276-293 | 存在，按集号不带 run → 跨剧泄漏隐患 | 配置 episode=2 | 加 run 字段 | P1 |
| 成人判定 / adult_overrides | config/adult_overrides.json；compiler.py:517 | 生效（整集 🔴 口径） | V2 bible:65 指向 | 已生效 | — |
| 镜头归属 shot_ownership | config/shot_ownership.json | 只限老项目（进规则哈希） | pipeline.py:452-470 | 保持 | — |
| 身份脸指针 face_reference.json | 同左 | 只限 V1 | edits.py:289 | 保持 | — |

### C. 视频 / 运镜
| 规则或资产 | 来源文件 | V2 状态 | 证据 | 建议 | 优先级 |
|---|---|---|---|---|---|
| VIDEO10 主链 night → build_jobs → vidgen（Pika / recipes） | tools/series10_video/build_jobs.py:37、vidgen.py:37、night.py:29 | **只限 V1（路径写死，不是开关）**；且 build_jobs 读 primary 导入稿 → 现在跑会把 V2 镜编进 V1 video 目录 | `RUN = data/pipeline/runs/series10_v1` | 按剧参数化（runs.py run_dir）或接 gate_legacy_tool | **P0** |
| ns_recipes 16 个 recipe（i2va_pika_flex、ref2va、two_person、overlays） | services/recipes/recipes/*.yaml；ns_recipes/registry.py:193 | 存在但 V2 没调用（无调用方；API 需 recipe_plan） | V2 video/ 无 jobs.json | 随视频链接上 | P0（同上） |
| H3 官方写法（对齐句 / 三字段 / Picture 剥离） | ns_recipes/prompt.py:185-207；ns_render/h3_video.py:339-342 | 生效面有，V2 没调用；V2 h3_prompt 已是官方结构（写手写的） | 导入稿 h3_prompt | 随视频链 | — |
| 提交前 H3 lint | ns_schema/h3_lint.py；h3_video.py:345-352 | 存在但 V2 没调用；不含 RL-T | roles.py:41 描述与实际不符 | 接 ns_recipes.lint（TIMELINE-O） | P1 |
| 视频策略 pika_only / dejudder / flush_risk hold | config/pipeline/video_policy.json:17 scope_source_contains=series10_v1 | 只限 V1（被 scope 挡住） | ns_recipes/compiler.py:188-219 | scope 加 series10_v2 或改按 run | **P0** |
| Pika Flex 默认基底 | render_quality.json video_bases.default=pika_flex | 存在，不分剧，提交即生效 | h3_video.py:85-109 | 已生效（待出片验证）；_base.yaml:99 仍写 official_base 依据 | P2 |
| 运镜词表 camera_moves.yaml（单一来源） | config/director/camera_moves.yaml；ns_agent/camera_norm.py | 写作端生效（QW-C1 warn、按 V1 词表）；视频端两处不传 run → V2 专属条目不可用 | ns_recipes/prompt.py:215、ns_render/pipeline.py:801 调用无 run；camera_norm.py:71-77 run_ok | 两处传 run | **P0** |
| K-REN-801 运镜先 A/B 再 enabled | camera_moves.yaml:279-352 | 生效（字段齐）：bolt_push_settle ab pass 3/3；handheld_follow partial 2/3 靠 requires 限制；fail 的 enabled=false | 配置 | 已生效；文件头写的 camera_vocab.py 不存在（已丢，实际是 camera_norm.py） | P2 |
| 镜头语言模板 v2 → 固定顺序英文句 | config/director/shot_spec_v2.yaml；tools/director/shot_v2.py:17 | 存在但生产没调用（只出评审页、读 V1 导入稿） | ISS-1103-023528-2869 | 接 build_first / 视频编译 | P1（已登记） |
| L-110 融合契约句 + 合成感检测 | shot_v2.py；config/policies/sentinel.yaml:74 composite_max=null | 存在但没启用 | tools/sentinel/probes.py:454-458 | 启用阈值 | P1 |
| L-111 灯光规则 lighting.yaml / lenses.yaml | config/director/lighting.yaml、lenses.yaml | 写作闸门生效（rubric_code.py:432、line3_score.py:49）；出图 / 视频链没接 | work_ep01/line3_score.md 有灯光行 | 随 shot_spec_v2 接 | P1 |
| 单镜 ≤6 秒 | writer_lints QW-T1 warn | 写作端 warn；视频链无检查 | ep01 镜 6 = 7 秒 | 升 block | P1 |
| 无字幕 | h3_lint H3-D4；vqa text_watermark | 视频链只有 H3-D4；成片无字幕检测 | — | 成片加 OCR 探针 | P2 |
| 所有画面不看镜头 | ns_recipes/lint.py:236-246；vidgen.py:103-113；vqa eye_contact（图） | 首帧生效；视频链只限 V1 | 第 8 镜提示词含“眼睛不看镜头” | 随视频链 | P0（同链） |
| 出片后 motion_qc / score_clip | ns_render/motion_qc.py；score_clip.py | 存在但 V2 没调用 | — | 随视频链 | P1 |
| 审片导演 director_system_prompt.md | config/recipes/director_system_prompt.md；tools/autopilot/director.py:19 | 存在但 V2 没调用（审片环节未到） | data/autopilot/runs/series10_v2 空 | 到审片阶段再核 | P2 |

### D. 声音
| 规则或资产 | 来源文件 | V2 状态 | 证据 | 建议 | 优先级 |
|---|---|---|---|---|---|
| V2 音色（6 角色）| config/voices_v2.json | 生效（strict，VoiceRunRequired） | ns_post/run_media.py:119-172；tts.py:67-86 | 已生效；文件头“未启用”注释过时 | P2 |
| TTS 技术参数（tts_model / asr / speech_python / remote_tts） | config/voices.json TECH_KEYS | 生效（V2 只拷 4 个技术键） | run_media.py:166 | 已生效 | — |
| V1 角色音色 | config/voices.json characters | 只限 V1 | 同上 | 保持 | — |
| V2 配乐曲库（L-131） | config/music_v2.json | 生效（strict） | run_media.py:57-105；sha 核对一致 | 已生效 | — |
| 集级 BGM（L-118）生成 / 写入 | tools/bgm/agent.py:31、deliver.py:29、brief.py:24 | 只限 V1（写死 data/music/series10）；V2 无写入方 | data/music/series10_v2 不存在 | 按剧参数化 | P1 |
| BGM 生成参数 bgm.json | config/bgm.json | 整季主题曲生效（bgm_themes.py:135）；逐集 agent 只限 V1 | — | 同上 | P1 |
| BGM 提示词 | config/prompts/bgm_brief.*、bgm_reason_plain.md | 只限 V1（随 agent） | — | 同上 | P1 |

### E. 模型 / LLM
| 规则或资产 | 来源文件 | V2 状态 | 证据 | 建议 | 优先级 |
|---|---|---|---|---|---|
| LLM 服务商 / 用途路由 | config/llm_providers.json；ns_api/llm_config.py | 生效（全局） | autoflow.json writer_backend=claude_agent | 已生效 | — |
| 出图预设 / prompt_guard | render_quality.json | 生效 | compiler.py:225 | 已生效 | — |
| STYLE-V2 工具配置 | config/v2style.json | 生效（V2 专用） | tools/v2style/common.py | 已生效 | — |
| 策略阈值 policies/*.yaml | config/policies | producer 部分 V2 没调用（status=preparing）；budget 写作链生效 | producer.py:323 | V2 转 producing 后复核 | P2 |

### F. 归因 / K 条目
| 规则或资产 | 来源文件 | V2 状态 | 证据 | 建议 | 优先级 |
|---|---|---|---|---|---|
| 归因表 attribution.yaml | config/pipeline/attribution.yaml；tools/pipeline/attribute_bug.py:90 | 只限 V1（写死读 data/import/script_v2.json） | V2 无归因记录 | 按剧参数化 | P1 |
| K 规则库 667 条 | knowledge/rules/*.yaml | 写作链生效；出图链确认执行的 K 点：K-REN-954/958/959、K-REV-V01 + promptfix 950–957 | 见 A/B 表 | 已生效 | — |
| 只有文档无检查的 K 条目 | docs/master/unchecked_rules.md（11-01 统计 128/391，过时） | 103 条两者都无（UI 30、REN 27、OPS 18、AST 17） | 统计见审计 | 重跑 iter_gate --list-unchecked | P2 |
| rule_ids.md（H3-* 规则号表） | docs/audit/rule_ids.md | 存在但 V2 没调用（gpu3 脚本用） | — | 保持 | — |
| 代码引用但规则库没有的 K 号（31 个） | K-OPS-E19~E25、K-HOME-*、K-VQA-001… | 规则缺登记 | grep | 补登记 | P2 |

### G. 运维 / RSI（见下文 §五，CARRYOVER-F 运维子审计）

## 五、运维与 IMGLAB
### G. 运维 / RSI
| 部件 | 来源文件 | V2 状态 | 证据 | 建议 | 优先级 |
|---|---|---|---|---|---|
| partition.json + repart_check（帧跟数据所在主机） | config/netfix/partition.json；tools/factory/repart.py:45；tools/netfix/dispatch.py:34-35、:125、:136-142、:178-179 | 只限 V1：repart 只数 `data/renders/epNN`；dispatch 写 V1 的 control / ready，V2 作为 primary 又被 extra_runs 排除 → 没有专属 control | partition.json 只有不带剧号的集号；data/producer/runs/series10_v2 只有 log.jsonl | 按剧取 renders_dir / producer_dir | P1（V2 开派前必须） |
| SENTINEL 探针 S1–S28 | config/policies/sentinel.yaml；tools/sentinel/probes.py、remote_probe.py | 部分生效：S11 / S19 / S27 / gpu_hours 按 run；S8 看图抽样（probes.py:476 `data/renders/ep*/S*/takes.json`）、producer 心跳 / registry / control（:130、:217、:431、:727；remote_probe.py:51-80）写死 V1 根 | sentinel.log 一直 tick；S6 自 11-02 12:41 起每次 `AttributeError 'list'.get`（probes.py:378，627 次） | S8 / producer 类改按剧；修 S6 | P1 |
| SLO.md 指标按剧 | docs/master/SLO.md:24、:68 | 只有 GPU 出图量按 run 拆；其余合计 | 文档 | 加 run 维度 | P2 |
| RSI scores.jsonl / SCORECARD | data/rsi/scores.jsonl；tools/sentinel/scorecard.py:78-80、:384 | 生效（计分对象 = primary = series10_v2；image 行 pending_stage） | 最新行 run=series10_v2；SCORECARD.md:44 口径变更留痕 | 主表“现分”仍是 V1 数；sv 标签全写 sv-04（本机 data/system_version.txt 停在 sv-20261102-04） | P2 |
| owner_decisions.yaml + decision_check | config/owner_decisions.yaml；tools/qa/decision_check.py；probes.py:535-537（S10）；system_version.py:161-164 发版闸门 | 存在但 V2 覆盖不全：L-125 / L-126 / L-128 已登记；**L-127、L-129～L-136 共 9 条没登记**；D-CLN-05 ❌（V1“只含 6 个场景”断言打到 V2 主剧） | decision_check_sentinel.json：66 ✅ / 2 ⏳ / 1 ❌ | 补 9 条；D-CLN-05 限定 run，否则下一次发版被闸门拦 | P1 |
| system_version 每轮发版 | tools/qa/system_version.py；data/system_versions/ | 生效（不分剧）：V2 期间 sv-15（19:59）、sv-16（21:04，部署两台） | index.json / lock_history | 21:04 之后无新 cut；golden_v2 --summary 已在，可补发版（ISS-1103-023529-71ed） | P1 |

### H. IMGLAB 结构化控制（docs/research/imglab/TRACK.md）
| 项 | TRACK 状态 | 代码落地 | V2 金样链用上？ | 建议 | 优先级 |
|---|---|---|---|---|---|
| ControlNet pose（T10） | Fun CN 冒烟失败（0.8/1.0 崩成拼图）→ 总调度定不推进；DWPose 只留景别闸门 | 仅 tools/imglab/ab.py、smoke.py | 否 | 保持不推进 | — |
| ControlNet depth（T7） | 研究，无人实测 | 无 | 否 | 研究闭环后再定 | P2 |
| FaceDetailer（T6） | 两台已装，冒烟 0.713→0.723，A/B 等窗口 | 仅 smoke.py；生产只有 image_params.py:59 detail_pass（默认关） | 否 | 补 A/B（研究必须闭环） | P2 |
| HandDetailer（T8） | 冒烟不合格（身份 0.713→0.585） | 仅 smoke.py | 否 | 保持 | — |
| PuLID / IP-Adapter | TRACK 无条目；研究文档“Qwen 版未查到”，Flux 不可商用 | 全仓 0 命中 | 否 | 不进生产 | — |
| IC-Light（T9） | 研究；首选一次生成，兜底 Edit-2509 Light-Migration | 全仓 0 命中 | 否 | 保持 | — |
| 金样链实际用的 | — | ns_render/workflows.py:124-157 qwen_edit 多参考 + frame_v9 预设 + IP.apply | 是 | — | — |

## 六、哪些是 V1 内容、确实该留在 V1
- 人物表 / 角色锁 / 身份脸 / face_reference / face_overrides / refcrops；林晚脚趾甲、针形细跟、水晶甲、Q8 发色、Q1a 三张人物卡、Q5 long_nails；scene_aliases 六个 V1 场景；voices.json 角色段；bgm 曲目；S★ / 徕卡 / W 杂志色 / 雾霾天蓝等画风句；config/script_chat_runs/series10_v1*；asset_repair/lin_wan_*；s2_waivers 的 ep02 豁免。
- 这些在 V2 都已被开关挡住或清单取代，**唯一例外是 V2 ep01 的 P4 全局头和导入稿 lora_triggers（P0-6）**。

## 七、这次审计没做的
- 没改代码、没出图、没重启；没读 data/master/。
- 运维子审计（partition / SENTINEL / scores.jsonl / SCORECARD / owner_decisions L-129–L-136 / system_version）和 IMGLAB TRACK.md 落地情况见 §五。
