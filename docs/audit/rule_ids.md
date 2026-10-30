# 逐镜审计规则编号表（rule_ids）

> 维护：**claude-sop**（唯一写入者）。代码（gpu3 `ns-studio/scripts/shot_audit.py`）和文档共用这一张表；新增、修改规则必须先改这里，再改代码。
> 依据：`docs/SOP_production.md` ★1/★3/★5、§6「H3 上游写法」、§8、§9A；`docs/SOP_parameters.md`。
> 版本：`rule_ids/v1`（2026-10-30）。编号一经发布不复用、不改义；规则作废时标“作废”，保留编号。

## 级别说明

- **block**：不通过时 `status.json.audit.verdict = fail`，视频渲染器和调度器硬拦截。只有锁定规则可以设为 block。
- **warn**：记入 `audit.warnings`，不拦截。用于「待验证 / 需 A/B」规则；规则锁定后由 claude-sop 改为 block。
- **override（豁免）**：只能凭项目方原话豁免。写进 `status.json.audit.overrides[{rule_id, owner_quote, by, at}]`；没有原话的豁免一律无效。

`audit.failures[]` 每项格式：`{rule_id, sop_ref, detail}`。其中 `sop_ref` 取下表的“SOP 出处”列。

## H3-A 提示词结构（§9A.1）

| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| H3-A1 | 第一行是官方对齐句，逐字一致；`Shot N` 为最后镜号；`S.SS` = `f"{frames/24:.2f}"`，且与本镜实际帧数一致 | 用正则全文匹配第一行；从文本取出 S.SS，与帧数/24 比对 | block | §9A.1 #1 |
| H3-A2 | 对齐句后恰好空一行；依次是 `integrated_multimodal_description:`、`overall_soundscape:`、`non_diegetic_music:`，字段名逐字一致，各字段之间空一行，没有其它字段 | 解析分段 | block | §9A.1 #2 |
| H3-A3 | 单镜头：正文只有 `[Shot 1]`，`[Shot 1]` 后面不带时间戳 | 统计 `[Shot ` 出现次数；检查时间戳格式 | block | §9A.1 #3 |
| H3-A4 | 正文开头写 “…established by Picture 1”，结尾一句写 “settles into … established by Picture 2 at the end of the shot” | 匹配两个固定短语，并检查结尾短语在最后一句 | block | §9A.1 #4 |
| H3-A5 | 不写否定句、不写禁用清单（cfg 1） | 在 `<d>` 外的英文里找否定词：`\b(no|not|never|without|don't|doesn't|avoid|nothing|none)\b`、`n't`，以及剧本 `负面追加` 或 visual_bible `negative` 原文。`N/A` 字段值除外 | block | §9A.1 #8 |
| H3-A6 | 不复述两张静帧：正文主要写动作路径 | 启发式：正文与首帧/尾帧编译提示词的英文译文 n-gram 重合率 > 阈值时报警（阈值待定） | warn | §9A.1 #5 |
| H3-A7 | 正文是英文：`<d>…</d>` 之外不出现中文字符 | 检查 `<d>` 外是否有 CJK 字符 | block | §9A.1 #7 |
| H3-A8 | `[Shot 1]` 以风格开场：`Live-action, cinematic, shallow depth of field,` | 前缀匹配 | block | §9A.1 #6 |
| H3-A9 | 只写看得见、听得见的内容；不写剧情概述和抽象情绪词 | VLM/LLM 判定（待定） | warn（待验证） | §9A.1 #9 |
| H3-A10 | 运镜写成句子里的自然动作，使用官方词汇和幅度、速度词；每镜一个运镜 | 匹配运镜词表；统计运镜动词个数，>1 时报警 | warn（“一镜一运镜”待验证） | §9A.1 #10、运镜词汇 |
| H3-A11 | 描述的总时长与请求时长一致，时长在 4–15 s 内 | 帧数/24 落在 [4, 15.1] | block | §9A.1 长度 |
| H3-A12 | 提示词总长度 ≤7000 字符 | len() | warn（待验证） | §9A.1 长度 |

## H3-D 对白与人声（§9A.1 对白与人声）

| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| H3-D1 | `<d>` 里只有语言标签和原文：`<d>[Chinese] …</d>` | 用正则检查每个 `<d>` 块 | block | §9A.1 对白 |
| H3-D2 | 每个 `<d>` 前面写说话人编号 `(S1)`、`(S2)`…，按首次开口顺序编号；音色、语气描述写在 `<d>` 外；从不发声的人没有编号 | 检查 `(S\d+(,S\d+)*)` 出现在 `<d>` 之前，且编号递增 | block | §9A.1 对白 |
| H3-D3 | 台词与剧本逐字一致（含标点），条数一致，顺序一致 | 与 script_*.json 本镜对白逐条比对 | block | §9A.1 对白；S1 逐字规则 |
| H3-D4 | 不用双引号包台词；`<d>` 内不写人名 | 检查 `"` `“` `”`；检查人名表 | block | §9A.1 对白；已知坑 |
| H3-D5 | 画外音用 `says in an off-screen voiceover`，`</d>` 后紧跟嘴唇闭合句 | 剧本标“画外”的台词：两个短语都必须出现 | block | §9A.1 对白 |
| H3-D6 | 🎙 内心独白不进 H3 | 独白原文不得出现在提示词里 | block | §9A.1 对白 |
| H3-D7 | 发声人数：亲密镜只让林晚发声（只有 (S1) = 林晚）；普通对话镜暂时允许多人 | adult 镜：编号数 ≤1；soundscape 里不写男声 | 亲密镜 block，其余 warn（待项目方定） | §9A.1 本项目附加规则 |
| H3-D8 | 说话人首次出现时，写清年龄、性别、是否在画面内、音色、语速 | 启发式关键词检查 | warn（待验证） | §9A.1 对白 |
| H3-D9 | `<d>` 前后用 `<cutoff>` / `<scenetrans>` 的情形（片尾截断、跨切） | 剧本标注了才检查 | warn | §9A.1 对白 |

## H3-S 声音字段（§9A.1）

| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| H3-S1 | `overall_soundscape` 写成一段 1–4 句英文；不含 `<d>`，不复述台词 | 分句计数；CJK 检查；`<d>` 检查 | block | §9A.1 soundscape |
| H3-S2 | `overall_soundscape` 不写 `N/A`（除非剧本明确要求全静音） | 值比对 | block | §9A.1 soundscape |
| H3-S3 | `non_diegetic_music: N/A`（本项目固定） | 值比对 | block | §9A.1 music；参数表 |

## P-A 视频模型与采样（§9A.3；SOP_parameters S4）

| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| P-A1 | DiT = `minimax_h3_fl2va_pruned_int8_convrot` | 检查 workflow JSON | block | 参数表 S4 模型 |
| P-A2 | cfg 1，BasicGuider，没有负面条件 | 检查 workflow JSON | block | §9A.3 CFG |
| P-A3 | 加速 LoRA 与 shift 配对：768p 版用 6/3，544p 版用 12/3；不加 LoRA 的基模用 12/3 | 从 workflow 取 LoRA 文件名和 SigmaShift 值 | block（配对规则） | §9A.3 Turbo |
| P-A4 | 加速 LoRA 的版本 = 参数表当前锁定版本 | 文件名比对 | warn（需 A/B） | 参数表 S4 加速 LoRA 版本 |
| P-A5 | 步数：Turbo 8 步；基模 20–25 步 | workflow | block | §9A.3 |
| P-A6 | 采样器 euler、调度器 simple；不用 ancestral/SDE | workflow | 不用 ancestral/SDE 这一条为 block；euler/simple 本身为 warn（待验证） | §9A.3 采样器 |
| P-A7 | 不挂 EasyCache、Spectrum、TeaCache 等缓存节点 | 检查 workflow 里的 class_type | block（SOP 先禁用） | §9A.3 缓存 |
| P-A8 | 使用 `MiniMaxH3AddGuide` 的镜头必须在 shot 上标明理由 | workflow 里有这个节点 → 必须有 reason 字段 | warn（需 A/B） | §9A.3 中间关键帧 |

## P-B 帧与几何（§9A.3）

| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| P-B1 | 帧数在 17k+5 网格上，范围 124–362，并且等于按 `**时长**` 查 §6 对照表得到的值 | 计算 | block | §6 表；§9A.3 |
| P-B2 | 首帧和尾帧上传前都是 768×1344，用同一种 center-crop 方式得到；记录两张图的 sha | 读图检查尺寸；检查 takes 记录里的 crop 方法和 sha | block | §9A.3 首尾帧预裁 |
| P-B3 | 24 fps；输出分辨率 768×1344 | workflow / ffprobe | block | §9A.3 |

## R-C 就绪闸门（★1/★3；AUD §2）

| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| R-C1 | 8 要素齐全：首帧、尾帧、img、motion、时长、sound/【H3 audio】（亲密镜另加 sound_intimate）、本镜配乐 cue、本集 BGM | 字段存在且非空 | block | ★1；AUD §2 |
| R-C2 | 首帧、尾帧、视频同属一条 take 链（同一流水线、同一 takes.json；尾帧由该首帧编辑而来） | 检查 takes 记录的父子关系 | block | ★3；AUD §2.1 |
| R-C3 | S1 已通过：`s1_gate.json` 已 accepted，且与本镜使用的剧本 sha 一致 | sha 比对 | block | ★1 S1；参数表 v3 切换闸门 |
| R-C4 | S2 已通过：本镜用到的触发词 / LoRA 在 LORA_REGISTRY 中都是 `accepted` | 读注册表 | block | ★1 S2 |
| R-C5 | 本镜所在场景的底板为 owner_confirmed（若本镜使用底板） | 读 scenes.json | block | ★1 S2；state_timeline 评审 |
| R-C6 | 帧闸门通过（S3-F 各条） | 汇总 S3-F | block | ★1 S3 |
| R-C7 | 场景内衔接检查通过（与上一镜尾帧比对） | continuity 结果 | block | AUD §3.4 |
| R-C8 | 输入未过期：take 记录的 inputs_sha / bible_version 等于当前值 | sha 比对 | block | ★3 |
| R-C9 | 去重：同一去重键（首帧 sha + 尾帧 sha + 提示词哈希 + 参数）没有已通过的视频 | 查 manifest | block（重复即 skip） | 参数表 S4 去重键 |
| R-C10 | 本集首集样片 G4 已锁定（非首集的镜头必查） | PIPELINE_LOCKED 有 G4 记录 | block | ★3、G4 |

## S1-W 剧本 H3 上游写法（§6）

| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| S1-W1 | motion 是一个连续镜头（无剪辑），只有一个主动作、一个运镜；最后一个“——”之后写结束状态 | 无“切/转场/cut”；找到“——” | block | §6 #1 |
| S1-W2 | `**时长**` 在 5–15 s，可映射到合法帧数 | 解析 | block | §6 #2 |
| S1-W3 | 【H3 audio】是 1–4 句英文 soundscape，不含台词，不含否定句 | 同 H3-S1、H3-A5 | block | §6 #3 |
| S1-W4 | 每句台词标明说话人；台词不被双引号包进 img 或 motion；🎙 独白单独成行 | 解析 | block | §6 #4 |
| S1-W5 | 首尾帧可生成（同景、同光、同服装；姿势可达；景别在一个运镜内） | LLM 判定 | warn | §6 #5 |
| S1-W6 | 运镜可以映射到官方词汇 | 词表映射 | warn | §6 #6 |
| S1-W7 | 每镜都有 `**H3提示词**` 字段（项目方 2026-10-30：剧本本身必须带 H3 官方提示词） | 字段存在且非空 | block | §6 #7 |
| S1-W8 | `**H3提示词**` 本身要通过全部 H3 结构与写法检查：H3-A1–A5、A7、A8、A11（对齐句、字段、单镜头、Picture 2 收敛、无否定、英文正文、风格开场、时长）；H3-D1–D7（`<d>` 对白、逐字、亲密镜只让林晚发声）；H3-S1–S3（soundscape，配乐 N/A）。不另设新编号，失败时按原编号报，sop_ref 写 “§6 #7” | 对剧本字段跑同一套检查 | 同各原规则的级别 | §6 #7；§9A.1 |
| S1-W9 | 出视频用的提示词 = 剧本 `**H3提示词**` 原文；只允许按实际帧数重算 S.SS，改动须留 diff | 文本比对（忽略 S.SS） | block | §6 #7 |

## S3-K 首尾帧（§8）与 S3-F 帧闸门（参数表 S3）

| rule_id | 规则 | 机器检查方法 | 级别 | SOP 出处 |
|---|---|---|---|---|
| S3-K1 | 首帧与尾帧同布景、同光线、同服装和发妆 | VLM 判定（与衔接检查同法） | block | §8 |
| S3-K2 | 人物至少中景、脸要够大；远景标为高风险 | 人脸框高 / 画面高 | warn | §8；§9A.3 失败模式 |
| S3-K3 | 尾帧状态 = motion 结束状态 = 提示词 Picture 2 收敛句所写状态 | LLM 判定 | warn | §8 |
| S3-F1 | 人脸相似度：SFace 与 CM_s1 母版脸部裁切余弦 ≥0.40（侧脸 ≥0.30） | WS 同法 | block | 参数表 S3 |
| S3-F2 | 焦外：背景/主体 Laplacian 比 <1.0（全景、大全景、俯拍豁免） | WS 同法 | block | 参数表 S3 |
| S3-F3 | 林晚发色 HSV 闸门 | WS 同法 | block | 参数表 S3 |
| S3-F4 | 非成人镜头裸露一票否决 | 裸露 QC v3 | block | 参数表 S3 |
| S3-F5 | VLM 逐条核对 Frame Spec 事实 | VLM | block | 参数表 S3 |
| S3-F6 | 同一张图上 LoRA 强度合计 ≤1.6 | 读 take 参数 | block | 参数表 S3 |
| S3-F7 | 色调匹配已执行（0.6；暗场 0.3），并保留原图 | 读 take 参数 | block | 参数表 S3 |
| S3-F8 | 无字幕、无文字（OCR） | owner_script_qc | block | 固定约束 |

## 变更记录

| 日期 | 改动 | 写入者 |
|---|---|---|
| 2026-10-30 | v1 发布 | claude-sop |
| 2026-10-30 | 新增 S1-W7–W9（剧本 `**H3提示词**` 字段，项目方指令） | claude-sop |
