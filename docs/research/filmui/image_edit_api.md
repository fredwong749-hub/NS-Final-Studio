# 图像工坊 · 人工编辑功能：后端接口清单（给 UIRSI / IMGLAB）

交互稿：data/review_pages/filmui/image_edit.html（r2）。下表每个功能都能在交互稿里点到。
“已有”的判断依据是 services/ 下的路由（2026-11-02 实查）和 takes.json 字段；“要新做”标注由谁负责。

| 功能 | 交互稿位置 | 后端现状 | 接口 / 字段 | 负责 |
|---|---|---|---|---|
| 矩形选区局部重绘 | 工具栏“矩形”+ 右下“重绘选区” | **已有** | POST /api/edits {type:image, id:take:…, annotations:[box], …}：框内羽化贴回，框外像素不变 | — |
| 任意形状遮罩（画笔 / 套索 / 反选 / 羽化） | 工具栏“画笔 / 套索”，选项栏羽化、反选 | **要新做** | /api/edits 增加 `mask_png`（与原图同尺寸的 L 通道）或 `mask_ops`（归一化坐标）；`feather_px`、`invert` | UIRSI（接口）+ IMGLAB（合成） |
| 重绘强度 denoise | 左栏“修复 · 局部” | **部分已有** | /api/edits 已有 `strength`（目前是 low / medium / high 三档）；改成接收 0–1 的数值 | IMGLAB |
| 自动选区（人物 / 脸 / 手 / 衣服 / 背景） | 工具栏“自动” | **要新做** | GET /api/images/segment?file=&parts=person,face,hands,clothes,bg → 每类返回一个 mask png（SAM2 / 人体解析；脸、手可以复用 Q1 的人脸框和 Q5 的手部框） | IMGLAB |
| 修手（HandDetailer） | 一键修复 | **要新做** | POST /api/edits {action:"hand_detail"}；ComfyUI Impact HandDetailer 工作流 | IMGLAB |
| 修脸（FaceDetailer） | 一键修复（标“调参中”） | **调参中** | 同上，action:"face_detail"，带身份脸参考 | IMGLAB |
| 去杂物 | 一键修复 | **部分已有** | 框选部分走 /api/edits inpaint；任意形状要等遮罩接口 | IMGLAB |
| 换背景 | 一键修复 | **要新做** | action:"replace_bg" + 场景槽底板 + 背景 mask | IMGLAB |
| 重打光（Light-Migration） | 一键修复；需要先在「场景」槽放一张场景图 | **要新做** | action:"relight", light_ref=场景图 | IMGLAB |
| 色彩匹配到场景 | 一键修复 | **要新做** | action:"color_match", ref=场景底板（轻量，可以放在后处理） | IMGLAB |
| 换衣服 / 单品 | 一键修复：先选中衣服区域，再把单品放进「单品」槽 | **部分已有** | /api/edits 的 action "refs" 已能带参考图；需要加上遮罩 | IMGLAB |
| 放大 2× | 图台底栏“放大 2×”、一键修复 | **部分已有** | SeedVR2 3B（config/render_quality.json upscale_4k）目前只用于视频交付；要加图片入口 POST /api/images/upscale {file, scale:2} | IMGLAB |
| 裁切 / 改画幅（9:16 / 16:9 / 1:1）、景别快捷键 | 工具栏“裁切” | **部分已有** | 前端裁切即可；存成新版本要走 /api/edits 版本链（type:image, action:"crop", box） | UIRSI |
| 扩图（outpaint，四边可拖） | 工具栏“扩图” | **要新做** | action:"outpaint", pad:{t,b,l,r}（16 px 对齐） | IMGLAB |
| 姿势（DWPose 骨架，可拖关节） | 工具栏“姿势”（标“实验”） | **要新做（实验）** | GET /api/images/pose?file= → 关节坐标；POST /api/edits {action:"pose", keypoints}（ControlNet） | IMGLAB |
| 种子锁定 / 变体 / 批量张数 | 左栏“生成” | **已有** | POST /api/shots/{id}/frame-jobs、takes/{stage}/{n}/regen 已能指定 seed 和张数；“同种子微调”= seed 不变、只改提示词或参考强度 | — |
| 参考槽强度 | 右栏参考图 | **部分已有** | /api/shots/{id}/refs/apply 已有；逐槽 `weight` 字段要加 | UIRSI |
| 提示词片段库 | 提示词“片段库 ▾” | **已有（读文件）** | config/director/shot_spec_v2.yaml、lighting.yaml、camera_moves.yaml；要一个只读接口 GET /api/director/vocab | UIRSI |
| 负面要求 + cfg 1 时失效提示 | 左栏“生成” | **已有** | 配方里的 cfg 来自 render_quality.json；FLUX / MOSS 的配方由 IMGLAB 补 | IMGLAB |
| 缩放 / 平移 / 1:1、并排 / 滑动分割 / 叠加对比 | 图台底栏 | 纯前端 | — | UIRSI |
| 撤销 / 重做 | 页头 | 前端（编辑状态）+ **已有**（已提交的版本走 /api/edits/{id}/rollback） | — | UIRSI |
| 版本树（从任意一版分支） | 右栏“版本” | **部分已有** | /api/edits 的版本链有 parent；画布 takes.json 的 `parent` 目前全是 null，要求出图时写 parent | UIRSI（写 parent） |
| 每张图的元数据面板 | 右栏“元数据” | **部分已有** | takes.json 已有 seed / workflow / prompt / references / seconds / producer；**缺 steps / cfg / base**，出图时要写进 take | IMGLAB |
| 就地质检（Q1 / Q1a / G1 / Q5 / Q3 / 合成感）+ 按原因重出 | 右栏“质检”，片条每帧角上的圆点 | **已有** | GET /api/shots/{id}/takes/{stage}/{n}/checks；postflight.items + params.vqa_rounds[].judge（action / prompt_delta）；“按原因重出”= regen 时带上 prompt_delta | — |
| 合成感专项 | 质检里暂用 Q4 真人质感 | **要新做** | IMGFIX 合成感检测接入后作为独立一项 | IMGFIX |
| 设定图 / 单品的逐张质检 | 建人物模式的质检页 | **要新做** | 目前只有 final_choice.json 的 flux_ok / qwen_ok 和跨人物相似度 | ASSETMASTER |
| 快捷键表、操作完成提示 | “?”、底部提示 | 纯前端 | — | UIRSI |

## 数据说明
- 质检、元数据、版本都用 ep01-S01 的真实 takes.json（第 16–22 版里文件还在的 6 版）。第 17 版 Q1 没过（0.581 < 0.7），可以演示“没过的写原因 + 按原因重出”。
- 自动选区、骨架坐标都是按第 19 版首帧手工估的示意，实现时由分割和姿态模型给出。
