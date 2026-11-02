# 写作后端 claude_agent：写手 / 评审 agent 接口说明（HOLLYWOOD r9，L-109）

> 项目方 11-02 03:3x 原话：“Claude后面写剧本还是你来写，用那个API太贵了，测试阶段都是用你的，之后上线再用外面的API”；“写剧本你可以用fable5.1来写”。
> 总调度派：写作链加可切换后端 `writer_backend: claude_agent | api`（config/llm_providers.json，默认 claude_agent，上线切回 api）。
> claude_agent 模式下 autoflow（tools/script_rsi/autoflow.py）不调任何写作 / 评审 API，只出**任务包**、收**产物**、跑代码判定和闸门。
> 写手（SCRIPTWRITER，Fable 5.1）和评审 agent 分开：写手只做 role=writer 的包，评审只做 role=reviewer 的包。

## 1. 任务包

路径：`data/pipeline/runs/<run>/writer_tasks/<step>.json`（第二季 `<run>` = `series10_s2`）。一个 step 一个包，autoflow 每推进一步写一个新包。

```json
{
  "schema": "nsfs.writer_task/1",
  "run": "series10_s2",
  "step": "P4_ep06",                 // 见 §3 step 命名
  "role": "writer",                  // writer | reviewer
  "episode": 6,
  "link": "P3-P4",                   // P0-P1 / P1-P2 / P2-P3 / P3-P4 / patch / facts / factcheck
  "system": "……完整系统提示词……",    // 已拼好：Hollywood 模板原文 + writer_knowledge 全部 K-WRT（含 K-WRT-804 运镜）+ 27 条代码判定 + 运镜词表 + 内容边界
  "user": "……本步的完整输入……",      // 已拼好：上一段产物 / 事实表 / 逐行编号的稿 / 要修的失败项（每条原文）/ 校验器报的问题
  "inputs": ["data/pipeline/runs/series10_s2/P3_ep06_screenplay.json", "…"],   // 只读参考
  "output": {"path": "data/pipeline/runs/series10_s2/writer_out/P4_ep06.md", "format": "markdown_episode"},
  "content_rules": "全部人物成年（≥22 岁）、自愿、虚构；暧昧和张力可以写，露骨的性描写不写；亲密镜写成占位……",
  "attempt": 1,
  "created_at": "2026-11-02T03:50:00",
  "status": "open"
}
```

`system` + `user` 就是 API 模式下发给写作模型的同一份请求，照着写即可；不用再自己找规则文件。

## 2. 产物与通知

1. 把产物写到 `output.path`（目录 `writer_out/`），**不要**直接写或覆盖 `P2_epNN_outline.json` / `P4_epNN.md` / `P4_epNN.final.md` 这些正式文件——autoflow 校验通过后自己落正式文件（与 API 模式同名同格式）。
2. 写完再建一个空的标记文件 `<output.path>.done`（例：`writer_out/P4_ep06.md.done`）。没有 `.done` 的产物 autoflow 不读（防止读到写了一半的文件）。
3. 交稿后只建 `.done`，等系统推进，不要自己跑命令（总调度 11-02，根因模式 1“双入口”）。推进只有两个入口：网页的 /api/script-autoflow/{run}/repair，和 .done 守护（`autoflow.py watch`，看到 .done 自动推进）；每次推进都记进 `<run>/autoflow.log`，标来源 cli / web / daemon。写作包里不再带 advance_cmd。
   autoflow 读产物 → 校验 / 代码判定 → 过了就落正式文件并写**下一个**任务包；没过就写同一 step 的返修包（`attempt` +1，`user` 里带上没过的原因）。
4. 状态看 `data/pipeline/runs/series10_s2/autoflow_epNN.json`：`awaiting` 字段写着现在在等哪个 step、谁（writer / reviewer）。页面 #/script-create?new=1 的 AutoflowPanel 同步显示。

## 3. step 命名与产物格式

| step | role | 什么时候出 | 产物格式（output.format） | 样例 |
|---|---|---|---|---|
| `P2_epNN` | writer | 新集（ep06–10）：单集大纲 | `json`：nsfs P2 大纲 JSON | config/pipeline/examples/P2_outline.json |
| `P3_epNN` | writer | 单集剧本（台词 / 独白 / 场次） | `json`：nsfs P3 剧本 JSON | config/pipeline/examples/P3_screenplay.json |
| `P4_epNN` | writer | 分镜剧本 | `markdown_episode`：从 `## epNN《标题》` 开始的一集 Markdown，字段同第一季 | config/pipeline/examples/P4_episode.md |
| `P4_epNN_rK` | writer | P4 没过校验（P4 阻断）时的返修 | 同 P4（整集重交） | — |
| `patch_epNN_K` | writer | 代码判定 / 导入阻断 / 事实偏差的逐行补丁（ep02–05 返修就是这一种） | `patches_json`：`{"patches": [{"line": 行号, "new": "整行新文本"}]}`，行号用包里 `user` 给的 L 编号 | — |
| `facts_epNN` | reviewer | 本集事实表（从 Brief + P1 + 本集 P2 / P3） | `facts_json`：hollywood_facts.md 任务 A 的 JSON | config/prompts/hollywood_facts.md |
| `factcheck_epNN_K` | reviewer | 整集事实核对（收尾前） | `factcheck_json`：任务 B 的 `{"ok", "deviations"}` | 同上 |

- P1 故事线第二季已有（`P1_storyline.json`），不用重写。
- ep02–05：P2 / P3 / P4 都已有，只出 `patch_epNN_K`（失败项见各集 `autoflow_epNN.json` 的 `rubric_code_fail` 和 code 段 detail）。
- ep06–10：依次出 `P2_epNN` → `P3_epNN` → `P4_epNN` → （补丁）→ `factcheck`。
- 打分：测试期只用代码判定（27 条，免费）；判断类条目（7 评审）先缓，`score` 段显示代码判定满足条数 / 27。

## 4. 内容边界（每个包的 content_rules 原样带上）

- 全部人物成年（≥22 岁）、一切亲密情节双方自愿、人物均为虚构。
- 暧昧和张力可以写；**露骨的性描写不写**。
- 亲密镜写成占位：该镜的 img / motion / H3 只写非露骨的画面（构图、视线、手、呼吸、环境），并在镜头块里加一行 `**H3校验**：本地生成（亲密镜占位）`——这类镜头的画面只在本地生成。
- 不改第一季已定的剧情事实和人物设定（身份、名字、年龄、发色发型、脸 = 林晚 L-086 身份脸、5 厘米透明水晶甲、人物关系、已发生剧情）；**每集服装 / 造型不是事实**，以本集造型行为准（K-WRT-H10）；同一集里没写换装却变衣服算缺陷。
- 缺信息标“未提供”，不编造。

## 5. 规则与模板位置

- Hollywood 模板原文：`config/prompts/hollywood_writer.md` §一（红线：不改给定的剧情事实和人物设定；缺信息标“未提供”）。
- 全部写作规则：`config/recipes/writer_knowledge.md`（含 K-WRT-H06 / H08 / H10、K-WRT-801–804 运镜）。
- 运镜词表：`config/director/camera_moves.yaml`（只写 enabled 的名字，每镜一种，“小幅”，不写速度词；复合运镜按词表 split 拆两镜）。名单会随 Pika A/B 变化，以包里 `system` 给的为准。
- 代码判定 27 条：`config/prompts/hollywood_rubric.json` + `tools/script_rsi/rubric_code.py`；导入闸门 = 代码判定 0 失败 + P4 阻断 0 + 事实核对 0 偏差。
