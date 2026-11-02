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
| UI 未测 | 页面之间深链接顺畅；只有“用这张”+“修改”；提交类操作 300 ms 内收下 + 全局队列；只显示通过验收的图 | — |
| 工作流 | unattended 35 = 1 − 等人决定的对象 / 在途对象（S13 + 登记表 pending / ready / running）；no_stuck 25 = 1 − S11 卡段工单 / 集数；no_dup 25 = max(0, 1 − S17 无限重出工单 / 5)；auto_requeue 15 = 1 − 建单超过 30 分钟仍是 new 的反馈单 / 反馈单总数 | data/sentinel/state.json、data/producer/registry.json、data/autopilot/flow/status.json、data/feedback/items |
| 工作流未测 | 每集完成自动回报；第二季暂停状态只认一个来源 | — |
| GPU 管理 | productive 40 = min(1, gpu_24h 真实运行占已知时段 / 80%)；rssh 20 = min(1, 近 24 h SENTINEL 合并调用成功率 / 0.99)（样本 < 10 记未测）；deploy_stop 15 = 部署 / 重启类暂停最长一段 ≤ 120 s 记 1，否则 120 / 最长；resident 15 = S25 常驻 CLIP 无未关工单记 1；lend_expiry 10 = S18 临时挂道无过期工单记 1 | data/rsi/gpu_24h.json（含 pause_segments）、data/sentinel/state.json mem.remote_calls、S25 / S18 工单 |
| GPU 未测 | 没有因分区错误或旁路导致的重复出图（分区唯一来源落地后接 S17 按分区拆） | — |

负责方（工单派给谁，抄送总调度）：出图 PROMPTFIX / VQAGATE / DETECT-S；视频 DEBUG-RSI / ASSEMBLY / CUTEDIT；剧本 HOLLYWOOD / SCRIPTWRITER；UI NAVIA / ASSETUX / UISCRIPT / POSTER；工作流 DEBUG-RSI / FACTORY；GPU 管理 FACTORY / NETFIX / SENTINEL；代码 AUDIT-M / FACTORY。
