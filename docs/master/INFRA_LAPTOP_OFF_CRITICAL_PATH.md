# 设计稿：把笔记本挪出关键路径（监控 / 中继 / 拉取都搬到服务器，笔记本只看）

W-INFRA 11-06 夜（PLAN_OVERNIGHT_20261106 第 4 线）。**只是设计，今晚不落地**；早上给项目方 / 总调度选择题。

## 1. 现状：笔记本为什么在关键路径上

11-05 10:00 → 11-06 05:20（笔记本本地时间）data/netfix/supervisor.log 实测：

| 现象 | 数字 | 根因（已查实） |
|---|---|---|
| base-b（直连跳板）反复重连 | EXIT 237 次 / 19 h，活不过 60 s 的占 233 次（p50 34 s） | 直连跳板认证通过后不回包，ServerAlive 10 s × 3 = 30 s 就 “Timeout, server not responding”；每次重连 = 跳板上一次白握手（ssh_base-b.err.log：channel open failed / No route to host、banner [False, False] 4.1 s） |
| 内层连接（道 / 命令主连接）批量掉 | gpu36-vqa 17 次、l3 11 次、cmd×8 条各 4–9 次，全部 rc=255、活 20–40 s | ssh_*.err.log 整页 “Connection timed out during banner exchange”：经 base-a 握手时 ConnectTimeout=20 s 内读不到服务器 sshd banner（底座被出图流量挤慢），退出 → 8 条同时重握手 → 更挤 |
| base-a 劣化 | banner slow 32 次、degraded 4 次 | 同上：一条 TCP 里排队（出图道 + 命令会话） |
| 命令通道成功率 | 1 h：gpu33 84.9%、gpu36 90.7%（目标 99%）；p50 2.2 s、p90 28 s、p99 106 s | 调用量 ≈ 3 100 次 / h（52 次 / min）；超时 (rc 124) 250 次、连接层 (255) 144 次 |

命令通道 1 h 调用量按来源（data/netfix/rssh_calls.jsonl）：

| 来源（笔记本进程） | 次 / h | 说明 |
|---|---|---|
| puller 小文件镜像 `cat …/registry.json` | ≈ 830 | 4 个 run × 2 台、每 90 s（**今晚已合并成每台一次 tar**） |
| resident_sync / 各线程 `cd …/repo && …` | ≈ 640 | 同步、relay、健康、打分 |
| `python3 -`（gpu_monitor API 12 s 超时、resident_sync 探针、restart_queue） | ≈ 445 | 界面 GPU 面板每次请求一条 |
| jobs.py 训练锁 `ls -1A` | ≈ 320 | API 后台刷新，缓存 30 s |
| puller 出箱清单（base64 exec） | ≈ 250 | 每台每 10 s 一拍 |
| monitor/server.py nvidia-smi | ≈ 150 | 看板 |
| 监管进程合成探测 `true` | ≈ 105 | 成功率指标本身 |
| sentinel 探针 / VQA 健康 | ≈ 100 | |

结论：**笔记本既是“观察者”又是“执行者”**——出图派单（dispatch laptop 模式）、视频中转（shard_relay）、成品拉回（puller）、打分（full_score 经隧道）、重启队列、生命周期拉起，全部经同一条香港底座；底座一抖，这些全部一起停。项目方“gpu 资源不能空闲”（L-202）的空卡，很多是笔记本连接抖出来的。

## 2. 今晚已做（笔记本端，不改架构）

- 底座 ssh 保活 15 × 6 = 90 s（原 10 × 3）；内层 ConnectTimeout 45 s（原 20）；退避只往上抖 ≤ 25%；
  纯热备底座（没有内层挂它）连续 4 次活不过 60 s → 每次重连多等 900 s（另一条底座一断立刻叫醒）；底座劣化时内层同时握手 ≤ 2。
  → 预期：base-b 的白握手从 ≈ 12 次 / h 降到 ≈ 3 次 / h；内层 banner 超时型重连明显减少。生效需监管进程重启（`tunnel_supervisor.py stop` → 等心跳过期 → `ensure`），已在跑的 ssh 认领不打断。
- puller 镜像 8 次 / 90 s → 2 次 / 90 s（省 ≈ 240 次 / h）。

## 3. 目标形态：一台服务器当“编排台”，笔记本只看

```
            [项目方浏览器] ──只读──> [笔记本 :8800 网页 / 看板]
                                          │  只拉快照（net_status / pipeline_status / 缩略图），不发命令
                                          ▼
      ┌──────────── gpu33（编排台，ORCH）─────────────┐
      │ producer serve（本机道）  night / vidgen       │
      │ orch_tick（新）：                               │
      │   · 每集三段调度（L-207）、lane_roles 阶段钩子    │
      │   · 空卡巡检（L-202）→ 派活                     │
      │   · 重启队列 / 生命周期拉起（本机 bash）           │
      │   · 中继：gpu36 ⇄ gpu33 成品 / 输入图（内网 10.0.0.x，rsync 或 lan_proxy）│
      │   · 看图分发器 :8870（已在 gpu33:3）             │
      │ 状态落盘：data/orch/*.json（单一真相）            │
      └──────────────────────┬──────────────────────┘
                             │ 内网 10.0.0.0/24（不经跳板）
      ┌──────────── gpu36（工位）─────────────────────┐
      │ producer serve  night  vidgen  ComfyUI ×3      │
      │ 只认 gpu33 的派单 / 控制文件（HTTP 内网接口）      │
      └──────────────────────────────────────────────┘
```

要点：
1. **执行全部在服务器本机或内网**：gpu33 ⇄ gpu36 之间走 10.0.0.x（已有 lan_proxy.py 的白名单 / 只监听内网 / 无登录能力模式，K-REV-V01），不再经笔记本中转。
2. **笔记本降级为只读视图 + 人工入口**：网页 / 看板读服务器写好的快照（经隧道拉 JSON，每 30–60 s 一次，一次一条合并调用），项目方的“用这张 / 修改”写入笔记本本地队列，由服务器编排台定期拉取（现有 outbox 反向：`inbox`）。笔记本掉线 = 看不到最新，但生产不停。
3. **命令通道只剩两类**：① 快照拉取（1 次 / 30 s / 台）② 人工决策下发（有事才发）。目标 < 300 次 / h（现在 3 100）。
4. **跳板上长连接**：2 条底座 + 2 条命令主连接（现在 2 + 8 + 7 道）；出图道隧道不再需要（出图在服务器本机派）。
5. **单一真相在服务器**：registry / takes / lane_roles_state / review_scale 都只在 gpu33 写；笔记本的 data/ 变成镜像（puller 只拉、不并回）。现有 partition.json 的 `laptop` 分区保留但默认空。

## 4. 分步（每步可回退，不改架构的先做）

| 步 | 内容 | 风险 | 回退 |
|---|---|---|---|
| S0（今晚） | 隧道参数 + puller 合并（§2） | 低 | 改回 tunnels.json 旧值 |
| S1 | API / 看板所有“每次请求一条 ssh”的读取改读 puller 镜像（gpu_monitor、jobs.py 训练锁、monitor nvidia-smi 并入 sentinel remote_probe 一拍一次） | 低：只是读旧 ≤ 60 s | 开关 NS_LIVE_SSH=1 |
| S2 | 中继改内网：shard_relay / resident_sync.relay 在 gpu33 上跑（源 gpu36 → 目的 gpu33 直接 scp/rsync 内网），笔记本只保活 | 中：需要 gpu33→gpu36 内网互信（只许 rsync 限定目录的 key，`command=` 限制） | 关掉服务器中继、笔记本中继照旧 |
| S3 | 编排台 orch_tick 搬到 gpu33：lane_roles 阶段钩子、空卡巡检、重启队列、生命周期，全部本机 bash（已支持 OFFLINE_SELF 本机执行路径） | 中：两处同时编排会打架 → 用 config/netfix/partition.json 的 `orchestrator: gpu33` 字段 + 笔记本侧硬性只读 | 字段改回 laptop |
| S4 | 项目方决策 inbox：笔记本 → gpu33 拉取（现有 puller 反向） | 低 | 决策仍走 rssh 下发 |
| S5 | 出图道隧道（6 条）退役，只留 2 底座 + 2 命令主连接 | 低 | tunnels.json 加回 |

## 5. 需要项目方 / 总调度定的（早上选择题）

1. **gpu33 ↔ gpu36 内网互信**：A 单向 gpu33→gpu36、限定 rsync 目录的专用 key（推荐）/ B 不加互信、继续走 lan_proxy HTTP 推拉（慢、要改代码）/ C 维持笔记本中转。
2. **编排台放哪台**：A gpu33（审图位在它上面，决策数据近）/ B gpu36（三卡都归 NS、负载更轻）。
3. **笔记本掉线时的产品行为**：A 生产不停、网页显示“最后同步 N 分钟前”（推荐）/ B 生产暂停等人。

## 6. 不做

- 不加新的对外监听（只许 127.0.0.1 / 10.0.0.x，K-REV-V01）。
- 不删任何现有隧道 / 脚本：退役一律进 `_retired` 或隔离区。
- 不在生产中途切换（L-204：集内不改架构）。
