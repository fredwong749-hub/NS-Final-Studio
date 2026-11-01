# Autopilot：一部新剧怎么自动做出来

这一页写给项目方，讲四件事：
- 怎么启动一部新剧；
- 你要在哪几步点确认；
- 其余步骤系统怎么自动做；
- 以后学到新东西怎么加进系统。

整个过程不需要 Claude 在线。写剧本由写作模型（外部网关）完成；审片由本地看图模型或规则完成；出片走 6 张 3090。

> ⤴ 2026-11-02 DISTILL（L-102 / ITERATION_PROTOCOL §G1）：上面这句是目标，还没有完全做到。现在哪些环节仍要 Claude 判断、怎么替换，见下面 §0；§0 的数字由代码生成，以 `data/autopilot/coverage.json` 为准。§1–§6 写的是 10-31 版 run.py（P4-P5…P11-P12 走 iterate_loop），剧本导入以后的实际生产已经改走 §0 的编排器。

## 0. 统一编排器与“谁在判断”（DISTILL 11-02，规则 K-OPS-X01–X05）

**一个编排器**：`tools/autopilot/flow.py`，入口仍然是 `run.py`。每集一个状态机，状态从真实记录现推（producer 登记表、作业清单、ready_episodes、night 状态、成片文件、成片分），不另存副本。

| 命令 | 做什么 |
|---|---|
| `run.py status --all` | 全局进度 + 卡点，同时写 `data/autopilot/flow/status.json`（界面直接读） |
| `run.py flow --episode 4` | 这一集逐段状态、下一步命令 |
| `run.py flow --episode 4 --dry-run [--with-producer-dryrun]` | 冷启动演练：把这一集当成新剧本走一遍，不出图、不调付费 API，列出所有要人或 Claude 介入的断点 → `data/autopilot/flow/drill_ep04.json` |
| `run.py coverage [--episode 4]` | 无 Claude 覆盖率 → `data/autopilot/coverage.json` |
| `run.py policy-check` | 策略和代码是否一致、引用的文件是否存在（退出码 0 = 通过） |
| `run.py guard [--apply]` | 策略守卫：系统暂停超过 180 秒就报警（`--apply` 才自动恢复） |
| `run.py approve-delivery --episode 4` | 项目方确认交付 |

**新剧本从页面启动（r2，项目方 02:3x）**：`#/script-create` 填 P0 Brief（现有 `POST /api/story-runs`），或 `run.py flow-start --brief <P0.json> --episode N`。flow 登记到 `data/autopilot/flow/runs.json`，`status --all` 里多一行“新剧本 …”逐段现推：故事提纲 → 写作链 P1–P4（run_chain）→ 好莱坞返修 + 评分（HOLLYWOOD r8 交付 `data/pipeline/runs/<id>/hollywood/epNN.json`：{candidates:[{name, score, invariants_pass, p4_block_zero, fact_check_zero}], spent_usd, rounds_left, staged_path, sha}，`policy.pick_import` 选导入稿）→ 导入（`imports.jsonl` 事件）→ 下面的生产段。冷启动演练 `run.py flow --episode 1 --dry-run` 从样例 Brief 开始，每个断点写负责方。

**每集 15 段**，每段的执行者都是已有工具，编排器不另起入口：

| 段 | 执行者 | 判断由谁做（现在） |
|---|---|---|
| 故事提纲 / 写作链 | 页面 + `tools/pipeline/run_chain.py`（外部写作 API） | owner 填 Brief；api_model 写、code 校验 |
| 好莱坞返修 + 评分 | HOLLYWOOD r8（基于 `tools/script_rsi/hollywood_r5.py`） | api_model；预算、选导入稿由 code；**评审噪声大时先修评审清单仍由 claude 判断** |
| 剧本导入 | `producer.py import-staged`（PRODUCER 令牌，项目方 11-01 方案 A 授权） | owner（Claude 会话会被权限系统拦下）→ 目标 code |
| 作业编译 | `episode_pipeline.py prepare` | code |
| 资产就绪 | `tools/factory/deps.py`、`sheet_intake.py`、`tools/asset_repair/repair.py` | code；**新角色设定图候选挑选仍由 claude 判断** |
| 首帧 / 尾帧 | producer 常驻 | code；**暂停超时恢复、尽力版重置、服务器代码版本仍由 claude 判断** |
| 看图闸门 | 生成契约 + 本地看图（`config/vqa.json`） | code + local_model；**换版首批复核、漏检入回归集、master_review 签字仍由 claude 判断** |
| 视频 / 视频检测 | night 常驻（Pika）+ `score_clip.py` + 视频看图 | code + local_model |
| 合成 / 后期 / 成片评分 | `night.finalize` → `tools/director/finish.py` → `film_score.py` | code |
| 交付闸门 | K-EDT-817 选后期版或原版 + 项目方看片 | code + owner |

**覆盖率**（2026-11-02 r2 起，`data/autopilot/coverage.json`）：51 个判断点（含写作段），现在 code 32、local_model 3、api_model 3、owner 4、claude 9（17.6%）；按 plan 全部落地后 claude 0。r2 目标 claude ≤ 4。交付闸门改为预览棘轮：成片分 ≥ max(30, 该集历史最好 − 1)，口型重出单 0，视线 A1 无零分，代码过了再等项目方看预览确认（gates.delivery_gate）。暂停按总调度 D5 口径：每次 pause 带 reason_kind / expires_at，运维暂停到点自动恢复，显式暂停超过 180 s 只告警（policy.pause_decision 唯一实现）。

**策略层**：`config/policies/`（resources / handback / budget / retry / gates / deploy，56 项）是阈值的单一来源。每项都写了出处（L 编号或规则号）、由哪段代码执行、状态：
- code_reads：代码直接读这一项；
- drift_checked：代码里另有一份常量，`policy-check` 逐项比对；
- pending：还没有代码执行，写了方案和负责人。

改阈值时要两边一起改，否则 `policy-check` 不通过。

**判断清单**：`config/policies/decisions.yaml`，记录今晚总调度和各 agent 做过的 52 个判断（数字以 coverage.json 为准）。每条都写了“现在由谁判、目标由谁判、代码化方案”。

**数据快照**：data/ 不进 git，其中决策 / 配置类文件（配方选择、设定图选择、驳回、ready_episodes、交还记录、takes 当前指针等，清单 `config/policies/state_files.yaml`）由 `tools/autopilot/state_snapshot.py` 在每次 cut 时打快照到 `data/system_versions/<sv>/`（tar + 逐文件 sha256），回滚用 `restore <sv>`；新剧本用 `init-run <run_id>` 只从 config/ 默认值生成（K-OPS-X06）。

**新增判定 prompt**：`config/prompts/asset_sheet_inspect.md`（本地看图模型逐栏检查设定图是否完整）。原因：出图闸门把设定图当标准答案，参考图本身的缺陷它查不出来。

**还要人或 Claude 介入的地方（以 drill_ep01.json 为准，r2 起从 P0 Brief 演练）（冷启动演练 ep04，13 个断点）**：producer 的 RUN_ID 写死 series10_v1（episode_pipeline 已由 WORKFLOW 改读 config/pipeline/run.json）；producer 零点击 dryrun 走不完首帧 → 尾帧 → 视频（首帧通过后被重打分撤下、循环），退出码却是 0；尽力镜放行合成与 ITERATION_PROTOCOL §3 冲突；import_staged 还没写导入事件（目前靠 ep_hash 兜底）；以及上表粗体的 claude 判断点。完整清单 `data/autopilot/flow/drill_ep04.json`。

## 0.1 多剧并行接口（总调度 11-02 02:4x 定；策略 resources.multi_run / run_priority，判断清单 DJ-54）

项目方在 #/script-create 新建剧本时，series10 继续生产。导入新剧本只新增一个 run，不替换正式剧。项目方闸门只保留两处：填 P0 Brief、看预览确认交付。

| 对象 | 接口 | 负责 |
|---|---|---|
| run 登记表 | `config/pipeline/runs.json`：`{"primary": "series10_v1", "runs": {"<run_id>": {"priority": 0, "status": "producing", "episode": N?, "created_at", "source": "import|flow-start"}}}`；`config/pipeline/run.json` 保留为 primary 指针（兼容旧读法）；导入新剧本 = 追加一条（priority 默认 10） | WORKFLOW |
| 导入事件 | `data/autopilot/imports.jsonl` 每条必须带 `run_id`；episode_pipeline 按 run 分别准备（作业写 `data/pipeline/runs/<run>/assets/first_frame_jobs.json`），ready 写 `data/autopilot/runs/<run>/ready_episodes.json`（primary 兼容旧路径） | WORKFLOW；import_staged 写事件 = DEBUG-RSI |
| producer | 对象 / 租约 / 账本 id 加 run 前缀 `<run>/<kind>:<shot>`（primary 兼容无前缀）；登记表、attempts、master_rejects 按 run 分文件 `data/producer/runs/<run>/`（primary 暂留 `data/producer/`）；渲染目录 `data/renders/<run>/epNN/SN/`（primary 仍是 `data/renders/`）；派单按 `resources.run_priority`：高优先级 run 有 ready 对象时，低优先级不派；不打断在途作业 | DEBUG-RSI |
| 服务器工厂 | inbox 目标状态按 run 分：`inbox/<run>/state-<seq>.json`（作业表 sha、holds、rejects、ready、min_code_sv）；`expected_refs` 按 run；outbox manifest 带 `run_id`；本地库按 sha 共用（相同资产不重复存）；交还条件按 (host, run) 记，preflight dryrun 按 run 跑 | FACTORY |
| 导入稿路径 | primary 仍是 `data/import/script_v2.json`；新 run 是 `data/import/runs/<run>/script_v2.json`（导入接口按 run_id 写，备份也按 run 分开放）。`image_jobs.rebuild_first_frame_jobs(run)` 按 run 读对应的导入稿 | 导入写入：DEBUG-RSI（import_staged）；image_jobs：AUTOPILOT / RSI |
| 派单 only | `tools/netfix/dispatch.py` 计算 only / 分区时认 `<run>/<kind>:<shot>` 前缀；分区按 (run, 集) 划分，新 run 默认跟随正式剧的分区规则，只用空档 | NETFIX |
| 过渡期 | 在 producer 和 dispatch 能认 run 前缀之前，primary 继续用不带前缀的旧格式，只有非 primary 的 run 带前缀（不影响现在的生产） | WORKFLOW / DEBUG-RSI / NETFIX |
| 编排器 | `flow.py` 读 `runs.json`：primary 走逐集状态，其余 run 走“新剧本”行；status.json 的 `new_runs` 带 priority | DISTILL |
| 预算 | 每部新剧：每集 ≤ $3、整部 ≤ $15（budget.writing_per_run），超出即停；追加预算才问项目方 | DISTILL / HOLLYWOOD |

## 1. 启动

在项目根目录运行。

**从故事提纲开始**（P0）。brief 的格式照 `config/pipeline/examples/P0_brief.json`：

```
.venv/Scripts/python.exe tools/autopilot/run.py start --episode 4 --from P0 --brief data/briefs/ep04.json
```

**剧本已经有了**，从分镜开始（P3）：

```
.venv/Scripts/python.exe tools/autopilot/run.py start --episode 4 --from P3
```

**演练**：不出片、不调付费接口，闸门自动通过，用来确认整条链能走通：

```
.venv/Scripts/python.exe tools/autopilot/run.py start --episode 3 --from P3 --dry-run --auto-approve
```

**中断或停在闸门之后**：

- 查看进度：`run.py status --run-id <id>`
- 继续执行：`run.py run --run-id <id>`

每一步都会把状态写进 `data/autopilot/<id>/`，所以随时可以停，再运行就接着做。

**可选开关（默认关，尽量自动）**：
- `--gate-storyline`：storyline 写完先停下，等你看过再继续。
- `--gate-outline`：单集大纲写完先停下。

看完后用 `run.py approve --run-id <id> --gate storyline`（或 `outline`）放行，再 `run`。

## 2. 系统自动做的事

| 段 | 做什么 |
|---|---|
| P0→P3 写作 | 调用 `tools/pipeline/run_chain.py`，按链条契约 `config/pipeline/chain.yaml` 逐段写，有预算上限和断点续跑：提纲 → storyline → 单集大纲 → 剧本。每次都会带上系统知识包（`config/recipes/writer_knowledge.md`）。 |
| P3→P4 分镜自检 | 剧本交上来后，系统先做格式校验、台词逐字检查、人物锚点短语检查，再检查 Shot Spec 缺不缺字段。不过的话，逐镜把错误带回给写作模型，只重写有问题的那几镜；集级问题才整集重写。最多 2 轮。稿件会盖写作规则版本章；盖了 sysimpl-v2 的新稿，时间轴和分拍槽位缺项会直接拦下，不派单。 |
| P4→P5 资产 | 缺身份参考的角色会出四栏设定图候选。 |
| P5→P6 首帧 | 没定稿首帧的镜头会出首帧候选。 |
| P6→P10 出片 | 按镜头类型自动选配方（对白近景、走动全身、双人、长镜头等），编译出 ComfyUI 参数，分到 6 张卡上出片。出片后自动审片打分，不合格就按规则表重出：换种子 → 改参数 → 换配方。每镜每版最多出 3 次，还不行就标“待项目方”。最后合成整集。 |
| P10→P11 审片 | 审片模型看每镜的接触印样，输出判定；不合格的镜头再重出。完成后生成审片页 `data/review_pages/<集>/index.html`，并自动打开。 |

## 3. 你要点确认的地方（只有这三处）

> 2026-11-01 起（项目方原话：“自动执行对应制作,人类不应该点,坏了,系统自动做”，选方案 A）：整季剧本导入以后，首帧 / 尾帧 / 视频 / 合成由**制作监督**自动推进（见 §7）。首帧、尾帧过了生成契约就自动设为当前，不再等你在画布上逐镜锁定；frames 闸门只在你想手动改某一镜时用。characters（挑身份参考）和 delivery（看成片）仍然是你的。

> 2026-10-31 起：界面需要登录。你登录后，下面这几处都是**点一下即生效**（记在你的账户名下，可撤销的给 10 秒撤销），不再勾“我是项目方”、也不再填原话（项目方原话：“系统是在我 login 的……你不需要每个东西都要打上一个字”）。所有操作自动记进 `data/audit/`，在界面“工具 → 操作记录”里能看。

| 闸门 | 什么时候停 | 你做什么 |
|---|---|---|
| characters | 有新角色还没有身份参考图 | 资产中心“挑设定图”里点“选这张”。选定后系统自己就能发现，再运行 `run` 即可。 |
| frames | 有镜头的首帧还没定稿 | 在画布上锁定每镜首帧。锁好后运行 `run`。 |
| delivery | 整集出完、审片页已打开 | 看审片页。没问题就运行 `run.py approve --run-id <id> --gate delivery`，然后 `run`。某镜不满意，就照审片页上的说明标记“重出”。 |

除这三处外，下面几类情况系统也会停下来等人：
- 写作方两轮仍没补齐格式：整集停在 P3-P4，缺口清单写在 `data/autopilot/<id>/writer_requests.md`，由总调度转给写作方。
- 花钱或许可类决定。
- 推翻旧决定的事。

## 4. 学到新东西，怎么变成系统的一部分

所有经验都存在 `knowledge/rules/*.yaml`，每条一个结论，写清这几项：
- 触发条件；
- 动作或参数；
- 证据和置信度；
- 日期；
- 属于哪一段（link）。

配方参数、自动重出规则表、写作模型的知识包、审片模型的提示词，都从这里生成，或者以这里为准做校验。

**加一条新规则：**
1. 在对应文件末尾加一条，格式见 `knowledge/schema.yaml`。例如审片阈值加到 `review.yaml`，重出阶梯加到 `loop.yaml`，写作格式要求加到 `writer.yaml`。
2. 运行 `.venv/Scripts/python.exe tools/knowledge/compile.py`。它会先校验，再重新生成下游文件。
3. 想看某一集在新规则下有没有不一致：`compile.py --episode 2`。

**自动学到的参数：** 出片 Loop 会把被证实有效的调整写到 `config/recipes/learned.yaml`。同一调整成功 5 次、成功率 ≥80% 就自动生效，同时追加到 `docs/ep02_iter/LEARNED_SPECS.md` 的 D 节。要撤回，把那条的状态改成“待验”。

**规则草案：** `knowledge/inbox/` 里放的是待确认的规则（由归因工具自动产出）。确认后把它移到 `knowledge/rules/`，原稿留在 `knowledge/inbox/confirmed/`。

**改了人物表登记会怎样：** 人物表里的 EN外貌短语、VOICE 声线短语一旦修改，资产版本账本（`registry:<角色>`）会记下新版本。用到旧登记的视频版本会自动标成“依赖已更新”。出片 Loop 下一版发现计划哈希变了，就会重出这些镜头。

## 5. 现在的限制

- Ref2VA、两段式这类配方要等 API 重启后才能真跑（重启后加 `--graph-passthrough`）。演练时按“已接通”处理。
- 本地看图审片会占用出图那张卡（gpu33:0）。不开时用规则审片兜底。
- 节奏已按你的原话“把节奏改得稍微快一点”定为规则（K-EDT-I01）。其他风格类决定仍然留给你。
- 旁白音色：规则要求独立的 narrator 音色、年轻都市感、语速自然、时长不超过所在镜头。具体用哪个音色，要等你在试听候选里挑定。

## 6. 总表：每一段由谁负责，哪里还要人

“负责代码”列的都是本仓库路径；“规则”列是 `knowledge/rules/` 里这一段（link）的条目，`index.json` 里按 link 统计。每个角色具体怎么做，见 `docs/playbooks/<角色>.md`；也可以运行 `run.py roles` 打印“判断步骤 → 代码 / 提示词 / 闸门”的明细。

| 连接 | 做什么 | 负责代码 | 判断由谁做 | 需要人吗 | 手册 |
|---|---|---|---|---|---|
| P0-P1 / P1-P2 / P2-P3 | 提纲 → storyline → 单集大纲 → 剧本 | `tools/pipeline/run_chain.py`，配合 `config/pipeline/chain.yaml` 和 `prompts/<link>.md` | 写作网关，按分段 prompt 和知识库条目写 | 可选闸门 storyline / outline，默认关；预算 | CHAINSPEC |
| P3-P4 | 剧本 → 分镜 / Shot Spec | `tools/autopilot/writer.py`、`services/recipes/ns_recipes/spec_import.py` | 代码校验，写作网关逐镜返修 | 两轮仍不过时交写作方 | PROMPT、CHAINSPEC |
| P4-P5 | 资产：身份参考 | `tools/ab/char_sheet_qi21.py`、`tools/identity_metric.py`（排序） | 代码只出候选并排序 | **characters 闸门**：挑身份图 | CONSIST |
| P5-P6 / P4-P6 | 首帧 | `POST /api/shots/{id}/frame-jobs` | 代码 | **frames 闸门**：定稿首帧 | CONSIST |
| P4-P7 / P6-P7 | 选配方，编译 H3 提示词和图（series10 默认基底 Pika Flex = `i2va_pika_flex`，由 `recipe_choice.json` 指定；overlay 禁用时 `compiler.blocked_swap` 换替身并记进计划，K-REN-301 11-01 修订） | `services/recipes/ns_recipes`（selector / compiler / lint） | 代码，依据规则 | 无 | ARCH、PROMPT |
| P7-P8 | 出片 | `tools/iterate_loop/loop.py`，API `video-jobs`（含 recipe_plan） | 代码（6 道分配） | 开新实验、许可登记 | ARCH、LAB、WFLIB |
| P4-P9 / P8-P9 | 声音 | `services/post/ns_post`、`tools/ab_voice_fix.py`、`tools/voice_convert_shot.py` | 代码回听和度量 | **挑音色**（旁白 narrator 等） | VOICE |
| P8-P10 / P9-P10 | 合成与剪辑 | `tools/assemble_episode.py`（loop 收版时调用） | 代码，按剪辑规则 | 无 | FIX |
| P10-P11 | 审片 | `tools/ep02_director/review.py`、`tools/autopilot/director.py`、审片页 | 机器指标，加审片模型（本地 VLM / 网关 / 规则兜底） | 置信度低的镜头人工复看 | DIR、UIRSI |
| P11-RETRY | 重出与归因 | `tools/iterate_loop/rules.yaml`（由知识库生成）、`tools/pipeline/attribute_bug.py`（`run.py report-bug`） | 代码，按规则阶梯；归因是确定性代码 | 3 次仍不过的镜头；规则草案确认 | DIR、CHAINSPEC、ARCH |
| P11-P12 | 交付 | `run.py approve --gate delivery` | — | **delivery 闸门** | UIRSI |

新到工作流时，运行 `run.py learn-workflows --dir <目录>`（WFLIB）。

## 7. 制作监督（PRODUCER）：剧本导入以后自动做到成片

> 项目方原话（11-01，经总调度）：“http://localhost:5173/#/script-create?run=series10_v1 自动执行对应制作,人类不应该点,坏了,系统自动做”。他选了方案 A：常驻服务、阶段推进不再让他点；删除 / 花钱 / 推翻旧决定仍问他。规则 **K-OPS-A01**（`knowledge/rules/asset_ops.yaml`，检查 = `tests/test_producer.py`）。

**它是什么**：`tools/autopilot/producer.py serve`，开机自启（`ops/autostart/laptop_autostart.ps1` 第 4 段），每 20 秒一轮：

1. **看状态**：每个对象一条链，状态全部从真实记录现推（不另存副本）——剧本 P4 校验报告 → 系统剧本 → 生成契约 preflight → 每镜 `takes.json` 当前首帧 / 尾帧及其 postflight → VIDEO10 的 `video/state_<host>.json` → `config/voices.json` 演员表 → `data/music/series10/epNN.wav` → `data/episodes/series10/epNN_v1.mp4` → 审片页。状态只有六种：等前一步 / 排队 / 进行中 / 已通过 / 没过 / 尽力。
2. **派活**：依赖过了就派。首帧 / 尾帧走唯一出图路径（K-REN-134：`ns_agent.frame_job` + `ns_render.unified_frame`，preflight 不过不提交），每条**空闲**出图道一个（道上有别人的任务就让道；gpu36:2 只给长视频；gpu33 GPU2 不用）。每个任务带 `comfy_tag`（agent = PRODUCER）。出完图立刻放道，契约打分在 CPU 线程里算。视频由 VIDEO10 的 `night.py` 按集出；一集每镜首尾帧都定下（含“尽力”镜）时，监督自动写 `night_control.json` 的 `force_eps` 放行，不再等人写。
3. **自己修**：内容不过 → 第 2 次换 seed → 第 3 次换参考（双人镜两张脸各占一槽；单人镜再换 seed）→ 还不过就取契约分最好的一版设为当前，标“尽力”、**不进合成**、写一句人话原因。隧道断 / 502 / 显存不够 / 缓存文件缺失 / 超时算基础设施错误：退避（30 s 起翻倍，≤10 分钟）+ 换道，不算次数。preflight 不过不提交，30 分钟后自动重查；缺你挑的身份参考 = 你的闸门。
4. **不撞车**：每个对象一个租约文件（`data/producer/leases/`）。ASSETMASTER `frames_v2.py`、VIDEO10 已派的集、画布任务队列里正在排的这一镜，都当别人的租约，不重复提交。

**你在哪看**：`#/script-create?run=series10_v1` 的“整季进度”下面多了“自动制作中”面板：每集一句话，点开是每镜首帧 / 尾帧 / 视频的状态、在哪条道做、第几次（n/3）、为什么重出 / 为什么标尽力；每集的声音 / 配乐 / 合成 / 审片页在等什么。只有你的事才会出现“要你处理”卡片（同时写进 `docs/overnight/morning_decisions.md`）。原来页头的“继续写 / 接着写到…”收进“⋯ 手动插队 / 重做”，没有删。

**暂停 / 继续**（你的覆盖）：面板右上角“暂停 / 继续”，或 `POST /api/producer/pause|resume`，或 `producer.py pause|resume`。暂停后不派新活，在跑的跑完。

**文件**：登记表 `data/producer/registry.json`（GPUVIEW 渲染任务中心读同一份）、只追加日志 `data/producer/log.jsonl`、心跳 `data/producer/heartbeat.json`、控制 `data/producer/control.json`（`paused`、`hold_lanes`、`workers.frames = producer|off`、`workers.video = VIDEO10|producer`、`only`）、尝试账本 `data/producer/attempts.json`（只记监督自己派过的尝试）、闸门 `data/producer/gates.json`。

**演练**（不碰 GPU）：`producer.py dryrun`（一镜零点击走完首帧 → 尾帧 → 视频）、`producer.py dryrun --inject-fail`（注入 502 和连续不过，看阶梯）。

**还没自动的**：剧本导入的最后一步（`/api/script-inbox/import`）现在只认 `by=owner`，监督不冒用你的名字；新一季要导入时监督会停在“导入”并写明原因，等总调度给导入接口加一个系统身份（经你授权的自动导入）。

**和原有各 loop 的交接**：ASSETMASTER 的 `frames_v2.py` 跑完当前这批后不再起新批，剩下的首尾帧由监督接；VIDEO10 的 `night.py` 继续按集出片，等它退役时把 `workers.video` 改成 `producer`，监督每轮直接调它的 `loop_once`；VOICE10 / BGM10 的产物一出现，监督就自动把对应集往合成推。

## 8. 在哪里跑：服务器常驻（2026-11-01 17:00 起默认，K-OPS-W07）
- 制作监督（producer）和视频夜跑（night.py）在两台服务器上各跑一套，只管本机负责的集（gpu33：ep01/03/05；gpu36：其余；gpu33 的 GPU2 是坏卡，永远不用），直接调本机 ComfyUI，不经过笔记本隧道。笔记本上的 producer 处于 `paused_by=SERVER_RESIDENT`，night.py 不跑。
- 笔记本是控制面：改代码 → `tools/autopilot/resident_sync.py loop` 自动推到服务器并热重启；结果每 20 分钟并回，画布和审片页照常看。推送 / 拉回都按文件清单比对、分批、断连重试，截断文件不覆盖（K-OPS-W02）。
- 报警（K-OPS-W06）：服务器上 GPU 空闲但有活超过 10 分钟、producer / night 心跳停，写 data/qa/alerts.jsonl，监控看板 :8810 的“报警”区显示；笔记本隧道由 infra_watchdog 看门狗自动重建（K-OPS-W05）。
- 配方：series10 重出默认 Pika Flex（`i2va_pika_flex`，项目方 11-01 ~16:20“改用 Pika Flex”）；脸红类描述的镜由 flush_risk 换回 `i2va_pdd2`（K-REN-301）。

## ⤴ 连接根治（NETFIX 2026-11-01 22:3x，总调度 fredw-2b 派；规则 K-OPS-N01 / N03 / N04 / N05）
项目方原话：“gpu连接是大问题,现在全部修复连接问题”。
- 隧道：tools/netfix/tunnel_supervisor.py 一个进程负责全部转发，每台服务器一条 ssh 挂多个 -L，指数退避；跳板不通时不起 ssh，恢复后立刻重连（注入实测恢复 14 s，验收线 60 s；日志在 data/netfix/inject/）。ops/autostart/tunnel*.sh 已退役，只调用 ensure。保活：计划任务 NS-Studio-TunnelSupervisor 每 5 分钟跑一次，登录时 laptop_autostart 也会拉起。看门狗在监管进程在岗时只报警、不修。
- 派单：每台机器只派本机的出图道。分区写在 config/netfix/partition.json：gpu33=[1,3,5,7]、gpu36=[2,4,6,8,9]、laptop=[10]；视频 ep10 归 gpu36。control 由 tools/netfix/dispatch.py 计算：only = 分区 ∩ data/autopilot/ready_episodes.json，交集为空时设为 ["__none__"]；服务器的暂停状态跟随笔记本全局暂停，快照在 data/netfix/laptop_ctrl.json。
- gpu33 看图：经 gpu36 内网入口 10.0.0.36:8870（tools/netfix/lan_proxy.py，只认 10.0.0.33），不经跳板。
- 跳板断时：服务器上的 producer / night / 看图都不依赖跳板，照常生产。笔记本这边，监管进程状态变为 relay_down，界面显示“服务器在自主生产、最后一次同步 xx 分钟前”，数据取自 data/netfix/net_status.json 的 relay.down_since_t 和 servers.<h>.last_pull_t。跳板恢复后，隧道 60 s 内全部恢复，resident_sync loop 下一拍自动并回（只拉 json 和当前版本图，大文件按需拉）。
- **跨机接手（work stealing）备用方案**：总调度 23:0x 决定先不做，`partition.json` 里 work_stealing 为 false。将来要做，只能按下面的两阶段交接，由笔记本居中协调。
  1. 前提：笔记本同时连得上两台服务器，并且被接手的集里一个对象都还没开始（没有 attempts，也没有租约）。
  2. 撤：把该集从 A 的分区里去掉，执行 `dispatch.py server-control A --write`。等 A 的 producer 下一拍心跳里 only 已不含该集，并确认 A 的 `data/producer/leases/` 里没有该集的对象。
  3. 给：把该集写进 B 的分区，partition.json 记下依据和时间，然后执行 `server-control B --write`。
  4. 并回：merge_pull 按新归属收文件。
  任一步跳板断开，就停在“两边都不派”的安全侧，不会两边重复派单。粒度只能是整集，不能按对象拆。
- **8871 收编**（23:0x）：VQAGATE 的看图隧道 8871 → gpu36:8870 已并入 gpu36 主连接，`tools/vqa/tunnel.ps1` 退役，现在只调用 ensure。收编前确认过：服务 queue=0，最后一次看图在 172 s 前，8871 上没有在途连接。
- **临时覆盖（23:4x，K-OPS-N06）**：服务器缺资产期间，由笔记本经隧道代派两台服务器的分区，服务器 only=__none__。哪台 `data/autopilot/assets_ready.json` 里 ready=true，那台就先进入 draining，再交还给服务器自己派单。当前模式看 `data/netfix/net_status.json` 的 dispatch_mode。
