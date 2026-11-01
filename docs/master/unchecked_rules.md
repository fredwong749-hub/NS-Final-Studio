# 无强制检查的规则（按 owner）

生成：`.venv/Scripts/python.exe tools/qa/iter_gate.py --list-unchecked`（2026-11-01 16:42）。共 128 / 391 条（来源 knowledge/rules/*.yaml；“有检查” = check 字段或 targets / loop 块）。

总调度 11-01 决定：这些规则标 `enforced: false`，继续作为指引生效、不降级为草案；各 owner 在 sweep 里逐条补 `check:`（测试 / 校验器 / gate 路径）后删掉 `enforced: false`。iter_gate 的 RL 项只对**新**规则缺检查判不通过。

| owner | 条数 | 规则 id（文件） |
|---|---|---|
| AUTOPILOT（ARCH，研究蒸馏） | 50 | K-REN-R01, K-REN-R02, K-REN-R03, K-REN-R04, K-REN-R05, K-REN-R06, K-REN-R07, K-REN-R08, K-REN-R09, K-REN-R10, K-REN-R11, K-REN-R12, K-REN-R13, K-REN-R14, K-REN-R15, K-REN-R16, K-REN-R17, K-REN-R18, K-REN-R19, K-REN-R20, K-REN-R21, K-PRM-R01, K-PRM-R02, K-PRM-R03, K-AST-R01, K-AST-R02, K-AST-R03, K-AST-R04, K-AST-R05, K-AST-R06, K-AST-R07, K-AST-R08, K-AST-R09, K-AST-R10, K-AST-R11, K-EDT-R01, K-EDT-R02, K-OPS-R01, K-OPS-R02, K-OPS-R03, K-OPS-R04, K-OPS-R05, K-OPS-R06, K-OPS-R07, K-OPS-R08, K-OPS-R09, K-OPS-R10, K-OPS-R11, K-OPS-R12, K-OPS-R13（knowledge/rules/research.yaml） |
| UIRSI | 23 | K-UI-001, K-UI-002, K-UI-003, K-UI-004, K-UI-005, K-UI-006, K-UI-007, K-UI-008, K-UI-009, K-UI-010, K-UI-011, K-UI-012, K-UI-013, K-UI-014, K-UI-015, K-UI-016, K-UI-017, K-UI-018, K-UI-019, K-UI-020, K-UI-030, K-UI-031, K-UI-032（knowledge/rules/ui.yaml） |
| AUTOPILOT（ARCH） | 12 | K-AST-001, K-AST-002, K-AST-003, K-OPS-002, K-AST-004（knowledge/rules/asset_ops.yaml）；K-REN-003, K-REN-013, K-REN-015, K-REN-016, K-REN-017, K-REN-018, K-REN-019（knowledge/rules/render.yaml） |
| IMGGEN | 11 | K-OPS-121, K-OPS-122, K-REV-121, K-REN-123, K-REV-122, K-AST-223, K-AST-221, K-AST-222, K-REV-124, K-REN-125, K-AST-252（knowledge/rules/render_imggen_s10.yaml） |
| INFRA | 7 | K-OPS-I01, K-OPS-I02, K-OPS-I03, K-OPS-I04, K-OPS-I05, K-OPS-I06, K-OPS-I07（knowledge/rules/ops_infra.yaml） |
| VIDEO10 | 7 | K-PRM-301, K-PRM-302, K-OPS-301, K-OPS-302, K-OPS-303, K-REN-301, K-REV-301（knowledge/rules/render_video_s10.yaml） |
| ASSETUX | 5 | K-UI-025, K-UI-026, K-UI-027, K-UI-028, K-UI-029（knowledge/rules/ui.yaml） |
| SERIES | 4 | K-AST-201, K-AST-202, K-AST-203（knowledge/rules/asset_series10.yaml）；K-WRT-210（knowledge/rules/writer_series10.yaml） |
| UIAUDIT | 4 | K-UI-021, K-UI-022, K-UI-023, K-UI-024（knowledge/rules/ui.yaml） |
| AUTOPILOT（剪辑 / FIX） | 2 | K-EDT-007, K-EDT-015（knowledge/rules/edit.yaml） |
| PROMPT | 1 | K-PRM-011（knowledge/rules/prompt.yaml） |
| AUTOPILOT（审片 / DIR） | 1 | K-REV-010（knowledge/rules/review.yaml） |
| CHAINSPEC | 1 | K-WRT-008（knowledge/rules/writer.yaml） |
