# V2_WALK_AUDIT：V2 剧本按网页流程走一遍，顺带审计整套系统（V2-WALK，总调度 fredw-2b 派，11-02 19:2x 起）

项目方原话（11-02 19:2x）：“master agent，整个过程 audit 全套系统，同时在网页也是一步步去展示，先从‘新建剧本’开始，目的是验证全部流程在这个 v2 剧本。”
项目方 19:3x：一边验证一边 debug，目标是做成能和小云雀比的系统。所以每一步都要回答两件事：项目方能不能在网页上自己完成这一步；体验比小云雀差在哪。

截图目录：data/review_pages/v2_live/walk/
根因模式（记忆 root-cause-patterns）：①一个东西两个入口 ②两台服务器各自编译 ③不送参考 ④种子不确定 ⑤没过的图给项目方看 ⑥同步阻塞、拒收 ⑦规则写了没生效 ⑧改分区不看数据在哪。另外加三类走查标签：〔V1〕读到 V1 内容，〔显示〕界面显示不对，〔技术词〕界面上出现技术词。

---

## 一、“新建剧本”这条链路（实测，11-02 19:3x）

网页上有**两条互不相通的链路**，都在 #/script-create?new=1 这一页。

### A. 下方表单“开始自动写作”（旧链路，UIRSI）
| 网页上点 | 调的接口 | 产物写到哪 | 写作后端 |
|---|---|---|---|
| 填剧名、提纲、集数、秒数、预算、“写到哪一步”，点“开始自动写作” | POST /api/story-runs（services/api/ns_api/story_runs.py start_run） | **新建** data/pipeline/runs/ui_<时间>_epNN/：P0_brief.json、ui_state.json，以及 P1–P4 正式文件和 .report.json | 后台线程 _worker 调 tools/pipeline/run_chain.run，再走 llm_config.resolve("script_write")，也就是**外部写作 API**（abliteration），**不看 writer_backend** |
| 左侧列表点某个剧 | GET /api/story-runs/{id} | 读同一目录 | — |
| 某段“看内容 / 原文 / 改” | GET / PUT /api/story-runs/{id}/artifact/{P0..P4} | 改原文后重新校验，下游挪到 superseded/ | — |
| 返修 / 继续 | POST …/retry、…/resume | 同上 | 外部 API |
| “送去导入（你确认）” | POST …/send-to-import | data/staging_input 草稿，再到 ② 导入页（ImportView），由项目方勾选导入 | — |

### B. 上方“全流程自动”面板（新链路，HOLLYWOOD，L-109 测试期用的就是这条）
| 网页上点 | 调的接口 | 产物写到哪 | 写作后端 |
|---|---|---|---|
| 右上“剧目”下拉选 series10_v2 | GET /api/story-runs?limit=60 → 对每个剧调 GET /api/script-autoflow/{id} | 读 data/pipeline/runs/series10_v2/autoflow.json、autoflow_epNN.json | — |
| （缺）填 / 导入 Brief | HOLLYWOOD 新增 POST /api/script-autoflow/{run}/brief（**API 未重启，未生效**；前端没有入口） | P0_brief.json，CLEAN_CUT.json | — |
| （网页没有 start 按钮，只有“一键返修”） | POST /api/script-autoflow/{run}/repair（start 也是这个），起子进程 tools/script_rsi/autoflow.py run | 状态写 autoflow*.json | writer_backend=claude_agent：tools/script_rsi/autoflow_agent.py 出写作包 |
| 写作包怎么发 | — | <run>/writer_tasks/<step>_a<k>.json（nsfs.writer_task/1，带 system / user / inputs / output / content_rules；V2 带 CLEAN_CUT，写作包里旧剧的词会被换掉） | SCRIPTWRITER（Fable）读写作包 |
| 稿子怎么回 | — | 写手写 <run>/writer_out/<step>_a<k>.json，再建 .done；下一次 run 时 run_chain.validate 校验，过了落正式文件（P1_storyline.json，造型表落 P1_looks.json），没过就出返修包 a<k+1> | — |
| P1 审阅闸（HOLLYWOOD 新增） | POST /api/script-autoflow/{run}/gate {key:"P1"/"epNN", action:"approve"/"revise", note}（**API 未重启，未生效**；前端没有按钮） | <run>/owner_gates.json | — |
| 看写作包和回稿（HOLLYWOOD 新增） | GET /api/script-autoflow/{run}/tasks、…/tasks/{包名}（**live 接口实测 404**） | — | — |
| P4 之后：事实表 → 代码判定加补丁 → FACTCHECK → 打分（测试期只用代码判定）→ rubric 闸门 → 导入闸门 | autoflow_agent.post_step；reviewer 包 facts_epNN / factcheck_epNN_K，writer 包 patch_epNN_K | — | reviewer 包由评审 agent 做 |
| “一键导入” | POST /api/script-autoflow/{run}/import（live + --owner-ok） | 导入 V2 run（L-098 一次点选） | — |

**结论**：V2 现在实际走的是 B，而且到目前为止全部是 HOLLYWOOD 在**命令行**跑 autoflow.py（HOLLYWOOD 19:3x 确认），网页只是旁观。A 是网页上最显眼的“开始自动写作”按钮，但它写不进 series10_v2，还会花外部 API 的钱。

---

## 二、审计发现（按影响排序；状态：待派 / 已修 / 修复中）

| # | 步骤 | 发现 | 根因模式 | 处理 | 状态 |
|---|---|---|---|---|---|
| W-01 | 新建剧本 | 网页上有两条写作链路：表单 A（/api/story-runs → 外部 API → ui_* 目录）和面板 B（/api/script-autoflow → claude_agent → 指定剧目录），状态、产物、按钮互不相通 | ①双入口 | 合并成一条：表单提交后写进选中剧的 P0（B 的 /brief），推进只走 B；A 下线，或改成调 B | **待派**（建议 UISCRIPT + HOLLYWOOD） |
| W-02 | 新建剧本 | 表单 A 的“开始自动写作”**无视 writer_backend=claude_agent**（story_runs._worker → run_chain → script_write 外部 API）。测试期一点就花钱，违反 L-109 | ⑦规则写了没生效 | _worker 开头读 autoflow_agent.backend()：是 claude_agent 就拒绝，或转到 B。在修好之前，网页上不要点这个按钮 | **已修 · FACTORY（19:2x）**：claude_agent 时不再起外部 API 线程，改成在 ui_* 目录放 writer_package.json，显示“等写作 agent”。**新问题**：这是第三种写作包格式（nsfs.writer_package/1），和 autoflow 的 nsfs.writer_task/1 不是一套，写手不会去 ui_* 目录收包，等于空转，要并进 W-01 |
| W-03 | 新建剧本 | 表单没有“选剧目”，写不进 series10_v2：P0 是 HOLLYWOOD 用脚本汇编写入的（剧名为空），列表上标着“命令行 / 未命名剧本” | ①双入口；〔显示〕 | HOLLYWOOD 缺口 5 已加 POST /brief；前端要接（选剧目 → 填或导入 Brief） | 修复中 · HOLLYWOOD（后端）/ 前端待 UISCRIPT |
| W-04 | P1 | P1 19:16 交稿，19:17 自动发出 P2_ep01_a1 写作包，没有停下来等项目方（P1 审阅闸缺失） | ⑦规则写了没生效（“P1 交项目方看”只写在文档里） | HOLLYWOOD 缺口 1：owner_gate.py + /gate；现在停在 awaiting_owner_p1，P2 标 held_by_p1_gate，包留着没人接 | 修复中 · HOLLYWOOD（代码已落盘，**API 没重启，网页没有按钮**） |
| W-05 | P1 | 网页上**看不到 P1 故事线原文**：面板 B 只显示状态，没有“看内容”；运行详情页（#/script-create?run=series10_v2）只显示 P0，因为 story_runs._episode_of 对 autoflow 跑的剧推不出集号 | ①双入口；〔显示〕 | **已修代码**：_episode_of 按 autoflow.json 补集号（services/api/ns_api/story_runs.py），本地调用实测 P1=ok 能显示；**要重启 :8800 才生效** | 已修 · 19:25 重启后已生效（截图 w07） |
| W-06 | 新建剧本 | “全流程自动”面板的剧目下拉**写死默认第二季 series10_s2**（已暂停），不是 primary | ①双入口（默认值和 runs.json 各存一份） | **已修**：AutoflowPanel 默认取 /api/script-library 的 primary（apps/web/src/v3/pages/AutoflowPanel.tsx），vite 热更新后截图 w06 确认默认就是 series10_v2 | 已修 |
| W-07 | 全页 | 技术词直接显示：awaiting_writer / awaiting_reviewer / awaiting_owner_p1 / held_by_p1_gate / needs_patch / reopened / Brief / “分数 undefined” / patch_ep07 / p4#QW-W14 / “第二季导入目标待 WORKFLOW / PRODUCER 接 --run” / series10_v2 / “命令行” | 〔技术词〕 | 状态词表统一翻成中文三态（等写手 / 等你看 / 通过），规则编号收进“详情” | **待派**（UISCRIPT / NAVIA） |
| W-08 | P1 | 面板写“写作模型”判定，实际是 claude_agent 写手；autoflow 的 P1 stage 记的是 decider=api_model | 〔显示〕 | decider 按 writer_backend 写 agent | 待派（HOLLYWOOD，小） |
| W-09 | 剧本库 | V2 卡片的标题曾显示 series10_v2（P1 回来前剧名为空），状态显示“写作中 0/10”，实际在等写手 / 等项目方；19:17 后显示剧名“透明高跟” | 〔显示〕 | 剧名为空时显示“新剧（未定名）”；状态读 autoflow verdict | 待派（UISCRIPT） |
| W-10 | 剧本库 | “写作流水线”里第二季（已暂停）的 7 行压在 V2 的 1 行上面，行首 S1 / S2 是季号还是阶段号看不出来 | 〔显示〕 | 已暂停的剧折叠起来；行首写剧名 | 待派（NAVIA） |
| W-11 | P1 造型表 | hollywood._json_block 只认 {…} 对象，造型表是列表，被误判“不是 JSON”，多出了一个返修包（已挪到 writer_tasks_void/） | ⑦校验器和产物格式不一致 | HOLLYWOOD 已修 | 已修 · HOLLYWOOD |
| W-12 | 后台 | :8800 API 有两个 uvicorn 进程同时挂着（.venv 一个、系统 Python 一个）；v2_live.py 也是两个进程（venv 一个、系统 Python 一个） | ①双入口（同一服务两份进程，代码版本可能不同） | **误报，撤销**：FACTORY 核实 .venv\Scripts\python.exe 在 Windows 上是转发器，会拉起系统 Python 子进程，两者是父子关系，端口上只有一份 API。restart_api.ps1 已加守卫（端口没空出来就不起新进程） | 撤销 |
| W-13 | 测试 | tests/test_story_runs_uirsi.py 有 2 个失败（test_story_images_grouped 等）：FACTORY 的 K-OPS-F24 把 story_images 的默认剧改成 current_run，测试没跟着改；和 W-05 的改动无关 | ⑦规则改了测试没跟 | 改测试 | 待派（FACTORY） |
| W-15 | P0（今天更早） | autoflow test-brief 覆盖了 V2 的 Brief，并且调了 1 次外部写作 API（data/pipeline/runs/series10_v2/test_brief_usage.json） | ⑦规则写了没生效（L-109） | HOLLYWOOD 加了两道闸：已有 Brief 不覆盖；claude_agent 后端默认不调外部 API（tests/test_autoflow.py） | 已修 · HOLLYWOOD |
| W-16 | 切割检查 | v1_leak 放行表里混进了空串，所有命中被打散，有问题的稿可能被报成 0 命中 | ⑦检查器失效但不报错 | HOLLYWOOD 已修并补了测试；建议 VQAGATE 复核切割检查有没有 fail-open | 已修 · HOLLYWOOD |
| W-17 | P1 闸门 | 闸门上线前已经发出的 P2 包，状态会显示成“在等写手” | 〔显示〕 | p1_gate 把闸门之后的段标成 held_by_p1_gate（这个词也要翻成中文，见 W-07） | 已修 · HOLLYWOOD |
| W-18 | P1 三评委 | judge_agent.py p1-collect 把结果写到 judge_p1/RESULT.json，**网页上没有任何地方读它**（services/api、apps/web 都搜不到），项目方和总调度只能看文件 | 〔显示〕；⑦规则写了没生效 | GET /api/script-autoflow/{run} 带出 P1 评审结果（各家总分、均分、逐条分歧、top_fixes），面板 P1 节点显示“评审 均分 x/40” | 修复中 · HOLLYWOOD（接口）/ UISCRIPT（显示） |
| W-19 | P1 闸门 | 总调度的门槛“三评委平均 ≥ 34/40 才交项目方，不到就返修”**没有写进代码**：owner_gate 和 p1_gate 不读 RESULT.json，P1 一收下就开项目方闸门；同一个评审交多份（judge_id 相同）也不会拦 | ⑦规则写了没生效 | p1_gate 先读 RESULT.json：stable、三个不同的 judge_id、均分 ≥ 34，才开项目方闸门；不到门槛就按 top_fixes 出 P1 返修包（返修有上限，超过上限转总调度）；门槛放配置文件 | 修复中 · HOLLYWOOD |
| W-20 | P1 三评委 | 三家 19:22–19:24 交齐，之后**没有任何东西自动跑 p1-collect**。V2-WALK 19:2x 手动跑了一次，结果三家 28 / 28 / 26，均分 27.33/40，σ 0.94，结果稳定、三个评审各不相同 | 需要人工绕过（人工接力） | autoflow 看到三家的 .done 都在，就自动 collect，再按门槛分流（并进 W-19） | 待派（HOLLYWOOD） |
| W-21 | P1 闸门 | 均分 27.33 **低于 34 的门槛**，但状态仍是 awaiting_owner_p1：如果 UISCRIPT 的按钮现在上线，项目方会看到一份没过门槛的稿（W-19 实证） | ⑤没过的东西给项目方看；⑦ | 门槛进代码之前，P1 先不要交项目方；HOLLYWOOD 按评审意见出返修 | 已修 · HOLLYWOOD（19:3x；门槛在 config/prompts/hollywood_p1_review.yaml，最多 3 轮；实测 verdict 已变成 awaiting_writer，不再摆给项目方） |
| W-22 | P1 详情页 | 运行详情页的 P1 有“让模型改… / 改原文 / 返修这一段”（story-runs 的 retry / PUT），和 HOLLYWOOD 的 /gate revise 是两套返修入口；详情页没有“用这版”，也不显示造型表 P1_looks 和评审分；页头剧名仍是“未命名剧本 · 命令行”，没读 P1 定的剧名 | ①双入口；〔显示〕〔技术词〕 | 并进 W-01：返修只走 /gate；P1 页显示造型表和评审分；剧名读 P1 | 已转 UISCRIPT（19:4x） |
| W-23 | P1 → P2 | 19:17:06 发出 P2_ep01_a1 的，**不是网页，也不是 HOLLYWOOD 或写手**，是 autopilot 守护：tools/autopilot/flow.py 的 autoflow_tick 看到写作包的 .done 已存在，就执行包里的 advance_cmd。证据：data/autopilot/flow/autoflow_tick.json 记着 "series10_v2/ep01": "P1_a1.json@1793614617"（=19:16:57，写手建 .done 后 1 秒）。推进链条的入口有三个（网页 /repair、命令行、守护），之前查不到是谁推的 | ①双入口 | 只留一个推进入口：守护也走 /repair 的同一套逻辑，autoflow.log 记 source=cli/web/daemon、pid（HOLLYWOOD 已加日志、去掉 advance_cmd，要确认守护还能不能推进） | 代码已修 · HOLLYWOOD（autoflow_tick 改成只报告；推进只走 autoflow.py，由网页 /repair 或 FACTORY 常驻服务调用；跨进程锁 advance.lock；autoflow.log 记来源）。**还剩一步**：resident_sync 内存里可能还是旧代码，FACTORY 重启后才算真正只有一个入口 |
| W-25 | P1 闸门 | **/gate 的 approve 不校验评审门槛**：owner_gate.act 直接写 approved，p1_approved() 随即放行 P2–P4 写作包；UISCRIPT 新面板在 verdict=awaiting_writer、第 2 稿还没评审时就显示“用这版”（w08）。点一下就绕过了 34 分门槛 | ⑤没过的东西给项目方看；⑦规则写了没生效（门槛只在分流里，闸门入口没挡） | 后端：approve 只在 p1_review.latest.passed 为真且评审 sha 等于当前稿 sha 时收，否则回 409 并说明原因（“修改”照收）；前端：只在 awaiting_owner_p1 时显示按钮 | 后端已关闭（总调度 19:4x 线上实测两次回 409，原因写明“第 2 轮 31.67/40……返修第 3 稿”；V2-WALK 在副本上调函数也被挡下）；前端：第 2 轮 w09 已验，第 3 轮已验（w11 / w12：面板和详情页都看不到正文，没有“看内容 / 原文 / 用这版”） |
| W-26 | 新建剧本 | 剧目下拉出现两个“新剧（未定名）”，其中一个是 UISCRIPT 的演示 run zz_uiscript_demo，它在正式目录 data/pipeline/runs/ 里；series10_v2 在下拉、左侧、页头都显示“新剧（未定名）”，没读 P1 定的剧名《透明高跟》（剧本库能读到） | ①双入口（剧名两个来源）；〔显示〕 | 演示 run 移出正式目录或在列表里过滤；剧名统一读 P1_storyline.title | 修复中 · UISCRIPT |
| W-24 | P1 评审 | judge_p1/STATE.json 第 1 轮 packed_at="19:5x"、extra_by="总调度 20:xx"，文件实际是 19:25 写的：时间戳是占位，或是编出来的 | 〔显示〕；数据可信度 | 记真实时间 | 已修 · HOLLYWOOD（STATE 里的 packed_at 已是真实时间 19:20:28 / 19:35:08 / 19:53:09） |
| W-27 | 工具 | 截图探针 probe_shot.mjs 写死了 9688 端口，几个 agent 同时截图就会连到别人的 Chrome，卡死（19:4x 实测卡了 4 分钟以上，残留多个 9688 Chrome） | ①一个资源两个使用方 | **已修**：PROBE_PORT 可以指定端口，没给就随机取 9700–9899 | 已修 · V2-WALK |
| W-28 | 各集进度 | P1 还在返修，“各集进度”tab 却把第 1–10 集都标成“写作中”；状态行只写“等写手交稿”，看不出这是第 3 稿、最后一轮（next_action 里有“返修中（第 2 轮，评审 31.67/40）”） | 〔显示〕 | 没开写的集显示“未开始”；状态行写明“返修第 3 稿（最后一轮）· 上轮 31.67/40” | 已转 UISCRIPT（总调度） |
| W-29 | P1 评审中 | 第 3 稿（P1_a3）、第 3 轮评审（r3 还没出分）时：面板写“第 4 稿在评审”，详情页写“第 4 轮”，轮次和稿次都多了一；详情页显示“第 3 轮均分 null”；P1 节点挂着绿色的“通过”，页头写“写手在写”，实际是评委在评 | 〔显示〕〔技术词〕 | 轮次和稿次直接取 STATE.rounds 和 attempt；没出分写“评审中（x/3 已交）”；评审中不挂“通过” | 修复中 · UISCRIPT |
| W-14 | P0 | 推进全部是命令行（HOLLYWOOD 19:10 / 19:17 / 19:2x 跑 autoflow.py run），网页的 start / repair 一次都没用过 | 需要人工绕过 | 之后改由网页 /repair 推进，V2-WALK 实测 | 进行中 |

已知缺口（总调度 19:3x 转来，HOLLYWOOD 负责，代码已落盘，tests/test_owner_gate.py 20 个测试全过，**等 API 重启和前端接入**）：
1. P1 审阅闸（网页“用这版 / 修改”）：POST /api/script-autoflow/{run}/gate，修复中 · HOLLYWOOD，前端待 UISCRIPT / NAVIA；
2. 网页看写作包和产物：GET …/tasks、…/tasks/{包名}，修复中 · HOLLYWOOD，live 实测 404，等重启；
3. 造型表进链：_looks_step 收稿后写 P1_looks.json，网页 stage 名 P1L，已在面板上显示“造型表 · 复用”，修复中 · HOLLYWOOD；
4. 新建剧本页能填或导入 Brief：POST …/brief，修复中 · HOLLYWOOD，前端没有入口；
5. /import 认 imported：修复中 · HOLLYWOOD。

---

## 三、体验差距（对照小云雀；按影响排序）

参考：docs/canvas_research_v3.md §1.1、docs/xyq_flow_full.md（小云雀实测）、docs/ep02_iter/competitor_flows.md。小云雀官方教程：https://www.xiaoyunque.com/tutorials/short-drama-remake 、https://www.xiaoyunque.com/tutorials/web-manual 、https://www.xiaoyunque.com/tutorials/short-drama-agent-smart-preview

| # | 这一步 | 项目方能不能在网页上自己完成 | 和小云雀差在哪 |
|---|---|---|---|
| X-01 | 新建剧本（选剧、填方向） | **不能**。表单写不进 series10_v2，而且点了会走外部 API；V2 的 P0 是 agent 用命令行写的 | 小云雀进项目后就是一条步骤 tab（剧本 → 资产 → 分镜），剧本贴进去或上传后点一次“剧本分析”，**提交前显示积分**（5 积分 / 100 字）。我们这一页有两套入口、两套状态，预算按美元填，但实际后端不花钱 |
| X-02 | 看故事线（P1） | **不能**。面板只有状态，没有正文；详情页要等 API 重启 | 小云雀的剧本概要和分析结果就放在项目页里，直接可看可改 |
| X-03 | 用这版 / 修改（P1 闸门） | **不能**。后端已有，网页没有按钮 | 小云雀的结果卡右上角固定两个按钮：“修改诉求”和“重新生成”。我们应该同样只放“用这版 / 修改”两个（L-123） |
| X-04 | 看进度 | 勉强能看，但看到的是英文状态词和规则编号 | 小云雀每集只有三态（未解析 / 解析中 / 解析完成），失败的集可以一键重试；分集是网格，没完成的集只显示下一步按钮 |
| X-05 | 推进下一段 | 只有“一键返修”，没有“开始 / 继续” | 小云雀没完成的集只显示一个主按钮（“生成脚本”） |

---

## 四、走查日志（最新在上）
- 19:5x HOLLYWOOD 交接：推进改由 FACTORY 常驻服务（source=daemon）负责；19:54 HOLLYWOOD 又从网页 /repair 多推了一次（有锁，没有副作用）。有 1 个写作链测试没能复现的失败，交 OVERSIGHT-F 留意。
- 19:5x 第 3 稿交了，第 3 轮评审包 19:53:09 发出。前端实测：评审中看不到正文，没有按钮（W-25 / W-22 前端通过）；剧名统一成《透明高跟》（W-26 通过）；各集显示“未开始”（W-28 通过）。新发现 W-29：轮次多了一、显示 null、评审中挂着“通过”。
- 19:4x 第 2 轮评审 33 / 31 / 31，均分 31.67，没过。19:38:47 第 3 家交齐，守护 19:42:23 自动汇总，自动出第 3 稿返修包（W-20 自动汇总已实测生效，延迟约 3.5 分钟）。评审分 tab（w10）显示两轮的分数和逐条均分，和 RESULT.json 一致。面板在没过门槛时不显示“用这版 / 修改”（w09，W-25 前端已实测）。W-25 后端：在 series10_v2 的副本上调 owner_gate.act(approve) 被挡下，提示“第 2 轮评审均分 31.67/40，没到门槛，正在返修第 3 稿；新稿评审过了门槛才能用这版”，“修改”照常收下；对线上接口 POST /gate 的实测被权限系统拒绝（会改共享状态），没有绕过，等授权。
- 19:3x 写手交 P1 第 2 稿（19:33:36），守护 19:33:37 推进（autoflow.log 记 source=daemon），故事线换了版本，所以先重出造型表包 P1_looks_a2，第 2 轮评审包还没出。UISCRIPT 新面板已上（w08：中文状态、四个 tab），但没评审就显示“用这版”（W-25，P0）。查清 19:17 的 P2 包是 autopilot 守护推的（W-23）。
- 19:4x HOLLYWOOD 修完 W-18 到 W-21：三家交齐后自动汇总、按门槛分流、新稿回来自动出下一轮评审包。实测 live 状态 = awaiting_writer（等写手交第 2 稿），P1_a2 返修包是走网页 /repair 出的（第一次没用命令行）。p1_review 字段要等 API 再重启才能在网页上看到；字段说明已转 UISCRIPT。
- 19:4x 总调度定：返修最多 3 轮；W-18 / 19 / 20 / 21 交 HOLLYWOOD；W-22 和 writer_package 空转交 UISCRIPT（已发）。等返修稿。
- 19:3x API 重启（FACTORY 19:25）后，故事线在详情页能看了（w07：#/script-create?run=series10_v2 → P1 → 看内容，有人物表、场景表）。/tasks 接口 200。三评委交齐，手动 collect 得均分 27.33/40，没过 34 的门槛，P1 不交项目方，转返修。
- 19:3x 新建剧本：链路摸清（第一节）；截图 w01 剧本库、w02 新建页（默认选错成第二季）、w03 切到 V2 的面板、w04 V2 运行详情（只显示 P0）、w05 详情页上没有 P1、w06 修好默认值后面板停在“等项目方看 P1”。当场修了 W-05、W-06；P2 包由 HOLLYWOOD 的闸门挡住，没人接。
