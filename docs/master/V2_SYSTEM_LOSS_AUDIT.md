# V2 系统部件丢失审计（SYSAUDIT-F，11-03 03:3x，只读）

> 起因：项目方 11-03 04:5x“系统层面，你也删掉很多东西。” L-125 只切割内容（剧本 / 人物 / 资产），系统部件应全部保留并继续迭代。
> 本审计只看**系统功能和运行部件**（常驻、接口、工具、隔离区、git 删除、配置开关）；规则与闸门见 docs/master/V1_TO_V2_CARRYOVER.md（CARRYOVER-F），不重复。
> 证据口径：本机 ps / 端口实测 03:1x–03:2x；远程只经 tools/netfix/rsh.py 只读命令；代码行号为当前工作树。未改任何文件、未重启任何进程。
> 优先级：P0 = 挡住第 1 集走完 PIPELINE_SOP_V2 10 步；P1 = 影响自动化 / GPU 利用；P2 = 其他。

## 一句话结论

路由、代码文件、规则在 git 里**一条都没删**（457e9e8 → HEAD 删除 0 条，新增 30 条路由）。丢的是**运行面**：V1 停机（11-02 18:2x）后，V2 的 producer / night 没有在任何一台机器上重新拉起，笔记本上的 producer / episode_pipeline / infra_watchdog 还是切 primary 之前启动的老进程（进程内缓存 RUN_ID=series10_v1），阶段 B 执行器 golden_worker.py 被整个移进隔离区，再加 runs.json status=preparing + golden 开关关着——结果 5 条出图道空转 ≥ 8 小时（S1 五道利用率 0.00），第 1 集卡在步骤 9/10 前面。

## 总表

| # | 部件 | V1 状态 | V2 现状 | 证据 | 怎么丢的 | 恢复建议 | 优先级 |
|---|---|---|---|---|---|---|---|
| **1 常驻和循环** |||||||
| 1.1 | producer（笔记本） | serve 常驻，心跳 data/producer/heartbeat.json | **没有 V2 producer**。在跑的 pid 13972 是 11-02 01:45 启动的（run.json 18:5x 才切 V2），RUN_ID 启动时读入 = series10_v1，心跳仍写 data/producer/heartbeat.json（03:13）；data/producer/runs/series10_v2/ 只有 log.jsonl（最后 00:59），无 heartbeat / registry；GET /api/producer/status → service_alive=false | tools/autopilot/producer.py:77 `RUN_ID = _run_id_from_config()`（导入时一次）；Get-Process 13972 StartTime 11/2 01:45；config/pipeline/run.json run_id=series10_v2；services/api/ns_api/producer.py:23-25 按 V2 目录读 | 没接（切 primary 后没重启）+ 写死（进程内缓存） | 受控重启 producer.py serve（会读 run.json=series10_v2，Paths → data/producer/runs/series10_v2）；同时见 6.1（status=preparing 会让它自暂停） | **P0** |
| 1.2 | producer（gpu33 / gpu36） | 两台各一个 serve（分区 ep 奇 / 偶），18:13/18:14 起 | 两台 run/producer.pid **DEAD**（1491152 / 3300337），heartbeat 31,4xx s 没更新；data/producer/runs/series10_v2/heartbeat.json MISSING；alerts A-RESIDENT-PROD-gpu33/36 crit 523 分钟 | rsh ps -eo + kill -0；data/qa/alerts.jsonl 03:18:43/47；ops/offline/ensure_runs.sh 只起“非 primary 且 producing”的剧 | 关掉（L-125 停 V1 后没为 V2 重起）+ 没接（无人管 primary 常驻） | resident_sync.py restart HOST（resident_restart.sh 起 producer 读服务器 run.json=series10_v2）；并在 resident_sync.health 加“primary 常驻挂了自动 restart_guarded” | **P0** |
| 1.3 | night（视频链，服务器） | 两台 night.pid 18:13 起，18:2x 停 | 两台 night.pid **DEAD**（1491154 / 3300339）；笔记本无 night 进程；data/pipeline/runs/series10_v2/video/ 只有 inputs/，night_state.json MISSING；A-RESIDENT-NIGHT crit | rsh；night.py:35-47 已按 run（--run / NS_RUN，MERGE-VID-O）；ops/factory/systemd/ns-night.service 未安装（systemctl 无 ns-night） | 关掉 + 没接 | resident_sync restart HOST（默认模式含 night）；或先在笔记本 night.py --run series10_v2 --once 验证 | **P0** |
| 1.4 | 阶段 B 金样首帧执行器 golden_worker | （11-03 新建，无 V1） | tools/pipeline/golden_worker.py **不在树里**，只在 data/_quarantine_20261103_golden_o/tools/pipeline/（02:33 移入，目录无 MANIFEST，文件从未进 git）；tests/test_golden_pipeline.py 同移；树内无任何 tick_golden / golden_worker 调用者；asset_worker.py:15“golden 作业本轮只生成不执行”；asset_worker.json golden=false | ls / grep -rn golden_worker；git log 为空；config/pipeline/asset_worker.json:golden | 隔离 + 关掉 | 从隔离区还原（先修 ISS-1103-023528 的 tick_golden(reserve) 签名）→ 跑 test_golden_pipeline → asset_worker.json golden=true | **P0** |
| 1.5 | episode_pipeline watch | pid 21792 11-02 02:34 起，盯 V1 导入 | 只认 data/import/script_v2.json（:47/:96/:121），判不出项目退回 series10_v1 run_dir（:55）；V2 导入稿 data/import/runs/series10_v2/script_v2.json（00:59）它看不见 | tools/autopilot/episode_pipeline.py 行号；Get-Process 21792 | 写死 V1 | 改读 run_paths 后重启；若 V2 由 asset_jobs/golden 取代则明确停掉（S16 清单同步改） | P1 |
| 1.6 | infra_watchdog | pid 6976 11-02 14:07 起 | A-NIGHT/A-IDLE 读 VID=data/pipeline/runs/series10_v1/video（:30,:138,:289），A-PROD 读 data/producer/heartbeat.json（:295）→ 看的全是 V1；V2 producer/night 在笔记本死了不会报 | tools/autopilot/infra_watchdog.py 行号 | 写死 V1 | 改读 runs.primary + producer_dir / vid_rel，重启 | P1 |
| 1.7 | SENTINEL（探针 + SLO） | serve 常驻 | 进程 21:23 起（切割后），但探针读 data/producer/registry.json(:130) / log.jsonl(:217,:712) / control.json(:444,:740)、data/renders/ep*/S*/takes.json(:489) = V1 路径 → S2/S3/S7/S8/S13/S17 评的是 V1；S6 每拍 AttributeError；S0 报“读不到 data/rsi/scores.jsonl”而文件在（03:16 更新）；open.json 58 单多为 V1 遗留 | tools/sentinel/probes.py 行号；data/sentinel/sentinel.log 03:14-03:16 | 写死 V1 | probes 改按 run（RUNS.primary_run 已有，:590/:764/:792 用了）；修 S0/S6 后重启 sentinel | P1 |
| 1.8 | 8810 监控看板 | 在跑 | 在跑（pid 45152 11-02 11:04 起，切割前）；/api/status 10 s 返回，remote_procs 为空，无 run 维度；gpu / alerts / sentinel / rsi 正常 | curl :8810/api/status；tools/monitor/server.py 无 runs.json 读取 | — | 重启载入新代码；加 run 字段 | P2 |
| 1.9 | v2_live 实时页 | — | 在跑，data/review_pages/v2_live/index.html 03:28 更新 | ps 8460/10336 | — | — | 正常 |
| 1.10 | resident_sync loop（sync auto） | loop 常驻 | 在跑（19:48 起），health 每 5 分钟；**只报警不拉起 primary producer/night**（:709-711），ensure_runs 只管非 primary producing（ensure_runs.sh:2）；factory_sync auto 线程在 | tools/autopilot/resident_sync.py:981-1012, 545-550 | 没接 | 加 primary 常驻自愈 | P1 |
| 1.11 | autoflow_resident + asset_worker + agent_dispatcher + hollywood_tick | — | 在跑（02:39 起，runs=[series10_v2]，tick 72）；dispatcher enabled、ep02 派单 done；hollywood 待打 35 张、看图忙时让路 | data/factory/autoflow_resident.json；agent_dispatcher.py status；hollywood_tick.py status | — | — | 正常 |
| 1.12 | api_guard / api_watchdog（:8800） | 看门狗起 uvicorn | 在跑（11-03 02:39 起），只记不重启（设计） | ps 17664/21240；tools/factory/api_watchdog.py:3 | — | — | 正常 |
| 1.13 | VQA 看图（笔记本 8870、gpu36 路由 8871） | — | 8870 loaded、served 255；8871 router dedicated、2 实例（8876/8878）；vqa.json 写的是 3 实例（8879 不在） | curl /health；config/vqa.json:6,:32 | 没接（第 3 实例） | 查 gpu36 :8879 | P2 |
| 1.14 | ComfyUI 道 | gpu33 0/1/3、gpu36 0/1 | 5 条全活（systemd ns-comfy@*），util 全 0、空转 ≥ 8 h；S1 五道 0.00 | rsh ps；/api/render/lanes reachable；open.json S1 | 上游 1.1–1.4 没起 | 同 1.1–1.4 | （归 P0） |
| 1.15 | 隧道（tunnel_supervisor / puller / tcpbridge） | — | 在跑；A-TUNNEL-18290 open 是 L-100 退役道 | ps；alerts open | — | 把 18290 从 infra_watchdog.TUNNELS 已去，关掉遗留报警 | P2 |
| 1.16 | 开机自启 / 计划任务 | register_owner.ps1 应注册 Laptop-Autostart + 5 个 NSFS-sync | 实际只有 NS-Studio-Monitor-Guard / ResidentSync-Guard / TunnelSupervisor / Autostart-Trial；**没有 NSFS-sync_* 任务**，autoflow_resident / vqa / v2_live 无守护 | Get-ScheduledTask；ops/autostart/README.md | 没接 | 项目方运行 register_owner.ps1；给 autoflow_resident 加 guard | P1 |
| 1.17 | S16 常驻进程清单 | 10 个 | 不含 autoflow_resident / agent_dispatcher / sentinel / v2_live；仍含 episode_pipeline | config/policies/sentinel.yaml:149-163 | 没接 | 补清单 | P2 |
| **2 服务和接口（ns_api）** |||||||
| 2.0 | 路由总数 | 457e9e8：320 条 | HEAD：350 条；**删除 0**，新增 30（cut-project / ep preview / frames-index / frame-queue / owner inbox+pick / script-library / v2 assets / v1-library…）；app.py 增 v1_guard.deny 中间件（只拦 renders/<非当前剧>） | comm routes_old/new；app.py 36-40,182 | — | — | 正常 |
| 2.1 | /api/producer/status | V1 心跳 | service_alive=false（接口按 V2 目录读，V2 无心跳） | curl | 归 1.1 | 归 1.1 | （P0） |
| 2.2 | /api/frame-queue（全系统出图队列 + “修改”排队） | V1 registry | 读 data/producer/registry.json（legacy）→ V2 页面显示 V1 ep02 的 51 条 queued | services/api/ns_api/frame_edit_queue.py:34 | 写死 V1 | 改 run_paths.producer_dir | P1 |
| 2.3 | /api/voices | config/voices.json | 仍返回 V1 林晚 / 顾辰 / 陈宇音色；shot_audio 已按剧取 voices_v2（P1-13a） | asset_center_p1.py:243-245；shot_audio.py:66 | 写死 V1 | 按剧取 voices_v2.json | P1 |
| 2.4 | /api/look-schedule、/api/looks/* | data/looks 全局 | character_defaults 仍是 lin_wan/gu_chen/chen_yu/ch_a_lan | looks.py:127；data/looks/ 不分剧 | 写死（全局文件） | V2 用 assets_v2 清单，接口按剧返回空或切源 | P2 |
| 2.5 | /api/revisions/keys、/api/decision-locks | 全局 | 返回 identity:ch_a_lan、L-122 林晚等 V1 条目 | curl | 全局不分剧 | 加 run 过滤 | P2 |
| 2.6 | /api/readiness | renders_gpu3 镜像 | continuity_sheet_path=renders_gpu3/ep01/…（V1 布局） | readiness.py:6-8,:75 | 写死 | 按 run | P2 |
| 2.7 | /api/projects、/api/sop/status | weita 为默认项目 | current=weita（status legacy，root=仓库根） | curl | 旧模型未并入 runs.json | 以 runs.json 为唯一来源 | P2 |
| 2.8 | /api/jobs | V1 作业 | 返回 V1 作业（最后 11-02 16:55 ep05-S6 failed） | curl | 全局 | 按 run | P2 |
| 2.9 | /api/character-hub | — | project=series10_v2 characters:[]（V2 人物在 assets_v2/manifest，接口没接） | curl | 没接 | 接 assets_v2 或下线 | P2 |
| 2.10 | /api/music | data/music/series10 | episodes:[]（按剧取 data/music/<run>，V2 集级配乐还没产出；曲库 data/music/v2_style 在） | bgm_api.py:31-41 | 内容未到 | — | — |
| 2.11 | /api/image-workshop/jobs | — | GET 404 = 只有 POST（image_workshop.py:62），正常 | — | — | — | 正常 |
| **3 工具和流水线** |||||||
| 3.1 | pipeline（asset_jobs / asset_worker / asset_checks / image_jobs / repair_chain / vlm_pool） | — | 阶段 A 在跑；image_jobs 按 run 取导入稿（:153）；repair_chain.py:32 写死 data/import/script_v2.json（V1 返修工具） | 代码行号 | repair_chain 写死 | repair_chain 加 --run | P2 |
| 3.2 | series10_video（night / build_jobs / vidgen） | V1 | 代码已按 run（MERGE-VID-O：run_ctx.resolve / vid_rel）；**没有进程**（见 1.3）；两台 vidgen.py run 在跑但 NS_RUN 为空、V2 video 目录不存在 | night.py:35-47；rsh /proc/<pid>/environ | 没接 | 同 1.3 | （P0） |
| 3.3 | bgm（agent / deliver / bgm_library） | data/music/series10 | deliver.out_dir 按剧（:54-55）；agent.py --run 可指 V2；music_v2.json 在 | 代码 | — | 等 ep01 成片后跑 | 正常 |
| 3.4 | assembly（assemble_episode.py 整集预览） | 默认 data/music | --music-dir 默认仍是 V1 目录（:94），V2 需显式传；night.py 调用时按 EPS_OUT 按剧 | assemble_episode.py:94 | 默认值写死 | 默认改 run_media.music_dir | P2 |
| 3.5 | poster | — | 无 run 概念，按输入文件；:8817 http.server 正在服务海报预览目录 | tools/poster/*.py；curl :8817 | — | — | 正常 |
| 3.6 | imgedit / image_workshop | — | tools/imgedit/ab_edit.py:61 写死 data/import/script_v2.json；image_workshop API 按 bases 正常 | 代码 | 写死 V1 | 加 --run | P2 |
| 3.7 | vidlab | config/vidlab/lanes.json | ab_run.py:128 改读 config/factory/hosts.json（SYSARCH 4-2）；lanes.json 删除有替代 | 代码 | — | — | 正常 |
| 3.8 | autopilot/flow.py（编排器） | — | 按 primary_run（:204）；last_tick 03:23 dry=false | data/autopilot/flow/last_tick.json | — | — | 正常 |
| 3.9 | qa：iter_gate / decision_check / decision_propagation / arch_scan / syntax_guard | — | 都在；arch_scan --check 正在跑；iter_gate.h1_hunt 只扫 V1 产物（:553-555）；decision_propagation --dry 退出 1 是规则同步问题（MERGE-OPS-O 已登记） | 代码；ps 44592 | iter_gate 写死 | h1_hunt 改按 run | P2 |
| 3.10 | rsi：scores.jsonl / SCORECARD | — | scores.jsonl 03:16 仍在追加（line=gpu run=series10_v2）；SCORECARD.md 停在 11-02 21:22；S14 出图 / 视频 6.9 h 无新分（V2 无产物可评） | ls -la | 没接（晚报 / 出图视频线无 V2 输入） | ep01 出图后自然恢复；SCORECARD 刷新接入 sentinel | P2 |
| 3.11 | attribution（tools/pipeline/attribute_bug.py） | — | --run 已有（:215） | 代码 | — | — | 正常 |
| 3.12 | master：sop_gate / episode_ready / episode_metrics / report_issue | — | 全部 run-aware；issues.jsonl 18 条 open | grep | — | — | 正常 |
| **4 隔离区（5 个根、42 个顶层目录）** |||||||
| 4.1 | data/_quarantine_20261103_golden_o/ | — | **系统代码**：tools/pipeline/golden_worker.py、tests/test_golden_pipeline.py + 11 个 golden-ep01-S* 作业；无 MANIFEST；移入 02:33-02:38（GOLDEN-O 回退期） | ls；git log 空 | 隔离（当内容处理了） | 还原（见 1.4） | **P0** |
| 4.2 | data/_quarantine/tools/（20 个脚本）+ tests/test_gpu3_tunnels.py + ops/autostart/tunnel*.sh | 一次性 / 重复脚本 | 有 MANIFEST.md 23 项、每项引用检查；gpu3_tunnels 由 tunnel_supervisor 取代 | data/_quarantine/MANIFEST.md | 隔离（有据） | 不还原 | — |
| 4.3 | data/_quarantine/vidlab_20261102/lanes.json | 道表 | 被 config/factory/hosts.json 取代（3.7） | — | 删除有替代 | 不还原 | — |
| 4.4 | data/_quarantine/netfix_20261101/（infra_inject_test.py、laptop_autostart.ps1 旧版、tunnel*.sh、dispatch/merge_pull .before） | — | 注入测试由 tools/netfix/inject_test.py + tests/test_netfix.py 取代 | grep | 删除有替代 | 不还原 | — |
| 4.5 | header_o_* / director_20261102 / imglab_* / debug_rsi_20261102 / merge_img_o / 20261103_autofix_o_demo_v2 / ownership.yaml.bak_* | — | 全是 .before/.bak 备份，原件都在树里（script_chat.py、knowledge/rules/*.yaml、tools/script_rsi/*.py、tools/qa/ownership.yaml） | 存在性检查 | 备份 | 不还原 | — |
| 4.6 | data/_quarantine_20261101b/{code_orig, config_orig, knowledge_orig, docs_orig} | — | .orig 备份；knowledge/rules 里 chain_v1 / edit / research_realism / ui / writer.yaml 都在 | ls knowledge/rules | 备份 | 不还原 | — |
| 4.7 | data/_quarantine_20261101b/golden/{bench.md, facelock, video_smoke, quality_v2_smoke, base_vs_turbo} | 测试金样数据 | 树内 golden/ 仍有 quality_v2 等；tests/test_quality_v2.py 引用 golden/ 能跑；facelock / video_smoke 已无引用 | grep | 隔离 | 不还原 | P2（确认即可） |
| 4.8 | 其余 ~26 项（v1_derived_index、v2_golden_tempstyle/v1style、asset_names、takes_bak 1348 文件、netfix_backfill/sync、prod_*、imgfix_lookA、timeline_o（V2 自己误出的写作包）、stale_tmp、oldscript、20261101b/data|docs|previews） | — | 内容 / 日志 / 图片，属 V1 或一次性产物 | ls | 内容隔离 | 不还原 | — |
| **5 git 删除（d4a10cc 11-02 12:06）** |||||||
| 5.1 | config/vidlab/lanes.json | 道表 | 替代 = hosts.json（ab_run.py:128-139） | git show | 删除（合理） | — | — |
| 5.2 | ops/autostart/tunnel.sh、tunnel_gpu36.sh | 隧道循环 | 替代 = tunnel_supervisor（K-OPS-N01），laptop_autostart.ps1:14-18 已不调 | git show | 删除（合理） | — | — |
| 5.3 | tools/autopilot/infra_inject_test.py | 注入测试 | 替代 = tools/netfix/inject_test.py | grep | 删除（合理） | — | — |
| 5.4 | 457e9e8（切割前最后一版）→ HEAD | — | 无其他删除；工作树无 D 文件 | git diff --diff-filter=D；git status | — | — | 正常 |
| **6 配置开关** |||||||
| 6.1 | config/pipeline/runs.json series10_v2.status | producing | **preparing** → producer.ctrl() 强制 paused_by=runs.json（producer.py:1883）；树内无任何代码会把它翻成 producing | runs.json:28；grep "producing" | 关掉（手工闸门，没人翻） | 阶段 A 过后由总调度改 producing（或加自动条件） | **P0**（归 1.1） |
| 6.2 | config/pipeline/asset_worker.json golden=false、voice=false | — | 阶段 B 执行与配音作业关 | 文件 | 关掉 | golden 随 1.4 打开；voice 待音色定稿 | P0 / P1 |
| 6.3 | config/compile/imgmaster.yaml enabled=false | — | 分段编译只试编（设计 P1） | 文件:3 | 关掉（设计） | — | P2 |
| 6.4 | config/factory/hosts.json gpu36:2、laptop enabled=false | — | L-100 看图专用卡（设计） | 文件:110,:131 | 设计 | — | — |
| 6.5 | config/gen_contract.json Q1d_anomaly enabled=false | — | 先记日志不拦（设计） | 文件:156 | 设计 | — | — |
| 6.6 | config/render_quality.json voice_conversion enabled=false、speaker=gu_chen | — | V1 人名残留 | 文件:1020-1022 | 关掉 | V2 配音定后再开 | P2 |
| 6.7 | config/script_chat.json run_parts 只有 series10_v1，legacy_default=series10_v1；config/script_chat_runs/ 只有 series10_v1*.md | — | V2 没有专属条款文件（HEADER-O 设计为通用规则） | 文件:28-33；ls | 没接 | 需要时加 series10_v2.md | P2 |
| 6.8 | config/recipes/timing_lint.json legacy_runs=[series10_v1]；video_policy.json scope_runs 含 series10_v2；asset_refs.json projects 含 series10_v2 | — | 都已覆盖 V2 | 文件 | — | — | 正常 |
| 6.9 | camera_moves.yaml 多数 enabled=false、voices_v2.json 多数候选 enabled=false、edit_engines firered/krea2 enabled=false | — | 项目方 L-129 只选 bolt_push_settle / 只启用 4 个音色 / 等模型（设计） | 文件 | 设计 | — | — |
| 6.10 | config/pipeline/runs.json series10_s2 status=paused | — | 项目方 16:0x 决定 | 文件:19 | 设计 | — | — |

## P0 清单（已用 tools/master/report_issue.py 登记）

1. **没有任何一台机器在为 V2 跑 producer**：笔记本 pid 13972 是 01:45 起的 V1 进程（RUN_ID 进程内缓存），两台服务器 producer 18:2x 停后未起；runs.json status=preparing 又会让新起的 producer 自暂停。→ 1.1 / 1.2 / 6.1
2. **阶段 B 执行器 golden_worker.py 被整目录隔离、未入 git、树内无调用者，golden 开关关** → 步骤 9 只能“生成作业”不能执行。→ 1.4 / 4.1 / 6.2
3. **V2 视频链没有进程**：两台 night.pid DEAD、笔记本无 night，V2 video 目录只有 inputs/。→ 1.3 / 3.2

## 恢复顺序建议（给总调度，按依赖排）

1. 还原 golden_worker.py + 测试（修 tick_golden(reserve) 签名）→ 受控重启 autoflow_resident → asset_worker.json golden=true。
2. runs.json series10_v2.status → producing（或加“阶段 A 全就绪自动翻”）。
3. 笔记本：受控重启 producer serve（restart_producer.ps1 的心跳 / pid 路径仍是 legacy data\producer\*，重启前先改成 run_paths；否则它会误判心跳）。
4. 服务器：resident_sync restart gpu33 / gpu36（起 producer + night）；在 resident_sync.health 加 primary 常驻自愈。
5. 重启 episode_pipeline / infra_watchdog / sentinel 之前先把 1.5 / 1.6 / 1.7 的 V1 写死改成按 run，否则重启后还是看 V1。
6. 项目方运行 ops/autostart/register_owner.ps1（补 Laptop-Autostart + 5 个 NSFS-sync 任务）。

## 需要你决定

- 1.5 episode_pipeline watch：V2 是改成按 run 继续用，还是确认已被 asset_jobs / golden_worker 取代后停掉并从 S16 清单移除？
- 6.1 runs.json status 由 preparing 翻 producing 的时机：现在就翻（阶段 A 还有 5 个 item 作业连续失败），还是加自动条件？
