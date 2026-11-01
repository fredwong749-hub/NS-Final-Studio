# UIPIXEL 扫描 p14

生成：2026-11-01T01:09:06.663Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 3 个 × 尺寸 1920×1080 × 主题 light = 截图 3 张（目录 apps/web/e2e/uipixel/p14/，主尺寸另有 _mark 标注图）
- **去重后问题 2 条**：严重 0 · 一般 2 · 轻微 0
- 分类：左对齐 2

## 每页问题数

| 状态 | 1920 浅 |
|---|---|
| projects 项目首页 | 0 |
| script_read 剧本阅读模式 | 0 |
| a_character 资产·人物 | 2 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●● | 左对齐 | a_character（1920l） | `nav.ac-nav > div.ac-nav-h`<br>「② 资产中心」 | apps/web/src/v3/assets/AssetCenter.tsx:160<br>apps/web/src/v3/assets/center.css:8 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p14/a_character_1920_light.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 2 | ●● | 左对齐 | a_character（1920l） | `nav.ac-nav > div.ac-nav-g`<br>「人物 · 当前剧」 | apps/web/src/v3/assets/AssetCenter.tsx:164<br>apps/web/src/v3/assets/center.css:10 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p14/a_character_1920_light.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |