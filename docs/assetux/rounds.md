# ASSETUX 人物资产页 · 迭代记录

- 负责：ASSETUX（资产中心人物资产页重做）。只改资产中心相关文件；登录 / 全站“一键即确认”归 UIRSI；删除接口归 EDITDEL；出图参考解析器归 REFLOCK；验收打分归 UIAUDIT。
- 约束：不 git 提交；不删数据（删除一律进回收站）；没重启 :8800；截图拦下全部非 GET（0 次放行写请求）。
- 对比与问题清单：`docs/assetux/compare.md`。截图：`apps/web/e2e/assetux/`（before_* = 改前；r1 / r2 / r3* = 改后各轮）。

## 改了哪些文件（发给 UIRSI 避免冲突）

| 文件 | 改动 |
|---|---|
| services/api/ns_api/character_hub.py（新） | 人物资产页接口：列表 / 详情 / 身份脸 / 设定图 / 单品挂造型 / 上传单品 / 加图 / 改名 / 删除进回收站 / 撤销删除 |
| services/api/ns_api/app.py | 只加 2 行：`include_router(CHUB.router)` |
| tests/test_character_hub_assetux.py（新） | 6 例，全在临时目录 |
| apps/web/src/v3/assets/PeopleHub.tsx（新）、hub_api.ts（新）、people_hub.css（新） | 人物页、上传对话框、撤销提示条 |
| apps/web/src/v3/assets/AssetCenter.tsx | 默认路由改人物页；左栏上半人物、下半其他资产；不再挂 SheetPicker / 旧 CharDetail |
| apps/web/e2e/assetux/（新） | shoot.mjs（复制自 uirsi，CDP :9691、只读旁路 :8806、/api/auth/me 本机桩）、场景 json、截图 |
| knowledge/rules/ui.yaml、knowledge/RSI_LEDGER.md | K-UI-025 ~ 028；账本 AX1–AX4 |
| docs/assetux/compare.md、rounds.md（新） | 本文件 |

数据（真实，不是测试）：

| 写入 | 内容 |
|---|---|
| data/looks/wardrobe.json | 林晚新单品 5 件（source=hub_upload）：lw-shoes-up-62fd9e 黑色漆皮细带高跟凉鞋；lw-accessory-up-9d0777 钢珠吊坠圈环、-c8bb9f 双铃铛圈环、-9028d1 横杆铃铛链环（2 张图）、-4080e5 单珠圈环（类别“身体饰品·穿环”，备注“项目方说明：乳环 / 阴环（身体穿环）”）。都没挂造型，等项目方在界面上点选 |
| assets/characters/lin_wan/wardrobe/ | 上面 6 张图 + manifest.json（鞋图先裁掉页面边角：原图 1135×1271 → 1074×1217，去掉右上角的页面图标） |
| data/assets/asset_versions.json | 每件 v1（横杆铃铛链环另有 v2） |
| data/looks/character_hub_log.jsonl | 操作记录（谁、何时、做了什么） |

## r1（10-31 23:40）

- 后端：`character_hub.py`。读写全部落在 REFLOCK 解析器读的地方（和 REFLOCK 对过接口）：
  - 身份脸 → `data/looks/face_overrides.json`（REFLOCK 已让 `face_of` 优先读它）；
  - 设定图 → `runs/<剧>/assets/sheets_chosen.json`（`sheet_of` 只读 file 字段）；
  - 单品挂造型 → `data/looks/item_map_overrides.json`（`item_map` 每次调用合并，不用重启）；
  - 上传单品 → `wardrobe.json`，主参考图放 `images[0]`（解析器取第一张）。
  - 缺图状态直接用 `look_inventory`（单品图 / 仅设定图 / 缺图），不再自己算第二套口径。
- 删除：调 EDITDEL `delete_object(type=asset)`，先解除它在造型里的映射；撤销 = `restore` + 映射写回。
- 前端：人物页 + 上传对话框 + 撤销提示条。
- 测试中途发现：fixture 里先替换了 `ns_api.looks.get_store` 再用它做 `dependency_overrides` 的键，第一次跑时上传写进了真实 wardrobe.json（1 件测试单品，图在临时目录）。已按原样从 wardrobe.json 去掉这 1 条，fixture 改成先记原函数再替换，并断言 `H.get_store is real_get_store`。

## r2（11-01 00:00）项目方 23:48 截图：“这个交互反人类啊！我连向下滑拖都不太行，我怎么用啊？”

- 根因：class 前缀 `ph-` 和 `v3/v3.css` 旧弹层 `.ph { max-height: min(70vh, 640px); overflow: auto }` 撞名，整个人物页被裁成 70vh 的小滚动框。
- 修：前缀全部改 `hub-`；`.hub` 明确 `height:auto; max-height:none; overflow:visible`；整页只剩 `.ac-main` 一个滚动区；锚点条吸顶（59 px，≤8% 视口），按钮加大（34 px）。
- 矮屏（≤800 px 高）左栏压紧，1280×720 下左栏也不出第二个滚动区。
- 实测（真实滚轮 25 × 600 px，跑 `e2e/uiaudit/scroll.js`）：

| 尺寸 | scrollers | nested | notBottom | lastInView | stickyCoverPct | clippedN | lockedCards |
|---|---|---|---|---|---|---|---|
| 1280×720 | 1 | 0 | [] | true | 8 | 0 | [] |
| 1440×900 | 1 | 0 | [] | true | 7 | 0 | [] |
| 1920×1080 | 1 | 0 | [] | true | 5 | 0 | [] |

- 新增：类别“身体饰品·穿环”（槽位 accessory + 标签）、上传备注、给单品再加一张图（`POST …/items/{id}/images`，加在后面，主参考图不变，版本 +1）、单品卡多图缩略条。
- 按总调度要求上传项目方给的 4 件身体饰品（5 张图），见上表。

## r3（11-01 00:20）

- 单品卡：A / B / C 挂造型一行、“＋图 / 删除”另起一行（r2 里“删除”被挤出卡片）；图片区固定 1:1。
- 上传对话框：两栏改 flex，图片不再压住表单；预览地址改在 effect 里建（StrictMode 下 useMemo 建的地址会被第一遍 cleanup 收掉，图裂）。
- 部件清单：解析器的占位 id（`__missing__`）不再显示成“单品：__missing__”。
- 截图：r3_*（18 张，深浅两套，1280 / 1440 / 1920），排版检查 fontOff 0 / colorOff 0 / contrastFail 0 / 横向滚动 0；控制台 0 错误；非 GET 0 次。

## 验证

- `npx tsc --noEmit`：通过。`npx vite build`（输出到临时目录，不动 dist）：通过。
- `pytest tests/test_character_hub_assetux.py`：6 通过。
- 全量 pytest：见交付报告（失败项逐条核对过归属）。

## 还没做 / 下一轮

- UIAUDIT r1 提的：资产中心其他页数据未到时防空崩溃、挑设定图页 1280×720 滚不到底、身份脸 / 设定图 / 场景 / 道具的删除按钮、技术字段（“by=owner”“refs.face_plate 同款”）改人话、音色 ▶ 试听统一换 ds/MediaPlayer（要和 UIRSI 对齐）。
- :8800 我没重启；11-01 00:40 复查时 `/api/character-hub` 在 :8800 已经是 200（有人重启过 API，不是本会话），人物页线上可用。

## r5–r8（11-01 00:40 ~ 02:00）

项目方 / 总调度提的问题和改法：

| 问题 | 改法 | 截图 / 测试 |
|---|---|---|
| 添加单品时只弹红字“这张图已经是单品…了”（项目方 00:35 截图） | 选图后先查库（POST …/check-image，不写数据），比对哈希和旧单品文件内容。已在库里 → 显示那件单品，主按钮“用这件，加到造型 B（不替换）”（POST …/items/{id}/adopt），次按钮“仍作为新单品添加（另起名）” | r5_dup_flow、r7_dup_flow；test_duplicate_image_is_not_an_error_use_existing_or_force |
| 名称框填文件名 | 已在库里 = 用已有名；新图由逻辑模型（abliteration，关推理）看图起名，顺便猜类别，可改、可重起；模型不可用时留空，不报错 | r5_dup_asnew |
| 00:32–00:42 那 6 条映射（项目方：“只是点着试试”） | 选择器没有错位 bug，提交的都是单品 id。成因：衣橱卡 A/B/C 原来会按槽位自动替换一个部件，选择器又只列同槽位的单品。现在：<br>· 默认“加为附加单品，不替换”，只有人明确选了才替换；<br>· 候选按槽位 + 部位过滤（部位口径同解析器 zone_of）；<br>· 卡片显示“已挂到 B·附加”，10 秒撤销；<br>· 日志记入口、部件名、单品名 | r6_part_pick_zone、r6_ask_part；hub_match.test.mjs（node --test，pytest 包了一层） |
| 场景卡 6 个都写“没有底图”（数据对不上） | 没有定稿底图时显示最新的 role=space 参考（“暂定底图”）；详情里列出底图候选（已登记的 + 出图线新出的），点一下设为当前（POST /api/assets/scenes/{sid}/plate-pick，按画布定稿处理，不改 S2 闸门）；登记的参考图可以删（进回收站，可撤销） | r6_scenes、r6_scene_insp；test_scene_space_ref_shows_on_card_and_one_click_pick |
| 只报错不给出路 | 规则 K-UI-029；人物页的失败提示都带“再试一次”或一键解决；全站 46 处列在 error_ways_out.md | docs/assetux/error_ways_out.md |
| 回退 P0-3“＋ 新造型”、P1-13“排期：角色 × 集” | 新造型存 data/looks/hub_extra_looks.json，排期存 data/looks/hub_episode_looks.json。REFLOCK 已接入解析器，优先级：整集排期 > 逐镜登记 > 剧本造型行。造型可以上传设定图（设为当前） | r8_schedule、r8_newlook_dialog；test_new_look_sheet_upload_and_schedule |
| 删除：身份脸 / 场景参考 | 登记过的参考图可以删（回收站 asset_ref），10 秒撤销 | r8_faces |
| 声音能听 | 用 ds/MediaPlayer 的 AudioPlayer；试听由 POST /api/voices/preview 合成（本机，只写缓存）；换音色 / A/B 跳到 #/sound?tab=voice | r8_voice |
| 界面里的内部用语 | 改成“系统”“写作模型”“新出的候选” | — |

滚动（真实滚轮）：1280×720 / 1440×900 都是 scrollers 1、nested 0、notBottom []、lastInView true。
截图时放行的唯一写类请求：POST /api/voices/preview（只写 TTS 缓存）；check-image 走只读旁路 :8806；其余非 GET 一律拦下。

还没做：
- 设定图候选（出图线文件）和道具的删除：回收站目前没有这两类对象，需要 EDITDEL 加类型。
- “将使用的参考图”在精修页显示：v3/edit 归 EDITDEL。

## r11（11-01，ITERATION_PROTOCOL v1 第一轮）

项目方任务：OT6（挑设定图 / 定脸）、OT2（接受 / 打回候选）、OT4（放大看图）。

| 步 | 内容 | 证据 |
|---|---|---|
| 2 度量 | 先测正确性：data_parity PASS（抽查 30 镜 · 466 项 · 不一致 0）。<br>再看隔离区对齐：/api/assets/characters 仍列 alex/ryan/kai/leo；/api/loras 8 行中 1 行（lin_wan_qi_v1）已移进隔离区；场景只剩 6 个（正确） | data/qa/assetux_r11_parity.json；本节 11-01 实测 |
| 3 改动 | · 人物相关卡片只认人物资产页演员表（林晚、顾沉、陈宇、阿岚）；<br>· 新增只读接口 GET /api/asset-quarantine，读隔离区移动记录；卡片和 LoRA 总表都按它过滤，表头写“已移进隔离区的 N 个不再列出”；<br>· “全部（含旧 N）”改成“全部（含当前剧没用到的 N）”，N=0 时写“全部”；<br>· G11 放大说明 data-zoom-label 覆盖人物页和场景候选的小图（UIMASTER 指出说明有重复）；<br>· 单品附图 ✓/✗（设为主图 = POST …/items/{id}/primary） | 文件清单见下 |
| 4 复核 | UIAUDIT（已请求） | 待 UIAUDIT 证据 |
| 5 回归 | gate.sh：tsc + build + data_parity 全过；tests/test_character_hub_assetux.py 13 例全过 | — |
| 6 入账 | knowledge/RSI_LEDGER.md AX6 | — |
| 7 规则 | K-UI-033（check: tests/test_character_hub_assetux.py） | — |

改动文件：
- services/api/ns_api/character_hub.py：/api/asset-quarantine、/api/asset-rejects、/items/{id}/primary。改前已在 LOCKS.md 登记。
- apps/web/src/v3/assets/{AssetCenter.tsx, P1Panels.tsx, hub_api.ts, PeopleHub.tsx, AssetInspector.tsx, people_hub.css}
- tests/test_character_hub_assetux.py

线上：/api/asset-quarantine 和 /items/{id}/primary 要等 :8800 下次重启才上线。在那之前，前端拿到的是空的隔离清单，LoRA 总表会照旧列出隔离项，人物过滤不受影响。重启后要做线上核对。

已知还没处理：LoRA 总表下面的“训练数据集”里还有 lin_wan_qi 的两份数据集（触发词 lnwan_qi）。隔离清单里没有这两份数据集，归 RECALL 判断要不要隔离。
