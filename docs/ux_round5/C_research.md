# UX5-C 调研：资产与一致性、二次修改与版本、流程与界面细节（2026-10-31）

> 目的：给第 5 轮 UX 提供外部依据。覆盖三块：资产中心怎么组织、资产改了以后下游镜头怎么办、主流程和界面细节。最后提炼成 22 条可落地的原则。
> 不重复的内容：小云雀全流程、可灵主体库的建主体步骤、LTX Storyboard 面板四要素、OiiOii 已经写在 `canvas_research_v3.md`、`xyq_flow_full.md`、`xyq_walkthrough.md`、`ux_round4.md`。本文只补这些文档里**没写的部分**；需要沿用的旧结论会注明"见 v3"。
> 方法：逐条读官方文档、帮助中心、更新日志和媒体或社区评测。每条结论附原文短引（不超过 15 词或 15 字）、链接和置信度。
> 置信度分三档：
> - **高**：官方文档或帮助中心正文，我亲自抓到了原文。
> - **中**：官方页面，但正文抓不到（403、重定向或头部溢出），引文来自搜索引擎对该官方页的摘录；或官方博客、营销页。
> - **低**：第三方评测、新闻稿、论坛帖，或由前两类推断。
> 限制：
> - 没登录任何网站，没点任何同意或付费。
> - 以下官方页 WebFetch 被拒（403 或解析失败）：help.runwayml.com、help.ltx.io、ltx.io 博客、freepik.com/ai/docs。这几处只能用搜索摘录，统一标"中"。
> - 海螺、Hedra、Vidu 的资产库界面没找到官方文档，单独列在 §6。

---

## 0. 五句话结论

1. **资产的结构各家基本一致**：每个资产是一张卡，有名字（库内唯一）、类型、2–8 张参考图和一段描述；在提示词里用 `@` 引用。可灵和 Flora 还多一个字段：可灵是**音色**，Flora 是**使用守则**。服装在可灵里是一个独立的主体类型（§1）。
2. **"资产改了，下游自动全改"只出现在营销文案里**：LTX 写的是 "propagate to all tagged instances"，即梦写的是"一处修改、全链路生效"。真正写进文档的节点工具（Flora、Runway Workflows）都是另一套规则：**下游不会自己重跑**，旧结果保留，由用户决定什么时候重跑；还可以把某个节点锁住，让它不参与重跑（§2.1）。
3. **成熟的影视管线（ShotGrid、Figma、Houdini）用的都是同一个模型**：镜头引用的是资产的**某一个版本**。上游出了新版本，下游只会被**标成"过期 / 有更新"**；用户先对比，再"更新所选"或"全部更新"；也可以故意钉在旧版本上（§2.2）。
4. **重跑的粒度分三档**：只跑这一个、跑这一个及其下游、跑整条链（Freepik Spaces）。运行前提示"会跑几个节点、总成本多少"（Flora）；运行中有一个可以取消的"进行中"面板（Runway）（§3）。
5. **对本项目最有用的组合是**：资产按版本号存；镜头记住自己用的是哪个版本；资产或 LoRA 一改，受影响的镜头标"有更新"，**但不自动重出**；用户在影响面清单里勾选，排进重出队列；已定稿的镜头默认跳过。这和 v3 的 N2 一致，本文补上了外部依据和状态设计（§4）。

---

## 1. 资产与一致性：各家怎么组织

### 1.1 逐产品

| 产品 | 发现 | 原文短引 | 来源 | 置信度 |
|---|---|---|---|---|
| **可灵 主体库 3.0** | 主体类型里，服装和场景都是独立类型 | "Characters, Animals, Items, Costumes, Scenes" | [Element Library 3 指南](https://kling.ai/quickstart/klingai-element-library-3-user-guide) | 高 |
| | 角色主体可以绑定音色（上传音频或从音色库选），也可以选"无声" | "bind the specific voice from an uploaded audio file" | 同上 | 高 |
| | 卡上要填：音色、名称、描述（可以 AI 自动写） | "voice tone, name, description, and other details" | 同上 | 高 |
| | 名称在库内唯一 | "Each name must be unique" | 同上 | 高 |
| | 一次生成能带的主体数有上限：视频不带输入视频时最多 7 个，带了输入视频最多 4 个；图像最多 10 个 | "you can upload up to 7" | 同上 | 高 |
| | 已经给了首帧或首尾帧时，还能再绑 3 个主体 | （同页 Video 3.0 小节，原文为改写） | 同上 | 中 |
| | 文档没说编辑主体后，已经生成的结果会不会变 | — | 同上 | 高（确认没写） |
| **LTX Studio Elements** | 类型有角色、物体、地点、风格等，可以跨项目复用，也可以在组织内共享 | "reuse across projects or share across your organization"（搜索摘录） | [Elements & Brand Kit 分类](https://help.ltx.io/hc/en-us/categories/35331831779602-Elements-Brand-Kit) | 中 |
| | 从剧本生成故事板时，会自动识别角色、物体、地点，并挂上对应的 Element | "automatically identifies characters, objects, and locations"（搜索摘录） | [Introduction to Elements](https://help.ltx.io/hc/en-us/articles/33578393195922-Introduction-to-Elements) | 中 |
| | 更新的入口：在 Elements 工作区选中资产 → 点「Replace Image」 | "Click "Replace Image" to update the visual" | [Getting Started with Elements](https://ltx.io/blog/getting-started-with-elements) | 中 |
| | 官方宣称改一次、所有打了标签的镜头都跟着改 | "Update once, propagate everywhere." | [Consistent Character](https://ltx.io/blog/how-to-create-a-consistent-character) | 中（营销文案，未见操作细节） |
| | 第三方评测：改了之后仍然要重出，不能就地编辑 | "changes still require regeneration rather than editing" | [Luma 评测](https://lumalabs.ai/news/ltx-studio-review) | 低（竞品写的评测） |
| | 第三方评测：生成前没有用 `@` 打标签，是不一致的主要原因 | "primary cause of the character inconsistency" | 同上 | 低 |
| **Flora Elements** | 每个 Element 最多 8 张同一主体的图 | "add up to 8 images of the same subject" | [Flora Elements](https://docs.flora.ai/editor/elements.md) | 高 |
| | 卡上有类别和**可选的使用守则**（写这个资产该怎么用、哪些细节重要） | "describe how the Element should be used" | 同上 | 高 |
| | 默认私有，可以共享到工作区 | "share an Element to your workspace" | 同上 | 高 |
| | 引用有两种方式：提示词里提及，或者在节点的选择器里换 | "open the node's picker" | 同上 | 高 |
| | 删除资产时，会把它从所有引用它的节点上解绑 | "unbinds it from any canvas nodes" | 同上 | 高 |
| **Higgsfield Soul ID** | 训练用 20–80 张同一人的照片，几分钟训完 | "Upload 20 or more photos" | [帮助中心](https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-create-and-use-a-soul-id-character) | 高 |
| | 少而干净的图，好过多而杂的图 | "clean, varied photos outperforms" | 同上 | 高 |
| | 一个 Soul ID 只能装一个人；多人场景要用 Elements | "A Soul ID holds one person" | 同上 | 高 |
| | 训练好的角色会自动出现在视频端的 Elements 里，用 `@` 调用 | "appear in Elements automatically" | 同上 | 高 |
| | 官方对一致性的预期是"明显是同一个人"，不是像素级相同 | "clearly the same person" | 同上 | 高 |
| | 在 Soul Cinema 里可以更新已有角色，不用从头重训 | "refreshes the character without training"（搜索摘录） | 同上（搜索摘录） | 中 |
| | 第三方说法：不同 Soul 模型之间不通用，换模型要重训 | "must be retrained for Soul Cinema"（搜索摘录） | [frankx 指南](https://www.frankx.ai/guides/higgsfield-soul-id-character-consistency) | 低 |
| **Krea 训练** | 最少 3 张，10–30 张效果更好 | "at least 3 images" | [Krea Training](https://www.krea.ai/docs/user-guide/features/training.md) | 高 |
| | **训练风格时用的模型，就是唯一能用这个风格出图的模型** | "the only model your custom style can generate with" | [Krea Style Guide](https://www.krea.ai/docs/Style-guide/Style-Guide.md) | 高 |
| | 训角色时，所有训练图要穿同一套衣服 | "in the exact same attire" | 同上 | 高 |
| | 补图可以继续精修模型 | "uploading additional images for more accuracy" | Krea Training | 高 |
| **OpenArt Characters** | 自定义角色模型用 4–100 张样图训 | "from 4 to 100 sample images" | [openart.ai/characters](https://openart.ai/characters) | 高（官方产品页） |
| | 一键出 9 个角度的多视图 | "makes 9 different angles" | 同上 | 高 |
| | 换了模型，已保存的角色照样能打标签使用 | "whichever model you pick" | 同上 | 高 |
| | Director 模式：对某一场提的修改只改那一场 | "changes only that scene" | 同上 | 高 |
| **即梦 短剧工作室** | 一个角色可以有多个形象，按剧情划分 | "一个角色会有多个形象" | [人人都是产品经理](https://www.woshipm.com/ai/6485581.html) | 低（实测文） |
| | 新手常常做到中途才发现缺素材、造型冲突 | "做到一半才发现" | 同上 | 低 |
| | 官方宣传：改一处，整条链路都生效 | "一处修改、全链路生效" | [IT 之家](https://ithome.com/1/018/013.htm) | 低（新闻稿，没写怎么触发） |
| **Seko 2.0（商汤）** | 生成下一集时保持人物和场景一致 | "保持人物和场景一致" | [新浪/智东西](https://news.sina.cn/ai/2025-12-15/detail-inhawtsc1849603.d.html?vt=4) | 低（新闻稿） |
| | 在分镜图上就地做画布编辑和对口型 | "画布编辑和对口型" | 同上 | 低 |
| **Vidu 参考生视频** | 最多 7 个主体，每个最多 3 张图；用 `@subject{id}` 引用 | "reference them in the prompt using"（ComfyUI 节点文档，搜索摘录） | [Comfy 文档](https://docs.comfy.org/ko/built-in-nodes/Vidu2ReferenceVideoNode.md) | 中 |
| **Runway** | Gen-4 References 主要面向角色和地点，提示词里用 `@tag` 引用 | "using the '@tag_name' format"（第三方） | [imagine.art](https://www.imagine.art/blogs/how-to-use-runway-gen-4-references) | 低 |
| **Hedra** | 多人画面里，要在提示词里写明是谁在说话 | "make the intended speaker unambiguous" | [Speaker selection](https://hedra.com/docs/pages/app/content-creation/speaker-selection) | 高 |

### 1.2 横向对照：资产卡上都有哪些字段

| 字段 | 可灵 | Flora | LTX | Higgsfield | 小云雀（见 v3 / XYQ） | 本项目建议 |
|---|---|---|---|---|---|---|
| 名称（唯一） | ✓ | ✓ | ✓ | ✓ | ✓ | ✓，`@` 用它 |
| 类型 | 角色 / 动物 / 物品 / **服装** / 场景 | 类别 | 角色 / 物体 / 地点 / 风格 | 只有角色 | 角色 × 造型、场景 × 子场景 | 角色、造型（服装）、场景、子场景、道具、音色、风格预设 |
| 参考图 | 2–4 张 | ≤8 张 | 1 张主图 | 20–80 张（训练用） | 1 张立绘 | 1 张定妆主图 + 若干辅图 |
| 描述 | ✓（可 AI 写） | — | — | — | 结构化外观描述 | 结构化外观描述（由写作方提供，系统只存） |
| 使用守则 | — | ✓ | — | — | — | ✓（"这张图只代表脸，不代表服装"这类规则） |
| 音色 | ✓ | — | — | — | — | ✓，挂在角色上 |
| 出现位置 | — | — | — | — | 形象数、出现集数 | 出现集和镜头数，可以点击跳转（v3 P8/P9） |
| 版本 | 没写 | 没写 | 没写 | Soul Cinema 可更新 | 抽卡组 | **必须有**（§2） |

---

## 2. 二次修改与版本管理

### 2.1 AI 工具：上游改了，下游怎么办

| 产品 | 发现 | 原文短引 | 来源 | 置信度 |
|---|---|---|---|---|
| **Flora** | 下游节点不会自己重跑 | "Downstream nodes never re-run on their own." | [How Nodes Run](https://docs.flora.ai/nodes/how-nodes-run.md) | 高 |
| | 相连的节点保留现有结果，直到用户再次运行 | "keep their current output until you run them again" | 同上 | 高 |
| | 只运行一个节点时，不会带动它的上游 | "does not automatically run the nodes connected upstream" | 同上 | 高 |
| | 每次运行的结果都追加进生成历史，不会覆盖 | "added to that node's generation history" | 同上 | 高 |
| | **流向下游的是用户选定的那一版** | "The active generation is what flows downstream." | 同上 | 高 |
| | 运行前悬停提示：会跑几个节点、总共花多少 | "how many nodes will run and the total cost" | 同上 | 高 |
| | 一次点击最多连跑同一个节点 20 次 | "up to 20 times in one go" | 同上 | 高 |
| | 批量节点：每一项都是独立任务，有自己的历史；一次最多 100 项 | "Each item produces its own output" | [Batch Node](https://docs.flora.ai/nodes/batch-node.md) | 高 |
| | 余额不够跑完整个批次时，直接拒绝运行 | （同页，原文为改写） | 同上 | 高 |
| | 可以把画布上的多步流程打包成可复用的"技法"（定义输入和输出） | "define inputs, define outputs, and publish" | [Techniques](https://docs.flora.ai/nodes/techniques.md) | 高 |
| **Runway Workflows** | 可以锁住某个节点，重跑整个工作流时它不会重新生成 | "won't regenerate on Workflow re-runs"（搜索摘录） | [Runway 帮助](https://help.runwayml.com/hc/en-us/articles/45763528999699) | 中 |
| | 同时跑多组时，右侧弹出 Active Runs 面板，可以看进度、可以取消 | "track progress and cancel runs"（搜索摘录） | 同上 | 中 |
| | 每次发布都生成一个带独立 ID 的版本；之后在应用里改工作流，不影响已发布的版本 | "Each publish creates a version with its own ID." | [Runway Dev Workflows](https://docs.dev.runwayml.com/workflows/) | 高 |
| | 某一步失败时，会报出哪个节点失败、为什么失败，已经完成的输出照常返回 | "outputs, node errors, and cost" | 同上 | 高 |
| **Freepik Spaces** | 三种运行粒度：只跑这个节点、跑整条工作流、跑这个节点及其下游 | "Run Downstream"（搜索摘录） | [Getting started with Spaces](https://www.freepik.com/ai/docs/your-first-space) | 中 |
| | 自动保存，没有保存按钮 | （搜索摘录，原文为改写） | 同上 | 中 |
| | 连线禁止成环 | "prevents circular loops"（搜索摘录） | [Nodes & connections](https://www.freepik.es/ai/docs/nodes-and-connections) | 中 |
| **LTX** | 官方建议先用 Retake 局部重做；评测说它的思路是"接受重出，但尽量缩小重出范围" | "tries to minimize its scope" | [Luma 评测](https://lumalabs.ai/news/ltx-studio-review) | 低 |
| **Krea / Higgsfield** | LoRA 或身份模型和训练它的底模绑死，换底模就要重训（Krea 是官方说法；Higgsfield 各页说法互相矛盾） | 见 §1.1 | — | 高 / 低 |
| **Flora 生成历史** | 用户可以清理过去的生成结果和不要的资产 | "storage and generation history" | [Canvas at scale](https://flora.ai/updates/canvas-at-scale) | 高 |

### 2.2 非 AI 的成熟做法

| 系统 | 发现 | 原文短引 | 来源 | 置信度 |
|---|---|---|---|---|
| **ShotGrid / Flow Production Tracking：Breakdown 应用** | 列出场景里引用的所有内容，标出哪些已经过期 | "tells you which items are out of date" | [Breakdown 文档](https://developers.shotgridsoftware.com/3c0c0ab6/) | 高 |
| | 多选后点"更新所选"，切换到最新版本 | "hit update selected" | 同上 | 高 |
| | 也可以有意钉在一个不是最新的版本上 | "Override to a version … not the latest" | 同上 | 高 |
| | 过期的条目上直接显示更新按钮 | "update button that is shown for outdated versions" | 同上 | 高 |
| **ShotGrid 状态** | 版本状态只有五个：N/A、待审、待导演审、已看、终审通过 | "Pending Review", "Viewed", "Final Approved" | [Autodesk 状态教程](https://help.autodesk.com/cloudhelp/ENU/SG-Tutorials/files/SG_Tutorials_tu_tracking_statuses_html.html) | 高 |
| | 状态的顺序要和审片流程一致 | "in line with your review process" | 同上 | 高 |
| | 版本被设为终审通过时，自动把所属镜头的状态也改成终审通过 | "if a linked Version's status is set to" | 同上 | 高 |
| | 用不到的状态可以删 | "some of these may not be needed" | 同上 | 高 |
| **ShotGrid 社区** | 有人提议对下游加一个"有新版本"的自定义状态，配合事件守护进程去标记 | "newer version available" | [社区帖](https://community.shotgridsoftware.com/t/how-do-i-know-when-there-is-a-newer-version-of-an-asset-that-is-used-in-a-shot/3222) | 低（社区帖） |
| **ftrack** | 2016 年论坛上，官方说 API 拿不到"当前版本"，只能按版本号或日期排序自己找 | "you will have to resort to loading the version number" | [ftrack 论坛](https://forum.ftrack.com/topic/709-how-to-query-current-assetversion-from-ftrack-new-api/) | 低（旧帖） |
| **Frame.io** | 新版本拖到旧版本上面就成了一个版本栈，打开时默认是最新版 | "the newest version will be ready to view" | [Versioning in Frame.io](https://help.frame.io/en/articles/9101068-versioning-in-frame-io) | 高 |
| | 版本历史里可以拖动排序，也可以从栈里移除某一版 | "Remove from stack" | 同上 | 高 |
| | 对比视图：并排、滑块叠加、像素差异；缩放和播放联动，也可以解除联动 | "linked zoom and playback controls" | [Comparison Viewer](https://help.frame.io/en/articles/9952618-comparison-viewer) | 高 |
| | 在对比视图里评论前，先点左边或右边的标题，确定评论挂在哪一版上 | （同页，原文为改写） | 同上 | 高 |
| | 资产状态：已通过、进行中、待审 | "Approved, In Progress, or Needs Review"（搜索摘录） | [Frame.io 博客](https://blog.frame.io/?p=2146) | 中 |
| **Figma 组件库** | 有更新时，资源库图标上出现蓝色角标 | "will display a blue badge" | [Review library updates](https://help.figma.com/hc/en-us/articles/360039234193) | 高 |
| | 默认先列出当前页的更新，可以切换到全文件 | "displays assets on the current page" | 同上 | 高 |
| | 审更新时默认并排对比，也可以切换成叠加 | "Side by side view" | 同上 | 高 |
| | 可以逐个实例更新，也可以一次全部更新 | "Update instance … or … Update all" | 同上 | 高 |
| | 只有发布了的更新才会通知下游 | "someone publishes an update" | 同上 | 高 |
| **Houdini PDG / TOPs** | 缓存状态分得很细：干净、待定（上游可能还会让它失效）、空、文件缺失、新、**过期（上游写了新文件）** | "upstream work items wrote new files" | [workItemCacheState](https://www.sidefx.com/docs/houdini/tops/pdg/workItemCacheState.html) | 高 |
| | "标脏所选"：下次运行时，这个节点的所有任务都会重跑 | "Marks the selected nodes as needing to recook" | [TOPs UI](https://sidefx.com/docs/houdini/tops/ui.html) | 高 |
| | 任务圆点用颜色区分：等待、运行中、完成、失败（红）、已取消 | "The work item is currently running." | 同上 | 高 |
| | 节点图标外圈是一个进度环 | "a ring around the icon shows the progress" | 同上 | 高 |
| **Unreal 派生数据缓存（DDC）** | 如果改动不在缓存键里（比如重新导入），就手动换一个 GUID，强制下次全部重建 | "Force the creation of a new GUID" | [InvalidateDeriveDataCacheGUID](https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/USkeletalMesh/InvalidateDeriveDataCacheGUID) | 高 |
| | 大数据不要直接放进缓存键（算键太慢），改用这个 GUID | "slow to create a key with big data" | 同上 | 高 |
| **Git LFS** | 文件锁：正在改的文件锁定在你名下，防止别人同时改 | "prevent other users from updating them" | [File Locking](https://github.com/git-lfs/git-lfs/wiki/File-Locking) | 高 |
| | 可锁定的文件在本地默认只读 | "make them readonly … automatically" | 同上 | 高 |

### 2.3 对本项目的含义（推断，置信度：中）

- **"引用"要记版本号**。镜头里存的应该是 `林晚·造型B@v3`，而不只是 `林晚·造型B`。不然就判断不出谁过期了。依据：ShotGrid Breakdown、Figma 实例、Houdini 缓存都是这么做的。
- **过期是一种标记，不是一个动作**。资产升到 v4 以后，用到 v3 的镜头显示"有更新"，不自动重出。依据：Flora 的 "never re-run on their own"、Figma 的更新要人接受、Breakdown 的"更新所选"。这正好也满足"已定稿的镜头不被静默改掉"（v3 N2）。
- **LoRA 或身份模型重训 = 资产出了一个新的大版本**。它和底模绑死（Krea），所以底模换了也算一次大版本变更。缓存键里要带上 `LoRA 版本 + 底模 + 预设`。像 DDC 那样：改动没进键里的，就手动换 GUID。
- **过期还要分来源**，参考 Houdini：
  - 上游资产变了（Stale）；
  - 文件丢了（Missing）；
  - 从来没出过（Empty）；
  - 上游还在跑、可能会变（CleanPending）。
  四种状态的用户动作不一样，但界面上最多用两种颜色表达（见 §4 原则 9）。

---

## 3. 流程简洁性与界面细节

| 主题 | 发现 | 原文短引 | 来源 | 置信度 |
|---|---|---|---|---|
| 运行粒度 | 只跑这个、跑到下游、跑全部，三档 | "Run Downstream"（搜索摘录） | Freepik Spaces | 中 |
| 运行前预估 | 悬停提示"会跑几个节点、总成本" | "how many nodes will run" | Flora | 高 |
| 进行中可见、可取消 | 右侧 Active Runs 面板 | "track progress and cancel runs" | Runway | 中 |
| 免费账户串行 | 一次只能跑一个生成任务，用户心里有预期 | "one generation at a time" | Flora | 高 |
| 失败隔离 | 告诉你哪个节点失败，其余输出照常返回 | "node errors" | Runway Dev | 高 |
| 批量 | 批量运行时，参数对每一项都一样；每项单独出结果 | "apply identically to every item" | Flora Batch | 高 |
| 审片状态 | 状态少而有顺序：待审 → 已看 → 通过 | "Pending Review" | ShotGrid | 高 |
| 打回 | Workfront 的决定选项里有"需要修改"（Needs work） | "Needs work"（搜索摘录） | [Workfront 文档](https://experienceleague.adobe.com/en/docs/workfront/using/review-and-approve-work/document-reviews-and-approvals/document-approval-status) | 中 |
| 对比 | 并排 + 滑块 + 像素差，播放联动 | "linked zoom and playback" | Frame.io | 高 |
| 进度可视 | 圆点颜色 + 节点外圈进度环 | "a ring around the icon" | Houdini | 高 |
| 大画布性能 | 上千个节点仍然要流畅；支持批量加块 | "projects exceeding 1200 nodes" | Flora | 高 |
| 深色主题底色 | 推荐 #121212，不用纯黑；层级越高，表面越亮 | "#121212"（搜索摘录） | [Material 2 Dark theme](https://m2.material.io/design/color/dark-theme) | 中 |
| 深色主题强调色 | 强调色要去饱和，在所有层级上文字对比度都要达到 4.5:1 | "at all elevation levels"（搜索摘录） | 同上 | 中 |
| 深色主题文字层级 | 高强调文字用 87% 白（二手说法） | "#FFFFFF (87% opacity)" | 二手 Medium | 低 |
| 降噪与密度 | 减少视觉噪声、对齐、提高导航的层级和密度 | "reduce visual noise, maintain visual alignment" | [Linear 重设计](https://linear.app/blog/how-we-redesigned-the-linear-ui) | 高 |
| 深浅主题同源 | 深浅两套主题用同一个生成器生成，色彩空间用 LCH，保证不同色相的亮度一致 | "LCH has the benefit" | 同上 | 高 |
| 密度可调 | 从很紧凑到很宽松，可以配置 | "from very condensed to more spacious" | 同上 | 高 |
| 深色下的图标 | 深色主题里，正文和中性图标调亮一些 | "lighter in dark mode" | 同上 | 高 |
| 新手痛点 | 做到一半才发现缺素材 | "做到一半才发现" | 即梦实测 | 低 |

已经确认、本轮沿用的规范（来自 `ux_round4.md`）：
- 文字最小 12 px；
- 按钮高度只用 24、28、34 三档；
- 胶囊圆角 999，矩形圆角用 `--r-1`；
- 1280–1920 宽度下都没有横向滚动。

外部资料里**没有找到**任何产品公开的间距或字号数值，所以不编造（见 §6）。

---

## 4. 给本项目的 22 条设计原则

适用位置：**资产**＝资产中心；**改**＝二次修改；**精**＝画布精修；**审**＝审片；**产**＝整集生产。

| # | 原则 | 具体做法 | 来源 | 适用 |
|---|---|---|---|---|
| 1 | **资产类型按"会被单独替换的单位"来拆** | 角色、造型（服装）、场景、子场景、道具、音色、风格预设，各自是一等资产。服装不要塞在角色描述里 | 可灵 "Costumes, Scenes"；小云雀"角色 × 造型"（XYQ） | 资产 |
| 2 | **资产卡字段固定 7 项** | 名称（唯一）、类型、主图、辅图、结构化描述、使用守则、版本。角色卡额外挂音色 | 可灵（名称唯一、音色）、Flora（守则、≤8 张图） | 资产 |
| 3 | **引用一律带版本号** | 镜头里存 `@林晚·造型B@v3`。界面上默认只显示名字，悬停才看到版本 | ShotGrid Breakdown、Figma 实例 | 资产 · 改 |
| 4 | **资产改了只"标记"下游，不自动重出** | 资产或 LoRA 一升版，用到旧版本的镜头显示"有更新"角标，不排任务 | Flora "never re-run on their own"；Figma 更新要人接受 | 改 |
| 5 | **影响面清单 = "更新所选 / 全部更新"** | 资产卡顶部写"有 12 镜用旧版 〔查看〕"。点开是镜头清单（缩略图 + 集·镜号 + 状态），可以勾选，再〔排进重出〕。已定稿的镜头默认不勾 | ShotGrid "update selected"；Figma "Update all" | 改 |
| 6 | **允许钉在旧版本** | 镜头可以"保持 v3"，角标从"有更新"变成"已钉"，以后不再提醒，直到用户取消 | ShotGrid "not the latest" 覆盖 | 改 · 精 |
| 7 | **LoRA 重训、换底模、改预设都算资产的大版本** | 缓存键 = LoRA 版本 + 底模 + 出图预设。改了键以外的东西（比如替换了训练图），就手动"作废缓存" | Krea 模型锁；Unreal 手动换 GUID | 改 · 产 |
| 8 | **升版前先做对比** | 资产 v3 和 v4 并排或滑块叠加，再拿一个代表镜头试出一张，看了再决定迁不迁 | Figma 并排 / 叠加；Frame.io 对比 | 改 |
| 9 | **过期的原因写在悬停里，颜色只用两种** | 只区分"要处理"和"等上游"两种颜色。原因（上游变了、文件丢了、从没出过）放在悬停里 | Houdini 缓存状态 | 审 · 产 |
| 10 | **每个槽位有一个"当前版"，下游只吃当前版** | 首帧有多张候选时，出尾帧和视频只用"当前"那一张。换当前版之后，尾帧和视频标"有更新" | Flora "active generation … flows downstream"；小云雀指定版（v3 P4） | 精 · 改 |
| 11 | **版本是栈，打开默认显示最新的已选版** | 帧槽角上写"3 版 · 当前 #2"。展开后可以排序、移除。旧版不删 | Frame.io 版本栈 | 精 · 审 |
| 12 | **对比视图三模式：并排、滑块、差异** | 播放和缩放默认联动，可以解锁。评论或打回要先选左边还是右边 | Frame.io Comparison Viewer | 审 |
| 13 | **锁定 = 不参与批量重出** | 定稿的镜头或帧上有锁标。批量重出和"全部更新"都会跳过它，影响面里显示"已锁 N 个，已跳过" | Runway "Lock node"；Git LFS 锁 | 产 · 改 |
| 14 | **重出三档粒度** | 〔只重出这一张〕〔重出这一张及下游（尾帧→视频）〕〔整镜重出〕 | Freepik Spaces 运行粒度 | 精 |
| 15 | **提交前写清楚范围和代价** | 批量条写"将重出 7 镜 · 首帧 7 / 视频 7 · 预计 35 分钟 · gpu3"。不写积分 | Flora 成本提示；v3 P10 | 产 |
| 16 | **进行中面板：可以看到、可以取消** | 顶栏一个"进行中 N"按钮，展开是任务列表（镜号、阶段、已等多久、〔取消〕）。不要散落在每一行 | Runway Active Runs；Houdini 进度环 | 产 |
| 17 | **失败按单元隔离** | 一镜失败不影响其他镜；写清楚失败在哪一步、原因是什么。"重试全部失败"做成一个按钮 | Runway node errors；v3 P11 | 产 |
| 18 | **审片状态最多 4 个，有顺序** | 未审 → 待改 → 通过（→ 已锁）。镜头状态由当前版本的状态自动推出来，不要人工改两处 | ShotGrid 状态和 Final Version trigger | 审 |
| 19 | **批量操作参数统一，结果分开** | 批量出首帧时，所有镜头用同一套预设；每镜的结果单独进各自的版本栈 | Flora Batch | 产 |
| 20 | **流程可以打包成"技法"或模板** | 例如"换装三步"（换造型 → 重出首帧 → 重出尾帧和视频）做成一个一键流程，输入是镜头加新造型 | Flora Techniques | 精 · 改 |
| 21 | **缺资产要在开工前暴露** | 整集开工前先查一遍资料：缺立绘、缺音色、缺子场景的，单独列出来，配一个"去补"按钮。不要做到一半才发现 | 即梦"做到一半才发现"；小云雀"请完善 N 个角色形象"（XYQ） | 产 · 资产 |
| 22 | **深色主题：层级靠表面亮度，强调色去饱和，密度高但对齐** | 底色不用纯黑，层级越高表面越亮。强调色去饱和，文字对比度至少 4.5:1。图标在深色下调亮一些。延续 UX4 的 12 px 下限和 24/28/34 三档按钮 | Material 2 Dark theme；Linear 重设计 | 全局 |

**落地优先级建议**：
1. 先做 3 + 4 + 5 + 13（版本化引用、只标记、影响面、锁）。这四条决定数据模型，晚做就要返工。
2. 再做 10 + 11 + 12（当前版、版本栈、对比）。
3. 然后做 15 + 16 + 17 + 21（生产可见性）。
4. 其余可以随做随加。

---

## 5. 不建议照搬的

| 做法 | 出处 | 原因 |
|---|---|---|
| "一处修改、全链路生效"（自动重出） | 即梦、LTX 营销文案 | 会静默改掉已定稿的镜头，和 v3 N2 冲突；而且这两家都没给出操作细节，证据弱 |
| 每个模型各有一个身份库，换模型就重训 | Higgsfield（第三方说法） | 我们的 LoRA 本来就和底模绑死。界面上应该明说"换底模 = 大版本"，而不是藏着不说 |
| 节点无限画布作为主视图 | Flora、Freepik、Runway Workflows | v3 N9 已经决定了，只借它们的"运行粒度 / 当前版 / 锁"语义 |
| 积分成本 | Flora、可灵 | 我们是本地算力，换成"时长 + 哪张卡"（v3 N8） |
| 对话式改项目 | Seko、即梦 | 违反"Claude 只写系统"的规则（v3 N4） |

---

## 6. 没找到（不做补全）

- **海螺（Hailuo）**：没找到官方的"已保存主体 / 角色库"文档。"每个项目 5 个角色"只是第三方说法，没核实。
- **Hedra**：没找到官方的 Elements 文档；"角色、服装、背景组件库"只来自第三方指南。
- **Vidu**：没找到"我的参考 / 保存主体"界面的说明，只有 API 层面的 `@subject` 用法。
- **Runway**：没找到 References 能不能"保存成命名资产、跨提示词复用"的官方说法。Scenario 帮助中心称截至 2025-12，Gen-4 References 只能通过 API 用（低置信）。
- **LTX、可灵、Flora**：都没写资产改了以后，旧镜头是自动更新还是要重出。LTX 只有营销句。
- **ftrack**：没找到"依赖版本过期提醒"的官方功能。
- **各产品深色主题的具体间距、字号、圆角数值**：没有公开的规范文档。Linear 只给了原则，Material 2 的透明度分档只有二手来源。
- **Seko**：官网没抓到，只有新闻稿。

---

## 7. 来源清单

AI 工具：
- 可灵 Element Library 3：https://kling.ai/quickstart/klingai-element-library-3-user-guide
- LTX Elements & Brand Kit：https://help.ltx.io/hc/en-us/categories/35331831779602-Elements-Brand-Kit
- LTX Introduction to Elements：https://help.ltx.io/hc/en-us/articles/33578393195922-Introduction-to-Elements
- LTX Getting Started with Elements：https://ltx.io/blog/getting-started-with-elements
- LTX Consistent Character：https://ltx.io/blog/how-to-create-a-consistent-character
- Luma 的 LTX 评测：https://lumalabs.ai/news/ltx-studio-review
- Flora Elements：https://docs.flora.ai/editor/elements.md
- Flora How Nodes Run：https://docs.flora.ai/nodes/how-nodes-run.md
- Flora Batch Node：https://docs.flora.ai/nodes/batch-node.md
- Flora Techniques：https://docs.flora.ai/nodes/techniques.md
- Flora Canvas at scale：https://flora.ai/updates/canvas-at-scale
- Runway Workflows 帮助：https://help.runwayml.com/hc/en-us/articles/45763528999699
- Runway Dev Workflows：https://docs.dev.runwayml.com/workflows/
- Freepik Spaces 入门：https://www.freepik.com/ai/docs/your-first-space
- Freepik Nodes & connections：https://www.freepik.es/ai/docs/nodes-and-connections
- Higgsfield Soul ID 帮助：https://higgsfield.ai/creator-hub/help-center/ai-models/how-do-i-create-and-use-a-soul-id-character
- frankx 的 Higgsfield 指南：https://www.frankx.ai/guides/higgsfield-soul-id-character-consistency
- Krea Training：https://www.krea.ai/docs/user-guide/features/training.md
- Krea Style Guide：https://www.krea.ai/docs/Style-guide/Style-Guide.md
- OpenArt Characters：https://openart.ai/characters
- Hedra Speaker selection：https://hedra.com/docs/pages/app/content-creation/speaker-selection
- Vidu 参考生视频（Comfy 节点文档）：https://docs.comfy.org/ko/built-in-nodes/Vidu2ReferenceVideoNode.md
- Runway References（imagine.art）：https://www.imagine.art/blogs/how-to-use-runway-gen-4-references
- 即梦短剧工作室（人人都是产品经理）：https://www.woshipm.com/ai/6485581.html
- 即梦短剧工作室（IT 之家）：https://ithome.com/1/018/013.htm
- Seko 2.0（新浪/智东西）：https://news.sina.cn/ai/2025-12-15/detail-inhawtsc1849603.d.html?vt=4

非 AI 系统：
- ShotGrid Breakdown 应用：https://developers.shotgridsoftware.com/3c0c0ab6/
- ShotGrid 状态教程：https://help.autodesk.com/cloudhelp/ENU/SG-Tutorials/files/SG_Tutorials_tu_tracking_statuses_html.html
- ShotGrid 社区帖：https://community.shotgridsoftware.com/t/how-do-i-know-when-there-is-a-newer-version-of-an-asset-that-is-used-in-a-shot/3222
- ftrack 论坛帖：https://forum.ftrack.com/topic/709-how-to-query-current-assetversion-from-ftrack-new-api/
- Frame.io 版本管理：https://help.frame.io/en/articles/9101068-versioning-in-frame-io
- Frame.io 对比视图：https://help.frame.io/en/articles/9952618-comparison-viewer
- Frame.io 博客：https://blog.frame.io/?p=2146
- Workfront 审批状态：https://experienceleague.adobe.com/en/docs/workfront/using/review-and-approve-work/document-reviews-and-approvals/document-approval-status
- Figma 库更新：https://help.figma.com/hc/en-us/articles/360039234193
- Houdini 缓存状态：https://www.sidefx.com/docs/houdini/tops/pdg/workItemCacheState.html
- Houdini TOPs 界面：https://sidefx.com/docs/houdini/tops/ui.html
- Unreal InvalidateDeriveDataCacheGUID：https://dev.epicgames.com/documentation/en-us/unreal-engine/API/Runtime/Engine/USkeletalMesh/InvalidateDeriveDataCacheGUID
- Git LFS 文件锁：https://github.com/git-lfs/git-lfs/wiki/File-Locking

界面规范：
- Material 2 深色主题：https://m2.material.io/design/color/dark-theme
- Linear 重设计：https://linear.app/blog/how-we-redesigned-the-linear-ui
