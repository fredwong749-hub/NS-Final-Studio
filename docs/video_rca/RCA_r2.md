# VIDEO-RCA 第 2 轮（总调度 fredw-2b 11-01 19:2x 派；基底 = Pika Flex，项目方 18:0x 决定）

> 服务 OT9。项目方 18:2x：“所有图片不要看镜头，不要看镜头！”。本轮按总调度决定 1–6 执行；r1 报告 docs/video_rca/RCA_r1.md。

## 1 项目方任务 / 本轮问题

| 问 | 答 | 证据（置信度） |
|---|---|---|
| Q① 首帧不看镜头时，Pika 会不会转头看镜头？ | **不会。** 用 G6 新句出的两张“两人互看”首帧（A / B 两个 seed）出 Pika，第 0 / 48 / 96 / 150 / 188 帧 × 2 张脸 = 20 个样本，0 个看镜头；女主全程看男主，男主低头看她 | data/ab/video_rca/r4_pika/faces_vid.jpg（高：2 条片 20 个样本，人工逐帧看）；对照 r1 S4_pika（生产首帧女主看镜头）开头看镜头 |
| Q② 外套中途消失能不能用 seed 或系统句消掉？ | **不能；根因是分拍里“对身上衣服的动作”。** 同首帧同提示词 6/6 条（PDD 1、Pika 换 seed / 加服装保持系统句 / 去掉 cropped 各 1–2）都在 3.3–3.9 s 外套消失再“穿回”。只把“she smooths the hem of her blazer”换成不碰衣服的动作：2/2 个 seed 外套全程穿着 | 消失：r1_base_cue/ep01-S3__rca_S3_pika_sheet.jpg、S3_pdd2_sheet.jpg、r4_pika/ep01-S3__rca_S3_seed2_sheet.jpg、S3_outfitcue_sheet.jpg、r7_outfit_text/ep01-S3__rca_S3_nocrop*_sheet.jpg；修好：r8_outfit_action/ep01-S3__rca_S3_noblazeract*_sheet.jpg（高：6/6 vs 0/2，人工看印样）。现剧本 93 镜里 16 镜分拍有“整理 / 拉 / 收紧 / 掀起 衣服”类动作（非亲密 5 镜，正则粗筛，含误报）。“保留动作 + 同句补‘the blazer staying on her shoulders’”无效：2/2 仍消失（r9_outfit_keep/*_sheet.jpg）。合计：带对衣服的动作 8/8 消失，去掉 0/2 → 写作规则草案 K-WRT-702（knowledge/inbox/2026-11-01_video_rca_writer.yaml），lint 号待 ITERAUDIT / SCRIPT-RSI 定。剩余小问题：外套下摆变短（形状漂移），S4 不碰衣服也有，未修 |
| Pika 4 帧一顿多严重、怎么去 | 慢动作镜是真 4 帧一顿（第 3 相位跳 1.24–1.34×）；大动作镜是 2 帧交替。去抖复用 K-LOOP-004，门槛 1.25 → 1.2 才能盖住 S5 | 见 §3（K-REV-705） |
| 单人：正脸 + 侧脸双参考槽能不能去掉看镜头 | **基本不能。** 6 对同 seed：单参考看镜头 3–4/6，双参考 3/6；sface 均值 0.885 → 0.843；双参考 1 张多出半个人头 | data/ab/video_rca/r2_dualref/faces.jpg、faces_S6.jpg、takes.jsonl（中：6 对，人工看）。不建议拿去问项目方 |

## 2 度量

（同 r1：score_clip 生产口径 + 人工看人脸裁切 tools/video_rca/facecrop.py；新增 tools/video_rca/judder.py：J4 + 2 帧相位 J2。）

## 3 Pika 4 帧一顿量化与去抖方案（K-REV-705）

| 片（Pika，同首帧同 seed） | 动作 pace | J4（z） | J2（z） | 相位形态 | 去抖后 J4 | 去抖清晰度代价 |
|---|---|---|---|---|---|---|
| S2 有系统句 | data/ab/video_rca/r1_base_cue 预览 · 0.27 | 1.347（3.91） | 1.091（1.28） | 第 3 相位 1.33× | — | — |
| S4 | data/ab/video_rca/r1_base_cue 预览 · 0.56 | 1.352（7.35） | 1.089（2.71） | 第 3 相位 1.34× | 1.096 | 拉普拉斯 188.0 → 185.3（−1.5%，360p） |
| S5 | data/ab/video_rca/r1_base_cue 预览 · 0.68 | 1.237（10.81） | 1.114（7.71） | 第 3 相位 1.24× | 1.092 | 209.3 → 202.8（−3%，360p） |
| S3（大动作） | data/ab/video_rca/r1_base_cue 预览 · 1.67 | 1.155（0.93） | 1.138（3.28） | 2 帧交替（PDD 同镜同样） | — | — |
| 冒烟 S3（全分辨率） | data/autopilot/pika_smoke/ep01-S3__pika.mp4 · 1.19 | 1.146（1.1） | 1.138（3.52） | 2 帧交替 | 1.035 | 103.8 → 77.8（−25%，全分辨率） |

出处：data/ab/video_rca/r1_base_cue/*_prev.mp4、data/ab/video_rca/r6_dejudder/（judder.py、sharp.py 本机测）。J4 在 360p 预览上测与服务器原片测一致（S2 1.347 vs 1.373，r1_base_cue/results.json）。
方案：沿用 PROD 已接好的链路（tools/series10_video/upscale_preview.py（needs_dejudder） → tools/dejudder.py → _dj → _sr1080），只把 config/pipeline/video_policy.json dejudder.j4_gt 1.25 改 1.2、j4_z_ge 3 不变——慢动作镜（4 帧一顿最显眼的地方）全部去抖、代价 ≤3%；大动作镜的 2 帧交替不触发（快动作上去抖要掉 25% 清晰度，且项目方 / 总调度看冒烟片没觉得顿）。该文件归 AUTOPILOT / PROD，改法已交总调度；tests/test_video_rca.py::test_v05 是 xfail(strict)，改完自动转红提醒。

## 4 独立复核

见 §4b。

## 4a 其它实验结论

| 实验 | 结果 | 结论 |
|---|---|---|
| r5_img_twoshot（本机道，ep01-S5 / ep03-S4 × 3 seed × 旧 / 正向 / 实测句） | 看镜头的脸：旧句 8/10、正向句 0–1/10（1 张存疑）、实测句 0/12（data/ab/video_rca/r5_img_twoshot/faces_01S5.jpg、faces_03S4.jpg；2 张下载失败未计） | 两句同样有效 → framing.two_shot_clause 已改回正向句 TWO_SHOT_POSITIVE（总调度决定 3），K-REN-703 转“确认” |
| r2_dualref（本机道，单人 3 镜 × 2 seed） | 看镜头：单参考 3–4/6、双参考 3/6；sface 均值 0.885 → 0.843；双参考 1 张多出半个人头（data/ab/video_rca/r2_dualref/takes.jsonl、faces.jpg） | 双参考槽没有明显收益，不建议上生产、不拿去问项目方。剧本 18:24 重导入后的单人提示词（带逐人视线句 K-REN-G06）下，现行单参考 ep01-S3 已 2/2 不看镜头 |
| r3_hide_offframe（Pika，复用 r1 原编译稿） | S4 脸高 0.122 → 0.124、S5 0.173 → 0.169、S6 0.133 → 0.141；印样几乎一样（data/ab/video_rca/r3_hide_offframe/） | Pika 不会为画外的鞋拉远 / 下摇（r1 那两条拉远是 PDD）→ K-REN-701 开关保持关 |
| r1 S6 有 / 无视线系统句（Pika） | 两条都是首帧看镜头 → 前 3.6 s 看镜头 → 分拍“给她披外套”起转向男主；两条几乎一样（r1_base_cue/ep01-S6__rca_S6_pika_*_sheet.jpg） | 视频侧视线系统句作用很小（G4 / G5 两例）；看镜头要在首帧修 |

## 4b 独立复核

未做（V1 未测）：r1 已由总调度派 AUDIT 复核；r2 请同一复核方顺带看 data/ab/video_rca/r4_pika、r8_outfit_action、r9_outfit_keep 的印样和 r5_img_twoshot 人脸裁切（我的看图判断需要独立复核）。

## 5 改动（本轮）

| 文件 | 改了什么 | 授权 |
|---|---|---|
| services/agent/ns_agent/framing.py | two_shot_clause：先按证据例外换成实测句（19:2x），r5 A/B 后改回正向句；两句都留成常量 TWO_SHOT_TESTED / TWO_SHOT_POSITIVE，docstring 记 ⤴ 与数字 | CONSENT REFLOCK → VIDEO_RCA（LOCKS） |
| tests/test_script_rsi_eyeline.py | 双人句断言：允许实测句 / 正向句，禁止“朝向镜头 / 看着镜头” | CONSENT SCRIPT_RSI → VIDEO_RCA（总调度决定 3） |
| services/recipes/recipes/_base.yaml | hide_offframe_parts 注释与 provenance：Pika 下无效，保持关 | CONSENT AUTOPILOT → VIDEO_RCA |
| knowledge/rules/render_video_rca.yaml | K-REN-701 证据 ⤴（Pika 无效）；K-REN-703 改回正向句、转确认；新 K-REV-705（Pika 去抖门槛） | 本 loop |
| tests/test_video_rca.py | 新 test_v05（xfail strict：等 PROD 把 j4_gt 改 1.2） | 本 loop（LOCKS 已登） |
| tools/video_rca/{lab.py,img_lab.py,judder.py,dualref_ab.py,facecrop.py} | from_job / hide_size / prompt_replace（只用于 scope=ab 诊断）、本机道模式、2 帧相位量化、双参考 A/B、人脸裁切 | 本 loop |

## 6 回归

- pytest：tests/test_video_rca.py、test_script_rsi_eyeline.py、test_image_framing.py、test_recipes_engine.py 全过（test_v05 为预期 xfail）。
- knowledge compile --check 通过（data/qa/iter_gate/VIDEO_RCA_r2.md K1，436 条）。
- 生产影响：framing.py 最终 = SCRIPT-RSI 原来的正向句（无净变化）；_base.yaml 只改注释 / provenance；没有改生产出片参数。
