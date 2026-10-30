# gpu3 渲染桥（canvas bridge）与重渲队列契约

> 2026-10-30。分工（已和 fredw-d9 约定）：**界面、API、造型（looks）都归 `apps/web` + `services/api/ns_api`**，造型唯一来源是 `data/looks/`。
> 本服务 `services/canvas_api` 只做一座薄桥：
> 1. 把 gpu3 上的渲染产物（`renders_gpu3`）提供给画布，包括文件、缩略图、视频尾帧和 Range 播放；
> 2. 维护一个只追加的重渲队列 `rerender_queue.jsonl`，画布往里写请求，gpu3 系列渲染器消费，进度写回 `rerender_events.jsonl`；
> 3. 给新剧向导 / 进度看板（T42）提供每集进度、系列启停标记 `series_control.json`、GPU 占用（第 7 节）。
>
> 它不读也不写 `data/renders`、`data/looks`、`edits.json`、`review.json`。

## 1. 目录与文件

| 位置 | 内容 |
|---|---|
| gpu3 `/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/renders_gpu3/` | **唯一真源**：系列渲染器的产物，加上 `rerender_queue.jsonl`、`rerender_events.jsonl` |
| 笔记本 `D:\NS-Final Studio\data\renders_gpu3\` | 上面目录的只读镜像（成集后拷回）。镜像里的队列文件只用来查看，不要在笔记本上往里追加 |
| gpu3 `ns-studio/data/run/weita/` | 系列渲染器工作目录（`STATUS.log`、`HARD_SHOTS.jsonl`、`BLOCKED.jsonl`、`WORKER_ERRORS.jsonl`、`epXX/clips`、`epXX/assembly`），桥只读，也作对照来源（标签 `weita`） |
| gpu3 `renders_gpu3/<slug>/` | **新项目**（slug ≠ `weita`）：产物 `<slug>/epXX/SN/…`（同下面的布局），渲染器状态文件也放这里 |
| 笔记本 `D:\NS-Final Studio\data\renders_gpu3\<slug>\` | 新剧产物的笔记本镜像（只读），与 gpu3 `renders_gpu3/<slug>/` 一一对应 |
| 笔记本 `projects/<slug>/`（gpu3：`nsfs_canvas/app/projects/<slug>/`，同相对路径） | 新剧向导的项目目录。剧本导入 JSON 在 `projects/<slug>/data/import/script_v2.json`，桥优先读它，没有再回退 `renders_gpu3/<slug>/script.json` |

项目 slug：`weita` = 《为他而骚》，映射到 `renders_gpu3` 根和上面的工作目录，**现有路径不动**；其他 slug 一律在 `renders_gpu3/<slug>/` 下。Take.file 仍相对 `data/`，例如 `renders_gpu3/newdrama/ep01/S1/takes/image_001.png`。

`renders_gpu3` 的布局与 `ns_render.pipeline` 的 take 布局一致，方便 ns_api 直接复用 `load_takes` 那一套：

```
renders_gpu3/epXX/SN/
  takes.json                 {"takes":[Take…], "active":{"image":n, "video":n}}   Take 见 ns_schema.edits.Take
  takes/image_003.png  takes/video_002.mp4  takes/video_002_last.png
  frame.png / video.mp4 / last.png       当前选用版本的副本
  compiled.json / status.json / errors.json   可选
```

- `Take.file`、`Take.last_frame` 都是**相对 `data/` 的路径**，例如 `renders_gpu3/ep01/S1/takes/image_003.png`。
- 在 Take 原有字段之外，渲染器可以多写几项，桥会原样透出：
  - `request_id`：由哪条请求产生；
  - `input_hash`：请求里带的哈希；
  - `qc`：`{"face":{"verdict":"pass","score":0.93,"reasons":[]}, "text":"fail", "drift":…, "decoration":…}`；
  - `last_target`：首尾帧模式下的目标尾帧路径。
- 兼容旧布局：没有 `takes.json` 时，`frame.png` 和 `video.mp4` 算作第 1 版，种子和耗时取自 `status.json` 的 `image` / `video`。

## 2. 重渲队列契约（`nsfs_canvas.rerender/v1`）

`rerender_queue.jsonl` 每行是一条请求，**只追加，从不改写**。取消也是追加一行，写 `op:"cancel"`。

```json
{"schema":"nsfs_canvas.rerender/v1","id":"3f9c0a1b2c4d","op":"render","shot":"ep01-S3",
 "stage":"video","keep_seed":true,"seed":238181613431232,
 "edit":{"camera":"camera push in 缓慢推近","expression":"咬唇","video_prompt":null,"last_frame":"next","note":""},
 "compiled":{"image_prompt":"…","image_negative":"…","video_prompt":"…","video_negative":"…",
             "image_loras":[["wardrobe_heels_v1.safetensors",0.8]],"references":["refs/REF-LW-01.face.png"]},
 "input_hash":"9a1c…","overrides":{"frames":243,"route":"fl2va_int8"},
 "priority":5,"batch":"b7e2","requested_by":"owner","note":"鞋要透明","at":"2026-10-30T05:12:00Z"}
```

| 字段 | 含义 |
|---|---|
| `project` | 项目 slug，默认 `weita`。所有项目共用这一个队列文件 |
| `shot` | `epXX-SN`，桥会规范成两位集号 |
| `stage` | `image`：重画首帧（视频不动）<br>`video`：只重生成视频，保留当前首帧<br>`both`：先首帧，再用新首帧出视频 |
| `keep_seed` / `seed` | 保留种子时，ns_api 填入当前选用 take 的种子<br>`seed` 为空且 `keep_seed=false` 时，由渲染器自取新种子 |
| `edit` | 画布那一刻的 `ShotEdit` 快照（`ns_schema.edits`）。渲染器应以它为准，不要再去读笔记本上的 `edits.json` |
| `compiled` | 可选。ns_api 已套用造型（`data/looks`）后的最终提示词、LoRA 和参考图<br>有就**原样使用**；没有就由渲染器自己用 `compile_shot` + `apply_edit` 编译 |
| `input_hash` | 可选。ns_api 对「提示词 + 造型 + 参考图」算的哈希，渲染器原样写回新 take，ns_api 用它判断「已过期」 |
| `overrides` | 可选的渲染参数，例如 `frames`（须在 17k+5 网格上）、`steps`、`route`（`fl2va_int8` / `fl2va_turbo` / `eros10` / `ref2va`）、`width` / `height` |
| `priority` | 0 最高，默认 5 |
| `batch` | 同一次批量操作的请求共用一个 id |
| `op:"cancel"` + `target_id` | 取消一条还在排队的请求。已经开始的请求不能取消 |

**渲染器的职责**：
1. 记住已读到的行号，按 `priority`、再按 `at` 取下一条请求，跳过已被取消的。
2. 被锁定的镜头由画布负责不发请求，渲染器不用判断。
3. 产物按第 1 节的布局写成新 take（`n` 递增），把它设为 active，并更新 `frame.png` / `video.mp4` / `last.png` 副本。
   - 视频的尾帧用 ffmpeg 抽出，存为 `video_NNN_last.png`。
4. 每到一个阶段，往 `rerender_events.jsonl` 追加一行进度：

```json
{"schema":"nsfs_canvas.render_event/v1","id":"3f9c0a1b2c4d","state":"started","worker":"gpu0","at":"…"}
{"schema":"nsfs_canvas.render_event/v1","id":"3f9c0a1b2c4d","state":"image_done","take":{"stage":"image","n":4},"at":"…"}
{"schema":"nsfs_canvas.render_event/v1","id":"3f9c0a1b2c4d","state":"done","take":{"stage":"video","n":3},"at":"…"}
{"schema":"nsfs_canvas.render_event/v1","id":"…","state":"failed","error":"CUDA OOM at 243f","at":"…"}
```

`state` 的取值：`started`、`image_done`、`video_done`、`done`、`failed`、`skipped`。也可以不写文件，改用 `POST /api/gpu3/queue/events`。

失败只做技术层面的重试（换种子、降帧数），**不改写提示词**，这和 `render_batch.py` 的约定相同。

## 3. 接口（全部在 `/api/gpu3/` 下，便于并进 ns_api 或反向代理）

| 方法 | 路径 | 作用 |
|---|---|---|
| GET | `/api/gpu3/health` | 队列文件路径、各来源目录是否存在 |
| GET | `/api/gpu3/projects/{slug}/episodes` | 每集进度（第 7 节） |
| GET / POST | `/api/gpu3/projects/{slug}/series` | 读 / 写系列启停标记 `series_control.json`（第 7 节） |
| GET | `/api/gpu3/gpus` | 每张卡的占用（第 7 节） |
| GET | `/api/gpu3/scheduler` | T46 阶段调度器的完整计划，只读（第 7.3 节、`docs/gpu_scheduler.md`） |
| GET | `/api/gpu3/episodes/{ep}` | 该集每镜的 `ShotRenders`（镜号取自剧本 JSON） |
| GET | `/api/gpu3/shots/{epXX-SN}` | 一镜的所有 take（各来源），以及 active、error、状态（`none`、`queued`、`rendering`、`done`、`failed`）和最近 10 条请求 |
| GET | `/api/gpu3/shots/{id}/takes/{source}/video/{n}/last.png[?w=360]` | 视频尾帧：有文件就直接返回，没有就用 ffmpeg 抽一帧并缓存。带 `w` 时返回 JPEG 缩略图 |
| GET | `/api/gpu3/media/{source}/{path}` | 原文件，支持 Range（视频可拖动） |
| GET | `/api/gpu3/thumb/{source}/{path}?w=360` | JPEG 缩略图（ffmpeg 生成，有缓存） |
| POST | `/api/gpu3/rerender` | 请求体是一条或一个数组的 `RerenderRequest`（`id`、`at` 可以省略）。返回 `{requests, errors}`，逐条处理，镜头不存在的那条报错，不影响其他 |
| POST | `/api/gpu3/queue/{id}/cancel` | 取消排队中的请求；已经开始的返回 422 |
| GET | `/api/gpu3/queue?shot=&state=&limit=` | 请求列表，含合并事件后的状态和产出的 take |
| POST | `/api/gpu3/queue/events` | 渲染器回写进度（`RenderEvent`） |

`episodes/{ep}`、`shots/{id}`、`…/last.png` 都接受 `?project=<slug>`，默认 `weita`。

`ShotRenders.takes[]` 的字段：`source`、`stage`、`n`、`active`、`file`、`url`、`thumb`、`last_frame_url`、`last_target_url`、`seed`、`prompt`、`seconds`、`frames`、`created_at`、`workflow`、`request_id`、`input_hash`、`qc[]`。

Pydantic 模型在 `services/canvas_api/ns_canvas/models.py`，契约测试在 `services/canvas_api/tests/`（`test_contract.py` 6 项 + `test_progress.py` 4 项，gpu3 上全部通过）。

## 4. 部署（gpu3）与访问

- 代码：`/root/claude-kimi-ns-studio-v1/nsfs_canvas/app/services/canvas_api`（这个目录的拷贝）。
- venv：`nsfs_canvas/.venv`，Python 3.12。依赖有 fastapi、uvicorn、pydantic，测试另需 pytest、httpx。
- systemd 单元：`nsfs-canvas-bridge.service`，绑定 `127.0.0.1:5180`。单元文件和环境变量文件在 `services/canvas_api/deploy/`。
  - 更新代码后执行 `systemctl restart nsfs-canvas-bridge`。
- 从笔记本访问：先建隧道 `ssh -N -L 15180:127.0.0.1:5180 gpu33`，再打开 `http://127.0.0.1:15180/api/gpu3/health`。
  - ns_api 可以把 `/api/gpu3/*` 反向代理到 `http://127.0.0.1:15180`，也可以直接把 `ns_canvas.app.create_app` 的路由并进去，在笔记本上读 `data/renders_gpu3` 镜像。
  - 笔记本上配置 `NSC_ROOTS=renders_gpu3|takes|D:\NS-Final Studio\data\renders_gpu3` 即可，不需要设 `NSC_QUEUE_DIR`；队列写入仍然要发到 gpu3 那一份。
- 跑测试：`cd services/canvas_api && NSC_FFMPEG=/root/claude-kimi-ns-studio-v1/tools/ffmpeg/bin/ffmpeg ../../../.venv/bin/python -m pytest -q`。

## 5. 平台调研要点（简版；完整调研见 `canvas_research.md` 和 `canvas-ui-spec.md`）

- **先审静帧，再出视频**：小云雀「智能预演」、即梦样片模式、LTX「出图前改分镜免费」。对应到这里就是 `stage=image` 和 `stage=video` 分开排队。
- **单镜部分重生成**：LTX Retake、即梦单镜重做、小云雀片段抽卡。对应 `stage` 和 `keep_seed`。
- **生成结果作为新版本，不覆盖旧的**：LibTV 节点衍生、Boords 版本。对应 take 递增、active 切换，以及只追加的队列和事件。
- **改资产后先出影响面，再选择性重渲**：小云雀「一键同步」改进版。对应 ns_api 的 `input_hash` 判断过期，再批量 `POST /rerender`。
- **首尾帧衔接**：小云雀截取首帧和尾帧、Flora 抽取视频尾帧。对应 `last_frame_url`（ffmpeg 现抽）和 `last_target_url`。

来源：[小云雀短剧 Agent 报道](https://news.qq.com/rain/a/20260529A02Z3W00) · [科技日报](https://www.stdaily.com/web/gdxw/2026-03/20/content_488925.html) · [LTX 角色一致性](https://ltx.studio/blog/how-to-create-a-consistent-character) · [LTX Storyboard 更新](https://ltx.studio/blog/ltx-storyboard-generator-update) · [Kling 3.0 用户指南](https://kling.ai/quickstart/klingai-video-3-model-user-guide) · [Kling Director Mode](https://kling.ai/blog/kling-video-3-director-mode-multi-shot-tutorial) · [Krea 节点工具综述](https://www.krea.ai/blog/top-node-based-ai-workflow-apps) · [即梦样片模式实测](https://www.woshipm.com/ai/6471440.html)

## 6. 依赖对方代码的地方

- `ns_schema.edits.Take` / `ShotEdit`：take 字段和 `edit` 快照的结构都以它为准。它改了，这份契约跟着改。
- `ns_render.pipeline` 的 take 目录布局，以及「`file` 相对 `data/`」这条约定。
- `data/import/script_v2.json`（`tools/import_script.py` 的产物）：只用来列出每集有哪些镜号。gpu3 上用的是笔记本那份的拷贝：`nsfs_mirror/data/import/script_v2.json`（由 `ops/sync/pull_laptop.sh` 原子推送，桥的 `NSC_SCRIPT_JSON` 指向它；封板修复）。

- gpu3 `ns-studio/scripts/weita_series.py` 的文件约定：
  - `STATUS.log` 行格式 `[epXX] ✅|⚠️|⛔ …`；
  - `HARD_SHOTS.jsonl` / `BLOCKED.jsonl` / `WORKER_ERRORS.jsonl` 的 `shot` / `item` 字段；
  - `epXX/clips/epXXsN.mp4`、`epXX/assembly/voiceover.json`、`epXX_final.mp4`。
- `upscale_4k.py` 的 QA 门槛（`QA_PASS` / `QA_HOLD` / `QA_FAIL`）与 `epXX_4k.mp4` / `epXX_4k.manifest.json`。
- T38 后期约定（fredw-d9）：`data/music/epXX.wav` + `.json`、`SN/audio/stems.json`、`data/episodes/epXX.mp4`（+`_4k`）。
- `golden/bench.csv` 的列：`shot`、`kind`、`gpu_seconds`、`ok`。

## 7. 项目进度、系列控制、GPU（T42 新剧向导 / 进度看板）

### 7.1 `GET /api/gpu3/projects/{slug}/episodes`

只读推导，不改任何文件。返回：

```json
{"project":"weita","control":null,
 "eta":{"total_s":950444,"gpu_seconds":950444,"active_gpus":1,
        "per_shot":{"frame":{"seconds_per_shot":554.2,"samples":8,"source":".../golden/bench.csv"},
                    "video":{"seconds_per_shot":2133.8,"samples":6,"source":".../golden/bench.csv"}},
        "formula":"(未出首帧镜数×每镜首帧GPU秒 + 未出视频镜数×每镜视频GPU秒) ÷ 正在出片的GPU数；已有成片的集为0"},
 "episodes":[
  {"ep":1,"title":"旋转门","shots":6,"frames":{"done":6,"total":6},"videos":{"done":6,"total":6},
   "qa":{"state":"none","source":null,"issues":[]},
   "audio":{"voiceover":false,"voiceover_wavs":0,"music":null,"stems_shots":0,"music_cues":false},
   "upscale_4k":{"state":"none","file":null,"shots_4k":0},
   "final":{"exists":false,"file":null},"status_line":null,"hard_shots":5,"blocked":0,"eta_s":0,
   "errors":["HARD ep01-S1: VLM facing: {\"正面朝向镜头\": false}", "…"]},
  {"ep":2,"title":"深夜外套","shots":6,"frames":{"done":1,"total":6},"videos":{"done":0,"total":6},"eta_s":15574,"…":"…"}]}
```

| 字段 | 从哪里来 |
|---|---|
| `shots` | 剧本导入 JSON 的镜数。weita：`data/import/script_v2.json`（不变）<br>新项目：`projects/<slug>/data/import/script_v2.json`，回退 `renders_gpu3/<slug>/script.json`<br>都没有就数已有的 `SN` 目录 |
| `frames` / `videos` | 每镜：renders_gpu3 有 active 的 image / video take（或旧布局的 `frame.png` / `video.mp4`）；视频也认工作目录里的 `epXX/clips/epXXsN.mp4`。`S1.superseded_*` 这类目录不算 |
| `qa` | 优先级从高到低：<br>1. `qa.json`（建议标记，见 7.4）；<br>2. `QA_FAIL` / `QA_HOLD` / `QA_PASS` 标记，查 renders_gpu3/epXX 和工作目录/epXX，规则与 `upscale_4k.qa_gate` 相同，`QA_PASS` 里写的 sha256 和成片不符时为 `stale`；<br>3. `STATUS.log` 该集最后一行的旗标：✅→`auto_pass`，⚠️→`blocked_shots`，⛔ / ⏸→`paused`；<br>4. 都没有就是 `none` |
| `audio` | `voiceover`：工作目录 `epXX/assembly/voiceover.json`（gpu3 系列装配的 TTS）<br>`music`：`data/music/epXX.wav`，`music_cues` 表示同名 `.json` 存在（T38 约定）<br>`stems_shots`：有 `SN/audio/stems.json` 的镜数 |
| `upscale_4k` | `epXX_4k.mp4`（renders_gpu3/epXX，或 `data/episodes/epXX_4k.mp4`），状态取 `epXX_4k.manifest.json` 的 `status`；`shots_4k` = 有 `takes/video_*_4k.mp4` 的镜数，只有单镜 4K 时为 `partial` |
| `final` | `epXX_final.mp4`（renders_gpu3/epXX 或工作目录/epXX），或 T38 装配的 `data/episodes/epXX.mp4` |
| `errors` | `BLOCKED.jsonl`、`HARD_SHOTS.jsonl`、`WORKER_ERRORS.jsonl`（该集最近 5 条）、各镜 `errors.json`、`epXX/FAILURE_REPORT.md` |
| `eta_s` | 见上面的 `formula`。每镜 GPU 秒 = `golden/bench.csv` 里成功的尝试按镜头求和（含重试和候选）再取平均；没有数据时用 60 s / 1600 s 兜底<br>「正在出片的 GPU」= `gpu.lock.*` 内容含 `owner_script_render` / `series`、不含 llm / train / lora 的卡数，至少 1 |

### 7.2 `POST /api/gpu3/projects/{slug}/series`

请求体 `{"action":"start|pause|stop","episodes":[2,3]|null,"adult_content":false,"by":"fredw-d9","note":""}`。`adult_content` 默认 `true`（2026-10-30 取消成人过滤器后只作记录），只接受 JSON 布尔值，`"yes"`、`1`、`null` 都返回 422。返回写下的记录和 `written` 路径。`GET` 同一路径读当前标记。

写入的文件 `series_control.json`（`nsfs_canvas.series_control/v1`）：

```json
{"schema":"nsfs_canvas.series_control/v1","project":"weita","action":"pause","episodes":[2,3],
 "adult_content":false,"by":"fredw-d9","note":"","at":"2026-10-30T06:10:00Z"}
```

- weita 同时写到 `renders_gpu3/weita/series_control.json` 和 `renders_gpu3/series_control.json`（根），内容相同；新项目写到 `renders_gpu3/<slug>/series_control.json`。
- 每次写入另外追加一行到同目录的 `series_control.log.jsonl`，留历史。
- `episodes:null` 表示整部剧。
- 离线时手工放一份同样的 JSON 也有效。
- **渲染器的职责**：每集开始前、每镜之间读一次。
  - `pause`：做完手上这一镜后停下，等到 `start` 再继续。
  - `stop`：做完手上这一镜后退出，与现有 `STOP` 文件同义。
  - `start` + `episodes`：只跑这些集。
  - `adult_content`：2026-10-30 起只记录，不再跳过成人镜头（旧版 `false` 会记为 blocked）。
  - 桥只写标记，不碰任何进程。

### 7.3 `GET /api/gpu3/gpus`

```json
[{"id":0,"name":"NVIDIA GeForce RTX 3090","faulty":false,"busy_by":"weita-v3-llm",
  "task":"pid:454302 weita-v3-llm (v3 script LLM, lend.gpu0)","vram_used_mb":20255,"vram_total_mb":24576,"util":85,
  "lock_file":{"file":"/root/.local/state/NS-Studio/gpu.lock.gpu0","pid":454302,"pid_alive":true,"owner":"weita-v3-llm","text":"…"},
  "train_lock":null,"lend_file":{"file":".../lend.gpu0","owner":"weita-v3-llm","text":"…"},
  "comfy":{"url":"http://127.0.0.1:8188","running":0,"pending":0},
  "processes":[{"pid":454302,"name":"llama-server","vram_mb":19638}]},
 {"id":2,"faulty":true,"note":"faulty — never used（显存 >11 GB 静默算错，见 /root/README-GPU2-FAULTY.txt）","busy_by":null,"…":"…"}]
```

数据来源：
- `nvidia-smi`：显存、利用率、进程；
- `/root/.local/state/NS-Studio/` 下的锁文件：`gpu.lock.gpuN`、`train.lock.gpuN`（或 `.N`）、`lend.gpuN`；
- 每个 ComfyUI 实例的 `/queue`：gpu0→8188，gpu1→8189，gpu3→8191。

`busy_by` 的取值顺序：锁文件的持有者 → ComfyUI 有正在运行的任务时为 `comfyui` → nvidia-smi 里的第一个进程 → `null`。GPU 2 永远标 `faulty`。

每张卡还有 `scheduler` 字段：T46 阶段调度器对这张卡的计划。取值为 `{"mode":"dry-run|active","at":…,"assign":<assign.gpuN.json 或 null>,"planned":"weita-v3","stage":"S1","locked":true,"why":"…","next":["lw-img-lora","pose-lora","lw-lora"]}`；调度器还没出过计划时为 `null`。完整计划用 `GET /api/gpu3/scheduler` 读（只读，内容就是 `scheduler_plan.json`）。契约和优先级说明见 `docs/gpu_scheduler.md`。

### 7.4 建议给系列渲染器的标记：`renders_gpu3/[<slug>/]epXX/qa.json`

`docs/qa_issues.md` 是写给人看的文字，进度看板需要一个机器可读的逐集结论。建议渲染器或 QA agent 写成：

```json
{"verdict":"pass|hold|fail","final_sha256":"…","issues":["S3 鞋不对"],"by":"qa-agent","at":"2026-10-30T06:00:00Z"}
```

它的优先级高于 `QA_*` 标记和 STATUS.log。现有的 `QA_PASS` / `QA_HOLD` / `QA_FAIL`（`upscale_4k` 门槛）照常有效。这个文件名和字段还要经协调人和系列渲染器 agent 确认。

### 7.5 新剧路径与 G3 回交约定

- 新剧在 gpu3 的产物：`renders_gpu3/<slug>/epXX/SN/…`；笔记本镜像：`data/renders_gpu3/<slug>/`（只读）。
- 新剧剧本导入：`projects/<slug>/data/import/script_v2.json`，gpu3 镜像在 nsfs_canvas checkout 内的同一相对路径。
- **G3 回交**：gpu3 改写好的新剧 v3 剧本交到 `projects/<slug>/script/*v3*.md`，可附 `*v3_changes.md` 说明改动。项目方在向导里审阅后重新导入。

### 7.6 逐镜 H3 / 审计（画布“出视频”闸门）

| 方法 | 路径 | 请求体 | 作用 |
|---|---|---|---|
| GET | `/api/gpu3/projects/{slug}/episodes/{ep}` | — | `{project, ep, audit_summary, shots:[ShotRenders…]}`<br>`audit_summary` = `{pass, fail, blocked, none, top_failures:[{rule_id,count}]×3}`，只统计有目录的镜 |
| GET | `/api/gpu3/projects/{slug}/shots/{epXX-SN}` | — | 一镜的 `ShotRenders`（同 `/shots/{id}?project=`） |
| POST | `/api/gpu3/projects/{slug}/shots/{id}/h3_edit` | `{"text":"…","by":"owner","base_sha":"<effective_sha256>"}` | 写 `edits.json.h3_prompt_override`，返回 lint 结果。**不渲染** |
| GET | `/api/gpu3/rules` | — | 解析 `docs/audit/rule_ids.md` 全表 → `{rules_sha, version, count, rules:[{rule_id, rule, check, level, sop_ref, section, retired}]}` |
| GET | `/api/gpu3/rules/{rule_id}` | — | gpu3 `ns-studio/scripts/shot_audit.py --explain <id> --json` 的输出，原样透出（`found, rule_id, rule, check, level, sop_ref, sop_lines[{line,text}], example_pass, example_fail, implementation, heuristic, rules_version`），另加 `rules_sha`、`retired`、`cached`<br>按「rule_id + 规则表 sha256」缓存；规则表一改，缓存自动失效<br>不在规则表里或不合法 → 404（不起子进程）；脚本说 `found:false` → 404；超时（`NSC_EXPLAIN_TIMEOUT`，默认 15 s）→ 504；输出不是 JSON → 502；脚本不可用 → 503 |
| POST | `/api/gpu3/projects/{slug}/shots/{id}/override` | `{"rule_id":"H3-A5","owner_quote":"项目方原话","by":"owner"}` | 往 `edits.json.audit_override_requests` 追加一条豁免请求。**不写 status.json** |

`ShotRenders` 新增的字段，都读自 `renders_gpu3/epXX/SN/`：

- `audit`：`status.json.audit` 的 `version`、`verdict`、`failures[]`、`warnings[]`、`not_checked`、`overrides[]`、`invalid_overrides[]`、`h3_edit`、`prompt_sha`，原样透出。另加 `override_requests[]`，来自 `edits.json`。没有审计数据时为 `null`。
- `h3`：`compiled.json` 的 `h3_prompt`、`h3_prompt_sha256`、`h3_prompt_source`、`h3_prompt_base_sha256`。另加：
  - `override`：`edits.json.h3_prompt_override` = `{text, sha256, by, at, base_sha}`；
  - `effective_sha256`：有 override 用 override 的 sha，否则用 `h3_prompt_sha256`。
- `shot_state`：`status.json` 的 `state`、`blocked`（如 `explicit_content_not_supported`）、`owner`、`scene_id`、`segment_id`、`continuity`、`bible_version`。
- `active_video`：active 视频 take 的 `n`、`prompt`、`prompt_sha256`（take 没写时由桥现算）、`reference`、`references`、`last_target`、`frames`。
- `video_gate` = `{verdict, prompt_sha, effective_sha256, blocked, video_ok}`。
  - `video_ok` 为真需要同时满足：`verdict == "pass"`，`prompt_sha == effective_sha256`，并且没有 `blocked`。
  - 画布据此决定“出视频”按钮能不能点；桥本身不拦截任何东西。

规则：

- **h3_edit**
  - `by` 必须是 `"owner"`，否则返回 403；`text` 为空返回 422。
  - `base_sha` 应填改之前看到的 `effective_sha256`；不一致返回 409，防止覆盖别人刚改的版本。
  - 写入用原子替换；每次修改另外追加一行到 `edits_history.jsonl`。
  - lint 来自同步过去的仓库 `ns_schema/h3_lint.py`（gpu3：`nsfs_mirror/packages/schema/ns_schema/h3_lint.py`），用 `lint_h3(text, frames, intimate)` 调用：
    - `frames` 依次取 `status.video.frames`、`compiled.frames`、视频 take 的 `frames`；
    - `intimate` 取 `compiled.adult`；
    - 已生效的 `audit.overrides` 计入豁免。
  - 返回 `lint = {ok, failed[], warnings[], frames, intimate, results[], lint_file}`。
  - 改完后由 gpu3 的 `shot_audit` 重新审计，得出新的 `verdict` 和 `prompt_sha`。
- **override**
  - `rule_id` 必须在 `docs/audit/rule_ids.md` 表格的第一列里，并且没有标“作废”。gpu3 的 `nsfs_mirror` 里没有这份表时，用桥 checkout 里随部署带过去的副本。
  - `owner_quote` 去掉首尾空格后不能为空；`by` 必须是 `"owner"`（否则 403）。
  - 写入格式：`{rule_id, owner_quote, by:"owner", at}`，同时追加到 `edits_history.jsonl`。
  - 由 gpu3 的 `shot_audit` 把请求合并进 `status.json.audit.overrides`；无效的请求进 `invalid_overrides`。

## 8. 归档

此前做过一版更完整的原型，已按分工从仓库移出，归档在 gpu3：`/root/claude-kimi-ns-studio-v1/nsfs_canvas/prototype/canvas_prototype_20261030.tgz`。只作参考，不部署。内容包括：
- 版本化 `shot.json`；
- 造型排期与 `@资产` 展开；
- 看板 / 甘特排期的 React 组件，未完成。
