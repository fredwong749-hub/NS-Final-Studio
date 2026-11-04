# EP01 视频齐 → 整集预览 → 复盘 done：自动接力验收清单（W46，2026-11-04）

> 接 `EP01_VIDEO_STAGE_RUNBOOK.md`（W41：尾帧 / 视频 / 预览三段）。本篇只管最后两关：**视频齐 → night finalize → `data/episodes/series10_v2/ep01_vN.mp4` → sop_gate“整集预览” → episode_retro --auto → done**。
> 全程在 gpu33 沙箱 `/root/work/fredw/w46/repo` 实跑（生产仓库整份复制、`config/factory/hosts.json video_root` 改指副本），跑的是生产同一份 night / vidgen / 合成 / 复盘代码；生产 takes.json、`data/episodes` 正式目录、生产 night_state 一个字节没动。
> 实测数字见文末「沙箱实测」。

## 0. 这次查出并修掉的断点（生产上不修就到不了“整集预览”）

| # | 断点 | 现象 | 修法（文件） | 生产状态 |
|---|---|---|---|---|
| F1 | **两台服务器都没有 `data/assets/voices_v2/`**（音色参考音频，15 MB） | night finalize 第一步 `voices_ok()` → `run_media.voice_config` sha 校验失败 → 本集 `hold_voices` | ① 03:4x 已把笔记本那份原样补到 gpu33 / gpu36 生产仓库（目录原来不存在，只增不覆盖；sha 与 voices_v2.json 一致）；② `resident_sync.run_sync_sources` 加 `run_media_dirs()`：按 voices_v2.json / music_v2.json 登记的目录 + `data/music/<剧>` 一起推（以后换音色自动跟上） | ① 已生效；② 笔记本树，resident_sync 重启后生效 |
| F2 | `hold_voices` 是死胡同 | `retry_assembly` 只救 `hold_tts` / `assemble_failed`；音色后到 → 本集永远不合成 | night.retry_assembly：`hold_voices` 且 `voices_ok()` → 回 `rendering`（下一轮 EP_RESOLVED → finalize） | 笔记本树，待 hf / cut |
| F3 | **vidgen 的 SOP 闸门整份控制文件一起判**（control eps=[1,2,4,6,8] 里 ep02 没过 → 整个 vidgen 抛 SopGateError 秒退；gpu36 04:42 实测：DISPATCH 后 0 条提交） | 视频阶段与 finalize 的 `vidgen proxies` 都被挡 | **W38 hf-20261104-10** 在 sop_gate.vidgen_guard 改成按 `video_shots_ok`（有镜可进就放行）——两台已是这一版（sha 4d4d169790b6）。W46 自己那版 vidgen.py（按整集判，更严）04:5x 上过 gpu36 几分钟后已还原为 hf-05（7eacb7b44d10），笔记本树同步还原 | ✅ 生产已生效（04:53 起 vidgen pid 304514，04:56:45 S2/S3 提交 gpu36:0/1） |
| F4 | 复盘没人跑 | episode_retro 文档写“常驻 autoflow_resident.retro_tick 每 10 分钟”，但代码和 git 历史里都没有 retro_tick → 预览出了也不生成复盘，ep02 出图永远卡“第1集复盘：missing” | night.finalize 成片进 `data/episodes/<剧>/` 后立刻 `retro_after_assembly()` = `episode_retro.auto()`（与 `--auto` 同一条路：生成 / 登记跟进 / 按 `retro_auto_done` 自动 done），结果写 `night_state.eps.N.retro` | 笔记本树，待 hf / cut |
| F5 | 成片层没有硬规矩 | 合成片不管多长、有没有字幕都进 `data/episodes/` → sop_gate“整集预览”直接放行 | night.`episode_hard_rules()`（进 `data/episodes/<剧>/` 之前，失败关闭）。**挡**：C-08 每镜 `duration_s` ≤ 6 s（末镜尾帧定格不算）；C-07 无字幕流（ffprobe + `ffmpeg -i` 判 Subtitle，壳看不见字幕流）+ timeline `subtitles=false`；有视频流；L-092 按**剧本**集长（`script_duration_s` 之和）60–120 s。**只记**（`hard_rules.warnings`）：合成实长不在 60–120 s（剪辑按运动量 / 对白修头尾：真 Pika 片 5.17→4.0 s）、合成器 `gates.verdict=fail`（对白溢出）。不过 → `assemble_failed`，片留 `_work/` | 笔记本树，待 hf / cut |

| F6 | **服务器 ffprobe 是兼容壳**（`/root/work/fredw/tools_bin/ffprobe` ← `tools/series10_video/ffprobe_shim.py`，`offline_20261101/bin/ffprobe` 链过去），只认 2 种写法，别的输出 `{}`；gpu36 根本没有真 ffprobe | finalize 合成必死：`ns_post/ffmpeg.py count_frames`（`-count_packets -show_entries stream=nb_read_packets -of csv`）→ `ValueError: '{}'`（沙箱 04:10 实测 assemble rc=1） | ffprobe_shim.py：本机有能跑的真 ffprobe（gpu33 `/root/claude-kimi-ns-studio-v1/env/ffmpeg/bin/ffprobe` 9.0.2；`NS_REAL_FFPROBE` 可指定）→ 直接 exec 真的；没有（gpu36）→ 通用仿真：`-select_streams`、任意 `-show_entries`、`-count_packets/-count_frames`（ffmpeg 解码数帧）、`-of json/csv/default`，子进程全带 timeout。gpu33 真 / 仿真结果一致（124 帧、768,1344、24/1）；gpu36 仿真实测 158 帧（旧壳 `{}`） | 笔记本树；生效要 deploy.py 把它拷到两台 `tools_bin/ffprobe`（W38 hf） |
| F7 | dejudder 宽高用壳不认的写法 | 每条片先跑 4–5 分钟 minterpolate 才报错 → 全集不去抖、不放大（原片 768×1344 进合成），finalize 白耗 ~50 分钟 | tools/dejudder.py `video_wh()`：`-show_streams -of json`（壳认得），并挪到最前（失败立刻失败）；真片 S10 实跑 rc=0（187 s，5.17 s 768×1344） | 笔记本树，待 hf / cut |

测试：`tests/test_w46_finalize.py`（F1②–F7 + 中继 + run_sync sha，见文件头）+ 改 `tests/test_night_v2_finalize.py::test_finalize_v2_reaches_assembly`（假 mp4 读不了时长 → 打桩硬规矩与复盘，只测合成路径）。
gpu33 实跑（W45 `tools/qa/remote_pytest.py`）：W46 全过；同批 4 条旧用例失败 = 服务器没有 `data/music/v2_style/*.flac`（曲库 179 MB，见第 3 节 G3），与本轮改动无关。

## 1. 生产自动接力（谁、在哪台、看什么文件）

```
producer serve（gpu33，常驻）
  └─ 首帧 / 尾帧定稿 → sop_gate“视频”阶段过 → night 的 ready_shots 有镜
night.loop_once（gpu33：night.py 常驻进程；没有 night 进程且 night_state.json ≥20 分钟没更新 → producer video_takeover 后台线程跑同一函数）
  ├─ dispatch_hosts：build_jobs → deploy push/control/start → vidgen run gpu33（逐集过 SOP，F3）
  ├─ 每轮：sync.py（服务器上 = 本机，空转）→ register_takes.py（视频进 takes.json active.video）
  ├─ ep_resolved：jobs.json 本集每镜 state_gpu33.json status ∈ done/best_effort/blocked → EP_RESOLVED
  └─ finalize(ep)：voices_ok（F1/F2）→ tts_missing → vidgen proxies → upscale_preview（去抖 + 放大，CPU）
       → assemble_episode.py --run <剧> --sources-from …/sources.timeline.json --dialogue-source h3 [--no-bgm]
       → episode_hard_rules（F5）→ 复制到 data/episodes/<剧>/epNN_vN.mp4（+ .timeline.json）
       → director/finish.py → episode_report.py → bgm_library（剪辑锁定后带 BGM 自动重合成 ≤2 次）
       → retro_after_assembly（F4）= episode_retro.auto → docs/master/RETRO_epNN.md（主剧）retro_status: done
sop_gate.check_preview：data/episodes/<剧>/epNN*.mp4 存在 → “整集预览”✅；retro_state=done → 第 N+1 集“出图”放行
```

### 验收清单（逐条有文件 / 日志可查，全部在 gpu33 生产仓库 `/root/work/fredw/offline_20261101/repo`）

| # | 检查 | 看哪里 | 通过标准 |
|---|---|---|---|
| A1 | 视频齐 | `data/pipeline/runs/series10_v2/video/state_gpu33.json` | ep01 每镜 `status` ∈ done / best_effort / blocked；`video/clips/ep01/ep01-SN__*.mp4` 每镜都有（sop_gate“视频”同口径） |
| A2 | night 在接 | `video/night.log` | 有 `EP_RESOLVED ep01`；没有 night 进程时 producer 日志有 `video_takeover` |
| A3 | 音色 / 配音 | `video/night.log` | 没有 `HOLD ep01` / `HOLD_TTS`；有就看 `night_state.json eps.1.hold_why`（F1：`data/assets/voices_v2/` 要在） |
| A4 | 代理 / 原片 | `video/night.log`、`video/episodes/ep01/manifest.json` | `proxies ep01 {"with_proxy": 11}`；没有 `ASSEMBLE_BLOCKED` / `ASSEMBLE_WAIT` |
| A5 | 合成 + 硬规矩 | `video/night.log` | `assemble ep01 0 …` 然后 `HARD_RULES ep01 pass`（集长 60–120 s、单镜 ≤ 6 s、无字幕流） |
| A6 | 整集预览 | `data/episodes/series10_v2/ep01_vN.mp4` + `.timeline.json` | 文件在；`sop_gate.py status --run series10_v2` ep01“整集预览”✅ |
| A7 | 复盘 | `video/night.log` `RETRO ep01 …`；`docs/master/RETRO_ep01.md` | 头部 `retro_status: done --> <!-- done_by: retro_auto`；night_state `eps.1.retro.done` = “自动 done：第 2 集可以进出图” |
| A8 | 下一集放行 | `sop_gate.py status --run series10_v2` | ep02“出图”不再报“第1集复盘：missing” |

卡住时的人工命令（都在 gpu33 生产仓库，`$PY=/root/work/fredw/offline_20261101/venv/bin/python`，`export OFFLINE_SELF=gpu33 NS_RUN=series10_v2`）：
```
$PY tools/series10_video/night.py --run series10_v2 --once                    # 跑一轮（night 常驻在就别手动跑，等它）
$PY tools/master/episode_retro.py --run series10_v2 --episode 1 --auto         # 复盘补跑（预览在才生成）
$PY tools/master/sop_gate.py status --run series10_v2
```

## 2. 沙箱怎么复现（不动生产）

```
# 笔记本：建副本（gpu33 上 cp 生产仓库，data 只带 series10_v2 相关）+ 推笔记本树改动 + hosts.json video_root → 副本
# gpu33：
source /root/work/fredw/w46/env.sh     # OFFLINE_SELF=gpu33 NS_RUN=series10_v2 NS_FINALIZE_TRIAL_OK=1 PATH 带 ffmpeg；cd 副本
$PY tools/master/finalize_trial.py prep --run series10_v2 --ep 1 --real ep01-S10=/root/work/fredw/w46/inputs/video_002_w41.mp4
$PY tools/master/finalize_trial.py loop --run series10_v2 --ep 1      # = night.loop_once，只把 dispatch_hosts 换成记日志（不派 GPU）
$PY tools/master/episode_retro.py --run series10_v2 --episode 1 --auto
```
- `finalize_trial.py prep`：按导入稿逐镜写 `video/clips/ep01/<镜>__w46_s0.mp4`——S10 = W41 真 Pika 片（5.167 s）；其余 10 镜 = 本剧该镜首帧缓推代片（`w46_standin`，时长 = 导入稿 duration_s，768×1344@24 + 静音轨），再写 vidgen 出完的 `jobs.json` / `state_gpu33.json`（每镜 done）和 `night_state.json`（ep01 rendering）。**代片只验管线，不是内容。**
- 守卫：ROOT = 生产仓库或没设 `NS_FINALIZE_TRIAL_OK=1` → 拒绝运行。

## 3. 生产上还差什么才能无人自动走完（具体到文件 / 事件）

| # | 差什么 | 卡在哪个事件 | 谁 / 怎么补 |
|---|---|---|---|
| G1 | F2–F5 的代码（night.py、vidgen.py）还只在笔记本树 | 生产 night（gpu33 pid 328822，13:10 EST 起）跑的是旧 night：没有复盘接力（F4）、硬规矩（F5）；vidgen 旧闸门（F3）会在 ep01 进视频时整个退出 | 总调度 / W38 走 hf（night.py + vidgen.py，推 gpu33 + gpu36，.bak 回退）或下一次 cut；night 常驻要重启才换代码（producer 的 video_takeover 也 import 同一份 night） |
| G2 | resident_sync 的 `run_media_dirs`（F1②）在笔记本树 | 以后换音色 / 加 BGM 不会自动到服务器 | 笔记本 resident_sync 重启后生效（这次的 voices_v2 已手工补齐，不挡 ep01） |
| G3 | **服务器没有 V2 曲库 `data/music/v2_style/`（179 MB）**，也没有 `data/music/series10_v2/` | finalize 照常合成（`--no-bgm`）；剪辑锁定后 `bgm_library` 交不出集级 BGM → 预览没有 BGM（不挡“整集预览”/ 复盘） | G2 生效后 run_sync 会推（179 MB 走 bulk）；或 W21 口径用 gpu33-hk 单独传 |
| G4 | 复盘只在 night 所在机器（gpu33）生成 | 笔记本上 `docs/master/RETRO_ep01.md` 不会自己出现（resident_sync.pull 只拉 `data/` 和 `docs/series10_video/`）；笔记本 sop_gate / master_check 看 ep01 复盘 = missing（服务器 producer 的 ep02 出图闸门看的是 gpu33 那份，不受影响） | 二选一（总调度定）：autoflow_resident.tick 加一拍 `episode_retro.tick()`（笔记本也按拉回的 `data/episodes/series10_v2/` 生成）；或 pull 加 `docs/master/RETRO_*.md` |
| G5 | ep01 内容：首帧定稿 8/11（缺 S4/S8/S9）、尾帧未齐 | sop_gate“视频”不过 → build_jobs 0 镜（沙箱实测 `shots: 0`）→ 不会 EP_RESOLVED | W38 主线 |
| G6 | `upscale_preview` 去抖（minterpolate，CPU 单线程）每镜约 3–4.5 分钟、串行 | finalize 一次 35–50 分钟；`run_dejudder` 的 subprocess 没 timeout | 非阻断；可改并行 + 加 timeout（upscale_preview.py 不归 W46） |
| G7 | F6 新壳要装到两台 `/root/work/fredw/tools_bin/ffprobe` | 不装 = 服务器上 finalize 合成必挂（`assemble_failed`，3 次重试后停） | W38 hf：`cp tools/series10_video/ffprobe_shim.py /root/work/fredw/tools_bin/ffprobe`（deploy.py push 自带这一步） |


## 4. ep01 视频段放 gpu36（总调度 04:0x 定：按三前提推进，partition 先不改）

| 前提 | 内容 | 状态 |
|---|---|---|
| ① 首尾帧到 gpu36 | `resident_sync.relay_video_frames`（新线程 relay_frames，每 300 s；`NS_RELAY_FRAMES=off` 关；CLI `resident_sync.py relay [--pairs]`）：按 partition（runs.<剧> 优先）只对“视频归 dst、出图归另一台服务器”的集，以出图机为真源 `ssh src tar \| ssh dst 安装`：图原子替换保 mtime、不删；takes.json 在 takes.json.lock 里合并（出图机的 image/last + 视频机自己的 video 版本与 active.video）；增量（takes.json 按上次中继 sha、图按大小）；连续 3 拍失败登记一次卡点 | ✅ 笔记本树；真机（gpu33 生产只读 → gpu36 沙箱 repo36）首拍 11 个 1.83 MB 53 s、第二拍 0 个 6.5 s；**resident_sync 重启后生效** |
| ② 代码一致 | gpu36 缺 hf-20261104-01..06（8 个文件，清单 + sha 见 V2_LIVE 04:05 “W46→W38”）；+ F2–F7 | 交 W38 台账 |
| ③ 资产清单一致 | `assets_v2/manifest.json`：04:0x 三份一致（2438062a）；服务器 mtime 比笔记本晚 6–13 s → “服务器更新的不盖”会误判 → `run_sync_sha_todo`：真源单文件远端 mtime 新过余量时比 sha，不同照推 | ✅ 笔记本树（随 resident_sync 重启生效） |
| 验证 | gpu36 沙箱放中继来的帧 + 8 个热修文件 + 当前清单 → `sop_gate.evaluate(series10_v2,1)` 九阶段与 gpu33 生产逐项一致（出图 8/11、出图检测 8/11、尾帧 4/11、提示词 ✓）；只放中继、不放热修 → 出图检测 5/11 | ✅ |
| 切换时机 | 总调度定（ep01 首尾帧齐、进视频阶段时改 partition video：1 → gpu36）；切后看 gpu36 `video/night.log` 有 `build_jobs` ready > 0 与 `DISPATCH gpu36` 道 [0,1] | 待 |

| G8 | 复盘自动 done 不看预览质量 | 沙箱 v1 实长 19 s（代片被修头尾）、verdict=fail、6 镜口型重出，`episode_retro.auto` 照样 `retro_status: done` → 第 2 集出图放行（W24 设计口径：有整集预览就 done） | 总调度定：要不要让 retro_auto_done 看 `night_state.eps.N.hard_rules.warnings` / director.lip_redo（config/pipeline/sop_gate.json retro_auto_done） |

## 5. 沙箱实测（2026-11-04，gpu33 `/root/work/fredw/w46/repo`；时间 = night.log Asia/Tokyo）

素材：S10 = W41 真 Pika 片（5.167 s）；其余 10 镜 = 本剧首帧缓推代片（`finalize_trial.py prep`，5 s 1 镜 + 6 s 9 镜，剧本合计 64 s）。

| 步 | 命令 / 事件 | 时刻 / 耗时 | 产物 / 结果 |
|---|---|---|---|
| 0 | `finalize_trial.py prep --run series10_v2 --ep 1 --real ep01-S10=…/video_002_w41.mp4` | 5 s | `video/clips/ep01/ep01-S{1..11}__w46_s0.mp4`、jobs.json、state_gpu33.json、night_state.json |
| 1 | `finalize_trial.py loop`（= night.loop_once）第 1 拍 | 03:26，1.3 s | `HOLD ep01`（voices_v2 不在服务器，F1） |
| 2 | 补 voices_v2 + F2 后第 2 拍 | 03:28 | `RETRY_ASSEMBLE` → `EP_RESOLVED` → `proxies` 被 vidgen_guard 挡（F3） |
| 3 | 第 3 拍（F3 前） | 03:30–04:10，40 分 | proxies 11/11 ✓；upscale 26 分（dejudder 每镜 4.5 分后失败，F7）；assemble rc=1 `count_frames '{}'`（F6） |
| 4 | 第 4 拍 `--reopen`（新壳 + F7） | 04:15–04:44，29 分 | upscale 27 分 ✓（`_dj` + `_sr1080` 全出）；assemble ✓ 2 分；HARD_RULES 旧口径 FAIL（实长 19 s、verdict=fail）→ 不发布 |
| 5 | 第 5 拍 `--reopen`（F5 新口径） | 05:05:36–05:07:39，2 分 3 秒（放大版已缓存） | `HARD_RULES pass（2 条只记）` → **`data/episodes/series10_v2/ep01_v1.mp4`**（19.0 s，1080×1920，video+audio，无字幕流）+ `.timeline.json`；director film_score 21.8/50、lip_redo 6 镜；BGM_LIB 曲库缺（G3）；**`RETRO ep01 … 自动 done：第 2 集可以进“出图”`** |
| 6 | `sop_gate.evaluate(series10_v2,1)` | 即时 | 视频 ✓ 11/11、整集预览 ✓ ep01_v1.mp4 |
| 7 | `episode_retro.py --run series10_v2 --episode 1 --auto` | 0.06 s | `RETRO_ep01.md 已 done`（retro_sig 没变不重写） |
| — | 真片单测 `tools/dejudder.py ep01-S10…` | 187 s | rc=0，5.17 s 768×1344 |

## 6. 部分预览（总调度 04:2x：有几镜拼几镜）

- `tools/assemble_series.py epNN --preview --partial --no-pull --no-bgm --out-dir … --out-name epNN_preview_partial_HHMM`：视频取 vidgen state（done）或本剧 takes.json `active.video`；缺的镜 = 1080×1920 黑场 + 镜号字样（仅预览）；`--no-bgm` 时曲库缺不挡。
- `tools/master/partial_preview.py --prod <生产仓库> --ep 1 --loop`：在隔离副本里跑，每 300 s 镜像生产本集渲染 + video state，≥3 镜拼、之后每多 2 镜重拼，产物装到生产 `data/episodes/<剧>/_partial/`（**子目录**：顶层 `ep01*.mp4` 会被 sop_gate 当整集预览放行复盘与下一集出图）。
- 现在跑在 gpu36（视频在 gpu36 出）：`/root/work/fredw/w46/repo36`，pid 见 `/root/work/fredw/w46/logs/partial_loop36.pid`，日志 `partial_loop36.log`，状态 `repo36/data/_w46_partial/state.json`。冒烟：gpu33 / gpu36 各 63.0 s（S10 真片 4.0 s + 10 镜黑场镜号），合成不到 1 分钟。

## 7. 05:2x–06:00 追加（总调度令，均已落两台，台账 hf-w46-02 / hf-w46-03）

| 项 | 做法 | 状态 |
|---|---|---|
| 片长 6.58 s（Pika 79 帧@12） | 根因 `ns_recipes/compiler.cap_frames_c08`：剧本 ≤6 s 的镜对齐后超 6 s → 141 帧（5.875 s）；兜底 `tools/series10_video/clip_trim.py` 合成前裁 ≤6.0 s（尾部裁、首帧保留，`<名>_le6.mp4`） | ✅ 下次 build_jobs 生效 |
| 已登记的 >6 s 当前视频 | `tools/series10_video/trim_takes.py`：_le6 经 register_takes.register 登记新版（postflight = 原门结论 + C08）并设当前，原版保留；night 每轮 register_takes 后调（登记前先裁） | ✅ 生产 S2/S3 05:57 已换（v2 6.0 s）；night 自动接力要 night 再重启（05:38 那次早于热修） |
| 冲刺：每镜先 1 条再出变体 | `vidgen.first_take_first`（control `first_take_first:false` 关） | ✅ gpu36 vidgen 05:58 重启加载（pid 357106） |
| 尾帧到了不重编作业 | night ready_sig 加 `passed_lasts()` | ✅ 代码已落；等 night 重启 |
| vidgen 不认 partition _temp_holds | gpu36 `video/night_control.json hold_lanes=[gpu36:1]`（night 合进 control） | ✅ 05:20:29 生效 |
| 部分预览拉回笔记本 | `tools/master/partial_pull.py --loop`（hk 优先，不通走命令主连接） | ✅ 笔记本 `data/episodes/series10_v2/_partial/ep01_preview_partial_0524.mp4` |

**仍卡（非 W46 代码）**：ep01-S1 七个变体 preflight I10（HC-07 锁定外貌：'red nails'）→ vidgen 不提交 → 交 W38 / 写手改提示词。S4–S9、S11 等首尾帧（W38 主线）。gpu36 night 需再一次 night-only 重启加载 hf-w46-03。
