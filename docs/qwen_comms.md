# Claude ↔ Docker Qwen 通讯规则（2026-10-30，项目方定，fredw-d9 维护）

> 项目方原话：“你整理好通讯，claude 和 docker 的 qwen 通讯建立好，docker qwen 负责写剧本，镜头提示词，训练 lora，blender 训练，以及部分爬虫任务”；“结果返回给你是剧本细节，claude 的画布短剧生产流直接启动 minimax 执行”；“image 模型也是通过 docker 来建立起来，需要的时候调度 image docker 来生成首尾帧图片”。
> 分工硬规则见 `docs/REQUIREMENTS.md` G1–G6：**内容全部归 Qwen，Claude 只写系统、只做收发，不参与也不审核内容。**

## 1. 角色

| 方 | 负责 | 不做 |
|---|---|---|
| **Docker Qwen**（gpu3 容器 `qwen-agent`，Qwen Code 智能体） | 剧本、分镜/镜头、画面与视频提示词、训练标注、LoRA 训练与评测、Blender 场景与渲染、爬虫任务、一切内容上的选择 | — |
| **Claude 系统**（画布 = fredw-92；gpu3 基础设施 = fredw-d9） | 发任务、取结果、把 Qwen 的剧本原样导入画布、调度出图与出视频（MiniMax H3）、GPU 分卡与锁、格式校验 | 不写、不改、不润色、不评价、不审核内容 |
| **项目方** | 各确认关口拍板 | — |

## 2. 服务与 GPU（gpu3）

| 服务 | 卡 | 地址 | 说明 |
|---|---|---|---|
| Qwen 写作模型（Docker `qwen-llm`） | **GPU1 常驻** | 宿主机 127.0.0.1:8098（容器经 docker0 172.17.0.1:8098） | OpenAI 兼容 `/v1/chat/completions`，带视觉。GPU1 被占用期间暂在 GPU3（宿主机进程），unit `qwen-migrate-gpu1` 自动切换，端口不变 |
| Qwen 智能体（Docker `qwen-agent`） | **GPU3**（切换完成前在 GPU1） | 只通过信箱访问 | Blender 5.2.3、ai-toolkit、底模只读；工作区 `/root/qwen-agent/work` |
| 信箱接口 `qwen-mailbox` | — | 宿主机 127.0.0.1:8099 | 见 §3 |
| Image Docker（首尾帧出图） | 按需调度到 **GPU0 / GPU3**（LoRA 卡空闲时） | 规划中 | 见 §6 |

GPU0 + GPU3 = LoRA 训练（项目方：“gpu1 一直挂着 qwen，lora 去找 gpu0、gpu3”）；GPU2 坏卡永不用。

## 3. 信箱接口（127.0.0.1:8099；笔记本 `ssh -N -L 18099:127.0.0.1:8099 gpu33`）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/tasks` | body `{"from": "<发起方>", "text": "<任务原文>", "meta": {"kind": "<类型>", ...}}` → `201 {"id": "..."}` |
| GET | `/tasks/<id>` | 任务 + `status`（queued / running / done / failed）+ `result.output`（Qwen 最后的回复，原样） |
| GET | `/tasks?since=<iso>` | 任务列表（id / from / created_at / status） |
| GET | `/files/<id>/` | 交付物清单（`/work/export/<id>/` 下的文件） |
| GET | `/files/<id>/<路径>` | 交付物原样字节 |
| GET | `/health` | 排队数、运行数 |

- 任务一次一个、按到达顺序执行；中断后自动放回队列重跑。
- 调度程序只在原文前加一行 `[系统] 信箱任务 <id>…`（编号、交付目录、类型），**原文一字不改**。
- `meta.kind` 约定：`script`（剧本/镜头/提示词）、`lora`、`blender`、`crawl`、`image_request`、`other`。`meta` 里其他字段原样带回，供发起方对账（如 `project`、`episode`、`shot`）。

## 4. 交付格式（Qwen → Claude 系统）

每个任务在 `/work/export/<id>/` 下：
- `result.json`：`{"task_id", "kind", "status": "done|failed", "files": [...], "summary"}`。
- **剧本交付格式**（`kind: script`）：`script.md`，与 `script play lib/` 里的现有剧本**同一格式**（逐集、逐镜 `**img**` / `**motion**` / `**sound**` / `**时长**` / 台词等，H3 字段按 SOP §6「H3 上游写法」）。Claude 系统用 `tools/import_script.py` 原样导入成 `projects/<slug>/data/import/script_v2.json`，不改任何文字。
- LoRA：`<名字>.safetensors` + `README.md`（触发词、底模、步数、数据集来源）。
- 图片 / Blender 渲染：PNG，文件名自定，在 `result.json.files` 里列出。

## 5. 生产流（剧本 → 视频）

1. 画布（或项目方）发 `kind: script` 任务 → Qwen 写剧本 → `script.md`。
2. Claude 系统取回 → `tools/import_script.py` 导入 → S1 闸门（格式校验：字段齐全、H3 格式）。**格式**不过 → 把校验器的报错原样作为新任务发回 Qwen 修改，Claude 不自己改。
3. S2：剧本用到的 LoRA 若缺 → 发 `kind: lora` 任务给 Qwen。
4. S3 首尾帧：画布调度 Image Docker（§6）按剧本提示词原样出图。
5. S4 视频：画布生产流直接启动 MiniMax H3 执行（SOP §9A）。
6. 内容层面的挑选、返工意见只来自 Qwen 或项目方。

## 6. Image Docker（首尾帧出图，2026-10-30 已搭好；GPU 实测待有卡空出）

- 容器 `ns-image`（镜像 `qwen-agent:1`）：只读挂载宿主机 ComfyUI 0.42 + Python 环境 + 模型（含 `qwen_image_2.1{,_turbo}_int8_convrot`），输入/输出/临时/用户目录独立可写：gpu3 `/root/qwen-agent/imagegen/{input,output,temp,user}`。ComfyUI 只发布到 gpu3 `127.0.0.1:8190`（笔记本 `ssh -N -L 18190:127.0.0.1:8190 gpu33`）。
- 控制脚本 gpu3 `/root/qwen-agent/agent/image_docker.sh`：
  - `up [gpu]`：在 GPU0/GPU3（`IMAGE_GPUS`）里找空闲卡——没有别人的 `train.lock.gpuN`、`gpu.lock.gpuN` 已释放、显存 < 1.5 GB——写 `train.lock.gpuN`（by `ns-image`）后起容器，就绪后打印地址；已在运行就直接打印。没有空闲卡退出码 **75**，并列出每张卡被谁占着（不抢、不杀、不改别人的锁）。
  - `down`：停容器、只删自己写的锁。`status`：JSON（running / gpu / url / idle_s）。
  - `reap`：队列空闲 ≥ 10 分钟（`IDLE_MIN`）就 `down`。由 systemd 定时器 `ns-image-reap.timer` 每分钟自动调用（项目方 2026-10-30 批准安装，开机自启）。
- 画布出图流程：`image_docker.sh up` → 往 :8190 提交 ComfyUI 工作流 → 从 `imagegen/output/` 取图。退出码 75 时排队稍后重试。
- 已验证（2026-10-30）：容器 CPU 模式 10 秒就绪、节点全部加载、只读挂载无报错；无空闲卡时 `up` 返回 75 且所有锁不变。待验证：有卡空出后在 GPU 上实际出一张 Qwen Image 2.1 首帧。
- 出图提示词原样来自剧本（编译器只做格式拼接，规则同 visual_bible）。
- **Qwen 出图队列 `qwen-image-api`**（gpu3 `127.0.0.1:8100`，容器内 `http://172.17.0.1:8100`；WORKFLOW.md S3：Qwen 自己调度 Image 2.1 Turbo）：`POST /jobs` 收 `prompt` / `negative_prompt` / `loras` / `refs`（≤3，/work 下）/ `width`×`height`（默认 768×1344）/ `seed` / `count`，或整份 ComfyUI `graph`；原样跑官方 Turbo 8 步模板。卡和容器一律交给 `image_docker.sh up`（75 = 排队，`waiting` 写明在等哪张卡），参考图拷进 `imagegen/input/<id>/`，结果移到 `/work/images/<id>/`（附尺寸、sha256）。`GET /jobs/<id>`、`GET /health`。用法写在 Qwen 的 `/work/QWEN.md`「出图」。代码 `agent/image_api.py`，日志 `/root/qwen-agent/image_api.log`；维护 fredw-5c。默认只用 GPU3（总调度 2026-10-30：GPU0 优先给 LoRA），任务可用 `gpus` 指定 0/3。
- **系统就绪看板**：`/work/SYSTEM_STATUS.{md,json}`（`agent/status/status_board.py` + 待办 `agent/status/todo.json`），列出写剧本 / LoRA / Blender / 首尾帧 / 视频各环节能否开工；环节转为就绪时给 Qwen 发 `from: system-status` 信箱通知。目前手动刷新，定时器 `qwen-status.timer` 待项目方批准。

## 7. 运维

- 代码与脚本：gpu3 `/root/qwen-agent/agent/`（`claim_gpu.sh`、`run_agent.sh`、`run_llm_docker.sh`、`dispatcher.py`、`mailbox_api.py`、`llm_relay.py`、`migrate_gpu1.sh`、`wait_gpu.sh`）。
- 日志：`/root/qwen-agent/{agent,qwen_llm,migrate,mailbox,relay}.log`；每个任务的 stderr 在 `work/mailbox/logs/<id>.log`。
- 卡的接手一律按任务边界、用锁文件，不杀任何进程。
