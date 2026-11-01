# ep02 v2a 审片（V2，2026-10-31 18:15）

- 成片：`data/episodes/ep02_v2a.mp4`（81.375 s，1080×1920，**PREVIEW**：S8 独白溢出 + 无 gpu3 qa.json）；时间线 `data/episodes/ep02_v2a.timeline.json`
- 审片：`data/ab/director/v2a/review.md`、`sheets/*.jpg`、`overview.jpg`、`color_timeline.png`
- 合成命令：`tools/assemble_episode.py ep02 --allow-laptop-video --sources-from data/episodes/ep02_v1.timeline.json --out data/ab/v2_iter/assemble_v2a`（产物复制为 ep02_v2a.*；日志 `data/ab/v2_iter/assemble_v2a/assemble.log`）

## 1. 这一版是什么

用 v1 **同一批 take**（`--sources-from` v1 时间线），按当前合成规则重出。对比 v1 的 settings，**唯一不同是 skin_guard：false → true**。
原因：v1（17:39）合成时 FIX 的剪定住段 / >6 s 拆刀 1.15× / 0.12 s 交叉淡化 / 环境底噪 / 溢出判失败 / bt709 / duck_under_bgm 已经生效（v1 时间线 settings 里都有），只有 skin_guard 默认开是 17:51 之后改的。所以 v2a 实际测的是“skin guard 单项”。

### 关于“只用合格 take”
按 `take_policy=locked_qc`，ep02 11 镜**没有一镜有合格定稿视频**：S3 定稿 v4 是运动质检 fail，其他 10 镜没有视频定稿。严格模式合成会是 11 张静帧，没有意义。
系统里没有“质检通过（非定稿）”的 CLI 开关（`post.edit_rules.allow_unlocked_qc_pass` 默认 false，注释写明要项目方 / 总调度定），所以 v2a 走 `--sources-from`（timeline 标 `take_policy: sources_override`），输出本来就是 PREVIEW（不生成 ep02_final / ep02 别名）。**没有替项目方定稿任何镜头。**

按严格规则，下面这些镜会被标缺（v2a 用的版本及其运动质检）：

| 镜 | v2a 用的版本 | 运动质检 | 定稿 |
|---|---|---|---|
| S1 | v3 official_base | pass | 无视频定稿 |
| S2 | v6 official_base | warn 动作偏弱 | 无 |
| S3 | v6 official_base | warn 动作偏弱 | 定稿 v4（fail）|
| S4 | v6 official_base | warn 动作偏弱 | 无 |
| S5 | v3 official_base | pass | 无 |
| S6 | v7 pika_flex（_dj）| warn 动作偏弱 | 无 |
| S7 | v3 official_base（_dj）| warn 开头定住 1.8 s | 无 |
| S8 | v4 official_base | warn 动作偏弱 | 无 |
| S9 | v3 official_base | warn 动作偏弱 | 无 |
| S10 | v4 official_base | warn 动作偏弱 | 无 |
| S11 | v4 official_base | pass | 无 |

## 2. 7 维打分（DIR rubric v1；看过 sheets 后定）

| 维 | v1 | v2a | 依据 |
|---|---|---|---|
| ① 人物 | 3 | 3 | 画面同源，SFace 中位几乎不变（S1 0.249→0.240、S10 0.176→0.205）；顾沉全片 0.10–0.20（没有身份来源） |
| ② 鬼影 | 7 | 7 | 同源；鬼影 p95 0.81–1.01，差 ≤0.04 |
| ③ 质感 | 6 | 6 | 同源 |
| ④ 运动 | 6 | 6 | 同源；S4/S6 静止 24%，S10 开头定住 0.5 s（v1 测 0.67 s，剪定住段后余量） |
| ⑤ 剪辑 | 3 | 3 | 同一剪辑（拆刀 / 剪定住段 v1 已有）；平均每刀仍 >5 s 的问题来自 S8 12.25 s 被拆 3 刀仍长、开场 3 s 无切点 |
| ⑥ 声画 | 6 | 6 | I −14.9 LUFS、TP −1.3；嘴部相关同 v1；BGM 仍是按 11 个静默点作曲的旧文件（见 §4） |
| ⑦ 调色 | 3 | 4 | skin guard 压住峰值：脸颊 a*p95 max S1 27.6→23.7、S2 38.2→33.7、S3 39.8→31.8、S4 37.6→34.2、S8 34.6→32.2；整帧红块 S2 0.10%→0.03%、S3 0.07%→0.01%。**但泛红面积不降**（cheek a*≥25 占比 S2 51%→48%、S3 49%→50%、S4 42%→43%），印样 S2 后半段肉眼仍是明显腮红。机器预评分 grade 1.6→3.1 |

**结论**：skin guard 有效但只压峰值，不够让 ⑦ 及格；①⑤ 是硬伤，需要重出（v2）和身份来源（项目方挑设定图）。

## 3. 参数改动与效果（v1 → v2a）

| 改动 | 效果 | 去向 |
|---|---|---|
| `post.skin_guard.enabled` false→true（FIX 默认） | 峰值 −2.4～−8.0 a*，面积 ±3%，红块缩小；嘴唇不褪色（FIX 测） | LEARNED_SPECS D 表已有，补 v2a 整集数据 |

## 4. 未解决 / 阻塞

- **BGM**：`data/music/ep02.wav` 仍是 E8 版（10 个“撤到静默（H3 已带配乐）”）。gpu33 `scripts/audio_post.py` 的 `bgm_for_episode` 无条件按 H3 自带配乐插静默点，现有接口（`bgm --prompt`、画布 edits.json）都绕不过去；需要给 audio_post.py 加“读 post.h3_music=duck_under_bgm 时不插静默点 + 按实际时间线时长作曲”的小补丁（已写好：V2 scratchpad `patch_audio_post.py`），改 gpu33 共享脚本被权限拦下，待授权。
- 顾沉身份：CONSIST 有设定图候选 `data/ab/char_sheets/gu_chen/`（T_s101 / T_s202），**待项目方挑**，生产不动。
