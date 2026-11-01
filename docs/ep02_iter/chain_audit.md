# ep02 全链路找错审计（CHAIN，2026-10-31）

项目方原话："把 episode 02 的问题找出……无论是提示错误、语言模型错误，还是 rendering 模型错误，你都要一直不断地找问题。找完之后，我需要你把整个系统重构一次，因为这个系统有问题。"

范围：只用 CPU。没有提交渲染，没有重启 API :8800，没有改 config，也没有 git 提交。Claude 不评价剧本内容的好坏，只查技术链路有没有把剧本忠实传下去；丢失、篡改、矛盾算系统问题。重构方案见 `docs/ep02_iter/refactor_proposal.md`。

## 0. 方法与数据来源

| 环节 | 读的文件 / 代码 |
|---|---|
| 剧本原文 | `data/staging_v3/为他而骚 （剧本和镜头）v3.1.md` §ep02（**6 镜**）→ `为他而骚短剧/Qwen剧本/为他而骚_ep02_qwen_rules_v2_20261030.md`（Qwen 拆成 **11 镜**，10-30 21:40）→ 导入 `data/import/script_v2.json`（10-30 22:06，生产用）；补全候选 `data/staging_v3/为他而骚_ep02_补全候选_PREP_20261031 v3.md`（带人物表、场景表，**未导入**） |
| 编译 | `services/agent/ns_agent/compiler.py`（规则编译，`generator=rules`，`prompt_method=script`）、`frame_spec.py`；产物 `data/renders/ep02/S*/compiled.json`、`visual_spec.json` |
| 出图 / 视频参数 | `data/renders/ep02/S*/takes.json`（每个版本的 prompt、seed、params）；定稿首帧 PNG 内嵌的 ComfyUI workflow（`prompt` chunk）；`services/render_router/ns_render/h3_video.py` |
| 作业 | `data/jobs/v1/*.json`（ep02 相关 116 个：done 87 / failed 17 / cancelled 5 / running 4 / queued 3）、`data/jobs/episodes/ep02.json` |
| 合成 | `data/episodes/ep02.timeline.json`（07:51 预览版）、`services/post/ns_post/assemble.py`、`data/music/ep02.json` |
| 画面核对 | 自制 11 镜定稿首 / 尾帧拼图，以及时间线所用视频的中段帧和末帧拼图（scratchpad，未写入项目） |
| 语言模型重放 | `config/llm_providers.json` → abliteration `abliterated-model-large-flash`，经 `ns_api.llm_config.complete_text` 调用，推理关闭，temperature 0.7。**6 次调用**，提示 2727 + 输出 1914 token，按 /models 单价（$1/M 输入、$2/M 输出）**约 $0.0066**。密钥没有写进任何文件或日志。结果见 §4 |

### 0.1 实际链路（按落盘数据还原）

```
v3.1 剧本(6镜) ──Qwen 写作模型拆镜+写H3英文──▶ Qwen ep02 稿(11镜) ──导入──▶ script_v2.json
   │                                                        （PREP 补全稿：人物表/场景表/造型，未导入）
   ▼
compiler.py（规则，确定性 + 依赖“当时可用 LoRA 列表”）──▶ compiled.json / visual_spec.json（原地覆盖，无历史）
   ├─ image_prompt ─▶ Qwen-Image 2.1 Turbo int8 + lin_wan_qi 0.8，8 步，cfg 1.0，1088×1920，纯文生图（无任何参考图）
   ├─ last_prompt  ─▶ Qwen-Image-Edit（图1=定稿首帧，图2=林晚母版脸）→ reinhard 校色 → 存 PNG（工作流元数据丢失）
   └─ video_prompt（= 剧本 H3 原文，只改对齐句秒数）─▶ H3 FL2VA int8（时间线所用版本：official_turbo 8 步 + 首尾帧）
          └─ last_frame_mode=none 时只换第一行对齐句，正文仍写 “Picture 2”
assemble.py（取每镜 “active” 版本，不看 locked）─▶ colormatch ─▶ 对白 TTS 盖掉 H3 原声（默认）─▶ BGM（全部 drop）─▶ loudnorm
```

**语言模型在 ep02 链路里的位置**：编译环节**没有**用 LLM（11 镜 `visual_spec.generator = rules`，`compiled.video_prompt` 与剧本 `h3_prompt` 逐字相同）。LLM 出现在上游：①Qwen（已撤下）把 v3.1 的 6 镜拆成 11 镜，并写了每镜的 H3 英文提示词；②abliteration 写的 PREP 补全稿和顾沉 / 陈宇人物表草稿，都没有进生产。所以 B 类问题集中在“剧本里由 LLM 写的 H3 英文段”，加上 §4 的现行模型重放。

## 1. 逐镜追溯表

### 1.1 剧本 → 编译

| 镜 | 时长 / H3 帧 | 剧本对白 / 独白 | 编译出的在画角色（faces_visible） | 场景 id / 底图 | 运镜（visual_spec） | 编译异常 |
|---|---|---|---|---|---|---|
| S1 | 8 s / 192 | — | 林晚 | SK-OFFICE / 无 | camera pull out | dropped `lnwan01` → 视频无林晚 LoRA |
| S2 | 6 s / 158 | 顾沉“方案第三页，数据错了。” | 林晚、顾沉 | 空 / 无 | static | video_loras=lin_wan_h3 1.0 |
| S3 | 6 s / 158 | “对不起，我马上改——”（说话人字段=“她慌”） | 林晚、顾沉 | 空 / 无 | static | 画布覆盖 `湿发贴脸`；dropped `lnwan01` |
| S4 | 6 s / 158 | “不用急。我陪你。”（说话人=“他”） | 林晚、顾沉 | 空 / 无 | static | img 与 S2/S3 逐字相同 |
| S5 | 8 s / 192 | 顾沉“冷。” | 林晚、顾沉 | 空 / 无 | static | **adult=True（关键词“裸”误判）**；dropped `lnwan01` |
| S6 | 6 s / 158 | “那我……明天还您。”（说话人=“她，不敢动”） | 林晚 | 空 / 无 | static | 林晚 facing=back（实为正面） |
| S7 | 8 s / 192 | “明天。外套，别洗。”（说话人=“他走了两步没回头”） | 林晚 | 空 / 无 | static | 同上 |
| S8 | 12 s / 294 | 独白 25.6 s（TTS） | **林晚、顾沉**（顾沉只是“西装衣领”被提到） | SK-TAXI / 无 | static | 顾沉角色锁被注入；dropped `lnwan01` |
| S9 | 6 s / 158 | 陈宇“这么大的外套？公司发的？” | 陈宇 | SK-HOME-KITCHEN（原文“玄关”）/ 无 | **空**（原文 tracking/手持） | video_loras=lin_wan_h3 1.0（男主镜） |
| S10 | 6 s / 158 | “同事借的。明天还。”（说话人=“她背对，声音平稳”） | 陈宇 | SK-HOME-KITCHEN / 无 | static | dropped `lnwan01` |
| S11 | 10 s / 243 | 独白 6.8 s | 林晚 | SK-HOME-CLOSET（place 解析成“焦点在衣橱内部与手部”）/ 无 | push in | — |

### 1.2 出图 / 视频 / 合成

首帧 11 镜都是 `qwen_t2i`：`qwen_image_2.1_turbo_int8_convrot` + `qwen3vl_8b_int8` + `lin_wan_qi_v1` 0.8，ManualSigmas 8 步，CFGGuider cfg=1.0，1088×1920，`reference=None`。时间线用的视频 11 镜都是 `h3_fl2va`：`official_turbo`（turbo LoRA v1.1）8 步，首 + 尾帧（`last_frame_mode` 当时没有这个字段，等于 use），没有附加 LoRA，`negative=""`。

| 镜 | 定稿首帧 | 定稿尾帧（图2） | 首尾帧差 | 时间线视频（是否定稿） | seed | 运动 QC | 时间线 / 实际时长 |
|---|---|---|---|---|---|---|---|
| S1 | image#4（qwen_edit_instruct，基于 #3 t2i） | last#1（母版脸） | 33.7 | video#2（**未定稿**） | 37096610396964 | pass（但 Turbo 脚重影，见 MOT） | 8.0 |
| S2 | image#4 | last#1（母版脸） | 4.4 | video#3（auto 定稿） | 21344987487846 | **fail** | 6.583 |
| S3 | image#5 | last#2（母版脸） | 6.8 | video#5（**未定稿**，定稿是 #4） | 7368018491623 | **fail** | 6.583 |
| S4 | image#3 | last#1（母版脸） | 4.8 | video#2（auto 定稿） | 231006279393518 | **fail** | 6.583 |
| S5 | image#3 | last#1（母版脸） | 47.8 | video#2（**未定稿**） | 279113605526517 | warn；画面里出现“冷”字（C6） | 8.0 |
| S6 | image#3 | last#1（母版脸） | 4.5 | video#2（auto 定稿） | 206345673685929 | **fail** | 6.583 |
| S7 | image#1 | last#1（母版脸） | 5.0 | video#2（**未定稿**） | 198038525067103 | **fail** | 8.0 |
| S8 | image#1 | last#1（**id_profile_v2**，与其他镜不同） | 4.7 | video#2（**未定稿**） | 246031615228362 | warn | 12.25 |
| S9 | image#1 | last#1（母版脸，林晚背对） | 13.4 | video#2（auto 定稿） | 96541247441274 | warn | 6.583 |
| S10 | image#1 | last#1（母版脸，林晚背对） | 5.5 | video#2（auto 定稿） | 196470470234279 | **fail** | 6.583 |
| S11 | image#1 | last#1（母版脸） | 23.3 | video#2（**未定稿**） | 281256795871646 | warn | 10.125 |

合成（`ep02.timeline.json`，10-31 07:51）：1080×1920 / 24 fps / 85.875 s / -14.1 LUFS。对白 = Kokoro TTS（H3 原声按 gate_db 40 压低），BGM 11 个提示点全部 `drop`。warnings：S8 独白盖到 S9–S11；S10 ASR 听成“同世界的明天还”；没有 qa.json，所以只是预览。

## 2. 问题清单

编号规则：A 提示 / B 语言模型 / C 渲染 / D 剪辑后期 / E 系统流程。**粗体编号**是架构性问题，汇总在 §3。

### A. 提示错误

**A1 男性角色没有族裔、没有脸部描述（S2–S10）**
- 环节：角色锁 → image_prompt；剧本 H3 英文。
- 证据：`compiled.json` 写的是 `【顾沉】34岁成年男性CEO，黑色高定衬衫，成熟克制英俊`、`【陈宇】23岁成年男性，温暖阳光，休闲装`。H3 里只有 `a man in a black tailored shirt`、`a young man in his early twenties`。林晚有“中国”，但 H3 英文只写了 `the young woman ... ice-blue hair`，族裔丢了。`data/ab/char_fix/draft_registry.py:84` 记录过：“夜间定妆候选里{names}出成了西方白人面孔；他们现有的人物文字里没有写族裔”。
- 影响：顾沉 / 陈宇的长相每镜都靠随机，种族也可能漂移（顾辰“变白人”的根因）。ep02 定稿首帧里两人看着是东亚人，但脸每镜不同，S5 和 S7 的顾沉发型、脸型都不一样。
- 根因：角色锁只来自旧剧本头；写作模型补的人物表行（`a 34-year-old East Asian man with short black hair…`）在 PREP 稿和 `registry_draft.md` 里，没有导入，也没有进角色锁。
- 修法：人物表（族裔 / 年龄 / 脸 / 发 / 体型 / EN 短语 / VOICE）作为 Shot Spec 的必填字段，资料闸门缺了就不出；H3 锚点句由编译器从人物表 EN 短语确定性生成，不靠写作者手抄。

**A2 系统统一后缀和剧本本镜内容互相矛盾**
- S11：img 写“蓝发垂落遮住部分脸部，只露出下巴和颈部线条”，系统后缀却补了“面部清晰对焦，五官锐利，暗部保留细节，面部可辨，画面光比1:4，非纯黑”；尾帧 end_state 是“画面陷入全黑”，同样带着“非纯黑，面部可辨”。结果首帧是正脸全身（拼图可见），尾帧也不黑，视频中途变黑后又被拉回尾帧（C9）。
- S2–S4：后缀“衣装完整、无裸露”和原文“黑色上衣领口微敞露出肌肤光泽”放在一起。
- S1 尾帧“周围黑暗吞噬了大部分空间”也配着“非纯黑”。
- 根因：`corrector_terms` / `lens_term` / 暗场句按关键词无条件追加，不读本镜的遮挡、朝向和暗场意图。
- 修法：后缀改成按 Shot Spec 字段（`face_visible`、`exposure_intent`）条件生成，并做冲突检测（“遮住脸”和“面部可辨”同时出现时报错）。

**A3 CFG=1 下，负面词无效，正向提示里的否定词反而起作用（全部 11 镜）**
- 证据：首帧工作流是 `CFGGuider cfg=1.0`，H3 是 `cfg 1.0 BasicGuider`，所以 `image_negative`（未成年人外观、裸露、字幕……）和 `video_negative` 实际**一个字都没生效**。H3 take 里干脆是 `"negative": ""`，但 compiled.json 里仍有 video_negative，记录在误导人。正向提示里系统自己加了“无字幕、无文字、无水印”“无裸露”“非纯黑”。项目自己的规则（v3_changes ep41）写过：“CFG=1 会把被否定的东西注入画面”。
- 影响：安全负面词形同虚设；“字幕 / 文字”反而可能被注入，S5 视频里真的出现了“冷”字（C6）。
- 修法：cfg=1 的模型不生成、不记录 negative；后缀只写正面描述（“干净画面、纯净背景”），并加一条编译校验：正向提示里出现“无/不/非 + 名词”就报错。

**A4 “提到名字”被当成“人在画面里”（S8）**
- 证据：S8 原文是“林晚在出租车后座，脸埋进**顾沉的西装衣领**”（外套在她身上，顾沉不在车里）。`present_characters` 把顾沉算进来，注入了 `【顾沉】34岁成年男性CEO…`，visual_spec.faces_visible 为 `['lin_wan','gu_chen']`。定稿首帧、尾帧和视频里，顾沉都坐在她身边（拼图 S8）。
- 根因：在画角色靠字符串匹配，“X 的 Y”这种所属格没有排除。
- 修法：Shot Spec 显式列 `characters_on_screen`（剧本“人物行”），编译器只用这个字段；所属格提及只算道具归属（prop.holder）。

**A5 剧本拆镜后首帧文字完全相同（S2=S3=S4，S9≈S10）**
- 证据：Qwen 稿镜2/3/4 的 img 逐字相同，镜9/10 只差“手持跟拍 / 正在喝水”。编译和闸门都没提示。
- 影响：三镜首帧几乎一样，再加上尾帧几乎没改 → 6 个静止镜头里 S2/S3/S4/S10 都在这一组。
- 修法：导入时做“相邻镜头首帧文字相似度”检查（只提示，不改内容），交给写作方决定。

**A6 林晚发色在各模块里写法不一致**：角色锁写“蓝发及腰”，S1 img 写“雾霾天蓝色及腰直发（比参考图略深、带一点灰）”，H3 写 `ice-blue`，旧 two_stage 写“浅冰蓝色”，PREP EN 写 `misty sky-blue`。成片里的发色都是偏深的饱和蓝（拼图）。修法：发色只在人物表 / 造型表定义一次，所有模块引用同一个值。

**A7 画布覆盖把别的集的造型注入进来（S3）**
- 证据：`data/renders/ep02/S3/edits.json`（10-31 00:34）有 `ref_overrides.characters.lin_wan.parts.hair = "lw-hair-lw-h1"`（湿发贴脸，来自 ep53 浴缸镜的造型）。S3 的 image_prompt 和 last_prompt 都带“【林晚造型】湿发贴脸”，S2/S4 没有，同一场办公室戏前后不连贯。edits.json 没有记录是谁改的。
- 修法：覆盖记录要带作者和理由；连续镜（同场景同时段）造型不一致时提示。

**A8 场景信息缺失或解析错误（全部 11 镜）**
- `scene.plate` 11 镜全是 None（没有场景底图）；S2–S7 的 `scene.id` 为空，Qwen 稿本来就没有“场景”行，PREP 稿有 `sk_office_night` 等但没导入。
- S9/S10 原文写“陈宇站在玄关”，被归到 `SK-HOME-KITCHEN`；S11 的 `place` 被解析成“焦点在衣橱内部与手部”。
- props 误报：“镜”来自“镜头”，“衣领”来自“领口”；`lighting.sources` 里混进了“黑色上衣领口微敞露出肌肤光泽”。
- 影响：办公室布局、台灯位置、林晚坐在左还是右，每镜都在变（S6 林晚在左，S7 在右），背景无法保持连续。
- 修法：场景是 Shot Spec 的结构化字段（id + 底图 + 机位），不从自由文本里猜。

**A9 visual_spec 朝向填错（S6、S7）**：林晚 facing=back，顾沉 facing=back；实际剧本是顾沉背对，林晚正面仰头。朝向会影响参考图选择和表情处理。修法同 A4：朝向写在 Shot Spec 里，编译器不猜。

**A10 S9 运镜丢失**：原文 motion 写的是“tracking shot 手持跟拍”，`visual_spec.camera_move` 为空，因为正则只认识部分英文运镜词。

**A11 成人分类误判（S5）**
- 证据：`adult_reasons=['关键词:裸']`，来源是 end_state 里的“裸露的颈侧”。连带后果：`safe_negative` 被清空（negative 只有 93 字），“衣装完整、无裸露”和“面部清晰对焦”两句没加，S5 被路由成只能本地生成。
- 修法：成人分类改为 Shot Spec 显式字段（剧本 level / explicit），关键词只做提示，不能单独翻转。

**A12 对白说话人字段是舞台提示**：“她慌”“他”“她，不敢动”“他走了两步没回头”“她背对，声音平稳”，靠启发式（`he→gu_chen (shot)`）推出说话人。这次推对了，但很脆弱。PREP 稿已经改成“（林晚，慌）”格式，但没导入。

**A13 小问题**：image_negative 里“字幕”“水印”各重复两次；legacy_video_prompt 仍然生成（带 `lnwan01`、8K 等），但没有任何环节使用，属于死字段。

### B. 语言模型错误

**B1 H3 英文段丢了族裔（11 镜，Qwen 写）**：中文锁里有“22岁中国成年女性”，H3 英文只剩 `the young woman ... ice-blue hair`；男性角色连中文锁里都没有。H3 的文本编码器只看英文段，所以 H3 生成时完全不知道人物的族裔。见 A1。

**B2 拆镜后 H3 段带着拆镜前的动作（S2）**
- 证据：v3.1 镜2（10 s，三句台词）的 H3 结尾是 `She leans in…`，soundscape 是 `…as she leans forward`。Qwen 拆成 S2/S3/S4 后，S2 的 motion 已经没有前倾（`script_ref.motion`：“……微微吞咽口水——两人距离极近的特写……”），但 S2 的 H3 仍保留 `She leans in, her expression flushed and intense`，soundscape 也一样。
- 影响：H3 文本和首帧、尾帧、motion 对不上。
- 修法：H3 段由编译器从 Shot Spec 生成，或者 LLM 生成后做“动作集合 ⊆ motion 动作集合”的校验。

**B3 S9 H3 暗示了一句剧本里没有的台词，运镜也写错了**：`He holds the coat up to ask another question` 暗示还有一句台词，但本镜只有一个 `<d>`，H3 可能自己补出含糊人声。运镜写成 `camera trucks right`，原文是“镜头缓慢推向厨房方向”。

**B4 现行写作模型重放：台词被污染、提到名字就变成在场（§4 详）**
- 用现行输入格式（说话人写在括号里，角色锁没有族裔）时，S2 两次都把说话人和语气写进了台词标签：`<d>[Chinese] 顾沉，声音低沉克制：方案第三页，数据错了。</d>`。H3 会把“顾沉，声音低沉克制”也念出来。
- S9 的标签格式写坏了：`<d>[Chinese, Chen Yu's warm and sunny young male voice…] …</d>`。
- S8 写成 `buries her face deep into the suit collar of Gu Chen, a 34-year-old adult male CEO…`，把顾沉的整段外貌带进来，等于告诉模型“他在”，和 A4 是同一种错。
- 输出直接用人名 `Gu Chen` / `Lin Wan`，H3 不认识这些名字，身份信息全丢。
- 改成带人物表 EN 行（含 East Asian）作为输入后，2/2 台词逐字正确，族裔词都在。
- 结论：只要 LLM 参与写 H3，就必须 ①输入里给结构化人物表；②输出后做确定性校验（`<d>` 内容逐字等于剧本台词、族裔词在、不出现未在场角色的外貌）；不通过就重试或打回。

（S3“改→赶”、S6“您→你”是 H3 念错，属于渲染模型问题，记在 C8。）

### C. 渲染错误

**C1 首帧没有任何身份参考（11 镜）**
- 证据：定稿首帧 PNG 内嵌的工作流只有 `EmptyLatentImage` + `LoraLoaderModelOnly lin_wan_qi_v1 0.8`，没有 LoadImage；takes 记录 `reference=None`。顾沉 / 陈宇没有 LoRA，也没有参考图（`assets/characters/gu_chen/candidates/` 里有 4 张候选，但没有接上，visual_spec 里 `plate=None`）。
- 影响：林晚只靠 LoRA 保持长相；男性角色每镜随机。
- 修法：身份参考作为资料闸门的必需资产；首帧走“参考图 + LoRA”工作流；没有参考就不出。

**C2 林晚 LoRA 的挂载和画面里有谁对不上**
- 出图 LoRA `lin_wan_qi` 0.8 是整张图生效的 model-only LoRA，S9/S10 画面主体是陈宇（林晚背对、在背景），照样挂着。
- 视频 LoRA `lin_wan_h3_v1` 1.0 的挂载不一致：S9（陈宇主镜）挂了；S1/S3/S5/S8（林晚是主角）没挂，原因是编译时 `lnwan01` 在“可用 LoRA 列表”里查不到就被 drop（`compiler.py:472 loras_for(shot.motion_triggers, dropped)`）。同一镜不同版本也不一样：S2 video#3 无、#5/#6 有；S4 #4 无、#5 有；S10 #3 有、#4 无。
- 修法：LoRA 由 Shot Spec 的在画角色 + 朝向决定（背对或不在画就不挂或降权），并且是确定性的；可用性检查放到出片前，不影响编译结果。

**C3 尾帧编辑改动太小，身份参考也用错**
- 尾帧模板写“保持图1的场景、机位、景别、光线、人物身份、发型与服装完全不变……只把画面改为……”，结果 7/11 镜的首尾帧差 < 7（S2/S3/S4/S6/S7/S8/S10）（静止的主因，QCV 已证实）。
- S9/S10 林晚背对、不在焦点，仍把林晚母版脸作为图2送进去；S8 换成了 `id_profile_v2.png`，参考图来源不统一。
- 尾帧 PNG 经过 reinhard 校色后由 PIL 重存，ComfyUI 工作流元数据丢失，无法复现。

**C4 首帧、视频和剧本对不上**
- S1：剧本要求“伏案，左手支撑下巴，右手握笔”，定稿首帧是蹲坐在椅子上、没有笔；H3 开头却写 `presses her fingers against her forehead`。
- S7：剧本是“顾沉背对镜头微微侧头”，首帧里顾沉正面看着林晚。
- S11：剧本是“手把外套挂进衣橱、脸被头发遮住”，首帧是林晚正脸、穿着黑色连衣裙（原文里连衣裙是挂在衣橱里的）。
- S5 尾帧：林晚换成黑色不透明高跟，造型表是 12cm 透明细跟。
- 修法：出片后用视觉 QC（VLM 或检测器）逐条核对 Shot Spec 的 must 事实（`visual_spec.facts` 已经列了 24 条，但没人检查）。

**C5 只给首帧时，提示词仍写 “Picture 2”（11 镜最新版本都是这样）**
- 证据：`h3_video.py:255 align_first_only()` 只换第一行，注释写“正文原样不动”。11 镜 `last_frame_mode=none` 的版本正文都还有 `settles into the pose … established by Picture 2 at the end of the shot`。
- 违反官方指南 §3.1（I2VA 应该是“first-frame anchor → action onset → continuous development”），模型拿到的是引用一张不存在的图的指令。
- 修法：I2VA / FL2VA 是两个模板，由编译器从 Shot Spec 生成，不在提交时字符串替换。

**C6 视频里出现字幕字（S5，时间线版本）**：video_002 第 4 s 左右，西装袖口上浮现白色“冷”字（scratchpad 截图）。H3 negative 为空，cfg=1；单字台词容易被模型画成字。目前没有 OCR 质检。修法：出片后加 OCR 检测；对单字台词，在提示词里写明没有可见文字。

**C7 Turbo 8 步的 4 帧一顿 / 脚重影**：时间线 11 镜全部用 official_turbo，MOT 已证实（`data/ab/motion_fix/best/metrics.md`）。默认基底在 10-31 白天才改成 official_base。

**C8 H3 念的字和剧本不一样**：S3“改”念成“赶”，S6“您”念成“你”（3 个版本都是“你”）。没有闸门拦，只在 QC 文档里记录。修法：ASR 回听和剧本比对 CER，作为定稿闸门（目前只用在 TTS 上）。

**C9 S11 中途变黑又跳回**：end_state 是全黑，但尾帧图被后缀强制成“非纯黑、面部可辨”。FL2VA 先跟着文本走到全黑，再被拉回尾帧图（时间线中段帧全黑，末帧是正脸）。根因见 A2。

**C10 长镜头靠“极小 LoRA”绕过 OOM（S8）**：video#3 `extra_loras=[['pika_h3_flex…', 0.0001]]`，是 `long_patch_lora` 补丁。在 provenance 里和真正的 LoRA 混在一起，看不出来；S8 在这之前 OOM 了 4 次。

### D. 剪辑 / 后期错误

**D1 默认对白用 TTS 盖掉 H3 原声**：嘴型必然对不上（QC 文档 §3 已证实）。H3 原声版只是变体，默认没改。

**D2 独白长度不受镜头时长约束（S8）**：S8 独白 25.6 s，镜头 12.25 s，盖到 S9–S11，和 S9/S10 的对白同时出声。导入和编译都没检查“独白时长 ≤ 镜头时长”。

**D3 ASR 失败照样用**：S10 TTS 回听 CER 0.29、`ok:false`，仍然进了成片，只在 warning 里写了一行。

**D4 BGM 实际静音，时长和提示点也对不上**：11 个提示点全部是“撤到静默（H3 已带配乐）”。ep02.wav 长 84.0 s，成片 85.875 s；music.json 的 shot_starts 按名义时长算（8/14/20…），时间线实际是 8.0/14.583/21.166…，S11 时已经偏了 3.7 s。

**D5 每镜 H3 自带的配乐都不一样**：S2/S3 等镜头的 H3 都写了 `non_diegetic_music`，切镜时音乐跳变；H3 只有一条混音轨，不能分离。

**D6 合成取的是 “active” 版本，不是定稿版本**：`assemble.py:_active_file` 只读 `active`。时间线里 S1/S5/S7/S8/S11 用的视频没有定稿，S3 用的是 video#5，而定稿是 #4。6 个运动 QC “不合格”的视频都进了成片。时间线只记录文件路径，不记录 take 号、inputs_sha、seed。

**D7 colormatch 只按首尾锚点**：S1 dE_mid 19.1、S11 dE_mid 22.5，校色计划只用 start/end 增益。对镜内有真实变化（拉远、关灯）的镜头，线性插值会给中段带上偏色。影响小，需要人眼确认。

### E. 系统 / 流程错误

**E1 资料不全仍然出片、自动定稿、合成**：`docs/ep02_readiness.md`：生产版 ep02 资料齐的镜头 **0/11**，缺 118 项（人物表、族裔、场景、身份参考……）。这些都是在出片之后才审出来的；闸门 `material_readiness.py` 是事后加的，而且要重启 API 才生效。夜间整集出片 `auto_lock` 已经把 S2/S4/S6/S9/S10 的静止视频定稿为“自动测试定稿”，至今没有撤销。

**E2 剧本版本链断了**：v3.1（6 镜）→ Qwen 拆成 11 镜（导入）→ PREP 补全稿（11 镜 + 人物表 + 场景表，未导入）。生产用的是三者里资料最少的那份。`data/looks/schedule.json` 仍然是 6 镜时代的映射（`ep02-S5: [lin_wan, chen_yu]`，没有 S7–S11），而 `sop.py` 的 SOP 闸门读的正是它。

**E3 编译不确定，inputs_sha 覆盖不全**：`video_loras` 取决于编译那一刻某条 GPU 道的 LoRA 列表；同一 `inputs_sha`（如 S2 的 c888eafbe78f950e）下出现了“无 LoRA / lin_wan_h3 1.0”两种结果。base、steps、last_frame_mode、extra_loras 都不在 inputs_sha 里。

**E4 产物覆盖写，没有可重放的 provenance**
- `compiled.json` 原地覆盖，11 镜都在首帧出完之后被重写（例如 S2 首帧 10-30 23:26，compiled 10-31 15:19；S4、S6 是 16:45），没有历史版本。
- 首帧 take 的 `params` 为 null（步数、cfg、LoRA、分辨率只能从 PNG 元数据里倒推）；尾帧 PNG 没有元数据。
- 结果：不能从 take 精确重放出同一张图。

**E5 混用过期首帧（S3）**：video#2 的 prompt 用的是新 inputs（1566d0b6…），首帧却是旧 inputs（eba004d4…）下出的 image#4。系统没有检查首帧和提示词是不是同一版输入。

**E6 作业和 API 进程绑在一起，回写会丢**
- ep02 有 9 个作业是“API 重启中断”。
- 4 个作业（S9/S10/S5/S1，10-31 05:23–05:40）在 gpu36 上**已经渲染完**，回写 Take 时 pydantic 报 `gpu Input should be a valid integer … 'gpu36:0'`，GPU 时间白花了。
- 5 个 S8 作业 OOM。
- `data/jobs/episodes/ep02.json` 只保留最后一次整集运行（533ed6f7da）；定稿记录引用的 run `ca47801717`、`dc0f5588c1` 在 data/jobs 下找不到。

**E7 坏图闸门误报（S4 image v6）**：后处理先 lanczos 1152×2016 → 768×1344，闸门再拿成品尺寸和请求尺寸比，报“坏图：尺寸 768×1344 与请求的 1152×2016 不符”，作业判为失败。

**E8 多份预览没有唯一权威版本**：data/episodes 下有 5 个 ep02 预览，其中 `S8S11截短8秒_勿用` 是早期 S8/S11 只出了 192 帧（8 s 上限）留下的。`ep02.timeline.json` 停在 07:51，之后的 active 版本都没有反映进去，也没有“已过期”标记。

**E9 画布 / 人工改动不留作者**：S3 的 edits.json（A7）、auto_lock 的 note“自动测试定稿，待项目方复审”都没有可追溯的执行者和审批记录。

## 3. 汇总：哪些是架构问题，不是单镜问题

| # | 系统性问题 | 涉及条目 | 表现 |
|---|---|---|---|
| 1 | **没有单一事实来源的镜头规格**。人物、场景、朝向、在画角色、成人分类，都是编译器从自由文本里用关键词猜 | A1 A4 A8 A9 A10 A11 A12 C2 E2 | 族裔丢失、顾沉被塞进出租车、场景为空、LoRA 挂错 |
| 2 | **编译不是纯函数**。结果取决于运行时 LoRA 列表；后缀无条件追加，不做冲突检测 | A2 A3 C2 C9 E3 | 同一输入出不同 LoRA；“遮脸”配“面部可辨” |
| 3 | **提交时修改提示词**（只换对齐句、注入图2句、补丁 LoRA），修改不回写规格 | C5 C10 C3 | I2VA 正文仍写 Picture 2 |
| 4 | **LLM 输出没有受约束，也没有校验** | B1 B2 B3 B4 | 台词被污染、加动作、丢族裔 |
| 5 | **产物没有 provenance、不可重放**：覆盖写、params 为空、元数据丢、哈希覆盖不全 | E3 E4 E5 D6 | 说不清哪张图是怎么出来的 |
| 6 | **闸门在错误的位置**：资料闸门事后加、QC 不拦定稿、合成不看定稿 | E1 D3 D6 C4 C6 C8 E7 | 0/11 资料齐也照出；不合格视频进成片 |
| 7 | **作业和 API 进程耦合**，回写 schema 太脆 | E6 | 9 个作业中断、4 个已出片的结果丢失 |
| 8 | **时长 / 音轨约束没有建模**：独白、对白、BGM、H3 音乐各算各的 | D1 D2 D4 D5 | 声音盖镜、BGM 静音 |

## 4. 附：语言模型重放明细

脚本：scratchpad `llm_replay.py`；结果：scratchpad `llm_replay.json`（不在项目内）。

任务：给写作模型一段中文镜头规格（img、motion、对白、时长、角色描述），要求它写 H3 I2VA 的 `integrated_multimodal_description`，并且明确要求“台词逐字、不加人、不加台词”。

| 次 | 镜 | 角色描述来源 | 族裔词 | `<d>` 逐字 | 观察 |
|---|---|---|---|---|---|
| 1 | S2 | 现行角色锁（男性无族裔） | 只有 chinese（林晚） | ✗ | `<d>[Chinese] 顾沉，声音低沉克制：方案第三页，数据错了。</d>`；直接用人名 Gu Chen |
| 2 | S2 | 同上 | 同上 | ✗ | 同一种污染，可复现 |
| 3 | S2 | PREP 人物表 EN 行 | chinese + east asian | ✓ | 锚点句带完整外貌；人名用中文字符（H3 不认识，需要去掉） |
| 4 | S2 | 同上 | 同上 | ✓ | 同上 |
| 5 | S8 | 现行角色锁 | chinese | —（无对白） | 写进了顾沉的完整外貌，等于让他在场（A4 的 LLM 版） |
| 6 | S9 | 现行角色锁 | chinese | ✗（标签格式写坏） | `<d>[Chinese, Chen Yu's warm…voice…] …</d>`；陈宇没有族裔 |

调用次数 6，token 2727 + 1914，估算 **$0.0066**（上限预算 $5，余量充足）。没有写回任何项目文件。
