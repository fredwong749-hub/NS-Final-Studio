# UIMASTER 总结（2026-11-01 08:20，经 UIRSI 转交，总调度落盘）

## 进度
- 100 次迭代计划跑到第 14 次（中途 HOLD 一次；改按 ITERATION_PROTOCOL 后每轮需 iter_gate + UIAUDIT 复核；额度将尽）。
- r3、r4 iter_gate PASS：data/qa/iter_gate/UIMASTER_r3.md、UIMASTER_r4.md。

## issues.json 现状
- verified 237 / wontfix 73 / fixed 43 / gone 26 / open 145
- open 按严重度：s4 0、s3 6、s2 27、s1 112（s1 多为“接口慢”，第 13 轮一次后端尖峰，复测 10–60 ms）
- open 按负责人：UIRSI 106、ASSETUX 15、EDITDEL 9（UIMASTER 代管）、UIPIXEL 7、UIMASTER 4、DATAALIGN 4

## 已做成（均经 UIAUDIT 复核）
- G11 全站小图放大；精修首屏补回 F05/F09/F11/F31；弹框焦点陷阱与回位；画布批量“通过 / 打回”；G10 P0 = 0（r12g）；04:38 后首屏 1.8–2.6 s。

## PW-019 刷新闪
- 违规 114 → 81（UIRSI 又挪了 5 个文件）。剩 store.tsx useStudio、RenderTasks（GPUVIEW）、v3/edit 若干、过渡再导出。
- 稳定通道已就绪；切换被权限系统拒绝（要停开发服务器），已列 morning_decisions 第 6 项，等项目方。:5174 已由 VOICE10 让出。

## 已知空档
- 挪 Drawer 导出时导入方约 10 秒拿不到导出；safe_edit.sh 应改为先在沙盒副本跑 tsc 再写真文件。

## 第 15–30 次交接（11-01 午，总调度落盘）
- 跑完 30/100 次。问题库：verified 325 / wontfix 101 / gone 118 / open 65（s3 11、s2 13、s1 41）。
- r3–r5 iter_gate 都是 PASS，UIAUDIT 复核 G10 P0 = 0。
- PW-019 违规 114 → 5（只剩 store.tsx，已登记 deferred）。
- PW-020 根因：safe_edit 沙盒建在 vite 根目录里，已挪到 node_modules/.cache。
- 新做的：↻ 再生成挂在精修 Stage 和 VersionChain 上；ErrorBoundary；看图器焦点陷阱。r6 证据还在等 UIAUDIT。
- 已派出：UIPIXEL（↻ 按钮 22px、和"⋯"重叠）；UIRSI（集头露出内部文件名）；DATAALIGN（后端间歇性卡顿 15–17 秒）。
- 接着做：等笔记本恢复（resume_from_gpu33.sh）后，开新会话从 `node apps/web/e2e/uimaster/crawl.mjs --iter=31` 起，先收 r6。
