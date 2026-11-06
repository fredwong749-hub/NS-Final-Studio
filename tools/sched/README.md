# SCHED-CORE：跨两台服务器的全局 GPU 工作板（11-06）

目标：L-205 KPI 一集 ≤ 50 min；L-206 一卡一模型、少切换；L-207 首尾帧 → 全卡视频 → 合成 → 下一集；L-202 按镜判就绪、卡不空转。

今天慢的根因：5–6 个各自为政的调度器（每台一个 producer 出图、每台 night + vidgen 出视频、笔记本 asset_worker、lane_relay、video_shard）
靠 hold / yield / 分片互相让道 → 卡空转、模型来回切、重复 / 过期活、视频等整集首尾帧、night 主循环被同步 / 预览阻塞 5–10 min。

本目录 = 独立的调度核心 + 模拟器 + 单测，**不改 producer / night / vidgen**（另有审计在看它们），默认不开（`config/pipeline/sched.json enabled=false`）。

| 文件 | 作用 |
|---|---|
| `core.py` | 工作板：任务 DAG、道池、拉式派单（HEFT 秩 + 亲和代价）、打分队列、租约 / 心跳 / 超时、幂等事件、JSON 状态、ETA |
| `sim.py` | 离散事件模拟器：用 11-06 ep01 实测耗时重放，比较今天 / 固定工位 / 新调度 / turbo 四种方式 |
| `../../tests/test_sched_core.py`、`test_sched_sim.py` | 单测（DAG 就绪、换代失效、亲和、关键路径、尝试→采用、租约超时换道、永不 gpu33:2、三段策略、幂等、序列化、ETA；模拟器确定性与场景关系） |
| `../../config/pipeline/sched.json` | 唯一配置 |

## 1. 模型

**任务 DAG（每集）**：`face/sheet/scene(资产) → first(镜) → last(镜) → video(镜) → assembly(集)`。
资产边只连到**用到它的镜**（按镜判就绪，L-202：S1 的脸 / 造型 / 底图齐了就出 S1，S2 单独等）。
首帧换代（`regen`）→ 本任务版本 +1、下游 last / video / assembly 全部失效（已 passed 的也回 blocked、尝试清零）；
道上还在跑的旧版本结果到达时按版本号丢弃（`rendered → "stale"`），不算尝试、道照常释放。

**道池**：`gpu33:0/1/3 + gpu36:0/1/2`（`gpu33:2` 坏卡：配置写了也剔除、`add_lane` 直接报错、反序列化也剔除）。
每道：`loaded_model ∈ {image, video, vqa, none}`、`render_capacity`（出图 / 视频并发，默认 1 = 队列深度 1）、`vqa_slots`（同卡看图实例数）、`health`、`speed`（耗时倍率）。
合成在伪道 `cpu:0`（不占卡）。

**状态机**：`blocked → ready → leased → running → scoring → passed | failed → (ready 重试 | best_effort → adopted)`。
`attempts ≤ max_attempts(3)`；用尽 → `best_effort`，`auto_adopt=true`（L-196 / L-204）即自动 `adopted`（取分最高一版），下游照常放行；关了就停在 best_effort 等 `adopt` 事件（项目方 / 总调度看图后）。
`passed / adopted` 都算“定下”。

**打分独立队列**：出图 / 视频道报 `rendered` 后任务进 `scoring` 队列，由 VQA 工位（有 `vqa_slots` 的道）`next_score_job` 拉走；出图 / 视频道**从不等打分**，立刻去问下一个任务。

## 2. 派单算法（拉式、全局贪心、带亲和）

道空了来问“下一个做什么”（`next_for_lane`）。工作板在所有 (空道, 就绪任务) 对上反复取：

```
score(task, lane) = rank(task) − episode_penalty · (task.ep − 最早在做的集) − cost(task, lane)

rank(task)  = work(task) + max over 下游 rank          （HEFT 向上秩 = 本任务起的关键路径剩余时间）
work(task)  = (est_mean(kind) + score_prior(kind)) × max(1, expected_attempts(kind) − 已用尝试)
cost(task, lane) = est(kind, lane) + switch_penalty(lane.loaded_model → task.model)   （同模型 0）
est(kind, lane)  = EWMA(实测 kind|lane)，没有就 duration_prior × lane.speed
```

- 秩大 = 关键路径长（first > last > video > assembly），先做；同秩按 id，确定性。
- `episode_penalty`（默认 100000 s）= 严格按集序（早的集永远先）；0 = 纯关键路径。
- 换模型只在“秩差 > 换模型代价”时发生；没别的活时照样切（不空卡）。
- 多个空道同时问：全局贪心先配最好的一对，再配剩下的（真正会被落租约的只有来问的那条道；别的道各自来问时再算，避免给没心跳的道“预留”活——`lane_stale_s` 内没心跳的道不参与规划）。
- 规划结果确定性：相同状态 → 相同分配（单测 `test_critical_path_priority…` 校验）。

**三段策略（L-207）** `policies.phase_gate`：
- `strict`（默认）：下一集的 first / last 要等本集视频全部定下；本集已进视频阶段时下一集视频可并入（同模型）；资产不受限（`assets_bypass_phase_gate`）。
- `fill_idle`：同上，但道空且没任何别的活时放行下一集首尾帧（L-202 空卡巡检精神）。
- `off`：纯关键路径。

**租约**：`lease{lane, token, t0, hb, ttl, version}`；`heartbeat(token)`；`expire(now)` 把心跳断的任务回 `ready`、记 `avoid_lanes`（下次尽量换道）、道超时计数到 `lane_down_after_timeouts` 标 `down` 不再派。打分租约同理（`score_lease_ttl_s`）。

**幂等事件**：`Board.apply({"id", "type", "t", ...})`，同 `id` 第二次返回 `"dup"`；类型：`lane_seen / next / start / heartbeat / rendered / next_score / scored / regen / adopt / hold / release / lane_role / expire`。
**单写者**：所有改动经同一个 Board 实例（进程内）或同一个服务进程；`save()` 原子写（tmp + replace），`load()` 重放安全（seen 集合随状态保存）。

**ETA**：`eta(now)` = `max(关键路径, 剩余工作量 / 健康出图道数)` 对 `kpi.episode_s`（3000）；`snapshot()` 给看板。

## 3. 配置 `config/pipeline/sched.json`

| 键 | 含义 | 默认 |
|---|---|---|
| `enabled` | 执行器是否先问工作板（false = 现状，各自调度） | false |
| `kpi.episode_s` | 一集 KPI | 3000 |
| `lanes.<id>.{host,speed,vqa_slots}` | 道池；gpu33:2 永不出现 | 6 道，gpu36 speed 1.25，gpu33:3 vqa 3 |
| `switch_penalty_s."a->b"` | 换模型代价 | image↔video 90，none→image 60 … |
| `duration_prior_s.<kind>` | 耗时先验（gpu33 基准） | first/last 310，video 410，assembly 360 |
| `score_prior_s.{image,video}` | 看图 / 打分耗时 | 90 / 65 |
| `expected_attempts.<kind>` | 关键路径用的期望尝试次数 | first 2.4，last 1.9，video 1.4 |
| `ewma_alpha` | 实测耗时平滑 | 0.3 |
| `policies.max_attempts / auto_adopt` | 3 次用尽自动采用 | 3 / true |
| `policies.phase_gate` | strict / fill_idle / off | strict |
| `policies.episode_order_penalty_s` | 集序优先强度 | 100000 |
| `policies.lease_ttl_s / score_lease_ttl_s / heartbeat_s` | 租约 | 1500 / 600 / 30 |
| `policies.lane_stale_s / lane_down_after_timeouts / requeue_avoid_same_lane` | 道健康 | 120 / 2 / true |
| `sim.server_repo` | `sim.py --fetch` 只读取数用的服务器仓库路径 | |

## 4. 模拟结果（`python tools/sched/sim.py --seeds 3`，11-06 实测参数，ep01 16 镜）

实测输入（只读取自两台服务器）：首尾帧 base35 gpu_s 中位 gpu33 310 s / gpu36 400 s，含排队 render_s 610 s（预取 2 深）；看图契约 91 s；
首帧每次不过率 77%、尾帧 57%（redo_fail / content_fail ÷ rendered）；视频 DONE gpu33 404 s / gpu36 415 s，打分 65 s，不过 ≈ 30%；合成 ≈ 6 min。

| 场景 | 总分钟 | 首尾帧 | 视频 | 合成 | 首视频起 | GPU 均用% | KPI≤50 |
|---|---|---|---|---|---|---|---|
| a 今天的方式（各自调度、预取 2 深、视频等整集、night 阻塞）——实测 ≈ 150 | 176 | 96 | 74 | 6 | 96 | 54 | 否 |
| b L-206/207 固定工位（出图 4 + 审图 1 + 视频 1 → 6 卡视频） | 138 | 101 | 31 | 7 | 61 | 64 | 否 |
| c 新调度（6 道一个工作板、亲和、按镜就绪） | 123 | 88 | 29 | 6 | 72 | 76 | 否 |
| d c + turbo 8 步首尾帧（75 / 95 s） | 75 | 45 | 25 | 5 | 22 | 65 | 否 |
| e d + 审图 6 实例（gpu33:3 ×3 + gpu36:2 ×3） | 68 | 30 | 33 | 6 | 23 | 61 | 否 |
| f e + 检测修好（首帧过率 60% / 尾帧 70%、看图 45 s） | 60 | 20 | 34 | 6 | 17 | 65 | 否 |

各道利用率 / 切换次（c）：gpu33:0 87/3，gpu33:1 89/3，gpu33:3 21/1（审图位，只在视频阶段出视频），gpu36:0 89/2，gpu36:1 86/2，gpu36:2 86/2。
a 的模拟值（176）比实测（150）偏悲观：模拟里 night 阻塞按每镜 2 min 计且视频道不派活；实测值以日志为准。

读法（L-205 要求的超时归因）：
1. **GPU 调度**：a→c 省 ~50 min（固定工位 b 只省 ~40：审图位整段 ~12% 利用率、视频位首尾帧阶段 39%）。
2. **逻辑（出图档位）**：base35 → turbo 8 步（L-206 ②）再省 ~50 min，是最大的一刀。
3. **检测**：turbo 之后瓶颈变成看图——32 张 × 2.4 次 × 90 s ÷ 3 实例 ≈ 38 min；审图加到 6 实例（e）省 7 min，不过率降到 40% / 30% + 看图 45 s（f）再省 8 min。
4. **剩下的硬底**：视频 16 段 × 1.4 次 × 410 s ÷ 6 卡 ≈ 25 min + 打分 + 尾段 ≈ 34 min。要进 50 min 还得：视频一次过率 ≥ 85%（1.4 → 1.15 次）或单段 < 5 min，或首尾帧阶段就让 2–3 张卡开始出已定镜的视频（c 的秩已倾向先做首尾帧，可把 `expected_attempts.video` 调高让视频秩上升）。
   以 f 的首尾帧 20 min + 视频（1.15 次）≈ 22 min + 合成 6 min ≈ 48 min 为可达路径。

## 5. 接入计划（lease board）

### 5.1 进程内库（第一步，无常驻）
```python
import sys; sys.path.insert(0, "tools/sched"); import core as S     # tools/ 不是包，按仓库惯例 sys.path / importlib 引入
board = S.Board(S.load_config())          # enabled 由调用方判断
S.build_episode(board, ep, shots, assets={shot: ["face:林晚", ...]}, holds={"S12": "成人镜等项目方"})
lease = board.next_for_lane("gpu33:0", now)        # → {task, kind, ep, shot, lane, token, attempt, version, est_s} | None
board.start(token, now); board.heartbeat(token, now)
board.rendered(token, now, secs=..., result={"take": n, "png": ...})  # → "scoring" | "passed" | "stale"
job = board.next_score_job("gpu33:3", now)         # VQA 工位拉打分
board.scored(job["token"], now, ok, score, why)    # → passed | ready(重试) | best_effort | adopted
board.regen("first:ep01-S1", now, reason="L-203")  # 换代 → 下游失效
board.expire(now); board.eta(now); board.snapshot(now); board.save(path)
```

### 5.2 小 HTTP 服务（第二步，笔记本或 gpu33 上一个进程 = 单写者）
`tools/sched/service.py`（待写）监听 `127.0.0.1:8811`（gpu36 经现有 lan_proxy / ssh -R 反向到笔记本，同 K-REV-V01 只认内网来源）：

| 方法 | 路径 | 体 | 返回 |
|---|---|---|---|
| POST | `/v1/lane/{lane}/next` | `{id, t, loaded_model}` | lease 或 `null` |
| POST | `/v1/lease/{token}/start` / `/heartbeat` | `{id, t}` | ok |
| POST | `/v1/lease/{token}/rendered` | `{id, t, secs, result}` | `scoring / passed / stale / dup` |
| POST | `/v1/vqa/{lane}/next` | `{id, t}` | score job 或 `null` |
| POST | `/v1/score/{token}` | `{id, t, ok, score, why, secs}` | 新状态 |
| POST | `/v1/task/{task}/regen` / `/adopt` / `/hold` / `/release` | `{id, t, reason}` | 受影响任务 |
| POST | `/v1/lane/{lane}/role` | `{id, t, render_capacity, vqa_slots, allow_models}` | ok |
| GET | `/v1/snapshot` / `/v1/eta?ep=` / `/v1/board` | | JSON（看板 8810 直接拉） |

所有 POST 带 `id`（调用方生成 uuid），重试安全；服务每次改动后 `save()`（原子写 `data/sched/board.json`），重启 `load()` 重放。

### 5.3 迁移步骤（不碰现有执行器之前 → 之后）
1. **影子模式（本任务已可做）**：`sched.json enabled=false`，resident_sync 里起一个只读线程：从 producer registry / vidgen state 喂事件进工作板，
   `snapshot()` 进看板 8810，并把“工作板会派什么 vs 实际派了什么”写 `data/sched/shadow.jsonl`——不改任何派单。看一集，核对估算与实际。
2. **producer 问板**：`producer.py` 派单循环里，每条空道先 `next_for_lane`（enabled=true 才问；返回 None 则该道不派）；`rendered` 后把契约 / 看图交给 VQA 工位（score 线程池改成 `next_score_job` 消费者），结果回 `scored`。
   规则：producer 不再自己选对象、不再 fanout / hold / canary 暂停整台；换代（regen / master_reject）改为向工作板发 `regen`。
3. **vidgen 问板**：`vidgen.py` 每道空了 `next_for_lane`，拿到 `video:epNN-Sx` 才提交；`DONE → rendered`，`SCORE → scored`；night 不再按台分集 / 分片（video_shard、lane_relay 关），只做合成（`assembly` 任务由 night 在 cpu:0 领）。
4. **asset_worker 问板**：资产任务（face/sheet/scene）由板按镜需求排优先级，笔记本 asset_worker 作为一条“请求道”领任务并转交对应 ComfyUI。
5. **工位切换**：`lane_role` 事件替代 lane_roles.json 的两张表（L-206/L-207 两段仍成立：首尾帧阶段 gpu33:3 vqa 3 实例；全部定下 → gpu33:3 render 1 + vqa 1）；idle_watch 改读 `snapshot()`：有 ready 任务而道空 > 5 min 才报。
6. **退出条件**：任一步出问题 `enabled=false` 即回旧行为（执行器各自判断 enabled，不依赖服务存活：服务不可达也按 enabled=false 处理并报卡点）。

### 5.4 不做的事（本任务约束）
不改 producer / night / vidgen / asset_worker；不发版、不部署、不提交；不写服务器；gpu33:2 永不入池；成人镜头 hold 由项目方触发放行。
