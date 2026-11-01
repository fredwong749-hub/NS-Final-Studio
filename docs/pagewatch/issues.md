# PAGEWATCH 问题单（#/script-create?run=series10_v1 常驻观察）

观察者：PAGEWATCH（apps/web/e2e/pagewatch/watcher.mjs，无头 Chrome CDP 9731，只读查看令牌，非 GET 全拦）。
每轮原始记录：apps/web/e2e/pagewatch/cycles/cNNN.json；截图：apps/web/e2e/pagewatch/shots/。
状态：open → fixed（owner 说修了）→ verified / reopened（PAGEWATCH 复查）。

## PAGEWATCH 自身规则（总调度 11-01 定）
- R1 巡检绝不能改项目方的持久偏好（localStorage、cookie、视图模式、筛选等）。长开的“项目方视角”主标签用默认 profile，只看不点；点击巡检和 1920 / 浅色快照一律开在独立的 browser context 里（Target.createBrowserContext，独立存储，用完即弃）。每轮记录主标签的 localStorage 快照，变了就记一条并排查来源。
  - 起因：11-01 点击巡检点了“阅读模式”，偏好写进同一 profile 的 localStorage，主标签跟着切到阅读模式（c115–c142 镜头行 0 行）。已改正。
- R2 只读：非 GET 请求一律在 CDP 层拦下回 503；不重启 :8800，不改生产数据。
- R3 侧标签会让无头 Chrome 把主标签当后台、节流定时器；Chrome 启动时已加 --disable-background-timer-throttling 等参数。
- R4 统计闪烁 / 跳动时，剔除 vite 热更新窗口（前后 4 s）；整页重载单独计数，作为 PW-019 / PW-020 类问题上报。

---

## PW-001 · P1 · 各集小卡里的进度条看不见（宽度塌成 12px，轨道宽 0）· owner UIPIXEL · **verified**
- 复查 02:33（本地时间）：UIPIXEL 在 ds.css 加了 `.ns-sep .sp{align-self:stretch}`；10 张小卡都看得见 7 段小条，宽 107px，和接口一致。截图 shots/B001_verify.png
- 时间：2026-11-01 17:23（c001）
- 截图：apps/web/e2e/pagewatch/shots/B001_ep_chip_progress.png、shots/c001_1440_dark.jpg（1920 / 浅色同样：shots/c001_1920_dark.jpg、c001_1440_light.jpg）
- 复现：打开 http://localhost:5173/#/script-create?run=series10_v1（1440×900 深色），看“第 1 集 … 第 10 集”小卡。
  在控制台：`document.querySelector('.ns-sep .sp').getBoundingClientRect().width` → 12；`.ns-sep .sp-track` 宽 0。
- 期望：每集小卡里有一条 7 段的紧凑进度条（剧本/分镜/首帧/尾帧/视频/声音/成片），能看出每集做到哪（DOM 里数据是对的，如第 1 集 首帧 3/7 ✗1）。
- 实际：小卡里什么都看不到。原因：`.ns-sep` 是 `flex-direction: column; align-items: flex-start`（v3/pages/story.css:171），`.sp.sp-compact` 不拉伸 → 只剩 gap 宽度。
- 建议：`.ns-sep .sp { align-self: stretch; }`（或 width:100%）。CSS 归 UIPIXEL。

## PW-002 · P2 · 首次打开时顶栏“渲染任务”按钮闪一下（数据从无到有也算“变了”）· owner UIRSI · **verified**
- 再复查 c007（02:37 新开页面，UIRSI 二次修复后）：加载时 0 次闪烁；切集时也 0 次闪烁。关闭。
- 复查 c005（新开页面）：顶栏不闪了，但**整季 + 10 集共 11 条进度条的 77 段在加载后同一毫秒全部闪了一遍**（17:32:07.866）。原因：PW-003 的修法先渲染“剧本 —”占位进度条，占位值不是 null，占位→真数据就被 useFlash 当成“变了”。项目方每次打开页面都会看到满屏闪。建议：占位时不挂 SegView 的 useFlash，或者把占位值也传成 null。
- 时间：2026-11-01 17:23（c001，drain.flashes[0]：button.v3-queue，页面加载 80 ms 后）
- 复现：打开页面，注入 MutationObserver 看 `.live-flash` 类：加载时 `.v3-queue` 立刻闪。
- 期望：useFlash 的约定“第一次渲染不闪”；首次拿到数据不该闪（项目方：只对更新的板块渐进闪）。
- 实际：RenderTasks.tsx:422 `useFlash(c ? [...] : null)` —— 先记下 `null`，数据到了 null→值 判成变化 → 每次打开 / 切页都闪。
- 建议：live.ts useFlash 里 prev 为 "null" 时只记录不闪（所有用 `x ? … : null` 的地方一起修好）。

## PW-003 · P2 · 首次加载布局跳动 CLS≈0.24 · owner UIRSI→PRODUCER/UIPIXEL · **verified**
- 第三次复查 03:01（freshload.mjs，新开标签，12 s）：**CLS 0.0274**（<0.1），加载时 0 次闪烁。制作监督骨架已预留 250px（实际高度 250px）。关闭。截图 shots/F1_1440_dark.jpg
- 再复查 c007（02:37）：CLS 仍是 **0.447**，仍未修好。
- 复查 c005：CLS 变成 **0.4327**（变差了）。来源：`div.ns-progress h47→291`（制作监督面板 section.ns-prod 晚到，一下子撑出 244px）、`nav.ns-series 257→494`、`details.ns-process 857→0`。现在跳动主要来自 ns-prod 没有预留高度。
- 时间：2026-11-01 17:23（c001，drain.shifts）
- 复现：PerformanceObserver(layout-shift) 打开页面：
  一次 0.2317：`nav.ns-series 264→257 h129→161`、`details.ns-process 868→0`、`div.ns-progress 186→179`；另有 0.0073、0.0049 两次（骨架 360px 被替换、v3-rows 485→494）。
- 期望：CLS < 0.1（骨架尺寸和真实内容一致，集条高度预留）。
- 实际：集条从 129 长到 161、写作过程折叠条消失再出现，整块往下推。

## PW-004 · P2 · /api/producer/status 404（页面显示“自动制作状态读不到 · API 需要重启一次”）· owner PRODUCER · **verified**
- 复查 c005：:8800 已重启，接口返回 200，页面不再报 404。
- 时间：2026-11-01 17:23（c001 起每次加载都有；控制台 1 条 404）
- 复现：`curl -H "x-ns-viewer-token: …" http://127.0.0.1:8800/api/producer/status` → 404 {"detail":"没有这个接口"}
- 期望：接口在线，页面显示自动制作状态。
- 实际：:8800 还在跑旧代码。PAGEWATCH 不重启 :8800，只记录；重启后复查。

## PW-005 · P1 · 制作监督面板的每集数字和进度条对不上（第 1 集 首帧 0/0，进度条是 3/7）· owner PRODUCER · **verified**
- 复查 03:02：serve 起来后，10 集分母都等于镜数（7/8/7/7/8/8/11/8/8/8）；首帧 / 尾帧 / 视频 和 /api/progress 逐集对比，9 集完全一致，只有第 1 集尾帧对不上（单列为 PW-011）。关闭。
- PRODUCER 02:36 回复：原因是 `once --only` 验证进程把整季 registry.json 按 only 过滤后写回去了；已改成登记表一律按整季推导（tests 通过），常驻 serve 起来后每 20 秒重写一次。口径说明：制作监督的“首帧”= 当前首帧已过契约的镜数，/api/progress 的首帧 = 有当前首帧的镜数，两者完成数可以不同（有意如此，面板提示里会写明）。等 serve 起好后复查：分母必须等于每集镜数。
- 时间：2026-11-01 02:33 本地（c005）
- 截图：apps/web/e2e/pagewatch/shots/B003_progress_block.png
- 复现：GET /api/producer/status?run=series10_v1 → episodes[*].shots 是空数组 []；页面就显示“第 1 集 首帧 0/0 · 尾帧 0/0 · 视频 0/0”，第 2 集“首帧 0/2”。
  同一页的 /api/progress：第 1 集 首帧 3/7 ✗1、第 2 集 2/8；整季 首帧 5/80。
- 期望：制作监督按镜追踪，分母等于每集镜数（7/8/…），完成数和 /api/progress 一致。
- 实际：分母 0（或 2），两块数字互相矛盾，项目方看不出到底做到哪。另外显示“制作监督没在跑（开机自启会拉起）· 842 秒前更新”：heartbeat_age_s≈842，服务没在跑。这一条是实情，只告知。

## PW-006 · P2 · 制作监督面板没有样式：灰底白字一行一块，深色主题对比度低 · owner UIPIXEL · **verified**
- 复查 03:02：紧凑两列、每集一行，深色下可读，高 250px 和骨架一致。截图 shots/B006_verify.png。关闭。
- 时间：2026-11-01 02:33 本地（c005）
- 截图：apps/web/e2e/pagewatch/shots/B003_progress_block.png
- 复现：深色 1440 打开页面，看“整季进度”下面的 section.ns-prod。
- 期望：和整页设计统一（ns-prod* 类名在 ProducerPanel.tsx 里注明样式归 UIPIXEL），高度固定或预留，避免 PW-003 的跳动。
- 实际：ns-prod* 没有任何 CSS 规则；10 行“第 N 集 …”是浅灰底加白字的胶囊，对比度低，像没做完的界面。整块高 244px，加载后才出现。

## PW-007 · P2 · 切集时整块重挂：进度条、集小卡全换新节点，镜头区先变成大骨架，跳动 CLS≈0.105 · owner UIRSI · **verified**
- 复查 02:50（UIRSI 把 key 改成只认 run.id）：从第 4 集切到第 2 集，整季进度条和集小卡**是同一个节点**，CLS 0.0007；只有镜头区出骨架（数据还没到，可以接受）；点当前这一集无骨架、无跳动。关闭。
- 时间：2026-11-01 02:39 本地（主标签实测）
- 截图：apps/web/e2e/pagewatch/shots/B007_ep_switch_skeleton.png（切到第 4 集后约 0.3 s：镜头区是一整块 360px 骨架）
- 复现：在页面里点任一集的小卡（比如第 3 集 → 第 2 集），用 MutationObserver 和 PerformanceObserver 观察：
  `.ns-progress .sp`（整季进度）和 `.ns-sep`（集小卡）点击前后都**不是同一个 DOM 节点**；出现 `div.ns-run-view>span.ds-skel`；
  layout-shift 合计 0.105（ds-skel 480→739 h360→161）。再点一次当前这一集，也会骨架一闪（CLS 0.017）。
- 期望：切集时只换镜头行那一块（项目方：“只对更新板块”）；整季进度和集小卡跟集号无关，应该原地不动；点当前这一集什么也不发生。
- 实际：NewScriptPage.tsx 里 RunView 的 `key={`${run.id}:${run.episode}`}`，集号一变整个 RunView 卸载重建（pickEp → loadRun → 新 run.episode → 新 key），所以连进度条和小卡都换了新节点，镜头区先出骨架。
- 备注：UIRSI 的 PW-002 修复后，切集已经不闪了；剩下的是重挂、骨架和跳动。

## PW-008 · **P1** · :8800 重启后页面的实时连接变成“僵尸”：不报错、不重连，徽标仍是绿色“实时”，进度一直停在旧值 · owner UIRSI · **verified**
- 守住两次重启复查（livewatch.mjs，每 3 s 读徽标、boot 和 :8800）：① UTC 18:06:22 API 断，18:06:29 恢复，18:07:15 页面自己换到新 boot 1a193243630；② 18:10:20 断，18:10:28 恢复，18:11:01 换到 boot 1a19327d338。全程没按 F5；之后 stale.log 没有陈旧记录，进度和接口逐段一致（c018、c019 进度不符 0）。重连延迟 33–46 s（看门狗 25 s 加后端启动），可以接受。关闭。
- 02:53 HMR 换上新 live.ts 后，看门狗立刻重连，补收 177 条事件，陈旧消失（c013）。live.py 的 ping/boot 要等下一次重启。
- 时间：2026-11-01 01:39–01:50 本地（UTC 17:39–17:50；c009–c011 + stale.log）
- 截图：apps/web/e2e/pagewatch/shots/B008_stale_series.png（第 2 集首帧 2/8）、B008_live_ind_green.png（顶栏仍是绿色“实时”）
- 复现：
  1. 开着页面；:8800 被重启（这段时间 01:39:45、01:43:37、约 01:46 都有一段 502，SSE 的 seq 从 93 重置到 4）。
  2. 页面的 EventSource 在 CDP 里仍是 open，`window.__live` 最后一条停在 seq 93（ts 01:39:32），之后 **537 s 一条事件都没收到**。
  3. 同一时间直连 `curl -N :8800/api/events`，45 s 收到 84 条 video/frame 事件。
  4. 页面数据过期：第 2 集 首帧 页面 2/8 / 接口 3/8，整季 首帧 页面 5/80 / 接口 6/80，**持续 200 s 以上还在涨**（stale.log）；徽标 `.live-ind` 一直显示“实时”。
- 原因：vite 代理把浏览器这一头的连接保持着，后端那头已经断了，浏览器收不到 error，live.ts 的 onerror 不会触发 → 不退回轮询，也不重连。后端每 15 s 发一次心跳，但用的是 SSE 注释（`: ping`），EventSource 的 onmessage 看不到，前端没法用它判断连接还活着。
- 期望：后端重启后几秒内自动重连（或退回轮询），重连后补一次全量重取；连接真断时徽标不能是绿色“实时”。
- 建议：
  (a) live.py 的心跳改成真正的事件（如 `data: {"type":"ping"}`），或者加一个 `event: ping` 并在前端 addEventListener('ping')；
  (b) live.ts 加看门狗：40 s 没收到任何消息（含 ping）就 es.close() 重开，并在重开前切到“连接中”；
  (c) 收到 hello 的 seq 比上次小 → 说明后端重启过 → 发一次 tick 让各块全量重取。
- live.py 在 services/api（共享，需要先在 LOCKS 登记）；live.ts 是 UIRSI 的。

## PW-009 · P2 · 制作监督接口一次 502，整块面板就消失，页面上跳 239px，15 s 后又跳回来 · owner PRODUCER · **verified**
- 复查：UTC 18:06:22 producer/status 502 时，面板保持 250px，c018 没有 ≥0.03 的跳动（只有常驻的 0.026，见 PW-015）。关闭。
- 时间：2026-11-01 01:39:47 → 01:40:02、01:43:47 → 01:44:02 本地（c009、c010 的 layout-shift）
- 复现：PerformanceObserver：`div.v3-rows.sf-fullrows 733→494`、`nav.ns-series 509→270`（CLS 0.0817），15 s 后反过来 `494→733`（又 0.0817）。两次都正好落在 `/api/producer/status` 返回 502 的时候（:8800 重启窗口）。
- 期望：接口偶尔失败时保留上一次的数据（加一个小的“暂时读不到”标记），不要把整块卸掉。项目方一直开着页面，每次后端重启都会看到整页上下跳两次。
- 实际：ProducerPanel 出错就不渲染（或者换成很矮的错误条），内容整体上移 239px；恢复后再撑开。

## PW-010 · 信息（不是前端 bug）· :8800 在 01:39–01:46 之间反复不可用 · 告知总调度
- vite 代理在 01:39:45–49、01:43:37–49 返回 502；render-tasks、jobs、lanes、render-backend、producer/status 一起 502，前后还有 6–14 s 的慢请求；SSE 的 seq 在约 01:46 重置。看起来是有人在重启 :8800。PAGEWATCH 不重启，只记录。后台有一个每秒探测（apps/web/e2e/pagewatch/api_probe.log）在继续记。

## PW-011 · P2 · 第 1 集 S5 制作监督说“尾帧、视频已过契约并设为当前”，接口里这一镜没有尾帧、没有视频 · owner PRODUCER（抄送 DATAALIGN）· **verified**
- 复查 03:13：制作监督改成读 /api/episodes/summary（和 /api/shots/{id}.frames 同一来源）；10 集首帧 / 尾帧 / 视频和 /api/progress 0 处不一致；视频括号改名“VIDEO10 定下 k”，不再自相矛盾。关闭。
- 时间：2026-11-01 03:02 本地
- 截图：apps/web/e2e/pagewatch/shots/B006_verify.png（第 1 集：尾帧 1/7（过契约 1）· **视频 0/7（过契约 1）**）
- 复现：
  `/api/producer/status?run=series10_v1` → episodes[0].shots 里 ep01-S5：first passed、**last passed（“v1 过契约并设为当前”）**、**video passed**；
  `/api/episodes/1` → ep01-S5 `last_frame: null`；`/api/progress` 第 1 集 尾帧 0/7、视频 0/7。
- 期望：制作监督的“当前版本”和画布 / 进度用的是同一份 current（takes.json）；“过契约 k”不能大于完成数 n。
- 实际：面板显示“视频 0/7（过契约 1）”，自相矛盾；尾帧面板 1/7、进度 0/7。可能是制作监督读的是自己的登记，没读 takes.json 的 active，或者 S5 的 take 没走 register_takes 写入口。

## PW-012 · P2 · 声音进度倒退（整季 7/56 → 3/56）页面没说原因 · owner UIRSI · **verified**
- 复查 04:52（c054 碰上一次真实倒退：第 2 集首帧 5→3、尾帧 4→3，第 3 集 3→2，第 4 集 6→5，整季首帧 24→20、尾帧 19→17）：整季条显示黄色“↓4”“↓2”，悬停写“比之前少了（24 → 20）：有版本被撤下 / 标了不要 / 换剧本后作废，要重出”；各集小卡的悬停提示也有同样说明。和 /api/progress 的 regressed 字段逐项一致。截图 shots/B012_regressed.png。关闭。
- 05:03 追加：UIRSI 给倒退段加了细黄边（inset 1px --c-warn）。第 3 集视频 2→0 时，集小卡上不用悬停就能看到（shots/B012b_chip_edge.png）。
- 小建议（不算 bug，已采纳）：集小卡太小，只有悬停提示，看不到角标；可以考虑给倒退的那一段加一个细黄边。
- 时间：2026-11-01 约 02:58 本地
- 复现：c001–c014 整季声音一直是 7/56（第 1 集 6/6，第 2 集 1/3）；现在 /api/progress 是 3/56（第 1 集 3/6，第 2 集 0/3）。
  原因可以查到：config/voices.json 在 02:58:14 改了（演员表换了），TTS 缓存按音色计，旧句子不算了。倒退本身是对的。
- 期望：一段进度倒退时，页面要说为什么（比如段的悬停提示或角标：“演员表 02:58 改了，3 句要重配”），不能只是条子变短。项目方会以为是 bug 或者数据丢了。
- 同类：c015 还记到 **第 1 集首帧 3→2**（S1 那张首帧画布上标“过期·需重出”，大概率因此不再计入），页面同样没说原因。
- 建议：/api/progress 的 seg 加一个 `regressed_reason`（live.py 可以比较上一次的值，或者看 voices.json 的 mtime），StageProgress 显示出来。

## PW-013 · P2 · /api/render-backend 常常 2–10 s（/api/render/lanes 也到过 11–14 s）· owner GPUVIEW / IMGPERF · **verified**；lanes 部分由 IMGPERF 修，03:49:52 重启后生效
- 复查 04:13：/api/render/lanes 直连 6 次 20–430 ms；c039–c041 没有 lanes 慢请求。c038 有一次 26 s，但那一刻所有接口一起卡了 25–39 s（render-tasks 37.8 s、producer/status 39.5 s），是 API 整体停顿，不是 lanes 的问题。
- 另外：GPUVIEW 的“渲染中 79”已修，复查时 API rendering 7–14，每条都在真实的卡道上（gpu36:0/1/2、gpu33、gpu33-cpu），顶栏显示同一量级。
- 复查 03:09：重启后连续 5 次 11–24 ms。
- 时间：2026-11-01 02:47–02:56 本地（apps/web/e2e/pagewatch/api_probe.log，每秒直连 :8800 探测）
- 复现：`curl -w "%{time_total}" :8800/api/render-backend` 循环调用。9 分钟内有 10 次超过 2 s（最慢 10.1 s）；同时段 /api/jobs、/api/episodes/summary 都正常。页面每轮请求它约 11 次（c009 记到 11.5 s）。
- 期望：<300 ms（缓存结果，后台刷新）。
- 实际：返回体很小但很慢，像是在请求里同步去探 GPU 后端，卡住了请求线程。

## PW-014 · P2 · live.ts 没有 HMR 清理：每热更新一次就多一条 /api/events 长连接（主标签现在同时 3 条），事件重复 · owner UIRSI · **fixed（部分复查通过）**
- 复查 03:36：主标签刷新后，c024–c027 EventSource 一直 opened 1 / closed 0；`__live` 20 条全不重复，tick 不重复，`window.__liveDispose` 已装上。还缺一次 live.ts 自然热更新来验证不再累积；等到了再标 verified。
- 时间：2026-11-01 03:10–03:13 本地
- 复现：开着页面，等 live.ts 被热更新（开发期常有）。CDP 看主标签：c016–c019 的 EventSource 累计 opened − closed 一直是 **3**；`window.__live` 里同一个 seq 出现两次（`frame:83`、`stage:84`、`stage:85` 各两次；本地 tick 也是成对出现）。
  直连 :8800/api/events 每个 seq 只有一次，所以重复来自前端。
- 期望：任何时候一个标签只有一条 SSE。
- 实际：src/v3/live.ts 没有 `import.meta.hot.dispose`，旧模块实例的 EventSource、看门狗和轮询定时器热更新后还在跑。项目方用的就是 :5173 开发服务器，所以他也会遇到：
  vite 是 HTTP/1.1，每个域名最多 6 条连接，3 条常驻 SSE 占掉一半，其余 /api 请求只能排队（首屏慢、慢请求的一部分原因）。
- 建议：live.ts 末尾加 `if (import.meta.hot) import.meta.hot.dispose(() => { es?.close(); stopPoll(); clear 看门狗 })`。

## PW-015 · P2 · 页面闲着时每 1–2 分钟有一次小跳动：整季进度块上移 7px（CLS 0.026 / 次）· **关闭（不是 bug）**
- 定位 03:16：c020 的 3 次跳动全在 HMR 热更新窗口里（±4 s），特征和首屏一样：集条 h125→157，是集小卡进度条后到。闲置时（没有 HMR）没有复现（ResizeObserver 守了 2.5 分钟，0 次变化）。首屏 0.026 在 0.1 预算内。只是开发期热更新引起的重挂，不算产品 bug。
- 时间：c017（UTC 18:03:39、18:05:07）、c018（18:08:10），新开标签也有（F3）
- 复现：PerformanceObserver：`div.ns-progress 186→179`，以及 `nav.ns-series 523→516 h125→157`、`div.ns-viewsw 664→689`。说明上面的页头（ns-rh）高度变了 7px，或者有一行在换行和不换行之间来回变。
- 期望：数据刷新时版面不动。
- 下一步：PAGEWATCH 继续定位是哪个节点变高。

## PW-016 · **P1** · 一阵实时事件就让页面把全季 84 镜的详情全拉一遍，其它请求排队 96 s · owner UIRSI（LiveBridge.tsx；store.tsx 是共享文件要登记 LOCKS）· **verified**
- 最终复查 04:03：c035（UTC 18:53:32）、c036（18:59:05）各来了一阵 **80 镜**事件（10 集全有，5 s 内）。页面只取了第 1 集 4 镜和 2 镜的详情，跨集 0 次；超过 10 s 的请求 0 条。关闭。
- 复查 03:53（第二版：只取当前集 + 正在看的镜，全局队列每批 4 镜）：c032、c033 两轮 SSE 消息 45 条，跨集逐镜重取 **0** 次，没有风暴；c032 的 11 条慢请求都在 18:49:45 :8800 重启的那几十秒里，不算这条。
- 复查 03:45（c030，UIRSI 的修改 18:36:17 UTC 已热更新上）：仍有一轮 **81 镜**，从 18:40:31 到 18:42:25 分批取完，每集 7–11 镜，10 集都有；慢请求 89 条，其中 74 条超过 10 s，最慢 31.7 s；producer/status 26 s，render-tasks 26 s，jobs 22 s。
  原因：过滤条件 `s.details[id] || cur.has(id)` 在长开的标签里形同虚设，之前几轮风暴已经把全季 84 镜的详情都放进了缓存，所以每镜都“已加载”。另外每次 flush 各跑一个“4 镜一批”的循环，几次 flush 叠在一起又变成并发。
  建议：只重取当前集（cur）的镜，加上正在打开的查看器那一镜；别的集的详情缓存标成“过期”，等切到那一集时再取；所有 flush 共用一个全局队列，同一时刻最多 4 条。
- 时间：UTC 18:29:25–18:30:53（c026；c003 也出现过一次 80 镜）
- 证据：apps/web/e2e/pagewatch/cycles/c026.json 的 `shotStorm`：84 次 `GET /api/shots/{id}`（ep01–ep10 每镜一次），84 次都是同一条调用栈：
  `window.fetch@netDedupe.ts:24 < req@api.ts:4 < shot@api.ts:34 < store.tsx:405 < store.tsx:440 < flush@LiveBridge.tsx:28 < LiveBridge.tsx:39`
  同一时段：`/api/jobs`、`/api/producer/status`、`/api/render-backend`、`/api/candidates`、`/api/episodes/1/readiness` 都等了 **96 s**，`/api/episodes/1` 13 s。本轮慢请求 113 条。
- 复现：开着第 1 集，后端一次发出多镜的 video/frame/job 事件（比如 VIDEO10 写 draft，或者重连后补发），LiveBridge 的 flush 把事件里所有镜号交给 `refreshAfter(list)` → `refreshShots(ids)` → `Promise.allSettled(ids.map(api.shot))`。不管这一镜在不在当前集、页面有没有用到它的详情，都一次全部并发去取。
- 期望：只重取页面上看得到、已经加载过详情的镜（`detailsRef.current[id]` 存在，或者属于当前集）；别的集只刷摘要。并发要限流（比如 4 条）。
- 实际：瞬间 84 条并发；vite 是 HTTP/1.1，每个域名 6 条连接，加上常驻 SSE，整页请求排队一分半，进度和面板都卡住不更新。
- 建议：LiveBridge flush 里 `list.filter(id => s.details[id] || s.episode?.shots.some(x => x.id === id))`，剩下的只 `refreshEpisodes()`；refreshShots 加并发上限。

## PW-017 · P2 · 一镜换了首帧，整行（1120×378，占屏幕 1/3）一起闪，而不是只闪变了的那一格 · owner UIRSI · open
- 时间：UTC 18:54:08、18:55:14、18:59:00（c035、c036 的 drain.flashes，area 0.327）
- 复现：开着第 1 集，等任一镜首帧出新候选或换当前版本。MutationObserver 看到 `article.v3-row` 整行加上 live-flash（1120×378）。
- 代码：src/v3/ReviewRow.tsx:342 `const rowFlash = useFlash([s.first_frame, s.first_frame_take, s.last_frame_target, s.last_frame_take, s.video, s.review?.state, status.text])`，359 行把它挂在整行上。
- 期望（项目方原话：“只对更新板块进行渐进的 flash”）：首帧变了只闪首帧那一格，尾帧变了只闪尾帧格，视频变了只闪视频格，状态变了只闪状态胶囊；整行不闪。
- **verified** 04:24：c043–c045 共 35 次闪烁，全在格子级别（`div.v3-frame.cand` 首帧候选格、`span.v3-status-wrap` 状态胶囊、`div.sp-seg.sp-first` 单段进度、顶栏任务按钮），大面积（>10% 屏）0 次，内容没变的 0 次。c044 那阵 80 镜事件期间也没有整行闪。关闭。
- 实际：任一字段变化都闪整整一行，生产高峰期第 1 集 7 行轮流大面积闪。
- 建议：拆成 4 个 useFlash（first、last、video、status），各自挂在对应的格子上。

## PW-018 · **关闭（正常）**· 后面 3 次重启重连 11 s / 28 s / 33 s；最初的 116 s 是个例· 19:11 那次 :8800 重启后，页面过了 116 s 才连上新后端（前几次 28–46 s）· owner UIRSI · 待再测
- 时间：UTC 19:11:03 API 断，19:11:09 恢复，19:13:05 页面才换到新 boot 1a1935f6c58（livewatch）。这段时间主标签在前台，不是 PAGEWATCH 的第二个标签造成的节流。
- 第二次实测（UTC 19:19，主标签已关节流）：19:19:13 API 断，19:19:16 恢复，**19:19:44 页面换到新 boot 1a19366e20c，用时 28 s**。总调度说接下来还有一次重启，再测一次就结案。
- 看门狗阈值 25 s，理论上应在 30–40 s 内重连。下一次重启再测；如果还超过 60 s，就转 UIRSI 查看门狗或重连退避。
- PAGEWATCH 自己的修正（04:18）：之前开侧标签（1920 / 浅色快照、点控件）时，无头 Chrome 会把主标签当后台标签节流定时器，渲染任务 4 s 轮询会停 ~40 s。已给 Chrome 加 --disable-background-timer-throttling 等参数，现在主标签和项目方前台标签行为一致。此前在侧标签窗口里看到的“顶栏落后 20+ s”不算 bug，已作废。

## PW-019 · P2 · 开发服务器热更新经常“Could not Fast Refresh”，项目方开着的页面被整块重挂、甚至整页重载 · owner UIMASTER（跨多个文件，按 ownership 分给各 owner）· open
- 时间：2026-11-01 01:21–05:46 本地（cycles/*.json 的 vite 消息汇总）
- 现象：项目方一直开着 :5173（开发服务器）。别的 agent 每改一次下面这些文件，Fast Refresh 都做不了，vite 就 invalidate、重跑上层模块，大片界面重挂（骨架、闪、滚动位置丢失）。传到根时直接整页重载：实测 UTC 17:33:14、20:41:39 两次整页重载（20:41:39 那次是 ZoomLayer.tsx 新增导出 ZOOM_LONG_MAX）。
- 原因：组件文件里同时导出了非组件的值，Fast Refresh 只能热换“只导出组件”的模块。按次数排：
  ReviewRow.tsx passBlock 24 次｜TopBarV3.tsx V3_PAGES 24｜components/Drawer.tsx errSummary 21｜RenderTasks.tsx ago 14｜pages/EpisodeReader.tsx parseP4 13｜EpisodeProduce.tsx useProduceView 12｜MaterialsDrawer.tsx openMaterials 11｜ds/editdel.tsx editApi 11｜ds/index.tsx ASSET_STATUS 9｜edit/RightTabs.tsx RIGHT_TABS 8｜edit/RefSwitchPanel.tsx tidyOptions 7｜ds/StageProgress.tsx useProgress 5｜StoryboardDetails.tsx H3_BLOCKS 4｜ShotCard.tsx mediaChain 4｜edit/RefBar.tsx SRC_TAG 4｜LeftRail.tsx aggChars 3｜frames.tsx jobStageText 3｜store.tsx LEGACY_REDIRECT 2｜sop.tsx useSop 2｜ui.tsx useUi 2｜OwnerDecision.tsx DECIDABLE 2｜edit/Stage.tsx modeCap 2｜ZoomLayer.tsx fullSrc / ZOOM_LONG_MAX｜ProducerPanel.tsx plain
- 期望：别人改代码时，项目方开着的页面只热换改动的那一小块，不重挂、不整页刷新。
- 建议：把这些常量、函数、hook 挪到同名的 .ts 文件（比如 ReviewRow.helpers.ts），组件文件只导出组件。各文件按 ownership.yaml 分给各自 owner。
- 说明：这只影响开发服务器 :5173；但项目方就是用它看生产进度的。
- 进展 09:14：各 owner 正在把导出挪到 *.helpers.ts。挪的过程中仍会有个别整页重载（UTC 00:13:46：Seam.tsx 删掉 seamCheck 导出 → invalidate → 整页重载）。这是过渡期的现象；挪完以后同类失败次数应该降到 0，PAGEWATCH 会逐轮统计。
- 09:29：c155 两分钟内整页重载 4 次（UTC 00:26:46、00:26:47 themeMode.tsx initTheme；00:27:58、00:28:05 MediaPlayer.tsx claim 两次）。

## PW-020 · P2 · 08:26–08:35（本地）项目方开着的页面被整页重载了 56 次（约每 10 秒一次），期间一直是骨架屏 · owner UIMASTER（:5173 开发服务器 / 稳定通道）· **fixed（待观察）**
- 原因（UIMASTER 09:0x）：safe_edit.sh 的 tsc 沙盒建在 apps/web/.tsc_sandbox，每次写回都会新建、再删掉一份 tsconfig.json 和 vite.config.ts。vite 当成配置变化，重启开发服务器，页面整页重载。那段时间正是 PW-019 连续挪导出。已把沙盒挪到 node_modules/.cache/uim_tsc_sandbox；PAGEWATCH 已确认旧目录删掉、脚本路径已改。
- PAGEWATCH 对时间戳：56 次重载里只有 10 次在 3 s 内跟着 Fast Refresh 失败（AuthGate 4、StageProgress 3、OwnerDecision / Undo / RenderTasks 各 1），另外 46 次前面没有 invalidate，符合“开发服务器整体重启”的解释，不完全是挪导出本身。
- 复查办法：之后有 agent 连续 safe_edit 时，看主标签有没有“connecting → connected”成串出现。
- 时间：UTC 23:26:00–23:35:00（c132–c135）
- 截图：apps/web/e2e/pagewatch/shots/c132_1440_dark.jpg（剧本列表和主区全是骨架，正文只有 178 字）
- 证据：主标签的 vite 客户端在这 10 分钟里出现 56 对“[vite] connecting... → [vite] connected.”（c132 20 对、c133 23 对、c134 9 对、c135 4 对）。每一对都表示开发服务器断了又回来、整页重载一次。c132 那一刻集数 页面 0 / 接口 10。
- 已排除：vite.config.ts、tsconfig.json、package.json、index.html 在这段时间都没改（最后修改 10-30 / 10-31），所以不是 vite 自己因为配置变化而重启，像是外部在反复重启或抢占 :5173 的开发服务器进程。同一时段前后有 gate.sh / 稳定通道的构建（e2e/uimaster/stable/builds 08:46 有更新）和取消掉的切换尝试。
- 期望：项目方开着的页面不应该因为后台工具反复整页重载。稳定通道正式切换前，gate.sh 和自测都别动 :5173 上的开发服务器进程。
- 需要 UIMASTER 确认：08:26–08:35 有没有脚本在启停 :5173 的 vite，或者另起了一个 vite 抢这个端口。
