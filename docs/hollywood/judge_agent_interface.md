# 判断类条目独立评审：任务包格式（总调度 11-02）

测试期用一个独立的 Claude agent 当评审，它和写手（SCRIPTWRITER）、HOLLYWOOD 都分开。口径按 config/prompts/hollywood_judge.md：§三 清单、§六 输出格式、r6 只判非代码条目。同一稿评 3 次，3 份总分的总体标准差 σ ≤ 1 才算稳定。评审 agent 由总调度派。

## 出包 / 收包
- 出包：`.venv/Scripts/python.exe tools/script_rsi/judge_agent.py pack --run-dir data/pipeline/runs/<run> --episodes 1-10 [--reps 3]`
- 收包：`.venv/Scripts/python.exe tools/script_rsi/judge_agent.py collect --run-dir data/pipeline/runs/<run> --episodes 1-10 [--write-score]`
  - 结果写到 `<run>/judge_out/judge_epNN.result.json`。
  - 加 `--write-score` 时，稳定的结果追加到 data/rsi/scores.jsonl（line=script_judge）。

## 任务包 `<run>/judge_tasks/judge_epNN_rK.json`（schema nsfs.judge_task/1）
| 字段 | 含义 |
|---|---|
| run / episode / rep / reps | 剧、集、第几份（1..reps） |
| role | 固定 judge |
| base_sha | 出包时这一集稿的 sha；稿变了这份作废，要重新 pack |
| judge_md / items | 口径文件；本次要判的条目 id（`<维度>#<条>`，代码条目不在内） |
| system / user | 评审的 system 提示词（hollywood_r5.judge_system_r6）和请求（judge_user：本集镜头块） |
| rules | 独立作答：不看别的 rep、不看写手自检；met=true 必须附逐字证据 |
| output.path / output.done_marker | 产物路径 `<run>/judge_out/judge_epNN_rK.json`，写完再建 `.done` |
| collect_cmd | 收包命令 |

## 产物（评审 agent 写）
只写一个 JSON，格式按 hollywood_judge.md §六：
`{"items": {"<维度>": [{"id": 1, "met": true, "evidence": "镜头块原文", "why": "…"}]}}`

## 打分与稳定性（judge_agent.collect）
- 每份单独算 50 分制总分。一条算满足，要同时满足两点：代码条目由 rubric_code 判过（如果这条有代码判定）；判断条目这一份评审判了 met（如果这条要评审判）。每维至少 1 分，和 score_r6 一致。
- met=true 但证据在镜头块里逐字找不到，按不满足处理（hollywood_r5.parse_evidence）。
- 3 份都交齐且 σ ≤ 1，结论是 stable；σ > 1，结论是 unstable，这一稿的判断分不采用；不到 3 份是 waiting。
- 判断条目按多数合成一份判定，写在 llm_majority 字段。
