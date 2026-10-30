# NS-Final Studio v1 收尾 TODO（项目方 2026-10-30 夜，fredw-92 汇总）

项目方原话要点：“优先把正常的流程做完，关于‘成人’的内容自动跳过，我们暂时不看”；“唯一的调度资源是远程 GPU3 里面的 3090：ComfyUI 的 image2.1（图片），MiniMax H3（视频）”；“所有的推动语言模型，使用的是…flex 模型的 API”；“把这个项目 close 掉”。

## 0. 定死的约定（所有 agent 遵守）
- 不做内容检测、不做成人检测 / 拦截（暂时）；不写、不改、不评剧本和提示词内容（内容来自写作模型或项目方，原样传）。
- 语言模型 = abliteration `abliterated-model-large-flash`（OpenAI 兼容，`https://api.abliteration.ai/v1`，密钥：环境变量 `ABLITERATION_API_KEY` 或 `config/abliteration.local.json`）。千问写作模型撤下，不再作为默认。
- 出图 = gpu3 GPU0 的 ComfyUI（笔记本隧道 `127.0.0.1:18188` → gpu3 `8188`），Image 2.1 Turbo（`qwen_image_2.1_turbo_int8_convrot` + `qwen3vl_8b_int8_convrot` + `qwen_image_2.1_vae_bf16`），林晚 LoRA `lin_wan_qi_v1.safetensors`。
- 视频 = gpu3 GPU3 的 ComfyUI（隧道 `127.0.0.1:18191` → `8191`），MiniMax H3 FL2VA。
- 两条已实测：笔记本 → 18191 → Image 2.1 Turbo + LoRA，768×1344 一张 28 s（scratchpad chain_test.py）。
- 不提交 git；每个改动记 docs/CHANGELOG_AGENTS.md；改共享文件前先重读；测试全过（`.venv\Scripts\python.exe -m pytest -q -p no:cacheprovider`，前端 `npx tsc --noEmit -p .`）。
- 规格：docs/canvas-ui-spec-v3-merge.md（UI 全部要求，第 1–9 节）；调研 docs/canvas_research_v3.md；可点原型 apps/prototype-v3/。

## 1. 写作链路（剧本 → 镜头脚本 → H3 提示词）
- [x] 已有：#/script-chat 大纲 → 写作模型按 config/script_chat_rules.md（rules_v2）+ 格式契约写剧本与分镜（含 **H3提示词** 四块）→ 草稿 → tools/validate_qwen_script.py 校验 → 返修 → 画布导入。
- [ ] W1：默认写作模型改为 large-flash；统一模型配置 config/llm_providers.json（+ .local.json 密钥）与“模型与 API”接口（规格 8.2）；script_chat / qwen_repair_loop / 导演加强都读它；去掉千问默认。
- [ ] W1：剧本创作页后端支持规格 8.1（提纲、集数范围、每集镜头 / 时长目标、规则版本、模型参数、同一提纲两模型 → A/B）。
- [ ] W1：用 large-flash 实测写 1 集（项目方提供的现有提纲或现有剧本大纲），走完校验 → 导入候选（不自动导入）。

## 2. 出图链路（首尾帧 + 改到满意）
- [ ] W2：画布出图改走 gpu3 ComfyUI（NS_COMFY_URL 指 18188；可按任务选卡）；放开 weita 项目 owner=gpu3 对画布出图的拒绝（画布交互改图就是主链路）；关掉成人拦截与看图评分（只出图，不打分、不否决）。
- [ ] W2：首帧编译带上 lnwan_qi（LORA_REGISTRY accepted → image_loras）；尾帧由定稿首帧编辑（C3）。
- [ ] W2：图片精修循环后端（规格第 7 节）：改提示词重出 / 指令改图（qwen_edit init_image + denoise 小中大）/ 换参考再改（多参考）；版本挂父版本形成修改链；定稿首帧 → 尾帧 → 定稿；回退；改定稿首帧使尾帧 / 视频过期。
- [ ] W5：本镜参考切换（规格第 6 节）：ShotEdit.ref_overrides、场景层覆盖、三层继承、影响面预览接口；编译器并入参考与 look_fragments。
- [ ] W5：人物资产 image2img（规格 7.3）：资产多参考图（上传、设为参考、复制）+ 用途标签（人物 / 风格 / 色彩 / 单件）；资产生成接口（底图 + 参考组 + 提示词 + 幅度 → Image 2.1）；资产版本。

## 3. 视频链路（H3 → 审 → 改参数 / 提示词 → 重渲）
- [ ] W3：画布出视频改走 gpu3 GPU3 ComfyUI（18191），H3 FL2VA，首尾帧 = 定稿帧，提示词 = 剧本 H3 四块（项目方覆盖优先），帧数按 17k+5 格；核对 gpu3 上 H3 模型 / VAE / 文本编码器文件名。
- [ ] W3：视频改参数重渲：种子、步数、帧数（时长）、LoRA 强度、提示词覆盖；视频版本链与对比；成人镜不拦。
- [ ] W3：实测 ep02 一镜（非红标）首帧 → 尾帧 → 视频全链路，记耗时。

## 4. 画布 UI（规格 docs/canvas-ui-spec-v3-merge.md 全部）
- [ ] W4a 外壳与审片：步骤条 + 工具菜单；审片模式一镜一行（旧字段全保留、定宽、状态点 + 一句下一步、提示词折叠、主按钮 = 下一步）；底部片段条；“为什么卡住”小窗；集头“待你决定”；状态词表。
- [ ] W4b 精修：三区；右栏标签（提示词 / 版本 / 规则 / 高级）；图片精修循环 UI（四种改法、修改链、对比、回退、定稿）；视频审片与改参数重渲；本镜参考条与切换面板；资产编辑器（参考图组 + 用途 + image2img）。
- [ ] W4c 页面：剧本创作页（提纲 + 模型设置 + 流式写作 + 校验 + 送导入 + A/B）；模型与 API 配置页 + 每处 ⚙ 覆盖；资产页角色卡。
- [ ] 深浅色、1600×900 与 1280×800 截图自查。

## 5. 运维 / 收尾
- [ ] 隧道：18188 / 18191 加进 ops/autostart/tunnel.sh 与 laptop_autostart.ps1 的端口检查；NS_COMFY_URL 写进 API 启动参数。
- [ ] gpu3 上千问写作模型（GPU1 :8098、qwen-agent）下线：需项目方确认后执行（会中断其信箱任务）。
- [ ] 全量测试、tsc、vite build；CHANGELOG；最终多 agent 复核（完整性 + 回归）；交付说明（怎么用、已知缺口）。

## 6. 场景：剧本描写 + 场景资产（项目方 2026-10-31）
项目方原话：“画布里面是有场景的，这意味着剧本在描写人物细节之外，还需要对场景进行描述……每个镜头除了人物和相关细节外，还需要场景的描述。所以，场景描述的图片也需要模型生成出来，而且场景必须保持一致性。因此，整个系统里面也要对场景进行资产管理。”
- [ ] S1 写作格式（系统规则，不写内容）：格式契约与写作规则要求写作模型输出①全剧 / 每集的**场景表**（场景 id、名称、空间描述、时段、光线、固定陈设）②每个镜头标明**所属场景 id** + 本镜的场景细节（机位看到的部分、道具状态）。校验器检查：每镜有场景 id、场景 id 在场景表里、同 id 跨集描述不冲突（只查结构与一致性，不评内容）。导入器解析进 script_v2.json（globals.scene_library、Shot.scene_id、Shot.scene_detail），与现有 scenes.json / state_timeline 的场景分组对齐。
- [ ] S2 场景资产库（跨集共用，保证一致）：每个场景 = 描述 + 参考图（上传 / 从镜头版本设为参考，标用途：空间 / 风格 / 色彩 / 道具）+ 生成的底图（Image 2.1 文生图或 image2img，多机位 / 多时段变体）+ 版本链 + 定稿底图；“用到的镜头”反查。复用人物资产那套接口与编辑器（asset_edit / AssetDrawer），类型 = scene。
- [ ] S3 出图接入：首帧任务自动带上本镜场景的定稿底图作参考（与人物参考一起排进 Image 2.1 编辑的 图1、图2…，用途写明“只取场景空间与陈设，不取人物”），编译器把场景描述并入首帧提示词；场景底图改版本 → 用到它的镜头标过期。本镜参考切换里可换场景变体（已有）。
- [ ] S4 界面：资产页加“场景”页签（场景卡：底图大图、出现集数 / 镜数、变体、定稿状态）；剧本创作页显示模型写出的场景表；审片行与精修参考条显示场景小卡（有底图显示底图）。
