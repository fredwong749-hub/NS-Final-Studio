# MASTER PICTURE：项目方决策全图 · 残留清单 · 系统图 · 缺口表

> RECALL 2026-11-01 02:30 写，交总调度 fredw-92。起因（项目方原话，11-01 00:28）：“你现在东修一下、西修一下是不行的啊！你需要有一个 master full picture 来修整个 system……你真的是需要把 memory 对齐，把整个 system 刷下来，一下一下、一点点来 debug。”
>
> **来源**
> - 对话原话：`docs/master/owner_messages_extracted.md`，由 `tools/qa/extract_owner_messages.py` 生成。主会话 760a7f62 有 223 条，另有 12 个旧会话；密钥已脱敏。
> - 记忆：`~/.claude/projects/C--Users-fredw/memory/*.md`，只读。
> - 决策文件：`series10_v1/owner_decisions.json`、`decisions.json`、`docs/overnight/morning_decisions.md`。
> - 一键确认：`data/audit/2026103{1}.jsonl`、`20261101.jsonl`，其中 role=owner 的 29 条。
>
> **机检**：`config/owner_decisions.yaml` 共 39 条断言，跑法 `.venv/Scripts/python.exe -X utf8 tools/qa/decision_check.py`。规则见 K-OPS-D01（`knowledge/rules/ops_decisions.yaml`）。
>
> **“实测”的意思**：本表“实测状态”一栏都是 11-01 01:40–02:30 读文件或调 :8800 得到的结果。写“未核实”的条目没有实测，不要当成通过。

## 0. 总数

| 统计 | 数 |
|---|---|
| 账本决策 | **79** 条 |
| ✅ 在位 | 46 |
| ❌ 不在位 | 4 |
| ⚠ 部分在位 / 未核实 / 待确认 | 18 |
| ⤴ 已被后续决定取代（不再要求） | 11 |
| decision_check（11-01 19:35，VOICE10 复跑） | 58 条：✅ 57，❌ 0，⏳ 1（tools/qa/decision_check.py；D-VOC-01…08 全 ✅） |

## 1. 项目方决策账本

**范围缩写**：剧本、人物/造型、资产、出图、视频、声音、UI、流程/规则、清理。

**状态**：✅ 在位，❌ 不在位，⚠ 部分在位 / 未核实，⤴ 已被取代。“原话”一栏只摘关键句，全文见 extracted.md 里对应时间戳。

| id | 时间（UTC） | 原话（摘） | 决定 | 范围 | 被取代 | 期望状态 | 实测状态 | 状态 |
|---|---|---|---|---|---|---|---|---|
| L-001 | 10-29 15:34 | “我说的真人不是真人的意思，是画面效果接近真人效果，去掉ai那种塑料味” | 真人 = 画面写实，角色全部合成 | 流程/规则 | — | 写实只作用于质感 | memory `realism-meaning` 和 `linwan-look` 已写；GEN_CONTRACT Q4 质感项在 | ✅ |
| L-002 | 10-29 16:01 | “不要字幕……颜色丰富艳丽……镜头采取大光圈” | 无字幕、艳丽、大光圈后缀 | 出图 | L-018（S★）；契约 I7 禁“浓郁饱和 / 色彩丰富艳丽 / 柔焦 / 奶油” | — | gen_contract.json `suffix_banned` 含这些词 | ⤴ |
| L-003 | 10-29 20:30 | 选“一镜一行 (Recommended)” | 分镜页一镜一行，首尾帧大图 | UI | — | 每镜一行，含首帧、尾帧、视频、剧本、对白、资产、提示词 | 11-01 项目方说“剧本的页面你改坏了”，UIRSI 在恢复（LOCKS.md）；本轮未截图 | ⚠ 未核实 |
| L-004 | 10-29 19:22 | “人物资产tab……参考图,服装,高跟鞋,美甲,发型,造型abc” | 要有资产管理 tab | UI/资产 | — | 每人有造型、设定图、单品 | /api/character-hub：林晚 looks 3 / sheets 3 / items 14；顾沉、陈宇、阿岚有 looks/sheets | ✅ |
| L-005 | 10-29 20:13 | 眼睛“按情节切换”；发色“雾霾天蓝” | 林晚发色锁雾霾天蓝；眼色按情节切换 | 人物 | — | 锁定外貌含 misty sky-blue | script_v2 character_registry 里有 “misty sky-blue”（D-SCR-04 ✅） | ✅ |
| L-006 | 10-29 16:56 / 20:03 / 20:04 | “12厘米透明高跟鞋外，也可以偶尔换个12厘米的漆皮侧开”；“跟一根筷子粗那么细”；“漆皮……抹上油那种” | 鞋与漆皮规格 | 人物/剧本 | — | 规格进系统自动补 | globals.lora_triggers 里 hh12clear / hh12patent / ptx* 的描述含这些规格（内容由写作方写，Claude 不评） | ✅ |
| L-007 | 10-29 16:56 / 16:58 | “5毫米……一个5毫米的球”；“左右都是4个环,阴蒂中间有一个环” | 饰品规格更正 | 人物/剧本 | — | 规格进系统 | lora_triggers lbrng9 / lbrng9_beads 描述与此一致 | ✅ |
| L-008 | 10-30 | 选 CM_s1（中度写实）做母版 | 林晚身份母版 = CM_s1 | 人物 | 部分被 L-026 取代（身份参考 = 设定图 A-s202 的 face_ref2va） | 出图身份参考 = 项目方挑定的那组 | identity_refs/manifest.json：林晚 = A-s202，对定妆 0.901；/api/assets/characters 的 face_url 仍指 `plates/id_front_s0.png`，与 hub 的 face_ref2va 不一致 | ⚠ |
| L-009 | 10-30 04:39 / 06:30 | “claude不做任何内容参与,也不评价内容” | Claude 只写系统 | 流程/规则 | — | 写作和挑选不由 Claude 做 | memory 硬规则在；本轮未改任何剧本文字 | ✅ |
| L-010 | 10-30 14:02 / 16:14 | “把千问给撤下”；“停千问” | 写作 LLM 改走外部 API | 流程 | — | 无本地 Qwen 写作 | config/llm_providers.json：默认 abliteration large-flash，并注明“千问写作模型撤下” | ✅ |
| L-011 | 10-30 14:03 | “走一个没有成人检测的方向，先把基础流程跑完” | 跳过成人检测 | 流程 | 取代 10-30 13:31“允许，但必须你本人点” | 不因成人判定卡流程 | adult_overrides `per_shot=false`，本轮删了 60 集 force_adult；未逐条验证渲染入口 | ⚠ 未核实 |
| L-012 | 10-30 14:00 | “按一个按钮，立马把当时的 reference 图片和一些提示词调度到 Image 2.1” | 画布一键重出 / 改图循环 | UI/出图 | — | frame-jobs 接口 | POST /api/shots/{id}/frame-jobs 在用（audit 01:46 项目方点过） | ✅ |
| L-013 | 10-30 13:59 | “提纲输入……模型设置……每一个地方都有这样一个 API 的 configuration” | 剧本创作页 + 模型/API 页 | UI | — | #/script-create、#/models | 两个路由都在；/api/story-runs 返回 200 | ✅ |
| L-014 | 10-30 15:50 | “场景必须保持一致性……对场景进行资产管理” | 场景资产管理 | 资产 | — | series10 6 个场景有底图 | /api/assets/scenes 只剩 6 个 series10 场景；项目方 00:56–00:58 一键挑了 6 个底图（audit plate-pick） | ✅ |
| L-015 | 10-30 17:17 | “R3 把 85 条生产规则接进系统……再用新规则重写” | 用新规则重写 ep03–60 | 剧本 | L-031（改做 10 集新剧） | — | — | ⤴ |
| L-016 | 10-30 17:53 | “长镜头长度模型决定,不限定时长” | 不截短 | 视频 | — | 有长镜头道 | render_endpoints：gpu36:2 长镜头道 max_frames 362，超长镜头改派、不截 | ✅ |
| L-017 | 10-30 17:56 | 自动出“定稿版”：“打开” | 锁首帧后自动出定稿档 | 出图 | 总调度裁定 11-01：被 frame_v9 取代（单遍 1.5× 出图 + lanczos + USM 已是锐化定稿，图片不再分定稿档）；视频以后若有定稿档另立新决定 | auto_final_on_lock 保持 false | render_quality.json `auto_final_on_lock: false`；注释原写“待徕卡锐利方案定稿后改定稿档再开”（D-IMG-06 ✅） | ⤴ |
| L-018 | 10-31 03:11 / 03:13 | “leica_sharp效果最好,用他”；选“S★ 全套组合” | 默认出图预设 S★ | 出图 | — | default_preset = leica_sstar | 实测 leica_sstar（D-IMG-01） | ✅ |
| L-019 | 10-30 17:56 | “加,不商用,纯粹自己研究技术” | 加 VBVR LoRA | 视频 | — | 可选视频 LoRA | optional_video_loras 含 H3-Licon-VBVR-I2V；gpu33 文件在（保留） | ✅ |
| L-020 | 10-30 17:57 | “去掉 gpu33 视频卡的 --cache-none……同意” | 去 --cache-none | 视频 | — | gpu33 ComfyUI 不带 --cache-none | gpu33 三个进程的参数里没有 --cache-none，带 --cache-ram 64 96 | ✅ |
| L-021 | 10-30 17:46 | “gpu36加入rendering gpu阵列” | gpu36 进渲染阵列 | 流程 | — | lanes 含 gpu36 | render_endpoints lanes 有 gpu36:0/1/2 | ✅ |
| L-022 | 10-31 03:11 | 选“交给写作模型按 v3 补” | 顾沉、陈宇的族裔由写作方补 | 人物 | — | 男主写“东亚” | registry：顾沉 / 陈宇 en 都含 “East Asian man” | ✅ |
| L-023 | 10-31 03:11 | 选“全部作废，按新描述重出” | 夜里定妆候选全部作废 | 资产 | L-026 | — | — | ⤴ |
| L-024 | 10-31 08:20 | 配乐选“整集统一 BGM (Recommended)” | 整集统一 BGM | 声音 | 适用于 series10（同一原则） | series10 每集有整集 BGM | 02:40 起 data/music/series10/ 出现 ep01.wav（他人写入）；旧剧 ep01/ep02.wav 已隔离（D-BGM-01 ✅，只查 ep01） | ⚠ |
| L-025 | 10-31 03:33 | 选“换种子 + 写作模型改声音描述 + 变声模型” | 顾沉的声音不要生硬 | 声音 | 被 L-057 取代（4 位角色重做候选） | — | 顾沉 voice_phrase 已改 “natural pace” | ⤴ |
| L-026 | 10-31 10:34 | “林晚A-s202 顾沉s101 陈宇s202脸” | 角色设定图 / 身份参考 | 人物/资产 | — | identity_refs 按这组登记 | manifest.json owner_quote 完全一致（D-IMG-04 ✅） | ✅ |
| L-027 | 10-31 10:34 | “改成正常节奏 (Recommended)” | 去掉写作规则里 6 处“偏慢” | 剧本/声音 | — | 规则里无“偏慢”，语速 1.0 | 4 份写作规则里“偏慢” = 0（D-VOC-07 ✅）；voices 林晚、顾沉 speed 1.0 | ✅ |
| L-028 | 10-31 10:34 | “加 (Recommended)”（独白镜加“嘴唇闭合”） | 独白镜加闭唇句 | 视频 | — | H3 编译器有闭唇句 | h3_prompt.py:26 有 “lips remain completely closed”（D-VOC-08 ✅） | ✅ |
| L-029 | 10-31 10:34 | 批准修改 gpu33 配乐脚本 | 配乐按镜长作曲、不插“撤到静默” | 声音 | — | gpu33 脚本已改 | 本轮未上 gpu33 核对 | ⚠ 未核实 |
| L-030 | 10-31 09:12 | “旧的剧本和图片,我觉得你应该清除掉,用最 latest 的图片就可以了” | 清旧剧本和旧图 | 清理 | 由 L-058 细化成“先隔离” | — | 见 L-058 | ⤴ |
| L-031 | 10-31 11:55 | “把我这个 50 集的剧本 summarize 一下，改成一个 10 集的剧本……林晚的人物依然保留” | 新剧 series10_v1，10 集 | 剧本 | — | 正式剧本 10 集 | script_v2.json 10 集；/api/episodes 返回 10（D-SCR-01/03 ✅） | ✅ |
| L-032 | 10-31 11:52 / 12:00 | “改名为momoso Agentic Drama Studio”；“候选 2 · 双环” | 改名并换 logo | UI | — | 标题与 logo | index.html 标题一致；Brand.tsx 是双环 | ✅ |
| L-033 | 10-31 12:28 | “A. 认可（推荐）：接着出阿岚的设定图” | 顾沉、陈宇沿用，新增阿岚 | 人物 | — | 演员表 4 人 | registry = 林晚 / 顾沉 / 陈宇 / 阿岚（D-SCR-02 ✅）；各 API 已同步为 4 人（D-CLN-02/03 ✅） | ✅ |
| L-034 | 10-31 12:04 | “大长腿、漆皮短裙……能写就写啊” | 风格方向转给写作模型 | 剧本 | — | 原话已转写作方 | series10_v1/owner_direction.md 在（Claude 不评内容） | ✅ |
| L-035 | 10-31 12:28 | “A. 不要（推荐）……标志物改用……钻石水晶甲” | 林晚不加痣，标志物 = 钻石水晶甲 | 人物 | — | P1_looks 无“痣” | D-SCR-05 ✅ | ✅ |
| L-036 | 10-31 12:29 | “A. 让写作模型改掉这段剧情” | ep03 不改发色 | 剧本 | — | 发色全程锁定 | HC-07 机检在（owner_decisions.json）；D-SCR-04 ✅ | ✅ |
| L-037 | 10-31 12:06–12:07 | “oag音色”；“QAg（深夜电台·温柔）”；“采取” | 旁白 = QAg | 声音 | — | narrator = narrator_qag | voices.json 实测一致，资产在（D-VOC-01/02/03 ✅） | ✅ |
| L-038 | 10-31 12:06 | “IndexTTS2……删掉（推荐）” | 删 IndexTTS2 权重 | 清理 | — | gpu36 无 5.5G 权重 | gpu36 只剩 src_tts/index-tts 源码 75M，hf 缓存里没有 IndexTeam | ✅ |
| L-039 | 10-31 12:30 | “A. 等格式问题清完、设定图出来后再导入” | 新剧导入时机 | 剧本 | — | replace 导入 | 已导入（script_v2 = 10 集；backups 留了 4 份 60 集） | ✅ |
| L-040 | 10-31 14:11 | “A. 用暂定版” | 阿岚设定图用暂定版 | 人物 | — | 阿岚有身份参考 | identity_refs/ch_a_lan/ch_a_lan_face_ref2va.png 在（D-IMG-05 ✅） | ✅ |
| L-041 | 10-31 12:30 | “网页上依然有很多旧的数据……只留下零网（10 集）的所有东西” | 网页只留 10 集内容 | 清理/UI | — | API 不再返回旧人物、旧场景、旧 BGM | 本轮隔离和改码后 D-CLN-01…08 全 ✅；剩余残留见 §2.3 | ✅（剩余见 §2） |
| L-042 | 10-31 12:30 / 15:52 | “先把这 6 张显卡用上，把 10 集的图片全部生成完毕，然后再做 video rendering” | 先出完全部图片，再出视频 | 流程 | — | 图片阶段完成后进视频 | ASSETMASTER / VIDEO10 在做；本轮未统计完成率 | ⚠ 未核实 |
| L-043 | 10-31 14:31 | “系统是在我 login 的……你要写入账户登录这个逻辑” | 登录即本人，一键确认，自动审计 | UI/流程 | — | auth 中间件 + audit | auth.py 在；audit 里 29 条 role=owner 一键操作 | ✅ |
| L-044 | 10-31 15:31 | 选“作为造型B的另一双鞋” | 黑漆皮凉鞋 = 造型 B 备选鞋 | 人物/资产 | — | 写作方按剧情换鞋 | morning_decisions：只有 ep03–05 部分换了，ep06–10 没换，ep07 换不成 | ⚠ |
| L-045 | 10-31 15:31 | 选“以单品图为准（带肩带开窗）” | 束腰以单品图为准 | 资产 | — | 造型 B 设定图按单品重出 | 本轮未核对设定图 | ⚠ 未核实 |
| L-046 | 10-31 14:35 | 林晚出图 LoRA（0.6）：“A. 去掉（推荐）” | 撤 lin_wan_qi | 出图 | — | 任何配置、剧本、自动补都不再挂 lin_wan_qi | 改前 auto_lora_triggers、render_quality.identity_loras、剧本 77 处 img_triggers 都还有。RECALL 11-01 已全部移除，文件已隔离，契约禁用表保留（D-LORA-01…04 ✅） | ✅（11-01 修） |
| L-047 | 10-31 14:39 / 14:40 | “同意了 你去下载”；9B 完整版选 “b” | 下载 FLUX.2 Klein 9B、FLUX.3 Klein，并测 9B base | 出图 | — | gpu36 有 9B 与 FLUX.3 | gpu36 diffusion_models 只有 flux-2-klein-4b / base-4b，没有 9B 和 FLUX.3 | ⚠ |
| L-048 | 10-31 14:35 | “安装 Krea2 换脸修图插件？……装（推荐）” | 装 Krea2 插件 | 出图 | — | 节点 + LoRA 在 | gpu36 有 comfyui-krea2edit 和 krea2_identity / general_edit_v2 | ✅ |
| L-049 | 10-31 14:11 | “A. 先不训（推荐）” | 不给顾沉、陈宇训出图 LoRA | 人物 | — | 没有男主 LoRA | 两台都没有 | ✅ |
| L-050 | 11-01 | “v10H 同上（写实·重）” | 写实·重 | 出图 | L-051（较新） | — | render_quality 注释记了两句原话，以较新为准 | ⤴ |
| L-051 | 11-01 | “v9 v10+场景底图这个还可以” | 全量重出用 frame_v9 + 场景底图 | 出图 | — | frame_redo_preset = frame_v9 | 实测 frame_v9（D-IMG-02 ✅） | ✅ |
| L-052 | 10-31 15:50 | “A. 不是 / 只是点着试试：6 条全部撤销” | 撤销 6 条误点的一键操作 | UI | — | 6 条已撤 | 本轮未查 audit / trash 对应项 | ⚠ 未核实 |
| L-053 | 10-31 15:52 | “你全部默认同意，先全部生成好尾帧……图片的事情我们先做完” | 图片阶段：契约通过即自动采用 | 出图/流程 | — | postflight 通过 → 后端自动设为当前（set_lock） | 只有前端显示；unified_frame.postflight_async 后面没有 set_lock 步骤（VIDEO10 报告，RECALL grep 确认） | ❌ |
| L-054 | 10-31 11:13 / 15:53 / 15:54 | “哪些是需要我做 decision 的 layout 出来”；“不同颜色 highlight”；“出选择题” | 交互规则：待决单列、彩色标记、选择题 | 流程 | — | 写进记忆 | memory 里 decision-layout、color-markers、use-choice-dialog 三条在 | ✅ |
| L-055 | 10-31 16:19 | “我点这个小图标可以放大……把全部类似的地方都改一下” | 小图都能点开放大 | UI | — | 全站小图可放大 | UIMASTER 在做；本轮未验 | ⚠ 未核实 |
| L-056 | 10-31 16:21 | “S1、S2、S3、S4……我发现你都是一模一样” | 前后端数据对齐 | UI | — | 每镜内容等于后端 | DATAALIGN 在做；RECALL 实测 `/api/story-runs/series10_v1?ep=1` 与 `?episode=3` 返回同样 10755 字节（参数名待 DATAALIGN 核） | ❌ |
| L-057 | 11-01 00:27 | 选“重做候选我来挑 (Recommended)” | 4 位角色各出 3–4 个新音色候选，项目方点选 | 声音 | 被 L-078 取代（改为系统按 QAg 方法自动选） | — | 见 L-078 | ⤴ |
| L-058 | 11-01 00:28 + 一键 | “旧的资产、旧的代码、很多旧的 Lora……把这些东西隔离一下”；一键“先隔离，验证后你删” | 旧内容先隔离，验证后由项目方删除 | 清理 | — | 隔离区 + MANIFEST + 删除脚本 | 隔离 76 项 23.0G，MANIFEST 在；验证通过；`ops/cleanup/delete_quarantine_20261101.ps1` 待项目方运行 | ✅（删除待项目方） |
| L-059 | 11-01 01:51（UI 操作） | （项目方本人在界面上删除） | ep02_claude_director_v1 移进回收站 | 清理 | — | 留在回收站、不恢复 | 总调度确认在 data/_trash/2026-11-01/tr-96029798c9；ITERAUDIT 已改指相关规则 | ✅ |
| L-060 | 10-31 08:54 | “Civitai 上有很多 Lora 模型……下载下来，整合到本地系统” | 下载 Civitai LoRA 供学习 | 资产 | — | 文件在 gpu36 | gpu36 有 civitai/（含 adult/ 15 个），总调度定保留 | ✅ |
| L-061 | 10-31 08:51 / 09:06 | 选“两台都装”；“批准在 gpu33 和 gpu36 安装那 4 个已审节点包” | 两台都装节点包 | 视频 | — | 两台都有 4 个节点包 | gpu33 与 gpu36 都有 H3-FaceRefine、H3-Motion-Context、PDD-Acc、VideoHelperSuite | ✅ |
| L-062 | 10-31 08:04 | “Fresh”选 abliteration | Fresh = abliteration | 流程 | — | — | llm_providers 一致 | ✅ |
| L-063 | 10-31 07:36 | “所有的资源都集中在把 Episode 2 跑通” | 全力迭代 ep02 | 流程 | L-031 / L-042（转做 series10） | — | — | ⤴ |
| L-064 | 10-31 08:20 | 选“仍然导入”（ep02 补全稿）和“撤销定稿”（5 个静止视频） | 导入 ep02 补全稿，撤 5 个定稿 | 剧本 | L-031 | — | — | ⤴ |
| L-065 | 10-31 11:08 | 选“仍然导入”（ep02 PROMPTv2） | 导入 ep02 新提示词 | 剧本 | L-031 | — | — | ⤴ |
| L-066 | 10-31 10:45 / 10:48 | “每一步学会的东西，都要转成 local 里的一个 system 和一对 prompt” | 经验沉淀成 knowledge 和提示词，autopilot 能自跑 | 流程 | — | knowledge 编译通过，autopilot 在 | knowledge/ 与 tools/autopilot 在；compile --check 本轮跑出 4 条旧错，总调度说 ITERAUDIT 已改绿 | ⚠ |
| L-067 | 10-31 14:19 | “Edit 功能：要加到每个地方……Delete 功能” | 每处都有编辑、删除 | UI | — | 编辑、删除、回收站 | EDITDEL 在做（LOCKS.md）；回收站已有项目方删除记录 | ⚠ |
| L-068 | 10-31 14:36 | “声音模型那边，我需要监听它的播放……我连播放按钮都没有” | 声音页能试听、接受、修改 | UI/声音 | — | 有试听接口和按钮 | 项目方 01:12–01:22 用过 POST /api/voices/preview（audit） | ✅ |
| L-069 | 10-31 15:46 / 15:52 | “剧本的页面你改坏了……之前起码有前后帧，还有视频” | 恢复每镜一行完整信息，不许静默删功能 | UI | — | 默认视图每镜一行 | memory no-silent-feature-removal 在；UIRSI 在恢复；本轮未截图 | ⚠ 未核实 |
| L-070 | 10-31 14:24 | “衣服、鞋子等很多东西都需要 reference” | 出图必须挂造型和单品参考 | 出图 | — | 契约 I3/I4 阻断 | GEN_CONTRACT I3/I4 + K-AST-230 在，但 `enforced: false` | ⚠ |
| L-071 | 10-29 17:43 | 选“自拍也是 AI 生成的” | 林晚脸已确认 AI 生成 | 人物 | — | face_reference 已确认 | memory session-ownership 记录 face_reference.json | ✅ |
| L-072 | 11-01 | （睡前授权）“视频成片只出预览，不定稿” | 视频只出预览 | 视频 | — | 能出成片前须有 V6 多肢 / V7 口型检测 | 两个检测器缺（K-REV-302），series10 只能出预览 | ❌ |
| L-073 | 10-30 16:21 | “镜头分镜里面……音乐提示词……都没有” | 分镜页要显示镜头、音乐提示词 | UI | — | 每镜显示提示词与音乐 | /api/episodes 的每集有 music 字段；单镜展示未截图 | ⚠ 未核实 |
| L-074 | 10-30 14:04 | “唯一的调度资源是远程 GPU3……image2.1……MiniMax” | 出图、出片只在远程 GPU | 流程 | 已扩为 gpu33 + gpu36 六卡（L-021） | — | render_endpoints 只指向隧道端口 | ✅ |
| L-075 | 10-31 13:09 | “两台服务器的内存条……1 TB，都要用完” | 内存用满（cache-ram） | 流程 | — | ComfyUI 带大 cache-ram | gpu33 `--cache-ram 64 96`，gpu36 `--cache-ram 56 88` | ✅ |
| L-076 | 11-01（选方案 A） | “自动执行对应制作,人类不应该点,坏了,系统自动做” | 常驻制作监督 PRODUCER 自动推进各阶段和导入；项目方不再逐个点阶段推进 / 导入，只在删除、花钱、推翻旧决定、挑身份参考时被问 | 流程/规则 | — | K-OPS-A01 在；tools/autopilot/producer.py 在；docs/AUTOPILOT.md §7 在 | 三者都在（knowledge/rules/asset_ops.yaml:97；AUTOPILOT.md:123 “## 7. 制作监督（PRODUCER）”）；常驻是否在跑本轮未核实 | ⚠ |
| L-077 | 11-01（方案 A 推论） | （同上，总调度转） | 导入可用系统身份 PRODUCER（带审计），前提是 P4 阻断数 = 0；replace 导入若会丢弃项目方锁定的成果，仍是项目方闸门 | 流程/剧本 | — | 导入接口认 PRODUCER 身份，校验 P4 阻断 = 0，replace 覆盖锁定成果时拦截 | 本轮只确认 producer.py 里 AGENT="PRODUCER"；导入闸门的代码未逐行核 | ⚠ 未核实 |
| L-078 | 11-01 | “我来不及筛选” | 角色音色由系统按 QAg 方法（Qwen3-TTS VoiceDesign + CosyVoice3）自动选，不再让项目方逐个挑 | 声音 | 取代 L-057 | voices.json 4 位角色都是新音色（含阿岚），并标 series=series10_v1 | config/voices.json 实测：林晚 lin_wan_cand/c2、顾沉 gu_chen_cand/c4、陈宇 chen_yu_cand/c2、阿岚 ch_a_lan_cand/c1，顶层与各条 series=series10_v1（tools/voice10/voice10.py autopick，11-01 02:57）；数字口径统一后重检选择不变（VOICE10 11-01 17:0x，docs/voice10/r1.md §2）；tools/qa/decision_check.py 11-01 19:3x D-VOC-04/05/06 ✅（合计 58：✅ 57 ❌ 0） | ✅ |
| L-079 | 11-01（一键） | “先隔离，验证后你删” | 旧材料先隔离、再验证，最后由项目方本人运行删除脚本 | 清理 | 细化 L-058 | 隔离区 + MANIFEST + 验证 + 删除脚本，AI 不删 | 隔离 76 项 23.0G；验证（API / build / compile / decision_check）通过；ops/cleanup/delete_quarantine_20261101.ps1 在，未运行 | ✅（删除待项目方） |
| L-080 | 11-01 16:10 | “启动图像识别模型,然后自动检测,一旦发现不对,叫系统重写做” | 看图闭环（R11-4/5/10）由只记录转为拦截 + 自动重出（D-VQA-01） | 出图/视频 | 取代 R11-4 “标定过 0.85 并经总调度批准才转阻断”、acting“不开拦截” | config/vqa.json judge.enforce=true；命中自动重出；低置信只记录 | enforce=true（decision_check ✅）；22 处旧口径残留待 VQAGATE 同步（decision_propagation 16:37） | ⚠ |
| L-081 | 11-01 16:15 | “image做出来后,用本地图像模型去检测图片是否达标……然后再跑视频rendering” | 图片闸门先于视频：视频只派过了看图检查的首帧；替换版由看图自动复核，代替总调度人工复核 | 出图/视频/流程 | 细化 L-080 | vqa.json gate.video_requires_q9=true；producer 不再停在“等总调度复核” | 16:37 video_requires_q9=false（AUDIT 读到），VQAGATE 在做 | ❌ |
| L-082 | 11-01 16:20 | 选“改用 Pika Flex (Recommended)” | series10 之后重出的视频改用 Pika Flex，已通过的镜头不动，保留泛红防护（D-VID-01） | 视频 | 扩展 R11-1/L-？的 Flex 默认到 series10 配方 | recipe_choice.json 指向 Pika 配方；K-REN-002/301 同步 | WORKFLOW 在做；STATUS.md 由 night.py 自动生成，口径须改 night.py | ⚠ |
| L-083 | 11-01 16:25 | “千万不要补补修修……一旦决定了,其它sub-tasks related都要改一下” | 全局决策原则 §G0：先全局扫描判断最优，决定后全量同步，旧口径登记扫描 | 流程/规则 | — | ITERATION_PROTOCOL §G0、K-OPS-D02、tools/qa/decision_propagation.py | 三者都在；decision_propagation 还没接进 iter_gate | ⚠ |
| L-084 | 11-01 16:22 | “s5等视频出来很糊……估计你的参数坏了” | 成片一律用原片合成（禁用代理）、同步原片、预览加放大；SOP §12“只放大定稿片”的口径改掉 | 视频/后期 | 部分取代 R11-7 / SOP §12 | 成片输入分辨率 ≥ 原片；ep01 重合成 | night.py:259 仍用 540×960 代理（AUDIT 16:37），PROD 在做 | ❌ |
| L-085 | 11-01 16:40 | “可以 你决定就可以 你一定要rsi轮回每次”；“视频那边很多问题……deep research……rsi下去直到修复好” | 夜间总调度自主决定、每轮续派；视频问题由 VIDEO-RCA 深研根治 | 流程 | — | NIGHT_PLAN_20261101 W1–W11 在跑 | 10+ loop 在跑；巡检 cron 每 45 分钟 | ✅ |
| L-086 | 11-01 17:2x | AskUserQuestion 选“只是嫌画质差 (Recommended)” | 林晚身份脸不换人：从设定图 A-s202 左栏大头按原图分辨率重新裁一张（头顶到下巴、含发际线和发色、不含项链衣服）登记为身份脸；以后“设为身份脸”只接受脸部裁切 | 资产/身份 | 取代 11-01 10:58 face_overrides 指向整张设定图（G20） | face_of = data/assets/identity_refs/lin_wan/lin_wan_face_hd_A_s202.png，manifest sha 一致；set_face 拒绝非脸部裁切（宽高比 0.6–1.6、人脸占比 ≥12%）；first_frame_jobs 重编（G21） | RSI 17:43 落实：face_overrides / manifest 改前备份（*.before_L086_20261101.json），70 个作业挂新脸、0 个挂整张设定图；10:58–17:43 间没有任何 take 用过整张设定图；test_single_identity_face / test_unified_frame / test_image_jobs 转绿 | ✅ |
| L-087 | 11-01 17:5x | “realism_ab……这个版本出来的东西,无论是画面效果还是颜色,都非常满意……很棒哎!”；AskUserQuestion 选“R0 现在这样” | 项目方对现行 S★ 出图的画面和颜色非常满意，锐化保持 R0：徕卡 S★ 全套（USM 1.2/60/2、后缀含“焦点锐利 / 暖调”、系统规格句）不改，契约 Q4 口径不改；RESEARCH 的 K-REV-X01 / K-REN-X02 / K-PRM-X04 标不采纳，RL01–RL03 只记录；GPU 档 G1 / G2 取消（scope=ab 代码保留） | 出图 | 维持 10-31 L-0xx 选 S★（leica_sharp）；不采纳 RESEARCH 改锐化 / 后缀 / Q4 的建议 | owner_decisions D-IMG-87a/b/c | decision_check + decision_propagation | ✅ |
| L-088 | 11-01 18:0x | “现在基本上要把图片和视频全部重做一次：1. 图片：全部重新勾一次，用最新的瑞丽 R0 方案。2. 视频：全部用皮卡来做。如果皮卡做不了，就等皮卡安装完再做。” | 全量重做：80 镜首尾帧按现行 S★ R0 重出；视频全部 i2va_pika_flex，无 pdd2 回退、无 Ref2VA 兜底，做不了的 hold；旧版本标过期不删 | 出图/视频 | 取代 L-082 “已通过的镜头不动” | recipe_choice 全 Pika；全量重做脚本；前置：G20/G21 → W5 → 剧本返修导入（L-090）→ Pika 冒烟亲审 | WORKFLOW 牵头；前置 G20/G21 ✅、W5 ✅（本地）；剧本返修进行中；Pika 冒烟 ep01-S3 已出（看镜头 + 外套形变） | ⚠ |
| L-089 | 11-01 18:05 | （总调度按 G0 定，RSI r5 设计冲突）—— | 驳回即撤下：master_reject 立即撤下被驳回的当前版本（P.clear_active），这一镜等替换版；改当前版本只走 pipeline.set_active 唯一入口并写审计（K-OPS-Q23 / K-OPS-V12） | 流程 | 取代 master_reject 旧口径“驳回版留作当前直到替换版通过” | producer.master_reject / ledger_sync / master_approve 已改；test_active_audit 白名单无 producer | PROD 18:10 落实，15 条测试过；随服务器推送生效 | ✅ |
| L-090 | 11-01 18:2x | “演员表现：所有图片不要看镜头，不要看镜头！……把演员的演戏规则、导演的规则、镜头的规则都做上去，把剧本改一下，重新更新一下规则。” | 补全表演 / 导演 / 镜头三套规则；编译器对所有出图和 Pika 出片注入视线句；写作模型按新规则返修 10 集（台词不变）并导入；授权写作 API 费用 | 剧本/规则/出图/视频 | 细化 R11-2/6/8/9 | D-SCR-07；QW-A7 / QW-AX1 等 lint；视线句覆盖率 100% | SCRIPT-RSI 18:2x 落实（CONSENT 见 LOCKS）：规则三表 docs/acting/PERFORMANCE_RULES.md §3；新 lint QW-A6/A7/A8/AX1 + K-WRT-T03 返修重切；frame_job 视线补句逐人覆盖、framing 双人句去掉朝向镜头（K-REN-703）；全部视频配方（含 3 个 Pika）继承视线句（测试锁）；10 集返修稿 data/staging_v3/merged/漆皮之下·十日_series10_v1_rsiD07_ep01…ep10_v3.md：台词逐字、集总时长不变、P4 阻断 0、目标 lint 217→8、镜数 80→92；**未导入**：/api/script-inbox/import 只收 by=owner（画布勾选）或 PRODUCER 令牌，SCRIPT-RSI 不冒用身份，待总调度定导入方式（import_plan：data/script_rsi/d07_full/import_plan.json） | ⚠ |
| L-091 | 11-01 18:3x | “把旧的东西全部移出……你要把规则跟最新的讨论内容 update 一次，然后再做一次全部。”；“我这台机器是能 run 一些图片的……部署一些图片模型” | 旧素材隔离到 _quarantine_20261101b（只隔离、删除由项目方运行脚本）；规则库刷新为现行口径；记忆清洗；笔记本部署本地出图道 laptop:0（D:\ns_comfy，参数与 S★ 一致） | 清理/流程 | 细化 L-079 | MANIFEST + 删除脚本；knowledge/archive；laptop:0 一致性验证 | CLEANUP / LOCALGPU 进行中；记忆已清洗（总调度） | ⚠ |
| L-092 | 11-01 21:4x | AskUserQuestion：“10 集都用，改完再出图 (Recommended)”；“改成 60–120 秒”；“允许，改成铅笔裙 (Recommended)” | 10 集按 HOLLYWOOD 模板重写，改完再恢复出图；集时长 60–120 秒（取代 QW-E3 50–75 / 目标 60–65，镜数上限按 ⌈秒数÷6⌉ 跟着变）；ep01 林晚人物卡“深灰西装裙”→“深灰铅笔裙”（HOLLYWOOD 人物卡不变量唯一字面例外，造型不变） | 剧本 / 写作规则 | 取代 K1 / QW-E3 时长口径 | D-SCR-08 / 08b、K-WRT-702（QW-W11）、hollywood.HEAD_EXCEPTIONS | RSI r7：导入器 / 校验器 / 上游 schema / writer_prompt / 写作合同 4 份文档已同步，decision_propagation 校验；HOLLYWOOD 10 集待开跑 | ⚠ |
| L-093 | 11-01 21:4x | AskUserQuestion：林晚造型 A 设定图“换回 v2_s202 (Recommended)” | 造型 A 当前设定图 = adopted/lin_wan_lookA_v2_s202.png | 资产 | 取代 11-01 10:57 人物中心挑的 lookA_s101（当时 v2 不在候选里） | D-AST-93（sheets_chosen.json） | IMGFIX 执行中；RSI 只入账 | ⚠ |
| L-094 | 11-02 00:2x | AskUserQuestion：“按剧本造型走 (Recommended)” | 鞋跟着每镜剧本造型：造型 A/B 透明高跟、造型 C 白球鞋；11-01 02:14:18 ep02 整集“全部透明 12cm 高跟”覆盖停用不删 | 资产 | 取代 11-01 02:14:18 整集鞋覆盖 | shot_looks.json overrides._stale + override_migration.l094 | IMGFIX 已执行：覆盖移出生效、作业重编 | ⚠ |
| L-095 | 11-01 22:5x / 23:0x | 22:5x：“记得每一次 iterate 完把东西记录下来.然后把规则系统的一些东西,全部代码都调一次,也就是说,每一次迭代都是用 override system,然后用 create a new version 那个 system versions”；23:0x：“在 GitHub 里面,帮我把这个分支的 working tree upload 上去,并在 GitHub 上 create 一个 git,名字跟这个 folder 的名字一样” | 每次迭代收轮后 cut 一个系统版本 sv-YYYYMMDD-NN（git commit + tag，规则 / 代码 / 配置 / 文档一起，可回退），deploy 覆盖两台服务器并写 data/system_version.txt；私有仓库 fredwong749-hub/NS-Final-Studio（origin），每次 cut 推前密钥扫描后自动 git push origin master --follow-tags | 运维 / 版本 | — | tools/qa/system_version.py、K-OPS-V01、iter_gate V2、docs/system_versions/INDEX.md、data/system_versions/index.json | CODE-RSI：sv-20261101-01 / -02 已发版、已推 GitHub、两台已部署 | ✅ |
| L-096 | 11-02 00:4x | “我要全部系统化，出一个 Hollywood level 的、画面非常漂亮的短剧……我起码要达到 50 分，就是你给的那个分数，50 over 50。”；AskUserQuestion 选“允许，剧情和人物不变 (Recommended)” | 写作目标 50 / 50（HOLLYWOOD 量表）；台词可为潜台词重写，发生了什么、谁说的、人物关系和设定不变（D-SCR-09，取代 HOLLYWOOD 不变量 I1“台词逐字”） | 剧本/流程 | 细化 L-092 / 22:1x“达到95分” | tools/script_rsi/hollywood_r5.py gate5：F1 说话人逐条顺序（代码）+ F2 独立事实核对调用；评审改可核对清单（config/prompts/hollywood_judge.md §三–§五） | HOLLYWOOD r5 11-02 落实，先跑 ep02 / 04 / 06 / 08（docs/master/HOLLYWOOD_PLAN.md §1B） | ⚠ 进行中 |
| L-111 | 11-02 04:0x | 项目方原话：“再新加一个关于灯光的提示词。剧本里面需要加上灯光，基于背景跟人物，做出适应的灯光场景……更加柔和，更加真实……要把它写到规则里面去” | 灯光词表 config/director/lighting.yaml（动机光源、主/辅/轮廓光比、柔硬、色温、人物适配）为单一来源；剧本每镜【灯光】字段（K-WRT + rubric）；第一季由导演层自动补；编译成固定位置的英文句，与融合契约句配合；与融合 A/B 合并验证 | 剧本/导演/出图 | 细化 L-107 / L-110 | lighting.yaml；K-WRT；shot_spec_v2 | DIRECTOR + HOLLYWOOD/SCRIPTWRITER + IMGFIX | ⚠ 进行中 |
| L-113 | 11-02 04:1x | 项目方原话：“交卷的那个样式不是特别好看，你可以选一下 positive frame，就是正片那些模式，然后做得更加真实一点”；“幻灯片设计出来了吗？之前缺乏镜头数据”；AskUserQuestion 选“B 深色桌面+灰纸框”，并选“允许下载”MiniMax-H3 官方运镜控制补丁（只装 gpu36） | UI 采用正片 B 风格（深色桌面 + 灰纸框，圆角片窗，框角 E-6），取代胶卷条；每镜必显镜头“实拍 / 计划”（D-LENS）；视频线可用 H3 Fun ControlNet（深度 + 机位轨迹）做运镜 A/B | UI / 视频 | 取代 r45 胶卷条方向 | season.py lens_info；data_parity D-LENS；gpu36 model_patches | UIRSI + VIDLAB | ⚠ 进行中 |
| L-112 | 11-02 03:5x | 项目方原话：“我需要你再做一个 image 生图的 RSI……两条重要 RSI 线：做图的线、做视频的线……剧本与分镜转化……UI 的 RSI……系统代码的 RSI……最终目标：一定要达到现在好莱坞电影的水平……你自己把这些 RSI 的标准、目标和分数定好……一整晚的时间”；“si = rsi” | 五条 RSI 线（出图 / 视频 / 剧本→分镜 / UI / 系统代码），标准、权重、目标见 docs/master/RSI_PROGRAM.md；每条线有代码打分器，分数写入 data/rsi/scores.jsonl；每条线有好莱坞参照集作满分锚点；SENTINEL 看板 + 每晚报告 + 分数不升自动开工单；GPU 24 小时时间分配（真正在跑 / 空跑 / 等待任务）上 8810 | 全系统 | 统摄 L-107 / L-110 / L-111 | RSI_PROGRAM.md；scores.jsonl；gpu_24h.json；8810 RSI 区 | IMGLAB / VIDLAB / HOLLYWOOD / UIRSI / SYSARCH + SENTINEL | ⚠ 进行中 |
| L-110 | 11-02 03:5x | 项目方原话：“发现一个新的 bug，就是 image 出图的问题：人物跟背景没有融合在一起，有点硬生生 PS 上去的感觉……写一写‘人物跟背景的柔和’这个提示词……学会怎么用（镜头资料）……没有出的图里面都要改一改” | 编译层统一注入融合契约句（光线/色温一致、接触阴影、同一景深、边缘自然、统一调色、空气感）+ 首帧使用镜头模板 v2 的焦段/景深/构图/光线；合成感检测（确定性指标 + VLM 题）进契约；未出/未过契约的首尾帧全部重编；S★ R0 预设参数不改（L-087） | 出图 | 细化 L-107 | K-REN（IMGFIX）；shot_spec_v2 | IMGFIX + DIRECTOR + VQAGATE | ⚠ 进行中 |
| L-109 | 11-02 03:3x | 项目方原话：“Claude后面写剧本还是你来写,用那个API太贵了测试阶段都是用你的,之后上线再用外面的API”；“写剧本你可以用fable5.1来写” | 测试阶段剧本由 Claude（Fable 5.1 子 agent）写，外部写作 API 停止花钱；writer backend 可切换（claude_agent / api），上线切回 api；写评分离；非露骨 + 成年自愿虚构不变 | 剧本/费用 | ⤴ 取代 10-30“Claude 不做内容参与”；L-097/L-104 的写作 API 预算冻结 | config/llm_providers.json writer_backend；autoflow | HOLLYWOOD + SCRIPTWRITER(fable) | ⚠ 进行中 |
| L-108 | 11-02 04:1x | 总调度按 L-098 定（依据：第一季按集换造型 A/B/C；L-104 原话“更加暴露点的版本”） | 第二季“不能改的人设”= 身份/名字/年龄/发色发型/脸（L-086）/标志性固定特征/人物关系/第一季已发生剧情；每集服装造型不是事实，以第二季剧本为准，新造型走 IMGFIX 资产流程；同集内无交代变装仍算缺陷 | 剧本/资产 | 细化 L-096 红线口径 | K-WRT-H10；hollywood 事实表 | HOLLYWOOD + IMGFIX | ⚠ 进行中 |
| L-107 | 11-02 03:2x | 项目方原话：“我发现了一些 AI 的运动镜头，需要你把这些内容放到镜头的提示词里面去……1. 让 Master Agent、剧本 Agent 和导演 Agent 学会这个事情，并写到本地规则里。2. 在 Season 2 里面，可以把这些内容写进去。” | 运镜词表 config/director/camera_moves.yaml 为单一来源（资料 docs/reference/camera_moves_20261102.md）；逐项在 Pika 上 A/B，过的才 enabled；导演层/编译层/写作规则/rubric 都按词表；第二季按新规则写 | 导演/剧本 | 细化 K-REN-801（改为按词表 enabled 判定） | config/director/camera_moves.yaml；K-WRT-8xx；rubric_code | DIRECTOR + HOLLYWOOD；总调度巡检核对 | ⚠ 进行中 |
| L-106 | 11-02 03:2x | 项目方原话：“允许笔记本监控自启”；另 03:1x “权限设置里放开 rsh.py 的远程命令” | 笔记本 SENTINEL 守护进程 + 8810 看板开机自启（计划任务）；用户级 settings.json 放开 tools/netfix/rsh.py 远程命令 | 运维/权限 | — | ops/autostart/；C:\Users\fredw\.claude\settings.json | SENTINEL / 总调度 | ⚠ 进行中 |
| L-105 | 11-02 03:1x | 项目方原话：“允许服务器常驻托管” | gpu33 / gpu36 生产进程用 systemd --user 托管（崩溃自动重启、开机自启），单元文件入库随 sv 发版 | 架构/运维 | ARCH-AUDIT #3 | ops/factory/systemd/；K-OPS-F09 | FACTORY | ⚠ 进行中 |
| L-104 | 11-02 02:4x | 项目方原话：“你再写一个类似的故事喽。现在这个故事是十集嘛，你再写个第二季（Season Two），讲这个女孩的第二阶段喽。反正之前我不是给过你一个 60 集的故事嘛，你就把后面的故事再做一个升级版本，更加暴露点的版本呗，这样更有看头嘛。你就把这个故事当作第二季，开启一个新的剧本，跑你这个流程。”；AskUserQuestion 预算选“$8” | 新开第二季 run（多剧并行，不替换 series10）：10 集，接第一季结局，取旧 60 集后半段做升级版；风格方向原话转写作模型；写作 API 上限 $8（每集 ≤ $0.8）；作为新建剧本全流程的验收 run | 剧本/流程/费用 | 系统硬约束不变：全部成年人（≥22）、自愿、非真实人物、亲密镜只本地生成；Claude 不写不评剧本内容 | config/pipeline/runs.json；budget.writing_per_run | HOLLYWOOD r8 + DISTILL | ⚠ 进行中 |
| L-102 | 11-02 01:4x | 项目方原话：“这个系统是拿这部剧来做一个 sample 的。所有的 learning 规则都要写到这个系统里，后面就不用 Claude 来指引整个事情了……我只会用 API key 来做简单的工作……所有工作尽量写成一个代码库，来 monitor 整个 process……创建剧本之后，剩下的流程就会按照你现在写的代码和规则全部自动化下来” | series10 是样板；每轮 RSI 必交“提炼”（判断→代码策略/规则/check/文档）；剧本导入后全流程由单一编排器推进与监控；跟踪无 Claude 覆盖率（decider 标注） | 流程/系统 | 细化 10-31 autopilot 目标 | docs/ITERATION_PROTOCOL.md §G1；tools/autopilot/；config/policies/ | DISTILL loop | ⚠ 进行中 |
| L-100 | 11-02 01:2x | 总调度按 L-098 定 | GPU 分工：笔记本 4080 + gpu36 GPU2 专做看图（VLM），出图道 5 条（gpu33 0/1/3、gpu36 0/1） | 资源 | — | config/netfix/override.json laptop_hold；config/vqa.json model.instances | VQAGATE / FACTORY | ⚠ 进行中 |
| L-099 | 11-02 01:1x | 项目方：“服务器那边应该有个 local 库……笔记本应该做一个简单的同步脚本任务,派到那边去生产” | 服务器是工厂、笔记本是控制台；方案 C（声明式 inbox + 按 sha 的本地库 + preflight 闭包 + 本机打分 + outbox） | 架构 | 取代 K-OPS-N06 临时覆盖 | docs/master/FACTORY_ARCH.md、FRAMEWORK_REFRAME.md | FACTORY | ⚠ 进行中 |
| L-098 | 11-02 01:0x | 项目方原话：“决定就好了.我现在给你 RSI,意味着全自动给你,你来做所有的决定要求目标达到.还有那个剧本,50美金,尽量少收一点,太贵了” | ① 全权委托：资产候选点选（含造型 A 袖子修复）与流程取舍由总调度按契约 + 亲审定，不再等项目方点选；不推翻已定审美决定（S★ R0、全 Pika、不看镜头、look A=v2_s202 脸身），不删除、不越权限。② 写作花费：r5 总上限 $50→$15（含已花约 $3.5），每集 ≤ $3，连续 1 轮不涨即停 | 资产/流程/费用 | 修订 L-093（点选人→总调度）、L-097（$50→$15） | hollywood_r5.py COST_CAP_USD；run5.sh 每集预算 | 总调度执行 | ⚠ 进行中 |
| L-097 | 11-02 00:4x | AskUserQuestion 选“$50” | 写作 API 预算 50 美元（从 r5 起算），先集中 3–4 集冲满分，验证方法有效后再推广 | 流程/费用 | — | hollywood_r5.py COST_CAP_USD = 50；每集预算 run5.sh 默认 9 | HOLLYWOOD r5 按集记账（report.json usage） | ⚠ 进行中 |
| L-101 | 11-02 01:2x | 项目方 01:08 全权委托（L-098），总调度代为点选“采用候选 1” | 林晚造型 A 当前设定图 = adopted/lin_wan_lookA_v2_s202_sleevefix.png：v2_s202 正面栏左臂补深灰外套袖（露米白袖口），遮罩外逐像素不变（脸、身体、其余三栏不变）；衣橱短款西装外套登记“两只袖子都是深灰西装袖（露米白衬衫袖口）”经编译器生效 | 资产 | 取代 L-093 的 adopted/lin_wan_lookA_v2_s202.png（旧图隔离 data/_quarantine/imgfix_lookA_sleeve_20261102/） | D-AST-93（sheets_chosen.json） | IMGFIX r5：契约逐项 data/review_pages/lookA_sleeve_fix/check.json；ep02-S4 验证中；lookA_hold 待解除 | ⚠ |
| L-099b | 11-02 01:2x | 项目方 01:1x：“单独写个 Agent，在服务器的 GPU 上写代码，把我们遇到的慢连接、断连一大堆的问题，在那边把系统的 framework 重新 reframe 一下”；总调度批复 FRAMEWORK_REFRAME 选 C | 服务器工厂框架 = 方案 C：服务器常驻 producer（本机道表，只连 127.0.0.1 的 ComfyUI）+ 声明式目标状态 inbox（带 min_code_sv，含全部 *_hold.json）+ 内容寻址本地库 + preflight dryrun 依赖闭包（交还条件 preflight_dryrun_ok）+ 本机打分常驻服务 + outbox（manifest.json + .done）；断网 ≠ 暂停；服务器代码 = 干净的 git 工作树，部署只发 tag 里的文件（工作树 drift 只报不拦），按道排空后重启（空转 ≤ 1 分钟）；D1–D10 全部批准；B（服务器放 GitHub 凭据 / 对象存储）暂不做、不问项目方 | 运维/架构 | 细化 L-099（docs/master/FACTORY_ARCH.md）；方案见 docs/master/FRAMEWORK_REFRAME.md；⤴ 取代 K-OPS-N06 临时覆盖和笔记本隧道派单（按 §5 迁移后隔离） | 规则从 K-OPS-F01 起（待落） | FACTORY loop 执行中（开发树 gpu36:/root/work/fredw/ns_factory_dev） | ⚠ 进行中 |

## 2. 残留清单

### 2.0 第二次隔离 + 规则刷新（CLEANUP，11-01 18:3x，L-091，总调度 fredw-2b 派）

> 项目方原话：“把旧的东西全部移出，因为我很怕你的记忆里面混入太多旧的素材了。所以，你要把规则跟最新的讨论内容 update 一次，然后再做一次全部。”沿用 L-079：只隔离，删除由项目方本人运行 `ops/cleanup/delete_quarantine_20261101b.ps1`。

- **隔离**：`data/_quarantine_20261101b/MANIFEST.md`，77 项 300.8M（12 篇旧会话 / ep02 时期文档、离线并回副本 3 项（已逐个核对 1321 个文件都已并回）、旧 60 集 / 母版 / lin_wan_qi 时期日志 31 项、golden 5 项、previews 8 项、master_face 缓存 6 项、dry-run 5 项、旧剧本备份 3 项等）。每项先跑引用检查（新规则 **K-OPS-Q30**，check = `tests/test_quarantine_refcheck.py`；工具 `tools/qa/quarantine_refcheck.py` + `quarantine_safe_move.py`）。验证时 compile --check 抓到 2 项是知识库证据（K-OPS-W02 / K-OPS-311 / RSI_LEDGER WF1），已恢复 3 处。
- **有引用、没移**（21 项，列在 MANIFEST 末尾）：`script play lib/`、`data/staging_v3/为他而骚*`（config/script_chat.json `header_sources` 与 `config/script_mainline.json` 仍指向 60 集 v3.1 / v2）、`data/iterate_loop/ep02_v2`、`data/pipeline/runs/ep02_r3`、`docs/ep02_iter/`（知识库证据）、`golden/`、`training/`、`previews/` 其余、`data/_offline_pull/_backup`、截断件隔离区等。
- **知识库**：K-EDT-I02 / K-WRT-008 / K-UI-019（已被取代）、K-REV-X01 / K-REN-X02 / K-PRM-X04（L-087 不采纳）移到 `knowledge/archive/superseded_20261101.yaml`；compile.py 加 `archived_ids`（supersedes 与 RSI_LEDGER 指向归档条目算存在），生成物已重编。K-EDT-013 标题“对白兜底仍用 Kokoro”改指 K-EDT-016 / L-078。
- **写作方文件**（CONSENT 见 LOCKS.md）：附录删 Alex/Ryan/Kai/Leo、60 集 D0–D10 分集表、60 集地点词表、旧风格后缀（85mm / 奶油 / 浓郁）、“看向镜头”可选视线、Qwen 出图调度整条；script_chat_rules.md 第 86 行 char_id 例子与第 106 行风格后缀；production_rules_v3 / qwen_writing_contract / chain.yaml writer_text 的 slug 例子改为 series10 四人。
- **过期口径**：owner_decisions 新增 D-VID-88、D-POST-84、D-ACT-90、D-CLN-10、D-CLN-11，D-IMG-01 / D-AST-86a 补 stale_terms；decision_propagation 残留见 §2.3 R14。


### 2.1 本轮已隔离（只移动，不删除）

清单在 `data/_quarantine_20261101/MANIFEST.md`，共 76 项 23.0G。

| 类别 | 机器 | 项数 | 大小 |
|---|---|---|---|
| assets | 笔记本 | 8 | 57.6M |
| loras | gpu33 | 27 | 16.9G |
| loras | gpu36 | 3 | 277M |
| loras | 笔记本 | 17 | 5.5G |
| renders / BGM / 审片页 | 笔记本 | 17 | 332M |
| voices | 笔记本 | 4 | 1.6K |

**改动过的配置**：先把原件备份到 `data/_quarantine_20261101/config/*.orig_20261101`，再就地删除旧条目。

| 文件 | 删掉的内容 |
|---|---|
| `config/voices.json` | 9 个旧角色和 chorus_men |
| `config/scene_aliases.json` | 3 条指向已隔离目录的条目 |
| `config/adult_overrides.json` | 7 条 ep>10 的 force_adult |
| `config/auto_lora_triggers.json` | lnwan_qi |
| `config/render_quality.json` | identity_loras 里的 lin_wan_qi |
| `data/import/script_v2.json` | globals.lora_triggers 里的 lnwan_qi，以及 77 处镜头 img_triggers 里的 "lnwan_qi" 元素。已逐项验证：剧本其余内容逐字不变 |
| `data/looks/looks.json` | Alex / Ryan / Kai / Leo 的 4 个 default look |
| `data/looks/schedule.json` | 4 人的 character_defaults；ep>10 的 50 集 episodes 和 300 条 shot_characters |

### 2.2 本轮已改的代码

改前已在 `docs/uimaster/LOCKS.md` 登记；原件备份在 `data/_quarantine_20261101/code_orig/`。

| 文件:行 | 改了什么 |
|---|---|
| `packages/schema/ns_schema/looks.py:34` | CHARACTERS 不再硬编码 Alex / Ryan / Kai / Leo，改为读正式剧本 globals.character_registry（读不到时兜底为 series10 四人，含阿岚 ch_a_lan） |
| `services/agent/ns_agent/looks.py:76-80` | PRESENCE_HINTS 去掉 4 人；其余登记角色（阿岚）按中文名判断是否在画 |
| `services/agent/ns_agent/state_timeline.py:129` | GU_CHEN_SIDE 只剩 gu_chen |
| `services/post/ns_post/speakers.py:30-38` | 去掉 Alex / Ryan / Kai / Leo / 四声齐；加上 阿岚 → ch_a_lan |
| `services/render_router/ns_render/frame_edit.py:322` | canvas_face_lock 恒为 False。旧逻辑“没挂身份 LoRA 就走两段换脸 qwen_two_stage”依赖已撤的 lin_wan_qi，而 K-REN-134 已定“不再用旧首帧作图1换脸”；series10 走 unified_frame，不经过这里 |
| `tests/test_looks.py`、`test_post.py`、`test_render_quality_q1.py` | 改了断言旧演员 / lin_wan_qi 的几行，改为新决定 |

### 2.3 仍在系统里的残留（未动，需派人）

| # | 路径:行 | 为什么是残留 | 谁在用 | 替代 / 处理 | 建议负责 |
|---|---|---|---|---|---|
| R1 | `data/pipeline/runs/series10_v1/assets/first_frame_jobs.json`（80 条） | graph 里仍挂 `lin_wan_qi_v1.safetensors`（文件已隔离）；也不是 frame_v9 | `tools/pipeline/submit_jobs.py`（preflight I8 会拒） | **仍有活读者，不能隔离**：① services/api/ns_api/story_runs.py:677-691（/api/story-runs 从这里读 asset_refs，只读，读不到就现算）；② tools/series10_imggen/imggen.py:171（有 graph 就直接用 graph 出图）；③ tools/bakeoff/run.py:190、tools/gen_contract/calibrate_q.py:56、tools/series10_imggen/server_deploy.py:33。处理：用 tools/pipeline/image_jobs.py 重建，或让 imggen 改走 frame_job.build_first。RECALL 用同一函数重建到 `data/qa/recall_smoke/_recall_smoke_first_frame_jobs.json`，确认重建后没有 lin_wan_qi | SERIES / ASSETMASTER（总调度派） |
| R2 | `data/import/script_v2.json:86 / :97 / :108`（globals.lora_triggers 的 starts） | `"ep09起"`、`"ep15起（逐步到9枚）"`、`"ep21起"` 是 60 集的起始集号 | 导入器把它当登记信息 | 属剧本数据，交写作方按 10 集改；文件名 jewellery_*_v1 / wardrobe_*_v1 在 gpu33 和 gpu36 的 loras 目录里都不存在 | 写作方（SERIES） |
| R3 | `services/post/ns_post/speakers.py` | 已清：旧 60 集称呼（穿孔师 / 纹身师 / 同事 / 男同事 / 店员）隔离到 LEGACY_60EP_TITLES，不再参与解析；NAMED 只含 voices.json 里有音色的人 | ns_post.speakers.resolve_episode → tts | series10 剧本里这些称呼 0 次（data/import/script_v2.json 实测）；tests/test_voice10_fix.py::test_legacy_60ep_titles_quarantined 通过（K-EDT-020） | VOICE10（已关） |
| R4 | `config/voices.json` | 已清：林晚 lin_wan_cand/c2、顾沉 gu_chen_cand/c4、陈宇 chen_yu_cand/c2、阿岚 ch_a_lan_cand/c1（cosyvoice3_zs），顶层 series = series10_v1 | night.py voices_ok() 放行；/api/voices | 按 L-078 系统自动选（L-057 已被取代）；D-VOC-04/05/06 ✅（decision_check 11-01 19:35） | VOICE10（已关） |
| R5 | `services/api/ns_api/voice_preview.py:5,29,87` 与 `/api/voices/candidates` | 候选音色仍是 Kokoro sid 3–57 | 声音页 | 换成 Qwen3-TTS / CosyVoice3 候选（和 QAg 同一套方法） | VOICE10 |
| R6 | ✅ 已清（CLEANUP 11-01，§2.0）`config/script_chat_rules_appendix.md:20` | 写作规则触发词里仍列“Alex、Ryan、Kai、Leo” | 写作模型提示词 | 已删并换成阿岚；D-CLN-11 grep_absent 守住 | — |
| R7 | `services/render_router/ns_render/pipeline.py:867`（qwen_two_stage / compose） | 旧“身份底板两段换脸”出图路径 | 未登记资产的项目会走 ns_render.pipeline 默认；series10 不走 | 确认无入口后整段删除 | ARCH |
| R8 | `services/agent/ns_agent/frame_job.py:5` 注释与 `data/cache/refs/master_face_*` | 旧母版裁切 master_face（K-REN-134 已禁） | 只剩注释和缓存 | 清缓存目录 | ARCH |
| R9 | `services/api/ns_api/assets.py`（face_url） | /api/assets/characters 的林晚 face_url 仍是 `plates/id_front_s0.png`，不是项目方挑定的 face_ref2va | 资产页 | 和 character-hub 统一到 identity_refs | DATAALIGN / ASSETUX |
| R10 | `data/looks/looks.json`、`schedule.json` | 阿岚没有 default look（default_look_id = None） | /api/looks、/api/assets/characters | 按 P1_looks 给阿岚建造型 | ASSETMASTER |
| R11 | `data/looks/schedule.json` episodes "1"–"10" | 种子来自旧 60 集 decor_schedule（例：ep6“妆容冲突”说明） | LookStore 集层解析 | 项目方闸门：已写进 docs/overnight/morning_decisions.md 第 3 项选择题，不擅自重新播种 | 项目方 → ASSETMASTER |
| R12 | `config/render_quality.json:270 / :625` 注释 | 文字仍描述“lin_wan_qi 0.6 / 0.8”（只是注释，不参与计算） | — | 下次改配置时顺手更新 | REFLOCK |
| R13 | 待确认、未移动：gpu33 + gpu36 的 `minimax_h3_ref2v_turbo_*`、`QI2.1_AnyAngle`、`qwen-image-2.1-outfit-swap` | 只有 tools/ab、tools/char_assets 引用，现行配方不用 | tools/char_assets/build_jobs.py（outfit-swap）、tools/ab/char_sheet_qi21.py（AnyAngle） | 总调度定：有代码引用就留。都还有工具引用，所以保留 | — |
| R14 | `knowledge/rules/render_video_s10.yaml` K-REN-301（标题 / then / 第 82 行证据注） | 仍写“脸红类描述镜换回 i2va_pdd2；纯 Ref2VA 24 步只用于无通过首帧”“已经通过的镜头不动；Ref2VA 兜底不变”，与 L-088（视频全部 Pika、flush_risk 挂起、无 Ref2VA 兜底，config/pipeline/video_policy.json）冲突；标题行带 ⤴ 所以旧扫描放过了 | 该文件 18:07–18:19 仍在被别的 loop 改，CLEANUP 没动 | 按 L-088 改 K-REN-301 并写上 “L-088 / pika_only”，第 82 行注加 ⤴；之后 D-VID-88 转绿 | WORKFLOW / VIDEO10 |
| R15 | ✅ 已修根因（CLEANUP r3，K-OPS-Q31）`config/script_chat.json` header_sources / `config/script_mainline.json` | 原写死 60 集旧稿路径、每次导入要人工改 | ns_api.script_chat / script_inbox | 改为从 script_v2.json sources 自动推导（ns_api/import_sources.py，sha 一致才用），推导不出来才回退配置；tests/test_import_sources.py | — |
| R16 | `packages/schema/ns_schema/upstream_common.py:17` CHAR_ID_RE、`storyline.py:67/137`、`tools/validate_qwen_script.py:119` QW-P2 文案 | 仍允许 / 列出 alex、ryan、kai、leo 四个旧 slug（规则文档已改成 series10 四人） | 写作链校验 | 从允许列表去掉（表外人名本来就由 HC-05 拦）；属代码改动 | CODE-RSI / ITERAUDIT |
| R17 | `config/visual_bible.toml` [look].fallback_suffix | 仍是 10-30 旧后缀（85mm f/1.2、奶油般柔焦、浓郁饱和、色彩丰富艳丽），项目设置页“③ 风格 · 统一风格后缀”会显示它；现行出图走 S★ 预设、契约 I7 拦这些词 | ns_agent.bible / compiler（剧本没写后缀时）、project_settings、wizard | 改成 S★ 后缀原文或标注“不用”——是配置值改动且项目方可见 | 总调度定 → REFLOCK |
| R18 | `tools/autopilot/roles.py:76` | autopilot 角色表仍写“K-EDT-I02（未挑定前闸门）”（规则已归档，L-078 改为系统自动选） | autopilot 角色说明 | 改成 K-EDT-016 | AUTOPILOT |

## 3. 系统图（页面 → API → 源文件）

DATAALIGN 的 `docs/DATA_MAP.md` 在 02:30 还不存在，下表由 RECALL 按路由和代码实测整理。

| 内容 | 页面（#/…） | API | 处理代码 | 数据源（真相） |
|---|---|---|---|---|
| 剧本（写作链） | #/script-create?run=series10_v1 | GET /api/story-runs、/api/story-runs/{id}[?ep]、/artifact/{node} | services/api/ns_api/story_runs.py | data/pipeline/runs/series10_v1/（P0–P4、ep01–ep10/P4_epNN.md） |
| 正式剧本 / 分集 / 分镜 | #/overview、#/cut、分集编辑器 | GET /api/season、/api/episodes、/api/episodes/{n} | ns_api/season.py、app.py、episodes_fast.py | data/import/script_v2.json（10 集）+ data/edits |
| 演员表 | 资产中心·人物 | /api/assets/characters、/api/character-hub、/api/looks | ns_api/assets.py（character_ids ← ns_schema.CHARACTERS ← script_v2 globals.character_registry）、character_hub.py、looks.py | data/import/script_v2.json、assets/characters/<id>/、data/assets/identity_refs/ |
| 造型 / 单品 | 资产中心·人物 | /api/looks、/api/looks/wardrobe/…、/api/character-hub/{cid}/… | ns_agent/looks.py（LookStore） | data/looks/{wardrobe,looks,schedule}.json、series10_v1/P1_looks.json |
| 场景 | 资产中心·场景 | /api/assets/scenes[/{id}]、/plate-pick | ns_api/scene_assets.py（scene_ids = 剧本场景库 ∪ data/scenes.json ∪ 用到的 ∪ assets/scenes 目录） | assets/scenes/<sk_*>/、data/scenes.json、config/scene_aliases.json |
| 声音（音色） | #/sound | /api/voices、/candidates、/narrator-samples、/preview、/{cid}/select、/in-script | ns_api/asset_center_p1.py、voice_preview.py | config/voices.json、data/assets/voices/narrator_qag/ |
| 台词音频 | #/sound | /api/sound/lines、/api/shots/{id}/audio | ns_api/shot_audio.py → ns_post.speakers / tts | config/voices.json（line_overrides）、剧本台词 |
| 配乐 | #/sound | /api/music、/api/music/{ep} | ns_api/season.py 一带；ns_post/music.py、assemble.find_music | data/music/epNN.wav（旧，已隔离）；series10 期望 data/music/series10/epNN.wav（缺） |
| 首帧 / 尾帧 | 分镜行、编辑台 | POST /api/shots/{id}/frame-jobs；GET /api/jobs | ns_api/frame_jobs.py → ns_render/frame_edit.regen → unified_frame（frame_v9）+ ns_agent/gen_contract preflight / postflight | config/render_quality.json、config/recipes/asset_refs.json、config/gen_contract.json → data/renders/epNN/SN/takes.json |
| 批量首帧（SERIES） | — | — | tools/pipeline/image_jobs.py → submit_jobs.py | series10_v1/assets/first_frame_jobs.json（R1：仍是旧图） |
| 视频 | 分镜行、#/cut | POST …/gpu3-rerender、render 队列 | ns_render/h3_video.py、workflows.py；tools/series10_video/night.py | config/render_endpoints.json（gpu33:0/1/3、gpu36:0/1/2）→ series10_v1/video、data/episodes/series10/ |
| 合成 | #/cut | /api/post/…、/api/episodes/{n}/cuts | ns_post/assemble.py | data/episodes/*.timeline.json |
| 审计 / 回收站 | #/audit、#/trash | /api/audit、/api/trash | ns_api/auth.py 中间件 | data/audit/*.jsonl、data/_trash/ |

## 4. 缺口表（按严重度）

| # | 严重度 | 缺口 | 证据 | 负责 |
|---|---|---|---|---|
| G1 | 已关 | ~~4 位角色没有新音色~~ → 4 位角色都有 series10 克隆音色（含阿岚） | D-VOC-04/05 ✅（tools/qa/decision_check.py 11-01 19:3x）；tests/test_post.py::test_resolve_overrides_and_every_script_speaker_has_a_voice 通过（11-01 19:3x 实测）；tests/test_voice10_fix.py::test_every_series10_line_resolves_to_a_voice 通过 | VOICE10 |
| G2 | 已关 | ~~voices.json 没有 series10_v1~~ → 顶层 `"series": "series10_v1"` 已写 | D-VOC-06 ✅（tools/qa/decision_check.py 11-01 19:3x）；night.py voices_ok() 放行。ep04 合成失败的真实根因另见 K-EDT-019（docs/voice10/r1.md §2） | VOICE10 |
| G3 | P0 | 契约通过的图要在所有路径上自动设为当前（项目方：图片“全部默认同意”）。ASSETMASTER 的 register_takes 已做；画布重出（unified_frame.postflight_async）之后还没有 set_lock | unified_frame.py:156 起 | PRODUCER |
| G4 | ✅ 已完成 | 首帧 postflight 交接：ASSETMASTER 写 takes.json 的 postflight 字段和 frames_ok.json，VIDEO10 两种都读；第一条片 ep01-S5 已按它派出 | 总调度 11-01 确认 | ASSETMASTER + VIDEO10 |
| G5 | P1 | series10 BGM 只有 1 集（项目方定“整集统一 BGM”）；02:20 时 /api/music 还是空 | data/music/series10/ | VIDEO10 / 声音 |
| G6 | P0 | 视频契约 V6 多肢、V7 口型检测器缺失，series10 视频只能出预览、不能出成片（K-REV-302） | 总调度转 | VIDEO10 |
| G7 | P1 | SERIES 首帧作业清单 80 条仍挂 lin_wan_qi_v1、不是 frame_v9（R1） | first_frame_jobs.json | SERIES / ASSETMASTER |
| G8 | P1 | 前后端数据不对齐（项目方：S1–S4 一模一样） | L-056；story-runs `?ep` 与 `?episode` 返回相同 | DATAALIGN |
| G9 | 已关 | ~~speakers.py 仍映射旧称呼~~ → 旧 60 集称呼隔离到 LEGACY_60EP_TITLES（不删、不参与解析），NAMED 只含 voices.json 里有音色的人（K-EDT-020） | services/post/ns_post/speakers.py；tests/test_voice10_fix.py::test_named_speakers_all_have_voices / test_legacy_60ep_titles_quarantined 通过 | VOICE10 |
| G10 | P1 | 阿岚没有 default look；schedule 的 ep1–10 是旧剧种子（R10、R11） | /api/looks 里 ch_a_lan default_look_id = None | ASSETMASTER |
| G11 | P1 | 剧本 globals 的 60 集起始集号；饰品 / 衣橱 LoRA 文件在服务器上不存在（R2） | script_v2.json:86/97/108 | 写作方（SERIES） |
| G12 | P1 | FLUX.2 Klein 9B、FLUX.3 Klein 没下载（只有 4B） | gpu36 diffusion_models | ASSETMASTER / BAKEOFF |
| G13 | P2 | 写作规则附录仍列 Alex / Ryan / Kai / Leo（R6） | script_chat_rules_appendix.md:20 | 写作方 |
| G14 | P2 | 资产页林晚 face_url 与项目方挑定的身份参考不一致（R9） | /api/assets/characters | DATAALIGN / ASSETUX |
| G15 | 已关 | auto_final_on_lock 保持 false：总调度裁定 L-017 已被 frame_v9 取代 | L-017 | — |
| G16 | P2 | 契约 I3/I4（造型、单品参考）的规则仍是 `enforced: false` | K-AST-230 | REFLOCK |
| G17 | P2（test_post 部分已关） | 仍红的测试：test_state_timeline 的 character_state_fields、owner_confirmation、inject_off 三个。用原件副本复跑同样失败；失败点是 auth.py 自动补“（fred 登录点选）”以及 60 集 golden 夹具，与清理无关。~~test_post::every_script_speaker_has_a_voice~~ 已过（VOICE10 11-01 19:3x 实测 tests/test_post.py 1 passed；G1 已关）。本轮已修好 frame_jobs_w2 / image_params_px / backend_f4 / leica_sstar / render_quality_q1 / looks 共 109 个用例 | pytest | ARCH（state_timeline） |
| G18 | P2 | 旧代码路径 qwen_two_stage（R7）、master_face 缓存（R8） | pipeline.py:867 | ARCH |
| G19 | P3 | 未核实的决定：L-003/011/029/042/045/052/055/069/073，需各负责方回报实测 | §1 | 各负责方 |
| G20 | ✅ 已关（L-086，RSI r5） | 林晚出图身份脸现在是**整张 4 栏设定图** A-s202（ar-f9519334bc），不是脸部裁切：11-01 10:58 fred（role owner）在人物中心点“设为身份脸”，10:58:37 又把 lin_wan_face_ref2va.png 驳回为“画质差”。asset_refs.face_of 读 face_overrides，所以之后所有出图挂的身份脸都是整张设定图（拼图 / 照搬参考板的风险）；identity_refs/manifest.json 仍登记旧裁切 → tests/test_single_identity_face.py、tests/test_unified_frame.py 红。待定：项目方是想换脸，还是只嫌裁切画质？要是想换，建议从 A-s202 重新高清裁脸再登记，而不是挂整张；人物中心 set_face 只该接受脸部裁切 | data/looks/face_overrides.json；data/looks/character_hub_log.jsonl 第 28–29 行；data/audit/20261101.jsonl | 总调度（问项目方）→ ASSETUX（set_face 限制）/ REFLOCK（重裁登记） |
| G21 | ✅ 已关（L-086，RSI r5） | 首帧作业清单过期：first_frame_jobs.json 是 10:32 生成的，11:14 ACTING 在编译器里加了视线句（K-REN-G01），之后没重编 → 只有 24/80 和编译器输出一致（tests/test_image_jobs.py 红）。要等 G20 定了再重编（否则会把整张设定图写进作业） | data/pipeline/runs/series10_v1/assets/first_frame_jobs.json；tools/prompt_v2/audit_framing.py | AUTOPILOT（image_jobs.rebuild_first_frame_jobs，经 PRODUCER） |
| G22 | P2 | tests/test_image_framing.py::test_closeup_subject_and_lead 还在断言旧句“只拍手”；framing.closeup_lead 11:10 改成正向句“画面里只有手这一局部…”（tests/test_gen_contract.py:468 已同步）→ 测试改成断言“画面里只有手” | services/agent/ns_agent/framing.py:186 | REFLOCK |
| G23 | P2 | tests/test_review_fixes_d9.py::test_h1_http_put_routes_strip_owner_confirmation 复制了真实 data/looks；真实排期里 ep04/05 林晚已经有项目方确认，range PUT 正确地保留了旧确认，测试却断言为空 → 测试改成断言“伪造的确认没写进去”（owner_confirmed_ref ≠ “伪造的原话”），或复制后先清掉确认字段 | tests/test_review_fixes_d9.py:36–68 | 总调度指派（looks 归属未登记） |
| G24 | P2 | tests/test_fix_ep02_round2.py：ep02-S1 最新视频提示词含 Picture 2（H3-A4），是 11-01 06:15 别的流程出的版本（已知） | docs/CHANGELOG_AGENTS.md | VIDEO10 / PROMPT |
| G25 | P2 | 只差一行 check 引用的规则：K-PRM-301（tests/test_recipes_engine.py）、K-PRM-302 + K-REV-301（tests/test_rsi_rule_checks.py），都在 render_video_s10.yaml，WORKFLOW 16:16 还在改这个文件，RSI 没碰。另外 13 条 RSI 已直接加好（edit / writer_camera / render_imggen_s10），无检查规则 141 → 128 | docs/rsi/UNCHECKED_AUDIT.md A / B | WORKFLOW |
| G26 | P2 | 能补检查、但要动 owner 代码的 17 条：REFLOCK（K-AST-001、K-REV-121、K-REV-122、K-AST-252、K-WRT-210）、ASSETMASTER（K-AST-221、K-AST-222）、VIDEO10（K-REN-301、K-OPS-302、K-OPS-303、K-PRM-011）、AUTOPILOT（K-REV-010、K-EDT-007 合成侧）、VOICE10（K-EDT-018 已由 RSI 补测，划掉）、IMGPERF / INFRA（K-OPS-121 / I06、K-OPS-I04） | docs/rsi/UNCHECKED_AUDIT.md C | 各 owner |
| G27 | P1 | V6 坏手指阈值为空（150 条测了、91 条 >0.2、全放行）；最新 ep01_v2 里 S2 / S4 用的是多手版本；看图服务和生产抢 gpu36 GPU0（OOM） | data/qa/defect_hunt/state.json DH-V20 / DH-X03；data/qa/defect_hunt/vlm_results.jsonl | VQAGATE（总调度 11-01 定） |
| G28 | P1 | 决策同步残留：D-VQA-01 有 17 处旧口径（只记录 / 标定 0.85 才阻断），另有 7 个必须同步的文件没写新口径；D-VID-01 的 docs/series10_video/STATUS.md 没写 Pika Flex | data/qa/decision_propagation/report.md | VQAGATE / VIDEO10（WORKFLOW） |
| G29 | P1 | 节奏慢的结构性原因：镜数上限 max(8, 说话轮次 + 独白段数) 和总时长 50–75 秒（目标 60–65 秒）放在一起，平均镜长下限就是 60 ÷ 8 = 7.5 秒；单镜 ≤6 秒（K-WRT-005 / K-WRT-Q07）没法全满足（8 × 6 = 48 秒 < 50 秒下限）。现稿 ep03 平均 7.7 秒、ep04 7.6 秒，QW-T1 37 处。二选一：A 上限放宽到 max(8, 轮次 + 独白, ⌈目标秒数 ÷ 6⌉)（60 秒 → 10 镜，出图 / 出片量约 +25%）；B 把每集目标时长降到约 45–50 秒（改集长，要项目方定）。RSI 建议 A。要同步的文件：services/agent/ns_agent/importer/script_md.py shot_cap、tools/pipeline/writer_prompt.py shot_cap / 第 109 行、tools/validate_qwen_script.py QW-E2、tools/validate_script_strict.py、config/script_chat_rules.md §2、docs/production_rules_v3.md K1 | knowledge/rules/writer_iteration.yaml K-WRT-Q07；data/qa/defect_hunt/state.json DH-S05 | 总调度定 → AUTOPILOT（writer_prompt / importer）+ RSI（validate_qwen_script） |
