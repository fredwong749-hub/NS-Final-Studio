# UIPIXEL 扫描 p5

生成：2026-10-31T19:47:59.958Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 1 个 × 尺寸 1440×900 × 主题 dark = 截图 1 张（目录 apps/web/e2e/uipixel/p5/，主尺寸另有 _mark 标注图）
- **去重后问题 1 条**：严重 0 · 一般 0 · 轻微 1
- 分类：可点区域过小 1

## 每页问题数

| 状态 | 1440 深 |
|---|---|
| audit 操作记录 | 1 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ● | 可点区域过小 | audit（1440d） | `details.audit-raw > summary`<br>「技术详情」 | apps/web/src/v3/AuditDrawer.tsx:65<br>apps/web/src/ds/ds.css:406 | 61x24 | 可点区域 61×24px（<28）<br><sub>uipixel/p5/audit_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |