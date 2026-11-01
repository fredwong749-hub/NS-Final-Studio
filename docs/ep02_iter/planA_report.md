# 方案 A 报告：官方 Ref2VA + 项目方挑定脸部裁切（V2，2026-10-31 21:45 收尾）

**状态：中止，没有合成 planA。** 21:35 项目方指令"6 张卡全部转去生成新 10 集剧本的图片"，ep02 实验停止。按总调度要求：loop（ep02_v2）已暂停，fanout 已停，我在 :8800 的 4 个排队 / 在跑作业已取消（0415862b4bd9 S2、7c5818709691 S1 排队；9c7c4bd0dd70 S4、a0d99d8fed35 S3 在跑），gpu33:0/1/3 ComfyUI 队列已空（21:40 核对）。

只评技术与剪辑，不评剧本内容。

## 1. 配方

| 项 | 值 | 来源 |
|---|---|---|
| 双人镜 | 配方 `two_person_ref2va`（ref2va pruned int8，24 步 euler/simple，shift 12/3，cfg 1，match，官方 ref-en 六段），**纯 Ref2VA：不放定稿首帧、不 AddGuide**（20:20 起） | lab_recipes.md 批 2 / 批 4；K-REN-011 |
| 身份图 | 项目方挑定设定图的脸部裁切：林晚 A-s202、顾沉 s101、陈宇 s202（`data/assets/identity_refs/*/*_face_ref2va.png`，manifest by=owner） | CONSIST；配方 `ref2va.identity_crops` |
| 单人镜 | 新配方 `solo_ref2va`（不自动选，loop `recipe_override` 指定）——S1 在排队时中止，未出片 | — |
| 长镜头 | S8 基模 24 + 只给首帧（gpu36:2，旧提示词）；S11 在排队时中止 | — |
| 后处理 | 去抖（dejudder，bt709）；R-RED 时加 skin_guard | 配方 `_base.post` |
| 道 | 只用 gpu33:0/1/3（20:45 起 gpu33:3 交方案 C，只用 0/1） | 总调度 |
| 提示词 | 19:27 首批 = 旧剧本提示词（E5 multiframe，旧林晚裁切）；20:10 起 = PROMPTv2（20:08 正式导入，按秒分拍） | — |

## 2. 每镜结果（机器指标；sheet 在 data/ab/director/<review>/sheets/）

| 镜 | 版本（take） | 组 | 静止 | 脸颊 a*≥25 占比 | a* 漂移 | SFace 对参考 | J4 | 硬切 | 未过项 | GPU 秒（render_s） | v1 同镜 SFace |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S2 | **12（fanout seed+10）** | 新 | 0.263 | **0.033** | 3.09 | 0.504 | 1.069 | 0 | **无（全过）** | 2019 | 0.356 |
| S2 | 11 | 旧 E5 | 0.083 | 0.154 | 18.5（sg 后） | 0.362 | 1.068 | 0 | 漂移、self | 2643 | |
| S3 | 7 | 旧 E5 | 0.234 | 0.064 | 6.15 | 0.542 | 1.847 | 1（0.2 s） | 漂移、self | 2636 | 0.362 |
| S4 | 9 | 新 | 0.538 | 0.039 | — | **0.718** | — | 0 | 静止 54%、self 0.334 | 2004 | 0.457 |
| S4 | 8 | 旧 E5 | — | — | 16.7 | — | — | 3（0.4/2.4/4.9 s） | 结尾定住 1.4 s、漂移、self | 2002 | |
| S5 | 4 | 旧（纯 Ref2VA） | 0.005 | 0.293 | 17.4 | **0.783** | 1.055 | 0 | 漂移、泛红、self | 2536 | 0.53 |
| S6 | **10** | 新 | 0.173 | 0.075 | 6.46（sg 后） | 0.678 | — | 0 | 漂移超 0.46（导演判过） | 1975 | 0.482 |
| S6 | 11（fanout seed+10） | 新 | 0.154 | 0.076 | 7.79 | 0.666 | 1.055 | 0 | 漂移 | 1975 | |
| S8 | 5 | 旧（基模 24，gpu36:2） | 0.017 | 0.272 | 12.4 | 0.264 | 1.131 | 1（1.2 s） | 漂移、泛红、身份 | 5720 | 0.423 |
| S10 | 6（fanout seed+10） | 新 | 0.051 | 0.055 | 9.99 | 0.289 | 1.066 | 0 | 漂移、身份（陈宇裁切） | 1961 | 0.176 |
| S1/S7/S9/S11 | — | — | 排队中被中止，没有新版本 | | | | | | | | |

GPU 时间：Ref2VA 158 帧（6.6 s）768×1344 单段 24 步在 gpu33 3090 上 **1961–2643 s / 条（33–44 min）**，上传 3–30 s；S8 294 帧基模 24（gpu36:2 novram）5720 s。

剪辑导演判定（data/iterate_loop/ep02_v2/director/verdicts.json）：S6 take 10 通过（漂移 6.46 只超 0.46，占比 0.075 属正常肤色，印样无泛红、无硬切）。

## 3. 结论（每条带样本量）

1. **纯 Ref2VA + 项目方脸部裁切 + 新提示词：身份和泛红明显好于 v1。** SFace S2 0.356→0.504、S4 0.457→0.718、S6 0.482→0.678、S10 0.176→0.289；cheek_red 全部 ≤0.076（v1 S2/S3/S4 0.42–0.51）。样本：4 镜各 1–2 seed。S2 seed+10 一版全部验收项通过。
2. **E5 multiframe（定稿首帧 + AddGuide）不行**：旧组 S2/S3/S4 self 余弦 0.33–0.43、漂移 6–21、S4 中途跳切 3 处。和 LAB 批 4 一致 → 已改纯 Ref2VA。样本 3 镜。
3. **按秒时间码（`At 00:SS.mmm`）在 Ref2VA 下没有造成硬切**：新组 6 条（S2 t12、S4 t9、S6 t10/t11、S10 t6）0 处硬切；跳切只出现在旧组（无时间码）。样本 6 条 / 4 镜，已写进 K-PRM-I01 证据（PROMPT 代记）。
4. **还没解决**：S4 新版后半段静止（54%）；陈宇（S10）身份只有 0.289；a* 漂移在 Ref2VA 上仍常见 6–10（占比低、肉眼不红，阈值 6 对 Ref2VA 偏严，见 backlog）。
5. **代价**：纯 Ref2VA 构图不跟定稿首帧（S6 印样为中景坐姿，与 v1 首帧不同）——"首尾帧一致"要求下要项目方 / 剪辑导演判可不可接受。

## 4. 剪辑规则（已做成可测规则，未在 planA 成片上验证）

- `post.edit_rules`：max_shot_s 6→4.5；pace_tighten（对白前 0.3 s、句后 0.5 s、无对白镜 ≤4 s 取运动量最大段、每镜 ≥3 s、独白镜不动）；J-cut jl_cut_s 0.3。tests/test_v2_pace.py。
- v1 同一批 take 试合成（尾留 0.4 s、无下限）：81.4 s → 52.5 s（-35%），已调参（data/ab/v2_iter/pace_test/）。
- `post.voiceover_drop.per_episode {"2":[8,11]}`（项目方原话"A. 去掉"）。
- 相邻镜调色匹配、48 fps 插帧：未做，见 LEARNING_BACKLOG。

## 5. 文件

- loop：data/iterate_loop/ep02_v2/（state.json、events.jsonl、results/、plans/、post/、director/verdicts.json）
- 并行 seed：data/ab/v2_iter/fanout/manifest.json（tools/ep02_iter/fanout.py）
- 硬切：data/ab/v2_iter/cut_check.json（tools/ep02_iter/cut_check.py）
- 选版：data/ab/v2_iter/planA/selection.json、sources.timeline.json（tools/ep02_iter/planA_sources.py；未合成）
- v2a：data/episodes/ep02_v2a.mp4、docs/ep02_iter/v2a_review.md
