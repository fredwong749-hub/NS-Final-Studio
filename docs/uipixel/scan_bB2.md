# UIPIXEL 扫描 bB2

生成：2026-10-31T18:06:25.329Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 4 个 × 尺寸 1280×720 / 1440×900 × 主题 dark = 截图 8 张（目录 apps/web/e2e/uipixel/bB2/，主尺寸另有 _mark 标注图）
- **去重后问题 4 条**：严重 0 · 一般 4 · 轻微 0
- 分类：标签/控件垂直居中 2 · 左对齐 2

## 每页问题数

| 状态 | 1280 深 | 1440 深 |
|---|---|---|
| edit_ep01 画布·精修（第 1 集） | 3 | 3 |
| edit 画布·精修（提示词） | 3 | 3 |
| edit_params 精修·参数 | 2 | 2 |
| edit_versions 精修·版本 | 1 | 3 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●● | 标签/控件垂直居中 | edit_ep01, edit, edit_params, edit_versions（1280d 1440d） | `button.v3-step > i`<br>「3」 | apps/web/src/v3/TopBarV3.tsx:342<br>apps/web/src/v3/v3.css:75 | 8.9px | 胶囊 / 标签和同行文字中线差 8.9px<br><sub>uipixel/bB2/edit_ep01_1280_dark.png #3</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |
| 2 | ●● | 标签/控件垂直居中 | edit_ep01, edit, edit_params, edit_versions（1280d 1440d） | `button.v3-step.cur > i`<br>「1」 | apps/web/src/v3/TopBarV3.tsx:342<br>apps/web/src/v3/v3.css:75 | 8.9px | 胶囊 / 标签和同行文字中线差 8.9px<br><sub>uipixel/bB2/edit_ep01_1280_dark.png #2</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |
| 3 | ●● | 左对齐 | edit_ep01, edit（1280d 1440d） | `div.v3e-scroll > details.v3e-fold`<br>「本镜分镜（剧本原文，只读）」 | apps/web/src/v3/edit/EditLoop.tsx:352<br>apps/web/src/ds/ds.css:290 | 2px | 和同组兄弟左边缘差 2px（同组应左对齐）<br><sub>uipixel/bB2/edit_ep01_1280_dark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 4 | ●● | 左对齐 | edit_versions（1440d） | `div.v3e-chain > button.node`<br>「#1 生成 过期·需重出」 | apps/web/src/v3/assets/AssetCenter.tsx:171<br>apps/web/src/v3/edit/edit.css:230 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/bB2/edit_versions_1440_dark_mark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |