# 角色手册：DIR 剪辑导演 / 审片

只评技术和剪辑：画面、运动、声音、调色、剪辑节奏。不评剧本内容和表演意图，也不做内容检测。

- **负责连接**：P10-P11（合成 → 审片）、P11-RETRY（审片 → 重出）、P8-P10（片段 → 剪辑节奏）
- **现在由谁做**：Autopilot。机器指标交给 `tools/ep02_director/review.py`；7 维判定交给 `tools/autopilot/director.py`，它按 `config/recipes/director_system_prompt.md` 判定，用本地 Qwen3-VL、外部网关或规则兜底。能不能交付由项目方定（delivery 闸门）。

## 输入
- 每镜视频，经过去抖和 skin guard 之后的版本；
- 合成成片和时间线 `data/episodes/epNN_*_iter_vN.mp4` / `.timeline.json`；
- RenderPlan 里的验收阈值，来自配方的 acceptance。

## 输出
- `data/ab/director/<名>/review.json`、`review.md`、`sheets/<镜>.jpg`（接触印样）、`overview.jpg`、`color_timeline.png`；
- 判定 JSON（`data/iterate_loop/<run>/director/verdicts.json`），格式见审片提示词末尾：verdict、7 维 scores、issues、action、confidence；
- 每版报告 `vN_review.md`，以及给人看的审片页 `data/review_pages/<集>/index.html`。

## 步骤
1. 逐镜机器指标：`.venv/Scripts/python.exe tools/ep02_director/review.py clips --name <名> S1=a.mp4 …`。整集用 `review.py episode <成片> <timeline> --name <名>`。
2. 拿指标对照配方验收阈值（`tools/iterate_loop/reviewer.py:failures`）。不过的，走规则表 `tools/iterate_loop/rules.yaml` 的阶梯。
3. 机器量不准的项交给审片模型看印样：鬼影 / 多肢、质感、接缝、嘴型。模型输出严格 JSON；不合格时重问一次，仍不合格就用规则兜底。置信度 <0.6 的只记录、不触发动作。
4. 判 fail 且动作是 reseed 的，iterate_loop 下一个 tick 会读到并重出（计入每镜 3 次的上限）；动作是 owner 的，标“待项目方”。
5. 有泛红标记时，用 `tools/ep02_director/red_trace.py` 把生成原片、去抖、调色、成片、关键帧放在一起逐帧追。
6. 收版：写 `vN_review.md`、`vN_director_queue.md`、审片页，停在 delivery 闸门。

## 判定标准（来源 `knowledge/rules/review.yaml`、`research.yaml` 的 K-REV-*，以及 `tools/ep02_director/rubric.md`）
- 7 维每维 ≥7 才算及格；任一维 <5，这一版不出门（K-REV-008）。
- 运动：静止占比 <50%，结尾定住 <0.5 s（K-REV-001）。卡顿：J4 ≥1.2 且 z ≥3 判为 4 帧一顿（K-REV-002）。
- 泛红：脸颊 a*p95 漂移 <6，a*≥25 的像素占比 <25%，红块 <1%（K-REV-003）。
- 身份：SFace 参考余弦中位 ≥0.30，镜内最低 ≥0.60；ArcFace 分 0.50 / 0.30 两档（K-REV-004、K-REV-R01）。

## 产生的规则放在哪里
- 新阈值、新判定写进 `knowledge/rules/review.yaml`（link 填 P10-P11）。
- 新的重出阶梯写进 `knowledge/rules/loop.yaml`（link 填 P11-RETRY）。
- 改完运行 `tools/knowledge/compile.py`，它会重新生成审片提示词和 rules.yaml。

## 什么时候需要人
- delivery 闸门；
- 判定是 owner 的镜头；
- 审片模型置信度低、只记录未动作的镜头，在审片页上人工看一眼。
