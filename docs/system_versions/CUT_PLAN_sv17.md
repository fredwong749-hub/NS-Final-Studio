# CUT_PLAN sv17：把未提交的工作树分批入版

- 写于 11-03 04:5x（本机 +09:00）。来自派单 T4 · OPS-RELEASE（task_c0c5da094ac2），对应 ISS-1103-033742-7564
- 基线：HEAD = 1d2cc20（sv-20261102-16）。`git status --porcelain -uall` 在 03:50 是 320 条，04:30 涨到 344 条，工作树还在长
- 本文件只给方案，**没有执行 cut**，cut 由总调度跑 `tools/qa/system_version.py cut`。下面所有核验都用临时 GIT_INDEX_FILE 拼树、git archive 出快照，没碰仓库的 index 和 HEAD

## 0. 结论（先看这里）

1. **cut A = G1 harness（47 个）可以单独发**。它的冻结树（HEAD + G1）已核：syntax_guard PASS（894 个文件）；cut 会挑出的定向测试 85 过 2 红，2 红都和分批无关（§3 #1、#2）。补进来的 quarantine_* 那几个文件，在快照上重跑相关测试 24/24 过
2. **其余代码不能按模块一刀刀切**。实测 G2（写作链）单独拼树，syntax_guard 能过，但定向测试里有一批红是因为它真的依赖后面几批的改动（§2 表）。G3 依赖 G4 的情况更严重（asset_worker 要用 gen_contract.style.EMPTY_SUFFIX、preflight.ASSET_STAGE_WAIVE、gen_contract.accept）。所以建议：
   - **cut B = G2–G7 一次发**（≈294 个文件）。G2–G7 只当**审核分组**用：每组由负责人对着清单确认“已审 / 留到 sv18”，没审过的文件从 cut B 的清单里拿掉，不用拆成多次 cut
   - 一定要再细分的话，只有一种拆法已核到 syntax_guard 层面能过：**G1+G2+G3 合成一版**（冻结树 syntax_guard PASS 936 个文件）。但 G2 的测试还会因为缺 producer.py / autoflow_resident.py 的改动而红，要把 §2 表里列的文件一起带上，再跑 cut --dry
3. **部署（deploy --verify）放到 cut B 之后**。cut A 只入 git。它在服务器上能跑，但不带 G3 时 sop_gate 的资产就绪阶段读不到 asset_jobs 产物，意义不大

## 1. 怎么拼树发版（用 cut 现有的 --tree）

```bash
export GIT_INDEX_FILE=/tmp/nsfs_cutA.idx; rm -f $GIT_INDEX_FILE
git read-tree HEAD                                  # cut B 时改成 read-tree <cut A 的 sv tag>
xargs -a LIST_G1.txt git add --                      # LIST = 下面 §4 的清单（cut B = G2..G7 拼起来）
T=$(git write-tree); unset GIT_INDEX_FILE
.venv/Scripts/python.exe tools/qa/system_version.py cut --dry --tree $T
.venv/Scripts/python.exe tools/qa/system_version.py cut --tree $T
```

- `--tree` 跳过“60 秒安静”预冻结，闸门（syntax_guard / compile --check / decision_check / decision_propagation / pick_tests 定向 pytest）跑在这棵树的快照上，cut 期间别人新改的文件不会混进来
- 清单是 04:3x 的状态。cut 前重跑 `git status --porcelain -uall`，新冒出来的文件按 §4 每组开头的“归组规则”放进对应组，不确定的留到 sv18
- vendor/_eval/{OpenCut,omniclip,openreel-video} 不进版：子模块只是 `-dirty`，提交号没变

## 2. 分批实测查出的跨组依赖（G2 单独拼树时，真实工作树上过、快照上红的测试）

| G2 的测试 | 快照上的报错 | 依赖的文件（所在组） |
|---|---|---|
| test_rules_v3 ×60、test_director 等（第 1 轮） | `camera_norm.is_enabled() takes 1 positional argument`（validate_qwen_script.motion_move 传 run / motion） | services/agent/ns_agent/camera_norm.py → **已挪进 G2** |
| test_v1_leak、test_merge_ops_o（第 1 轮） | `ns_api.script_chat has no attribute assert_no_v1 / run_for_dir` | services/api/ns_api/script_chat.py → **已挪进 G2** |
| test_owner_gate::test_run_import_path_only_own_run_dir | `producer has no attribute run_import_path_ok` | tools/autopilot/producer.py（G6） |
| test_promptfix::test_v2_primary_run_imports_run_scoped | `producer has no attribute run_scoped_import` | tools/autopilot/producer.py（G6） |
| test_promptfix::test_approve_triggers_placeholder_fill | `KeyError: 'fill_note'` | 待查（G3 / G5 的 API） |
| test_acting_beats::test_resident_spawns_next_episode | `autoflow_resident has no attribute asset_tick` | tools/factory/autoflow_resident.py（G3） |
| test_hollywood_r5::test_fb0007_partial_woman_no_wardrobe_on_man | `assert None == ['neck']` | 待查（G3 出图编译） |
| test_h3_prompt::test_rules_same_as_lab_copy | 规则副本不一致 | 待查（G3 / G4） |
| test_rules_v3::test_episode_head_rules | QW-E6b 判定变了 | 待查 |

还有约 15 条红，是因为快照里没有 data/（FileNotFoundError、场景底图 sha、`'林晚' in []`）。真 cut 的快照会把 data/ 硬链接进去，这些不算。

G3 单独拼树（在 G1+G2 之上）：syntax_guard **FAIL**（asset_worker.py:739 `from ns_agent.gen_contract import accept`，accept.py 03:57 才新建）。补上 accept.py 以后测试 42 红，主要是 `gen_contract.style.EMPTY_SUFFIX` ×15、`preflight.ASSET_STAGE_WAIVE`、`cast_table` 新属性。所以 asset_jobs 和出图编译已经合成 G3。

## 3. 卡 cut 的已知问题（各自负责人修，本单不越界）

| # | 问题 | 证据 | 负责人 |
|---|---|---|---|
| 1 | `tests/test_system_version.py::test_verified_install_refuses_truncated_stdin` 在本机**必红**，而且它是 SMOKE，每次 cut 都跑。原因：`shutil.which("bash")` 拿到 `C:\Windows\System32\bash.exe`（WSL），收到的是 `C:/Users/.../pytest-of-fredw/...` 这种 Windows 路径，`cat >` 写不进去，returncode=1。测试和 `_verified_install` 相对 HEAD 都没改 | 真实工作树重跑 `pytest tests/test_system_version.py -k truncated` → 1 failed；`where bash` 只有 System32 和 WindowsApps 两个 WSL 入口 | 总调度 / MERGE-OPS-O（system_version 归属）：测试把路径转成 /mnt/c 形式，或在没有 POSIX bash 时 skip |
| 2 | `tests/test_sv_verify_lock.py::test_locks_md_active_then_inactive` 只在我的模拟快照里红（real_data_guard：写 snap/data/system_versions） | 真实工作树 11 passed。模拟快照放在 \\wsl.localhost 下、没有硬链接 data/。**不算问题**，cut --dry 时看一眼就行 | — |
| 3 | `tests/test_owner_gate.py::test_owner_revise_in_direction_marks_took_over_via_gate` 在真实工作树上红：`HeaderMissing: 剧 took1 的P1 作业包里有旧剧内容：sk_white_cyc（L-126；词表 config/v1_guard.json）`。夹具用了 V1 场景 id，新的 v1_guard 把它挡了 | 真实工作树 G2 定向测试 527 过 2 红（另一条是 #1） | CODER-PS / HEADER-O（v1_guard 与夹具）。按 K-OPS-C02，夹具改成不带 V1 场景名，测试不删 |
| 4 | `tests/test_asset_pipeline.py::test_pending_job_left_with_passed_candidates_is_salvaged` 在真实工作树上红：`'done' == 'awaiting_pick'` | 真实工作树 G3 定向测试 113 过 1 红 | AUTOPIPE-A |
| 5 | push_check 默认档（tier 2）FAIL，见 §5 | — | CODER-PS |
| 6 | golden_worker.py / test_golden_pipeline.py 在 03:50 前后又被移回 `data/_quarantine_20261103_golden_o/`（ISS-1103-033325-9b07），不在任何一组里 | 04:0x `ls tools/pipeline/golden_worker.py` → 不存在 | GOLDEN-O / AUTOPIPE-A：还原并过测试后放进 G3 或 sv18 |
| 7 | config/render_quality.json 里 L-147（auto_final_on_lock_runs）的注释写“项目方 11-03 05:0x”，比本机时间晚约 1 小时 | final_tier.py docstring 同样写法 | 总调度入账前核一下（和 ISS-1103-032439-9dff 同类） |
| 8 | config/recipes/asset_refs.json `looks_file` 03:18 的改动没说明（ISS-1103-032336-3aff） | — | MERGE-IMG-O，G3 审核时说清楚 |

## 4. 分组清单

归组规则（新文件按这个放）：G1 = tools/master/{sop_gate,master_check,report_issue,pending_requests,episode_retro,episode_metrics}、tools/qa/*、docs/**、tests/conftest.py；G2 = tools/script_rsi/*、agent_dispatcher、写作 / 派单 prompts 与规则、ns_recipes、导入器、camera_norm、ns_api/script_chat；G3 = tools/pipeline/asset_*·hollywood_tick·vlm_pool、episode_ready、autoflow_resident、owner_pick / owner_delegate / instance / look_confirm、run_media、services/agent/**、services/render_router/**、tools/gen_contract|promptfix|assetmaster|imgfix|vqa/*、出图 / 看图 config；G4 = tools/series10_video|bgm|v2style|voice10|vidlab/*、services/post/*；G5 = services/api/*（上面没点名的）、apps/web/**；G6 = tools/autopilot|factory|sentinel|netfix|monitor|debug|uirsi/*、ops/**、config/pipeline/runs.json·producer.json、config/policies/*；G7 = config/owner_decisions.yaml、knowledge/generated/index.json。

- **G1 的 tests/conftest.py**：把派人请求的 inbox 改写到临时目录（NSFS_INBOX_DIR），G2 写作链的测试要靠它。它同时给 `final_tier.auto_final_on_lock` 的替身加了 run 参数，这个参数在 G3 才有。不过替身只在测试显式传 path 时才调原函数，G1 的定向测试都不传，实测不受影响
- **G1 不含 test_sop_gate.py**：它第 173 行会去读 asset_worker.py 源码里的 `sop.require(`，放在 G3
- **G3 里有 run_media 和 4 个 ns_api 新文件**（owner_pick / owner_delegate / instance / look_confirm）：asset_jobs、asset_worker、episode_ready 直接 import 它们。app.py 顶层 import 了 instance / owner_inbox / owner_pick / pipeline_status，所以 app.py 留在 G5，但不能比 G3 先进
- **G6 的 config/pipeline/runs.json** 是开关，归总调度。进版的值等于当时的运行状态，总调度确认后再放进来
- **G7 owner_decisions.yaml 放最后**：新加的检查（D-PRM-141 要 lint.py 里有 RL-T9，D-V2-14x 要 PLAN 文档）依赖 G1 / G2。cut A 跑的是 HEAD 版决定表。cut A `--dry` 时如果 decision_check 报 ❌，就把这个文件提前到 cut A
- G5 前端不在 pytest 里，cut B 前补跑一次前端 build / tsc

**cut A 的定向测试**（pick_tests 在 G1 冻结树上的实际结果）：test_decision_propagation、test_defect_hunt、test_episode_metrics、test_episode_retro_master_check、test_iter_gate、test_push_check、test_quarantine_refcheck、test_sv_verify_lock、test_syntax_guard、test_system_version（另外手动跑了 test_quarantine_code_guard）

**cut B 的定向测试**：数量很大（G2 一组就 37 个测试文件、529 条）。真实工作树上 G2 定向是 527 过 2 红（§3 #1、#3），G3 资产组定向是 113 过 1 红（§3 #4）。G4–G6 没逐组跑，交给 cut --dry。

### G1 harness（cut A）（47 + 6 = 53 个；W11 11-03 调整见下）

**W11（A-G1 第 22 轮 P0 ②③）对 G1 的调整**：
- **补入 `tools/autopilot/runs.py`**（从 G6 挪来）：G1 的 sop_gate probe-prompts / promote --apply、defect_hunt 入口要用它新增的 RUN_ENV_KEYS / run_env / set_status / gate_legacy_tool，HEAD 版没有 → AttributeError。diff 是纯新增，不改旧函数
- **补入 `tools/qa/decision_propagation.py` + `tests/test_decision_propagation.py`**：日志型流水（docs/master/V2_LIVE.md、CHANNEL.md）不做 stale 扫描（LOG_STREAMS，理由写在文件头；propagate 里点名的照样查），修 D-VQA-01 ❌10
- **补入 `tests/test_sop_gate_promote.py`**（新）：promote auto=false 只报告 / auto=true 写 runs.json + status_history、整集预览目录按 run、master_check ④ sop_gate.enabled
- **补入 `docs/master/AUDIT_A6_W6_ASSET_SHEET_20261103.md`**：本清单之后新冒出的 docs，按归组规则进 G1
- **`config/owner_decisions.yaml` 不整份进 G1，进的是“HEAD + D-CLN-05 钉 run: series10_v1”这一处**（git hash-object 写 blob，`update-index --cacheinfo` 放进临时索引，相当于 `git add -p` 只取这一块）。原因（W11 实跑 tree 5ac07ee8，带整份工作树决策表 + lint.py + asset_worker.json）：decision_check ❌12（D-V2-129～139 要 camera_moves.yaml / run_style.json / music_v2.json / voices_v2.json / hollywood_writer.md / app.py / owner_delegate.json / import_script.py / dispatch.py / agent_dispatcher.json / asset_jobs.py，分属 G2–G6），且 lint.py 在 G1 树上 syntax_guard E4（`from ns_schema.shot_spec import ALIGN_TOL_S`，shot_spec.py 不在 G1）。决策表其余新增检查随 cut B（G7）一起进
- **A-G1 建议的 `services/recipes/ns_recipes/lint.py`、`config/pipeline/asset_worker.json` 因此不进 G1**：它们只被 D-PRM-141 / D-V2-140 引用，这两条检查不在 G1 版决策表里；lint.py 进 G1 反而把 syntax_guard 打红
- D-VQA-01 不再在决策表里 stale_allow V2_LIVE.md（工作树上已撤这一项，改由 LOG_STREAMS 统一处理）

**W11 实跑结果（11-03 05:4x）**：tree `9741c3bec6bc0e8a606e9535004631f850ff5200`（HEAD 1d2cc20 + 上面 53 项）`cut --dry --tree` 七道闸门全绿，ok=true、退出码 0：

```
{
 "id": "sv-20261103-01",
 "prev": "sv-20261102-16",
 "tree_given": true,
 "tree": "9741c3bec6bc0e8a606e9535004631f850ff5200",
 "snapshot": {
  "dir": "D:\\nsfs_cut_snapshots\\sv-20261103-01",
  "files": 2786,
  "linked": 63756
 },
 "frozen_files": 53,
 "ok": true,
 "dry": true,
 "changed": 53,
 "loops": ""
}
  ✅ 全仓语法守卫（K-OPS-C01）：syntax_guard PASS：896 个文件，0 个有错，2.51 秒
  ✅ 知识库 compile --check：OK kb-20261102-46175d5f：660 条规则，一致性检查通过，生成物最新
  ✅ arch_scan --check（K-OPS-S01 棘轮）：  untracked_imported 0 ⏎ ARCH_SCAN PASS （0 处退化）
  ✅ VQA 回归集（K-REV-V19）：WARNING: Logging before InitGoogle() is written to STDERR ⏎ W0000 00:00:1793652051.501808   51936 inference_feedback_manager.cc:121] Feedback manager requires a model with a single signature inference
  ✅ decision_check（0 ❌，⏳ 可以）：合计 69：✅ 67  ❌ 0  ⏳ 2
  ✅ decision_propagation（K-OPS-D02）：决定原文已省略（避免 decision_propagation 把日志摘录当旧口径；总调度 05:5x）
  ✅ 定向 pytest（13 个文件：改动涉及 + smoke）：1 failed, 117 passed in 72.46s (0:01:12) ⏎ 串行重跑通过：tests/test_story_runs_uirsi.py::test_one_at_a_time ⏎ 并行偶发、串行通过：['tests/test_story_runs_uirsi.py::test_one_at_a_time']
EXIT=0
```
- 定向 pytest 里 test_story_runs_uirsi::test_one_at_a_time 并行偶发红、串行重跑过（cut 自带的重跑规则判过）；test_system_version 的 truncated_stdin 在本机走 Git bash 真跑通过（只有 WSL 入口 bash 时才 skip 并写明原因）
- 中间两轮（留作对照）：tree 5ac07ee8（整份工作树决策表 + lint.py + asset_worker.json）syntax_guard E4 + decision_check ❌12；tree 0eddc6fd pytest 4 红（sop_gate 引用的 run_ctx.py 是 G4 未跟踪新文件 → 改成“有就用、没有退回同一规则”）

拼树（在 §1 方法上多一步）：
```bash
git show HEAD:config/owner_decisions.yaml > od_g1.yaml   # 再只加 D-CLN-05 的 title 与 `run: series10_v1` 两行（同工作树）
B=$(git hash-object -w od_g1.yaml)
git read-tree HEAD; xargs -a LIST_G1.txt git add --; git update-index --cacheinfo 100644,$B,config/owner_decisions.yaml; T=$(git write-tree)
```

```
config/pipeline/sop_gate.json
docs/CHANGELOG_AGENTS.md
docs/master/CHANNEL.md
docs/master/DECISION_AUTOPIPE_20261103.md
docs/master/DEPLOY_V2_PRODUCER.md
docs/master/MASTER_PICTURE.md
docs/master/MASTER_SELF_AUDIT_20261103.md
docs/master/METRICS_SPEC.md
docs/master/OVERSIGHT_LOG.md
docs/master/OWNER_CANON.md
docs/master/PIPELINE_SOP_V2.md
docs/master/PLAN_V2_MASTER.md
docs/master/RETRO_ep01.md
docs/master/REVIEW_GLOBAL_FABLE.md
docs/master/REVIEW_GLOBAL_OPUS.md
docs/master/SCORECARD.md
docs/master/SLO.md
docs/master/TODO_BOARD.md
docs/master/V1_TO_V2_CARRYOVER.md
docs/master/V2_LIVE.md
docs/master/V2_SYSTEM_LOSS_AUDIT.md
docs/master/V2_WALK_AUDIT.md
docs/overnight/morning_20261102.md
docs/overnight/morning_20261103.md
docs/system_versions/CUT_PLAN_sv17.md
docs/system_versions/INDEX.md
docs/uimaster/LOCKS.md
docs/uimaster/NAVFLOW_BEFORE.md
tests/conftest.py
tests/test_episode_metrics.py
tests/test_episode_retro_master_check.py
tests/test_quarantine_code_guard.py
tests/test_sv_verify_lock.py
tests/test_system_version.py
tools/master/episode_metrics.py
tools/master/episode_retro.py
tools/master/master_check.py
tools/master/pending_requests.py
tools/master/report_issue.py
tools/master/sop_gate.py
tools/qa/data_parity.py
tools/qa/decision_check.py
tools/qa/defect_hunt.py
tools/qa/quarantine_move.py
tools/qa/quarantine_refcheck.py
tools/qa/quarantine_safe_move.py
tools/qa/system_version.py
tools/autopilot/runs.py
tools/qa/decision_propagation.py
tests/test_decision_propagation.py
tests/test_sop_gate_promote.py
docs/master/AUDIT_A6_W6_ASSET_SHEET_20261103.md
```
（config/owner_decisions.yaml 的 D-CLN-05 一块另按上面 update-index 放入，不在 xargs 清单里）

### G2 写作链 autoflow / 派单器（70 个）

```
config/director/camera_moves.yaml
config/director/shot_spec_v2.yaml
config/pipeline/agent_dispatcher.json
config/pipeline/chain.yaml
config/pipeline/examples/P4_episode.md
config/prompts/dispatch_reviewer.md
config/prompts/dispatch_writer.md
config/prompts/hollywood_facts.md
config/prompts/hollywood_judge.md
config/prompts/hollywood_writer.md
config/qwen_writer_system_prompt.txt
config/recipes/director_system_prompt.md
config/recipes/timing_lint.json
config/recipes/writer_knowledge.md
config/script_chat.json
config/script_chat_rules.md
config/script_chat_rules_appendix.md
config/script_chat_runs/series10_v1.md
config/script_chat_runs/series10_v1_appendix.md
config/v1_guard.json
knowledge/rules/director.yaml
knowledge/rules/writer_hollywood.yaml
knowledge/rules/writer_iteration.yaml
knowledge/rules/writer_series10.yaml
packages/schema/ns_schema/shot_spec.py
packages/schema/ns_schema/storyline.py
services/agent/ns_agent/camera_norm.py
services/agent/ns_agent/importer/script_md.py
services/api/ns_api/script_chat.py
services/recipes/ns_recipes/acting.py
services/recipes/ns_recipes/compiler.py
services/recipes/ns_recipes/lint.py
services/recipes/ns_recipes/prompt.py
tests/fixtures/l141/ep01_v2_shots.md
tests/test_agent_dispatcher.py
tests/test_director.py
tests/test_epchain_o.py
tests/test_full_p4_adopt.py
tests/test_header_o.py
tests/test_judge_agent.py
tests/test_k211.py
tests/test_l141_migrate.py
tests/test_owner_gate.py
tests/test_patch_exhaust.py
tests/test_prompt_timeline_v2.py
tests/test_qw_c1_vocab.py
tests/test_review_a_p0p1.py
tests/test_rules_v3.py
tests/test_segment_fix.py
tests/test_timeline_o.py
tools/director/cut_plan.py
tools/factory/agent_dispatcher.py
tools/import_script.py
tools/pipeline/attribute_bug.py
tools/pipeline/p4_adapter.py
tools/pipeline/run_chain.py
tools/script_rsi/autoflow.py
tools/script_rsi/autoflow_agent.py
tools/script_rsi/hollywood_r5.py
tools/script_rsi/l141_migrate.py
tools/script_rsi/line3_score.py
tools/script_rsi/narrative_code.py
tools/script_rsi/owner_gate.py
tools/script_rsi/rubric_audit.py
tools/script_rsi/rubric_code.py
tools/script_rsi/scene_lock.py
tools/script_rsi/segment_fix.py
tools/script_rsi/staging.py
tools/script_rsi/v1_leak.py
tools/validate_qwen_script.py
```

### G3 asset_jobs + 出图编译 / 看图（84 个）

```
config/compile/bible_series10_v2.toml
config/compile/run_style.json
config/gen_contract.json
config/pipeline/asset_worker.json
config/pipeline/hollywood_score.json
config/pipeline/owner_delegate.json
config/prompts/vqa_inspect.md
config/recipes/asset_refs.json
config/render_quality.json
config/s2_waivers.json
config/v2style.json
config/voices_v2.json
config/vqa.json
knowledge/rules/prompt.yaml
knowledge/rules/render_promptfix.yaml
packages/qc/ns_qc/provenance.py
services/agent/ns_agent/asset_refs.py
services/agent/ns_agent/bible.py
services/agent/ns_agent/cast_table.py
services/agent/ns_agent/compiler.py
services/agent/ns_agent/frame_job.py
services/agent/ns_agent/frame_spec.py
services/agent/ns_agent/framing.py
services/agent/ns_agent/gen_contract/accept.py
services/agent/ns_agent/gen_contract/cards.py
services/agent/ns_agent/gen_contract/postflight.py
services/agent/ns_agent/gen_contract/preflight.py
services/agent/ns_agent/gen_contract/style.py
services/agent/ns_agent/run_paths.py
services/agent/ns_agent/shot_language.py
services/agent/ns_agent/state_timeline.py
services/agent/ns_agent/vqa/contract.py
services/api/ns_api/instance.py
services/api/ns_api/look_confirm.py
services/api/ns_api/owner_delegate.py
services/api/ns_api/owner_pick.py
services/post/ns_post/run_media.py
services/render_router/ns_render/final_tier.py
services/render_router/ns_render/pipeline.py
services/render_router/ns_render/unified_frame.py
tests/test_adult_nude_context.py
tests/test_asset_pipeline.py
tests/test_asset_worker_sop_backoff.py
tests/test_derived_out.py
tests/test_fix_ep02_owner_1031.py
tests/test_golden_v2_checks.py
tests/test_hollywood_tick.py
tests/test_manifest_look_shoes.py
tests/test_master_sop_tools.py
tests/test_merge_img_o.py
tests/test_owner_delegate.py
tests/test_owner_pick.py
tests/test_promptfix_v2.py
tests/test_sop_gate.py
tests/test_takes_write_entry_sync.py
tests/test_vqagate.py
tests/test_w2_merge_img.py
tools/assetmaster/frames_v2.py
tools/assetmaster/gen_look_sheets.py
tools/assetmaster/look_fix.py
tools/bakeoff/post_local.py
tools/bakeoff/run.py
tools/build_state_timeline.py
tools/factory/autoflow_resident.py
tools/gen_contract/calibrate_imgfix.py
tools/gen_contract/calibrate_q.py
tools/gen_contract/look_audit.py
tools/gen_contract/reflock_page.py
tools/gen_contract/reflock_v9.py
tools/gen_contract/reflock_validate.py
tools/gen_contract/rescore_takes.py
tools/gen_scenes.py
tools/imgfix/lookA_adopt.py
tools/master/episode_ready.py
tools/pipeline/asset_checks.py
tools/pipeline/asset_jobs.py
tools/pipeline/asset_worker.py
tools/pipeline/hollywood_tick.py
tools/pipeline/vlm_pool.py
tools/promptfix/cast_v2.py
tools/promptfix/golden_v2.py
tools/s2_waiver.py
tools/series10_imggen/imgfix_ab.py
tools/vqa/gaze_regression.py
```

### G4 视频 / 后期 / 配音（33 个）

```
config/music_v2.json
config/pipeline/video_policy.json
services/post/ns_post/assemble.py
services/post/ns_post/speakers.py
services/post/ns_post/tts.py
tests/test_bgm.py
tests/test_cuts_v2_compose.py
tests/test_merge_vid_o.py
tests/test_v2_media.py
tests/test_video10_resilience.py
tools/assemble_episode.py
tools/assemble_series.py
tools/bgm/agent.py
tools/bgm/bgm_library.py
tools/bgm/deliver.py
tools/cut_export.py
tools/series10_video/build_jobs.py
tools/series10_video/deploy.py
tools/series10_video/episode_report.py
tools/series10_video/night.py
tools/series10_video/run_ctx.py
tools/series10_video/score_clip.py
tools/series10_video/sync.py
tools/series10_video/upscale_preview.py
tools/series10_video/vidgen.py
tools/v2style/bgm_themes.py
tools/v2style/camera_ab.py
tools/v2style/grade_ab.py
tools/v2style/parallax_bt.py
tools/v2style/voice_distinct.py
tools/v2style/voice_v2.py
tools/vidlab/acting.py
tools/voice10/voice10.py
```

### G5 API + 前端（67 个）

```
apps/web/e2e/uirsi/scene_label.test.mjs
apps/web/src/App.tsx
apps/web/src/projects/Root.tsx
apps/web/src/types.ts
apps/web/src/v3/Canvas.tsx
apps/web/src/v3/EpisodeProduce.tsx
apps/web/src/v3/NavTabs.helpers.ts
apps/web/src/v3/OwnerDecision.helpers.ts
apps/web/src/v3/OwnerDecision.tsx
apps/web/src/v3/PageIntro.tsx
apps/web/src/v3/PipelineMatrix.tsx
apps/web/src/v3/ReviewRow.tsx
apps/web/src/v3/StoryboardTable.tsx
apps/web/src/v3/TopBarV3.tsx
apps/web/src/v3/assets/AssetCenter.tsx
apps/web/src/v3/overview_now.css
apps/web/src/v3/ownerQueue.ts
apps/web/src/v3/ownerqueue.css
apps/web/src/v3/pageMap.ts
apps/web/src/v3/pageintro.css
apps/web/src/v3/pages/AssetsPage.tsx
apps/web/src/v3/pages/AutoflowPanel.tsx
apps/web/src/v3/pages/CutEditor.tsx
apps/web/src/v3/pages/FramesPage.tsx
apps/web/src/v3/pages/ImageEditPage.tsx
apps/web/src/v3/pages/OwnerQueuePage.tsx
apps/web/src/v3/pages/P1Review.tsx
apps/web/src/v3/pages/ProjectSettingsPage.tsx
apps/web/src/v3/pages/SeasonPage.tsx
apps/web/src/v3/pipeline.css
apps/web/src/v3/queueActs.ts
apps/web/src/v3/sceneLabel.pure.ts
apps/web/src/v3/sceneLabel.ts
apps/web/src/v3/stepbar.css
apps/web/src/v3/stepbar.ts
apps/web/src/v3/v3.css
services/api/ns_api/api_snapshot.py
services/api/ns_api/app.py
services/api/ns_api/bgm_api.py
services/api/ns_api/character_hub.py
services/api/ns_api/cut_project.py
services/api/ns_api/cuts.py
services/api/ns_api/frame_jobs.py
services/api/ns_api/owner_gates.py
services/api/ns_api/owner_inbox.py
services/api/ns_api/owner_queue.py
services/api/ns_api/pipeline_status.py
services/api/ns_api/ref_switch.py
services/api/ns_api/ref_switch_assets.py
services/api/ns_api/scene_assets.py
services/api/ns_api/script_autoflow.py
services/api/ns_api/script_library.py
services/api/ns_api/shot_audio.py
services/api/ns_api/sop.py
services/api/ns_api/story_runs.py
services/api/ns_api/trash.py
services/api/ns_api/v2_assets.py
services/api/ns_api/voice_preview.py
services/api/ns_api/wizard.py
tests/test_api_instance.py
tests/test_cutedit_api.py
tests/test_cuts_ux5.py
tests/test_owner_inbox.py
tests/test_pipeline_status.py
tests/test_r43_uirsi.py
tests/test_uifix_f_v2_cut.py
tests/test_v2cut_o.py
```

### G6 常驻 / 哨兵 / 运维 / 开关（37 个；runs.py 已挪进 G1）

```
config/netfix/partition.json
config/pipeline/producer.json
config/pipeline/runs.json
config/policies/gates.yaml
config/policies/sentinel.yaml
knowledge/rules/ops_factory.yaml
knowledge/rules/ops_sentinel.yaml
ops/autostart/laptop_autostart.ps1
ops/offline/merge_pull.py
ops/restart_api.ps1
ops/restart_autoflow.ps1
tests/test_debug_rsi.py
tests/test_distill_flow.py
tests/test_factory.py
tests/test_merge_ops_o.py
tests/test_prodmerge_o.py
tests/test_producer_run_identity.py
tests/test_restart_api_ps1.py
tests/test_sentinel.py
tools/autopilot/episode_pipeline.py
tools/autopilot/flow.py
tools/autopilot/producer.py
tools/autopilot/resident_sync.py
tools/autopilot/roles.py
tools/debug/lanes.py
tools/factory/api_watchdog.py
tools/factory/decisions_guard.py
tools/factory/deps.py
tools/factory/repart.py
tools/iterate_loop/rules.yaml
tools/monitor/v2_live.py
tools/netfix/dispatch.py
tools/sentinel/judges.py
tools/sentinel/probes.py
tools/sentinel/remote_probe.py
tools/sentinel/scorecard.py
tools/uirsi/api_restart_guard.py
```

### G7 决定表 + 编译产物（2 个）

```
config/owner_decisions.yaml
knowledge/generated/index.json
```

## 5. decision_check / decision_propagation（T4 目标 1）

| 时刻 | decision_check | decision_propagation --dry |
|---|---|---|
| 03:01（MERGE-OPS-O 卡点） | 0 ❌ | 退出码 1：D-IMG-01 有 2 处、D-VQA-01 有 4 处没同步 |
| 03:50（本单接手，未改任何文件） | 退出码 0：✅ 86 ❌ 0 ⏳ 1（D-V2-02 等 V2 导入） | 退出码 0：12/12 ✅ |

- 这 6 处是 MERGE-IMG-O 在 03:05–03:22 同步的：render_quality.json `default_preset = "leica_sstar"`（:214）；vqa.json `enforce: true`（:260、:265）；script_chat_rules.md:106 和 appendix:73 改写成“按本剧风格配置 config/compile/run_style.json”
- 核过不是靠放宽口径过的：用 **HEAD 版** owner_decisions.yaml（不带 MERGE-IMG-O 加的 new_terms / stale_allow）对当前树重跑 propagation，仍然 12/12 ✅、退出码 0
- 注意：在 WSL 里直接调 `.venv/Scripts/python.exe tools/qa/decision_check.py`，会因为 cp1252 控制台编码报 UnicodeEncodeError，退出码 1。要带 `PYTHONIOENCODING=utf-8`，并用 `WSLENV=PYTHONIOENCODING` 把它传给 Windows 进程。system_version.cut 自己已经设好了 ENV，cut 闸门不受影响

## 6. push_check / syntax_guard（当前工作树，03:5x）

| 检查 | 结果 | 不过的文件 | 负责人 |
|---|---|---|---|
| syntax_guard | PASS：947 个文件 0 错 | — | — |
| push_check --tier 1 | PASS：906 个文件 13.98 MB，轮次差异 [906, 0] | — | — |
| push_check（默认 tier 2） | **FAIL**：1293 个文件 220.2 MB，轮次差异 [1293, 0]，P2 有 3 条 | `data/pipeline/runs/series10_v2/writer_out/factcheck_ep01_a1.json`、`facts_ep01_a1.json`（内容带 ```json 代码围栏，不是合法 JSON）；`writer_out/P2_ep02_a1.json.done`（0 字节标记） | CODER-PS（写手交稿 / 派单器落盘：落盘前剥掉围栏，或改成 .md 后缀；.done 标记写入内容，或由 push_check 负责人把 `*.done` 列为允许 0 字节） |
| 快照 G1 | syntax_guard PASS（894） | — | — |
| 快照 G1+G2 | syntax_guard PASS（907） | — | — |
| 快照 G1+G2+G3（不含 accept.py 时） | syntax_guard FAIL | asset_worker.py:739 import gen_contract.accept | 已把 accept.py 归入 G3；补上后 G1..G3 PASS（936） |



### G2/G3 补入（REVIEW-G2 P1-2，总调度 10:50 并入）
G2 += tools/script_rsi/hollywood.py、tools/knowledge/compile.py、tests/test_fact_patch_guide.py、packages/schema/ns_schema/h3_lint.py、tools/pipeline/hard_constraints.py；G3 += tests/test_w7_import_followup.py。真 cut B 前按 §4 归组规则再跑一次 `git status --porcelain -uall` 核对。

## 7. cut B 实跑记录（W13 CUTB-PREP，11-03 11:3x–12:5x，Opus 工人；没 commit / tag / push / deploy）

- 清单：`docs/system_versions/LIST_cutB.txt`（349 项，一行一个路径，可直接 `xargs git add`）。= §4 G2–G7 + §G2/G3 补入 + REVIEW-G3（4 项 + hosts.py / hosts.json）+ A-G7（7 项）+ REVIEW-G5/G6 / G4b 补入 + CODER-PS 12:08 交付 + `git status --porcelain -uall` 按归组规则新冒出的（当日 docs、sop_gate.json、ops/*、runs.py、master_check / sop_gate.py、acting_lints / writer_lints / ownership.yaml、lane_heal.py + json + 测试、test_struct_full_rewrite / test_night_v2_finalize / test_story_runs_409 等）。LIST 文件本身被 `.gitignore:87 /docs/**/*.txt` 忽略，不进树
- 不进：仓库根误建的 `series10_v2/`（autoflow.json / autoflow_ep02.json / autoflow.log / work_ep02，06:33，疑似 autoflow 按 cwd 相对路径写盘——没删，留给负责人查）；vendor/_eval、data/、隔离区
- 拼树：§1 方法，临时索引 `C:\Users\fredw\AppData\Local\Temp\nsfs_cutB.idx`，用 Windows git.exe（WSL git 在 /mnt/d 上太慢）
- 第 1 轮 tree `9b0f958763b1cbec0fa4530d712ea62cac8ab7ef`（336 项）`cut --dry`：syntax_guard ✅（963 文件）/ compile --check ✅ / VQA ✅ / decision_check ✅（✅86 ❌0 ⏳1）/ propagation ✅；**arch_scan ❌ 18 处退化**（业务代码 silent_read / nonatomic_json / hard_run / unowned 等，已报总调度 → W15 修到 0，不改基线）；**pytest ❌ 4 failed / 1908 passed**（132 文件）
- pytest 红项定性（快照 -n 12 复跑 5 红）：
  | 测试 | 定性 | 处理 |
  |---|---|---|
  | test_voice10_fix::test_cosy_setup_dry_run | 环境：PATH 的 bash = System32 WSL 入口，读不到 `D:/…` 脚本 → 127 | 同 truncated_stdin 口径：优先 Git bash，只有 WSL 入口才 skip 并写原因；本机 Git bash 真跑 13/13 |
  | test_restart_api_ps1::…preflight_is_not_killed | 时序过严（串行也红）：pwsh 冷启动 + 拿锁比假 API 的 6 s 慢，第一次探针就看到 | 15 s / 30 s / 50 s，断言不变；串行 2/2 过 |
  | test_merge_vid_o::test_build_base_keeps_v2_scoped_camera_move | 数据态陈旧：ep01-S8 重导后运镜句改成句中小写 | 不分大小写替换，仍断言换进去；23/23 |
  | test_v2cut_o::test_ref_switch_only_registered_scenes_for_v2、test_frame_jobs_w2::test_chain_regen_instruct_lock_last_stale | 并行偶发（快照串行过） | 不改，cut 自带串行重跑口径 |
- 按复审另修（只改测试）：test_v2cut_o 3 条（场景库 / 注册表 → “全是本剧登记、不含 V1 id”；造型动作 → 读 look_confirm.episode_state 两态）；test_promptfix_v2 2 条（参考图允许本剧 crop_dir / board_dir = preflight I11 同口径；L-130 比去标记后的 scene_detail）；test_factory a12（Git bash / WSL 入口 skip 口径，本机 Git bash 真跑过）+ resident 用例打桩 asset_tick / dispatch_tick / hollywood_tick（real-data-guard）；test_prodmerge_o:277 改 L-161 口径（fanout 进版关）
- 第 2 轮 tree **`9b1a00a56a87a009f9a8483c9d952d0736663925`**（349 项，含 W15 / W16 / CODER-PS 12:08）12:24 起跑，pytest -n 12 worker 内存压力下僵死 27 分钟，总调度 taskkill；重跑由总调度在机器空出后执行。kill 前六道闸门已全绿：syntax_guard ✅（967 文件）/ compile --check ✅（kb-20261103-2b54fc9c，668 条）/ **arch_scan ✅ 0 处退化** / VQA ✅ / decision_check ✅（✅86 ❌0 ⏳1）/ propagation ✅；pytest 被杀前进度 96%，可见 1 个 F（名字没输出出来，待总调度重跑定性）。cut_lock 12:58 已正常释放（active=false）
- 本节写于 tree 9b1a00a5 之后：按 LIST 重拼会多带本节文档改动，tree hash 随之变
