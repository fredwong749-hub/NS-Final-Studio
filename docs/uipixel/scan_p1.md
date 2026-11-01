# UIPIXEL 扫描 p1

生成：2026-10-31T18:53:07.246Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 2 个 × 尺寸 1440×900 × 主题 dark = 截图 2 张（目录 apps/web/e2e/uipixel/p1/，主尺寸另有 _mark 标注图）
- **去重后问题 6 条**：严重 1 · 一般 1 · 轻微 4
- 分类：可点区域过小 5 · 左对齐 1

## 每页问题数

| 状态 | 1440 深 |
|---|---|
| sound 声音页 | 8 |
| audit 操作记录 | 2 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●●● | 可点区域过小 | sound（1440d） | `div.vs-cands > button.vs-cand`<br>「候选 1」 | apps/web/src/v3/assets/VoiceStudio.tsx:145<br>apps/web/src/v3/assets/center.css:223 | 53x22 | 可点区域只有 53×22px（<24 难点中）<br><sub>uipixel/p1/sound_1440_dark_mark.png #4</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 2 | ●● | 左对齐 | audit（1440d） | `div.v3p-page > table.audit-tbl`<br>「时间 谁 做了什么 对象 结果 11-01 02」 | apps/web/src/v3/AuditDrawer.tsx:43<br>apps/web/src/v3/v3.css:541 | 8px | 和同组兄弟左边缘差 8px（同组应左对齐）<br><sub>uipixel/p1/audit_1440_dark_mark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 3 | ● | 可点区域过小 | sound（1440d） | `nav.v3p-tabs > button`<br>「角色音色 · 旁白」 | apps/web/src/components/Dialogs.tsx:219<br>apps/web/src/canvas-v2.css:8 | 100x25 | 可点区域 100×25px（<28）<br><sub>uipixel/p1/sound_1440_dark_mark.png #1</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 4 | ● | 可点区域过小 | sound（1440d） | `span.vs-sample > button.vs-cand`<br>「▶ 深夜电台 · 明亮」 | apps/web/src/v3/assets/VoiceStudio.tsx:145<br>apps/web/src/v3/assets/center.css:223 | 122x25 | 可点区域 122×25px（<28）<br><sub>uipixel/p1/sound_1440_dark_mark.png #6</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 5 | ● | 可点区域过小 | sound（1440d） | `span.vs-sample.cur > button.vs-cand`<br>「▶ 深夜电台 · 温柔现在在用」 | apps/web/src/v3/assets/VoiceStudio.tsx:145<br>apps/web/src/v3/assets/center.css:223 | 174x25 | 可点区域 174×25px（<28）<br><sub>uipixel/p1/sound_1440_dark_mark.png #7</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 6 | ● | 可点区域过小 | audit（1440d） | `details.audit-raw > summary`<br>「技术详情」 | apps/web/src/v3/AuditDrawer.tsx:65<br>apps/web/src/ds/ds.css:406 | 61x24 | 可点区域 61×24px（<28）<br><sub>uipixel/p1/audit_1440_dark_mark.png #2</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |