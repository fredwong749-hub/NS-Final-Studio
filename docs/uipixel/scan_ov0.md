# UIPIXEL 扫描 ov0

生成：2026-10-31T16:59:25.966Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 31 个 × 尺寸 1280×720 / 1440×900 / 1920×1080 × 主题 dark = 截图 93 张（目录 apps/web/e2e/uipixel/ov0/，主尺寸另有 _mark 标注图）
- **去重后问题 25 条**：严重 25 · 一般 0 · 轻微 0
- 分类：文字/按钮重叠 25
- 扫描中被拦下的写请求（未发出）：POST /api/voices/preview

## 每页问题数

| 状态 | 1280 深 | 1440 深 | 1920 深 |
|---|---|---|---|
| projects 项目首页 | 6 | 7 | 5 |
| script_new 新建剧本 | 6 | 7 | 5 |
| script_read 剧本阅读模式 | 2 | 3 | 3 |
| overview 全剧总览 | 0 | 0 | 0 |
| review 画布·审片 | 1 | 1 | 0 |
| review_ep01 画布·审片（第 1 集，有图） | 6 | 5 | 5 |
| review_ep01_scroll 画布·审片（第 1 集，往下滚） | 1 | 0 | 0 |
| edit_ep01 画布·精修（第 1 集） | 0 | 0 | 10 |
| edit 画布·精修（提示词） | 2 | 0 | 24 |
| edit_params 精修·参数 | 8 | 6 | 6 |
| edit_versions 精修·版本 | 8 | 6 | 6 |
| edit_assets 精修·资产 | 3 | 1 | 1 |
| edit_sound 精修·声音 | 2 | 0 | 0 |
| edit_rules 精修·规则 | 2 | 0 | 0 |
| assets 资产中心 | 0 | 0 | 0 |
| a_character 资产·人物 | 0 | 0 | 0 |
| a_linwan 资产·人物页（林晚） | 0 | 0 | 0 |
| a_look 资产·形象 | 0 | 0 | 0 |
| a_item 资产·单品 | 0 | 0 | 0 |
| a_scene 资产·场景 | 0 | 0 | 0 |
| a_scene_open 资产·场景弹框 | 0 | 0 | 0 |
| a_voice 资产·音色 | 0 | 0 | 0 |
| a_sheets 资产·设定图 | 0 | 0 | 0 |
| a_preset 资产·预设 | 0 | 0 | 0 |
| a_loras 资产·LoRA | 0 | 0 | 0 |
| a_template 资产·模板 | 0 | 0 | 0 |
| sound 声音页 | 0 | 0 | 0 |
| cut 成片页 | 0 | 0 | 0 |
| trash 回收站 | 0 | 0 | 0 |
| audit 操作记录 | 0 | 0 | 0 |
| models 设置 / 模型 | 0 | 0 | 0 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●●● | 文字/按钮重叠 | projects, script_new, review_ep01（1280d 1440d 1920d） | `span.ed-tile-acts > button.ds-btn.xs`<br>「✎ 改」 | apps/web/src/ds/MediaPlayer.tsx:260<br>apps/web/src/ds/ds.css:11 | 24x15 | 和「过期」（span）重叠 24×15px，字 / 按钮互相压住<br><sub>uipixel/ov0/projects_1280_dark.png #3</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 2 | ●●● | 文字/按钮重叠 | projects, script_new, script_read, review …（1280d 1440d 1920d） | `div.v3-field > p.v3-one`<br>「睫毛轻颤，齐刘海垂在眉前，自然深棕色眼睛，嘴角轻」 | apps/web/src/v3/ReviewRow.tsx:382<br>apps/web/src/v3/ux4.css:84 | 286x12 | 和「林晚的手指在键盘上敲了两下停住，」（p.v3-script）重叠 286×12px，字 / 按钮互相压住<br><sub>uipixel/ov0/projects_1280_dark.png #6</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 3 | ●●● | 文字/按钮重叠 | edit, edit_params, edit_versions, edit_assets …（1280d） | `header.v3-head > button.v3-btn.sm`<br>「全选本集」 | apps/web/src/v3/Canvas.tsx:215<br>apps/web/src/ds/ds.css:132 | 49x28 | 和「8 镜待补：亲密镜头缺亲密声 ·」（button.sb-chip.bad）重叠 49×28px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_1280_dark.png #1</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 4 | ●●● | 文字/按钮重叠 | projects, script_new, script_read（1280d 1440d 1920d） | `div.ns-run-wrap > button.ns-run`<br>「漆皮之下·十日 · 10 集 写完了 10-31」 | apps/web/src/v3/pages/NewScriptPage.tsx:184<br>apps/web/src/v3/pages/story.css:8 | 34x24 | 和「🗑」（button.ds-btn.danger）重叠 34×24px，字 / 按钮互相压住<br><sub>uipixel/ov0/projects_1280_dark.png #1</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 5 | ●●● | 文字/按钮重叠 | projects, script_new, review_ep01（1280d 1440d 1920d） | `div.jobbar.running > span`<br>「渲染中 7:43」 | apps/web/src/components/frames.tsx:31<br>apps/web/src/canvas-v3.css:31 | 24x13 | 和「过期」（span）重叠 24×13px，字 / 按钮互相压住<br><sub>uipixel/ov0/projects_1280_dark.png #2</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 6 | ●●● | 文字/按钮重叠 | edit_ep01, edit（1920d） | `details.v3e-fold > summary`<br>「尾帧提示词」 | apps/web/src/v3/edit/EditLoop.tsx:352<br>apps/web/src/v3/edit/edit.css:348 | 24x5 | 和「dt」（dt）重叠 24×5px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_ep01_1920_dark.png #1</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 7 | ●●● | 文字/按钮重叠 | projects, script_new, review_ep01（1280d 1440d 1920d） | `span.ed-tile-acts > button.ds-btn.danger`<br>「🗑」 | apps/web/src/ds/MediaPlayer.tsx:260<br>apps/web/src/ds/ds.css:11 | 16x15 | 和「需重出」（span）重叠 16×15px，字 / 按钮互相压住<br><sub>uipixel/ov0/projects_1280_dark.png #5</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 8 | ●●● | 文字/按钮重叠 | edit_ep01, edit（1920d） | `label.v3e-fld > textarea.grow.sm` | apps/web/src/components/Dialogs.tsx:100<br>apps/web/src/components/people.css:8 | 104x6 | 和「div」（div.sb-txt）重叠 104×6px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_ep01_1920_dark.png #4</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 9 | ●●● | 文字/按钮重叠 | edit_params, edit_versions（1280d 1440d 1920d） | `div.px-sh > b`<br>「模型」 | apps/web/src/v3/edit/ImageParams.tsx:118<br>apps/web/src/v3/edit/edit.css:363 | 24x14 | 和「项目方 选定（展开看细节）」（details.px-note.px-notefold）重叠 24×14px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_params_1280_dark.png #3</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 10 | ●●● | 文字/按钮重叠 | edit_params, edit_versions（1280d 1440d 1920d） | `div.v3e-seg.sm > button`<br>「Turbo（快）」 | apps/web/src/components/Dialogs.tsx:219<br>apps/web/src/canvas-v2.css:8 | 104x14 | 和「项目方 选定（展开看细节）」（details.px-note.px-notefold）重叠 104×14px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_params_1280_dark.png #4</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 11 | ●●● | 文字/按钮重叠 | edit_params, edit_versions（1280d 1440d 1920d） | `div.px-sec > div.px-note`<br>「Turbo 用官方固定 8 步 sigma、cf」 | apps/web/src/v3/edit/ImageParams.tsx:256<br>apps/web/src/v3/edit/edit.css:361 | 303x2 | 和「项目方 选定（展开看细节）」（details.px-note.px-notefold）重叠 303×2px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_params_1280_dark.png #5</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 12 | ●●● | 文字/按钮重叠 | edit_params, edit_versions（1280d 1440d 1920d） | `label.px-row.off > span.k`<br>「步数」 | apps/web/src/components/Dialogs.tsx:219<br>apps/web/src/v3/edit/edit.css:174 | 24x11 | 和「项目方 选定（展开看细节）」（details.px-note.px-notefold）重叠 24×11px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_params_1280_dark.png #6</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 13 | ●●● | 文字/按钮重叠 | edit_params, edit_versions（1280d 1440d 1920d） | `label.px-row.off > input` | apps/web/src/v3/edit/ImageParams.tsx:97<br>apps/web/src/v3/edit/edit.css:368 | 157x13 | 和「项目方 选定（展开看细节）」（details.px-note.px-notefold）重叠 157×13px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_params_1280_dark.png #7</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 14 | ●●● | 文字/按钮重叠 | edit_params, edit_versions（1280d 1440d 1920d） | `label.px-row.off > input.n` | apps/web/src/components/Drawer.tsx:62<br>apps/web/src/v3/edit/edit.css:374 | 62x15 | 和「项目方 选定（展开看细节）」（details.px-note.px-notefold）重叠 62×15px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_params_1280_dark.png #8</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 15 | ●●● | 文字/按钮重叠 | edit_ep01, edit（1920d） | `label.v3e-fld > span.k` | apps/web/src/components/Dialogs.tsx:219<br>apps/web/src/v3/edit/edit.css:174 | 24x13 | 和「dt」（dt）重叠 24×13px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_ep01_1920_dark.png #8</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 16 | ●●● | 文字/按钮重叠 | edit（1920d） | `label.v3e-fld > textarea.grow.sm` | apps/web/src/components/Dialogs.tsx:100<br>apps/web/src/components/people.css:8 | 325x16 | 和「div」（div.sb-txt）重叠 325×16px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_1920_dark.png #9</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 17 | ●●● | 文字/按钮重叠 | edit（1920d） | `div.v3e-fld > span` | apps/web/src/v3/edit/AssetDrawer.tsx:689<br>apps/web/src/v3/edit/edit.css:126 | 60x15 | 和「textarea」（textarea.grow.sm）重叠 60×15px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_1920_dark.png #14</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 18 | ●●● | 文字/按钮重叠 | edit（1920d） | `div.v3e-fld > div.v3e-ro` | apps/web/src/v3/edit/EditLoop.tsx:368<br>apps/web/src/v3/edit/edit.css:212 | 18x2 | 和「dt」（dt）重叠 18×2px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_1920_dark.png #21</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 19 | ●●● | 文字/按钮重叠 | edit_assets（1280d 1440d 1920d） | `section.ar-wrap > p.ar-note`<br>「参考图位置不够、改用文字描述的：场景」 | apps/web/src/v3/edit/AssetRefs.tsx:50<br>apps/web/src/v3/edit/edit.css:502 | 72x7 | 和「p」（p.ar-note）重叠 72×7px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_assets_1280_dark.png #3</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 20 | ●●● | 文字/按钮重叠 | projects, script_new（1440d） | `span.v3-dl > em`<br>「独白：」 | apps/web/src/v3/ReviewRow.tsx:392<br>apps/web/src/v3/v3.css:316 | 39x8 | 和「static shot 固定机位」（p.v3-script）重叠 39×8px，字 / 按钮互相压住<br><sub>uipixel/ov0/projects_1440_dark_mark.png #6</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 21 | ●●● | 文字/按钮重叠 | projects, script_new（1440d） | `p.v3-two > span.v3-dl`<br>「独白：他看我了。就一眼，我心跳全乱。」 | apps/web/src/v3/ReviewRow.tsx:392<br>apps/web/src/v3/v3.css:316 | 195x8 | 和「static shot 固定机位」（p.v3-script）重叠 195×8px，字 / 按钮互相压住<br><sub>uipixel/ov0/projects_1440_dark_mark.png #7</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 22 | ●●● | 文字/按钮重叠 | script_read（1440d 1920d） | `div.v3-field > p.v3-two`<br>「—」 | apps/web/src/v3/ReviewRow.tsx:388<br>apps/web/src/v3/v3.css:311 | 14x8 | 和「镜头缓推，从两人并排的正面中景起」（p.v3-script）重叠 14×8px，字 / 按钮互相压住<br><sub>uipixel/ov0/script_read_1440_dark_mark.png #3</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 23 | ●●● | 文字/按钮重叠 | edit_ep01, edit（1920d） | `label.v3e-fld > span` | apps/web/src/v3/edit/AssetDrawer.tsx:689<br>apps/web/src/v3/edit/edit.css:126 | 58x5 | 和「div」（div.sb-txt）重叠 58×5px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_ep01_1920_dark.png #3</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 24 | ●●● | 文字/按钮重叠 | edit_ep01, edit（1920d） | `span > small` | apps/web/src/v3/edit/AssetDrawer.tsx:689<br>apps/web/src/v3/edit/edit.css:126 | 223x5 | 和「div」（div.sb-txt）重叠 223×5px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_ep01_1920_dark.png #6</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |
| 25 | ●●● | 文字/按钮重叠 | edit_ep01, edit（1920d） | `span.k > small` | apps/web/src/components/Dialogs.tsx:219<br>apps/web/src/v3/edit/edit.css:174 | 132x15 | 和「textarea」（textarea.grow.sm）重叠 132×15px，字 / 按钮互相压住<br><sub>uipixel/ov0/edit_ep01_1920_dark.png #10</sub> | 同一角落的多个标签放进同一条 flex 底栏（ds-tilebar：gap、状态省略号 + title、窄了操作收进 ⋯），不再各自 absolute |