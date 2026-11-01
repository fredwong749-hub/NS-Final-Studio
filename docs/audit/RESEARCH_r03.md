# AUDIT · RESEARCH 收尾复核 r03（2026-11-01 18:10–18:18，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG “17:5x RESEARCH 收尾（L-087）”。机读版：data/qa/audit/RESEARCH_r03.json

## 结论：通过

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | L-087 进账本 | docs/master/MASTER_PICTURE.md 第 120 行 L-087，有原话和 AskUserQuestion 选项“R0 现在这样” | 通过 |
| 2 | D-IMG-87a/b/c 可检查，并且已全量同步 | owner_decisions.yaml 第 401、411、417 行；decision_check 18:03：除 D-VQA-02（预期）以外全部 ✅；decision_propagation：D-IMG-87a ✅ 已全量同步 | 通过 |
| 3 | 不采纳的规则标 ⤴，原文可追溯 | K-REV-X01 / K-REN-X02 / K-PRM-X04 已从 research_realism.yaml 移到 knowledge/archive/superseded_20261101.yaml，文件头写明了 L-087 和移动的位置；research_realism.yaml 只剩 K-WRT-X05（已补 lint: [QW-W9]）；X03 在 inbox | 通过（r01 的两条规则问题都已关闭） |
| 4 | RL01–RL03 降为只记录 | realism_lint.py 第 42、48、62 行 level=record，文件头写了 L-087 | 通过 |
| 5 | GPU 档取消，scope=ab 代码保留 | gpu_plan.json / realism_gpu_ab.py 标 ⤴；scope=ab 的隔离在 RESEARCH_r02 已经核对过 | 通过 |
| 6 | 测试 / compile | test_realism_lint 包含在 18:05 的 84 条定向测试里，全过；compile --check 18:03 OK（414 条） | 通过 |

## 留给总调度的一点
- 契约 Q4（lap_full ≥175）量的其实是 USM 锐化强度（RESEARCH_r01 §5）。L-087 定了 S★ 不改，所以 Q4 现在照常可用。以后只要有人改锐化参数，Q4 会跟着整体漂移。建议在 D-IMG-87a 的说明里加一句“改锐化必须同时重标 Q4”（交 REFLOCK）。
