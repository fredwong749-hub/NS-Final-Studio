# AUDIT · VQAGATE 复核 r02（2026-11-01 18:03–18:06，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG “17:4x VQAGATE（续，总调度 17:3x 决定）”、docs/vqa/GATE_CALIBRATION.md（17:44）、tools/vqa/after_network.py（17:42）、config/owner_decisions.yaml 里的 D-VQA-02，以及 r01 留下的 6 个未关闭问题。机读版：data/qa/audit/VQAGATE_r02.json

## 结论：r01 的问题里 4 项关闭或有了合理处置，2 项要等网络恢复（未测）。没有发现说法和事实不一致

| r01 问题 | 现状（AUDIT 复测） | 结论 |
|---|---|---|
| 1 80 镜扫完 | 还是 11 张看成（GATE_CALIBRATION §1“gpu36 隧道 16:5x 断开前”）。跳板从 16:57 起不通：night.log 16:57:08 “Connection timed out during banner exchange”；看门狗 18:03 还在报隧道探测失败。after_network.py 第 1 步：看图服务不可达就以退出码 3 退出，什么都不改 | 未测（外部条件不满足；有收尾脚本，并且是幂等的） |
| 2 标定报告 | docs/vqa/GATE_CALIBRATION.md 已交，每项都写了召回 / 误报，或写明“未测”及原因。eye_contact 只有 gaze_mp 有数（留出 27/37、25/34，误报 0/13、1/16，出处 data/acting/mp_features_v1.json），VLM 单项写的是“未测（没有阴性标签集）”。blocking 只开了 eye_contact / continuity / hair / framing / extra_person / underage；误报偏高的 posed / outfit / accessory / plastic / limbs 不拦 | 通过（数字带出处，没测到的如实写“未测”） |
| 3 video_requires_q9 | 仍是 false，但已经变成总调度的明确决定：D-VQA-02（owner_decisions.yaml 第 354 行），打开条件 = 80 镜回扫并 apply 完成，由 after_network.py 第 5 步自动改 true 并写 complete.json。decision_check 18:03：**D-VQA-02 ❌（实测 False）**，51 项里 45 ✅ / 1 ❌ / 5 跳过。这个 ❌ 是条目里写明的预期 | 通过（决定有记录、可检查、有打开条件）。风险见下面“提醒” |
| 4 ep01-S1 漏判看镜头 | GATE_CALIBRATION §2、§4 已承认 S1、S3、S5 漏检，并做了归因：这几张眼珠和头朝同一方向偏，虹膜几何分不开，网格留出最好也只到 29/37。rubric 补了“侧脸但瞳孔对镜也算”，效果待 calib_gaze 验证 | 通过（如实承认漏检，归因有数据；修复效果未测） |
| 5 producer 新代码未生效 | 笔记本 producer 进程（PID 24952）还是 15:41:20 起的，但 16:59:46 已经 pause --by SERVER_RESIDENT（CHANGELOG WORKFLOW ⑦），生产改由服务器常驻。服务器端代码要等跳板恢复后才能推上去（after_network --push）。也就是说，**目前没有任何一个正在跑的 producer 带着闸门代码** | 未测（等网络） |
| 6 vqa_skip 期间受影响的版本 | 交付里没有给出清单 | 未关闭 |

## 交叉核对
- “ep01-S5 当前被设回总调度驳回过的 v3”：和 RSI r5 的结论一致（data/audit/20261101.jsonl 第 388 行，17:39:39 在 v4 上点了“不要”，takes_ui.reject 退回到 v3）。根因（reject 退回时不查驳回）已由 RSI r5 的 K-OPS-Q23 修掉，VQAGATE 这边只做了清理。两边口径一致。
- 测试：test_vqagate / test_gen_contract 等定向测试通过；全量结果见 RSI_r03.md。

## 提醒（P1，交总调度）
- after_network.py 恢复后会**自动**把 video_requires_q9 改成 true，并推代码到两台服务器。这个开关决定视频能不能派，在无人值守时自动打开。条件是“80 镜都看成并 apply 过”，但召回本身还没过标定（eye_contact 的 VLM 召回未测），打开后被拦的镜会自动重出、占 GPU。这是总调度 17:3x 已经批过的方案，AUDIT 不反对，但建议 complete.json 写出来以后通知总调度亲审一次拦截名单，再放量。
- D-VQA-02 的预期 ❌ 会让依赖 decision_check“0 ❌”的收轮判断一直不过。建议给这类“有打开条件的待开决定”加一个 pending 状态，和真正的违规区分开（交 RECALL / ITERAUDIT）。
