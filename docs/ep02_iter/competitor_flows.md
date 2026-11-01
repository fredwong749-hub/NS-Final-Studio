# 竞品“剧本 → 成片”生产流程研究（COMP，2026-10-31）

项目方原话：“学习小云雀以及其他做 RSI 的公司是如何工作的……做出一个比 Seedance 更强大的、做短剧的 flow system。”

本文只研究**生产流程和系统设计**（数据结构、自动化边界、一致性机制、迭代与质检），不研究 UI 外观（UI 见 `docs/ux_round5/C_research.md`、`docs/canvas_research_v3.md`）。小云雀现场流程已在 `docs/xyq_walkthrough.md`、`docs/xyq_flow_full.md` 实测记录，本文直接引用其结论，标“XYQ 实测”。Seedance 模型层机制（首尾帧掩码、MM-RoPE 多镜头）已在 `docs/research/seedance_consistency.md`，本文只补流程层。

**方法与限制**
- 逐一抓取官方文档、官方博客、arXiv、GitHub README 和媒体实测。引文是原文短句（中文 <15 字，英文 <15 词），经 WebFetch 抽取；个别标“转述”的是概括不是原话。
- 置信度：**高** = 官方文档/论文正文/README 原文；**中** = 官方营销页、媒体实测；**低** = 搜索摘要、第三方 API 平台、聚合站，或我的推断。
- 本次**没有**打开 :9471 Chrome：本地两份 XYQ 实测文档已覆盖小云雀全流程（到“立即生成”前一步），再进现场的边际信息少、风险（分集编辑器自动保存）不值得。没登录、没付费、没点任何生成。
- 抓取失败：LTX 博客（header overflow）、Vidu 开放平台文档（Document not found）、今日头条教程（正文为空）、Seedance 2.0 arXiv HTML（404，只读到摘要）。这几处只用到能确认的部分。
- 国内 AI 短剧公司**没有**找到公开的、带抽卡率/返工率/质检细节的一手管线分享；只有媒体口径的成本和周期数字（§1.12）。

---

## 0. 结论先行（8 句）

1. **所有做得好的产品都是同一条骨架**：剧本全局解析 → 资产库（角色×造型、场景×子场景，带“出现集数”）→ 分镜脚本（Agent 自动拆，人改）→ 按“片段”出视频（参考图自动带入）→ 片段级重拍 → 整集配乐/字幕/合成。差别只在每一步是“模型能力”还是“流程工具”在扛。
2. **Seedance 系真正领先的是模型层的三件事**：一次生成里原生多镜头切换（15 s 内 2–3 镜）、音画同生（对白+音效+配乐，立体声多轨）、大参考容量（2.0：9 图/3 视频/3 音频；2.5：30 图/10 视频/10 音频，4–30 s）。这三件我们靠流程追不平，只能用 H3 Ref2VA（同构接口，9 图/3 视频/3 音频）逼近。
3. **小云雀/即梦的流程层优势全部可以本地复刻**，而且我们能做得更严：资产按造型/子场景建模、每片段自动带参考、智能预演（先出整组分镜图再出视频）、片段重拍（只重做选中时间段）、草稿档→成片档（Seedance 2.5 `draft` 480p → 用草稿 ID 出正片）、整集配乐与多轨合成。
4. **开源 agent 的共同做法**：先出关键图再出视频；关键图 best-of-k + VLM 打分挑选（ViMax 默认 k=2）；按“机位依赖图”拓扑排序、无依赖的并行（ViMax）；视觉 QC 低于阈值自动重出 + 发布闸门（wind-comic）；上游改动只把受影响的下游标脏（drama-series-agent，且它用的就是本地 ComfyUI + MiniMax H3 Ref2VA，和我们同栈）。
5. **一致性方面，各家没有魔法**：主体库 = 2–4 张图（可灵）/ 1–15 张图（Vidu Q4）/ 4 张图（Higgsfield Popcorn）+ 文字描述 + 可选音色。我们的独有优势是**可以训练角色 LoRA + 跑人脸相似度闸门**，SaaS 用户做不到。
6. **音色锁定已成标配**：可灵主体绑 5–30 s 音频，Vidu Q4 0–3 段音色，Seedance 2.5 “角色 2 的音色为音频 1”，小云雀在资产库改音色全剧同步。我们目前没有用 H3 `ref_audios`。
7. **人在环节，各家都把人放在三个点**：剧本概要/分集大纲确认、资产图确认（定妆）、片段成片后重拍。分镜脚本基本全自动（即梦“几乎不需要用户自己写”）。我们额外有首帧/尾帧定稿关口（C3，项目方要求保留），这是我们比 Seedance 系慢的主因，但也是可控性来源——要做的是把它批量化、预演化，而不是删掉。
8. **“比 Seedance 更强”的可行路径**：不是单段画质（模型差距在），而是**确定性 + 可追溯 + 自动质检 + 无限本地抽卡 + LoRA 身份**。也就是：Shot Spec 单一事实来源 + 配方引擎按镜头类型选工作流 + 草稿档大批量抽卡 + VLM/人脸/ASR 自动挑选 + 只把最好的给项目方看。

---

## 1. 各家流程图（ASCII）

### 1.1 小云雀 · 短剧 Agent（字节，底层 Seedance 2.0/2.5）

```
剧本（上传 txt/docx ≤10 万字，或 Agent 从设定生成 → 剧本概要让人确认）
  │  全局设置：项目名 / 风格（风格词作为前缀加到每次生成）/ 比例
  ▼
剧本分析（按集，5 积分/100 字）→ 角色、造型（不同时期形象）、场景、子场景，每个映射“出现集数”
  ▼
资产库（列表/画布）：每造型一张全身白底立绘 + 结构化外观描述 + 音色
  │  人：确认/改描述重出/上传自有图；“下一步”时缺图只提示“仍要继续”
  ▼
分集视频 → 选规划方式（15 s 上限/片段 或 30 s，选后不可改）→ 生成分镜脚本（Agent，按集计费）
  ▼
故事板：片段卡 = 结构化提示词（场景锚定句 + N 个分镜各写时长/景别/机位/@角色·造型/动作/声音）
  │  可选：智能预演（≥2 片段，参考 ≤9 个素材）→ 先出整组分镜图插回片段，人看绿点确认
  ▼
立即生成（R2V，无首尾帧定稿；Seedance 一次生成内切 2–3 镜，音画同生）
  ▼
片段重拍（选时间段 + 帧注释 + 写“改什么/保留什么”，按所选时长计费）/ 抽卡重出
  ▼
生成配乐 · 添加字幕 · 多轨编辑器 → 合成 → 导出全集
```

| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 剧本上限 | “最长支持10万字” | https://www.xiaoyunque.com/tutorials/web-manual | 高 |
| 资产改动全剧同步 | “一键同步更新” | 同上 | 高（官方说法，同步是否重出未验证） |
| 片段级局部重做 | “片段重拍” | 同上；https://www.xiaoyunque.com/tutorials/seedance-2-5 | 高 |
| 预演的目的 | “降低抽卡率” | https://www.xiaoyunque.com/tutorials/short-drama-agent-smart-preview | 高 |
| 规划方式 15 s/30 s 选定后不能改；片段内 2–3 分镜各标时长；对白写进视频提示词 | XYQ 实测（21_gen_script_click.png、23_editor.png） | docs/xyq_flow_full.md | 高（亲见） |
| 分镜阶段可配“技能”（自定义规则和输出格式） | XYQ 实测（20_skill_settings.png） | docs/xyq_flow_full.md | 高 |
| 首尾帧：故事板里没有首尾帧定稿层 | XYQ 实测 | docs/xyq_walkthrough.md | 高 |
| Seedance 2.5 单次 4–30 s、1080p，480p 低成本迭代再超分 | 转述 | https://www.xiaoyunque.com/tutorials/seedance-2-5 | 高 |
| 参考上限 30 图/10 视频/10 音频；图片参考 1–8 个主体最稳 | 转述 | 同上 | 高 |
| 音色按参考绑定 | “角色 2 的音色为音频 1” | 同上 | 高 |
| 分轨否定 | “无 BGM” | 同上 | 高 |
| R2V 指定首尾帧 | “图片 1 为首帧” | 同上 | 高 |
| 重拍一次只改一件事 | 转述（“只改表情或只改动作更稳”） | 同上 | 高 |

### 1.2 即梦 · 短剧工作室（2026-10-26 上线，DreamShot 分镜模型）

```
起点（一句话 / 改编小说或 IP / 上传剧本）→ Agent 给三种角度（剧情流/情感流/升级流）+ 卖点标签 → 人选
  ▼ 三步生成：故事设定 → 分集大纲 → 单集剧本（人逐层改）
资产：自动拆角色（按剧情阶段拆多形象）+ 场景，系统写好资产图提示词 → 人确认/改/补表情、三视图
  ▼
分镜：DreamShot 自动切分整理（画布/故事板双模式，3D 导演台摆机位）
  ▼
视频（Seedance 1.5 Pro / 2.x，音画一体）→ 智能预演串起整组分镜检查
  ▼
后期：对话改（Agent 自动生成过渡片段插入）、单镜定点重拍、人声/背景分离、重新配音
```

| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 分镜自动化程度 | “几乎不需要用户自己写” | https://www.woshipm.com/ai/6485581.html | 中（媒体实测） |
| 1.7 万字剧本拆出 7 角色 20 场景，同角色多形象 | 转述 | 同上 | 中 |
| 修缝：Agent 生成四段约 4 秒过渡视频插入 | 转述 | 同上 | 中 |
| 串联剧本/资产/分镜/视频/后期 | 转述 | https://ithome.com/1/018/013.htm | 中 |
| 自研分镜模型 DreamShot；后期智能切镜 | 搜索摘要 | https://www.pingwest.com/a/318850 | 低 |
| 单镜头定点重拍、人声背景分离、重新配音 | 搜索摘要 | https://m.sohu.com/a/974402014_122563727 | 低 |

### 1.3 Seedance 2.0 / 2.5（火山方舟 API，模型能力本身）

```
一次调用 = 一个“片段”
  输入：文本（可写分镜/时间戳 [1s-4s]）+ 参考图(2.0:≤9 / 2.5:≤30) + 参考视频 + 参考音频
  模式（互斥）：首帧 / 首尾帧 / 全能参考（task_type: reference | edit | extend）
  ├─ draft=true（仅 2.5，480p 样片，草稿 ID 7–14 天有效）── 满意 ──▶ 用草稿 ID 出正片
  ├─ generate_audio=true（默认）对白+音效+配乐同生
  ├─ return_last_frame=true → 拿尾帧接下一片段
  └─ priority 0–9；service_tier flex（离线，半价，2.x 不支持）
输出：4–15 s（2.0）/ 4–30 s（2.5），480p–1080p（2.0 基础版到 4K）
```

| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 多镜头音画 | “15-second high-quality multi-shot audio-video output” | https://seed.bytedance.com/en/blog/seedance-2-0-正式发布 | 高 |
| 参考容量 | “9 images, 3 video clips, 3 audio clips” | 同上；https://arxiv.org/abs/2604.14148 | 高 |
| 音画同生架构 | “unified multimodal audio-video joint generation architecture” | 同上 | 高 |
| 官方自认短板 | “detail stability, hyper-realism, and dynamic vitality” | 同上 | 高 |
| 草稿档 | 参数 `draft`，480p only，草稿 ID 可用于出正片（转述） | https://docs.volcengine.com/docs/82379/1520757 | 高 |
| 尾帧回传 | 参数 `return_last_frame` | 同上 | 高 |
| 2.5 时长/参考 | duration 4–30；reference_image 1–30 | 同上 | 高 |
| 对白写法 | 对白放双引号（转述） | 同上 | 高 |
| 原生输出 | 2.0 “480p and 720p”（摘要） | https://arxiv.org/abs/2604.14148 | 高 |

### 1.4 可灵 Kling 3.0（多镜头 + 主体库 Element Library 3）

```
主体库：建主体（主图 + 1–3 张补充图，或 3–8 s 单人视频）+ 名称/描述 + 绑定音色（5–30 s 音频/音色库/无声）
  类型：角色/动物/道具/服装配饰/场景/特效/其他
  ▼
视频 3.0：Multi-Shot 开关
  ├─ 自动：模型自己规划镜头数、景别、机位（时长 “Calculated by AI”）
  └─ 自定义：≤6 镜，每镜填 时长 / 景别机位 / 叙事内容(动作+对白) / 运镜，总长 3–15 s
  + 首尾帧 + 最多 3 个主体（主体须出现在参考帧里）；Omni：无视频输入时最多 7 个主体
  ▼ 原生音频（中英日韩西 + 方言/口音标签），3+ 角色对白共指
```

| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 镜头上限 | “Up to 6 shots” | https://kling.ai/blog/kling-video-3-multi-shot-guide | 高 |
| 每镜字段 | “Framing and Perspective” / “Narrative Content” / “Camera Movement” | 同上 | 高 |
| 视频主体 | “a 3–8s video clip of a single character” | https://kling.ai/quickstart/klingai-element-library-3-user-guide | 高 |
| 音色跟随主体 | “follows the character consistently” | 同上 | 高（厂商说法） |
| 主图建议正脸 | “uploading a front-facing image for higher consistency” | 同上 | 高 |
| 首帧+主体解决转角度变形 | “subjects losing their shape” | 同上 | 高 |
| 3+ 角色对白 | “Multi-Character Coreference (3+)” | https://kling.ai/quickstart/klingai-video-3-model-user-guide | 高 |
| 绑定音色后提示词不再写音色 | 转述 | 同上 | 高 |
| 时长 | “a flexible duration ranging from 3 to 15 seconds” | 同上 | 高 |

### 1.5 Vidu Q4（参考生视频）

```
1–15 张参考图（人物/场景/画风任意组合）+ 0–3 段音色 → 单次 ≤16 s 多镜头叙事，音画同出，2K/4K
```

| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 参考图 | “1~15 张图自由组合” | https://www.vidu.com/zh/vidu-q4 | 中（官方营销页） |
| 音色 | “0~3 段音色复刻角色声音” | 同上 | 中 |
| 切镜 | “运镜切镜丝滑不跳切” | 同上 | 中 |
| 音画 | “音画同步输出” | 同上 | 中 |
| Q2 参考生视频最多 3 个主体 | 搜索摘要（Comfy 节点页） | https://comfy.org/zh/workflows/api_vidu_q2_r2v-c1956ef24421/ | 低 |

### 1.6 海螺 / MiniMax（Hailuo Video Agent，H3 是同家模型）

```
Video Agent：模板化多步（脚本 → 图 → 视频 → 配音 Speech 2.5），S2V 主体参考保持跨镜外观
```
| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| S2V 用参考图保持角色跨镜一致 | 搜索摘要 | https://help.scenario.com/en/articles/minimax-hailuo-video-the-essentials | 低 |
| Agent 可调 Hailuo 2.3/02、Speech 2.5 | 搜索摘要 | https://useapi.net/docs/api-minimax-v1/post-minimax-agent | 低 |
| **没找到**：海螺官方的短剧模板、多镜头流程、音色绑定文档 | — | — | — |

我们本地用的 MiniMax H3（FL2VA / Ref2VA）官方短片管线已在 `refactor_proposal.md §7` 吸收，不重复。

### 1.7 LTX Studio

```
一句话或剧本 → 拆 Scenes/Shots（先看镜头数和每镜文字）→ 自动抽取 Elements（角色/物件/地点）
  → 分镜帧（FLUX / Nano Banana）→ 动态分镜（可导出 MP4 animatic + PDF pitch deck）→ 出视频
  → 对白：音色挂在角色 Element 上，按说话人标注；多说话人逐个口型同步
```
| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 自动抽元素 | “Review automatically extracted characters, objects, and locations as Elements” | https://website.ltx.studio/studio/platform/ai-storyboard-generator | 中（营销页） |
| animatic 导出 | “exported as MP4 files” | 同上 | 中 |
| 三层定制 | “project, board, and frame levels” | 同上 | 中 |
| 音色挂角色、逐说话人口型 | 搜索摘要 | https://ltx.io/blog/how-to-add-ai-voiceovers-dialogue-to-videos | 低（正文抓取失败） |

### 1.8 Higgsfield（Soul ID → Popcorn → Cinema Studio → Seed Audio → Supercomputer）

```
剧本拆解（2 分钟短片约 15–25 镜，标每镜角色/地点）
  → Soul ID（20+ 张照片训练持久人脸）
  → Popcorn：每场戏一次生成 4/6/8 帧分镜（≤4 张参考，“图一的人在图三的地点”），单帧可改
  → Cinema Studio：每镜显式参数（类型/光/色/机身/镜头/焦距/光圈），以 Popcorn 帧 + Soul ID 为输入
  → Seed Audio：按场生成对白/环境/配乐
  → Supercomputer：持有镜头表和装配顺序，剩余镜头并行，合成
```
| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 先分镜后视频的理由 | “Fixing blocking after shots are already generated means regenerating” | https://higgsfield.ai/blog/ai-short-film-pipeline | 中（官方博客） |
| 先出最难的一镜 | 转述（最难镜成立，其余通常也成立） | 同上 | 中 |
| 每场锁一次光与镜头 | “Lock genre, lighting, and lens settings once per scene” | 同上 | 中 |
| 长镜退化 | “Identity and lighting consistency degrade past 30 seconds” | 同上 | 中 |
| Popcorn 序列 | “coherent sequences of up to 8 frames” | https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-popcorn | 高（帮助中心） |
| 重出时改文字不重传参考，避免外观重置 | 转述 | 同上 | 高 |

### 1.9 OpenArt（One-Click Story → Director）

```
One-Click Story：模板（角色 Vlog/MV/讲解）+ 角色图 + 一句话 → 约 1 分钟成片 → 故事板模式逐片段改提示词
Director（2026-06-23）：对话“vibe directing” → 结构/角色/风格 → 画面+对白+音乐+音效一起生成 → 逐场对话迭代，≤5 分钟
```
| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 输入到 1 分钟片 | 转述 | https://techcrunch.com/?p=3035461 | 中 |
| 音画一起出 | “而非事后再剪辑合成” | https://openart.ai/zh-cn/blog/openart-director-press-release/ | 中（官方新闻稿） |
| 逐场迭代 | “一个场景接一个场景” | 同上 | 中 |
| 一致性靠 Flux Kontext，参考从 10–20 张降到 1 张 | 搜索摘要 | https://bfl.ai/blog/openart-with-flux1-kontext | 低 |

### 1.10 开源 agent

**ViMax（HKUDS，arXiv 2606.07649）**
```
Idea/Script/Novel → 编剧 → 分镜 agent（每镜：机位、运动、光、站位、时长 + 画面/音效/对白）
  → 关键图（角色设定 → 场景背景 → 镜头关键帧，后者以前者为参考）
     每个任务并行采样 k 个候选 → VLM 按“画面保真/叙事一致/符合分镜”打分 → 取最高
  → 机位依赖图：同场景同角色的不同机位连边；按拓扑序生成，无依赖并行，依赖方继承前驱的视觉锚
  → 机位间过渡视频作“空间锚” → 视频 → 合成；支持断点续跑、渲染检查点
```
| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 依赖图 | “camera dependency graph” | https://arxiv.org/html/2606.07649v2 §2.3.1 | 高 |
| 评分维度 | “visual fidelity, narrative consistency, and shot specification adherence” | 同上 §2.1.2 | 高 |
| k=2 默认；k 更高成本升、全局一致性反降 | 转述 §3.7 | 同上 | 高 |
| 全并行最快但一致性最低 | 转述 §3.5 | 同上 | 高 |
| 发布说明：重试、持久渲染状态、检查点、续跑 | “render checkpoints” | https://github.com/HKUDS/ViMax | 高 |

**MovieAgent（showlab，arXiv 2503.07314）**：导演/编剧/分镜师/场务四个 LLM 角色，层级 CoT 规划场景→机位；输入=剧本+角色库。摘要未写 QC 循环。https://arxiv.org/abs/2503.07314 ｜高（仅摘要层面）

**drama-series-agent（binwu1，与我们同栈）**
```
develop（世界观/角色/画风/分集图）→ write（按 skills 写单集）→ cast（角色立绘 + 可选音色参考，绑定镜头任务表）
  → render：生成 episode-run.jsonl → 本地 ComfyUI MiniMax H3 Ref2VA（fast/lora/turbo/quality 四档）
     → 每镜结束 ffmpeg 抽尾帧接下一镜首帧 → 拼 master.mp4
  设定或剧本改动 → 只把受影响的下游标为需重跑；Jobs 页断点续跑
```
| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 尾帧接续 | “Prev-shot tail → next first frame” | https://github.com/binwu1/drama-series-agent | 高（README） |
| 同栈 | H3 Ref2VA 工作流，四档质量 | 同上 | 高 |

**wind-comic（ChrisChen667788）**：最完整的“视觉 QC 自愈”设计。
| 要点 | 原文短引 | 链接 | 置信度 |
|---|---|---|---|
| 身份锁 | “8-field DNA identity lock” | https://github.com/ChrisChen667788/wind-comic | 高（README，阈值无校准数据） |
| 自动重出阈值 | “if a shot's character match scores <75” | 同上 | 高 |
| 发布闸门 | “four-dimension publish gate”（画面对剧本/一致性/口型可对齐性/实测嘴-音对齐） | 同上 | 高 |
| 并发越高尾帧链越弱 | 转述 | 同上 | 高 |
| 框选坏段只重拍该段；首次采用保留原版可回滚 | 转述 | 同上 | 高 |

**Toonflow（HBAI-Ltd，约 2 万星）**：无限画布，文本节点（故事/人设/镜头描述）→ 图节点 → “按镜头生成视频片段”；README 未写一致性机制和 QC。https://github.com/HBAI-Ltd/Toonflow-app ｜高

### 1.11 小结：两种主流“渲染单元”

| 单元 | 谁在用 | 优点 | 缺点 |
|---|---|---|---|
| **片段**（10–15 s，内含 2–6 个分镜，一次生成内切镜） | 小云雀、即梦、可灵 Multi-Shot、Vidu Q4、Seedance | 镜间连贯由模型保证；对白跨镜连续；点击少 | 片段内无法单镜替换（只能“片段重拍”选时间段）；无首尾帧可控性 |
| **单镜**（首帧/关键帧 → 视频，镜间靠参考/尾帧） | 我们、ViMax、Higgsfield、drama-series-agent、wind-comic | 每镜可控、可单独重出、可锁首帧构图 | 镜间连贯靠流程（参考、尾帧、锚点）；人审关口多 |

### 1.12 国内 AI 短剧公司（只有媒体口径数字，没有管线细节）

| 公司/平台 | 公开信息 | 链接 | 置信度 |
|---|---|---|---|
| 昆仑万维 SkyProduction | 整合 SkyReels、Seedance、可灵，“剧本直达成片” | https://m.huxiu.com/article/4895398.html | 中 |
| 万兴剧厂 | 集成 Seedance 2.0、Kling 3.0、Vidu Q3；含成本核算 | 同上 | 中 |
| 中文在线次元神笔 | 剧本拆解→角色场景建模→分镜→生图生视频→后期；单集耗时约降 50%（自述） | 同上 | 中 |
| 山海星辰 NOVA AI | 团队 20–40 人 → 5–10 人，周期 25–40 天 → 7–10 天（自述） | 同上 | 中 |
| 行业 | AI 真人短剧每分钟成本 4000–5000 元 → 约 1000 元（媒体） | 同上 | 中 |
| 通用经验 | 定妆先行，“先定妆，再锁Seed，最后训练专属LoRA”；单镜 3–6 s 最稳 | https://www.zhihu.com/question/2069389637840385255 等教程（搜索摘要） | 低 |

**没找到**：任何公司公开的抽卡率、返工率、质检阈值、人审节点数。别凭此推断行业水平。

---

## 2. 能力对比矩阵（7 项 × 各家 vs 我们现状）

“我们现状”依据：`docs/ep02_iter/chain_audit.md` §0.1、`LEARNED_SPECS.md`、`h3_comfy_expert.md`、`refactor_proposal.md`。

### ① 剧本 → 分镜（自动化与结构）

| | 结构/字段 | 自动化 | 时长/节奏 |
|---|---|---|---|
| 小云雀 | 片段卡：场景锚定句 + N 分镜（时长、景别、机位、左右构图、@角色·造型 + 动作、运镜、声音）；分镜阶段可配“技能” | Agent 按集出分镜脚本，人改 | 规划方式 15 s/30 s 上限，选后锁定 |
| 即梦 | DreamShot 自动切分 | “几乎不需要用户自己写” | 未公开 |
| 可灵 | 每镜：时长/景别机位/叙事内容/运镜 | 自动或自定义 | ≤6 镜，总 3–15 s |
| ViMax | 机位、运动、光、站位、时长 + 画面/音效/对白 | 全自动 | — |
| Higgsfield | 镜头表 + 每镜显式摄影参数 | 半自动 | 2 分钟约 15–25 镜 |
| **我们** | 写作模型（外部 API 网关）出镜头：img / 尾帧 / motion / H3 正文 / 台词；编译器靠关键词猜在画角色（chain_audit A4） | 拆镜由写作方做；编译确定性但依赖运行环境 | 每镜单独时长；无片段层；无模型能力约束 |

### ② 角色/场景一致性

| | 机制 | 参考数量 | 跨镜锁定 |
|---|---|---|---|
| 小云雀 | 角色×造型、场景×子场景资产；立绘 + 结构化描述；@ 引用自动带图 | Seedance 2.5 最多 30 图 | 每片段固定一张子场景图 + 造型立绘 |
| 可灵 | 主体 2–4 图或 3–8 s 视频 + 音色 | 3.0 首尾帧 +3 主体；Omni 7 | 首帧 + 主体绑定 |
| Vidu Q4 | 参考图任意组合 | 1–15 图 + 0–3 音色 | 参考图 |
| Higgsfield | Soul ID（20+ 照片训练）+ Popcorn ≤4 参考 | — | 每场一次出全部分镜帧 |
| wind-comic | 多视图 + 8 字段 DNA + 风格帧 sref + 人脸分 <75 自动重出 | — | DNA 文本注入每镜 |
| **我们** | 林晚：图像 LoRA + 母版脸；首帧纯文生图**无参考图**；男角色无身份参考（C1）；人脸 SFace 闸门 ≥0.30 | FL2VA 只吃首尾帧；Ref2VA（9 图）未进生产 | 尾帧由定稿首帧 Qwen-Edit 来；镜间无锚 |

### ③ 多镜头连贯

| | 做法 |
|---|---|
| Seedance 系/可灵/Vidu | 模型一次生成内切镜（片段内连贯由注意力共享保证）；片段间靠 `return_last_frame`、续写/延长、截帧做下一片段参考 |
| 小云雀 | 片段内 2–3 镜；建议截上一镜首/尾帧做下一镜参考；智能预演先统一规划整组分镜图 |
| 即梦 | Agent 自动生成过渡片段插入修缝 |
| ViMax | 机位依赖图 + 前驱视觉锚 + 机位间过渡视频 |
| drama-series-agent / wind-comic | 尾帧接首帧链（wind-comic 自承并发越高越弱） |
| Higgsfield | 每场 Popcorn 一次出全部帧；每场锁光与镜头；>30 s 退化，按首尾帧拼 |
| **我们** | 镜内首尾帧硬钉；镜间无显式衔接字段（ep02 S6→S7 左右互换、S5 换鞋，refactor §7.1 已提 continuity 列）；不做合镜 |

### ④ 音画

| | 对白/口型 | 音色锁定 | BGM/音效 |
|---|---|---|---|
| Seedance 2.x | 同生，立体声多轨；对白放双引号；方言 | 2.5：“角色 N 的音色为音频 N” | 同生；可分轨否定“无 BGM” |
| 可灵 3.0 | 原生，5 语种 + 方言口音；3+ 角色共指 | 主体绑定 5–30 s 音频 | 原生 |
| Vidu Q4 | 音画同出 | 0–3 段音色 | 同出 |
| 小云雀 | 写进片段提示词；独白写“在心里想”+“不说话” | 资产库改音色全剧同步 | 整集“生成配乐”+字幕+多轨 |
| 即梦 | 同生；后期人声/背景分离、重新配音 | 未公开 | — |
| Higgsfield | Seed Audio 按场出 | — | 按场 |
| wind-comic | TTS → viseme → 嘴-音对齐分 → 漂移修正；口型模型外挂 | 每角色路由 | — |
| **我们** | H3 原声对白（嘴部相关 0.19–0.70，优于 TTS）；独白 TTS；ASR-CER 待接 | **未用 H3 ref_audios** | 整集 BGM（ep02 全部 drop，D4/D5 待修） |

### ⑤ 人在环节

| | 人挑/人改的点 | 自动的点 |
|---|---|---|
| 小云雀 | 剧本概要、资产图、分镜脚本可改、预演分镜图（绿点）、片段成片、重拍 | 剧本分析、资产拆解、分镜脚本、参考自动带入 |
| 即梦 | 角度三选一、设定/大纲/单集逐层、资产确认 | 分镜几乎全自动 |
| ViMax | Agent Loop/TUI 审文本产物 | 关键图 VLM 挑选 |
| wind-comic | 导演台、框选坏段重拍、闸门 override（显式记录） | <70/<75 自动重出 |
| **我们** | 项目方：定妆、首帧定稿、尾帧定稿、视频通过（每镜约 4 次，XYQ 改后）；剧本归写作方 | 编译、出图出视频、QC 部分；auto_lock 曾越权定稿（需撤销决策） |

### ⑥ 迭代速度

| | 并行 | 草稿 → 成片 | 局部重出 |
|---|---|---|---|
| Seedance 2.5 | 云端并发，priority 0–9 | `draft` 480p → 草稿 ID 出正片；480p 迭代再超分 4K | edit / extend；片段重拍按选中时长计费 |
| 小云雀 | 多选批量出片段、批量多集 | 480p 迭代 → 超分 | 片段重拍；资产节点“+”出变体 |
| ViMax | 依赖图拓扑并行；候选并行 | — | 检查点续跑 |
| Higgsfield | 剩余镜头并行 | 分镜帧当草稿（改分镜不花视频钱） | 单帧改 |
| **我们** | 3090 多卡、按阶段严格优先；首帧约 70 s、视频约 12 min/镜 | **无草稿档**（两段式 0.5 MP 未用过） | 只能整镜重出；作业状态活在 API 进程里（E6） |

### ⑦ 质检与失败处理

| | 质检 | 失败处理 |
|---|---|---|
| Seedance/小云雀 | 未公开自动质检；靠人看 + 抽卡 | 抽卡重出；片段重拍；预演降低抽卡率 |
| ViMax | VLM 打分挑关键图；ViCLIP 指标 | 更强 LLM 重试、持久渲染状态、续跑 |
| wind-comic | 分镜审 <70、风格审 <70、人脸 <75、口型自愈、四维发布闸门、节奏闸门（默认只警告） | 自动重出 + 人工 override 留痕 |
| H3 官方 skills | QC 清单 + 三级 fallback（已吸收到 refactor §7.3/7.4） | — |
| **我们** | 静止帧、4 帧一顿、泛红、SFace、近黑（LEARNED_SPECS A 组，确认）；OCR/ASR/VLM 待接（P5） | 每镜 ≤3 次再标待项目方；fallback 阶梯已设计未实现 |

---

## 3. Seedance 系的强项，我们能否追平/超越

| Seedance 系强项 | 靠什么 | 我们能否追平 | 路径（模型 / 流程） |
|---|---|---|---|
| 一次生成内多镜头切换、镜间自然 | **模型**（MM-RoPE 交错文本 + 剪辑数据训练） | 部分 | 模型：H3 单次 124–362 帧（约 5–15 s），可在一条 H3 正文里写 2–3 个镜头试“合镜”（未验证 H3 是否会切镜，需 A/B）。流程：做不到就用“同场景锚 + Ref2VA 同组参考 + 尾帧仅用于连续动作”逼近 |
| 音画同生、多说话人、立体声 | **模型** | 基本追平单说话人 | H3 本身就是音画联合（32 kHz 立体声）；差距在多说话人和口型精度。流程：一镜一说话人（写作规则）、ASR-CER 闸门、只重做音频轨（latent 噪声掩码音频通道，h3_comfy_expert §5） |
| 参考容量 9–30 图 + 音色 | 模型 | 追平 2.0 | H3 Ref2VA 同为 9 图/3 视频/3 音频，`<Picture N>` 编号（seedance_consistency §2）；需要把首帧锁构图的 AddGuide multiframe 跑通（E5） |
| 1080p/4K、4–30 s | 模型 + 超分 | 分辨率可追平，时长不能 | 768p → 两段式 + 3D latent 上采样 / 4K 超分（upscale_4k.md）；时长上限 15 s，长镜拆镜 |
| 草稿档 → 正片 | 流程 + 模型 | **能超越** | 本地无计费：0.5 MP 第一段定运动（两段式前半）当草稿，k 个草稿并行 → 自动 QC 挑 → 只对胜者跑第二段。Seedance 草稿也要钱，我们只花电 |
| 资产拆解、造型/子场景、自动带参考 | 流程 | **能超越** | Shot Spec 注册表 + 造型带出现集数 + 编译器按 characters_on_screen 自动注入参考；再加 LoRA（SaaS 用户没有） |
| 智能预演（先出整组分镜图） | 流程 | **能超越** | 我们本来就出首帧：改成“整场一次出全部首帧 + 场景母版统一光线”，人按场批量定稿 |
| 片段重拍（时间段局部重做） | 模型（edit） | 部分 | H3 v2v 低 denoise（0.15）+ 时间掩码；音频轨单独重做；FaceRefine 裁脸重绘（h3_comfy_expert §5） |
| 一致性 | 模型 + 资产 | **能超越** | 角色图像 LoRA + 视频 LoRA + Ref2VA + SFace 闸门 + best-of-k，SaaS 只能靠参考图 |
| 无内容限制的成人镜头 | — | **只能本地** | 记忆规则：成人镜头只本地生成；Seedance 系不可用（小云雀出片前还有“安全确认”框） |
| 可复现、可追溯 | — | **能超越** | RenderPlan + plan_hash + replay（refactor §3.3）；云端 seed 不可控（2.x 无 seed 参数） |

**一句话**：模型层（多镜头切换、多说话人口型、30 s 长镜、原生 1080p）我们追不平；流程层（资产、预演、草稿、自动挑选、追溯、身份 LoRA、无限抽卡）我们可以全面超越。“比 Seedance 强”= 用流程把本地模型的每一次输出都榨到最好，并且只把通过自动质检的结果交给项目方。

---

## 4. 对重构的 15 条建议

标注说明：**RP** = `docs/ep02_iter/refactor_proposal.md` 对应章节/阶段；**RE** = 配方引擎 `services/recipes`（`ns_recipes/selector.py`、`recipes/*.yaml`）；**UI** = `apps/web/src/v3`。已在 RP 里写过的不再重复提，只提增量。

| # | 建议 | 依据（竞品） | 对应 |
|---|---|---|---|
| 1 | **Shot Spec 上加“片段/场”层**：`clip: {id, shots:[...], render_unit: shot\|clip, max_s}`。默认 shot（保留首尾帧），允许把同场连续 2–3 镜标成 clip 用一次 H3 生成（合镜），做 A/B | 小云雀片段=2–3 分镜；可灵 ≤6 镜；Seedance 原生多镜头 | RP §2 schema、P1；RE 新配方 `multi_shot_clip.yaml`；UI 审片行可折叠成片段行 |
| 2 | **模型能力档案（capability profile）进配方引擎**：每个配方声明 `max_s`、帧网格、参考上限（图/视频/音频）、是否锁首帧、是否出音频；写作方拆镜前拿到档案，导入时校验 | 小云雀“规划方式 15 s/30 s 选后不可改”；Seedance 各型号时长/参考上限不同 | RE `registry.py` 增字段；RP §3.2 LLM 约束输入；P1 资料闸门 |
| 3 | **按场预演**：整场所有镜头的首帧在一个作业里出（同一场景母版 + 同光线基线 + 同组角色参考），项目方按场批量看、批量定稿，再进尾帧/视频 | 小云雀智能预演（“降低抽卡率”）；Higgsfield Popcorn 一场一次出 4–8 帧；ViMax 先关键图 | RP P2 编译器产出 scene batch；作业队列 P3；UI 片段条“按场定稿” |
| 4 | **草稿档 → 成片档两段式**：草稿 = H3 0.5 MP 第一段（定构图运动，含音频），k 个并行；胜者才跑第二段 3D latent 上采样 + 精修。RenderPlan 记 `tier: draft\|final` 和父草稿 id | Seedance 2.5 `draft` → 草稿 ID 出正片；小云雀 480p 迭代再超分 | RE 每配方拆 draft/final 两节；RP §3.3 provenance 父子关系；P3 |
| 5 | **best-of-k + 自动挑选**：首帧与草稿视频都并行出 k 个（默认 k=2，按 GPU 空闲加），用 SFace + 泛红/静止/近黑 + VLM “符合 Shot Spec must 事实”打分，自动选最高的给项目方；其余保留可换 | ViMax k=2 VLM 挑选（且 k 过大反降一致性）；wind-comic 阈值自动重出 | RP P5 QC 改为“排序器”而不只是闸门；UI 审片行显示“k 选 1 · 分数”，⋯ 里可换候选 |
| 6 | **镜间依赖图 + 拓扑调度**：Spec 的 `continuity.from_prev` 为 continuous 的边才用尾帧接续，其余镜回锚场景母版；无依赖的镜并行，依赖镜等前驱定稿 | ViMax 机位依赖图（全并行最快但一致性最低）；wind-comic 并发越高尾帧链越弱；drama-series-agent 尾帧链 | RP §7.1 continuity 列 → 调度器读取；P3 作业队列；`gpu_scheduler` 按依赖派单 |
| 7 | **先出最难的一镜做金丝雀**：每场先跑风险最高的镜（双人、全身行走、远景、对白），过 QC 再放其余；失败则整场先停，提示改锚点或资产 | Higgsfield “先出最难的一镜” | RE selector 给配方标风险分；P3 调度；UI 场头显示“金丝雀：通过/未过” |
| 8 | **资产 = 角色×造型 / 场景×子场景，带出现集数和音色**：造型注册表加 `episodes:[...]`、`voice_ref`（5–30 s 单人干净音频）；编译器按 `characters_on_screen` 自动带造型图 + 子场景图 + 音色进 Ref2VA | 小云雀造型/子场景/出现集数；可灵主体绑音色；Vidu 0–3 音色；Seedance “角色 N 的音色为音频 N” | RP §2 looks/scenes 注册表 + 新字段；RE `two_person_ref2va.yaml` 增 `ref_audios`；UI 资产页角色卡（XYQ #9 未做项） |
| 9 | **片段/镜头局部重做三件套**：①只重做音频轨（视频 latent 不变，掩码音频通道）②时间段 v2v 低 denoise（选 t0–t1）③FaceRefine 裁脸重绘。每种都作为新 Artifact，原版保留可回滚 | 小云雀“片段重拍”按选中时长；即梦定点重拍、人声分离重新配音；wind-comic 框选坏段重拍 | RE 新配方 `audio_only_redo`、`v2v_segment`、`face_refine`；RP §3.3；UI 精修区时间轴框选 |
| 10 | **重出时改锚点不重抽**：重试 1 注入本镜 Reference Anchors 句（RP §7.4 已有）；另外规定重出一次只改一个维度（表情 / 动作 / 光），Spec 记 `retry_axis` | 小云雀“一次只改一件事”；Higgsfield 重出改文字不重传参考 | RP §7.4；RE prompt.py；UI 重出弹层只给单选维度 |
| 11 | **风格前缀与每场摄影基线作为编译常量**：项目级 style 前缀 + 每场 `scene.lighting` / 镜头焦段锁一次，编译器逐镜注入，不由写作方逐镜重复 | 小云雀 style_pe_before 前缀；Higgsfield 每场锁光与镜头 | RP §3.1 编译纯函数输入 bible_rev；§7.1 scene.lighting |
| 12 | **上游改动只标脏，按影响面排队**：资产/LoRA/Spec 改 rev → 受影响镜头标“有更新”，不自动重出；已定稿默认跳过；队列显示将重跑的镜数与预计 GPU 时间 | drama-series-agent 只标受影响下游；小云雀“一键同步更新”（营销口径）；C_research §2 | RP §3.3 + P3；UI 影响面清单（C_research 原则已有，此处给调度落点） |
| 13 | **发布闸门四维 + 显式 override 留痕**：合成前每镜须有：画面对 Spec（VLM）、身份（SFace）、对白（ASR-CER）、嘴-音对齐（H3 原声相关值）。项目方可 override，但必须写入时间线 warnings 和 Spec provenance | wind-comic 四维发布闸门 + pacingOverride 记录；H3 官方 QC 清单 | RP §3.4 第 4–6 步、P5；UI 合成前清单 |
| 14 | **作业层借 Seedance API 的四个字段**：`priority`（0–9，预演/金丝雀高、批量低）、`execution_expires_after`（排队过期自动取消）、`return_last_frame`（每个视频产物都附尾帧 Artifact）、`callback`（worker 完成即回写，API 不持有状态） | 火山方舟 Seedance API 参数 | RP §3.5 作业持久化、P3；`gpu_scheduler` |
| 15 | **写作侧“技能”= 分镜规则文件版本化**：写作方拆镜所用规则（config/script_chat_rules.md 等）带 rev 写进每个 Spec 的 source；规则改了能查出哪些集是旧规则拆的。Claude 只管版本与校验，不评价规则内容 | 小云雀“技能设置”可配分镜阶段规则和输出格式；drama-series-agent `skills/` | RP §2 source 字段、§3.2；UI 集信息显示“拆镜规则 rev” |

不建议照搬：
- 去掉首尾帧定稿层（C3 项目方要求保留；我们的做法是把它批量化、预演化，见 #3）。
- 对话式“故事板助手”改剧本（写作走外部 API 网关，Claude 不写不评内容）。
- 即梦的“三种角度 + 卖点标签”、钩子密度打分：属于内容判断，归写作方和项目方。
- 尾帧链贯穿全集（drama-series-agent 做法）：误差累积，只在 continuity=continuous 时用（#6）。
- 片段为默认渲染单元：先 A/B（#1），不改默认。

---

## 5. 来源清单

官方 / 一手：
- 小云雀 Web 手册：https://www.xiaoyunque.com/tutorials/web-manual
- 小云雀 Seedance 2.5 手册：https://www.xiaoyunque.com/tutorials/seedance-2-5
- 小云雀 智能预演：https://www.xiaoyunque.com/tutorials/short-drama-agent-smart-preview
- Seedance 2.0 官方博客：https://seed.bytedance.com/en/blog/seedance-2-0-正式发布
- Seedance 2.0 技术报告摘要：https://arxiv.org/abs/2604.14148
- 火山方舟 Seedance API：https://docs.volcengine.com/docs/82379/1520757
- 可灵多镜头指南：https://kling.ai/blog/kling-video-3-multi-shot-guide
- 可灵主体库 3：https://kling.ai/quickstart/klingai-element-library-3-user-guide
- 可灵视频 3.0 手册：https://kling.ai/quickstart/klingai-video-3-model-user-guide
- Vidu Q4：https://www.vidu.com/zh/vidu-q4
- LTX Storyboard：https://website.ltx.studio/studio/platform/ai-storyboard-generator
- Higgsfield 短片管线：https://higgsfield.ai/blog/ai-short-film-pipeline
- Higgsfield Popcorn 帮助：https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-popcorn
- OpenArt Director 新闻稿：https://openart.ai/zh-cn/blog/openart-director-press-release/
- ViMax：https://github.com/HKUDS/ViMax ，https://arxiv.org/html/2606.07649v2
- MovieAgent：https://github.com/showlab/MovieAgent ，https://arxiv.org/abs/2503.07314
- drama-series-agent：https://github.com/binwu1/drama-series-agent
- wind-comic：https://github.com/ChrisChen667788/wind-comic
- Toonflow：https://github.com/HBAI-Ltd/Toonflow-app

媒体 / 第三方：
- 人人都是产品经理（即梦短剧工作室实测）：https://www.woshipm.com/ai/6485581.html
- IT 之家：https://ithome.com/1/018/013.htm
- TechCrunch（OpenArt One-Click Story）：https://techcrunch.com/?p=3035461
- 虎嗅（AI 短剧公司与成本）：https://m.huxiu.com/article/4895398.html
- Scenario（Hailuo 说明）：https://help.scenario.com/en/articles/minimax-hailuo-video-the-essentials
- useapi（MiniMax Agent）：https://useapi.net/docs/api-minimax-v1/post-minimax-agent
- Comfy Vidu Q2 R2V：https://comfy.org/zh/workflows/api_vidu_q2_r2v-c1956ef24421/
- PingWest / 搜狐（即梦，搜索摘要）：https://www.pingwest.com/a/318850 ，https://m.sohu.com/a/974402014_122563727
- 知乎（AI 短剧流程，搜索摘要）：https://www.zhihu.com/question/2069389637840385255

本地：
- docs/xyq_walkthrough.md、docs/xyq_flow_full.md（小云雀实测）
- docs/research/seedance_consistency.md（Seedance 模型层机制、H3 Ref2VA 同构）
- docs/ep02_iter/refactor_proposal.md、chain_audit.md、h3_comfy_expert.md、LEARNED_SPECS.md
