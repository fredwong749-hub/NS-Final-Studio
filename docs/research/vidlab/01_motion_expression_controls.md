# VIDLAB 01：Pika / H3 在 ComfyUI 里能用的运动与表情控制（线 2，11-02）

> 只列能在我们这套环境（MiniMax H3 FL2VA int8 pruned + Pika Flex LoRA，ComfyUI 0.42）里落地的控制手段。置信度：高 = 源码或官方文档；中 = 多人实测；低 = 单人或推断。
> 不换主线模型（L-088），不花钱。

| # | 手段 | 控制对象 | 现状 / 证据 | 置信度 | 本线动作 |
|---|---|---|---|---|---|
| 1 | 提示词表演节拍：每个 `At 00:0X` 分拍写可观察的微动作（眉、眨眼、呼吸、嘴角），按秒写眨眼 | 表情 | H3 官方指南要求“按时间写可观察的变化”；HF #96 提到 H3 几乎不眨眼，有人建议写明第几秒眨眼（docs/research/h3_deep/01_official.md） | 中（机制）/ 低（效果） | vl_r1_acting：ACT2 臂（tools/vidlab/acting.py micro_beats） |
| 2 | 全局“脸一直在演”系统句 | 表情 | 同 open_motion_cue 的位置规则（prompt.py 插在第一个时间码之前） | 低 | vl_r1_acting：ACT1 臂 |
| 3 | 把正文里的定格动词（hold there / freezing / stays locked）换掉 | 表情 / 动作 | ep01-S4 原稿每拍都有定格词；现在只是推断，还没做 A/B | 低 | 属写作侧用词，先量化“定格词数 ↔ 表演活跃度”的相关性，再交 HOLLYWOOD / writer_knowledge |
| 4 | Pika Flex LoRA 强度 1.0 → 0.8 | 运动量 / 表情 | 社区：蒸馏或 turbo LoRA 会让动作僵（“ref2va turbo LoRAs make things a bit rigid”，lightx2v #58）；首尾帧贴合差时有人从 1.0 降到 0.8–0.65 | 低-中 | vl_r1_acting：LORA08 臂（graph_set） |
| 5 | `MiniMaxH3AddGuide` 中间关键帧（表情变化帧放在中段） | 表情 / 姿态 | 节点存在，没有 strength 参数；有人反馈 guide 放太密会把脸冻住（hidetaro7） | 高（存在）/ 低（效果） | r2 候选：需要出图线（IMGLAB）出同机位、换表情的关键帧 |
| 6 | **MiniMax H3 Fun ControlNet Union**（`MiniMaxH3FunControlNetApply` + model patch） | 运镜（Depth / MLSD）+ 肢体 / 头部（Pose） | ComfyUI 官方教程：补丁可用于 fl2va 和 ref2va 底模；控制类型有 Canny / Depth / HED / MLSD / Pose；strength 0–10，另有 start / end_percent。gpu36 的 object_info 里已有这个节点，**但 model_patches 目录不存在**，补丁文件 `minimax_h3_fun_controlnet_union_pruned_int8_convrot.safetensors`（Comfy-Org/MiniMax-H3，免费）还没下载。和 Pika Flex LoRA 叠加的效果没有任何公开实测 | 高（节点 / 文档）/ 低（和 Pika 叠加） | **结构化运镜的首选方向**：用首帧单目深度加虚拟机位轨迹渲染一段 Depth 控制视频，让运镜按参数执行，不靠提示词去“求”；Pose 用参照表演的骨骼驱动头部和肩部动作。要下载补丁，并且服务器上得有一条空闲道，下载和放置走 deploy 登记 |
| 7 | 拆镜（≤6 s） | 漂移 / 动作完整度 | 官方 fallback：“shorten the shot to ≤6s”；K-WRT-704 拆镜有效（RCA_r4） | 中-高 | 已在写作侧落地 |
| 8 | 步数 6 → 8 | 动作顺滑 | 社区：4 步动作慢，8 步更顺；Pika 官方模板固定 6 步 | 中 | 排在 LoRA 之后；会改变 Pika 模板 |

## 度量
- 打分器：tools/vidlab/score.py（六个分项）+ tools/vidlab/clipmetrics.py（表演 / 运镜像素指标）。
- 好莱坞锚点：Charade（1963，美国公有领域）和 Tears of Steel（2012，CC-BY 3.0）的人物镜头。片源只存在本地 data/rsi/ref_video/raw/，只给本地模型看。

## 参考
- ComfyUI Fun ControlNet 教程：https://docs.comfy.org/zh/tutorials/video/minimax/minimax-h3-fun-controlnet.md
- 节点文档：https://docs.comfy.org/built-in-nodes/MiniMaxH3FunControlNetApply.md
- Union 2.0（二手来源，没有核实）：https://comfyui-wiki.com/fr/news/2026-09-22-minimax-h3-fun-controlnet-union-2
- 既有调研：docs/research/h3_deep/、docs/research/h3_prompt_and_fl2v.md

## 实测结果（vl_r1，11-02 11:1x–12:2x，gpu36:1 + gpu33:1，判定 decider = code）
| 实验 | 判定 | 数据 | 文件 |
|---|---|---|---|
| ACT1 全局表演句 | 不通过 | 配对增益中位 +3.3%（S4 s02 +10.3%，但 J4 +0.32；S4 s03 +1.3%；S5 s02 +3.3%） | data/rsi/vidlab/ab_vl_r1_act1.json |
| ACT2 分拍微表情（acting.micro_beats） | 通过（规则：配对增益中位 ≥15% 且 ≥3/4 对变好） | S5 近景单人 s02 +47.0%、s03 +45.3%（眨眼从 0 次/分升到 16 次/分，视线跳动 0.27→0.68/s）；S4 双人 s02 +1.3%、s03 −4.4%；J4、看镜头均不变 | data/rsi/vidlab/ab_vl_r1_act2.json |
| 结构化运镜 camctl（横移，107 帧，strength 0.6、end_percent 0.5） | 不通过 | 运镜执行 0.0→1.0（横移实测 −0.0711，目标 −0.07；杂旋转 2.3°→0.3°），表演活跃度 0.95→0.89；**看镜头占比 0→0.775**，判失败；画面右缘出现暗色竖条（已修：控制视频先放大铺满画面） | data/rsi/vidlab/ab_vl_r1_camctl_truck.json |
| camctl 158 帧 | OOM | gpu36:1 和 gpu33:1 都超显存；107 帧能跑（单条 365 s） | — |

结论：
- 表情：问题不在缺一句“要演”的口号，而在每个分拍没有可执行的微动作。ACT2 对近景单人有效（Pika 默认几乎不眨眼，HF #96）；双人中景没效果，下一步要查双人镜的脸是否太小，或者分拍主语只写了一个人。
- 运镜：Pika 只靠提示词基本执行不了横移 / 俯仰（41 条语料：横移 0.10、上摇 0.0）。FunControlNet 控制视频能把机位轨迹执行准，但会诱发看镜头；下一版试 strength 0.4、end_percent 0.3，同时把人物遮罩外扩到肩部以上的整块区域。
