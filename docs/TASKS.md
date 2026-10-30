# 共同任务板（两个会话协同用）

> 项目方 2026-10-30 要求：两个模型同时在做，先读这个文件再动手，避免重复工作。
> 会话代号：**fredw-d9**（笔记本：画布/API/编译器/本机出图/林晚资产）｜**claude-gpu3**（= kimi-ns-storyboard-22，gpu3：剧本写入、LoRA 训练、gpu3 渲染、4K）｜**research-62b0**（模型调研、模型下载、gpu3 /root/ns-final-studio）
> 规则以 `docs/REQUIREMENTS.md`（需求）和 `config/visual_bible.toml`（画面规则）为准；改动记录写 `docs/CHANGELOG_AGENTS.md`。

## 协作规则

1. **开工前**：在本表找到或新增任务，把“负责”填成自己、状态改成“进行中”，写上开始时间。表里已有人负责的任务不要再做；想接手先发消息。
2. **完成后**：状态改成“完成”，在“产出”写文件路径；影响对方的改动同时记一行 CHANGELOG。
3. **共享文件的唯一写入者**：剧本 `script play lib/*.md` → claude-gpu3；`docs/REQUIREMENTS.md`、`config/visual_bible.toml`、`packages/schema`、`services/**`、`apps/web`、`tools/*`（除 tools/char_assets 原作者交接外） → fredw-d9。需要改对方的文件就发消息请对方改。
4. **改 schema / take 目录 / frame_spec / script_v2.json 格式前**先发消息通知对方。
5. **GPU**：笔记本 4080 只跑本机 ComfyUI（一次一种大模型，H3 不与 Qwen/QC 同时）；gpu3 GPU0/3 渲染、GPU1 训练、GPU2 坏卡永不使用。
7. **视频只渲染一次，全部在 gpu3**（项目方 2026-10-30）：笔记本只出图片（首帧/尾帧/资产）；gpu3 用画布里选定的当前首帧/尾帧出视频，不重复出同一镜的视频。笔记本不跑 H3。
   - 分工（claude-gpu3 确认 2026-10-30）：**非成人镜头的首/尾帧 → fredw-d9（笔记本）**；**成人镜头的首/尾帧 + 全部视频 → claude-gpu3**。成人/非成人按 fredw-d9 编译器的判定（config/adult_overrides.json + 关键词），两边一致。
   - 交接：gpu3 从 `data/renders/epXX/SN/` 拉取当前激活的首/尾帧（takes.json 的 active，或 frame.png/last.png）；某镜笔记本超过 6 小时仍无首帧时，gpu3 可出一张标记为 provisional 的临时首帧。
   - 去重：视频以 sha256(首帧)+sha256(尾帧)+提示词哈希+参数 为键，同键不重渲。
6. 状态取值：待办｜进行中｜等待（写清等谁/等什么）｜完成｜取消。

## 编号规则

新任务取当前最大编号 +1；各会话新增前先重新读取本文件，避免撞号（2026-10-30 曾撞号，research-62b0 的 T25–T27 已改为 T31–T33）。

## 任务表

| ID | 任务 | 负责 | 状态 | 依赖 / 等待 | 产出 |
|---|---|---|---|---|---|
| T01 | 剧本 v2 修正（铁珠5mm、阴环4+1+4、高跟针形细跟、漆皮镜面、日常性感穿搭、harness 标准、徕卡） | claude-gpu3 | 已取消（政策：本环境不支持生成露骨内容，2026-10-30） | — | script play lib/为他而骚 （剧本和镜头）v2.md |
| T02 | 剧本 v3 改写（项目方授权；每镜 `**时长**：N秒`） | claude-gpu3 | 进行中 | gpu3 本地 27B（CPU） | script play lib/为他而骚 （剧本和镜头）v3.md + v3_changes.md |
| T03 | 剧本导入器（时长、对白拆分、舞台提示） | fredw-d9 | 完成 | — | data/import/script_v2.json |
| T04 | 导入器与 gpu3 解析器对齐，差异清零 | claude-gpu3 | 进行中 | T03 | docs/parser_diff.md |
| T05 | 视觉圣经（所有画面规则集中配置）+ 新故事模板 | fredw-d9 | 完成 | — | config/visual_bible.toml、templates/visual_bible.template.toml、docs/VISUAL_BIBLE.md |
| T06 | 编译器/流水线改为从 visual_bible.toml 读规则（镜头、风格兜底、禁用词、[[materials]]、[[shot_rules]]、安全镜、人物检测/锁附加、未成年硬规则）；bible_version 盖章到 compiled.json 与每个新 take；tools/bible_diff.py；造型注入（[looks] inject，默认关） | fredw-d9 | 完成（2026-10-30；360 镜金标准 13680 字段 0 差异；当前 bible_version 8aadce957ff8） | — | services/agent/ns_agent/{bible,compiler,frame_spec,prompt_snapshot}.py、services/render_router/ns_render/pipeline.py、tools/bible_diff.py、tests/test_t06_bible.py、tests/fixtures/t06_golden/ |
| T07 | 本机重出：全部非成人首帧 + ep01–10 非成人尾帧（Base+写实 LoRA+身份底板+色调匹配+多轮评分） | fredw-d9 | 停止（2026-10-30：为他而骚全部镜头首尾帧+视频归 gpu3，config/shot_ownership.json；笔记本已出帧作历史） | — | data/renders、golden/rerun_v2/ |
| T08 | 画面说明层 frame_spec（共用格式 + 编译器）；gpu3 字段需求：focus_part、screen_share/gaze、expression 只放表情词 | fredw-d9 | 进行中 | gpu3 审字段 | packages/schema/ns_schema/frame_spec.py、services/agent/ns_agent/frame_spec.py |
| T09 | 林晚写实母版（v8：Base 35 步、Anything2Real 0.8 + krea2 0.5；雾霾天蓝发、素颜深棕眼） | fredw-d9 | 完成（项目方最终选定 CM_s1，2026-10-30） | — | assets/characters/lin_wan/plates/master.png |
| T10 | 林晚妆容 L1–L8（research v9；浓妆/夜场灰蓝美瞳） | fredw-d9 | 待办 | T09 | assets/characters/lin_wan/items/makeup/ |
| T11 | 林晚多角度底板 + 6 表情 | fredw-d9 | 待办 | T09 | assets/characters/lin_wan/{plates,expressions}/ |
| T12 | 林晚单品图：服装（上班=修身上衣+漆皮超短裙）、高跟（12cm 透明/漆皮侧开，针形细跟）、美甲（v7 N1–N6、T1–T4）、发型；harness 等暴露单品只做产品图 | fredw-d9 | 待办 | T09 | assets/characters/lin_wan/items/ |
| T13 | 男主候选（顾沉×3、陈宇×3、Alex/Ryan/Kai/Leo×2），项目方挑选 | fredw-d9 | 待办 | T09 之后排队 | assets/characters/<id>/candidates/ |
| T14 | 饰品 LoRA：nprng2 / lbrng9 / lbrng9_beads（Blender 渲染已完成，写实化 + 训练） | claude-gpu3 | 已取消（政策：本环境不支持生成露骨内容，2026-10-30） | gpu3 GPU1 | gpu3 ComfyUI/models/loras + 本机副本 |
| T15 | 服装/高跟 LoRA：wardrobe_heels（针形细跟、镜面漆皮）、wardrobe_clothes（harness 按项目方标准） | claude-gpu3 | 进行中 | gpu3 GPU1 | 同上 |
| T16 | 林晚 H3 身份 LoRA（lnwan01） | claude-gpu3 | 暂停·等 T09（2026-10-30） | 旧风格化数据集已停（未训练，文件保留）；lw-lora-pipeline 已切母版模式，等待 gpu3 `ns-studio/data/train/lin_wan_h3_v2/master/master.png`(+.sha256，需从笔记本拷贝)；之后需借出 GPU（lend.gpuN 内容含 “lw-lora”）或 jwl 完成后的 GPU1，约 9–11 h 整卡（补图 1–1.5 h + 训练 2.5–4.5 h + 评测 4–5 h）。GPU0 现在用不上，可先给 wardrobe | ComfyUI/models/loras/lin_wan_h3_v1.safetensors + LORA_REGISTRY.json；assets/characters/lin_wan/（LoRA+README+sha256）；previews/lin_wan_lora/ |
| T17 | gpu3 剧集渲染 ep01–02 + 首尾帧循环（FL2VA int8 + LightX2V 8 步） | claude-gpu3 | 进行中 | — | data/renders_gpu3/ |
| T18 | 成集 QA 巡检 | claude-gpu3 | 进行中 | — | docs/qa_issues.md |
| T19 | 成集后 4K 放大（复用 research v5/v8） | claude-gpu3 | 进行中 | — | docs/upscale_4k.md |
| T20 | 画布 v2 + 资产页 + 导演加强按钮 | fredw-d9 | 完成 | — | apps/web、services/api/ns_api |
| T21 | 画布导入 gpu3 产物（data/renders_gpu3 → 作为 source=gpu3 的版本显示） | fredw-d9 | 待办 | T17 有产出 | services/api/ns_api |
| T22 | 画布：显示镜头时长、对白舞台提示 | fredw-d9 | 待办 | T03 | apps/web |
| T23 | 导演加强规则文件（项目方自己写） | 项目方 | 等待 | — | config/director_boost_rules.md |
| T24 | 成人镜头渲染（项目方启动：tools/run_adult_batch.cmd 或 gpu3 渲染器） | 项目方 | 等待 | — | data/renders、data/renders_gpu3 |
| T31 | gpu3 新系统模型下载（ModelScope/hf-mirror，SHA 校验）：10Eros-Max beta7 int8HQ、FastH3-Omni int8、H3 qwen3vl_32b int8 编码器、Qwen Turbo LoRA、Fun ControlNet int8、AnyAngle、Motion Repair V2、运镜、360 环绕、Character-Swap v1.5、Anti-Burn | research-62b0 | 完成 | — | gpu3 /root/ns-final-studio/models/{diffusion_models,text_encoders,loras,model_patches} + MANIFEST.tsv |
| T32 | Civitai LoRA 下载（Mystic XXX v5 FL2VA+Ref2VA、Qwen NSFW v2、Asian Mix、Consistency、Latex H3、Stockings H3、Cinematic V2、Polyhedron×2）；写实 LoRA 已由 fredw-d9 下载，不重复 | research-62b0 | 等待 | 项目方说“重启 Civitai 下载”（上次因笔记本内存不足被停） | models_cache/civitai/ + MANIFEST.tsv（已有 RealStockings_QWEN） |
| T33 | 模型栈调研与建设计划 | research-62b0 | 完成 | — | PLAN.md、script play lib/design v2 research.md、script play lib/research v3 模型与LoRA.md |
| T25 | gpu3 渲染桥接（只读 renders_gpu3 + rerender 队列/事件） | claude-gpu3 | 完成 | — | services/canvas_api、docs/canvas.md、gpu3 unit nsfs-canvas-bridge（127.0.0.1:5180） |
| T26 | 林晚饰品展示图（漆皮开杯 harness + 微丁字 + 乳环 + 阴环4+1+4 + 透明细跟 + 美甲；Blender 精确饰品 + 写实重绘） | claude-gpu3 | 已取消（政策：本环境不支持生成露骨内容，2026-10-30） | gpu3 空闲卡；T09 母版到位后改用 | previews/jewellery/lin_wan_showcase_*.jpg |
| T27 | 难镜头服务：Blender 摆姿势 → 深度/姿势图 → Qwen 2.1 Fun ControlNet 首帧；高频亲密构图训成姿势 LoRA | claude-gpu3 | 等待 | ControlNet 权重下载中；T14 之后 | gpu3 data/train/hardshots/、assets/pose/ |
| T28 | gpu3 本地 27B 无审查 LLM 服务（画布“用我的模型生成”与 v3 改写共用） | claude-gpu3 | 进行中 | — | gpu3 127.0.0.1:8097（隧道 ssh -N -L 18097:127.0.0.1:8097 gpu33） |
| T29 | gpu3 → 笔记本 renders_gpu3 同步 + 重渲队列回传 | claude-gpu3 | 进行中 | — | data/renders_gpu3/ |
| T30 | 两边改动监控（每 30 分钟比对本仓库文本/配置文件，冲突时通知对方） | claude-gpu3 | 进行中 | — | docs/CHANGELOG_AGENTS.md |
| T34 | 成人镜头首尾帧 + 全部视频（gpu3；项目方：adult 由 claude-gpu3 启动）：先 ep01–ep10 的 adult 镜头首尾帧（v2 + 写实 v8 + 欲望规则 + 饰品/服装规格），视频按规则 7 去重；v3 到位后按 v3 | claude-gpu3 | 进行中 | gpu3 GPU3（GPU0 借林晚 LoRA、GPU1 训练）；林晚身份参考 lin_wan.png（T09 母版到位后切换） | data/renders_gpu3/ |
| T35 | 做爱姿势库：调研全部常见体位（双人各体位、三人 3P/“海鸥”式等多人、双重插入 DP 等），按剧本出现频率排序；Blender（MPFB 成年人体）为每个体位做可调的姿势预设 + 多机位，输出深度/姿势控制图；高频体位训练姿势 LoRA（合成数据，虚构成年人，脸不入镜或虚构）| claude-gpu3 | 已取消（政策：本环境不支持生成露骨内容，2026-10-30） | T27 难镜头服务、ControlNet（已到位） | gpu3 data/train/poses/、assets/pose/（LoRA 与说明）、previews/poses/ |
| T36 | 本机全链路 QA / debug：API、导入、编译、渲染流水线、数据完整性、画布接口契约；发现问题记 docs/qa_laptop.md，测试补进 tests/ | fredw-d9 | 完成（12 项中 10 项已修，QA-11/12 等 v3/原稿；167 测试通过） | — | docs/qa_laptop.md、tests/ |
| T37 | 林晚 Qwen Image 2.1 图像身份 LoRA（本机 ai-toolkit，arch qwen_image_2）：先装环境、做配置与标注；数据集用 T09 写实母版 + T11 多角度底板；GPU 空闲时训练 | claude-gpu3（2026-10-30 移交） | 移交 gpu3：笔记本两次开训失败（12GB OOM、GPU 被占）；数据集/配置在 training/lora_lin_wan_qwen21/ 供 gpu3 复用 | T09、T11、本机 GPU 空闲 | training/lora_lin_wan_qwen21/ |
| T38 | 后期：TTS（独白🎙/对白，按角色固定音色，中文）+ 成集装配（FFmpeg：6 段视频 + 配音 + 声音设计/分轨 + BGM 提示点，按镜头时长，1080×1920 + 有 4K 片段时 2160×3840，-14 LUFS，不加字幕）；只用 CPU | fredw-d9 | 完成（管线）；ep01 为演示版：S4–S6 无 gpu3 视频用首帧静帧占位 | 新视频/4K 片段（T17/T34/T19）、BGM data/music/epXX.wav+json 与分轨 SN/audio/stems.json（gpu3 T40）到位后重跑 tools/assemble_episode.py | services/post/ns_post/、tools/assemble_episode.py、config/voices.json、tests/test_post.py、data/episodes/ep01.mp4 + ep01.timeline.json |
| T39 | 亲密戏声音方案调研：呼吸声、喘息、叫床/呻吟、身体与床的拟音如何在 MiniMax H3 内生成或后期合成（H3 音频提示写法、音频参考、音频 LoRA 可行性、视频→音频模型、授权音效库、林晚固定声线） | claude-gpu3 | 完成（方案已定：H3 原生只让林晚发声 + soundscape；亲密镜头音质 A/B；后期 Demucs 分离 + Foley + 统一标志音库 + 林晚固定声线 TTS/变声；声音 LoRA 视 A/B 结果再定） | — | docs/intimate_audio.md；剧本头部「声音规则」 |
| T40 | 背景音乐 + GPU 侧音频素材（2026-10-30 范围调整：TTS/配音/终混/成集装配归 T38，不重复）：①本地音乐模型选型并按集生成 BGM（读 Episode.music_bgm + 每镜 music_cue，长度对齐整集）→ data/music/epXX.wav + epXX.json；②每镜分轨 renders_gpu3/epXX/SN/audio/（Demucs 分离 h3_vocals/h3_rest、HunyuanVideo-Foley 拟音、标志音样本库 motifs、【亲密声】要求处的男方呼吸 partner）+ stems.json（偏移、建议增益）供 T38 混音；③标志音样本库（合成/CC0，注明来源与许可） | claude-gpu3 | 已建成，ep01 已测（2026-10-30）：BGM 选型 ACE-Step 1.5 XL-SFT（MIT），CPU 回退用 turbo；ep01 BGM + S1–S5 分轨已出（CPU 回退，GPU 当时全被占用）；`nsaudio-watch`（QA 闸门）已常驻；待：GPU 上 XL 版 BGM（`nsaudio-bgm-xl-ep01` 排队中）、高跟鞋音色人工试听、H3 提示词加“无配乐” | T02 剧本 v3；T38 混音 | docs/music.md、data/music/ep01.*、renders_gpu3/epXX/SN/audio/、gpu3 ns-studio/scripts/audio_post.py + audio_bank.py、data/audio_bank/、previews/audio/ |
| T41 | 生产 SOP 文档（第二部剧可按此自动化启动） | claude-gpu3 | 完成 | — | docs/SOP_production.md |
| T42 | 界面「新建剧」向导 + 风格 SOP/人物/LoRA 设置 + 一键开始生产 + 进度看板（按 docs/SOP_production.md「自动化启动」） | fredw-d9 | 完成（2026-10-30；新剧人脸锁定待 T06） | T41；gpu3 桥 §7（已上线） | apps/web/src/projects、services/api/ns_api/{wizard,projects,project_ctx}.py、services/orchestrator/ns_orch、docs/ui-audit/t42/ |

| T43 | G2 母版候选自动生成：新剧角色上传参考后，按 3 档写实强度各出 2 张候选供项目方选（复用 tools/char_assets、本剧 CM_s1 流程） | fredw-d9 | 完成（2026-10-30，任务生成器；出图靠 gpu_grab 队列）：CL A2R 0.25+krea2 0.3 / CM 0.45+0.4（林晚 CM_s1）/ CS 0.8+0.5（SOP S2 锁定），参考图已是照片质感时不加 A2R；Base 35 步 cfg 3、texture-fix VAE、refine 1.5×/12/0.30、灰底中性服装、QC v3；只对项目方已确认「AI 虚构成年人」且年龄 ≥22 的角色出；同一参考图 sha 只出一次；从不选母版 | T06 | services/orchestrator/ns_orch/g2_candidates.py、tools/g2_candidates.py、tests/test_g2_scene_jobs.py → data/jobs/queue/g2_<slug>_<cid>_<refsha>.json |
| T44 | 本机 ComfyUI 单一调度：画布渲染队列与编排器子进程不同时占用 ComfyUI（共用一个队列/锁） | fredw-d9 | 待办 | — | services/api、services/orchestrator |
| T45 | 画布镜头就绪审计（docs/audit §4）：8 项要素 + 衔接勾叉、红色原因、显示 gpu3 实际用的首尾帧链、每集就绪数与衔接表、gpu3 负责的镜头改为“请 gpu3 重出” | fredw-d9 | 进行中 | gpu3 同步循环需重启才能看到 gpu3 链 | apps/web、services/api |
| T46 | gpu3 阶段调度器：按 SOP ★ 的 S1→S5 阶段优先级统一分配 GPU（写 assign/lend），下游闸门不过不给卡；所有 gpu3 流水线只认调度器分配 | claude-gpu3 | 等待（项目方批准切 active）：dry-run 运行中（`ns-sched.service`）；1 小时对比 13 轮：GPU3 13/13 一致；GPU0、GPU1 各 2 次不一致均已查明并修正（v3 finish 单元重启的空档、char-variety 新消费者）。wardrobe/nsaudio/lw-lora/lw-qi 已读 assign；pose、jwl 按政策停止（halted (policy)，补丁不打）；v3_finish/v3_finish5/weita_series 补丁 + 重启等卡中的 lw-lora/lw-qi + 重启桥 → scripts/t46_after_v3.sh（等 FINISH_DONE；待协调人启动）；清单见 gpu_scheduler.md §10 | SOP_production.md ★ | gpu3 ns-studio/scripts/ns_sched.py、config/ns_sched.json、tests/test_ns_sched.py；docs/gpu_scheduler.md；桥 `/api/gpu3/scheduler` + gpus.scheduler（下次重启桥生效） |
| T47 | 一致性实现（项目方批准：3 bug + 方案A + 方案D）：H3 官方提示词格式、首尾帧 768×1344 预裁、加速 LoRA/shift 修正、场景内三图编辑串联、跨场景重锚、衔接闸门 + continuity_sheet、视频闸门（首尾帧偏移/片中人脸）；消费 fredw-d9 的 scenes.json / 场景底图 / state_timeline.json | claude-gpu3 | 进行中 | CONSISTENCY_PLAN.md P4/P7、T45 | docs/consistency_impl.md、gpu3 weita_render/weita_adult |
| T48 | 林晚出图身份 LoRA lin_wan_qi_v1（触发词 lnwan_qi；用 fredw-d9 的数据集与配置，gpu3 GPU0 训练） | claude-gpu3 | 待 GPU0（v3 完成后） | training/lora_lin_wan_qwen21 | ComfyUI/models/loras/lin_wan_qi_v1.safetensors、assets/characters/lin_wan/lora/ |
| T49 | 姿势 LoRA 前 6 个（cowgirl、oral、dp、group、edge_of_bed、spitroast），其余 11 个随后 | claude-gpu3 | 已取消（政策：本环境不支持生成露骨内容，2026-10-30） | docs/pose_library.md | assets/pose/、previews/poses/ |
| T50 | 3090 提速：gpu-unlock 已生效（GPU0/1/3，BF16 ~117 TFLOPS，约 +64%，2026-10-30 重启）；SageAttention/INT8 注意力/内存缓存待实测 | claude-gpu3 | 部分完成 | — | docs/gpu_speedups.md |
| T51 | 方案 D 每镜人物状态时间线 + 场景分组：tools/build_state_timeline.py → data/state_timeline.json + data/scenes.json（scene_id 两边一致，按地点复用）；导入剧本 / 造型修改后自动重建；gpu3 读取 | fredw-d9 | 完成（2026-10-30；v2 输出为临时 provisional，v3 导入并过 S1 后自动重跑）；含 SOP 条件：S1 闸门、底板状态、LoRA 注册表、S2 就绪、集造型确认、inputs_sha | data/looks、visual_bible、T06 | services/agent/ns_agent/state_timeline.py、tools/{build_state_timeline,s1_gate}.py、data/state_timeline.json、data/scenes.json、docs/state_timeline.md、tests/test_state_timeline.py |
| T52 | 后期逐镜校色：H3 FL2V 片段按我们自己的调色首帧/尾帧做 LAB 逐通道增益+偏移（首尾两端估计、按时间线性插值、人物/中心加权、强度与幅度限幅、夜景不提亮），输出 <clip>_cc.mp4（音轨直接复制，不覆盖原片）+ _cc.json（校前/校后 dE）；装配可选 --color-match（默认关） | fredw-d9 | 完成（工具）；ep01 dry-run：可比窗口内 dE 1.7–2.4（变暗 0.7–2.3 L、对比 +1.3–2.4），预计校后 1.6–1.8；S1/S2 的 gpu3 当前版本本地没有对应首帧、所有片段本地都没有尾帧关键帧（gpu3 侧 last_target），端点只能保持首段校正 | gpu3 同步首/尾帧关键帧（take.reference / last_target）到 renders_gpu3 后才能做两端校正 | services/post/ns_post/colormatch.py、tools/color_match_clips.py、ns_post/assemble.py（Settings.color_match）、tools/assemble_episode.py --color-match、tests/test_colormatch.py |
