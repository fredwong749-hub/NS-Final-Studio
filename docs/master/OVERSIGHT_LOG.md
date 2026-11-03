# OVERSIGHT_LOG（Fable 独立监督；最新在上）

只审不改。每条：谁 / 说了什么 / 实际是什么 / 证据 / 严重度 / 建议。工作树基线：sv-20261102-14（a2110ad，18:07），之后无提交，148 个文件未提交。

---

## 第 30 轮（A18b · Fable，Orca 工人 task_1633ece01376，总调度派）· 11-03 15:1x–15:3x · W18b LIFECYCLE-P0 复审（只审不改，25 分钟时间盒；两个开关仍默认关）

### 复核范围
第 29 轮 P0-1 / P1-1 / P1-2 / P1-3 / P1-4 / P1-6 / P2-3 原文 ↔ W18b 交付：services/api/ns_api/owner_delegate.py:566-842（LOCAL_LANE_PREFIX / _Unknown / _owner_marks / _owner_touched / _script_flags / _producer_lanes / _cand_lane / frame_tick）、tools/autopilot/resident_sync.py:1036（LC_DEFAULT）/ :1098-1125（lifecycle_heartbeats）/ :1138-1160（_server_start / _rq_state）/ :1225-1310（lifecycle_tick 服务器分支）、config/pipeline/sop_gate.json lifecycle、config/pipeline/owner_delegate.json first_frame、apps/web/src/v3/status.ts:85-110 + :256-272、apps/web/src/components/Viewer.tsx:210-218、services/api/ns_api/app.py:296（_auto_locked）、tests/test_producer_lifecycle.py（W18b 新增 12 条）、tests/test_owner_delegate.py。

### 实跑结果（出处；全部只读，真实 data/ 零写入）
- `PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_producer_lifecycle.py tests/test_owner_delegate.py tests/test_sop_gate_promote.py tests/test_w17b_release_p1.py -q`：**72 passed**（12.7 s，1 个 FastAPI on_event 弃用警告）。
- `resident_sync.py lifecycle --dry`（15:16:21，真实状态）：run=series10_v2 status=producing；ep01=出图(4) / ep02=资产就绪(2) / ep03=导入闸门(1)；唯一目标 laptop:producer hb_age 0.4 min → running（不起）；服务器无目标。data/autopilot/lifecycle.json 未产生 ✅。
- `owner_delegate.py frames --dry`（真实状态，first_frame.enabled=false）：**dry 不再被开关短路**，返回 4 行 skip：ep01-S1 / ep01-S3 "网页定稿过首帧（fred 2026-11-01）"、ep01-S6 "#/queue 有项目方动作（spot:ep01-S6:last:3 2026-11-02T12:46）"、ep02-S1 "网页定稿过首帧（? 2026-10-31）"；其余 ep01 11 镜 / ep02 7 镜静默跳过。delegate_seen.json / delegate_frames.json 未产生，delegate_log.jsonl mtime 不变（03:49:36）✅。
- 临时脚本（Windows Temp，-I，只读）逐镜探真实数据：ep01 全部 11 镜 **cands=[]**（pf.ok=True 的旧版本没有 Q9 项，新版本 Q9=untested / accept_retry）→ 现在没有任何镜到"过检"门槛；`_script_flags(series10_v2, 1/2)` 正常返回 adult=∅ local=∅（导入稿 data/import/runs/series10_v2/script_v2.json 有 adult / h3_check / index 字段）；`_producer_lanes` = {}（attempts.json 没有 take+lane 的 history）；ep01 11 镜里只有 7 个新版本 take.producer.lane 有值（gpu36:0 / gpu36:1 / gpu33:0 / gpu33:3），S1 / S2 / S4 / S6 的全部 take 没有道记录。
- tsc：`npx tsc --noEmit -p apps/web` rc=0 ✅。

### 必查 1 · P0-1 失败关闭整集 ✅
- `ep_set()`（:762-768）按集缓存：fn 抛异常 → `cache[ep] = "<Type>: msg"`（字符串），不再是 `{sn}`；调用处 `isinstance(adult, str)` → skip "第 N 集整集不代"（:790-796），同集后续镜命中同一缓存字符串 → 同样 skip。缓存是 frame_tick 每次调用新建（:757-758），下一拍重新判定、仍失败仍关，不是只关一拍。
- 默认判定改为 `_script_flags`（:647-663）：导入稿不存在 → `Path.read_text` 抛 FileNotFoundError；没有这一集 → LookupError；镜号坏 → ValueError；全部走异常路径 → 整集 skip。不再用 sop_gate.adult_shots_of（读不到返回空集 = 放行）。
- 成人 / 本地专用两次独立判定（:790 / :795），任一失败整集关。
- 测试：test_frame_adult_unknown_closes_whole_episode（S4 + S6 都 skip、原因含"整集不代"）、test_frame_missing_import_doc_closes_episode（导入稿删掉 → 不代）均绿；第 29 轮复现场景（adult_fn 抛异常 → S6 被代选）已不成立。

### 必查 2 · P1-3 本地专用 ✅ 判定本身 / ⚠ 副作用 P1-7
- 三路都不代：候选道以 `laptop:` 开头 → req.candidates[].route="local_only" → never_reason（:807-811）；候选没道记录（take.producer.lane 无、账本也无）→ skip "判不出来"（:803-806）；账本读不了 / 不是对象 → lanes_err → skip（:798-801）；镜级 H3 校验"本地生成 / 占位 / 暂缓" 或 route=local_only → req.route="local_only" → never_reason。tests：test_frame_laptop_lane_candidate_never / test_frame_take_producer_lane_laptop_never / test_frame_unknown_lane_fails_closed / test_frame_h3_local_only_shot_never 绿。
- **P1-7（新）· "lane 以 laptop: 开头 = 本地专用" 与 L-165 分区冲突，ep01 代选永远不触发**：config/netfix/partition.json images.laptop=[1]（note_L165：笔记本 4080 先出 ep01），tools/netfix/dispatch.py:4 "笔记本 producer 只派 laptop:0"；而 producer.py:474（L-128）本地专用作业许的是"项目方自有机器的道（笔记本 + gpu33 + gpu36）"，不是笔记本独占。所以 ep01 今后每个首帧版本都带 lane=laptop:0 → never_reason "候选里有成人 / 本地专用资产" → L-142 原文"ep01 首帧由系统代选"在当前分区下一条也不会代。方向只偏保守（不会误代），但功能等于关着。另：S1 / S2 / S4 / S6 的旧版本没有道记录 → 即便过检也永远 "判不出来"。建议：候选级只用镜级 H3 / route 判（_script_flags 的 local 已覆盖同一口径），去掉 LOCAL_LANE_PREFIX 规则；或 Take 落 route 字段后按 route 判。
- 实跑佐证：当前 ep01 没有过检候选，frames --dry 看不出这条；用 partition + dispatch 代码推导。

### 必查 3 · P1-4 项目方动过 ✅ 判定 / ⚠ 跨剧偏保守 P2-8
- `_owner_marks`（:584-627）：data/audit/*.jsonl 里 POST `/api/shots/<sid>/takes/(image|first)/<n>/(lock|unlock)`（FRAME_AUDIT_RE 与 frame_jobs.py:503 / :547 真实路由一致）→ 网页定稿 / 解锁都算；data/owner_queue/decisions.jsonl 里提到该镜、且 by≠delegate / via 不以 delegate 开头的任何动作 → 算；目录 / 文件不存在 = 无记录；read_text OSError → _Unknown → frame_tick marks_err → **每镜 skip "按动过算，不代"**（:772-775 / :782-784）。`_owner_touched` 另加 locked_by.by ∉ {None, delegate} 分支（:636-638）。tests：test_frame_web_unlocked_once_not_picked（S4 解锁 → 只代 S5）、test_frame_owner_queue_action_not_picked、test_frame_owner_marks_unreadable_fails_closed、…_ignores_s10_vs_s1（`(?!\d)` 防 S1 误匹配 S10）绿。
- 跨剧：audit / decisions 不带剧名。真实数据：series10_v2 created_at=2026-11-02T18:28，而 ep01-S1 / S3 的 lock 记录是 11-01 17:37、ep02-S1 是 10-31、ep01-S6 的 spot 决定是 11-02 12:46（且说的是"第 8 版首帧"，本剧 S6 只有 2 版）→ 全部是上一剧的痕迹。方向只偏保守（只会多 skip，不会误代）✅；代价：series10_v2 的 ep01-S1 / S3 / S6、ep02-S1 永远不代。P2-8，建议按 runs.json created_at 过滤 audit / decisions 的 at。

### 必查 4 · P1-6 "系统代选·可改" ✅（#/queue 本身仍无条目，P2-9）
- status.ts:103-110 `delegateLockOf`：locked_by[stage].by==="delegate" 且 locked[stage]===n → 版本号；`autoLockOf` 先查它再查 auto（:89-90）→ frameState 回 "auto"（:129）→ 与 auto 同状态 `auto_first`（:256）/ `auto_last`（:268），文案 `autoWord` = "系统代选·可改"。Canvas.tsx:224-226 把 auto_first 并入 lockFirstList / toReview0、ReviewRow.tsx:375 / :624 同一换版入口 → 可改 ✅。Viewer.tsx:214-217 查看器 chip "系统代选·可改" ✅。tsc rc=0 ✅。
- 残留 P2-9：(a) 只有 ShotDetail 在手时认得出（摘要 app.py:296 `_auto_locked` 只认 by=="auto"），detail 没加载的列表里会先显示普通"已定稿"；(b) #/queue（OwnerQueuePage ← GET /api/owner/queue，owner_queue.py）没有任何 L-142 / delegate 条目，"事后可在 #/queue 修改"落在画布审片行而不是 #/queue 页。要不要按 L-142 字面补 #/queue 条目，由总调度定。

### 必查 5 · P1-1 / P1-2 ✅
- hb_stale_min：resident_sync.py:1036 LC_DEFAULT=5，sop_gate.json lifecycle.hb_stale_min=5，docstring（:1101-1103）同口径；test_hb_stale_default_is_5_in_code_and_config + test_stale_heartbeat_over_5min_restarts（2.5 min running / 5.5 min 拉起）绿。
- 服务器 attempts：首次 → `requested`，`req_id` 记下、`req_counted=False`、attempts 不加（:1289-1295）；队列未执行（RQ.pending 非空）→ `queued`，不写新请求不计数（:1256-1260）；restart_done.jsonl 的 request_ids 含该 req_id 才有 done_t（_rq_state :1147-1157）；done 后 grace_min 内 → `waiting`；过 grace 仍无心跳且 req_counted=False → attempts+1、req_counted=True（:1250-1254）→ 同拍写下一条请求；3 次 → gave_up → `_lc_issue` 只在 rec["issue"] 为空时登记一次（:1270-1275）。队列读不了 → 当作 pending（不写不计，:1246-1248）。心跳变新 → running → attempts / issue / req_id 归零（:1236-1240）。tests：test_server_only_requests_never_count_or_report_p0（6 拍 66 min 只 1 条请求、attempts=0、无 issue）、test_server_attempt_counted_only_after_queue_executed_and_grace、test_grace_then_three_failures_report_p0_once 绿。
- 笔记本仍按"起了就算一次"（:1283-1286），与第 29 轮口径一致。

### 必查 6 · P2-3 ✅
- `if not cfg.get("enabled") and not dry: return []`（:741）→ dry 不受开关短路；dry 下 skip 走 out.append（:751-755），frame_pick 行 `{**row, dry, enabled}` 后 continue（:823-825），不调 lock_fn、不写 FRAME_SEEN / log / V2_LIVE。真实实跑 3 个落盘文件 mtime / 存在性不变。test_frame_dry_ignores_enabled_and_writes_nothing 绿（并断言非 dry 仍受开关）。

### P2（记录）
- P2-8 跨剧 audit / decisions 偏保守（见必查 3）。
- P2-9 #/queue 无条目 + 摘要 _auto_locked 不认 delegate（见必查 4）。
- 第 29 轮 P1-5（L-142 "总调度亲审" vs 30 分钟超时）、P2-1 / P2-2 / P2-4 / P2-5 / P2-6 / P2-7 本轮未动，仍待总调度记账 / 裁定。

### ✅ 核对通过（有出处）
- 失败关闭原则贯穿：成人 / 本地专用 / 道记录 / 项目方痕迹 / 渲染根 / 导入稿 读不了 → 一律不代，frames --dry 真实数据零 frame_pick 行。
- never_reason 仍写死（test_never_reason_still_hard_coded）；lifecycle.apply=false / first_frame.enabled=false 未动（test_hb_stale_default… 断言 apply=False）。
- 本轮没有改动任何代码 / 配置 / 真实 data/（只写本日志；临时脚本放 Windows Temp）。

### 给总调度的问题（需你定）
1. P1-7：L-165 下 ep01 全在 laptop:0 出图 → 按当前规则 ep01 一条也不代。要 L-142 真生效，必须先改 LOCAL_LANE_PREFIX 规则（建议改镜级 H3 / route 判定）。
2. P2-9：L-142 字面"在 #/queue 修改"要不要补 #/queue 条目，还是认画布审片行为准（记 L-xxx）。

### 结论
**first_frame.enabled 可否开：是（无 P0）**——P0-1 已修实证；P1-3 / P1-4 / P1-6 已落；但在当前 L-165 分区下开了也不会代任何 ep01 镜（P1-7），要 L-142 真生效需先修 P1-7。
**lifecycle.apply 可否开：是（无 P0）**——P1-1 / P1-2 已修实证；当前真实状态下开了只会判 laptop running、不动；服务器两台 20 小时旧心跳的状态（第 29 轮已记）一旦某集分区落到服务器会按新规则写请求、计数只在队列真执行后。

---

## 第 29 轮（A18 · Fable，Orca 工人 task_973f21445705，总调度派）· 11-03 14:24–14:4x · W18 PRODUCER-LIFECYCLE 独立审计（只审不改，40 分钟时间盒；开关默认关）

### 复核范围
tools/autopilot/resident_sync.py:1024-1289（lifecycle_cfg / lifecycle_stage / lifecycle_want / lifecycle_heartbeats / _server_start / lifecycle_tick / lifecycle_thread / loop）、tools/autopilot/producer.py maybe_promote（:1930-1949）+ ctrl（:1917-1928）+ 心跳写入（:2069，TICK_S=20）+ pid 单实例守卫（:3440-3462）、tools/autopilot/restart_queue.py（**审计中 14:24:07 被改**：新增 norm_mode / merged_mode，process 已按 merged_mode 调 rs.restart(host, mode)；下文按新版本判）、tools/master/sop_gate.py（judge / promote_check / promote / stage_view / status / shot_frames / check_assets / check_prompts）、services/api/ns_api/owner_delegate.py:530-710（frame_candidates / frame_choose / _owner_touched / _default_frame_lock / frame_tick / tick / _loop）+ never_reason（:200-217）+ _skip_once（:188）、frame_jobs.lock_take（:504-530）、render_router/ns_render/frame_edit.unlock（:131）、config/pipeline/sop_gate.json lifecycle{} / promote{}、config/pipeline/owner_delegate.json first_frame{}、config/render_quality.json auto_final_on_lock_runs、config/netfix/partition.json、tests/test_producer_lifecycle.py（28 条）、MASTER_PICTURE L-142 / L-147 / L-152 / L-157 / L-160 / L-163、OWNER_CANON C-10 / C-11 / C-16 / C-22。

### 实跑结果（出处）
- `pytest tests/test_producer_lifecycle.py tests/test_owner_delegate.py tests/test_sop_gate_promote.py -q`：**48 passed**（4.1 s；real-data-guard 写真实数据 0 次）。
- `resident_sync.py lifecycle --dry`（14:27:02，真实状态）：run=series10_v2 status=producing；ep01=出图(4) / ep02=资产就绪(2) / ep03=剧本(0)；producer_eps=[1] night_eps=[]；唯一目标 laptop:producer hb_age 0.7 min → **running**（不起）；服务器无目标（ep01 出图分区=laptop，L-165）。不带 `-X utf8` 直接跑 cp1252 崩（WSL 下 PYTHONUTF8 不透传，不是业务问题；restart_queue.py status 同样）。
- `owner_delegate.frame_tick(dry=True)`（真实状态）：返回 `[]`——因为 first_frame.enabled=false 时 **dry 先于开关被短路**（:626-627），dry 看不到"会代哪些镜"，config `_switch` 写的"frames --dry 先看"在开关关着时不成立（P2-3）。
- 临时目录构造（scratchpad 脚本，打桩 laptop_fn / server_fn / lock_fn，不起进程不写真实数据）：
  · 阶段=提示词 → skip"没有任何一集到出图"，laptop / server 调用 0 ✅
  · 阶段=出图、全部无心跳 → laptop:producer started + gpu33:producer started(mode=producer-only)，night_eps=[]、不起 night ✅；lifecycle.json 写入、V2_LIVE 2 行（打桩）
  · 真 sop_gate.stage_view 于临时目录（只有 P4_ep01.md + 空 autoflow）→ ep01=导入闸门 → 不起 ✅
  · 成人镜 S3（adult_fn 返回 {3}）→ skip"成人相关（只能项目方本人）"✅；普通镜 S4 同分 v1/v2 → 取 v1 ✅，标 "系统代选·可改" ✅
  · **adult_fn 抛异常（剧本读不到）→ 同集第二个镜 S6 被代选了 ❌**（见 P0-1）
  · frame_tick(dry=True) 仍写 data/owner_queue/delegate_seen.json + delegate_log.jsonl（skip 记录）（P2-3）
- 当前 data/autopilot/resident_sync.json health（14:23）：gpu33 / gpu36 producer_hb_age_min=1188.5（paused=true，20 小时旧心跳）、night_state_age_min≈2.99e7（没有 night_state）→ lifecycle 读到的是 **数字而不是 None**，一旦某集到出图/尾帧且分区在服务器，会立即请求重启（这是预期行为，但要知道现在两台服务器就是这个状态）。

### 必查 1 · 不抢跑 ✅（有一处口径说明）
- 阶段来源 = `sop_gate.stage_view`（唯一阶段模型，:1057-1063），不是别处；producer 起条件 stage ∈ {出图,出图检测,尾帧,视频}（LC_PRODUCER_STAGES）、night ≥ 尾帧（LC_NIGHT_FROM）、legacy / 非 preparing|producing 一律 skip（:1180-1186）。
- preparing 自动 promote：`sop_gate.promote → promote_check → judge(ep, 出图)`（:655-682）；judge 只看 evaluate 前 4 个阶段的证据 + 上一集复盘 done，**不读 observe_stages**（observe 只在 require 里生效）→ 正是 A1b 第 24 轮的 enforce 口径；资产缺口（check_assets gaps）/ 探针未过或过期（check_prompts fingerprint）→ judge 不过 → 不提升、不起（test_promote_not_ok_does_not_start ✅）。promote.auto=false → 只报不写（:1197-1199）。
- 口径说明（P2-1）：stage_view 的"阶段"是 current_stage（第一个没过的阶段），**不含上一集复盘**；judge(出图) 含复盘。ep N 四阶段都过但 ep N-1 复盘没 done 时：stage_view 说 ep N=出图 → lifecycle 会起 producer，但 promote / 每镜 require 都挡 → producer 起来空转。不抢跑（不派单），只是"起了没活干"。

### 必查 2 · 不误起 / 不重复起
- **P1-1 · hb_stale_min=2 与 producer 一拍最长时长没对齐**：心跳在 tick 末尾写（producer.py:2069），TICK_S=20，但一拍内含导入 / consistency / raise_gates / 打分登记，`import_err` 重试 sleep 30·(k+1)（:1708）单次就能超 2 分钟；服务器健康报警用的是 ≥10 分钟（:726）。心跳 >2 min 即触发 restart_producer.ps1：先运维暂停 ≤180 s 等 inflight=0、不满也杀（ps1:20-33）→ 在途单靠租约过期重派。误触发不丢数据但白跑一轮（11-01 04:42 事故同类）。建议 hb_stale_min ≥ 5（或 ≥ 3×实测最长 tick），放开前用 ops/logs/producer_series10_v2 实测一拍上限。
- draining / 刚重启窗口：笔记本 state ∈ {exited, draining} → None → "没有心跳" → 起（:1105-1107）。lifecycle 自己起的受 grace 10 min 保护（last_try，:1239）；**别人**（deploy / release_tick / 人工 ps1）正在 drain 时 lifecycle 会并发再跑一次 ps1。后果有界：producer `acquire_pidfile` O_EXCL + 心跳新鲜判活（:3440-3462）→ 不会双实例；只是多杀一次 / 多等 3 分钟。P2-2。
- grace 10 min ✅（test_grace_then_three_failures_report_p0_once）；连续 3 次只登记一次 ✅（rec["issue"] 判空，:1225-1228；dry 不登记）。
- **P1-2 · 服务器目标的 attempts 数的是"写了请求"不是"重启了"**：`_server_start` 只追加 restart_requests.jsonl 并立刻 ok=True（:1133-1139；已有待办还 dedup ok）；restart_queue 30 分钟 gap（RESTART_MIN_GAP_S）内不执行。时间线：t0 请求(1) → t10 dedup(2) → t20 dedup(3) → t30 gave_up → **P0 issue**，而队列可能 t30 才刚执行。假 P0 + 之后 attempts 不归零（只有心跳变新才 reset）。建议：服务器目标在 RQ.pending(host) 非空时记 waiting 不计 attempts，或 attempts 只在 restart_done 出现该请求 id 后才算一次失败。
- restart_queue mode（W18 自述"process 忽略 mode 一律 all"）：**14:24:07 的新版本已修**——request(mode=) / norm_mode / merged_mode（全同 mode 才保留，否则 all）/ process 记 mode + modes_requested 并 `rs.restart(host, rec["mode"])`；resident_restart.sh producer-only 确实不起 night（sh:24-37）。剩余口径（P2-4）：没写 mode 的旧请求 / 别人的请求 norm 成 all（"宁可全起"），restart_guarded 代码变更重启也是 DEFAULT_MODE=all → "阶段 < 尾帧 night 不起"只是 lifecycle 自己请求的属性，不是系统不变量；night 早起的后果有界（night 只派已定稿 + sop_gate 视频闸门过的镜）。另：同一台 producer 在跑、night 没起 → 请求 mode=all 整机重启（排空 ≤90 s 后照重启，RQ:63-66）→ 在途出图单被打断一次，是 DJ-20 既定代价，记一笔。
- 没有"人工 hold"：总调度 / 运维有意停掉某台 producer（不改 runs.json status）时，apply=true 下 2 分钟内会被拉起；只有 runs.json paused / archived 能停它。P2-5，建议 lifecycle.hold:[目标] 或认 data/autopilot/lifecycle.json 里的 hold 字段。

### 必查 3 · 首帧代选（L-142）
- 触发 = 出图检测通过（postflight ok + Q9 pass + 没 master_reject/bad/quarantined/accept_retry，与 sop_gate.shot_frames 同口径 ✅）+ 自最早过检版本起 timeout_min(30) 无人定稿（:655-663）；候选只取"通过"的（C-09 ✅，test_frame_pick…：v3 没过不参选）。选择 = (-blocking, Q1+bundle 通过率, -n) 取 max → 同分取小版本号 ✅。
- **P0-1 · 成人镜失败关闭只关一个镜**（:640-644）：`adult_shots_of` 抛异常时 `adult_cache[ep] = {sn}` 只把**当前镜**当成人，同一集后面的镜（同一拍 / 以后每拍都命中缓存前的那一次）按"非成人"继续代选。实跑：adult_fn 抛异常 → ep01-S6 被代选定稿。导入稿读不到 / 剧本解析错时，成人镜首帧会被系统定稿 → 进尾帧 / 视频链；与 never"成人镜头渲染只能项目方触发"、C-22 冲突（L-147 打开后还会自动排定稿档重出）。tests 只测一个镜（test_frame_adult_unknown_fails_closed），所以绿。修法一行：异常时 `adult_cache[ep] = None` 并整集 continue。**first_frame.enabled 放开前必修。**
- **P1-3 · "本地专用候选"判不出来**：never_reason 看 `candidates[].adult / route`（:208-210），但 takes.json 的 Take 记录没有 route / adult 字段（render_router/ns_render/pipeline.py:1223 Take(...) 无此字段；route 只在 producer 的 job 上，:1652）→ 候选级检查恒为空，只有镜级 adult_shots_of 生效。test_frame_local_only_candidate_never 用夹具 route="local_only" 绿，真实数据永远不带。非成人但 local_only（H3 校验标本地生成）镜会被代选。建议：镜级用 producer.local_only_shots(script) 同口径，或 Take 落 route。
- **P1-4 · "项目方动过的不代"实际判不到**：`_owner_touched` 靠 `locked_history[].stage=="image"`（:586-588），但只有 tools/debug/unlock_owner.py 写 locked_history；网页解锁 frame_edit.unlock（:131-140）只 pop locked / locked_src，不留痕 → 项目方自己锁过又解锁的镜，30 分钟后被系统定稿（推翻项目方决定，never 第 4 条）。seen_row 分支只覆盖"系统代选过被撤"的情况。建议 frame_edit.unlock 写 locked_history（by / at），或 frame_tick 查 data/audit 里该镜的 lock/unlock 写请求。
- **P1-5 · L-142 原文 ≠ 代码触发条件**：MASTER_PICTURE L-142 = "过检 **+ 总调度亲审后**，项目方事后可在 #/queue 修改"；代码 = 过检 + 30 分钟无人点，没有总调度亲审步骤。L-160 给总调度全权，可以裁定"30 分钟超时 = 亲审的替代"，但要在 L-xxx 记一笔，否则是按 owner_delegate.json 的 _doc 而不是账本在跑。
- **P1-6 · "系统代选·可改"在 #/queue 没有呈现**：label 只写进 takes.json locked_by.image（by="delegate"）；apps/web 全库没有"系统代选"/ "delegate:L-142" 字样，status.ts / Viewer.tsx 只认 `locked_by.by === "auto"`（自动定稿·待复审）→ 网页把它显示成普通定稿，#/queue 没有条目、没有"改"入口（只能去画布换版本）。L-142"事后可在 #/queue 修改"、C-10"要他拍板的进 #/queue"未落实；汇总页 render_page 的 acts 也不含 frame_pick 事件（只过滤 pick/gate_*）。
- 写 delegate_log（log()，event=frame_pick）+ delegate_frames.json + V2_LIVE（_frame_live）✅；与 L-136 无关 ✅：tick() 在 active() 之前先跑 frame_tick（:712-714），test_frame_runs_even_when_l136_inactive 绿。
- L-147 接线 ✅：_default_frame_lock → frame_jobs.lock_take（画布同入口）→ FT.auto_final_on_lock；render_quality.json auto_final_on_lock=false、auto_final_on_lock_runs.series10_v2=false（等共用验收并回）→ 现在代选只定稿不排定稿档；final_job=false 时 V2_LIVE 不写"已排定稿档"。防写错剧守卫（P.shot_dir(sid)/takes.json 必须 == 扫到的文件）✅。
- :8800 后台每拍 importlib.reload 本模块（:844-850）→ 改 owner_delegate.json first_frame.enabled=true 即生效，无需重启；**反过来说 P0-1 的修法落盘也即生效**。

### P2（记录）
- P2-1 stage_view 不含上一集复盘 → producer 可能空起（见必查 1）。
- P2-2 别人 drain 时 lifecycle 并发跑 ps1（pid 守卫兜底，不双起）。
- P2-3 frame_tick(dry) 被 enabled 短路、且 dry 仍写 seen/log；建议 dry 跳过 enabled 判断并不落盘。
- P2-4 mode=all 的其它来源（见必查 2）。
- P2-5 没有人工 hold。
- P2-6 L-165（笔记本先出 ep01、gpu33 加回 1）只在 partition.json note_L165，MASTER_PICTURE 没有 L-165 行（账本缺项）。
- P2-7 restart_queue.py 14:24 的 mode 改动没有对应测试（tests 里 merged_mode/norm_mode 只在 test_w17b_release_p1.py 被引用），属 cut B 未复审代码。

### ✅ 核对通过（有出处）
- C-16 阶段 < 出图不起：lifecycle_want 按 stage_index（:1072-1077）+ 实跑 S1 / S2b。
- promote 两处写者（producer.maybe_promote、lifecycle_tick）都走 sop_gate.promote，auto=true 才写，status_history by=auto:*（test_promote_default_path_writes_status_history_auto）。幂等：翻一次后 status=producing，promote_check 直接 False。
- 服务器 health 过期 >15 min = unknown 不起（:1113-1116；test_server_health_stale_is_unknown_not_started）；producer_run_mismatch → 当无心跳 → 起（ISS-1103-033310 口径）。
- 同一台一拍只起一次（started_hosts，merged）；laptop 走 restart_producer.ps1 -Run <run>，ps1 respect 原暂停（wasPaused 不 resume）。
- lifecycle 线程独立、异常只记日志（:1272-1286）；dry 不写 lifecycle.json、不报 issue、不写 V2_LIVE（test_dry_plans_without_acting_or_writing）。
- never_reason 仍写死，改 json 打不开（test_never_reason_still_hard_coded）。

### 给总调度的问题（需你定）
1. P1-5：L-142"总调度亲审"是否以"30 分钟超时"替代？要记 L-xxx。
2. P1-1：hb_stale_min 2 → 5？要不要先实测一拍上限。

### 结论
**lifecycle.apply 可否开：否**——P1-1（2 分钟误判拉起）、P1-2（服务器 attempts 假 P0）先修；无 P0。修后可开（当前真实状态下开了也只会判 laptop running、不动）。
**first_frame.enabled 可否开：否 + P0-1**（成人镜失败关闭只关一个镜，剧本读不到时成人镜会被系统定稿）；同批修 P1-3 / P1-4 / P1-6，P1-5 由总调度记账裁定。

---

## 第 28 轮（A17 · Fable，Orca 工人 task_5f3582fae349，总调度 MASTER-WSL 派）· 11-03 14:06–14:2x · W17 RELEASE-AUTO 独立审计（只审不改，45 分钟时间盒）

### 复核范围
tools/autopilot/release_tick.py（release_once / acquire_lock / CliRunner / handover_once / tick）、tools/qa/system_version.py W17 段（gates:170-212、release_cfg / pytest_n / xdist_stall_s / _proc_table / proc_tree_cpu / run_watched:214-333、build_tree_from_list:351-389、cut_lock:731-753、deploy:1289-1325、main handover/release:1538-1593）、config/pipeline/release.json、resident_sync.py release_thread/loop:1000-1036、ops/autostart/resident_guard.ps1、ops/autostart/restart_producer.ps1、tests/test_release_auto.py、OWNER_CANON C-25、MASTER_PICTURE L-152 / L-160 / L-162 / L-163。

### 实跑结果（出处）
- `PYTHONUTF8=1 .venv/Scripts/python.exe -m pytest tests/test_release_auto.py tests/test_system_version.py tests/test_sv_verify_lock.py -q`：**56 passed，17.11 s**，real-data-guard 写真实数据 0 次。
- `system_version.py handover --dry`（真仓库，只读）：条件 ❌deployed（release_result 不存在）❌handover_requested ✅stage（series10_v2 ep1 在“出图”≥“出图”）✅not_attempted；列出 4 步；没拿锁、没动任何进程 / 文件（release_tick.py:456-460 只在 apply 时往下走）。**注意：stage 条件此刻已经满足——第一份 deploy=true + handover=true 的请求一旦 done，换代会在同一拍自动执行（tick:563-565）。**
- 临时 git 仓 + 假 `tools/qa/system_version.py`（走真 CliRunner 子进程、真 build_tree_from_list、真 O_EXCL 锁、真 report_issue 到临时 issues/LIVE），9 个场景：
  - 绿路：cut --dry → cut → deploy 三次调用，子进程环境 NS_CUT_PYTEST_N=4 / NS_CUT_XDIST_STALL_S=600.0（来自 release.json），结果 done / deployed=True，CHANGELOG + V2_LIVE 各一行，锁释放；同一请求再跑 = already。
  - dry 绿、真 cut 红：failed step=cut，issue `release:cut`（blocking），不 deploy；再跑 = already（不重复登记）；**只改请求 `at` 字段** → sha 变 → 从头再跑一遍 dry+cut、再登记一条 issue（见 P2-7）。
  - deploy 子进程 rc=0 但 verify.ok=false：failed step=deploy（release_tick.py:220 自己重算 ok，不信 rc）。deploy_guard SystemExit（无报告）：failed “没拿到报告（rc=1）”。cut 崩溃无报告：同样 failed。
  - 锁被活 pid 持有：busy、零调用；锁 pid 已死：接管、跑完；result status=running 同 sha 且无锁（上次中途崩）：从头重跑。清单项不存在：failed step=tree + issue。deploy=false：done / deployed=False。
- 真机进程树（14:10，总调度手工 `cut --dry --tree 9b1a00a5` 正在跑）：30004 venv stub（0 CPU / 4 MB）→ 12528 真 python（97 CPU-s）→ 3636 pytest stub（0 CPU / 4 MB）→ 13604 真 pytest（361 CPU-s / 311 MB，无 -n，14:03:59 起，14:10 仍在跑）。证实 W17 自述“7 MB / 0 CPU 的是 stub”，proc_tree_cpu(stub) 统计子孙 = 真 python + worker，正确；串行跑 7 分钟持续吃 CPU，10 分钟“CPU 增量 < 1 s”窗口不会误杀正常慢测试。历史：-n 12 并行 815 用例 40–68 s（index.json sv-20261102-14/16、sv-20261103-01），串行超时 max(3600, 30×文件数) 够。

### P0（立即退回）
无。

### P1（启用前修，或启用后第一份真实请求前修）

**P1-1 · cut / deploy 超时只杀 stub，不杀真进程（release_tick.py:195-199）**
- 说：cut_timeout_s 14400 / deploy_timeout_s 10800 超时 → rc=124、失败登记。
- 实际：`subprocess.run(..., timeout=)` 超时只 kill 直接子进程 = `.venv\Scripts\python.exe` 启动器 stub（真机进程树已证实两层）；真正的 `system_version.py cut` 孤儿继续跑，可能在 release 已记 failed、issue 已登记之后仍 commit / tag / push，deploy 同理可能在“失败”之后继续推服务器。system_version 自己的 `_kill_tree`（:282）就是为这件事写的 taskkill /T，但 CliRunner 没用。
- 建议：CliRunner._run 改 Popen + 超时 `_kill_tree`（Windows taskkill /T /F），或复用 run_watched。

**P1-2 · resident_guard / 重启 resident_sync 会把正在跑的 release 杀一半（resident_guard.ps1:36-40；release_tick 跑在 resident_sync 守护线程里）**
- 说：resident_sync loop 需要重启才生效。
- 实际：守护按 `data/autopilot/flow/last_tick.json`（autoflow core 线程写）超过 25 分钟没更新判卡死 → `taskkill /PID /T /F` 整棵树；任何手工重启 resident_sync（启用 W17 本身、以后每次 resident_sync 改代码）也是同一动作。release 的 cut / deploy 都是它的子进程：cut 中途死 = cut_lock 挂到 45 分钟 TTL、快照目录残留、release_lock pid 死 → 下一拍从头重跑；deploy 中途死 = 服务器可能半推（deploy_host 自带 sha 校验，但 restart 请求 / verify 未做），result 停在 running → 下一拍从头重跑 → cut 报“相对上一版没有改动”→ failed + 一条假 issue，而已切出的版本不会被自动 deploy。重启路径没有任何“等 release 完”的判断。
- 今天启用时：当前 resident_sync（pid 14308，11-02 19:48 起，老代码无 release_thread）里没有 release 在跑；总调度手工 cut（pid 30004，父进程是 shell 50476）不是它的子进程，重启 resident 不影响它。启用动作本身安全。
- 建议：守护和手工重启前看 `data/system_versions/release_lock.json`（活 pid）与 cut_lock active，有就不杀、等；或把 release_thread 拆成独立进程 / 计划任务，不随 resident_sync 生死。

**P1-3 · 请求没有“必须齐哪些复审组”的清单（release_tick.py:100-124；release.json 无 required_groups）**
- 实际：validate_request 只要求 reviews 非空且每项有 group；review_blockers 只看列出的组。一份只写 `[{"group":"G2","verdict":"可入"}]` 的请求就能全自动 cut + deploy + 换代。L-157 要求 G2–G7 逐组 Fable 复审无 P0 才 cut B。现在唯一防线是写请求的人（总调度）自觉。
- 建议：release.json 加 `required_groups: ["G2","G3","G4","G5","G6","G7"]`，release_once 缺组 = not_approved。

**P1-4 · cut_lock TTL 45 分钟（system_version.py:622）< 一次 cut 可能的时长，手工 cut 与自动 release 会撞**
- 实际：cut_lock 只在开始时写一次 expires_t（:735），不续期；而 W17 自己给 cut 的超时是 4 小时，xdist 僵死自愈路径 = 10 分钟 stall + 串行重跑（最长 4050 s）≈ 78 分钟。release_once 判“有人在 cut”只靠 `cut_locked()`（:296）。总调度手工 cut 跑过 45 分钟后，release_thread 下一拍会并行再起一个 cut：两者 `next_id()` 算出同一个 sv 号 → 同一个快照目录 SNAP_BASE/sv、同一个 docs/system_versions/<sv>.md；HEAD 由 update-ref CAS 保护只会成一个，但另一个的报告 / 快照 / index.json 会互相覆盖。今天 13:42 / 13:55 / 14:00 三次手工 cut 都在跑，这个窗口是真实的。
- 建议：CUT_LOCK_TTL_S ≥ cut_timeout_s，或 cut 期间每道闸门后续期；release_once 另看 lock_history 最近一条 start 无 end。

**P1-5 · handover 一步失败不停，继续做后面的步（release_tick.py:474-513）**
- 说：“每步写 V2_LIVE，失败 report_issue”。
- 实际：① 笔记本 restart_producer.ps1 失败（例如 V2 producer 没起来，脚本不打印 restarted → ok=False）后，② 仍向两台服务器投 restart 请求、③ 仍 kill bench2 / bakeoff。L-152 口径是“起 V2 之后再停旧”；现在是“不管 V2 起没起都停旧、都重启服务器”。每步失败确实都登记 issue，attempted=True 在第 ① 步之前就写（:470-472）所以严格只试一次（--force 重做），这两点都对。
- 建议：任一步 ok=False 即 break，后面的步记 skipped。

### P2（记录，下轮跟）

**P2-6 · proc_tree_cpu 不含根进程自己的 CPU（system_version.py:264-279）**：在 venv stub 下正确（根 = stub，0 CPU）。若 PY 不是 stub（.venv 不在 → sys.executable；或 Linux），`-n 0` 串行 pytest 没有子孙 → 树 CPU 恒 0 → 10 分钟后被当僵死杀掉（code 125），而且这正是自愈重试用的 -n 0 路径。建议把根进程自己的 CPU 也加进去（对 stub 加 0 无害）。Windows PID 复用会把无关进程算成子孙 → 只会高估 CPU（漏判，安全方向）。

**P2-7 · “同一请求只跑一次”= 内容 sha，改 `at` 就重跑**：按设计（“改请求才会再跑”）。红了改 at 重跑 = 全套闸门再跑一遍，不绕闸门；但对已 done 的请求改 at 会再 cut 一次 → “没有改动”failed + 假 issue。建议 done 后对同一 list+reviews（忽略 at）直接 already。

**P2-8 · 中途异常后 result 停在 running，下一拍从头重跑**（release_tick.py:273-275、303-354）：真 cut 已 commit 之后任何异常（例如 report_issue 写文件 OSError、_wj 失败）都会让下一拍重新 cut → “相对上一版没有改动”→ failed，已切的版本永远不会被自动 deploy。建议 running 态按 step 续跑（已有 sv 就直接 deploy）。

**P2-9 · Windows `_pid_alive` 用子串判断（release_tick.py:131-134）**：`str(pid) in tasklist 输出`，pid 123 会匹配 1234 或内存列数字 → 锁持有者已死仍判活 → 锁要等 6 小时 TTL。另：LOCK_TTL_S 6 h < cut 4 h + deploy 3 h，TTL 到期即判 stale（:156 是 or），手工 `system_version.py release` 可能在合法长 release 第 6 小时抢锁（release_thread 自己是串行的，不会自撞）。

**P2-10 · 停 bakeoff 的 bash -c 外壳会报 STILL**（release_tick.py:499-509）：`kill -TERM` 发给正在等前台子进程的 bash，bash 要等子进程退出后才死，5 s 后 `kill -0` 仍在 → result=STILL → r3.ok=False → 登记 issue，虽然 `python run.py gen` 本身也匹配并被 TERM 了。建议 STILL 的再等 10 s 复查一次，或对 bash 外壳按子进程状态判。

**P2-11 · release_thread 的模块快照**：release_thread 进程内缓存 system_version（RT._MODS），release_cfg / build_tree / cut_locked 用启动时的代码，cut / deploy 走子进程用磁盘代码；release.json 改了立即生效，release_tick.py / system_version.py 的 in-process 部分改了要重启（又回到 P1-2）。

### ✅ 核对通过（有出处）
- 绝不绕闸门：dry 绿真 cut 红 → 停（临时仓 B 场景；release_tick.py:320-329）；deploy 失败 / verify 不过 / 无报告 → 停（:218-225、:200-203）；每条 failed 都走 fail() → report_issue blocking（:306-311），invalid 也登记（:287），not_approved 按设计不登记（还在审）。没有任何把 ok=false 当成功的路径：cut 看报告 ok，deploy 重算 ok = rc==0 ∧ 所有 host ok ∧ verify ok。
- 并发：release_lock O_EXCL + pid 活检 + TTL（:146-164）；cut_lock 活跃 = busy 不写结果（:296-298，test_cut_lock_active_means_wait）；release_thread 单线程、tick 阻塞到 release 结束，没有两拍重入；请求文件被同时写 = 后写赢，release 读一次 bytes 钉 sha，中途改了下一拍再跑新的。
- handover：--dry 不拿锁、不执行（:456-460，真机实跑）；--apply 条件不满足不动（test_handover_conditions_not_met）；attempted 在动手前写、--force 才重做；只停不删（kill 命令只有 kill/sleep/echo，:499；test 断言无 rm）；protect = DEFAULT_PROTECT（producer / night / fwd / ComfyUI main.py --listen / resident_sync / sshd）+ release.json（uvicorn / audio_post）+ sentinel S16；legacy 匹配很窄（bench2\.py；run\.py gen --models=|score_srv\.py 且 cwd 含 /bakeoff/），clip_srv / ns_vqa 不会命中；score_srv 只在 tools/bakeoff 用，不是生产 VQA。restart_producer.ps1 只在成功时打印 restarted，_laptop_restart 以此判 ok（:447）。
- xdist 自愈：stub 孙进程统计正确（真机进程树证实）；stall 窗口 10 分钟 + 每 30 s 采样，比较的是“≥10 分钟前那次采样到现在的 CPU 增量”，串行慢测试持续吃 CPU 不会被误杀；超时并行 2400 s / 串行 ≥3600 s，历史并行 40–68 s；僵死 → 杀整棵树（taskkill /T）→ -n 0 重跑一次，记 cut 报告 xdist_heal（:181-190、:897-899）。
- resident 线程：每拍异常捕获、记日志、继续（resident_sync.py:1018-1019），失败关闭；不与 asset / autoflow tick 抢锁（release_lock 只有 release / handover 用，cut_lock 别人只读）；enabled 以 release.json 为准（RELEASE_TICK=True 常开）。
- AUTO_CODE_PUSH=False（resident_sync.py:850）：主 loop 不再推代码 / 重启，与 deploy 不冲突。

### 给总调度的问题（需你定）
1. P1-3：required_groups 是否就按 L-157 的 G2–G7？cut B 之后的小版本（例如只改 tools/qa）是否允许少组？
2. P1-2：启用 W17 的 resident 重启请等当前手工 cut sv-20261103-02 结束后做（虽然不是它的子进程，但 cut_lock 活跃时 release_thread 也只会 busy），并确认以后 resident_sync 重启流程先看 release_lock。

**结论：W17 可否启用（resident 重启后让它接管发版）：是。P0 = 0；P1 = 5（P1-1 超时只杀 stub、P1-2 重启杀 release、P1-3 无必需复审组清单、P1-4 cut_lock 45 分钟撞手工 cut、P1-5 换代一步失败不停）。建议：现在就可重启 resident 让 release_thread 空转（无请求 = idle）；写第一份真实 release_request 前先修 P1-1 / P1-3 / P1-5（三处都是十行以内），P1-2 / P1-4 可随下一版。**

---


## REVIEW-G4b cut B · 11-03 11:2x–12:0x · G4 视频 / 后期 / 配音（33 文件）发版前复审（Fable，只读；L-153 / L-157）

**派单口径说明**：上一位 REVIEW-G4 审的是出图编译子集；本轮按 CUT_PLAN_sv17 §4 **G4 = tools/series10_video|bgm|v2style|voice10|vidlab/*、services/post/*、config/music_v2.json、video_policy.json**（33 个）逐文件 diff / 新文件通读。

**结论：G4 按现状不能进 cut B，P0 = 1（night.py 的 V2 收尾路径死路，两处连环），另有 1 个清单漏项不补则 night / deploy / sync 导入即炸。** 两处修法都是几行（见 P0 / P1-1），修完 + 补入 hosts.py 即可入版。V1（legacy）路径逐行核过没动；写真实数据副作用 0 处新增；V1 剧名 / 人物 id 硬编码只剩 legacy 分支（NAME2ID_V1 / HOST_OF_EP_V1 / ALT_SHEET，非 V1 剧全部不用）；Q9-先于-视频闸门改成失败关闭（_q9_ok / _q9_ok_file 看图模块缺 = 不过）；camera_moves 只在 camera_ab.py 的试听页标“项目方已选”，没有改启用；At 时间码（L-141）只在 vidlab/acting.py 分拍正则加了自然语言分拍，没有写死 At。

### 清单核对（`git status --porcelain -uall`，WSL 上 >120 s）
- §4 G4 的 33 个全部仍未提交（25 M + 8 ??），按归组规则（tools/series10_video|bgm|v2style|voice10|vidlab、services/post）扫全树：**没有漏在组外的 G4 文件**。
- **G4 的跨组硬依赖，其中一个不在任何组**：

| 依赖 | 被谁 import | 在哪组 |
|---|---|---|
| `tools/factory/hosts.py` 的 `video_root / video_code_managed`（工作树新增 20 行，HEAD 没有） | night.py / deploy.py / sync.py **导入时**就调 `_video_root()` → HEAD 版 `AttributeError` | **不在任何组**（§4 G6 清单只有 api_watchdog / decisions_guard / deps / repart）→ 必须补入 |
| `services/post/ns_post/run_media.py`（新） | tts.py / assemble_series / cut_export / deliver / bgm_library / night / run_ctx | G3（§4 已注明） |
| `tools/autopilot/runs.py` current_run / gate_legacy_tool / legacy_run | run_ctx / deliver / voice10 / tts._current_run | G1（cut A 已带） |
| `tools/master/sop_gate.py` filter_video_specs / video_dispatch_ok / vidgen_guard | build_jobs / night / vidgen | G1（cut A 已带） |
| `ns_recipes.compiler.video_policy`、`ns_agent.gen_contract.style.segment_of`、`ns_agent.cast_table.speaker_cast / char_ids`、`ns_agent.run_paths` | build_jobs / bgm_library / speakers / tts | G2 / G3，合发即可 |
| `tools/director/edit_lock.py`（check / bgm_request / XFADE_S） | bgm_library | HEAD 已有，未改 |
| `config/factory/hosts.json` video_root | hosts.video_root | HEAD 已有 video_root（工作树只改 2 行，不在组内；不补也能跑） |

### 实跑（`.venv/Scripts/python.exe -m pytest -q -n 6`，PYTHONIOENCODING=utf-8，Windows python，工作树）
- 26 个文件 = §4 列的 5 个（test_bgm / test_cuts_v2_compose / test_merge_vid_o / test_v2_media / test_video10_resilience）+ 直接 import G4 改动模块的 21 个（test_post / test_narrator_voice / test_cutedit_assemble / test_cutedit_export / test_acting_beats / test_acting_system / test_voice10_fix / test_voice10_s10 / test_post_h3_dialogue_aud / test_fix_ep02_assemble / test_fix_ep02_round2 / test_recipe_pika_default / test_prodmerge_o / test_shot_audio_uirsi / test_voice_preview_uirsi / test_factory_hosts / test_sop_gate / test_vqagate / test_motion_qc / test_t42_projects / test_colormatch）：

```
FAILED tests/test_merge_vid_o.py::test_build_base_keeps_v2_scoped_camera_move
FAILED tests/test_prodmerge_o.py::test_fanout_spreads_seeds_over_free_lanes
2 failed, 357 passed, 1 skipped, 33 warnings in 685.82s (0:11:25)
EXIT=1
```
- 2 红定性（都不是 G4 的真 bug）：
  1. `test_merge_vid_o::test_build_base_keeps_v2_scoped_camera_move` = **陈旧测试（数据快照）**：测试把 ep01-S8 H3 里的 `"The camera pushes in with small amplitude"`（大写 T）替换成 V2 运镜句再断言；V2 导入稿 `data/import/runs/series10_v2/script_v2.json`（04:50 重导，晚于测试 04:22）里这句现在是 `"…and the camera pushes in with small amplitude"`（小写），replace 成空操作 → 断言红。实跑 `build_jobs.set_run('series10_v2'); load_specs()['ep01-S8']` 确认 H3 含该句（小写）。改测试用不区分大小写的替换即可；不是 build_jobs / prompt.py 的问题。
  2. `test_prodmerge_o::test_fanout_spreads_seeds_over_free_lanes` = **陈旧测试，且属 G6**（文件 ?? 未跟踪、不在清单）：第 277 行断言真实 `config/pipeline/producer.json` fanout.enabled is True，而总调度 L-161 已把它关成 false（`_note` 写明“cut B 进版关”）。测试要跟着决定改；G4 无关。
- 用 `-n 6` 时 conftest 的 real-data-guard 汇总行没有打印（串行才有）；退出码 1 只来自上面 2 红。
- 额外实跑（见 P0）：`NS_RUN=series10_v2` 下 `import night; night.voices_ok()` → True；`night.tts_missing()` → `"音色表读不了：当前剧 series10_v2 是资产包模式：音色必须按剧取（load_voice_config(run=...)）…"`；`NS_RUN=series10_v2 tools/assemble_episode.py ep01` → 退出码 2（guard_asset_pack_run 拒绝）。
- 曲库：config/music_v2.json 三条曲目文件都在、sha256 全对。

### P0
- **P0-1 · night.py 对非 V1 剧的 finalize 永远走不到合成（两处连环，同一函数）**。`night.py:357` `tts_missing()` 调 `tts_preflight(root=ROOT)` **没传 run** → `tts.py:318` 走 `load_voice_config(root/config/voices.json)` → 路径等于 VOICES_JSON 且当前剧是资产包模式 → `VoiceRunRequired` → 返回“音色表读不了” → 每集都 `hold_tts`，永不合成（实跑复现，见上）。就算把 run 传进去，`night.py:396` 接着起子进程 `tools/assemble_episode.py`，而本批给它加的 `guard_asset_pack_run()`（assemble_episode.py:62-77）对资产包剧直接退出 2 → `assemble_failed`，自动重试 3 次后终态。也就是说 MERGE-VID-O 的标题功能“V2 并回 V1 视频链”在最后一步是死的；V1（LEGACY）两处都不受影响。`test_merge_vid_o::test_deploy_and_night_follow_run` 只断言路径常量，`test_v2_media::test_assemble_episode_tool_refuses_v2` 只测 guard 本身，没有一条测试走 night.finalize 的 V2 分支。修法（CODER-PS，≈10 行）：① `tts_missing` 非 LEGACY 时 `tts_preflight(root=ROOT, run=RUN_ID)`；② `finalize` 非 LEGACY 时改调 `tools/assemble_series.py`（它已按剧取导入稿 / 曲库 / 音色，compose(run=) 11-03 已对齐）或给 assemble_episode.py 加 `--run` 走 `load_voice_config(run=)`；③ 补一条测试：`NS_RUN=series10_v2` 打桩 ssh / run 后跑 `finalize`，断言 status 不是 hold_tts / assemble_failed。失败关闭、不写坏数据，所以不是“危险”，但按 L-153 / L-157 它是本批最核心路径的真 bug。

### P1
- **P1-1 · `tools/factory/hosts.py` 必须补入 cut B**（见依赖表）：HEAD 版没有 `video_root / video_code_managed`，night / deploy / sync 三个文件在 import 时就 `importlib` 加载 hosts.py 并调 `video_root()`，快照树上必 `AttributeError`。按归组规则属 G6（tools/factory/*），§4 G6 清单没有它；`tests/test_factory_hosts.py` 也没覆盖这两个新函数（grep 0 处）。
- **P1-2 · 没有测试覆盖的关键新路径**（不挡 cut，记给 sv18）：`night.bgm_after_assembly`（V2 集级 BGM 写入点 + 自动重合成 ≤2 次）grep tests 0 处；`deliver.choose` 的 `mode == "library"` 分支 0 处；`build_jobs.name_ids()` 非 V1 走 cast_table 的分支只经 test_merge_vid_o 间接；`vidlab/acting.py` BEAT 新增的自然语言分拍（`Around/By the … second`）test_acting_beats 0 处（L-141 的落点就靠这一条正则）。
- **P1-3 · `tests/test_prodmerge_o.py`（G6）第 277 行断言与 L-161 冲突**，cut B 的 pick_tests 若挑到它闸门会红；转 G6 复审 / CODER-PS。

### P2
- **P2-1 · `deliver.choose` V2 换曲静默降级**：界面“换用这一版”走 `LB.deliver_episode(track=chosen_id)`，但 `pick_track` 只在该曲的 `use` 与段落匹配时才用它，不匹配就悄悄退回曲库第一首（没有报错、meta.json 里也看不出项目方指定被忽略）。建议不匹配时 raise。
- **P2-2 · `night.write_status` 仍 `range(1, 11)` 写死 10 集**（night.py:583 一带），V2 集数不同时状态表错位；`load_specs` 已改成“导入稿里有的全部集”，这里没跟。
- **P2-3 · `tts._current_run()` / `deliver.current_run()` 每次调用都 `sys.path.insert(0, …)`**，长驻进程 sys.path 会无限增长（night 每轮调一次）；用 `if p not in sys.path` 守一下（deliver.py 已这样写，tts.py 没有）。
- **P2-4 · `build_jobs` 非 V1 剧 `HOST_OF_EP = {}`**，没有 `video/hosts.json` 时 `meta["host"] = None` 静默不派（注释写明是有意的）；`config/netfix/partition.json` 还没有 `runs.series10_v2.video`，退回全局 video 分区（1,3,5,7,9,10 → gpu33），能跑，但 V2 集数和 V1 不同时分区要另登记。
- **P2-5 · `deploy.push_plan` managed=True 时不再推代码**（hosts.json 两台 video_root == repo → managed）：服务器上的 `tools/series10_video/run_ctx.py`、`video_policy.json` 都只靠 system_version deploy 下发；cut B 发版前 vidgen 在服务器上 import run_ctx 会失败（这是 PRODMERGE-O 的有意设计，记录以免当 bug 查）。

### ✅ 核对通过（有出处）
- **V1 路径没动**：`speakers.V1_CAST` = 原常量，`resolve_episode(cast=None)` 行为不变（test_narrator_voice / test_post 全绿）；`tts.load_voice_config()` 对 legacy 剧照读 config/voices.json；`deliver.out_dir()` legacy = config/bgm.json output.dir；`bgm/agent.py` legacy 照旧 ACE-Step；`build_jobs` legacy 保留 NAME2ID_V1 / HOST_OF_EP_V1 / ALT_SHEET / identity_crops；`night` LEGACY 时 PID / STATUS / EPS_OUT / music 目录全是原值；`voice10.py` 加 `gate_legacy_tool`（I-16）只认第一季。
- **失败关闭处处到位**：run_ctx.resolve（没登记 / 不在 scope_runs → VideoRunError）；`recipe_choice()` 没文件且政策给不出 → RecipeChoiceMissing（不再默认 i2va_pdd2）；`vidgen.policy_hold` 读不到政策 → hold；`_q9_ok` 看图模块缺 → False；`alt_crops` 非 V1 → 空（不用 V1 的脸，L-126）；`default_voiceover_speaker` V2 没 voiceover_speaker → TtsError（不退回 lin_wan）；`voice_for` 人物表有、未选音色 → TtsError（不拿女主顶替）；`UnresolvedSpeaker` “他”判不出 → 报错不猜顾沉；`music_dir` 曲库 sha 不符 → V2MediaError。
- **C-16 / L-118（BGM 整集定剪后再配）**：bgm_library 只在 edit_lock L1–L5 锁定后铺整集；night 只在合成后调它，不逐镜配。
- **C-24（运镜词表）**：camera_ab.py 只给 bolt_push_settle / handheld_follow 的已选片打标，2.5D 视差（parallax_bt.py）页面标“项目方：效果很差，不用”，没有接进任何生产路径。
- **loudnorm 重做保留偏差最小一次**（deliver.py:125-160）：三条新测试覆盖首遍候选 / 容差内不重做 / 保留最小偏差；逻辑核过无误。
- **run_ctx.strip_run / arg_run**、`deploy.main` 先 strip 再校验位置参数：`--run` 不会撞到 push/control/start 的 argv 判断。

**G4 可入 cut B：否（现状）。P0 = 1：night.py 非 V1 剧 finalize 两处连环（tts_missing 不传 run → 永远 hold_tts；assemble_episode.py 对资产包剧退出 2）。需补入：`tools/factory/hosts.py`（G6 规则，不在任何组；不补则 night / deploy / sync 导入即炸）。需剔除：无；但 `tests/test_prodmerge_o.py`（G6，未跟踪）与 L-161 冲突，cut B 挑到就红，要先改。P0 修掉 + hosts.py 补入后可入。**

---

## REVIEW-G5 cut B · 11-03 11:1x–11:4x · G5 API + 前端（67 + 6 文件）发版前复审（Fable，只读；L-153 / L-157）

**派单口径说明**：派单标题写的是“视频链 night / vidgen / H3 recipes / camera_moves / dejudder”，但 CUT_PLAN_sv17 §4 的 **G5 = API + 前端**（视频链是 G4，总调度 10:56 已派 A-G3/A-G4/A-G7；night.py / vidgen.py 在 G4 清单里，ns_recipes/*、camera_moves.yaml、director_system_prompt.md 按 §4 规则归 G2，dejudder 只在 video_policy.json（G4）/ ns_recipes/compiler.py（G2））。派单正文第 1 步明确“读 §4 的 G5 清单”，本轮按 **§4 G5（API + 前端）** 审；视频链那几个文件没审，如果总调度本意是视频链，请另派。

**结论：G5 可以进 cut B，P0 = 0。** 73 个文件逐个 diff / 通读（67 清单 + 6 个按 §4 规则属 G5 的漏项）；写真实数据副作用 0 处新增（启动副作用反而全部收进“正式实例”门，见 ✅）；V1 剧名 / 人物硬编码 0 处（这一批主要就是在拆 V1 硬编码：script_v2.json / scenes.json / state_timeline.json / music/series10 / voices.json 全改按当前剧取）；绕闸门分支 0。入版前要做两件事：**补入 `apps/web/src/v3/plainWords.ts`（P1-1，不补前端编译必断）**，以及另外 5 个漏项按下表补 / 留。

### 清单核对（`git.exe status --porcelain -uall` 11:0x = 338 条；WSL git 在 /mnt/d 上 >120 s，用的 Windows git.exe）
- §4 G5 的 67 个全部仍未提交，无一个已入 HEAD / 消失。
- `services/api/ns_api/` 下不在 G5 清单的改动文件：`script_chat.py`（§2 已归 G2 ✓）、`instance.py / look_confirm.py / owner_delegate.py / owner_pick.py`（§4 注明归 G3 ✓）。
- **按 §4 规则属 G5、但不在任何组的 6 个（补入 / 留 sv18）**：

| 文件 | 状态 | 处置 |
|---|---|---|
| `apps/web/src/v3/plainWords.ts` | 新（??） | **必须补入**。`OwnerQueuePage.tsx` / `queueActs.ts` / `stepbar.ts`（三个都在 G5 清单）`import { plainText } from "./plainWords"`——cut B 快照少了它，`tsc -b` 必断（cut 闸门不跑前端编译，查不出） |
| `apps/web/src/v3/assets/AssetInspector.tsx` | 改 1 行 | 补入（文案去技术词：“data/assets/proposals/”→“修改提议”，W5 同批） |
| `apps/web/e2e/uirsi/topbar_check.mjs` | 改 | 补入（A5 P2-1 后按新布局改的检查：换集下拉在范围条 .v3-scope；不补则 G10 / iter_gate 跑旧检查对新顶栏必红） |
| `tests/test_ui_stepbar.py` | 新，19 用例 | 补入（sop.py stepbar_view / issue_step / latest_first / pageMap 登记的唯一测试） |
| `apps/web/e2e/w5ui/shoot_w5.py`、`shoot_w5b.py` | 新 | 可补可留（Playwright 截图脚本，只 GET，产物写 data/review_pages/；不参与闸门） |

- cut B 跨组硬依赖（都在 G2–G7 里，合发即可，列出来是给拼树核对用）：`app.py` 顶层 import `instance / owner_pick / owner_inbox / pipeline_status`（G3 / G5）；`cut_project / cuts / bgm_api` → `ns_post.run_media`（G3 新文件）；`shot_audio / voice_preview` → `tts.load_voice_config(run=) / default_voiceover_speaker / speakers.Cast.from_cfg / UnresolvedSpeaker`（G4 的 tts.py / speakers.py）；`cuts._command` → `tools/assemble_series.py --dialogue-source`（G4）；`sop.py` 按路径 exec `tools/master/sop_gate.py / episode_ready.py / report_issue.py`（G1 已入 cut A / G3）；`owner_gates` → `look_confirm.confirm`、`ns_agent.looks.parse_episode_list`（G3 / HEAD 已有）；`script_autoflow` → `owner_gate.pending_fill_note`（G2；§2 表里 `KeyError: 'fill_note'` 就是它）；`wizard.import_staged` → `tools/autopilot/runs.py` 的 `registry / import_path / legacy_run / is_legacy`（G1，cut A 已带）。这些符号在当前工作树都核过存在。

### 实跑（`.venv/Scripts/python.exe -m pytest -q`，PYTHONIOENCODING=utf-8；Windows python，工作树）
- **批 1 = G5 定向**（清单 8 个测试文件 + 补入 test_ui_stepbar + 覆盖 app.py 预检门的 test_restart_api_ps1 + 覆盖 sop.py / owner_gates / bgm_api 的 test_sop / test_sop_release_fixes / test_owner_gate / test_bgm，14 个文件）：**246 passed, 4 failed，573 s**；`[real-data-guard] 写真实数据 0 次；遗留非守护线程 0；真实哨兵文件被改 0`。
- 4 红定性：
  1. `test_v2cut_o.py` ×3（`test_reimported_v2_scene_library_is_only_sk_white_cyc` / `test_ref_switch_only_registered_scenes_for_v2` / `test_v2_look_action_per_episode_with_names_and_thumbs`）= **陈旧测试，且已经修了**：断言写死 00:xx 的数据快照（场景库只有 sk_white_cyc、ep01 造型未确认），真实数据翻转后必红。W13 CUTB-PREP 在 **11:17:18** 改了这三条（改成“全是本剧登记 / 不含 V1 id”“两态按 look_confirm.episode_state 判”，不是放宽），我的批 1 在 11:16:26 起跑、收集的是旧文件。用当前文件重跑 `tests/test_v2cut_o.py`：**20 passed**（22 s）。cut B 带 11:17 之后的版本即可。
  2. `test_restart_api_ps1.py::test_revive_api_started_by_someone_during_preflight_is_not_killed` = **环境 / 时序**（文件属 G6，ops/restart_api.ps1 与该测试 mtime 02:0x 都没再动）：测试假定脚本拿锁后的第一次探针在 2–3 s 内发生、假 API 6 s 后才起；本机实际“拿到锁后”那次探针已经看到假 API 健康（`why=补起前（拿到锁后）:58622 已经健康，没动它`），只是阶段名不是测试要的“停旧进程之前”——行为（exit 0、没杀健康实例、没留锁）都对。单独重跑仍红（不是并行负载）。此前第 16 / 17 轮记录这个文件 9 passed ×3 / 3 passed，说明和本机当下 PowerShell 启动耗时有关；G6 复审时请再跑一次，不是 G5 的问题。
- **批 2 = 波及面**（import 了本批改动 API 模块、但不在 G5 清单的 23 个测试文件：test_script_inbox / test_story_runs_uirsi / test_script_chat / test_r41_uirsi / test_infra_status_uirsi / test_uirsi_check_wiring / test_review_fixes_d9 / test_editdel / test_freeze_guard / test_bad_image_uxf1 / test_h3_prompt / test_autoflow / test_factory / test_owner_run / test_prodmerge_o / test_script_ab / test_active_audit / test_audit_fixes_20261030 / test_debug_rsi / test_gpu_grab / test_llm_config_w1 / test_owner_pick / test_owner_delegate）：**438 passed, 0 failed，1033 s**（和总调度 11:26 起的 `cut --dry -n 12` 抢 CPU）。但 **real-data-guard 报“写真实数据 6 次”→ 退出码 1**：全部来自 `tests/test_factory.py::test_autoflow_resident_single_instance_and_status_filter`（`data/pipeline/asset_jobs/worker.lock`、`data/factory/agent_dispatcher/state.json.tmp*`、`data/factory/hollywood_tick.lock`）——和 REVIEW-G2 P1-1 同一个毛病（resident.tick 没打桩 asset_tick / dispatch_tick / hollywood_tick）。test_factory.py 属 G6 清单，不是 G5 的改动；但 cut B 的 pick_tests 若挑到它，闸门会红。转 G6 复审 / CODER-PS（见 P1-4）。
- 前端：`apps/web` `npm run typecheck`（tsc -b --noEmit）**exit 0**；`node --test e2e/uirsi/scene_label.test.mjs` **4 passed**。
- 工作树在审期间只动了 1 个 G5 文件（tests/test_v2cut_o.py 11:17，W13），其余 72 个 mtime 都早于 11:1x。cut 必须 `--tree` 冻结。

### P0
无。

### P1
- **P1-1 · `apps/web/src/v3/plainWords.ts` 不在任何组**（见清单表）。三个 G5 文件 import 它；工作树 `npm run typecheck`（`tsc -b --noEmit`）**exit 0**，但那是因为文件在工作树里；cut B 的快照不带它，前端源码就是坏的（下一次 `vite build` 断）。补一行进清单即可。
- **P1-2 · 无测试覆盖的新路径**（不挡 cut，记给 sv18）：`character_hub._manifest_fill_parts / _manifest_items`（资产包模式人物页用清单补单品显示，含成人类 `local_only` 分支）——grep tests 0 处；`sop.asset_look_states`（资产包剧“确认造型”改按集算、`_s2_from_timeline` 过滤状态表的 look_unconfirmed）只经 test_v2cut_o 的 api 夹具间接覆盖；`cut_project._v2_library_choices` 只经 test_cutedit_api 一条覆盖。
- **P1-3 · 清单补入**（同清单表）：`AssetInspector.tsx`、`topbar_check.mjs`、`tests/test_ui_stepbar.py` 三个按 §4 规则属 G5 的改动不在任何组；不补的话前两个只是改动漏发（下一版再带），`test_ui_stepbar.py` 漏发则 sop.py 新增的 230 行 stepbar 代码在 cut 的 pick_tests 里零覆盖。

- **P1-4 · （G6 范围，顺带报）`tests/test_factory.py::test_autoflow_resident_single_instance_and_status_filter` 写真实数据 6 次**，pytest 退出码 1，cut 闸门挑到就红。修法同 REVIEW-G2 P1-1：该用例里 `monkeypatch.setattr(RES, "asset_tick", …)` / `dispatch_tick` / `hollywood_tick` 三个替身；或 cut B 清单暂拿掉 test_factory.py。

### P2
- **P2-1 · GET 带写副作用**：`owner_inbox.inbox()`（`GET /api/owner/inbox`，顶栏每 20 s 轮询）每次先调 `look_confirm.sync_picks(root)` → 可能 `owner_pick.enqueue_pick` / `_close_pick` 写 `data/owner_queue/requests.json`。幂等（已开着的不重投、只关 superseded），生产上就是“确认造型自动进通知”的设计；但 TestClient / decision_check 进程内打这个接口时也会写真数据（test_owner_inbox 传了临时 root，没触发）。建议 sync 放到 resident tick 或加 `startup_side_effects_allowed()` 门，和 app.py 其它副作用同口径。
- **P2-2 · sop.py 每次重新 exec 模块**：`_episode_ready_module()` / `_sop_gate_module()`（sop.py:119 / :305）没有像 `pipeline_status._gate()` 那样缓存，`project_summary` 每次调用都重新 `exec_module(sop_gate.py)`，`look_asset_state` 每个 (人物, 集) 各 exec 一次 episode_ready.py；同一进程里 sop_gate 会有两份模块对象（`ns_tools_master_sop_gate` 名字相同但对象不同）。只影响性能 / 内存，不影响判定。
- **P2-3 · wizard.import_staged 在请求线程里同步跑 producer.py 子进程**（`wizard.py:234`，timeout 1800 s）：`validate_script` 的 HTTP 请求会挂到导入完成；`subprocess.TimeoutExpired` 没接 → 500。PRODMERGE-O C-9 的方向（向导不直接写生产导入稿）是对的，只是该转成作业。
- **P2-4 · REVIEW-C P1-3（三按钮）的现状**：后端 `owner_queue.py:277 DECIDE_OPTS` / `:325` 仍是“同意 / 不同意 / 稍后”，`POST /api/owner/decide` 仍收 `choice=later`；前端 `queueActs.twoActs` 把它折成“批准 / 修改”、“稍后”不做按钮（grep 前端新增行：0 处“稍后 / 不同意”按钮；`RejectDialog` 已从 App.tsx 摘掉）。L-123 / C-09 在界面层满足；后端选项表留 sv18 清。
- **P2-5 · OwnerDecision 探针**：`probeOwnerDecisionApi` 每次页面加载 `POST /api/sop/owner-decision` 空 body 来探接口在不在。核过 `owner_gates.OwnerDecision.gate` 是必填 → pydantic 422，不进 `decide()`，不记录；但它会在 API 访问日志里留一条 422。
- **P2-6 · 与第 21 轮（A5）结论的对照**：P1-1 fallback 横幅 → 已做（`TopBarV3.tsx:606` sb-banner、`PipelineMatrix.tsx:19-22`，`issues_error` 也渲染了）；P1-2 卡点取最早一条 → 已改 `latest_first`（阻断优先 + 时间降序 + 同句去重）；P2-1 换集下拉位置 → topbar_check.mjs 已按事实改（但该文件不在清单，见 P1-1 表）。
- **P2-7 · 界面技术词**（W5 口径）：新增行里仍有 `NavTabs.helpers.ts:106`“进度接口还没生效（后台重启后出现）”、`ImageEditPage.tsx:31`“（后台重启后出现）”、`CutEditor.tsx:23` 同类——都是“后端比网页旧”时的提示，REVIEW-C P2-2 已记，不算新问题。

### ✅ 核对通过（有出处）
- **启动副作用全部进“正式实例”门**：`app.py:98-113` `_PREFLIGHT = NS_API_PREFLIGHT or not instance.startup_side_effects_allowed()` → `JOBS.restore` / `EPROD.resume_on_startup` / `PJ.resume_on_startup()` / loop watchdog `LW.start` / `_lifecycle` 留痕都受门；`frame_jobs.py:560-565` postflight sweeper 同口径；`api_snapshot.in_tests()` 非正式实例不写 `data/cache/api_snapshots`。正式实例 = `api_watchdog.py:33` 设 `NS_API_MANAGED=1`（restart_api.ps1 / laptop_autostart.ps1 都经看门狗起）。风险点：手起 uvicorn 的实例不再 restore 任务，这是 RESTARTFIX-O 的有意设计，已在第 17 轮 / REVIEW-C 记录。
- **V1 硬编码拆除（C-14 / L-126）**：`sop.py` state_files / script_file 走 `ns_agent.run_paths`，解析失败 → None（不回退 V1 的 data/ 全局文件，阻塞项 `timeline_missing`）；`timeline_foreign` 时状态表的 scene_id / 底板一律不显示；`ref_switch.scene_map / plate_options / _default_plate` 非 V1 剧只认本剧登记场景；`scene_assets.scenes_json` 清单模式不读 `data/scenes.json`；`script_library.scene_catalog`、`trash._is_current_asset_image`、`app._inputs_sig / _cache_global_sig` 同口径；`bgm_api.music_dir / _ep_dir`、`cut_project.music_choices`、`cuts._command` 资产包剧走 `run_media`（music_v2 / voices_v2），`choose` V2 直接 409；`shot_audio / voice_preview` 音色表按 run。前端 `sceneLabel.pure.ts` 删掉 WORD 表（office→办公室、gu→顾沉 这类 V1 词），登记里没有的显示“场景未登记：id”；`ReviewRow / StoryboardTable` 不再读 `data/scenes.json`。grep G5 全部新增行：`林晚 / lin_wan / sk_office_night / series10_v1` 只出现在注释和一条测试夹具（`test_cutedit_api.py` 用 V1 曲目当反例，断言 422）。
- **闸门没放水**：`owner_queue.decide` 对带 `pick_api` 的条目 409（必须走统一入口才生效）；`undo` 对 `via=owner_pick*` 的决定 409（已写进配置不能撤）；`character_hub._v2_adult` 清单读不到 → 一律不发（失败关闭）；`sop.look_asset_state` 算不出 → `ready=False` 带原因；`asset_look_states` 异常 → 每集不就绪；`pipeline_status` sop_gate 读不到 → 503 不猜；`cut_project.put_project` V2 曲目不在曲库 → 422。
- **前端编译**：`apps/web` `npm run typecheck` exit 0（工作树）；`node --test e2e/uirsi/scene_label.test.mjs` 4/4 过。
- **GET 只读**（除 P2-1）：`/api/pipeline/status`、`/api/sop/stepbar`（20 s 缓存，`_stepbar_cache` 进程内）、`/api/_instance`、character_hub 清单补显示（“不写任何文件”核过：`_manifest_fill_parts` 只改返回的 dict）。
- `sop.py:586` 把 stepbar 路由挂到 `pipeline_status.router` 上：`app.py:43` import sop 早于 `:208 include_router(PSTAT.router)`，顺序成立；`tests/test_ui_stepbar.py:104` 也断言了 openapi 里有 `/api/sop/stepbar`。

**G5 可入 cut B：是。P0 = 无。需补入：`apps/web/src/v3/plainWords.ts`（必须）、`apps/web/src/v3/assets/AssetInspector.tsx`、`apps/web/e2e/uirsi/topbar_check.mjs`、`tests/test_ui_stepbar.py`；可补可留：`apps/web/e2e/w5ui/shoot_w5.py`、`shoot_w5b.py`。需剔除：无（G5 没有一个文件需要拿出来；`tests/test_v2cut_o.py` 要带 11:17 之后的版本）。G6 侧：`tests/test_factory.py` 修 P1-4 或暂拿掉。**

---

## REVIEW-G6 cut B · 11-03 11:1x–11:5x · G6 常驻 / 哨兵 / 运维 / 开关（37 + 7 文件）发版前复审（Fable，只读；L-153 / L-157）

**结论：G6 可以进 cut B，P0 = 0。** 37 个文件逐个 diff / 新文件通读；G6 定向 pytest 15 个文件 394 过 2 红（1 红是环境口径、W13 11:19 已修并串行重跑过；1 红是时序过严的陈旧断言），但 real-data-guard 报“写真实数据 6 次”→ 退出码 1。入版前要做四件事（P1-1～P1-4）：修一行时序断言、给 test_factory.py:782 用例补三行打桩、补入 7 个按规则属 G6 的漏项、fanout 开关由总调度定。

### 清单核对（`git status --porcelain -uall` 11:1x 与 11:4x 都是 338 条，Windows git.exe 0.4 s；WSL git 在 /mnt/d 上 >120 s 被我杀掉）
- §4 的 37 个全部仍未提交、无一个消失。untracked 5 个（producer.json、test_merge_ops_o / test_prodmerge_o / test_producer_run_identity / test_restart_api_ps1）cut 前要 `git add`。
- 按归组规则应属 G6、但不在任何组（**P1-3，补入**）：`tools/factory/hosts.py` + `config/factory/hosts.json`（10:02，REVIEW-G3 P1-1 已点名：after_network 顶层 import 依赖）；`ops/autostart/restart_producer.ps1`（10:01，按剧重启：-Run 默认 runs.json primary、pid / 心跳 / control 走 runs.producer_dir、只停命令行含 producer.py 的 pid）；`ops/offline/ensure_runs.sh` + `ops/offline/resident_restart.sh`（10:02，video10_srv 退役 → `$R/models_cache/vision`、producer / night 带 --run、读不到 primary 退出码 2 不回退 V1）；`tools/autopilot/runs.py`（**cut A 之后又改**，10:03：register_run 新剧默认 status=preparing，test_prodmerge_o::test_register_run_defaults_to_preparing 守）；`tests/test_infra_resident.py`（11:03，REVIEW-G3 P1-3 同一个，归一组即可）。
- 不属 G6 的未跟踪文件：`tools/factory/agent_dispatcher.py` 在 G2 ✓、`tools/factory/autoflow_resident.py` 在 G3 ✓。
- 工作树仍在动：`tests/test_factory.py` mtime **11:19:19**（W13 CUTB-PREP：a12 用例改 Git bash / 只有 WSL 入口就 skip），我第一遍跑的是 11:1x 旧版；其余 G6 文件 11:05 后没动。cut 必须 `--tree` 冻结。

### 实跑（`.venv/Scripts/python.exe -X utf8 -m pytest -q`，PYTHONIOENCODING=utf-8）
- 15 个文件（G6 清单 9 个测试 + 按改动模块补 test_factory_hosts / test_netfix / test_producer / test_episode_pipeline / test_push_preflight_deps / test_api_instance）：**394 passed, 2 failed，901.7 s**；`[real-data-guard] 写真实数据 6 次；遗留非守护线程 0`；EXIT=1。
- 串行重跑 2 红：`test_factory.py::test_a12_atomic_sync_writes` **passed**（W13 11:19 版）；`test_restart_api_ps1.py::test_revive_api_started_by_someone_during_preflight_is_not_killed` **仍红**（45.98 s）。
- 红 1 定性 = **环境**（CUT_PLAN §3 #1 同类）：旧版用 `shutil.which("bash")` 拿到 `C:\Windows\system32\bash.EXE`（WSL 入口），`while read … mv` 对 C:/… 路径卡住 → 60 s TimeoutExpired。W13 已改成优先 `C:\Program Files\Git\bin\bash.exe`、只有 WSL 入口时 skip；串行重跑过 → 已销。
- 红 2 定性 = **时序过严的陈旧断言**（两遍都红，串行也红，不是偶发）：脚本行为是对的——rc 0、写 `restart_skipped stage=already_healthy`、别人起的 API 没被杀（`api.poll() is None` 过）；只是本机 Acquire-Lock + 父进程链 6 次 Get-CimInstance 慢于夹具 `delay=6.0`（tests/test_restart_api_ps1.py:260），健康探针在“拿到锁后”那一次就命中，而 :266 断言写死 `"停旧进程之前" in why`（实际 why = “补起前（拿到锁后）:65005 已经健康，没动它”）。改法一行：只断言 stage == already_healthy（两处 Skip-Healthy 都算），或把 delay 调到拿锁之后、预检（10 s）结束之前。不改会卡 cut 的 pick_tests（该文件在 G6 清单里必被 pick，串行重跑规则救不了）。
- **写真实数据 6 次**（会让 cut 闸门退出码 1）：`tests/test_factory.py:782 test_autoflow_resident_single_instance_and_status_filter`（HEAD 已有）调 `AR.tick(...)`，而 G3 的 `autoflow_resident.py:127` 现在每拍还调 asset_tick / dispatch_tick / hollywood_tick，用例没打桩 → 写 `data/pipeline/asset_jobs/worker.lock`、`data/factory/agent_dispatcher/state.json.tmp*`、`data/factory/hollywood_tick.lock` 各 2 次。与 REVIEW-G2 P1-1（test_epchain_o）同一类；修法照 `tests/test_epchain_o.py:88-91` 三行 monkeypatch（asset_tick / dispatch_tick / hollywood_tick → lambda {}）。
- 另一条告警：`test_prodmerge_o::test_accept_retry_is_capped_on_rescore` 导入 ns_api.app 起的 episodes-summary 线程读真实 takes.json → `services/api/ns_api/app.py:280 data["active"]` KeyError（线程内，用例仍过；G5 范围，P2-5）。

### P0
无。

### P1
- **P1-1** `tests/test_restart_api_ps1.py:266` 时序过严断言（一行），否则 cut pick_tests 必红。
- **P1-2** `tests/test_factory.py:782` 用例补三行 monkeypatch，否则 cut 的 real-data-guard 退出码 1。
- **P1-3** 补入 7 个 G6 漏项：tools/factory/hosts.py、config/factory/hosts.json、ops/autostart/restart_producer.ps1、ops/offline/ensure_runs.sh、ops/offline/resident_restart.sh、tools/autopilot/runs.py（cut A 后又改）、tests/test_infra_resident.py。漏掉前两个 G3 的 after_network 一 import 就 AttributeError；漏掉 runs.py 则 test_prodmerge_o 红、新剧又默认 producing。
- **P1-4** `config/pipeline/producer.json` **fanout.enabled=true 的出处站不住**：`_note` 写“L-155（项目方 11-03 05:0x 多卡并行）”，而 MASTER_PICTURE.md:327 这条 L-155 已标“作废：PS 侧重号”（账本正式 L-155 = 03:5x 项目方已睡；CHANNEL 10:50 MASTER-WSL：“多卡并行”若账本无记录由我补编号）。且 A1 第 19 轮 A1-11 列的“开启前补”两条都没做：① `producer.py:2399 dispatch_fanout` 不走 `hard_capped` / `obj_rate_exceeded`（:2292 / :2297 只在主循环）；② `:2640 if slot == oid: leases.release(oid)`——主槽一完成就放租约，#k 槽仍在途时对象可再被“一对象一道”派单，超 max_per_obj。现在 series10_v2 是 preparing、producer 不派单，所以不是 P0；但进版值 = 开关（同 REVIEW-G3 P2-6 口径），由总调度定：补正式编号 + 修这两处再 true，或先 false 入版。
- **P1-5（REVIEW-C P1-2 遗留，未修）** SENTINEL 对 V2 producer 仍是盲区：`tools/sentinel/remote_probe.py:25` 第 7 个参数 PDIRS，`tools/sentinel/probes.py:115` 仍只传 6 个（root files vqa ports broken lan）→ `out["runs"]` 永远 `{}`，S2 / S3 / S7 / S13 仍只看 data/producer（V1，已归档）。不挡 cut，留 sv18 第一批。

### P2
- **P2-1** `config/policies/sentinel.yaml` S28 url 写死 `http://10.0.0.36:8893/health`（与 REVIEW-G3 P2-1 gen_contract count_host 同类）；机器地址该从 hosts.json / vqa.json lan_url 取。
- **P2-2** `tools/autopilot/resident_sync.py:36` RUN_ID 仍是模块级 `primary_run(strict=True)` 缓存（A1-10 未修）：新加的 `producer_rel(RUN_ID)` / `producer_run_mismatch(hb, RUN_ID)` 在 loop 常驻期间 primary 一换就看旧剧目录、对新进程误报 A-RESIDENT-PROD-RUN。
- **P2-3** `producer.Paths(run_id=None)` 在 runs.json 读不到时 `default_run()` 返回 ""：pd = data/producer/runs/（空剧名）；`main()` 的 `run_env("")` 抛 RunNotRegistered 没接。只在没有登记表的演练目录触发。
- **P2-4（运维状态，不是 cut 问题）** 笔记本 pid 13972（11-02 01:45 起、旧代码、为已归档 V1 跑）心跳 11:18:58 仍在更新、run=None；A1b 第 22 轮“上线前提 ①：手工停掉再起新 serve”没执行；`data/producer/runs/series10_v2/` 没有 heartbeat / pid → V2 笔记本侧没有 producer。新版 restart_producer.ps1 只认 `$Pd/producer.pid`（V2 目录），停不到这个旧进程，要手工。
- **P2-5** `services/api/ns_api/app.py:280 _active` 假定 takes.json 有 `active`（G5）。
- **P2-6** 进版的开关值 = 现网状态，由总调度确认后入：runs.json series10_v2 preparing + episode 1；partition.json 借道 / 挂道清空、retired_lanes 只剩 gpu36:2；producer.json fanout true / accept true max_rechecks 2；gates.yaml video_requires_q9=true + brand_logo 阻断（与 config/vqa.json gate / checks 核过一致，judge.enforce=true）；`data/ops/api_guard_auto.json` 不存在 = 自动重启仍关（第 16 / 17 轮口径不变）。
- **P2-7** `ops/restart_api.ps1` 仍写死 `$Root = "D:\NS-Final Studio"`（HEAD 已有）；`-DataDir / -LogDir / -Port` 等只给测试。

### 核对通过（有出处）
- **写真实数据副作用**：`producer.maybe_promote` 只在 sop_gate.json promote.auto=true 才写 runs.json（现 false → 只记 promote_ready；A1-4 结论不变）；serve 的 `acquire_pidfile` O_EXCL + `_pid_holder_alive`（pid + started + 心跳 ≤600 s）+ `handoff` 排空 / 复核 / draining 不谎报 exited——代码 :3248-3420 与 A1b 第 22 轮实跑的版本一致；netfix `laptop_run_controls` / `prepare_run_controls` 只对 runs.json 登记、非 legacy、未归档的剧写 `data/producer/runs/<run>/control.json`，preparing / paused 的写成 paused=true + paused_by=runs.json（K-OPS-F20），reconcile 里 try 包住不挡主剧；merge_pull 项目方决定键（locked / locked_src / locked_history / master_gate）以笔记本为准 + `_atomic_json` 原子写；resident_sync push 四处改 `atomic_install_cmd`（逐文件 mv，同文件系统 rename）；lanes.release 只清自己的（by / to / client_prefix），不带 --by 只放借道，idle_sweep 回收前查卡上非 ComfyUI 进程、探测失败不回收；api_watchdog `child_env` 只给看门狗起的实例 NS_API_MANAGED=1；restart_api.ps1 先在 8801 验新（NS_API_PREFLIGHT + NS_POSTFLIGHT_SWEEP=0 + NS_NO_API_SNAPSHOT）再停旧、只停 `api_<Port>.pid.json` 记的树（pid + 创建时间），02:04 之后没再改，第 16 / 17 轮 + REVIEW-C 已审；restart_autoflow.ps1 只停锁里 pid 树；resident_restart.sh / ensure_runs.sh 只停 run/*.pid 里命令行对得上的进程。
- **没有绕闸门的分支**：派单候选先 `sop_gate_block` → `sop_gate.require_backoff`（首帧=出图、尾帧=尾帧；legacy 放行；判不了=不派，失败关闭）；fanout 只给已在途（已过闸门）的首帧对象加种子，每个种子算一次尝试 ≤ MAX_TRIES，兄弟种子已过只记历史不改结论；`shared_accept` 出错 → retry（score_infra）不放行，rescore 复核次数 > accept.max_rechecks 按没过处理；`--run` 只认登记表（:3752）；`register_run` 新剧默认 preparing，preparing → producing 只经 sop_gate.promote。
- **C-14 V1 隔离**：新增行里 V1 专名只在 legacy 分支——`Paths` 的 voices / music / eps_out / review 按剧（V2 → voices_v2.json、music/<run>、episodes/<run>、review_pages/<run>_video，test_prodmerge_o 守 `"series10" not in review`）；`_run_id_from_config` 默认 "" 不再 series10_v1；deps.dryrun 改 `runs.current_run`（I-16）；decisions_guard.run_id / episode_pipeline.run_dir 改认 runs.json primary；runs.py 的 DEFAULT_PRIMARY 还在但 producer.primary_now 绝不回退它（A1b CASE A/B）；video10_srv 退役（hosts.json 两台 video_root = 发版目录、`video_code_managed` 为真、脚本 NS_QC_VISION_DIR 改 `$R/models_cache/vision`，test_prodmerge_o 守 "video10_srv" 不再出现）；roles.attribute_bug 的 --run 透传到 attribute_bug.py:215。
- **默认值与 OWNER_CANON**：C-13 fanout 方向一致，但 L-140 整集就绪不变（sop_gate_block 按集判）✓；C-16 先图后视频：gates.yaml video_requires_q9=true 与 vqa.json 一致 ✓；C-11 promote.auto=false → 总调度 `sop_gate.py promote --apply` ✓；C-25 发版目录 = video_root ✓；K-OPS-F33 / F35 / S19 三条新规则各有 check 指向已过的测试 ✓。
- **跨模块符号都在**：runs.current_run / run_env / is_legacy / renders_dir / producer_dir；sop_gate.stage_view / promote / promote_check / require_backoff / config（G1 已入）；vqa.contract.sanitize / reask_eye（G3）；dispatch.control_for / global_pause / apply；remote_probe `import urllib.request`；scorecard.stage_of 非 legacy 走 stage_view、v2_live 按文件路径载 sop_gate。
- **已审轮次结论没有相悖处**：A1-1 / A1-3 / A1-5 / A1-6 修复仍在（第 22 轮核过）；第 17 轮 P1-1 端口残留 → RESTARTFIX-O 段在（REVIEW-C 核过）；第 27 轮 P1-2 untracked worker 归 G3；REVIEW-C P2-1 claim 路径仍在（设计保留）。
- 本轮没有改任何代码 / 配置、没有重启、没读 data/master/；测试写盘除 P1-2 那 6 次被 guard 拦下外都在 tmp。

### 给总调度的最后一行
**G6 可入 cut B：是（P0 = 0；G6 清单 37 个文件无需剔除）。入版前：① 修 tests/test_restart_api_ps1.py:266 一行（时序过严断言）；② tests/test_factory.py:782 用例补三行 monkeypatch（asset_tick / dispatch_tick / hollywood_tick），否则 cut 的 real-data-guard 退出码 1；③ 补入 7 个漏项：tools/factory/hosts.py、config/factory/hosts.json、ops/autostart/restart_producer.ps1、ops/offline/ensure_runs.sh、ops/offline/resident_restart.sh、tools/autopilot/runs.py（cut A 后又改）、tests/test_infra_resident.py（与 G3 P1-3 同一个）；④ config/pipeline/producer.json fanout.enabled 由总调度定：补正式决定编号并修 A1-11 两处（dispatch_fanout 走上限检查、最后一个槽退出才放租约）后再 true，或先 false 入版。**

---

## REVIEW-G4 cut B · 11-03 11:0x–11:5x · G4 出图编译（compiler build_first / gen_contract preflight·postflight·accept / frame_job / shot_language / golden_v2 收薄）复审（Fable，只读；L-153 / L-157）

**范围说明（先看）**：派单标题的 G4 = 出图编译 / 看图，与 CUT_PLAN_sv17 §4 的 G4（视频 / 后期 / 配音 33 个）不是同一组。§4 没有单独的"出图编译"清单，它并在 **G3（84 + 1）** 里。本轮按派单标题审 G3 里的出图编译 / 看图子集（下表 60 个文件：services/agent/ns_agent/{compiler, frame_job, shot_language, frame_spec, framing, bible, cast_table, run_paths, state_timeline, asset_refs, gen_contract/*, vqa/contract}、services/render_router/ns_render/{final_tier, unified_frame, pipeline}、tools/promptfix/*、tools/gen_contract/*、tools/assetmaster/*、tools/imgfix、tools/vqa、tools/bakeoff、tools/gen_scenes、tools/build_state_timeline、tools/s2_waiver、tools/series10_imggen、packages/qc/provenance、config/{gen_contract, compile/*, render_quality, s2_waivers, v2style, vqa, prompts/vqa_inspect}、knowledge/rules/{prompt, render_promptfix}、tests 11 个）。asset_jobs / asset_worker / asset_checks / hollywood_tick / vlm_pool / episode_ready / autoflow_resident / owner_* / run_media / instance 留给 A-G3。**CUT_PLAN §4 的 G4 视频组本轮没审**，总调度要另派。

**结论：G4（出图编译子集）可以进 cut B，P0 = 0。** 定向 pytest 见下；P1 两条（画布改稿路径分段后缀错配、cast_v2 --render 仍是第二条出图账）都不挡 cut，留 sv18 第一批。

### 实跑
- 基线 HEAD = 6125b3e（sv-20261103-01）。`git status --porcelain -uall` 339 条；diff 用 `diff -u --strip-trailing-cr`（工作树 CRLF，裸 diff 会把整文件标成改动）。本子集净改动约 1 700 行（新文件 accept.py 234 / cards.py 110 / shot_language.py 162 / cast_v2.py 195 / bible_series10_v2.toml 70 + 6 个新测试）。
- 定向 pytest 32 个文件（本子集 11 个测试 + 按改动文件 pick 的 test_gen_contract / unified_frame / image_jobs / frame_jobs_w2 / outer_items / state_timeline / t06_bible / s2_waiver / rescore_takes / imgmaster_compile / single_identity_face / partial_face_described / image_framing / prodmerge_o / v2cut_o / sop_gate / last_frame_specs / leica_sstar_lca / render_quality_q1 / scenes_s2_s3 / scene_segments_d2 等 21 个）：**420 passed，6 failed，1 skipped，903 s**；real-data-guard 写真实数据 0 次。6 红分类：
  - **环境 / 测试隔离 ×3**（不是真 bug）：`tests/test_promptfix_v2.py::test_p15b_v2_compile_refs_all_from_assets_v2`、`::test_v2_compile_never_opens_v1_visual_bible`、`::test_l130_segment_marker_never_in_prompt`。该文件**单跑 32 passed（2 s）**；独立进程复现（NS_RUN=series10_v2，S8 原样 / 加【幻想段】各编一次）：【场景】段 + "本镜场景：" 都在、标记已剥、`style_segment` 判对、`visual_bible.toml` 打开 0 次、`trace.faces == ["lead_f"]`。32 文件同进程串跑时被别的测试污染（golden_v2 模块级 `PROJECT = _current_run()` 在首次 import 时钉死，test_merge_img_o / test_v2cut_o 等用 `setenv NS_RUN`；test_golden_v2_checks 已用独名加载规避）。另 p15b 的断言 "refs 全在 assets_v2/" 本身已陈旧：MERGE-IMG-O 之后 O4 设定图的 half_nohead 裁图按项目 crop_dir 落在 `data/pipeline/runs/series10_v2/images/refcrops/`（来源仍是 assets_v2 的设定图），单跑时 refs 全在 assets_v2/、串跑时多出这张裁图，差异来自前面测试留下的状态（原因由 A-G3 / MERGE-IMG-O 查），建议断言改为"来源 = 清单或清单派生"。
  - **陈旧测试 / 数据态 ×3（G5，不是本组）**：`tests/test_v2cut_o.py::test_reimported_v2_scene_library_is_only_sk_white_cyc`（V2 场景库现在 6 个，全是本剧；文件 11:17 正被 W13 CUTB-PREP 改，docstring 已写明改法）、`::test_ref_switch_only_registered_scenes_for_v2`（读真实 V1 `data/state_timeline.json` 要 sk_office_night）、`::test_v2_look_action_per_episode_with_names_and_thumbs`（要第 1 集已确认造型，随 data 翻转）。
- 本轮没改代码、没重启、没读 data/master/；只读 data/import/runs/series10_v2/script_v2.json 一次（核对段落标记在哪个字段）。

### 清单核对（§4 归组）
- G3 清单 85 个文件（含 10:50 补入的 test_w7_import_followup.py）在 `git status` 里**全部存在**，没有已消失的。
- 本子集命名空间里**不在任何 §4 组**的改动：`knowledge/rules/render_qwen21.yaml`（1 行，HEADER-O 文案通用化"林晚 22 岁"→"全部角色为成年人"，按规则应归 G3 出图 / 看图 config）、`tools/vqa/after_network.py`（PRODMERGE-O：DEST 改读 hosts.json video_root，发版目录不再直推代码；依赖 **G6 的 tools/factory/hosts.py + config/factory/hosts.json**，它们也不在任何组）。建议：render_qwen21.yaml 补进 G3；after_network.py + hosts.py + hosts.json 三个一起补进 G6（分开会 ImportError）。
- 整个 status 里不在任何 §4 组的其余文件（给总调度，非本组）：apps/web/e2e/uirsi/topbar_check.mjs、apps/web/src/v3/assets/AssetInspector.tsx、apps/web/src/v3/plainWords.ts、apps/web/e2e/w5ui/shoot_w5*.py（G5）；knowledge/rules/research.yaml、packages/schema/ns_schema/h3_lint.py（G2 已点名）、tools/qa/acting_lints.py（G1）；ops/autostart/restart_producer.ps1、ops/offline/ensure_runs.sh、ops/offline/resident_restart.sh、tests/test_infra_resident.py、tests/test_asset_age_judge.py、tests/test_asset_items_w9.py（G6 / G3）；tests/test_l123_no_reject_ui.py、tests/test_ui_stepbar.py、tests/test_struct_full_rewrite.py（G5 / G2）；docs/master/HANDOVER_CODER_PS_20261103.md（G1）；`series10_v2/autoflow.json`、`series10_v2/autoflow_ep02.json`（**仓库根下多出的目录，疑似误写路径，不该进版**）；vendor/_eval 三个子模块 -dirty（§1 已说不进）。

### P0
无。

### P1（不挡 cut，sv18 第一批）
- **P1-1 · 画布改稿路径的风格后缀不按段取（L-130 在 prompt_override 分支失效）。** `frame_job.build_first:311`：`prompt_override` 时用 `ST.preset_suffix()` / `ST.image_suffix()`（不带 project、不带 segment）判断 / 补后缀；`style.preset_suffix(run, None)` 对分段剧（V2）走 `segment_preset(r, None)` → 缺省段（reality）。幻想段镜头在画布整段改稿重出（`unified_frame.render_first` ← `frame_edit.py:353/374/384`）时：改稿里带的是 fantasy 后缀 → 判"没有后缀"→ 再拼一句 reality 后缀，提示词同时含两段风格句；`job["preset"]` 仍是 fantasy_c（:324 按 segment_of 取）。I7 认任一段后缀，所以闸门放行。HEAD 版 V2 只有一句临时后缀，没有这个错配，是 L-130 分段改动新引入。修法一行：`:311` 改成 `ST.preset_suffix(project, seg_in)` / `ST.image_suffix(project, seg_in)`（seg_in 提前到 :323 之前算）。正常 producer / 资产作业路径不受影响。
- **P1-2 · `tools/promptfix/cast_v2.py --render` 仍是第二条出图 + 验收账（与 PRODMERGE-O "不再各写一套 / 帧只记 takes.json 一本账"相悖）。** golden_v2 的 --render / --rejudge 已退役（退出码 3），但 cast_v2 还保留整套 render()：借道出图写 `data/ab/v2_cast/takes.jsonl` + `data/review_pages/v2_cast/`，用自己的 vlm_check / age_check / ocr_check 判定（不走 gen_contract.accept，QB 的人数 / 合并看图口径不同）。它是 CAST-S 过渡原型，文件头自己也写"正式形态是 asset_worker"。不是 P0：只由人手动触发、编译仍走 build_first + preflight(mode=setting_candidate)、不写 takes.json。建议同 golden_v2 处理：--render 退役指向 asset_worker 的设定候选作业，或整个文件留 sv18 从清单拿掉（它只被 tests 以外的东西引用吗——grep 没有调用方）。

### P2（记录，下轮跟）
- **P2-1** `frame_job.with_note:288`、`compile_frame_v2:690`、preflight I7 非资产包分支 `:329`（`ST.preset_suffix()`）都按**当前剧**（`ST._run()`）取后缀，而 `compile_frame` 按 `project` 取：当前剧 = V2、编译 V1 归档镜（画布看 V1、frames_v2 等）时 with_note 找不到 S★ 后缀 → 补句落在风格后缀**之后**；I7 报"没有默认预设后缀"。HEAD 已如此（不是本轮退步），W7 的 V1 prompt_sha 冻结核对是在 NS_RUN=V1 下做的。sv18 统一传 project。
- **P2-2** `gen_contract/accept.py:33` `_load` 把 `tools/vqa`、`tools/pipeline` 目录插进 `sys.path`（生产进程里 producer / final_tier 都会触发）：之后任何裸 `import accept` / `import anomaly` / `import image_jobs` 都会解析到这两个目录（tools/vqa 下有同名 accept.py = Q10 旧验收）。模块本身用了独名 spec 加载，不冲突；是全局副作用。建议 spec 加载时不动 sys.path，或只在 `_load` 内临时插入。
- **P2-3** `accept.evaluate:` anomaly 检测 `host="gpu36"` 写死在 services 代码里（config/gen_contract.json Q1d_anomaly.host / Q10_accept.count_host 已有配置项）。
- **P2-4** `tests/test_merge_img_o.py::test_v2_s8_close_wardrobe_and_negative`、`test_sheet_mode_has_no_gaze_lines` 直接读真实 `data/import/runs/series10_v2/script_v2.json` 第 1 集第 8 镜并断言"穿黑色漆皮抹胸紧身短裙 / 高亮镜面漆皮 / 四分之三侧脸"：ep01 正式重导（V2_LIVE 04:05 卡点）后随稿翻转（同 REVIEW-G2 P2-4）。有 skipif HAVE_V2，cut 快照硬链接 data/ 后会跑。
- **P2-5** `config/gen_contract.json` `Q10_accept.count_host` "" → `http://10.0.0.36:8893`（gpu36 内网常驻检测服务）与 `config/vqa.json video_requires_q9 false → true`、`brand_logo blocking:true`：三处都是**运行开关**，有决定出处（V2_LIVE 11-02 21:0x VQAGATE / FACTORY；L-137；W-40），cut --dry 时按 runs.json 同样口径由总调度确认一次。
- **P2-6** `tools/vqa/accept.py`（Q10，VQAGATE 11-02）与新 `gen_contract/accept.py`（QB，PRODMERGE-O）并存：producer（G6）两道都挂（`producer.py:885` Q10、`:3006` QB），identity / outfit / prompt / count 四项判两遍、口径不同（Q10 用 tools/vqa 的 prompt 核对，QB 用合并看图）。不矛盾但重复，留 sv18 合并。
- **P2-7** `shot_language._spec()` / `_shot_v2()` `lru_cache(maxsize=1)` 进程内永久缓存 shot_spec_v2.yaml / shot_v2.py：resident 常驻进程改 yaml 不生效（run_style.json 每次读，不受影响）。
- **P2-8** `frame_job.GARMENT_ALIAS = {"深灰西装裙": …}` 与 `asset_refs.NAME_ID` 四个 V1 名字仍是模块级常量（V2 名字由 `register_manifest_names` 动态登记进同一表）。只审 C-14：不是 V2 提示词会带出的内容，但"V1 造型词 → 出图叫法"这类知识应随剧配置。HEAD 已如此。

### 核对通过（有出处）
- **唯一出图路径没有第二入口**：build_first 仍是 compile_shot 的唯一调用点（`frame_job.py:68`），prompt 出口 `ST.strip_segment_marks(body)`（:316）+ 编译器出口 `_no_segment_marks`（compiler.py:865-867）两道，段落标记只进 `job.preset / style_segment / style_warning / compile_trace`。实核：V2 导入稿里标记只在 `scene_detail`（11 处：2【幻想段】/ 9【现实段】），`style.segment_of` 扫 scene_detail → 判得到；`test_l130_segment_marker_never_in_prompt` 已去 xfail。
- **闸门没有放宽分支**：preflight I2 由"有脸槽就行"改成"主体角色必须在 face_ids 里"（:250，更严）；I3 新增 `sheet_gaps`（露脸 + 景别看得见服装 + 只有清单单品图 → fail，开关 `I3_require_sheet` 缺省 true）；I9 脸板放行只在 `_faceboard_ok`（每格 role=face、带角色 id、不重复）；I7 分段剧认任一段后缀、空镜 / 单品设定候选只认 `EMPTY_SUFFIX`，禁用词 / V1 短语照查；`apply_asset_stage` 只在 `mode=setting_candidate` 且 `asset_stage∈{face,sheet,scene,item}` 时把对应项 fail→na，写了 mode 但 stage 不认识 = I2 fail（失败关闭）；全仓只有 asset_worker.py:902 与 cast_v2.py:71 设这个 mode，API / 画布作业不带。`ContractResult.ok` 是属性，`apply_asset_stage` 在排序前改 items，结论一致。
- **共用验收失败关闭**：`final_tier.final_accept` 验收抛错 → `ok=False` 不接替定稿；`accept_retry` → ok=False；`_make_final` 不过只留版本、`_clear_error`、不 lock（:248-253）。`accept.enabled` 只对 `not is_legacy and asset_manifest` 的剧，配置读不到 = False（V1 口径不变）。`render_quality.json auto_final_on_lock_runs.series10_v2 = false`（总调度裁定先关，L-147 等并回后开），`auto_final_on_lock(path, run)` 按剧覆盖，`test_auto_final_on_lock_per_run` 断言真实配置为 false。
- **负面词**：`job_negative` 永远带 `compiler.MINOR_GUARD`；`unified_frame.build_graph` 只在 `unet != turbo 且 cfg > 1` 才把负面词写回编码器，Turbo 照旧不送（与 workflows.negative_for 一致）。
- **takes.json 单一写入口（A-04）**：`unified_frame._pf_write`、`rescore_takes.py` 改走 `P.mutate_takes(path=…)`；`test_a04_no_direct_takes_json_writes_anywhere` 全仓 AST 扫（本轮跑过）。
- **V1 / V2 切割（C-14 / L-126）**：`bible.bible_path` 资产包剧只读 `run_style.json runs.<剧>.bible`（V2 = config/compile/bible_series10_v2.toml，人物表空、无"光比1:4"、无 Leica 句），没登记 → `V1BibleRefused`；`run_paths.state_dir / timeline_json / scenes_json` 非 V1 剧指到 `data/import/runs/<run>/`，解析到 `data/` 抛 `V1PathError`；`state_timeline` 只在 legacy 剧记 V1 母版、"每镜列林晚"只对 V1；`s2_waivers` 老条目补 `run: series10_v1`、无 run 的条目只对 legacy 生效；tools/gen_contract、assetmaster、imgfix、bakeoff、series10_imggen 共 11 个历史工具把写死的 `series10_v1` 改成 `RUNS.legacy_run(ROOT)` 并加 `gate_legacy_tool`（要显式 --run）；`cards.py` V2 人物卡从本剧 P1 人物表生成，config 里的 lin_wan / gu_chen / chen_yu 卡只给旧剧；`Q1_identity.lead` / `yaw_relax.characters "@lead"` 按 `cast_table.lead_id` 解析。本子集新增代码里没有新的 V1 剧名 / 人物硬编码（除 P2-8 的既有常量）。
- **默认值与 OWNER_CANON / 决定表**：L-130（fantasy_c / reality_c2、缺省现实段 + 告警）、L-145（英文 Leica / ARRI / Kodak 质感句进 V2 后缀、中文"徕卡 / S★ / 50mm f/2 / 暖调通透"仍挡——`v1_style_phrases` 去掉了 "Leica"/"leica"，`strip_brand` 仍去镜头句里的 Leica 型号）、L-148（后缀删灯光 / 时间词）、L-149（lens auto + fusion 开）、L-147（定稿档按剧开关、先关）都能在 run_style.json / render_quality.json / test_merge_img_o 里对上，与 OVERSIGHT_LOG 第 18–27 轮结论（W7 归档剧编译冻结、W2 探针 build_first+preflight、A2 F4 括注 label、ISS-1103-023528-1509 脸板逐格、ISS-1103-024205-8856 一体件）没有相悖处。
- **golden_v2 收薄**：只剩 `--compile / --summary`，必须 `--shot`（退出码 2），`--render / --rejudge` 退出码 3；不再 import shutil、不写 data/ab、data/review_pages；`load_imported` 从 `runs.import_path` 取镜、成人镜拒绝、多人镜不再拒；`test_no_v1_skeleton_or_hardcoded_text` 守"frozen_v1 / 外滩 / 风衣 / 陆家嘴"不回来。

### 建议留到 sv18 / 从 cut B 清单拿掉 / 补入
- 本子集 60 个文件**都不用拿掉**；P1-2 若总调度要收口，可把 `tools/promptfix/cast_v2.py` 暂拿掉（没有调用方，asset_worker 不依赖它）。
- **补入**：`knowledge/rules/render_qwen21.yaml` → G3；`tools/vqa/after_network.py` + `tools/factory/hosts.py` + `config/factory/hosts.json` → G6（三者同进同退）。`series10_v2/autoflow*.json`（仓库根）不进版、让 CODER-PS 查写错路径的调用方。
- P1-1（一行）、P1-2、P2-1～P2-8 留 sv18 第一批。

**G4 可入 cut B：是。P0 列表：无。需剔除：无（可选剔除 tools/promptfix/cast_v2.py）；需补入：knowledge/rules/render_qwen21.yaml（G3）、tools/vqa/after_network.py + tools/factory/hosts.py + config/factory/hosts.json（G6）。另：CUT_PLAN §4 原 G4 视频组（33 个）未审，请另派。**

---

## REVIEW-G3 cut B · 11-03 11:0x–11:2x · G3 资产作业 asset_jobs / asset_worker / asset_checks / owner_pick / inbox（84 + 1 文件）发版前复审（Fable，只读；L-153 / L-157）

**结论：G3 可以进 cut B，P0 = 0。** 85 个文件逐个 diff / 通读；G3 定向 pytest 407 过 2 红（2 红都是随真实数据翻转的陈旧断言，不是代码 bug）；写真实数据 0 次。入版前要做三件事（P1-1～P1-3）：补入 4 个按规则属 G3 的漏项、cut B 必带 G6 的 hosts.py / hosts.json（G3 顶层 import 依赖）、修 tests/test_promptfix_v2.py 两条一行断言（或暂拿掉该文件）。

### 清单核对（`git status --porcelain -uall` 11:0x = 336 条，Windows git.exe 1 s；WSL git 在 /mnt/d 上 >120 s）
- §4 的 84 个 + §528 补入的 tests/test_w7_import_followup.py：85 个全部仍未提交，无一个消失 / 已入 HEAD。camera_norm.py / importer/script_md.py 按 §2 已归 G2 ✓。
- 按归组规则应属 G3、但不在任何组（**P1-3，补入**）：`tests/test_asset_age_judge.py`（新，06:22，W6b 判词器 25 + 28 句回归）、`tests/test_asset_items_w9.py`（新，04:59，W9 单品规格）、`tests/test_infra_resident.py`（改 +213 行，11:03，W12 / W12b 7 个用例）、`tools/vqa/after_network.py`（改，10:02，PRODMERGE-O：DEST 改读 hosts.video_root、发版目录不再直推代码）。`knowledge/rules/render_qwen21.yaml`、`research.yaml`（HEADER-O 04:25 各 1 行去 V1 人名）归 G2 同批或 G3 都行，别漏。
- **跨组硬依赖，不在任何组（P1-1）**：`tools/factory/hosts.py`（新函数 video_root / video_code_managed）+ `config/factory/hosts.json`（video_root 两台改成发版目录 /root/work/fredw/offline_20261101/repo）。`tools/vqa/after_network.py:36` 顶层 `DEST = _video_root()` 直接调 hosts.video_root()，HEAD 的 hosts.py 没有这个函数 → cut B 漏掉它们，after_network 一 import 就 AttributeError（syntax_guard 只编译、查不出）。G4 series10_video 的 deploy 同样用 video_code_managed。按规则归 G6，G6 复审请一并确认。
- 工作树仍在动：asset_worker.py / autoflow_resident.py / test_infra_resident.py mtime **11:03**（W12b：A12 第 27 轮 P1-1 的 drop_pyc + import_dep + 心跳 reloaded_deps），晚于 CUT_PLAN（04:5x）与第 27 轮（06:39）；本轮读的是这一版。cut 必须 `--tree` 冻结。

### 实跑（`.venv/Scripts/python.exe -X utf8 -m pytest`，PYTHONIOENCODING=utf-8）
- 21 个测试文件（G3 清单 19 + 补入 test_asset_age_judge / test_asset_items_w9 / test_infra_resident）：**407 passed, 2 failed, 1 skipped，198.8 s**；`[real-data-guard] 写真实数据 0 次；遗留非守护线程 0`；退出码 1 只因 2 红。
- 另跑 G6 清单里的 `tests/test_prodmerge_o.py`（覆盖 G3 的 gen_contract/accept.py 三态、final_tier.final_accept、golden_v2 收薄）：**28 passed**，2 s。
- CUT_PLAN §3 #4 `test_pending_job_left_with_passed_candidates_is_salvaged` **已转绿**（test_asset_pipeline 70 用例全过）。
- 2 红定性 = **陈旧测试**（都在 tests/test_promptfix_v2.py，`need_v2` 读真实 data/，随真实数据翻转；cut 快照硬链接 data/ 后一样红）：
  1. `test_p15b_v2_compile_refs_all_from_assets_v2`：refs 多了 `data/pipeline/runs/series10_v2/images/refcrops/lead_f_O4_sheet_s1102_half_nohead.png`——O4 设定图登记后 asset_refs.sheet_crop 按 crop_dir（config/recipes/asset_refs.json）裁的去头半身参考，源图在 assets_v2；断言“全部以 assets_v2/ 开头”过窄（测试 03:08 写时 O4 还没设定图）。不是 V1 泄漏（同一断言的 `"lin_wan" not in asset_refs` 没触发）。改法：前缀允许 crop_dir，或断言 trace 里每张参考的 source。
  2. `test_l130_segment_marker_never_in_prompt`：04:50 重导（MERGE-OPS-O）后导入稿 ep01-S8 的 scene_detail 本身 = “【现实段】透明亚克力椅在白幕左前…”，测试断言**原始** `sh.scene_detail`（带标记）在 prompt 里——与它自己要守的 L-130“标记一律不进提示词”矛盾，数据带标记后必红。改法：比较 `ST.strip_segment_marks(sh.scene_detail)`。
  两条各一行（**P1-2**）；来不及改就把 tests/test_promptfix_v2.py 暂拿出 cut B——但它另外 20 个用例是 V1 bible 失败关闭 / W-40 去 logo 参考 / L-130 分段风格的守卫，建议改不建议拿。

### P0
无。

### P1
- **P1-1** cut B 必带 `tools/factory/hosts.py` + `config/factory/hosts.json`（G6 规则，目前不在任何组；G3 的 after_network.py 顶层依赖）。
- **P1-2** tests/test_promptfix_v2.py 两条陈旧断言会让 cut 的 pick_tests 闸门红（该文件在 G3 清单里必被 pick）。
- **P1-3** 补入 4 个 G3 漏项（test_asset_age_judge / test_asset_items_w9 / test_infra_resident / after_network），否则 W6b 判词器、W9 单品契约、W12 重载的回归不进版，after_network 的“发版目录不直推代码”也不进版。

### P2
- **P2-1** `config/gen_contract.json` Q10_accept.count_host 从 "" 改成写死 `http://10.0.0.36:8893`（03:06，MERGE-IMG-O 批次，无出处说明）。机器地址该从 config/factory/hosts.json 或 vqa.json lan_url 取（K-OPS arch_scan 口径）；只影响服务器端 Q10 人数判（笔记本资产线走 anomaly.check(host="gpu36") 不读它）。
- **P2-2** `tools/promptfix/cast_v2.py`（新 195 行）把 V2 三个配角的外貌 / 服装 / 提示词和 SCENE_ID 写死在代码里（docstring 自称“过渡期原型，正式形态是 asset_worker”）。不是 V1 内容（sk_white_cyc 是 V2 场景），但 C-01 / C-02 口径下应退役进 _quarantine 或改读 P1（sv18）。
- **P2-3** `tools/pipeline/vlm_pool.py` 没有直接测试（test_hollywood_tick 注入 probe / generate 绕过它）；K-REV-V01“只认本机地址”靠 _is_local 一个守卫，建议补 1 条“非本机 url 拒绝”。
- **P2-4** render_quality.json `auto_final_on_lock_runs.series10_v2=false`（L-147 注释“等共用验收并回后由总调度打开”）：PRODMERGE-O 已把 final_accept 挂进 render_final、test_prodmerge_o 过——开关仍关，开不开归总调度；§3 #7 的“项目方 11-03 05:0x”时间字样仍在（final_tier docstring 同），入账前核。
- **P2-5** §3 #8 asset_refs.json looks_file：已在 `_looks_doc` 写明（资产包模式造型唯一来源 = 清单；tests/test_w2_merge_img.py 守住）→ 可销。
- **P2-6** 进版的开关值 = 现网状态：asset_worker.json apply_meta / render / push 开、voice / golden 关、max_parallel 2（L-140）；owner_delegate.json enabled=false 且 03:49 已到期；hollywood_score.json enabled=true（总调度 02:4x）。与 G6 runs.json 同理，由总调度确认后入。
- **P2-7** 已审轮次的 P1 均已落地：A9 第 25 轮 ①②（item_skip_reason：“无 / 0件 / 项目方编号 / （参考照）/ 项目方已上传”跳过；scene 走 sheet 模式 + person_phrases 守卫扩到 scene）✓；A12 第 27 轮 P1-1 drop_pyc ✓（test_w12b ×4 过）；A6b P2“子进程覆盖已定案状态”→ _child_save / _settled_by_tick ✓；A2 第 18 轮 F1（extras 搬入改 V1 提示词）→ W7 freeze_archived_extras 归档剧冻结 ✓。

### 核对通过（有出处）
- **写真实数据副作用**：作业 / 待办 / 清单写入全部经 `asset_jobs.guard_run`（只认 runs.json 登记剧；demo_v2 这类试跑剧拒绝）；子进程按 `root_of_job` 取数据根、`--root` 不一致不跑；`_spawn` 在 PYTEST_CURRENT_TEST 下拒起；`run_voice` 非真实仓库必须注入 runner；owner_pick 启动补执行只在 NS_API_MANAGED=1 + 单实例锁 + holds_port（instance.py）；look_confirm 只写 run 目录 look_confirm.json；hollywood_tick 只追加 metrics ledger、两边 /health 都空闲才打、Q9 一来让路；push 走 sync.verified_install 核 sha、失败只登记卡点不回滚本地清单；清单写入前核 sha0、原子写；A-04：takes.json 只经 mutate_takes（_pf_write 改走它，test_a04 守）。
- **没有绕闸门的分支**：出图候选必经 `sop_filter` → `sop_gate.require_backoff`（按 (run, 集) 退避，A1-6 稳定签名，状态落文件）；preflight `mode=setting_candidate` 只豁免 ASSET_STAGE_WAIVE 列的项，asset_stage 不认识 → I2 fail（失败关闭）；I3 露脸无设定图 → fail（C-16 资料齐全才出）；sheet 作业必须 `registered_face` 且参考按完整 sha256 对上；adult / local_only 一律拒；Q9 untested 不算过、排队超时只 retry 不换种子；年龄判词失败关闭（A6b 25/25 + 28 句）；杀子进程前 verify_proc 三要素（pid + 创建时间 + 命令行指纹）核不上不杀；salvage 只认 sha 对得上的 passed 候选且不少于 salvage_min。
- **代选 L-136**：never_reason 写死（成人 / 拍板类 / 候选 adult / local_only / 条目文字含成人词），配置打不开；owner_direction 下不冒充项目方；系统已自动选用（notice / auto_picked）的不再代选（不重复登记）；项目方在代选条目上改选 → 转 revise；到期检查读 data/audit 项目方 2xx 写请求。
- **C-14 V1 隔离**：新增行里 V1 专名只在 V1 分支（state_timeline `v1_cast`、s2_waivers 老条目补 run=series10_v1、legacy 工具经 `RUNS.gate_legacy_tool` 后用 `_LEGACY`）；compiler / frame_spec 的 V1 缺省表是 HEAD 原有且标“运行时一律经 _char_ids()”；V2 编译 `bible.bible_path` 只读 run_style.json 登记的 bible_series10_v2.toml、没登记 → V1BibleRefused（test_v2_compile_never_opens_v1_visual_bible 守）；gen_contract Q1 `lead` / `@lead` + Q1a `cards_by_run` 让 V2 不落 V1 键；run_style v1_style_phrases 去掉英文 Leica 有 L-145 出处，中文“徕卡 / S★ / R0”照挡。
- **默认值与 OWNER_CANON**：C-05 两段预设 fantasy_c / reality_c2 按 L-129 / L-130 selected、后缀只留质感（L-148）；C-09 / C-10 pick 只有“用这张 / 修改”，自动选用发“已自动选用，可修改”告知；C-13 max_parallel 2 按 L-140；C-22 成人只项目方本人；C-23 项目方上传单品不重画（owner_item_for）。
- 本轮没有改任何代码 / 配置、没有重启；测试写盘都在 tmp（real-data-guard 0 次）。

### 给总调度的最后一行
**G3 可入 cut B：是（P0 = 0；G3 清单 85 个文件无需剔除）。入版前：① 补入 tests/test_asset_age_judge.py、tests/test_asset_items_w9.py、tests/test_infra_resident.py、tools/vqa/after_network.py（knowledge/rules/render_qwen21.yaml、research.yaml 随 G2 HEADER-O 批）；② cut B 必带 G6 的 tools/factory/hosts.py + config/factory/hosts.json；③ 修 tests/test_promptfix_v2.py 两条陈旧断言（各一行）或暂拿掉该文件。**

---

## REVIEW-G2 cut B · 11-03 10:3x–10:5x · G2 写作链 autoflow / 派单器（70 文件）增量复审（Fable，只读；L-157）

**结论：G2 可以进 cut B**，条件是先修 P1-1（一行夹具，否则 cut 的 pick_tests 闸门必红）并把 P1-2 的漏项补进清单。REVIEW-A 第 2 轮之后的增量改动（K211-F 第 3 轮 / MERGE-OPS-O / MIGRATE-O / HEADER-O / SV17-O / 派单器测试编码）逐项核过，没有新入口、守卫没有误拦；没有 P0。

### 实跑
- 20 个文件（G2 清单 16 个测试 + test_merge_ops_o / test_fact_patch_guide / test_v1_leak / test_w7_import_followup）：**283 passed，0 failed，83 s**；CUT_PLAN §3 #3 的 `test_owner_gate::…took_over_via_gate` 已转绿（夹具不再带 V1 场景 id）。
- 但 **real-data-guard 报“写真实数据 2 次”，pytest 退出码 1**（见 P1-1）。
- `tools/knowledge/compile.py --check`：OK kb-20261103-6d634b14，668 条规则（HEADER-O 的 concrete_id_check 没拦任何现行规则）。
- 增量范围（mtime 晚于 04:15 的 G2 文件）：hollywood_facts / hollywood_judge / writer_*.yaml / director_system_prompt / writer_knowledge（通用化文案）、validate_qwen_script.py（QW-C1 词表单一来源 + V2 硬规则）、script_md.py（镜头 extras 读 shot_spec_v2.yaml）、import_script.py（single_source / scope_globals / v1_gate）、autoflow.py、autoflow_agent.py、test_timeline_o / test_header_o / test_agent_dispatcher。STRUCT-O 的结构项分支在这两个文件里还没有落盘（没有 STRUCT-O 标记，mtime 04:49/04:50），本轮没看到在制代码。

### P0
无。

### P1
- **P1-1 · 测试写真实数据（会卡 cut 闸门）。** `tests/test_epchain_o.py:88` 的 `test_resident_spawns_next_episode` 只打桩了 `asset_tick`，没打桩 `dispatch_tick` / `hollywood_tick`：`resident.tick` → `agent_dispatcher.tick(root=ROOT)`（config enabled=true）写 `data/factory/agent_dispatcher/state.json.tmp*`，`hollywood_tick` 建 `data/factory/hollywood_tick.lock`。guard 抛错、被 resident 的 try/except 吞掉，用例显示通过，但会话结束 guard 报 2 次 → **退出码 1**。修法：`tests/test_epchain_o.py:88` 下面再加两行 `monkeypatch.setattr(RES, "dispatch_tick", lambda ad=None: {})` / `monkeypatch.setattr(RES, "hollywood_tick", lambda runs=None, ht=None: {})`，测试不删。来不及修就把 `tests/test_epchain_o.py` 从 cut B 清单暂拿掉（代码 `autoflow.next_episodes` 不受影响）。
- **P1-2 · 本轮增量改动有 6 个文件不在 CUT_PLAN 任何一组里**（按 §4 归组规则都该是 G2，不补进去 cut B 快照就少了这些改动）：`tools/script_rsi/hollywood.py`（04:39，K211-F 第 3 轮 `worse_detail` :383 / :449，I6 拒收带 lint 原文）；`tools/knowledge/compile.py`（04:28，HEADER-O `concrete_id_check` :362 / :390）；`tests/test_fact_patch_guide.py`（04:39，测 `autoflow.FACT_PATCH_GUIDE`，已过）；`tests/test_w7_import_followup.py`（04:44，测 episode_ready，归 G3）；`packages/schema/ns_schema/h3_lint.py:328` 与 `tools/pipeline/hard_constraints.py:101`（HEADER-O 文案通用化，一行各）。
- **P1-A（REVIEW-A 第 2 轮遗留）· 未修。** `tools/pipeline/run_chain.py:176-181` 仍在 api 后端直接写 `P4_epNN.md`，不经 `adopt_full_p4`、不看 hard_blocks。仍是休眠路径：`autoflow.py:842` `be == "claude_agent"` 才走 `AG.run`，api 分支现在走不到。另外同一分支 `autoflow.py:741` 导入失败只 set `import_failed`、不写 `import_fail_sig`，一旦切回 api 后端，`pending_done`（:1071）会每拍重导（空转）。留 sv18，不挡 cut。
- **P1-B（REVIEW-A 第 2 轮遗留）· 未修。** `tools/script_rsi/v1_leak.py:39-43` `old_runs` 仍 = runs.json 里除本剧外所有剧；`docs/master/PIPELINE_SOP_V2.md` 没有“开第 3 部剧时前作 id 白名单”的步骤。第 3 部剧第一天必撞 HeaderMissing（有 `record_run_error` 3 次 halted_error 兜底，不空转）。留 sv18。

### P2
- **P2-1** `tools/validate_qwen_script.py:1020` 用模块级 `_RUN["run"]` 传“本剧”给 `motion_move` / `camera_vocab`：同进程并发 validate（API + resident 线程）会串剧；临时路径认不出剧时退回 legacy → V2 硬规则不生效（p4_adapter :101 显式传 run，主路径没问题）。
- **P2-2** `autoflow_agent.py:1181` 只在“重导失败”分支记 `import_fail_sig`；首导失败（api 后端 `autoflow.py:741`）没有，见 P1-A。
- **P2-3** REVIEW-A P2-C 仍在：`config/v1_guard.json` props 20 个硬命中常用词（纹身 / 门卡 / 红绳…）04:04 之后没改。
- **P2-4** SV17-O 夹具化没做完：`tests/test_merge_ops_o.py:22/206/227`、`tests/test_timeline_o.py:21-22`、`tests/test_header_o.py:22-28`、`tests/test_epchain_o.py:16` 仍只读真实 `data/pipeline/runs/series10_v2` / `data/import`（有 skipif，cut 快照硬链接 data/ 后能跑，但随真实数据翻转）。
- **P2-5** `autoflow_agent.py:1089` `code_n =len(` 少个空格（纯格式）。

### 核对通过（增量）
- **没有第二个入口**：推进只有 `autoflow.py run`（resident `autoflow_resident.py:102`、`owner_delegate.py:429`、`script_autoflow.py:72` 都起它，跨进程推进锁 `acquire_advance_lock`）；派单器 `agent_dispatcher.py` 只起 claude.exe（:263-286），不调 autoflow；写作包只从 `autoflow_agent.packet`（:116）出，派人请求一包一文件 `packet_request`（:297）。整集稿仍只有 `adopt_full_p4`（:1722）一个来源，chain_step / `intake_full_p4`（:1764）共用。
- **K211-F 第 3 轮**：`autoflow.py:265` `fact_id` = sha1(kind|ref)[:6]，事实偏差 id 不再随位置漂；`:278` `FACT_PATCH_GUIDE` 只追加到 fact 类目标（`patch_user` :467）；`hollywood.py:383` `worse_detail` 只改 I6 detail 文本。
- **MERGE-OPS-O**：`import_script.py:362` `single_source=bool(run)` 只对非 V1 剧；`:351` 拒绝拿 V1 导入稿当合并底稿；`:294` `v1_gate` 闸门自身出错 = 不放行；`autoflow.py:1037` `import_retry_sig` 按导入器 / 词表 / 本剧 bible 指纹，`pending_done` 只在指纹变了才重导、`halted_error` 跳过、`reopened` 自动接手。
- **MIGRATE-O**：`l141_migrate.apply_file` 只对 CLEAN_CUT 剧、原稿复制到 `data/_quarantine/l141_migrate_<日期>/`（测试用 `NSFS_L141_QUARANTINE` 指到 tmp）、审计写 run 目录；出错不挡推进。
- **守卫没有误拦**：`assert_no_v1` 只抛不改、legacy 剧直接放行；三处出口（packet :125、`final_v1_hits` :1497、导入 `v1_gate`）同一词表；QW-C1 只在 `hard_run(run)`（非 legacy）才升 block，词表按剧（`camera_norm.is_enabled(id, run)`）；本轮 283 用例没有一条因守卫误拦失败。
- **派单器测试编码**：`tests/test_agent_dispatcher.py:20` 假 claude 改为 `sys.stdin.buffer.read().decode("utf-8")`，cp936 机器已过。
- 本轮没有读 data/master/、没有改代码、没有重启；跑测试写盘都在 tmp_path（除 P1-1 那两次被 guard 拦下的）。

### 建议留到 sv18 / 从 cut B 清单拿掉
- G2 的 70 个文件**都不用拿掉**；P1-1 若来不及改，只暂拿掉 `tests/test_epchain_o.py`。
- 把 P1-2 的 6 个文件补进 cut B（hollywood.py / compile.py / test_fact_patch_guide.py / h3_lint.py / hard_constraints.py 进 G2，test_w7_import_followup.py 进 G3）。
- P1-A / P1-B / P2-1～P2-4 留 sv18 第一批。

---

## 第 27 轮（A12 · Fable，Orca 工人 ctx_f95513df610e，总调度 MASTER-WSL 派）· 11-03 06:39 · W12 RESIDENT-RELOAD 复核

**结论：P0=0；可进 sv-17（先 git add 两个未跟踪 worker 文件）；可受控重启（已于 06:3x 执行，新 pid 45872）；P1×2（同秒同 size 改动 pyc 陈旧 → W12b；untracked 文件须入 cut B）。**

# A12 · 独立审计 W12 RESIDENT-RELOAD（只审不改）— 2026-11-03 06:3x

审的对象：`tools/pipeline/asset_worker.py`（RELOAD_DEPS / sync_deps 头段）、`tools/factory/autoflow_resident.py`（asset_tick phase、run_loop 连错计数 / P0 登记）、`tools/master/master_check.py sec_resident_assets`、`tests/test_infra_resident.py` 两个 w12 用例。
方法：读代码 + 真跑（Windows venv python、NTFS 临时副本 `C:\Users\fredw\AppData\Local\Temp\w12audit\root`，复现脚本 `...\w12audit\repro.py` / `pyc.py`；不碰仓库 data/）。

### P0
- 无。

### P1（这轮必须修，不阻断 sv-17 / 重启）
**P1-1 · 版本戳比 CPython 的 .pyc 校验更细，"同秒 + 同 size" 改动会重载到旧字节码（静默半新半旧）**
- 实测（NTFS + Windows python，`pyc.py`）：隔秒写 MARK=4 → 重载、MARK=4 ✔；**同一秒内同 size 写 MARK=5 → sync_deps 返回 ['asset_checks']（戳 mtime_ns 变了、判对了）但模块里 MARK 仍是 4** ✘；同秒写 MARK=6 并先删 `__pycache__` 里的 pyc 再 sync_deps → MARK=6 ✔。
- 原因：pyc 头只记源文件 mtime（秒）+ size，同秒同 size 判"pyc 有效"，`importlib.reload` 直接执行旧字节码。戳再细（哪怕加内容 hash）都救不了这一步——问题在 reload 本身。
- 触发面：agent 一秒内对同一文件改两次且长度相同（如把 `(900, 1800)` 改成 `(600, 1200)`）；`copy2 / robocopy / rsync -t` 这类保留 mtime 的工具同 size 覆盖也一样（见 P2-1）。概率低但正是 W12 要消灭的那类"重载了却是旧代码"，且无任何报错。
- 同一问题其实也适用于 resident 对 `asset_worker.py` 本身及所有 `_load()` 的模块（spec_from_file_location 同样走 pyc 缓存）——这是 W12 之前就有的，不算 W12 退步。
- 建议（一行量级）：`sync_deps` 里 `importlib.reload(m)` 之前 `Path(importlib.util.cache_from_source(str(src))).unlink(missing_ok=True)`；或常驻进程起时 `sys.dont_write_bytecode=True` 并清一次 `__pycache__`。顺手把戳加上内容 sha1（3 个文件 <200KB/拍，可忽略）。

**P1-2 · 进 sv-17 的前提：`tools/pipeline/asset_worker.py`、`tools/pipeline/asset_checks.py` 在 git 里是 UNTRACKED（不是 ignore）**
- `git ls-files` 查：asset_worker.py / asset_checks.py 未跟踪；autoflow_resident.py / master_check.py / sop_gate.py / test_infra_resident.py 已跟踪。HEAD（sv-20261103-01）里根本没有 asset_worker.py。tests/ 下也有 ~20 个未跟踪测试（test_asset_pipeline.py、test_asset_worker_sop_backoff.py 都在内）。
- 历次 sv 提交显然不 `git add` 新文件 → "W12 进 sv-17" 对 worker 侧改动等于没进。总调度定：sv-17 前 `git add tools/pipeline/asset_worker.py tools/pipeline/asset_checks.py tests/test_asset_pipeline.py tests/test_asset_worker_sop_backoff.py`（以及是否把其它未跟踪的 tools/tests 一并收编，仓库卫生问题，非 W12 责任）。

### P2（记录，下轮跟）
**P2-1 · 戳粒度（问题 3）**：mtime_ns + size 在 NTFS（100ns）上同秒覆盖能判出（实测）；漏的只有"同 size + mtime 被保留"（实测 `os.utime` 回拨后 sync_deps 返回 []、MARK 停在旧值）。NTFS/WSL 混写不额外漏：WSL 经 drvfs 写也由 NTFS 打 mtime，resident 是 Windows python 直读 NTFS，无属性缓存。加内容 hash 是对的但要和 P1-1 的删 pyc 一起做，否则 hash 判出了、reload 仍可能拿旧 pyc。
**P2-2 · asset_checks 第一次懒加载后必多一次无谓 reload**：首拍 sync_deps 时它不在 sys.modules（跳过，连戳都不记），AC_bundle 内 `import asset_checks` 后无戳，下一拍"无戳 = 不知新旧"→ 重载一次。无害（同代码），只是每个进程第二拍多一次。
**P2-3 · 心跳里看不到 reloaded_deps**：run_loop 只把 `a["reloaded_deps"]` 写进 life.log，不进心跳（复现里拍 5 心跳 reloaded=None、life.log 有 `['asset_jobs','asset_checks']`）。master_check ⑥ 想显示"上拍重载了谁"做不到。
**P2-4 · 登记失败不再重试**：`report_asset_stuck` 返回 None → issue_id="登记失败"，之后整段连错不再尝试登记；只有 life.log 一行。建议 None 时下一拍再试。
**P2-5 · tick_fn 整体抛异常那一拍，心跳没有 state / asset_* 字段**（走 outer except 的精简心跳）→ 停摆期间若某拍 advance_runs 抛错，⑥ 那一拍会瞬时不显示资产线停摆；streak 计数不丢，下一拍恢复显示。
**P2-6 · 旧 P0 还开着**：master_check 顶部仍列 ISS-1103-051601-5d74（WATCHDOG，资产线自 04:56 全停）；现在 worker 心跳已正常（06:29，started/failed 空），受控重启后由总调度关掉。

### ✅ 核对通过（有出处）
- **问题 1 · reload 副作用 / 类身份**：asset_jobs 定义 `TrialRunInRealRepo`、`RegisterError`，sop_gate 定义 `SopGateError`，asset_checks 无类。实测 reload 后 `RegisterError is 旧类 = False`，`except 旧类` 接不住新类——但全仓库（tools / ns_* / apps / tests）**没有任何** `from asset_jobs|sop_gate|asset_checks import X` 绑定；asset_worker 里全是 `AJ.` / `_SOP.` 属性访问（运行时取到新类），且 worker 本身每拍重新执行、在 sync_deps 之后才引用。常驻进程内其它持有者：`tools.autopilot.runs` / autoflow（af）不 import 这三者；agent_dispatcher / hollywood_tick 每拍 `_load` 新对象；producer / master_check / v2_live / scorecard / episode_retro 都是别的进程或 `_load` 成独名模块（不在 sys.modules 同名下，sync_deps 不碰）。三个依赖顶层只 import 标准库，模块级只有常量 / 正则；`require_backoff` 每次 `os.open` 追加、无常驻句柄 → reload 不丢状态。ns_* 不纳入的理由成立。
- **问题 2 · 失败关闭逐拍**（`repro.py`，asset_checks.py 注入 `def broken(:`，真 `_load` + 真 `report_issue.report` 写临时 issues.jsonl / live.md）：
  拍1 state=ok phase=load streak=1 issue=None（SyntaxError，载入失败 = 不派）；拍2 streak=2；**拍3 state=reload_failed streak=3 issue=ISS-1103-062709-7d16**（issues.jsonl +1 行，who=resident blocking=true "P0 资产 tick 连续 3 拍出错（reload_failed，phase=load）"，V2_LIVE 卡点行 +1）；拍4 streak=4 **issue 同一个 id、issues.jsonl 不再加行**；拍5 修好 → state=ok、asset_error/streak/issue 全清、life.log "第 5 拍 asset_tick 恢复（此前连续 4 拍出错，卡点 …）"+"重载依赖：['asset_jobs','asset_checks']"，模块 AUDIT_MARK 就地更新；拍6/7 只重载 asset_jobs（ALWAYS_RELOAD 口径）。脚本跑了两遍 → 两行 issue，各自一遍一行 = "只一次"成立。
- **问题 4 · master_check ⑥**：真跑 `master_check.py` ⑥ 行 "resident pid 26588 第118拍 13s 前；asset_worker 13s 前（render=True …）"，无资产线告警（正确：当前 worker 正常）。用复现心跳喂 `sec_resident_assets`：停摆 → "⚠ resident 资产线停了（state=reload_failed：新旧代码对不上 / 依赖重载失败，连续 3 拍，卡点 ISS-…）"；未到线 → "资产 tick 本拍出错（连续 1 拍，未到登记线）"；正常 → []；**旧版心跳（无 state 键，即现在还在跑的 pid 26588）→ []，不误报**。与 W8 draining 无交集：draining 是 producer 心跳（`producer.py:3329`）由 sec_producers 显示，⑥ 只读 resident 心跳且只认 reload_failed/asset_failed 两值。
- **问题 5 · 测试**：`pytest tests/test_infra_resident.py tests/test_asset_pipeline.py tests/test_asset_worker_sop_backoff.py -q` → **83 passed, 1 warning, 29.6s, exit 0**（W12 报 149 是别的集合；这三个文件 83 全过）。W12 复现输出已读到（修复前 3 拍 AttributeError BACKOFF_S、修复后拍 1 重载 sop_gate），与我的复现一致。
- **sync_deps 顺序 / 失败关闭语义**：`_FRESH` 在 import 之前算；`RELOADED_DEPS = sync_deps(...)` 在任何 `AJ.` / `_SOP.` 顶层引用之前；reload 抛错原样外抛，戳在 reload 之后才 set → 坏代码不记戳、下一拍重试（测试 + 复现都验证）。`Path(f).resolve() != src` 守卫在真仓库路径（D:\NS-Final Studio，Windows 大小写）上成立：pid 26588 自 06:21 起每拍重新执行含 sync_deps 的新 worker，worker 心跳 06:29 正常、无 error。
- **现网状态**：resident pid 26588 05:26:12 启动，`autoflow_resident.py` 05:51:49 改 → **它跑的是旧 run_loop（心跳无 state 键），W12 的连错计数 / P0 / 心跳字段尚未生效；worker 侧 RELOAD_DEPS 因每拍重执行已经生效**。当前无 running 资产作业、无 ASSET-WORKER 道占用；`ops/restart_autoflow.ps1` 用 `taskkill /T /F` 杀树，此刻不会误杀在途出图子进程。

### 给总调度的问题（需你定）
1. P1-2：sv-17 前是否 `git add` 这两个 worker 文件 + 两个未跟踪测试？其余 ~20 个未跟踪 tools/tests 是否一并收编？
2. P1-1 删 pyc 的一行修法让 W12 顺手做还是另开单？

### 结论
**W12 可进 sv-17：是（附 P1-2：先 git add，否则 worker 侧没进）。可否现在受控重启 autoflow_resident 让它生效：是（P0 = 0；此刻无 running 作业、无道占用，`ops/restart_autoflow.ps1` 即可；重启后关 ISS-1103-051601-5d74）。P1-1（同秒同 size 改动拿旧 pyc）不阻断，下一轮修。**

---

## 第 26 轮（A-G1b · Fable，Orca 工人 ctx_99cbd0e4ffff，总调度 MASTER-WSL 派）· 11-03 06:18 · W11 闸门修复复核（cut A 最后一道）

**结论：W11 六项核实、闸门没放水；cut A 可以发（前置：重跑干净的 dry 全绿）；tree 用不带 W12 未审改动的版本。**

## 第 23 轮（A-G1b · Fable，Orca 工人 task_3c963a75445a，总调度派）· 11-03 05:3x–06:0x · 复核 W11 RELEASE-PREP（cut A 发版前最后一道，只审不改）

**结论：W11 的 6 项声称全部核实、闸门没放水；cut A 代码面可以发。但 05:57 本人与总调度两个 `cut --dry` 撞进同一个快照目录（P0，本人造成的一半）：总调度正在跑的 a3b25713 dry 用的快照里 master_check.py / OVERSIGHT_LOG.md / CUT_PLAN 是我那棵树（2b2c35c9）的文件，结果作废；我的失败进程退出时把 cut_lock.json 写成 active=false、LOCKS.md 写回“未冻结”，而总调度的 pid 34492 还在跑。真 cut 前必须等 34492 退出、重跑一次 --dry。**

实跑：按 CUT_PLAN §4（含 hash-object blob 步骤）在临时 GIT_INDEX_FILE 重拼树 → T=10bc6655（05:52）；diff-tree 对 W11 9741c3be、总调度两棵树 2b2c35c9 / a3b25713；Windows python 跑 test_system_version -k truncated（1 passed 2.07 s，不是 skip）、test_decision_propagation + test_sop_gate_promote（12 passed）；decision_propagation 构造实验 4 组（脚本 C:\Users\fredw\AppData\Local\Temp\a_g1b\exp.py）；`cut --dry --tree 2b2c35c9` 05:57:18 起跑、05:57:38 在 build_snapshot 炸（见第 5 条）。

### 1. LOG_STREAMS 没放水，但豁免面比原来的 stale_allow 宽（P2）
- **谁说了什么**：W11：V2_LIVE.md / CHANNEL.md “不做 stale 扫描、propagate 照查”，撤 D-VQA-01 的 stale_allow。
- **实际是什么**：diff 只有一处生效点 `scan_files()`：`r not in LOG_STREAMS`（decision_propagation.py:59）→ 两个文件从**所有决定**的 stale 扫描里拿掉；propagate 对它们只剩 `check_decision` 第 148 行“文件里有没有 new_terms”这一项（propagate 本来就只查这一项，过期口径靠 scan 抓）。构造实验（D-VQA-01 真实 stale_terms）：C1 V2_LIVE 里写一行“总调度 决定：VQA 只记录、不拦截，标定过 0.85 并经总调度批准才转阻断”→ stale 0，**不报**；C2 同句 + 列进 propagate、无新口径 → unsynced“没有新口径”，报；C3 同句 + 新口径“转拦截”同在 → 不报；C4 同句放 docs/master/PLAN.md → stale 1，报。即“propagate 照查”只对“完全没写新口径”成立，旧口径文字本身在这两个文件里永远不报。D-VQA-01 绿的原因：真实 V2_LIVE.md 命中 10 行（:11/13/17/18… 全是 report_issue 自动插的“⚠ 卡点（ASSET-WORKER）…q9=fail、prompt_vlm=fail”），现在整个文件不扫 → stale 0。
- **是否放水**：今天不算——第 22 轮在真实工作树跑全量 propagation 退出码 0，说明除这 10 行外没有别的决定命中这两个文件，LOG_STREAMS 的实际效果 = 原 stale_allow。但 CHANNEL.md 现有 5 行 `| DECISION |`（MASTER-WSL 写的决定）、V2_LIVE.md 有 87 行非卡点行，以后在这两处写的旧口径决定永远不会被抓。
- **证据**：exp.py 输出 A=10 / B stale=0 / C1 0 / C2 报 / C3 0 / C4 报；`grep -c "| DECISION |" docs/master/CHANNEL.md` = 5。
- **建议（P2，不挡 cut）**：豁免收窄到 report_issue 的行前缀（“⚠ 卡点（”）而不是整个文件；或 DECISION 行照扫。测试 test_log_streams_skipped_for_stale_but_still_checked_in_propagate 已锁定现行语义，改时同改。

### 2. truncated_stdin 测试：skip 条件不宽，本机真跑过 ✅
- skip 只有两种：没有任何 bash；或 `os.name == "nt"` 且 bash 路径含 `\system32\` / `\windowsapps\`（WSL 入口）。Windows 上优先写死 `C:\Program Files\Git\bin\bash.exe`，Linux / 服务器走 `shutil.which("bash")` 照常真跑。本机 `.venv/Scripts/python.exe -m pytest tests/test_system_version.py -k truncated -rs` → **1 passed**（-rs 无 skip 行）。
- P2：Git 装在别处（便携版 / D 盘）的 Windows 机会退回 which("bash") → 可能拿到 System32 而 skip；要更稳就从 `git --exec-path` 推 bash 路径。

### 3. sop_gate “按 run”：V2 剧按 run 名；legacy 仍是 "series10" 字面量，两处（P2，不算 C-14 未修的 P0）
- sop_gate.py:92-108 `_episodes_rel`：run_ctx.py 在 → `run_ctx.episodes_out(run)`；不在（cut A 树、服务器）→ `Path("data/episodes") / ("series10" if is_legacy(run) else run)`。而 run_ctx.episodes_out（tools/series10_video/run_ctx.py:126-128，G4 未跟踪）本身就是同一句 `"series10" if is_legacy(run) else run`。所以“退回同一规则”属实，规则本身对 legacy 仍写死目录名，只是唯一口径挪到 run_ctx、sop_gate 保留一份复制；is_legacy 来自 runs.json `legacy_unprefixed_run`，V2 剧（series10_v2）已按 run 取 data/episodes/series10_v2。
- 定性：C-14 要的是旧内容不进网页 / 新剧不沾旧名；这里是 V1 自己的目录常量，不影响 V2。P2：runs.json 注册表加 legacy 目录字段，run_ctx 读它；cut B 后删 sop_gate 的复制（docstring 已写明）。

### 4. 决策表 blob：只多 D-CLN-05 一处 ✅
- 9741c3be / 2b2c35c9 / a3b25713 三棵树里 config/owner_decisions.yaml 都是 blob 4614109，对 HEAD 的 diff = D-CLN-05 title 改 + `run: series10_v1` 一行（2 插 1 删）。我按 §4 步骤从 HEAD 文本重做得到同一哈希 461410909788…。工作树决策表另有 +120 行（D-PRM-141、D-V2-127～140、D-IMG new_terms 改、D-VQA-01 注释）**均不在 cut A**。

### 5. 复现：树已变 + 两个 dry 撞车（P0）
- **tree 对比**：我 05:52 按 §4 重拼 = 10bc6655 ≠ 9741c3be。差 6 个文件：docs/CHANGELOG_AGENTS.md +3、docs/master/CHANNEL.md +7、docs/overnight/morning_20261103.md +7、docs/system_versions/CUT_PLAN_sv17.md +31、docs/uimaster/LOCKS.md ±8（锁状态文字）、**tools/master/master_check.py +15/−1**（W12 RESIDENT-RELOAD 新函数 sec_resident_assets，文件 mtime 05:51:59，未经审计）。
- 总调度期间自己拼了两棵：**2b2c35c9**（05:51:16 起 dry，pid 15316，05:56 前正常结束、锁释放）= 9741 + 上面 4 个 docs，**代码与 W11 树逐字节相同**；**a3b25713**（05:57:08 起 dry，pid 34492）= 2b2c + OVERSIGHT_LOG +42、CUT_PLAN ±1、master_check W12 +15。
- **撞车**：我 05:57:18 起 `cut --dry --tree 2b2c35c9`，和 34492 同用 D:\nsfs_cut_snapshots\sv-20261103-01：我的 build_snapshot 把对方刚建的空目录转成 .old1793653041，两边 tar 解包进同一目录，我的进程在硬链接 apps/web/e2e/uipixel/ovd.log 时 FileExistsError → copy2 PermissionError，EXIT=1（05:57:38）；退出时 cut_lock 写 `active=false / "cut 结束：失败"`、LOCKS.md 回“未冻结”，而 34492 仍在跑（05:59 在 arch_scan）。快照现状：master_check.py = 2ae639ef（2b2c 版，不是 a3b2 的 daa5df96）、OVERSIGHT_LOG.md = 66ee5668（不是 5c01ab26）、CUT_PLAN = 0e422a67（不是 26f025f7）。→ **总调度这次 a3b25713 的 dry 测的是混树，结果作废；我没拿到自己的闸门输出。**
- 根因（P1，system_version.py）：cut_lock 只是建议锁，`cut --tree` 不检查已有 active 锁（pid 活着）就起跑；快照目录名固定 sv-<id>，并发必撞。建议：active 且 pid 活 → 拒绝起跑；快照目录带 pid。
- 日志：/tmp/claude-1000/-mnt-d-NS-Final-Studio/0c635d56-1e88-48d9-9f28-7358aa6c9b9e/scratchpad/cut_dry_2b2c.log

### 6. 部署面：cut 不会 deploy，但非 dry 会推 GitHub ✅
- `cut()`（system_version.py:659-）不调 deploy；main 的 cut 分支只有 cut + record_cut。非 dry 走 commit-tree → update-ref（CAS）→ tag → `push_remote()`（:750 → :777，`git push origin <分支> --follow-tags`，推前 PUSH_SECRET_RE 扫描，命中不推写 alerts）。origin = github.com/fredwong749-hub/NS-Final-Studio。deploy 是独立子命令且默认自动 verify（第 22 轮 §6 已核）。“只入 git 不 deploy”成立，知道会推远端即可。

### 7. 其余声称抽核
- arch_scan 4 处：episode_metrics `_atomic_write`（:71-75，用于 :886/:890/:903/:904）、:141 的 parents[2] 已去；system_version `_write_verify` tmp+os.replace（:1243-1249）；test_sv_verify_lock.py:117 `timeout=60`。arch_scan.py 未改、data/sysarch/baseline.json（未跟踪）mtime 11-02 19:20 → 棘轮没被挪基线。
- master_check ④：SWITCH_EXPECT 新增 `("sop_gate.enabled", config/pipeline/sop_gate.json, eq True)`，当前值 true。
- tests/test_sop_gate_promote.py 新增，12 条（含 propagation）本机过。

**cut A 可以发：是，有一个前置条件。P0：等 pid 34492 退出后（或杀掉它）重跑一次 `cut --dry --tree <T>` 全绿再真 cut；本轮两个并发 dry 都不能作数。真 cut 用的 tree：`2b2c35c983327c917694ce09bb599ec91574931a`（= W11 已全绿的 9741c3be 代码 + 4 个 docs，不带 W12 未审的 master_check 改动）。若总调度决定带上 W12 那 15 行，则改用 `a3b257130830c87d9aa4c3806d67b08a604b53f4`，但要先有人审它。**

---

## 第 25 轮（A9 · Fable，Orca 工人 task_7f93286072b6，总调度派）· 11-03 06:0x · 独立审计 W9 ASSET-ITEMS（只审不改，代码零改动）

**结论：W9 六条声称基本成立，P0 无；P1×2（都是“下一步就会踩”的前瞻风险，不是 W9 改坏的）、P2×5。W9 可进 sv-17。项目方待选 4 条：别选 卓琳 nails1 s1100、卓琳 outfit1 s1102、江予白 acc1 s1102；卓琳 acc1 两张都行、建议 s1101。**

### 实跑证据（.venv/Scripts/python.exe -X utf8，仓库零改动）
| 项 | 结果 |
|---|---|
| `pytest tests/test_asset_*.py tests/test_asset_pipeline.py -q` | **154 passed**，5 warnings，70 s（W9 自报 89 是它挑的 5 个文件；本轮范围更大） |
| `episode_ready --run series10_v2 --episode 1` | **1 个缺口**：[look] 祁念 O4 没有设定图（sheet-lead_f-O4）；item 缺口 0 |
| 基线对比 | W9 改前副本在其 scratchpad/orig（04:51），**diff 里混着 W6b 的 proc 身份 / 年龄判词改动**（orig 早于 W6b），下面只审 item 相关 |
| 真编译 sheet-lead_f-O4（mode=sheet，W9 未动） | 无镜头语言 / 融合句 / 视线句（MERGE-IMG-O 起就没有；**“sheet 仍含融合段”这个前提本身不成立**，sheet 从来不含） |
| 真编译 face-ch_zhuo_lin（mode=shot，W9 未动） | 仍含“镜头：75mm…人物和场景是同一次拍摄…环境光染到皮肤…”+“四分之三侧脸 / 眼睛看着画面里的人” |
| 真编译 item-ch_zhuo_lin-A-acc1 / item-ch_jiang_yubai-A-acc1 | 169 / 179 字，人像句 **0 命中**，person_phrases 守卫不触发 |
| 真编译 scene-sk_white_cyc（内存里补 spec.suffix 后） | **含“镜头：35mm…人物和环境一起清楚。人物和场景是同一次拍摄：…环境光染到皮肤和衣服上…”**（见 A9-6） |
| 物件契约跑含人脸图（item-lead_f-O4-饰品 seed 候选 0bce9964，白底女模特） | prompt_vlm **fail**：第 1 条“有女性模特，可见人脸、手臂、腿”、第 2 条“主体是服装不止一件”、第 3 条不符；OCR 无 |
| 物件契约跑含领标图（item-ch_jiang_yubai-A-outfit1 候选 5dfbfe93，隐形人台皮夹克） | prompt_vlm **fail**（第 1 条“穿着服装的模特可见躯干手臂腿”）；但第 4 条“无品牌标志”**答了符合**——物件契约本身看不出领标，品牌靠 Q9 brand_logo 拦（真实作业 05:28–05:35 规则 4 下 8 张全被 brand_logo 挡，成立） |
| 亲看 8 张待选 PNG + 2 张 03:49 的 _crop.png | 8 张全是白底 / 浅灰底单物件、无人无人体；_crop.png 是从设定图裁的（带模特手 / 脸），**没进 owner_queue 的候选列表**（requests.json 只列 s11xx） |

### 逐条
A9-1 ｜ W9 说：item 的 Q9 去掉只对人像有效的项、换更严物件契约，brand_logo / underage 仍拦、阈值未动。｜ 实际：**成立**。去掉的 Q9 阻断项（仅 kind=item）：eye_contact、hair_mismatch、framing_mismatch、continuity_break、extra_person 共 5 项（asset_checks.py:147 ITEM_NA_DEFECTS）；新增物件契约 4 条（asset_jobs.py item_checks：①无人无人台无任何人体部位 ②只有这一样东西 ③颜色/材质对得上（有词才问；一套几件逐件对）④纯白/纯色底无标志字母文字）+ OCR 照旧 + 年龄 na（item 本来就 want_person=False）。config/vqa.json 未改：brand_logo / underage_look blocking=True，q9_asset 对 underage_look 强制保留。extra_person 从 Q9 挪到契约①“有一个人就不过”，更严。｜ 证据：上表两张图实跑；江予白 outfit1 规则 4 下 8/8 brand_logo。｜ OK ｜ 契约④对领标 / 吊牌看不出来，别指望它替代 Q9 brand_logo（P2-a，保持现状即可，别再把 brand_logo 挪进契约）。

A9-2 ｜ W9 说：item 编译跳过镜头语言 / L-110 融合段，带守卫。｜ 实际：**成立且不伤人像作业**。开关是 asset_worker.py:670 `mode="sheet" if kind in ("sheet","item")`：sheet 本来就是 sheet 模式、face / scene 仍是 shot 模式，W9 只改了 item 这一支。frame_job 的 sheet 模式只做减法（shot_language_note 返回空、不补 eyeline、plan_for turn=False），不会往 item 里加“正面站立”之类 sheet 句（真编译 169 字可证）。守卫 person_phrases（7 个固定短语）在 _compile 末尾对 item 抛 RuntimeError → 作业 failed，不出图。｜ 证据：四种 kind 真编译结果见上表。｜ OK ｜ 顺带记录（非 W9）：face 作业是证件式胸像却仍走 shot 模式，带“四分之三侧脸 / 眼睛看着画面里的人 / 融合句”，与 face 口径冲突（P2-b，face 作业已 done，不急）。

A9-3 ｜ W9 说：祁念 O4 饰品 / 鞋 / 服装是伪作业（饰品=无、项目方编号），已关闭不渲染。｜ 实际：**“无 / 编号”属实，但关闭不是 W9 的 no_item 关的，记录的理由也不是这个**。P1 原文在 data/pipeline/runs/series10_v2/P1_looks.json O4.zh=“服装=日常全身装：…（全身参考照）｜鞋=SH1 或 SH2｜饰品=无”（script_v2.json 里祁念 O4 写的是“饰品: 0件”，另一套措辞）。三条作业 04:52:29 由 close_stale 收尾：state=done、final=True、result.closed_reason=“缺口已不在（episode_ready 本拍没有这一项）”、log 一行，文件和 6 张候选都在——**可追溯**，但“缺口不在”是因为 W7 把“没设定图的造型”从 item 缺口改成 look 缺口，不是因为“饰品=无”。W9 报告里“饰品=无 不可能出图”是事后解释，与落盘理由不一致。｜ 严重度 P2-c（追溯性够，叙述不准）｜ 建议：W9 报告 / 交接里改口为“W7 口径下缺口消失、close_stale 收尾；no_item 只保证以后不再生成”。
　　**P1-①（前瞻，马上会踩）**：ep1 唯一缺口是 sheet-lead_f-O4；它一登记，plan_items_from_sheet 会按同一段 zh 规划 item：实跑 parse_parts + no_item → 鞋“SH1 或 SH2”跳过 ✅、饰品“无”跳过 ✅、**服装“日常全身装：…（全身参考照）” no_item=None → 会新建 item-lead_f-O4-outfit1**（iid O4_outfit1 不在清单 have={O4_garment, SH1} 里、作业文件也不存在）→ 先从设定图裁、裁不出就出“平铺俯拍”候选——这件衣服是项目方上传的 O4_garment（C-23），不该重画，而且会和清单里已有的 O4_garment 并存两份。另 no_item("0件")=None：若 P1_looks 以后按 script_v2 措辞重生成，“0件”会被当物件出图。｜ 建议（给 W9/CODER）：no_item 加 `^0\s*件$`；plan_items_from_sheet 对 label 含“全身参考照 / 参考照”或该 slot 在清单里已有项目方来源（source 含“项目方上传”）的项跳过并 log 原因；在 O4 sheet 登记前上这条，否则下一拍就会派一个不该出的作业。

A9-4 ｜ W9 说：4 条已 awaiting_pick、候选白底单物件；江予白 s1102 是相机包不该选。｜ 实际（亲看）：**8 张全部白底 / 浅灰底、无人无人体，契约与 P1 文字一致；但按 C-04 对照设定图有 3 张不该选**：
　　· 卓琳 acc1 s1100：金色细链**肩包**（长链、长方体、浅灰底）；s1101：金色口金链条手包、纯白底。两张都对得上 P1“金色细链手包”，**建议 s1101**（更像手包，底更白）。
　　· 卓琳 nails1 s1100：8 片方圆（coffin）中长鲜红甲片；s1101：9 片尖长（stiletto）鲜红甲片。设定图 s1102 里是尖长甲 → **别选 s1100**（形状偏短方、片数也不足 10），选 s1101。Q9 对两张都报 extra_limbs / accessory_mismatch 只记录（对甲片乱答，W9 预料之中）。
　　· 卓琳 outfit1 s1101：酒红单扣西装 + 同色西裤 + 黑缎吊带衫平铺，与设定图单扣西装一致；s1102：**双扣西装**、吊带衫摆在旁边 → **别选 s1102**，选 s1101。
　　· 江予白 acc1 s1101：黑色皮质宽带绕成环（当“相机皮带缠两圈”可用）；s1102：**黑色相机小包 + 长背带**，看图第 2 条答“仅此一件黑色相机包”放过了 → **别选 s1102**（与 W9 一致）。注意这两张是 item_rule=3 时出的（提示词与规则 4 单件写法相同、Q9 还多拦 extra_person），awaiting_pick 不会被 refresh_items 重写，无需返工。
　　附：nails1 作业里还残留一条 key=crop、passed=True 的候选和 result 指向 assets_v2/…/A_nails1_crop.png（03:49 从旧设定图裁的手部图，文件还在、清单里已没有）；没进 pick 列表，但作业状态自相矛盾（awaiting_pick 却带 result）。｜ P2-d ｜ refresh / 换设定图时把旧 crop 候选和 result 清掉。

A9-5 ｜ 实跑 ｜ pytest 154 passed；episode_ready ep1 只剩 sheet-lead_f-O4 一个缺口，5 条 awaiting_pick 的 item 不算缺口（I4 口径只在镜头真的要这件时报）。｜ OK ｜ 无。

A9-6 ｜ 下一集风险 ｜ **P1-②：scene 作业确实带融合段**：scene 走 mode=shot，真编译（内存补 suffix）出来“镜头：35mm 镜头…人物和环境一起清楚。人物和场景是同一次拍摄：…环境光染到皮肤和衣服上；手和身体与桌面…”——空镜提示词里整段人像融合句，ep2 新场景（P3/P4 生成的 scene 作业）出图时会往空镜里长人；现有 scene-sk_white_cyc 已 done 且是旧格式（无 spec.suffix，重编译 preflight 直接拒），不受影响。｜ 建议：scene 也用“不加镜头语言段”的模式（mode=sheet 或新开 mode=empty）+ person_phrases 守卫扩到 scene；empty_suffix 已把风格后缀换掉、负面词已含人物，缺的只是这一段。
　　**P1 缺材质 / 颜色时**：item_traits 取不到词 → 提示词不写“颜色：/材质：”、契约第 3 条整条不问（例：“相机皮带”只问材质皮；无词则 2 条 + 白底条）——**不乱填、也不失败关闭，只是少一道核对**，可接受。边角（P2-e）：COLOR_RE 把“裸粉”拆成“裸”“粉”，nails 主语只取第一个色 → 祁念 O4 甲“短款裸粉美甲”会编成“一套**裸**穿戴甲片…颜色：裸、粉”，措辞别扭且可能撞 compiler 的“裸”语境判断；建议颜色表加“裸粉 / 裸色”整词、nails 主语用全部颜色词。

### 给总调度的一句话
W9 **可进 sv-17（是，P0 无）**。进版前或 O4 设定图登记前要补两件 P1：① plan_items_from_sheet 别为“（全身参考照）/ 项目方已上传”的服装重画（否则 sheet-lead_f-O4 一登记就派 item-lead_f-O4-outfit1）；② scene 作业去掉镜头语言 / 融合段。给项目方：**这 4 条待选里别选 卓琳 nails1 s1100、卓琳 outfit1 s1102、江予白 acc1 s1102**；卓琳 acc1 两张都能用，建议 s1101。


## 第 24 轮（A1b · Fable，Orca 工人 ctx_c919a551a619，总调度 MASTER-WSL 派）· 11-03 05:25 · W8 PRODUCER-P1 复核

**结论：A1-1/2/3/5/6 全部成立，P0 无，P2×6；W1+W8 可进 sv-17；V2 producer 可受控重启（上线前须先停旧代码 pid 13972，按 L-152 条件）。**

## 第 22 轮（A1b · Fable，Orca 工人 task_7e14dec1ef29，总调度 MASTER-WSL 派）· 11-03 05:2x · 复核 W8 PRODUCER-P1（A1 的 5 条修复）

**结论：W8 五条修复全部成立，P0 无；P2×6。W1 + W8 可进 sv-17；V2 producer 可受控重启上线（P0 列表：空；上线前两条运维动作见文末）。**

# A1b 独立审计（Fable，只读）· 2026-11-03 05:17–05:22 · 临时目录 + Windows venv python 实跑，仓库零改动

### 实跑证据
| 项 | 结果 |
|---|---|
| `pytest tests/test_producer_run_identity.py tests/test_sop_gate.py tests/test_asset_worker_sop_backoff.py -q`（.venv/Scripts/python.exe，PYTHONUTF8=1） | **35 passed**（86 s，real-data-guard 写真实数据 0 次） |
| `pytest tests/test_prodmerge_o.py -q` | **23 passed** |
| `import producer`（NS_PRIMARY_RUN=series10_v2）/ `import asset_worker` | OK / OK |
| drift_test CASE A（runs.json 截断、无 run.json） | drift=**None**，primary_now=None ✅ |
| CASE B（截断 + run.json 旧指针 series10_v1） | drift=**None** ✅（不再回退 DEFAULT_PRIMARY） |
| CASE C（runs.json 正常、心跳坏） | drift=**None** ✅ |
| CASE D（V1 进程、primary=series10_v2） | handoff drained=True，**successor=series10_v2** ✅ |
| **CASE E**（serve；第 1 拍后 primary 切 series10_v3 且保持） | 第 2 拍 run_switch_suspect seen=1 → 第 3 拍 run_switch → exit，**successor=series10_v3**，ticks=[True, False] ✅ |
| **CASE F**（第 1 拍切 v3、第 2 拍切回 v2） | run_switch_suspect → **run_switch_cleared**，无 successor，继续派单 ticks=[T,F,T,T,T,T] ✅ |
| CASE G（runs.json 连续 2 拍截断，第 3 拍恢复） | 全程无 suspect、不交接（未知=不动）✅ |
| CASE H（切 v3 → 截断 → 再 v3） | 截断那拍把 suspect 清零，之后重新数 2 拍才交接（保守，可接受） |
| CASE I（本剧 archived 触发 handoff，排空期间改回 producing） | **aborted=True**，心跳 state=draining（随后正常 tick 整体重写心跳，state 字段消失）✅ |
| O_EXCL Windows 实测（os.open O_CREAT\|O_EXCL） | 第二次 → **FileExistsError**；对方句柄打开着时仍 FileExistsError；unlink 对方打开着的文件 → PermissionError WinError 32 |
| acquire_pidfile 并发：6 个进程同一刻启动（赢家像真 producer 一样活着、不写心跳=只靠 120 s 宽限） | **1 个赢家**，5 个 loser 都看到赢家记录 ✅ |
| 陈旧 pid 文件（pid 已死、mtime 1000 s 前）+ 6 个同时启动者 | **1 个赢家** ✅ |
| 旧格式 pid 文件 `{pid, started}`（= 现在 13972 那种）+ 活进程 + 新鲜心跳无 run 字段 | 新启动者 **0 赢家**（正确拒启）✅ |
| 活持有者但心跳 700 s 没更新 | 新启动者 **1 赢家** = 双持有（W8 设计如此，见 P2-4） |
| require_backoff enforce：t0 挡+写 1 条，t+20 挡（退避中、不写）；**t+40 缺口消失**（gate→ok） | **立即放行** allow=True ok=True（judge 先于退避）✅；t+60 缺口再现 → 挡、不再写违规（沿用窗口）✅ |
| observe→enforce 切换（t+40 改 sop_gate.json） | **立即生效**：allow=False mode=enforce，新签名写 1 条；切回 observe 立即放行、不写 ✅ |
| enabled=false | 立即放行 ✅ |
| next_action 文案 / 计数 / fails 数变化 | 签名不变，**不重写违规** ✅（A1-6 修复成立） |
| 退避状态文件损坏 `{broken` | 当空处理：重写 1 条、enforce 照挡（失败关闭）✅ |
| 真实仓库 judge（只读）series10_v2 ep1 | 出图：**不过**（资产就绪缺口 1、提示词 0/1：造型没有设定图）但在 observe_stages；尾帧：不过·enforce；资产就绪：过 |
| violations.jsonl | 166 条，**04:30 之后 0 条**（asset_worker 侧已安静）；`_sop_backoff.json` 04:56 已是 `{}` |

### 逐条
A1b-1 ｜ W8 说：primary_now 读不准=None、不回退 DEFAULT_PRIMARY；DRIFT_CONFIRM_TICKS=2；handoff 末尾复核。｜ 实际：**成立**。CASE A/B/C/G 均 None 不动；E 两拍一致才交接且接班剧正确；F 单拍抖动清零；I 复核恢复即 aborted 继续跑。runs.py:33 `_js` 对 PermissionError 退避 8 次。｜ 证据：上表；producer.py:3248-3269、:3413、:3316-3336。｜ OK ｜ 无。

A1b-2 ｜ W8 说：drain 超时继续等 ≤ LEASE_S、心跳 draining、只有真排空才写 exited。｜ 实际：成立（test_drain_overrun_heartbeat_is_draining_not_exited 过；:3296-3301、:3352-3355）。遗留：返回后 serve return 0 → 解释器 join 在途线程，心跳停在 draining 不再更新；pid 文件已放，同剧可再起一个 producer 与残余线程并存（与 A1-3 原备注一致，producer 单道租约仍防重派）。｜ P2（沿用 A1-2 口径）｜ 无需本轮改。

A1b-3 ｜ W8 说：acquire_pidfile O_EXCL + _pid_holder_alive（pid 活 + 心跳 pid/started 一致 + 心跳 ≤600 s 或 120 s 宽限）。｜ 实际：**成立**。6 进程同秒启动（新建 / 陈旧两种）都只 1 个赢家；O_EXCL 在 NTFS 上就是 CREATE_NEW 原子语义，对方句柄打开着也报 FileExistsError；旧格式 pid 文件 + 活进程正确拒启。两处边角：① 活持有者一拍卡 >600 s（心跳没写）→ 第二个启动者判陈旧、删文件、双持有（设计取舍：换 PID 复用防护）；② 陈旧清理 `pidf.unlink()` 撞上别的进程正读 pid 文件 → WinError 32 → 走 `except OSError: return (False, old)` → 对一个已死持有者报“已在运行”退出码 0，运维要再起一次。｜ P2 ｜ ① 心跳陈旧且 pid 活时记一条 `pidfile_suspect` 日志而不是静默接管；② unlink PermissionError 退避重试一轮。

A1b-4 ｜ W8 说：require_backoff 单一实现，producer:2381 / asset_worker:440 都调它。｜ 实际：**成立**。grep 全树只剩这两个调用点 + sop_gate.filter_jobs（无人调用，仍走裸 require；留着是个陷阱）。enforce 窗口内缺口消失立即放行（judge 在退避前，退避只约束“写违规”不约束“放行”）；observe↔enforce、enabled 切换立即生效（cfg 进签名）。每拍每候选在退避分支都 `_write_state` 一次（11 镜×2 = 22 次原子写/拍），I/O 可接受但比写 violations 时没少。｜ OK ｜ filter_jobs 删掉或改调 require_backoff（P2）。

A1b-5 ｜ W8 说：签名 = 阶段名 + 状态码 + gate 配置。｜ 实际：成立（Q2d：next_action 文案、第 N 次、fails 数、缺口数变化都不重写）。`_CODE_RE` 会把 next_action 里的 `--ep=1` 之类也当状态码（现有文案里没有，备忘）。旧 `_sop_backoff.json` 格式：键 epNN 的旧条目 sig 对不上 → same=False → 多写 1 条后进入新窗口，**每集一次性 1 行，可接受**；且现在文件已是 `{}`（04:56 gate ok 时被清），实际 0 行。｜ OK ｜ 无。

A1b-6 ｜ 问：master_check ⑥ 不认 state=draining。｜ 实际：⑥（master_check.py:200-205）只看 exited / fresh / paused，排空期心跳 paused=True → 显示「在跑·暂停 在途 N」且无 ⚠；resident_sync:714 producer_paused=True。总调度会误以为有人经 control.json 暂停了它（K-OPS-E08 口径），但 E08 超时告警读的是 control.json 不是心跳，**不会触发误告警，也没有任何自动动作读心跳 paused**。另 ⑥ 取 primary 仍 run.json 先于 runs.json（A1-10 未修）。｜ P2 ｜ ⑥ 加一行：hb.state=="draining" → 「交接排空中（exit_reason）在途 N」；primary 改 runs.json 优先。

A1b-7 ｜ 新发现：handoff 末尾 `new = primary_now()`（3 次 ×0.2 s）若恰好读不准 → successor=None → 本进程仍退出 → 新剧无人出图（与原事故同后果，窗口极小：前面已连续 2 拍 + 复核都读到了）。｜ 证据：producer.py:3338-3345。｜ P2 ｜ new is None 时按“未知”处理：再等一拍重读，仍 None 则 aborted 继续跑，不要无接班退出。

A1b-8 ｜ 新发现：primary_now 在 runs.json **不存在**时采信 run.json（CASE B2：run.json=series10_v1 → drift=“已切到 series10_v1”）。真实部署 Paths 启动即要求 runs.json 有 legacy_unprefixed_run（否则 RunRegistryMissing），所以这个分支只在 runs.json 被整文件删除/改名时才走到；现 run.json=series10_v2 与 primary 一致，无害。｜ P2 ｜ primary_now 去掉 run.json 分支（不存在 = None）。

A1b-9 ｜ W8 说：5 文件 110 passed。｜ 实际：简报列的 3 文件 = **35 passed**；test_prodmerge_o 23；W8 标记只出现在 2 个测试文件里，110 对应哪 5 个文件没写明（同 A1-12 的毛病）。｜ 事实 ｜ 交付单写清文件集合。

### 上线前提（运维动作，不是代码问题）
1. 笔记本 pid 13972（11-02 01:45 起、旧代码、为已归档 V1 跑、心跳无 run 字段、pid 文件旧格式）**新代码无法让它自己交接**——必须手工停掉再起新 serve；新代码对这个旧格式 pid 文件会正确拒启同剧，不会误删。
2. runs.json 里 series10_v2 现为 **preparing**：新 serve 起来后只报 promote_ready 不派单（A1-4），所以重启本身零风险；真正开始出图要总调度 `sop_gate.py promote --apply`。提升前注意：出图在 observe_stages 里，而 ep1 judge 实测资产缺口 1 + 提示词 0/1（造型没有设定图）→ 提升即派单（配置口径，A1-4 已备注）。

**最后一行：W1 + W8 可进 sv-17 = 是（P0：空）；V2 producer 可受控重启上线 = 是（P0：空；先停 13972、promote 前清 observe 或接受 observe 放行）。**

---

## 第 23 轮（A6b · Fable，Orca 工人 task_54e847a1ae37，总调度派）· 11-03 05:22 · W6b ASSET-SAFETY 复核（成年判词器失败关闭 + 杀进程核身份）

**结论：W6 + W6b 可进 sv-17（是；无 P0）。A6 第 20 轮两条 P1 均已修实：A6 反例集 25 条全部按预期；伪造 proc 指向无关活进程走真 tick（不打桩 _kill）5 种情形均不杀、状态/登记正确；103 passed / 220 passed 复现。剩 4 条 P2（判词器残留 4 句、bundle 年龄只判“年龄：”一行、旧作业被定案后子进程会覆盖状态、unverified 路径仍先 salvage），建议 W6c 顺手补，不阻塞发版。**

# A6b · W6b 独立审计（Fable，2026-11-03 05:14–05:22；只审不改）

范围：tools/pipeline/asset_checks.py:43-93、asset_worker.py:278-310/456-482/913-988、tests/test_asset_age_judge.py、tests/test_asset_pipeline.py:1185-1250、W6b_report.md、data/pipeline/asset_jobs/series10_v2 现状。实跑环境：`.venv/Scripts/python.exe`（Win 3.12），临时 root 在 %TEMP%/pytest-of-fredw，仓库零改动（本条日志除外）。

## 1. 判词器：A6 第 20 轮反例集（25 条）→ 新判词器
| 句子 | A6 期望 | 新 | 一致 |
|---|---|---|---|
| 画面里的人看起来是“成年”，因… | pass | pass | ✅ |
| 年龄：成年 | pass | pass | ✅ |
| 她是成年人；旁边的孩子未成年 | fail | fail | ✅ |
| 这个人是成年人，但另一位像未成年 | fail | fail | ✅ |
| 不像成年人，更像未成年 | fail | fail | ✅ |
| 不是成年人 | fail | fail | ✅ |
| 非成年 | fail | fail | ✅ |
| 大概率成年，但也可能是未成年 | fail | fail | ✅ |
| 像未成年 / 看起来像未成年但穿着成熟 / 未成年 / 未成年，另一位成年 / 没有人 / adult / minor / 不确定 / 约15岁 / 15岁左右的少女 | fail | fail ×10 | ✅ |
| 无人物 | na | na | ✅ |
| （空） | untested | untested | ✅ |
| 成年？不确定 / 成年女性，约 17 岁 / 成年，但旁边那位看起来未成年（A6“新旧都放过”） | fail | fail ×3 | ✅ |
| s1101 原话“成年，…无未成年视觉元素。” / s1102 原话 | pass | pass | ✅ |

25/25 一致；W6b 表里的“旧”列由测试内复原的 W6 写法实跑核对（test_age_judge_counterexamples 同时断言旧/新），不是手填。

### A6b 新造 28 条刁钻句（期望按失败关闭）
pass 且合理：成年，18岁 / 成年，十八岁左右 / 成年，二十出头 / 成年，无未成年视觉元素，无儿童 / 成年，没有任何未成年迹象，年龄约20岁 / 成年，1.8 米高 / 成年，1998年生 / 成年，不算年轻 / 成年女性，没有稚气（“没有稚气”是安全否定被抹掉，理由成立）。
fail 且合理：成年（约 16 岁）/ 未成年？不，是成年（未成年线索不在否定里）/ 看不出年龄（无判词）/ 成年感但稚气 / 成年 adult woman, looks like a teenager / 成年，但不排除未成年的可能 / 成年 — 不过也许是 minor / 成年，无未成年视觉元素；但另一位是儿童（抹掉安全否定后“儿童”仍在）/ 成年。理由：面部成熟。⏎（画面右侧还有一个小孩）/ 成年，Young girl 风格 / 成年，幼态脸 / 成年，是个学生样子的女性 / 成年女性，稚气未脱 / 成年，无人物遮挡（“无人物”+“成年”矛盾 → fail，过严可接受）。
**pass 但不该 pass（4 句，P2）**：
| 句子 | 新 | 为什么漏 |
|---|---|---|
| 不能确定是否成年 | pass | AGE_UNSURE_RE 只有“不确定/无法确定/难以确定”，没有“不能确定/是否”；AGE_NEG_ADULT_RE 限否定词后 ≤3 字 |
| 成年，但未必 | pass | “未必”只在 AGE_NEG_ADULT_RE 里且要求后面跟“成年” |
| 成年，八岁 / 成年，七八岁左右 | pass | AGE_NUM_RE 只认阿拉伯数字和“十X岁”，个位中文数字（一~九岁）没覆盖 |
“两人都是成年人”→ pass：判词器只管年龄，人头数由 anomaly.check expected=1 兜（A6 §1 已核），合理。
原始 W5 写法（startswith 成年）对“不能确定是否成年”是 fail，本版 pass，属同类残留但出现概率低（提示词要求首行三选一），且生产路径有 bundle 第 2 条 + 人头数两道闸 → **P2**。修法一行：UNSURE 加 `不能确定|无法|不好判断|是否|未必`，NUM 加 `[一二三四五六七八九两]岁`，反例进 CASES。

### age_check 整句 vs 生产路径（P2）
- age_check(asset_checks.py:43-48) 确实整段过 _age_status（W6b 说法属实）。但 **生产路径** render_one(asset_worker.py:790-795) 的 age 来自 bundle_check → parse_bundle，只取以“年龄”开头的那一行；理由若被模型换行写（“年龄：成年⏎理由：约 16 岁，穿校服”）就被丢掉 → 实跑验证 parse_bundle 给 pass，而整段判给 fail。提示词要求“三行”且两张真实回答都是单行（s1101/s1102），所以是低概率口子，定 P2：parse_bundle 把紧随“年龄”行之后、不是编号/文字/总结的行拼进 age 文本即可。
- 旁注：age_check 的 `"untested" if r.get("error") and st != "pass" else st` → 看图调用报错但 text 含“成年”会 pass；client.generate 报错时不带 text（vqa/client.py:142-148），现实触发不了，记录。

## 2. verify_proc 实跑（临时 root，真 tick，真 _kill 不打桩，受害进程 = 本机起的无关 python sleep）
| 情形 | 作业 proc 记录 | 结果 | 进程 |
|---|---|---|---|
| A 最刁钻：pid + 创建时间都对上无关活进程，只有命令行指纹不同 | {pid=真, sig=真, cmd_sha1=run-job 的} | failed, final=True, pid=None, error=“pid_mismatch：子进程超时…身份核不上（命令行指纹对不上），未杀”；心跳 timeouts=[{killed:false, why:pid_mismatch}]；issues.jsonl 登记“连续失败…pid_mismatch” | **活着** ✅ |
| B pid 复用（创建时间对不上） | {pid=真, sig=真+12345} | 判死不进超时路径：pending（attempts<2 重排），error=“pid_mismatch：pid 还在但创建时间对不上…未杀”，timeouts 无 | 活着 ✅（原进程确已不在，重排合理） |
| C 旧作业无 proc、pid 指向活进程、超时（= 任务单第 4 点场景；用真 _pid_alive） | 无 | failed, final=True, error=“pid_mismatch…作业没记子进程身份…未杀”，timeouts killed:false，登记卡点 | 活着 ✅ |
| D dry=True | 同 A | state 仍 running，timeouts 无，不杀 | 活着 ✅ |
| E 对照：身份三项全对（proc_identity 取自该进程） | 真身份 | timeouts killed:true why=timeout，pending，error 含“核过身份” | **被杀** ✅（taskkill 真生效，list2cmdline 指纹 = CIM CommandLine 属实） |
脚本：\\wsl.localhost\Ubuntu-24.04\tmp\claude-1000\-mnt-d-NS-Final-Studio\e4b942b5-87ee-48ae-bd11-906e3391b51e\scratchpad\test_a6b_verify_proc.py（5 passed）。注意 tests 里 _sheet_job_with_cands 会把 _pid_alive 打桩成 False，W6b 的 legacy 用例自己再打成 True——它测的是逻辑不是真 tasklist；本轮 C 用真 _pid_alive 补上。
- 生产确认：_PROCS 每拍随 resident 重载为空（autoflow_resident.py:146 _load），生产永远走 sig 路径；05:16 心跳新起的两个作业（outfit1 pid 50624 / zhuo_lin-A-acc1 pid 23400）作业文件已带 proc{pid,sig,cmd_sha1} → resident 已在跑新代码，**不需重启**。proc_sig 复用 agent_dispatcher（test_proc_sig_reuses_agent_dispatcher 锁定）。

## 3. 测试实跑
- `pytest tests/test_asset_age_judge.py tests/test_asset_pipeline.py -q` → **103 passed**（26 s）；CASES 实数 37 条（与声称一致）。
- `tests/test_asset*.py tests/test_*asset*.py tests/test_agent_dispatcher*.py` → **220 passed**（110 s）。
- 五个文件均为未入库新文件（??），未 commit（W6b 自述一致）。

## 4. W6b 遗留：两个旧代码起的在跑作业（pid 25904 / 6228）
- **已自然消解，无需处理**：item-ch_jiang_yubai-A-acc1 05:04:09 子进程自己收尾 → awaiting_pick（2 候选投待办）；item-ch_jiang_yubai-A-outfit1 05:05:56 子进程自己标 failed（4 张候选 Q9 全报 brand_logo），05:16:07 按新代码重起（pid 50624，带 proc）。当前 running 作业全部带 proc，**没有任何无身份的在跑作业**，90 分钟 pid_mismatch 定案的场景不会发生。
- 若将来再出现无身份/核不上但其实还在跑的作业（P2，记录）：tick 会 failed(final)+登记，并把道的 hold 放掉；子进程跑完时 run_job 的 finally(asset_worker.py:1037-1046) 无条件 save_job 自己的状态 → 会覆盖 failed(final)（final 字段丢失），卡点却留着不关；期间该道可能被下一个作业双占。影响有界（最多一条道短时双占 + 一条陈旧卡点），建议 W6c：① _fail(final) 时不放道、改记 `lane_suspect`，由 refresh/人工清；② run_job finally 先 load_job，若盘上已是 failed+final 就只写 log 不覆盖 state。
- unverified 路径在 _fail(final) 前仍先 try_salvage(asset_worker.py:306)：可能还在跑的作业被 salvage 成 awaiting_pick 后子进程再覆盖；同上一并处理（P2）。

## 汇总
| # | 项 | 级别 | 一句话 |
|---|---|---|---|
| 1 | _age_status 残留 4 句（不能确定是否成年 / 成年，但未必 / 八岁 / 七八岁） | P2 | 两处正则各加几个词 + 进 CASES |
| 2 | 生产 bundle 路径只判“年龄：”一行，换行写的理由被丢 | P2 | parse_bundle 拼续行 |
| 3 | 核不上定案 failed(final) 后子进程收尾会覆盖状态 / 道被提前放掉 / 先 salvage | P2 | finally 先读盘状态；final 时不放道 |
| 4 | 旧作业 pid 25904 / 6228 | 无 | 已自然收尾，当前所有 running 作业带 proc |

**W6 + W6b 能否进 sv-17：是（无 P0；A6 两条 P1 已修并经真进程 / 真 tick 复核；4 条 P2 不阻塞，建议派 W6c 一并补）。**

---

## 第 22 轮（A-G1 · Fable，Orca 工人 ctx_61b92ebf5fb8，总调度派）· 11-03 05:1x · cut A = G1 harness（47 文件）发版前复审

**结论：cut A 现在不能发（否）。P0 ×3：① 真跑 `cut --dry --tree` 四道闸门红（arch_scan 4 处退化 / decision_check ❌1 / decision_propagation ❌10 / pytest 1 红），T4 只报了 syntax_guard + 定向测试；② G1 对 G6 runs.py 新函数有硬依赖，G1 树上 sop_gate probe-prompts / promote --apply / defect_hunt 入口都 AttributeError；③ 决策表（G7）与 G1 耦合：用 HEAD 决策表 D-CLN-05 / D-VQA-01 红，换工作树决策表又要 G2 lint.py、G3 asset_worker.json。**

实跑：拼树 6a1db637（HEAD 1d2cc20 + 47 文件，+6582/−33）→ `tools/qa/system_version.py cut --dry --tree 6a1db637`（快照 D:\nsfs_cut_snapshots\sv-20261103-01，2784 文件 + 63577 硬链接，05:00 退出码 1）；快照上重跑 arch_scan / decision_check / decision_propagation / master_check / sop_gate / defect_hunt；真实工作树对照跑 decision_check（87：✅86 ❌0 ⏳1）和 propagation（退出码 0）。

### 1. T4 的闸门结论（P0）
- **谁说了什么**：CUT_PLAN §0.1：“冻结树（HEAD + G1）已核：syntax_guard PASS（894）；定向测试 85 过 2 红，2 红都和分批无关”。
- **实际是什么**：真 `cut --dry --tree` 7 道闸门 3 过 4 红：syntax ✅895、kb ✅、VQA 回归 ✅；**arch_scan ❌**（4 处退化：no_timeout tests/test_sv_verify_lock.py:117 0→1；nonatomic_json tools/master/episode_metrics.py:867/:885 0→2；hard_import_path episode_metrics.py:141 0→1；nonatomic_json tools/qa/system_version.py:1251（verify 写 verify_*.json）2→3）；**decision_check ❌1**（D-CLN-05 /api/assets/scenes 多出 sk_white_cyc：HEAD 版检查没钉 run，进程内 app 走 primary=series10_v2；工作树决策表已改成 `run: series10_v1`，真实工作树 ✅）；**decision_propagation 退出码 1**（D-VQA-01 ❌10 处，全是 docs/master/V2_LIVE.md 里 report_issue 自动插入的 ASSET-WORKER 卡点行“q9=fail、prompt_vlm=fail”命中 stale_terms；工作树决策表已把 V2_LIVE.md 加进 stale_allow，所以真实工作树 ✅）；**pytest ❌**（11 文件 99 过 1 红，不是 85/2）。T4 没跑 cut --dry，arch_scan / decision 两道完全没核。
- **证据**：`本轮 scratchpad/cut_dry.log`（本轮临时目录）"reason": "闸门不过：arch_scan --check…；decision_check…合计 69：✅ 66 ❌ 1 ⏳ 2；decision_propagation…；定向 pytest…1 failed, 99 passed"；快照 `arch_scan.py --check` → "ARCH_SCAN FAIL（4 处退化）"；快照 `decision_check.py` 第 15 行 "❌ D-CLN-05 … 多出 ['sk_white_cyc']"；快照 `decision_propagation.py --dry` → "D-VQA-01 ❌ 10 处没同步" 表 10 行均为 `docs/master/V2_LIVE.md`；`git diff HEAD -- config/owner_decisions.yaml` +stale_allow … docs/master/V2_LIVE.md；config/owner_decisions.yaml:124 `run: series10_v1`。
- **建议**：(a) arch_scan 4 处由 HARNESS-O / 总调度改成原子写（tmp+os.replace）、补 timeout、去掉 parents[2] 硬路径——棘轮不能靠改基线过；(b) 决策表见第 3 条。

### 2. G1 → G6 runs.py 硬依赖（P0）
- **谁说了什么**：CUT_PLAN §4 把 tools/autopilot/runs.py 放 G6，§2 的跨组表没列 G1 对它的依赖；T4 说“cut A 在服务器上能跑”。
- **实际是什么**：HEAD 版 runs.py 没有 RUN_ENV_KEYS / run_env / set_status / gate_legacy_tool（工作树 +127 行、纯新增）。G1 树上实跑：`sop_gate.py probe-prompts --run series10_v2 --episode 1` → `AttributeError: module 'runs_for_sop_gate' has no attribute 'RUN_ENV_KEYS'`（sop_gate.py:462）；`sop_gate.py promote --apply` 会在 sop_gate.py:544 `_runs().set_status` 同样炸（只读 promote 正常：promote=false，ep01 卡资产就绪缺口 1 / 提示词 6/11）；`tools/qa/defect_hunt.py --help` → `AttributeError: module 'runs' has no attribute 'gate_legacy_tool'`（defect_hunt.py:987，test_defect_hunt 不调 main 所以测试绿）。status / check / judge / master_check 不受影响。
- **证据**：快照 python -c hasattr 表：import_path True，renders_dir True，RUN_ENV_KEYS False，run_env False，set_status False，gate_legacy_tool False；上面两条报错原文。
- **建议**：把 tools/autopilot/runs.py 补入 cut A（diff 纯新增、不改旧函数；pick_tests 会带上 test_*runs*），或在 CUT_PLAN 明写 cut A 的 probe-prompts / promote --apply / defect_hunt 不可用。

### 3. 决策表 G7 与 G1 耦合（P0）
- **谁说了什么**：CUT_PLAN §4：“cut A 跑的是 HEAD 版决定表。cut A --dry 时如果 decision_check 报 ❌，就把这个文件提前到 cut A”。
- **实际是什么**：HEAD 决策表 → 第 1 条的 D-CLN-05 ❌ + D-VQA-01 ❌10。把工作树 owner_decisions.yaml 加进 G1 拼第二棵树 54c70169 实跑 propagation：D-VQA-01 ✅（剩下 D-VID-01 / D-IMG-87a 红只是我的纯导出没有 data/，真快照硬链接 data/ 后会过）。但工作树决策表新增的检查又要别的组：D-PRM-141 要 services/recipes/ns_recipes/lint.py 含 RL-T9（HEAD 0 处，文件在 G2）、D-V2-140 要 config/pipeline/asset_worker.json（HEAD 没有，G3）——这两条 decision_check 在 G1+G7 树上会 ❌（推断，没拼全快照实跑）。
- **证据**：`config/owner_decisions.yaml:609-610 pattern: 'RL-T9' paths: [services/recipes/ns_recipes/lint.py]`；`git show HEAD:services/recipes/ns_recipes/lint.py | grep -c RL-T9` = 0；`:697 file: config/pipeline/asset_worker.json`；`git cat-file -e HEAD:config/pipeline/asset_worker.json` 不存在。
- **建议**：cut A 要么带上 owner_decisions.yaml + lint.py + asset_worker.json（+ 它们各自 pick 的测试，再 --dry 一次），要么接受 T4 §0.2 的方案直接 cut B 一次发。决策表这种“全树耦合”的文件分批发版本质上过不了闸门。

### 4. 2 条红测试的定性
- **#1 test_system_version::test_verified_install_refuses_truncated_stdin**：真红、不挡。`shutil.which("bash")` 在本机 = `C:\Windows\system32\bash.EXE`（WSL 入口），`cmd /c where bash` 只有 System32 / WindowsApps 两个；bash -c "cat > C:/Users/..." 在 WSL bash 里写不到 Windows 路径。被测函数 `_verified_install`（system_version.py:882）和测试相对 HEAD 均未改；sv-16 的闸门记录是 815 passed（docs/system_versions/sv-20261102-16.md:18），说明总调度那套 shell 的 PATH 里有 POSIX bash 排在前面。**定性：环境差异，不是功能坏；但它在 SMOKE 里，真 cut 必须从和 sv-16 同一套环境启动，否则必红。** 建议 MERGE-OPS-O 改测试：bash 路径含 System32 或 `bash -c 'uname'` 不是 MSYS/Git 时 skip。
- **#2 test_sv_verify_lock::test_locks_md_active_then_inactive**：T4 说法成立。真快照（硬链接 data/）上 11/11 过，本轮 99 过里包含它。根因是 `cut_lock()` 开头 `DATA.mkdir`（system_version.py:533）碰真实 data/system_versions，没 data/ 的模拟快照才被 real_data_guard 判红。P2：测试应同时 monkeypatch SV.DATA，或 cut_lock 改成 mkdir CUT_LOCK.parent。

### 5. 逐文件 diff（47 个）
- **副作用 / 真实数据写**：report_issue.py 写 data/pipeline/issues.jsonl + 在 docs/master/V2_LIVE.md 第一行后插行（:36-46）；sop_gate.py `_log_violation` 追加 data/pipeline/sop_gate/violations.jsonl（:329）、probe_prompts 写 data/pipeline/sop_gate/<run>/epNN_prompts.json（:498）；episode_metrics.write_summary 写 data/pipeline/runs/<run>/metrics/ 与 data/review_pages/metrics/（:865-885，非原子，见第 1 条）；episode_retro 写 docs/master/RETRO_epNN.md（原子）；system_version.cut_lock 现在每次都重写 docs/uimaster/LOCKS.md（:540），**包括 --dry**（本轮 dry 后 LOCKS.md 与拼树一字不差，往返稳定，核过）；quarantine_refcheck.record_retired 写 data/_quarantine*/RETIRED.json。全部是设计内写入、都在 root 参数下，测试夹具用 tmp。conftest 新增 NSFS_INBOX_DIR 临时目录、DERIVED_OUT 沙盒（HEAD 的 asset_refs 没有 DERIVED_OUT，conftest 用 hasattr 守着，不炸）。
- **C-14 硬编码**：sop_gate.py:308 `"series10" if is_legacy(run)` 新代码写死 V1 整集预览目录名（P2，应走 runs.py 取 legacy 路径）；defect_hunt.py:398 林晚/顾沉/陈宇/阿岚、data_parity.py:240 docstring 均为 HEAD 既有、本轮 diff 未动，且 defect_hunt 已被 gate_legacy_tool 限定 V1；其余 45 文件无。
- **绕过闸门的分支**：sop_gate.json `enabled:false` → require 直接放行且**不记违规**（sop_gate.py:379-381）；master_check SWITCH_EXPECT 只看 observe_stages（info），不看 enabled → 有人关总开关巡检看不见（P1，建议加 `sop_gate.enabled eq True`）。`observe_stages` 现为 [资产就绪, 提示词, 出图]，json 自己写的解除条件“第 1 集过导入闸门后清空”已经满足（真实 status：ep01 已过 剧本→导入闸门，卡资产就绪缺口 1），但没清空；这三阶段 observe = 资料不齐也能出图，与 OWNER_CANON C-16“资料齐全才出”冲突（P1，总调度清空或写明新解除条件）。`retro_enforce` 可配置关掉（P2）。无 env 变量绕过。
- **没测试覆盖的关键路径**：`promote` / `promote_check`（写 runs.json 状态机）在 G1、G3 的测试里都没有一条（grep test_sop_gate.py / test_episode_retro_master_check.py：0 处）；`_probe_subprocess` 只在注入 runner 时被绕过；require/filter_jobs/observe 的 12 条测试全在 G3 的 test_sop_gate.py，cut A 里 sop_gate 只有 judge/retro 两条间接覆盖（test_episode_retro_master_check.py:70-78）。P1：promote 补测试（至少 preparing→producing 一正一反、--apply 写 status_history）。
- **conftest `auto_final_on_lock` 替身**（:46）传 run 参数，HEAD 的 final_tier 签名只有 path（final_tier.py:39）：显式传 path 的测试在 G1 树会 TypeError，G1 定向测试都不传，T4 说法核过（P2）。
- **docs 27 个**：无密钥（PUSH_SECRET_RE 口径 grep 0 命中）。CUT_PLAN_sv17.md 自己也在 G1 里。

### 6. 部署面（cut A 若被 deploy）
- **谁说了什么**：T4：“cut A 只入 git；在服务器上能跑，但不带 G3 时 sop_gate 资产就绪阶段读不到 asset_jobs 产物，意义不大”。
- **实际是什么**：不崩。check_assets 读不到 `_ready_epNN.json` 返回 ok=False“没有 episode_ready 结果”（sop_gate.py:216-218），status / master_check 正常出页（快照实跑 master_check 全 7 节有输出）。但 ① cut A 树上没有任何调用 require 的生产代码（asset_worker / build_jobs / night / vidgen / producer 都在 G3/G4/G6），闸门等于没接线，test_sop_gate.py:171 的接线测试在 G3；② master_check ④ 在 G1 树上 3 条假 ❌（agent_dispatcher.json / asset_worker.json HEAD 都没有 → 值 None）；③ `deploy` 现在默认自动 `verify`，verify 要服务器 `golden_v2.py --summary --shot` 打 GOLDEN_SUMMARY，HEAD 的 golden_v2 没这两个参数（grep 0）→ cut A 部署 verify 必 fail、deploy 退出码 1（失败关闭，不是崩）。结论：同意“只入 git 不 deploy”。

### 7. 旁注（P2）
- `cut()` 在 `--tree` 分支之前就 cut_lock(True, note="预冻结：等冻结目录 60 s 无改动")，给 --tree 的 dry run 也会把全仓锁 10 分钟并写 LOCKS.md 🔒（本轮 04:54–05:00 其它 agent 看到的冻结就是我这次 dry）；note 文案对 --tree 不准。
- sop_gate.json `_doc` 仍写“默认 golden_v2 --summary”，代码 DEFAULT_CFG 已是 build_first+preflight（sop_gate.py:66），文案陈旧。
- quarantine_move.py `ROOT = Path(r"D:\NS-Final Studio")` 写死盘符（HEAD 既有）。

**cut A 可以发：否。P0：① 闸门 4 红（arch_scan 4 处退化 / D-CLN-05 / D-VQA-01 ×10 / 1 红测试）；② runs.py 缺依赖（probe-prompts、promote --apply、defect_hunt 炸）；③ 决策表耦合（HEAD 表红、工作树表又要 G2/G3 文件）。** 清单调整：**补入** tools/autopilot/runs.py、config/owner_decisions.yaml、services/recipes/ns_recipes/lint.py、config/pipeline/asset_worker.json（补完再 --dry 一次，仍不保证 decision_check 全绿）；**剔除** 无（docs 全部可进）。更省事的路线是 T4 自己的 §0.2：G1–G7 一次 cut B，先把 arch_scan 4 处和 truncated 测试环境问题修掉。



## 第 21 轮（A5 · Fable，Orca 工人 ctx_6a0f16e9bbd3，总调度 MASTER-WSL 派）· 11-03 05:01 · W5 UIUX 复审（项目方视角）

**结论：代码绿、交付态不合格（否）。P0 条件：① 正式 :8800 未重启 → 首页 fallback 写“没有卡住”是假的；② 阻断卡点取最旧一条（升序）。P2：修改语义、工程词、重复卡点、topbar_check。→ 派 W5b 修，修完总调度受控重启 :8800。**

# A5 独立审计：W5 UIUX 交付（只审不改）— 2026-11-03 05:0x

审计者：Fable（A5）。标准：项目方醒来 30 秒内能否明白「在哪一步 / 卡在哪 / 要我做什么」。
实跑环境：本机。正式 :8800 + 正式 vite :5173（= 项目方早上真正看到的）；另起临时预检 API :8813（NS_API_PREFLIGHT=1，不写数据）+ 临时 vite :5179（配置文件放仓库外，仓库零改动）跑新接口。

## 实跑证据
| 项 | 结果 |
|---|---|
| pytest uirsi + l123 + test_ui_stepbar | **131 passed**（80 s） |
| npm run build | **exit 0**，✓ built（既有 >500 kB 警告） |
| shoot_w5.py @ :5179（新接口） | **exit 0**，20 路由全通无 404，7 张截图与 W5 原图像素差 0.4–1.7%（只差顶栏时间性数字）→ 可复现 |
| shoot_w5.py @ :5173→:8800（正式、fallback） | **exit 0**，20 路由全通；截图 data/review_pages/ui_20261103_a5audit/prod/ |
| GET /api/sop/stepbar 只读 | :8813 连调 3 次；data/ config/ 共 48 531 文件 mtime 快照前后，变动 31 个全属 autoflow / sentinel / netfix / producer / writer_tasks 常驻进程；data/pipeline/issues.jsonl、data/sop/ 未动；sop.py L925–1131 无任何 open/write/dump → **只读成立** |
| 正式 :8800 | /api/sop/stepbar → **404「没有这个接口」**（未重启，W5 自述属实）；/api/pipeline/status 200 |
| 阶段模型一致性 | master_check 04:52 与 /api/pipeline/status 同时刻一致（ep01 资产就绪、ep02 导入闸门）；stepbar 只调 pipeline_status + report_issue.load，六步 = sop_gate.STAGES 分组（测试锁定） |
| 03b 假数据 | 只在 e2e 脚本里用 Playwright route 拦 /api/owner/inbox 注入；前端源码无 "演示数据"/DEMO → 正式页面不会出现 |

## OVERSIGHT_LOG
### P1-1 fallback 静默误导：正式页面今早会说「没有卡住的步骤」
- W5 说：没重启前退回旧接口，「计数照常，但没有卡点和负责方，'卡在哪'格会写明」。
- 实际：prod/01_home_stepbar.png：顶栏「①剧本 完成1·进行1」「②资产 完成0·进行1」；「卡在哪·谁负责」写 **「没有卡住的步骤（卡点登记要后台重启后才显示）」**；「系统在做什么」把 **默认负责方**（写手 + 系统检查 / 系统·资产作业）当事实显示；矩阵图例仍写「状态来自后台的阶段检查和卡点登记」。同一时刻真相（master_check / :8813 新接口）：未关卡点 36 条、阻断 24 条，ep01 ②资产「卡住：资产作业连续失败」，ep02 ①剧本「卡住：空转」。
- 证据：stepbar.ts fromPipe() 只设 fallback:true；PipelineMatrix.tsx 全文件仅第 78 行一处用到 fallback，且只在 blocked 为空时出现；TopBarV3 步骤条、矩阵、图例均不读 fallback；issues_error 字段前端从未渲染。
- 建议：fallback 时顶栏 + 「现在」四格 + 矩阵顶部统一加一条醒目横幅「后台还没重启，下面只有进度、没有卡点」，并把「没有卡住的步骤」改成「卡点读不到」；或先重启 :8800 再给项目方看。

### P1-2 「卡在哪」一句话取的是最旧的卡点，不是最新的
- W5 说：卡住格第二行 = 卡点一句话。
- 实际：sop.py stepbar_view 对卡点按 (非阻断, time) **升序**排，取 blocking[0] → 最早登记的那条。:8813 实跑：ep01 ②资产显示「资产作业（江予白）连续失败」（02:24），而 master_check 最新阻断是 卓琳 outfit1（04:38）/ 祁念 O4（04:27）；W5 截图 01 的「第1集 补丁环 10 轮白做」（03:24）在截图时已被 04:03/04:15 的新卡点覆盖。盲测时项目方看到的「卡在哪」= 几小时前的旧原因。
- 证据：ro_check 输出 now.blocked[0].block；sop.py L1056。
- 建议：阻断项按 time 降序取最新一条；详情列表倒序。

### P1-3 盲测三问 vs 真相（截图 01/02 时点 04:34；真相取 04:49 master_check）
| 问 | 我从截图读到 | master_check 真相 | 一致？ |
|---|---|---|---|
| 在哪一步 | 第1集 ①剧本「还有1处要改，系统正在自动修」 | 04:49 ep01 在导入闸门「重新导入失败」，04:52 已到资产就绪 | 时点漂移可解释；**但正式 fallback 页今早会显示「完成/进行中」而无卡住** |
| 卡在哪 | 「第1集 补丁环 10 轮白做 · 负责 总调度 · 共16条」「第2集 空转 · 总调度」 | 最新阻断：producer 重导失败（K211-F 04:41）、卓琳/祁念资产作业失败（ASSET-WORKER） | **不一致**（P1-2 旧条优先；负责方「总调度」实为 WATCHDOG/K211-F 登记） |
| 要我做什么 | 「挑 祁念 造型 O4 的设定图（2 选 1）」→ 去待办 | /api/owner/inbox count=1 pick | 一致 ✅ |
- 结论：「要我做什么」这一问合格；「卡在哪」在新接口下答错（旧条），在正式 fallback 下答「没有」。

### P2-1 C-17 不删功能：20 路由可达 ✅（URL 直达 + 入口登记）；点击级验证见文末「未核/已核」
- W5 说：20 个旧路由都能从 UI 点到。
- 实际：e2e 只用 goto(URL) 验证，不是点击；test_ui_stepbar 只核 pageMap.ts 登记了入口字符串。源码核对：TopBarV3 TOOLS 菜单含 项目设置/全剧总览/新建剧本/写作对话/剧本导入/资产中心/图像编辑器/声音/画布/串播/表格/分镜表/成片·剪辑器·整集预览/模型/A-B/操作记录/回收站/V1 库/旧资产地址/任务队列/快捷键；AssetCenter 左栏有 资产包清单、图像编辑器(#/image-edit)、声音(#/sound)、人物；CutPage 内嵌 CutEditor（mode=edit）+ 整集预览；404 页与 #/settings 页底 AllPages 列全部 20 条。结论：**入口在代码里都存在，没有被收敛掉**；点击级 Playwright 结果见文末。
- P2：W5 自述跳过 e2e/uirsi/topbar_check.mjs（r45 P0 的顶栏不回退检查），此检查要求顶栏有「第 N 集」下拉——现在顶栏确实没有（在范围条里），该检查如进 G10 会红。建议总调度决定是改检查还是补回下拉。

### P2-2 C-09 / L-123 残留
- 全站 grep：无「要这个 / 不要 / 拒绝 / 打回」按钮可达。RejectDialog 组件仍在 components/Dialogs.tsx（已无渲染入口，App.tsx 注释说明），keymap.ts 仍引用 rejectFor 状态（死代码）。FeedbackLayer 的「打回」是反馈工单的重开，不是镜头判决，可接受。
- queueActs.ts：「修改」在 decide 类条目上实际提交后端 key **reject**（带一句话）。对「花钱」类拍板，项目方点「修改」= 不同意花钱，语义有歧义（P2）。建议 decide 类第二个按钮文案改「不同意（写一句话）」或在输入框提示「写了就是不批准」。
- C-10：#/queue 之外仍有项目方动作入口：OwnerDecisionDialog（CutPage G5 验收 / G4 锁样片 / 确认造型）、P1Review「用这版」、Canvas「待你决定 1 查看」、AssetsPage/OwnerConfirm 确认造型。它们与待办是同一批事项的页内入口（待办「修改」本身就是跳到页面），不算违反，但「每页 ≤2 个主操作」在画布 / 资产中心确实没做（W5 自述一致）。

### P2-3 中文大白话：工程词位置（抽查 10 页 + 卡点文案）
- 页头一句话（pageMap.ts 20 条）、空态（05 出图页「第 10 集还没有镜头…」）、404 页：**干净** ✅。
- 仍含工程词、项目方会看到的位置：
  1. 总览格子详情（:8813 实跑）：「补丁环 I6 把候选稿的 **lint** 码和原始 **P4** 比」「模块级 = 调用了 3030 行后才定义的）使 **producer 整体 import 失败**」「提示词探针（逐镜编译+**preflight**）」「verify 拿不到 prompt **sha** 比对」「**P1 storyline** 第2集 **logline** 写 **SH2**」；负责方「工程师（**REVIEW-A / HARNESS-O / SYSAUDIT-F / autoflow run**）」。test_no_raw_text_leaks 只测 5 个固定 token，挡不住这些。
  2. 待办卡片（03_queue / 正式 inbox）：「候选 1（**seed 1101**）」「都过了**出图契约**、本地看图、年龄观感和 **OCR**」。
  3. 待办页右上快捷键说明「← → 换一条 · 1 批准 / 用这张 · 2 修改 · 空格 看详情 · Z 撤销上一个」——可接受但密。
  4. 画布镜头行：「SUMMICRON-M 50mm F2」「KODAK VISION3 500T 5219」「static shot」——旧问题，非 W5 范围。
  5. 「已知要先解决：阶段 B 新代码要生效需重启」出现在 ep01 ④出图「未开始」格里，负责方标「系统·出图」（登记人 GOLDEN-O 是工程 agent，不是系统）。
- 建议：report_issue 登记时加 plain 字段（W5 已提）；owner_label 把 GOLDEN/HARNESS/REVIEW 统一成「工程师」而不是「系统·出图」。

### P2-4 其它
- 同一卡点文案重复 5 次（「资产作业（江予白）连续失败」×3、「卓琳」×2，共 14 条）：report_issue 未关项没去重，详情列表全是重复行。建议按 issue_plain 文本去重并计数。
- ep01 ①剧本已「完成」仍挂 5 条「挡路」旧卡点（补丁环 10 轮白做 等，已过时未关）——UI 忠实显示，但项目方会困惑「完成了为什么还挡路」。建议 done 格不显示阻断，或总调度关旧单。
- shoot_w5.py 的 OUT 参数若在仓库外会 ValueError（relative_to(ROOT)）；两次 e2e 均记录 blocked_non_get=2（有页面在只读模式下仍发非 GET 请求，被拦，未查是哪一个）。
- e2e 首次打开 vite 冷编译 >20 s，脚本用 180 s 等待，正常。

## 点击级入口验证（Playwright 点 UI，不输 URL；:5179）
- 已核 ✅（点「设置 ▾」菜单项真正到页、页头一句话正确）：全剧总览、新建剧本、写作对话、剧本导入、资产中心、图像编辑器、声音、成片·剪辑器·整集预览、模型与 API、回收站、第一版视频库、资产中心（旧地址）、分镜表（→ #ep01）、任务队列（抽屉）、快捷键（弹层）= 15/20。
- 未核（我的脚本问题，不是页面问题：选择器含「/」解析失败、5 s 超时、菜单被 modal-back 遮）：项目设置、剧本 A/B 对比、操作记录、画布、表格视图；步骤条 6 个按钮 / 顶栏「待办」/ 左上标识 的点击结果因输出截断未记录。以上入口源码里都在（TopBarV3 TOOLS / STEPS），URL 直达 e2e 全通；按总调度 05:15 时间盒不再重跑。

## 结论
**W5 能否进 sv-17：否（带 P0 条件）。** 代码本身无 P0（只读成立、测试/构建/e2e 全绿、功能未删）。阻止项是**交付状态**：正式 :8800 未重启，项目方早上打开的是 fallback 页，页面会断言「没有卡住的步骤」且把默认负责方当事实（P1-1），与真相（24 条阻断）相反——这正是项目方「难理解」的核心。满足两条即可进：① 重启 :8800 让 /api/sop/stepbar 上线（或 fallback 加醒目横幅）；② 卡点取最新一条（P1-2，一行排序改动）。

给项目方早上看的 3 句话：
1. 新首页能在 30 秒内告诉你「第几集、哪一步、要你做什么」，待办只剩「批准 / 修改」两个按钮，20 个老页面一个没删，都收进右上「设置 ▾」。
2. 但后台还没重启，今早首页「卡在哪」那一格会写「没有卡住」——这是假的，实际第 1 集资产和第 2 集剧本都卡着，等总调度重启后才会显示。
3. 卡点的解释文字还是工程师口吻（lint、producer、seed 之类），下一轮要让登记卡点的人写一句人话。

---

## 第 20 轮（A6 · Fable，Orca 工人 ctx_ed17e11918e5，总调度 MASTER-WSL 派）· 11-03 04:52 · W6 ASSET-SHEET 复审

**结论：否进 sv-17（无 P0，2 P1：判词器对否定句/多人句误 pass；taskkill 只看 pid 会杀错进程树）→ 派 W6b 修。**

# A6 · W6 ASSET-SHEET 独立审计（Fable，2026-11-03 05:0x；只审不改）

范围：tools/pipeline/asset_checks.py / asset_worker.py / asset_jobs.py（均为未入库新文件）、services/api/ns_api/owner_pick.py:326 路径、tests/test_asset_pipeline.py W6 段、sheet-lead_f-O4 作业与两张候选。
实跑：asset 相关 15 个测试文件 153 passed（含 W6 新增 7 条）；episode_ready series10_v2 ep1；两张候选绕过看图缓存重跑 age_check / bundle_check / anomaly.check。

## 逐条

### 1. 判词解析（C-22 / HC-07 红线）
- **谁说了什么**：W6：“_age_status 改为取第一个出现的判词；判词是未成年、或没有判词，一律 fail；没放宽。”
- **实际是什么**：反例集（旧 = `startswith("成年")`→pass / `startswith("无人物")`→na / 其余 fail，按 cast_v2.py:119 同款写法复原）跑新旧两版，fail→pass 翻转的有 8 条：

| 回答 | 旧 | 新 | 合理？ |
|---|---|---|---|
| 画面里的人看起来是“成年”，因… | fail | pass | 合理（W6 根因） |
| 年龄：成年 | fail | pass | 合理 |
| 她是成年人；旁边的孩子未成年 | fail | pass | **不合理**（多人句放过未成年） |
| 这个人是成年人，但另一位像未成年 | fail | pass | **不合理** |
| 不像成年人，更像未成年 | fail | pass | **不合理**（否定句，首个判词“成年”在“不像”后面） |
| 不是成年人 | fail | pass | **不合理** |
| 非成年 | fail | pass | **不合理** |
| 大概率成年，但也可能是未成年 | fail | pass | 边界（不确定句应 fail） |

  未翻转且正确：像未成年 / 看起来像未成年但穿着成熟 / 未成年 / 未成年在前混排 / 没有人 / adult / minor / 不确定 / 约15岁 / 15岁左右的少女 → 均 fail；无人物 → na；空 → untested。新旧都放过：“成年？不确定”“成年女性，约 17 岁”“成年…未成年（成年在前）”（旧写法同样 startswith 成年 → pass，不是 W6 引入）。
- **是不是 P0**：生产路径不是。sheet / face 候选的 passed 要六项全过，年龄之外还有两道独立闸：① anomaly.check 人头数 expected=1（多一个头 → duplicate_person / extra_head → count=fail）；② bundle 第 2 条“外观明显是成年人（大约 N 岁，不像未成年）”由看图模型答 符合/不符合，判未成年时会答不符合 → prompt_vlm=fail。所以“她是成年人；旁边的孩子未成年”这类多人句被 ① 拦，“不像成年人，更像未成年”被 ② 拦。但 `_age_status` 本身作为红线判词器不再失败关闭：否定句、多人句、“大概率…也可能未成年”都 pass，且 age_check（CLI）单独用时没有②这道闸。**定级 P1**（红线解析器放宽，靠别的闸兜底）。
- **证据**：本文附的 adv.py 跑表（已记在本审计）；asset_worker.vlm_items:635/639；tools/vqa/anomaly.py:769-784。
- **建议**：`_age_status` 补三条、三行即可：(a) 首个判词前若紧跟 不/非/不像/不是 → fail；(b) 文本任何位置出现 未成年 且不在“无未成年/没有未成年/不像未成年/非未成年”否定里 → fail；(c) 出现“可能/也许/不确定”且判词是成年 → fail。把表里 5 条不合理反例加进 test_age_verdict_parses_first_verdict_not_prefix。

### 2. salvage（≥2 张 sha 对得上的过检候选就收尾）
- **谁说了什么**：W6：“子进程没收尾 / pending 时若已有 ≥2 张 sha 对得上的过检候选就直接收尾。”
- **实际是什么**：salvage_records(:815) 只收 job.candidates[] 里 passed=True 且 sha256 与盘上复核图一致、且复核 JSON（若有）passed 不为 False 的条目。candidates 条目只在 render_one 完整返回后由 run_job(:915) 追加，而 render_one 的 passed = 六项 label 全 pass/na，复核图与 JSON 也只在 ok 时才拷贝；中途被杀的候选不会进 candidates，更没有 sha。**契约只跑一半的候选不可能被当过检**，核对通过。两点旁注：① 复核 JSON 缺失时 rec={} 仍接管（只影响打分）——可接受，因为 passed/sha 以作业文件为准；② pending 路径的 salvage(:343) 跑在 sop_filter 之前，SOP 闸门没过的集也会把旧候选投进待办——P2。
- **证据**：asset_worker.py:759-779（只在 ok 才写复核文件 / sha）、:915-917、:815-843、:343；test_salvage_refuses_tampered_or_too_few_candidates 通过。
- **定级**：无 P0/P1；P2 一条（SOP 闸门顺序）。

### 3. 超时杀子进程
- **谁说了什么**：W6：“job_timeout_min 超时杀子进程并落 pending/failed + why。”
- **实际是什么**：tick(:270-283) 的 alive 判定：`_PROCS` 有 Popen 用 poll()，否则 `_pid_alive(j.pid)` 用 tasklist。常驻服务每拍用 importlib 重新载入 asset_worker（autoflow_resident._load:31-35 每次新建模块），模块级 `_PROCS` 每拍都是空的 → 生产上**永远走 tasklist 路径**，只看 pid 存不存在，不看命令行。子进程死了没收尾、pid 被 Windows 回收给别的进程（resident 自己、API、别的 run-job、ComfyUI 本地进程都可能），且作业 started_at 超 90 分钟 → `taskkill /PID <pid> /T /F`(:885) 杀错进程并连带其子树。03:30 事故正是“子进程被杀、作业停在 running”这种形态，窗口真实存在。测试里 _pid_alive/_kill 都是 monkeypatch，没覆盖 pid 复用。
- **定级**：**P1**（新引入的 /T /F 杀进程没有身份核验）。
- **建议**：杀前核验：`tasklist /FI "PID eq N" /V` 或 `Get-CimInstance Win32_Process -Filter "ProcessId=N"` 取 CommandLine，必须含 `run-job --job <该作业文件>`（或比较进程创建时间 ≥ started_at）才杀，否则只落状态不杀；并把 `_PROCS` 改成不随重载丢失（挂到 builtins / 单独模块）或干脆在 job 里记进程创建时间。

### 4. ensure_golden 停掉后 owner_pick.py:326 路径
- **谁说了什么**：W6：“ensure_golden 改为只在 _ready_epNN.json 记录，不再生成 golden 作业。”
- **实际是什么**：owner_pick._ready_hook(:325-327) → asset_jobs.after_pick(:1073) → generate(:507) → ensure_golden(:540)，唯一入口，现在只返回字典写进 _ready_epNN.json 的 golden 字段，不写作业文件；tools/autopilot/producer.py 不读 asset_jobs。全仓没有第二处生成 golden-epNN。owner_pick.py:326 的 docstring 仍写“全部就绪时写阶段 B 作业 golden-epNN”，是陈旧注释（W6 没改这个文件）。历史 golden-ep01.json（pending）原样留着，worker 心跳 golden_pending 仍列出它，master_check / UI 可能误读为“待执行”——P2。
- **证据**：grep golden 全仓；data/pipeline/asset_jobs/series10_v2/_ready_ep01.json golden=null（ep1 还有 1 缺口）；test_ensure_golden_only_records_and_keeps_legacy_job 通过。
- **定级**：无漏网；P2 两条（陈旧注释、遗留 pending 作业）。

### 5. 实跑
- 测试：`pytest tests/test_asset*.py tests/test_*asset*.py`（15 文件）→ **153 passed, 0 failed**；W6 指定 4 文件 61 passed（与 W6 报的一致；W6 报的“199 过 1 跳 1 败”是另一组 13 文件，含 test_v2cut_o，本次未复现那组）。W6 新增测试实数 7 条（age 1、salvage 3、timeout 1、golden 1、dead_child_fails 1），与声称一致。
- episode_ready series10_v2 ep1：1 缺口 = 祁念 O4 没有设定图（等 pick）；11 镜 adult 全否。
- sheet-lead_f-O4.json：state=awaiting_pick，attempts=1，candidates 3（1100 age=fail，1101/1102 六项全 pass，sha 齐），pid=None，lane=None；log 记录 04:19 接管收尾；owner_queue requests.json 有 pick:sheet:lead_f:O4（2 选 1，推荐 s1101，候选 sha 与作业一致）。
- 注意：seed1100 的失败记录仍是 age=fail（旧解析所判），W6 没重判也没重出，候选只有 2 张（配置要 3 张）——按 salvage_min=2 设计是允许的，但项目方只有 2 选 1。P2 记录。

### 6. 两张候选图重跑契约（不改阈值，绕过缓存 refresh=True）
- s1101：age_check 首行“成年”；bundle 5 条全符合、年龄“成年，…无未成年视觉元素”、文字“无”、总结全部符合；anomaly heads expected=1 got=1 pass（finger_ratio 为 low 置信只记录）。
- s1102：age_check 首行“成年”；bundle 同上全过；anomaly 同上 pass。
- 两张回答都**以“成年”开头**，旧解析也会 pass；pass 不是靠解析漏洞。缩略图亲看：单人成年女性、雾蓝长直发、黑漆皮抹胸短裙 + 黑丝 + 透明细跟，与 P1 O4 一致。
- 旁注（非 W6 引入）：render_one 的 label.identity 固定 "na"，设定图没做与已登记身份脸的相似度核；待办文案“都过了出图契约、本地看图、年龄观感和 OCR”没说身份——与事实一致，但 owner_delegate 打分口径写着“身份相似度 + …”，与实际不符，P2。

## 汇总
| # | 项 | 级别 | 一句话 |
|---|---|---|---|
| 1 | _age_status 否定句 / 多人句 / 不确定句 fail→pass | **P1** | 红线判词器不再失败关闭；生产路径靠人头数 + bundle 第 2 条兜住，需补三条规则 + 反例测试 |
| 3 | 超时 taskkill /T /F 不核进程身份，_PROCS 每拍重载为空 | **P1** | pid 复用时会杀错进程树；杀前核命令行 / 创建时间 |
| 2 | pending salvage 跑在 SOP 闸门前 | P2 | 顺序调到 sop_filter 之后 |
| 4 | owner_pick.py:326 注释陈旧；golden-ep01 pending 遗留在心跳里 | P2 | 改注释；遗留作业标 done/closed_reason 或心跳里注明“已停” |
| 5 | seed1100 未按新解析重判，候选只 2 张 | P2 | 可接受；记录 |
| 6 | identity 固定 na，代选打分文案与实际不符 | P2 | 非 W6 引入，另派 |

**W6 能否进 sv-17：否（无 P0；两条 P1 需先修：① _age_status 否定/多人/不确定句失败关闭 + 反例测试；② 超时杀进程前核验 pid 身份）。两张候选与 awaiting_pick 状态本身没问题，项目方可照常在 #/queue 选。**

---

## 第 19 轮（A1 · Fable，Orca 工人 ctx_e63cbe94ddc8，总调度 MASTER-WSL 派）· 11-03 04:47 · W1 FACTORY-V2 + PRODMERGE-O producer.py 复审

**结论：A1 审计完成：P0 无；P1×3（误交接 / producer require 无退避 / retire 绕守卫）；可进 sv-17 分批 cut**

# A1 独立审计（Fable，只读）· W1 FACTORY-V2 + PRODMERGE-O producer.py 改动 · 2026-11-03 04:3x

A1-1 ｜ W1 说：identity_drift 每拍重判，剧归档/主剧换了才交接。｜ 实际：drift 只读 runs.json，心跳坏/缺字段不触发（实跑 CASE C → None）。但 runs.json 一次读失败（截断 ValueError / Windows os.replace 撞读者 PermissionError）→ runs.registry 非 strict 回退 run.json → 再回退 DEFAULT_PRIMARY=series10_v1 → 误判“主剧已切到 series10_v1” → 正确的 V2 进程停派单并退出；handoff 时 runs.json 已恢复则 new==run_id → successor=None → V2 无人出图（笔记本无自动拉起）。｜ 证据：实跑 scratchpad/drift_test.py：CASE A（runs.json 截断+无 run.json）drift=“主剧…已切到 series10_v1”；CASE B（截断+run.json 旧指针）同；CASE C（runs.json 正常，心跳坏）None。tools/autopilot/runs.py:26-30 `_jl` OSError→None、:44-52 registry 回退、:23 DEFAULT_PRIMARY；producer.py:3250-3252、:3281-3283；producer.py:638 自己注释“Windows os.replace 会撞上读者”，而 runs.py:33-37 `_js` 无重试；tests/test_producer_run_identity.py 无读坏登记表用例（grep 0）。｜ P1 ｜ identity_drift 读登记表失败=“未知，不动”（strict 或显式判 None）；drift 连续 ≥2 拍才交接；handoff 末尾复核 new==run_id 且未归档 → 放弃退出继续跑。

A1-2 ｜ W1 说：排空在途 ≤15 分钟。｜ 实际：drain 900s 到点 inflight 非空也写心跳 exited、放 pid、return；ThreadPoolExecutor 非守护线程在解释器退出时 join，在途单实际跑完并照常写 takes/账本（不丢、不重排）；但此时心跳已是 exited（⑥ 显示“已退出”而 GPU 还在为它跑）。｜ 证据：producer.py:3273-3296、:1868 pool、:2628-2637 finally。｜ P2 ｜ 超时未排空写 state=draining 而非 exited；或把 drain 上限设成 ≥ LEASE_S。

A1-3 ｜ W1 说：pid 文件防重、拉起新主剧 serve。｜ 实际：同剧防重只在 serve 启动读 pd/producer.pid + pid_alive（非 O_EXCL、不校验进程身份；PID 被别的进程复用 → 永不启动且退出码 0）。successor 只在排空后拉起且 pd/pid 按剧分开，同剧无双派单窗口；旧进程残余线程仍占道，新进程 probe_lanes 把队列里 PRODUCER 标签当自己人 → 预取深度内叠加。｜ 证据：producer.py:3301-3305、:1042-1052、:2204-2209、:3254-3267。｜ P2 ｜ pid 文件 O_EXCL 写 + 心跳 pid/started 校验。

A1-4 ｜ PRODMERGE-O：preparing→producing 走 sop_gate.promote。｜ 实际：promote_check 走 judge（observe 只影响 require，不影响 judge），实跑 `sop_gate.py check --run series10_v2 --episode 1 --stage 出图` → “不能进入”（导入闸门 reopened / 资产缺口 1 / 提示词 6/11）；`promote` → promote=false；sop_gate.json promote.auto=false → producer 只记 promote_ready，不写 runs.json。无抢跑，不违反 L-140/C-16。备注：一旦 producing，按镜 sop_gate_block 在 observe_stages 含“出图/提示词”时全放行，是配置口径不是代码缺陷。｜ 证据：scratchpad/runs.out；sop_gate.py:522-549、:356-371；producer.py:1897-1902、:1905-1927；config/pipeline/sop_gate.json。｜ OK ｜ 无。

A1-5 ｜ PRODMERGE-O：sop_gate_block 派单前按镜过闸门。｜ 实际：每拍 20s 对每个 ready 候选调 require；require 在 observe 下无条件 _log_violation，无退避/去重（producer 的 10 分钟去重只管自己 log.jsonl）。V2 转 producing 且出图仍 observe 时 ep01 11 镜 ×（首帧+尾帧）→ 每分钟几十条 violations.jsonl，正是 W1 刚在 asset_worker 侧修掉的同一事故（ISS-1103-033742-73be）复刻到 producer。与 asset_worker 不是同一 stage（资产就绪 vs 出图/尾帧）不算重复计同一条，但 master_check “违规 N 次”把两者合计。｜ 证据：producer.py:2370-2386；sop_gate.py:356-371、:329-336。｜ P1 ｜ 把 asset_worker 的 judge+退避抽进 sop_gate（如 require_backoff(by,stage,ep,shot)），producer 侧复用；至少在 observe_stages 清空前修。

A1-6 ｜ W1 说：asset_worker 退避按 (by,stage,missing) 去重，任意 30 分钟 ≤2 条。｜ 实际：签名含 missing 全文，missing 里有“第 N 次”计数 → 计数一变即视为新一轮重写违规。实测 03:59→04:17（22 分钟）写了 7 条（03:59:05、04:01:58、04:10:33、04:13:50、04:15:25、04:17:02、04:17:34）；_sop_backoff.json first=04:17:34 logged=1，一直被重置。｜ 证据：data/pipeline/sop_gate/violations.jsonl 统计（近 90 分钟 165 条全为 asset_worker/资产就绪/observe/ep1）；data/pipeline/asset_jobs/series10_v2/_sop_backoff.json；asset_worker.py:432-437。｜ P2 ｜ 签名前剥离计数/时间（如 `（第 \d+ 次）`），或只按 missing 的阶段名签名。

A1-7 ｜ 问：enforce 切换期间是否沿用旧 mode 最长 30 分钟。｜ 实际：cfg_sig 含 enabled + 本阶段是否 observe，切换立刻重判，不沿用。｜ 证据：asset_worker.py:426-431；tests test_state_change_rejudges_immediately 通过。｜ OK ｜ 无。

A1-8 ｜ W1 说：隔离守卫 protected_code / kept_code，RETIRED.json 例外。｜ 实际：move_one 对 tools/tests .py 只要计划项带 retire:{reason,by} 两个任意非空字符串即放行，且跳过引用检查（“退役登记代替引用检查”）；decision 可空、by 不校验。实跑 dry：`retire={"reason":"x","by":"anyone"}` → tools/autopilot/producer.py = would_move，code_refs 空。｜ 证据：scratchpad/probe_move.py 输出；quarantine_safe_move.py:60-71；quarantine_refcheck.py:88-104 record_retired 只查非空。｜ P1 ｜ retire 项仍跑 RC.check 且 code_refs 必须为空；by 必须含“总调度/项目方”，decision 必填并匹配 L-\d+/ISS-。

A1-9 ｜ 守卫范围。｜ 实际：CODE_ROOTS 只有 tools/tests；services/ packages/ apps/ ops/ 的 .py/.ts 不受保护（services/api/ns_api/producer.py 只是碰巧因同名命中被 kept_referenced）。`quarantine_refcheck.py --scan-quarantine` 报 21 个旧隔离区系统代码未登记（data/_quarantine/tools/*.py 等），master_check 没接这个扫描。golden_worker.py / test_golden_pipeline.py 已在 RETIRED.json（by 总调度MASTER-WSL，decision L-151）。｜ 证据：quarantine_refcheck.py:63-64；scan 输出。｜ P2 ｜ CODE_ROOTS 扩到 services/packages/ops（.py/.sh/.ts）；master_check 加 scan_quarantine 一行。

A1-10 ｜ W1 说：master_check ⑥ 按主剧 + producing 读心跳；resident_sync 读 producer_rel(RUN_ID) 并报 mismatch。｜ 实际：⑥ 取 primary 先读 run.json 再回退 runs.json（与 PRODMERGE-O“只认 runs.json primary”相反）；resident_sync.py:36 RUN_ID 是模块级 primary_run 缓存，loop 常驻期间 primary 一切换，health 仍看旧剧目录且 producer_run_mismatch 会对新进程误报——与 ISS-1103 同类的导入时缓存。实跑 ⑥ 输出正确：V1 pid 13972 旧代码仍跑、V2 无心跳（W1 代码尚未热进进程）。｜ 证据：master_check.py:180；resident_sync.py:36、:698、:727。｜ P2 ｜ 两处改为每拍 primary_run(strict)。

A1-11 ｜ PRODMERGE-O：fanout 一镜多种子分道。｜ 实际：默认关（producer.json fanout.enabled=false，注明与 L-140 冲突）；实现是 producer 内新写 dispatch_fanout，golden_worker 已从树里删，树内无第二份（L-137 字面满足），但 golden 的 per_lane/max_parallel/候选≥3 语义没搬，只保留“每种子一次尝试 ≤3”。细节：fanout 种子绕过 obj_rate_exceeded/hard_capped；主槽完成即 release 租约而 #k 槽仍在途 → 对象可再被“一对象一道”派单，超 max_per_obj。｜ 证据：producer.py:2388-2431、:2636-2637、:2268；config/pipeline/producer.json。｜ P2 ｜ 开启前补：fanout 走同一组上限检查；lease 在最后一个槽退出才 release。

A1-12 ｜ W1 说：定向 pytest 142 passed。｜ 实际：简报指定的 6 个文件 = 47 passed（45s）；tests/test_prodmerge_o.py 另 23 passed；`import producer`（RUN_ID=series10_v2）/`import asset_worker` OK；master_check 全段正常退出。142 这个数对不上指定集合（可能含别的文件，W1 没写明）。｜ 证据：scratchpad/pytest.out、runs.out。｜ 事实 ｜ 交付单写清 pytest 的文件集合。

结论：能否进 sv-17 分批 cut —— 是（P0 列表：空）。但 A1-1（runs.json 读失败误交接）与 A1-8（retire 随手绕守卫）各 <10 行改动，建议随本批一并修；A1-5（producer 侧 require 无退避）必须在 observe_stages 清空 / V2 转 producing 之前修，否则下一集 violations.jsonl 重演。

---

## REVIEW-A sv-17 第 2 轮 · 11-03 04:1x · 复核 K211-F 对 P0 / P1①②③⑤ 的修复（Fable，只读）

**结论：可以进 sv-17。** P0 已修、三件核实项成立；没有新的 P0。带 2 条 P1（不挡 cut，sv-17 后第一批修）和 3 条 P2。P1④（sop_gate 成人镜）按总调度说明不在本轮范围。

### 实跑
- 22 个文件 356 用例：**350 passed / 6 failed**（1 m 31 s）。6 条失败都不是本轮改动的回归：`test_timeline_o`、`test_v2cut_o`、`test_merge_vid_o ×2`（读真实 `P4_ep01.final.md` / 真实 API 快照，adopt 换底后文件改名，就是总调度说的真实数据测试）；`test_owner_gate::…took_over_via_gate`（tmp 剧 took1 复制了 V2 故事线，`sk_white_cyc` 被按“别剧内容”拦——守卫按“除本剧外所有剧”取词是设计如此，是夹具耦合真实 runs.json）；`test_agent_dispatcher`（上一轮 P2-1 假 claude 读 stdin 没按 UTF-8，仍未修）。
- 新测试 `test_k211 / test_patch_exhaust / test_full_p4_adopt / test_segment_fix / test_review_a_p0p1` 全过（含行为用例：adopt 换底清零预算、补丁环等包时整集稿缓一拍再收、hard_blocks 稿拒收、requeue → reopened 被 daemon 接手、同一错误 3 次 halted_error + 登记）。

### 三件核实
1. **补丁环基线 = 当前稿 ✅**：`autoflow_agent.py:1013-1014` `base_lint = H.lint(cur, ep)`；`R5.gate5(pre, cur, c, …)`，I6 / I2 / F1 都对 cur 比；hard 口径收成一处 `hollywood_r5.hard_checks`（:184，SOFT_CHECKS + 调用方 auto_fixable），post_step 与 r5 轮回同一函数。原始 P4（base）只剩 I2 造型行放行那一处引用。
2. **hard_blocks 堵死 ✅（主路径）**：进补丁环的三个口全部经 `non_tl_blocking`（hard_blocks → 99）：chain_step 首分支 `:896` 改走 `patchable_p4`（旧 report.json 的 blocking≤6 不再信，`test_full_p4_adopt:159` 有断言）、chain_step 新稿 `:922`、intake_full_p4 `:1793`；导入前 post_step 仍以 `lint_now["shot_block"]` → not_importable 兜底，硬阻断进不了导入稿。剩一个**休眠绕路**见 P1-A。
3. **整集稿只有 adopt 一个来源 ✅（claude_agent 后端）**：写 `P4_epNN.md` 的只有 `adopt_full_p4`（`:1720`，chain_step `:930` 与 intake `:1797` 共用；旧 P4 / final / split 改名留档、补丁包全记已处理、`patch_base` 重置、未交稿补丁 `void_open_patches` 作废并写 .void 让派单器停）。`l141_migrate` / `segment_fix` 是在收稿前对写手产物就地改写（原稿进 data/_quarantine、审计 jsonl），不是新来源；`requeue_full_p4` 只把稿重新排队给 intake。其它写 P4 的地方：`run_chain.run_link:176-181`（见 P1-A）。

### P1（不挡 cut）
- **P1-A · API 后端的 run_link 仍直接写 P4 canon。** `tools/pipeline/run_chain.py:176-181`：`obj is not None` 就写 `P4_epNN.md`，不看 hard_blocks、不走 adopt、不动 final。现在因 `writer_backend=claude_agent`（L-109，`autoflow.py:822`）走不到；一旦切回 api 后端（上线计划）就是第二个整集稿来源 + 硬阻断绕路。建议 P3-P4 在 api 后端也经 adopt_full_p4 + non_tl_blocking。
- **P1-B · 守卫词表对“新剧”的口径要写进 SOP。** `v1_vocab` 取“除本剧外所有剧”的人物 / 场景 id：第 3 部剧开工时 series10_v2 的 `sk_white_cyc` 等会被当旧剧内容，写手包出口 HeaderMissing（本轮 test_owner_gate 的失败就是这个样子）。现在有 `record_run_error` 3 次即 halted + 登记（`autoflow.py:980`，RUN_ERROR_HALT=3），不会再静默空转，但新剧第一天必然撞上；需要在 PIPELINE_SOP_V2 开新剧步骤写明（或白名单按 CLEAN_CUT 的“前作”字段放行）。

### P2
- **P2-A** `test_review_a_p0p1` 的 4 条里 3 条、`test_full_p4_adopt:151-159`、`test_patch_exhaust:98` 是源码字符串断言，不是行为测试；基线 = cur 这一条没有“旧 final 带新码、补丁仍被收”的行为用例。
- **P2-B** `test_agent_dispatcher.py:21` 假 claude `sys.stdin.read()` 不带 UTF-8（上一轮 P2-1），cp936 机器一直红。
- **P2-C** `weak_props`（名单 / 验收 / 图纸 / 老公）只在同段另有 V1 专名时才报（`script_chat.py:613-621`）✅；但 `props` 里仍有“纹身 / 穿孔 / 门卡 / 红绳 / 银戒”等常用词是硬命中，V2 稿正当用到会卡（有 halted_error 兜底，不再空转）。

### 核对通过
- P1② 规则文本：`config/script_chat_rules.md:197` 改为 L-141 拍序写法，`appendix:125` QW-A8 改为“`In the first two seconds,` 之前”；`test_review_a_p0p1::test_p1_2_rules_text_follows_l141` 过。
- P1⑤ 补丁满次：`autoflow_agent.py:1103-1104` `patch_budget_used ≥ PATCH_MAX` → `patch_exhausted`：写 `work_epNN/patch_diag.json`（剩余项 / 逐项已试次数 / 从没出过包的项 / 拒收原因统计 / 方案）+ report_issue（同一 k 只登记一次，登记失败不崩）+ not_importable；reopen 重置 `patch_base`，`pending_done` 对 reopened 自动接手。
- P1③：`autoflow.py:832-835` 异常 → `record_run_error`，同一错误连续 3 次登记卡点 + `halted_error`，`pending_done` 跳过该集；错误消失自动清。
- 本轮没有读 data/master/；没有改代码、没有重启。

---

## 第 18 轮（A2 · Fable，Orca 工人 ctx_a9d03929f029，总调度 MASTER-WSL 派）· 11-03 04:19 · W2 MERGE-IMG 交付复审

**结论：可进 sv-17 分批 cut（无 P0）；2 P1（V1 extras 行为变了 / 6/11 跑在无 extras 旧导入稿上，重导后须重跑）+ 4 P2。**

# A2 · W2 MERGE-IMG 独立审计（Fable，只读，11-03 04:0x–04:2x）

工作树：D:\NS-Final Studio，基线 1d2cc20（sv-16）。W2 改动实际落点：`git diff` 只有 2 个已跟踪文件（script_md.py +2 行、asset_refs.json 1 行），另 3 个未跟踪新文件（tools/master/episode_ready.py、tools/master/sop_gate.py、tests/test_w2_merge_img.py）。tools/master/probe_prompt.py 已不在树里。

## 实跑（命令 / 耗时 / 结果）

| 命令 | 耗时 | 结果 |
|---|---|---|
| brief 原命令 `pytest tests/test_w2_merge_img.py tests/test_episode_ready*.py tests/test_import*.py` | 1.3 s | **exit 2：`file or directory not found: tests/test_episode_ready*.py`**（该文件不存在，brief 的命令本身跑不起来，no tests ran） |
| `pytest tests/test_w2_merge_img.py tests/test_script_importer.py tests/test_import_sources.py tests/test_merge_img_o.py tests/test_merge_import.py tests/test_master_sop_tools.py tests/test_parser_alignment.py tests/test_v2cut_o.py tests/test_asset_refs_inherit.py tests/test_character_hub_assetux.py` | 53 s | 103 passed / **1 failed** / 2 skipped。失败 = test_v2cut_o::test_v2_look_action_per_episode_with_names_and_thumbs（断言 ep01 应有“确认造型”动作，实际 data/pipeline/runs/series10_v2/assets/look_confirm.json 里 ep01 已于 02:23:44 由 owner 确认 → sop.py:757 `if st["confirmed"]: continue`，动作为空。数据态陈旧测试，与 W2 无关，W2 说法成立） |
| `pytest tests/test_sop_gate.py` | 1.2 s | 12 passed |
| `pytest tests/test_w2_merge_img.py -rs` | 0.9 s | 6 passed，0 skip（HAVE_V2 为真，manifest 用例真跑了） |
| `sop_gate.py probe-prompts --run series10_v2 --episode 1` | 2.2 s | 6/11，失败镜 1/2/4/8/9 全部 I3“祁念 造型O4 没有设定图”；写 data/pipeline/sop_gate/series10_v2/ep01_prompts.json（at 04:07:03，fingerprint.import_sha=94337dec…） |
| `episode_ready.py --run series10_v2 --episode 1 --json` | 0.7 s | exit 1，gaps 恰 1 条：kind=look / 祁念 / “祁念 造型O4 没有设定图” / shots **[1,2,4,8,9]** / owner “资产作业 sheet-lead_f-O4（…）”。与探针失败镜**逐镜一致** |
| `tools/script_rsi/v1_leak.py scan --file data/pipeline/runs/series10_v2/P4_ep01.final.md` | 0.2 s | **0 命中，exit 0** |

## 发现（谁说了什么 / 实际是什么 / 证据 / 严重度 / 建议）

### F1 · P1 ·「其余未知字段仍走集级（V1 行为不变）」不成立：V1 / S2 稿的每镜 **光线** / **分拍** 行也被搬进 shot.extras，V1 编译提示词会变
- **W2 说**：报告第 5 行“其余未知字段仍走集级（V1 行为不变）”；tests/test_w2_merge_img.py:57 用“机位与景别落集级”当作 V1 不变的证据。
- **实际**：V1 生产源稿本来就在每镜写 **光线** / **分拍**（staging_v3/merged/…_series10_v1_ep01-10.md 镜内 光线 73 / 分拍 80 处；…_rsiD07_ep01-10_v3.md 87 / 93 处；hwd_ep01–05/08–10 每集 9–10 处）。新导入器把它们从 ep.extras 搬到 shot.extras；frame_job.first_beat_gaze（frame_job.py:146-158）不按剧分流，`:224` / `:234` 视线句直接读 **分拍** 的“视线=”。
- **证据**（同一份 V1 源稿，SHOT_EXTRA_LABELS 旧集合 vs 新集合各导一次，再各走 `FJ.build_first` 编译）：
  - V1 ep01：7 镜中 S6、S7 prompt_sha 变；ep01-S6 视线句 「林晚的脸」→「走廊暗处」
  - V1 ep06：8 镜中 S5、S6 prompt_sha 变；ep06-S5 视线句 「画面里的人或物」→「她睫毛下垂」（该句在提示词里出现 4 次，4 处全变）
  - 重导 V1 全部源稿 vs 现行 data/import/script_v2.json：90 处 extras 归属差异（每集 ep.extras 失去 光线/分拍，各镜 shot.extras 多出 ['光线','分拍']）
- **影响**：series10_v1 在 runs.json 为 archived、series10_s2 paused，当前不会被重导，所以**不挡 cut**；但“V1 不变”这句写进了 CHANGELOG 和测试名，是错误口径。一旦 V1 / S2 任一集重导再编译，视线句会换落点（未经任何人决定）。
- **建议**：CHANGELOG 716 行改口为“V1/S2 稿重导后每镜 光线/分拍 进 shot.extras，first_beat_gaze 会改视线落点”；补一条用 V1 真实镜（如 ep06-S5）固定旧提示词或按剧分流的回归测试，而不是用“机位与景别落集级”代表 V1。

### F2 · P1 · 探针 6/11 是在**没有 extras 的旧导入稿**上跑的；W2 的导入器改动至今没进任何生产提示词或证据
- **W2 说**：“ep01 0/11 → 6/11”“scratch 导入证明 11/11 镜有 extras”“正式重导被 v1_leak‘徕卡’挡”。
- **实际**：
  - 生产导入稿 data/import/runs/series10_v2/script_v2.json（00:59，sources sha 94337dec…）11 镜 `shot.extras` 全为 **[]**，构图/灯光/光线/分拍/表演节拍 全在 ep.extras。探针证据 fingerprint.import_sha 正是 94337dec → 6/11 与 W2 改动无关（6/11 的提升来自 PRODMERGE-O 的 build_first+preflight 探针，不是 extras）。
  - 同一份 final.md 只切换 SHOT_EXTRA_LABELS 旧/新 各导一次再编译：**11/11 镜 prompt_sha 全变**，通过数 6→6 不变。即 extras 改的是提示词内容，不改过闸数；而现有证据里一条都没包含这些内容。
  - W2 说的挡板已不存在：config/v1_guard.json（未跟踪，mtime 04:04:57）已无“徕卡”；`v1_leak.py scan` 对现行 final.md 0 命中。final.md 已在 04:10:11 又被改过（sha e40680… ≠ 导入稿 94337dec…），导入稿已经陈旧；现在挡住正式重导的是 ISS-1103-040944-d569 的 intake 死锁（他人范围）。
  - 重导后 sop_gate.check_prompts 会按 fingerprint 判“证据过期”（sop_gate.py:214），6/11 证据作废，须重跑 probe-prompts。
- **建议**：sv-17 说明里把“ep01 提示词 6/11”标注为“旧导入稿（无 extras）口径”；MERGE-IMG 的“镜头语言 v2 / first_beat_gaze 生效”在重导 + 重跑 probe 之前不得记为已验证。

### F3 · P2 · 镜头语言 v2 七段只收了四段：**机位与景别** / **运镜** / **声音** 仍落集级（和这次修的是同一个 bug）
- **W2 说**：“镜头语言 v2 三段 + 光线/分拍/表演节拍 归到本镜 extras”。
- **实际**：config/director/shot_spec_v2.yaml 定义 7 个 md_label（机位与景别、镜头、构图、灯光、运镜、表演节拍、声音，yaml:10-63）。SHOT_EXTRA_LABELS 只含 镜头/构图/灯光/表演节拍（+光线/分拍）；ep01 现稿每镜都写了 **运镜** / **机位与景别** / **声音**（各 11 处），导入后全部丢到 ep.extras（干跑导入 ep.extras labels = ['下镜','台词时段','场景定稿｜sk_white_cyc','声音','机位与景别','站位','运镜','镜头运动']）。W2 的测试甚至把“机位与景别落集级”写成期望。
- **影响**：今天编译没读这三段（shot_language 只读 镜头/构图/灯光；spec_import 自己重扫 md 拿 站位/镜头运动 等），所以不坏；ep02 起任何按镜读 运镜 / 机位 的功能会原样再踩一次。
- **建议**：SHOT_EXTRA_LABELS 从 shot_spec_v2.yaml 的 md_label 生成（单一来源），或在注释里写明为何故意不收这三段；改掉测试里对“机位与景别落集级”的断言。

### F4 · P2 ·「label 不变」属实，但带括注的 label 编译端读不到
- **实际**：导入器原样保留 label（反例实跑：`**灯光（动机）**` → extras label 就是 “灯光（动机）”）；shot_language.script_field（shot_language.py:62-68）只 `strip("*：: ")` 后与 ("灯光",) 精确比对 → lighting 返回 **""**；first_beat_gaze 用 startswith("分拍") 所以 “分拍（节拍）” 能读到。ep01 现稿 5 个 label 11/11 都是裸标签，今天不触发。
- **建议**：script_field 复用导入器 `_split_label` 的 base 比对，和 first_beat_gaze 一致。

### F5 · P2 · episode_ready 设定图缺口的 owner 在另一条路径下会回到“写手”
- **W2 说**：“sheet 缺口命名为 sheet-<cid>-<look> 作业”。
- **实际**：check() 先扫 `sr.missing`：asset_refs.py:1588 在造型**没有任何单品图**时发 “资产缺图 / <名> 造型X 没有设定图”，episode_ready.py:93-96 把它记为 kind=look、owner=OWNER["look"]=“写手 / 资产线（造型表与清单对不上）”；随后 sheet_gaps 再发同 (kind, who, what) → gap() 合并只并 shots、**保留第一条的 owner**。ep01 的 O4 有单品图走 warns 路径（1586 行）所以没触发，今天逐镜一致；ep02 若出现没有单品图的新造型，缺口会写给“写手”而不是 sheet 作业。
- **建议**：missing 循环里 detail 以“没有设定图”结尾的也用 SHEET_OWNER，或直接跳过交给 sheet_gaps。

### F6 · P2 ·「character_hub / data_parity / resident_sync 对缺键都已兼容（核过）」——两处只是“不报错”，不是“等价”
- load_looks 无 looks_file 时在 asset_refs.py:395 提前 `return manifest_looks(project)`，跳过 399 行的 `hub_extra_looks`（资产中心“＋ 新造型”）和 item_map/extra_parts。data/looks/hub_extra_looks.json 现为 {}，今天无影响；ep02 若有人在资产中心给 V2 加新造型，编译看不到。
- tools/qa/data_parity.py:300-301 `looks = rj(looks_file)` → V2 为 []，name_id 为空；:380/:404/:700 用它做 名→cid，退化为原名比对。未实跑 data_parity，不下结论，只记“非等价回退”。
- character_hub._p1 已单独回落到 <run>/P1_looks.json（character_hub.py:296-303，仅显示用）；resident_sync 只是少推一个文件。这两处确属兼容。

## 已核无问题（含反例）
- **V1 路径静默回退**：series10_v2 无 inherits，`AR.chain_files("series10_v2","looks_file")` 为空（测试断言 + 实读 asset_refs.json:62-71），不会回落到 V1 的 P1_looks.json。
- **反例导入**（字段乱序 + 未知字段 **气味** + 续行 + 带括注 label + 空值 **光线**： + 集级 **光线** 行）：不炸、不吞；未知字段连同续行进 ep.extras（旧行为），镜内字段乱序照常进 shot.extras，镜头前的集级 **光线** 仍留集级；schema round-trip 正常；S1 first_beat_gaze=“灯架后的方向”、S2=“他的脸”。
- **单一实现**：sop_gate.compile_preflight（sop_gate.py:441-469）直接 `FJ.build_first(run, e, sh, s.globals)` + `PF.check(req)`，req 键与生产 unified_frame.py:228-229 一致（多传 framing_project、lane=probe_lane “gpu36:0”，I12 用得到）；无复制的编译逻辑；config/pipeline/sop_gate.json prompt_probe="build_first+preflight"。
- **口径一致性**：episode_ready gaps shots [1,2,4,8,9] 与探针失败镜 {1,2,4,8,9} 逐镜一致，owner 已是 sheet-lead_f-O4；data/pipeline/asset_jobs/series10_v2/sheet-lead_f-O4.json state=pending 存在。
- **label 不变**：导入器写入 `Extra(label=label, …)` 用的是原 label（script_md.py:677），实测含括注原样保留。

## 结论
**可以进 sv-17 分批 cut：是**（无 P0；代码改动本身正确且测试覆盖）。但 cut 说明必须带两句实话：① ep01“提示词 6/11”是旧导入稿（无 extras）上的数字，MERGE-IMG 的导入器效果尚未进任何生产提示词 / 证据，重导后证据作废需重跑探针（F2）；② “V1 行为不变”口径错误，V1/S2 重导会改视线落点（F1）。F3–F6 是 ep02 会再踩的坑，建议在下一批里修。

---

## REVIEW-A sv-17 · 11-03 03:5x · 自 sv-16 以来“写作 / 导入 / 推进 / harness”一批（Fable 复审，只读）

**结论：不可以进 sv-17。** 一个 P0（补丁环 I6 基线过期导致死锁，ep01 已满次 not_importable，主线卡死）；修掉 P0 并让两条失败测试转绿后可以 cut。
依据：OWNER_CANON §A、PLAN_V2_MASTER v4 §1.1 / §3、记忆 ns-final-studio-core；根因模式（双入口 / 规则不生效 / 失败关闭 / 真实数据被测试写入）逐条对照。自己读 diff、自己跑测试，不采信 agent 报告。

### 实跑
- 20 个文件 472 用例：**434 passed / 2 failed**（9 m 31 s）。失败：`tests/test_agent_dispatcher.py::test_whitelist_args_and_done_model_and_metrics`、`tests/test_v2cut_o.py::test_v2_look_action_per_episode_with_names_and_thumbs`（见 P2-1 / P2-2）。
- 真实状态核对（只读 data/pipeline/runs/series10_v2/autoflow_ep01.json）：verdict=not_importable，“补丁已出 11 次仍有失败项，交总调度”；gate / import = reopened；a8–a11 四个补丁全部被 I6 拒；a11 是镜 6 的缩短镜长包，同样被 I6 拒。
- 用现行规则重算：`P4_ep01.md`（I6 基线）lint 只有 TL-7；`P4_ep01.final.md`（当前稿）有 QW-T1、TL-6、TL-9、TL-10、TL-11。两者之差就是 I6 的“变多”。

### P0（已登记 ISS-1103-035043-ec2e）
- **P0-1 · 补丁环 I6 基线是原始 P4，不是当前已采用稿 → 补丁环死锁、满次退回。** `tools/script_rsi/autoflow_agent.py:955` `base_lint = H.lint(base, ep)`（base = P4_ep01.md 原稿）；`tools/script_rsi/hollywood.py:436` I6 “每个码不比原稿多”拿候选稿和这个基线比。当前稿 final.md 经前几轮补丁 + TIMELINE-O 新规则已带 TL-6/9/10/11 + QW-T1，原稿没有 → 之后任何补丁（哪怕只改镜 6 一行）都判 I6 变多，被拒；a1–a11 满次（`autoflow_agent.py:1070` PATCH_MAX=10）→ not_importable。和 PLAN §7 第 1 项“I2 和 regen_header 打架”是同一类根因（基线过期 / 新规则追溯），I2 修了、I6 没修。另：`autoflow_agent.py:1006` post_step 的 hard 只放过 I7，而 `hollywood_r5.py:439` 同一闸门放过 I6/I7/W11，两处口径不一致。影响：ep01 过不了导入闸门 → 资产 / 提示词 / 出图全部停在 sop_gate 前；sv-17 发了也出不了图。修法：I6 基线改为当前已采用稿的 lint（或每次同规则重算），并把补丁满次改成自动 report_issue（PLAN §1-1 要求，现在只写 next_action）。

### P1
- **P1-1 · 硬阻断不收稿有一条绕路。** `autoflow_agent.py:877` chain_step 第一个分支按旧 `P4_epNN.md.report.json` 的 `blocking ≤ 6` 收稿进补丁环，没看 `rep.hard_blocks`；`non_tl_blocking` 的 99 只在第二分支 / intake_full_p4 生效。旧 report 里 QW-T1 只算 1 条 block，7 秒镜照样进补丁环（MERGE-VID-O 裁定相反）。
- **P1-2 · L-141 规则不生效（写手拿到两套写法）。** `config/script_chat_rules.md:197`（sysimpl-v2 节）仍写“从第二拍起每拍以 `At 00:SS.mmm,` 开头”，`config/script_chat_rules_appendix.md:125`（QW-A8）仍写“第一个 `At 00:0x` 之前”；`script_chat.timeline_block` 只对 strict 剧追加一段“本段优先”，核心规则本身没改。校验侧（lint RL-T8/T9、p4_adapter TL-、prompt.build_base 失败关闭）已按 L-141；规则文件和校验打架 = 根因模式“规则写了没生效”。
- **P1-3 · 写手包出口 V1 守卫抛错后没人接。** `autoflow_agent.py:105` packet() 里 `assert_no_v1` 抛 HeaderMissing → `autoflow.py:832` 只 advance_log(error) 再 raise，状态文件不变、不登记卡点；resident 每拍再起一次再失败（静默循环）。词表里有“名单 / 验收 / 图纸 / 纹身 / 老公 / 穿孔”这类常用词（`config/v1_guard.json props`），V2 稿一旦正当用到且本剧 P1 没出现过，整条写作线就会这样卡住。守卫“只检查不改写”本身 ✅（redact 已删，`test_header_o.py:200` 有断言）。
- **P1-4 · sop_gate 按镜阶段不排除成人镜。** `tools/master/sop_gate.py:252` `_per_shot` 与 `:275` check_video 用导入稿全部镜号判“出图 / 出图检测 / 尾帧 / 视频”；PLAN §1.2 第 6 条“成人镜头标待项目方触发，不算阻断”。成人镜未出图时整集视频闸门永远不过（视频 / 尾帧是 enforce）。其余判定核过：导入闸门要 gate=ok 且 import=imported（reopened 不过 ✅）；第 N+1 集出图要第 N 集 RETRO done ✅；observe 只记违规 ✅；非仓库根无配置 = 不启用（只影响测试夹具）。
- **P1-5 · 补丁满次没有自动诊断。** `autoflow_agent.py:1070` 只 `st.set(verdict="not_importable", next_action="…交总调度")`，没有 report_issue，没有诊断文件；PLAN §1-1 “补丁满次自动出诊断交总调度”未实现。本次 ep01 满次就是靠人读状态文件才发现。

### P2
- **P2-1 · test_agent_dispatcher 在 cp936 机器失败。** `tests/test_agent_dispatcher.py:21` 假 claude 用 `sys.stdin.read()` 不带 UTF-8，提示词乱码，断言 `"P3_ep02" in stdin` 失败。真实派单器用 `-X utf8` 起启动器、claude.exe 自己按 UTF-8 读 stdin，不受影响；但 sv-17 cut 前测试要绿。
- **P2-2 · test_v2cut_o 读真实快照。** `tests/test_v2cut_o.py` 的 `api` fixture 取真实 `/api/sop/episode/1`，断言“第 1 集造型应有一条待确认”，随真实数据变化而翻转（现在造型已确认 → 失败）。测试耦合真实数据，应改夹具。
- **P2-3 · timeline_check 只在目标全是 TL- 时生效。** `autoflow_agent.py` timeline_check：`len(shots) != len(targets)` 直接放行，TL + 其它项混合的补丁不查“只改时间轴行”。
- **P2-4 · assert_no_v1 每次都 exec 一遍 v1_leak.py 并全量读所有剧。** `script_chat.py` `_v1_leak()` 用 spec_from_file_location 重载；build_system_prompt 每个请求都跑。功能对，开销可观（网页 /chat、每个包）。

### ✅ 核对通过（有出处）
- **L-141 At 只标切镜（校验侧）**：`ns_recipes/lint.py` `in_shot_timecodes` / `cut_issues`（RL-T9：镜内 At 时间码、[Shot N≥2] 缺 At、不递增）、`timeline_alignment`（RL-T8 拍序 ↔ **分拍**）；`p4_adapter.py` 把 SS-M1/M2/M5/M6/M8 + RL-T 合成每镜一条 `[TL-<镜>]`；`prompt.py build_base` 缺时间轴 → NeedsWriter（失败关闭，不静默生成）；`shot_spec.rules_at_least` V2 / 新剧一律 strict、legacy 按旧开关。
- **硬阻断（主路径）**：`validate_qwen_script.py:985/1001` V2_HARD_RULES = QW-T1 / QW-C1，`hard_run` 非 legacy 才升 block；`autoflow_agent.non_tl_blocking` 有 hard_blocks → 99；intake_full_p4 / chain_step 第二分支都用它。
- **V1 守卫只检查不改写**：`v1_leak.redact` 已删（旧文件在 data/_quarantine/header_o_guard_20261103/）；`script_chat.assert_no_v1` 只抛不改；词表集中 `config/v1_guard.json`；三处出口（写手包 `autoflow.py:306`、作业包 `autoflow_agent.py:105`、成稿 `final_v1_hits` + 导入 `import_script.v1_gate`）同一份词表；缺配置 = RuntimeError / HeaderMissing（失败关闭）。`script_header` 非 legacy 剧只读本剧 P1 + 资产清单，没有 P1 → HeaderMissing，不回退 V1。导入稿按剧收口（scope_globals / scope_triggers），V1 导入稿不能当合并底稿。
- **派单器权限白名单**：`agent_dispatcher.build_cmd`：`--restricted --strict-mcp-config --mcp-config {}`、`--tools Read,Write`、`--allowedTools Read Edit(<output>) Edit(<done>)`、`--disallowedTools Bash PowerShell NotebookEdit WebFetch WebSearch Agent Task Read(data/master/**)`、`--permission-mode dontAsk --permission-prompts none --no-session-persistence`；claude.exe --help 确认这些 flag 都存在。写手必须 fable、评审不能等于写手模型（pick_model）；产物路径不在仓库根 = 不派；超时只杀自己起的 pid（创建时间核对）；3 次失败 → report_issue。提示词 `config/prompts/dispatch_writer.md` 明写“不要运行命令，不要联网”。
- **owner_gate**：代选（L-136）不能 redirect、审计记 released_by_delegate 不记项目方放行；只认 approve/revise/redirect（L-123 ✅）；took_over 补记只认 owner_gates 历史里转交之后的 revise。
- **EPCHAIN**：`next_episodes` 第 N 集 imported 且 N+1 无状态文件才开，到 P1 最后一集为止，读不到 = 0（失败关闭）；P1 未过项目方闸门 packet() 拒出包。
- **resident**：每拍异常只记 life.log + 心跳继续；detach 脱离作业对象；派单 / 资产作业 / 好莱坞打分出错只记不退出。
- **真实数据被测试写入**：新测试写盘都在 tmp_path / NSFS_INBOX_DIR；test_header_o / test_timeline_o / test_epchain_o 对真实 run 目录只读。本次复审没有读 data/master/。

### 给总调度（需你定）
1. P0-1 修法二选一：I6 基线换成当前已采用稿（推荐，一行改动 + 测试），还是每轮用现行规则重算 base_lint 并把“新规则追溯”单独列项？
2. P1-4：sop_gate 的成人镜怎么标（读导入稿 shot.adult 字段排除，还是按 producer 的 owner_trigger_ids）？

---

## REVIEW-B sv-17 · 11-03 03:5x · 编译 / 出图闸门 / 资产 / 代选（sv-16 之后未提交改动，L-153 复审）

**结论：可以进 sv-17。** 本批无 P0；3 条 P1 不阻断发版（1 条随发版自然收口，2 条分别归写作侧 / 运维核实）。只读审查：自己读 diff、自己跑测试、自己在沙盒（`NS_DERIVED_ROOT`）下编译 ep01 S1 / S2 / S8；未改代码、未重启、未读 data/master/。

### 实跑
- 范围内测试：`test_merge_img_o / test_asset_pipeline / test_owner_pick / test_owner_delegate / test_golden_v2_checks / test_owner_inbox` → **110 passed, 1 skipped**（skip = `test_sheet_spec_shoe_from_p1_schedule`，夹具 zh_look 只有 4 段，非代码问题）。相邻闸门测试 `test_vqagate / test_promptfix_v2 / test_director / test_hollywood_tick / test_derived_out / test_manifest_look_shoes / test_adult_nude_context / test_owner_gate / test_sop_gate` → **220 passed**。real-data-guard：写真实数据 **0 次**。
- 真编译（NS_RUN=series10_v2，派生图沙盒）：S8 近景 / S1 三人中景 / S2 双人中景，结果见下。

### 逐项核实（依据 OWNER_CANON C-04 / C-16 / C-22、PLAN v4 1-0～1-5、CARRYOVER P0 1/2/3）
| 项 | 结论 | 证据 |
|---|---|---|
| 近景服装送进去 | ✅ | S8 提示词含“祁念穿黑色漆皮抹胸紧身短裙”+“高亮镜面漆皮”材质句，refs 含 `outfits/outfit_daily_patent_tube_dress.png`；`framing.py:103-152 visible_items/visible_garment`、`asset_refs.py:175-178 zone_of 全身装→body`、`frame_job.py:123-128` |
| 三人镜每人送脸 | ✅ | S1 一块脸板 3 格各标 character（`asset_refs.py:1902 members.character`），`trace.faces=['ch_zhuo_lin','lead_f','ch_tang_yao']`（`frame_job.py:364-375 face_ids`），preflight I2 pass、I9 不再判“同槽两张脸”（`preflight.py:234-238,249-258,278-280`） |
| 硬负面词永在 | ✅ | `compiler.py:469-475 _negative` 强插 MINOR_GUARD；`frame_job.py:349-361 job_negative` 再兜底；三镜 job.negative 均含“未成年人外观”。Base/定稿档写回编码器 `unified_frame.py:41-47`；Turbo cfg=1 负面不参与采样是模型限制（workflows.negative_for），作业记录照样带 |
| L-145 / L-148 后缀 | ✅ | `render_quality.json:606,777` 两段 style_suffix 含 Leica / ARRI / Kodak，已删“日落暖阳 / 机顶直闪 / 白平衡偏冷”等灯光时间词；`run_style.json:154` 英文 Leica 移出 V1 泄漏名单、中文“徕卡”仍挡 |
| L-149 镜头句 / 融合句 | ✅ | `run_style.json:139 shot_language lens=auto, fusion=true, lighting=script`；S8 实出“镜头：50mm 镜头，光圈 f/1.4，浅景深…”+ L-110 融合句（`shot_language.py:103-137`，顺序由 `shot_spec_v2.yaml:165-170`） |
| L-147 定稿档 | **当前关闭** | `render_quality.json:320-321 auto_final_on_lock=false, auto_final_on_lock_runs.series10_v2=false`（总调度 11-03 裁定：共用验收并回前先关）；`final_tier.py:39-51` 按剧覆盖已实现。与项目方 L-147 点选“开”不同，🟢 需告知项目方 |
| L-139 代选条件 | ✅ | `asset_jobs.py:575-600 delegate_active`；`asset_worker.py:317,723,831` 设定图 / 单品裁图只在代选开着时自动登记，否则投 #/queue。实证：03:48:51 项目方点选后 03:49:36 代选自动关闭（`owner_delegate.json expiry.expired_kind=owner_decision`，`delegate_log.jsonl`） |
| 代选不越界 | ✅ | `owner_delegate.py:191-207 never_reason`：非 pick / 删除花钱推翻 / adult / route=local_only / 候选或人物带成人 / 文字含成人词一律跳过；`:46 PICK_KINDS` 白名单；redirect 禁止（`owner_gate.py:174-175`）。代选开着的 72 分钟里 **0 条代选**（delegate_log 只有 enabled / closed） |
| 审计不冒充 | ✅ | by=“总调度代选” via=delegate:L-136（`owner_delegate.py:44-45,367-392`）；写作闸门 `released_by_owner=False, released_by_delegate=True`（`owner_gate.py:201-203`）；decisions.jsonl 现有记录 by 只有 fred / owner / 总调度（代录） |
| asset_refs.json looks_file | 未改坏 | `git diff HEAD -- config/recipes/asset_refs.json` 内容为空（M 仅换行符）；V2 块与 HEAD 逐字一致 |
| 测试写真实数据 | ✅ 0 次 | conftest `_SANDBOX_ROOTS` 新增 `ns_agent.asset_refs.DERIVED_OUT`（`tests/conftest.py:187`），`test_owner_* / test_asset_pipeline` 全部 tmp_path |

### P1（不阻断 sv-17）
- **P1-1 · DELEGATE · `services/api/ns_api/owner_delegate.py:641`**：后台线程每拍 `importlib.reload(sys.modules[__name__])`，:8800 正式实例每 60 s 把工作树里的本文件热加载——未复审 / 未发版的代码直接上线，绕过 system_version。sv-17 发版后读到的就是已发版代码，风险随发版收口；但机制本身违反“复审后才上线”，建议下轮改成只在 deploy 后重启时加载。
- **P1-2 · 写作侧 / L-130 · `frame_job.py:380-384`**：ep01 导入稿 11 镜没有任何【幻想段】/【现实段】标记，三镜编译全部 `style_warning="按缺省 reality 段出"`。若 ep01 有幻想段，会按现实段调色。应并进 L-150 整集返修包（写手补标记），或总调度明确 ep01 全现实段。
- **P1-3 · 资料齐全才出（C-16）· `preflight.py:212-231,259-269`**：I3 新口径下 S1 / S2 / S8 全部 `I3 fail：祁念 造型O4 没有设定图`——这是规则正确生效，不是 bug；但意味着 sv-17 后 ep01 一镜都出不了，直到 `asset_jobs/series10_v2/sheet-lead_f-O4` 作业完成并选定（PLAN 1-2）。发版后第一件事应是看这条作业状态。

### P2
- `asset_refs.py:1826 _line(item)`：近景里单品槽文字仍写全标签“…短裙 + 黑色薄透丝袜 + 透明尖头细高跟，必须与图2完全一致”，与 K-REN-707“近景不提看不见的下身”只在 outer_items_note 一侧落实（测试 `test_v2_s8…` 断言刻意避开了这一句）。
- `frame_job.py outer_items_note`：S1 / S2 对祁念写“造型设定图上有，正文没写也必须入画”，而祁念 O4 并无设定图，措辞失实；同时 S1 三槽上限把祁念 outfit 参考挤成“按文字描述（参考槽不足）”，三人镜女主服装一致性靠文字。
- `config/recipes/asset_refs.json:66`：V2 `looks_file=data/pipeline/runs/series10_v2/assets/P1_looks.json` 不存在（真实文件在 run_dir 根），`load_looks` 靠 `manifest_looks` 兜底；HEAD 已如此，非本批引入。
- `owner_pick.py:448 replay`：只排除 via 以 owner_pick 开头的记录，`via=look_confirm`（画布确认）被当旧决定补执行一次（decisions.jsonl 01:56 / 02:23 同一 pick:look 两条）。
- `config/gen_contract.json:155`：Q10 `count_host` 由 ""（本机）改为 `http://10.0.0.36:8893`（gpu36 内网入口，vqa.json 同口径只认 10.0.0.33）。服务器侧可达；笔记本侧（golden_v2 evaluate / asset_worker 候选检查）若走到 Q10 会 untested 挡——需运维核实或按主机分流。
- `config/compile/run_style.json:139`：`shot_language._doc` 仍写“镜头句与融合句暂关，等总调度定”，与同一行 `_l149` 和实际值矛盾，读配置的人会误解。
- `tools/promptfix/golden_v2.py:103-105`：`load_imported` 只收 cast=={"祁念"} 的单人镜，多人镜 SystemExit；PLAN 1-4 换 build_first + preflight 探针后应退役此脚本的 --render。
- 审查期间（03:48–03:49）`data/pipeline/runs/series10_v2/images/refcrops/` 新增 2 张 nohead 裁图：归因为项目方 fred 03:48:48 在 #/queue 选定卓琳 A 设定图后 asset_worker 的正常派生，不是本审查写入（本审查派生根 `NS_DERIVED_ROOT` 沙盒为空）。

### 历史备注（不计入本批）
- `assets_v2/manifest.json` 里 ch_tang_yao / ch_jiang_yubai 的 `A_shoes1` 由“系统自动”登记于 02:19 / 02:34，早于 L-139（03:1x）与代选开启（02:37）；现行代码已按 L-139 门控。

---

## REVIEW-C sv-17 · 11-03 03:5x · sv-16（1d2cc20）之后未提交的"视频 / 运维 / 重启 / UI"批次复审（L-153：先复审 → sv-17 → 出图）

**结论：可以进 sv-17。** 无 P0；3 条 P1 都不是本批引入的回归或已有上游硬拦，列为 sv-17 之后第一轮必修。只读复审，未改代码、未重启、未读 data/master/。

### 实跑（自己跑，不采信 agent 报告）
- `pytest tests/test_merge_vid_o.py test_merge_ops_o.py test_restart_api_ps1.py test_api_instance.py test_sv_verify_lock.py test_system_version.py test_video10_resilience.py test_sentinel.py test_factory.py test_bgm.py test_merge_img_o.py`：**287 passed, 1 skipped**，520 s（含真跑 pwsh + uvicorn）。
- `apps/web`：`npx tsc -b --noEmit` 退出码 0。
- `tools/qa/decision_check.py`：87 项 ✅86 ❌0 ⏳1（D-V2-02 等 V2 导入完成，合理待开）；决策全量同步 12 条全 ✅。

### 九个核实点（文件:行）
| 点 | 结论 | 证据 |
|---|---|---|
| 视频前先过 Q9 | ✅ | `build_jobs.py:149-159` `_q9_ok` / `_q9_ok_file` 看图模块载不进 → False（原来放行）；`config/vqa.json:260/265 enforce=true`；`tools/master/sop_gate.py:228/268` “出图检测”= postflight ok + Q9 pass + 非 master_reject，`config/pipeline/sop_gate.json` observe 只含 资产就绪/提示词/出图，“视频”enforce；`night.py:171` 派单前第二道 `video_dispatch_ok` |
| 单镜 ≤6 s 硬阻断 | ✅ 写作/导入层；⚠ 视频层无复核（P1-1） | `tools/validate_qwen_script.py:983-1015` QW-T1 按镜 block + hard_blocks；`autoflow_agent.py:849-854` hard_blocks → 99 不收稿；已收集走 `duration_patch`（:1578）。但 `build_jobs.py` / `ns_recipes/compiler.py:288-290` 只有 H3 帧上限（recipe frames.max），没有 6 s 复核 |
| 视频端 run 参数 | ✅ | `deploy.py:141-144` `NS_RUN={run} … vidgen.py run {host} --run {run}`；`night.py:36` 设 NS_RUN、`run():76` 子进程继承；`night.py:364` proxies 带 --run；`vidgen.py:714-717` 没给剧 return 2；`run_ctx.resolve` 未登记 / 不在 scope_runs → VideoRunError |
| 重启只停自己记下的 pid + detach | ✅（P2-1 见下） | `ops/restart_api.ps1:252-267` 先 `api_<Port>.pid.json`（pid+创建时间）；`:98-107` Stop-Tree 按创建时间收树、不用 taskkill /T；`:335-340` 经 `api_watchdog.py --detach`（`api_watchdog.py:471-500` DETACHED_PROCESS+NEW_PROCESS_GROUP+BREAKAWAY，close_fds，pid 走文件）；`ops/restart_autoflow.ps1:10-18` 只停锁里 pid、`autoflow_resident.py --detach` |
| 非正式实例不跑副作用 | ✅ | `ns_api/instance.py:why_not`（pytest / NS_API_PREFLIGHT / NS_API_MANAGED≠1 / 单实例锁）；`app.py:98-113 / 209-222 / 2102` JOBS.restore、EPROD/PJ.resume、loop watchdog 全受门；`frame_jobs.py:561-564`、`owner_pick.py:497-500` 各自再查；`api_watchdog.py:33` 设 NS_API_MANAGED=1，`laptop_autostart.ps1:33` 经看门狗 |
| 发版 verify 必须带镜号 | ✅ | `system_version.py:1247-1252` 无 shot → 写 ok=False 不碰服务器；`deploy():1115-1119` 自动 verify；`main():1326` verify 不过退出 1；`--no-verify` 只给回退 |
| decision_check 通过 | ✅ | 见上 |
| UI 无静默删功能 / 无技术词 | ✅ 功能；⚠ 技术词（P2-2） | 总览移到品牌 + 工具菜单（`TopBarV3.tsx:62/445`），声音 / 反馈开关进工具菜单（:53 / :511），`#/assets` 回资产中心、`?type=pack` 保留资产包清单（`App.tsx:38-39`）；`ImageEditPage.tsx` 删“等价命令行”、两个 disabled 按钮保留改文案、加 Verdict |
| 只有“用这张”和“修改” | ✅ 本批新增；⚠ 既有三按钮（P1-3） | `OwnerQueuePage.tsx` PickCards 只有“用这个 / 修改”；`OwnerDecision.tsx` 删 cli；但 `owner_queue.py:277` DECIDE_OPTS = 同意 / 不同意 / 稍后、`:325` 抽检同样三项（HEAD 已有） |

### 问题
**P1-1 · 视频层没有 ≤6 s 复核** — `tools/series10_video/build_jobs.py:448`（只写 seconds）、`services/recipes/ns_recipes/compiler.py:288-290`。L-137 前导入的 V2 集或 legacy 路径一旦有 >6 s 镜，视频链会照编。建议 build_all 对非 legacy 剧 `duration_s > 6` 的镜记 not_ready（和 Q9 同一口径），一行代码 + 一条测试。
**P1-2 · SENTINEL 对 V2 producer 仍是盲区（半成品）** — `tools/sentinel/remote_probe.py:23-26` 新增第 7 个参数 PDIRS（各剧 producer 目录），但 `tools/sentinel/probes.py:115` 只传 6 个参数，且 probes.py 没有任何地方读 `out["runs"]`。S2/S3/S7/S13 还是只看 `data/producer`（V1），V2_SYSTEM_LOSS_AUDIT 1.7 并未真正修复。
**P1-3 · #/queue 拍板 / 抽检卡仍是“同意 / 不同意 / 稍后”三按钮** — `services/api/ns_api/owner_queue.py:277、:325`，前端 `OwnerQueuePage.tsx:165` 原样渲染。违 L-123 / C-09（只有“用这张”+“修改”）。非本批引入，但 L-153 之后项目方要进 #/queue 拍板，建议并入下一轮。
**P2-1 · restart_api.ps1 兼容路径仍按命令行认旧进程** — `ops/restart_api.ps1:253-267`：pid.json 缺失或对不上 → 按 `uvicorn ns_api.app:app --port 8800` 命令行匹配（注释说只给旧版脚本起的）。pid.json 过期（进程没了）时也会走到这里。建议再发一版后删掉 claim 路径。
**P2-2 · 界面技术词** — `OwnerQueuePage.tsx:71/147`“（L-136）”；`NavTabs.helpers.ts:105`“进度接口还没生效（后台重启后出现）”；`CutEditor.tsx:23`“成片接口还没生效，后台重启后出现”；`ImageEditPage.tsx:62`“出图模型列表还没读到（后台重启后出现）”。都是本批新写的，改成“正在准备，稍后自动出现”。
**P2-3 · night.write_status 写死 10 集** — `tools/series10_video/night.py:469` `range(1, 11)`，V2 集数不同会错报。
**P2-4 · 单行 `__import__("tools.master.sop_gate")` 导入** — `build_jobs.py:476`、`night.py:171`、`vidgen.py:718`（带 `# noqa: E701`）。功能对，但三处复制同一句、可读性差；放进 run_ctx 一个 `sop_gate()` 助手。
**P2-5 · video_policy.scope_runs 与 runs.json 两处登记** — `config/pipeline/video_policy.json:17-21` 新剧要同时登记两处才出视频（失败关闭方向，设计如此），SOP 第 8 步要写明。

### 对照 OWNER_CANON / PLAN v4
- C-16 先图后视频：sop_gate“视频”阶段要求本集每镜出图检测 + 尾帧全过 ✅。C-09 两操作：本批 ✅、既有三按钮 ✗（P1-3）。C-14 V2 不退回 V1：`build_jobs.alt_crops / crops / NAME2ID` 非 legacy 一律空 ✅；`bgm` V2 只走 `music_v2.json` 曲库 ✅。C-25 每轮发版 + verify 带镜号 ✅。PLAN v4 §3 第 8 步“Q9 已过才放行；≤6 s”：前者两道都在，后者只在写作层（P1-1）。

## 第 17 轮（OVERSIGHT-F2）· 11-03 00:1x · RESTARTFIX-S 对第 16 轮 P1-1 / P1-2 / P2-1～P2-4 的修复

**结论：不可以打开自动重启（data/ops/api_guard_auto.json 继续不存在）。** 第 16 轮列的 6 条都按说明修了、测试 3 遍全过、锁不会误接管、预检实例的三个启动任务确实没挂；但审计期间（00:09–00:12）总调度手动跑新版 ps1 又一次走进 `port_busy`（exit 2，API 不在 3.5 分钟），而守护补起在这种“端口残留”情形下大概率会以 `port_foreign` 退出、什么都不做——这是本机今晚 3 次杀旧后 2 次复现的主故障，修复没有覆盖它。补完下面 P1-1 再审一轮才可开。

### 实跑（3 遍）
- `test_restart_api_ps1.py`：9 passed ×3（112 s / 113 s / 94 s，真跑 pwsh + uvicorn）；`test_r43_uirsi.py`：33 passed ×3；`test_factory.py`：63 passed ×3。**0 失败、0 skipped、无偶发**；real-data-guard 写真实数据 0。
- 现场：开关文件不存在；`data/ops/` 下无 `api_restart.lock`、无 `api_preflight.pid`（两次手动 ps1 退出后都清干净了）；:8801 无监听；:8800 `/api/season` 200（00:12:59 经看门狗起，pid 28116）。
- `exit` 在 try/finally 里会触发 finally：用脚本实测（函数内 `exit 4` → “finally ran”，rc=4）——Fail-Restart / Skip-Healthy / busy exit 1 都会释放锁、清预检。

### 1）还有没有“旧杀新没起”/“杀掉健康 API”
| 路径 | 结论 | 证据 |
|---|---|---|
| exit 4（preflight / preflight_port / port_foreign）| ✅ 停旧之前返回，old_kept=true | ps1:138、154、165–167 都在 170 Stop-Process 之前 |
| -Revive 杀健康 API | ✅ 不会 | ps1:125（拿锁后）与 :168（停旧前一瞬）两次 `Api-Healthy`，200 即 exit 0 写 restart_skipped/already_healthy；测试 `test_revive_already_healthy_never_kills_api`、`..._started_by_someone_during_preflight_is_not_killed` 覆盖。残余窗口：别人起的实例在 :168 探针时还没起完（启动 ~3–10 s，按 lifecycle 22:02:52→55）会被当旧进程杀，但 ps1 随后起自己的一份，API 仍会在——P2 |
| exit 3（not_up，180 s）| ⚠ 可接受 | 旧已杀、新进程慢；ps1 不收拾它；下一拍补起 -Revive 先测健康，慢实例起好了就 exit 0。超 ~5 分钟才起的实例会被补起杀掉重来一次（补起 30 分钟只一次） |
| **exit 2（port_busy）→ 补起** | **⚠ P1** | 实证：00:09 总调度手动 ps1 停旧后 `8800 端口 90 秒仍被占用（进程 0,0）` → exit 2、A-API-RESTART-FAIL crit（00:11:08）、守护 00:11:20 记 A-API-DOWN；00:12:40 再跑一次才起来（up 00:12:59）。21:56 那次同样。**若开关打开**，补起会在 00:11:20–00:12:20 之间进 ps1：预检 ~5–10 s 后到 :159–167——`$olds` 空、`$owners`（PID 0 被 `-ne 0` 滤掉）空、`$claim` 空、`Listening` 仍真 → **`port_foreign` exit 4（old_kept=true）**，不等端口、不起新，补起额度（revive_attempt）已消耗，API 继续不在直到人工。端口残留实测 90 s < 残留 < ~3 min（00:09:38 杀 → 00:12:53 已空），补起撞上残留的概率很高。即：修复把“补起多次”改成“补起一次”，但补起在本机最常见的故障形态下不起作用 |
| ps1 被守护 450 s 超时杀（只杀 pwsh）| P2 | 预检残留靠 pid 文件下次清 ✅（ps1:117–124，测试覆盖）；但若在 :170 之后被杀：无 restart_failed → outcome=unfinished → 只 crit 告警，`revive_check` 的 last_fail 不是 old_kept=false → 不补起。最长路径 ≈ 2+10+60+30+90+180 ≈ 372 s < 450，正常够用 |
| 守护两条线叠拍 | ✅ | resident_sync `autoflow_thread` 同线程串行（:935–951），api 线子进程超时 600 s taskkill /T；两个 ps1 同时只会 exit 5 |

### 2）锁接管会不会误接管正在进行的重启
- 接管条件（ps1:62–73）：持有 pid 不存在，或锁文件 LastWriteTime 超 20 分钟。一次重启最长 ≈ 372 s，守护 450 s 必杀；20 分钟不可能碰到活着的重启 ✅。pid 用 `Get-Process -Id`，跨会话 / 提权进程也能看到（只会把别人判“活”，不会判“死”）✅。锁内容读不出且 < 5 s 当占用 ✅；CreateNew + FileShare.Read 期间文件删不掉 ✅。
- P2：两个进程同时发现残留锁 → 都 Remove-Item → A 先 CreateNew 成功、B 的 Remove-Item 把 A 的锁删掉再创建 → 两把锁并行（毫秒级窗口，且须先有残留锁）。
- P2：pid 复用（死持有者的 pid 被别的进程占）→ 最多白等 20 分钟（失败关闭方向，不危险）。
- P2：补起先写 revive_attempt 再跑 ps1（guard:343）；ps1 若 exit 5（撞上手动重启）或 unfinished，补起额度也被消耗；30 分钟内不再补。

### 3）预检实例（NS_API_PREFLIGHT=1）是否不改真实数据
- ✅ `app.py:98–100 / 194–195 / 206–207`：`JOBS.restore`、`EPROD.resume_on_startup` 不挂、`PJ.resume_on_startup()` 不跑；`owner_pick._replay_on_startup`（:338–343）也按同口径跳过；`_lifecycle_should_log` 不记。测试 `test_app_preflight_skips_startup_tasks`（子进程真导入 app）+ `test_p2_lifecycle_not_written_by_tests_or_preflight`。ps1:139–144 只给子进程设环境变量并随后清掉 ✅。
- ⚠ P2 **还有一条没挡**：`frame_jobs.py:558–566 _start_postflight_sweeper()` 导入即起（只认 `pytest` 或 `NS_POSTFLIGHT_SWEEP=0`，不认 NS_API_PREFLIGHT），20 s 后 `unified_frame.sweep_once` → `run_postflight` 对所有 pending 的 take 真算契约、`_pf_write` 写真实 `takes.json`、`AC.on_contract` 改“当前版本”（:343–363），与真 API 的扫描线程并发。热启动预检 ~5 s 内被杀、通常赶不上 20 s；冷启动（代码刚改、pyc 重编）有可能赶上。一行修：`_start_postflight_sweeper` 加 `NS_API_PREFLIGHT` 判断，或 ps1 预检环境再设 `NS_POSTFLIGHT_SWEEP=0`、`NS_NO_API_SNAPSHOT=1`。
- P2（轻）：预检实例的 `loop_watchdog` 往 `data/qa/loop_lag.jsonl` 追加 beat/stall；`_warm_episodes_bytes` 写摘要快照（原子替换，内容同真 API）；都是噪声不是损坏。
- 观察（与本修复无关、第 12 轮 P2 仍开）：`api_lifecycle.jsonl` 00:01:10/00:01:19、00:07:52/00:08:49 各一对 api_startup/api_shutdown（pid 47444、53276，不是 :8800），是某个进程内起的真数据目录 app 实例写进生产留痕。

### 4）P2-3 / P2-4
- lanes release 不带 --by 且道上有 hold → CLI 打印“没有清理任何 hold，请加 --by”（lanes.py:325–330），测试 `test_restartfix_lanes_cli_release_without_by_warns` ✅；`hold` 默认 by 改为 `--by` / `NS_AGENT` / “unknown（没写 --by）”（:323）✅。
- UpWaitS 180、PS1_TIMEOUT_S 450、flow 超时 480 ✅（guard:228 的算式 ≈370 s 正确）。

### 分级
P0：无（开关关着，守护不动任何进程；两次手动 ps1 锁 / pid 文件都清干净）。
P1
1. **补起撞端口残留**：`-Revive` 下 `$olds` 为空、看不到属主、端口仍在听 → 应按“残留”等 FreeWaitS（而不是 port_foreign 立即退出）；同时 FreeWaitS 90 → ≥240（实测残留可到 ~3 min）；并查残留根因——停旧改成 `taskkill /PID <看门狗 pid> /T /F` 杀整棵树（API 起的 ssh / ffmpeg 等子进程可能继承了监听句柄，Stop-Process 只杀 4 个 python），杀完立刻看 netstat 是否还有 PID 0 的 8800。做完用“真杀 :8800 旧实例”的方式验一次（总调度亲自跑，非测试端口），再审。
P2
1. 预检实例 postflight 扫描线程未挡（见 3）。
2. 残留锁双接管的毫秒级竞争；pid 复用白等 20 分钟。
3. 补起额度在 exit 5 / unfinished 时也被消耗。
4. ps1 在 :170 之后被 450 s 超时杀 → 无 restart_failed、不补起（只 crit 告警）。
5. 停旧前一瞬的 ~3–10 s 启动窗口里别人刚起的实例会被当旧进程杀（随后 ps1 自己起一份，API 仍在）。
6. 非 -Revive 的常规重启杀所有命令行含 `uvicorn ns_api.app:app` 的 python（含别的端口的开发实例）；`uvicorn.exe` 方式起的实例不被识别（只会 port_foreign 保旧，安全）。
7. 直接 `uvicorn` 手起不更新 `api_restart.json`，守护开关打开后 covered_filter 不认，积压请求会再白杀一次（第 16 轮已记）。

---

## 第 16 轮（OVERSIGHT-S 代审）· 11-02 · FACTORY 的 API 自动重启修复（K-OPS-F34 / F35）

**结论：不可以打开自动重启（data/ops/api_guard_auto.json 继续保持不存在）。** 脚本本身（先验后停、预检失败保旧进程）是对的；但"补起一次"有两处会让 API 再挂，补完 P1-1 / P1-2 再审一轮才可开。

### 实跑
- `test_restart_api_ps1.py`：3 passed（真跑 pwsh，约 58 s）；`test_r43_uirsi.py`：30 passed；lanes 相关（-k lane/release/hold/lend）31 passed。全部 **0 skipped、0 失败**，real-data-guard 0。只各跑 1 遍，没做重复压测，偶发性未证实。
- data/ops/ 下确认没有 api_guard_auto.json；:8801 当前无监听。lanes.py 实际在 tools/debug/lanes.py（不在 tools/factory/）。

### 逐条
1）旧杀新没起（exit 2 / 3 / 4）
- exit 4（preflight / preflight_port / port_foreign）：都在 Stop-Process 之前返回，old_kept=true，旧进程保留。✅（测试覆盖前两种 + 端口被占）
- exit 2（port_busy）：旧的已杀、端口 90 s 仍被占 → API 不在。**路径仍存在**，只是多了等待、告警（crit）、守护补起；开关关着时只能等人。
- exit 3（not_up）：旧的已杀、新的 90 s 没 200 → API 不在，同上。新进程可能只是慢（预检给了 60 s，正式只给 90 s），脚本不去收拾它。
- 所以"旧杀新没起"没有被消除，是被"告警 + 补起"兜住；而补起本身有 P1-1 / P1-2。

2）8801 预检
- 成功 / 失败都会 `taskkill /T /F` 预检进程树并等端口空（最多 30 s），失败有清理。✅
- 但没有 try/finally：脚本在预检起来后被杀（守护 330 s 超时只杀 pwsh、不杀树；或手动 Ctrl-C）→ 8801 残留；之后每次都是 `preflight_port` exit 4，旧进程保留，**不会弄挂 API，但自动重启永久失效且无人清理**（只有 warn 告警）。P2-1。
- 预检实例会跑完整 startup（JOBS.restore、EPROD.resume_on_startup、PJ.resume_on_startup 等），只有生命周期留痕被 NS_API_PREFLIGHT 屏蔽。它与真 API 同时在线约几十秒，若 resume_on_startup 会重派任务，可能与真 API 各派一次——没有实测，P2-2（请 FACTORY 确认 resume 是否只读/幂等）。

3）补起 vs 项目方手动启动
- **P1-1 补起不止一次**：revive_check 只看"最后一条事件"。补起会先写 revive_attempt，但补起脚本自己失败（port_busy / not_up，old_kept=false）又会写一条 restart_failed，成为"最后一条"，30 分钟内再次满足条件 → 每拍（60 s）再补起，最多循环 30 分钟，每轮一次预检 + 90 s 等端口。测试只验了"revive_attempt 紧跟 failed"，没验"补起后又失败"。docstring 与测试名都说"补一次"，实际不是。
- **P1-2 与手动启动撞车**：守护发现 API 不在 → 起 ps1（-Force）。ps1 预检要最长 60 s，期间项目方若手动起了 8800（命令行含 `uvicorn ns_api.app:app`），ps1 第 2 步会把它当"旧进程"在 `$olds` 里一并 Stop-Process，等于杀掉刚起好的健康 API；端口占用判断（foreign）也认它为"自己人"。守护 / ps1 都没有互斥锁（锁文件、互斥量均无），tick 本身也没有防重入（flow.api_restart_tick 超时 360 s，tick_parts 是否会叠拍未核实）；两个 ps1 同时跑时第二个只会在 8801 上 exit 4，但补起与手动起之间无保护。
- 缓解：补起要求开关打开 + 30 分钟内 + old_kept=false，且 api_up 连测两次失败（3 s 间隔）；项目方手动起时多半 30 秒内就好，但 ps1 冷启动时窗口长（预检 + 等端口最多 ~2 分钟），撞车概率不低。

4）开关
- AUTO_SWITCH 不存在 / 内容坏 / enabled 不是 `true`（严格 `is True`）→ auto_enabled()=False。tick 的执行路径与 revive_check 的补起路径都在调 run_restart_ps1 之前判开关，且 `--dry` 先于开关返回。✅ 测试 `test_guard_stop_bleed_switch_off_never_runs_restart` + `api_down...revives_once` 的 r3 覆盖。
- 注意：开关只管守护。人 / 别的 agent 直接跑 `ops/restart_api.ps1` 不受影响（本来就是手动入口，符合预期，但"今晚三次"里哪些是手动的由 restart_events 的 parent_chain 为准）。

5）lanes.release / lend / hold
- release：by 给了才清 by / to / client_prefix 等于 by 的那条；不给 by 只清借道（不碰 hold）；kind 可限类；两类都空了才从 retired_lanes 拿掉；无匹配记 release_noop。✅ lend 在有效 hold 上拒绝；hold 带 by 进审计。test_factory 里有 PROMPTFIX / STYLE-V2 场景。
- P2-3：by 与 hold 的 `by` 默认值是 "DEBUG-RSI"，调用方不传 by 的 hold 会被当作 DEBUG-RSI 的，别人用 by="DEBUG-RSI" 就能放；release 不给 by 时拒绝清 hold 但 CLI 不提示，容易误以为放掉了（只在审计里是 noop）。

6）测试：见"实跑"。test_restart_api_ps1 依赖 pwsh + 真起 uvicorn 子进程，约 1 分钟，CI 无 pwsh 时整文件 skip（本机未 skip）。arch_scan 上轮记的 no_timeout 1（该测试 subprocess.run 的 timeout 已有，Popen/wait 部分未细看）。

### 分级
P0：无（开关关着时，守护不会杀任何进程）。**但打开开关后 P1-1 / P1-2 都可能让 API 不在。**
P1
1. 补起可重复（见 3 / P1-1）。建议：补起前写 revive_attempt 之后，只要 30 分钟窗口内出现过任何 revive_attempt 就不再补（不看"最后一条"），或把补起次数计数落盘。
2. 补起 / 重启与手动启动无互斥，且 ps1 会杀"新起的健康 API"。建议：ps1 加互斥（文件锁 data/ops/restart.lock，守护与手动同一把）；第 2 步前再测一次 `/api/season`，若 API 已经是健康的 Force 补起则直接退出 0（"已有人起了"）。
P2
1. 8801 无 try/finally，被杀会残留并让自动重启永久失效；建议开头清理自己遗留的 8801。
2. 预检实例跑完整 startup（resume_on_startup 等）是否会和真 API 重复派任务未验证。
3. lanes 默认 by 与 release 无 by 对 hold 的静默 noop。
4. exit 3 的 90 s 对冷启动偏紧，慢启动会被判失败后又被补起杀掉重来。
5. 偶发性：每个测试文件只跑 1 遍。

---

## 第 14 轮 · 11-02 22:45 快照 · STYLE-V2 P1-13a 接线（run_media）；HOLLYWOOD 派人请求共用写入 / camera-patch / 测试隔离

### 实跑
- `pytest test_v2_media / test_owner_gate / test_judge_agent / test_distill_flow / test_bgm / test_cutedit_api / test_cutedit_export`：**138 passed / 0 skipped**，real-data-guard 0。
- `arch_scan --check`：5 处——owner_inbox.py、run_media.py、parallax_bt.py 未入版；`tests/test_restart_api_ps1.py` no_timeout 1；`tools/uirsi/api_restart_guard.py` silent_read 2（FACTORY 正在做的 API 重启那批，下轮一起看）。

### 1）STYLE-V2 P1-13a
| 项 | 结论 | 证据 |
|---|---|---|
| run_media.py | ✅ | `services/post/ns_post/run_media.py`：资产包模式剧 → 配乐只认 `config/music_v2.json`（run 必须一致、逐条 sha256、曲目为空报错；:57-72），集级目录 `data/music/<run>/`（解析到 V1 目录直接抛；:75-83），`check_episode_music` 要求 epNN.json 的 library_track / library_sha256 与曲库一致、剪辑换曲文件必须在曲库或本剧目录（:86-105）；音色只认 `voices_v2.json` selected+enabled 各 1、ref.wav sha 校验（:109-146），技术段沿用 voices.json 的 tts_model / asr_model / speech_python / remote_tts 四个键，不含任何 V1 角色。失败 = V2MediaError，不退 V1 |
| 接线 | ✅ 四处 | `assemble_series.py:180-183` `load_voice_config(run=run)` + `RM.music_dir(run)`；`cut_export.py:134-139` 同 + `check_episode_music`；`bgm_api.music_dir:31-42` 按 `RP.current_run()`（V2 走 run_media，legacy 才 series10）；`shot_audio.py:67` `load_voice_config(run=RP.current_run())`、`_music_dir → music_dir()`；`tts.load_voice_config(run=…)` :56-62 |
| **还有没有别的入口读 V1（V2 下）** | ⚠ P2 ×5 | ① `tts.py:514` `RoutedTts(backend, load_voice_config())`——旁白克隆改走远程时**不带 run**，拿的是 V1 voices.json 角色表（只有当传进来的 backend 不是 RoutedTts 时触发；assemble_series 已传 RoutedTts，shot_audio 的预览走 Kokoro 不触发；但口子在）。② `tts.py:91` `voiceover_speaker()` cfg 为 None 时读 V1，且注释"退回 lin_wan"。③ `tts.py:449` 同类兜底。④ `assemble.py:1080` `voices_cfg or load_voice_config()` 兜底 V1（compose / cut_export 都传了 cfg，别的调用方不传就漏）。⑤ `shot_audio.py:160` 预览 Kokoro 后端用 `tts.load_voice_config()`（V1 表）取 Kokoro 音色 — 同一函数 :67 已按 run 取了一份，两份混用。另：`bgm_api.py:50/63` 候选 / 选曲仍写死 `data/music/series10/epNN/{meta.json,cands}`（V1 BGM 候选列表），V2 下 /api/music 的候选和"换用这一条"会落到 V1 目录；asset_center_p1 `/api/voices`、character_hub:509、asset_revs 指纹读 voices.json（V1 角色展示 / 指纹，非合成路径）。建议：`load_voice_config()` 不带 run 时在资产包模式下直接报错（和 run_style 一样失败关闭），一次把 5 个兜底堵死；bgm_api 候选目录按 `music_dir()` 取 |
| deliver.py 偏差最小 | ✅ / P2 | `tools/bgm/deliver.py:92-118`：5 次重做记 (|偏差|, 增益, 报告)，取最小；最后写出的不是最好那次就按最好增益重写 dst；`redo.kept_gain_db`。P2：第 1 遍（不限幅）没进候选——它若比所有重做都近会被丢；重写一遍 loudnorm 结果与记录的报告非严格同一文件；test_bgm 仍无 redo 分支用例 |
| tools/assemble_episode.py 要不要改 | 建议：**改成按剧取，或明确标死 V1 专用并加守卫** | 它是 T38 的手动装配（`:109 load_voice_config()` 读 V1 voices.json，BGM 读 `data/music/epXX`，输出 data/episodes/epXX_final.mp4），和 assemble_series 是两套合成入口（根因模式 1）。最省的做法：开头加 `runs.current_run()` 判断——资产包模式的剧直接拒绝并提示用 `assemble_series.py`；或和 compose 一样接 run_media。不建议维持"V1 手动工具但无守卫"：V2 期有人顺手跑 `assemble_episode.py ep01` 就把 V1 音色 / 配乐合进 V2 |

### 2）HOLLYWOOD
| 项 | 结论 | 证据 |
|---|---|---|
| review_request / judge_request 共用写入 | ✅ | `autoflow_agent.py:230-240 _inbox_write(rel, req)`：唯一写入口；`NSFS_INBOX_DIR` 有值 → 改写到该目录同名文件；原子替换（.tmp → replace）；只写不读不列 data/master；OSError 只打印不影响推进。`judge_request:216-225`、`review_request:243-247` 都调它 |
| camera-patch CLI | ✅ | `autoflow.py:905-940`：子命令先拿推进锁（和常驻 / 网页互斥），`AG.camera_patch:1217-1240`：运镜 id 必须在 camera_moves.yaml；补丁环忙（没有 final / 有未处理 patch 包 / 还有失败项）→ 只进 `agent.camera_queue`，空闲才出包（避免两包同时出）；出包经 `packet()`（守卫 / 覆盖句都在），包带 base_sha / targets=cam#N / camera_shot / camera_move。收稿 `:911-918`：闸门不变量先过 → `camera_check:1202-1214` **逐行比对**：镜块之前、之后的所有行必须与原稿完全相同（`lo[:rg_o[0]] != ln_[:rg_n[0]] or lo[rg_o[1]:] != ln_[rg_n[1]:]` → 拒），该镜的镜头运动必须是 move_id 认的写法；再要求失败项不变多。P2：`_shot_block` 若在新稿里找不到镜 N 返回"找不到镜"，而镜号被改名也会落到这里（可接受） |
| 测试隔离 NSFS_INBOX_DIR | ✅ / P2 | 实现在 `_inbox_write:232-233`；`test_owner_gate.py:61`（api 夹具）、`test_judge_agent.py:161`、`test_distill_flow.py:497` 各自 setenv。**没有 conftest 级默认**：任何新测试走到 `_p1_review` 出评审包 / reviewer 包而忘了 setenv，就写真实 `data/master/inbox/*.json`（我按约定没有去看 data/master 下有没有被写过）。建议 `tests/conftest.py` 加 `os.environ.setdefault("NSFS_INBOX_DIR", <tmp>)`，和 NS_PRIMARY_RUN 一样全局钉住；并把 data/master 纳入 real-data-guard 的监视目录 |

### P2 汇总
tts / assemble / shot_audio 五处不带 run 的 `load_voice_config()` 兜底 V1；bgm_api 候选 / 选曲目录写死 V1；deliver 第 1 遍不入候选、无 redo 测试；NSFS_INBOX_DIR 无全局默认；assemble_episode.py 无 V2 守卫（建议见上）。无 P0 / P1。

---

## 第 13 轮 · 11-02 22:25 快照 · UISCRIPT L-134 待办通知中心；STYLE-V2 L-129–132 登记 + deliver 响度重做；FACTORY API 重启（待交）

### 实跑
- `pytest test_owner_inbox / test_bgm / test_director / test_promptfix_v2`：**96 passed / 0 skipped**，real-data-guard 0。
- 线上 :8800（22:02 恢复）：`GET /api/owner/inbox` → count 0，counts {gate 0, decide 0, spot 0, pick 0}；`GET /api/owner/queue` → count 0，counts {decide 0, spot 0, pick 0}；两边 items 一致（都空）。V2 当前 P1 gate = approved（21:53:28 by fred，below_threshold / released_by_owner / round 5 / mean 32），verdict awaiting_writer（等 P4_ep01）→ 不该有通知，实测确实没有 ✅。

### 1）UISCRIPT 通知中心
| 问 | 结论 | 证据 |
|---|---|---|
| 顶栏数字 / 标签页标题 / #/queue 同一来源 | ✅ | `ownerQueue.ts:64` 唯一 fetch = `/api/owner/inbox`；`TopBarV3.tsx:188-198` 用 `q.count` / `q.counts.gate`；`useTabBadge`（ownerQueue.ts:147-150）`document.title = (n) …` 同一个 `q.count`；`OwnerQueuePage.tsx:206 useOwnerQueue()` 同一份数据。后端 `owner_inbox.inbox()` = `owner_queue.build()` 超集 + gate 项（:78-83） |
| 深链接 | ✅ | 后端 `_flow_link` = `#/script-create?new=1&flow=<run>&anchor=story|eps`；前端 `AutoflowPanel.tsx:97-124`：hash 带 flow → `loadRuns(flow)` 选中该剧，anchor=eps → 切"各集"页，否则故事线页，150 ms 后滚到面板；`OwnerQueuePage.tsx:270/351/359` 点击 / 回车 / 链接都 `location.hash = it.link`。注意 `new=1` 同时让 `NewScriptPage.tsx:80` 进入"新建"模式（setSel(null)），面板靠 flow 参数自己选剧——两者并存，实测靠 AutoflowPanel 的 flow 覆盖；没有浏览器实测，逻辑上成立 |
| 闸门状态变了通知自动消失 | ✅ | `owner_inbox.gate_items:39-75` 每次现算：`gate.status ∈ (None, pending)` 且 verdict ∈ {awaiting_owner_p1, owner_direction} 才出；approved / revise_requested / revising / redirect_requested 都不出；不另存。测试 `test_gate_notification_then_disappears`；线上 approved 后 0 项 ✅ |
| 会不会提前推没到门槛的稿 | ✅ 不会 | 只认 verdict `awaiting_owner_p1`（p1_gate 只在 `_p1_review` 过门槛后才设）和 `owner_direction`（总调度凭令牌转的，文案写明"没到门槛，等你定方向"，:61-65）；`awaiting_writer / awaiting_p1_judges / p1_review_failed / p1_fill_failed` 都不进。测试 `test_owner_direction_notification` |
| L-123 | ✅ | 通知文案只有"用这版 / 修改"；OwnerQueuePage 无"不要 / 拒绝 / 打回"字样（grep = 0） |
| P2 | | `gate_items:73` 用 `out[-1]["run"] == run` 避免 ep01 与 P1 重复，依赖 out 的顺序，写法脆；archived 过滤用 `_CLOSED` 集合而不是 `runs.status` 的统一口径（frozen / paused 的剧仍会被扫） |

### 2）STYLE-V2 登记（L-129–132）
| 项 | 结论 | 证据 |
|---|---|---|
| render_quality.json 预设 | ✅ | image_presets 新增 8 个 v2_editorial_*；项目方选定 `v2_editorial_fantasy_c`、`v2_editorial_reality_c2`（decision L-129/L-130），其余 6 个 `archived: true + archived_note`（不删）。**接线** ✅：`config/compile/run_style.json runs.series10_v2.segments` fantasy→fantasy_c / reality→reality_c2（post_lut 文件 `v2_fantasy_c.cube`、`v2_reality_c2.cube` 都在），`gen_contract/style.segment_preset:79-86` → `frame_job.py:286-288 job["preset"]`；archived 的 id 没被任何配置引用。`default_preset` 仍 = leica_sstar（V1），但 V2 作业走 segments 不走 default_preset；默认段 reality + 告警 |
| music_v2.json | ✅ 登记 / **⚠ P1-13a 没接线** | tracks 三条 `A_reality / B_reality / C_fantasy` sha256 **全对**（实算），archived 五条只留路径不带 sha（n/a）。但 `grep music_v2` 在 services/ 与 tools/（除 v2style 审片页）= 0——没有消费者；`tools/assemble_series.py:199 compose(... music_dir=ROOT/"data/music/series10")` **写死 V1 的配乐目录**：V2 装配 / 预览会配 V1 的 BGM（L-126 又一个入口，第 5 轮清单漏了这一条）。`cut_export.py:139` 按工程 bgm 文件取 ✅ 但工程默认 bgm 从哪来也要按剧 |
| voices_v2.json | ✅ | status owner_picked、enabled true；4 个角色 ×3 候选 `ref_sha256` **12/12 实算一致**；selected 各 1（lead_f b / m1 b / m2 c / m3 c）且 enabled；未选的 `enabled:false + archived:true`。消费者：仅 tools/v2style（voice_v2.py / voice_distinct.py）；ns_post TTS 仍读 `config/voices.json`（V1 音色表），V2 配音接线待做（和 music 同类，归 P1-13a） |
| deliver.py 响度重做 | ✅ / P2 | `tools/bgm/deliver.py:77-110`：两遍 loudnorm → 偏差 > 0.5 LU 报警 → 192 kHz 预限幅 + 加增益最多 5 次重做 → 仍偏离 `level_ok=False`（不静默交付）；中间文件放系统临时目录。P2：重做循环把 **最后一次** 结果写进 dst，不是偏差最小的一次（5 次都没进容差时可能比第 1 次更差）；`tests/test_bgm.py` 没有覆盖 redo / level_ok 分支（grep redo = 0） |

### 3）FACTORY API 自动重启
待它交付后复核（本轮未查）。现状：API 21:14:59 经看门狗起、仍在跑；lifecycle 有 started/api_startup 记录。

### P1 汇总
- **P1-13a** STYLE-V2 的 music_v2 / voices_v2 只登记没接线：`assemble_series.compose` 仍写死 `data/music/series10`（V1 配乐进 V2 成片 / 预览），TTS 仍读 V1 `voices.json`。按剧取配乐目录 / 音色表，和 run_style 一样放 run 级配置。

### P2
deliver 重做取最后一次而非最佳 + 无测试；owner_inbox 的 ep01 去重写法与 _CLOSED 口径；`new=1` 与 `flow=` 同时出现靠面板覆盖。

---

## 第 12 轮 · 11-02 22:10 快照 · sv-16（1d2cc20）：FACTORY F32/F33/_hm/export_tag 跳过；PROMPTFIX run_style/I7/K-REN-961/派生守卫/edits；VQAGATE Q10 count_host

### 实跑
- 10 个测试文件批跑：**1 failed / 351 passed / 0 skipped**；失败 `test_imgfix.py::test_k264_sheet_intake_catches_missing_sleeve_and_missing_outer`，单跑和整文件重跑 ×2 都过 → **flaky**（批跑并发下）；real-data-guard 0。
- `arch_scan --check`：FAIL 1 处（tools/v2style/parallax_bt.py 未入版）。
- :8800 现状：`data/ops/api_lifecycle.jsonl` 21:14:59 `started by=项目方 watchdog_pid=8792 pid=38692` → 21:15:00 `api_startup pid=3172`；三个进程都在（StartTime 21:14:59）。**API 经看门狗在跑** ✅。

### 1）FACTORY
| 项 | 结论 | 证据 |
|---|---|---|
| K-OPS-F32 留痕 | ✅ 已生效 | 规则 `ops_factory.yaml:369-375`；`ops/restart_api.ps1:3 param -By`、:15 记 restart_requested（含父进程链）、:45 经 `api_watchdog.py --by`、:53 restart_done → `data/ops/restart_events.jsonl`；`api_watchdog.run:28-40` 记 started / exited(rc)；`app.py:2104-2127` 启动 / 关闭各一行。21:14:59 这次完整留痕。`restart_events.jsonl` 还不存在 = 新版 restart_api.ps1 还没被调用过（这次是别的方式起的看门狗，by=项目方）。P2：lifecycle 里 20:47–21:15 有 9 对相隔 2–3 s 的 api_startup/api_shutdown（无 started 事件、ppid 各不同）——是 TestClient / 脚本在进程内起 app 时写进**生产**审计文件的；`_lifecycle()` 没判 pytest / 非 :8800 场景，审计文件会被测试刷脏。建议只在看门狗子进程（env 标记）里写 |
| K-OPS-F33 挂道 | ✅ | `tools/debug/lanes.py:109-114 lend(job_kind="comfy")`，非 comfy → `LendRefused`；`idle_sweep:240-268`：借满 idle_min、队列空、最近一单结束超时后，再 `gpu_foreign_procs`（nvidia-smi 查非本道 ComfyUI 进程占显存，:211-238）——有进程或探测失败 → `idle_release_blocked` 不回收；测试 `test_k_ops_f33_non_comfy_must_hold_and_idle_sweep_checks_gpu` |
| infra_status `_hm` | ✅ | `infra_status.py:63-70`：非法 / 负 / 超范围时间戳 → None，不再 500；api_8800.out.log 21:18 `/api/infra/status 200` |
| test_export_tag 在冻结快照里跳过 | ⚠ P2 | `tests/test_system_version.py:394-398`：没有 `.git` → skip；没有 sv tag → skip。cut 闸门的定向 pytest 跑在 `build_snapshot`（`system_version.py:568` 明确排除 .git）的目录里（`:617 gates(..., root=snap["dir"])`）→ **在 cut 闸门里这条永远 skip**；只有开发者在工作树手跑才执行；浅克隆（无 tag）的 CI 也会 skip。不是"永远不跑"，但"发版闸门永远不跑"。建议：不依赖 .git——用 `git -C <仓库> archive` 指向真实仓库路径（环境变量 NS_REPO_GIT）或把 export_tag 的"原字节 vs 工作区"判定拆成纯函数测 |

### 2）PROMPTFIX
| 项 | 结论 | 证据 |
|---|---|---|
| run_style.json 按剧取风格、没登记就报错 | ✅ | `config/compile/run_style.json` runs.series10_v2.suffix（临时、避开 suffix_banned）+ bible；`gen_contract/style.py:40-48 preset_suffix`：有登记用登记；资产包模式没登记 → `StyleMissing`（不退 V1 S★）；旧剧 → render_quality 默认。`bible.py:260-271` 资产包剧没 bible → `V1BibleRefused`；`compiler.py:118` V2 不补 V1 visual_bible 的 Leica 句 |
| I7 V1 风格词阻断 + v1_leak style | ✅ | `preflight.py:294-296`：`ST.v1_style_hits`（run_style.json v1_style_phrases：徕卡 / Leica / S★ / R0 / 暖调通透 / 微反差强 / 50mm f/2 / 干净真实）命中 → I7 fail；只对资产包模式剧判；`v1_leak.py:85-97` 把同一份词表作为 "style" 类并入 redact / 检测 |
| K-REN-961 例外只对 runs 列出的剧 | ✅ / ⚠ P2 | `camera_moves.yaml:282/297/312/325/338` 五个运镜都 `runs: [series10_v2]`；`camera_norm.run_ok:71-76` `run or current_run()` in runs；`run_scoped` 只对标了 runs 的放开速度词 / 不强制 The camera 开头；`normalize_video_prompt:140-148` 其它剧遇到这些运镜走 fallback（arc）。**但** run 取自进程上下文 `current_run()`（NS_RUN / primary），`compiler.py:826` 调用时不传本镜所属剧——同一进程若编译别的剧（例：primary=V2 时跑 S2 / V1 夹具），会拿到 V2 的例外。多剧并行进程设 NS_RUN 时正确；单进程混编时漏 |
| DerivedWriteRefused 按写入目标判 | ✅ / P2 | `asset_refs.py:965-983`：`_run_of_path(out)` → `data/pipeline/runs/<剧>/…` 取剧名 → `derived_writable(剧)`（状态 ∈ WRITABLE_RUN_STATUS）；不在剧目录（测试临时目录）→ 放行。V1/V2 的 crop_dir / board_dir 都在 `data/pipeline/runs/<剧>/images/` 下 ✅ 受守。P2：docstring 说也认 `data/renders/<剧>/`，代码只认 pipeline/runs；没配 crop_dir/board_dir 的剧用默认 `data/refcrops` / `data/refboards`（仓库根级）→ `_run_of_path` 返回 None → 不守（第二季若用默认目录就是这种） |
| edits.py 清欠债 | ✅ | sv-16 diff（+56/−38）：`edit_project()` 按当前剧、无项目配置抛错（`config/edit_engines.json` 的 project 字段废）；`cid == "lin_wan" and not _RP.manifest()` V1 兜底只在非资产包模式；`_atomic_json` / `_log_bad_lines` 收口写法 |

### 3）VQAGATE Q10 count_host
- `config/gen_contract.json:146 Q10_accept.count_host = "http://10.0.0.36:8893"`；`contract.py:687-697`：host 是 http → `defer=False`（gpu33 上也内联测人数，不再推迟）。
- 服务不可用分支：`anomaly._measure_http` 异常 → 每张 `{"error": …}` → `accept.count_check:173-174` → `{"status":"untested", infra:True}`；`accept.apply:217-229` fail / untested 都进 blocking Q10（infra 的标 score_infra，producer 只重打分不重出）；`vqa.json gate.enforce=true、untested_blocks=true`。**是 untested 且阻断** ✅。
- 运维提醒（不是缺陷）：这意味着 gpu36 的 :8893 常驻 + lan_proxy 一停，两台所有首帧都卡在 Q10 untested（设计上的失败关闭）；SENTINEL 要有这条服务的探针。

### P2 汇总
lifecycle 审计被进程内 app 实例（测试）刷脏；export_tag 测试在 cut 闸门永远 skip；K-REN-961 的 run 取进程上下文不取本镜剧；派生守卫对根级默认目录不生效、docstring 与实现不一致；test_k264 批跑 flaky；parallax_bt.py 未入版。

---

## 第 11 轮 · 11-02 21:55 快照 · NAVIA v1_guard 按 data 根判断（删 active）；CUTEDIT P1-9b prev_value / restore

### 实跑
- `pytest test_v1_v2_split_navia / test_frames_index_assetux / test_cutedit_api / test_cutedit_export`：**27 passed / 0 skipped**，real-data-guard 0。

### 1）NAVIA
| 问 | 结论 | 证据 |
|---|---|---|
| 残留 patch | ✅ 无 | `grep v1_guard.active / G.active` 全仓 = 0；`tests/test_v1_v2_split_navia.py:36-44 _client` 直接挂 `ns_api.app._v1_v2_split`（生产同一个中间件函数）+ `StaticFiles(directory=tmp data)`，TestClient 真打 /files；12 条用例覆盖：V2 primary 拦 V1 布局 / 放 V2、大小写·编码·反斜杠·`..`、legacy primary 放行、沙箱无 runs.json 不拦、runs.json 坏 → fail-closed、仓库 data 缺 runs.json → fail-closed、缓存按 data 根、gpu3-media 与 cache 出口、/v1-files 只放视频、scoped 按 data 根、video_index、v1-library |
| 三个调用点都传 data 根 | ✅ | `app.py:64 deny(path, query, P.DATA)`；`frames_index.py:29`、`video_index.py:31` `scoped(rel, data_dir=_P.DATA)` |
| NS_PROJECT_ROOT 启动时守卫生不生效 | ⚠ 不生效，但不是 V1 的口 | `v1_guard.py:31-33`：data 根 ≠ 仓库 data 且旁边没有 runs.json → `v2_prefix` 返回 None → 不拦。项目目录由 `project_ctx.PROJECT_SUBDIRS:227-229` 建（有 `config/`、`data/renders`、`data/renders_gpu3`），**不建 `config/pipeline/runs.json`**，所以带 `NS_PROJECT_ROOT=projects/<slug>` 起的 API 整条守卫是关的。但那时 `/files` 发的是 `projects/<slug>/data`——那部剧**自己的** renders/epNN，不是 series10_v1 的文件（仓库 data 不在挂载目录下，`/files/../` 被 StaticFiles 挡）；本机现在也没有任何 projects 目录、没有脚本用这个变量起 API（第 10 轮已核）。结论：不是 L-126 的新口；是"非仓库根 = 沙箱 = 不拦"这个约定的边界。P2 建议：项目目录若日后有多个版本（也建 runs.json）守卫会自动生效；或在 `v2_prefix` 对"data 根下存在 `renders/ep\d+/`（V1 布局）且没有 runs.json"打一条日志，免得静默 |
| 缓存键带 mtime 是否正确 | ✅ | `_prefix_cached:58-67`：键 = `str(data 根)`，值 = `(runs.json st_mtime_ns 或 None, 前缀)`；mtime_ns 变 → 重算；`os.replace` 写 runs.json 必变 mtime；runs.json 不存在时 mt=None 也能区分"从无到有"。仓库 data 下读不到 → `v2_prefix` 抛出发生在写缓存之前 → 不会把坏结果缓存住，每次都 fail-closed。无问题 |

### 2）CUTEDIT P1-9b
| 项 | 结论 | 证据 |
|---|---|---|
| prev_value | ✅ | `cut_project.py:465-498 commit_changes`：基线之后**别的窗口**改过同一字段 → `overrode` 存 `{field, label, prev_rev, prev_by, prev_at, prev_what, prev_value(= field_value 完整旧值), text}`；字幕是整份列表、顺序是整份序列、裁切是该镜入出点 |
| POST …/cut-project/restore | ✅ | `:557-585`：按 `history_id`（history 条目新加 `id`）找 overrode，可指定 field；order 的镜集合、trim 的镜号不在当前工程里的跳过；`commit_changes(..., always_record=True, extra={"restored_from": …})` → 恢复记成新改动、被它盖掉的当前值也进新条目的 overrode（可再恢复回去）；原条目加 `restored[]`；202 |
| client 标识 | ✅ / P2 | `CutEditor.tsx:96 CLIENT = 随机 8 位（每次加载页面一个）`，PUT 和 restore 都带（:251）；服务端 `other = prev and prev.client != client`（:477）——同窗口重发 / 连改不记"覆盖"（`test_resend_with_old_base_from_same_window_is_not_an_override`）。P2：刷新页面就换 id，自己上一次会话的改动会被当成"别人的"记进 overrode（只是多一条可恢复记录，不丢数据） |
| 恢复本身记成新改动 | ✅ | `new["what"] = "恢复被覆盖的改动：…"`，`restored_from`、`always_record`；测试 `test_restore_brings_back_overridden_subtitles` |
| 边角 | P2 | restore 时若 prev_value 与当前值相同，`commit_changes` 返回 None → 不写 history、静默 202；前端看不出"没变化"。建议回 `{"restored": false, "why": "和现在一样"}` |

### 结论
两批都达标，可进下一版。P2 三条（项目根无 runs.json 时静默不拦、刷新换 client id 的假覆盖、restore 无变化静默）记录即可。

---

## 第 10 轮 · 11-02 21:40 快照 · NAVIA P1-9a 修复里的 `v1_guard.active(P.DATA)` 开关

### 事实
- `services/api/ns_api/v1_guard.py:100-103 active(data_dir)`：`Path(data_dir).resolve() == (ROOT / "data").resolve()`，ROOT = 代码仓库根。
- `app.py:64`：`if GET/HEAD and v1_guard.active(P.DATA) and v1_guard.deny(...)`；`/files` 挂的也是 `StaticFiles(directory=P.DATA)`（:2090）。
- `P` = `ns_render.pipeline`：`pipeline.py:41-42 ROOT = Path(os.environ.get("NS_PROJECT_ROOT") or <仓库根>)`，`DATA = ROOT / "data"`。
- `v1_guard.deny` 读的 runs.json 是**代码 ROOT** 下的（:14-15），不是 P.DATA 所在根的。
- 测试：`tests/test_v1_v2_split_navia.py:43` `monkeypatch.setattr(G, "active", lambda d: True)` 后再测 deny——生产的 `active()` 本身没有被任何用例跑到，中间件路径 (:64) 也只在 active 被 patch 掉的前提下测。

### 问 1：线上有没有配置 / 环境变量能让 P.DATA 指到别处、绕过拦截
- **有，一个**：环境变量 `NS_PROJECT_ROOT`（T42 多项目：`project_ctx.py:157-161 ctx.env()` 给子进程设成 `projects/<slug>`；`bible.py:27`、`looks.py:26`、`compiler.py:53`、`framing.py:61` 同样认它）。API 进程若带着它启动：P.DATA = `projects/<slug>/data` → `active()` False → 守卫整条关掉，而 `/files` 照样发 P.DATA 下的文件。
- **今天没被触发**：`ops/restart_api.ps1`、`ops/autostart/*.ps1`、config 里都不设 `NS_PROJECT_ROOT`（grep ops/config/*.ps1/*.env = 0）；只有 `qwen_mailbox.py:339/429` 给**子进程**用 `ctx.env()`，不影响 API 自己。所以线上 :8800 现在是拦着的。
- 另一个在进程内改 `P.DATA` 的只有 `tools/ab_quality.py:48`（离线工具，不是 API）。
- 结论：开关是潜在的，不是现实的；但它是根因模式 1 的又一例——"拦不拦"看代码根，"发哪个目录"看 P.DATA，两套根。

### 问 2：能不能改成测试里也拦
- **能，而且更干净**。把判据从"P.DATA 是不是仓库 data"改成"**被发的这个 data 根**旁边有没有 runs.json、primary 是不是 legacy"：
  - `deny(path, query, data_dir)` 读 `Path(data_dir).parent / "config/pipeline/runs.json"`（和 `ns_agent.run_paths._ctx` 同一口径：沙箱 / 测试临时目录没有 runs.json → 旧行为不拦；有 → 按它判）；仓库 data 下 runs.json 读不到 → 仍按拒绝（现有 fail-closed 保留）。
  - 这样 `active()` 可以删掉；中间件路径在测试里真跑：夹具 `tmp/config/pipeline/runs.json = {"primary":"v2","legacy_unprefixed_run":"v1","runs":{...}}` + `tmp/data/renders/ep01/S1/takes/a.png`（V1 布局）+ `tmp/data/renders/v2/ep01/S1/takes/b.png`，`monkeypatch.setattr(P,"DATA",tmp/"data")`，TestClient：GET `/files/renders/ep01/...` → 404、`/files/renders/v2/...` → 200、`/files/cache/gpu3_media/renders_gpu3/...` → 404、primary=legacy 时 → 200。
  - 现有几十个 `monkeypatch.setattr(P, "DATA", tmp)` 的测试没有 runs.json → 不拦，行为不变；想测拦截的写 runs.json 即可。
  - `_prefix_cached` 的缓存键要带 data_dir（现在只按仓库 runs.json 的 mtime）。
- 顺带：`frames_index.py:28` / `video_index.py:30` 的 `v1_guard.scoped(rel)` 也读代码根的 runs.json，一起改成按 data 根。

### 严重度
P2（线上未触发；测试覆盖缺口 + 双根设计）。建议 NAVIA 按问 2 改，删掉 `active()`。

### 对 sv-16 cut 前状态
无 P0 未决。第 9 轮之后仍开着的：P1-9a（本轮确认已修，待上面 P2 收口）、P1-9b CUTEDIT 被覆盖改动无法恢复（字幕尤甚）、P1-6b 的尾巴（V1 里两份 `_derived_index.json` 待你定处置）、PROMPTFIX V1 风格后缀未交。这些不是我认为必须挡 cut 的项；是否带着 P1 发版由你定。

---

## 第 9 轮 · 11-02 21:25 快照 · VQAGATE 未测口径 / HOLLYWOOD 覆盖句 / NAVIA 整段匹配 / PROMPTFIX 守卫 / CUTEDIT 三方合并 / :8800 被停

### 实跑
- 11 个测试文件：**240 passed / 0 failed / 0 skipped**，real-data-guard 0 次（test_vqagate、test_vqa_anomaly、test_owner_gate、test_v1_v2_split_navia、test_frames_index_assetux、test_promptfix_v2、test_gen_contract、test_imgfix、test_autoflow、test_cutedit_api、test_cutedit_export）。
- `arch_scan --check`：FAIL 15 处，全部是新文件未入版 / 被引用未入版（cast_table、v1_guard、v1_library、v2_assets、api_watchdog、video_hands…）；无新增实质退化。

### 1）VQAGATE
| 项 | 结论 | 证据 |
|---|---|---|
| judge 无身份参照 → untested | ✅ | `anomaly.py:394-402`：有真人脸 + refs 未就绪 + 非 refless → `untested` 列表 + verdict clean→untested；有命中仍是 hit |
| check / count_check 当阻断 | ✅ | `anomaly.check:779` status = fail / untested / pass；`accept.count_check:176-183` 四条 untested 分支（检测器没跑成 ×2、本剧无身份脸、judge 判未测）；`accept.apply:217-229` "fail / untested 都进 blocking（Q10）"，只因基础设施的标 score_infra |
| `_ids()` 按剧 | ✅ | `anomaly.py:63-80`：资产包模式读清单 characters（id + display_name）；解析失败返回空表 + stderr 报，不退回 V1；非清单剧才 NAME_ID |
| video_hands ≥3 帧、分母只算有手帧 | ✅ | `video_hands.py:51-70`：`len(ok) < MIN_TESTED(3)` → untested；`tested = 有手的帧`；全无手 → na（不是 pass） |
| DETECT-S 夹具改动有没有放过该抓的 | ⚠ P2 | `tests/test_vqa_anomaly.py:22-32`：`face()` 默认给 A_→lin_wan 0.85、B_→chen_yu 0.85，`feat()` 默认 refs_loaded = V1 四人。改前这些用例 refs 没加载、陌生人判据整段跳过，所以没有任何用例曾真正测过"陌生人"；改后 extra_head 用例（:65-75、:114-121）用第三个 emb / 显式 sims 仍在测 ✅。**但**夹具把所有 A_/B_ 都设成"认得出"，而 judge 对"认得出、却不在本镜 cast 里的脸"没有判据（`:307-309` strangers 只看 sim < stranger_cos）——这个检测缺口是原有的，不是夹具造成的，只是夹具让它永远不会被用例暴露。建议补一条用例：B_（陈宇）入画、cast 只有林晚 → 现在是 clean，应判 extra_head（需要 judge 加"已识别但不在 cast"判据）。另：夹具 autouse 设 `NS_RUN_ID=series10_v1`，依赖 `remote_score.face_project` 认这个变量 |

### 2）HOLLYWOOD
| 项 | 结论 | 证据 |
|---|---|---|
| PLACEHOLDER_OVERRIDE 进包 | ✅ | `autoflow.py:123-125` 覆盖句 + OVERRIDE_TAG；`autoflow_agent.py:44/92` 两份 CONTENT_RULES 尾部都接上；`packet():111-112` 兜底：system+user+rules 里有"标'未提供'/标未提供"且没有 TAG → 追加。P2：`hollywood_writer.md:10`"没贴出的参数写'未提供'"这个写法不在兜底匹配词里（靠覆盖句的"事实核对类字段"语义覆盖）；CONTENT_RULES(:44) 仍保留旧句再接覆盖句，同一条规则里先说"标未提供"再说"不适用"，能用但不干净 |
| 补占位空话校验 | ✅ | `fill_check:614-620`：去空白 < FILL_MIN_CHARS=6、核心字符 ∈ TRIVIAL_FILL（无 / 暂无 / 没有 / 略 / 同上 / none…）、核心 < 2 字 → 拒。纯标点 / "无" 混不过；6 个重复字这类语义空话仍能过（无法靠规则判，P2 记录） |

### 3）NAVIA v1_guard 整段匹配
| 项 | 结论 | 证据 |
|---|---|---|
| 大小写 / 编码 / 多斜杠 / `./` / 反斜杠 | ✅ 已堵 | `v1_guard.py:66-76` `_variants`（反复 URL 解码、反斜杠、合并斜杠、算掉 ./ ../、去尾点空格、去 ::$DATA、统一小写）；实测 `/files/Renders/…`、`/files/RENDERS/…`、`%2F`、`//`、`/./`、`?src=data%2Frenders…`、`/api/assets/file?path=…`、`/api/looks/ref-image?path=…` 全部 DENY |
| **P1-9a 重新打开的口：renders_gpu3 / gpu3-media** | ⚠ | 整段匹配特意把 `renders_gpu3/` 排除（:67 注释"renders_gpu3/、myrenders/ 不算"），`/api/gpu3-media/` 直接豁免（:58）。本机 **`data/cache/gpu3_media/renders_gpu3/ep01/S1/takes/image_001.png` 等 10 个 V1 首帧缓存真实存在**，实测 `/files/cache/gpu3_media/renders_gpu3/ep01/S1/takes/image_001.png` → **allow**，`/api/gpu3-media/renders_gpu3/ep01/S1/takes/image_001.png` → allow（`app.py:1751-1766` 本地有就 FileResponse，没有就 `RD.fetch_media` 去 gpu3 镜像拉，镜像里是 V1 的 renders_gpu3/epXX）。旧正则 `renders(?:_gpu3)?/` 本来挡住这两条，这次改成整段匹配反而放开了。修法：`renders_gpu3/` 也按"非当前剧目录"判（它整个目录都是 V1 时代的）；gpu3-media 路由在自己的 400 检查之后再调 `v1_guard.deny`，或直接下线（V2 不用 gpu3 镜像） |

### 4）PROMPTFIX
| 项 | 结论 | 证据 |
|---|---|---|
| 派生图写入守卫 | ✅ | `asset_refs.py:965-968 _guard_derived_write`：runs.json 状态 ∉ WRITABLE_RUN_STATUS → raise DerivedWriteRefused；读不出 runs.json → 不许写；调用点 :697、:709（sheet_crop 两个生成分支，在 `.save(out)` 之前）、:976（record_derived）、:1717（make_board 生成前）——生成分支也守住了（第 6 轮 P1-6b 的缺口已补）。V1 里 20:22:05 写进去的两份 `_derived_index.json` 仍在，待你定处置 |
| cast_table.py | ✅ | `services/agent/ns_agent/cast_table.py`：名字→id / 女性 / 女主一张表，来源 = asset_refs.NAME_ID + 清单 register_manifest_names + asset_refs.json female/lead；`current_project` 走 `run_paths.current_run`，V2 不退回 V1；被 compiler / frame_spec / metrics import（arch_scan 显示未入版） |
| edit_project | ✅ | `edits.py:674 edit_project()`，`:689` 按当前剧取、取不到 ValueError 失败关闭（第 5 轮 P1-5a 已修） |
| V1 风格后缀去掉 | ⏳ 未查 | 它正在做；`compiler.py` 里 grep "S★ / 徕卡 / leica_sstar / style_suffix" = 0 命中，等它交了再核 |

### 5）CUTEDIT 三方合并（field_rev）
| 问 | 结论 | 证据 |
|---|---|---|
| 两边都改同一字段，被覆盖方能否从 history 恢复 | ⚠ **P1-9b 只有文字、不能一键恢复，字幕根本恢复不了** | `cut_project.py:412-416 mark_field` 记 field_rev{rev, by, at, what}；`:429-434 touch` 基线之后别人改过 → `overrode.append("…覆盖了第 N 版（谁 时间）的'what'")`，写进 history.entry.overrode（:487-491）。`what` 是人话描述：裁切 = "S5 入 0.50 / 尾裁 0.20"（数值在，可手抄回）、顺序 = "镜头顺序 S3 S1 S2"（可手抄）、**字幕 = "字幕 N 条"**（只有条数，旧文本没存）、bgm = 文件名 / 数值。没有存被覆盖的旧值本体，也没有"恢复这一版"的接口。建议 overrode 里带 `prev_value`（整个字段旧值），并给 `POST …/cut-project/restore {field, rev}` |
| 保存失败自动重发会不会重复应用 | ✅ 不会重复，但会留假"覆盖"记录 | 客户端只发与 baseRef 的差异（`CutEditor.tsx:208-236`），失败后 `pending` 留着 3 s 重发（:253-258）；服务端逐字段"值相同就不动"（:413、:421、:433 等），`what` 为空不升 rev → 幂等 ✅。P2：若第一次其实已成功只是客户端没收到，重发时 base 还是旧 rev，`touch` 会判"基线之后改过"→ history 多一条"覆盖了第 N 版（owner）"的假记录（覆盖的是自己刚存的同值） |

### 6）:8800 在 20:28:13 被直接结束——CUTEDIT / NAVIA / ASSETUX 的停进程写法会不会连带
- **能查到的事实**：`ops/logs/api_8800.{out,err}.log` 最后写入 20:28:13，最后一行是正常请求（/api/infra/status 500），无 shutdown 记录；`ops/logs/infra_watchdog.log` 11-02 20:21–20:29 只有 gpu33/36 心跳告警和 20:29:44 CLEAR，没有杀本机进程的记录；`data/ops/api_lifecycle.jsonl` **不存在**——api_watchdog 包装（`restart_api.ps1:44-45`）是 20:28 之后才加的，所以 20:17 起的那个 API 没有退出码记录。三方（CUTEDIT 20:27 匹配 sbx_server / vite-sbx-cutedit / edgecdp；NAVIA、ASSETUX 按端口 / 命令行）的实际命令**不在仓库里**（grep 全仓 .ps1/.py/.mjs/.md 无这三个词），审计日志 20:16–20:30 也没有，我只能按写法推。
- **推断（按 Windows / PowerShell 语义）**：
  1. `Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'sbx_server|vite-sbx-cutedit|edgecdp' } | Stop-Process`：API 两条命令行是 `python.exe -m uvicorn ns_api.app:app --port 8800 --host 127.0.0.1`（及 20:17 起的也是 Start-Process 直接起的 python），不含这三个子串；`-match` 是正则但这三个词不含通配，不会误匹配。**连带概率低（我给 ~90% 不会）**。
  2. 父子树：`restart_api.ps1:44` 用 `Start-Process -WindowStyle Hidden` 起，父进程是那次脚本的 pwsh/explorer，不在任何 agent 的 bash 会话树下；`taskkill /T` 杀 agent 自己的 bash / node 树不会到它。`.venv\Scripts\python.exe` 是真 python 不是转发器（pyvenv 直接执行），没有额外中间层。
  3. 会连带的写法：`Stop-Process -Name python`、`Get-Process python | Stop-Process`、`taskkill /IM python.exe`（K-OPS-F30 的扫描只扫仓库文件，扫不到会话里敲的命令）；或按端口 `Get-NetTCPConnection -LocalPort 8800`（只会在明确写 8800 时命中）；`-match 'edge'` 只会碰 msedge / edgecdp，不碰 API。
  4. 20:27 → 20:28:13 的时间相关性强，但没有证据链；也可能是别的会话用了上面第 3 条的写法。
- **把握**：对"给出的三个匹配词本身不会命中 API"约 90%；对"到底是谁结束的"查不出来（无留痕）。建议：① 让三方把 20:2x 实际执行过的停进程命令原样贴到 CHANGELOG（含完整 PowerShell）；② api_watchdog 已上线，下次会有 rc；③ K-OPS-F30 的检查扩到会话层：agent 守则写明"停进程只许 `Stop-Process -Id <自己记下的 pid>`，命令原文记 CHANGELOG"。

### P1 汇总
- **P1-9a** NAVIA：整段匹配把 `renders_gpu3/` 排除 + `/api/gpu3-media/` 豁免 → 本机 10 个 V1 首帧缓存可经 `/files/cache/gpu3_media/renders_gpu3/...` 和 `/api/gpu3-media/...` 取到。
- **P1-9b** CUTEDIT：被覆盖的改动只在 history 留文字，字幕只有条数，无法恢复。

### P2
DETECT-S 夹具让"已识别但不在 cast 的脸"缺口永不暴露；CONTENT_RULES 旧句 + 覆盖句同条；"写'未提供'"变体不在兜底匹配词；重发后假"覆盖"记录；V1 里两份 _derived_index.json 待处置；arch_scan 6 个新文件被引用未入版。

---

## 第 8 轮 · 11-02 21:05 快照 · HOLLYWOOD 补占位小包 P1_fill + "未提供"两处来源冲突

### 实跑
- `pytest test_owner_gate / test_autoflow`：**41 passed / 0 skipped**（含 `test_approve_triggers_placeholder_fill`、`test_fill_check_rejects_still_placeholder_and_unknown_field`）。

### 1）P1_fill 逐项（tools/script_rsi/autoflow_agent.py）
| 问 | 结论 | 证据 |
|---|---|---|
| 逐字段比对能否被绕过（整份只改空白 / 标点） | ✅ 绕不过 | `fill_check:592-615`：`{"fields":{…}}` 走 `_set_path` 只落到指定路径、路径不存在 → "字段不存在"；交整份 → `new = d`，同样 `diff_paths(sl, new)`。`diff_paths:577-590` 是**严格相等**的叶子级 diff（多 / 少键、列表长度不同、类型不同都算该路径变了）→ 其它字段改一个空格 / 标点就进 `changed`，`:608` 判"改了不许改的字段" → 整份拒收。基准 = 正式稿文件本身（:623），不是补默认值后的模型 |
| 改"允许字段"但没真补 | ⚠ P2 | "补了"的判据只是 `x in changed`（:609）+ 重跑 `check_storyline`。把"（未提供）"改成"。"或"无"：`placeholder_hits`（storyline.py:125-130，NFKC 归一）不命中，若该字段没有最短长度规则就过。建议 fill_check 加"非空且非纯标点、长度 ≥ N 字"的字段级检查 |
| prefill 留档 | ✅ | `:657` `canon.rename(... .prefill<HHMMSS>.json)` 再写新稿；STATE 记 `placeholder_fills[{old_sha,new_sha,fields,packet}]`（:665-667） |
| STATE 改指新稿会不会顺带放过别的未评审改动 | ✅ 不会 | 出包时记 `base_sha`（:625、:634）；收稿前 `pk_prev.base_sha != base_sha` 或 fields 变了 → 重新出包不收（:633-637）；`new` 要么是 canon 深拷贝只改 allowed 字段，要么整份经严格 diff 只许 allowed 不同；STATE 只在 `rounds[-1].sha == old_sha` / `owner_direction.sha == old_sha` 时改指（:661-664）。所以新 sha 对应的内容 = 评审过的那稿 + 仅占位字段。唯一没覆盖的是上一行的"伪补" |
| 最多 3 次 → p1_fill_failed | ✅ | `FILL_MAX = 3`（:543）；第 k 稿不过且 `k >= FILL_MAX`（:645-648）→ stage escalated、`verdict="p1_fill_failed"`、`awaiting=None`、live_note 转总调度。即第 1、2 稿不过再出包，第 3 稿不过转总调度 |
| 不进三评委 | ✅ 符合设计 | 只补 SL-12 字段、评审 sha 跟着换（:661-664），不再出评审包；前提是上面"严格 diff"成立 |

### 2）"缺信息标'未提供'"两处来源冲突——实际下发的包以哪句为准
- **事实**：V2 已发的 4 份 P1 包（`writer_tasks/P1_a1…a4.json`，最新 a4 = 20:00:20）`system` 里"未提供"各出现 **4 次**，`content_rules` 里 **1 次**，`"不留占位词"` **0 次**——即新规则（`autoflow_agent.py:92 CONTENT_RULES_CLEAN` 改写）至今没进任何一份真实包；a4 的 content_rules 仍是旧句"缺信息标'未提供'"。
- **来源**（同一份 system 里）：① `autoflow.py:127` 包头原文"【项目方 11-01 好莱坞模板（原文；红线：…缺信息标"未提供"…）】"（位置 2342/15591，靠前）；② `config/prompts/hollywood_writer.md:10`"没贴出的参数写'未提供'"；③ `hollywood_writer.md:14` 红线"缺信息标'未提供'"；④ 包尾【内容边界】= CONTENT_RULES（非 clean run，`autoflow_agent.py:44` 仍是"缺信息标'未提供'"）或 CONTENT_RULES_CLEAN（clean run，现已改成"不留占位词…写成具体内容"，位置 15363，最后）。另 `autoflow.py:751` 还有一份同句。
- **以哪句为准**：没有任何机制裁决——两句同时下发，写手模型自己猜。按权重，模板那句出现 3 次、在前、还冠以"项目方原文 / 红线"；新句 1 次、在最后。实践里只能预期写手继续写"未提供"，然后被 SL-12（storyline.py:157 block）打回 → 返修循环（第 4 轮 r4-fable 就是这么发现的）。对非 clean run（第二季）更糟：CONTENT_RULES 本身还教写"未提供"，SL-12 却对所有剧生效。
- **严重度 P1**：根因模式 1"同一事实两个入口"。建议：hollywood_writer.md 是项目方原文，改不改原文由你定；系统层至少在 `autoflow.py:127` 包头加一句明确的覆盖（"本系统里缺信息不写'未提供'，按 P0/P1 写成具体内容；原文红线里的'标未提供'不适用"），并把 CONTENT_RULES（非 clean）与 `autoflow.py:751` 一起改；加一条测试：任何新出的写作包 system+content_rules 不得同时含"标'未提供'"与"不留占位词"。

### P1 汇总
- **P1-8a** 写手包里"标'未提供'"（×4，含项目方模板原文）与"不留占位词"（×1）并存，真实包尚无新句；SL-12 会把按模板写的稿一律打回。

### P2
fill_check 对"伪补"（改成标点 / 单字）无最短内容检查。

---

## 第 7 轮 · 11-02 20:50 快照 · NAVIA v1_guard / V1 库 / LoadImg；CUTEDIT 202 合并 / 重编号导出 / srt；HOLLYWOOD W-38 / W-37 / 证据核验 / SL-12 / owner_hold

### 实跑
- `pytest test_cutedit_export / test_cutedit_assemble / test_frames_index_assetux / test_v1_v2_split_navia / test_v2_assets_assetux / test_owner_gate / test_judge_agent / test_autoflow`：**70 passed / 0 failed / 0 skipped**，real-data-guard 写真实数据 0 次。W-37 两条上轮红的用例现在绿 ✅。

### 1）NAVIA
| 项 | 结论 | 证据 |
|---|---|---|
| 拦截收进统一出口 | ✅ 但有绕过 | `app.py:60-66` HTTP 中间件：GET/HEAD 且 `v1_guard.deny(path, query)` → 404；覆盖 /files、/api/thumb?src、任何查询串（`v1_guard.py:53-67` 两次 unquote、反斜杠归一）；runs.json 读不到 → 拒绝（fail-closed）。`/v1-files` 单独挂 `_V1VideoFiles`，只放 `renders/ep*/S*/takes/*.mp4|webm`（:2080-2089） |
| **P1-7a 大小写绕过** | ⚠ | `deny` 的正则区分大小写；实测 `/files/Renders/ep01/S1/takes/a.png` → allow、`/files/RENDERS/ep01/x.png` → allow、`/files/renders/ep01/...` → DENY。笔记本是 NTFS，StaticFiles 按大小写不敏感找到文件 → V1 图经改大小写的 URL 照样发出。修法：`text.lower()` 再匹配，或 `re.I` |
| /api/v1-library 只读 | ✅ | `v1_library.py` 只有一个 `@router.get`（:41）；`V1Library.tsx` 只有刷新 / 播放 / 关闭三个按钮（:30/:50/:72），无 POST、无"用这版 / 修改 / 重出"（:2 注释亦声明） |
| LoadImg.tsx | ✅ | 0.3 s 后显示"原图传输中"，失败重试 4 次（3/6/9/12 s），仍失败"文件不在"；重试用 `?r=n` 破缓存；不改任何数据 |

### 2）CUTEDIT
| 项 | 结论 | 证据 |
|---|---|---|
| 保存 202 | ✅ | `cut_project.py:400 @router.put(... status_code=202)`；原来的 409（"工程已更新到第 N 版"）已删，改为 history 里记"基于第 x 版的改动，已合并到第 y 版"（:121-122 diff） |
| **P1-7b 旧版本合并会默默覆盖别处的新改动** | ⚠ | 服务端"合并" = 只应用这次发来的字段（:405-435），不是对比客户端基线的三方合并。而网页每次保存都发**全部**视频段的入出点 + **完整**顺序 + 字幕（`CutEditor.tsx:208-213`）。场景：A 窗口（rev 3）改了 S5 的裁切 → 服务端 rev 4；B 窗口还在 rev 3，只拖了顺序，保存时把 S5 的旧裁切、旧字幕一起发回 → :413 判"值不同"→ 覆盖回旧值，202 收下，只在 history 留一句。项目方在 A 的改动就这样丢了。修法：客户端带基线 rev 的快照、服务端只应用"与基线不同"的字段；或网页只发改动字段 |
| 导出重编号 → 还原镜号 | ✅ | `cut_export.py:142 renumber_for_order`（按 order 把 index 重排成 1..n，trims / sources 按 fwd 重挂；order 与剧本镜集合不符 → ValueError）→ 合成 → `:147 relabel_timeline`（shots[].index/shot 还原剧本号，`cut_position` = 成片位置；speech 同步改 shot 与 key）→ `:155 srt_cues` 在还原之后按剧本镜号查 `start_s` ✅ 顺序正确。测试 `test_cutedit_export.py:77` 断言 `[(3,1),(1,2),(2,3)]` |
| 字幕外挂 | ✅ | `:155-157` 写 `_final/<base>.srt`，manifest 记 `"subtitles": "sidecar .srt（不烧录，L-002）"`；cut_export.py 无 drawtext / burn |
| 路径 run_paths | ✅ | `cut_export.py:113-114, 140 RP.script_path(ROOT)`；`cut_project.py:21, 47 _RP.renders_for_data` |
| 镜号还原会不会错位 | ✅ 未发现 | back 由 renumber 生成（新号→剧本号），relabel 只查 back；speech 的 key 用 `-S{pos}#`→`-S{orig}#` 字符串替换，仅当 key 为 str。潜在边角：`episode2.shots[*]` 里的 `id` 字段（"ep01-S5"）没随重编号改，若 assemble 用 id 而非 index 定位源文件会错——当前 assemble 用 index（测试通过），记为 P2 观察 |

### 3）HOLLYWOOD 第三批
| 项 | 结论 | 证据 |
|---|---|---|
| W-38 escalate_and_advance | ✅ | `autoflow.py:628-650`：先拿推进锁（最多等 60 s，拿不到报错、不写任何状态）→ 同一把锁内 `review_escalate_owner`（令牌）→ 立即 `AG.run`（source=escalate）→ finally 放锁；verdict 只由推进写，不双写 |
| W-37 _refuse_closed | ✅ 绿 | `script_autoflow.py:56-61` CLOSED = archived/frozen/paused → 409 大白话；`_spawn:65` 和 `/brief:252` 都调。P2：`/gate` 先 `act()` 落盘再 `_spawn` → 已关闭的剧 gate 记录仍会被写一次才 409 |
| p1_collect 证据核验 | ✅ | `judge_agent.py:297-300` NFKC + 引号统一 + 去空白后查子串；`:378` 不合格封顶 `EVIDENCE_FAIL_CAP=2`；`:385-388` 超过 `EVIDENCE_FAIL_MAX=3` 条整份无效、不计均分、要求重交；无证据仍记 1 分 |
| SL-12 占位词阻断 | ✅ 单一来源 | `ns_schema/storyline.py:124-157` block 级；`looks_table.py:22-33` 复用 `placeholder_hits`；judge_agent:337 只记录 |
| _p1_owner_hold 会不会成口子 | ✅ 范围收紧 | `autoflow_agent.py:539-553`：只在 P1 已 owner_direction 或 approved 时生效；`validate` 后若 **任何** block 的 rule 不在 `OWNER_HOLD_RULES={"SL-12"}` → 返回 None 走正常返修（:547）；只有"全部阻断都是 SL-12"才沿用并把问题挂进 `st.p1_owner_hold`。扩大口子只能改这个常量。风险仅剩：被 hold 的稿带着"（未提供）"进 P2——即待做的"补占位小包 + 逐字段 diff"，在它落地前 P2 包里会有占位词（P2 跟踪） |

### P1 汇总
- **P1-7a** v1_guard.deny 大小写绕过（Windows）。
- **P1-7b** cut-project 旧版本合并 = 整包覆盖，会默默丢别处的新改动。

---

## 第 6 轮 · 11-02 20:40 快照 · VQAGATE 三件 + asset_refs 20:16 改动 + FACTORY 一批

### 实跑
- `pytest tests/test_gen_contract.py`：20:3x 快照 **6 failed / 35 passed**，real-data-guard 拦下 7 次 `mkstemp → data/pipeline/runs/series10_v1/images/refboards`；20:4x FACTORY 加 `_archived()` 后复跑 **41 passed，写真实数据 0 次**。
- `pytest test_factory / test_system_version / test_vqagate / test_promptfix_v2 / test_story_runs_uirsi`：**175 passed / 0 skipped**。
- `arch_scan --check`：FAIL，**asset_refs.py silent_read 7→8**（新 `_archived()` 的 try/except）+ 未入版新文件（cast_table.py、v1_guard.py、v1_library.py、v2_assets.py、post_verify.py、golden_v2.py hard_run/nonatomic_json）。

### 1）VQAGATE
| 项 | 结论 | 证据 |
|---|---|---|
| anomaly_server 只听 127.0.0.1 | ✅ | `anomaly_server.py:136 ThreadingHTTPServer(("127.0.0.1", PORT))`；内网经 lan_proxy 只放 gpu33（文档 :12/:19） |
| 与 anomaly.py 共用一份代码 | ✅ | `:74-75` 从 `anomaly.REMOTE_SRC` 按 `"\nrefs = {}\n"` 拆成加载段 / 每请求段，拆不到 / 缺 @@RES@@ 启动即报错（:49-59）；/health 带 code_sha |
| 服务不可用 = 未测，不当通过 | ✅ | `anomaly.py _measure_http`：异常 → 每张 `{"error": …}`；`contract_check:746-747` error → status untested；`contract.py:301/309/322`：untested 进 blocking；`config/vqa.json gate.enforce=true、untested_blocks=true`。Q1d 本身按总调度决定是"只记录 na"（contract.py:707） |
| 图片是否出自有机器 | ✅ | 帧 / 图 b64 只 POST 到 host 参数（gpu36 :8893 内网）或 rssh gpu36；无外部 URL |
| Q1 per_face / wrong_faces | ✅ | `postflight.per_face_rows:79-91` 每脸 {bbox, h_ratio, as, sim, best, verdict}；`accept.identity:40-42` wrong_faces = verdict ∉ {过, 可放行, 小脸不判, 未判} |
| video_hands 8 帧 / ≥2 帧同类才不过 | ✅ | `video_hands.py:27-48` 均匀抽 n=8（跳首尾 5%）；`judge_frames:51-66` 同 code ≥ min_hits=2 → fail，1 帧只记；0 帧测成 → untested。P2：`tested` 把"没检到手"的帧也算进分母（文档说"测不到手的帧不算"），且只要 1 帧测成就能 pass——8 帧里 7 帧 error、1 帧 clean = pass，建议 tested < 3 也算 untested |
| **"没加载身份参照但画面有脸 → 未测"** | **⚠ P1-6a 没实现** | `anomaly.judge:287-289`：`refs_ready` 为 False 时 `strangers=[]`——陌生人判据**静默跳过**；`contract_check:748-751` 只看 defects，不看 `r["refs_loaded"]` → 有脸、无身份参照照样返回 **pass**。这是一条"未测当通过"。修法：`if faces and not refs_ready → status untested, reason "身份参照未加载"` |
| V1 耦合 | P2 | `anomaly.run_files:787 want = set(NAME_ID.values())`（V1 四个 id）；`accept.look_texts` 用 `RS.FACE_PROJECT`（已改按当前剧解析 ✅） |

### 2）asset_refs.py 20:16 改动（谁、是否违规）
- **谁**：工作树注释 `asset_refs.py:918 "PROMPTFIX 11-02 20:3x（总调度 20:10 ②）：派生参考图的 sha 账本"`；CHANGELOG_AGENTS.md 里 **没有** PROMPTFIX 对应条目（grep "sha 账本 / _derived_index" = 0），只有 FACTORY 20:4x 的修补说明。与 FACTORY 的说法一致：是 PROMPTFIX 加 sha 账本时带进来的。
- **做了什么**：`sheet_crop` / `make_board` 在笔记本上遇到"已有缓存但账本没登记"的派生图就 `record_derived()` 补写 `_derived_index.json`（diff :680-681、:1663-1664）；服务器侧 `_derived_on_server` 先返回 / 抛错，不会写 ✅（"服务器禁止重新生成派生参考图"这条没破）。
- **违规点**：补登记不分剧——测试解析 V1 镜头时往 **已归档的 V1 树** 写了 `data/pipeline/runs/series10_v1/images/refcrops/_derived_index.json` 和 `refboards/_derived_index.json`（两文件 mtime 20:22:05，仍在）。L-126 V1 只读冻结 → **违反**；同时让 test_gen_contract 6 条红。FACTORY 20:24 加 `_archived(project)` 守卫后不再写 ✅，但：① 只守了"缓存补登记"分支，新生成分支（sheet_crop 新裁 / make_board 新板）仍无守卫——对归档剧新生成本身就是写 V1，应在 `sheet_crop/make_board` 入口对 `_archived` 直接拒绝；② 20:22:05 写进 V1 的两个账本文件没处理（按"不删只隔离"由总调度定：移到 V1 清单的 `_quarantine/` 或保留并登记）；③ `_archived` 的 try/except 让 arch_scan silent_read 7→8。
- 严重度：**P1**（已修一半；规矩被破过一次、留下文件）。不是 P0 的原因：没有写进出图作业，服务器侧没生成。

### 3）FACTORY 一批
| 项 | 结论 | 证据 |
|---|---|---|
| export_tag 用版本库原字节 | ✅ | `system_version.py:729 git archive --format=tar <sv>`；注释 :733-734 说明 CRLF 根因 |
| .gitattributes eol=lf | ✅ | `* text=auto eol=lf`、`*.py text eol=lf`、`*.sh/.service/.env eol=lf`；.cmd/.bat/.ps1 crlf |
| post_verify 自动核对 | ✅ | `tools/factory/post_verify.py`（当前剧 face_of + sha 对清单 + 版本号）；`system_version.py:881 r["post_verify"] = post_verify(rs, h)`；测试 `test_deploy_records_post_verify`。未入版（arch_scan untracked） |
| 131 包清 advance_cmd | ✅ | 全部 writer_tasks：键 `advance_cmd` = **0** 份，`advance_cmd_removed` = 125 份（另 void 目录 2 份保留原字段作存档）；文件未删 |
| T-SR-01 事件同步 | ✅ | `tests/test_story_runs_uirsi.py:315 test_tsr01_wait_uses_completion_event`、`SR.wait(rid)` 改用完成事件；TODO_BOARD:209 仍标 ⏳ 需更新 |
| compose 按剧取剧本 | ✅ | `assemble_series.py:200 RUNS.script_path(run or RUN_ID, ROOT)` |
| runs 加载器收口两个入口 | ✅ | `spec_from_file_location(runs.py)` 只剩 `ns_agent/run_paths.py` + `tools/autopilot/runs.py` 自身（arch_scan 是扫描器）；40 处改为 `from ns_agent.run_paths import` / `ns_api.run_paths` 转调 |
| K-OPS-F30 只停自己的 pid | ✅ | 规则 `ops_factory.yaml:348-351`；`test_factory.py:849 test_k_ops_f30_no_mass_kill_by_name_or_port` 全仓扫 taskkill /IM、pkill -f、killall、Stop-Process -Name、fuser -k，只放行 ops/restart_*.ps1 |
| asset_refs `_archived()` | ✅/⚠ | 见第 2 节 |

### P1 汇总
- **P1-6a** VQAGATE："无身份参照 + 有脸 → 未测"没实现，`contract_check` 会 pass。
- **P1-6b** PROMPTFIX asset_refs 账本补登记写进归档 V1（L-126）；FACTORY 已守一半，新生成分支未守、两份已写文件待处置。

### P2
video_hands 1 帧即可 pass、tested 分母含无手帧；anomaly.run_files `want=NAME_ID`（V1）；arch_scan asset_refs silent_read +1；TODO_BOARD T-SR-01 状态未更新；/gate 对已关闭剧先写 gate 再 409。

---

## 第 5 轮 · 11-02 20:25 快照 · HOLLYWOOD P1-4a/4b/W-35/W-37 + V1→V2 带入口全面扫

### 实跑
- `pytest test_owner_gate / test_autoflow / test_judge_agent / test_story_runs_uirsi / test_script_library / test_v1_leak / test_lead_char_id`：**2 failed / 67 passed / 0 skipped**。红的两条都是 W-37 这批"测试先于代码"：`test_closed_runs_refused`（要 `SA.run_status`、`BriefBody.source_run`、frozen/paused 也 409）、`test_looks_parse_list_and_closed`（closed_check 口径变了）；`test_spawn_refuses_closed_run` 断言源码里有 `_refuse_closed(run_id, "开写或推进")`，当前 script_autoflow.py 里没有这个函数——W-37 **进行中、未完成**。
- `arch_scan --check`：FAIL 10 处，全是新文件未入版（ns_api/v1_guard.py、v1_library.py、v2_assets.py、tools/promptfix/golden_v2.py、tools/v2style/bgm_chroma_sim.py）+ golden_v2.py 的 hard_run / nonatomic_json 各 1。
- 我没有读 data/master/ 下任何文件（只看了 config/master/escalate.sha256 摘要与 .gitignore:98-99）。

### 1）HOLLYWOOD
| 项 | 结论 | 证据 |
|---|---|---|
| P1-4a 令牌授权 | ✅ | `autoflow_agent.py:258-270 _check_escalate_token`：无 --token-file → PermissionError；`config/master/escalate.sha256` 不存在 → PermissionError；sha256(令牌 strip) ≠ 摘要 → PermissionError；对上只返回摘要前 8 位。`review_escalate_owner:276-292` 仍先查 by 含"总调度"，再查令牌；审计写 token_digest8 / pid / user，**不写令牌原文**；`autoflow.py:914` 日志只记 digest8。`.gitignore:99 data/master/escalate.token`。测试 `test_owner_direction_flow:411-422` 覆盖"非总调度 / 只写 by 无令牌 / 令牌错 / 对"四支。P2：token 文件不存在时抛 FileNotFoundError 而非 PermissionError（仍拒绝，只是消息不友好）；`--token-file` 路径出现在进程命令行（本机可见，不含原文） |
| P1-4b 接手后照样评审 | ✅ | carry 已删（grep `owner_direction_carry` = 0）。`p1_gate:474` 项目方"修改"时写 `owner_took_over`；`_p1_review:357-360` took 时轮数上限不再 escalate；新稿 sha 不同 → 照常出三评委包；收分后没到门槛 → `:390-402` 自动写 owner_direction（新稿 sha、by="系统（项目方已接手，自动带评分）"、`reference_only=True`），停在 owner_direction 等项目方；approve 记 below_threshold / released_by_owner。测试 `test_owner_revise_new_draft_reviewed_reference_only:447-495` |
| W-35 读锁空/半截 | ✅ | `autoflow.py:606-620`：FileExistsError 后最多 20×10 ms 重读；FileNotFoundError（刚释放）→ 回去重抢；一直读不出 dict → `return None`（按有人持锁，不删）；只有读到 dict 且陈旧 / pid 已死才 unlink |
| W-37 拒绝归档/冻结/暂停 | ⚠ 进行中 | 现在只有 `_reject_archived:203-210`，只在 `/brief` 调（:230），只拒 `archived`；/start /repair /gate 经 `_spawn` 不查；frozen / paused 不拒。测试已写成目标口径（见"实跑"），当前红 |

### 2）V1 → V2 / 新剧 带入口清单（全仓扫）
✅ = 已切断；⚠ = 仍可能带入；标 P 级的要修。

| # | 入口 | 状态 | 证据 |
|---|---|---|---|
| 1 | 写作包（autoflow_agent.packet） | ✅ | clean_cut run 经 `v1_leak.redact` 换掉旧剧名 / 场景 / 道具，内容边界用 CONTENT_RULES_CLEAN；registry_chars/scenes 清空（`run():773`）；本轮 V2 包 grep V1 名 = 0 |
| 2 | story_runs（旧写作线） | ✅ | claude_agent 下 `_start` / `:357` 直接 409，不跑 `_worker`（registry_tables 在 `_worker:481` 里，不可达）；`story_images` 按 `_RP.current_run()` |
| 3 | 导入器 tools/import_script.py | ✅ | `--script` required 无默认（:195）；`--image-doc` 默认 None 且注明 V2 不许引旧文档；`-o` 默认 `runs.json primary` 的导入稿路径 |
| 4 | /brief 续写来源 | ✅/⚠ | `BriefBody.clean_cut=True` 默认；`_reject_archived` 拒 registry_from 含归档剧；但 frozen/paused 来源不拒（W-37 未完） |
| 5 | asset_refs 解析 | ✅ | `config/recipes/asset_refs.json series10_v2` 无 inherits，assets_manifest=assets_v2/manifest.json；`face_of:891-897` manifest 模式只读清单；`project_cfg` 只在有 inherits 时合并父项目（:68-93）；`asset_refs.py:337` 把清单 display_name/aliases 登记进 NAME_ID |
| 6 | **改图 / 导演加强 preflight（ns_api/edits.py）** | **⚠ P1-5a** | `edits.py:669 project = engines_cfg().get("project") or "series10_v1"`，`config/edit_engines.json` 里 project = **series10_v1**。V2 镜头走"改图"时，契约请求按 V1 项目做 asset_refs 槽位规划 → 带 V1 身份脸 / 设定图进 V2 改图作业。应按 shot 所在剧（`runs.current_run()` / framing_project）取 |
| 7 | **frame_spec 人物表** | **⚠ P1-5b** | `frame_spec.py:214 CHAR_IDS={"林晚":"lin_wan",…}`、`:352 WHO_IDS={"她":"lin_wan",…}`、`:649 lead = … id=="lin_wan"`；`gpu3_fields.py:21 FEMALE={"lin_wan"}`。`build_spec` 被 `ns_render/pipeline.compile_with_edits:796` 和 `prompt_snapshot:26` 调用，是 V2 编译也会走的路。V2 人物名不在表里 → `CharacterSpec(id="extra")`，"她"的视线目标 → `lin_wan`。asset_refs 的 NAME_ID 已按清单登记，frame_spec 的两张表没有（grep `CHAR_IDS.update/[` = 0）。两份人物表 = 根因模式 1 |
| 8 | VQA 打分 / 报告 | ⚠ P2 | `postflight.py:56 NAME_ID`、`:168 outer_rows(project="series10_v1")`、`:208` 按 `sims["lin_wan"]` 排脸、`:455/459`；`metrics.py:255` 默认 character "lin_wan"；`report.py:99 WHO`。`remote_score.local_faces` 已按清单（第 1 轮核过），但本地判读仍按 V1 id 取字段——V2 结果只是取不到、不会错判，但字段名写死 |
| 9 | 造型数据种子 ns_agent/looks.py | ⚠ P2 | `:29 LIN_WAN_FACE="assets/characters/lin_wan/lin_wan.png"`，`seed():227` 给 lin_wan 塞 V1 脸；`:71-79` 角色锁 / 参考表写死 V1。API 侧 grep `seed(` 无调用（只 CLI `ns_agent.looks seed`），V2 looks_dir 不会被自动种；但若有人对 V2 跑 seed 就带入 |
| 10 | Ref2VA 身份登记 preflight | ⚠ P2 | `preflight.py:84-101 registered_identity_files` 读 **V1** `data/assets/identity_refs/manifest.json`；`:305` Ref2VA 分支按它判"已登记身份图"。V2 走 Pika 不走 Ref2VA，且结果是拒绝不是带入；但 V2 若开 Ref2VA 会被 V1 清单卡死 |
| 11 | 网页资产 / 人物 / 图片 | ✅ | `assets.py:190 _RP.manifest_character_ids()` 只列清单角色；`ns_api/v1_guard.py`（新，未入版）：primary 非 legacy 时文件必须在 renders/<primary>/ 下，V1 只在 /api/v1-library；`decision_check D-V2-01` 实测只含 lead_f |
| 12 | 剧本库 | ✅ | `script_library.py:27 _DONE_STATES` 含 archived → 历史剧本 |
| 13 | CUTEDIT / compose / 装配 | ✅ | `assemble_series.py:139` 与 `:200` 都改 `RUNS.script_path(run or RUN_ID)`；`tools/cut_export.py:140 RP.script_path`；`cut_project.py:47 _RP.renders_for_data`；`tools/assemble_episode.py:119` 由 `--script` 显式传 |
| 14 | prompt_rewrite | ✅ | 纯文本改写，不读参考图（grep assets/face_of/.png = 0） |
| 15 | pause / control / producer 路径 | ✅ | 第 4 轮已核（pause_state.py、producer.Paths legacy_run_id） |
| 16 | 工具脚本 | ⚠ P2 | `tools/gen_contract/calibrate_imgfix.py:76` 写死 `runs/series10_v1/epNN/P4_epNN.md`；`look_audit / reflock_v9 / reflock_validate / imgfix_ab` 用 `RUN/ep01/P4` 常量——都是离线校准工具，不在生产链，但复用在 V2 上会读 V1 稿 |

### P1 汇总
- **P1-5a** `edits.py:669` + `config/edit_engines.json project=series10_v1`：V2 改图契约按 V1 项目规划参考（真实带入口）。
- **P1-5b** `frame_spec.CHAR_IDS / WHO_IDS`、`gpu3_fields.FEMALE` 写死 V1 人物；V2 编译经 `pipeline.compile_with_edits → build_spec` 会把"她"指到 lin_wan、V2 人物当 extra。应改成从 asset_refs.NAME_ID（已按清单登记）取，一张表。
- **W-37 未完成**：只 /brief、只 archived；/start /repair /gate 未拦；frozen/paused 未拦；测试红 2 条。

### P2
令牌文件不存在抛 FileNotFoundError；postflight/metrics/report 的 V1 id 字段；looks.seed 的 V1 种子；Ref2VA 身份登记读 V1 清单；离线校准工具写死 V1 路径；arch_scan 10 处未入版。

---

## 第 4 轮 · 11-02 20:10 快照 · HOLLYWOOD owner_direction / FACTORY sv-15（48afe13）/ 并发测试复跑

基线：sv-20261102-15 = 48afe13（19:59:30）；之后工作树 21 个文件未提交（含 owner_gate.py / autoflow_agent.py / autoflow.py / script_autoflow.py / P1Review.tsx 等 owner_direction 这批）。

### 实跑
- 9 个测试文件批跑两遍：**195 passed / 195 passed，0 failed，0 skipped**（test_owner_gate / test_autoflow / test_factory / test_system_version / test_promptfix_v2 / test_vqagate / test_looks_table / test_judge_agent / test_cutedit_assemble）。
- `test_two_processes_only_one_advances` 单跑 8 次 + 批跑 2 次 = **10/10 过**。改法：两个子进程各写 ready_i，等 go 文件同时抢锁，持锁方等 release 才放（test_owner_gate.py:301-323）——第 3 轮的偶发根因（A 放锁后 B 才起）已消除。
- `arch_scan --check`：FAIL 但只剩 **1 处**（`services/api/ns_api/script_library.py` mtime_latest 0→1，sv-15 之后的改动，不在本轮范围）。
- 进程：`tools/factory/autoflow_resident.py --interval 30`（pid 38316，19:52 起）单实例；HOLLYWOOD 的 `autoflow.py watch` 已不在；uvicorn 只剩 :8800（:8811 已停）。心跳 data/factory/autoflow_resident.json 20:08:09 runs=[series10_v2]。

### 1）HOLLYWOOD owner_direction
| 问 | 结论 | 证据 |
|---|---|---|
| 授权强度 | **P1-4a 太弱** | `autoflow_agent.py:258 review_escalate_owner`：`if "总调度" not in (by or ""): raise PermissionError` —— 任何进程 `autoflow.py review-state --escalate-owner --by 总调度` 就过；没有登录、没有凭证、不记调用方 pid/会话。`advance_log` 记了 by 文本（autoflow.py:902），但 by 本身是自报的 |
| sha 绑定 | ✅ 对那一稿成立，但被 carry 延长 | `owner_gate.owner_direction:27-39`：STATE.owner_direction.sha ≠ 当前 P1_storyline sha → None；`review_escalate_owner:268` 要求最后一轮评的 sha = 当前稿。**但**见下行 |
| "修改"后新稿不再评审 | **P1-4b 口子成立** | 项目方在 owner_direction 下点"修改"→ `p1_gate:445-449` 写 `owner_direction_carry`；下一次 `_p1_review:325-329` 把 owner_direction 的 sha 直接改成新稿 sha，`:331-339` 有 od 就 `return False/True`、**不再出评审包**。carry 没有次数上限：每次"修改"都重新 carry，一次 escalate 之后这部剧的 P1 永远不进三评委，直到"换方向"（redirect 归档 judge_p1）。文档说"只对当时那一稿有效"，实际是"对之后所有项目方改稿都有效" |
| redirect 只归档 | ✅ | `p1_gate:423-438`：P1 / report / P1_looks / judge_p1 整目录 `rename` 到 `_redirect_<时间>/`，`void_downstream` 移包，P0_brief.outline 前缀新方向；无 unlink / rmtree |
| 其它 | ⚠ | `act(redirect)` 要求 note 非空（:136-137）——"换方向"必须打字；approve 在 od 下记 `below_threshold / released_by_owner / audit`（:151-153）✅ 审计完整 |

**P1-4a 建议（授权）**：改成凭证而不是字符串。可行做法：`data/master/escalate.token`（.gitignore；总调度会话启动时生成，SHA-256 摘要写进 `config/master/escalate_token.sha256` 入版）；CLI 读文件算摘要对上才放行，并把摘要前 8 位 + pid + USERNAME 写进 STATE.owner_direction 与 autoflow.log；agent 守则（docs/AUTOPILOT.md 或各 loop 的 .md）写明"不许读 data/master/"。它挡不住恶意进程（同一用户都能读），但挡得住"顺手 --by 总调度"的误触和自动化脚本，审计也能回溯。更强的做法是把 escalate 做成网页动作、要项目方 / 总调度登录会话（`auth.user_of`），命令行只留 --dry。
**P1-4b 建议**：carry 最多 1 次（或完全不 carry）：项目方改稿后仍出评审包，分数只作参考、不拦——既保留"项目方定方向"，评审数据也不断档。

### 2）FACTORY sv-15
| 项 | 结论 | 证据 |
|---|---|---|
| pause_state.py 唯一判定 | ✅ | `tools/factory/pause_state.py`：远端执行 PAUSE_PY，run = run.json run_id，legacy → data/producer/control.json，其它 → runs/<run>/control.json；runs.json status≠producing 或 control.paused 都算已暂停；读不到 = 已暂停（保守）。`restart_queue.py:111-113`、`system_version.py:916-918` 都改调它；`test_factory.py:721 test_pause_state_real_layout` 用真实目录结构测 V1 control 不能用来判 V2 ✅。P2：剧 id 读 run.json 而不是 `runs.primary_run()`——两个入口（有注释说明同 producer.RUN_ID） |
| assemble_series 按剧取路径 | **⚠ 半改（P1-4c）** | `:139 RUNS.script_path(RUN_ID, ROOT)` ✅；**`:200 load_episode(ROOT / "data/import/script_v2.json", ep)` 仍写死 V1**——这是 `compose()`（成片 / 预览 / CUTEDIT cut_export 共用的合成入口）读的剧本。V2 装配会拿 V1 的集表配音配乐 |
| I11–I13 无 project 失败关闭 | ✅ | `preflight.py:367-368`（I11）、`:391-393`（I12/I13）：`elif not proj and kind == "image": add(..., "fail", "出图作业没有 framing_project…失败关闭")` |
| lead_f 造型只从 manifest 读 | ✅/⚠ | `looks_table.py:65-86 lead_manifest()` 从 assets_v2/manifest.json 取 LEAD_LOOKS / ADULT / DAILY / SHOES，代码不再写死 ✅；但 `closed_check:140` 和 `packet_user:170` 仍读 `assets_v2/owner_inputs.json`——造型集合仍两个来源（P2，第 1 轮 P2-8 剩一半） |
| runs.current_run 统一 | ✅/⚠ | `runs.py:85-90 current_run()`：NS_RUN 优先，其次 NS_PRIMARY_RUN / primary ✅。但 runs.py 的 `spec_from_file_location` 加载器副本从 9 份涨到 **12 份**（新增 ns_recipes/compiler、tools/import_script、tools/factory/autoflow_resident）——每多一份就多一处口径漂移点（P2） |
| autoflow_resident.py | ✅ | 单实例 `data/factory/autoflow_resident.lock` O_EXCL + 死 pid 接管（:49-66）；只推 `ADVANCE_STATUSES=("preparing","active","producing")`（:25-26、:77-83）；推进用 `autoflow.py run --source daemon`，跨进程锁在 autoflow 里（:97-99）；心跳 json；HOLLYWOOD 的会话级 watch 已停、不重复。P2：`_pid_alive` 用 `tasklist` 子进程（:40），30 s 一拍可接受 |

### 3）并发测试
✅ 10/10（见"实跑"）。不再偶发。

### P1 汇总
- **P1-4a** escalate-owner 授权只靠 `--by` 含"总调度"（建议凭证 + 审计，见上）。
- **P1-4b** owner_direction carry 无上限 → 一次 escalate 后项目方改稿永远不进三评委（与"只对那一稿有效"的说法不符）。
- **P1-4c** `tools/assemble_series.py:200` 仍写死 V1 剧本（第 1 轮 P1-4 只改了 :139 一处）。

### P2
pause_state 读 run.json 而非 runs.primary_run；looks_table closed_check / packet_user 仍读 owner_inputs.json；runs.py 加载器 12 份；"换方向"必须打字；arch_scan 剩 1 处（script_library.py mtime_latest）。

---

## 第 3 轮 · 11-02 19:45 快照 · HOLLYWOOD H2–H5 修复 + UISCRIPT 新建剧本页

### 实跑
- `pytest test_owner_gate / test_autoflow / test_ui_no_tech_words_assetux / test_story_runs_uirsi / test_judge_agent / test_l123_no_reject_ui`：**批跑 1 failed / 55 passed / 0 skipped**；失败 `test_owner_gate.py::test_two_processes_only_one_advances`，单跑 3 次全过 → **flaky**（见 P1-3b）。
- `arch_scan --check`：FAIL 22 处（untracked_code 为主；新增 `tools/factory/autoflow_resident.py` 未入版却被 test_factory import）。
- 第 2 轮三评委确由守护自动汇总：`autoflow.log` 19:42:23 `source=daemon pid=4792` → 19:42:24 verdict awaiting_writer "返修中（第 2 轮，评审 31.67/40）"；`judge_p1/r2/RESULT.json` n=3 totals [33,31,31] mean 31.67 judge_ids r2-fable/r2-opus/r2-sonnet base_sha=613ef1da…；STATE.json rounds[-1] passed=False why=["均分 31.67 < 34"] revise_attempt=3。✅

### 1）HOLLYWOOD 逐项
| 项 | 结论 | 证据 |
|---|---|---|
| 跨进程锁 | ✅ 有 | `autoflow.py:595-617 acquire_advance_lock`：O_EXCL 建 `work_epNN/advance.lock`，写 pid/source/at；陈旧（>1800 s）或 pid 已死接管；`cmd_run:624-633` 拿不到 → 记 `skipped_locked` 退出，finally unlink |
| 并发测试 | ⚠ 有但 flaky | `test_two_processes_only_one_advances` 起两个子进程各拿锁、睡 2 s；批跑时失败、单跑过——负载下 A 进程可能"拿锁-睡 2 s-释放"完才轮到 B 起来 → 两个 GOT。要用屏障（同时起跑信号 / 更长持锁）才稳；`test_advance_lock_cross_process` 单进程逻辑测试 ✅ |
| watch 扫评审 .done | ✅ | `autoflow.py pending_done:773-795`：verdict==awaiting_p1_judges 时读 STATE.rounds[-1].dir，三个 judge .done 齐才报；测试 `test_watch_detects_all_judges_done` 覆盖"少一家不报" |
| 扫描范围含 flow.py | ✅ 停用 | `flow.py:865-871 autoflow_tick` 只返回 due 不执行；旧实现改名 `_autoflow_tick_retired` 留档不调用；测试 `test_single_advance_entry_flow_tick_reports_only`。但 `test_packets_have_no_advance_cmd_and_cli_logs` 仍只扫 tools/script_rsi（P2） |
| ep_gate 走 packet() | ✅ | `autoflow_agent.py:420-423` 调 `packet(..., output_path=op)`；packet 新增 `output_path` 参数（:99、:109） |
| autoflow.log 拆分 | ✅ | `script_autoflow.py:58` 子进程 stdout 改写 `autoflow.stdout.log`；autoflow.log 仅 JSON 行（旧的首行状态 JSON 仍留在文件头，历史脏数据） |
| writer_tasks advance_cmd 清掉 | ✅ | `grep -l advance_cmd writer_tasks/*.json` = 0；void 目录两份旧包仍含该字段（存档，不被任何路径读） |
| void 写法统一 | ✅ | 文件名 `<step>_a<k>.void<HHMMSS>.json`、包内 status=voided + voided_at、`VOID_LOG.jsonl` 记 why/moved；P2 包和 19:17:58 looks 包的 VOID_LOG 没补一条（只有 19:42:23 自动 void 那条） |
| CHANGELOG 改正 | ⚠ 半改 | :648 加了"autoflow_tick 停用推进"，但 :646 原文"一次命令行 autoflow 推进…待 SCRIPTWRITER 确认"未改——时间线仍把真凶写错 |
| W-25 别的写 approved 路径 | ✅ 无 | `owner_gate.act` 是唯一外部入口（approve 时 `p1_review_ok` 否则 PermissionError → /gate 409，`script_autoflow.py:184-185`）；`set_status` 只被 p1_gate（revising/pending）和 intake_full_p4（epNN）调；`ns_api.owner_gates` / `data/sop/owner_gates.json` / orchestrator engine 的 approved 是 V1 SOP g4/g5 另一套文件；没有 `/api/gates` 路由（只有 `/api/producer/gate`，不同系统）；story_runs 不碰 owner_gates。直接手改 `<run>/owner_gates.json` 仍可（`_read` 无校验，P2） |

### 2）UISCRIPT 逐项
| 问 | 结论 | 证据 |
|---|---|---|
| 按钮显示条件 | ✅ | `P1Review.tsx:13-16 canShowP1`：只有 verdict==awaiting_owner_p1 且 latest.passed!==false 且 P1 非 revise_requested；按钮只有"用这版"（:106）"修改"（:109）；"修改"给 6 个一键选项 QUICK（:9、:89），文字可选（:96）——符合 L-123 + 一键原则 |
| clean_cut 默认 | ✅ true | `NewScriptPage.tsx:223 continueOld=false`，`:291 clean_cut: !continueOld`，勾"续写已有剧"才 false；后端 `test_brief_clean_cut_default_true` |
| /gate 的 by | ⚠ 取会话但不拒未登录 | `script_autoflow.py:183 _actor(request)` 从 `auth.user_of` 取名、不信前端 ✅；但没登录返回 "未登录" 后**照样写 approved**（:160-168 无 403）。`auth.py:9` 自己写"各闸门接口原有的检查会拒绝（403）"，这里没有；`test_p1_approve_refused_until_review_passed` 甚至以 request=None（= 未登录）成功 approve 作为通过条件。story-images pick 对 unauthenticated 是 403（test_story_runs_uirsi:287）。→ **P1-3a** |
| story_runs claude_agent 409 | ✅ | `story_runs.py:298-299`（_start）、`:357-358` 都 `raise HTTPException(409, AGENT_REFUSE)` |
| xfail 去掉 | ✅ | `test_ui_no_tech_words_assetux.py` 末尾 `test_status_ts_fully_plain` 无标记且通过；`grep -rl xfail tests/` 只剩 test_qa_laptop / test_resolution_layers / test_video_rca（旧文件，与本批无关） |

### P1
- **P1-3a /gate 未登录也能"用这版"**（上表）。建议 `_actor` 拿不到用户直接 403，测试把 request=None 的 approve 改成断言 403。
- **P1-3b 并发测试 flaky**（上表）。红了一次就会被当"偶发"忽略，等于没有覆盖。

### P2
- CHANGELOG:646 时间线未改正；`test_packets_have_no_advance_cmd_and_cli_logs` 不扫 flow.py；`pending_done` 在 p1_collect 因 base_sha 变化 / 条目不全而 n<3 时 verdict 仍 awaiting_p1_judges 且 .done 全在 → 守护每 30 s 再起一次 run（空转）；`owner_gates.json` 可手改无校验；`tools/factory/autoflow_resident.py` 新文件未入版但已被 test_factory import（arch_scan untracked_imported）；autoflow.log 文件头残留一行旧 stdout JSON。

---

## 第 2 轮 · 11-02 19:36 快照 · HOLLYWOOD 三批（A 门槛 / B 闸门守卫 / C 去 advance_cmd + watch 守护）

注意：HOLLYWOOD 在我复核期间仍在改（owner_gate.py 19:36:22、test_owner_gate.py 19:35:40、void 目录 19:30–19:33 改名），下面以 19:36 工作树为准。

### 实跑
- `pytest tests/test_owner_gate.py tests/test_autoflow.py tests/test_judge_agent.py`：**2 failed, 23 passed, 0 skipped**。失败：`test_owner_gate.py::test_gate_actions`、`test_owner_gate.py::test_no_p2_packet_before_p1_approved`，都是 `owner_gate.py:111 PermissionError: 还没有 P1 故事线`——19:36:22 新加的 W-25（"用这版"必须先过三评委）让两条老用例的 `OG.act(..., "approve")` 直接炸。报告说"测试过"，当前红。
- `arch_scan --check`：FAIL（19 处退化，比上轮 26 少；HOLLYWOOD 新文件 looks_table.py / owner_gate.py 仍是 untracked_code，入版即消）。
- 进程：`autoflow.py watch --run-dir data/pipeline/runs/series10_v2 --interval 30`（pid 14412，19:32:36 起）在跑；uvicorn :8800 与 :8811 两个 API 实例在跑；resident_sync 的 autopilot 拍在跑（`data/autopilot/flow/last_tick.json` 19:36:05，dry=false）。

### P0

**P0-H1 · HOLLYWOOD · "推进只有两个入口"不成立：autopilot 的 flow.autoflow_tick 仍是活着的第四个入口，而且它才是 19:17 事故的真凶**
- 说：（CHANGELOG_AGENTS.md:646）19:17:06 的 P2 是"一次命令行 autoflow 推进……待 SCRIPTWRITER 确认是否其 advance_cmd"；（:647、docs/hollywood/writer_agent_interface.md:37）"推进只有两个入口：网页 /repair 和 .done 守护"。
- 实际：`data/autopilot/flow/autoflow_tick.json` 记着 `"series10_v2/ep01": "P1_a1.json@1793614617"`（=19:16:57，写手建 .done 后 1 秒）——是 `tools/autopilot/flow.py:862-897 autoflow_tick` 读 writer_tasks 里 best 包的 `advance_cmd`（`flow.py:849`）并 `subprocess.run` 出来的，V2-WALK 已在 `docs/master/V2_WALK_AUDIT.md` W-23 写明。这条路现在仍在跑：`tools/autopilot/resident_sync.py:928-943 autoflow_thread → autoflow_tick_once`，`ops/logs/autoflow_tick_core.out` 19:36:05。HOLLYWOOD 既没停它，也没在时间线里认它。
- 为什么"去掉 advance_cmd"堵不住它：① `writer_tasks/P1_a2.json`（19:25:46，早于 19:31 的改动）**仍含 advance_cmd**，其 .done 19:33:36 已在；`autoflow_due` 每集只取 (attempt, mtime) 最大的包，眼下恰好是 `P1_looks_a2.json`（19:33:38，新包、无 cmd → `not x.get("cmd")` 跳过）挡在前面，一旦它被消费 / 改名，P1_a2 就成 best，autopilot 会再执行一次 P1_a2 的 advance_cmd——与 watch / 网页并发推进同一集；② `flow.py:855-858` 的 P4 分支**自己拼 cmd**（`autoflow.py run … --import dry`），根本不看包里有没有 advance_cmd，今后每个 P4 .done 都会被 autopilot 推一次。
- 根因模式 1（双入口）未关：推进入口现在是 4 个（CLI、网页 /start /repair、watch 守护、autopilot flow tick），彼此无共享锁（见 P1-H2）。
- 建议（给 HOLLYWOOD，抄 DEBUG-RSI 因为 flow.py 归 autopilot）：flow.autoflow_due/autoflow_tick 对 V2 run 关掉或改成只调 watch 的同一函数；清掉现存包里的 advance_cmd（P1_a1 / P1_a2 / void 里两份，改字段不删文件）；CHANGELOG 646 的时间线按 autoflow_tick.json 改正。

### P1

**P1-H2 · 同一集会被推进两次：三个 spawner 的"正在推进就跳过"都只在各自进程内**
- `autoflow.py cmd_watch` 用进程内 `procs` dict（diff :79-86）；`script_autoflow._procs` 是 API 进程内 dict（:27、:46-48），而 API 有两个实例（:8800 / :8811 → 两个 dict）；autopilot 用 `work_epNN/flow_tick.lock`（flow.py:873-877），watch 和网页都不看这把锁。没有任何跨进程锁文件。watch 30 s 一扫 + 项目方点 /repair（或 UISCRIPT 从 8811 点）= 两个 `autoflow.py run` 同时跑同一集，各自 `packet()` 写 `_a<k+1>`、各自改 autoflow_epNN.json。
- 建议：一把 `<run>/work_epNN/advance.lock`（O_EXCL 建文件 + 过期）放进 `autoflow.cmd_run` 入口，三个 spawner 自然共用；测试起两个进程并发 run。

**P1-H3 · A）"三家交齐后自动汇总"不自动**
- `autoflow.py pending_done`（diff :63-72）只看 `autoflow_epNN.json.awaiting.output + .done`；而 `_p1_review` 在等评委时 `st.set(verdict="awaiting_p1_judges", awaiting=None)`（autoflow_agent.py:240）。评委写 `judge_p1/r2/judge_k/out/p1_review.json.done` 不触发任何推进——第 2 轮三家交齐后要靠人点 /repair 或 CLI。现状：19:35:08 起 verdict=awaiting_p1_judges（0/3），守护不会接。
- 门槛本身 ✅ 在配置：`config/prompts/hollywood_p1_review.yaml`（min_mean 34 / min_item_mean 2.01 / max_rounds 3 / judges 3），`review_passed` 读 cfg；代码里的 `cfg.get("min_mean", 34)` 等是兜底默认值，重复了一份数字（P2）。

**P1-H4 · 测试与报告不符 + 覆盖缺口**
- 当前 2 条红（见"实跑"）。
- `test_no_p2_packet_before_p1_approved` 对失败分支（raise）和放行分支都测了 ✅；`test_packets_have_no_advance_cmd_and_cli_logs` 断言 tools/script_rsi/*.py 无 "advance_cmd" ✅，但没查 `tools/autopilot/flow.py`（它还在读 advance_cmd）；`test_pending_done_detection` 用绝对路径（`ROOT / 绝对路径` 恰好等于绝对路径）才过，生产写的是相对路径（H.RC._rel），没测到真实分支；没有任何用例测 watch 并发 / 跨进程锁 / autopilot tick 与 watch 互斥。
- `ep_gate` 的整集返修包（autoflow_agent.py:336-344）直接 `AF.write_json`，不走 `packet()`，守卫（和将来任何包级规则）管不到它——步名 revise 在白名单里所以今天不出事，但是第二个出包口。

**P1-H5 · autoflow.log 两种内容混写**
- `script_autoflow._spawn` 把子进程 stdout 重定向到 `<run>/autoflow.log`（:58-60），`advance_log` 又往同一文件 append JSON 行。现文件第 1 行是 `cmd_run` print 的整段状态 JSON，不是 advance 记录；按"每行一条推进记录"读会错。

### P2
- 19:17 时间线是否站得住：**结构上站得住**（CLEAN_CUT.json 18:45 → P2_ep01_a1 19:17:06 → owner_gates.json 19:17:57；gates 为空 = P1 从未 approved），新 `enabled()` 对 CLEAN_CUT run 一律生效后这一幕不会重演；但"是谁推的"写错了（见 P0-H1）。
- void 处置：`writer_tasks_void/P2_ep01_a1.json` 已移入（不删 ✅），但文件内仍 `status: open`、无 voided_at / 原因；另一份改名成 `P1_looks_a2.void191758_jsonbug.json`——两种隔离写法。建议统一在包里写 `status: void, voided_at, why`。
- 守护潜在空转：`post_step` 的 not_importable 分支（autoflow_agent.py:572、576）不清 `awaiting`，最后一个补丁产物的 .done 一直在 → `pending_done` 每 30 s 命中一次、每次起一个 `autoflow.py run`。现在没发生（awaiting=None），到 P4 阶段会。
- 其它出包 / 推进路径核对：`story_runs._start` 在 claude_agent 下只写 writer_package.json、不出 writer_task ✅；`story_api.ts` 只改了状态词 ✅；`script_autoflow` 的 /start /repair /gate 都经 `_spawn`（带 --source web）✅；grep `nsfs.writer_task` 只有 autoflow_agent 一个生产者 ✅。
- 第二季旧包 `series10_s2/writer_tasks/*.json` 仍带 advance_cmd（TODO_BOARD I-16 已记）——autopilot tick 对它们照样有效，第二季恢复前要先清。

---

## 第 1 轮 · 11-02 19:30–20:00（OVERSIGHT-F）

### 复核范围
FACTORY（K-OPS-F23–F26、runs.py、资产包模式、preflight I11/I12、decision_check D-V2-01/02/OPS-128、重启去暂停、story-runs 外部 API）；PROMPTFIX（K-REN-957–959、run_paths.py）；HOLLYWOOD（owner_gate / p1_gate / ep_gate / _looks_step / closed_check / script_autoflow /gate /tasks /brief /import、P1 三评委）；UISCRIPT（NewScriptPage / P1Review）；STYLE-V2（tools/v2style）。

### 实跑结果（出处）
- `pytest -q -rs` 13 个测试文件：**177 passed，0 skipped**（test_factory / test_promptfix / test_promptfix_v2 / test_v1_leak / test_system_version / test_owner_gate / test_judge_agent / test_gen_contract / test_current_run / test_looks_table / test_lead_char_id / test_autoflow / test_l123_no_reject_ui）。
- `tools/qa/decision_check.py`：69 条 ✅67 ❌0 ⏳2（D-V2-01 ✅ 只含 lead_f；D-V2-02 ⏳ pending_until IMPORTED；D-OPS-128 ✅）。注意：不带 `-X utf8` 直接跑会 UnicodeEncodeError 崩（cp1252），不是业务问题。
- `tools/qa/arch_scan.py --check`：**FAIL，26 处退化**（见 P2-13）。

### P0（立即退回）

**P0-1 · PROMPTFIX · K-REN-957 规则没写进知识库（和今天 K-REN-956 漏写同一类）**
- 说：K-REN-957–959 已加规则。
- 实际：`knowledge/rules/render_promptfix.yaml` 的 diff 只新增 K-REN-956、958、959；`grep -rn K-REN-957 knowledge/` = 0 条。代码和测试却到处引用它：`services/agent/ns_agent/asset_refs.py:1245,1267,1286,1371`、`frame_job.py:312`（rules 列表里写了 "K-REN-957"）、`framing.py:361`、`gen_contract/preflight.py:208`、`tests/test_promptfix.py:214`。
- 根因模式：规则写了不生效（知识库是规则的唯一来源，缺一条 = 下次编译审计对不上号）。
- 建议：PROMPTFIX 补 K-REN-957（背影 / 远景人物不送正脸 + 景深层次句）到 render_promptfix.yaml，check 指到 test_promptfix.py 对应用例；AUDIT 把"代码引用的 K-* 必须在 knowledge/rules 里存在"做成 arch_scan 一条。

### P1（这轮必须修，不阻断其它人）

**P1-2 · HOLLYWOOD · 19:17 前漏出的 P2 包"没被接走"，但也没作废，仍是 open**
- 问 1）P1 闸门是否真的挡住自动出 P2；漏出的 P2 包是否没被接走。
- 实际：闸门逻辑在（`autoflow_agent.chain_step` 两处 `p1_gate(...)`，`p1_gate` 在 P1 非 approved 时 return False）。V2 run 当前 `autoflow_ep01.json` verdict=awaiting_writer（三评委 27.33<34 已出 P1 第 2 稿），P2 stage 标成 held_by_p1_gate。**确实没被接走**：`writer_out/` 下没有 P2_ep01_a1.json/.done。
- 但：`data/pipeline/runs/series10_v2/writer_tasks/P2_ep01_a1.json` 仍 `status: open`（created 19:17:06，闸门 19:17:57 才 enable），它依据的 P1 已被改名为 `P1_storyline.v192546.json`（19:25 返修时）。`writer_tasks_void/` 里只有 P1_looks_a2.json，P2 没进 void。`GET /api/script-autoflow/{run}/tasks` 把它列成 answered=false 的待写包（`script_autoflow.py:139`）。若任何写手把它写回，P1 一 approve，`chain_step` 对 P1-P2 的 attempts==1 直接 `ready()` 收稿——收的是基于旧 P1 的大纲。
- 建议：HOLLYWOOD 把 P2_ep01_a1.json 移到 writer_tasks_void（不删）；p1_gate 在 revise 时顺手把下游 open 包一起 void；/tasks 对 held 的包标 held，不列为待写。

**P1-3 · FACTORY · K-OPS-F26"不解别人的暂停"读错 control 文件，V2 当 primary 时无效**
- 说：system_version.server_pause_owner / restart_queue.pre_paused 先读服务器 control，已加规则 F26 + 测试 test_a09。
- 实际：两处都写死 `data/producer/control.json`（`tools/qa/system_version.py:922`、`tools/autopilot/restart_queue.py` 新增 pre_paused `cat {rs.R}/data/producer/control.json`）。而 producer 的 control 路径按 F24 分剧：`tools/autopilot/producer.py:550` 非 legacy 剧 = `data/producer/runs/<run>/control.json`；primary 现在是 series10_v2。于是读到的是 V1（已归档）的 control，不是正在跑的主剧。`tests/test_system_version.py:376-378` 用 `_FakeRS.ctrl` 假字符串，测不到路径。另外 K-OPS-F20（`producer.py:1881`）说暂停唯一来源是 runs.json status，这两处只看 control.paused_by，又是第二个入口。
- 根因模式：同一事实两个入口；规则写了不生效。
- 建议：FACTORY 改成 `runs.producer_dir(run, root)/control.json`（经 runs.py 唯一入口），并把 runs.json status≠producing 也算"别人暂停"；测试断言路径。

**P1-4 · CUTEDIT/FACTORY · tools/assemble_series.py 一半 V2 一半 V1（L-126 漏点）**
- 实际：`tools/assemble_series.py:38-41` RUN_ID=`RUNS.primary_run()`（= series10_v2），但 `:139` 仍 `json.loads((ROOT / "data/import/script_v2.json")...)` 读 V1 导入稿；今天该文件改了 compose()（CUTEDIT 对齐）却没动这一行。V2 一旦装配，拿 V2 的 state 配 V1 的镜表。
- 建议：改为 `RUNS.script_path(RUN_ID)`；arch_scan hard_import_path 对 tools/ 也要算（它现在 138 处只是计数、不算退化）。

**P1-5 · UISCRIPT/HOLLYWOOD · 新建剧本页不传 clean_cut，/brief 默认 False → 从页面新建的剧不是"完全切割"**
- 实际：`services/api/ns_api/script_autoflow.py` BriefBody `clean_cut: bool = False`；`grep -rn clean_cut apps/web/src` = 0 条，`NewScriptPage.tsx` 的 brief body 不含该字段。series10_v2 的 CLEAN_CUT.json 是 18:45 手工放的。下一部从页面建的剧，写作包会带旧剧人物 / 场景表（`autoflow_agent.run` 只在 clean_cut 时清 rc/rs）。
- 建议：V2 起 /brief 默认 clean_cut=True（或页面显式传 true）；test_owner_gate 的 brief 用例去掉 `clean_cut=True` 参数后应仍为 clean。

### P2（记录，下轮跟）

**P2-6 · PROMPTFIX · preflight I11/I12/I13 对"没有 project 的作业"是 na（放行）**
- `preflight.py` 新增段：`proj = req.get("framing_project") or req.get("project")`；`if proj and manifest_rel(proj)` 才判，否则 `add("I11","na",...)`。`unified_frame.py:67/222` 用 `job.get("framing_project")`；`tools/poster/gen.py:72`、`tools/pipeline/image_jobs.py:263` 等走 contract_request，是否带 project 未逐一核。V2 期间"没 project"应按当前剧判，不应 na。

**P2-7 · 全体 · runs.py 的加载器复制了 9 份，口径已开始漂**
- `grep` 到 9 个文件各自 `spec_from_file_location(... tools/autopilot/runs.py)`：ns_agent/run_paths、ns_api/run_paths、gen_contract/preflight（两处）、vqa/continuity、ns_render/pipeline、tools/factory/inbox、tools/gen_contract/remote_score、tools/promptfix/compile_sha、tools/qa/arch_scan。只有 `ns_agent/run_paths._ctx` 认 `NS_RUN`；`ns_api/run_paths` 不认；`tools/qa/decision_check._current_primary` 直接读 runs.json、绕过 `NS_PRIMARY_RUN`。多剧并行时 agent 侧和 API 侧会解析到不同剧。
- 建议：一个公共 `ns_runs()` 加载器 + 一个 `current_run()`，其它全调它。

**P2-8 · HOLLYWOOD · lead_f 造型清单三个来源**
- `tools/script_rsi/looks_table.py:119-142` closed_check 读 `assets_v2/owner_inputs.json`；`asset_refs.face_of/manifest` 读 `assets_v2/manifest.json`；`looks_table.py:65-67` 还写死 `LEAD_LOOKS=("O1".."O4")`。今天三者一致（都 O1–O4 / SH1 SH2 / J1 J2），改一处就会裂。K-OPS-F23 说 V2 只认 manifest.json。

**P2-9 · HOLLYWOOD · 评审口径有一处放宽 + 状态文件被手改**
- `config/prompts/hollywood_p1_review.yaml` `require_stable: false`（注释"总调度 20:xx 口径不含 σ"），代码 `review_passed` 原本有 σ≤1 判据，现在只记录。评委独立性：三家 judge_id J1-fable / J2-opus / J3-sonnet 不同、各自目录、无证据条目记 1 分（`judge_agent.p1_collect`），均分 27.33 未过、已出 P1 第 2 稿——流程正确；但 judge_id 是自报的，没法从文件证明模型不同。
- `judge_p1/STATE.json` 里 `"packed_at": "2026-11-02T19:5x"`、`extra_fixes`/`extra_by` 是手工写入（代码只写 strftime）。手改机器状态文件以后没法区分"系统判的"和"人加的"。
- 请总调度确认 σ 放宽是你定的；建议 extra_fixes 走单独文件。

**P2-10 · 测试改动核对**
- 未发现删断言 / 改失败为跳过。`test_promptfix.py` 删了两个 `pytest.skip`（现在真跑）；`test_vqagate.test_continuity_prev_same_scene` 改为 monkeypatch 钉 V1 路径；`test_factory:212`、`test_story_runs_uirsi:289/292` 是跟着接口改断言。
- 唯一软点：`tests/test_ui_no_tech_words_assetux.py` 新增 `@pytest.mark.xfail(strict=False)` 的 `test_status_ts_fully_plain`（status.ts 还有"已打回""契约全过""Q9"），这是把没做完的事标成预期失败——要有工单跟。
- `tests/test_owner_gate.py:51-54` 闸门接线测试是源码字符串断言（`ag.count("p1_gate(...)") == 2`），不是行为测试；P1 挡 P2 的行为没有用例。

**P2-11 · HOLLYWOOD/UISCRIPT · 闸门接口和"不让项目方打字"**
- `/gate` 的 `by` 由前端传、默认"项目方"（`GateBody.by="项目方"`），P1Review.tsx 不传；写审计靠中间件。`owner_gate.act` 要求"修改"必须有一句话（`ValueError("“修改”要写一句话")`），前端按钮 disabled 直到输入。和记忆"登录即本人·一键确认、不让项目方打字"有张力——建议"修改"给点选项（选择题）+ 可选原话。
- 2）"先收下再异步"：✅ `script_autoflow.gate` 先 `_og().act()` 落盘再 `_spawn`，正在跑时只记下。

**P2-12 · FACTORY · story-runs 外部 API 修复 ✅，但其它外部写作口没按 writer_backend 挡**
- ✅ `story_runs._start` 开头 `if writer_backend()=="claude_agent": _hand_to_agent(); return`，三个调用点（:399/:555/:571）都经 `_start`；`config/llm_providers.json writer_backend="claude_agent"`。
- 仍会调外部文本 API 的：`ns_api/script_chat.py:392`（/chat/completions）、`ns_api/prompt_rewrite.py`（用途 prompt_rewrite）、`ns_api/edits.py:493 call_llm`。都不是图片（不违 K-REV-V01），但 L-109 测试期花钱。V2 页面若能到这些入口要挡。

**P2-13 · 全体 · arch_scan --check FAIL（26 处退化）**
- 14 处 untracked_code（新文件未入版，提交后消）；2 处 untracked_imported（run_paths.py 被 asset_revs/bible/compiler、assets/character_hub/cut_project 引用但没入版）。
- STYLE-V2 实打实的：`tools/v2style/camera_ab.py` def_ssh 1 / no_timeout 1 / hard_path 6；`grade_ab.py` def_ssh 1 / no_timeout 3 / hard_path 4；`voice_v2.py` hard_path 6 / nonatomic_json 1；`bgm_theme_worker.py` nonatomic_json 1；`looks.py` no_timeout 1。sv-15 发版前要清零。

**P2-14 · UISCRIPT/FACTORY · 笔记本上两个 ns_api 实例**
- 进程表：uvicorn :8800（19:25:12，正式）+ uvicorn :8811（19:26:46，`apps/web/vite.uiscript_tmp.config.ts` 指向它）。同一份代码两套进程读写同一 data/，闸门 / 任务状态可能被两边各自缓存。`producer.py serve` 两行是 py 启动器 + 子进程，不是重复。
- 建议：UISCRIPT 用完 8811 即停；FACTORY 去重脚本按端口认。

**P2-15 · FACTORY · 文档漂移**
- `tools/autopilot/runs.py:7-11` 模块注释仍写"primary 一律保持旧路径……primary 不加前缀"，与 K-OPS-F24 相反；读代码的人会按旧口径理解。
- `autoflow_ep01.json` 里 P1G 段 status=awaiting_owner、P1R 段 revise_requested 同时存在（/tasks 原样返回），网页若按 P1G 显示会误导。P1Review.tsx 的 canOwnerAct 已排除此情况，但数据本身该改。

### ✅ 核对通过（有出处）
- K-OPS-F23/F24/F25/F26 四条都在 `knowledge/rules/ops_factory.yaml` 新增段，check 指向的测试都存在且通过。
- `config/factory/hosts.json` gpu33 / gpu36 / laptop `owner_controlled: true`；`tools/factory/hosts.py owner_lane` 没道 / 认不出 = False（失败关闭）。
- producer：`adult_shot_ids` + `owner_trigger_ids` 未触发不派（diff :162-163、:247-250）；route=local_only 非自有道 raise（:172-173）。
- preflight 新增 I11（清单 sha）/ I12（道）/ I13（品牌词）；I2 在资产包模式下清单无脸 = fail，不退旧脸（`preflight.py` manifest_missing_faces、stale_face_slots 新分支）。
- `asset_refs.face_of`：manifest_rel 有值只读清单、不读 face_overrides / faces（:891-897）。
- V2 写作包无 V1 内容：P2_ep01_a1.json、P1_a2.json 里 grep 林晚|顾沉|lin_wan|gu_chen|series10_v1|阿岚 = 0。
- runs.json：primary=series10_v2（preparing）、legacy_unprefixed_run=series10_v1（archived）、assets_manifest=assets_v2/manifest.json；manifest 只有 lead_f（looks O1–O4 looks_closed=true，items SH1/SH2/J1/J2）。
- STYLE-V2 候选只用 `assets_v2/characters/lead_f/face/lead_f_face_v1.png` + `outfits/outfit_trench_coat.png`（`grade_ab.py:38-39`、`camera_ab.py:36`），`grep lin_wan|series10_v1|data/looks|identity_refs tools/v2style` = 0。但路径写死、没经 manifest sha 核对（K-OPS-F23 口径），归 P2-13 一起改。
- `tests/conftest.py` 钉 `NS_PRIMARY_RUN=series10_v1`，只对真实仓库生效（`runs.primary_run:58-60`），tmp 目录测试读自己的登记表。
- L-123：P1Review.tsx 只有"用这版 / 修改"两个按钮；`owner_gate.act` 拒绝 reject。web 其余"打回 / 驳回"字样在反馈工单（FeedbackLayer）与 V1 旧页（EditCenter / SeasonPeek），不是今天改的。

### 给总调度的问题（需你定）
1. P2-9：`require_stable: false`（σ 不拦）是不是你定的？
2. P2-11："修改"必须打一句话 vs"不让项目方打字"，按哪条？
