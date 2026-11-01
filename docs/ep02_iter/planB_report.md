# PLANB：ep02 方案 B 报告（2026-10-31，项目方叫停后的收尾版）

方案 B 的目标是**保住定稿首帧的构图**。做法：I2VA 只给定稿首帧，用 PDD-Acc 8NFE 两段式出片，再接 H3 FaceRefine 修脸；脸颊压色原计划在合成时由 skin guard 完成。

所有出片都直接提交到 gpu36 的 ComfyUI（:8188/:8189/:8190），没有占用 gpu33。不写 takes，不定稿，不改剧本和 config。

21:30 项目方下令“6 张卡立刻转去出新 10 集的图片，ep02 实验到此为止”：
- 方案 B 已停。我在三条道上的排队全部删掉（17 个），正在跑的 3 个已中断。21:37 实测 gpu36 0/1/2 各占约 560 MB，利用率 0%。
- **按指令不合成 ep02_planB.mp4**，所以也没有跑 review --name planB。

文件位置：
- 出片脚本：`tools/lab_ep02/planb_run.py`（本次新增）
- 产物：`data/ab/planB/ep02/<镜>/`。每次出片的完整 API 图、提示词来源和 gpu_s 都记在同名 `.json` 里。
- 打分：`data/ab/planB/ep02/scores/`，含 `scores.md`、`scores.json` 和接触印样 `<name>_sheet.jpg`
- 提交日志：`data/ab/planB/ep02/logs/`

## 1. 实测耗时（可查证）

计时口径：
- `gpu_s` 取 ComfyUI history 里 `execution_start` 到 `execution_success` 的时间差，不含排队，记在各 `<name>.json` 里。
- 每一段的步速取自 ComfyUI 日志的 tqdm 行。摘录在 `data/ab/planB/ep02/logs/gpu36_step_timing_2110.txt`，原日志是 gpu36 上的 `/root/work/fredw/comfy/logs/gpu0.log` 和 `gpu1.log`。
- **条件**：三张卡同时满载时，过热守护把每张卡压到 200 W（20:45 `nvidia-smi` 实测 power.limit 200 W，SM 855–1110 MHz）。下表数字都是在降频状态下测的，满功率时应该更快。

| 配方 / 环节 | 镜头·帧数 | 实测 | 来源 |
|---|---|---|---|
| PDD 两段式·生成：第一段 544×960 4 步 + 3D 放大 + 第二段 768×1344 4 步 | S2·158 帧 | 第一段 4 步 2:56（44–45 s/步），第二段 4 步 6:35（99–100 s/步）。加上文本编码、VAE、放大，**生成约 8–10 min/镜** | gpu36_step_timing_2110.txt（gpu1 段）；B1_S2 生成完就停了：execution_start→error 共 732 s，含修脸时人脸检测失败（缺 face_yolov8m.pt），见 logs/B1_S2.log |
| FaceRefine：768² 裁切、基模 10 步、denoise 0.42 | S2·158 帧 | 10 步 8:05（48.6–49.2 s/步），**约 8 min** | gpu36_step_timing_2110.txt（gpu1 段，`10/10 [08:05`） |
| **B2_S2 合计（生成 + 修脸）** | S2·158 帧 | **gpu_s 1362.3（22.7 min）**；ComfyUI 日志写“Prompt executed in 00:22:43” | logs/B2_S2.log；S2/B2_S2_pdd2.json |
| B2_S3 / B2_S4 / B2_S10 合计 | 158 帧 | gpu_s 1366.1 / 1363.1 / 1442.5 | S3、S4、S10 各自的 `B2_*_pdd2.json` |
| 基模 24 步单段 768×1344（对照 R0） | S2·158 帧 | 24 步 42:47（107 s/步），**gpu_s 2637.7（44 min）** | S2/R0_S2_b24_s1.json；gpu36_step_timing_2110.txt（gpu0 段，`24/24 [42:47`，“Prompt executed in 00:44:24”） |
| PDD 两段式·生成，长镜头道 --novram | S8·294 帧 | 生成版 08:35 落盘；修脸开始后被中断，execution 共 1437 s，其中生成约 20–23 min | gpu36:2 history e3d1c8a1；S8/B2_S8_pdd2.mp4 |

结论：
- PDD 两段式生成的耗时约为基模 24 单段的 1/4–1/5（约 9 min 对 44 min），同一 seed 下质量相当（见 §3）。
- 修脸这一段（8 min）现在和生成本身一样贵。如果改成 PDD 3 步（denoise 0.375，σ 从 .878 起），预计约 2.5 min。这一项没测。

## 2. 每镜配方（B2，主线）

所有镜头相同的部分：
- UNET：`minimax_h3_fl2va_pruned_int8_convrot`
- CLIP：`qwen3vl_32b nvfp4_awq`
- VAE：视频 int8_convrot，音频 fp32（gpu36 没有 fp16 视频 VAE）
- 注意力：comfy kitchen attention
- 采样：BasicGuider，cfg 1
- PDD：`MiniMaxH3PDDAccApply(FL2VA-Acc-8Step, nfe 8, lora 1.0, head 1.0, on_off_grid error)` → SigmaShift 12/3 → euler
- 切分：`SplitSigmas(PDD σ, 4)`，切点 σ=.923。第一段 544×960，首帧 lanczos 缩放后编码条件；第二段 768×1344，首帧重新编码条件；同一个 RandomNoise
- 放大：`MinimaxH3LatentUpscaler3D(conv_v1_fp16, target 768×1344, align 32, chunking 开)`，前后用 LTXVSeparate / ConcatAVLatent 拆合音视频 latent
- 修脸（`_fr`）：
  - `H3FaceTrackCrop`：face_yolov8m，crop 2.5，768×768，per_frame，identity_track 关（gpu36 没有 insightface 模型），选最大的脸
  - 条件与注入：`MiniMaxH3ImageToVideo`（不给首帧，画布等于裁切尺寸）+ `H3InjectVideoLatent`
  - 采样：fl2va 基模（不挂 PDD），12/3，`BasicScheduler simple 10 步 denoise 0.42`
  - 贴回：`H3FaceStitch(face_only, 24/24, colour_match 1)`；音频用主生成的音轨
- seed：20261101
- 提示词：PROMPT 的 sysimpl-v2 版本 `data/ab/prompt_v2/ep02/S<n>.i2va.txt`。总调度 20:08 告知项目方已批准导入；当时 compiled.json 还没重编，所以直接读这份文件，A 和 B 用的是同一份。B1_S2 用的是旧的 compiled.json，作为对照保留。
- 补装（都只在 gpu36 的 /root/work/fredw 下）：
  - `models/ultralytics/bbox/face_yolov8m.pt`，来自 HF Bingsu/adetailer，sha256 717923c1…943e5f
  - `models/loras/h3-realism-people-t2v-i2v-r2v.safetensors`，来自 HF fal，sha256 acc52960…5b787e，和 gpu33 那份一致
  - 两个文件都是走机房代理下载的。笔记本中转只有约 0.02 MB/s，中途断过一次，已放弃。

## 3. 指标（lab_score；门槛：mean ≥ 0.5、J4 ≤ 1.3、cheek_red ≤ 0.25、0 硬切、SFace ≥ 0.30）

| 镜 | 版本 | 门槛 | mean | J4 | 硬切 | cheek_red max | SFace 中位 | gpu_s | 印样 |
|---|---|---|---|---|---|---|---|---|---|
| S2 | B1 PDD 两段式 + **旧提示词** | ❌ 泛红 / 身份 | 0.78 | 1.07 | 0 | 0.39 | 0.28 | （生成约 9 min） | scores/B1_S2_sheet.jpg |
| S2 | **B2 PDD 两段式 + 新提示词** | ✅ | 0.86 | 1.06 | 0 | **0.09** | 0.33 | 1362（含修脸） | scores/B2_S2_sheet.jpg |
| S2 | B2 + 修脸 | ✅ | 0.86 | 1.06 | 0 | 0.09 | **0.365** | 同上 | scores/B2_S2_fr_sheet.jpg |
| S2 | R0 基模 24 单段 + 新提示词（同 seed） | ✅ | 0.87 | 1.13 | 0 | 0.08 | 0.35 | 2638 | scores/R0_S2_b24_s1_sheet.jpg |
| S3 | B2 | ✅ pass | **1.76** | 1.14 | 0 | 0.08 | 0.339 | 1366 | scores/B2_S3_sheet.jpg |
| S3 | B2 + 修脸 | ✅ | 1.75 | 1.13 | 0 | 0.08 | 0.342 | 同上 | scores/B2_S3_fr_sheet.jpg |
| S4 | **B2（采用，未修脸）** | ✅ | 0.54 | 1.07 | 0 | 0.09 | 0.318 | 1363 | scores/B2_S4_sheet.jpg |
| S4 | B2 + 修脸 | ❌ 身份 | 0.53 | 1.06 | 0 | 0.09 | **0.257↓** | 同上 | 丢弃（K-REV-R09：修后不得低于修前） |
| S6 | B2（中断前已存的生成版，未修脸） | ✅ | **0.84** | 1.12 | 0 | 0.08 | **0.446** | 约 989（被中断） | scores/B2_S6_sheet.jpg |
| S8 | B2 长道 294 帧（生成版，未修脸） | ❌ 泛红 | **2.06** | 1.16 | 0 | **0.29** | 0.389 | 约 1437（被中断） | scores/B2_S8_sheet.jpg |
| S10 | B2 | ❌ 身份 | 0.59 | 1.08 | 0 | 0.05 | 0.187 | 1442.5（含修脸） | scores/B2_S10_sheet.jpg |
| S10 | B2 + 修脸 | ❌ 身份 | 0.59 | 1.08 | 0 | 0.06 | 0.188 | 同上 | scores/B2_S10_fr_sheet.jpg |

没出的镜：
- S1、S5、S7、S9、S11：已排队，叫停时删掉了。
- 各镜第 2 个 seed（20261102，不修脸）：已排队，叫停时删掉了。
- B3：S2/S3/S4 + realism-people 1.0 的 PDD 版本，已排队，叫停时删掉了。

和 v1（v1 审片 review.md）、LAB 的对照：
- **S6 静止镜**：v1 0.475，LAB 跑过的所有 FL2VA/I2VA 配方都 ≤0.49；B2 是 **0.84**，构图也是定稿首帧。主要变量是新提示词（按秒分拍），PDD 两段式至少没有拖后腿。
- **S3**：v1 0.48 → 1.76。**S8**：v1 0.98 → 2.06。
- **泛红**：同配方同 seed 下，旧提示词 0.39，新提示词 0.09。S3/S4/S6 都在 0.08–0.09。只有 S8 是 0.29：cheek_a95 从 20.5 升到 38.4，长镜头泛红随时间加重的现象依旧，合成时的 skin guard 可以兜底。
- **身份**：这条路线跟着定稿首帧走。S2–S8 的 SFace 在 0.32–0.45，S10 是 0.19。这和 LAB 批 4 的结论一致：身份的根在首帧本身。FaceRefine 没有身份参考，作用很小（+0.034 / +0.003 / −0.061）。

## 4. 和方案 A 比（预期 + 已有数据）

| 维度 | 方案 B（本报告） | 方案 A（Ref2VA + 脸部裁切；ledger B-V2a） |
|---|---|---|
| 构图 | **保住定稿首帧**（硬钉） | 来自提示词，与首帧不同（LAB X1 S6 坐姿变成站姿） |
| 身份 SFace | 0.19–0.45 | S4 0.718、S6 0.678（明显更强） |
| 泛红 | 新提示词下 0.08–0.09；S8 长镜头 0.29 | 0.04–0.08 |
| 动作量 | S3 1.76、S6 0.84、S8 2.06（新提示词 + PDD） | LAB X1 S6 1.28 |
| 卡顿 J4 | 1.06–1.16，没有一条 > 1.3 | LAB 1.03–1.38 |
| 速度 | 生成约 9 min / 158 帧（200 W），PDD 8 步 | Ref2VA 20 步两段式，3090 约 16 min / 6 s（LAB 批 2） |

预期：
- B 强在构图忠实于定稿首帧、更快，适合暴力多 seed 筛选。
- B 弱在身份：首帧身份分低的镜（S10）救不回来。
- 两者兼得的路线：先用身份参考重出首帧（CONSIST 的 R 方式），再走 B；或者修脸时换成带脸部参考的 Ref2VA（gpu36 上只有 Singularity ref2va v2，社区许可，仅供内部对比，没跑）。

## 5. 建议（只是建议，没有改 config）

1. `video_bases` 增加试验基底 `fl2va_pdd_2stage`，参数见 §2，K-REN-019。用作多 seed 筛选的快档：同 seed 下质量和基模 24 相当，耗时约 1/4。
2. FaceRefine 默认关闭。只在“修后 SFace ≥ 修前”时采用（K-REV-R09）。没有身份参考时收益很小，而且要花 8 min。如果要用，改成 PDD 3 步，或者接 Ref2VA + 脸部裁切参考。
3. 长镜头（S8）I2VA 要配 skin guard 或首尾帧，因为泛红会随时间加重。
4. gpu36 上过热守护会降频到 200 W，三卡同时跑 PDD 时每步慢约 2 倍。要做成本估算，应在满功率下重测一次。

## 6. 学习记录

- RSI_LEDGER：B-PB1（修脸 ◐）、C-PB1（新提示词压泛红 ✅）、E-PB1（PDD 两段式 ✅），以及 A-PB1（静止镜 S6 救回 ◐）。
- 规则：新增 K-REN-019（PDD 两段式快档）。
- `tools/knowledge/compile.py --check` 已通过。
