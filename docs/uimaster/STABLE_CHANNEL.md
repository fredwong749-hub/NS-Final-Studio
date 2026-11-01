# 项目方稳定通道（PW-019）· 运维说明

## 为什么要有
项目方一直开着 http://127.0.0.1:5173 看生产进度。这个地址原来是 vite 开发服务器，所以任何 agent 一存前端文件，页面就会热更新。热更新失败时会退化成整页重载或大片重挂，项目方看到的就是"刷新闪得难受"。PAGEWATCH 统计 11-01 共有 197 次 Fast Refresh 失败，详见 docs/pagewatch/issues.md#PW-019。

## 切换后的样子

| 地址 | 是什么 | 谁用 |
|---|---|---|
| http://127.0.0.1:5173 | 稳定版：只放过了 gate.sh 的生产构建。静态文件由 apps/web/e2e/uimaster/stable/server.mjs 提供，/api 和 /files 原样转发到 :8800（SSE 实时推送照常） | 项目方；所有"项目方看到什么"的验收 |
| http://127.0.0.1:5174 | vite 开发服务器（热更新） | 各 agent 改代码、本轮自测、复爬新改动 |

项目方开着的标签页不用重开：切换时 vite 客户端断线，探测到 :5173 恢复后会整页刷新一次，地址不变，登录不变（Cookie 不分端口）。

## 怎么更新（构建器）
- 构建器是 apps/web/e2e/uimaster/stable/rebuild.mjs --loop，常驻运行，每 15 分钟检查一次。
- 只有 src、index.html、vite.config.ts、package.json 有变化时才动手：
  1. 先跑 apps/web/e2e/uimaster/gate.sh（tsc、爬虫自检、组件导出检查、vite build、开发服务器模块、data_parity）；
  2. 闸门全过，才构建到 stable/builds/b<本机时间>/；
  3. 构建完，原子改写 builds/current.txt。服务端每 2 秒读一次这个指针，所以换版不停服。
- 闸门不过：不切换，项目方继续看上一份，原因写进 stable/builds/rebuild.log。
- 只保留最近 6 份构建。
- 带指纹的 assets/* 永久缓存；index.html 每次都向服务器确认，所以换版后项目方下次刷新、或在页面里跳转时就会拿到新版。

## 常用命令（在 apps/web/e2e/uimaster/stable/ 下）
- node rebuild.mjs：立即检查一次，源码有变就构建。
- node rebuild.mjs --force "原因"：源码没变也重建，但照样要过闸门。
- node rebuild.mjs --list：列出保留的构建，当前那份前面标 *。
- node rebuild.mjs --rollback：指回上一份构建。2 秒内生效，不用重启服务。
- curl http://127.0.0.1:5173/__stable：查当前是哪一份构建。

## 切换和回退
- 切换：pwsh apps/web/e2e/uimaster/stable/switch.ps1。由总调度安排时间，因为项目方的页面会断一下。
  步骤：
  1. 确认已有一份过了闸门的构建；
  2. 在 :5174 起开发服务器；
  3. 停掉 :5173 上的开发服务器；
  4. 在 :5173 起稳定版；
  5. 启动构建器。
  任何一步失败都会自动回退。
- 整体回退（不要稳定通道了）：pwsh apps/web/e2e/uimaster/stable/switch.ps1 -Rollback，:5173 恢复成开发服务器。
- 开机自启 ops/autostart/laptop_autostart.ps1：切换完成后，把"3) 前端 :5173（vite dev）"一节改成"开发服务器 :5174 + 稳定版 :5173 + 构建器"。切换当天由 UIMASTER 改，改法和 switch.ps1 第 1、3、4 步一样。

## 切换后要改端口的工具（各自的 owner 改一行：BASE 读环境变量 NS_WEB，默认 http://127.0.0.1:5174）
- 新改动的自测、复爬要打开发服务器 :5174：
  - apps/web/e2e/uimaster/crawl.mjs（UIMASTER，已支持 UIM_BASE）
  - apps/web/e2e/uiaudit/detect.mjs（UIAUDIT）
  - apps/web/e2e/uipixel/scan.mjs、probe.mjs、cardshot.mjs（UIPIXEL，已支持 UIPX_BASE）
  - apps/web/e2e/uirsi/shoot.mjs、probe.mjs、tasks.mjs、netdbg.mjs、netimg.mjs、netlist.mjs、vite.live-demo.config.mjs（UIRSI）
  - apps/web/e2e/assetux/shoot.mjs（ASSETUX）
  - apps/web/e2e/editdel/shoot.mjs（EDITDEL，现由 UIMASTER 代管）
  - apps/web/e2e/gpuview/shoot.mjs（GPUVIEW）
  - apps/web/e2e/dataalign/probe.mjs（DATAALIGN）
  - apps/web/e2e/voice10/shoot.mjs（VOICE10）
  - tools/ui_smoke/smoke.mjs
- "项目方看到什么"的验收打稳定版 :5173：
  - apps/web/e2e/pagewatch/watcher.mjs、freshload.mjs（PAGEWATCH 本来就是看项目方页面，保持 :5173）
  - UIAUDIT 的"项目方视角"复测（加一个 NS_WEB=http://127.0.0.1:5173 跑法）
- 只是在文案或日志里写了链接，不影响运行：tools/assetmaster/choose.py、register_items.py、tools/autopilot/producer.py。给项目方看的链接继续写 :5173，这正是稳定版。
- gate.sh 已改成自动找开发服务器（先 :5174，再 :5173），切换前后都能用。

## 已经验证（切换前，在 :5199 试跑）
- 构建 b20261031-055534 过了 gate.sh（data_parity 634 项，不一致 0），:5199 首页 200，/api/auth/me 200，深链接回 index.html。
- /api/events SSE 经转发能收到 hello 事件；页面顶栏显示"实时"，不显示"断开"。
- 爬虫在 :5199 上爬 shell / canvas / assets_char / sound：没有报错层、白屏、控制台或接口错误，G11 全过，记录在 docs/uimaster/log/ 的 918 次干跑输出里。
