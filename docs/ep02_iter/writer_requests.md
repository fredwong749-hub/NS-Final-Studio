# ep02 迭代：转写作方的请求（经总调度）

系统侧（FIX）只改规则和代码，不改剧本内容。下面这些是内容层面的修改请求，由写作方按规则重写。

| # | 日期 | 来源 | 请求 | 依据 | 状态 |
|---|---|---|---|---|---|
| W1 | 2026-10-31 | 项目方原话“改成正常节奏”（总调度转） | **按新规则重写 ep02 人物表 VOICE 声线短语的语速**：林晚现为 `soft slow pace`，顾沉现为 `measured slow pace`。新规则是“自然语速”（`config/script_chat_rules_appendix.md` 第 67 行、`docs/production_rules_v3.md` 第 114 行已改），音色、音区不变。人物表改了以后，H3 提示词里说话人首次出现的描述也要逐字跟着改（H3-X3）。另外按新的 H3-A11 写法（`config/script_chat_rules.md` 第 131 行），动作量要按正常速度在 N 秒内做完，并留出最后约 1 秒仍在进行的动作 | `docs/ep02_iter/writer_rules_addendum.md` §12 第 1、2、4 条 | 写作模型已产出（PROMPT 10-31 19:5x）：VOICE 林晚=a mid-high sweet breathy voice, natural pace；顾沉=a low restrained voice, natural pace；陈宇=a warm bright voice, natural pace（data/ab/prompt_v2/ep02/voice_revision.json），已并入 H3 与新稿 data/staging_v3/为他而骚_ep02_补全候选_PROMPTv2_20261031.md 人物表；**待项目方画布导入** |
| W2 | 2026-10-31 | FIX（chain_audit A3） | 剧本 img 统一后缀里有“无字幕、无文字、无水印”。cfg=1 时，正向提示词里的否定词反而会把这些东西画出来（ep02 S5 视频出现了“冷”字）。系统后缀已经改成只写正面描述；剧本后缀是否改成正面写法（如“画面干净、纯净背景”）由写作方决定 | `docs/ep02_iter/chain_audit.md` A3 | 写作模型已给正向后缀（无否定字）：data/ab/prompt_v2/ep02/writer_revisions/revisions.json W2；全局头后缀属剧本全局，**待总调度采纳**（未改生产） |
| W3 | 2026-10-31 | FIX（DIR v0 §3） | S2、S4、S5、S7 的 H3 提示词里有 flush / flushed 描述，在 Pika 和只给首帧的模式下会画成大面积圆形红斑。系统已加后期限幅；措辞改不改由写作方决定 | `docs/ep02_iter/v0_baseline_review.md` §3.3 | 写作模型在 sysimpl-v2 重写里自行处理（知会了红斑技术原因），见 data/ab/prompt_v2/ep02/S*.fl2va.txt；已并入新稿，**待项目方画布导入** |
| W4 | 2026-10-31 | FIX（合成闸门） | S8 独白约 25.6 s，镜头只有 12.25 s。合成规则现在把溢出判为不通过，独白在本镜结尾截断。需要缩短独白或拆镜 | `chain_audit.md` D2 | 写作模型建议版：S8 独白 40 字（上限 41），不拆镜——data/ab/prompt_v2/ep02/writer_revisions/revisions.json；**台词改动，待项目方确认**，未替换 |
| W5 | 2026-10-31 | CHAIN F5 | ep02 有 10/11 镜的 non_diegetic_music 写的是“…providing a restrained / sustained background layer”，这是在解释配乐作用，官方 §4.7 要求只写乐器、速度、节奏、强弱。lint 报 warn，系统不改原文 | `docs/ep02_iter/h3_official_conformance.md` §4 F5 | 写作模型已按官方 §4.7 重写 11 镜 non_diegetic_music（只写乐器/速度/强弱），已并入新稿，**待项目方画布导入** |
| W6 | 2026-10-31 | 项目方原话（总调度转 VOICE）：“旁白的声音很难听，是一个老女人的声音，一个 Chinese 的女人。这是一部 fashion 的都市片，所以旁白的声音一定要更加年轻，语气和描写都要更好一点。” | **“描写”这一半归写作方**：ep02 旁白（🎙 林晚内心）文本按“年轻、fashion 都市片”的要求由写作方重写或确认不改。位置：`data/import/script_v2.json` ep02 **S8** voiceover（“别洗。”两个字……看着我湿。）、**S11** voiceover（味道会散的，对吧？……是心跳的证据。）。可与 W4（S8 独白超镜长）一起处理。系统侧（VOICE）只处理“声音/语气”：旁白音色候选见 `data/review_pages/narrator_pick/index.html`，候选登记 `data/assets/proposals/narrator_voice_candidates.json`，未切换（项目方闸门） | 本条原话；`data/assets/proposals/narrator_voice_candidates.json` | 写作模型建议版（与 W4 合并）：S8 40 字、S11 24 字，语气更年轻——revisions.json；**台词改动，待项目方确认**，未替换 |

## W7（总调度转，2026-10-31 21:00）陈宇衣橱描述太笼统
- 来源：CONSIST。cy-casual 只有"休闲装"三个字，设定图身体被模板人台填满（两个 seed 都失败）。
- 需要写作方补：上衣（款式/颜色/材质，粒度如"浅灰圆领卫衣"）、下装、鞋、配饰（可选）、体型（是否补身高）、其他集是否换装。
- 状态：**写作模型已产出，待导入**（PROMPT 10-31 20:27，abliteration 关推理）：造型行写在 data/staging_v3/为他而骚_ep02_陈宇造型补全_W7_20261031.md；全文（含体型、换装说明）见 data/ab/prompt_v2/ep02/writer_revisions/w7_chen_yu.json。已通知 CONSIST 出陈宇造型设定图。
