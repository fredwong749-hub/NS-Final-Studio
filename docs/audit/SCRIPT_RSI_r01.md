# AUDIT · SCRIPT-RSI 复核 r01（2026-11-01 19:23–19:24，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：data/script_rsi/d07_full/lint_table.md、返修稿 data/staging_v3/merged/漆皮之下·十日_series10_v1_rsiD07_ep01…ep10_v3.md（18:18）、导入记录 data/producer/log.jsonl 的 imported_staged、data/import/script_v2.json（18:24）。
边界：AUDIT 不评价剧本内容，只核对系统层的不变量（台词逐字、lint 数、导入通道和出处）。机读版：data/qa/audit/SCRIPT_RSI_r01.json

## 结论：通过

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | 台词逐字不变（lint 表最后一列全 ✅） | AUDIT 用 importer.script_md.import_script 解析返修前的来源稿（ep02/03/06 用 qwsz1_ep02_03_06_v3，其余用 ep01-10_lookfix_v3，和 defect_hunt state.json 的 script_src 一致）和返修稿，逐集比对“对白 + 独白”的文本序列和说话人序列：**10 集全部完全相同**（每集 3–12 句） | 通过 |
| 2 | 镜数变化 7→9 等 | 解析结果：ep01 7→9、ep02 8→10、ep03 7→9、ep04 7→9、ep05 8→9、ep06 8→9、ep07 11→11、ep08 8→9、ep09 8→9、ep10 8→9，和 lint 表一致；合计 93 镜，和 script_v2.json 的 93 镜、CODE-RSI 记的 data_parity“93 镜”一致 | 通过 |
| 3 | lint 表：合计 217 → 8，剩下的是 T1 7 条 + ep06 A5 1 条 | AUDIT 自己用 writer_lints.check_pacing 跑返修稿：QW-T1 剩 ep03 2、ep04 1、ep05 1、ep09 2、ep10 1 = 7，QW-T2 全部 0，和表一致。A1–A8 / AX1 没有逐项重跑 | T1 / T2：通过；A 类：未测（只核对了加总） |
| 4 | 导入走 PRODUCER 通道 | data/producer/log.jsonl 唯一一条 imported_staged：18:24:39，status 200，by “PRODUCER（总调度 fredw-2b 派，D-SCR-07）”，sha 75dbfdb9bb68…；返修稿 sha256 实测 = 75dbfdb9bb68c2d3…，一致；script_v2.json sources 里这一条覆盖 episodes [1…10] | 通过 |
| 5 | 导入前有备份 | data/script_rsi/d07_full/backup_before_import/ 里有 10 份 readiness_epN.json（就绪状态快照），不是剧本原文的备份；原稿在 staging_v3/merged/ 里都还在（上面第 1 条就是用它们比对的） | 通过（原稿可找回） |

## 提醒
- 镜数从 80 变成 93，旧镜号会整体后移（ep01 S8、S9 是新镜）。旧的出图 / 视频版本挂在旧镜号上：如果新稿在中间插了镜，同一个镜号对应的内容就变了。按 RSI r5 / WORKFLOW 的 full_redo，这次是全量重做，所以问题不大，但审片页和 active_audit 应该按新镜号重扫一遍（data_parity 93 镜已过）。
- 剩下的 7 条 QW-T1 是 warn 级，按 K-WRT-Q07 返修环不改时长，属于正常残留。
