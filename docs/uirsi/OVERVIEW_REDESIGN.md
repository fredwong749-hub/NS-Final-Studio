# 全剧总览（#/overview）重设计方案

> ⤴ **已被项目方否决（11-02 02:1x 原话：“达文西那个设计稿不行，完全不合理。去掉这个逻辑吧，不用达文西。”）**。
> 总调度定：A / B 两版布局、三栏检视、全站中性灰 token、胶片带都不做；本文保留存档，不删。
> 仍然有效、已在 r43 落实的只有 §2.3 口径错误 K1–K7（顶栏忙闲 / 外部任务措辞 / 渲染任务计数 / 进度失败口径 / 隔离不算减少 / 五态主状态 / 计划内重做不算过期）——它们是独立的 bug 修复，与 DaVinci 版面无关。
> UIRSI r43 核对：DaVinci 相关代码（布局 / 检视 / 灰 token / 胶片带）一行都还没写，无需回退（grep apps/web/src 无版面改动；见 docs/uirsi/rounds/r43.md）。


UI-DESIGN，2026-11-02 01:4x，总调度 fredw-2b 派。本文只写方案，代码由 UIRSI 实施。

## 0 背景

### 项目方原话
- **11-02 01:2x**：“总览好吵哎，排版不好看，状态也有点混乱……数据的展示也清晰一点，图片也可以稍微大一点点。”
- **11-02 01:3x（优先级最高）**：“这个页面，我比较喜欢看到有很多你工作状态的图，包括特写、中镜、小图以及 reference 图，我是想看到更多细节的。这些我是想看的，但是一些乱七八糟的事情就不要展示了。”

- **11-02 01:4x（优先级最高，视觉方向）**：“有个很专业的调色软件叫 DaVinci（达文西），那些风格好像是嵌入进来的。我希望网页是往那个风格来做，更专业一点。”
  - 所以 A / B 两版都换成专业调色软件的界面语言：中性灰分层、界面本身几乎没有彩色、缩略图角上的小色标、小号字和等宽时码。
  - B 版贴近它的调色页布局：上排是静帧库、检视器、检查器，中间一条全剧时间条，下面是镜头缩略带。
  - A 版贴近它的媒体页布局：左边是集列表（相当于媒体夹），右边是镜头池。
  - 只借鉴布局和视觉语言，不用对方的商标、Logo 和图标原件（§1.5）。

### 一句话方向
- 总览以图为主。每镜能看到：主图、脸部局部、过程版本、参考图。
- 状态只留一个干净的记号。
- 符号、计数胶囊、给机器看的口径数字全部收起来。
- 生产健康收进页头角落，有异常才变色。

### 样稿
- 页面：`data/review_pages/ui_redesign/index.html`。自包含，用真实数据，右下角可切换 A / B / 浅色。
- 截图（都已看过）：
  - `shot_B_1440_dark.png`（B 默认：第 1 集，选中 S1）
  - `shot_B_1440_dark_ep03.png`（第 3 集，选中双人镜 S5；没图的镜显示出场人物）
  - `shot_B_1920_dark.png`
  - `shot_A_1440_dark.png`、`shot_A_1920_dark.png`
- 地址后面可以加 `#B@ep03-S5`，直接打开某一镜。
- 01:3x 那一版“卡片式”样稿的生成脚本保留在 scratchpad 的 `uiov/page_v1_cards.py`，已被本版取代。
- 改版前的截图：`apps/web/e2e/uirsi/r41b_overview_1440_dark.png`。
- 数据快照时间 11-02 01:29–01:32，全部来自只读 GET 和读文件：
  - `/api/season`、`/api/episodes/summary`、`/api/render/lanes`、`/api/render-tasks`
  - `data/producer/registry.json`
  - `series10_v1/assets/first_frame_jobs.json` 的 refs
  - `data/renders/ep*/S*/takes.json`（只取未隔离的版本）
  - 看图卡的 `/health`
- 生成脚本在会话 scratchpad 的 `uiov/build.py`、`build2.py`、`page.py`，可以重跑。

---

## 1 研究结论（带引用）

方法是逐条读官方文档和社区帖。置信度：高 = 读到原文；中 = 只读到搜索摘要或社区帖；低 = 第三方镜像。

### 1.1 镜头板与进度管理

| # | 结论 | 原文 | 链接 | 置信度 |
|---|---|---|---|---|
| R1 | ftrack：状态可以自定义很多个，但每个都必须归到 4 个“状态类”里，统计按这 4 类算 | “ftrack has four states that you need to map your statuses to.”（Not Started / In Progress / Done / Blocked） | https://help.ftrack-studio.backlight.co/hc/en-us/articles/13129960855575 | 中（原页 403） |
| R2 | ftrack 建议工作流保持简单 | 搜索摘要转述为 “Not Started, In Progress, and Completed or Approved” | https://help.ftrack-studio.backlight.co/hc/en-us/articles/13129959130007 | 中 |
| R3 | Frame.io 只有 3 个审阅状态，并用颜色标出 | “Let your teammates know when an asset is Approved, In Progress, or Needs Review.” / “New color-coded labels communicate the status of a clip” | https://blog.frame.io/?p=2146 | 高 |
| R4 | ShotGrid / Flow 自己提醒：状态设得太自由就会失控；可以用条件格式只高亮“已批准” | “With all of this freedom, it can be easy to become lost in a lot of different things to track” / “Use conditional formatting to highlight approved versions” | https://help.autodesk.com/cloudhelp/ENU/SG-Tutorials/files/SG_Tutorials_tu_tracking_statuses_html.html | 高 |
| R5 | Kitsu 默认 5 个状态：TODO / WIP / Waiting For Approval / Retake / Done。语义由标志位决定（is_done、is_retake、is_feedback_request），颜色只是表现 | 第三方镜像摘要 | https://mintlify.wiki/cgwire/zou/api/tasks/task-status | 低–中 |

### 1.2 AI 视频分镜工具

| # | 结论 | 原文 | 链接 | 置信度 |
|---|---|---|---|---|
| R6 | LTX Studio 按场景拆镜，并显示每个场景有几镜 | “You'll see how many shots each scene contains and what's scripted for each one” | https://ltx.io/blog/ltx-storyboard-generator-update | 中 |
| R7 | LTX 用画布网格并排对比、淘汰变体（和本页“过程版本小图”是同一个思路） | “The canvas makes variation visible enough to compare, reject and steal from yourself.” | https://www.jivochat.com/blog/reviews/software/ltx-studio-review.html | 低 |
| R8 | 即梦 Dreamina 每格分镜承载动作、机位、情绪；预览时看运动、构图、音画 | “show key actions, camera angles, emotional beats, and scene progression” | https://dreamina.capcut.com/create/script-to-storyboard-ai | 高（营销页） |
| R9 | 小云雀短剧 Agent 按集批量确认或重出 | “小云雀提供了‘批量选择’按钮” | https://news.qq.com/rain/a/20260529A02Z3W00 | 中 |
| — | Runway、可灵的卡片尺寸 | 未能读取（没有公开文档） | — | — |

### 1.3 状态色与信息密度

| # | 结论 | 原文 | 链接 | 置信度 |
|---|---|---|---|---|
| R10 | Linear 重设计：减少视觉噪声，少用品牌色，回到中性外观 | “reduce visual noise” / “limiting how much chrome (blue in our case) was used” / “return to a more neutral and timeless appearance” | https://linear.app/now/how-we-redesigned-the-linear-ui | 高 |
| R11 | Apple：不能只靠颜色传达信息，要配文字或形状 | “Avoid relying solely on color to differentiate between objects… or communicate essential information.” / “use text labels or glyph shapes to identify objects or states” | https://developer.apple.com/design/human-interface-guidelines/color | 高 |
| R12 | Apple：颜色只给真正需要强调的元素 | “reserve it for elements that truly benefit from emphasis, such as status indicators or primary actions” | 同上 | 高 |
| R13 | Apple：语义色定下来就不要挪作他用 | “Avoid redefining the semantic meanings of dynamic system colors.” | 同上 | 高 |
| R14 | Primer 只有少数语义色；attention 同时用于警告和进行中 | “attention: Warning states, active processes such as queued PRs and tests in progress” | https://primer.style/foundations/color/overview | 高 |
| R15 | Primer 的 StateLabel 每个状态都配专属图标 | “Each status variant has an associated icon, selected based on the status type.” | https://primer.style/components/state-label | 高 |
| R16 | Vercel Geist 默认用灰色 | “Use solid gray by default.” / “Background 2 should be used sparingly” | https://vercel.com/geist/colors | 高 |
| R17 | Material（Wear M2.5）：深色背景上饱和色会“振动”，应改用低饱和色 | “use desaturated colors as a more legible alternative” / “Use accent colors sparingly” | https://developer.android.com/design/ui/wear/guides/m2-5/styles/color | 中（M3 原页未能读取） |
| R18 | Tufte 的数据墨水比和 chartjunk：去掉不传递信息的装饰 | “any visual element that isn't really necessary and in fact distracts from the chart's meaning”（NN/g 转述） | https://www.nngroup.com/articles/clutter-charts/ | 高（转述；原书未读） |

### 1.4 深色图片网格

| # | 结论 | 原文 | 链接 | 置信度 |
|---|---|---|---|---|
| R19 | Pinterest Gestalt Masonry 默认列宽 236px | “columnWidth… The preferred/target item width in pixels.”（默认 236） | https://gestalt.pinterest.systems/web/masonry | 高 |
| R20 | Apple 深色模式：背景更暗、前景更亮；正文对比度不低于 4.5:1 | “dimmer background colors and brighter foreground colors” / “no lower than 4.5:1” | https://developer.apple.com/design/human-interface-guidelines/dark-mode | 高 |
| R21 | Apple：内容图在深色背景上会“发光”，可以稍微压暗 | “consider slightly darkening the image to prevent the background from glowing” | 同上 | 高 |
| R22 | Lightroom 网格只用 3 级灰表示 未选 / 选中 / 主选中，不用彩色；缩略图可以缩放 | “In grid view there are 3 levels of gray used to indicate not selected / selected and most selected.” | https://community.adobe.com/t5/lightroom-classic/way-to-change-background-color-of-cell-in-library-grid-view-lr-6/m-p/9482257 | 中（社区帖） |

### 1.4b 专业调色软件 DaVinci Resolve 的界面语言（项目方 01:4x 指定的主参考）

读取情况：
- Blackmagic 论坛直接抓取返回 403；手册 PDF 解析不出正文。下面标“中”的都来自搜索摘要或手册的 HTML 镜像。
- 官网 Color / Media / 新特性页读到了原文（标“高”）。
- Mixing Light、Frame.io Insider、No Film School 没有找到专门讲 UI 的文章。

| # | 结论 | 原文 | 链接 | 置信度 |
|---|---|---|---|---|
| D1 | 默认界面是偏冷的蓝灰；偏好设置里有开关，打开后变成完全中性、去饱和的灰；检视器背景也能单独换成灰 | “switches DaVinci Resolve to a totally neutral, desaturated gray UI” / “Use gray background in viewers” | https://www.steakunderwater.com/VFXPedia/__man/Resolve18-6/DaVinciResolve18_Manual_files/part133.htm | 中 |
| D2 | 不做亮色主题，理由是专业暗环境里发光的界面不受欢迎 | “professional, low light environments where a glowing UI is not desirable” | https://forum.blackmagicdesign.com/viewtopic.php?p=766674 | 中 |
| D3 | 标记颜色是一套固定色名（16 种），颜色只用在标记上 | “markerColor can be one of the following constants: resolve.MARKER_BLUE … MARKER_CREAM” | https://extremraym.com/cloud/resolve-scripting-doc/（官方脚本 README 镜像） | 中高 |
| D4 | 调色页缩略图上的旗标叠在缩略图顶部（左上起横排）；有 clip color 时显示一个彩点 | “a flag icon of the appropriate color appears on top of its thumbnail” | DR18.6 手册镜像 part2673 | 中 |
| D5 | 新版支持按已调色 / 未调色、星级、旗标、clip color 筛选（对应本页的“筛选 ▾”） | “Filter by graded, ungraded, star rating, flag and clip color” | https://www.blackmagicdesign.com/products/davinciresolve/whatsnew | 高 |
| D6 | 调色页布局：节点编辑器在右上，示波器在右下，Gallery 存静帧作参考，Lightbox 把全部镜头铺成缩略图 | “The node editor at the top right is like a flow chart” / “Stills can be organized into albums and are stored in the gallery” / “displays every clip in your timeline as a thumbnail with grades applied” | https://www.blackmagicdesign.com/products/davinciresolve/color | 高 |
| D7 | 调色页缩略图条：每张带镜头编号；已调色的编号有外框，多版本时是双框；图下文字可切换（编码 / 文件名 / 版本） | 手册摘要 | https://ltbits.github.io/davinci-resolve-manuals/DR12/DR12-RM-24.pdf | 中 |
| D8 | 媒体页：上方是存储，下方是媒体池，右边是元数据检查器；媒体池有缩略图 / 列表 / 胶片 / 元数据卡四种视图 | “an inspector to view and edit over 200 different metadata parameters” | https://www.blackmagicdesign.com/products/davinciresolve/media | 高 |
| D9 | 社区反面意见：字太小 | “the UI … is so small I cannot read it” | https://forum.blackmagicdesign.com/viewtopic.php?p=773979 | 中 |
| D10 | 社区反面意见：界面拥挤 | G2 评论里有 “cluttered interface” | — | 低 |

没核实到的：界面字体名、“时码用等宽字”的官方说法、面板细分隔线的官方描述。这几条是看截图得出的观察，本文只把它们当作风格借鉴。

### 1.5 提炼出的设计原则（本方案逐条落实）

- **P1** 状态收敛到 5 个语义态，细分原因只放悬停 / 面板（R1 R2 R3 R5）。
- **P2** 颜色只给“需要人看”的状态。其他状态用中性灰阶，或只用形状、动效（R4 R12 R14 R16）。
- **P3** 全页强调色不超过 3 个，深色背景上用低饱和色（R10 R17）。
- **P4** 状态 = 形状 + 文字，颜色排第三。◆ 需要你看、◌ 过期、呼吸点 = 正在出、✓ = 已确认（R11 R15）。
- **P5** 去掉每张图下的彩色胶囊。改成图角一个记号；排队和未开始不画任何记号，让例外显眼（R4 R18）。
- **P6** 去掉 9 个彩色筛选胶囊，改成中性的“筛选 ▾”菜单，选中项才高亮（R14 R16）。
- **P7** 进度只留一个维度、一条单色细线，加一句白话；不用多色分段条和自造符号（✗4、↓50）（R18 R1）。
- **P8** 图要大，大小可调（S / M / L 三档）（R19 R22，项目方 01:3x）。
- **P9** 没出图的镜不画大灰框。压成矮卡或收拢成一条，上面放已经备好的参考小图（R18）。
- **P10** 背景用深灰不用纯黑，卡片比背景亮一档；正文对比度 ≥ 4.5:1（R17 R20）。
- **P11** 缩略图统一压暗到 93%，悬停时恢复（R21）。
- **P12** 选中、悬停只用灰阶或一个 accent 描边，不和状态色共用颜色（R22 R13）。
- **P13** 语义色全站只定义一次。总览、画布、审片共用同一套 5 态（R13 R5）。
- **P14** 界面用中性灰分层：5 档相近的灰；面板之间 1px 深缝，加小号大写的面板标题条；不用彩色边框、大圆角和阴影（D1 D2）。
- **P15** 状态用旗标表达：缩略图左上角一面小旗（需要你看 = 黄旗，过期 = 橙色虚旗，已确认 = 绿旗），正在出 = 蓝点，镜号在右上。底边 3px 一条色带对应 clip color，只给 需要你看 / 过期 / 已确认 三种状态用（D3 D4 D7）。
- **P16** 版面借用调色页：上排是静帧库（参考 + 版本）、大检视器（主图 + 特写 + 尾帧）、检查器（状态 / 步骤 / 检查），中间一条全剧时间条，下面是镜头缩略带（D6 D7）。也提供媒体页式的“集列表 + 镜头池”（D8）。
- **P17** 字号偏小但可以缩放：正文 12px，面板标题 10.5px 大写；时码、镜号、数量用等宽数字；提供 100% / 125% 两档界面缩放，避免被吐槽字太小（D9）。

---

## 2 现状盘点

### 2.1 总览现有功能和信息项（功能对照的基准，共 31 项）

来源：`apps/web/src/v3/pages/SeasonPage.tsx`、`StatusTags.tsx`、`shotstatus.css`、`season.css`、`ds/StageProgress.tsx`。

**页头**
1. 标题“全剧总览”
2. 摘要行：集数 · 镜数 · 首帧 x/n · 尾帧 · 视频 · 通过 · 有候选待挑 n
3. “显示细节”开关（记在 localStorage `sea.detail`）
4. “人物时间线”开关
5. 全剧 7 段进度条（剧本 → 分镜 → 首帧 → 尾帧 → 视频 → 声音 → 成片）：完成数、进行中微光、失败 ✗n（悬停看原因）、减少 ↓n、预计时间

**图例与筛选**
6. 图例：段色含义、换场 ┃ / 同场换机位 ─ / 接力 ➜、在画 ● / 局部 ◐ / 画外 ○、换装
7. 板块筛选：过期 / 进行中 / 已确认 / 未开始（按集）
8. 9 类镜头标签图例，带数量，点一下按全剧筛选

**集行**
9. 集状态块（过期 / 进行中 / 已确认 / 未开始）+ 集左边框色
10. “第 N 集”链接，进画布
11. 集标题
12. 镜数 · 秒数
13. 进度一句（首帧 / 视频 / 过）
14. “细节 ▸”展开
15. 本集各类标签数量，可点筛选
16. 场景列表
17. 承上集（同场景 / 换场 + 悬停说明）
18. 各阶段胶囊（剧本 / 资产 / 首帧 / 尾帧 / 视频 / 成片）
19. 本集 7 段进度条
20. 选中整集
21. 当前集高亮

**镜卡**
22. 首帧图；没有当前首帧时显示最新一张合格候选；旧剧本的图不显示（写“未出（剧本已更新）”）
23. 尾帧小图叠在右下
24. 镜号
25. 主标签 + “+n”，悬停列出全部
26. “N 张候选”
27. “生成中”
28. “本地”（成人镜头）
29. 4 段进度：首 / 尾 / 视频 / 通过
30. 景别 · 时长、换装、人物时间线、场景色带、镜间衔接符号
31. 交互与状态反馈：
    - 点卡 → 进这一镜的画布行；Ctrl / Shift 点 = 多选
    - 跟画布同一过滤，不匹配的变暗；标签筛选时不匹配的变淡
    - 数字变化时闪一下（Flash）
    - 实时事件触发刷新，并每 60 秒刷新
    - 悬停提示汇总：id、景别、场景、时长、候选、成人、全部标签、img_summary、操作说明

### 2.2 每个状态的来源和真实含义（现行口径）

| 显示 | 来源 | 真实含义 | 问题 |
|---|---|---|---|
| 看图没过 vqa_fail（红） | registry 某阶段 status≠passed 且 last_error 含“契约没过”；或现行剧本最新 take 的 vqa_rounds judge=fail | 某一版没过契约 / 看图 | 不区分“系统还会自动重试”和“重试用完”。上游首帧在重做时，下游尾帧的旧失败照样报 |
| 旧剧本版本 old（紫） | candidates 里只剩 script=old 的版本 | 只有剧本更新前出的图 | r41 隔离后现在为 0 |
| 待重出 redo（琥珀） | registry redo / master_reject | 已重置 / 驳回，等重出（现在是 L-088 全量重做） | 按计划进行的重做被当成异常色。严重度排在“出图中”前面，所以正在出的镜也显示“待重出” |
| 过期 stale（橙虚线） | registry stale | 剧本 / 输入改了 | 和 redo 语义重叠 |
| 待补判 judge（灰蓝点线） | 最新 take 的 vqa 未测，或 Q9 untested | 看图结果还没出 | 实际原因常常是看图卡积压或 OOM，属于生产问题 |
| 尽力版 best（粉） | registry best_effort | 用了罚分最小的一版 | 真正需要人接受 |
| 出图中 busy（蓝） | registry running | 正在出 | 被 redo 压住，看不到 |
| 排队中 queued（灰） | registry ready 且不是 redo / stale | 等空闲卡 | — |
| 通过 ok（绿） | registry passed | 这一阶段通过 | 一镜可能同时“尾帧通过 + 首帧待重出”（42 镜） |
| 集“过期 / 进行中 / 已确认 / 未开始” | shot_status.episode_blocks：任一阶段有 old/stale/redo 就“过期”，上游过期则下游也过期 | — | 全量重做期间 10 集全挂“过期”，信息量为 0 |

**实测分布**（11-02 01:29 `/api/season`）

- 主标签：待重出 85、看图没过 14、排队中 2、尽力版 1。
- 按镜计带标签的数量：待重出 98、通过 51、看图没过 14、出图中 9、排队 4、待补判 3、尽力版 1。

### 2.3 口径错误（交 UIRSI 修；r42 正在锁这些文件，请一并处理）

| # | 现象 | 根因（已核实） | 建议修法 |
|---|---|---|---|
| K1 | 顶栏“卡 0/7 忙”，而服务器 5 道其实在跑 | GpuPanel.tsx 的 `laneBusy` 只看 `/api/render/lanes` 里 ComfyUI 的瞬时 `/queue`。01:32 实测：lanes 全是 idle 或 external，但 `/api/render-tasks` 有 rendering 6、producer heartbeat 的 inflight=9。两次之间的上传 / 后处理 / 看图阶段都读成空闲。7 = 5 条服务器道 + 长镜头道 gpu36:2 + laptop:0，分母也不对 | 忙闲按 producer 在办的单（registry.tasks / heartbeat.inflight 按 lane 归属）加“最近 60 s 出过东西”判断；分母只算 5 条出图道；长镜头道、笔记本道单列 |
| K2 | 我们自己的 producer 任务显示成“外部任务” | lanes 的 activity=external 是“ComfyUI 有任务但不是 ns_api 发的”，而服务器常驻 producer 正好不经 ns_api | 能对上 producer 登记（extra_data.ns_tag）的就写“出图”；对不上的才写“其他任务” |
| K3 | “渲染任务 1 跑 · 301 等 · 30 失败”看不懂 | “等”297 = 计划中 199（plan：缺图镜，还没提交）+ producer 排队 98。“失败”29 = 3 天前（10-29~30）旧流程的 ns_api 视频任务，没有被后来的成功覆盖 | 顶栏只写“在办 n · 排队 m”，m 只算 producer 真正排着的单；“计划中”只放抽屉里；失败只算近 24 小时内、没被后来的成功覆盖、且不在隔离区的，旧失败归档 |
| K4 | 进度条“首帧 4/102 ✗4” | `/api/progress` 的 failed 计入了连接错误（WinError 10061、“API 重启中断”） | 基础设施错误不计入内容进度，进生产健康 |
| K5 | 进度条“尾帧 ⇂50” | regressed：r40/r41 隔离旧剧本尾帧后数量减少 | 隔离是有意为之，不算“减少”；或者只在悬停里说明 |
| K6 | 正在出的镜显示“待重出” | shot_status 的 ORDER 把 redo 排在 busy 前面 | 改用 §3 的“最前一步”规则 |
| K7 | 10 集全挂“过期” | episode_blocks 把计划内的 redo 当成 stale | 计划内重做 = 进行中；只有没排上的才算过期 |
| K8 | 集摘要仍把旧剧本的“当前”尾帧算作有尾帧（r40 已报 DATAALIGN） | — | 跟进 |

另外，样稿快照时 gpu36 看图卡 `/health` 是 loaded=false，last_error 为 CUDA OOM，积压 6；笔记本看图卡积压 5、served 0。这就是“检查中”镜头卡住的真实原因，应该显示在生产健康里，而不是挂在镜卡上。

---

## 3 状态模型收敛：每镜一个主状态，共 5 种

### 3.1 规则

一镜的主状态 = **流水线上最前面一个还没确认的步骤**的状态。步骤顺序：首帧 → 尾帧 → 视频 → 你审。

- 上游在重做时，下游的旧结论自动作废，不再另报。这样 K6 和“尾帧通过 + 首帧待重出”的冲突就消失了。
- 全部步骤都确认后：视频没审 = 需要你看（视频待你审）；审过 = 已确认。

### 3.2 五态

| 主状态 | 记号（旗标 + 文字；缩略图左上角） | 颜色 | 什么时候出现 |
|---|---|---|---|
| 需要你看 | 黄旗 + 底边 3px 黄色色带 | 唯一的实心强调色 `--need` | 最前一步是：尽力版等接受 / 重试用完仍没过 / 视频待审 / 有候选但系统不会自动选 |
| 过期 | 橙色虚旗 + 底边 3px 橙色色带 | `--stale` | 最前一步的输入变了，且还没排进重出 |
| 进行中 | 正在出 = 蓝色呼吸点；排队 = 不画记号，图下灰字“排队 / 排队重出”；检查中 = 灰字 | 低饱和 `--doing`，只用于点和底线 | 正在出 / 排队 / 计划内重出 / 看图检查中 / 没过但系统会自动重试 |
| 未开始 | 不画记号，灰字“未开始（等首帧）” | 灰 | 最前一步没有任何动作（等上游） |
| 已确认 | 绿旗 + 底边 3px 绿色色带 | 低饱和 `--done` | 全部步骤确认、审过 |

项目方要求“已确认 / 进行中 / 过期”三种必须看得出来：分别对应 ✓ 绿勾、蓝呼吸点 + 灰字、橙虚线。保留了语义，只是收敛了表达方式。

### 3.3 旧标签 → 新主状态

| 旧 kind（阶段 = 最前一步时） | 新主状态 · 图下文字 |
|---|---|
| busy / registry running | 进行中 · 正在出 |
| judge | 进行中 · 检查中（看图卡积压 / OOM 进生产健康） |
| redo / master_reject（registry status=ready） | 进行中 · 排队重出（悬停：第 1/2 次） |
| queued | 进行中 · 排队 |
| vqa_fail，attempts < max | 进行中 · 没过，自动重试 n/max |
| vqa_fail，attempts ≥ max | 需要你看 · 重试 n 次都没过：原因 |
| best | 需要你看 · 尽力版，等你接受 |
| stale / old，且没排进重出 | 过期 · 按旧剧本 / 旧输入出的 |
| stale / old，已排进重出 | 进行中 · 排队重出 |
| ok（这一步） | 看下一步 |
| 下一步 pending 且 waiting_for 上游 | 未开始（等首帧） |
| 视频已出、review=unreviewed | 需要你看 · 视频待你审 |
| review passed | 已确认 |

### 3.4 实测结果

用 `build.py` 跑当前数据，102 镜全部是“进行中”（正在出 11，其余排队重出 / 检查中），需要你看 0。整页因此安静下来，这是真实情况：系统在按 L-088 全量重做，眼下没有要人做的事。样稿底部附了 5 种状态的样例（图是真的，状态是演示）。

### 3.5 集层面

- 不再给每集挂状态块。
- 只在集标题后加两枚提示：`需要你看 n`（实心黄）、`过期 n`（虚线橙）。没有就不显示。
- 其余写成一句灰字：“10 镜 · 60 秒 · 有图 3/10 · 首帧定了 0/10”。

### 3.6 后端（交 UIRSI，shot_status.py）

- 新增 `main5: need|stale|doing|todo|done`、`why`（一句大白话）、`running: bool`。旧 `tags` 保留，供悬停和面板使用。
- episode_blocks 增加 `need_n`、`stale_n`。

---

## 4 信息层级与版面

### 4.1 共同部分（A、B 一样）

1. **顶栏**：口径修正后写“● 出图 4/5 道在出”“工具 ▾”。“渲染任务”按钮保留，数字按 K3 修正。
2. **页头一行**：“全剧总览”+ 一句白话：“10 集 · 102 镜 · 首帧定了 2 · 视频 0 · 现在不需要你看 · 系统在重做，11 镜正在出”。有需要你看时，这一段换成黄字“n 镜需要你看”。
   - 右边是中性按钮：`筛选 ▾`、`细节 ▾`、`图 S/M/L ▾`，再加生产灯。
   - 生产灯平时是“● 生产正常”（灰绿点），异常时变成黄点“生产偏慢”或红点“生产停了”。
3. **生产健康**收在生产灯的弹层里，默认不展开：
   - 5 条出图道各自在出 / 空闲 / 连不上；
   - 2 张看图卡各自是否可用、积压多少；
   - 每张首帧耗时（近 5 单中位数）、排队单数、预计出完时间；
   - 近 24 小时没解决的失败数。
   - 数据源：`/api/factory/health`（r42 正在做）。
4. **一条单色细进度线**：首帧定了 / 总镜数，替代 7 段条。7 段条移进“细节 ▾ → 各阶段进度”。
5. **集**：标题行一行（见 §3.5）+ 右侧“打开本集 → / 选中整集”。

### 4.2 样稿 B：调色页式（推荐做默认）

1440 × 900 一屏放得下，1920 × 1080 时同比例放大。

```
┌ 顶栏 44 ───────────────────────────────────────────────────────────────┐
├ 页工具条 34：全剧总览 · 一句白话 ············ 筛选▾ 细节▾ 图M▾ ●生产 ┤
├ 参考·静帧 300 ┬ 检视（中性深灰底）────────────┬ 检查 320 ────────────┤
│ 这一镜用的参考 │   主图 9:16（≈ 250×445 / 1440）│ 状态 / 原因 / 景别   │
│ 身份脸/造型/   │   特写 118×118                  │ 时长 / 出场          │
│ 单品板/场景    │   尾帧 118×210                  │ 步骤：首帧→尾帧→     │
│ 出过的版本     │ 时码 · 景别 · 场景（底条 24）   │ 视频→你审            │
│ ✓ ✕ …         │                                 │ 最近一版：结论 /     │
│                │                                 │ 脸像 / 视线；操作    │
├ 全剧时间条 30：01 … 10，宽度按秒数，底部 2px 是“有图”比例 ───────────────┤
├ 镜头缩略带 268：本集每镜 118×210（+9%）+ 时码 + 状态词 ──────────────────┤
└─────────────────────────────────────────────────────────────────────────┘
```

- 单击缩略带的镜头 = 上排换成这一镜；双击或点“打开这一镜 →” = 进画布（防误点）。
- 点时间条 = 换集。
- 没图的镜仍占一格，格里显示出场人物的身份脸小圆和景别。镜位顺序看得见，又不是一块大灰框。
- 图片尺寸：
  - 检视主图约 250 × 445（1440）/ 350 × 620（1920），是现状 105 × 190 的 2.3 倍以上，项目方要的“图大、看得见细节”在这里满足；
  - 缩略带 118 × 210（+9%）；“图 L”档 136 × 242（+26%）。
- 不合并的理由：缩略带是导航，检视器才是“看”。

### 4.3 样稿 A：媒体页式

- **左栏“集”**（200 宽）：全部 + 01–10 每集一行，写“有图 x/n”，下面一条 2px 灰线表示比例；底部是“标记”说明。
- **右栏“镜头池”**：每集一个分组，标题一行；每镜一张工作卡：
  - 主图 150 × 267（1440，+43%）/ 1920 同尺寸，每行 10；
  - 过程条：脸部局部 44、最近 3 版 23 × 41（带 ✓ ✕ …）、尾帧；
  - 参考条：34 × 44 × 4；
  - 底行：景别 · 时码 + 状态词。
- **没图的镜**：矮卡（约 150 × 80）——镜号、景别、状态词 + “参考已备好”的 4 张参考小图。
- 点任一镜 → 跳到 B 视图并选中这一镜。
- 图片档位：S 128（+19%）、M 150（默认）、L 200。

### 4.4 A 和 B 的分工

- 默认打开 B（调色页式）：一屏同时看到一集的镜头带、一镜的大图 + 特写 + 参考 + 版本，最贴近项目方说的“看到很多工作状态的图”。
- A 当“细节 ▾ → 镜头池视图”：适合横向扫全剧所有已出的图。
- 两者用同一份数据、同一套旗标。

### 4.5 脸部局部

样稿是按“林晚蓝发”的颜色启发式裁的，个别会偏，比如双人镜裁到男主后脑。实施时请改用 postflight 已经测到的人脸：Q1 / G1 的 evidence 里有 faces，但目前没有落 bbox。需要后端在 `contract.postflight.items[Q1].evidence.faces[]` 补 `bbox`，再加一个 `/api/thumb?crop=` 参数（交 UIRSI + REFLOCK 用 CONSENT）。

---

## 5 Token（深 / 浅两套）

### 5.1 颜色（调色软件式：中性灰分层，颜色只给旗标）

| token | 深色 | 浅色 | 用途 |
|---|---|---|---|
| --seam | #0d0d0d | #b5b5b5 | 面板之间 1px 缝（面板“嵌”在一起的感觉） |
| --g0 | #141414 | #c9c9c9 | 检视器底、缩略图底 |
| --g1 | #1b1b1c | #d6d6d6 | 工具条、缩略带、镜头池 |
| --g2 | #222223 | #e0e0e0 | 面板 |
| --g3 | #2a2a2b | #e9e9e9 | 面板标题条、按钮 |
| --g4 | #333335 | #f2f2f2 | 选中行、悬停 |
| --hair | #3a3a3c | #bdbdbd | 按钮描边、弹层边 |
| --t1 / --t2 / --t3 | #d6d6d6 / #9a9a9a / #6a6a6a | #1c1c1c / #4f4f4f / #7d7d7d | 正文 / 次要 / 弱 |
| --sel | #e6e6e6 | #111111 | 选中描边（白，不用彩色） |
| --need | #e9c046 | #a87c00 | 黄旗：需要你看 |
| --stale | #e0864f | #b4561c | 橙色虚旗：过期 |
| --doing | #5f95d0 | #2f69a8 | 蓝点：正在出 |
| --done | #58b383 | #257a50 | 绿旗：已确认 |
| --bad | #d9605a | #b83a33 | 版本 ✕、生产“停了” |

- 默认是纯中性灰（D1 的“中性灰”开关打开后的效果）。以后如果要加“略带冷色”的主题，只需要调 --g0 到 --g4 这五档。
- 不做彩色面板。缩略图统一压暗到 93%，悬停时恢复。
- 对比度：--t2 在 --g2 上约 5.9:1；--t3 只用于时码、辅助说明。
- 现有 theme.css 的映射：`--c-bg`→g1、`--c-raise`→g2、`--c-sunken`→g0、`--c-line`→seam / hair、`--c-ok`→done、`--c-info`→doing、`--c-stale`→stale；--need 和五档灰是新增的。
- 是只在总览生效（`.sea-page` 作用域）还是全站切换，请总调度定。全站切换会影响画布（E7）的观感，不影响结构。

### 5.2 字号、间距、圆角

- 字号：
  - 面板标题 10.5px，大写，字距 .08em，颜色 t2；
  - 正文 12px；集名、页名 13px；
  - 时码、镜号、数量用等宽字（JetBrains Mono / Consolas），tabular-nums。
- 界面缩放 100% / 125% 两档，放在“图 ▾”菜单里（D9）。
- 间距：4 / 6 / 8 / 10 / 12 / 14。面板内边距 10，卡片间距 6–12。
- 圆角：2（缩略图）、3（按钮）、4（弹层）。不用大圆角，不用阴影（弹层除外）。
- 动效：只有正在出的蓝点呼吸（1.4 s）；遵守 prefers-reduced-motion。

## 6 功能对照（31 项都有去处，不删）

| # | 现有功能 | 新去处 |
|---|---|---|
| 1 | 标题 | 保留 |
| 2 | 摘要行 | 改成页头一句白话（首帧 / 视频 / 需要你看 / 在出）。尾帧数、通过数、候选待挑数进“细节 ▾ → 数字” |
| 3 | 显示细节开关 | 并入“细节 ▾”菜单（仍记在 localStorage） |
| 4 | 人物时间线开关 | 细节 ▾ → 人物时间线 |
| 5 | 全剧 7 段进度条（✗、↓、预计时间） | 页头单色细线 + 细节 ▾ → 各阶段进度（原组件原样）。✗ / ↓ 改成文字写在悬停里；基础设施失败进生产健康 |
| 6 | 图例 | 细节 ▾ → 图例；主状态图例在“筛选 ▾”里每项自带记号 |
| 7 | 板块筛选（按集） | 筛选 ▾ → 按集：有需要你看 / 有过期 / 在做 / 已确认 / 未开始 |
| 8 | 9 类标签筛选 + 数量 | 筛选 ▾ → 按镜：5 主状态（带数量）+ “更多原因”展开 9 类旧标签（带数量） |
| 9 | 集状态块 + 左边框色 | 改成集标题后的“需要你看 n / 过期 n”；没有就不显示 |
| 10 | 第 N 集链接 | 保留，另加“打开本集 →” |
| 11 | 集标题 | 保留 |
| 12 | 镜数 · 秒数 | 保留（灰字） |
| 13 | 进度一句 | 保留：有图 x/n · 首帧定了 x/n |
| 14 | 细节 ▸ | 保留，每集 |
| 15 | 本集各类数量筛选 | 细节 ▸ 里，点了能筛 |
| 16 | 场景列表 | 细节 ▸ |
| 17 | 承上集 | 细节 ▸；悬停说明保留 |
| 18 | 各阶段胶囊 | 细节 ▸，改成灰阶文字 + 有问题的阶段才上色 |
| 19 | 本集 7 段进度条 | 细节 ▸ |
| 20 | 选中整集 | 保留 |
| 21 | 当前集高亮 | 保留（集号前加 accent 竖条） |
| 22 | 首帧 / 候选 / 旧剧本不显示 | 保留，主图更大；“候选”角标 |
| 23 | 尾帧小图 | A：过程条里单独一格；B：面板里 |
| 24 | 镜号 | 保留 |
| 25 | 主标签 + “+n”、悬停看全部 | 主状态记号 + 图下状态词；悬停 / 面板里列出全部旧标签和原因 |
| 26 | N 张候选 | 角标“候选 n”，过程条里能直接看到这些版本 |
| 27 | 生成中 | 蓝色呼吸点 + “正在出” |
| 28 | 本地（成人） | 保留，右上镜号旁加灰色“本地”小字 |
| 29 | 4 段进度（首 / 尾 / 视频 / 通过） | 细节 ▾ → “每镜四段”开启后显示在底行；悬停 / 面板里的步骤清单（首帧… / 尾帧… / 视频…）也有 |
| 30 | 景别 · 时长、换装、人物时间线、场景色带、衔接符号 | 景别 · 时长默认显示在底行；换装、色带、衔接符号、人物时间线在细节 ▾ 里分别开关 |
| 31 | 点卡进画布、Ctrl / Shift 多选、过滤变暗、标签筛选变淡、Flash、实时刷新、悬停汇总 | 全部保留。B 里单击 = 看面板，双击 / “打开这一镜” = 进画布（防误点） |

新增：调色页式三栏（静帧库 / 检视 / 检查）、全剧时间条、镜头缩略带、脸部局部、过程版本小图（带判定）、参考图条、生产健康弹层、图片 S / M / L、界面缩放。

不推翻的已定规则：
- 画布一镜一行、首尾帧大图（E7），视频大于首尾帧，资产 tab：都不在本页，不受影响。
- 已确认 / 进行中 / 过期三种语义：见 §3.2。
- 旧剧本版本隔离、只看最新（K-UI-046）：过程条只取未隔离的版本，历史版本仍走 ⋯ → 历史版本。

---

## 7 给 UIRSI 的实施清单（按优先级）

### P0：口径（先改对，再改样子）
1. K1 / K2：顶栏出图道忙闲改按 producer 在办 + 最近 60 s；分母是 5 条出图道；自家任务不再写“外部任务”。改 GpuPanel.tsx 和 `/api/render/lanes` 或 factory_health。
2. K3：“渲染任务”按钮只写“在办 n · 排队 m”；计划中、3 天前旧失败不进数字（render_tasks.py 的 counts 加 `queued`、`planned`、`failed_recent`——r42 锁里已列出）。
3. K4 / K5：`/api/progress` 的 failed 不计基础设施错误；隔离导致的减少不标 ↓。
4. K6 / K7：shot_status 增加 `main5`、`why`、`running`（§3）；episode_blocks 加 `need_n`、`stale_n`，计划内重做不算过期。测试：用 01:29 的快照断言 102 镜 main5=doing，以及 ep01-S1 的 why=“首帧排队重出（第 1/2 次）”。

### P1：总览骨架（B 调色页式为默认）
5. SeasonPage 按 §4.2 的调色页布局实现：静帧库 / 检视 / 检查 三栏 + 全剧时间条 + 镜头缩略带。同时：
   - 页头一句 + 单色细线；
   - 中性“筛选 ▾ / 细节 ▾ / 图 S M L ▾”，替代彩色图例、板块胶囊和 9 胶囊；
   - 集行收敛（§3.5）。
6. 镜头缩略：左上旗标、右上镜号、底边色带、图下“时码 + 状态词”；图片档位 S / M / L 和界面缩放 100% / 125% 记在 localStorage `sea.size`、`sea.zoom`。
7. 没图的镜：缩略带里显示出场身份脸 + 景别；镜头池视图里是矮卡 + 参考小图。
8. 生产灯 + 弹层，接 `/api/factory/health`，8 s 轮询，异常才变色。

### P2：工作状态图
9. `/api/season` 每镜加：
   - `refs`：作业 refs → `/files/...` + 类别（身份脸 / 造型 / 单品板 / 场景底图）；
   - `takes`：最近 3–6 个未隔离版本的缩略图址 + 判定 v / w / sim / gaze，取自 contract.postflight；
   - `last` 当前尾帧。
   只读 takes.json 和 first_frame_jobs.json，带 mtime 缓存。
10. 过程条和参考条（A），点小图打开现有大图查看器。
11. 脸部局部：postflight 落人脸 bbox + `/api/thumb?crop=x,y,w,h`（需要 REFLOCK 的 CONSENT）。上线前过程条先不放脸格，不要用颜色启发式。

### P3：镜头池视图与收尾
12. 细节 ▾ → “镜头池”视图（A，媒体页式）：左边集列表、右边工作卡，点卡跳到 B 并选中这一镜。
13. token（§5）：五档中性灰 + 旗标四色；总览不再使用 busy / adult / 场景色带作为默认色。是否全站切换由总调度定。
14. 画布 / 审片行的 MainTag 换成同一套 5 态记号（P13），旧 9 类留在悬停里。
15. G10 功能对照：按 §6 的 31 项逐条找得到；截 1440 / 1920 × 深 / 浅四张图。UIAUDIT 复核时加一条：页面上同时出现的强调色不超过 3 种。
