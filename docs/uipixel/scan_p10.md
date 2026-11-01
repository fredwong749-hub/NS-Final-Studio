# UIPIXEL 扫描 p10

生成：2026-10-31T20:35:45.500Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 31 个 × 尺寸 1440×900 × 主题 dark = 截图 31 张（目录 apps/web/e2e/uipixel/p10/，主尺寸另有 _mark 标注图）
- **去重后问题 3 条**：严重 0 · 一般 3 · 轻微 0
- 分类：吸顶条遮挡 3

## 每页问题数

| 状态 | 1440 深 |
|---|---|
| projects 项目首页 | 1 |
| script_new 新建剧本 | 1 |
| script_read 剧本阅读模式 | 1 |
| overview 全剧总览 | 0 |
| review 画布·审片 | 0 |
| review_ep01 画布·审片（第 1 集，有图） | 0 |
| review_ep01_scroll 画布·审片（第 1 集，往下滚） | 0 |
| edit_ep01 画布·精修（第 1 集） | 0 |
| edit 画布·精修（提示词） | 0 |
| edit_params 精修·参数 | 0 |
| edit_versions 精修·版本 | 0 |
| edit_assets 精修·资产 | 0 |
| edit_sound 精修·声音 | 0 |
| edit_rules 精修·规则 | 0 |
| assets 资产中心 | 0 |
| a_character 资产·人物 | 2 |
| a_linwan 资产·人物页（林晚） | 0 |
| a_look 资产·形象 | 2 |
| a_item 资产·单品 | 0 |
| a_scene 资产·场景 | 1 |
| a_scene_open 资产·场景弹框 | 0 |
| a_voice 资产·音色 | 1 |
| a_sheets 资产·设定图 | 0 |
| a_preset 资产·预设 | 1 |
| a_loras 资产·LoRA | 0 |
| a_template 资产·模板 | 1 |
| sound 声音页 | 0 |
| cut 成片页 | 0 |
| trash 回收站 | 0 |
| audit 操作记录 | 0 |
| models 设置 / 模型 | 0 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●● | 吸顶条遮挡 | a_character, a_look, a_scene, a_voice …（1440d） | `div.ac-page > nav.ac-nav`<br>「② 资产中心 人物 · 当前剧 林晚 3/3 套」 | apps/web/src/v3/assets/AssetCenter.tsx:157<br>apps/web/src/v3/assets/center.css:7 | 8<848 | 吸顶条高 848px，但滚动区 scroll-padding-top 只有 8px：Tab 聚焦 / 跳转会把控件藏到条下面（G4）<br><sub>uipixel/p10/a_character_1440_dark_mark.png #1</sub> | 滚动区 scroll-padding-top = 吸顶条高度；吸顶条不透明底 + z-index |
| 2 | ●● | 吸顶条遮挡 | projects, script_new, script_read（1440d） | `div.sf-page > nav.sf-steps`<br>「剧本 ① 新建剧本 故事提纲 → 自动写故事线 」 | apps/web/src/v3/pages/ScriptFlowPage.tsx:31<br>apps/web/src/ds/ds.css:485 | 56<60 | 吸顶条高 60px，但滚动区 scroll-padding-top 只有 56px：Tab 聚焦 / 跳转会把控件藏到条下面（G4）<br><sub>uipixel/p10/projects_1440_dark_mark.png #1</sub> | 滚动区 scroll-padding-top = 吸顶条高度；吸顶条不透明底 + z-index |
| 3 | ●● | 吸顶条遮挡 | a_character, a_look（1440d） | `div.hub > nav.hub-anchors`<br>「身份脸 造型 A 造型 B 造型 C 排期 衣橱」 | apps/web/src/v3/assets/PeopleHub.tsx:293<br>apps/web/src/v3/assets/people_hub.css:34 | 0<59 | 吸顶条高 59px，但滚动区 scroll-padding-top 只有 0px：Tab 聚焦 / 跳转会把控件藏到条下面（G4）<br><sub>uipixel/p10/a_character_1440_dark_mark.png #2</sub> | 滚动区 scroll-padding-top = 吸顶条高度；吸顶条不透明底 + z-index |