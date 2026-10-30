# 封板 debug：API / 剧本导入 / gpu3 链（debug-api，fredw-92 派）

## 摘要

- 测试：基线 534 通过 / 4 跳过 → 现在 **591 通过 / 4 跳过**（本轮新增 tests/test_release_debug_api.py、tests/test_sop_release_fixes.py 共 30 个用例、test_gpu_monitor.py +1，
  并按新签名改了 1 个旧测试；其余增量来自同时在改的其它会话）。
- 找到并修复 **18 个问题**：高 1（gpu3-media 路径穿越）、P0 1（D-1 S1 按整份剧本版本判）、中 8（含 3 个慢接口和前端回退）、低 8。
  另外 QA4-01 接线和 A-2 慢接口按派单完成。
- 没有改共享结构（schema 字段、目录约定、API 返回结构）。新增内容都是附加的：`s1.warnings`、owner_action `gate="source_drift"`、
  阻塞码 `script_partial_v3`。需要改共享结构的写成了下面的提案。
- 生产数据没动：import_script / s1_gate 实跑都写到临时目录，跑前跑后对 script_v2.json、s1_gate.json 做了 sha 校验，都没变。
  线上 API 只发了只读 GET。
- state_timeline.py、tools/import_script.py 按协调要求没有留下改动（source_drift 的去重放在 sop.py 的包装里做）。

## 需要重启 API 才生效

1. app.py：/api/gpu3-media 路径穿越修复（**安全，优先**）；/api/readiness、/api/sop/status 缓存；单集 SOP 视图加 source_drift 提醒
2. sop.py：D-1 S1 按集判、QA4-01 源文件漂移提醒
3. script_inbox.py、script_ab.py、owner_run.py、readiness.py、gpu_monitor.py、qwen_mailbox.py、episodes_fast.py 的修复
4. 另外：线上 API 现在**没有挂上 owner_run 路由**（`/api/gpu3/episodes/1/run-eligibility` 返回“没有这个接口”）。
   说明进程比代码旧，重启后才会有。
- 前端（store.tsx / api.ts / ImportView.tsx）由 Vite 热更新，不用重启；`tsc -b --noEmit` 通过。

## 明细

| 模块 | 测试项 | 结果 | 问题 | 修复 | 严重度 |
|---|---|---|---|---|---|
| app.py /api/gpu3-media | `renders_gpu3/..%5C..%5Cconfig%5Cscript_mainline.json`（线上只读 GET） | **失败→已修** | Windows 上反斜杠也是路径分隔符，只检查 `/` 分段里的 `..`，结果能读出仓库里任意文件（线上实测 200） | 拒绝 `\`、`:`、`.`、`..`；测试覆盖 4 种穿越写法 + 正常读镜像 | 高 |
| sop.py（D-1） | 混合版本剧本（ep01 v3、ep02 v2），S1 校验 0 + G3 已采纳 | **失败→已修** | S1 用整份剧本版本（v2）判，ep01 也被 script_not_v3 拦住 | 按集用 `episode_version` 判：v3 的集不拦，低于 v3 的集报“第 N 集剧本还是 vX”；项目级混合时报 `script_partial_v3`（“部分集仍是 v2（epX-Y）”），全部低于 v3 时仍报 script_not_v3；读不到剧本时退回旧逻辑。真实数据：ep01 的 S1 只剩 timeline_stale / g3_not_accepted / element:sound，ep02 仍有 script_not_v3 | P0（D-1） |
| sop.py（QA4-01） | 源文件导入后改过 / 文件不见了 / 重复登记 / 没有剧本时退回状态表 | 已接线 | 画布 SOP 状态里没有这条提醒 | `s1.warnings=[{code:source_drift, level:warn, text:"剧本源文件导入后又改过，需重新导入：<路径>", paths}]`，同时进「待你决定」（gate=source_drift，cli=None，不拦镜头、不改 passed），单集视图也显示。真实数据现在报 1 条：《剧本和镜头》v2.md | 中 |
| sop.py / state_timeline.source_drift | 生产 script_v2.json 里同一个 image 提示词文件登记了 4 次（旧条目 sha 已不同） | **误报→sop 侧已修** | 旧条目被当成“导入后改过” | sop.py 每个路径只看最后一条登记（与 fredw-92 的 dedupe_sources 同一口径）。`s1_gate.py` 的输出和状态表的 `changed_sources` 下次合并导入前仍会带这条误报，见提案 P2 | 中 |
| tools/import_script.py | 合并去重 sources | fredw-92 已修 | 同一源文件重复 3–4 次 | **fixed by fredw-92**（dedupe_sources + test_merge_dedupes_sources_keeping_latest） | 中 |
| tools/import_script.py | 实跑：`--script data/script_chat/…/script.md --merge-base <生产副本> --source-version v3 -o 临时 --no-timeline` | 通过 | — | 60 集 / 361 镜，替换 ep1，sources 去重后 3 条，script.md 的版本 v3、集 [1]；生产文件 sha 没变 | — |
| script_inbox.validate | 校验器崩溃 / 输出不是 JSON | **失败→已修** | 错误结果按 sha 写进缓存，同一文件以后永远拿到这条错误，“重新校验”也恢复不了 | 错误不写缓存；导入时提示“格式校验没跑成” | 中 |
| script_inbox.post_import | 两个导入同时进行 | **失败→已修** | 备份和回滚会交错，后一次可能把前一次的结果“恢复”掉 | 导入串行化，第二个直接返回 409 | 中 |
| script_inbox.post_import | 同一秒内导入两次 | **失败→已修** | 第二次的备份覆盖第一次的备份 | 文件名重名时加 `-1`、`-2` | 低 |
| script_inbox.post_import | mode 拼错（如 `mrege`） | **失败→已修** | 静默按 replace 处理（会整份替换） | 只收 merge / replace，其它 422 | 中 |
| script_inbox.post_import | merge_base 不存在 | **失败→已修** | 先备份、跑子进程，失败后 500 再回滚 | 导入前先 422，不碰剧本 | 低 |
| script_inbox 导入流程 | 正常合并 / 失败回滚 / replace 不带 --merge-base / 写日志 | 通过（新增测试） | — | — | — |
| script_inbox._current | import_log.jsonl 有一行坏 JSON | **失败→已修** | 整个收件箱 GET 返回 500 | 跳过坏行 | 低 |
| /api/script-inbox/download | 非候选、`../`、正常候选、中文文件名 | 通过 | — | 新增测试 | — |
| script_input | 草稿保存 / 覆盖 409 / 删除进 .trash / 上传编码 | 通过（已有测试） | — | — | — |
| script_ab /choices | ab_choices.jsonl 有坏行 | **失败→已修** | GET 返回 500 | 跳过坏行和非对象行 | 低 |
| script_ab /sources、/episode | 线上 GET | 通过 | — | — | — |
| owner_run | 桥返回的错误体是非对象 JSON（如 `["busy"]`） | **失败→已修** | `.get` 抛 AttributeError → 500 | 只有对象才取 `detail` | 低 |
| owner_run | 🔴 集拒绝、by≠owner 403、note 为空 422、dry_run 透传 | 通过（已有测试） | GPU 2 没有在本地拦（目前靠桥拦） | 见提案 P3 | — |
| gpu3_requests | 线上 GET；镜像回退；按镜过滤 | 通过 | 桥的 /queue 条目没有 project 字段，走桥时没法按项目过滤（走镜像时能） | 不改（桥的契约），已记录 | 低（备注） |
| readiness.gpu3_takes / gpu3_chain | takes.json 是 `[]` / 字符串 / takes 为 null / takes 里有非对象 / active 是列表 | **失败→已修** | 都会抛 AttributeError / TypeError → 500 | 都容忍，按“没有版本”处理 | 低 |
| app.py gpu3-rerender | stage 校验、video 闸门、桥不可达 502、桥拒绝 422 | 通过（已有测试 + 代码审读） | — | 没有真实发请求 | — |
| gpu_monitor | 冷启动第一个请求 | **慢→已修**（A-2） | 第一次同步采集要等 ssh（约 8 s） | 冷启动不等 ssh，ssh 那几项由后台线程下一轮补上 | 中 |
| gpu_monitor._owner / collect | 锁文件内容是 `123` / `"x"`；桥返回的不是列表 | **失败→已修** | AttributeError / TypeError，面板 500 | 容忍 | 低 |
| qwen_mailbox /tasks | 线上 5.6 s | **慢→已修**（A-2） | 最多 10 个未完成任务串行问上游，每个约 0.6 s | 改成并行，同一任务 5 s 内不再问；不可达时 reachable=false + 提示 | 中 |
| qwen_mailbox files / 下载 | `..` 路径、编码 | 通过 | — | 新增测试 | — |
| /api/readiness、/api/sop/status | 线上 1.5 s / 1.5–4.6 s | **慢→已修**（A-2） | 每次全量计算 | KeyedCache：签名（剧本、状态表、场景表、关口、造型计划的 mtime + 当前项目 + 剧本对象）变了就同步重算；签名没变但超过 10 s 时先返回旧值、后台重算；测试根（SOP_ROOT）不缓存 | 中 |
| episodes_fast | 线上 /api/episodes/summary 0.06 s；单集 | 通过 | — | 新增 KeyedCache 及测试 | — |
| 前端 store.fetchEpisodes | 新接口 5xx / 超时 | **失败→已修** | 靠匹配错误文字判断是否退回，文字里带“404”的 5xx 也会退回旧的 8 MB 接口 | `req` 的错误带上 HTTP status；只有 404 才退回；5xx / 网络错误显示“集列表加载失败，N 秒后重试”并重试 2 次（2 s、5 s）；合并在途请求的逻辑不变 | 中 |
| tools/s1_gate.py | 真实根只读查看；临时根写入 `--validator-errors 0`；`--accept "  "` 返回 2；没有剧本返回 2 | 通过 | 输出里的 provisional 按整份剧本版本算（混合时为 true），与 D-1 的按集口径不同 | 提案 P2 | 低（备注） |
| tools/s2_waiver.py | 文件缺 `waivers` 键；`--episode 0` | **失败→已修** | KeyError；第 0 集也能登记豁免 | 缺键时补上；`--episode` < 1 拒绝（只在临时 CFG 上测，没替项目方写豁免） | 低 |
| state_timeline.waived / episode_version | 只对登记的那一集、那一项生效；撤销；没写原话 | 通过（已有测试） | — | — | — |

## 提案（需要改共享结构 / 别的会话负责的文件，本轮没动）

- **P1 画布导入传版本**：`/api/script-inbox/import` 的 body 加 `source_version`（API 结构变化），转给
  `import_script.py --source-version`。现在经画布导入 `script.md` 这类文件名里没有 vN 的稿，该集版本为空，
  S1 按集判会当成 < v3。目前只能用命令行导入。
- **P2 state_timeline.source_drift 按路径只看最后一条**（state_timeline.py 归 fredw-92）：和 sop.py 用同一口径，
  消除 `s1_gate.py` 输出和状态表 `changed_sources` 里的重复条目误报（下次合并导入时 dedupe_sources 也会消掉）。
  同时可以让 `s1_gate.py` 的 provisional 也按集显示。
- **P3 owner_run 本地拒绝 gpu=2**（SOP ★2：GPU 2 永不使用）、steps 只收 frames / video / 4k。现在完全靠桥校验。
- **P4 桥 /queue 条目带 project**：这样 gpu3_requests 走桥时也能按项目过滤。
