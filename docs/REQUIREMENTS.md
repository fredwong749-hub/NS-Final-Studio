# 项目方需求清单（唯一准绳）

> 所有开发、出图、调参前先对照本清单；新需求追加到这里并注明日期。状态：✅ 已落实｜⚠️ 部分｜❌ 未落实。
> 最后整理：2026-10-30

## A. 画面质量

| # | 要求（项目方原话要点） | 状态 | 落实位置 / 缺口 |
|---|---|---|---|
| A1 | “真人效果” = 画面接近实拍、去掉 AI 塑料味；角色全部合成 | ⚠ | 首帧链：两段式出图后单独一批“轻精修”（Base 12 步 + PureLens 0.4 + texture-fix VAE，denoise 0.22；A/B 见 golden/quality_v2/owner_ab，项目方要保留参考图感觉，写实只作质感）；评分含“真人感”0–10（本地看图模型）。身份参考 = 项目方通过的母版 plates/master.png（CM_s1）脸部裁切。2026-10-30 起本项目首尾帧归 gpu3（config/shot_ownership.json），本机链路保留供其它项目/对照 |
| A2 | 高清级别，**Leica 镜头锐利度**，电影级调色和画面感 | ✅ | 编译器追加光学措辞“Leica Summilux-SL {焦段} f/{光圈} 级别的锐利解析力与微反差，焦平面上眼睛与睫毛清晰锐利…”，焦段光圈取自剧本后缀；后缀已有 Leica/徕卡 时不加（compiler.lens_term）。评分含主体锐度（Laplacian） |
| A3 | 不要字幕；画面干净；专业镜头画面感 | ✅ | 剧本 img/motion 统一后缀 + 负面词 |
| A4 | 颜色丰富艳丽，**色调参考项目方给的林晚定妆图**（assets/style/color_reference_01.png） | ✅ | 所有首帧（含非林晚镜头）出图后做 LAB Reinhard 颜色迁移到 assets/style/color_reference_01.png，力度 0.6，只增不减反差/饱和；暗场/夜景不动亮度、绝不提亮、色度偏移减到 35%（ns_render/grade.py）；未调色原图保留为 takes/*_raw.png。本机无 KJNodes ColorMatch（只有核心 ColorTransfer），故用 Python 实现。尾帧以定稿首帧为参考迁移（0.7） |
| A5 | 大光圈浅景深（f/1.4） | ✅ | 风格后缀 |
| A6 | **图生视频，首尾帧图片决定画质**（2026-10-30）：生图提示词必须做好；保持参考图那种**浓郁色调**、大光圈、**背景虚化（奶油焦外）**（⤴ 风格后缀部分已被 L-018 徕卡 S★ 与契约 I7 取代，L-087 选 R0 维持）；首尾帧靠这些细节提升画面质感 | ⚠ | 首帧：身份底板 + 作用说明、两段式（先文生图出构图，再用底板只换脸和发型——直接带底板编辑会照搬正脸构图，见 golden/quality_v2/sweep）、Leica 措辞、色调匹配、焦外占比评分；尾帧独立生成（C3）。写实度仍差（A1） |

## B. 人物一致性

| # | 要求 | 状态 | 落实位置 / 缺口 |
|---|---|---|---|
| B1 | 林晚必须与 **assets/linwan** 一致（浅冰蓝及腰直发、齐刘海、冷白皮、精致妆容） | ⚠ | 身份参考改为项目方通过的母版 assets/characters/lin_wan/plates/master.png 的脸部裁切（只取脸和刘海，避免把项链/玫瑰带进镜头；ns_render/refs.py），母版缺失时退回项目方参考图脸部裁切，再退回 M0–M6 妆容底板。两段式：先文生图出构图，再“只把五官、妆容、发色发型换成图2（浅冰蓝及腰直发、齐刘海…）”——直接带底板编辑会照搬正脸构图，长篇作用说明会让换脸失效（golden/quality_v2/sweep、idfix）。评分核对“浅冰蓝色及腰长直发、齐刘海” |
| B2 | 人物要做**多角度资产**（正/侧/背/全身/表情）来保证一致性，参考短剧平台做法 | ❌ | 待调研 + 建角色资产流程 |
| B3 | 林晚脸部来源：项目方确认为 AI 生成（含车内自拍） | ✅ | config/face_reference.json |
| B4 | 每集切换人物资产（衣服、鞋、妆容、发型、饰品 D 状态） | ⚠️ | data/looks 已建；60 集均待项目方确认（集计划 owner_confirmed_at）；编译器已接入造型注入，开关 visual_bible `[looks] inject`（默认关，只对确认过的集生效，打开前用 tools/bible_diff.py --inject-preview 看差异并 A/B）；每镜状态见 data/state_timeline.json（T51） |
| B7 | **高跟鞋鞋跟规格**（2026-10-30）：跟高 **12cm**；鞋跟**细到一根筷子那么粗**（直径约 6 毫米，针形细跟），现有透明高跟样图的跟太粗 | ✅ | 编译器对含“高跟/细跟/hh12clear/hh12patent”的镜头追加一次“鞋跟直径约6毫米、细如一根筷子的针形细跟，跟高12厘米”（风格后缀前），并作为 Frame Spec 的 must 事实由评分核对；资产图/LoRA 数据集待重做 |
| B8 | **全部漆皮材质**（2026-10-30）：漆皮高跟鞋的跟同样要筷子般细；**所有漆皮**（高跟鞋、束腰、风衣、捆绑内衣等）都必须是**像抹了油一样的高亮镜面漆皮**——湿润光泽、镜面反射、高光锐利 | ✅ | 编译器对含“漆皮”（及 ptx* / hh12patent 触发词）的镜头追加一次“漆皮为像抹了油一样的高亮镜面漆皮，表面湿润光泽，镜面反射清晰，高光锐利”，并作为 must 事实核对 |
| B9 | **林晚的妆容要更精致、更性感**，人物描述“还差点意思”（2026-10-30）；要 deep research 妆容细节与人物描述 | ❌ | 妆容调研 research v9 进行中；之后基于写实母版重做 M0–M6 |
| B10 | **林晚日常穿着偏性感**（2026-10-30）：平时上班也穿**漆皮超短裙**（按 B8 高亮镜面漆皮），衣服整体偏性感，**不要保守的衣服** | ⚠ | ①已改：安全镜条目改为“衣装完整、无裸露”，去掉“保守”“职业装”；安全镜负面改为“裸露、走光、低俗姿势”；非成人追加负面去掉“性感暴露”（裸露质检照旧）。②③由剧本/资产会话负责 |
| B6 | **林晚的衣服、鞋子、美甲都要用 image 模型生成**成资产图（2026-10-30） | ⚠️ | 2026-10-30 改由本机（fredw-d9 资产 agent）负责全部林晚资产生成；妆容 M0–M6 已生成，写实母版与 L1–L8 妆容、底板、单品进行中 |
| B5 | **林晚美甲**（2026-10-30）：手指甲 **5 厘米超长**、最新款**透明延长甲、镶满钻石饰品**；脚趾甲 **2 厘米**、超性感美甲；要 deep research 款式，并用 image 模型多生成几款美甲资产 | ⚠️ | 已登记为 data/looks 单品；款式调研与资产图生成进行中；编译器：脚趾甲条目已从林晚 DNA 锁移出，只在镜头原文写到赤脚/脚趾/露趾/透明高跟时追加（避免无故赤脚） |

## C. 剧本与提示词

| # | 要求 | 状态 | 落实位置 / 缺口 |
|---|---|---|---|
| C1 | **严格按 script play lib 的提示词**：《image提示词》§1.2 拼装公式（垫图 + DNA 锁 + 场景锁 + 装饰锁 + 分镜 img + 负面）、§2.2 垫图优先、透传不加戏 | ⚠️ | 垫图、DNA 前置、纠正器条目已落实；场景锁 SK-* / 装饰锁全文（数据C）不在仓库；每镜 2 张择优未做 |
| C2 | 《3提示词纠正器》调参条目 | ⚠️ | 1.1 特写、1.2 暗场、1.3 安全镜已落实；1.1 网红脸、1.2 蓝发色号按 B1 不启用 |
| C3 | 视频用**首尾帧**实现（剧本资料写明） | ✅ | 尾帧作为独立资产：pipeline.render_last_frame 以当前首帧为图1（768×1344）+ 身份底板为图2 做 Qwen 2.1 编辑，提示词 = 编译字段 last_prompt（motion 最后“——”后的结束状态 + “同一场景同一人物同一服装”）；存 takes/last_NNN.png（stage "last"），当前版本复制为 last.png；render_video 优先用画布指定尾帧（next/上传），其次当前独立尾帧。视频只在 gpu3 出；本机尾帧链只在沙箱验证过（golden/quality_v2/smoke2），2026-10-30 起本项目尾帧由 gpu3 出 |
| C5 | **剧本是画面推动的**（2026-10-30）：每个镜头的首/尾帧必须用 image 模型**多轮生成**，直到达到剧本描写的细节 + 项目方要的色彩与镜头画面；对应《image提示词》§1.2 每镜多张择优（人脸相似度、装饰数量、无缺陷），失败重试 ≤3 | ✅ | pipeline 多轮多候选：每轮 3 张构图 → 裸露质检 → 本地 Qwen3-VL 8B（ComfyUI TextGenerate）逐条核对 Frame Spec facts（+身份、未写赤脚时“没有赤脚”）→ 最好的构图换脸 → 调色 → 评分（剧本 0.40、脸 0.15、真人感 0.15、色调 0.10、锐度 0.10、焦外 0.10；2026-10-30 起裸露只记录、不否决），全部留档、最高分设为当前，低于 0.65 再来一轮（批量 2 轮），仍低记 takes.json review。单镜约 5 分钟（与资产会话共用 ComfyUI）。2026-10-30 重出 30 镜（ep01–ep06 非成人）后按项目方决定停止：本项目首尾帧+视频归 gpu3 |
| C4 | 铁珠 5 毫米、每串一颗；阴环左 4 右 4 阴蒂 1；高跟默认 12cm 透明，偶尔 12cm 漆皮侧开 | ✅ | 剧本已改（剧本唯一写入者：kimi-ns-storyboard-22 会话） |

## D. 模型与生产

| # | 要求 | 状态 | 落实位置 / 缺口 |
|---|---|---|---|
| D1 | 首帧用 **Image 2.1（Qwen Image 2.1）或 Klein** | ✅ | Qwen Image 2.1 Turbo int8（本机）；Klein 未做对比 |
| D2 | 成人画面本地无审查模型生成，由项目方启动 | ✅ | 本机启动器 run_adult_batch 已按项目方要求移除（2026-10-30）；当晚进一步取消成人过滤器（T61、docs/UNCENSORED.md）：成人镜头不再需要单独启动，也不再被任何闸门拦 |
| D3 | 模型选择要 deep research，能达到剧本细节 | ⚠️ | research v3–v5；均未实测 |
| D5 | **成集通过 QA 后做最终 4K 放大**（2026-10-30） | ⚠️ | gpu3 会话负责，复用 research v5/v8（MMH3 Ultimate Upscale / Regenerate-2K / SeedVR2 3B int8 + 颗粒），文档 docs/upscale_4k.md |
| D4 | 多 agent 并行开发 / debug / render；遇到问题自我迭代 | ✅ | — |

## E. 画布

| # | 要求 | 状态 | 落实位置 / 缺口 |
|---|---|---|---|
| E1 | 每镜显示首尾帧图片、提示词、镜头、表情，方便二次修改与重渲 | ⚠️ | 2026-10-30 项目方：**首尾帧图片没有在镜头卡上展示**（尾帧只有出视频后才有） |
| E2 | 参考短剧平台的界面与交互；每集切换人物资产要可见 | ✅ | 2026-10-30 项目方：**没有认真 deep research 小云雀、Seedance 等短剧平台的交互页面**，要单独开 agent 调研，再开新 agent 修改交互；封板核对 2026-10-30：已落实（docs/research/short_drama_platform_ui.md；T54-B） |
| E3 | **每个镜头必须有**：首帧图、尾帧图、镜头提示词（首帧/视频）、剧本原文、人物图（该镜用到的角色资产图）、表情等细节 | ⚠ | 尾帧需要作为独立资产先生成（不是等视频出完才有）；人物图需接角色资产；封板核对 2026-10-30：界面八要素已有（画布行 + R-C1 阻断），数据侧尾帧等仍缺 |
| E4 | 交互要经得起大量人工操作（耐用） | ✅ | 以调研结论为准修改；封板核对 2026-10-30：已落实（离线等待、失败重试、批量确认） |
| E7 | **v2 画布不合格，要重做**（2026-10-30 项目方）：①集视图改为**一镜一行**（左：首帧、尾帧 9:16 大图并排；右：镜号·景别·运镜·时长、剧本、表情、对白/独白、人物资产小图、提示词折叠、状态）；②**图太小看不清**——首尾帧和资产图要大，点击全屏对比；③**文字太多太乱**——行内只留关键信息，提示词等收进检查器；④**操作流程不顺**——改提示词→重出→对比→选定要顺手；⑤**资产页不好用**——要像小云雀的角色卡：大定妆图、造型 A/B/C、单品一目了然 | ✅ | 重做中；封板核对 2026-10-30：已落实（T59、T54-B 一镜一行、大图、检查器、改词→重出→对比），待项目方验收 |
| E8 | **画布加 soundscape 提示词，让 H3 声音更自然**（2026-10-30）：按 H3 官方提示词规范（docs/h3_prompt_guide_base_en.txt §4.6–4.7）每镜有 `overall_soundscape`（1–4 句英文：环境声、动作声、呼吸等非语言人声，不含对白）和 `non_diegetic_music`（**背景音乐**：本集默认 + 单镜覆盖，1–3 句英文：乐器、速度、节奏、强弱；无则 N/A，项目方 2026-10-30 追加），默认取剧本 sound（v3 的【H3 audio】优先），画布可编辑 | ✅ | 编译器按官方格式拼进视频提示词；画布视频页可编辑；封板核对 2026-10-30：已落实（H3 面板、resolve_music、H3-S3 机检）；配乐规则（X-4，项目方 2026-10-30 选“按 E8 写进 H3”）：H3 的 non_diegetic_music 带本集 / 单镜配乐（取值 = 本镜修改 > 剧本 **H3提示词** 字段 > 【配乐】静默提示（N/A）> 本集【BGM】英文，函数 ns_agent.h3_prompt.resolve_music）；后期对 H3 已带配乐的镜头不再叠加 BGM（ns_post.music.h3_music_shots，装配时这些镜头的 BGM 静音，时间线 bgm.h3_music_shots 记录） |
| E5 | **人物资产 tab / 资产管理**：每个角色的参考图、服装、高跟鞋、美甲、发型、造型 A/B/C 等，可上传、管理、组合成造型 | ✅ | 2026-10-30 项目方提出；data/looks 只有数据和接口，没有资产管理页面；封板核对 2026-10-30：已落实（CharacterCard.tsx、PeoplePage.tsx、manage.py） |
| E6 | 资产设置要能**驱动出图**：用 Image 2.1（Qwen Image 2.1）或 Klein，把造型里的参考图（脸、服装、鞋、美甲、发型）作为多参考输入 | ⚠ | 待角色资产调研（research v6）给出做法；封板核对 2026-10-30：部分（角色卡「用这些参考出图」+ gpu3 出图队列 :8100 已通，端到端未验证） |

## F. 流程

| # | 要求 | 状态 |
|---|---|---|
| F1 | 先整理好需求再执行（本文件） | ✅ |
| F2 | 成人批量要提醒；未确认就弹窗问 | ✅ |

## G. 分工（硬规则，2026-10-30 项目方定）

> 项目方原话：“现在3张显卡，必须有一张是qwen来运行，其它2张训练lora，记住qwen负责剧本，镜头，提示词等内容写作”；“claude opus 负责写系统”；“claude不做任何内容参与，也不评价内容，分工清晰，qwen主要负责内容”。

| # | 要求 | 状态 | 落实位置 / 缺口 |
|---|---|---|---|
| G1 | **内容全部由 Qwen 负责**：剧本、分镜/镜头设计、画面与视频提示词、训练集标注（caption）、LoRA 样图/评测提示词、造型与妆容描述，以及内容方面的评价和挑选（好不好看、像不像、选哪张、哪个 checkpoint 好）。项目方拍板的关口（G 系列确认）不变 | ⚠ | gpu3 GPU3 :8098 Qwen3.8-27B（T53）；现有流水线里由 Claude 写的内容逐步换成 Qwen 写 |
| G2 | **Claude（所有 Claude 会话）不参与任何内容，也不评价内容**：只写系统——代码、流水线、调度/锁、数据格式与校验、文件/哈希/分辨率等技术检查、把 Qwen 的输出**原样**接进系统。Claude 不写、不改、不润色 Qwen 的内容，不对画面或文字给审美判断；技术闸门（格式、字段齐全、哈希、尺寸、裸露检测等自动 QC）属于系统，可以由 Claude 实现 | ⚠ | 本条起生效；Claude 遇到内容问题时转给 Qwen 或项目方，不自己回答 |
| G3 | **gpu3 分卡**：3 张可用卡（GPU0/1/3；GPU2 坏卡永不用）中**1 张常驻 Qwen 写作模型**，**另 2 张训练 LoRA**。2026-10-30 项目方定具体卡：“gpu1 一直挂着 qwen”，**GPU1 = Qwen 常驻**，**GPU0 + GPU3 = LoRA** | ⚠ | T53：GPU1 当前被 lw-lora-pipeline 出图占用，迁移脚本 gpu3 unit qwen-migrate-gpu1 等它结束后把 Qwen 从 GPU3 挪到 GPU1、Qwen Docker 挪到 GPU3；按任务边界用锁接手，不杀进程 |
| G4 | **Blender 代码与 LoRA 训练由 Qwen 接管**（2026-10-30 项目方：“qwen接管blender代码和lora”）：Blender 场景/渲染代码、LoRA 数据集、训练配置、训练与评测都由 Qwen 负责；Claude 不再写 Blender/LoRA 代码，只负责让 Qwen 能运行的基础设施（gpu3 分卡与锁、Qwen 服务） | ⚠ | 交接：林晚+服装 LoRA 数据集 training/lora_lin_wan_qwen21_outfit/、gpu3 data/train/lin_wan_qi_outfit/（未开训；Claude 写的 14 条标注与样图提示词待 Qwen 重写） |
| G5 | **Claude 不参与任何内容，也不参与任何内容审核**（2026-10-30 项目方：“claude不参与任何内容以及审核”）：Claude 不看图/看文审阅内容，不批准、不驳回、不挑选、不打分、不提修改意见；内容审核由 Qwen 和项目方负责。自动 QC（裸露检测、哈希、尺寸、字段齐全等）属于系统代码，Claude 可以实现和维护，但审核标准与阈值由项目方/Qwen 定，Claude 不自行增删或解释审核结论 | ⚠ | 本条起生效；适用所有 Claude 会话 |
| G6 | **Qwen Docker 负责全部内容、Blender、LoRA 训练；画布由 Claude 与该 Docker 做基础通讯合作**（2026-10-30 项目方原话：“qwen docker负责全部内容,blender,lora训练,至于画布,claude和这个docker做基础通讯合作”） | ⚠ | gpu3 `/root/qwen-agent/`：容器 qwen-agent（Qwen Code 智能体，连 :8098；Blender 5.2.3、ai-toolkit 只读挂载；只看得到分给它的一张卡）；通讯接口 gpu3 127.0.0.1:8099（POST /tasks {from,text,meta} → {id}；GET /tasks/<id> 查状态与 Qwen 原样输出；笔记本 `ssh -N -L 18099:127.0.0.1:8099 gpu33`）。Claude 只收发，不看、不改、不判断内容 |
| G7 | **Claude ↔ Docker Qwen 通讯规则**（2026-10-30 项目方：“你整理好通讯…docker qwen 负责写剧本，镜头提示词，训练 lora，blender 训练，以及部分爬虫任务”；“结果返回给你是剧本细节，claude 的画布短剧生产流直接启动 minimax 执行”；“image 模型也是通过 docker 来建立起来，需要的时候调度 image docker 来生成首尾帧图片”） | ⚠ | **docs/qwen_comms.md**：信箱 :8099（任务 / 状态 / 交付物文件）；Qwen 交付 script.md（与剧本库同格式）→ tools/import_script.py 原样导入 → 画布生产流 → MiniMax H3；Image Docker 按需调度到 GPU0/GPU3（下一步实现） |
| G8 | **写作 = gpu3 本地 Qwen（:8098）；abliteration 太贵、已放弃（只保留为可选后端）；Qwen Docker 主要做 LoRA 训练与 Blender**（2026-10-30 项目方先说“qwen写作部分交给abliteration来做,qwen主要任务还是训练lora和blender任务现在”，后改回“还是用qwen写吧，api那个太贵了”）。Claude 仍只写系统、不写不评内容 | ⚠ | 画布「剧本创作」对话框（T58，provider=qwen；abliterated-model-large-v2 仅可选），系统提示词 = config/script_chat_rules.md + config/qwen_writer_system_prompt.txt + 剧本全局头；输出过 tools/validate_qwen_script.py；信箱任务 20261030T025143-f48d4702 已通知 Qwen 启动 LoRA/Blender |

## 2026-11-01 项目方新提（原话照录，fredw-92/PF 会话里收到，已转总调度 fredw-92 分派；状态：待做）

| # | 原话 | 状态 |
|---|---|---|
| R11-1 | “把 Flex 设成默认基底” | ✅ config video_bases.default = pika_flex（fredw-92/PF，default_change_pf 有回退说明） |
| R11-2 | “还有一个很重要的bug,就是演员的眼睛不要看镜头,这是不对的,你参看cinecrew(github)的一些提示词和演员拍戏的规则.第二,剧情镜头还是很慢,因此我洗完没有渲染的地方把以上2点修复.” | ⚠ 系统 + 规则已做，写作返修已派 PRODUCER（ACTING 11-01）：表演 / 视线规则带出处 docs/acting/PERFORMANCE_RULES.md（CineCrew、MiniMax-H3 skills、Wikipedia、Backstage）；出图补正向视线句 asset_refs.EYELINE_NOTE（K-REN-G01）；H3 固定插 open_motion_cue / eyeline_cue（K-REN-G02）；写作 K-WRT-A01–A05 + QW-A1–A5；看镜头已转拦截（项目方 11-01 16:10 原话转拦截（D-VQA-01 / L-080：config/vqa.json gate.enforce=true、judge.enforce=true））：出图走本地看图闸门 Q9 的 eye_contact / posed_stiff（命中就重出，闸门先于视频）；像素视线检测 G1 / score_clip.acting 仍只作旁证（K-REV-G04 修订）；测试 tests/test_acting_system.py、tests/test_acting_lints.py |
| R11-3 | “对于没有render video的集数,重写修改剧本bugs,不看镜头,镜头节奏很慢,通过修改时间轴的提示词,你留这些需求” | ⚠ 已派 PRODUCER：未出片镜（ep02 S2/4/5/6、ep03 S1/2/4/5、ep05 S3/5、ep06 S3/6/7/8、ep07 全、ep08 全、ep09 除 1 镜、ep10 除 1 镜）走 qwen_repair_loop --fix-warn --only-codes QW-A1..A5 → 合并导入；节奏规则 QW-A3（第一拍即动、拍长 ≤2.5 s、不连两拍静止）；未合并前出片需总调度定是否暂停 |
| R11-4 | “第三,我发现生图的一致性还是很多bugs,鞋子不一致性,在不同的镜头鞋子就错了;人物的一致性也是不行;有些地方生图发生了多一只手,因此需要api llm进行每次产图判断合不合格,这个写到本地规则去,调度api llm进行判断图,视频等合格,是否出现不正常,你思考补充类似的错误图和视频等判断逻辑,写到本地规则,添加到sop检查去” | ⚠ 系统已落实，已转拦截（VQAGATE，项目方 11-01 16:10 原话转拦截（D-VQA-01 / L-080：config/vqa.json gate.enforce=true、judge.enforce=true））：本地看图模型 Qwen3-VL-8B 部署在 gpu36 :8870，图片不出本机；22 项出图检查 + 5 项视频检查（鞋、多手、身份、多人等），每项对应一条契约项（config/vqa.json），已接进 postflight Q9 / V9（REFLOCK）、PRODUCER 记录、SOP §8 §9；规则 K-REV-V01…V04、K-REN-V05、K-WRT-V06，测试 tests/test_vqa.py。新增跨镜连贯 continuity_break（同场上一镜首帧作参考）、摆拍 posed_stiff；只拦 defect（高置信），unsure 只记录；图片闸门先于视频（build_jobs 只派 Q9 通过的首帧）。标定结果 docs/vqa/GATE_CALIBRATION.md；缺口：视频层拦截（V9）在第二段做 |
| R11-5 | “btw,我想了想,我需要你code个出图,出视频等检测规则,这些规则需要你帮忙写,合不合格,然后用api llm来做大脑分析, 写入到系统去” | ⚠ 系统已落实，目前只记录（VQA 11-01）：检测规则写成代码 ns_agent/vqa/（rubric / client / contract / judge）；“大脑”按项目方 11-01 改为本地视觉模型（成人内容不出本地），写作网关只收文字。缺口同 R11-4（标定） |
| R11-6 | “图和视频等bugs:演员的眼睛对视问题很大,剧本和镜头提示词问题,需要你添加agent去找演员训练规则,一个演员要完成剧本故事要做什么,故事的一些场景情节需求,演员的眼神,表情,语气等应该怎么做才合理有画面感?这个需要agent添加逻辑到导演剧本规则去” | ⚠ 规则已进写作 / 导演提示词：writer_knowledge.md（K-WRT-A01 视线、A04 表情与语气、A05 多人反应）+ director_system_prompt.md 判定标准（视线无落点 / 第二人无表情 → fail）；出处 docs/acting/PERFORMANCE_RULES.md；写作返修已派 |
| R11-7 | “出图的问题,这个图很明显出现错误,然后对应的视频也是,而且像素很低,后期可以用scale视频高清放大模型放到4k,这个写到sop去”（附图 #42） | ⚠ SOP 已写，实测进行中（VQA 11-01）：SOP §12 加了“只对已批准片做的 4K 后处理”（gpu33 SeedVR2 3B，绝不用 GPU2，QC 不过回退 Lanczos），config/vqa.json upscale_4k、K-EDT-V07；49 帧片段已在 gpu33 GPU3 空闲窗口排队实测，耗时和质量结果见 docs/vqa/STATE.md |
| R11-8 | “字幕不是要求不加么?你忘记了?你又不会看记忆了;还有一个通用bug,就是每个镜头第一帧,演员都看着镜头,而且停顿1秒多,这个是不合理的,写入规则去掉”（附图 #43） | ⚠ ① 字幕：ns_post.ffmpeg.assert_no_subtitles 硬拦（NO_SUBTITLES=True，无开关，K-REN-G03，测试 tests/test_acting_system.py）；现有合成本来就不加字幕，项目方看到的字幕来源未查到（可能是 H3 自己画字或审片页显示台词）——score_clip 加了字幕带检测（只记录）。② 首帧看镜头 + 停顿：H3 open_motion_cue + 出图视线句 + QW-A3；score_clip.acting.first_sec 测首秒定格 / 看镜头（只记录，暂定阈值下 ep01-S6、ep02-S1 等检出） |
| R11-9 | “新bugs:当画面出现超过一个人,第二个等,他们面部表情,眼神是没有,这是剧本提示词的错误,写入剧本镜头规则按照minimax h3的镜头提示词写” | ⚠ 写作 K-WRT-A05 + QW-A5（反应= 写“名字：视线 + 表情”，H3 每人一句，按官方 ref-en 多人例）；编译器 lint RL-E1（多人露脸镜 H3 视线 / 表情短语数 ≥ 人数）、RL-E2（H3 写看镜头）；现稿 QW-A5 103 处，写作返修已派 PRODUCER |
| R11-10 | “bugs[Image #44] 这个出图错误,需要每次出图本地视觉大模型自己判断是否正确,把图片信息返回给api llm做判断;失败了,把反馈错误的信息以及更新提示词重跑,写入规则”（附图 #44） | ⚠ 闭环已转拦截（VQAGATE，项目方 11-01 16:10 原话转拦截（D-VQA-01 / L-080：config/vqa.json gate.enforce=true、judge.enforce=true））：本地看图写文字描述和缺陷清单 → 写作网关（只收文字，judge.text_only_guard）判 pass / fail，并给 prompt_delta → PRODUCER 已接 review_round，每轮写进 take.params.vqa_rounds；judge.enforce=true：命中就重出——PRODUCER _postflight 先过本地看图闸门（不过不设为当前），下一次出图套用 prompt_delta（producer.vqa_delta），每轮只改一个维度，最多 3 轮；驳回替换版也由闸门自动复核（G0）；K-REN-V05 / 006。项目方的示例图 #44 拿不到，改用总调度驳回的图做样例 |
| R11-11 | “以上很多基础的bugs,rsi agent应该可以发现的,我暂时打个样给了你,然后类似的问题,你生成一堆问题,然后一点点去debugs和check,然后端更新规则到本地代码系统去” | 待做（RSI：以 R11-2…R11-10 为样例，自己生成同类问题清单 → 逐条复现 / 检查 → 把结论固化成本地规则和代码检查；RSI 漏检这些问题本身也要查原因） |
| R11-12 | “所以现在生图用flux吗?如果是,把flux调参数的也学明白,启动agent上去学习,然后回来检测我们的剧本提示词对不对?把学会的规则和bad cases写入本地规则系统,然后每次新剧本写的时候follow这些规则系统” | 待做。事实：现在出图不是 Flux，是 Qwen Image 2.1（预览 Turbo，默认预设 leica_sstar；定稿档 Qwen Image 2.1 Base）；FLUX.2 Klein 只是 config/edit_engines.json 里未启用的改图候选。按原意改为：研究 Qwen Image 2.1 的调参和提示词写法 → 回查现有剧本出图提示词 → 规则和 bad cases 写进本地规则系统，新剧本写作必须遵守 |
| R11-13 | “我只关心生成真人的逼真的效果,那个强而已,你帮我决定,同时社区很多微调参数,你这个需要拍个agent去学习参数,尤其真人微调参数” | 决定（fredw-92/PF 代定，项目方授权）：生产先继续用 Qwen Image 2.1（整条出图链都建在它上面；身份来自脸部参考图、走统一的 frame_v9 路径——lin_wan_qi_v1 身份 LoRA 已按项目方决定移出出图链并隔离）；同时派 agent 研究社区真人写实调参 / 微调（Qwen Image 2.1 的写实 LoRA、采样参数、提示词；以及 FLUX.2 等对手的写实微调），用同一组镜头做真人写实 A/B（皮肤质感、光影、手、脸一致性）。只有对手在“真人逼真”上明显更强、且身份一致性不掉，才提出换模型，由项目方挑。学到的参数和 bad cases 写进本地规则系统。总调度已把 R11-12 / R11-13 合并交给 BAKEOFF（docs/ep02_iter/image_bakeoff.md），做“各自调到最好再比”的真人写实对比 |
| R11-14 | “保留 Flex 做视频默认”（项目方已知它替换了 official_base 24 步方案后确认） | ✅ 维持 video_bases.default = pika_flex |
