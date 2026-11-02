# REVIEW_GLOBAL_FABLE：从项目方与产品出发的全局审查（GLOBAL-F，11-03 03:1x–03:3x，只读）

> 口径：以 docs/master/OWNER_CANON.md C-01…C-25 为唯一标准；每条结论都给出 文件:行号 或 11-03 03:1x 实测（GET http://127.0.0.1:8800 / 读 apps/web 源码 / 跑只读命令）。
> 不采信任何 agent 报告里的说法；引用 V1_TO_V2_CARRYOVER / RETRO_ep01 / V2_WALK_AUDIT 时只引其中能复核的事实（我重新核过文件或接口）。
> 没做的事：没改代码、没重启、没出图、没读 data/master/。
> 一句话总判：**系统“规则层”很厚（667 条 K 规则、87 条决策断言、265 个测试文件、31 份 master 文档），但“产品层”对项目方几乎是空的：V2 到现在 0 张首帧、0 条视频、0 个成片；他能在网页上做的只有看 5 条“已自动选用”的通知。**

---

## A. 需求覆盖表（OWNER_CANON C-01…C-25）

状态：✅ 已满足｜◐ 部分满足｜✗ 未满足｜▼ 被退化（V1 有、V2 丢或变差）

| # | 定律（缩） | 状态 | 证据（实测 / 文件:行） | 缺口一句话 |
|---|---|---|---|---|
| C-01 | 全自动流水线，每集比指标 | ◐ | 推进链在：resident 第 67 拍、asset_worker 15 s 前、派单器 enabled（`tools/master/master_check.py` 03:13 输出 ⑥④）；但 ep01 自动化 0.3232、介入 54 次、项目方等待 125 min（`docs/master/RETRO_ep01.md` §1，由 episode_metrics 算）；V2 出图 / 视频链不存在：`data/renders/series10_v2/` 不存在，`tools/series10_video/build_jobs.py:37`、`vidgen.py:37`、`night.py:29` 写死 `series10_v1` | 写作段已半自动，出图以后全靠人 |
| C-02 | 不修修补补；卡点→规则+代码 | ◐ | 有登记机制 `tools/master/report_issue.py`、`PIPELINE_SOP_V2.md`；但 RETRO_ep01 51 条卡点里 28 条“写进代码 ❌ 没找到”（`RETRO_ep01.md` §2 统计）；ASSET-WORKER 同一类“sheet/item 连续失败”登记 11 次（ISS-1103-011516…024835）仍在重复 | 同类卡点重复出现 = 没从根上修 |
| C-03 | 记忆压缩成骨架，先读再干 | ✅ | `~/.claude/.../memory/MEMORY.md`（11-03 02:51 重建，51→34 份），34 条链接全部可解析（脚本核过）；仍有 2 处过期：`ns-final-studio-current-state.md` 只记到 L-144，账本已到 L-146；`ns-final-studio-v2-restart.md` 正文仍写“等项目方给 V2 方向”（L-127 已给） | 小修即可 |
| C-04 | 人物一致性是系统工程 | ▼ | 生效：唯一编译入口 `frame_job.py:264`、种子流 K-REN-954、I2/I11 只认清单（CARRYOVER §四 B）；**退化**：Q1a 人物卡只有 lin_wan/gu_chen/chen_yu（`config/gen_contract.json Q1a_attr.cards`，ISS-…c8c0 open）；近景服装整句被 K-REN-707 删光（ISS-…8856 open）；`config/vqa.json gate.video_requires_q9=false`（ISS-…4b21 open） | 3 个 P0 都登记了、都没关 |
| C-05 | 画面质感：实拍感、徕卡、4K、时尚大片 | ✗ | V2 一张正式首帧都没有：`GET /api/frames-index` → `episodes:[]`，`GET /api/candidates?ep=1` → `shots:{}`；L-145（徕卡+ARRI+Kodak）11-03 04:3x 才定，`config/owner_decisions.yaml` 只到 L-144（grep） | 无法评；先出图 |
| C-06 | 不要字幕 | ◐ | 写作 / 出图后缀有禁字幕句（第 8 镜编译含“无字幕句”，CARRYOVER §三）；视频 H3-D4 lint；剪辑器“不烧字幕”（`CutEditor.tsx:6`）；成片无 OCR 探针（CARRYOVER C 表“无字幕”行） | 成片侧少一道检测 |
| C-07 | 不看镜头、表演三套规则 | ◐ | 写作 QW-A1–A8 生效（`tools/qa/acting_lints.py`）；首帧提示词含视线句（第 8 镜编译）；视频侧只限 V1（`vidgen.py:103-113`） | 视频链接上才算 |
| C-08 | H3 时间轴按秒分拍 | ◐ | RL-T1–T9 已 strict 挡在导入（`sop_gate status`：ep01 gate=reopened，“补丁已出 10 次仍有失败项”）；L-141 At 只标切镜已进 lint（`tests/test_timeline_o.py`） | 规则生效了，但 ep01 被它卡住 10 轮 |
| C-09 | 只有“用这张”+“修改”；202 异步；只给看通过的 | ◐ | V2 资产页只有“修改”（`V2AssetsPage.tsx:41-43`）；审片行“用这张 / 修改”（`ReviewRow.tsx:161,182`）；cut-job / cut-project 都 202；**残留**：`App.tsx:172` 仍挂 `RejectDialog`；`OwnerQueuePage.tsx:19-22` 机签抽检给“身份不像 / 造型不对 …”原因列表（= “不要 + 原因”语义） | 两处 L-123 残留 |
| C-10 | 登录即本人；一键；#/queue 通知中心 | ◐ | `#/queue` 在，`GET /api/owner/inbox` count=5 全是 pick；`auth.py` 在；**但** inbox `master_waits` 写“总调度在定 51 项（等总调度，不需要你）”，对象含 `first:ep03-S1 / last:ep03-S6`——V2 只导入了 ep01，这是 V1 对象泄漏进项目方通知中心 | 通知中心混进 V1 杂讯 |
| C-11 | 总调度全权 + 代选 | ✅ | `config/pipeline/owner_delegate.json enabled=true`，never 列表写死；`GET /api/owner/delegate` 显示 L-136 出处 | — |
| C-12 | 总调度必须亲审 | ◐ | `master_check.py` 一页巡检在；“③ 未复审交付：deliver.py 未上线，无从统计”（03:13 输出） | 复审门没有代码 |
| C-13 | GPU 24 小时拉满 | ✗ | `GET /api/factory/health` 03:12：gpu33:0/1/3、gpu36:0/1、laptop:0 全部 `state:idle util 0.0`；ep01 GPU 占用 0.1446（RETRO §1）；而 `data/rsi/scores.jsonl` 最新 gpu 线 95 分（productive 100）——计分口径与事实相反 | 空转且计分不报警 |
| C-14 | 旧内容隔离，网页只显示最新 | ▼ | 隔离生效：`run_paths.py:38-55` V1PathError、`/api/v1-library readonly:true`；**泄漏**：`/api/owner/inbox master_waits` 含 ep03 对象；`/api/readiness?ep=1` 返回 `continuity_sheet_path:"renders_gpu3/ep01/…"`（V1 路径）；`/api/episodes/1/cuts` `script_at:"2026-10-31T23:15:59"`（V1 导入时间）；`/api/decision-locks` 第一条是林晚 L-122 脸锁 | 4 个接口把 V1 事实带给 V2 页面 |
| C-15 | 剧本好莱坞级 | ◐ | P1 三评委三模型（RETRO：fable 5 / opus 5 / sonnet 5）；ep01 评分 `score_basis=code_only_27`（CARRYOVER A 表“好莱坞评审”行）；P1 均分 27.33→32 低于 34 门槛仍进入 P2（MASTER_PICTURE M-V2-P1-R4） | 门槛没挡住，评审只跑代码分 |
| C-16 | 资料齐才出；先图后视频；按集；整集 BGM | ◐ | `sop_gate.py` 阶段序列写死、L-140 整集就绪（`asset_worker.json max_parallel=2`）；集级 BGM V2 没有写入方（`tools/bgm/agent.py:31`、`deliver.py:29` 写死 `data/music/series10`） | BGM 链按剧参数化 |
| C-17 | 画布一镜一行，首尾帧大图 | ✅ | `ReviewRow.tsx:1-2,417-426`：首帧｜尾帧｜视频 + 剧本 / 表情 / 对白 / 声音 / 首帧提示词 / H3 提示词 / 镜头 | 保住了 |
| C-18 | 多模型分工、省 Opus | ✅ | `agent_dispatcher.json kinds=[writer,reviewer]`、SOP `must_differ_from`（`PIPELINE_SOP_V2.md` 派人表） | — |
| C-19 | 成本：测试期 Claude 写 | ✅ | `/api/script-autoflow/series10_v2` `budget_usd:0.0`；NewScriptPage 显示“花费 $0.00 · 写手直接写”（`NewScriptPage.tsx:408`） | — |
| C-20 | 沟通：中文、短、本地审片页 | ✅ | `data/review_pages/v2_assets/<run>/<job>/`（inbox link 字段指向本地页） | 过程性，无代码 |
| C-21 | 研究闭环、结构化控制 | ◐ | IMGLAB 四类无一进生产（CARRYOVER §五 H：全仓 PuLID / IC-Light 0 命中）；L-143 定 ep02 起 A/B | 已知、已排期 |
| C-22 | 安全红线（自有机器、全成年、不发外部） | ✅ | I10 HC-07 / I12 本地路由 pass（第 8 镜 preflight）；ep01 11 镜 adult 全“否”（`episode_ready` 输出） | — |
| C-23 | 服装造型以项目方指定为准 | ◐ | `assets_v2/manifest.json:137`“只有 O1–O4（O4 是 19:1x 新增的日常装）”；ep01 用 O4，但 `episode_ready` 报“祁念 造型O4 没有设定图”，I3 只显“设定图 0 张”仍 pass（CARRYOVER §三） | O4 设定图是 ep01 唯一资产缺口；`V2_LIVE.md` 19:0x 行仍写“只允许 O1/O2/O3”，与清单矛盾 |
| C-24 | 运镜 / 镜头语言 | ◐ | 词表 A/B 字段齐（`camera_moves.yaml:279-352`）；视频端两处不传 run → V2 专属运镜变 static（`ns_recipes/prompt.py:215`、`ns_render/pipeline.py:801`，ISS-…0474 open）；shot_spec_v2 没接 build_first（ISS-…2869 open） | 2 个 P0/P1 open |
| C-25 | 每轮发版、自动回报、探针先于项目方 | ◐ | 最近 cut sv-20261102-16（11-02 21:04）；本机 `data/system_version.txt` 停在 sv-04 → scores 的 sv 标签全错；SENTINEL S6 自 11-02 12:41 起每拍报错（CARRYOVER G 表） | 发版停了 6 小时以上，探针自己带病 |

**统计**：✅ 7、◐ 14、✗ 2、▼ 2。两条“未满足”（画面质感、GPU 拉满）和两条“被退化”（一致性、旧内容隔离）全部指向同一件事：**V2 出图 / 视频生产链还没接上 V1 地基**。

---

## B. 产品走查断点（新建剧本 → 看成片，以小云雀为标杆）

走查方式：按顶栏步骤条（`TopBarV3.tsx:82-89`：总览｜剧本｜资产｜分镜｜出图｜视频｜成片）逐页读源码 + 调接口。小云雀的对照基线用 `docs/xyq_walkthrough.md`（10-31 实走：出一个片段 2 次点击；分集卡直写 x/n；状态永远告诉你下一步）。

| 步 | 页面 / 接口 | 项目方能不能自己完成 | 断点 / 露技术词 / 多点 |
|---|---|---|---|
| 1 新建剧本 | `#/script-create?new=1`，`NewScriptPage.tsx:283` 提纲只写进 `/api/script-autoflow/{run}/brief` | **能**（V2-WALK W-01 双链路已合并为单一入口） | 页面仍保留“写到哪一步 / 每集镜数”等参数（`:385-395`），小云雀只要一段提纲 |
| 2 故事线闸门 | `#/queue` “等你看”组，`owner_inbox.py:37 _flow_link` 深链接 | **能**（有条目时） | 评审门槛没挡：P1 均分 < 34 仍放行（见 C-15）；项目方会看到没过门槛的稿（根因模式 ⑤） |
| 3 大纲→剧本→分镜→导入 | 全自动（派单器 + autoflow） | 不用他动 | **卡死点**：ep01 导入闸门 reopened，补丁 10 轮未过（`sop_gate status`）。`/api/script-library` 却显示“写作中 0/10，imported 0”，`/api/progress` `run:null`——项目方在网页上看不出“卡在时间轴 lint”这一事实 |
| 4 资产 | `#/assets` → `V2AssetsPage.tsx`（只读清单卡 + “修改”） | **只能改，不能看全** | `GET /api/v2/assets` `scenes:[]`（场景 sk_white_cyc 在 `/api/assets/scenes` 有，V2 页不显示）；3 个配角 looks=0；`/api/character-hub` `characters:[]`。V1 资产中心（`#/assets-v1`，4379 行）有：人物页、设定图挑选 SheetPicker、对比 CompareView、影响面 ImpactDrawer、场景上传 / 批量生成 ScenesTab、LoRA / 模板表、音色工作台 VoiceStudio——V2 页一样都没有（见 C 节） |
| 5 分镜画布 | `#ep01`，`/api/episodes` 11 镜 | 能看 | 全部格子“首帧未出”；主按钮为“出首帧”但 L-140 整集就绪 + `asset_worker.golden=false`，点了也不会出——按钮与开关口径不一致 |
| 6 出图 | `#/frames` → `/api/frames-index` | 空页 | `episodes:[]`，页面文案“缺图 / 待你看 / 尽力版 / 已定稿”（`FramesPage.tsx:4`）——“尽力版”是内部词 |
| 7 视频 | `#/videos` → `/api/videos/overview` | 空页 | `total:0`；后端 `median_s:2095.1` 来自 V1 历史 |
| 8 成片 | `#/cut` → `/api/episodes/1/cuts` / `cut-project` / `preview` | **断** | cuts 返回 `script_at 2026-10-31`（V1）；cut-project 404 文案“先装配一次：tools/assemble_series.py ep01”；preview 404 文案“手动跑 tools/assemble_series.py epNN --preview”——**错误文案直接露命令行**（根因模式 #10） |
| 9 通知中心 | `#/queue` | 能点 | 5 条全是“已自动选用…可修改”的告知（代选模式）；`master_waits` 混入 V1 对象（C-10）；文案“只放过了契约的候选”（`OwnerQueuePage.tsx:17`）——“契约”是内部词 |
| 10 图像编辑器 | `#/image-edit` | **几乎到不了** | 唯一入口是 V1 资产中心的一个图标（`AssetCenter.tsx:171`），V2 资产页和顶栏都没有；页内文案“基座列表接口还没生效（:8800 重启后出现）”“出图接口还没接上（P3）”（`ImageEditPage.tsx:57,105`） |
| 11 监控 | `127.0.0.1:8810` | 另一个网页 | 与 5173 不互链；RSI 分数“ui clean 28.6”自己也承认杂乱（`scores.jsonl` 最新 ui 行） |

**与小云雀的差距（本质）**
- 小云雀：进项目 → 分集卡写 x/n → 片段卡“立即生成 ✦60” → 视频预览就在旁边。每一步都知道“下一步是什么、要花多少、还差几个”。
- 我们：7 个一级页 + 1 个通知中心 + 1 个看板，但 V2 剧本卡在第 3 步时，**没有任何一个页面告诉项目方“卡在哪、系统在做什么、他要不要管”**。`/api/progress run:null`、剧本库“写作中 0/10”、`master_waits` 说“不需要你”——三处口径各说各话。
- 10-31 XYQ 已把每镜点击从 9 次减到 4 次（`xyq_walkthrough.md` 已实施表），这部分 V2 保住了（ReviewRow 主按钮“定稿并出下一步”），但 V2 没有一镜能走到那一步。

---

## C. V1 半成品清单（V1 完成度 → V2 现状）

| 功能 | V1 代码 / 完成度 | V2 现状（实测） | 判定 |
|---|---|---|---|
| 成片剪辑器 CUTEDIT | `CutEditor.tsx` 899 行：裁头尾（拖把手 / 输入秒）、拖拽换序、集级 BGM 换曲 / 起点 / 音量 / 淡入淡出 / 对白自动压低、字幕相对时间、原位自动保存、restore、导出（`cut_project.py:417-689` 6 个接口）。**V1 完成度约 70%**（P1 闭环做完，没有多轨 / 转场 / 波形） | 代码在、路由在（`#/cut`，步骤条 ⑤）；后端按当前剧取目录（`run_paths.renders_for_data`→`renders_root()`）；但 V2 没有视频 → `cut-project` 404，且文案露命令行 | **不是“没了”，是“到不了”**；错误文案要改成人话 + 呼吸灯 |
| 整集预览 ASSEMBLY | `tools/assemble_series.py` 按剧（`RUNS.primary_run()`、`renders_dir`，:38-40,247）；`ep_preview.py` 1 接口；`FilmOverview.tsx` 457 行 | `GET /api/episodes/1/preview` 404 露命令行；`FilmOverview.tsx` **没挂路由**（`App.tsx V3_PAGE_COMP` 无；只被 RightTabs / ReviewRow 引用） | 代码在，入口半死 |
| 图像编辑器（L-115/L-117/L-119/L-120） | `ImageEditPage.tsx` 225 行（选基座 / 参考 / 出图 / 历史 / 质检点）；后端 `image_workshop.py` 3 接口、`edits.py` 12 接口（adopt / reject / rollback / learned）、`prompt_rewrite.py`、`asset_edit.py` 9 接口。**V1 完成度约 40%**：只有 qwen21 能出图（走 `frame-jobs scope=ab`），无遮罩重绘、无“采用到镜头”的原子写（EDITOR_INTEGRATION P2/P3 未做）、其它基座“接口没接上” | `GET /api/image-workshop/bases` 200；`history?shot=ep01-S8` `items:[]`；`GET /api/edits` `edits:[]`；页面入口只剩 V1 资产中心一个图标 | **L-146 点名“V2 直接没有了”——准确说是“没有入口 + 没有数据”** |
| 资产页 | V1 `AssetCenter`（`#/assets-v1`）共 14 个组件 4379 行：PeopleHub 人物页、AssetInspector、CompareView 候选对比、ImpactDrawer 影响面、SheetPicker 设定图挑选、OwnerConfirm 一键确认、Verdict 契约结论、VoiceStudio 音色、P1Panels（LoRA / 道具 / 模板表）、ScenesTab 场景上传与批量生成。**V1 完成度约 75%** | V2 `V2AssetsPage.tsx` 1 个文件：只读 manifest 卡片 + “修改”弹框；`scenes:[]`；配角 looks 0；没有上传、候选对比、影响面、音色、场景 | **▼ 退化最严重的一页**（项目方原话“很多 v1 半成品也没有了”属实） |
| 海报 POSTER | `tools/poster/` 5 个脚本（compose / content / gen / layout），CLI 产物在 `data/posters/_v1_parked` | 前端 0 处引用（grep 只命中 `<video poster=>` 属性）；V2 无海报 | V1 本来就只有 CLI；V2 为零 |
| 8810 实时看板 | `tools/sentinel/rsi.py` 生成：GPU 漏洞榜、暂停段、按剧 24 h 出图量、RSI 分数 | 200 在线 | 在；但与 5173 不互链，且 gpu 线 95 分与全空转矛盾 |
| V1 视频库 | `#/v1-library`，`/api/v1-library` 65 镜 readonly | 在 | ✅ |
| 阅读模式 EpisodeReader | 174 行 | 没挂路由（App.tsx 无） | 死代码或待接 |
| 写作对话 `#/script-chat`、A/B `#/script-ab` | 路由在 | ScriptFlowPage 自己写“单集对话写作已下线”（`:56`），路由却还在 | 双入口残留 |
| 声音页 `#/sound` | SoundPage 155 行 | `/api/voices` 返回的是 `config/voices.json`（V1 结构，4778 B）；V2 音色在 `voices_v2.json` | 要核 SoundPage 读哪份 |
| 步骤条（L-146 新要求） | 7 个一级页 | 步骤条没有“各步完成集数”副文字（`TopBarV3.tsx:324-350` 只算当前集） | 待做 |

---

## D. 文档 / 记忆 / 账本治理：一个事实几个来源

### D1 现状数字
- `docs/` 共 455 份 .md，其中 105 份 11-02 以后改过；`docs/master/` 31 份；记忆 35 份（11-03 02:51 重建后链接全通）。
- 决策账本：`MASTER_PICTURE.md` §1 L-001…L-146（311 行，一张表混了 V1 已作废和 V2 现行）；机检 `config/owner_decisions.yaml` 87 条断言，覆盖到 L-144。

### D2 同一事实的多个来源（必须合并）
| 事实 | 来源 1 | 来源 2 | 来源 3+ | 现状 |
|---|---|---|---|---|
| 生产顺序 | `PLAN_V2_MASTER.md` §3 十阶段 | `PIPELINE_SOP_V2.md` 0–10 步 | `ALIGNMENT.md` 9 步；`sop_gate.py STAGES` 9 阶段；`V2_PLAN.md` §四 S1–S9；`docs/SOP_production.md` 418 行；`docs/WORKFLOW.md`；`docs/PIPELINE_CHAIN.md` | **7 份**，阶段数 9 / 10 / 11 各不同；代码只认 `sop_gate.STAGES` |
| 指标 / 分数 | `PLAN_V2_MASTER.md` §1.3（6 项） | `METRICS_SPEC.md`（集级） | `SCORECARD.md`（7 项到 100）、`RSI_PROGRAM.md`（5 线）、`SLO.md`（S1–S15）、`TODO_BOARD.md` 第一屏 | **5 套口径**；gpu 线 95 分 vs 实测全空转证明口径失真 |
| 计划 | `PLAN_V2_MASTER.md`（自称唯一） | `V2_PLAN.md`（L-125 版，§三 5 条“沿用 L-122 脸”已被 §〇作废但正文仍在） | `V2_READINESS.md`、`FOCUS_PLAN_20261102.md`、`NIGHT_PLAN_20261101.md`、`HOLLYWOOD_PLAN.md`、`DECISION_AUTOPIPE_20261103.md`、`ARCH_ROADMAP.md` | 8 份计划类，6 份已过期 |
| 项目方要求 | `OWNER_CANON.md`（25 条） | `docs/REQUIREMENTS.md`（“唯一准绳”，最后整理 10-30，全是林晚 / V1 内容） | `docs/owner_requirements_for_writer.md`、`owner_messages_extracted.md` 2924 行 | REQUIREMENTS 标“唯一准绳”却是 V1 内容，与 CANON 冲突；`ns-final-studio-core.md` 还让“先读 docs/REQUIREMENTS.md” |
| V2 造型集合 | `assets_v2/manifest.json:137` O1–O4 | `V2_LIVE.md` 19:0x “只允许 O1/O2/O3，不许有第 4 套” | — | 文档落后于清单 |
| V1→V2 切割口径 | `OWNER_CANON C-14` | `ns-final-studio-v2-restart.md`（带 ⚠ 纠偏） | `V2_PLAN.md §〇`（未纠偏版） | 旧口径未归档 |
| 开关 | 各 `config/pipeline/*.json` | `master_check.SWITCH_EXPECT` 种子表 | `ns-final-studio-current-state.md` “开着的开关” | 三处手工同步；switch.py 未做（L-144 延后） |

### D3 已过期、应归档的文档（建议移到 `docs/master/_archive/`，只留一行指针）
`V2_PLAN.md`、`V2_READINESS.md`、`FOCUS_PLAN_20261102.md`、`NIGHT_PLAN_20261101.md`、`HOLLYWOOD_PLAN.md`（第二季内容）、`FRAMEWORK_REFRAME.md`、`FACTORY_ARCH.md`、`TODO_BOARD.md`（11-02 17:4x 第 3 版，挂着 S1–S7 分数全过时）、`unchecked_rules.md`（11-01）、`MASTER_SELF_AUDIT_20261103.md`（并进根因模式）、`FACTCHECK_V2.md`、`V2_WALK_AUDIT.md`（结论已并入 SOP）；docs 根：`REQUIREMENTS.md`、`CORE.md`、`SOP_production.md`、`TASKS.md`、`TODO_v1_close.md`、`USER_GUIDE_v1.md`、`WORKFLOW.md`（V1 分工）。

### D4 账本本身的问题
- `MASTER_PICTURE.md` §1 混排：行序不按号（L-130…135 在 L-109 之前，L-136…146 在文件末尾另起一段无表头），⤴ 已取代 11 条仍在主表；“实测状态”列是 11-01 的实测，读者分不清哪列是现在。
- `owner_decisions.yaml` 缺 L-145、L-146；D-CLN-05 把 V1“只含 6 个场景”断言打到 V2 主剧（CARRYOVER G 表）——下一次发版闸门会被自己拦。
- 记忆与账本重复：`ns-final-studio-current-state.md` 复述 L-125…L-144 一行一条，账本改了它不会跟着改。

### D5 治理建议（“一个事实一个来源”）
1. **顺序**只留 `PIPELINE_SOP_V2.md`（人读）+ `sop_gate.STAGES`（机读），二者由测试保证一致（`tests/test_sop_gate.py` 加一条“STAGES == SOP 表的阶段列”）；`ALIGNMENT`、`V2_PLAN §四`、`PLAN §3` 改成指针。
2. **指标**只留 `METRICS_SPEC.md`（定义）+ `episode_metrics.py`（计算）；SCORECARD / RSI_PROGRAM / SLO 合并成 `SLO.md` 一份“探针表”，分数不再另算一套。
3. **账本**拆两张：`LEDGER_V2.md`（L-125 起现行，按号排序，每条带 owner_decisions 断言号）和 `LEDGER_V1_ARCHIVE.md`；`current-state` 记忆只留“看 LEDGER_V2 最后 10 条”的指针。
4. **要求**：`REQUIREMENTS.md` 改名归档为 V1；`ns-final-studio-core.md` 的“先读 docs/REQUIREMENTS.md”改为 OWNER_CANON。

---

## E. 迭代闭环：每集 = 一次系统迭代，现在能不能闭环？

闭环应是：生产 → 卡点登记 → 修进代码 / SOP → RETRO（指标对比） → 记忆 / harness 更新 → 下一集自动跑，由 harness 检查。逐环核：

| 环 | 现有部件 | 实测 | 缺口 |
|---|---|---|---|
| 卡点登记 | `report_issue.py` → `data/pipeline/issues.jsonl`（92 行） | master_check 口径“未关 20 条（阻断 11）”；`sop_updated` 填了 36 条，`code_updated` 字段**一次都没填过**（统计：56 条 None、30 True、6 False，code 全空） | “修进代码”没有落点字段，RETRO 只能靠 grep 猜（28/51 ❌） |
| 修进代码 / SOP | `PIPELINE_SOP_V2.md` 第 3、8、9 步已塞成长段 | SOP 表格单元格超过 1500 字（第 3 步），已不可读 | SOP 该拆成“前置条件清单 + 卡点史”两张表 |
| 指标 | `episode_metrics.py` → `metrics/ep01_summary.json` + `review_pages/metrics/series10_v2_ep01.html` | 已出；好莱坞分 None、阶段 A 时长 None（RETRO nulls 2 项） | 没有“和上一集比”的页面（ep01 是第一集可理解），但 `ep0A_vs_ep0B.html` 生成逻辑未验证 |
| 复盘门 | `episode_retro.py` + `sop_gate retro_enforce=true` | RETRO_ep01 draft；清单 50 项全是 `[ ]`，而且每条卡点自动生成 1–2 个勾选项——总调度要手勾 50 次 | 复盘门形式上有，实际上会被“全勾”绕过；应改为：卡点 `code_updated` 有测试文件名 → 自动勾 |
| 记忆更新 | 手工（总调度写 memory） | 11-03 02:51 重建一次 | 没有“RETRO done → 提示更新哪几份记忆”的机制；建议 RETRO 第 4 节自动列出“本集改了哪些开关 / 规则 → 对应记忆文件” |
| harness 执行 | `sop_gate`（observe：资产就绪 / 提示词 / 出图）、`master_check`、`asset_worker.filter_jobs`、`golden_v2.require` | 调用点只有 4 处（grep）；视频链调用点在 V1 脚本里（`build_jobs.py:476`、`night.py:171`） | V2 视频链不存在，所以“视频 / 整集预览”闸门目前挡的是空气 |
| 发版 | `system_version.py` cut / deploy / verify；SMOKE 5 个测试 | 最近 cut 11-02 21:04；本机 txt 停 sv-04；`decision_propagation --dry` 退出码 1（ISS-…9fcb） | 发版链自己坏着，每集收尾“发版”这一环现在走不通 |
| 探针 | SENTINEL S1–S28 | S6 每拍 AttributeError；S8 / producer 探针写死 V1 根 | 探针看不见 V2 |

**结论**：闭环的 8 个环里，**4 个有代码但对 V2 失效**（harness 视频段、发版、探针、复盘门可绕过），**2 个没有落点**（code_updated、记忆更新），只有“登记”和“指标计算”两环真正在转。还缺的三样东西，按价值排序：
1. `report_issue` 加 `--code <test_or_file>` 必填项 + 关单时校验文件存在 → RETRO “写进代码”列自动可信。
2. `sop_gate` 的视频 / 预览闸门要有 V2 调用点（随视频链按剧参数化一起做）。
3. 发版链修通（system_version.txt 本机写回、D-CLN-05 限 run、L-145/146 入 yaml），否则“每集收尾发版”永远是口头的。

---

## F. 计划建议（分阶段；每阶段：目标 / 交付物 / 验收 / 依赖）

总原则：**先把一集做完，再谈产品好看**；每阶段只允许 ≤ 3 条并行线，全部挂在关键路径上（PLAN §6 已定 ≤ 4 个代码 agent）。

### 阶段 1：第 1 集按 SOP 端到端做完（金样集）
- **目标**：series10_v2 ep01 走完 `sop_gate.STAGES` 全部 9 阶段 + RETRO done；项目方在 `#/cut` 能看到整集预览。
- **交付物**（按依赖顺序）
  1. 导入闸门过：时间轴补丁环收口（已 10 轮，若第 11 轮不过 → 总调度按 L-141 口径手改一次并把该模式写进写手包示例，不再无限补丁）。
  2. 资产缺口清零：O4 设定图（唯一缺口，`episode_ready` 输出）；3 个配角 item 作业“连续失败”的根因（同一错误登记 11 次）必须定位到代码再放行。
  3. 编译 P0 三件：近景服装（ISS-…8856）、Q1a 按剧生成人物卡（ISS-…c8c0）、`video_requires_q9=true`（ISS-…4b21）。
  4. 视频链按剧参数化：`build_jobs / vidgen / night` 读 `runs.run_dir`；`video_policy.scope` 加 V2；`prompt.py:215` / `pipeline.py:801` 传 run（ISS-…3737 / 0474）；`tools/bgm` 按剧。
  5. 出图：golden 开关打开（L-142 代选 + 总调度亲审）→ 11 镜首帧 → 尾帧 → 视频 → `assemble_series.py` 预览。
  6. `sop_gate.observe_stages` 清空（转 enforce）；RETRO_ep01 done；sv-17 cut + deploy + verify。
- **验收**：`sop_gate status --run series10_v2` ep01 当前=整集预览、复盘 done；`GET /api/episodes/1/preview` 200；`master_check` ② 阻断 0；`episode_metrics` 全部指标非 null。
- **依赖**：无（这是一切的前提）。期间**不开**任何 UI 改版、海报、编辑器线。

### 阶段 2：产品面“看得见、点得动”（对标小云雀的最小集）
- **目标**：项目方不看聊天、不看 8810，只在 5173 就知道“每集到哪、卡在哪、要不要我”。
- **交付物**
  1. 步骤条副文字 = 各步完成集数（L-146）；`/api/progress` 带 run；剧本库 / 进度 / 通知中心三处口径统一读 `sop_gate.status`。
  2. 通知中心清杂讯：`master_waits` 只算当前剧对象；pick 条目带本地审片页链接；去掉“契约”等内部词（ui 线 `no_jargon` 分项作验收）。
  3. 成片 / 预览 / 编辑器的 404 文案改为“这一集还没拼好，系统拼好会亮”+ 呼吸灯（根因 #10）。
  4. `RejectDialog` 下线；机签抽检的原因列表改为“修改”一句话（L-123）。
  5. V1 事实不进 V2 页：`readiness.continuity_sheet_path`、`cuts.script_at`、`decision-locks` 按剧过滤。
- **验收**：V2-WALK 式走查截图 11 页 0 处命令行 / 0 处 V1 对象；`scores.jsonl ui.no_jargon ≥ 95`。
- **依赖**：阶段 1 的 ep01 有数据可显示。

### 阶段 3：恢复并做完 V1 半成品（L-146 点名）
- **目标**：资产页、图像编辑器、剪辑器三件在 V2 可达、可用、不比 V1 少功能。
- **交付物**
  1. 资产页：`V2AssetsPage` 并回 `AssetCenter` 的组件（SheetPicker / CompareView / ImpactDrawer / ScenesTab / VoiceStudio 按剧读 manifest），改前先列旧功能清单逐项对照（`feedback-no-silent-feature-removal`）。
  2. 图像编辑器：进顶栏 ②资产下标签；遮罩重绘 + “采用到镜头”原子写（EDITOR_INTEGRATION P2）；其它基座要么接上要么不显示。
  3. 剪辑器：对 ep01 实际时间线跑通裁切 / BGM / 导出；`FilmOverview` 挂路由或删除。
  4. 海报：`tools/poster` 接成 `POST /api/episodes/{n}/poster`，成片页一键出。
- **验收**：每件有“旧功能清单 → 新页逐项 ✅”表；项目方在 ep01 上完成一次“修一张图 → 采用 → 镜头更新”。
- **依赖**：阶段 1、2。

### 阶段 4：文档 / 账本 / 记忆收敛（可与阶段 2 并行，低 GPU）
- **交付物**：D5 的 4 条；归档 D3 清单；`owner_decisions.yaml` 补 L-145/146、D-CLN-05 限 run；`current-state` 记忆改指针。
- **验收**：`docs/master/` ≤ 12 份现行文档；`decision_check` 0 ❌；`decision_propagation --dry` 退出 0。
- **依赖**：无。

### 阶段 5：ep02 测量集（harness 收紧）
- **交付物**：`report_issue --code` 必填；RETRO 勾选项由代码证据自动勾；`sop_gate` 全 enforce；SENTINEL S6/S8/producer 探针按剧；`system_version.txt` 本机写回；每集收尾自动 cut。
- **验收**：ep02 指标对 ep01：自动化 ≥ 60%、介入 ≤ 20、GPU ≥ 40%（PLAN §1.3）；ep02 开工到整集预览期间总调度手工命令 ≤ 5 次。
- **依赖**：阶段 1、4。

### 阶段 6：ep03–ep10 自治集 + 结构化控制 A/B（L-143）
- 按 PLAN §5；每集 RETRO 自动生成、总调度只看 `master_check`；IMGLAB 四类逐项 A/B，指标不升不留。

---

## 附：本次审查实测清单（可复跑）
- `curl :8800/api/{episodes/1/cuts, episodes/1/cut-project, episodes/1/preview, frames-index, videos/overview, v2/assets, assets/scenes, character-hub, owner/inbox, owner/delegate, readiness?ep=1, decision-locks, factory/health, image-workshop/bases, image-workshop/history?shot=ep01-S8, edits, progress, script-library, script-autoflow/series10_v2}`
- `python tools/master/sop_gate.py status --run series10_v2`；`python tools/master/master_check.py`；`python tools/master/episode_ready.py --run series10_v2 --episode 1`
- 源码：`apps/web/src/App.tsx`、`v3/TopBarV3.tsx`、`v3/pages/{OwnerQueuePage,CutPage,CutEditor,ImageEditPage,NewScriptPage,FramesPage,VideosPage}.tsx`、`v3/assets/{V2AssetsPage,AssetCenter}.tsx`、`v3/ReviewRow.tsx`；`services/api/ns_api/{cuts,cut_project,ep_preview,image_workshop,edits,run_paths,owner_inbox}.py`；`tools/master/*.py`；`config/pipeline/{sop_gate,agent_dispatcher,owner_delegate,asset_worker,runs}.json`；`assets_v2/manifest.json`
