# cut C 预检（A-G3 · Fable，总调度派 msg_6a76aabe14d2）· 11-03 18:18–22:0x · 只 dry 不 cut

- 清单：docs/system_versions/LIST_cutC.txt（114 项 / 22 个归属组 / 1 项不入）；冻结树 `31f837209f109813c706610308ab845f472cc670`（HEAD 44e6c37 + 清单，114 added / 0 removed）
- dry：`cut --dry --tree 31f83720 --report-json data/system_versions/cutC_dry_A-G3.json`，NS_CUT_PYTEST_N=0 串行；18:18 起跑，中间笔记本休眠约 3 小时（21:4x 恢复），21:52 结束 rc=1。快照 D:\nsfs_cut_snapshots\sv-20261103-03（2936 文件 / 64775 链接）
- 守卫：net-guard 拦 0 次；**proc-guard 拦 1 次（见 ⑦）**；real-data-guard 写真实数据 0 次

## 七门逐门

| # | 闸门 | dry 结果 | 复核（22:0x 单独重跑） | 判定 |
|---|---|---|---|---|
| ① | 全仓语法守卫 | ✅ 992 文件 0 错 | — | 过 |
| ② | 知识库 compile --check | ❌ K-OPS-W03（knowledge/rules/asset_ops.yaml:157）证据文件不存在 data/pipeline/runs/series10_v1/video/night.pid | 工作树上 `compile.py --check` = OK（668 条）；night.pid 在工作树存在 | **真 bug（cut C 内部互相打架）**：W22 新增 `LIVE_PID_RE`（system_version.py:929，快照不带 .pid/.lock/心跳）→ 快照里永远没有 night.pid → 该规则的证据校验在每次 cut 都会红。修法二选一：(a) asset_ops.yaml K-OPS-W03 evidence src 改指 `data/pipeline/runs/series10_v1/video/night_state.json`（存在）并把 pid 事实写进 note；(b) compile.py 证据校验对 data/ 路径回退查 ROOT。推荐 (a)，一行 |
| ③ | arch_scan --check（K-OPS-S01 棘轮） | ❌ 超时 600 s | 快照内重跑 1m35s：**FAIL 6 处退化**（工作树重跑 19 处，其中 13 处 untracked_* 入版即消） | 超时 = 休眠环境；**6 处真退化阻断**（下表） |
| ④ | VQA 回归集（K-REV-V19） | ❌ 超时 900 s | 重跑 39 s：PASS 12/12 | 环境（休眠） |
| ⑤ | decision_check | ✅ 87：86 ✅ 0 ❌ 1 ⏳ | — | 过 |
| ⑥ | decision_propagation | ✅ L-092 | — | 过 |
| ⑦ | 定向 pytest（44 文件） | ✅（2 failed → 串行重跑 2 passed；闸门按 flaky 放行）636 passed 1 skipped 636 s | 见下 | 过，但 2 条红要归属 |

## ③ arch_scan 6 处真退化（棘轮不许增，不修不能 cut）

| 退化 | 文件 | 归属 |
|---|---|---|
| silent_read 0→2 | services/agent/ns_agent/vqa/client.py | W23 |
| silent_read 0→1 | services/api/ns_api/owner_delegate.py | W18b / W29 |
| silent_read 0→2 | services/api/ns_api/owner_inbox.py（readonly_items 的 `except Exception: pass` + 坏行 `except ValueError: continue`） | **A-G3（我），改为记 stderr/_warn 即可，下轮 5 分钟** |
| no_timeout 0→1 | tests/test_hermetic_w22.py | W22 |
| no_timeout 0→2 | tests/test_release_auto.py | W17b |
| no_timeout 0→1 | tests/test_w17b_release_p1.py | W17b |

（测试代码只有 no_timeout 进棘轮：subprocess.run/Popen 不带 timeout= 会让 cut 的 pytest 卡死。）

## ⑦ pytest 2 条 FAILED（串行重跑都过）

1. `tests/test_w17b_release_p1.py::test_cli_runner_timeout_kills_whole_tree` — **proc-guard 拦下**：测试走到 system_version._kill_tree（:362-364 `taskkill /PID <pid> /T /F`），而该 pid 的进程树里被 pid 复用"领养"了一个别人的活进程 **47184 = tools/factory/api_watchdog.py --by restart_api**（:8800 的看门狗）；W22 守卫把它拦住并让用例红。重跑时没有 pid 复用就绿。**判定：真 bug，归属 W17（_kill_tree 不核对子进程身份就 /T /F）+ W17b（测试在真实进程上演练 kill）——这就是今天 :8800 / autoflow_resident 两次被"外部 taskkill"的机制（ISS-1103-172328 / 172950）。** 修法：_kill_tree 改为只杀 CreationDate 晚于父进程且 CommandLine 含本次 watched 命令的子进程（或用 Job Object）；测试改用 proc_guard 的桩，不起真进程树。
2. `tests/test_watchdog.py::test_run_registers_dedupes_and_writes_timeline` — `assert d["findings"] == 1` 得 2 + PermissionError（Temp\nsfs_watch_*.out 被另一进程占用）。第一次跑时 ① 的用例刚被拦、留下未关的 watched 输出文件；串行重跑 19 s 过。**判定：被 ① 连带（并发/文件锁偶发），归属 W27/W19，无需单独修；① 修完复测。**

## 结论与建议顺序

- **cut C 现在不能 cut**：② 知识库 1 处、③ 棘轮 6 处为硬阻断；④ 为环境。pytest 过（flaky 放行），但 ⑦-1 是今天 API/常驻被杀的根因，建议和 cut C 一起修而不是放行。
- 先修哪条：**1）W17 `_kill_tree` 身份核对（⑦-1，P0 级安全）→ 2）② K-OPS-W03 证据路径一行 → 3）③ 六处退化各归属 5–15 分钟（我的 owner_inbox 两处可立刻改）→ 4）重跑 dry（NS_CUT_PYTEST_N=0，机器别休眠，约 30 分钟）。**
- 清单两处待总调度确认：producer.py 为 W20+W28+W33 共改；W33 的 render_paths 一组（12 文件，mtime 17:47–18:08）若未交付需剔除——dry 期间 W33 仍在改（Opus 终端"迁移 series10_v2 渲染前缀"），tree 31f83720 已不是最新工作树，重跑前要重新拼树。
- 不入版：docs/master/handover/vqa_client_route_CODER-PS.patch（CODER-PS 交接稿，W23 已实现）。
