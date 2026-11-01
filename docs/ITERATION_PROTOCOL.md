# 统一迭代协议（ITERATION_PROTOCOL v1，ITERAUDIT 2026-11-01）

> 项目方原话（11-01）：“整个 system 的 iteration 还要全部 check 一下，这个是没有 logic 的。”
> 起因：画布上 S1–S4 显示的是同一份内容，夜里约十个 loop 各自迭代，没有一个发现——它们量的是像素、间距、截图分数，没有量“界面上的内容 = 后端这一镜的数据”。
> 本文是所有迭代 loop 的共同骨架。收轮闸门：`tools/qa/iter_gate.py`（规则 K-OPS-Q01、K-OPS-Q02，`knowledge/rules/ops_iteration.yaml`）。所有权表：`tools/qa/ownership.yaml`。
> 数据一致检查（前端 = 后端）由 DATAALIGN 交付（待交付）`tools/qa/data_parity.py`，本协议只调用它，不重复实现。

---

## G0. 全局决策原则（项目方 2026-11-01 定，所有 loop、所有决策的前提）

> 项目方原话（11-01 约 16:25）：“你是rsi了,因此,在做任何事情都要全面scan一下md,看看是不是最好方案,我们千万不要补补修修,我们要全局思维去看待每个tasks是否合理,我需要你约定这个原则,我们做任何决策都要这个前提,一旦决定了,其它sub-tasks related都要改一下”

任何决策、派活、修复都按下面四步走，跳过任何一步都不算完成：

1. **先全局扫描**：动手前在 docs/、knowledge/、config/、各 loop 的 STATE.md 和 REQUIREMENTS.md 里检索这件事的关键词。回答三个问题：已有部件吗？有项目方旧决定吗？有别的 loop 在做吗？把检索词和命中的文件写进决策记录。
2. **判断是不是最好方案**：优先复用和打开已有系统（例如把只记录的开关转成拦截），不要另造平行实现。只修一个症状的补丁，必须说明为什么不改根因。
3. **决定后全量同步**：列出受影响的文档、配置、规则、正在跑的 loop 派单和子任务，逐项改到和新决定一致。被取代的旧说法标 ⤴ 并写明取代者，不能留着互相矛盾的口径。
4. **入账可检**：决定进 MASTER_PICTURE §1 账本和 config/owner_decisions.yaml（K-OPS-D01）。旧口径关键词登记为过期词，由 K-OPS-D02 的检查扫描还有没有残留。

## G1. 提炼原则（项目方 2026-11-02 定，L-102；每轮 RSI 的必交物）

> 项目方原话（11-02 01:4x）：“这个系统是拿这部剧来做一个 sample 的。所有的 learning 规则都要写到这个系统里，后面就不用 Claude 来指引整个事情了，不然成本会很高……尽量每次选完之后，把东西写成代码和文档存到系统里。我只会用 API key 来做简单的工作……所有工作尽量写成一个代码库，来 monitor 整个 process……创建剧本之后，剩下的流程就会按照你现在写的代码和规则全部自动化下来，包括检测图片、检测效果图是否有效等等。”

1. **每个判断都要落成机器能执行的东西**：总调度或 agent 每做一次判断（选图、驳回、GPU 分工、交还条件、积压上限、止损、预算停跑……），本轮就必须写成以下之一，并带测试或 check：代码策略（config/policies/*.yaml + 读取它的代码）、knowledge 规则、闸门、本地模型 / 便宜 API 的判定 prompt。只写在聊天或报告里的结论不算完成。
2. **记录“谁做的判断”**：编排器给每个环节标 `decider = code | local_model | api_model | owner | claude`。DISTILL 每轮统计 `claude` 的占比（无 Claude 覆盖率），目标是新剧本从剧本导入到成片 decider 全部不是 claude。
3. **一个编排器**：剧本导入之后的全部环节，由同一套代码推进和监控（tools/autopilot/），包括出图、看图检测、视频、视频检测、合成、成片评分。各 loop 的工具都要接到这个编排器上，不能另起入口。
4. **项目方只保留必要闸门**（见 L-098 委托范围），其余全由规则、代码和本地模型判定。

例（11-01 首次执行）：项目方要求“看图检测、不对就重出”。全局扫描发现 R11-4/5/10 已经建好 VQA 闭环，只是 `config/vqa.json judge.enforce=false`。于是改成打开现有闭环、补充跨镜连贯检查项，没有新建检测器，同时同步 REQUIREMENTS、vqa/acting STATE、SOP §8 §9、GEN_CONTRACT。

---

## 0. 审计结论（为什么要统一）

### 0.1 各 loop 现状

| Loop | 触发 | 量什么 | 通过线 | 谁判 | 回归 | 写回 | 何时停 |
|---|---|---|---|---|---|---|---|
| UIMASTER | 每次改前端后 `crawl.mjs --iter=N`，目标 100 轮 | 报错层 / 白屏 / 控制台 / 接口错 / 像素（check.js）/ 滚动 / 点了“无反应” / 小图能否放大（`apps/web/e2e/uimaster/crawl.mjs` 第 327–458 行） | 问题数下降；`gate.sh` = tsc + build + main.tsx 200 | 自己（问题“复爬未再出现”即记 verified，第 547–551 行） | 无基线功能清单；无数据核对 | `docs/uimaster/issues.json`（11-01 01:26 时 iter_001 仍在跑，文件未生成） | 100 轮 |
| UIRSI | 每轮 r1…r28（31 待交）按 `docs/uirsi/RUBRIC.md` 打分，修最低 2–3 项 | R1–R17 + 任务分 T1–T7（点击数 / 秒）+ 技术分 K1–K5 | 总分 ≥128/170、每项 ≥6；T 平均 ≥9 | 自己写打分器、自己打分 | “同一测法”只写在 RUBRIC 第 17 行，没有代码强制；测法中途改过 3 次 | `knowledge/rules/ui.yaml`（32 条，0 条有机器落点） | 无停止条件 |
| UIPIXEL | `scan.mjs <round>` | 可点区域、对齐、间距刻度、悬停态、指针（`docs/uipixel/scan_t2.md`） | 问题数 | 自己 | 无 | 无 | 无 |
| UIAUDIT | 每轮 `run_round.ps1 rN` 复测别人 | 契约覆盖率（对象×操作）、任务分、滚动 G1–G5、G10 功能回退 | 覆盖 ≥60%、任务 ≥70、滚动 40/40、G10 P0=0 | **独立方**（唯一一个） | G10：`regress_check.mjs` 按正则找文字 | `K-UI-021…030` | 无 |
| ASSETMASTER | 资产 / 帧重做 | 契约 Q1（身份）为主；场景 / 单品看“过契约” | `tools/assetmaster/choose.py`：两版都过 Q1 选 FLUX | 自己选、自己登记（`--apply` 直接写资产库） | 无 | `asset_assetmaster.yaml` 8 条，0 条有机器落点 | 无 |
| REFLOCK | 参考锁定、契约实现 | 契约 Q1–Q7；阈值在自己的已知答案集上标定 | `config/gen_contract.json` | 自己写阈值、自己验证（`tools/gen_contract/reflock_validate.py`） | 无 | `gen_contract.yaml` 9 条，0 条有机器落点 | 无 |
| IMGGEN | 每镜首帧，失败换 seed ≤3 次 | 身份 / 景别 / 文字 | 契约 | 自己 | 无 | `render_imggen_s10.yaml` 14 条，0 条有机器落点 | 3 次后取最好一张标“尽力” |
| VIDEO10 | `night.py` 每 120 s 一轮，按集推进 | `score_clip.py`：动作 / J4 / 泛红 / 硬切 / 身份 / 景别 | 契约 + K-REN-122 | 自己；审片页交总调度 | 无 | `render_video_s10.yaml` 7 条，0 条有机器落点 | 每镜“通过 / 尽力 / 等首帧”即合成；`force_eps` 可强制放行 |
| BAKEOFF | 新模型就重跑 | 契约 Q1–Q7（Q2 / Q7 是颜色直方图代理） | 排名 | 自己 | 无 | — | 一次性 |
| AUTOPILOT / iterate_loop | `run.py` 状态机 + loop tick | `reviewer.py` ACCEPT 10 项指标 + 审片模型 | 阈值 | 审片模型或 RuleBased（同一批指标） | 无 | `learned.yaml`：同一调整成功 5 次且 ≥80% 自动“确认” | 每镜 3 次后标“待项目方”；delivery 闸门 |

### 0.2 逻辑漏洞（证据）

| # | 漏洞 | 证据 |
|---|---|---|
| H1 | **量错东西**：所有 UI loop 只量“样子”，没有一项量“内容 = 后端这一镜” | `apps/web/e2e/uimaster/crawl.mjs`、`apps/web/e2e/uipixel/check.js`、`apps/web/e2e/uiaudit/detect.mjs` 都没有调用 `/api/shots/{id}` 做比对；`docs/uiaudit/UI_CONTRACT.md` 第 35–45 行 G0–G10 全是结构 / 排版，G8“最新可见”测法写的是“人工 + 截图”；G10 的回退检查（`apps/web/e2e/uiaudit/regress_check.mjs`）只用正则找“首帧 / 尾帧 / 视频”这几个字——S1–S4 显示同一张图也能通过 |
| H2 | **代理分数涨、任务没做成** | `docs/uirsi/rounds/r19-r25.md` 第 79 行：任务分记 9.3，“T4–T7 卡在生产状态闸门……不扣界面分”（7 个任务里 4 个做不完）；`knowledge/RSI_LEDGER.md` U8：排版分 9.3–9.8 时 T3 挑设定图“根本做不到”；`docs/uirsi/rounds/r14-r18.md` 第 20 行 T3 终点中途改过 |
| H3 | **没测到 = 通过** | `tools/iterate_loop/reviewer.py` 第 65–72 行 `failures()`：`if thr is None or v is None: continue`；`flatten()` 第 47 行把 None 指标删掉——没检测到脸时 `sface_ref_min` 不存在，身份项直接算过。与 `services/agent/ns_agent/gen_contract/postflight.py` 文件头“没测到的项 = untested（不算通过）”互相矛盾 |
| H4 | **“已验证” = 症状没再出现** | `crawl.mjs` 第 547–551 行：上一次的问题这一轮没再出现就记 verified；点击配置按轮换（第 32 行）、每页最多点 80 个——没测到也会被记成“已验证” |
| H5 | **自己改、自己判** | UIRSI 自己写打分器（`apps/web/e2e/uirsi/score.mjs`）自己打分，测法中途改了 3 次（`docs/uirsi/RUBRIC.md` 第 77 行 K2 r19 改口径、第 110 行 r7 改对比度口径、T3 终点）；UIAUDIT r2 复测时，UIRSI 说已加的 EditButton 实际找不到（`docs/uiaudit/detect_r2.md` §2 第 1 条）；ASSETMASTER 的 `choose.py --apply` 自选自登记；REFLOCK 在自己的已知答案集上定阈值（`knowledge/RSI_LEDGER.md` RL4：鞋线 0.775，反例最高 0.762，余量 0.013） |
| H6 | **没有回归基线，修了又坏** | `knowledge/RSI_LEDGER.md` UIA5：基线比对查出 6 条 P0 功能回退，“r1–r3 的 detect 一条都没抓到”；`docs/uirsi/rounds/r26-r28.md` r28：项目方“剧本的页面你改坏了”；`docs/uirsi/rounds/r5-r7.md` 一轮归档 31 个文件；G10 规则 K-UI-030 是事后才加的，而且 UIRSI 自己的轮次流程里没有调用 |
| H7 | **规则没有检查** | `knowledge/rules/` 260 条里 155 条既没有 targets 也没有 loop 块（`ui.yaml` 32/32、`gen_contract.yaml` 9/9、`asset_assetmaster.yaml` 8/8、`render_imggen_s10.yaml` 14/14、`render_video_s10.yaml` 7/7）；`docs/GEN_CONTRACT.md` §0.3 要求总调度签 `master_review.md`，契约定稿（10-31 23:40）之后更新过的审片页里，只有 `series10_images`、`series10_imgfix` 有签字（`master_review_v1/v2.md`）；`asset_reflock`、`image_bakeoff`、`series10_assets_v2`（11-01 01:07–01:28 更新）、`series10_video`、`uiux` 都没有，也没有代码阻止发出 |
| H8 | **loop 互相覆盖** | `docs/uimaster/LOCKS.md` 只管前端，后端和数据文件没有归属：`first_frame_jobs.json` 被 `tools/pipeline/image_jobs.py` 重写，同时被 imggen / imgfix / bakeoff / calibrate 读（存在 `first_frame_jobs.before_round2.json`）；`knowledge/RSI_LEDGER.md` G11：SERIES 手工剥触发词，把应保留的出图触发词和 LoRA 一起剥掉；`takes.json` 在 tools / services 下 43 个 .py 里被引用；`docs/CHANGELOG_AGENTS.md` 第 13 行：测试读生产剧本，被别的 loop 换剧本后整体失败 |
| H9 | **数字无出处 / 过期** | `docs/uirsi/STATE.md` §1 路由表在 r5 后过期（第 164 行自己承认）；UIRSI 报告“已加”的东西被 UIAUDIT 复测否定；任务分 9.3 是在把失败任务剔除后算出来的 |
| H10 | **停不下来，也不升级** | UIRSI、UIPIXEL、UIMASTER 没有“分数不再涨 / 同一问题复发就停”的条件；IMGGEN 和 VIDEO10 失败后标“尽力”照样进合成（`knowledge/RSI_LEDGER.md` IMG I5：25/80 镜是“尽力”；`tools/series10_video/night.py` 文件头：“尽力”即算定下并合成） |

---

## 1. 每一轮的 7 步（所有 loop 一样）

| 步 | 做什么 | 必须产出 | iter_gate 项 |
|---|---|---|---|
| 1 项目方任务 | 从 §2 选本轮服务的项目方任务 OTn（可多选）。不能对应任何 OT 的改动，不算一轮迭代 | 报告第一行写 OTn | S0 |
| 2 度量（先测正确性） | 顺序固定：**① 正确性**（data_parity：界面内容 = 后端；契约 Q1–Q7；剧本字段逐字）→ **② 任务能否做完**（OT 的 done_when）→ **③ 样子**（像素 / 间距 / 速度）。③ 的分数不能抵消 ① ② 的不过。测不到的项记“未测”，不是“通过” | 度量结果文件路径 | D1、C1 |
| 3 改动 | 只改 `tools/qa/ownership.yaml` 里属于自己的文件；共享文件只走规定写入口；前端改动先在 `docs/uimaster/LOCKS.md` 登记 | `--changed` 文件清单 | O1、O2 |
| 4 独立复核 | 复核方 ≠ 改动方（见 §4 复核表）；复核证据必须比改动新 | 复核方的证据文件 | V1 |
| 5 回归 | 前端：`gate.sh` + G10 功能清单（`detect.mjs flows_regress.json` → `regress_check.mjs`；iter_gate 自动取 UIAUDIT 最新一份 `rNg_detect.json`，按修改时间再按轮号，不写死某一轮）+ data_parity；生成：契约逐项（未测 / 冒充通过即不过）；全部：`compile.py --check`、`check_chain.py`；相关 pytest | detect / 契约 JSON | U1、R1、D1、C1、K1、K2、T1 |
| 6 入账 | 报告写 7 步，每个数字同一行带出处（文件路径或 §）；结论写进 `knowledge/RSI_LEDGER.md` 本 loop 的节 | `--report` | L1 |
| 7 规则 + 检查 | 新教训写成 knowledge 规则，**必须带 `check:` 字段**（指向强制它的测试 / 校验器 / gate）；给不出检查的只能进 `knowledge/inbox/` 当草案；没有新教训就写 `--no-lesson "<理由>"` | 规则 id | RL |
| 7a 写作方回写 | 项目方 11-01：“记得每一次发现bugs,找到solution后,把规则写到系统code去,这样,剧本llm更好去自动改进”。每条教训先分类：**影响剧本 / 分镜该怎么写的**（domain=writer，或 link 在 P0–P4），规则必须同时带 ① `targets: [{kind: writer_prompt, section: …}]` + `writer_text`（compile.py 写进 `config/recipes/writer_knowledge.md`，写作模型的 system_parts 里）和 ② `lint: [QW-…]`（P4 校验器里定义的规则号；`tools/qa/writer_lints.py` 的 QW-W* 在写作链路 p4_adapter / qwen_repair_loop 里是 block，写作模型返修环自己改）；只影响系统层的不用 | 规则 id | RL（写作规则不完整 = 不通过） |

收轮：`.venv/Scripts/python.exe tools/qa/iter_gate.py …` 退出码 **0 = PASS** 才能说“本轮完成 / 已修 / 已验证”；**1 = FAIL**（修或回滚）；**2 = INCOMPLETE**（补测；未测 ≠ 通过）。结果写在 `data/qa/iter_gate/<loop>_<round>.md`，回报总调度时附这个路径。

## 2. 项目方任务（验收看任务做成 + 内容正确）

定义在 `tools/qa/ownership.yaml` → `owner_tasks`：

| 任务 | 做成的标准 |
|---|---|
| OT1 审一集的镜头行 | 每镜首帧 / 尾帧 / 视频 / 台词 = 后端该镜当前版本；不同镜内容不同 |
| OT2 接受 / 打回候选 | 一键生效，后端 current 真的变了；撤销后后端恢复 |
| OT3 试听 | ▶ 播的是这一镜这一句的音频（URL 与 `/api/shots/{id}/audio` 一致），能停、能 A/B |
| OT4 放大看图 | 原图、这一镜这一版、Esc 可关 |
| OT5 对照剧本 | 界面上的剧本原文 / 对白 / 造型 = Shot Spec 该镜字段（逐字） |
| OT6 挑设定图 / 定脸 | 点选后资产库当前版本改变，下游解析器读到新图 |
| OT7 看成片 / 对比 | 播放的是最新合成文件；两版同步 |
| OT8 新建剧本到导入 | P1–P4 可看可改；导入后画布镜数一致 |
| OT9 生成结果合格 | 契约逐项表（未测 ≠ 通过）+ 总调度 `master_review.md` 签字后才给项目方 |

## 3. 停止与升级

**停（本 loop 本目标结束，报总调度）**
- 连续 2 轮 iter_gate PASS，且本轮所选 OT 的 done_when 全部满足；
- 或连续 3 轮正确性指标（D1 / C1 的不过数）没有下降——说明方法不对，停下来换方法，不要继续刷样子分。

**立刻停手并升级总调度**
- 回归：G10 出现 P0、data_parity 由过变不过、契约出现“冒充通过” → 先回滚本轮改动，再报；
- 同一问题第二次出现（GEN_CONTRACT §5：视为系统缺陷）→ 要补规则 + 检查，不是再修一次；
- O1 越界（要改的文件属于别人）→ 发消息给 owner，不要自己改；
- 需要项目方闸门（定脸 / 定稿 / 删除 / 花钱 / 推翻旧决定）→ 按 `feedback-use-choice-dialog` 交总调度出选择题；
- 每镜重出 3 次仍不过 → 标“不合格”，**不进合成、不给项目方**；“尽力”只能放在标明“未达契约”的单独分组里。

**禁止**
- 改测法后拿新旧分数比较（同一指标改口径要开新版本号，前后两轮都用新口径重测）；
- 把做不完的任务从分母里剔除；
- 在别的 loop 刚改过（O2 提示）的文件上覆盖写。

## 4. 所有权与复核

文件归属以 `tools/qa/ownership.yaml` 为准（O1 自动核对）；摘要：

| Loop | 拥有 | 本轮复核方（V1） |
|---|---|---|
| UIMASTER | `apps/web/e2e/uimaster/**`、`docs/uimaster/**` | UIAUDIT |
| UIRSI | App / TopBarV3 / Canvas / ReviewRow / `v3/pages/**`、`services/api/ns_api/takes_ui.py`、`shot_audio.py`、`story_runs.py` | UIAUDIT（数据一致由 DATAALIGN 的 data_parity） |
| UIPIXEL | 全部 `apps/web/src/**/*.css`（含资产 / 编辑目录下的）、`ds/ZoomLayer.tsx` | UIMASTER（复爬）+ UIAUDIT G10 |
| UIAUDIT | `apps/web/e2e/uiaudit/**`、`docs/uiaudit/**` | 总调度抽查（UIAUDIT 不改产品代码） |
| ASSETUX / EDITDEL | 资产中心 / 编辑删除相关前端 | UIAUDIT |
| ASSETMASTER | `tools/assetmaster/**`、`data/assetmaster/**` | REFLOCK（契约）+ 总调度 master_review |
| REFLOCK | `tools/gen_contract/**`、`ns_agent/gen_contract/**`、`config/gen_contract.json` | BAKEOFF 或总调度用留出样本复核阈值（不能用标定时的同一批图） |
| IMGGEN | `tools/series10_imggen/**` | REFLOCK（契约） |
| VIDEO10 | `tools/series10_video/**` | 总调度 master_review（审片页） |
| BAKEOFF | `tools/bakeoff/**` | REFLOCK |
| AUTOPILOT | `tools/autopilot/**`、`tools/iterate_loop/**`、`tools/pipeline/**`、`services/recipes/**` | 总调度 |
| DATAALIGN | `tools/qa/data_parity.py`（待交付） | UIAUDIT |
| ITERAUDIT | `tools/qa/iter_gate.py`、`tools/qa/ownership.yaml`、本文 | 总调度 |

**owner 授权**：owner 同意别的 agent 改自己某个文件时，在 `docs/uimaster/LOCKS.md` 的“## 授权”一节加一行，格式固定：`CONSENT: <文件 owner> -> <被授权 agent> : <路径或 glob> | <原话 / 日期>`（例：`CONSENT: UIPIXEL -> UIRSI : apps/web/src/ds/live.css | …`）。iter_gate O1 读到匹配的授权行就判通过（记“owner 授权”），没有授权行仍判越界。

共享文件（只走写入口）：`takes.json`（API / register_takes）、`first_frame_jobs.json`（image_jobs.py）、`identity_refs/**`（项目方闸门）、`learned.yaml`（writeback.py）、知识库生成物（compile.py）、`knowledge/rules/**` 与 `RSI_LEDGER.md`（只追加自己的条目）、`services/api/ns_api/**`（先登记 LOCKS，改完跑 data_parity）、`main.tsx`、`v3/candidates.ts`（先登记 LOCKS）。

## 5. iter_gate 用法

```
.venv/Scripts/python.exe tools/qa/iter_gate.py --loop UIRSI --round r29 --task OT1,OT4 ^
  --changed apps/web/src/v3/ReviewRow.tsx --verifier UIAUDIT --verify-evidence apps/web/e2e/uiaudit/r6g_detect.json ^
  --report docs/uirsi/rounds/r29.md --rules K-UI-033
```

生成类加 `--contract <ContractResult JSON>`；要给项目方看加 `--for-owner --review-dir data/review_pages/<批次>`。
`data_parity.py` 交付前，UI 类 loop 的 D1 一律是“未测”→ INCOMPLETE；这是有意的：在内容正确性能被测之前，UI 轮次不能宣布完成。

## 5.1 测试不写真实数据（K-OPS-Q03）

`tests/conftest.py` 在会话开始装 `tools/qa/real_data_guard.py`：本进程任何线程写真实 `data/`（open 写模式、`Path.write_*`、`os.replace` 等）一律抛 `RealDataWriteError` 并记账；`P.DATA`、`P.RENDERS` 等数据根默认指向临时目录；会话结束有违规、遗留非守护线程、或真实 `takes.json` 等哨兵文件被改，退出码 1，报告写 `data/qa/test_guard_last.json`。确需真实数据的用例标 `@pytest.mark.real_data`。iter_gate T1 读这份报告，没有本次报告即判不通过。

## 5.2 内容缺陷猎捕（常驻 loop，K-OPS-Q13，项目方 R11-11）

任何 loop 都只量自己的指标；**内容缺陷**（看镜头、第二人没表情、多手、跨镜鞋不一致、节奏慢、字幕、低分辨率……）由这个常驻 loop 专门找：
1. 触发：每出一集新首帧 / 新视频 / 新成片。
2. 度量：`tools/qa/defect_hunt.py`（59 类：剧本 / 首帧 / 视频 / 声音 / 合成；auto 本地检测，看图类进 VQA 的 VLM rubric 队列），断点续跑。
3. 分派：命中按 `tools/qa/ownership.yaml` 交 owner，写进 `docs/rsi/DEFECT_HUNT.md`。
4. 固化：确认的类 → 规则 + check；写作相关的同时 writer_text + QW lint（7a）。
5. 闸门：iter_gate **H1**——生成类 loop 收轮时猎捕状态必须比最新产出新、检测器无报错。
6. 停：连续两集新产出某类 0 命中且 VLM 抽检通过 → 该类降为周检；新样例（项目方 / 总调度指出）→ 当天加类。

## 6. 已知未修（留给各 owner，不在本协议内改）

- `apps/web/e2e/uimaster/crawl.mjs`：verified 要求同配置、同元素被点到且有正向断言（UIMASTER）。
- `apps/web/e2e/uiaudit/regress_check.mjs`：功能清单每条加“内容断言”（例如首帧图 src 属于该镜、各镜 src 互不相同），接 data_parity（UIAUDIT + DATAALIGN）。
- `docs/uirsi/RUBRIC.md`：任务分不得剔除做不完的任务；测法改动开新版本号（UIRSI）。
- 无检查的旧规则（总调度 11-01 决定）：157 条已标 `enforced: false`，继续作为指引生效、不降级；按 owner 的清单见 `docs/master/unchecked_rules.md`（`tools/qa/iter_gate.py --list-unchecked` 重新生成）；各 owner 在 sweep 里补 `check:` 后删标记。RL 只对新规则缺检查判不通过。
- `tools/iterate_loop/reviewer.py` / `writeback.py` 已修（ITERAUDIT 11-01，总调度指派）：有阈值但没测到 = untested 失败；`learned.yaml` 自动确认要求留出镜（学到它的镜以外）≥ 2 条且成功率 ≥ 0.8；测试见 `tests/test_iterate_loop.py`。
