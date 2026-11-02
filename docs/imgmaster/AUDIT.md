# IMGMASTER 现状盘点（P1 第 1 步，只读）

> 负责：IMGMASTER（总调度 fredw-2b 派，L-118）。日期 2026-11-02。任务书：docs/master/CONSISTENCY_PLAN.md §1 / §7 / §8。
> 数据口径：`data/pipeline/runs/series10_v1/assets/first_frame_jobs.json`（rebuilt_at 2026-11-02 08:21:15）+ `data/renders/ep01/S*/takes.json` 的当前版本（active）。
> 指标用本地 Python 算（PIL + numpy），场景和服装描述用 takes 里本地看图模型已经写好的 vlm_text。没有把图片发给任何外部服务。

## 0. 结论（一句话）
ep01 的 10 个镜头**全部是同一场景 sk_office_night**，但没有任何一张图、任何一段文字在 10 镜之间是“同一个东西”：场景底图 10 镜全被丢掉；灯光、走廊方位、陈设各镜自己写；服装参考有 4 种拼法；重出时又按镜换了预设、seed、主机，还被 VQA 修正句改过。拼起来生硬是结构问题，不是某一句提示词写错了。

## 1. 首帧提示词今天是怎么拼出来的（按拼接顺序）

入口：`tools/pipeline/image_jobs.py rebuild_first_frame_jobs` / `tools/autopilot/producer.py FrameExec.render` / 画布 `ns_render.unified_frame.render_first` → 都调 `services/agent/ns_agent/frame_job.py build_first → compile_frame`。

| # | 段 | 生成代码 | 规则 | 是否整场一致 |
|---|---|---|---|---|
| P0 | 单人朝向句“X的眼睛看着…四分之三侧脸…” | `asset_refs.single_turn_line / _apply_single_turn`（塞到 prompt_prefix **最前面**） | K-REN-704（F1/F2acc） | 否：只有单人镜有，双人镜没有 → 两类镜头**段落顺序不同** |
| P1 | 参考说明“图N是…必须完全一致” | `asset_refs.plan_slots → _line`，`_apply_sheet_gaps` | K-AST-230、I2–I5、I9、K-AST-263 | 否：随槽位变（见 §2） |
| P2 | 触发词 | `compiler.compile_shot → loras_for / identity_triggers` | I8、K-REN-103 | 是（series10 全剥掉） |
| P3 | 景别首句 framing_lead | `framing.lead / closeup_lead / TWO_FACE_CLOSE_LEAD` | K-REN-101 / 123 / 902 / 903 | 按景别 |
| P3b | 双人句 TWO_SHOT_TESTED“两人…互相看着对方” | `framing.two_shot_clause` | K-REN-703 / 705 | 否，且**和本镜动作冲突**（§3-5） |
| P3c | 局部人物“只露出手，不露脸” | `framing.partial_clause` | K-REN-705 / 903 | 按镜 |
| P4 | 角色锁【林晚】… | `compiler.lock`，`asset_refs.locks_without_wardrobe`，`framing.filter_parts / part_lock` | K-AST-232、K-REN-705b | 基本一致，但按景别删词（“长腿”只在中景出现） |
| P5 | 造型片段 look_fragments | `compiler.look_fragments` | [looks] inject | 按镜 |
| P6 | 剧本 img 正文（含**本镜自己写的灯光、陈设、方位**） | 剧本原文，`framing.filter_parts / strip_fullbody` 删句 | K-REN-901 | **否：灯光 / 方位句每镜各写一遍**（§3-1、3-2） |
| P7 | 【场景】段 | `compiler.scene_segment`（场景表逐字 + “本镜场景：…”） | S3 | 前半段一致；“本镜场景”每镜不同且互相矛盾 |
| P8 | 纠正器句（面部清晰对焦 / 光比1:4 / 衣装完整） | `compiler.corrector_terms`（visual_bible [[shot_rules]] 按关键词触发） | 纠正器 1.1–1.3 | 否：特写 / 近景有“面部清晰对焦”，中景没有 |
| P9 | 材质句 | `compiler.material_terms` | B5/B7/B8 | 按镜 |
| P10 | 镜头锐度句 | `compiler.lens_term`（后缀含徕卡时为空） | A2 | 是 |
| P11 | 槽位不足说明“X的服装…按文字描述（参考槽不足）” | `asset_refs.TEXT_FALLBACK_NOTE`（经 `frame_job.with_note`） | I9 | 否 |
| P12 | 外层单品补句“本镜造型A要穿全：…” | `frame_job.outer_items_note` | K-REN-101、K-REN-707 | 否：同造型 10 镜补的单品各不相同 |
| P13 | 视线补句“X的视线落在…上” | `frame_job.eyeline_note` | D-SCR-07、K-REN-903 | 否 |
| P14 | 外套细节句“两只袖子都是深灰西装袖” | `frame_job.garment_detail_note` | IMGFIX r5 | 是（上身入画时） |
| P15 | S★ 风格后缀 + 无字幕 | `gen_contract/style.image_suffix`（config/render_quality.json） | I7、L-087 | 是（**不动**） |

P11–P14 由 `frame_job.with_note` 插到后缀之前；P0 插到最前。**之后还有三处改写**：
- `producer.FrameExec.render` 的重出阶梯：`faces_only / double_face / faces_look / board` 变体改参考和前缀；`rung.preset` 换成 `frame_v9_heavy`（krea2 0.5 → 0.8）；
- `producer.vqa_delta → ns_agent.vqa.judge.apply_delta`：上一版看图没过，往提示词里加修正句（例：ep01-S7 当前版本里的“顾沉脸部严格对齐图1参考：34岁成熟克制，眉骨与下颌线清晰…”）；
- 画布 `unified_frame.render_first(prompt_edits=…)` 逐句替换。

**尾帧**：`frame_job.build_last` = “图2是脸部参考” + `compiler.last_prompt`（`visual_bible last_frame_keep` + 结束状态 + 角色锁 + 纠正器 + 后缀）。**没有【场景】段、没有造型参考、没有灯光句**，参考只剩首帧 + 一张脸。

其它不走 frame_job 的出图入口（今天仍存在，需在 arch_scan 棘轮里盯住）：`ns_render.pipeline`（936–941、1136 旧两步）、`ns_api.edits`（编辑器整图）、`ns_api.asset_edit` / `ns_api.assets`（资产图）、`ns_render.frame_edit`（局部改图）、`tools/gpu_grab.py`、`tools/gen_assets*.py`。

## 2. 参考图槽今天由谁决定
- 身份脸：`asset_refs.face_of` = `data/looks/face_overrides.json`（按 run 继承）> config faces。林晚 = `lin_wan_face_hd_A_s202.png`（L-086），顾沉 = `gu_chen_face_ref2va.png`（不是高清版）。
- 造型：`asset_refs.resolve_shot` → 资产中心整集排期 `hub_episode_looks` > 画布逐镜 `shot_looks.overrides` > 系统登记 > 剧本造型行；单品来自 `item_map + item_map_overrides`；设定图按景别取半身 / 全身裁图 `sheet_crop`。
- 场景底图：`asset_refs.scene_ref`（`config/scene_aliases.json` + `shot_looks.scene_overrides`）。
- 排槽：`asset_refs.plan_slots`，qwen_image_2.1 只有 **3 槽**；超出时**场景第一个被丢**，然后合并同角色低优先级为参考板，再丢第二人的单品 / 设定图。
- 生产重出时 producer 的四种变体再改一次槽位。

### ep01 实际槽位（当前作业）
| 镜 | 景别 | 槽 1 | 槽 2 | 槽 3 | 被丢 |
|---|---|---|---|---|---|
| S1 | 特写 | 林晚脸 | 林晚设定图（半身） | 板 09a3（外套 + 指甲） | 场景 |
| S5 | 中景 | 顾沉脸 | 林晚脸 | 顾沉设定图（全身） | 场景、林晚设定图、外套、指甲 |
| S6 | 近景 | 林晚脸 | 林晚设定图（半身） | 板 09a3 | 场景 |
| S7 | 中近景 | 顾沉脸 | 林晚脸 | 顾沉设定图（**半身**） | 场景、林晚全部造型参考 |
| S8 | 近景 | 林晚脸 | 板 42a8（设定图 + 外套 + 指甲） | 顾沉设定图（全身，**顾沉只露手**） | 场景 |
| S9 | 中景 | 林晚脸 | 顾沉脸 | 板 c087（林晚设定图 + 外套 + 指甲） | 场景、顾沉设定图 |

同一场景、同一造型 A，林晚的服装参考有 **4 种拼法**（设定图 + 板 / 合并板 / 无 / 另一块合并板），顾沉设定图半身全身来回换。**场景底图 `assets/scenes/sk_office_night/refs/ar-9565919866.png` 在 10 镜里一次都没送进模型**，作业 warnings 里还写着“暂定，待总调度亲审”。

## 3. ep01 S01 / S06 / S07 / S08（加 S5 / S9 对照）不一致的具体来源

### 3-1 主光：没有一句“整场主光”
| 镜 | 剧本 img 里的灯光（P6） | “本镜场景”（P7） | 实测 CCT | 实测左右亮度差（右−左） |
|---|---|---|---|---|
| S1 | 暖黄台灯**从右侧逆光**；屏幕冷白光从正面；“侧脸朝窗” | 台灯亮着 | 4792 K | **−0.084（左亮）** |
| S6 | 暖黄台灯**右侧逆光**；屏幕冷白光正面 | 台灯在画面右侧 | 4820 K | +0.099 |
| S7 | 暖黄台灯右侧逆光（无屏幕光） | **台灯在后方** | **3820 K** | −0.025 |
| S8 | 台灯右侧逆光；**窗外霓虹在侧脸** | 台灯在后方 | 4726 K | −0.084（左亮） |
| S5 | 台灯从右侧逆光；屏幕光正面 | 台灯在右侧 | 5002 K | −0.015 |
| S9 | 台灯右侧逆光；**安全出口绿光** | 台灯在后方 | 4589 K | +0.001 |

全集 10 镜首帧 CCT 3820–5002 K（极差 1182 K），S7 比相邻 S6 / S8 冷约 1000 K。S1 写“右侧光”实测左亮。根因：灯光由每镜正文各自描述，场景表那句“暖黄台灯侧逆光”没写方向，没有一处“整场主光”被各镜共用。

### 3-2 空间与屏幕方向：走廊左右翻转
剧本“本镜场景”：S3 / S4 / S5 **走廊在画面左侧**；S7 / S8 / S9 **走廊在画面右侧**。而 S5–S9 顾沉一直在画面右、林晚一直在左（机位没有越轴）——走廊跟着翻是空间矛盾。台灯“右侧”（S5 / S6 / S10）和“后方”（S7 / S8 / S9）也来回换。今天没有任何结构化的机位轴线 / 陈设位置，编译器只把这些原文逐字转给模型。（写作侧，交 HOLLYWOOD 定“场景定稿行” + lint。）

### 3-3 造型：参考拼法和补句每镜不同
- 参考：见 §2 表（4 种拼法）。S7 林晚造型参考全丢，只有一句“按文字描述（参考槽不足）”。
- 补句 P12：S1 只补“钻石水晶甲”，S6 补“米白衬衫、钻石水晶甲”，S7 补“米白衬衫、钻石水晶甲、细银链”，S5 / S9 补“深灰铅笔裙”。同一套造型 A 被描述成不同的组合。
- 结果（本地看图模型 vlm_text）：首帧多为“深灰短款西装外套”；**尾帧** S6 / S9 写成“黑色西装外套、黑色下装 / 黑色铅笔裙”，S9 尾帧场景被描述成“现代办公室室内”——尾帧提示词没有【场景】段和造型参考，漂了。S1、S8 尾帧 Q2 记录“短款西装外套没穿（外层探针 0.14 / 0.17 < 0.3）”。

### 3-4 段落顺序不固定
单人镜：朝向句 → 参考说明 → 景别 → …；双人镜：参考说明 → 景别 + 双人句 → …。视线补句、穿全补句、袖子句的位置取决于当时有没有命中。同场镜头之间连“哪句话在第几段”都不一致，模型对前置句权重更高，导致同场不同镜的重点不同。

### 3-5 模板句和本镜动作冲突
- S7：双人句“两人…互相看着对方，目光落在对方脸上”，正文写“顾沉视线落在外套上”。
- S9：双人句“两张脸都清晰入画、互相看着对方”，正文写“顾沉背对镜头朝走廊暗处走”。
- S5：双人句“互相看着”，正文林晚看工牌、顾沉看林晚的手。
- S8：顾沉只露手，但槽 3 送了顾沉全身设定图。

### 3-6 生产执行层：同场各镜按不同参数出
| 镜 | 当前版本 | 重出阶梯 | 预设 | 主机道 | 编译时间 |
|---|---|---|---|---|---|
| S1 | v22 | 插队 2/2 换 seed | frame_v9（krea2 0.5） | gpu33:0 | 04:07 |
| S5 | v13 | 驳回 4/4 | **frame_v9_heavy（krea2 0.8）** | gpu33:3 | 04:05 |
| S6 | v8 | 插队 1/2 | frame_v9 | gpu33:1 | 03:16 |
| S7 | v8 | 驳回 1/2 + **vqa_delta 修正句** | frame_v9 | gpu33:3 | 03:16 |
| S8 | v6 | 驳回 1/2 | frame_v9 | gpu33:0 | 03:17 |
| S9 | v9 | 插队 3/4 | **frame_v9_heavy** | gpu33:0 | 04:09 |

- 质感 LoRA 强度在同场里 0.5 / 0.8 混用 → 颗粒和反差不同。
- seed 每次重出随机，没有场景 seed 族。
- S7 / S8 当前版本的提示词**和现行作业不一样**（S8 多一句“顾沉的视线落在林晚的脸上”，是 K-REN-903 之前编的），但 `bible_version` 都是 `49250a6f09a6`，`first_frame_jobs.json` 里 `compiler_inputs_sha` 是空串 → 系统认不出“这几镜是旧规则编的”，同一场景混着两代编译器的产物。
- takes 的 `deps` 只有 `identity:lin_wan`，没有场景依赖；`scene_plate` 字段存在但全是 null → 场景一换，各镜不会失效重出。

## 4. 不确定性清单（“问题散落”具体落在哪）
1. 提示词有 **15 个段 / 插入点**，分布在 compiler.py、framing.py、asset_refs.py、frame_job.py、style.py、visual_bible.toml、producer.py、vqa/judge.py 共 8 处；没有一份记录说“这一句来自哪条规则、哪个版本”。
2. 参考槽有 **5 个决定方**（face_overrides、hub 排期 / shot_looks、item_map、scene_aliases、producer 变体），最终槽位只能事后从作业里反推。
3. 首帧和尾帧是两套拼法（尾帧没有场景、造型、灯光段）。
4. 重出时预设、seed、修正句、槽位都可能被改，作业文件（first_frame_jobs.json）和真正出图的提示词可以不一样。
5. 版本戳不覆盖编译器代码改动（bible_version 不变、compiler_inputs_sha 为空）。

## 5. 对设计的直接要求（→ docs/imgmaster/DESIGN.md）
- 整场一次定：场景母版底图、主光（方向 / 色温 / 光比 / 动机光源）、陈设位置、机位轴线、站位、本场造型、调色基准 → continuity 文件；P6 / P7 里的环境描述改成从 continuity 取同一句。
- 编译固定分段（单人 / 双人同一顺序），P0–P14 都改成“改写某一段”的插件，并登记在 config/compile/plugins.yaml；尾帧同样分段，带场景段。
- 参考槽按“身份脸 > 场景局部底图 > 本场造型板 > 其它”统一分配；本场造型板整场只做一块、各镜共用。
- 重出阶梯不许改提示词正文和预设之外的段；场景内锁定同一预设、同一 seed 族、同一主机。
- compile_trace 随 take 入账；continuity 的 sha 进 deps，缺失或不符就拒派。
