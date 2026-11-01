# UIPIXEL 扫描 p7

生成：2026-10-31T19:52:49.546Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 5 个 × 尺寸 1440×900 × 主题 dark = 截图 5 张（目录 apps/web/e2e/uipixel/p7/，主尺寸另有 _mark 标注图）
- **去重后问题 2 条**：严重 0 · 一般 2 · 轻微 0
- 分类：左对齐 2

## 每页问题数

| 状态 | 1440 深 |
|---|---|
| overview 全剧总览 | 0 |
| edit 画布·精修（提示词） | 0 |
| edit_versions 精修·版本 | 0 |
| edit_assets 精修·资产 | 0 |
| a_scene 资产·场景 | 2 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●● | 左对齐 | a_scene（1440d） | `nav.ac-nav > div.ac-nav-h`<br>「② 资产中心」 | apps/web/src/v3/assets/AssetCenter.tsx:158<br>apps/web/src/v3/assets/center.css:8 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p7/a_scene_1440_dark_mark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 2 | ●● | 左对齐 | a_scene（1440d） | `nav.ac-nav > div.ac-nav-g`<br>「人物 · 当前剧」 | apps/web/src/v3/assets/AssetCenter.tsx:162<br>apps/web/src/v3/assets/center.css:10 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p7/a_scene_1440_dark_mark.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |