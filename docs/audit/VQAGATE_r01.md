# AUDIT · VQAGATE 复核 r01（2026-11-01 16:52–16:53，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG 里 VQAGATE 的交付记录（“16:5x VQAGATE fredw-2b 派”）、config/vqa.json、data/vqa/gate_scan/latest.json（16:50）、tests/test_vqagate.py。
对照 NIGHT_PLAN W1 的完成标准：80 镜首帧全扫完；拦截项有召回 / 误报数；ep01 点名的镜头被拦并进入重出；producer 不再卡在“等总调度复核”。
AUDIT 没有改产品文件，也没有跑 gate_scan apply / redo。机读版：data/qa/audit/VQAGATE_r01.json

## 结论：代码和测试通过；W1 完成标准 4 项里 0 项达成（不通过 / 未生效）

| # | 完成标准 / 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | 测试 | tests/test_vqagate.py + tests/test_gen_contract.py：52 条全过。r01 / r02 记的 3 条红测试已经变绿 | 通过 |
| 2 | 80 镜首帧全扫完 | data/vqa/gate_scan/latest.json（16:50:50）只有 **18 行**（ep01 全部 7 镜、ep02 8 镜、ep03 3 镜），其中 **8 行没有结果**（ep02-S1…S6、ep03-S1、S2：defects = null） → 有结果的只有 10/80 | **不通过** |
| 3 | 拦截项有召回 / 误报数 | config/vqa.json 的 gate._doc 说 blocking 名单“按 data/vqa/gate_calib/report.json 定”，_enforce 说“按 docs/vqa/GATE_CALIBRATION.md 定”，**这两个文件都不存在**。只有 gaze_mp 有标定数字（data/acting/mp_features_v1.json：留出召回约 0.73，误报 0/13、1/16）。_blocking_v1 自己写了 outfit / accessory / plastic_doll / posed_stiff / extra_limbs 在首扫的命中率 30–60%，和标签对不上，所以没开拦截 | **不通过**（blocking 名单没有可核对的召回 / 误报出处） |
| 4 | ep01 点名镜头被拦并进入重出 | 扫描结果：ep01-S4、S6、S7 判了 eye_contact；S5 判了 hair / continuity。**但 ep01-S1 take 14 被判全部 ok**。我自己看了这张交付图（renders/ep01/S1/takes/image_014_27f6d482_raw_post.png）：林晚在打字，眼睛正对镜头。这是项目方点名的“眼睛对着镜头”，闸门漏了（gaze_mp 旁证也没有判出来）。另外，是否“进入重出”要靠 producer，见第 6 条 | **不通过**（至少漏 1 镜） |
| 5 | 图片闸门先于视频（D-VQA-01 / D3：“image 做出来后先检测再跑视频”） | config/vqa.json 第 80 行 **`"video_requires_q9": false`**。ns_agent/vqa/contract.py 第 141 行：这个值为 false 时 q9_passed 恒为真，build_jobs 照样给没过闸门的首帧派视频。CHANGELOG 写的是“build_jobs.passed_frames 要求 Q9（gate.video_requires_q9）”，但开关是关着的；decision_check D-VQA-01 只断言 judge.enforce，查不到这一项 | **不通过**（说法和配置不一致；决定的后半句没落地） |
| 6 | producer 不再卡在“等总调度复核”（auto_review_redo） | 代码在，但 CHANGELOG 自己写了“需重启：producer、:8800”。Get-CimInstance 查到 producer.py serve 进程创建时间是 15:41:20，在这些改动之前，**到 16:58 没有重启** → 跑着的 producer 还是旧代码，拦截和自动复核都没生效 | 未生效 |

## G0
- 复用了已有闭环（contract / postflight / producer / rescore_takes.write_back / auto_current），没有另造检测器。✅
- 文档同步：decision_propagation 返回 0（RSI_r02 已核对，是真改的）。但 decision_check 的断言只覆盖 judge.enforce，没有覆盖 gate.video_requires_q9，所以“图片过闸门后才进视频”这半句决定没有机检 → 建议在 owner_decisions.yaml 给 D-VQA-01 加一条 video_requires_q9 = true 的断言（RECALL）。
- 16:24–16:47 rubric 模板里的 {continuity} 占位符让正在跑的旧进程报 KeyError（vqa_skip），已经修了并加了回归测试。这 23 分钟里出的图有没有因为 vqa_skip 记成 untested、被挡或者被放过，要列出清单。

## 复现
1. `PYTHONUTF8=1 .venv/Scripts/python.exe -c "import json;r=json.load(open('data/vqa/gate_scan/latest.json',encoding='utf-8'))['rows'];print(len(r),sum(x.get('defects') is None for x in r))"` → `18 8`
2. `sed -n 80p config/vqa.json` → `"video_requires_q9": false,`
3. `ls docs/vqa/GATE_CALIBRATION.md data/vqa/gate_calib/report.json` → 都不存在
4. 打开 data/renders/ep01/S1/takes/image_014_27f6d482_raw_post.png 看视线；对照 latest.json 里 ep01-S1 的 eye_contact = ok

## 给 VQAGATE / 总调度的未关闭问题
1. 把 80 镜扫完（data/vqa/gate_scan/latest.json），没有结果的镜写原因。
2. 交标定报告（GATE_CALIBRATION.md / gate_calib/report.json）：每个 blocking 项的召回 / 误报和样本数。
3. video_requires_q9 要么改成 true，要么写明为什么暂时 false、由谁拍板。现在的状态不符合 D-VQA-01 的后半句。
4. ep01-S1 漏判看镜头：查 eye_contact 判据和 gaze_mp 为什么都没拦住。
5. 重启 producer 和 :8800 要按派单走（AUDIT 不做重启）；重启后再复核“等总调度复核”是否消失。
6. 列出 16:24–16:47 vqa_skip 期间受影响的版本。
