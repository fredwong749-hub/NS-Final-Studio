# GPU 实时面板 + 渲染任务中心（GPUVIEW 2026-11-01）

项目方原话：
- “实时展示gpu显卡做什么任务细节”
- “顶部我需要一个rendering任务tasks,告知我现在整个系统需要rendering的任务(剧本,镜头,图片,视频等细节)一个all,pending,rending状态对应的objects”
- 画布底栏：“这里uiux设计头不喜欢,展示内容也很快,你思考重构”

规则：K-OPS-G01（每个 GPU 任务都要带 comfy_tag，check `tests/test_gpuview.py`）、K-OPS-G02（渲染任务只有一份登记表，数字对得上，check `tools/qa/render_tasks_parity.py`），见 `knowledge/rules/ops_gpuview.yaml`。

## 1. 为什么以前只写“其他任务占用”

各 agent（IMGGEN / ASSETMASTER / VIDEO10 / BAKEOFF / SERIES …）直接往 ComfyUI 投任务，ns_api 只认得自己队列里的任务，别人的一律算“外部任务”。
gpu36 的温度 / 显存原来只经 gpu33 的 ssh 读，gpu36 根本没读，所以写“读不到”。

## 2. 约定：投 ComfyUI 时带标签（comfy_tag）

```python
from ns_agent import comfy_tag as CT        # services/agent/ns_agent/comfy_tag.py，只用标准库
body = {"prompt": g, "client_id": CLIENT + uuid.uuid4().hex[:8]}   # client_id 不改（各工具按前缀认领自己的任务）
CT.attach(body, CT.make("VIDEO10", "video", episode=1, shot="S6", label="Ref2VA 24 步", attempt=2, max_attempts=4))
```

- 标签放在 `extra_data.ns_tag`，ComfyUI 原样留在 `/queue` 和 `/history` 每项的第 4 个元素里。
- 字段：`agent`（谁）、`kind`（first_frame / last_frame / frame / video / sheet / voice / tts / bakeoff / edit / train / other）、`episode`（数字）、`shot`（"S4"）、`label`（一句补充）、`attempt` / `max_attempts`（第几次，1 起）、`idx` / `total`（批量第几张）、`obj`（对象，如“林晚 · 造型C”）、`job`（工具自己的作业 id）。
- 面板显示：`CT.describe(tag)`，例：“出首帧 · 第3集 S4 · 第2次重试”、“视频 · 第1集 S6 · Ref2VA 24 步”、“模型对比 BAKEOFF · 第 212/391 张”。
- 没带标签的任务：按 client_id 前缀、输出文件名（filename_prefix）、模型名推断，写“未标记任务 · FLUX 资产图 · …”，agent 后面标“（推断）”。
- 已接入：imggen.py（含借用它的 ASSETMASTER / REFLOCK 脚本）、assetmaster/*、vidgen.py、bakeoff/run.py、pipeline/submit_jobs.py、char_assets/asset_gen.py、gen_contract/reflock_validate.py、prompt_v2/plan_c_*、ab/char_sheet_qi21.py、ab/consist_swap.py、ns_render/comfy_client.py（`client.ns_tag`）+ ns_api/jobs.py（画布任务，frame_jobs / video_jobs / edits / unified_frame 都经过它）。
- 正在跑的进程用的是旧代码，下次启动才带标签。gpu33 / gpu36 镜像目录里运行的脚本要把 `comfy_tag.py` 一起同步过去，否则退回同格式的普通 dict。

## 3. 不经 ComfyUI 的 GPU 任务：写心跳

```python
CT.heartbeat("VOICE10", "试听音色 · 林晚 候选3", kind="voice", server="gpu36", gpu=1, step=3, steps=10, ttl=120)
...
CT.heartbeat_done("VOICE10")
```

- 本机写 `data/gpu_heartbeats/<agent>-<pid>.json`；直接在 gpu36 上跑的任务写 `/root/work/fredw/gpu_heartbeats/*.json`（同字段，一行 JSON）。
- 字段：`agent, label, kind, server, gpu, step, steps, pct, eta_s, episode, shot, thumb, state, ttl, pid, started, updated`。
- 超过 `ttl` 秒没更新、或 `state: "done"`，面板当作已结束。
- 心跳出现在 GPU 面板对应的卡上（server + gpu 对得上；gpu 写 null 时放到同机上跑着该 agent 常驻进程的卡，如 REFLOCK 的 clip_srv.py）；对不上卡的列在面板底部“其他 GPU 任务”；同时进渲染任务中心（渲染中）。

## 4. 后端

| 接口 | 文件 | 说明 |
|---|---|---|
| `GET /api/gpu/live` | `services/api/ns_api/gpu_live.py` | 每张卡：谁在做什么、进度（ComfyUI 日志里的采样第 x/y 步；没有日志时按本道最近同类任务耗时中位数估）、已跑 / 预计还要、排队数 + 后面 3 个、利用率 / 显存 / 温度 / 功耗 / 功耗墙、gpu36 温控守护状态、最近一张出图、非 ComfyUI 进程（训练 / 其他用户）、心跳 |
| `GET /api/gpu/thumb` | 同上 | ComfyUI 出图的缩略图（经本机隧道读 `/view`，服务端缩放、内存缓存 60 张） |
| `GET /api/render-tasks` | `services/api/ns_api/render_tasks.py` | 渲染任务中心：ns_api 任务 + 各道 ComfyUI 队列 / 最近历史 + 心跳 + 写作 P3/P4 + 计划中（缺首帧 / 尾帧 / 视频、首帧因剧本已改过期） |

采集（全部只读）：
- ComfyUI：每条道 `/queue` 每 4 秒、`/history?max_items=20` 每 30 秒（道表来自 `config/render_endpoints.json`：gpu33 18188/18189/18191 → :8188/:8189/:8191；gpu36 18288/18289/18290 → :8188/:8189/:8190，已核对远端端口所在的卡号一致）。
- nvidia-smi：每台机器一条常驻 ssh（BatchMode），远端 bash 循环每 5 秒打一段快照：`nvidia-smi --query-gpu=…`、`--query-compute-apps`、进程表、ComfyUI 日志末尾的采样进度、`/var/lib/gpu36-dimm-guard/state`（只读）、远端心跳目录；远端循环最多 30 分钟，断了本机 10 秒后重连。**不执行 `nvidia-smi -pl` 或任何改状态的命令。**
- 采集线程在第一次请求时启动，2 分钟没人看就停（ssh 一起关）。接口只读缓存，不在请求里连远端。
- gpu36 温控守护（`/usr/local/sbin/gpu36-dimm-guard.sh`）：内存温度 ≥70 ℃ 把 GPU 功耗墙压到 200 W，≥78 ℃ 压到 100 W；面板在 gpu36 组头和每张卡上标“温控守护限功耗 200 W（默认 350 W）”。
- nvidia-smi 解析与 `tools/monitor/server.py`（:8810）共用 `services/agent/ns_agent/gpu_smi.py`。

渲染任务分桶（每行只在一个桶）：`all = pending + rendering + failed + done`。
- 失败后同镜同类已有成品或后面有一次成功 → 归 done，标“失败后已重试成功”，`error.resolved_by` 指向成功那次。
- 已取消的画布任务不算渲染任务（`sources.cancelled_jobs_excluded` 记条数）。
- 剧本 / 分镜只列进行中 / 等待 / 要返修。

## 5. 前端

- `apps/web/src/components/RenderTasks.helpers.ts`（数据钩子与筛选 / 计数 / 时间格式，PW-019 起从组件文件拆出，改这些函数改这里）+ `apps/web/src/components/RenderTasks.tsx`（只导出组件）：唯一的数据钩子 `useRenderTasks()`（全站一份轮询，4 秒 + `/api/events` 事件立即重取）+ 行组件 `TaskRow` + 列表 `TaskList` + 顶栏按钮 `RenderTasksButton`。顶栏抽屉和画布底栏“任务队列”用同一套。后端没有 `/api/render-tasks` 时退回 `/api/jobs`（只有画布任务）。
- `apps/web/src/components/GpuPanel.tsx`：抽屉里有 `/api/gpu/live` 时每张卡换成实时卡（LiveCard）；接口没有时照旧。渲染任务行里点卡名会打开这个面板（事件 `ns:gpu-open`）。
- 样式：`apps/web/src/components/rendertasks.css`（新文件，已登记 LOCKS，之后归 UIPIXEL）。

## 6. 核对

```
.venv/Scripts/python.exe tools/qa/render_tasks_parity.py            # P1 分桶、P2 各道队列 = 界面、P3 画布任务数 = /api/jobs
node apps/web/e2e/gpuview/shoot.mjs "/?theme=dark#ep01" after_gpu_1440_dark 9000 ".v3-gpu|wait:9000"   # 截图（只读查看令牌）
.venv/Scripts/python.exe apps/web/e2e/gpuview/alt_api.py 8801       # :8800 未重启时的只读小实例（只挂这三个接口）
```
