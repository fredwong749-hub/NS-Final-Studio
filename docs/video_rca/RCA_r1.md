# VIDEO-RCA 第 1 轮：视频问题逐类根因（W11，总调度 fredw-2b 派，2026-11-01）

> 项目方原话（11-01 晚）：“现在视频那边很多问题,我不知道怎么修复好,也不知道是提示词还是什么,你deep research这些问题,然后rsi下去直到修复好”；18:2x：“所有图片不要看镜头，不要看镜头！”
> 以前的评价：“完全是废品”；“Pika 画面比 H3 自然，但脸部突然泛红/大红点”；“男生的声音有点生硬”；ep01_v2：“问题很多……不连贯,眼睛也对着镜头”；“s5等视频出来很糊……估计你的参数坏了”。
> 18:0x 项目方新决定（总调度转）：视频全部用 Pika Flex，不回退 H3 / PDD。所以本文的修复全部以 i2va_pika_flex 为准；PDD 的结论只作历史归因。
> 服务的项目方任务：OT9。G0 扫描关键词：看镜头 / gaze / eyeline / 景别 / two_shot / FACING / split_step / outfit / flush；命中 docs/acting/PERFORMANCE_RULES.md、knowledge/rules/acting.yaml（K-REN-G01/G02）、docs/rsi/DEFECT_HUNT.md、knowledge/RSI_LEDGER.md §A–C/V10/DH、services/recipes、ns_agent/framing.py、docs/research/h3_deep、docs/ep02_iter/*。没有新造检测器：发生率全部来自生产 score_clip 打分和总调度的人工视线标签。

## 0. 口径

- 发生率：`tools/video_rca/rates.py` → `data/ab/video_rca/rates_baseline.json`。“现行版”= 每镜当前选中的那一版（state_gpu33/36.json 的 chosen），59 条；“全部尝试”142 条，其中 138 条是 i2va_pdd2（ep01_v2 时期的基底）。看镜头用总调度人工标签 `data/acting/gaze_labels.json`。
- 层：①剧本 / 分拍文字 ②H3 提示词编译 ③首帧 ④模型基底 ⑤采样参数 ⑥后期。
- 置信度：高 = 控制变量实验或代码级证据；中 = 统计相关 + 外部资料；低 = 单例或推断。
- 外部研究（原文引用 + 链接）：`docs/video_rca/research_r1.md`，下文写作 R-Qn-m（该文 Qn 节第 m 条）。
- 实验：`tools/video_rca/lab.py`（与生产同一个 compile_shot、同一张首帧、同 seed，只改一个因素）+ `srv_run.py`（gpu36 本机执行，只用 gpu36:2，提交前查队列为空、longshot=normal）。结果目录 `data/ab/video_rca/<实验>/`，服务器 `/root/work/fredw/video_rca/<实验>/`。
- 审片页：`data/review_pages/video_rca/index.html`（`tools/video_rca/page.py` 生成，组定义 `tools/video_rca/groups.json`）。


## 1. 问题类目表（发生率 = 现行版 / 全部尝试；出处 rates_baseline.json，除注明外）

| # | 类目 | 发生率 | 根因层（主 → 次） | 证据（置信度） | 修复 / 交出 | 修前 → 修后 | 状态 |
|---|---|---|---|---|---|---|---|
| C1 | 看镜头（片头 / 全程） | 片头看镜头 56/72、首帧看镜头 71/100（data/ab/video_rca/rates_baseline.json）| ③首帧（主）→ ②编译（次） | 首帧看镜头 → 片头看镜头 49/54（91%）；首帧没看 → 片头看镜头 4/10（40%）；不给首帧的 Ref2VA 3/10（高，交叉表 rates.py）。出图系统句 framing.two_shot_clause 写“各自至少四分之三侧脸朝向镜头（toward the camera）”（代码，高）；重试锚点句 127/538 条编译稿带 facing the camera（代码，高）。单人：图1 正脸直视的脸部参考被 Qwen 连视线一起抄（R-Q1-5/6，中） | ① 编译器锚点句改译、lint RL-E3（K-REN-702，已改）；② 双人出图系统句改“互相看着对方、眼睛不看镜头”（K-REN-703，改法交 REFLOCK）；③ 单人出图加“图1 只取身份、不取头部角度和视线 + 四分之三侧脸”句（交 REFLOCK，待加 3/4 侧脸参考）；④ Q9 看图闸门拦（VQAGATE） | 双人首帧 A/B：旧句 4 张脸里 3 张看镜头 → 新句 0/4（G6）；单人：旧句 / 只加“不看镜头”句 / 只加角色句共 6 张，至少 5 张看镜头 → 角色 + 侧脸句 2/4 看镜头（G7、r4_img_single）；Pika 视频：首帧不看镜头时（S4_ffnew）见 §3 | 双人已证；单人部分 |
| C2 | 开场定格 / 首秒停顿 | head_s>0.5：0/59、0/142；人工“开头定格+看镜头”10/72（data/ab/video_rca/rates_baseline.json）| ③首帧（定格多与看镜头同现）→ ②编译 | 像素运动量看不出“人在动但在看镜头”（DEFECT_HUNT DH1）；10 条定格全部同时看镜头 | open_motion_cue 已在（K-REN-G02）；与 C1 同修 | Pika r1 7 条 head_s 全为 0 | 随 C1 |
| C3 | 摆拍 / 站桩 | 动作不足 1/59、5/142（data/ab/video_rca/rates_baseline.json）| ③首帧（主）→ ①分拍 | ep01-S5 首帧本身是正面对称站姿（造型设定图式），Pika 照样只做微动（S5_pika 抽帧）；出图参考 = 正脸大头照 + 正面全身设定图（去头）→ 出成目录照姿势（推断，中） | 同 C1 的单人出图修法（不取参考图姿势）；写作侧“开头即在动作中”已有 K-WRT-A* | — | 交出图链路 |
| C4 | 第二人没表情 | VLM 项，未测（DH-V17 交 VQA） | ①分拍文字 | S4 原稿 Pika：分拍写了两人各自视线（his eyes lifting to hers），女主从看镜头转为看男主（faces_vid.jpg）——写了就演；没写就呆（R-Q6-1 低-中） | 写作规则已有 RL-E1 / QW-W9；本轮不新增 | — | 已有规则 |
| C5 | 跨镜不连贯（服装、发色） | 镜内发色漂移 6/53、18/132（data/ab/video_rca/rates_baseline.json）；跨镜未测 | ③首帧（主） | S5 首帧头发是深藏青、外套黑色；同镜 r4 出图 A/B 外套是米色——同一造型不同 seed 出不同颜色（r4_img_single/sheet.jpg，中）；出图提示词“比参考图略深，带一点灰”把发色压暗（推断） | 交 REFLOCK / VQAGATE（跨镜连贯项） | — | 交出 |
| C6 | 服装中途消失又穿回（Pika） | 冒烟 1/1（data/autopilot/pika_smoke/ep01-S3__pika.mp4）；本实验 1/1（data/ab/video_rca/r1_base_cue/ep01-S3__rca_S3_pika_sheet.jpg）| ④基底 + ①分拍（站起 + 整理外套）| S3_pika 第 63–110 帧外套消失、第 94–126 帧“穿回”（S3_pika_sheet.jpg，高：复现）；V6 把它判成多手 | 服装保持系统句 outfit_cue（VRCA-E5）/ 换 seed 对照，见 §3 | — | 实验中 |
| C7 | 身份漂移 | p10<0.5：24/51、72/129（data/ab/video_rca/rates_baseline.json）| ④基底 + ③首帧 | Pika 同首帧同 seed 中位 0.54–0.92，与 PDD 相当（data/ab/video_rca/r1_base_cue/results.json） | 不在本轮 | — | 观察 |
| C8 | 多手 / 多肢 | 12/59、41/142；坏手指 33/59（data/ab/video_rca/rates_baseline.json）| ⑥检测器误报（主）+ ④基底 | 中全景单人 8/8 命中、特写单人 9/26（score 分组）；S3_pika 的“多手”实为外套形变（C6）；S4_pika 4 只手 / 2 人 = 正常 | 交 VQAGATE（VLM 复核）；C6 修好后复测 | — | 交出 + 随 C6 |
| C9 | 4 帧一顿（J4） | 11/59、35/142（data/ab/video_rca/rates_baseline.json，PDD）| ④基底（少步蒸馏） | Pika r1：S2/S4/S5 J4 1.23–1.40、z 4.5–10.8 → 按口径全部命中；PDD 同镜 z 0.35–1.35（高，同首帧同 seed） | 后期去抖 post.dejudder（K-LOOP-004，_base 默认开，J4 1.34–1.52 → 1.08）；交 PROD 确认 Pika 片走去抖 | 待 PROD 去抖后复测 | 交出 |
| C10 | 脚重影 | 未测（历史 knowledge/RSI_LEDGER.md A1）| ④基底 | 历史结论 | — | — | 未测 |
| C11 | 结尾定住 | 1/59、2/142（data/ab/video_rca/rates_baseline.json）| ⑥后期已剪 | trim_frozen 默认开 | 已有 | Pika r1 tail_s 全 ≤0.12 | 达标 |
| C12 | 画面软 / 糊 | 未测（原无清晰度口径）→ 新增 tools/video_rca/sharp.py | ⑥代理（主，PROD W4）+ ⑤采样（次） | 同首帧同 seed：S5 中段 / 首帧拉普拉斯比 PDD 0.658 → Pika 0.784（lap 125 → 154）；S3 0.541 → 0.469（大动作镜，两者都降）；PDD 第二段从 σ≈0.923 起步、等效全尺寸只走 4 步（graph.py split_step=4；R-Q3-1 中） | 基底已改 Pika（项目方决定）；PDD split 实验因决定撤销；代理 / 放大归 PROD | S5 0.658 → 0.784 | 模型层改善；后期交 PROD |
| C13 | 脸部泛红 | cheek_red>0.25：0/59、2/142（data/ab/video_rca/rates_baseline.json）| ②提示词脸红词（主，C2 已证）→ ④Pika 放大 | Pika r1 5 条 cheek_red 0.043–0.095（全过），ep01 提示词无脸红词；series10 现行 80 镜编译稿里只有 ep05-S4（亲密镜，未实验）有 “redden”，且 flush_risk 词表没有 redden（不会触发拦截） | 词表补 redden / reddening（交 WORKFLOW）；无脸红词的镜头 Pika 不用回退 | Pika 0/5 泛红 | Pika 可覆盖非脸红镜 |
| C14 | 节奏慢 | 剪辑层（knowledge/RSI_LEDGER.md A-V2a）| ⑥剪辑 | — | 不在本 loop | — | 不在本层 |
| C15 | 口型 | V7 不过 2/40、26/91（data/ab/video_rca/rates_baseline.json）| ④基底 | S4_pika V7 0.185 不过（PDD 同镜现行版 0.586 过）；S5_pika 0.674 过（PDD 0.484） | 观察，第 2 轮多 seed | — | 观察 |
| C16 | 景别退档 | 差 ≥1 档 29/55（rates_baseline.json）；比要求远 21/55（data/ab/video_rca/ff_size.json）| ③首帧（主）→ ②编译 | 远 21 条里 17 条首帧本就远（ff_size.py，高）；视频比首帧再远 ≥1 档 11/55；描述句带画外鞋 / 高跟 / 腿 62/111 退档 vs 不带 0/7（size_vs_prompt.py，中）；S4 两个 seed 都为画出高跟拉远 / 下摇（高，单镜） | 编译器按景别删画外造型分句（K-REN-701，开关默认关，VRCA-E3 待测）；首帧景别交 REFLOCK | Pika 同镜：S5 近景保住（PDD 退到中景） | 实验待跑 |

## 2 度量

- 正确性：生产打分口径不变（tools/series10_video/score_clip.py，同 VIDEO10 闸门）；新增清晰度 tools/video_rca/sharp.py（只记录，不进闸门）。看镜头 = 总调度人工标签 + 我亲自看人脸裁切（tools/video_rca/facecrop.py，YuNet 同 score_clip）。像素视线检测器（ns_qc.gaze）只作旁证：r1 里 S5_pika 全程看镜头，它报“视线离轴”（data/ab/video_rca/r1_base_cue/faces_vid.jpg 对照 results.json），召回不够，不用它下结论。
- 发生率：data/ab/video_rca/rates_baseline.json（rates.py）；首帧 vs 视频景别 data/ab/video_rca/ff_size.json；景别 × 画外下半身词 tools/video_rca/size_vs_prompt.py 输出。
- 未测：跨镜服装 / 发色连贯（VQAGATE 在做）、第二人表情（VLM 项）、脚重影、Pika 多 seed 稳定性（每组只 1–2 seed）。

## 3 改动

| 文件 | 改了什么 | 规则 |
|---|---|---|
| services/recipes/ns_recipes/prompt.py | FACING_EN“镜头”→ “with the body turned toward the front of the frame and the gaze angled off to one side”（原 facing the camera）；新 hide_offframe_parts()；系统句键加 outfit_cue（默认无值 = 不插） | K-REN-702、K-REN-701 |
| services/recipes/ns_recipes/lint.py | RL-E3（error）：锚点句 / 系统句含 facing / toward the camera | K-REN-702 |
| services/recipes/recipes/_base.yaml | prompt.hide_offframe_parts: false + provenance（待验 VRCA-E3） | K-REN-701 |
| knowledge/rules/render_video_rca.yaml | 4 条规则 | K-REN-701/702/703、K-REV-704 |
| knowledge/inbox/2026-11-01_video_rca_writer.yaml | 写作草案 K-WRT-701（单镜证据，未收编） | — |
| tests/test_video_rca.py | 6 项（K-REN-703 的检查：SCRIPT-RSI 改了 framing.py 后已去掉 xfail，现 6 passed） | 全部 |
| tools/video_rca/** | 实验台、口径脚本、审片页 | — |

LOCKS 已登记（docs/uimaster/LOCKS.md 两行）。services/recipes 属 AUTOPILOT（不在岗），iter_gate O1 判越界 → 见“需要决定”第 1 条。没有改 framing.py；SCRIPT-RSI 已按 K-REN-703 改（D-SCR-07），但措辞和本轮实测的不同（见需要决定 3）。

## 4 独立复核

未做（V1 未测）：需要总调度指派复核方（建议 ITERAUDIT 用 tools/qa/graph_schema_check.py 复核编译稿 + 重跑 tests/test_video_rca.py）。

## 5 回归

- pytest：tests/test_video_rca.py 5 passed + 1 xfailed；tests/test_recipes_engine.py、test_recipe_plan_api.py、test_recipe_pika_default.py、test_h3_prompt.py、test_prompt_timeline_v2.py、test_acting_system.py 共 72 + 30 passed（11-01 本轮跑）。
- knowledge compile --check 通过（data/qa/iter_gate/VIDEO_RCA_r1.md K1）；data_parity 通过（同文件 D1）。
- 编译稿影响面：FACING_EN 只影响 attempt ≥2 的重试稿（series10 现有 538 条编译稿里 127 条，data/pipeline/runs/series10_v1/video/prompts/）；hide_offframe_parts 默认关，不影响生产。vidgen 的作废判断只看首帧（check_stale），提示词改动不会让已出片作废。

## 6 实验清单（gpu36:2，client videorca-；同首帧 / 同 seed / 同编译器，一次一个因素）

| 实验 | 臂 | 因素 | 状态 | 结论 |
|---|---|---|---|---|
| r1_base_cue（data/ab/video_rca/r1_base_cue/results.json）| S3/S5/S4 × {pdd2, pika}；S2/S6 Pika × {有, 无}系统句 | 基底；视线系统句 | S3/S5 两基底、S4_pika、S2 两臂完成；S4_pdd2 撤（项目方定 Pika）；S6 两臂排队中 | 见 C9/C12/C15/C16；G4：首帧看镜头时系统句压不住 |
| r1_img_gaze（data/ab/video_rca/r1_img_gaze/faces.jpg）| ep01-S4、S3 × 旧 / 新系统句 × 2 seed（出图） | 出图视线系统句 | 完成 | 双人 3/4 → 0/4 看镜头；单人加句 2/2 仍看 |
| r4_img_single（data/ab/video_rca/r4_img_single/faces.jpg）| S3 × {角色句, 角色 + 侧脸句}、S5 × {旧, 角色 + 侧脸句} × 2 seed（出图） | 图1 角色句 / 四分之三侧脸句 | 完成 | 角色 + 侧脸 2/4 不看；只角色 0/2 |
| r4_pika（data/ab/video_rca/r4_pika.json）| S4 × 新首帧 A / B；S3 × 换 seed / outfit_cue | Pika：首帧不看镜头时会不会转头；外套形变 | 18:35 起跳板断网，服务器在跑，结果下一轮取 | 待取 |
| r2_pdd_split（data/ab/video_rca/r2_pdd_split.json）| PDD 第二段起点 | — | 撤销（项目方 18:0x 决定全部 Pika） | — |
| r3_hide_offframe（data/ab/video_rca/r3_hide_offframe.json）| S5/S6/S4 Pika × 删画外造型分句 | K-REN-701 | 已编好，网络恢复后提交 | 待跑 |

## 7 规则

K-REN-701（待验）、K-REN-702（确认）、K-REN-703（待验，改法交 REFLOCK）、K-REV-704（确认），检查都在 tests/test_video_rca.py；写作草案 K-WRT-701 在 knowledge/inbox/。
