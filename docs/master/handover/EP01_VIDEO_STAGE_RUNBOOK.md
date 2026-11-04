# EP01 尾帧 → 视频 → 整集预览 Runbook（W41，2026-11-04）

> 给 W38（ep01 主线）用。三段都在真机（gpu33:1，producer 不用的道）以**沙箱**实跑过一遍：生产 takes.json / producer 状态一个字节没动。
> 沙箱驱动 `tools/master/video_stage_trial.py`（镜目录复制到 `data/_w41_trial/renders/series10_v2/`，`NS_RENDERS_DIR` 指过去，跑生产同一份代码）。
> 实测数字见文末「实测记录」。

> **03:0x 项目方硬规矩**：看图打分 / 人数检测 / 出图 / 尾帧 / 视频一律在 gpu33 / gpu36 上跑，笔记本只编排、推文件、读结果。
> 下面生产命令都符合（producer 在 gpu33；vidgen + score_clip 在服务器）。W41 沙箱试跑里**笔记本算的两项不算数**：尾帧的 G1 视线（0j 那个 bug）和视频试跑的 motion_qc 运动量；尾帧 Q1–Q8 是 gpu33 GPU 测的（measured_on gpu33 3090），算数。
> `video_stage_trial.py` 的视频运动量检查以后要搬到服务器（score_clip）才算；整集预览合成（x264 / TTS / ASR）现在还在笔记本 CPU，是否也要搬请总调度定。

## 0. 开工前必须知道（这次踩到的坑）

| # | 坑 | 现状 |
|---|---|---|
| 0a | **V2 takes.json 混进 V1 林晚版本并被设为当前**（S8/S10 active.image/last/video、S9 active.last）。STATE“尾帧 ✅ S10”是 V1 误计 | 已摘 7 个 active 指针（take 条目不删，备份 `takes.json.bak-w41`，明细 `data/quarantine/series10_v2/v1_active_pointers_w41.jsonl`）。**S8/S10 现在没有当前首帧/尾帧，要重出** |
| 0b | `build_jobs.passed_frames / passed_lasts` 不查剧前缀 → 视频会拿 V1 首尾帧出 V2 片 | 已修：只认 `renders/<本剧>/epNN/SN/` 前缀（失败关闭） |
| 0c | **V2 视频变体 preflight I11 必 fail**：首帧输入 JPEG 在 `data/pipeline/runs/series10_v2/video/inputs/`，不在资产包允许目录 → vidgen 一条都不提交 | 已修：`asset_refs.manifest_derived_dirs` 放行本剧 `video/inputs/` |
| 0d | vidgen 在 gpu36 上按 PORTS 用全部三道，含 **gpu36:2 坏卡**（没在 shared_lanes → 专用道每道 2 个） | 已修：`vidgen.usable_lanes` 按 hosts.json（enabled / roles / broken_gpus）+ 写死坏卡过滤 |
| 0e | `assemble_series.py --preview` 在 V2 没 `video/hosts.json` 时 FileNotFoundError；占位首帧只找 `images/frames/`（V2 不用）→ 全黑 | 已修：没 hosts.json = 不读服务器；占位取本剧 takes.json 当前首帧（只认本剧前缀）；加 `--out-dir` |
| 0f | 第 0a–0e 的修复都在笔记本树里，**服务器要等下次 cut + deploy 才拿到**（vidgen 跑在服务器上；producer 出图/打分也在服务器） | 待总调度入版 |
| 0g | **S10 的 V2 首帧没有一版过契约**（1/2/9/10/11/12 全是 Q2 造型 fail：白吊带 + 银灰缎面短裤 clip 0.73–0.78 < 0.83；n=12 另有 Q9 fail“唐瑶右眼瞳孔朝向镜头”）→ producer 不会做尾帧、build_jobs 不会派视频 | 内容问题，W38 主线处理（重出 / 造型参考 / Q2 阈值裁定） |
| 0l | **服务器（gpu33）takes.json 的 S3 / S5 active.image 是 V2 内容但文件在 V1 前缀**（`renders/ep01/S3/takes/image_001_0cf507ca…`，11-03 21:48 旧版 producer 写的，W33 前的路径 bug）。0b 的前缀闸门入版后，这两镜会被**挡在视频外**（失败关闭） | deploy 前先做 W33 追加（把 V1 目录里的 V2 图迁回 `renders/series10_v2/` 并改 take.file），或 W38 重出这两镜首帧 |
| 0j | 笔记本上跑 producer 时，`_postflight` 只把 gpu33 的 `host_path` 交给 `remote_score.postflight_full` → 本机算的 G1 视线 `cv2.imread` 服务器路径 →“G1 读不到图”，Q9 看图也拿不到图 | 已修：host_path 不在本机时同时给本机交付图 `file`（服务器上行为不变） |
| 0k | 试跑视频内容问题：S10 提示词写“gold-chain clutch … beyond the frame”，Pika 在片中段让**一只手从画面上方拎着金链包伸进来** | W38 / 写手：改提示词（别让画外物体被“看向”时具象化），或接受重出 |
| 0h | 视频政策 L-088 = **只用 Pika（`i2va_pika_flex`，只给首帧）**；尾帧现在不是视频输入（配方没有 `@last_frame`）。尾帧只给 sop_gate“尾帧”阶段 + 审片用 | 照政策 |
| 0i | sop_gate“整集预览”阶段只认 `data/episodes/series10_v2/ep01*.mp4`（night.py finalize 产物）；`assemble_series --preview` 的 `_final/preview_latest.mp4` **不算过闸** | 记录；要过闸走 night.py |

## 1. 尾帧

**生产一条命令**（W38 用）：不用手动——gpu33 上 `producer.py serve` 自动派。条件：`control.json only` 含该镜、道不在 `hold_lanes`、本镜首帧**当前版本** `postflight.ok`（否则报“首帧没有过契约的当前版本，不能做尾帧”）。
手动单镜（服务器上）：`producer.py once --only ep01-S10 --wait`。

**试跑（沙箱，不动生产）**：
```
.venv/Scripts/python.exe tools/master/video_stage_trial.py last --shot ep01-S10 --lane gpu33:1 --first-n 12 [--force]
```
- 代码路径 = `producer.FrameExec.render("last", …)`：`frame_job.build_first` → `build_last(首帧当前版本)`（图1 首帧 + 图2 身份脸，提示词 = 编译器 last_prompt）→ `unified_frame._run` → `pipeline._add_take(activate=False)` → 后台 `_postflight`（gpu33 远端打分 Q1–Q8 → 失败退笔记本 CPU）→ `vqa_gate`（Q9 看图 8870/8871）→ `auto_current.on_contract` 过了才设为当前。
- 产物：`data/renders/series10_v2/ep01/S10/takes/last_NNN_<tag>_raw.png` + `_raw_post.png`；takes.json 追加 `{"stage":"last","n":N,"file":"renders/series10_v2/ep01/S10/takes/last_…_raw_post.png","path":"unified_frame（K-REN-134）· PRODUCER","postflight":{…}}`，过契约 → `active.last = N`。
- 常见错：
  - `首帧没有过契约的当前版本` → 先解决首帧（0g）。
  - `ComfyUnavailable: /upload/image: ConnectionResetError` → 隧道抖，producer 当基础设施错退避重派；手动重跑即可（本次第 2 次就是这个）。
  - `cv::findDecoder imread_('…/output/gpu1/ns_final/…png')` 远端打分读原始输出偶发失败 → postflight 自己重试 3 次再退笔记本 CPU（慢，约 +3–4 分钟）。
  - 看图 `8870 refused` → 正常（笔记本上走 8871 隧道）；两个都不通 → Q9 untested，不设为当前。

## 2. 视频

**生产一条命令**（笔记本）：
```
.venv/Scripts/python.exe tools/series10_video/night.py --run series10_v2          # 常驻；--once 跑一轮
```
night 每 120 s：本集**每镜**首帧都“当前 + postflight.ok + Q9 过 + Q10 出图后验收 pass + 本剧前缀”才就绪（或 `night_control.json` 的 `force_eps` 放行）→ 选机写 `video/hosts.json` → `build_jobs`（编 `jobs.json`）→ deploy 推作业 + 输入图 → 服务器 `vidgen.py run <host> --run series10_v2` 出片、打分（score_clip，venv_idm）→ sync 拉回 `data/pipeline/runs/series10_v2/video/clips/ep01/ep01-SN__<变体>_s<seed>.mp4`（sop_gate“视频”阶段就看这个目录）。

**试跑（沙箱单镜）**：
```
.venv/Scripts/python.exe tools/master/video_stage_trial.py video --shot ep01-S10 --lane gpu33:1 --first-n 12 [--dry] [--force]
```
- 编译 = `build_jobs.compile_variant`（生产同一份；配方按 video_policy 派生 = `i2va_pika_flex`）→ 硬规矩检查 → 直接提交到道 → 取回 mp4 → ffprobe 时长 / 抽尾帧 / 运动量 → 沙箱 takes.json 登记一版 video（不设为当前）。
- 硬规矩（`hard_rule_check`）：C-08 单镜 ≤6 s（spec 秒数 + 帧数/24）；C-06 提示词不许要求看镜头；C-07 不许出现字幕类词；L-141 单镜作业里不许 `At MM:SS` 时间戳。
- Q9：视频只用 Q9 过的首帧（`build_jobs._q9_ok`，`config/vqa.json gate.video_requires_q9=true`）。报告里 `first_q9_passed`。
- 常见错：
  - preflight `I2 视频必须用已通过 Q1–Q7 的首帧` → 首帧没过契约（0g），生产不会派。
  - preflight `I11 … video/inputs/… 不在资产包清单` → 0c，服务器未入版前仍会挡。
  - `no_first_frame` / route `waiting_frame` → 该镜首帧没进 passed_frames（看 jobs.json `anomaly_skipped` 写的原因）。
  - `no_last_frame:stale_pair` → 只在送尾帧的配方（Pika 不送）。

## 3. 整集预览

**生产（过 sop_gate 闸）**：night.py 在本集每镜都定下（通过 / 尽力）后自动 finalize：服务器出 540×960 代理 → 拉回 → `tools/assemble_episode.py ep01 --sources-from <timeline> --out data/episodes/series10_v2/_work` → `data/episodes/series10_v2/ep01_vN.mp4`（sop_gate check_preview 认这个）。

**随时看效果（不过闸）**：
```
.venv/Scripts/python.exe tools/assemble_series.py ep01 --preview [--no-pull] [--out-dir <目录>]
```
→ 默认 `data/renders/series10_v2/ep01/_final/preview_latest.mp4 + .srt + _manifest.json`；没视频的镜 = 本剧当前首帧缓推占位，再没有 = 黑场。
- 沙箱试跑：`tools/master/video_stage_trial.py preview --shot ep01 --no-pull` → `data/_w41_trial/preview/ep01/`（沙箱里有 W41 试跑视频的镜自动换进去）。**试跑别写生产 `_final/`**：retro_tick 看到整集预览就会生成 / 自动 done 复盘。
- ffmpeg：Windows winget Gyan.FFmpeg 9.0.2（PATH 里的 ffmpeg / ffprobe）；x264 CPU 编码，不占 GPU。
- 时长核对：manifest `shots[].duration_s` 之和 = ffprobe 时长（试跑 64.0 = 64.0）；每镜 ≤6 s。
- 字幕：不烧录，只出外挂 .srt（L-002）；ffprobe 只有 video + audio 两路流。
- 副作用：`--preview` 每次重建 `data/cache/tts_preview`（工具自己的临时缓存）。
- 常见错：`bgm: no file` → V2 ep01 还没有集级 BGM（`data/music/series10_v2/`，music_v2.json）；`H3 原声对白回听不合格（no H3 audio）→ TTS 兜底` 占位镜正常。

## 4. 复盘（episode_retro）

```
.venv/Scripts/python.exe tools/master/episode_retro.py --run series10_v2 --episode 1 [--dry]     # 生成 docs/master/RETRO_ep01.md
.venv/Scripts/python.exe tools/master/episode_retro.py --run series10_v2 --episode 1 --auto      # 常驻同路：整集预览在才生成
.venv/Scripts/python.exe tools/master/episode_retro.py done --run series10_v2 --episode 1
```
- 输入：`episode_metrics.collect`（本集指标 + 上一集对比）、`data/pipeline/issues.jsonl` 本集卡点、git 本集开工以来 `config/ knowledge/ PIPELINE_SOP_V2.md` 的改动、sop_gate `check_preview`（= `data/episodes/series10_v2/ep01*.mp4` 存在）。
- `--auto` / 常驻 retro_tick：没整集预览片 → skip；有 → 生成并按 `config/pipeline/sop_gate.json retro_auto_done` 自动 done（ep02 进出图的闸门）。

## 不靠沙箱的复核（02:4x，总调度令）

- `producer.py status --run series10_v2`（gpu33 上，只读）：心跳正常；ep01 首帧 4/11、尾帧 2/11、视频 0/11。
- `night.py --run series10_v2 --once`（笔记本）：按 partition 写 `video/hosts.json`（ep01→gpu33）+ `night_state.json`；sop_gate 挡 ep01 进视频（出图 4/11），**没派任何作业**。
- `assemble_series.py ep01 --preview --no-pull`（笔记本，写生产 `_final/`）：2 m 46 s，64.0 s；S2 / S6 用本剧当前首帧占位（0e 新逻辑），其余黑场。
- gpu33:1 已按总调度令从 producer `hold_lanes` 放回（这条 hold 是 01:43 NETFIX dispatch 写的，下一轮可能写回）。

## 实测记录（2026-11-04，gpu33:1，沙箱）

沙箱驱动报告：`data/_w41_trial/logs/<cmd>_ep01-S10_<时间>.json`；沙箱产物在 `data/_w41_trial/`（只增不删）。

| 段 | 实跑命令 | 耗时 | 产物 | 结果 |
|---|---|---|---|---|
| 尾帧 | `video_stage_trial.py last --shot ep01-S10 --lane gpu33:1 --first-n 12 --force` | 渲染 89 s（GPU 39.9 s，含上传参考）+ postflight 262 s（远端打分 + 本机 G1/Q9），合计 5 m 53 s | `data/_w41_trial/renders/series10_v2/ep01/S10/takes/last_004_5b8c067c_raw(_post).png`；沙箱 takes.json `last n=4`，`path=unified_frame（K-REN-134）· PRODUCER`，postflight 已写 | 契约不过：Q2 造型 clip 0.742 < 0.83；G1“读不到图”（= 0j，已修）；Q9 因前置不过未看图 → `current: keep`（不设为当前），与生产行为一致。第 1 次试跑同样出了图（6 m 11 s），第 2 次死在隧道 `ConnectionResetError` |
| 视频 | `video_stage_trial.py video --shot ep01-S10 --lane gpu33:1 --first-n 12 --force` | 编译 0.1 s；提交到取回 369 s（含 H3/Pika 模型加载、排在尾帧后、经隧道下载） | `data/_w41_trial/renders/series10_v2/ep01/S10/takes/video_002_w41.mp4` + `_last.png`；沙箱 takes.json `video n=2`（`params.w41_trial`，不设为当前） | 配方 `i2va_pika_flex`（只给首帧）；124 帧 = **5.167 s**（spec 5.0 s，≤6 ✅）；768×1344 @24 fps，video+audio；硬规矩 C-06/07/08/L-141 全过；运动量 pass；preflight 只剩 I11（沙箱输入路径；生产路径已修 0c）+ 首帧 I2；**首帧 Q9 = fail**（生产不会派）；内容见 0k |
| 整集预览 | `video_stage_trial.py preview --shot ep01 --no-pull`（= `assemble_series.build(…, preview=True, out_dir=沙箱)`） | 41 s（全占位）/ 93 s（含 1 镜视频） | `data/_w41_trial/preview/ep01/preview_latest.mp4 + .srt + _manifest.json` | 63.0 s = 各镜之和 63.0 s ✅；1080×1920 @24 fps；−14.13 LUFS；无字幕流 ✅；S10 = 试跑视频（剪辑规则后 4.0 s），其余 10 镜黑场（ep01 现在没有一镜有本剧当前首帧）；BGM“no file”；7 句 TTS 兜底 |
| 复盘 | `episode_retro.py --run series10_v2 --episode 1 --dry` / `--auto --dry` | 数秒 | 只打印 | `--dry` 能出全文（指标 / 101 条卡点 / 规则改动）；`--auto` → `skip: 整集预览还没出`（它认 `data/episodes/series10_v2/ep01*.mp4`，见 0i） |
