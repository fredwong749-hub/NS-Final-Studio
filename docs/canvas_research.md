# AI 竖屏短剧生产画布：竞品交互调研 + 设计方案

> 调研日期：2026-10-30｜调研方式：只读网页检索（官方手册、帮助中心、媒体实测、第三方评测）
> 场景前提：60 集 × 6 镜 × 10 s；剧本、分镜脚本**离线写好后导入**；每镜「首帧图 → 图生视频」；核心痛点是人工操作太多，尤其是**按集切换角色造型**（服装、鞋、妆、发型、首饰/饰品状态）。
> 标注约定：**[官方]** 指官方手册或帮助中心；**[实测]** 指媒体或作者上手文章；**[二手]** 指导航站、营销稿或综述；**[未证实]** 指只有单一来源或推断。截图里的内容我没法直接看到，凡是根据文字描述还原的界面，都按上面的约定标注。

---

## 0. 结论速览（TL;DR）

1. **还没有哪款产品真正做了"按集段排造型"**。离这个需求最近的有两家：小云雀短剧 Agent 会"提取角色在不同时空的**妆造特征**，并**映射到对应集号**"[官方]；即梦短剧工作室（2026-10-26 上线）可以把"一个角色按剧情阶段拆成**多个形象**"[实测]。两家都是 Agent 自动拆出来、用户事后确认，**都没有可视化的"造型排期表"**，服装、鞋、妆、发、首饰也都没有拆成独立部件。这块就是我们可以做出差异化的地方。
2. 业界在一致性上已经形成共识：**资产库（主体 / Elements）加 `@引用`**。可灵主体库用 1 主图 + 1~3 辅图，支持 AI 补视角、绑定音色，分类里就有「服装与配饰」[官方]；LTX Elements 能从剧本自动抽取，官方博客建议用 `@Sarah_casual / @Sarah_formal` 这种**变体命名**来表示换装[官方博客]。
3. 降低人工的主要招数有四个：**导入剧本后自动拆集、拆镜、建资产**；**改一次资产，全剧同步**（小云雀"一键同步更新"，纳米漫剧"改一次服饰，全剧数千镜头自动更新"）；**批量和非线性并行生成**；**先审静帧（预演），再花钱出视频**（小云雀「智能预演」、即梦 3D 导演台、LTX 的"出图前改分镜是免费的"）。
4. 在二次修改这块，大家普遍做得不好。只有 Boords 有完整的"版本 + 帧级评论 + 帧级审批状态"[官方]；AI 工具大多只做到"单镜重生成 / 重拍"，局部重绘则交给画布（即梦智能画布、LibTV 节点衍生"原图不覆盖"）。
5. 视图形态正在往**"画布 + 故事板双模式"**收敛（即梦短剧工作室 DreamShot 明确做了双模式切换，宣称约 1000 个素材时画布仍然流畅）[实测]。纯节点画布（LibTV / TapNow / Flora / Weavy / Krea）灵活，但缺少集和镜的结构，**不适合 360 镜的量产管理**，只适合用来做"单镜修复工作台"。

---

## 1. 各产品逐项调研

### 1.1 小云雀 · 短剧 Agent（字节 / 剪映系）——重点

| 维度 | 发现 | 来源 |
|---|---|---|
| 信息架构 | 项目（全局设定表单：项目名称、画面风格、画面比例）→ 全集列表（可"分集生成视频"）→ 每集自动拆镜，**底部分镜栏**可以增删镜头。官方流程共 6 步：① 首页「短剧Agent」上传剧本或 AI 写剧本 → ② 确认剧本概要，填全局设定 → ③ **生成全局角色** → ④ **生成全局场景** → ⑤ 分集视频生成，编辑**故事版**，生成分镜视频 → ⑥ 右上角「合成」，导出全集 | [官方手册](https://www.xiaoyunque.com/tutorials/web-manual) |
| 分镜卡 | 字段有：分镜脚本（在「故事版编辑」里改）、**分镜出现的角色妆造**、场景图、参考素材（道具、光影、站位垫图）、`@` 引用资产库里的角色和场景；可以**截取当前帧、首帧、尾帧**，衔接上一镜和下一镜。实测文章另外提到每镜有"画面描述、角色、场景、台词、时长" | [官方手册](https://www.xiaoyunque.com/tutorials/web-manual)，[新浪实测](https://finance.sina.com.cn/stock/t/2026-03-23/doc-inhrxvtw1306679.shtml) |
| 分镜单元 | 报道称以 10~15 s 为一个分镜单元，内部再细分为 3~5 s 的动态单元[二手]；官方预演教程给的示例 clip 时长是 8/9/11/13 s | [官方·智能预演](https://www.xiaoyunque.com/tutorials/short-drama-agent-smart-preview) |
| 角色资产 | "Agent 自动捕获剧本中的所有角色，并**提取角色在不同时空的妆造特征，映射到对应集号**"；按钮有「新建角色」「编辑角色与音色」「根据故事设计角色形象」「新建角色形象」；**在「资料库」里改角色形象或音色后，该角色出场的所有剧集都会一键同步更新**；新角色会参考已有角色的形象，保证长相一致 | [官方手册](https://www.xiaoyunque.com/tutorials/web-manual) |
| 跨集识别 | 能把"叶姓婢女 / 叶才人 / 叶太后"识别成同一个人；**脸锚定不变，服装、妆容、表情随处境变化**（"雅致 → 端庄 → 沧桑"），年龄和身体状态也会随时间更新 | [新浪](https://finance.sina.com.cn/stock/t/2026-03-23/doc-inhrxvtw1306679.shtml)（宣传稿，[未独立验证]） |
| 批量 | "批量生成多集、多分镜"；**跨集非线性并行**：一个镜头在渲染时可以去开另一集，前提是已经建好"数字资产档案"和"创作蓝图" | 官方手册，新浪 |
| 预演 | 「智能预演」：在集编辑器底栏点「智能预演」→ 选一组提示词已确认的 clip（>2 个，引用资产 ≤9）→「生成智能预演」→ 分镜图插入对应 clip，**用绿点标记** → 检查无误后再出视频 | [官方·智能预演](https://www.xiaoyunque.com/tutorials/short-drama-agent-smart-preview) |
| 二次编辑 | 整组预演不满意就选中 clip 重抽；**单张分镜图**不满意，点图右上角编辑入口**进入画布** → 从分镜拖出节点、输入修改要求、出图 → 加入素材 → 从资产库拖回编辑器。场景图通过改"场景描述"重生；角色图到资料库里改 | 同上 |
| 已知问题 | 等待时间长（建全局角色"半小时以上"），一致性偶尔出瑕疵，**分镜编辑自由度不够**，参考图约束力会随生成次数增加而减弱，多集容易漂移[二手] | [爱范儿实测](https://www.ifanr.com/1658787)，[CSDN 横评](https://blog.csdn.net/Xiaofeng3693/article/details/163754298) |

**可借鉴**：妆造按集号映射、资料库改一处全剧同步、先预演后出视频、绿点状态标记、"故事版 + 画布"两层（画布用来修单张图）。
**它的缺点也是我们的机会**：映射关系不可视、不能手动排期，部件（鞋、首饰）不独立，同步是"全量改"，没有"受影响镜头清单 → 选择性重渲"这一步。

### 1.2 即梦 / Dreamina（字节）

| 维度 | 发现 | 来源 |
|---|---|---|
| **短剧工作室（2026-10-26 新上线）** | 三个入口：一句话灵感、小说/IP 改编、上传剧本；剧本 10~100 集。剧本分三层（故事设定 / 分集大纲 / 完整剧本），每层都能和 Agent 讨论修改，点「下一步」进入资产库 | [网易实测](https://www.163.com/dy/article/LAB4MTVA0511N33R.html)，[fluxbbs](https://fluxbbs.com/jimeng-short-drama-studio-dreamscript-anycook-dreamshot-20261026/) |
| 资产 | 1.7 万字剧本被拆成 7 个角色、20 个场景；**一个角色按剧情阶段拆成多个形象**；每张资产图都由 Agent 先写好提示词，用户可以确认生成、手改，或补充表情、三视图、特定角度 | [网易实测](https://www.163.com/dy/article/LAB4MTVA0511N33R.html) |
| 视图 | DreamShot 支持「**画布**（整理素材）/ **故事板**（编排剧情）」双模式切换；画布在约 1000 个素材时仍能顺滑拖拽、缩放、框选和撤销重做；**3D 导演台**可以摆机位和运镜，预演不消耗视频算力；智能预演把关键镜头串起来先看节奏 | 同上，[凤凰网](https://tech.ifeng.com/c/8xXa3tiLbLF) |
| 二次编辑 | 右下角「**与 AI 对话**」面板：用自然语言描述问题，Agent 先检查项目状态再修（例如自动补 4 段约 4 s 的转场、去掉误生成的疤痕）；**片段重拍**、补拍、插入、重新编排、**回退**；声音重构（人声和 BGM 分离后重配）；智能切镜 | 同上 |
| 协作 | 团队版：多账号资产管理、积分管理 | [网易](https://www.163.com/dy/article/LAB4MTVA0511N33R.html) |
| 旧版「故事创作」 | 先「创建空白分镜」，再逐格写描述出图；「出演角色」里填角色名称和提示词，或导入已有角色图；「图转视频」页面有运镜方式、生成模式、时长、尾帧开关；可对口型、补帧。成片仍然要到剪映里剪 | [网易 2024](https://www.163.com/dy/article/J7VU0NS3055673SX.html) |
| 智能画布 | 局部重绘（框选后输入描述）、扩图、消除、抠图、多图层；生成的 4 张候选图放在**右侧图层面板**里选 | [CSDN](https://blog.csdn.net/Makecucy/article/details/148848940)，[教程](https://runyoung0613.github.io/jimeng-tutorial/charpter/ch09-%E6%99%BA%E8%83%BD%E7%94%BB%E5%B8%83.html) |
| 批量 | "选中镜头批量转为动态片段"[二手] | [火山引擎开发者社区](https://developer.volcengine.com/articles/7655153826827075593) |

### 1.3 可灵 Kling（快手）

| 维度 | 发现 | 来源 |
|---|---|---|
| 主体库 / Elements | 入口有三个：Omni 输入框的「Create Element」、Video 3.0 的「Bind elements to enhance consistency」、资产页的「Elements」。建主体的流程：上传主图（建议正面，可「Select from History」）→ 自动识别类型（可改）→ **绑定音色**（仅角色）→ 1~3 张辅图 → 名称（库内唯一）+ 描述（可以 AI 自动写，**建议写清"需要忽略的特征"**）→ Generate | [官方指南](https://kling.ai/quickstart/klingai-element-library-3-user-guide) |
| 分类 | 角色、动物、道具、**服装与配饰（Costumes & Accessories）**、场景、特效、其他。说明服装可以作为独立主体，和角色主体叠加使用（O1 指南："combine characters, items, outfits, scenes"） | 同上，[O1 指南](https://kling.ai/quickstart/klingai-video-o1-user-guide) |
| AI 补视角 | 只传 1 张主图，用 O1 Image 自动生成其他视角（会员每天 3 次免费） | 同上 |
| 引用与上限 | 在提示词里输入 `@` 唤出主体，或「Add from Element Library」；资产页点「Use Element」直接带入 Omni。有视频输入时，图片加主体最多 4 个；没有时最多 7 个；图片生成最多 10 个。主体总数按会员等级 30~500 个 | 同上 |
| 多镜头 | Video 3.0「Custom Multi-Shot」：单次最多 15 s、最多约 6 镜，每镜可以设时长、景别、角度、叙事、运镜；提示词格式为 `Shot 1 (3s): …` | [3.0 Omni 指南](https://kling.ai/quickstart/klingai-video-3-omni-model-user-guide)，[VEED](https://www.veed.io/learn/kling-3-0-guide) |
| 多图参考 | 1.6 起支持 1~4 张图；**框选主体**，只参考图中指定的部分 | [AITOP100](https://www.aitop100.cn/infomation/details/27123.html) |
| 二次编辑 | 支持单镜独立修改重生成[二手]；没有看到版本历史 | 火山引擎文章 |

### 1.4 海螺 Hailuo（MiniMax）

- 「主体参考」（S2V-01）：单张图锁定人物外观（性别、年龄、肤色、五官），姿势、表情和环境交给提示词控制；初期只支持单人，多人、物体、场景参考列在后续计划里。[量子位](https://www.qbitai.com/2025/01/243200.html)，[ai-bot](https://ai-bot.cn/s2v-01/)
- 粘贴剧本能自动拆出基础镜头，**但没有分镜文稿导出排版**，定稿要手工整理。[火山引擎](https://developer.volcengine.com/articles/7655153826827075593)
- 和本需求的关系：只能作为模型层的参考，产品层没有可借鉴的 IA。

### 1.5 剪映 / CapCut

- 国内剪映是**时间线**形态，有"时间轴层面的镜头分段标记"和批量字幕，**没有角色人设管理**。[火山引擎](https://developer.volcengine.com/articles/7655153826827075593)
- CapCut 海外版有 AI Storyboard Generator 和 Script-to-video（选风格、比例、配音，逐场景调整），是轻量模板化工具。[CapCut](https://www.capcut.com/tools/ai-storyboard-generator)
- 它在流程里的角色是**最终剪辑和交付的落点**：有戏 AI 和扣子都支持"导出剪映草稿"，视频、字幕、配音三条轨自动对齐。

### 1.6 腾讯智影 / 百度

- 腾讯智影：本次检索**没有找到**它有短剧分镜或角色库能力的可靠资料（结果都是腾讯云 API 教程）。[未证实]
- 百度：只在二手综述里看到"百度智能云 Hogee（2026-04 内测），一站式 AI 短剧平台，多智能体分工"，没有官方稿。[知乎综述](https://zhuanlan.zhihu.com/p/2042925285423699301) [未证实]

### 1.7 国内漫剧/短剧一站式工具

| 产品 | IA / 关键交互 | 资产 | 批量 / 二改 | 来源 |
|---|---|---|---|---|
| **有戏AI（风平智能）** | 「开始创作」→ 剧名、剧情/旁白模式 → 上传剧本（5~10 万字，按"章/集"自动拆）→ 分镜页「**智能分镜**」（场景、景别、运镜、音效、时长、可直接生成的提示词）→ 角色和场景图 → 故事板批量生成 → 成片页导出 | 启动时为每个角色生成**定妆照和三视图并锁入资产库**，后续分镜自动继承；角色旁有「多视图」按钮 | **任意环节可以回退，改动只影响当前环节**；故事板可以按题材切换视频模型；「**导出剪映草稿**」 | [网易](https://www.163.com/news/article/L5DROIBR00019UD6.html)，[ai-bot](https://ai-bot.cn/youxiai/) |
| **LibTV（Liblib）** | 无限画布，双击生成节点（文本、图片、视频、音频、脚本）；脚本节点有三种模式（剧本 / 视频参考 / 角色）→「生成分镜」批量出图 → 一键转视频；输入 `/` 调出九宫格、25 宫格、剧情推演、角色三视图；宫格可以**一键切成单图** | 角色三视图、正侧面 | 图片节点可设数量；**结果从源节点衍生出新节点，原图不覆盖**；把节点流程"打组"后「添加到工具箱」，作为模板复用；有 Skill/OpenAPI 给 Agent 调用 | [量子位](https://www.qbitai.com/2026/03/390320.html)，[腾讯新闻](https://news.qq.com/rain/a/20260319A05XAY00) |
| **TapNow** | 节点画布 + Agent（自然语言做分镜、角色设计、批量处理） | 真人素材库 | **没有时间线**，成片要外部剪辑 | [什么值得买](https://post.smzdm.com/p/a82lrprl/)，[pixo](https://pixo.video/zh/alternatives/tapnow) |
| **知漫剧** | 角色卡 + 场景库 + 强制参考；建议先小批量测试特写、全身和多人对话镜，稳定后再整集出图 | 角色库只填 3~4 项核心外貌特征，"后续所有分镜自动调用同一份形象数据" | "个别镜头崩坏只需单帧重绘" | [掘金](https://juejin.cn/post/7699681127507591222) |
| **360 纳米漫剧流水线** | 编剧智能体解析场次、出场序列、场景切换；导演智能体规划景别、运镜 | 正侧背三视图 + 场景四视图 + "空间记忆" | "**改一次人设或服饰，全剧数千关联镜头自动更新**" | [搜狐](https://www.sohu.com/a/1029539663_121684745)，[IT之家](https://www.ithome.com/1/005/809.htm) [二手] |
| **1人漫剧** | 集 → 章 → 镜头；一键抽取角色（姓名、性别、年龄、外貌）、场景、道具；**分步向导**：批量关联 → 推理提示词 → 首尾帧设置 → 批量生成 → 批量超分 → 视频生成，每一步都有确认弹窗 | 多风格定妆照，**多候选切换**；批量配置公共前缀/后缀提示词和参考图；属性面板 | 多 API Key 轮询、并发控制、按功能绑定不同模型、可编辑提示词模板；**项目 = 文件夹 + 结构化 JSON** | [官网功能页](https://1renmanju.com/features/) |
| **Toonflow（开源）** | 无限画布组织剧本、角色、场景、视频片段；3D 导演台；按镜头生成 | 角色、场景、道具资产画布；三视图；多参考视频生成 | 可接 ComfyUI、本地 LLM；MCP、插件 | [GitHub](https://github.com/HBAI-Ltd/Toonflow-app) |
| 扣子 Coze + Seedance | 结构化分镜字段：序号、台词、时长、运镜、画面描述；项目空间沉淀角色设定稿 | — | 基于分镜批量生成；导出剪映格式 | [火山引擎](https://developer.volcengine.com/articles/7655153826827075593) |

无界AI、闪剪、来画、布尔AI：本次检索没有找到它们在短剧 IA 或换装方面有可引用的具体交互细节，跳过。[未证实]

### 1.8 海外

| 产品 | IA | 资产 / 一致性 | 批量 / 二改 / 视图 | 来源 |
|---|---|---|---|---|
| **LTX Studio** | 上传剧本 → 选图像模型和比例 → **审阅自动抽取的 Elements** → Generate 整板；出图前可以对镜头拆分做**合并、拆分、改写**（"这一步不花钱"）；Scene → Shot，每场左侧有 Scene Settings（地点、光照、天气、声音）；每镜一个小面板（预览图 + 站位、对白、机位下拉） | Elements = 角色、物体、地点，用 `@` 标签；官方博客建议**换装用变体 Element**：`@Sarah_casual / @Sarah_formal / @Sarah_athletic`；角色名重复出现会自动绑定到同一个 Element；有教程称每场可以设 Outfit/Mood [未证实] | 单镜重生成不影响其他镜；**Retake** 只重做镜头内 2~16 s 的片段；Flows 节点做批量变体；时间线排序；导出 pitch deck PDF 给客户审 | [Luma 评测](https://lumalabs.ai/news/ltx-studio-review)（竞品方），[LTX 一致性博客](https://ltx.io/blog/how-to-create-a-consistent-character)，[aiindigo](https://aiindigo.com/tutorials/getting-started-with-ltx-studio-creating-cohesive-ai-video-narratives) |
| **Runway** | Gen-4 References：上传图并打标签，提示词里写 `@John`；每次最多约 3 张参考；Workflows（2025-10）是节点画布，有输入节点、媒体模型节点、LLM 节点，可以整条运行或**单节点运行** | 参考图建议光照均匀、姿态中性、背景干净 | — | [AlternativeTo](https://alternativeto.net/news/2025/10/runway-launches-node-based-workflows-for-building-custom-ai-creative-pipelines)，[Substack](https://kristopherdunham.substack.com/p/mastering-character-consistency-in) |
| **Higgsfield** | Popcorn：Auto 模式（一句话，≤8 帧）/ Manual 模式（逐帧指定）；≤4 张参考图，按编号在提示词里引用；**Generate 按钮上先显示积分消耗**；Cinema Studio 主打摄影机控制 | Soul ID 负责跨会话的人脸身份；Popcorn 的一致性只在会话内有效 | 帧可以作为 Kling/Veo 的首帧；尾帧接下一段 | [官方帮助](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-popcorn)，[GLBGPT](https://www.glbgpt.com/hub/higgsfield-popcorn-review/) |
| **Flora / FAUNA** | 节点画布，50+ 模型；FAUNA Agent（2026-03）会在画布上自动加节点、连线、运行，用户在旁边看着调；Techniques = 专业团队沉淀的可复用工作流 | 角色一致性要**自己用 Character Reference 节点搭**，没有内建角色系统 | 适合做单镜修复和风格探索 | [FLORA 博客](https://flora.ai/blog/introducing-fauna)，[Multic 评测](https://www.multic.com/guides/flora-review/) |
| **Weavy（Figma Weave）** | 节点画布；**Array 节点 + Text Iterator**：把一组提示词分别跑同一个模型；一个节点里存放多次结果，可以切换"单个 / 全部 / 某批次"显示，或者**拆成独立节点** | — | 批量迭代器这个模式值得借鉴 | [Weavy 帮助](https://help.weavy.ai/en/articles/12343281-iterators) |
| **Krea Nodes** | 无限画布链式调用模型，可以把工作流**发布成 App**；批量处理用相同设置；Prompt-to-Workflow 把一句需求展开成扇出工作流 | 参考图统一风格 | — | [Krea 文档](https://docs.krea.ai/user-guide/features/nodes) |
| **Freepik Spaces** | 节点画布，**改开头的提示词整条链自动更新**（"recipe"）；实时协作，**评论可以挂在帧或节点上**；触发器、模板、API | 团队流程里"角色先审批，再进入服装和场景" | — | [BusinessWire](https://www.businesswire.com/news/home/20251104023735/en/Freepik-Launches-Freepik-Spaces-to-Power-AI-Visual-Creation-and-Collaboration-in-Real-Time)，[Chase Jarvis](https://chasejarvis.com/blog/freepik-spaces/) |
| **Katalist** | 导入剧本（CSV、Word、PPT 或粘贴）→ 识别角色、场景、动作；每镜可以调景别、角度、姿势、构图、道具 | 从角色库自动给主要角色分配 AI 演员；**一键在全片替换角色（换演员）** | Video Studio 出视频 | [katalist.ai](https://katalist.ai/)，[99signals](https://www.99signals.com/katalist/) |
| **Midjourney** | 没有原生分镜；Omni-reference（`--ow` 调权重）可以用一张图锚定角色、服装和关键道具，`--sref` 统一风格 | — | 批量提交 | [echai](https://echai.ventures/how-founders-use-ai/video-image-audio/how-do-you-keep-characters-and-brand-look-consistent-across-ai-generated-scenes-and-assets) |
| **Pika** | 输入英文分段文案，得到漫画式分镜，再一键生成动画；没有资产管理 | — | — | 火山引擎文章 |
| **Boords（传统）** | 故事板网格，自动给帧编号和分组；可以当 animatic 播放 | AI 角色生成器 | **版本菜单（V1/V2…，可以把评论和帧状态复制到新版本，可恢复）**；**帧级评论**（客户免登录）；**帧状态：In Progress / Review Needed / Approved**；Project Activity 动态流 | [boords.com/iterate](https://boords.com/iterate) |
| **StudioBinder（传统）** | 剧本 → 每场自动生成 shot list；镜头有景别、运镜、配图、颜色标签、筛选 | **剧本拆解：在剧本里标注道具、服装（wardrobe）、角色**，生成按部门分组的 Breakdown Report | — | [Peerspace 评测](https://www.peerspace.com/resources/studiobinder-production-management-software-review) |
| 真人剧组惯例 | 服装连戏：每场拍定妆照加连戏笔记，**"一张照片 + 笔记 = 该场的一页"**；按"换装（costume change）"编号排期 | — | — | [Get Reelisms](https://www.getreelisms.com/blogs/filmmaking/costume-department-101-who-does-what-the-on-set-etiquette-everyone-should-know)，[NOS 标准](https://www.ukstandards.org.uk/en/nos-finder/SKSQ13/oversee-and-maintain-costume-continuity) |

---

## 2. 汇总对比表

| 产品 | 信息架构 | 资产 / 造型 | 批量 | 二次编辑 | 视图 |
|---|---|---|---|---|---|
| [小云雀](https://www.xiaoyunque.com/tutorials/web-manual) | 项目 → 全集 → 集 → 分镜（底部分镜栏） | 资料库；**妆造按集号映射**；改一处全剧同步；`@角色形象` | 多集多镜批量，跨集并行 | 预演重抽；单图进画布修；截帧衔接 | 故事版 + 画布（修图） |
| [即梦短剧工作室](https://www.163.com/dy/article/LAB4MTVA0511N33R.html) | 剧本三层 → 资产库 → 故事板 | **一角色多形象（按剧情阶段）**；三视图、表情 | 未明说 | 对话改稿、片段重拍、补拍、插入、**回退** | **画布 / 故事板双模式** + 3D 导演台 |
| [可灵](https://kling.ai/quickstart/klingai-element-library-3-user-guide) | 单次生成（多镜 ≤15 s） | 主体库：1+3 图、补视角、音色、**服装配饰分类** | — | 单镜重生 | 生成面板 |
| [海螺](https://www.qbitai.com/2025/01/243200.html) | 单次生成 | 单图主体参考 | — | — | 生成面板 |
| 剪映 / CapCut | 时间线 | 无 | 字幕批量 | 剪辑 | 时间线 |
| [有戏AI](https://www.163.com/news/article/L5DROIBR00019UD6.html) | 剧本 → 章/集 → 智能分镜 → 故事板 → 成片 | 定妆照 + 三视图锁库 | 故事板批量 | **分环节回退，影响局部**；剪映草稿 | 分步页面 |
| [LibTV](https://www.qbitai.com/2026/03/390320.html) | 节点画布 | 三视图 | 宫格切图；模板工具箱 | **衍生新节点，不覆盖原图** | 画布 |
| [1人漫剧](https://1renmanju.com/features/) | 集 → 章 → 镜 | 多候选定妆照；公共前后缀提示词 | **分步批量向导** + 并发 / Key 轮询 | — | 表格 + 画布 |
| [LTX Studio](https://lumalabs.ai/news/ltx-studio-review) | 剧本 → Scene → Shot | Elements（自动抽取），变体命名换装 | 整板生成；Flows | 单镜重生，Retake 局部时段 | 故事板 + 时间线 |
| [Higgsfield](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-popcorn) | 序列（≤8 帧） | Soul ID | Auto 模式 | 改提示词重生 | 序列 |
| [Flora](https://flora.ai/blog/introducing-fauna) / [Weavy](https://help.weavy.ai/en/articles/12343281-iterators) / [Krea](https://docs.krea.ai/user-guide/features/nodes) / [Freepik Spaces](https://chasejarvis.com/blog/freepik-spaces/) | 节点画布 | 自建参考节点 | **Iterator / 发布成 App / 改链头联动** | 节点级评论（Freepik） | 画布 |
| [Katalist](https://katalist.ai/) | 剧本 → 镜 | **一键全片换演员** | 整板 | 单镜细调 | 故事板 |
| [Boords](https://boords.com/iterate) | 项目 → 板 → 帧 | — | — | **版本 + 帧评论 + 帧状态 + 活动流** | 网格 / animatic |
| [StudioBinder](https://www.peerspace.com/resources/studiobinder-production-management-software-review) | 剧本 → 场 → shot list | **剧本拆解标注服装、道具** | — | — | 列表 / 故事板 |

---

## 3. 最值得照搬的 15 个模式（按"减少人工"的收益排序）

1. **造型按集段映射（Look Schedule）**，原型是小云雀"妆造映射到集号"和即梦"一角色多形象按剧情阶段"。我们要把它做成**可视、可编辑的排期表**。省力原因：360 镜不必逐镜 `@` 形象，镜头会按所在集自动继承当前造型。
2. **改资产后全剧同步，但要先出影响面再执行**，原型是小云雀资料库"一键同步"和纳米"改一次全剧更新"。改进点：先列出受影响的镜头（N 镜首帧失效），用户勾选后加入队列。省力原因：不用去找"这个耳环出现在哪些镜头"，也不会把已定稿的镜头静默覆盖。
3. **导入时自动抽取并绑定资产**，原型是 LTX 自动抽取 Elements、按名字自动绑定，以及小云雀识别称谓别名。省力原因：省掉逐镜手工挂角色和场景，只需要人工审阅一次"别名合并表"。
4. **先审静帧，后出视频（预演门槛）**，原型是小云雀智能预演的绿点、即梦 3D 导演台，以及 LTX 的出图前改分镜"免费"。省力原因：视频最贵，静帧审一遍能挡住大部分返工。
5. **网格批量审阅 + 状态标记**，原型是 Boords 的 In Progress / Review Needed / Approved 和小云雀绿点。省力原因：一屏看完一集甚至十集的首帧，键盘快速打"过 / 不过"。
6. **分步批量向导**，原型是 1人漫剧的"批量关联 → 推理提示词 → 首尾帧 → 批量生成 → 超分 → 视频"。省力原因：把流水线固化成几个"全选 → 执行"的按钮，每步一次确认就行。
7. **非线性并行队列**，原型是小云雀的跨集并行、1人漫剧的并发控制和多 Key 轮询。省力原因：人在审第 3 集的时候，第 4~10 集在后台跑。
8. **生成结果作为新版本衍生，不覆盖原图**，原型是 LibTV 衍生新节点和 Boords 版本菜单。省力原因：放心批量重跑，随时回退，不用手动备份。
9. **部件化资产**，原型是可灵把「服装与配饰」做成独立主体分类，以及 StudioBinder 剧本拆解里服装、道具单独标注。省力原因：只换耳环时不必重做整套造型，排期按部件独立。
10. **资产描述里写"忽略特征" + 1 主图 + 3 辅图 + AI 补视角**，原型是可灵主体库。省力原因：一次定好参考，后续漂移减少，抽卡次数下降。
11. **分镜卡上的截帧衔接（尾帧 → 下一镜首帧）**，原型是小云雀「截取当前帧/首帧/尾帧」和 Higgsfield 链式。省力原因：连续动作镜头不用手工导出再导入。
12. **对话式全局修改**，原型是即梦「与 AI 对话」面板会先检查项目状态再改。省力原因：一句"第 12~18 集女主别戴眼镜"转成批量结构化操作（要先预览，再执行）。
13. **单镜修复工作台（画布）**，原型是小云雀点图右上角进画布、即梦智能画布局部重绘、LibTV 节点。省力原因：难修的镜头才进画布，修完一键回填到镜头，不会污染主流程。
14. **改链头联动和模板化 recipe**，原型是 Freepik Spaces 和 LibTV「添加到工具箱」。省力原因：把"首帧生成 recipe"（模型、参数、提示词模板）存成项目级模板，换风格只改一处。
15. **生成前显示成本 / 导出剪映草稿**，原型是 Higgsfield 按钮上显示积分、有戏 AI 的剪映草稿（三轨对齐）。省力原因：批量前能预估成本，交付时不用手工对轨。

---

## 4. 设计方案：NS 短剧生产画布

### 4.1 核心数据模型（先把"自动"做对）

```
Project
 ├─ Episode[1..60]            (ep_no, title, status)
 │   └─ Shot[1..6]            (shot_id = E012-S03)
 │        ├─ script fields    (画面描述, 台词, 时长=10s, 景别, 运镜, 情绪, 出场角色[], 场景, 道具[])  ← 离线导入，只读来源
 │        ├─ resolved_look    (由 Look Schedule 自动解析，可被 shot-override 覆盖)
 │        ├─ first_frame: Version[] (img, prompt_final, seed, model, refs_hash, created, status)
 │        ├─ video: Version[]       (mp4, based_on_frame_ver, prompt, seed, model, status)
 │        ├─ selected_frame_ver / selected_video_ver
 │        ├─ lock: none | frame | video        (锁定后不被自动失效/批量覆盖)
 │        └─ state: 待绑定→首帧排队→首帧待审→首帧通过→视频排队→视频待审→定稿 ; + stale 标记
 ├─ Character
 │   ├─ identity (脸/体型参考：1主+3辅, "忽略特征"描述, 别名[])
 │   └─ Slot assets: outfit[], shoes[], makeup[], hair[], jewelry[], prop_state[]   (每个部件独立资产, 有参考图+文字描述)
 ├─ LookSchedule  (character × slot × episode_range → asset_id)     ← 新核心
 │     + scene/shot 级 override（如"E15-S4 湿发"）
 └─ Location / Prop assets
```

**失效机制（stale，这是省人工的关键）**：每个首帧版本记录生成时的 `refs_hash`，也就是它所用的身份、部件资产版本、场景、提示词模板的哈希。资产或排期一改，系统重新计算所有镜头的 hash，不一致的镜头标为 **stale（橙色角标）**，但不自动重跑。用户在"影响面板"里一键把 stale 且未锁定的镜头加入队列。

### 4.2 屏幕清单

| 屏幕 | 用途 | 主要视图 |
|---|---|---|
| ① **剧集看板 Episode Board** | 60 集总览：每集一行 6 张缩略图，状态色条，进度统计 | 网格（缩放 LOD） |
| ② **镜头画布 Shot Canvas + 检查器** | 一集或多集的首帧和视频并排审阅，右侧 Inspector 编辑提示词、看继承链、重渲 | 网格 / 单镜大图 |
| ③ **造型排期 Look Schedule** | 角色 × 部件 × 集段的甘特式排期；部件资产库 | 时间轴矩阵 |
| ④ 版本对比 Compare | 同一镜 A/B（或 4 宫格）对比，叠加差异，选定或回滚 | 并排 / 滑杆 |
| ⑤ 渲染队列 Render Queue | 首帧和视频两条队列，并发、优先级、失败重试、成本预估 | 表格 |
| ⑥ 导入向导 Import | 剧本和分镜表导入、别名合并、资产自动绑定确认 | 分步 |
| ⑦（可选）修复工作台 | 局部重绘、扩图、换参考，修完回填为新版本 | 画布 |

### 4.3 低保真线框

**① 剧集看板（默认首页）**

```
┌───────────────────────────────────────────────────────────────────────────────────┐
│ NS Studio ▸ 《项目名》   [导入剧本] [造型排期] [队列 ●12 运行/48 等待]  预估: 1,240 积分 │
├──────────┬────────────────────────────────────────────────────────────────────────┤
│ 筛选      │ 视图: (●首帧)(○视频)(○双层)   缩放: [–]━━●━━[+]   选中: 18 镜            │
│ □ 待审 42 │ ┌─────┬──────┬──────┬──────┬──────┬──────┬──────┬───────────────────┐   │
│ □ stale 9 │ │ E01 │ [S1]✔│ [S2]✔│ [S3]✔│ [S4]✔│ [S5]✔│ [S6]✔│ ■■■■■■ 定稿  look:A │   │
│ □ 失败  2 │ │ E02 │ [S1]✔│ [S2]● │ [S3]✔│ [S4]✔│ [S5]⟳│ [S6]✔│ ■■■■□□       look:A │   │
│ □ 已锁   │ │ E03 │ [S1]◐│ [S2]◐│ [S3]◐│ [S4]◐│ [S5]◐│ [S6]◐│ 首帧待审      look:A │   │
│ 角色      │ │ ... │                                              ── look 切换线 ──  │   │
│ ☑ 女主    │ │ E12 │ [S1]⚠│ [S2]⚠│ [S3]  │ [S4]⚠│ [S5]  │ [S6]⚠│ stale×4    look:B │   │
│ □ 男主    │ │ E13 │ ...                                                       look:B │   │
│ 造型      │ └─────┴──────┴──────┴──────┴──────┴──────┴──────┴───────────────────┘   │
│ ☑ look:B  │  图例: ✔通过 ●待审 ◐首帧已出 ⟳排队/运行 ⚠stale ✖失败 🔒锁定            │
├──────────┴────────────────────────────────────────────────────────────────────────┤
│ 批量: [生成首帧▾] [重渲stale] [通过所选] [生成视频] [锁定] [导出剪映草稿]  快捷键 A/R/L │
└───────────────────────────────────────────────────────────────────────────────────┘
```
- LOD：缩小时每格只显示色块（可同时看到 60 集 × 6 = 360 格）；中等缩放显示缩略图和状态角标（约 10 集 = 60 张）；放大后显示缩略图、台词首行和造型名。
- 集与集之间画一条"**look 切换线**"，可以直观看到女主第几集换了造型。
- 拖框多选，Shift 选择整集行，在行头点「整集」选中该集 6 镜。

**② 镜头画布 + 检查器（日常主工作区）**

```
┌───────────────────────────────────────────────┬──────────────────────────────────────┐
│ E12 ◂ ▸   [首帧|视频|并排]  过滤: stale        │ 检查器 E12-S03                    🔒□ │
│ ┌────────┐ ┌────────┐ ┌────────┐             │ 状态: 首帧待审  v3/3   [对比 v2↔v3]   │
│ │ S1 ✔   │ │ S2 ⚠   │ │ S3 ●   │             │ ── 剧本(导入, 只读) ─────────────────  │
│ │ [img]  │ │ [img]  │ │ [img]  │             │ 画面: 女主推门而入, 雨夜...            │
│ │ 中景/推│ │ 特写   │ │ 全景   │             │ 台词: "你还敢回来?"   时长 10s          │
│ │"台词.."│ │"台词.."│ │"台词.."│             │ 景别 全景 · 运镜 缓推 · 情绪 愤怒        │
│ └────────┘ └────────┘ └────────┘             │ ── 资产(自动解析) ─────────────────── │
│ ┌────────┐ ┌────────┐ ┌────────┐             │ 女主  身份✓  look:B「黑色风衣期」       │
│ │ S4 ⚠   │ │ S5 ⟳   │ │ S6 ✔   │             │   ├ 服装 风衣v2   (排期 E12–E20)        │
│ │ [img]  │ │ [....] │ │ [img]  │             │   ├ 鞋   短靴v1   (排期 E10–E25)        │
│ └────────┘ └────────┘ └────────┘             │   ├ 发型 湿发 ← 本镜覆盖  [移除覆盖]    │
│                                               │   └ 首饰 珍珠耳环v1 (E01–E30)          │
│ ── 版本条(S3) ── [v1][v2][v3●]  seed 88123     │ 场景 旧宅玄关 v1   道具 —               │
│                                               │ ── 最终提示词(模板展开, 可局部改) ──── │
│                                               │ [ ...可编辑, 改动以 diff 高亮... ]      │
│                                               │ 模型 [seedream▾] seed [88123]□固定      │
│                                               │ [重生首帧] [仅改提示词重生] [局部修复→] │
│                                               │ [通过 A] [打回 R+备注] [生成视频]       │
└───────────────────────────────────────────────┴──────────────────────────────────────┘
```
- 检查器的**资产区显示继承链**：每个部件都标明来自哪个排期段（E12–E20），或者是本镜覆盖。点击可以跳到排期表。
- 提示词分成"模板展开部分（只读、灰色）"和"手改部分（高亮 diff）"两层。模板更新时保留手改部分，并提示冲突。
- `J/K` 切换上一镜 / 下一镜，`A` 通过，`R` 打回，`G` 重生，`L` 锁定，`C` 对比，`Space` 播放视频。

**③ 造型排期（Look Schedule）——核心差异化屏**

```
┌──────────────────────────────────────────────────────────────────────────────────────┐
│ 造型排期   角色: [女主 ▾]   模式: (●部件)(○整套look)      [AI 从剧本推断排期] [影响面板] │
├──────────┬───────────────────────────────────────────────────────────────────────────┤
│ 集 →     │ 1    5    10   15   20   25   30   35   40   45   50   55   60              │
│ 身份/脸  │ ████████████████████████████████████████████████████████████  identity v2 🔒│
│ 服装     │ ██粗布衣v1██████│██黑风衣v2████████│██宫装A█████████████████│██素白孝服██ │
│ 鞋       │ ██布鞋██████████████│██短靴v1██████████████████│██绣鞋████████████████ │
│ 妆容     │ ██素颜████████████████│██淡妆██████████████████████│██浓妆(复仇)██████ │
│ 发型     │ ██麻花辫███████│██披发██████████████████████│██盘发+步摇██████████████ │
│ 首饰     │ ░░无░░░░░░░░░░░░░░│██珍珠耳环v1█████████████████│██凤钗(E41起)████████ │
│ 道具状态 │ ░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░░│██左手缠绷带 E33–E36██░░░░░░░░░░░░░░ │
│ ◆覆盖     │        ◆E12-S3湿发   ◆E27-S1~S6 夜行衣                                    │
├──────────┴───────────────────────────────────────────────────────────────────────────┤
│ 选中: 服装「黑风衣v2」E12–E20  [拖边界改集段] [拆分] [替换资产▾] [仅限场景: 室外□]       │
│ 影响: 54 镜 → 首帧失效 31(未锁) / 已锁 23 不动   预估 31×首帧成本   [加入队列] [取消]   │
├──────────────────────────────────────────────────────────────────────────────────────┤
│ 部件资产库(服装)  [粗布衣v1][黑风衣v2][宫装A][素白孝服] [+新建: 1主图+3辅图+忽略特征]  │
└──────────────────────────────────────────────────────────────────────────────────────┘
```
- 交互参考甘特图：**拖动色块边界**修改集段；在某集位置 Alt+点击**拆分**色块；从下方资产库**把资产拖到集段上**完成替换。
- 「整套 look」模式把各部件的组合存成命名 look（如 look:B「黑色风衣期」），用于看板显示和快速套用；「部件」模式用于精细调整。
- 覆盖（◆）分三级：场景级（例如"所有雨夜外景湿发"）、集内镜头级、单镜级。优先级为 单镜 > 场景规则 > 集段排期。
- 「AI 从剧本推断排期」：LLM 读取分集剧本里的服装和妆容线索，生成**草案色块（虚线）**，每块附剧本原文证据，人工点"采纳"后才生效。这里只推断资产绑定，不改写剧本文本。
- 每次修改都会弹出**影响面板**（模式 2），默认不碰已锁定的镜头。

### 4.4 主流程（逐步）与自动 / 人工分工

| # | 步骤 | 自动（系统） | 人工 |
|---|---|---|---|
| 1 | **导入**剧本和分镜表（docx/md/csv/json） | 解析成集 → 镜结构，校验 60×6、时长；抽取角色、别名、场景、道具 | 审阅"别名合并表"（如 叶婢女 = 叶才人），一次完成 |
| 2 | **建资产** | 为每个角色生成身份候选（1 主 + AI 补 3 视角）；为部件生成候选；场景概念图 | 每个资产从 4 个候选里**挑 1 个并锁定**身份（关键人工环节） |
| 3 | **排造型** | 从剧本推断排期草案（虚线色块，附证据） | 在排期表上采纳、拖动、拆分；这是主要的人工创作点，**一部剧约 30 分钟** |
| 4 | **自动绑定** | 每镜按"集号 + 场景规则 + 覆盖"解析 resolved_look，拼出最终提示词和参考图组（不超过模型上限，优先级：身份 > 服装 > 发型 > 首饰 > 场景） | — |
| 5 | **批量首帧** | 按集顺序入队，并发生成；首帧每镜默认出 2 张候选 | 在看板上选范围并点「生成首帧」（或者开启"导入后自动跑"） |
| 6 | **网格审阅** | 自动预检（人脸相似度低于阈值、人数不对、文字乱码时标黄）[建议] | 在画布里用键盘过一遍：A 通过、R 打回（附备注）、候选二选一 |
| 7 | **修复** | 打回的镜头按备注自动改写**手改层**提示词再重生（可选）；局部修复走工作台，产出新版本 | 难修的镜头进入工作台局部重绘；改资产或排期就走影响面板 |
| 8 | **出视频** | 只对"首帧通过"的镜头入视频队列；视频提示词 = 镜头运镜、动作、台词模板 | 选整集或全部点「生成视频」 |
| 9 | **视频审阅** | 自动生成每集 60 s 串播预览（6 镜连播） | 串播看节奏；单镜打回时选"只重生视频（保留首帧）"或"首帧也重做" |
| 10 | **重渲与定稿** | 版本保留；"定稿"即锁定；资产后续再改也不会动定稿镜头（除非手动解锁） | 定稿整集后导出剪映草稿 / mp4 |

**必须自动的部分**：结构解析、资产绑定和提示词拼装、stale 失效计算、队列调度和失败重试、版本归档、串播预览、导出对轨。
**必须人工的部分**：身份定妆（选和锁）、造型排期采纳、首帧审阅、视频审阅、定稿。
**可以选择自动的部分**：排期推断草案、打回后按备注自动改写、AI 预检。

### 4.5 关键交互细则

- **三种视图**：看板（全剧，按集行）→ 画布（1~3 集，审阅和编辑）→ 排期（角色 × 集段）。看板里双击集行进入画布；检查器里点部件来源跳到排期并高亮对应集段；排期里点影响数跳回看板，并自动筛选出受影响的镜头。三者共享同一个"选中集合"。
- **版本对比**：并排 / 滑杆 / 4 宫格三种方式；显示两个版本的 refs_hash 差异（例如"首饰：珍珠耳环 v1 → v2；seed 不同"），可选定任意版本或回滚。
- **队列**：首帧和视频两条队列；按集优先级拖拽排序；显示失败原因并支持一键重试；运行前汇总积分 / 成本；暂停或恢复不丢状态（服务端持久化，对应用户"低介入批量生产"的目标）。
- **锁定语义**：`锁首帧` 表示资产再变也不失效这一镜的首帧；`锁视频`（定稿）表示全部冻结。批量操作默认跳过锁定的镜头，并在确认框里写明"跳过 N 个锁定镜头"。
- **评论与审批（单人或小团队够用就行）**：沿用 Boords 的三态（待审 / 需修改 / 通过），打回时附文字备注并挂在版本上；活动流记录"谁在何时把哪个排期段从 E12 改到 E14"。

---

## 5. 风险与未证实项

- 小云雀"妆造映射集号"、即梦"一角色多形象"的具体 UI（是否能手动编辑映射）**没有找到截图级描述**，以上信息来自官方手册文字和媒体实测，属于 [未证实细节]。
- LTX Studio"每场 Outfit 字段"只有单一教程提到，[未证实]。
- 腾讯智影、百度 Hogee、无界AI、闪剪、来画、布尔AI：没有找到可靠的交互资料。
- 多数国内平台资料来自营销稿，"改一处全剧同步"等说法都**没有经过独立验证**；我们的设计刻意改成"影响面板 + 选择性重渲"，避免静默覆盖。
- 模型参考图数量有上限（可灵有视频输入时 4 个、否则 7 个；Popcorn 4 个）。部件化资产在拼参考图时必须有**优先级截断规则**，并且检查器里要显示"本镜因上限丢弃了：首饰参考图（仅用文字描述）"。

## 6. 主要来源

- 小云雀：[官方 Web 手册](https://www.xiaoyunque.com/tutorials/web-manual) · [智能预演教程](https://www.xiaoyunque.com/tutorials/short-drama-agent-smart-preview) · [新浪财经](https://finance.sina.com.cn/stock/t/2026-03-23/doc-inhrxvtw1306679.shtml) · [爱范儿实测](https://www.ifanr.com/1658787) · [塔猴手册](https://www.tahou.com/article/209141088873566213)
- 即梦：[短剧工作室·网易实测](https://www.163.com/dy/article/LAB4MTVA0511N33R.html) · [凤凰网](https://tech.ifeng.com/c/8xXa3tiLbLF) · [fluxbbs](https://fluxbbs.com/jimeng-short-drama-studio-dreamscript-anycook-dreamshot-20261026/) · [故事模式 2024](https://www.163.com/dy/article/J7VU0NS3055673SX.html) · [智能画布 CSDN](https://blog.csdn.net/Makecucy/article/details/148848940)
- 可灵：[Element Library 指南](https://kling.ai/quickstart/klingai-element-library-3-user-guide) · [Video 3.0 Omni 指南](https://kling.ai/quickstart/klingai-video-3-omni-model-user-guide) · [O1 指南](https://kling.ai/quickstart/klingai-video-o1-user-guide)
- 海螺：[量子位](https://www.qbitai.com/2025/01/243200.html)
- 国内一站式：[有戏AI·网易](https://www.163.com/news/article/L5DROIBR00019UD6.html) · [LibTV·量子位](https://www.qbitai.com/2026/03/390320.html) · [1人漫剧](https://1renmanju.com/features/) · [知漫剧·掘金](https://juejin.cn/post/7699681127507591222) · [Toonflow](https://github.com/HBAI-Ltd/Toonflow-app) · [火山引擎 8 工具](https://developer.volcengine.com/articles/7655153826827075593) · [搜狐对比](https://www.sohu.com/a/1029539663_121684745) · [TapNow](https://post.smzdm.com/p/a82lrprl/)
- 海外：[LTX·Luma 评测](https://lumalabs.ai/news/ltx-studio-review) · [LTX 一致性](https://ltx.io/blog/how-to-create-a-consistent-character) · [Higgsfield Popcorn](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-popcorn) · [Runway Workflows](https://alternativeto.net/news/2025/10/runway-launches-node-based-workflows-for-building-custom-ai-creative-pipelines) · [FLORA FAUNA](https://flora.ai/blog/introducing-fauna) · [Weavy Iterators](https://help.weavy.ai/en/articles/12343281-iterators) · [Krea Nodes](https://docs.krea.ai/user-guide/features/nodes) · [Freepik Spaces](https://www.businesswire.com/news/home/20251104023735/en/Freepik-Launches-Freepik-Spaces-to-Power-AI-Visual-Creation-and-Collaboration-in-Real-Time) · [Katalist](https://katalist.ai/) · [Boords Iterate](https://boords.com/iterate) · [StudioBinder 评测](https://www.peerspace.com/resources/studiobinder-production-management-software-review)
