# 图像编辑 A/B 第 1 轮实测方案（A/B-1、2、3、12）

- 写方案：IMGEDIT-RESEARCH，2026-11-02
- 执行：ASSETUX，**19:10 之后开跑**
- 背景：总调度 fredw-2b 已定（DEEP_RESEARCH 的“需要决定”）：许可继续用 qwen-research（测试阶段、非商用）；2511 进 A/B 当后备；E-3 先跑 A/B-3、按数据定；本地扩写器只限 A/B；MOSS 不进人物主路径。
- 依据：docs/research/imgedit/DEEP_RESEARCH.md §D、§F3。

## 0. 总规矩（每项都适用）

| 项 | 规定 |
|---|---|
| 出图道 | **借 gpu36:1，只用这一条。**<br>原因：第一季出图分区全在 gpu33（partition.images：gpu33 = ep1–10），三条道 gpu33:0/1/3 都是主线，**一律不碰**。gpu36:0 继续做 ep08–10 视频。gpu36:2 是看图卡，留给本地 VLM 打分用。 |
| 借道命令 | `.venv/Scripts/python.exe tools/debug/lanes.py lend gpu36:1 ASSETUX 180 imgedit_ab ASSETUX`<br>借 180 分钟，到期由 sweep 自动收回。跑完立刻 `lanes.py release gpu36:1`。 |
| 借道前置检查 | 1. `lanes.py sweep`。<br>2. 确认 gpu36:1 当前没有正在跑的视频作业，有的话等它跑完；借道只是不再派新单，不杀在跑的。<br>3. 查 gpu36 视频积压：ep08–10 ready 视频超过 20 条时，先报总调度再借。 |
| 防抢 | 每张图交之前，确认 gpu36:1 的 ComfyUI 队列为空，沿用 tools/imglab/ab.py 的 lane_idle 写法。第一张要求道整条空闲 ≥ 120 s。 |
| 产物位置 | 只写 data/ab/imgedit/r1/<项>/。不写 takes.json，不写契约账本，不走生产作业，不设当前版本。 |
| 镜头范围 | 只用判定为非成人的单镜（ab.py is_adult 同口径）。底图取这些镜当前 active 的首帧。 |
| 图片外发 | 不外发。改写只发文字，走现有 prompt_rewrite，经 text_only_guard。 |
| 提示词 | **先冻结，再出图。**<br>第 0 步用现有改写接口，按下表的“中文意图”各改写一次，结果存进 data/ab/imgedit/r1/prompts.json。之后所有臂都用这同一份文字，只有 A/B-3 的两个变体例外。<br>中文意图是测试用的编辑指令（技术用例），不属于剧本内容。 |
| 冻结锁 | 新脚本放 tools/imgedit/ab_edit.py，scope = ab，照常过 freeze_guard 和 arch_scan。只读复用 edits.py 和 workflows.py 的构图函数，**不改生产代码**。 |
| 打分 | 共四层，见 §5：①身份分 Q1（锚分，对 L-086）；②像素指标；③本地 VLM（gpu36:2 看图卡）；④总调度亲审。 |
| 停止 | 遇到以下任一情况立即停，释放道，并报总调度：<br>- 总调度叫停；<br>- gpu36:0 视频报警；<br>- 连续 3 张出图失败；<br>- 借期剩 10 分钟。 |

## 1. 样本（四项共用一套，第 0 步固定下来写进 samples.json）

| 组 | 张数 | 选法 |
|---|---|---|
| P：林晚单人 | 6 | 特写 2、中景 2、全身 2。来源是 ep01–ep03 非成人单镜当前首帧，要求 Q1 已 pass，身份分本身没问题 |
| D：双人镜 | 2 | 林晚加另一角色同框，用来看串脸 |
| S：场景底图 | 2 | 场景资产底图，无人 |

编辑意图（中文，第 0 步送改写）：

| 代号 | 用于 | 中文意图 | 选区（0–1 相对坐标） |
|---|---|---|---|
| e1 换鞋 | P 全身、中景 | 把鞋换成黑色漆皮细高跟 | 框住鞋 |
| e2 改光线 | P、S | 光线改成从画面左侧来的柔和窗光 | 整张 |
| e3 换背景 | P、D | 背景换成夜晚的城市街道，人物不变 | 整张，B 臂另配人物 mask |
| e4 改表情 | P 特写、中景 | 表情改成淡淡的微笑 | 框住脸 |
| e5 加道具 | S | 桌上加一束白色郁金香 | 框住桌面 |
| e0 不改 | P、S | 保持画面完全不变 | 整张（只用于 A/B-12，测纯漂移） |

## 2. A/B-1：编辑的输入结构（检验 D1 是不是根因）

**臂**

| 臂 | 构图 |
|---|---|
| A0 现行 | 和 edits._generate 完全一致：原图作 init latent，denoise 0.55（medium），Turbo `turbo_sigmas(0.55)`。图像槽 = asset_refs 槽位（身份脸、设定图……）。提示词 = compose_instruction 的输出：冻结指令 + 中文锁段 + “图N是…”前缀 + image_suffix |
| B1 官方 | 照 Comfy 官方模板 image_qwen_image_2_1_image_edit：image_1 = 底图，image_2… = 同一套槽位参考，按顺序后移；**满 8 步**，cfg 1，resolution 0，latent 取 image_1 的尺寸。提示词 = 同一冻结指令，图片引用一律改成 `<image1>`、`<image2>`…；**不拼中文锁段，不拼风格后缀** |
| A0s（可选） | A0，denoise 0.35。只在时间够时跑，用来看“现行再轻一点”能不能救 |

**规模**：8 张（P6 + S2），每张 2–3 个意图（P 用 e1/e2/e4 中适用的，S 用 e2/e5），2 臂，2 个 seed，约 80 张。

**判定**：B1 胜出的条件是以下三条同时满足。
1. 改动到位率（VLM 判“点名的属性改了没有”）比 A0 高 ≥ 20 个百分点。
2. Q1 锚分的中位数 ≥ A0 − 0.01，且 Q1 通过率不低于 A0。
3. 总调度亲审时，偏好 B1 的配对 ≥ 60%。

B1 胜出后，A/B-2 和 A/B-3 都以 B1 为底。如果 B1 没胜出，A/B-2 和 A/B-3 以 A0 为底，并报总调度。

## 3. A/B-2：局部修改的做法

**跑之前先查一件事**：在 gpu36:1 的 ComfyUI 上调 `/object_info/TextEncodeQwenImage21`，看它有没有 mask 输入。结果写进 r1/notes.md。没有 mask 输入就不跑 B3。

**臂**（都在 B1 结构上，除非 A/B-1 判 A0）

| 臂 | 做法 |
|---|---|
| A 现行 | 整张改完，矩形框高斯羽化后贴回（edits.composite_region）。提示词加“只改需要修改的区域” |
| B1 标注 | 在 image_1 的 RGB 上用红色画框住区域的圈（docs.comfy.org 2.1：“Paint Pen strokes go on the image's RGB layer”）。提示词写“只修改 `<image1>` 中红圈内的[对象]：……”。出图后用羽化 mask 把框外贴回原像素（ImageCompositeMasked）。贴回用的是**不带红圈**的原图 |
| B2 裁切 | crop & stitch：框外扩 1.5 倍，裁出来，缩到约 1MP（对齐 32 的倍数）作 image_1 去编辑，再缩回原尺寸，羽化贴回原图 |
| B3 mask | 只在节点有 mask 输入时跑：原生 mask |

**规模**：只用带框的意图，即 e1 换鞋、e4 改表情、e5 加道具，每个意图 4 张图，共 12 个组合；3–4 臂，2 个 seed，约 72–96 张。

**判定**
- 框外 SSIM ≥ 0.995，且框外 LAB 均值差 ≤ 1.0。这一条是硬门槛，A 臂理论上本来就能满足。
- 接缝：VLM 判“框边缘有没有可见接缝或光影断层”，并由总调度亲审。
- 改动到位率。
- Q1（e4 改表情时最关键）。

到位率最高、并且接缝判“无”比例最高的臂胜出。

## 4. A/B-3：提示词里身份怎么写（E-3 / E-9，决定 HC-07 的写法）

**臂**（结构用 A/B-1 的胜者。指令由外部改写生成，两套系统提示词各改写一次，然后冻结）

| 臂 | 改写用的系统提示词 |
|---|---|
| V-A 现行 | config/recipes/edit_prompt_rewrite.md 原样：每次都写 identity unchanged 和 haze sky-blue waist-length straight hair 的外貌描述 |
| V-B 新写法 | 临时副本放 data/ab/imgedit/r1/edit_prompt_rewrite_vB.md，**不改 config**：外貌那一条换成“用一句总括保留：`<image1>` 中人物的身份、发型发色、姿势、构图与其余画面保持与输入图一致；面部身份与 `<imageK>`（身份脸）一致”，并删掉每次都写的画风句（E-3、E-4、E-9） |

**规模**：P 6 张 + D 2 张；P 跑 e1、e2、e3，D 跑 e3；2 个 seed，2 个变体，约 64 张。

**判定**
- Q1 锚分：V-B 中位数 ≥ V-A，并且 V-B 的通过率不低于 V-A。
- **HC-07 外貌锚点**：用 hair_attr（ns_agent.vqa.hair_attr）判发色和长度，加上 VLM 判“钻石水晶甲是否还在”（手可见时）。V-B 的保持率不得低于 V-A。这是硬门槛，不过就不改规则。
- 改动到位率：V-B ≥ V-A。
- 双人镜：VLM 判“两人的脸是否串了”。
- 总调度亲审偏好。

全部满足才把 E-3、E-9 写进规则文件，否则维持现行写法。

## 5. A/B-12：分辨率和对齐（偏移）

**臂**

| 臂 | 做法 |
|---|---|
| R-A 现行 | edits 的 `_fit_size(…, 1920)`，加 ImageScale center-crop 到画布 |
| R-B 官方 | 底图先缩放并裁到宽高都是 32 的倍数，resolution 0，latent 等于 image_1 的尺寸，不开 custom_size |
| R-C（可选） | resolution 1024（官方默认），latent 等于编码器输出的尺寸 |

**规模**：e0 不改，P 6 张加 S 2 张；再加 e4 改表情（框住脸），P 4 张；每组 2 个 seed，约 40–60 张。总时间不够时，这一项可以和 A/B-1 的 B1 共用出图，只加 R-A 一臂。

**判定**（不需要人看，全靠像素）
- 整体位移：用 cv2.phaseCorrelate 对原图和结果做相位相关，算 dx 和 dy。e4 只算框外。
- 框外 SSIM、LAB 均值差（ab.look_drift）。
- e0 下“什么都没改”时的 Q1 锚分变化。

R-B 胜出条件：|dx|、|dy| 的中位数 ≤ 1px，且明显小于 R-A。胜出后进 F1 的工作流默认参数。

## 6. 打分口径（四层）

| 层 | 工具 | 说明 |
|---|---|---|
| ① 身份分 | tools/gen_contract/remote_score.postflight_full（和 ab.py score 同口径，Q1 锚分对 L-086；Q1a 有就记） | ArcFace 打分，不占出图道。记锚分原值，不只记 pass 或 fail |
| ② 像素 | 新脚本里算：框外 SSIM、框外 LAB 均值差、phaseCorrelate 的 dx/dy | 选区从 samples.json 读，和出图时用的是同一个框 |
| ③ 本地 VLM | gpu36:2 看图卡，tools/vqa/server.py，经 ns_agent.vqa.client，只连 127.0.0.1 或 ssh gpu36 | 固定 5 问，回答只能是是或否：Q-a 点名的属性改到了吗；Q-b 选区外有没有变化；Q-c 框边缘有接缝或光影断层吗；Q-d 发色和发型还是雾霾天蓝及腰长直发吗（P 组）；Q-e 两个人的脸串了吗（D 组）。每图问 1 次，同一图文缓存 |
| ④ 总调度亲审 | 本地页面 data/review_pages/imgedit_ab/r1.html，生成后直接打开 | 每个配对左右随机摆放，不标臂名。点选“左好 / 右好 / 差不多”，一键生效，写进 r1/review.jsonl。页面顶部列 ①–③ 的汇总，可以展开看每张的分数。没过 Q1 的图标红但照常显示（A/B 要看全量） |

## 7. 时间和顺序（单道 gpu36:1）

1. **19:10–19:30 第 0 步**：借道和前置检查、samples.json、prompts.json（外部改写，两套各一份）、object_info 检查。先出 5 张实测单张耗时，按实际耗时排后面的计划。
2. **A/B-12 和 A/B-1 同批**（B1 的出图共用）：约 100–140 张。
3. **A/B-2**：约 72–96 张。
4. **A/B-3**：约 64 张。
5. 打分 → 生成审片页 → 释放 gpu36:1 → 向总调度交报告。

报告里要附契约逐项表：每项的臂、张数、①–④ 的汇总，以及胜出的结论和依据。

**估算**：生产单张 40 s–2 min（EDITOR_INTEGRATION §3-9），全部约 250–300 张，单道放不进 180 分钟。按以下顺序砍：
1. 先砍 A0s 和 R-C；
2. 再把 seed 降到 1 个；
3. 仍超时就只跑 A/B-1 和 A/B-12，A/B-2、A/B-3 第二晚再跑，并且**重新借道**，不续借超时。

## 8. 交付物
- data/ab/imgedit/r1/：samples.json、prompts.json、各臂出图、scores.jsonl、notes.md
- data/review_pages/imgedit_ab/r1.html：亲审页
- 给总调度的报告：四项各自的结论（胜出臂和数字）、要改进规则或工作流默认值的条目，以及没跑完的项和原因
