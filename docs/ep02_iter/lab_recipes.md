# LAB：ep02 渲染配方对照（2026-10-31，进行中）

LAB 只做系统侧配方对照，不评剧本内容。所有产物标 LAB：
- 经 :8800 提交的版本：请求带 `by: "LAB"`，记在 `data/ab/lab/manifest.json`。出完后 API 会把新版本设为“当前”，`tools/lab_ep02/lab_runner.py watch` 会立刻撤回到出片前的当前版本。LAB 不定稿，不审片通过。
- Ref2VA（项目方工作流）：:8800 没有这条管线，所以直接提交到 gpu33:1 的 ComfyUI。产物放在 `data/ab/lab_ref2va/`，不写 takes。

工具：
- `tools/lab_ep02/lab_score.py`：打分，输出到 `data/ab/lab/scores/`，包括 `scores.md`、`scores.json` 和每条视频的 `*_sheet.jpg` 接触印样。
- `tools/lab_ep02/lab_runner.py`：提交和撤回当前版本。
- `tools/lab_ep02/ref2va_run.py` / `ref2va_prompt.py`：Ref2VA 两段式，提示词用官方六段格式。
- `tools/lab_ep02/i2v_override.py`：生成 I2VA 正文修正版。

指标说明：
- mean / 静止 / 尾定：同 motion_qc。
- J4 / z：同 motion_judder。
- 硬切：HSV 直方图 Bhattacharyya > 0.35，且帧差 > max(8, 6×中位)。
- 脸红：YuNet 定位，用蓝发判定是林晚。cheek_a95 = 脸颊带 Lab a* 的 95 分位；cheek_red = 脸颊 a* ≥ 25 的像素占比。“起”取开头 0.5 s 的中位数，“max”取全片最大值。

## 批 1：脸部泛红（GPU 侧对照 + 现有 30 个版本复测）

S2 固定同一张定稿首帧、同一 seed 20261101、只给首帧，只改配方：

| 版本 | 配方 | mean | J4 | cheek_a95 起→max | cheek_red 起→max | 产物 |
|---|---|---|---|---|---|---|
| R1 | Pika Flex | 1.21 | 1.16 | 29.6→43.4 | 0.08→**0.61** | renders/ep02/S2/takes/video_007_a27855cc4d04.mp4（S2 take 8） |
| R3 | Pika Flex + antiburn 0.7 | 0.92 | 1.15 | 30.5→45.4 | 0.08→**0.65** | video_007_d42cc9e502c4.mp4（take 7） |
| R6 | Pika Flex + lin_wan_h3_v1_step250 0.8 | 0.93 | 1.18 | 30.5→44.5 | 0.07→**0.67** | video_008_961bd364114b.mp4（take 9） |
| 现有 S2_C | Pika Flex（QCV，另一 seed） | 1.28 | 1.16 | 29.0→43.7 | 0.07→0.51 | data/ab/static_fix/S2_C.mp4 |
| 现有 t6 | 基模 24 步 | 0.75 | 1.11 | 30.2→38.3 | 0.08→0.52 | S2 take 6 |
| 现有 t5 | 基模 24 步（另一 seed） | 1.64 | 1.62 | 30.2→30.6 | 0.08→0.12 | S2 take 5（1.25 s 处有硬切） |
| 现有 A | Turbo 8 步 | 0.80 | 1.11 | 30.6→37.6 | 0.08→0.41 | data/ab/static_fix/S2_A.mp4 |

所有 ep02 版本按“提示词里有没有 flush / blush 类词”分两组：

| 组 | 镜头 | 首帧 cheek_a95 | 版本内 cheek_red 最大 |
|---|---|---|---|
| 提示词有 flush / blush（视频提示词里出现 1–2 次，首帧图提示词里有“脸颊绯红 / 泛红”） | S2 S3 S4 S6 S7 S8 | **29–34**（S8 20） | 0.08–0.67，Pika 和只给首帧时最高 |
| 提示词没有 | S1 S5 S9 S10 S11 | 16–23 | **≤ 0.08**，所有配方都是 |

结论（证据强度：中高；S2 一个 seed 跑了 3 个配方，现有版本 30 个）：
1. **泛红不是 Pika 独有的。** 所有配方都会泛红：基模 24 步（S2 t6 0.52、S3 t6 0.50）、Turbo（S2_A 0.41、S8 t2 0.45）都有。只出现在提示词写了脸红的镜头。没写的 5 镜，所有配方的 cheek_red 都 ≤ 0.08。
2. **Pika 把泛红放得最大，而且最稳定。** S2 上 Pika 三个配方和两个 seed 都是 +14 a*，cheek_red 0.5–0.67。基模两个 seed 分别是 +0.3 和 +8，和 seed 关系很大。
3. **随时间变重。** cheek_a95 从开头往后一路升高，和社区报告（Comfy-Org HF #55 “intensifies frame by frame”）一致。只给首帧时没有尾帧把颜色拉回来，所以比首尾帧版本更红（S2：只给首帧 0.41–0.67，首尾帧 t4 0.16）。
4. **antiburn 0.7 和 lin_wan LoRA 0.8 都压不住**（R3 0.65、R6 0.67，和 R1 0.61 差不多）。
5. **首帧本身已经偏红。** 有 flush 词的镜头，首帧 cheek_a95 是 29–34，没有的是 16–23。另外，林晚的身份参考图 `assets/characters/lin_wan/lin_wan.png` 本身就是浓腮红妆。
6. 去暖调 / 去锐化首帧的对照**没有跑**：:8800 的 video-jobs 只用定稿首帧，没有“换一张首帧”的参数，改定稿首帧又属于项目方的决定。cfg / shift / Pika 步数在 API 里也不能改：Pika 固定 6 步，sigma 表里已经含 shift，cfg=1 是 CFG 蒸馏要求的。所以批 1 只能对照“配方 + LoRA”。

系统侧建议（只写建议，不改 config）：
- 有脸部近景、且提示词写了脸红的镜头，不用 Pika，用基模 24 步，并跑 2 个 seed，用 cheek_red 挑红得少的那版（建议门槛：cheek_red ≤ 0.25，和 rubric ⑦ 一致）。
- 出片后的质检里加一项 cheek_red（指标已在 `lab_score.py` / `review.py` 里），超过 0.25 时标“脸部泛红”。
- 提示词里的 flush / 绯红是剧本内容，系统不改，只把“这类词和泛红强相关”的证据交给写作方 / 项目方。

## 批 2：Ref2VA（项目方工作流）和 FL2VA/I2VA 对照（18:20 中间结果）

Ref2VA 设置：
- ref2va int8，20 步 euler/simple，SplitSigmas@10。前 10 步在 544×960 跑，然后 3D latent 放大到 768×1344，再跑后 10 步。
- BasicGuider，SigmaShift 12/3，comfy kitchen attention，fp16 视频 VAE。
- 提示词：官方 ref-en 六段，正文取剧本英文 H3 字段。
- 参考图：P1 = lin_wan.png 脸，P2 = REF-LW-01 造型全身，P3 = 顾沉。不给首帧。
- seed 20261101。
- 3090 出片时间：6 s 的镜头约 16 min（S6）；S2 加 <Audio 1> 约 32 min，其中含排队。

| 镜 | 版本 | 判定 | mean | J4 | cheek_a95 起→max | cheek_red max | SFace 中位（对 lin_wan.png） | 产物 |
|---|---|---|---|---|---|---|---|---|
| S6 | **X1 Ref2VA** | **pass** | **1.28** | 1.38 | 25.5→27.0 | 0.09 | **0.70** | data/ab/lab_ref2va/X1_S6_ref2va_off_s1.mp4 |
| S6 | 现有 t6 基模 24 | fail | 0.31 | 1.23 | 28.9→35.2 | 0.08 | 0.48 | S6 take 6 |
| S6 | 现有 t7 Pika（RR） | warn | 0.44 | 1.34 | 30.1→37.8 | 0.09 | 0.50 | S6 take 7 |
| S6 | R4 Pika seed2 | warn | 0.48 | 1.36 | 28.5→33.7 | 0.07 | — | S6 take 8 |
| S2 | **X3 Ref2VA + 顾沉 <Audio 1>** | **pass** | **2.02** | **1.03** | 26.1→31.3 | **0.10** | **0.75** | data/ab/lab_ref2va/X3_S2_ref2va_off_audio_s1.mp4 |
| S2 | R2 基模 32 步 | warn | 0.67 | 1.08 | 30.9→38.2 | 0.29 | 0.33 | S2 take 10 |
| S2 | 现有 t6 基模 24 | warn | 0.75 | 1.11 | 30.2→38.3 | 0.52 | 0.34 | S2 take 6 |
| S2 | R1 Pika | pass | 1.21 | 1.16 | 29.6→43.4 | 0.61 | 0.38 | S2 take 8 |
| S1 | **X2 Ref2VA** | pass | **2.59** | 1.13 | 27.1→34.9 | 0.10 | **0.53** | data/ab/lab_ref2va/X2_S1_ref2va_off_s1.mp4 |
| S1 | 现有 t3 基模 24 | pass | 2.07 | 1.14 | 15.6→22.8 | 0.05 | 0.24 | S1 take 3 |

接触印样：data/ab/lab/scores/X1_S6_ref2va_sheet.jpg、X2_S1_ref2va_sheet.jpg、X3_S2_ref2va_audio_sheet.jpg。

ASR 回听（SenseVoice）：
- X3 S2：“方案第三页，数据错了。”，字全对，但 4.6 s 才开口，6.5 s 结束，几乎贴到片尾。
- X1 S6：“那我明天还你。”，“您”仍念成“你”，和 FL2VA 版本一样，所以这不是配方的问题。

观察：
1. **Ref2VA 在三个问题镜上的动作量、身份、泛红全面领先。**
   - S6 从“静止·不合格”变成通过，mean ×4。
   - 身份 SFace 0.48–0.50 → 0.70–0.75。S1 0.24 → 0.53。
   - 脸颊泛红不再随时间变重：S2 的 cheek_red 从 0.52–0.61 降到 0.10。
   - S2 的 J4 是 1.03，没有 4 帧一顿。S6 的 J4 是 1.38，仍有。
   - 看印样，S1 腿脚交叠的动作段没有多腿或重影。
2. **代价是构图不受定稿首帧约束。** Ref2VA 不给首帧，所以场景和机位来自提示词。我们的六段提示词只搬了剧本的英文字段，中文 image_body 没有放进去。结果：
   - S6 成片是站姿，没有披外套、没有台灯暖光；剧本 image_body 写的是坐姿、外套披肩、台灯暖光。
   - S2 林晚穿上了 lin_wan.png 里的项链和粉色上衣。这是参考图 P1 的服装渗漏，CONSIST 也报告了同样的现象。

   修法：P1 改用只含脸的裁切图（X4 在跑）；或者按 FL2VA 社区模板 / drama-series-agent 的做法，把定稿首帧放在 <Picture 1> 作为首帧，角色图从 <Picture 2> 起排（E5 multiframe）。后者既保留构图，又能锁身份，下一批要做。
3. Motion Repair V2 0.9（D1 S1）、realism-people 1.0（D2 S2）、基模 24 步对照（D3 S2）还在出。gpu33:3 隧道 18:00 前后断过一次，任务在服务器上没丢，已改用 `tools/lab_ep02/fetch_prompt.py` 按 prompt_id 取回结果。

### 批 2 补充（18:40）

| 镜 | 版本 | 判定 | mean | J4 | cheek_red max | SFace | 产物 |
|---|---|---|---|---|---|---|---|
| S1 | D1 基模 24 + Motion_Repair_V2 0.9（I2VA 修正） | pass | 2.11 | **1.35**（基模 1.14） | 0.04 | 0.30 | data/ab/lab/direct/D1_S1_b24_mrepair09_s1.mp4 |
| S2 | D3 基模 24（I2VA 修正，seed s1） | warn | 0.90 | 1.11 | 0.28 | 0.29 | data/ab/lab/direct/D3_S2_b24_s1.mp4 |
| S6 | R7 基模 24（I2VA 修正） | **fail** | 0.33 | 1.06 | 0.08 | 0.48 | S6 take 9 |
| S10 | R5 Pika seed2 | warn | 0.40 | 1.06 | 0.09 | 0.30 | S10 take 5 |
| S10 | 现有 t4 基模 24 | warn | 0.49 | 1.08 | 0.08 | 0.22 | S10 take 4 |

- **Motion Repair V2 0.9 有害。** J4 从 1.14 升到 1.35，把“4 帧一顿”带回来了，动作量没有增加。0.4 档没跑，社区中位强度是 0.4。
- **I2VA 正文去掉 Picture 2 分句，救不了静止镜。** S6 基模 24 修正前 0.29–0.31，修正后 0.33，仍然 fail。S6 / S10 在 FL2VA / I2VA 的所有配方下（Turbo、基模 24 / 32、Pika、两个 seed）都是 fail 或 warn，只有 Ref2VA（X1）通过。
- 基模 32 步（R2）和 24 步差不多：S2 mean 0.67 对 0.75–0.90，泛红 0.29 对 0.28–0.52。多出的步数不值得。

## 每类镜头的最佳配方（LAB 18:45 结论，证据：每格 1–3 条）

| 镜头类型 | 代表镜 | 推荐配方 | 关键指标 | 主观观察（看印样） | 风险 / 代价 |
|---|---|---|---|---|---|
| 人物走动 / 腿脚入画 | S1（S5、S9） | **Ref2VA 两段式**；其次**基模 24 + 只给首帧** | Ref2VA：mean 2.59，J4 1.13，SFace 0.53。基模：J4 1.14，SFace 0.24 | 两者都没有多腿 / 脚重影。Ref2VA 动作更完整，身份明显更像 | Ref2VA 不受定稿首帧构图约束。不要加 Motion Repair 0.9（J4 1.35），Turbo 有脚重影（MOT） |
| 对白近景（脸大、提示词写了脸红） | S2、S3、S4 | **Ref2VA + 脸部裁切参考 + 角色音色 <Audio>**；其次基模 24 + 2 seed 挑 cheek_red 低的 | Ref2VA：J4 1.03，cheek_red 0.10，SFace 0.75，ASR 全对。基模：cheek_red 0.12–0.52（看 seed） | Ref2VA 脸稳、不随时间变红。不要用 Pika：cheek_red 0.5–0.67 | Ref2VA 开口晚（4.6 s）。整张定妆图做参考会带进项链和粉裙，已用脸部裁切解决（X4：SFace 0.81，cheek_red 0.08）。FL2VA 路线上的泛红对策是 realism-people 1.0（D2：0.28 → 0.08） |
| 静态情绪（首尾帧几乎一样） | S6、S10、S7 | **Ref2VA** | S6 mean 1.28、S10 mean 1.35，都 pass；FL2VA / I2VA 全部 fail 或 warn | 有呼吸、视线、手部的小动作，不再像幻灯片 | 构图来自提示词，与定稿首帧不同（S6 坐姿变站姿） |
| 长镜头（≥ 10 s） | S8、S11 | **基模 24 + 只给首帧 + I2VA 正文修正**，走长道 gpu36:2 | R9 S11：pass，mean 2.74，J4 1.01，0 硬切，SFace 0.55 | — | S8 没测（R10 已取消）。Ref2VA 在长镜头上没测；3090 上 10 s 以上的两段式要算显存 |

通用：
- 硬切：这一批新出的 14 条都是 0 处。现有版本里只有基模 24 的 S2 t5（1.25 s）和 S11 t3（2.29 s）各 1 处，换 seed 就消失了。建议出片后跑 `lab_score.cuts`，检出硬切就自动换 seed 重出。
- 卡顿：基模 24 / 32 的 J4 是 1.06–1.14（平滑）；Pika 1.15–1.36；Ref2VA 1.03–1.38，S6 那条偏高，pytorch attention 对照（X5）在出。没有超过 1.4 的版本可以接 `tools/dejudder.py`。

## 建议写进 config/render_quality.json 的改动（只是建议，没有改）

1. `video_bases.bases` 新增 `official_ref2va_2pass`（试验）。参数：
   - unet `minimax_h3_ref2va_pruned_int8_convrot.safetensors`，clip `qwen3vl_32b_minimax_h3_nvfp4_awq`，视频 VAE `minimax_h3_video_vae_fp16`，音频 VAE fp32。
   - steps 20，`split_step` 10，`lowres` [544, 960]，`upscaler` `minimax_h3_latent_upscaler_3d_conv_v1_bf16.safetensors`，target [768, 1344]，align 32。
   - sampler euler，scheduler simple，shift [12, 3]，guider BasicGuider，cfg 1。
   - attention `comfy kitchen attention`（待 X5 对照 pytorch 后再定）。
   - `ref_image_size` match。
   - `refs`：角色脸部裁切图 + 本集造型全身图，最多 3 张；音色参考用 `ref_audios`，约 4 s。
   - `prompt_format` `ref-en-6`。
   - 只在 gpu33 有权重；gpu36 缺 ref2va unet 和 fp16 VAE。gpu33→gpu36 内网直连 ssh 报 host key verification failed，复制没做，需要运维先配好 known_hosts。
2. `video_bases.pika_flex` 加上 `avoid_when: ["face_closeup_with_blush_prompt"]` 或提示文字，例如“脸部近景易泛红，cheek_red 0.5–0.67”。
3. `motion_qc` 增加：
   - `cheek_red_warn: 0.25`（rubric ⑦）；
   - `cut_reject: true`：检出镜内硬切，判“需换 seed”；
   - `identity_sface_warn: 0.30`。
4. `official_base.steps` 保持 24。32 步没有收益（R2）。
5. `optional_video_loras` 加 Motion_Repair_V2 时，推荐强度不要超过 0.4（0.9 让 J4 1.14 → 1.35）。antiburn 和 lin_wan_h3_v1 对泛红无效，不推荐用于这个目的。

### 批 3（19:10，收尾）

| 镜 | 版本 | 判定 | mean | J4 | cheek_a95 起→max | cheek_red max | SFace | 产物 |
|---|---|---|---|---|---|---|---|---|
| S2 | **X4 Ref2VA + 脸部裁切参考 + 顾沉 <Audio 1>** | pass | 1.81 | **1.03** | 26.7→28.4 | **0.08** | **0.81** | data/ab/lab_ref2va/X4_S2_ref2va_facecrop_audio_s1.mp4 |
| S2 | **D2 基模 24 + realism-people 1.0** | warn | 0.64 | 1.09 | **30.0→30.3** | **0.08** | 0.29 | data/ab/lab/direct/D2_S2_b24_realism10_s1.mp4 |
| S2 | D3 基模 24 对照（同 seed） | warn | 0.90 | 1.11 | 28.7→35.8 | 0.28 | 0.29 | data/ab/lab/direct/D3_S2_b24_s1.mp4 |
| S10 | **X6 Ref2VA + 脸部裁切** | **pass** | **1.35** | 1.20 | 15.6→29.5 | 0.08 | 0.39 | data/ab/lab_ref2va/X6_S10_ref2va_facecrop_s1.mp4 |
| S11 | **R9 基模 24 + I2VA 修正（长道）** | **pass** | **2.74** | **1.01** | 17.5→32.0 | 0.12 | 0.55 | S11 take 6 |

- **脸部裁切参考解决了服装渗漏。** X4 的林晚是 ep02 的白衬衫，不再是参考图里的项链和粉色上衣。身份 SFace 从 0.75 升到 0.81，泛红 0.08，J4 1.03。印样：data/ab/lab/scores/X4_S2_ref2va_facecrop_audio_sheet.jpg。
- **realism-people 1.0 能压住泛红**（同 seed：cheek_a95 漂移从 +7.1 降到 +0.3，cheek_red 从 0.28 降到 0.08）。代价是动作量从 0.90 降到 0.64。这是 FL2VA/I2VA 路线上唯一有效的泛红对策，和社区 Comfy-Org HF #55 的说法一致；只测了 1 个 seed，要再跑 2 个 seed 确认。
- **S10 静止镜：Ref2VA 通过**（1.35，FL2VA 所有配方 ≤ 0.49）。陈宇没有参考图，现在只靠提示词。
- **S11 长镜头：基模 24 + I2VA 正文修正**通过，mean 2.74，J4 1.01，没有硬切。旧 seed 的 t3 在 2.29 s 有硬切。

尚未出完：
- X5：S6 Ref2VA 换 pytorch attention，和 kitchen INT8 对照，在 gpu33:3 跑。结果由 `tools/lab_ep02/fetch_prompt.py http://127.0.0.1:18191 b12d5aae-2ef0-4532-8418-4d2ad3c03228 data/ab/lab_ref2va/X5_S6_ref2va_pytorchattn_s1.mp4` 取回（后台已在等）。
- R8：S1 基模 24 + I2VA 修正，在 gpu36:1 跑。
- R10：S8 Pika，已按总调度要求取消。

## 下一批建议（未做）
1. **E5 Ref2VA multiframe：定稿首帧作 <Picture 1> 兼首帧锚点，角色脸部裁切从 <Picture 2> 起排。** 目的是在保留 Ref2VA 身份、动作、无泛红优势的同时，把构图拉回定稿首帧，解决现在最大的代价。
2. realism-people 0.4 / 1.0 × 2 seed，FL2VA 和 Ref2VA 两条线都测。
3. Ref2VA 开口时间：S2 4.6 s 才开口。可以对照 EXPERT 的音频三条规则（`</d>` 前加句号、写 soundscape、不说话的人写 silently），也可以把 <Audio 1> 截得更短。
4. 男角参考：陈宇、顾沉的设定图（CONSIST）出来后补进 Ref2VA。

## 批 2 任务清单
- Ref2VA 项目方工作流（官方六段提示词）：X1 S6、X3 S2（加 <Audio 1> 顾沉音色参考，音频取 S2 take 6 的 H3 原声 2.6–6.4 s），gpu33:1。
- 基模 24 步 + I2VA 正文修正（去掉 Picture 2 分句）：R7 S6、R8 S1、R9 S11（长道）。另有 R10 S8 Pika，R2 S2 基模 32 步，R5 S10 Pika，R4 S6 Pika seed 2。
- 旧格式 Ref2VA 提示词（自定义段落、中文场景）作废，存档在 `data/ab/lab_ref2va/prompts_old/`，没有出片。

## 批 4（19:45 起，总调度第二批任务）

### E3 注意力：kitchen INT8 对比 pytorch（S6 Ref2VA，同 seed）
| 版本 | mean | J4 | cheek_red | SFace | 产物 |
|---|---|---|---|---|---|
| X1 comfy kitchen attention | 1.28 | 1.38 | 0.09 | 0.70 | data/ab/lab_ref2va/X1_S6_ref2va_off_s1.mp4 |
| X5 pytorch attention | 1.30 | 1.40 | 0.08 | 0.71 | data/ab/lab_ref2va/X5_S6_ref2va_pytorchattn_s1.mp4 |
- 两条逐帧 PSNR 中位只有 27.0 dB，说明数值上已经走出两条不同的轨迹，但所有质量指标都一样。**kitchen INT8 attention 没有可测到的画质损失，保留。** S6 的 J4 1.38 两版都有，是这个镜头 + Ref2VA 本身的问题，和注意力无关。

### E5 multiframe：定稿首帧作 <Picture 1> + AddGuide frame 0，脸部裁切从 <Picture 2> 起
单段 20 步全尺寸（AddGuide 接两段式时，第二段尺寸会对不上，所以这次没用两段式），3090 约 23 min。
| 镜 | 版本 | 判定 | mean | J4 | cheek_red | SFace | 构图 | 产物 |
|---|---|---|---|---|---|---|---|---|
| S6 | E5 multiframe | **warn** | 0.39 | 1.12 | 0.09 | 0.49 | **保住**（坐姿、披外套、台灯暖光） | data/ab/lab_ref2va/E5_S6_mf_s1.mp4 |
| S6 | X1 纯 Ref2VA | pass | 1.28 | 1.38 | 0.09 | 0.70 | 丢失（站姿） | |
| S6 | FL2VA 基模 24 | fail | 0.31 | 1.23 | 0.08 | 0.48 | 保住 | |
| S2 | E5 multiframe + <Audio 1> | pass | 1.14 | 1.12 | **0.08** | 0.35 | **保住** | data/ab/lab_ref2va/E5_S2_mf_audio_s1.mp4 |
| S2 | X4 纯 Ref2VA 脸部裁切 | pass | 1.81 | 1.03 | 0.08 | 0.81 | 丢失 | |
| S2 | FL2VA 基模 24 | warn | 0.75–0.90 | 1.11 | 0.28–0.52 | 0.29–0.34 | 保住 | |

结论：
- **E5 保住了构图，但身份和动作都回到首帧的水平。** 首帧锚点压过了脸部参考：S6 的 SFace 从 0.70 回落到 0.49，S2 从 0.81 回落到 0.35，基本和 FL2VA 一样。S6 又变得几乎不动（0.39）。
- 只有一项比 FL2VA 好：**S2 不泛红**（0.08 对 0.28–0.52）。另外 S2 动作是 FL2VA 基模的 1.3–1.5 倍。
- 所以身份问题的根在**定稿首帧本身**（CONSIST 已核实：首帧是纯文字出图，没有参考）。只要首帧是锚点，视频就跟首帧走。要两者兼得，得先用身份参考重出首帧（CONSIST 的 R 方式），再用 E5 或 FL2VA。
- 印样：data/ab/lab/scores/E5_S6_mf_sheet.jpg、E5_S2_mf_audio_sheet.jpg。S2 的最后 0.6 s 林晚的脸有可见变化，可能是被脸部参考拉动，需要人工回看。

### R8：S1 基模 24 + I2VA 正文修正（seed 20261101，gpu36:1）
- pass，mean 2.10，**J4 1.39**，SFace 0.32。印样 data/ab/lab/scores/R8_S1_b24_i2vfix_s1_sheet.jpg。
- 注意：MOT 用另一个 seed 测到基模 24 的 J4 是 1.12，这次是 1.39。**基模 24 “没有 4 帧一顿”取决于 seed，不是稳定性质。** 出片后应该测 J4；J4 > 1.3 的版本接 dejudder，或者换 seed 重出。

### E2 分辨率：736×1312 对比 768×1344（S1，基模 24，I2VA 修正，seed 20261101，gpu36）
| 版本 | mean | J4 | cheek_red | SFace | 产物 |
|---|---|---|---|---|---|
| E2 736×1312（宽高都 ≡ 32 mod 64） | 1.81 | **1.393** | 0.05 | 0.35 | data/ab/lab/direct/E2_S1_b24_736x1312_s1.mp4 |
| R8 768×1344（宽高都 ≡ 0 mod 64） | 2.10 | **1.389** | 0.06 | 0.32 | S1 take 4 |
- **同 seed 下 J4 完全一样，社区“mod-64 尺寸会顿挫”的假说不成立**（单 seed，证据中等）。保持 768×1344。

### 停止 GPU 实验（20:00，总调度：6 张卡全部给方案 A/B PK）
- 已停的：lab_queue 驱动（还没提交的有 E5_S1、X7 S2 台词定时、6 条 realism-people 补种子，都没跑），以及 :8800 的 LAB 撤回 watcher。
- 正在跑的 E2 照常跑完并已取回。LAB 不再往任何道提交任务。
- 没跑的这些改成配方建议，已发给方案 A（V2，gpu33）和方案 B（PLANB，gpu36），由它们在各自方案里作为变体顺带跑。内容：Ref2VA 两段式（脸部裁切参考 + 六段提示词 + --say-at）、E5 先重出首帧、realism-people 1.0 每镜 2 个 seed、不用 Pika 于脸红镜、不用 Motion Repair 0.9、出片后跑 lab_score 闸门。
- gpu36 补 ref2va 权重：从 gpu33 经本机中转，实测下载约 0.85 MB/s、上传约 0.85 MB/s；ref2va unet 21.0 GB + fp16 VAE 5.2 GB + upscaler 0.7 GB，单向就要约 8.6 h，超过 30 min 的上限，**没做**。等 gpu33→gpu36 内网直连（known_hosts）由运维配好再说。

### 打分工具改进（CPU 侧）
`tools/lab_ep02/lab_score.py`：
- 新增 `--asr`：SenseVoice 回听，给出台词文本、开口时刻和结束时刻。实测 X4 开口 4.62 s，E5 S2 4.02 s，X1 S6 3.42 s。
- 新增 LAB 闸门 `gate`：mean ≥ 0.5、J4 ≤ 1.3、cheek_red ≤ 0.25、0 硬切、SFace ≥ 0.30（有脸时），不合格时列出原因（动作不足 / 4 帧一顿 / 脸部泛红 / 镜内硬切 / 身份偏离）。`scores.md` 里加了一列“LAB 闸门”。
- 已有的指标：运动质检（同 motion_qc）、J4/z、节奏、jerk、鬼影 p95、HSV 硬切、林晚脸颊 a*p95 / cheek_red 的起点和最大值、整帧红块、SFace 中位（对 lin_wan.png），还会出 12 帧接触印样。

辅助工具：
- `fl2va_direct.py`：生产图生成器直连 ComfyUI，支持额外 LoRA 和 `--size`。
- `ref2va_run.py`：两段式或单段（`--single`），支持 `--guide` 首帧 AddGuide、`--audio`、`--attn`，等待时遇到隧道抖动会自动重连。
- `ref2va_prompt.py`：官方六段格式，支持 `--mf`、`--say-at`、`--audio-gu`。
- `fetch_prompt.py`：按 prompt_id 取回结果。
- `lab_queue.py`：每道串行、空闲才提交。
