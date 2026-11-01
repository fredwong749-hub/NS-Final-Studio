# VIDEO-RCA 第 3 轮（总调度 fredw-2b 11-01 22:05 派；基底 Pika Flex；全部 scope=ab）

> 服务 OT9。空档用 gpu36:2 + gpu33:0/1/3（gpu36:0/1 被其他用户占显存，Pika 报 VRAM grow failed，未用；gpu33:2 坏卡不用）。服务器本机提交、每道一次只挂 1 个，生产有 ready 变体时非长镜头道自动退让（tools/video_rca/srv_run.py prod_ready）。
> 剧本 18:24 重导入后镜号变了（旧 S4 = 新 S5 …），所有实验复用 r1 原编译稿（lab.py from_job），V6 / V7 用实验自带的旧镜头信息重跑（srv_run.py v67_meta），不再读生产 jobs.json。**r3_hide / r7 / r8 / r9 当时的 V6 / V7 读的是新镜号的 jobs.json，那几条的 V6 / V7 数字作废**（看图结论不受影响）。

## 1 项目方任务 / 本轮问题

### 1.1 Pika 口型 V7（每组 3 seed）

| 组（同首帧、复用 r1 原编译稿）（data/ab/video_rca/r10a_lip/results.json 等（见表下出处））| 说话人 | V7 corr（3 seed） | 过 | 嘴部开合中位 | 张嘴帧占比 |
|---|---|---|---|---|---|
| S5 原稿（近景）（data/ab/video_rca/r10a_lip/results.json 等（见表下出处））| 林晚 | 0.674 / 0.724 / 0.659 | 3/3 | 0.016–0.020 | 0.15–0.18 |
| S4 原稿（中景双人）（data/ab/video_rca/r10a_lip/results.json 等（见表下出处））| 顾沉 | 0.185 / 0.322 / 0.218 | 1/3 | 0.006–0.007 | 0 |
| S4 新首帧 B（两人互看）（data/ab/video_rca/r10a_lip/results.json 等（见表下出处））| 顾沉 | 0.160 / 0.633 / 0.376 | 2/3 | 0.006–0.007 | 0 |
| S6 无视线系统句（data/ab/video_rca/r10a_lip/results.json 等（见表下出处））| 顾沉 | 0.214 / 0.205 / 0.036 | 0/3 | 0.008 | 0 |
| S6 有视线系统句（data/ab/video_rca/r10a_lip/results.json 等（见表下出处））| 顾沉 | 0.374 / 0.383 / 0.127 | 2/3 | 0.008–0.011 | 0 |
| S4 + VOICE 短语 restrained → calm（data/ab/video_rca/r10a_lip/results.json 等（见表下出处））| 顾沉 | 0.249 / 0.176 / 0.279 | 0/3 | 0.006–0.007 | 0 |
| S4 + 台词后补 “his mouth opening clearly on each syllable”（data/ab/video_rca/r10a_lip/results.json 等（见表下出处））| 顾沉 | 0.707 / −0.032 / 0.123 | 1/3 | 0.006–0.007 | 0 |
| S4 台词前一拍 “低头看鞋尖” → “看着她的脸”（data/ab/video_rca/r15_headup_*） | 顾沉 | 0.258 / 0.555 / 0.429 | 2/3 | 0.008–0.010 | 0 |

出处：data/ab/video_rca/{r1_base_cue,r4_pika,r10a_lip,r10b_lip,r10c_shape,r14a_voiceword,r14b_lipcue}/results.json（v7 字段）。
结论（中）：
- 不过的全是男主顾沉说话的镜：嘴部开合中位只有林晚的 1/3（0.006–0.011 vs 0.016–0.020），张嘴帧占比 0；corr 在 −0.03–0.71 之间随 seed 乱跳 → 嘴几乎不动，相关全靠噪声。人工看 S4 第 100–118 帧（台词在 4.0 s）：顾沉头低垂看向下方，嘴型几乎看不出（data/ab/video_rca/r14b_lipcue/mouth_14.jpg）。
- 台词那一拍说话人不低头（“看着她的脸”）：2/3 过，corr 均值 0.41（原稿 0.24），开合中位升到 0.008–0.010——方向对、幅度小（中-低，3 seed；data/ab/video_rca/r15_headup_1–3/results.json）。
- 改 VOICE 短语（restrained → calm）0/3 无效（data/ab/video_rca/r14a_voiceword/results.json）；补系统口型句 1/3，不稳定，不建议上编译器。
- 检测器口径也有问题（交 VQAGATE / VIDEO10；tools/series10_video/v7_lipsync.py audio_env）：v7_lipsync 的声音包络是整条音轨 RMS（含 Pika 自己生成的脚步声、键盘声、配乐），2–5 个字的短台词只占 0.1–0.3 的帧，corr 被噪声主导；应只在台词时段（分拍时间码 ± 0.5 s）内算。
- 成片还要注意：如果合成用 TTS 替换 H3 原声，口型对的是 H3 原声，不是 TTS（未核实，交 VOICE10 / PROD）。

### 1.2 外套形变（AUDIT 对 r2 的限定，已复核）

- r8（去掉整理外套的动作）逐帧看 2.4–4.0 s（data/ab/video_rca/r8_outfit_action/*_kf.jpg）：**AUDIT 说得对**——外套没有整件消失，但站起来后两只袖子变成米白衬衫袖，外套变成无袖短马甲（2/2 seed）。r1 原稿（带整理动作）是整件消失再以无袖马甲穿回（r1_base_cue/ep01-S3__rca_S3_pika_kf.jpg）。
- 所以有两个根因（data/ab/video_rca/r8_outfit_action/、r9_outfit_keep/、r7_outfit_text/）：① “对身上衣服的动作”→ 整件脱下再穿回（8/8 vs 0/2，K-WRT-702 草案保留，但限定为“整件消失”）；② 大幅姿态变化（坐 → 站）时深色西装外套向“无袖 / 短款马甲”漂移，与有无整理动作、有无 cropped 字样都无关（S3 r7 / r8 / r9 全部出现）。
- S4（站着不动、不碰衣服）3+2 条：cropped 字样删 / 不删，外套长度和袖子在 0 / 60 / 100 / 140 / 190 帧基本一致，看不出系统性变短（data/ab/video_rca/r10c_shape/torso_compare.jpg）→ 小动作镜没有明显漂移，r2 说的“S4 也变短”撤回为“未证实”。
- ②的对策（未测，需要出图层配合）：大幅姿态变化的镜用首尾帧（fl2va：尾帧画出站立且外套完整的状态），或把“坐 → 站”与“站着说话”拆成两镜。要做需要一张定稿尾帧（交出图链路 / 总调度排）。

### 1.3 去抖门槛 1.2 下的清晰度代价（全分辨率，gpu36 实测）

| 片（gpu36 /root/work/fredw/video_rca/r12_dejudder/log2.txt）| 动作 pace | 相位形态 | J4（z）前 → 后 | 拉普拉斯中段 前 → 后 | 代价 |
|---|---|---|---|---|---|
| S6 有系统句（大动作）（gpu36 /root/work/fredw/video_rca/r12_dejudder/log2.txt）| 2.03 | 4 帧型（第 3 相位 1.45×） | 1.465（9.6）→ 1.042 | 120.0 → 117.7 | −1.9% |
| S4（慢）（gpu36 /root/work/fredw/video_rca/r12_dejudder/log2.txt）| 0.56 | 4 帧型 | 1.403（8.6）→ 1.058 | 146.2 → 144.0 | −1.5% |
| S5（慢）（gpu36 /root/work/fredw/video_rca/r12_dejudder/log2.txt）| 0.69 | 4 帧型 | 1.234（10.8）→ 1.062 | 154.2 → 148.5 | −3.7% |
| S3（大动作）（gpu36 /root/work/fredw/video_rca/r12_dejudder/log2.txt）| 1.67 | 2 帧交替 | 1.161（1.0）→ 1.056 | 99.6 → 74.1 | −25.6% |

出处：gpu36 /root/work/fredw/video_rca/r12_dejudder/log2.txt（judder.py + sharp.py）。
结论（高；/root/work/fredw/video_rca/r12_dejudder/log2.txt）：代价取决于**顿挫类型**，不取决于动作幅度——4 帧型（一个相位跳）去抖代价 ≤4%（大动作镜也一样）；2 帧交替型去抖要掉 25%。现行门槛 J4 > 1.2 且 z ≥ 3 正好把 2 帧交替型（z≈1）排除在外 → **不需要按动作幅度分档**，维持 1.2 / z 3。

### 1.4 双人镜第二人反应（R11-9）

- 5 条 Pika 双人片（S4 原稿 / 删画外、S6 有 / 无系统句 / 删画外），第 60 / 110 / 160 帧人工看非说话人（林晚）：5/5 视线落在对方身上；表情是轻微变化（唇微张、眉轻收），没有“空白 / 看镜头”（data/ab/video_rca/r13_react/react_1–5.jpg）。首帧本身看镜头的片，前 2–3 s 仍看镜头，直到分拍写到“看对方”才转开（与 r2 Q① 一致）。
- 结论（中，5 条；data/ab/video_rca/r13_react/）：Pika 下第二人“有眼神”基本达标，“表情幅度”偏弱；表情强度没有像素口径，未量化。

## 2 能变成规则的结论

| 结论 | 规则 | 状态 |
|---|---|---|
| 去抖门槛 1.2 / z≥3，不按动作分档；2 帧交替型不去抖（docs/video_rca/RCA_r3.md §1）| K-REV-705（补全分辨率证据） | 确认（WORKFLOW 已改门槛，test_v05 已转正） |
| 对衣服的动作 → 整件消失再穿回（docs/video_rca/RCA_r3.md §1）| K-WRT-702 草案（限定：只管“整件消失”；不管大动作下的无袖漂移） | 草案，等 QW lint 号 |
| 大幅姿态变化 → 外套向无袖 / 短款漂移 | 暂不成规则：根因已定位，修法（尾帧 / 拆镜）未测 | 待验 |
| 男主说话嘴几乎不动；V7 用整轨 RMS 不可靠（docs/video_rca/RCA_r3.md §1）| 交 VQAGATE / VIDEO10（V7 只算台词时段）；写作侧草案 K-WRT-703“台词那一拍说话人脸朝对方、别低头”（r15：1/3 → 2/3，corr 0.24 → 0.41） | 草案 |
| 双人第二人眼神 Pika 下 5/5 有（docs/video_rca/RCA_r3.md §1）| 不新增（RL-E1 / QW-W9 已有） | — |


## 2 度量

同 r1 / r2：生产 score_clip 口径（V6 / V7 用实验自带旧镜头信息重跑，srv_run.py v67_meta）、tools/video_rca/judder.py、sharp.py、facecrop.py 人工看脸；本轮新增 gpu33 三道（同 ComfyUI 版本、同模型文件）。未测：表情强度（没有像素口径）、TTS 替换后的口型（交 VOICE10 / PROD 核实）。

## 3 改动

- services/agent/ns_agent/framing.py：two_shot_clause 切回 TWO_SHOT_TESTED（总调度 22:5x，生产反例 ep01-S5 v5；CONSENT REFLOCK → VIDEO_RCA 已在 LOCKS）。
- knowledge/rules/render_video_rca.yaml：K-REN-703 ⤴（生产反例）、K-REV-705 补全分辨率证据。
- knowledge/inbox/2026-11-01_video_rca_writer.yaml：新写作草案 K-WRT-703（台词那拍别低头）。K-WRT-702 已被 SCRIPT-RSI 收编进 knowledge/rules/writer_iteration.yaml（QW-W11）；AUDIT 的限定（只管“整件消失”，坐→站的无袖漂移是另一根因）需要写进那条，文件归 ITERAUDIT，改法交总调度。
- tools/video_rca/srv_run.py（多道 VRCA_PORT / VRCA_OUT / VRCA_FF、生产 ready 时非长镜头道退让、v67_meta 重跑 V6 / V7）、lab.py（--host gpu33、--lane、from_job 可换首帧）。

## 4 独立复核

未做（V1）：r3 的看图判断（外套无袖、口型、反应）请 AUDIT 复核 data/ab/video_rca/r8_outfit_action/*_kf.jpg、r10c_shape/torso_compare.jpg、r14b_lipcue/mouth_14.jpg、r13_react/react_*.jpg。

## 5 回归

- pytest：tests/test_video_rca.py、tests/test_script_rsi_eyeline.py 11 passed（data/qa/iter_gate/VIDEO_RCA_r3.md T1）。
- knowledge compile --check 通过（data/qa/iter_gate/VIDEO_RCA_r3.md K1）。
- 生产：只改 framing.two_shot_clause 一句（总调度指令），其余都是 scope=ab；gpu33 三道在 00:1x 总调度收回后不再提交（最后一批 r15 已跑完）。
