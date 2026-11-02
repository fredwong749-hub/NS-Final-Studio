# 全局代码与架构审查（GLOBAL-O，Opus，11-03，只读）

> 派单：总调度。与 Fable 审查员独立并行，互不参照，最后由总调度合并。
> 标准：项目方原话、OWNER_CANON C-01…C-25、PLAN_V2_MASTER v3（§1.2 DoD）、MASTER_PICTURE §1（L-001…L-146，以最新为准）。
> 方法：读代码；本机进程表；经 `tools/netfix/rsh.py` 对 gpu33 / gpu36 做只读的 ps、nvidia-smi、md5sum；只读运行 `sop_gate.py status`、`master_check.py`；跑全量 pytest（结果见 §F.3）。没改代码、没重启、没出图，也没读 data/master/。
> 已有审计 V1_TO_V2_CARRYOVER.md 列过的不再重复（下文用“CARRYOVER P0-n / P1-n”指代）。V2_SYSTEM_LOSS_AUDIT.md 和 NAVFLOW_BEFORE.md 在写本文时还不存在，没有参照。
> 引用写法：`文件:行号`，路径相对 `D:\NS-Final Studio`；“实测”指 11-03 本次审查当场看到的输出。

---

## 一句话结论

V1 的生产主干（producer → takes.json → 画布 → night/vidgen → assemble）**一次都没有为 V2 跑过**。V2 的首帧只能走 `tools/promptfix/golden_v2.py` 这个金样 CLI，而它写死了“只出祁念单人镜、只取第 1 集”，记账也记在另一本账上（`data/ab/v2_golden_ep01/takes.jsonl`）。这本账画布、视频链、成片都读不到。所以第 1 集现在的状态不是“还差几步”，而是**出图以后的整段链路对 V2 不通**。第一阶段要做的不是再写新工具，而是让 V2 走回 V1 主干（L-137）。

---

## A. 架构地图

### A.1 现在实际在跑的进程（实测）

| 机器 | 常驻进程 | 作用 | 对 V2 有没有用 |
|---|---|---|---|
| 笔记本 | `tools/factory/autoflow_resident.py --interval 30` | 写作推进、导入后跑 episode_ready、派单器 tick、asset_worker tick | 有（V2 的唯一推进入口） |
| 笔记本 | `api_watchdog.py` → `uvicorn ns_api.app:app :8800` | API + 网页 | 有 |
| 笔记本 | `tools/autopilot/producer.py serve` | V1 出图 / 尾帧 / 视频交接状态机 | **没有**：`data/producer/control.json` 是 `only=["__none__"]`，7 条道全部 hold；`data/producer/runs/series10_v2/` 下只有一个 log.jsonl，没有 control 和 registry |
| 笔记本 | `tools/autopilot/episode_pipeline.py watch` | V1：看到 CHANGELOG 里的“HOLLYWOOD 导入 epNN”就重编 first_frame_jobs | 没有（V2 导入不写这一行）；但 RUN 读的是 run.json = series10_v2，见 C-2 |
| 笔记本 | sentinel、monitor/server.py（8810）、monitor/v2_live.py、infra_watchdog、resident_sync、tunnel_supervisor、puller、tcpbridge ×N、`D:\ns_vqa\server.py` | 运维 / 看板 / 本地看图 | 部分有 |
| gpu33 | `vidgen.py run gpu33`（cwd `/root/work/fredw/video10_srv`）、ComfyUI 8188/8189/8191、`clip_srv.py`（cwd `offline_20261101/repo`）、`audio_post.py watch`（2 天）、**`bench2.py h3`（`/root/claude-kimi-ns-studio-v1`，已跑 3 天 7 小时）**、**`nsfs_canvas uvicorn`（services/canvas_api 的老部署）** | 视频 worker / 出图 / 打分 | 视频 worker 跑的是一份没被版本管理的副本（见 C-3） |
| gpu36 | `vidgen.py run gpu36`（cwd `video10_srv`）、ComfyUI 8188/8189、vqa server ×2 + vqa_router、anomaly_server、**bakeoff `run.py gen`（已跑 1 天 15 小时）** | 同上 | 同上 |
| 全部 | nvidia-smi 实测所有道 **0%** 利用率；master_check ⑦ 同样显示 0% | — | GPU 闲置（C-13 要求拉满） |

### A.2 按阶段：真正生效的入口、重复实现、死代码

| # | 阶段 | V1 生产主干（在 V1 上真正跑通过） | V2 现行入口 | 重复入口（根因模式 #1） | 死代码 / 一次性 |
|---|---|---|---|---|---|
| 0 | “当前是哪部剧” | `tools/autopilot/runs.py`（读 `config/pipeline/runs.json` 的 primary） | 同左 | **三个来源**：runs.json 的 `primary`；`config/pipeline/run.json` 的 `run_id`（`producer.py:68-77` 写明“只从 run.json 读”，此外还有 episode_pipeline.py:39、flow.py、decisions_guard.py、state_paths.py、run_chain.py、identity_face_check.py、ns_api/story_runs.py 在读）；环境变量 `NS_RUN`（golden_v2.py:33） | — |
| 1 | 写作 P1–P4 | `hollywood_r5.py` / ns_api `script_chat` / `autopilot/writer.py` / `qwen_repair_loop.py` | `autoflow_resident` → `autoflow.py` → `autoflow_agent.py` + `factory/agent_dispatcher.py`（无头 Claude）+ `pipeline/run_chain.py`；网页一键入口 `ns_api/script_autoflow.py` 起的是同一个子进程（这一处没问题） | V1 的四条写作入口都还在，V2 没用 | `script_chat_batch.py`、`script_chat_repair.py`、`qwen_chat.py`、`qwen_task.py`、`export_qwen_script.py` |
| 2 | 导入 | `tools/import_script.py`（V1 泄漏闸门 `:288-300` 已加上） | `autoflow_agent.py:1166` → `producer.py import-staged` → import_script | 能写导入稿的入口 **≥5 个**：import-staged；`ns_api/script_inbox.py:305`；`ns_api/qwen_mailbox.py:427`；**`ns_api/wizard.py:178` 绕过 import_script 直接写 script_json**（不过 V1 守卫，也不过 strict）；`ns_orch/engine.py:161` | `services/orchestrator`（10-30 以后没改过） |
| 3 | 资产 | `assetmaster/*`、`char_assets/`、`gen_assets*.py`、`voice10/`、`bgm/agent.py` | `pipeline/asset_jobs.py` + `asset_worker.py` + `asset_checks.py` + `owner_pick` + `v2style/voice_v2.py` + `bgm/bgm_library.py` | `promptfix/cast_v2.py:80` 还在，仍能出角色候选（CAST-S 的一次性补救） | `gen_assets.py`、`gen_assets_items.py`、`gen_assets_v2.py`、`asset_repair/` |
| 4 | 提示词编译 | **唯一入口 `ns_agent/frame_job.build_first`**（这一处是对的） | 同左 | 调用方有 12 个（`grep build_first(`），其中 poster、cast_v2、compile_sha、series10_imggen/imggen 是旁路；`config/compile/imgmaster.yaml` 的插件式编译开关是关的（CARRYOVER B 表） | `tools/imgmaster/` |
| 5 | **出图执行 + 记账** | `producer.py serve` → `ns_render.unified_frame` → `data/renders/<run>/epNN/SN/takes.json`（每镜版本链、redo 阶梯 K-OPS-E09、种子流 `producer.py:2321`、借道、哨兵工单） | **`golden_v2.py --render --shot N --lane X`**（手工指定道）→ `data/ab/v2_golden_ep01/takes.jsonl` + `data/review_pages/v2_golden/` | **两本账**：takes.json 和 ab 账；sop_gate 两本都读（`sop_gate.py:212-247`），episode_metrics 读的是第三个文件 `data/ab/v2_golden/takes.jsonl`（`episode_metrics.py:134`），和 golden_v2 实际写的 `v2_golden_epNN`（`golden_v2.py:395`）不是同一个 | `golden_worker` 已隔离（`data/_quarantine_20261103_golden_o/`）；`series10_imggen/imggen.py`（V1 服务器出图） |
| 6 | 出图后检测 | `gen_contract/postflight.py`（Q1–Q10）+ `vqa/contract`（Q9）+ `vqa/anomaly` + `vqa/accept` | golden_v2 自己有一套判定 `judge_bundle` / `verdict`（`golden_v2.py:237-282`）；资产另有 `asset_checks.bundle_check` | **三套判定**。GOLDEN-O 交的“并入清单”（bundle 进 postflight、vlm_pool 进 vqa client、retry 三态）没有执行：postflight 和 vqa 里 grep `bundle` / `vlm_pool` 都是 0 命中 | — |
| 7 | 给项目方看 / 选首帧 | 画布读 takes.json；#/queue | review_pages/v2_golden（本地 HTML） | **网页没有任何地方读 v2_golden**：在 `services/api` 和 `apps/web/src` 里 grep `v2_golden`，0 命中 | — |
| 8 | 尾帧 | producer 的 `last` 对象（`producer.py:263-272`） | **没有入口** | — | — |
| 9 | 视频 | `series10_video/night.py`（笔记本）→ `build_jobs.py` → `deploy.py push` → 服务器 `vidgen.py run` | 同左；MERGE-VID-O 正在改成按剧（`build_jobs.py:39-57`、`night.py:35-47`） | `build_jobs.passed_frames()` 只读 takes.json（`build_jobs.py:166-196`），**读不到 V2 的 ab 账**。服务器上 vidgen 有三份（C-3）。`ns_recipes/acting.py` 和 `tools/vidlab/acting.py` 是同一套规则的两份副本，文件头自己写着“改规则两处同改”（`ns_recipes/acting.py:5`） | `video_rca/`、`vidlab/`、`lab_ep02/`、`iterate_loop/`（ns_recipes 只在注释里引用） |
| 10 | 整集预览 / 后期 | `night.finalize` → `tools/assemble_episode.py` → `ns_post/assemble.py`；`tools/director/finish.py` | 同左（按剧改造进行中，`night.py:381-392`） | 成片有四个入口：assemble_episode、`assemble_series.py`、CUTEDIT 的 `cut_export.py`、`ns_api/cuts.py`。`ns_post/assemble.find_source` 写死了 `data/renders/epNN/SN`（`assemble.py:347-349`），不认剧 | `ab_motion_*.py`、`color_match_clips.py`、`rr_recover_video_takes.py` |
| 11 | **阶段 / 状态模型** | producer 的 registry 对象（script→import→assets→first→last→video→voice→bgm→assemble→preview，`producer.py:1174-1320`） | `tools/master/sop_gate.py`（9 个阶段） | **一共六套**：sop_gate；`ns_api/sop.py`（S1–S5 + G1–G5，网页读的是 `/api/sop/status`，`app.py:1152`）；`tools/autopilot/flow.py`（12 段，写 `data/autopilot/flow/status.json`）；`ns_orch/engine.py`（`data/orchestrator/state.json`）；producer registry；`stage_status.json`（**没有任何写入方**，最后修改 11-02 20:23，但 `sentinel/scorecard.py:86` 和 `monitor/v2_live.py:50` 还在读） | `tools/sop_owner.py`（V1 G4/G5） |

### A.3 V1 主干和 V2 新写部分对照

| 层 | V1 主干（应当作地基） | V2 新写的部分 | 判定 |
|---|---|---|---|
| 剧注册 | runs.py | runs.json 里的 assets_manifest、按剧路径 | 并入了，但“当前剧”有三个来源 → 统一 |
| 写作 | run_chain、validate_qwen_script、lints、knowledge | autoflow / autoflow_agent、agent_dispatcher、补丁环 | 是在主干上加的，方向对 |
| 资产 | assetmaster、voice10、bgm/agent | asset_jobs / worker / checks、voice_v2、bgm_library | V2 这套更好；V1 那套可以退役 |
| 编译 | build_first、asset_refs、framing、bible | bible_series10_v2.toml、run_style | 已并入（剩下的缺口见 CARRYOVER P0-1、P1-13） |
| 出图执行 | **producer + takes.json** | **golden_v2（ab 账）** | **平行实现，违反 L-137**，第一阶段要并回 |
| 检测 | postflight / vqa / anomaly | golden 的 bundle、asset_checks、vlm_pool | 能力有用，但还没并进 postflight |
| 视频 | night / build_jobs / vidgen / recipes | 按剧改造中 | 主干对；接不到 V2 的首帧 |
| 后期 | ns_post、assemble、cut_export | music_v2 / voices_v2 | 有一部分写死 V1 路径 |
| 控制面 | system_version、decision_check、sentinel、arch_scan | sop_gate、master_check、episode_retro、episode_metrics、report_issue、episode_ready | 方向对；问题是阶段模型有六套 |

---

## B. 离“做完第 1 集”有多远（PLAN_V2_MASTER §1.2 DoD，逐项）

实测：`sop_gate.py status --run series10_v2` 显示 ep01 当前在**导入闸门**，复盘是 draft；`master_check` 显示待处理请求 0 条，GPU 全部 0%。也就是说，**系统现在停着，没有人在推进第 1 集**。

| DoD | 现状（证据） | 还缺什么 | 缺的部件在哪 |
|---|---|---|---|
| 1 P1→P4 strict 全过 | ❌ `autoflow_ep01.json`：gate=reopened，import=reopened，verdict=not_importable，next_action=“补丁已出 10 次仍有失败项，交总调度”。剩 6 项没过：S6 时长 7 秒（QW-T1）；S6/S9/S10/S11 镜内用了 `At 00:02.000` 时间码（RL-T9，即 L-141）；S7 手部动作 3 拍（k211）。补丁历史 a5→a10 的失败数是 9→8→7→7→7→6，a8、a9 因为 SS-A3 变多被拒 | ① L-141 是**改规则以后整份旧稿都要迁移**，但补丁环每轮最多 14 行、靠 LLM 一镜一镜改，收敛不了。需要**确定性迁移**（At 时间码 → 自然英文时间顺序），这是规则驱动的机械改写，有先例：qwen_repair_loop 按时长重算对齐句；② 拆镜（S6 7 秒→两镜）补丁格式做不了，要走“整集重出 P4”或者专门的拆镜补丁；③ 补丁环用完以后没有自动升级（没有写进 #/queue，也没有派单），只在 master_check 里显示 | `tools/pipeline/p4_adapter.py`（check_p4）、`tools/script_rsi/autoflow_agent.py`（补丁环、收稿）、`tools/pipeline/repair_chain.py` |
| 2 资产全部登记 | ❌ `_ready_ep01.json`：ready=False，gaps=1（`sheet-lead_f-O4`，03:15 刚生成，状态 running）。item 作业连续失败：ch_jiang_yubai acc1 / outfit1、ch_zhuo_lin acc1 / outfit1，原因是 Q9 brand_logo、prompt_vlm 判“画面里有人台”，attempts=2 | ① 单品作业的出图提示词要排除 logo 和人台（这是规则缺口，不是运气问题）；② asset_worker 的 `voice=false`、`golden=false`（master_check ④）；③ 集级 BGM 没有产出目录（`data/music/series10_v2` 不存在） | `tools/pipeline/asset_worker.py`、`asset_checks.py`、`config/pipeline/asset_worker.json`、`tools/bgm/bgm_library.py` |
| 3 首帧 / 尾帧通过契约并亲审 | ❌ 0/11。sop_gate 提示词探针 0/11：镜 1–7、10、11 全是“拒绝：镜 N 的人物是 […]，只出祁念（lead_f）单人镜”；镜 8 是 I3 设定图缺失 | ① **golden_v2 写死了单人和人名**：`golden_v2.py:96-99` `if names != {"祁念"}: raise SystemExit`，`:95` `ep = s.episodes[0]` 不管 `--episode`。这是 V2 内容写进了代码，第 2 集起完全不可用；② 出图执行要走 producer（多人、多集、redo 阶梯、种子流、借道、takes.json），但 producer 从没为 V2 开过（runs.json 里 series10_v2 的 status=preparing，`producer.py:1883`：runs.json 的 status 不是 producing 就自动暂停）；③ 尾帧在 V2 没有入口；④ 总调度亲审签字（master_review）没有代码落点：sop_gate 只认 `take.master_reject`，没有“已亲审”字段 | `tools/autopilot/producer.py`、`config/pipeline/runs.json`、`tools/master/sop_gate.py`（提示词探针 `prompt_probe` 指向 golden_v2）、`gen_contract/postflight.py` |
| 4 视频在 Q9 之后、过视频检查 | ❌ 0 条。`vqa.json gate.video_requires_q9` 已改成 true（MERGE-VID-O） | ① passed_frames 只读 takes.json（`build_jobs.py:174`），V2 首帧在 ab 账里 → 视频链永远拿不到首帧；② 服务器 vidgen 跑的是 `video10_srv` 里的副本，md5 和 system_version 部署的副本、笔记本上的都不一样（C-3）；③ score_clip / motion_qc 在 V2 没调过（CARRYOVER C 表） | `tools/series10_video/build_jobs.py`、`deploy.py`、`tools/qa/system_version.py` |
| 5 整集预览 | ❌ | `ns_post/assemble.find_source` 写死 `data/renders/epNN`（`assemble.py:349`）；V2 的视频片段写在 `data/pipeline/runs/<run>/video/clips/`（sop_gate `check_video` 认这里），预览和片段两边的路径要对齐；BGM 见第 2 项；配音只认 voices_v2（`night.py:241-249` 已按剧） | `services/post/ns_post/assemble.py`、`tools/assemble_episode.py`、`tools/series10_video/run_ctx.py` |
| 6 成人镜头标“待项目方触发” | ⚠ 编译器的成人判定在（`compiler.py:517`），golden_v2 遇到成人镜就拒绝；但 sop_gate 的逐镜判定**不排除成人镜**（`_per_shot` 的 want = 本集全部镜，`sop_gate.py:252-260`）→ 只要有一个成人镜，本集就永远过不了“出图” | sop_gate 要读 shot.adult，把成人镜记成 `pending_owner`，不算阻断 | `tools/master/sop_gate.py` |
| 7 复盘、记忆和 harness 更新、指标入账 | ⚠ `RETRO_ep01.md` 是 draft；`episode_retro done` 只看人工勾选（`- [x]`），没有机器核对 | 复盘清单要能机器验证（E.4）；指标读错了账（`episode_metrics.py:134`） | `tools/master/episode_retro.py`、`episode_metrics.py` |

**关键路径估算**：只要第 1 项（写作闸门）和第 3 项里的“出图走 producer”不解决，后面五项都开始不了。这两件事都不是“再修一个 bug”，而是**接回主干**。

---

## C. 丢失和退化（只写 CARRYOVER 没有覆盖的部分）

| # | 问题 | 证据 | 影响 | 建议 |
|---|---|---|---|---|
| C-1 | **V2 出图不走 V1 主干**：redo 阶梯、自动重出、借道调度、哨兵工单、尾帧、画布版本链，V2 全部没有 | `golden_v2.py:2`“scope=ab，不写 takes”；`data/renders/series10_v2` 不存在；producer V2 目录只有 log | C-04“不过就自动重出”、C-16 出图顺序、L-124 按集出视频，V2 全部做不到 | 第一阶段并回（G.1-4） |
| C-2 | “当前剧”有三个来源（run.json / runs.json primary / NS_RUN） | A.2 第 0 行 | 根因模式 #1；episode_pipeline watch 以为自己在跑 series10_v2，实际按的是 V1 的触发规则 | run.json 退役，改为全部调 `runs.current_run()`；arch_scan 加一项计数 |
| C-3 | **服务器上有三份代码**：视频 worker 跑的 `/root/work/fredw/video10_srv`（11-02 18:08）不是 system_version 部署的 `offline_20261101/repo`（11-02 21:04） | md5 实测：video10_srv `32cf3aa4…`、offline repo `f479d887…`、笔记本 `2cda1b3a…`。部署工具也是三套：`system_version.py deploy`（resident_sync.R）、`series10_video/deploy.py:3,31`（video10_srv）、`series10_imggen/server_deploy.py:26`（imggen_srv） | 根因模式 #2；sv-17 发了版，视频 worker 也不会换代码；MERGE-VID-O 的改动到不了服务器 | 只留一个服务器代码根（offline repo），video10_srv / imggen_srv 改成软链接或退役；verify 核运行中进程的 cwd 和文件 sha |
| C-4 | 服务器上有遗留实验进程在跑 | gpu33 `bench2.py h3`（3 天 7 小时，V1 目录）、`nsfs_canvas uvicorn`（services/canvas_api 老部署）、`audio_post.py watch`；gpu36 bakeoff `run.py gen`（1 天 15 小时） | 占显存、占 ComfyUI 队列；lanes 判“空闲道”时会把它们算成忙 | 列清单交总调度，确认后停（线上动作，要先审） |
| C-5 | 阶段模型有六套，网页读的是 V1 的 S1–S5 | A.2 第 11 行；`app.py:1152` | L-146 的步骤条要“各步完成集数”，现在没有唯一的数据源 | sop_gate 作为唯一阶段模型，开 `/api/master/sop`；ns_api/sop.py、flow.py、stage_status.json 改成从它派生或退役 |
| C-6 | RSI 计分板按一个没人写的文件判“走到哪一段” | `scorecard.py:84-89` 读 `stage_status.json`；这个文件没有写入方（全仓 grep 只有两个读方），内容停在“S1 故事线等你看：32/40” | SCORECARD、v2_live 的阶段一直显示 S1 | 改读 sop_gate.status |
| C-7 | 指标、闸门、出图三方读写的金样账不是同一个文件 | `episode_metrics.py:134`（v2_golden）、`sop_gate.py:236`（v2_golden_epNN）、`golden_v2.py:395`（写 v2_golden_epNN） | RETRO 里“阶段 B 时长”“出图一次通过率”算错，或者算成 null | 统一到 takes.json（C-1 解决后自然消失） |
| C-8 | producer 的 V2 路径里还有 V1 写死项 | `producer.py:556-558`：`music = data/music/series10`、`eps_out = data/episodes/series10`、`review = review_pages/series10_video`；voice 对象的等待文案是“VOICE10 定本剧演员表（config/voices.json）”（`:1263`） | producer 一旦为 V2 打开，配音、BGM、合成、预览四个对象都会指向 V1 | 和 C-1 一起改，改成调 run_ctx 和 run_media |
| C-9 | 导入有一个绕过闸门的入口 | `ns_api/wizard.py:178` 直接 `ctx.script_json.write_text(...)`，不经过 import_script（`:288` 的 V1 守卫、strict lint） | 新建剧向导会把没过闸门的稿写成导入稿 | 改成调 import_script，或者在向导里禁用写导入稿 |
| C-10 | 生产依赖放在一次性命名的目录里 | `postflight.py:4-6` 的 Q1/Q3/Q6/Q5 靠 `tools/series10_imggen/score_remote.py`、`hands_remote.py`；asset_worker 的借道靠 `tools/debug/lanes.py`；规则 `acting.py` 有两份 | 退役一次性目录时会把生产搞断；也说明“哪些是主干”在目录结构上看不出来 | D 节模块地图：迁到 qc/ 和 render/ 下 |
| C-11 | 运行中的代码大量没进版本 | `git status` 自 sv-16（11-02 21:04）以来有 **282 个未提交改动**（services/api 25、apps/web 19、services/agent 17、docs/master 15、tools/script_rsi 10…）；arch_scan 最新一次 `untracked_code=26`（基线 0）；常驻进程加载的就是这些工作区文件 | 根因模式 #7 / #9：线上跑的是没复审、没发版的代码；出了问题没有可回退的版本 | 第一阶段开头先做 Fable 复审 + sv-17 cut（G.1-0） |
| C-12 | 补丁环用完以后没人接 | `autoflow_ep01.json` next_action=“交总调度”，但 pending_requests=0，也没有生成 #/queue 条目 | 系统静默停住；C-01“不靠 Claude 驱动”反向退化 | 补丁用完 → 自动 report_issue 并进 master_check 红灯；“规则迁移”类失败走确定性迁移 |
| C-13 | 改规则（L-141）以后没有“已有稿迁移”这一步 | L-141 改的是 H3 的 At 写法，旧稿 4 个镜立刻不合格，补丁环收敛不了（B 第 1 项） | 以后每改一条写作规则，在制的集都会卡死 | SOP 加一条：改规则必须同时给出迁移器或者“整集重写”的触发器；decision_check 检查新 L-xxx 有没有迁移说明 |
| C-14 | sop_gate 的出图阶段把成人镜算成阻断 | B 第 6 项 | 含成人镜的集永远“没做完” | 见 B 第 6 项 |
| C-15 | V2 首帧在网页上看不到 | A.2 第 7 行 | C-09 / C-12：总调度亲审和项目方修改都没有界面 | C-1 解决后走画布 |

---

## D. 模块地图与工具收敛

### D.1 现状规模（实测）
- tools/ 下有 47 个子目录和 39 个顶层脚本。引用计数（在 services、tools、ops、web、config、tests、packages 里 grep 路径或模块名；脚本在 scratchpad 的 refs.py）显示，**外部引用为 0 的有**：ab_motion_compare、ab_motion_fix、ab_quality、qwen_task、rr_recover_video_takes、imgedit/、ui_smoke/（空目录）。**只被测试引用的**：color_match_clips、g2_candidates、gpu_grab、parser_diff、script_chat_repair。
- arch_scan 最新一次（`data/sysarch/scan_latest.json`，11-03 03:09）：hard_run 59、hard_import_path 127、hard_path 133、silent_read 307、nonatomic_json 214、untracked_code 26。

### D.2 目标模块地图（14 个顶层模块 + 1 个隔离区）

| # | 模块 | 包含（现有部件，只搬不重写） | 唯一入口 / 唯一事实 |
|---|---|---|---|
| 1 | `core/run` | runs.py、run_paths、state_paths、hosts | `runs.current_run()`、`runs.*_dir(run)`；run.json 退役 |
| 2 | `writing` | script_rsi（autoflow、autoflow_agent、rubric、judge、v1_leak）、pipeline（run_chain、chainlib、p4_adapter、repair_chain、writer_prompt）、validate_qwen_script、qa/writer_lints、acting_lints、knowledge/compile、factory/agent_dispatcher | autoflow_resident → autoflow |
| 3 | `import` | import_script、ns_agent/importer、spec_import、hard_constraints、build_state_timeline | `import_script.import_run(run, ep)`（wizard、inbox、mailbox、orch 都改成调它） |
| 4 | `assets` | pipeline/asset_jobs、asset_worker、asset_checks、owner_pick、v2style（voice_v2、looks、bgm_themes）、gen_scenes | 资产清单 manifest（带 sha） |
| 5 | `compile` | ns_agent（compiler、frame_job、asset_refs、framing、bible、shot_language、camera_norm）、director/shot_v2 | `frame_job.build_first` |
| 6 | `render` | ns_render、producer、debug/lanes（转正）、netfix/dispatch、seed_stream | producer → takes.json（**唯一出图账本**） |
| 7 | `qc` | gen_contract（preflight、postflight、remote_score、clip_srv）、series10_imggen/score_remote 和 hands_remote（搬进来）、vqa（server、contract、anomaly、accept、vlm_pool）、identity_metric | `postflight.evaluate`（golden 的 bundle 并进来） |
| 8 | `video` | series10_video（改名 video：build_jobs、night、vidgen、score_clip、deploy 并进 system_version）、ns_recipes、h3_video、motion_qc | night → build_jobs → vidgen |
| 9 | `post` | ns_post、assemble_episode、cut_export、director（finish、post_pass、film_score）、bgm、poster | `assemble(run, ep)` |
| 10 | `infra` | netfix、factory（sync、resident、hosts、api_watchdog）、qa/system_version、ops/*.ps1 | system_version cut / deploy / verify（覆盖所有服务器代码根） |
| 11 | `harness` | master（sop_gate、master_check、episode_retro、episode_metrics、episode_ready、report_issue、pending_requests）、qa/decision_check、arch_scan、iter_gate；以后的 switch、deliver、brief | `sop_gate.evaluate` = 唯一阶段模型 |
| 12 | `observe` | sentinel、monitor、scorecard、rsi | 只读 harness 和账本 |
| 13 | `api` | services/api（按上面 1–11 分组 router） | — |
| 14 | `web` | apps/web | — |
| 15 | `lab/`（隔离区，生产代码不许 import） | ab/、ab_*.py、bakeoff/、imgfix/、imgmaster/、imglab/、vidlab/、video_rca/、lab_ep02/、ep02_director/、ep02_iter/、prompt_v2/、iterate_loop/、localgpu/、research/、perf/、workflow_lib/、promptfix/（golden_v2 的判定并进 qc 以后）、cast_v2、assetmaster/、voice10/、char_assets/、gen_assets*.py、qwen_*.py、script_chat_*.py、services/orchestrator、services/canvas_api，以及上面那些 0 引用脚本 | arch_scan 加一项 `lab_import`：生产代码 import lab 的次数只许减不许增 |

### D.3 收敛规则
1. **搬之前**先跑 import 图（静态 AST 加服务器 `server_deps.yaml`），被生产引用的先搬到目标模块、留一个转发 shim，等一个版本没人用了再隔离。
2. 一律“隔离、不删”（硬约束）：用 `qa/quarantine_safe_move.py`。
3. 每次搬迁就是一次 system_version，并且 verify 两台机器。
4. 合并顺序按风险从低到高：0 引用脚本 → lab 目录 → 单入口收口（import、run）→ 账本合并（render / qc）→ 服务器代码根。

---

## E. harness：用代码保证四件事

HARNESS-O 已经做了：`sop_gate`（require / filter_jobs / filter_video_specs / video_dispatch_ok / vidgen_guard）、`master_check`（6 节）、`episode_retro`（draft / done 门 + `retro_enforce`）。本节只写**还缺什么**，以及怎么和它们衔接。

### E.1 SOP 不跳步：唯一阶段模型 + 入口全覆盖
- **唯一阶段模型**：sop_gate.evaluate 是唯一的阶段事实。ns_api/sop.py、flow.py、stage_status.json、scorecard.stage_of、v2_live 一律改成从它派生（C-5、C-6）。L-146 的步骤条也读它。
- **入口全覆盖**：现在 `require` 只挂在 golden_v2.render、asset_worker、build_jobs、night 四处。没挂的出图 / 视频派发入口有：**producer 的派单**（第一阶段 V2 主力）、ns_api 的 frame_jobs / regen（画布“修改”重出）、series10_imggen/imggen、服务器 vidgen（只记录、不挡，`sop_gate.py:404`）。
  - 做法：在 `ns_render.unified_frame` 和 `ns_render.h3_video` 的提交函数里**统一调一次 require**，这是最底层的必经点，不再在每个上层工具里各挂一次。
  - 加 arch_scan 度量 `gate_bypass`：直接调 ComfyUI 提交、但调用栈上不经过这两个函数的位置，只许减不许增。
- **证据要与账本一致**：提示词探针要从 golden_v2 换成 `build_first + preflight`（`tools/pipeline/preflight_deps.py` 已经是这个形状），否则多人镜永远是 0/11（B 第 3 项）。成人镜判 `pending_owner`（B 第 6 项）。
- **observe → enforce 的条件写成代码**：sop_gate.json 的 observe_stages 现在靠总调度手工清空。改成：某一阶段在本集已有通过证据，或者连续 N 拍没有误挡，master_check 就给出“可以收紧”；清空 observe_stages 本身走 switch（E.2）。

### E.2 开关有决策依据（switch，L-144：ep01 之后做）
- `tools/master/switch.py set <config> <key> <value> --decision L-xxx`：只有这条命令能改 `config/pipeline/*.json` 里登记过的开关。它写一行 `data/pipeline/switch_log.jsonl`（谁、什么时候、旧值、新值、依据哪条 L 号），然后原子写入配置。
- master_check ④ 现在的 SWITCH_EXPECT 只有 3 条约束。改成：对比开关文件的 sha 和 switch_log 的最后一行；不一致 = 有人直接改了文件 → 红灯，并自动 report_issue。
- decision_check 加一条：新的 L-xxx 如果改的是规则，必须写“在制集怎么迁移”（C-13）。

### E.3 交付有复审（deliver + 复审门，L-144：ep01 之后做；在那之前靠总调度手工派 Fable）
- `tools/master/deliver.py add --by AGENT --files … --issue ISS-…`：交付时登记改动文件的 sha。`deliver.py review --id … --by FABLE --verdict pass|p0 …`：复审人和作者必须是不同的模型（沿用派单器 must_differ_from 的口径）。
- system_version **cut 的闸门**加一条：本次改动里每个代码文件都要对应一条 pass 的复审记录；缺了就拒绝 cut（和 decision_check 同一个位置，`system_version.py:137-184`）。
- master_check ③ 接 deliver，显示“未复审数”。这一节现在写的是“deliver.py 未上线”（`master_check.py:118`）。

### E.4 记忆和文档每集更新（让复盘门可以机器验证）
episode_retro 现在的 STANDARD_ITEMS 是人工勾选（`episode_retro.py:27-37`）。把每一项改成能用代码核对：

| 清单项 | 机器核对 |
|---|---|
| MEMORY / 记忆 | 记忆目录里至少有一个文件的修改时间晚于本集开工时间，并且引用了 `RETRO_epNN` |
| PIPELINE_SOP_V2 | 本集 issues 里每一条阻断，都有 `sop_updated=true`，并且 SOP 文本里 grep 得到它的 ISS 号 |
| 卡点进代码 | 每条阻断 issue 在代码或测试里 grep 得到 ISS 号（第 2 节表里“写进代码 ❌”的条目 = 门不过） |
| 开关 | switch_log 本集的每一行都带 L 号 |
| 指标 | episode_metrics 的 summary 已经落盘，并且 nulls 为空（或者每个 null 都有说明） |
| DoD | sop_gate.evaluate 本集 9 个阶段全过（成人镜 pending_owner 除外） |

`episode_retro done` 只有在上表全过时才写 `retro_status: done`；人工勾选只作为补充。

### E.5 brief（L-144：ep01 之后做）
`tools/master/brief.py --task … --stage …` 自动拼出：SOP 对应步骤的前置条件、system-inventory 里的已有部件（按阶段过滤）、相关 C-xx 定律、根因模式 7 条、当前锁（LOCKS.md）、DoD。派单器的写作包已经有类似的拼装（autoflow_agent.packet），可以复用。

### E.6 和 HARNESS-O 现有部件的衔接
- **不另起**：E.1 改的是 sop_gate 本身（探针、成人镜、入口下沉到 unified_frame / h3_video）；E.2 和 E.3 是 master_check ③ ④ 预留的那两块；E.4 改的是 episode_retro 的 done 判定。
- **顺序**：E.1 属于第一阶段（不做完，第 1 集就过不了 sop_gate）；E.2、E.3、E.5 按 L-144 放到第二阶段；E.4 在第 1 集复盘时就要用，放在第一阶段的末尾。

---

## F. 风险与回归保护

### F.1 会让“能跑的东西”坏掉的改动

| 改动 | 可能坏掉什么 | 保护措施 |
|---|---|---|
| V2 出图改走 producer | producer 有 3431 行，派单经过 NETFIX dispatch 和 partition（CARRYOVER G 表：V1 根目录写死）→ 可能派错剧、写错目录、动到 V1 冻结库 | 先跑 `producer.py dryrun`（`:3076`，用临时根，可以注入失败）对 V2 走一遍；V1 冻结库只读挂载，或者用 sha 快照比对；只开 1 条道试跑 |
| golden 的判定并进 postflight | postflight 是全剧共用的，V1 的 Q 判定口径会变 | 新判定项加开关，只对资产包模式的剧（V2）打开；用 `data/vqa/gate_calib` 的标定集回放，误报率不许上升 |
| sop_gate 改成 enforce、下沉到 unified_frame | 画布“修改”重出、资产作业、海报会被挡住 | 先按“调用方”白名单 observe 一个版本，看 violations.jsonl 再收紧；资产阶段和海报按阶段豁免 |
| 第 1 集拆镜、重新导入 | 镜号会变，scene_locks、资产作业的 shots、asset_jobs 都按镜号记 | 重新导入时用已有的 `reimport_changed_shots` 机制，再加一个镜号映射表；测试覆盖“拆镜后资产作业还能对上” |
| 服务器代码根统一、停遗留进程 | 视频 worker 重启以后，正在跑的作业会丢 | 线上动作走“先审 → 确认项目方没在用 → 有回退”（根因模式 #9）；先停 vidgen 的派单入口，等队列清空再换 |
| 282 个未提交改动一次 cut | 一次带进很多没复审的改动 | 按 agent 拆成几批，Fable 复审后分批 cut；每批 deploy 后都跑 `verify --shot 8` |
| tools 搬家 | 服务器上按路径跑的脚本（night.py 用 ssh 启动 vidgen，`night.py:364`）找不到文件 | 留转发 shim 一个版本；arch_scan `bypass_script` 必须保持 0 |

### F.2 回归保护体系（建议做成第一阶段的一部分）
1. **V2 端到端冒烟（夹具剧）**：在临时根里放一部 3 镜的夹具剧（单人、双人、成人各一镜），用假渲染器和假 VLM，跑完 sop_gate 的 9 个阶段。每次 cut 都要跑。producer 的 dryrun 和 flow.py `--dry-run` 已经有一半的骨架。
2. **两台机器编译一致**：`compile_sha.py` 对本集每一镜比较两台的 prompt_sha（根因模式 #2）。
3. **V1 冻结库不被改动**：对 series10_v1 的导入稿、takes.json、成片做 sha 快照，cut 时比对。
4. **arch_scan 棘轮**：新增 `lab_import`、`gate_bypass`、`ledger_write`（除 producer 和 _add_take 以外写 takes.json 或 ab 账的位置）三项，只许减。
5. **线上动作清单**：重启、停进程、换代码根，一律先审、有回退命令、确认项目方当时没在用。

### F.3 测试实测
全量 `pytest -q -p no:cacheprovider tests`（串行，共收集 3032 个用例，收集阶段 0 错误）。跑了 25 分钟到我设的时限，停在约 83%：**2 个 F**（分别在约 18% 和约 47% 处），其余通过，少量跳过。剩下约 17% 没跑，所以没有汇总行，也没定位是哪两个用例失败。建议用 system_version 的 xdist 方式（`-n 12`）补跑全量，再定位这 2 个 F。原始输出在 `C:\Users\fredw\AppData\Local\Temp\claude\C--Users-fredw\e8d12603-324c-42ac-bcc6-1b7d57747fff\scratchpad\pytest.txt`。结论：测试基本是绿的，但**测试绿不代表 V2 链路通**。B 节列出的断点（两本账、单人限制、视频读不到首帧）没有一个测试覆盖得到，所以 F.2 第 1 条的夹具剧端到端冒烟是必需的。

---

## G. 计划建议（取代 PLAN_V2_MASTER v3 的 §7；§1–§6 保留，按本文修订 §2、§4）

总规矩：代码 agent 同时不超过 4 个，每个都必须挂在当前阶段的关键路径上；Opus 写的东西都由 Fable 复审；线上动作由总调度批准。

### 第一阶段：按 SOP 把第 1 集端到端做完（唯一主线）

| 步 | 目标 | 交付物 | 验收标准（机器可查） | 负责 | 依赖 |
|---|---|---|---|---|---|
| 1-0 | 冻结基线 | 282 个未提交改动按 agent 分批，Fable 复审 → sv-17 cut / deploy / verify | `system_version verify` 两台一致；arch_scan `untracked_code` 回到 0 | Fable 复审 + 总调度 cut | — |
| 1-1 | 写作闸门过 | ① L-141 确定性迁移器（At → 自然英文时间顺序，规则来自 RL-T8/T9，放在 p4_adapter 的修复环节，每次替换都留痕）；② 拆镜：S6 走“整集重出 P4”，或者给补丁格式加 `split` 指令；③ 补丁用完 → 自动 report_issue + master_check 红灯 | `autoflow_ep01.json` gate=ok、import=reimported；`check_p4` 0 阻断；镜数变化后资产作业重新对齐 | Opus 开发 / Fable 复审 | 1-0 |
| 1-2 | 资产就绪 | 单品作业提示词规则（不出 logo、不出人台，写进 asset_jobs 的空镜后缀和负面词）；开 `voice`（switch 带 L 号；switch 工具没上线前由总调度记录）；按剧写入 `data/music/series10_v2/ep01.wav`（bgm_library） | `_ready_ep01.json` ready=True、gaps=0；sop_gate“资产就绪”通过 | Opus 开发 / Fable 复审 | 1-1（镜数确定以后） |
| 1-3 | 提示词阶段 | sop_gate 探针改用 build_first + preflight（preflight_deps 的形状）；删掉 golden_v2 的单人限制和人名写死，或者直接不用它做探针；成人镜判 pending_owner | 提示词阶段 ≥（非成人镜数）/（非成人镜数）通过；两台 prompt_sha 一致 | Opus 开发 / Fable 复审 | 1-1 |
| 1-4 | **出图并回主干** | ① runs.json series10_v2 → producing；producer 的 V2 路径去掉 V1 写死项（C-8）；② golden 的 bundle 判定（逐条看图 + 年龄 + OCR）并进 postflight（只对资产包模式的剧打开）；③ sop_gate.require 下沉到 unified_frame 提交函数；④ 先跑 producer dryrun，再开 1 条道，再开全部道；⑤ takes.json 加 `master_review` 字段（总调度签字），sop_gate“出图检测”认这个字段 | 每个非成人镜都有过契约、过 Q9 的首帧，并且有总调度签字；画布能看到；`data/ab/v2_golden_ep01` 不再有新写入；出图一次通过率、Q1 入账 | Opus 开发 / Fable 复审；签字由总调度 | 1-2、1-3 |
| 1-5 | 尾帧 + 视频 | producer 的 last 对象对 V2 生效；视频 worker 代码根并进 system_version（停 video10_srv 由总调度批准）；passed_frames 读 takes.json（1-4 以后自然成立） | 每镜都有视频片段，单镜 ≤6 秒，每条都是先过 Q9 再出；score_clip 已跑 | Opus 开发 / Fable 复审 | 1-4 |
| 1-6 | 整集预览 | assemble.find_source 按剧取路径；预览接 voices_v2 和集级 BGM；本地审片页 | `data/episodes/series10_v2/ep01*.mp4` 存在；审片页能本地打开；sop_gate 9 个阶段全过 | Opus 开发 / Fable 复审 | 1-5 |
| 1-7 | 复盘 | episode_retro 的 done 判定改成机器核对（E.4）；episode_metrics 改读 takes.json；RETRO_ep01 写完；记忆压缩更新 | `retro_status: done` 由代码判定；指标和基线对比入账 | Opus 开发（retro 改造）/ 总调度写复盘 / Fable 复审 | 1-6 |

并行度：1-2 和 1-3 可以并行；1-4 是最大的一块，单独一个 Opus。整个第一阶段同时最多 3 个代码 agent。

### 第二阶段：harness 补全（L-144）
- 目标：规矩完全靠代码约束，不靠自觉。
- 交付：switch（E.2）、deliver + 复审门（E.3）、brief（E.5）；sop_gate 成为唯一阶段模型，开 `/api/master/sop`；ns_api/sop.py、flow.py、stage_status.json、scorecard.stage_of 改成从它派生；L-146 步骤条读它（UI 由 NAVFLOW 线做）；arch_scan 新增 `gate_bypass`、`ledger_write`、`lab_import`。
- 验收：master_check ③ ④ 能显示真实数字；任何开关被直接改文件都会红灯；cut 时缺复审就拒绝；网页步骤条的数字和 `sop_gate status` 一致。
- 负责：Opus 开发 / Fable 复审。依赖：第一阶段完成。

### 第三阶段：收敛（D 节）
- 目标：每个阶段只有一个入口、一个账本，服务器只有一个代码根。
- 交付：run.json 退役；导入只留 import_script（wizard、orch 改造）；golden_v2 的出图路径、cast_v2、imggen.py 隔离；score_remote、hands_remote、lanes 搬进 qc / render；lab/ 隔离区成形；video10_srv、imggen_srv 退役；服务器遗留进程清掉（C-4）；acting.py 只留一份。
- 验收：D.2 里每个模块都只有一个入口；arch_scan 的 hard_run、hard_import_path、lab_import 都下降；V1 冻结库 sha 不变；夹具剧冒烟通过。
- 负责：Opus 开发（按风险从低到高分批）/ Fable 复审。依赖：第二阶段的 deliver 门（每一批都要有复审记录）。可以和第四阶段的写作部分并行。

### 第四阶段：第 2 集（测量集）
- 目标：同一套系统再跑一遍，核心是减少介入；L-143 结构化控制从这一集开始逐项 A/B。
- 验收：PLAN §1.3 的 ep02 目标（自动化 ≥60%、介入 ≤20、一次通过率 ≥60%、GPU ≥40%），退步的项必须立项修。
- 负责：系统自己跑 + 总调度只看 master_check；A/B 由 Opus 开发、Fable 复审。依赖：第一阶段 RETRO done（sop_gate 的 retro_enforce 会强制这一点）。

### 第五阶段：第 3–10 集（自治集）
- 目标和验收沿用 PLAN §5；连续两集不达标就停下来做专项修复。

---

## 需要总调度决定
1. 🔴 第 1-4 步“出图走 producer”还是“临时把 golden 通过的图登记进 takes.json（register_takes 桥接）”。本文推荐走 producer（符合 L-137）；桥接更快，但会把双入口留下来。属于架构决定，按 core 记忆应先和项目方讨论。
2. 🔴 拆 S6：整集重出 P4（会改动其他镜），还是给补丁加 split 指令（要开发）。
3. 🟡 停掉服务器遗留进程（bench2、bakeoff、nsfs_canvas、audio_post）、退役 video10_srv：线上动作，需要批准。
4. 🟡 282 个未提交改动的复审和发版顺序。
