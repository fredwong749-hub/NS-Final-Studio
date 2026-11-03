# STATE — NS-Final Studio（唯一当前真相；每轮结束覆盖更新；≤80 行）

- 更新：2026-11-03 22:05（MASTER-WSL）
- 当前阶段：**Phase R（跑通）**——冒烟门 eval/run_smoke.ps1 已建（W26），基线 1/8
- 最佳版本：git tag best = 44e6c37（sv-20261103-02，15:53 cut 七门全绿；2 条并行偶发串行重跑通过）；deploy #1 15:56–16:03 两台 ssh rc=255（项目方 15:5x 称远程 GPU 停机 1 小时）→ 后台每 2 分钟探两台，通了自动 deploy #2 + 验证，然后 L-152 换代
- 冒烟分数：**2/8**（R2 16:52：G2、G7；G1/G8 因 :8800 当时不通；eval/results/20261103-1652.json）

## 能跑到的环节（series10_v2 真实数据）
- 剧本 → 导入闸门 → 资产就绪 → 提示词 ✅（ep01）；ep02 卡"资产就绪"（5 缺口，身份脸作业被 count=untested 误判 failed）；ep03 写手已交 a3（15:34），autoflow 待接续
- 出图（首帧）✅ 能出（ep01 7 镜 14:17 已出）；出图检测 ❌ 经隧道打分/看图 12–30 分钟/镜、超时循环
- 尾帧 ✅ 一镜（S10）；视频 ❌ 未到；整集预览 ❌；复盘 ❌
- 换代完成：服务器 sv-20261103-02；gpu33 producer 在跑、control only_n=11（ep01）；笔记本 resident_sync loop 17:48 已换新代码；gpu36 重启排队。根因链：V2 run 级 ready 清单从未写（L-178）

## 已知坏点（≤5）
1. **服务器 producer 依赖的笔记本产物不自动同步**（ready 清单 / run 产物 / sop_gate 证据 / 派生参考图）：今晚全部手工 tar 推 gpu33 后才出图（L-178/179/180；ISS-181531/181720）
2. **gpu36 看图服务不在 resident 管辖**：server.py/watcher 死了没人知道 → gpu33 出图后 Q9/Q10 untested → score_infra 循环（ISS-220512；22:0x 手工拉起中）
3. **cut C 被挡**（A-G3 预检 docs/system_versions/CUTC_PRECHECK.md）：_kill_tree pid 复用误杀（= 今天 :8800/常驻被杀机制，P0）、K-OPS-W03 证据被 LIVE_PID_RE 排除、arch_scan 6 处退化 → W37 第一任 11-03 22:17 断网崩（①_kill_tree 已改完、31 测试过），11-04 重派第二任 ctx_aa966545c36c（Sonnet）只修 ②③ 剩 4 处；test_v1_leak 词表（W35）
4. merge_pull 并回按剧过滤已修（W36：否决 role/origin/path + 正证据，失败关闭；拒绝记 data/quarantine/<run>/merge_rejects_*.jsonl）——待入版 cut C；下次并回后看一次 live 统计
5. 冒烟 2/8（R2）；R3（看门狗补起 :8800 + resident_guard 看护）代码已入树，冒烟未重跑——等 gpu36 看图恢复后跑
- 已修待入版（cut C）：W17b/W18b/W20～W23/W6c/W14/W26/W26b/W27～W34/A-G3 分期 1

## 本轮工人（项目方 17:3x 放开并行）
- W35（v1_leak 词表）、W36（merge_pull 按剧）、W37（cut C 前置修复）、A-G3（owner_inbox silent_read → 然后重跑 cut C dry）

## 本轮唯一任务（R4）
- cut C 入版（W35/W36/W37 修完 → A-G3 dry 七门绿 → cut sv-20261103-03 → deploy 两台 → best 移动），让服务器拿到 adopt 过滤 / 写路径前缀 / 看门狗 / 守卫。

## 禁区
- eval/ 目录、评分表、best 标签只有总调度/诊断线可改。
- 不动 config/netfix、tools/netfix（W21）、producer.py（W20）、system_version.py + tests/conftest.py（W22）、vqa/client.py（W23），直到它们交付并入版。

## 下一轮候选（不许本轮动）
- 换代到服务器本地打分（cut → deploy --verify → L-152 handover）；ep02 资产 untested 不判 fail（W6c 已交付，待入版）。

## ⚡ 断电恢复清单（项目方 21:43 说笔记本快没电；按顺序做）
1. （21:4x 更正：笔记本只是休眠 18:4x–21:3x，没断电；A-G3 的 cut C dry pid 53588 仍活、锁已续期——不要清锁、不要重派。看门狗 21:38 因休眠登记的两条心跳陈旧 ISS 已关。）清 cut 锁只在 active=true 且 pid 不在时做。
2. 起常驻：ops/autostart/laptop_autostart.ps1（tunnel_supervisor ensure）→ ops/restart_resident_sync.ps1 → ops/restart_autoflow.ps1 → ops/restart_api.ps1 -Force → D:\ns_vqa\start.ps1；restart_producer.ps1 -Run series10_v2（笔记本 producer 现为 only=__none__，只保心跳）。
3. 服务器不受影响：gpu33 producer（pid 35505，sv-20261103-02）持有 ep01 11 镜 control；恢复后用 tools/netfix/rssh 看 data/producer/runs/series10_v2/log.jsonl 有无 dispatch/rendered；gpu36 重启请求 17:43 仍在队列。
4. 工人：W33 追加（迁回 V1 目录里的 V2 图 + frames_index 前缀）、A-G3 cut C 预检（tree 31f83720）断电后需重派；其余工人均已交付（见 ITERATION_LOG / MASTER_PICTURE L-171～L-178）。
5. 最近真相：冒烟 2/8（R2）；best=44e6c37；P0 跨剧泄漏已隔离 + 写路径已修（W28/W33）；:8800 两次被杀 → 看门狗规则 10 + resident_guard 看护已入码（待入版 cut C）。
