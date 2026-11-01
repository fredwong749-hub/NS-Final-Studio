# 内容缺陷猎捕（DEFECT_HUNT）· 活清单

> 项目方 R11-11（docs/REQUIREMENTS.md）：“以上很多基础的bugs,rsi agent应该可以发现的,我暂时打个样给了你,然后类似的问题,你生成一堆问题,然后一点点去debugs和check,然后端更新规则到本地代码系统去”。
> 样例 R11-2…R11-10：演员看镜头、开场盯镜头停 1 秒、节奏慢、第二人没表情 / 眼神、鞋不一致、多一只手、像素低、有字幕。
> 具体样例由 ACTING（表演 / 眼神规则）和 VQA（本地 VLM 评分）处理；本文是**通用机制**：类目 → 检测 → 命中 → 规则 + 检查 → 分派 → 常驻 loop。
> 工具：`tools/qa/defect_hunt.py`（断点续跑，状态 `data/qa/defect_hunt/state.json`，看图类队列 `data/qa/defect_hunt/vlm_queue.json`）。规则：K-OPS-Q13、K-REV-Q01、K-REV-Q02、K-WRT-Q06（`knowledge/rules/review_defect_hunt.yaml`、`knowledge/rules/writer_iteration.yaml`）。

## 1. 根因：为什么十个 RSI loop 一个都没抓到

总调度的假设成立，补几点更具体的证据：

1. **loop 量的是界面和基础设施。** UIMASTER / UIRSI / UIPIXEL / UIAUDIT 全是界面（`docs/ITERATION_PROTOCOL.md` §0.1）；INFRA、BAKEOFF 量速度和模型对比。`knowledge/RSI_LEDGER.md` 的 UI / I / IMG / V10 各节，结论都落在排版、接口、GPU 利用、契约阈值上，没有一行是“看片找内容缺陷”。
2. **画面质量只靠契约里几个窄项，而契约对这批缺陷是盲的。** GEN_CONTRACT 首帧 Q1–Q7 = 身份 / 造型 / 景别 / 质感 / 手肢 / 文字 / 场景，没有“视线 / 看镜头 / 第二人表情 / 跨镜鞋连续”；视频 `tools/series10_video/score_clip.py` 量动作量、J4、泛红、硬切、身份、景别、V6 手肢、V7 口型，同样没有视线和表演。首轮实测：现行 62 镜首帧 **Q1–Q7 全部通过、0 处不通过**（DH-F01–F07 = 0），总调度也逐张签了 master_review——但项目方一眼看出看镜头、多手、鞋不对。契约全过 ≠ 片子没问题。
3. **能看图的审片环节在 series10 上没跑过。** `tools/autopilot/director.py`（本地 VLM / 网关审片 + 7 维打分）只在 `data/autopilot/ep02_autopilot_dry`、`ep03_autopilot_dry`、`p0_dry` 三个 dry-run 里出现；series10 的出片驱动 `tools/series10_video/night.py` 不调用它。`knowledge/RSI_LEDGER.md` D8“分拍写视线 / 表情 / 反应能改善眼神戏”至今是 ⏳“还没出片验证”。
4. **闸门阈值放过了已经测到的缺陷。** V6 记到了多出来的手，但阈值是 extra_hand_frac ≥ 0.05 才不过：首轮 21 条视频“手最多 3 只 / 1 人”，V6 仍判通过（`data/pipeline/runs/series10_v1/video/scores/ep01-S2__mot.json`）。
5. **没有人被指派“找内容缺陷”。** 每个 loop 的停止条件都是“自己的分数 / 契约过了”（`docs/ITERATION_PROTOCOL.md` §0.2 H2、H10），没有一个 loop 的输入是“成片 + 剧本”、输出是“缺陷清单”。

补充结论：R11-8“开场盯镜头”**不是剧本写出来的**。DH-S01（剧本里写看镜头）= 0，DH-S02（首拍没给视线落点 / 静止开场）= 0：80 镜首拍都写了视线落点。问题出在出图 / 出片模型的默认行为，只能在画面上测（DH-F12 / DH-V15，交 VQA 的 VLM 或人脸朝向检测），提示词层由 ACTING 加“开场即在动作中、视线在 X”。

## 2. 类目与检测方式

59 类，按 剧本 19 / 首帧 17 / 视频 18 / 声音 3 / 合成 2 分组，见下方自动生成的表。检测方式：

- **auto**：本地确定性检测——剧本字段（`data/staging_v3/merged` 每集最新稿的 人物 / 分拍 / 衔接 / 造型 / img / H3）、首帧契约记录（`data/renders/epNN/SN/takes.json` 当前版 postflight）、像素统计（分辨率、重复文件、同场亮度跳变）、视频指标（`data/pipeline/runs/series10_v1/video/scores/*.json`）、成片 timeline（`data/episodes/series10/*.timeline.json`）。
- **vlm**：只能看图看片（看镜头、第二人表情、跨镜鞋饰、路人脸、鬼影、表演是否符合剧本……）→ 写进 `data/qa/defect_hunt/vlm_queue.json`，由 VQA 的本地 VLM rubric 打分；本工具**不把它们记成 0 命中**。

## 3. 首轮命中后的分派（2026-11-01）

owner 以 `tools/qa/ownership.yaml` 为准；剧本类改法只给写作方规则（Claude 不改剧本内容）。

| 命中类 | 首轮 | 分派给 | 要做的 |
|---|---|---|---|
| DH-S11 外层没写进 img、DH-S12 下装泛称 | 6、3 | 写作方（经 PROMPT / 总调度） | 已有 QW-W1 / QW-W4（写作链路 block）+ writer_knowledge；现行稿 ep01 返修 |
| DH-S17 接力承接动作断 | 9 | 写作方（经 PROMPT） | 新 QW-W5 + K-WRT-Q06（本轮加） |
| DH-S16 分拍没覆盖到镜长 | 8 | PROMPT / AUTOPILOT（SS-M2） | 写作链路里升 block 或确定性补拍 |
| DH-S03 多人镜第二人反应空、DH-S08 对白镜没写视线 | 1、2 | ACTING | 并入 R11-9 / R11-6 的表演规则与 lint |
| DH-S05 节奏慢、DH-S06 台词密度 | 2、1 | PROMPT + FIX（剪辑） | K-EDT-I01 节奏规则复核 ep03 |
| DH-F11 同场首帧亮度跳变 | 2 | PRODUCER | 同场接力镜加光线一致检查 |
| DH-V07 多一只手（闸门放过） | 21 | VIDEO10 + VQA | K-REV-Q01：任一帧超手即缺陷，抽帧交 VLM |
| DH-V09 坏手指、DH-V08 分身 | 33、13 | VIDEO10 + VQA | V6 阈值复核 + VLM 复核 |
| DH-V06 身份漂移、DH-V12 景别退档 | 42、46 | VIDEO10 | 已有 K-REN-301 / K-REV-301；下一轮只算现行版 |
| DH-V04 顿挫、DH-V05 镜内硬切、DH-V01 动作不足、DH-V13 发色漂移、DH-V11 泛红 | 14、5、4、11、2 | VIDEO10 | 按 loop 阶梯重出 |
| DH-V10 口型 V7 不过 | 10 | VIDEO10 | 对白镜按 V7 重出 / 改对白源 |
| DH-V14 540×960 单镜 / 没有 4K 档 | 14 | VIDEO10 + FIX | K-REV-Q02：4K 放大写进 SOP（R11-7） |
| DH-A02 长时间无人声、DH-A01 真峰值 | 4、1 | FIX（剪辑）/ BGM10 | 节奏收紧 + 限幅 |
| DH-X01 成片用占位 / 静帧 | 28 | FIX / VIDEO10 | 缺片补齐后重合成 |
| 看图类 DH-F12–F17、DH-V15–V18、DH-A03 | 交 VQA | VQA（+ ACTING） | 进 VLM rubric；结果回写本表 |

注：视频类按 `video/scores` 里**全部尝试**统计（77 条，含已淘汰的 seed），不是只算现行版；下一轮按 PRODUCER 登记表只算现行版。

## 3b. 第 2 轮（RSI，fredw-2b 派，2026-11-01 16:05）：R11 样例逐条复现

数字出处：data/qa/defect_hunt/state.json（16:05 `defect_hunt.py --force`）；视频按“全部尝试 / 现行版”两个数（K-REV-Q03）。

| 样例 | 复现结果 | 根子在哪 | 新规则 / 检查 |
|---|---|---|---|
| R11-2 演员看镜头 | **复现**：总调度标签 data/acting/gaze_labels.json 首帧 100 张有效标签 71 张看镜头（DH-F18）；剧本侧 DH-S01 = 0 | 出图模型默认行为，不是剧本写的 | K-OPS-Q14（标签当真值计数）；渲染侧修法已有 K-REN-G01（ACTING） |
| R11-8 开场盯镜头停 1 秒 | **复现**：片头 72 条里 56 条看镜头，其中 10 条带定格（DH-V21，现行版 19 条）；head_s 指标 DH-V02 = 0（运动量指标看不出“人在看镜头”） | 出片模型默认行为；DH-S02 = 0（80 镜首拍都写了视线落点） | K-OPS-Q14；K-REN-G02（ACTING，待验）。检测器召回 0.42 / 0.61 未过线（data/acting/calib_score.json） |
| R11-4 多一只手 | **复现，并且进了成片**：最新 ep01_v2 里 S2（mot，手最多 3 只 / 1 人）、S4（s2，5 只 / 2 人）都是 V6 通过的版本（DH-X03）；现行版多手 14 条（DH-V07） | V6 闸门 extra_hand_frac ≥0.05 才拦 + 坏手指阈值为空 | K-REV-Q06（成片版本复核）、K-REV-Q05（空阈值暴露：bad_finger_frac 150 条测了、91 条 >0.2、全放行，DH-V20） |
| R11-4 鞋不一致 | 剧本侧**未复现**：看得见脚的 7 镜 img 都写了鞋（DH-S20 = 0）；画面侧要看图（DH-F14，VQA 只判了 1 张，未测） | 剧本侧 lint VQ-W1 从没接进写作链路（只在 tools/vqa 定义） | K-OPS-Q15 + 接线（validate_qwen_script 加载 VQ-W1） |
| R11-4 人物不一致 | 现行版身份 p10 <0.5 24 条（DH-V06） | 出片 | 已有 K-REN-301（VIDEO10） |
| R11-9 第二人没表情 | 剧本侧 DH-S03 1 处（ep04-S4）；ACTING 的 QW-A5 更严，103 处；画面侧要看图（DH-F13 / V17 未测） | 剧本 + 画面 | 已有 K-WRT-A05 / QW-A5 |
| R11-3 节奏慢 | ep03 平均镜长 7.7 s、ep04 7.6 s（DH-S05）；成片 ep01_v1 有 13 s、8.2 s 无人声段（DH-A02） | 剧本 + 剪辑 | 已有 K-EDT-I01、QW-A3 |
| R11-8 字幕 | **未复现**：剧本 / 提示词 / timeline 都没要字幕（DH-S15 = 0），首帧 Q6 0 处 | — | 已有 K-REN-G03 硬拦 |
| R11-7 像素低 | 单镜 540×960 代理、成片没有 4K 档（DH-V14 18 处） | 交付链 | 已有 K-REV-Q02 / K-EDT-V07 |
| 口型 | V7 不通过现行 4 条；另有 6 条是“未测”（脸检出不足），首轮被错记成口型缺陷 | 统计口径 | K-REV-Q04 |

本轮发现的“漏检原因”（补 §1）：
6. **未测被算成缺陷 / 通过。** DH-V10 首轮把 V7“未测”记成口型不同步；反过来 V6 的 bad_finger_frac 阈值是 null，测到了也永远判通过。两头都让数字不可信（K-REV-Q04 / Q05）。
7. **全部尝试 ≠ 成片。** 首轮按 160 条全部尝试计数，说不出成片里有没有缺陷；改成同时看现行版和成片 origin 后，才看到 ep01_v2 实际带着多手的版本（K-REV-Q03 / Q06）。
8. **已经有人工真值，没人接进来。** 总调度 11-01 标完 183 条看镜头标签，缺陷猎捕仍把看镜头记成“交 VQA”。标签就是复现证据（K-OPS-Q14）。
9. **写作 lint 只定义不接线。** VQ-W1 在 tools/vqa/script_lint.py 里，写作链路的校验器没加载，写作模型从来看不到（K-OPS-Q15，测试逐条核对）。

看图类实跑（vlm_queue）：tools/qa/defect_vlm.py 已写好（进了成片的可疑视频先跑，再多人镜首帧，再其余首帧）。16:07 试跑 2 条：ep01-S3 看图服务 OOM（看图模型 7 GB 装上 gpu36 GPU0 后 ComfyUI 涨到 16 GB）；ep01-S4 视频判定输出不是 JSON（VQA 视频提示词的解析问题，交 VQA）。为不抢生产卡，已停，并让工具碰到 OOM 立即停。看图类目前仍然 = 未测。

### 交 VQAGATE（看图命中 → 拦截 + 自动重出；总调度 11-01 通知）

能变成拦截项的看图类，以及建议的拦截条件。项目方 11-01 已定看图闭环转拦截、图片闸门先于视频（config/owner_decisions.yaml D-VQA-01；config/vqa.json judge.enforce = true），下表的标定素材用来量误拦率，不再是开拦截的前提：

| 缺陷类 | VQA 检查项 | 建议拦截 | 标定素材（现成） |
|---|---|---|---|
| DH-F12 / F18 首帧看镜头 | eye_contact | 首帧 defect → 按 K-REN-G01 加视线句重出 | data/acting/gaze_labels.json 图片 100 条（71 正 / 29 反） |
| DH-V15 / V21 片头看镜头 / 定格 | first_frame_stare | 视频 defect → 换 seed / 加 open_motion_cue 重出 | 同上，片头 72 条（56 正） |
| DH-V07 / X03 多一只手 | extra_limbs（视频抽帧） | hands_max >2×人数的片抽帧给 VQA，确认就拦 | 现行版 14 条 + ep01-S2__mot / ep01-S4__s2 / ep01-S3__v1；VQA 标定集**缺多手正例**（docs/vqa/STATE.md），这些可以补 |
| DH-F14 跨镜鞋 / 饰品 | shoe_mismatch / accessory_mismatch | 同造型相邻镜不一致 → 拦 | VQA 标定集鞋 7 / 7 |
| DH-F13 / V17 第二人没表情 | blank_expression | 多人镜 defect → 拦并回写剧本 QW-A5 | 多人镜现行首帧 22 张（defect_vlm --dry 列表），需标注 |
| DH-V16 鬼影 / 穿模 | morphing | 视频 defect → 换 seed | 无，需标注 |
| DH-F21（新，AUDIT 19:3x）单品串人：一个角色的标志性单品（指甲 / 手套 / 首饰）长在另一个角色身上 | item_on_wrong_person（VQAGATE 新加，从 outfit_mismatch 拆出来；只判两人及以上的镜头） | 先只记录；标定过了再拦 | 正例：reflock_val S4_vN，顾沉手上长着林晚的“冰川满钻尖甲”（data/ab/localgpu_verify/repro_S4_vN/，服务器原图也是这样）；反例：两人镜里已通过的首帧（ep01-S6、ep04-S1 等）；结果写 data/vqa/gate_calib/item_wrong_person.json。**22:5x 实测：看图模型做不成高置信拦截**（正例原口径判 na、口径 B 判 defect 但理由错），改法见 GATE_CALIBRATION §8：手部裁切后单独问 |

VQAGATE 可以直接调 `tools/qa/defect_vlm.py`（不改它）；结果写 data/qa/defect_hunt/vlm_results.jsonl，首帧判定同时进 data/vqa/index.json（VQA 的缓存入口）。

## 4. 常驻 loop（ITERATION_PROTOCOL §5.2，iter_gate H1）

- 每出一集新首帧 / 新视频 / 新成片：`.venv/Scripts/python.exe tools/qa/defect_hunt.py --force`，新命中按上表分派，写回本文；看图类等 VQA 结果。
- iter_gate **H1**：生成类 loop（ASSETMASTER / REFLOCK / IMGGEN / VIDEO10 / BAKEOFF / AUTOPILOT）收轮时，`data/qa/defect_hunt/state.json` 必须比最新的 takes.json / 视频评分 / 成片 timeline 新，检测器不得报错；否则 INCOMPLETE / FAIL。
- 新缺陷类：在 `tools/qa/defect_hunt.py` 的 CLASSES 加一行（检测器 + owner + 规则），写作相关的同时加 QW lint + writer_text（ITERATION_PROTOCOL 7a）。

## 5. 断点续跑（笔记本离线 / 中断后）

- 状态每跑完一类就落盘：`data/qa/defect_hunt/state.json`。直接再跑 `tools/qa/defect_hunt.py`，已完成的类跳过；`--force` 全部重跑；`--only DH-V07,DH-S17` 只跑几类；`--report` 只按状态重写本文的生成段。
- 只读：不改剧本、不出图、不调 GPU / API。

## 6. 首轮结果（自动生成）

## 首轮结果（自动生成）

<!-- defect_hunt:begin（tools/qa/defect_hunt.py 生成，勿手改本段） -->

更新：2026-11-01 17:52；类目 67；自动检测 56 类，其中有命中 31 类、共 689 处；交 VQA 6 类。剧本来源：{}；首帧 0 镜；视频评分 0 条（现行版 None 条：manifest chosen，无 manifest 的镜取最新评分）。

| 类 | 阶段 | 缺陷 | 样例 | 方式 | 命中（全部尝试 / 现行版） | 例子（视频优先列现行版） | owner | 规则 / 检查 |
|---|---|---|---|---|---|---|---|---|
| DH-S01 | 剧本 | 演员看镜头（视线=镜头 / looks at the camera） | R11-2 R11-8 | auto | 0 |  | ACTING→PROMPT | 新 QW-W5 |
| DH-S02 | 剧本 | 开场没给视线落点 / 以静止开场（模型默认先看镜头、停 1 秒） | R11-8 | auto | 0 |  | ACTING→PROMPT | 新 QW-W6 |
| DH-S03 | 剧本 | 多人镜第二人没有表情 / 视线 / 反应 | R11-9 | auto | 1 | ep04-S4｜2 人在画（林晚、陈宇），0/5 拍反应=空，分拍里没写到 陈宇 | ACTING→PROMPT | K-WRT-I02 + 新 QW-W7 |
| DH-S04 | 剧本 | 整镜分拍没有身体动作（静止镜） | ep01-S2 | auto | 0 |  | PROMPT | K-WRT-Q03 QW-W2 |
| DH-S05 | 剧本 | 节奏慢：平均镜长 >7.5s / 长镜只有 ≤2 拍 | R11-2 R11-3 | auto | 2 | ep03｜平均镜长 7.7s（>7.5s）<br>ep04｜平均镜长 7.6s（>7.5s） | PROMPT | K-EDT-I01 |
| DH-S06 | 剧本 | 台词密度：>5 字/秒说不完；无台词长镜拍数过少 | R11-3 | auto | 1 | ep07-S1｜22 字 / 4s = 5.5 字每秒（>5，说不完或被压缩） | PROMPT | K-WRT-002 |
| DH-S07 | 剧本 | 180° 轴线：同场相邻镜两人左右互换且没标越轴 | — | auto | 0 |  | PROMPT | K-WRT-104 |
| DH-S08 | 剧本 | 对白镜没写说话人视线（眼神线断） | R11-6 | auto | 2 | ep05-S3｜对白镜分拍没写视线<br>ep05-S6｜对白镜分拍没写视线 | ACTING→PROMPT | K-WRT-003 |
| DH-S09 | 剧本 | 鞋与本镜造型登记不一致 | R11-4 | auto | 0 |  | PROMPT | K-AST-252 |
| DH-S10 | 剧本 | 发型发色与登记不一致 | — | auto | 0 |  | PROMPT | HC-07 |
| DH-S11 | 剧本 | 外层衣物没写进 img | V14 | auto | 6 | ep01-S1｜林晚 造型有「西装外套」，img 没写<br>ep01-S2｜林晚 造型有「西装外套」，img 没写 | PROMPT | K-WRT-Q01 QW-W1 |
| DH-S12 | 剧本 | 下装泛称（西装裙 / 套裙） | V14 | auto | 3 | ep01·林晚｜造型服装「西装裙」<br>ep02·林晚｜造型服装「西装裙」 | PROMPT | K-WRT-Q05 QW-W4 |
| DH-S13 | 剧本 | 局部角色写了脸 / 头发 | ep03-S6 | auto | 0 |  | PROMPT | K-WRT-Q02 QW-CH6 |
| DH-S14 | 剧本 | 独白镜嘴在动 / H3 缺 lips closed | — | auto | 0 |  | PROMPT | K-WRT-Q04 QW-W3 H3-D5 |
| DH-S15 | 剧本 | 提示词 / 成片要了字幕或文字 | R11-8 | auto | 0 |  | PROMPT + FIX | 新 QW-W8 |
| DH-S16 | 剧本 | 分拍时间没覆盖到镜长 | — | auto | 8 | ep02-S1｜分拍到 4s，镜长 5s<br>ep07-S5｜分拍到 4s，镜长 5s | PROMPT | SS-M2 |
| DH-S17 | 剧本 | 接力“承：动作”的物件 / 动作下一镜没接上 | — | auto | 9 | ep01-S5｜承：动作｜手垂在身侧；img + 首拍只接上 0/3<br>ep02-S3｜承：动作｜指尖停在耳侧；img + 首拍只接上 0/4 | PROMPT | K-WRT-R06 |
| DH-S18 | 剧本 | 接力 / 同场换机位却换了场景（空间地理断） | — | auto | 0 |  | PROMPT | QW-LK2 |
| DH-S19 | 剧本 | 同场相邻镜光线冷暖互换 | — | auto | 0 |  | PROMPT | K-AST-252 |
| DH-F01 | 首帧 | 人物身份不像（Q1） | R11-4 | auto | 0 |  | REFLOCK / PRODUCER | GEN_CONTRACT Q1 |
| DH-F02 | 首帧 | 造型 / 鞋不一致（Q2） | R11-4 | auto | 0 |  | REFLOCK / PRODUCER | GEN_CONTRACT Q2 |
| DH-F03 | 首帧 | 景别不对（Q3） | — | auto | 0 |  | REFLOCK / PRODUCER | GEN_CONTRACT Q3 |
| DH-F04 | 首帧 | 塑料 / 糊 / 油光（Q4） | — | auto | 0 |  | REFLOCK / PRODUCER | GEN_CONTRACT Q4 |
| DH-F05 | 首帧 | 多手 / 多肢 / 多人（Q5） | R11-4 R11-10 | auto | 0 |  | REFLOCK / PRODUCER | GEN_CONTRACT Q5 |
| DH-F06 | 首帧 | 文字 / 水印 / 字幕（Q6） | R11-8 | auto | 0 |  | REFLOCK / PRODUCER | GEN_CONTRACT Q6 |
| DH-F07 | 首帧 | 场景不对（Q7） | — | auto | 0 |  | REFLOCK / PRODUCER | GEN_CONTRACT Q7 |
| DH-F08 | 首帧 | 契约项未测 / 没有 postflight（未测冒充通过） | — | auto | 0 |  | REFLOCK / PRODUCER | K-OPS-Q01 |
| DH-F09 | 首帧 | 分辨率低于 768×1344 | R11-7 | auto | 0 |  | PRODUCER | 新 |
| DH-F10 | 首帧 | 不同镜头当前首帧是同一张图 | S1–S4 事故 | auto | 0 |  | DATAALIGN / PRODUCER | 新 |
| DH-F11 | 首帧 | 同场相邻首帧亮度跳变（光线连续） | — | auto | 2 | ep04-S7｜同场相邻首帧平均亮度 75→123<br>ep10-S8｜同场相邻首帧平均亮度 42→93 | PRODUCER | 新 |
| DH-F12 | 首帧 | 演员看镜头 | R11-2 R11-8 | vlm | 2（VQA 已判现行首帧 5/55 张） | ep01-S4｜VQA eye_contact：林晚应迎上顾沉视线，图中未迎上<br>ep03-S4｜VQA eye_contact：两人均未看镜头，原文不允许看镜头 | VQA | VLM rubric（VQA eye_contact） |
| DH-F13 | 首帧 | 第二人没有表情 / 眼神 | R11-9 | vlm | 0（VQA 已判现行首帧 5/55 张） | VQA 已判现行首帧 5/55 张 | VQA | VLM rubric（VQA blank_expression） |
| DH-F14 | 首帧 | 跨镜鞋 / 饰品不一致（同造型） | R11-4 | vlm | 2（VQA 已判现行首帧 5/55 张） | ep01-S4｜VQA accessory_mismatch：林晚指甲应为5厘米超长透明水晶甲，图中为短指甲<br>ep03-S4｜VQA accessory_mismatch：林晚指甲未见钻石水晶甲 | VQA | VLM rubric（VQA shoe / accessory） |
| DH-F15 | 首帧 | 路人 / 背景人脸畸形 | — | vlm | 0（VQA 已判现行首帧 5/55 张） | VQA 已判现行首帧 5/55 张 | VQA | VLM rubric（VQA artifact） |
| DH-F16 | 首帧 | 道具 / 场景陈设跨镜不一致 | — | vlm | 0（VQA 已判现行首帧 5/55 张） | VQA 已判现行首帧 5/55 张 | VQA | VLM rubric（VQA wrong_scene） |
| DH-F17 | 首帧 | 剧本写的动作 / 姿势没画出来（图文不符） | R11-10 | vlm | 交 VQA | 交 VQA 的本地 VLM rubric（data/qa/defect_hunt/vlm_queue.json） | VQA | VLM rubric |
| DH-V01 | 视频 | 动作不足 / 静止 | R11-2 | auto | 8 / 1 | ep10-S2__s4｜mean 0.288 still 0.732 | VIDEO10 | K-REN-302 |
| DH-V02 | 视频 | 开头定格（head_s >0.5s，首帧盯镜头 1 秒） | R11-8 | auto | 0 |  | VIDEO10 | 新 |
| DH-V03 | 视频 | 结尾定格（tail_s >0.5s） | — | auto | 2 / 1 | ep10-S7__s2｜tail_s 0.75 | VIDEO10 | K-EDT-003 |
| DH-V04 | 视频 | 顿挫 / 抖动（J4 ≥1.2 且 z ≥3） | — | auto | 37 / 14 | ep03-S4__v1｜J4 1.38 z 5.66<br>ep03-S7__s2｜J4 1.287 z 5.91 | VIDEO10 | K-REV-R06 |
| DH-V05 | 视频 | 镜内硬切 / 跳帧 | — | auto | 14 / 4 | ep05-S1__s4｜cuts [0.12]<br>ep05-S2__s4｜cuts [0.08] | VIDEO10 | K-REV-R05 |
| DH-V06 | 视频 | 身份漂移（sface p10 <0.5） | R11-4 | auto | 82 / 24 | ep01-S1__v1｜林晚 p10 0.461<br>ep01-S4__s2｜顾沉 p10 0.223；林晚 p10 0.24 | VIDEO10 | K-REN-301 |
| DH-V07 | 视频 | 多一只手（任何帧手数 >2×人数，闸门放过的也算） | R11-4 | auto | 45 / 14 | ep01-S2__mot｜手最多 3 只 / 1 人，extra_hand_frac 0.01（V6 通过）<br>ep01-S3__v1｜手最多 4 只 / 1 人，extra_hand_frac 0.068（V6 不通过） | VIDEO10 + VQA | 新 |
| DH-V08 | 视频 | 重复人 / 分身（dup_side_frac >0.1） | — | auto | 26 / 4 | ep04-S6__v1｜dup_side_frac 0.135<br>ep05-S7__s4｜dup_side_frac 0.681 | VIDEO10 | V6 |
| DH-V09 | 视频 | 坏手指（bad_finger_frac >0.2） | — | auto | 91 / 40 | ep01-S2__mot｜bad_finger_frac 0.208<br>ep01-S3__v1｜bad_finger_frac 0.528 | VIDEO10 + VQA | V6 |
| DH-V10 | 视频 | 口型：对白不同步 / 独白嘴在动（V7 不过） | — | auto | 26 / 4 | ep01-S6__s3｜V7 不通过 嘴部开合与声音相关 0.29 < 0.3<br>ep03-S3__s4｜V7 不通过 嘴部开合与声音相关 0.21 < 0.3 | VIDEO10 | V7 |
| DH-V11 | 视频 | 脸颊泛红 / 首帧色偏 | — | auto | 3 / 0 | ep04-S4__r24｜cheek_red 0.127 dE0 12.57<br>ep05-S6__v1｜cheek_red 0.251 dE0 1.32 | VIDEO10 | K-REV-R0x |
| DH-V12 | 视频 | 景别退档（实测 ≠ 要求） | V1 | auto | 106 / 38 | ep01-S1__v1｜要 特写 实测 近景/中近景<br>ep01-S5__v1｜要 近景 实测 中景 | VIDEO10 | K-REV-301 |
| DH-V13 | 视频 | 发色漂移（hair dS/dV >25） | — | auto | 20 / 7 | ep01-S4__s2｜hair dS 28.0 dV -10.5<br>ep03-S3__s4｜hair dS 12.0 dV -31.5 | VIDEO10 | 新 |
| DH-V14 | 视频 | 分辨率低 / 没有 4K 交付档 | R11-7 | auto | 22 | ep01-S1.mp4｜540×960<br>ep01-S1_sg.mp4｜540×960 | VIDEO10 + FIX | 新（SOP 4K 放大） |
| DH-V15 | 视频 | 演员看镜头 / 开场盯镜头 | R11-2 R11-8 | vlm | 交 VQA | 交 VQA 的本地 VLM rubric（data/qa/defect_hunt/vlm_queue.json） | VQA | VLM rubric |
| DH-V16 | 视频 | 鬼影 / 拖影 / 肢体穿模 | — | vlm | 交 VQA | 交 VQA 的本地 VLM rubric（data/qa/defect_hunt/vlm_queue.json） | VQA | VLM rubric |
| DH-V17 | 视频 | 第二人表情 / 视线空白 | R11-9 | vlm | 交 VQA | 交 VQA 的本地 VLM rubric（data/qa/defect_hunt/vlm_queue.json） | VQA | VLM rubric |
| DH-V18 | 视频 | 表演与剧本动作不符 | R11-6 | vlm | 交 VQA | 交 VQA 的本地 VLM rubric（data/qa/defect_hunt/vlm_queue.json） | VQA + ACTING | VLM rubric |
| DH-A01 | 声音 | 响度偏离 -14 LUFS / 真峰值 >-1 | — | auto | 1 | ep01_v1.timeline.json｜真峰值 -0.88 dBTP（>-1） | FIX（剪辑） | K-EDT-* |
| DH-A02 | 声音 | 长时间无人声（>6s 死寂） | R11-2 | auto | 4 | ep01_v1.timeline.json｜5.0–18.0s 无人声 13.0s<br>ep01_v1.timeline.json｜22.8–31.0s 无人声 8.2s | FIX（剪辑） | 新 |
| DH-A03 | 声音 | 配乐没给台词让路（避让） | — | vlm | 交 VQA | 交 VQA 的本地 VLM rubric（data/qa/defect_hunt/vlm_queue.json） | BGM10 | QW-M1 |
| DH-X01 | 合成 | 成片用了占位 / 静帧 / 有合成警告 | — | auto | 28 | ep01_v1.timeline.json｜ep01-S2 用占位 / 静帧（still）<br>ep01_v1.timeline.json｜ep01-S6 用占位 / 静帧（still） | FIX（剪辑） | — |
| DH-X02 | 合成 | 剧本里的镜头成片没有 | — | auto | 0 |  | FIX（剪辑） | — |
| DH-S20 | 剧本 | 看得见脚的景别鞋没写进 img | R11-4 | auto | 0 |  | PROMPT（写作方） | K-WRT-V06 VQ-W1 |
| DH-F18 | 首帧 | 演员看镜头（人工标签） | R11-2 | auto | 71 | ep01-S1_4208ace3.jpg#0｜人工标注：看镜头<br>ep01-S1_746cb5f7.jpg#0｜人工标注：看镜头 | ACTING / REFLOCK | K-REN-G01 K-REV-G04 |
| DH-V19 | 视频 | 视频契约项未测（V6 / V7） | — | auto | 6 / 1 | ep10-S5__s4｜V7 未测：说话人 / 主角的脸只在 20% 的帧里检出 | VIDEO10 | K-REV-Q04 |
| DH-V20 | 视频 | 闸门阈值为空（测了但永不拦） | R11-4 | auto | 1 | V6.bad_finger_frac｜阈值为空，150 条都测了、永不拦；其中 91 条 >0.2（例 ep01-S2__mot = 0.208） | VIDEO10 | K-REV-Q05 |
| DH-V21 | 视频 | 开头看镜头 / 定格（人工标签） | R11-8 | auto | 57 / 19 | ep01-S1__v1｜人工标注：开头看镜头<br>ep01-S2__mot｜人工标注：开头看镜头 | ACTING / VIDEO10 | K-REN-G02 K-REV-G04 |
| DH-X03 | 合成 | 成片用的视频版本按现评分仍有缺陷 | R11-4 | auto | 4 | ep01_v1.timeline.json｜ep01-S3（v1）进了成片：闸门不过：多肢；手最多 4 只 / 1 人<br>ep01_v1.timeline.json｜ep01-S4（s2）进了成片：手最多 5 只 / 2 人 | FIX + VIDEO10 | K-EDT-009 K-REV-Q01 |
| DH-F19 | 首帧 | 当前版本指向被驳回 / 标不要 / 坏图的版本 | ep01-S5 | auto | 0 |  | PRODUCER + VQAGATE | K-OPS-Q23 |
| DH-F20 | 首帧 | 当前版本和审计日志对不上（有路径绕过 set_active） | ep01-S5 | auto | 1 | ep01-S2·image｜当前 6，审计最后记到 None（2026-11-01T17:01:00） | ITERAUDIT | K-OPS-Q23 |

<!-- defect_hunt:end -->
