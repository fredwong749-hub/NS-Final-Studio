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

## 夜间 ND（2026-10-31 03:35 起，SOP 跑通：S2 人物 / 场景 → ep02 补长镜头 → 配乐 → 合成）
驱动：会话 scratchpad `char_driver.py`（人物定妆候选）、`scene_driver.py`（空场景底图候选），状态落盘可续跑。
| 轮 | 步骤 | 失败现象 | 根因 | 修复 | 文件:行 | 结果 |
|---|---|---|---|---|---|---|
| 1 | S2 人物：经 /api/assets/{cid}/gen-jobs 出定妆候选（预设 C + 林晚 LoRA） | gen-jobs 不收 preset / params，只能出 Turbo 默认图、带不了 LoRA | 资产生成没接 PX 的出图参数 | GenBody 加 preset / params / label；@identity = 人物身份 LoRA（auto_lora_triggers），触发词最前；记 effective；新测试 2 例 | services/api/ns_api/asset_edit.py（GenBody、plan_gen、identity_loras、run_gen）；tests/test_asset_gen_preset_nd.py | 03:40 空档重启 API；首批 6 张 03:42 出完（gpu33:0，约 30 s/张） |
| 1 | 自动分道 | 一张林晚候选被自动派到 gpu33:1（fredw-92：今晚 GPU1 借给 fredw-0b 训练） | 自动分配不知道训练借卡（gpu33 上 train.lock.gpu1 只在服务器侧） | 取消该任务，两个驱动改为显式 gpu=0；（系统侧：jobs 自动分道未读训练锁，记为待办） | scratchpad 驱动 | 已改派 gpu33:0 |
| 1 | ep02 配乐：gpu33 `audio_post.py bgm 2` | — | GPU0/1/3 都被占 | AUDIO_GPU_WAIT_MIN=0 → CPU 回退（ACE-Step turbo），不占卡、不动服务 | gpu33:/root/work/fredw/nd/bgm_ep02.log | 进行中 |
| 2 | S2 人物：9 套 × 4 张（林晚 ep02–05、顾沉 ep02–05、陈宇 ep02；ep03 / ep05 草稿无陈宇、ep04 草稿有陈宇人物表但没有他的造型行 → 不出） | 36/36 成功，0 失败，gpu33:0，约 30 s/张；三视（1344×768 横幅）工作流可出 | — | 男角色无身份底板：先用 t2i 出 ep02 正面，再上传为该人物 identity 参考，其余各集各视图都以它为身份参考（同人一致） | data/assets/asset_gens.json（label「候选·待复审 · epNN 定妆 X」、parent = 本集正面 gen） | 拼图 data/ab/night_assets/char_*.jpg |
| 2 | S2 场景：ep02 4 个 + 草稿 3 个（sk_office_elevator / sk_guchen_dining / sk_gu_chen_closet）× main / reverse | 14/14 成功并存为场景底图版本（variant main / reverse，未定稿） | ep02 生产剧本没有场景表：只有 scenes.json 的名称 / 时段 / 光线枚举，sk_taxi 两张都没出成车内（只有“名称：出租车”） | 系统不补写描述（守则）；记为待写作方补 ep02 场景表 | assets/scenes/<id>/versions/ | 拼图 data/ab/night_assets/scenes_ep0N.jpg |
| 2 | ep02 BGM（gpu33 CPU，ACE-Step turbo 8 步，305 s 生成） | 产出 84 s；cue 表 11 镜全是“撤到静默”（S1–S10 H3 已带配乐，S11 剧本写“撤到静默，强度0”）→ 装配时 BGM 实际全程静音，符合 X-4 / E8 | — | — | data/music/ep02.wav + ep02.json（从 gpu33 nsfs_mirror/data/music 拷回） | 等 LS 补 S8 / S11 后合正式版 |
| 3 | fredw-92 转 UXF3 结论：ep01 / ep02 是旧格式，没有场景表原文 | ep02 的 8 张底图只来自 scenes.json 的名称 / 时段 / 光线枚举 | 旧格式剧本无场景表 | 不删文件；8 条版本记录 label 改为「作废候选·ep02 无场景表原文…」，拼图改名 scenes_ep02_作废_无场景表原文.jpg；ep02 底图待写作模型按 v3 补场景表（或重写 ep02）后再出。人物：ep02 只用角色锁 + looks/wardrobe 原文，林晚 ep02 没有服装原文（造型只有发 / 甲 / 妆）→ 列“缺原文、待补” | data/assets/asset_versions.json | — |
| 4 | EB 三道并行验证（05:23，eb_validate.py，只出视频，ep02-S3 / S9 / S10，auto_lock + force） | S3 在 gpu33:1 跑完（746 s）；S9（gpu36:0）、S10（gpu36:1）渲染完成后存版本时失败：`Take.gpu Input should be a valid integer ('gpu36:0')`，两条道各白跑约 14 min | ns_schema.edits.Take.gpu 原来是 int，G36 字符串道 id 存不进 take | 别的 agent 05:32 已改成 `int | str | None`（edits.py:157），05:37 API 重启后生效；本轮不再改 | packages/schema/ns_schema/edits.py:157 | 等 GPU1 训练锁落地后重跑（避免派到借出的 gpu33:1） |
| 5 | EB 第二轮（05:40，S1 / S5 / S9 / S10，auto_lock + force） | S9（gpu33:1，EB 自动派，锁文件当时带点前缀没被识别）、S10（gpu33:0）完成，各 746 s；S1 / S5 在 gpu36 又因 Take.gpu 失败 | API 05:16 起的进程仍是旧 schema（05:32 的修复没加载） | fredw-92 修 jobs.parse_train_locks（`.train.lock` 也算）+ 出发前现读锁，06:08 重启 API | services/api/ns_api/jobs.py（fredw-92） | API 版本问题，不计入加速比 |
| 6 | 四道并行（06:09，video-jobs 显式指定道：S1→gpu36:0、S5→gpu36:1、S3→gpu33:0、S7→gpu33:3） | 4/4 成功，gpu36 的 take 端到端存好（gpu 记 "gpu36:0"） | — | — | data/renders/ep02/S{1,5,3,7}/takes/video_*.mp4 | 墙钟 1562 s，串行合计 4719 s，加速 3.02×；gpu36 渲染 192 帧 1457–1552 s，约为 gpu33 同帧数（S7 927 s）的 1.6 倍（上传只 2–3 s，慢在卡上，原因待 G36 查：--cache-none 每次重载模型 / 两卡同时满载后被压功耗） |

## 长镜头不截短（fredw-92/LS，2026-10-31）

项目方原话：“长镜头长度模型决定，不限定时长。拍”。第 3 轮加的 192 帧上限（h3_video.safe_max_frames / NS_H3_MAX_FRAMES）已删除。
测试镜头 ep02-S8（剧本 12 s），定稿首尾帧 + 剧本 H3 提示词原样（同 video-jobs 代码路径导出，种子 20261031），768×1344，8 步 Turbo。
gpu36 测试实例：GPU2 :8198（/root/work/fredw/longshot/ls.sh、matrix.sh；结果 results.jsonl）；gpu33 只在 :8189 / :8191 队列空时直接投工作流，不改启动参数。产物 data/ab/longshot/（不是生产版本）。

| 配置 | 帧数 | 结果 | 显存峰值 | 墙钟 |
|---|---|---|---|---|
| gpu33 默认（动态显存 + --reserve-vram 1，--cache-ram 常驻） | 243 | 过 | 22.87 GiB | 1310 s（含上传） |
| 同上 + 解码前 VRAM_Debug unload_all_models | 243 | 过 | 22.81 GiB | 1283 s |
| gpu33 默认 | 260 | 过 | 22.87 GiB | 1428 s |
| gpu33 默认 / 出片前 POST /free（空闲 0.38 GiB） | 277 | OOM（MLP fc1，已分配 17.9–18.0 GiB + 要 4.97） | — | 24–27 s |
| gpu33 出片前 POST /free | 294 | OOM（19.12 + 4.97） | — | 24 s |
| gpu36 A --reserve-vram 1（= gpu33 GPU0 参数，--cache-none） | 294 | OOM（19.12 + 4.97） | 23.3 GiB | 18 s |
| B + --disable-pinned-memory | 294 | OOM（同上） | — | 18 s |
| C --reserve-vram 4 + 无 pinned | 294 | OOM（同上） | — | — |
| D --reserve-vram 7 + 无 pinned | 294 | OOM（同上） | — | — |
| E --disable-dynamic-vram --lowvram --reserve-vram 2 | 294 | OOM（20.24 + 4.97） | — | 226 s |
| **F --novram --disable-pinned-memory** | **294** | **过**（294 帧 / 12.25 s，音轨齐） | **12.4 GiB** | **1903 s**（162 s/步，满功耗） |
| **F 同上** | **362** | **过**（362 帧 / 15.08 s） | **15.1 GiB** | **3161 s**（339 s/步，三卡满载被守护压到 200 W） |
| G --disable-dynamic-vram --lowvram --reserve-vram 9 | 294 | 加载结果与 F 相同（0 MB 上卡、19996 MB 外放），229 s/步 @200 W，无速度优势，中途停掉 | — | — |

结论：
- 爆点是 DiT 每层 MLP fc1 的激活（294 帧约 9.4 万 token × 28672 × 2 字节 ≈ 4.97 GiB），不是权重常驻、pinned memory 或 VAE 解码；默认动态显存 / lowvram 都会把一部分权重留在卡上，激活放不下。--novram 让权重全留在内存、逐层上卡，峰值降到 12–15 GiB，362 帧也有约 8 GiB 余量。
- gpu33 视频卡的 --cache-ram 常驻对上限没影响（出片前 /free 后 277 仍 OOM），所以长镜头流程里不加 /free。
- 不需要分段接力（第 2 步兜底方案没有实现）。
- 代价：长镜头道每步慢（--novram 294 帧约 32 min、362 帧约 53 min，200 W 降速时）。gpu33 的 3 条道照常用默认参数，≤260 帧的镜头仍在原道。

落地：
- config/render_endpoints.json：max_frames {"0":260,"1":260,"3":260}（gpu33 实测）；lanes 加 "gpu36:2" {url 18290, max_frames 362, long_only true}。gpu36:0 / :1 没测过，按默认 192。
- gpu36:2 长镜头道：/root/work/fredw/longshot/lane.sh start|stop|restart|status（GPU2 :8190，--novram --disable-pinned-memory --cache-none，PID run/lane.pid，日志 logs/lane.log，输出 comfy/output/gpu2）；隧道沿用 tunnel_gpu36.sh 的 18290。
- 代码：h3_video.frames_for 不再截短（返回剧本帧数）；render 在道上限不够时报错而不是出短版，长镜头等待上限按帧数放宽（timeout_for），take.params 记 method="single"、lane_max_frames；video_jobs.route_long：帧数超过所选道的上限 → 改派能出的道（params.route.rerouted_from），没有长镜头道 → 409；jobs.pick_lane 不把出图和短视频派到 long_only 道；endpoints.max_frames / long_lanes / long_only；Take.gpu 收 "gpu36:2" 这类字符串道 id。测试 tests/test_longshot_ls.py（8 例），全量 934 passed / 6 skipped。
- 生产验证（07:00，API 已在 /api/jobs 空闲时重启）：POST /api/shots/ep02-S8/video-jobs {"gpu":3} → 自动改派 gpu36:2（params.route.rerouted_from = gpu33:3），job 27911bedf883 完成，视频第 2 版 294 帧 = 剧本 12 s，method=single，lane_max_frames=362，render 1645 s（27.4 min），显存峰值 10.53 GB。已知小问题：任务 eta_s 仍按 840 s 估（长镜头道没有历史时偏短），跑过几次后按该道历史中位数自动修正。
| 7 | LS 交付后补 S11 满时长（07:26 video-jobs 不指定道，243 帧 / 10 s，定稿首尾帧 + 剧本 H3 原文）→ 自动派到 gpu33:3 | 成功，1309 s，video v2 | — | — | data/renders/ep02/S11/takes/ | — |
| 7 | 合 ep02 全 11 镜：`tools/assemble_episode.py ep02 --allow-laptop-video --color-match`（每镜用当前视频版本，不新定稿） | 成功；5 条警告：S8 内心独白 13.9 s 越过 S9–S11、S10 回听 CER 0.29、没有 gpu3 qa.json → 按规则命名 PREVIEW | — | 不改命名规则 | data/episodes/ep02_PREVIEW_未完成.mp4 | 1080×1920，85.9 s，2061 帧，-14.1 LUFS / -1.43 dBTP；校色 11/11，S1（ΔE 均值 7.5）、S11（8.1）、S9（3.4）片中色偏大 |
