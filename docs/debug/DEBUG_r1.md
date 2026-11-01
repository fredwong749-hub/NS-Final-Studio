# DEBUG-RSI r1 运行期问题清单（总调度 fredw-2b 派，2026-11-02 00:31 起）

> 项目方原话（11-02 00:3x）：“整一套系统的代码还是蛮多问题的,那你再启动第二个 ISI,专门做 debug,找问题.然后 GPU 那边肯定有很多问题啊,还有这边的那个康也有很多问题”
> 时间：笔记本是 Tokyo Standard Time（UTC+9），服务器是 America/New_York（EST，UTC−5），两边时钟都已校准（与 google.com 的 Date 头一致）。下文时间一律换算成笔记本时间。
> 状态：已修 / 已交（交给负责方）/ 待批。规则：knowledge/rules/ops_debug.yaml（K-OPS-E01–E05）；测试：tests/test_debug_rsi.py。

## 关键数字：出图慢在哪（端到端追踪）

依据：data/producer/log.jsonl（dispatch / rendered / contract_s）对照服务器 ComfyUI 的 /history（execution_start / success）。

| 段 | 香港线路前（23:43–00:26） | 香港线路后（00:44–） | 证据 |
|---|---|---|---|
| 派单 → ComfyUI 开始执行 | 0.5–15.7 分钟（ep01-S10：00:20:17 派到 gpu33:1，00:35:59 才开始执行） | 约 30 s | gpu33 :8189 /history；log.jsonl |
| GPU 执行 | 33–43 s（gpu33 / gpu36 全部生产图） | 同 | /history exec_s |
| 执行完 → rendered（取回 PNG 2.9 MB） | 2–3 分钟（ep01-S1 00:16:08 执行完，00:18:57 rendered） | 约 30 s（00:44:28 派 → 00:45:42 rendered，共 74 s） | 同上；bw_test.jsonl 单流 35–53 KB/s |
| rendered → 契约 + 看图出结果（contract_s） | 506 / 638 / 1484 s | 646 s；redo_fail 和 rendered 的时间差 576–1321 s | log.jsonl contract_s；redo_fail 时间戳 |
| GPU 实际利用率 | gpu33 三张卡 3.5 小时共出 9 张生产图（GPU 合计约 6 分钟） | — | gpu33 /history |

结论：跳板（香港线路切换前）让单张从 40 s 拖到 3–5 分钟；更大的问题是**契约打分 + 看图 8–25 分钟**，而且打分在等的时候占着派单线程（问题 1），GPU 大部分时间空着。

## 问题清单

| # | 现象 | 证据 | 根因 | 负责方 | 状态 | 规则 |
|---|---|---|---|---|---|---|
| 1 | 道显示“在做”，GPU 实际空闲；新派的单 15 分钟以上没交给 ComfyUI | 00:46 派出的 ep01-S10（gpu36:0）、ep02-S1（laptop:0）、ep02-S2（gpu33:0）、ep02-S3（gpu36:1）到 01:03 仍没交；4 个 ComfyUI 的 /queue 和 /history 都没有这几单；producer 进程只有到 127.0.0.1:8870 的连接，子进程只有 full_score 的 ssh（00:59 起）和训练锁 ssh | producer 派单线程池 = 道数（6）；_run_one 出完图还在本线程等契约打分 + 看图（8–25 分钟）→ 6 个线程全在等打分，新单在线程池里排队 | PRODUCER（CONSENT → DEBUG_RSI，by 总调度） | **已修**，01:08:53 重启生效：线程数 max(8, 3×道数)；打分积压 ≥ 2×道数×看图实例数就停派（score_backlog 事件） | K-OPS-E05 |
| 2 | 已经出好的图因为轮询超时被重派，白做一遍 | first:ep01-S8：gpu33:0 00:22:53 执行成功（/history），00:24:33 记 infra_error “/history timed out”，00:25:35 重派 | comfy_client.wait() 轮询 /history，只要一次 ComfyUnavailable 就整单作废 | REFLOCK（comfy_client，CONSENT → DEBUG_RSI） | **已修**（01:08 重启生效） | K-OPS-E01 |
| 3 | 下载断线被当成内容失败，算一次尝试 | first:ep01-S7：00:20:47 已出好；00:22:23 content_error IncompleteRead(65536 bytes read, 2868839 more expected)；attempts.json tries=1 | http.client.IncompleteRead 不属于 ConnectionError，classify 归为“内容”；download 不重试 | REFLOCK / PRODUCER | **已修**：HTTPException 改归 ComfyUnavailable，下载重试 3 次；ep01-S7 账本 tries 1→0（01:05，有备份和 audit 字段，总调度授权） | K-OPS-E02 |
| 4 | 超时取消会打断这张卡上别人正在跑的作业 | 原 wait() 超时调 self.interrupt() 发的是 {}（全局打断）；gpu33 :8188 和 gpu36 :8188 各有 1 条 execution_interrupted | 没用 ComfyUI 0.42 的 prompt_id 定向打断 | REFLOCK | **已修**：cancel(prompt_id) = 出队 + 定向打断 | K-OPS-E03 |
| 5 | 暂缓清单里的镜还在出图 | lookA_hold.json 00:57:52 生效；00:44 起的 producer 00:56:42 / 00:57:33 仍出了 first:ep01-S8 / S9；重启前在途 12 单全在暂缓清单里 | IMGFIX 00:58 才加读取逻辑，进程没重启 | PRODUCER / IMGFIX | **已修**：01:08:53 重启生效；补了测试 | K-OPS-E04 |
| 6 | 契约打分 8–25 分钟（23:50 前约 24 s） | contract_s 506–1484 s；switch.jsonl 出图方等本机看图让卡 990.5 / 722.3 / 1062.5 s；producer vqa_gate_err TimeoutError（00:13:08 ep01-S1、00:13:55 ep01-S4）；infra_error “同卡看图服务 300s 内没让出”（00:20:03）；score_retry full_score@gpu33 “mux_client_request_session: Session open refused by peer”（00:59:03） | ① 看图 VLM 单实例串行，本机看图和本机出图抢同一张 12 GB 卡；② full_score 每次新开 mux 会话，超过服务器 MaxSessions 被拒后重试；③ full_score 用 base64 经 ssh 标准输入传参考图（gpu33 上 python3 -c “import base64…req=json.load(stdin)” 的进程挂了 12 分钟） | VQAGATE（看图）/ NETFIX（mux 会话）/ REFLOCK（remote_score 传参考图） | **已交**（总调度 01:0x 转派） | — |
| 7 | 笔记本 producer 每单都新开一次跳板 ssh 握手 | 00:40:09 producer 52804 的子进程：ssh.exe gpu33 “ls -1A /root/.local/state/NS-Studio” 加 ssh.exe -W 194relay；producer.err 里多次 “读不到 gpu33 的训练锁…banner exchange” | 进程 00:14 起，早于 NETFIX 00:26 装的 shim；jobs._ssh_train_locks 每单现读一次 | NETFIX | **已修**：00:44 重启后 shim 生效（01:03 子进程已经走 wsl ssh -S） | K-OPS-N07（NETFIX） |
| 8 | 服务器常驻 night / producer 约 20 分钟被重启一次 | ops/logs/resident_sync.log：20:55–00:23 共 22 次 restart，每次 “stopped night … stopped producer … 作废租约 N” | resident_sync.loop 只要代码有变（code_changed_since）就 push + restart，十几个 loop 不停改代码 → 不停重启；restart 不等在途作业 | WORKFLOW（AUTOPILOT） | **已交**：建议改成只在常驻进程实际 import 的文件变了才重启，30 分钟内最多一次，重启前先排空 | — |
| 9 | gpu36 :8188 / :8189 出图 OOM、VRAM grow failed | gpu36 /history：:8189 “VRAM grow failed” 2 次、“Allocation … would exceed allowed memory (12.7 GiB)” 2 次；:8188 1 次；nvidia-smi：看图服务 pid 2350180 在 GPU0 占 8254 MiB、GPU1 占 458 MiB，和 ComfyUI 同卡 | gpu36 看图服务和出图道同卡，没有让卡机制（笔记本有 yield，服务器没有） | VQAGATE / NETFIX（分区） | **已交** | — |
| 10 | 本机出图道被看图卡住，最长等 17 分钟 | D:\ns_vqa\logs\switch.jsonl 的 yield 秒数 20.7–1062.5（8 次中 3 次 > 700 s）；00:27:05 三个让卡请求一起放行 | 看图推理排队时不让卡；comfy_client _yield_peer 等 300 s 超时后单子退回 | VQAGATE（server.py）/ LOCALGPU | **已交** | — |
| 11 | 服务器 history 里有零星 OOM | gpu33 :8188 / :8189 / :8191 在 10-31 23:45 有 OOM（不是今晚）；今晚 gpu33 无报错 | 旧问题 | — | 记录，未复现 | — |
| 12 | full_redo reject-old-jobs 调用参数错误 | ops/logs/reject_old_jobs.err.log 00:28：“unrecognized arguments: 脸部词、不挂身份脸（IMGFIX 00:3x…”——--note 后的文字带空格没加引号 | 调用方拼命令行 | IMGFIX / WORKFLOW | **已交** | — |
| 13 | 本机出图道 laptop:0 偶发 VRAM grow failed / Fault failed | D:\ns_comfy\logs\comfy_20261101_183640.err：VRAM grow failed 1、Fault failed 1（aimdo cuMemSetAccess）；118 单 p50 59.3 s、p90 66.1 s、最大 487 s | 和看图争 12 GB 显存 | VQAGATE / LOCALGPU | 已交（同 #10） | — |
| 14 | 看门狗、监管进程反复起 | data/netfix/supervisor.log 22:30–00:33 共 12 次 START；infra_watchdog.log 21:52–22:28 杀 ssh 52 次（22:34 改成只探测之后为 0） | 监管进程被 ensure / 重载反复拉起 | NETFIX | 已交（报告给 NETFIX），22:34 之后看门狗不再杀 | — |
| 15 | 孤儿 / 闲置进程 | gpu33：bench2.py h3（2 天 4 小时，0 CPU，父进程 35779）；gpu36：bakeoff run.py gen（13 小时，futex 等待，0 CPU）；两台 pagelock.py 锁 148 / 122 GB 页缓存（有意为之） | 旧实验没收尾 | BAKEOFF / 总调度 | **待批**（不占 GPU，没 kill；kill 前要负责方确认） | — |
| 16 | ComfyUI 常驻内存大 | RSS：gpu33 51 / 84 / 49 GB，gpu36 89 / 70 / 84 GB（--cache-ram 64 96 / 56 88）；gpu36 可用内存 90 GB、free 13 GB；两次采样（00:33 / 00:54）gpu36 没涨 | --cache-ram 第二个值 = 非活动缓存上限（cli_args.py:141），RSS 落在设定范围内 | — | 记录：未见泄漏趋势，gpu36 余量偏紧，建议观察 | — |
| 17 | 服务器负载 | gpu33 load 229（00:3x 的 5 分钟均值）→ 7.9（01:00）；gpu36 98 → 19.7 | v7_lipsync 吃满 96 核（VQAGATE 已修线程限制） | VQAGATE | 已消退 | — |

| 18 | gpu36 两条出图道 01:09 起没人派单（P0） | 笔记本 override_state.json gpu36=server（01:09:07）→ 笔记本 hold 了 gpu36:0/1；gpu36 本机 control.json（01:09:34 推）override_phases gpu36='draining'、only=__none__；gpu36 :8188 / :8189 最近 15 分钟 0 单，GPU 0% | server-control 推到 gpu36 的是切换前算出的 phase，翻成 server 后没有重推 | NETFIX | **已交**（01:14） | — |
| 19 | 香港线路下 gpu33 道仍然每单多 100 s | ep03-S5：01:09:12 派，01:09:14 开始执行，35 s 执行完，01:11:37 才 rendered（render_s 145.1）；ep03-S4 render_s 157.5 / gpu_s 39.8；supervisor.log 01:08–01:11 gpu33-l0 / l1 / l3 一直报 “PROBE slow… timeout” | gpu33 的转发看起来还没走香港线路，或者这条线下行慢 | NETFIX | **已交** | — |
| 20 | 本机看图被校准脚本长时间占用，laptop:0 出图道饿死 | 01:15：4080 显存 11.7 GB、利用率 100%，18388 队列为空；看图 heartbeat state=running；8870 的客户端包括 tools/vqa/v6_calib.py（pid 19784，00:19:34 起）；producer 01:09:41 派到 laptop:0 的 ep10-S3 01:15 仍没出图 | 实验脚本和生产共用同一个看图实例，没有让卡 | VQAGATE | **已交** | — |
| 21 | producer.err 里 cv2 在笔记本上读服务器路径 | “imread_('/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu3/ns_final/ep01-S3_image_v9_00002_.png'): can't open/read file”（2 次，cv2 进程启动后 0.03 s 和 34 s）——这是 host_path 被拿到本机读 | 来源没定位到（producer._postflight 只把 host_path 交给 remote_score；本机 gaze_mp / postflight 读到会静默返回 None → 这一项等于没测） | REFLOCK / VQAGATE | **已交**（附带：未测项要确认没有被当成通过） | — |
| 22 | 待重启才生效的改动在堆积 | VQAGATE K-OPS-V15（Q2–Q8 已经不过的图不送看图；11-01 08–16 点 214 张里有 151 张属于这种）01:1x 落地，producer 01:08 重启之后才加的 | — | 总调度安排 | **待批**：下一次 producer 重启（按 E05 的方式不 pause，一分钟内完成） | — |

## 修了什么

- services/render_router/ns_render/comfy_client.py（原版备份 data/_quarantine/debug_rsi_20261102/comfy_client.py.bak）：E01 轮询宽限、E02 IncompleteRead 归连接问题 + 下载重试、E03 cancel(prompt_id)。
- tools/autopilot/producer.py（备份 data/_quarantine/debug_rsi_20261102/producer.py.bak）：E05 线程池放大 + 打分积压背压 + vlm_instances()。
- tests/test_debug_rsi.py（12 条），knowledge/rules/ops_debug.yaml（E01–E05，compile --check 通过）。
- 01:08:53 重启笔记本 producer（50196 → 44720，不 pause；在途 12 单全在 lookA 暂缓清单里，不影响有效产出）。

## 打分改到服务器本机做（总调度第 3 项，方案）

现状：gpu33 道 → remote_score.postflight_full 一次 ssh 在 gpu33 GPU 上读原始输出、复现后处理再打分；gpu36 道 → 交付图上传到 gpu33 打分；看图 Q9 走笔记本 8870 或 gpu36 8870（内网代理）。每单要经跳板 1–2 次 ssh，还要传参考图。
改法：服务器常驻 producer 本来就在本机跑契约打分（OFFLINE_SELF）。把“出图 + 打分”整段交给出图那台服务器的常驻 producer（K-OPS-N06 的分区交还），笔记本只收结果 json + 缩略图（NETFIX outbox 回传）。前提是服务器资产补推完（assets_ready.json）。笔记本这边不必新写打分代码，等 NETFIX 交还分区即可。耗时实测待交还后做。
