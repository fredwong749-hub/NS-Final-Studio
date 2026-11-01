# AUDIT · RSI r4 + r5 复核（AUDIT r03，2026-11-01 18:03–18:22，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：docs/rsi/r4_report.md（17:16）、docs/rsi/r5_report.md（18:00）、data/qa/iter_gate/ITERAUDIT_r4.md（17:17）、ITERAUDIT_r5.md（18:01:53，INCOMPLETE，只差 V1）。机读版：data/qa/audit/RSI_r03.json。
本文件就是 r5 收轮要用的 V1 证据（时间晚于 r5 的最后一次改动）。

## 结论：通过

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | G29 方案 A：镜数上限 = max(8, 轮次 + 独白, ⌈总时长 ÷ 6⌉) | importer/script_md.py 第 723 行 shot_cap 的文档和实现；writer_prompt.py 第 77–80 行 `max(8, 对白+独白, -(-target//6))`，目标 60 秒时上限 10。被取代的旧口径标了 ⤴。D-SCR-06 在 decision_check 里是 ✅，decision_propagation 显示已全量同步。CONSENT AUTOPILOT → ITERAUDIT 已登记 | 通过（AUDIT r02 指出的根因已修） |
| 2 | K-OPS-Q22 收编（O1 对没登记的 loop 直接判不通过） | ops_iteration.yaml 收编；有 tests/test_iter_gate.py 的新用例；草案移到 inbox/confirmed | 通过 |
| 3 | AUDIT r02 的其它问题 | REQUIREMENTS 改为共享 ✅；RESEARCH 已登记 ✅；K-REN-X03 移进 inbox、K-WRT-X05 补 lint ✅；RECALL 文件补了 CONSENT ✅ | 通过 |
| 4 | G20 身份脸重裁（L-086） | data/looks/face_overrides.json → data/assets/identity_refs/lin_wan/lin_wan_face_hd_A_s202.png（17:43:17，478×479）。**AUDIT 看了图**：只有头部，头顶到下巴，蓝色长发和刘海都在，不带项链和衣服，是脸部裁切。下巴离下边缘很近，但没有被切掉。登记人写的是“总调度代录（项目方 AskUserQuestion 只是嫌画质差）” | 通过 |
| 5 | G21 首帧作业清单重编 | first_frame_jobs.json（17:45:34）：80 个作业里 70 个挂新脸（新脸文件名出现 280 次），旧设定图 ar-f9519334bc 出现 0 次 | 通过 |
| 6 | K-OPS-Q23：改当前版本只走 set_active 一个入口，并留审计 | AUDIT 自己用 active_audit.why_ineligible 只读扫了 80 份 takes.json：当前版本指向“不能当当前”的 0 处。current_changes.jsonl 第 136 行有 ep05-S3 清空 v7 的记录（actor = RSI active_audit，总调度 r5 指派，改前有备份 takes.before_KOPSQ23）。ep05-S3 v7 确实是 10:21 总调度驳回过的（同一文件第 117 行）。另外和 VQAGATE 17:4x 查到的 ep01-S5 那条对得上 | 通过 |
| 7 | compile / decision_check | 18:03：compile OK（414 条）；decision_check 51 项，45 ✅ / 1 ❌（D-VQA-02，预期）/ 5 跳过；decision_propagation 返回 0（4 条决定都 ✅） | 通过 |
| 8 | 全量 1669 过 / 3 不过 | AUDIT 18:03–18:09 跑：**1682 过 / 5 不过 / 4 跳过 / 1 xfail**。不过的：test_fix_ep02_round2（G24，已知）；test_acting_lints::test_good_single_person_clean、test_rules_v3::test_shot_rules[kw24/kw25-QW-D1-block]、test_revisions_p1_ux6::test_keep_old_requires_owner_and_only_one_rev。后 4 条我单独复跑过，这 3 个文件 89 条全过。跑测期间 tools/qa/acting_lints.py、tools/validate_qwen_script.py 被别的 loop 改过（修改时间晚于 18:03），所以是并行改动造成的一过性失败，不是 RSI 的改动造成的。G22（test_image_framing）、G23（test_review_fixes_d9）这次也是绿的 | 通过（RSI 的改动没有引入回归） |

## 提醒
- face_crop_check 会拒掉整张设定图（宽高比 1.77）。项目方以后在界面上再点“设为身份脸”时，会被这一项拦住；UIRSI r37 的 PeopleHub 已经改成“非脸部裁切只给说明”。前后端口径一致。
- 写作合同的 6 个文件暂时归 ITERAUDIT（r4 §3 写了“待确认”），总调度要定一个最终 owner。

## 给 RSI
- 用本文件作为 --verify-evidence 重跑 `iter_gate --loop RSI --round r5 --verifier AUDIT`。
