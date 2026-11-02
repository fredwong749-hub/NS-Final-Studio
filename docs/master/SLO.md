# 系统 SLO 与主动探测（总调度 fredw-2b，11-02 02:3x，L-103）

> 项目方 02:3x：“每次都是我指出来你才去修……这不是 RSI……你还没有具备 fully autopilot 的能力。”
> 原则：问题必须由系统自己先发现。每条 SLO 都配一个自动探针；违约时自动开工单（data/sentinel/issues.jsonl）并派给负责 loop。项目方先于系统发现的问题，一律记一条“探针缺口”，并补上探针。

| # | SLO | 目标 | 探针 | 违约后派给 |
|---|---|---|---|---|
| S1 | 每条出图道 GPU 利用率（滚动 30 分钟，/history 执行时间并集） | ≥ 0.8 | lane_util | DEBUG-RSI |
| S2 | 每台服务器有 ready 单时，GPU 不能全空 | 连续 3 分钟全 0% 即违约 | nvidia-smi + producer 登记表 | DEBUG-RSI |
| S3 | 打分 p50（出图完成 → 契约结论） | ≤ 120 s | producer log | VQAGATE |
| S4 | 连接：底座或内层断开后恢复时间 | ≤ 30 s；跳板新建连接 < 50 次/小时 | net_status + relay_rate | NETFIX |
| S5 | 发版：cut 成功率；服务器代码版本 = 最新 sv | cut 一次通过；版本差 ≤ 1 | last_cut.json + system_version.txt | FACTORY |
| S6 | 服务器配置和笔记本一致（refs、覆盖配置、vqa.json 等） | 0 差异 | sync verify | FACTORY |
| S7 | 暂停：无主暂停时长 | ≤ 180 s | policy.pause_decision | DEBUG-RSI |
| S8 | 内容：过契约首帧的看镜头率、身份失败率、缺件率（本地 VLM 抽检） | 看镜头 0、身份 0、缺件 0 | VLM 抽检每小时 10 张 | VQAGATE / IMGFIX |
| S9 | 界面：彩色元素数、旧图 / 裂图、口径矛盾（截图 + 规则检查） | 状态色只有圆点；裂图 0；矛盾 0 | 无头截图 + DOM 规则 | UIRSI |
| S10 | 决策与规则：decision_check / propagation / compile | 0 ❌ | 每拍 | 规则 owner |
| S11 | 编排器：每集卡在同一段的时长 | 同段 > 2 小时无进展即违约 | flow status | DISTILL |
| S12 | 剧本：代码判定失败项、尺子标准差 | 新稿 0 失败；σ ≤ 1 | rubric_code / ruler | HOLLYWOOD |
| S15 | 编排器 tick 存活：data/autopilot/flow/last_tick.json | ≤ 5 分钟更新且 dry=false | tick 文件（总调度 04:2x） | WORKFLOW |
| S16 | 笔记本常驻进程清单（tunnel_supervisor / puller / ns_api / vite / producer / infra_watchdog / resident_sync / episode_pipeline / 8810 看板 / 4080 看图） | 缺 0 | 进程命令行（清单在 sentinel.yaml S16_laptop_procs；L-103 缺口：resident_sync 没在跑无人发现） | 各进程负责方 |
| S17 | 单镜出图速率 | 同一镜每小时 ≤ 8 次 | producer rendered（笔记本 + 服务器；ep05-S3 重出到第 82 版的缺口） | DEBUG-RSI |
| S18 | 临时挂道到期（partition.json _temp_holds） | 不过 expires_at；没写 expires_at ≤ 15 分钟 | partition.json（gpu36:0 挂 3.5 小时的缺口） | 挂道的 loop |
| S19 | 产能见底：所有 run 的可派 ready（只算 runs.json 里 status=producing 的 run；已导入但 run 不是 producing 的 ready 单列、不算可派）合计 vs 道数 × 2，每台 vs 本机道数 × 2（单里写哪台见底、另一台还剩多少）；有没有下一批（待导入的稿 / 导入了没放单） | 可派 ready ≥ 10、每台 ≥ 本机道数 × 2，或有待导入的稿 | 两台服务器登记表 ready + autoflow.json verdict=importable + imports.jsonl（11:01 gpu33 空 30 分钟的缺口） | 总调度 / DEBUG-RSI |
| G26 | 声明 vs 实际：config/factory/hosts.json 里每条 enabled 的道——ComfyUI 端口有进程在听、system_stats 正常、监听进程跑在声明的 GPU 上（--cuda-device / CUDA_VISIBLE_DEVICES / nvidia-smi 计算进程）；broken_gpus（gpu33:2）上没有任何作业 | 0 不符 | 服务器本机实测（remote_probe 同一次调用）；sv-09 部署后自动上线 | DEBUG-RSI（运行期）/ FACTORY（声明错） |
| S20 | 笔记本上命令行在 scratchpad 路径下、还在运行的 python / sh 进程（K-OPS-Y04：会改生产状态的代码不许从 scratchpad 跑） | 0 | 进程命令行（Windows 拿不到工作目录，只看命令行）；lend_any.py / hold_lane.py / lend_lane.sh 标“已知，sv-10 收编”；只读豁免（sentinel.yaml readonly_exempt，总调度认领、命令行里没有 ssh）：watch_green.sh | 按脚本名的负责方，判断不出派总调度 |
| S20+ | 会话 shell（Git Bash / sh / pwsh / powershell）活了 > 2 小时、30 分钟内在它下面新起 ssh ≥ 3 次 = 永不结束的 ssh 轮询 | 0 | SENTINEL 每拍进程快照（新 ssh 的父 / 祖父 shell）∪ NETFIX ssh_spawn_watch.ps1 记录（VQAGATE 凌晨两个轮询让跳板新建连接维持 108 次/小时） | 起它的 loop，看不出派总调度 |
| S21 | 读旧状态路径：data/state/legacy_reads.jsonl 24 小时内的 state_legacy_read（netfix/partition、netfix/override、pipeline/runs、pipeline/run） | 0（sv-11 删旧读的前提） | state_paths.read_state 读旧位置时记的日志；负责方按 caller 查 ownership.yaml | 调用方负责方 |
| S22 | 冻结期间改文件：data/rsi/freeze_drift.jsonl（{sv, at, files}） | 0；之后成功 cut 自动关 | FACTORY cut 记录 | 文件负责方 |
| S23 | 笔记本侧出图道可达率：每拍测本地隧道端口 /system_stats（gpu33:0/1/3、gpu36:0/1；gpu36:2 按 L-100 退役不计） | 每道 5 分钟可达率 ≥ 80%；同一拍不通的道 < 半数 | 笔记本本机实测（13:07–13:21 隧道来回重连、6 道全拒连，S2 / G26 只测服务器本机端口没报）；与 NETFIX A-TUNNEL-FLAP 互为备份 | NETFIX |
| S24 | API 响应时间：/api/episodes、/api/season 每分钟测一次（带只读查看令牌） | 最近 20 次 p95 < 2 s（失败按 30 s 计） | 笔记本本机实测（今天 /api/season 一度 6–25 s、页面卡在加载） | UIRSI2 |
| S25 | 常驻 CLIP（两台 :8872）：pid 文件对应进程活着；clip_resident_events.jsonl 里 exit_rc_3 一小时 ≤ 3 次；/health 超时给 30 s（单线程忙时会慢，只记证据不算挂） | 进程在、重载 ≤ 3 次/小时 | 服务器本机（单独一次 rssh，5 分钟一次） | FACTORY |
| S13 | 等人决定：任何对象等总调度 / 项目方定；流水线断档（GPU 空、ready 0、pending 多） | 等人 ≤ 10 分钟；断档 0 | 登记表 waiting_for + nvidia-smi（总调度 02:4x 追加：02:22 gpu33 全 0% 根因 = 77 个首帧“等总调度定”） | DEBUG-RSI |

探针实现：tools/sentinel/（K-OPS-S02…S07；阈值 config/policies/sentinel.yaml）；工单 data/sentinel/issues.jsonl，未关闭快照 data/sentinel/open.json，看板 :8810“工单”区。

总调度每拍只做三件事：看工单 → 按 G0 派单 → 核对上一批工单是否真的关闭（看探针数据，不看报告）。

## GPU 24 小时时间分配（项目方 11-02 04:0x；SENTINEL，tools/sentinel/gpu_hours.py → data/rsi/gpu_24h.json 每小时刷新，8810“GPU 24 小时”表）

对象：生产出图卡 gpu33:0/1/3、gpu36:0/1；VLM 卡 gpu36:2、笔记本 4080 单列。窗口 = 最近 24 小时，按 10 s 一格归类，每格只归一类（优先级 真正在跑 > 空跑 > 借道实验 > 等待任务 > 无数据），各项合计 = 24 h。

| 项 | 口径 | 证据 |
|---|---|---|
| 真正在跑 | 生产任务（ComfyUI 执行带 ns_tag.agent=PRODUCER）执行成功，且 producer 日志在执行结束后 15 分钟内有同镜 `rendered`（take 入库），该 take 没被回滚作废；不论之后契约过没过 | 服务器 ComfyUI /history 执行区间 + producer `rendered`；/history 覆盖之前用 `rendered.gpu_s` |
| 空跑 | 卡被占着或在跑但没有有效产出：执行报错 / 中断；执行成功但没收下（孤儿）；产出被回滚作废（`master_reject` 原因含 身份脸用错 / 覆盖配置缺失 / 作废 / 回滚 / 孤儿 / 重复 / 全量重做，例：01:24–01:32 错脸 31 张）；派单后到取回 / 报错之间卡没在执行（加载、传输、等结果） | /history + producer `dispatch` / `rendered` / `infra_error` / `master_reject` |
| 借道实验 | 别的 loop 占卡（ns_tag.agent≠PRODUCER 或未标：A/B、标定、冒烟）。不是生产也不是空转，单列；需要时并入“空跑”由总调度定 | /history 的 ns_tag |
| 等待任务 | 有证据卡上没有任何执行、也没有派给它的单（pause / hold / 断连 / 服务停 / 没有 ready 单） | /history 覆盖时段内的空白 |
| 无数据 | 拿不到证据的时段：/history 覆盖不到（ComfyUI 重启前）且日志里没有这张卡的派单；远程取数失败的整机；VLM 卡（没有 ComfyUI 历史，等 data/sentinel/gpu_samples.jsonl 的 nvidia-smi 采样攒满 24 h） | — 不猜 |

RSI 线 5“自运行”分项取 `for_rsi_line5.productive_pct`（生产 5 卡“真正在跑”占 5×24 h 的百分比，无数据时段留在分母里）。

“等待任务”再按原因拆（总调度 04:1x；同样 10 秒一格，优先级自上而下，写进 gpu_24h.json waiting_reasons，看板展开行）：
| 原因 | 口径 | 负责方 |
|---|---|---|
| 服务停 | 这条道 infra_error 之后到下一次 rendered（最多 30 分钟） | DEBUG-RSI |
| 断连 | supervisor.log 该道隧道 PROBE fail / KILL / EXIT → UP 之间，且当时由笔记本经隧道派单 | DEBUG-RSI |
| 时区存疑 | 只有 ts 字符串、没有 epoch t 的 pause（ts 可能是服务器 EST 写的，K-OPS-E18）；带 t 的事件一律以 t 为准（11-02 08:1x 核对：EST 写的 pause 的 t 与东京时间一致） | DEBUG-RSI |
| 总调度暂停 | 暂停事件 by 含“总调度 / fredw-2b”的段（派单方照实写，记在总调度账上，不开单；例 11-01 19:41–23:17 总调度全局暂停（为 IMGFIX），显示名在 sentinel.yaml GPU24_alloc.pause_labels） | 总调度 |
| 暂停（运维 / 各 loop） | 该道当时的派单方（最近一次派单来自笔记本还是服务器 producer）处于 pause / resume 之间（没有 resume 时以同一派单方下一次派单为结束；SENTINEL control 历史开始记录后以历史为准） | DEBUG-RSI |
| 打分积压闸顶满 | 派单方记 score_backlog 后 300 s 内 | DEBUG-RSI |
| hold（让道） | SENTINEL control 历史（data/sentinel/control_history.jsonl，11-02 08:1x 起）里该道在 hold_lanes 或 partition.json _temp_holds；之前没有历史的时段计入“原因不明” | FACTORY |
| 队列没单（缺资产 / 缺稿） | 派单方这一分钟有 preflight_block | FACTORY |
| 原因不明 | 以上都没有证据 | SENTINEL（探针缺口） |
最大两项（不含原因不明）各开一张 GPU24 工单；原因不明超过等待任务的 20% 另开一张派 SENTINEL。
ComfyUI 重启会清空 /history：空历史不算“没执行”（记无数据），SENTINEL 每小时把取到的执行区间存档到 data/sentinel/comfy_hist/，重启后用存档补。VLM 卡按 data/sentinel/gpu_samples.jsonl 的 nvidia-smi 采样算（利用率 ≥ 5% = 在跑），没有采样的时段 = 无数据，攒满 24 小时自动全覆盖。
按 run（季）分开的出图量：gpu_24h.json by_run（对象 id 带 <run>/ 前缀的归该 run，否则归主 run；rendered 次数、收下次数、GPU 执行小时、出过图的镜数），看板 GPU 24 小时区和 RSI 区、晚报都按 run 分开显示（总调度 08:2x，第二季与第一季同等优先）。暂停段清单 pause_segments 写谁暂停的、备注、起止。
