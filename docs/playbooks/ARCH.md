# 角色手册：ARCH 系统架构 / 配方引擎 / 出片 Loop

- **负责连接**：P4-P7（Spec → H3 提示词编译）、P6-P7（首帧 → 配方）、P7-P8（配方 → 视频片段）、P11-RETRY（规则阶梯）
- **现在由谁做**：全部是代码；判断规则来自知识库。

## 输入
- Shot Spec（`packages/schema/ns_schema/shot_spec.py`，由 `services/recipes/ns_recipes/spec_import.py` 从剧本 Markdown 解析）；
- 配方 `services/recipes/recipes/*.yaml`，每个参数都带 provenance；
- 写回层 `config/recipes/learned.yaml`。

## 输出
- RenderPlan：确定性的 ComfyUI API 图、提示词、验收阈值、plan_hash；
- 出片 Loop 的状态、事件、结果，在 `data/iterate_loop/<run>/`；
- 每版的 `vN_review.md`。

## 步骤
1. 选配方：`ns_recipes.selector.select`。依据是 match 和 priority，再叠加 overlay（夜景、泛红风险）。
2. 编译：`ns_recipes.compiler.compile_shot`（纯函数，同输入同哈希），再跑静态校验 `ns_recipes.lint`。
3. 出片 Loop：`.venv/Scripts/python.exe tools/iterate_loop/loop.py start|run|status|next-version --run-id <id>`（dry-run 加 `--dry-run`）。
   - 6 道分配，长镜头只派 gpu36:2；
   - 审片后按 `rules.yaml` 的阶梯处理，每次只改一个维度，每镜最多 3 次；
   - 收版时合成并写回。
4. 知识库：`tools/knowledge/compile.py [--check] [--episode N] [--inbox]`。它负责校验，检查和配方、render_quality、写作附录是否一致，并生成 rules.yaml、写作知识包、审片提示词。

## 判定标准
- 每个配方参数都有 provenance（`ns_recipes.cli validate`）；
- 知识库一致性检查 0 处不一致；
- 全量 pytest 通过。

## 产生的规则放在哪里
`knowledge/rules/render.yaml`（P7-P8）、`loop.yaml`（P11-RETRY）。

## 什么时候需要人
- 许可登记；
- 改默认配方（总调度）；
- API 重启后打开图透传（`--graph-passthrough`）。
