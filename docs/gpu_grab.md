# GPU 抢卡任务器 `tools/gpu_grab.py`（fredw-d9，2026-10-30）

项目方指示："显卡空闲你就抢"。本任务器只跑**资产/候选文生图**（角色候选、场景底板、单品等），
礼貌地使用空闲卡：笔记本是主力，gpu3 只在调度器允许、卡真正空闲时短时借用。

## 用法

```
uv run python tools/gpu_grab.py --status            # 各卡能不能抢（约 2 分钟采样）+ gpu3 may-use 结果
uv run python tools/gpu_grab.py --once              # 一轮：有空卡就领任务，跑完退出
uv run python tools/gpu_grab.py --watch             # 常驻，每 60 s 看一次（--poll 改间隔）
uv run python tools/gpu_grab.py --once --no-gpu3    # 只用笔记本（--no-laptop 只用 gpu3）
```

常驻启动（由人决定何时开；本任务没有常驻启动）：
`Start-Process -WindowStyle Hidden uv -ArgumentList 'run','python','tools/gpu_grab.py','--watch' -WorkingDirectory 'D:\NS-Final Studio'`
停止：结束该 python 进程即可（gpu3 锁最长 20 分钟后由调度器按 TTL 视为过期；下次启动会删掉自己的过期锁；
`data/jobs/running/` 里的文件下次启动自动放回队列，已完成的子任务不重跑）。

日志：`data/logs/gpu_grab.log`。

## 队列

- 放任务：`data/jobs/queue/*.json`，格式同 `data/jobs/gpu3_char_variety_20261030.json`
  （顶层元数据 + `"jobs": [...]`；也可以是单个任务对象）。按修改时间先来先跑。
- 子任务字段：`prompt`、`negative`、`seed`、`size`、`model`、`steps`、`cfg`、`lora`、`vae`、`refine`（可选，
  `{scale, steps, denoise}`，同 gen_assets 第二遍低重绘）、`file`、`out_dir`，其余字段原样写进 manifest。
  提示词/负面词**严格按原文**提交，不追加任何内容。
- 可选 `targets`（文件级或子任务级）：`["laptop", "gpu3:0", "gpu3:1", "gpu3:3"]` 的子集，默认全部。
  `gpu3:2` 会被拒绝（坏卡）。
- 流转：`queue/` → 领取时移到 `running/` → 结束移到 `done/`（全部成功）或 `failed/`（有子任务失败/被拒）。
  文件里追加 `_gpu_grab`：每个子任务的 `status`、`gpu`、`sha256`、`qc`、错误、超时次数；被拒文件写 `refused`。
  中途让卡（may-use 不再允许、锁被占、超时、ComfyUI 断开）→ 带着进度放回 `queue/`，下次接着跑。

## 拒绝的任务（直接进 failed/，从不出图）

- 成人：`adult` / `nsfw` / `explicit` / `adult_shot` 为 true，或 `rating` ∈ adult/nsfw/explicit/r18（文件级或子任务级）。
  成人镜头只在本地专用流程生成。提示词里出现 "adult man" 之类的词不算标记。
- 镜头首尾帧/视频：`kind` 为 frame/first_frame/last_frame/video/i2v/fl2v/h3/shot，或带 shot/shot_id/episode/frames/
  video/motion 字段，或 `out_dir` 在 renders/frames/run 下。`config/shot_ownership.json` 里 owner=gpu3 的项目
  （weita）原因写明"gpu3 渲染器负责"；其他项目同样拒绝（本任务器只做资产/候选）。永不出视频（笔记本绝不跑视频）。
- 缺字段、尺寸越界、`out_dir` 在项目外、`file` 不是纯 .png 文件名、targets 非法。

## 每张图

1. 第一遍文生图（ns_render.workflows.qwen_t2i），有 `refine` 时做第二遍低重绘（同 tools/gen_assets.refine_graph）。
2. 长边缩到 ≤1536（同 gen_assets）。
3. **QC v3 裸露质检硬失败**（ns_render.qc.nudity_qc：NudeNet + CLIP v2 + 同一台 ComfyUI 上的 Qwen3-VL 看图裁决）：
   命中 → 删图、子任务记 failed，不换种子重试。
4. 通过 → 写 `out_dir/file`，`out_dir/manifest.json` 按文件名替换/追加一条（任务字段 + sha256、qc、gen_seconds、
   gpu、runner、job_id、created_at）。`out_dir/file` 已在 manifest 且种子与提示词相同 → 跳过。

## 笔记本（RTX 4080 12 GB，ComfyUI :8188）

可抢 = ComfyUI 可达且队列空（running 和 pending 都为空）+ 没有这些进程（只看 python/uv/cmd/powershell 命令行）：
`render_batch`、`tools/gen_*.py`（含 gen_assets_v2）、`run_adult_batch`、训练（`train*.py`、`training/`、ai-toolkit、
kohya、musubi、train_network）。单任务上限 60 分钟。笔记本跑完不卸载模型（别的会话可能接着用）。

## gpu3（4×3090，GPU2 坏，永不使用）

端口 ↔ GPU（systemd `ns-comfy@<gpu>-<port>`，`deploy/gpu3/comfy-launch.sh %i`）：

| GPU | gpu3 端口 | 访问 |
|---|---|---|
| 0 | 8188 | `ssh -N -L <本地空闲端口>:127.0.0.1:8188 gpu33`（任务器自动开/关隧道） |
| 1 | 8189 | 同上 :8189 |
| 2 | — | 坏卡，无 ComfyUI，永不使用 |
| 3 | 8191 | 同上 :8191 |

状态目录 `/root/.local/state/NS-Studio/`（任务器只读，唯一的写操作是自己的 `gpu.lock.gpuN`）：

| 文件 | 含义 | 任务器怎么用 |
|---|---|---|
| `gpu.lock.gpuN` | 卡被占用：`pid:<pid> <名字>` 或无 pid 的 `<名字>`；死 pid = 过期；无 pid 锁按消费者 `lock_ttl_s` 过期 | 存在就不抢；自己的锁 = `fredw-d9 <job>`（无 pid，TTL 1200 s） |
| `train.lock.gpuN` / `train.lock.N` | 训练占用 | 存在就不抢 |
| `lend.gpuN` | 旧借卡约定，**只有调度器/持有人写** | 存在就不抢；**从不写** |
| `assign.gpuN.json` | 调度器 active 模式的分配 | 存在就不抢 |
| `scheduler_plan.json` / `scheduler_state.json` / `scheduler_plans.jsonl` / `scheduler_events.jsonl` | 调度器每 5 分钟一轮的计划、状态与事件 | 不直接读，由 `may-use` 判断 |
| `scheduler_mode` | dry-run / active | 不读 |
| `night_queue.token` | 演示 API 的夜间凭据（与卡无关） | 不读、不用 |

gpu3 调度器（docs/gpu_scheduler.md）为本任务器登记了消费者 `fredw-d9-assets`（S2，`short_jobs`，`gpus [1,3,0]`，
`match fredw-d9`，`lock_ttl_s 1200`，`legacy none`）。短任务的 `may-use` 规则：卡上没有活锁，最新计划没把卡给任何
非短任务消费者，也没有 S1 / 长 S2 消费者在 `next_at_boundary` 里等这张卡。

**每个 gpu3 子任务的流程**：

1. 本地预筛（每次 `--watch` 轮询都采样）：上表的锁/lend/assign 文件都不存在，并且 nvidia-smi 连续 ≥2 分钟
   显存 <1 GB、利用率 <5%。
2. `ssh gpu33 /root/claude-kimi-ns-studio-v1/env/comfy/bin/python …/ns-studio/scripts/ns_sched.py may-use fredw-d9-assets <gpu>`：
   退出码 0 才继续；非 0、ssh 失败、超时 = 不可用。
3. 用 O_EXCL（bash `set -C`）创建 `gpu.lock.gpuN`，内容 `fredw-d9 <队列文件名>:<file>`；train.lock/lend/assign 已存在或
   锁已存在 → 放弃。
4. 开 ssh 隧道 → 远端 ComfyUI 队列必须为空 → 出图 + QC（看图模型用同一台 gpu3 ComfyUI）。**单任务 ≤15 分钟**
   （含 refine），超时中断（ComfyUI /interrupt，只中断自己提交的任务）并放回队列；同一子任务超时 2 次 → failed。
5. 结束后 ComfyUI `/free` 卸载模型（卡回到 <1 GB），关隧道，**删锁**（只删内容与自己写的完全一致的锁）。
6. 下一个子任务从第 2 步重新开始（每个任务前都问 may-use，锁也每个任务单独加/放）。不允许 → 带进度放回队列。

从不：写 lend/assign、改调度器文件、杀或抢占 gpu3 进程、碰 GPU2、在 gpu3 跑超过 15 分钟的单任务。

卡挑选顺序：gpu3:1 → gpu3:3 → gpu3:0 → laptop（与调度器登记的偏好一致）。每张空卡各领一个队列文件，多卡并行。

注意：gpu3 上 ComfyUI 跑完别人的任务后若不卸载模型，显存会一直 >1 GB，按"<1 GB"规则这张卡不会被视为空闲
（宁可少抢）。所以 gpu3 空窗不多，笔记本是主力。

## 测试

`uv run pytest -q tests/test_gpu_grab.py`：校验（成人/镜头/weita 归属/GPU2/路径）、空闲窗口、锁文件阻挡、
笔记本进程识别、队列流转（done/failed/放回）、每任务 may-use + 加锁/放锁顺序、may-use 中途拒绝、抢锁失败、
超时放回再失败、执行器异常仍释放锁。全部用假的 gpu3/笔记本/出图，不连网。
