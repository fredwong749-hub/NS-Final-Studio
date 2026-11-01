# UX5-B 资产二次修改机制（审查 + 设计稿）

> 作者：UX5-B（Claude，只写系统）· 2026-10-31 · 状态：设计稿，本阶段未改任何代码 / 配置，未提交任务，未重启 API。
>
> 项目方原话：“一旦对资产做二次修改（比如对资产不满意需要重新修改），无论是做 Lora 的训练、图片的更改，还是提示词的更改，
> 这些情况你都要考虑进去。”
>
> 边界：本机制只管“哪个版本被谁用了、现在是不是旧的、要不要重出、谁能拍板”。剧本 / 提示词 / 画面内容由写作模型和项目方产出，
> 系统原样流转，不写、不改、不评价任何内容；不做内容检测。

---

## 0. 一句话结论

现状已经有**很多零散的过期检测**（造型哈希、场景底图 sha、首帧定稿号、剧本字段比对、H3 覆盖 script_sha、集造型确认绑定内容哈希），
但**没有统一的“资产版本 id”**，也**没有“镜头版本用了哪些资产版本”的完整记录**。结果是：造型 / 单品 / 场景底图 / 首帧 / 剧本文字改了会被发现；
**定妆母版、身份参考图、LoRA、出图预设内容、视频基底配方、附加视频 LoRA、音色、成片**改了，下游基本**不会自动知道**。

设计核心只有三条：

1. 每类资产算一个**内容指纹 = 版本 id**（`rev`，不可变），再加一个**当前指针**；版本登记在一本账里（可回滚、可对比）。
2. 每个新出的镜头版本（Take）在已有的唯一盖章点 `pipeline.stamp_versions` 记下**所用依赖 → rev** 的清单 `deps`。
3. **过期 = 盖章的 rev ≠ 当前 rev**（读时算，不靠写标记）。回滚指针后，旧版本自动“恢复不过期”；影响面 = 反查谁的 `deps` 里有这个键。

---

## 1. 现状审查

### 1.1 各类资产存在哪、有没有版本 / 哈希

| 资产 | 存放 | 版本号 / 哈希 | 镜头版本（Take）是否记下所用版本 |
|---|---|---|---|
| 角色表 / 人物锁 | `data/import/script_v2.json` globals.character_locks；`data/ab/char_fix/registry_draft.md`（草稿） | 剧本整体 `script_sha`；`globals` 段哈希进 `inputs_sha`；草稿确认绑 `draft_sha256`（`rerender.py approve`） | 间接：`inputs_sha`（16 位，全部输入混一起） |
| 定妆母版 | `assets/characters/<slug>/plates/master.png` | 文件 sha 进 `state_timeline.input_hashes()` 和每镜 `inputs.masters` | 间接：`inputs_sha` |
| 脸部参考 | `config/face_reference.json` → `assets/characters/lin_wan/lin_wan.png`；资产参考 `data/assets/asset_refs.json`（如 `ar-c2351c9dcf`） | 只哈希了 **json 本身**，不含它指向的图；asset_refs 有 sha 但不进 inputs | `take.reference` / `references` 记路径，无 sha |
| 形象 look | `data/looks/looks.json`（Look.version、preview_image） | `look_hash`（Resolver 解析结果） | `take.look_hash` ✔ |
| 衣橱单品 | `data/looks/wardrobe.json`（ItemImage.version + sha256） | 同上并入 `look_hash` | ✔（经 look_hash） |
| 资产修改链 | `data/assets/asset_gens.json` / `asset_refs.json` / `asset_versions.json` | 每条有 sha256；`void` 记作废原话 | — |
| 场景底图 | `assets/scenes/<id>/plate*.png` + manifest | sha（`plate_info`），owner_confirmed 绑 sha | `take.scene_plate{path,sha256}` ✔（仅带过底图的首帧） |
| 出图预设 | `config/render_quality.json` image_presets / user_presets，`default_preset=leica_sstar` | **无**（user preset 同名覆盖，内置预设可被直接改） | `params.preset` 只记 **id**；`params.effective` 记了生效参数，但无人比对 |
| 视频基底 | `render_quality.json` video_bases（official_turbo / pika_flex / official_base） | **无** | `params.base` + `base_params` + `model.extra_loras` 记了，**`h3_video.stale_reasons` 不比对** |
| 附加视频 LoRA | `optional_video_loras`（有 sha256） | 有 sha，但不进任何过期判断 | `params.model.extra_loras` 记了名字 + 强度 |
| 出图身份 LoRA | `data/renders_gpu3/LORA_REGISTRY.json`（目前只有 lin_wan_qi_v1，accepted + sha）；`config/auto_lora_triggers.json`（人物 → 文件 + 强度） | registry sha 进 `inputs.loras` | 间接：`inputs_sha`；`take.loras`/`triggers` 记名字 |
| 视频身份 LoRA（如 lin_wan_h3_v1_step250） | 剧本 globals.lora_triggers；**不在 registry** | **无 sha**（registry_status=missing → sha None） | 只在视频参数里有文件名 |
| 训练数据 | `training/lora_*/dataset_manifest.json`（每张图有 source_sha256） | 有，但没和 registry / 定妆版本连起来 | — |
| 镜头提示词 | 读时由 `compiler.compile_shot` 编译；渲染时写 `data/renders/epXX/SN/compiled.json`；`prompt_snapshot` 留快照 | `bible_version`（编译规则版本）、`script_sha` | `take.prompt` 原文 + `basis_prompt` + `bible_version` ✔ |
| 镜头修改 | `data/renders/epXX/SN/edits.json`（ShotEdit.updated_at）、`episode_edit.json` | 时间戳 | 按 `updated_at > created_at` 判断 |
| H3 项目方覆盖 | edits.json `h3_prompt_override`（base_sha、script_sha） | ✔ | ✔（`h3view` 判 stale） |
| 音色 | `config/voices.json`（sid / speed / model） | **无**；TTS 缓存键 = sha(model, sid, speed, text) | 成片 timeline 不记音色版本 |
| 成片 | `data/episodes/epXX.timeline.json` | — | 每镜记了 `file`（含 take 号 + job id），**不与当前定稿比对** |

### 1.2 现在改一个资产，下游谁会自动知道

**会知道（已有，设计要复用，不推翻）：**

- 造型 / 单品 / 集计划 / 默认造型：`LookStore._mutate` 前后比对全部镜头 `look_hash` → 返回 `AffectedShots`；Take 的 `look_hash` 不同 →「造型已改」。
- 集造型确认：`episode_confirmed` 绑定确认时的内容哈希，改了自动失效；`refs/apply scope=episode` 主动撤销确认。
- 本镜 / 本场参考切换：`ref_switch` 的 `/refs/preview` 给 affected / stale / 衔接提醒，`/refs/apply` 可附带“重出首帧”。
- 场景底图换定稿：`take.scene_plate.sha256` ≠ 当前文件 →「场景底图已改」；`scene_assets._stale_shots` 汇总。
- 首帧换定稿：`frame_edit.lock` 写 `takes.json stale{last,video}`；尾帧 / 视频按 `from_first`、`params.first/last {n, sha}` 判「首帧已换」「定稿首帧已换」。
- 剧本文字 / 画布修改 / 导演加强：`_stale_split` 用提示词比对得出「剧本已改」「提示词已改」「导演加强已改」「本集加强已改」；编译规则升级归「编译器升级」（global，不出角标）。
- H3 覆盖：剧本 H3 字段 sha 变了 → 覆盖标“剧本已更新，需重新确认”。
- 场景底图 / LoRA 的项目方确认都绑 sha（`plate_info`、registry accepted+sha）。
- `state_timeline` 在造型改动后防抖重建，`inputs_sha` 随之更新。
- TTS 按 (model, sid, speed, text) 缓存，换音色后**下次合成**会自然重合成。

**不会知道（缺口）：**

| # | 缺口 | 证据 |
|---|---|---|
| G1 | `inputs_sha` 不同**只有在提示词文字也对不上时**才被查看。换母版 / 换脸参考 / 换 LoRA 文件 / 换 registry sha（提示词不变）→ 首帧**不显示过期** | `services/api/ns_api/app.py` `_stale_split`：`_inputs_changed` 嵌在 `if target and not prompt.endswith(target)` 分支内 |
| G2 | `input_hashes()` 不含：出图预设、视频基底、附加视频 LoRA、音色、`asset_refs` 身份参考图、`face_reference.json` 指向的图片文件 | `services/agent/ns_agent/state_timeline.py` `input_hashes` / `build` 的 `inputs` |
| G3 | 预设内容改了（同名 user preset 覆盖、内置预设被改）无人发现；Take 只记了预设 id | `image_params.save_user_preset`；`pipeline` 写 `params.preset` |
| G4 | 视频基底配方改了（步数、sampler、base_lora、shift）不判过期；附加视频 LoRA 换文件不判过期 | `ns_render/h3_video.stale_reasons` 只比首尾帧 |
| G5 | 视频身份 LoRA（step250 → 新 step）没进 registry，没有 sha，换 step 完全无感 | `LORA_REGISTRY.json` 只有 lin_wan_qi_v1 |
| G6 | LoRA 与训练数据 / 定妆版本没有关联：定妆母版改了，用旧母版训练的 LoRA 不会被标“训练数据已旧” | `dataset_manifest.json` 有 source_sha256，但没人读 |
| G7 | 成片不判过期：镜头换了视频定稿、换了音色，`epXX.timeline.json` 不会被标旧 | `ns_post/assemble.py` 只取当时的 active |
| G8 | 没有统一“资产版本 id”，各处版本号口径不同（ItemImage.version、Look.version、asset_versions 的 vN、scene manifest、registry sha），也**没有**预设 / 基底 / 音色 / 母版的版本记录；原地覆盖的文件（master.png、plate.png、voices.json、render_quality.json）**旧内容没留快照**，无法回滚 | 各模块 |
| G9 | 过期多数是“读时现算”，只有首帧定稿会写 `takes.json stale`；没有“依赖已更新：X vA→vB”这种可读的来源文案 | `frame_edit.lock` |
| G10 | 影响面只在造型 / 参考切换 / 场景页有；改母版、LoRA、预设、基底、音色前看不到“会影响 N 镜、要多少 GPU 时间” | — |
| G11 | 重出队列：`jobs.py` 每卡 FIFO，无优先级；整集出片 EB 有 `plan`（含预计时长）和 `force`，但不能按“某次资产修改”选镜头 | `jobs.submit`、`episode_produce` |
| G12 | 作废（`/assets/{id}/void`）只标记候选，不检查是否已有镜头用它出过图；`rerender.py approve` 的“原话 + 草稿 sha”绑定很好，但出来的候选和后续镜头没关联 | `asset_edit.void_records`、`data/ab/char_fix/rerender.py` |

### 1.3 有没有版本号 / 哈希、旧镜头会不会被标过期 —— 简答

- 有哈希的：剧本（script_sha）、编译规则（bible_version）、造型（look_hash）、单品图（sha256）、场景底图（sha）、registry LoRA（sha）、母版（sha，仅进 inputs_sha）、首尾帧（take sha）、H3 覆盖（base_sha / script_sha）、本镜全部输入（inputs_sha，16 位混合）。
- 没有的：出图预设、视频基底、附加视频 LoRA（有 sha 但不用）、视频身份 LoRA、音色、成片。
- 旧镜头被标过期：造型、场景底图、首帧定稿、剧本 / 修改文字 —— 会；母版 / 脸参考 / LoRA / 预设 / 基底 / 音色 —— **不会**（或只在提示词恰好也变时才会）；成片 —— **不会**。

---

## 2. 设计：概念与数据模型

### 2.1 依赖键（dep key）与版本（rev）

每个可被二次修改的东西有一个**依赖键**；它当前内容的规范化哈希（sha256 前 12 位）就是**rev**。rev 是内容寻址的、不可变的；同一内容永远同一 rev。

| 依赖键 | rev 取自（规范化内容） | 现有来源 |
|---|---|---|
| `identity:<slug>` | master.png sha + face_reference.json 指向图片的 sha + 本人身份参考（asset_refs role=identity 且在用）的 sha 列表 | assets/characters、config/face_reference.json、data/assets/asset_refs.json |
| `charlock:<slug>` | 剧本 character_locks 本人那条 + 人物表行（原文，只哈希不解析） | script_v2.json |
| `look:<look_id>` | Look 的 JSON（含 version、preview_image、items） | data/looks/looks.json |
| `item:<item_id>` | WardrobeItem JSON（含 images[].sha256、reference_images） | data/looks/wardrobe.json |
| `plate:<scene_id>[:<variant>]` | 定稿底图文件 sha（+ owner_confirmed 状态） | assets/scenes |
| `lora:<file>` | LoRA 文件 sha（registry / models.lock / optional_video_loras） | 三处登记 |
| `loraslot:<slug>:<image|video>` | 人物 → 当前 LoRA 文件 + 强度（指针本身也是可回滚的资产） | auto_lora_triggers.json、剧本 lora_triggers |
| `preset:<id>` | 预设 params 规范化 JSON（`@identity` 展开前） | render_quality.json image_presets / user_presets |
| `vbase:<id>` | 视频基底配方 JSON | render_quality.json video_bases.bases |
| `vlora:<id>` | optional_video_loras 条目（名字、sha、推荐强度） | render_quality.json |
| `voice:<slug>` | voices.json 本人条目（model、sid、speed）+ tts_model.id | config/voices.json |
| `shotfield:<shot_id>:<img|end|motion|h3|sound|dialogue|duration>` | 剧本该镜该字段原文 | script_v2.json |
| `shotedit:<shot_id>` | edits.json 里影响提示词的字段（image_prompt、boost_*、camera、expression、h3_prompt_override.text…） | edits.json |
| `epedit:<ep>` | episode_edit.json 的 boost / music / scene_overrides | episode_edit.json |
| `frame:<shot_id>:<image|last>` | 该镜定稿帧 {n, sha}（Take 之间的边） | takes.json |
| `video:<shot_id>` | 该镜定稿 / 当前视频 {n, sha} | takes.json |
| `global:bible` | bible_version（编译规则） | 现有，**仍归 global，不出角标** |

规则：**指针也是资产**。例如“林晚的出图 LoRA 用哪个文件”是 `loraslot:lin_wan:image`，换 step 只改这个指针的 rev；LoRA 文件本身（`lora:<file>`）不可变。

### 2.2 版本账本（revisions ledger）

新文件 `data/assets/revisions.jsonl`（只追加）+ `data/assets/revisions_head.json`（当前指针缓存，可由账本重算）。

```jsonc
// revisions.jsonl 一行 = 一次观察到的新版本
{"key": "identity:lin_wan", "rev": "a1b2c3d4e5f6", "seq": 4, "label": "定妆 v4",
 "prev": "9f8e7d6c5b4a", "at": "2026-10-31T21:10:00", "by": "owner|canvas|agent:<名>|observed",
 "owner_quote": "…（闸门类必填）", "source": {"api": "POST /api/assets/lin_wan/identity", "job_id": "…", "gen_id": "…"},
 "snapshot": "data/assets/revs/identity/lin_wan/a1b2c3d4e5f6/"   // 原地覆盖类文件的内容快照
}
```

- `seq` 给人看的“v4”；`rev` 给机器比对。
- 写入方式两种：**主动**（API 修改资产时顺手登记，带 by / 原话）和**被动观察**（`asset_revs.observe()` 读时发现指纹变了但账本里没有 → 记一条 `by: "observed"`，提示“未经系统改动”，例如有人直接改了 config 或覆盖了 master.png）。
- 原地覆盖型资产（master.png、plate.png、face_reference 指向图、voices.json 条目、render_quality.json 片段）在登记时把**旧内容**复制到 `data/assets/revs/<type>/<id>/<rev>/` —— 这是回滚的前提（G8）。不可变型资产（新 LoRA 文件、`<id>-vN` 新单品 / 新造型、takes/*.png）不复制，只记路径。

### 2.3 镜头版本盖章（Take.deps）

`ns_schema.edits.Take` 新增可选字段：

```python
deps: dict[str, str] | None = None   # {依赖键: rev}；出图 / 出视频时由 pipeline.stamp_versions 盖章；None = 旧版本（不参与新规则）
```

盖章点**只有一个**：`services/render_router/ns_render/pipeline.py stamp_versions()`（现已在这里盖 bible_version / inputs_sha）。
`frame_edit.py:313`、`final_tier.py:182` 派生版本时继承父版本 `deps`，再覆盖本次实际不同的项（如换参考、换预设）。

每个 stage 的依赖集合（由 `asset_revs.shot_deps(shot_id, stage, params)` 计算，规则来自现有 state_timeline 行 + 本次有效参数）：

```
image : shotfield:img, shotedit, epedit, charlock:*在画, identity:*在画, look:*/item:*本镜生效,
        loraslot:*:image + lora:<文件>, plate:<scene>, preset:<本次预设>, global:bible
last  : frame:image（定稿 n+sha）, shotfield:end, 以及 image 的人物 / 造型 / 预设 / 底图依赖
video : frame:image, frame:last（若用）, shotfield:motion|h3|sound|dialogue|duration, shotedit(h3 覆盖),
        vbase:<本次基底>, vlora:<附加>, loraslot:*:video + lora:<文件>, voice:*（仅 H3 原声出对白时）
cut   : video:<每镜>, voice:*（TTS 时）, epedit:music, post 设置 → 记在 epXX.timeline.json 顶层 deps
```

### 2.4 过期判定（读时算）

```
stale_deps(take) = [k for k, r in take.deps if current_rev(k) != r]
```

- 每条输出带可读文案：`依赖已更新：林晚 定妆 v3→v4`、`出图预设「徕卡 S★」内容已改（v2→v3）`、`视频基底「官方基模」配方已改`、`林晚出图 LoRA 已换：qi_v1 → qi_v2_step1500`、`音色已改：林晚`。
- 分类沿用规范 §3.5.7：`global:bible` 只进检查器（不出角标）；其余全部是 local → 卡片角标 **「依赖已更新」**（与现有「过期·需重出」同一角标位，文案区分来源）。
- **修 G1**：对有 `deps` 的 Take，依赖比对**独立于**提示词比对，不再嵌在 `if not prompt.endswith(target)` 里。旧 Take（`deps=None`）保持现有逻辑，避免一次性把历史版本全部翻成过期。
- 传递：上游定稿换了才往下传（与现有 `frame_edit.lock` 一致）—— 首帧只是“依赖已更新”时，尾帧 / 视频显示**弱提示**「上游依赖已更新（首帧待重出）」，不直接标过期；首帧重出并**定稿**后，尾帧 / 视频才因 `frame:image` rev 变化而过期。这样避免改一个母版就把整条链全部翻红、项目方分不清先做什么。
- 回滚：指针回到旧 rev → 用旧 rev 出的 Take 自动恢复“不过期”，无需清标记。

### 2.5 依赖图示意

```
                    ┌────────────── 资产层（rev 不可变 + 当前指针）───────────────┐
 charlock:lin_wan ─┐
 identity:lin_wan ─┼──► (训练) lora:lin_wan_qi_v2.safetensors ──► loraslot:lin_wan:image
 dataset_manifest ─┘            ▲ dataset_sha / from_identity_rev                    │
 look:lw_office ── item:*       │                                                   │
 plate:sk_office                │                                                   │
 preset:leica_sstar             │                                                   │
 shotfield / shotedit           │                                                   │
                    └───────────┼───────────────────────────────────────────────────┘
                                ▼
           ┌──────────── 镜头层（Take.deps 盖章）─────────────┐
           │  首帧 image vN  ──定稿──►  尾帧 last vM            │
           │       │                      │                    │
           │       └────────定稿──────────┴──► 视频 video vK ◄─ vbase / vlora / loraslot:*:video / shotfield:h3
           └───────────────────────────────────────────────────┘
                                ▼
           成片 epXX.timeline.json（deps: video:<每镜>, voice:*, music, post）──► G4 / G5 项目方验收
```

### 2.6 状态机

**资产版本（rev）**

```
            生成 / 上传 / 训练完成
  (none) ─────────────────────────► candidate 候选·待复审
                                      │        │
                    项目方/画布设为当前 │        │ 作废（by + 原话）
                    （闸门类必须 owner）│        ▼
                                      ▼      void 作废候选（文件保留，不能再设当前 / 作参考）
  superseded 旧版 ◄──被新版替换── current 当前
        │                              ▲
        └──────── 回滚（同闸门）────────┘
  observed：账本发现未经系统的改动 → 直接成为 current，并在资产页标「未登记的改动」（可一键回滚到上一版）
```

**镜头某一格（首帧 / 尾帧 / 视频 / 成片）对依赖的状态**

```
 fresh 最新 ──依赖 rev 变了──► dep_stale 依赖已更新（角标）
    ▲                              │      │            │
    │ 指针回滚                      │      │ 保留旧版     │ 上游待重出（仅提示）
    │                              │      ▼            ▼
    │                              │   kept 保留旧版（项目方原话，记豁免；再变一次依赖会重新提示）
    │                              ▼
    │                         queued 已排重出 ──► rendering ──► review 新版待复审
    │                                                              │
    └──────────────── 新版定稿（locked）/ 或项目方选回旧版定稿 ◄──────┘
```

- `review` 阶段旧定稿**不动**：新版只“设为当前”，不自动定稿（重出默认 `mode=review`），旧定稿继续供成片使用，直到项目方定稿新版。
- `kept`：等价于对单镜的“依赖更新豁免”，存 `takes.json dep_waivers[stage] = {key, rev_at_waiver, by:"owner", quote, at}`；只对那一个 rev 生效。

---

## 3. 八个场景逐一说明

通用口径：**版本** = 依赖键 + rev + 账本一行；**过期传播** = 读时比对；**影响面** = 反查 `deps`；**重出** = 进统一的“修改重出队列”（§4）；**对比** = CompareModal 左旧右新；**回滚** = 移当前指针。

### S1 改角色定妆图 / 参考图（identity）

- 版本：`identity:<slug>`。改母版 / 换脸参考图都走新接口登记（旧 master.png 进快照）。现有 `/assets/{id}/versions` 明确“人物身份底图不在这里改”，保持；新增专门的定妆接口（§5）。
- 依赖下游：该人物**在画**的所有首帧 →（定稿后）尾帧 → 视频 → 成片；以及**用该定妆训练的 LoRA**（`lora:*` 的 `from_identity_rev`）→ 提示「LoRA 训练数据来自旧定妆 v3」（只提示，不自动重训）。
- 角标：「依赖已更新：林晚 定妆 v3→v4」。
- 闸门：**设为当前 = 定妆确认，项目方本人**（by=owner + 原话）。候选可以由画布 / agent 出。`rerender.py approve` 的“原话 + 草稿 sha”是同一模式，统一进账本。
- 回滚：项目方点“回到 v3” → 快照写回 master.png（文件操作，账本记一条 rollback）。
- 现有缺口修复：G1、G2（脸参考图片 sha、asset_refs 身份参考 sha 进指纹）。

### S2 改服装（造型 look / 单品 item）

- 版本：已有 `-vN` 新资产（不可变，默认）与 `in_place`（原资产加版本）两条路；统一为：`item:<id>` / `look:<id>` 的 rev 取内容哈希，账本登记，`asset_versions.json` 保留为人可读记录。
- 下游：`LookStore._mutate` 已给出 `AffectedShots`；新增把它包装成统一影响面（加 stage、已定稿数、GPU 时间）。
- 角标：现有「造型已改」保留，文案补 rev：「造型已改：通勤套装 v2→v3」。
- 闸门：改**集默认 / 集计划** = 造型确认失效（现有：scope=episode 必须 owner，`confirm_episodes(revoke=True)`）；只改一镜 / 一场不需要。
- 回滚：`-vN` 路径 = 用 `refs/apply` 指回原资产；`in_place` 路径 = 账本指针回旧 rev（图片文件本就保留）。

### S3 重训或换 LoRA（新 step、新数据）

- 版本：LoRA 文件**永不覆盖**，新 step / 新数据 = 新文件名（如 `lin_wan_qi_v2_s1500.safetensors`），registry 新条目：`status: training → candidate → accepted`，并新增 `dataset_sha`（dataset_manifest 的哈希）、`from_identity_rev`、`base_model`、`step`。人物用哪个 = `loraslot:<slug>:<image|video>` 指针（今天在 `auto_lora_triggers.json` / 剧本 lora_triggers 里）。
- 视频身份 LoRA（step250 这一类）补进 registry（G5），否则无法比对。
- 下游：指针变 → 该人物在画的全部首帧（image 槽）或全部视频（video 槽）→ 后续链。
- A/B：P1 提供“同种子对比”—— 选 3–5 个代表镜，用旧 / 新 LoRA 各出一版（seed、预设、参考全相同，只换 LoRA），并排看；对比结果不自动采纳。
- 闸门：registry `accepted`（项目方原话，现有 `accepted_ref`）+ 指针切换（项目方本人）。训练本身占 GPU、外部 API 打标属于花钱 → 项目方。
- 回滚：指针指回旧文件（文件仍在）；用旧 LoRA 出的 Take 自动恢复不过期。

### S4 改出图预设

- 版本：`preset:<id>` rev = 预设 params 规范化哈希。改内置 / 同名覆盖 user preset → 新 rev（旧内容进快照）。`default_preset` 是指针 `preset:@default`。
- 下游（两种，必须区分）：
  - **预设内容改了**：用这个预设出的 Take → 「出图预设『徕卡 S★』已改（v2→v3）」= dep_stale。
  - **默认预设换了**（指针换）：旧 Take 不过期（当时用的预设没变），只在检查器提示「默认预设已换为 X，本版用的是 Y」；整集出片的新任务用新默认。
- 闸门：`default_preset` 是项目方选定（“项目方 2026-10-31 选定 C”）→ 换默认 = 项目方本人；改某个预设的内容 = 影响所有用它的镜头，影响面 > 0 时需项目方确认。
- 回滚：快照恢复预设片段（写 render_quality.json，经 `image_params` 现有写入函数）。

### S5 改镜头提示词 / 剧本字段（只流转，不改内容）

- 来源只有两个：写作模型产出新剧本（导入 → `script_sha` 变）；项目方在画布写覆盖（edits.json / H3 覆盖）。Claude 不改、不评价。
- 版本：`shotfield:<shot>:<field>` 按字段哈希，导入时对比前后两版剧本，只有字段真的变了的镜头才 dep_stale（比现在“整剧本 sha 变 + 提示词比对”更准，且能告诉项目方“第 3 镜只有 sound 行变了 → 只影响视频，首帧不用重出”）。
- 字段 → 格子映射：img → 首帧；end → 尾帧；motion / h3 / sound / dialogue / duration → 视频；人物表行 → `charlock` → 该人物在画镜头；集头造型行 → look 计划。
- H3 覆盖：保留现有 base_sha / script_sha 机制，覆盖文本也作为 `shotedit` 的一部分进 deps。
- 闸门：H3 覆盖仍只项目方（现有）；剧本导入本身走写作流程现有闸门（S1 gate）；系统不新增内容判断。
- 回滚：剧本有 `data/import/backups/`；回滚 = 重新导入某个备份（写作流程决定，系统只提供“回到备份 X 会让哪些镜恢复 / 变过期”的影响面）。

### S6 改场景底图

- 现有机制最完整（`take.scene_plate.sha256` + `scene_assets._stale_shots` + owner 确认绑 sha）。只做统一：`plate:<scene>[:variant]` 进 deps，账本登记，影响面接口统一；**修补**：没带 `scene_plate` 的首帧（底图经参考覆盖进来）也通过 deps 覆盖到。
- 闸门：底图 owner_confirmed（S2 闸门）= 项目方；画布定稿只到 candidate（现有）。

### S7 改音色 / 声音描述

- 版本：`voice:<slug>` rev = voices.json 本人条目 + tts 模型 id；“声音描述”（剧本 VOICE 声线行、H3 audio 段）属于剧本字段（S5）。
- 下游：
  - TTS 对白：成片（`cut`）过期 —— TTS 缓存本来按音色区分，重新合成即可，不占出图 GPU（CPU / 小模型），影响面显示“只需重新合成 N 集，约 X 分钟”。
  - H3 原声出对白的视频：声音描述在 H3 提示词里 → 视频 dep_stale（这个很贵，影响面要单列）。
- 闸门：音色是人物身份的一部分 → 换音色 = 项目方本人。

### S8 改视频基底配方

- 版本：`vbase:<id>`（配方内容）+ `vbase:@default`（默认指针）；`vlora:<id>` 同理。
- 下游：与 S4 同样区分“配方内容改了”（用它出的视频过期）与“默认换了”（只提示）。Take 已记 `params.base` / `base_params` / `extra_loras`，P0 就能比对（G4）。
- 闸门：默认基底是项目方决策（`default_decision`）→ 换默认 = 项目方；VBVR 这类许可受限的 LoRA 保持现有“仅研究”标签。

### 场景汇总表

| 场景 | 依赖键 | 直接影响 | 默认重出范围 | 闸门（必须项目方本人点） |
|---|---|---|---|---|
| S1 定妆 / 脸参考 | identity | 在画首帧（+提示 LoRA） | 首帧，定稿后链式 | 设为当前（定妆确认） |
| S2 服装 | look / item | 本镜生效造型的首帧 | 首帧 | 改集默认 / 集计划 |
| S3 LoRA | lora / loraslot | 在画首帧 或 视频 | 先 A/B 代表镜，再批量 | accepted + 换指针；训练 / 外部打标花钱 |
| S4 出图预设 | preset | 用该预设的帧 | 首帧 / 尾帧 | 换默认；改内容且影响>0 |
| S5 剧本 / 提示词 | shotfield / shotedit | 按字段映射到格子 | 只重出变了的格子 | H3 覆盖；导入走写作闸门 |
| S6 场景底图 | plate | 本场首帧 | 首帧 | 底图 owner 确认 |
| S7 音色 | voice | 成片（TTS）/ 视频（H3 原声） | 重新合成；视频单列 | 换音色 |
| S8 视频基底 | vbase / vlora | 用该基底的视频 | 视频 | 换默认 |

所有场景共同的闸门：**删除**（文件 / 版本，P2 前一律不删，只作废）、**作废**（by=owner 带原话，现有）、**花钱**（外部 API：写作网关、外部打标、云渲染）、**批量重出超过阈值**（见 §4，确认框，非原话闸门）。

---

## 4. 影响面预览与批量重出

### 4.1 影响面（不写任何东西）

输入：一组“将要发生的变化” `[{key, to_rev | to_draft}]`（例如“把 loraslot:lin_wan:image 指到 qi_v2”）。
计算：

1. 反查：所有镜头当前 / 定稿 Take 的 `deps` 中含该键的（有 `deps` 的 Take）；旧 Take（无 `deps`）用 state_timeline 行现算本镜是否用到该资产（人物在画、造型、底图、触发词）作为**估计**，标“估计（旧版本无盖章）”。
2. 分层：直接受影响的格子（首帧 / 尾帧 / 视频 / 成片），以及“定稿后会连带”的格子。
3. 计数：按集、按格子；其中**已定稿**多少、**项目方验收过（G4 / G5）**多少、**有 kept 豁免**多少。
4. 时间：每格用 `jobs.estimate(kind, gpu)`（近期实际耗时中位数）× 数量 ÷ 可用道数（与 EB `produce/plan` 同口径）；TTS 单独估。
5. 会失效的确认：集造型确认、底图 owner 确认、G4 / G5 验收、H3 覆盖 —— 逐条列出。

### 4.2 修改重出队列

不新造调度器：**复用整集出片 EB（`episode_produce`）**，它已有 DAG（首帧 → 定稿 → 尾帧 → 定稿 → 视频）、跨道铺开、可恢复、`plan`。扩展：

- 新 body 字段：`shots`（已有）、`reason: "rev:<key>@<rev>"`、`stages` 按影响面自动给、`mode` 默认 **review**（不自动定稿，旧定稿保留到项目方选）、`priority`。
- 优先级（同一集内 EB 调度时排序；跨集排队靠 jobs 层 P2 的优先级）：
  1. 离交付最近的集（未过 G5 的最小集号）优先；
  2. 已定稿 / 已验收的镜头优先于从未定稿的（它们是“被改坏”的）；
  3. 首帧先于视频（视频要等首帧定稿）；
  4. 项目方手点的单镜永远插在批量前（现有单镜 frame-jobs 不受影响）。
- 阈值确认：预计 GPU 时间 > 2 h 或格子 > 30 时，确认框显示总时长与“正在跑的任务会被往后排多少”。不是原话闸门，但不能由 agent 静默提交（遵守“不提交任务”的会话约束）。
- 进度挂在账本那一行上：`rev` 详情页能看到“这次修改：已重出 12/40，待复审 8，保留旧版 3”。

---

## 5. 接口草案

全部新增，不改现有接口语义；现有 `AffectedShots`、`/refs/preview`、`scene_assets` stale 保持，内部改为调用统一实现。

```
GET  /api/revisions/keys?type=identity|look|item|plate|lora|loraslot|preset|vbase|vlora|voice
     → [{key, label, current:{rev, seq, at, by}, versions_count, used_by_count, unregistered_change: bool}]

GET  /api/revisions/{key}
     → {key, label, current, versions:[{rev, seq, label, at, by, owner_quote, source, snapshot, state}],
        used_by:{rev: count}}                      // 每个版本被多少镜头格子用着

POST /api/revisions/impact
     body {changes:[{key, to_rev?}], episodes?:[n]}
     → {changes:[{key, from:{rev,seq}, to:{rev,seq}}],
        cells:[{shot_id, stage, take_n, locked, approved, estimated: bool, chain:["last","video","cut"]}],
        by_episode:{"2":{image:8, last:3, video:5, cut:1}},
        gpu_estimate_s:{image:…, video:…, tts:…, total_parallel:…, lanes:[…]},
        confirmations_lost:[{gate:"look", episode:2, character:"lin_wan"}, …],
        requires_owner: true|false, reasons:["换定妆 = 定妆确认"]}

POST /api/revisions/{key}/set-current         // 移当前指针（含回滚）
     body {rev, by, owner_quote?, note?}
     → 403 当 key 属于闸门类且 by≠owner 或无原话；成功 → {applied, impact}（同上，事后快照）

POST /api/revisions/{key}/observe             // 手动触发一次指纹检查（读时也会做）
GET  /api/shots/{id}/deps                     // 每格：deps 表 + 每项 当时 rev / 当前 rev / 状态 / 文案
POST /api/shots/{id}/deps/keep                // 保留旧版（豁免）{stage, key, by:"owner", owner_quote}
POST /api/revisions/rerun                     // 生成 EB 任务（P1）
     body {key, rev, cells?:[{shot_id, stage}], mode:"review", priority?, by}
     → 复用 POST /api/episodes/{n}/produce（按集拆）；返回各集 produce 状态链接
GET  /api/episodes/{n}/cut/deps               // 成片依赖与是否过期（P1）
```

现有接口补字段（P0）：

- `GET /api/shots/{id}`（app.py 摘要）每个 take 的 `stale` 原因里加入 dep 文案；新增 `stale_deps:[{key, from, to, label}]`（结构化，供角标 tooltip）。
- `GET /api/assets/{asset_id}` 加 `revision:{key, current, versions_count, used_by_count}`。
- `POST /api/assets/{asset_id}/versions`（in_place）、`/refs/apply`、`/assets/scenes/{id}/plate` 返回体并入统一 `impact`。

---

## 6. UI 交互稿（ASCII）

### 6.1 镜头卡角标

```
┌ ep02 · S3 ───────────────────────────────┐
│ [首帧 v4 ✓定稿] [尾帧 v2]  [视频 v3]       │
│  ⚠ 依赖已更新      ⚠ 上游待重出  ⚠ 上游待重出 │
│  └ 林晚 定妆 v3→v4                        │
│  └ 出图 LoRA qi_v1→qi_v2_s1500            │
│ [对比] [重出首帧] [保留旧版…]               │
└──────────────────────────────────────────┘
```
- 「依赖已更新」= dep_stale（橙）；「过期·需重出」现有红色保留给首帧定稿已换等直接过期；「上游待重出」灰色小字，不计入统计。
- 「保留旧版…」打开原话输入框（项目方本人），记 kept。

### 6.2 资产页 · 版本与影响面（以定妆为例）

```
┌ 资产 · 林晚 · 定妆（identity:lin_wan）─────────────────────────────┐
│ 当前  v4  2026-10-31 21:10  项目方「…原话…」                         │
│ ───────────────────────────────────────────────────────────────── │
│  v4 ● 当前   [图]  用于 3 格（新出）                                  │
│  v3 ○ 旧版   [图]  用于 41 格   [对比 v3|v4] [回到 v3]                │
│  v2 ○ 旧版   [图]  用于 0 格                                         │
│  c7 ◌ 候选·待复审 [图]  [设为当前…]  [作废…]                           │
│  ! 未登记的改动：master.png 在 21:40 被直接覆盖（v5 observed） [回到 v4] │
└──────────────────────────────────────────────────────────────────┘
```

### 6.3 设为当前 / 回滚前的影响面确认框

```
┌ 把「林晚 定妆」从 v3 换成 v4 ─────────────────────────────────────┐
│ 会影响：首帧 23 镜（其中已定稿 19、已验收 G4 的 ep02 共 11 镜）      │
│        定稿后连带：尾帧 19、视频 17、成片 ep02                       │
│        LoRA lin_wan_qi_v1 的训练数据来自 v3（只提示，不自动重训）       │
│ 预计 GPU：首帧约 46 min（3 道并行）；连带视频约 5.1 h                 │
│ 会失效：ep02 G4 验收                                                │
│ ───────────────────────────────────────────────────────────────── │
│ 这是定妆确认，需要项目方本人。原话：[______________________________] │
│ 应用后： (•) 只标记，不重出   ( ) 排队重出首帧（review，不自动定稿）    │
│                                   [取消]   [确认（项目方）]          │
└──────────────────────────────────────────────────────────────────┘
```

### 6.4 修改重出队列面板

```
┌ 修改重出 ─────────────────────────────────────────────────────────┐
│ #1 identity:lin_wan v3→v4   ep02  首帧 12/23 ▓▓▓▓▓░░░  待复审 8  保留 3 │
│ #2 preset:leica_sstar v2→v3 ep03  首帧  0/9   排队中（前面 1 项）       │
│ #3 voice:gu_chen            ep02  成片重合成 ✓                         │
│ 优先：先近交付集 → 已定稿镜 → 首帧先于视频            [暂停] [取消 #2]   │
└──────────────────────────────────────────────────────────────────┘
```

### 6.5 A/B 对比（复用 CompareModal）

```
┌ 对比 ep02·S3 首帧 ─────────────────────────────────────────────┐
│   v4（定妆 v3 · LoRA qi_v1 · 徕卡 S★ v2）│ v6（定妆 v4 · LoRA qi_v2 · 徕卡 S★ v2）│
│   [ 图 ]                               │ [ 图 ]                               │
│   不同的依赖：定妆 v3→v4，LoRA qi_v1→qi_v2 （高亮）                         │
│   [定稿左边] [定稿右边] [两版都留着]                                         │
└──────────────────────────────────────────────────────────────┘
```
系统只并排展示与列出差异项，不给“哪个更好”的判断。

---

## 7. 分期

### P0（本轮可落地，均为只读 / 盖章 / 显示，不改渲染行为）

| 改动 | 文件 |
|---|---|
| 新模块：依赖键指纹、`shot_deps(shot, stage, params)`、`current_revs()`（mtime 缓存，复用 `_sha_cached`）、账本读写 + 被动观察 | 新增 `services/agent/ns_agent/asset_revs.py` |
| Take 加 `deps` 可选字段 | `packages/schema/ns_schema/edits.py` |
| 盖章：`stamp_versions` 写 `deps`；派生版本继承 | `services/render_router/ns_render/pipeline.py`、`frame_edit.py`、`final_tier.py`、`h3_video.py`（视频 Take 创建处） |
| 过期：有 `deps` 的 Take 独立比对（修 G1）；视频比对 base_params / extra_loras（修 G4，旧 Take 也可，因为已记录）；文案 `依赖已更新：…` | `services/api/ns_api/app.py` `_stale_split`；`ns_render/h3_video.stale_reasons` |
| 指纹覆盖补齐（修 G2/G3 的检测部分）：脸参考图片、身份 asset_refs、预设内容、视频基底、附加视频 LoRA、音色 | `asset_revs.py`（不改 state_timeline 的 inputs_sha 口径，避免全体历史版本翻转） |
| 只读接口：`GET /api/revisions/keys`、`GET /api/revisions/{key}`、`POST /api/revisions/impact`、`GET /api/shots/{id}/deps` | 新增 `services/api/ns_api/revisions.py`，在 `app.py` include_router |
| 前端：角标文案「依赖已更新」+ tooltip 列出 stale_deps；资产详情显示“当前 vN / 用于 N 格” | `apps/web/src/v3/words.ts`、`apps/web/src/v3/edit/VersionChain.tsx`、`api_v1.ts`、资产 tab 组件 |

P0 测试（新增 `tests/test_asset_revs_p0.py`，用 conftest 的临时项目根，不碰真实数据）：

1. 指纹稳定：同内容两次计算 rev 相同；JSON 键顺序不同 rev 相同。
2. **G1 回归**：换 master.png（提示词不变）→ 有 `deps` 的首帧出「依赖已更新：… 定妆」；无 `deps` 的旧 Take 行为与现在一致。
3. 回滚：文件换回 → 该 Take 恢复 fresh。
4. 预设内容改 → 用该预设的 Take 过期；只改 `default_preset` → 不过期，仅检查器提示。
5. 视频基底配方改 → 用该基底的视频过期；默认基底换 → 不过期。
6. 音色条目改 → `voice:<slug>` rev 变；（P0 只验证指纹，成片过期在 P1）。
7. 盖章继承：frame_edit 派生版本继承父版本 deps，换参考的那一项更新。
8. 影响面：构造 3 镜（2 镜林晚在画、1 镜不在）→ impact 只返回 2 镜；旧 Take 标 `estimated: true`；GPU 估算调用 `jobs.estimate`（打桩）。
9. 被动观察：直接改文件 → 账本出现 `by: "observed"` 一行，且只记一次。
10. 现有测试全绿：`test_ref_switch_w5.py`、`test_scenes_s2_s3.py`、`test_looks.py`、`test_video_jobs_v1.py`、`test_frame_jobs_w2.py`、`test_state_timeline.py`。

> 部署提示：P0 改动在 API 进程里，生效需重启 :8800；须等当前渲染任务跑完、由总调度安排重启时间。本稿不做。

### P1

- 写路径：`POST /api/revisions/{key}/set-current`（含回滚、闸门校验、原话），快照目录 `data/assets/revs/`；定妆 / 音色 / 预设 / 基底 / LoRA 指针的写入都改走它（现有 asset_edit / scene_assets / looks 写入时同步登记账本）。
- LoRA：registry 补视频 LoRA、`dataset_sha`、`from_identity_rev`、`step`；训练脚本完成时写 candidate 条目；“LoRA 训练数据来自旧定妆”提示。
- 成片：`assemble` 把 `deps` 写进 `epXX.timeline.json`；`GET /api/episodes/{n}/cut/deps`；成片卡角标；音色变更只需重合成的路径。
- 修改重出队列：`POST /api/revisions/rerun` → EB（`reason`、`mode=review`、集内优先级排序、阈值确认）；进度挂在账本行。
- 保留旧版（kept 豁免）接口 + UI；作废时检查“是否已有镜头用它出过图”并在确认框列出（G12）。
- 同种子 A/B：选代表镜按旧 / 新 rev 各出一版（仅换一个依赖）。
- 剧本按字段 diff：导入新剧本后给出“字段级变化 → 格子”清单（流转，不评价内容）。
- 测试：`tests/test_revisions_p1.py`（闸门 403、回滚快照恢复、EB 只排受影响格子且 mode=review 不动旧定稿、成片过期、kept 只对一个 rev 生效、作废检查）。

### P2

- `jobs.py` 每道队列改优先级队列（跨集、跨来源统一优先级），单镜手点永远最高。
- 依赖图可视化页（资产 → 镜头 → 成片，按集折叠）。
- 旧版本归档 / 删除（项目方本人，带原话；只删无人引用的 rev；删前再算一次 used_by）。
- 修改通知：剧本字段级变化 / 人物表变化经 qwen_mailbox 告知写作方（只发“哪些镜头格子因此过期”的事实，不发内容意见）。
- GPU 预算：多项修改同时待重出时，按预计时长给出合并方案（如同一镜的定妆 + LoRA 两项变化合并成一次重出）。
- 把 `state_timeline.inputs_sha` 口径与 `deps` 统一（`inputs_sha` 退化为 deps 的摘要），去掉双轨。

---

## 8. 不做的事 / 风险

- 不做任何内容判断：不判断新版“更好 / 更像 / 合规”，对比只摆图和差异项。
- 不自动重出、不自动定稿新版：所有重出都要人点；批量默认 review。
- 旧 Take 不追溯盖章：避免一次把几百个历史版本翻成过期；影响面里旧 Take 标“估计”。
- 账本被动观察可能把“临时手动实验”的改动也记成新版本 → UI 明确标“未登记的改动”，一键回滚。
- 快照占磁盘：只给原地覆盖型资产存快照（图片 / 配置片段，体量小）；LoRA 与渲染结果本来不可变，不复制。
- `render_quality.json`、`voices.json`、`auto_lora_triggers.json` 的写入属于配置文件修改，P1 实施时要经项目方 / 总调度同意的写入通道（本轮不碰）。
