# 核心总纲 · 附录：决定、资产、UI、剧本清单（2026-10-31 21:00 整理）

[docs/CORE.md](CORE.md) 的完整明细，整理时只读、不评价内容。
- 路径都相对项目根目录。缩写：`CL` = docs/CHANGELOG_AGENTS.md，`REQ` = docs/REQUIREMENTS.md，`OWR` = docs/owner_requirements_for_writer.md，`RQ` = config/render_quality.json，`MEM` = Claude 记忆目录。
- 前后决定有冲突时，以日期最新的为准；被替代的旧条目标“（已被覆盖）”。

---

## A. 项目方已做的决定（原话 · 日期 · 出处）

### A1 画面 / 写实
- 10-29 15:34 · "真人效果" = 画面质感接近实拍、去 AI 塑料味，角色全合成 · OWR §A6 L379；REQ A1；MEM ns-final-studio-realism-meaning.md
- 10-29 15:42 · "画面必须达到高清级别,leica镜头锐利度,电影级别的调色和画面感" · OWR §A6 L358；REQ A2
- 10-29 16:01 · "不要字幕,画面保持专业镜头的画面感,干净,颜色丰富艳丽…镜头采取大光圈" · OWR §A6 L356；REQ A3/A5
- 10-29 19:30 · "浓郁色调,大光圈镜头,产生那种背景虚化的感觉" · OWR §A6 L357；REQ A6
- 10-30 · 色调参考 = 林晚定妆图（assets/style/color_reference_01.png） · REQ A4
- 10-30 · "图生视频，首尾帧图片决定画质"，生图提示词必须做好 · REQ A6
- 10-30 · 林晚长相以项目方参考图的感觉为准，否决 research v8 写实母版："我喜欢我给你的linwan参考图，你现在的没有感觉"；写实只加在质感上 · MEM ns-final-studio-linwan-look.md
- 10-31 · 默认出图预设改为徕卡 S★："leica_sharp效果最好，用他"，后续选"S★ 全套组合" · CL L63–64；RQ `default_preset_note`、`image_presets[0].note`（现值 default_preset = leica_sstar）
- 10-31 · 出图配置先选 C（Turbo + texture_fix VAE + krea2 0.5 + lin_wan 0.6），之后被 S★ 取代 · RQ `auto_final_on_lock_note`、`image_presets[1].note`

### A2 一致性 / 人物
- 10-29 07:39 · 林晚脸 = 项目方提供，"记得这个样子"（AI 生成的虚构角色） · assets/characters/lin_wan/lin_wan.provenance.json
- 10-30 · 林晚脸部（含车内自拍）"也是 AI 生成的"，approved_for_adult=true · config/face_reference.json；REQ B3
- 10-30 · 林晚身份母版定 CM_s1（中度写实·种子1）："这个最好，决定用这个"，取代 CL_s0 · assets/characters/lin_wan/plates/master.provenance.json；MEM ns-final-studio-linwan-look.md
- 10-30 · 林晚与 assets/linwan 一致（及腰直发、齐刘海、冷白皮、精致妆容） · REQ B1
- 10-30 · 人物要做多角度资产（正/侧/背/全身/表情） · REQ B2
- 10-30 · 每集切换人物资产（衣服、鞋、妆容、发型、饰品） · REQ B4
- 10-29 20:03 · 高跟 12cm、鞋跟"跟一根筷子粗那么细"（约 6mm） · REQ B7；OWR §A3 L268
- 10-29 20:04 · 所有漆皮"抹上油那种,很亮的漆皮镜面" · REQ B8；OWR §A3 L260
- 10-29 20:05 · 妆容"化妆也不够精致,sexy" · REQ B9；OWR §A6 L387
- 10-29 20:06 · 林晚日常"平时上班也是穿漆皮超短裙"，不要保守衣服 · REQ B10；OWR §A3 L265
- 10-29 19:26 · 美甲：手指甲 5cm 透明延长甲镶钻，脚趾甲 2cm · REQ B5；OWR §A3 L272–274
- 10-29 06:42 · 男性角色"要小鲜肉样子"，不要老男人 · OWR §A2 L239、Q13
- 10-30 · 饰品规格（数量/位置/5mm 珠、每串一颗）见 OWR §A3 L276–280；REQ C4
- 10-30 02:55 · 珠子颜色定"还是不锈钢本色" · OWR §3 Q1；CL L255
- 10-30 · 林晚出图身份 LoRA "linwan lora直接使用；系统自动补"触发词 · config/auto_lora_triggers.json `note`/characters.林晚
- 10-31 · 顾沉/陈宇夜间定妆候选（西方面孔）："交给写作模型按 v3 补"；"全部作废，按新描述重出"（文件保留） · CL L82；data/assets/asset_refs.json gu_chen/chen_yu `void.owner_quote`
- 10-31 · 身份参考选定："林晚A-s202 顾沉s101 陈宇s202脸" · data/assets/identity_refs/manifest.json `owner_quote`
- 10-31 · 写作模型 VOICE 声线改自然语速："改成正常节奏" · docs/ep02_iter/writer_requests.md W1；docs/ep02_iter/LEARNED_SPECS.md §D3

### A3 视频配方
- 10-30 · 视频用首尾帧实现（剧本资料写明） · REQ C3（已被 10-31 新配方覆盖为"只给首帧"默认）
- 10-30 07:30 · 时长写整数秒："minimax要求的时间怎么没了"；实际长度交给 H3 · OWR §1.2 L60、§4 第 11 条
- 10-31 · 视频"完全是废品……你采取任何方式都要搞定"，授权全权处理 → 默认改 official_base 24 步 + 只给首帧 · CL L12–13；RQ `video_bases.default_decision`（现值 default = official_base）
- 10-31 · "画面连贯性很差，女主角的脚移动出现影子多腿问题；…很卡顿，很慢的节奏" · CL L31
- 10-31 · "Pika H3 Flex 下载体验一下，画面可以选择基底" · CL L313；RQ `video_bases_note`
- 10-31 · VBVR 附加视频 LoRA："加，不商用，纯粹自己研究技术" · CL L107；RQ `optional_video_loras[0].owner_decision`
- 10-31 · "用真实照片训练的 LoRA 看看效果"（A/B） · CL L305
- 10-31 · 定稿时自动排定稿档："打开" · CL L108（**已被覆盖**：10-31 项目方批了“撤销定稿 (Recommended)”，以配置 false 为准；CHANGELOG 21:30 已更正）
- 10-31 · H3 提示词"按秒来计算动作"、镜间衔接、眼神表情互动、节奏太慢 · docs/ep02_iter/prompt_bug_v1.md L3；LEARNED_SPECS L114/L117
- 10-31 · 撤销 ep02 五镜视频定稿（S2/S4/S6/S9/S10）："撤销定稿"，文件保留 · CL L377
- 10-30 · 一镜一人说话（H3-D7 对所有镜 block） · OWR §3 Q9；CL L270（"一镜一人是项目方原话"）

### A4 声音 / 配乐
- 10-29 20:53 · "剧本也要增加背景音乐提示词" · OWR §A5 L328
- 10-30 · 画布加 soundscape / non_diegetic_music（背景音乐本集默认 + 单镜覆盖） · REQ E8
- 10-30 · 配乐 X-4 选"按 E8 写进 H3" · REQ E8
- 10-30 · 亲密镜男方无台词、无声 · OWR §3 Q10/Q11
- 10-31 · 听 H3 原声版后"声音好一些，男生的声音有点生硬" → 对白来源默认 h3 · CL L363；RQ `post.dialogue_source.owner_decision`
- 10-31 · "不接受 S6 念成了'明天还你'"；修法三选全要 · CL L367
- 10-31 · 旁白"一定要更加年轻，语气和描写都要更好一点"（音色切换属项目方闸门，未切） · writer_requests.md W6；data/assets/proposals/narrator_voice_candidates.json
- 10-31 · TTS 语速"改成正常节奏"（林晚 0.9→1.0、vo 0.86→1.0；顾沉 0.92→1.0） · config/voices.json `speed_owner_decision`
- 10-31 ~17:30 · "整集统一 BGM"（H3 自带音乐压低 12 dB，铺统一配乐） · CL L378；RQ `post.h3_music.owner_decision`（覆盖 10-30 的"H3 带配乐的镜不叠 BGM"）

### A5 剪辑 / 节奏
- 10-30 01:37 · 镜与镜之间"避免跳的离谱…这是最大bug"（同场景逐字一致） · OWR §A7 L418
- 10-31 · 节奏"改成正常节奏"：动作按正常速度在 N 秒内做完 · LEARNED_SPECS §D3；writer_requests W1
- 10-31 · 需要 editing director 审片；每版给他看，不理就继续迭代直到叫停 · MEM ns-final-studio-ep02-iterate-loop.md
- 10-31 17:40 · "只对 episode two 进行 iterations"；两个 loop 合一，目标"比 Seedance 更强大" · docs/ep02_iter/RSI_PLAN.md L3
- 每集 6–8 镜 / 50–75 秒不是项目方原话（助手规格） · OWR §3 Q14

### A6 写作 / 剧本
- 10-29 20:46 · 亲密镜要写【亲密声】 · OWR §A1 L187
- 10-30 03:34 · 含亲密镜的集"标红" · OWR §1.1 L33
- 10-30 07:20 / 07:33 · uncensored、更露骨、"我需要很多成人做爱画面" · OWR §1.1 L26–28
- 10-30 · 写作者可在大纲之外新增亲密场次（限已有成年角色） · OWR §3 Q12
- 10-30 · 首尾帧规格词由"系统自动补"，不改透传 · OWR §4 第 1 条；MEM ns-final-studio-workflow-alignment.md
- 10-30 · 先读全库把成人限制 layout 出来、做完全部 uncensored · CL L285
- 10-30 · "测试一集无标红的"（ep02 端到端） · data/import/import_log.jsonl（10-30 21:42）
- 10-31 · ep02 补全稿导入："仍然导入" · CL L375；import_log 10-31 17:21
- 10-31 · ep02 PROMPTv2 导入："仍然导入 (Recommended)" · CL L382；import_log 10-31 20:08
- 10-31 · 完整 pipeline "从第一个 point 到 last point 梳理清楚…每个 chain 之间都有自己的一些规则和 format" · docs/PIPELINE_CHAIN.md L5
- 10-31 · 学到的东西变成本地 system + 一对 prompt，以后新剧本不靠 Claude 驱动 · MEM ns-final-studio-autopilot-goal.md
- 写作方变更时间线：10-30 Qwen 写（G1）→ 10-30 下午改 abliteration（"qwen写作部分交给abliteration来做"）→ 10-30 07:35 改回 Qwen（"还是用qwen写吧，api那个太贵了"）→ 10-30 夜撤下千问（"我可能会不用千问了…调度外部的 API"）→ 10-31 现行 abliteration API（large-flash） · REQ G8；OWR §0 L6；MEM ns-final-studio-qwen-gpu3-division.md、ns-final-studio-session-ownership.md；docs/USER_GUIDE_v1.md L5（**两份文档不一致，以较新的 memory / CHANGELOG 为准**：10-30 夜撤下千问，10-31 起写作方是 abliteration API）

### A7 流程 / 闸门 / 自动化 / 分工
- 10-30 · "claude opus 负责写系统"；"claude不做任何内容参与，也不评价内容" · REQ G 节 L74、G2
- 10-30 · "claude不参与任何内容以及审核" · REQ G5；CL L200
- 10-30 · "qwen接管blender代码和lora" · REQ G4；CL L199
- 10-30 · "gpu1一直挂着qwen"（GPU1 Qwen、GPU0+3 LoRA）（已被 10-30 夜撤千问、10-31 GPU 全给 ep02 覆盖） · REQ G3；CL L206
- 10-30 · qwen docker 负责内容/blender/lora，画布与之通讯 · REQ G6/G7
- 10-30 · 需求先整理再执行，REQUIREMENTS 为唯一清单 · REQ F1；CL L172
- 10-30 · 总调度：项目方"我现在只和你交流""所有请求来这边" · MEM ns-final-studio-master-routing.md
- 10-30 · "很烦，全部问我""你能不能全自动一点"：只问本人闸门 / 花钱 / 删除 / 推翻旧决定 · MEM ns-final-studio-full-auto.md、ns-final-studio-master-decide-dont-ask.md
- 10-30 · 去掉成人启动器："去掉run_adult"；成人过滤器取消 · CL L229；REQ D2
- 10-30 · ep02 "造型确认，这次跳过底图"（项目方本人运行 s2_waiver） · CL L239
- 10-30 · 成集通过 QA 后做最终 4K 放大 · REQ D5
- 10-30 · 两边实时对齐（监控） · CL L154
- 10-31 · 资料齐全才 render："不具备资料的，会不要render" · CL L45
- 10-31 · "你启动自动图片检测，看看 bugs 在哪里" · CL L71
- 10-31 · GPU 全给 ep02、停 LoRA 训练 · MEM ns-final-studio-ep02-iterate-loop.md（覆盖 10-31 凌晨"lora 和 blender 那个任务我已经授权了，gpu 空闲就跑起来"，CL L307）
- 10-31 · gpu36 加入渲染阵列："把 gpu33 环境复制过去 gpu36""当 gpu 不做 image 的时候也可以转成 rendering video" · CL L93
- 10-31 · comfy 缓存改 --cache-ram："同意" · CL L105
- 10-31 · 审片页本地打开："不要跳到claude.ai去 在本地给我看" · MEM feedback-local-review-pages.md
- 10-31 · 回复里"需要我做 decision 的 layout 出来" · MEM feedback-decision-layout.md
- 10-31 · 闸门不因全自动取消：定妆/身份设为当前、删除、超授权花钱、推翻旧决定 → 项目方 · RSI_PLAN.md §闸门 L21–22
- 10-31 · UI：全力 uiux 迭代、学小云雀细节并整合 · CL L32、L54
- 10-30 · 画布：v2 不合格重做，一镜一行、首尾帧大图、资产页像小云雀角色卡 · REQ E7；MEM ns-final-studio-canvas-editor.md
- 10-31 晚 · 标识 momoso：“候选 2 · 双环” · 来源：总调度会话记录；apps/web/src/v3/TopBarV3.tsx L16 注释

### A8 许可 / 花钱
- 10-31 · VBVR（CC BY-NC）仅非商用研究："加，不商用，纯粹自己研究技术" · RQ `optional_video_loras[0]`；CL L107
- 10-31 下午 · “Fresh 的 API 已经付费了，我再充了 50 美金进去”（Fresh 就是 abliteration） · 来源：总调度会话记录；MEM ns-final-studio-session-ownership.md
- 10-30 · "api那个太贵了"（当时改回本地写作） · REQ G8
- 成人画面只走本地模型，不走闭源 API · MEM ns-final-studio-realism-meaning.md；REQ D2

---

## B. 人物与资产现状

### B1 assets/characters/
| 角色 | 定妆 / 母版 | refs（asset_refs.json） | candidates | provenance |
|---|---|---|---|---|
| lin_wan | lin_wan.png（项目方提供，10-29）；plates/master.png（CM_s1，10-30 项目方定） | ar-c2351c9dcf（母版脸裁切，10-31 03:41）、ar-f9519334bc（设定图 A-s202，by=owner，10-31 19:37） | 无 candidates 目录；expressions 7、items 109、looks 7、plates 27、refs 18 个文件 | lin_wan.provenance.json、plates/master.provenance.json、master_v2_CL_s0_superseded.provenance.json |
| gu_chen | 无根目录定妆图 | ar-98f7c63570（夜间候选，已作废）、ar-b4e17a82d0（设定图 T-s101，by=owner） | 含 _young 变体等，共 28 png / 5 json | candidates/manifest.json |
| chen_yu | 无根目录定妆图 | ar-9650becaf0（已作废）、ar-bc97a45f2a（T-s202 脸） | 12 png / 4 json | candidates/manifest.json |
| ⤴ alex / ryan / kai / leo（旧 60 集，已撤） | 无 | 无 | 各 2 张 + manifest.json | 仅 candidates manifest；无角色锁（OWR Q4） |

### B2 data/assets/identity_refs/manifest.json（by=owner，10-31，CONSIST 登记）
- 原话："林晚A-s202 顾沉s101 陈宇s202脸"
- 文件：lin_wan_face_ref2va.png（源 data/ab/char_sheets/lin_wan/lin_wan_sheet_A_s202.png）、gu_chen_face_ref2va.png（源 gu_chen_sheet_T_s101.png）、chen_yu_face_ref2va.png（源 chen_yu_sheet_T_s202.png）
- ArcFace（w600k_r50，规则 ≥0.50 同人）：林晚 vs_sheet 0.883 / vs 定妆 lin_wan.png 0.901；顾沉 vs_sheet 0.822 / vs 陈宇设定图 0.369；陈宇 vs_sheet 0.843 / vs 顾沉设定图 0.386
- 用途：Ref2VA 的 <Picture N> 用 *_face_ref2va.png；出图多参考用设定图

### B3 data/ab/char_sheets/ 候选
- lin_wan：sheet_A_s101、A_s202（已选）、B_s101、B_s202
- gu_chen：sheet_T_s101（已选）、T_s202
- chen_yu：sheet_T_s101、T_s202（已选，只用脸）
- outfit/：lin_wan_ep02_L1office ×2（img1facecrop / img1sheetA202，s301）
- frames/：S1/S2/S8/S9 的 E（编辑定稿）vs R（从设定图重出）对照 + contact_locked_E_R.jpg
- 挑选页：data/review_pages/char_sheets_pick/index.html；运行记录 runs.jsonl、frame_jobs.json、outfit_jobs*.json
- 陈宇造型补全（W7）：data/staging_v3/为他而骚_ep02_陈宇造型补全_W7_20261031.md，待导入

### B4 身份 LoRA（config/auto_lora_triggers.json）
- 只登记林晚 1 条：trigger lnwan_qi，image，lin_wan_qi_v1.safetensors，强度 0.8
- 其它：lin_wan_h3_v1（视频身份 LoRA）仍是 training，video_identity_enabled=false（LEARNED_SPECS L73）；models.lock 的 lnwan01 标 training（CL L255）；顾沉 / 陈宇无身份 LoRA

### B5 config/voices.json（Kokoro multi-lang v1.1，Apache-2.0）
| 角色 | voice / sid | speed | f0 |
|---|---|---|---|
| 林晚 lin_wan | zf_067 / 36 | 1.0（vo 1.0） | 262 |
| 顾沉 gu_chen | zm_029 / 68 | 1.0 | 107 |
| 陈宇 chen_yu | zm_050 / 77 | 1.03 | 152 |
| 穿孔师 | zf_036 / 22 | 1.0 | 214 |
| 纹身师 | zm_058 / 84 | 0.97 | 127 |
| 同事 | zf_007 / 9 | 1.05 | 205 |
| 男同事 | zm_089 / 96 | 1.05 | 142 |
| 店员 | zf_076 / 43 | 1.05 | 312 |
| ⤴ Alex / Ryan / Kai / Leo（旧 60 集，已撤） | zm_012/61、zm_037/74、zm_095/98、zm_055/81 | 1.03 / 1.0 / 0.98 / 0.95 | 135 / 124 / 161 / 121 |
- 注：对白默认来源已改 h3（RQ post.dialogue_source），TTS 主要用于独白 / 旁白；旁白候选 C1f（zf_072, 1.05）等见 narrator_voice_candidates.json，未切换。
- 剧本人物表 VOICE（script_v2.json globals.character_registry）：林晚 "a mid-high sweet breathy voice, natural pace"；顾沉 "a low restrained voice, natural pace"；陈宇 "a warm bright voice, natural pace"。

### B6 场景库
- data/import/script_v2.json globals.scene_library（3 条，均 defined_in [2]，时段均"深夜"）：sk_office_night（深夜写字楼办公区角落）、sk_taxi_backseat（出租车后座）、sk_rental_entry（出租屋玄关与厨房）
- assets/scenes/ 7 个目录（data/assets/asset_versions.json 各 2 版 main/reverse）：sk_office、sk_taxi、sk_rental_entry、sk_rental_closet = "作废候选"；sk_office_elevator、sk_guchen_dining、sk_gu_chen_closet = "候选·待复审"。注意 id 不一致（sk_office vs sk_office_night，sk_taxi vs sk_taxi_backseat）。
- ep02 场景底图定稿缺 11 镜（CL L376）

---

## C. UI 现状与入口

### C1 打开方式
- 前端开发服务：http://127.0.0.1:5173；后端 API :8800（docs/USER_GUIDE_v1.md L4）
- :8800 同时托管打包好的前端（apps/web/dist 存在时，`/{path}` 回 index.html；`/files` = data/ 静态目录；`/api/docs/{name}`）——services/api/ns_api/app.py L1721–1732
- 依赖隧道：15180 渲染桥、18099 信箱、18188 / 18191 gpu3 ComfyUI（USER_GUIDE L5）
- 监控看板：http://127.0.0.1:8810（tools/monitor/server.py）——MEM ns-final-studio-monitor-dashboard.md
- 开机自启：ops\autostart\register_owner.ps1（项目方运行一次）

### C2 hash 路由页面（apps/web/src/App.tsx、v3/TopBarV3.tsx）
| 路由 | 组件 | 内容 |
|---|---|---|
| `#/script-create` | v3/pages/ScriptFlowPage | ① 新建剧本：提纲 → P1–P4 自动写 → 送导入；`?tab=import` 剧本导入；`?tab=chat` 单集对话写作 |
| `#/assets` | v3/assets/AssetCenter（角色详情复用 v3/pages/AssetsPage） | 资产中心：角色·形象·衣橱·道具·场景·风格·音色·提示词模板；`?type=character` 人物 |
| `#/models` | v3/pages/ModelsPage | 模型与 API |
| `#/cut` | v3/pages/CutPage | ⑤ 成片：版本、播放、对比、合成 |
| `#/projects`、`#/projects/new`、`#/inbox` | projects/* | 项目·新建剧·待办·进度看板 |
| `#/script-chat` | chat/* | 旧剧本对话框（只翻旧会话） |
| `#ep01` 等 / 默认 | v3/Canvas（ReviewRow、edit/*） | 画布：审片模式（一镜一行）/ 精修模式（L/Enter/双击） |
- store View（无 hash 的视图）：overview（全部集总览）、episode、nodes（节点画布）、assets（旧）、import、people、ab（剧本 A/B）；另有 table、storyboard、play（串播）、jobs、materials（本集资料清单）、classic（旧版镜头行）。
- 顶栏步骤条：S1 剧本→materials；S2 资产→#/assets；S3 出图→canvas；S4 视频→canvas-video；S5 成片→#/cut（TopBarV3.tsx L79–85）

### C3 规范文档（标题级结论）
- docs/canvas-ui-spec.md（v1，10-30）：平台调研 / 旧 UI 保留做法 / 画布规范
- docs/canvas-ui-spec-v2.md（10-30）§0：没有平台同时并排放首尾帧，要自己设计；小云雀分镜显示出场角色妆造与场景图；图和视频分两步出
- docs/canvas-ui-spec-v3-merge.md（10-30）：保留旧设计信息 + 采用小云雀式组织；两种模式一键切换；"待你决定"条；资产页角色卡；本镜参考设定；精修循环；剧本创作页 + 统一模型配置
- docs/canvas-ui-fixes-v3.1.md（10-31）：审片 / 精修 / 资产 / 顶栏 / 逻辑 细节修正
- 另有 docs/ux_audit_round1–3.md、ux_round4.md、ux_round5/、ux_round6/、uirsi/、ui-audit/

### C4 审片页 data/review_pages/（本地 HTML）
| 目录 | 标题 | 内容 |
|---|---|---|
| brand_logo | momoso 标识 · 三选一 | 2 张顶栏截图 |
| char_sheets_pick | ep02 角色设定图挑选 | 8 张设定图 + E/R 对照 |
| ep01 | ep01 审片 | index.html |
| ep02 | ep02 审片 | index.html |
| ep02_planC | ep02 方案 C 审片 | index.html |
| ep02_v1 | ep02 第 1 版审片 | ep02_v1.mp4、old_vs_new.mp4、overview.jpg |
| latest | momoso 最新版本总览 | index.html |
| narrator_pick | 旁白音色挑选 | 34 个文件（C1–C3 等 mp3/wav） |
| uiux | UI/UX 第5–6轮进展 | index.html |
- 成片文件：data/episodes/ep02_v1.mp4（10-31 17:39）、ep02_v2a.mp4（18:07）及两个"未完成/勿用"预览

---

## D. "最新 10 集"剧本清单（只列文件，不读剧情）

### D1 生产剧本库 data/import/script_v2.json（60 集；最近一次合并 10-31 20:08）
sources：
| 源文件 | version | 当前提供的集 |
|---|---|---|
| script play lib\为他而骚 （剧本和镜头）v2.md | v2 | 3–60 |
| 为他而骚短剧\Qwen剧本\为他而骚_ep01_qwen_rules_v2_20261030.md | v3 | 1 |
| 为他而骚短剧\Qwen剧本\为他而骚_ep02_qwen_rules_v2_20261030.md | v3 | （无，已被替换） |
| data\staging_v3\为他而骚_ep02_补全候选_PREP_20261031 v3.md | v3 | （无，已被替换） |
| data\staging_v3\为他而骚_ep02_补全候选_PROMPTv2_20261031.md | null（文件内 sysimpl-v2） | 2 |
| script play lib\为他而骚（image提示词） v2.md | null | — |

库内 ep01–ep10：
| 集 | 镜数 | H3 字段 | 来源 |
|---|---|---|---|
| ep01 | 7 | 7/7 | Qwen rules_v2 20261030 |
| ep02 | 11 | 11/11 | PROMPTv2 20261031（warnings：11 镜、82 秒超 50–75） |
| ep03–ep10 | 各 6 | 0 | script play lib v2.md |

### D2 链条产物 data/pipeline/runs/series10_v1/（CHAINSPEC，《漆皮之下·十日》，10 集，最新）
- P0_brief.json：source = "写作模型压缩 data/import/script_v2.json 60 集 synopsis"，episodes 1–10，seconds_per_episode [50,75]
- P1_storyline.json（10 集）；每集 P2 大纲、P3 剧本 JSON（全部 ok）、P4 分镜 Markdown
- 规则版本：全部 P4 头部 `rules_version: rules_v2+sysimpl-v3`
- 写作花费累计 $1.7979（drive_log.jsonl 最后一行）

| 集 | P4 文件 | 镜数 | H3提示词 | P4 状态（3 轮后） | 剩余 blocking |
|---|---|---|---|---|---|
| ep01 | ep01/P4_ep01.md | 8 | 8 | needs_writer | 2 |
| ep02 | ep02/P4_ep02.md | 9 | 9 | needs_writer | 7 |
| ep03 | ep03/P4_ep03.md | 6 | 6 | needs_writer | 13 |
| ep04 | ep04/P4_ep04.md | 8 | 8 | needs_writer | 6 |
| ep05 | ep05/P4_ep05.md | 6 | 6 | needs_writer | 6 |
| ep06 | ep06/P4_ep06.md | 13 | 13 | needs_writer | 3 |
| ep07 | ep07/P4_ep07.md | 6 | 6 | needs_writer | 2 |
| ep08 | ep08/P4_ep08.md | 8 | 8 | needs_writer | 2 |
| ep09 | ep09/P4_ep09.md | 7 | 7 | needs_writer | 3 |
| ep10 | ep10/P4_ep10.md | 8 | 8 | needs_writer | 12 |
- 卡住的规则号：P4-GATE、P4-SPEC、LK34-01、LK34-03（drive_log.jsonl）。未导入 script_v2.json。

### D3 其它全本 / 单集稿
| 文件 | 集 | ep01–10 镜数 | H3提示词 | 时间 |
|---|---|---|---|---|
| data/staging_v3/为他而骚 （剧本和镜头）v3.1.md | 1–60 | 6,6,6,6,6,6,7,6,6,6 | ep08 5/6，其余齐 | 10-30 20:34（未在 script_v2 sources 中） |
| data/staging_v3/为他而骚 （剧本和镜头）v3.md | 1–60 | 6,6,6,6,6,6,7,6,6,6 | ep01/07/08/09 不齐 | 10-30 13:54 |
| data/staging_v3/archive/为他而骚 v3.1（Qwen逐镜格式返修 ep01-14…）.md | 1–60 | — | 303 处 | 10-30 16:19 |
| 为他而骚短剧/Qwen剧本/为他而骚_全本_qwen_rules_v2_20261030.md | 1–5 | 7,11,7,6,6 | 齐 | 10-30 21:40 |
| 为他而骚短剧/Qwen剧本/*_qwen_rules_v1_20261031.md（ep01、ep02、全本） | — | 6 | — | 10-31 20:39，内容为"# 占位剧本"（测试产物） |
| data/staging_v3/repair/_work.md | 53 | — | — | 10-30 20:34 |
- 规则版本：以上文件内 grep 不到 rules_version / sysimpl 字样（PROMPTv2 稿按 CL L383 是 sysimpl-v2 产出）。

### D4 剧本对话框草稿 data/script_chat/（7 个会话，最晚 10-31 02:49）
| 会话 | 集 | 镜 | H3 | rules | 校验 blocking/warn |
|---|---|---|---|---|---|
| 20261030-231830-8a262b | ep03 | 7 | 7 | rules_v2 | 1/5（inbox 0） |
| 20261031-010935-86d929 | ep04 | 8 | 8 | — | 0/1 |
| 20261031-021820-fb6a6d | ep05 | 8 | 8 | — | 0/4 |
| 20261031-021820-feaa45 | ep04 | 8 | 8 | — | 0/2 |
| 20261031-021828-d01334 | ep03 | 8 | 8 | — | 0/6 |
| 20261031-024934-44e771 | ep05 | 8 | 8 | — | 0/6 |
| 20261031-024934-95bbaf | ep04 | 7 | 7 | — | 0/2 |
- 均已送 inbox（session.json inbox），未见导入记录。

### D5 docs 里的 SERIES 产出
- 没有专门的 series10 文档；docs/PIPELINE_CHAIN.md §试跑（L170–）用的是 v3.1 ep01–03 剧情行，只跑 ep02 到 P4。

---

## 不确定 / 没找到（总调度 10-31 已答复第 1、2、3、5 条，见 CORE.md ⑤ ⑧；第 7 条已建对照表 config/scene_aliases.json）
1. auto_final_on_lock：CL L108 记项目方"打开"改 true，但 RQ 现值 false（L434），note 写"暂时关闭"，没找到改回的记录。
2. 写作方 10-30 的先后：OWR 写 07:35"还是用qwen写"，REQ G8 写先 abliteration 后改回；10-31 实际用 abliteration API。没有一条 10-31 的原话说"改用 abliteration"，只有 MEM session-ownership 和 USER_GUIDE。
3. momoso 标识选候选 2、abliteration 充值 50 美金：只在代码注释 / 记忆里，没找到原话。
4. 为他而骚短剧/fong的想法 owner_quotes.md（553 行原话汇编）没有逐条摘，A 节只用了 OWR 已引的部分；MORNING_DECISIONS.md 的已决项没有逐条核对。
5. "最新 10 集"有两套：生产库 script_v2.json（为他而骚 ep01–10，ep03–10 是 v2 无 H3）和 series10_v1（新标题《漆皮之下·十日》，全部 needs_writer，未导入）。按哪套算"最新"要由调用方定。
6. series10_v1 是写作时正在跑的产物（21:00 前后），数字可能还会变。
7. 场景 id 两套命名（scene_library 和 assets/scenes）对不上，没查到映射表。
