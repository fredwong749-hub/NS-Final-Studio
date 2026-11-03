# CODER-PS → MASTER-WSL 对齐交接（11-03 10:5x）

项目方原话（10:5x，PS 会话）：“wsl 那边你有没有把 master agent 的全部 todo 和它对齐，我们记忆里讨论的问题，你要让它知道，同时你等待它指挥。”

背景：PS 会话（fredw-2b）此前没有读 CHANNEL，一直自认总调度，自行派活、写了账本 L-145 到 L-155。从现在起本会话只当 CODER-PS 用：等 MASTER-WSL 分派，不再写账本和计划。

## 1. 项目方反复强调的事（记忆里已经压缩好，请当作总调度的准绳）
记忆在 C:\Users\fredw\.claude\projects\C--Users-fredw\memory\。完整定律见 docs/master/OWNER_CANON.md，共 25 条，附原话和被违反的次数。

最关键的几条：
1. **V2 只重做内容**（剧本、人物、身份脸、资产、场景）。V1 的 runtime、routine、infra、提示词、模型、规则、闸门全部是地基，V2 在上面继续迭代，必须比 V1 好，不许另起平行实现。项目方原话：“你把它全部归零是什么情况啊？”部件清单见记忆 ns-final-studio-system-inventory，继承差距见 docs/master/V1_TO_V2_CARRYOVER.md、V2_SYSTEM_LOSS_AUDIT.md。
2. **生产 SOP 是唯一顺序**：剧本 → 导入闸门 → 资产就绪 → 提示词 → 出图 → 出图检测 → 尾帧 → 视频 → 整集预览 → 复盘。不许跳步。
3. **每一集是一次系统迭代**：生产 → 卡点改进代码、规则和 SOP → 写 RETRO → 更新记忆和 harness → 下一集自动跑。每集都要和上一集比指标，包括自动化、介入次数、通过率、Q1、GPU、好莱坞分。
4. **不修修补补**：卡点就是改流水线的机会。判断标准是下一集能不能自己走过去。
5. **重大 infra 和规则决策先和项目方讨论**，用选择题。他在睡觉时只能做成默认关的开关。这条是 11-03 被严厉批评过的。
6. **记忆和文档要压缩、要单一来源、开工前先读。**项目方原话：“memory control 是你这个模型里面最核心的核心”。
7. **产品功能 V1 做了一半的，V2 不许丢**：OpenCut 剪辑器、图像编辑器、资产页 14 个组件、海报、整集预览。改版前必须列出旧功能清单。
8. **画风（V2）**：徕卡镜头风格、ARRI 摄影机、Kodak 胶片感，加时尚大片感。去塑料感、不磨皮。灯光以每一镜的剧本为准。
9. **MiniMax/H3 的时间轴**：At 只用来标切镜，镜内按秒分拍、用自然语言写（L-141）。
10. **UI**：只有“用这张”和“修改”两个按钮；只显示通过的；一键操作；不露技术词和命令行；导航是步骤条加进度矩阵。
11. **GPU 拉满**；出图卡死要有自动检测和自愈（项目方 10:4x 新报的问题，见 CHANNEL）。

## 2. 项目方在 PS 会话做的点选（已在 CHANNEL 10:06 写成 DECISION，请去重后正式编号）
画风 Leica/ARRI/Kodak；导航用步骤条加矩阵，恢复编辑器、剪辑器和资产页；定稿档开（要挂在共用验收之后）；灯光以剧本为准；镜头句和融合句都加；ep01 第 6 镜整集返修；出图并回 V1 producer；停 V1 旧 producer，起 V2 producer 和 night；停 bench2 和 bakeoff；退役 video10_srv；282 处改动先复审再出图；出图自动启动；多卡并行。

## 3. PS 侧在制和待办（等 MASTER-WSL 确认或改派）
| 项 | 状态 | 说明 |
|---|---|---|
| L-158 结构项自动转整集返修，ep02 出包（STRUCT-O，Opus） | 在制 | 已 CLAIM autoflow.py / autoflow_agent.py |
| G2 自审 + Fable 复审 | ✅ 已交付 | CHANNEL DELIVER；还有 6 个漏项文件请补进 cut B 清单 |
| ISS-b589 ① 写作链剩余的 V1 名字 | 部分完成 | HEADER-O 已清掉写手可见的规则和例句；还残留在 config/prompts/vqa_inspect.md、asset_sheet_inspect.md（看图提示词，可能让 V2 判图带偏）、tools/qa/writer_lints.py 等处 |
| ISS-b589 ② push_check tier 2：3 个 writer_out 文件（fenced JSON / 0 字节 .done） | 未做 | 会挡发版 |
| 项目方 10:4x：一键出片弹层右侧被截断，文案里有内部词 | 可接 | 前端 |
| 项目方 10:4x：GPU 出图卡死没有自愈逻辑 | 待分派 | 属于 producer / lanes（W1/W8 的区域） |
| sv18 遗留：run_chain 用 api 后端时直接写 P4（P1-A）、v1_leak 前作白名单（P1-B）、validate_qwen_script 模块级 _RUN | 待排期 | REVIEW-G2 |
| PS 侧交付和复审证据 | — | OVERSIGHT_LOG：REVIEW-A（两轮）、B、C、D、G2；GLOBAL-O/F 全局审查（REVIEW_GLOBAL_*.md）；PLAN_V2_MASTER v4（PS 写的，请 MASTER-WSL 合并或取代） |

## 4. 风险提示
- 两边曾经同时改过同一批文件（producer.py、asset_worker、sop_gate 等）。cut B 的复审要把 W 系列和 PS 系列的改动放在一起看。
- MASTER_PICTURE 里 L-154 和 L-155 有两组同号行，PS 写的那组作废，请 MASTER-WSL 清理。
- 记忆的索引和总纲已经在 PS 侧重建过（MEMORY.md、ns-final-studio-core.md）。如果和 WSL 侧的认知有冲突，以 MASTER-WSL 为准，请告知，我来同步。

CODER-PS 在等 MASTER-WSL 分派。
