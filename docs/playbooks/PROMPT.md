# 角色手册：PROMPT 提示词 / 写作规则

只管格式和可实现性，不写剧情，也不评价内容。

- **负责连接**：P3-P4（剧本 → 分镜 / Shot Spec）、P4-P7（Spec → H3 提示词编译）
- **现在由谁做**：
  - 规则以 `config/script_chat_rules.md` 的附录 sysimpl-vN 和知识包 `config/recipes/writer_knowledge.md` 的形式，在写作模型每次调用时自动带上。
  - 校验是代码。
  - 返修由写作模型完成：`tools/autopilot/writer.py` 逐镜发【格式返修】，最多 2 轮。

## 输入
- 写作模型交来的剧本分镜 Markdown；
- 官方 H3 提示词指南（base-en / ref-en）。

## 输出
- 校验结果：
  - `ns_schema.shot_spec.missing_fields`（SS-*）
  - `ns_recipes.lint`（RL-*，其中 RL-T1–T7 是时间轴、视线、表情、衔接、节奏）
  - `ns_schema.llm_output_check`（台词逐字、无人名、锚点短语）
- 返修消息；
- 写作规则附录的新版本。

## 步骤
1. 写作模型交稿后，运行 `WR.selfcheck(稿, 集)`，执行严格格式校验、llm_output_check 和 Shot Spec 缺字段检查。
2. 有问题时，按镜分组，一镜发一次请求、只替换那一镜；集级问题最后整集修一次（`writer.repair_round`）。最多 2 轮，仍不过就整集停下（needs_writer），缺口写到 `writer_requests.md`。
3. 稿件盖规则版本章：`<!-- rules_version: rules_v2+sysimpl-vN -->`（`spec_import.stamp`）。盖了 v2 章的集，Autopilot 会把它加进 `config/recipes/timing_lint.json` 的 episodes_error，时间轴、分拍槽位、下镜缺失直接拦下。没盖章的旧稿记为 unknown，不按 v2 判。
4. 新的写法要求：加一条 `knowledge/rules/writer.yaml` 或 `prompt.yaml`，填 `writer_text` 和 `targets: [{kind: writer_prompt, section: …}]`，再运行 compile.py。知识包会自动更新，版本号随之变化。CHAINSPEC 的 `writer_prompt.py` 会把 link 等于该段、status 为确认或建议的条目拼进分段 prompt。

## 判定标准
- H3 三字段齐全，soundscape 必写。
- I2VA 正文没有 Picture 2。
- `</d>` 前要有句末标点。
- 每 1.5–2 秒一拍。
- 每拍写视线和表情；双人镜还要写对方的反应。
- 接力镜头要有“下镜”。
- 正文每秒约 18–25 个英文词。

## 产生的规则放在哪里
`knowledge/rules/prompt.yaml`（link P4-P7）、`writer.yaml` 和 `chain_v1.yaml`（link P3-P4）。

## 什么时候需要人
- 风格类决定，例如节奏快慢、口吻；
- 是否把独白放进 H3。
