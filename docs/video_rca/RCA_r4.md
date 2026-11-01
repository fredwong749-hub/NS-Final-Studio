# VIDEO-RCA 第 4 轮（00:3x 暂停；00:5x VQAGATE 推线程上限后恢复，只用 gpu36:2）

> 只用 gpu36:2，scope=ab。00:3x 总调度：v7_lipsync 在两台服务器上各占 74–90 核，拖垮了 sshd → 我的 srv_run 已全部停掉（gpu36 杀掉 r17 执行器 1 个；gpu33 没有我的进程；ps 核对无残留 score_clip / v6 / v7 子进程）。r18 执行器没起来（启动 ssh 超时）。

## 已完成
- K-WRT-702 补限定（knowledge/rules/writer_iteration.yaml 证据加 ⤴：只管“整件消失”，坐→站无袖漂移是另一根因，RCA_r3 §1.2）；CONSENT ITERAUDIT → VIDEO_RCA 已写进 docs/uimaster/LOCKS.md；compile --check 通过（445 条）。
- 拆镜写法规则草案 K-WRT-704（knowledge/inbox/2026-11-01_video_rca_writer.yaml）：穿外套的人不在一镜里完成坐→站，上一镜停在起身开始，下一镜从站定开始。证据：S3 坐→站 8/8 + 2/2 外套变形 vs S4 全程站着 5 条外套基本不变；拆镜本身的 A/B 未完成。
- 口型诊断首帧：r16_img_malefront（gpu36:2，2 seed）出了一张顾沉四分之三正脸、嘴微张的双人首帧（data/ab/video_rca/r16_img_malefront/sheet.jpg，seed 20261205 可用；seed 31 顾沉偏看镜头，弃用）。
- tools/video_rca/srv_run.py：所有服务器子进程（score_clip、V6/V7 重跑、sharp、ffmpeg）一律 taskset 绑 4 核（VRCA_CORES，默认 44-47）+ nice 15 + 线程环境变量 4；ffmpeg -threads 4。还没推到服务器，下次启动时推。

## 暂停中（等 VQAGATE 给 v7_lipsync 加线程限制并推上服务器）
- r17_split_standing（拆镜镜 B：从站定开始，2 seed）：第 1 条在 gpu36:2 的 ComfyUI 里已提交，生成会跑完，但不会打分。
- r18_lip_malefront（男主正脸首帧 × 3 seed，区分“模型问题”和“视角问题”）：已编好，没提交。
- 首尾帧方案：等 ep01-S3 出定稿尾帧。
- 生产双人镜按实测句重出后的看镜头率：等新首帧出来。


## 恢复后结果

### r17 拆镜镜 B（从站定开始，2 seed；data/ab/video_rca/r17_split_standing/*_kf.jpg，第 0/40/80/120/170 帧）
- 两个 seed 外套在整条片里都和第 0 帧一致，没有再漂移（2/2）→ 不做坐→站时，Pika 保住首帧里的服装（与 S4 5/5 一致），支持 K-WRT-704 的拆镜写法（中，2 seed）。
- **新发现（根因候选，高）：造型参考图本身就是坏的。** 林晚造型 A 的去头设定图 data/pipeline/runs/series10_v1/images/refcrops/lin_wan_lookA_v2_s202_front_nohead.png（出图的图2，全集林晚造型 A 镜头都用它）里那件短款西装外套**只有一只袖子**：画面左侧（她的右臂）是深灰外套袖，画面右侧（她的左臂）露的是米白衬衫袖，外套前襟也只到腰。参考板 ①（refboards/board_09a34ea5c95f.png）却是正常的长袖西装外套。出图把两者拼成“外套前襟 + 衬衫袖”的混合体（这张站姿首帧、S5 首帧都是），视频里外套漂成“无袖 / 短款马甲”正好落到设定图的样子。
- 这就是 AUDIT 指出的“无袖”的上游根因：不是 Pika 自己发明的，是造型资产缺袖子 + 和参考板冲突。交 ASSETMASTER / REFLOCK：重出造型 A 设定图（外套两只袖子完整、长度与参考板一致），之后重出受影响首帧；VQAGATE 可加一项“外套袖子左右一致”。
- 复核 ep01-S3 首帧（data/pipeline/runs/series10_v1/video/inputs/ep01-S3_ada503e6.jpg）：外套同样只有右臂一只深色袖子，搭在桌上的左臂是米白衬衫袖——**首帧里外套本来就是“一只袖子”的不可能结构**。视频层结论随之修正：坐→站时外套“变无袖 / 消失再穿回”，是模型在大动作中把这件结构不成立的外套“解释”掉；S4 / r17 站着不动时就保持首帧原样。拆镜（K-WRT-704）只能减轻，根治是修造型资产（高：参考图、两张首帧都能直接看到）。

### r18 口型：男主四分之三正脸首帧 × 3 seed（data/ab/video_rca/r18_lip_malefront/）
- V7：corr −0.075 / −0.171 / −0.176，0/3 过；嘴部开合中位 0.0066–0.0074，张嘴帧 0（同 S4 原首帧 1/3、新首帧 B 2/3）。
- 人工看第 96–120 帧（台词在 4.0 s）：首帧里顾沉是四分之三正脸，但到台词那一拍，他已按分拍“eyes lifting to hers, jaw drawing in”转成**侧脸朝向林晚**，嘴几乎不动（mouth.jpg）。
- 结论（中）：换首帧角度救不了，因为分拍让说话人在台词时转向对方，模型就把他画成侧脸；侧脸 + 几乎不张嘴 → V7 不过。林晚近景正面说话 3/3 过。“男主模型本身”和“视角”仍没完全分开——要分开需要台词那一拍男主面朝画面前方（例如对方在镜头一侧的过肩反打），下一轮在空闲出图道上做。
- 对写作侧的含义：K-WRT-703 草案（台词那拍别低头）可扩成“台词那一拍说话人的脸至少四分之三朝画面前方（反打 / 过肩构图），不要侧脸对侧脸说话”——待验证后再改。

### 资源
- 总调度 L-100：gpu36:2 改作 VQAGATE 专用看图卡。r18 跑完后服务器上没有我的执行器、:8190 队列为空，已通知 VQAGATE（a6b7881314877ca56）。之后的视频测试只排空闲出图道，不抢 producer 正在派单的道。
