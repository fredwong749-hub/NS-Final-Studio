# IMGMASTER 设计（P1）：分段编译 + 连续性 + 统一参考槽

> 负责：IMGMASTER-S（接 IMGMASTER）。任务书：docs/master/CONSISTENCY_PLAN.md §1 / §8；现状盘点：docs/imgmaster/AUDIT.md。日期 2026-11-02。
> 状态：P1 = 设计 + 只读试编（开关默认关）。出图路径在 `imgmaster.enabled=false` 时一字未变。

## 0. 一页结论
- 不新起入口：改造 `services/agent/ns_agent/frame_job.py`（K-REN-134 唯一出图作业构建），加 `compile_frame_v2`，其余入口（producer、画布、编辑器 submit-interactive）以后只要走 `build_first / build_last` 就自动走它。
- 提示词 = **参考标注头** + 固定五段：`[framing 景别·镜头] [continuity 场景连续性块] [characters 人物块] [action 本镜动作] [constraints 约束句]` + S★ 风格后缀（L-087，不进任何插件视野）。
- 其它规则只能登记为插件改“本段”；参考图槽不归插件，只归 `asset_refs.plan_slots_v2`。
- 每次编译产出 `compile_trace`（每段来自哪条规则 / 文件 / 版本、槽位用了哪几张为什么、删了哪些分句），随 take 落账。
- continuity 是决策文件：缺失或 sha 不符 → 拒派（失败关闭）。

## 1. continuity 数据结构
来源：HOLLYWOOD 导出 `data/pipeline/runs/<run>/continuity/scene_locks_epNN.json`（schema `nsfs.scene_locks/1`，`tools/script_rsi/scene_lock.py export`）。路径一律经 `tools/autopilot/runs.py` 取 run 目录，不写死。

```
{schema: "nsfs.scene_locks/1", run, episode,
 scenes: {<scene_id>: {fixtures: [陈设], key_light: "主光一句话（方向 + 光源 + 辅光）", blocking: {名: {side: 左|中|右, pose}},
                       screen_direction: "谁在哪侧、走廊 / 台灯等大物件在哪侧", shots: [镜号]}},
 links: [{shot, transition, cue_type, cue}]}
```
IMGMASTER 只读。编译用到的字段：`key_light`、`screen_direction`（进整场固定句）、`blocking`（越轴检查）、`fixtures`（校验必填）。四个字段缺一 → `CompileError`。
后续（P2，由 DEBUG-RSI / FACTORY 落地，本设计只定接口）：
- 场景母版底图 `scene_plate` 走场景级 takes（`data/renders/<ep>/scene_<scene>/takes.json`），continuity 里补 `plate: {asset_id, sha}`；各镜参考槽取它按景别裁的局部（P1 仍用现有 `assets/scenes/<目录>` 最新一张整图，局部裁切是 P2）。
- 调色基准 `grade: {lut|hist_sha}` 供后期色彩匹配。
- 本场造型 `looks: {角色: 造型id}`：P1 由 `asset_refs.scene_look_refs` 从同场各镜的解析结果算（见 §4）。
- **试用定稿**：HOLLYWOOD 导出前，试编用 `data/review_pages/imgmaster/ep01_scene_locks_TRIAL.json`（取 AUDIT §3 多数值，走廊左右是任选一边，非定稿）。导出后试编自动改读真文件。

## 2. frame_job 分段编译
### 固定顺序
```
参考标注头（槽位分配函数产出：[单人朝向句 K-REN-704] + 逐槽“图N是…必须完全一致”）   ← 不是一段；A/B 证明朝向句必须在最前
[framing]      景别首句（含双人 / 局部句）                 来源：compiler.compile_shot（K-REN-101/123/902/903/705）原样透传
[continuity]   【场景】<场景表字段，去掉“光线”>；主光：…；站位与屏幕方向：…   整场逐字相同
[characters]   角色锁 + 造型片段 + 外层单品补句(outer_items)
[action]       剧本 img 正文（去环境句）+ “本镜场景：…”（过方位守卫）
[constraints]  纠正器 / 材质 / 槽位不足说明 + 镜头句   ；最后接 S★ 风格后缀 + 无字幕
```
- 单人镜和双人镜**同一顺序**（AUDIT §3-4 的“段落顺序不固定”消除）：朝向句只是“有没有”，不是“在哪”。
- 原料来源：P1 不重写 `compiler.compile_shot`，由 `_split_old` 按锚点把它的输出拆回各段（`【` 首个角色锁、剧本 img 首分句、`scene_segment` 原文、风格后缀）；P2 起 compile_shot 直接按段返回，`_split_old` 退役。拆不准会体现在 trace 的 sha 上，试编页逐镜可见。
- 失败关闭：`load_plugins` 校验不过 / continuity 缺失 / 场景无定稿 → `CompileError`，不回退旧路径。`imgmaster.fail_closed` 开关预留给“不想挡生产”的灰度（默认 true）。

### 插件登记表 `config/compile/plugins.yaml`
每条 `{id, segment, rule_id, order, enabled}`；`segment` ∈ 五段；`rule_id` 必须在 `knowledge/rules/*.yaml` 存在且带 `check`（G1）；代码里 `@plugin("id")` 的实现必须有 enabled 条目，反之亦然（未登记插件不许跑）；签名 `(segment_text, shot, continuity) -> segment_text`，拿不到最终提示词和其它段。

| id | 段 | 规则 | 作用 | 状态 |
|---|---|---|---|---|
| scene_detail_guard (5) | action | K-WRT-H23 | “本镜场景”里的物件方位（左右 / 前后同轴）和 continuity 相反 → 删该分句记 trace；含动作 / 视线的不自动删，进 trace.warnings | 启用 |
| cont_scene_block (10) | continuity | K-WRT-H23 | 场景表（去掉“光线”）+ 整场固定句 | 启用 |
| env_dedupe (10) | action | K-WRT-H25 | 不带人名、非动作 / 视线、和 continuity 主光 / 场景表重复的环境 / 灯光分句删掉；continuity 没说的环境细节（安全出口绿光）保留 | 启用 |
| outer_items (10) | characters | K-REN-707 | 原 `outer_items_note` | 启用 |
| text_fallback (10) | constraints | K-AST-263 | 槽位不足的文字说明 | 启用 |
| eyeline | action | **无**（D-SCR-07 没有规则条目） | 视线补句 | 禁用：缺规则；试编用 `legacy=True` 补回并标 legacy |
| garment_detail | characters | **无**（IMGFIX r5） | 袖子句 | 禁用：缺规则；同上 |
| framing_lead_rule | framing | K-REN-101（无 check） | 景别首句 | 禁用：规则没 check；景别首句目前原样透传 |

> 缺口（要别的 owner 补，否则这三条永远是 legacy）：ACTING / HOLLYWOOD 给 D-SCR-07 补规则条目 + check；IMGFIX 给袖子句补规则 + check；K-REN-101 补 check。
### 旁路收口
arch_scan“提示词旁路”棘轮（SYSARCH 已有，现基线 2）：编译模块以外对 prompt 字段做 `+=` / 拼接 = 退化。现存散落处（producer 重出阶梯 `faces_only / board` 变体改参考和前缀、`vqa.judge.apply_delta` 加修正句、画布 `prompt_edits`）P2 逐个改成：重出阶梯只许改参考槽 / 预设 / seed（不许改段文本）、vqa_delta 改成给 `action` 段登记插件、画布编辑落成对某段的显式覆盖（trace 记 `override`）。

## 3. 开关与灰度
`config/compile/imgmaster.yaml`：`imgmaster.enabled: false`（默认）。关 = `build_first / build_last / compile_frame` 与改造前逐字相同（tests/test_unified_frame、test_imgfix、test_gen_contract 71 条全过）。
开启顺序（P2，需总调度批）：ep01 一场 → ep01 全集 → 全剧；每步先跑 `tools/imgmaster/trial_compile.py` 看 C1–C5。

## 4. 统一参考图槽分配（`asset_refs.plan_slots_v2`）
优先级：**身份脸 > 场景局部底图 > 本场造型单品板 > 其它**。身份脸 L-086 不动（A-s202 等）。
- 旧：`plan_slots` 槽满时“场景第一个被丢”。新：`plan_slots(scene_protected=True)`，场景槽不让位，丢的是造型（走文字 + 固定说明句）。
- 本场造型单品板：`scene_look_refs(各镜 ShotRefs)` 把同场每个角色出现过的非脸参考取并集（设定图取全场最常用的一种裁法），整场同一份 → `make_board` 按内容哈希得到**同一个文件**（ep01 林晚 7 镜同一块 board）。
- 只露局部的人（`presence=局部` 且无脸）不占造型槽（旧版 S8 给只露手的顾沉送了全身设定图）。
- 记录：`trace.preamble.slots / dropped`，每张写 kind / character / file，丢弃项写原因。
- **容量是硬约束**：qwen_image_2.1 只有 3 槽，双人露脸镜 = 2 脸 + 1 场景 = 满，造型全部走文字（ep01 的 S5/S7/S9）。想让双人镜也有造型参考，只能合并身份脸成一块脸板——动 L-086 身份脸保真，**需总调度 / 项目方拍板，不由我改**。

## 5. compile_trace（随 take 落账）
`write_compile_trace(trace, out_dir)` → `{file, sha}`。内容 schema `nsfs.compile_trace/1`：
```
shot, model, continuity{file, sha256, scene}, plugins_sha, compiler_inputs_sha, bible_version,
segments[{name, sha, chars, sources[{rule|plugin, rule_id, file, order, legacy?}]}],
preamble{sha, slots[{index, kind, file, character}], dropped[...], rule},
dropped_clauses[{plugin, clause, conflict?}], warnings[...], applied_plugins, prompt_sha
```
落账：take 记录加 `compile_trace: {file, sha}`（EDITOR_INTEGRATION 附录 A2 的 take 字段，`ns_render.pipeline` 唯一写入口，DEBUG-RSI 加）；编辑器 `accept-take / submit-interactive` 同样带。图像工坊 / 反馈后台按它回答“这一镜为什么长这样”（P3 展示）。同一镜同 `prompt_sha` 同文件名，天然去重。
失效：takes 的 `deps` 增加 `continuity:<scene>:<sha>` 与 `plugins:<sha>`；变了 → E24 签名失效；**已采用 / 加锁的镜不自动重出**，只标“和新场景定稿不一致”（附录 A，同 CONSISTENCY_PLAN §2）。

## 6. continuity 进 decisions_guard（待 FACTORY 落实，接口如下）
`tools/factory/decisions_guard.py`：
- `REQUIRED` 追加 `"data/pipeline/runs/{run}/continuity/scene_locks_ep{ep:02d}.json"`，但只在“该集 import 里有场景定稿行”（`tools/script_rsi/scene_lock.parse_locks` 非空）时必需（旧集没有就不拦）；
- deps 闭包按 sha 推到服务器；服务器缺或 sha 不对 → 拒派，不许静默按“没有连续性块”出图（Top15 #2）。
- 本人不改该文件（不在 IMGMASTER 归属内）；FACTORY 接手时按此处两条加，并加一条 `tests/test_factory*.py` 用例。

## 7. 一致性检查（试编页 `data/review_pages/imgmaster/epNN_compile_diff.html`）
| 项 | 判定 | ep01 结果 |
|---|---|---|
| C1 同场主光句逐字一致 | 10 镜连续性块同一串且含主光原句 | 通过（旧版 AUDIT：CCT 3820–5002K、灯光各镜自写） |
| C2 场景槽都在 | 有场景底图的镜都有 scene 槽 | 通过（旧版 10/10 丢） |
| C3 造型参考一致 | 同角色各镜造型参考同一文件 | 通过：林晚 7 镜同一块（旧 5 种）；顾沉全是双人镜、无造型槽（走文字） |
| C4 段落顺序固定 | 各段在提示词中位置单调 | 通过 |
| C5a 越轴 | 站位左右 vs 定稿 | 通过 |
| C5b 方位文字矛盾 | 最终提示词里无和定稿相反的走廊 / 台灯方位 | **未过**（S3/S4：朝向句“看着画面左侧走廊方向…”来自剧本的视线落点，在参考标注头里；已自动删的是 S3/S4/S5 的“走廊方向在画面左侧”）。这是写作侧问题（走廊到底左还是右由 HOLLYWOOD 定稿），编译层不改写剧本视线落点 |

## 8. P2 清单
1. compile_shot 直接按段返回，退役 `_split_old`。
2. 场景母版底图 + 按景别裁局部；scene_plate 入账（场景级 takes）。
3. 重出阶梯 / vqa_delta / 画布编辑改走插件或显式覆盖；场景内锁同一预设、seed 族、主机。
4. 尾帧 `build_last` 也走分段（带场景段 + 本场造型参考）。
5. decisions_guard / deps / E24；takes 增 `compile_trace`。
6. 补三条规则缺口后把 legacy 插件转正。

## 9. 总调度 11-02 补充决定
- **ep01 走廊 = 左**（总调度定，以剧本视线为准，待 HOLLYWOOD 写进场景定稿行）。试用定稿已改左；S7–S9 写“右”的方位分句由 scene_detail_guard 删（含动作 / 视线的分句只进 trace.warnings，S9 的“视线朝画面右侧的走廊暗处”需写作侧改）。
- **双人镜不合成脸板**（L-086 保真优先），造型继续走文字；compile_trace 的 `look_refs_via_text` 标“造型参考因槽满走文字”。基座支持更多参考槽（FLUX 3 Klein 10 张）时再放开。
- **三条规则缺口已补**：K-REN-101 补 check；视线补句（决策 D-SCR-07）= K-REN-710；袖子句 = K-REN-709；eyeline / garment_detail 转正为启用插件，legacy 补位已删。knowledge compile --check 绿。
- **ownership**：IMGMASTER 名下已加 tools/imgmaster/**、tests/test_imgmaster_*、docs/imgmaster/**、data/review_pages/imgmaster/**（CONSENT 记总调度名下）。
