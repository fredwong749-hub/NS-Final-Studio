# UIAUDIT 独立复核：GPUVIEW r2 + IMGPERF r2（以及 UIRSI 本轮、DATAALIGN 冷启动）

复核方：UIAUDIT。日期 2026-11-01 约 03:37–03:55。:8800 在 03:35:15 重启（以本机进程启动时间为准）。

## GPUVIEW r2

| 项 | 结果 | 判定 | 证据 |
|---|---|---|---|
| P2-2 队列徽标和列表用同一个筛选 | 第 2 集：页签"任务队列 第2集 失败 1"，列表"失败 1"，筛选"第 2 集"。第 1 集：页签"第1集 失败 4"，列表"失败 4" | ✓ 通过 | `gvr2_detect.json`、`gvr2_GV2_queue_a.png` |
| P2-1 "暂时连不上 N 秒" vs "离线" | 代码已上线：`services/api/ns_api/gpu_live.py` 第 339 行 `OFFLINE_AFTER_S = 120`，第 367/370 行文案是"ComfyUI 离线（已连不上 N 分钟）"和"暂时连不上（N 秒）· 卡在忙（利用率 x%）"。重启后 7 张卡里 6 张 busy、1 张 faulty（坏卡 · 不用），这段时间没碰到短暂断开，现场看不到这两种文案 | 按代码判通过；现场**未测** | `/api/gpu/live` |
| 渲染中任务的副标题显示阶段 | `/api/render-tasks` 里 8 个渲染中的任务：VIDEO10 视频 ×5、BGM10 配乐 ×1，还有首帧。sub 都是"渲染中"；配乐那条带 step 4/4。这些任务都不走 ns_api，没有 job.progress，所以没有阶段标签，符合预期 | ns_api 任务的阶段标签**未测**（ns_api 没有在跑的任务） | `/api/render-tasks` |
| 接口速度 | `/api/render/lanes` 105 / 161 / 69 ms；`/api/render-tasks` 54–56 ms；`/api/gpu/live` 14–20 ms | ✓ | 本文件 |

## IMGPERF r2

| 项 | 结果 | 判定 |
|---|---|---|
| 1. 画布格子显示"<阶段> · m:ss"，不再只有秒表 | 代码已接上：`apps/web/src/components/frames.tsx` 第 26–36、67、100 行 `jobStageText(job)` 读 `job.progress.label` 和本段用时；`ShotCard.tsx:29` 也接了。但 `ShotCard.tsx:101/152` 的格子角标还是"渲染中…"（这一处没接）。ns_api 现在 0 个在跑的任务，界面上看不到实况 | 代码通过；现场**未测**；ShotCard 角标记 P2 |
| 2. G10 | 见下面 G10 一节：P0 = 0 | ✓ |
| 3. `frame_timing_check.py --last 10` 和分卡 | 02:20 以后 ns_api 没有新的 frame 任务（0 条），够不上 5 条的门槛 | **未测（等样本）** |
| `/api/render/lanes` 提速 | 105 / 161 / 69 ms | ✓ |

## DATAALIGN 冷启动（补测）

- 收到总调度"已重启"的消息后，**立即**同时发 3 个 `/api/episodes`：**1645 / 1469 / 1332 ms**（全部 200）。紧接着再发 3 个：489 / 604 / 907 ms。
- 说明：我发请求的时间是 03:37:52，进程是 03:35:15 起来的，中间隔了约 2.5 分钟，别的 agent 可能已经先调过。所以这组数是"重启后最早一批并发请求之一"，不保证是第一批。
- 和第 2 版的 6–18 s 相比，并发冷请求在 2 s 以内，single-flight 有效。结论写进 `verify_dataalign_d2.md` 第 3 版附注。

## UIRSI 本轮（PW-016 / PW-014 / P1）

| 项 | 结果 | 判定 |
|---|---|---|
| F23 `#/script-chat` | 停在 `#/script-chat`，有"新对话""继续" | ✓ |
| F19 1280×720 工具菜单"串播审片" | 菜单里在 y=506–549，视口内 | ✓ |
| 画布"▶ 串播审片"按钮在屏内 | ✓ | ✓ |
| F08 ⋯ 菜单总是有"只重出视频" | ✓（ep02 没有视频的镜也显示） | ✓ |
| 场景字段不显示 sk_… | 画布正文里没有 sk_ id | ✓ |
| F16 画布行"本镜造型"角标 | ep02 这一集没有单独改造型的镜，角标不会出现 | **未测（状态相关）** |
| "✗ 不要"小框 | 见 verify_uimaster_r3.md 第 7 行 | ✓ |

## G10 功能回退（本轮）

`apps/web/e2e/uiaudit/r10g2_detect.json`，判定文件 `r10g2_regress.md`：**P0 = 0**，P1 = 1（F19：工具菜单 / 画布页没被 regex 采到"串播"二字，实际在菜单里，见上表；下轮调正则）。
iter_gate R1 请改读 `r10g2_detect.json`。
