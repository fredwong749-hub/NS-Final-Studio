# 没有自动检查的规则 · 审计（RSI，fredw-2b 派，2026-11-01 下午）

来源：`.venv/Scripts/python.exe tools/qa/iter_gate.py --list-unchecked`，11-01 16:02 一共 141 / 363 条（docs/master/unchecked_rules.md；rules_page 筛选“没有自动检查”一栏是同一批）。
边界：knowledge/rules 只能追加自己的条目，所以别人规则的 `check:` 由 owner 自己加（加一行，并删掉 `enforced: false`）。RSI 能做的是：① 找出**其实已经有检查、只是规则没引用**的；② 自己写得出的检查直接写好（`tests/test_rsi_rule_checks.py`、`tools/qa/defect_hunt.py`）；③ 补不了的写明原因。

## 汇总

| 类 | 条数 | 处理 |
|---|---|---|
| A 已经有测试，规则没引用 | 12 | owner 在 check: 加下表路径（每条都 grep 核对过断言内容） |
| B RSI 本轮新写的检查 | 3（另 2 条在 C 里，数据层已有部分检查） | 测试已过；owner 在 check: 引用 |
| C 能补、但要动 owner 的代码 | 17（K-OPS-121 / I06 合一行） | 写了建议的检查做法，交 owner / 总调度 |
| D 不宜做成自动检查 | 109 | 原因见下（研究笔记 50、界面 32 交 UI loop、项目方闸门 / 决定 5、运维操作要点 / 待验实验 / 流程约定 22） |

## A. 已经有测试，规则没引用（owner 加一行 check 就算有检查）

| 规则 | owner | 已有检查（断言内容） |
|---|---|---|
| K-EDT-005 切点边缘淡化 0.12 s | AUTOPILOT（FIX） | tests/test_fix_ep02_assemble.py:120 `edge_fade_s == 0.12`（只覆盖淡化；≤10 dB 跳变没测） |
| K-EDT-006 对白溢出判不通过 | AUTOPILOT（FIX） | tests/test_fix_ep02_assemble.py §“对白 / 独白溢出判不通过”（:91 起） |
| K-EDT-016 音色只来自 _cand | VOICE10 / FIX | tests/test_voice10_s10.py（_cand 夹具 + voices.json 写入） |
| K-EDT-017 CER 前数字转中文读法 | AUTOPILOT（FIX） | tests/test_voice10_s10.py::test_cer_canonicalises_numerals |
| K-EDT-014 参考音频 sha 锁定 | AUTOPILOT（FIX） | tests/test_narrator_voice.py、tests/test_voice10_s10.py（ref sha） |
| K-EDT-009 合成只取定稿版、记 plan_hash | AUTOPILOT（FIX） | tests/test_iterate_loop.py（plan_hash 写进 sources）；成片层由 defect_hunt DH-X03 复核（K-REV-Q06） |
| K-WRT-108 写作模型默认关推理 | PROMPT | tests/test_llm_config_w1.py:262 `reasoning_effort == "none"` |
| K-REN-102 景别取舍按项目 / 集开关 | PROMPT | tests/test_image_framing.py（off_episodes / keep_locked_shots） |
| K-REN-103 出图提示词只经编译器 | PROMPT / REFLOCK | tests/test_image_jobs.py::test_series_jobs_prompt_equals_compiler_output、::test_submit_gate_rejects_hand_written_prompt |
| K-AST-251 造型参考去头 | IMGGEN→REFLOCK | tests/test_gen_contract.py:289（K-AST-233 去头断言） |
| K-REN-124 徕卡 S★ 默认路径 | IMGGEN→REFLOCK | tests/test_leica_sstar_lca.py::test_default_is_leica_sstar_and_matches_experiment |
| K-PRM-301 H3 只由编译器生成 | VIDEO10 | tests/test_recipes_engine.py、tests/test_prompt_timeline_v2.py（specs_from_import → compile_shot） |

## B. RSI 本轮新写的检查

| 规则 | 检查 | 内容 |
|---|---|---|
| K-REN-122 首帧景别档位 | tests/test_rsi_rule_checks.py::test_size_bands_match_rule_in_image_and_video_qc | imggen.py 与 score_clip.py 的 BANDS = 规则原文 [0.45, 0.27, 0.17, 0.115, 0.095, 0.05] |
| K-REV-301 视频景别差 ≥2 档 | 同上 + ::test_video_size_mismatch_is_two_bands；数据层 defect_hunt DH-V12（现行版 38 条） | |
| K-PRM-302 视频不挂身份 LoRA / 风格句禁词 | ::test_video_bad_lora_and_style_regex_cover_rule_words、::test_recipe_style_leads_are_clean | build_jobs 的两个正则覆盖规则里每个词；所有配方 style_lead 干净 |
| K-EDT-007 整集 −14 LUFS / 真峰值 ≤−1 | defect_hunt DH-A01（数据层，现命中 ep01_v1 真峰值 −0.88） | 只测已合成的成片；合成代码侧没有单测（见 C） |
| K-AST-252（同场光线连续部分） | defect_hunt DH-F11 / DH-S19 | 同场相邻首帧亮度跳变 >45（现 2 处） |

## C. 能补、但要动 owner 的代码（建议做法）

| 规则 | owner | 建议的检查 |
|---|---|---|
| K-AST-001 露脸角色要有定稿身份参考 | REFLOCK | gen_contract preflight 缺脸阻断已有（asset_refs “缺图阻断”），在 tests/test_gen_contract.py 加一条“在画露脸角色无 identity_refs → preflight fail”的断言并引用 |
| K-REV-121 “不像他人”门槛 max(0.40, 互相余弦+0.05) | REFLOCK | 把门槛函数抽成纯函数，测 顾沉/陈宇 0.429 → 0.479 |
| K-REV-122 双人镜第二人没出脸只重出 1 次 | REFLOCK | imggen.decide 单测（两次都只差这项 → 标“待人工看”） |
| K-AST-222 新角色设定图“与他人”检查 | ASSETMASTER | 设定图选择函数单测（≥门槛自动换 seed） |
| K-AST-221 新角色先定 A 再约束 B / C | ASSETMASTER | 同上，B / C 判“与 A 余弦 ≥0.50” |
| K-AST-252 场景空镜底图登记后才过 I5 | REFLOCK | preflight I5 单测（无 role=space → fail） |
| K-REN-301 露脸镜默认走首帧路线 | VIDEO10 | build_jobs.recipe_choice + 阶梯选择函数单测 |
| K-OPS-302 推模型后核 sha256 | VIDEO10 / INFRA | deploy 脚本里 sha 比对抽函数并单测 |
| K-OPS-303 服务器端 motion_qc 显式传配置路径 | VIDEO10 | 静态测试：score_clip.py 里 MQ.thresholds 调用带 render_quality.json 参数 |
| K-REV-010 接触印样末帧 dur − 1.5 帧 | AUTOPILOT（DIR） | 找到取帧函数加单测（本次 grep 没找到实现位置，需 owner 指路） |
| K-EDT-018 HNR 窗自相关校正 | VOICE10 | tools/voice10/voice10.py hnr_corrected 用合成正弦 + 噪声测（低音 f0 110 Hz 不被低估） |
| K-EDT-007（合成侧） | AUTOPILOT（FIX） | assemble 响度归一单测：输出 −14±1、TP ≤−1 |
| K-WRT-210 无 LoRA 作业去触发词 | SERIES / REFLOCK | 编译器单测：无 LoRA 时 triggers_removed 非空、正文无 lnwan01 |
| K-PRM-011 Ref2VA detailed_description 350–500 词 | VIDEO10 / AUTOPILOT | tests/test_prompt_timeline_v2.py 现在只测结构，加词数区间断言 |
| K-OPS-121 / K-OPS-I06 道深度按服务器队列算 | IMGPERF / INFRA | 提交线程的“补交条件”抽函数单测（本工具在服务器上的任务数 <2 才补） |
| K-OPS-I04 重启前队列空且未取回 = 0 | INFRA | 重启守卫函数单测（tests/test_api_c_backend.py 有“未取回”相关，可复用） |

## D. 不宜做成自动检查（原因）

- **研究蒸馏 50 条**（knowledge/rules/research.yaml，K-*-R01…，AUTOPILOT）：是社区 / 论文结论的摘录，status 多为“建议 / 待验”；能检查的前提是被采纳进配置后由采纳方写检查（tests/test_research_adoption_params.py 已覆盖被采纳的那部分）。保留 enforced: false 合理。
- **界面 32 条**（K-UI-001…032，UIRSI 23 / ASSETUX 5 / UIAUDIT 4）：检查应是 e2e spec，那几个 loop 正在并行跑，归它们引用自己的 spec；RSI 不改。
- **项目方闸门 / 决定 5 条**（K-AST-201/202/203、K-WRT-008、K-AST-004）：是“谁定了什么”的记录，检查对象是 config/owner_decisions.yaml（RECALL 的 decision_check 已在比对决策账本），不是代码行为。
- **运维操作要点 / 待验实验 / 流程约定 22 条**：K-OPS-I01/I02/I03/I05/I07、K-OPS-122、K-OPS-301、K-EDT-015、K-REN-018（远程服务启动参数、内存锁、机器分工、venv 版本——只能在服务器上巡检，不在仓库测试里）；K-REN-003/015/017/019、K-REN-123/125、K-REV-124、K-AST-223、K-REN-013、K-REN-016（status 待验 / 建议的 A/B 结论或参数取舍，先要实验结果，定了以后由 owner 写进配置再测）；K-AST-002、K-AST-003、K-OPS-002（出候选流程 / 场景继承约定 / 作业找回做法，属流程说明；K-OPS-002 若要测可做“按 plan_hash + seed 找回”单测，交 AUTOPILOT）。

## 交给总调度

- A 类 12 条：转各 owner 加一行 check（不改代码）。
- C 类 17 条：转各 owner 排进自己的 sweep。
