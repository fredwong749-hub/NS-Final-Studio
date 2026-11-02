# OVERSIGHT_LOG（Fable 独立监督；最新在上）

只审不改。每条：谁 / 说了什么 / 实际是什么 / 证据 / 严重度 / 建议。工作树基线：sv-20261102-14（a2110ad，18:07），之后无提交，148 个文件未提交。

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
