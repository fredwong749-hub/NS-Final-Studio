# 系统架构地图 ARCH_MAP（ARCH-AUDIT，2026-11-02 02:3x–03:xx，只读审计）

> 派单：总调度 fredw-2b。范围：进程拓扑、数据流、代码层次、配置与状态、所有权、并发写者、结构性问题、目标架构差距、删繁就简。
> 方法：读代码 + 本机进程/端口探测 + 经 tools/netfix/rsh.py 只读查看 gpu33/gpu36（ps、ss、sha256sum）。全程没有改文件、没有重启。
> 引用写法：`文件:行号`；"实测"表示 02:2x–02:4x 当场看到的结果。路径都相对 D:\NS-Final Studio。

---

## 1. 进程与服务拓扑

### 1.1 总图（现状，不是目标）

```
                     跳板 sz194:19422（唯一入口；HK 线最终也经过它，config/netfix/ssh_config:23-35）
                                   │
笔记本（控制台 + 实际上的半个工厂）       │                       gpu33（3 卡可用；GPU2 坏）           gpu36（3 卡）
─────────────────────────────            │                       ─────────────────────────           ─────────────────────────
tunnel_supervisor ──WSL 主连接×8─────────┼──► sshd ──► fwd.py 18188/89/91 → ComfyUI 8188/89/91   fwd.py 18288/89/90 → ComfyUI 8188/89（8190 已停）
  ├ 内层 -L 1818x/1828x/15180/18098/18099/8871                (systemd ns-comfy@)                  (nohup，无守护)
  └ ensure_puller → puller（outbox 拉取，目前 0 条）          producer serve + night.py            producer serve + night.py
producer serve（经隧道派单，IMAGE_LANES）                      (resident_restart.sh setsid nohup)    (同左)
infra_watchdog（另一套修隧道逻辑）                             canvas bridge 5180 / qwen-mailbox 8099 vqa_router 8870 → server.py×3 (8876/78/79)
ns_api :8800  / vite :5173                                    / audio_post（systemd）              lan_proxy 10.0.0.36:8870（给 gpu33 看图）
resident_sync loop（推代码、health、重启服务器常驻）            人工：pagelock、bench2、v7_lipsync…  人工：bakeoff、video_rca srv_run、pagelock
episode_pipeline watch / monitor :8810 / D:\ns_vqa :8870                                            clip_resident 8872（没在跑）
散落 ssh -L 8875/8877（绕过 supervisor）
```

### 1.2 进程表

| 机器 | 进程 | 端口 | 谁拉起 | 谁监控 | 出处 | 实测 |
|---|---|---|---|---|---|---|
| 笔记本 | tunnel_supervisor serve | 转发 1818x/1828x/15180/18098/18099/8871 | 计划任务 NS-Studio-TunnelSupervisor（每 5 分钟 ensure） | 计划任务；infra_watchdog 看心跳 | tools/netfix/tunnel_supervisor.py:693-707；config/netfix/tunnels.json | 在跑（02:28 刚重启） |
| 笔记本 | puller serve | — | supervisor.ensure_puller | supervisor（锁文件） | tunnel_supervisor.py:611-626 | 在跑；两台 outbox 0 条 |
| 笔记本 | ns_api（uvicorn） | 8800 | laptop_autostart.ps1:30-37 / ops/restart_api.ps1:22（日志路径两处不同） | **无** | — | 200 |
| 笔记本 | vite dev | 5173 | laptop_autostart.ps1:40-43 | **无** | — | 在跑 |
| 笔记本 | producer serve | 客户端连 1818x/1828x | laptop_autostart.ps1:52-57 / restart_producer.ps1:30 | infra_watchdog（只报警） | tools/autopilot/producer.py:78 | 在跑 |
| 笔记本 | infra_watchdog serve | — | laptop_autostart.ps1:24 | **无** | tools/autopilot/infra_watchdog.py | 在跑 |
| 笔记本 | resident_sync loop | — | **人工** / recover 自起（resident_sync.py:1026） | **无** | resident_sync.py:680 | 在跑 |
| 笔记本 | episode_pipeline watch | — | **人工**，没有拉起脚本 | **无** | tools/autopilot/episode_pipeline.py:336 | 在跑 |
| 笔记本 | monitor | 8810 | **人工** | **无** | tools/monitor/server.py:30 | 200 |
| 笔记本 | D:\ns_vqa\server.py（4080 看图） | 8870 | **人工**（仓库外 D:\ns_vqa\start.ps1） | **无** | services/api/ns_api/factory_health.py:29 | 在跑 |
| 笔记本 | infra_sidecar | 8804 | 人工（临时截图） | 无 | apps/web/e2e/uirsi/infra_sidecar.py:40 | 在跑 |
| 笔记本 | 散落 ssh -L 8875→gpu36:8874、8877→8876 | 8875/8877 | 人工，Git ssh 直连跳板 | 无 | 代码里找不到 | 8875 不通 |
| gpu33 | ComfyUI ×3 | 8188/8189/8191 | systemd ns-comfy@ | systemd | — | 在跑 |
| gpu33/36 | fwd.py | 18188/89/91；18288/89/90 | resident_restart.sh:25 | resident_sync health（经跳板） | offline_20261101/fwd.py:4 | 在跑 |
| gpu33/36 | producer serve + night.py | — | resident_sync.restart → resident_restart.sh | resident_sync health，每 5 分钟，经跳板 | resident_sync.py:337 | 在跑，两台都是 sv-20261102-03 |
| gpu36 | ComfyUI ×2 | 8188/8189 | **nohup，不是 systemd** | **无** | — | 在跑 |
| gpu36 | vqa_router + server.py ×3 | 8870 → 8876/8878/8879 | **人工** | **无** | tools/vqa/vqa_router.py:24 | 在跑。**没有 vLLM 进程**（实测 ps），和 config/vqa.json `instances_note` 说的"已切到 vllm_proxy"不符 |
| gpu36 | lan_proxy | 10.0.0.36:8870 | resident_sync.py:585-587 每拍保活 | resident_sync | tools/netfix/lan_proxy.sh:16 | 在跑 |
| gpu36 | clip_resident | 8872 | 人工 | 自带循环 | ops/factory/clip_resident.sh | **没在跑** |
| 两台 | crontab | — | — | — | — | 没有项目任务 |

计划任务（笔记本）：实际只注册了 NS-Studio-TunnelSupervisor，以及一个指向不存在路径 `D:\Coding\NS-Storyboard\ops\autostart\autostart_trial.ps1` 的 NS-Studio-Autostart-Trial。**NS-Studio-Laptop-Autostart 和 5 个 NSFS-* 同步任务都没有注册**（ops/autostart/register_owner.ps1:5-12 从没执行过）；ops/logs/autostart.log 最后一条是 11-01 15:49。也就是说，笔记本重启以后，除隧道之外的所有进程都要人工拉起。

### 1.3 端口与车道表有几份副本
出图道的地址至少写在 5 个地方，内容已经对不上：
- producer.py:78 IMAGE_LANES
- resident_sync.py:453（gpu36:2 → 8190，这个口已经停了）
- 服务器 offline_20261101/fwd.py:4
- config/netfix/tunnels.json（18290、18098 都是死口）
- config/render_endpoints.json

---

## 2. 数据流

R = data/pipeline/runs/series10_v1

| 步骤 | 输入 → 输出 | 写者 | 读者 | 单一事实来源 / 副本 |
|---|---|---|---|---|
| 剧本导入 | script play lib/*.md 或 staged 稿 → data/import/script_v2.json，另写 import_log.jsonl、data/autopilot/imports.jsonl | tools/import_script.py:195（原子写）；API script_inbox；producer.py:1962-2004 import-staged | image_jobs、episode_pipeline、takes_ui | **SoT** = script_v2.json；import/backups 是备份；服务器上的是 tier1 推送副本 |
| 作业编译 | script_v2 → R/assets/first_frame_jobs.json | **只有一个写入口** tools/pipeline/image_jobs.py:264，**直接 write_text、非原子** | producer、flow、full_redo、imggen、remote_preflight | SoT；`.before_*` 是备份；服务器副本、_offline_pull 是副本 |
| 首帧 / 尾帧 | 作业 + 参考图（asset_refs 解析）→ data/renders/epNN/SN/takes.json + 图 | producer（P._add_take / set_active）、:8800 API（takes_ui、frame_jobs）、register_takes、merge_pull | auto_current、night、assemble、画布 | 每镜 takes.json 是 SoT；服务器、renders_gpu3、outbox 里的是副本，**而且服务器副本也会被服务器 producer 写，两边各写各的**，靠 merge_pull 合并 |
| 契约 / 看图 | 版本图 → takes.json 的 postflight / contract | unified_frame.py:259；rescore_takes；vqa 服务只写自己的目录 | producer、night 闸门 | 以 takes.json 为准；attempts.json 只是 producer 的派单账本 |
| 视频 | 合格首帧 → R/video/jobs.json、state_<host>.json、night_state.json → takes.json 的 video | build_jobs.py:391（非原子）；vidgen；night.py:501 → register_takes | night、vidgen、full_redo | state_<host>.json 在服务器上是 SoT，笔记本上是拉回来的副本 |
| 合成 / 后期 | takes active + 配音 + 配乐 → data/episodes/series10/epNN_*.mp4 | night.finalize → ns_post/assemble.py → tools/director/finish.py | 画布、审片页、film_score | 成片是导出物 |

参考图解析（首帧质量的根）：services/agent/ns_agent/asset_refs.py。身份脸、单品图、造型、场景底图都从 data/looks/*、data/assetmaster/*、config/recipes/asset_refs.json 解析，**每个文件读不到都静默回退**（见 §6 问题 #2）。

---

## 3. 代码层次

| 目录 | 管什么 | 主入口 |
|---|---|---|
| services/api（ns_api，约 70 个模块） | 笔记本主 API :8800 | ns_api.app |
| services/canvas_api（ns_canvas） | gpu33 渲染桥 :5180 | 服务器 systemd |
| services/agent（ns_agent） | 编译层：导入、frame_spec、唯一出图作业 frame_job（K-REN-134）、gen_contract 前后检、asset_refs、vqa 客户端 | 库 |
| services/render_router（ns_render） | ComfyUI 客户端、unified_frame、pipeline（takes 读写、set_active）、qc/motion_qc | 库 |
| services/post（ns_post） | 合成 assemble.py（1556 行）、TTS、校色、4K | 库 |
| services/orchestrator（ns_orch） | T42 "开始生产"状态机（老的那条生产线） | API 调用 |
| services/recipes（ns_recipes） | 配方选择、编译、lint | 库 |
| services/qc | **空目录** | — |
| packages/qc（ns_qc）、packages/schema | 度量闸门 PI-01…30；剧本 / 分镜 schema | 库 |
| tools/autopilot | producer（2489 行）、flow、run、episode_pipeline、full_redo、policy、resident_sync（1141 行）、infra_watchdog、state_snapshot | 常驻 + CLI |
| tools/factory | 方案 C 的 deps / inbox / outbox / library / sync | CLI（**整个目录没进 git**） |
| tools/netfix | rssh/rsh、tunnel_supervisor、puller、dispatch、lan_proxy | 常驻 + CLI |
| tools/series10_imggen、series10_video | 服务器上的出图 / 视频（imggen、night.py、score_clip、vidgen） | 服务器常驻 |
| tools/gen_contract、tools/vqa | 契约打分（remote_score、local_score、clip_srv）、看图服务 | 服务器服务 |
| tools/pipeline | 写作链 run_chain、image_jobs、preflight_deps、register_takes | CLI |
| tools/qa | iter_gate、system_version、push_check、decision_check、ownership.yaml | CLI |
| tools/director、ep02_director | 后期、成片评分；审片 review.py | CLI |
| tools/iterate_loop | 老的出片 loop，现在只留给 P0–P3 回放 | CLI |
| tools/ab、bakeoff、video_rca、research、lab_ep02、ep02_iter、prompt_v2、imgfix、localgpu | 实验和对照；**其中一部分是生产依赖**（见 §8） | 一次性 |
| ops/ | autostart、offline（服务器常驻补丁和并回）、sync、cleanup、owner | 脚本 |
| config/ | 配置；policies/ 是阈值的单一来源（**没进 git**） | — |
| knowledge/ | 规则 yaml → compile.py 生成下游文件 | — |
| apps/web | 前端 React，外加 e2e sidecar | vite |

入口数量：带 `__main__` 的 tools 270 个、services 9 个、apps 9 个。

**做同一件事的多个入口**
- 生产驱动 8 个：producer.py serve（实际主线）、flow.py（状态视图）、run.py、episode_pipeline.py、full_redo.py、iterate_loop/loop.py、ns_orch/engine.py（API "开始生产"）、series10_video/night.py
- 出图：只有 frame_job + unified_frame 是合规路径；另有约 15 个脚本直接连 ComfyUI（§8）
- 合成：assemble_episode.py、assemble_preview_subset.py、prompt_v2/assemble_plan_c.py、director/post_pass.py
- 打分：ns_qc、score_clip、review.py、film_score、remote_score / local_score / clip_srv、vqa/gate_scan
- 重启 producer：laptop_autostart、restart_producer.ps1、resident_sync restart / recover / switch、system_version deploy、restart_queue
- 修隧道：tunnel_supervisor、infra_watchdog（TUNNELS 还指向已退役的 tunnel.sh，infra_watchdog.py:35-38）、gpu3_tunnels.py
- 推送到服务器：resident_sync push（按工作树、按 mtime）、tools/factory/sync.py push（按 sha 闭包）、system_version deploy（先 rs.push 再核 tag sha）、series10_video/deploy.py、series10_imggen/server_deploy.py、tools/vqa/deploy_offline.sh

---

## 4. 配置与状态在哪里

| 类别 | 在 git | 只在 data/（不进 git） | 只在服务器 |
|---|---|---|---|
| 代码 | tools/services/packages/ops 的大部分 | — | 服务器上的补丁：offline_20261101/fwd.py、bin/ssh（OFFLINE_ALIASES）、resident_prep 字符串替换后的副本 |
| **运行中的代码却不在 git** | — | tools/autopilot/{policy,flow,state_snapshot,import_events,restart_queue}.py、tools/factory/、tools/netfix/puller.py、tools/director/finish.py、tools/vqa/vqa_router.py、ns_agent/{camera_norm,sheet_intake}.py、config/policies/、config/pipeline/run.json（git status `??`） | 服务器上有 policy.py、tools/factory/*（实测 gpu33），说明是从工作树推上去的，不是从 sv tag 来的 |
| 阈值配置 | config/vqa.json、render_endpoints.json、gen_contract.json 等 | — | 服务器副本（S6 要求 0 差异） |
| 决策状态 | — | data/looks/*、R/assets/sheets_chosen.json、shot_looks.json、recipe_choice.json、master_rejects.json、ready_episodes.json、*_hold.json、face_overrides.json | 服务器副本 |
| 运行状态 | — | data/producer/{control,attempts,registry,log}.json(l)、data/netfix/*、assets_ready.json | 服务器各一份 control.json（实测两台 sha 和笔记本各不相同，设计上如此） |
| 服务器专有 | — | — | /root/work/fredw/vqa/server.py、vqa venv、ComfyUI、模型、D:\ns_vqa（笔记本上、仓库外） |

state_snapshot 的覆盖范围（config/policies/state_files.yaml）漏了这几份会改变出图结果的决策文件：data/looks/item_map_overrides.json、data/looks/hub_episode_looks.json、data/assetmaster/look_extras.json、data/autopilot/*_hold.json、config/scene_aliases.json（最后这个在 config 里，跟着代码走）。

实测 03:0x，12 个关键文件在笔记本 / gpu33 / gpu36 上的 sha：face_overrides、item_map_overrides、hub_episode_looks、look_extras、lookA_hold、scene_aliases、vqa.json、sheet_item_checks、sheets_chosen、recipe_choice 三边一致（FACTORY 刚手工补齐）；**config/pipeline/run.json 两台服务器都没有**（未入 git → cut 不含 → deploy 不发）；producer 读不到就静默回退成 series10_v1（producer.py:60-66），现在只是碰巧对。

---

## 5. 所有权（tools/qa/ownership.yaml 与实际是否一致）

- 11-01 以来改过的文件（git log + 工作树）中，有 **490 个匹配不到任何 owner**。tracked 文件里无主的有 1297 / 2361 个。无主的代码目录：
  - tools/imgfix、tools/monitor、tools/localgpu、tools/knowledge、tools/prompt_v2、tools/ab、tools/char_assets
  - services/render_router（unified_frame、pipeline 之外的部分）、services/post（tts、director 之外的部分）、services/orchestrator、packages/schema、packages/qc
  - ops/autostart（tunnel*.sh 之外的部分）
- **派单用的 loop 名在表里没有**：HOLLYWOOD、IMGFIX、SENTINEL、UI-DESIGN、LOCALGPU 没有条目。WORKFLOW 走别名映射到 AUTOPILOT。FACTORY 只有 tools/factory/** 等，**服务器运行时实际在 tools/autopilot/producer.py（归 DEBUG_RSI）、resident_sync.py 和 ops/offline/**（归 AUTOPILOT）**，和 FACTORY_ARCH 原则 5"FACTORY 负责服务器运行时"对不上。
- 一个文件两个 owner：docs/AUTOPILOT.md 同时登记给 AUTOPILOT 和 DISTILL（违反"一个文件只有一个 owner"）。
- DISTILL 写了 tools/autopilot/flow.py、policy.py，但按表这两个文件归 AUTOPILOT。
- rule_owners 里还引用已经不在岗的 INFRA、SERIES、CHAINSPEC、PROMPT。

---

## 6. 并发写者

| 文件 | 写者 | 原子写 | 锁 | 风险 |
|---|---|---|---|---|
| data/renders/**/takes.json | producer、:8800 API、merge_pull（puller 进程内调一次；resident_sync.py:399 又起子进程调一次）、register_takes / night、quarantine 脚本 | pipeline._write_json 是原子的 | **只有进程内 RLock**（services/render_router/ns_render/pipeline.py:240-243，注释原话"只管本进程"） | 高：整份读改写，会丢版本或丢 active |
| data/producer/attempts.json | producer（7 处）、full_redo.py:242、merge_pull.py:304（非原子） | 部分 | 无 | 高：reset 可能被覆盖 |
| data/producer/control.json | producer.py:2101/2125、infra_watchdog（pause_tick）、ns_api/producer.py:100/110、netfix/dispatch.py:262、episode_pipeline.py:180 | 是 | 无 | 中高：only / paused 互相覆盖 |
| R/assets/first_frame_jobs.json | image_jobs.py:264 | **否** | 无 | 中：producer 读到半个文件 → 当成 {} |
| R/video/jobs.json | build_jobs.py:391 | 否 | 无 | 中 |
| data/autopilot/assets_ready.json | resident_sync.py:906、factory/sync.py:180、factory/deps.py:189 | 是，但**共用 tmp 名 assets_ready.tmp** | 无 | 中 |
| data/producer/master_rejects.json | producer ×4、merge_pull.py:125（非原子） | 部分 | 无 | 中 |
| merge_pull 本身 | puller 有锁（data/netfix/puller.lock），resident_sync 起的 merge_pull 不拿这把锁 | — | 半 | 中 |
| data/autopilot/*_hold.json | imgfix/lookA_adopt.py:89/95 | 否 | 无 | 低 |
| 固定 tmp 名 | ns_api/producer.py:35（".api.tmp"）、night.py:59（".tmp"） | — | — | 低 |

---

## 7. 结构性问题（全量清单在 §9 Top 15；这里是分类索引）

- 单点故障：跳板、WSL 主连接（rssh 不自己重连，rsh.py:4）、笔记本人工进程 resident_sync 是服务器常驻唯一的保活者、gpu36 无守护
- 双份事实来源：takes / attempts / control 两边各写；车道表 5 份；vqa 实例数在 config 和实际之间对不上；代码"在 git 里的版本"和"在服务器上跑的版本"
- 隐式依赖（失败静默放行）：asset_refs 的覆盖类文件、*_hold.json、expected_refs、run.json
- 写死：series10_v1 出现在 97 个文件、共 476 处；/root/work/fredw 出现在 67 个文件；offline_20261101 出现在 15 个文件
- 多入口：ssh 7 种方式（41 个文件直接起 ssh，登记清单 config/netfix/ssh_callers.txt 只有 30 个）；推送 6 条路径；重启 5 条路径
- 测试和 cut：98 / 189 个测试文件读真实 data/；最近一次 cut sv-20261102-04 失败（xdist 收集不一致，data/system_versions/last_cut.json）
- 人工拉起：见 §1.2 标"人工"的行
- 缺超时和回压：70 处 subprocess.run 没有 timeout（核心链路 19 处）；ns_api 的 queue.Queue() 无上限（app.py:193、jobs.py:283）

---

## 8. 删繁就简（只列，不动）

### 8.1 可以隔离的死代码和废弃入口
- 0 引用或一次性：
  - 有明确证据的：tools/gen_asset_sheets.py（没有 main，0 引用）、redo_asset.py、latex_scraper.py、prepare_lora_dataset.py、narrator_verify.py、tools/autopilot/push_assets_json.py（docstring 自称"一次性"）
  - 只在文档里出现过的：fetch_civitai.py、lb_llm_captions.py、build_lin_wan_dataset.py、gen_makeup.py、v3_check.py、restore_archive.py、assemble_preview_subset.py、rr_ep02_newrecipe_qc.py、ab_history.py、ab_refine.py、ab_static_fix*.py、ab_motion_fetch.py
- 已被 K-REN-134 取代：gen_assets.py、gen_assets_v2.py（它直接读 gen_assets_items.py 的源码文本，:201）、gen_assets_items.py、render_batch.migrate_legacy
- 已退役还被引用：ops/autostart/tunnel.sh、tunnel_gpu36.sh（infra_watchdog.py:35-38 仍指向它们）；gpu3_tunnels.py（和 supervisor 重复）
- 死配置：tunnels.json 里的 18098、18290；resident_sync.py:453 的 gpu36:2 → 8190；factory_health.py:29 探测的笔记本 8870（laptop:0 已 disabled）
- 空目录 services/qc；仓库根目录的 20261102T000000_00000{0-3}_selftest_take/（tools/netfix/puller_selftest.py:28 把产物写到了仓库根目录，是 bug）、p.out、ominichar.jpg
- 计划任务 NS-Studio-Autostart-Trial（指向不存在的路径）
- 一次性脚本：ops/cleanup/delete_quarantine_20261101{,b}.ps1、ops/owner/ep02_*.ps1、config/*.before_*_20261102 备份
- **注意，名字像实验、其实是生产依赖，隔离前要先迁走**：series10_video/score_clip.py:37-40 依赖 ep02_iter/cut_check、lab_ep02/lab_score、ep02_director/review、motion_judder；series10_video/deploy.py:27-29 会把它们推到服务器；ab_voice_fix.py 被 voice_convert_shot.py:19 import

### 8.2 可以合并的重复实现
1. 出图：只留 frame_job + unified_frame + image_jobs / imggen。约 15 个直连 ComfyUI 的脚本（gen_assets*、gpu_grab、char_assets/asset_gen、ab/char_sheet_qi21、bakeoff/run.py:668、video_rca/*、lab_ep02/lab_runner、ep02_iter/v2_runner、prompt_v2/plan_c_*）只在实验目录保留，不进生产路径
2. ssh：13 个自己写的 `def ssh()`（resident_sync.py:87、remote_score.py:76、night.py:70、imggen.py:341、voice10.py:143、ns_api/jobs.py:704、gpu_monitor.py:97 等）统一改成 rssh.run；下线 bash_ssh_wrapper 和 ssh_shim 的猴补
3. 推送：resident_sync push、factory/sync.py push、system_version deploy、series10_video/deploy.py、series10_imggen/server_deploy.py、vqa/deploy_offline.sh 合并为 factory/sync.py（数据按 sha）+ system_version deploy（代码按 tag）两条
4. 修隧道：只留 tunnel_supervisor；infra_watchdog 去掉 taskkill / start_loop 那一段；gpu3_tunnels.py 隔离
5. 车道表：5 份收成 config/factory/hosts.json 一份（D1）
6. 运动 / 卡顿检测：motion_judder.py、ns_render/motion_qc.py:120、ep02_director/review.py:297（同名不同实现）、video_rca/judder.py 统一到 ns_render.motion_qc
7. 身份度量：ArcFace（identity_metric）、SFace（ns_qc/face.py）、remote_score Q1 三套口径，定一个
8. 合成：assemble_episode + assemble_preview_subset 合并；prompt_v2/assemble_plan_c.py 和 director/post_pass.py:300 各自拼 ffmpeg 的部分改调 ns_post
9. 控制文件：data/producer/control.json、series10_imggen/images/control.json、night_control.json、series_control.json 四套；control.json 的 11 个读者改走一个读取函数
10. 生产驱动：ns_orch/engine.py 和 iterate_loop 的出片段退役，只保留 producer + night 作为执行器，flow 作为视图

---

## 9. 结构性问题 Top 15（按影响排序）

| # | 问题 | 出处 | 类别 | 建议负责 |
|---|---|---|---|---|
| 1 | **运行中的代码不在版本里**：producer 依赖的 policy.py，以及 flow / state_snapshot / tools/factory / puller / vqa_router / config/policies / run.json 都是 `??`。服务器上却有这些文件（实测 gpu33），说明是工作树推送带上去的。后果：sv tag ≠ 实际运行代码，`rollback sv-03` 会把 producer 回滚成 import 失败；按 D9"只发 tag"部署反而会把它们删掉 | git status；producer.py:2049-2059；gpu33 ls | 双份事实来源 / cut | FACTORY（D9）+ CODERSI |
| 2 | **决策覆盖文件读不到就静默放行（失败开放）**，同一类问题至少 9 处：asset_refs 的 face_overrides（:558-562，01:32 P0 的根因）、item_map_overrides（:205）、item_map_quarantine（:195）、hub_extra_looks / hub_episode_looks（:232）、look_extras（:310）；producer 的 *_hold.json（producer.py:97-107 注释"文件坏/不在 = 不挡"）；inbox expected_refs（tools/factory/inbox.py 文件头"文件不存在 = 不拦"）；run.json（producer.py:60-66 回退 series10_v1，**服务器上现在就缺这个文件**）。preflight 不检查这些文件是否存在 | 见左 | 隐式依赖 | FACTORY（deps 闭包把"决策文件存在 + sha"列为硬依赖）+ REFLOCK（asset_refs 改成缺文件即报错） |
| 3 | **服务器常驻没有本机守护**：producer / night / fwd 用 setsid nohup 起，没有 systemd 也没有 cron；唯一保活者是笔记本上人工起的 resident_sync loop，还要经跳板。gpu36 的 ComfyUI、vqa_router 也是 nohup。跳板一断，服务器进程挂了就没人拉 | ops/offline/resident_restart.sh:25；resident_sync.py:680-720；两台 crontab 为空 | 单点 / 人工拉起 | FACTORY |
| 4 | **跳板 + WSL 主连接是单点**：rssh 发现主连接不在就直接 rc 255，不自己重连；supervisor 只靠 5 分钟一次的计划任务拉起；HK 线最终也经过 sz194 | tools/netfix/rsh.py:4；rssh.py:7-13；ssh_config:23-35 | 单点 | NETFIX |
| 5 | **takes.json / attempts.json / control.json 多进程读改写、没有跨进程锁**；merge_pull 还有两个调用方，锁不共用 | pipeline.py:240-243；merge_pull.py:125/206/304；resident_sync.py:399；§6 表 | 并发写者 | DEBUG-RSI（producer / attempts / control）+ NETFIX（merge_pull 单入口）；takes 写入口归 REFLOCK |
| 6 | **cut 脆弱，阻断配置下发**：sv-04 因 xdist 各 worker 收集不一致失败；98 / 189 个测试读真实 data/，数据一变测试就变。cut 失败 → 新 config（run.json 等）上不了服务器；而 01:59 一次失败的 cut 照样跑了 deploy，把 vqa.json 还原了 | data/system_versions/last_cut.json；morning_20261102.md:80 | 测试 / cut | CODERSI（测试隔离真实数据）+ FACTORY（cut 失败禁止 deploy） |
| 7 | **推送有 6 条路径、判断依据各不相同**（mtime / sha / tag / 整目录），推送清单靠人维护；resident_sync 的 LIVE_PREFIX 只认 data/assetmaster/sheets_v2/adopted/，look_extras.json 等只有在"服务器已有"时才更新 | resident_sync.py:197-199、201-216、227-229；factory/sync.py；system_version.py:699-710 | 多入口 | FACTORY（数据）+ CODERSI（代码按 tag） |
| 8 | **配置声称的状态和实际进程对不上，没有探针**：vqa.json 写"instances 4、已切 vllm_proxy"，gpu36 实测是 vqa_router + 3 个 server.py、没有 vLLM；clip_resident 8872 没在跑；gpu36:8190 已停但三份配置还在用 | config/vqa.json `instances_note`；gpu36 ps；resident_sync.py:453 | 双份事实来源 | VQAGATE（实例）+ SENTINEL（声明 vs 实际探针） |
| 9 | **生产仍走隧道派单**：producer 的 IMAGE_LANES 写死 127.0.0.1:1818x；服务器靠 fwd.py 把端口转回来才能用同一份代码；D1 的 hosts.json 不存在；outbox 两台都是 0 条（D7 没有真正接通） | producer.py:78；fwd.py:4；config/factory 不存在 | 目标差距 | FACTORY |
| 10 | **笔记本开机后几乎全靠人工拉起**：Laptop-Autostart 和 NSFS-* 计划任务都没注册；ns_api、vite、infra_watchdog、episode_pipeline、monitor、resident_sync、D:\ns_vqa 都没人监控 | register_owner.ps1:5-12；schtasks；autostart.log | 人工拉起 | WORKFLOW（autostart）+ SENTINEL（存活探针） |
| 11 | **写死 run_id 和路径**：series10_v1 出现在 97 个文件；只有 producer / episode_pipeline / state_snapshot 读 run.json。resident_sync（14 处）、full_redo、night、vidgen、build_jobs、ns_api 的 render_tasks / edits / voice_preview / bgm_api 写死。换剧时链路会分叉 | resident_sync.py:197/228/251…；producer.py:125-127；full_redo.py:80/105/284 | 写死 | WORKFLOW（作业 / 推送）+ DISTILL（run.json 唯一来源 + lint） |
| 12 | **重启和修隧道多入口**：重启 producer 有 5 条路径；infra_watchdog 仍按已退役的 tunnel.sh 去 taskkill ssh，和 supervisor 的"一家负责"（K-OPS-N01）冲突；gpu3_tunnels.py 也能独立守端口；还有绕过 supervisor 的散落 ssh -L | infra_watchdog.py:35-38、131-132、235-245；gpu3_tunnels.py:42 | 多入口 | NETFIX（隧道）+ DEBUG-RSI（restart 收口到 restart_queue） |
| 13 | **ssh 调用分散**：41 个文件直接起 ssh（登记清单 30 个），13 个自写 `def ssh()`，靠 sitecustomize 猴补兜底；今晚的连接风暴（26 条 ssh）就出在这里 | config/netfix/ssh_callers.txt；§8.2-2 | 多入口 | NETFIX |
| 14 | **缺超时和回压**：70 处 subprocess.run 没有 timeout（合成 ffmpeg assemble.py:396、pipeline.py:537、run.py:510 shell=True 等）；ns_api 的 queue.Queue() 无上限；producer 的 PREFLIGHT_RETRY_S=30 分钟按时间轮询，不响应依赖到齐 | §⑤ 统计；producer.py:66；app.py:193、jobs.py:283 | 回压 / 超时 | DEBUG-RSI（producer 侧）+ DIRECTOR（合成 ffmpeg）+ UIRSI（API 队列） |
| 15 | **所有权表和实际脱节**：490 个最近改动的文件无主；HOLLYWOOD / IMGFIX / SENTINEL 没有条目；FACTORY 负责的服务器运行时文件归在 DEBUG_RSI / AUTOPILOT 名下；docs/AUTOPILOT.md 两个 owner。iter_gate 依赖这张表，所以越界改动查不出来 | tools/qa/ownership.yaml；§5 统计 | 所有权 | ITERAUDIT（总调度定） |

另外几条在 Top 15 之外但值得记下：
- first_frame_jobs.json、jobs.json 非原子写（image_jobs.py:264、build_jobs.py:391）
- scene_ref 仍按 mtime 取图（asset_refs.py:585，P14 未修）
- puller_selftest 把产物写到仓库根目录
- 4 套 control 文件
- 身份度量三套口径

---

## 10. 目标架构差距表

依据：FACTORY_ARCH.md（L-099）、FRAMEWORK_REFRAME.md 方案 C（D1–D10）、AUTOPILOT.md §0、SLO.md（S1–S12）。

| # | 目标（出处） | 现状 | 差距 | 负责 | 优先级 |
|---|---|---|---|---|---|
| G1 | D1 工厂身份 + 本机道表（hosts.json、NS_FACTORY_HOST） | config/factory 不存在；IMAGE_LANES 写死隧道端口；fwd.py、bin/ssh、resident_prep 补丁都还在 | 全部 | FACTORY | P0 |
| G2 | D2 本地库按 sha；scene_ref 不按 mtime | library.py 已写，生产路径不用；asset_refs.py:585 仍按 mtime | 接线 | FACTORY + IMGFIX（names.json 逻辑名） | P1 |
| G3 | D3 依赖闭包 = preflight 自己算；交还要 dryrun 0 挡 | deps.py、preflight_deps 有了，但**决策覆盖文件不在闭包里**（问题 #2） | 闭包补"决策文件 + sha" | FACTORY | P0 |
| G4 | D4 inbox 声明式目标状态 + min_code_sv | 只做了 expected_refs，而且失败开放；control / hold / rejects 仍由 CONTROL_FILES 分别推；min_code_sv 没有 | 大部分 | FACTORY + WORKFLOW（push 清单退役） | P0 |
| G5 | D5 断网 ≠ 暂停；运维暂停带 expires_at | policy.pause_decision 已有；服务器 paused 仍跟随笔记本 laptop_ctrl（dispatch.py） | 解耦服务器暂停 | DEBUG-RSI + NETFIX | P1 |
| G6 | D6 本机打分常驻服务 + VLM 专用卡批处理 | scorer.py 不存在；clip_resident 没在跑；gpu36 实测没有 vLLM（router + 3 个 server.py） | 全部 | VQAGATE（VLM）+ FACTORY（scorer） | P0（S3 打分 p50 ≤120 s 直接靠它） |
| G7 | D7 outbox 事件 + puller | outbox_emit 已接（producer.py:436），两台 outbox 0 条；结果仍靠 resident_sync 每 20 分钟 tar 拉回 | 验证接通、退役 tar pull | NETFIX（puller）+ FACTORY（写端） | P1 |
| G8 | D8 依赖到齐事件驱动重查 | PREFLIGHT_RETRY_S=30 分钟 | 全部 | DEBUG-RSI | P2 |
| G9 | D9 服务器代码 = 干净 git 工作树，部署只发 tag，按道排空滚动重启 | 服务器是 offline_20261101/repo 拷贝；**运行中的代码有一批不在 git**（问题 #1）；cut 会失败 | 先把运行代码全部入版，再改部署 | FACTORY + CODERSI | P0 |
| G10 | D10 一条命令的控制台 sync push / pull / status | factory/sync.py 有了，但和 resident_sync、system_version deploy 等 6 条推送并存 | 收口 | FACTORY + WORKFLOW | P1 |
| G11 | FACTORY_ARCH 原则 5：单一负责人 | ownership 没反映（问题 #15） | 改表 | ITERAUDIT（总调度定） | P1 |
| G12 | FACTORY_ARCH §2-4：隔离笔记本隧道派单路径和 K-OPS-N06 | override.json active=true；笔记本 producer 仍在跑 | 待 G1 / G6 完成 | FACTORY + NETFIX | P1 |
| G13 | 服务器常驻自保活（隐含在原则 1"跳板断一小时照常出图"里） | 无 systemd / cron（问题 #3） | 全部 | FACTORY | P0 |
| G14 | AUTOPILOT §0 一个编排器 | flow 是视图；执行器分散在 8 个入口；ns_orch / iterate_loop 未退役 | 退役旧驱动 | DISTILL | P2 |
| G15 | AUTOPILOT §0 冷启动：run.json 单一来源 | 97 个文件写死 series10_v1；服务器缺 run.json | lint + 改读者 | WORKFLOW + DISTILL | P1 |
| G16 | AUTOPILOT §0 state 快照覆盖全部决策文件 | 漏 item_map_overrides / hub_episode_looks / look_extras / *_hold | 补 state_files.yaml | DISTILL | P1 |
| G17 | SLO S1/S2 道利用率、GPU 全空探针 | 无 SENTINEL 代码（tools/sentinel、data/sentinel 都不存在）；monitor :8810 人工起 | 全部 | SENTINEL（DEBUG-RSI 接单） | P0 |
| G18 | S4 连接恢复 ≤30 s | supervisor 有；主连接断时 rssh 不重连 | 加主连接自愈探针 | NETFIX + SENTINEL | P1 |
| G19 | S5 cut 一次通过、版本差 ≤1 | sv-04 失败；有 98 个测试依赖真实数据 | 测试隔离 + 收集确定性 | CODERSI | P0 |
| G20 | S6 服务器配置和笔记本 0 差异 | 没有自动 sync verify 探针；本次手工比对：run.json 两台都缺 | 探针 + 清单 = state_files.yaml ∪ deps 闭包 | FACTORY + SENTINEL | P0 |
| G21 | S7 无主暂停 ≤180 s | run.py guard 有，`--apply` 默认关 | 常驻 | DEBUG-RSI | P1 |
| G22 | S8 内容抽检 | VLM 抽检没有排程 | 定时 | VQAGATE | P1 |
| G23 | S9 界面探针 | uirsi 截图有；没有常驻 | 定时 | UIRSI | P2 |
| G24 | S11 编排器同段 >2 h 违约 | flow status 有；没有违约开单 | 接 issues.jsonl | DISTILL + SENTINEL | P2 |
| G25 | S12 剧本尺子 | rubric_code 有；未入 git | 入版 | HOLLYWOOD | P2 |
| G26 | "声明 vs 实际"探针（本次审计新增建议） | vqa.json 和实际进程不符、车道表 5 份互相不符 | 新探针：配置声明的端口 / 实例 / 版本逐项实测 | SENTINEL | P1 |

---

## 11. 建议的整理顺序（给总调度参考，不是决定）
1. 当天：把运行中的未入版代码全部纳入版本（#1），修好 cut 的确定性（#6），cut 失败禁止 deploy。
2. 当天：把决策覆盖类文件列为 preflight 硬依赖并比对 sha（#2、G3、G20）；把 run.json 推上服务器。
3. 1–2 天：服务器常驻改 systemd 自保活（#3、G13）；VLM / scorer 本机化（G6）；SENTINEL 起 S1/S2/S6 探针（G17、G20、G26）。
4. 随后：推送 / 重启 / ssh / 车道表收口（#7、#12、#13、G1、G10）；takes / attempts / control 改单写者（#5）；ownership 重排（#15）。
