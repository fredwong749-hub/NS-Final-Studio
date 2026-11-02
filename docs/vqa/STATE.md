# VQA 会话可恢复状态（VQA，fredw-92 子会话；2026-11-01）

范围：R11-4 / R11-5 / R11-7 / R11-10（docs/REQUIREMENTS.md，状态已更新为 ⚠）。硬规则 K-REV-V01：图片 / 帧只进本地视觉模型（gpu36 自建服务），**绝不发外部 API**；写作网关只收文字。

## 决定
- 本地看图模型：**Qwen3-VL-8B-Instruct**（Apache-2.0，https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct），bitsandbytes nf4（视觉塔与 lm_head 不量化），gpu36 GPU0/1 让道模式。32B INT4 约 18 GB，要整卡，现在没有空卡，所以不选。
- 4K：沿用 gpu33 上已有的 SeedVR2 3B 阶段（/root/claude-kimi-ns-studio-v1/ns-studio/scripts/upscale_4k.py；本机入口 services/post/ns_post/upscale4k.py）。

## 已完成
- **部署**：gpu36 /root/work/fredw/vqa。
  - 组成：venv（torch 2.11 cu128、transformers 5.22.1、bnb 0.50.2）、模型、nf4 存档、server.py（127.0.0.1:8870）、start.sh（幂等启动）。
  - 冒烟测试：加载 16.7 s，单图 5.7 s，峰值显存 6.5 GB。
  - 让道方式：ComfyUI 队列空 ≥20 s 且显存余 ≥7000 MiB 才加载；来活立刻卸载；空闲 90 s 也卸载；绝不 /free 别人的 ComfyUI。
- **代码**：services/agent/ns_agent/vqa/{__init__,rubric,client,contract,judge}.py；tools/vqa/{server,calibrate,recurring,script_lint}.py。
- **配置**：
  - config/vqa.json：22 项出图检查 + 5 项视频检查，每项对应一条契约项；judge.enforce=true + gate 段（项目方 11-01 16:10 原话转拦截，D-VQA-01）；24 项出图检查（新增 continuity_break、posed_stiff）；upscale_4k 段。
  - 提示词：config/prompts/vqa_inspect.md、vqa_judge.md。
- **规则与测试**：knowledge/rules/vqa.yaml（K-REV-V01…V04、K-REN-V05、K-WRT-V06、K-EDT-V07）；tests/test_vqa.py 17 项全过。
- **SOP**：docs/SOP_production.md §8（Q9 + R11-10 闭环）、§9（V9）、§12（4K 只做已批准片）。
- **接入**（三方都由 owner 自己改完）：
  - REFLOCK：postflight 加了 Q9 / V9。转拦截后：没有看图结果 = untested（挡），blocking 项 defect = fail；笔记本路径没缓存时现场看图（postflight._q9_live）。
  - VIDEO10：score_clip 加了 v9_vlm → score["vlm"]，还没推到服务器。
  - PRODUCER：_postflight 先过 vqa_gate（命中就重出，不设为当前），review_round 写 take.params.vqa_rounds（mode=enforce），下一版套用 prompt_delta；要等笔记本 producer 重启后生效。
- **LOCKS**：已在 docs/uimaster/LOCKS.md 登记 VQA 的文件。ownership.yaml 归 ITERAUDIT，要请总调度加 VQA 一行。

## 进行中
1. **标定集同步**：
   - 只同步压缩版：JPEG，主图 ≤1.3 MP，扩展名不变，37 MB，分 12 块，每块 3 MB。
   - 本机暂存在 /tmp/vs_part_*（Git Bash /tmp），传到 gpu36:/root/work/fredw/vqa/xfer/。
   - 中转（sz194）很不稳，经常被 reset。
   - 收齐后在 gpu36 执行：
     `cd /root/work/fredw/vqa/xfer && cat vs_part_* > s.tgz && mkdir -p ../repo && tar -xzf s.tgz -C ../repo && cd ../repo && setsid nohup ../venv/bin/python tools/vqa/calibrate.py run > ../logs/calib.log 2>&1 &`
   - 跑完：`../venv/bin/python tools/vqa/calibrate.py score` → data/vqa/calibration/report.json / report.md，拉回本机同名目录。
2. **4K 实测**：
   - 在 gpu33 /root/work/fredw/vqa4k/run.sh（nohup，timeout 1 h）跑：`upscale_4k.py shot ep03-S4_49f.mp4 --gpu 3 --allow-idle`。
   - 片段：49 帧，原片 360×640 预览，放大 6 倍到 2160×3840。
   - 脚本自己等 GPU3 队列空 60 s 再 /free 接手；22:21 起在等卡。
   - 结果在 out/ep03-S4_49f.4k.json（timings、VRAM）、out/*_qc/、run.log。
   - 1 小时内没轮到就会超时退出，下次在空闲窗口重跑 run.sh。

## 标定集（data/vqa/calibration/set.json，174 个样本，全部是总调度给的标签）
- 场景对：59。
- 手正常：31。没有“多手”的正例，所以多手这一项不能转阻断（K-REV-V03 要求正反例都有）。
- 塑料感：13 不合格 / 36 合格。
- 鞋：7 不合格 / 7 合格（参考鞋 LW-S01）。
- 服装：5 不合格 / 7 合格。
- 身份：2 不合格 / 3 合格。
- 景别：3 不合格 / 1 合格。
- 发型：5 张（顾沉长发）。
- 多人：2 张（双林晚）。
- 穿着状态：1 张（光膀子）。
- 文字：4 张无文字。

## 恢复办法
- 服务：`ssh gpu36 /root/work/fredw/vqa/start.sh`；`curl 127.0.0.1:8870/health`。
- 离线期间（OFFLINE_20261101）生效的数据在 gpu33 / gpu36 的副本上。看图结果要写进副本里的 data/vqa/，postflight 的 cached_for 才查得到（REFLOCK 提醒）。

## VQAGATE（fredw-2b 派，2026-11-01 16:10 起）：转拦截，闸门先于视频
- 项目方原话（D-VQA-01 / L-080 / L-081）：“启动图像识别模型,然后自动检测,一旦发现不对,叫系统重写做”“image做出来后,用本地图像模型去检测图片是否达标……然后再跑视频rendering”。取代 K-REV-V03 的旧前提（等标定门槛和总调度批准）。
- 口径：config/vqa.json gate.enforce=true、judge.enforce=true；只拦 defect 且该项 blocking=true（高置信），unsure 只记录；没看图 = untested（挡）。blocking 名单按 docs/vqa/GATE_CALIBRATION.md。
- 接线：postflight Q9（_q9_item / _q9_live）；PRODUCER _postflight → vqa_gate → contract.apply；producer.vqa_delta 下一版套 prompt_delta；驳回替换版自动复核 auto_review_redo / note_auto_reject（G0）；build_jobs.passed_frames 只认 Q9 通过（gate.video_requires_q9）。
- 跨镜连贯：ns_agent/vqa/continuity.py（同 scene_id 上一镜当前首帧 / 尾帧对本镜首帧）。
- 回扫：tools/vqa/gate_scan.py scan | apply | redo（写回走 rescore_takes.write_back，PRODUCER reconcile_demoted 自动重出）。
- 截断修复：max_new_tokens 1800、紧凑 JSON、rubric._salvage 按项抢救（ep01 首扫 7 张 3 张截断）；ssh 管道先缩图再发（client._shrink）。
- 服务：主力迁笔记本 RTX 4080 Laptop（D:\ns_vqa 独立 venv），client 先连本机 127.0.0.1:8870，连不上走 ssh gpu36。

## VQAGATE 待办（VIDEO-RCA r1 发现，总调度 19:1x 转；必须在打开 gate.video_requires_q9 之前处理）
1. 视频层判看镜头以看图模型为主。S5_pika 全程在看镜头，像素检测器（ns_qc.gaze / acting.camera_gaze）却报“视线离轴”。改法：score_clip 的看镜头结论按 V9 的 eye_contact / first_frame_stare 和 MediaPipe 高置信度命中取 OR；像素检测器报“离轴”不能作为放行依据，只写进证据。验收：S5_pika 被判看镜头；用 100 张标签加片头 72 条（data/acting/gaze_labels.json）量召回和误报。
2. V6 命中后交看图模型复核，区分“多一只手”和“衣物形变”。VIDEO-RCA 报中全景单人镜 8/8 命中，其中一部分是 Pika 外套形变。改法：v6_limbs 判不过时，抽命中帧交本地看图（问题写成“这是多出来的手 / 手臂，还是衣服、外套的形变”）：是衣物形变 → V6 改判通过，另记 temporal_outfit（服装不连贯，进 V8）；是真多手 → 维持“多肢”。验收：拿 VIDEO-RCA 的 8 条片子人工对照，报改判前后的数字；ep01-S2 mot、S4 s2 两个正例仍然判不过。

## 方案：让道模式下给看图留最短窗口（总调度 20:0x 要求，恢复全量重做时落地；实现交 LOCALGPU 或 VQAGATE）
- 问题：19:34–19:50 实测，laptop:0 出图连续排队时，看图服务每次刚加载完就被 /yield 卸掉，排队的看图请求一条也跑不成；Q9 一直是未测，新图积压。
- 规则（满足任一条就给看图开窗口）：
  1. 每出 N=6 张图；
  2. 看图队列里最老的请求等了 M=8 分钟以上；
  3. 看图积压 ≥ 10 条。
- 窗口内：出图方（ComfyClient）提交前，若看图在窗口期，就不发 /yield，而是等窗口结束；窗口长度 = min(积压条数 × 50 s, 6 分钟)。按口径 B 单条 42–53 s 估算，一个窗口能判 6–8 张。
- 窗口开始时：先对本机 ComfyUI POST /free，再加载看图模型（不然残留显存会把第一次加载挤到共享内存，20:0x 实测出现过）；窗口结束时卸载并 empty_cache。
- 记账：每个窗口写 D:
s_vqa\logs\switch.jsonl（ev=vqa_window：开始 / 结束、判了几条、出图等了多少秒），总调度据此调 N / M。
- 吞吐估算：出图约 60 s 一张时，N=6 意味着每 6 分钟让出约 5 分钟，出图吞吐约降一半。要是太慢，可以把看图放到 gpu36 备用道（隧道通的时候），本机只补判。
- **已实现（20:3x，总调度批参数）**：tools/vqa/server.py 的 maybe_open_window / window_active 与 /yield 等窗口。参数用环境变量 VQA_WIN_N=6、VQA_WIN_WAIT_S=480、VQA_WIN_BACKLOG=10、VQA_WIN_PER_JOB_S=50、VQA_WIN_MAX_S=270（270 小于出图方 yield_timeout_s 300，出图方不会超时报错），VQA_WIN_N=0 关掉。窗口内跳过“空闲 IDLE_S 秒”的等待，显存不够照旧先 /free ComfyUI。开、关窗口都记 switch.jsonl（ev=vqa_window，含 served、draw_waited_s）。comfy_client._yield_peer 没改（CONSENT LOCALGPU → VQAGATE 已登记）。测试 tests/test_vqagate.py::test_vqa_min_window_opens_on_any_condition。
- **吞吐实测：未测。** 要等全量重做恢复、laptop 道连续出图后，跑 `tools/vqa/window_report.py --since <启用时间> --before <启用前一段>`，结果写 data/vqa/window_report.json。现成的“启用前”基线只有 18:30–19:40 的 3 张（2.6 张 / 小时），太少，不能当基线。生效前提：本机看图服务要用新的 server.py 重启（start.ps1 -Restart 会把仓库里的 server.py 拷过去）。

## 机签（master_review autosign）现状 — 2026-11-02 14:xx

- **现在是 manual（人工签），不是测试期。**
  - 11:00 按“只取现行剧本”的口径切到 auto：35 对，一致率 1.0，漏放 0。
  - 12:45 项目方抽检否决 ep04-S10 v6：陈宇在画面里出现两次，人数异常，现行契约测不到这一项。
  - 12:46:26 autosign_spot_check 判为 revert，自动退回人工（data/vqa/autosign_state.json：reverted_at = 2026-11-02T12:46:26）。
- **切回条件**：
  1. detector 的人数检测（DETECT-S anomaly.py）接进契约，并由总调度标定后打开拦截；
  2. 把 ep04-S10 v6 这类“同一人出现两次”加进回归集，重新跑 autosign.py check 评估门槛；
  3. 切回由总调度定。代码层面：退回过人工后，check 即使达标也维持 manual，要总调度确认才会切。
- **测试期抽检**：每 10 张抽 1 张（data/vqa/autosign_spot.jsonl）；误拦记 data/vqa/autosign_false_reject.jsonl。
