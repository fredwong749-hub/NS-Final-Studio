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
