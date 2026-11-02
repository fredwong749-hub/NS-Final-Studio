# V2 producer / night 部署手册（11-03 03:5x，只读调查 + 操作步骤）

执行人：**总调度，sv-17 之后**。本文件只是手册；调查阶段没有执行任何停止 / 启动 / 重启 / kill / 部署。
**每一个线上动作前，先确认项目方当时没在用**（网页 #/queue 没有未决项、没在审图、没在点“用这张 / 修改”；拿不准就不动）。
目标：V2（series10_v2）并回 V1 出图主干——笔记本旧 V1 producer 退出，gpu33 / gpu36 上 V2 producer + night 起来，视频 worker 改用 system_version 部署的仓库。
记号：`rsh` = `.venv/Scripts/python.exe tools/netfix/rsh.py`；`$OFF` = `/root/work/fredw/offline_20261101`；`$R` = `$OFF/repo`。

## 0. 核实到的事实（2026-11-03 03:49，笔记本 + rsh 只读）

| 项 | 事实 |
|---|---|
| 笔记本旧 producer | pid **13972**，StartTime 11-02 01:45:04，命令行 `C:\Users\fredw\AppData\Local\Programs\Python\Python312\python.exe -u tools/autopilot/producer.py serve`（**无 --run**）；父进程 **29176** = `D:\NS-Final Studio\.venv\Scripts\python.exe -u tools/autopilot/producer.py serve`（venv 启动器）。`data/producer/producer.pid` = {"pid":13972,"started":"2026-11-02T01:45:04"}；`data/producer/heartbeat.json` ts 03:48:58、paused=false、inflight=0 |
| 笔记本 control | `data/producer/control.json`：only=["__none__"]，hold_lanes 7 条（gpu33:0/1/3、gpu36:0/1/2、laptop:0）。`data/producer/runs/series10_v2/` 只有 log.jsonl（00:59:28），没有 control / heartbeat / registry / producer.pid |
| API | `GET :8800/api/producer/status` → active=false, service_alive=false |
| runs.json | primary=series10_v2；series10_v2 **status=preparing**；series10_s2 paused；series10_v1 archived；`config/pipeline/run.json` run_id=series10_v2 |
| gpu33 | `$OFF/run/producer.pid`=1491152、`night.pid`=1491154（审计 1.2/1.3 已记 DEAD，本次没逐个 kill -0）；fwd.pid=1069762 活；`$OFF/STOP` 不存在 |
| gpu36 | producer.pid=3300337、night.pid=3300339（同上）；fwd.pid=3019043 活；STOP 不存在 |
| gpu33 vidgen | pid **1497362**（11-02 18:14:57），`/root/work/fredw/venv_idm/bin/python -u tools/series10_video/vidgen.py run gpu33`（无 --run，环境无 NS_RUN），cwd=`/root/work/fredw/video10_srv`，`video10_srv/run/vidgen.pid`=1497362 |
| gpu36 vidgen | pid **3304076**（11-02 18:15:15），`... vidgen.py run gpu36`（无 --run、无 NS_RUN），cwd=`/root/work/fredw/video10_srv`，pid 文件=3304076；/proc exe 是 `/root/work/fredw/python/cpython-3.12.16-linux-x86_64-gnu/bin/python3.12`（与 gpu33 的 venv_idm py3.11 不同） |
| md5 vidgen.py | video10_srv（两台一致）`32cf3aa450e2e745e3868e2ff09420e4`；offline repo（两台一致）`f479d8873e33d2348f4588bda45bcd61`；笔记本 `2cda1b3a00b97a72c3c1d1dd1f96397b`（三份互不相同） |
| md5 night.py | video10_srv `8f3dc505aaa8112af5ec1b3ff58e5cb2`；offline repo `842d7aaeb721eea07f5f6ceac67b690c`；笔记本 `4221d36cafcb78028191727e5aaa40a6` |
| md5 producer.py | offline repo（两台）`102f13b300817ebdaae0f39541d897af`；笔记本 `1bde47e6da8ea7a3e6edaac1f7643c0c`（笔记本工作树有未提交改动） |
| 服务器 data | `$R/data/producer/runs/` 只有 series10_s2（V2 目录要 producer 首次起才建）；`video10_srv/data/pipeline/runs/` 有 ep02_r3 / series10_s2 / series10_v1 / series10_v2 |
| 服务器 GPU | gpu33 GPU0/1/3 util 0%、GPU2 15 MiB（永不用）；gpu36 三卡 util 0%（显存各 15–16 GB，常驻模型） |
| 服务器 producer.py | 已有 `--run` 参数（`$R/.../producer.py:3327`，`run = a.run or RUN_ID` 在 :3335），`serve --run series10_v2` 可直接用 |
| 遗留进程 | gpu33：bench2.py h3 pid **136364**；nsfs_canvas uvicorn pid **204085**（端口 5180）；audio_post.py watch pid 939465。gpu36：bakeoff `run.py gen` pid **2440298**（父 bash 2440296） |

## 1. 前置条件（全部满足才往下走）

执行人：总调度，sv-17 之后。

1. sv-17 已 cut / deploy / verify：`.venv/Scripts/python.exe tools/qa/system_version.py status`、`verify`。
   验收：两台 `$R/tools/autopilot/producer.py`、`tools/series10_video/night.py`、`vidgen.py` 的 md5 与笔记本一致（`rsh gpu33 "md5sum $R/tools/series10_video/vidgen.py"` 对 `md5sum tools/series10_video/vidgen.py`）。PRODMERGE-O 的 producer.py（不在导入时读死 run.json）已在包内。
2. runs.json：**series10_v2 必须是 producing，否则新起的 producer 每拍被强制暂停**（`producer.py:1883` 起 `ctrl()` 对 status≠producing 强制 paused_by=runs.json）。翻转规则与 `tools/master/sop_gate.py` 对齐，翻之前先只读判定：
   ```
   .venv/Scripts/python.exe tools/master/sop_gate.py status --run series10_v2 --json
   .venv/Scripts/python.exe tools/master/sop_gate.py check --run series10_v2 --episode 1 --stage 出图
   ```
   “出图”check 通过（剧本 → 导入闸门 → 资产就绪 → 提示词 全过）才改 status。翻转只走 PRODMERGE-O 的入口（写 status_history，并按 runs.json 重写派生的 run.json）：
   ```
   .venv/Scripts/python.exe tools/master/sop_gate.py promote --run series10_v2            # 只读判定，退出码 0 = 可以提升
   .venv/Scripts/python.exe tools/master/sop_gate.py promote --run series10_v2 --apply --by 总调度
   ```
   不要手改 runs.json 的 status。`config/pipeline/sop_gate.json` promote.auto=true 时，producer 在 preparing 下每分钟自己判、自己提升（默认 false：只在 log.jsonl 记 promote_ready）。
   提升后 producer 仍按镜过 sop_gate.require（首帧 = 出图、尾帧 = 尾帧），提示词没过的镜不派；成人镜只记 pending_owner，不自动派。
3. producer dryrun（不出图）：`.venv/Scripts/python.exe tools/autopilot/producer.py dryrun`，要求退出码 0、无 FAIL。
4. 三台 `config/pipeline/run.json` run_id 与 `runs.json` primary 都是 series10_v2（deploy 后 `rsh gpu33 "cat $R/config/pipeline/run.json"` 复核）。PRODMERGE-O 后 run.json 是 runs.json 派生的指针：不一致时跑 `.venv/Scripts/python.exe -c "import sys; sys.path.insert(0,'tools/autopilot'); import runs; print(runs.run_ptr_drift()); runs.sync_run_ptr()"`。producer / episode_pipeline / decisions_guard 已改为直接读 runs.json primary。
5. 共用验收与分道开关：`config/pipeline/producer.json`（accept.enabled=true 只对资产包剧；fanout.enabled=false，开不开见手册末“待决”）。定稿档 `config/render_quality.json auto_final_on_lock_runs.series10_v2` 仍为 false，由总调度在首批首帧过共用验收后打开。
6. 重启队列没积压：`.venv/Scripts/python.exe tools/autopilot/restart_queue.py status`。

## 2. 停笔记本 V1 旧 producer（pid 13972）

执行人：总调度，sv-17 之后；线上动作，先确认项目方没在用。

### 2.0 先改 restart_producer.ps1，否则会误判

现行文件是 `ops/autostart/restart_producer.ps1`（`tools/autopilot/restart_producer.ps1` 不存在）。它写死 legacy 路径，且被 `tools/autopilot/episode_pipeline.py:288` 自动调用，所以**改之前不要手动跑它**。要改的行：

| 行 | 现状 | 改成 |
|---|---|---|
| 8 | `data\producer\control.json` | `data\producer\runs\series10_v2\control.json`（或经 `runs.producer_dir`） |
| 14 | `data\producer\heartbeat.json` | `data\producer\runs\series10_v2\heartbeat.json` |
| 18 | `data\producer\producer.pid` | `data\producer\runs\series10_v2\producer.pid` |
| 11、33 | `producer.py pause/resume` 无 --run | 加 `--run series10_v2` |
| 30 | `-ArgumentList "-u","tools/autopilot/producer.py","serve"` | 末尾加 `"--run","series10_v2"` |
| 25 | 按 CommandLine 找父进程（启动器） | 保持，启动器 + 子进程都要停 |

这些是代码变更，随 sv 发版；来不及就用下面 2.2 的手工命令。

### 2.1 排空（rendering = 0）

```
Get-Content "D:\NS-Final Studio\data\producer\heartbeat.json"      # inflight 要为 0（03:48:58 实测 0）
curl.exe -s http://127.0.0.1:8800/api/producer/status
.venv/Scripts/python.exe tools/autopilot/producer.py pause --by "总调度 PRODMERGE" --kind ops --expires-s 180 --run series10_v1
```
`--run series10_v1`（legacy，落在 data/producer/）；ops 暂停上限 180 s，到点自动恢复，所以暂停后立刻做 2.2。循环看 heartbeat.inflight 直到 0（最长 3 分钟；在途靠 45 分钟租约过期重派，不强等）。

### 2.2 停

```
Get-CimInstance Win32_Process -Filter "ProcessId=13972" | Select ProcessId,CommandLine    # 确认还是它
Stop-Process -Id 13972 -Confirm:$false
Get-CimInstance Win32_Process -Filter "ProcessId=29176" | Select ProcessId,CommandLine    # 启动器是否还在
Stop-Process -Id 29176 -Confirm:$false
```
（先子后父；启动器不停会再起子进程。）

### 2.3 确认停了

```
Get-Process -Id 13972 -ErrorAction SilentlyContinue                      # 应无输出
Get-CimInstance Win32_Process | ? { $_.CommandLine -match "producer.py" } | Select ProcessId,CommandLine   # 不应再有无 --run 的 serve
Get-Content "D:\NS-Final Studio\data\producer\heartbeat.json"            # 隔 30 s 看两次，ts 不再变
```
旧 `data/producer/producer.pid` 残留不删（锁文件，下次 pid_alive 判死后覆盖）。此时 `/api/producer/status` 仍 service_alive=false（V2 还没起），属预期。

### 2.4 回退

V1 已 archived，通常不回退。需要时：`Start-Process -WindowStyle Hidden -WorkingDirectory "D:\NS-Final Studio" -FilePath ".venv\Scripts\python.exe" -ArgumentList "-u","tools/autopilot/producer.py","serve","--run","series10_v1" -RedirectStandardOutput ops\logs\producer.out.log -RedirectStandardError ops\logs\producer.err.log`。注意 series10_v1 status=archived，producer 只跑 producing，回退后会被 ctrl() 强制暂停，不会出图（安全阀）。

## 3. 起 V2 producer

执行人：总调度，sv-17 之后；线上动作，先确认项目方没在用。出图在服务器，**笔记本按现分区可以不起**（见 3.6）。

### 3.1 起之前先写 control（只开 1 条道、1 个镜）

V2 control：服务器 `$R/data/producer/runs/series10_v2/control.json`，笔记本 `data\producer\runs\series10_v2\control.json`。producer 每 20 s 读一次：
```
rsh gpu33 "cd $R && mkdir -p data/producer/runs/series10_v2 && printf '%s' '{\"paused\": false, \"only\": [\"ep01-S1\"], \"hold_lanes\": [\"gpu33:1\",\"gpu33:3\",\"gpu36:0\",\"gpu36:1\",\"gpu36:2\",\"laptop:0\"]}' > data/producer/runs/series10_v2/control.json && cat data/producer/runs/series10_v2/control.json"
```
gpu36 同理（只开 gpu36:0，hold 其余）；先只在 gpu33 起试跑，gpu36 等通过后再起。`only` 是镜号（与 `producer.py once --only ep02-S1` 同口径）。**`tools/netfix/dispatch.py` 会按分区重算 control（producer.py 注释 K-OPS-F20）**，起后立即 cat 复核没被覆盖。

### 3.2 起（服务器）

首选官方入口：`.venv/Scripts/python.exe tools/autopilot/resident_sync.py restart gpu33 --producer-only`（prep + 停旧 + 起 fwd/producer，不起 night）。但 **`ops/offline/resident_restart.sh` 的 producer 起命令目前是 `producer.py serve`（无 --run）**，依赖 run.json；sv-17 的该脚本若没带 `--run series10_v2`，用手工命令（照搬脚本环境）：
```
rsh gpu33 "OFF=/root/work/fredw/offline_20261101; R=\$OFF/repo; cd \$R && export TZ=Asia/Tokyo OFFLINE_SELF=gpu33 OFFLINE_ALIASES= PATH=\$OFF/bin:\$PATH PYTHONUTF8=1 PYTHONIOENCODING=utf-8 NS_QC_VISION_DIR=/root/work/fredw/video10_srv/models_cache/vision; d=data/producer/runs/series10_v2; mkdir -p \$d; setsid nohup \$OFF/venv/bin/python -u tools/autopilot/producer.py serve --run series10_v2 </dev/null >>\$d/producer.out 2>&1 & echo \$! > \$d/serve.pid; sleep 3; echo pid \$(cat \$d/serve.pid)"
```
gpu36：`OFFLINE_SELF=gpu36 OFFLINE_ALIASES=gpu33`。pid 文件用 `serve.pid`（与 ensure_runs.sh 约定一致；`producer.pid` 是 producer 自己的 JSON 锁，不占）。
**`ensure_runs.sh` 只起“非 primary 且 producing”的剧（:2、:12），V2 是 primary，它不会拉起 V2**；`resident_sync.health` 也只报警不拉起（:709-711）。所以 V2 常驻靠 PRODMERGE-O 让 resident_restart.sh 带 `--run`，或手工起。

不建议首跑用 systemd：`ops/factory/systemd/ns-producer.service` / `ns-night.service` 的 ExecStart 无 `--run`，且审计 1.3 记服务器未安装。

### 3.3 1 条道试跑 → 全开

1. 起后 1–2 分钟按 3.4 验证；看 gpu33:0 出 ep01-S1：running → passed（Q4/Q5/Q8/Q9 契约），总调度亲审出的图。
2. 通过再放：only 改成该集全部镜（或 `[]`），hold_lanes 分批缩小（gpu33 三条 → gpu36 两条 → 需要时 laptop:0）。每批观察 5 分钟 `log.jsonl` 无 `tick_err`。
3. 异常一键停：control `paused: true`，或 `producer.py pause --run series10_v2 --by 总调度 --kind master`（整条道暂停必须带 --kind）。

### 3.4 验证

```
rsh gpu33 "cd $R/data/producer/runs/series10_v2 && cat serve.pid producer.pid heartbeat.json; ls -la registry.json; tail -3 log.jsonl | cut -c1-300; p=\$(cat serve.pid); readlink /proc/\$p/cwd; tr '\0' ' ' </proc/\$p/cmdline"
curl.exe -s "http://127.0.0.1:8800/api/producer/status?run=series10_v2"
```
期望：producer.pid 的 pid 活；heartbeat.json ts 在 40 s 内；cmdline 含 `--run series10_v2`；cwd=`$R`；registry.json 存在；笔记本 API 的 service_alive=true 要等 puller / resident_sync pull 把服务器 V2 目录拉回（20 分钟一拍），即时核对用上面的 rsh。看到 paused_by="runs.json" → runs.json status 还不是 producing，回第 1 节。

### 3.5 回退

先 pause + 等 inflight=0，再 `rsh <host> "kill -TERM \$(cat $R/data/producer/runs/series10_v2/serve.pid)"`，不用 -9。control 文件只覆盖，不删。

### 3.6 笔记本 V2 producer（可选）

起前先做完 2.0。命令：`Start-Process -WindowStyle Hidden -WorkingDirectory "D:\NS-Final Studio" -FilePath ".venv\Scripts\python.exe" -ArgumentList "-u","tools/autopilot/producer.py","serve","--run","series10_v2" -RedirectStandardOutput ops\logs\producer.out.log -RedirectStandardError ops\logs\producer.err.log`。先写好 control（only=["__none__"] 即不出图）。验证看 `data\producer\runs\series10_v2\{heartbeat.json,producer.pid,registry.json}` 和 `/api/producer/status`（应 service_alive=true）。

## 4. 起 V2 night（两台服务器）

执行人：总调度，sv-17 之后；线上动作，先确认项目方没在用。**前置：第 3 节已出至少 1 个通过的首帧，且 `sop_gate.py check --run series10_v2 --episode 1 --stage 视频` 通过**（视频必须先过 Q9）；REVIEW_GLOBAL_OPUS 表 4 记 build_jobs.passed_frames 只读 takes.json、读不到 V2 的 ab 账，MERGE-VID-O 未修之前 night 也拿不到首帧。

night.py 已按 run（`night.py:35-47`，`--run` / `NS_RUN`）。服务器常驻（现行 resident_restart.sh 路线）：
```
rsh gpu33 "OFF=/root/work/fredw/offline_20261101; R=\$OFF/repo; cd \$R && export TZ=Asia/Tokyo OFFLINE_SELF=gpu33 OFFLINE_ALIASES= PATH=\$OFF/bin:\$PATH PYTHONUTF8=1 PYTHONIOENCODING=utf-8 NS_QC_VISION_DIR=/root/work/fredw/video10_srv/models_cache/vision NS_RUN=series10_v2; setsid nohup \$OFF/venv/bin/python -u tools/series10_video/night.py --run series10_v2 </dev/null >>\$OFF/logs/night.out 2>&1 & echo \$! > \$OFF/run/night.pid; sleep 3; echo night \$(cat \$OFF/run/night.pid)"
```
gpu36：`OFFLINE_SELF=gpu36 OFFLINE_ALIASES=gpu33`。或 `resident_sync.py restart <host>`（默认 all 模式含 night，同样要核对其 night 命令带 `--run`）。笔记本上跑 night 的替代方案：先 `.venv/Scripts/python.exe tools/series10_video/night.py --run series10_v2 --once` 单轮验证；两处不要同时跑。

验证：
```
rsh gpu33 "OFF=/root/work/fredw/offline_20261101; p=\$(cat \$OFF/run/night.pid); kill -0 \$p && tr '\0' ' ' </proc/\$p/cmdline; tail -5 \$OFF/logs/night.out"
```
期望 cmdline 含 `--run series10_v2`；V2 video 目录出现 `night_state.json`（审计 1.3 现状 MISSING；笔记本 `data\pipeline\runs\series10_v2\video\`，服务器 `$R/data/pipeline/runs/series10_v2/video/`）。
停：`kill -TERM <night.pid>`，不 -9。回退：停 night；V2 video 目录只增不删。

## 5. 退役 video10_srv（vidgen 改用 offline_20261101/repo）

执行人：总调度，sv-17 之后；线上动作，先确认项目方没在用；**第 3、4 节跑通后再做**。目录**只隔离不删**。

### 5.0 阻碍：先改代码，随 sv 发版

- `tools/series10_video/night.py:41`、`deploy.py:31`、`sync.py:24`、`tools/vqa/after_network.py:29` 的 `DEST = "/root/work/fredw/video10_srv"`；`config/factory/hosts.json:8,68` 的 `video_root`；`config/v2style.json:28`。不改，night 仍把作业推进旧目录、从旧目录读状态。改成 `$R` 时注意 `deploy.push` 会把笔记本的 `tools/series10_video`、`ns_render`、`ns_qc` 等代码目录写进 DEST，写进部署仓库会覆盖 sv 版本：**必须改成只推作业 json / 输入图，不推代码**。
- `ops/offline/resident_restart.sh:25,40`、`ensure_runs.sh:32` 的 `NS_QC_VISION_DIR=/root/work/fredw/video10_srv/models_cache/vision`（YuNet/SFace onnx）。隔离旧目录前把 `models_cache/` **复制**到 `$R` 并改这几处，否则 producer 的 QC 视觉模型找不到。
- 解释器：gpu33 用 `/root/work/fredw/venv_idm/bin/python`（py3.11），gpu36 现行 exe 是 `/root/work/fredw/python/cpython-3.12.16-.../python3.12`；`deploy.py:32` 的 PY 写 venv_idm。重起沿用各台现在的解释器。

### 5.1 步骤（每台）

1. 记录现状（只读）：第 0 节 pid / md5；`ls video10_srv/data/pipeline/runs/*/video`。
2. 等在途视频做完（`vidgen_<host>.log` 末尾无 running；控制用 `deploy.py control <host> '<json>'`）。
3. 停旧 vidgen（TERM）：
   ```
   rsh gpu33 "cd /root/work/fredw/video10_srv && p=\$(cat run/vidgen.pid) && kill -0 \$p && kill -TERM \$p; for i in \$(seq 20); do kill -0 \$p 2>/dev/null || break; sleep 1; done; kill -0 \$p 2>/dev/null && echo STILL_ALIVE || echo STOPPED"
   ```
   gpu36 同理（pid 3304076）。仍活先查原因，不默认 -9。
4. 需要续用的历史数据 **cp -a 复制**到 `$R/data/pipeline/runs/<run>/video/`（不 mv）。
5. 起新 vidgen（cwd=`$R`，带 `--run` 和 `NS_RUN`）：
   ```
   rsh gpu33 "OFF=/root/work/fredw/offline_20261101; cd \$OFF/repo && mkdir -p data/pipeline/runs/series10_v2/video && PYTHONUTF8=1 TZ=Asia/Tokyo NS_RUN=series10_v2 nohup /root/work/fredw/venv_idm/bin/python -u tools/series10_video/vidgen.py run gpu33 --run series10_v2 </dev/null >>data/pipeline/runs/series10_v2/video/vidgen_gpu33.out 2>&1 & echo \$! > \$OFF/run/vidgen_series10_v2.pid; sleep 3; cat \$OFF/run/vidgen_series10_v2.pid"
   ```
   gpu36：`run gpu36`，解释器先 `ls` 确认 venv_idm 存在且 import 正常，否则用其原 python3.12。
6. 隔离旧目录（只在 5.0 改完后）：`rsh <host> "cd /root/work/fredw && touch video10_srv/RETIRED_20261103 && mv video10_srv video10_srv.retired_20261103"`。5.0 没改完就只 touch 标记，不 mv。

### 5.2 验证

```
rsh gpu33 "p=\$(cat $OFF/run/vidgen_series10_v2.pid); readlink /proc/\$p/cwd; tr '\0' ' ' </proc/\$p/cmdline; tr '\0' '\n' </proc/\$p/environ | grep NS_RUN; md5sum $R/tools/series10_video/vidgen.py"
md5sum tools/series10_video/vidgen.py        # 笔记本
```
期望：cwd=`/root/work/fredw/offline_20261101/repo`；NS_RUN=series10_v2；两台 md5 = 笔记本 md5（调查时 f479d887… vs 笔记本 2cda1b3a…，**不一致，sv-17 后应一致**；不一致说明 sv 没覆盖 vidgen 或笔记本有未发版改动）；`ps` 里不再有 cwd=video10_srv 的 vidgen。

### 5.3 回退

停新 vidgen（TERM）；如已改名则 `mv video10_srv.retired_20261103 video10_srv`；按 `deploy.py start` 的本体重起旧 vidgen：`cd /root/work/fredw/video10_srv && PYTHONUTF8=1 nohup <原解释器> -u tools/series10_video/vidgen.py run <host> >> .../vidgen_<host>.out 2>&1 < /dev/null & echo $! > run/vidgen.pid`。目录没删过，回退只是挪回来。

## 6. 停遗留实验进程

执行人：总调度，sv-17 之后；线上动作，先确认项目方没在用。**全部“待总调度确认”**（C-4：占显存、占 ComfyUI 队列）。下面 pid 是 03:49 的值，停之前必须重新确认 pid、启动时间、cwd 没变。

### 6.1 只读确认

```
rsh gpu33 "ps -eo pid,lstart,etime,args | grep -E 'bench2|nsfs_canvas|audio_post' | grep -v grep; for p in 136364 204085 939465; do echo \$p cwd=\$(readlink /proc/\$p/cwd); done; nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader; ss -ltnp | grep 5180"
rsh gpu36 "ps -eo pid,lstart,etime,args | grep -E 'run.py gen|score_srv' | grep -v grep; for p in 2440296 2440298; do echo \$p cwd=\$(readlink /proc/\$p/cwd); done; cat /root/work/fredw/bakeoff/srv/run/gen.pid"
```

| 机器 | 进程 | pid | 启动 | cwd | 建议 |
|---|---|---|---|---|---|
| gpu33 | `bench2.py h3 1,3,0 kitchen h3b`（claude-kimi 的 env/comfy python） | 136364 | 10-30 20:05 | /root/build_sage | 待总调度确认后停（实验基准，已跑 3 天） |
| gpu33 | `nsfs_canvas` uvicorn `ns_canvas.app:create_app` 127.0.0.1:5180 | 204085 | 10-30 23:16 | .../nsfs_canvas/app/services/canvas_api | **待总调度确认**（画布老部署；停前看 5180 有没有连接 / 隧道依赖） |
| gpu33 | `audio_post.py watch --gate qa` | 939465 | 10-31 19:35 | 未读 | C-4 列出但无停止建议，默认保留，总调度定 |
| gpu36 | bakeoff `run.py gen --models=qa_base,...` | 2440298（父 bash 2440296） | 11-01 11:20 | /root/work/fredw/bakeoff/srv | 待总调度确认后停（pid 文件 `run/gen.pid`） |

### 6.2 停止（TERM，不默认 -9）

```
rsh gpu33 "kill -TERM 136364; sleep 5; kill -0 136364 2>/dev/null && echo STILL || echo STOPPED"
rsh gpu33 "kill -TERM 204085; sleep 5; kill -0 204085 2>/dev/null && echo STILL || echo STOPPED"      # 待总调度确认
rsh gpu36 "kill -TERM 2440296 2440298; sleep 5; kill -0 2440298 2>/dev/null && echo STILL || echo STOPPED"
```
gpu36 的 bakeoff 启动命令是 `(run.py gen ...; score_srv.py) &` 子 shell 链：只 TERM run.py，父 bash 会接着跑 score_srv.py，所以父 2440296 一并 TERM；停完 `ps` 复核没有 score_srv.py 冒出来。仍 STILL 的先查，30 秒后再由总调度决定是否升级到 -9。
验证：`nvidia-smi` 显存下降；`ps` 无对应进程；`ss -ltnp | grep 5180` 为空。

### 6.3 回退

这些是实验 / 老部署，没有统一启动脚本，**停之前把 6.1 的完整 ps 输出存档**（data/qa/ 或 docs/master/），作为回退依据：
- bench2.py：`cd /root/build_sage && /root/claude-kimi-ns-studio-v1/env/comfy/bin/python bench2.py h3 1,3,0 kitchen h3b`（参数取自本次 ps，未实测恢复）。
- nsfs_canvas：`cd /root/claude-kimi-ns-studio-v1/nsfs_canvas/app/services/canvas_api && /root/claude-kimi-ns-studio-v1/nsfs_canvas/.venv/bin/uvicorn --factory ns_canvas.app:create_app --host 127.0.0.1 --port 5180 --workers 1`。
- bakeoff：原命令 11-01 11:20 的 `cd /root/work/fredw/bakeoff/srv; (... run.py gen --models=qa_base,qa_native,qa_lora0,qa_imgtag,qa_suffix,qa_all --modes=contract --seed0; ... score_srv.py) >> run/gen.out`（完整行见 ps）。

## 7. 总顺序（总调度，sv-17 之后）

1. 第 1 节前置全过 → 2. restart_producer.ps1 改好（随 sv）→ 3. 停笔记本旧 producer（第 2 节）→ 4. 起 gpu33 V2 producer 1 条道（第 3 节），亲审首张 → 全开两台 → 5. 起 night（第 4 节）→ 6. 视频链跑通后退役 video10_srv（第 5 节）→ 7. 最后停遗留实验进程（第 6 节，不影响 V2）。
每步完成写一条日志（pid、时间、验证输出）；失败立刻按各节“回退”处理并通知项目方。

## 8. 发现的阻碍清单

1. `ops/autostart/restart_producer.ps1:8,14,18`（legacy 路径）、`:11,33`（pause/resume 无 --run）、`:30`（serve 无 --run）；且 `tools/autopilot/episode_pipeline.py:288` 自动调用它。
2. `config/pipeline/runs.json` series10_v2 status=preparing → producer 强制暂停；PRODMERGE-O 已加翻转入口 `sop_gate.py promote --apply`（规则：任一集 judge(出图) 通过），见第 1 节第 2 条。
3. `ops/offline/resident_restart.sh`（producer / night 起命令无 --run）；`ops/offline/ensure_runs.sh:2,12` 不管 primary；`tools/autopilot/resident_sync.py:709-711` health 只报警不拉起 primary 常驻。
4. `ops/factory/systemd/ns-producer.service`、`ns-night.service` ExecStart 无 --run，服务器未安装。
5. video10_srv 写死：`night.py:41`、`deploy.py:31`、`sync.py:24`、`tools/vqa/after_network.py:29`、`config/factory/hosts.json:8,68`、`config/v2style.json:28`、`resident_restart.sh:25,40`、`ensure_runs.sh:32`（模型目录）。
6. ~~`producer.py:77` RUN_ID 导入时读 run.json~~：PRODMERGE-O 已改（RUN_ID 只是兼容名；Paths / ctrl / main 一律现读 runs.json；`--run` 必须是 runs.json 登记的剧，否则退出码 2）。
7. 笔记本 producer.py 与服务器 repo 的 md5 不同（笔记本工作树有未提交改动），sv-17 之前不可对比。
