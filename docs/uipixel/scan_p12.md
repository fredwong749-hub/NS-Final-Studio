# UIPIXEL 扫描 p12

生成：2026-10-31T20:44:36.588Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 7 个 × 尺寸 1440×900 × 主题 dark = 截图 7 张（目录 apps/web/e2e/uipixel/p12/，主尺寸另有 _mark 标注图）
- **去重后问题 3 条**：严重 0 · 一般 0 · 轻微 3
- 分类：间距不在刻度 2 · 同类内边距 1

## 每页问题数

| 状态 | 1440 深 |
|---|---|
| projects 项目首页 | 1 |
| overview 全剧总览 | 0 |
| review 画布·审片 | 2 |
| edit_params 精修·参数 | 1 |
| assets 资产中心 | 0 |
| trash 回收站 | 0 |
| models 设置 / 模型 | 0 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ● | 间距不在刻度 | projects, review（1440d） | `div.v3-info > div.v3-people`<br>「林晚 A 景 深夜写字楼办公区角落 无底图 分镜」 | apps/web/src/v3/ReviewRow.tsx:449<br>apps/web/src/v3/pages/story.css:222 | paddingLeft:38 | paddingLeft 38px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/p12/projects_1440_dark_mark.png #1</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 2 | ● | 间距不在刻度 | review（1440d） | `div.v3-info > div.v3-people`<br>「林晚 A 顾沉 A 电梯与楼道 分镜详情 ▸ 首」 | apps/web/src/v3/ReviewRow.tsx:449<br>apps/web/src/v3/pages/story.css:222 | marginTop:7 | marginTop 7px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/p12/review_1440_dark_mark.png #2</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 3 | ● | 同类内边距 | edit_params（1440d） | `div.v3e-fld > div.v3e-ro`<br>「—」 | apps/web/src/v3/edit/EditCenter.tsx:765<br>apps/web/src/v3/edit/edit.css:212 | 8/8/8/8 | 同类卡片 .v3e-ro 内边距有 2 种（4/8/4/8 · 8/8/8/8）<br><sub>uipixel/p12/edit_params_1440_dark_mark.png #1</sub> | 同组卡片统一 padding（卡 16 / 紧凑卡 12） |