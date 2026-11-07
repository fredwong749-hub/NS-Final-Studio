# CLAUDE.md — NS-Final Studio 宪法（≤100 行，极少改）

## ⛔ 硬规则（11-07 审计与修复指令 Step 1，优先于下文一切）
- 每个会话结束必须覆盖更新 `STATE.md`（≤80 行：当前版本、冒烟分数+时间、能跑到哪一步、已知坏点 ≤5、下一轮候选）；没更新 STATE 的会话视为未完成。每做完一步在 `ITERATION_LOG.md` 追加一行（日期、做了什么、证据路径）。
- 自动 cut / release 分支已冻结（config/pipeline/release.json enabled=false），只留手工提交；冒烟 ≥6/8 前禁止 cut 新版本、禁止新增功能、禁止新写计划文档。
- 提交信息必须写清改了什么、为什么；禁止“系统版本（K-OPS-V01）”模板提交。（下文“commit 只走 system_version.py cut”冻结期间作废。）
- `config/pipeline/state.json` 与 `knowledge/generated/` 不入库（.gitignore；仓库留 `config/pipeline/state.example.json`）。
- 汇报发布状态不许只说“七门全绿”，必须同时报冒烟分数。
- `tools/autopilot/producer.py` 冻结：只许改冒烟门直接相关的行，新功能写新模块（冒烟 ≥6/8 后由项目方解冻）。

## 项目是什么
- 短剧全自动生产线：新剧本 P0 → 分镜/提示词 → 首帧/尾帧 → 视频 → 整集成片，目标 100% 无人介入（OWNER_CANON C-01）。
- 当前主剧 run = `series10_v2`（config/pipeline/runs.json primary）；V1（series10）内容彻底隔离，只带方法论（C-14）。
- 质量终局：画面接近实拍、4K、徕卡锐利（C-05）；好莱坞质感分（本地 VLM 1–10）≥ 8.5；一致性/成功率接近 95%。

## 不做什么（红线）
- 不删文件（只隔离、只停不删）；不花预算外的钱；成人画面只在自有机器；不碰 gpu33:2 / gpu36:2（坏卡）。
- 不推翻项目方已点选的创作决定（MASTER_PICTURE 账本 L-xxx 为准）。
- commit 只走 `tools/qa/system_version.py cut`（七道闸门）；线上重启先审并有回退。
- 评估器 `eval/` 只有总调度/诊断线可写，worker 不许改、不许给自己放行。
- 硬规矩：不看镜头、无字幕、单镜 ≤6 秒、At 只标切镜（C-06/07/08、L-141）。

## 目录约定
- `docs/master/`：MASTER_PICTURE.md（账本，master-only）、PLAN_V2_MASTER.md、OWNER_CANON.md、CHANNEL.md（总调度日志）、OVERSIGHT_LOG.md（审计轮次）。
- `tools/master/`：sop_gate.py（唯一阶段模型）、watchdog.py、report_issue.py（卡点板）。
- `tools/autopilot/`：producer.py（唯一出图路径）、resident_sync.py（常驻：发版/生命周期）、release_tick.py。
- `tools/factory/autoflow_resident.py`：剧本自动流 + asset_worker + hollywood_tick 每拍。
- `services/api`（:8800）、`services/agent/ns_agent`（契约/看图）、`services/render_router/ns_render`（出图）。
- `data/pipeline/runs/<run>/`：剧本/分镜/状态；`data/renders/<run>/epNN/SNN/takes.json`：每镜版本；`data/producer/runs/<run>/`：producer 状态。
- `eval/`：冒烟门 run_smoke.ps1 + 评分表（RSI 实施包 §4）；`STATE.md`：唯一当前真相；`ITERATION_LOG.md`：轮次账本；`BACKLOG.md`：停车场。

## 机器与网络
- 笔记本（Windows，WSL 总调度）+ gpu33（10.0.0.33，3090×4，GPU2 坏）+ gpu36（10.0.0.36）。
- 小命令走 gpu33-t / gpu36-t（香港底座内）；大文件走 gpu33-hk / gpu36-hk 单独传（运维 FONG-QUICK.md）。
- 远程命令经 tools/netfix/rssh.py；隧道由 tools/netfix/tunnel_supervisor.py 监管（config/netfix/tunnels.json）。

## 会话协议（RSI 实施包 §3）
- 新会话只读本文件 + STATE.md 开工；ITERATION_LOG.md 只在查回归时读最近 5 轮；禁止开局通读仓库/日志。
- 一轮一假设；Phase R（冒烟 8/8 连续 3 次）达标前禁止质量优化与新功能；范围外想法写 BACKLOG.md。
- 分数升 → cut 并移动 best；不升 → 回到 best，假设记"已排除"。停止条件：达标 / 连续 2 轮无提升 / 10 轮。

## 模型分工
- worker（日常改码）：Sonnet；诊断/架构（连续 2 轮失败或动评估器）：Opus；审计：Fable；评估：本地脚本（$0）；日志归类：Haiku。
