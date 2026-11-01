# UIPIXEL 扫描 bB1

生成：2026-10-31T18:03:16.048Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 4 个 × 尺寸 1280×720 / 1440×900 × 主题 dark = 截图 8 张（目录 apps/web/e2e/uipixel/bB1/，主尺寸另有 _mark 标注图）
- **去重后问题 7 条**：严重 0 · 一般 7 · 轻微 0
- 分类：左对齐 4 · 标签/控件垂直居中 3

## 每页问题数

| 状态 | 1280 深 | 1440 深 |
|---|---|---|
| edit_ep01 画布·精修（第 1 集） | 4 | 4 |
| edit 画布·精修（提示词） | 3 | 3 |
| edit_params 精修·参数 | 4 | 4 |
| edit_versions 精修·版本 | 4 | 2 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●● | 标签/控件垂直居中 | edit_ep01, edit, edit_params, edit_versions（1280d 1440d） | `button.v3-step > i`<br>「3」 | apps/web/src/v3/TopBarV3.tsx:342<br>apps/web/src/v3/v3.css:75 | 8.9px | 胶囊 / 标签和同行文字中线差 8.9px<br><sub>uipixel/bB1/edit_ep01_1280_dark.png #3</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |
| 2 | ●● | 标签/控件垂直居中 | edit_ep01, edit, edit_params, edit_versions（1280d 1440d） | `button.v3-step.cur > i`<br>「1」 | apps/web/src/v3/TopBarV3.tsx:342<br>apps/web/src/v3/v3.css:75 | 8.9px | 胶囊 / 标签和同行文字中线差 8.9px<br><sub>uipixel/bB1/edit_ep01_1280_dark.png #2</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |
| 3 | ●● | 左对齐 | edit_ep01, edit（1280d 1440d） | `div.v3e-scroll > details.v3e-fold`<br>「本镜分镜（剧本原文，只读）」 | apps/web/src/v3/edit/EditLoop.tsx:352<br>apps/web/src/ds/ds.css:290 | 2px | 和同组兄弟左边缘差 2px（同组应左对齐）<br><sub>uipixel/bB1/edit_ep01_1280_dark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 4 | ●● | 左对齐 | edit_params, edit_versions（1280d 1440d） | `div.v3e-fld > select.v3e-sel`<br>「生成（由首帧编辑出尾帧） 用下一镜首帧（衔接） 」 | apps/web/src/v3/edit/RightTabs.tsx:643<br>apps/web/src/v3/edit/edit.css:508 | 4px | 和同组兄弟左边缘差 4px（同组应左对齐）<br><sub>uipixel/bB1/edit_params_1280_dark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 5 | ●● | 左对齐 | edit_params, edit_versions（1280d 1440d） | `div.v3e-fld > span.v3e-lane`<br>「自动（gpu33·卡1） gpu33·卡1 · 」 | apps/web/src/v3/edit/LaneSelect.tsx:37<br>apps/web/src/ds/ds.css:367 | 2px | 和同组兄弟左边缘差 2px（同组应左对齐）<br><sub>uipixel/bB1/edit_params_1280_dark.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 6 | ●● | 标签/控件垂直居中 | edit_ep01（1280d 1440d） | `button.v3e-cand.bad > span.badmk`<br>「坏图」 | apps/web/src/v3/edit/EditCenter.tsx:565<br>apps/web/src/ds/ds.css:282 | -15.3px | 胶囊 / 标签和同行文字中线差 -15.3px<br><sub>uipixel/bB1/edit_ep01_1280_dark.png #4</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |
| 7 | ●● | 左对齐 | edit_versions（1440d） | `div.app.v3-app > div.pad.bad`<br>「分镜画布出错：Rendered more hoo」 | apps/web/src/components/Dialogs.tsx:166<br>apps/web/src/canvas-v3.css:246 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/bB1/edit_versions_1440_dark_mark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |