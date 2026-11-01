# UIAUDIT 独立复核：IMGPERF r1

复核方：UIAUDIT。日期 2026-11-01，约 03:15。

**结论：不通过。** 第 1 项画布还是只显示秒表；第 2、3 项样本不够，记"未测"。

| # | 检查 | 结果 | 证据 |
|---|---|---|---|
| 1 | 画布任务行显示 job.progress 的阶段（如"GPU 出图""ComfyUI 排队"），而不是光一个秒表 | **✗ 前端没接上**。后端已经写好：`services/api/ns_api/jobs.py` 第 119–127 行有 `STAGE_LABEL`（排队 / 检查训练锁 / 准备 / 上传参考图 / ComfyUI 排队 / GPU 出图 / 下载结果 / 后处理 / 写入版本），job 记录里有 `progress.label`（实测 ep01-S1 那条 job 的 progress = `{stage:"done", label:"完成"}`）。但画布的格子进度 `apps/web/src/components/frames.tsx:55` 仍是 `渲染中 ${elapsed(...)}`，`ShotCard.tsx:100` 是"渲染中…"；全前端 grep 不到任何读 `progress.label` 的代码。复核时 ns_api 队列里没有正在跑的任务，没能在界面上看到实况，所以这一条是按代码判的 | grep 结果见本文件；`/api/jobs` |
| 2 | 新的出图任务分散到多张卡，不再都落在 gpu33:0 | **未测（样本不足）**。`/api/jobs` 里最近 25 条 frame 任务：卡 0 有 7 条，卡 1 有 1 条，gpu36:1 有 1 条。但 IMGPERF 上线以后只来了 1 条新 frame 任务（02:16，ep01-S1），判断不了分不分散。另外 lane 字段有的写"0"，有的写"gpu36:1"，同一个字段两种写法，建议统一成"服务器:卡" | `/api/jobs` |
| 3 | `tools/perf/frame_timing_check.py --last 10` | 带 timing 的 frame 任务 1 个，**未测 5 个**，违规 0 个。只有 1 个样本，不能算通过 | 命令输出 |

打回 IMGPERF：
1. 画布格子（`frames.tsx`、`ShotCard.tsx`）显示成 `progress.label · step/total`，不要只显示秒表。
2. 跑出至少 10 条新的 frame 任务后，再请我复核第 2、3 项。
