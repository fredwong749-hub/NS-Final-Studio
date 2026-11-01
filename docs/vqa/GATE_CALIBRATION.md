# VQAGATE 看图闸门标定（2026-11-01 16:5x，VQAGATE · fredw-2b 派）

口径：项目方 11-01 16:10 原话转拦截（D-VQA-01 / L-080）。只拦 defect（高置信），并且该项要在 config/vqa.json 里 `blocking=true`；unsure 写进证据，不挡。数字都标了出处，没测到的写“未测”。

## 0. 七步（ITERATION_PROTOCOL）
1. 场景：项目方任务 OT9（看一镜生成结果是否合格）。项目方 11-01 16:10 原话：“一旦发现不对，叫系统重写做”；16:3x：“image 做出来后先用本地图像模型检测，再跑视频”。
2. 度量：每项的召回 / 误报见 §1；按项统计的 defect 占比在 data/vqa/gate_scan/rates.json（11 张，eye_contact 8/11、accessory 7/11、posed 6/11、outfit 5/11、hair 4/11、plastic 4/11、continuity 2/11、extra_limbs 2/11）。gaze_mp 的数据在 data/acting/mp_features_v1.json。
3. 改动：config/vqa.json（enforce、gate、blocking）；services/agent/ns_agent/vqa/{contract,continuity,rubric,client}.py；postflight.py 的 _q9_item / _q9_live；auto_current.py 的 passes；producer.py 的 vqa_gate / vqa_delta / auto_review_redo；build_jobs.py 的 _q9_ok；score_clip.py 的 vlm_fails；tools/vqa/gate_scan.py。
4. 独立复核：还没有，等 AUDIT（verifier ≠ VQAGATE）。
5. 回归：tests/test_vqagate.py（17 条）、tests/test_vqa.py、tests/test_gen_contract.py、tests/test_producer.py 全过（data/qa/iter_gate/VQAGATE_g1.md T1）。
6. 证据：data/vqa/gate_scan/latest.json、applied.json；data/producer/log.jsonl 17:01–17:02 的 demoted 记录（first:ep01-S2/S5/S6/S7、ep02-S7/S8、ep03-S3）；16:52 master_approve last:ep03-S7（by VQAGATE）。
7. 规则：K-REV-V08、K-REV-V09、K-REV-V10、K-OPS-V11（knowledge/rules/vqa.yaml）；修订 K-REV-V02、K-REV-V03、K-REN-V05、K-REV-G04。

## 1. 检测项表

| 项 | 判据 | 召回 | 误报 | 阈值 / 口径 | 拦截 |
|---|---|---|---|---|---|
| eye_contact（看镜头） | VLM defect；或 gaze_mp 高置信度命中 | gaze_mp 留出：27/37、25/34（≈0.73）；VLM 单独：未测（没有标好的阴性集） | gaze_mp 留出：0/13、1/16；全集 1/29 | gaze_mp 判据 \|0.3×yaw_n + eye_x\| ≤ 0.05 且 pitch_n ≤ 0.12（数据：data/acting/mp_features_v1.json，总调度标的 100 张）；VLM 自相矛盾的 defect 降为 unsure（contract.sanitize） | 是 |
| continuity_break（跨镜不连贯） | VLM，参考图 = 同场上一镜当前首帧 | ep01 点名正例：S5（发色）命中，S7（发色）命中；S1→S2 外套：总调度看的是成片，首帧 S1 其实穿着外套，不算正例 | 未测（阴性只有 ep01 S2/S3/S4 3 张，都没报） | VLM defect | 是（出处 data/vqa/gate_scan/latest.json、data/vqa/gate_scan/rates.json） |
| hair_mismatch（发色 / 发型） | VLM，对身份参考 | ep01 S5、S7 命中（总调度点名） | ep02-S8 报“参考图4是灰发”，疑似把顾沉参考当成林晚，算疑似误报；n 太小 | VLM defect | 是 |
| framing_mismatch（景别） | VLM | 未测（这批首帧都没报；总调度 G0 点名的 ep05-S3/S5 不在本次看成的样本里） | 未测 | VLM defect | 是（G0 要求） |
| extra_person（多人 / 重复人） | VLM | 未测 | 本次 11 张都没报 | VLM defect | 是（hard，原本就极少误报）（出处 data/vqa/gate_scan/latest.json、data/vqa/gate_scan/rates.json） |
| posed_stiff（摆拍站桩） | VLM | ep01 S4/S5/S6/S7 命中 | ep02-S8、ep03-S4 也报了，11 张里报了 6 张，偏高 | — | 否，只进证据（出处 data/vqa/gate_scan/latest.json、data/vqa/gate_scan/rates.json） |
| outfit / accessory / plastic_doll | VLM | — | 11 张里分别报了 7 / 8 / 5 张；和总调度标签对不上 | — | 否（出处 data/vqa/gate_scan/latest.json、data/vqa/gate_scan/rates.json） |
| extra_limbs / hand_malformed | VLM | 未测（标定集里没有多手正例，VQA STATE） | 2/11 | — | 否（V6 用 VLM 数手转主判据，留到视频段做）（出处 data/vqa/gate_scan/latest.json、data/vqa/gate_scan/rates.json） |
| underage_look | VLM | — | — | HC-07 | 是（任何时候都拦） |

样本说明：gpu36 隧道 16:5x 断开前，有 11 张现行首帧看成（ep01 S1–S7、ep02 S7/S8、ep03 S3/S4），结果在 data/vqa/gate_scan/latest.json。其余首帧记“待重扫”，不写回、也不撤当前。每项的 defect / unsure 占比用 `tools/vqa/gate_scan.py report` 生成，写到 data/vqa/gate_scan/rates.json（等全量扫完再跑）。

## 2. ep01 首帧逐镜（总调度点名 vs 闸门）

| 镜 | 总调度点名（成片） | 闸门结果 | 结论 |
|---|---|---|---|
| S1 | 白衬衫没外套（S1→S2） | 过 | 首帧 S1 其实穿着深色外套，不连贯出在成片 / 视频层（出处 data/vqa/gate_scan/latest.json、data/vqa/gate_scan/rates.json） |
| S2 | 看镜头 | 拦：eye_contact（gaze_mp） | 命中 |
| S3 | 看镜头 | 过 | 漏检：MediaPipe 测得 eye_x −0.27，VLM 判看画面左 |
| S4 | 站位跳变；看镜头（林晚） | 过：VLM 的 defect 证据是“未迎上顾沉视线”，降为拿不准 | 总调度 100 张标签里这张首帧两张脸都标“没看镜头”（data/acting/gaze_labels.json），不算看镜头漏检；问题在视频层 |
| S5 | 看镜头；发色变深 | 拦：hair_mismatch + continuity_break | 命中（发色）；看镜头本身没测出 |
| S6 | 两人直视镜头、摆拍 | 拦：eye_contact（VLM + gaze_mp 两张脸） | 命中 |
| S7 | 发色 | 拦：hair_mismatch + eye_contact + continuity_break | 命中 |

首帧阶段：按镜算，点名的镜里拦住 S2、S5、S6、S7。按“看镜头”一项算，总调度标签里 ep01 当前首帧标看镜头的有 S1、S2、S3、S5、S6、S7 共 6 张，命中 S2、S6、S7 共 3 张，S1、S3、S5 漏检（归因见 §4；S5 另因发色被拦）。出处：data/vqa/gate_scan/applied.json、data/acting/gaze_labels.json。S1 不连贯的根子不在首帧。

## 3. 改阈值
- blocking 名单：config/vqa.json checks.*.blocking，依据写在 gate._blocking_v1（tests/test_vqa.py 会核对每个 blocking 项都写了依据）。
- gaze_mp：config/vqa.json gate.gaze_mp。
- 隧道恢复后：先跑 `tools/vqa/gate_scan.py scan --resume`，再跑 apply 和 report，然后按 rates.json 复核误报，再打开 gate.video_requires_q9。

## 4. 漏检归因（17:4x，断网期间只用本地数据）
- 对照总调度的 100 张标签（data/acting/gaze_labels.json、data/acting/mp_features_v1.json）：
  - **ep01-S4 当前首帧 52a5cc73 两张脸都标“没看镜头”**，所以 S4 不算看镜头漏检。S4 的问题是视频层的站位跳变和多手，归 V6 / 视频段。
  - ep01-S1（4208ace3）、S3（ada503e6）、S5（1848b71b）都标了“看镜头”，但 MediaPipe 测得眼珠和头朝同一个方向偏：eye_x / yaw_n 分别是 0.17、1.1、0.64（出处 data/acting/mp_features_v1.json）。
- 总体分布：100 张里头偏过去的（|yaw_n| > 0.15）正例共 38 张，大多数 eye_x / yaw_n 在 −0.2 到 −0.45 之间（眼珠转回来对着镜头）；但有 5 张是正比值，和反例（24 张，多数在 0.1 到 0.6 之间）混在一起（出处 data/acting/mp_features_v1.json）。所以这几张靠虹膜几何分不开，再调 MediaPipe 阈值只会拉高误报。实测：把 bs_x、头偏角上限加进网格做奇偶两折留出，最好的结果是 29/37、误报 1/13，另一折 25/34、误报 1/16，比现行好不了多少（出处 data/acting/mp_features_v1.json）。现行阈值不改。
- 改 rubric 写法：vqa_inspect.md 的 eye_contact 补一句“脸侧转、但眼珠转回来正对观众的也算看镜头（只看瞳孔朝向）”，并要求 people[].gaze 和这一项一致。效果未测，等网络恢复后用 `tools/vqa/gate_scan.py calib_gaze` 在这 100 张上做留出验证（看图模型、降级后、合并三种口径各报召回 / 误报，写 data/vqa/gate_calib/gaze_vlm.json）。

## 5. 垂眼排除（18:4x，总调度亲审 MediaPipe 单独命中的 4 张：ep01-S2、ep03-S7、ep04-S1 判对；ep04-S2 误报，林晚垂眼看碗）
- 修法：MediaPipe 分支加排除条件，eyeLookDown（bs_y）> 0.35 或 eyeBlink > 0.6 时不算看镜头（config/vqa.json gate.gaze_mp.down_max / blink_max）。
- 100 张标签留出：奇偶两折分别是召回 25/34、误报 0/16，召回 27/37、误报 0/13；排除前是 25/34、1/16 和 27/37、0/13。召回不变，唯一的误报（ep04-S1 第 2 张脸，bs_y 0.617）被排除（出处 data/acting/mp_features_v1.json）。正例 bs_y 最大 0.19，阈值取 0.35，在两者之间。
- 样本外：ep04-S2 当前首帧 bs_y 0.598，排除后不再拦（出处 data/vqa/gate_scan/preview.md）。
- blink_max 未标定：标签特征里没有 blink，只用来排除明显闭眼。gaze_mp 输出已加 blink 字段，下次标定可以用。
- 旧判定里 MediaPipe 记的 eye_contact 用 contract.refresh_gaze 按新阈值重算，preview 和 apply 都走这一步。

## 6. 俯仰上限 P 0.12 → 0.2（19:0x，总调度转 LOCALGPU：A 组 ep01-S1 s20261201 肉眼在看镜头，分数 0.03 在带内，但 pitch 0.129 超了 P 被漏）
- 在 100 张标签上加垂眼排除后扫 P = 0.12–0.25：两折留出召回 25/34、27/37，误报 0/16、0/13，全都不变（出处 data/acting/mp_features_v1.json）。原因是标签里落在视线带内的正例 pitch 都 ≤ 0.12；pitch 高的那个反例本来就被垂眼条件排除了。
- 样本外 data/ab/identity_gaze_ab/：A_s20261201（pitch 0.129）改后命中；A_s20261301、ep01-S2 A（pitch 0.111 / 0.104，分数 0.014 / 0.01）照旧命中；两张 B 图视线离轴（分数 0.375 / 0.495 / −0.373），不命中。
- 局限：标签集里 pitch 0.12–0.2 之间没有带内反例，误报不升只说明“没有反证”，不代表测过。新首帧过闸门后，按总调度抽查继续看。
