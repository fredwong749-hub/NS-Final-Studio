# UIUX-LOOP 轮回审查日志（11-06，worker UIUX-LOOP）

项目方：“uiux 那边的也很多问题，你多开个 agent 去修，同样用轮回审查逻辑，一点点修复”。
每轮：① 打 UI 用到的 GET 接口（只读）+ 对照页面代码 → ② 改最小正确的一处（后端算状态、单一活来源）+ 测试 → ③ 复测 + 记录。
不重启服务、不发版、不提交、不写服务器。改动只在 services/api、apps/web、tests。

## 第 1 轮（11-06 18:06 JST）状态来源错：总览把 ep01 每镜标成“已重置 / 驳回待重出 / 过期”

- 证据（改前）：GET /api/frames-index?ep=1 → ep01 S1–S8 main=`redo`“已重置 / 驳回待重出”、S9/S10 `stale`“过期”；而 brain 快照 / 出图机登记表：首帧 16/16 过、尾帧 12/16 过、视频 13 已定。
- 根因：`services/api/ns_api/shot_status.py`、`frame_edit_queue.py` 读全局 `data/producer/registry.json`（最后更新 11-03 22:21，V1 / 早期 V2 的 redo / master_reject），活的那份是 `data/producer/runs/series10_v2/registry.json`（resident_sync 几分钟前同步，心跳新鲜）。/api/season 的每镜标签、板块“过期”、修改队列的排队位置全部跟着错。
- 修：`run_paths.producer_registry()` 单一入口（K-OPS-F24，legacy 剧才是旧位置）；两处读者改为 `registry_path()`，缓存键带路径；测试可覆盖 REGISTRY。
- 顺手：`/api/pipeline/status` 每次 5–7 s（sop_gate.status），顶栏 / 总览 / 成片页都在轮询 → 同剧 20 s 缓存（与 /api/sop/stepbar 的 STEPBAR_TTL_S 同口径）。
- 证据（改后，进程内同代码）：ep01 main = ok 11 · queued 4（S4/S8/S9/S13 尾帧排队）· best 1（S3 视频尽力版）；0 个 redo / stale。
- 测试：tests/test_uiux_loop_registry_source.py（4 过）；相关 112 过（test_r40/r43/frames_index_*/takes_ui/season/videos_overview/pipeline_status/ui_status_live/frame_edit_queue）。
- 待重启生效：是（API 进程里的模块）。

## 第 2 轮（11-06 18:06 JST）尾帧兜底（L-204 D8 / L-203 last_frame_fallback i2va）页面看不见、还打架

- 证据（改前）：ep01 S4 / S8 / S13 takes.json 顶层 `last_frame_fallback={mode:i2va, first_n, why}`（producer.gaze_fallback / PS-MASTER 17:38–17:59 定）。出图页尾帧格却写“尾帧在重出”“新 v8”（S4）、“等打分”（S8）；视频页 /api/videos/overview → S4/S8/S13 `need_frames missing=[last]`“缺尾帧 · 去出图补尾帧”。
- 修：`frames_index.last_fallback(takes)`（绑定的首帧还是当前首帧才有效）；尾帧格 state=`fallback`（不算缺图、不标新、不写在重出，带 word / why）；`video_index` 兜底镜不算缺尾帧（todo + fallback=i2va）。前端：出图页“不用尾帧 / 运镜交给视频模型”平静灰格 + 抽屉说明；视频页右下角“只用首帧”。
- 测试：tests/test_uiux_loop_fallback.py（4 过）；`npm run build` 过。
- 待重启生效：是。

## 第 3 轮（11-06 18:16 JST）新增：每集进度 / KPI 面板（总览顶部）

- 缺口：页面上看不到 L-205 的 50 分钟预算用了多少、L-207 三段到哪一段、每镜首 / 尾 / 视频三件事各自定下没有、兜底镜有几个；这些只在 data/brain/STATUS.md 里。
- 加：`GET /api/episodes/kpi`（`services/api/ns_api/episode_kpi.py`，10 s 缓存，实测 0.4–1.4 s）——KPI 计时读 data/brain/snapshot.json 的 kpi（30 分钟内才认，否则本机 producer log 第一次 dispatch 当起点并标“计时只有一台”）；每镜状态读活的登记表；图只给当前（通过）版；阶段优先 lane_roles_state.json `_active`，没有按登记表自算（assembled 但视频没齐 = “合成整集”，不是“已合成”）。
- 前端 `apps/web/src/v3/EpisodeKpi.tsx` + `kpi.css`，挂在 `#/overview` 的 NowPanel / 进度矩阵之后（可折叠记忆）：每集一行 阶段胶囊 · 用时 / 50 min 进度条（超了红、写超多少）· 首 / 尾（含 N 镜不用尾帧）/ 视频计数 · 每镜小图（首帧 + 尾帧叠角 + 三个点）点开进画布；接口 404（后台没重启）写明。
- 实测（进程内）：ep01 合成整集 · 超预算 · 首 16 尾 12+3 兜底 视频 14；ep02 出首尾帧 · 超预算 199 min · 0/16；ep03/04 还没开始。
- 测试：tests/test_uiux_loop_episode_kpi.py（5 过）；npm build 过。待重启生效：是（新路由）。

## 第 4 轮（11-06 18:16 JST）总览标签与登记表打架：“旧剧本版本 / 看图没过”挂在已通过的镜上

- 证据（改前，进程内 /api/season）：ep01 板块“本集过期：首帧、尾帧、成片要重出”；main = vqa_fail 6 · old 5 · ok 4 · queued 1；first_old 5 / last_old 4（图不显示）。
- 根因 ①：takes_ui.script_version 用导入作废线（import_events changed_shots，14:49 重导含 S1/S2/S4/S5/S6/S8/S12/S14/S15）把当前首尾帧判成“旧剧本版本”；但活的登记表 first/last/video 都是 passed 且 take 号 = 当前版（producer 导入时按编译后的提示词核过没变、保留），大脑按 16/16 做完在合成。
- 根因 ②：shot_status 把“现行版本里最新一版看图没过”挂成主标签 vqa_fail，而那只是系统自动重试的一版，当前版早已通过（项目方只看通过的）。
- 修：`shot_status.ledger_passed(shot, stage, n)`（活登记表 passed 且 take 号对上）；takes_ui 当前版若登记表 passed → script=current；tags_for 该阶段登记表 passed 且有当前版 → 不挂最新一版的看图结论。登记表 ready（真在重出）口径不变。
- 测试：tests/test_uiux_loop_ledger_current.py（3 过）；相关 65 过。待重启生效：是。

## 第 5 轮（11-06 18:30 JST）兜底镜 / 已排重出的镜在总览的口径 + 钟点 JST + 3 条过期静态测试

- 证据（第 4 轮后 /api/season）：ep01 板块仍“本集过期：尾帧、成片要重出”；S8 尾帧挂“旧剧本版本 + 排队”（它已 I2VA 兜底，不出尾帧）；S9 尾帧登记表 ready“首帧换过、跟着重出”却算“过期”（main5 已经是“尾帧排队重出”，两处口径不一）。
- 修：shot_status 认 frames_index.last_fallback——兜底镜不挂尾帧阶段任何标签、五态跳到视频、板块尾帧=已确认；板块“过期”只给登记表还没排进重出的（ready / running = 进行中，main5 同口径）。
- 钟点：笔记本系统时钟是美东，fmtClock（预计完成 / 排队预计）用浏览器本地 → 改为 Asia/Tokyo；修改记录 at（time.strftime 裸串）读接口时转 JST（存储不动）。
- 3 条早已失败的静态测试（不是本轮改坏）：提交逻辑挪到 Verdict.helpers.ts、步骤条字数分节点 → 断言跟到现文件，口径不变。
- 证据（改后 /api/season 进程内）：ep01 “本集进行中”，main = ok 14 · best 1（S3 视频尽力版等你接受）· old 1（S9 尾帧排队重出）；各阶段 done / doing；first_old 0。
- 测试：tests/test_uiux_loop_status_r5.py（3 过）；全部相关 175 过；npm build 过；arch_scan 见下。待重启生效：是。

## 复测汇总（11-06 18:30 JST）

| 接口 | 改前 | 改后（进程内同代码） |
|---|---|---|
| /api/frames-index?ep=1 | main redo 8 · stale 2；S4/S8/S13 尾帧“在重出 / 新 / 等打分” | main ok 11 · queued 4 · best 1；S4/S8/S13 尾帧 `fallback`“不用尾帧”；缺图 0 |
| /api/videos/overview?ep=1 | S4/S8/S13 need_frames“缺尾帧” | todo + fallback=i2va“只用首帧” |
| /api/season ep01 | 板块“本集过期：首帧、尾帧、成片要重出”；main vqa_fail 6 · old 5 · ok 4 | 板块“本集进行中”；main ok 14 · best 1 · old 1 |
| /api/pipeline/status | 5–7 s / 次，无缓存 | 首次 2–6 s，20 s 内 0.02 s |
| /api/episodes/kpi | 没有 | 新增，0.4–1.4 s（10 s 缓存） |

## 还没修（交 PS-MASTER 定）

- /api/pipeline/status（sop_gate）说 ep01 “首帧检查完成 15/16，缺 镜13”，登记表 / 大脑说 16/16：闸门本地证据（Q9）与出图机口径不一致，闸门在 tools/master 不在本工人范围。
- /api/readiness（整剧）20 s 不返回（UI 没用它，只有工具用）；/api/candidates?ep=1 3–7 s、/api/factory/health 3–5 s、/api/season 首次 3–9 s：都是每次重算，若要再快需加缓存或改算法（没动，避免扩架构）。
- 总览每镜 created_at（出图机写的裸时间串，纽约时区）在画布 / 历史里按原样显示（.slice），不是 JST；要改得统一出图机写入口径，不在 UI 范围。
- 全剧总览 ep01 S3 视频“尽力版，等你接受”、13 镜“视频待你审”= 项目方审片动作（L-123 只有“用这张 / 修改”），按设计保留。

# UIUX-LOOP-2 轮回（11-06 19:1x 起，worker UIUX-LOOP-2，接着第 5 轮）

## 第 6 轮（11-06 19:10 JST）慢接口根因 = /api/factory/health 在请求线程里 ssh；时间口径查清；大脑面板

- 证据（改前，活的 :8800，重启后实测）：/api/factory/health **60 s 不回**（curl --max-time 60 → 000）；同一时段 /api/frames-index?ep=1 12–21 s、/api/videos/overview?ep=1 8 s、/api/episodes/kpi 4.8 s、/api/readiness?ep=1 2.6 s；而进程内同代码：candidates 0.3–0.8 s、season_now 1.3 s、frames-index 0.5 s、videos 0.9 s、kpi 0.4 s。
- 根因：`factory_health._factory_status()` 每次请求 exec tools/factory/sync.py 并调 `status()`——对 gpu33 / gpu36 各跑一次 ssh（rrun timeout 60 s × run_retry 4 次），返回的又没有 `lanes` 字段，**结果一律被丢掉**；前端每 8 s 轮询一次，隧道一抖就一排线程卡在 ssh 上，线程池占满后别的接口跟着慢（这就是“/api/season 首次 3–9 s、candidates 3–7 s”的来源，不是它们自己慢）。
- 修：请求路径不许连机器——钩子只认 sync.py 的 `health_status()`（与本接口同结构、只读本机文件），模块按 mtime 只加载一次，`status()` 永不被调；两张看图卡 /health 探针并行（原串行 1.5 s × 2），5 s 内直接用、过期回旧值后台刷（stale-while-revalidate）。进程内实测：60 s+ → 冷 1.1 s / 热 0.02 s。
- 顺手：`takes_ui._run_legacy()` 每个版本问一次 runs.json / run.json（一集 ~800 次）→ 按 (NS_PRIMARY_RUN, 两个文件 mtime) 记住；candidates 热 0.8 → 0.33 s，season_now 1.4 → 0.7 s。
- /api/readiness 20 s+ 的大头（ep=1 7.4 s 里 5.4 s）= `tools/autopilot/runs.registry()` 没缓存、一次请求读 runs.json 4202 次（compiler.lens_term / asset_refs.manifest_rel / run_paths 一路调）；在 tools/autopilot 不在本工人范围，**交 PS-MASTER**：runs.registry 加 mtime 缓存（6 行）即可。UI 不用这个接口。
- 时间口径（核过事实，不是猜）：出图机写的 takes.json created_at **已经是 JST**——两台 producer / night / vidgen 都在 `TZ=Asia/Tokyo` 下跑（ops/offline/ensure_runs.sh、resident_restart.sh、tools/factory/sync.py ENV），实测 ep01 S1 尾帧 #120 created_at 17:10 vs 本机文件 mtime 03:21（美东）= 差 14 h；log.jsonl ts=14:49:28 对 t=1793944168 也是 JST。所以总览 / 画布里 .slice 显示的版本时间是对的，r5 “还没修”那条是误判。**真正是美东的**：笔记本 time.strftime 写的任务表 created_at / started_at（frame_jobs）、修改记录 at（frame_edit_queue）。新建 `ns_api/clock.py` 单一入口（local_naive_to_jst / server_naive_jst）；frame_edit_queue.to_jst 改走它；frames-index 的 gen.created_at / started_at 给页面带 +09:00（前端 genView 用 Date.parse 算“排了多久 / 预计几点”，不再靠浏览器时区）。
- 新增：`GET /api/brain/status`（services/api/ns_api/brain_status.py，5 s 缓存，实测 0.04 s）读 data/brain/{STATUS.md, decisions.jsonl, owner_notes.md, snapshot.json} + config/brain/brain.json → 总览 EpisodeKpi 面板下方“大脑在想什么”只读面板（apps/web/src/v3/BrainPanel.tsx + brain.css；默认收起一行：模式 · 最近决定 · 最新给项目方的话；展开：给项目方的话 / 最近决定（只记不做标出）/ 大脑看到的（快照探针、开着的卡点、空着的卡）/ 看状态页全文 / 本地打开 STATUS.md；缺哪份文件写明）。
- episode_kpi.py arch_scan：silent_read 已 0（except 都带 `# arch-ok` 且理由成立：显示层缺文件 = 面板写明）；`--files … --check` 对本轮 + UIUX-LOOP 改过的 13 个文件 PASS（0 退化）。全仓 `--check` 剩下的只有 **untracked_code / untracked_imported**（episode_kpi.py、clock.py、brain_status.py 没入版，app.py import 它们）——发版前需 PS-MASTER `git add` 这三个文件（本工人不做 git 操作）。
- 测试：tests/test_uiux_loop2_r6.py（8 过）；相关 98 + 34 + 90 过（uiux_loop*、takes_ui、r41/r43、season、render_paths、frames_index*、frame_edit_queue、active_audit、pipeline_status、ui_status_live、videos_overview、factory）；npm build 过。
- 待重启生效：是（factory_health / takes_ui / clock / brain_status 都在 API 进程里）。重启后请再量一次 /api/factory/health、frames-index、season。

## 第 7 轮（11-06 19:40 JST）出图页 / 视频页只认有图的镜；视频页“未出”与登记表打架

- 证据（改前，活的 :8800）：/api/frames-index?ep=2 → 8 镜（登记表 ep02 有 16 镜、16 首帧 ready 排队），S2 / S9 / S11–S16 页面上根本不存在；/api/videos/overview?ep=1 → S3 `todo`“未出”、S4 `todo`“未出”，而登记表 S3 视频 best_effort（“试了 4 次没全过，取罚分最小的一版”）、S4 视频 passed（“v1 过审片打分”）、总览也挂着“尽力版 · 等你接受”；/api/episodes/kpi 按登记表说 ep01 视频 16/16 已合成。三个页面三个口径。
- 根因 ①：frames_index.build / video_index.build 只 glob `renders/ep*/S*/takes.json`——没出过图的镜没目录就没格子。根因 ②：producer 定下视频时 registry.objects.video.take 是 None、本机 takes.json 的 active 也没 video（定下时 take 号没写进 active，或片子还没同步到本机），视频页只认 active.video → 一律“未出”。
- 修：`shot_status.ledger_shots / ledger_obj / ledger_cell`（活登记表的镜集合与阶段状态，大白话：排队等空闲的卡 / 正在出 / 等上一步 / 没出来，系统在重试 / 尽力版 / 已定下）。出图页、视频页镜集合 = 目录 ∪ 登记表；没图的格子写登记表状态（FramesPage missWord / tip），不再写“还没出图”。视频页：登记表 best_effort / passed 而本机没当前视频 → 给登记表指的那版（没写 take 号 → 最新一版通过后检且片子已在本机的，并在格子 / 抽屉写明“登记表没写定下的是哪一版，先给 vN”；片子没拉到本机 → 待你看 + “片子还没拉到本机”，不给 404 的地址）；尽力版单独一态 `best_effort`（“尽力版 · 待你看”，“待你看”筛选含它，仍只有 用这版 / 修改）；首尾帧还在排队的镜写“等首尾帧（排队等空闲的卡）”（todo，灰），不写“缺首尾帧 · 去出图”（那是要项目方动手的琥珀色卡住）。
- 证据（改后，进程内同代码）：frames-index ep2 = 16 镜，首帧格“排队等空闲的卡”、尾帧格“等上一步”、主标签 queued；videos ep1 = 待你看 15 · 尽力版 1（S3 给 v4 并写明 v6 还没到本机；S4 给 v1）；videos ep2 = 16 镜“等首尾帧（排队等空闲的卡）”、need_frames 0。
- 测试：tests/test_uiux_loop2_r7.py（3 过，临时登记表）；3 个旧测试（frames_index_assetux / videos_overview_navia / uiux_loop_fallback）各加一行隔离活登记表（它们只测目录口径）；相关 225 过；npm build 过；arch_scan --files 17 个文件 PASS。待重启生效：是。

## 第 8 轮（11-06 19:55 JST）修改队列排着不会出的尾帧；进度条“视频 11/16 其余在排队”与登记表 16/16 打架

- 证据（改前，活的 :8800）：/api/frame-queue 第 1 位 = `last:ep01-S4`（第 2 位 S8 尾帧），而大脑 17:45–17:59 已给 S4 / S8 写 I2VA 兜底（takes.json last_frame_fallback，没有当前尾帧；登记表里尾帧对象还是 ready “尽力版的契约变了 → 自动重置”）；队列小窗写“ep01-S4 尾帧 排第 1 · 19:xx 前后”。/api/pipeline/status ep01 视频格“视频出了 11/16 镜，其余在排队”（sop_gate 只认本机 data/pipeline/runs/<run>/video/clips 目录，片子要同步回来才算），登记表视频 passed 15 + best_effort 1 = 16/16，总览 KPI 面板也写 16/16 已合成——同一屏两个数。
- 修：frame_edit_queue.snapshot 跳过“兜底生效且没有当前尾帧”的尾帧对象（响应带 skipped_fallback 供核对；有当前尾帧、登记表要重出的 S9 照常排）；pipeline_status.live_adjust 带 video_ledger（登记表本集视频 定下 / 尽力版 / 总数），fold 在闸门落后时写“视频全部定下 16/16 镜（1 镜尽力版等你定） · 本机已收到 11/16 段”，闸门判定（state=doing）不动。
- 证据（改后，进程内）：队列 queued 40、skipped [last:ep01-S4, last:ep01-S8]，第 1 位 = first:ep02-S1；ep01 视频格如上文。
- 测试：tests/test_uiux_loop2_r8.py（3 过）；相关 53 过；arch_scan --files PASS。待重启生效：是。

## 还没修 / 交 PS-MASTER（11-06 19:55 JST）

- 发版前 `git add services/api/ns_api/{episode_kpi,clock,brain_status}.py`（arch_scan untracked_imported；本工人不做 git 操作）。
- /api/readiness 20 s+：tools/autopilot/runs.registry() 无缓存（一次请求读 runs.json 4202 次，占 7.4 s 里的 5.4 s）——6 行 mtime 缓存即可，不在本工人范围。
- 大脑 KPI 计时口径：ep01 start = 11-03 21:47（两台里最早派单，含之前几轮重做）→ 面板“用时 69.5 小时 · 已合成”；按 L-205 应从本版导入（11-06 14:49）之后第一次派单起算。telemetry.kpi 在 tools/brain，交 BRAIN-FW / PS-MASTER 定口径（UI 按单一来源显示，没改）。
- S9：takes.json 已写 I2VA 兜底（PS-MASTER 17:38）但还有当前尾帧 v3、登记表尾帧 ready“首帧换过跟着重出”——两处决定打架（兜底 vs 重出），页面按登记表显示“尾帧排队重出”；该由大脑定一个。
- 活的 :8800 还是旧进程：/api/factory/health 60 s 不回、frames-index 12–21 s、candidates 2.9 s 都是线程池被 ssh 占满的症状，重启后请复测（进程内同代码 0.3–1.1 s）。
- 项目方待办（设计如此，不是 bug）：ep01 视频 15 镜“待你看”+ S3 尽力版 等 用这版 / 修改；8 项资产底图“挑一张”在 #/queue。

## 第 9 轮（11-06 20:05 JST）KPI 面板“用时 69.5 小时 · 已合成”写明口径；全套复测

- 证据：/api/episodes/kpi ep01 start=11-03 21:47（大脑快照 kpi：两台里最早派单）、本版剧本导入 11-06 14:49 → 面板“用时 69.5 小时”，项目方会当成这一集真做了三天。
- 修（UI 只写明，口径不改、仍是单一来源）：episode_kpi 每集带 import_at（takes_ui.cutoff_for，本集最后一次导入）与 start_before_import；面板用时后小字“（含之前几轮重做）”、悬停写“早于本版剧本导入 11-06 14:49”。ep02 start 14:50 晚于其导入 11-05 18:10 → 不标。
- 复测（进程内同代码）：kpi 0.4 s；全部相关 244 过（uiux_loop r1–r9、frames_index*、videos、season、takes_ui、r41/r43、pipeline_status、ui_status_live、factory、frame_edit_queue、active_audit、render_paths、l123_no_reject_ui、ui_no_tech_words）；npm build 过；arch_scan --files 18 个文件 PASS（0 退化；全仓剩 untracked_* 三个新文件待 git add）。
- 待重启生效：是（全部在 API 进程里，ops/restart_api.ps1）。重启后复测清单：/api/factory/health（应 < 1.5 s）、/api/frames-index?ep=1 / ?ep=2（16 镜）、/api/videos/overview?ep=1（待你看 15 · 尽力版 1）、/api/frame-queue（skipped_fallback 2）、/api/pipeline/status ep01 视频格、/api/brain/status、总览三块面板。

# UIUX-LOOP-3 轮回（11-06 19:3x 起，worker UIUX-LOOP-3，接着第 9 轮；API 已带 r1–r9 重启）

## 第 10 轮（11-06 19:35 JST）重启后复测：r6–r9 全部生效；两处小回归

- 复测（活的 :8800，重启后）：/api/factory/health 0.41 s（原 60 s 不回）；/api/frames-index?ep=1 冷 4.6 → 热 0.35 s，ep=1 / ep=2 都 16 镜（ep1 ok 14 · best 1 · queued 1；ep2 queued 16“排队等空闲的卡”）；/api/videos/overview?ep=1 待你看 15 · 尽力版 1；/api/frame-queue 第 1 位 last:ep01-S9（S4 / S8 不在）；/api/pipeline/status ep01 视频格“视频全部定下 16/16 镜（1 镜尽力版等你定） · 本机已收到 11/16 段”；/api/brain/status 0.02 s（缺 owner_notes.md 写明）；/api/season 0.04 s、/api/episodes/kpi 0.5 s、/api/candidates?ep=1 0.6 s。
- 回归 ①：/api/frame-queue 没有 `skipped_fallback`（r8 只加在 snapshot() 里，路由挑键时没透出）→ 路由带出（活接口能核对 S4 / S8 为什么不在队列）。
- 回归 ②：/api/pipeline/status 集级一句话 plain 仍是“停在“视频”：视频出了 11/16 镜，其余在排队”，同一屏视频格写 16/16 → plain_episode 认格子（cells）同口径。
- 测试：tests/test_uiux_loop3_r10.py（3 过）。待重启生效：是。

## 第 11 轮（11-06 19:45 JST）/api/readiness：runs.registry() 读 runs.json 4202 次 → mtime 缓存

- 证据（进程内 cProfile，_readiness_report(1) 按镜缓存清空后）：runs.registry 3246 次 / 一次请求，经 compiler.lens_term → run_paths._ctx → is_legacy → legacy_run 一路调；活接口 /api/readiness?ep=1 2.2 s、整剧 7.9 s（重启后首次）。
- 修（tools/autopilot/runs.py，本轮唯一允许的 tools 文件）：`_jl_cached` 按 (mtime_ns, size) 记住一次解析，文件一换就重读；返回两层拷贝（顶层 + 每部剧条目；试过 deepcopy：0.5 ms × 3000 次又回到秒级）——register_run / set_status 就地改条目再写回，不能改到缓存。
- 证据（改后，进程内同代码，首次含导入）：readiness?ep=1 10.1 → 5.6 s、整剧 9.0 → 4.5 s；剩下的大头是每镜 compile_for_display / shot_looks / h3view（ns_agent，不在本工人范围）。UI 不用这个接口。
- 测试：test_uiux_loop3_r10.py::test_runs_registry_cached_by_mtime_and_returns_copy；tests 里读 runs.json 的 113 过（test_prodmerge_o 1 条、test_distill_flow 1 条本来就红：前者连网被 net-guard 拦，后者 vqa.json / producer 卡表与策略漂移，与本轮无关）。

## 第 12 轮（11-06 19:55 JST）项目方看不到最新成片：成片页列不出 V2 的 66 版、连播放的是 11-04 的占位预览

- 证据（活的 :8800）：/api/episodes/1/cuts → `cuts: []`（成片页“第 1 集还没有成片”），而 data/episodes/series10_v2/ 里 ep01_v1…v64_post 共 66 版（最新 ep01_v64_post.mp4 19:42 JST，night 合成 + DIRECTOR post_pass 调色 / 音效）；/api/episodes/1/preview → 11-04 02:48 拼的 preview_latest（11 镜全占位、0 视频），而且地址写死 `/files/renders/ep01/_final/…` = V1 的旧预览目录（V2 的在 renders/series10_v2/ep01/_final）。总览 / KPI 面板没有任何“最新成片”入口。合成闸门结论（timeline.json gates：v64_post verdict=fail，缺 S2 / S4 / S8 / S13 用静帧 / 黑场占位）页面上看不到——闸门没过的片会被当成成片。
- 根因：cuts._epdir 写死 data/episodes/（K-OPS-F24：只有 legacy 剧才用不带前缀的路径）；ep_preview 地址拼串写死。
- 修：`run_paths.episodes_dir / episodes_for_data`（V2 = data/episodes/<run>/，legacy = data/episodes/，沙箱 data 旧行为）；cuts：`episode_films`（顶层 epNN*.mp4，不含 _work / _partial 半成品）、`film_gate`（闸门 verdict / 缺镜 / post → 大白话：“预览版 · 合成闸门没过：缺 4 镜用占位” / “成片 · 合成闸门通过”；装配器标 preview 的一律预览版）、`latest_film`（最新一版，三处共用）；每版带 `gate`，闸门没过 / preview 的加“预览”标签；钟点改 JST（以前 time.localtime = 笔记本美东）；66 版 × 16 镜每次重读 timeline / takes.json 12.9 s → timeline 按 mtime 缓存 + 每次请求每镜当前视频只问一次 → 冷 0.94 s / 热 0.31 s。ep_preview：最新成片比巡检预览新 → 连播给最新成片（timeline 的 start_s / duration_s / kind 映射到同一结构，占位镜灰）并带 `film`（名字 / 版本 / 闸门一句话 / 缺哪几镜）；预览地址按文件真实位置。episode_kpi：每集带 `film`。
- 前端：EpisodeKpi 每集一行加“最新成片 v64 · 预览版 · 合成闸门没过：缺 4 镜用占位 · 11-06 19:42 · 播放”（点开成片页本集；“播放”直接开文件）、没有成片写“还没有”；每集“首尾对照”开关（L-203：首帧 | 尾帧 并排大图 + 视频一个点，只显示通过的版本，点开进画布，记住选择）；连播本集顶栏写明“最新成片 vN · 预览版 · 闸门没过 … · 预览，非交付”或“闸门通过的成片”；成片页每版一个闸门标签（闸门没过 · 缺 N 镜 / 闸门通过 / 没有闸门记录，悬停列缺镜原因与已调色）。全部只有看与跳转，没有新增任何接受 / 驳回入口（L-123 静态测试过）。
- 证据（改后，进程内）：cuts ep1 66 版，最新 ep01_v64_post“预览版 · 合成闸门没过：缺 4 镜用占位”，ep01_v65.mp4（19:36，还没 timeline）“没有闸门记录”；preview ep1 source=film v64_post（视频 12 · 占位 4 · 71.3 s）；kpi ep1.film 同上，ep2–4 null；ep2 preview 404 口径不变。
- 测试：tests/test_uiux_loop3_r12.py（5 过）；cuts / cutedit / kpi / uiux 相关 62 过；npm run build（tsc -b）过。待重启生效：是。

## 第 13 轮（11-06 20:05 JST）全页接口计时；/api/pipeline/status 过期那一次 3–11 s 卡住顶栏

- 活接口全扫（页面会调的 GET，热）：全部 < 1 s（/api/sop/episode/1 0.6 s、/api/v1-library 0.85 s 最慢）；冷的只有首次：/api/people 5.4 → 0.02 s、/api/assets/scenes 2.3 → 0.09、/api/character-hub 2.4 → 0.3、frames-index 4.6 → 0.35（都是进程内缓存，重启后第一下）。/api/events 是 SSE 长连接（60 s 不回是对的）。请求路径里没有 ssh：factory_health（r6 已改）、gpu_live（常驻线程）、gpu_monitor（首次 collect(ssh=False)，ssh 在后台线程）、infra_status（读文件）。
- 证据：/api/sop/stepbar 一次 11.5 s（前后都 0.01 s）= 20 s 缓存过期那一次同步重算 sop_gate.status（进程内 2.8 s，活接口受线程池影响 3–11 s）；顶栏 / 总览 / 成片页都在轮询，每 20 s 就有一个请求被卡住。
- 修：pipeline_status 过期 ≤ 5 分钟先回旧值、后台单飞刷新（STALE_MAX_S；超过才同步重算，不给太旧的）；stepbar 自己的重算只剩 open_issues + 视图：两个缓存都过期时 0.04 s（原 2.7 s+）。
- 测试：tests/test_uiux_loop3_r13.py（2 过）；pipeline_status / stepbar / r8 / r10 共 46 过；arch_scan --files 7 个改过的 py PASS（0 退化）。待重启生效：是。

## 还没修 / 交 PS-MASTER（11-06 20:05 JST）

- 发版前 `git add` 新文件：services/api/ns_api/{episode_kpi,clock,brain_status}.py（r6 起 untracked_imported）+ tests/test_uiux_loop3_r1{0,2,3}.py（本工人不做 git 操作）。
- /api/readiness 还要 4.5–5.6 s（进程内首次）：每镜 compile_for_display / shot_looks / h3view 在 ns_agent，不在本工人范围；UI 不用它。
- ep01 最新成片 v64_post 合成闸门 fail（缺 S2 / S4 / S8 / S13）：S4 / S8 已 I2VA 兜底、登记表视频 passed，但装配时本机 clips 还没同步到（pipeline/status“本机已收到 11/16 段”）——等 resident_sync 拉齐后 night 会再合成；页面现在诚实标“预览版”。
- KPI 面板 ep01 阶段“已合成”来自 lane_roles_state / 登记表 assembly passed，而最新成片闸门没过——面板旁边的“最新成片”一行已写明；阶段词本身由大脑定（没改）。
- 活的 :8800 仍是 r9 的进程：r10–r13 全部要重启生效（ops/restart_api.ps1）。重启后复测：/api/episodes/1/cuts（66 版、< 1 s）、/api/episodes/1/preview（source=film）、/api/episodes/kpi（ep1.film）、/api/frame-queue（skipped_fallback 2）、/api/pipeline/status plain、/api/sop/stepbar 过期那一次 < 0.1 s、总览 KPI 面板“最新成片 / 首尾对照”。

## 第 14 轮（11-06 20:08 JST，PS-MASTER 报）最新成片不该按 mtime 挑：v64_post（预览、4 镜占位）压过 v65；.part 不能列

- 证据（重启后活接口）：/api/episodes/1/preview 与 KPI“最新成片”都挑 ep01_v64_post.mp4（timeline preview、闸门 fail 缺 4 镜；同步重新 touch 过，mtime 05:42 EST），而 ep01_v65.mp4（05:36 EST，PS-MASTER：16/16 真视频、HARD_RULES 过；本机还没有它的 timeline.json）排在后面；ep01_v66.* 正在写（.part）。
- 规则（PS-MASTER 定）：① 合成闸门通过的 > 没有闸门记录的（timeline 还没同步到）> 预览 / 闸门没过的；② 同一档版本号大的在前，不看 mtime；③ *.part、0 字节、旁边有同名 .part 的一律不列（含 plan / _final 的成片）。
- 修（cuts.py 一处口径：film_tier / film_rank_key / _incomplete；episode_films 排好序，latest_film、/cuts“最新”、/preview、KPI 都跟着）；没有闸门记录的成片标“整集成片 · 闸门记录还没同步到本机”（kind=unknown），既不冒充成片也不叫预览版；连播顶栏 / KPI 同口径。
- 证据（改后，进程内，活数据）：/cuts ep1 66 版，前三 = v65（没有闸门记录）、v64_post（缺 4 镜）、v63_post（缺 5 镜），v66 .part 没列；/preview source=film v65；kpi ep1.film v65。时延：cuts 冷 1.6 / 热 0.32 s，preview 0.05 s，kpi 0.5 s。
- 测试：tests/test_uiux_loop3_r14.py（3 过：闸门通过 > 未知 > 预览、版本号压 mtime、.part / 0 字节 / 旁有 .part 不列、/cuts 与 KPI 跟排序）；r12 期望按新规则改（闸门通过的 v9 排预览版 v63_post 前）；相关 50 过；npm run build 过；arch_scan --files PASS。没有新增任何接受 / 驳回入口。待重启生效：是（cuts / ep_preview / episode_kpi + 前端 dist）。

## 第 15 轮（11-06 21:54 JST）Fable 复审 SHIP-WITH-FIXES：B1 缓存竞态、B2 视频页只登记在登记表的镜被写成“缺首尾帧”

- B1（tools/autopilot/runs._jl_cached，producer 侧也用）：写进 _REG_CACHE 后又从字典回读，另一线程同时 pop → registry() KeyError → 写完就用本地元组；函数里没有第二处回读。测试用“set 完立刻 pop”的字典模拟。
- B2（video_index）：只登记在登记表、本机没 takes.json 的镜 missing 永远是 [first, last]，`elif missing and not cur` 把登记表的 视频 running / ready、首尾帧 passed 全盖成“缺首尾帧 · 去出图”→ 先看登记表：视频 running → 在出、ready → 排队；首尾帧都 passed → “首尾帧已定下（图还没拉到本机），等出视频”（视频 failed 照登记表）；首 / 尾任一 ready / running / pending / failed（没出来，系统在重试）→ “等首尾帧（…）”，按首帧→尾帧先报前者；登记表里首尾帧对象都没有才是“缺首尾帧 · 去出图”。活数据：ep1 待你看 14 · 尽力版 1 · todo 1（S1 首帧刚被重置 ready，活接口旧代码同样 14·1·1，不是本轮改的）；ep2 16 todo；need_frames 0。
- 小修：cuts.latest_film 文档字符串改成“按 film_rank_key”；BrainPanel 不认识的决定种类显示“其它动作”（悬停带原词），不再裸露英文。
- 测试：tests/test_uiux_loop3_r15.py（2 过）；r7 / videos / fallback / r10 / r12 / r14 / l207 / episode_pipeline 共 51 过；npm run build 过；arch_scan --files PASS。待重启生效：是。
