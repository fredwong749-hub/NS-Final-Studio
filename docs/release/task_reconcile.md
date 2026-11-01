# 封板对账：任务 / 需求 / 生产问题 / 待决定 / 文档矛盾（task_reconcile）

> 生成：2026-10-30 晚（只读对账，未改任何代码与其它文档）。
> 依据：docs/TASKS.md、REQUIREMENTS.md、WORKFLOW.md、SOP_production.md、CHANGELOG_AGENTS.md（今天的条目，按追加顺序最新在下）、qa_laptop.md、production_issues.md、owner_requirements_for_writer.md、script_chat_rules_audit.md、design/frontend_fix/audit.md、gpu3_health.md、parser_diff.md、qc_gates.md；并只读核对了 data/import/script_v2.json、data/script_chat/、config/adult_overrides.json、config/auto_lora_triggers.json、packages/qc/。
> 今晚的现行事实（以此为准对账）：写作 = gpu3 本地 Qwen（abliteration 因太贵已弃用）；Claude 只做系统与排错，不写也不评判内容；成人判定 = 整集 🔴（逐镜已回退，`config/adult_overrides.json` `per_shot:false`）；成人渲染由项目方本人启动，渲染流水线按设计跳过露骨镜头；笔记本 run_adult_batch 已删除；ep01（🔴）不能经 gpu3 渲染；ep02（非 🔴）是端到端测试集（造型已确认，场景底板仅本次测试豁免）；林晚出图 LoRA lin_wan_qi_v1 已交付并验收；林晚视频 LoRA lnwan01 在 GPU0 的 Qwen 队列中排队；服装 LoRA 排在 ep02 渲染之后；GPU1 = Qwen LLM 常驻；GPU2 坏卡；60 集 Qwen rules_v2 全量重写在跑（1 worker，约 8–15 分钟/集）；规格词由系统自动补到首帧和尾帧（不是透传）。
> 状态取值：**done** 完成｜**in progress** 进行中｜**blocked** 被卡住（写清等什么）｜**obsolete** 已作废／被取代｜**duplicate** 重复。

---

## 0. 摘要

- 任务板 61 个 ID（T01–T60 + T54-B）：**done 30**（其中 14 个还有收尾动作）｜**in progress 9**｜**blocked 13**｜**obsolete 8**｜**duplicate 1**。板面状态与实际不符的 11 个：T16、T17、T19、T27、T28、T34、T46、T48、T53、T55、T58。
- 需求 A1–G8 共 44 条：已落实 20｜部分 20｜未落实 2（B2、B9）｜被取代 2（F2、G8）。REQUIREMENTS.md 的状态列 E 节整体过期（E2/E4/E5/E7/E8 标 ❌ 或 ⚠，实际已做），B1 / B6 / C4 / G8 文字过期。
- 30 条生产问题：**有阻断性自动闸门 6 条**｜部分（只 warn、只在笔记本、没接进 gpu3、或从未在新片上跑过）15 条｜**没有有效闸门 9 条**。
- 待项目方决定：去重后 38 项；今天已答 6 项（Q1、Q9、Q12、时长、规格词、成人整集判定），由今天的决定隐含覆盖 2 项（Q10、Q11，建议请项目方一句确认），仍待决定 30 项。
- 文档矛盾 28 组，其中 8 组直接影响封板（第 5 节标 ★）。

### 封板最关键的缺口（按阻塞程度）

1. **ep02 端到端还走不通**：`data/import/script_v2.json` 里 ep02 仍是 v2 原稿（6 镜全部没有 `h3_prompt`）；rules_v2 的 ep02 稿 3 轮返修后仍 block=1（`data/script_chat/_logs/rules_v2_full.log`、`ep02_repair.log`），目前只在 session.json 里，会话的 `script.md` 只有 ep01；导入必须带 `--merge-base --source-version v3` 才过 S1（CHANGELOG fredw-92 两条）；之后才能 S2 就绪 → GPU3 渲染 → 还卡（gpu3_health §7）。
2. **S3 首尾帧走哪条链没定**：WORKFLOW §2/§4 写“Qwen 写 Image 2.1 提示词并经 :8100 自行调度出图，交 frames.json，Claude 原样用”，今天定的是“系统自动补规格词”（编译器路径，QA4-02）。没有任何代码产出 `frames.json`；画布 S3 导入 / 「请 Qwen 出首尾帧」、S4 H3 执行器读 frames.json（WORKFLOW §5 两个未勾项）都没做。ep02 用哪条链出帧需要先定。
3. **闸门没接进 gpu3**：`packages/qc/ns_qc`（qc_gates.md）只在笔记本跑，gpu3 `weita_series._clip_checks` / `add_take` / `step_a_shot` / `audio_post` / 同步计划任务五个接入点都没改；PI-07“最佳候选失败仍被锁定”（weita_series 900–904 行）仍在；take 没写 `reference_sha / last_target_sha`（PI-08、T52）。
4. **gpu3 不抗重启**：qwen-llm-gpu1、qwen-agent3、qwen-mailbox、qwen-llm-relay、weita-v3-llm-cpu、nsaudio-watch 都是 Transient unit；笔记本隧道守护、同步循环都不自启（gpu3_health §7、PI-24）。
5. **LoRA 注册表镜像不同步**：笔记本 `data/renders_gpu3/LORA_REGISTRY.json` 里 lin_wan_qi_v1 仍是 training、sha256=null，state_timeline 因此给林晚镜头标 `lora:lnwan_qi:training`（QA4-07）；会让 ep02 S2 就绪判不过。
6. **全量重写耗时**：剩 58 集 × 8–15 分钟 ≈ 8–15 小时（单 worker），之后每集还要 G3 采纳 + 导入；当前在写 ep03。
7. **4K 不可用**：`up4k-test` failed，无人跟进（gpu3_health §2）；D5 依赖它。
8. **资产与 LoRA 的内容侧大多未启动**：T10–T13（妆容、多角度底板、单品、男主候选）Qwen 待办；饰品 / 姿势 LoRA 已停（nprng2、lbrng9、pose_* 触发词出图时会被剥掉）；服装 LoRA 排在 ep02 后。
9. **写作规则母本自相矛盾**：owner_requirements_for_writer.md（rules_v2 母本）仍写“尾帧规格词由写作者自己写、系统不追加”和“非亲密镜 ≤2 位说话人”，与今天的决定冲突；config/script_chat_rules.md 已按新决定改（CHANGELOG fredw-c8 封板前汇总），母本没同步。

---

## 1. 任务对账（TASKS.md 全部 ID）

| ID | 任务（简） | 现负责 | 板面状态 | 实际状态 | 证据 | 还差什么 / 板面偏差 |
|---|---|---|---|---|---|---|
| T01 | 剧本 v2 修正（铁珠、阴环、细跟…） | claude-gpu3（已结束） | 已取消 | obsolete | TASKS；规格已并入 rules_v2 附录 A3 | 无 |
| T02 | 剧本 v3 改写 | fredw-92 | 取消 | obsolete | 被 T55 → T58 rules_v2 全量重写取代 | 无 |
| T03 | 剧本导入器 | fredw-d9 | 完成 | done | data/import/script_v2.json；fredw-92 加 `--merge-base`、`--source-version` | 无 |
| T04 | 导入器与 gpu3 解析器对齐 | fredw-92 + fredw-ae | 完成 | done | parser_diff.md（三份 0 差异）；gpu3_health §6.4（P1–P3 已打） | 5 条已知分歧只在不合契约的输入上出现 |
| T05 | 视觉圣经 | fredw-d9 | 完成 | done（有收尾） | config/visual_bible.toml | 系统后缀里的否定句“无字幕 / 无水印 / 无裸露”（owner_req §4.8） |
| T06 | 编译器读 visual_bible | fredw-d9 | 完成 | done（有收尾） | CHANGELOG T06；bible_version 现 da4109a65f1c | 新剧锁脸：`ns_render.refs.CHAR_IDS` 仍写死本剧三角色（CHANGELOG T42“已知缺口”），未见关闭 |
| T07 | 本机重出非成人首尾帧 | fredw-d9 | 停止 | obsolete | shot_ownership 全归 gpu3；QA4-03 ep01 旧帧已撤 | 无 |
| T08 | frame_spec 共用格式 | fredw-d9 | 完成 | done | CHANGELOG T08；tests/test_t08_frame_spec.py | 无 |
| T09 | 林晚写实母版 | fredw-d9 | 完成 | done | plates/master.png（CM_s1） | 无 |
| T10 | 林晚妆容 L1–L8 | Qwen | 待办 | blocked（Qwen 未开始；GPU0 排 lnwan01、GPU3 留 ep02） | 无交付物 | Qwen 出图 + 项目方挑；Q15 |
| T11 | 多角度底板 + 6 表情 | Qwen | 待办 | blocked（同上） | PeoplePage 缺图红点 | 需求 B2 唯一路径 |
| T12 | 单品图（服装/高跟/美甲/发型） | Qwen | 待办 | blocked（同上） | 信箱 20261030T031834-41749bf4 | Qwen 执行 |
| T13 | 男主候选 | Qwen | 待办 | blocked（同上） | — | Qwen 出图 + 项目方挑选 |
| T14 | 饰品 LoRA | claude-gpu3 | 已取消 | obsolete | SOP_parameters：deferred | 无人接；触发词出图时被剥离（D-27） |
| T15 | 服装/高跟 LoRA | Qwen | 待办 | blocked（项目方定：ep02 渲染后再训） | 现行事实；gpu3_health §1 | ep02 渲完 → GPU3 还给 Qwen；Claude 写的 14 条标注作废待 Qwen 重写（REQ G4） |
| T16 | 林晚 H3 视频 LoRA lnwan01 | Qwen | 进行中 | blocked（排队：信箱 f11c841c，GPU0，排第 2） | gpu3_health §1、§7 | **板面偏差**：“依赖”列仍写 GPU1、拷 master.png、借卡；开训后约 9–11 h |
| T17 | gpu3 剧集渲染 ep01–02 | fredw-ae | 进行中 | blocked | gpu3_health §7；script_v2.json ep02 无 H3 提示词 | **板面偏差**：ep01 是 🔴，不能经 gpu3（owner_run 409）；ep02 等 rules_v2 稿过校验 + 导入 + S2 就绪 |
| T18 | 成集 QA 巡检 | fredw-5c | 进行中 | in progress | qa_laptop 第 4 轮 | ep02 出片后跑 tools/qc_run.py |
| T19 | 成集后 4K 放大 | fredw-ae | 进行中 | blocked | gpu3_health §2：`up4k-test` failed | **板面偏差**：无进展；查失败原因 + 等首个 QA 通过的集 |
| T20 | 画布 v2 + 资产页 | fredw-d9 | 完成 | done | 已被 T54/T59 取代展示 | 无 |
| T21 | 画布导入 gpu3 产物 | fredw-92 | 完成 | done | tests/test_api_c_backend.py | 无 |
| T22 | 画布时长 / 舞台提示 | fredw-92 | 完成 | done | 同上 | 无 |
| T23 | 导演加强规则文件 | 项目方 | 等待 | blocked（等项目方） | config/director_boost_rules.md | 按 G1 内容归 Qwen，可能已作废（D-20） |
| T24 | 成人镜头渲染 | 项目方 | 等待 | blocked（项目方本人启动） | CHANGELOG fredw-b3 删 run_adult_batch；owner_run.py | 与现行一致；owner_run 依赖 fredw-ae runner 接受 op=='run' |
| T31 | gpu3 新模型下载 | research-62b0 | 完成 | done | MANIFEST.tsv | 无 |
| T32 | Civitai LoRA 下载 | research-62b0 | 等待 | blocked（等“重启 Civitai 下载”） | TASKS | D-21 |
| T33 | 模型栈调研 | research-62b0 | 完成 | done | PLAN.md 等 | 无 |
| T25 | gpu3 渲染桥 | claude-gpu3 | 完成 | done | services/canvas_api；nsfs-canvas-bridge 运行 | 无 |
| T26 | 林晚饰品展示图 | claude-gpu3 | 已取消 | obsolete | — | 无 |
| T27 | 难镜头服务 Blender+ControlNet | Qwen | 待办 | blocked（Qwen 未开始） | — | **板面偏差**：依赖写 T14，T14 已取消；是否还做由项目方 / Qwen 定 |
| T28 | gpu3 本地无审查 LLM 服务 | fredw-ae | 进行中 | done（运行中，有收尾） | gpu3_health §1–2：qwen-llm-gpu1 :8098（2 槽 × 48k）+ CPU :8097 | **板面偏差**：应为完成；产出列仍写 :8097；剩 Transient → 常驻 |
| T29 | gpu3 → 笔记本同步 + 重渲回传 | fredw-ae | 进行中 | in progress | 心跳 7 分钟（qc_gates §3）；LORA_REGISTRY 未同步（QA4-07）；关键帧未同步（T52） | 同步源改 ComfyUI/models/loras/LORA_REGISTRY.json；同步 take 关键帧；不依赖会话（PI-24） |
| T30 | 两边改动监控 | fredw-5c | 进行中 | in progress（无产出证据） | — | 封板期是否需要，总调度定 |
| T34 | 成人首尾帧 + 全部视频（gpu3） | fredw-ae | 等待 | obsolete（与 T24 重复） | 现行：项目方本人启动，流水线跳过露骨镜；G8 abliteration 路线已弃 | **板面偏差**：关闭，保留 T24 |
| T35 | 做爱姿势库 | claude-gpu3 | 已取消 | obsolete | — | 无 |
| T36 | 本机全链路 QA | fredw-d9 | 完成 | done | qa_laptop.md 第 1–4 轮 | QA4-06 偶发失败观察中；QA-11/12 等新稿 |
| T37 | 林晚 Qwen 2.1 图像 LoRA | Qwen | 合并到 T48 | duplicate（of T48） | — | 无 |
| T38 | 后期 TTS + 成集装配 | fredw-d9 | 完成（管线） | done（有收尾） | CHANGELOG T38；QA4-04 按 H3 实际片长装配 | ep02 素材到位后跑；缺独白时长闸门（PI-16）、成片响度复测拦截（PI-17） |
| T39 | 亲密戏声音方案 | claude-gpu3 | 完成 | done（有收尾） | docs/intimate_audio.md | §2.2 模板含否定句和人名，违反 H3-A5/D4/D7（owner_req §4.5），要改且不得进写作者上下文 |
| T40 | BGM + 分轨素材 | fredw-5c | 已建成，ep01 已测 | done（有收尾） | docs/music.md；gpu3_health §6.5 | ep02 出片后跑；cue 词表统一（owner_req §4.6） |
| T41 | 生产 SOP 文档 | claude-gpu3 | 完成 | done（有收尾：内容过期） | docs/SOP_production.md | 与现行冲突见 X-04/05/06/10/11/12/15/16；claude-sop 已结束，SOP 无指定维护者 |
| T42 | 新建剧向导 + 编排器 | fredw-d9 | 完成 | done | CHANGELOG T42 | 新剧锁脸缺口见 T06 |
| T43 | G2 母版候选自动生成 | fredw-d9 | 完成 | done | g2_candidates.py | 无 |
| T44 | 本机 ComfyUI 单一调度 | fredw-92 | 完成 | done | comfy_lock.py | 无 |
| T45 | 画布镜头就绪审计 | fredw-92 | 进行中 | in progress（大部分已实现） | sop.py S4 h3_lint 阻塞；桥 audit / video_gate 接口 | “gpu3 链”显示要同步循环重启；未登记完成 |
| T46 | gpu3 阶段调度器 | fredw-ae | 等待（项目方批准） | blocked（建议关闭） | gpu3_health §2：ns-sched 不存在；PI-27 项目方收回调度权；G3 固定分卡 | **板面偏差**：D-22 |
| T47 | 一致性实现（方案 A/D、衔接闸门） | fredw-5c | 进行中 | in progress（代码有，未出过一帧） | production_issues PI-04 | ep02 首次真实验证；阈值待用 ep01 好/坏对校准 |
| T48 | 林晚出图 LoRA lin_wan_qi_v1 | Qwen | 训练完成，评测交 Qwen | done（已交付、已验收，有收尾） | CHANGELOG fredw-d9：交付到 ComfyUI/models/loras + LORA_REGISTRY delivered + .done；QA4-07：gpu3 记录 accepted、sha 873b727b；config/auto_lora_triggers.json（lnwan_qi 0.8） | **板面偏差**：应改完成；剩笔记本注册表镜像同步（QA4-07）、评测样图后补（Qwen） |
| T49 | 姿势 LoRA 前 6 个 | claude-gpu3 | 已取消 | obsolete | — | pose_* 触发词出图时被剥离（D-27） |
| T50 | 3090 提速 | fredw-ae | 部分完成 | in progress（暂停） | gpu3_health §3：bench 已由项目方停 | 封板期可不做 |
| T51 | 人物状态时间线 + 场景分组 | fredw-d9 | 完成 | done（有收尾） | data/state_timeline.json；QA4-01 source_drift | rules_v2 稿导入后自动重建；其余集场景底板仍缺 |
| T52 | 后期逐镜校色 | fredw-d9 | 完成（工具） | done（有收尾） | QA4-08 | 两端校正等 gpu3 同步 reference / last_target 关键帧 |
| T53 | gpu3 分卡 + Qwen 基础设施 | fredw-d9 | 基础设施完成 | done（有收尾） | gpu3_health §1–2 | **板面偏差**：正文仍写“GPU3 = Qwen、GPU1 = 服装 LoRA”，已被 G3 取代 |
| T54 | 画布全面开发 E1–E8 | fredw-92 | 进行中 | in progress | CHANGELOG fredw-92 多条；audit.md §3 剩余两项已由 fredw-92 完成 | S3 frames.json 导入 / 「请 Qwen 出首尾帧」、S4 执行器未做（WORKFLOW §5） |
| T54-B | 画布子任务 | fredw-25 | 完成 | done | CHANGELOG fredw-25 | 无 |
| T55 | Qwen 写作契约 + 校验器 + 返修循环 | fredw-92 | 进行中（v3→v3.1 返修） | done（工具，有收尾） | validate_qwen_script.py、qwen_repair_loop.py | **板面偏差**：v3.1 后台返修已被 T58 取代，应停止并关闭，避免占 Qwen 槽（X-28） |
| T56 | 生产问题登记册 | fredw-92 | 完成 | done | production_issues.md；qc_gates.md | 闸门补齐见第 3 节 |
| T57 | gpu3 性能与分工 | fredw-d9 | 进行中 | in progress | gpu3_health §1–2、§6、§7 | Transient → 常驻；信箱优先级（封板期不做）；qwen-agent3 未经 claim_gpu |
| T58 | 剧本创作对话框 + 全量重写 | fredw-c8 | 进行中 | in progress | rules_v2_full.log：ep01 交付（7 镜 53 秒 block 0），ep02 block=1 返修中，ep03 写作中 | **板面偏差**：描述仍写 abliteration 默认；剩 58 集约 8–15 h；每集导入须 `--source-version v3` |
| T59 | 画布视觉重设计 | fredw-25 | ② 完成，待验收 | done（待项目方验收） | docs/design/t59/applied/ | D-23 |
| T60 | 画布加载提速 | fredw-25 | 完成 | done | CHANGELOG T60 | 无 |

**计数**：done 30（T03 T04 T05 T06 T08 T09 T20 T21 T22 T25 T28 T31 T33 T36 T38 T39 T40 T41 T42 T43 T44 T48 T51 T52 T53 T54-B T55 T56 T59 T60；其中有收尾动作 14 个：T04 T05 T06 T28 T38 T39 T40 T41 T48 T51 T52 T53 T55 T59）｜in progress 9（T18 T29 T30 T45 T47 T50 T54 T57 T58）｜blocked 13（T10 T11 T12 T13 T15 T16 T17 T19 T23 T24 T27 T32 T46）｜obsolete 8（T01 T02 T07 T14 T26 T34 T35 T49）｜duplicate 1（T37）。

### 1b. 板上没有、但文档里有的待办（建议补 ID）

| 来源 | 待办 | 现状 |
|---|---|---|
| WORKFLOW §5 | S3 接入：画布导入 Qwen `frames.json` + 「请 Qwen 出首尾帧」发 `kind:image_request` | 未做 |
| WORKFLOW §5 | S4 H3 执行器：读 Qwen 首尾帧 + `h3_loras` 原样出视频，记哈希 | 未做（gpu3 现用 weita_render / weita_series） |
| WORKFLOW §5 | 内容检测撤出 Claude 侧（人脸相似度、发色、服装、VLM 核对剧本改为只报数） | 未做；与 G5 冲突（X-13） |
| WORKFLOW §5 | Image Docker + image_request 接口 | 已做（fredw-d9 image_docker.sh :8190；fredw-5c qwen-image-api :8100），WORKFLOW 未勾 |
| WORKFLOW §5 | Qwen :8098 迁 GPU1 | 已做（gpu3_health §1），WORKFLOW 未勾 |
| WORKFLOW §5 | gpu3 渲染器研究补丁 research_adoption §三 G1–G8 | 未见执行证据 |
| qc_gates §4 | ns_qc 接入 gpu3 五处 | 未做 |
| gpu3_health §7 | Transient unit 改常驻；隧道守护自启；qwen-agent3 用 claim_gpu 包裹；GPU3 在 ep02 后还给 Qwen 并发信箱通知 | 未做 |
| QA4-07 | LORA_REGISTRY 镜像同步源改为 ComfyUI/models/loras | 已告知 fredw-92，未见完成 |
| owner_req §4 | 系统侧 14 条 | 已修 3 条（resolve_music 尊重 N/A：fredw-92；wardrobe 珠色：fredw-5c；尾帧规格词：QA4-02）；其余 11 条（intimate_audio 模板、cue 词表、后缀否定句、旧发色 / 旧规格、机检与规则不一致、上下文预算同步、写作者身份表述、数据C / D0–D10 缺失等）未见处理 |

---

## 2. 需求覆盖（REQUIREMENTS A1–G8）

| # | 要求（简） | REQ 标注 | 实际 | 落实位置 | 缺口 |
|---|---|---|---|---|---|
| A1 | 真人质感，角色全合成 | ⚠ | 部分 | gpu3 两段式出图 + lin_wan_qi_v1；本机轻精修链已不用于本剧 | 没在新帧上验证；PI-20 无闸门；“真人感”阈值归 Qwen / 项目方 |
| A2 | 高清、Leica 锐利、电影调色 | ✅ | 已落实（图像） | compiler.lens_term；H3 里按 rules_v2 不写 Leica | 无 |
| A3 | 无字幕、干净 | ✅ | 已落实 | H3-D4 block、S3-F8 OCR | 系统后缀含否定句，CFG=1 下无效（owner_req §4.8） |
| A4 | 色调参考林晚定妆图 | ✅ | 部分 | 本机 grade.py；gpu3 S3-F7 | 若 ep02 走 Qwen → :8100 出图，是否调色未定义（X-03） |
| A5 | 大光圈 f/1.4 | ✅ | 已落实 | 风格后缀（实为 f/1.2） | Q7 |
| A6 | 首尾帧决定画质 | ⚠ | 部分 | 同 A1 / A4 | 同上 |
| B1 | 林晚与参考一致 | ⚠ | 部分 | 母版脸部裁切 + lin_wan_qi_v1（已验收）+ auto_lora_triggers | REQ 文字仍写“浅冰蓝”，现行“雾霾天蓝”（X-09） |
| B2 | 多角度资产 | ❌ | 未落实 | T11（Qwen 待办） | 整项未开始 |
| B3 | 脸部来源 AI 生成 | ✅ | 已落实 | config/face_reference.json | 无 |
| B4 | 每集切换人物资产 | ⚠ | 部分 | data/looks、LookPicker、look_confirmed（M3） | `[looks] inject` 默认关；仅 ep02 造型确认 |
| B5 | 美甲 5cm / 2cm | ⚠ | 部分 | 编译器条目；rules_v2 A3 | 资产图 T12 未做 |
| B6 | 服装鞋美甲 image 生成资产 | ⚠ | 部分 | 现归 Qwen（T10–T12） | REQ 文字仍写 fredw-d9 负责（X-21） |
| B7 | 鞋跟 12cm、6mm | ✅ | 已落实（提示词） | 编译器首尾帧都补（QA4-02） | 鞋 LoRA 未训（T15） |
| B8 | 镜面漆皮 | ✅ | 已落实（提示词） | 同上 | 同上 |
| B9 | 妆容更精致更性感 | ❌ | 未落实 | T10（Qwen 待办） | Q15 |
| B10 | 日常偏性感、漆皮超短裙 | ⚠ | 部分 | 安全镜条目改写；rules_v2 A3 | 资产 / 服装 LoRA |
| C1 | 严格按剧本提示词拼装 | ⚠ | 部分 | 编译器 §1.2 拼装；写作改由 Qwen rules_v2 | 数据C（场景锁 / 装饰锁全文）不在仓库（Q4） |
| C2 | 纠正器条目 | ⚠ | 部分 | 编译器特写 / 暗场 / 安全镜（首尾帧都补） | 纠正器多条与 rules_v2 冲突，已按 rules_v2（audit C8–C20） |
| C3 | 首尾帧出视频 | ✅ | 已落实（系统） | 尾帧独立资产；gpu3 唯一出视频 | 新稿还没出帧；PI-08 |
| C4 | 铁珠 / 阴环 / 高跟规格 | ✅ | 已落实 | rules_v2 A3；fredw-5c 改 wardrobe.json、manifest、image提示词 v2.md | desire_amplification.md 是否仍写“黑球”未核；REQ 文字“kimi 会话已改”过期 |
| C5 | 多轮出图择优 | ✅ | 部分 | gpu3 step_a 多候选；本机多轮评分已不用于本剧 | 评分含“剧本 / 真人感”等内容判断，与 G5 冲突（X-13）；PI-07 |
| D1 | Image 2.1 或 Klein | ✅ | 已落实 | Qwen Image 2.1 | Klein 未对比（非封板项） |
| D2 | 成人本地生成，项目方启动 | ✅ | 已落实 | 启动器已删；owner_run 面板，🔴 集 409 | runner 接受 op=='run'（fredw-ae） |
| D3 | 模型选择 deep research | ⚠ | 部分 | research v3–v5 | 未实测；H3 A/B 已推迟 |
| D4 | 多 agent 并行 | ✅ | 已落实 | — | 无 |
| D5 | 成集 QA 后 4K | ⚠ | 部分 | docs/upscale_4k.md | up4k-test failed；无 QA 通过的集 |
| E1 | 每镜显示首尾帧、提示词 | ⚠ | 已落实（界面） | T54 尾帧预期来源、镜头行 | 数据侧尾帧缺（PI-08） |
| E2 | 参考短剧平台交互 | ⚠ | 已落实 | docs/research/short_drama_platform_ui.md；T54-B | REQ 状态过期 |
| E3 | 每镜必有 8 要素 | ❌ | 部分 | 画布行 + R-C1 阻断 | 界面有，数据缺 |
| E4 | 交互耐用 | ⚠ | 已落实 | 离线等待、失败重试、批量确认 | REQ 状态过期 |
| E5 | 人物资产 tab | ❌ | 已落实 | CharacterCard.tsx、PeoplePage.tsx、manage.py | REQ 状态过期 |
| E6 | 资产驱动出图（多参考） | ❌ | 部分 | 角色卡「用这些参考出图」；:8100 队列 | 未见端到端验证 |
| E7 | 画布重做 5 点 | ❌ | 已落实（待验收） | T59、T54-B、ux-fix | D-23；REQ 状态过期 |
| E8 | soundscape / 配乐进 H3 | ❌ | 已落实 | H3 面板、resolve_music、H3-S3 | D-13；REQ 状态过期 |
| F1 | 先整理需求 | ✅ | 已落实 | — | 无 |
| F2 | 成人批量提醒、弹窗 | ✅ | 被取代 | 启动器已删；owner_run 需勾“项目方本人启动” | 文字改指 owner_run（X-22） |
| G1 | 内容全部由 Qwen | ⚠ | 部分 | T58 剧本由 Qwen 写 | 首尾帧提示词 / frames.json、标注重写、评测挑选尚未由 Qwen 产出 |
| G2 | Claude 不写不评内容 | ⚠ | 部分 | 校验器只查格式；ns_qc 只测技术量 | gpu3 VLM 核对剧本仍阻断（X-13） |
| G3 | GPU1 = Qwen，GPU0+3 = LoRA | ⚠ | 已落实 | gpu3_health §1 | GPU3 暂留 ep02；unit 非常驻 |
| G4 | Blender + LoRA 归 Qwen | ⚠ | 部分 | lin_wan_qi_v1 已交；lnwan01 排队 | 服装 LoRA ep02 后；T27 未开始 |
| G5 | Claude 不参与内容审核 | ⚠ | 部分 | qc_gates“只测技术量、阈值来自文档” | 同 G2；“待项目方定”阈值 3 项 |
| G6 | Qwen Docker + 画布通讯 | ⚠ | 已落实 | 信箱 :8099、qwen_mailbox 代理 | 无 |
| G7 | 通讯规则 / 生产流 | ⚠ | 部分 | 剧本：信箱 → 校验 → 导入 已通；qwen_comms §6 出图 | S3 frames.json / S4 执行器未做 |
| G8 | 写作交 abliteration | ⚠ | 被取代 | 项目方改回 Qwen；script_chat.json 默认 qwen | REQ / WORKFLOW 头部仍写 abliteration 负责（X-01） |

**计数**：已落实 20（A2 A3 A5 B3 B7 B8 C3 C4 D1 D2 D4 E1 E2 E4 E5 E7 E8 F1 G3 G6）｜部分 20（A1 A4 A6 B1 B4 B5 B6 B10 C1 C2 C5 D3 D5 E3 E6 G1 G2 G4 G5 G7）｜未落实 2（B2 B9）｜被取代 2（F2 G8）。

---

## 3. 30 条生产问题的闸门现状

图例：**有** = 已有阻断性自动闸门并接在生产路径上｜**部分** = 有检查但只 warn、只在笔记本 ns_qc、没接进 gpu3、或从未在新片上跑过｜**无** = 没有有效的自动闸门。

| PI | 问题 | 闸门 | 现有检查 | 缺什么 |
|---|---|---|---|---|
| PI-01 | 林晚脸崩 / 溶解 | 部分 | 帧 S3-F1 block；gpu3 视频闸门（SFace 中位数 ≥0.30）未在新片跑；ns_qc Q-D1 fail / Q-D2 warn（笔记本） | 人脸尺寸 S3-K2 升 block；ns_qc 接进 gpu3；golden 负样本回归（样本不在笔记本） |
| PI-02 | 参考图把衣服项链带进镜头 | 无 | 只有流程修复（脸部裁切、两段式） | 参考图泄漏检查（VLM 属内容判断，按 G5 要项目方 / Qwen 定） |
| PI-03 | 发色漂移 | 部分 | 帧 S3-F3 block；视频 Q-D3/Q-D4 warn（笔记本） | 视频阶段接进 gpu3 |
| PI-04 | 服装道具漂移 / 镜间跳 | 部分 | R-C7、S3-K1（阈值未校准，未出过帧）；Q-D5 warn | 校准；视频阶段接入；道具计数 |
| PI-05 | 鞋不符、赤脚 | 部分 | VLM“没有赤脚”；R-C8 / Q-P1 过期判定 fail | 过期镜头自动列表 + 重排；鞋 LoRA |
| PI-06 | 饰品位置数量 | 部分 | 17 镜“挂着不穿”硬检查（🟡） | 数量检查；`qc_unchecked[]` 在画布显示 |
| PI-07 | 构图朝向不符，失败候选仍锁定 | 无 | 闸门存在但失败时不拦（weita_series 900–904） | step_a 锁定前加 `worst()!="fail"`；S3-K3 升 block |
| PI-08 | 首尾帧不同源 | 部分 | R-C1/R-C2/P-B2 block；ns_qc Q-K1–K3、Q-P4/Q-P6（笔记本） | take 写 reference_sha / last_target_sha 并同步；Q-P6 进画布红标 |
| PI-09 | 非成人镜裸露 | 有 | S3-F4（QC v3）一票否决；set_active 拒绝成人镜笔记本版本 | gpu3 侧“qc 为空不能设 active” |
| PI-10 | 字幕烧进画面 | 有 | H3-D4 block；S3-F8 OCR；视频 OCR | 无 |
| PI-11 | H3 自带配乐 | 部分 | H3-S3 文本 block；resolve_music 尊重 N/A（已修）；Q-A1 warn | 视频阶段拦截；后期 BGM 叠加规则（D-13） |
| PI-12 | 拟音 / 开头嘟囔 | 部分 | 拟音 CLAP 闸门；Q-A5 warn | 开头嘟囔接入 gpu3；地点底噪补位 |
| PI-13 | 多人声串扰 / 男声 | 部分 | 剧本级 H3-D7 block（亲密镜 + 非亲密多人）；Q-A3/A4 warn（F0 估计） | 说话人嵌入模型；视频阶段拦截 |
| PI-14 | Turbo 音质 / 响度 | 部分 | Q-A2/A2b warn | 亲密镜音质 A/B（已推迟） |
| PI-15 | 标志音不像 | 无 | — | audio_bank 构建门槛，或换真实录音（D-15） |
| PI-16 | 独白溢出到下一镜 | 无 | 规则有字数上限，机检没有（owner_req §4.10） | 校验器 SC-11 + 装配前时间线校验 |
| PI-17 | 声音 / 配乐字段缺、响度 | 部分 | R-C1、S1-W3 block；BGM CLAP 闸门 | 成片 −14±1 LUFS 复测拦截 |
| PI-18 | 首帧色调景深不符 | 有 | S3-F2、S3-F7 block（gpu3 帧闸门） | 亮度 / 暖度 warn（阈值 D-31） |
| PI-19 | H3 视频颜色漂移 | 部分 | Q-K4/Q-K5 warn（笔记本）；校色默认关 | 接进 gpu3；关键帧同步后开校色 |
| PI-20 | 画面质感差 | 无 | — | 主体锐度 / VMAF；“真人感”阈值归 Qwen / 项目方 |
| PI-21 | H3 提示词非官方格式 | 有 | h3_lint、shot_audit、validate_qwen_script、validate_script_strict 全部 block | 无（等 rules_v2 稿全部导入） |
| PI-22 | 运镜不忠实 / 中途转身 | 无 | S3-K3 只 warn | 朝向一致 block；yaw 跳变 |
| PI-23 | 参数文件不同步 | 部分 | P-A1…A7 审计 | PIPELINE_LOCKED md / json / SOP_parameters 自动比对 |
| PI-24 | 两条出图链 / 同步依赖会话 | 部分 | `_PREVIEW_未完成` 装配闸门；Q-P3 fail、Q-P5 / 心跳 Q-S1 warn | 同步改计划任务 / systemd；画布红条 |
| PI-25 | 规则无版本 | 部分 | R-C8 / Q-P1 fail（判定） | 受影响镜头自动列表 + stale 标记 + 不进成片 |
| PI-26 | 进程用旧代码 / 吞异常 | 无 | QC RLock 已加 | code_sha 巡检；worker 异常重新入队 |
| PI-27 | GPU 争用 | 无 | 项目方手动；锁协议 | nvidia-smi 进程 ↔ 锁巡检；GPU2 进程报警 |
| PI-28 | 汇报“完成”实际没做 | 无 | — | 状态从产物生成（本次 T48 / T28 板面偏差就是实例） |
| PI-29 | 解析编译 bug | 有 | tests/test_qa_laptop.py；QA4-01 源文件漂移检测 | 导入后自动扫描、命中即拒绝导入 |
| PI-30 | v3 绕过确认闸门 | 有 | R-C3 / s1_gate.json；导入 `--source-version` 按集判 | 渲染器启动时比对剧本 sha |

**计数**：有 6（PI-09、10、18、21、29、30）｜部分 15（PI-01、03、04、05、06、08、11、12、13、14、17、19、23、24、25）｜无 9（PI-02、07、15、16、20、22、26、27、28）。
**建议 ep02 之前补的**：PI-07（失败候选锁定，一行检查）、PI-08（take 写关键帧 sha）、ns_qc 接进 gpu3 `_clip_checks`（覆盖 PI-01/03/04/19 的视频阶段）。

---

## 4. 仍待项目方决定的事项（合并去重）

来源缩写：Q = owner_requirements_for_writer §3；SP = SOP_production；PI = production_issues；QG = qc_gates；GH = gpu3_health；WF = WORKFLOW；T = TASKS。

### 4a. 今天已答（勿再问；右列是还没同步的文档）

| # | 事项 | 答复 | 尚未同步 |
|---|---|---|---|
| D-01 | Q1 阴环珠颜色 | 不锈钢本色 | desire_amplification.md、IMG 数据E（未核）；REQ C4 |
| D-02 | Q12 写作者能否新增亲密场次 | 允许，限大纲内成年角色 | 已同步（rules_v2 / script_chat_rules M1） |
| D-03 | Q9 / PI-13 / SP §9A.1 H3-D7 | 普通对话镜每镜一人说话；亲密镜只林晚说话 | owner_req A2/A4 仍写“≤2 位”、Q9 仍列待定；SOP §9A.1“冲突待定”与示例 2（X-06） |
| D-04 | 时长语义（G13） | 剧本写整数 N，实际片长由 H3 决定 | 剧本全局头“6 镜 × 10 秒” |
| D-05 | 首 / 尾帧规格词 | 系统自动补（去重），不透传 | owner_req A6、§4.1、M3（X-02）；WF §2/§4“原样”（X-03） |
| D-06 | 成人判定 | 整集 🔴 继承（per_shot=false） | TASKS 规则 7、T34、SOP §8（X-04） |

### 4b. 由今天的决定隐含覆盖，建议请项目方一句确认

| # | 事项 | 现行默认 |
|---|---|---|
| D-07 | Q10 亲密场次里男性台词放哪 | 移到同场次相邻的非亲密镜 |
| D-08 | Q11 后期是否给亲密镜合成男方呼吸 | 不合成（男方无声） |

### 4c. 仍待决定

| # | 事项 | 来源 | 现行默认 / 备注 |
|---|---|---|---|
| D-09 | 未指定颜色的单品 | Q2 | 黑漆皮、黑乳贴、银色金属环 |
| D-10 | 多人规则（≤2 焦点、位置分配表）是否适用本剧 | Q3 | 适用 |
| D-11 | 缺失参考资料；⤴ Alex/Ryan/Kai/Leo 角色锁（旧 60 集，已撤）；D0–D10 定义（数据C） | Q4、owner_req §4.14 | 写作者首次出场定一条描述 |
| D-12 | “精致”可否入提示词 | Q5 | 可用，优先具体妆面 |
| D-13 | 配乐进 H3 后，后期是否在这些镜头再铺整集 BGM | SP §9A.1、CHANGELOG fredw-92、PI-11 | 建议不铺 |
| D-14 | 出图模型（Turbo / Base / NoctQ）；SOP_parameters 5 个“待验证” | Q6 | 写作按 CFG=1 |
| D-15 | 标志音：人工试听或换真实录音 | PI-15 | 未定 |
| D-16 | 独白溢出三选一 | PI-16、MORNING_DECISIONS #1/#2 | 未定；时长交给 H3 后仍可能溢出 |
| D-17 | 光圈 f/1.4 还是 f/1.2 | Q7、REQ A5 | f/1.2 |
| D-18 | 单人镜是否写人数 | Q8 | 不强制 |
| D-19 | 顾沉角色锁“34 岁”vs“小鲜肉” | Q13 | 画面写年轻成年男性 |
| D-20 | 导演加强规则（项目方自己写）是否仍需要 | T23 | 未定 |
| D-21 | 是否“重启 Civitai 下载” | T32 | 等原话 |
| D-22 | 阶段调度器 T46 继续还是关闭 | T46、GH §2 | 现为手动 + 固定分卡 |
| D-23 | 画布重设计验收 | T59 | 待验收 |
| D-24 | 男主候选挑选 | T13 | 候选未出 |
| D-25 | 各集造型确认（ep02 已确认）；`[looks] inject` 何时打开 | REQ B4 | 默认关 |
| D-26 | 各集剧本采纳（SP-G3，rules_v2 稿逐集导入） | SP、WF §5 | ep01 已导入；其余待写完 |
| D-27 | 饰品 LoRA（nprng2/lbrng9/beads）与姿势 LoRA 是否交 Qwen 训练；未训前触发词被剥离是否可接受 | T14、T49、SOP_parameters | 已 deferred |
| D-28 | 用 ep02 样片锁定 PIPELINE_LOCKED 参数（SP-G4） | SP | ep02 出片后 |
| D-29 | 场景底板：ep02 豁免，其余集是否必须先出 | 现行事实、PI-04 | 未定 |
| D-30 | ns_qc“待项目方定”的阈值（Q-K6 SSIM、Q-D6 主色、Q-A1b 谱峰） | QG §2 | 只报 info |
| D-31 | 首帧亮度 / 暖度阈值、“真人感”阈值 | PI-18、PI-20 | 项目方 / Qwen 定 |
| D-32 | 每集 6–8 镜、50–75 秒（助手定的规格） | Q14 | 沿用 |
| D-33 | 妆容 L1–L8 是否启用；ep06 归属 | Q15、REQ B9 | 按 VB |
| D-34 | 左脸颊小痣 | Q16 | 不写 |
| D-35 | 美甲长度写法 | Q17 | 照写“5厘米” |
| D-36 | 撤到静默写淡出英文还是 N/A | Q18 | 本镜淡出写英文 |
| D-37 | Image 2.1 首尾帧由谁发起（Qwen 自发 / 画布发 image_request / 系统编译器 + gpu3 渲染器） | WF 头部“待项目方明确” | 未定，直接影响 ep02（X-03） |
| D-38 | gpu3 核心服务改常驻、隧道自启是否在封板期做 | GH §7 | 由总调度定 |
| （附） | React Flow 去水印需要 Pro 授权 | QA30-07 | 非封板项 |

---

## 5. 文档之间的矛盾（★ = 影响封板）

| # | 主题 | 一方 | 另一方 / 现行事实 | 建议 |
|---|---|---|---|---|
| X-01 ★ | 谁写剧本 | WORKFLOW 头部“写作现由 abliteration 负责”；REQ G8 主句；T58 描述“abliteration 默认” | 现行 Qwen 写，abliteration 弃用（G8 末句、owner_req §0、script_chat.json provider=qwen） | 改 WORKFLOW 头部与 G8 主句；WORKFLOW §5 Qwen 清单里的信箱任务 b2c39613、“34 个任务已撤”标为历史 |
| X-02 ★ | 尾帧规格词谁写 | owner_req A6“尾帧要自己写全规格词，系统不追加”、§4.1；script_chat_rules_audit M3 | 现行：系统首尾帧都自动补并去重（QA4-02；fredw-c8“规格句由编译器补”） | 改 owner_req（rules_v2 母本） |
| X-03 ★ | S3 出图链 | WORKFLOW §2/§4：Qwen 写 Image 2.1 提示词并自行调度，Claude“原样”用、不改提示词 | 今天定“系统自动补规格词”（编译器路径）；gpu3 实际用 weita_series 出帧 | 定 D-37；若走 :8100，规格词 / 调色 / 锁脸在哪层补要写清 |
| X-04 ★ | 成人判定与分工 | TASKS 规则 7：逐镜判定，成人首尾帧 + 全部视频归 claude-gpu3；T34；SOP §8“非成人 → 笔记本、成人 → gpu3” | 现行：整集 🔴；项目方本人启动；流水线跳过露骨镜；本剧全部镜头首尾帧 + 视频归 gpu3（shot_ownership），笔记本不出本剧帧 | 改 TASKS 规则 7、SOP §8；关 T34 |
| X-05 ★ | GPU 分配 | TASKS 规则 5“GPU0/3 渲染、GPU1 训练”；SOP §5“LoRA 训练 GPU1 为主”；SOP ★“GPU0/1/3 中 1 张常驻 Qwen”；T53 正文“GPU3 = Qwen、GPU1 = 服装 LoRA”；T16 依赖写 GPU1 | 现行 G3：GPU1 = Qwen；GPU0 = lnwan01 队列；GPU3 暂留 ep02 后还给 Qwen；GPU2 坏卡 | 统一按 G3 改 |
| X-06 ★ | 普通对话镜说话人数 | SOP §9A.1 H3-D7“冲突待定，按官方双人语法”+ 示例 2（S1、S2）；owner_req A2/A4“≤2 位说话人”、Q9 待定 | 现行：每镜一人说话（fredw-92 H3-D7 非亲密多人 block；validate_script_strict block） | 改 SOP §9A.1 与示例 2、owner_req A2/A4/Q9 |
| X-07 ★ | ep01 / ep02 的渲染卡 | gpu3_health §1“GPU3 留给 ep01 渲染整卡”；gpu_monitor 暂停锁标签“为 ep01 预留”；T17“ep01–02” | 现行：ep01 是 🔴 不能经 gpu3；GPU3 为 ep02 预留（gpu3_health §7） | 改 §1 与锁文件名 / 标签 |
| X-08 ★ | LoRA 状态 | TASKS T48“评测交 Qwen”；笔记本 LORA_REGISTRY 镜像 training / sha null | gpu3 注册表 accepted、sha 873b727b；项目方已验收 | 改板；修同步源（QA4-07） |
| X-09 | 林晚发色 | REQ B1“浅冰蓝”；SOP §9A.2 示例“ice-blue hair”；纠正器“深靛蓝” | VB / rules_v2“雾霾天蓝”，并禁写“浅冰蓝” | 改 REQ B1、SOP 示例 |
| X-10 | 剧本唯一写入者 | TASKS 规则 3、SOP §2：claude-gpu3（= kimi 会话）；记忆亦如此 | claude-gpu3 已结束；内容由 Qwen 写、fredw-92 / fredw-c8 导入；fredw-5c 今天改了 `script play lib/…image提示词 v2.md`（珠色） | 重新指定剧本库写入者 |
| X-11 | SOP 维护者 | SOP ★4：claude-sop 是 SOP 与 SOP_parameters 唯一写入者，每 30 分钟巡检 | claude-sop / claude-gpu3 已结束；fredw-5c 今天改了 SOP | 指定新维护者 |
| X-12 | 调度器 | SOP ★2：借卡只能由调度器写、每 5 分钟重算 | ns-sched 不在运行；项目方手动（PI-27）；固定分卡 | SOP 改为“现行手动 + 锁协议” |
| X-13 | 内容检测归属 | WORKFLOW §1/§5、REQ G2/G5：Claude 不做内容检测，人脸相似度、发色、VLM 核对剧本要撤出或只报数 | REQ C5 本机评分（剧本 0.40、真人感 0.15）；gpu3 S3-F5 VLM 事实核对为 block；ns_qc SFace / 发色为 fail | 项目方定哪些算系统技术闸门、哪些算内容审核；阈值归属写清 |
| X-14 | 时长范围 | H3-A11 4–15 s；S1-W2 5–15 s；导入器 3–15 s；gpu3 夹到 3/15；剧本全局头“6 镜 × 10 秒” | rules_v2：5–15 整数 | 统一到 5–15 |
| X-15 | v3 改写用哪台 LLM | SOP §6：gpu3 :8097“最好占一张 GPU”；资源表“3–5 小时” | 现行 GPU1 :8098，全量重写约 8–15 h | 改 SOP §6 |
| X-16 | 负面词 | SOP §2 剧本结构列 `**负面追加**`；IMG §1.2 负面全拼 | rules_v2 不写负面字段（SC-21 block）；script_v2.json 里 v2 原稿集仍带 negative_extra | 改 SOP §2 |
| X-17 | 配乐 cue 词表 | qwen_writer_system_prompt.txt / 契约：进入 / 延续 / 推高 / 落下 / 点题 | music.md / rules_v2：进入 / 延续 / 渐强 / 推到高点 / 撤到静默 / 落下 / 重音 | 统一（owner_req §4.6） |
| X-18 | intimate_audio 模板 | intimate_audio.md §2.2 含 “No male voice”、“(S1) Lin Wan” | H3-A5 / D4 / D7 | 改模板（owner_req §4.5） |
| X-19 | 系统后缀否定句 | VB 统一后缀“无字幕、无文字、无水印”，安全镜“无裸露” | CFG=1 否定无效；rules_v2 禁写否定 | 系统侧改正向写法 |
| X-20 | REQUIREMENTS 状态列 | E1–E8 多为 ❌ / ⚠ | E2、E4、E5、E7、E8 已实现 | 更新状态列 |
| X-21 | 资产负责人 | REQ B6“改由本机 fredw-d9 负责全部林晚资产” | T10–T12 已移交 Qwen | 改 REQ B6 |
| X-22 | 成人批量提醒 | REQ F2“成人批量要提醒，未确认弹窗” | 启动器已删；owner_run 需勾“项目方本人启动” | F2 改指 owner_run |
| X-23 | WORKFLOW TODO 勾选 | §5：Image Docker、Qwen 迁 GPU1 未勾 | 已完成 | 勾掉 |
| X-24 | WORKFLOW §3 优先级 | “先把 LoRA 做完：出图 → 视频 → 衣服 / 鞋 / 指甲 / pose” | 现行：ep02 渲染先占 GPU3，服装 LoRA 排 ep02 后 | 改 §3 |
| X-25 | CHANGELOG 顺序 | 文件头“追加式，最新在上” | 实际最新在下 | 改头部说明 |
| X-26 | “G”编号撞名 | SOP G1–G5 = 人工关口；REQ G1–G8 = 分工规则；h3_sound G1/G13 = 研究条目 | — | 引用时加前缀（SOP-G / REQ-G） |
| X-27 | 记忆与现行 | 记忆：“剧本唯一写入者 = kimi 会话”、“gpu3 1 卡 Qwen + 2 卡 LoRA” | kimi / claude-gpu3 已结束；GPU3 暂借 ep02 | 记忆需更新（本次只读，未改） |
| X-28 | v3.1 返修与 rules_v2 重写并行 | T55“v3 → v3.1 全量返修后台运行” | 已被 T58 取代；两者都占 Qwen 的 2 个槽 | 确认 v3.1 循环已停 |

---

## 6. 建议的封板顺序（只列系统侧动作；内容全部归 Qwen / 项目方）

1. 定 D-37（S3 出图链）与 D-29（底板豁免范围），写进 WORKFLOW。
2. 修 LORA_REGISTRY 镜像同步（QA4-07）；确认 v3.1 返修循环已停（X-28）。
3. ep02 rules_v2 稿到 block=0 → `tools/import_script.py --merge-base --source-version v3` 导入 → 重建 state_timeline → S2 就绪。
4. gpu3：step_a 失败不锁定（PI-07）、add_take 写关键帧 sha（PI-08）、`_clip_checks` 接 ns_qc（PI-01/03/04/19）——都是小改动，放在 ep02 之前。
5. GPU3 渲染 ep02 → tools/qc_run.py → T40 BGM / 分轨 → T38 装配 → 项目方 SOP-G4 样片锁定 → GPU3 还给 Qwen（服装 LoRA）。
6. 并行：Transient unit 改常驻（D-38）、同步改计划任务（PI-24）、查 up4k-test（T19）。
7. 文档：先改第 5 节 ★ 项（X-01…X-08），其余随后。
