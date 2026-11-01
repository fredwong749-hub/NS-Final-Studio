# 角色手册：UIRSI 竞品与 UI 迭代

- **负责连接**：P10-P11（审片页）、P11-P12（交付闸门页）
- **现在由谁做**：Autopilot 生成审片页；画布 UI 的改动在 `apps/web`，由 UI agent 负责，项目方验收。竞品研究的结论按知识库流程写成规则。

## 输入
- 项目方对画布和审片体验的反馈；
- 竞品研究 `docs/ep02_iter/competitor_flows.md`；
- UI 审计材料 `docs/ui-audit/`。

## 输出
- 审片页 `data/review_pages/<集>/index.html`：逐镜状态、配方、出片次数、审片判定、接触印样，以及闸门操作说明；
- UI 改进清单和实现，在 apps/web。

## 步骤
1. 每版收版后，Autopilot 自动生成审片页并打开（`run.py` 的 review_page）。
2. 项目方在审片页上：
   - 认可整版就运行 `run.py approve --gate delivery`；
   - 某镜不行，就在 verdicts.json 写 fail + reseed，然后再 run；
   - 之后这一步会做成页面上的一键按钮，由 UI agent 实现。
3. 竞品做法（best-of-k、按场预演、草稿档 → 成片档、合镜）先写成 `knowledge/rules/research.yaml` 的建议条目，再由 ARCH / LAB 评估是否落地。

## 判定标准
- 项目方一眼就能看到哪些镜要他处理；
- 闸门操作不超过一步。

## 产生的规则放在哪里
`research.yaml` 里 link 为 P10-P11 / P11-P12 的条目。

## 什么时候需要人
- 所有 UI 验收；
- delivery 闸门。
