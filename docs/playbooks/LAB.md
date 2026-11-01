# 角色手册：LAB 配方对照实验

- **负责连接**：P7-P8（配方 → 视频片段）、P10-P11（打分）
- **现在由谁做**：
  - 实验提交和打分是代码，入口在 `tools/lab_ep02/`。
  - 开不开实验由总调度决定，因为要占 GPU。
  - 结论写进知识库后，配方自动对齐；自动迭代 Loop 也会通过写回机制自己“做实验”，即同一调整出现 ≥5 次就升级。

## 输入
- 要对照的配方：通常是配方 status=待验 的条目，或 `h3_comfy_expert.md` §8 的 E1–E12；
- 同一镜、同一张定稿首帧、同一份提示词、同一个 seed。一次只改一个变量。

## 输出
- `data/ab/lab/…` 下的视频；
- `scores.json` / `scores.md`；
- 接触印样 `<名>_sheet.jpg`；
- `docs/ep02_iter/lab_recipes.md` 的批次表。

## 步骤
1. 写计划 JSON：`{"lanes": {"<comfy url>": [["<名>", "<脚本>", 参数…]]}}`。脚本可以是 `ref2va_run.py`、`fl2va_direct.py`、`planb_run.py`。
2. 按道串行跑：`.venv/Scripts/python.exe tools/lab_ep02/lab_queue.py plan.json`。生产优先，每道同时只占 1 个。
   - 经 :8800 提交时用 `lab_runner.py submit <label> <shot> <gpu> '<json>'`，再用 `lab_runner.py watch`。LAB 版本会自动撤回“当前版本”，不会被定稿。
3. 打分：`.venv/Scripts/python.exe tools/lab_ep02/lab_score.py <out_dir> name=path.mp4 …`。指标包括运动、J4、硬切、泛红漂移、身份。
4. 写结论：每条结论加一条 `knowledge/rules/<域>.yaml`。写清证据文件、≤30 字原话、置信度；配方参数用 `targets: {kind: recipe, …}` 指定。然后改配方 YAML（带 provenance），并运行 `tools/knowledge/compile.py`，它会检查配方和知识库是否一致。

## 判定标准
- 只看像素指标，不看内容。
- 结论要有对照组（同 seed、同首帧）。只有 1 镜对照的结论写成 status: 建议，不改默认值（例如 K-REN-R12 kitchen 注意力）。
- 换了关键帧，同一个 seed 的结果不可比（K-REN-009）。

## 产生的规则放在哪里
`knowledge/rules/render.yaml`、`research.yaml`，link 填 P7-P8；需要 A/B 的写 `experiment: E<n>`。

## 什么时候需要人
- 开实验（要花 GPU）；
- 社区权重的许可登记（status 待许可登记）。
