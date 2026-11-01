# 镜头语言：怎么写成 H3 能执行的字段（PROMPT，2026-10-31）

项目方原话：“提示词里面关于镜头描写（特写、拉长、转换、切场）这些东西学会了没有？”

边界：本文只讲**写法、格式和可实现性**，也就是系统怎么把一个镜头设计写成 H3 能执行的字段。哪一镜用什么镜头、拍什么，由写作方或导演决定。正式规则在 `knowledge/rules/writer_camera.yaml`（K-WRT-101–108、K-PRM-101–103、K-EDT-101–102），写作模型的系统提示词在 `config/pipeline/prompts/P3-P4.md`，写作规则附录升到 sysimpl-v3。

## 1. 官方写法（最高置信）

| 项 | 官方原文 | 出处 | 我们的规则 |
|---|---|---|---|
| 运镜三要素 | “motion type + amplitude + speed”；“medium amplitude and normal speed are usually omitted” | base-en §4.3 | 运镜写成一句动作：The camera pushes in with small amplitude as …；一镜只用一种运镜（K-PRM-101） |
| 运镜词表 | Zoom / Push / Pan / Truck / Tilt / Pedestal / Arc / Tracking / Static / Shake / POV / Roll | base-en §4.3 表 | 本项目不用 Shake、POV、Roll（规则 §5 原有）。主观视角写成机位位置（K-PRM-102） |
| 切镜 | `[Shot 2] At 00:03.500, the camera cuts to...`；“If only the distance or a slight angle needs to change, prefer camera motion” | base-en §4.2 | 一镜就是一个连续镜头。景别要连续变化时用运镜；要换机位就拆成下一镜（K-WRT-101） |
| 转场 | “When explicitly requested by the user, cross-dissolve, fade, or wipe may also be used” | base-en §4.2 | 我们每镜单独生成，转场交给剪辑做。转场写在 **下镜** 行，H3 里不写（K-EDT-101） |
| 首帧和参考图 | “If an image is used only to define a character … do not create a standalone picture entry” | ref-en §2.2 | 纯 Ref2VA 里，参考图只是身份参考。构图全靠第一句（景别、机位、站位、光），编译器会删掉首帧锚定子句（K-PRM-103） |
| 描述细度 | “clearly establish the current composition … camera movement” | ref-en 开头 | 第一句写构图，每一拍写运镜和动作 |

## 2. 短剧摄影语法（行业通用，中置信）

| 语法 | 定义（原文） | 出处 | 落成的格式规则 |
|---|---|---|---|
| 180° 轴线 | “The 180 rule sets an imaginary axis, or eye line, between two characters”；“you must then decide which side of the line you will place each subsequent camera setup.” | https://www.studiobinder.com/blog/what-is-the-180-degree-rule/ | 正反打的相邻镜，两人在画面左右的位置不变（**人物** 行左右逐镜一致）。越轴要标 HARD CUT（K-WRT-104；与 SS-X4 一致） |
| 正反打 / 视线匹配 | “one character is shown looking at another character (often off-screen)”；“It is an example of an eyeline match.” | https://en.wikipedia.org/wiki/Shot_reverse_shot | 说话人朝向对方，视线落在对方身上。下一镜接视线落点（K-WRT-104、K-EDT-102） |
| 动作匹配切 | “the action of one shot matches the continuation of a similar action in the next shot” | https://www.studiobinder.com/blog/types-of-editing-transitions-in-film/ | 同一场戏里，下一镜从上一镜动作的中段进入，所以上一镜结尾要留一个仍在进行的动作（K-EDT-102；sysimpl-v2 RL-T6） |
| 叠化 | “A film dissolve transition is a gradual transition from one shot to the next.” | 同上 | 只在时间过渡时用，0.3–0.5 秒（K-EDT-102） |
| 跳切 | “Jump cuts are primarily used to show the passage of time.” | 同上 | 本项目不作默认转场 |
| 景别递进 / 焦点接力 | “全景入画 → 推进聚焦 → 触发/诱因 → 反应/互动 → 过程 → 高点特写”；镜间用“物理接力 / 视线接力 / 环境接力” | docs/ep02_iter/runninghub_study.md 第 287 行 | 景别随情绪由远到近，特写和大特写留给高点；相邻两镜同景别连续不超过两镜（K-WRT-105） |
| 过肩、侧面 | “Prefer over-shoulder, profile / 3/4, or medium two-shot with both eyelines readable” | binwu1 dialogue-facing-bind.md | 双人对白不写两张正脸对着镜头（K-WRT-104） |
| 一镜一种运镜 | “Keep one dominant camera idea (don't stack orbit + track + push)” | 同上 | K-PRM-101 |
| 钩子 | 导演稿：“开场 3 秒内必须有第一刀”；v1 实测开场第一镜 8 s、9.14 s 才开口 | ep02_director_cut.md；data/ab/director/v1/review.md | 镜 1 约 4 秒，从动作中段的特写起手（K-WRT-106） |
| 竖屏 9:16 | “画幅由工作流决定”；“竖屏中近，庄周偏土路左侧” | binwu1 timed-motion-template.md 第 226、160 行 | 景别偏近，主体放在上 1/3，视线方向留空；提示词里不写 9:16（K-WRT-107）。“头部留白 / 三分法”在社区样例里没找到，属于通用构图习惯，置信低 |

## 3. 社区样例里的写法

- 项目方工作流的 CAMERA 段（Realistic AI Video MiniMax H3.json 节点 85）：“A continuous medium shot from slightly across the table, positioned near eye level. The camera slowly pushes forward by a small distance.” 包含四项：连续景别、机位高度、一种运镜、幅度。我们沿用这四项，只是不写 slowly（按项目方的节奏要求）。
- 一段提示词内多镜切换：civitai 2734359（Better Human Motion）的样例是每 2 秒切一镜：“[Shot 4] At 00:06.000, the camera cuts to a static medium shot”。没找到这种写法对身份 / 嘴型影响的实测，项目自己的文档也写着“未验证”（competitor_flows.md 第 368 行），所以只列为待验（K-WRT-102）。
- 尾帧接首帧链式拼接时身份会漂移（civitai 2833322 Multishot：“identity error compounds”），我们每镜独立生成，不受这一条影响。
- 手持效果：handheld_h3 LoRA；跟拍防抖：LOCKSTAB（civitai_study.md 第 76、102 行）。没测，不进默认。

## 4. 运行规则

- **写作模型调用默认关推理（K-WRT-108）**：方案 C 转写时，abliteration large-flash 开着推理，连续 3 次在 24000 token 处截断，其中推理占 19–24k token；关掉推理后，一次就输出了完整 9 镜，约 11k token。

## 5. 待验

- 镜内 `[Shot N]` 多镜，对比拆镜加剪辑：看身份 SFace、嘴型、切点 ΔE。
- 竖屏主体放上 1/3、视线方向留空的写法，在 H3 出片里会不会被执行：方案 C 出片后看接触印样。
