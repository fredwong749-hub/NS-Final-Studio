# 系统重构建议（基于 ep02 全链路审计，CHAIN，2026-10-31）

依据：`docs/ep02_iter/chain_audit.md`（问题编号 A/B/C/D/E 沿用该文件）。本文件只讲系统结构，不涉及剧本内容。所有“由谁定”的决定，标注为项目方闸门。

## 1. 现在的系统错在哪里（一句话版）

现在剧本是自由文本，编译器靠关键词去猜“谁在画面里、在哪、朝哪、是不是成人镜头”。编译结果还取决于运行环境（当时哪条 GPU 道上有哪些 LoRA）。提交时会再改一次提示词，改动不回写。产物原地覆盖，没有出处记录。闸门、QC 和合成彼此不连通。作业状态又活在 API 进程里。ep02 的 40 多条问题，绝大多数都能归到这六点之一（chain_audit §3）。

## 2. 目标数据模型：Shot Spec（每镜唯一事实来源）

一个镜头只有一份结构化规格。剧本导入、写作模型补全、画布修改，都只能改它，并且每次修改生成一个新版本。所有下游提示词都是它的**纯函数**。

```yaml
shot_spec/2:
  id: ep02-S8
  rev: 7                         # 单调递增；任何修改都产生新 rev，旧 rev 只读保留
  source: {script_file, script_sha, line, imported_at, edited_by}   # 每个字段可单独带 source
  duration_s: 12
  scene: {id: sk_taxi_backseat, plate: assets/scenes/...png#sha, time_of_day: 深夜, camera: {size: 特写, angle: 侧面, move: static, lens: 85mm}}
  characters_on_screen:          # 只有这里列出的人才进角色锁 / LoRA / 参考图
    - {id: lin_wan, facing: side, face_visible: true, look: lw-ep02-office, focus: primary}
  mentioned_only: [gu_chen]      # 只提到名字、不在画面里（A4）
  props: [{id: gc-suit-jacket, holder: gu_chen, worn_by: lin_wan, state: worn}]
  first_frame: {text: <剧本 img 原文>, must: [...facts]}
  end_frame:   {text: <剧本 尾帧原文>, exposure_intent: normal|dark|black}   # 驱动后缀（A2/C9）
  motion: {text: <剧本 motion 原文>, actions: [...]}
  audio:
    dialogue: [{speaker: lin_wan, text: "…", stage: "慌"}]               # 说话人 = 角色 id，舞台提示单独一列（A12）
    voiceover: {speaker: lin_wan, text: "…", max_s: 11.5}                 # ≤ 镜头时长，导入即校验（D2）
    soundscape_en: "…"
    music: {mode: episode_bgm|h3, cue: …}
  rating: {level: 2, explicit: false, source: script}                     # 不由关键词翻转（A11）
  h3: {mode: fl2va|i2va, text: <可选：写作者手写的 H3 正文>}
```

角色、场景、造型各有自己的注册表（`registry/characters/*.yaml`、`scenes/*.yaml`、`looks/*.yaml`），也都带 rev。角色注册表必填：族裔、年龄、脸、发、体型、EN 短语、VOICE、身份参考图（sha）、LoRA（图 / 视频，各带适用条件）。缺一项，资料闸门就是 missing（A1、C1）。

## 3. 管线：确定性编译 + 受约束的 LLM 填充

```
导入/编辑 ──▶ Shot Spec(rev) ──▶ 资料闸门(纯函数，缺即停) ──▶ 编译(纯函数) ──▶ RenderPlan(不可变, 带哈希)
                   ▲                                             │
           LLM 只能填 Spec 的空字段                                ├─ 首帧作业  ┐
           (JSON Schema 输出 + 校验器)                             ├─ 尾帧作业  ├─ 作业队列(独立持久化) ─▶ GPU worker
                                                                  └─ 视频作业  ┘            │
                                                                                            ▼
                                                     Artifact(带 provenance) ─▶ QC(运动/OCR/ASR/VLM 事实核对) ─▶ 定稿闸门
                                                                                            ▼
                                                                         合成只取“定稿 + QC 通过”的 Artifact
```

### 3.1 编译 = 纯函数
- `compile(spec_rev, registry_revs, bible_rev, compiler_version) → RenderPlan`。输入里**没有**“当前 GPU 上有什么 LoRA”。LoRA 选择只看 Spec（在画角色 + 朝向 + focus）。可用性在派单时检查：缺了就不派，不能悄悄去掉（修 C2、E3）。
- `RenderPlan` 列出每一步的全部参数：模型文件和 sha、LoRA 和权重、参考图和 sha、分辨率、步数、sampler、cfg、seed、提示词全文、负面词（cfg=1 时显式写 `null`，A3）。`plan_hash` 是这些参数的哈希，替代现在覆盖不全的 inputs_sha。
- I2VA / FL2VA 是两个独立模板，由 `h3.mode` 选择；不在提交时替换第一行（修 C5）。
- 后缀按条件生成：`face_visible=false` 不加“面部可辨”，`exposure_intent=black` 不加“非纯黑”；不生成否定式正向词（修 A2、A3、C9）。
- 编译后跑静态校验：①同一提示词里出现互斥词对（遮脸 ↔ 面部可辨；全黑 ↔ 非纯黑）就报错；②正向词里有“无/不/非 + 名词”就报错；③不在 `characters_on_screen` 里的角色出现外貌锁就报错；④相邻镜首帧文字相似度超过阈值就提示（A5）。

### 3.2 LLM 只做受约束的填充
- LLM 用来补 Spec 里写作者没写的字段（人物表行、场景表、H3 英文正文、EN 外貌短语），不能直接产出最终提示词。
- 输出用 JSON Schema 约束（例如 `{h3_body: str, used_character_ids: [..], dialogue_echo: [..]}`），然后跑确定性校验：
  - `dialogue_echo` 必须逐字等于 Spec 台词，且 `<d>` 里只有台词（§4 重放中 S2 的 3/4 次失败都能被这条拦下）；
  - 每个在画角色的 EN 锚点短语（含族裔）必须原样出现；
  - 不出现 `mentioned_only` 角色的外貌；
  - 不出现人名（H3 不认识名字）；
  - 动作动词集合 ⊆ motion 动作集合（防止 B2 那种拆镜残留），超出的只提示。
- 不通过 → 带着校验错误重试，最多 N 次 → 仍失败就标 `needs_writer`，不进渲染。
- 每次调用记录 provider、model、prompt 哈希、usage、费用和输出，存成 Artifact，可以重放。

### 3.3 Provenance 与可重放
- 每个 Artifact（图、视频、音频、时间线）记录：`plan_hash`、`spec_rev`、上游 Artifact id + sha、实际执行的 workflow JSON 全文（发给 ComfyUI 的那份）、worker / GPU、耗时、QC 结果。图像后处理（校色、锐化、缩放）作为新 Artifact 记录，不覆盖原图（修 E4、C3 元数据丢失）。
- `compiled.json` / `visual_spec.json` 不再原地覆盖，按 `spec_rev` 分目录保存，或做成内容寻址存储。
- 一致性检查：视频作业的首帧 Artifact 和提示词必须来自同一个 `spec_rev`，否则拒绝派单（修 E5）。
- `replay(artifact_id)`：用记录下来的 workflow JSON 原样重跑，验证结果可复现。

### 3.4 闸门顺序固定
1. 资料闸门（Spec 完整）→ 2. 编译静态校验 → 3. 出片前检查（首尾帧差、LoRA / 参考可用、帧数 ≤ 道上限）→ 4. 出片后 QC（运动、OCR 防字幕、ASR 对台词 CER、VLM 核对 must 事实、朝向、在画人数）→ 5. 定稿（auto_lock 只能定稿 QC 全通过的版本，并记录执行者）→ 6. 合成只取定稿版本，时间线记录每镜 artifact id（修 E1、D3、D6、C4、C6、C8）。

### 3.5 作业持久化与 API 解耦
- 作业队列改成独立持久化（SQLite / 文件 WAL），worker 是独立进程，API 只负责读写队列。API 重启不影响正在跑的作业（修 E6 的 9 个“API 重启中断”）。
- 回写分两步：先存 Artifact 原件和 workflow，再更新索引。schema 校验失败只影响索引，原件不丢；之后可以重新索引（修 E6 的 `gpu36:0` 事件：4 个已出片的结果丢失）。
- 整集运行记录追加写，不覆盖（修 E6 的 run 记录丢失）。
- 失败隔离：一镜失败只阻塞依赖它的下游，其他镜照常进行；OOM 自动改派到长镜头道，不用补丁 LoRA（C10）。

### 3.6 音频与时长作为约束建模
- 合成前求解每镜的时间约束：独白 / 对白时长 ≤ 镜头时长 − 余量，不满足就在导入时报给写作方（D2）。
- 对白来源默认 H3 原声；TTS 只用于独白，以及 ASR 不过时的兜底（D1，需项目方点头）。
- 一集只用一个音乐来源：H3 镜内音乐和整集 BGM 二选一，由 Spec `audio.music.mode` 决定；BGM 按实际时间线时长和镜头起点生成（D4、D5）。

## 4. 分阶段计划

| 阶段 | 内容 | 产出 / 验收 | 风险控制 |
|---|---|---|---|
| P0（1–2 天，止血） | ①assemble 只取 locked 且 QC 不是 fail 的版本，时间线记 take 号和 plan_hash；②撤销 ep02 夜间 auto_lock 的“自动测试定稿”（项目方闸门）；③`align_first_only` 换成 I2VA 正文模板，至少删掉正文里的 Picture 2 句；④修 Take.gpu 类型（int\|str）；⑤坏图闸门按“后处理后尺寸”比较；⑥cfg=1 时不记录、不展示 negative；⑦present_characters 排除“X 的 Y”所属格 | ep02 重新合成可追溯；不改任何剧本 | 每项都是小改动，可以单独回滚；跑全量测试 |
| P1（3–5 天） | Shot Spec v2 schema + 角色 / 场景 / 造型注册表；导入器把 v3.1 / Qwen / PREP 统一转成 Spec，并显示差异；资料闸门改读 Spec；schedule.json 等旧映射改由 Spec 派生 | ep02 的 Spec 完整度报告；人物表族裔、场景底图、男角身份参考到位（资产与写作由项目方 / 写作方确认） | 旧 compiled 路径并行保留，开关切换；先只对 ep02 启用 |
| P2（3–5 天） | 纯函数编译器 + RenderPlan + 静态校验；LoRA 规则改为由 Spec 决定；后缀条件化；I2VA / FL2VA 双模板 | 同一 Spec 编译两次，plan_hash 相同；ep02 11 镜静态校验 0 error | 用 ep01 / ep02 的历史 compiled 做差异对照，人工抽查 |
| P3（3–5 天） | 作业队列独立持久化 + worker 进程化 + 两段式回写 + Artifact provenance + replay | API 随时重启不丢作业；随机抽 3 个 Artifact 能逐位复现（或在同 seed 下 SSIM ≥ 阈值） | 新旧队列并存一周，只把新作业切过去 |
| P4（2–4 天） | LLM 受约束填充（JSON Schema + 校验 + 重试 + 费用记录），先用在 H3 正文和人物表补全 | 重放集（ep02 11 镜 × 3 次）台词逐字率 100%、族裔覆盖 100%、未在场角色外貌 0 | 每次调用有预算上限；校验失败绝不进渲染 |
| P5（3–5 天） | QC 闸门：OCR、ASR-CER、VLM must 事实核对（在画人数、朝向、遮挡），接到定稿闸门和画布 | ep02 现有版本里 C4 / C6 / C8 能被自动拦下 | 阈值先只提示一周，用项目方审片结果校准后再拦 |
| P6 | 音频时长约束求解、单一音乐来源、TTS 只做独白 | 无盖镜；BGM 与时间线对齐 | 配乐方案由项目方选 |

## 5. 风险

1. **迁移期双轨**：旧 compiled.json 和新 RenderPlan 并存时，画布可能显示不一致。对策：画布读 RenderPlan，旧字段只读，并加“来源”标记。
2. **严格闸门降低出片量**：资料不全就不出，短期内能出的集会变少。这是有意为之；需要项目方确认“宁缺勿滥”的取舍（项目方闸门）。
3. **VLM / OCR 质检有误报**：先只提示、校准后再拦，避免像 E7 那样误杀。
4. **LLM 校验过严导致重试成本上升**：每次调用设预算上限并记录费用；按 §4 重放，6 次调用约 $0.0066，量级很低。
5. **H3 本身的局限**（念错字、4 帧一顿、单轨音频）重构解决不了，只能靠 QC 拦和换配方。重构的价值是让这些问题可见、可追溯、不会悄悄进成片。
6. **资产缺口**：顾沉 / 陈宇的身份参考、场景底图要生成并由项目方定稿，这是 P1 的前置条件，不属于代码工作。

## 6. 需要项目方定的事（只列，不代定）

1. 是否撤销 ep02 夜间 auto_lock 的 5 个“自动测试定稿”（S2/S4/S6/S9/S10）。
2. 是否导入 PREP 补全稿（人物表、场景表、造型）作为 ep02 的新剧本版本。
3. 对白默认来源改成 H3 原声；音乐来源是 H3 还是整集 BGM。
4. 资料闸门“缺就不出”是否对项目方手动出片也生效（现在只拦自动出片）。
5. 纯独白镜要不要在 H3 正文里加 “lips remain closed”，以及要不要试官方画外音写法，把独白交给 H3 自己出声（这两项都会改动剧本里的 H3 正文，见 §7.3 和 conformance B13）。

## 7. 吸收官方短片管线（MiniMax-H3 skills，提交 199b7d0e）

参考：`data/ab/owner_workflows/minimax_h3_official_skills/3d-animation-short-generator/references/` 里的 shot-table-spec、storyboard-guidelines、qc-checklist、fallback-policy、model-selection；`co-op-game-intro-generator/references/h3-video-prompt-template.md`；`h3-prompt-writing/references/base-en.txt`、`ref-en.txt`。逐条格式对照见 `docs/ep02_iter/h3_official_conformance.md`。

前提：官方这套是 **3D 卡通、自选画幅、交互式选择卡** 的流程；我们是 **9:16 写实短剧、写作模型全自动 + 项目方闸门**。下面逐条写明采用、改造后采用、不适用，以及理由。

### 7.1 Shot Spec 对齐官方“标准镜头信息表”（六列）

| 官方列 / 子字段 | 对应的 Shot Spec 字段（§2） | 处理 | 理由 |
|---|---|---|---|
| Shot ID & Duration（`S03 / 6s`） | `id`、`duration_s` | 采用 | 已有 |
| Continuity Handoff（承接上一镜结尾：道具位置、视线、姿势、声音桥；引出下一镜开头） | 新增 `continuity: {from_prev, to_next, hard_cut}` | **采用** | ep02 S6→S7 林晚左右互换、S5 尾帧换鞋，都是因为缺这一列。v3 剧本本来有“衔接”行（PREP 稿有，生产稿没有） |
| Reference Anchors · Fixed Landmarks（场景卡里的地标和屏幕位置） | `scene.landmarks: [{id, screen_pos}]`，从场景注册表继承 | **采用** | 审计 A8：场景为空，办公室布局每镜都变 |
| Reference Anchors · Character Positions（每个角色的屏幕位置、前中后景、朝向、起始姿势） | `characters_on_screen[].{screen_pos, depth, facing, pose}` | **采用**（必填） | 审计 A4 / A9 / C4：顾沉被放进出租车、朝向填错、S7 顾沉正对镜头。co-op 模板“P1 永远在左、P2 永远在右”的固定站位，同样适用于双人镜 |
| Reference Anchors · Exited Character Status（上一镜在、这一镜不在的人去了哪里） | `exited: [{id, where, why}]` | **采用** | A4 的反面，例如 S8 写 `gu_chen — 留在办公室`，编译器就不会注入他 |
| Reference Anchors · Lighting Baseline（主光、补光、轮廓光方向 + 本镜修正） | `scene.lighting: {key, fill, rim, modifier}` | **采用** | 代替现在从自由文本里猜 `lighting.sources`（A8 误报） |
| Identity bindings（准确的角色卡、场景卡名） | `characters_on_screen[].id` + 注册表 rev；`scene.id` | 采用 | 已在 §2 |
| Hook Type + 钩子密度 | `hook`（可选标注） | **不作为闸门** | 节奏和内容判断属于写作方和项目方；Claude 不评价内容（硬规则） |
| Per-Second Directives（每秒五要素：动作/姿势/表情、运镜、位置、声音、交接） | `motion.beats: [{t0,t1,action,camera,position,audio,handoff}]` | **改造后采用**：≥ 6 s 的镜头按约 2 秒一段，由写作模型填，校验时间无空隙 | ep02 有 6 个静止镜头，FL2VA 正文缺运动路径（conformance B8），分段能逼出“首帧 → 中间变化 → 尾帧”的路径。不强制逐秒，是因为写实表演逐秒切会碎；H3 提示词本身也不用时间码，分段只在 Spec 里，由编译器合成连续英文 |
| 夸张弹性表演、荷兰角、景别必须交替 | — | **不适用** | 3D 卡通风格规定；写实短剧按剧本景别走 |
| Shot Description 里的 negative prompt | — | **不采用** | H3 和 Qwen-Image Turbo 都是 cfg=1，负面词不生效（审计 A3） |
| Audio & Dialogue Track（Narration / Dialogue 带时间段、SFX 时间点、`narrator-mouth-closed: true`） | `audio.dialogue[].{t0,t1,tone}`、`audio.voiceover.{t0,t1}`、`audio.sfx[]`、`audio.mouth` | **采用** | 审计 D1 / D2（独白盖三镜、嘴型对不上）；`mouth-closed` 对应 H3 官方画外音写法（conformance B13） |

### 7.2 官方 Shot Table 自检（Step 5.5，六项）并入资料闸门

| 官方自检项 | 处理 | 位置 |
|---|---|---|
| 1 钩子密度 | **不适用**（内容判断） | — |
| 2 单镜时长 ≤ 15 s，超过就拆 | 采用（已有 lint H3-A11：4–15 s）；拆镜只提示，交给写作方 | 编译静态校验 |
| 3 每镜重要角色 ≤ 3 人 | 采用；另保留本地规则 H3-D7（普通对话镜每镜一人发声） | 资料闸门 |
| 4 同一室内场景连续两镜以上，地标和光线基线要继承，否则写连续性说明 | **采用**，硬校验 | 资料闸门（纯函数） |
| 5 分段指令覆盖整段时长、无空隙 | 采用（按 7.1 的约 2 秒一段） | 资料闸门 |
| 6 跨镜衔接链不能矛盾；视线、位置、道具、光线翻转要标 `HARD CUT` | **采用** | 资料闸门 + 画布“衔接链”视图 |

### 7.3 官方 QC 清单（Step 8 / 9 与重新生成纪律）并入 §3.4 闸门顺序

| 官方检查 / 规则 | 并入哪一步 | 处理 |
|---|---|---|
| 角色一致性 | 4 出片后 QC：人脸身份相似度（对照身份参考图）+ VLM 核对在画人数、朝向 | 采用 |
| 场景连续性（对照 Reference Anchors） | 4 出片后 QC：VLM 核对 `scene.landmarks`、`screen_pos` | 采用 |
| 对白可懂度 | 4 出片后 QC：ASR 和剧本对照 CER（审计 C8） | 采用 |
| 拟音 / SFX 同步 | 4 出片后 QC | 改造后采用：先人工审，系统只提示 |
| 整片一条连续 BGM，按成片实际节奏匹配，对白下压；**不要逐镜生成 BGM** | 6 合成（§3.6） | **采用**（审计 D4 / D5）。H3 镜内配乐和整集 BGM 二选一，由项目方定 |
| 保留原片音频和 SFX，除非用户要求替换 | 6 合成 | 采用：对白默认用 H3 原声（审计 D1，需项目方点头） |
| 除非用户要求，不加字幕或文字；成片不能有分镜标签残留 | 4 出片后 QC：OCR | 采用（审计 C6 的“冷”字） |
| 缺失 / 偏弱镜头 | 4 运动 QC（已有 QCV） | 已有 |
| 重新生成纪律：下游必须用最新**已批准**版本；不能悄悄混用新旧素材；多版本并存时先指明当前版本 | §3.3 provenance + 6 合成只取定稿 | **采用**（审计 D6 / E5 / E8） |
| 每个确认点都用选择卡（画幅、时长、分镜模式、模型、分辨率、成片） | — | **改造**：我们是全自动，只有项目方闸门（定稿、花钱、推翻旧决定、删除）在画布上用选择卡；画幅（9:16）、分辨率（768P）固定 |

### 7.4 官方 fallback 阶梯并入失败隔离（§3.5）

| 官方阶梯（H3） | 我们的版本 | 理由 |
|---|---|---|
| 第 1 次重试：同一镜重出，提示词前缀**逐字引用该行的 Reference Anchors** | **采用**：重试时编译器在 H3 正文首句注入本镜锚点（在画角色 EN 短语、屏幕位置、地标），不只是换 seed | 现在重出只换 seed（QC 文档 §6.1），漂移原因没有处理 |
| 第 2 次重试：缩到 ≤ 6 s，多出的秒数拆成新行，重跑自检 | **改造**：系统只生成“建议拆镜”交给写作方，不自动改剧本 | 拆镜改变剧本结构，属于写作方或项目方的决定 |
| 第 3 次重试：换模型（Seedance 2.0） | **改造**：在本机已验证的配方之间降级（official_base + 只给首帧 → pika_flex + 只给首帧 → Ref2VA 实验），按成本档位记录 | 我们没有 Seedance；配方依据见 QC 文档 MOT |
| 三次失败后暂停，让用户选（换模型 / 放宽 / 跳过并标占位 / 人工给参考） | **采用**：标 `needs_owner`，画布出选择卡；合成时该镜放占位并写进 timeline warnings，**不阻塞其他镜头** | 失败隔离 |
| 成片偏离锚点：引用锚点重出；不行就换模型；**不要把修正过和没修正的片段悄悄混着合成** | 采用：定稿闸门要求全集用 QC 通过的定稿版本 | 审计 D6 |
| 铅笔分镜的降级阶梯 | **不适用** | 我们不出铅笔分镜，首帧 / 尾帧本身就是可视化 |

### 7.5 其他官方要点

- **model-selection**：H3 支持 768P / 2K。我们在 3090 上 768×1344 已经接近显存上限，2K 需要官方没有开源的 Regenerate-2K（MOT 结论）。分辨率选择卡**不适用**，保持 768P。
- **storyboard-guidelines** 的“文字分镜文档是权威渲染参考、抽出的单镜节点优先、改完再并回”：等同于 Shot Spec 单一事实来源 + rev。**采用**理念，不采用画布节点形式（我们的画布一镜一行已经覆盖）。
- **co-op 模板**：“每个身份一张参考图 + 固定左右站位 + 禁止身份互换、脸部融合”。**采用**，落地方式是 Ref2VA：每个角色一个 `<Subject N>`，站位写在 Shot Spec（conformance R2）。
- **ref-en 六段格式**：作为 P4 实验路径，由编译器按官方六段确定性生成。现在 lab 的自定义格式（`tools/lab_ep02/ref2va_prompt.py`）不能代表 Ref2VA 的真实能力，需要重做（conformance §2）。

### 7.6 对分阶段计划（§4）的增补

- P0：加上 conformance §4 的 F1–F8（已发给 FIX）。
- P1：Shot Spec 增加 `continuity`、`scene.landmarks`、`scene.lighting`、`characters_on_screen[].{screen_pos,depth,pose}`、`exited`、`motion.beats`、`audio.*.{t0,t1}`、`audio.mouth`；资料闸门加入 7.2 的第 2–6 项。
- P2：编译器为 I2VA / FL2VA / L2VA / T2VA / Ref2VA 各出一套模板，lint 按模式分支；重试时注入锚点句。
- P5：QC 加入 7.3 的身份相似度、地标 / 站位 VLM 核对、OCR。
- P6：一集一条 BGM。
