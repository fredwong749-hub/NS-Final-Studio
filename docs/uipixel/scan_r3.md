# UIPIXEL 扫描 r3

生成：2026-10-31T20:28:02.101Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 31 个 × 尺寸 1280×720 / 1440×900 / 1920×1080 × 主题 dark / light = 截图 186 张（目录 apps/web/e2e/uipixel/r3/，主尺寸另有 _mark 标注图）
- **去重后问题 19 条**：严重 1 · 一般 3 · 轻微 15
- 分类：间距不在刻度 9 · 可点区域过小 4 · 左对齐 2 · 同类内边距 2 · z-index 遮挡 1 · 滚动嵌套 1

## 每页问题数

| 状态 | 1280 深 | 1280 浅 | 1440 深 | 1440 浅 | 1920 深 | 1920 浅 |
|---|---|---|---|---|---|---|
| projects 项目首页 | 3 | 3 | 3 | 3 | 3 | 0 |
| script_new 新建剧本 | 3 | 3 | 3 | 3 | 3 | 0 |
| script_read 剧本阅读模式 | 4 | 4 | 3 | 3 | 3 | 3 |
| overview 全剧总览 | 8 | 8 | 0 | 0 | 0 | 0 |
| review 画布·审片 | 3 | 3 | 4 | 4 | 3 | 3 |
| review_ep01 画布·审片（第 1 集，有图） | 3 | 3 | 4 | 4 | 3 | 3 |
| review_ep01_scroll 画布·审片（第 1 集，往下滚） | 3 | 3 | 4 | 4 | 3 | 3 |
| edit_ep01 画布·精修（第 1 集） | 2 | 2 | 2 | 2 | 2 | 2 |
| edit 画布·精修（提示词） | 2 | 2 | 2 | 2 | 2 | 2 |
| edit_params 精修·参数 | 2 | 2 | 3 | 3 | 3 | 3 |
| edit_versions 精修·版本 | 3 | 2 | 3 | 3 | 3 | 3 |
| edit_assets 精修·资产 | 2 | 2 | 2 | 2 | 2 | 2 |
| edit_sound 精修·声音 | 2 | 2 | 2 | 2 | 2 | 2 |
| edit_rules 精修·规则 | 3 | 2 | 3 | 3 | 3 | 3 |
| assets 资产中心 | 3 | 3 | 0 | 2 | 0 | 2 |
| a_character 资产·人物 | 3 | 3 | 0 | 2 | 0 | 2 |
| a_linwan 资产·人物页（林晚） | 3 | 3 | 0 | 2 | 0 | 2 |
| a_look 资产·形象 | 3 | 3 | 0 | 2 | 0 | 2 |
| a_item 资产·单品 | 3 | 3 | 0 | 2 | 0 | 2 |
| a_scene 资产·场景 | 3 | 3 | 0 | 2 | 0 | 2 |
| a_scene_open 资产·场景弹框 | 0 | 3 | 2 | 0 | 2 | 0 |
| a_voice 资产·音色 | 3 | 3 | 0 | 2 | 2 | 0 |
| a_sheets 资产·设定图 | 3 | 3 | 0 | 2 | 0 | 2 |
| a_preset 资产·预设 | 3 | 3 | 0 | 2 | 0 | 2 |
| a_loras 资产·LoRA | 3 | 3 | 0 | 2 | 0 | 2 |
| a_template 资产·模板 | 3 | 3 | 2 | 0 | 2 | 0 |
| sound 声音页 | 0 | 0 | 0 | 0 | 0 | 0 |
| cut 成片页 | 0 | 0 | 0 | 0 | 0 | 0 |
| trash 回收站 | 1 | 1 | 1 | 1 | 1 | 1 |
| audit 操作记录 | 0 | 0 | 0 | 0 | 0 | 0 |
| models 设置 / 模型 | 1 | 1 | 0 | 0 | 1 | 1 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●●● | z-index 遮挡 | script_read（1280d 1280l） | `span > button.ds-btn.ghost`<br>「暂停」 | apps/web/src/ds/MediaPlayer.tsx:260<br>apps/web/src/ds/ds.css:11 | nav.sf-steps | 被 div.sf-page > nav.sf-steps 盖住，点不到<br><sub>uipixel/r3/script_read_1280_dark.png #4</sub> | 调整层级或让遮挡层 pointer-events:none |
| 2 | ●● | 左对齐 | assets, a_character, a_linwan, a_look …（1280d 1280l 1440l 1920l 1440d 1920d） | `nav.ac-nav > div.ac-nav-h`<br>「② 资产中心」 | apps/web/src/v3/assets/AssetCenter.tsx:158<br>apps/web/src/v3/assets/center.css:8 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/r3/assets_1280_dark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 3 | ●● | 左对齐 | assets, a_character, a_linwan, a_look …（1280d 1280l 1440l 1920l 1440d 1920d） | `nav.ac-nav > div.ac-nav-g`<br>「人物 · 当前剧」 | apps/web/src/v3/assets/AssetCenter.tsx:162<br>apps/web/src/v3/assets/center.css:10 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/r3/assets_1280_dark.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 4 | ●● | 滚动嵌套 | edit_versions（1440d 1440l 1920d 1920l） | `div.v3e-ver > div.v3e-chain`<br>「#1 生成 过期·需重出 #2 生成 当前 #3」 | apps/web/src/v3/edit/VersionChain.tsx:132<br>apps/web/src/v3/edit/edit.css:229 | div.v3e-ver | 滚动区套在另一个滚动区（div.v3e-ver）里<br><sub>uipixel/r3/edit_versions_1440_dark_mark.png #3</sub> | 只保留一层滚动（内层改 overflow:visible 或外层固定高度） |
| 5 | ● | 间距不在刻度 | projects, script_new, script_read, overview …（1280d 1280l 1440d 1440l 1920d 1920l） | `div.sp-row > div.sp-seg.sp-script`<br>「剧本 10/10」 | apps/web/src/ds/StageProgress.tsx:91<br>apps/web/src/ds/live.css:29 | rowGap:3 | rowGap 3px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r3/projects_1280_dark.png #1</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 6 | ● | 间距不在刻度 | projects, script_new, script_read, overview …（1280d 1280l 1440d 1440l 1920d 1920l） | `div.sp-row > div.sp-seg.sp-script`<br>「剧本 10/10」 | apps/web/src/ds/StageProgress.tsx:91<br>apps/web/src/ds/live.css:29 | columnGap:3 | columnGap 3px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r3/projects_1280_dark.png #2</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 7 | ● | 间距不在刻度 | projects, script_new, script_read, review …（1280d 1280l 1440d 1440l 1920d 1920l） | `div.v3-info > div.v3-people`<br>「林晚 A 景 深夜写字楼办公区角落 无底图 分镜」 | apps/web/src/v3/ReviewRow.tsx:449<br>apps/web/src/v3/pages/story.css:222 | paddingLeft:38 | paddingLeft 38px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r3/projects_1280_dark.png #3</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 8 | ● | 间距不在刻度 | assets, a_character, a_linwan, a_look …（1280d 1280l） | `nav.ac-nav > div.ac-nav-foot`<br>「全部资产（卡片总览） 人物登记（新建 · 改名 」 | apps/web/src/v3/assets/AssetCenter.tsx:177<br>apps/web/src/v3/assets/center.css:18 | marginTop:58 | marginTop 58px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r3/assets_1280_dark.png #3</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 9 | ● | 间距不在刻度 | review, review_ep01, review_ep01_scroll（1440d 1440l） | `div.v3-info > div.v3-people`<br>「林晚 A 顾沉 A 电梯与楼道 分镜详情 ▸ 首」 | apps/web/src/v3/ReviewRow.tsx:449<br>apps/web/src/v3/pages/story.css:222 | marginTop:7 | marginTop 7px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r3/review_1440_dark_mark.png #4</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 10 | ● | 间距不在刻度 | trash（1280d 1280l 1440d 1440l 1920d 1920l） | `div.ed-trash > p.ds-muted`<br>「删除的剧本、版本、成片、资产都在这里（data/」 | apps/web/src/ds/editdel.tsx:181<br>apps/web/src/ds/ds.css:121 | marginTop:13 | marginTop 13px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r3/trash_1280_dark.png #1</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 11 | ● | 同类内边距 | edit_params, edit_versions（1440d 1440l 1920d 1920l 1280d） | `div.v3e-fld > div.v3e-ro`<br>「—」 | apps/web/src/v3/edit/EditCenter.tsx:765<br>apps/web/src/v3/edit/edit.css:212 | 8/8/8/8 | 同类卡片 .v3e-ro 内边距有 2 种（4/8/4/8 · 8/8/8/8）<br><sub>uipixel/r3/edit_params_1440_dark_mark.png #3</sub> | 同组卡片统一 padding（卡 16 / 紧凑卡 12） |
| 12 | ● | 同类内边距 | edit_rules（1280d 1440d 1440l 1920d 1920l） | `div.v3e-fld > div.v3e-ro`<br>「没有要你处理的」 | apps/web/src/v3/edit/EditCenter.tsx:765<br>apps/web/src/v3/edit/edit.css:212 | 8/8/8/8 | 同类卡片 .v3e-ro 内边距有 2 种（4/8/4/8 · 8/8/8/8）<br><sub>uipixel/r3/edit_rules_1280_dark.png #3</sub> | 同组卡片统一 padding（卡 16 / 紧凑卡 12） |
| 13 | ● | 间距不在刻度 | models（1280d 1280l 1920d 1920l） | `section.v3p-card > p.v3p-muted`<br>「加载中…」 | apps/web/src/v3/pages/AssetsPage.tsx:270<br>apps/web/src/v3/pages/pages.css:30 | marginTop:13 | marginTop 13px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r3/models_1280_dark.png #1</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 14 | ● | 间距不在刻度 | overview（1280d 1280l） | `button.sea-card > span.sea-cast`<br>「● ◐ · ·」 | apps/web/src/v3/pages/SeasonPage.tsx:207<br>apps/web/src/ds/ds.css:383 | marginTop:21 | marginTop 21px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r3/overview_1280_dark.png #3</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 15 | ● | 间距不在刻度 | overview（1280d 1280l） | `button.sea-card > span.sea-cast`<br>「● ● · ·」 | apps/web/src/v3/pages/SeasonPage.tsx:207<br>apps/web/src/ds/ds.css:383 | marginTop:23 | marginTop 23px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r3/overview_1280_dark.png #4</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 16 | ● | 可点区域过小 | overview（1280d 1280l） | `div.sea-eph > a.sea-epn`<br>「第 1 集」 | apps/web/src/v3/pages/SeasonPage.tsx:154<br>apps/web/src/ds/ds.css:314 | 52x26 | 可点区域 52×26px（<28）<br><sub>uipixel/r3/overview_1280_dark.png #5</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 17 | ● | 可点区域过小 | overview（1280d 1280l） | `div.sea-eph > button.v3p-link.sea-selall`<br>「选中整集」 | apps/web/src/v3/edit/RightTabs.tsx:62<br>apps/web/src/ds/ds.css:434 | 62x26 | 可点区域 62×26px（<28）<br><sub>uipixel/r3/overview_1280_dark.png #6</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 18 | ● | 可点区域过小 | overview（1280d 1280l） | `div.sea-eph > a.sea-epn`<br>「第 2 集」 | apps/web/src/v3/pages/SeasonPage.tsx:154<br>apps/web/src/ds/ds.css:314 | 52x26 | 可点区域 52×26px（<28）<br><sub>uipixel/r3/overview_1280_dark.png #7</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 19 | ● | 可点区域过小 | overview（1280d 1280l） | `div.sea-eph > button.v3p-link.sea-selall`<br>「选中整集」 | apps/web/src/v3/edit/RightTabs.tsx:62<br>apps/web/src/ds/ds.css:434 | 62x26 | 可点区域 62×26px（<28）<br><sub>uipixel/r3/overview_1280_dark.png #8</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |