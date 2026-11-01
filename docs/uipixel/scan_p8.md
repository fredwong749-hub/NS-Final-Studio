# UIPIXEL 扫描 p8

生成：2026-10-31T19:54:34.502Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 10 个 × 尺寸 1440×900 × 主题 dark = 截图 10 张（目录 apps/web/e2e/uipixel/p8/，主尺寸另有 _mark 标注图）
- **去重后问题 1 条**：严重 0 · 一般 0 · 轻微 1
- 分类：可点区域过小 1

## 每页问题数

| 状态 | 1440 深 |
|---|---|
| projects 项目首页 | 0 |
| review 画布·审片 | 0 |
| edit 画布·精修（提示词） | 0 |
| edit_params 精修·参数 | 0 |
| edit_assets 精修·资产 | 0 |
| edit_rules 精修·规则 | 0 |
| assets 资产中心 | 0 |
| a_scene 资产·场景 | 2 |
| audit 操作记录 | 0 |
| models 设置 / 模型 | 0 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ● | 可点区域过小 | a_scene（1440d） | `span.ac-foot > button.ac-use`<br>「用在 2 集 · 10 镜 ›」 | apps/web/src/v3/assets/AssetCard.tsx:76<br>apps/web/src/v3/assets/center.css:81 | 105x24 | 可点区域 105×24px（<28）<br><sub>uipixel/p8/a_scene_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |