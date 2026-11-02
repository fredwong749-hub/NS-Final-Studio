# SCORECARD：六项都要到 100 分（总调度 fredw-2b，11-02 17:4x）

项目方原话（11-02 17:4x）：“我希望你达到 100 分，无论是 UI、剧本、工作流（workflow）、rendering 还是 GPU 管理、代码，全都要达到 100 分。没有达到 100 分，自动开始迭代。”

**规则**
- 每项的分数由代码按下列指标自动计算，SENTINEL 每 20 分钟写入 data/rsi/scores.jsonl，并画进 8810 看板。
- 不到 100 分，负责方自动开下一轮。总调度每轮亲审：分数的出处、截图和样张。
- 任何一项不许靠改口径涨分。指标改动要总调度批准，并在本文件留痕。
- 对齐基准：docs/master/ALIGNMENT.md（出图到视频的 9 步）；待办明细：docs/master/TODO_BOARD.md。

| 项 | 现分（出处，时间） | 100 分的标准（全部满足） | 负责 | 下一轮 |
|---|---|---|---|---|
| 1 出图 rendering | 68.1（scores.jsonl image，03:56，已过时） | ALIGNMENT 9 步全部落地；第 8 步自动验收（身份 / 服装 / 提示词 / 人数手数）作为闸门；第一季 102 镜首尾帧全部通过验收；项目方再提同类反馈（陌生人、串装、多手、站位）为 0；两台同一镜提示词 sha 一致 | PROMPTFIX + VQAGATE + DETECT-S | sv-14 上线后重算；按集顺序补图 |
| 2 视频 | 72.5（scores.jsonl video，时间缺失） | 102 镜视频全部定稿；每集整集预览自动生成；成片剪辑器可裁切、换 BGM、导出定稿；10 集成片 10/10 | DEBUG-RSI + ASSEMBLY + CUTEDIT | ep01 → ep10 按 L-124 顺序推进 |
| 3 剧本 | 93.1（scores.jsonl script，14:44） | 第二季 10 集过 v3 + 场景定稿行 + K-WRT-211 / 212 + FACTCHECK；盲评 v3 全胜；lint QW-W13 / W14 命中为 0；automation 分项满分 | HOLLYWOOD + SCRIPTWRITER | lint 命中改写；ep06–10 收尾 |
| 4 UI | 待算（线 4 指标见 RSI_PROGRAM） | 顶栏 7 个一级入口一键可达；每页全剧视角、没有空白页；页面之间深链接顺畅；只有“用这张”+“修改”；提交类操作 300 ms 内收下，原位显示状态加全局队列；只显示通过验收的图；界面不出现技术词；1280 宽度不挤；项目方 UI 反馈清零 | NAVIA + ASSETUX + UISCRIPT + POSTER | NAVIA 顶栏三轮自迭代；ASSETUX 编辑器重做 |
| 5 工作流 workflow | 待算（新） | 主线按集顺序无人值守推进：出图 → 验收 → 尾帧 → 视频 → 整集预览；项目方的修改自动入队、自动改写、自动重出；每集完成自动回报；第二季暂停状态只认一个来源；硬上限、去重、不重复出 | DEBUG-RSI + FACTORY | sv-14 护栏；E30 排序落地 |
| 6 GPU 管理 | 待算（新） | 出图卡空转率低（按 gpu_24h 的真实运行 / 空转 / 等待算）；没有因分区错误或旁路导致的重复出图；部署停派 ≤ 2 分钟；命令通道两台成功率 ≥ 0.99；常驻服务（CLIP / VQA）不反复重启；借道到期自动收回 | FACTORY + NETFIX + SENTINEL | gpu33 命令超时根治；分区唯一来源 |
| 7 代码 | 56.8（scores.jsonl system，13:31） | arch_scan 0 退化；同一事实只有一个来源（根因模式第 1 条全清）；服务器代码 = sv 版本（漂移探针 0）；测试全绿；AUDIT-M 问题清单 A-01…A-14 全部关闭；no_claude / self_run 分项达标 | AUDIT-M + FACTORY + 各负责方 | sv-14；A-01…A-10 逐条关 |

注：项目方点名六项，“出图”和“视频”拆开写，所以表里一共 7 行。

## 附录 A：自动计分公式与口径（SENTINEL，tools/sentinel/scorecard.py；规则 K-OPS-S17）

- 每 20 分钟由 SENTINEL 计算七项，每项一行写进 data/rsi/scores.jsonl（by = "SENTINEL scorecard"，带 parts / lowest / unmeasured / evidence / sv），8810 看板“RSI 分数”区与晚报 data/review_pages/rsi/index.html 画轨迹。
- 不到 100 分 → SENTINEL 开 SC 工单派下表负责方并抄送总调度，工单写最低分项和证据。
- 权重与线只在 config/policies/sentinel.yaml SC_scorecard；改动要总调度批准并在本附录留痕。**不许靠改口径涨分。**
- 新三项（UI / 工作流 / GPU）：分项 0–1，未测按 0 计入（不能当满分）；本表“100 分标准”里还不能代码测的条目列为 unmeasured，存在时总分封顶 95。

| 项 | 公式（沿用 = RSI_PROGRAM 现有打分器重算） | 数据源 |
|---|---|---|
| 出图 | 沿用线 1：identity 25 + hands 15 + pose 15 + light 20 + gaze 10 + pass_speed 15（light 未接时按打分器规定不进分母，partial） | tools/imglab/score.py（takes.json postflight，近 24 h） |
| 视频 | 沿用线 2：cam 20 + act 25 + lip 15 + cons 20 + stab 10 + film 10 | tools/vidlab/score.py score（clipmetrics + 好莱坞参照锚点） |
| 剧本 | 沿用线 3：script 35 + shot_block 20 + shootable 20 + structure 15 + automation 10（第二季） | tools/script_rsi/line3_score.py --run-dir data/pipeline/runs/series10_s2 |
| 代码 | 沿用线 5：no_claude 30 + self_run 20 + release 15 + structure 20 + rule_coverage 15 | tools/rsi/system_score.py |
| UI | topbar 25 = topbar_check 通过的（页 × 宽度）/ 21；no_blank 20 = 7 个一级页面里非空白页占比；clean 20 = 无彩色胶囊 / 无口径矛盾 / 无裂图的页面占比（S9 同一套 DOM 规则）；no_jargon 15 = 页面文字不含技术词（词表 SC_scorecard.ui_jargon_words）的页面占比；feedback 20 = max(0, 1 − 未关闭 UI 反馈单 / 5) | apps/web/e2e/uirsi/topbar_check.mjs、probe.mjs（只读）、data/feedback/items（category 以 ui 开头、状态不在 closed / done / verified / deferred）；界面实测每小时一次（后台），超过 90 分钟的实测不用 |
| UI 顶栏口径 v2（留痕：总调度 11-02 18:0x 批） | topbar = 通过的检查 / 25：7 个页面 × 3 宽度（1280 / 1440 / 1920）各查一次——顶栏 7 个一级入口（总览 / 剧本 / 资产 / 分镜 / 出图 / 视频 / 成片）都在、可点、互不重叠、页面无横向滚动（21 次）；出图 / 视频 / 成片 / 分镜四页范围条里有换集下拉（4 次）。改动原因：NAVIA 按项目方要求把换集下拉从顶栏移到页内范围条（有意的改版），旧口径（顶栏要有“第 N 集 ▾”）已过时；这次改口径是为了反映已批准的新设计，不是为了涨分 | SENTINEL 自己的检查（tools/sentinel/scorecard.py TOPBAR_JS，经 apps/web/e2e/uirsi/probe.mjs 只读执行）；UIRSI 的 topbar_check.mjs 另行由 UIRSI 按新设计更新 |
| UI 未测 | 页面之间深链接顺畅；只有“用这张”+“修改”；提交类操作 300 ms 内收下 + 全局队列；只显示通过验收的图 | — |
| 工作流 | unattended 35 = 1 − 等人决定的对象 / 在途对象（S13 + 登记表 pending / ready / running）；no_stuck 25 = 1 − S11 卡段工单 / 集数；no_dup 25 = max(0, 1 − S17 无限重出工单 / 5)；auto_requeue 15 = 1 − 建单超过 30 分钟仍是 new 的反馈单 / 反馈单总数 | data/sentinel/state.json、data/producer/registry.json、data/autopilot/flow/status.json、data/feedback/items |
| 工作流未测 | 每集完成自动回报；第二季暂停状态只认一个来源 | — |
| GPU 管理 | productive 40 = min(1, gpu_24h 真实运行占已知时段 / 80%)；rssh 20 = min(1, 近 24 h SENTINEL 合并调用成功率 / 0.99)（样本 < 10 记未测）；deploy_stop 15 = 部署 / 重启类暂停最长一段 ≤ 120 s 记 1，否则 120 / 最长；resident 15 = S25 常驻 CLIP 无未关工单记 1；lend_expiry 10 = S18 临时挂道无过期工单记 1 | data/rsi/gpu_24h.json（含 pause_segments）、data/sentinel/state.json mem.remote_calls、S25 / S18 工单 |
| GPU 未测 | 没有因分区错误或旁路导致的重复出图（分区唯一来源落地后接 S17 按分区拆） | — |

**口径变更留痕（总调度 11-02 20:10 批）**：七项改按主 run（series10_v2）计分，V1 已归档不再计分。出图只算 V2 的版本、视频只算 V2 的片，V2 还没到该段时写 pending_stage（不出分、不开单、不进轨迹）；剧本按 series10_v2 跑线 3；工作流的 no_stuck 换成 review_chain（P1 评审交齐后 5 分钟内自动汇总，S27），unattended 改看写作推进常驻服务心跳（S26）+ 主 run 等人决定；GPU 的 productive 按“当前阶段应有占用”算（S1 写剧本 0、S2 资产 0.3、S3 出图 0.8、S4 视频 0.8、S5 成片 0.5；应有占用为 0 时不扣分）。

负责方（工单派给谁，抄送总调度）：出图 PROMPTFIX / VQAGATE / DETECT-S；视频 DEBUG-RSI / ASSEMBLY / CUTEDIT；剧本 HOLLYWOOD / SCRIPTWRITER；UI NAVIA / ASSETUX / UISCRIPT / POSTER；工作流 DEBUG-RSI / FACTORY；GPU 管理 FACTORY / NETFIX / SENTINEL；代码 AUDIT-M / FACTORY。

**剧本线 S1 阶段分（总调度 11-02 20:3x 批）**：主 run 还没有分集稿时，剧本线 = P1 故事线最新一轮三评委均分 ÷ 满分 × 100，记录注明“P1 阶段分”（现 32/40 = 80，judge_p1/r4/RESULT.json 20:17）；有分集稿后自动切回线 3。S27 评审汇总探针扫描 judge_p1/ 下所有 rN 轮次目录。

**权重变更留痕（总调度 11-02 20:4x 批）**：新增 S28“Q10 人数检测服务”（从 gpu33 测 10.0.0.36:8893/health 且 loaded=true，连续 2 次失败开单），计入两项——工作流 unattended 35→30、no_dup 25→20、新增 q10_detector 10；GPU 管理 productive 40→35、resident 15→10、新增 q10_detector 10（S28 无未关工单记 1）。

## 附录 B：代码线 structure 扣分前 5（SENTINEL 自动生成，口径 = tools/rsi/system_score.py STRUCT_ANCHOR 的 10 项，取自 data/sysarch/scan_latest.json 20:16:09；实时数据见 scores.jsonl system 记录 evidence.structure_top）

structure 现值 888（首扫锚点 1266），分项 31.0。按文件：

| # | 文件 | 扣分点数 | 构成 | 负责方（ownership.yaml） |
|---|---|---|---|---|
| 1 | tools/bakeoff/run.py | 19 | hard_path 5、direct_ssh 4、hard_run 4、no_timeout 3、def_ssh 1、silent_read 1、nonatomic_json 1 | BAKEOFF（已停，IMGFIX 代管） |
| 2 | tools/video_rca/lab.py | 19 | hard_path 13、direct_ssh 2、nonatomic_json 2、def_ssh 1、hard_run 1 | VIDEO_RCA |
| 3 | tools/monitor/server.py | 15 | silent_read 9、hard_path 6 | SENTINEL（我名下，下一轮自己清） |
| 4 | tools/video_rca/srv_run.py | 15 | hard_path 7、no_timeout 4、nonatomic_json 2、hard_run 1、silent_read 1 | VIDEO_RCA |
| 5 | services/api/ns_api/edits.py | 12 | silent_read 9、nonatomic_json 2、hard_run 1 | EDITDEL（已停，UIRSI 代管；改前要在 docs/uimaster/LOCKS.md 登记临时锁、改完跑 data_parity） |

按模块（前两级目录）：services/api 112、tools/series10_video 63、tools/gen_contract 53、tools/video_rca 49、services/agent 48。
