## 第 28 轮（A-G7 · Fable，Orca 工人 task_3774faa0c44e，总调度 MASTER-WSL 派）· 11-03 11:0x–11:4x · cut B 发版前复审 G7（UI apps/web/src W5/W5b + sop.py 只读聚合 + uirsi 测试 + 决定表 / 编译产物）

**结论：G7 可入 cut B（是）。P0 无。P1 ×1：tests/test_v2cut_o.py 有 3 条数据态快照断言在真实工作树上必红，cut B 的 pick_tests 会挑它 → 闸门红；要在 cut --dry 前改成性质断言（不删测试）。需补入 7 个清单外文件（按 §4 规则归 G5）；需剔除 0。**

### 0. 范围说明（派单与 CUT_PLAN 口径不一致，两边都审了）
- 派单标题把 G7 定义为 "UI apps/web/src（W5/W5b）+ services/api sop.py 只读聚合 + uirsi 测试"；CUT_PLAN_sv17 §4 的 G7 只有 2 个文件（config/owner_decisions.yaml、knowledge/generated/index.json），apps/web/** 与 sop.py 在 G5。
- 本轮覆盖：§4 G7 两个文件 + G5 里的 apps/web/**（37 项）+ services/api/ns_api/sop.py + tests/test_r43_uirsi.py、test_ui_stepbar.py、test_l123_no_reject_ui.py。G5 其余 services/api/* 文件（app.py、owner_inbox.py 等 20 个）没审，留给 A-G5。
- 基线：HEAD = 6125b3e（sv-20261103-01 = cut A）。diff 都是相对 cut A。

### 1. 清单核对（`git status --porcelain -uall` 11:0x，339 条）
- CUT_PLAN G7：`M config/owner_decisions.yaml`、`M knowledge/generated/index.json` 都在 ✅。
- CUT_PLAN G5 的 apps/web/** 37 项全部仍在（23 M + 14 新文件，含 pipeline.css / stepbar.css / overview_now.css / pageintro.css / sceneLabel.pure.ts / scene_label.test.mjs）✅。
- **清单外新冒出、按 §4 归组规则归 G5、必须补入的 7 个**：
  1. `M apps/web/e2e/uirsi/topbar_check.mjs`（W5b：换集下拉改查范围条 .v3-scope；test_ui_stepbar::test_topbar_check_follows_scope_bar 读它）
  2. `?? apps/web/e2e/w5ui/shoot_w5.py`（同上测试读它，断言 `sys.exit(2)` / `def _rel(`）
  3. `?? apps/web/e2e/w5ui/shoot_w5b.py`
  4. `?? apps/web/src/v3/plainWords.ts`（W5b 人话词典；stepbar.ts / queueActs.ts / OwnerQueuePage.tsx 都 import 它——**漏了前端 tsc/build 直接红**）
  5. `M apps/web/src/v3/assets/AssetInspector.tsx`（1 行文案：去掉 "config/ … data/assets/proposals/" 路径）
  6. `?? tests/test_ui_stepbar.py`（W5 / W5b 的 23 条测试）
  7. `M tests/test_l123_no_reject_ui.py`（W5 / W5b 新增 2 条）
- 需剔除：无。

### 2. 逐文件

#### services/api/ns_api/sop.py（+459 / −30）
- **W5 段（L925–1131，GET /api/sop/stepbar）只读成立**：只调 `_PSTAT.pipeline_status(run)` 与 `report_issue.load()`。AST 核：`sop_gate.stage_view → status` 可达的 36 个函数里没有 `_write_state` / `_log_violation`（它们只被 require / require_backoff 调）；`report_issue.load` 只 read_text；`look_confirm.episode_state` 只调 episode_people / is_confirmed / pick_id（`_atomic` 写函数只在确认路径）。与第 21 轮 mtime 快照结论一致。
- **A5 P1-2 / P2-4 修复核实**：`latest_first` 同 id 留最新登记 → 阻断优先 + 时间降序 → 同一句话（issue_plain 60 字）去重；done 格去掉旧"挡路"只计 `stale`；`blocking[0]` = 最新一条。test_ui_stepbar 5 条锁定（test_blocking_cell_uses_the_latest_issue_first 等）。
- **UIFIX-F / V2CUT-O 段（第 18–27 轮没有审过）**：`state_files` / `script_file` 走 `ns_agent.run_paths`，解析失败返回 None、**不回退 V1 的 data/ 全局文件**（C-14 ✅，timeline_missing 报错不装作有）；`timeline_foreign` 把 script_sha 对不上的状态表的 scene_id / 底板全部挡掉；`shot_scene` 取法 剧本场景 > 当前剧状态表 > None；`look_asset_state` 口径复用 `tools/master/episode_ready.character_gaps`，异常 → 不就绪并写明原因（失败关闭 ✅）；`asset_look_states` 用 `ns_api.look_confirm.episode_state`（和通知中心同一份），没有 runs.json 的临时根保持旧口径。
- **路由注册方式（P2）**：`_PSTAT.router.include_router(router)` 在 sop 模块 import 时挂到 pipeline_status.router 上。FastAPI 的 include_router 是拷贝路由，所以全靠 app.py:43 `import sop` 早于 app.py:208 `include_router(PSTAT.router)`；顺序一反 /api/sop/stepbar 就 404 且无任何报错。test_route_registered_without_touching_app 用 openapi() 锁住了现状。合并时改成 `app.include_router(SOP.router)`（文件里自己也这么写了）。
- **P2**：`_episode_ready_module()` / `_sop_gate_module()` 每次调用都 `spec_from_file_location + exec_module` 重新执行 tools/ 脚本，无缓存（`_report_issue()` 有缓存，是对的做法）；`sop_gate_view` 每次 project_summary 都重载一次 sop_gate.py；episode_ready.py 导入时还往 API 进程 sys.path 插 services/agent、services/post。性能 / 进程污染，不是正确性问题。
- **P2**：`asset_state_files` 用 `data/looks/hub_episode_looks.json`（全局路径，非 per-run）做缓存签名。
- `api_stepbar` 的 `try/except _HTTPException: raise` 等于没包，其它异常 500——可接受（sop_gate 读不到本来就不该猜）。
- V1 剧名 / 人物硬编码：无。`_STEP_WORDS` / `owner_label` / `STEP_OWNER` 都是通用词。
- 默认值 vs OWNER_CANON：`owner_label` 把 GOLDEN / IMG / FRAME 折成 "系统 · 出图"（登记人其实是工程 agent，第 21 轮 P2-3 指出过）；前端 `plainOwner` 再把 "工程师（…）" 折成 "系统（工程线）"。无冲突，只是口径未根治（根治在 report_issue 加 plain 字段，G1）。

#### apps/web/src（W5 / W5b / NAVFLOW-F / UIFIX-F / V2CUT-O / INBOXPICK-S，23 M + 14 新）
- **写副作用**：前端新增的非 GET 只有 `pickItem`（POST /api/owner/pick）、`DelegateBanner` 撤销（POST /api/owner/delegate/revoke）、既有 `decideItem` / `undoItem`——都是项目方主动点击。例外：`probeOwnerDecisionApi` 在页面加载时自动 **POST /api/sop/owner-decision 空 body** 探路由（靠 422/400 拦下，不记录）。只读 e2e 记录的 `blocked_non_get=2`（第 21 轮 P2-4 没查出是谁）很可能就是它。**P2**：探测改 HEAD/OPTIONS 或 GET 一个只读接口，别让只读模式下页面自己发 POST。
- **C-09 / L-123**：全站 grep 无 "要这个 / 不要 / 打回" 入口；App.tsx 摘掉 `<RejectDialog>`；#/queue 每条只有 "批准 / 用这张" + "修改"（`queueActs.twoActs`，"稍后" 不做按钮）；decide 类 "要求修改" 必填一句理由，reason 加前缀 "要求修改："；点了原地 202 ack。后端仍记 `choice=reject`（CHANNEL 05:46 已知遗留）——P2 延续，不阻断。
- **C-14**：`sceneLabel.ts` 删掉 WORD 表（含 `gu: "顾沉"`、office→办公室），纯函数挪到 `sceneLabel.pure.ts`，登记里没有的显示 "场景未登记：id"；ReviewRow / StoryboardTable 不再读 `data/scenes.json`；底图所属场景与本镜不一致（V1 残留）不显示；`sopSceneId` 旧后端 timeline_stale 时不信。node --test 4/4。V1 名字只出现在注释里。
- **C-17 不删功能**：20 个旧路由在 `pageMap.ts` 登记入口，TopBarV3 "设置 ▾"（原 "工具 ▾"）分组 设置 / 剧本 / 资产与声音 / 查看 / 高级 全部保留；#/assets 换回 AssetCenter，V2AssetsPage 变成左栏 "资产包清单"（?type=pack）；♪ 声音从顶栏并入资产中心左栏 + 菜单。test_ui_stepbar 4 条锁定入口存在。
- **A5 P1-1 修复核实**：`stepbar.ts` fallback 时 `owner: ""`（不拿默认负责方冒充事实）、`fallback: true`；TopBarV3 顶栏下、NowPanel、PipelineMatrix 都挂 `sb-banner` "后台接口未更新，卡点读不到（旧接口口径）"；`issues_error` 渲染；源码里 "没有卡住" 字样 0。
- **Root.tsx**：`/`（无 hash）→ #/overview；#/inbox → #/queue；#/projects → #/script-create。App.tsx 未知 `#/…` → NotFound 页（列全部页面），不再静默落进画布。
- **ownerQueue.ts 改读 /api/owner/inbox**（原 /api/owner/queue）：后端 owner_inbox.py 在 G3/G5，cut B 一次发没问题；但 G5 后端若单独回滚，顶栏 "待办" 全部读不到（写明以备查）。
- **无测试覆盖的关键路径（P2）**：`stepbar.ts` 的 fromPipe / humanize / load 与 `queueActs.ts` 的 twoActs / editReason 只有 pytest 里的源码字符串断言，没有行为测试（node --test 只覆盖 scene_label）。twoActs 的 POS / NEG 映射决定项目方点 "批准" 到底提交哪个 key（approve / pass / use…，或 recommend.choice），值得一份 node 测试。
- 其它改动（AutoflowPanel 深链接、CutEditor 404 分流、FramesPage 空态、ImageEditPage 去技术词、P1Review holdText、SeasonPage 先出 NowPanel）：看过，无副作用、无 V1 硬编码。

#### tests/test_r43_uirsi.py（+246）、test_l123_no_reject_ui.py（+27）、test_ui_stepbar.py（新 277 行）
- test_r43_uirsi 新增的是 API 重启守护（K-OPS-F34 止血开关、restart_failed 不记 done、revive 只一次、RESTARTFIX-O/S）——被测代码 tools/uirsi/api_restart_guard.py 在 G6；夹具把开关 / 事件 / 日志全换到 tmp_path，`api_up` 钉 True。第 27 轮已复核过这批。本轮 33 条过。
- test_ui_stepbar：六步 = `sop_gate.STAGES` 的分组（不另定义）、计数 / 卡住 / ahead、原文不泄漏（tools/x.py、seed 1200、q9=fail）、20 路由登记 + 入口真实存在、每页一句话 ≤80 字且不含 uv run / tools/ / data/ / .py / /api/、四问标题、两按钮、最新卡点优先、done 格去旧挡路、fallback 横幅、人话词典唯一、topbar_check 跟范围条。覆盖面对得上 W5 / W5b 的自述。
- 未发现删断言 / 改失败为跳过。

#### config/owner_decisions.yaml（+120 / −2）
- D-SCR 某条 `new_terms` 补 `run_style\.json`、`本剧风格配置`（MERGE-IMG-O，ISS-1103-030156-9fcb）；D-VQA-01 stale_allow 只改注释（W11：V2_LIVE.md 改由 LOG_STREAMS 统一不扫）；新增 D-PRM-141 + D-V2-127…144 共 17 条 grep_present / json 检查。
- 引用的文件分属 G2–G6：lint.py（G2）、camera_moves.yaml / run_style.json / music_v2.json / voices_v2.json / hollywood_writer.md（G2/G3/G4）、app.py（G5）、owner_delegate.json / asset_jobs.py / asset_worker.json（G3）、import_script.py（G2）、dispatch.py（G6）、agent_dispatcher.json（G2）、workflows.py（G3）、PLAN_V2_MASTER.md / DIRECTION_V2.md（docs，cut A 已入）。→ **只能随 cut B 整体进**，与 CUT_PLAN §4 "G7 放最后" 一致。
- 无绕闸门分支、无 V1 硬编码（D-AST-93 林晚那条是 HEAD 既有、钉在 series10_v1 路径上）。

#### knowledge/generated/index.json（+225）
- kb-20261102-46175d5f → kb-20261103-6d634b14，660 → 668 条（ops +4 含 K-OPS-F33 借道 / 挂道，render +3，writer +1）。一条 writer_text 把 "蓝发高光、…水晶甲反光点" 改成 "发色高光、…美甲反光点"（去 V1 人物特征，C-14 ✅）。
- 编译产物依赖 knowledge/rules/*.yaml + tools/knowledge/compile.py（G2 补入项）；进 cut B 时必须与 rules 同树，否则 `compile --check` 闸门红。

### 3. 实跑（真实工作树，11:1x–11:3x）
| 项 | 结果 |
|---|---|
| `pytest tests/test_r43_uirsi.py tests/test_ui_stepbar.py tests/test_l123_no_reject_ui.py tests/test_pipeline_status.py tests/test_v2cut_o.py tests/test_uifix_f_v2_cut.py tests/test_ui_no_tech_words_assetux.py` | **117 passed / 3 failed**（26 s）；real-data-guard 写真实数据 0、遗留线程 0 |
| 3 红 = `test_v2cut_o.py::test_reimported_v2_scene_library_is_only_sk_white_cyc`、`::test_ref_switch_only_registered_scenes_for_v2`（断言 V2 导入稿场景库 / 注册表只有 sk_white_cyc，实际已登记 6 个 V2 场景：sk_river_penthouse 江景高层公寓、sk_rooftop_bar 跨年天台酒吧、sk_night_cab、sk_lane_attic、sk_show_backstage）、`::test_v2_look_action_per_episode_with_names_and_thumbs`（ep01 造型 02:23 已确认，第 18 / 25 轮已定性） | 三条全是 **陈旧测试（数据态快照断言）**，不是真 bug、不是环境；多出来的场景全是 V2 的，不是 V1 漏进来 |
| `tsc -b --noEmit`（node 24.20.0） | exit 0 |
| `vite build` | exit 0（既有 >500 kB 警告；dist 在 .gitignore） |
| `node --test apps/web/e2e/uirsi/scene_label.test.mjs` | 4/4 |
| `tools/qa/decision_check.py`（PYTHONIOENCODING=utf-8） | 87 条：✅86 ❌0 ⏳1（D-V2-02 等 V2 导入）；propagation 12/12 ✅；exit 0 |
| `tools/knowledge/compile.py --check` | OK kb-20261103-6d634b14：668 条，一致，生成物最新 |
| `py_compile apps/web/e2e/w5ui/shoot_w5*.py` | OK（syntax_guard 会扫到它们） |

### 4. P0
无。

### 5. P1
- **P1-1 test_v2cut_o 3 条数据态红会把 cut B 闸门打红**。`tests/test_v2cut_o.py` 在 G5 清单里（新文件，必进），cut 的 pick_tests 按改动文件会挑它。处理：把 `scene_library`/`run_scene_registry` 两条改成性质断言（全部 scene_id 都在当前剧登记表、不含 V1 id），`look_action` 那条改用临时根夹具或断言 "已确认 → 动作为空 / 未确认 → 有动作" 两态；按 K-OPS-C02 不删。负责人 V2CUT-O / UIFIX-F；来不及就总调度在 cut --dry 时按 §3 口径记红项豁免。

### 6. P2
- sop.py 路由挂在 pipeline_status.router 上、靠 app.py import 顺序；合并时改 `app.include_router(SOP.router)`。
- `_episode_ready_module` / `_sop_gate_module` 每次调用重新 exec tools/ 脚本（无缓存），episode_ready 导入改 sys.path。
- `probeOwnerDecisionApi` 页面加载时自动 POST 空 body 探路由；只读 e2e 的 blocked_non_get=2 疑似来源。
- stepbar.ts / queueActs.ts 没有行为级测试（只有源码字符串断言）。
- decide 类 "要求修改" 后端仍记 choice=reject（已知）。
- `owner_label` 把 GOLDEN / IMG 工程 agent 折成 "系统 · 出图"；根治在 report_issue 加 plain 字段（G1）。
- `asset_state_files` 用全局 data/looks/hub_episode_looks.json 做缓存签名。

### 7. 与已审轮次（18–27）结论对照
- 第 21 轮 A5 两条 P0 条件：① 排序取最新——已修并有测试；② :8800 上线新接口——代码层已就绪（CHANNEL 05:46 总调度已受控重启），本轮没有连 :8800 验证线上状态。A5 四条 P2：修改语义（部分：前端文案 + 必填理由，后端 key 未改）、工程词（plainWords 词典兜底）、重复卡点（去重）、topbar_check（选择器改范围条）——都有对应改动。
- 第 18 / 25 轮对 test_v2cut_o::look_action 的 "数据态陈旧" 定性：本轮复现，并新增两条同类（场景库快照）。
- 无与 18–27 轮结论相悖处。

**G7 可入 cut B：是。P0：无。需补入（归 G5）：apps/web/e2e/uirsi/topbar_check.mjs、apps/web/e2e/w5ui/shoot_w5.py、apps/web/e2e/w5ui/shoot_w5b.py、apps/web/src/v3/plainWords.ts、apps/web/src/v3/assets/AssetInspector.tsx、tests/test_ui_stepbar.py、tests/test_l123_no_reject_ui.py。需剔除：无。前提：test_v2cut_o 3 条陈旧断言在 cut --dry 前改掉，或总调度按 §3 记红项豁免。**
