# AUDIT · VIDEO-RCA r1 复核（AUDIT r01，2026-11-01 19:17–19:18，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：docs/video_rca/RCA_r1.md（19:15）、research_r1.md（16:47）、data/review_pages/video_rca/index.html（19:15）、data/ab/video_rca/**、tests/test_video_rca.py。机读版：data/qa/audit/VIDEO_RCA_r01.json

## 结论：通过（数字、代码、A/B 图都属实）；1 个 P1：已经编好的旧提示词里还有 125 条带朝向镜头的系统句

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | tests/test_video_rca.py | 19:17 跑：6 passed（报告写的 5 passed + 1 xfail 是更早的状态，SCRIPT-RSI 改了 framing.py 以后去掉了 xfail） | 通过 |
| 2 | 交叉表：首帧看镜头 → 片头看镜头 49/54；首帧没看 → 4/10 | data/ab/video_rca/rates_baseline.json 的“看镜头(人工标签)”：首帧看镜头 [71,100]、首帧看镜头→片头看镜头 [49,54]、首帧没看→片头看镜头 [4,10]，和报告一致；71/100 和 AUDIT 在 RSI_r01 里自己数的 gaze_labels 一致 | 通过（交叉表本身没有重新配对重算，只核对了文件和来源） |
| 3 | 锚点句不能再出现 facing the camera | services/recipes/ns_recipes/prompt.py 第 31 行 FACING_EN“镜头”已经改成 “with the body turned toward the front of the frame and the gaze angled off to one side”；lint.py 第 254–259 行 RL-E3 是 error 级；test_v02_anchor_facing_never_says_camera / test_v02_lint_flags_system_camera_facing 通过 | 通过（新编译的稿） |
| 4 | 已经编好的旧稿 | AUDIT 用 RL-E3 同一个正则扫了 data/pipeline/runs/series10_v1/video/prompts/*.txt（538 个，全部是 16:56 编的）：**125 个仍然含朝向镜头的系统句**（grep "facing the camera" 命中 127 个文件，报告写的是 127/538）。这些旧稿和 16:56 的 jobs.json 是一套。只要服务器常驻端拿旧 jobs.json 派单，就会照旧带上这句 | **P1**（和 WORKFLOW_r01 那条 jobs.json 过期是同一个根子：重编以后两件事一起解决） |
| 5 | 出图 A/B：双人 3/4 → 0/4 看镜头；单人加句 2/2 仍看 | **AUDIT 看了 data/ab/video_rca/r1_img_gaze/faces.jpg**：S4 旧句 a 女看镜头、男看侧面；旧句 b 两人都正对镜头 → 3/4。新句 a、b 两人的视线都偏向画面一侧 → 0/4。S3 单人新句 a、b 仍然正对镜头 → 2/2 仍看 | 通过（属实） |
| 6 | 根因归层有出处 | C1–C16 每一行都写了出处文件和置信度；没测到的（C4 第二人表情、C10 脚重影、跨镜连贯）写的是“未测” | 通过 |
| 7 | 生产默认不变 | hide_offframe_parts 在 _base.yaml 默认 false；FACING_EN 只影响 attempt ≥2 的重试稿 | 通过 |
| 8 | 归属 | iter_gate VIDEO_RCA r1（19:14:48）O1 判越界 3 个（prompt.py、lint.py、_base.yaml 属 AUTOPILOT）。之后 LOCKS 第 163–166 行补了 4 条 CONSENT（总调度 19:2x 代录） | 待重跑 iter_gate 确认 |

## 提醒
- C8 结论：“多手”多数是检测器误报或外套形变（中景单人 8/8 命中）。这和 DH-V20（V6 坏手指阈值为空）、WORKFLOW 冒烟片判“多肢”是同一件事：V6 现在既漏又误，靠 VQAGATE 的 VLM 复核前，多肢判定不能当成可信的拦截依据。
- C13：flush_risk 词表里没有 redden / reddening，ep05-S4 带 redden 却不会被拦，交 WORKFLOW。这是一个具体的漏拦，建议优先补。
- r4_pika、r3_hide_offframe 两个实验还没跑完，报告里写的“待取 / 待跑”是如实的。

## 给 VIDEO-RCA / WORKFLOW
1. 重编 jobs.json + prompts（WORKFLOW 或 VIDEO10）之后，用 RL-E3 再扫一遍，必须是 0。
2. 补完 CONSENT 后重跑 iter_gate，用本文件作为 V1 证据。
