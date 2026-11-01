# 角色手册：CHAINSPEC 链条契约 / 上游写作

- **负责连接**：P0-P1、P1-P2、P2-P3、P3-P4（写作 LLM 段），以及 P11-RETRY（审片问题归因）
- **契约**：`config/pipeline/chain.yaml` 和 `docs/PIPELINE_CHAIN.md`。每个连接规定格式、必须做 / 禁止做、校验器、闸门。
- **现在由谁做**：
  - 写作由外部写作网关完成，按 `config/pipeline/prompts/<link>.md` 加知识库条目组装 prompt；
  - 校验和返修是代码，在 `tools/pipeline/run_chain.py` 里；
  - 归因是代码，在 `tools/pipeline/attribute_bug.py` 里，确定性执行，不调用 LLM。

## 输入
P0 brief，格式 `nsfs.brief/1`，样例在 `config/pipeline/examples/P0_brief.json`。

## 输出
- `P1_storyline.json`、`P2_epNN_outline.json`、`P3_epNN_screenplay.json`、`P4_epNN.md`（剧本分镜 Markdown，可以直接导入）；
- 每个产物旁边有 `.report.json`，另外还有 `prompts/`、`raw/` 和记账文件 `data/pipeline/ledger.jsonl`。

## 步骤
1. Autopilot 的 P0-P1 段调用 `run_chain.run(brief, 集, out_dir, upto="P4", budget=…)`，一次跑到 P4。已经存在且能过校验的产物会复用，不重复花钱。
2. 每段都是：组装 prompt → 调用写作网关 → 校验 → 不过就带着错误重写（轮数见 chain.yaml）→ 仍不过就标 needs_writer，整集停下。
3. P4 落稿时盖规则版本章：`spec_import.stamp`。
4. 审片或项目方反馈的问题：运行 `.venv/Scripts/python.exe tools/autopilot/run.py report-bug --run-id <id> --episode N --symptom "镜头切换生硬"`。它会调用 attribute_bug，把问题归因到某个连接，判断是已有规则还是缺规则，并把规则草案写进 `knowledge/inbox/`。
5. 草案由总调度确认后，移进 `knowledge/rules/`（原稿留在 `knowledge/inbox/confirmed/`），再运行 compile.py。

## 判定标准
- 产物必须通过 chain.yaml 里该连接的校验器；
- 不超预算（`--budget-usd`）；
- 不写剧情评价。

## 产生的规则放在哪里
`knowledge/rules/chain_v1.yaml` 等。link 用连接 id，比如 P3-P4。

## 什么时候需要人
- 可选闸门：storyline、单集大纲，默认关，用 `--gate-storyline` / `--gate-outline` 打开；
- 规则草案确认；
- 预算。
