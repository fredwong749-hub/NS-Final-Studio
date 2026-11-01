# 生产流水线链条契约（PIPELINE_CHAIN）

CHAINSPEC，2026-10-31。机器可读版：`config/pipeline/chain.yaml`（单一事实来源，本文是给人看的说明）。

> 项目方原话："把这条完整的生产 pipeline 从第一个 point 到 last point 梳理清楚：明确每一 point 之间要做什么、不做什么，以及 format 是什么、规则是什么……每个 chain 跟 next chain 之间都有 connect，所以每个 chain 之间都有自己的一些规则和 format。"

硬规则：Claude 只写系统。剧情和台词由写作 LLM 写，项目方定。链条里的每条规则都只管格式和可实现性。

---

## 0. 一页总图

```
 项目方                    写作 LLM（abliteration large-flash，用途 script_write）                       系统 / 渲染 / 审片
 ───────                  ─────────────────────────────────────────────────                       ─────────────────────
 P0 故事提纲 ──P0-P1──▶ P1 全剧 storyline ──P1-P2──▶ P2 单集大纲 ──P2-P3──▶ P3 单集剧本 ──P3-P4──▶ P4 剧本分镜 / Shot Spec
 (Brief JSON)  [闸·可选]  (人物表/场景表/分集)  [闸·可选]  (节拍 B1…Bn)            (场次/台词/独白)   [闸·导入]  (Markdown → Shot Spec v2)
                                                                                                            │
          ┌─────────────────────────────────────┬───────────────────────────────┬───────────────────────────┤
          ▼ P4-P5                               ▼ P4-P6                         ▼ P4-P7                     ▼ P4-P9
     P5 资产 [闸·定妆] ──P5-P6──▶ P6 首帧/尾帧 [闸·定稿] ──P6-P7──▶ P7 视频提示词+配方 ──P7-P8──▶ P8 视频片段
     (身份参考/造型/场景底图/音色)                                                                   │ P8-P9 / P8-P10
                                                                   P9 声音 ──P9-P10──▶ P10 剪辑合成 ◀┘
                                                                                          │ P10-P11
                                                                   P11 审片 ──P11-P12──▶ P12 成片交付 [闸·成片]
                                                                     │
                                                                     └─P11-RETRY─▶ attribute_bug 归因到某段连接 → 该段回退（写作重写 / 换种子 / 换配方 / 交项目方）
```

### 每段一行（状态：已定 = 格式 + 校验 + 回退都有；部分 = 缺其中一部分；缺 = 没有规则）

| 连接 | 做什么 | 不做什么 | 输出格式 | 谁做 | 闸门 | 状态 |
|---|---|---|---|---|---|---|
| P0-P1 | 提纲 → 世界观、人物表（5 格进 H3）、场景表（6 格）、逐集一段话 | 改提纲、多出集、场景卡写人物 | `nsfs.storyline/1` JSON | 写作 LLM | 可选（默认自动通过） | **已定**（本轮新建） |
| P1-P2 | 一集一段话 → 节拍表 B1…Bn（场景 / 人物 / 秒数 / 标签） | 新增人物 / 场景、改 logline、写台词全文 | `nsfs.episode_outline/1` JSON | 写作 LLM | 可选 | **已定**（本轮新建） |
| P2-P3 | 节拍 → 场次剧本（动作、台词、独白、声音），每场标节拍 | 删节拍、新增人物、写景别 / 运镜 / H3 英文 | `nsfs.screenplay/1` JSON | 写作 LLM | — | **已定**（本轮新建） |
| P3-P4 | 剧本 → 剧本分镜（img / 场景 / 人物 / 衔接 / 分拍 / motion / 时长 / sound / 对白 / 🎙 / H3） | 改台词、加独白、否定词、人名进 H3、镜内切镜 | 剧本分镜 Markdown（script_chat_rules §2）→ Shot Spec v2 | 写作 LLM | 导入确认（项目方） | **已定**（格式）；时间轴 sysimpl-v2 刚上 |
| P4-P5 | Spec 列资产需求（在画角色 / 场景 / 造型 / 说话人） | 缺资产照样出片、用别集造型 | 资产注册表 + provenance | 系统 + 渲染 | 定妆（项目方） | 部分 |
| P4-P6 | Spec img / 结束状态 → 出图提示词（后缀按字段条件生成） | 关键词猜在画人物、否定后缀 | compiled.json image_prompt / last_prompt | 系统 | — | 部分 |
| P5-P6 | 资产 + Spec → 首帧（参考图出图）、尾帧（编辑） | 纯文字出图换不动身份 | takes.json image#N / last#N | 渲染 | 首尾帧定稿（项目方） | 部分 |
| P6-P7 | 定稿帧 + 配方选择（首帧 / 首尾帧 / Ref2VA；series10 视频全部 i2va_pika_flex（L-088：无 pdd2 回退、无 Ref2VA 兜底；脸红类描述镜由 flush_risk 挂起等 Pika 方案，config/pipeline/video_policy.json pika_only）——项目方 11-01 ~18:0x“视频：全部用皮卡来做”，K-REN-301） | 提交时改提示词不回写 | RenderPlan | 系统 | — | 部分 |
| P4-P7 | Spec H3 正文 → 按模式编译（I2VA / FL2VA / Ref2VA）+ 按秒分拍校验 | 改写作者正文内容 | H3 四块 / Ref2VA 六段 | 系统 | — | 部分 |
| P7-P8 | RenderPlan → GPU 作业 → 视频 take | 无 provenance 覆盖产物 | takes.json video#N | 渲染 | — | 部分 |
| P4-P9 | Spec 音频字段 → 音轨计划（独白 TTS、BGM 提示点） | — | 音轨计划 | 系统 | — | **缺**（独白音色无规则，v1“旁白声音老”落这里） |
| P4-P9 · bgm | P3 + P4 → 写作模型配乐 brief → 本地 ACE-Step 候选 → 度量 + 闸门 → 审听模型挑选（≤3 轮） | 具名作品 / 人声 / 外部 API / 逐镜曲目 / 旧剧配乐 | nsfs.bgm_brief/1 + data/music/series10/epNN.wav + .json + meta.json | 写作 / 审听 LLM + 本地音乐模型 + 系统 | bgm_review（审听模型；项目方可在声音页一键换用） | **已定**（BGM10 11-01，docs/BGM.md） |
| P8-P9 | 对白用 H3 原声，TTS 只做独白 / 兜底；整集一条 BGM | 逐镜 BGM、TTS 盖原声 | 音轨 | 系统 | — | 部分 |
| P8-P10 / P9-P10 | 只取定稿 + QC 通过 take；剪定住段、拆刀、切点音频、响度、bt709 | 混用新旧版本 | timeline.json + mp4 | 系统 | — | 部分 |
| P10-P11 | 审片：身份、泛红、静止、顿挫、近黑、嘴型、构图对剧本 | 评价剧情 | director_verdict | 审片 LLM + 系统 | — | 部分 |
| P11-RETRY | bug → 归因到连接 → 该段回退；规则草案进 knowledge/inbox | 只换种子不改原因 | 归因记录 + 草案 | 系统 | 3 次失败交项目方 | 部分（本轮建归因） |
| P11-P12 | 全集定稿检查（响度、许可、全部定稿）→ 交付 | — | 成片 + qa.json | 项目方 | 成片（项目方） | 部分 |

上游 P0→P4 由 CHAINSPEC 负责，规则在 `chain.yaml rules` 里，共 59 条（BR / SL / EO / SP / LK*）。下游 P4→P12 由 ARCH 负责，规则在 `knowledge/rules/*.yaml` 里，共 140 条，每条都带 `link` 字段，按字段挂到对应连接上。

---

## 1. 怎么用

| 要做什么 | 命令 |
|---|---|
| 从提纲跑到剧本分镜（写作 → 校验 → 带错误重写 ≤2 轮 → 记账） | `.venv/Scripts/python.exe tools/pipeline/run_chain.py --brief <P0.json> --episode N --out data/pipeline/runs/<id> [--upto P4] [--budget-usd 8]` |
| 看某段的写作提示词（从 chain.yaml + knowledge 组装） | `.venv/Scripts/python.exe tools/pipeline/writer_prompt.py P1-P2` |
| 校验契约本身（引用、schema、校验器、knowledge link） | `.venv/Scripts/python.exe tools/pipeline/check_chain.py` |
| 一份产物属于哪个节点、违反哪条规则（规则原话 + 所属连接） | `.venv/Scripts/python.exe tools/pipeline/check_chain.py --artifact <文件>` |
| 审片发现归因到连接、生成规则草案 | `.venv/Scripts/python.exe tools/pipeline/attribute_bug.py "<bug 描述>" --episode N --write` |
| 测试 | `.venv/Scripts/python.exe -m pytest tests/test_pipeline_chain.py` |

ARCH 的 Autopilot（`tools/autopilot/run.py`）从 P0 开始跑，上游部分调用 `run_chain.run(...)` 或 `run_link(...)`。接口写在 run_chain.py 文件头。

文件一览：

- schema：`packages/schema/ns_schema/storyline.py`（P0 Brief、P1 Storyline）、`episode_outline.py`（P2）、`screenplay.py`（P3，以及 P2-P3、P3-P4 的连接校验）、`upstream_common.py`
- 契约：`config/pipeline/chain.yaml`、`config/pipeline/attribution.yaml`（症状 → 连接归因表）
- 样例：`config/pipeline/examples/`
- 提示词模板：`config/pipeline/prompts/<连接>.md`
- 工具：`tools/pipeline/{chainlib,writer_prompt,run_chain,p4_adapter,check_chain,attribute_bug}.py`

---

## 2. 上游各段详细

各段公共约定：
- 输出只有一个 JSON 对象，允许包一层 ```json 代码块；schema 设为 `extra=forbid`，多写字段也会被拦下。
- 返修时把不通过的规则号和原话带回给写作 LLM，要求只改被点名的地方。最多重写 2 轮，来源是 `knowledge/settings.yaml writer_selfcheck.max_rounds`。
- 2 轮后仍不过，状态标 `needs_writer`，整条链停在这一段，下游不会拿到失败的产物。

### P0 项目方故事提纲（Brief）

- **输入**：项目方在 `#/script-create` ① 创作页填的字段：提纲文本框、集数 epFrom/epTo、镜数、秒数、规则版本、模型。
- **输出**：`nsfs.brief/1`，样例见 `config/pipeline/examples/P0_brief.json`。`outline` 和 `episode_lines` 存项目方原文，系统不改写。
- **校验**：BR-01…04（`check_brief`）。
- **状态：部分**。页面字段已经有了，但页面还不直接产出 Brief JSON，目前由 run_chain / Autopilot 拼装。待建：页面加一个“生成 Brief”的出口。

### P0-P1 → P1 全剧 storyline

- **输出**：`nsfs.storyline/1`。
  - `characters[]` 五格（name、char_id、zh_look、en_phrase、voice_phrase）和剧本 `**全剧人物表**` 一一对应。P4 会把 en_phrase / voice_phrase 逐字抄进 H3 锚点句和说话人句。
  - `scenes[]` 六格和 `**全剧场景表**` 一一对应。
  - `episodes[]` 每集一条：owner_line、logline、characters、scenes、intimate、carry_out。
- **必须**：
  - 集数范围不多不少（LK01-01）；
  - owner_line 逐字照抄项目方给的逐集一句话（LK01-02）；
  - 已登记的人物和场景各格逐字照抄（SL-10，与 QW-P7 / QW-SC9 同一口径）；
  - 全部角色 ≥18 岁（SL-02，★ 最高优先级规则）；
  - en_phrase 写族裔，不写服装、人名、否定词（SL-04）。chain_audit A1/B1 的“族裔丢失”就是在这里出的。
- **禁止**：场景卡写人物（SL-07，官方 STEP 4）；改提纲；输出 JSON 以外的文字。
- **UI**：待建，建议放在 `#/script-create` 的 storyline 卡（人物表 / 场景表 / 分集）。定稿后人物表进 `#/assets` 角色页，场景表进场景页。
- **状态：已定**。

### P1-P2 → P2 单集大纲

- **输出**：`nsfs.episode_outline/1`。节拍表 `beats[]` 每拍有 id、summary、scene_id、characters、est_s、purpose、has_dialogue。
  - purpose 只是受控标签：hook / setup / turn / reveal / tender / intimate / payoff / bridge / cliffhanger，借鉴官方 Hook Type。系统只查标签在不在词表里，不判断好坏。
- **必须**：
  - title、logline、intimate 逐字照抄 storyline（LK12-01）；
  - 不新增人物和场景（LK12-02）；
  - 节拍秒数合计 = 目标时长 ±5，目标在 50–75 秒之间（EO-04）；
  - carry_in 接上一集的 carry_out（LK12-04，跨集衔接）。
- **UI**：待建（节拍表）。
- **状态：已定**。

### P2-P3 → P3 单集剧本

- **输出**：`nsfs.screenplay/1`。按场次组织，`lines[]` 每行的 kind 是 action / dialogue / voiceover / sound 之一。台词 `text` 只放原文，语气写进 `tone`，画外写进 `off_screen`（SP-04）。chain_audit A12“说话人字段是舞台提示”就是在这里出的。
- **必须**：
  - 每个节拍都有场次覆盖（LK23-01）；
  - 场次的 scene_id 等于节拍的 scene_id（LK23-02）；
  - 全集台词 + 独白字数 ≤ 3.5 字/秒 × 时长（SP-06）；
  - 单句 ≤52 字，保证一镜放得下（SP-09）。
- **禁止**：写景别 / 运镜（SP-05，归 P4）；新增人物。
- **UI**：待建（剧本视图）。导入后，台词和独白出现在画布 StoryboardDetails 的“对白”和“独白”字段。
- **状态：已定**。

### P3-P4 → P4 剧本分镜 / Shot Spec

- **写作提示词**：沿用现有加载点 `ns_api.script_chat.prompt_for`（`config/script_chat_rules.md` rules_v2 + sysimpl 附录 + 按触发词注入的附录 + 全局头），后面追加 `config/pipeline/prompts/P3-P4.md` 链条段（LK34-*）和 knowledge 里 link=P3-P4 的 writer_text。用户消息里放 P3 剧本 JSON、本集人物 / 场景表，以及系统按 P3 算好的镜数上限和目标总时长。
- **输出**：现行剧本分镜 Markdown（规则 §2 格式），经 `spec_import` 转成 Shot Spec v2。
- **校验**（`p4_adapter.check_p4`）：
  - ① 导入关口 `tools/validate_qwen_script.validate`，和创作页、收件箱用的是同一个，规则号 QW-/H3-/S1-/R-C1/IMG-/RL- 保留在消息里；
  - ② 真实导入器 `import_script`；
  - ③ `specs_from_markdown` + `missing_fields` 的 block 项（SS-*）；
  - ④ 连接逐字校验 LK34-01/03：台词和独白不增、不减、不改。
- **UI**：
  - `#/script-create` 草稿和校验；
  - `#/script-create?tab=import` 导入，项目方确认；
  - 画布 StoryboardDetails 字段：scene、cast、link、img、motion、end、expr、dialogue、vo、sound_h3、intimate、music_cue、duration、h3；
  - 分镜表 StoryboardTable（一镜一行）。
- **状态：已定**（格式）。sysimpl-v2 时间轴（RL-T*）刚上线。

---

## 3. 下游各段（ARCH 负责，CHAINSPEC 只负责挂载）

每段的规则在 knowledge 里查：`knowledge/rules/*.yaml` 中 link 等于该段的条目。`check_chain` 会校验这些 link 都是合法的连接 id。

| 连接 | knowledge 条目（示例） | 校验器 / 执行 | 回退 |
|---|---|---|---|
| P4-P5 | K-AST-001（露脸角色要有定稿身份参考）、K-AST-R03/R05/R06/R09/R10 | tools/s1_gate.py、SS-P5 | needs_owner（定妆） |
| P5-P6 / P4-P6 | K-AST-003、K-AST-R01/R02/R04、K-REN-015 | frame_spec.py、image_check.py | render_retry |
| P6-P7 / P4-P7 | K-PRM-001…012、K-PRM-R01…R03、K-REN-004 | h3_lint、ns_recipes.lint（RL-*） | writer_repair / render_retry |
| P7-P8 | K-REN-*、K-OPS-* | motion_qc.py | render_retry（≤3 次 → 项目方选择卡） |
| P8-P9 / P4-P9 | K-EDT-001/002、K-REN-R20、K-AST-R09 | — | **P4-P9 缺规则**（见 §5） |
| P4-P9 · bgm / P9-P10 | K-EDT-B01…B06（knowledge/rules/edit_bgm.yaml） | tools/bgm/brief_schema.py（BGM-B01…B14）、tools/bgm/agent.py gate()、tests/test_bgm.py；合成 `--music-dir data/music/series10` | brief：writer_repair ≤2 轮；候选：调整重出 ≤3 轮 → needs_owner（合成 --no-bgm） |
| P8-P10 / P9-P10 | K-EDT-003…009、K-EDT-R01/R02 | assemble.py、dejudder.py | rerun_post |
| P10-P11 | K-REV-R01…R10 | tools/ep02_director/review.py | retry_via_attribution |
| P11-RETRY | K-LOOP-003…009 | tools/iterate_loop/loop.py + attribute_bug | 阶梯 → needs_owner |
| P11-P12 | K-EDT-007、K-OPS-R04/R05 | — | needs_owner（成片闸门） |

---

## 4. 本轮验证：P0 → P4 实跑（abliteration large-flash，推理关）

测试提纲：项目方 v3.1 剧本 ep01–03 的 `**剧情**` 行原文（`data/pipeline/test_brief_ep01-03.json`）。没有自己编剧情，只把 ep02 跑到 P4。

| 段 | 结果 | 轮数 | 说明 |
|---|---|---|---|
| P0-P1 | 通过 | 1 | 3 个已登记角色、3 个已登记场景逐字照抄；owner_line 逐字一致 |
| P1-P2 | 通过 | 2 | 第 1 轮 EO-04：节拍秒数合计与目标时长不符 |
| P2-P3 | 通过 | 2 | 第 1 轮 SP-01：schema 不符 |
| P3-P4 第 1 次（r1） | 3 轮后 needs_writer | 3 | 3 轮卡在同几类错：H3-X1 ×9（造型 EN 末项前的逗号被改成 and）、SS-M2 ×9（分拍最后 1 秒空着）、QW-E2（镜数 9 > 8）、LK34-03（自己加了一段独白） |
| P3-P4 第 2 次（r2） | 3 轮后 needs_writer | 3 | 加了 LK34-07/08/09 后，H3-X1、SS-M2、QW-E2 全部消失；剩下 H3-A4 ×8（settles 句并进上一句、写成 settling）、QW-E3（总时长 48 秒）、LK34-03 |
| P3-P4 第 3 次（r3） | **通过** | 3 | 加了 LK34-10/11，并把 LK34-03 的消息改成指名到镜：第 3 轮 0 block。导入关口通过，8 镜都转成 Shot Spec v2，总长 65 秒 |

费用：13 次调用共 **$0.48**（预算 $8），账在 `data/pipeline/ledger.jsonl`，tag 为 `chainspec-20261031`。产物和每轮的提示词、原文、报告在 `data/pipeline/runs/ep02_r1…r3/`。

**这次实跑说明了两件事**：

1. P3-P4 前两次失败的错，机检规则其实早就有（H3-X1 / SS-M2 / H3-A4 / QW-E2 / QW-E3）。缺的是写给写作模型的那句话不够具体，比如没说“逗号也要逐字”“最后一拍的止 = N”“settles 单独成句”。按 RSI 把这几类写成 P3-P4 的连接规则后，第 3 次就过了。
2. 其中两条已经由 PROMPT 写进 sysimpl-v2 原文（`config/script_chat_rules.md` 第 198、203 行）。LK34-08 / LK34-10 和原文有重复，暂时保留作为连接层的强化。

**补记（同日稍晚）**：FIX 改了生产登记里的 VOICE 声线短语，把“slow pace”改成了“natural pace”。之后再用 `check_chain --artifact` 查 r3 的 P4，多出 3 条 H3-X3 block：稿件逐字抄的是旧短语，和新登记对不上。P1 storyline 也会因为同样原因报 SL-10。这正是“上游登记改了，下游产物要标脏”的情况，check_chain 能查出来，但目前没有自动标脏（见 §6）。P4 落稿时已经按 ARCH 的 `spec_import.stamp` 盖上写稿时的规则版本章。

r3 剩下 23 条 warn，都不阻塞：QW-G2 是全局头的问题（系统的，已从本段报告里排除），另有 QW-C4、QW-K3、QW-E6b、H3-A10。

---

## 5. RSI：审片 bug → 连接 → 规则

流程：审片发现 → `attribute_bug.py` → 用 `config/pipeline/attribution.yaml` 的症状关键词找到候选连接 → 在 chain.yaml / knowledge / 现行规则文件里找相关规则 → 把生产剧本这一集转成 Shot Spec，用现行校验器统计违规次数 → 得出结论 → 草案写进 `knowledge/inbox/`（status 待确认）→ 总调度 / ARCH 确认后移进 `knowledge/rules/` → 下次组装提示词时自动带上，因为 writer_prompt 会读 knowledge 里 link 匹配的 writer_text。

项目方 v1 五条的演示（`attribute_bug.py --v1-demo --episode 2 --write`）：

| v1 bug | 首要连接 | 结论 | 证据（生产 ep02，按现行规则校验） | 草案 |
|---|---|---|---|---|
| 镜头切换生硬 | **P3-P4** | 规则已有，旧稿没执行 | RL-T5 开头衔接句 ×11、RL-T6 结尾仍在进行的动作 ×11（11 镜） | `knowledge/inbox/2026-10-31_cut_harsh.yaml`：接力镜头的“下镜”和开头衔接句升为 block，审片加接缝检查 |
| 眼神表情生硬 | **P3-P4**（P4-P7 次之） | 规则已有，旧稿没执行 | SS-M1 没有分拍 ×11、RL-T3 缺视线 ×6、RL-T4 ×1 | `…_gaze_expression_stiff.yaml`：Shot Spec 按写稿时的真实规则版本记录 |
| 提示词时间轴差 | **P3-P4**（P4-P7 次之） | 规则已有，旧稿没执行 | SS-M1 ×11、RL-T1 没有 At 00:SS 时间码 ×11 | `…_timeline_coarse.yaml`：RL-T1/T2 作为出片前的硬闸门 |
| 节奏慢 | **P3-P4**（P9-P10 次之） | 规则已有，旧稿没执行 | RL-T7 ×7、SS-M1 ×11；剪辑侧 K-EDT-003/004 还是“建议” | `…_pace_slow.yaml`：写作动作量和剪辑每刀时长分开度量、分开记账 |
| 旁白声音老 | **P4-P9** | **缺规则** | 这一段没有任何规则；项目方原话见 writer_requests W6 | `…_narrator_voice_old.yaml`：独白 TTS 音色要和人物表年龄、VOICE 一致；切换音色由项目方定 |

顺带发现的系统 bug（已告知 ARCH）：`spec_import` 导入时，把当时的规则版本（sysimpl-v2）盖到了旧稿上。v1 稿被标成了 v2，规则版本的出处就不可信了。

---

## 6. 地图：之后 RSI 要填的格子

| 位置 | 缺什么 | 归属 |
|---|---|---|
| P0 UI | 创作页直接产出 Brief JSON；P1/P2/P3 的查看、编辑卡（storyline、节拍表、剧本视图） | UI（apps/web v3/pages/ScriptCreatePage） |
| P0-P1 / P1-P2 闸门 | 项目方是否要在 storyline / 大纲处确认（竞品都在这里放一个人工点）。默认自动通过，开不开由项目方定 | 项目方闸门 |
| P3 → P4 返修 | 返修轮里写作模型有时会把正文截断（r2 第 1–2 轮）。考虑改成逐镜返修：只回传不通过的镜，用 splice 合并（script_chat 已有 `merge_shot_reply`） | CHAINSPEC 下一轮 |
| P4-P9 | 独白 / 旁白音色和语速的规则（草案已在 inbox） | ARCH / 项目方 |
| P4 rules_version | ARCH 已修：只认稿件里自带的 `rules_version` 章，没有就记 unknown；run_chain 的 P4 落稿已经盖章 | 已完成 |
| 上游改动标脏 | 登记（人物表 VOICE / EN、场景表）改了以后，用旧登记写的 P1–P4 产物要自动标“需重写”。现在只能靠重跑 check_chain 发现 | CHAINSPEC + ARCH |
| P10-P11 → 归因 | 审片输出（director_verdict）直接调用 attribute_bug，不再靠人写 bug 描述 | ARCH（reviewer）+ CHAINSPEC |
| attribution.yaml | 还没有覆盖的症状：念错字、字幕烧入、手指 / 多腿、亲密镜男声 | CHAINSPEC，按审片结果追加 |
