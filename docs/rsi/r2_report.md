# RSI r2（fredw-2b 派，2026-11-01 15:58–16:40）

## 1 项目方任务
OT9 看一镜生成结果是否合格（项目方 R11-11：以 R11-2…R11-10 为样例找同类缺陷 → 复现 → 固化成规则和检查，见 docs/REQUIREMENTS.md）。
插队任务（总调度转项目方 §G0 原则，docs/ITERATION_PROTOCOL.md §G0）：交付 K-OPS-D02 的检查，登记两条新决定并扫一遍。

## 2 度量（先测正确性）
- 知识库：上次中断前已修好，15:58 的 compile --check 已经是 OK（knowledge/generated/index.json，15:52 生成）；本轮结束时 380 条规则，一致性检查通过（tools/knowledge/compile.py --check）。
- 缺陷猎捕 16:05 全量重跑：65 类，自动检测 54 类，30 类有命中，一共 684 处（data/qa/defect_hunt/state.json；docs/rsi/DEFECT_HUNT.md §6）。
- 样例逐条复现的结果见 docs/rsi/DEFECT_HUNT.md §3b。关键数字：首帧看镜头 71/100，片头看镜头 56/72（data/acting/gaze_labels.json）；最新 ep01_v2 成片里有 2 镜用的是多手版本（data/episodes/series10/ep01_v2.timeline.json，对照 data/pipeline/runs/series10_v1/video/scores/ep01-S2__mot.json）；V6 坏手指阈值为空，150 条测了，91 条超过 0.2，全部放行（data/qa/defect_hunt/state.json DH-V20）。
- 没有自动检查的规则：141 条（docs/master/unchecked_rules.md，16:02）。审计结果见 docs/rsi/UNCHECKED_AUDIT.md。
- 看图类：试跑 2 条，都没出有效结果（data/qa/defect_hunt/vlm_results.jsonl）= 未测。

## 3 改动
- tools/qa/defect_hunt.py：视频类同时记“全部尝试 / 现行版”两个数；V7 未测单列；新增 6 类（DH-S20 / F18 / V19 / V20 / V21 / X03）；看图类读 VQA 已有判定（vqa_bridge）；state 写入遇到 Windows 文件锁会重试。
- tools/qa/defect_vlm.py（新）：把看图类交给本地看图服务（K-REV-V01），碰到 OOM 或等不到空闲卡就停。
- tools/validate_qwen_script.py：接上 VQ-W1（tools/vqa/script_lint.py），写作链路能看到鞋这条 lint 了。
- tools/qa/iter_gate.py：LINT_SOURCES 加 acting_lints / vqa script_lint；加 --loop RSI 别名，映射到 ITERAUDIT。
- tools/qa/decision_propagation.py（新）：K-OPS-D02 的检查，读 config/owner_decisions.yaml 的 stale_terms / new_terms / propagate / stale_allow 四个字段。
- config/owner_decisions.yaml：D-VID-01 加了同步字段；新增 D-VQA-01（看图转拦截）。
- tools/qa/ownership.yaml：tests/test_ui_copy_uirsi.py 归 UIRSI；本轮新加的文件归 ITERAUDIT。
- knowledge/rules：review_defect_hunt.yaml 加 K-REV-Q03…Q06；ops_iteration.yaml 加 K-OPS-Q14 / Q15；ops_decisions.yaml K-OPS-D02 的 status 改成“确认”（原值不合法，compile 报错）。
- tests：tests/test_defect_hunt.py 加 7 条；新建 tests/test_rsi_rule_checks.py（4 条）、tests/test_decision_propagation.py（4 条）。

## 4 独立复核
未测。本轮没有独立复核方，需要总调度指派（不能由 RSI 自己判通过）。

## 5 回归
- 定向测试：tests/test_defect_hunt.py、tests/test_rsi_rule_checks.py、tests/test_decision_propagation.py、tests/test_iter_gate.py、tests/test_writer_lints.py 全过；引用 validate_qwen_script / qwen_repair_loop / p4_adapter 的测试 207 过、1 跳过（tests/ 下这几个文件）。
- 全量 tests/：1576 过、7 不过、4 跳过（16:20 跑，用时 327 秒）。7 条不过的都和本轮改动无关：tests/test_fix_ep02_round2.py（已知遗留，docs/CHANGELOG_AGENTS.md 有记录），以及 tests/test_image_framing.py、tests/test_image_jobs.py、tests/test_unified_frame.py、tests/test_single_identity_face.py、tests/test_ref_switch_assets.py（它在测试里写了真实的 refboards，被 real_data_guard 拦下）、tests/test_review_fixes_d9.py——这几条都在出图编译器、身份脸、界面路由上，由别的 loop 并行在改。
- decision_check：43 项里 38 项 ✅、0 项 ❌、5 项跳过（tools/qa/decision_check.py --no-api）。

## 6 证据
data/qa/defect_hunt/state.json、docs/rsi/DEFECT_HUNT.md、docs/rsi/UNCHECKED_AUDIT.md、data/qa/decision_propagation/report.md、data/qa/defect_hunt/vlm_results.jsonl、knowledge/RSI_LEDGER.md（DH 节）。

## 7 规则
K-REV-Q03、K-REV-Q04、K-REV-Q05、K-REV-Q06、K-OPS-Q14、K-OPS-Q15（knowledge/rules/review_defect_hunt.yaml、knowledge/rules/ops_iteration.yaml）；check 都是 tools/qa/defect_hunt.py 加 tests/test_defect_hunt.py。
