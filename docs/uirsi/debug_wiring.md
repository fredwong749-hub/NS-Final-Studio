# UIDEBUG：前后端连接排错（debug_wiring）

- 日期：2026-10-31
- 负责：UIDEBUG（只写系统；不改剧本内容、不提交渲染、不删数据、没 git 提交）
- 范围：apps/web/src（React/Vite :5173）↔ services/api/ns_api（FastAPI :8800）
- 工具：
  - 静态：`tools/uirsi/check_wiring.py`（前端 159 处 /api 调用 × OpenAPI；默认 import ns_api.app 现算，不信正在跑的旧进程）
  - 测试：`tests/test_uirsi_check_wiring.py`（解析器自测 + 全仓检查，已进 pytest）、`tests/test_uidebug_lanes_swr.py`
  - 运行时：无头 Chrome（CDP :9691），逐页打开 27 个页面 / 状态，记网络（状态 / 耗时 / 大小）、控制台、未处理异常、卡住的加载、可见错误文字；**全部非 GET 在 Fetch 层拦下不发送**；只点页签 / 卡片，不点生成、定稿、通过、保存、导入、合成、删除

## 1. 结论

| | 数量 |
|---|---|
| 问题总数 | 12（P0 1 · P1 4 · P2 7） |
| 已修（后端，待重启生效） | 2：W-07、W-08 |
| 交给 UIRSI（前端，已发 SendMessage） | 6：W-03、W-04、W-05、W-06、W-09、W-10（另 W-11 的 klein 测试） |
| 待 :8800 重启生效 | 3：W-01（代码早已有）、W-07、W-08 |
| 待议（后端 + 前端一起） | 1：W-02 |

静态比对：前端调用的路径、方法、必填 query / body 字段 **0 个 E 级错误**；POST / PUT 请求体（内联对象 + FrameJobBody、VideoJobBody、ScriptSessionInit、GenerateRequest、OwnerDecision Body、refs/apply、cut-job 等有类型的）逐一对过 Pydantic 模型，没有字段名不一致。真实 GET 响应与 TS 类型对过 30 个接口，没有“前端读、后端不给”的必有字段。
主要问题在**运行中的 API 比代码旧**（W-01）和**页面加载时后端慢**（W-02 / W-07 / W-08）。

重启条件：`GET /api/jobs` 当时 running 3、queued 2（A/B/C 在出片）→ **没重启**。

## 2. 问题清单

| # | 严重度 | 页面 | 前端位置 | 后端位置 | 现象 | 证据 | 修法 | 状态 |
|---|---|---|---|---|---|---|---|---|
| W-01 | P0 | ① 新建剧本 `#/script-create`（含被转来的 `#/projects`、`?tab=chat`） | apps/web/src/v3/pages/story_api.ts:89–102；NewScriptPage.tsx:49 | services/api/ns_api/story_runs.py:313 起（8 条路由） | 运行中的 :8800 没有 `/api/story-runs*`（代码里有）：左栏“写作记录暂时读不到：后台还没有这项功能（等 API 重启后出现）”；“开始自动写作”/返修/送去导入都会 404 | 两轮运行时各 6 / 7 次 404；`check_wiring.py --openapi http://127.0.0.1:8800/openapi.json` 列出 8 条 E-ROUTE；代码 OpenAPI 与运行中只差这 8 条 | 重启 :8800（ops/autostart/laptop_autostart.ps1 第 2 段命令，只停监听 8800 的进程） | 待重启 |
| W-02 | P1 | 画布 ep02 审片 / 精修、资产 | store.tsx:450（整集逐镜拉详情）等 | app.py（/api/episodes/{n}、/api/sop/episode/{n}、/api/shots/{id}） | 页面一开 50–135 个请求同时打 API；单打很快的接口在页面里排队：`/api/sop/episode/2` 15–25 s、`/api/episodes/2` 14 s、`/api/shots/ep02-S*` 每个约 5 s（单打 0.17 s）；精修页“提示词”页签显示“正在读取 ep02-S1…”超过 8 s | r2_crawl：≥4 s 的 API 请求 118 次；单独计时 shots 0.17 s、produce 0.07 s | 待议：前端按需拉详情（只拉可见 / 选中镜头），后端 /api/shots/{id} 减重或加短缓存 | 待议 |
| W-03 | P1 | 画布 ep02 | apps/web/src/store.tsx:450 `refreshShots` | app.py `GET /api/shots/{id}`（每个约 137 KB） | 进一集就把 11 镜的完整详情全拉一遍（W-02 的主要来源之一）；集摘要本来就是为了让卡片不必逐镜请求 | 网络记录：ep02 加载 11 个 /api/shots/ep02-S* 并发 | 只拉当前选中 / 可见行；其余用 /api/episodes/summary 的轻字段 | 交 UIRSI |
| W-04 | P2 | 精修 · 出图参数 | apps/web/src/v3/api_v1.ts:346 | frame_jobs.py:195 | gpu="auto" 时 URL 成 `/api/render/image-presets?`，refresh 时 `?&refresh=true` | 网络记录 | 用 URLSearchParams 拼 | 交 UIRSI |
| W-05 | P2 | 整集出片 · 取消 | apps/web/src/v3/EpisodeProduce.tsx:184 | episode_produce.py:975 | 给不收请求体的 produce/cancel 发 `{}`，无害 | check_wiring 第 1 轮 E-BODYKIND（空对象，之后检查器把空体降为不报） | 改 `{method:"POST"}` 无体 | 交 UIRSI |
| W-06 | P2 | 多处（旧组件下线后） | api.ts putH3Override / gpu3Resend / uploadFirstFrame / looks.setDefault / episodeRange / schedule / putTags / episodeEdit / assets.generate / importManifest；api_v1_pages.ts scriptApi.*；rev_api.ts plan / proposals / templateUsage | 例：PUT /api/shots/{id}/audit-override、POST /api/shots/{id}/h3-lint、GET /api/shots/{id}/gpu3-state、GET /api/explicit-holds、PUT /api/look-schedule、GET/DELETE /api/script-input… | 27 个接口封装已无调用方，后端 74 条路由前端没有入口（含项目 / 向导 / 剧本对话等已下线的）——需要确认哪些是故意下线、哪些是功能没接上（H3 覆盖 + 重发 gpu3、上传首帧、造型排期最值得确认） | `check_wiring.py --unused`；grep 调用方 | UIRSI 确认；故意下线的删封装，没接上的补入口 | 交 UIRSI |
| W-07 | P1 | 所有页（顶栏“卡 N/6 忙”）、精修、场景页 | apps/web/src/v3/edit/lanes.ts:86；scenes_api.ts:141 | services/api/ns_api/jobs.py:733 `render_lanes` → `lanes()` | 页面里 4–10 s，单打 8 s：探测缓存 15 s 一过期就经隧道现探 6 个地址（每个 2.4–4.4 s） | 第 1 轮 lanes 61 次 ≥4 s 中占多数；分段计时 probe 2.4–4.4 s、train_locks 首次 10–12 s（之后走缓存） | 展示路径改“先给上次结果、后台刷新”（`_probe_for_view`，最旧 120 s，返回 cached/age_s）；`ns_render.endpoints.peek` 只读取缓存。提交任务的选卡（pick_lane / resolve_lane / lanes() 默认）照旧现探，渲染行为不变 | 已修，待重启 |
| W-08 | P1 | 精修 · 出图参数面板；资产页 | apps/web/src/v3/api_v1.ts:345；scenes_api.ts:149 | services/api/ns_api/frame_jobs.py:166 `lane_allowed` | 精修页加载 `/api/render/image-presets` 36–40 s（单打 0.04 s）：10 分钟缓存过期后同步取 ComfyUI object_info，卡在出视频的卡上要几十秒 | r1：40062 ms / 36451 ms | 过期不到 6 h → 先给旧值（refreshing:true）并后台刷新；从没取过或点“刷新”仍同步。提交时的参数校验照旧读同一份缓存 | 已修，待重启（冷启动第一次仍同步：r2 资产页 gpu=0 首次 20 s） |
| W-09 | P2 | 画布集头 | apps/web/src/v3/ProduceHistory.tsx:92 `useRun` | episode_produce.py | 已有 EpisodeProduce 的共享轮询，又自己 fetch 一份；ep02 加载时 `/api/episodes/2/produce` 并发 4 次 | 网络记录 | shared 有值时不再 fetch | 交 UIRSI |
| W-10 | P2 | `#/script-create?tab=chat` | ScriptFlowPage.tsx | — | 单集对话写作页已删，旧链接静默落到 ①，不提示 | 截图 script-chat-tab.jpg 与 script-create 相同 | 落到 ① 时提示一句“对话写作已下线” | 交 UIRSI |
| W-11 | P2 | 测试 | tests/test_klein_option.py 读已删除的 components/assets/parts.tsx | — | 全量 pytest 3 个失败都不是本次改动：klein（UIRSI 重构删了 parts.tsx）；test_t06_bible 黄金提示词差异（tests/fixtures/t06_golden 与提示词编译被别的会话改动中）；test_knowledge_autopilot（本次加规则后需要 compile，已处理） | pytest 1199 passed / 3 failed | klein 测试跟着重构改；t06 由改编译的一方更新黄金 | klein 交 UIRSI；t06 报总调度 |
| W-12 | P2 | 全站（开发态） | apps/web/src/main.tsx:18 StrictMode | — | 开发服务器下 render-backend / lanes / story-runs 每页各请求 2 次（StrictMode 双挂载），构建版不会 | 网络记录 | 不改；排错脚本计重复时扣除 | 信息 |

## 3. 第 1 轮 → 第 2 轮（RSI）

| 指标 | 第 1 轮 | 第 2 轮 | 说明 |
|---|---|---|---|
| 静态 E 级（路由 / 方法 / 必填） | 0（代码 OpenAPI）；8（对运行中 :8800） | 0；8 | 运行中的进程没重启，W-01 原样 |
| 静态 P2（W-05 空体） | 1 | 0 | 检查器把空对象请求体降为不报（W-05 仍交 UIRSI） |
| 页面数 | 25 | 27 | 第 2 轮加表格 / 分镜表，精修页 10 个页签按文字点 |
| API 4xx / 5xx | 6 | 7 | 全是 /api/story-runs（W-01），多出的一次来自新加页面 |
| 未处理异常 / 控制台 JS 错误 | 0 / 0 | 0 / 0 | 控制台只有 story-runs 的 404 资源日志 |
| 被拦的非 GET | 0 | 0 | 安全点击没有触发任何写请求 |
| ≥4 s 的 API 请求 | 61 | 118 | W-07 / W-08 要 :8800 重启才生效；第 2 轮时出片任务更多、API 更忙（W-02） |
| 精修页页签可点 | 1/8（选择器问题） | 8/10（“首帧”“尾帧”在当前布局不是按钮文字） | “提示词”页签点开后“正在读取 ep02-S1…”> 8 s（W-02） |

重启后复测命令（:8800 空闲时）：

```
.venv/Scripts/python.exe tools/uirsi/check_wiring.py --openapi http://127.0.0.1:8800/openapi.json   # 期望 0 个 E
curl -s -o NUL -w "%{time_total}\n" http://127.0.0.1:8800/api/render/lanes                          # 期望 < 0.5 s（第二次起）
```

## 4. 规律（写进 knowledge/rules/ui.yaml）

- K-UI-007：前端每个 /api 调用都必须在后端路由表里（路径、方法、必填字段）——check_wiring.py + pytest。
- K-UI-008：代码有路由 ≠ 运行中的 API 有；交付写“待重启生效”，前端对框架 404 降级显示。
- K-UI-009：被轮询的展示接口不同步等远端，先给旧值后台刷新；提交路径照旧现取。
- K-UI-010：同一接口一个页面只拉一份（共享 hook）。

RSI 账本：knowledge/RSI_LEDGER.md §H（H1–H4）。

## 5. 改动文件

- 新增：tools/uirsi/check_wiring.py、tests/test_uirsi_check_wiring.py、tests/test_uidebug_lanes_swr.py、docs/uirsi/debug_wiring.md
- 修改（后端，展示路径，不改渲染）：services/api/ns_api/jobs.py（`_probe_for_view`、`lanes(view=)`、`render_lanes`）、services/api/ns_api/frame_jobs.py（`lane_allowed` 旧值 + 后台刷新）、services/render_router/ns_render/endpoints.py（`peek`）
- 知识：knowledge/rules/ui.yaml（K-UI-007…010）、knowledge/RSI_LEDGER.md §H
- 前端：没改（全部交 UIRSI）
