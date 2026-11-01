# 数据对齐契约：界面字段 → 接口 → 源文件

DATAALIGN 写于 2026-11-01，规则编号 K-UI-D01，强制检查脚本是 `tools/qa/data_parity.py`（在 iter_gate 里是 D1 项）。

> 项目方原话（11-01）：“S1、S2、S3、S4 的每一个 scene 里面，对应的剧本、对应的人头都不太一样，但我发现你都是一模一样，所以里面的 content 都是错的……你全部 scan 一下整个 system，看看还有哪些地方 Backend 跟 Front end 的 data 没有对齐。”

本文的约定：
- 界面上显示的每个逐镜字段，必须等于下表“源”那一列的文件内容。
- 改动前端绑定或改动接口后，都要跑 `.venv/Scripts/python.exe tools/qa/data_parity.py`，退出码为 0 才算完成。
- 数据缺失时，界面显示“?”或“未登记”，不准编一个值出来顶上。

## 1. 项目方指出的问题：逐镜头像全都一样

### 1.1 根因

- **接口那一侧**：`/api/episodes/{n}` 返回的 `shots[].characters` 只走旧造型库 `ns_agent.looks.Resolver`。
  - 谁在画：用 `detect_characters` 在正文里搜关键词。动作描写里只要出现“顾沉”两个字，就算他在画；“阿岚”不在关键词表里，永远不会出现。
  - 造型：全部是 `<角色>-default`，`look_label` 为空。
  - 脸：用的是旧库的 `plates/id_front_s0.png`，顾沉在旧库里没有这张图，所以头像是空的。
- **出图那一侧**：`ns_render.unified_frame` 调用 `ns_agent.asset_refs.resolve_shot`。
  - 谁在画：读剧本本镜的 **人物** 行（`shot.cast`），只算“在画”和“局部”两种。
  - 造型：按优先级取，依次是资产中心整集排期 `data/looks/hub_episode_looks.json`、逐镜登记 `<run>/assets/shot_looks.json`、剧本造型行。
  - 脸：取 `face_of`，依次查 `data/looks/face_overrides.json` 和 `config/recipes/asset_refs.json` 里的 faces。
- **前端那一侧**：`apps/web/src/v3/LeftRail.tsx:43` 的 `letterOf` 写的是 `(c.look_label || "A")`。造型字母为空时一律显示“A”。

结果是第 3 集 S1–S7 每一镜都显示“林晚 A + 顾沉 A（空头像）”。按源数据，S1 只有林晚 A，S2 是顾沉 B + 林晚 A，S3–S6 是两人都 B，S7 只有林晚 B。

### 1.2 修复

- 新增 `services/api/ns_api/shot_cast.py`，按出图的同一口径计算每镜的人选、造型字母和脸。
- `app.py` 的 `_shot_summary` 里，`characters` 改为 `SCAST.merge(...)`。旧库的插槽、冲突、本镜覆盖信息都保留。
- 剧本如果不属于在资产里登记过的项目（例如 weita 旧剧），行为和原来一样。
- `letterOf` 的规则改为：凡是“与出图同源”的人物，造型对不上登记时显示“?”，不再冒充“A”。

### 1.3 验证

- 修改前，在线 :8800 共 80 镜：人选错 21 镜；人选对、但字母错 47 镜；脸不是出图用的身份脸 79 镜。
- 修改后（进程内运行新代码，`data_parity --inproc --all`）：80 镜、1220 项全部一致。
- 截图：
  - 修改前：`apps/web/e2e/dataalign/before_ep3.png`
  - 修改后（新接口结果注入页面）：`apps/web/e2e/dataalign/after_ep3.png`

## 2. 共用数据源

| 接口 | 后端 | 源文件 |
|---|---|---|
| `/api/episodes/summary` | `app.py episodes_summary` → `episodes_fast.SummaryCache`，后台缓存最长 60 秒，只返回轻字段 | 同 `/api/episodes/{n}` |
| `/api/episodes/{n}` | `app.py _episode_payload` → `_cached_shots` → `_shot_summary`，按镜输入签名缓存（`shot_cache.py`） | 见下表 |
| `/api/sop/episode/{n}` | `sop.py` | `data/state_timeline.json`、`data/scenes.json`、`data/sop/owner_gates.json` |
| `/api/story-images[?run=]` | `story_runs.story_images` | `data/pipeline/runs/<run>/images/**`。不带 run 时，取当前剧本自己的运行 |
| `/api/shots/{id}/asset-refs` | `story_runs.shot_asset_refs` | 当前剧本对应运行的 `assets/first_frame_jobs.json`，没有就调 `asset_refs.plan_for` 现算 |
| `/api/candidates?ep=` | `takes_ui` | `data/renders/epNN/Sk/takes.json` |

## 3. 镜头卡（画布审片行 / 剧本页“每镜完整一行” / 左栏）逐字段

所有字段都来自 `/api/episodes/{n}` 的 `shots[]`。前端 `ReviewRow.tsx`、`ScriptFullRows.tsx`、`LeftRail.tsx` 直接读这份数据。

| 界面字段 | 接口字段 | 后端 | 源文件 | 检查项 |
|---|---|---|---|---|
| 镜号 S1…Sn | `id` / `index` | `_shot_summary` | `data/import/script_v2.json` episodes[].shots[] | D-SHOT |
| 剧本（画面 / 动作） | `script_text`，`storyboard.img_prompt` / `motion_prompt` | `shotinfo.script_text`、`_storyboard` | 剧本，与 `data/pipeline/runs/<run>/epNN/P4_epNN.md` 原文逐字相同 | D-SCRIPT |
| 景别、运镜、时长 | `camera.*`、`duration.seconds` | `shotinfo.camera_info` | 剧本（剧本没写时长时，按 10 秒兜底，并标 `source=default`） | D-DUR |
| 对白、独白 | `dialogue[]`、`voiceover` | 剧本 | 剧本 **🎙 / 对白** 行 | D-DLG |
| 人物头像、名字 | `characters[].character` / `name` | `shot_cast.shot_cast` | 剧本本镜 **人物** 行，只算“在画”和“局部” | D-CAST |
| 造型字母 A/B/C | `characters[].look_label` | `shot_cast` | `data/looks/hub_episode_looks.json` 优先，其次 `<run>/assets/shot_looks.json` | D-LOOK |
| 头像图 | `characters[].face_url` | `asset_refs.face_of` | `data/looks/face_overrides.json` 优先，其次 `config/recipes/asset_refs.json` 的 faces | D-FACE |
| 场景小卡名称、底图 | 场景 id 取 SOP 的 `scene_id`；名称来自 `data/scenes.json`；底图来自 `/api/shots/{id}/refs` | `sop.py`、`ref_switch` | 剧本 `scene_id` | D-SCENE |
| 首帧、尾帧、视频 | `first_frame` / `last_frame_*` / `video` | `takes.json` 当前版本，或 gpu3 链 | `data/renders/epNN/Sk/takes.json`，或 `data/renders_gpu3/…` | D-FRAME |
| 计数（如“首帧 x/N”） | 摘要里的 `summary.first_frames` / `videos` / `passed` | `episodes_fast.light_episode` | 同上；摘要缓存最长 60 秒 | D-COUNT（只警告） |
| 状态、按钮 | `review` / `stale` / `job*` / `readiness` | `_review`、`_stale_split`、内存任务队列 | `review.json`、`takes.json` | — |

只要源数据里各镜不一样，界面就不能整集显示成一样（检查项 D-VARY）。

## 4. 剧本页（`#/script-create`）

| 界面 | 接口 | 源 |
|---|---|---|
| 各集标题条 | `/api/story-runs/{id}/artifact/P1` | `<run>/P1_storyline.json` |
| 阅读模式：每镜的画面、人物、对白、全部字段 | `/api/story-runs/{id}/artifact/P4?ep=` | `<run>/epNN/P4_epNN.md` 原文，只做排版 |
| 阅读模式：人物 | 同上 | **人物** 行。修复后保留“（画外）”“（局部）”，以前整段括号被删掉，画外的人也显示成在场 |
| 阅读模式：首帧图 | 该集已导入画布时，取画布当前首帧，没有就取候选，再没有就取还没登记版本的草图；该集没导入时，取 `/api/story-images?run=<本运行>` | 修复前取的是“出图目录里最新一张任意图”，可能是校验用的 raw 图，而且不按运行区分 |
| 过程视图 P3 / P4 | 同 artifact | 原文 |

## 5. 其他页面（只读扫描，字段 → 接口 → 源）

| 页面 | 字段 | 接口 | 源 |
|---|---|---|---|
| `#/overview` SeasonPage | 每镜景别、场景、人物、衔接、秒数 | `/api/season` | `season.py`，读剧本 |
| `#/overview` SeasonPage | 首帧、视频进度 | store 摘要 | 见 §3 |
| `#/cut` | 成片、时长、“落后 N 镜” | `/api/episodes/{n}/cuts` | `data/episodes/epNN*.mp4`、`*.timeline.json`、`takes.json` |
| `#/sound` | 台词、说话人、试听 | `/api/sound/lines`、`/api/shots/{id}/audio` | `ns_post.speakers`、`config/voices.json`、`data/cache/tts` |
| `#/sound` | 配乐 | `/api/music` | `data/music/epNN.wav`、`.json` |
| `#/assets` 人物页 PeopleHub | 脸、设定图、排期 | `/api/character-hub*` | `asset_refs.face_of`、`sheets_chosen.json`、`shot_looks.json`、`hub_episode_looks.json` |
| `#/assets` 旧角色卡 | 形象 | `/api/assets/characters` | 旧 LookStore：`data/looks/looks.json`、`schedule.json` |
| 编辑模式 RefBar | 人物、形象、场景 | `/api/shots/{id}/refs` | 旧 Resolver（见 §6 第 1 条） |
| 顶栏步骤 ① | “N 镜缺资料” | `/api/episodes/{n}/readiness` | `material_readiness.py` |
| 顶栏步骤 ② | “造型待确认” | `/api/looks/episodes/{n}` | 旧 Resolver + `schedule.json`（见 §6） |

## 6. 已知未对齐、还没修的项

这几项涉及别的 loop 的设计，或需要项目方拍板，所以没有在本轮修。

1. **编辑模式的“切换本镜参考”还在用旧造型库。** 涉及 `/api/shots/{id}/refs` 和 `ref_switch.py`。series10 出图走 `asset_refs.resolve_shot`，不读画布的参考覆盖，所以在这里切换不会影响出图。RefBar 一加载，显示的人物和形象也会变回旧库的结果。需要 REFLOCK 和 ASSETUX 决定：是让 `asset_refs` 读覆盖，还是让切换写 `shot_looks` / hub。
2. **用旧库 `look_id` 做分组的地方。** 包括 AssetsPage `buildUsage`、`center.ts usageOf.byLook`、AssetCenter 本集造型条，以及 `v3/looks.ts lookLetter`（按旧库列表顺序编字母）。这些地方显示的“哪集用哪套造型”仍是旧库排期，和人物页 `character_hub._schedule`（用的是 `shot_looks.json`）对不上。
3. **顶栏 ②“造型待确认”和 `sop.py` 的造型关口都读旧 `schedule.json`。**
4. **场景“使用镜头”的口径不同。** `scene_assets.py` 的使用镜头来自 `ref_switch.scene_map`（旧 Resolver），和剧本里的 `scene_id` 口径不同。
5. **配乐里的镜号是按位置编出来的。** `shot_audio.py:184` 用 `S{k+1}`。series10 的镜号是连续的，目前没有错；以后插镜或删镜就会错位。
6. **剧本没写时长时，接口兜底成 10 秒，总时长里也算进去了。** 接口带了 `source=default` 标记，但 SeasonPage 的秒数显示为空，两页的总秒数会不一样。
