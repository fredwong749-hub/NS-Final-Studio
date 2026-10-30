# gpu3 体检（fredw-d9，2026-10-30 06:55 EDT；总调度 fredw-b3 要求）

只读检查结果。停用清单已由项目方批准并本人执行（07:06 EDT 核实，见 §2–4）；unit 文件全部保留，只 stop / disable。

## 1. GPU 分工（当前，项目方 G3）

| 卡 | 用途 | 锁 | 状态 |
|---|---|---|---|
| GPU0 | Qwen 智能体容器 LoRA 卡 2（cuda:1）→ 林晚 H3 视频 LoRA lnwan01 | `train.lock.gpu0` by qwen-agent | 空闲，等信箱任务 `f11c841c`（lnwan01 交接重提交） |
| GPU1 | Qwen 写作模型（Docker，`:8098`，2 槽 × 48k 上下文） | `train.lock.gpu1` by qwen-llm | 96% 在用，21 GB |
| GPU2 | 坏卡，永不用 | — | 0 MB（CPU 版 Qwen 已不再碰它） |
| GPU3 | Qwen 智能体容器 LoRA 卡 1（cuda:0）；**留给 ep01 渲染整卡**，服装 LoRA 排在 ep01 之后 | `train.lock.gpu3` by qwen-agent（ns-image 可借，见 qwen_comms.md §6） | 空闲 |

## 2. 服务（systemd）

| unit | 状态 | 用途 / 负责 | 结论 |
|---|---|---|---|
| `qwen-llm-gpu1` | 运行 | Qwen 写作模型 GPU1 | 保留 |
| `qwen-agent3` | 运行 | Qwen 智能体容器（GPU3+GPU0，信箱 2 并发） | 保留 |
| `qwen-mailbox` `qwen-llm-relay` | 运行 | 信箱 `:8099`、容器→LLM 转发 | 保留 |
| `qwen-image-api` + `ns-image-reap.timer` | 运行 | 出图队列 `:8100` → Image Docker `:8190`；空闲 10 分钟回收 | 保留（02:59、04:41 已在 GPU3 实际出图） |
| `weita-v3-llm-cpu` | 运行 | CPU 版 Qwen `:8097`（纯 CPU，48 线程，5.6 tok/s） | 保留 |
| `ns-comfy@0-8188` `@1-8189` `@3-8191` | 运行 | 每卡一个 ComfyUI（`--cache-none`） | 保留；GPU1 的 8189 空载约 0.4 GB |
| `nsfs-canvas-bridge` | 运行 | 画布桥 `127.0.0.1:5180` | 保留；ep01 S1/S2 首帧经隧道取到 200 |
| `nsaudio-watch` | 运行（06:52 重启） | 后期配乐/拟音 QA 闸门 | 保留（已打 BGM N/A 补丁） |
| `wardrobe-gen` `wardrobe-pipe-clothes` `wardrobe-pipe-heels` | **已停**（07:06 EDT 核实 inactive） | claude-gpu3 的服装/高跟 LoRA 出图与训练流水线（T15） | 项目方批准（“全部停掉”/“停掉旧的进程”），由项目方本人执行；LoRA 已归 Qwen |
| `lw-qi-lora` | **已 disable**（unit 文件保留） | 林晚出图 LoRA；`.done` 已补 | 同上 |
| `up4k-test` | **failed** | 4K 放大 A/B 测试（T19） | 查失败原因后再定；目前无人依赖 |
| `redis-server` | **failed** | 系统包，项目未使用 | 不动 |
| `vmtouch` | 运行 | 页缓存常驻 | 保留 |
| `ns-sched`（T46 调度器） | **不存在/未运行** | 状态文件停在 10-29 23:43（dry-run） | GPU 已按 G3 固定分配，调度器暂不需要；T46 待项目方定是否继续 |

## 3. 孤儿进程（不属于任何服务）

| pid | 已运行 | 内容 | 结论 |
|---|---|---|---|
| 35780 | 7.6 h | `/root/build_sage/bench2.py h3 1,3,0 baseline,sage h3a`（T50 SageAttention 基准），等一张完全无锁的卡 | **已停**（项目方执行，07:06 核实）；要测就另约时间整卡跑 |
| 37883 38143 42196 | 7.4 h | 3 个 `until grep CHAIN_DONE/released … bench_*.out` 等待循环 | **已停**（随 35780） |

## 4. 锁文件（`/root/.local/state/NS-Studio/`）

- `train.lock.gpu0/1/3`：见 §1，均有效。`gpu.lock.*`：无。
- `lend.gpu0`（pose-lora，死条目）已移走为 `.lend.gpu0.dead-pose-lora-20261030`；`lend.gpu3`（wardrobe）已由项目方改名为 `.lend.gpu3.removed-wardrobe-20261030`。现在没有任何 `lend.*`。
- `up4k-test` 失败、`ns-sched` 不运行：按总调度要求原样记录，暂不处理。
- `scheduler_*`：T46 dry-run 遗留，未被使用。

## 5. 磁盘与内存

- `/`（NVMe 1.8 T）用 32%（540 G），余 1.2 T。
- 内存 503 G：进程约 40 G，页缓存约 380 G。

## 6. 本次已修

1. Qwen 两个任务失败的根因：写作模型每槽 32k 上下文不够 → 改 2 槽 × 48k，Qwen Code `contextWindowSize=49152`（自动压缩）；失败任务已重提交。
2. `qwen-agent3` 起不来：旧 qwen-llm 留下的 `train.lock.gpu3` 过期锁 → 已改为 qwen-agent。
3. CPU 版 Qwen 误用 4 张卡（含坏卡 GPU2）→ 纯 CPU。
4. 解析器 T04 P1–P3（`weita_render.py.bak-t04-20261030`），三份剧本 0 差异。
5. 后期 BGM：剧本写 N/A/无配乐/静默 时不再生成，不再从旧 v3 草稿补（`audio_post.py.bak-bgm-20261030`）。
6. 笔记本隧道守护 `tools/gpu3_tunnels.py`（桥 15180 / 信箱 18099 / LLM 18098，断了自动重连；笔记本重启后需重新运行）。

## 7. 封板期遗留清单（fredw-d9，2026-10-30 07:30 EDT；封板起只修 bug）

| 项 | gpu3 位置 | 状态 | 还差什么 |
|---|---|---|---|
| **核心服务都是临时 unit，gpu3 重启后不会自动恢复** | qwen-llm-gpu1、qwen-agent3、qwen-mailbox、qwen-llm-relay、weita-v3-llm-cpu、nsaudio-watch（Transient=yes） | 运行中 | 改成 /etc/systemd/system 下 enabled 的常驻 unit（按现有 ExecStart，不改功能）；封板期是否做由总调度定 |
| GPU3 为 ep02 预留 | `/root/.local/state/NS-Studio/.train.lock.gpu3.qwen-agent-paused-for-ep01` | 锁暂停中（GPU3 无锁） | ep02 渲完后改名回 `train.lock.gpu3` 还给 Qwen 并发信箱通知 |
| qwen-agent3 未经 claim_gpu 启动 | `/root/qwen-agent/agent/run_agent.sh`（CUDA_VISIBLE_DEVICES=3，AGENT_GPUS=3,0） | 运行中；锁靠手动维护 | 下次正常重启时恢复用 `claim_gpu.sh 3 8191 qwen-agent --` 包裹 |
| ep02 端到端渲染 | renders_gpu3/ep02（未归档） | 等 fredw-92：剧本 H3提示词 + S2 就绪 | 归档旧 ep02 → GPU3 渲染 → 逐镜核对 `h3_prompt_source=script_field` 与 lnwan_qi → 还卡 |
| lnwan01 开训 | 信箱 f11c841c（排第 2） | 排队 | 本机后台检查在等 GPU0 占用后报开训时间 |
| 信箱任务优先级 | dispatcher.py 按文件名先来先跑 | 无优先级 | 需重启容器才能加；封板期不做 |
| 笔记本隧道守护 | 笔记本 `tools/gpu3_tunnels.py`（pid 6076） | 运行中 | 不开机自启；笔记本重启后需重新运行 |
| T46 调度器 / up4k-test | — | 未运行 / failed | 按总调度要求暂不处理 |

## 8. 封板修复记录（2026-10-30 下午）

- D-22：T46 阶段调度器关闭，`ns-sched` 保持不运行，**改用固定分卡**（GPU1 = Qwen 写作模型；GPU0/GPU3 = Qwen 的 LoRA 卡，渲染时借用）。
- GPU3 现为 `train.lock.gpu3`（by `ep02-render-reserve`）预留给 ep02；渲完删掉这把预留锁，把 `.train.lock.gpu3.qwen-agent-paused-for-ep01` 改名回 `train.lock.gpu3`（qwen-agent）。
- 其余逐项见 `docs/release/debug_gpu3.md` 和 CHANGELOG（封板修复）。
