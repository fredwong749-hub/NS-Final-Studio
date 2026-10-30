# 每镜人物状态时间线 + 场景分组（方案 D，T51）

> 笔记本（fredw-d9）生成，gpu3 只读。生成器：`uv run python tools/build_state_timeline.py`（代码 `services/agent/ns_agent/state_timeline.py`）
> 输出：`data/state_timeline.json`（每镜人物状态）+ `data/scenes.json`（场景分组，供场景底板 / 三图编辑）。
> 自动重建：`tools/import_script.py` 导入剧本后；任何造型修改后（`LookStore` 每次写 data/looks，2 秒防抖后台重建，
> 覆盖 looks API / 资产页 / `python -m ns_agent.looks confirm`）；`tools/s1_gate.py` 改闸门后。`NS_TIMELINE_AUTOBUILD=0` 关闭。
> 两个文件的 `scene_id` 完全一致。字段只增不删，读取方请忽略不认识的字段。镜号：`shot_id` = "ep01-S1"（规范），`gpu3_shot_id` = "ep01s1"。

## 一、版本与过期

### 1. `bible_version`（全局规则版本，信息用）

12 位十六进制短哈希，输入：

| 来源 | 怎么算 |
|---|---|
| `config/visual_bible.toml` | 解析后按键排序的 JSON 的 sha256（注释、空白、键顺序改动不影响） |
| `data/import/script_v2.json` | 文件 sha256 |
| `data/looks/*.json` | 每个文件 sha256 |
| `config/shot_ownership.json` | 文件 sha256 |
| 编译器规则代码 | `ns_agent.bible.RULES_CODE_REV`（拼装逻辑改动时手动递增，当前 `t06.1`） |

```python
from ns_agent.compiler import bible_version
bible_version()                                        # 当前项目（NS_PROJECT_ROOT 或仓库根）
bible_version(project_root="/root/ns-final-studio")    # 指定项目根
```

笔记本写进每个 `data/renders/epXX/SN/compiled.json`（`bible_version`）和每个新 take（`Take.bible_version`）；gpu3 出的 take 请写同一字段。
`uv run python tools/bible_diff.py <旧版本>` 列出编译提示词变了的镜头（快照在 `data/bible_versions/<版本>.json.gz`）。

### 2. `inputs_sha`（每镜输入哈希，判断过期用）

16 位，取自：本镜剧本文字（img/motion/触发词/D 状态/时长）+ 剧本全局（角色锁、后缀、负面、触发词表）+ 本集负面 +
每个角色解析后的造型（look_hash、妆容状态、单品 id/描述/参考图）+ `scene_id` + 场景底板 `plate_sha256` +
入镜角色写实母版 `assets/characters/<id>/plates/master.png` 的 sha + 所需 LoRA 的 sha256 + visual_bible 相关节
（look、realism、materials、shot_rules、shot_rules_safe、assembly、classification、looks、入镜角色的 characters.<id>）。

- 时间线每镜给 `inputs_sha` 和 `prev_inputs_sha`（上一次生成时的值；不同 = 本镜输入变了）。
- 笔记本把它写进 `compiled.json`（`inputs_sha`）和每个新 take（`Take.inputs_sha`）。**take 的 inputs_sha ≠ 当前 = 过期**。
- 代码：`ns_agent.state_timeline.shot_inputs_sha("ep01-S1")`。

## 二、`data/state_timeline.json`

```jsonc
{
  "format": "ns.state_timeline/1",
  "generated_at": "2026-10-30T12:00:00",
  "bible_version": "8aadce957ff8",
  "source": {"script": "v2", "script_sha": "f5af…", "bible_version": "8aadce957ff8"},
  "provisional": true,                    // 见第四节：!(剧本 ≥ v3 且 validator_errors == 0 且 g3_accepted)
  "s1_gate": {"validator_errors": null, "g3_accepted": false, "g3_ref": "", "checked_at": null},
  "source_hashes": {                      // bible_version 的输入 + 以下附加项（附加项不进 bible_version，只进 inputs_sha / 供核对）
    "visual_bible": "…", "script": "…", "looks/looks.json": "…", "looks/schedule.json": "…", "looks/wardrobe.json": "…",
    "shot_ownership": "…", "rules_code": "t06.1",
    "master/lin_wan": "…", "face_reference": "…", "comfy/models.lock": "…",
    "data/renders_gpu3/LORA_REGISTRY.json": "…", "s1_gate": null
  },
  "scenes_sha": "…",                      // = data/scenes.json 的 scenes_sha
  "episodes": {"1": {"look_confirmed": false, "confirmed_ref": null, "confirmed_at": null, "assets_locked_version": null}},
  "stats": {"shots": 360, "scenes": 33, "segments": 143, "needs_review_shots": 338, "s2_ready_shots": 0,
            "unknown_place_segments": 0,
            "per_episode": {"1": {"shots": 6, "scenes": 5, "segments": 5, "needs_review": 6, "s2_ready": 0}}},
  "shots": [
    {
      "shot_id": "ep01-S2", "gpu3_shot_id": "ep01s2", "episode": 1, "index": 2,
      "scene_id": "sk_elevator",          // = scenes.json；按地点跨集复用
      "segment_id": "ep01_seg02",         // 本集内连续同场景的一段（三图编辑链 / 衔接检查按段断开）
      "segment_start": true,              // 段首 → 切镜处重新锚定（方案 A）
      "place": "电梯", "place_key": "elevator",
      "home_owner_source": null,          // 房间类地点的“谁家”依据：explicit | episode | characters | room_history | default
      "place_source": "explicit",         // explicit | inherited（沿用本段）| prev_episode（集首无地点，接上一集）| unknown
      "time_of_day": "morning",           // morning | day | dusk | night | ""
      "time_source": "inherited",         // explicit | inherited | unknown
      "transition": "place",              // 段首才有：episode | place | time | 次日 | 转场 | 闪回 | 梦境 | 当晚 | 周X …
      "characters": {
        "lin_wan": {
          "present": true,                // data/looks 出场检测 + 本镜覆盖
          "look_id": "lin_wan-default", "look_label": "林晚 · 默认 · D0",
          "items": {                      // 槽位 → 单品（outfit, shoes, makeup, hair, nails, accessory, other）
            "makeup": [{"id": "lw-makeup-bare", "name": "素颜", "description": "素颜",
                        "reference_images": ["assets/characters/lin_wan/items/makeup/M1_s0.png", "REF-LW-01"],
                        "in_shot": true, "trigger": null, "source": "episode"}]
          },
          "makeup_state": "bare",         // visual_bible [characters.lin_wan.makeup_states] 的键：bare | transition | heavy | night | tears
          "makeup_state_source": "look",  // look（造型单品）| bible（按集表）| default
          "makeup_item": "lw-makeup-bare",
          "makeup_overlay": "",           // "tears"：本镜原文写到 泪/哭（tears.when）
          "eye_state": "bare", "eyes": "自然深棕色眼睛",   // bare/transition → 深棕；其余 → glam 灰蓝美瞳（visual_bible eyes）
          "hair": {"text": "雾霾天蓝色及腰直发…，齐刘海", "items": ["lw-hair"]},
          "nails": {"hands": "5厘米超长透明水晶甲、镶满钻石饰品", "toes": "2厘米长的性感美甲",
                    "toes_in_prompt": false},   // 原文写到赤脚/脚趾/透明高跟等才进提示词（[[materials]] toenails_lin_wan）
          "heels": "hh12clear",
          "d_state": "D0", "d_state_source": "episode", "visibility": "visible",   // visible | hidden | in_box
          "adornments": [{"id": "lora-nprng2", "name": "乳环…", "trigger": "nprng2", "removable": false,
                          "worn": true, "visible": false}],   // worn = 在身上（in_box 的可摘件为 false）；visible = 本镜写到且未遮
          "needs_review": true,
          "review_reasons": ["episode_plan_unconfirmed", "episode_plan_needs_review"],   // 另有 look_conflict_error
          "conflicts": [{"kind": "script_item_unplanned", "severity": "info", "message": "…", "item_id": "…"}],
          "look_hash": "…"
        }
      },
      "required_loras": [                 // 镜头触发词 + 造型里本镜生效、带触发词的单品 / 可见装饰
        {"trigger": "hh12clear", "kind": "image", "lora_id": "wardrobe_heels_v1.safetensors",
         "registry_status": "missing", "sha256": null}          // missing | training | accepted
      ],
      "s2_ready": false,
      "s2_blockers": ["s1_gate_not_passed", "lora:hh12clear:missing", "plate:sk_elevator:missing",
                      "look_unconfirmed:ep01", "missing_ref:assets/…png", "ref_unresolved:<item>:REF-LW-01"],
      "inputs_sha": "f853139abfb7f4a1", "prev_inputs_sha": null,
      "changes_from_prev_shot": {         // 与全剧顺序的上一镜比
        "prev_shot_id": "ep01-S1", "scene_changed": true, "segment_changed": true,
        "characters": {"lin_wan": ["present"]}   // present, look_id, items.<slot>, makeup_state, eye_state, hair, d_state, visibility, adornments
      },
      "needs_review": true,               // 入镜角色 needs_review，或地点未知
      "bible_version": "8aadce957ff8"
    }
  ]
}
```

- 林晚每镜都有条目（不入镜时 `present: false`，状态照常解析，方便衔接）；其他角色只在入镜时出现。
- 造型解析与画布一致：角色默认造型 → 集造型计划 → 本镜覆盖（`services/agent/ns_agent/looks.py`）。
- `needs_review`：集造型计划没有项目方确认（`owner_confirmed_at`）一律为 true。

### S2 就绪（`s2_ready` / `s2_blockers`）

全部满足才 `s2_ready: true`：
1. S1 闸门通过（`provisional: false`），否则 `s1_gate_not_passed`；
2. 所有 **图像** LoRA（`kind: image`）`registry_status: accepted`（视频 LoRA 只列出，不拦 S2）；
3. 本镜场景底板 `plate_status: owner_confirmed`；
4. 本集造型已由项目方确认（`episodes[n].look_confirmed`）；
5. 入镜角色每个单品的参考图都存在：路径型参考缺文件 → `missing_ref:<路径>`；只有 REF-xx 注册表 id、没有任何文件 → `ref_unresolved:<单品>:<id>`。

### LoRA 注册表

`comfy/models.lock`（笔记本）与 `data/renders_gpu3/LORA_REGISTRY.json`（gpu3，`{"loras": [...]}` 或 `{文件名: {...}}`）合并，按触发词取较好状态。
条目字段：`file`、`triggers`（字符串或 `{trigger}`）或 `trigger`、`sha256`、`status`。
**accepted 必须同时有 `sha256` 和 `status: "accepted"`**；`status` 为 training/queued/eval → training；其余 → missing。

## 三、`data/scenes.json`

```jsonc
{
  "format": "ns.scenes/1", "generated_at": "…", "bible_version": "8aadce957ff8",
  "source": {"script": "v2", "script_sha": "…", "bible_version": "8aadce957ff8"}, "provisional": true,
  "s1_gate": {…}, "scenes_sha": "…",
  "scenes": [
    {
      "scene_id": "sk_elevator", "episode": 1, "episodes": [1, 3, 6, 7, 51, 59],
      "place": "电梯", "place_key": "elevator",
      "time_of_day": "morning", "times": ["morning", "night"],
      "shots": ["ep01-S2", "ep01-S3", "…"],
      "segments": [{"segment_id": "ep01_seg02", "episode": 1, "time_of_day": "morning", "shots": ["ep01-S2", "ep01-S3"]}],
      "plate": "assets/scenes/sk_elevator/plate.png",
      "plate_status": "missing",          // missing | candidate | owner_confirmed
      "plate_sha256": null,
      "plate_built_from": null,           // manifest.json 的 built_from：{scenes_sha, bible_version}
      "owner_confirmed_at": null, "owner_confirmed_ref": null,
      "plate_exists": false,
      "needs_review": false               // 整段认不出地点（epXX_scNN）→ true
    }
  ]
}
```

### 场景底板清单 `assets/scenes/<scene_id>/manifest.json`（gpu3 生成底板时写；项目方确认后补确认字段）

```jsonc
{"plate": "plate.png", "built_from": {"scenes_sha": "…", "bible_version": "…"},
 "owner_confirmed_at": "2026-10-31T10:00:00", "owner_confirmed_ref": "项目方原话", "plate_sha256": "<确认时的图 sha>"}
```

- 没有图 → `missing`；有图但没确认 → `candidate`；有 `owner_confirmed_at` 且图的 sha 与 `plate_sha256` 一致（或没写）→ `owner_confirmed`。
  确认后换了图（sha 不一致）自动退回 `candidate`。
- **S3 只能用 `owner_confirmed` 的底板。**

## 四、权威性：S1 闸门（SOP）

`provisional = !(剧本版本 ≥ v3 且 s1_gate.validator_errors == 0 且 s1_gate.g3_accepted)`

- 剧本版本取自 script_v2.json `sources[]` 里《剧本和镜头》的文件名（…v2.md → v2）。
- 闸门记录：`data/import/s1_gate.json`（`validator_errors`、`g3_accepted`、`g3_ref`、`checked_at`、`script_sha`），
  由项目方 / 协调用 `uv run python tools/s1_gate.py` 写：
  - `--validator-errors N`：记录校验器错误数；
  - `--accept "项目方原话"`：记录 G3 接受（必须给原话，**系统从不自动接受**）；`--revoke` 撤销；
  - 记录绑定写入时的剧本 sha；剧本重新导入后旧记录自动失效（重新视为未通过）。
- `provisional: true` 的场景分组**不得用于生成场景底板**。v2 的输出都是临时的；v3 导入并过 S1 后重跑（导入会自动重跑）才是正式版。

## 五、场景分组规则（确定性）

1. 只看剧本 img 原文，去掉开头的 LoRA 触发词和引号“…”里的屏幕文字/台词。
2. 地点词表（`state_timeline.PLACES`）：写字楼大堂、电梯、公司茶水间、公司洗手间、员工食堂、写字楼办公区、专柜、穿孔工作室、纹身店、
   酒店宴会厅、地铁、高级餐厅、出租车、豪车车内、小巷、顾沉家楼下、街道。强词优先，弱词（写字楼、公司、床、沙发）只在没有强词时用。
   地点与房间都命中时取原文里先出现的。
3. 房间（`ROOMS`：衣帽间、厨房、餐桌、浴室、玄关、阳台、卧室、客厅、书房）按“谁家”区分为 `gu_chen_*` / `rental_*`：
   原文写“顾沉家 / 出租屋 / 回家” > 本集上一段 > 本段入镜角色（顾沉、Alex/Ryan/Kai/Leo → 顾沉家；陈宇 → 出租屋）> 该房间上次的归属 > 出租屋。
   依据写在 `home_owner_source`（`characters` / `room_history` / `default` 是推断，可能需要人工看）。
4. 同一集内连续镜头：地点不变、时段不冲突、没有转场词（次日、第二天、翌日、转场、闪回、回忆、梦境、数日后、几天后、一周后、当晚、句首“周X”）→ 同一段。
   没写地点的镜头沿用本段地点；段首还没地点时用段内第一个写到的地点。原文写明另一处房屋（“深夜出租屋：…”）也换段。
5. 换集一定换段；集首整段都没写地点时接上一集最后的地点（`place_source: prev_episode`）。
6. `scene_id`：`sk_<place_key>`（跨集复用，一张底板服务多集）；仍认不出 → `epXX_scNN`（集内本地 id，`needs_review: true`）。

当前 v2 结果（2026-10-30，bible_version 8aadce957ff8）：33 个场景、143 段、地点未知 0 段。

## 六、造型注入开关（P2，`[looks] inject`）

`config/visual_bible.toml` 的 `[looks] inject = false`（默认）。打开前须：T06 版本化已就位（第一节）、只对项目方确认过的集生效
（集计划 `owner_confirmed_at`，用 `uv run python -m ns_agent.looks confirm <集> lin_wan "项目方原话"` 记录）、
先跑 `uv run python tools/bible_diff.py --inject-preview [--all-episodes]` 看编译差异，并至少 A/B 一镜。
打开后：每个入镜角色的造型片段 `【林晚造型】…`（`[looks] slots`：服装/鞋/妆/发）接在角色 DNA 锁之后（首帧与尾帧提示词），
去掉剧本原文、角色锁、材质规则里已有的内容；注入的单品同样触发 `[[materials]]` 规则（如注入透明高跟 → 追加筷子细跟句，只一次）。

## 七、gpu3 渲染侧字段

> 2026-10-30 按 gpu3 渲染会话的 6 项请求增加（代码 `services/agent/ns_agent/gpu3_fields.py`，测试 `tests/test_state_timeline_gpu3.py`）。
> 全部是**从剧本原文（img / motion，去掉触发词前缀和引号内屏幕字）确定性推出的文字规则**，只增字段。
> 拿不准一律标 `*_source: "guess"`；`inherited` = 本段前面镜头写过。统计在 `stats.gpu3`。

### 1. 每镜 `props`

```jsonc
"props": [{
  "id": "lora-ptxcorset",          // 衣橱单品 id；词表里的通用物件 / 衣物为 "prop:<词>"（文件夹、手机、外套 …）
  "name": "黑色漆皮束腰", "description": "…", "slot": "outfit",   // 物件 slot = null
  "state": "hanging",              // 首帧：worn | hanging | held | on_table
  "state_source": "text",          // text | inherited（本段前镜）| guess（衣物默认 worn，物件默认 held）
  "state_end": "hanging", "state_end_source": "text",   // 尾帧（motion 里写到的；没写同首帧）
  "holder": null, "holder_source": null,   // worn/held 时的人：look（造型里有）| wardrobe（专属单品）| text | guess
  "mention": "黑色漆皮束腰", "found_in": "img",           // img | motion | trigger（只有触发词）
  "trigger": "ptxcorset", "ref_image": null,             // 单品的第一张文件参考图（没有 = null）
  "trigger_in_shot": true, "in_look": false,
  "trigger_conflict": true,        // 本镜触发词会把它画成“穿着”，但 state ≠ worn → 渲染侧按 state 处理（ep05-S1 的教训）
  "look_conflict": false           // 造型把它算作在身上，但 state ≠ worn
}]
```

- 状态线索（同一分句内离道具最近的胜出，前面的优先）：挂/挂在/墙上/衣架 → hanging；桌上/放在/摆在/扣在 → on_table；
  拿/握/手里/抱着/怀里/捧/端 → held；穿/戴/系上/披/裹/一身 → worn（“穿孔”“挂断”不算）。
- 通用词并入单品：“束腰”并入同镜 / 本段 / 造型里的“黑色漆皮束腰”；“外套”并入同镜的“西装外套”。
- 与换装对齐：写了“脱下 X” → X 首帧 worn；写了“穿上 / 披上 X” → X 尾帧 worn、首帧不是 worn。

### 2. 每角色每镜 `changes_within_shot` / `items_end` / `visibility_end`

```jsonc
"changes_within_shot": [{"slot": "outfit", "item": "lora-ptxcorset",   // 认不出单品时 item = null，看 garment
  "garment": "束腰", "from": "worn", "to": "removed",   // to: removed | opened | lowered | lifted | worn（穿上时 from = absent）
  "verb": "脱下", "text": "束腰脱下、挂回自己房间的衣架上", "found_in": "img", "source": "guess", "prop": "lora-ptxcorset"}],
"items_end": {"outfit": [], "makeup": ["lw-makeup-bare"], …},   // 槽位 → 单品 id；按 removed / worn（有 item 的）改过
"visibility_end": "visible", "visibility_end_source": "same"     // same | text（放进盒 / 从盒取出）| guess（遮挡衣物脱下 / 解开）
```

- 动词：脱下/脱掉/褪下/扯下/摘下 → removed；解开/解暗扣/拉开拉链 → opened；拉下/褪到 → lowered；掀起/撩起 → lifted；
  穿上/套上/戴上/披上/换上/裹浴袍/罩住 → worn。分句里必须有衣物词（拉开窗帘 / 车门不算）；只写了扣子 / 下摆时
  归到本镜写到的外衣（`source: guess`）。
- 穿的人：紧挨的“X的 / 她的” > 分句里最近的人名 / 代词 > 林晚（guess）。“他解开她的衬衫”→ 林晚。
- 没有换装时 `items_end` = `items` 的 id。

### 3. 每镜 `framing` / `faces_visible`

剧本没有单独的景别字段，从 img（没有再看 motion）里**最先出现**的景别词取：
极近特写/大特写/巨细特写/微距 → `extreme_close`；特写/近景/手部特写 → `close`；中景/半身/双人构图/侧影 → `medium`；
全景/远景/全身/长镜 → `full`。都没有：开头写手/指尖/屏幕/对话框 → close，写背影/走/站立 → full，其余 medium（`framing_source: guess`）。

`faces_visible`：入镜角色里脸能看到的（id 列表）。剪影 → []；特写且原文没有脸/眼/唇等词 → []；
背影/背对镜头的人去掉；“画外 + 人名”去掉。`faces_visible_source`: text | guess（默认全部入镜角色）。

### 4. scenes.json `plate_detail`（以及每段 `light`）

```jsonc
"plate_detail": {"path": "assets/scenes/sk_elevator/plate.png", "sha256": null, "status": "missing",
                 "light": {"time": "morning", "key_direction": "front", "colour_temp": "neutral"}}
```

- **原 `plate` 字段仍是路径字符串**（只增不改），对象版放在 `plate_detail`；`status` = `plate_status`，`sha256` = `plate_sha256`。
- `light.time` = 场景主时段（认不出 null）；`key_direction`: top | side | back | window | front；`colour_temp`: warm | cool | neutral，
  按场景内所有镜头原文的光线词投票，没有任何词 → null。一个场景跨多集多时段时整体光线较粗，**按段用 `segments[].light`**（同规则，只看本段）。

### 5. 段：`prev_segment_id` / `cut_type` / `episode_segments`

- 每镜、scenes.json 每段、`episode_segments` 每条都有 `prev_segment_id`（全剧顺序的上一段；**跨集也接上**，第一段为 null）和
  `cut_type`：闪回/回忆/梦境 → `flashback`；次日/第二天/翌日/数日后/当晚/周X/时段变化（time）→ `time_skip`；换集/换地点/转场 → `hard`。
- 时间线顶层 `episode_segments`: `{"1": [{segment_id, prev_segment_id, scene_id, place, time_of_day, transition, cut_type, light, shots}]}`。

### 6. 每角色每镜 `signature` / `signature_end`

12 位 = sha256(排序去重后的 id 用 `|` 连接)：outfit / shoes / accessory / other 槽位的单品 + `worn` 的装饰 + 本镜
`holder` 是该角色且 `state`（尾帧用 `state_end`）为 worn 的道具。妆、发、甲不进签名。`signature_end` 用 `items_end`
（装饰收进盒时可摘装饰不计）。两镜签名相同 = 穿戴相同，可直接比较。
