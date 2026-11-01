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
