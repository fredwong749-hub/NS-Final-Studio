# 封板 debug 审计 · 笔记本侧（audit_laptop）

> 生成：2026-10-30 约 20:40。只读审计：未改源码、未提交、未导入、未触发渲染 / gpu3 / Qwen 任务。
> 范围：`D:\NS-Final Studio` 的 Python 服务 + React 画布。任务 / 需求 / 文档的对账另见 `docs/release/task_reconcile.md`，本文件只写这次实测发现的问题，不重复那份的内容。
> 严重度：**P0** = 阻塞封板｜**P1** = 封板前应修｜**P2** = 之后再修。负责方：canvas-frontend / api / compiler/agent / writer-tools / post / docs/config。

## 0. 摘要

| 检查 | 结果 |
|---|---|
| `pytest -q`（根目录，testpaths=tests） | **534 passed, 4 skipped**，136 s，0 失败。测试没有改动任何已跟踪文件 |
| `services/canvas_api/tests`（不在根 testpaths 里） | 不设 PYTHONPATH：5 个文件收集失败；设 `PYTHONPATH=.`：**3 failed / 19 passed / 1 skipped** |
| `npx tsc -b --noEmit` | 0 错误 |
| `npx vite build`（输出到临时目录） | 成功。232 个模块，主 chunk 415 KB（gzip 131 KB） |
| API :8800 GET 探测（48 个 URL） | 没有 5xx；4 类 404（见 §3）；6 个接口超过 1 s；**正在运行的进程比代码旧**（缺 owner_run 路由） |
| 流水线空跑 ep01/ep02（parse → compile_shot → build_spec/assemble/validate → state_timeline.build，全在内存里） | 13 镜 0 异常，spec 校验 0 问题；timeline 1.1 s；跟磁盘上的 timeline 比，stale_inputs=[] |
| 未提交改动 | 已跟踪文件改了 101 个（+6701/−2518），暂存了 2 个删除，未跟踪路径约 120 个；仓库只有 2 次提交（初始快照） |

共 **P0 3 条、P1 15 条**，见各节表格。最后一节是建议的封板顺序。

---

## 1. 工作区 / git 卫生

| # | 问题 | 严重度 | 证据 | 负责方 |
|---|---|---|---|---|
| G-1 | 多个会话约 20 小时的改动全部没提交：已跟踪文件改了 101 个，另有约 120 个未跟踪路径（新 API 模块 13 个、新测试 26 个、新工具 14 个、前端新组件 / CSS 15 个）。HEAD 还是 `e614fee` 初始快照。不提交就拿不出"一个完整版本"，出问题也没法回滚 | **P0** | `git status --short` 共 225 行；`git log --oneline` 只有 2 次提交 | docs/config（总调度） |
| G-2 | 仓库根目录下有未跟踪的 **Claude 会话记录** `为他而骚短剧/7785c2ec-….jsonl`（61 MB，含完整对话和 API 请求内容），同目录还有 `HANDOVER.md`、`Qwen剧本/`、`fong的想法 owner_quotes.md`。这些绝不能进 git，要移出仓库或加进 .gitignore | **P0** | `du -sh 为他而骚短剧` 为 61M；`grep run_adult_batch` 命中的就是这里的 jsonl | docs/config |
| G-3 | 零散 / 临时文件：`p.out` 是 cProfile 二进制输出（未跟踪）；`ominichar.jpg` 被跟踪在仓库根目录；`golden/assets/v2_work/`（73 MB）和 `v2_work_pilot2.log`、`v2_work_run.log` 未跟踪（.gitignore 里的 `golden/**/work/` 匹配不到 `v2_work`）；`ops/logs/*.log` 和 `ops/logs/pull_laptop.lock` 未跟踪 | P1 | 看 `p.out` 文件头是 marshal/pstats 格式；`git ls-files ominichar.jpg` 有输出 | docs/config |
| G-4 | `ops/laptop/` 和 `ops/sync/` 下有 5 个同名脚本，内容已经不一样了（差 17–56 行），看不出哪份是现行版 | P1 | 逐个 `cmp ops/laptop/X ops/sync/X`，5 个全部不同 | docs/config |
| G-5 | 换行符来回改：新增的 `.gitattributes` 规定 `* text=auto eol=lf`，但工作区还有 32 个文件是 CRLF（git 提示 "CRLF will be replaced by LF"）。忽略空白后 diff 从 +6701/−2518 变成 +6605/−2422，约 96 行是纯换行噪音；`tools/gpu_grab.py` 等文件的 diff 里混着换行改动 | P2 | `git diff --stat` 与 `git diff -w --stat` 对比 | docs/config |
| G-6 | 金标准夹具被重新生成了：`tests/fixtures/t06_golden/prompts_before.json` 改了 1203 行（`last_prompt` / `qwen_last` 现在带触发词前缀，例如 `hh12clear，图1是…`）。test_t06_bible / test_t08 能过，只是因为基线跟着代码一起改了。这是行为变化，TASKS T06 写的"0 差异"已经不成立 | P1 | `git diff tests/fixtures/t06_golden/prompts_before.json` | compiler/agent |
| G-7 | 剧本源文件 `script play lib/为他而骚（image提示词） v2.md` 在工作区被改了 6 行。按分工，剧本只能由 kimi 会话写入；需要确认是谁改的、有没有授权 | P1 | `git status` 显示 ` M "script play lib/…v2.md"`；timeline 的 `source.changed_sources` 列出 2 个 v2 源文件 sha 已漂移 | docs/config |
| G-8 | `tools/run_adult_batch.{cmd,ps1}` 已删除（已暂存），但还有地方引用它：`docs/MORNING_DECISIONS.md:16`（还写着"仍可自己启动"）、`docs/gpu_grab.md:66`、`tools/gpu_grab.py:65`（进程名正则）、`tools/render_batch.py:116`（提示文字） | P2 | `grep -rn run_adult_batch` | docs/config |
| G-9 | 有一个可清理（prunable）的 git worktree：`/home/fredw/orca/workspaces/NS-Final Studio/sablefish` | P2 | `git worktree list` | docs/config |
| G-10 | 有两个孤儿 bash 进程（PID 19356 / 28952，15:34 启动），每 90 s 轮询一次 Qwen 任务 `20261030T023440-50611743`。信箱里已经没有这个任务（返回 404），这个循环永远不会结束 | P2 | `Win32_Process` 命令行；`GET /api/qwen/tasks/20261030T023440-50611743` 返回"Qwen 信箱没有这个任务" | writer-tools |

## 2. 测试与构建

| # | 问题 | 严重度 | 证据 | 负责方 |
|---|---|---|---|---|
| T-1 | `services/canvas_api/tests` 不在根 pytest 的 testpaths 里（`pyproject.toml:28 testpaths=["tests"]`），所以"534 passed"并没有覆盖 gpu3 桥。直接跑时缺 PYTHONPATH，5 个文件报 `ModuleNotFoundError: ns_canvas` | P1 | `pytest services/canvas_api/tests` | api |
| T-2 | canvas_api 有 3 个测试失败：`test_rules::test_explain_and_cache` 和 `test_rules::test_errors` 期望 200/404，实际 502；`test_runs::test_run_progress_cancel` 期望 200，实际 409（进程已死的 `gpu.lock.gpu1` 没被当成空闲）。根因判断是 Windows 平台问题：`rules.py:86` 的 `subprocess.run(..., text=True)` 没传 `encoding='utf-8'`，子进程用 cp1252 打印中文会失败；pid 存活检测也是 POSIX 写法。桥部署在 Linux 上，实际影响小，但应该把这些测试标成只在 Linux 跑，或者补上 encoding | P2 | 同左；`ns_canvas/rules.py:86` | api |
| T-3 | `ns_canvas/rules.py:38` 的 `"\|"` 是无效转义，会触发 SyntaxWarning（以后的 Python 版本会直接报错）。改成 `"\\|"` 或 raw 字符串 | P2 | pytest 的 warnings summary | api |
| T-4 | 4 个测试被跳过，需要环境变量 `NS_GPU3_PARSER` 或 `NS_QA_DATA=1`。也就是说，parser 对齐和 renders 数据审计默认不跑 | P2 | `pytest -rs` | api |
| T-5 | 前端 tsc 和 vite build 都通过；`apps/web/src` 里没有 `as any`，也没发现没被引用的组件或 API 模块 | — | — | canvas-frontend |

## 3. API（:8800，只发了 GET）

| # | 问题 | 严重度 | 证据 | 负责方 |
|---|---|---|---|---|
| A-1 | **运行中的 API 比代码旧**。uvicorn（PID 37672）20:10:25 启动，没开 --reload；之后 `app.py`（20:21）、`owner_run.py`（20:21）、`script_chat.py`（20:22）、`gpu_monitor.py` / `script_inbox.py`（20:13）都改过。`/openapi.json` 里没有 `/api/gpu3/episodes/{ep}/run` 和 `/run-eligibility`，可前端 `OwnerRunPanel.tsx:61,71,81` 在调它们，所以"按集渲染"面板现在会 404。封板前要重启并重新探测 | **P0** | openapi 的 123 条路由里没有 owner_run；`owner_run.py:49,56` 有定义；`app.py:70-71` 有 include_router | api |
| A-2 | 慢接口：`/api/qwen/tasks` 7.1 s；`/api/episodes` 3.9 s、**8.26 MB**（旧的全量接口，新接口失败时 `store.tsx:321` 会退回来用它）；`/api/gpus` 2.5 s、`/api/render-backend` 1.5 s（每次请求都要等本机 ComfyUI :8188 超时）；`/api/readiness` 1.5 s / 600 KB；`/api/sop/status` 1.2 s。`/api/episodes/summary` 本身 0.09 s，但它报的后台构建 `build_s=5.06` | P1 | 探测脚本记录的 time_total | api |
| A-3 | `/api/boost/config` 返回 `base_url=https://api.abliteration.ai/v1`、`model=abliterated-model`。原因是 `config/director_boost_llm.local.json` 用 abliteration 覆盖了 `director_boost_llm.json` 里的 gpu3 Qwen（:18097）。项目方已经因为太贵弃用 abliteration，但画布的"导演加强·用我的模型生成"现在还会走这个付费 API | P1 | `GET /api/boost/config`；`app.py:990-994` 的 .local 覆盖逻辑 | api / docs/config |
| A-4 | `/api/looks/episodes/2` 和 `/api/looks/shots?episode=2` 都返回 404 "unknown episode: 2"，而 ep01 和 `/api/episodes/2` 正常。造型库只认 ep01，从 ep02 起画布的造型面板拿不到数据 | P1 | `ns_agent/looks.py:650` 的 `raise KeyError(f"unknown episode: {ep}")` | compiler/agent |
| A-5 | 有字段后端返回了、前端类型里没有：单镜详情里的 `gpu3_audit`、`video_gate`、`audit_override_requests`、`h3_prompt_sha256`，`types.ts` 没定义，整个 `apps/web/src` 也没用到。审计豁免和视频闸门后端已经做了，画布还没接，属于半成品 | P2 | `GET /api/episodes/1` 的 shot 键与 `types.ts` ShotSummary 对比 | canvas-frontend |
| A-6 | `/api/docs/{name}` 只提供 3 篇文档（`docs.py:15`），前端没有调用，可能是死路由。`/api/script-inbox` 和 `/api/script-inbox/` 是两条重复路由（`script_inbox.py:119-120`） | P2 | openapi | api |
| A-7 | LLM / 桥的端口各配各的：`director_boost_llm.json` 用 :18097（CPU Qwen），`script_chat.json` 和 `qwen_repair_loop.py:51` 用 :18098，信箱 :18099，桥 :15180。隧道配置应该集中到一处（比如 `tools/gpu3_tunnels.py`） | P2 | 端口 grep | docs/config |

## 4. 数据完整性

| # | 问题 | 严重度 | 证据 | 负责方 |
|---|---|---|---|---|
| D-1 | **ep01 的 S1 闸门永远过不了**。`data/import/s1_gate.json` 绑定的 sha `889fdda6…` 和当前 `script_v2.json` 的规范化 sha 一致，`g3_accepted=true`、`validator_errors=0`；但 `state_timeline.json` 还是 `provisional=True`，所有集 `s2_ready=0`，`/api/sop/episode/1` 报 `script_not_v3`（"剧本还是 v2"）。原因：`state_timeline.py:575` 用的是整份剧本的 `script_version()`，它取第一个"剧本和镜头"源文件名，得到 v2；代码里已经有按集判断的 `episode_version()`（sources 里登记 ep01 是 v3），但这里没用。结果是项目方已经确认"继续渲染"的 ep01，在 SOP 和就绪闸门上仍被拦住 | **P0** | `GET /api/sop/episode/1` 返回 `s1.passed=false`、`blockers=[script_not_v3]`；timeline `stats.s2_ready_shots=0` | compiler/agent |
| D-2 | `script_v2.json` 是拼起来的：60 集都在，但只有 ep01 来自 rules_v2 对话稿（4ee2a2，7 镜），**ep02–60 是从 v2 备份恢复的**。ep02–60 共 59 集的 `h3_prompt` 全为空，本集 `music` / `music_bgm` 也全为空；就绪检查里 ep02 每一镜的 sound/H3、配乐 cue、BGM 都不过。按"严格按剧本提示词"的要求，ep02 起都还不能交给 H3 | P1（数据状态，不是代码问题） | 逐集扫描：无 H3 的集为 2..60，无配乐的集为 2..60；`/api/readiness` ep2 的 sound / music_cue / bgm 各 6 处失败 | writer-tools（Qwen 写作，kimi 写入） |
| D-3 | `script_v2.json.sources` 有 8 条，里面有重复：同一个 chat `script.md` 出现 3 次，`image提示词 v2.md` 出现 4 次且有两种 sha；只有 1 条带 `version`/`episodes`。merge 导入每次都往后追加、不去重，`source_drift` 也会跟着重复报 | P1 | `sources` 的打印结果 | writer-tools（`tools/import_script.py` 的 merge） |
| D-4 | 源文件漂移：timeline 的 `changed_sources` 列出 `剧本和镜头 v2.md`（导入时 c8c6…，现在 64d9…）和 `image提示词 v2.md`（84a0… 变成 307f…），说明导入之后 v2 源文件又被改过 | P1 | `state_timeline.json.source.changed_sources` | docs/config |
| D-5 | 成人标记本身前后一致：规则是 `config/adult_overrides.json per_shot=false`（整集 🔴）+ 关键词 + `force_adult`，361 镜里存的 `adult` 和 `classify_adult()` 现算的结果 **0 处不一致**。ep01 7/7 是 adult，ep02–04 为 0；另有 25 个非 🔴 集因为关键词或 force 有部分镜头是 adult。问题在于还有一份独立的"露骨红标"清单（`/api/explicit-holds`，73 镜，来源是 gpu3 status.json），和 adult 字段是两套标准，比如 ep10 有红标、却没有 adult 镜 | P2（两套标准，需要写明各管什么） | 现算对比脚本；`/api/explicit-holds` | compiler/agent / docs/config |
| D-6 | `lnwan_qi` 自动补齐：361 镜里有 309 镜的 img_triggers 带 `lnwan_qi`，覆盖全部 60 集。`LORA_REGISTRY.json` 里 `lin_wan_qi_v1` 是 accepted，有 sha256；笔记本上只有 `training/…/output/lin_wan_qi_v1` 目录（已 gitignore）。另一个触发词 `lnwan01` 属于 H3 视频 LoRA，`comfy/models.lock:129` 里它的 `sha256=null`；`visual_bible.toml:107`（`detect_she_with_trigger`）、`bible.py:197`、`looks.py:174` 都把 `lnwan01` 写死了。两个触发词一个管图像、一个管视频，分工没错；问题是"林晚触发词"这条规则散在 `auto_lora_triggers.json`、`visual_bible.toml`、`models.lock`、`LORA_REGISTRY.json` 和代码常量里，至少 4 处 | P1（同一规则多处来源） | grep 结果见左 | compiler/agent / docs/config |
| D-7 | config 引用：代码里引用、但实际不存在的 config 文件只有 `config/s2_waivers.json`，它是可选的，没有就表示没有豁免，可以接受。资产 manifest 共 846 个文件引用，图片引用全部能找到；缺的 544 个都是模型文件名（`*.safetensors`，只作来源记录，本来就不在本机） | P2 | 扫描脚本 | — |
| D-8 | 密钥明文存放：`config/abliteration.local.json` 和 `director_boost_llm.local.json` 里有 API key。它们已被 gitignore（`config/*.local.json`），没进 git。既然 abliteration 已弃用，可以考虑把 key 删掉 | P2 | `git check-ignore` | docs/config |

## 5. 流水线空跑（ep01 / ep02，只读）

| # | 项 | 严重度 | 证据 | 负责方 |
|---|---|---|---|---|
| P-1 | 对 `data/script_chat/…4ee2a2/script.md` + `image提示词 v2.md` 做纯解析（`import_script`）：得到 1 集 7 镜，1 条警告（缺 ep2–60，单集稿本来就这样）。没跑 `tools/import_script.py`，因为它会写 `script_v2.json` 和 timeline | — | 空跑输出 | — |
| P-2 | 对 ep01 7 镜和 ep02 6 镜跑 `compile_shot` + `frame_spec.build_spec/assemble/validate`：0 异常，0 个 spec 问题 | — | 同上 | — |
| P-3 | `state_timeline.build()`（不写盘）耗时 1.1 s，`provisional=True`（原因见 D-1）；跟磁盘上的 timeline 比，`stale_inputs=[]` | — | 同上 | — |
| P-4 | 空跑前后 `git status` 没有变化 | — | 前后 diff 为空 | — |

## 6. 重复实现 / 死代码 / 半成品

| # | 问题 | 严重度 | 证据 | 负责方 |
|---|---|---|---|---|
| X-1 | **本机 ComfyUI 有两套调度**：一套是 `ns_orch/comfy_lock.py`（T44 的跨进程文件锁 `data/comfy.lock`，画布和编排器共用）；另一套是 `tools/gpu_grab.py`，它自己看 :8188 队列是否空闲、用进程名正则判断能不能抢卡，**不认 comfy.lock**。画布持锁期间，gpu_grab 也可能往本机 ComfyUI 塞任务 | P1 | `grep comfy_lock tools/gpu_grab.py` 无命中；`gpu_grab.py` 文件头说明 | api / writer-tools |
| X-2 | 剧本进系统有 **5 个入口**：`script_input.py`（粘贴 / 上传，存到 data/staging_input）、`script_inbox.py`（导入候选 + 校验 + 导入）、`script_chat.py`（对话写作，产出 data/script_chat/*/script.md）、`script_ab.py`（A/B 选择，写 ab_choices.jsonl）、CLI `tools/import_script.py`（含 merge 模式）。另外 `config/script_mainline.json` 和 `ImportView.tsx` 里还有一个"主线"概念。真正写 `script_v2.json` 的只有"inbox 导入 → `import_script.py`"这一条路，其它入口各管什么需要写成一页说明，或者合并 | P1 | 路由列表；`import_log.jsonl` 里的三次导入（20:10 整份、20:13 merge、20:18 merge） | api / writer-tools |
| X-3 | **abliteration 残留**（已弃用）：`script_chat.json` 的 providers 里还有它（只是不是默认）；`tools/qwen_repair_loop.py:366-400,736-737` 里 `--backend` 默认值是 `local`，help 文字却写"abliteration = 默认"，自相矛盾；`script_chat.py:240` 遇到 402 时提示"去 abliteration.ai 充值"；还有 `tools/script_chat_batch.py:85`，以及界面文字 `ScriptAB.tsx:255`、`ImportView.tsx:22`；再加上 A-3 的导演加强覆盖 | P1 | grep abliteration | writer-tools / canvas-frontend |
| X-4 | **配乐有两个解析器，规则还互相矛盾**：`h3_prompt.resolve_music()`（`h3_prompt.py:74`）在剧本没写配乐时，会把本集 BGM 英文**放进 H3**（source=episode）；`app.episode_music()`（`app.py:348`）的文档却写"不进 H3，H3 的 non_diegetic_music 保持 N/A"。后期还有第三套：`ns_post/music.py` 的 `read_edit_music/resolve_cues`。画布 `_audio()` 里的 `music` 用的是剧本中文 cue，H3 用英文。要定下唯一来源 | P1 | 同左 | compiler/agent / post |
| X-5 | CSS 层层覆盖：`main.tsx` 依次加载 `theme.css → styles.css → canvas-v2.css → canvas-v3.css → t59.css → ux-fix.css`（注释写着"最后加载"）；组件里另外加载 `t54b.css`、`assets-v3.css`、`assets.css`、`ab.css`、`gpu.css`、`people.css`。合计约 2500 行，v2、v3 两套样式同时生效，是几个会话各自往上叠出来的 | P2 | `grep "import .*\.css"` | canvas-frontend |
| X-6 | 依赖方向反了：`services/orchestrator/ns_orch/{comfy_lock,engine,executors,g2_candidates,gpu3,laptop_steps}.py` 都 `from ns_api.project_ctx import …`，编排器反过来依赖 API 包 | P2 | `grep "from ns_api" services/orchestrator` | api |
| X-7 | 默认开着的开关：`NS_TIMELINE_AUTOBUILD=1`（改造型后自动重建 timeline）；`NS_ORCH_BACKGROUND=1`（API 进程里跑着编排器后台线程，当前 `running=false`，不会自己开跑）。`visual_bible [looks] inject=false`。没发现会自动触发渲染的开关 | — | env grep；`GET /api/projects` | — |
| X-8 | 还有进程在跑：审计期间 `data/script_chat/_logs/ep02_repair.log`、`rules_v2_full.log`、`data/staging_v3/repair/run.log` 一直有写入（另一个会话正在跑 ep02 返修 / 全本）。封板前要等它们跑完，或者写明这些产出不算进本版 | P1 | 测试期间被改动的文件列表 | writer-tools |

## 7. 文档 / 任务板与现实不符（只列实测发现的，完整对账见 task_reconcile.md）

| # | 问题 | 严重度 | 证据 | 负责方 |
|---|---|---|---|---|
| R-1 | `docs/REQUIREMENTS.md:85` 的 G8 还写着"写作改由 abliteration.ai 负责，Qwen 转做 LoRA"。实际已经改回 Qwen 写（`script_chat.json` 默认 provider=qwen） | P1 | 同左 | docs/config |
| R-2 | TASKS T06 写"当前 bible_version 8aadce957ff8""360 镜 0 差异"。实际 bible_version 是 `8eabf6852ea5`，共 361 镜（ep01 现在是 7 镜），而且金标准已经重新生成过（见 G-6） | P1 | `state_timeline.json.bible_version`；stats.shots=361 | docs/config |
| R-3 | TASKS T51 写"v3 导入并过 S1 后自动重跑"。实际过了闸门也还是 provisional（见 D-1） | P1 | D-1 | compiler/agent |
| R-4 | TASKS T60 写"API 已重启"，但现在跑的进程又过时了（见 A-1）。T60 说旧的 `/api/episodes` 保留，它仍是 8 MB / 3.9 s，新接口失败时前端还会退回去用 | P2 | A-1、A-2 | api |
| R-5 | TASKS T38 的产出写的是 `data/episodes/ep01.mp4`，实际只有 `ep01_PREVIEW_未完成.mp4` 和 `ep01.timeline.json` | P2 | `ls data/episodes` | post |
| R-6 | TASKS T58 的描述写的是 abliteration.ai abliterated-model-large-v2；T02 写"被 G8 abliteration 写作取代"。两处都和现行事实（Qwen 写）矛盾 | P2 | TASKS.md 原文 | docs/config |
| R-7 | TASKS 表格行顺序乱（T25–T30 排在 T33 后面，T58 排在 T57 前面）；T36 写"167 测试通过"，现在是 534 个 | P2 | TASKS.md | docs/config |

---

## 8. 建议的封板顺序

1. 先处理工作区：把会话记录目录移出仓库或加进忽略（G-2）；清掉 p.out、v2_work、ops/logs（G-3）；然后**按区域分几次提交**（G-1）。提交前确认剧本源文件是谁改的（G-7）。
2. 等 X-8 的后台返修跑完，重启 :8800（A-1），再跑一遍 GET 探测，确认 owner_run 路由已经出现。
3. 修 D-1：`state_timeline` 和 `sop.s1_gate` 改为按集用 `episode_version()` 判断（或者请项目方明确：混合稿下 S1 按集过）。修完重建 timeline，确认 ep01 的 `s2_ready` 不再一直是 0。
4. 把 abliteration 从默认路径上清掉（A-3 / X-3 / R-1）：导演加强的 .local 覆盖、help 文字、错误提示、REQUIREMENTS G8。
5. gpu_grab 改为认 comfy.lock（X-1）；定下配乐的唯一来源（X-4）；让造型库支持 ep02 起的各集（A-4）。
6. 把 canvas_api 的测试接进根 pytest（或写进 CI 说明）（T-1），处理 T-2 / T-3 的 Windows 兼容问题。
7. 数据侧（不归 Claude 写）：ep02–60 的 H3 提示词和配乐要由 Qwen 按 rules_v2 产出，经 kimi 写入后重新导入（D-2）；导入器 merge 时给 sources 去重（D-3）。
