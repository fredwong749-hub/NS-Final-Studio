# RSI r3（fredw-2b 派；时间以文件修改时间为准）

## 1 项目方任务
OT9（R11-11 续：红测试归因、节奏慢的根因）；W8（docs/master/NIGHT_PLAN_20261101.md：规则系统、决策同步残留清零）。

## 2 度量（先测正确性）
- 7 条红测试逐条归因（断言、源文件修改时间、审计日志），结论见 docs/master/MASTER_PICTURE.md §4 G20–G24：
  - tests/test_single_identity_face.py、tests/test_unified_frame.py：同一个根因。data/looks/face_overrides.json 里林晚的身份脸指向整张 4 栏设定图 A-s202（ar-f9519334bc），是 data/looks/character_hub_log.jsonl 第 28 行 fred 点选的；第 29 行同时把 lin_wan_face_ref2va.png 驳回为“画质差”。
  - tests/test_image_jobs.py：data/pipeline/runs/series10_v1/assets/first_frame_jobs.json 是 10:32 生成的，编译器后来加了视线句（K-REN-G01），所以 24/80 不一致（tools/prompt_v2/audit_framing.py 逐镜对比，ep01-S7 差的就是这一句）。
  - tests/test_image_framing.py：断言还是旧句；services/agent/ns_agent/framing.py:186 已改成正向句（tests/test_gen_contract.py:468 已同步）。
  - tests/test_review_fixes_d9.py：测试复制了真实 data/looks；真实排期里 ep04/05 已经有项目方确认，断言跟着变了。
  - tests/test_ref_switch_assets.py：参考板写到了真实 refboards 目录 → 本轮改成临时目录，5/5 通过（tests/test_ref_switch_assets.py）。
  - tests/test_fix_ep02_round2.py：已知遗留。
- 节奏慢：80 镜的时长全部来自剧本，H3 帧数按时长直接换算（packages/schema/ns_schema/h3_lint.py frames_for_seconds）。写作输入是“总时长目标 60 ±5、镜数 6–上限 max(8, 轮次+独白)”（tools/pipeline/writer_prompt.py:109），所以平均镜长下限约 7.5 秒。K-WRT-203 原文还写着“7–9 秒常见”（knowledge/rules/writer_series10.yaml）。新 lint 在现稿上：QW-T1 37 处、QW-T2 3 集（tools/qa/writer_lints.py）。
- 决策同步：decision_check 43 项，38 ✅ / 0 ❌ / 5 跳过；decision_propagation 两条决定都已全量同步（data/qa/decision_propagation/report.md）。
- 无检查规则：141 → 128 条（docs/master/unchecked_rules.md，iter_gate --list-unchecked）。

## 3 改动
- tools/qa/writer_lints.py：新增 QW-T1 / QW-T2，级别固定 warn（返修环不能改镜数 / 时长）。规则 K-WRT-Q07 写进 knowledge/rules/writer_iteration.yaml，writer_text 进 config/recipes/writer_knowledge.md。
- knowledge/rules/writer_series10.yaml：K-WRT-203 里“7–9 秒常见”这句标 ⤴，由 K-WRT-Q07 取代（G0 同步）。
- tools/qa/decision_propagation.py：新增 K-OPS-D03（无 owner 的文件单列、算不通过）、K-OPS-D04（生成物列进同步清单 = 配置错误），并加了 summary()。tools/qa/decision_check.py 末尾打印汇总。
- tools/qa/iter_gate.py：新增 G0 项（归本 loop 的文件里有残留 = 不通过）；K1 不过时列出比生成物新的规则文件和它的 owner。
- tools/qa/ownership.yaml：validate_qwen_script.py → ITERAUDIT；REQUIREMENTS.md、docs/vqa/STATE.md、docs/acting/{STATE,CALIBRATION,PERFORMANCE_RULES}.md、config/vqa.json → VQAGATE；SOP_production.md 设为共享（写入口 = 总调度派单）。
- config/owner_decisions.yaml：D-VID-01 的同步对象从 STATUS.md 改成 tools/series10_video/night.py；D-VQA-01 的 stale_allow 加上审计报告和 MASTER_PICTURE。
- 13 条旧规则补上 check 引用：knowledge/rules/edit.yaml 7 条、writer_camera.yaml 3 条、render_imggen_s10.yaml 3 条。tests/test_rsi_rule_checks.py 新增 K-EDT-018 的 HNR 测试。
- knowledge/rules/ops_decisions.yaml：收编 K-OPS-D03 / D04（草案移到 knowledge/inbox/confirmed/）。
- tests/test_ref_switch_assets.py：参考板目录改成 tmp_path。
- docs/master/MASTER_PICTURE.md §4：新增 G20–G29。

## 4 独立复核
r2 的复核证据 docs/audit/RSI_r01.md（AUDIT）。r2 收轮（iter_gate --verifier AUDIT）结果是 INCOMPLETE：r3 又改了 r2 的几个文件，复核证据比改动旧，需要 AUDIT 按本报告重新复核。

## 5 回归
- 定向：tests/test_writer_lints.py、tests/test_defect_hunt.py、tests/test_iter_gate.py、tests/test_decision_propagation.py、tests/test_rsi_rule_checks.py、tests/test_ref_switch_assets.py 全过；引用写作校验器的测试 208 过、1 跳过（tests/ 下 grep 出的文件）。
- 全量 tests/：1617 过、6 不过、4 跳过（耗时 312.75 秒）。6 条不过都已归因到 docs/master/MASTER_PICTURE.md G20–G24，不是本轮改动造成的；tests/test_ref_switch_assets.py 已转绿。
- compile --check：OK（tools/knowledge/compile.py）。

## 6 证据
docs/master/MASTER_PICTURE.md §4 G20–G29、data/qa/decision_propagation/report.md、data/looks/character_hub_log.jsonl、knowledge/RSI_LEDGER.md（DH7 / DH8）、docs/audit/RSI_r01.md。

## 7 规则
K-WRT-Q07（knowledge/rules/writer_iteration.yaml，lint QW-T1 / QW-T2）、K-OPS-D03 / K-OPS-D04（knowledge/rules/ops_decisions.yaml）；K-WRT-203 部分 ⤴。
