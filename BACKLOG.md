# BACKLOG — 停车场（轮次中冒出的"顺便改一下"先记这里，不许当场动手）

- 好莱坞质感分进出图检测、逐集棘轮（原 W25 spec：C:\Users\fredw\AppData\Local\Temp\ns_specs\spec_W25_hollywood_gate.md）——Phase Q
- 每集复盘全自动 + 指标对比 + 记忆/harness 候选（原 W24 spec：spec_W24_retro_auto.md）——Phase Q；Phase R 期间用 ITERATION_LOG 代替
- ep01 S2/S4/S6 尽力版 → 整集返修包（L-150 项目方点选）——Phase Q
- 出图道/打分上传离开 -t 底座（ISS-1103-150939）——若换代后笔记本不再出图则关闭
- UI/UX 可读性（项目方 11-02 夜："uiux 变得很难用"）剩余项——Phase Q
- arch_scan 49 处 untracked_* 退化 = 新文件未入版，cut C 入版即消
- test_asset_pipeline::test_requeued_suspect_job_not_restarted_while_child_alive 并行偶发（W14 报）
- resident_sync.py:1030 注释过期（restart_queue 已支持 mode，W17b 报）
- 写手 fable 30 分钟超时一次（P4_ep03_a3 第 1 次）：整集返修包生成耗时统计后再定超时
- 通知中心→带 chat 的项目方助手（项目方 11-03 16:0x 需求）：plan 在 docs/master/PLAN_OWNER_CHAT.md，分期 1（通知直说）可与 Phase R 并行，2–4 等冒烟门 8/8
- W33 迁移 --apply：34 个 V2 版本文件从 V1 目录搬到 renders/series10_v2/…（0 冲突、0 与 V1 共享）——等 cut C 入版后做，当前 resolve_rel 新旧都能读
- frames_summary.py / perf/frame_timing_check.py 读全局 frames_v2、pipeline.audit_active 写全局 current_changes.jsonl、series10_v2 looks.json 里 V1 角色（W33 只列未改）
- 服务器 producer 需要的三类笔记本产物都没有自动同步：run 产物（P4/autoflow/asset ready）、sop_gate 阶段证据（data/pipeline/sop_gate/<run>/）、派生参考图（images/refboards|refcrops + _derived_index.json，K-OPS-F23 按 sha 推送只在笔记本出图路径触发）。11-03 晚全部手工 tar 推 gpu33；规则级修法进 ISS-1103-181720（resident_sync 每拍增量同步在产剧这三类）
- gpu36 vqa/server.pid 记录的是 bash 包装进程 pid（手工拉起时 echo $! 取错），下次 deploy_offline/resident_restart 接管时改为 python 进程 pid；并把 vqa server+watcher 纳入 resident_restart.sh all（ISS-220512）
