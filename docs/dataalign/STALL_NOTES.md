# :8800 整体卡顿（15–17 s）排查笔记（DATAALIGN，总调度 11-01 P1）

本文是可续接笔记：笔记本离线前后都以这里为准，每推进一步就更新。

## 现象
- 偶发时几乎所有接口同时变成 15–17 s，过一会儿自己恢复；平时只有 10–150 ms。
- UIMASTER 爬虫日志里的卡顿窗口：
  - 04:47：docs/uimaster/runs/iter_013.out
  - 05:41：docs/uimaster/runs/iter_014.out
  - 08:57：docs/uimaster/runs/iter_015.out
  - 10:38：docs/uimaster/runs/iter_027.out
- 卡顿时一批互不相干的接口一起慢，慢的程度也差不多（同一秒内 7–10 s）：render/lanes、render-tasks、looks/episodes/1、sop/episode/1、readiness、cuts。说明慢的不是某一个接口，而是整个进程。

## 怀疑方向
- 事件循环被同步代码阻塞（async 处理函数里做了重活）。
- 线程池被占满。
- 某个吃 GIL 的后台线程长时间占着 CPU。

## 当前步骤
1. 已有：tools/qa/data_parity/stall_watch.py。每秒探一次 /api/comfy-lock（很轻的同步接口），超过 2 s 就用 py-spy dump 抓服务器全部线程的调用栈，存到 docs/dataalign/stalls/。
2. 后台运行命令：`.venv/Scripts/python.exe tools/qa/data_parity/stall_watch.py --minutes 120`
3. 结论和修法写在下方“进展”，按时间顺序追加。

## 进展
- 11-01 10:47 起：后台运行 stall_watch（每秒探测，最长 5 h；py-spy 先用非阻塞方式重试，不行再用阻塞方式；pid 取已建立连接的那个 python 进程，因为这台机器上监听行显示的 pid 是 0）。到 10:55 为止没有抓到超过 2 s 的卡顿，探测最慢 0.09 s。
- 已排除：render_tasks 的 HTTP 自调用只在 SOURCE=http 时才会走，默认不走。async 处理函数全是上传接口和 SSE（SSE 每 0.5 s 让出一次），没有 async 重活。
- 怀疑一（放大器）：按镜缓存单飞时，等待别的请求算完的请求也占着线程池名额（anyio 默认 40 个）。几个慢计算叠在一起（预热、后台 TTL 重算、集摘要刷新）就会占满，连 render/lanes、looks 这种轻接口也得排队。这和日志里“一批不相干的接口同时 7–10 s”对得上。
- 怀疑二：CPU 密集的后台线程（集摘要全量重算、按镜后台重算、postflight-sweeper）抢 GIL。
- 已加（重启 :8800 后生效）：
  - services/api/ns_api/loop_watchdog.py：每 0.5 s 往事件循环投一个回调。回调延迟超过 1.5 s，或线程池占满，就往 data/qa/loop_lag.jsonl 写一条，带上全部线程的调用栈；平时每 60 s 写一条心跳，记录最大延迟和线程池最高占用。
  - 同步线程池从 40 调到 100（环境变量 NS_THREADPOOL 可改）。
- 续接时按这个顺序看：
  1. data/qa/loop_lag.jsonl 里 kind=stall 的记录：threadpool 是 [100,100] 说明线程池占满；loop_pending_s 很大说明事件循环被堵。
  2. docs/dataalign/stalls/*_stall.txt 里的 py-spy 调用栈。
  3. 拿记录时间去对 UIMASTER 爬虫日志里的慢窗口。
- 11-01 11:05 **复现并确认根因**：80 个 /api/shots/{id} 同时并发 → 18.9 s 才全部返回；同一时间最轻的 /api/comfy-lock 也慢到 6.8 s。
  - 原因：镜头详情每次都现算（每个版本都要判一次过期），同步线程池 40 个名额被占满，再叠加 GIL 串行。
  - 画布、阅读页、爬虫一次拉全集详情时，就会出现“整体卡 15–17 s”。
- **已修（重启 :8800 后生效）**：
  - /api/shots/{id} 加按镜缓存：签名与 /api/episodes 相同，另加本镜 errors/compiled/visual_spec 三个文件；摘要（含任务字段）每次取最新。
  - 缓存结果与现算逐字段相同（tests/test_summary_fresh.py::test_shot_detail_cached_equals_fresh）。
  - 进程内 80 镜：第一次 7.6 s，之后 0.76 s。
  - 详情缓存也随按镜缓存一起写盘（data/cache/api_snapshots/shot_detail.pkl），重启后直接读回。
  - 同步线程池 40 → 100。
  - 看门狗 data/qa/loop_lag.jsonl。
- **重启后要复核**：
  1. 重跑上面的 80 并发突发：轻接口的延迟应 < 1 s。
  2. 看 data/qa/loop_lag.jsonl 有没有 kind=stall。
  3. 看 stall_watch 有没有抓到新的卡顿。
