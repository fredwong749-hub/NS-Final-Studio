# AUDIT · WORKFLOW 复核 r02（服务器常驻 night，2026-11-01 22:11–22:12，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：data/autopilot/resident/{sha_gpu33.json, sha_gpu36.json, jobs_rebuild_gpu33.json, jobs_rebuild_gpu36.json}、ops/logs/{video_up.out.log, resident_sync.log, resident_loop.out.log}。机读版：data/qa/audit/WORKFLOW_r02.json

## 结论：通过；关闭 WORKFLOW_r01 / VIDEO_RCA_r01 的 P1（服务器端旧作业清单问题）

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | 两台服务器常驻 night 已起（20:15 / 20:27） | video_up.out.log 20:15:16：gpu33 “night pid 1069782 alive”；resident_sync.log 22:09:33 gpu33 night 重启为 pid 1210609 alive（打了补丁之后重启）。健康检查 22:08 gpu33、22:10 gpu36 的 night_state_age_min 都是 1.6–1.9，night 每轮都在写状态，**两台的 night 都活着** | 通过 |
| 2 | sha 核对 | sha_gpu33.json（20:08:28）：核 630 个，不一致 0，重推修好 7 个（6 张 ep02_outfit 身份参考图 + full_redo/plan.json）；sha_gpu36.json（20:19:56）：核 633 个，不一致 0，修好 8 个。video_up.out.log 有同样的数字 | 通过（采信脚本输出，AUDIT 没有登录服务器另算 sha） |
| 3 | 重编后 jobs.json：非 Pika = 0，RL-E3 = 0 | jobs_rebuild_gpu36.json：shots 93，**non_pika_ready 0，rl_e3_ready 0**，rl_e3_examples []。但 dist = {}，holds 列表里几乎都是 waiting_frame / blocked_no_frame：**现在一个可派的变体都没有**（health 里 dispatchable 也是 0），所以 0 / 0 目前在一张空清单上成立 | 通过（成立，但是在空清单上） |
| 4 | 旧编译稿残留 | jobs_rebuild_gpu36.json 里 rl_e3_prompt_files = **35**：服务器 prompts 目录里还有 35 个旧稿带朝向镜头的句子，只是不在 ready 变体里。等首帧补出来、重编生成新变体时，这些文件会不会被重新用到，取决于 build_jobs 是不是每次都重写 prompts | 提醒（交 WORKFLOW 确认重编会覆盖或清掉旧稿） |
| 5 | GPU 空转 | health：gpu33 idle_min 100.6，三条道 util 0；gpu36 只有 lane 0 在 35%。原因是 producer 从 19:41 起被总调度暂停（出图根因在修，见 IMGFIX_r01），没有新首帧，视频就无片可派。producer_hb_age_min ≈ 400 是笔记本 producer 暂停后的心跳年龄 | 符合当前决定（不是缺陷） |

## 提醒
- 恢复出图以后，第一批 Pika 变体生成时要再核一次 non_pika_ready / rl_e3_ready（那时清单才不是空的）。建议 resident_sync 的 rebuild_jobs 每次都写这两个数，并在不为 0 时拒绝起 night。
- 本地 data/pipeline/runs/series10_v1/video/jobs.json 还是 16:56 的旧版（305 Pika / 108 Ref2VA / 7 establishing）。笔记本 night 已经停了，不会被派，但审片页或工具如果读本地这一份，会看到过期数据。
