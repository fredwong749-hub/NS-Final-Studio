# Autopilot：一部新剧怎么自动做出来

这一页写给项目方，讲四件事：
- 怎么启动一部新剧；
- 你要在哪几步点确认；
- 其余步骤系统怎么自动做；
- 以后学到新东西怎么加进系统。

整个过程不需要 Claude 在线。写剧本由写作模型（外部网关）完成；审片由本地看图模型或规则完成；出片走 6 张 3090。

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
