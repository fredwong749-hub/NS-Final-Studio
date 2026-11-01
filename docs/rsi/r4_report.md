# RSI r4（fredw-2b 派：总调度对 r3 五项决定 + AUDIT 草案 + RESEARCH 规则；时间以文件修改时间为准）

## 1 项目方任务
OT9（R11-2 / R11-3 节奏慢：G29 方案 A 落地）；W8（docs/master/NIGHT_PLAN_20261101.md）。

## 2 度量（先测正确性）
- G29 落地后，用现稿重算（tools/qa/writer_lints.py check_pacing，上限取 services/agent/ns_agent/importer/script_md.py shot_cap）：
  - 10 集镜数上限从 8 变成 9–12（ep07 有 11 镜，上限 12；importer/script_md.py shot_cap 逐集算）。
  - 现稿还是旧上限下写的（7–8 镜），所以 QW-T2“还能加镜”从 3 集变成 8 集（tools/qa/writer_lints.py check_pacing）。QW-T2 的意思是“镜数没到上限就先加镜”，上限放宽后它在旧稿上只会更多；要等之后重写才会消失，不是改完上限就清零。
  - 真正变化的是规则现在能满足了：例如 ep03 一共 54 秒，上限 9 镜，平均 6 秒（原来上限 8 镜时最少 6.75 秒；数字出自 data/qa/defect_hunt/state.json 用的同一份剧本）。
- 决策同步：D-VID-01、D-VQA-01、D-SCR-06（新登记）都已全量同步（data/qa/decision_propagation/report.md）。
- iter_gate r3（用 AUDIT 证据 docs/audit/RSI_r02.md 收轮）不过的项，归属如下（data/qa/iter_gate/ITERAUDIT_r3.md）：
  - K1：knowledge/RSI_LEDGER.md 第 176 行（UIAUDIT 的 UIA9）引用了 inbox 里的草案 K-OPS-Q20 → 归 UIAUDIT。
  - RL：K-UI-038 的 check 指向一个不存在的 apps/web/e2e/uiaudit/parity2_check.mjs → 归 UIAUDIT / UIRSI。
  - O1：tests/test_ref_switch_assets.py 已在 LOCKS 补了 CONSENT。
  - V1：r3 的文件在 r4 又改过，复核证据比改动旧。

## 3 改动
- 镜数上限（G29 方案 A，D-SCR-06）改成 max(8, 轮次 + 独白, ⌈总时长 ÷ 6⌉)，涉及：
  - services/agent/ns_agent/importer/script_md.py shot_cap（新增 PACE_SHOT_S = 6）
  - tools/pipeline/writer_prompt.py shot_cap（用 P3 的 target_duration_s；CONSENT 已写进 docs/uimaster/LOCKS.md）
  - tools/validate_qwen_script.py QW-E2 文案、tools/validate_script_strict.py 注释
  - config/script_chat_rules.md、docs/production_rules_v3.md、config/qwen_writer_system_prompt.txt、docs/qwen_writing_contract.md 的文字同步
  - tests/test_validate_script_strict.py 按新公式改了断言（并补了一个“镜数超上限仍 block”的用例）
  - 已出片的镜不动。
- knowledge/rules/writer_iteration.yaml K-WRT-Q07：“已知冲突”改为“已按 G29 方案 A 解决”。
- tools/qa/iter_gate.py：
  - RULE_LOOPS = {ITERAUDIT}，C1 判不适用；
  - O1 对未在 ownership.yaml 登记的 loop 直接不通过（K-OPS-Q22）；
  - 新增 tests/test_iter_gate.py::test_c1_not_applicable_for_rule_loop_and_o1_needs_registration。
- tools/qa/ownership.yaml：
  - tests/test_ref_switch_assets.py → REFLOCK；
  - REQUIREMENTS.md 改为共享（写入口 = 总调度派单）；
  - RESEARCH 登记 tools/research/**、tests/test_realism_lint.py、knowledge/rules/research_realism.yaml；
  - RECALL 条目注明“总调度认领，ITERAUDIT 为协作者”；
  - 写作合同 6 个文件暂登记给 ITERAUDIT（tests/test_decision_propagation.py 的 K-OPS-D03 用例查出无主，待确认）。
- docs/uimaster/LOCKS.md 新增 CONSENT：AUTOPILOT→ITERAUDIT（writer_prompt.py）、RECALL→ITERAUDIT（decision_check.py、owner_decisions.yaml、MASTER_PICTURE.md）、REFLOCK→ITERAUDIT（tests/test_ref_switch_assets.py）、ITERAUDIT→RESEARCH（writer_lints.py）。
- RESEARCH：K-REN-X03 从 knowledge/rules/research_realism.yaml 移到 knowledge/inbox/2026-11-01_research_x03.yaml；K-WRT-X05 补上 lint: [QW-W9]。
- K-OPS-Q22 收编进 knowledge/rules/ops_iteration.yaml（check = iter_gate O1 + 测试），草案移到 knowledge/inbox/confirmed/2026-11-01_audit_r1b_q22.yaml。
- config/owner_decisions.yaml：新增 D-SCR-06（检查 + stale_terms + propagate）。
- knowledge/RSI_LEDGER.md 第 176 行（UIAUDIT 的 UIA9）：引用的草案 K-OPS-Q20 改成 inbox 文件路径。账本只能引用已收编的规则，否则整个知识库都编不过（compile 报错）。
- tools/qa/iter_gate.py owner_of：共享条目比 owner 的通配更具体时按共享算（docs/uimaster/LOCKS.md 写 CONSENT 不再被判越界；tests/test_iter_gate.py::test_specific_shared_entry_beats_owner_wildcard）。

## 4 独立复核
待 AUDIT 按本报告复核（r3 的复核证据是 docs/audit/RSI_r02.md）。

## 5 回归
- 定向：tests/test_iter_gate.py、tests/test_decision_propagation.py、tests/test_validate_script_strict.py 全过；compile --check 通过（tools/knowledge/compile.py，402 条）：账本第 176 行引用的草案号已改成文件路径，见 §3。
- 全量 tests/：1648 过、6 不过、4 跳过、1 xfail（耗时 326.58 秒）。6 条不过就是 docs/master/MASTER_PICTURE.md G20–G24 里那几条，没有新增。

## 6 证据
data/qa/decision_propagation/report.md、data/qa/iter_gate/ITERAUDIT_r3.md、docs/uimaster/LOCKS.md、docs/audit/RSI_r02.md。

## 7 规则
K-OPS-Q22（新）；K-WRT-Q07（更新）；K-WRT-X05 补 lint；K-REN-X03 移进 inbox；D-SCR-06（决策检查）。
