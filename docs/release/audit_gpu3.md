# gpu3 封板审计（只读）

- 审计时间：2026-10-30 07:34–07:50 EDT（笔记本 20:34–20:50 JST）；两边时钟 NTP 同步，偏差 <15 s
- 方式：`ssh gpu33` 只读命令 + 笔记本只读检查。没有启停任何服务、没改/删任何文件、没碰锁/lend、没投信箱任务、没跑渲染/训练。
- gpu3 归 fredw-ae 会话管；本文只列观察到的问题和建议修法，修不修、何时修由总调度定。
- 严重度：**P0** = 阻塞封板；**P1** = 封板前应修；**P2** = 以后再说。

## 总结

| # | 严重度 | 问题（一句话） |
|---|---|---|
| A | P0 | ep02 渲染**没在跑**（07:45 复核）：GPU3 0%、:8191 队列空、没有 `lend.gpu3`、没有 weita-runner 实例、rerender_events 最后一条是 10-29 18:57Z。目前**没有任何一集端到端跑通过** |
| B | P0 | 笔记本↔gpu3 的同步、隧道、`ns_api :8800` 全挂在 Claude 会话或另一个会话的 scratchpad 上，会话一结束就停；Windows 自启任务指向不存在的目录，上次运行失败 |
| C | P0 | 剧本三处版本不一致：笔记本 / nsfs_mirror / 桥读的 nsfs_canvas 副本，sha 三个都不同；桥读的那份是 10-29 17:06 的旧版 |
| D | P1 | 核心服务全是 transient unit，`ns-comfy@*` 也是 disabled：gpu3 重启后 Qwen LLM、信箱、智能体容器、ComfyUI 都不会自己起来（10-29 22:36 那次重启后是手工拉起的） |
| E | P1 | 孤儿 `chain.sh`（pid 35779，8h+，ppid 1）还活着，正在跑 `bench2.py h3b`，下一步会跑 `bench2.py train`；gpu3_health.md 写的是“已停” |
| F | P1 | GPU3 预留只停留在约定上：没有 `train.lock.gpu3`/`lend.gpu3`；出图接口默认 `DEFAULT_JOB_GPUS=[3]`，bench2 和 image_docker 都可能在 ep02 开跑前抢到 GPU3 |
| G | P1 | 信箱：排队 7、运行 2（已跑 31 min）；lnwan01 交接任务 f11c841c 还在 inbox 第 2 位，GPU0 持着 `train.lock.gpu0` 但 0% 空转；6 个失败里 3 个是 “Model stream ended after a tool result without visible progress”，1 个是 32k 上下文溢出 |
| H | P1 | rerender_queue 里 4 条 owner 请求（3 条 07:29–07:30 EDT、1 条 06:57Z）没有 `run_id`/`gpu`，weita-runner 只取有 run_id 的条目，看不到消费者 |
| I | P1 | 桥用的 h3_lint、import_script 跟笔记本代码不一致（sha 不同）；nsfs_mirror 的代码停在 10-29 23:00 |

---

## 1. systemd

| 项 | 严重度 | 证据 | 建议修法（只描述，没做） |
|---|---|---|---|
| 核心服务全是 transient unit，重启不会恢复 | P1 | `systemctl list-unit-files`：`qwen-agent3 / qwen-llm-gpu1 / qwen-llm-relay / qwen-mailbox / weita-v3-llm-cpu / nsaudio-watch / up4k-test` 都是 `transient`，FragmentPath=`/run/systemd/transient/*`。gpu3 最近一次启动在 10-29 22:36（`uptime 8:57`）；`journalctl -b`：ComfyUI 三个实例在 22:38:28 被人工拉起，up4k-test 在 22:38:30 | 用现有 ExecStart 写成 `/etc/systemd/system/*.service` 并 enable（功能不变）；起依赖顺序：relay 依赖 qwen-llm-gpu1，qwen-agent3 依赖 relay+mailbox |
| `ns-comfy@0-8188 / 1-8189 / 3-8191` 在跑但 unit 是 disabled | P1 | `systemctl show ns-comfy@0-8188 -p UnitFileState` → `disabled`；`multi-user.target.wants` 里只有 `nsfs-canvas-bridge`、`qwen-image-api`。桥的 `NSC_COMFY=0=…8188;1=…8189;3=…8191` 依赖这三个 | `enable ns-comfy@0-8188 ns-comfy@3-8191`；GPU1 那个见第 2 节 |
| `qwen-agent3` 是 `Restart=no` | P1 | `systemctl show qwen-agent3 -p Restart` → `no`；`/root/qwen-agent/agent.log`：07:11 dispatcher 因 `FileNotFoundError … os.replace(src, dst)`（任务刚被撤走的竞争）崩溃，`[qwen-agent gpu3] exited 1`，07:13 才被人工重启（07:13 版 dispatcher.py 已加 try/except） | 常驻 unit 用 `Restart=on-failure`，dispatcher 再崩能自己回来 |
| `up4k-test.service` failed（transient） | P2 | `Result=exit-code`，22:38:30 起来就 `status=1/FAILURE`；Description=`tools/seedvr2/tests/run_ab.sh` | 确认 4K 测试不需要后 `systemctl reset-failed up4k-test` |
| `redis-server.service` failed | P2 | `Start request repeated too quickly`，`Result=protocol`（22:36:40） | 没看到项目用 redis；不用就 disable |
| claude-gpu3 遗留 unit 文件 | P2 | `weita-runner@.service`（Description “claude-gpu3; started by the owner only…”）、`lw-qi-lora.service`（“claude-gpu3 … waits for lend.gpu0=lw-img-lora”，lin_wan_qi_v1 已交付）、`ns-api.service`、`ns-ui.service`：都 disabled/inactive | 写明哪些保留（weita-runner@ 是渲染链要用的）；lw-qi-lora 可以删 |
| `ns-image-reap.timer` / `nsfs-canvas-bridge` | OK | timer enabled 每分钟；bridge enabled、active、`NRestarts=0`，07:22:08 起 | — |

## 2. 进程与 GPU

| 项 | 严重度 | 证据 | 建议修法 |
|---|---|---|---|
| ep02 渲染没在跑 | P0 | 07:45:14：`nvidia-smi` GPU3 `399 MiB, 0 %`；`curl :8191/queue` → `{"r":0,"p":0}`；`ps` 里没有 weita_runner / ns_render；`rerender_events.jsonl` 最后一条 `weita-fix-ep01s1… done 2026-10-29T18:57:55Z`；`renders_gpu3/ep02/status.json`：`frames_done 0, videos_done 0, qa pending`（10-29 21:04Z） | 确定 ep02 用哪个入口（runner + `lend.gpu3 = "owner-run <run_id>"`，或桥的 `POST /api/gpu3/projects/weita/episodes/{ep}/run`）；开跑前先按下面一行把 GPU3 锁住 |
| GPU3 预留没有锁 | P1 | 锁目录只有 `train.lock.gpu0`、`train.lock.gpu1`、`.train.lock.gpu3.qwen-agent-paused-for-ep01`，没有 `lend.*`；`image_api.py:44 DEFAULT_JOB_GPUS = [3]`；`image_docker.sh` 的空闲判定 = 没有别人的 train.lock + 显存 < 1500 MB → 现在 GPU3 算空闲；桥 `/api/gpu3/gpus` 里 GPU3 `lock_file:null, train_lock:null` | ep02 开跑时写 `lend.gpu3`（owner-run）或 `train.lock.gpu3`（by=ep02-render）；渲染期间出图默认卡改成 GPU0，或者暂停接出图任务 |
| 孤儿 chain.sh 还在跑 | P1 | `ps`：`35779 ppid=1 08:16:37 /bin/bash ./chain.sh`（cwd `/root/build_sage`）→ `136364 bench2.py h3 1,3,0 kitchen h3b`（29 min）；`chain.log`=“Terminated”（h3a 被杀后链条接着往下走）；下一步是 `bench2.py train 1,3,0 lowvram,fullvram`（在抢到的卡上跑 ai-toolkit 训练）。`docs/gpu3_health.md` 第 38 行写的是“已停（随 35780）” | kill 35779 及其子进程（由 fredw-ae/项目方执行），并更正 gpu3_health.md。眼下 bench2 拿不到卡，只是因为过期的 `scheduler_plan.json`（10-29 23:43）把三张卡都标成 `locked:true`；只要有人刷新这个 plan，它就会去抢 GPU3/GPU0 |
| GPU0：持锁但空闲 | P1 | `train.lock.gpu0` by qwen-agent，since 06:41；GPU0 `429 MiB 0 %`；lnwan01 交接任务 `20261030T065327-f11c841c` 还在 inbox；gpu3 上 pid 144677 是笔记本会话起的轮询循环，在等它变成 TAKEN/GPU0_BUSY | 见第 3 节：让 lnwan01 先执行 |
| GPU1：ComfyUI 8189 跟 llama-server 同卡 | P1 | GPU1 `21051/24576 MiB, 96–98 %`：llama-server pid 131492 占 20642 MiB + ComfyUI pid 5506 占 380 MiB；桥 `NSC_COMFY` 仍然列着 `1=http://127.0.0.1:8189` | 停掉 ns-comfy@1-8189（GPU1=Qwen 永久），从 `NSC_COMFY` 去掉 1，免得桥把渲染派到 GPU1 上 OOM |
| CPU 版 Qwen（:8097）没人用 | P2 | `weita-v3-llm-cpu` pid 100976，RSS 30 GB，`-t 48 -c 32768`，1 个 slot；`ss -tnp` 里 :8097 没有 ESTAB 连接 | 确认没有消费者就停掉 |
| `scheduler_*` 状态文件过期 | P2 | `scheduler_plan.json` 10-29 23:43，`scheduler_mode`=`dry-run`，里面还写着 weita-v3 / char-variety / wardrobe（都已停） | 不留调度器的话就归档，免得 bench2 这类脚本读到假状态 |
| GPU2 / 容器 / 过期 lend | OK | GPU2 15 MiB、桥标 `faulty:true`；`docker ps -a` 只有 qwen-agent、qwen-llm、dcgm-exporter，没有残留容器；`.lend.gpu0.dead-pose-lora-20261030`、`.lend.gpu3.removed-wardrobe-20261030` 已改名不生效 | — |

## 3. Qwen（LLM、信箱、调度程序）

| 项 | 严重度 | 证据 | 建议修法 |
|---|---|---|---|
| 信箱积压，lnwan01 被卡住 | P1 | `:8099/health` → `{"queued": 7, "running": 2}`；`inbox/` 最早一条 06:53；运行中的 `0e6688b0`（canvas，lora 评测）和 `391159fc`（fredw-d9-system）07:13 开始，07:45 已 31 min，日志 0 字节；lnwan01 交接 `f11c841c` 排在 `9d95ab55` 后面；`dispatcher.py`：`sorted(INBOX.glob)` 严格按文件名先后、`MAX_TASKS=2`、`TASK_TIMEOUT_S=6h` | 加 `meta.priority`，或者 GPU 训练类任务单独开一路 |
| 失败模式：流中断 / 上下文溢出 | P1 | outbox 12 条里 6 条 failed：`fcbdc57f / f48d4702 / ce266008` = `[API Error: Model stream ended after a tool result without visible progress.]`（前面刷了几十行 “Retrying provider attempt”）；`b2c39613` = `400 request (45295 tokens) exceeds the available context size (32768 tokens)`；`ab1a2006` = `Operation cancelled`（07:11 容器重启） | 上下文已经是每 slot 49152（`/props n_ctx=49152, total_slots=2`，`-c 98304 --parallel 2`），溢出那条可以重试；流中断要在 qwen CLI 侧加超时/重试上限，失败后自动重新入队一次 |
| 有个 slot 生成特别长 | P2 | `/slots`：slot 1 `n_decoded=11230`（上限 `n_predict` 20000），slot 0 `2385` | 观察是不是在 thinking 循环；需要的话把 max_tokens 调到 8–12k |
| llama-server 健康 | OK | `:8098/health` ok；`docker logs --since 60m qwen-llm` 里没有 error/OOM；约 26.8 t/s | — |
| 06:44 LLM 迁移期间的 sshd 报错 | P2 | `journalctl -p err`：06:44:50–53 `sshd: connect_to 127.0.0.1 port 8098: failed` 刷屏（笔记本隧道在重启窗口里连不上） | 不用处理 |
| QWEN.md 一致性 | OK / P2 | `sha256 agent/QWEN.md == work/QWEN.md = db342d2f…`；`/root/qwen-agent/QWEN.md` 不存在（只有这两份）。P2：正文还写着“内容全部由你负责”，G8 只在开头加了一段覆盖说明 | 把正文改顺 |
| Qwen 看到的项目文档快照过期 | P1 | `/root/qwen-agent/work/project/docs/REQUIREMENTS.md` 16947 B，10-30 01:44 EDT；笔记本 `docs/REQUIREMENTS.md` 17756 B，20:21 JST（=07:21 EDT） | 给 `/work/project/` 加定时同步，或每次发信箱任务前同步一次 |
| SYSTEM_STATUS 有过期/矛盾内容 | P2 | `work/SYSTEM_STATUS.md`（07:33 刷新）S3 还写着“容器在 GPU1 … 写作模型随后迁到 GPU1”（早已完成）；“系统待办 更新于 09:10”比当前时间还晚；出图那行写“GPU0、GPU3 可用”，跟 GPU0=lnwan01、GPU3=ep02 预留冲突 | 修正 S3；status_board 读锁的时候也显示预留 |
| `.bak` 堆积 | P2 | `agent/` 下 7 个 `.bak-20261030`（dispatcher.py、image_docker.sh、migrate_gpu1.sh、QWEN.md、run_agent.sh、run_llm_docker.sh、wait_gpu.sh） | 挪到 `agent/_bak/` 或者进 git |

## 4. 渲染链

| 项 | 严重度 | 证据 | 建议修法 |
|---|---|---|---|
| 剧本三处版本不一致 | P0 | sha256：笔记本 `data/import/script_v2.json` = `3c1c00cd4e0d…`（593882 B，20:25:26 JST）；gpu3 `nsfs_mirror/data/import/script_v2.json` = `ea713d4a0da3…`（593149 B，07:19:42 EDT）；桥 `NSC_SCRIPT_JSON=/root/…/nsfs_canvas/data/import/script_v2.json` = `217e53e977dd…`（548155 B，**10-29 17:06**，桥用它算镜号和总镜数） | 只认笔记本一个真源，推送时两处一起写，或把桥的 `NSC_SCRIPT_JSON` 指到 nsfs_mirror；渲染前核对 sha |
| s1_gate 的 sha 跟文件对不上，时间没有时区 | P1 | 笔记本 `s1_gate.json script_sha=889fdda6…`，gpu3 的是 `da8086b0…`，都不等于对应 script_v2.json 的 sha256；`checked_at "2026-10-30T20:18:50"` 没有时区（这是 JST，gpu3 在 EDT）；`g3_ref` 原文写着 “validator 0 指本次导入的 ep01 rules_v2 …，ep02-60 为 v2 备份恢复、未按 rules_v2 校验” | 写明 gate sha 的算法；时间统一用带时区的 ISO；ep02–60 要按 rules_v2 校验后再算过闸 |
| 笔记本剧本最后一次写入没记进 import_log | P2 | `import_log.jsonl` 最后一条 20:18:30；`script_v2.json` mtime 20:25:26 | 所有写 script_v2 的路径都记一行 |
| mirror 里有一份 36 KB 的剧本备份 | P2 | `nsfs_mirror/data/import/backups/script_v2.json.20261030-201904` 只有 36706 B（其他备份都 >540 KB），说明 07:19 被覆盖前，mirror 里放的是一份残缺剧本 | 推送时校验大小、集数，不够就拒绝 |
| rerender_queue 里没人消费的条目 | P1 | queue 5 条、events 3 条。4 条 `{"by":"owner","stage":"image","gpu":null,"run_id":null}`：`15b69a19263d`（ep01-S1，06:57Z）、`be1c6a3107eb`（ep01-S1，11:29Z）、`773b0dd5fed5`（ep01-S2，11:29Z）、`3f4ca7313a9d`（ep09-S1，11:30Z），都没有 events。`weita_runner.py:41 RUN_OPS = ("render","run")`，:106 要求条目有 `run_id`，另外还要 `lend.gpuN` 里写着 owner-run | 定下 image 阶段重渲由谁消费；canvas 至少显示“排队中，无消费者”；ep01 shot 目录已经归档到 `_archive/ep01_v2_20261030`，要确认这几条指向新版 |
| weita-runner 从没在 gpu3 跑过 | P1 | `ns-studio/data/run/weita/logs/` 下没有 `runner_*.log`；`systemctl list-units weita-runner@*` 为空 | ep02 如果走 runner，把 `lend.gpu3="owner-run <run_id>"` + `systemctl start weita-runner@gpu3` 写进 ep01_render_log 的操作清单 |
| 桥健康端点 | OK / P2 | `/api/gpu3/health` 200（1.9 ms），`/api/gpu3/gpus` 200（153 ms）；`/health`、`/api/health`、`/api/status` 都是 404 | P2：加一个根路径 `/health` |
| renders_gpu3 结构 | P2 | 454 MB；ep02–ep36 加 `_archive/ep01_v2_20261030`；散着 `ep05_superseded_reflw01`、`S1.superseded_backview`、`S2.superseded_scoring_v1`；根目录有 `LORA_REGISTRY.json.bak-20261030` | 统一挪进 `_archive/` |
| LORA_REGISTRY | OK / P2 | 1 条 `lin_wan_qi_v1 status=accepted`，文件存在，`sha256 873b727b…` 跟实际文件一致；`ComfyUI/models/loras/LORA_REGISTRY.json` 软链完好；`find -xtype l` 没有断链。P2：`trained_at "06:53:00Z"` 其实是 EDT（文件 mtime 06:54 EDT = 10:54Z）；`"by":"claude-gpu3"`；loras 目录里有 `LORA_REGISTRY.json.broken-copy-20261030`；lnwan01 还没登记 | 改正 trained_at；清理 broken-copy；lnwan01 训完再登记 |
| 桥的 lint/导入代码跟笔记本不一致 | P1 | `h3_lint.py`：mirror `06a7cef9…` vs 笔记本 `7a289043…`；`tools/import_script.py`：mirror `6a17238d…` vs 笔记本 `b547c964…`；nsfs_mirror 代码目录最后修改 10-29 23:00，不是 git checkout | 封板时做一次代码同步（或从 git tag 部署），部署记录写 sha |

## 5. 同步与“只活在会话里的东西”

| 项 | 严重度 | 证据 | 建议修法 |
|---|---|---|---|
| 渲染同步循环挂在别的会话的 scratchpad 上 | P0 | 笔记本 pid 3612：`bash …\Temp\claude\D--kimi-ns-storyboard\7785c2ec-…\scratchpad\sync_laptop.sh`（14:32 JST 起；外层 31796 挂在 claude.exe 19024 下）。脚本注释写着 “runs while this Claude session lives”，负责 renders_gpu3 → 笔记本 `data/renders_gpu3`、`previews/weita_epXX`，以及把笔记本 rerender_queue 合并进 gpu3。`.last_sync_gpu3`=1793359986（审计时约 8 min 前，还在工作） | 移进仓库（如 `tools/sync_gpu3.sh`），由守护或 Windows 计划任务起，日志写到 `data/logs/` |
| 其他同步脚本没在跑 | P1 | 同一个 scratchpad 里还有 `pull_laptop.sh / music_sync.sh / previews_sync.sh / g3pull.sh / nsfs_watch.sh / rsipull.sh`，进程表里都没有；gpu3 没有 crontab，也没有 rsync 循环。剧本推送只靠 `ns_api`（`services/api/ns_api/script_inbox.py`），没有定时同步，所以才有 C | 列一张同步清单（方向、触发方式、负责人），不用的删掉 |
| 笔记本开机自启是坏的 | P0 | 计划任务 `NS-Studio-Autostart-Trial` → `powershell -File D:\Coding\NS-Storyboard\ops\autostart\autostart_trial.ps1`，这个目录**不存在**；`LastTaskResult 2147942667`（0x8007010B，目录名无效），上次运行 13:02。`ns_api :8800`（pid 37672）、`gpu3_tunnels.py`（pid 6076）都是手工起的 | 把自启任务改到 `D:\NS-Final Studio`，起 ns_api、gpu3_tunnels、同步守护 |
| 隧道重复托管 | P2 | `tools/gpu3_tunnels.py`（19:55 起）托管 15180/18099/18098；claude.exe 19024 下还有一个 `while true; do ssh -N -L 15180… -L 18099…` 循环（14:21 起）。`data/logs/gpu3_tunnels.log`：`19:55:25 supervisor started`、`20:35:49 qwen-llm: down 2x, (re)opened … (pid 39248)` | 只留 gpu3_tunnels.py；会话循环结束后守护会补上 |
| 会话里的等待循环 | P2 | claude.exe 19024 下：`until … lin_wan_qi/.done … systemctl is-active lw-gpu0-relay`（15:14 起；`lw-gpu0-relay` 已不存在，可能永不退出）、`until curl :8800/api/qwen/tasks/20261030T023440-50611743`（15:34 起）；claude.exe 1552 下轮询 f11c841c（gpu3 pid 144677，最多 3 h）；claude.exe 2104 下循环看 GPU0/3 忙闲 | 都是只读轮询，随会话结束；lw-gpu0-relay 那个可以手动结束 |

## 6. 磁盘、杂物、重复副本

| 项 | 严重度 | 证据 | 建议修法 |
|---|---|---|---|
| 磁盘 / 内存 | OK | `/` 1.8T，已用 541G（32%），inode 1%；内存 503G，可用 466G | — |
| `/root/ns-final-studio`（73G）跟 ComfyUI/models 是同一批文件 | OK / P2 | `stat`：两边 fasth3_omniref… 都是 inode 58073109，硬链数 2，不额外占空间 | 在文档里说明是硬链，别当成重复副本删掉 |
| `/root/work/fredw/kimi-ns-storyboard` 162G | P2 | `du`；10-28 以后没有改动 | 确认是不是旧项目，由项目方决定归档还是删除 |
| 其他旧目录 | P2 | `/root/build_sage`（229M，孤儿 bench）、`/root/rsi-idx`（120M，ns-studio 的另一份 checkout）、`/root/rsi-wt`、`/root/gpuburn-20261027`、`/root/gpu-burn.src`、`/root/gpu_unlock_src`、`/root/qa_supervisor`、`/root/ns-studio-creator-data` | 列一张封板保留清单，其他归档 |
| 旧剧本 `.bak` 放在 Qwen 能读的地方 | P1 | `find … -name "*.bak*" -o -name "*.broken*"` 共 55 个；`/root/qwen-agent/work/project/script play lib/为他而骚 （剧本和镜头）v2.md.bak-20261030-{heelthin,skirt,harness,leica,voice,toenail,steelbead}`（每个约 250 KB）就在 Qwen 的项目快照里 | 挪出 `/work/project/`，免得 Qwen 读到旧版剧本 |
| 代码重复 | P1 | 见第 4 节 h3_lint / import_script；另外 `ns-studio/packages/prompt-compiler/…/compiler.py` 与 `/root/rsi-idx/ns-studio/…/compiler.py` 同 sha（`804bf549`），`nsfs_mirror/services/agent/ns_agent/compiler.py` 是另一份（`c5a25a41`）；`ns-studio/data/archive/pre_audit3_20261030/shot_audit.py` 是旧版 | 只从一个仓库部署，部署记录写 sha |
| 笔记本仓库没提交的改动 | P2 | `D:\NS-Final Studio` `git status --porcelain` 225 条，HEAD `e614fee`（12:33 JST） | 封板前提交或打 tag |

## 7. 关于“完整跑完一集做验收”（项目方 20:45 JST 要求）

本审计只读，没有跑。下面是只读观察，给真正执行的会话（gpu3 归 fredw-ae）参考：

- 现在没有任何一集是端到端完成的：`renders_gpu3/ep02/status.json` `frames_done 0 / videos_done 0`；ep05 `frames_done 2 / videos_done 0`；ep01 已归档（`_archive/ep01_v2_20261030`）。
- 剧本闸门原文：只有 ep01 按 rules_v2 校验过（validator 0），“ep02-60 为 v2 备份恢复、未按 rules_v2 校验”。桥的 `/api/gpu3/projects/weita/episodes` 对 60 集返回的结构都一样（6 镜），看不出哪集标红；标红要以笔记本画布显示为准。
- 开跑前要先清掉的阻塞项（按顺序）：E（kill chain.sh）→ F（锁 GPU3）→ C（剧本三处对齐）→ 选定入口（桥 `POST …/episodes/{ep}/run` 或 runner+lend）。

## 附：建议处理顺序

1. 验收集：先锁 GPU3（lend/train.lock），停 GPU3 上的默认出图，kill 孤儿 chain.sh，再选一集不标红的跑通（A、E、F）。
2. 统一剧本真源，先推送再核对三处 sha（C）。
3. 同步循环和自启任务改成常驻，不依赖任何会话（B）。
4. gpu3 的 transient unit 改成常驻 unit，qwen-agent3 设 `Restart=on-failure`（D）。
5. 信箱加优先级，让 lnwan01 先拿到 GPU0（G）。
