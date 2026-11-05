# V2 单集生产 SOP（流水线顺序与前置条件，会持续补充）

> 项目方 11-02 23:3x 原话：“现在发现任何问题，都要先通告给 master agent，让他知道现在的情况，并把流水线的顺序细节都填上。这样在下个 episode 的时候，就能把这些细节补上去，就不会每次都卡在那里了。这是我们的目标。”
>
> 规矩：
> - 任何 agent 或系统步骤卡住、发现缺口，先登记到 `data/pipeline/issues.jsonl`（工具：`tools/master/report_issue.py`），同时通告总调度；
> - 总调度确认后，把这条经验写进本文件对应步骤的“前置条件”，并做进 `tools/master/episode_ready.py` 的自动检查；
> - 每集开工前先跑一遍 `episode_ready.py`。缺的东西一次性列出来，提前补齐，不在半路卡住。

## 顺序

| # | 步骤 | 谁做 | 前置条件（来自过往卡点） | 卡过的地方（日期 / 原因） |
|---|---|---|---|---|
| 0 | 剧级准备 | 总调度 | runs.json 登记了这部剧；CLEAN_CUT.json；资产包清单 manifest；风格四件（调色 / 运镜 / 配乐 / 音色）已选定 | — |
| 1 | P1 故事线 + 造型表 | 写手（Fable）→ 三评委 | 评委由总调度派（看 judge_request.json）；证据必须是原文 | 11-02 评审交齐后没自动汇总（W-20，已修） |
| 2 | 项目方闸门 P1 | 项目方 | 待办通知中心有这一条 | 11-02 escalate 之后 verdict 没同步（W-38，已修） |
| 3 | P2 单集大纲 → P3 剧本 → P4 分镜 | 写手 | 运镜只用 camera_moves.yaml 里 enabled、并且 runs 包含本剧的运镜；正文不留占位词 | 11-02 QW-C1 词表和 camera_moves 是两份（已修成单一来源）；11-03 全局头仍从 V1 导入稿推导，P4_ep01.final.md 带了 121 行 V1 头（林晚 / 顾沉 / lnwan01 / V1 场景表）；写作规则里手写了含 pan / truck 的旧运镜清单（HEADER-O 已修：全局头只按本剧 P1_storyline + P1_looks + 资产包清单推导，缺数据直接报错不回退 V1；通用写作规则 / 知识包 / 示例改成通用写法（女主 A / 男主 B），V1 专属条款移到 config/script_chat_runs/series10_v1*.md 按剧注入；非 V1 剧写手包出口出现 V1 id 即失败（只检查不改写）；运镜表按 camera_moves.yaml 自动注入；tests/test_header_o.py）；11-03 项目方“MiniMax 提示词的运动要有时间轴”：sysimpl-v2 时间轴只在 timing_lint.json 切 error 时才拦，V2 第 1 集 11 镜全部带病导入（RL-T5 开头衔接 11/11、RL-T3 拍内视线 8/11、镜6 H3 3 拍对 **分拍** 4 拍）（TIMELINE-O 已修：V2 / 新剧一律 strict（shot_spec.run_strict，legacy_runs 只留 V1）；写手包按剧注入【本剧时间轴硬规则】（script_chat.timeline_block）；**分拍** 每拍必写 运镜=（SS-M8）；tests/test_timeline_o.py）；11-03 03:2x L-141：At MM:SS.mmm 只用于切镜，镜内分拍改写自然英文 In the first two seconds… / Then, around the third second… / … as the shot ends（RL-T8 拍序拍数对 **分拍**、RL-T9 镜内不许 At / 切镜必须 At 且递增）；补丁环 I2 集头误判修复（之前采用过造型行补丁的集，后续补丁不再卡 I2） |
| 4 | 事实表 / 事实核对 | FACTCHECK（看 review_request.json） | — | — |
| 5 | 补丁环 | 写手 | 补丁可以改集头的“造型｜人名”行；每轮最多 14 行 | 11-02 写手交了整集稿，不是补丁（已修：等补丁期间不收整集稿） |
| 6 | 导入 | 系统 | 导入路径必须在本剧 run 目录下 | 11-02 V2 成了主剧后走了老的收件箱接口，返回 404（已修）；11-03 导入关口不查 H3 时间轴（TIMELINE-O 已修：p4_adapter.check_p4 按镜合成 [TL-<镜>] 阻断（RL-T1–T8 + SS-M1/M2/M5/M6/M8），补丁环每镜一个目标、只许改该镜 **分拍** / **表演节拍** / H3 正文行（autoflow_agent.timeline_check）；编译器 build_base 缺时间轴 / 与分拍对不上 → needs_writer“缺时间轴”，不静默编整句；导入闸门前成稿集头按 script_header(run) 重生（旧稿隔离到 data/_quarantine/header_regen_<日期>/），成稿出现 V1 id（assert_no_v1）→ 闸门 blocked）；11-03 MERGE-VID-O（L-137，总调度裁定）：V2 单镜 >6 秒（QW-T1）/ 运镜不在本剧词表（QW-C1）= 硬阻断，check_p4 的 rep.hard_blocks 非空 → non_tl_blocking 返回 99，新稿不收；已收的集单镜超 6 秒 → 系统出“缩短镜长”补丁（autoflow_agent.duration_patch，目标 dur#<镜>，排队规则同运镜包）：只许改该镜 **时长**（往下改到 ≤6 秒）和 **分拍** / **表演节拍** / **台词时段** / H3 时间轴行，镜数、镜号、台词不变（duration_check）；写手判断压不进 6 秒 → 交 {"cannot_fit": 原因}，系统登记卡点交总调度决定是否拆镜 |
| 7 | 成人标记 | 系统（compiler） | 妆容 / 颜色类的“裸”不算成人 | 11-02 “裸妆 / 裸粉美甲”被误判成成人镜（已修） |
| 8 | 资产就绪（出图前） | **系统自动（阶段 A 资产作业，M-AUTOPIPE-01）** → 项目方只在待办通知里点“用这个” | 本集出场的每个人都有身份脸，manifest 里有 display_name；本集的造型排期已经写进 hub_episode_looks.json（和 P1 排期一致）；本集用到的单品图都有 file 和 sha256（SH1 要从 O4 原图裁出）；本集用到的每个场景都有底图；本集说话的每个人都有选定的音色；**造型确认属于资产阶段**：要等身份脸选定以后，网页“确认造型”入口才出现（SOP 造型动作带 asset_ready，口径 = episode_ready.character_gaps 同一份代码；之前只显示一句“X的形象还在出候选，选定后再确认造型”，不露命令行）（UIFIX-F 11-03） | 11-02 第 1 集：lead_f 没写 display_name、O4 没有 sheet、sk_white_cyc 没有底图、卓琳 / 唐瑶 / 江予白没有身份脸、卓琳 / 唐瑶没有音色；GOLDEN-S 补记（tools/master/report_issue.py 还不存在，先写这里）：①出图前必须先做本集造型排期（POST /api/character-hub/{cid}/schedule），否则剧本造型行和清单造型名文字对不上（script_match 0.35），I3 报“造型对不上 P1 登记”，O4 并不缺 sheet；②清单单品要接进造型才算数：SH1 要从 O4 原图纯裁剪（assets_v2/characters/lead_f/shoes/shoe_SH1_clear_pointed_heels_crop.png，原图 sha 与裁剪框写在 manifest SH1.note），再把 SH1 挂进 looks.O4.items，manifest_looks 按单品 slot 挂成鞋部件，I4 才过；服务器要部署 asset_refs.py 这个改动才一致 |
| 9 | 金样首帧 | **系统自动（阶段 B：第 8 步全部就绪后自动生成 golden-epNN 作业；本轮只生成，执行由 golden 开关接）** | 第 8 步全部通过；契约（Q1 / 服装 / 提示词 / 人数 / Q9 / OCR / brand_logo）全部通过 | 11-02 Q9 视线判定的证据和结论矛盾（已修）；11-03 镜头带 scene_id 时【幻想段】经“本镜场景：”漏进出图提示词（ISS-1103-005241-bf53，已修：段落标记只给调色和元数据用，编译器出口 compiler._no_segment_marks 统一清掉；测试 tests/test_promptfix_v2.py::test_l130_segment_marker_never_in_prompt）；11-03 MERGE-IMG-O（L-137）：近景一体件（抹胸裙）整句被删 → 只删看不见的单品、全身装 zone=body；露脸且服装入画却没有造型设定图 → I3 fail（资料不齐不出，前置：先出设定图）；三人镜脸板逐格认人（I2 / I9）；Q1a 人物卡按剧从 P1 生成、Q1 主角线按本剧 lead；作业负面词不再被覆盖；设定图不加朝向视线句；镜头语言 v2（构图 / 灯光取导入稿 extras，前置：导入器带上这些字段，ISS-1103-031008-8c50）；导入器已把 构图 / 灯光 / 镜头 归到本镜 extras（改后要重导一次）；L-147 V2 定稿档自动开；L-148 后缀只留质感、灯光以剧本为准；L-149 镜头句 + 融合句开；episode_ready 设定图口径 = preflight.sheet_gaps（ISS-1103-030746-664a） |
| 10 | 尾帧 → 视频 → 整集 → 配乐 / 配音 → 成片 | 各线 | 配乐只从 music_v2.json 取；音色只从 voices_v2.json 取 | — |

## 第 8 步怎么自动走（阶段 A 资产作业，AUTOPIPE-A 11-03；代码 tools/pipeline/asset_jobs.py + asset_worker.py + asset_checks.py）

1. **发现缺口 → 作业**：导入成功后 autoflow.ready_after_import 跑 episode_ready，每个缺口生成一个作业文件 `data/pipeline/asset_jobs/<run>/<job_id>.json`（同一缺口只生成一个，幂等）；常驻服务 autoflow_resident 每拍也会再生成一次（每 ready_every_s 秒或登记后强制）。
   作业类型：`face-<cid>`（身份脸候选）、`scene-<sid>`（场景底图候选）、`sheet-<cid>-<look>`（配角造型设定图候选，总调度 11-03 已批；身份脸登记后才派）、`voice-<cid>`（音色候选，voice_v2 --roles-file）、`item-…`（单品图：清单里有裁剪规则就裁，否则出候选）、`meta-name / meta-looks / meta-schedule-<cid>`（display_name / 造型骨架 / 造型排期：直接从 P1 写入，不用项目方挑）、`golden-epNN`（阶段 B）。
   别的 agent 已经投过的 pick（例 CAST-S 的 `v2cast-<对象>`）：作业直接接管为 awaiting_pick，不再出候选。
2. **执行器**（常驻服务每拍调 asset_worker.tick，单实例锁 worker.lock，只处理 runs.json 状态 preparing / active / producing 的剧；开关 config/pipeline/asset_worker.json：apply_meta / render / voice / push / golden，默认除 push 外全关）：
   - face / scene / sheet / item：唯一编译入口 frame_job.build_first → preflight **设定候选模式** → 借道出图 → postflight + Q9（设定候选口径）+ 人数（anomaly）+ **一次合并看图**（逐条核对 + 年龄观感 + OCR，asset_checks.bundle_check）→ 全过的才拷进 `data/review_pages/v2_assets/<run>/<job>/` 并投待办通知；
   - 借道：空闲道 = 车道表 image 道 − exclude_lanes（gpu33:2 / gpu36:2）− 别人 hold / lend / 挡着的道 − ComfyUI 队列里有活的道；每道 `lanes.py hold --by ASSET-WORKER`，每道一个子进程、最多 max_parallel 个并行，用完 `release --by ASSET-WORKER`（收尸时再放一次，幂等）；
   - voice：子进程跑 voice_v2 plan → push → design（gpu36 CPU）→ clone → pull → check → page --roles（登记 support_candidates）→ 投 `pick:voice_v2:<role>`；
   - 失败：attempts < max_attempts 下一拍重排；用完登记卡点（ASSET-WORKER）。
3. **设定候选模式（preflight，规则写死在 gen_contract/preflight.py ASSET_STAGE_WAIVE）**：作业显式写 `mode="setting_candidate"` + `asset_stage`，才按表把“本作业要产出的那项”判 na（detail 保留原判）：face → I2、I3；sheet → I3、I4（I2 照查；设定图是这套造型的源头产出，ISS-1103-013228-cab4 总调度定 A）；scene → I5；item → I3、I4；其余各项照查；asset_stage 不认识 = I2 fail（失败关闭）。不再允许脚本自己豁免（cast_v2 已改走这个模式）。
   **AUTOFIX-O 11-03 补的规则**（OVERSIGHT-A 复审 ISS-1103-004546/6260/ca20/cb05/8787）：
   - 登记取剧：作业（find_job_by_pick）的 run 优先，其次请求的 run；都没有 / 不一致 / 没登记 = 失败关闭，绝不回退 current_run()。
   - sheet：该角色身份脸已在清单（file + sha256 对得上）才派；出图前按 sha 核参考里确实送了这张脸，否则不出（核的是实际送出文件的完整 sha256；compile_trace.refs[].sha 只有 16 位，不能拿来比）。
   - sheet 登记后：按 P1_looks 这套造型的部件（asset_refs.parse_parts，与 I4 同口径；“无”跳过）自动生成 `item-<cid>-<look>-<slot>N` 作业 → 子进程 run-crop 从设定图按部件区裁（人物外框 × 区带，SH1 纯裁剪做法，记框与源 sha）→ 本地看图 + OCR 过了直接登记 looks[look].items + item_map_overrides 部件映射并推两台，不用项目方挑；裁不出来 / 不过 → spec.crop_failed，改走出候选投待办。
   - **派生资产自动选用（总调度 11-03；L-139 项目方 03:1x 拍板：只在代选模式开着时）**：sheet（设定图）和 item（单品图 / 裁图）是派生资产——身份脸是项目方选的、造型文字是项目方放行的 P1。**只有代选模式开着且没到期**（asset_jobs.delegate_active → ns_api.owner_delegate.active；载不进来读 config/pipeline/owner_delegate.json）时才自动选用；平时（代选关着 / 到期）一律投 #/queue 等项目方挑（裁图 = 1 个候选“确认”）。代选开着时：候选过检后系统按分数（身份余弦 Q1 sims + 看图逐项通过率）自动登记最好的一张（picked_by=“系统自动…”），inbox 只发一条“已自动选用，可修改”的告知；项目方点别的候选 = 换成那张（register_pick 只允许替换系统自动选用的条目），旧设定图派生的单品移到 items_replaced、对应 item 作业改指新设定图重新排队。规则上线前已投成待选的 sheet / item，下一拍自动选用。**身份脸、场景底图、音色**这类新的创作选择仍由项目方挑。
   - 设定图看图只核大件（P1_looks 单品层级：outfit / shoes 部件；饰品、腕带、指甲等小件是 item 作业的事）；每张候选的拒因汇总写进作业 error / log；Q9 没拿到看图结果（排队 / 没跑）= 同步再要一次，仍没有就重排（不算失败）。
   - 缺口已不在的 pending / failed 作业（本集独有、由缺口生成的 face / scene / voice / sheet / meta）自动收尾为 done（closed_reason），同类缺口规划失败时不收（ISS-1103-011049-336c）。
   - Q9 设定候选口径：看图模型只在本阶段不判的项（sheet / face 的 eye_contact）上结论矛盾 → 按其余缺陷重判，不再 untested。
   - 资产包文件名只许 [A-Za-z0-9_.-]（asset_jobs.safe_name；# 会在 /files/ URL 里截断）；旧名迁移用 `asset_jobs.py normalize-names --run <剧>`（sha 不变、原件进隔离区、推两台）。失败作业重排用 `asset_jobs.py requeue --run <剧> --job <id>`。
   - scene / item：不用人像风格后缀，整句换成空镜后缀（时间 / 光线取 P1 场景表，带人的半句剔掉，句尾 = style.EMPTY_SUFFIX），负面写明不出现人物；I7 在这两种模式只认空镜后缀。
   - 外壳：设定候选一镜分镜用 asset_jobs.setting_script（V2 中性外壳），不许再用 V1 夹具 frozen_v1_subset.json。
   - P1 人物：年龄缺 / zh_look 不是六段 = 不出图（不生成“0岁”，色彩基调不进脸的描述）。
   - 试跑 / 测试：真实仓库只认 runs.json 登记的剧（asset_jobs.guard_run）；子进程按作业文件所在数据根干活（--root）；测试里起真实子进程直接报错；真实 voice_v2 链只在真实仓库跑，已选定的槽不再出候选、不写回 support_candidates。
   - replay：API 启动时放后台守护线程（总时限 REPLAY_TIMEOUT_S，到点剩下的 deferred 留下次）；补执行占位超过 REPLAY_STALE_S 没收尾 = 陈旧，可重补（CLI `owner_pick.py replay --stale-s=60`）。
4. **Q9 设定候选口径（asset_checks.q9_asset）**：face / sheet 是证件式近正脸胸像 / 全身设定图，接受视线偏一侧，“看镜头”（eye_contact）不判；其余缺陷按 config/vqa.json blocking；未成年外观（underage_look）任何时候都不过；没有 Q9 结果照旧不算过。
5. **通用检查**：`tools/pipeline/asset_checks.py age|ocr|bundle <图>`（只进本地看图模型，K-REV-V01）。
6. **投递**：统一 `owner_pick.enqueue_pick(root, req)`（同 id 替换；detail 用 owner_pick.pick_detail 模板），候选带 file / thumb / sha256 或 audio。
7. **选定 → 登记**：POST /api/owner/pick 按 kind 分派：face → 清单 characters[cid].face（file + sha256 + picked_by，display_name 没有就从 P1 补）；scene → scenes[sid].base；sheet → looks[look].sheet；item → looks[look].items[id]；voice → voices_v2 roles。已有的不覆盖（带原因重现）。推两台用 sync.verified_install（服务器端核 sha 再原子替换；失败登记卡点不回滚，FACTORY sync auto 每 10 分钟补推）。处理器上线前项目方已点过的：owner_pick replay（API 启动 / `owner_pick.py replay`）按 decisions.jsonl 补执行。
8. **登记后**：READY_HOOK → 作业 done → 重跑 episode_ready → 全部就绪写 `golden-epNN`（阶段 B 作业，spec.executor = golden_v2 --shot N；执行待 golden 开关）。

## 下一集开工前要确认（episode_ready 自动检查）

- 本集出场人物：身份脸、display_name、别名都齐
- 本集造型：本集造型排期已写进 hub_episode_looks.json，且 preflight 口径的 I3 / I4（造型登记、单品图）都过（不再单独查 sheet）
- 本集场景：底图都已选定
- 本集说话人：音色都已选定
- 本集镜头：adult 标记已重算，没有误判
- 缺口 → `data/pipeline/asset_jobs/<run>/` 里每个缺口一个作业（asset_jobs.py list --run <run> 能看到），没有卡在“等某个 agent 手工出候选”

## 按集流水（EPCHAIN-O 11-03，项目方 02:1x：ep01 做完做 ep02，最终 100% 全自动）

- 第 N 集导入成功（autoflow_epNN.json `verdict=imported`）后，常驻服务下一拍（≤30 秒）自动开第 N+1 集：推进一次即出 P2 包，到 P1_storyline 最后一集为止。
  只看写作状态，第 N 集出图不挡第 N+1 集写作。入口不变：`tools/factory/autoflow_resident.py` → `autoflow.pending_done()`（内含 `next_episodes()`）→ `autoflow.py run --source daemon`，每集一把 `work_epNN/advance.lock`。
  P1 闸门 / 项目方闸门规则不变（P1 没“用这版”，packet() 不出 P2–P4 包）。
- 每段一行计量：`data/pipeline/runs/<run>/metrics/epNN.jsonl`（格式 docs/master/METRICS_SPEC.md §A）。

## 派人请求（总调度按这里派 agent）

每个写作包 / 评审包 / P1 评委轮一出，系统写**一条请求一个文件**：`data/master/inbox/requests/<run>__<id>.json`（多集、多步同时排队，互不覆盖）。
旧的单文件 `judge_request.json` / `review_request.json` 仍写（只留最近一条，兼容），以 `requests/` 为准。

格式 `nsfs.dispatch_request/1`：

| 字段 | 含义 |
|---|---|
| run / id | 剧 / 请求 id（`<step>_a<k>`，评委轮 `judge_p1_r<n>`） |
| kind | `writer`（写手）/ `reviewer`（事实表、事实核对）/ `judge`（P1 三评委） |
| episode / step / attempt / link | 第几集、哪一步（P2_ep02、facts_ep02、patch_ep02…）、第几次、写作链段 |
| packet | 写作包路径（writer_tasks/<step>_a<k>.json）；评委另有 `packets[]` |
| output / done_marker | 交稿路径和 .done 路径；评委为 `outputs[]`（每位 judge_j/out/p1_review.json） |
| suggested_model | 建议模型：写手 `fable`，评审 `sonnet`；评委 `suggested_models` = `sonnet / haiku / opus`（三位不同） |
| must_differ_from | 评审 / 评委不能用的模型（= 写手模型 `fable`；写和评不能是同一个模型） |

派人规矩：交稿写到 `output`，再建 `.done`；`.done` 第 2 行写 `model: <实际模型 id>`（例 `model: claude-fable-5-1`，METRICS 记实际模型用；不写就按建议模型记）。不要自己跑推进命令，系统下一拍自己接。

只读列出待处理请求（包还在、没作废、`.done` 还没建）：

    .venv/Scripts/python.exe tools/master/pending_requests.py            # 表格
    .venv/Scripts/python.exe tools/master/pending_requests.py --json     # JSON
    .venv/Scripts/python.exe tools/master/pending_requests.py --all      # 含已交稿 / 已作废

派单器（tools/factory/agent_dispatcher.py，L-138 已开）：写手经一次性启动器起（DETACHED + 新进程组 + CREATE_BREAKAWAY_FROM_JOB），不在 resident 进程树里；重启 resident（ops/restart_autoflow.ps1 的 taskkill /T）不会带走在跑的写手，新 resident 按 data/factory/agent_dispatcher/state.json 的 pid + 创建时间接回，不重排（ISS-1103-033131-1efe，tests/test_agent_dispatcher.py::test_resident_restart_does_not_kill_or_requeue_writer）。

## ep01 收尾阶段的项目方决定怎么落进流水线（L-186…L-192，AUDIT-RULES 11-05 补；原文 docs/master/MASTER_PICTURE.md §1 末尾，机检 config/owner_decisions.yaml D-V2-187…192c）

| 决定 | 流水线里的落点 | 状态（11-05 16:4x JST） |
|---|---|---|
| L-186 整集 ≥60 s：写作时长目标按**剪后**算（剪前 ≈ 目标 ÷ 0.7），QW-T 时长检查改为预估剪后时长；节奏规则不放松 | 第 3 步写作：writer 规则 + tools/qa/writer_lints.py 的 QW-T 时长检查 | ⏳ 规则级修法还没写进 writer 规则 / QW-T（只做了 ep01 补镜 S12–16）；归 CODER-LENS（writer_lints / writer_camera）下一轮 |
| L-187 L-183 自动“尽力取最高分进片”改开关、默认关 ⤴ **已被 L-196 修订（11-05 20:2x）：review_adopt_auto=true，用尽自动采用最好一版** | config/pipeline/producer.json review_adopt_auto=true（CODER-AUTO）；项目方事后仍可在 #/queue“修改” | ✅ D-V2-187（已改为 L-196 口径） |
| L-188 L1 画风基线：有动机主光 + 光比 ≤3:1 + 负补光 + 背景低 1–2 档、禁平光句；sk_white_cyc 低调底图 1104；多人三层站位；post_film 开 / 关 USM；祁念短款裸粉甲 | K-WRT-807/808/809 + QW-L1/L2 阻断；run_style.json lighting_en；render_quality post_film；P1_looks | ✅ D-V2-188 / 188b；🟡 run_style.json lighting_en.fantasy 仍写 “warm ring light … from the front right” —— 幻想段按 L-130 幻想 C 高调暖金可以高调，但“环形灯 / 正面”是 L1 明令关掉的灯（H3a 6/6 关着才算过），建议改成有动机暖主光（CODER-PT 文件，待其改） |
| L-189 KPI 改“画面指数”（bg_lum↓、subj_bg_ratio↑、dof_ratio↑、halo↓）+ 亲看抽检；VLM 只做单图缺陷 | tools/imglab/picture_index.py + tools/sentinel/scorecard.py v2（CODER-SCORE） | ✅ D-V2-189 |
| L-190 发版 / 部署交 release_tick 自动（一次授权） | config/pipeline/release.json enabled=true；请求 data/system_versions/release_request.json（list 或 manifests） | ✅ D-V2-190；注意 tick 跑在 resident_sync loop 里 |
| L-191 ep01 首帧 35 步 base 定稿档 + 人数闸；过肩 / 俯拍等机位不靠文字 | render_quality.json first_frame_tier.runs.series10_v2=base35（作业签名带档位）；Q10 visible_people 闸随 base35 自动开；K-REN-124 已改为只限 V1 | ✅ D-V2-191 |
| L-192 ① 运镜白名单 6 种（static / push_in / pull_out / bolt_push_settle / handheld_follow / pedestal_up）；truck / arc 方向反写 + 中档幅度复测后项目方看样片再开；双人镜只用推 / 拉 / 固定 / 手持 | config/director/camera_moves.yaml enabled + multi_person_moves + camera_norm.multi_person_fallback；H3 官方写法运镜句 = run_style.json prompt_template.video=v2（默认 v1，待开） | ✅ D-V2-192a/b；🟡 multi_person_moves 里多了 bolt_push_settle（PS-MASTER 审 dump 后加，属推近类）—— 项目方原话是四种，开 v2 前请项目方确认 |
| L-192 ② 构图“先摆位再出图”：3D 摆位 → 深度 / 姿势控制图 → Qwen-Image ControlNet；S4 先试 3 版 | tools/previz（CODER-PV 的 blocking 摆位脚本 + 3 份 S4 摆位 JSON），ControlNet 模型经 hf-dl；生产 workflows.py 仍不含 ControlNet（D-V2-143 注明 L-192 ② 修订路径） | ⏳ S4 3 版出图中 |
| L-192 ③ 焦段光圈表（建立 24–35mm T2.8–4 / 双人 40–50 T2 / 过肩单人 65–85 T1.4–2 / 特写 85–135 T1.2–1.4 / 物件 100 微距）、背景须有远处实景光源、⤴ L-192 取代 L-002 旧“85mm f/1.2 奶油虚化”后缀口径（仅 lens_sim 光学标定用 f/1.2，不是出图提示词后缀）：lens_sim 按 85mm f/1.2 重标定 | K-WRT L3 条（QW-L9/L10/L11 warn）+ run_style.json lens_table 兜底 + lens_sim_v2 | ✅ D-V2-192c；🔴 **冲突**：K-WRT-812（L2 焦段“全集只用三档 35 / 50 / 75，特写 = apo_summicron_75_f2”，QW-L4）与 L-192 表（特写 85–135）互相矛盾，config/director/lenses.yaml 没有 85 / 100 / 135 档且光圈（f/2–2.8）低于表 → 按 L-192 改 K-WRT-812 档位与 lenses.yaml（加 Summilux-M 90 f/1.5 等效 85–90、APO 135），CODER-LENS 文件，待其改 |

### 11-05 晚追加（L-193…L-196 + 运维教训，RULES-1105 补；规则层 K-OPS-I11…I14 / K-OPS-D05 / D06 / K-REN-963 / K-REV-807，机检 D-V2-191b…196b、D-V2-OPS-I11）

| 决定 | 流水线里的落点 | 状态（11-05 20:5x JST） |
|---|---|---|
| L-193 首帧跨两台：gpu33 producer 经 lane_relay 借 gpu36 道出首帧（笔记本白名单代理 + ssh -R，只放行 ComfyUI 出图接口）；视频按镜跨两台同时开 | config/pipeline/lane_relay.json enabled=true、lanes=gpu36:0/1/2（笔记本 `lane_relay.py serve` 由项目方亲启；producer 重启后读）；config/pipeline/video_shard.json enabled=true；阶段交接写 data/pipeline/lane_relay_hold.json 还道 | ✅ D-V2-193 / 193b / 193c / 194d |
| L-194 可用 6 卡 = gpu33:0/1/3 + gpu36:0/1/2（gpu33:2 坏卡）；按阶段全卡集中，无闲卡；看图集中 gpu33:3 本机实例；gpu36:2 不再看图专用（修订 L-100） | config/factory/hosts.json gpu36:2 enabled + roles=[image, video]（ComfyUI :8190，隧道 gpu36-l2）；video_shard ep01 权重 gpu36:gpu33 = 3:2；K-OPS-I12 | ✅ D-V2-194 / 194b / 194c |
| L-195 提示词阶段按镜判：过关的镜先出图，没过的镜单独卡住（取代 L-140 整集就绪才出图；asset_worker 并行回 2 不变） | config/pipeline/sop_gate.json whole_episode_prompts=false（sop_gate.judge 按 shot 取证据）；K-OPS-D05 | ✅ D-V2-195 |
| L-196 全自动：首 / 尾帧闸门只留硬项（Q1 身份 / 人数 / 无字幕水印 / 成人安全），Q9 / QB / Q10 看图类只记录不挡（⤴ 局部取代 D-VQA-01 “看图复核闭环 enforce”：看图照跑照记、next_prompt 不再触发重出；未成年外观 / 成人安全仍挡）；重出用尽自动采用最好一版；总调度只看 episode_run 报告 | config/gen_contract.json blocking_items=[Q1, count, text, adult]（gen_contract/blocking.py）；producer.json review_adopt_auto=true、accept.run_qb=false（CODER-AUTO）；K-OPS-D06 | ✅ D-V2-187 / 196 / 196b |

#### V2 首帧生产配方（单一来源 K-REN-963；改任何一项先改规则再改配置）

| 项 | 现行值（series10_v2，11-05） | 文件 | 机检 |
|---|---|---|---|
| 提示词模板 | image=v2 / video=v2（机位首句置前、去【角色】块、人物一行、按露脸人数写同框；H3 官方运镜句紧跟构图句） | config/compile/run_style.json runs.series10_v2.prompt_template | D-V2-191c |
| 出图档位 | base35 = unet base / 35 步 / cfg **3.0** / euler simple（cfg 小批：2.0 无改善、1.5 画面变平 → 不降 cfg，身份靠换种子 + 模板 v2） | config/render_quality.json first_frame_tier | D-V2-191 / 191b |
| 焦段 | 分镜【光学】行 > 【镜头】id > lenses.yaml by_kind：建立 28 T2.8 / 双人 50 T2 / 过肩单人 85 T1.4 / 特写 135 T1.2 / 插入 100 微距（L-192 ③） | config/director/lenses.yaml、ns_schema.prompt_v2.lens_of | D-V2-192c |
| 人数 / 身份闸 | 硬项只有 Q1 身份 + count 人数 + text + adult（L-196）；过肩前景只露肩 / 背影的人不算露脸（K-WRT-H16 修订，staging._face_hidden = prompt_v2.hidden_face） | config/gen_contract.json blocking_items；tools/script_rsi/staging.py | D-V2-196 |
| 背影判定 | 只认 背影 / 背面 / 背身 / 背对镜头 / 背朝镜头，按小句主语归属；“背脊 / 后背 / 背对他”不算（K-REV-807） | services/agent/ns_agent/asset_refs.py back_in_text | tests/test_rules_1105.py |
| 机位 | 过肩 / 俯拍等不靠文字：L-192 ② previz 摆位 → 控制图 → ControlNet（tools/previz，S4 三版已验可行；接入生产前 S4 仍走文字） | tools/previz | D-V2-143 注 |
| 道 | 首帧阶段 6 道：gpu33:0/1/3 本机 + gpu36:0/1/2 经 lane_relay（L-193 / L-194） | hosts.json / lane_relay.json | D-V2-193… |

### 当天验证有效的运维规矩（已写进 knowledge/rules/ops_infra.yaml K-OPS-I08…I14）
- **deploy 改了派单相关配置 = 立刻紧急重启 producer（K-OPS-I11）**：hosts.json / lane_relay.json / sop_gate.json / gen_contract.json / producer.json / render_quality.json / run_style.json / video_shard.json 任一相对上次部署有改 → `system_version.py deploy` 自动把重启请求升 urgent（只改配置 → producer-only，night 不动；同版还改了代码 → all），不等 30 分钟重启间隔（20:00–20:15 gpu33 producer 没读到 cut O 的 gpu36:1/2 借道与 L-195，道空着）。
- **新稿导入 / 换代后立刻 probe-prompts（K-OPS-I13）**：episode_run 的 regen 段已自动跑；手工 `producer.py import-staged` / `regen` 的人必须紧接着跑 `tools/master/sop_gate.py probe-prompts --run <剧> --episode N`。sop_gate.require_backoff 每次先 judge 再看退避，证据刷新即放行，不需要手清退避（tests/test_rules_1105.py）。
- **交给项目方亲手执行的命令给 PowerShell 工具语法或脚本（K-OPS-I14）**：不给带 `$_` / `$VAR` 的 Git Bash 一行命令（20:03 lane_relay 旧进程没停、新进程又起）；WSL 侧 stdin 管进去（K-OPS-I09）；时间一律 TZ=JST-9（K-OPS-I10）。
- **转发器父子 = 一份服务**：.venv\Scripts\python.exe 是 venv launcher，再起 Python312 子进程；resident_sync / monitor / sentinel 各“两份”实为一份。盘点用 `python tools/ops/proc_instances.py`，不按解释器路径杀。
- **wsl.exe 会再展开 $VAR、MSYS 会转换 /mnt/c 路径**：WSL 侧脚本从 stdin 管进去（`wsl.exe -e bash -s < x.sh`），Git Bash 调 wsl.exe 前 `MSYS_NO_PATHCONV=1`。
- **时间一律 JST（TZ=JST-9）**：笔记本时钟美东；system_version.ENV / release_tick / cut_deploy_*.sh 同口径；Git Bash 取时间用 `TZ=JST-9 date`（`TZ=Asia/Tokyo` 退成 UTC）。
- **deploy 后本机也写 data/system_version.txt**（之前只写服务器，本机工具读到 11-02 旧版本）。
