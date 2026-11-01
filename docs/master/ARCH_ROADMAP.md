# 代码架构路线图 ARCH_ROADMAP（SYSARCH 常驻维护）

> 负责：SYSARCH（总调度 fredw-2b 11-02 派）。底稿：docs/master/ARCH_MAP.md（ARCH-AUDIT，只读审计）。
> 分工：SYSARCH 管代码结构；SENTINEL 管运行指标（docs/master/SLO.md）；DISTILL 管策略和判断点（docs/AUTOPILOT.md）。三家产物互相引用，不重复。
> 状态写法：待办 / 进行中 / 待验 / 关闭（关闭必须附验证证据）。百分比 = 关闭项 ÷ 全部项（§1 + §2 + §4，去重后 47 项）。

## 0. 机制：结构问题由系统先发现

| 机制 | 做法 | 出处 |
|---|---|---|
| 巡检 | `python tools/qa/arch_scan.py`：全仓 AST 扫 10 项结构退化 → data/sysarch/scan_latest.json + history.jsonl | K-OPS-S01 |
| 棘轮 | `arch_scan.py --check` 对比 data/sysarch/baseline.json：任一文件任一项变多、或新冒出“未入版却被 import 的模块” = 不过 | tests/test_arch_scan.py |
| 架构闸门 | 各 loop 交 cut 前跑 `arch_scan.py --files <改动> --check`，加上人工审 diff 六条：不新增平行实现、不新增静默放行、远程只走 rssh、配置单一事实来源、每个判断有 decider + check（G1）、子进程有 timeout | 本文 §5 |
| 豁免 | 调用方确实显式处理了 None 的读取，在 except 行写 `# arch-ok: <理由>`；SYSARCH 审 | K-OPS-S01 |
| 基线收紧 | 只在关单后由 SYSARCH `--write-baseline`；棘轮只往下 | — |

**首扫基线（11-02 02:43，535 个代码文件）**：no_timeout 80、direct_ssh 35（未登记 1）、def_ssh 15、hard_run 157（只算代码里的字符串，注释 / docstring 不算；ARCH_MAP 的 476 处含文档和配置）、hard_path 137、silent_read 317、nonatomic_json 245、untracked_code 36、unowned 243、**未入版却被 import 12 个**。

待办：把 `arch_scan --files --check` 接进 iter_gate（新检查项 A1）和 system_version cut 的闸门——iter_gate / system_version 分属 ITERAUDIT / FACTORY，需总调度定（见文末）。

---

## 1. Top 15 结构性问题

| # | 问题（ARCH_MAP §9） | 负责 | 验收标准 | 依赖 | 状态 |
|---|---|---|---|---|---|
| 1 | 运行中的代码不在版本里 | FACTORY（cut）+ 各 owner 入版 | `arch_scan` 的 untracked_imported = 0；git status 里代码目录 `??` 的 .py = 0；从 sv tag 干净检出能 import producer / ns_api / canvas | — | **恶化**：12 个（02:43），比审计时多 decisions_guard、sentinel/store、runs、script_autoflow、sheet_intake、camera_norm |
| 2 | 决策覆盖文件读不到静默放行 | FACTORY（F09 decisions_guard）+ REFLOCK（asset_refs 缺文件报错） | producer 派单前 problems() 非空即拒派；asset_refs 9 处覆盖读改成缺文件报错；服务器 run.json 存在 | #1（decisions_guard 未入版）；G20 | 进行中（F09 代码在笔记本工作树，服务器未部署；**服务器两台仍缺 config/pipeline/run.json、runs.json**，02:43 实测） |
| 3 | 服务器常驻无本机守护 | FACTORY | producer / night / fwd 由 systemd 或 cron 拉起；kill -9 后 ≤60 s 自动恢复（实测） | G9 | 待办（02:43 实测 gpu33 无 crontab；gpu36 crontab 空；producer 仍 nohup） |
| 4 | 跳板 + WSL 主连接单点 | NETFIX | 主连接断后 ≤30 s 自愈（S4）；rssh 失败有探针报警 | — | 待办 |
| 5 | takes / attempts / control 多写者无跨进程锁 | DEBUG-RSI（attempts / control）+ NETFIX（merge_pull 单入口）+ REFLOCK（takes 写入口） | 每个文件只有一个写入口函数；跨进程文件锁；并发写测试通过 | — | 待办 |
| 6 | cut 脆弱（xdist 收集不一致；98 个测试读真实 data） | FACTORY（cut 失败禁 deploy）+ CODERSI（测试隔离） | 连续 3 次 cut 一次过；cut 失败时 deploy 拒绝执行（测试） | — | 待办（last_cut.json：sv-04 失败） |
| 7 | 推送 6 条路径 | FACTORY（数据按 sha）+ WORKFLOW | 只剩 factory/sync.py push + system_version deploy；其余入口打印退役提示后退出 | G9、G10 | 待办 |
| 8 | 配置声明 ≠ 实际进程 | VQAGATE + SENTINEL（G26 探针） | 声明 vs 实际探针 0 差异 | — | 待办 |
| 9 | 生产仍走隧道派单 | FACTORY | IMAGE_LANES 从 hosts.json 读；服务器 fwd.py 停掉后照常出图 | G1 | 待办（02:43 两台 fwd.py 仍在跑） |
| 10 | 笔记本开机靠人工拉起 | WORKFLOW + SENTINEL | 计划任务注册；重启笔记本后 ns_api / vite / supervisor 自动起 | — | 待办 |
| 11 | 写死 run_id 和路径 | WORKFLOW（读者改走 runs.py）+ DISTILL（lint）；SYSARCH 做无主部分 | arch_scan hard_run 只降不升，目标 = 0（runs.py 除外） | runs.py 入版（#1） | 进行中（runs.py 已有，未入版；基线 157 处） |
| 12 | 重启 / 修隧道多入口 | NETFIX（隧道）+ DEBUG-RSI（restart_queue） | infra_watchdog 无 taskkill / start_loop 段；gpu3_tunnels.py 隔离；重启只走 restart_queue | — | 待办；SYSARCH 可代做 §4-3 |
| 13 | ssh 调用分散 | NETFIX；SYSARCH 做迁移 | arch_scan direct_ssh、def_ssh 降到只剩登记的必需项；ssh_unlisted = 0 | — | 进行中（基线 35 / 15；ssh_unlisted 1：apps/web/e2e/gpuview/crosscheck.py） |
| 14 | 缺超时和回压 | DEBUG-RSI / DIRECTOR / UIRSI；SYSARCH 做无主部分 | arch_scan no_timeout = 0；ns_api 队列有上限 | — | 进行中（基线 80） |
| 15 | 所有权表脱节 | ITERAUDIT（总调度定） | arch_scan unowned = 0；HOLLYWOOD / IMGFIX / SENTINEL / SYSARCH / FACTORY 有条目；docs/AUTOPILOT.md 一个 owner | — | 待办（基线 243 个代码文件无主） |

## 2. 目标架构差距 G1–G26

| # | 目标 | 负责 | 验收标准 | 依赖 | 状态 |
|---|---|---|---|---|---|
| G1 | D1 工厂身份 + hosts.json | FACTORY；SYSARCH 收车道表 | config/factory/hosts.json 唯一车道表，其余 4 份改读它；NS_FACTORY_HOST 生效 | — | 待办（config/factory 不存在） |
| G2 | D2 库按 sha；scene_ref 不按 mtime | FACTORY + IMGFIX | asset_refs.py 不再用 mtime 取图 | — | 待办 |
| G3 | D3 依赖闭包含决策文件 + sha | FACTORY | deps 闭包列出 decisions_guard.REQUIRED 并比 sha | #2 | 进行中 |
| G4 | D4 inbox 声明式 + min_code_sv | FACTORY + WORKFLOW | CONTROL_FILES 推送退役；min_code_sv 检查有测试 | G3 | 待办 |
| G5 | D5 断网 ≠ 暂停 | DEBUG-RSI + NETFIX | 服务器 paused 不跟随笔记本 | — | 待办 |
| G6 | D6 本机打分常驻 + VLM 专用卡 | VQAGATE + FACTORY | scorer 常驻，S3 打分 p50 ≤120 s | — | 待办 |
| G7 | D7 outbox + puller | NETFIX + FACTORY | outbox 有事件；tar pull 退役 | — | 待办 |
| G8 | D8 依赖到齐事件驱动 | DEBUG-RSI | 不再 30 分钟轮询 | G7 | 待办 |
| G9 | D9 服务器 = 干净 git 树，只发 tag | FACTORY | 服务器代码 sha = sv tag；#1 关闭 | #1、#6 | 待办 |
| G10 | D10 一条命令控制台 sync | FACTORY + WORKFLOW | 同 #7 | #7 | 待办 |
| G11 | 单一负责人 | ITERAUDIT | 同 #15 | — | 待办 |
| G12 | 隔离笔记本隧道派单 | FACTORY + NETFIX | 笔记本 producer 退出生产 | G1、G6 | 待办 |
| G13 | 服务器自保活 | FACTORY | 同 #3 | — | 待办 |
| G14 | 一个编排器 | DISTILL | ns_orch / iterate_loop 出片段退役 | — | 待办 |
| G15 | run.json / runs.json 单一来源 | WORKFLOW + DISTILL | 同 #11；服务器有 runs.json | #1 | 进行中 |
| G16 | state 快照覆盖全部决策文件 | DISTILL | state_files.yaml ⊇ decisions_guard.REQUIRED ∪ OPTIONAL（建议加测试互查，避免两份清单） | #2 | 待办 |
| G17 | S1/S2 道利用率探针 | SENTINEL | tools/sentinel 入版并常驻 | #1 | 进行中（代码在、未入版） |
| G18 | S4 连接 ≤30 s 恢复 | NETFIX + SENTINEL | 同 #4 | — | 待办 |
| G19 | S5 cut 一次过 | CODERSI | 同 #6 | — | 待办 |
| G20 | S6 服务器配置 0 差异 | FACTORY + SENTINEL | 探针清单 = state_files.yaml ∪ deps 闭包；0 差异 | G16 | 待办（run.json、runs.json 两台缺） |
| G21 | S7 无主暂停 ≤180 s | DEBUG-RSI | run.py guard --apply 常驻 | — | 待办 |
| G22 | S8 内容抽检排程 | VQAGATE | 定时 | — | 待办 |
| G23 | S9 界面探针常驻 | UIRSI | 定时 | — | 待办 |
| G24 | S11 编排器违约开单 | DISTILL + SENTINEL | issues.jsonl 有违约单 | — | 待办 |
| G25 | S12 剧本尺子入版 | HOLLYWOOD | rubric_code.py 入版 | #1 | 待办 |
| G26 | 声明 vs 实际探针 | SENTINEL | 端口 / 实例 / 版本逐项实测 | G1 | 待办 |

## 3. 删繁就简（只隔离到 data/_quarantine，不删）

| 项 | 负责 | 前置条件 | 状态 |
|---|---|---|---|
| 0 引用一次性脚本（ARCH_MAP §8.1 第一组 6 个） | SYSARCH（通知 owner 后隔离） | quarantine_refcheck 0 引用 | 待办 |
| gen_assets / gen_assets_v2 / gen_assets_items（K-REN-134 取代） | REFLOCK | refcheck；gen_assets_v2 读 items 源码一起走 | 待办 |
| tunnel.sh / tunnel_gpu36.sh / gpu3_tunnels.py | NETFIX；SYSARCH 代做 | infra_watchdog 先去掉引用 | 待办 |
| 死配置 18098 / 18290 / gpu36:8190 / laptop 8870 | NETFIX / AUTOPILOT / FACTORY | 车道表收口（G1）时一起删 | 待办 |
| services/qc 空目录、仓库根 selftest 产物、puller_selftest 写根目录 bug | SYSARCH / NETFIX | — | 待办 |
| 实验目录里的生产依赖（score_clip → ep02_iter 等） | VIDEO10 / VQAGATE | 先迁到 ns_render / ns_qc | 待办 |
| 合并：motion / judder 4 份、身份度量 3 套、合成 4 入口、control 4 套 | 见 ARCH_MAP §8.2 | — | 待办 |

## 4. SYSARCH 亲自做的无主整合（每步小、可回退、带测试；动别人文件先通知）

| # | 项 | 涉及 owner | 验收 | 状态 |
|---|---|---|---|---|
| 4-1 | ssh 统一到 rssh.run（13 个自写 def ssh 先改） | NETFIX + 各文件 owner | arch_scan def_ssh 15 → 0（rssh/rsh/shim/supervisor 外） | 待办 |
| 4-2 | 车道表收成 config/factory/hosts.json | FACTORY（D1 主导） | 同 G1；SYSARCH 只做读者改造 | 等 FACTORY 定 schema |
| 4-3 | 退役 tunnel*.sh / gpu3_tunnels.py / infra_watchdog 修隧道段 | NETFIX | K-OPS-N01；infra_watchdog 无 taskkill ssh | 待办 |
| 4-4 | 删繁就简里能隔离的 → data/_quarantine | 各 owner | quarantine_refcheck 0 引用 | 待办 |
| 4-5 | 80 处 subprocess 补 timeout（先无主文件，再核心链路 19 处由 owner） | DEBUG-RSI / DIRECTOR / UIRSI | arch_scan no_timeout 80 → 0 | 待办 |
| 4-6 | series10_v1 写死 157 处改读 runs.py | WORKFLOW（runs.py） | arch_scan hard_run → 0 | 等 runs.py 入版 |

## 5. 架构闸门审查记录（diff 级）

| 时间 | loop | 改动 | 结论 | 回给 |
|---|---|---|---|---|
| 02:43 | FACTORY | producer.py +359 行接 decisions_guard（K-OPS-F09） | 方向对（失败关闭）；**两条必须先满足再部署**：① decisions_guard.py 入版（现在 `??`，按 tag 部署 producer 会 import 失败）；② run.json / runs.json 先推上服务器（现在两台都缺，F09 一上线服务器 producer 会整体拒派 = 停产）；decisions_guard.py:56 仍留 `run or "series10_v1"` 回退，应改为 run 为空直接返回问题 | FACTORY |
| 02:43 | SENTINEL | tools/sentinel/probes.py | :302 写死 data/pipeline/runs/series10_v1/... 帧目录，改用 runs.py；7 处读取静默放行（探针读不到应报“未知”而不是当正常）；整个 tools/sentinel 未入版却已被 run.py、canvas app、iterate_loop import | SENTINEL |

## 6. 巡检日志

| 时间 | 新发现 | 出处 |
|---|---|---|
| 02:43 | 未入版却被 import 的模块 12 个（审计时 #1 列的是 7 类）：canvas_api/app.py（**gpu33 服务器跑的渲染桥**）import 了未入版的 runs.py 和 sentinel/store.py；ns_api/app.py import 未入版的 script_autoflow.py；producer.py import 未入版的 policy / import_events / factory.inbox / factory.outbox / decisions_guard | data/sysarch/scan_latest.json `untracked_imported` |
| 02:43 | 新增直接起 ssh 却没登记：apps/web/e2e/gpuview/crosscheck.py | arch_scan ssh_unlisted |
| 02:44 | knowledge 编译失败：K-WRT-705（knowledge/rules/writer_camera.yaml:238）section “人物字段” 不在允许列表 → compile.py 不出生成物，所有 loop 的 K1 检查都会挂 | compile.py --check |
| 02:5x | 基线写下后约 10 分钟，棘轮又抓到 6 处新退化：tools/sentinel/{sentinel,build_ui_flows}.py 新文件未入版，probes.py 静默读取 7→8，build_ui_flows 非原子写 JSON；tools/qa/identity_face_check.py 新增 1 处静默读取 | arch_scan --check |

## 进度

关闭 0 / 47（0%）。进行中 8。机制（§0 巡检 + 棘轮）已落地：tools/qa/arch_scan.py、tests/test_arch_scan.py（10 过）、K-OPS-S01。
