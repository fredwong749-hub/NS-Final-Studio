# NS-Final Studio 生产 SOP：从一部新剧本到 4K 成片

> 2026-10-30 起草（claude-gpu3）。依据《为他而骚》第一部实际跑通/踩坑的流程整理，目标是**第二部剧可以在界面里一键启动、全自动跑完**，人只在少数关口拍板。
> 需求以 `docs/REQUIREMENTS.md` 为准，画面规则以 `config/visual_bible.toml` 为准，分工以 `docs/TASKS.md` 为准。

---

## 0. 总览

```
① 立项 ─► ② 剧本导入与校验 ─► ③ 风格SOP（视觉圣经）─► ④ 人物与资产 ─► ⑤ LoRA 训练
   ─► ⑥ 剧本加强（v3：欲望/姿势/时长/声音/配乐）─► ⑦ 画面说明（Frame Spec）
   ─► ⑧ 首帧/尾帧多轮出图 ─► ⑨ 视频（H3 FL2VA）─► ⑩ 成集 QA ─► ⑪ 声音（配乐/分层/配音/混音）
   ─► ⑫ 4K 放大 ─► ⑬ 成片装配与导出
```

| 关口（人拍板） | 在哪一步 | 界面里做什么 |
|---|---|---|
| G1 风格定稿 | ③ | 选风格模板、上传色调参考图、确认视觉圣经 |
| G2 人物定妆 | ④ | 为每个角色从候选中选定身份母版（写实强度可选） |
| G3 剧本加强确认 | ⑥ | 抽查 v3 的对照（原文 vs 加强），一键采纳或退回 |
| G4 样片锁定 | ⑨ | 看第 1 集样片，锁定生产参数（PIPELINE_LOCKED） |
| G5 成片验收 | ⑬ | 看每集成片，标记发布/返工 |

其余全部自动；任何自动步骤失败超过 3 次进入**异常队列**（界面可见），不阻塞其他集。

---

## ★ 分工：Qwen 负责内容，Claude 只写系统（硬规则，2026-10-30 项目方定，所有剧本、所有会话适用）

> 项目方原话：“qwen负责剧本，镜头，提示词等内容写作”；“claude opus 负责写系统”；“claude不做任何内容参与，也不评价内容，分工清晰，qwen主要负责内容”。详见 `docs/REQUIREMENTS.md` G1–G3。

- **Qwen（gpu3 常驻写作模型）**：剧本、分镜/镜头、画面与视频提示词、训练集标注、样图与评测提示词、造型/妆容描述，以及一切内容上的评价与挑选。
- **Claude（所有 Claude 会话）**：只写系统——代码、流水线、调度与锁、数据格式与校验、技术检查（字段、哈希、尺寸、自动 QC），并把 Qwen 的输出原样接入。**不写、不改、不润色内容，不评价内容，也不参与任何内容审核**（不审阅、不批准/驳回、不挑选、不打分）；遇到内容问题交给 Qwen 或项目方。自动 QC 属于系统代码，Claude 可实现，标准由项目方/Qwen 定（REQUIREMENTS G5）。Blender 代码与 LoRA 也归 Qwen（G4）。
- **项目方**：各确认关口照旧拍板。
- **gpu3 分卡**（封板修复 2026-10-30，按 REQUIREMENTS G3）：GPU1 = Qwen LLM 常驻（:8098）；GPU0 / GPU3 = Qwen LoRA 训练 / Blender，渲染时临时借用（按 train.lock / gpu.lock 在任务边界接手，不杀进程）；GPU2 坏卡永不使用（T53）。

## ★ 阶段闸门与资源优先级（硬规则，2026-10-30 项目方定，所有剧本适用）

> 项目方原话：“剧本必须把资产生成完毕，然后图片什么的，最后才分配资源生成视频；如果每个镜头缺少任何一个环节，都不会去 render 视频……用这个 SOP 来把控，不要重复制造垃圾。”

### 1. 五个阶段，严格按顺序，上游没过就不进下游

| 阶段 | 内容 | 出口闸门（全部满足才算过） |
|---|---|---|
| **S1 剧本** | 导入 → v3 加强 → 校验 | 每个镜头都有：img、motion、时长、sound、【H3 audio】、【配乐】cue、**`**H3提示词**`**（`S1-W7`）；每集都有配乐/【BGM】；**提示词符合 H3 官方规范**（§6 “H3 上游写法”逐条校验，`S1-W1`–`S1-W6`）；校验 0 错；G3 采纳 |
| **S2 资产** | 角色母版与多角度底板/表情/妆容（G2）；造型 looks；每场景底图（场景 master plate）；每镜角色状态表（state timeline）；剧本触发词用到的**全部 LoRA**（身份/服装/鞋/饰品/姿势）训练完、样图过审、登记进 LORA_REGISTRY | 剧本里出现的每个触发词都能在 registry 里找到已验收的 LoRA；每个场景有底图；状态表覆盖每个镜头 |
| **S3 画面** | 每镜首帧 + 尾帧（同一条 take 链，768×1344），场景内衔接链，帧闸门 + 衔接闸门 | 每镜首尾帧都过闸门；每集衔接对照表生成且抽查通过；首集 G4 样片锁定参数 |
| **S4 视频** | H3 FL2VA（官方提示词格式，§9A），视频闸门（首尾帧偏移、片中人脸） | 进入前（就绪闸门）：8 要素 + 衔接 + 帧闸门 + **逐镜审计 pass**（★5，`R-C*`、`H3-*`、`P-*`）+ **提示词符合 H3 官方规范**（§9A.1 逐条：对齐句与 S.SS、空行、三字段顺序、英文正文、`<d>[Chinese]` 台词逐字、无否定句、收敛到 Picture 2、帧数在 17k+5 网格上）；出口：每镜视频过 QC，`qa.json` 每镜 pass |
| **S5 成片** | 声音（配乐/分层/混音）→ 装配 → 4K | `_final` 只在 qa.json 全 pass 时写；G5 验收 |

- 闸门按**镜头**和**集**两级判断：某镜在 S3 没过，这一镜绝不进入 S4；某集有任何一镜没过 S4，这一集绝不装配 `_final`，只能出 `_PREVIEW_未完成`。
- 声音资产（配乐、音效库）只用 CPU，可与 S3 并行；不占 GPU 优先级。
- 镜头卡片（画布）显示每镜 8 要素 + 衔接 + 所处阶段；缺什么标红。不满足闸门的镜头，界面上的“出视频”按钮不可用。

### 2. GPU 资源按阶段优先级分配

优先级从高到低（同一时刻，高优先级有待办就不把卡给低优先级）：

1. **S1 剧本 LLM**（v3 改写；短时）
2. **S2 资产与 LoRA 训练**（训练集生成 + 训练；同级内按“被最多镜头用到”的 LoRA 先做）
3. **S3 首尾帧**（只做“它需要的 LoRA 已经验收”的镜头；按集顺序，场景内串行）
4. **S4 视频**（只做通过就绪闸门的镜头）
5. **S5 4K / 重型后期**

- 多部剧并存时：先按阶段优先级，再按剧的立项先后。
- GPU 2 永不使用。**现行（封板修复 2026-10-30，D-22）**：阶段调度器 ns-sched（T46）**关闭**，改用固定分卡（见 ★ gpu3 分卡）+ 锁协议，渲染借卡由项目方 / 总调度手动安排；下面两条只在将来重新启用调度器时适用。
- GPU 借用（lend）只能由调度器写，各流水线只认调度器分给自己的卡。
- 调度器每 5 分钟重算一次；任何流水线想跳级（例如资产没齐就出视频）会被拒绝并记入异常队列。
- 测速、基准测试（bench）不属于任何生产阶段：只能用调度器标记为空闲的卡，每次不超过 10 分钟，有 S1–S5 待办时让出（协调 2026-10-30，起因是巡检 #4 发现 sage-bench 占用 GPU1）。

### 3. 防止“重复制造垃圾”

- 出视频前必须过就绪闸门（8 要素 + 衔接 + 帧闸门）；不满足的请求直接 `skipped`，不消耗 GPU。
- 每个镜头只有一条 take 链：首帧、尾帧、视频同源；笔记本与 gpu3 不得各出一套。
- 剧本或资产变了（sha 变化）→ 只把受影响的镜头退回对应阶段，不整集重跑。
- 每阶段第一次在新剧上跑时，先做 1 集样本、人看过再放量（首集即 G4）。

### 4. 如何提问 SOP 管理员（fredw-5c；claude-sop 已结束）

- **谁管**：fredw-5c（2026-10-30 起接替已结束的 claude-sop，总调度 fredw-b3 指派）是本 SOP 与 `docs/SOP_parameters.md`（参数锁定表）的唯一写入者；下文的“claude-sop”均指 SOP 管理员。它只在纸面上放行或拦截；真正执行拦截的是调度器（T46）和渲染器。需要停掉什么，由它通知协调（claude-gpu3）。
- **什么时候问**：每一步动手前都要问，包括进入新阶段、启动批量、改参数、改编译输入（剧本、造型、视觉圣经）。
- **怎么问**：发一条消息，写明“即将在 <剧/集/镜> 做 <事>，阶段 Sx，用 <参数/模型/LoRA>，依赖 <上游产物>”。
- **它查什么**：
  1. **顺序**：上游阶段的出口闸门是否真实通过（S1 校验与 G3；S2 的 LORA_REGISTRY 验收、场景底板、状态表；S3 的 `renders_gpu3/epXX/SN/status.json` 帧闸门与衔接）。
  2. **参数**：与参数锁定表逐行比对。表中「待验证」的值不能当作锁定值用。
  3. **资源**：是否符合 GPU 阶段优先级、是否持有调度器分配给自己的卡；GPU2 一律不得使用。
  4. **防垃圾**：是否只有一条 take 链；是否只退回受影响的镜头；首次跑新剧是否先出 1 集样本。
- **回答格式**：
  - ✅ 顺序与参数相符；或
  - ❌ 写明违反的条款或参数行，以及必须先完成什么。
- **参数怎么改**：发消息并附证据（A/B 图或测量值、项目方原话、或已合并且带测试的修复）。经 claude-sop 核实后写进锁定表并记入变更记录。不得降低项目方定下的规则；有冲突时上报协调。
- **巡检**：claude-sop 约每 30 分钟对比一次 gpu3 实况（运行中的 unit、lock/lend/assign、status.json、scheduler_plan.json）与本 SOP，发现违规就报告协调。

### 5. 逐镜审计（硬规则，2026-10-30 项目方定）

- 每一镜在出视频前都必须通过逐镜审计。审计脚本是 gpu3 `ns-studio/scripts/shot_audit.py`，结果写进 `status.json.audit = {verdict, failures[{rule_id, sop_ref, detail}], warnings[], overrides[]}`。
- **verdict ≠ pass 的镜头，视频渲染器和调度器一律硬拦截**，不消耗 GPU。
- 规则清单只有一份：`docs/audit/rule_ids.md`，代码和文档共用。本 SOP §6、§8、§9A 与 `SOP_parameters.md` 里每条规则都标了 rule_id，前缀含义：
  - `H3-A*`：提示词结构
  - `H3-D*`：对白与人声
  - `H3-S*`：声音字段
  - `P-A*`：模型与采样
  - `P-B*`：帧与几何
  - `R-C*`：就绪闸门
  - `S1-W*`：剧本写法
  - `S3-K*` / `S3-F*`：首尾帧与帧闸门
- 级别：已锁定的规则为 **block**；「待验证 / 需 A/B」的规则为 **warn**（记录、不拦截），锁定后由 claude-sop 改为 block。
- **豁免**：只凭项目方原话，写进 `audit.overrides[{rule_id, owner_quote, by, at}]`；没有原话的豁免无效，审计按 fail 处理。不能整镜豁免，只能逐条 rule_id 豁免。
- 改规则的顺序：先改 `rule_ids.md`（claude-sop），再改代码；编号不复用、不改义。
- claude-sop 审阅 `docs/audit/shot_audit_report.md`，把漏掉的规则、实现不符的规则报给协调。

---

## 1. 立项（项目文件夹）

新项目 = 复制模板目录，界面「新建剧」一步完成：

```
projects/<剧名>/
  script/            原始剧本 + 图片提示词 + 纠正器（只读原件）+ v3 加强版
  config/            visual_bible.toml（由模板生成）、adult_overrides.json、face_reference.json
  assets/            characters/<id>/{plates,expressions,items,looks}、style/、clothes/、heels/、piercing/、pose/
  data/              import/、looks/、renders/（笔记本出图）、renders_gpu3/（gpu3 视频）、music/
  previews/          每一步给人看的拼图
  docs/              本剧的 TASKS、QA、变更日志
```

（第一部《为他而骚》目前仍在仓库根目录；第二部起放进 `projects/`，代码共用。）

## 2. 剧本导入与校验

- 格式：沿用《为他而骚》的 Markdown 结构（`## epNN《》`、`**镜N｜img**`、`**motion**`、`**sound**`、`**对白**`、`🎙`（K3：`**负面追加**` 已作废，导入器仍认旧剧本）；必写 `**时长**`（K4），可选 `**配乐**`、`【亲密声】`、`【H3 audio】`、`【配乐】`、触发词前缀）。
- 导入器：`tools/import_script.py --script <file>` → `data/import/script_*.json`（每镜 `adult`、`duration`、对白/舞台提示拆分、触发词）。
- 自动校验：集数×镜数、对白每秒 ≤3.5 字、触发词与 LoRA 注册表一致、装饰状态表完整；问题列入异常队列。
- **剧本唯一写入者**：claude-gpu3（其他人改剧本发消息）。每次修改留 `*.bak-<日期>-<原因>` 备份并同步 gpu3（sha256 校验）。

## 3. 风格 SOP（视觉圣经）

- 从 `templates/visual_bible.template.toml` 生成 `config/visual_bible.toml`（界面表单填写）：
  - 画面：镜头感（例：徕卡锐利度、85mm f/1.2、奶油虚化、浓郁暖色）、色调参考图、无字幕、干净。
  - 写实：research v8（Base 35 步真 CFG、krea2 胶片质感 0.5、1.5MP + 0.30 二次、不用“精致/娃娃感”）；**写实只作质感，不改项目方认可的人物长相**。
  - 材质规则：如“漆皮 = 镜面湿亮”“高跟 = 12cm 针形细跟”——出现关键词自动追加。
  - 镜头类型规则（纠正器）、安全镜规则、成人镜规则、欲望强度默认档（`docs/desire_amplification.md`）。
  - 声音规则（`docs/intimate_audio.md`）：主角固定声线、只让一人发声、标志音库。
  - 配乐风格（全剧基调）。
- 写入剧本头部的统一后缀（img/motion）与基础负面；界面里可预览“一镜示例提示词”。

## 4. 人物与资产（每个角色）

1. 身份：项目方给参考图（必须确认为 AI 生成/虚构成年人，记录在 `config/face_reference.json`）→ 生成 3 档写实强度候选 → **G2 选定母版** `plates/master.png`。
2. 多角度底板（正/3/4/侧/背/全身）+ 6 表情（灰底中性服装，避免照搬造型照的衣服项链背景）。
3. 妆容库（素颜/浓妆/夜场…）、发型、美甲（如 5cm 透明钻甲/2cm 脚甲）。
4. 单品库：服装、鞋、饰品——每件出“产品图 + 穿着图”；暴露类单品只做产品图（笔记本侧），穿着图走 gpu3。
5. 造型 A/B/C 与**造型排期**（角色 × 部件 × 集段，`data/looks/`）；界面甘特图调整，改动只把受影响镜头标为过期。

## 5. LoRA 训练（gpu3，GPU0 / GPU3；GPU1 = Qwen LLM 常驻，封板修复 2026-10-30）

| 类型 | 数据来源（只用合成/无人商品图） | 触发词示例 |
|---|---|---|
| 身份（图像 + H3 视频） | 母版 + 多角度底板生成的 30–40 张静图 | `lnwan01` |
| 饰品 | Blender 精确建模 + 遮罩贴回写实化 | `nprng2` `lbrng9` `lbrng9_beads` |
| 服装/鞋 | 无人商品图 + 合成试穿（真人照只当款式参考） | `hh12clear` `ptxharness` … |
| 姿势 | Blender 体位预设 + 写实化（`docs/pose_library.md`） | `pose_<name>` |

- 训练前出数据集拼图，自动审核（鞋跟粗细、漆皮光泽、饰品数量）+ 必要时 G 关口抽查。
- 训好后：最佳检查点 → `ComfyUI/models/loras/` + `LORA_REGISTRY.json` + 剧本图片提示词「数据E」注册表 + `assets/<类别>/`（附 README、sha256）。
- 剧本里已写的触发词会在 LoRA 注册后自动生效（未注册时自动剥离）。

## 6. 剧本加强（v3，可选但默认开）

- 本地无审查模型（gpu3 `127.0.0.1:8097`，最好占一张 GPU）按规则改写 img/motion：欲望强度、身材镜头数、亲密场景的明确体位（`pose_*`）、每镜 `**时长**`、`【亲密声】`/`【H3 audio】`、每集 `**配乐**`/`【BGM】`、每镜 `【配乐】`。
- 硬性校验：结构、原文对白/独白逐字不变、连续性事实（饰品/服装/鞋/美甲/发型）、成年与自愿、不新增人物；失败重写 ≤3 次，否则保留原文并记录。
- 输出 `v3.md` + `v3_changes.md`（每集身材镜头/床戏镜头/平均强度/总时长）→ **G3 确认**后导入。

### H3 上游写法（S1 出口必查；v3 及以后所有剧适用，2026-10-30 项目方指令）

剧本写好的就该是“H3 可直接用”的素材。以下每条都进 S1 校验，任何一条不过就算 S1 校验报错：

1. `S1-W1` **motion = 一个连续镜头**：从首帧状态写到尾帧状态，中间没有剪辑；只有一个主动作、一个运镜。结束状态必须和尾帧（Picture 2）画得出来的样子一致，写在 motion 最后一个“——”之后，供尾帧编辑使用（visual_bible last_frame_keep）。依据 §9A.1 第 3–5 条。
2. `S1-W2` **时长 → 合法帧数**：`**时长**：N秒` 只写整数 N，必须落在 4–15 s（K4，每镜必写，系统不再默认 10 秒）；系统换算成 17k+5 网格上的帧数（向上取，见下表），实际片长交给 H3（以对齐句的 `S.SS` 为准，项目方 2026-10-30，h3_sound G13）；超过 15 s 的镜头拆成两镜。依据 §9A.3。

| 秒（≤） | 4.46 | 5.17 | 5.88 | 6.58 | 7.29 | 8.00 | 8.71 | 9.42 | 10.12 | 10.83 | 11.54 | 12.25 | 12.96 | 13.67 | 14.38 | 15.08 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 帧数 | 107 | 124 | 141 | 158 | 175 | 192 | 209 | 226 | 243 | 260 | 277 | 294 | 311 | 328 | 345 | 362 |

   对齐句里的 `S.SS` 取 `f"{帧数/24:.2f}"`（表中“秒”一行即此值）。
3. `S1-W3` **【H3 audio】 = 官方 soundscape 写法**：1–4 句英文，写环境声、动作声、非语言人声，不写台词，不写否定句。H3 原生音频只让林晚发声（亲密镜头强制；普通对话镜见 §9A.1 冲突说明）；配乐写进 `non_diegetic_music`（项目方 2026-10-30）：1–3 句英文，写乐器/速度/节奏/强弱；本镜无配乐写 `N/A`。
4. `S1-W4` **台词按说话人分条**：每句台词标明说话人（“（顾沉）…／（她）…”），原文逐字，标点不改；不用双引号包进 img 或 motion；🎙 独白单独成行（不进 H3）。编译器据此生成 `(S1)…<d>[Chinese] …</d>`。
5. `S1-W5` **首尾帧可生成**：首帧和尾帧必须是同一个镜头的起点和终点，即同一布景、同一光线、同一套服装；姿势变化在一个连续动作里能做到；景别变化不超过一个运镜能走完的范围（例如推近一档、上摇一段）。做不到的就拆镜，或标 `AddGuide` 中间关键帧（需 A/B）。
6. `S1-W6` img、motion 里的中英混写运镜（如 `camera push in 缓慢推近`）要能映射到 §9A.1 的运镜词汇和幅度、速度词。
7. `S1-W7`–`S1-W9` **每镜必须有 `**H3提示词**` 字段**（项目方 2026-10-30 指令，S1 必备）：
   - 由剧本写入者（v3 agent）直接写成 §9A.1 的官方 FL2VA 全文：对齐句（按本镜帧数算 S.SS）、空行、三个字段、英文正文、`<d>[Chinese]` 逐字对白、无否定句、`non_diegetic_music` 按 §9A.1（英文配乐或 N/A）、亲密镜只让林晚发声。
   - 这个字段在 S1 就要通过 H3-A/D/S 全部检查。
   - 出视频时原样使用，只允许按实际帧数重算 S.SS。
   - 缺这个字段，S1 不通过。
   - v3 在释放 GPU0 之前补齐。

## 7. 画面说明（Frame Spec）

共享模块 `ns_agent.frame_spec`：把剧本镜头拆成结构化画面说明（人物朝向/清晰度/占比/可见部位、饰品计数与位置、景别机位焦段、场景母版、首帧/尾帧状态、特殊手法、必有事实），再按模型渲染提示词（镜头与质感 → 身份参考角色说明 → 姿势表情 → 服装 → 饰品计数 → 鞋 → 美甲 → 场景光线 → 他人虚实 → 正面化约束）。项目方的“首/尾帧加强”字段原样追加。

gpu3 渲染字段（T08）：`focus_part`/`focus_label`（焦点部位）、每角色 `gaze_start`/`gaze_end`（camera/other/down/up/away/object/closed）、`screen_share_value`、只含表情词的 `expression`，以及从 `data/state_timeline.json` 原样复用的 `framing`/`faces_visible`/`prop_states`/`changes_within_shot`/`items_end`；拿不准的标 `*_source: guess`。格式见 `docs/frame_spec_compiler.md` §6。

## 8. 首帧/尾帧（多轮出图）

- 分工（封板修复 2026-10-30，现行）：成人判定 = 集标题 🔴 整集每镜都算成人（`config/adult_overrides.json` "per_shot": false）；本剧全部首尾帧由 gpu3 出（`config/shot_ownership.json`），笔记本不出本剧的帧；成人镜头由项目方本人启动（`TASKS.md` 规则 7）。
- 每镜：清单（`checklist.json`）→ 每轮 2–4 张候选 → VLM 逐项打分 + 人脸相似度/背景虚化/色彩/文字检测 → 定点修（局部重绘、ControlNet、Blender 难镜头）→ 最多约 4 轮。
- 尾帧以首帧为参考编辑出动作终态；两者都存为版本，画布显示。
- 色调轻度匹配到项目色调参考图。
- **为 H3 准备首尾帧（S3 闸门必查；`S3-K1`–`S3-K3`、`P-B2`）**：
  - 首帧和尾帧来自同一 take 链，同一布景、同一光线、同一服装和发妆；姿势变化可达；景别、机位在一个运镜范围内（§6 H3 上游写法第 5 条）。
  - 两帧都用同一种方式 center-crop + lanczos 到 768×1344，并记录 sha（§9A.3）。
  - 人物至少中景、脸要占足画面（远景小脸是 H3 的已知弱点）；剧本要求远景时，在 Frame Spec 里标为高风险镜头。
  - Frame Spec 的 `last` 状态 = motion 结束状态 = 视频提示词里 “settles into … Picture 2” 所描述的状态，三者必须一致。

## 9. 视频（gpu3 唯一出视频处）

- H3 FL2VA int8 + LightX2V 8 步（约 28 分钟/243 帧镜头）；亲密镜头若音质不过关改用 base 12–16 步或 10Eros 非加速（A/B 定）。
- 首帧 + 尾帧锁定；帧数按 `**时长**` 整数秒向上取 17k+5 网格（≥107 帧 = 4 s，≤362 帧，见 §6 表）。实际片长以 H3 输出为准（对齐句 `S.SS` = 帧数/24，243 帧 → 10.12 s），不再按剧本秒数后期裁切（项目方 2026-10-30，h3_sound G13）。
- 提示词、帧数、分辨率、采样参数全部按 **§9A H3 视频规范（官方）**；参数值以 `docs/SOP_parameters.md` 的 S4 表为准。
- 视频去重键：sha256(首帧)+sha256(尾帧)+提示词哈希+参数；同键不重渲。
- 重渲队列：画布 → `data/renders_gpu3/rerender_queue.jsonl` → gpu3 处理 → `rerender_events.jsonl`。

## 9A. H3 视频规范（官方）

> 2026-10-30 项目方指令：视频制作必须逐条遵守 MiniMax 官方 H3 提示词指南和参数要求；剧本与镜头提示词的写法也要服从它。维护：claude-sop。
> 每条规则都标了来源，抓取日期均为 **2026-10-30**。没能抓到原文的规则标「待验证」，不得当作锁定值。来源缩写：
> - **[G]** 官方提示词指南 <https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/docs/VIDEO_PROMPT_WRITING_GUIDE_base_en.md>
> - **[K]** 官方改写技能 <https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/SKILL.md>
> - **[C]** ComfyUI 提示词页 <https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide>
> - **[CN]** ComfyUI 原生节点文档 <https://docs.comfy.org/tutorials/video/minimax/minimax-h3-native>
> - **[N]** ComfyUI 节点源码 <https://github.com/Comfy-Org/ComfyUI/blob/master/comfy_extras/nodes_minimax_h3.py>
> - **[M]** FL2VA model_index <https://huggingface.co/MiniMaxAI/MiniMax-H3/blob/main/FL2VA/model_index.json>
> - **[L]** LightX2V Turbo 规格表 <https://github.com/ModelTC/Minimax-H3-Turbo>
> - **[LH]** LightX2V HF 文件列表 <https://huggingface.co/lightx2v/Minimax-h3-Turbo/tree/main>
> - **[R]** 本地调研 docs/research/h3_prompt_and_fl2v.md（社区来源，置信度见原文）

### 9A.1 FL2VA 提示词结构（逐字遵守）

最终提示词只能是下面四块，顺序固定，字段名一个字母都不能改（[K]：“Preserve the exact field names, section order, labels, and timing notation”）：

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.

integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...
```

| rule_id | 规则 | 来源 |
|---|---|---|
| H3-A1 | 第一行是对齐句（原文逐字，包括破折号 —）。`N` = 实际最后一个镜头的编号（我们是单镜头，所以写 `Shot 1`）；`S.SS` = 有效时长，**保留两位小数**，按 `f"{frames/24:.2f}"` 计算（243 帧 → `10.12`）。原文：“The instruction must be the first line of the final prompt, followed by one blank line before the core fields.” | [G] |
| H3-A2 | 对齐句后空**一行**，然后依次写 `integrated_multimodal_description` → `overall_soundscape` → `non_diegetic_music`，字段之间空一行 | [G][K] |
| H3-A3 | **单镜头**：“FL2VA generally favors a single shot so the model can interpolate continuously from the first frame to the last frame. Use multiple shots only when they are explicitly specified.” 第一个镜头不写时间戳（“Do not add a timestamp to the first shot.”） | [G] |
| H3-A4 | 正文写法：“first-frame state → observable intermediate changes → progressively narrowing differences → last-frame state”。开头写 “…begins in the position, framing and lighting established by Picture 1”，结尾写 “…settles into the pose, spacing, and composition established by Picture 2 at the end of the shot.”（句式取自官方示例） | [G] |
| H3-A6 | **不要复述两张静帧**：“The body should not repeat two static image descriptions; instead, it should supply the motion path that connects them.” 人物和场景锚点只写一句，其余篇幅写连接两帧的动作路径 | [G] |
| H3-A8 | 开头先写风格和起始构图，例如 “Live-action, cinematic, …”（官方示例原样）；我们固定写 `Live-action, cinematic, shallow depth of field,` 再写景别 | [G] 示例 |
| H3-A7 | **语言**：正文用英文，台词、歌词、画面文字保留原语言。[K] 原文：“Write rewrite sections in English; preserve dialogue, lyrics, and visible scene text in their original language.” [C]：“Write prompts in English. Dialogue/lyrics in `<d>` tags.” | [K][C] |
| H3-A5 | **不写否定句，不写禁用清单**：cfg 1 的 BasicGuider 没有负向分支；[C]：“Ban lists add unwanted concepts”，应改写成“画面里应该有什么”。剧本的负面追加、visual_bible 的 negative 都不得原样拼进 H3 提示词（字幕一律不提，靠“不写文字”实现） | [C] |
| H3-A9 | 每个细节都必须对应画面里看得见、或音频里听得见的东西；不写剧情概述（[K]：“Avoid plot summaries…”）；不写抽象情绪词（[G] 配乐条）。原文 “Every detail should correspond to something visible or audible” 引自 [R]，本次抓取未逐字核到 → 待验证 | [K][G]；[R] |
| H3-A10 | 只是距离或角度略有变化时，用运镜处理，不切镜（[G]：“If only the distance or a slight angle needs to change, prefer camera motion.”） | [G] |

**运镜词汇**（[G]，`H3-A10`）：Zoom In/Out、Push In/Pull Out、Pan Left/Right、Truck Left/Right、Tilt Up/Down、Pedestal Up/Down、Arc Shot、Tracking Shot、Static Shot。
- 幅度写 `with small amplitude` / `with large amplitude`，速度写 `at slow speed` / `at fast speed`。原文：“Add amplitude and speed only when they are meaningful; medium amplitude and normal speed are usually omitted.”
- 运镜要写成句子里的自然动作：“Camera motion should be written as a natural English action within the shot, rather than stacked as separate labels at the end of a sentence.”
- 每镜一个运镜、一个主动作（[R] 引 HF 讨论 #65，社区建议 → 待验证，但本 SOP 先按此执行）。

**对白与人声**（[G][C]；`H3-D1`–`H3-D9`）：
- `H3-D2` 说话人用稳定编号 `(S1)`、`(S2)`，按在本镜里第一次开口的先后编号；多人同时说话写 `(S1,S2)`；从不发声的人物不给编号（“characters who never vocalize receive no speaker ID”）。
- `H3-D1` 说话人身份、音色、语气、动作都写在 `<d>` **外面**。`<d>` 里只放语言标签和原文：“Inside `<d>`, include only the language tag and the actual user-provided spoken content.” 格式：`The young woman with a soft, slightly nervous voice (S1) says: <d>[Chinese] 原文。</d>`
- `H3-D3` 台词逐字照抄剧本，包括标点：“Preserve every original word and punctuation mark verbatim; do not translate or rewrite them.”（[G]）
  - [C] 建议少用省略号（“Ellipses often hurt intelligibility”），但官方指南要求逐字保留。**以官方 [G] 和剧本逐字规则为准，不改标点**；省略号要删只能由剧本写入者在剧本里改。
  - 不加装饰性重复和 emoji（[C]）。
- `H3-D8` 第一次出现的说话人，要描述年龄、性别、是否在画面内、音色、语速（[R] 摘自 [G]，本次抓取未逐字核到 → 待验证；先按此写）。
- `H3-D5` 画外音必须写 `says in an off-screen voiceover`，并在 `</d>` 后紧接说明画面内该人物嘴唇闭合（[G]：“Immediately after every voiceover `<d>` block, state that the corresponding on-screen character's lips remain closed”）。
- `H3-D9` 片尾被截断的台词用 `<cutoff>`；跨剪辑延续的台词用 `<scenetrans>`，并写明音频跨切延续（[G]）。
- `H3-D4` 不用双引号包台词（双引号会被烧成字幕，见「已知坑」）；不写人名。
- `H3-D6` 🎙 内心独白**不进 H3**，后期 TTS（PIPELINE_LOCKED）。
- `H3-D7` **本项目附加规则**（不是官方规则；项目方 2026-10-30 定，**block**）：**每镜只让一个人说话**——H3 原生音频里同一镜只有一个说话人 `(S1)`；亲密镜只让林晚发声，男方呼吸放到后期。两个人对话就拆成两镜，各说各的（画布机检与 `validate_script_strict` 都按 block 执行）。soundscape 里不写 “no male voice” 这类否定句（违反第 8 条），用正向写法只列出发声者的呼吸和动作声。
  - 历史：曾因“普通对话镜按官方语法可写 (S1)(S2) 两人”挂为冲突待定，按官方双人语法执行；已由项目方 2026-10-30 的“每镜一人说话”取代。

**overall_soundscape**（[G]；`H3-S1`、`H3-S2`）：
- 1–4 句英文，写成一段，内容是环境声、动作声、非语言人声：“Use 1–4 English sentences in one continuous paragraph to summarize the ambient sound, physical action sounds, …”
- 不重复对白：“Dialogue, singing, and diegetic music already belong in the multimodal description and should not be repeated here.”
- 只有明确要求全片静音时才写 `N/A`。

**non_diegetic_music**（[G]；`H3-S3`）：
- 1–3 句英文，写乐器、速度、节奏、强弱变化，不写抽象情绪词。
- 没有配乐写 `N/A`。**项目方 2026-10-30 定：配乐进 H3**（取代原“本项目固定 N/A”）。取值：本镜人工（画布）> 剧本 **H3提示词** 自带（非 N/A）> 本集默认配乐 > `N/A`；只收英文，中文【配乐】提示只给后期、不翻译。后期是否在写了配乐的镜头上再铺整集 BGM：待项目方定（建议不铺，避免双重音乐）。

**长度**（[K]；`H3-A11`、`H3-A12`）：
- 描述的总时长必须与请求的视频时长一致（“Always match the total duration of the description to the requested video length (4–15 seconds).”）。
- 官方没有字数硬上限；vLLM recipe 的 API 上限 7000 字符引自 [R]，未抓取 → 待验证。

### 9A.2 示例（按 v2 ep01 写，仅示范写法，不是生产文本。v3 进入 `gpu3 owner_scripts/weita_ersao/staging_v3/` 后，claude-sop 换成 v3 镜头）

**示例 1：ep01 镜1（上摇，无对白，243 帧）**。剧本：img = 低机位，透明细高跟踏上大理石；motion = 缓慢上摇到抱着文件夹的脸，理刘海；sound = 高跟敲大理石回声 + 大堂环境音；🎙 不进 H3。

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 10.12-second mark of the target video.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, a low-angle shot begins in the position, framing and lighting established by Picture 1, with a pair of clear 12 cm needle heels stepping onto the reflective marble floor of an office lobby in slanting morning light. The camera tilts up at slow speed as she walks forward, travelling along the glossy black patent mini skirt that sways with each step, past her waist and chest, to the face of the young woman with long ice-blue hair and straight bangs. She hugs a folder against her chest with a polite, slightly nervous gaze, lifts one hand to smooth her bangs, and settles into the pose, expression, and composition established by Picture 2 at the end of the shot.

overall_soundscape: Crisp heel clicks echo off the marble floor over the soft murmur of the lobby. The revolving door turns with a low, steady whoosh behind her.

non_diegetic_music: N/A
```

**示例 2：普通对话镜（一人一镜，243 帧）**——只示范结构，尖括号是占位，不是生产文本。按 H3-D7，两个人的对话拆成两镜，每镜只有一个说话人 `(S1)`；另一人的台词写在下一镜（由写作者拆镜）。

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 10.12-second mark of the target video.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, shallow depth of field, a <景别与运镜> begins in the position, framing and lighting established by Picture 1, <场景与人物外观（正向写法）>. <动作 1>. The on-screen <说话人外观与声音特征> (S1) says <语气>: <d>[Chinese] <这一镜唯一说话人的台词></d> <动作 2>. <主体> settles into the pose and composition established by Picture 2 at the end of the shot.

overall_soundscape: <环境声与动作声，1–4 句英文，正向写法，不写台词>

non_diegetic_music: <1–3 句英文，乐器 / 速度 / 节奏 / 强弱；没有就写 N/A>
```

示例里的要点：
- 对齐句逐字照抄。
- 正文英文，台词中文放在 `<d>` 里，标点逐字保留。
- 说话人描述写在 `<d>` 外面。
- 不复述两张静帧，只写动作路径。
- 没有否定句。
- 结尾句收在 Picture 2。
- 配乐写 N/A。

### 9A.3 技术要求

| 项（rule_id） | 要求 | 状态 | 来源 |
|---|---|---|---|
| 帧率 `P-B3` | 24 fps | 锁定 | [N] `FPS = 24` |
| 帧数网格 `P-B1` | 节点会把帧数**向上**对齐到 17k+5（`while n % 17 != 5: n += 1`），所以 4n+1 规则不适用。243 = 17×14+5，合法。时长与帧数对照见 §6 表 | 锁定 | [N][CN] |
| 时长范围 `H3-A11` | 4–15 s（[K]）；本项目取 107–362 帧（K4，2026-10-31；4 s 档画质待实测） | 锁定 | [K]；[R] |
| 分辨率 `P-B3` | 短边 768、面积上限 768×1344、边长为 32 的倍数（`BASE_SHORT_EDGE = 768`、`MAX_PIXELS = 768 * 1344`、`CANVAS_MULTIPLE = 32`）。原生 16:9 = 1344×768；我们是 9:16，用 **768×1344** | 锁定 | [N][CN] |
| 首尾帧预裁 `P-B2` | 节点对首帧是 `_resize(..., "disabled")`（源码注释 “plain stretch to canvas”），对尾帧是 `"center"`（“aspect-preserving cover-crop”）；[CN]：“an off-aspect image comes out stretched”。所以**两帧都要先在本地用同一种方式 center-crop + lanczos 到 768×1344，并断言尺寸后再上传** | 锁定（gpu3 weita_render L1174–1186 已实现） | [N][CN] |
| 关键帧强度 | 没有强度参数；“`denoise` does not scale guide strength” | 锁定（官方事实） | [CN] |
| 首尾帧进文本编码器 | `clip.tokenize(prompt, images=images)`：首帧 = Picture 1，尾帧 = Picture 2，所以对齐句是起作用的 | 锁定 | [N] |
| 中间关键帧 `P-A8` | `MiniMaxH3AddGuide(frame_idx)`：负数表示从片尾往前数；没有 strength 参数。只在“必须经过某个中间姿态”的镜头上用，FL2VA + Turbo 下的效果需 A/B | 需 A/B | [N]；[R] |
| CFG `P-A2` | cfg 1，BasicGuider，没有负向分支 | 锁定 | [C] |
| 基模 shift `P-A3` | video 12 / audio 3（`sigma_shift_scales`） | 锁定 | [M] |
| 基模步数 `P-A5` | ComfyUI 默认 20，为动作质量可提到 25（“Raise steps (e.g. 25) for motion quality”）；官方参考 50 引自 [R] | 20–25 锁定；50 待验证 | [CN]；[R] |
| Turbo（LightX2V）配对 `P-A3` `P-A4` | 544p 的 `8step_v1.0`：shift **12/3**；768p 的 `8step_v1.0_768p`：shift **6/3**、8 步（[L]：“Recommended settings: 8 NFE, video shift 6, audio shift 3”）。`8step_v1.1_768p` 文件存在（[LH]），但规格表没抓到它这一行 → 按 768p 用 6/3，**待验证** | 配对规则锁定；用哪个版本 → 需 A/B | [L][LH] |
| Turbo 质量代价 | Turbo 的运动和音频略软（“slightly softer motion/audio”）；参考必须守住时用 20–25 步（R2V 页） | 锁定（官方说明） | [CN] |
| 采样器 `P-A6` | euler + simple；不用 ancestral/SDE（音频破音，ComfyUI issue #15283） | 待验证（社区来源） | [R] |
| 缓存加速 `P-A7` | 不挂 EasyCache、Spectrum、TeaCache（社区对比显示会融化、出双轮廓） | 待验证（社区来源；本 SOP 先禁用） | [R] |

**已知失败模式与对策**（来自 [R]，社区或推断，置信度见原文）：

| 症状 | 原因 | 对策 |
|---|---|---|
| 远景脸崩、脸糊 | 官方承认的模型问题（HF #87）；远景小脸最严重 | 人物至少中景，脸要占足画面；固定种子多抽；不挂缓存 |
| 尾帧附近重影、双重曝光 | 首尾帧几何不一致（拉伸 vs 裁切）；首尾差距过大，模型只能“溶解”过去；挂了缓存；竖屏 Turbo 可能有重影（#44，ref2v） | 两帧同法预裁；首尾帧同景别、同光、同机位族；关缓存；9:16 Turbo vs 基模 A/B |
| 漂离首帧 | 中文正文；没写对齐句；复述静帧；动作和尾帧矛盾；动作幅度过大 | 按 9A.1 写；一个主动作 |
| 落不到尾帧 | 缺收敛句；首尾差距超出 10 s 能完成的连续动作；Turbo 一致性不足 | 加 “settles into … Picture 2”；缩小首尾差距或拆镜；加 AddGuide；关键镜用基模 20–25 步做对照 |
| 镜间色调跳变 | 种子相关的色偏、VAE 色偏 | 用 euler；成片做相邻镜头颜色匹配 |

---

## 10. 成集 QA（自动 + 抽查）

- 每镜：脸/眼、烧字、首帧漂移、人数、服装/鞋/饰品计数、姿势朝向、色彩/虚化、音频存在。
- 每集：时长、拼接、独白位置、连续性账本 diff。
- 失败熔断（纠正器 §3.1）：一集 ≥3 镜失败暂停该集并出报告；同类失败跨 3 集判定系统性问题；单镜 3 次失败进入异常队列（先走合成修复再判 BLOCKED）。
- 记录：`docs/qa_issues.md`、`STATUS.log`（`[epXX] ✅ 出图…| 视频…| 成片…| 装饰…| 耗时…`）。

## 11. 声音

- gpu3：每集 BGM（`data/music/epXX.wav`）+ 每镜分层（Demucs 人声/其余、Foley、标志音库、对方呼吸）`renders_gpu3/epXX/SN/audio/`。
- 笔记本：TTS（独白/对白，固定声线）、混音（Foley −6..−10 dB、独白处场景 −8..−12 dB、母带 −14 LUFS/−1 dBTP）。
- **配乐规则（X-4，项目方 2026-10-30 选“按 E8 写进 H3”）：H3 的 non_diegetic_music 带本集 / 单镜配乐（取值 = 本镜修改 > 剧本 **H3提示词** 字段 > 【配乐】静默提示（N/A）> 本集【BGM】英文，函数 ns_agent.h3_prompt.resolve_music）；后期对 H3 已带配乐的镜头不再叠加 BGM（ns_post.music.h3_music_shots，装配时这些镜头的 BGM 静音，时间线 bgm.h3_music_shots 记录）。** gpu3 渲染器（模板 / 兜底提示词）、shot_audit 的 H3-S3、audio_post 已按本规则同步（fredw-ae，封板修复）。

## 12. 4K 放大（成集 QA 通过后）

- gpu3：每镜放大到 2160×3840（时序一致的视频超分，复用 research v5/v8），轻锐化 + 颗粒，不改调色；输出 `takes/video_NNN_4k.mp4` + 对比图与闪烁指标。

## 13. 成片装配与导出

- 笔记本 `tools/assemble_episode.py`：4K 镜头 + 混音音轨 + 0.3s 交叉溶解 + 片尾字卡 → 1080×1920 与 2160×3840 两版；**G5 验收**。

---

## 自动化启动（第二部剧）

1. 界面「新建剧」向导：剧名 → 上传剧本文件（三件套）→ 选风格模板并上传色调参考图（G1）→ 为每个角色上传参考图并确认“AI 生成/虚构成年人” → 选成人内容开关与默认欲望强度 → 选需要的 LoRA 类别 → 生成项目目录与配置。
2. 点「开始生产」：编排器按上表依次跑 ②→⑬；每个关口在界面弹出待办卡片（G2–G5），其余自动。
3. 进度看板：每集一行（剧本/首帧/视频/QA/声音/4K/成片 的状态灯）、GPU 占用、异常队列、预计完成时间。

## 资源与时间（3×3090 参考）

- 一个 10 秒镜头视频约 28 分钟（t8）；一集（6–8 镜）单卡约 3.5–4.5 小时；60 集两卡约 6 天（不含返工）。
- LoRA：每个 1.5–3 小时；身份 H3 LoRA 约 9–11 小时（含评估）。
- 剧本 v3：本地 27B 占一张 3090 约 3–5 小时；CPU 需约 40 小时。

## 已知坑（第一部的教训）

- 参考造型照会把衣服/项链/背景带进每个镜头 → 身份参考只用脸部裁切或中性底板。
- 双引号台词会被 H3 烧成字幕 → 对白只用 `<d>…</d>`，不写人名。
- Turbo cfg1 不认“穿衣/不要”类约束 → 关键镜头用 Base 真 CFG。
- 多线程共享 OpenCV DNN 会崩 → QC 模型加锁。
- GPU 抢占 → 锁文件 + 借卡协议（`/root/.local/state/NS-Studio/{gpu,train,lend}.*`）；GPU2 坏卡永不使用。
- 两个开发会话 → `TASKS.md` 认领、单写者、改契约先通知。
- H3 FL2VA 节点对首帧是**拉伸**、对尾帧是**居中裁切**，比例不对时两帧几何不一致，会出现重影 → 首尾帧先用同一方式 center-crop 到 768×1344 再交给 H3（证据：ComfyUI `nodes_minimax_h3.py` 源码，见 docs/research/h3_prompt_and_fl2v.md §2；claude-sop 2026-10-30 记）。
- LightX2V 加速 LoRA 与 shift 必须配对：544p 版本用 12/3，768p 版本用 6/3；配错会让 sigma 网格偏离训练分布（证据：LightX2V 官方表格，同上 §2；gpu3 实际加载的版本待核对，见 SOP_parameters.md）。
- 渲染器发现 v3 文件就会自动改用 v3（`weita_render.py` 的 SCRIPT_PATH）→ 这绕过了 S1 的 G3 闸门。v3 文件放上 gpu3 之前必须先通过 G3（claude-sop 2026-10-30 巡检发现）。
