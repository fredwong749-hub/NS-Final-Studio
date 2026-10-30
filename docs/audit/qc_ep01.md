# QC 报告 ep01（自动生成，ns_qc/2026-10-30.1）

> 生成：2026-10-30T06:00:27+00:00；镜像：`D:\NS-Final Studio\data\renders_gpu3\ep01`；工具：`tools/qc_run.py --episode 1`。
> 只含技术量（尺寸、哈希、PSNR/SSIM、ΔE、SFace、LUFS、F0、版本、时间），不含任何内容或审美判断（G1–G6）。
> 阈值与级别见 docs/qc_gates.md；`unchecked` 不等于通过。

**总判定：🔴 fail**　当前 bible_version：`da4109a65f1c`（data/state_timeline.json bible_version）；人脸参考：reference assets/characters/lin_wan/lin_wan.png (config/face_reference.json)

同步心跳 Q-S1：✅ pass，7.3 分钟（阈值 <= 30.0；.last_sync_gpu3: epoch in file 2026-10-30T05:53:08+00:00）

## 逐镜汇总

| 镜 | 判定 | fail | warn | unchecked | 视频 |
|---|---|---|---|---|---|
| S1 | 🔴 fail | 1 | 5 | 3 | video_002.mp4 |
| S2 | 🔴 fail | 1 | 4 | 7 | video_001.mp4 |
| S3 | 🔴 fail | 1 | 7 | 2 | video_002.mp4 |
| S4 | 🔴 fail | 1 | 2 | 8 | 无 |
| S5 | 🔴 fail | 1 | 2 | 8 | 无 |
| S6 | 🔴 fail | 1 | 0 | 10 | 无 |

## 逐镜明细

### S1（🔴 fail）

| 闸门 | PI | 指标 | 值 | 阈值 | 级别 | 结果 | 说明 |
|---|---|---|---|---|---|---|---|
| Q-K1 | PI-08 | video_size | [768, 1344] | == [768, 1344] | locked→fail | ✅ pass | video 768×1344 @ 24 fps, 243 frames |
| Q-K1b·first | PI-08 | keyframe_aspect_rel_diff | 0 | <= 0.01 | locked→fail | ✅ pass | first keyframe 1152×2016 vs video 768×1344 |
| Q-K2 | PI-08 | first_frame_psnr_db | 32.9 | >= 20.0 | locked→fail | ✅ pass | SSIM 0.9185 |
| Q-K6 | PI-08 | first_frame_ssim | 0.918 | 待项目方定 | pending→info | ℹ info | PSNR 32.865 dB |
| Q-K4·first | PI-19 | edge_dE2000 | 1.07 | <= 4.0 | suggested→warn | ✅ pass | first 0.5s mean LAB [48.2, -1.0, 7.4] vs keyframe [49.2, -1.1, 7.1] |
| Q-K5 | PI-19 | max_abs_dL | 1.32 | <= 8.0 | suggested→warn | ✅ pass | max /ΔL*/ over 31/243 frames that structurally match the keyframe (≥0.85): frame 28 (1.17 s) signed -1.32; all frames: -36.59 at 5.46 s |
| Q-K3 | PI-08 | last_frame_ssim | — | >= 0.55 | documented→fail | ⚪ unchecked | no last keyframe available locally (shot has no independent last keyframe, or it was not synced — PI-08) |
| Q-K4·last | PI-19 | edge_dE2000 | — | <= 4.0 | suggested→warn | ⚪ unchecked | no last keyframe available locally |
| Q-P6 | PI-08,PI-24 | shown_frame_vs_video_frame0_structure | — | >= 0.85 | documented→warn | ⚪ unchecked | shot has no frame.png in the mirror |
| Q-D1 | PI-01 | sface_median | 0.693 | >= 0.3 | locked→fail | ✅ pass | 10/22 samples with a face; min 0.414; no-face samples 12 |
| Q-D2 | PI-01 | sface_min_2s_window_median | 0.519 | >= 0.2 | suggested→warn | ✅ pass | median per 2 s window (4 samples), minimum over windows |
| Q-D3 | PI-03 | hair_hsv_bad_frames | 3 | == 0 | documented→warn | 🟡 warn | 3/10 sampled frames fail the S3-F3 HSV rule at t=[6.0, 6.5, 7.5] |
| Q-D4 | PI-03 | hair_max_dE2000_vs_first | 9.61 | <= 12.0 | suggested→warn | ✅ pass | hair-band LAB ΔE2000 vs first sample (t=6.0s); per sample [0.0, 4.62, 2.33, 2.1, 2.08, 9.31, 9.6, 9.54, 9.6, 9.61] |
| Q-D5 | PI-04 | torso_ab_bhattacharyya_max | 0.402 | <= 0.45 | suggested→warn | ✅ pass | face-anchored torso box; worst at t=9.0s; 10 samples |
| Q-D6 | PI-04 | torso_dominant_dE2000_max | 7.08 | 待项目方定 | pending→info | ℹ info | face-anchored torso box; dominant LAB ΔE2000 vs first sample |
| Q-A1 | PI-11 | clap_music_score | 1 | <= 0.3 | suggested→warn | 🟡 warn | prompt non_diegetic_music = unspecified; sum of CLAP music-labels on the full H3 non-vocal bed (audio_post h3_rest_tags) |
| Q-A1b | PI-11 | bed_tonal_ratio | 0.885 | 待项目方定 | pending→info | ℹ info | share of frames with a sustained tonal peak |
| Q-A2 | PI-14 | h3_integrated_lufs | -13.8 | -30.0 … -16.0 | suggested→warn | 🟡 warn | ffmpeg ebur128 (BS.1770) |
| Q-A2b | PI-14 | h3_true_peak_dbtp | -2.9 | <= -1.0 | suggested→warn | ✅ pass |  |
| Q-A3 | PI-13 | male_f0_voiced_s | 0 | <= 0.5 | suggested→warn | ✅ pass | voiced <165 Hz; H3 dialogue genders none |
| Q-A4 | PI-13 | pitch_band_count_excess | 0 | <= 0 | pending→warn | ✅ pass | 0 pitch band(s) >0.5 s vs 0 expected gender(s) |
| Q-A5 | PI-12 | voiced_s_first_1s | 0 | < 0.3 | suggested→warn | ✅ pass | voiced seconds in 0–1.0 s |
| Q-P1 | PI-25,PI-05 | bible_version | ['image#8:unstamped', 'video#2:unstamped'] | == current bible_version | locked→fail | 🔴 fail | current bible_version da4109a65f1c; active takes 2, not current 2 |
| Q-P2 | PI-25 | prompt_compiled_after_render | True | == False | documented→warn | 🟡 warn | h3_prompt compiled 2026-10-30T03:50:53Z vs video take #2 2026-10-29T18:57:55Z; take prompt sha 99f811de878e vs compiled h3_prompt sha 42ed7bec2e43 |
| Q-P3 | PI-24 | stems_video_sha_match | True | == True | documented→fail | ✅ pass | stems 214be0ab499b vs video 214be0ab499b |
| Q-P4·first | PI-08,PI-24 | keyframe_source_local | True | == True | documented→warn | ✅ pass | first keyframe recorded /root/claude-kimi-ns-studio-v1/nsfs_mirror/data/renders_gpu3/ep01/S1/frame.png → fetched from gpu3 (read-only copy) |
| Q-P4·last | PI-08,PI-24 | keyframe_source_local | False | == True | documented→warn | 🟡 warn | last keyframe recorded /root/claude-kimi-ns-studio-v1/ns-studio/data/run/weita/ep01/frames/ep01s1.rr_last.png → not in the local mirror; gpu3 fetch failed |
| Q-P5 | PI-24 | video_file_present_and_active | True | == True | documented→warn | ✅ pass | take 214be0ab499b vs video.mp4 214be0ab499b |

### S2（🔴 fail）

| 闸门 | PI | 指标 | 值 | 阈值 | 级别 | 结果 | 说明 |
|---|---|---|---|---|---|---|---|
| Q-K1 | PI-08 | video_size | [768, 1344] | == [768, 1344] | locked→fail | ✅ pass | video 768×1344 @ 24 fps, 243 frames |
| Q-K2 | PI-08 | first_frame_psnr_db | — | >= 20.0 | locked→fail | ⚪ unchecked | no first keyframe available locally |
| Q-K4·first | PI-19 | edge_dE2000 | — | <= 4.0 | suggested→warn | ⚪ unchecked | no first keyframe available locally |
| Q-K3 | PI-08 | last_frame_ssim | — | >= 0.55 | documented→fail | ⚪ unchecked | no last keyframe available locally (shot has no independent last keyframe, or it was not synced — PI-08) |
| Q-K4·last | PI-19 | edge_dE2000 | — | <= 4.0 | suggested→warn | ⚪ unchecked | no last keyframe available locally |
| Q-P6 | PI-08,PI-24 | shown_frame_vs_video_frame0_structure | — | >= 0.85 | documented→warn | ⚪ unchecked | shot has no frame.png in the mirror |
| Q-D1 | PI-01 | sface_median | 0.609 | >= 0.3 | locked→fail | ✅ pass | 22/22 samples with a face; min 0.498; no-face samples 0 |
| Q-D2 | PI-01 | sface_min_2s_window_median | 0.554 | >= 0.2 | suggested→warn | ✅ pass | median per 2 s window (4 samples), minimum over windows |
| Q-D3 | PI-03 | hair_hsv_bad_frames | 0 | == 0 | documented→warn | ✅ pass | 0/22 sampled frames fail the S3-F3 HSV rule |
| Q-D4 | PI-03 | hair_max_dE2000_vs_first | 4.57 | <= 12.0 | suggested→warn | ✅ pass | hair-band LAB ΔE2000 vs first sample (t=0.0s); per sample [0.0, 0.33, 0.33, 0.36, 0.6, 0.76, 1.02, 1.23, 1.04, 1.03, 0.95, 1.36, 1.45, 1.55, 1.1, 2.68, 4.57, 4.26, 1.97, 0.96, 1.02, 1.05] |
| Q-D5 | PI-04 | torso_ab_bhattacharyya_max | 0.382 | <= 0.45 | suggested→warn | ✅ pass | face-anchored torso box; worst at t=8.0s; 22 samples |
| Q-D6 | PI-04 | torso_dominant_dE2000_max | 47.7 | 待项目方定 | pending→info | ℹ info | face-anchored torso box; dominant LAB ΔE2000 vs first sample |
| Q-A1 | PI-11 | clap_music_score | 0.039 | <= 0.3 | suggested→warn | ✅ pass | prompt non_diegetic_music = unspecified; sum of CLAP music-labels on the full H3 non-vocal bed (audio_post h3_rest_tags) |
| Q-A1b | PI-11 | bed_tonal_ratio | 0.109 | 待项目方定 | pending→info | ℹ info | share of frames with a sustained tonal peak |
| Q-A2 | PI-14 | h3_integrated_lufs | -9.4 | -30.0 … -16.0 | suggested→warn | 🟡 warn | ffmpeg ebur128 (BS.1770) |
| Q-A2b | PI-14 | h3_true_peak_dbtp | -0.3 | <= -1.0 | suggested→warn | 🟡 warn |  |
| Q-A3 | PI-13 | male_f0_voiced_s | — | <= 0.5 | suggested→warn | ⚪ unchecked | a male speaker is in the H3 dialogue |
| Q-A4 | PI-13 | pitch_band_count_excess | 0 | <= 0 | pending→warn | ✅ pass | 1 pitch band(s) >0.5 s vs 2 expected gender(s) |
| Q-A5 | PI-12 | voiced_s_first_1s | — | < 0.3 | suggested→warn | ⚪ unchecked | shot has H3 dialogue (start time unknown) |
| Q-P1 | PI-25,PI-05 | bible_version | ['image#1:unstamped', 'video#1:unstamped'] | == current bible_version | locked→fail | 🔴 fail | current bible_version da4109a65f1c; active takes 2, not current 2 |
| Q-P2 | PI-25 | prompt_compiled_after_render | True | == False | documented→warn | 🟡 warn | h3_prompt compiled 2026-10-30T03:50:53Z vs video take #1 2026-10-29T18:30:41Z; take prompt sha ae64362c705b vs compiled h3_prompt sha 5d0d980b2c65 |
| Q-P3 | PI-24 | stems_video_sha_match | True | == True | documented→fail | ✅ pass | stems ac2fc34eb9a5 vs video ac2fc34eb9a5 |
| Q-P4·first | PI-08,PI-24 | keyframe_source_local | False | == True | documented→warn | 🟡 warn | first keyframe recorded /root/claude-kimi-ns-studio-v1/ns-studio/data/run/weita/ep01/frames/ep01s2.png → not in the local mirror; gpu3 fetch failed |
| Q-P5 | PI-24 | video_file_present_and_active | True | == True | documented→warn | ✅ pass | take ac2fc34eb9a5 vs video.mp4 ac2fc34eb9a5 |

### S3（🔴 fail）

| 闸门 | PI | 指标 | 值 | 阈值 | 级别 | 结果 | 说明 |
|---|---|---|---|---|---|---|---|
| Q-K1 | PI-08 | video_size | [768, 1344] | == [768, 1344] | locked→fail | ✅ pass | video 768×1344 @ 24 fps, 243 frames |
| Q-K1b·first | PI-08 | keyframe_aspect_rel_diff | 0 | <= 0.01 | locked→fail | ✅ pass | first keyframe 1152×2016 vs video 768×1344 |
| Q-K2 | PI-08 | first_frame_psnr_db | 21.5 | >= 20.0 | locked→fail | ✅ pass | SSIM 0.5469 |
| Q-K6 | PI-08 | first_frame_ssim | 0.547 | 待项目方定 | pending→info | ℹ info | PSNR 21.521 dB |
| Q-K4·first | PI-19 | edge_dE2000 | 1.19 | <= 4.0 | suggested→warn | ✅ pass | first 0.5s mean LAB [55.4, 3.0, -3.0] vs keyframe [56.2, 2.2, -2.8] |
| Q-K5 | PI-19 | max_abs_dL | 1.52 | <= 8.0 | suggested→warn | ✅ pass | max /ΔL*/ over 15/243 frames that structurally match the keyframe (≥0.85): frame 14 (0.58 s) signed -1.52; all frames: 8.04 at 10.08 s |
| Q-K3 | PI-08 | last_frame_ssim | — | >= 0.55 | documented→fail | ⚪ unchecked | no last keyframe available locally (shot has no independent last keyframe, or it was not synced — PI-08) |
| Q-K4·last | PI-19 | edge_dE2000 | — | <= 4.0 | suggested→warn | ⚪ unchecked | no last keyframe available locally |
| Q-P6 | PI-08,PI-24 | shown_frame_vs_video_frame0_structure | 0.118 | >= 0.85 | documented→warn | 🟡 warn | frame.png structure vs video frame 0; sha equal to the keyframe used: False (not in the local mirror; gpu3 fetch failed; INFERRED by structure match 0.974) |
| Q-D1 | PI-01 | sface_median | 0.305 | >= 0.3 | locked→fail | ✅ pass | 15/22 samples with a face; min -0.023; no-face samples 7 |
| Q-D2 | PI-01 | sface_min_2s_window_median | 0.082 | >= 0.2 | suggested→warn | 🟡 warn | median per 2 s window (4 samples), minimum over windows |
| Q-D3 | PI-03 | hair_hsv_bad_frames | 0 | == 0 | documented→warn | ✅ pass | 0/15 sampled frames fail the S3-F3 HSV rule |
| Q-D4 | PI-03 | hair_max_dE2000_vs_first | 6.28 | <= 12.0 | suggested→warn | ✅ pass | hair-band LAB ΔE2000 vs first sample (t=0.0s); per sample [0.0, 0.3, 3.44, 5.41, 6.28, 6.26, 5.62, 5.69, 4.68, 2.12, 2.54, 4.35, 2.43, 2.61, 4.37] |
| Q-D5 | PI-04 | torso_ab_bhattacharyya_max | 0.586 | <= 0.45 | suggested→warn | 🟡 warn | face-anchored torso box; worst at t=7.0s; 15 samples |
| Q-D6 | PI-04 | torso_dominant_dE2000_max | 47.4 | 待项目方定 | pending→info | ℹ info | face-anchored torso box; dominant LAB ΔE2000 vs first sample |
| Q-A1 | PI-11 | clap_music_score | 0.999 | <= 0.3 | suggested→warn | 🟡 warn | prompt non_diegetic_music = unspecified; sum of CLAP music-labels on the full H3 non-vocal bed (audio_post h3_rest_tags) |
| Q-A1b | PI-11 | bed_tonal_ratio | 0.757 | 待项目方定 | pending→info | ℹ info | share of frames with a sustained tonal peak |
| Q-A2 | PI-14 | h3_integrated_lufs | -11.5 | -30.0 … -16.0 | suggested→warn | 🟡 warn | ffmpeg ebur128 (BS.1770) |
| Q-A2b | PI-14 | h3_true_peak_dbtp | -1 | <= -1.0 | suggested→warn | ✅ pass |  |
| Q-A3 | PI-13 | male_f0_voiced_s | 0 | <= 0.5 | suggested→warn | ✅ pass | voiced <165 Hz; H3 dialogue genders none |
| Q-A4 | PI-13 | pitch_band_count_excess | 0 | <= 0 | pending→warn | ✅ pass | 0 pitch band(s) >0.5 s vs 0 expected gender(s) |
| Q-A5 | PI-12 | voiced_s_first_1s | 0 | < 0.3 | suggested→warn | ✅ pass | voiced seconds in 0–1.0 s |
| Q-P1 | PI-25,PI-05 | bible_version | ['video#2:unstamped', 'image#10:unstamped'] | == current bible_version | locked→fail | 🔴 fail | current bible_version da4109a65f1c; active takes 2, not current 2 |
| Q-P2 | PI-25 | prompt_compiled_after_render | True | == False | documented→warn | 🟡 warn | h3_prompt compiled 2026-10-30T03:50:53Z vs video take #2 2026-10-29T18:31:11Z; take prompt sha 110541555e39 vs compiled h3_prompt sha 1d4f97dcb95a |
| Q-P3 | PI-24 | stems_video_sha_match | True | == True | documented→fail | ✅ pass | stems 3e7f35d65abd vs video 3e7f35d65abd |
| Q-P4·first | PI-08,PI-24 | keyframe_source_local | False | == True | documented→warn | 🟡 warn | first keyframe recorded /root/claude-kimi-ns-studio-v1/ns-studio/data/run/weita/ep01/frames/ep01s3.png → not in the local mirror; gpu3 fetch failed; INFERRED by structure match 0.974 |
| Q-P5 | PI-24 | video_file_present_and_active | True | == True | documented→warn | ✅ pass | take 3e7f35d65abd vs video.mp4 3e7f35d65abd |

### S4（🔴 fail）

| 闸门 | PI | 指标 | 值 | 阈值 | 级别 | 结果 | 说明 |
|---|---|---|---|---|---|---|---|
| Q-K1 | PI-08 | video_size | — | == [768, 1344] | locked→fail | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-K2 | PI-08 | first_frame_psnr_db | — | >= 20.0 | locked→fail | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-K3 | PI-08 | last_frame_ssim | — | >= 0.55 | documented→fail | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-D1 | PI-01 | sface_median | — | >= 0.3 | locked→fail | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-A1 | PI-11 | clap_music_score | — | <= 0.3 | suggested→warn | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-A2 | PI-14 | h3_integrated_lufs | — | -30.0 … -16.0 | suggested→warn | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-A3 | PI-13 | male_f0_voiced_s | — | <= 0.5 | suggested→warn | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-P1 | PI-25,PI-05 | bible_version | ['image#2:unstamped', 'video#1:unstamped'] | == current bible_version | locked→fail | 🔴 fail | current bible_version da4109a65f1c; active takes 2, not current 2 |
| Q-P2 | PI-25 | prompt_compiled_after_render | True | == False | documented→warn | 🟡 warn | h3_prompt compiled 2026-10-30T03:50:53Z vs video take #1 2026-10-29T19:34:54Z; take prompt sha bd06832734d6 vs compiled h3_prompt sha 76b2763b2264 |
| Q-P3 | PI-24 | stems_video_sha_match | — | == True | documented→fail | ⚪ unchecked | video file not in the mirror |
| Q-P5 | PI-24 | video_file_present_and_active | False | == True | documented→warn | 🟡 warn | active video take #1 (renders_gpu3/ep01/S4/takes/video_001.mp4) and video.mp4 both missing |

### S5（🔴 fail）

| 闸门 | PI | 指标 | 值 | 阈值 | 级别 | 结果 | 说明 |
|---|---|---|---|---|---|---|---|
| Q-K1 | PI-08 | video_size | — | == [768, 1344] | locked→fail | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-K2 | PI-08 | first_frame_psnr_db | — | >= 20.0 | locked→fail | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-K3 | PI-08 | last_frame_ssim | — | >= 0.55 | documented→fail | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-D1 | PI-01 | sface_median | — | >= 0.3 | locked→fail | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-A1 | PI-11 | clap_music_score | — | <= 0.3 | suggested→warn | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-A2 | PI-14 | h3_integrated_lufs | — | -30.0 … -16.0 | suggested→warn | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-A3 | PI-13 | male_f0_voiced_s | — | <= 0.5 | suggested→warn | ⚪ unchecked | no active video in the local mirror (takes.json active video #1) |
| Q-P1 | PI-25,PI-05 | bible_version | ['video#1:unstamped', 'image#22:unstamped'] | == current bible_version | locked→fail | 🔴 fail | current bible_version da4109a65f1c; active takes 2, not current 2 |
| Q-P2 | PI-25 | prompt_compiled_after_render | True | == False | documented→warn | 🟡 warn | h3_prompt compiled 2026-10-30T03:50:54Z vs video take #1 2026-10-29T18:31:21Z; take prompt sha 8f0562bc1296 vs compiled h3_prompt sha 9606d0cfe1c5 |
| Q-P3 | PI-24 | stems_video_sha_match | — | == True | documented→fail | ⚪ unchecked | video file not in the mirror |
| Q-P5 | PI-24 | video_file_present_and_active | False | == True | documented→warn | 🟡 warn | active video take #1 (renders_gpu3/ep01/S5/takes/video_001.mp4) and video.mp4 both missing |

### S6（🔴 fail）

| 闸门 | PI | 指标 | 值 | 阈值 | 级别 | 结果 | 说明 |
|---|---|---|---|---|---|---|---|
| Q-K1 | PI-08 | video_size | — | == [768, 1344] | locked→fail | ⚪ unchecked | no active video in the local mirror (shot has no video take) |
| Q-K2 | PI-08 | first_frame_psnr_db | — | >= 20.0 | locked→fail | ⚪ unchecked | no active video in the local mirror (shot has no video take) |
| Q-K3 | PI-08 | last_frame_ssim | — | >= 0.55 | documented→fail | ⚪ unchecked | no active video in the local mirror (shot has no video take) |
| Q-D1 | PI-01 | sface_median | — | >= 0.3 | locked→fail | ⚪ unchecked | no active video in the local mirror (shot has no video take) |
| Q-A1 | PI-11 | clap_music_score | — | <= 0.3 | suggested→warn | ⚪ unchecked | no active video in the local mirror (shot has no video take) |
| Q-A2 | PI-14 | h3_integrated_lufs | — | -30.0 … -16.0 | suggested→warn | ⚪ unchecked | no active video in the local mirror (shot has no video take) |
| Q-A3 | PI-13 | male_f0_voiced_s | — | <= 0.5 | suggested→warn | ⚪ unchecked | no active video in the local mirror (shot has no video take) |
| Q-P1 | PI-25,PI-05 | bible_version | ['image#6:unstamped'] | == current bible_version | locked→fail | 🔴 fail | current bible_version da4109a65f1c; active takes 1, not current 1 |
| Q-P2 | PI-25 | prompt_compiled_after_render | — | == False | documented→warn | ⚪ unchecked | no active video take |
| Q-P3 | PI-24 | stems_video_sha_match | — | == True | documented→fail | ⚪ unchecked | no audio/stems.json |
| Q-P5 | PI-24 | video_file_present_and_active | — | == True | documented→warn | ⚪ unchecked | no active video take |

## 过期 / 未盖章的 active take（Q-P1，R-C8）

| 镜 | stage | take | 状态 | take 的 bible_version |
|---|---|---|---|---|
| S1 | image | 8 | unstamped | — |
| S1 | video | 2 | unstamped | — |
| S2 | image | 1 | unstamped | — |
| S2 | video | 1 | unstamped | — |
| S3 | video | 2 | unstamped | — |
| S3 | image | 10 | unstamped | — |
| S4 | image | 2 | unstamped | — |
| S4 | video | 1 | unstamped | — |
| S5 | video | 1 | unstamped | — |
| S5 | image | 22 | unstamped | — |
| S6 | image | 6 | unstamped | — |

## 阈值表（本次运行）

| 闸门 | 指标 | 阈值 | 状态 | 级别 | 出处 |
|---|---|---|---|---|---|
| Q-K1 | video_size | == [768, 1344] | locked | fail | rule_ids P-B3 (24 fps, 768×1344) |
| Q-K1b | keyframe_aspect_rel_diff | <= 0.01 | locked | fail | rule_ids P-B2 (same 4:7 centre crop for first/last; stretch vs crop → ghosting) |
| Q-K2 | first_frame_psnr_db | >= 20.0 | locked | fail | SOP_parameters 视频 QC（锁定 2026-10-29）: 首帧 PSNR ≥20 dB |
| Q-K3 | last_frame_ssim | >= 0.55 | documented | fail | consistency_impl §二 视频闸门; gpu3 weita_series LAST_SSIM_MIN = 0.55 |
| Q-K4 | edge_dE2000 | <= 4.0 | suggested | warn | production_issues PI-19: 前/后 0.5 s 与首/尾帧人物区域 ΔE2000 ≤ 4（建议值，未锁定） |
| Q-K5 | max_abs_dL | <= 8.0 | suggested | warn | production_issues PI-19: 全片 L* 相对首帧漂移 ≤ 8（建议值，未锁定） |
| Q-K6 | first_frame_ssim | 待项目方定 | pending | info | no documented SSIM bound for the first frame (待项目方定); reported only |
| Q-D1 | sface_median | >= 0.3 | locked | fail | SOP_parameters 视频 QC（锁定）: SFace 中位数 ≥0.30; gpu3 SIM_CLIP_MIN |
| Q-D2 | sface_min_2s_window_median | >= 0.2 | suggested | warn | production_issues PI-01: 任意连续 2 秒最小值 ≥0.20（建议值） |
| Q-D3 | hair_hsv_bad_frames | == 0 | documented | warn | S3-F3 hair_colour (gpu3 weita_series.hair_colour) applied per sampled video frame; frame gate is block, the video use is new → warn |
| Q-D4 | hair_max_dE2000_vs_first | <= 12.0 | suggested | warn | production_issues PI-03: 头发 LAB ΔE ≤ 12（建议值） |
| Q-D5 | torso_ab_bhattacharyya_max | <= 0.45 | suggested | warn | production_issues PI-04: 人物区域 LAB 直方图相对首帧 Bhattacharyya ≤0.45（建议值） |
| Q-D6 | torso_dominant_dE2000_max | 待项目方定 | pending | info | dominant clothing colour drift; no documented bound (待项目方定) |
| Q-A1 | clap_music_score | <= 0.3 | suggested | warn | production_issues PI-11: non_diegetic_music = N/A 时 CLAP music ≤0.30（建议值） |
| Q-A1b | bed_tonal_ratio | 待项目方定 | pending | info | DSP proxy for sustained tonal content in the non-vocal bed (待项目方定); reported only |
| Q-A2 | h3_integrated_lufs | -30.0 … -16.0 | suggested | warn | production_issues PI-14: H3 原声 −30…−16 LUFS（建议值） |
| Q-A2b | h3_true_peak_dbtp | <= -1.0 | suggested | warn | production_issues PI-14 / SOP_parameters S5 响度（待验证）: 真峰值 ≤ −1 dBTP |
| Q-A3 | male_f0_voiced_s | <= 0.5 | suggested | warn | production_issues PI-13: F0 中位数 <165 Hz 的人声段 >0.5 s 且本镜不允许男声 → 报（建议值） |
| Q-A4 | pitch_band_count_excess | <= 0 | pending | warn | speaker-count proxy: voiced pitch bands (<165 Hz / ≥165 Hz, each >0.5 s) vs genders of the H3 dialogue speakers (待项目方定; no speaker-embedding model locally) |
| Q-A5 | voiced_s_first_1s | < 0.3 | suggested | warn | production_issues PI-12: 无对白镜头前 1.0 s 语音 <0.3 s（建议值） |
| Q-P1 | bible_version | == current bible_version | locked | fail | rule_ids R-C8 (输入未过期：take 的 bible_version 等于当前值) — block |
| Q-P2 | prompt_compiled_after_render | == False | documented | warn | PI-25: 规则/提示词改动后已出 take 必须标 stale; compiled.h3_prompt_compiled_at vs take.created_at |
| Q-P3 | stems_video_sha_match | == True | documented | fail | PI-24 / SOP S5: 每镜 video_sha256 必须等于 renders_gpu3 中的文件 |
| Q-P4 | keyframe_source_local | == True | documented | warn | PI-08: 视频 take 实际用的首/尾帧要同步到 renders_gpu3 |
| Q-P5 | video_file_present_and_active | == True | documented | warn | PI-24: 镜像里 video.mp4 = active video take（sha） |
| Q-P6 | shown_frame_vs_video_frame0_structure | >= 0.85 | documented | warn | PI-08: 画布显示的帧（frame.png）必须是视频实际用的首帧; 0.85 = ns_post.colormatch match_min |
| Q-S1 | sync_heartbeat_age_min | <= 30.0 | suggested | warn | production_issues PI-24: 心跳超过 30 分钟没更新 → 报警（建议值） |
