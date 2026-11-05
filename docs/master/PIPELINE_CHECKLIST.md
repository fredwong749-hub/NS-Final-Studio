# 一集生产清单（唯一 todo + checklist）

项目方原话（11-05 22:0x）：“逻辑很不清晰，你基于整个 pipeline 建立一条 todo 和 check list，不在里面的不做，超时的立马重来，保持连接，你思考怎么稳定和快的问题和方案。”

## 规则
1. **一集在跑时，GPU 只做这张清单上的事**。资产候选、A/B、研究、别集都不许占卡；清单外的任务等这一集结束再排。
2. **每一步有完成标准和超时**。超时就立刻重做（换道或换种子）；同一步重做 2 次仍不行，记卡点并跳到兜底（例如自动采用最好的一版），不让整集停下。
3. **一个调度者**：由 episode_run 按清单派活、计时、重做。producer / night 只是执行器，不再各自判断“要不要让道、要不要暂停”。
4. **保持连接**：笔记本到两台服务器用常驻 SSH 主连接，断了自动重连；所有远程命令走它（tools/netfix/rssh）。
5. **每步写一行状态**（开始、结束、用时、重做次数），供瀑布图和复盘。

## 清单（目标用时按 6×3090，L-197 新流程）

| # | 步骤 | 输入 → 输出 | 完成标准 | 目标 | 超时 → 动作 |
|---|---|---|---|---|---|
| 1 | 导入分镜 | staging P4 → 导入稿 | validate block 0，导入稿 sha 写入 | ≤ 1 min | 2 min → 重跑 1 次，仍失败记卡点（分镜问题） |
| 2 | 同步到出图机 | 导入稿 → gpu33 | 两边 sha 一致 | ≤ 30 s | 90 s → 直接推送（不等同步循环） |
| 3 | 提示词检查（逐镜） | 导入稿 → 每镜编译 + preflight 证据 | 每镜 ok；不 ok 的镜单独卡住，其余继续 | ≤ 1 min | 3 min → 重跑 |
| 4 | 首帧（逐镜，6 道全开） | 每镜 → 1 张定稿首帧 | 硬闸过（身份 / 人数 / 无字 / 成人安全） | 每张出图 ≤ 2× 预计；整集 ≤ 15 min（8 步）/ ≤ 45 min（35 步） | 单张超时 → 取消并换道重出；硬闸不过 → 换种子立刻重出；3 次后自动采用最高分版 |
| 5 | 视频（逐镜，首帧定稿即派，全部放得下视频模型的道） | 首帧 → 片段 | 片段存在、时长对、无黑帧 | 每段 ≤ 2× 预计（~450 s）；整集 ≤ 25 min | 单段超时 → 取消并换道重出 1 次；仍失败用上一个可用片段或静帧推镜兜底并记卡点 |
| 6 | 合成成片 | 全部片段 → 成片 | 成片存在、时长 60–120 s | ≤ 10 min | 20 min → 重跑合成 |
| 7 | 拉回 + 对比页 | 成片 → 本机 + 网页 | 大小一致、页面可开 | ≤ 5 min | 10 min → 重传 |
| 8 | 复盘数据 | 各步状态 → 瀑布图 | 页面生成 | ≤ 1 min | 不挡成片 |

尾帧不在清单上（L-197 A，从 ep02 起）。

## 稳定性（怎么不卡）
- 清单外不占卡 → 不会出现“首帧在排、视频让道”这类互相等。
- 任何“暂停 / 不接活”都必须带到期时间；清单执行期间，非本集的 hold 一律无效。
- 部署只在两集之间做；集内不重启执行器。
- 超时即重做，不等人；重做有上限，到上限走兜底，不停整集。
- 健康巡检（每 60 s）：执行器心跳、各道 /queue、隧道、看图 / 打分服务；挂了自动拉起并记一行。

## 快（怎么到 25–30 分钟一集）
- 首帧 8 步 + 摆位控构图（L-197 B），身份稳 → 少重出。
- 砍尾帧（L-197 A）→ 图片工作量减半，视频不再等尾帧。
- 视频首帧定稿就开出，和后面的首帧并行。
- 视频生成长度按剪后用量（约 5 s → 用多少出多少）。

## 执法实现（CHECKLIST 11-05，tools/master/episode_checklist.py）
- 任务表：data/pipeline/runs/<run>/episode_run/epNN_tasks.json（每步一行 + 首帧 / 视频逐镜一行：status / lane / started / ended / secs / attempts / timeout_s）；epNN_report.md 末尾有“清单与耗时”表；动作日志 epNN_events.log（`MM-DD HH:MM(JST) | CHECKLIST | ACT/FALLBACK/LOCK/CONN | …`）。
- 清单外不做：episode_run 每拍写 data/pipeline/episode_lock.json（TTL 600 s 滚动，episode_run 停了自失效）；asset_worker 见旗标跳过 render；A/B / 研究工具提交 GPU 前须调 tools/pipeline/episode_lock.active(root)。集开始时两台 night_control：yield_s=0、hold_lanes 只留坏卡 gpu33:2，原值备份在文件内 _ep_lock_backup，整集完成自动还原（卡点停下则保持，手动还原 = 跑 RESTORE_CODE 或集完成）。
- 超时即重做：首帧单张 > 2×预计（base35 330 s / turbo 60 s，读 config/render_quality.json）→ producer retry；3 次后 review-adopt 最高分版（report_issue）。视频单段 > 900 s 或首帧定稿后 120 s 未派 → night --once；2 次仍不行 → 记卡点兜底；night 状态 > 900 s 没更新 → 紧急 night-only 重启请求（每集一次）。注意 producer retry 不取消在途单（放回重派，在途单由 producer 自己的 render 超时取消）。
- 保持连接（已核实）：tools/netfix/rssh 本来就走 WSL OpenSSH 常驻主连接（ControlMaster，gpu33-cmd / gpu36-cmd* 池，tunnel_supervisor 托管、断了自动重连；ProxyCommand=false 只许复用，不新建握手）；run_retry 对 rc=255 / 超时按 10 s×n 退避重试；episode_run 的远程调用全走 run_retry。新增：每拍巡检 net_status.json，某台没有 up 的主连接就记一行 CONN。
