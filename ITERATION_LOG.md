# ITERATION_LOG — NS-Final Studio（只追加；格式：轮次 | 日期 | 阶段 | 假设 | 变量 | 冒烟分 | 结局 | 备注）

| 轮 | 日期 | 阶段 | 假设（一句） | 改的唯一变量 | 冒烟分 | 结局 | 备注 |
|---|---|---|---|---|---|---|---|
| R0 | 2026-11-03 15:5x | Phase R | 先有"跑通"的定义才有迭代 | 新建 eval/run_smoke.ps1（八门） | — | 进行中 | 基线未跑；采纳 RSI 实施包（L-170）。此前 11-01～11-03 的工作按 docs/master/OVERSIGHT_LOG.md 第 1–29 轮与 MASTER_PICTURE L-001…L-169 追溯 |
| R0b | 2026-11-03 15:56 | Phase R | cut B 入版即 best 基线（服务器本地打分是跑通前提） | sv-20261103-02 发版 + 部署两台 + L-152 换代 | — | 进行中 | best=44e6c37；deploy 起跑 |
| R0 结果 | 2026-11-03 16:16 | Phase R | （同上） | eval/run_smoke.ps1 建成（W26） | **1/8**（15.2 s；只过 G7） | 基线已立 | G1 :8800 没在跑（16:15 已重启）；G2/G3 smoke_v2 缺 asset_refs.json 项目条目→5 缺口→build_first 空；G4–G6/G8 连带未跑。下一轮唯一变量：asset_refs.json 加 smoke_v2 条目 |
| R1 | 2026-11-03 16:19 | Phase R | smoke_v2 缺资产项目条目是 G2/G3 根因 | config/recipes/asset_refs.json 加 smoke_v2（inherits series10_v2） | **2/8**（10 s；G1 过因 :8800 已重启、G7 过） | 采纳（分数升，配置留下） | G2 仍 3 缺口：祁念造型对不上 P1 登记（script_match 0.35）、唐瑶本集造型排期没进 hub_episode_looks.json、第 3 条见 eval/results/20261103-1618.json；G3 StyleMissing：config/compile/run_style.json 没有 smoke_v2 风格后缀。下一轮唯一变量：smoke_v2 模板补齐本剧级配置（run_style + P1 looks/排期对齐夹具） |
| R2 | 2026-11-03 17:21 | Phase R | smoke_v2 本剧级配置对齐主剧即 G2/G3 过 | run_style.json 加 smoke_v2 + 夹具/排期对齐（W26b） | **2/8**（1690 s；G2 ✅ 新过、G7；G1/G8 失败因 :8800 在 16:52 又不通——外因） | 采纳（G2 由红转绿；总分未升因 API 外因） | G3 只差出图日志关键字（rendered + takes.references）；G4 25 分钟内首帧 3/3 + 尾帧 2/3 真出了、视频 0/3（VIDEO10 在服务器端，未换代）。下一轮唯一变量：:8800 为何反复被杀（与 cut/全量 pytest 同时段）—守卫落地后重跑 |
| R3 | 2026-11-03 22:05 | Phase R | :8800 反复被杀靠看门狗/守护自愈 | watchdog 规则 10 + resident_guard 看护 autoflow（W27） | —（未重跑：gpu36 看图服务死、cut C 被挡） | 代码采纳、分数待测 | 真机制已被 A-G3 预检抓到：system_version._kill_tree taskkill /T 按 pid 杀树、pid 复用误杀（W37 修）。换代里程碑：gpu33 本地出 ep01 首帧（L-180） |
| R4 | 2026-11-04 01:3x | Phase R | cut C 入版后服务器拿到 adopt 过滤 / 写路径前缀 / 看门狗 / 守卫，冒烟 G1/G8 不再因 :8800 被杀而红 | sv-20261104-01（e56e5e1；W17b/W18b/W20～W37/A-G3 分期 1 共 130 文件） | —（deploy 后重跑） | 进行中 | cut 后半段撞陈旧 index.lock（17:29 误杀遗留）由总调度补完；W37 _kill_tree 身份核对 = 该类事故根因修法 |
| R4 结果 | 2026-11-04 02:30 | Phase R | （同上） | sv-20261104-01 已部署两台 + verify ok | **1/8**（1523 s；只过 G2） | 不升 → best 不动（仍 44e6c37） | G1 红=笔记本看图 :8870 没起（环境，非代码）；G3/G4 红=smoke_v2 窗口内无 rendered（笔记本 producer only=__none__，smoke 出图链路未接到服务器）；G7 红=W38 改 sop_gate 后 smoke_v2/ep01_prompts.json 两遍不一致（P1 交 W38）；G5/G6/G8 连带。ep01 冲刺不因此停 |
| R4 冲刺结果 | 2026-11-04 07:54 | Phase R | ep01 全自动跑通到成片 | 热修 hf-01..17 + hf-w46-01..04（判定口径 L-182～L-185、参考/证据/路由/车道/成片链路） | —（冒烟待重跑） | **ep01_v1.mp4 已出**（45.04 s，11 镜，硬规矩 pass） | 6 镜首/尾帧为待项目方复核版（S4/S5/S7/S8/S9/S11）；整集 45 s < L-092 60 s（逐镜裁 ≤6 s）；全部热修待下次 cut 入版 |
| R4 入版 | 2026-11-04 13:38 | Phase R | （同上） | sv-20261104-02 = cut D（ep01 冲刺全部热修 + W40/W42/W44/W45/W46 交付，84 文件） | —（未 deploy、未重跑冒烟） | 入版、交接 PowerShell | 项目方 13:38 令本会话停止调度；deploy/冒烟/best 由接手方做 |
| — | 2026-11-04 13:38 → 2026-11-07 10:4x | — | **日志断裂**：此期间 STATE / ITERATION_LOG 未维护（约 20 个版本 sv-20261104-03…sv-20261107-12、冒烟未重跑），本次审计后恢复。不假装连续。 | — | — | — | 依据：《审计与修复指令 20261106》P0-1 |
| A1 | 2026-11-07 10:4x | Phase R 冻结 | 审计 Step 1：冻结仪式 | release.json enabled=false；CLAUDE.md 顶部硬规则；producer.py 冻结令；.gitignore 去掉 state.json / knowledge/generated（留 state.example.json） | — | 完成 | 证据：config/pipeline/release.json、CLAUDE.md、.gitignore |
| A2 | 2026-11-07 10:4x | Phase R 冻结 | 审计 Step 2：按事实重写 STATE | STATE.md 重写（服务器实跑 sv-20261107-11；冒烟最近 1/8 @11-04） | — | 完成 | 证据：STATE.md、data/system_version.txt、eval/results/20261104-0204.json |
| A3 | 2026-11-07 11:0x | Phase R | 冒烟基线 | 无（HEAD effe0bd0 实测） | **2/8** | 基线 | G1/G7 过；G2 被 QW-L12（夹具 3 镜同景别同机位）拦；eval/results/20261106-2103.json |
| A4 | 2026-11-07 11:1x | Phase R | 夹具镜2 改近景即可过 QW-L12 → G2 过 | eval/smoke/P4_smoke.md 第 81 行 中景→近景 | **1/8** | 降 → 已回滚 | 改夹具使 sop_gate 导入复验缓存失效，新红 H3-A1×2 + G7 不幂等（import_revalidate.json 两遍不同）；eval/results/20261106-2105.json |
| A5 | 2026-11-07 11:2x | Phase R | G2 三处一起修：夹具镜2 近景（QW-L12）+ 夹具镜1/2 S.SS 4.46/5.17（H3-A1，夹具自身错）+ import_revalidate 按剧预期 block（smoke_v2 豁免 QW-E2/E3） | 同一门 G2 | **2/8**（G1/G2 过；G7 新红） | 持平 → 已回滚 | G2 首次过；G7 红因：第二遍 import_revalidate.json 没落盘（API 进程内 _MEMO 命中不写文件）；eval/results/20261106-2108.json |
| A6 | 2026-11-07 11:4x | Phase R | A5 + import_revalidate 进程内记忆命中也落盘（G7 两遍一致） | 同一门 G2/G7 | —（未出分） | 被 Claude Code 内存回收中途杀掉 | 代码改动保留在工作区未提交（tools/master/import_revalidate.py、config/pipeline/sop_gate.json、eval/smoke/P4_smoke.md、tests/test_import_revalidate_memo_1107.py 16/16 过）；smoke_v2 已手工翻回 paused；等项目方说“重跑冒烟” |
| P1 | 2026-11-07 18:2x | 冻结期例外（项目方 a） | gpu33 本机算阶段错 → 0 视频道 | 两台服务器 config/pipeline/state.json run_phase.mode record→enforce（项目方亲手跑 ops/psmaster/runphase_enforce_1107.py；备份 .bak_rp_1107；回退 --revert） | —（非冒烟） | 生效 | 18:24 两台 lane_roles_phase frames→videos；ep03 11 镜 queued→rendering；gpu33 GPU0/1 100% |
| A6 | 2026-11-07 18:3x | Phase R | A5 + import_revalidate 记忆命中补写落盘 | 同一门 G2/G7 | **3/8**（G1/G2/G7 过） | 升 → 保留、已提交 | eval/results/20261107-0432.json；下一门 G4：producer once 25 分钟 0 派图（同 A5） |
| A7 | 2026-11-07 19:0x | Phase R | G4：dispatch.py 对 kind=smoke 剧不挂服务器道 → 笔记本冒烟 producer 能派图 | tools/netfix/dispatch.py control_for + runs.json smoke_v2.kind | **3/8**（G1/G2/G7） | 持平 → 已回滚 | 改动没生效：A7 窗口 19:03:42 写 smoke_v2 control 的是一个仍跑 11-01 版 dispatch（无 L-202 字样）的常驻进程，照旧 hold 全部 6 道、only=__none__；候选为 11-03 起没重启过的笔记本 producer serve / sentinel / monitor。eval/results/20261107-0503.json |
| P2 | 2026-11-07 20:2x | 冻结期例外（项目方 both） | 补丁 v3 §2 上线 gpu36 + 笔记本 11-03 起的旧常驻进程重启 | 发版 sv-20261107-13（ec89806e；night.py / assemble_series.py + 7 测试；闸门三修：RUNTIME_IGNORED 豁免、D-V2-190 跟随冻结、ops/psmaster 归 FACTORY）；producer serve / sentinel / monitor 重启 | —（非冒烟） | 已部署 | 20:24 两台 night 跑新码；签名口径切换 → ep01/ep04 各重开一次（预期，ep01 将到 v76）；验收（同输入 0 新版本）观察中；注意：发版工具生成的提交信息仍是“系统版本（K-OPS-V01）”模板，违反审计规则，待改 system_version.py |
| B1 | 2026-11-07 20:5x | Phase R 基线 | P2（sv-13 上线 + 旧常驻进程重启）后重跑 | 无代码改动 | **3/8**（G1/G2/G7） | 平 → 记基线（无改动可回滚） | eval/results/20261107-0625.json，code 8d9e4135；G4 仍 0 派图 |
| A9 | 2026-11-07 22:4x | Phase R / 线 0 基线 | G4：重启 11-05 起跑旧码的 tunnel_supervisor（每 30 s reconcile 写 smoke control）+ dispatch 对 kind=smoke 剧笔记本独占派图 | 41da4458（dispatch.py + runs.json kind + 测试）；tunnel_supervisor 22104→26356 | **3/8**（G1/G2/G7） | 平 → 根因报告 R1（G4 第 3 次不过，止损；回滚与否入裁决清单 #2） | eval/results/20261107-0838.json，code 1aca3ee7；control 已对（22:40:59 only=[S1,S2,S3]、hold 仅 gpu36:2/laptop:0、窗口内未被覆盖），但 producer 22:45:02 priority_yield→series10_v2(9)，0 派图 |

### R1 根因报告：冒烟 G4 0 派图（11-07 23:2x，线 1；A5/A7/A9 三次不过，止损）
结论：G4 有两层拦截，第一层已除（证据成立），第二层是 producer 的优先级让路，冻结区代码，止损待裁决。
第一层（已除）——写 control 的进程：
1. 写者唯一：全仓只有 tools/netfix/dispatch.py 写 data/producer/runs/<run>/control.json（laptop_run_controls / pause_run_control / apply）。
2. 调用者：tools/netfix/tunnel_supervisor.py:723-735 每 30 s 后台线程 dispatch.reconcile() → laptop_run_controls；dispatch 只在启动时 import，不 reload。
3. 进程：pythonw tunnel_supervisor.py serve，PID 22104/13456，CreationDate 2026-11-05 22:24 JST（11-05 08:24 EST），跑启动时那份 dispatch。
4. 时间序列：A7 窗口 19:03:42 smoke_v2 control 被写成 hold 全部 6 道 + only=__none__（ITERATION_LOG A7 行）；A5/A6/B1 窗口同样 0 派图。
5. 处置（选“升级”不选“停”）：tunnel_supervisor 管隧道，停掉 = 笔记本到两台服务器断线；22:36 重启到当前码（PID 26356），隧道 ADOPT 原连接，两台 hostname 探测通。
6. 处置后证据：A9 窗口 22:40:59 control = only=[ep01-S1,S2,S3]、hold 仅 [gpu36:2, laptop:0]、paused=false；窗口内 mtime 不再变；23:04:46 窗口结束由 runs.json 改回 paused（正确）。
第二层（未除）——优先级让路：
7. data/producer/runs/smoke_v2/log.jsonl 22:40–23:05：只有 review_scale ×12 与 priority_yield ×1（22:45:02 to={series10_v2: 9}；9 = 该剧 ready 帧数，不是优先级），0 条派单。
8. 代码：tools/autopilot/producer.py:3959-3965 dispatch_frames 先调 higher_priority_busy（:523-538）：priority 数字更小且 producing 的剧登记表里有 ready 首/尾帧 → 本剧整拍不派。
9. 配置：config/pipeline/runs.json smoke_v2.priority=50、series10_v2.priority=0；series10_v2 生产中几乎总有 ready 帧 → 冒烟剧永远让路。
10. 该层从 A5 起就在（第一层把它挡住看不见），不是 A9 引入。
需要项目方：裁决清单 #1（冒烟窗口内 smoke_v2 priority）。producer.py 冻结，不改让路逻辑。
| A10 | 2026-11-08 03:2x | Phase R / 线 1 裁决 #1 | G4：smoke_v2 priority 50→-1（项目方批准） | 354e80c0（runs.json 一行） | **3/8**（G1/G2/G7） | 平 → 保留（项目方裁决，非盲试）→ 根因报告 R2 | eval/results/20261107-1322.json，code 354e80c0；G4 15.8 s 即结束（不再是 1500 s 超时），0 派图 |

### R2 根因报告：A10 后 G4 仍 0 派图（11-08 03:4x，线 1；G4 第 4 次不过，止损）
证据只有两处：G4 窗口的 smoke log.jsonl 被其后 G7 两遍重建清掉（data/producer/runs/smoke_v2/ 现只剩 control.json），能看的是 results 里 once 的 stdout 尾巴和 oom 摘录。
1. once 15.8 s rc=0 退出（之前三次都是 1500 s 超时）：派单路径行为变了，但“已越过优先级让路”**没有直接证据**（日志被清）。
2. 第三层（证据成立）：once 输出 ep01-S2 等 reasons=["K-OPS-F03 refs 与目标状态不一致：期望 refs 表里没有剧 smoke_v2（先在笔记本 inbox.py build + sync push）"]。
   代码：producer.py:1332 派单前调 tools/factory/inbox.check_refs；inbox.py:66-70 非主剧查 expected["runs"][run]，没有 → 拒派。
   为什么没有：inbox.py _runs（:107-117）只给 status ∈ LIVE_STATUSES 的剧建期望表；smoke_v2 平时 paused，只在 G4 窗口里被 smoke.py 翻 producing 25 分钟，窗口内没人重建表 → 冒烟剧永远不在表里。
3. 第四层（评估器误报，证据成立）：eval/smoke.py:44 OOM_RE 含 OOM；producer.py:3853 review_resident_hold 的 why 文本写着“（免 OOM）”→ 只要审图卡驻留，G4 就记“日志有 OOM”判失败，即使出了图。evaluator 冻结不动。
4. review_resident_hold gpu33:3 本身正常（L-206 审图卡不派出图），不是拦截层。
需要项目方：裁决清单 #4（第三层）、#5（第四层）。
| A11 | 2026-11-08 03:4x | 总指令 第二部分 裁决 #4/#5 | G4：冒烟剧进期望 refs 表（1f593bc5）+ OOM 误报判定（75df58a9）；手动 inbox build 后表含 smoke_v2:3 | 两个 commit | **3/8**（G1/G2/G7） | 平 → 保留（项目方裁决，非盲试；首帧已出 = 实质推进）→ 根因报告 R3 | eval/results/20261107-1347.json，code c9faf54d；G4 首帧 3/3 镜有本窗口版本（每镜 8 版）、G3 缺项 6→3（只剩尾帧）；尾帧 / 视频 0；1500 s 超时；OOM 仍报（review_scale 尾巴的旧 last_error） |

### R3 根因报告：A11 后 G4 仍不过（11-08 04:2x；G4 第 5 次不过，止损）
推进：两层拦截已除（R1 第一层、R2 第三层）——冒烟 producer 本窗口真派图，三镜首帧各出 8 版（eval/results/20261107-1347.json G4 evidence.first）。
剩下三层（证据只来自 results 的 once 输出尾巴与 oom 摘录；窗口日志又被 G7 重建清掉）：
5. 尾帧拦截：once 尾巴 = ep01-S3 "尾帧生成契约 preflight 连续 3 次不过 → 本镜视频退回只给首帧（I2VA，L-204 D8；绑定首帧 v7）"，
   preflight 理由 I6 “图3 的‘必须一致’标注不在提示词里”、I9 “实际送进模型的参考……与槽位规划不符”。I2VA 兜底 = 设计上不出尾帧，
   而 G4 过门要 3 张尾帧（评估口径不动）→ 只要兜底触发，G4 必不过。待查：是冒烟夹具 eval/smoke/P4_smoke.md 尾帧行写法，还是编译器对 3 参考尾帧漏标（生产剧同型？ep01-S4 尾帧兜底同路径）。
6. 视频：本窗口 0 段。冒烟剧的视频由谁出未核实（服务器 vidgen 按 series10_v2 jobs.json；smoke_v2 不在任何视频作业表里——待查证，不下结论）。
7. OOM 判定：review_scale 事件的 tail 带 :8878 看图实例的历史 last_error（真 CUDA OOM，非本窗口生成）→ 每次都记“日志有 OOM”。属评估口径问题，按红线不改 eval。
需要项目方：裁决清单 #6 / #7 / #8。
R3 补（04:4x，裁决 #6/#7 缺省 = 只读取证，已做）：
- #6 尾帧 I6/I9：series10_v2 生产日志“尾帧生成契约 preflight”0 次 → 冒烟专有。I6 判定在 services/agent/ns_agent/gen_contract/preflight.py:333-338（非脸槽的 slot.line 必须原文出现在提示词里）。
  定位到具体哪一槽 / 哪句需要冒烟窗口的 preflight 报告，而该日志与 data/renders/smoke_v2 每次被 G7 重建清掉 → 本次取证止于“冒烟专有”。下次 G4 窗口由总调度在旁拷贝 log.jsonl 与尾帧作业记录（不改 eval）。
- #7 视频：两台服务器常驻只有 vidgen.py run <host> --run series10_v2 与 night.py，笔记本无视频工人；全仓 tools/series10_video 无 smoke 字样 → 冒烟剧视频**无人出**，G4“视频 3/3”在现有部署下不可达（结构性，非偶发）。

### R4 根因报告：裁决 #7/#8 批准后执行前核实，两条前提都不成立（11-08 08:5x JST；只读取证，未动任何进程）
#8（“:8878 last_error 是旧的，重启清掉”）——错，R3 第 7 条更正：OOM 是**本窗口真 OOM**，且根因在审图卡缩容失效。
1. gpu33 /root/work/fredw/vqa/logs/server_8878.log 最后一次写 11-08 03:54、server_8877.log 03:53 = A11 冒烟窗口内；末行均 torch.OutOfMemoryError（GPU 3）。三个实例 :8876/:8877/:8878 的 /health last_error 全是 OOM，不止 :8878。
2. 三实例自 11-06 19:01–19:04 起一直在（pid 3972477 / 3972951 / 3976738）；/root/work/fredw/vqa/ 只有 server_8876.pid + router_8870.pid，8877/8878 无 pid 文件。
3. 生产 producer 日志 data/producer/runs/series10_v2/log.jsonl：review_scale phase=videos want=1 共 79 次全部 ok=true（末次 11-08 05:26:56）——但实例仍是 3 个。
4. 代码：tools/vqa/review_instances.sh:206-220 scale 只经 stop_ports（:68-73）按 pid 文件停；无 pid 文件 = 静默不停；随后 health "$K"（:217）只判“活着 ≥K”，3≥1 → rc 0。L-207“视频段审图卡只留 1 实例”从未生效。
5. 后果一（生产）：GPU3 同卡还有视频 ComfyUI :8191（pid 1379405，comfy-launch-reserve9.sh，就是各条 OOM 文本里的“Process 1379405 868 MiB”）。journalctl 11-07 18:24–18:28 该进程 24 次 “Allocation on device 0 would exceed allowed memory (out of memory)”，:8188/:8189 0 次 → vidgen_gpu33.log 18:24:32–18:28 ep03-S1/S2/S8/S9/S10/S11 各 4 变体 RENDER_ERR → settle_rec 无打分 → blocked。gpu33 四卡此后 0% 空转（★闲卡：活在等卡）。
6. 后果二（冒烟）：审图实例自己也 OOM → review_scale 尾巴带 OOM → G4 判“日志有 OOM”。#5 误报修正不涉及此条（它是真 OOM，评估器报得对）。
#7（“gpu36 临时起 vidgen --run smoke_v2”）——单起工人不够：
7. smoke_v2 在两台和笔记本都没有 data/pipeline/runs/smoke_v2/video/（无 jobs.json、无 control、无 hosts.json）。
8. config/pipeline/video_policy.json scope_runs = [series10_v1, series10_s2, series10_v2]；tools/series10_video/build_jobs.py set_run 对登记过却不在 scope_runs 的剧失败关闭（PolicyMissing）→ 冒烟剧编不出视频作业。要出冒烟视频需：视频政策登记 + hosts 分配 + 窗口内首尾帧出完后 rebuild_jobs + control + vidgen，是一条链的配置改动，不是一个临时进程。
需要项目方：裁决清单 #7、#8（已按本报告改写）。
| R4 执行 | 2026-11-08 08:5x–09:1x | 裁决 #8（改写版） | 停 gpu33 :8877/:8878（pid 3972951/3976738，核对命令行为 vqa/server.py；记 vqa/logs/switch.jsonl）→ GPU3 20.2→7.3 GB；ep03-S1/S2/S8/S9/S10/S11 写视频重做单（master_rejects，by=PS-MASTER，触发清单已在）→ 08:55:37 六镜重新提交；代码 cd85d3ec 只入库 | — | 冒烟未重跑（3/8） | 生产恢复：gpu33 三卡 0%→100%；冒烟待 #7 齐后一并重跑 | gpu33 vidgen_gpu33.log 08:55:37 SUBMIT×6 |

**P3（冻结期例外，项目方 11-08 点名批准“7a 三道”）**：gpu36 发版部署目录 /root/work/fredw/offline_20261101/repo/config/pipeline/video_policy.json 手放一行 scope_runs += smoke_v2（原文件 .bak_P3_1108；内容 = 笔记本 71271f28；下次发版自然覆盖为同内容）。核验：gpu36 上 NS_RUN=smoke_v2 run_ctx.resolve() 通过。冒烟窗口内 gpu36 三道出冒烟视频（窗口看守：night.py --run smoke_v2 + 每 20 s 拉回 clips + 取证拷贝 #6；窗口关即停 night 与 vidgen_smoke_v2.pid）。回退：恢复 .bak_P3_1108。
| A12 | 2026-11-08 09:10–09:37 JST | 裁决 #7a（P3）+ #8 后首跑 | G4：冒烟视频链（night --run smoke_v2 + gpu36 三道 + 拉回 clips）+ 审图卡腾出 | 700cbbae | **3/8**（G1/G2/G7） | 平 → 保留（项目方批准动作，非盲试；首帧 3/3 镜本窗口有版本、G3 缺项只剩尾帧）→ 根因报告 R5 | eval/results/20261107-1910.json；窗口取证 scratchpad smoke_A12/（watch.log、night.out、snap_live 57 行 log.jsonl） |

### R5 根因报告：A12 后 G4 仍不过（11-08 09:5x JST；三层各报状态，不开新一轮取证）
A. 尾帧（#6）——**未修**。窗口日志已拷出（smoke_A12/snap_live/data/producer/runs/smoke_v2/log.jsonl）：last:ep01-S2 09:30:17 / 09:31:29 last_preflight_fail
   “I6 图3 的‘必须一致’标注不在提示词里；I9 实际送进模型的参考图与槽位规划不一致”→ 09:32:43 last_unavailable（I2VA 兜底）。S1/S3 首帧没过，尾帧没轮到。
   定位到代码路径：尾帧 compose = frame_job.build_last_compose → build_first(continuity_ref=首帧) → continuity_slot（:417，槽满 3 时让位最后一个非脸槽、
   首帧挂末位）。具体是哪一槽的标注在让位 / 改号时丢失：preflight 失败的作业不落盘、日志只有理由串 → 下一步本地复现（smoke 夹具 S2 尾帧作业 + preflight），
   结论是编译器 → 修 continuity_slot（复现测试同 commit）；生产 0 次的原因待复现确认（疑生产镜槽位多不满 3）。
B. 视频（#7a）——**链已通、本窗口没轮到**。night --run smoke_v2 窗口全程在跑（19:10:55–19:36:02，watch.log），但 night 整集闸门要 3 镜首帧全过契约：
   只有 S2 首帧 09:29:29 passed；S1/S3 首帧 score_infra ×4（Q10 人数检测器 http://10.0.0.36:8893 不可用 → infra_error 不计次、反复重打分）→ 本集没就绪、0 派视频。
   阻塞点 = gpu36 :8893 anomaly 常驻 down（STATE 坏点 7③ 已记“down”，今天证实它直接卡首帧 Q10）。
C. OOM（#8）——**代码已上线两台（P4 手放），缩容真停服已验收；但 OOM 仍在**，新根因：gpu33 上两个 producer 抢审图卡——
   生产 producer（series10_v2，视频段）每拍 scale 1；`producer.py serve --run smoke_v2`（gpu33 pid 2020053，11-07 20:26 发版部署拉起的冒烟常驻）
   按冒烟 frames 段每拍 scale 3。证据：gpu33 data/pipeline/review_scale.json 与 :8877 进程父链（3317351 ← bash scale 3 ← 3317320 ← 2020053）；
   09:32–09:34 两边交替 scale 1 / scale 3。另：单实例 :8876 + 同卡 ep03 视频时 GPU3 23.5/24.5 GB，:8876 仍新 OOM（174/180 MiB）。
需要项目方：服务器上的冒烟常驻 producer（gpu33 2020053 / gpu36 2916932，非我起）停或改为不做 review_scale——见裁决清单。

**P4（项目方 11-08 指令第 2 件“发版或手放均可”）**：tools/vqa/review_instances.sh（cd85d3ec 版，sha256 231c629f…）手放 gpu33 / gpu36 发版部署目录，原文件 .bak_P4_1108（两台原 sha cea6eb9e… = 修前版）。
验收（真机，日志 gpu33 /root/work/fredw/vqa/logs/P4_accept_1108.log）：09:33:39 scale 1 → “ADOPT :8877 pid 3314870（无 pid 文件，按监听端口认回）”“stopped instance :8877 (pid 3314870)”，进程确认已退；
活着 2 > 目标 1 → “SCALE_EXCESS … rc=6”（修前同情形 rc 0）。:8877 随即被另一路 scale 3 重起（见 R5-C），不是停不掉。
| A13 | 2026-11-08 10:13–10:38 JST | #6 尾帧修复（95ddb0f9：冒烟 last_frame_mode = compose，与生产一致） | G4 尾帧 | 95ddb0f9 | **3/8**（G1/G2/G7） | 平 → 保留（G4 内部升：尾帧缺镜 3→1、OOM 不再报、视频链首次派单）→ R5 续 | eval/results/20261107-2013.json；窗口 scratchpad smoke_A13/：night 10:19:04 READY ep01 → DISPATCH gpu36 三道、vidgen 10:19:02 START；0 SUBMIT——逐镜 SOP 闸门：S1 首帧、S1/S2 尾帧 score_infra（Q10 :8893 不可用）没过契约；S3 尾帧窗口内没出 |

R5 续（A13 后，三层状态）：A 尾帧 ✅ 已修（preflight 不再挂；缺镜 3→1，剩 S3 = 首帧过得晚、窗口内没轮到）；B 视频 = 链路全通（night 判就绪→推 jobs→起 vidgen），唯一卡点 = :8893 down 使 Q10 打不了分（裁决 #9）；
C OOM = 本窗口 G4 未报（gpu33 视频段已空，审图卡未被挤）；冒烟常驻 producer 抢 scale 的根因仍在（裁决 #8 新）。另 G3 新出现：S1 首帧引用上一窗口的版本文件（G7 清掉后文件不存在）——登记坏点，不动手。
时间账：本窗口尾帧最早 10:30 出、打分卡在 :8893；视频单段 ~420 s，冒烟要在 25 分钟内过 G4，首尾帧需在窗口前 15 分钟内过契约。

| A14 | 2026-11-08 17:34–17:59 JST | #8 停冒烟常驻 producer + #9 笔记本 Q10 隧道（908f9cca） | G4 | 85f96a1f | **2/8**（G1/G2） | 降 → 不回滚（#9 生效：Q10 0 score_infra、S1/S2 首帧过；G7 降为本轮窗口看守 night 在 smoke_v2 写视频状态文件所致；G4“OOM”命中的是 review_scale 回显里路由器旧 last_error，疑误报未核） |

R5 终（A14 后三层）：尾帧 = 链路通、内容重做耗窗口（S1 尾帧 FL→G1→第 3 次）；视频 = 网络已通、night 17:52 派单，但 smoke_v2 视频作业全 needs_writer（SHOT_BLOCKED_NO_VARIANT）；OOM = 无新 OOM，回显旧错误疑误报。

**P5（项目方 11-08 “开工”批准）：冻结令解除，旧架构封存，转新架构重构。** 依据 ns-refactor-plan.md（项目方下达）+ PS-MASTER 五点修正：①API + queue.db 放 gpu33（笔记本下关键路径）；②出图 / 视频分区分开（images 1,3→gpu33 / 2,4→gpu36；video 1,2,4→gpu36 / 3→gpu33）；③data/ 在笔记本（55 takes.json），M0 即核；④QC 不过只挡本镜下一步、不反压派单；⑤gpu33 GPU3 专给审图。§6 六项按计划推荐。线 3 冒烟停在 A14；生产照跑至 M1。旧仓库 tag archive/ns-final-20261108-85f96a1f；新仓库 ns-studio-v2。
