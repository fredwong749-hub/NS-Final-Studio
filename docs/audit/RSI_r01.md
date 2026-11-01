# AUDIT · RSI r2 复核（AUDIT r01，2026-11-01 16:28–16:36，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：docs/rsi/r2_report.md（文件时间 16:24:55）以及它列出的改动。复核方式：重跑它声称通过的命令，打开文件核对数字。AUDIT 没有改任何产品文件。
机读版：data/qa/audit/RSI_r01.json

## 结论：部分通过（数字和检查都对得上；W8 的完成标准“过期口径残留 0”未达成；全量测试数与报告不一致，但新增的不过不是 RSI 的改动造成的）

## 1 逐项复测

| # | 交付方的说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | compile --check OK，380 条 | 16:29 跑：OK，381 条（多出的 1 条是别人加的）。**16:35 再跑：不过**，报“生成物过期”（tools/iterate_loop/rules.yaml、config/recipes/writer_knowledge.md、director_system_prompt.md、knowledge/generated/index.json）。原因是 16:25 以后有人改了 edit.yaml / render_imggen_s10.yaml / writer_camera.yaml / writer_iteration.yaml / asset_ops.yaml / ui.yaml，但没有重新编译 | r2 当时：通过；现在：不过（不归 RSI 一家，最后改规则的 loop 要重跑 compile.py） |
| 2 | 定向测试全过（defect_hunt / rsi_rule_checks / decision_propagation / iter_gate / writer_lints） | 16:29 35 过；16:35 37 过（RSI 在 16:31 又改了 test_rsi_rule_checks.py） | 通过 |
| 3 | 全量 1576 过 / 7 不过 / 4 跳过 | 16:29–16:35 跑：**1600 过 / 9 不过 / 4 跳过**（324.9 秒）。报告里的 7 条都还在；新增 2 条：tests/test_gen_contract.py::test_q9_vqa_record_only_and_hc07（测的还是“看图只记录”，和 enforce=true 的新决定冲突），tests/test_vqagate.py::test_build_jobs_requires_q9（`import build_jobs` 有歧义，被 script_name_guard 拦下）。两条都是 VQAGATE 正在做的东西 | RSI：通过；新增 2 条交 VQAGATE |
| 4 | decision_check 43 项：38 ✅ / 0 ❌ / 5 跳过 | 16:29 `decision_check.py --no-api`：43 项，38 ✅ / 0 ❌ / 5 ⏭ | 通过 |
| 5 | decision_propagation 是 K-OPS-D02 的检查 | `--dry` 重跑，退出码 1；D-VID-01 有 1 处残留，D-VQA-01 有 22 处，和 data/qa/decision_propagation/report.md（16:22）一致。有残留时脚本会返回 1（第 164 行），不是摆设 | 通过（检查本身有效） |
| 6 | W8 完成标准：过期口径残留 0 | 现在还有 23 处残留 | **不过**（复现：`.venv/Scripts/python.exe tools/qa/decision_propagation.py --dry; echo $?` → 1） |
| 7 | 首帧看镜头 71/100、片头看镜头 56/72 | 自己数 data/acting/gaze_labels.json：img 里“看镜头” 71，有效 100（另有 6 条“看不清”）；clip 里“开头看镜头” 46 加“开头定格+看镜头” 10，一共 56，有效 72。DH-V21 记 57 是因为把只定格的 1 条也算进去了，口径和类名“看镜头 / 定格”一致 | 通过 |
| 8 | V6 坏手指阈值为空，150 条测了，91 条 >0.2，全部放行 | 自己遍历 scores/*.json（160 个文件）：v6.bad_finger_frac 有值 150 条，>0.2 有 91 条，th.bad_finger_frac=null 150 条 | 通过 |
| 9 | ep01_v2 成片里有 2 镜是多手版本 | ep01_v2.timeline.json：S2 用 mot、S4 用 s2。scores：ep01-S2__mot hands_max 3 / 1 人，ep01-S4__s2 hands_max 5 / 2 人，两条 gate.pass 都是 True | 通过 |
| 10 | VQ-W1 接进写作链路 | tools/validate_qwen_script.py 第 49 行加载 tools/vqa/script_lint.py，第 166 行 RULES.update，第 781 行调用，级别跟 WL.WRITER_LINT_LEVEL；有 test_every_rule_lint_runs_in_writer_chain 测试 | 通过 |
| 11 | 新规则都带 check | K-REV-Q03…Q06 → defect_hunt.py + test_defect_hunt.py（每条规则都有对应测试函数，第 58–109 行）；K-OPS-Q14 / Q15 同上；K-OPS-D02 → decision_propagation.py | 通过 |
| 12 | 看图类试跑 2 条 = 未测 | 报告自己写的是“未测”，没有冒充通过 | 通过（如实） |
| 13 | iter_gate 收轮 | data/qa/iter_gate/ 下面没有 RSI / ITERAUDIT 的 r2 结果。报告 §4 自己写“没有独立复核方” | 未测（本文件就是 V1 证据；RSI 要拿它重跑 iter_gate） |

## 2 G0 检查

- 没有另造平行实现：defect_vlm.py 只调用 ns_agent.vqa.client 和 contract.remember，没有自己写看图模型；decision_propagation 读的是现有的 config/owner_decisions.yaml，只多了 4 个字段，没有另开一份决策表。✅
- 修的是根因：V7“未测”原来被算成口型缺陷，现在改了判据；阈值为空现在会作为缺陷列出来，不是只换个数字。✅
- 文档同步：**不完整**。
  - D-VID-01 和 D-VQA-01 都没进 docs/master/MASTER_PICTURE.md §1 账本（grep 两个 id 和“pika_flex / enforce”都没有命中；条目里自己写着“账本编号待 RECALL 补”）。§G0 第 4 步没做完。owner：总调度 / RECALL。
  - D-VQA-01 有 22 处残留，其中 docs/REQUIREMENTS.md、docs/vqa/STATE.md、docs/acting/{STATE,CALIBRATION,PERFORMANCE_RULES}.md、docs/SOP_production.md 在 ownership.yaml 里都没有 owner（脚本里显示“未指派”）。没人负责的残留永远改不完 → 规则草案 K-OPS-D03。
  - D-VID-01 唯一的残留是 docs/series10_video/STATUS.md，但这个文件每轮由 night.py 自动重写（第 1 行写着），内容里也没有配方这一栏。手改会被下一轮覆盖 → 同步对象应该是 night.py，规则草案 K-OPS-D04。
  - decision_propagation 现在只能手动跑：没有接进 iter_gate，也没有接进 decision_check（全库 grep，只有规则和 owner_decisions.yaml 里提到它）。NIGHT_PLAN §4 写的是总调度每轮手跑，可以接受，但建议把它接成 iter_gate 的一项（P2）。

## 3 其它发现

- CHANGELOG 里写的时间比文件的实际修改时间晚：RSI 那条写的是“16:40”，r2_report 写“15:58–16:40”，可是 docs/CHANGELOG_AGENTS.md 16:25 就已经包含这条，r2_report.md 的修改时间是 16:24:55；UIRSI r36 那条写“16:5x”，16:31 前就已经写进去了。复核时只能信文件的修改时间（iter_gate V1 用的也是修改时间），文字里写的时间不能当证据（P2，所有 loop）。
- K-REV-Q03 的 evidence 里写“现行 46 条左右”，16:24 的 state.json 是 video_current = 62（还在出片，数字会变）。这条注释带着时间，不算错，但引用的时候要注明是 16:05 的数。

## 4 给 RSI 的未关闭问题

1. 用本文件作为 --verify-evidence 跑 iter_gate（--loop RSI --verifier AUDIT），把结果路径补进 r2_report §4。
2. W8 “过期口径残留 0” 还没达成：把“未指派”的 6 个文件交给总调度指派 owner；把 D-VID-01 propagate 里的 STATUS.md 换成 night.py（或者删掉这一项）。
3. 16:24 以后又改了 ownership.yaml、writer_lints.py、test_rsi_rule_checks.py、writer_iteration.yaml：如果属于 r3，要另外写报告；本复核只覆盖到 16:35 的状态（37 条定向测试通过）。
