# UIPIXEL 扫描 bC0

生成：2026-10-31T18:08:21.882Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 1 个 × 尺寸 1280×720 / 1440×900 / 1920×1080 × 主题 dark = 截图 3 张（目录 apps/web/e2e/uipixel/bC0/，主尺寸另有 _mark 标注图）
- **去重后问题 11 条**：严重 0 · 一般 11 · 轻微 0
- 分类：同行卡片等高顶齐 5 · 左对齐 4 · 标签/控件垂直居中 2

## 每页问题数

| 状态 | 1280 深 | 1440 深 | 1920 深 |
|---|---|---|---|
| overview 全剧总览 | 10 | 15 | 16 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●● | 同行卡片等高顶齐 | overview（1280d 1440d 1920d） | `li.sea-cell > button.sea-card`<br>「S2 本地 特写 · 8s ● ● · ·」 | apps/web/src/v3/pages/SeasonPage.tsx:186<br>apps/web/src/ds/ds.css:307 | top0.9/h-2.1 | 同一行卡片顶边差 0.9px、高度差 -2.1px（同一行要等高、顶对齐）<br><sub>uipixel/bC0/overview_1280_dark.png #5</sub> | 行容器 align-items:stretch，卡片内可变内容（标签）预留固定行或改为浮层；连接符固定高度对齐到图片中线 |
| 2 | ●● | 同行卡片等高顶齐 | overview（1280d 1440d 1920d） | `button.sea-card > span.sea-pic.none`<br>「未出 S6 本地」 | apps/web/src/v3/pages/SeasonPage.tsx:188<br>apps/web/src/v3/pages/season.css:33 | top-8.1/h-0.1 | 同一行卡片顶边差 -8.1px（同一行要等高、顶对齐）<br><sub>uipixel/bC0/overview_1280_dark.png #8</sub> | 行容器 align-items:stretch，卡片内可变内容（标签）预留固定行或改为浮层；连接符固定高度对齐到图片中线 |
| 3 | ●● | 左对齐 | overview（1280d 1440d 1920d） | `button.sea-card > span.sea-segs`<br>「首帧 · 尾帧 · 视频 · 通过」 | apps/web/src/v3/pages/SeasonPage.tsx:196<br>apps/web/src/v3/pages/season.css:42 | 4px | 和同组兄弟左边缘差 4px（同组应左对齐）<br><sub>uipixel/bC0/overview_1280_dark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 4 | ●● | 左对齐 | overview（1280d 1440d 1920d） | `button.sea-card > span.sea-meta`<br>「特写 · 4s」 | apps/web/src/v3/pages/SeasonPage.tsx:201<br>apps/web/src/v3/pages/season.css:50 | 4px | 和同组兄弟左边缘差 4px（同组应左对齐）<br><sub>uipixel/bC0/overview_1280_dark.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 5 | ●● | 左对齐 | overview（1280d 1440d 1920d） | `button.sea-card > span.sea-band`<br>「林晚与陈宇的家」 | apps/web/src/v3/pages/SeasonPage.tsx:187<br>apps/web/src/v3/pages/season.css:32 | -4px | 和同组兄弟左边缘差 -4px（同组应左对齐）<br><sub>uipixel/bC0/overview_1280_dark.png #3</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 6 | ●● | 左对齐 | overview（1280d 1440d 1920d） | `button.sea-card > span.sea-pic.none`<br>「未出 S6 本地」 | apps/web/src/v3/pages/SeasonPage.tsx:188<br>apps/web/src/v3/pages/season.css:33 | -4px | 和同组兄弟左边缘差 -4px（同组应左对齐）<br><sub>uipixel/bC0/overview_1280_dark.png #4</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 7 | ●● | 同行卡片等高顶齐 | overview（1280d 1440d 1920d） | `button.sea-card > span.sea-pic`<br>「S2 本地」 | apps/web/src/v3/pages/SeasonPage.tsx:188<br>apps/web/src/v3/pages/season.css:33 | top0.9/h-0.1 | 同一行卡片顶边差 0.9px（同一行要等高、顶对齐）<br><sub>uipixel/bC0/overview_1280_dark.png #7</sub> | 行容器 align-items:stretch，卡片内可变内容（标签）预留固定行或改为浮层；连接符固定高度对齐到图片中线 |
| 8 | ●● | 同行卡片等高顶齐 | overview（1280d 1440d 1920d） | `li.sea-cell > span.sea-link.cut`<br>「┃」 | apps/web/src/v3/pages/SeasonPage.tsx:182<br>apps/web/src/v3/pages/season.css:24 | 8.7px | 卡片之间的连接符「┃」高度和其他连接符差 8.7px<br><sub>uipixel/bC0/overview_1280_dark.png #9</sub> | 行容器 align-items:stretch，卡片内可变内容（标签）预留固定行或改为浮层；连接符固定高度对齐到图片中线 |
| 9 | ●● | 同行卡片等高顶齐 | overview（1280d 1440d 1920d） | `li.sea-cell > span.sea-link`<br>「➜」 | apps/web/src/v3/pages/SeasonPage.tsx:182<br>apps/web/src/v3/pages/season.css:24 | 8.7px | 卡片之间的连接符「➜」高度和其他连接符差 8.7px<br><sub>uipixel/bC0/overview_1280_dark.png #10</sub> | 行容器 align-items:stretch，卡片内可变内容（标签）预留固定行或改为浮层；连接符固定高度对齐到图片中线 |
| 10 | ●● | 标签/控件垂直居中 | overview（1440d 1920d） | `button.v3-step.cur > i`<br>「1」 | apps/web/src/v3/TopBarV3.tsx:342<br>apps/web/src/v3/v3.css:75 | 8.9px | 胶囊 / 标签和同行文字中线差 8.9px<br><sub>uipixel/bC0/overview_1440_dark_mark.png #15</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |
| 11 | ●● | 标签/控件垂直居中 | overview（1920d） | `button.v3-step > i`<br>「2」 | apps/web/src/v3/TopBarV3.tsx:342<br>apps/web/src/v3/v3.css:75 | 8.9px | 胶囊 / 标签和同行文字中线差 8.9px<br><sub>uipixel/bC0/overview_1920_dark.png #16</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |