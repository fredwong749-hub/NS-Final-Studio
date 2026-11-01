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
| 15 | 孤儿 / 闲置进程 | gpu33：bench2.py h3（2 天 4 小时，0 CPU，父进程 35779）；gpu36：bakeoff run.py gen（13 小时，futex 等待，0 CPU）；两台 pagelock.py 锁 148 / 122 GB 页缓存（有意为之） | 旧实验没收尾 | 总调度 | **登记不处理**（总调度 01:2x 定：bench2.py 在 /root/claude-kimi-ns-studio-v1 下，不是本项目；bakeoff 负责方不确定；都不 kill） | — |
| 16 | ComfyUI 常驻内存大 | RSS：gpu33 51 / 84 / 49 GB，gpu36 89 / 70 / 84 GB（--cache-ram 64 96 / 56 88）；gpu36 可用内存 90 GB、free 13 GB；两次采样（00:33 / 00:54）gpu36 没涨 | --cache-ram 第二个值 = 非活动缓存上限（cli_args.py:141），RSS 落在设定范围内 | — | 记录：未见泄漏趋势，gpu36 余量偏紧，建议观察 | — |
| 17 | 服务器负载 | gpu33 load 229（00:3x 的 5 分钟均值）→ 7.9（01:00）；gpu36 98 → 19.7 | v7_lipsync 吃满 96 核（VQAGATE 已修线程限制） | VQAGATE | 已消退 | — |

| 18 | gpu36 两条出图道 01:09 起没人派单（P0） | 笔记本 override_state.json gpu36=server（01:09:07）→ 笔记本 hold 了 gpu36:0/1；gpu36 本机 control.json（01:09:34 推）override_phases gpu36='draining'、only=__none__；gpu36 :8188 / :8189 最近 15 分钟 0 单，GPU 0% | server-control 推到 gpu36 的是切换前算出的 phase，翻成 server 后没有重推 | NETFIX | **已交**（01:14） | — |
| 19 | 香港线路下服务器道（gpu33 和 gpu36）仍然每单多约 100 s，全花在下载 PNG 上 | ep03-S5：01:09:12 派，01:09:14 开始执行，35 s 执行完，01:11:37 才 rendered（render_s 145.1）；ep03-S4 render_s 157.5 / gpu_s 39.8；supervisor.log 01:08–01:11 gpu33-l0 / l1 / l3 一直报 “PROBE slow… timeout” | gpu33 的转发看起来还没走香港线路，或者这条线下行慢 | NETFIX | **已交** | — |
| 19b | （补充证据）| ep02-S9：gpu36:1 01:16:07 执行完，3.1 MB 原图 01:17:43 才写进 data/renders/ep02/S9/takes/image_001_21ed6840_raw.png，约 33 KB/s；ep02-S8 01:16:21 → 01:17:58 同样慢。派单到开始执行只要 2–17 s（上传已经快了），下载没变快 | ComfyUI 端口转发（l0/l1/l3）可能没走香港线路，或者这条线下行就是封顶 | NETFIX | **已交** | — |
| 20 | 本机看图被校准脚本长时间占用，laptop:0 出图道饿死 | 01:15：4080 显存 11.7 GB、利用率 100%，18388 队列为空；看图 heartbeat state=running；8870 的客户端包括 tools/vqa/v6_calib.py（pid 19784，00:19:34 起）；producer 01:09:41 派到 laptop:0 的 ep10-S3 01:15 仍没出图 | 实验脚本和生产共用同一个看图实例，没有让卡 | VQAGATE | **已交** | — |
| 21 | producer.err 里 cv2 在笔记本上读服务器路径 | “imread_('/root/claude-kimi-ns-studio-v1/ComfyUI/output/gpu3/ns_final/ep01-S3_image_v9_00002_.png'): can't open/read file”（2 次，cv2 进程启动后 0.03 s 和 34 s）——这是 host_path 被拿到本机读 | 来源没定位到（producer._postflight 只把 host_path 交给 remote_score；本机 gaze_mp / postflight 读到会静默返回 None → 这一项等于没测） | REFLOCK / VQAGATE | **已交**（附带：未测项要确认没有被当成通过） | — |
| 22 | 待重启才生效的改动在堆积 | VQAGATE K-OPS-V15（Q2–Q8 已经不过的图不送看图；11-01 08–16 点 214 张里有 151 张属于这种）01:1x 落地，producer 01:08 重启之后才加的 | — | 总调度安排 | **待批**：下一次 producer 重启（按 E05 的方式不 pause，一分钟内完成） | — |

| 23 | ~~服务器 ComfyUI 没有日志文件~~（初判错误，01:2x 更正） | gpu33 三个 ComfyUI 是 systemd 单元 ns-comfy@{0-8188,1-8189,3-8191}，stdout 那个 socket 是 journald，日志一直在（journal 共 1.1 GB；近 3 小时 error 0 条）；gpu36 的 :8188 / :8189 写 /root/work/fredw/comfy/logs/gpu{0,1}.log，:8190 写 longshot/logs/lane.log，都不到 1 MB，之前没有轮转 | — | DEBUG-RSI | **已修**：gpu36 加 /etc/logrotate.d/ns-comfy-gpu36（50 MB 轮转、留 7 份、copytruncate，**不用重启 ComfyUI**，logrotate -d 验证通过）；gpu33 本来就由 journald 管 | K-OPS-E07 |
| 24 | gpu36 日志里有 LoRA 文件损坏、cuDNN 报错、OOM | gpu0.log：“h3-realism-people-t2v-i2v-r2v.safetensors … Tensor extends past the end of the file”（文件不完整）、cuDNN “No valid execution plans” 1 次、OOM 1 次；gpu1.log：OOM 3 次、VRAM grow failed 2 次；lane.log OOM 2 次；三个日志一共 7 次 Processing interrupted | 这个 LoRA 现在两台服务器的 loras 目录里都找不到，应该已被替换或移走，属于旧问题；OOM 同第 9 条（看图和出图同卡，L-100 已改为看图专用卡）；interrupted 和第 4 条全局打断有关（E03 已修） | VIDEO-RCA / VQAGATE | 记录 | — |

## 重启后 10 分钟（01:08:55–01:19:25，笔记本 producer 44720）

- 派单：gpu33:1 1 单、gpu33:3 1 单（之后 gpu33 进入 draining，交给服务器）、gpu36:0 2 单、gpu36:1 2 单（01:09–01:15 因问题 18 空了 6 分钟）、laptop:0 2 单，两单都没出（问题 20：01:14:41 infra_error “同卡看图服务 300s 内没让出”）、gpu33:0 被 IMGFIX 的实验占着、gpu36:2 被 VIDEO-RCA 占着。
- E05 生效：gpu36:1 01:17:44 出完 ep02-S9，01:17:55 就派了 ep04-S1，不再等打分。
- 每单：派单 → 开始执行 2–17 s；GPU 35–40 s；执行完 → rendered 97–108 s（下载，问题 19）；render_s 137–158 s。
- 打分：10 分钟内这 4 单一个都没打完（contract_s 还没出），打分 p50 > 8 分钟，和问题 6 一致。

## 修了什么

- services/render_router/ns_render/comfy_client.py（原版备份 data/_quarantine/debug_rsi_20261102/comfy_client.py.bak）：E01 轮询宽限、E02 IncompleteRead 归连接问题 + 下载重试、E03 cancel(prompt_id)。
- tools/autopilot/producer.py（备份 data/_quarantine/debug_rsi_20261102/producer.py.bak）：E05 线程池放大 + 打分积压背压 + vlm_instances()。
- tests/test_debug_rsi.py（12 条），knowledge/rules/ops_debug.yaml（E01–E05，compile --check 通过）。
- 01:08:53 重启笔记本 producer（50196 → 44720，不 pause；在途 12 单全在 lookA 暂缓清单里，不影响有效产出）。

## 打分改到服务器本机做（总调度第 3 项，方案）

现状：gpu33 道 → remote_score.postflight_full 一次 ssh 在 gpu33 GPU 上读原始输出、复现后处理再打分；gpu36 道 → 交付图上传到 gpu33 打分；看图 Q9 走笔记本 8870 或 gpu36 8870（内网代理）。每单要经跳板 1–2 次 ssh，还要传参考图。
改法：服务器常驻 producer 本来就在本机跑契约打分（OFFLINE_SELF）。把“出图 + 打分”整段交给出图那台服务器的常驻 producer（K-OPS-N06 的分区交还），笔记本只收结果 json + 缩略图（NETFIX outbox 回传）。前提是服务器资产补推完（assets_ready.json）。笔记本这边不必新写打分代码，等 NETFIX 交还分区即可。耗时实测待交还后做。

## 操作记录

- 01:0x 我在 gpu33 上 kill 了 pid 1531364（`bash -s`，已挂约 15 分钟，没有子进程，阻塞在 do_wait）。**推断是我自己的探测进程**：它的启动时间和我那次超时的探测吻合。kill 之后没看到别的会话报错。
- 从此以后：探测命令在服务器上一律套 `timeout`，退出时清理自己留下的临时文件和进程（K-OPS-E06）。

---

# r2（01:2x 起，总调度派：本机看图改专用、服务器交还之后的新瓶颈；目标 5 条出图道利用率 ≥ 80%）

测法：tools/debug/lane_util.py（ComfyUI /history，统计各作业 execution_start 到结束的并集 / 窗口长度，按 ns_tag.agent 分开；结果追加到 data/debug/lane_util.jsonl）。每 30 分钟测一次。

| 时间 | 窗口 | gpu33:0 | gpu33:1 | gpu33:3 | gpu36:0 | gpu36:1 | 平均 |
|---|---|---|---|---|---|---|---|
| 01:31 | 01:01–01:31（交还前后混合） | 0.206（未标 0.141 = IMGFIX 实验） | 0.129 | 0.112 | 0.123 | 0.137 | **0.141** |

交还后（gpu33 01:23、gpu36 01:25 起由服务器本机 producer 派单）服务器日志：

- 服务器本机：render_s 37–64 s、gpu_s 35–62 s，派单间隔 5–20 s；本机打分到出结果约 20–70 s（redo_fail 时间戳减 rendered 时间戳）。对比笔记本经隧道时 render_s 137–158 s、打分 8–25 分钟。
- 新问题 r2-1：gpu33 本机 producer 01:23:28、01:26:55 起了两次（sv-02 部署热重启）。重启后同一对象用同一个 seed 重派，ComfyUI 直接命中缓存（ep03-S4、ep03-S7：render_s 4.6、gpu_s 0.0），等于把同一张图再打一次分、再记一个版本。属于小浪费，记录。
- 新问题 r2-2：笔记本交还前出好、还没打完分的图（ep02-S8/S9、ep03-S6/S7/S8）服务器又出了一遍。总调度定：由 FACTORY D4（声明式 inbox 带上笔记本的在途 / 待打分对象）解决。
- 新问题 r2-3：gpu36 本机还是 sv-01，没有 hold 逻辑，01:24:51 出了暂缓清单里的 ep02-S1/S2。总调度 01:2x 正在单独 cut sv-03 部署 gpu36（推送前检查拦下了 cut 之后新建的两个代码文件）。
| 01:46 | 01:15–01:45 | 0.262 | 0.258 | 0.241 | 0.355 | 0.330 | **0.289** |
| 01:46 | 01:30–01:45（15 分钟） | 0.143 | 0.171 | 0.146 | 0.355 | 0.326 | **0.228** |

- r2-4（P0，已交 VQAGATE）：gpu36 的 vLLM（GPU2，:8000）一直 0%，没接到请求。vllm_proxy.py 没有在听任何端口，因为 127.0.0.1:8870 还被旧的 vqa/server.py（pid 2350180）占着。旧服务在出图卡 GPU0 / GPU1 之间反复装卸（server.log 01:26–01:44 共 12 次，其中 1 次 OOM），打分约 0.7 张/分钟，三条道出图能力约 4 张/分钟 → 两台的 E05 积压闸（上限 12）顶满（score_backlog：gpu33 01:38:47 / 01:43:52，gpu36 01:41:06），GPU 等打分。
- r2-5：笔记本 producer 01:45:02 重启（44720 → 13972，sv-02 代码）。手上 8 单打分卡了 16–27 分钟，而这几镜服务器已经重出过。
- r2-6（01:5x，总调度要求“删掉笔记本 :18388 排队的 9 单”）：**没删，也删不了**。01:51 查时 :18388 已经不在听端口（curl 连接被拒）。原因：最后一单在 4080 上 8 步跑了 5 分 07 秒（38 s/步，平时约 5 s/步，因为和 01:22 装上的专用看图抢显存），之后进程不再响应（comfy_20261101_183640.err 最后一行 01:44:18）。watchdog 01:45:54 判“18388 不通”去重启，新进程 01:45:58 报 “Port 18388 is already in use” 退出；旧进程 52092 还在，但内存只剩 29 MB、端口已释放，是挂死状态。原来那 1 跑 9 等的队列随进程一起没了，所以不用删、也无从按单号删。**派单方：未知**（总调度 01:5x 更正：VIDEO-RCA 核实 r19 / r20 一直在 gpu36 本机执行，11-01 20 点之后没连过 18388）。查过的线索：ComfyUI 日志不打 client_id 和 filename_prefix（0 处）；history 只在内存里，随进程一起没了；output/ns_final 最后一张是 01:37:53 的 ep10-S3_image_v9_00002_（“Prompt executed in 00:15:25”），那是笔记本 producer 01:22:27 派的 PRODUCER 单，不是那 9 单。不再追：笔记本 ComfyUI 已经停了，这个来源也断了。
  - 待批：按 L-100，笔记本 ComfyUI（19152 / 52092）和它的 watchdog（powershell 40220）应该停掉，否则 watchdog 迟早会把 ComfyUI 再拉起来，又和看图抢 12 GB 显存。这些进程归 LOCALGPU，我没动。
- r2-7（01:5x，总调度批准 L-100，CONSENT LOCALGPU → DEBUG_RSI）：停掉笔记本 ComfyUI（19152 / 52092）、watchdog（powershell 40220）和它刚拉起的 start.ps1（26492）；查了计划任务、HKCU Run 和启动文件夹，都没有会拉起 ns_comfy 的项（NS-Studio-Autostart-Trial 指向 D:/Coding/NS-Storyboard 下一个不存在的脚本，和这里无关），所以不用 disable 任何东西。config/render_endpoints.json 的 laptop:0 改成 hold=true + disabled=true，原因写进 _hold_change 和 label（check_lane 只允许这几个字段）；services/api/ns_api/infra_status.py 在 disabled 时只显示“笔记本显卡：看图卡”，不再报“没在运行 / 离线”。gpu_live 和 producer 读的 _extra_lanes 会跳过 disabled 的道。测试：tests/test_debug_rsi.py::test_l100_laptop_lane_disabled_and_shown_as_vqa_card；localgpu_lane / infra_status / gpuview / producer 一共 100 条全过。API :8800 要重启才会加载 infra_status 的改动。备份在 data/_quarantine/debug_rsi_20261102/。

| 时间 | 窗口 | gpu33:0 | gpu33:1 | gpu33:3 | gpu36:0 | gpu36:1 | 平均 |
|---|---|---|---|---|---|---|---|
| 02:20 | 01:50–02:20（切 vLLM 前后混合） | 0.470 | 0.473 | 0.450 | 0.698 | 取不到 | 0.523 |
| 02:20 | **02:05–02:20（切 vLLM 之后）** | 0.536 | 取不到 | 0.442 | 0.797 | 0.772 | **0.637** |

- r2-8：切 vLLM 之后，gpu36 到了 0.77–0.80，gpu33 停在 0.44–0.54。gpu33 的根因（服务器日志）：派单到这一单真正开始执行之间排了 50–100 s，例如 gpu33:3 02:08:30 派单、02:10:04 才 rendered，但 render_s 只记 39.9 s——线程池排队的时间没算进去。原因是本机线程池 18 个线程（max(8, 3×6 道)），而积压上限是 48（2×6×4）；gpu33 打分 p50 352 s / p90 563 s（gpu36 是 132 / 253 s），等打分的单把 18 个线程占满（inflight 19），新单只能在池里排队。**已修**（K-OPS-E05 修订）：线程数改成 积压上限 + 2×道数。要部署到服务器、重启常驻 producer 才生效。
- r2-9（已交 VQAGATE）：gpu33 打分出现 score_infra：“看图模型输出不是 JSON”（02:16:02），以及“ssh … gpu36 unreachable from gpu33 (no cross-host key)”（02:17:11）——看图客户端连内网入口失败时退去走 ssh，而 gpu33 没有到 gpu36 的密钥。
- r2-10：gpu33 打分慢的地方还有 clip_srv.py（comfy env）。FACTORY 说 gpu36 的 CLIP 退到了 CPU（89 s）——我这次测的是 gpu36 打分 p50 132 s，比 gpu33 快，下一轮单独拆段计时。
- r2-11（02:2x–02:36，热修，总调度 02:22 令）：只在服务器各自现有的 producer.py（sv-03，sha 5ef221b0…）上就地补了 K-OPS-E05 线程池那一处（远端脚本做替换 + compile 检查，原文件备份在 /root/work/fredw/debug_rsi_backup/producer.py.sv03.*）。热修后两台 sha 都是 **21f7ffeb615d12ca8be8c97f60fe5b6a821021429ac94aea4008a78713d0c332**。笔记本那份 producer.py 里还有暂停 / dryrun / RUN_ID 等没部署的改动，所以没有整份推上去（服务器缺 policy.pause_decision、import_events.py、config/pipeline/run.json）。重启已排进 restart_queue（urgent）：gpu33 1f43d29cfb1f、gpu36 e1ce79339c69，等 resident_sync 执行。
- r2-12（02:33，**gpu33 四张卡 0% 的真实原因不是线程池**）：gpu33 本机 producer 分区（42 镜）里已经没有 ready 对象——首帧 41 个是“驳回重出 2 次都没换上，等总调度定”，尾帧 16 个是“首帧过契约”才能做。gpu36 同样有 36 个首帧卡在“等总调度定”，只剩 10 个 ready。这是一道决策闸门：驳回计划用完、没有自动的下一步。两台合计 77 个首帧在等总调度。

## r2 后段（02:3x–03:0x）：producer 接手后的改动和 P0“0 张通过”

- r2-13（P0 根因，K-OPS-E10）：02:00 之前和之后都是 0 张通过（gpu36 02:00 前 26 张 / 后 59 张 redo_fail，gpu33 前 27 / 后 64）。02:00 后的失败里，**约 30%（gpu36 19/61、gpu33 19/64）blocking 为空**，照样记 redo_fail。根因在 vqa/contract.py:apply()：契约先按“Q9 未跑”判了 ok=False，看图回来是 pass 时，代码是 ok = 旧 ok and Q9 没挡，永远翻不回 True。笔记本已修并补了测试；**服务器热修被权限系统拦下**（Remote Shell Writes），没有绕过。补丁脚本在 scratchpad 的 hotfix_vqa.sh，交项目方决定是否执行，正式版随 sv-04 发。
- r2-14（真没过，约 70%）：Q1 身份 ArcFace 0.61–0.64 < 0.70（gpu36 33 张、gpu33 36 张）；看图判的配饰不符 38 / 26、服装不符 29 / 11、看镜头 10 / 4、塑料感 9 / 6。身份线不降（项目方要求人物一致）。根因待查：身份参考和本镜造型冲突、多张参考互相稀释，还是这批景别本身就测不准。和 VQAGATE / IMGFIX 一起抽样核对。
- r2-15（K-OPS-E09）：驳回阶梯写成代码，“等总调度定”这个出口删掉；策略写在 config/policies/retry.yaml redo_ladder。
- r2-16（K-OPS-E08）：暂停口径。判定 = policy.pause_decision；set_paused 强制写 reason_kind + expires_at；producer 和 infra_watchdog 每拍执行；restart_producer.ps1 改为 --kind ops --expires-s 180、最多等 3 分钟。
- r2-17：dryrun 修好。FakeFrameExec 补上 Q9 pass；原来看图闸门要求 Q9，演练里的图一直设不成当前，被 reconcile 撤回后无限循环、退出码还是 0。现在 S1 视频 passed 才算成功，否则返回 2 并报卡在哪一步；普通演练和注入演练都能走通。
- r2-18（K-OPS-W15）：RUN_ID 改成读 config/pipeline/run.json；import_staged 成功后调 import_events.append_import。
- 待做：(2) 登记表一致性检查进 data_parity + 修派生逻辑；(3) auto_force_eps 只对过了契约的镜生效；(4) 尽力版在规则 / 资产版本变化时自动 reset；多 run（DISTILL 接口）；import-staged --run（第二季）；Q1 和配饰误判抽样核对。
