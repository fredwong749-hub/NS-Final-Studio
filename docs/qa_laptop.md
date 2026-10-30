# 笔记本全链路 QA（T36）

> 负责：fredw-d9 的 QA agent。只读检查 + 回归测试；不改其他 agent 的源码。
> 回归测试：`tests/test_qa_laptop.py`（未修复的缺陷是 `xfail(strict=True)`，修好后会 XPASS 报错，把对应 xfail 去掉即可）。
> 渲染数据检查默认跳过：`NS_QA_DATA=1 uv run pytest -q tests/test_qa_laptop.py`。
> API 契约检查用一份独立副本 + 独立端口（:8812，PYTHONPATH 指向副本，NS_COMFY_URL 指向不可达端口），从不 POST /render、/render-batch；data/ 没有被改动（已核对 mtime）。

## 第 1 轮 — 2026-10-30 05:45

### 总览

| 检查 | 结果 |
|---|---|
| `uv run pytest -q` | 107 通过 → 加 QA 测试后 121 通过 + 8 xfail（已知缺陷）+ 3 跳过（数据检查，NS_QA_DATA=1 时 2 通过 + 1 xfail） |
| services/canvas_api 测试（gpu3 的 T25） | 5 通过（需 `PYTHONPATH=services/canvas_api`，根 pyproject 的 testpaths 不包含它） |
| 前端 `tsc --noEmit` | 通过 |
| 导入器：60 集 × 6 镜，每镜 img/motion/sound 非空，adult 已写入，与编译器判定一致；重新导入结果与 data/import/script_v2.json 一致 | 通过 |
| 编译 360 镜（compile_shot + build_spec + validate）：未成年人护栏、风格后缀、禁用词、Leica/徕卡/无字幕重复、validate | 全部通过；问题见 QA-01/03/04/05 |
| API 契约（api.ts 用到的全部 27 个路径模板 + types.ts 必填字段，5 个样本镜头 + 全部 60 集摘要 + PUT 往返） | 全部路径存在、必填字段齐全；见 QA-09 |
| data/renders：178 镜 takes.json；active 指向的文件都存在；frame.png 与 active 首帧 sha256 一致；qc 标记的版本从未被设为当前 | 通过；见 QA-02 |
| 密钥：仓库（除 .venv/node_modules/models_cache/comfy_out）与全部日志里没有导演加强 key、CIVITAI_TOKEN、sk-/hf_/token= 形态；`config/director_boost_llm.local.json` 被 `config/*.local.json` 忽略（git check-ignore 通过）；被跟踪的 director_boost_llm.json 没有 api_key | 通过；见 QA-10 |

### 问题表

| id | 严重度 | 区域 / 负责 | 复现 | 期望 vs 实际 | 建议修复 |
|---|---|---|---|---|---|
| QA-01 | 高 | 编译器 `services/agent/ns_agent/compiler.py::_strip_triggers`（图像流水线 agent） | `compile_shot` ep21-S1（img = `hh12clear, lbrng9, lbrng9_beads，顾沉家卧室…`），可用 LoRA 为本机 ComfyUI 实际列表（剧本 10 个触发词一个都没有） | 期望：LoRA 缺失的触发词全部去掉。实际：只剥掉第一个，`lbrng9, lbrng9_beads` 留在首帧提示词中段（在 DNA 锁之后）。真实剧本 15 镜受影响：ep21-S1 ep23-S1 ep23-S3 ep25-S3 ep28-S4 ep28-S6 ep32-S3 ep37-S4 ep39-S2 ep41-S5 ep42-S3 ep42-S4 ep46-S1 ep46-S4 ep57-S4；Frame Spec 路径（`build_spec`，它复用 `_strip_triggers`）同样。PROMPT_METHOD 默认 "script"，渲染时直接生效 | 剥掉一个触发词后 `text = text.lstrip(" ，,")` 再匹配下一个；或者用 `_leading_triggers` 的分词方式整体去掉开头的触发词串。测试：`test_strip_triggers_handles_ascii_comma_space`、`test_dropped_triggers_never_reach_image_prompt`、`test_real_no_leftover_triggers` |
| QA-02 | 高 | 渲染数据 data/renders（图像流水线 agent / 渲染批次；gpu3 交接） | `NS_QA_DATA=1 pytest tests/test_qa_laptop.py -k adult` | 期望：成人镜头首帧由 gpu3 出（TASKS 规则 7），笔记本不应有当前版本。实际：20 个现判为成人的镜头在 data/renders 里有笔记本 01:24/01:38 出的 `qwen_t2i` 首帧 v1，设为当前、已复制成 frame.png，**qc 为空（从未做裸露质检）**，compiled.json 里仍是 `adult: false`（关键词补充前编译）：ep11-S1 ep16-S4 ep16-S5 ep26-S1 ep26-S4 ep27-S3 ep27-S4 ep27-S5 ep27-S6 ep29-S2 ep29-S4 ep29-S6 ep40-S1 ep40-S2 ep49-S1 ep51-S2 ep51-S4 ep53-S2 ep53-S4 ep58-S3。gpu3 按规则从 data/renders 拉“当前首帧”，会拿到这些按安全镜提示词出的旧图 | 清掉这 20 镜的 active.image（保留文件留档）并删掉 frame.png，或标记 provisional；之后 render/activate 时若当前判定为成人且 take 无 source=gpu3/owner 标记，拒绝设为当前。REPORT.md 也应把它们列成“待 gpu3” |
| QA-03 | 中 | 编译器 `CHARACTER_HINTS` / Frame Spec `resolve_characters`（图像流水线 agent） | `compile_shot` ep37-S1（`顾沉家客厅：布置完成的场地…`，空镜） | 期望：地点所有格“顾沉家/顾沉家楼下”不算顾沉入镜。实际：追加【顾沉】DNA 锁，Frame Spec 也把顾沉列为画面人物（“画面中仅两人”）。确认误判：ep21-S1、ep37-S1、ep42-S1、ep60-S1；另有 10 镜“顾沉家…，他…”顾沉确实在画面（判定碰巧正确） | 角色检测前去掉 `顾沉家`/`顾沉的(家|公寓|车…)` 这类所有格地点，再看是否另有“顾沉/他”。测试：`test_possessive_place_does_not_add_character_lock` |
| QA-04 | 低 | Frame Spec `assemble`（图像流水线 agent） | `build_spec` ep57-S3 / ep59-S2（img 触发词 hh12patent，`feet` 可见） | 期望：B7/B8 材质句只出现一次。实际：高跟描述（hh12patent 的触发词说明本身含“像抹了油一样…针形细跟…”）+ rule facts 再追加一遍 → 提示词里 `表面湿润光泽，镜面反射清晰，高光锐利` 和针形细跟句各两遍 | `rules` 拼装前过滤掉已出现在 `wear` 里的条目（与 `corr` 对 lighting 的处理相同）。测试：`test_real_spec_prompt_no_duplicate_material_terms` |
| QA-05 | 中 | Frame Spec `motion_start` / compiler `CAMERA_PREFIX_RE`（图像流水线 agent） | `F.motion_start("camera orbit 缓慢环绕她一身端庄的仪态——微笑")` | 期望：去掉英文运镜指令。实际：`CAMERA_PREFIX_RE` 要求前缀后有逗号，没有逗号时整句保留 → “camera orbit 缓慢环绕…”、“handheld follow 情感爆发镜…”作为首帧 fact 进了 spec 提示词（spec 方法下 111 镜首帧提示词含英文运镜词（img 原文没有），如 ep12-S4、ep17-S1）。同一路径还会把 motion 里“（…——…）”切开，留下未闭合的“（”（18 镜，如 ep57-S3） | 运镜前缀匹配到第一个中文字符为止（`^(camera|static|handheld|slow motion|time-lapse)[A-Za-z \-]*`），再去掉；按“——”切分前先跳过括号内的破折号。测试：`test_motion_start_drops_camera_prefix_without_comma` |
| QA-06 | 中 | 导入器 `services/agent/ns_agent/importer/script_md.py::_parse_dialogue`（fredw-d9 导入器负责人） | `_parse_dialogue('（她，仰脸）“网上学的。／为了你。”')` | 期望：一句台词，说话人“她，仰脸”。实际：先按“／”切分，引号内的“／”把台词拆成两行，第一行文本带“（她，仰脸）“…”、第二行带残缺“”，说话人都为空。真实剧本 23 镜：ep35-S3 ep36-S2 ep36-S3 ep37-S6 ep38-S4 ep39-S4 ep40-S2 ep40-S4 ep41-S3 ep44-S4 ep46-S4 ep46-S5 ep47-S4 ep48-S4 ep53-S6 ep54-S4 ep54-S6 ep56-S2 ep56-S3 ep56-S4 ep56-S5 ep57-S5 ep60-S2。影响画布对白显示和 T38 TTS 说话人分配 | 只在引号外的“／”处切分（先用 LINE_RE 全文匹配，再处理余下文本）。测试：`test_dialogue_slash_inside_quotes_is_one_line` |
| QA-07 | 低 | 导入器 `_parse_dialogue` | ep05-S4 `（他，贴在她耳侧，画外声）：“那就看你——是不是自愿。”` | 期望：说话人“他，贴在她耳侧，画外声”。实际：括号和引号之间的“：”让 LINE_RE 不匹配括号，speaker_note=None | LINE_RE 允许括号后可选 `[：:]\s*`。测试：`test_dialogue_colon_between_speaker_and_quote` |
| QA-08 | 低 | 导入器（对白/舞台提示）+ 剧本原文（claude-gpu3） | data/import/script_v2.json | 72 句对白没有说话人。除 QA-06/07 外：9 镜整行是舞台提示（ep07-S1“（她回应的吻）”、ep10-S5“（无——全镜无对白…）”、ep25-S4 等）被当成台词文本；ep29-S3 屏幕消息“他：“…””格式；ep50-S2 无引号“（她）完了。（他）这是什么？”；ep25-S3 对白为“—”；ep03-S1 等续句没写说话人（可接受）。另：46 处 img/motion/sound 原文里残留 Markdown `**` 加粗（ep46-S1、ep46-S4、ep47-S5、ep50-S2 的 img 进了首帧提示词） | 整行只有括号的段 → stage（text 为空，TTS 跳过）；“X：“…””格式识别说话人；导入时去掉成对 `**`。剧本侧的格式由 claude-gpu3 统一 |
| QA-09 | 低 | API `services/api/ns_api/app.py` SPA 兜底（画布 v3 agent） | `curl -i :8812/api/does-not-exist` | 期望：未知 `/api/*` 返回 404 JSON。实际：`/{path:path}` 兜底返回 200 index.html，前端 `req()` 会在 `r.json()` 报难懂的解析错（接口改名/拼错时不易发现）。已核对：/files 与兜底路由都不能穿越到 config/（`..`、`%2e%2e`、`%5c` 均被拦或回 index.html） | 兜底路由里 `if path.startswith("api/"): raise HTTPException(404)` |
| QA-10 | 低 | `tools/fetch_civitai.py`（research-62b0 / 资产 agent） | 代码审查 | token 以 `?token=` 拼进 URL；`except Exception as e: print(e)`——当前 urllib 的 HTTPError 不含 URL，日志里未发现 token，但 InvalidURL/重定向类异常会带 URL | 打印前 `str(e).replace(token, "***")` |
| QA-11 | 信息 | 剧本 v2（claude-gpu3，T02） | 导入 | 360 镜全部 `duration_source=default`（10 秒）：v2 剧本没有 `**时长**`；每集 60 秒默认值。等 v3 剧本 | — |
| QA-12 | 信息 | 导入器 | `tools/import_script.py` | 1 条警告：第 3450 行无法归属“（原文修正）第一份。留在了最里面。……好烫。*” | 剧本写入者确认该行归属 |

### 按负责人汇总（未关闭）

- 图像流水线（compiler / frame_spec / render 数据）：QA-01（高）、QA-02（高）、QA-03、QA-05（中）、QA-04（低）
- 导入器：QA-06（中）、QA-07、QA-08（低）
- 画布 v3 / API：QA-09（低）；契约本轮无缺口
- 资产 / 下载工具：QA-10（低）
- claude-gpu3 剧本：QA-08 格式部分、QA-11、QA-12（信息）

## 第 2 轮 — 2026-10-30 06:09

- `uv run pytest -q`：140 通过 / 3 跳过 / 8 xfail（其他 agent 新增了 tests/test_post.py 等，全部通过）；canvas_api 9 通过 1 跳过；tsc 通过。
- 编译 / 导入 / 数据 / API 契约（重新拷贝最新代码到 :8812 副本）/ 密钥扫描：结果与第 1 轮相同。
- **已修复**：无。**新增**：无。QA-01 … QA-12 仍未关闭。

## 第 3 轮（最后一轮）— 2026-10-30 06:30

- `uv run pytest -q`：155 通过 / 3 跳过 / 8 xfail；canvas_api 9 通过 1 跳过；tsc 通过。
- 编译 / 导入 / 数据 / API 契约（:8812 副本，最新代码）/ 密钥扫描：结果与第 1、2 轮相同（契约检查里唯一的 400 是故意发的非法 review state，属预期行为）。
- **已修复**：无。**新增**：无。QA-01 … QA-12 仍未关闭。QA 测试副本和 :8812 服务已停掉 / 留在临时目录，data/ 未被改动。

## 修复记录（fredw-d9，2026-10-30）

| QA | 状态 | 修复 |
|---|---|---|
| QA-01 | ✅ 已修 | compiler._strip_triggers 每个触发词前先去前导空格；xfail 已去掉 |
| QA-02 | ✅ 已修（数据） | 20 个成人镜头的笔记本当前首帧/尾帧撤下（active=null，frame.png → frame.png.deactivated_adult），记入 qc_log.jsonl；已通知 gpu3 改由 T34 出帧、拉帧规则写进代码；set_active 拒绝成人镜头的笔记本版本 → 已交画质 agent |
| QA-06 | ✅ 已修 | 只在引号外按“／”切分 |
| QA-07 | ✅ 已修 | 括号与引号之间允许冒号 |
| QA-08 | ✅ 部分 | 支持“名字：“…””写法；字段里的 Markdown ** 去掉。无说话人台词 72 → 15（多为纯舞台提示） |
| QA-09 | ✅ 已修 | 未知 /api/* 返回 404 |
| QA-10 | ✅ 已修 | 下载异常信息里的 token 打码 |
| QA-03/04/05 | ✅ 已修（画质 agent） | 地点所有格不再触发角色锁；无逗号运镜只去英文运镜词、括号内“——”不切；Frame Spec 不重复材质句；set_active 拒绝成人镜头的笔记本版本（QA-02 代码闸门） |
| QA-11/12 | 等 v3 / 原稿 | — |

## 2026-10-30 全站走查（fredw-92 debug agent）

走查方式：CDP 无头 Chrome 逐页加载（总览 / 集 ep01 / ep01-S1 / ep60-S5 / 节点 / 资产 / 人物 / 导入 / #/projects / #/inbox / #/script-chat），收集 console 错误与警告、未捕获异常、≥400 或失败的请求、>10 s 的慢请求、是否卡在“加载中”；交互：检查器 7 个 tab、点帧开查看器、A/B、版本条、资产灯箱、导入页「校验格式」（只读）。API：枚举 `app.routes` 里的全部 GET（含各 router），参数用 ep1 / ep60、ep01-S1（gpu3 负责）、ep60-S5、lin_wan 等。不触发出图、gpu3 重出、Qwen 任务或剧本导入。脚本在会话临时目录（crawl.mjs / sweep.py），不进仓库。

| ID | 页面 / 接口 | 现象 | 原因 | 修复 | 测试 |
|---|---|---|---|---|---|
| QA30-01（中） | `GET /api/qwen/tasks` | 每次 11–12 s | 本地已取消的任务（status=cancelled）不在 TERMINAL 里，列表每次都向上游补问，上游已删 → 404，一个约 1 s | `qwen_mailbox.TERMINAL` 加 `cancelled` → 0.9 s | `tests/test_qa_laptop_1030.py::test_qwen_list_skips_cancelled` |
| QA30-02（高） | 集视图 / 查看器缩略图 `GET /api/gpu3-media/…/takes/*.png` | 大量 502，gpu3 镜头的帧图空白 | 桥隧道慢（2.8 MB 一张要 14–22 s），并发时 5 s 超时 → 熔断 15 s → 这段时间所有缩略图 502；每次打开都重新经桥取 | `takes/` 下带版本号的文件取完整一次就存到 `data/cache/gpu3_media/<rel>`（写 .part 再改名，长度不对就丢弃；Range 请求不存；frame/last/video.mp4 会被 gpu3 覆盖，不缓存）。第二次 0.12 s，桥断时已缓存的照样能看 | `test_gpu3_media_takes_cached` |
| QA30-03（中） | `GET /api/episodes` | 2–12 s，页面同时加载时 13–25 s，节点视图曾卡在「加载节点画布…/加载 ep01-S1…」20 s | 每次请求都在 Windows 上做几千次 `Path.resolve()`（每次 `_rel` 都重新 resolve `P.DATA`；`assets.file_url` 每次都 resolve `ASSETS_DIR`） | `readiness._rel` 缓存 DATA 根和镜头目录的 resolve 结果（按 `str(P.DATA)` 作 key，测试换根也对）；`assets.file_url` 缓存 ASSETS_DIR 的 resolve。resolve 6465 → 2745 次，热态约 3 s | `test_rel_cached_matches_resolve` |
| QA30-04（低） | ep60 集视图 | `GET /api/looks/episodes/61` 404 | 刷新造型时取 [n-1, n, n+1]，末集也请求 n+1 | `store.tsx`：按已知最大集号过滤 | 手动复现：打开 `/?view=episode#ep60-S5`，确认没有 404（走查第 2 轮已通过）。没有前端测试运行器 |
| QA30-05（中） | 全部画布页 | 一打开就并发两次 `/api/episodes`（各 8.8 MB），互相拖慢到 >20 s | 开发模式下 StrictMode 双挂载；轮询 / 改动刷新和在途请求叠加，没有合并 | `store.tsx` 的 `refreshEpisodes` 合并在途请求：300 ms 内重复的调用直接复用；更晚来的调用标记一次，本次结束后再刷一次（调用方拿到的总是之后的数据） | 手动：`performance.getEntriesByType('resource')` 里 `/api/episodes` 由 2 次降到 1 次 |
| QA30-06（信息） | 全部画布页 | `/favicon.ico` 404 | index.html 没有设图标 | ✅ 已修（fredw-25，T60）：index.html 加 `<link rel="icon" href="/favicon.svg">` + `apps/web/public/favicon.svg`；API 托管 dist 时根下静态文件直出 | `tests/test_episodes_fast.py::test_spa_serves_root_static_files_and_blocks_traversal` |
| QA30-07（信息） | 节点视图 | React Flow 警告「hiding the attribution」 | `proOptions.hideAttribution` 需要 React Flow Pro 订阅 | 不修：是授权问题，交项目方决定 | — |
| QA30-08（信息） | `GET /api/qwen/tasks/{id}`、`…/files` | 已取消任务返回 404 | 上游信箱已删除这个任务，属预期 | 不修 | — |

API 扫描（修复后）：全部 GET 无 5xx、无超过 10 s 的请求。4xx 都是预期结果：projects/weita 的 style、characters 返回 409（现有项目不能在向导里改）；`/api/docs/REQUIREMENTS` 404（白名单外）；`/api/script-input/text` 缺 path 返回 422；gpu3-media 路径越界返回 400。
复测：12 个页面 / 交互全部渲染，没有 console 错误或未捕获异常；除 favicon 外没有 ≥400 的请求。pytest 498 通过 / 4 跳过（含新增 3 个）；tsc 0 错误。注：复测时 `/api/script-chat/config`、`/system` 曾短暂 500（config/script_chat_rules_appendix.md 缺失，另一会话正在加这个文件），文件补上后恢复 200，不是本轮改动引起。API 已用同样的命令在 :8800 重启，加载了新代码。


## 第 4 轮 — 2026-10-30 晚（fredw-5c，后端与工具链）

范围：导入 → 编译 → frame_spec → state_timeline → 装配（T38）→ 校色（T52）。只读检查用 `scratchpad/qa/pipeline_check.py`（重新导入到临时文件后与 data/import 比对；全量编译 + build_spec 检查格式、残留触发词、重复材质句、尾帧缺规格词；state_timeline --check）。API 契约本轮未扫（fredw-92 走查已覆盖）。

| ID | 严重度 | 区域 | 现象 | 修复 | 测试 |
|---|---|---|---|---|---|
| QA4-01（中） | 导入 / state_timeline | 剧本 .md 源文件在导入后又被改过（两份 v2 源 sha 都变了），画布读的仍是旧导入，没有任何提示 | ✅ `state_timeline.source_drift()`；时间线 `source.changed_sources`；`tools/s1_gate.py` 输出并提示“需项目方重新导入”。SOP 闸门是否据此加 blocker 由 fredw-92 决定（services/api） | `test_source_drift_flags_edited_or_missing_script_files`、`test_timeline_source_lists_changed_sources` |
| QA4-02（高） | 编译器 G1 | 尾帧不追加触发词、材质条目（漆皮 / 6mm 细跟 / 脚趾甲）和纠正器条目（特写 / 暗场 / 安全镜），首尾帧造型对不上；frame_spec qwen_last 同样 | ✅ 两条路径都按“首帧原文 + 结束状态”补，规则同首帧；项目方定“系统自动补”，加去重（写作者已写的同一条目不再加，尾帧只和自己的文字比） | `tests/test_last_frame_specs.py`；t06 金标准更新 last_prompt / qwen_last |
| QA4-03（高） | 渲染数据 data/renders | ep01 换成 rules_v2 剧本并恢复整集 🔴 后，S1–S6 仍挂着笔记本 04:17–07:29 按旧剧本出的当前首帧（S1 还有尾帧） | ✅ 同 QA-02：active 去掉 image/last，frame.png / last.png → `*.deactivated_adult`，文件全部保留，记入 data/renders/qc_log.jsonl | `NS_QA_DATA=1 pytest tests/test_qa_laptop.py` 22 通过 |
| QA4-04（中） | 装配 T38 | G13 定“剧本写整数秒、实际片长交给 H3”，装配仍把每镜裁切 / 定格到剧本秒数 | ✅ 有视频的镜头按视频实际时长装配，占位静帧才用剧本秒数；时间线记 `script_duration_s`、`duration_from`。fredw-92 的 4K VBV 与 _cc source_sha256 保留 | `tests/test_post.py::test_assemble_episode_end_to_end` |
| QA4-05（中） | 测试 | 20:02 导入只剩 ep01 时 19 个测试失败：test_looks / test_sop / test_qa_laptop / test_quality_v2 直接读 data/import/script_v2.json，并写死 60 集 × 6 镜、ep01-S3 非成人 | ✅ 功能测试改读固定剧本 `tests/fixtures/t06_golden/data/import/script_v2.json`；test_qa_laptop 默认也用它，`NS_QA_DATA=1` 才查真实数据；镜数检查改为镜号从 1 连续 | 全量 531 通过 / 4 跳过 |
| QA4-06（低） | 测试 | `tests/test_readiness.py::test_blocked_status_and_continuity` 在一次全量里失败，单跑与重跑都通过（疑似与并发改动或用例顺序有关）；同样情况：`tests/test_episodes_fast.py::test_detail_matches_legacy_and_summary_endpoint` 在一次全量中失败（运行期间 services/api/ns_api/app.py 被改动），单跑 5/5 通过 | 观察中（封板后在无并发改动时复跑全量确认） | — |
| QA4-07（信息） | LoRA 注册表 | 笔记本与 gpu3 的 LORA_REGISTRY.json 里 lin_wan_qi_v1 仍是 status=training、sha256=null，state_timeline 因此给林晚镜头标 `lora:lnwan_qi:training` | 原因：gpu3 真记录在 `ComfyUI/models/loras/LORA_REGISTRY.json`（accepted、sha256 873b727b…、strength 0.8，文件已在 loras/），镜像 `data/renders_gpu3/LORA_REGISTRY.json` 未同步；已告知 fredw-92 改同步源 | — |
| QA4-08（信息） | 校色 T52 | ep01-S1/S2 本地没有匹配首帧关键帧，dry-run 跳过 | 已知（T52：等 gpu3 同步关键帧） | — |

同轮按项目方决定的系统改动（非缺陷）：成人判定默认恢复整集 🔴 继承（逐镜代码保留，`config/adult_overrides.json` `"per_shot": false`）；编译器读 `config/auto_lora_triggers.json`，把 lnwan_qi 放在首尾帧触发词最前、本机缺 LoRA 文件也不剥掉、不重复；阴环珠数据改为 5mm、左4 阴蒂1 右4、不锈钢本色；SOP 时长语义（G13）。
