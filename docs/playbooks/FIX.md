# 角色手册：FIX 止血修复 / 剪辑规则

- **负责连接**：
  - P4-P7：提交前 lint 闸门
  - P8-P10：合成只取通过版本
  - P9-P10：剪辑与声音规则
- **现在由谁做**：都是代码，没有判断步骤。新问题的修法先在审片里归因（CHAINSPEC 的 attribute_bug），再变成规则。

## 输入
- chain_audit 和审片报告里点名的系统缺陷；
- 项目方的剪辑要求，例如整集统一 BGM、对白用 H3 原声。

## 输出
- 代码修复（render_router、assemble、lint），带单测；
- `config/render_quality.json` 的 post 规则。改法只做局部编辑，知识库对这个文件只读校验。

## 步骤
1. 提交前 lint：`ns_render.h3_video.submit_lint`（I2VA 只给首帧时，正文里不能有 Picture 2，H3 结构要完整）。配方图走 `ns_recipes.lint` 和 `ns_api.recipe_render.validate_graph`。
2. 合成：`.venv/Scripts/python.exe tools/assemble_episode.py epNN --sources-from <loop 写的 vN_sources.timeline.json> --variant iter_vN --dialogue-source h3 --h3-music duck_under_bgm`。
   - 只用 QC 通过的版本；
   - 剪掉定住段；
   - 统一 bt709；
   - skin guard；
   - 独白溢出判失败。
3. 依赖变更标脏：`ns_agent.asset_revs` 的依赖键，包括 identity、loraslot、preset、vbase、vlora、voice、registry。依赖变了，旧版本读出来时会显示“依赖已更新：…”。
4. 每个修复都要有测试，并跑一次全量 pytest。

## 判定标准
- 修复不能改变已定稿内容，也不能悄悄混用新旧素材（K-EDT-009）。
- 响度 −14 LUFS ±1，真峰值 ≤−1 dBTP（K-EDT-007）。
- 切点处跳变 ≤10 dB（K-EDT-005）。

## 产生的规则放在哪里
`knowledge/rules/edit.yaml`。link 填 P8-P9、P9-P10、P8-P10 或 P11-P12。如果对应 render_quality 的键，用 `targets: {kind: render_quality, path, value}`。

## 什么时候需要人
需要撤销已定稿、改变默认配方、重启 API 的事，交总调度决定。
