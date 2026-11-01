# 渲染服务器资源利用（INFRA，2026-10-31 夜）

项目方原话：“记得把全部的 GPU 用满，包括内存条也要用上。两台服务器的内存条加起来应该有 1 TB，都要用完，想想怎么用完。”

本文时间：笔记本是北京时间（TST）；服务器是美东时间（比北京时间慢 12 h）。原始数据都在服务器的 `/root/work/fredw/ns-infra/` 下：`util.csv` 每 10 s 采一次，`hist_before_*.json` 是重启前的 ComfyUI 历史，`lock*.log`、`restarts.log`。

## 1. 测量（22:10–22:30，改动前）

| 项 | gpu33 | gpu36 |
|---|---|---|
| 内存 | 503 GB；进程占用约 22 GB，页缓存 332 GB，available 475 GB | 440 GB；进程占用约 19 GB，页缓存 140 GB，available 413 GB |
| CPU | 96 线程，load 1–5 | 96 线程（EPYC 7K62 48 核），load 7–27，瞬时峰值 87（质检打分） |
| 可用 GPU | GPU0/1/3（GPU2 坏，永不用） | GPU0/1/2 |
| ComfyUI | :8188 `--cache-none`；:8189/:8191 `--cache-ram 140 200` | :8188/:8189 `--cache-none`；:8190 `--novram --disable-pinned-memory --cache-none` |
| ComfyUI 进程 RSS | 2.8 / 4.9 / 16.9 GB | 6.9 / 6.9 / 7.9 GB |
| 磁盘读 | 平均 91 MB/s，峰值 1.2 GB/s（模型从 NVMe 读） | 约 0 |
| GPU 利用率（采样均值） | GPU0 38%、GPU1 47%、GPU3 47% | GPU0 44%、GPU1 39%、GPU2 13% |
| IMGGEN 记录的道利用率 | 0.58 / 0.67 / 0.65 | 0.63 / 0.57 / 0.62（22:30 里程碑） |

ComfyUI 单张执行时间（从 `/history` 的 execution_start 到 execution_success 计）：

| | 首帧 768×1344，25 步 | 设定图 |
|---|---|---|
| gpu33:1 / :3（cache-ram） | 中位数 41.7 / 41.3 s | 145 / 143 s |
| gpu36:0 / :1（cache-none） | 42.8–48.0 / 46.1 s | 196–332 s |
| **gpu36:2（--novram）** | **100–116 s** | **635–650 s** |

### 时间都耗在哪里

1. **主要是笔记本链路，不是 GPU**：
   - 笔记本 Wi-Fi 实测下行约 270 KB/s。
   - 每个隧道请求（`/queue`）要 0.9–3 s，`ssh` 建连要 10 s。
   - 一张 1.3 MB 的 PNG 走 `/view` 要 7–35 s，走 `scp` 要 37 s。
   - 质检原来的走法是：图先下到本机，转成 JPEG，再 `scp` 上传到 gpu36 打分，同一张图过两次这条慢链路。
   - 举例：gpu33:1 在 09:11:26（美东）出完的图，IMGGEN 22:12:22 才记 done，晚了 56 s；下一张 22:12:28 才提交，这条道空转约 17 s。
2. **gpu36:2 的 `--novram`**：首帧慢 2.4 倍，设定图慢 4 倍。它是给 >260 帧的长镜头视频设的，却拿来出图了。
3. **模型加载**：图片任务里影响不大，因为热模型在页缓存里，从页缓存重载只要几秒。但 gpu33 上视频主模型只有一半在缓存里：fl2va 11.3/21 GB、ref2va 14.4/21 GB、32b 文本编码器 13.9/27.1 GB。反而是实验用的 Eros、fasth3、pinkcherry 整个都在缓存里。所以从出图切到出视频时，要从 NVMe 冷读约 1.3–1.5 GB/s：fl2va + ref2va + 32b TE 共约 48 GB，大约 35 s。
4. **调度方面**：改动前 IMGGEN 的道深度按“还没取回的任务”计算，又在提交前同步取回结果，所以取回一慢，补交也跟着停。另有两个问题：Windows 上 `state.json` 的 `os.replace` 撞上读者会报 PermissionError；写审阅页时一直拿着全局锁。
5. **隧道守护**：`data/logs/gpu3_tunnels.log` 每分钟都在重开 `qwen-llm` 的 18098 隧道。千问已经撤下，这是无效的 ssh 开销。**这条未修，留给负责隧道守护的会话。**

## 2. 改动（只改运行环境，不提交渲染任务）

| 改动 | gpu33 | gpu36 |
|---|---|---|
| 常用权重锁进内存（`ns-infra/pagelock.py lock`，mmap + mlock，等同 `vmtouch -dl`） | 151 GB，清单见 `hot33.txt`：Qwen-Image 2.1（含 turbo）、H3 ref2va/fl2va pruned int8、qwen3vl 32b int8 和 nvfp4、qwen3vl 8b、全部 VAE、PDD Acc、潜空间放大、全部 LoRA | 104 GB，整个 models 目录 |
| 其余模型预读（`pagelock.py warm`，可被回收） | 214 GB（`warm33.txt`），27 s 读完 | 不需要，已全部锁住 |
| ComfyUI 缓存参数 | 三卡都是 `--cache-ram 64 96`，见注 1 | :8188/:8189 `--cache-ram 56 88`；:8190 改为 normal 模式（去掉 `--novram`），见注 2 |
| 内存保护 `ns-infra/memguard.sh` | available < 48 GB 时对本项目 3 个端口发 `POST /free`；< 24 GB 时停 pagelock | 阈值 56 / 32 GB（共用机器，留得更多） |
| 采样器 `ns-infra/sampler.sh` | 每 10 s 记一次 `util.csv` | 同左 |

注：
1. gpu33 的缓存参数通过 systemd drop-in 生效：`/etc/systemd/system/ns-comfy@.service.d/10-infra-ram.conf` 指向 `/root/work/fredw/ns-infra/comfy-launch-ram.sh`。原单元和原 `comfy-launch.sh` 都没改，备份在 `ns-infra/backup/`。
2. gpu36:2 的模式切换写在 `longshot/lane.sh`：`restart long|normal`，当前模式记在 `run/mode`。

`--cache-ram A B` 的含义（ComfyUI 0.42 源码 `execution.py`）：A、B 不是缓存大小，而是“系统还剩多少可用内存”的门槛（GB）。可用内存 < B 时先丢掉非当前作业的缓存，< A 时再丢当前作业的缓存。原来的 `140 200` 在 503 GB 机器上意味着可用内存降到 200 GB 就开始丢缓存，等于只用了一半内存。现在的门槛对应的缓存上限：

- gpu33：(503 − 96) / 503 ≈ 81%，当前作业可以用到 87%；
- gpu36：(440 − 88) / 440 = 80%，当前作业可以用到 87%。

锁住的页不计入 available（不可回收），所以 ComfyUI 的缓存会在锁住的部分之外再往上涨，直到碰到门槛。

**gpu36:2 的 `--novram` 能不能改成 `--lowvram`？** 362 帧长镜头 OOM 发生在 `SamplerCustomAdvanced` 的激活值上（`render_endpoints.json` 里的 `_max_frames_comment`），不在权重上。`--lowvram` 能不能撑住 362 帧，只有跑一次长镜头才知道，而 INFRA 不提交渲染任务。所以保留 long 模式，做成可切换：**出 >260 帧的镜头前，先在该道队列为空时执行 `/root/work/fredw/longshot/lane.sh restart long`，用完再 `restart normal`**。重启约 10–25 s。`--lowvram` 留作待验实验（E-INF-1）。

**为什么不用 tmpfs 放中间 latent**：在 `--cache-ram` 下，ComfyUI 的中间结果本来就留在进程内存里，不落盘。输出 PNG 每张约 1.3 MB，写 NVMe 不是瓶颈，所以 tmpfs 没有可测的收益，没有做。

### 滚动重启（一次一道，没有打断正在跑的任务）

IMGGEN 加了暂停开关：`control.json` 的 `hold_lanes`。流程是：挂住一道，等它的 `/queue` 清空，重启，等 `/system_stats` 能访问，然后解除，换下一道。

| 道 | 清空时间（TST） | 重启后恢复用时 |
|---|---|---|
| gpu36:2 | 22:28:33 | 9 s（pid 427752 → 475532） |
| gpu33:0 | 22:30:16 | 16 s |
| gpu36:0 | 22:30:37 | 15 s（394208 → 478355） |
| gpu36:1 | 22:32:22 | 19 s（381187 → 484050） |
| gpu33:1 | 22:33:47 | 15 s |
| gpu33:3 | 22:35:06 | 26 s |

**这次的教训**：“队列空”不等于“结果已取回”。ComfyUI 的 `/history` 只存在进程内存里。gpu36:1 和 gpu33:3 各有 1 张图已经出完，但 IMGGEN 的取回线程还没把它拉走，进程就重启了，结果 22:50 被判为 LOST 并重出。这两张原图仍在服务器 output 目录里，浪费了约 2 × 45 s GPU。规则见 K-OPS-I04：重启前要等提交方的未取回数也为 0。

另外，gpu36 上 `comfy.sh` 和 `lane.sh` 的 PID 文件原本都已过期（记的是 122601、137510、179464，实际是 394208、381187、427752）。我先按端口加 venv 路径核对过，再改写成正确的 PID，然后才重启。

## 3. 前后对比

| 指标 | 改动前 | 改动后 | 来源 |
|---|---|---|---|
| 首帧单张执行时间（中位数） | 41–46 s；gpu36:2 100–116 s | 42–44 s，**六道一致**；gpu36:2 降到 43.9 s，**快 2.4 倍** | ComfyUI `/history` |
| 设定图（gpu36:2） | 635–650 s | 预计 150–190 s，与其他道相同（这批设定图在重启前已出完，没有实测） | 同上 |
| 进程冷启动后第一张首帧（含载模型） | 设定图 136–330 s（冷启动 + 冷盘） | 43–48 s（权重已锁在内存里） | 同上 |
| 换模型：读 21 GB 视频 DiT | 冷盘约 1.3–1.5 GB/s：fl2va + ref2va + 32b TE 共 48 GB 约 35 s；半冷的 fl2va 8.0 s | 已锁：21 GB 只要 2.0–2.2 s（约 10 GB/s） | `lock33.log`、`cat` 计时 |
| 道内两张之间的空隙（重启后、有活时） | 中位数 0.3–0.9 s；隧道取回慢时一次能空 17 s 以上 | 中位数 0.2–0.3 s（IMGGEN 改成按服务器队列补交、独立线程取回） | `hist_stats.py` |
| GPU 忙碌占比（有活的窗口） | 道利用率 0.57–0.67（IMGGEN）；gpu33:3 39%，gpu36:1 64% | gpu36:0 98%，gpu33:0 79%，gpu36:2 78%，gpu33:3 70%，gpu33:1 67%，gpu36:1 55% | `hist_stats.py` |
| GPU 平均利用率（采样器） | gpu33 38–47%；gpu36 13–44% | gpu33 45–51%；gpu36 33–36% | `util.csv`，见注 |
| 内存：不可回收部分（总量 − available） | gpu33 103 GB；gpu36 83 GB | gpu33 156 GB（其中锁住 141–151 GB）；gpu36 111 GB（锁住 96–101 GB） | `util.csv` |
| 内存：物理占用（总量 − free） | gpu33 355 GB（71%）；gpu36 160 GB（36%） | gpu33 392 GB（78%）；gpu36 149 GB（34%）；两台合计 541/943 GB（57%） | `free -g` |

注：采样器的“改动后”窗口（22:36–22:48）正好是这批图的收尾。80 镜里已出 78 镜，剩下的都是换 seed 重出，6 道经常没活可派，所以 GPU 平均利用率偏低是**缺活**，不是环境问题。看“有活时”的执行时间和空隙这两行更准。

### 内存为什么还没到 80–90%

- **ComfyUI 吃多少内存由作业决定**：只出图时，各进程 RSS 只有约 3 GB（权重走 mmap，计在页缓存里）。到视频阶段，Ref2VA/PDD 的权重、32b 文本编码、解码帧和缓存的中间结果会把进程撑大。上限已经放开到约 80–87%（见上面的门槛），并有 memguard 兜底。
- **gpu36 的模型目录只有 97 GB，已经全部锁住**，再锁也没有东西可锁。要让 gpu36 也用到 80%，有意义的做法是把 gpu33 上视频阶段要用、gpu36 却没有的权重拷过来并锁住：
  - `minimax_h3_ref2va_pruned_int8_convrot`，21 GB，两人 Ref2VA 配方必需；
  - `qwen3vl_32b_minimax_h3_int8_convrot`，27 GB；
  - `Motion_Repair_V2`；
  - 潜空间放大 bf16。

  反过来，gpu33 缺 PDD 精修用的 `minimax_h3_latent_upscaler_3d_conv_v1_fp16`。两台之间走内网拷，需要用笔记本 ssh-agent 转发（之前 `xfer_models.sh` 就是这么做的），而笔记本的 agent 目前没有加载私钥。**已解决（23:00）**：总调度定为每台从原始来源下载，不走 ssh -A，见下面“权重补齐”。

### 权重补齐（23:00，总调度批准：从原始来源下载，不经 ssh -A 中转）

| 机器 | 文件 | 来源（固定版本） | sha256（HF LFS = 另一台现有 = 下载，三方一致） |
|---|---|---|---|
| gpu36 | minimax_h3_ref2va_pruned_int8_convrot（20.97 GB） | Comfy-Org/MiniMax-H3 @912b6e38 | 9255f52b…5779 |
| gpu36 | Motion_Repair_V2（155 MB） | JOKER141/MiniMax-H3-General-Motion-Continuity-Repair @1676b352 | edfa0e28…7574 |
| gpu33 | minimax_h3_latent_upscaler_3d_conv_v1_fp16（691 MB） | LBH-123-AI/Minimax_h3_latent_Upscaler @3f941d5d | 043e5a48…55c2 |

- 走机房代理 10.0.0.101:7190 下载，21 GB 约 5 分钟。下载脚本是 `ns-infra/dl.sh`，代理只写在命令里。
- 三个 ComfyUI 实例的 `/object_info` 都已列出新文件。
- 补齐后重锁：gpu36 现在锁 124.8 GB，gpu33 锁 151.6 GB，两台合计锁 276 GB。
- 许可已登记在 `docs/ep02_iter/workflow_library.md`。
- 三个文件都找到了公开来源，没有找不到来源的。
- 单纯为了把数字凑满而去占内存，比如开 tmpfs 填空数据，不会更快，反而挤掉了视频阶段需要的余量，所以不做。

## 4. CPU 侧并行与“编排搬到服务器”

- 质检打分（ArcFace、景别、OCR）已由 IMGGEN 改成在出图机器上原地打分：gpu33 读自己的 output 目录，gpu36 也一样，各用自己的 `venv_idm`，图不再经过笔记本。
- 编排器搬到服务器：总调度同意“两台各管各”，跨机 key 不开。
  - INFRA 已备好 `tools/series10_imggen/server_deploy.py`：`push`、`check`、`start`、`stop`、`status`、`control`。服务器上用仓库镜像目录 `/root/work/fredw/imggen_srv/`。
  - `check` 演练两台都通过：`import imggen` 能读到 80 个首帧作业和 24 个设定图作业；本机 `/queue` 0.7 ms（走隧道是 0.9–3 s）；打分环境正常。
  - 笔记本端用 `tools/series10_imggen/sync_thumbs.py`：每 60 s 用一条 ssh 加 tar 流，只拉 `state_gpu33.json`、`state_gpu36.json` 和新增缩略图，已实测可用。
  - 切换时间：首帧这批出完以后（约 23:10），由 IMGGEN 改 `imggen.py --lanes local33|local36` 后切换，给视频阶段用。
- gpu36 的 CPU 并行上限按核数一半，24 个并发进程。原因是 SKILL 规定“不同时压满全核和三卡”：三卡在跑时，打分、ffmpeg 等 CPU 任务合计不超过 24 个线程。gpu33 没有这条限制，但也留出一半给 ComfyUI 的 CPU 侧解码。

## 5. 回滚

- gpu33：`rm /etc/systemd/system/ns-comfy@.service.d/10-infra-ram.conf && systemctl daemon-reload`，然后在队列空时逐道 `systemctl restart ns-comfy@<inst>`。
- gpu36：用 `comfy/comfy.sh.bak-20261031-infra` 和 `longshot/lane.sh.bak-20261031-infra` 覆盖回去，再在队列空时重启。
- 解锁内存：`kill $(cat /root/work/fredw/ns-infra/lock.pid)`。停保护：`kill $(cat .../memguard.pid)`。停采样：`kill $(cat .../sampler.pid)`。
