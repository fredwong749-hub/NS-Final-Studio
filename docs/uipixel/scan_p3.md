# UIPIXEL 扫描 p3

生成：2026-10-31T18:56:24.544Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 4 个 × 尺寸 1440×900 × 主题 dark = 截图 4 张（目录 apps/web/e2e/uipixel/p3/，主尺寸另有 _mark 标注图）
- **去重后问题 3 条**：严重 0 · 一般 2 · 轻微 1
- 分类：左对齐 2 · 同类内边距 1

## 每页问题数

| 状态 | 1440 深 |
|---|---|
| projects 项目首页 | 0 |
| script_read 剧本阅读模式 | 0 |
| edit_params 精修·参数 | 1 |
| a_look 资产·形象 | 2 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●● | 左对齐 | a_look（1440d） | `nav.ac-nav > div.ac-nav-h`<br>「② 资产中心」 | apps/web/src/v3/assets/AssetCenter.tsx:158<br>apps/web/src/v3/assets/center.css:8 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p3/a_look_1440_dark_mark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 2 | ●● | 左对齐 | a_look（1440d） | `nav.ac-nav > div.ac-nav-g`<br>「人物 · 当前剧」 | apps/web/src/v3/assets/AssetCenter.tsx:162<br>apps/web/src/v3/assets/center.css:10 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p3/a_look_1440_dark_mark.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 3 | ● | 同类内边距 | edit_params（1440d） | `div.v3e-fld > div.v3e-ro`<br>「—」 | apps/web/src/v3/edit/EditCenter.tsx:765<br>apps/web/src/v3/edit/edit.css:212 | 8/8/8/8 | 同类卡片 .v3e-ro 内边距有 2 种（4/8/4/8 · 8/8/8/8）<br><sub>uipixel/p3/edit_params_1440_dark_mark.png #1</sub> | 同组卡片统一 padding（卡 16 / 紧凑卡 12） |