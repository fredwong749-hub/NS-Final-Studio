# 分镜精简稿（SHOT_SCHEMA_LITE）——L-199：写作方只写导演决定

项目方 11-05（L-199，MASTER_PICTURE）：分镜写作改“只写导演决定”——每镜约 10 个结构字段；出图 / 视频提示词、布光句、背景实景光源、声音、镜头默认值由代码按场景表和规则生成；校验在代码里自动修正，只有剧情矛盾才退回；一次快模型调用；大纲 → 可导入分镜 ≤ 1 分钟。先做 ep02 新旧对比（首帧不能变差）再切。

- JSON Schema（单一来源）：`tools/script_lite/shot_schema_lite.json`
- 写作提示词：`tools/script_lite/prompt_lite.md`；一次调用：`tools/script_lite/write_p4_lite.py`（模型 = `config/llm_providers.json purposes.script_write`，现为 abliteration flash，与现行写作链路同一入口 `ns_api.llm_config`）
- 展开器（确定性）：`tools/script_lite/expand.py` → 现行可导入 P4 Markdown（导入器 / 校验器 / 编译器全部不改）

## 每镜字段（写作方写的 = 导演决定）

| 字段 | 值 | 说明 |
|---|---|---|
| `n` / `scene_id` / `segment` | 整数 / `sk_…` / `fantasy`｜`reality` | 场景 id 必须在 P1 场景表；段决定布光 / 配乐档 |
| `size` | 大特写｜特写｜近景｜中近景｜中景｜中全景｜全景 | 景别 → 镜头类型 → 焦段（lenses.yaml by_kind） |
| `angle` + `tilt` | side45｜side30｜front｜ots｜high｜low + 平视｜平视略低｜略仰｜略俯｜俯拍 | `ots` 时写 `ots_from`（被越肩的人，只露肩与后脑，不算露脸）、`ots_shoulder` |
| `lens_id` / `cam_height_m` | 可空 | 空 = 代码按镜头类型默认（双人 / 中景 50 T2 1.4 m；过肩 / 单人近景 85 T1.4 1.5–1.55 m；插入 100 微距 T2；特写 135 T1.2；车内 1.2 m） |
| `move` | `{id, amp, why}`，id ∈ static / push_in / pull_out / pedestal_up / bolt_push_settle / handheld_follow | 只用 camera_moves.yaml 对本剧 enabled 的六种；why = 动机 |
| `cast[]` | `{name, presence(在画｜局部｜背影｜画外), pos(左｜中｜右), depth(前｜中｜后), orient, part, pose_en, action, action_en, gaze, gaze_dir, mouth}` | action 不写人名、至少一个接触动作；action_en 给 H3 锚点句 |
| `props` / `props_en` | 本镜看得见的道具状态 | 进 **场景** 行与前景层 |
| `beats[]` ≤3 | `{t0, t1, zh, en, gaze, expr, react, sfx_zh, sfx_en}` | 时间轴连续覆盖 0→时长；en 现在时、无否定词、无引号、无人名 |
| `line` | `{speaker, tone, text, beat, offscreen}` 或 null | 一镜一句一人；beat = 落在第几拍 |
| `duration_s` | 4–6 整数 | Σ ≥ 86 s（剪后 ×0.7 ≥ 60，K-WRT-819） |
| `link` / `cut` | `{type, carry}` / `{type, lead_s, reason, at}` | 衔接 / 下镜 |
| `end_state_zh` / `end_state_en` | 结束状态（不写景别词） | motion 的 `——` 之后 |

集级：`episode, title, synopsis, music{zh, bgm_en, cue_en{1,2,3}}, setting_en{段}, practicals_en{段}, sublocation{段}`。

## 代码生成的字段（写作方不写）

| P4 字段 | 来源 |
|---|---|
| **镜头** / **光学** | lenses.yaml `by_kind`（镜头类型 = insert / closeup / ots_or_single_mcu / two_shot / establishing）+ 机位高度默认 |
| **光线** / **灯光** / img 末尾布光句 | 场景表“光线”列按 幻想段 / 现实段 切段：主光（光源 + 方向 + 色）、边光、补光 / 留暗、焦外光源；色温按光源词表 |
| **构图** | 前景（过肩前景人 / 前排人物 / 道具）｜中景（脸在三分点 / 上三分之一）｜背景（场景表远处实景光源 → 焦外光斑，K-WRT-817）｜视线方向（按对方左右位置，轴线 K-WRT-811；单人加“留出空间”） |
| **站位** / **人物** / **机位与景别** | cast + angle；过肩写“背对镜头｜只以 X 肩与后脑入画、大幅虚化”（K-WRT-H16 / K-REV-807 口径） |
| **运镜** / **镜头运动** / motion 前缀 | camera_moves.yaml（zh / id / h3_official） |
| **分拍** / **表演节拍** / **台词时段** / **下镜** | beats / line / cut 格式化 |
| **sound** / **声音** | 各拍 sfx + 配乐 cue 状态机（现实段撤到静默 0；幻想段进入 1 / 延续 / bolt 推到高点 3 / 落下 2）+ 【H3 audio】 |
| **H3提示词** | 官方 FL2VA 四块：锚点句（景别 + 机位 + 每个在画人物 EN外貌 + 造型 EN + 站位 + action_en + L1 英文布光）/ 焦外句 / 分拍（In the first two seconds… Then, around the Nth second… as the shot ends）/ 台词 `(S1) says: <d>[Chinese] …</d>` / settle 句；overall_soundscape = 【H3 audio】；non_diegetic_music = cue_en[档] 或 N/A |
| 集头 **造型｜X** / 人物表 / 场景表 / **场景定稿** / **本集镜头规划** | P1_storyline + P1_looks（schedule 的 O1+O4 合并）+ 各镜推导（轴线 / 焦段档 / coverage / 固定占比） |

## 代码自动修正（不进 LLM；`expand.autofix`）

镜号重排；时长钳到 4–6；分拍时间轴重排；H16（≥2 露脸 + 紧景别 → 改过肩，第二人只露肩与后脑）；K-WRT-818（两人景深层拉开）；多人镜运镜白名单（static / push_in / pull_out / handheld_follow）；bolt / pedestal 只单人；H15（在画人物缺接触动作 → 补“手撑在<陈设>上”）；固定占比 > 20% → 多出的改 push_in；H3 否定词替换。

只退回写作方（bounce）：总时长 ×0.7 < 60 s、镜数 < ⌈Σ/6⌉、人物不在 P1、场景不在表。

## 已知缺口（代码生成不了、L3 手写版有的）

见 CHANNEL 11-05 WRITER-LITE 报告：img 人物句是“造型 + 动作 + 视线”的模板句，没有 L3 那种逐件衣物的在镜细节（领口露出短裙上缘、腕表反光）；人物适配句是模板；H3 分拍英文完全依赖写作方 `en`；场景表 P1 `sk_rooftop_bar` 光线列只有一段（天台），楼下车内的现实段布光要靠 `--scene-table-from`（L3 稿的两段式场景行）——建议把 P1 的场景行改成两段式后 LITE 才能不带参数跑。
