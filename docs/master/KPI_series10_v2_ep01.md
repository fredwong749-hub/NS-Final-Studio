# KPI series10_v2 ep01（L-205：一集 ≤ 50.0 min）

生成：2026-11-07T19:26:23（JST）· 工具 tools/master/episode_kpi_report.py · 预算来源 docs/master/PIPELINE_CHECKLIST.md（base 档）
起点：11-06 14:54:52（锚点 regen：regen L-204-psm11-全集重出-sv07 @ 11-06 14:53:00）· 截至：11-07 19:26:23 · 状态：✅ 已完成
**用时 789.9 min / 预算 50.0 min → 超 739.9 min**；归因（min）：逻辑 300、代码 9、GPU 调度 95、检测 336
镜头 16 个（成人镜不计：无）· 道 6 条

## 1. 阶段耗时 vs 预算

| 阶段 | 起 | 止 | 实际 min | 预算 min | 超 min | 状态 | 归因 逻辑/代码/GPU 调度/检测 | 备注 |
|---|---|---|---|---|---|---|---|---|
| 导入 / 探针 | 11-06 14:49:28 | 11-06 14:54:52 | 5.4 | 2.5 | 2.9 | 完成 | 3/0/0/0 | 导入 11-06 14:49:28（L-204 psm11：出图前全量离线检查 32/32 全绿（首尾帧设想 + 5 背景视向 + 过肩前景局部不露脸））→ 第一次派单 11-06 14:54:52 |
| 首帧 | 11-06 14:54:52 | 11-06 16:51:14 | 116.4 | 20.0 | 96.4 | 完成 | 0/1/17/78 | 定下 16/16 |
| 尾帧 | 11-06 15:11:52 | （截至 until） | 1694.5 | 8.0 | 1686.5 | 进行中 | 854/0/77/756 | 定下 15/16；未定：S8 |
| 视频 | 11-06 15:54:41 | 11-06 19:23:15 | 208.6 | 15.0 | 193.6 | 完成 | 136/6/52/0 | 定下 16/16，窗口内提交 17 段；沿用起点前片段（night 落定）：S1, S9, S11, S14, S15 |
| 合成 | 11-06 19:23:15 | 11-06 19:40:43 | 17.5 | 8.0 | 9.5 | 完成 | 8/1/0/0 | night 主机 gpu36；合成周期 4 次（REOPEN 重开 2）；最近成片 ep01_v65_post.mp4 v65 |
| 拉回交付 | 11-06 19:40:43 | 11-07 04:04:43 | 504.0 | 3.0 | 501.0 | 完成 | 501/0/0/0 | 本机 ep01_v65_post.mp4 52 MB，拉回完成 11-07 04:04:43 |

整集超预算 739.9 min → 逻辑 300 / 代码 9 / GPU 调度 95 / 检测 336（证据权重秒：逻辑 44728, 代码 1402, GPU 调度 14153, 检测 50124）。超预算分钟按各类证据秒数的比例分配（最大余数法，和 = 超预算分钟）；证据秒数是并行道上的叠加，不等于墙钟。

## 2. 每道 GPU 忙时（按作业类型，窗口内；忙 s = 同道区间并集）

| 道 | 首帧 s（张） | 尾帧 s（张） | 视频 s（段） | 忙 s | 纯 GPU s | 利用率 % | 空卡有活 min |
|---|---|---|---|---|---|---|---|
| gpu33:0 | 6003（10） | 17267（34） | 404（1） | 14700 | 14352 | 31.0 | 21 |
| gpu33:1 | 7731（13） | 5615（9） | 828（4） | 8166 | 7824 | 17.2 | 123 |
| gpu33:3 | 4633（6） | 7233（10） | 0（0） | 6763 | 6299 | 14.3 | 147 |
| gpu36:0 | 6408（7） | 1162（1） | 2272（5） | 6444 | 5606 | 13.6 | 152 |
| gpu36:1 | 5043（6） | 1066（1） | 1775（4） | 5158 | 4919 | 10.9 | 174 |
| gpu36:2 | 2966（4） | 2756（3） | 1372（3） | 4533 | 4420 | 9.6 | 184 |

## 3. 每帧尝试与失败原因

派单 113 · 出图 104 · 过 11 · 契约没过 72 · 打分故障 0；失败原因：FL×39, Q1×19, Q10×6, G1×5, Q9×3, Q6×2

| 帧 | 派单 | 出图 | 结论 | 出图中位 s | 打分中位 s | 定下 | 道 |
|---|---|---|---|---|---|---|---|
| first:ep01-S1 | 3 | 3 | redo_fail×2, best_effort×1 | 842.0 | 45.0 | best_effort 11-06 15:40:19 | gpu33:0,gpu33:3 |
| last:ep01-S1 | 0 | 0 | — | — | — | passed（起点前） 11-05 23:37:27 |  |
| first:ep01-S2 | 7 | 5 | redo_fail×4, best_effort×1 | 599.0 | 60.0 | best_effort 11-06 16:19:23 | gpu33:0,gpu33:1,gpu36:0,gpu36:1 |
| last:ep01-S2 | 2 | 2 | content_fail×1, passed×1 | 986.0 | 45.0 | passed 11-06 15:46:06 | gpu33:0,gpu36:2 |
| first:ep01-S3 | 2 | 1 | redo_auto_approved×1 | 694.0 | 106.0 | redo_auto_approved 11-06 15:11:12 | gpu36:0,gpu36:1 |
| last:ep01-S3 | 1 | 1 | passed×1 | 759.0 | 148.0 | passed 11-06 15:27:16 | gpu33:3 |
| first:ep01-S4 | 3 | 3 | redo_fail×2, redo_auto_approved×1 | 629.0 | 143.0 | redo_auto_approved 11-06 15:38:23 | gpu33:1,gpu36:2 |
| last:ep01-S4 | 13 | 13 | passed×1, content_fail×8, best_effort×4 | 624.0 | 11.0 | last_unavailable（兜底） 11-06 17:59:23 | gpu33:0,gpu33:1,gpu33:3 |
| first:ep01-S5 | 6 | 5 | redo_fail×4, redo_auto_approved×1 | 604.0 | 106.0 | redo_auto_approved 11-06 16:23:32 | gpu33:0,gpu36:0,gpu36:1,gpu36:2 |
| last:ep01-S5 | 7 | 6 | content_fail×5, passed×1 | 609.0 | 46.0 | passed 11-06 16:51:15 | gpu33:0,gpu33:1,gpu33:3,gpu36:1 |
| first:ep01-S6 | 2 | 1 | redo_auto_approved×1 | 639.0 | 132.0 | redo_auto_approved 11-06 15:11:18 | gpu33:1,gpu36:2 |
| last:ep01-S6 | 1 | 1 | passed×1 | 999.0 | 132.0 | passed 11-06 15:38:15 | gpu36:2 |
| first:ep01-S7 | 2 | 2 | redo_fail×1, redo_auto_approved×1 | 1107.0 | 207.0 | redo_auto_approved 11-06 15:43:48 | gpu36:0 |
| last:ep01-S7 | 6 | 6 | content_fail×4, best_effort×1, passed×1 | 572.0 | 100.0 | passed 11-06 16:58:24 | gpu33:0,gpu33:1,gpu36:2 |
| first:ep01-S8 | 1 | 1 | redo_auto_approved×1 | 743.0 | 92.0 | redo_auto_approved 11-06 15:12:37 | gpu36:1 |
| last:ep01-S8 | 0 | 0 | — | — | — | 未定 |  |
| first:ep01-S9 | 3 | 3 | redo_fail×2, best_effort×1 | 653.0 | 50.0 | best_effort 11-06 15:40:47 | gpu33:0,gpu33:1,gpu36:2 |
| last:ep01-S9 | 23 | 23 | content_fail×23 | 572.0 | 57.0 | hard_cap_exhausted 11-06 19:14:46 | gpu33:0,gpu33:1,gpu33:3,gpu36:1 |
| first:ep01-S10 | 0 | 0 | — | — | — | redo_auto_approved（起点前） 11-06 14:53:10 |  |
| last:ep01-S10 | 3 | 2 | content_fail×1, passed×1 | 1163.0 | 67.0 | passed 11-06 16:34:46 | gpu33:3,gpu36:0,gpu36:2 |
| first:ep01-S11 | 6 | 6 | redo_fail×4, rescore×1, best_effort×1 | 593.0 | 65.0 | best_effort 11-06 16:51:14 | gpu33:0,gpu33:1,gpu36:0 |
| last:ep01-S11 | 0 | 0 | — | — | — | passed（起点前） 11-06 10:04:38 |  |
| first:ep01-S12 | 1 | 1 | redo_auto_approved×1 | 623.0 | 98.0 | redo_auto_approved 11-06 15:15:59 | gpu33:1 |
| last:ep01-S12 | 1 | 1 | passed×1 | 641.0 | 45.0 | passed 11-06 15:52:55 | gpu33:1 |
| first:ep01-S13 | 2 | 2 | redo_fail×1, redo_auto_approved×1 | 956.0 | 172.0 | redo_auto_approved 11-06 15:46:16 | gpu36:1 |
| last:ep01-S13 | 1 | 1 | passed×1 | 383.0 | 48.0 | passed 11-06 18:42:28 | gpu33:0 |
| first:ep01-S14 | 6 | 5 | redo_fail×4, best_effort×1 | 645.0 | 161.0 | best_effort 11-06 16:42:03 | gpu33:0,gpu33:1,gpu33:3,gpu36:1,gpu36:2 |
| last:ep01-S14 | 0 | 0 | — | — | — | passed（起点前） 11-06 00:01:59 |  |
| first:ep01-S15 | 5 | 5 | redo_fail×4, best_effort×1 | 633.0 | 112.0 | best_effort 11-06 16:14:57 | gpu33:1,gpu33:3,gpu36:0 |
| last:ep01-S15 | 2 | 1 | passed×1 | 614.0 | 102.0 | passed 11-06 16:08:18 | gpu33:0,gpu36:0 |
| first:ep01-S16 | 3 | 3 | redo_fail×2, redo_auto_approved×1 | 849.0 | 111.0 | redo_auto_approved 11-06 16:02:06 | gpu33:3,gpu36:1 |
| last:ep01-S16 | 1 | 1 | passed×1 | 738.0 | 162.0 | passed 11-06 16:17:16 | gpu33:3 |

## 4. 视频段

窗口内提交 17 · 完成 17 · 过 17 · 没过 0 · 生成中位 422 s · 打分中位 70 s

| 镜 | 段数 | 道 | 结论 | 定下 | 配方 |
|---|---|---|---|---|---|
| S2 | 4 | gpu33:1,gpu33:1,gpu33:1,gpu33:1 | pass,pass,pass,pass | SHOT_PASS | i2va_pika_flex |
| S3 | 4 | gpu36:0,gpu36:2,gpu36:0,gpu36:0 | pass,pass,pass,pass | SHOT_BEST_EFFORT | i2va_pika_flex |
| S4 | 1 | gpu33:0 | pass | SHOT_PASS | i2va_pika_flex |
| S5 | 1 | gpu36:0 | pass | SHOT_PASS | i2va_pika_flex |
| S6 | 1 | gpu36:2 | pass | SHOT_PASS | i2va_pika_flex |
| S7 | 1 | gpu36:1 | pass | SHOT_PASS | i2va_pika_flex |
| S8 | 1 | gpu36:2 | pass | SHOT_PASS | i2va_pika_flex |
| S10 | 1 | gpu36:0 | pass | SHOT_PASS | i2va_pika_flex |
| S12 | 1 | gpu36:1 | pass | SHOT_PASS | i2va_pika_flex |
| S13 | 1 | gpu36:1 | pass | SHOT_PASS | i2va_pika_flex |
| S16 | 1 | gpu36:1 | pass | SHOT_PASS | i2va_pika_flex |

## 5. 等待

| 等待 | 次数 | 合计 s | 中位 s | 最大 s | 其中有空道 s | 被闸门挡 |
|---|---|---|---|---|---|---|
| 就绪 → 派单 | 107 | 34121 | 39 | 10141 | 17722 | 1 次 |
| 首尾成对 → 视频提交 | 10 | 23258 | 1083 | 11326 | 18974 | |
| 出图 → 打分结论 | 104 | 10225 | 67 | 1976 | | |
| 视频全定 → 合成起 | 1 | 0 | | | | |

最长的就绪→派单：last:ep01-S13 10141 s（11-06 15:46:16→11-06 18:35:17 gpu33:0，空道 9141 s，闸门：sop_gate_block：退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13））；last:ep01-S10 3939 s（11-06 14:53:10→11-06 15:58:49 gpu36:0，空道 1080 s）；last:ep01-S10 2575 s（11-06 14:53:10→11-06 15:36:05 gpu36:2，空道 215 s）；last:ep01-S12 1530 s（11-06 15:15:59→11-06 15:41:29 gpu33:1，空道 0 s）；last:ep01-S5 1416 s（11-06 15:58:51→11-06 16:22:27 gpu33:0，空道 434 s）

最长的成对→提交：S8 11326 s（11-06 15:12:37→11-06 18:21:22，空道 8435 s，尾帧未定，按首帧定下算）；S4 4504 s（11-06 17:59:23→11-06 19:14:26，空道 4504 s，尾帧兜底（只用首帧））；S2 2179 s（11-06 16:19:23→11-06 16:55:42，空道 2179 s）；S3 1646 s（11-06 15:27:16→11-06 15:54:41，空道 634 s）；S6 1083 s（11-06 15:38:15→11-06 15:56:18，空道 730 s）

## 6. 空卡有活

本集口径（道空闲 ∩ 本集有帧 / 镜在等，道·分钟，日志推算）：gpu33:0 21、gpu33:1 123、gpu33:3 147、gpu36:0 152、gpu36:1 174、gpu36:2 184

idle_watch 口径（道空闲且全剧有活，道·分钟，笔记本每分钟采样）：gpu33:0 1145、gpu33:1 1323、gpu33:3 1425、gpu36:0 1049、gpu36:1 1076、gpu36:2 1110

idle_watch 动作：
- 11-06 16:37:40 ACT night_once gpu36 gpu36 可派视频 2 镜而道空 -> rc=0 11-06 16:37:48 RUN series10_v2 data/pipeline/runs/series10_v2/video
- 11-06 16:37:40 ACT report gpu36 gpu36 道 ['gpu36:2'] 空闲 5 分钟（全台空：False）；活：ready 首尾帧 45（ep [1, 2, 3, 4]）/ 本台可派视频 2 镜 / 资产作业 5；原因线索：night_control yield_s=30；sop_gate 出图阻断 {2: ['资
- 11-06 17:03:47 ACT night_once gpu33 gpu33 可派视频 6 镜而道空 -> rc=0 11-06 17:04:05 RUN series10_v2 data/pipeline/runs/series10_v2/video
- 11-06 17:03:47 ACT report gpu33 gpu33 道 ['gpu33:3'] 空闲 5 分钟（全台空：False）；活：ready 首尾帧 43（ep [1, 2, 3, 4]）/ 本台可派视频 6 镜 / 资产作业 4；原因线索：night_control yield_s=30；sop_gate 出图阻断 {2: ['资
- 11-06 17:04:47 ACT night_once gpu36 gpu36 可派视频 2 镜而道空 -> rc=0 11-06 17:05:00 RUN series10_v2 data/pipeline/runs/series10_v2/video
- 11-06 17:14:47 ACT night_once gpu33 gpu33 可派视频 6 镜而道空 -> rc=0 11-06 17:14:54 RUN series10_v2 data/pipeline/runs/series10_v2/video
- 11-06 17:24:47 ACT night_once gpu33 gpu33 可派视频 5 镜而道空 -> rc=0 11-06 17:24:56 RUN series10_v2 data/pipeline/runs/series10_v2/video
- 11-06 17:34:47 ACT night_once gpu33 gpu33 可派视频 5 镜而道空 -> rc=0 11-06 17:34:52 RUN series10_v2 data/pipeline/runs/series10_v2/video
- 11-06 17:37:47 ACT report gpu36 gpu36 道 ['gpu36:2'] 空闲 14 分钟（全台空：False）；活：ready 首尾帧 43（ep [1, 2, 3, 4]）/ 本台可派视频 0 镜 / 资产作业 4；原因线索：night_control yield_s=30；sop_gate 出图阻断 {2: ['
- 11-06 18:03:48 ACT report gpu33 gpu33 道 ['gpu33:1', 'gpu33:3'] 空闲 26 分钟（全台空：False）；活：ready 首尾帧 43（ep [1, 2, 3, 4]）/ 本台可派视频 5 镜 / 资产作业 4；原因线索：night_control yield_s=30；sop_gate 
- 11-06 18:44:48 ACT report gpu36 gpu36 道 ['gpu36:0', 'gpu36:2'] 空闲 5 分钟（全台空：False）；活：ready 首尾帧 42（ep [1, 2, 3, 4]）/ 本台可派视频 0 镜 / 资产作业 4；原因线索：night_control yield_s=30；sop_gate 出
- 11-06 19:19:14 ACT report gpu33 gpu33 道 ['gpu33:1', 'gpu33:3'] 空闲 5 分钟（全台空：False）；活：ready 首尾帧 42（ep [1, 2, 3, 4]）/ 本台可派视频 6 镜 / 资产作业 5；原因线索：night_control yield_s=30；sop_gate 出

## 7. 重启 / 事故

计数：REOPEN 3、best_effort_reset 4、gaze_round 3、hard_cap_exhausted 2、infra_error 9、lane_roles_phase 2、last_void_reset 29、night_restart 9、pause:deploy 2、pause:restart 6、producer_restart 6、register_takes 4、retry 1、review_scale 10、score_timeout 1、sop_gate_block 17

- 11-06 14:55:01 gpu33 infra_error first:ep01-S3 gpu36:1 ComfyUnavailable: /upload/image: [Errno 111] Connection refused
- 11-06 14:55:01 gpu33 infra_error first:ep01-S6 gpu36:2 ComfyUnavailable: /upload/image: [Errno 111] Connection refused
- 11-06 14:55:01 gpu33 infra_error first:ep01-S2 gpu36:0 ComfyUnavailable: /upload/image: [Errno 111] Connection refused
- 11-06 14:55:31 gpu33 pause:restart   暂停派单：重启前排空 暂停 116 s
- 11-06 14:57:19 gpu33 producer_restart   producer 重启 pid 3637823 code 3b274b97e572308b
- 11-06 14:57:51 gpu36 pause:restart   暂停派单：重启前排空 暂停 42 s
- 11-06 14:58:06 gpu36 night_restart   data/pipeline/runs/series10_v2/video
- 11-06 14:58:07 gpu36 producer_restart   producer 重启 pid 2706205 code 3b274b97e572308b
- 11-06 15:17:45 gpu33 last_void_reset last:ep01-S4  首帧换过（当前首帧 v14 比尾帧 v4 新），尾帧作废，跟着重出，不计次
- 11-06 15:18:41 gpu33 last_void_reset last:ep01-S5  首帧换过（当前首帧 v2 比尾帧 v8 新），尾帧作废，跟着重出，不计次
- 11-06 15:19:55 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 15:29:49 gpu36 pause:restart   暂停派单：重启前排空 暂停 106 s
- 11-06 15:31:25 gpu36 producer_restart   producer 重启 pid 2835466 code 3b274b97e572308b
- 11-06 15:31:25 gpu36 night_restart   data/pipeline/runs/series10_v2/video
- 11-06 15:36:04 gpu33 last_void_reset last:ep01-S5  首帧换过（当前首帧 v2 比尾帧 v8 新），尾帧作废，跟着重出，不计次
- 11-06 15:40:04 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 15:41:43 gpu33 last_void_reset last:ep01-S15  首帧换过（当前首帧 v12 比尾帧 v2 新），尾帧作废，跟着重出，不计次
- 11-06 15:46:39 gpu33 sop_gate_block last:ep01-S13  SOP 闸门：series10_v2 第1集镜13不能进入“尾帧”——出图检测：0/1 镜首帧过契约 + Q9；缺 镜13
- 11-06 15:47:22 gpu33 last_void_reset last:ep01-S5  首帧换过（当前首帧 v2 比尾帧 v8 新），尾帧作废，跟着重出，不计次
- 11-06 15:52:41 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 15:56:12 gpu33 infra_error last:ep01-S10 gpu36:2 ComfyUnavailable: /history/ed990972-ac51-4285-90f0-049c39844fed: TimeoutError: timed out
- 11-06 15:56:12 gpu33 infra_error last:ep01-S15 gpu36:0 ComfyUnavailable: /history/109d1486-b4c7-405f-9d5f-e843a804f510: TimeoutError: timed out
- 11-06 15:56:12 gpu33 infra_error first:ep01-S14 gpu36:2 ComfyUnavailable: /history/52881eda-184e-4585-832a-d253bcf05829: TimeoutError: timed out
- 11-06 15:56:13 gpu33 infra_error first:ep01-S2 gpu36:1 ComfyUnavailable: /history/7bad6af3-f871-439d-8c01-3c0c6d22748c: TimeoutError: timed out
- 11-06 15:56:36 gpu33 infra_error first:ep01-S5 gpu36:1 ComfyUnavailable: /history/a89b953a-34d9-437a-bc95-259c668d160d: TimeoutError: timed out
- 11-06 15:58:49 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- 11-06 15:59:02 gpu33 last_void_reset last:ep01-S5  首帧换过（当前首帧 v2 比尾帧 v8 新），尾帧作废，跟着重出，不计次
- 11-06 16:02:15 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 16:03:57 gpu33 score_timeout first:ep01-S11  TimeoutError()
- 11-06 16:08:54 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- 11-06 16:14:40 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 16:17:45 gpu36 register_takes   raw_decode obj, end = self.scan_once(s, idx) ^^^^^^^^^^^^^^^^^^^^^^ json.decoder.JSONDecodeError: Expecting property name enclosed in double
- 11-06 16:21:19 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- 11-06 16:22:25 gpu33 infra_error last:ep01-S5 gpu36:1 ComfyUnavailable: /history/387de9c3-fd3c-4a17-aff1-2b3cc122493e: TimeoutError: timed out
- 11-06 16:22:54 gpu33 gaze_round last:ep01-S4  3 版全部看镜头 / 排排站或与首帧太像（L-200 / L-203 硬闸，不采用）→ L-204 自动再给第 1/2 轮换种子（3 次），不计之前的次数
- 11-06 16:27:16 gpu33 gaze_round last:ep01-S7  3 版全部看镜头 / 排排站或与首帧太像（L-200 / L-203 硬闸，不采用）→ L-204 自动再给第 1/2 轮换种子（3 次），不计之前的次数
- 11-06 16:28:42 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 16:32:19 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- 11-06 16:37:48 gpu36 night_restart   data/pipeline/runs/series10_v2/video
- 11-06 16:42:04 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 16:42:35 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- 11-06 16:52:36 gpu36 register_takes   thon3.12/json/decoder.py", line 356, in raw_decode raise JSONDecodeError("Expecting value", s, err.value) from None json.decoder.JSONDecodeE
- 11-06 16:52:39 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 16:52:40 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- 11-06 16:55:33 gpu33 best_effort_reset last:ep01-S4  尽力版的契约 / 预设 / 看图规则变了 → 自动重置，重新给 3 次，不计次（K-OPS-E11）
- 11-06 17:00:08 gpu33 retry last:ep01-S8  S8 尾帧登记表 best_effort 与账本(tries 0 final None)不一致，卡住不派；放回重派
- 11-06 17:02:50 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- 11-06 17:03:06 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 17:05:00 gpu36 night_restart   data/pipeline/runs/series10_v2/video
- 11-06 17:05:02 gpu36 REOPEN   入选版本有变，按新版本号重合成
- 11-06 17:05:25 gpu36 REOPEN   入选版本有变，按新版本号重合成
- 11-06 17:09:48 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 17:12:57 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- 11-06 17:21:39 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 17:23:05 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- 11-06 17:27:28 gpu33 gaze_round last:ep01-S4  9 版全部看镜头 / 排排站或与首帧太像（L-200 / L-203 硬闸，不采用）→ L-204 自动再给第 2/2 轮换种子（3 次），不计之前的次数
- 11-06 17:32:45 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 17:33:13 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- 11-06 17:43:15 gpu33 last_void_reset last:ep01-S9  首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次
- 11-06 17:43:16 gpu33 sop_gate_block last:ep01-S13  退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- …共 108 条，全量见 JSON

大脑动作（decisions.jsonl）：
- 11-06 17:36:11 no_action by BRAIN-FW-selftest dry dry-run（没动手）

## 8. 归因证据（每个超预算阶段）

### 导入 / 探针：超 2.9 min → 逻辑 3、代码 0、GPU 调度 0、检测 0

### 首帧：超 96.4 min → 逻辑 0、代码 1、GPU 调度 17、检测 78
- [代码] 116 s · gpu33 暂停派单 116 s（restart：暂停派单：重启前排空）11-06 14:55:31
- [代码] 106 s · gpu36 暂停派单 106 s（restart：暂停派单：重启前排空）11-06 15:29:49
- [代码] 42 s · gpu36 暂停派单 42 s（restart：暂停派单：重启前排空）11-06 14:57:51
- [代码] 30 s · first:ep01-S3 gpu36:1 infra_error ComfyUnavailable: /upload/image: [Errno 111] Connection refused 退避 30 s 11-06 14:55:01
- [代码] 30 s · first:ep01-S6 gpu36:2 infra_error ComfyUnavailable: /upload/image: [Errno 111] Connection refused 退避 30 s 11-06 14:55:01
- [GPU 调度] 865 s · first:ep01-S14 就绪 11-06 15:43:56 → 派单 11-06 15:58:33（gpu36:1）等 877 s，其中有空道 865 s
- [GPU 调度] 801 s · first:ep01-S2 就绪 11-06 15:36:20 → 派单 11-06 15:57:29（gpu33:1）等 1269 s，其中有空道 801 s
- [GPU 调度] 759 s · first:ep01-S5 就绪 11-06 15:45:54 → 派单 11-06 15:58:33（gpu36:0）等 759 s，其中有空道 759 s
- [GPU 调度] 215 s · first:ep01-S5 就绪 11-06 14:54:52 → 派单 11-06 14:58:27（gpu33:0）等 215 s，其中有空道 215 s
- [GPU 调度] 215 s · first:ep01-S6 就绪 11-06 14:54:52 → 派单 11-06 14:58:27（gpu33:1）等 215 s，其中有空道 215 s
- [检测] 1936 s · first:ep01-S11 v12 打分 1976 s > 40.0 s
- [检测] 1076 s · first:ep01-S15 第 3 次重出（上一版契约没过：redo_fail）11-06 15:34:01 道 gpu36:0 1076 s
- [检测] 1000 s · first:ep01-S11 第 2 次重出（上一版契约没过：Q10,Q9）11-06 15:17:17 道 gpu36:0 1000 s
- [检测] 1000 s · first:ep01-S14 第 3 次重出（上一版契约没过：redo_fail）11-06 15:58:33 道 gpu36:1 1000 s
- [检测] 985 s · first:ep01-S7 第 2 次重出（上一版契约没过：redo_fail）11-06 15:25:16 道 gpu36:0 985 s

### 尾帧：超 1686.5 min → 逻辑 854、代码 0、GPU 调度 77、检测 756
- [逻辑] 10141 s · last:ep01-S13 就绪 11-06 15:46:16 → 派单 11-06 18:35:17 等 10141 s，期间被闸门挡：sop_gate_block：退避中（出图检测：0/1 镜首帧过契约 + Q9；缺 镜13）
- [逻辑] 1066 s · last:ep01-S9 v13 出完被 last_void_reset 作废（首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次）11-06 15:40:04
- [逻辑] 807 s · last:ep01-S4 v11 出完被 gaze_round 作废（3 版全部看镜头 / 排排站或与首帧太像（L-200 / L-203 硬闸，不采用）→ L-204 自动再给第 1/2 轮换种子（3 次），）11-06 16:22:54
- [逻辑] 791 s · last:ep01-S9 v17 出完被 last_void_reset 作废（首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次）11-06 16:28:42
- [逻辑] 654 s · last:ep01-S9 v18 出完被 last_void_reset 作废（首帧换过（当前首帧 v22 比尾帧 v3 新），尾帧作废，跟着重出，不计次）11-06 16:42:04
- [GPU 调度] 1080 s · last:ep01-S10 就绪 11-06 14:53:10 → 派单 11-06 15:58:49（gpu36:0）等 3939 s，其中有空道 1080 s
- [GPU 调度] 434 s · last:ep01-S5 就绪 11-06 15:58:51 → 派单 11-06 16:22:27（gpu33:0）等 1416 s，其中有空道 434 s
- [GPU 调度] 215 s · last:ep01-S10 就绪 11-06 14:53:10 → 派单 11-06 15:36:05（gpu36:2）等 2575 s，其中有空道 215 s
- [GPU 调度] 137 s · last:ep01-S7 就绪 11-06 16:25:17 → 派单 11-06 16:27:34（gpu33:0）等 137 s，其中有空道 137 s
- [GPU 调度] 121 s · last:ep01-S10 就绪 11-06 16:19:18 → 派单 11-06 16:21:19（gpu33:3）等 121 s，其中有空道 121 s
- [检测] 807 s · last:ep01-S4 第 3 次重出（上一版契约没过：FL,Q1）11-06 16:07:46 道 gpu33:3 807 s
- [检测] 791 s · last:ep01-S9 第 1 次重出（上一版契约没过：FL,G1）11-06 16:14:40 道 gpu33:3 791 s
- [检测] 771 s · last:ep01-S7 第 2 次重出（上一版契约没过：FL）11-06 15:58:34 道 gpu36:2 771 s
- [检测] 740 s · last:ep01-S10 第 2 次重出（上一版契约没过：content_fail）11-06 16:21:19 道 gpu33:3 740 s
- [检测] 695 s · last:ep01-S4 第 2 次重出（上一版契约没过：FL,Q1）11-06 15:55:15 道 gpu33:3 695 s

### 视频：超 193.6 min → 逻辑 136、代码 6、GPU 调度 52、检测 0
- [逻辑] 11326 s · S8 首帧定下 11-06 15:12:37 → 视频提交 11-06 18:21:22 等 11326 s（尾帧未定，按首帧定下算：等尾帧决策 / HOLD）
- [逻辑] 4504 s · S4 首帧定下 11-06 17:59:23 → 视频提交 11-06 19:14:26 等 4504 s（尾帧兜底（只用首帧）：等尾帧决策 / HOLD）
- [代码] 118 s · gpu36 暂停派单 118 s（deploy：暂停派单：部署 sv-20261106-08：重启前暂停派单，重启后恢复）11-06 18:56:25
- [代码] 60 s · first:ep01-S2 gpu36:1 infra_error ComfyUnavailable: /history/7bad6af3-f871-439d-8c01-3c0c6d22748c: Timeo 退避 60 s 11-06 15:56:13
- [代码] 30 s · last:ep01-S10 gpu36:2 infra_error ComfyUnavailable: /history/ed990972-ac51-4285-90f0-049c39844fed: Timeo 退避 30 s 11-06 15:56:12
- [代码] 30 s · last:ep01-S15 gpu36:0 infra_error ComfyUnavailable: /history/109d1486-b4c7-405f-9d5f-e843a804f510: Timeo 退避 30 s 11-06 15:56:12
- [代码] 30 s · first:ep01-S14 gpu36:2 infra_error ComfyUnavailable: /history/52881eda-184e-4585-832a-d253bcf05829: Timeo 退避 30 s 11-06 15:56:12
- [GPU 调度] 2179 s · S2 首尾成对 11-06 16:19:23 → 视频提交 11-06 16:55:42 等 2179 s，其中有空道 2179 s
- [GPU 调度] 805 s · S16 首尾成对 11-06 16:17:16 → 视频提交 11-06 16:30:40 等 805 s，其中有空道 805 s
- [GPU 调度] 803 s · S5 首尾成对 11-06 16:51:15 → 视频提交 11-06 17:04:38 等 803 s，其中有空道 803 s
- [GPU 调度] 730 s · S6 首尾成对 11-06 15:38:15 → 视频提交 11-06 15:56:18 等 1083 s，其中有空道 730 s
- [GPU 调度] 634 s · S3 首尾成对 11-06 15:27:16 → 视频提交 11-06 15:54:41 等 1646 s，其中有空道 634 s
- [检测] 10 s · ep01-S2 alt 视频打分 70 s > 60.0 s

### 合成：超 9.5 min → 逻辑 8、代码 1、GPU 调度 0、检测 0
- [逻辑] 653 s · 合成周期 11-06 16:52:37→11-06 17:03:30 之后被 REOPEN（入选版本有变）重做
- [逻辑] 549 s · 合成周期 11-06 17:19:38→11-06 17:28:47 之后被 REOPEN（入选版本有变）重做
- [逻辑] 480 s · 合成周期 11-06 15:17:20→11-06 15:25:20 之后被 REOPEN（入选版本有变）重做
- [代码] 60 s · night register_takes 报错 11-06 16:17:45：raw_decode obj, end = self.scan_once(s, idx) ^^^^^^^^^^^^^^^^^^^^^^ json.decoder.JSONDecod
- [代码] 60 s · night register_takes 报错 11-06 16:52:36：thon3.12/json/decoder.py", line 356, in raw_decode raise JSONDecodeError("Expecting value"
- [代码] 60 s · night register_takes 报错 11-06 18:42:45：.py", line 354, in raw_decode obj, end = self.scan_once(s, idx) ^^^^^^^^^^^^^^^^^^^^^^ jso
- [代码] 60 s · night register_takes 报错 11-06 19:25:35：decoder.py", line 354, in raw_decode obj, end = self.scan_once(s, idx) ^^^^^^^^^^^^^^^^^^^

### 拉回交付：超 501.0 min → 逻辑 501、代码 0、GPU 调度 0、检测 0
- [逻辑] 0 s · 没有直接证据，按流程等待（逻辑）记

## 9. 合成周期

| 起（EP_RESOLVED） | 止 | 收尾事件 | 步骤 | 报错 | REOPEN |
|---|---|---|---|---|---|
| 11-06 15:17:20 | 11-06 15:25:20 | HARD_RULES | 7 | 2 |  |
| 11-06 16:52:37 | 11-06 17:03:30 | RETRO | 9 | 0 | 11-06 17:05:25 |
| 11-06 17:19:38 | 11-06 17:28:47 | RETRO | 10 | 1 | 11-06 18:21:39 |
| 11-06 19:23:15 | 11-06 19:40:43 | FINALIZE_DONE | 11 | 1 |  |

## 10. 背景：起点之前同日的尝试（不计入 KPI）

派单 101 · 出图 62；导入：11-06 08:00:08 L-201：ep01 S1/S2 改分镜（现实段冷灰 + 光闪匹配切 + S2 低机位单人），项目方 11-06 确认方案；11-06 09:03:11 L-203 首尾帧设想回写 + 五个背景视向（sk_white_cyc_rev/_door/_mirror/_top）；11-06 10:07:12 S4/S5/S12/S14/S15 过肩前景人物改标局部（身份闸不再要求露脸；H3 只写虚化肩背）；11-06 10:09:54 S12/14/15 过肩前景改后脑与左肩（局部不露脸）；11-06 10:14:02 S12/14/15 过肩前景只写肩背（去脸/发/视线），局部不露脸；11-06 14:49:28 L-204 psm11：出图前全量离线检查 32/32 全绿（首尾帧设想 + 5 背景视向 + 过肩前景局部不露脸）

## 口径

- 起点 = 最近一次“全集重出 / 导入”后的第一次派单（--anchor）；截至 = --until（默认现在）；进行中的阶段按截至时刻算实际用时。
- 首帧 / 尾帧“定下”= passed / master_approve / redo_auto_approved / review_adopt / best_effort / hard_cap_exhausted / last_unavailable（兜底）；之后再派单 / 作废即回到未定。
- 视频“定下”= vidgen SHOT_PASS / SHOT_BEST_EFFORT 或 state 里 chosen 的那段完成；合成周期 = night EP_RESOLVED → RETRO/report/director。
- GPU 忙时 = 派单→出图 / 提交→完成 的墙钟（按道），利用率 = 忙时 ÷ 本集用时。
- 归因：每个超预算阶段的分钟按四类证据秒数比例分配，证据是并行道上的叠加；没有证据的超预算记“逻辑”（流程等待）。
- 来源缺失：无
