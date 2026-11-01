# UIPIXEL 扫描 p2

生成：2026-10-31T18:54:38.116Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 6 个 × 尺寸 1440×900 × 主题 dark = 截图 6 张（目录 apps/web/e2e/uipixel/p2/，主尺寸另有 _mark 标注图）
- **去重后问题 10 条**：严重 0 · 一般 4 · 轻微 6
- 分类：可点区域过小 6 · 左对齐 4

## 每页问题数

| 状态 | 1440 深 |
|---|---|
| projects 项目首页 | 2 |
| review 画布·审片 | 1 |
| assets 资产中心 | 5 |
| sound 声音页 | 0 |
| audit 操作记录 | 1 |
| models 设置 / 模型 | 1 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●● | 左对齐 | assets（1440d） | `nav.ac-nav > div.ac-nav-h`<br>「② 资产中心」 | apps/web/src/v3/assets/AssetCenter.tsx:158<br>apps/web/src/v3/assets/center.css:8 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p2/assets_1440_dark_mark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 2 | ●● | 左对齐 | assets（1440d） | `nav.ac-nav > div.ac-nav-g`<br>「人物 · 当前剧」 | apps/web/src/v3/assets/AssetCenter.tsx:162<br>apps/web/src/v3/assets/center.css:10 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p2/assets_1440_dark_mark.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 3 | ●● | 左对齐 | assets（1440d） | `nav.ac-nav > div.ac-nav-foot`<br>「全部资产（卡片总览） 人物登记（新建 · 改名 」 | apps/web/src/v3/assets/AssetCenter.tsx:177<br>apps/web/src/v3/assets/center.css:18 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p2/assets_1440_dark_mark.png #3</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 4 | ●● | 左对齐 | assets（1440d） | `div.hub > div.hub-newlook`<br>「＋ 新造型 新建一套造型（林晚 现在有 A / 」 | apps/web/src/v3/assets/PeopleHub.tsx:397<br>apps/web/src/v3/assets/people_hub.css:241 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p2/assets_1440_dark_mark.png #4</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 5 | ● | 可点区域过小 | projects（1440d） | `details.ns-old > summary`<br>「以前的稿子（1）」 | apps/web/src/v3/pages/NewScriptPage.tsx:150<br>apps/web/src/v3/pages/story.css:163 | 247x24 | 可点区域 247×24px（<28）<br><sub>uipixel/p2/projects_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 6 | ● | 可点区域过小 | projects（1440d） | `details.ns-prod-log > summary.ds-small`<br>「自动修复记录（最近 1 条）」 | apps/web/src/ds/MediaPlayer.tsx:159<br>apps/web/src/ds/ds.css:122 | 1094x24 | 可点区域 1094×24px（<28）<br><sub>uipixel/p2/projects_1440_dark_mark.png #2</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 7 | ● | 可点区域过小 | review（1440d） | `div.v3-rows > button.v3-seam.none`<br>「未检查」 | apps/web/src/v3/Canvas.tsx:86<br>apps/web/src/ds/ds.css:291 | 350x24 | 可点区域 350×24px（<28）<br><sub>uipixel/p2/review_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 8 | ● | 可点区域过小 | assets（1440d） | `figure.hub-face > button.hub-face-del`<br>「删除」 | apps/web/src/v3/assets/PeopleHub.tsx:338<br>apps/web/src/v3/assets/people_hub.css:237 | 40x24 | 可点区域 40×24px（<28）<br><sub>uipixel/p2/assets_1440_dark_mark.png #5</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 9 | ● | 可点区域过小 | audit（1440d） | `details.audit-raw > summary`<br>「技术详情」 | apps/web/src/v3/AuditDrawer.tsx:65<br>apps/web/src/ds/ds.css:406 | 61x24 | 可点区域 61×24px（<28）<br><sub>uipixel/p2/audit_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 10 | ● | 可点区域过小 | models（1440d） | `div.v3p-card-head > button.btn-mini`<br>「刷新」 | apps/web/src/components/Dialogs.tsx:11<br>apps/web/src/canvas-v2.css:50 | 40x24 | 可点区域 40×24px（<28）<br><sub>uipixel/p2/models_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |