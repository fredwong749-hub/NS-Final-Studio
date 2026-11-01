# 旧来源 P4_epNN.md 的读取方（K-OPS-Q24，RSI 11-01；交 CLEANUP 隔离）

背景：PROD 18:30 导入 D-SCR-07，data/import/script_v2.json（sha d1701401…）镜数从 80 变成 93。可是首帧作业还在读 data/pipeline/runs/series10_v1/epNN/P4_epNN.md（10-31 21:33 的旧稿），结果新增的 13 镜没有作业，已有 80 镜的出图文字也不是导入稿。
现在生产出图的唯一来源 = 导入稿。`tools/pipeline/image_jobs.load_episode(P4)` 默认直接抛 LegacySourceError；写作 / 调研工具确实要读，必须显式设 NS_ALLOW_P4_SOURCE=1。

## 已改成读导入稿
- tools/pipeline/image_jobs.py：rebuild_first_frame_jobs、新增 sync_job_set / jobs_vs_import
- tools/pipeline/submit_jobs.py：compile_mismatch
- tools/prompt_v2/audit_framing.py：audit
- tools/autopilot/full_redo.py：G21 改成调 jobs_vs_import
- tests/test_image_jobs.py

## 还在读 P4 稿（经 IJ.load_episode 的，现在会直接报错 = 已被堵住）
- tools/assetmaster/frames_v2.py:125（ASSETMASTER，不活跃）
- tools/gen_contract/calibrate_imgfix.py:75、look_audit.py:41、reflock_v9.py:41、reflock_validate.py:45（REFLOCK 的标定 / 审计工具）
- tools/series10_imggen/imgfix_ab.py:142（IMGGEN，不活跃）

## 直接读 P4 文件、没走 IJ 的（需要各 owner 改成读导入稿，或者由 CLEANUP 隔离）
- tools/qa/data_parity.py:113（DATAALIGN）：D-SCRIPT 拿 storyboard 和 P4 原文比，导入后口径过期——优先级最高
- tools/bgm/bgm_timeline.py:63（BGM10）
- tools/series10_imggen/scene_plates.py:38（IMGGEN）
- tools/assetmaster/merge_import.py:35、look_fix.py:69（ASSETMASTER：P4 → 导入的写作侧工具，属于合法用途）
- tools/series10_video/build_jobs.py:78：只有加 --from-p4 才走这条，默认已经是 import
- services/api/ns_api/story_runs.py:125：写作运行页展示 P4 原文，属于合法用途
- tools/autopilot/run.py、tools/pipeline/run_chain.py、tools/prompt_v2/director_to_p4.py：写作链路自己产出 P4，属于合法用途

## CLEANUP 11-01 r2 处理结果（总调度 fredw-2b 转交）
| 读取方 | 处理 |
|---|---|
| tools/qa/data_parity.py（D-SCRIPT） | 只和导入稿比（原本就在比 script_v2 字段）；P4 附加对照改为仅 NS_ALLOW_P4_SOURCE=1 |
| tools/bgm/bgm_timeline.py | episode_inputs 改取导入稿来源 md（script_v2.json sources 最后一个覆盖本集、sha256 一致）的本集原文；实测 ep01/05/10 各 9 镜 = 导入稿 |
| tools/assetmaster/frames_v2.py | 改读 IJ.import_episode（生产出图） |
| tools/gen_contract/look_audit.py | 默认已读导入稿；`--source p4` 调研对照显式放行 |
| tools/gen_contract/calibrate_imgfix.py、reflock_v9.py、reflock_validate.py、tools/series10_imggen/imgfix_ab.py | 标定 / 对照实验复现当时 P4 稿出的图 = 调研用途，显式 setdefault NS_ALLOW_P4_SOURCE=1 |
| tools/series10_imggen/scene_plates.py | 10-31 一次性工具；未设 NS_ALLOW_P4_SOURCE=1 直接退出 |
| merge_import.py、look_fix.py、story_runs.py、run.py、run_chain.py、director_to_p4.py、build_jobs --from-p4 | 写作链路 / 写作侧工具，合法读取，不改 |

P4 文件本身：写作链路仍在产出和读取（run.py / run_chain / story_runs 展示），**不隔离**。
