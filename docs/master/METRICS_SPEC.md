# METRICS_SPEC（集级指标规范 v1：EPCHAIN-O 11-03 起草逐段格式，METRICS-F 合并定稿）

目的：项目方 11-03 02:1x 定的目标——每做完一集，和上一集比：**依赖模型是否减少、生产时间是否缩短、画面质感、成功率、自动化是否提高**；终点是 100% 全自动、质感接近 95% 好莱坞级。
本文两部分：§A 写作链逐段计量的**写入格式**（写入方 `tools/script_rsi/autoflow.py`，EPCHAIN-O）；§B **集级汇总指标**的定义与取数（读取 / 计算方 `tools/master/episode_metrics.py`，METRICS-F）。

产物：`data/pipeline/runs/<run>/metrics/epNN_summary.json`（汇总）+ `data/review_pages/metrics/<run>_epNN.html`（单集）/ `<run>_ep0A_vs_ep0B.html`（对比）。

规矩：只读真实记录，**拿不到的数一律 `null` 并在 `nulls[]` 写明原因，不估、不编**。看图打分只走本地 / 自有机器上的 VLM（`ns_agent.vqa.client.generate`），图不出外网。

---

## §A 逐段计量格式（写入方 autoflow，EPCHAIN-O 草案 v1）

### 文件

- 路径：`data/pipeline/runs/<run>/metrics/epNN.jsonl`（每集一份，只追加，一行一个 JSON）。
- 什么时候写一行：某一段（stage）**到了一个结果**。进行中的状态（running / awaiting_* / repair_requested / needs_patch / revising /
  held_by_p1_gate / deviation / reopened / waiting_p1_review，以及 P1G 的 owner_direction）不写；同一段同一结果重复报告不重复写。
  一段先有结果、后又退回进行中（例如补丁环“有新失败项，退回待修”），下次再到结果时再写一行——所以同一 stage 可能有多行，按 `ended_at` 取最后一行即最终结果。
- 写失败只打印，不挡推进。

### 字段（schema = `nsfs.metrics.stage/1`）

| 字段 | 类型 | 含义 |
|---|---|---|
| schema | str | 固定 `nsfs.metrics.stage/1` |
| run | str | 剧（run 目录名） |
| episode | int | 集号 |
| stage | str | 段 id：P0 / P1 / P1L / P1R / P1G / P2 / P3 / P4 / EPG / facts / code / factcheck / score / gate / import / asset_ready / asset_jobs |
| name | str | 段中文名 |
| started_at | str | 这一段（这一轮）开始时间，本地时间 `YYYY-MM-DDTHH:MM:SS`（第一次出现、或从结果退回进行中时记） |
| ended_at | str | 到结果的时间 |
| duration_s | int | ended_at − started_at（含等 agent / 项目方的时间：claude_agent 期间这就是“生产时间”） |
| by | str | 由谁完成：`code`（纯代码判定 / 复用）、`agent:<模型>`（写作包由 agent 交稿；模型先取最近一次交稿 `.done` 前 5 行里的 `model: <id>`，没有才用派人请求里的建议模型：写手 `fable`、评审 `sonnet`、P1 评委 `sonnet+haiku+opus`）、`api`（writer_backend=api 时外部模型）、`owner`（项目方点选） |
| model_source | str? | 只在 by=agent:* 时有：`done`（取自 .done）/ `suggested`（建议模型） |
| attempts | int | 尝试次数 = 这一段出过的写作包个数（writer_tasks/<step>_a*.json），没有包的代码段 = 1；carried 段 = 0 |
| result | str | 段的结果状态原文（ok / reused / approved / imported / reimported / blocked / not_importable / gaps / …） |
| ok | bool | result 是否算成功（ok / reused / approved / passed / imported / reimported / dry_run_ok / ready / generated / importable） |
| carried | bool | 整季只做一次的段（P0 / P1 / P1L / P1R / P1G）在第 2 集起是沿用：carried=true，by=code，attempts=0，不计入本集的人工 / agent 工作 |
| decider | str | 原始 decider（code / api_model / judge / owner），便于核对 by 的映射 |
| writer_backend | str | claude_agent / api |
| usd | float? | 有花费时才有（api 后端） |

### METRICS-F 对 §A 的定稿意见

- **模型字段要记实际派的模型，不是建议模型**：派人时 `.done` 文件第 2 行写 `model: <id>`（例 `model: claude-fable-5-1`），autoflow 写 `epNN.jsonl` 时 `by` 取 `.done` 里的 model；没有就退回建议模型并加 `model_source: "suggested"`。`episode_metrics.py` 读 `.done` 时也按同一规则。
- 有 `epNN.jsonl` 时，§B 的写作段时间 / attempts / by **优先用它**；没有（ep01 回溯）才从 autoflow.log / autoflow.json 反推，并在 `nulls[]` 记“逐段计量未落盘，按日志反推”。

---

## §B 集级汇总指标（计算方 episode_metrics.py）

### 1. 数据源（按阶段）

| 阶段 | 记录 | 用途 |
|---|---|---|
| 写作 P1→导入 | `runs/<run>/metrics/epNN.jsonl`（§A，优先）；回溯：`autoflow.log`（每次推进一行，带 source / verdict）、`autoflow.json`（stages / agent_history / started）、`writer_tasks/`、`writer_out/`（含 `.done`）、`writer_out_void/`、`_rejected_*/`、`judge_p1/STATE.json`、`owner_gates.json` | agent 调用数、各步尝试次数、项目方等待、人工介入 |
| 资产阶段 A | `data/pipeline/asset_jobs/<run>/*.json`（nsfs.asset_job/1，含 log）、`data/ab/v2_assets/<run>/<job>/takes.jsonl`、`data/ab/v2_cast/takes.jsonl`（CAST-S 身份脸 / 场景候选，经 face/scene 作业 `adopted_from` + `target` 关联） | 出图次数、契约通过率、VLM 调用、项目方挑选等待 |
| 金样阶段 B | `data/ab/v2_golden/takes.jsonl`（按 `compile_trace.shot` = `epNN-*` 归集）、`asset_jobs/worker.json` 的 golden 开关 | 金样候选通过率、质感分 |
| 横切 | `data/pipeline/issues.jsonl`、`data/ops/api_lifecycle.jsonl`、`data/debug/lane_loans.jsonl`、`data/state/netfix/partition.json`（lanes）、`docs/master/V2_LIVE.md` | 卡点、人工重启、借道 / 挂道、道的清单 |

一集的**时间窗**：`autoflow.json.started`（或本集第一条 autoflow.log）→ 本集最后一条可见记录（资产作业 / takes / 挂道里最晚的时间）。横切数据只取窗内的行。

### 2. 指标定义

#### 2.1 模型依赖（`model_calls`）
- `writer.calls`：`writer_out/` 里 writer 角色的交稿数（.json / .md，不含 .done）+ `writer_out_void/` 作废稿 + `_rejected_*/writer_out_*` 作废稿；`voided` 单列。角色看 `writer_tasks/<同名>.json` 的 `role`，找不到包时 `facts_* / factcheck_*` 记 reviewer。
- `writer.model`：先读 `.done` 第 2 行 `model:`；没有则按 PIPELINE_SOP_V2 步骤 1（写手 = Fable，L-109 测试期 Claude 写）标注，`model_source` 写明来源。
- `reviewer.calls`：facts / factcheck 交稿数；模型取 `.done`（如 `FACTCHECK claude_testphase` 没有型号 → `model: null`）。
- `judges.calls`：`judge_p1/STATE.json` 各轮 `result.judge_ids` 之和；`by_model` 按 id 后缀（fable / opus / sonnet / haiku）归类。
- `vlm.calls`：出图候选每条 take 的本地 VLM 调用数估算：`vlm`（逐条核对）1 次 + Q9 状态 pass/fail 1 次 + 顶层 `age` 1 次 + 顶层 `ocr` 1 次（CAST-S 一张图 4 次；阶段 A 合并看图 1 次 + Q9）。`vlm.calls_estimated: true`。
- `hollywood_vlm.calls`：好莱坞质感打分实际调用次数（见 2.4）。

#### 2.2 人工 / agent 介入（`interventions`）
每一类都给数量 + 明细（时间、谁、做了什么）：
- `manual_cli`：autoflow.log 里 `source ∈ {cli, escalate}` 的推进（手工命令、总调度转交）。
- `rejected_deliverables`：`autoflow.json.agent_history` 里 `accepted == false`（写手交错、补丁未减少失败项等）。
- `requeue_after_fix`：资产作业 log 里“重新排队（attempts 归零）”（代码修了根因再手工重排）。
- `api_restarts`：`api_lifecycle.jsonl` 窗内 `event=started` 且 `by` 不是 pytest / *-sim 的（项目方 / 总调度 / restart_api 手起）。
- `manual_lane_holds`：`lane_loans.jsonl` 窗内 `ev ∈ {hold, lend}` 且 `by` 不是 ASSET-WORKER / producer / DEBUG-RSI 自动回收的系统 worker。
- `issues`：`issues.jsonl` 本 run 本集 `open` 条数、`blocking` 条数、已关闭数（参考，不计入 total）。
- `v2_live_mentions`：V2_LIVE.md 含“手工 / 手动 / 人工 / 补救 / 补记 / 接手 / 临时”的行数（只有 HH:MM，不能按窗过滤，参考）。
- `total`：前五类之和。

#### 2.3 时间（`time`，秒；同时给 `h`）
| 键 | 起 | 止 |
|---|---|---|
| `writing_p1` | `autoflow.json.started` | `owner_gates.P1.at`（项目方放行 P1） |
| `writing_p2_to_import` | P1 放行 | autoflow.log 最后一条 `verdict=imported` |
| `stage_a_assets` | 本集第一条资产作业 `created_at` | 全部作业 `done` 时的最大 `updated_at`；未完成 → `end: null`，给 `elapsed_so_far_s` |
| `stage_b_golden` | 本集金样 takes 第一条 `at` | 最后一条 `at`；没有 takes → null |
| `owner_wait` | 写作：autoflow.log 第一条 `owner_direction` → `owner_gates.history` 下一条 owner 动作（revise / approve），逐段累加；阶段 A：作业 log “投待办通知 / 接管已有的待办通知” → “项目方选定”，未选定的算到窗尾并标 `open` | |
| `total_wall` | 窗起 | 窗尾 |

#### 2.4 质感（`quality`）
按来源（`cast_face` / `scene` / `sheet` / `golden`）分别聚合，再给 `all`：
- `q1_identity`：postflight Q1 状态计数（pass / fail / na / untested）；`cos_mean` = evidence `per_face[].sim` 的均值（没有数值 sim 则 null）。
- `q9_review`：Q9 状态计数；`untested_ratio`（服务排队 / 未跑的比例）。
- `anomaly`：`anomaly.status` 计数 + `reasons` 非空的 take 数。
- `vlm_items`：逐条核对通过率 = `vlm.items[].ok` 为真的条数 ÷ 总条数；没有 `items` 时按 `vlm.text` 行首“符合 / 不符合”统计。
- `contract_pass_rate`：`passed`（或 `pass`）为真的 take 数 ÷ take 数。
- `hollywood`：**好莱坞质感分**（1–10，5 项：构图 composition、光线 lighting、质感 texture、表演 performance、一致性 consistency，均值为总分）。只对**已过检查**的图打：资产作业 candidates（passed / contract_ok）、金样作业 slots（passed）、已登记金样首帧（`data/pipeline/golden/<run>/epNN/SNN.json`）、阶段 A 账本 takes（passed）。
  **自动打（总调度 11-03 裁定 1c46 ①）**：`tools/pipeline/hollywood_tick.py` 由 autoflow_resident 每拍调一次（独立 tick，不碰 asset_worker 主流程）：发现新过检的图 → 低优先级队列 → **只在本地看图服务空闲（两边 /health 都 queue=0、inflight=0）时**打，每拍最多 `max_per_tick` 张，每张打前再探一次空闲，Q9 / 出图检查一来就让路。固定 rubric（`hollywood_tick.RUBRIC`，模型只回一个 JSON），走 `vlm_pool.generate`（只认本机 / 自家 gpu36 隧道）。结果追加到 `runs/<run>/metrics/hollywood_epNN.jsonl`（每张一行：file、source、episode、shot/job、scores、mean、note、raw、model、via、error、at）；失败重试到 `max_attempts`。开关 `config/pipeline/hollywood_score.json`。
  `episode_metrics` **只读这个账本**，不现场跑：没有打成的行 → null，原因写明失败行数。

#### 2.5 成功率（`success`）
- `writing.first_pass`：P1 三评委 / P2 / P3 / P4 / 补丁环 / 事实核对 / 导入 各自“第一次就过”的布尔值与尝试次数（P1 轮数 = STATE.rounds；P2–P4 看 stages[].attempt；补丁环看 agent_history 里 patch_* 条数与接受数；导入看 autoflow.log import_failed 次数）。
- `p1_judges`：轮数、每轮均分、门槛 34、是否由项目方低于门槛放行。
- `images`：按来源：`takes`、`passed`、`pass_rate`、`takes_per_pass`（= takes ÷ passed；passed 0 → null）、`preflight_blocked_attempts`（作业 log 里“preflight 不过”的次数，这些根本没出图）。
- `asset_jobs`：按 kind 的 state 计数、`attempts` 总和、首次成功的作业数。

#### 2.6 自动化比例（`automation`）
步骤表 = autoflow `stages[]`（decider：code / api_model = 系统，owner = 项目方）+ 资产作业（meta = 系统；face / scene / sheet 作业本身 = 系统，但“挑选”各算一步 = 项目方；`adopted_from` 不为空说明候选由 agent 手工出 → 该作业改记 agent）+ 2.2 的每一次介入各算一步（人工 / agent）。
`ratio = system_steps ÷ total_steps`；同时给 `by_actor` 计数。

#### 2.7 GPU 利用率（`gpu`）
- 道清单：`partition.json.lanes` 展平。
- 占用 = `lane_loans.jsonl` 里每条道 `hold / lend` → 同一条道下一次 `release / idle_release`（没有 release 的到 `expires_at` 或窗尾）；只算窗内部分，重叠合并。
- `per_lane.util = busy_s ÷ window_s`；`overall = Σbusy ÷ (道数 × window_s)`。窗 = 阶段 A 起（或本集第一次挂道 / 金样出图，取早）→ 窗尾（写作期不用 GPU，不计入分母；`window_s` 单列）。
- 注：这是“被占住的时间”，不是 nvidia-smi 的真实算力利用率；`basis` 字段写明。

### 3. 对比（`compare`）
`episode_metrics.py compare --run R --a 1 --b 2`：对两份 `epNN_summary.json` 里的关键数值逐项算 `delta`、`delta_pct` 和方向好坏（时间 / 调用 / 介入 / takes_per_pass 越少越好；通过率 / 自动化 / 质感 / 利用率越高越好），两边任一为 null → `n/a`。HTML 一页：两列 + 差值列 + 颜色（好 / 坏 / 不适用）。

### 4. 已知空缺（ep01 回溯时）
- `metrics/ep01.jsonl` 尚未由 autoflow 落盘（§A 刚定）→ 写作段全部按 autoflow.log / autoflow.json 反推。
- 写手 / 评审包不记录模型型号 → 按 SOP 标注，不是测得的。
- 真实 GPU 算力利用率没有采样记录 → 只能用挂道 / 借道时长。
- 好莱坞质感分还没有跑过 → null，等显式触发。
- 金样阶段 B 还没按 SOP 第 9 步正式跑（golden 开关关着）；`v2_golden/takes.jsonl` 是 PROMPTFIX 11-02 的金样试跑，按 shot 归到 ep01，标 `trial: true`。
