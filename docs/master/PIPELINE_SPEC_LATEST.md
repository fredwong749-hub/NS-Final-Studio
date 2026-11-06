# NS-Final Studio 流水线规格（最新版，供外部模型审计）

- 写于 2026-11-06 17:0x JST｜作者 SPEC-DOC（只读，未改代码 / 服务器）｜基线 = 工作树 + 最新发版 **sv-20261106-07**（commit a358fde，gpu33 14:39 / gpu36 14:43 部署，`docs/system_versions/INDEX.md:5`、两台 `data/system_version.txt` 实读一致）
- 口径：每个数值都写出处（`文件:行` 或配置键）。标 **[未核实]** 的是没能从代码 / 实测确认的；标 **[本地未入版]** 的是工作树里改了但 sv-20261106-07 没包含的；标 **[L-206 实现中]** 的是三名工人正在做、未上线的。
- 决策编号 L-xxx = `docs/master/MASTER_PICTURE.md` §1 项目方决策账本（最新 L-206，`MASTER_PICTURE.md:376`）；K-xxx = `knowledge/rules/*.yaml` 规则号；D-V2-xxx = `config/owner_decisions.yaml` 机检断言。
- 时间一律 JST（`tools/qa/system_version.py:55` ENV TZ=JST-9；`tools/netfix/rssh.py:111` TZ_NAME Asia/Tokyo；`tools/autopilot/producer.py:770` PROJECT_TZ_H=9）。笔记本系统时钟是美东，服务器 America/New_York，脚本内部自行换算。

---

## 0. 一页总览

| 项 | 内容 | 出处 |
|---|---|---|
| 目标 | 小云雀级（“小云雀五分钟就做完了”）、100% 全自动（“我需要你全自动，不要检测那么多了”）、画面好莱坞级（Leica / ARRI / Kodak 质感，L1 画风基线） | L-196 / L-197（`MASTER_PICTURE.md:366-367`）、L-188（`:358`）、L-145 |
| KPI | **一集 ≤ 50 分钟**（单段视频 ≈ 5 分钟反推）；每集出逐步耗时表，超预算归因到 逻辑 / 代码 / GPU 调度 / 检测 四类并当轮修进代码（带单测） | L-205（`MASTER_PICTURE.md:375`） |
| 当前版本 | sv-20261106-07 = a358fde（线上）；规则 697 条（kb-20261106-3339c2fb）；定向 pytest 881 passed / 4364 collected；**cutAD（→ sv-20261106-08）在切，含 L-206 全部代码** | `docs/system_versions/sv-20261106-07.md:3,22,69-71`；`LIST_cutAD.txt` |
| 发版流程 | `system_version.py cut` 七门全绿 → commit + tag `sv-YYYYMMDD-NN` → 推 `release/<sv>` 分支 + `gh pr create` 合 master（不再直推 master，项目方 11-06 08:3x）→ `deploy --verify` 两台 → 本机写 `data/system_version.txt` | `tools/qa/system_version.py:1412-1452`（push_remote / open_pr）、`:1828-1876`（deploy）、`docs/master/CHANNEL.md:375` |
| 生产铁律（L-204 三条） | (1) 出图前全量离线检查一次改完、全绿才导入；(2) 每镜最多 3 次，过了就用，否则自动采用最好一版继续；硬闸只拦 身份 / 人数 / 文字 / 成人 / 视线排排站 / 首尾太像；集内不改架构、不中途重启；(3) 到点必交，只报首尾帧小样与成片两次 | L-204（`MASTER_PICTURE.md:374`） |
| 项目方决策边界 | 成人镜头只由项目方在界面触发（系统 / agent 不自动派，`producer.py:3489-3494` adult_wait_owner）；删除一律隔离（`data/_quarantine*`）；永远不代：成人渲染、删除、花钱、推翻旧决定（`config/pipeline/owner_delegate.json` never[]） | L-128 / L-198 / L-205、`config/factory/hosts.json` `_owner_controlled_doc` |
| 最新决定（17:1x） | **L-207（实现中，工人 L207-PHASES）**：一集严格三段——① 首尾帧阶段（出图 4 + 审图 1 + 视频 1，L-206）→ ② 首尾帧全部定下后**全部 6 张卡做视频**（含审图位 gpu33:3，看图缩到 1 个实例与视频模型同卡供视频打分，约 7.5 GB + H3 约 13 GB）→ ③ 合成 → 下一集首尾帧；SOP / PIPELINE_CHECKLIST / lane_roles.json 按此改 | `MASTER_PICTURE.md` 末行 L-207；`config/pipeline/lane_roles.json` `_L207`、phases.videos.video（6 道）、review.vqa_instances_by_phase {frames 3, videos 1} |
| 在发版中 | L-206 代码已完成并入 **cutAD**（`docs/system_versions/LIST_cutAD.txt`，38 项；过七门即 sv-20261106-08）：lane_roles.json、`tools/autopilot/lane_roles_producer.py`、`tools/series10_video/lane_roles.py`、`tools/vqa/review_instances.sh`、`tools/previz/auto_blocking.py`、turbo_previz 按集档位（render_quality first_frame_tier.runs.series10_v2.from_episode）、night.py 等闸门满 45 min 才落定、asset_worker 身份脸核对口径 | `LIST_cutAD.txt:1,4,26,29,33,34,39` |
| 当前主剧 | `series10_v2`（status producing，episode 1，assets_manifest assets_v2/manifest.json）；V1 archived 只读 | `config/pipeline/runs.json` runs.series10_v2 |
| 11-06 实测 | ep01 16 镜 14:53 重出开跑（KPI 计时），17:00 仍未交付；详见 §8 | `docs/master/CHANNEL.md:419`、本文 §8 |

---

## 1. 硬件与拓扑

### 1.1 机器与 GPU

| 机器 | GPU | 道（lane） | ComfyUI 端口 | 笔记本隧道口 | 角色 | 出处 |
|---|---|---|---|---|---|---|
| gpu33（自有） | 4×3090；**GPU2 坏卡永不用** | gpu33:0 / gpu33:1 / gpu33:3 | 8188 / 8189 / 8191 | 18188 / 18189 / 18191 | image+video；gpu33:3 同时跑看图 :8870（comfy `--reserve-vram 9`，H3 int8 ~20 GB 放不下 → 视频分片不派该道） | `config/factory/hosts.json` hosts.gpu33（broken_gpus [2]、lanes、max_frames 260、recipe_max_frames.h3_funcontrolnet 107）；`config/pipeline/video_shard.json` exclude_lanes._why |
| gpu36（自有） | 3×3090 | gpu36:0 / gpu36:1 / gpu36:2 | 8188 / 8189 / 8190 | 18288 / 18289 / 18290 | image+video（L-194：三卡全归 NS，gpu36:2 ComfyUI `comfy.sh start 2`） | `hosts.json` hosts.gpu36；L-194 |
| 笔记本（Windows 11） | RTX 4080 | laptop:0（enabled=false，roles [vlm]） | 18388 | — | 总调度 / 常驻 / 中继；本机看图 8870（现优先走 8871 隧道到 gpu33） | `hosts.json` hosts.laptop；`config/vqa.json` route.laptop_prefer_tunnel=true |

- 坏卡红线在代码里多处写死：`producer.py:131` BAD_LANES、`vidgen.py:403` BROKEN_LANES、`idle_watch.py:45` NEVER_LANES、`health_tick.py:36`、`lane_relay.py:30`、`lane_roles_producer.py`/`lane_roles.py` BAD_LANES/BROKEN。
- 服务器仓库路径：`/root/work/fredw/offline_20261101/repo`，venv `/root/work/fredw/offline_20261101/venv/bin/python`；gpu33 ComfyUI 根 `/root/claude-kimi-ns-studio-v1/ComfyUI`，gpu36 `/root/work/fredw/comfy`（`hosts.json`）。

### 1.2 网络：互不信任 + 笔记本中继

- 两台服务器之间**没有 ssh 互信**（K-OPS-Y02）；任何跨机数据（首尾帧 → 视频机、helper 片子 → owner、借道出图）都经笔记本（`tools/series10_video/shard_relay.py:1-20`、`tools/autopilot/lane_relay.py:1-14`、`resident_sync.py:1675-1680` relay_frames）。
- 笔记本 → 服务器：`tools/netfix/tunnel_supervisor.py` 一个进程托管全部 ssh：底座 base-a（香港路由，转发 127.0.0.1:22360→10.0.0.36:22、22330→10.0.0.33:22）与 base-b（直连，22361 / 22331 热备）；6 条道隧道 + `gpu36-vqa`（笔记本 8871 → gpu33:8870）+ 每台 4 条 WSL ControlMaster 命令主连接（`gpu33-cmd..cmd4`、`gpu36-cmd..cmd4`，sock `/home/fredw/.ssh/nsnf/<host>-cmdN.sock`）。参数：tick_s 5、probe_every_s 15、probe_timeout_s 20、hang_rounds 3、backoff_s [3,6,12,24,30]、max_connecting 2（跳板）/ max_connecting_inner 8、route_order [hk, direct]、route_fail_max 4、route_bad_s 600、migrate_after_s 120（`config/netfix/tunnels.json`）。
- 远程命令唯一入口 `tools/netfix/rssh.py`：`wsl.exe -d Ubuntu-24.04 --exec ssh -S <sock> -o ControlMaster=no -o ProxyCommand=false`（只复用、不新握手，`rssh.py:107`）；`run()` 默认 timeout 900 s（`:121`），sock 池 4 条随机分摊（`:28`，服务器 sshd MaxSessions 10）；`run_retry()` tries=4（`:183`），rc=255 / 超时退避重试（`PIPELINE_CHECKLIST.md:44`：10 s×n）；大文件 `bulk_put()` 走 Git sftp 经 `<host>-hk`（`:224`）。调用记 `data/netfix/rssh_calls.jsonl`，状态 `data/netfix/net_status.json`。
- 借道（L-193）：`tools/autopilot/lane_relay.py serve` 在笔记本起白名单 HTTP 代理（ALLOW 只有 /system_stats /queue /object_info /history /view /prompt /upload/image /view_metadata /interrupt /free，`lane_relay.py:32-34`；MAX_BODY 64 MB）+ `ssh -R` 挂到 gpu33 的 127.0.0.1:28288/28289/28290（上游 = 笔记本隧道 18288/18289/18290，max_inflight 2，`config/pipeline/lane_relay.json`）。gpu33 producer 把这三口当 gpu36:0/1/2 的道（`producer.py:2572-2579`）。阶段交接写 `data/pipeline/lane_relay_hold.json {"hold":[...]|"all"}`，producer 每轮现读（`producer.py:3380-3383`）。**隧道断了反向隧道 5 s 重连**（`lane_relay.py:181`）。
- 服务器内网：gpu33 producer 调 gpu36 看图 / 人数检测走 `10.0.0.36:8870` / `10.0.0.36:8893`（`config/vqa.json` model.lan_url，`tools/netfix/lan_proxy.py` 只认 10.0.0.33 来源；`config/gen_contract.json` image_thresholds.Q10_accept.count_host）。

### 1.3 每台常驻进程

**gpu33 / gpu36（服务器，`ops/offline/resident_restart.sh`，环境 TZ=Asia/Tokyo OFFLINE_SELF=<host> PYTHONUTF8=1）**

| 进程 | 起法 | 说明 | 出处 |
|---|---|---|---|
| fwd.py | `$OFF/fwd.py`（pid `run/fwd.pid`） | 127.0.0.1:181xx/182xx → 本机 ComfyUI（不经跳板） | `resident_restart.sh:30-31`、`dispatch.py:5` |
| producer | `tools/autopilot/producer.py serve --run <primary>`（pid `run/producer.pid`） | 首尾帧派单 / 打分 / 闸门 / 采用；每 TICK_S=10 s 一拍 | `resident_restart.sh:33`、`producer.py:108` |
| night + vidgen | `tools/series10_video/night.py --run <primary>`（pid `run/night.pid`）；`restart_vidgen` 随 night-only/all | 视频编排 + 合成；vidgen 是实际提交 ComfyUI 的执行器（Runner） | `resident_restart.sh:47`、`resident_sync.py:419-427` |
| ComfyUI ×3 | gpu33：systemd `ns-comfy@3-8191`（drop-in `--reserve-vram 9`，`CHANNEL.md:207`）；gpu36：`/root/work/fredw/comfy/comfy.sh start N` | 出图 + 视频 | `hosts.json` |
| 看图 VQA :8870 | gpu33:3 本机 Qwen3-VL-8B nf4（`tools/vqa/start_gpu33_vqa.sh`，B1 11-05；实例 :8876/:8878/:8879 由 `tools/vqa/vqa_router.py` 占 :8870 分发） | L-194 看图集中 gpu33:3；gpu36 :8870 固定 GPU1（`vqa.json` model.gpus [1]）现已让位 | `config/vqa.json` model.*、`tools/vqa/vqa_router.py:4-9,24-25` |
| 打分常驻 :8873 / :8874 | `ops/factory/score_resident.sh`（`tools/gen_contract/score_srv.py --kind idm 8873` venv_idm insightface+rapidocr；`--kind hand 8874` venv_hand mediapipe），CPU、只听 127.0.0.1 | full_score 冷起 40–60 s/张 → 常驻 1.3–3.2 s | `score_srv.py:2-9`、`config/pipeline/score_resident.json` enabled=true、`remote_score.py:282-290` |
| 人数 / 异常检测 :8893 | `ops/factory/anomaly_resident.sh`（`tools/vqa/anomaly_server.py`，gpu36 GPU1，`resident_sync.py:2141-2142`）；gpu33 producer 经 10.0.0.36:8893 | yolov8m-seg + face/hand yolo + DWPose + OneFormer，~2.5–3 GB | `anomaly_server.py:20`、`vqa.json` model.vram_budget |
| clip_srv | `ops/factory/clip_resident.sh`（CPU） | Q2 造型 CLIP | `vqa.json` model.vram_budget._doc |

**笔记本（Windows）**

| 进程 | 起法 / 周期 | 说明 | 出处 |
|---|---|---|---|
| tunnel_supervisor serve | 计划任务 NS-Studio-TunnelSupervisor 每 5 min ensure；tick 5 s | 全部隧道 + 命令主连接 | `ops/autostart/laptop_autostart.ps1:14-18`、`tunnels.json` tick_s |
| puller serve | TICK_S 10 s；BATCH_MB 8；一拍 ≤6 批；MIRROR_EVERY_S 90（镜像 `data/producer/registry.json`）；SCAN_EVERY_S 300（takes_scan）；FETCH_MB_PER_TICK 12 | 服务器 outbox → `data/_offline_pull/<host>/` → `ops/offline/merge_pull.merge_file` 并回；不 ack 不删 | `tools/netfix/puller.py:1-25,43-45,192-193,229,334` |
| API :8800（uvicorn ns_api.app） | `tools/factory/api_watchdog.py` 托管 | 画布 / 待办 / owner_pick / 代选后台线程 | `laptop_autostart.ps1:30-39`、`config/pipeline/owner_delegate.json` |
| 前端 :5173（vite）、监控 :8810 | — | `#/queue` 待办页（`episode_run.py:42` OWNER_URL） | `laptop_autostart.ps1:43-47`、`health_tick.py` DEFAULT_CFG.ports |
| resident_sync loop | 主循环：并回 1200 s、健康 300 s；守护线程：autoflow core/line3/api 每 60 s（子进程超时 1200/900/960 s）、factory_sync 600 s、release_tick 60 s、episode_run（`episode_run.json` enabled=**false**）、lifecycle 60 s、run_sync 120 s、relay_frames 60 s（+15 s 看 puller 回执）、vqa_guard 300 s | 同步 / 中继 / 发版 / 生命周期 | `resident_sync.py:2297-2325`、常量 `:939-945,994-995,1022,1045,1108,1410-1411,1675-1679,2020-2028` |
| autoflow_resident | 每拍：写作推进 + asset_worker.tick + hollywood + dispatch；守护线程 health_tick（每 45 s，≤60）与 idle_watch（每 60 s）；看门狗每 30 min | 资产作业执行器宿主 | `tools/factory/autoflow_resident.py:10,137-143,292-326` |
| lane_relay serve | 常驻（反向隧道断 5 s 重连） | 借道代理 | `lane_relay.py:160-188` |
| shard_relay --loop | 每 120 s 一轮 | helper state / clips / scores → owner | `shard_relay.py:6,278` |
| infra_watchdog serve | 30 s 探 6 条道隧道 | 报警到 `data/qa/alerts.jsonl` | `laptop_autostart.ps1:20-26` |
| producer serve（笔记本） | laptop_autostart 起 | laptop:0 已 disabled，实际不派 | `laptop_autostart.ps1:49-62`、`hosts.json` laptop |

进程清单的权威登记在 `config/policies/sentinel.yaml` S16_laptop_procs（`:149-166`）。

---

## 2. 端到端流程

总顺序（`tools/master/sop_gate.py:48` STAGES）：**剧本 → 导入闸门 → 资产就绪 → 提示词 → 出图 → 出图检测 → 尾帧 → 视频 → 整集预览**；可按镜判的阶段 SHOT_STAGES = {提示词, 出图, 出图检测, 尾帧}（`:49`）；第 N+1 集从“出图”起要第 N 集复盘 done，`retro_parallel=true` 时最多落后一集（`sop_gate.py:626-644`、`config/pipeline/sop_gate.json` retro_parallel）。

一集的调度清单（目标用时，`docs/master/PIPELINE_CHECKLIST.md` §清单）：导入 ≤1 min（2 min 重跑）→ 同步 ≤30 s（90 s 直推）→ 提示词检查 ≤1 min（3 min 重跑）→ 首帧（单张 ≤2× 预计：base35 330 s / turbo 60 s；硬闸不过换种子；3 次后采用最高分）→ 视频（单段 ≤900 s；首帧定稿 120 s 未派 → night --once；2 次仍不行兜底）→ 合成 ≤10 min（20 min 重跑）→ 拉回 + 对比页 ≤5 min → 复盘 ≤1 min。执法代码 `tools/master/episode_checklist.py:24-33`（STEP_OF 超时、FIRST_EXPECT_S、FIRST_FACTOR 2.0、FIRST_MAX_REDO 3、VIDEO_MAX_S 900、VIDEO_DISPATCH_S 120、VIDEO_MAX_REDO 2、NIGHT_STALE_S 900、LOCK_TTL_S 600）；调度者 `tools/master/episode_run.py`（段 import→preflight→regen→first→video→finalize→pull→compare→timeline，`:36`；段超时 `:39-40` import 600 / preflight 300 / regen 900 / first 7200 / video 7200 / finalize 3600 / pull 1800 / compare 300 / timeline 600）。**注意**：episode_run 常驻目前关着（`config/pipeline/episode_run.json` enabled=false，`_psm_1105`：regen 段曾对整集下换代），11-06 ep01 是 PS-MASTER 手工 import-staged + 两台执行器重启后由 producer / night 自行推进。

### 2.1 写作（P1–P4）

| 项 | 内容 | 出处 |
|---|---|---|
| 链路 | P0 简报 → P1 故事线 + 造型表（三评委，均分 ≥34/40、≤3 轮，未过转项目方）→ 项目方闸门 → P2 单集大纲 → P3 剧本 → P4 分镜 → 事实核对 → 补丁环 → 导入 | `docs/master/PIPELINE_SOP_V2.md` §顺序 1–6；`metrics/ep01_summary.json` judges.threshold=34 |
| 写手 / 评审分工 | 写手 fable、评审 sonnet、评委 sonnet / haiku / opus 三位不同，写与评不同模型（must_differ_from）；派人请求 `data/master/inbox/requests/<run>__<id>.json`（nsfs.dispatch_request/1） | `PIPELINE_SOP_V2.md` §派人请求 |
| P4 分镜格式（每镜） | `**镜N｜img**`（首帧 = 起幅）→ `**场景**：sk_<id>｜细节` → `**人物**：名（在画｜左/中/右｜前/中/后）…`（≤3 人在画+局部）→ `**衔接**` → `**时长**：整数秒 4–15` → 镜头语言段 `**机位与景别** / **镜头** / **构图** / **灯光** / **运镜** / **表演节拍** / **声音**`（shot_spec_v2 ①–⑦，首帧只用 ①②③④）→ `**光学**：焦段 mm｜T 光圈｜高度=`（L3）→ motion（最后一个 `——` 之后 = 落幅完整画面，≥40 字）→ `**H3提示词**`（```text 块，英文，(S1)/(S2) 编号、无人名 / 触发词 / 双引号）→ `【H3 audio】` 1–4 句英文 | `tools/validate_qwen_script.py:80-162` RULES；`config/director/shot_spec_v2.yaml` segments；`tools/qa/writer_lints.py:406-408` QW-L14 |
| 集头 | `## epN《标题》` + `**剧情**` + `**出场人物**` + `**用到的场景**` + `**造型｜角色**：服装=｜鞋=｜妆=｜发=｜甲=` + 本集场景表 / 人物表（继承项逐字照抄）+ “本集镜头规划”段（轴线 / 焦段档 / 过肩分配） | `validate_qwen_script.py:80-137`；QW-L8（`writer_lints.py:292`） |
| 集时长 | 各镜时长之和 60–120 s（L-092）；镜数 6 ≤ n ≤ max(8, 说话轮次+独白段, ⌈秒数÷6⌉)；写作按剪后算：剪前 ≈ 目标 ÷ 0.7（assemble 剪掉 ~30%） | QW-E2 / QW-E3（`validate_qwen_script.py:81-82`）；QW-T3（`writer_lints.py:41,61-65`：PACE_TRIM_KEEP 0.7、EPISODE_MIN_S 60、PACE_MAX_S 6.0、PACE_AVG_S 6.5、SPEECH_CPS 4.5） |
| 首尾帧设想（L-203） | 起幅 = 铺垫，落幅 = 落点；至少两项明显不同（景别 / 机位角度 / 人物位置姿态 / 关键动作完成 / 道具状态 / 光线），变化来自本镜运镜与动作；ep01 16 镜设想文档 `docs/master/EP01_FRAME_PAIRS.md`（psm9 回写，psm11 为 ep01 现行导入稿 `staging/P4_ep01.L3_psm11.md`） | L-203；`CHANNEL.md:378,392` |
| 背景视向子场景（K-WRT-L203b） | 同一影棚按机位方向分 `sk_white_cyc` / `_rev` / `_mirror` / `_top` / `_door`，父场景已登记即算同场（衔接“同场换机位”不算换场） | `validate_qwen_script.py:149,497-498` |
| 过肩 / 局部规则（L-204 ①） | 过肩前景人物首尾两帧都不露脸：人物行 presence=局部，部位写“背影+部位”（后脑 / 肩 / 耳廓转向）；只有身体部位词算 hidden（`prompt_v2.hidden_face`，`packages/schema/ns_schema/prompt_v2.py:316-338`）；过肩按原文“越X拍Y”认（括注也认） | L-204；`services/agent/ns_agent/asset_refs.py:1307-1325` BACK_PART_WORDS；`CHANNEL.md:397` |
| 运镜白名单 | 6 种 enabled：static / push_in / pull_out / bolt_push_settle / handheld_follow / pedestal_up；双人镜只 static / push_in / pull_out / handheld_follow（multi_person_moves）；truck / arc / pan / tilt / zoom / focus_pull disabled 待复测 | `config/director/camera_moves.yaml` moves[].enabled、multi_person_moves（L-192） |
| 焦段表（L-192 ③） | 建立 24–35 T2.8–4（一场最多一个）/ 双人中景 40–50 T2 / 过肩近景 65–85 T1.4–2 / 特写 85–135 T1.2–1.4 / 插入 100 微距 T2；兜底 by_kind：establishing leica_cine_28_t28、two_shot arri_cine_50_t2、ots_or_single_mcu arri_cine_85_t14、closeup leica_cine_135_t12、insert leica_cine_100_macro_t2 | `tools/script_rsi/rubric_code.py:746` L3_TABLE；`config/director/lenses.yaml` by_kind |

### 2.2 导入

| 步 | 内容 | 出处 |
|---|---|---|
| 校验 | `tools/validate_qwen_script.py <P4.md> --json`：真实导入器解析 + `ns_schema.h3_lint.lint_h3` + 字段规则（block / warn）；退出码 0 无 block / 1 有 block / 2 解析不出 | `validate_qwen_script.py:1-15` |
| 写手 lint | `tools/qa/writer_lints.py`：QW-T1/T2/T3（warn）、QW-L1/L2（L1 平光 / 三层，warn）、QW-L3–L8（L2 镜头语言，warn）、QW-L9–L11（L3 焦段 / 背景光源 / 双人站位，warn）、**QW-L12 / QW-L13（L-201，block）**：同场相邻两镜景别或机位至少一项要变；现实↔幻想切换前后两镜写触发画面；**QW-L14（L-203，block）**：起幅与落幅 ≥2 项不同、落幅 ≥40 字 | `writer_lints.py:284-295,379-412`；`validate_qwen_script.py:710-714`（只对 V2 及以后的剧 hard_run） |
| rubric 闸门 | `producer.py import-staged` 先核 sha256 → `rubric_gate()`（`tools/script_rsi/rubric_code.py` 代码判定项，失败 ≠0 不放行；`--skip-rubric-gate` 只有总调度）→ `/api/script-inbox/validate` block=0 → 导入到 `data/import/runs/<run>/script_v2.json`（非主剧 / V2 走 `tools/import_script.py -o … --no-timeline`，同 run 旧稿备份 `backups/`）→ `import_events.append_import` → 审计 `log.jsonl` imported_staged / import_blocked | `producer.py:4306-4370,4542-4580` |
| 摆位判定 | K-WRT-H15 接触动作 / H16 双人景别（`tools/script_rsi/staging.py:1-10`），psm11 时 rubric 29/29 ok、validate block 0 / warn 5、临时编译 FIRST 16/16、LAST 16/16 ok | `CHANNEL.md:392` |
| 成人标记 | `compiler.classify_adult`（ADULT_KEYWORDS，NUDE_BENIGN 裸妆 / 裸色不算；`config/adult_overrides.json` 覆盖）；成人镜在 提示词 / 出图 / 出图检测 / 尾帧 / 视频 阶段 = 等项目方触发，不算阻断 | `services/agent/ns_agent/compiler.py:43-67,518`；`sop_gate.py:53` PENDING_OWNER_STAGES |
| 导入后 | 两台 probe-prompts（K-OPS-I13）；episode_pipeline 重编 `first_frame_jobs.json`（`tools/pipeline/image_jobs.rebuild_first_frame_jobs`）→ 写 `data/autopilot/ready_episodes.json` | `tools/autopilot/episode_pipeline.py:1-16`；`episode_run.py:319-323` |

### 2.3 同步

- 代码 / 规则：只经发版 `deploy`（`AUTO_CODE_PUSH=False`，`resident_sync.py:871`）。
- 运行期产物（笔记本 → 两台）：run_sync 每 120 s 增量（`RUN_SYNC_EVERY_S`，`:1411`），小文件 ≤2 MB 一批经命令主连接 stdin tar，≥512 KB 的大文件经 `<host>-hk` sftp 每 tar ≤32 MB（`:1414-1416`），跳过 writer 包 / 评审 / video 目录 / 日志（`:1419-1423`）；控制文件（master_rejects / ready_episodes / laptop_ctrl…）按对象合并推（`:766-768`）；单批卡 300 s 杀 ssh 重连（BATCH_TIMEOUT_S `:293`）；LINK_KBPS 1500（`:295`）。
- 首尾帧（出图机 → 视频机）：relay_frames 每 60 s + puller 回执 15 s 触发（`:1675-1676`），远端 `merge_takes` 只并非 video 的 take、保留目标机的 active.video（`:1681-1691`）。
- 服务器 → 笔记本：puller（§1.3）；镜像 `data/producer/registry.json` 每 90 s（**注意**：本机现存的 `data/producer/registry.json` run=series10_v1，是旧镜像，§8）。
- 分区 / control：`tools/netfix/dispatch.py` 按 `config/netfix/partition.json` ∩ `ready_episodes.json` 算每台 `control.json` 的 only / hold_lanes / paused（`dispatch.py:1-15,286-333`）；images gpu33 [1,3,5,7,9,10] / gpu36 [2,4,6,8]，video gpu33 [3,5,7,9,10] / gpu36 [1,2,4,6,8]（`partition.json` images / video）；跨机不接手（work_stealing false）。**partition.json 是运行期可变文件**（retired_lanes / _temp_holds 被 asset_worker 实时改，工作树与 HEAD 差异即此，`git diff config/netfix/partition.json`）；新位置 `data/state/netfix/partition.json` 兼容期先新后旧（`dispatch.py:34-35`）。

### 2.4 资产就绪（按镜，L-202）

| 项 | 内容 | 出处 |
|---|---|---|
| 判定 | `sop_gate.check_assets(root, run, ep, shot)` 读 `data/pipeline/asset_jobs/<run>/_ready_epNN.json`（asset_jobs.generate 写，含 shot_gaps {镜号: [缺口]}）；`whole_episode_assets=false` → 本镜缺口为空即放行；音色不挡首帧（ASSET_JOB_NO_BLOCK={voice}） | `sop_gate.py:201-250`；`config/pipeline/sop_gate.json` whole_episode_assets；`tools/pipeline/asset_jobs.py:553-575` |
| 按镜放行到派单 | `episode_pipeline.sync_shot_ready` 每拍把缺口为空的镜写进 `ready_episodes.json`（partial 条目）→ `dispatch.control_for` only 含这些镜（resident_sync loop 每拍调） | `episode_pipeline.py:356-416`；`resident_sync.py:2327-2330` |
| 作业类型 | face-<cid>（候选 8）/ scene-<sid>（2）/ sheet-<cid>-<look>（3）/ item-…（2）/ voice-<cid> / meta-* / golden-epNN | `config/pipeline/asset_worker.json` candidates；`asset_jobs.py:33-35` |
| 执行器 | `asset_worker.tick`（autoflow_resident 每拍）：单实例锁 `asset_jobs/worker.lock`；空闲道 = hosts image 道 − exclude_lanes[gpu33:2] − 别人 hold/lend − 队列有活；每道 `lanes.py hold --by ASSET-WORKER` 15 min（作业活着过半续期）；max_parallel 6；作业超时 90 min；max_attempts 2；ready_every_s 300；未测（看图 / 人数不可用）退避 300 s | `asset_worker.json`；`asset_worker.py:129-131,317-360,1248` |
| 候选检查 | 唯一编译入口 `frame_job.build_first`（mode=setting_candidate + asset_stage，preflight 豁免表 ASSET_STAGE_WAIVE：face→I2,I3；sheet→I3,I4；scene→I5；item→I3,I4）→ 出图 → postflight + Q9（设定候选口径）+ 人数 + 一次合并看图（age / ocr / 逐条） | `services/agent/ns_agent/gen_contract/preflight.py:481-503`；`PIPELINE_SOP_V2.md` §第 8 步 |
| 代选（L-136 / L-198） | `config/pipeline/owner_delegate.json` enabled 时按分自动登记最好一张（picked_by=系统自动）；项目方在网页做任何决定即到期自动关（11-05 21:59 已到期，enabled=false）；首帧代选 `first_frame.enabled=true timeout_min=30`（L-142）不受 L-136 影响 | `owner_delegate.json` |
| 登记 | POST /api/owner/pick → 清单 characters[cid].face / scenes[sid].base / looks[look].sheet / items；推两台 `sync.verified_install`（核 sha） | `PIPELINE_SOP_V2.md` §第 8 步 7 |

### 2.5 提示词探针（证据指纹）

- 探针 = `sop_gate.compile_preflight`：隔离子进程按剧环境对每镜跑唯一编译入口 `frame_job.build_first` + `preflight.check`，不出图（`sop_gate.py:999-1056`；`prompt_probe` "build_first+preflight"，`probe_lane` gpu36:0，`probe_timeout_s` 900）。
- 证据文件 `data/pipeline/sop_gate/<run>/epNN_prompts.json`（schema nsfs.sop_gate.prompts/2）：`fingerprint {import_sha, manifest_sha}`、`manifest_keys`（本集用到的清单条目，W38 按集指纹）、`shots{N: {ok, why, prompt_sha, refs_sha, manifest_keys, input_fp}}`（实读 ep01：16/16 ok，at 2026-11-06T00:49:46）。
- 过期判定：导入稿 sha 或（按集）清单 sha 变 → “证据过期”；按镜 `input_fp` 没变的镜照常可派（`sop_gate.py:305-345,1069-1075`）。
- 自动刷新（FIX-ORCH O1）：阻断原因含 STALE_MARKERS（证据过期 / 还没有证据 / 探针超时，`:716`）且 `auto_probe_stale=true` → 后台起 probe-prompts；锁 `epNN_auto_probe.lock` 按 pid 判在跑；正常写完 30 s 可再探（`AUTO_PROBE_MIN_GAP_S`）；崩了 300 s；超时写“探针超时”证据并 300→600→1200→2400 退避、封顶 3600（`:712-716,798`）；退避期间 require_backoff 封顶 120 s（STALE_BACKOFF_S）。health_tick 的 stale_prompt 检查也会调同一函数（`health_tick.py:185-186`，分项 apply 已开）。

### 2.6 首帧

| 项 | 内容 | 出处 |
|---|---|---|
| 派单对象 | 登记表（`producer.derive`）每镜 objects first / last / video；候选 = status ready 且不在退避、不在途；排序：集号小→大、驳回 / 插队先、尾帧先于首帧、按镜号 | `producer.py:1724-1800,3470-3478` |
| 派单前闸 | 成人镜等 owner_triggers；本地专用资产只派自有机器道；`hard_capped`（24 h 该阶段自动版本 ≥30 → cap_exhaust 标用尽 → 采用最好一版，L-204 D2）；`obj_rate_exceeded`（同对象 1 h 派单 ≥8 → runaway_hold 6 h）；`sop_gate_block`（require_backoff 阶段 出图/尾帧，失败关闭）；attempt > MAX_TRIES=3 不派 | `producer.py:3478-3560,3164-3200,2951-2963,3570-3595` |
| 编译 | `frame_job.build_first(project, ep, shot, globals)` → compiler v2 + 模板 v2（`prompt_template_v2.image_body`）：① 首句 景别（中文+括注）+ 机位 + 焦段 T 值 + 景深 + 焦点（焦点人 / 略虚人）② 同框句按露脸人数 ③ 人物行（造型 / 站位 / 动作；背影人写“背对镜头的背影”）④ 场景：+ 光线：（L1 布光句，按分镜【灯光】字段生成，`prompt_v2.lighting_en_from`）⑤ 材质 / 近景技术句 ⑥ “X 的脸、发型、服装以参考图为准” + 风格后缀；负面词 = negative_extra（看镜头 / 正对镜头 / 多余的人物 / 平光 / 白边 / 塑料皮肤…）+ 否定改写对象 + “第 N+1 个人” + MINOR_GUARD“未成年人外观”（永在） | `services/agent/ns_agent/prompt_template_v2.py:251-345`；`config/compile/run_style.json` prompt_template_v2；`compiler.py:25` MINOR_GUARD；`frame_job.py:591` job_negative |
| 参考槽（L-204 ②） | 优先级：身份脸（0 / 0.5；三人镜合成 faceboard）> 主体造型设定图（1）+ 主体单品（2.x）> **场景底板（5）** > 第二人设定图（11）> 第二人单品（12.x）；槽满先让位低优先级；第二人服装走文字 + 首帧连续性 | `asset_refs.py:59-61` SCENE_SLOT_PRIO=5.0；`frame_job.py:1083` 规则注释“身份脸 > 场景 > 本场造型 > 其它” |
| 出图档位 | `first_frame_tier(project, episode)`：series10_v2 default **base35**（unet base / 35 步 / cfg 3.0 / euler / simple）；**[本地未入版]** `from_episode {"2": "turbo_previz"}`（L-206 ②A）；没列的剧 preview（预设自带 turbo 8 步）；作业签名带 tier= 段 | `config/render_quality.json:1034-1052`；`frame_job.py:477-531`；`producer.py:188-200` job_sig |
| 种子流 | K-REN-954：key `<镜>/<stage>/<salt>`，第 k 颗 = `pipeline.seed_for(key,k)`，跳过本镜本 stage takes.json 里用过的种子（重试永不复用）；L-204 D8 加轮时 salt 带 `gazeN` | `services/render_router/ns_render/seed_stream.py:1-20`；`producer.py:3648-3664` |
| 阶梯（rung） | 第 1 次 frame_v9 默认 → 第 2 次换 seed → 第 3 次再换 seed（双人镜改两张脸各占一槽）；驳回阶梯 redo_ladder：输入变了重置不计次；输入没变追加 frame_v9_heavy ×2（skip_heavy_on 含 Q1 时跳过重档）；再不过标 best_effort | `producer.py:3666-3683,3262-3312`；`config/policies/retry.yaml` redo_ladder |
| 渲染 | `unified_frame._run`：`workflows.qwen_edit` 建图（Turbo 默认，预设 / tier 覆盖采样；cfg>1 时把负面词写回 TextEncodeQwenImage）→ ComfyUI → 下载 raw → `image_params.post_file` 后处理（1.5× 出 1152×2016 → lanczos 缩回 768×1344 → post_film 胶片调色，USM 关）→ Take（workflow frame_v9_unified，params.compile_trace / tier / previz / prompt_template）；渲染超时 = 900 s × 预取深度 = **1800 s**；租约 LEASE_S 45 min | `unified_frame.py:35-54,105-150`；`producer.py:542-552,109`；`render_quality.json` post_film |
| 预取 | 每道 ComfyUI 队列深度 prefetch_depth=2（`config/policies/resources.yaml:41-44`；NS_PRODUCER_PREFETCH 覆盖）；**[L-206 实现中]** frames 阶段适用集 → image_prefetch_depth=1 | `producer.py:528-540,3327-3347` |
| 打分 | 出图完成 → `post_pool`（max(6, 道数×深度)，`producer.json` post_pool.max_workers=0）里 `_postflight`：gpu33 原始输出 `remote_score.postflight_full`（常驻 8873/8874；失败 10 s 重试一次 → 退回 `UF._postflight`）→ `vqa_gate`（Q9 看图）→ QB 跳过（run_qb=false）→ 尾帧加 FL → `apply_blocking_policy`（L-196 硬项）→ canary（ignore Q1）→ `FE.annotate` + `auto_current.on_contract` + outbox | `producer.py:2302-2383,563-580`；`config/pipeline/producer.json` |
| 背压 | 积压 = 等开始打分的图（不含打分中）；上限启动 2×道数×看图实例，之后按最近 15 min 吞吐动态算（dynamic_backlog）；到上限停派并开工单 score_backlog | `producer.py:555-561,2600-2606,3454-3466` |

### 2.7 首帧检测（契约项与阻断）

契约 = preflight（出图前 I1–I13）+ postflight（出图后 Q1–Q9 + Q1a / Q1x / Q10 / QB / G1 / 尾帧 FL）；全部项照跑照记，只有 `blocking_items` 挡（§4）。

- preflight 项（`preflight.py:26-33`）：I1 在画角色清单 / 朝向站位；I2 身份脸参考（露脸人必须有清单身份脸 + 槽；faceboard 算）；I3 本镜造型 id + 设定图（露脸且服装入画无设定图 = fail，资料不齐不出）；I4 景别可见单品图；I5 场景底图；I6 提示词 = 编译器输出 + 参考逐一标注；I7 系统后缀 = 当前预设、无 suffix_banned 词（柔焦 / 奶油 / 浓郁饱和 / 油光 / creamy / plastic skin …，`gen_contract.json` suffix_banned）；I8 LoRA 白名单（lora_allow 只有 krea2_film_texture_qwen21；lin_wan_qi_v1 / glamour_realism 禁）；I9 槽位规划；I10 成年人 / 锁定外貌（HC-07）；I11 参考只认 assets_v2/manifest.json + sha；I12 本地专用资产只许自有机器道（L-128）；I13 品牌字样。
- postflight 项（`postflight.py:27-29,353-704`）：Q1 身份（ArcFace 对 face_of，每张 ≥min_face_ratio 的脸都要认得出；bank top-k；三段 bands + 复核带交看图）；Q1a 逐人头发属性（MediaPipe 分割 + 看图，L-205 非硬项看图不跑）；Q1x 同场跨镜（非硬项不跑）；Q2 造型（CLIP 区域，只判鞋 ≥0.775 / 下装 ≥0.83 / 设定图 ≥0.74，其余只记录）；Q3 景别（脸高档位 bands [0.45,0.27,0.17,0.115,0.095,0.05] 容差 1）；Q4 质感（record_only）；Q5 手 / 多肢（max_flags 0，肢体比例 / 手型只记录）；Q6 文字（OCR 框 >0 挡，纯数字标点忽略）；Q7 场景（record_only）；Q8 发色（record_only）；G1 视线（YuNet，L-200 时判 fail）；Q9 本地看图缺陷清单（`config/vqa.json` checks）；Q10 出图后验收（identity / outfit / prompt / count 四标签，`tools/vqa/accept.py`）；QB 共用验收（现关）。
- 看图调用（Q9）：`vqa.contract.inspect_for` → `vqa.client.generate`：路由 W23——服务器上 OFFLINE_SELF 本机 8870（loaded 即用，忙等 ≤ busy_wait_s 600，poll 10 s）→ 否则 `model.lan_url` 10.0.0.36:8870；笔记本先 8871 隧道（laptop_prefer_tunnel）再本机 8870；都不在 = untested（不判 fail）；HTTP 超时 timeouts[kind]×(排队+1)：image 240 / video 300 / ask 180 s；单次最长等待由调用方 wait_s（现 900）定；**[L-206 实现中]** 只去审图位（`client.py:246`）。一次看图同时判 eye_contact / lineup（lineup 不另起调用，`vqa.json` checks.lineup._doc）；看图视线结论矛盾 → `reask_eye` 重问一次（`vqa/contract.py:291-317`）；G1 与看图都有结论时以看图为准（`blocking.py:60-71`）。
- 重出阶梯：每镜每阶段 MAX_TRIES=3（`producer.py:104`）；内容不过 → 下一次换种子（rung）；3 次用尽 → `escalate_exhausted`（输入变了重置 / 重档 / best_effort）→ `review_adopt_auto=true` 时 `adopt_best_effort_sweep`（每 120 s）取 Q1–Q9 全过且分数最高版设为当前并标 review_needed；没有全过版 → relaxed 取 safe_take（成人 / 文字不过的除外）；**看镜头 / 排排站（gaze_bad）或首尾太像（fl_bad）的版本任何采用路径都不收（never_adopt）** | `producer.py:1516-1545,1610-1660,2898`。
- 视线 / FL 兜底轮（L-204 D8）：3 次用尽且候选全是 never_adopt → 自动再给换种子轮（gaze_round+1，最多 GAZE_EXTRA_ROUNDS=2，每轮 3 次，硬上限放行 3 次）；轮也用尽：尾帧 → `last_unavailable` + takes.json 顶层 `last_frame_fallback={mode:"i2va", first_n}`（视频退回只给首帧）；首帧 → 取没看镜头的最好一版，没有就取最好一版标 gaze_waived + review_needed 并报卡点 | `producer.py:106,2975-3014`。
- 尾帧 preflight 死路修复（REVIEW-SV CRITICAL，11-06）：尾帧生成契约 preflight 不过按次计数，60 s 后重编重试，满 MAX_TRIES=3 次 → 退回 I2VA（同 D8），不再 30 min 退避无限重来、也不再把 assets:{sid} 标 blocked 连带挡首帧 | `producer.py:3839-3859`。
- 其它错误分类：code 错 → CODE_RETRY_S 300 后再试、不计次；infra 错 → INFRA_BACKOFF (30,60,120,300,600) 换道、不计次；preflight 缺资产 → 等资产（签名变即放回，上限 WAIT_ASSET_MAX_S 6 h），其它 preflight → PREFLIGHT_RETRY_S 1800 | `producer.py:110-111,132,630,3820-3870`。

### 2.8 尾帧（L-203 compose）

| 项 | 内容 | 出处 |
|---|---|---|
| 模式 | `run_style.json runs.series10_v2.last_frame_mode = "compose"`（env NS_LAST_FRAME_MODE 可临时覆盖）；"edit" = 旧法（首帧作图1 + bible last_frame_keep 小改） | `services/agent/ns_agent/video_mode.py:60-75`；`config/compile/run_style.json` |
| 编法 | `frame_job.build_last_compose`：落幅 = motion“——”之后文字（`end_framing`，`_END_RE` 落幅=）当新图编（景别 / 机位按落幅改写 `last_angle_field` / `compose_last_shot`），同首帧模板 / 槽位逻辑（留一槽），通过契约的首帧挂最后一张参考 `continuity_slot`，标注句 “图{n}是本镜头首帧，只用来保持人物服装、发型、场景陈设与光线一致；构图、机位、景别按下面的结束画面重新构图。”；槽满顶掉最后一个非脸槽（sheet / board / item 优先让位） | `frame_job.py:412-446,645-760` |
| preflight | 同首帧 I1–I13 + 连续性参考检查 `_continuity_ok`（图号对得上） | `preflight.py:191-205` |
| 依赖 | 首帧 passed 才给尾帧（deps_ok=first_ok_for_last）；首帧换版 → 旧尾帧作废（voided）并账本清零不计次（L-204 D5 `void_reset`）；**[L-206 实现中]** hold_regen_downstream：首帧换代中不派尾帧 | `producer.py:1789-1793,2965-2973`；`lane_roles_producer.py apply_hold_regen` |
| FL 比对 | 尾帧 postflight 并入 FL：`first_last.similarity`（struct = 24×42 模糊亮度相关 ≥0.80 或 ssim（宽 256 亮度 SSIM）≥0.85 → 太像 fail；读不到图 untested 同样挡）；校准：ep01 111 对 struct 中位 0.82 / p75 0.94，S1 v7 0.858、S2 v3 0.828（项目方点名太像）、真推近 S8 v21 0.736 | `gen_contract/first_last.py:1-20,54-72`；`config/gen_contract.json` first_last / _first_last |
| 档位 | 与首帧同一张表（base35；**[本地未入版]** turbo_previz.last_frame.previz=true 时按落幅另算尾帧摆位图，缓存 auto_last/） | `render_quality.json:1049` |

### 2.9 视频

| 项 | 内容 | 出处 |
|---|---|---|
| 模式 | `video_mode.mode = "fl2va"`（首帧 + 尾帧两张不同画面之间生成，L-203 撤回 L-197 A）；I2VA 代码留：`video_mode.no_last(run, ep, shot)`（mode i2va + from_episode / shots）或 takes.json `last_frame_fallback=i2va` → `keyframes.last_frame_mode=none` | `video_mode.py:17-49`；`build_jobs.py:324-347,425-435` |
| 进入条件 | `build_jobs.passed_frames`：active.image 版本 postflight.ok 且无 master_reject 且 `q9_passed`（video_requires_q9）且 anomaly 不挡且出图后验收 pass（review_needed 的版本视同 pass）；尾帧同理 `passed_lasts`（@last_frame 必须存在，否则变体 no_last_frame 不提交）；sop_gate“视频”阶段按镜 `filter_video_specs`；首帧换代中（L-206）/ video_hold.json 按镜 hold → route=hold | `build_jobs.py:186-347,543-631`；`config/vqa.json` gate.video_requires_q9 |
| 变体阶梯 | jobs.json 每镜一组变体（v1 + r24 / alt / b24 / i2v / mot + 种子 s2 / s3 / s4）；`next_variant`：第 1 条 v1（派不了取阶梯第一个能派的）；按上次 gate.fails 选：身份偏离→r24,alt,b24；脸部泛红→r24,b24；景别不符→i2v；动作不足→mot；再 SEEDS；**MAX_RENDERS=4**（force_queue 不受限）；preflight 不过的变体不提交 | `vidgen.py:68-69,274-304` |
| 配方 | pika_only：只许 `i2va_pika_flex`（L-088），别的配方 hold 不回退；dejudder 开（J4 >1.2 且 z ≥3 → `tools/dejudder.py`） | `config/pipeline/video_policy.json` |
| 道 / 让道 | night_control 默认 shared_lanes 全 6 道、per_lane 2、**yield_s 30**（FIX-VID：180→30）、poll_s None → V2 45 s（V1 120）；hold_lanes 由 partition / 分片 / L-206 并入；video_lanes = 专用视频道不受让道；vram_gate（video_boost）可按道设显存门槛；LANE_MAX_FRAMES 260（超过改派长镜头道 gpu36:2） | `night.py:59-67,959-967`；`vidgen.py:63-66,417-440,689-700` |
| 提交 / 超时 | `Lane.submit` POST /prompt timeout 120；`timeout_for(frames)` = max(3600, 3600×(frames/192)²)，steps>12 再 ×steps/12；上传 UPLOAD_TIMEOUT_S 900；帧数 = `frames_for_seconds`（ceil(秒×24) 对齐 17k+5，107–362 = 4–15 s） | `h3_video.py:50-62,202,392-470`；`packages/schema/ns_schema/h3_lint.py:20,72` |
| 打分 | `score_clip.py`（venv_idm，线程池 gpu33 3 / gpu36 2，NS_SCORE_THREADS 4）：运动量 mean / p90、J4 抖动、硬切、YuNet+SFace 身份（每 6 帧）、泛红、V6 手数（venv_hand）、V7 口型、V9 看图抽帧（6 帧）；GATE mean_min 0.5 / cheek_red_max 0.25 / cuts_max 0 / sface_min 0.30 / seen_min 0.15 / J4_soft 1.3（只软项）；多肢 = V6 命中 且 看图 extra_limbs 两者都成立才挡；score 子进程 timeout 1500 s | `tools/series10_video/score_clip.py:1-12,43,303-345`；`vidgen.py:22,464,830-848` |
| 落定 | 变体过 gate → done（chosen）；阶梯用尽 → best_effort 取 penalty 最小（L-196）；连续 2 次提交报错 → blocked；口型重出作废每镜 ≤ lip_redo_max_per_shot=1 | `vidgen.py:244-256,575-612,752-784`；`config/post/director.json` lip_redo_max_per_shot |
| 分片（L-193 按镜跨两台） | `video_shard.json`：ep01 owner gpu36，权重 gpu36:gpu33 = 3:2（确定性分配，同配置同剧本两台算出同一张表）；exclude gpu33:3；helper 只出镜不合成；领取表 shard_claims.json（CLAIM_LEASE_S 1800）；helper state >900 s 没更新 = 失联收回（HELPER_STALE_S）；只从 state ≤300 s 新鲜的台抢镜（STATE_FRESH_S）；笔记本 shard_relay 每 120 s 拉 state_<host>.json / jobs.json、把 helper 的 clips/*.mp4 + scores 送 owner | `video_shard.py:144-146,182-183`；`shard_relay.py:1-25` |
| 空卡巡检联动 | idle_watch 探到本台有可派视频而道空 → `night.py --once`（最多每 act_gap_s 600 一次） | `idle_watch.py:220-223,536-540`；`config/pipeline/idle_watch.json` |

### 2.10 合成 → 成片

`night.finalize`（`night.py:575-690`）在 `ep_resolved`（本集每镜 done / best_effort / blocked）后触发：

1. 前置：`voices_ok()`（config/voices.json 是本剧演员表）、`tts_missing()`（本机有 Kokoro / SenseVoice 解释器）否则 hold。
2. `vidgen.py proxies <host> <ep>`（服务器，venv_idm，超时 1800）→ `sync.py` 拉原片 → manifest.json；`drop_stale`：片子首帧 ≠ 当前首帧的旧片不进成片（D10）。
3. `upscale_preview.py epNN`：原片 → `_sr1080.mp4`（SeedVR2 结果优先，兜底 lanczos 放大 + unsharp 5:5:0.6、CRF 16）；J4 >1.2 且 z ≥3 先 `_dj.mp4` 去抖。540×960 代理只给审片页，禁止进成片（K-EDT-V10）。
4. 占位：没出片 / 过期 / 等闸门的镜 → 首帧静帧缓推（PLACEHOLDER_PUSH 0.06，`ns_post/assemble.py:717,753-760`）进 timeline，night_state 记 placeholder_shots；原片到位 < 需要数 → ASSEMBLE_BLOCKED 不合成。
5. `tools/assemble_episode.py epNN --out … --sources-from sources.timeline.json --variant vN --dialogue-source h3 --run <run>` [+ `--music-dir data/music/<run>` 或 `--no-bgm`]（超时 5400 s）：CPU only；对白 = H3 原声（回听 CER >0.35 的镜用 Kokoro TTS 兜底）；独白 TTS；SenseVoice 回听；剪辑规则 `render_quality.json post.edit_rules`（take_policy locked_qc、max_shot_s 4.5、split_zoom 1.15、pace_tighten：对白前 0.3 s / 后 0.5 s、无对白镜 ≤4 s、每镜 ≥3 s、J-cut 0.3 s、room_tone −50 dBFS、overflow_policy fail）；两遍 loudnorm −14 LUFS / TP −1.5；x264 crf 18；切点交叉淡化 0.12 s；skin_guard 对脸 a* 限幅。
6. `episode_hard_rules`：挡 C-07 字幕流、无视频流、C-08 单镜 >6.0 s（容差 0.05）、L-092 剧本集长不在 60–120 s；只记：合成实长不在 60–120、合成闸门 verdict=fail（缺镜 / 溢出）。不过 → 留 `_work` 不进 `data/episodes/<run>/`。
7. `tools/director/finish.py <mp4> --script <导入稿>`：post_pass（调色 + 音效 + 响度）→ film_score → lip_redo 记单（K-EDT-805）；delivery_gate 放行 → 交付后期版（`config/post/director.json` enabled / post_pass / film_score / lip_redo / shot_music_off / camera_norm 全 true）。
8. `episode_report.py <ep> <host> <ver>` → `docs/series10_video/<run>/epNN_review.md` + `data/review_pages/series10_video/<run>/epNN/index.html`（LABEL：done=预览、best_effort=未达契约）。
9. `bgm_after_assembly`：`tools/bgm/bgm_library.py` 判剪辑锁定（L1–L5），只差 L5 → 自动再合成一次确认；锁定且曲库配乐已交付而本版无 BGM → 再合成一次带 BGM；同签名最多 BGM_AUTO_MAX=2 次（曲库 `config/music_v2.json`，ACE-Step 生成 `config/bgm.json`，loudnorm −16 LUFS）。
10. `retro_after_assembly` → `tools/master/episode_retro.py auto` 写 `docs/master/RETRO_epNN.md`（复盘，第 N+2 集出图前必须 done）。

### 2.11 拉回 / 审片页 / 复盘

- 拉回：episode_run `act_pull` 经 `tools/master/partial_pull.py` sftp 拉成片到本机，大小核对（`episode_run.py:477-516`）；对比页 `data/review_pages/<run>_epNN_compare/index.html`（新版 vs 上一版 + 瀑布）；耗时瀑布 `episode_timeline.py`；一集任务表 `data/pipeline/runs/<run>/episode_run/epNN_tasks.json` + `epNN_events.log`（`episode_checklist.py:1-12`）。审片页本地打开（`feedback-local-review-pages` 记忆）。
- 计量：`data/pipeline/runs/<run>/metrics/epNN.jsonl`（METRICS_SPEC §A）；`tools/master/episode_metrics.py` 汇总 → `epNN_summary.json`（现存 ep01_summary 是 11-03 的 11 镜版）。
- KPI 耗时表：L-205 要求每集逐步耗时表并归因；目前只有 checklist 任务表与 metrics jsonl，**11-06 ep01 这一轮的正式耗时表尚未生成**（episode_run 关着）。

---

## 3. 模型与参数表

### 3.1 出图（Qwen-Image 2.1，ComfyUI）

| 档 | 权重 / 参数 | 出处 |
|---|---|---|
| 默认图（QwenModel） | unet `qwen_image_2.1_turbo_int8_convrot.safetensors`、clip `qwen3vl_8b_int8_convrot.safetensors`、vae `qwen_image_2.1_vae_bf16.safetensors`；预设 leica_sstar 用 texture_fix VAE `texture_fix_vae_for_qwen_image_2.1_bf16.safetensors` | `ns_render/workflows.py:17-20`；`render_quality.json` tiers.final.vae、image_presets[leica_sstar].params.vae |
| base35（ep01 现行） | unet base `qwen_image_2.1_int8_convrot.safetensors`、35 步、cfg 3.0、euler / simple；负面词生效；1152×2016 出图缩回 768×1344；实测 ~328 s/张（8 步 ~61 s） | `render_quality.json:1035-1037`、tiers.final.unet |
| turbo（L-206 退路）**[本地未入版]** | unet turbo、8 步、cfg 1.0 | `render_quality.json:1041-1044` |
| turbo_previz（ep02 起）**[本地未入版]** | 8 步 turbo + Fun ControlNet Union `qwen_image_2.1_fun_controlnet_union_int8_convrot.safetensors`（ModelPatchLoader → ZImageFunControlnet → QwenImage21Cache）；control strength 0.55、start 0.0、end 0.7；摆位图 `tools/previz/auto_blocking.py`（CPU 光线投射，render_scale 0.5，单镜 5–10 s，缓存 `data/previz/<ep>-S<n>/auto/<sha12>/`，算不出退 turbo）；尾帧 previz=true | `unified_frame.py:55-73`；`render_quality.json:1045-1052`；`auto_blocking.py:1-16` |
| LoRA | 生产只许 `krea2_film_texture_qwen21.safetensors` 0.5；frame_v9_heavy = krea2 0.8；lora_cap 1.6 | `gen_contract.json` lora_allow；`producer.py:5061` PRESET_WORD；`render_quality.json` tiers.final.lora_cap |
| 分辨率 | 768×1344 交付（render_scale 1.5 → 1152×2016）；IMAGE_SIZE 画布 1088×1920 | `render_quality.json` image_presets[leica_sstar]；`ns_render/pipeline.py:70` |
| 后期 | post_film enabled=true、usm=false；film {knee 0.78, knee_a 0.66, s_curve 0.12, lift 0.0157, gamma 1.0, sat 1.08, vib 0.08, skin_keep 0.5, grain 0.012}；lut apply=false | `render_quality.json:1054-1060` |
| 风格后缀 | 段落预设 fantasy `v2_editorial_fantasy_c`（LUT v2_fantasy_c.cube）/ reality `v2_editorial_reality_c2`（v2_reality_c2.cube），default_segment reality；V1 S★ 短语（徕卡 / S★ / R0 / 50mm f/2 / 暖调通透…）出现即阻断 | `run_style.json` runs.series10_v2.segments、v1_style_phrases；`render_quality.json:579,750` |
| 镜头句 | 分镜【光学】> 【镜头】id > lenses.yaml by_kind；V2 去品牌只写焦段 T 值 | `prompt_template_v2.py:126-181`；`run_style.json` shot_language |
| 景深 | lens_sim v2（`ns_render/lens_sim_v2.py`，VERSION lens_sim/v2-optics：按焦段 / T 值 / 对焦距离算 CoC，分层散焦）——生产是否接入 **[未核实]**（L-197 B 说“景深交给 lens_sim v2”，本轮只见模块与 A/B 脚本 `tools/research/lens_sim_ab.py`） | `lens_sim_v2.py:32,60-311` |

### 3.2 尾帧

同 §2.8：compose 模式、同首帧模型 / 档位 / 槽位；连续性参考句 `frame_job.py:645`；旧 edit 模式模板 `config/compile/bible_series10_v2.toml [assembly].last_frame_keep`（L-201 版：只锁人物 / 发型 / 服装 / 场景 / 光线，机位景别跟落幅）。

### 3.3 视频（MiniMax H3，ComfyUI）

| 项 | 值 | 出处 |
|---|---|---|
| DiT | `minimax_h3_fl2va_pruned_int8_convrot.safetensors`（int8；w4a8 + LoRA 时补丁失效 ComfyUI #16420） | `workflows.py:29` |
| 文本编码器 / VAE | clip `qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors`；video VAE `minimax_h3_video_vae_int8_convrot.safetensors`；audio VAE `minimax_h3_audio_vae_fp32.safetensors`（必须 fp32） | `workflows.py:41-45` |
| 默认基底 pika_flex | LoRA `pika_h3_flex_fl2va_comfy_bf16.safetensors` 1.0（sha256 68783e64…）、6 步、lcm、ManualSigmas "1.0, 0.972973, 0.923077, 0.8, 0.571429, 0.333333, 0.0"、shift 12/3 已算进 sigma、cfg 1.0、BasicGuider、steps 不可改；首尾帧都给 | `render_quality.json` video_bases.default / bases[pika_flex] |
| 备选 | official_turbo（`minimax_h3_fl2v_turbo_8step_v1.1_768p_comfyui_bf16` 1.0、8 步 euler/simple、shift 6/3）；official_base（无 LoRA、24 步、shift 12/3、只给首帧，≥261 帧自动挂 1e-4 Pika LoRA 防 OOM） | 同上 bases[] |
| 尺寸 / 帧率 | VIDEO_SIZE 768×1344、24 fps；帧数 17k+5，107–362 帧（4–15 s）；每道上限 gpu33 260 帧，h3_funcontrolnet 107 帧 | `pipeline.py:71`；`workflows.py:50`；`h3_lint.py:20`；`hosts.json` |
| 可选 LoRA | VBVR `H3-Licon-VBVR-I2V.safetensors`（仅研究、非商用，default_on false） | `render_quality.json` optional_video_loras |
| 运动质检 | motion_qc：still_diff 0.35、fail_mean 0.5、fail_p90 0.9、fail_still_frac 0.9、warn_mean 1.0、frozen_tail 1.0 s / head 1.5 s、keyframe_warn 10.0 | `render_quality.json` motion_qc |
| 运镜句 | 模板 v2：`h3_official` 官方写法（动词 + 幅度 + 速度），h3_amp_shift −1（推 / 拉幅度词降一档）；约束句 constraint_en “The face stays stable and sharp throughout, the frame clean of text and watermark” | `camera_moves.yaml` moves[].h3_official；`run_style.json` prompt_template_v2.constraint_en |

### 3.4 看图（Qwen3-VL）

| 项 | 值 | 出处 |
|---|---|---|
| 模型 | `Qwen/Qwen3-VL-8B-Instruct`，bitsandbytes nf4（峰值 7206–7386 MiB / 实例；gpu36 GPU1 实测 ~8.3 GB），本地权重 `models/Qwen3-VL-8B-Instruct-nf4` | `config/vqa.json` model.*；`tools/vqa/server.py:85,236` |
| 实例 / 端口 | router :8870 → 后端 8876/8878/8879（VQA_BACKENDS）；`model.instances`=2（配置）/ 3（gpu33:3 B1）；**[L-206 实现中]** review.vqa_instances 3、port_base 8870、实例 = 8870+6+i = 8876/8877/8878（`lane_roles_producer.py` REVIEW_PORT_OFFSET=6） | `vqa_router.py:24-25`；`vqa.json` model.instances；`config/pipeline/lane_roles.json` review |
| 口径 B | 主图 subject_max_pixels 600000、参考 ref_max_pixels 150000、max_new_tokens 1000（server 默认 900）、video_frames 6 | `vqa.json` model.*；`server.py:303` |
| 显存 / 卸载 | need_free_mib 7000；idle_unload_s 90（VQA_DEDICATED=1 永不卸载）；每做完一条查同卡 ComfyUI 队列，有活就让出 | `vqa.json`；`server.py:15,48-49` |
| 路由超时 | image 240 / video 300 / ask 180 s；queue_max 6；busy_wait_s 600；poll_s 10；health_timeout_s 3；route 日志 `data/vqa/route.jsonl` | `vqa.json` route |
| 判定口径 | judge.enforce=true、gate.enforce=true、untested_blocks=true、continuity_prev_shot=true、hair_primary=true、auto_review_redo=true；calibration min_agreement 0.85 / min_n 8 | `vqa.json` judge / gate |

### 3.5 身份 / 人数 / 视线 / OCR

| 检测 | 模型 / 参数 | 出处 |
|---|---|---|
| 身份 ArcFace | insightface **buffalo_l**（retinaface det_10g + arcface w600k_r50），CPU，det_size 640，模型根 `/root/work/fredw/idm_models`（NS_IDM_ROOT） | `tools/series10_imggen/score_remote.py:5,23-27`；`tools/identity_metric.py:2,40,171` |
| Q1 阈值 | lead / lin_wan 0.70，default 0.60，other_floor 0.40，other_margin 0.05，recognize_floor 0.45，min_face_ratio 0.04；bands default [[0.10, 近中景及以上, 过 0.60, 复核 0.50], [0.0, 小脸, 0.50, 0.40]]；size_tiers [[0.27,特写,0.55],[0.10,近中景,0.50],[0.04,小脸,0.40]]；bank k=3 anchor_min 0.50；复核带清晰度 band_sharp min 42.3；yaw_relax 关 | `gen_contract.json` image_thresholds.Q1_identity；`vqa.json` gate.band_sharp |
| 人数 / 异常 | `tools/vqa/anomaly.py`：person_yolov8m-seg、face_yolov8m、hand_yolov9c、buffalo_l、DWPose 133 点、OneFormer ADE20K swin-tiny（镜面）；TH：min_face_px 28、face_det 0.5、same_cos 0.40、pair_cos 0.50、mirror_cos 0.40、mirror_cover 0.5、person_conf 0.4、hand_conf 0.35、hand_nms_iou 0.45、kp_conf 0.3、finger 0.25–2.5；常驻 :8893（gpu36 GPU1） | `anomaly.py:1-20,32-44,474-484`；`resident_sync.py:2141-2142` |
| 看图人数闸 | Q10 prompt 子项 visible_people vs cast：少于“在画”或多于“在画+局部+背影” = people_count 不符 → count 硬项挡（blocking_items 含 count 恒开） | `tools/vqa/accept.py:174-257`；`blocking.py:36-41,74-79` |
| 视线 G1 | YuNet `face_detection_yunet_2023mar.onnx` + SFace `face_recognition_sface_2021dec.onnx`（`packages/qc/ns_qc/face.py:16-17`，score 0.6）；`ns_qc/gaze.py`：MIN_IOD 22 px、YAW_K 1.6、CAM_GAZE_X 0.22、CAM_PITCH (0.38, 0.80)；BLOCK=False / PROVISIONAL=True 但 L-200 下 blocking_items 含 gaze 即判 fail | `gaze.py:21-31`；`postflight.py:32-56` | ⤴ L-196/L-200（只记录口径为后续修订）
| 视线 MediaPipe（gaze_mp） | A 0.3、T 0.05、P 0.2、down_max 0.35、blink_max 0.6；标定 100 张留出召回 ≈0.73、误报 0–1/16 | `vqa.json` gate.gaze_mp |
| OCR | rapidocr-onnxruntime，置信度 ≥0.6 且字高 ≥ 画面高 1.2%；Q6 max_boxes 0，纯数字 / 标点框忽略（`^[\d\s.,:;\-/+%]+$`） | `score_remote.py:7`；`gen_contract.json` Q6_text |
| 造型 Q2 | CLIP ViT-L/14 区域滑窗（clip_srv CPU）：鞋 0.775、下装 0.83、设定图 0.74；feet_band [0.70, 0.78] 待目检；embellished_max 0.7；hand/neck/upper/waist/body 只记录 | `gen_contract.json` Q2_outfit |
| 头发 Q1a | MediaPipe selfie_multiclass 分割：below_max 0.15、blue_max 0.45、blue_min 0.20（人物卡由 `gen_contract/cards.py` 从 P1 生成） | `gen_contract.json` Q1a_attr |

### 3.6 声音 / 后期

| 项 | 值 | 出处 |
|---|---|---|
| TTS | Kokoro `kokoro-multi-lang-v1_1`（sherpa-onnx，CPU），服务器 `/root/work/fredw/speech/models/kokoro-multi-lang-v1_1`；音色表 `config/voices_v2.json` | `config/voices.json:4-9`；`services/post/ns_post/tts.py:1-6,45-49` |
| ASR 回听 | SenseVoice（sherpa-onnx CPU，FunASR licence），H3 原声 CER 上限 0.35 | `tts.py:1`；`assemble_episode.py:131` |
| 响度 | −14 LUFS / TP −1.5 dBTP（成片）；BGM 轨 −16 LUFS / −1 dBTP；H3 底床 −3 dB | `ns_post/assemble.py:11-12,53-56`；`tools/bgm/bgm_library.py:10` |
| BGM 生成 | ACE-Step `acestep-v15-xl-sft`（50 步 cfg 7，need 21000/16000 MiB 档）→ `acestep-v15-turbo`（8 步）→ CPU 兜底；打分 CLAP + Demucs（gpu36 CPU）；gates vocal_rel_db_max −20 等 | `config/bgm.json` generation.tiers / gates |
| 超分 | SeedVR2 3B（gpu33 `scripts/upscale_4k.py`，sr_short 1080 / 4K 2160×3840 只在 master/owner_approved）；兜底 lanczos + unsharp 5:5:0.6 CRF 16 | `vqa.json` upscale_4k；`upscale_preview.py:3-7` |
| 去抖 | `tools/dejudder.py`，门槛 J4 >1.2 且 z ≥3.0 | `video_policy.json` dejudder |
| 变声 | Seed-VC 只换 speaker 那句（VOX，项目方选“下载变声模型保留嘴型”）**[未核实现行是否启用]** | `render_quality.json:1027` |

---

## 4. 闸门与阈值总表

### 4.1 首 / 尾帧硬项（L-196 / L-200 / L-203）

`config/gen_contract.json` `blocking_items = ["Q1", "count", "text", "adult", "gaze", "FL"]`（D-V2-196），实现 `services/agent/ns_agent/gen_contract/blocking.py`：

| 硬项 | 触发条件 | 阈值 / 来源 |
|---|---|---|
| Q1 身份 | Q1 项 fail / untested；Q10.identity、QB.identity 同源 | §3.5 Q1 阈值 |
| count 人数 | Q10.count（anomaly）bad；Q10.prompt fail 且 why 含 people_count；Q9 defects 含 extra_person；QB.count | `blocking.py:21-23,36-41,74-79` |
| text 文字 | Q6 fail（OCR 框 >0）；Q9 text_watermark / brand_logo；QB.ocr | `blocking.py:21-23,67` |
| adult 成人安全 | Q9 underage_look；QB.age | 同上 |
| gaze 视线 / 排排站 | Q9 eye_contact / lineup；G1 fail（看图真看过且没报视线缺陷时 G1 只记录） | `blocking.py:20,60-66` | ⤴ L-196/L-200（只记录口径为后续修订）
| FL 首尾太像 | 只在尾帧阶段：struct ≥0.80 或 ssim ≥0.85；读不到图 untested 同挡 | `first_last.py` DEFAULTS、`gen_contract.json` first_last |

不在名单的项（Q1a / Q1x / Q2–Q5 / Q7 / Q8 / Q9 其余缺陷 / Q10 其余 / QB 其余）：照跑照记，status 改 na、`record_only=true`、原判留 `status_recorded`（`blocking.py:88-110`）。`vqa_skip_nonblocking=true`：非硬项看图子检查（Q1a 看图逐人问答、Q1x 同场跨镜、Q10 服装“谁穿什么”）不跑，记 `skipped_nonblocking`（`vqa/contract.py:49-60`）。QB 共用验收不跑（`producer.json` accept.run_qb=false）；`accept.skip_prefailed=true`；`max_rechecks` 2。

### 4.2 Q9 缺陷码分级（`config/vqa.json` checks）

| blocking=true（defect 即 Q9 fail） | blocking=false（只记录） | ⤴ L-196/L-200（只记录口径为后续修订）
|---|---|
| extra_person(Q1)、hair_mismatch(Q8)、framing_mismatch(Q3)、eye_contact(Q9)、underage_look(I10)、continuity_break(Q9)、lineup(Q9)、brand_logo(Q6) | extra_limbs、hand_malformed、body_anatomy、identity_drift、outfit_mismatch、shoe_mismatch、accessory_mismatch(soft)、clothing_state、wrong_scene、lighting_time(soft)、text_watermark、blank_expression(soft)、plastic_doll、face_artifact、artifact、collage_or_ref_leak、low_resolution(soft)、posed_stiff(soft)、item_on_wrong_person |

注意两层叠加：Q9 项内部按 vqa.json blocking 判 fail；再由 L-196 `blocking.apply` 只把 count / text / adult / gaze 对应缺陷算硬项——所以 hair_mismatch / framing_mismatch / continuity_break 虽在 vqa.json 是 blocking，最终只记录不挡（`blocking.py:21,68-72`）。 ⤴ L-196/L-200（只记录口径为后续修订）

### 4.3 视频闸门

- score_clip GATE：mean ≥0.5、cheek_red ≤0.25、cuts 0、每个应在画角色 SFace 中位 ≥0.30（检出 ≥15% 采样帧）、J4 >1.3 只软项；V6 手数（`gen_contract.json` video_thresholds.V6：extra_hand_frac 0.05、hands_max_per_person 2、dup_side_frac 0.15、flicker_max 10、bad_finger_frac 0.85、untested_frac 0.8）+ 看图 extra_limbs 同时命中才判多肢；V9 看图 blocking 缺陷进 fails（enforce 关 = 只软项）（`score_clip.py:43,303-370`；`gen_contract.json` video_thresholds）。
- 进视频前：首帧 postflight.ok + Q9 passed + anomaly 不挡 + Q10 验收 pass（§2.9）。
- 成片硬规矩：`night.episode_hard_rules`（§2.10 第 6 步）；sop_gate“整集预览”只认 `data/episodes/<run>/epNN_vN.mp4`。

### 4.4 其它闸门

| 闸门 | 规则 | 出处 |
|---|---|---|
| 导入 rubric | 代码判定失败项 ≠0 不放行；L-201 / L-203 规则 block | §2.2 |
| canary（换版首批复核） | 换版后前 6 镜同一阻断项失败 >34% → 暂停派单 30 min×2^strikes（≤4 h），ignore_items [Q1] | `producer.py:126-130,1299-1306`；`producer.json` canary |
| 硬上限 | 每镜每阶段 24 h 自动版本 ≥30 → 用尽 → 采用最好一版 | `producer.py:105,3164-3200` |
| 失控 | 同对象 1 h 派单 ≥8（NS_PRODUCER_OBJ_PER_HOUR）→ runaway_hold 6 h | `producer.py:3478,3203-3210` |
| 发版七门 | syntax_guard、kb compile --check、arch_scan --check（棘轮）、VQA 回归集、decision_check（0 ❌）、decision_propagation、定向 pytest（改动涉及 + smoke，xdist n=4，僵死 10 min 自愈退串行） | `system_version.py:205-290`；`config/pipeline/release.json` |
| 代选闸 | owner_delegate gate min_mean 30 / max_low_item 2 | `owner_delegate.json` gate |

---

## 5. 调度与并发参数

### 5.1 producer（`tools/autopilot/producer.py`）

| 参数 | 值 | 行 |
|---|---|---|
| TICK_S | 10 s | 108 |
| MAX_TRIES | 3 | 104 |
| HARD_CAP_DEFAULT | 30 / 24 h（retry.yaml hard_cap 同值） | 105 |
| GAZE_EXTRA_ROUNDS | 2 | 106 |
| STUCK_MIN | 10 min（ready 无派单路径 → stuck_object） | 107 |
| LEASE_S | 2700 s | 109 |
| INFRA_BACKOFF | (30, 60, 120, 300, 600) | 110 |
| PREFLIGHT_RETRY_S | 1800 | 111 |
| CODE_RETRY_S | 300 | 132 |
| WAIT_ASSET_MAX_S | 21600 | 630 |
| RESCORE_TIMEOUT_S / RESCORE_MAX / RESCORE_BACKOFF | 900 / 0（= post_pool 大小）/ (300,600,1200,1800,3600) | 114-116 |
| SCORE_CHAIN_COOL_S / SCORE_RETRY_S | 300 / 60 | 117-118 |
| RESCORE_HOURLY_MAX / RESCORE_CAP_BACKOFF_S | 3 / 1800 | 123-124 |
| CANARY_EXPIRE_S / MAX | 1800 / 14400 | 128-129 |
| ORPHAN_SCORE_S / ORPHAN_TAKE_S / ORPHAN_SWEEP_MAX | 120 / 600 / 20 | 1877-1888 |
| NIGHT_STALE_S | 1200 | 2426 |
| DRIFT_CONFIRM_TICKS / PID_GRACE_S / PID_HB_FRESH_S | 2 / 120 / 600 | 4826-4828 |
| prefetch_depth | 2（resources.yaml）；渲染超时 900×深度 | 528-552 |
| post_pool | max(6, 道数×深度)；L-206 下限 3×审图实例 | 563-580 |
| score_backlog_max | 启动 2×道×看图实例；之后 dynamic_backlog(最近 15 min 吞吐, 15 min 视野) | 555-561, 2603 |
| 线程池 | max(8, max(backlog,96) + 2×深度×道数) | 2606 |
| obj_per_hour | 8 | 3478 |
| adopt_best_effort_sweep | 每 120 s | 2898 |
| maybe_promote | 每 60 s | 2667 |
| 开关 | review_adopt_auto=true、fanout.enabled=false、canary.ignore_items [Q1]、accept.run_qb=false / skip_prefailed=true / max_rechecks 2 | `config/pipeline/producer.json` |

### 5.2 night / vidgen

| 参数 | 值 | 出处 |
|---|---|---|
| poll_s | V2 45 s（V1 120；night_control.poll_s 覆盖） | `night.py:959-967` |
| yield_s | 30 s（两台 night_control.json 实读 30） | `night.py:59-60`；服务器 `video/night_control.json` |
| per_lane | 2 | `night.py:60` |
| shared_lanes | 6 道全部（减 video_lanes / hold） | `night.py:59,64-67` |
| MAX_RENDERS / SEEDS | 4 / [s2,s3,s4] | `vidgen.py:68-69` |
| LANE_MAX_FRAMES / LONG_LANE | 260 / gpu36:2 | `vidgen.py:63-66` |
| 打分线程 | gpu33 3 / gpu36 2；NS_SCORE_THREADS 4 | `vidgen.py:464`；`score_clip.py:22` |
| UNDISPATCHABLE_GRACE_S | 1800 | `vidgen.py:236` |
| 打分子进程 timeout | 1500 s | `vidgen.py:839` |
| ASM 超时 | assemble 5400、proxies 1800、upscale 3600、finish 3600、report 1800、bgm 1800 | `night.py:601-681,794` |
| EP_SECONDS / SHOT_MAX_S / BGM_AUTO_MAX | 60–120 / 6.0 / 2 | `night.py:693-694,785` |
| vram_gate | night_control.video_boost.vram_gate {道: MiB}（默认关） | `night.py:867-874`；`vidgen.py:417-424` |

### 5.3 sop_gate / 资产 / 巡检 / 自愈

| 模块 | 参数 | 出处 |
|---|---|---|
| sop_gate | BACKOFF_S (900, 1800)、BACKOFF_KEEP_S 21600、STALE_BACKOFF_S 120、AUTO_PROBE_COOLDOWN_S 300、MIN_GAP 30、MAX_BACKOFF 3600、probe_timeout_s 900、probe_lane gpu36:0、LAST_TRIES 3、retro_parallel true、promote.auto true、lifecycle {apply true, hb_stale_min 5, grace_min 10, max_fails 3, health_max_age_min 15} | `sop_gate.py:455,670-716`；`sop_gate.json` |
| asset_worker | max_parallel 6、exclude [gpu33:2]、hold 15 min（续期）、job_timeout 90 min、max_attempts 2、ready_every_s 300、UNMEASURED_BACKOFF_S 300、candidates face 8 / scene 2 / sheet 3 / item 2 | `asset_worker.json`；`asset_worker.py:1248` |
| idle_watch | interval 60 s、idle_min 5、util_idle_pct 5、act_gap_s 600、restart_gap_s 1800、report_repeat_min 60、producer_stale 5 / night_stale 10 min、probe_timeout 40、queue_timeout 6、night_once_timeout 180；actions night_once / restart_request / report_issue / channel（+lane_relay 借道自动开 / 还 **[本地未入版]**） | `config/pipeline/idle_watch.json`；`idle_watch.py:49-55` |
| health_tick | apply=false（全局）、every_s 45、confirm_ticks 2、max_restarts_per_hour 3、backoff 60→900、idle_lane_min 5；分项 apply：stale_prompt→probe_stale、deploy_stale→restart_resident_sync / stop_start_lane_relay / flag_restart_autoflow（同 key 30 min 一次）；服务器 rq_restart 仍 dry | `config/master/health_tick.json`；`health_tick.py:39-52` |
| restart_queue | MODES producer-only / night-only / all；RESTART_MIN_GAP_S 1800（urgent 插队）；排空 DRAIN_FULL_S 60 / MAX 90 / POLL 10；先 pause（未被别人暂停时）→ drain → `resident_restart.sh` → resume | `restart_queue.py:52-88,140-188`；`resident_sync.py:872` |
| lifecycle（W18） | producer 心跳 >5 min 且本集阶段 ∈ {出图,出图检测,尾帧,视频} → 该集出图分区服务器 request_restart producer-only；阶段 ≥尾帧 → night all；起后 10 min 不重复；连续 3 次 P0 | `resident_sync.py:1108-1114,1253-1280` |
| lane_relay | max_inflight 2 / 道；反向隧道 5 s 重连 | `lane_relay.json`；`lane_relay.py:181` |
| episode_lock | TTL 600 s 滚动；asset_worker 见旗跳过 render | `tools/pipeline/episode_lock.py:2,28` |

### 5.4 L-206 / L-207 工位表（L-206 代码完成、在 cutAD 发版中；L-207 实现中）

契约文件 `config/pipeline/lane_roles.json`（未在 sv-20261106-07；已列入 `LIST_cutAD.txt:4`）：enabled=true、from_episode=2（ep01 不中途改调度）；

| 阶段 | image 出图位 | review 审图位 | video 视频位 |
|---|---|---|---|
| frames（本集有首 / 尾帧没定） | gpu33:0、gpu33:1、gpu36:0、gpu36:1（每卡只排 1 单：image_prefetch_depth=1） | gpu33:3（Qwen3-VL ×3 实例 8876–8878 + 人数 / 身份检测；视频打分看图也在此） | gpu36:2（首尾帧一对过检即开出） |
| videos（全部定下：passed / best_effort / na）**L-207** | —（出图位自动转视频位，一集每卡至多切换一次） | gpu33:3（缩到 **1** 个看图实例，vqa_instances_by_phase.videos=1） | **全部 6 道**：gpu33:0、gpu33:1、gpu33:3、gpu36:0、gpu36:1、gpu36:2 |

- 三段铁律（L-207）：首尾帧 → 全卡视频 → 合成 → 下一集首尾帧；审图位在视频阶段与 H3 同卡（看图 ~7.5 GB + H3 ~13 GB，`lane_roles.json` `_L207`）。实现工人 L207-PHASES，**实现中**：产物（night 视频阶段把 gpu33:3 纳入视频道、review_instances.sh 按阶段缩实例、SOP / CHECKLIST 改写）未入 cutAD。
- hold_regen_downstream=true：某镜首帧换代中（redo / regen / master_rejects 未 cleared）不派它的尾帧 / 视频。
- 状态文件 `data/pipeline/lane_roles_state.json`（nsfs.lane_roles_state/1，producer 每拍写，night / vidgen 读；没有则视频侧按 takes / registry 自算）。
- L-206 实现文件（已完成，在 cutAD）：`tools/autopilot/lane_roles_producer.py`（producer / idle_watch 读，`LIST_cutAD.txt:26`）、`tools/series10_video/lane_roles.py`（night / vidgen / score_clip / shard_relay / build_jobs 读，`:33`）、`tools/vqa/review_instances.sh`（审图位实例起停，`:39`）、`tools/previz/auto_blocking.py`（`:29`）、`tools/research/turbo_previz_ab.py`（`:30`）、`tests/test_l206_lane_roles_prod.py` / `_vid.py` / `test_l206_turbo_previz.py` / `test_previz_auto.py`（`:17-20`）；接线点见 `git diff` 的 producer.py / night.py / vidgen.py / vqa/client.py / score_clip.py / video_shard.py / shard_relay.py / build_jobs.py / accept.py / idle_watch.py / frame_job.py。`tools/autopilot/lane_roles.py` 是未入清单的同名旧稿（**审计时以 lane_roles_producer.py 为正本**）。
- ② ep02 起首帧 turbo_previz（§3.1，按集档位 `first_frame_tier.runs.series10_v2.from_episode`）；切换前用 `tools/research/turbo_previz_ab.py` 出 ep01 S1–S4 对照给项目方看。
- cutAD 同批两处修复：① `night.py:367-397` `HOLD_RESOLVE_S`=2700 s（env NS_HOLD_RESOLVE_S）+ `gate_hold_aged`：等闸门的镜要在 `video/_gate_hold_since.json` 连续记满 45 min 才按落定算——根因：ep01 视频阶段每来一镜就整集 finalize 一遍，finalize 同步阻塞 night 主循环 5–10 min，gpu36 三卡空转；② `asset_worker.py:903-906` 身份脸候选看图只核“一个人 / 成年 / 没有裸露 / 五官正常”，去掉“背景中性纯色 / 穿着日常”（与角色设定冲突，ep02 两张身份脸 15/15 被误判）。

---

## 6. 状态文件与单一来源

| 文件 | 写者 → 读者 | 关键字段 | 出处 |
|---|---|---|---|
| `data/renders/<run>/epNN/SK/takes.json` | `pipeline.mutate_takes`（锁 + seq + 备份 + last_op）；producer / 画布 / night / relay | `takes[]`（n、stage image/last/video、file、raw_file、seed、prompt、seconds、created_at、workflow、references、params{compile_trace, tier, previz, prompt_template, post, redo_fix_clause}、postflight{stage, subject, items[{id,status,detail,evidence,blocking,record_only,status_recorded}], contract_version, ok, blocking[], reasons[], measured_on, scored_from, vqa_gate, accept, record_only_items, code_sha, judged_pid, review_needed, review, first_last, gaze_waived}、producer{attempt, rung, lane, seed, tag}、master_reject）、`active{image,last,video}`、`seq`、`last_op`、`last_ops[]`、`master_gate{image|last}`（驳回闸）、**`last_frame_fallback{mode:"i2va", first_n, at, by, rule, why}`（顶层；first_n ≠ active.image 即失效）**、`locked_by` | 实读 `data/renders/series10_v2/ep01/S1/takes.json`；`producer.py:3009-3011`；`build_jobs.py:327-347` |
| producer 目录 `data/producer/[runs/<run>/]` | producer | `registry.json`（登记表，与 /api/render-tasks 共用）、`log.jsonl`（只追加事件：dispatch / rendered / passed / content_fail / redo_fail / best_effort / review_adopt / infra_error / sop_gate_block / adult_wait_owner / score_infra …）、`attempts.json`（账本：tries / final / redo_* / ladder_plan / gaze_rounds / last_pf_fails / last_frame_fallback / hard_capped / cap_extra / waiting_asset / backoff_until）、`master_rejects.json`、`heartbeat.json`、`control.json`（only / hold_lanes / paused / dispatch_by）、`leases/<对象>.json`（O_EXCL，过期 / 进程没了即失效）、`consistency.json`、`owner_triggers.json`、`import_token`。**registry.json 是否也按 run 分目录 [未核实]**（gpu33 run 目录下没列出 registry.json） | `producer.py:13-24,729-753`；gpu33 实读目录 |
| 视频 `data/pipeline/runs/<run>/video/` | build_jobs（笔记本）/ night / vidgen / shard_relay | `jobs.json`（每镜变体 + route / hold / first_frame）、`state_<host>.json`（shots{sid: {status, chosen, renders[{variant, seed, lane, t_sub, state, pid, score, gpu_s, first_frame}], force_queue}}）、`control_<host>.json`、`night_state.json`（eps{ep: {host, status, ready_shots, placeholder_shots, hard_rules, final, assembled_n, director}}, lane_mode, lane_key, lane_roles）、`night_control.json`（yield_s / hold_lanes / video_lanes / video_boost / bgm / poll_s）、`hosts.json`、`shard_claims.json`、`_shard_relay_status.json`、`clips/epNN/`、`inputs/`、`scores/`、`episodes/epNN/manifest.json`、`night.log` | `vidgen.py:3-16`；`night.py:53-56` |
| sop_gate | `data/pipeline/sop_gate/<run>/epNN_prompts.json`、`epNN_auto_probe.lock`、`backoff/<run>.<by>.json`、`violations.jsonl`、`auto_probe.log` | §2.5 | `sop_gate.py:252-256,693-697,756-760` |
| 资产 | `data/pipeline/asset_jobs/<run>/<job_id>.json`（nsfs.asset_job/1）、`_ready_epNN.json`（ready / gaps / shot_gaps / created / existing / closed）、`worker.lock`、`_sop_backoff.json` | §2.4 | `asset_jobs.py:32,73-77,685` |
| 分区 / 控制 | `config/netfix/partition.json`（→ `data/state/netfix/partition.json`）、`data/netfix/override_state.json`、`data/autopilot/ready_episodes.json`（partial 条目）、`data/producer/control.json`、`data/pipeline/lane_relay_hold.json`、`data/pipeline/episode_lock.json`、`data/autopilot/{video_hold,runaway_hold,lookA_hold,orphan_hold}.json`（K-OPS-I15：hold 必须带 expires_at） | §2.3 | `dispatch.py:34-38,271-276`；`health_tick.py` check_holds |
| L-206 / L-207 | `data/pipeline/lane_roles_state.json` **[cutAD 待发]**；`video/_gate_hold_since.json`（night 等闸门计时，`night.py:372`） | §5.4 | |
| 清单 | `assets_v2/manifest.json`（唯一参考来源，sha 核对）；派生图账本 `_derived_index.json` | I11 | `asset_refs.py:770-846,993` |
| 发版 | `data/system_versions/index.json`（nsfs.system_versions/1）、`release_request.json` / `release_result.json` / `release_lock.json`、`cut_lock.json`（TTL 45 min）、`deploy_<sv>_*.json`、`<sv>_pytest_<n>.txt`、`data/system_version.txt`（两台 + 本机） | §7 | `system_version.py:43-56,869-871` |
| 卡点 / 决策 | `data/pipeline/issues.jsonl`（report_issue）、`docs/master/MASTER_PICTURE.md`（决策账本）、`docs/master/CHANNEL.md`（agent 通道，格式 `MM-DD HH:MM | WHO | …`）、`docs/master/V2_LIVE.md`（实时页，新在上）、`config/owner_decisions.yaml`（机检） | | |
| 网络 | `data/netfix/net_status.json`、`rssh_calls.jsonl`、`puller_state.json` / `puller_status.json`、`fetch_queue.jsonl` | §1.2 | |
| 常驻 | `data/autopilot/resident_sync.json`、`relay_frames.json`、`run_sync.json`、`lifecycle.json`、`vqa_guard.json`、`restart_requests.jsonl` / `restart_done.jsonl`、`data/factory/autoflow_resident.{lock,json}`、`data/pipeline/idle_watch/status.json`、`data/master/health_tick*`（**[未核实]** 具体文件名） | §1.3 | |

---

## 7. 发版与运维

| 项 | 内容 | 出处 |
|---|---|---|
| cut | `system_version.py cut [--id sv] [--list LIST_cutX.txt]`：全局互斥（cut_lock TTL 45 min + cut.mutex）→ 预冻结等冻结目录 60 s 无改动（最多 10 min）→ 冻结树快照 → 七门对快照跑 → 提交冻结树 + tag → `push_remote`（密钥扫描命中不推 → `data/qa/alerts.jsonl`；推 `release/<sv>` + tag；`open_pr` 正文 = `docs/system_versions/<sv>.md`） | `system_version.py:1258-1300,1412-1452` |
| deploy | `deploy <sv> [--verify]`：`deploy_guard` → git archive 导出 CODE_DIRS（tools / services / packages / config / knowledge / ops）→ `deploy_host`（sha 核对、原字节 LF）→ 派单相关配置变了（hosts / lane_relay / sop_gate / gen_contract / producer / render_quality / run_style / video_shard）自动升 urgent 重启（只改配置 producer-only；改了代码 all，K-OPS-I11）→ `verify`（golden 镜 8 / series10_v2）→ 写 index + `data/system_version.txt`；verify 不过 = 部署不算完成 | `system_version.py:1828-1876`；`config/pipeline/release.json` verify_shot / hosts |
| release_tick（自动发版，L-190） | `data/system_versions/release_request.json`（nsfs.release_request/1：list 或 manifests、reviews G2–G7 “可入”、deploy、handover）→ resident_sync 每 60 s：拼树 → cut --dry → cut → deploy --verify → L-152 handover；同 sha 只跑一次；release_lock TTL 6 h；pytest_n 4、xdist_stall_min 10、cut_timeout 14400、deploy_timeout 10800、gates_on local | `tools/autopilot/release_tick.py:1-50`；`release.json` |
| 手工入口 | `ops/psmaster/cut_deploy_<X>.sh`（cutAA / AB / AC …，LIST 在 `docs/system_versions/LIST_cut*.txt`） | `ops/psmaster/` |
| 重启 | 服务器：`restart_queue.request(host, reason, by, urgent, mode)` → resident_sync 每拍 `process`（30 min 间隔，urgent 插队）→ pause → drain（60–90 s）→ `ops/offline/resident_prep.py` + `resident_restart.sh <host> <mode>` → resume；只停 `run/*.pid` 里命令行对得上的进程。笔记本：`ops/restart_resident_sync.ps1`、`ops/restart_autoflow.ps1`（写旗交 resident_guard）、`ops/restart_api.ps1`、`ops/autostart/restart_producer.ps1`；guard 计划任务 NS-Studio-ResidentSync-Guard / NS-Studio-Monitor-Guard（60 s 内拉起） | `restart_queue.py`；`resident_sync.py:419-427`；`health_tick.py:464-500`；`resident_restart.sh` |
| 互斥锁 | cut_lock / cut.mutex / release_lock；producer `leases/`（O_EXCL）；asset_worker `worker.lock`；autoflow_resident `.lock`；sop_gate `epNN_auto_probe.lock`（pid）；partition.lock（三方合并）；puller / tunnel_supervisor 单实例锁 | `system_version.py:869-876`；`producer.py:21`；`dispatch.py:431`；`tunnel_supervisor.py:801` |
| 冻结 | cut 期间 FROZEN_TOP（tools/ services/ packages/ config/ knowledge/ ops/ tests/ apps/）改动不进这一版；NS_FREEZE_EXEMPT=1 豁免 cut 自己 | `system_version.py:878,1288` |
| 回滚 | `system_version.py rollback <prev>` 只生成命令：`git diff --stat <sv> <prev>` → `git checkout <prev> -- .` → `deploy <prev>`；执行要总调度确认 | `system_version.py:17,854-858,1878` |
| 规则 | 改阈值先改 `knowledge/rules/*.yaml` 再改配置（K-REN-963 单一来源）；`tools/qa/decision_check.py` 跑 115 条断言（0 ❌） | `PIPELINE_SOP_V2.md` §V2 首帧生产配方；sv 文档 |

---

## 8. 已知问题与风险（截至 11-06 17:00 JST）

### 8.1 ep01 本轮实测（14:53 开跑，KPI ≤50 min）

数据来源：① 笔记本已并回的 `data/renders/series10_v2/ep01/S*/takes.json`（merge_pull 最后并回 15:43 + 后续 puller；取 created_at ≥ 14:50，`$TEMP/ns_takes_local.py` 本轮统计）；② gpu33 / gpu36 `data/producer/runs/series10_v2/log.jsonl`（rssh 只读，ts ≥ 14:50）；③ gpu36 `video/night.log`、两台 nvidia-smi（16:5x）。

| 指标 | 实测 | 说明 |
|---|---|---|
| 出图耗时 | 首帧 49 张：中位 **630.7 s**（min 351、max 1045）；尾帧 37 张：中位 624.8 s | takes.seconds = ComfyUI 排队+渲染（预取深度 2 → 一张等前一张，≈2×gpu_s）；gpu_s 本身 ~300–330 s（log `rendered` 行 gpu_s 299.6 / 326.8） |
| 判不过率 | 首帧 39/49 不过（**80%**）；尾帧 27/37 不过（73%） | 首帧阻断项：Q10 18、Q1 15、Q9 11、G1 3、Q6 1；尾帧：**FL 20**、Q1 13、Q10 4、Q9 2、G1 2、Q6 1 |
| gpu33 producer 事件（14:50–17:00） | dispatch 98、rendered 86、redo_fail 38、content_fail 24、best_effort 10、review_adopt 3、infra_error 9、sop_gate_block 7、master_reject 16、regen 16、last_void_reset 14、adult_wait_owner 21 | 440 行 |
| gpu36 producer | dispatch 2（只 ep02-S10）、adult_wait_owner 42、**score_infra 5：`ModuleNotFoundError("No module named 'torch'")`**（只重打分链路在 gpu36 上缺 torch，退避 3600 s） | gpu36 本机打分链路坏，ep02 首帧打不了分 |
| GPU 利用 | 16:5x gpu33 GPU0 92% / GPU1 100% / GPU3 35%；**gpu36 三卡 0%**（显存 19–20 GB 占着，模型空载） | gpu36 借道出图在 16:2x 后停（借道只给 ep01 首帧；ep02 卡资产），视频位无活 |
| 白跑 | S4 尾帧 v9–v14 六连 FL+Q1 不过（含一次 K-OPS-E11 “规则变了”自动重置再给 3 次，`best_effort_reset` 16:55:33）；S9 尾帧 v12–v19 八连 FL；S2 首帧 6 次（Q1 ×4、Q10 ×2）；S11 首帧 6 次、S14 / S15 首帧 5 次全不过 | 尾帧 compose 在推近类镜上 FL 高发（struct 阈值 0.80 对“推进一档”的落幅可能过严，`first_last.py` 校准只有 111 对） |
| S8 状态矛盾 | 登记表 last:ep01-S8 = best_effort 而账本 tries 0 / final None → 卡住不派；PS-MASTER 17:00 手工 `retry` 放回 | log `retry` 17:00:08；K-OPS-E11 重置与登记表推导不一致 |
| 合成 | gpu36 night 16:52 EP_RESOLVED（S5/S7/S8/S13 waiting_frame、S4 过期片）→ 16:56 assemble v？ 硬规矩 pass 但 **合成闸门 verdict=fail（缺镜 S4 / S5 …，静帧占位）**；`register_takes` 16:52 JSONDecodeError（某 takes.json 读到半写） | night.log |
| 看图 | 15:29–16:00 gpu36 看图排队 1 张 46–51 min 没结论（loaded=False，等 GPU1 ComfyUI 让显存）；W40 / SELF-HEAL 登记 ISS-1106-1529xx / 1544xx / 1554xx | V2_LIVE |
| 结论 | 开跑 127 min 时 16 镜首帧只有 S3 / S4 / S5 / S6 / S7 / S8 / S10 / S12 / S13 过（9/16，含 review_adopt），尾帧过 S2(adopt) / S3 / S4(v8 后被换) / S5(adopt) / S6 / S10 / S12 / S15；视频 done 仅沿用早先版本；**KPI 50 min 未达（>2.5×）**；归因候选：检测（Q10 / Q1 底噪、FL 阈值）、GPU 调度（gpu36 空转、预取 2 拉长单张等待）、逻辑（尾帧依赖首帧换版反复作废） |

### 8.2 代码 / 版本风险

| # | 风险 | 证据 |
|---|---|---|
| 1 | **L-206 代码（cutAD 待发）与 L-207 实现中代码并存于工作树**：producer / night / vidgen / vqa client / score_clip / shard_relay / video_shard / build_jobs / idle_watch / accept / frame_job 共 15 文件 +895/−393 行未提交（cutAD 按 blob 锁定 38 项，`LIST_cutAD.txt`）；`tools/autopilot/lane_roles.py`（旧稿，不在清单）与 `lane_roles_producer.py`（正本）并存；L207-PHASES 仍在改 night / lane_roles 相关文件，cut 冻结期间的改动会落到下一版 | `git status` / `git diff --stat`；`LIST_cutAD.txt` |
| 2 | **配置文件被运行期改写**：`config/netfix/partition.json`（retired_lanes / _temp_holds 由 asset_worker 改）与 `config/pipeline/owner_delegate.json`（到期时间）在 config/ 下却是状态文件；发版 diff 会把运行态带进版本 | `git diff config/netfix/partition.json` |
| 3 | REVIEW-SV 的 MINOR 项清单：CHANNEL 只记了 CRITICAL（尾帧 preflight 无限重试）已修（`CHANNEL.md:399`），**MINOR 清单未落盘，本文无法列出** | grep 全仓只命中 CHANNEL:399 |
| 4 | 测试顺序 / 并行依赖：`test_debug_rsi` e17 曾因 Producer 用 `object.__new__` 构造缺类属性而红（已加 `relay_lanes=frozenset()` 类默认，`producer.py:2558`）；`test_lane_relay default_off` 与 lane_relay.json enabled=true 冲突；`test_unified_frame` / `test_vqa_anomaly_regression` 在 `-n4` 并行偶发红、串行过；`tests/test_vqa*.py`、`test_netfix.py` 直接打本机 8870/8871 与隧道，隧道重建时必挂；FIX-ORCH 报 9 红为既有 tunnels.json（gpu36-vqa 键名指 gpu33）问题 | `CHANNEL.md:261,275,349,398`；`V2_LIVE.md:294`（历史） |
| 5 | 笔记本内存紧张：v2_live 实时页进程被内存回收（`CHANNEL.md:114`）；lens_sim D 档“因内存保护中止”（`:210`）；笔记本本机看图 OOM 把 ep02 素材验收堵 6 h（`vqa/client.py:255`）→ 现改 laptop_prefer_tunnel | 多处 |
| 6 | Fable 5 h 额度 12:20 用尽 → FIX-PRE-2 / PROD-2 / VID-2 / WRITER-P11-2 由 Opus 从半成品续做（`CHANNEL.md:391`）；同一文件两模型接力，需重点审 producer.py 3820–3870（尾帧 preflight）、2940–3020（void_reset / gaze_fallback）、night.py finalize | |
| 7 | gpu36 只重打分链路缺 torch（§8.1）→ 任何在 gpu36 本机需要 torch 的打分退回失败；`score_infra` 退避 3600 s 会让对象长时间不动 | gpu36 log |
| 8 | 两台 night 同时对 ep01 跑（gpu33 state 有 S3/S8/S13 blocked、gpu36 为 owner），分片 + 领取表 + L-206 三层规则叠加，容易出现“两台都不出 / 都出同一镜” | `state_gpu33.json` / `state_gpu36.json` 实读 |
| 9 | `data/producer/registry.json`（笔记本镜像）仍是 series10_v1 旧表；界面 / idle_watch 若读它会得到错误全局状态 | 本机实读 run=series10_v1 |
| 10 | 隧道 / 命令主连接不稳：17:00 前后 rssh 多次 rc 255（Connection closed）；SELF-HEAL 16:31 “gpu33 健康记录 16 分钟没更新”、16:49 隧道口不通 | `V2_LIVE.md` 顶部；本轮 rssh |
| 11 | 未入版文件清单（`git status ??`）：`config/pipeline/lane_roles.json`、`tools/autopilot/lane_roles.py`、`tools/autopilot/lane_roles_producer.py`、`tools/series10_video/lane_roles.py`、`tools/previz/auto_blocking.py`、`tools/research/{turbo_previz_ab,hybrid_ab,lens_sim_ab,look_v2_ab,cfg_batch_ab,adherence_img_ab,writer_lite_ab}.py`、`tools/vidlab/adherence_video.py`、`tools/script_lite/`、`tests/test_previz_auto.py`、`tests/test_l206_*.py`、`docs/overnight/morning_20261106.md`、`docs/master/handover/vqa_client_route_CODER-PS.patch`、多份 `*.bak_*`；已跟踪但改了未提交：`config/render_quality.json`（first_frame_tier turbo_previz）、`services/api/ns_api/pipeline_status.py`（670 行重写）等 28 文件 | `git status --short` |

---

## 9. 审计指引（给外部模型）

### 9.1 最容易出死路的地方

1. **登记表 ↔ 账本不变量**（`producer.derive` / `_frame_obj` / `escalate_exhausted` / `void_reset` / `cap_exhaust` / `gaze_fallback`）：status best_effort 而 tries=0、`redo_exhausted` 与 `final` 不一致、`last_frame_fallback.first_n ≠ active.image`、`master_rejects` 未 cleared 但对象已 passed。11-06 S8 即此类（§8.1）。建议对 `attempts.json` × `registry.json` × takes.json 写一致性检查（已有 `consistency.json` 自检 `producer.py:388`）。
2. **退避 / 重试计次口径**：哪些错误 counted=false（code / infra / preflight 等资产）、哪些计次（content）；`PREFLIGHT_RETRY_S` 1800 vs 尾帧 preflight 60 s ×3；`hard_cap` 只看 24 h takes 数，不随重置清零；`obj_rate_exceeded` 8/h 与 3 次 × 2 轮 gaze 加轮的交互。
3. **尾帧依赖链**：首帧换版 → 尾帧 void → 视频过期片 drop_stale → 合成占位；FL 阈值固定 0.80 / 0.85 对推近镜是否过严（S4 / S9 连续 FL）。
4. **看图单点**：Q9 untested = 不通过（failed closed），看图排队 / OOM / 隧道断直接让整条出图线停在“等看图”；`busy_wait_s 600` + `wait_s 900` 的组合延迟。
5. **分片 + 领取 + L-206 三套道规则**同时作用于 night_control / control_<host> / jobs.json route；检查 `roles_control`、`decide_claims`、`role_claims` 的优先级与互斥。
6. **跨进程契约**：takes.json 只能经 `mutate_takes`（A-04）；两台 producer 各自只合并自己推出的集到 lane_roles_state；relay `merge_takes` 保留目标机 active.video；`ready_episodes.json` partial 条目只增不减。
7. **sop_gate 证据过期循环**：导入 / 清单改 → 证据过期 → auto probe（900 s 超时）→ 退避 → producer `sop_gate_block`；probe 锁按 pid；两台各自探（episode_run 要求两台都过）。
8. **Windows / Linux 差异**：路径分隔（`RP.shot_take_rel_dir`、`rel()`）；CRLF（服务器文件必须 LF，`export_tag` 注释）；`.venv/Scripts/python.exe` 在服务器是 shim（`resident_restart.sh:28`）；WSL 调用 `wsl.exe` 会二次展开 `$VAR`、MSYS 转换 `/mnt/c`（K-OPS-I09）；PowerShell 给项目方、不给带 `$_` 的 Git Bash 一行命令（K-OPS-I14）。
9. **时区**：笔记本美东、服务器 America/New_York、项目 JST；`dispatch.iso()` 自己 +9 h；`system_version` ENV TZ=JST-9；takes.json created_at 带 +09:00；比较时间戳前统一 `ts_epoch`。
10. **失败关闭 vs 失败开放**：arch_scan `silent_read` 度量专门抓“try 读文件 except 返回常量”；审计每个 `# arch-ok:` 注释是否真的安全（例如 lane_roles 读不到 = 旧行为、hosts.json 读不到 = 只去掉坏卡）。
11. **成人镜**：`adult_wait_owner` 永远等项目方；sop_gate 把它当“不算阻断”，但 build_jobs / night 的“本集只有成人镜”分支（night.log 16:36）要确认不会把整集判成就绪或永远 pending。

### 9.2 离线复现

- 全量离线编译 + preflight（不占 GPU）：`.venv/Scripts/python.exe -X utf8 tools/master/sop_gate.py probe-prompts --run series10_v2 --episode 1`（走 `compile_preflight` 隔离子进程；写 `data/pipeline/sop_gate/series10_v2/ep01_prompts.json`）；单镜编译看提示词：`tools/research/turbo_previz_ab.py dry`（build_first + previz + 图 + preflight，不碰 GPU）；写作校验：`tools/validate_qwen_script.py <P4.md> --json`；rubric：`tools/script_rsi/rubric_code.py` / `staging.py`。
- 单测：`.venv/Scripts/python.exe -m pytest -q -rf -p no:cacheprovider [-n 4] <files>`（发版用同一命令，`system_version.py:245`）；建议先串行（§8.2 #4）；TZ=JST-9；相关集合：`tests/test_l204_fix_prod.py`（23）、`tests/test_l205_perf.py`（11）、`tests/test_fix_orch_1106.py`（17）、`tests/test_video_fixvid2.py`、`tests/test_health_tick.py`、`tests/test_sop_gate.py`、`tests/test_producer_w44.py`、`tests/test_l203_frame_pair_lint.py`、`tests/test_l201_*`、`tests/test_l206_*`（未入版）。
- 结构闸门：`tools/qa/arch_scan.py --check`（基线 `data/sysarch/baseline.json`，度量 no_timeout / direct_ssh / silent_read / nonatomic_json / untracked_code / hard_path …）；`tools/qa/syntax_guard.py --dry`；`tools/qa/decision_check.py`；`tools/qa/decision_propagation.py --dry`。
- 干跑 producer：`producer.py dryrun`（FakeFrameExec，不碰 GPU，`producer.py:2385-2413`）；`restart_queue` / `lifecycle --dry`；`idle_watch.py once --dry-run`；`health_tick.py`（apply=false 只报）。
- 只读看线上：`tools/netfix/rssh.run(host, cmd)`；服务器日志 `data/producer/runs/series10_v2/log.jsonl`、`data/pipeline/runs/series10_v2/video/night.log`、`vidgen_<host>.log`；本机 `docs/master/V2_LIVE.md`（新在上）、`data/pipeline/idle_watch/status.json`。

---

## 附：本轮读过的源文件

配置：`config/gen_contract.json`、`docs/system_versions/LIST_cutAD.txt`、`tools/vqa/review_instances.sh`（只确认存在）、`config/render_quality.json`、`config/compile/run_style.json`、`config/compile/bible_series10_v2.toml`、`config/director/lenses.yaml`、`config/director/camera_moves.yaml`、`config/director/shot_spec_v2.yaml`、`config/director/lighting.yaml`、`config/vqa.json`、`config/pipeline/producer.json`、`config/pipeline/sop_gate.json`、`config/pipeline/asset_worker.json`、`config/pipeline/lane_roles.json`、`config/pipeline/lane_relay.json`、`config/pipeline/video_shard.json`、`config/pipeline/idle_watch.json`、`config/pipeline/runs.json`、`config/pipeline/episode_run.json`、`config/pipeline/score_resident.json`、`config/pipeline/owner_delegate.json`、`config/pipeline/release.json`、`config/pipeline/video_policy.json`、`config/master/health_tick.json`、`config/netfix/partition.json`、`config/netfix/tunnels.json`、`config/factory/hosts.json`、`config/policies/retry.yaml`、`config/policies/resources.yaml`、`config/policies/sentinel.yaml`、`config/post/director.json`、`config/bgm.json`、`config/voices.json`、`config/owner_decisions.yaml`。

文档：`docs/master/MASTER_PICTURE.md`、`PIPELINE_CHECKLIST.md`、`PIPELINE_SOP_V2.md`、`EP01_FRAME_PAIRS.md`、`CHANNEL.md`、`V2_LIVE.md`、`RETRO_ep01.md`、`docs/system_versions/INDEX.md`、`sv-20261106-07.md`、`LIST_cutAC.txt`、`docs/overnight/morning_20261106.md`、`ops/autostart/README.md`、`ops/autostart/laptop_autostart.ps1`、`ops/offline/resident_restart.sh`。

代码：`tools/autopilot/{producer,resident_sync,idle_watch,episode_pipeline,lane_relay,restart_queue,lane_roles,lane_roles_producer,release_tick}.py`、`tools/master/{sop_gate,health_tick,episode_checklist,episode_run}.py`、`services/agent/ns_agent/{compiler,frame_job,asset_refs,framing,prompt_template_v2,video_mode}.py`、`services/agent/ns_agent/gen_contract/{blocking,postflight,preflight,first_last,accept}.py`、`services/agent/ns_agent/vqa/{contract,client}.py`、`packages/schema/ns_schema/{prompt_v2,h3_lint}.py`、`packages/qc/ns_qc/{face,gaze}.py`、`services/render_router/ns_render/{unified_frame,pipeline,h3_video,workflows,seed_stream,lens_sim_v2}.py`、`services/post/ns_post/{assemble,tts}.py`、`tools/series10_video/{night,vidgen,build_jobs,shard_relay,video_shard,score_clip,episode_report,lane_roles,upscale_preview}.py`、`tools/assemble_episode.py`、`tools/director/finish.py`、`tools/pipeline/{asset_worker,asset_jobs,episode_lock}.py`、`tools/netfix/{rssh,dispatch,puller,tunnel_supervisor}.py`、`tools/qa/{system_version,writer_lints,arch_scan}.py`、`tools/validate_qwen_script.py`、`tools/script_rsi/{rubric_code,staging}.py`、`tools/factory/autoflow_resident.py`、`tools/vqa/{accept,anomaly,anomaly_server,vqa_router,server}.py`、`tools/gen_contract/{score_srv,remote_score}.py`、`tools/series10_imggen/score_remote.py`、`tools/identity_metric.py`、`tools/previz/auto_blocking.py`、`tools/research/turbo_previz_ab.py`、`tools/bgm/bgm_library.py`、`tools/dejudder.py`。

实测数据：`data/renders/series10_v2/ep01/S*/takes.json`、`data/pipeline/runs/series10_v2/video/{night_state,state_gpu33,state_gpu36}.json`、`data/pipeline/sop_gate/series10_v2/ep01_prompts.json`、`data/pipeline/asset_jobs/series10_v2/_ready_ep0{1,2}.json`、`data/pipeline/idle_watch/status.json`、`data/producer/registry.json`、`data/netfix/net_status.json`、`data/autopilot/resident_sync.json`、`data/pipeline/runs/series10_v2/metrics/ep01_summary.json`、`data/system_versions/sv-20261106-07_pytest_2.txt`；gpu33 / gpu36 经 rssh 只读：`data/system_version.txt`、`data/producer/runs/series10_v2/log.jsonl`、`video/night.log`、`video/night_control.json`、`data/producer/runs/series10_v2/control.json`、`nvidia-smi`。
