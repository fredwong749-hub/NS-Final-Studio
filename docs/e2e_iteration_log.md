# ep02 端到端多轮自我迭代 debug 日志（fredw-92/D1）

目标：ep02 共 11 镜，每镜 首帧 → 尾帧 → H3 视频，再拼成片。全部走 v1 接口（frame-jobs / takes lock / video-jobs / jobs）。
出图 GPU0（gpu=0，隧道 18188），视频 GPU3（gpu=3，隧道 18191），流水线并行。
驱动脚本：会话 scratchpad `e2e_driver.py`（状态机：每镜 首帧未定稿 → regen；首帧定稿 → 尾帧 regen；首尾帧定稿 → 视频；出图卡一次只挂一个任务、视频卡一次只挂一个任务，方便中途重启 API）。

**定稿说明**：本轮所有定稿均为**自动测试定稿（by: e2e-auto，“自动测试定稿，待项目方复审”）**——每个阶段第一个成功的版本自动定稿，不看画面质量。lock 接口不收 note 字段，因此记在本日志与驱动事件流里。

起始状态（2026-10-31 01:09）：S1 首尾帧已定稿无视频；S2 首尾帧 + 视频 v2 完成；S3 首帧因发型参考覆盖过期 → 重出；S4–S6 只有旧的未定稿版本（剧本已改）；S7–S11 无任何版本。两条隧道空闲可达。

| 轮 | 步骤 | 失败现象 | 根因 | 修复 | 文件:行 | 结果 |
|---|---|---|---|---|---|---|
| 1 | 启动驱动：S1 视频（GPU3）+ S3 首帧重出（GPU0） | S3 首帧 v5 74 s 成功；驱动在记自动定稿日志时崩溃（UnicodeEncodeError，cp1252 控制台） | 驱动脚本自身：stdout 非 UTF-8 | 驱动 stdout.reconfigure(utf-8) + 启动时接管已在跑的任务（避免重复提交） | scratchpad e2e_driver.py | S3 首帧 v5 已自动测试定稿（锁请求在崩溃前已发出）；S1 视频继续跑 |
| 1 | 运维检查：GET /api/jobs | S1 视频正在 GPU3 跑，/api/jobs 却返回 [] | /api/jobs 只列旧渲染队列 `_jobs`，v1 任务队列（jobs.py）不在其中；按“/api/jobs 空才重启 API”规则会把正在跑的视频打断 | /api/jobs 并入 `JOBS.all_jobs()`（带 v1:true，stage 映射 first→image、视频 → video） | services/api/ns_api/app.py:1464 | 下次 API 重启后生效 |
| 2 | 加第二条视频线 GPU1（千问已撤，gpu3 :8189，隧道 18189） | 视频 / 出图任务 gpu=1 被拒（400/422“gpu 只能是 (0, 3)”） | `jobs.GPUS = tuple(DEFAULT_URLS)` 写死 0/3，没读 config/render_endpoints.json 的 gpus 表（ns_render.endpoints.gpu_ids 已经会读） | `jobs.GPUS` 改为每次读 `endpoints.gpu_ids()` 的类 tuple 对象；config gpus 表加 "1": 18189；两条旧测试“gpu=1 必须拒绝”改为 gpu=2（坏卡）；新增 tests/test_gpu_lanes_d1.py（4 例） | services/api/ns_api/jobs.py:27-55；config/render_endpoints.json；tests/test_video_jobs_v1.py:143；tests/test_frame_jobs_w2.py:209 | 先用 ComfyClient.check 核对 H3 工作流在 :8189 / :8191 都无缺失模型（实例标识 out:…/output/gpu1 与 gpu3 不同 → 跨卡首尾帧上传一次，按 F1） |
| 2 | 空档重启 API（01:28，S1 视频完成、S4 尾帧完成后，驱动暂停提交） | — | — | 按 laptop_autostart.ps1 方式重启（NS_COMFY_URL=18188） | — | /api/assets/scenes 200；/api/jobs 已列出 v1 任务；S3 视频 → GPU3、S4 视频 → GPU1 并行 |
| 3 | 视频：S1–S6 完成（GPU3 / GPU1 轮流，每版 12.3–16.4 min） | S8（剧本 12 s → 294 帧）两次在 GPU3 失败：`SamplerCustomAdvanced` torch.OutOfMemoryError（已分配 19.13 GiB + 再要 4.97 GiB > 23.56 GiB）；S11（10 s → 243 帧）同样会超 | 768×1344 的 H3 在 3090（--reserve-vram 1）上实测上限约 192 帧（8 s，峰值 22.6 GB）；系统只按 H3 训练范围 124–362 帧校验，没有显存上限 | 加显存安全上限：`h3_video.frames_for()` = min(frames_for_seconds, safe_max_frames())，默认 192，环境变量 NS_H3_MAX_FRAMES 可调（向下对齐 17k+5）；超出的镜头按 gpu3 修复规则 oom.lower_cost “出短一格、剪辑按片长走”，take.params 记 frames_requested / frames_capped；video-jobs 的 params.frames 同步；剧本 frames_for_seconds 不动；新增测试 1 例 | services/render_router/ns_render/h3_video.py:29-50,226,268；services/api/ns_api/video_jobs.py:79 | 全量测试 835 passed / 6 skipped；待空档重启 API 后重出 S8、S11 |
| 4 | 02:18 第二次空档重启 API → 重出 S8（GPU3，192 帧，frames_requested 294）与 S10/S11（GPU1） | — | — | — | — | 02:49 全部 11 镜 首帧 / 尾帧 / 视频 完成（S8、S11 视频按显存上限 8 s） |
| 5 | 装配：`tools/assemble_episode.py ep02 --allow-laptop-video`（现成 laptop 装配器，v1 take 走 data/renders/ep02/S*/takes.json 的 active video；Kokoro 配音 + SenseVoice 回听；每镜 H3 原声作声音设计底；-14 LUFS） | 输出名为 `ep02_PREVIEW_未完成.mp4`，警告却说“有占位镜头”（实际 11 镜全是视频） | 预览判定 = 有占位 或 gpu3 qa.json 不通过；警告文字写死“有占位镜头” | 警告写明真实原因（“gpu3 QA 未通过 / 没有 qa.json”）；命名规则不改（只有 gpu3 验收才叫 final，旧规则） | services/post/ns_post/assemble.py:714 | data/episodes/ep02_PREVIEW_未完成.mp4：1080×1920，84.08 s，2018 帧，h264/aac，-14.01 LUFS / -1.26 dBTP；11 镜全为 H3 视频 + 原声 |

## 结果汇总（02:51）
- 11/11 镜头：首帧、尾帧、视频全部完成；所有定稿均为 **e2e-auto 自动测试定稿，待项目方复审**。
- GPU 时间：出图 18 个任务共 25.7 min（GPU0）；视频 10 版共 154 min（GPU3 6 版、GPU1 4 版，单版 12.3–17.0 min）+ OOM 失败 3.3 min；墙钟 01:09 → 02:49（1 h 40 min）。
- 遗留：① 成片命名仍为 PREVIEW：没有 renders_gpu3/ep02/qa.json（gpu3 验收）；② 没有 data/music/ep02.wav——按 X-4，S1–S10 的 H3 片段自带配乐，只有 S11 的 H3 音乐是 N/A，需要 gpu3 audio_post 出 BGM（gpu3 侧任务，本轮未动 gpu33）；③ S8 剧本 12 s / S11 10 s 被显存上限截到 8 s，S8 内心独白（TTS 约 14 s）溢出到 S9–S11，片尾静帧保持 4.58 s；④ S10 对白 ASR 回听 CER 0.29（“同事借的”听成“同世界的”）；⑤ 其它镜头的过期旧版本（剧本已改）留在版本链里未删。

## 项目方决定后的调整（02:55，经 fredw-92 转：“长镜头长度模型决定，不限定时长。拍”）
| 轮 | 步骤 | 失败现象 | 根因 | 修复 | 文件:行 | 结果 |
|---|---|---|---|---|---|---|
| 6 | 9 镜预览成片（跳过 S8、S11，等 LS 交回长镜头方案再补） | 直接把剧本删掉两镜交给装配器 → `plan_timeline` IndexError | 装配器默认“第几镜 = Shot.index”定位台词与片段，跳镜后序号不连续 | 新工具 tools/assemble_preview_subset.py：保留镜头重编号 1..n，片段按原序号先 find_source 再经 `sources=` 传入；输出名 `epXX_预览·S8 S11 待补.mp4` + timeline（带 preview_subset），不叫 final、不建别名 | tools/assemble_preview_subset.py（新） | data/episodes/ep02_预览·S8 S11 待补.mp4：9 镜，63.5 s，1524 帧，-14.02 LUFS / -1.84 dBTP；校色（--color-match）9/9 镜都做了 |
| 6 | 先前 11 镜版含 S8 / S11 的 8 s 截短视频 | — | 违反“不得截短” | 改名为 `ep02_PREVIEW_未完成_S8S11截短8秒_勿用.mp4`（+ timeline），未删除；S8 / S11 当前视频版本（frames_capped=true）留在版本链里，待 LS 交回后重出替换 | data/episodes/ | — |

校色结果（ΔE，校色后对首/尾帧）：S1–S7、S10 平均 0.74–2.10；**原 S9 中段 ΔE 9.52、平均 4.09**（片中色偏大，首尾端 <1），建议项目方看一眼 S9。
192 帧上限（h3_video.safe_max_frames）只是临时保护，由 LS 撤掉 / 换成长片卡或分段接力；S8（294 帧）、S11（243 帧）待 LS 交回后补出，再用 `tools/assemble_episode.py ep02 --allow-laptop-video --color-match` 合正式版。
