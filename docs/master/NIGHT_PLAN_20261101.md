# 夜间 RSI 计划 2026-11-01 → 11-02（总调度 fredw-2b）

> 项目方原话（11-01 约 16:35，睡前）：“现在你rsi整个系统,我睡觉,你先review我们讨论重点,再出plan,然后再rsi修复我们的问题”
> 前提：docs/ITERATION_PROTOCOL.md §G0 全局决策原则（K-OPS-D02）。每项先扫已有部件和旧决定，修根因，决定后全量同步。
> 来源：今天的对话；docs/REQUIREMENTS.md R11-1…R11-14；docs/master/MASTER_PICTURE.md §4 缺口表 G1–G19；docs/rsi/DEFECT_HUNT.md。

## 1. 今天讨论的重点（项目方原话 → 问题）

| # | 原话（摘） | 问题本质 |
|---|---|---|
| D1 | “ep01_v2 问题很多……不连贯,眼睛也对着镜头” | 成片内容缺陷：看镜头、摆拍、跨镜服装 / 发色不连贯；现有闸门对此是盲的 |
| D2 | “启动图像识别模型,然后自动检测,一旦发现不对,叫系统重写做” | 本地 VLM 闭环（R11-4/5/10）已建好但只记录 → 转成拦截 + 自动重出 |
| D3 | “image做出来后,用本地图像模型去检测图片是否达标……然后再跑视频rendering” | 顺序：图片闸门先于视频；视频只给过了看图检查的首帧派单 |
| D4 | “pika的模型下载好了吗?”→ 选“改用 Pika Flex” | series10 配方仍是 i2va_pdd2，改为 Pika Flex（保留泛红防护） |
| D5 | “图片是不是用flux现在?” | 不是，是 Qwen-Image 2.1；R11-12/13 真人写实调参研究仍是“待做” |
| D6 | “千万不要补补修修……一旦决定了,其它sub-tasks related都要改一下” | 已落 §G0 + K-OPS-D02 + decision_propagation.py |
| D7 | “s5等视频出来很糊……估计你的参数坏了” | 合成用了 540×960 / 313 kbps 代理再拉伸；原片没同步；预览不放大 |
| D8 | “gpu3和gpu6连不上?” | 笔记本隧道 18188 卡死、18189 断开，没有自动重连；GPU 空转无人报警 |
| D9 | “笔记本关闭后重启工作” | 合盖后所有 loop 断，靠人工恢复；服务器不会自己继续 |
| — | （总调度发现）redo_candidate 等总调度复核 | 人工复核成了瓶颈：总调度不在线，GPU 就空着 |
| — | （总调度发现）ep05-S3/S5 手部大特写驳回 8 次 | 构图 / 参考槽根因未修，一直靠换种子 |
| — | （总调度发现）ep04 合成失败：TTS | G1/G2 音色缺口：series10 角色没有新音色，阿岚无音色 |

## 2. 工作流（按影响排序，每项一个负责 loop）

| W | 内容 | 根因 / 已有部件 | 负责 | 完成标准（done_when） | 核验 |
|---|---|---|---|---|---|
| W1 | 看图闸门：首帧 / 尾帧先过本地 VLM（契约 Q1–Q9 + 视线 + 跨镜连贯 + 景别），不过自动重出；视频只派闸门通过的帧；替换版自动复核，代替总调度人工复核 | 复用 ns_agent/vqa 闭环，开 enforce；rubric 补跨镜连贯 / 看镜头 / 摆拍 | VQAGATE | 80 镜首帧全扫完；拦截项有召回 / 误报数；ep01 点名镜头被拦并进入重出；producer 不再出现“等总调度复核”卡住 | 总调度抽 10 张亲看 |
| W2 | 视频层拦截：score_clip 的 vlm / acting 转 gate.fails，命中自动重出 | 同 W1，在图片闸门之后做 | VQAGATE | ep01 命中镜头重出、复检通过或标尽力 | 总调度看重出片 |
| W3 | series10 改用 Pika Flex | 复用 dialogue_closeup_pika / pika_flex 参数 / flush_risk | WORKFLOW | recipe_choice 指向 Pika；冒烟一镜出片 + 打分走通；K-REN-002/301 同步 | 总调度看冒烟片 |
| W4 | 清晰度：合成用原片，同步原片，预览加 SeedVR2 放大（兜底 lanczos+锐化）；代理码率参数查错 | night.py 258–263 用 proxy；clips/ 不存在；SOP §12 只放大定稿片 | PROD | ep01 重合成；1:1 对比图；规则：成片输入分辨率 ≥ 原片 | 总调度看对比图 |
| W5 | 局部大特写根因（手部特写出成人像、发色丢失） | 对比 ep10-S8 v8 成功 vs ep05-S3/S5 失败的提示词 / 参考槽 | PROD（编译器若属 REFLOCK 则交方案） | ep05-S3/S5 一次出对；规则进 CONSIST / GEN_CONTRACT | 总调度看图 |
| W6 | 音色缺口 G1/G2/G9 → ep04 等合成的 TTS 失败 | L-078 已定“系统按 QAg 方法自动选，不让项目方挑”；voices.json 缺 series10 | VOICE10（新派） | 4 位角色有音色；voices.json series=series10_v1；ep04 合成成功 | 总调度听抽样 |
| W7 | 基础设施韧性：隧道看门狗自动重连；GPU 空转 / night 卡住报警；合盖时服务器自动接管（离线模式自动化），开盖自动并回 | ops/autostart/tunnel.sh、laptop_autostart.ps1、ops/offline/* 已有，靠人工 | WORKFLOW | 隧道断 ≤2 分钟自动恢复（注入测试）；空转 >10 分钟写报警（⤴ 16:55 由 20 改 10）；⤴ 16:55 改为服务器常驻为默认（K-OPS-W07：resident_sync push / restart / pull / loop），笔记本只做控制面 | 注入测试 data/qa/infra_inject.jsonl（freeze 109.4 s / kill 42.6 s）；WORKFLOW 报告 |
| W8 | 规则系统：R11-11 缺陷猎捕、148 条无检查规则补检查、过期口径扫描（decision_propagation） | DEFECT_HUNT 59 类已建 | RSI | 新规则都有 check；过期口径残留 0 | iter_gate RSI |
| W9 | R11-12/13 真人写实调参研究（Qwen-Image 2.1 社区参数、LoRA、采样），检测剧本提示词是否符合 | 状态“待做” | RESEARCH（新派） | 研究报告带出处与置信度；可落地参数做小 A/B；规则进 knowledge | 总调度看 A/B 页 |
| W11 | 视频问题深研与根治（项目方 16:45：“现在视频那边很多问题……也不知道是提示词还是什么,你deep research这些问题,然后rsi下去直到修复好”）：每类问题归因到剧本 / 提示词编译 / 首帧 / 基底 / 采样 / 后期，控制变量实验 + 官方和社区研究，修在系统里，循环直到每类达标 | 已有大量 H3 研究和 A/B（h3_deep、QC_ep02、motion_fix、pika_flex），在它们之上补 | VIDEO-RCA（新派，实验用 gpu36:2 让道） | 每类问题都有根因、证据、修复和前后数字；ep01 问题镜头重出后过打分、过看图闸门、过亲审 | 总调度看 data/review_pages/video_rca/ |
| W10 | 界面 | UIRSI r36（↻ 角标、ASSETUX 文案）+ UIAUDIT 复核 | UIRSI / UIAUDIT | iter_gate UIRSI PASS | UIAUDIT 证据 |

## 3. 顺序与依赖
1. W4（清晰度）、W6（音色）、W7（隧道）不依赖别的，立即并行。
2. W1 → W2：先图片闸门，再视频拦截。W3 的 Pika 冒烟可以并行；Pika 批量重出要等 W1 图片闸门接通，避免拿不合格的首帧去出片。
3. W5 的修法如果改编译器，要先于 W1 对 ep05 的自动重出生效。
4. 所有重出只走 producer / night 现有流程；成片只出预览、不定稿。

## 4. 总调度夜间职责
- AUDIT 不能常驻（子 agent 交报告即结束）：改为按需复核——每当某 loop 交付、或 45 分钟巡检时发现有未复核的交付，总调度用 SendMessage 续派 AUDIT 复核该份交付；iter_gate V1 用它的证据。
- 每个 loop 交报告：按契约亲审（看图 / 看片 / 看数字出处），不过退回；过了就派下一轮。
- 每轮跑 decision_check + decision_propagation，有 ❌ 就派负责方。
- 早上交：docs/overnight/morning_20261102.md + 本地审片入口 data/review_pages/latest/。只放通过亲审的成果；需要项目方决定的用点选题。

## 4a. 全量重做（项目方 18:0x：“图片和视频全部重做一次：1. 图片……用最新的瑞丽 R0 方案。2. 视频：全部用皮卡来做。如果皮卡做不了，就等皮卡安装完再做。”）
- 牵头 WORKFLOW；图片 = 现行 frame_v9 / 徕卡 S★ R0；视频 = 全部 i2va_pika_flex，无 pdd2 回退、无 Ref2VA 兜底，做不了的 hold。
- 前置：G20 身份脸重裁（RSI）→ **SCRIPT 剧本返修导入（SCRIPT-RSI / PROD，18:30 已导入 93 镜）** → G21 作业按导入稿重编（RSI，jobs_vs_import 核对）→ W5 特写编译器（PROD）→ Pika 冒烟亲审 → 全量出图 → 每镜过闸门即派 Pika → 齐集服务器合成。脚本：tools/autopilot/full_redo.py（gate / plan / apply --dry / apply，可续跑；pause / resume），闸门 18:4x 已按总调度登记齐。
- 分工（总调度 18:4x）：出图 = 笔记本 producer（laptop:0 + 跳板通时的服务器出图道），apply 在笔记本本机标 93 个 first 对象（尾帧随首帧换版重做）；视频 = 服务器 night / vidgen（resident_sync video_up：推代码 → 推新首帧 → 本机重编 jobs.json 核非 Pika = 0 → 只起 night）。估算 图片 5.3 + 视频 20.2 = 25.5 GPU 时（data/autopilot/full_redo/plan.json）。
- 旧版本只标过期不删；VIDEO-RCA 实验聚焦 Pika（含泛红）。

## 4b. 跳板恢复后总调度执行清单（16:57 起断网）
1. 确认两台服务器常驻进程（WORKFLOW resident_restart.sh）在跑；GPU 利用率。
2. WORKFLOW 一键：推最新代码 → 常驻热重启 → Pika 冒烟一镜 → 周期并回。
3. `.venv/Scripts/python.exe tools/vqa/after_network.py --push --calib`（VQAGATE：80 镜回扫 / apply / 打开 video_requires_q9 / 标定）。
4. producer `reset-best-effort`（ep01-S6、ep02-S8 等）；笔记本 producer / :8800 是否恢复由常驻模式决定。
5. ep01_v3 服务器合成（PROD + VOICE10 TTS）；ep05-S3 用新编译器重出。
6. 续派 AUDIT 复核 VQAGATE / PROD / WORKFLOW / VOICE10 / RSI r4-r5。

## 5. 不做 / 需要项目方的
- 不删文件、不花钱、不推翻旧决定、不定稿成片、不评价剧本内容。
- 预计没有需要项目方决定的事；遇到会留到早上用点选题问。
