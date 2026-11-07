# ASSETS-MISSING — series10_v2 ep01–ep04 素材缺口（活文件，破循环指令 线 2）

**清单已清零（11-08 03:5x JST）。**

口径：某镜“到不了视频”的缺口（缺首帧 / 尾帧 / 首帧不合规），不含正常排队渲染中的镜。
来源：/api/videos/overview（笔记本 :8800）+ 两台服务器 data/pipeline/runs/series10_v2/video/jobs.json（anomaly_skipped）+ producer 登记表 / 账本。11-07 23:3x JST 盘点。
销账规则：补上 = 该对象有本剧新版本且进了视频队列；每项补法执行时单独 commit，并在此划掉写提交号。

| # | 集 / 镜 | 缺什么 | 为什么缺 | 补法 | 状态 |
|---|---|---|---|---|---|
| 1 | ~~ep01-S1~~ | 首帧（连带尾帧、视频） | 首帧 3/3 次没过契约（G1 + 身份；v9 按 L-200 补判“看镜头 / 排排站”撤下）→ 标尽力版；尾帧规则“等首帧过契约”、视频等首尾帧 → 死锁。gpu33 账本 tries=3 | 自动：gpu33 `producer.py reset-best-effort --shots ep01-S1 --run series10_v2`（重新给 3 次，旧次数标 before_gate_change） | ✅ 已销账（69820b74）：首帧 v27 过契约（23:27）、尾帧 v12 过契约（23:56）；gpu36 00:03 用新首尾帧提交视频，00:09 出 video_003，00:10 打分 PASS（mean 2.713） |
| 2 | ~~ep02-S1~~ | 首帧（视频被跳过） | 当前首帧 v1 = renders/ep02/S1/takes/image_001_pipeline_9274396b.png，不在本剧渲染目录（跨剧版本 C-14）→ gpu36 build_jobs anomaly_skipped，不进视频 | 自动：gpu36 `producer.py reject --obj first:ep02-S1 --n 1`（撤下跨剧版本，本剧重出，不计 3 次上限） | ✅ 已销账（69820b74）：23:29 前后首帧 v6 过契约成当前、尾帧已过、视频已提交；gpu36 jobs.json 23:38 重建 anomaly_skipped=[] |
| 3 | ~~ep02-S4~~ | 首帧（同上） | 同上：image_001_pipeline_d82ca1f6.png 跨剧版本 | 同上 | ✅ 已销账（69820b74）：23:29 前后首帧 v6 过契约成当前、尾帧已过、视频已提交；gpu36 jobs.json 23:38 重建 anomaly_skipped=[] |
| 4 | ~~ep02-S7~~ | 首帧（同上） | 同上：image_001_pipeline_ac7b7ab0.png 跨剧版本 | 同上 | ✅ 已销账（69820b74）：23:29 前后首帧 v6 过契约成当前、尾帧已过、视频已提交；gpu36 jobs.json 23:38 重建 anomaly_skipped=[] |

不算缺口（记录备查）：
- ep03 S1/S2/S4/S8–S11：11 镜全部在 gpu33 jobs.json（18:24 重建），按序渲染中（已出 4 镜待审、1 尽力）。
- ep04：12/12 镜有视频（待审 / 尽力）。

已发现、按单线律只排队不动手：网页 #/videos 把 ep02-S1/S4/S7 显示为“queued”，实际被 build_jobs 跳过（页面与真实状态不一致）。
