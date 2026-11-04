# STATE — NS-Final Studio（唯一当前真相；每轮结束覆盖更新；≤80 行）

- 更新：2026-11-03 22:05（MASTER-WSL）
- 当前阶段：**Phase R（跑通）**——冒烟门 eval/run_smoke.ps1 已建（W26），基线 1/8
- 当前版本：sv-20261104-02（bfc4e158，cut D，11-04 13:38，已推 GitHub，未 deploy）；最佳版本：git tag best = 44e6c37（sv-20261103-02，15:53 cut 七门全绿；2 条并行偶发串行重跑通过）；deploy #1 15:56–16:03 两台 ssh rc=255（项目方 15:5x 称远程 GPU 停机 1 小时）→ 后台每 2 分钟探两台，通了自动 deploy #2 + 验证，然后 L-152 换代
- 冒烟分数：**2/8**（R2 16:52：G2、G7；G1/G8 因 :8800 当时不通；eval/results/20261103-1652.json）

## 能跑到的环节（series10_v2 真实数据）
- 剧本 → 导入闸门 → 资产就绪 → 提示词 ✅（ep01）；ep02 卡"资产就绪"（5 缺口，身份脸作业被 count=untested 误判 failed）；ep03 写手已交 a3（15:34），autoflow 待接续
- 出图（首帧）✅ 能出（ep01 7 镜 14:17 已出）；出图检测 ❌ 经隧道打分/看图 12–30 分钟/镜、超时循环
- 尾帧 ❌（W41 01:5x 查实：S8/S10 的 active.image/last 与 S3/S7/S8/S10 的 active.video 都是 V1 林晚版指针，C-14 泄漏，已摘并隔离记录；V2 尾帧要从 V2 首帧重做）；视频 🎬 11/11 全部过闸登记（07:4x）；ep01 视频段已划 gpu36，帧由 relay 从 gpu33 送）；整集预览 🎬 07:54 成片已出并 08:45 拉回笔记本 data/episodes/series10_v2/ep01_v2.mp4（45.04 s，硬规矩 pass；L-092 整集 45<60 s 只记）；复盘 ✅ 07:56 RETRO_ep01.md 自动 done（film_score 28.3/50）；gpu36 sop_gate ep01=完成（九阶段全有证据）
- 换代完成：服务器 sv-20261103-02；gpu33 producer 在跑、control only_n=11（ep01）；笔记本 resident_sync loop 17:48 已换新代码；gpu36 重启排队。根因链：V2 run 级 ready 清单从未写（L-178）

## ⚡ 交接（11-04 13:38，项目方令：本会话停止全部调度，指挥权交 PowerShell 的 claude 会话）
- 本会话（WSL/Fable 总调度）已停：不再派工、不再发信、监听已关；Orca run_ecd99b164f7a 无存活工人（W38/W42/W43/W45/W46 均 worker_done）。
- 刚完成：cut D 已入版 = sv-20261104-02（commit bfc4e158，树 ec43e2f0，84 文件，七门全绿；进程级 TZ=JST-9 + xdist 4），GitHub 已自动推送 master + 标签。**两台服务器尚未 deploy 这一版**（服务器现为 sv-20261104-01 + 热推文件，内容与 sv-20261104-02 一致）。
- 接手方下一步：① deploy 两台：`.venv\Scripts\python.exe tools/qa/system_version.py deploy sv-20261104-02 --report-json data/system_versions/deploy_sv-20261104-02_report.json`，之后 `verify sv-20261104-02 --shot 8 --run series10_v2`，再 best 标签按冒烟分定（上次冒烟 1/8，R4）；② Windows 时区被改成 Central Standard Time → 项目方 `Set-TimeZone -Id 'Tokyo Standard Time'`（否则 sv 号按本地日期算错、6 条时间测试红；进程级 TZ=JST-9 可绕）；③ 项目方复核 ep01 的 6 个待复核版（首帧 S4 v12 / S8 v1 / S9 v8，尾帧 S5 v8 / S7 v7 / S11 v1）与整集 45 s<60 s（L-092）；④ ep02 是否开跑由项目方定（故事线《透明高跟》第 5 稿 32/40，停在“等项目方定方向”）；⑤ BACKLOG 里 W43/W46 遗留 P1/P2。
- 工具与坑：工人测试走 tools/qa/remote_pytest.py（gpu33）；cut 七门默认 gpu33（release.json gates_on），服务器缺数据会多 2 条环境红，本地用 --on local；gpu36 复用 ssh 通道反复抖，直连（ControlMaster=no）可通；tunnel_supervisor 僵死用 stop + kill + ensure；restart_queue 30 分钟间隔；deploy 命令在本会话被 Claude Code 权限分类器拦，PowerShell 侧请自行确认权限。

## 已知坏点（≤5）
1. ~~服务器 producer 依赖的笔记本产物不自动同步~~（W40 02:30 已入码 run_sync，待下次 cut 入版；真实宕机自动拉起未验证）（ready 清单 / run 产物 / sop_gate 证据 / 派生参考图）：今晚全部手工 tar 推 gpu33 后才出图（L-178/179/180；ISS-181531/181720）
2. ~~gpu36 看图服务不在 resident 管辖~~（W40 vqa_guard 已入码；score_infra 真因 = 8893 人数检测没人拉起，已起在 GPU1）：server.py/watcher 死了没人知道 → gpu33 出图后 Q9/Q10 untested → score_infra 循环（ISS-220512；22:0x 手工拉起中）
3. **cut C 已入版 = sv-20261104-01（e56e5e1，tree addb1e0f，130 文件，七门全绿 694 passed）**：01:27 cut 的 git reset 撞上 11-03 17:29 陈旧 .git/index.lock（pid 复用误杀留下的，W37 已修根因；锁已改名隔离 index.lock.stale-20261103-1729），tag/index/状态快照由总调度 01:3x 补完；GitHub 推送第一次断线，已重试。**deploy 已完成**（项目方 01:45 亲手跑）：gpu33/gpu36 两台 ok；gpu33 01:49 排空后重启（producer pid 204016）；gpu36 重启 340461cfe44a 排队中；verify 02:02 两台 ok（golden ep01-S8 server_ok、manifest 一致）。冒烟 02:04–02:30 重跑 = **1/8**（eval/results/20261104-0204.json；G1 笔记本 :8870 没起、G3/G4 smoke_v2 无出图、G7 sop_gate 两遍不一致→W38）；best 不动 44e6c37。best 仍 = 44e6c37，等冒烟分升再移。
4. merge_pull 并回按剧过滤已修（W36：否决 role/origin/path + 正证据，失败关闭；拒绝记 data/quarantine/<run>/merge_rejects_*.jsonl）——待入版 cut C；下次并回后看一次 live 统计
5. 冒烟 1/8（R4，02:30；R2 曾 2/8）；R3（看门狗补起 :8800 + resident_guard 看护）代码已入树，冒烟未重跑——等 gpu36 看图恢复后跑
- 已修待入版（cut C）：W17b/W18b/W20～W23/W6c/W14/W26/W26b/W27～W34/A-G3 分期 1

## 本轮工人（项目方 17:3x 放开并行）
- 项目方 11-04 01:4x 原话："ep01搞了几天也搞不好,你现在只有一个命令,立马启动全部agents,一口气做完,做不完,不停止"。W38 ✅ 08:19 收工 + ✅ 11:1x cut D 红清（imgfix 测试改为真有分才断言；push_preflight_deps 已绿）（ep01 提示词→完成；hf-01..17 + sync36；报告 docs/master/handover/W38_EP01_REPORT.md；未完：S8 尾帧 Q9 结论与证据矛盾、vidgen rescore 不跑视频 VLM、6 版待项目方复核）、W40 ✅ 02:30 交付（resident_sync 新增 run_sync 每 120 s 推两台 + vqa_guard 每 300 s 探/拉起 gpu36 8870/8893；37+92 测试过；已重启常驻单份）、W41 ✅ 03:1x 交付（尾帧/视频/整集预览三段在 gpu33 沙箱实跑通：视频 5.167 s 硬规矩全过、预览 63 s；修 5 个 V2 视频链 bug；runbook docs/master/handover/EP01_VIDEO_STAGE_RUNBOOK.md；注意 episode_retro --auto 只认 night finalize 产出）、W42 ✅ 03:0x 交付（asset_refs 按角色取单品；S10 take7 Q2 pass）+ ✅ 06:08 L-184 + ✅ 09:10 cut D gen_contract 9 红清（测试过时：V1 夹具归档守卫；只改测试）、W44 ✅ 03:12 交付（producer.py：canary 按 code_sha+pid 隔离并自动恢复、rescore 每镜每小时 ≤3、尾帧→视频 night 接手、hold_lanes 到期 sweep；dispatch.py 修 hold 来源；待 hf-03 上 gpu33）、W43 ✅ 08:1x 终审（15 轮；ep01 整集预览成立，红线全程未碰；明细 docs/master/OVERSIGHT_LOG.md 终审节）、W45 ✅ 08:3x 收工（cut 七门默认 gpu33 83.8 s vs 笔记本 277 s；remote_pytest；数据镜像 B 限速中；8870 固定 GPU1；文档 CUT_ON_SERVER/DEV_ON_SERVER/SMOKE_ON_SERVER）、W46 ✅ 06:0x + ✅ 09:2x（成片拉回笔记本 ep01_v1/v2 同 sha；cut D 自家红清：merge_takes 模块级、arch 7 处 0 退化、test_factory/test_w46_finalize 更新）（视频→finalize→预览→retro 在 gpu33 沙箱全链跑通；10 处服务器阻塞修好并两台同步 hf-w46-02/03；帧中继 gpu33→gpu36→笔记本；部分预览循环；runbook docs/master/handover/EP01_FINALIZE_RUNBOOK.md）。W39 RELEASE-DEPLOY 派不出：Claude Code 权限分类器连派工也拦（Production Deploy）→ deploy 必须项目方亲手跑那一行（见第 3 条）。

## 本轮唯一任务（R4，项目方 01:4x 改）
- ✅ 07:56 ep01 全流程完成（成片 ep01_v1.mp4 45 s、retro done）。下一步：项目方复核 6 镜待复核版与 45 s 时长；全部热修入版 cut D；冒烟重跑；ep02 按同一条线自动走。原任务：附带：cut C 入版：dry 绿 ✅ → cut sv-20261104-01 ✅ → deploy 两台 ✅ verify ✅ → 冒烟重跑 → 分数升才移 best，让服务器拿到 adopt 过滤 / 写路径前缀 / 看门狗 / 守卫。

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
