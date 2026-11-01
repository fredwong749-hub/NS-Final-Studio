# AUDIT · PROD 复核 r02（2026-11-01 18:05–18:06，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG “17:30 后（PROD，W5）”和“17:00 后（PROD，续）”两条记录，加上 r01 留下的未关闭问题。机读版：data/qa/audit/PROD_r02.json

## 结论：W5 编译器改动通过；W5 的完成标准“ep05-S3/S5 一次出对”未测（还没出图）；W4 改成“服务器合成”后，ep01_v3 仍然没做（跳板断了）

| # | 说法 / 完成标准 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | 手部参考只取两只手（_hand_pair，*_hand2.png），躯干占比 torso_share > 0.35 不送 | services/agent/ns_agent/asset_refs.py 第 423 行 _hand_pair、第 447 行 torso_share、第 817–820 行超过阈值就不作参考并写原因。我自己看了 data/pipeline/runs/series10_v1/images/refcrops/ch_a_lan_lookA_v2_s101_front_hand2.png（17:46，152×246）：左右两只黑皮手套加前臂，没有躯干和脸，是对的 | 通过 |
| 2 | 手 + 肩颈局部（framing “手与肩颈”） | framing.py 第 169–174 行：动作写到肩、颈时，局部范围扩大为“手与肩颈”；第 200 行有英文对照；part_lock 保留发色句 | 通过 |
| 3 | QW-W10 + 规则 K-AST-V10 / K-REN-V11 / K-WRT-V10 | writer_lints.py 第 12、37 行，级别 warn；compile --check 18:03 通过（414 条） | 通过 |
| 4 | 测试 | test_image_framing、test_writer_lints、test_gen_contract 等 84 条全过（18:05）。之前一直红的 test_image_framing::test_closeup_subject_and_lead（G22）现在也过了 | 通过 |
| 5 | W5 完成标准：ep05-S3/S5 一次出对 | 只做了试编译（CHANGELOG 记的是 preflight ok）。data/renders/ep05/S3/takes/ 最新的首帧还是 16:22 的 image_009，之后没有新图 | 未测 |
| 6 | W4：改成服务器合成，原片不拉回笔记本 | sync.py 拉原片改成 night_control.json "pull_clips": true 才做（默认关）；方案写在 docs/series10_video/SERVER_ASSEMBLY.md。CHANGELOG 自己写了“17:00–17:15 跳板连不上，ep01_v3 服务器合成未做” | 方向通过（符合总调度 G0）；ep01_v3 未测 |
| 7 | deploy.py 探测 ssh 失败时这轮不推（16:57 曾把 36 MB 视觉模型塞进包） | night.log 16:57:08 那次确实推了 48.1 MB 然后超时，修复的就是这个；代码没有逐行复核 | 未测（只核对了起因） |

## 小问题
- hand2 是两块裁切横向拼起来的，中间有一条黑色竖线（拼缝）。图很小（152×246），作为参考图可以用，但出图模型可能把这条线当成画面里的东西。建议拼接处留白或用背景色（P2）。

## 给 PROD
1. 跳板恢复、全量重做开始以后，ep05-S3/S5 的新首帧出来要通知复核：看是不是两只手 + 肩颈局部、发色对不对、有没有冒出成年人的脸。
2. ep01_v3（服务器合成）做完以后，补一张 v3 和 v2 同一帧的对比。
