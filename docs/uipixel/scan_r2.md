# UIPIXEL 扫描 r2

生成：2026-10-31T19:44:27.196Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 31 个 × 尺寸 1280×720 / 1440×900 / 1920×1080 × 主题 dark / light = 截图 186 张（目录 apps/web/e2e/uipixel/r2/，主尺寸另有 _mark 标注图）
- **去重后问题 43 条**：严重 1 · 一般 12 · 轻微 30
- 分类：可点区域过小 21 · 左对齐 10 · 间距不在刻度 7 · 同类内边距 2 · 文字/按钮重叠 1 · 标签/控件垂直居中 1 · 展开收起跳动 1

## 每页问题数

| 状态 | 1280 深 | 1280 浅 | 1440 深 | 1440 浅 | 1920 深 | 1920 浅 |
|---|---|---|---|---|---|---|
| projects 项目首页 | 6 | 6 | 6 | 6 | 7 | 0 |
| script_new 新建剧本 | 6 | 6 | 6 | 6 | 7 | 0 |
| script_read 剧本阅读模式 | 5 | 5 | 6 | 6 | 7 | 5 |
| overview 全剧总览 | 0 | 0 | 0 | 0 | 0 | 0 |
| review 画布·审片 | 6 | 6 | 6 | 6 | 7 | 6 |
| review_ep01 画布·审片（第 1 集，有图） | 6 | 6 | 5 | 6 | 7 | 7 |
| review_ep01_scroll 画布·审片（第 1 集，往下滚） | 4 | 4 | 6 | 6 | 7 | 7 |
| edit_ep01 画布·精修（第 1 集） | 3 | 3 | 4 | 4 | 8 | 8 |
| edit 画布·精修（提示词） | 3 | 3 | 4 | 4 | 8 | 8 |
| edit_params 精修·参数 | 10 | 10 | 10 | 10 | 14 | 14 |
| edit_versions 精修·版本 | 10 | 10 | 10 | 4 | 8 | 8 |
| edit_assets 精修·资产 | 5 | 5 | 2 | 6 | 10 | 8 |
| edit_sound 精修·声音 | 3 | 3 | 3 | 3 | 7 | 7 |
| edit_rules 精修·规则 | 6 | 2 | 6 | 6 | 10 | 10 |
| assets 资产中心 | 5 | 5 | 0 | 2 | 0 | 3 |
| a_character 资产·人物 | 4 | 5 | 0 | 3 | 0 | 3 |
| a_linwan 资产·人物页（林晚） | 5 | 5 | 3 | 0 | 3 | 0 |
| a_look 资产·形象 | 5 | 5 | 0 | 0 | 3 | 3 |
| a_item 资产·单品 | 0 | 0 | 2 | 0 | 0 | 2 |
| a_scene 资产·场景 | 4 | 8 | 2 | 0 | 6 | 0 |
| a_scene_open 资产·场景弹框 | 4 | 8 | 0 | 6 | 0 | 6 |
| a_voice 资产·音色 | 4 | 4 | 2 | 2 | 0 | 2 |
| a_sheets 资产·设定图 | 3 | 4 | 2 | 2 | 0 | 0 |
| a_preset 资产·预设 | 4 | 4 | 0 | 0 | 2 | 0 |
| a_loras 资产·LoRA | 0 | 4 | 0 | 2 | 0 | 0 |
| a_template 资产·模板 | 4 | 4 | 2 | 2 | 0 | 0 |
| sound 声音页 | 0 | 0 | 0 | 0 | 0 | 0 |
| cut 成片页 | 0 | 0 | 0 | 0 | 0 | 0 |
| trash 回收站 | 1 | 1 | 1 | 0 | 1 | 1 |
| audit 操作记录 | 1 | 1 | 9 | 1 | 1 | 0 |
| models 设置 / 模型 | 2 | 2 | 1 | 1 | 1 | 2 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●●● | 文字/按钮重叠 | review, review_ep01（1280d 1280l） | `details.ds-tilebar-more > summary`<br>「⋯」 | apps/web/src/ds/TileBar.tsx:68<br>apps/web/src/ds/ds.css:220 | 20x15 | 和「尾帧候选」（span）重叠 20×15px，字 / 按钮互相压住<br><sub>uipixel/r2/review_1280_dark.png #6</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 2 | ●● | 左对齐 | assets, a_character, a_linwan, a_look …（1280d 1280l 1440l 1920l 1440d 1920d） | `nav.ac-nav > div.ac-nav-h`<br>「② 资产中心」 | apps/web/src/v3/assets/AssetCenter.tsx:158<br>apps/web/src/v3/assets/center.css:8 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/r2/assets_1280_dark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 3 | ●● | 左对齐 | assets, a_character, a_linwan, a_look …（1280d 1280l 1440l 1920l 1440d 1920d） | `nav.ac-nav > div.ac-nav-g`<br>「人物 · 当前剧」 | apps/web/src/v3/assets/AssetCenter.tsx:162<br>apps/web/src/v3/assets/center.css:10 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/r2/assets_1280_dark.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 4 | ●● | 标签/控件垂直居中 | projects, script_new, script_read（1280d 1280l 1440d 1440l 1920d 1920l） | `div.ns-rh-t > span.ds-tag.ok`<br>「写完了」 | apps/web/src/v3/assets/AssetCard.tsx:40<br>apps/web/src/ds/ds.css:36 | 4.5px | 胶囊 / 标签和同行文字中线差 4.5px<br><sub>uipixel/r2/projects_1280_dark.png #4</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |
| 5 | ●● | 左对齐 | edit_ep01, edit, edit_params, edit_versions …（1920d 1920l） | `aside.v3-rail.v3-lib > div.v3-rail-h`<br>「资产库 «」 | apps/web/src/v3/LeftRail.tsx:154<br>apps/web/src/v3/ux4.css:42 | 4px | 和同组兄弟左边缘差 4px（同组应左对齐）<br><sub>uipixel/r2/edit_ep01_1920_dark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 6 | ●● | 左对齐 | edit_ep01, edit, edit_params, edit_versions …（1920d 1920l） | `aside.v3-rail.v3-lib > p.v3-lib-hint`<br>「点标“本镜”的卡 = 换 S1 的参考」 | apps/web/src/v3/LeftRail.tsx:181<br>apps/web/src/v3/ux4.css:54 | 4px | 和同组兄弟左边缘差 4px（同组应左对齐）<br><sub>uipixel/r2/edit_ep01_1920_dark.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 7 | ●● | 左对齐 | edit_ep01, edit, edit_params, edit_versions …（1920d 1920l） | `div.v3-edit > div.v3-edit-center`<br>「首帧 · #7 ✎ 改 🗑 ⛶ 全屏看首尾帧 」 | apps/web/src/v3/Canvas.tsx:362<br>apps/web/src/v3/v3.css:361 | 3px | 和同组兄弟左边缘差 3px（同组应左对齐）<br><sub>uipixel/r2/edit_ep01_1920_dark.png #3</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 8 | ●● | 展开收起跳动 | audit（1440d） | `details.audit-raw > summary`<br>「技术详情」 | apps/web/src/v3/AuditDrawer.tsx:65<br>apps/web/src/ds/ds.css:406 | -66,0 | 展开 / 收起后触发按钮自己移动了 (-66, 0)px<br><sub>uipixel/r2/audit_1440_dark_mark.png #2</sub> | 展开内容放在触发器下方；触发器不随内容高度改变位置 |
| 9 | ●● | 左对齐 | review, review_ep01, review_ep01_scroll（1920d 1920l） | `aside.v3-rail.v3-lib > div.v3-rail-h`<br>「资产库 «」 | apps/web/src/v3/LeftRail.tsx:154<br>apps/web/src/v3/ux4.css:42 | 4px | 和同组兄弟左边缘差 4px（同组应左对齐）<br><sub>uipixel/r2/review_1920_dark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 10 | ●● | 左对齐 | edit_assets（1280d 1280l 1440l 1920d 1920l） | `aside.v3-right > div.v3-right-body`<br>「出首帧用的参考 参考齐了 图1 脸 · 林晚的脸」 | apps/web/src/v3/Canvas.tsx:161<br>apps/web/src/v3/v3.css:368 | 2px | 和同组兄弟左边缘差 2px（同组应左对齐）<br><sub>uipixel/r2/edit_assets_1280_dark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 11 | ●● | 左对齐 | a_scene, a_scene_open（1280l 1920d 1440l 1920l） | `article.ac-card.ac-r169 > span.ac-foot`<br>「用在 2 集 · 10 镜 ›」 | apps/web/src/v3/assets/AssetCard.tsx:73<br>apps/web/src/v3/assets/center.css:80 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/r2/a_scene_1280_light.png #3</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 12 | ●● | 左对齐 | a_scene, a_scene_open（1280l 1920d 1440l 1920l） | `button.ac-card-hit > span.ac-meta`<br>「深夜写字楼办公区角落 v1 画布已定稿（待项目方」 | apps/web/src/v3/assets/AssetCard.tsx:53<br>apps/web/src/v3/assets/center.css:75 | 12px | 和同组兄弟左边缘差 12px（同组应左对齐）<br><sub>uipixel/r2/a_scene_1280_light.png #4</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 13 | ●● | 左对齐 | edit_versions（1440l 1920d 1920l） | `div.v3e-chain > button.node`<br>「#2 生成 当前」 | apps/web/src/v3/assets/AssetCenter.tsx:171<br>apps/web/src/v3/edit/edit.css:230 | -8px | 和同组兄弟左边缘差 -8px（同组应左对齐）<br><sub>uipixel/r2/edit_versions_1440_light_mark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 14 | ● | 间距不在刻度 | projects, script_new, script_read, review …（1280d 1280l 1440d 1440l 1920d 1920l） | `div.sp-row > div.sp-seg.sp-script`<br>「剧本 10/10」 | apps/web/src/ds/StageProgress.tsx:91<br>apps/web/src/ds/live.css:29 | rowGap:3 | rowGap 3px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r2/projects_1280_dark.png #1</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 15 | ● | 间距不在刻度 | projects, script_new, script_read, review …（1280d 1280l 1440d 1440l 1920d 1920l） | `div.sp-row > div.sp-seg.sp-script`<br>「剧本 10/10」 | apps/web/src/ds/StageProgress.tsx:91<br>apps/web/src/ds/live.css:29 | columnGap:3 | columnGap 3px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r2/projects_1280_dark.png #2</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 16 | ● | 间距不在刻度 | projects, script_new, script_read, review …（1280d 1280l 1440d 1440l 1920d 1920l） | `div.v3-info > div.v3-people`<br>「林晚 A 景 深夜写字楼办公区角落 无底图 分镜」 | apps/web/src/v3/ReviewRow.tsx:449<br>apps/web/src/v3/pages/story.css:222 | paddingLeft:38 | paddingLeft 38px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r2/projects_1280_dark.png #3</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 17 | ● | 可点区域过小 | edit_ep01, edit, edit_params, edit_versions …（1280d 1280l 1920d 1920l） | `details.v3e-fold.v3e-h3full > summary`<br>「视频提示词（完整）」 | apps/web/src/v3/edit/EditCenter.tsx:770<br>apps/web/src/ds/ds.css:290 | 442x24 | 可点区域 442×24px（<28）<br><sub>uipixel/r2/edit_ep01_1280_dark.png #3</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 18 | ● | 可点区域过小 | assets, a_character, a_linwan, a_look …（1280d 1280l） | `div > button.ac-nav-i.in`<br>「出图预设 10」 | apps/web/src/v3/assets/AssetCenter.tsx:171<br>apps/web/src/v3/assets/center.css:11 | 155x24 | 可点区域 155×24px（<28）<br><sub>uipixel/r2/assets_1280_dark.png #4</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 19 | ● | 可点区域过小 | review, review_ep01, review_ep01_scroll, edit_ep01 …（1920d 1920l） | `div.v3-lib-scope > button`<br>「本集」 | apps/web/src/components/Dialogs.tsx:224<br>apps/web/src/canvas-v2.css:8 | 40x26 | 可点区域 40×26px（<28）<br><sub>uipixel/r2/review_1920_dark.png #5</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 20 | ● | 间距不在刻度 | assets, a_character, a_linwan, a_look …（1280d 1280l） | `nav.ac-nav > div.ac-nav-foot`<br>「全部资产（卡片总览） 人物登记（新建 · 改名 」 | apps/web/src/v3/assets/AssetCenter.tsx:177<br>apps/web/src/v3/assets/center.css:18 | marginTop:58 | marginTop 58px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r2/assets_1280_dark.png #3</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 21 | ● | 可点区域过小 | edit_params, edit_versions（1280d 1280l 1440d 1440l 1920d 1920l） | `div.v3e-seg.sm > button`<br>「Turbo（快）」 | apps/web/src/components/Dialogs.tsx:224<br>apps/web/src/canvas-v2.css:8 | 104x24 | 可点区域 104×24px（<28）<br><sub>uipixel/r2/edit_params_1280_dark.png #6</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 22 | ● | 可点区域过小 | edit_params, edit_versions（1280d 1280l 1440d 1440l 1920d 1920l） | `div.v3e-seg.sm > button`<br>「普通」 | apps/web/src/v3/edit/AssetDrawer.tsx:832<br>apps/web/src/ds/ds.css:323 | 57x24 | 可点区域 57×24px（<28）<br><sub>uipixel/r2/edit_params_1280_dark.png #8</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 23 | ● | 可点区域过小 | projects, script_new, script_read, review …（1920d 1280d 1280l 1440d 1440l 1920l） | `div.v3-cand-bar > button.v3-cand-use`<br>「用这张」 | apps/web/src/v3/ReviewRow.tsx:125<br>apps/web/src/v3/candidates.css:30 | 140x24 | 可点区域 140×24px（<28）<br><sub>uipixel/r2/projects_1920_dark.png #7</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 24 | ● | 可点区域过小 | projects, script_new, script_read（1280d 1280l 1440d 1440l 1920d 1920l） | `details.ns-old > summary`<br>「以前的稿子（1）」 | apps/web/src/v3/pages/NewScriptPage.tsx:150<br>apps/web/src/v3/pages/story.css:163 | 207x24 | 可点区域 207×24px（<28）<br><sub>uipixel/r2/projects_1280_dark.png #5</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 25 | ● | 可点区域过小 | projects, script_new, script_read（1280d 1280l 1440d 1440l 1920d 1920l） | `details.ns-prod-log > summary.ds-small`<br>「自动修复记录（最近 2 条）」 | apps/web/src/ds/MediaPlayer.tsx:159<br>apps/web/src/ds/ds.css:122 | 990x24 | 可点区域 990×24px（<28）<br><sub>uipixel/r2/projects_1280_dark.png #6</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 26 | ● | 可点区域过小 | assets, a_character, a_linwan, a_look（1280d 1280l 1920l 1440l 1440d 1920d） | `figure.hub-face > button.hub-face-del`<br>「删除」 | apps/web/src/v3/assets/PeopleHub.tsx:338<br>apps/web/src/v3/assets/people_hub.css:237 | 40x24 | 可点区域 40×24px（<28）<br><sub>uipixel/r2/assets_1280_dark.png #5</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 27 | ● | 可点区域过小 | edit_ep01, edit, edit_params, edit_versions …（1440d 1440l） | `details.v3e-fold.v3e-h3full > summary`<br>「视频提示词（完整）」 | apps/web/src/v3/edit/EditCenter.tsx:770<br>apps/web/src/ds/ds.css:290 | 492x24 | 可点区域 492×24px（<28）<br><sub>uipixel/r2/edit_ep01_1440_dark_mark.png #3</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 28 | ● | 可点区域过小 | edit_ep01, edit, edit_rules（1440d 1440l 1920d 1920l 1280d） | `details.v3e-fold > summary`<br>「本镜分镜（剧本原文，只读）」 | apps/web/src/v3/edit/EditCenter.tsx:770<br>apps/web/src/ds/ds.css:290 | 331x24 | 可点区域 331×24px（<28）<br><sub>uipixel/r2/edit_ep01_1440_dark_mark.png #4</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 29 | ● | 可点区域过小 | review, review_ep01, review_ep01_scroll（1280d 1280l 1440d 1440l） | `div.v3-rows > button.v3-seam.none`<br>「未检查」 | apps/web/src/v3/Canvas.tsx:86<br>apps/web/src/ds/ds.css:291 | 300x24 | 可点区域 300×24px（<28）<br><sub>uipixel/r2/review_1280_dark.png #5</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 30 | ● | 可点区域过小 | a_scene, a_scene_open（1280l 1920d 1440l 1920l） | `span.ac-foot > button.ac-use`<br>「用在 2 集 · 10 镜 ›」 | apps/web/src/v3/assets/AssetCard.tsx:76<br>apps/web/src/v3/assets/center.css:81 | 105x24 | 可点区域 105×24px（<28）<br><sub>uipixel/r2/a_scene_1280_light.png #7</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 31 | ● | 同类内边距 | edit_params, edit_versions（1280d 1280l 1440d 1440l 1920d 1920l） | `div.v3e-fld > div.v3e-ro`<br>「—」 | apps/web/src/v3/edit/EditCenter.tsx:765<br>apps/web/src/v3/edit/edit.css:212 | 8/8/8/8 | 同类卡片 .v3e-ro 内边距有 2 种（4/8/4/8 · 8/8/8/8）<br><sub>uipixel/r2/edit_params_1280_dark.png #3</sub> | 同组卡片统一 padding（卡 16 / 紧凑卡 12） |
| 32 | ● | 可点区域过小 | edit_params, edit_versions（1280d 1280l 1440d 1440l 1920d 1920l） | `details.px-note.px-notefold > summary`<br>「项目方 选定（展开看细节）」 | apps/web/src/v3/edit/ImageParams.tsx:256<br>apps/web/src/v3/edit/edit.css:361 | 331x24 | 可点区域 331×24px（<28）<br><sub>uipixel/r2/edit_params_1280_dark.png #5</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 33 | ● | 可点区域过小 | edit_params, edit_versions（1280d 1280l 1440d 1440l 1920d 1920l） | `div.px-loras > button.v3e-link`<br>「+ 加一个 LoRA」 | apps/web/src/v3/edit/EditLoop.tsx:260<br>apps/web/src/ds/ds.css:314 | 92x25 | 可点区域 92×25px（<28）<br><sub>uipixel/r2/edit_params_1280_dark.png #10</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 34 | ● | 间距不在刻度 | review, review_ep01, review_ep01_scroll（1440d 1440l） | `div.v3-info > div.v3-people`<br>「林晚 A 顾沉 A 景 场景未标 分镜详情 ▸ 」 | apps/web/src/v3/ReviewRow.tsx:449<br>apps/web/src/v3/pages/story.css:222 | marginTop:7 | marginTop 7px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r2/review_1440_dark_mark.png #4</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 35 | ● | 可点区域过小 | review, review_ep01, review_ep01_scroll（1920d 1920l） | `div.v3-rows > button.v3-seam.none`<br>「未检查」 | apps/web/src/v3/Canvas.tsx:86<br>apps/web/src/ds/ds.css:291 | 451x24 | 可点区域 451×24px（<28）<br><sub>uipixel/r2/review_1920_dark.png #7</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 36 | ● | 可点区域过小 | models（1280d 1280l 1440d 1440l 1920d 1920l） | `div.v3p-card-head > button.btn-mini`<br>「刷新」 | apps/web/src/components/Dialogs.tsx:16<br>apps/web/src/canvas-v2.css:50 | 40x24 | 可点区域 40×24px（<28）<br><sub>uipixel/r2/models_1280_dark.png #2</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 37 | ● | 同类内边距 | edit_rules（1280d 1440d 1440l 1920d 1920l） | `div.v3e-fld > div.v3e-ro`<br>「没有要你处理的」 | apps/web/src/v3/edit/EditCenter.tsx:765<br>apps/web/src/v3/edit/edit.css:212 | 8/8/8/8 | 同类卡片 .v3e-ro 内边距有 2 种（4/8/4/8 · 8/8/8/8）<br><sub>uipixel/r2/edit_rules_1280_dark.png #3</sub> | 同组卡片统一 padding（卡 16 / 紧凑卡 12） |
| 38 | ● | 可点区域过小 | edit_rules（1280d 1440d 1440l 1920d 1920l） | `details.v3e-fld > summary`<br>「视频提示词规则检查 都过了」 | apps/web/src/v3/edit/AssetDrawer.tsx:689<br>apps/web/src/ds/ds.css:375 | 331x24 | 可点区域 331×24px（<28）<br><sub>uipixel/r2/edit_rules_1280_dark.png #5</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 39 | ● | 间距不在刻度 | trash（1280d 1280l 1440d 1920d 1920l） | `div.ed-trash > p.ds-muted`<br>「删除的剧本、版本、成片、资产都在这里（data/」 | apps/web/src/ds/editdel.tsx:181<br>apps/web/src/ds/ds.css:121 | marginTop:13 | marginTop 13px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r2/trash_1280_dark.png #1</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 40 | ● | 可点区域过小 | audit（1280d 1280l 1440d 1440l 1920d） | `details.audit-raw > summary`<br>「技术详情」 | apps/web/src/v3/AuditDrawer.tsx:65<br>apps/web/src/ds/ds.css:406 | 61x24 | 可点区域 61×24px（<28）<br><sub>uipixel/r2/audit_1280_dark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 41 | ● | 可点区域过小 | edit_assets（1280d 1280l 1440l 1920d） | `details.ar-note > summary`<br>「其他说明（1）」 | apps/web/src/v3/edit/AssetRefs.tsx:50<br>apps/web/src/v3/edit/edit.css:502 | 331x24 | 可点区域 331×24px（<28）<br><sub>uipixel/r2/edit_assets_1280_dark.png #5</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 42 | ● | 间距不在刻度 | models（1280d 1280l 1920l） | `section.v3p-card > p.v3p-muted`<br>「加载中…」 | apps/web/src/v3/pages/AssetsPage.tsx:270<br>apps/web/src/v3/pages/pages.css:30 | marginTop:13 | marginTop 13px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/r2/models_1280_dark.png #1</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 43 | ● | 可点区域过小 | edit_assets（1440l 1920d） | `li > a`<br>「↗」 | apps/web/src/v3/edit/ShotAssetsTab.tsx:128<br>apps/web/src/ds/ds.css:329 | 24x24 | 可点区域 24×24px（<28）<br><sub>uipixel/r2/edit_assets_1440_light_mark.png #6</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |