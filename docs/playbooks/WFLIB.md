# 角色手册：WFLIB / CIVIT / RHUB 工作流学习

- **负责连接**：P7-P8（配方 → 视频片段）
- **现在由谁做**：解析和出报告是代码，只读解析 JSON，不执行工作流。哪些结论进配方，按知识库流程处理：写成规则，然后跑 compile 校验。社区权重的许可由人登记。

## 输入
- 新到的工作流目录，来源包括项目方给的、Civitai、RunningHub、GitHub；
- 各机器的模型清单（`data/ab/owner_workflows/_meta/*.tsv`）和节点清单。

## 输出
- `parsed.json`：每个工作流的模型 / LoRA / 采样 / shift / SplitSigmas / 放大器 / 分辨率 / 帧长 / 注意力 / 参考槽位 / 后处理，以及缺哪些权重和节点；
- 报告 md，例如 `docs/ep02_iter/workflow_library.md`、`civitai_study.md`、`runninghub_study.md`。

## 步骤
1. 运行 `.venv/Scripts/python.exe tools/autopilot/run.py learn-workflows --dir <目录>`。它会依次跑 `tools/workflow_lib/parse.py` 和 `report.py`，报告写到 `docs/workflow_learn/<目录名>.md`。
2. 拿报告和现有配方对比参数分布，找出我们没有用过的做法，例如两段式、PDD、续接。
3. 能落地的结论：
   - 写成 `knowledge/rules/research.yaml` 条目，标 status 建议或待验，并写 experiment 编号；
   - 需要实测的交给 LAB；
   - 社区权重写进 `services/recipes/recipes/community_pending.yaml`，标“待许可登记”。

## 判定标准
- 只采纳有源码、官方文档或实测支持的参数；单人报告标 low。
- 3090 显存约束：第二段 ≤1.03 MP（K-REN-010）。

## 产生的规则放在哪里
`knowledge/rules/research.yaml`、`render.yaml`，link 填 P7-P8。

## 什么时候需要人
- 许可登记；
- 下载大权重、装节点包这类要花时间和磁盘的事。
