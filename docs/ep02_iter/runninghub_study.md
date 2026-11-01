# RunningHub 工作流学习（RHUB，2026-10-31）

只读学习，范围是 runninghub.ai 上公开的 ComfyUI 工作流、MiniMax H3 Model API 和 Workflow API 文档。本文只整理技术和流程，不写也不评价剧本内容。

## 0. 方法与安全记录

- **访问方式**：项目方自己登录的独立 Chrome（调试端口 9471），用 CDP 连到他已打开的 RunningHub 标签页。
  - 守护脚本：`scratchpad/rh/rh_daemon.mjs`。
  - 小云雀标签页没有碰过。
  - 结束时已把标签页导航回首页。
- **拦截规则**：在该标签页上开启 Fetch 拦截。
  - 非 GET/HEAD/OPTIONS 的请求一律 `failRequest`。
  - 路径中含 run/queue/submit/create/save/clone/copy/fork/publish/pay/order/recharge/credit/subscribe/follow/like/comment 的请求也拦截。
  - 同时屏蔽 `window.open`。
- **拦截统计**：共拦截 384 次，放行 6461 个 GET。
  - 被拦的主要是统计上报（Google/ahrefs/haimawan），以及 `instance/access/auth`、`coupon/popup`、`likeOrCollect/status2`、`follow/isFollow`、`uc/apiKey/get`、`area/price/calculate`、`product/v2/rightList/compare` 等。
  - 08:47:58–08:48:46 这段时间，拦截日志里出现了 5 次 `likeOrCollect/create`（点赞/收藏某个 MODEL）和 3 次 `uc/follow/followUser`。这段时间我只在跑搜索接口，没有点击页面。可能是窗口里有人手动操作，也可能是页面自身行为。8 次全部被拦截，账户没有改动。
  - 完整日志：`scratchpad/rh/rh_block.log`。
- **单独放行的纯查询 POST**（都只读，不改数据）：

  | 接口 | 用途 |
  |---|---|
  | `/api/search/workflow` | 工作流搜索 |
  | `/api/portal/tag/tree`、`/api/sku/tag/query` | 分类树 |
  | `/api/portal/v2/getDictConfig`、`/api/system/getConfig` | 站点配置 |
  | `uc/getUserInfo`、`uc/userIdentity`、`uc/point/summary`、`message/user/unreadCount`、`uc/team/my-teams` | 页头登录态；不放行时页面报 "Response failed" |
  | `/api/area/price/table`、`/api/area/price/table/all` | 价格表 |
  | 以 `list/query/search/tree/detail/page` 结尾的接口 | 通配放行；其中包括页面自己发出的 `api/key/list`（Key 列表页的元数据，响应内容我没有读取） |
  | `/api/workflow/export` | 即详情页 "Download" 按钮。抓包确认它返回的就是工作流 JSON；本身免费，只会增加作者的下载计数 |

- **页面数量**：约 40 次页面导航，加约 70 次只读接口调用（25 次搜索、61 次导出、10 次价格表），远低于 150 页的上限，每次调用间隔 2–4 秒。
- **下载**：61 次导出请求中，55 个工作流 JSON 落盘，有 4 个返回 404（作者已下架）。
  - 目录：`data/ab/owner_workflows/runninghub/<作者>__<标题>/workflow.json`，每个目录附 `source.txt`（原链接）。
  - 索引：`_index.tsv`。
  - 没有执行任何文件。
  - 页面 Download 按钮触发时，浏览器还可能各存了一份到 Chrome 默认下载目录（Zhiyan Meow R2v 共 2 次）。
- **截图**：`data/ab/owner_workflows/runninghub/_screens/`（post_*.png、api_detail_minimax_h3.png、search_api_wf.png）。
- **页面中要求做事的文字**：作者描述里普遍有"填邀请码领 1000 RH 币"、"加 TG/微信群"、"网盘下载整合包"、"点击 Run"等。这些只记录，没有执行。
- **解析工具**：`scratchpad/rh/analyze.cjs`，汇总每个工作流的节点类型、模型、关键参数和作者说明，输出在 `scratchpad/rh/analysis.txt`。

---

## 1. 关键发现（先看这里）

1. **H3 社区的通用做法是"低清采样 → 3D latent 放大 → 高清短补采"**。具体有三种：两段式 sigma-split、SelfLift 单采样器、导演台。这样既快又清楚。我们现在是 24 步全尺寸直出（`official_base`），这条思路可以同时解决"迭代慢"和"细节软"。我们 gpu33 已有 `Comfyui_Minimax_h3_latent_Upscaler` 节点和 conv_v1 模型，`comfyui-SelfLift` 也装了，只差参数。
2. **H3 原生修脸已经成套**：`H3FaceTrackCrop → H3PerFrameDenoise → H3 重绘 → H3FaceStitch`。
   - 流程：逐帧 YOLO 跟踪脸，裁成 512/768 视频，用 H3 自己以 denoise 0.35–0.45 重绘 4–8 步，按脸的大小逐帧调整降噪，再羽化贴回。
   - 音频保持锁定，口型不变。
   - 对应我们的"脸部细节"、"S10/S8 身份分低"和"泛红"问题（重绘可以把脸颊颜色拉回参考）。
   - 我们已有 `face_yolov8m.pt`，只缺节点包。
3. **长镜头/续写**有三类做法：
   - `MiniMaxH3MotionContext`（上一段尾部 22 帧做运动上下文）；
   - 核心节点 `MiniMaxH3AddGuide`（帧序号可以用负数，从片尾倒数加引导帧）；
   - `ColorTransfer(mkl_lab, target_frame, 0.75)`，每段颜色对齐上一段。

   这些都能拿来解决 ep02 的"段间色漂/泛红漂移"和"单镜过长要拆"。
4. **口型**：T8 的 `MiniMaxH3AudioConditioningT8` 有 `mode=lock_source`。外部音轨（TTS 或配音）作为 drive_audio 锁住，音频 latent 遮罩为 0，H3 按这条音轨生成嘴型。这样能直接解决 v0 "TTS 和嘴型差约 2.5 s"的问题：先出 TTS，再让 H3 对着它演。RunningHub 自家的 "H3 RH Enhanced" API 也把 drive audio 设为必填，思路相同。
5. **云端通道**：官方 H3 API 价格见第 6 节，768P I2V 为 $0.077/s，RH Enhanced 768p 为 $0.04/s。
   - Workflow API 支持在 `workflow` 字段里直接提交完整工作流 JSON，不必先在网站保存；支持 24/48/84 GB 三档实例；共享 Key 默认 100 并发，按 GPU 秒计费。
   - 只能用于非成人镜头（项目规定成人镜头只在本地生成），而且官方 API 有审核。
6. **分镜表格式**：社区分镜工作流都把规则写成结构化格式交给 LLM，比如 9 镜"焦点接力"结构、"Next Scene:"逐镜续写、角色"3 个不可变视觉锚点"档案、主体/场景/运动/美学/风格五段式。第 7 节整理成可以交给写作模型的格式规则。

---

## 2. 按我们的问题归类（每条：工作流 → 解决什么 → 关键参数 → 我们有没有 → 对 ep02 的预期）

图例：✅ gpu33 已有 / 🟡 部分有（缺模型或节点包）/ ❌ 没有。所有链接形如 `https://www.runninghub.ai/post/<id>`。

### 2.1 迭代速度 / 卡顿慢

| # | 工作流（作者，使用量） | 链接 id | 解决什么 | 关键节点与参数 | 所需模型 | 我们有吗 | 对 ep02 的预期 |
|---|---|---|---|---|---|---|---|
| S1 | **MiniMax H3 I2V — Fast Cinematic Action (2-Stage Sigma-Split latent Upscale)**（Prompt Mastery，1441 次 / 36 收藏，H3 I2V 第一） | 2094290218739343361 | 低清只跑高 sigma 定结构，latent 放大后只跑低 sigma 补细节 | 两次 `MiniMaxH3ImageToVideo`（1344×768，73 帧）；`ManualSigmas` 三套：5 步 `0.9231,0.8780,0.8000,0.6316,0.3158,0`、4 步 `0.9035,0.8,0.6316,0.3158,0`、3 步 `0.9035,0.6316,0.3158,0`；`SplitSigmas(6)`；`LTXVSeparateAVLatent → MinimaxH3LatentUpscaler3D(target 1280×704, fp16) → LTXVConcatAVLatent`；turbo 4step LoRA 0.75；euler；T8 `DualClockSampler`（视频/音频各 4 步） | hybrid_fl2va_ref2va_b25-49 int8、fl2v lightx2v turbo 4step v0.1、latent_upscaler_3d_fp16 | 🟡 节点和 conv_v1 有；b25-49 混合模型没有，可以用我们的 fl2va int8 替代 | 单镜耗时预计降到现在 24 步的 1/3–1/4。注意：作者针对的是高动态动作 |
| S2 | **MiniMax H3 New 8-Step 768p Turbo**（Smart Bobo，827 / 22） | 2094073154908983297 | 8 步 768p turbo 的标准配方 | `BasicScheduler(beta, 8, 1)`；`MiniMaxH3SigmaShift(12, 3)`；turbo_8step_v1.0_768p LoRA 1.0；`MiniMaxH3Unified`（omni_reference）；`MiniMaxH3MemoryEfficientSageAttentionPatch`。作者推荐：一采 0.4MP + 二采放大 1.6 倍 → 720P；一采 0.5MP + 二采放大 2 倍 → 1080P | fl2va bf16、turbo 8step 768p | ✅ LoRA 有（v1.0/v1.1） | 和我们 Turbo 8 步相近，差别在 beta 调度和 12/3 shift。可以作为 Turbo 的对照组 |
| S3 | **H3_fl2va_10+3 Latent Upscaler** / **H3_ref2va_10+3**（celestial swan，49 / 70） | 2091189314620309505 / 2090800189666177026 | 首尾帧 + 两段式 | 一采 `BasicScheduler(simple, 20)` 后 `SplitSigmas(10)`，只跑前 10 步；放大后 3 步 `0.9035,0.6316,0.3158,0`；turbo 4step v1.1 768p 1.0；shift 12/3 | fl2va int8、turbo 4step | ✅ 全有（latent upscaler 用 conv_v1 替代 fp16 版） | **最容易直接上 ep02 FL2VA**：10+3 = 13 步，还保留了 20 步调度的前半段 |
| S4 | **minimax_h3_ref2va_fastH3_trim_latent_upscale** / **fastH3_ref2va**（有趣的80后程序员，107 / 131） | 2110657086861684737 / 2110249193162936322 | FastH3 蒸馏模型 8 步 | fasth3_trim_8step int8 或 fasth3_8step_v2；`simple 8`；SplitSigmas(4) + 3D 放大 + 3 步 | fastvideo_fasth3_* | 🟡 我们有 `fasth3_omniref_8step_pruned_int8`，trim/v2 版本没有 | Ref2VA 预览档 |
| S5 | **SelfLift 系列**（吴限宇宙 Ref Multimodal SelfLift LowVRAM 2K；Winters Gong H3selflift Drama Dedicated；郑中琦 SelfLift 双采音频锁） | 2098529015913426946 / 2114944498378846210 / 2113897588037844993 | 单个采样器里先低清后高清，显存低，画面直接 2K | `SelfLiftAvatarH3Sampler`（slmonker/selflift-Avatar）参数 [seed, cfg 1, steps 5–6, lowres_scale 0.4–0.6, rho 0–0.5, w_min 0.5, w_max 1, upscaler h3_upscaler_lms_v0.1 / latent_upscaler_3d_fp16_V2, …, global_stream/spatial, 4096, chunks 4]；`H3SigmaRefiner(1, 0.7, 0, cosine)`。**作者说明**：文戏总 6 步、transition 5，搭配字节 DMAD 4step LoRA 1.0；打戏 8 步、transition 6，搭配 lightx2v v0.1 0.6–0.7 | DMAD 4step full critic、h3_upscaler_lms_v0.1、H3电影感V2、MysticXXX V5.1 | 🟡 我们的 `comfyui-SelfLift` 是 `SelfLiftH3Sampler` 版（参数为 [seed, cfg, steps, lowres_scale, rho, w_min, w_max, upscaler, …]，singularity_V2_face_refine 就在用这个版本）；DMAD 4step 有（avg_rank_39 版）；lms upscaler 没有 | **文戏 6 步就能直出高清**，是 ep02 对白镜头提速的首选候选 |
| S6 | **All-in-One Director Console**（郑中琦，62/105） | 2115013398462570497 | 一个导演台节点管素材、分段、步数和开关 | `MiniMaxH3Director` + `MiniMaxH3DirectorSelfLift`（低清 6 步 → 3D 放大 → 高清 4 步，lowres 0.6，lms v0.1，rho 0，nearest）+ `MiniMaxH3DirectorFaceRefine`（见 2.4）。默认 b25 + DMAD 0.80 + Mystic V1 0.45，Euler/beta/10 步，CFG 1，shift 12/3；续接段间引导 22 帧 | AIMixer/ComfyUI_MiniMaxH3_Director | ❌ | 结构值得参考（第 8 节），节点本身作者注明"未测试" |
| S7 | 显存/速度补丁（多数工作流都带） | — | 3090 24G 跑 H3 不爆显存 | KJNodes `MiniMaxChunkFeedForward(2–8, 4096)`、`MiniMaxLowVRAMAttention(4)`、`MiniMaxH3MemoryEfficientSageAttentionPatch`、`BlockSparseAttention`、`ModelAttentionBackend`；`EasyCache(0.3, 0.15, 0.9)`（pearldotey fl2va-ss）；郑中琦的建议是"还爆显存就把 chunks 调成 4 或 8，seq 调成 2048" | — | ✅ KJNodes 里有前两个 | 全尺寸 2K 或二采时用得上 |

### 2.2 多腿鬼影 / 动作不连贯

| # | 工作流 | id | 要点 | 我们有吗 | 预期 |
|---|---|---|---|---|---|
| G1 | 文武双修 双采融合（yifan wang，35） | 2096179835811274753 | 8 步拆成"低 4 + 高 4"两套模型链：HIGH 用 Dasiwa REF2VA Hybrid 0.5 + Combat V2 0.49 + ErosMax 0.7 + Motion Repair 0.25 + 电影质感 0.2；LOW 用 Motion Repair 0.75 + Combat 0.7 + 电影质感 0.5；`SolAttnMiniMax(1.3, 0.2, 0.9, 12288…)`、`MiniMaxH3SemanticBridgeConfigT8`、`H3SigmaRefiner`；最后 `LatentUpscaler3D(megapixels 2)` | 🟡 Motion_Repair_V2 有 | 高 sigma 段管结构，低 sigma 段加大 Motion Repair。可以拿来对 S1 脚部重影做 A/B |
| G2 | 导演台的武打组（郑中琦） | 2115013398462570497 | 文戏默认关闭；打戏开 Combat V2 0.65 + Motion Repair V2 0.35 + Fight Flow 0.35 + speed slider 3 | 🟡 | ep02 是文戏，**Motion Repair V2 单独 0.25–0.35** 值得试 |
| G3 | AutoContext Unlimited Duration（哏啾的小拇歌，46） | 2101344066620731394 | `H3AutoContextSampler` 分段 + `H3SeamCorrection(medium, medium, 0.3, 15, 2)` 修段间接缝；Motion_Repair 0.6/0.25 双段 | ❌ | 长镜头接缝 |

### 2.3 身份一致（人物 / 角色）

| # | 工作流 | id | 要点 | 我们有吗 | 预期 |
|---|---|---|---|---|---|
| I1 | **Minimax_H3_R2v**（Zhiyan Meow，官方模板，1277） | 2084156547344986113 | 官方 Ref2VA：最多 9 图 + 3 视频 + 3 音频；`ref_image_size`：`match` 快，`max` 保留短边最高 2048 px，**身份更稳**但慢（参考 token 每步都参与计算）；res_multistep / simple 20 | ✅ | 林晚/顾沉身份分低的镜头改用 `max` 做 A/B |
| I2 | Character Swap 系列（thefeed 75；白日梦想家 92；Datahoney 内置） | 2109576315773915137 / 2095727557672198145 | `h3_character_swap_v1.5` 1.0（"高度贴合参考图风格"）；thefeed 用 H3 做**图像编辑**（ref2va 只出 22 帧，取一帧当图） | ✅ swap v1.5/pro 都有 | 顾沉"没有身份锚"：先用 H3 swap 把参考脸统一，再进视频 |
| I3 | **Movie Director 多参考 + 音频 + 机位切换**（OffArtwork，36） | 2102688089310347266 | `MiniMaxH3ReferenceToVideo`（768×1344 **竖屏**，124 帧，`max`）；turbo v4 step600 1.0；beta 10 步 → SplitSigmas(8) → 3D 放大 ×1.5 → 4 步 | 🟡 | 少见的竖屏 9:16 实例，参数可以直接借用 |
| I4 | subject_definitions 写法（奶霸 selflift motion transfer；导演台） | 2109932153285906433 | prompt 开头写 `subject_definitions: <Subject 1> is the young woman in <Picture 1>, preserving her facial identity, <发型/服装逐项>`，再写动作 | ✅（只是格式） | 交给写作模型的格式规则（第 7 节） |
| I5 | Qwen-Edit 2511 多角度（water，12674 / 618；jingchen573 分镜一致性 109 节点） | 2014417657260417025 / 2078821984347197442 | 角色/场景多角度出图：`Qwen-edit-2511-multiple-angles` LoRA 1.0 + Lightning 8 步，`ModelSamplingAuraFlow(3)`，`CFGNorm(1)`；jingchen 叠加 next-scene v2 0.8、InSubject 0.7、360 LoRA 0.9、Unblur-Upscale 0.6，最后过 SeedVR2 7B | ❌（我们是 Qwen-Image 2.1，有 `QI2.1_AnyAngle`） | 思路：用多角度 LoRA 给关键帧补角度，我们对应的是 AnyAngle |
| I6 | Krea2 角色四视图（电商设计师阿贵，257） | 2090350895467892737 | `Krea2-CharacterSheet-QuadView-lora-v1` 1.0，2000×1200，10 步 | ❌ LoRA 没有 | 角色设定图：一张图出四视图，可用作 Ref2VA 的参考图 |

### 2.4 脸部细节 / 修脸（ep02 最该补的一环）

| # | 工作流 | id | 关键参数 | 节点包 | 我们有吗 |
|---|---|---|---|---|---|
| F1 | **H3 FACE REFINE Repair distorted faces**（Doc_workBox，120） | 2090058776664641538 | `H3FaceTrackCrop(face_yolov8m, conf 0.35, crop 2.0, 512×512, auto_capped_768, 高斯平滑 21/51, per_frame, 0.28, largest, person_yolov8m-seg)` → `MiniMaxH3ReferenceToVideo(本镜原 prompt, 512×512, 362 帧)` → `H3PerFrameDenoise(0.9, 0, absolute_px, 50, 200, 1, 9)` → `BasicScheduler(simple, 4, **0.45**)`（作者标注"key dial"）→ `H3FaceStitch(face_only, 24, 24, 1, 1, fade_out)`；`MiniMaxH3NativeAudioLock` 锁音频 | comfyui-h3-facerefine / comfyui_fearnworksnodes | 🟡 face_yolov8m ✅；节点包 ❌；person seg ❌ |
| F2 | **H3 Face Distortion Repair (Single Person)**（T8star，138） | 2089600646134738945 | T8 版：ref2va int8 + turbo 8step 0.75；`simple 8 步 denoise 0.45`；`FaceRefineParityPlan(…crop 2.5, manual_512, 高斯 21/51)`；`PerFrameDenoise(0.8, 0.35, relative_to_clip, 30, 120)`；AudioConditioningT8 `lock_source 0.35`；prompt 模板 "Preserve the same identity, expression, gaze, head pose, timing, lighting and camera motion. Restore only plausible facial s[tructure]…"；`SolAttnMiniMax` | T8mars/minimax-h3-audio-T8 | 🟡 |
| F3 | singularity_V2_face_refine（有趣的80后程序员，108 / 7） | 2112932115164123137 | **用的就是我们装的 `SelfLiftH3Sampler`**（4 步，lowres 0.4）+ `H3FaceTrackCrop(face_yolov8n, crop 2.5, 768×768, manual, largest_face, insightface)` + `H3FaceStitch` + `VOSR2Upscale` | 同 F1 | 🟡 |
| F4 | Face Detailer I2V Small Face（大圣Ai自习室） | 2100147183408803842 | 小脸专用：`H3PerFrameDenoise(1, 0.35, absolute_px, 30, 120)`；`ImageResizeKJv2(1024, nvidia_rtx_vsr)` 先放大；脸裁 768 | 同 F1 | 🟡 |
| F5 | 导演台 FaceRefine | 2115013398462570497 | face_yolov8m，0.35，crop 2.5，768×768，largest_face，denoise 0.40，8 步 euler/simple，face_only 贴回；在二采之后执行 | AIMixer director | ❌ |
| F6 | ReActor 换脸（Zhiyan Meow，376） | 2078630613040599041 | `ReActorFaceSwap(inswapper_128, retinaface_resnet50, codeformer, 1, 1)` | ❌ | 不推荐用在写实成片：inswapper 128 分辨率偏低，皮肤像蜡。只作为兜底 |

**结论**：F1/F2 的共识参数是"脸裁 512–768，crop 2.0–2.5，denoise 0.40–0.45，4–8 步，逐帧降噪按脸大小在 0.35–0.9 之间调，24 帧羽化贴回，音频锁定"。中景和全身镜头（S9/S10 脸部 Laplacian 只有 13–18）是最直接的受益者。

### 2.5 泛红 / 调色统一

| # | 来源 | 要点 | 我们有吗 | 预期 |
|---|---|---|---|---|
| C1 | Datahoney Long Video Resume（2112909829342134273） | 核心节点 `ColorTransfer(mkl_lab, target_frame, 0, 0.75)`：每段生成后向参考帧做 LAB/MKL 迁移，强度 0.75 | ✅ 本机核心节点有 ColorTransfer（grade.py 注释提到过），现在用的是 Python 版 Reinhard | 可以把 dejudder 之后的脸颊 a* 限幅换成 MKL 迁移做对照，看泛红漂移（相对开头 ≥6）能不能压下去 |
| C2 | 电影质感正式版（图图的ai世界，2268 / 88，H3 工作流使用量第一） | `H3电影感V2` LoRA 0.8（作者建议 0.7，高动态镜头 0.5，触发词 DY）+ ref2v turbo 8step 0.75；`er_sde` + 手动 12 步 `1,.9902,.9781,.9627,.9426,.9156,.8780,.8130,.6877,.5527,.3684,.1316,0`；1344×1792（竖屏）×1008 | ❌ LoRA 没有 | 作者声称针对"塑料感、过锐、硬光、AI 感"做了优化。我们有 h3-realism-people 0.7 做同类对照 |
| C3 | 修脸重绘（2.4） | H3 低 denoise 重绘脸部，等于在模型内部重新生成肤色 | — | 对付局部圆斑式泛红，比后期限幅更自然 |

### 2.6 口型 / 对白

| # | 工作流 | 要点 | 我们有吗 | 预期 |
|---|---|---|---|---|
| L1 | 郑中琦 SelfLift 双采音频锁（2113897588037844993）/ Single Sample 长视频数字人（2115295605128314881） | `MiniMaxH3AudioConditioningT8`：`lock_source`（drive_audio，音频 latent 遮罩 0，最终合成用原音轨）和 `native`（模型自己出声）用开关切换；`official_2_to_15s`；作者注明"锁音频不保证人物身份或口型完全准确" | ❌ T8 节点包 | **TTS 嘴型偏差 2.5 s 的根治方案**：先定音轨，H3 跟着演。要和"H3 原声"版做 A/B，比较嘴部相关性和句内/句外比 |
| L2 | InfiniteTalk single（Aiwood，22183 / 1097，全站最热之一） | Wan2.1 I2V 14B + InfiniteTalk Single + lightx2v rank128 0.8；`flowmatch_distill` 4 步；`MultiTalkWav2VecEmbeds`；`AudioSeparation` 先分离人声 | ❌ | 后期口型修正的备选：只重做嘴部，不动身份 |
| L3 | LatentSync 1.6 一分钟长视频（T8star） | `LatentSyncNode(1408, 1.5, 30)` + `VideoLengthAdjuster` | ❌ | 后期对口型。分辨率偏低，牙齿容易糊（作者专门出过"牙齿更清楚"版） |
| L4 | 短剧表情迁移（无极，3310 / 425） | Wan2.1 FantasyPortrait + InfiniteTalk | ❌ | 表情驱动。偏动漫 |

### 2.7 长镜头 / 续写 / 分段

| # | 工作流 | 要点 | 我们有吗 |
|---|---|---|---|
| R1 | **All-in-One Long Video Resume**（Datahoney，202 节点） | 续写开关；`VideoFrameSample(22, tail)` 取上一段尾部 22 帧；`MiniMaxH3AddGuide`（**核心节点**，负数帧号从片尾倒数）；`ColorTransfer` 0.75；IndexTTS2.5 配音；character_swap 1.0；`MiniMaxH3PromptEnhancerT8`（本地 GGUF Qwen） | 🟡 AddGuide / ColorTransfer 是核心节点 ✅ |
| R2 | MiniMax_H3_fl2va_ref2va 加速版（Y Z，31） | `MiniMaxH3MotionContextSaveLatent / LoadLatent / Trim(0, 24) / MotionContext(22)`：把上一段 latent 存成上下文，下一段带着 22 帧运动上下文生成。节点来源（WFLIB 提供）：NikoDemon80/ComfyUI-H3-Motion-Context（commit 518c083d），多参考图版是 seitanism/ComfyUI-H3-Motion-Context-MultiRef | ❌ |
| R3 | AutoContext Unlimited Duration（2101344066620731394） | `H3Parameter`（分段/标签）+ `H3AutoContextSampler` + `H3SeamCorrection` | ❌ |
| R4 | 2K Regenerate Upscaler（Peto Gara） | `MMH3TemporalSplitParams(136, 17, 0.999)`：按 136 帧时间分块，重叠 17 帧；`MMH3SpatialSplitParams` 空间分块；`VAEDecodeTiled(512, 64, 64, 8)` | ❌（bbaudio-2025/Comfyui-MMH3-UltimateUpscale） |

### 2.8 超分 / 插帧（smooth）

| # | 工作流 | 要点 | 我们有吗 | 预期 |
|---|---|---|---|---|
| U1 | **2K Regenerate Upscaler**（Peto Gara，2115979586264653826） | 一采 fasth3_omniref_8step + dmad 8step critic 1.0（shift 6/3，simple 8）；二采 `MMH3LatentUpscaleWithModelParams(conv_v1_fp16, 1280×704)` → `MMH3UltimateUpscale` + lms_v1.0 0.8 + sharp_curve_branches 1.0 + open_h3_regenerate_2k_lora 1.0，`sa_solver simple 4 步 denoise 0.25` | 🟡 omniref 8step ✅、lms ✅、regenerate_2k_refiner ✅；dmad 8step critic ❌ | 768P 成片再生成 2K：脸部和纹理是"重新生成"，不是插值放大 |
| U2 | 官方 Regeneration API（第 6 节） | 768P → 2K，$0.05/s | 云端 | 同上的云端版，非成人镜头可用 |
| U3 | GIMM 插帧到 60（阿硕讲ai，4376）/ 放大 + 插帧（破狼，5507） | `GIMMVFI_interpolate`：gimmvfi_r_arb_lpips / f_arb_lpips，倍率 2–4；`2xNomosUni_span_multijpg_ldl` / RealESRGAN x2 | ❌ | 24 → 48/60 fps 更顺。**注意**：插帧会把"每 4 帧一顿"的顿挫也平滑掉，但掩盖不了真正的静止。应放在 dejudder 之后 |
| U4 | SeedVR2（HAIGC 1119；Future 补帧版 432；小齐齐 SeedVR2 + RIFE） | `SeedVR2(3b fp8/fp16, 1088, batch 1–21)` + `BlockSwap(20–32)`；`RIFE VFI(rife47, 10, 2)` | ✅ SeedVR2 3B 模型在 gpu33 / gpu3 脚本 | 已有 4K 可选步骤，不新增 |
| U5 | FlashVSR 低显存长片段（AI-KSK，292） | `FlashVSR_SM_KSampler(1472×2560, …, wavelet, 81)`，streaming_dmd | ❌ | 比 SeedVR2 快，可做预览级超分 |

### 2.9 分镜一致

见 2.3 的 I5，以及第 7 节（Next Scene、焦点接力、资产库）。

---

## 3. 前 10 个值得在 ep02 实测的（排序）

排序依据：对 7 维打分的预期增益、我们已有的程度、实测成本。每项都标明对照基线。

| 排名 | 实测项 | 来源 | 打中哪一维 | 准备工作 | 判定指标 |
|---|---|---|---|---|---|
| 1 | **FL2VA 10+3 两段式**：simple 20 → SplitSigmas(10)，conv_v1 3D 放大到 1280×704（竖屏对应 704×1280），3 步 `0.9035,0.6316,0.3158,0`，turbo 4step v1.1 1.0，shift 12/3 | celestial swan | ④运动、③质感、迭代速度 | 全都有，零安装 | 单镜耗时、静止占比、J4、脸部 Laplacian，对照 official_base 24 |
| 2 | **H3 原生修脸**：F1/F2 参数（crop 2.5、768、denoise 0.40–0.45、8 步、逐帧降噪 0.35–0.9、24 帧羽化、音频锁） | Doc_workBox / T8star / 导演台 | ①身份、③质感、⑦泛红 | 装 comfyui-h3-facerefine（或 fearnworks）节点包；face_yolov8m 已有 | SFace 余弦中位（S10 0.267 → ≥0.30）、脸部 Laplacian、脸颊 a*p95 |
| 3 | **SelfLift 文戏 6 步**：我们的 `SelfLiftH3Sampler`，steps 6，lowres_scale 0.5–0.6，rho 0，w_min 0.5，w_max 1，upscaler 用 conv_v1；搭配 DMAD 4step 1.0 + H3SigmaRefiner | Winters Gong / 吴限 / singularity face refine | 速度、③质感 | 补 h3_upscaler_lms_v0.1（或先用 conv_v1）；装 H3SigmaRefiner（yichengup） | 同 1 |
| 4 | **TTS 锁音轨对口型**：AudioConditioningT8 `lock_source` | 郑中琦 | ⑥声画 | 装 T8mars/comfyui-minimax-h3-audio-T8 | 嘴部 0 偏移相关、句内/句外比，对照 H3 原声版（0.19–0.70） |
| 5 | **Ref2VA `ref_image_size=max`** 对身份分低的镜头（S1 base24 0.204、S8 0.276、S10） | 官方模板 | ①身份 | 零安装 | SFace 中位、跨镜一致性 |
| 6 | **ColorTransfer(mkl_lab, 0.75) 对齐首帧/参考帧**，替代或配合 skin guard | Datahoney | ⑦泛红 | 核心节点 | 脸颊 a*≥25 占比、a*p95 漂移（≥6 警告） |
| 7 | **Motion Repair V2 0.25–0.35（低 sigma 段 0.75）** 修 S1 脚部重影 | 文武双修 / 导演台 | ②鬼影 | 已有 | 条带图 3.2–3.8 s 前脚 |
| 8 | **2K Regenerate**（本地 U1 或云 API U2）用在终版成片 | Peto Gara / 官方 | ③质感 | 本地缺 dmad 8step critic 和 MMH3 包 | 中景脸部 Laplacian |
| 9 | **长镜头拆段续写**：上一段尾 22 帧 AddGuide + ColorTransfer | Datahoney / Y Z | ⑤节奏（单镜 ≤6 s）、⑦色漂 | AddGuide 是核心节点 | 段间 ΔE、接缝帧差 |
| 10 | **GIMM-VFI ×2 插帧**（dejudder 之后） | 阿硕 / 破狼 | ④顺滑 | 装 ComfyUI-GIMM-VFI | J4、观感 |

> 安装节点包、补模型、改配置都要经过总调度和 LAB，本文只给建议。所需节点包清单见第 5 节。

---

## 4. 采样配方对照（社区里出现最多的几种）

| 配方 | 采样器/调度 | 步数 | shift | LoRA | 用途 |
|---|---|---|---|---|---|
| 官方基线 | res_multistep / simple | 20 | 默认 | — | 官方模板（R2v、ref2va multi-param） |
| Turbo 8 步 | euler / beta | 8 | 12/3 | turbo_8step 768p 1.0 | Smart Bobo |
| Turbo 4 步 + 两段 | euler + ManualSigmas | 4–5 + 3 | 12/3 | turbo 4step 0.75–1.0 | Prompt Mastery、celestial swan |
| er_sde 手动 10 步 | er_sde + ManualSigmas `1,.9882,.973,.9524,.9231,.878,.8,.6316,.4737,.1579,0` | 10 | — | ref2v turbo 8step 0.75 | Datahoney、郑中琦长视频 |
| er_sde 手动 12 步 | `1,.9902,.9781,.9627,.9426,.9156,.8780,.8130,.6877,.5527,.3684,.1316,0` | 12 | — | 电影感 V2 0.8 + ref2v turbo 0.75 | 电影质感正式版 |
| er_sde 5 步 | `1,.9524,.878,.6316,.4737,0` | 5 | 12.2/3 | fl2v turbo 4step v1.2 1.0 + realism-people 0.7 | 大头黄猫 direct-ai-actor |
| DMAD | euler / beta 或 simple | 6–10 | 12/3 或 6/3 | DMAD 4step/8step 0.8–1.0 + Mystic 0.45 | 导演台、SelfLift 文戏 |

共识：CFG 1 + BasicGuider（无负面），视频/音频 shift 12/3。这和我们 LEARNED_SPECS 里"负面提示对 Pika 无效"一致。

---

## 5. 节点包与模型缺口（gpu33 现状对照）

gpu33 ComfyUI（`/root/claude-kimi-ns-studio-v1/ComfyUI`）。gpu36 直连 ssh 超时，没能查。

- **已有**：
  - 节点：KJNodes（含 MiniMaxChunkFeedForward / LowVRAMAttention / SageAttention patch / TokenCounter）、Comfyui_Minimax_h3_latent_Upscaler（3D/2D）、comfyui-SelfLift（SelfLiftH3Sampler / TST / ImageSampler）。
  - latent_upscale_models：conv_v1_bf16。
  - ultralytics/bbox/face_yolov8m.pt；SEEDVR2 3b + ema_vae。
  - LoRA：DMAD 4step、lms_v1.0_r64、realism-people、Motion_Repair_V2、MysticXXX V4、character_swap v1.5/pro、regenerate_2k_refiner、turbo fl2v 4/8 步、ref2v turbo 4/8 步。
  - 主模型：fasth3_omniref_8step。
- **缺（按实测排名的需要）**：

  | 优先级 | 缺什么 | 用于 |
  |---|---|---|
  | 1 | comfyui-h3-facerefine（WFLIB 对齐为 Carasibana/ComfyUI-H3-FaceRefine，commit d8521d14）或 comfyui_fearnworksnodes（H3FaceTrackCrop / H3PerFrameDenoise / H3FaceStitch / H3InjectVideoLatent / MiniMaxH3NativeAudioLock） | 第 2 名 |
  | 2 | yichengup/ComfyUI-YCNodes-MiniMax-H3（H3SigmaRefiner） | 第 3 名 |
  | 3 | T8mars/comfyui-minimax-h3-audio-T8（AudioConditioningT8、DualClockSamplerT8、FaceRefine*T8Advanced） | 第 4 名 |
  | 4 | bbaudio-2025/Comfyui-MMH3-UltimateUpscale | 第 8 名 |
  | 5 | ComfyUI-GIMM-VFI | 第 10 名 |
  | 6 | 可选：slmonker/selflift-Avatar（SelfLiftAvatarH3Sampler）、AIMixer/ComfyUI_MiniMaxH3_Director | — |

  - 模型：h3_upscaler_lms_v0.1、minimax_h3_latent_upscaler_3d_fp16(_V2)、dmad 8step critic、H3电影感V2（触发词 DY）、b25-49 hybrid int8（HF smhfacct/Minimax-H3-fl2va-ref2va-hybrid-models）、person_yolov8m-seg、taeh3（只用于预览）。
  - 模型链接都写在各 workflow.json 的 MarkdownNote 里（HF：Comfy-Org/MiniMax-H3、LBH-123-AI/Minimax_h3_latent_Upscaler、lightx2v/Minimax-h3-Turbo）。

---

## 6. 云端通道评估（只读文档，没有调用）

### 6.1 MiniMax H3 Model API（标准模型 API，按输出秒数计费）

| SKU / 端点 | 内容 | 价格 | 关键限制 |
|---|---|---|---|
| `/minimax/hailuo-h3/image-to-video`（504203） | 官方 H3 首尾帧 I2V | 768P $0.077/s，2K $0.12/s | prompt 1–20480 字；firstFrameUrl / lastFrameUrl 各 1 张（≤30 MB）；duration 取 5–15 的整数；resolution 只有 768P 或 2K；可选 aigc_watermark |
| 504201 Multimodal Ref2V | 官方 Ref2VA | 同上；参考图前 5 张免费，之后 $0.04/张；参考视频按时长计费；音频免费 | 最多 9 图 / 3 视频 / 3 音频 |
| 504205 H3-Max I2V | — | 480P $0.063/s，768P $0.1/s | — |
| 504211/12/13 Regeneration 768P→2K | 把已生成的 768P 再生成为 2K | $0.05/s（输入素材再计一次费；图片前 5 张免费，之后 $0.025/张） | baseVideoUrl：带音轨，24fps，宽高能被 32 整除，面积 ≤768×1344，107–362 帧；prompt 必须和原生成一致 |
| `/rhart-video/minimax-h3-rh-enhanced/i2va`（2102602472381587457，RH 自托管 "Enhanced"） | I2V / 首尾帧，**drive audio 对口型** | 480p $0.03/s，768p $0.04/s，1080p $0.06/s | aspectRatio 支持 9:16；duration 4–15 s；首尾帧图 ≤100 MB；driveAudio 可选（说明写"required"，不填就用工作流默认） |
| minimax-h3-max-turbo i2v（504402） | 快速档 | 480p $0.032/s，768p $0.05/s | 5–15 s |
| H3-Context-IR（i2va/t2va/r2va） | 只返回增强后的 prompt | 输入 $0.83 / 1M token，输出 $3.29 / 1M token | 不生成视频 |
| minimax speech-2.8-turbo / hd | TTS | $0.05 / $0.09 每千字符 | 17+ 音色、语气词 |

- **调用流程**：`POST /openapi/v2/<endpoint>`（Bearer Key）→ 返回 taskId → `POST /openapi/v2/query`，也可以用 webhook。
- **结果 URL 只保留 24 小时**，要及时下载。
- **Model API 只支持 Enterprise-Shared Key**。
- 估算（不含失败重跑）：ep02 共 11 镜约 80 s。
  - 768P 官方：约 $6.2；
  - RH Enhanced 768p：约 $3.2；
  - 再生成 2K：每次约 $4。

### 6.2 Workflow API（跑我们自己的 ComfyUI 图）

- **提交**：`POST https://www.runninghub.ai/task/openapi/create`，参数：
  - `apiKey`、`workflowId`；
  - `nodeInfoList[{nodeId, fieldName, fieldValue}]`；
  - **`workflow`（完整工作流 JSON 字符串，会覆盖 workflowId）**——不用先在网站保存，避免"编辑器自动保存"那类事故；
  - `instanceType`：`default` 24 GB、`plus` 48 GB、`ultra` 84 GB；
  - `webhookUrl`、`usePersonalQueue`（独享 Key，排队上限 1000）。
- **注意事项**：
  - API 每次调用都会重置 seed，要固定 seed 必须在 nodeInfoList 里显式写；
  - 前端字段（如 control_after_generate）和组逻辑无效；
  - LoRA 要走"取上传 URL → 上传 → 用 RHLoraLoader 加载"三步；
  - 图片通过 Upload API 拿到 fileName 后填给 LoadImage。
- **计费**：
  - 企业共享：默认 100 并发，按调用期间的 GPU 秒计费，不调用不收费，高峰期可能排队，环境会随平台升级；
  - 企业独享：按 GPU 数量 × 时长预付，不排队，环境版本固定；
  - 开通企业 API 要联系客户经理。
  - 具体的每秒单价在 "API Key Call Benefit Comparison" 和会员页。会员页的价格对比接口（`product/v2/rightList/compare`）被我的拦截规则挡住了，我也没有为此放行，**单价未确认**。
- **云端节点环境**：工作流里出现了 RunningHub 专有节点，如 `RHHiddenNodes`、`RH_LLMAPI_NODE`、`RHMiniMaxH3*`、`RH_IndexTTS25_*`。上面列的 SelfLift、facerefine、T8 等社区包都在云端工作流里跑过，说明平台已经预装了它们。

### 6.3 判断

| 用途 | 结论 |
|---|---|
| 加速 iterate | **可行，但只限非成人镜头**（项目规定"成人镜头只本地生成"；官方 MiniMax API 有内容审核，RH 自托管 Enhanced 的审核策略没写）。最实用的是 Workflow API + `workflow` 字段直接送我们的图，加 `plus` 48 GB 实例跑全尺寸 2K 或二采，100 并发可以把 11 镜一次全部并行 |
| 对口型 | RH Enhanced I2V 的 driveAudio 768p $0.04/s，可以作为 TTS 锁音轨方案的云端对照 |
| 2K 终版 | Regeneration API $0.05/s，素材要求和我们的 768P 成片兼容（24fps、宽高能被 32 整除、≤362 帧） |
| 风险 | 素材需要上传到 RH 存储（隐私）；共享环境会升级导致节点漂移；结果 24 小时过期；需要企业 Key（涉及花钱，属于项目方闸门） |

---

## 7. 给写作模型的结构化格式（只有格式和流程，不含内容）

这些规则以后可以放进 `config/script_chat_rules.md` 一类的规则文件，由写作模型照格式产出。Claude 不写内容。

1. **subject_definitions 头**（Ref2VA / 多人镜）：每个镜头的 H3 正文第一段固定写 `subject_definitions: <Subject N> is the <角色类型> in <Picture N>, preserving <facial identity>, <发型>, <服装逐项>, <配饰>`，后面才写动作。参考图顺序和 `<Picture N>` 一一对应（官方模板也是按连接顺序引用）。
2. **角色视觉档案**（AiKisma 资产库）：每个角色固定这些字段：
   - 外貌、服装、性格、配色；
   - **3 个不可变视觉锚点**（面部 / 着装 / 道具）。

   写作规则：
   - 锚点必须在每个场景和镜头的提示词里重复出现；
   - 禁止用模糊形容词，改用具体的几何特征；
   - 角色名写全名，禁止"你/我/他"；
   - 场景提示词里不出现角色。
3. **镜头描述五段式**（AI-Matt Klein 分镜）：主体（同前 + 本镜变化）+ 场景（本镜可见范围）+ 运动（人物动作 + 镜头运动）+ 美学控制（景别、光位、色调、构图、机位、节奏）+ 风格化（质感、材质）。"同前"表示继承上一镜，只写变化。
4. **9 镜焦点接力结构**（Visual Continuity Director）：全景入画 → 推进聚焦 → 触发/诱因 → 反应/互动 → 过程 → 高点特写 → 变化/后果 → 余韵局部 → 拉远出画。镜与镜之间用**物理接力 / 视线接力 / 环境接力**衔接（上一镜结尾的动作要成为下一镜开头的画面）。先判断调性：静谧/情感靠光影和微表情衔接，悬疑靠手部和门，激烈靠碰撞和位移。这能帮我们修 v0 "8/10 相邻同景别"的问题。
5. **Next Scene 续写**（乐导 / next-scene LoRA）：每镜以 `Next Scene:` 开头，约 100 字连续文字，必须写明景别和镜头类型（特写/中景/远景/俯拍/跟拍/环绕/侧移/拉远）、镜头节奏（慢推/快切/手持），以及"动作表情是上一镜的自然推进"。
6. **长镜分段**（Datahoney）：同一场的续写段时长相同，标注"第几段"，自动跳过重叠帧。
7. **分镜反推**（AI-Cyber Kimi 2.5）：用三段式构图（开始/高潮/结局）+ 15 秒视频分镜。可以用于成片反推审片。

---

## 8. 对系统重构的启发

### 8.1 流程

把单次 24 步改成"预览档 → 选定 → 精修档"三级：

| 档位 | 配置 | 作用 |
|---|---|---|
| 预览档 | 0.4MP、8 步 Turbo 或 FastH3（或 SelfLift 4–6 步） | 只用来挑 seed 和动作，每镜 3–4 个 take 并行 |
| 选定档 | 同 seed，10+3 两段式 / SelfLift 到 768P | 得到可用画面 |
| 精修档（可选） | H3 修脸（音频锁）→ ColorTransfer 对齐 → dejudder → GIMM ×2 → 2K Regenerate 或 SeedVR2 | 终版质量 |

依据：社区工作流普遍把"一采/二采/修脸/续写"做成**独立开关**，而且缓存一采的 latent（导演台："缓存和输出目录独立；修改总步数时同时检查 SelfLift 切换步"）。

- 我们的 `services/render_router/ns_render/workflows.py` 应该支持把一采 latent 落盘，二采和修脸从缓存起跑，不重算一采。
- 种子策略：预览用 randomize，选定后改 fixed，并把 seed 写进 takes.json（Workflow API 也会强制重置 seed）。

### 8.2 分镜表（Shot Spec）建议新增字段

由系统确定性填写的，或由写作模型按第 7 节格式产出的：

- `subjects[]`：Subject N ↔ Picture N ↔ 角色 ID ↔ 3 个锚点（EN 短语，来自人物表）。
- `continuity_in` / `continuity_out`：接力类型（物理/视线/环境）以及具体元素。
- `shot_size`、`camera_move`（官方词表）、`pace`。
- `audio_mode`：`h3_native` / `lock_tts`（对应 AudioConditioningT8 lock_source）/ `vo_closed_lips`。
- `ref_image_size`：`match` / `max`（身份关键镜头默认 max）。
- `segment`：长镜拆段的段号、时长、与上一段的重叠帧数（默认 22）。
- `post`：`face_refine`（denoise）/ `color_anchor`（参考帧）/ `vfi` / `regen_2k` 开关。

### 8.3 质检（和 LEARNED_SPECS 衔接）

- **修脸前后都要过 SFace**：修脸后余弦必须 ≥ 修脸前，否则丢弃修脸结果（T8 的说明里也写着"output is a review candidate only"）。
- **段间接缝**：续写段接点前后各 0.5 s 的帧差和 ΔE 设阈值（H3SeamCorrection 是同一思路）。
- **锁音轨镜头**：嘴部相关性闸门沿用现有指标，阈值按 H3 原声版的下限 0.19 设。
- **两段式和 SelfLift 的新增风险**："低清定结构"会让小脸更糊，所以中景、全身镜头默认必须开修脸。

---

## 9. 附：已导出工作流索引（55 个）

见 `data/ab/owner_workflows/runninghub/_index.tsv`。按类别：

- **H3 核心（27）**：Zhiyan Meow R2v；Prompt Mastery sigma-split；Smart Bobo 8-step 768p；图图 电影质感；Datahoney Long Video Resume；吴限 SelfLift LowVRAM 2K；郑中琦 SelfLift 双采音频锁 / 导演台 / 单采长视频数字人；OffArtwork Movie Director；Peto Gara 2K Regenerate；pearldotey fl2va-ss；Aether Latent FL2VA；celestial swan fl2va / ref2va 10+3；有趣的80后程序员 fastH3_ref2va / trim_latent_upscale；上上签 ref2va multi-param；yifan wang 文武双修；白日梦想家 Character Swap + 反推；thefeed character swap 图像编辑；奶霸 selflift motion transfer；Winters Gong H3selflift Drama；exQYQX5o H3 Prompt Enhance；Lavaflow Camera Moves；大头黄猫 direct-ai-actor；Y Z fl2va_ref2va 加速版。
- **H3 修脸 / 续写（6）**：T8star Face Distortion Repair；Bobosiki face preservation；Doc_workBox FACE REFINE；有趣的80后程序员 singularity_V2_face_refine；大圣 Face Detailer Small Face；哏啾 AutoContext。
- **分镜 / 短剧（9）**：乐导 Next Scene；AI-Matt Klein 分镜；water Qwen-Edit 2511 多角度；jingchen573 分镜一致；AI-Cyber 分镜反推；侃侃的抹布 短剧拍档 V8；AiKisma 短剧资产库；北岸北地 主角设计；无极 表情迁移。
- **后期（13）**：破狼 放大 + 插帧；阿硕 GIMM 60fps；小齐齐 SeedVR2 + RIFE；HAIGC SeedVR2；Future SeedVR2 补帧；AI-KSK FlashVSR；Aiwood InfiniteTalk；T8star LatentSync 1.6；Zhiyan Meow ReActor；稳号甄选家 换脸转头控制 / Animate 调色换脸；AIGC Qwen Image 2.1 GH 加速；电商设计师阿贵 Krea2 四视图。
- **导出返回 404（作者已下架）**：2109498950188376065、2107370699363352578、2095468125374840833、2113178037708763138。
