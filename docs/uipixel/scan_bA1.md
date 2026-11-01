# UIPIXEL 扫描 bA1

生成：2026-10-31T17:53:56.423Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 31 个 × 尺寸 1440×900 × 主题 dark = 截图 31 张（目录 apps/web/e2e/uipixel/bA1/，主尺寸另有 _mark 标注图）
- **去重后问题 29 条**：严重 3 · 一般 7 · 轻微 19
- 分类：可点区域过小 22 · 缺悬停态 4 · 无手型指针 3

## 每页问题数

| 状态 | 1440 深 |
|---|---|
| projects 项目首页 | 6 |
| script_new 新建剧本 | 6 |
| script_read 剧本阅读模式 | 6 |
| overview 全剧总览 | 4 |
| review 画布·审片 | 2 |
| review_ep01 画布·审片（第 1 集，有图） | 3 |
| review_ep01_scroll 画布·审片（第 1 集，往下滚） | 3 |
| edit_ep01 画布·精修（第 1 集） | 1 |
| edit 画布·精修（提示词） | 1 |
| edit_params 精修·参数 | 6 |
| edit_versions 精修·版本 | 6 |
| edit_assets 精修·资产 | 4 |
| edit_sound 精修·声音 | 0 |
| edit_rules 精修·规则 | 2 |
| assets 资产中心 | 0 |
| a_character 资产·人物 | 0 |
| a_linwan 资产·人物页（林晚） | 5 |
| a_look 资产·形象 | 0 |
| a_item 资产·单品 | 0 |
| a_scene 资产·场景 | 0 |
| a_scene_open 资产·场景弹框 | 2 |
| a_voice 资产·音色 | 0 |
| a_sheets 资产·设定图 | 0 |
| a_preset 资产·预设 | 0 |
| a_loras 资产·LoRA | 0 |
| a_template 资产·模板 | 0 |
| sound 声音页 | 3 |
| cut 成片页 | 0 |
| trash 回收站 | 0 |
| audit 操作记录 | 0 |
| models 设置 / 模型 | 1 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●●● | 可点区域过小 | projects, script_new, script_read（1440d） | `div.ns-prod-ep > button.ns-prod-ep-h`<br>「第 1 集 首帧过契约 2/7 · 尾帧 0/7」 | apps/web/src/v3/ProducerPanel.tsx:145 | 527x22 | 可点区域只有 527×22px（<24 难点中）<br><sub>uipixel/bA1/projects_1440_dark_mark.png #2</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 2 | ●●● | 可点区域过小 | a_scene_open（1440d） | `span.ac-foot > button.ac-use`<br>「用在 2 集 · 10 镜 ›」 | apps/web/src/v3/assets/AssetCard.tsx:76<br>apps/web/src/v3/assets/center.css:81 | 97x15 | 可点区域只有 97×15px（<24 难点中）<br><sub>uipixel/bA1/a_scene_open_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 3 | ●●● | 可点区域过小 | edit_assets（1440d） | `li > a`<br>「↗」 | apps/web/src/v3/edit/ShotAssetsTab.tsx:128<br>apps/web/src/v3/edit/edit.css:477 | 18x15 | 可点区域只有 18×15px（<24 难点中）<br><sub>uipixel/bA1/edit_assets_1440_dark_mark.png #2</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 4 | ●● | 缺悬停态 | projects, script_new, script_read（1440d） | `div.ns-viewsw > button.on`<br>「每镜完整一行」 | apps/web/src/components/Dialogs.tsx:219<br>apps/web/src/canvas-v2.css:8 | hover+active | 缺少 悬停态、按下（点击反馈）<br><sub>uipixel/bA1/projects_1440_dark_mark.png #6</sub> | 加 :hover 背景（--c-hover） |
| 5 | ●● | 缺悬停态 | edit_assets（1440d） | `li.ar-slot > a.ar-img`<br>「图1」 | apps/web/src/v3/edit/AssetRefs.tsx:38<br>apps/web/src/v3/edit/edit.css:498 | hover | 缺少 悬停态<br><sub>uipixel/bA1/edit_assets_1440_dark_mark.png #3</sub> | 加 :hover 背景（--c-hover） |
| 6 | ●● | 缺悬停态 | edit_assets（1440d） | `li > a`<br>「↗」 | apps/web/src/v3/edit/ShotAssetsTab.tsx:128<br>apps/web/src/v3/edit/edit.css:477 | hover+active | 缺少 悬停态、按下（点击反馈）<br><sub>uipixel/bA1/edit_assets_1440_dark_mark.png #4</sub> | 加 :hover 背景（--c-hover） |
| 7 | ●● | 无手型指针 | a_linwan（1440d） | `header.hub-hero > button.hub-hero-face`<br>「当前身份脸 · 点开看大图」 | apps/web/src/v3/assets/PeopleHub.tsx:752<br>apps/web/src/v3/assets/people_hub.css:24 | zoom-in | 可点元素鼠标不是手型（cursor:zoom-in）<br><sub>uipixel/bA1/a_linwan_1440_dark_mark.png #1</sub> | cursor:pointer（全局 ds.css 规则） |
| 8 | ●● | 无手型指针 | a_linwan（1440d） | `figure.hub-face > button.hub-face-img`<br>「当前」 | apps/web/src/v3/assets/PeopleHub.tsx:319<br>apps/web/src/v3/assets/people_hub.css:52 | zoom-in | 可点元素鼠标不是手型（cursor:zoom-in）<br><sub>uipixel/bA1/a_linwan_1440_dark_mark.png #2</sub> | cursor:pointer（全局 ds.css 规则） |
| 9 | ●● | 无手型指针 | a_linwan（1440d） | `div.hub-sheet > button.hub-sheet-main`<br>「当前设定图」 | apps/web/src/v3/assets/PeopleHub.tsx:860<br>apps/web/src/v3/assets/people_hub.css:64 | zoom-in | 可点元素鼠标不是手型（cursor:zoom-in）<br><sub>uipixel/bA1/a_linwan_1440_dark_mark.png #4</sub> | cursor:pointer（全局 ds.css 规则） |
| 10 | ●● | 缺悬停态 | a_linwan（1440d） | `header.hub-hero > button.hub-hero-face`<br>「当前身份脸 · 点开看大图」 | apps/web/src/v3/assets/PeopleHub.tsx:752<br>apps/web/src/v3/assets/people_hub.css:24 | hover+active | 缺少 悬停态、按下（点击反馈）<br><sub>uipixel/bA1/a_linwan_1440_dark_mark.png #5</sub> | 加 :hover 背景（--c-hover） |
| 11 | ● | 可点区域过小 | edit_params, edit_versions（1440d） | `div.v3e-seg.sm > button`<br>「Turbo（快）」 | apps/web/src/components/Dialogs.tsx:219<br>apps/web/src/canvas-v2.css:8 | 104x24 | 可点区域 104×24px（<28）<br><sub>uipixel/bA1/edit_params_1440_dark_mark.png #2</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 12 | ● | 可点区域过小 | edit_params, edit_versions（1440d） | `div.v3e-seg.sm > button`<br>「普通」 | apps/web/src/v3/edit/AssetDrawer.tsx:832<br>apps/web/src/ds/ds.css:323 | 57x24 | 可点区域 57×24px（<28）<br><sub>uipixel/bA1/edit_params_1440_dark_mark.png #4</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 13 | ● | 可点区域过小 | projects, script_new, script_read（1440d） | `details.ns-old > summary`<br>「以前的稿子（1）」 | apps/web/src/v3/pages/NewScriptPage.tsx:150<br>apps/web/src/v3/pages/story.css:163 | 247x24 | 可点区域 247×24px（<28）<br><sub>uipixel/bA1/projects_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 14 | ● | 可点区域过小 | projects, script_new, script_read（1440d） | `details.ns-prod-log > summary.ds-small`<br>「自动修复记录（最近 1 条）」 | apps/web/src/ds/MediaPlayer.tsx:159<br>apps/web/src/ds/ds.css:122 | 1120x24 | 可点区域 1120×24px（<28）<br><sub>uipixel/bA1/projects_1440_dark_mark.png #5</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 15 | ● | 可点区域过小 | review, review_ep01, review_ep01_scroll（1440d） | `details.ds-tilebar-more > summary`<br>「⋯」 | apps/web/src/ds/TileBar.tsx:65<br>apps/web/src/ds/ds.css:220 | 24x28 | 可点区域 24×28px（<28）<br><sub>uipixel/bA1/review_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 16 | ● | 可点区域过小 | review, review_ep01, review_ep01_scroll（1440d） | `div.v3-rows > button.v3-seam.none`<br>「未检查」 | apps/web/src/v3/Canvas.tsx:86<br>apps/web/src/ds/ds.css:291 | 350x24 | 可点区域 350×24px（<28）<br><sub>uipixel/bA1/review_1440_dark_mark.png #2</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 17 | ● | 可点区域过小 | edit_ep01, edit, edit_rules（1440d） | `details.v3e-fold > summary`<br>「本镜分镜（剧本原文，只读）」 | apps/web/src/v3/edit/EditLoop.tsx:352<br>apps/web/src/ds/ds.css:290 | 331x24 | 可点区域 331×24px（<28）<br><sub>uipixel/bA1/edit_ep01_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 18 | ● | 可点区域过小 | sound（1440d） | `nav.v3p-tabs > button`<br>「角色音色 · 旁白」 | apps/web/src/components/Dialogs.tsx:219<br>apps/web/src/canvas-v2.css:8 | 100x25 | 可点区域 100×25px（<28）<br><sub>uipixel/bA1/sound_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 19 | ● | 可点区域过小 | review_ep01, review_ep01_scroll（1440d） | `span.ds-tilebar-st > button.v3-cand-old`<br>「旧图 ×1」 | apps/web/src/v3/ReviewRow.tsx:138<br>apps/web/src/ds/ds.css:235 | 54x24 | 可点区域 54×24px（<28）<br><sub>uipixel/bA1/review_ep01_1440_dark_mark.png #3</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 20 | ● | 可点区域过小 | edit_params, edit_versions（1440d） | `details.px-note.px-notefold > summary`<br>「项目方 选定（展开看细节）」 | apps/web/src/v3/edit/ImageParams.tsx:256<br>apps/web/src/v3/edit/edit.css:361 | 331x24 | 可点区域 331×24px（<28）<br><sub>uipixel/bA1/edit_params_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 21 | ● | 可点区域过小 | edit_params, edit_versions（1440d） | `div.px-loras > button.v3e-link`<br>「+ 加一个 LoRA」 | apps/web/src/v3/edit/EditLoop.tsx:260<br>apps/web/src/ds/ds.css:314 | 92x25 | 可点区域 92×25px（<28）<br><sub>uipixel/bA1/edit_params_1440_dark_mark.png #6</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 22 | ● | 可点区域过小 | overview（1440d） | `div.sea-eph > a.sea-epn`<br>「第 1 集」 | apps/web/src/v3/pages/SeasonPage.tsx:154<br>apps/web/src/ds/ds.css:314 | 52x26 | 可点区域 52×26px（<28）<br><sub>uipixel/bA1/overview_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 23 | ● | 可点区域过小 | overview（1440d） | `div.sea-eph > button.v3p-link.sea-selall`<br>「选中整集」 | apps/web/src/v3/edit/RightTabs.tsx:61<br>apps/web/src/v3/pages/pages.css:32 | 62x26 | 可点区域 62×26px（<28）<br><sub>uipixel/bA1/overview_1440_dark_mark.png #2</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 24 | ● | 可点区域过小 | overview（1440d） | `div.sea-eph > a.sea-epn`<br>「第 2 集」 | apps/web/src/v3/pages/SeasonPage.tsx:154<br>apps/web/src/ds/ds.css:314 | 52x26 | 可点区域 52×26px（<28）<br><sub>uipixel/bA1/overview_1440_dark_mark.png #3</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 25 | ● | 可点区域过小 | overview（1440d） | `div.sea-eph > button.v3p-link.sea-selall`<br>「选中整集」 | apps/web/src/v3/edit/RightTabs.tsx:61<br>apps/web/src/v3/pages/pages.css:32 | 62x26 | 可点区域 62×26px（<28）<br><sub>uipixel/bA1/overview_1440_dark_mark.png #4</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 26 | ● | 可点区域过小 | edit_assets（1440d） | `details.ar-note > summary`<br>「其他说明（1）」 | apps/web/src/v3/edit/AssetRefs.tsx:50<br>apps/web/src/v3/edit/edit.css:502 | 331x24 | 可点区域 331×24px（<28）<br><sub>uipixel/bA1/edit_assets_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 27 | ● | 可点区域过小 | edit_rules（1440d） | `details.v3e-fld > summary`<br>「视频提示词规则检查 都过了」 | apps/web/src/v3/edit/AssetDrawer.tsx:689<br>apps/web/src/v3/edit/edit.css:126 | 331x24 | 可点区域 331×24px（<28）<br><sub>uipixel/bA1/edit_rules_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 28 | ● | 可点区域过小 | a_linwan（1440d） | `figure.hub-face > button.hub-face-del`<br>「删除」 | apps/web/src/v3/assets/PeopleHub.tsx:338<br>apps/web/src/v3/assets/people_hub.css:237 | 40x24 | 可点区域 40×24px（<28）<br><sub>uipixel/bA1/a_linwan_1440_dark_mark.png #3</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 29 | ● | 可点区域过小 | models（1440d） | `div.v3p-card-head > button.btn-mini`<br>「刷新」 | apps/web/src/components/Dialogs.tsx:11<br>apps/web/src/canvas-v2.css:50 | 40x24 | 可点区域 40×24px（<28）<br><sub>uipixel/bA1/models_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |