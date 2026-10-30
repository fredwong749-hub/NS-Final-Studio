# AI 短剧 / 分镜平台交互调研（v1，2026-10-30）

> 目的：回应 REQUIREMENTS E2/E7 ——"没有认真 deep research 小云雀、Seedance 等短剧平台的交互页面"。
> 范围：只看**交互与界面组织**，不评价任何平台或本项目的剧本、图片内容。
> 方法：逐页读官方手册/帮助中心，再补媒体实测和社区文章。每条结论附**原文引用 + 链接 + 置信度**。
> 置信度：**高**＝官方手册/帮助中心原文；**中**＝官方营销页、主流媒体实测、开源项目 README；**低**＝单一第三方转述、或只有搜索摘要没有正文。
> 局限：我无法登录这些产品，看不到截图里的文字（多数教程的关键步骤是图）。小红书、B 站、YouTube 视频正文基本抓不到，知乎专栏返回 403。**凡写"未找到"的，就是真没找到，不是推断。**

---

## 0. 结论速览（先读这个）

| 维度 | 行业里能确认的做法 | 主要来源 |
|---|---|---|
| 分镜组织 | **集 → 片段 → 分镜**三级。小云雀：故事板页面有**底部分镜栏**，用来增删镜头，主区编辑分镜脚本。重制转绘的分镜工作台是**左边资产、中间脚本、右边预览/对比**三栏 | 小云雀官方手册 |
| 每镜字段 | 时长、景别、机位、角色动作、色彩、焦段（小云雀 2.0 实测）；时长、取景/机位、内容、运镜（可灵 Custom Multi-Shot） | 腾讯新闻实测、可灵官方博客 |
| 角色资产 | **先做资产再拆分镜**。资产库按集号映射妆造；同一角色可有**多个形象版本**，分镜里按镜选择；资产改了，全剧同步 | 小云雀官方手册、腾讯新闻实测 |
| 绑定方式 | 大家都用 **@ 引用**（小云雀、可灵、LTX、Seedance、火宝短剧都是）；可灵另有"从主体库添加"按钮 | 各家官方 |
| 首尾帧 | 主流用法是"**截取上一镜尾帧当下一镜首帧**"；可灵的"Add End Frame"按钮在图生视频右上角 | 小云雀、可灵、Higgsfield、Google Flow |
| 重出 / 版本 | 小云雀用"片段重拍"（时间轴截取 + 修改指令）；Dreamina 一次出 4 张变体后锁定；海螺对单个分镜"重新生成 / 添加到对话"。**并排对比多个版本的界面，官方文档几乎都没写**，只有小云雀重制转绘提到"对比视图" | 各家 |
| 批量 | 小云雀：资产库「批量」出全部资产图，右上角「批量」处理多集，列表视图全选后批量生成；火宝短剧：批量生成前弹确认框（镜数、总时长、模型、分辨率），失败的一键重试 | 小云雀官方、火宝 README |

---

## 1. 字节 小云雀（短剧 Agent / 重制转绘 / 资产创作画布）

官方教程目录：https://www.xiaoyunque.com/tutorials （共 14 篇，短剧相关 5 篇：画布、3D 导演台、剧本助手、重制转绘、智能预演）

### 1.1 分镜 / 镜头列表

- **故事板＝主编辑区加底部分镜栏。** 主编辑区用来改分镜脚本，底部分镜栏用来增删镜头。
  > "分镜拆分：自动拆分镜，包括分镜脚本、分镜出现的角色妆造、场景图。"
  > "有不想要的镜头或想增加的镜头？底部分镜栏支持灵活增加、删除镜头。"
  > "故事版编辑：对分镜脚本中不满意的部分可以手动编辑，不想编辑也可以直接生成视频。"
  — 小云雀 Web 产品手册 STEP 05「分集视频生成，故事版编辑」https://www.xiaoyunque.com/tutorials/web-manual ｜**高**
  - 重点：官方把每个分镜的三样东西放在一起，即**脚本、该镜角色妆造、场景图**。这和我们 E3 的"每镜必有人物图"是同一个思路。
- **分镜工作台三栏布局**（重制转绘流程）：
  > "分镜工作台左侧是角色与场景资产，中间是片段脚本分镜，右侧可在转绘、原片、白模和对比视图间切换。"
  — 短剧「重制转绘」使用手册 环节八 https://www.xiaoyunque.com/tutorials/short-drama-remake ｜**高**
  - 同页配图标题写着"逐片段检查分镜脚本和预览"，配图说明称"片段01对应包含4个分镜的脚本，每个分镜配有台词及镜头描述"（配图说明，不是正文）｜**中**
- **层级是"片段 ⊃ 分镜"，每个分镜带一组结构化字段：**
  > "每个片段由 2-3 个分镜组成，每个分镜标注了时长、景别、机位、角色动作、画面色彩和焦段。"
  — 腾讯新闻《实测小云雀短剧 Agent 2.0》https://news.qq.com/rain/a/20260528A07MOU00 ｜**中**（媒体实测）
- **图有多大：未找到。** 官方文字没写缩略图尺寸，截图里的信息我读不到。

### 1.2 角色 / 资产管理

- **按集号映射妆造（和我们的"排期：角色 × 集"是一回事）：**
  > "提取角色在不同时空的妆造特征，并精准映射至对应集号。"
  > "如果有准备好的角色图，也可以手动上传。"
  — web-manual STEP 03「剧本资产拆解：生成全局角色」｜**高**
- **改资产后全剧同步，不用逐镜替换：**
  > "直接在资料库修改，改完后所有该角色出场的剧集画面 / 声音会一键同步更新，无需逐个镜头替换。"
  — web-manual STEP 03 ｜**高**
  > "修改角色卡之后，相关分镜会自动同步更新"（转述）— 搜狐时间线实测 https://timeline.sohu.com/news/kvIXh6ngRy ｜**中**
- **一个角色可以有多个形象版本，分镜里按镜选择：**
  > "同一角色在资产库里可以有多个形象版本，在故事板里可以按分镜需要选择不同版本。"
  > "点进陆沉的角色卡，能看到基础形象和「求索者形象」两个版本。"
  — 腾讯新闻 2.0 实测 https://news.qq.com/rain/a/20260528A07MOU00 ｜**中**
- **画布里角色可以挂"子形象"（父角色下面挂造型）：**
  > "新建角色/场景节点，可以填充相关信息，可以选择已有角色/场景作为其子形象"
  > "在图片节点可以右键选择「应用到角色」「应用到场景」对已有进行角色/场景节点进行主图替换"
  > "在画布里创作好素材后，可以在**节点工具栏**或**右键菜单栏**里选择保存为道具/素材"
  > "可以双击节点标题修改节点名称，加入资产库中的素材名称也会同步更改"
  — 小云雀短剧 Agent 画布使用手册 https://www.xiaoyunque.com/tutorials/short-drama-agent-canvas ｜**高**
- **资产库和画布的关系：**
  > "在画布中创作的节点可添加进资产库，在故事板分镜页调用"
  > "剧本资产拆解后进入资产库页面，可点击右上角「在画布中编辑」进入画布"
  > "展示角色和场景：将隐藏基础节点及其相关连线，只清晰展示资产库结果"
  — 同上 ｜**高**
- **角色卡带人物小传：**
  > "资产库里还附带类似人物小传的介绍。" "如果对系统生成的角色图片不满意，可以替换图片"
  — 爱范儿实测 https://www.ifanr.com/1658787 ｜**中**
- **绑定到镜头靠 @：**
  > "Tips：使用 @ 来引用资产库中的角色和场景。" — web-manual STEP 05 ｜**高**
  > "在分镜脚本的编辑框里输入 @，就能一键调用前置设定好的专属角色、场景和道具。" — 腾讯新闻 2.0 实测 ｜**中**
  > "我们可以逐个分镜修改提示词和角色引用" — 爱范儿 ｜**中**
- **服装、鞋、美甲这类单品有没有独立管理：未找到。** 官方只提到"角色、场景、道具、素材"四类资产，以及"妆造"。

### 1.3 首帧 / 尾帧

> "快速截取上一镜头的尾帧作为下一镜头的首帧参考，轻松实现视频连贯转场。"
— web-manual「玩转分镜故事板 · 秘密一：首尾帧截取，丝滑转场」｜**高**

> "在参考模式（R2V）中，支持指定具体图片为首、尾帧，写在 Prompt 第一句。"
> "创作模式支持「参考生成」、「视频编辑」、「视频延长」、「首尾帧模式」"
— 小云雀 Seedance 2.5 使用手册 https://www.xiaoyunque.com/tutorials/seedance-2-5 ｜**高**

- **官方承认首尾帧有局限，所以加了"智能预演"：先出整组分镜图，确认后再出视频。**
  > 智能预演会"基于镜头提示词，预演并统一规划关键分镜图，自动插入片段作为视频参考"；页面列出的问题之一是首尾帧只能保证两个镜头之间一致，多镜头仍需反复抽卡。
  > 操作：在分集编辑器底部点「智能预演」→ 选一组已确认提示词的片段 →「生成智能预演」→ 分镜图自动插入对应片段，**以绿点标记** → 确认后再生成视频。限制：片段多于 2 个，引用素材不超过 9 个。
  > 单张不满意时："打开分镜图右上角的编辑入口进入画布，生成新图片，将其加入素材，再从资产库拖入编辑器"（WebFetch 转述）。
  — https://www.xiaoyunque.com/tutorials/short-drama-agent-smart-preview ｜**高**（步骤为转述，引号内的"基于镜头提示词…"为原文）
- **替换首帧的具体按钮：未找到。**

### 1.4 改提示词 → 重出 → 版本 → 选定

- **片段重拍**（官方完整流程）：
  > "1. 入口：在画布的视频节点或短剧Agent-分镜故事板，点击**「片段重拍」**"
  > "2. 在时间轴上截取要重拍的片段，额外支持**精准截帧注释**"
  > "3. 使用**「智能切割分镜」**功能辅助拆成多个片段，通过点选精准选中单个片段"
  > "4. 可以在输入框中持续完善修改指令，点击提交，发起片段重拍"
  > "建议说清楚四件事：改哪里、保留什么、想要什么效果、不要改什么。"
  > "一次重拍不要贪多。比如只改表情、只改动作、只换道具，效果会更稳定。"
  — web-manual「片段重拍」｜**高**
- **抽卡：** "不改 Prompt，直接点击重新生成，"抽"张新卡。"；想改动作等内容，可点视频结果右上角的"修改诉求"调整提示词后再生成（后半句为转述）。— Seedance 2.0 手册 https://www.xiaoyunque.com/tutorials/seedance-2-0 ｜**高**
- **对比：** 重制转绘的右栏可切换"转绘、原片、白模和对比视图"（见 1.1）｜**高**。
- **版本历史列表、两版并排选定：未找到。** 画布手册只说"不仅保留最终结果，也保留中间过程和参考依据"，没写版本 UI。

### 1.5 批量 / 快捷键 / 预览 / 分集

> "不想逐次点击？短剧Agent也灵活支持批量生成多集、多分镜。" — web-manual STEP 05 ｜**高**
> "不满意的内容可重新生成或微调，也可用「批量」生成全部资产图片。" — 重制转绘 环节六 ｜**高**
> "为每一集生成分镜脚本；右上角「批量」可处理多集。" — 重制转绘 环节七 ｜**高**
> "已经完成的分集可以播放、继续编辑或下载。" — 重制转绘 环节九 ｜**高**
> "在列表视图全选**批量生成**" / "在画布中**整组执行**" — 画布手册「初次进入画布」｜**高**
> 快捷键："以下展示为Mac版本快捷键，Windows版本可将`cmd`替换为`ctrl`，整理画布为`shift` + `option` + `F`"（完整列表是图片，读不到）— 画布手册 ｜**高**
> 顶部 tab："点最上边的角色和场景，能看到具体的主角和场景图"，"点最上边分集视频可以观看" — 腾讯新闻 https://news.qq.com/rain/a/20260326A08BMA00 ｜**中**
> 3D 导演台：截图"可将截图或动态参考视频发送到画布"，作为"分镜图或视频生成的构图参考" — https://www.xiaoyunque.com/tutorials/short-drama-agent-3d-director ｜**高**

---

## 2. 即梦 Dreamina（短剧工作室 / Octo / 首尾帧）

- **短剧工作室（2026-10-26 上线），画布和故事板两种模式：**
  > "双模式创作，画布、故事板自由切换，灵活适配创作流程"
  > "故事板全局协同，支持对话改稿、全局修改、灵活调整剧情，保持分镜有序编排"
  > "智能预演关键分镜，串联关键镜头，提前把控画面衔接与叙事节奏"
  — IT之家 https://ithome.com/1/018/013.htm ｜**中**（产品发布报道，没有逐步 UI）
- **Octo（2026-04 内测）：**"能够完成从故事大纲梳理、核心资产构建，到剧本分镜生成、短片成片输出的全链路操作" — 新京报 https://www.bjnews.com.cn/detail/1775720323129620.html ｜**中**。官方英文营销页说，每个 scene 下面点 "Generate video" 生成，并且可以按场景单独重出（WebSearch 摘要，未读到正文）｜**低**
- **变体与锁定：**
  > "gives you four variants per prompt; lock the winning frame and regenerate adjacent beats to match."
  > "Use batch generation to explore multiple looks, then shortlist the best panel for each beat."
  — Dreamina 官方指南 https://dreamina.capcut.com/resource/ai-image-generator-for-storyboard-frames ｜**中**（官方营销/教程页，没有对比 UI 细节）
- **首尾帧：**
  > "In the text box, click the "+" icon to upload your first and last frame" — https://dreamina.capcut.com/resource/first-last-frame ｜**中**。交换或替换按钮：**未找到**。
- **Seedance 2.0 在即梦的入口：** 首尾帧入口和全能参考入口是分开的；全能参考里用"@素材名"指定每份素材的用途（例如图片1当首帧）；输入 @ 会弹出已上传素材列表。— CSDN 手册转载 https://adg.csdn.net/69a2877254b52172bc5e15b3.html 、博客 https://blog.wenhaofree.com/posts/articles/seedance-2-0-practical-guide/ ｜**中**（第三方转述，各文章给的素材上限不一致）
- 每镜字段、角色卡结构、版本对比：**未找到官方说明**。

## 3. Seedance 相关创作界面

Seedance 本身是模型，界面落在小云雀、即梦和火山引擎上。能确认的交互已经写进 §1.3、§1.4、§2：
- "点击 `+` 号上传图片，**最多支持 9 张**"；@ 有两种方式："直接点击输入框下方的"@"按钮"，或"长按你已经上传的素材缩略图"；成功后输入框里出现【@图1】标签。— 小云雀 Seedance 2.0 手册 ｜**高**
- 2.5 的素材上限："图片：最多 30 张 4K 分辨率以内的图片"、"视频：最多 10 段视频，所有视频总时长不超过 30s"；"支持 @ 引用全画布的资产作为参考" — 小云雀 Seedance 2.5 手册 ｜**高**

## 4. 可灵 Kling（Element Library / Multi-Shot / 首尾帧）

- **主体库（Element Library 3.0）：** 每个主体 = 1 张主图 + 1–3 张补充图，最多 4 张。
  > "Each element must contain at least 2 reference images"；主图建议 "front-facing image for higher consistency"，补充图 "from different angles or showing additional details"。
  > 类型有 Characters / Animals / Items / **Costumes**（"Clothing, style outfits, accessories etc."）/ Scenes / Others，系统自动识别类型；库内名称不能重复。
  > 调用方式：Omni 里输入 "@"，或点 "Add from Element Library"；资产页点 "Use Element"。Video 3.0 "recommended to bind elements that appear in the start frame"。
  — https://kling.ai/quickstart/klingai-element-library-3-user-guide ｜**高**
  - 一个角色的多套造型怎么管：**官方没有**，只能把服装单独建成 Costumes 主体。
- **Custom Multi-Shot：**
  > "click "Custom Multi-Shot" to flexibly configure the number of shots and their durations." — https://kling.ai/quickstart/klingai-video-3-model-user-guide ｜**高**
  > 每个镜头四个字段：Duration、"Framing and Perspective: Specify shot size, camera angle, and point of view"、"Narrative Content: …character action, dialogue, and story progression"、"Camera Movement"；最多 "Up to 6 shots"。— https://kling.ai/blog/kling-video-3-multi-shot-guide ｜**高**
  > ComfyUI 节点文档：所有分镜时长之和必须在 3–15 秒之间 — https://docs.comfy.org/zh/built-in-nodes/KlingVideoNode ｜**中**
- **首尾帧：** 点 "Add End Frame"，按钮 "located at the top right corner of the 'Image to Video' function"；建议 "Choose two similar images with the same theme"。— https://kling.ai/quickstart/ai-video-start-end-frames ｜**高**。替换或交换按钮：**未找到**。
- 版本对比、批量、集切换：**未找到**（可灵不是多集产品）。

## 5. 海螺 Hailuo / MiniMax

> "最新上线视频Agent的「半自定义」模式，支持用户在生成过程中自由编辑分镜内容并回顾进度。"
> "用户能在生成视频的过程中介入编辑中间环节，如分镜图片、分镜视频等。"
> "对于不满意的分镜内容，选择"重新生成"，或将其"添加到对话"中，通过输入提示词进行精准微调。"
> "用户能用"查看项目"回顾完整的生成过程，避免退出界面后丢失进度。"
— AI 工具集 https://ai-bot.cn/sites/48346.html ｜**中**（第三方转述官方更新）
- 故事模式、角色卡、首尾帧 UI：**未找到**官方帮助文档。

## 6. LTX Studio

- 先拆结构再出图："Review your script divided into clear scenes and shots, showing the number of shots"；"Characters and objects are automatically extracted from your script as Elements"；可以 "create animated storyboards, which can be exported as MP4 files"。— https://website.ltx.studio/studio/platform/ai-storyboard-generator ｜**中**（官方营销页）
- @ 绑定角色：在 Gen Space 或 Storyboard 打开镜头，在 prompt/description 里输入 "@" 加角色名，从下拉框选 Character Element（来自 https://ltx.studio/blog/getting-started-with-elements 的搜索摘要，正文抓取失败）｜**中低**
- 镜头编辑："The shot editor enables further control over each shot in a separate panel."；"You can also switch between shots by dragging and dropping them."；"The left panel will affect the entire scene, deciding on location, lighting, and weather conditions"；"Every edit may be "refreshed" to generate a different AI take on the same prompt." — CineD 深度评测 https://www.cined.com/ltx-studio-deep-dive-the-first-ai-based-full-editing-suite ｜**中**（2024 年评测，界面可能已经改过）
- "ten variations of a shot side by side"（WebSearch 摘要，原页未核实）｜**低**

## 7. Runway

- Runway Academy 有 "Storyboard Creator Featured Workflow" 和 "Story Panels" 教程，但页面正文只有一句 "Learn how to use the Storyboard Creator Featured Workflow."，内容在视频里，**读不到**。— https://academy.runwayml.com/tutorial/storyboard-featured-workflow ｜**低**
- 分镜表、角色卡、版本 UI：**未找到**。

## 8. Higgsfield（Popcorn）

> "Popcorn creates coherent sequences of up to 8 frames"；"Popcorn accepts up to 4 image references"，在提示词里按编号引用（如 "image one"）；"a frame works as a start frame or reference for Kling or Veo"；重出时 "Refine the text prompt instead of re-uploading inputs"。
— 官方帮助中心 https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-popcorn ｜**高**
- 帧的布局（网格还是列表）：**未找到**。

## 9. 其他：Google Flow、开源短剧工具

- **Google Flow：** Frames to Video（首帧/尾帧）、Ingredients to Video（最多 3 个主体）、"Add to Scene" 送进 Scenebuilder、"Jump To" 保留上一镜最后一帧的上下文切到新镜头、"Extend" 接着上一段往下生成；FAQ 说 Scenebuilder 离开项目后会重置，但所有片段都能在 clips view 找到。— https://labs.google/fx/en-gb/tools/flow/faq ｜**中**（WebSearch 摘要）
- **火宝短剧 huobao-drama（开源，真实 UI）：**
  > "Review and tweak each shot's prompt on the right (`@character` references map to reference images automatically)"
  > "Click "Batch Generate Videos"; failed tasks can be retried in one click"
  > "selection mode + pre-generation confirmation (shot count / total duration / model / resolution)"
  > "Select shots (hover to preview each clip)"
  > "The episode list shows the production status of every episode — click "Enter Studio" to continue"
  — https://github.com/chatfire-ai/huobao-drama ｜**高**（README 原文）
- **Pika：** 没有找到分镜表或角色一致性相关的界面文档。

---

## 10. 共性总结

1. **资产先行，镜头引用资产。** 小云雀、可灵、LTX、火宝都是先建角色/场景资产，镜头里用 @ 引用；资产一改，所有引用它的镜头都同步。
2. **一个角色下挂多个形象（子形象），镜头选的是形象，不是零散单品。** 小云雀的"子形象"、"基础形象 / 求索者形象"都是这样。可灵把服装做成独立的 Costumes 主体。没有一家在镜头卡上逐件展示衣、鞋、甲。
3. **分镜字段是结构化的**（时长、景别、机位、动作），不是一段长文。
4. **首尾帧的核心交互是"上一镜尾帧 → 下一镜首帧"的继承**，再加一个"整组预演"兜底多镜头一致性。
5. **重出偏向"局部、带指令"**：小云雀的片段重拍要求写清四件事，海螺可以把单个分镜"添加到对话"微调，Dreamina 出 4 个变体后锁定。
6. **多版本并排对比几乎没有平台写进文档。** 我们画布现有的"当前 v1 / 新版本 v2 + 全屏对比"在这一点上已经比可查到的公开资料更细。不要为了"对齐平台"把它删掉。
7. **批量操作要先确认、可以重试**：批量出资产、批量多集、全选批量生成、出之前弹确认框、失败的一键重试。

---

## 11. 对照我们画布的交互改进建议（按收益排序，最多 15 条）

对照对象：`docs/ui-audit/v3/ep01-1600.png`（集视图）、`assets-1600-full.png`（资产页）。
现状要点：集视图一镜一行，首帧和尾帧并排，右边是文字、表情、对白、人物、衣/鞋/甲/妆/发五个小格，以及首帧和视频两段提示词的折叠；右侧检查器有"当前 v1 / 新版本 v2"、"设 v2 为当前"、"全屏对比 C"、"提示词差异"；顶部有"整集出首帧/尾帧/视频"和"串播"；镜与镜之间有"S1 尾帧 → S2 首帧 · 未衔接"分隔线。资产页有大定妆图、身份底板、造型卡、单品分类 tab，以及"排期：角色 × 集"矩阵。

| # | 改进 | 现状问题 | 来源与引用 |
|---|---|---|---|
| 1 | **镜头行的人物区改成显示"角色头像 + 造型名 + 造型主图"（如 林晚 · 造型A），点一下可以切换本镜造型。** 衣/鞋/甲/妆/发五个小格挪到悬浮层或检查器的"人物"tab。缺图的单品在造型名旁边用一个红点汇总提示 | 现在一行里有五个小格，其中"衣""鞋"空着，"甲"是红框，看不出这一镜用的是哪套造型 | 小云雀：分镜拆分自带"分镜出现的角色妆造"；"同一角色在资产库里可以有多个形象版本，在故事板里可以按分镜需要选择不同版本"（§1.1、§1.2，高/中） |
| 2 | **把"S1 尾帧 → S2 首帧 · 未衔接"分隔线做成按钮：「用上一镜尾帧作本镜首帧参考」**，点了直接写入 S2 的首帧参考并标成"已衔接" | 现在只显示状态，不能操作 | 小云雀"快速截取上一镜头的尾帧作为下一镜头的首帧参考"（高）；Higgsfield "chaining the final frame"（高）；Flow "Jump To"（中） |
| 3 | **改造型或单品时，弹出影响范围（"影响 N 集 / M 镜"），并提供"只更新引用 / 批量重出受影响镜头"两个选项** | 资产页显示了"用于 338 镜"，但改动之后不会提示，也不能连带处理 | 小云雀"改完后所有该角色出场的剧集画面 / 声音会一键同步更新，无需逐个镜头替换"（高） |
| 4 | **集视图加一条底部镜头胶片条**：每镜一个首帧小缩略图加状态点（已出 / 待选 / 打回 / 已衔接），点击跳到对应镜头行，可在这里增删镜头 | 一集镜头多时要长距离滚动，看不到整集全貌 | 小云雀"底部分镜栏支持灵活增加、删除镜头"（高）；智能预演"以绿点标记"（高） |
| 5 | **"整集出首帧/尾帧/视频"和多镜批量操作改成两步：先勾选（全选或筛选），再弹确认框（镜数、总时长、模型、分辨率、预计耗时）；任务失败的镜头集中显示，提供"一键重试失败"** | 现在的批量按钮一点就执行，没有确认，也没有失败汇总 | 火宝 "pre-generation confirmation (shot count / total duration / model / resolution)"、"failed tasks can be retried in one click"（高）；小云雀"在列表视图全选**批量生成**"（高） |
| 6 | **"重出首帧"改为一次出 2–4 张候选**，在检查器里排成一排，点一张后"锁定为当前"。保留现在的 v1/v2 并排和全屏对比 | 现在每次只出一版，比较只能两两进行 | Dreamina "four variants per prompt; lock the winning frame"、"shortlist the best panel for each beat"（中） |
| 7 | **重出弹窗加四个短字段：改哪里 / 保留什么 / 想要什么 / 不要改什么。** 这只是表单结构，内容仍由 Qwen 侧填写和编译，画布只负责提交 | 现在只能直接改整段长提示词，看不出这次到底改了什么 | 小云雀片段重拍"建议说清楚四件事：改哪里、保留什么、想要什么效果、不要改什么"、"一次重拍不要贪多"（高） |
| 8 | **镜头的结构字段做成一排 chips**：时长 · 景别 · 机位 · 运镜 · 焦段（有就显示），点了可以就地改。行内不再放成段文字 | 镜头标题行混写成"S1 · 缓慢上摇 · 时长 10s / 机位 低机位仰拍"，字段不统一 | 小云雀 2.0"每个分镜标注了时长、景别、机位、角色动作、画面色彩和焦段"（中）；可灵 Custom Multi-Shot 的 Duration / Framing / Narrative / Camera Movement 四字段（高） |
| 9 | **提示词里的角色和造型用 @chip 显示**（如 @林晚·造型A），悬停显示参考图，点击跳到资产页 | 提示词是纯文本，看不出哪些资产被注入了 | 小云雀"使用 @ 来引用资产库中的角色和场景"（高）；可灵 "@"/"Add from Element Library"（高）；火宝 "`@character` references map to reference images automatically"（高） |
| 10 | **资产页按"角色 → 造型（子形象）→ 单品"分层**：造型 A/B/C 并排成大卡，每张卡显示主图和它包含的单品缩略图；单品卡加"应用到造型…"的右键或按钮 | 现在只有一张"默认"造型卡，单品区和造型的关系不直观 | 小云雀画布"可以选择已有角色/场景作为其子形象"、"右键选择「应用到角色」…进行主图替换"（高）；可灵把服装单列为 Costumes 主体（高） |
| 11 | **身份底板统一成"1 张正面主图 + 最多 3 张补充角度"**，正面必填，用徽标标明主图 | 现在显示"正 / 3/4"加"还缺 侧·背"，规则不明确 | 可灵 "at least 2 reference images"、主图 "front-facing"、补充 1–3 张 "from different angles"（高） |
| 12 | **集视图左侧（或顶部"本集造型"处）加可折叠的"本集资产栏"**：本集出场角色的大头像和本集造型，可以拖到镜头行上换造型 | 顶部"本集造型"只有几个小 chip，没法拖拽，也看不清造型 | 小云雀重制转绘"分镜工作台左侧是角色与场景资产，中间是片段脚本分镜，右侧可在…对比视图间切换"（高） |
| 13 | **"串播"拆成两档：① 预演串播，按每镜时长连续播放首帧→尾帧静帧（视频还没出也能看节奏）；② 成片串播。** 集完成后显示"播放 / 继续编辑 / 导出" | 尾帧要等出视频才有，看不到整集节奏 | 小云雀智能预演（高）；即梦"串联关键镜头，提前把控画面衔接与叙事节奏"（中）；LTX "animated storyboards…exported as MP4"（中）；重制转绘"已经完成的分集可以播放、继续编辑或下载"（高） |
| 14 | **左侧集列表每一项显示生产进度（如 首帧 12/18 · 视频 0/18 · 审 0/6），并能按"有待选 / 有打回"筛选** | 现在只有色点加"审 0/6"，色点的含义要猜 | 火宝 "The episode list shows the production status of every episode"（高） |
| 15 | **加快捷键面板（? 键打开）**：J/K 切上一镜/下一镜，[ / ] 切集，C 全屏对比（已有），Enter 设为当前，R 重出，Shift+R 批量重出选中镜头 | 只有"全屏对比 C"有提示 | 小云雀画布有快捷键面板，"Windows版本可将`cmd`替换为`ctrl`"（高） |

**不建议跟进的：** 3D 导演台（小云雀、即梦都有，但和我们"Qwen 写内容、画布只做系统"的分工无关，成本高）；聊天式改稿（"添加到对话"）。后者与本项目分工冲突：内容由 Qwen 负责，画布不做对话改写。

---

## 附：来源清单

- 小云雀教程目录 https://www.xiaoyunque.com/tutorials
- 小云雀 Web 产品手册 https://www.xiaoyunque.com/tutorials/web-manual
- 小云雀短剧 Agent 画布 https://www.xiaoyunque.com/tutorials/short-drama-agent-canvas
- 小云雀智能预演 https://www.xiaoyunque.com/tutorials/short-drama-agent-smart-preview
- 小云雀重制转绘 https://www.xiaoyunque.com/tutorials/short-drama-remake
- 小云雀 3D 导演台 https://www.xiaoyunque.com/tutorials/short-drama-agent-3d-director
- 小云雀 Seedance 2.0 / 2.5 手册 https://www.xiaoyunque.com/tutorials/seedance-2-0 、https://www.xiaoyunque.com/tutorials/seedance-2-5
- 腾讯新闻 小云雀 2.0 实测 https://news.qq.com/rain/a/20260528A07MOU00 ；腾讯新闻 https://news.qq.com/rain/a/20260326A08BMA00
- 爱范儿 https://www.ifanr.com/1658787 ；搜狐时间线 https://timeline.sohu.com/news/kvIXh6ngRy
- IT之家 即梦短剧工作室 https://ithome.com/1/018/013.htm ；新京报 Octo https://www.bjnews.com.cn/detail/1775720323129620.html
- Dreamina https://dreamina.capcut.com/resource/ai-image-generator-for-storyboard-frames 、https://dreamina.capcut.com/resource/first-last-frame
- 可灵 https://kling.ai/quickstart/klingai-element-library-3-user-guide 、https://kling.ai/quickstart/klingai-video-3-model-user-guide 、https://kling.ai/quickstart/ai-video-start-end-frames 、https://kling.ai/blog/kling-video-3-multi-shot-guide
- 海螺 https://ai-bot.cn/sites/48346.html
- LTX https://website.ltx.studio/studio/platform/ai-storyboard-generator ；CineD https://www.cined.com/ltx-studio-deep-dive-the-first-ai-based-full-editing-suite
- Runway Academy https://academy.runwayml.com/tutorial/storyboard-featured-workflow
- Higgsfield https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-use-popcorn
- Google Flow FAQ https://labs.google/fx/en-gb/tools/flow/faq
- 火宝短剧 https://github.com/chatfire-ai/huobao-drama

**抓取失败（未计入结论）：** 知乎专栏（403）、CSDN 部分文章（521）、ltx.io 博客（Header overflow）、vidmuse 文档（403）、B 站和 YouTube 视频正文。
