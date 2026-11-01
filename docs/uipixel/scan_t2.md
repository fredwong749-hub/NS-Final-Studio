# UIPIXEL 扫描 t2

生成：2026-10-31T16:25:42.839Z · 脚本 apps/web/e2e/uipixel/scan.mjs（检测逻辑 check.js）

- 状态 1 个 × 尺寸 1440×900 × 主题 dark = 截图 1 张（目录 apps/web/e2e/uipixel/t2/，主尺寸另有 _mark 标注图）
- **去重后问题 21 条**：严重 5 · 一般 13 · 轻微 3
- 分类：可点区域过小 6 · 同行卡片等高顶齐 4 · 左对齐 4 · 缺悬停态 3 · 间距不在刻度 2 · 标签/控件垂直居中 1 · 无手型指针 1

## 每页问题数

| 状态 | 1440 深 |
|---|---|
| overview 全剧总览 | 27 |

## 问题清单（按严重度）

| # | 级 | 类别 | 页面（尺寸/主题） | 组件 | 源码 | 量化值 | 说明 | 修法 |
|---|---|---|---|---|---|---|---|---|
| 1 | ●●● | 可点区域过小 | overview（1440d） | `div.v3-top-l > a.v3-brand`<br>「momoso Agentic Drama Stu」 | apps/web/src/v3/TopBarV3.tsx:311<br>apps/web/src/v3/ux4.css:6 | 22x22 | 可点区域只有 22×22px（<24 难点中）<br><sub>uipixel/t2/overview_1440_dark_mark.png #18</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 2 | ●●● | 可点区域过小 | overview（1440d） | `div.sea-eph > a.sea-epn`<br>「第 1 集」 | apps/web/src/v3/pages/SeasonPage.tsx:149<br>apps/web/src/v3/pages/season.css:13 | 42x16 | 可点区域只有 42×16px（<24 难点中）<br><sub>uipixel/t2/overview_1440_dark_mark.png #21</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 3 | ●●● | 可点区域过小 | overview（1440d） | `div.sea-eph > button.v3p-link.sea-selall`<br>「选中整集」 | apps/web/src/v3/edit/RightTabs.tsx:61<br>apps/web/src/v3/pages/pages.css:32 | 52x16 | 可点区域只有 52×16px（<24 难点中）<br><sub>uipixel/t2/overview_1440_dark_mark.png #22</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 4 | ●●● | 可点区域过小 | overview（1440d） | `div.sea-eph > a.sea-epn`<br>「第 2 集」 | apps/web/src/v3/pages/SeasonPage.tsx:149<br>apps/web/src/v3/pages/season.css:13 | 42x16 | 可点区域只有 42×16px（<24 难点中）<br><sub>uipixel/t2/overview_1440_dark_mark.png #23</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 5 | ●●● | 可点区域过小 | overview（1440d） | `div.sea-eph > button.v3p-link.sea-selall`<br>「选中整集」 | apps/web/src/v3/edit/RightTabs.tsx:61<br>apps/web/src/v3/pages/pages.css:32 | 52x16 | 可点区域只有 52×16px（<24 难点中）<br><sub>uipixel/t2/overview_1440_dark_mark.png #24</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |
| 6 | ●● | 同行卡片等高顶齐 | overview（1440d） | `li.sea-cell > button.sea-card`<br>「未出 S2 本地 特写 · 8s ● ● · ·」 | apps/web/src/v3/pages/SeasonPage.tsx:180<br>apps/web/src/v3/pages/season.css:28 | top0.9/h-2.1 | 同一行卡片顶边差 0.9px、高度差 -2.1px（同一行要等高、顶对齐）<br><sub>uipixel/t2/overview_1440_dark_mark.png #7</sub> | 行容器 align-items:stretch，卡片内可变内容（标签）预留固定行或改为浮层；连接符固定高度对齐到图片中线 |
| 7 | ●● | 同行卡片等高顶齐 | overview（1440d） | `button.sea-card > span.sea-pic.none`<br>「未出 S2 本地」 | apps/web/src/v3/pages/SeasonPage.tsx:182<br>apps/web/src/v3/pages/season.css:33 | top0.9/h-0.1 | 同一行卡片顶边差 0.9px（同一行要等高、顶对齐）<br><sub>uipixel/t2/overview_1440_dark_mark.png #11</sub> | 行容器 align-items:stretch，卡片内可变内容（标签）预留固定行或改为浮层；连接符固定高度对齐到图片中线 |
| 8 | ●● | 左对齐 | overview（1440d） | `button.sea-card > span.sea-segs`<br>「首帧 · 尾帧 · 视频 · 通过」 | apps/web/src/v3/pages/SeasonPage.tsx:190<br>apps/web/src/v3/pages/season.css:42 | 4px | 和同组兄弟左边缘差 4px（同组应左对齐）<br><sub>uipixel/t2/overview_1440_dark_mark.png #1</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 9 | ●● | 左对齐 | overview（1440d） | `button.sea-card > span.sea-meta`<br>「特写 · 4s」 | apps/web/src/v3/pages/SeasonPage.tsx:195<br>apps/web/src/v3/pages/season.css:50 | 4px | 和同组兄弟左边缘差 4px（同组应左对齐）<br><sub>uipixel/t2/overview_1440_dark_mark.png #2</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 10 | ●● | 左对齐 | overview（1440d） | `button.sea-card > span.sea-band`<br>「林晚与陈宇的家」 | apps/web/src/v3/pages/SeasonPage.tsx:181<br>apps/web/src/v3/pages/season.css:32 | -4px | 和同组兄弟左边缘差 -4px（同组应左对齐）<br><sub>uipixel/t2/overview_1440_dark_mark.png #3</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 11 | ●● | 左对齐 | overview（1440d） | `button.sea-card > span.sea-pic.none`<br>「未出 S6 本地」 | apps/web/src/v3/pages/SeasonPage.tsx:182<br>apps/web/src/v3/pages/season.css:33 | -4px | 和同组兄弟左边缘差 -4px（同组应左对齐）<br><sub>uipixel/t2/overview_1440_dark_mark.png #4</sub> | 同组表单项共用一条左对齐线：去掉单独的 margin-left / padding-left，提示文字放进控件列 |
| 12 | ●● | 同行卡片等高顶齐 | overview（1440d） | `li.sea-cell > span.sea-link.cut`<br>「┃」 | apps/web/src/v3/pages/SeasonPage.tsx:176<br>apps/web/src/v3/pages/season.css:24 | 8.7px | 卡片之间的连接符「┃」高度和其他连接符差 8.7px<br><sub>uipixel/t2/overview_1440_dark_mark.png #15</sub> | 行容器 align-items:stretch，卡片内可变内容（标签）预留固定行或改为浮层；连接符固定高度对齐到图片中线 |
| 13 | ●● | 同行卡片等高顶齐 | overview（1440d） | `li.sea-cell > span.sea-link`<br>「➜」 | apps/web/src/v3/pages/SeasonPage.tsx:176<br>apps/web/src/v3/pages/season.css:24 | 8.7px | 卡片之间的连接符「➜」高度和其他连接符差 8.7px<br><sub>uipixel/t2/overview_1440_dark_mark.png #16</sub> | 行容器 align-items:stretch，卡片内可变内容（标签）预留固定行或改为浮层；连接符固定高度对齐到图片中线 |
| 14 | ●● | 标签/控件垂直居中 | overview（1440d） | `button.v3-step.cur > i`<br>「1」 | apps/web/src/v3/TopBarV3.tsx:340<br>apps/web/src/v3/v3.css:75 | 8.9px | 胶囊 / 标签和同行文字中线差 8.9px<br><sub>uipixel/t2/overview_1440_dark_mark.png #17</sub> | 行容器 align-items:center；标签 line-height 与控件高度一致（ds-field） |
| 15 | ●● | 无手型指针 | overview（1440d） | `label.sea-tog > input` | apps/web/src/v3/pages/SeasonPage.tsx:118<br>apps/web/src/v3/pages/season.css:4 | default | 可点元素鼠标不是手型（cursor:default）<br><sub>uipixel/t2/overview_1440_dark_mark.png #20</sub> | cursor:pointer（全局 ds.css 规则） |
| 16 | ●● | 缺悬停态 | overview（1440d） | `div.v3-top-l > a.v3-brand`<br>「momoso Agentic Drama Stu」 | apps/web/src/v3/TopBarV3.tsx:311<br>apps/web/src/v3/ux4.css:6 | hover+active | 缺少 悬停态、按下（点击反馈）<br><sub>uipixel/t2/overview_1440_dark_mark.png #25</sub> | 加 :hover 背景（--c-hover） |
| 17 | ●● | 缺悬停态 | overview（1440d） | `div.v3-popwrap.v3-ep-pick > button.v3-ep-name`<br>「第 1 集 · 入职日的一瞥 ▾」 | apps/web/src/v3/v3.css:72 | hover+active | 缺少 悬停态、按下（点击反馈）<br><sub>uipixel/t2/overview_1440_dark_mark.png #26</sub> | 加 :hover 背景（--c-hover） |
| 18 | ●● | 缺悬停态 | overview（1440d） | `li.sea-cell.sel > button.sea-card`<br>「S1 特写 · 4s ● · · ·」 | apps/web/src/v3/pages/SeasonPage.tsx:180<br>apps/web/src/v3/pages/season.css:28 | hover+active | 缺少 悬停态、按下（点击反馈）<br><sub>uipixel/t2/overview_1440_dark_mark.png #27</sub> | 加 :hover 背景（--c-hover） |
| 19 | ● | 间距不在刻度 | overview（1440d） | `li.sea-cell > button.sea-card`<br>「S1 特写 · 4s ● · · ·」 | apps/web/src/v3/pages/SeasonPage.tsx:180<br>apps/web/src/v3/pages/season.css:28 | rowGap:3 | rowGap 3px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/t2/overview_1440_dark_mark.png #5</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 20 | ● | 间距不在刻度 | overview（1440d） | `li.sea-cell > button.sea-card`<br>「S1 特写 · 4s ● · · ·」 | apps/web/src/v3/pages/SeasonPage.tsx:180<br>apps/web/src/v3/pages/season.css:28 | columnGap:3 | columnGap 3px 不在间距刻度（4/8/12/16/24/32…）<br><sub>uipixel/t2/overview_1440_dark_mark.png #6</sub> | 改成 --sp-* token（4/8/12/16/24/32） |
| 21 | ● | 可点区域过小 | overview（1440d） | `div.v3-popwrap.v3-ep-pick > button.v3-ep-name`<br>「第 1 集 · 入职日的一瞥 ▾」 | apps/web/src/v3/v3.css:72 | 168x26 | 可点区域 168×26px（<28）<br><sub>uipixel/t2/overview_1440_dark_mark.png #19</sub> | 最小 28px 高（主要按钮 32px），或用 ::after 扩点击区 |