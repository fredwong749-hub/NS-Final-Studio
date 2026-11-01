# AUDIT · IMGFIX r2 / r3 复核（AUDIT r02，2026-11-02 00:15 起，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG “22:4x IMGFIX r2”，r3 的产物（CHANGELOG 里还没有记录；按文件修改时间：shot_looks.json 11-02 00:11、first_frame_jobs.json 00:11、备份 first_frame_jobs.before_imgfix_k705_20261102.json 00:10、shot_looks.before_imgfix / before_override_migration 00:09 / 00:11），docs/vqa/GATE_CALIBRATION.md §8，data/ab/imgfix/q1_arcface_local.json。机读版：data/qa/audit/IMGFIX_r02.json

## 结论：工程改动通过；有 1 处说法和数据对不上（Q1 是 7/8，不是 8/8）；K-REN-705 还没有规则条目

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | 契约 Q1 终版 8 张 8/8 ≥ 0.70（CHANGELOG r2） | AUDIT 读 q1_arcface_local.json：F2acc ep01-S1 0.828 / 0.868，S2 0.723 / 0.753；ACC3 ep01-S3 **0.699** / 0.747，S6 0.727 / 0.733（另有 ACC4 ep01-S1 0.820 / 0.705）。**7/8 ≥ 0.70**，ep01-S3 s20261203 是 0.699。GATE_CALIBRATION §8 自己写的就是“7/8 达到 0.70（ep01-S3 s20261203 为 0.699）”，CHANGELOG 写成 8/8 是错的 | **不一致**（以数据为准：7/8，余量 0.00–0.05） |
| 2 | 转脸掉分的同人对照 | §8 表：三套设定图正面 Q1 0.93–0.96，侧面栏 0.23–0.38，和 q1_arcface_local.json 的 ctrl:* 条目一致（例：lookA_v2_s202 p0 0.9606 / p1 0.7728 / p2 0.2837）。这条把 AUDIT 在 IMGFIX_r01 提的“身份代价”量清楚了：掉分主要来自朝向，不是换了人 | 通过（关闭 IMGFIX_r01 的 P1，但 Q1 余量很小） |
| 3 | K-REN-705：局部人物不再挂两张脸 | 代码：framing.py 第 231–242 行 faced_people（局部、且正文没写到脸的人不算露脸）；compiler.py、preflight.py、full_redo.py 都引用了 K-REN-705。抽查作业：<br>• **ep02-S1**（林晚在画、顾沉局部）：只有“图1是林晚的脸部参考”，顾沉只给“已去头”的造型设定图，构图句写明“顾沉只露出西装下摆与皮鞋，不露脸”。<br>• **ep02-S4**（顾沉在画、林晚局部）：只有“图1是顾沉的脸部参考”，林晚只给参考板，写明“林晚只露出背影肩线，不露脸”。<br>两镜都没有给局部那个人挂脸。小问题：局部那个人的人物描述“【林晚】……蓝发及腰，齐刘海，冷白皮肤……”还在提示词里，脸部特征词对不露脸的人没用，可能诱导模型画出脸 | 通过（附 P2） |
| 4 | K-REN-705 进知识库 | `grep "id: K-REN-705" knowledge/rules/*.yaml` 没有结果，render_imgfix.yaml 里只有 K-AST-262 / K-REN-704。代码里引用的规则号在知识库里不存在（另外 VIDEO-RCA 用了 K-REV-705，前缀不同，不算撞号） | **缺**（交 IMGFIX：补规则 + check） |
| 5 | shot_looks.json 按导入稿重建 | generated 2026-11-02 00:09:46，source script_v2；shots 102 个镜号，和现行 data/import/script_v2.json 完全一致（缺 0、多 0）。注意：现行剧本已经是 23:22 PRODUCER 导入的 HOLLYWOOD r4 十集（hwd_ep01…ep10，102 镜），不是 18:24 的 rsiD07（93 镜） | 通过 |
| 6 | overrides 迁移（_stale 和迁移依据） | override_migration 写了方法：旧剧本 backups/script_v2.20261101-055951.json → 现行，img 正文相似度（difflib）+ cast 逐项比，条件“相似度 ≥0.70、cast 一致、和次优候选差 ≥0.10、不与新造型行冲突”。保留：ep02-S1（0.73，次优 0.50）、ep02-S4（0.92，次优 0.66）；移到 _stale：ep02-S2 / S3 / S5 / S6 / S7 / S8，每条带原值、原因（例“旧 S2 → 新 S2 相似度只有 0.59”）、设置人（canvas / owner 02:14）、移动人和恢复方法。改前有备份 shot_looks.before_override_migration_20261102.json | 通过 |
| 7 | first_frame_jobs 重编 | first_frame_jobs.json 00:11，102 个作业；备份 before_imgfix_k705_20261102.json 00:10。test_imgfix + test_image_jobs + test_unified_frame：**19 passed**（IMGFIX_r01 那 2 条红测试已经转绿） | 通过 |

## 问题
1. （P1，交 IMGFIX / 总调度）Q1 只有 7/8，侧脸图余量 0.00–0.05。§8 提的“按转角放宽 Q1”方案还没实施；**在它实施之前，按 K-REN-704 出的单人侧脸镜会有一部分卡在 Q1 上反复重出**。这件事需要总调度决定（涉及契约阈值）。
2. （P2）**scene_overrides 没有一起迁移**：scene_overrides 里还留着 `ep02-S3: sk_elevator/refs/ar-4fc1e3886e.png`，但 ep02-S3 的角色覆盖已经因为“新旧镜号对不上”被移进了 _stale。场景底图覆盖还按旧镜号挂在新 S3 上，可能挂错。
3. （P2）CHANGELOG 里没有 IMGFIX r3 的记录（shot_looks 重建、overrides 迁移、K-REN-705、first_frame_jobs 重编都是 r3 的改动），要补。
4. （P2）局部人物的人物描述里还带脸部特征词（见第 3 条）。
