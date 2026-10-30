# QC 闸门（ns_qc）：把反复出现的问题变成可测量的自动检查

> 建立：2026-10-30（agent D）。依据：docs/production_issues.md（PI-01…PI-30、Top-10、§七 回归检查清单）、docs/audit/rule_ids.md、docs/SOP_parameters.md、docs/consistency_impl.md、docs/CONSISTENCY_PLAN.md、services/post/ns_post/colormatch.py。
> 规则：只测技术量（尺寸、哈希、PSNR/SSIM、ΔE、SFace 余弦、LUFS、F0、版本号、文件时间），不判断内容或审美（G1–G6）。阈值全部来自已有文档；文档里没有数的，写“待项目方定”，只报告（info）或 warn。**`unchecked` 不等于通过**（PI-06 的要求），报告里单独计数。

## 1. 代码与用法

| 位置 | 作用 |
|---|---|
| `packages/qc/ns_qc/thresholds.py` | 闸门表：每条闸门的指标、阈值、状态（locked / documented / suggested / pending）、不达标时的级别、出处 |
| `packages/qc/ns_qc/media.py` | ffmpeg 解码（按帧号取全分辨率帧、末帧、整片小图、音频）、ebur128 响度、PSNR、SSIM、结构相关、CIELAB、CIEDE2000、h3_keyframe 同款几何（居中裁 4:7 → Lanczos 768×1344） |
| `packages/qc/ns_qc/face.py` | YuNet + SFace（与 gpu3 `ns_launcher.VISION_WEIGHTS` 同一 sha256，带锁），S3-F3 发色规则（移植自 gpu3 `weita_series.hair_colour`），躯干框 a/b 直方图、主色 |
| `packages/qc/ns_qc/video_gates.py` | `keyframe_gate`（PI-08/PI-19）、`drift_gate`（PI-01/03/04） |
| `packages/qc/ns_qc/audio_gates.py` | `audio_gate`（PI-11/12/13/14），YIN 基频 |
| `packages/qc/ns_qc/provenance.py` | bible_version 盖章、提示词重编译时间、stems 与视频 sha、关键帧是否在镜像、video.mp4 = active take、同步心跳 |
| `packages/qc/ns_qc/runner.py` | 一集全部闸门 → `docs/audit/qc_epNN.{md,json}` + 每镜 `data/qc/epNN/<镜>.json` |
| `tools/qc_run.py` | CLI：`.venv\Scripts\python.exe tools\qc_run.py --episode 1 [--shots S1,S3] [--gpu3-host gpu33]`；有 fail 时退出码 2 |
| `tests/test_qc_gates.py` | 18 项回归测试（合成视频/音频，CPU） |

依赖只有 stdlib + numpy + OpenCV + Pillow + ffmpeg/ffprobe；不 import 其它服务，gpu3 可以直接复制或加 `sys.path` 使用。
人脸模型查找顺序：`$NS_QC_VISION_DIR`、`models_cache/vision`、`models/vision`、`ns-studio/models/vision`；笔记本这份是 2026-10-30 从 gpu3 只读复制的，sha256 与 gpu3 固定值一致。人脸参考图读 `config/face_reference.json`（`assets/characters/lin_wan/lin_wan.png`）。gpu3 用的是 CM_s1 母版脸部裁切，所以两边的 SFace 绝对值会有差别。
`--gpu3-host`：takes.json 里记录的是 gpu3 绝对路径、镜像里又没有的关键帧，用 `scp -o BatchMode=yes` 只读复制到 `data/qc/kf_cache/`；不改 gpu3 上任何文件。

## 2. 闸门表

级别：**fail** = 已锁定或已写进文档/代码的阈值；**warn** = 只在 production_issues 里提议、尚未锁定；**info** = 待项目方定，只报告数值。

| 闸门 | PI | 指标（怎么测） | 阈值 | 状态 → 级别 | 出处 |
|---|---|---|---|---|---|
| Q-K1 | PI-08 | 视频宽×高（ffprobe） | = 768×1344 | locked → fail | rule_ids P-B3 |
| Q-K1b | PI-08 | 关键帧宽高比与视频宽高比的相对差 | ≤ 0.01 | locked → fail | rule_ids P-B2 |
| Q-K2 | PI-08 | 解码第 0 帧 vs 首帧（按 h3_keyframe 同法裁切缩放）PSNR | ≥ 20 dB | locked → fail | SOP_parameters 视频 QC |
| Q-K6 | PI-08 | 同上，SSIM（亮度，高斯 11×11） | 待项目方定 | pending → info | — |
| Q-K3 | PI-08 | 真正的末帧 vs 尾帧 SSIM | ≥ 0.55 | documented → fail | consistency_impl §二；gpu3 `LAST_SSIM_MIN` |
| Q-K4 | PI-19 | 前 / 后 0.5 s 的中心加权平均 LAB 与首 / 尾帧之间的 CIEDE2000 | ≤ 4 | suggested → warn | PI-19 |
| Q-K5 | PI-19 | 全片 L* 相对首帧的最大漂移；**只算与首帧结构相关 ≥ 0.85 的帧**（运镜带来的亮度变化不算颜色漂移） | ≤ 8 | suggested → warn | PI-19；0.85 = colormatch `match_min` |
| Q-D1 | PI-01 | 每 0.5 s 取一帧，YuNet 人脸（高 ≥ 80 px）与参考脸的 SFace 余弦，取中位数 | ≥ 0.30 | locked → fail | SOP_parameters 视频 QC；gpu3 `SIM_CLIP_MIN` |
| Q-D2 | PI-01 | 每个 2 s 窗口（4 个采样点）的中位数，取最小值 | ≥ 0.20 | suggested → warn | PI-01（“连续 2 秒最小值”按窗口中位数实现，单帧遮挡不触发） |
| Q-D3 | PI-03 | 每个采样帧套用 S3-F3 HSV 发色规则，统计不通过的帧数 | = 0 | documented → warn | S3-F3（帧阶段为 block；视频阶段是新用法，先 warn） |
| Q-D4 | PI-03 | 发带区域蓝色像素的平均 LAB，与第一个有脸的采样点之间的 ΔE2000 最大值 | ≤ 12 | suggested → warn | PI-03 |
| Q-D5 | PI-04 | 躯干框（脸下方 1.15–3.0 个脸高）LAB a/b 直方图与第一个采样点之间的 Bhattacharyya 距离最大值；没有脸时改用中心框 | ≤ 0.45 | suggested → warn | PI-04 |
| Q-D6 | PI-04 | 躯干框 k-means 主色与第一个采样点之间的 ΔE2000 最大值 | 待项目方定 | pending → info | — |
| Q-A1 | PI-11 | take 提示词里 `non_diegetic_music` 为 N/A 或没有这个字段时：audio_post stems.json 中 H3 完整底声的 CLAP music 类标签之和（stems 的 video_sha256 必须等于本片，否则视为证据过期，记 unchecked） | ≤ 0.30 | suggested → warn | PI-11 |
| Q-A1b | PI-11 | DSP 替代量：非人声底声里持续 ≥ 8 帧、比中位数高 15 dB 的谱峰占比 | 待项目方定 | pending → info | — |
| Q-A2 | PI-14 | H3 原声积分响度（ffmpeg ebur128，BS.1770；没有时退回 RMS 近似并注明） | −30 … −16 LUFS | suggested → warn | PI-14 |
| Q-A2b | PI-14 | 真峰值 | ≤ −1 dBTP | suggested → warn | PI-14；SOP_parameters S5 响度 |
| Q-A3 | PI-13 | Demucs 人声干声（没有时用混音）的 YIN 基频：F0 < 165 Hz 的浊音时长；本镜 H3 对白里有男性说话人（config/voices.json 的性别）时不检查 | ≤ 0.5 s | suggested → warn | PI-13 |
| Q-A4 | PI-13 | 说话人数的替代量：时长 > 0.5 s 的音高带数（<165 / ≥165 Hz）超出对白性别数的部分 | ≤ 0 | pending → warn | 本地没有说话人嵌入模型 |
| Q-A5 | PI-12 | 没有 H3 对白的镜头，前 1.0 s 的浊音时长 | < 0.3 s | suggested → warn | PI-12 |
| Q-P1 | PI-25/05 | active take 的 `bible_version`（current / stale / unstamped）与当前值（data/state_timeline.json）比较 | = 当前值 | locked → fail | rule_ids R-C8 |
| Q-P2 | PI-25 | compiled.json 的 `h3_prompt_compiled_at` 晚于视频 take 的 `created_at`（视频不是按现行提示词出的） | = False | documented → warn | PI-25 |
| Q-P3 | PI-24 | stems.json 的 `video_sha256` = 镜像中视频文件的 sha256 | 相等 | documented → fail | PI-24；SOP S5 |
| Q-P4 | PI-08/24 | 视频 take 记录的首 / 尾帧在本地镜像里能找到（或已从 gpu3 只读取回）；按结构相关推断出来的不算 | 能找到 | documented → warn | PI-08 |
| Q-P5 | PI-24 | 镜像里的 `video.mp4` 与 active 视频 take 文件 sha 相同，并且两者都存在 | 相同 | documented → warn | PI-24 |
| Q-P6 | PI-08/24 | 画布显示的 `frame.png` 与视频第 0 帧的结构相关 | ≥ 0.85 | documented → warn | PI-08（“画布显示的帧 = 视频用的帧”） |
| Q-S1 | PI-24 | `data/renders_gpu3/.last_sync_gpu3` 的年龄（文件里的 epoch，读不到时用 mtime） | ≤ 30 min | suggested → warn | PI-24 |

## 3. ep01 首次实测（2026-10-30，`docs/audit/qc_ep01.md`）

- 总判定 fail。6 镜里只有 S1、S2、S3 的视频在镜像里；S4、S5 的 active 视频 take 和 video.mp4 都不在（Q-P5），S6 还没有视频。
- Q-P1：6 镜的 active take **全部没有 bible_version 盖章**（10/29 出的片）→ fail，与审计 R-C8 360/360 的结论一致。
- Q-P2：S1–S5 的 H3 提示词是 10-30 03:50Z 重编译的，视频是 10-29 出的 → 视频不是按现行提示词出的。
- S1：首帧 PSNR 32.9 dB / SSIM 0.92（首帧从 gpu3 只读取回）；ΔE 首段 1.07；SFace 中位数 0.693；**发色 3/10 帧不过 S3-F3**（6.0–7.5 s）；**CLAP music 1.00**（PI-11 复现）；响度 −13.8 LUFS（高于 −16）；尾帧在 gpu3 上已经不存在 → Q-K3 unchecked。
- S2：首帧在镜像和 gpu3 上都找不到；SFace 0.609；响度 −9.4 LUFS、真峰值 −0.3 dBTP（两项 warn）；music 0.04。
- S3：**首帧是推断出来的**（image_002，结构相关 0.974）；**画布的 frame.png 和视频第 0 帧结构相关只有 0.118**（Q-P6，PI-08 混源）；首帧 PSNR 21.5 dB（勉强过 20）；SFace 中位数 0.305 过线，但 **2 s 窗口最小值 0.082**（Q-D2，PI-01 溶解类）；躯干 Bhattacharyya 0.586（Q-D5）；CLAP music 1.00。
- 心跳：运行时 7 分钟，pass。

## 4. gpu3 应该在哪些地方调用（只列位置，gpu3 代码未改）

gpu3 根目录 `/root/claude-kimi-ns-studio-v1/ns-studio/scripts/`（2026-10-30 只读核对的行号）：

1. `weita_series.py` `_clip_checks`（第 979 行起，由 `clip_checks` 第 971 行在 `w._mlock` 下调用）：在现有 PSNR / SFace / SSIM 之后加
   `from ns_qc.video_gates import keyframe_gate, drift_gate`；参数 `first_kf = frame`，`last_kf = OUT/epXX/keyframes/<镜>.last.h3.png`，`models` 用 `ns_qc.face.FaceModels(YUNET_PATH, SFACE_PATH)`，`ref_embedding = ctx.lw_target`；把 fail 级结果并入 `fails`，warn 级写进 `out["qc_warn"]`。
2. `weita_series.py` `add_take`（第 346 行）：已经写 `bible_version`；另加 `reference_sha`、`last_target_sha`（PI-08），Q-P4、Q-P6 就能改用 sha 比对。
3. `weita_series.py` `step_a_shot`（第 827 行，第 900–905 行是最佳候选失败仍被锁定的地方，PI-07）：本包没有替代 VLM 判定；锁定前可以加一个 `ns_qc.thresholds.worst(...) != "fail"` 的检查。
4. `audio_post.py` 写 `h3_rest_tags` / `h3_music_suspected` 的地方（第 899–900 行，stems.json 在第 1001、1018 行写出）：调用 `ns_qc.audio_gates.audio_gate(clip, prompt=<视频 take 的提示词>, ...)`，把结果写进 `stems.json["qc"]`；如果要拦截视频，在 `_clip_checks` 里调用。
5. 笔记本同步（`ops/sync/sync_laptop.sh`、`ops/laptop/*`）：每次同步写 `.last_sync_gpu3`（已有）；计划任务里跑 `tools/qc_run.py --episode N`，退出码 2 时提示。

## 5. 还没覆盖的部分

- PI-13：没有说话人嵌入模型（ECAPA / WavLM），Q-A4 只能用音高带估计；F0 < 165 Hz 区分不了低音女声和男声。
- PI-11：本地没有 CLAP，Q-A1 用的是 audio_post 已经算好的标签；Q-A1b 的 DSP 量还没有校准（待项目方定）。
- PI-04：躯干框是按脸的位置推算的，不是人物分割；Q-D6 的主色在 k-means 里容易在衣服和背景之间跳，所以只报 info。道具数量、VLM 服装问句都不在本包里。
- PI-22 朝向和 yaw 跳变、PI-12 拟音底噪、PI-16 独白时长、PI-23 参数文件一致、PI-26 code_sha：都还没做。
- 阈值校准：PI-01 里列的 golden 负样本（ep01s3_a2、ep01s6_a1、qipi ep01s1 等）不在笔记本镜像里，没能跑“每次 QC 改版都必须判 FAIL”的回归，需要 gpu3 同步过来。
