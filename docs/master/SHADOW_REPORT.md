# SHADOW_REPORT（L-209 S1 影子调度，自动生成，勿手改）

最近一拍 2026-11-07 04:00:06+09:00 · run series10_v2 · run 级 active ep02 阶段 **frames**
累计 256 拍 / 254.3 min（自 2026-11-06 23:45:50+09:00）· 探针失败 无 · 成人镜不进图 21 · 两台登记表不一致对象 41

## 1. 累计（逐拍：现网 vs 影子）

| 指标 | 现网 | 影子 |
|---|---|---|
| 空道分钟（道·分钟） | 1090.8 | 757.4 |
| 其中“空着但影子有活派” | 333.5 | 0 |
| 换模型次数 | 140 | 3 |
| 视频饿死分钟（有就绪视频且能做视频的道空着） | 106.0 | 1.0 |
| 两台 L-207 阶段不一致的拍数（M4） | 67 | 0（一个 run 级阶段） |

差异类别（窗口：上一拍影子决策 vs 两拍间现网真实派单）：live_left_idle:partition 188, live_work_on_closed_ep 83, lane_freed_midwindow 66, live_left_idle:live_phase_split 61, live_left_idle:video_not_queued 40, live_left_idle:live_waiting_rescore 16, rank_order 11, live_breaks_role_or_gate 11, live_left_idle:unexplained 5, shadow_frames_first 2, live_left_idle:live_paused 1, same_task_other_lane 1, live_ahead_of_deps 1

瞬时类别（现网空着、影子要派 → 现网为什么空着）：partition 190, live_phase_split 62, video_not_queued 45, live_waiting_rescore 28, unexplained 8, live_role_violation 8, not_in_control_only 1, live_paused 1

## 2. 本拍：每道

| 道 | 现网 | 影子角色（run 级阶段） | 影子决策 | 差异类别 / 机制 | 证据 |
|---|---|---|---|---|---|
| gpu33:0 | idle  | image | last:ep02-S11 | partition / M1 partition.json / control.only+hold_lanes | ep02-S11 归 gpu36（control.only），gpu33 的 producer 不派它；gpu36 的 hold_lanes 含 gpu33:0 |
| gpu33:1 | idle  | image | — |   |  |
| gpu33:3 | idle  | — +审图×3 | — |   |  |
| gpu36:0 | idle  | image | — |   |  |
| gpu36:1 | idle  | image | — |   |  |
| gpu36:2 | idle  | video | video:ep02-S1 | live_phase_split / M4 lane_roles_state._active（每台各算） | gpu36 认为 ep02 在 videos，影子 run 级 = frames |

就绪任务 {'last': 1, 'video': 3} · 闸门 hold 3 · 资产 hold 0 · 登记表在跑但不占道 0

## 3. L-207 阶段：两台各算 vs 影子一个 run 级（M4）

| 来源 | _active | active 阶段 | 本集（ep2）阶段 |
|---|---|---|---|
| gpu33 lane_roles_state | ep2 | frames | frames |
| gpu36 lane_roles_state | ep2 | videos | videos |
| 影子 | ep2 | frames | frames |

🔴 两台不一致；与影子不同

## 4. 窗口回看（最近 60 min，log 重建；资产作业不在 log 里 → 空闲偏高）

| 道 | 忙 min | 空 min | 作业数 | 换模型 | 序列（i=出图 v=视频） |
|---|---|---|---|---|---|
| gpu33:0 | 0.0 | 60.0 | 0 | 0 |  |
| gpu33:1 | 0.0 | 60.0 | 0 | 0 |  |
| gpu33:3 | 0.0 | 60.0 | 0 | 0 |  |
| gpu36:0 | 59.3 | 0.7 | 33 | 0 | vvvvvvvvvvvvvvvvvvvvvvvvvvvvvv |
| gpu36:1 | 0.0 | 60.0 | 0 | 0 |  |
| gpu36:2 | 0.0 | 60.0 | 0 | 0 |  |
| 合计 | | 300.7 | | 0 | 空闲率 84% |

## 5. 本集用时预测（模拟器续跑影子策略，KPI ≤ 50 min）

- ep02：KPI 起点 11-06 14:50，已用 **789.9 min**；影子续跑还需 **56.1 min** → 预测总 846.0 min（现网线性外推还需 691.2 min；视频已定 8/15；未收敛种子 0）
- 同参数冷启动一集（影子策略、15 镜）：143.0 min（KPI 50）
- 参数（窗口实测，样本不足用 sim.MEASURED）：{"frame_gpu_s": {"gpu33": 310, "gpu36": 400}, "video_gpu_s": {"gpu33": 404, "gpu36": 415}, "frame_pass_p": {"first": 0.23, "last": 0.43}, "video_pass_p": 0.05, "samples": {"frame": {"gpu33": 0, "gpu36": 0}, "video": {"gpu33": 0, "gpu36": 2}, "video_scores": 38, "frame_rendered": {"first": 0, "last": 0}}}

## 6. 两份 partition.json（ARCH_MAP_20261106 §3）

| 执行者 | 读哪份 | 位置 |
|---|---|---|
| producer probe_lanes / partition_held | config/netfix/partition.json | producer.py:3546 |
| tools/netfix/dispatch.py → control.json only / hold_lanes | data/state/netfix/partition.json | dispatch.py:34 |
| night.py（_D.read_partition）→ control_<host>.json | data/state/netfix/partition.json | night.py dispatch_hosts |
| asset_worker（_temp_holds 写入，tools/debug/lanes.py） | data/state/netfix/partition.json | asset_worker.py:380 |

| 台 | md5 config / state | 字段不同 | 生效临时 hold config / state | 只在一份里的 hold |
|---|---|---|---|---|
| gpu33 | 2876c1ae / 4af0c343 | — | [] / [] | {'config': [], 'state': []} |
| gpu36 | 2876c1ae / 4af0c343 | — | [] / [] | {'config': [], 'state': []} |

## 7. 两台登记表不一致（前 12 / 共 41；影子用的那台标在 used）

- first:ep01-S1: {'gpu33': 'best_effort', 'gpu36': 'ready'} → used gpu33
- video:ep01-S11: {'gpu33': 'pending', 'gpu36': 'passed'} → used gpu36
- video:ep01-S12: {'gpu33': 'pending', 'gpu36': 'passed'} → used gpu36
- video:ep01-S14: {'gpu33': 'pending', 'gpu36': 'passed'} → used gpu36
- last:ep01-S4: {'gpu33': 'best_effort', 'gpu36': 'ready'} → used gpu33
- video:ep01-S7: {'gpu33': 'pending', 'gpu36': 'passed'} → used gpu36
- video:ep01-S9: {'gpu33': 'pending', 'gpu36': 'passed'} → used gpu36
- first:ep02-S1: {'gpu33': 'ready', 'gpu36': 'passed'} → used gpu36
- last:ep02-S1: {'gpu33': 'pending', 'gpu36': 'best_effort'} → used gpu36
- first:ep02-S10: {'gpu33': 'ready', 'gpu36': 'passed'} → used gpu36
- last:ep02-S10: {'gpu33': 'pending', 'gpu36': 'passed'} → used gpu36
- video:ep02-S10: {'gpu33': 'pending', 'gpu36': 'best_effort'} → used gpu36

## 8. 上一窗口逐道差异

- gpu33:0: 影子 last:ep02-S11 / 现网 None → live_left_idle:partition M1 ep02-S11 归 gpu36（control.only），gpu33 的 producer 不派它；gpu36 的 hold_lanes 含 gpu33:0
- gpu36:0: 影子 None / 现网 video:ep01-S1 → live_work_on_closed_ep STATE ep01 已合成 / 没有可派镜，现网还在出
- gpu36:2: 影子 video:ep02-S1 / 现网 None → live_left_idle:live_phase_split M4 gpu36 认为 ep02 在 videos，影子 run 级 = frames

## 9. S3 唯一调度器（L-209 S3 phase 1，sched=record；视频跨台 只记录，首尾帧只记录）

累计 2 拍 / 1.0 min（自 2026-11-07T10:08:12）：现网空道 6.3 道·分钟（100.0%）→ 调度器下 0.0（0.0%），预计多用 **6.3 道·分钟**；按道 {'gpu33:0': 1.05, 'gpu33:1': 1.05, 'gpu33:3': 1.05, 'gpu36:0': 1.05, 'gpu36:1': 1.05, 'gpu36:2': 1.05}

最近决定 2026-11-07T10:08:12（到期 2026-11-07T10:18:12）· active {'ep': 2, 'phase': 'videos', 'stages': {'1': 'videos', '2': 'videos', '3': 'videos', '4': 'done'}, 'since': '2026-11-07T08:54:43'}

| 道 | 现网 | 调度器排队（前 3） |
|---|---|---|
| gpu33:0 | idle | video:ep03-S1, video:ep03-S2, video:ep03-S8 |
| gpu33:1 | idle | video:ep03-S10, video:ep03-S3, video:ep03-S9 |
| gpu33:3 | idle | video:ep03-S11, video:ep03-S4, last:ep01-S1 |
| gpu36:0 | idle | video:ep02-S1, video:ep03-S5 |
| gpu36:1 | idle | video:ep02-S4, video:ep03-S6 |
| gpu36:2 | idle | video:ep02-S7, video:ep03-S7 |

跨台：video:ep03-S5→gpu36:0（归 gpu33）；video:ep03-S6→gpu36:1（归 gpu33）；video:ep03-S7→gpu36:2（归 gpu33）

机制编号见 docs/master/ARCH_MAP_20261106.md §2.3：M1=partition.json / control.only+hold_lanes；M3=lane_roles.json 工位表；M4=lane_roles_state._active（每台各算）；M5=video yield / shared_lanes；M6=video_lanes / vram_gate；M7=video_shard；M8=lane_relay；M9=per-process leases；M11=pauses / sop_gate / preflight；M12=asset_worker _temp_holds；SCHED=新调度器策略（HEFT 秩 + 集序 + 亲和）；STATE=状态分裂（两台登记表 / 孤儿记录）；?=未解释
