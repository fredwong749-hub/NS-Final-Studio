# UIPIXEL 扫描 bC1

生成：2026-10-31T18:09:26.768Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 1 个 × 尺寸 1280×720 / 1440×900 / 1920×1080 × 主题 dark = 截图 3 张（目录 apps/web/e2e/uipixel/bC1/，主尺寸另有 _mark 标注图）
- **去重后问题 6 条**：严重 0 · 一般 6 · 轻微 0
- 分类：左对齐 4 · 标签/控件垂直居中 2

## 每页问题数

| 状态 | 1280 深 | 1440 深 | 1920 深 |
|---|---|---|---|
| overview 全剧总览 | 5 | 5 | 6 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●● | 左对齐 | overview（1280d 1440d 1920d） | `button.sea-card > span.sea-segs`<br>「首帧 · 尾帧 · 视频 · 通过」 | apps/web/src/v3/pages/SeasonPage.tsx:196<br>apps/web/src/v3/pages/season.css:42 | 4px | 和同组兄弟左边缘差 4px（同组应左对齐）<br><sub>uipixel/bC1/overview_1280_dark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 2 | ●● | 左对齐 | overview（1280d 1440d 1920d） | `button.sea-card > span.sea-meta`<br>「特写 · 4s」 | apps/web/src/v3/pages/SeasonPage.tsx:201<br>apps/web/src/ds/ds.css:384 | 4px | 和同组兄弟左边缘差 4px（同组应左对齐）<br><sub>uipixel/bC1/overview_1280_dark.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 3 | ●● | 左对齐 | overview（1280d 1440d 1920d） | `button.sea-card > span.sea-band`<br>「林晚与陈宇的家」 | apps/web/src/v3/pages/SeasonPage.tsx:187<br>apps/web/src/v3/pages/season.css:32 | -4px | 和同组兄弟左边缘差 -4px（同组应左对齐）<br><sub>uipixel/bC1/overview_1280_dark.png #3</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 4 | ●● | 左对齐 | overview（1280d 1440d 1920d） | `button.sea-card > span.sea-pic.none`<br>「未出 S6 本地」 | apps/web/src/v3/pages/SeasonPage.tsx:188<br>apps/web/src/v3/pages/season.css:33 | -4px | 和同组兄弟左边缘差 -4px（同组应左对齐）<br><sub>uipixel/bC1/overview_1280_dark.png #4</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 5 | ●● | 标签/控件垂直居中 | overview（1280d 1440d 1920d） | `button.v3-step.cur > i`<br>「1」 | apps/web/src/v3/TopBarV3.tsx:342<br>apps/web/src/v3/v3.css:75 | 8.9px | 胶囊 / 标签和同行文字中线差 8.9px<br><sub>uipixel/bC1/overview_1280_dark.png #5</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |
| 6 | ●● | 标签/控件垂直居中 | overview（1920d） | `button.v3-step > i`<br>「2」 | apps/web/src/v3/TopBarV3.tsx:342<br>apps/web/src/v3/v3.css:75 | 8.9px | 胶囊 / 标签和同行文字中线差 8.9px<br><sub>uipixel/bC1/overview_1920_dark.png #6</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |