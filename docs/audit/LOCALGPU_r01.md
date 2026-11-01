# AUDIT · LOCALGPU 复核 r01（2026-11-01 19:21–19:23，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG 里 LOCALGPU 的两条记录（18:25、19:19），data/ab/localgpu_verify/、tools/localgpu/check_lane.py、config/render_endpoints.json 的 laptop:0、K-OPS-L01、tests/test_localgpu_lane.py。机读版：data/qa/audit/LOCALGPU_r01.json

## 结论：通过（本机道出的图和服务器一致，数字我复算过）。轮流用卡（看图服务和出图共用一张卡）没过验收，LOCALGPU 自己如实写了“未通过”

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | 用同一套工作流复现服务器 ep01-S4_vN s20261311 / 12 的原图：MAE 1.96 / 2.00，PSNR 32.1 / 32.2 dB | AUDIT 自己用 numpy 对比 data/pipeline/runs/series10_v1/images/reflock_val/v9/ep01-S4_vN_s2026131{1,2}_raw.png 和 data/ab/localgpu_verify/repro_S4_vN/…_local_raw.png：**MAE 1.96 / 2.00，PSNR 32.1 / 32.2**，完全一致。我看了 cmp_S4_vN_s20261311.jpg：左右两张构图、人物、光线一样，差异图里只有边缘有细线（浮点 / 显卡差异级别） | 通过 |
| 2 | ep01-S1 当前作业本机出图，图结构和作业记录零差异 | ep01-S1_local_s20261201.json：graph_diffs_vs_job_record = []，preset frame_v9，后处理 lanczos 1152×2016 → 768×1344 + USM 1.2 / 60 / 2（和 L-087 的 S★ 一致），显存峰值 11340 MiB | 通过 |
| 3 | check_lane.py（K-OPS-L01）：道记录不带出图参数，参数和 leica_sstar 逐项相同 | 19:4x 跑 `tools/localgpu/check_lane.py`：退出码 0，"ok": true（没加 --live / --sha，所以 ComfyUI 节点和模型 sha 这两项这次没测）。K-OPS-L01 的 check = [tests/test_localgpu_lane.py, tools/localgpu/check_lane.py] | 通过（--live / --sha 未测） |
| 4 | 测试 | tests/test_localgpu_lane.py 和 push_check、syntax_guard 一起跑，25 条全过 | 通过 |
| 5 | producer 的 image_only / hold 改动 | render_endpoints.json laptop:0：image_only=true，hold=**false**（_hold_change：“19:2x 总调度选 A：本机道开派，本机看图停（Q9 记未测待补判）”）。按 18:25 的记录，jobs.py 不给 image_only 道派视频，producer 出图道表并进了 image_only 道。代码只读了 CHANGELOG 和配置，测试覆盖由 test_localgpu_lane 提供 | 通过 |
| 6 | 轮流用卡（看图服务和出图同卡） | 19:19 记录：看图服务单条判定峰值 13293 MiB，超过卡上的 12282 MiB，单条要 9–18 分钟 → 验收没过，本机只出图、不在本机看图 | 未通过（如实写了） |

## 提醒（交 VQAGATE / 总调度）
- 本机道开派以后，这些图的 Q9 是“未测”。config/vqa.json 的 gate.untested_blocks=true，所以它们在补判之前不会被设为当前，也不会进视频（D-VQA-02 打开以后）。这和“Q9 记未测待补判”的口径一致，**但会积压**：要有人在服务器看图服务恢复后批量补判（after_network.py 的 scan --resume 能不能覆盖本机出的新版本，需要 VQAGATE 确认）。
- 我在 cmp 图里看到一个内容问题（不是 LOCALGPU 的问题，是出图本身的）：服务器原图和本机图里，**顾沉右手上都长着林晚的“冰川满钻尖甲”**，林晚的单品参考漏到了第二个人身上。这是 reflock_val 的旧验证图，交 REFLOCK / VQAGATE 看现行出图有没有同样的单品串人问题（建议加进 DEFECT_HUNT 一类）。
