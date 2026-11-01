# 视线 / 首秒定格 / 字幕带检测器标定（ACTING，K-REV-G04）

- 检测器：packages/qc/ns_qc/gaze.py（YuNet 五点头部朝向 + 眼球暗区偏移；帧差首秒定格；下 38% 字幕带）。阈值暂定（PROVISIONAL=True，像素检测的 BLOCK 开关保持关闭）。2026-11-01 16:10 起看镜头已转拦截（项目方原话，D-VQA-01）：由本地看图闸门 Q9 eye_contact 拦，像素检测只作旁证；看图闸门标定见 docs/vqa/GATE_CALIBRATION.md
- 接线：出图 postflight G1（status 恒 na，evidence.would_fail）；VIDEO10 score_clip `acting` 字段，命中只进 gate.soft
- 样本：data/pipeline/runs/series10_v1/video/inputs/*.jpg（72 张首帧）+ video/_preview/*.mp4（原始片段）→ data/acting/calib_results.json
- 暂定阈值下的分布（11-01 10:53，未标定，不代表对错）：首帧 72 张：疑似看镜头 36、视线离轴 35、未测 1
- 标注页：data/review_pages/acting_gaze_calib.html（183 个样本，总调度点选后“导出标注” → data/acting/gaze_labels.json）
- 判分：`.venv/Scripts/python.exe tools/acting/calibrate_gaze.py --score` → 召回 ≥0.85 且误报 ≤0.15 = 分得开，才提议 BLOCK=True（总调度批准）
- 已知局限：眼球用最暗像素质心，睫毛 / 眼影会把 iris_dx 往正向偏（首帧均值约 +0.1）；眼距 <22 px 记未测；字幕带是形状启发式，未在真字幕样本上验证

## 第 1 次判分（11-01，总调度标注 data/acting/gaze_labels.json 183 条；结果 data/acting/calib_score.json）
- 判分器修正：原来用子串判“看镜头”，“没看镜头”也被算成看镜头 → 改为按选项全文比对，并把图片 / 片段看镜头 / 片段定格分三项
- 图片看镜头（n=100）：召回 0.423，误报 0.207 → 分不开
- 片段首秒看镜头（n=72）：召回 0.607，误报 0.188 → 分不开（标注只看 4 帧，把握一般）
- 片段首秒定格（n=72，正例仅 11）：召回 0.455，误报 0.213 → 分不开
- 图片 |gaze_x| 阈值扫描（偶数位定阈值、奇数位留出）：最佳 0.49，留出召回 0.865、误报 0.385 → 仍分不开（标注里看镜头占 71%，阴性样本少）
- 结论：不开拦截，BLOCK 保持 False。下一步思路：换带眼球关键点的模型（如 MediaPipe Face Mesh 的虹膜点 / L2CS-Net 视线估计）再标定，阴性样本要补足
