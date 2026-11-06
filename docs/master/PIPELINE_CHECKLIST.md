# 一集生产清单（唯一 todo + checklist）——L-206 / L-207 三段流水

项目方原话（11-05 22:0x）：“逻辑很不清晰，你基于整个 pipeline 建立一条 todo 和 check list，不在里面的不做，超时的立马重来，保持连接，你思考怎么稳定和快的问题和方案。”
项目方原话（11-06 L-206）：“出图和审图是不是分开来做？一个 gpu 专门出图，另一个 gpu 审图，load 模型也省很多时间。”
项目方原话（11-06 L-207）：“首尾帧一旦做完，下一步就是全部显卡做视频，这个 gpu 调度你做好，新的 sop pipeline 你按照这个逻辑来。”
KPI（L-205）：一集 ≤ 50 分钟（单段视频 ≈ 5 分钟）；每步超预算要归因（逻辑 / 代码 / GPU 调度 / 检测）并当轮修进代码。

## 规则
1. **一集在跑时，GPU 只做这张清单上的事**。资产候选、A/B、研究、别集都不许占卡；清单外的任务等这一集结束再排（资产作业见 C1：审图位永不借、视频段一条不借）。
2. **一集严格三段，按集排队（L-207）**：① 首尾帧段 → ② 全卡视频段 → ③ 合成（CPU）→ 下一集 ① 。下一集的首尾帧**只在**本集视频全部定下后开始（合成可以和下一集首尾帧重叠）。一条道一段只装一种模型，一集内每卡至多切换一次（出图 → 视频）。
3. **每一步有完成标准和超时**。超时就立刻重做（换道或换种子）；同一步重做 2 次仍不行，记卡点并跳到兜底（例如自动采用最好的一版），不让整集停下。
4. **一个排序源**：`data/pipeline/lane_roles_state.json` `<run>._active = {ep, phase}`（producer 每拍写；粘性：占卡的集没到合成不换）。出图调度（producer）、视频调度（night / vidgen）、空卡巡检（idle_watch）、资产工人（asset_worker）都只读它和 `config/pipeline/lane_roles.json`，不各自判断。
5. **保持连接**：笔记本到两台服务器用常驻 SSH 主连接，断了自动重连；所有远程命令走它（tools/netfix/rssh）。
6. **每步写一行状态**（开始、结束、用时、重做次数），供瀑布图和复盘。

## 三段分卡表（config/pipeline/lane_roles.json 单一来源；坏卡 gpu33:2 永不出现）

| 段 | 出图位（image） | 审图位（review） | 视频位（video） | 看图实例（gpu33:3） | 资产作业可借 |
|---|---|---|---|---|---|
| ① 首尾帧 frames | gpu33:0 gpu33:1 gpu36:0 gpu36:1（每卡只排 1 单） | gpu33:3（Qwen3-VL ×3 + 人数 / 身份检测） | gpu36:2（首尾帧一对过检即开出） | 3 | 只借 4 张出图位 |
| ② 视频 videos | —（出图位全部转视频位） | gpu33:3（缩到 1 个实例，供视频打分） | **全部 6 张**：gpu33:0 gpu33:1 gpu33:3 gpu36:0 gpu36:1 gpu36:2 | 1 | 一条不借（等） |
| ③ 合成 assembly | —（CPU：night finalize / assemble_episode） | 下一集 ① 起 → 3 | 下一集 ① 起 → gpu36:2 | 3 | 下一集 ① 的规则 |

- gpu33:3 视频段：ComfyUI :8191 带 `--reserve-vram 9`（给 1 个看图实例 ≈ 7.5 GB 留显存），H3 ≈ 13 GB 同卡；分片排除表（video_shard.json exclude_lanes）在视频段对它让位（night `_shard_hold`）。
- 阶段切换（① → ②、③ → 下一集 ①）由 producer 的钩子自动跑 `bash tools/vqa/review_instances.sh scale N`（N = review.vqa_instances_by_phase[phase]：3 / 1），后台线程 + 超时 + 幂等，结果在 `data/pipeline/review_scale.json`；失败只记日志，调度照用活着的实例（分发器 :8870 按 /health 挑）。
- 视频打分（score_clip V9 看图）只去审图位：gpu33 上 → 127.0.0.1:8870；gpu36 上 → 10.0.0.33:8870（gpu33 审图位内网入口 `tools/netfix/review_lan_proxy.sh`，只听 10.0.0.33、只认 10.0.0.36；resident_sync 每拍保活；开关 review.lan_proxy.enabled）。
- 段的判定（C2 兜底，防止卡在 ①）：本集非成人镜首尾帧全定下 → ②；或 ≥1 镜定下且没有 ready / running 的首尾帧（其余在等资产 / 导入 / 卡死）→ ②；或定下数 20 分钟没变且没有在跑 → ②。卡住的镜之后就绪 → 回切 ①（计次、记日志）。成人镜不计、不挡切段。

## 清单（目标用时按 6×3090，L-206 / L-207 三段；每集总预算 ≤ 50 min）

| # | 段 | 步骤 | 输入 → 输出 | 完成标准 | 目标 | 超时 → 动作 |
|---|---|---|---|---|---|---|
| 1 | 准备 | 导入分镜 + 首尾帧设想（L-203） | staging P4 → 导入稿 | validate block 0，导入稿 sha 写入，首尾两帧设想 ≥2 项不同 | ≤ 1 min | 2 min → 重跑 1 次，仍失败记卡点（分镜问题） |
| 2 | 准备 | 同步到出图机 | 导入稿 → gpu33 / gpu36 | 两边 sha 一致 | ≤ 30 s | 90 s → 直接推送（不等同步循环） |
| 3 | 准备 | 提示词检查（逐镜，L-195） | 导入稿 → 每镜编译 + preflight 证据 | 每镜 ok；不 ok 的镜单独卡住，其余继续 | ≤ 1 min | 3 min → 重跑 |
| 4 | ① | 首帧（逐镜，4 张出图位，每卡 1 单） | 每镜 → 1 张定稿首帧 | 硬闸过（身份 / 人数 / 无字 / 成人安全 / 视线排排站） | 每张 ≤ 2× 预计（turbo 60 s / base35 330 s）；整集 ≤ 10 min（8 步）/ ≤ 20 min（35 步） | 单张超时 → 取消换道重出；硬闸不过 → 换种子；3 次后自动采用最高分版（L-204） |
| 5 | ① | 尾帧（逐镜，按落幅单独构图，L-203） | 首帧定稿 → 1 张尾帧 | 硬闸过 + 首尾不太像（FL） | 整集 ≤ 8 min（与首帧交错，同 4 张出图位） | 同上；首帧换代中不派它的尾帧（hold_regen_downstream） |
| 6 | ① | 审图（gpu33:3，3 实例） | 每张图 → 契约结论 | 结论落账本，不出“未测” | 每张 ≤ 40 s；排队 ≤ 2× 道数 × 实例 | 连续 4 轮没结论 → 看图退旧路由（review_fallback）；实例全不在 → 卡点 |
| 7 | ①→② | 切段 | 本集首尾帧全定下（或 C2 兜底） | `_active.phase = videos`；scale 1 成功或记日志 | ≤ 2 min（卸出图模型 + 停 2 实例） | scale 失败 → 用活着的实例，记 review_scale rc；不挡视频 |
| 8 | ② | 视频（逐镜，6 张卡全出，FL2VA / I2VA） | 首尾帧 → 片段 | 片段存在、时长对、无黑帧、打分过 | 每段 ≤ 2× 预计（≈ 5 min → 上限 10 min）；整集 16 镜 ≤ 15 min | 单段超时 → 取消换道重出 1 次；仍失败用上一个可用片段或静帧推镜兜底并记卡点 |
| 9 | ② | 视频打分（gpu33:3 的 1 个看图实例） | 片段 → V9 / 身份结论 | 结论落 state | 每段 ≤ 60 s | 审图位不可达 → 未测不判 fail；gpu36 走 10.0.0.33:8870 不通 → 卡点（review_lan_proxy） |
| 10 | ②→③ | 切段 + 下一集 ① 起 | 本集视频全定下 | `_active` 换到下一集 frames；scale 3 | ≤ 2 min | scale 失败 → 用活着的实例（看图慢但不停），记日志 |
| 11 | ③ | 合成成片（CPU，与下一集 ① 重叠） | 全部片段 → 成片 | 成片存在、时长 60–120 s | ≤ 8 min | 20 min → 重跑合成；等闸门的镜 15 min 才按落定（HOLD_RESOLVE_S） |
| 12 | ③ | 拉回 + 对比页 | 成片 → 本机 + 网页 | 大小一致、页面可开 | ≤ 3 min | 10 min → 重传 |
| 13 | ③ | 复盘数据 | 各步状态 → 瀑布图 + 逐步耗时表（L-205） | 页面生成；超预算步骤归因四类之一 | ≤ 1 min | 不挡成片 |

预算合计（8 步 turbo）：准备 ≈ 3 min + ① ≈ 20 min + 切段 2 min + ② ≈ 17 min + 切段 2 min + ③（与下一集重叠）≈ 12 min → 本集占卡 ≈ 44 min，≤ 50 min。35 步 base 的集 ① 另加 ≈ 10 min，需从 ② 的并行里省回来（6 张卡全出视频）。

## 两集之间 PS-MASTER 要做的事（发版后生效）
1. gpu33：`bash tools/vqa/review_instances.sh start --replace`（起 3 实例 + 分发器）；`bash tools/netfix/review_lan_proxy.sh`（审图位内网入口；之后 resident_sync 自动保活）。
2. gpu33:3 的 ComfyUI :8191 必须带 `--reserve-vram 9`（已是现状）；视频段不再手工 hold 它。
3. 两台 night / vidgen、shard_relay 重启一次读新代码；producer 重启后第一拍写 `_active`。
4. `config/pipeline/video_shard.json` 给要跑的集配 owner / weights（没配 = 整集一台出视频，用不满 6 张卡）。
5. 看 `python tools/autopilot/lane_roles_producer.py status`：`_active`、各集 stage、review_scale 的 rc；scale 失败就手工 `review_instances.sh scale N`。

## 稳定性（怎么不卡）
- 清单外不占卡 → 不会出现“首帧在排、视频让道”这类互相等。
- 任何“暂停 / 不接活”都必须带到期时间；清单执行期间，非本集的 hold 一律无效。
- 部署只在两集之间做；集内不重启执行器。
- 超时即重做，不等人；重做有上限，到上限走兜底，不停整集。
- 健康巡检（每 60 s）：执行器心跳、各道 /queue、隧道、看图 / 打分服务；挂了自动拉起并记一行。
- 空卡巡检（L-202）按段看角色：视频段 6 张卡都算视频道；下一集的 ready 首尾帧不算“有活”（按序等）。

## 快（怎么到 ≤ 50 分钟一集）
- 首帧 8 步 + 摆位控构图（L-197 B / L-206 ②），身份稳 → 少重出。
- 一卡一模型、一集内每卡至多切一次 → 不反复 load 模型（L-206）。
- 首尾帧全定下后 6 张卡全出视频（L-207），视频段看图缩到 1 实例给视频模型让显存。
- 合成是 CPU，和下一集首尾帧重叠。
- 视频生成长度按剪后用量（约 5 s → 用多少出多少）。

## 执法实现（CHECKLIST 11-05，tools/master/episode_checklist.py；L-206 / L-207 分卡：tools/autopilot/lane_roles_producer.py + tools/series10_video/lane_roles.py）
- 任务表：data/pipeline/runs/<run>/episode_run/epNN_tasks.json（每步一行 + 首帧 / 尾帧 / 视频逐镜一行：status / lane / started / ended / secs / attempts / timeout_s）；epNN_report.md 末尾有“清单与耗时”表；动作日志 epNN_events.log（`MM-DD HH:MM(JST) | CHECKLIST | ACT/FALLBACK/LOCK/CONN | …`）。
- 分段：producer `lane_roles_tick` 每拍推 phases / stages / `_active` → `data/pipeline/lane_roles_state.json`；`lanes_allowed` 只给 active 集的 frames 段出图位；night `roles_for_host` 按 `_active` 写 control（video_lanes / hold_lanes）；vidgen 只派 lane_roles.video 道；idle_watch `lane_roles_map(active=…)`；asset_worker `lane_roles_policy`。
- 清单外不做：episode_run 每拍写 data/pipeline/episode_lock.json（TTL 600 s 滚动，episode_run 停了自失效）；asset_worker 见旗标跳过 render；A/B / 研究工具提交 GPU 前须调 tools/pipeline/episode_lock.active(root)。
- 超时即重做：首帧单张 > 2×预计（base35 330 s / turbo 60 s，读 config/render_quality.json）→ producer retry；3 次后 review-adopt 最高分版。视频单段 > 900 s 或首尾帧定稿后 120 s 未派 → night --once；2 次仍不行 → 记卡点兜底；night 状态 > 900 s 没更新 → 紧急 night-only 重启请求（每集一次）。
- 保持连接（已核实）：tools/netfix/rssh 走 WSL OpenSSH 常驻主连接（ControlMaster，tunnel_supervisor 托管、断了自动重连）；run_retry 对 rc=255 / 超时按 10 s×n 退避重试；episode_run 的远程调用全走 run_retry。每拍巡检 net_status.json，某台没有 up 的主连接就记一行 CONN。
