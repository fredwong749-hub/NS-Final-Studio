# Image Edit 页 · 同类产品研究（FILMUI，2026-11-02，L-115）

范围：生成 / 编辑界面怎么分区，参考图槽、历史与版本、遮罩局部重绘、对比、角色一致性怎么做。
没有截图权限的产品，下面的“截图要点”根据官方文档的描述和图注整理。置信度：高 = 官方文档；中 = 官方文档加第三方；低 = 只有第三方资料。

| 产品 | 布局 / 参数分区 | 参考图槽 | 历史 / 版本 | 遮罩重绘 | 对比 | 链接 | 置信度 |
|---|---|---|---|---|---|---|---|
| **Invoke** | 左边是参数面板（模型、提示词、尺寸），中间是画布，右边是 Layers / Gallery 两个标签 | 全局参考图放在提示词框下面；区域参考图是一种图层，用画笔遮罩限定作用范围；IP-Adapter 有 Full / Style / Composition 三种方式 | Gallery 标签存出图；图层可以开关 | 在画布上用画笔画遮罩，Regional Guidance 可以给每块区域单独写提示词 | 没有专门的对比视图 | [Invoke：参考图（IP-Adapter）](https://support.invoke.ai/support/solutions/articles/151000159340)；[Control Layers 发布说明](https://www.invoke.com/post/introducing-control-layers-a-powerful-ui-for-applying-regional-prompts) | 高 |
| **Midjourney Web** | 提示词条在顶部，参数（比例、风格化、版本）放在设置弹层里；Editor 单独一页 | 把图拖进提示词条，分到三个区：Image Prompt / Style Ref / Omni Ref；Omni 强度滑条 0–1000，默认 100；V7 起用 Omni 取代 --cref | Create 页按时间流列出全部出图，可以按批次查看 | 在 Editor 里做局部重绘（Vary Region）；文档说重绘带 Omni 参考的图之前要先移除参考 | 一批 4 张并排就是事实上的对比方式 | [Omni Reference 文档](https://docs.midjourney.com/hc/en-us/articles/36285124473997)；[Character Reference 文档](https://docs.midjourney.com/docs/character-reference)；[Style Reference 文档](https://docs.midjourney.com/docs/style-reference) | 高 |
| **Leonardo** | 左侧参数栏（模型 / 预设 / 尺寸 / 张数），中间是结果流 | Image Guidance 分 Content / Style / Character 三类参考，可以混用；Character Reference 一次只能用 1 张图 | 结果流加个人图库 | Canvas 编辑器支持 inpaint；Realtime Canvas 是草图实时出图 | 没有专门的对比视图 | [Leonardo：Image Guidance 帮助](https://intercom.help/leonardo-ai/en/articles/8497988-image-guidance)；[Content Reference 教程](https://leonardo.ai/learn/core-feature/how-to-use-leonardo-ais-content-reference-feature/) | 中 |
| **Krea** | Realtime：左边是输入（画布、参考），右边实时出结果，两边同时显示 | 可以放多张风格参考，实时混合；评测说角色一致性弱 | 会话历史 | 画布上涂色块驱动生成 | 左输入右输出，本身就是并排对比 | [Krea Realtime 文档](https://docs.krea.ai/features/realtime) | 中 |
| **Runway** | 生成页底部是提示词条，参考图在提示词条上方 | References 一次最多 3 张；提示词里用 @tag 或 “image 1 / image 2” 指代某张参考；单张参考就能在不同光照、地点下保持角色一致 | 资产库加会话 | — | — | [Runway：Gen-4 Image References 指南](https://help.runwayml.com/hc/en-us/articles/40042718905875-Gen-4-Image-References-Guide)；[Runway Academy：References](https://academy.runwayml.com/gen4/gen4-references) | 高 |
| **Ideogram Character** | 生成页里多一个 Character 参考槽 | 上传 1 张角色图，之后靠提示词出各种变体 | — | 有 Magic Fill / 重绘 | — | [Design Offset：Ideogram Character 发布报道](https://design-offset.com/20250729-ideogram-introduces-ideogram-character/) | 低 |
| **Adobe Firefly** | 左侧参数栏，中间结果 2×2 | Generative Fill 里的 References 偏风格；Structure Reference（构图 / 深度）和 Style Reference 是两个独立的槽 | 每次出 4 张，可以回看 | Generative Fill：先选区，再写提示词 | 一组 4 张对比 | [Adobe：Generative Fill 帮助](https://helpx.adobe.com/uk/firefly/web/work-with-images/edit-images/generative-fill.html)；[Photoshop Essentials：Structure / Style Reference](https://www.photoshopessentials.com/?p=35312) | 中 |
| **Freepik** | Image Editor 把多种工具放在同一个工作区，可以连续操作 | Retouch 里有 “Include Image”，把参考图放进遮罩区域 | 会话内可以连续编辑 | Retouch：先选区再描述；有 3 种遮罩方式 | — | [Freepik：Retouch 文档](https://www.freepik.com/ai/docs/retouch-images)；[Freepik：Image Editor 文档](https://cn.freepik.com/ai/docs/image-editor) | 中 |
| **ComfyUI 新前端** | 侧栏有 Queue（队列历史）/ Node Library / Model Library / Workflows（含模板）/ Assets（出图）几个标签 | 由节点决定（参考图就是 LoadImage 节点） | Queue 和 Assets 两处可查 | 有遮罩编辑器（Mask Editor） | — | [ComfyUI 界面总览](https://docs.comfy.org/interface/overview) | 高 |

## 角色一致性工具的共同点
1. **参考图分类型**：身份（脸）、风格、构图 / 结构、内容 / 物件，每类一个槽；Midjourney、Leonardo、Firefly、Invoke 都这样分。
2. **每个槽有强度**：Midjourney 用 --ow 滑条；Invoke 用权重加生效步数区间。
3. **提示词里能指代参考图**：Runway 用 @tag 或 image 1/2/3。
4. **单张参考就能起步**：Runway、Ideogram、Leonardo 的 Character Reference 都是单图起步；但生产上还是靠设定图（多视角）保证稳定。我们已有规则（L-086）：身份脸只接受脸部裁切。

## 落到我们 Image Edit 页的设计规则
- 三栏布局：左边“基座 + 预设 + 高级参数（默认收起）”，中间大图台 + 提示词，右边“参考图槽 + 资产库”。参考 Invoke 和 Firefly，但去掉图层的复杂度。
- 参考图槽固定 4 类：身份脸 / 设定图 / 单品 / 场景。每个槽显示原图缩略图、强度和来源，可以从资产库拖入；提示词里用 @脸 @设定 @单品1 @场景 指代（参考 Runway 的 tag）。
- 出图历史 = 一条 35mm 片条（风格 A）。每帧片边印基座、种子和次序；点一帧放到图台上，Shift+点第二帧进入并排对比。
- 遮罩重绘就在图台上画笔涂抹，不另开页面（参考 Freepik Retouch 和 Firefly Generative Fill）。
- 对比用并排两图，下方标注基座和种子（参考 Krea 的左右并排）；可以直接拿 Qwen-Image 2.1 和 FLUX 同种子出的设定图做 A/B。
- “人工生成人物”做成 5 步：写设定 → 定脸 → 设定图 → 造型单品 → 登记资产。每步的预设、参考槽和出图历史自动切换，最后一键登记（遵守“登录即本人 · 一键确认”）。
