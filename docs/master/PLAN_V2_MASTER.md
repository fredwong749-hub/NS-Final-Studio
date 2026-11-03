# NS-Final Studio · V2 总计划（PLAN_V2_MASTER）

版本 v3，11-03 04:1x，总调度起草。依据：
- docs/master/OWNER_CANON.md（C-01…C-25）
- V1_TO_V2_CARRYOVER.md
- PIPELINE_SOP_V2.md
- MASTER_PICTURE §1（L-xxx）
- ep01 基线指标

本文是 V2 唯一的计划。改动只能追加修订记录，不另起第二份。


# ★ v4（11-03 05:4x，取代 v3 §7；依据 REVIEW_GLOBAL_OPUS.md + REVIEW_GLOBAL_FABLE.md + V2_SYSTEM_LOSS_AUDIT.md + V1_TO_V2_CARRYOVER.md + OWNER_CANON）

## v4.0 两份审查的共同结论（事实）
- V2 交付 0 首帧 / 0 视频 / 0 成片；V1 生产主干（producer→takes.json→画布→night/vidgen→成片）从未为 V2 启动过；5 条出图道空转 ≥8 h。
- 规则没删、代码没删，丢的是**运行面**和**单一来源**：阶段模型 6 套、"当前剧" 3 个来源、帧账本 3 本、服务器代码 3 份、生产顺序文档 7 份。
- 自 sv-16 以来 282 个未提交改动在常驻进程里跑，没复审没发版。
- 产品面断：没有页面告诉项目方卡在哪；资产页从 14 组件退成 1 个只读文件；剪辑器 / 预览 / 编辑器"到不了"。

## v4.1 阶段一：ep01 按 SOP 端到端做完（唯一优先，代码 agent ≤4）
| 步 | 内容 | 负责 | 退出条件（机器可查） |
|---|---|---|---|
| 1-0 | 282 改动分 5 批由 Fable 复审（写作导入 / 编译闸门 / 视频 / 运维 harness / UI）→ sv-17 cut → deploy → verify --shot 8；服务器三份代码收成一份 | OVERSIGHT-F ×N → SV17-O | 复审无 P0；两台 prompt_sha / 代码 md5 一致 |
| 1-1 | 写作：ep01 整集返修（L-150，进行中）；新增**确定性迁移器**把旧稿镜内 At 改 L-141 写法（不靠 LLM 循环）；补丁满次自动出诊断交总调度 | 派单器 + K211-F + Opus | 导入闸门 strict 全过，imported_sha |
| 1-2 | 资产：祁念 O4 设定图（SH1）走资产作业 → 代选/亲审 | asset_worker | episode_ready = preflight 同口径 0 缺口 |
| 1-3 | 单一来源：sop_gate 成为唯一阶段模型（网页 sop.py、stage_status、步骤条都读它）；"当前剧"只认 runs.json；封掉 wizard.py 绕闸门导入 | Opus | 各页阶段与 master_check 一致 |
| 1-4 | 提示词探针改用 build_first + preflight（不再走 golden_v2） | Opus | 11 镜（除成人镜）preflight 过 |
| 1-5 | 出图并回 V1 主干：停 V1 旧 producer，起 V2 producer/night；golden 的 bundle 验收并进 postflight；帧只记 takes.json 一本账；定稿档（L-147）挂在同一验收后再开 | Opus | 每镜首帧过契约、总调度亲审接触印样签字、代选/项目方选定 |
| 1-6 | 尾帧 → 视频（Q9 先行、≤6s、L-141） | 视频链 | 每镜视频过检 |
| 1-7 | 整集预览 + 整集 BGM + 配音 | 后期 | 本地预览页 |
| 1-8 | RETRO_ep01 机器核对（不靠手勾）→ 记忆 / harness 更新 → 复盘门 done | 总调度 | 复盘门过 |

## v4.2 阶段二：系统收敛（ep01 后、ep02 出图前）
- harness 补全：switch（开关带 L-xxx）、deliver 复审门（cut 前必过）、brief 生成器（L-144）。
- 产品面（L-146）：步骤条 + 进度矩阵（读 sop_gate）；资产页按 V1 14 组件并回；剪辑器 / 整集预览 / 图像编辑器有入口且能跑 ep01；去掉 RejectDialog（L-123）；404 文案不露命令行。
- 工具收敛：14 个顶层模块 + lab/ 隔离区（生产代码不许 import）；约 25 个一次性目录进 lab/；score_remote / hands_remote / debug/lanes 先搬主干。
- 文档治理：顺序只留 PIPELINE_SOP_V2 + sop_gate.STAGES；指标只留 METRICS_SPEC；账本拆"V2 现行 / V1 归档"；REQUIREMENTS.md 归档；GPU 计分改按实测占用。
- 运维：监控 / SENTINEL / watchdog 按剧；计划任务和自启补齐；遗留实验进程清理。

## v4.3 阶段三：ep02 测量集
- 同一套系统跑 ep02，对比 ep01 指标（PLAN §1.3）；L-143 结构化控制逐项 A/B；全部闸门 enforce；发版自动。

## v4.4 阶段四：ep03–ep10 自治
- 总调度只看 master_check + RETRO；每集比上一集好，连续两集不达标就停下专项修。

## v4.5 需要项目方拍板（选择题）
1. 出图路径：并回 V1 producer（推荐，L-137）vs 先桥接登记 golden 图
2. 启停常驻：停 V1 旧 producer、起 V2 producer/night；停服务器遗留实验进程（bench2 3 天、bakeoff 1 天 15 小时）、退役 video10_srv
3. 282 改动先复审发版再出图（推荐）vs 边出图边复审


---

## 0. 现状（只写事实）
- **已完成的集：0。**
  - ep01：剧本已导入，资产已就绪；但剧本时间轴不合格，补丁环仍在跑。首帧、视频、成片都还是 0。
  - ep02：剧本写到 P3，P4 正在由派单器派写手写。
- **ep01 基线**：

  | 指标 | 数值 |
  |---|---|
  | 自动化 | 37.9% |
  | 人工 / agent 介入 | 46 次 |
  | GPU 占用 | 14.1% |
  | 出图一次通过 | 45% |
  | Q1 身份 | 0.822 |
  | 项目方等待 | 125 分钟 |

- **没做完的根因**：
  1. 同时开的线太多，没有一条走到终点。
  2. V2 另起平行工具，V1 的地基没接上：服装、镜头语言、视频链、时间轴 strict 等 6 处 P0。
  3. 规矩靠总调度自觉，没有代码层面的约束（缺 harness）。
  4. 重大决定没先和项目方讨论。
  5. 记忆分散、过时，开工前没对照。

## 1. 目标与验收标准

### 1.1 终局（C-01 / C-15）
- 新剧本从 P0 到成片全自动，不靠 Claude 驱动。
- 故事达到好莱坞水平。
- 画面接近实拍：时尚大片、4K 质感、徕卡式锐利。
- 一致性、成功率、质感都接近 95%。
- 产品体验对标小云雀。

### 1.2 一集算“做完”的定义（DoD，缺一项就不算完）
1. P1→P4 全部通过 strict 闸门：
   - 时间轴：H3 的 At 只用在切镜处，镜内用自然语言写时间顺序（L-141）；
   - 单镜 ≤ 6 s；
   - 不看镜头；
   - 无字幕；
   - 没有 V1 泄漏。
2. 资产全部登记：身份脸、造型设定图、单品、场景、音色。
3. 每个非成人镜头的**首帧和尾帧**都通过契约（Q1 身份、Q9 看图、anomaly、服装、人数、手部），而且经过总调度亲审。
4. 每个镜头的**视频**都在过 Q9 之后才出，并通过视频检查。
5. **整集预览**：拼接、整集 BGM（L-118）、配音，放在本地审片页。
6. **成人镜头**：在 DoD 里标为“待项目方触发”，不算阻断。
7. **本集复盘** RETRO_epNN 写完；记忆和 harness 已更新；指标已入账。

### 1.3 每集指标目标（每一集都要比上一集好，退步就修 pipeline）

| 指标 | ep01 基线 | ep02 目标 | ep03+ 目标 | 终局 |
|---|---|---|---|---|
| 自动化比例 | 37.9% | ≥ 60% | ≥ 80% | ≥ 95% |
| agent / 总调度手工介入 | 46 | ≤ 20 | ≤ 8 | ≈ 0 |
| 出图一次通过率 | 45% | ≥ 60% | ≥ 75% | ≥ 90% |
| Q1 身份均值 | 0.822 | ≥ 0.83 | ≥ 0.85 | 稳定 |
| GPU 占用（生产时段） | 14% | ≥ 40% | ≥ 60% | ≥ 70% |
| 好莱坞质感分（本地 VLM，1–10） | 未测 | 建立基线 | +0.5/集 | ≥ 8.5 |
| 项目方等待时间 | 125 min | 只在 #/queue 一次性点选 | — | 只做创作选择 |

## 2. 系统架构：V1 是地基，V2 在上面加东西

**原则（C-14、L-137）**：V2 只换内容（剧本、人物、资产、场景）。技术层一律用 V1 的部件，加上按剧参数（run）。不许另起平行实现。

| 层 | V1 地基（主干，必须生效） | V2 增量（在地基上加） |
|---|---|---|
| 写作 | knowledge→writer_knowledge、script_chat_rules（sysimpl-v2）、QW/RL/SL lint、PERFORMANCE_RULES、三评委、FACTCHECK、补丁环 | 按剧全局头（HEADER-O）、V1 守卫 assert_no_v1、多集流水（EPCHAIN-O）、无头派单器（L-138） |
| 资产 | manifest 和 sha、asset_refs 槽位、verified_install 推两台 | 资产作业 + inbox pick 登记、代选（L-136/L-139） |
| 编译 | 唯一入口 compiler/build_first、shot_spec_v2 镜头语言、L-110 融合、L-111 灯光、风格后缀、I7 禁用词、种子流 | 按剧 bible、清单造型槽位 |
| 出图与检测 | GEN_CONTRACT preflight/postflight、Q1/Q1a、Q9（vqa.json）、anomaly、producer/night 调度、lanes 借道、partition | vlm_pool 多实例分流（待并入 vqa client）、按镜动态 check_items |
| 视频 | H3（Pika Flex 默认基底）、recipes、camera_moves（A/B 测过才启用）、≤6 s、视频前必须过 Q9 | bolt_push_settle 等 V2 运镜（L-129）、At 只标切镜（L-141） |
| 后期 | 整集 BGM、配音、拼接预览、CUTEDIT | music_v2 / voices_v2 |
| 运维 | resident 单一推进入口、system_version cut/deploy/verify、SENTINEL、SLO、restart_api（detach） | episode_metrics、hollywood_tick |
| UI | 一镜一行画布、“用这张”+“修改”、只显示通过的、一键确认 | #/queue 通知中心、代选横幅 |

**并回规则**：V2 新写的东西，有用的就并进对应的 V1 部件，没用的退役并隔离。GOLDEN-O 已经交了“可以并入的清单”：种子多道并行进 producer，retry 三态进 postflight，vlm_pool 进 vqa client，bundle 进 postflight。

## 3. 生产 SOP：每集 10 个阶段，每个阶段都有通过证据，由 sop_gate 强制

| # | 阶段 | 通过证据（机器可查） | 谁做 | 项目方介入 |
|---|---|---|---|---|
| 1 | 剧本 P1–P4 | 每段 report 0 阻断；评委分数达到门槛 | 派单器（Fable 写，Sonnet 评） | P1 方向（创作），其余不介入 |
| 2 | 导入闸门 | strict lint 全过；assert_no_v1 0 命中；imported_sha | resident→autoflow | 无 |
| 3 | 资产就绪 | episode_ready 全部就绪 | 资产作业 + #/queue | 挑新的脸、场景、音色（创作） |
| 4 | 提示词 | 每镜 compile 成功，preflight I1–I13 全过；两台 prompt_sha 一致 | 编译入口 | 无 |
| 5 | 出图 | 每镜候选数 ≥ N | producer/night + lanes | 无 |
| 6 | 出图检测 | postflight 全过（Q1/Q9/anomaly/服装/人数）；不过的自动重出，最多 N 次 | 检测闸门 | 无 |
| 7 | 亲审 + 选首帧 | 总调度接触印样签字（master_review）；#/queue 选定，或代选 | 总调度 → 项目方 | “用这张”或“修改” |
| 8 | 尾帧 → 视频 | Q9 已过才放行；视频检查过；单镜 ≤ 6 s | H3 recipes | 无 |
| 9 | 整集预览 | 拼接 + BGM + 配音，生成本地页面 | 后期 | 看整集，“修改” |
| 10 | 复盘 | RETRO_epNN done；指标入账；记忆和 harness 已更新 | 总调度 | 无 |

**硬规则**：
- 阶段不许跳，也不许抢跑：整集就绪才出图（L-140），先出完图再出视频（C-16）。
- 写作可以跨集并行，ep N+1 的写作不受 ep N 出图的限制。但 ep N 的 RETRO 没写完，ep N+1 不准进入出图阶段。

## 4. 控制平面（harness）：把规矩做成代码
| 部件 | 作用 | 状态 |
|---|---|---|
| sop_gate | 第 3 节的阶段闸门。出图、视频的入口开头先 require，没过就报错 | HARNESS-O 在做 |
| master_check | 一页巡检：每集阶段、卡点和负责人、未复审交付、开关与决策是否一致、心跳、GPU | HARNESS-O 在做 |
| episode_retro | 复盘生成 + 复盘门 | HARNESS-O 在做 |
| switch | 开关只能带 L-xxx 修改，直接改文件就报警 | ep01 完成后做 |
| deliver + 复审门 | 每次交付登记；cut 时缺复审就拒绝 | ep01 完成后做（这期间复审靠人工派 Fable） |
| brief | 派单模板自动附上 SOP、已有部件、定律、约束、锁 | ep01 完成后做 |
| 记忆协议 | 总纲（core）+ 部件清单 + OWNER_CANON 三件套；每次 RETRO 后压缩更新 | 已重建（11-03 03:3x） |

## 5. 迭代节奏：每一集是一次系统迭代
- **ep01（金样集）**：总调度全程盯。目标是把 SOP 10 个阶段第一次完整走通，把 V1 地基全部接上。卡点全部登记进 SOP 和代码。
- **ep02（测量集）**：同一套系统跑，核心是减少介入。按第 1.3 节逐项和 ep01 对比，退步的项立项修。
- **ep03–ep10（自治集）**：总调度只看 master_check 和 RETRO，异常才介入。每集都必须比上一集好；连续两集不达标，就停下来做专项修复。
- 每集收尾：发 system_version，跑 RETRO，压缩记忆。

## 6. 分工与模型（C-18）
- **总调度（Opus）**：只做编排、决策、亲审，不写代码。派单都用 brief 模板。
- **写剧本**：Fable（派单器）。评审：Sonnet。P1 评委：多模型。
- **写代码**：先给 Fable；难的给 Opus；Opus 的交付一律由 Fable 复审（OVERSIGHT）。
- 同时在跑的代码 agent 不超过 4 个，每个都必须挂在关键路径上。

## 7. 立即执行：ep01 关键路径（第 3 节阶段 2→10）
| 序 | 事项 | 负责 | 退出条件 |
|---|---|---|---|
| 1 | 补丁环集头冲突（I2 和 regen_header 打架）+ L-141 写法 | TIMELINE-O | patch 被收下，重新导入，strict 全过 |
| 2 | 编译 P0：近景服装、三人镜每人一张脸、shot_spec_v2、L-110、L-111、负面词、sheet 视线 | MERGE-IMG-O | S1/S8/S9 编译对比通过，preflight 过 |
| 3 | 视频链按剧：Q9 先于视频、运镜 run、≤6 s block、BGM 按剧 | MERGE-VID-O | ep01 S8 视频提示词验证通过 |
| 4 | 账本补 L-127、L-129…L-141；import 守卫；repart/dispatch 按剧 | MERGE-OPS-O | decision_check 过；V2 可以派单 |
| 5 | sop_gate + master_check + retro | HARNESS-O | ep01 判在“提示词”阶段 |
| 6 | Fable 复审 1–5 的全部改动，以及今晚未复审的交付 | OVERSIGHT-F | 无 P0 |
| 7 | sv-17 cut → deploy → verify --shot 8 | SV17-O | 两台一致 |
| 8 | 出图 → 检测 → 亲审 → #/queue | producer + 总调度 | 10 个非成人镜头首帧通过 |
| 9 | 尾帧 → 视频 → 预览 | 视频链 | 整集预览页 |
| 10 | RETRO_ep01 → 记忆 / harness 更新 → ep02 进入出图 | 总调度 | 复盘门过 |

## 8. 风险和对应检查（根因模式 → harness）
| 风险 | 对应措施 |
|---|---|
| 双入口 / 平行实现 | 第 2 节并回规则；brief 自动附已有部件 |
| 两台编译不一致 | verify 核 prompt_sha |
| 不送脸 | preflight I2；每人一张脸 |
| 失败图外露 | 只展示通过的；Q9 |
| 规则写了没生效 | strict；CARRYOVER 每集验收 |
| 线上动作没审 | 复审后才重启；restart_api detach |
| 重大决定没讨论 | 记忆 ⭐⭐；switch 带 L-xxx |
| 线太多 | 代码 agent ≤ 4，必须挂关键路径 |
| token 浪费 | 上下文控制在 250k 以内；巡检只跑 master_check |

## 9. 需要项目方拍板（会在对话里用选择题问）
1. ep01 首帧怎么定：项目方在 #/queue 亲自选，还是继续代选（L-136 在他下一次网页操作时会自动到期）。
2. IMGLAB 结构化控制（ControlNet pose/depth、FaceDetailer/HandDetailer、PuLID、IC-Light）：在 ep01 就上，还是 ep01 先用现有链路走通、从 ep02 起逐项 A/B 上线。
3. harness 剩下的部件（switch、deliver 复审门、brief）：在 ep01 出图前做完，还是 ep01 完成后再做。

## 修订记录
- v1（04:0x）：初稿，按“目标→SOP→ep01 待办”。自查问题：没有一集“做完”的定义，没有量化目标，没有并回规则。
- v2：加入 DoD、指标表、V1 地基/V2 增量对照表。自查问题：harness 和 SOP 没对上，没写写作并行和出图串行的边界，线太多的风险没有约束。
- v3：加入阶段证据表（sop_gate 按它实现）、复盘门、代码 agent ≤ 4、待拍板事项。
- v3 定稿（04:2x）项目方点选：①ep01 首帧系统代选、事后可改（L-142）；②结构化控制从 ep02 起逐项 A/B 上线（L-143）；③harness 余下三件 ep01 完成后做（L-144）。
- v4.1（11-03 11:10，总调度 MASTER-WSL，依据 L-160 全权授权）：今日执行序 = ①G2–G7 复审收齐（G2 ✅）→ ②拼树 cut B（sv-20261103-02）→ ③deploy --verify 两台 → ④按 L-152：停笔记本旧 V1 producer、起 V2 producer/night、停 bench2/bakeoff 实验、退役 video10_srv（只停不删）→ ⑤ep01 出图→检测→首帧系统代选（L-142）+总调度亲审→尾帧→视频→整集预览→RETRO_ep01 → ⑥ep02 整集返修（L-158/159）跟进。期间 CODER-PS 做 UI 溢出/409/GPU 卡死自愈/b589 残留。
