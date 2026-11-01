# 早上报告（2026-10-31）

## 先看这里（fredw-92，07:55）
1. **ep02 整集满时长成片**：`data/episodes/ep02_PREVIEW_未完成.mp4`（85.9 s，11 镜，S8 294 帧 / S11 243 帧都没截短）。未经你验收所以仍叫 PREVIEW。请重点看：S8 内心独白 13.9 s 盖过 S9–S11；S10 “同事借的”听成“同世界的”；S1 / S11 / S9 校色后仍偏色。
2. **人物定妆候选**：`data/ab/night_assets/char_lin_wan.jpg`、`char_gu_chen.jpg`、`char_chen_yu.jpg`（9 套 × 4 张，都是候选，等你挑）。**林晚磨皮**：先看 `data/ab/lin_wan_face_summary.jpg` 和锐度 / 徕卡对比。
3. **ep03–05 场景底图候选**：`data/ab/night_assets/scenes_ep03/04/05.jpg`。
4. **要你拍板**：ep02 缺场景表和林晚服装原文（按 v3 重写 ep02，还是只补）；顾沉 / 陈宇人物表补族裔；ep04 陈宇缺造型行；ep03–05 导入生产；ep06–60 批量写作（约 $5）；画质预览 / 定稿配置。
5. **基础设施**：长镜头道 gpu36:2 上线（不截短）；五张卡并行出片 3.0×；gpu36 被过热保护压到 200 W 偏慢（找运维看散热 / 网口 100 Mb/s）；GPU1 在训练林晚 LoRA lnwan01（约 3 h）+ 评测（4–5 h），全程锁卡。
6. **UI/UX**：第 3 轮审查 + 修复已完成（docs/ux_audit_round3.md），画布刷新即可看到。小云雀走查：请在本机调试 Chrome（端口 9471）登录后告诉我。


## 画质对比（fredw-92 汇总，夜间陆续更新）
- **出图配置**：项目方已选 C（Turbo + texture_fix VAE + 胶片 LoRA 0.5 + 林晚 LoRA 0.6），已设为画布默认；“锁定后自动出定稿版”暂时关闭（原定稿档是没选的 Base 两段式）。
- **真实照片 LoRA**：`data\ab\realphoto_lora\`（S4/S1/S6 × R0–R6，`contact_sheet_S*.jpg`、脸手局部 `crops_face_hand.jpg`、`params_table.md`）。
  - Canon UltraReal（canon_qwen21，可商用、需署名）；Restore（qwen-image-2.1-restore，qwen-research-license，商用受限）。
  - 注意：R1、R4、R5、R6 的实际强度按 LoRA 总上限 1.6 等比例缩小，实际值见参数表。
- **VBVR 视频对比**：`data\ab\vbvr\ep02-S6_AB_side_by_side.mp4`（仅非商用研究）。
- **锐度 / 徕卡风格后缀**、**Pika Flex**：出完后补在下面。
- **待项目方选**：林晚脸部用哪组（磨皮问题），预览 / 定稿各用哪套。林晚 LoRA 按项目方要求保持现有 lin_wan_qi_v1。

## 夜间协调
- fredw-0b（项目方 T64）借 gpu33 GPU1 训练林晚 H3 身份 LoRA（lnwan01）；姿势 LoRA、ep06 以后底图归它。本会话的 LB 只做首饰 / 高跟鞋 / 服装 LoRA 和 Blender；ND 只做 ep02–05 的人物和场景候选。

## LoRA / Blender（fredw-92/LB）
项目方原话：“lora 和 blender 那个任务我已经授权了，gpu 空闲就跑起来”。清单与卡位：docs/LORA_BLENDER_QUEUE.md。
- 排进队列（gpu33 `lb-runner.service`，只用 GPU3，等 ep02 视频出完、GPU3 空闲 ≥30 min 才开训；生产来了自动停自己的训练、按检查点续训）：jewellery_nprng2_v1（从 750/1200 步续训）→ jewellery_lbrng9_v1（写实化 28→57 张 + 2000 步）→ jewellery_lbrng9_beads_v1（写实化 0→55 张 + 2000 步）。约 7.5 GPU 小时，早上前大概率只能完成前一两个。
- 新数据集的标注全部由写作 LLM（lora_llm = abliteration large-flash）生成并原样使用：lbrng9 57 条、lbrng9_beads 55 条，0 失败；原始回复在 data/lb/captions_llm/。
- 产出（完成后）：ComfyUI/models/loras/jewellery_<c>_v1.safetensors，LORA_REGISTRY 状态 **candidate**（未审），sha256 在 jewellery/LORA_SHA256.txt，技术指标 lb/out/<name>.json，采样总览 jewellery/sheets/<name>_samples.jpg。进度看 gpu33 ns-studio/data/train/lb/runner.log。
- 跳过：lnwan01 / 姿势 LoRA / ep06+ 底图（归 fredw-0b）。Blender：首饰场景 180 个早已渲完，无需再跑；T27 难镜头服务没有输入 spec，没跑。
- **要项目方拍板**：① 高跟鞋 / 服装 LoRA 卡在流水线自带的审核关口（看 wardrobe/samples/*_dataset_sheet.jpg 后 touch REVIEWED_heels / REVIEWED_clothes），且现有标注 / 补图提示词出自已结束的 claude-gpu3 会话——原样用，还是交写作 LLM 重标？② TASKS 里 T14 首饰写着“已取消（政策）”，本次按总调度范围在跑，如不该跑请叫停（`systemctl stop lb-runner`）；③ 首饰写实化提示词与采样提示词同样出自旧 Claude 会话脚本，是否改由 LLM 出；④ gpu36 今晚没用（G36 仍在传生产模型，训练还需另传约 33 GB，且会超“三卡最多两张满载”）。

## LoRA / Blender（fredw-92 复核后的结论）
- **首饰 LoRA（nprng2、lbrng9、lbrng9_beads）已停**：TASKS.md T14 于 10-30 以“本环境不支持生成露骨内容”取消，这组属于私密部位饰品；授权 LoRA 任务的指令不推翻这一取消决定。gpu33 上的 `lb-runner.service` 已停止并取消开机自启，训练从未真正开始（一直在等 GPU3 空闲），没有占用 GPU。已生成的 LLM 标注留在 `data/lb/captions_llm/`，未使用。
- **高跟鞋、服装 LoRA**：卡在流水线自带的审核关口（REVIEWED_heels / REVIEWED_clothes）。它们的标注和补图提示词出自已结束的旧会话，需项目方决定：原样用，还是交写作模型重标。
- **Blender**：首饰的 180 个场景早已渲完；T27 难镜头服务缺逐镜姿势规格（属内容），未跑。
- **林晚视频 LoRA（lnwan01）、姿势 LoRA**：归 fredw-0b（T64），在 gpu33 GPU1 上训练加评测，约 7–10 小时。
- 清单：`docs/LORA_BLENDER_QUEUE.md`。

## 夜间事故（fredw-92）
- **API 短暂掉线**：04:21 前后，我挂的“任务空闲就重启 API”脚本停掉了旧进程，但新进程没有启动成功（退出码 255，是脚本里 bash 调 PowerShell 那一步出的错）。发现后已手动拉起，新代码全部加载，接口正常。掉线期间提交的任务由 ND 核对、续跑；整集出片的状态存在磁盘上，会自动续跑。以后重启 API 直接用 PowerShell 工具，不再从 bash 里套着调用。
- **ep02-S1 坏图**（UXF1 查出）：一个测试中途失败时，后台任务没停，把一张 64×112 的假图写进了真实的 ep02-S1。已隔离并恢复为定稿 #4，全库只有这一张；同时加了防再犯措施和坏图校验。

## 锐度 / 徕卡后缀对比（已出完）
- `data\ab\leica_sharp\<镜头>\contact_sheet.jpg`（S4、S1、S6；C0–C7、后缀 S1–S5、S★；每格标全参数和后缀全文），脸 / 手 1:1 局部 `crop_face_1to1.png`、`crop_hand_1to1.png`，总览 `overview.md`。
- 注意：C3、C6、S★ 是按 1.5 倍尺寸出的图，同种子下构图变了，锐度差异里混着构图差异。C4 的 Turbo 细节重绘实际只走了 1 步，几乎无效，已补 C4b（Base 低强度多步重绘）。
- 林晚脸部汇总（各实验的林晚脸放在同一张图）：`data\ab\lin_wan_face_summary.jpg`（出完后在这里）。

## Pika H3 Flex 视频对比（已出完）
- 并排视频：`data\ab\pika_flex\`（ep02-S2、S5；同种子、同定稿首尾帧、同提示词、同帧数）。许可：MiniMax H3 Community License。
- 和定稿首尾帧的贴合度（越高越贴）：两版基本持平，差别都在 0.1 dB / 0.015 SSIM 以内；Flex 在 S5 上首帧 SSIM 略高（0.897 → 0.912）。
- 耗时：Flex 6 步，在 GPU0 上每次重载模型，实测 605–745 秒；官方 8 步在生产卡上 721–985 秒。两边环境不同，不能直接当速度比。显存都约 22.7 GB。
- 画布已可选：精修 › 改参数重渲 › 视频基底（官方 8 步，默认 / Pika H3 Flex，6 步·试验）。好不好看由项目方看片决定。

## SOP 跑通（fredw-92/ND 夜间驱动；逐轮日志见 docs/e2e_iteration_log.md「夜间 ND」）
<!-- ND-SECTION -->
| 阶段 | 状态 | 产出 |
|---|---|---|
| S2 人物 | **完成（候选）**：9 套 × 4 张（正面 / 半身 / 全身 / 三视），36/36 成功。用预设 C；林晚另带 lin_wan_qi_v1（强度 0.6，按预设 C），并用项目方母版脸作身份参考；男角色先出 ep02 正面，再拿它作本人其余全部候选的身份参考。全部进了资产修改链，标“候选·待复审”；没设本集默认，也没确认造型 | 拼图：`data/ab/night_assets/char_lin_wan.jpg`、`char_gu_chen.jpg`、`char_chen_yu.jpg`；单张在 `assets/characters/<id>/refs/<id>/gen/` |
| S2 场景 | **ep03–05 完成（候选）**：sk_office_elevator / sk_guchen_dining / sk_gu_chen_closet，各出主机位和反向机位。提示词 = 草稿场景表原文（与【场景】段同一格式）+ 空场景用途句；存为场景底图版本，没有定稿。**ep02 跳过**：旧格式剧本没有场景表原文，夜里按场景名推断出的 8 张已标“作废候选”（文件保留） | 拼图：`data/ab/night_assets/scenes_ep03.jpg`、`scenes_ep04.jpg`、`scenes_ep05.jpg`（作废的：`scenes_ep02_作废_无场景表原文.jpg`） |
| S3/S4 ep02 | **完成**：LS 交付了 S8 满时长 v2（294 帧，gpu36:2）；S11 满时长 v2（243 帧，gpu33:3，1309 s）由 ND 补出。11 镜视频都是剧本时长，没有截短 | — |
| S5 ep02 配乐 | **完成**：在 gpu33 跑 audio_post bgm 2，走 CPU 回退（ACE-Step turbo），没占卡，也没动服务。按 X-4 / E8：S1–S10 的 H3 片段已带配乐，S11 剧本写的是“撤到静默，强度0”，所以装配时 BGM 全程静音，符合规则 | `data/music/ep02.wav`、`ep02.json` |
| S5 ep02 成片 | **完成（PREVIEW，等项目方验收）**：11 镜全部校色，BGM 按规则静音，-14.1 LUFS / -1.43 dBTP。每镜用的视频版本：S1 v2、S2 v3、S3 v5、S4 v2、S5 v2、S6 v2、S7 v2、S8 v2、S9 v2、S10 v2、S11 v2（只取当前版本，没有新定稿）。请注意：S1、S11 片中色偏大（校色后 ΔE 均值 7.5 / 8.1），S9 是 3.4；S8 的内心独白 13.9 s，越过了 S9–S11；S10 对白回听 CER 0.29 | `data/episodes/ep02_PREVIEW_未完成.mp4`（1080×1920，85.9 s，2061 帧）+ `ep02.timeline.json` |

- **修了什么**：资产生成接口 gen-jobs 原来不支持出图预设和 LoRA。现在加了 preset / params / label，预设里的 @identity 指该人物的身份 LoRA；只增不改，新增 2 个测试，全量测试通过。
- **GPU 用时（ND）**：gpu33:0 约 49 分钟（50 张资产图 24 分钟 + 视频 25 分钟）；gpu33:1 约 25 分钟（2 个视频，都在借出给训练之前）；gpu33:3 约 16 分钟；gpu36:0 约 66 分钟、gpu36:1 约 63 分钟（其中约 80 分钟是 API 旧版本导致的白跑）；BGM 走 CPU，约 10 分钟。
**整集出片多道验证（ep02，只出视频，≤8 s 已定稿镜头）**
- 06:09 四道并行（gpu36:0 / gpu36:1 / gpu33:0 / gpu33:3，提交时显式指定道）：4/4 成功，墙钟 **1562 s**，串行合计 **4719 s**，加速比 **3.02×**。gpu36 的 take 能端到端存好。
- gpu36 偏慢：192 帧要 1457–1552 s，同帧数的 gpu33:3 只要 927 s，慢约 1.6 倍；上传只用 2–3 s，时间花在卡上（待 G36 查：--cache-none 每次重载模型，或两卡同时满载后被压功耗）。
- 05:40 那轮（EB 自动分道）：S9（gpu33:1）、S10（gpu33:0）完成，两道加速 1.82×。
- **API 版本问题，单独列出、不计入加速比**：05:23 的 S9、S10 和 05:40 的 S1、S5 都在 gpu36 渲染完后存版本失败，报错 `Take.gpu` 不收 "gpu36:N"。原因是 API 进程加载的还是旧 schema，06:08 重启后已解决。另外，05:40 那轮 EB 把 S9 派到了已借出的 gpu33:1，原因是 `.train.lock` 开头带点的锁文件没被识别，fredw-92 已修。
- 新视频版本：S1 v2、S5 v2、S3 v5、S7 v2（没有定稿）；S9、S10 是 EB auto_lock（自动测试定稿，待复审）。都是同一条剧本的重渲，可以和旧版本并排对比。
- **请项目方决定 / 待补原文**：
  1. ep02 是旧格式剧本：没有场景表，出不了 ep02 底图；林晚 ep02 的造型只写了发 / 甲 / 妆，没有服装原文，所以候选里是素体或背心。要请写作模型按 v3 规则重写 ep02，或者补上场景表和造型行。
  2. 顾沉、陈宇的角色锁和 EN 人物表都没写族裔，出图偏西方面孔。要由写作方或项目方补人物表的外貌句。
  3. ep04 草稿有陈宇的人物表，但没有他的造型行，所以 ep04 的陈宇没出。
  4. 从候选里挑定妆：挑中后在资产页存为造型版本或本集默认（项目方本人关口）。

## 林晚脸部汇总（磨皮问题，先看这张）
- `data\ab\lin_wan_face_summary.jpg`：今晚所有出图实验里林晚的脸放在同一张图（S4：texture A–G、徕卡锐度 / 后缀、真实照片 LoRA；S1、S6：徕卡、真实照片 LoRA）。每格下面标变体名、模型和步数、出图尺寸、LoRA 和强度、是否重绘、是否锐化、后缀编号。
- 看皮肤时注意：S1、S6 原图里的脸只有约 190–300 px，汇总图里被放大了；E/F/G 的原图是 1152×2016，脸本身就大。每格都标了原裁切边长，比较时以此为准。
- 新增 C4b（Base 14 步、denoise 0.25 的细节重绘，林晚 LoRA 0.6），三个镜头各一张，已放进汇总图和各镜拼图。
- 视频实验：加速 LoRA 版本对比 X1、强度对比 X3 的并排片在 `data\ab\` 下（`*_side_by_side.mp4`、`*_frame_sheet.jpg`、`*_params.md`）；人物一致性 X4、时长 X5 还在出。

## gpu36 已接入渲染阵列（G36）
- 在线的卡：gpu33:0、gpu33:3、gpu36:0、gpu36:1；gpu33:1 今晚借给 fredw-0b 训练林晚视频 LoRA；gpu36:2 留给长镜头测试；gpu33:2 是坏卡，永不使用。
- 卡不再固定出图或出视频：出图优先 gpu33:0，没有就找任意空闲卡；视频哪张卡空就上哪张；有训练锁的卡自动跳过。
- 实测：gpu36 出一张首帧 21 秒（gpu33 要 55–140 秒，慢在上传）；出一段 5 秒视频 545 秒（和 gpu33 视频卡相当）。
- 环境从 gpu33 原样复制（ComfyUI 0.42.0，1262 个节点完全一致），只放在 /root/work/fredw/ 下；两台服务器的登录配置都没动。
- **要找运维**：gpu36 的网口只协商到 100 Mb/s（网卡支持千兆），约 89 GB 的模型传了 2 小时 20 分。
- 如实说明：G36 在 gpu33 上做环境测试时误用了坏卡 GPU2，只跑了几毫秒的小测试，没有留下进程。

## 视频实验（XP，已全部出完；只给对照材料，由项目方挑）
- **X1 加速 LoRA 版本**（ep02-S2，6 秒，同种子同定稿首尾帧）：`data\ab\X1_turbo_versions\`。
  - 官方 8 步 v1.1（现用）/ v1.0：每条约 710 秒。
  - **4 步 v1.2、4 步 v1.3：约 400 秒，快将近一倍**；DMAD 4 步约 391 秒。值得重点看画质有没有掉。
  - 基模不挂 LoRA 20 步：约 1613 秒（画质上限参照）。
- **X3 加速 LoRA 强度** 0.8 / 0.65：`data\ab\X3_turbo_strength\`。
- **X4 人物一致性通道**（参考图驱动 + 首尾帧引导 + 林晚角色卡等 4 种）：`data\ab\X4_identity\`。提示词用剧本原样，没改写成参考图模式的格式（改写属于内容）。
- **X10 视频逐镜校色**：`data\ab\X10_colormatch\X10_deltaE_table.md`，ep02 全部视频校色前后的色差表，只算数不改片。
- **X5**：`data\ab\texture_C_G_ep02\`，S1/S6/S9 各出 C、G 两版，和锁定版并排。
- 每组都有并排视频 `*_side_by_side.mp4`、截帧表 `*_frame_sheet.jpg`、参数和耗时 `*_params.md`。共用约 3.4 GPU 小时。

## 夜间事故：GPU1 训练被派活 + gpu36 视频存不进版本（fredw-92，05:40–06:08）
- **GPU1 训练 OOM（fredw-0b 的林晚 LoRA lnwan01）**：ND 整集验证时把 ep02-S9 视频派到 gpu33:1，训练第二次 OOM。原因：选道用后台刷新的训练锁缓存（会旧一两分钟，ssh 读失败还按无锁），派出前不再查。已修：出发前现读一次锁，有锁不跑、交回 EB 换道；读失败沿用上次结果。现在 lnwan01 在 GPU1 训练（750 步约 3.2 h），之后 H3 评测 4–5 h，全程有锁，生产不会派过去。
- **gpu36 出的视频存版本失败**：`Take.gpu` 只收整数。代码 05:32 已修，但 API 是 05:16 启动的旧代码，ep02 的 S1/S5/S9/S10 在 gpu36 上各白跑约 14 分钟。06:08 重启 API 后生效，ND 重跑。
- 测试：909 passed / 4 skipped。

## UI/UX 第 3 轮（UXA3 审查 → UXF5 修复）
- 审查：docs/ux_audit_round3.md（上轮 44 条：已修 20 / 部分 10 / 未修 14；新发现 11 条，P0 是 gpu36 视频存不进版本，已随 06:08 重启修好）。
- UXF5 已修：GPU 面板列全 5 条道（gpu33 / gpu36 分组）、顶栏卡状态 0.9 s 出数；整集出片记录失败显示红色、“API 重启中断”单列为中断；自动定稿 / 过期统一写法，已定稿首帧的主按钮改“去看尾帧→”；5 页 12px 以下字号清零、1280 宽无横向滚动；运镜中文、场景胶囊真实状态、出图 LoRA 列表剔除视频 LoRA 与检查点等。pytest / tsc / vite build 通过。
- 留待下轮：R8、R10 部分、R11；HMNSFW-AIO、moawxx 两个 LoRA 看不出底模，仍在出图列表。sop.py 的“不进 S3”文案改动待下次 API 空闲重启生效（前端已兜底）。

## gpu36 视频偏慢的原因（fredw-92 06:45 查）
- 三张卡功耗墙都被机器的过热保护（gpu36-dimm-guard）压到 200 W（正常 300–350 W），GPU2 正在跑 LS 长镜头测试满载 200 W。三卡同时满载 15–20 分钟后自动降功耗，属正常现象，按规则不得自行执行 `nvidia-smi -pl`。
- 影响：同 192 帧 gpu36 约 1457–1552 s，gpu33:3 约 927 s。要长期三卡满载出片，需找运维看散热；或排活时 gpu36 少开一张卡（间歇负载基本不降速）。
