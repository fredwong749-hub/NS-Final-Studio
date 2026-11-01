# AUDIT · IMGFIX 复核 r01（2026-11-01 22:05–22:08，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG “21:2x IMGFIX”、data/review_pages/imgfix/{index.html, summary.json}（21:34）、data/ab/imgfix/sheet_acc3.jpg / sheet_f2acc.jpg / takes.jsonl（54 行）、asset_refs.py（K-AST-262 / K-REN-704）、tests/test_imgfix.py、first_frame_jobs 的重编和备份。机读版：data/qa/audit/IMGFIX_r01.json

## 结论：两个根因的方向通过，看图数字基本属实；有 2 个 P1：①侧脸句会让身份相似度大幅下降，契约 Q1 没测；②现在的 first_frame_jobs.json 和编译器又对不上了（85/93 不一致，2 条测试红）

### 1 看图核对（AUDIT 自己看了两张拼图）

| 说法 | AUDIT 看到的 | 结论 |
|---|---|---|
| 看镜头 0/8（ACC3 4 张 + F2acc 4 张） | sheet_acc3.jpg：S3 203 / 303、S6 206 / 306 都是四分之三侧脸，视线看画面一侧；sheet_f2acc.jpg：S1 201 / 301 低头看键盘，S2 202 / 302 低头或侧看。**8 张没有一张正对镜头** | 属实 |
| 外套 6/6（S1 0/2） | S1 两张都只穿衬衫，没有外套（0/2，和报告一致）；S2 两张、S3 两张、S6 306 都是黑色西装外套；**S6 206 是米色 / 浅驼色外套**（q2=0.404）。外套“有没有”确实是 6/6，但 206 的**颜色和另外 5 张黑色不一致**，跨镜会穿帮 | “有外套”属实；颜色一致性只有 5/6 |
| summary.json | ACC3：gaze_hit 0/4、q2_pass 4/4；F2acc：gaze_hit 0/4、q2_pass 2/4，和拼图一致 | 属实 |

### 2 身份代价（P1）

summary.json 里，所有带“侧脸句”（T3 / ACC2 / ACC3 / O2+T3）的组，SFace 身份相似度都明显下降：
- 基线 A0 0.922、R4 0.930、O1 0.942；
- T3 0.719（最低 0.62）、ACC2 0.711（最低 0.616）、**ACC3 0.697（最低 0.659）**、O2+T3 0.665。

也就是说，K-REN-704 把侧脸句放到提示词最前面，解决了看镜头，但身份相似度从 0.92 掉到 0.70 左右。A/B 只记了 SFace（takes.jsonl 的 metrics.sface_vs_face_A），**没有跑契约 Q1（ArcFace，林晚线 0.7，config/gen_contract.json 第 49–50 行）**。两种指标量纲不同，不能直接套线，但如果 Q1 也是同样幅度下降，全量重做出来的单人镜会大批判 Q1 不过、反复重出。进生产之前要先在这 8 张上跑一次 postflight Q1。

### 3 代码和测试
- asset_refs.py：第 390 行 sheet_item_check、第 416 行 sheet_outer_gaps（K-AST-262），第 1138 行 single_turn_line、第 1165 行套进 prompt_prefix（K-REN-704）。
- 测试：test_imgfix + test_image_jobs + test_unified_frame 一起跑，**16 过 2 不过**：
  - test_image_jobs::test_series_jobs_prompt_equals_compiler_output：audit_framing 显示 93 个作业里只有 85 个和编译器一致（`assert (93 >= 1 and 85 == 93)`）；
  - test_image_jobs::test_submit_gate_rejects_hand_written_prompt：作业 ep01-S1 原样提交就被 compile_mismatch 判成不一致。
- 时间线（文件修改时间）：first_frame_jobs.json 21:30:11 重编（备份 first_frame_jobs.before_imgfix_20261101.json 21:14，在）；之后 services/agent/ns_agent/frame_job.py 在 **22:06:29** 还在被改，另外有人在 21:50 留了备份 first_frame_jobs.before_K-REN-103.json。所以现在是编译器改了、作业清单还没重编的中间状态。
- 影响：producer 从 19:41 起被总调度暂停（log.jsonl：“单人镜看镜头 + 缺外套为系统性问题……先修根因再继续”），目前没有出图在跑，所以**不是 P0**；但恢复全量重做之前，必须重编，并让 test_image_jobs 两条转绿，否则提交闸门会拒掉对不上的作业（submit_jobs.compile_mismatch）。

### 4 其它
- 根因 ①（外套缺失 = 现行造型 A 设定图是没画外套的 v1 候选）：报告说 character_hub._sheet_candidates 已经把 adopted v2 放进候选，但**现行 sheets_chosen 有没有换回 v2_s202**，交付里没写清楚，AUDIT 也没查到换图记录。如果没换，F2acc 的 S1 0/2 就是这个原因。换设定图属于项目方闸门（OT6），要走总调度出选择题。
- S★ 和身份脸没动，和交付说法一致（face_overrides 仍是 lin_wan_face_hd_A_s202，见 RSI_r03）。

## 给 IMGFIX / 总调度
1. （P1）在 ACC3 / F2acc 的 8 张图上跑契约 postflight Q1，报 ArcFace 数值；如果大批低于 0.7，K-REN-704 要和身份一起权衡（比如侧脸角度改小）。
2. （P1）重编 first_frame_jobs（先确认 22:06 那次 frame_job.py 的改动已经停了），让 test_image_jobs 两条转绿，再恢复 producer。
3. S6 206 的外套颜色不一致：建议 VQAGATE 的 outfit / continuity 项把“颜色”也算进去。
4. 造型 A 的现行设定图要不要换回 v2_s202，需要项目方拍板。
