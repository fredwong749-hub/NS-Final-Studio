# AUDIT · RSI r3 复核（AUDIT r02，2026-11-01 16:42–16:48，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：docs/rsi/r3_report.md（文件时间 16:41:28），以及 data/qa/iter_gate/ITERAUDIT_r3.md（16:42:04）。AUDIT 没有改产品文件。机读版：data/qa/audit/RSI_r02.json

## 结论：内容通过；收轮未通过（RSI 自己跑的 iter_gate 是 FAIL：O1 越界、L1、RL 三项不过；全量测试的说法在报告里没有出处）

## 1 逐项复测

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | compile --check OK | 16:42 跑：OK，391 条，生成物是最新的（r01 记的“生成物过期”已经消掉） | 通过 |
| 2 | 定向测试全过 | 16:42 跑：writer_lints / defect_hunt / iter_gate / decision_propagation / rsi_rule_checks / ref_switch_assets 共 46 条全过 | 通过 |
| 3 | 全量 tests/：结果见 ITERAUDIT_r3.md | ITERAUDIT_r3.md 的 T1 只跑了 46 条定向测试，里面没有全量结果，**这句话没有出处**。AUDIT 16:43–16:48 自己跑了全量：1615 过 / 8 不过 / 4 跳过（307 秒）。不过的 8 条：test_fix_ep02_round2、test_image_framing、test_image_jobs、test_review_fixes_d9、test_single_identity_face、test_unified_frame（这 6 条 RSI 都已归因到 G20–G24，并写了 owner），另 2 条是 test_vqagate::test_config_has_gate_and_new_checks、::test_request_carries_continuity_ref（VQAGATE 正在改）。test_ref_switch_assets 已经变绿，r01 记的 test_gen_contract q9 和 test_build_jobs_requires_q9 也已经变绿 | RSI 改的部分：通过；报告引用：不过 |
| 4 | decision_check 38 ✅ / 0 ❌ / 5 跳过 | 16:42 复测一致 | 通过 |
| 5 | decision_propagation 两条决定都已全量同步 | `--dry` 退出码 0：D-VID-01 ✅、D-VQA-01 ✅。抽查了这是真改还是绕过：docs/vqa/STATE.md 第 16、21、23、58–60 行，SOP_production.md 第 212 行，都改写成了“转拦截 / enforce=true / 没看图 = untested（挡）”，16:39–16:40 改的；stale_allow 只多了审计报告和 MASTER_PICTURE（这两处记录的是决定本身，可以接受）；night.py 第 352 行配方改成读 recipe_choice.json | 通过 |
| 6 | G20：林晚身份脸是整张 4 栏设定图 | data/looks/face_overrides.json series10_v1.lin_wan = ar-f9519334bc.png（10:58:28，by fred）；character_hub_log.jsonl 第 28 行 action=face、第 29 行把 lin_wan_face_ref2va.png 驳回为“画质差”。我自己看了这张图：1984×1120，四栏（半身特写 + 正面 + 侧面 + 背面全身），不是脸部裁切 | 通过（归因属实） |
| 7 | G21：first_frame_jobs.json 是 10:32 生成的，已过期 | 文件修改时间 10:32:11 | 通过 |
| 8 | 无检查规则 141 → 128 | `iter_gate --list-unchecked` 16:42：128 / 391 | 通过 |
| 9 | K-WRT-Q07 写作规则完整 | knowledge/rules/writer_iteration.yaml 第 188–204 行：targets writer_prompt、writer_text、lint [QW-T1, QW-T2]、check 都有；writer_lints.py 第 29–30、167–178 行固定 warn；writer_knowledge.md 里能找到 | 通过 |
| 10 | ownership：6 个没有 owner 的文件已登记 | ownership.yaml 第 40–41 行归 VQAGATE；第 82 行 SOP_production 设为共享 | 通过（见 §3 第 2 条） |
| 11 | 收轮 | ITERAUDIT_r3.md = **FAIL**：O1 越界 3 个（decision_check.py、owner_decisions.yaml、MASTER_PICTURE.md 都属于 RECALL，docs/uimaster/LOCKS.md 里没有 RECALL → RSI 的授权行）；L1 报告引用了当时还不存在的 ITERAUDIT_r3.json/.md；RL 把 K-OPS-D03 判成“写作规则不完整” | 不过 |

## 2 G0
- 节奏慢：RSI 的结论是 G29 是结构性原因（镜数上限 max(8, …) × 6 秒 < 50 秒下限）。它的处理是加 warn 级 lint 并把 K-WRT-203 标 ⤴，**根因还没修**：tools/pipeline/writer_prompt.py 第 109 行“镜数 6–{shot_cap}”仍是原样。G29 已经按 G0 写明“总调度定 → AUTOPILOT（writer_prompt / importer）”。在镜数上限改掉之前，K-WRT-Q07“先加镜”和镜数上限还是冲突的，QW-T2 会一直报。可以接受（已经交给 owner），但不能把 G29 记成已修。
- G20 RSI 记成 P0，路线是“总调度问项目方”。身份脸属于项目方闸门（identity_refs），AUDIT 同意不能由 loop 自己改回去。

## 3 问题
1. **（P1）O1 越界**：r2、r3 都改了 RECALL 的 config/owner_decisions.yaml，r3 还改了 decision_check.py 和 MASTER_PICTURE.md，都没有授权行。要么总调度在 LOCKS 补 `CONSENT: RECALL -> RSI : ...`，要么把这些改动交给 RECALL 来做。
2. **（P2）docs/REQUIREMENTS.md 归 VQAGATE 不合适**：这是全项目记录项目方原话的文档，各个 loop 都要往里追加。现在归给 VQAGATE 一家，以后其它 loop 写 REQUIREMENTS 都会被 O1 判越界。建议设为共享，写入口 = 总调度派单，和 SOP_production 一样。
3. **（P2）RL 判 K-OPS-D03 不完整**：起因是 AUDIT 在 inbox 草案里给的 link 带了 P0-P1，被当成了写作规则。现在 ops_decisions.yaml（16:42）里的 link 已经是 [P11-RETRY]，RSI 重跑 iter_gate 应该就能过。这一条是 AUDIT 草案的问题，不扣 RSI。
4. 报告第 5 节的全量测试要写上实际数字和来源，可以直接引用本文件：1615 / 8 / 4。

## 4 给 RSI
- 拿本文件作为 `--verify-evidence`，重跑 `iter_gate --loop RSI --round r3 --verifier AUDIT`。O1 要等总调度补授权或改为转交以后才能过。
