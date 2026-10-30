# 亲密戏音频方案调研（MiniMax H3 FL2VA + 后期）

> 调研日期：2026-10-30。只读调研，未下载任何模型，也未改动机器。
> 范围：虚构成年角色、双方自愿的亲密戏。本文只写技术要点，不写露骨内容。
> 标记说明：**【已证实】** = 官方文档/仓库原文；**【社区】** = 论坛、Civitai、博客里的个人经验；**【未验证】** = 本文推断，需要在 gpu3 上实测。

---

## 0. 结论速览（按优先级）

1. **先在 H3 内部把能做的做好（A）**：用**非 turbo** 的底模渲染最终音频，步数 **≥8**（推荐 12–20）；shift 保持 **video 12 / audio 3**；ComfyUI **≥0.33**。非语言声音（呼吸、喘息、轻呼）写在 `overall_soundscape`，台词只用 `<d>`，必须把 `non_diegetic_music` 写明（填 N/A），并且一个镜头只让**一个人发声**。
2. **林晚的声线一致性（B）**：最可控的路线是**先做音频、再驱动视频**：用固定合成声线（TTS）或 H3 的最佳低清版本得到台词音频，然后用 audio-drive 把音频冻结进 AV latent，让 H3 只生成视频和口型。Ref2VA 的 `<Audio N>` 音色参考目前**不可靠**。后期变声（VC）是保底方案。
3. **后期栈（C）**：HunyuanVideo-Foley XL 做身体接触、布料、床响等拟音；**标志性声音母题**（12 cm 高跟、铃铛、金属珠、漆皮）用**授权音效库/实录做成固定样本库**，不靠生成。耳语和内心独白用 CosyVoice 3 / IndexTTS2 / GPT-SoVITS。呻吟类发声用 H3 原生生成，或者用**有成人用途授权**的音效包/签约配音演员。
4. **音频 LoRA（D）**：musubi-tuner 已经支持 H3 联合音视频 LoRA，可以加音频 loss。但要先做完 A/B 测试再决定是否训练。数据只能来自：H3 自己筛选出的好样本、合成声线，以及签了成人内容授权的配音演员/授权音效。
5. **A/B 测试（E）**：选一个 5 秒的亲密镜头、固定 seed，跑 8 组对比（第 6 节）。

---

## 1. H3 原生音频：现状与注意点

### 1.1 Prompt 结构【已证实】
- FL2VA 的正文有三个字段：`integrated_multimodal_description`（带分镜 `[Shot N]`，台词和动作写在这里）、`overall_soundscape`（1–4 句，写环境声、动作声、**非语言人声**）、`non_diegetic_music`（只写配乐，没有就写 `N/A`）。
  来源：[ComfyUI 官方 H3 Prompt Guide](https://docs.comfy.org/tutorials/video/minimax/minimax-h3-prompt-guide)、[comfyui-wiki 指南](https://comfyui-wiki.com/en/tutorial/advanced/video/minimax/minimax-h3-prompt-writing)
- 台词格式：`(S1)` 说话人 ID + 动作/语气写在 `<d>` 外面；`<d>[Chinese] 原文。</d>` 里只放原文，句末要有标点。省略号"often hurt intelligibility"（影响清晰度）。画外音写 "says in an off-screen voiceover"，并在 `</d>` 后注明嘴唇闭合。
- 官方建议用 `BasicGuider`、cfg 1、**不使用负向分支**。所以"不要 XX"这类否定句只能写进正文，效果不稳定【社区】。
- 官方列出的已知问题：多说话人时会把台词分配给错误的人；`overall_soundscape` 或 `non_diegetic_music` 留空时可能冒出多余人声或配乐。

### 1.2 非语言人声（呼吸/喘息/呻吟）怎么写
- 主流做法【社区】：非语言声音写在 `overall_soundscape`，例如 "a quiet laugh, a sharp exhale"。**不要**在 soundscape 里写"某人说话/台词"，否则音频分支会收到第二条无标签的说话指令，导致双声和含糊嘟囔（[malcolmrey H3 prompting guide](https://huggingface.co/datasets/malcolmrey/various/blob/main/h3-center/docs/MINIMAX_H3_PROMPTING_GUIDE.md) Rule 8）。
- `<d>` 内的行内表演标签（Rule 54）：`<breath>` `<inhale>` `<exhale>` `<deep breath>` `<catches breath>` `<sighs>` `<whisper>` `<softer>` `<laughs>` `<pause>` `<long pause>`。这些是**社区实验用法，每次生成效果不同**，不是官方语法。【社区/未验证】
- 拟声词（"嗯…""啊…"）放进 `<d>`：H3 会当成台词去念，经常念得很机械；而且会引入省略号问题。**不推荐**。如果确实要用，写成短促的单字加句号。【未验证】
- 无人发声的镜头要写清楚：例如 "No voices and no speech of any kind" 或 "mouths closed, speaking no dialogue"。嘴部微张的静息状态容易引发嘟囔（Rule 53）。

### 1.3 采样设置与 turbo 对音频的影响
- shift：ModelSamplingMiniMaxH3 / MiniMaxH3SigmaShift 默认 **video 12.0 / audio 3.0**。它不是音量或音质旋钮，改动会同时影响运动和音频（[LegacySampling README](https://github.com/starsFriday/ComfyUI-MiniMax-H3-LegacySampling/blob/main/README.md)、[embedded-docs](https://github.com/Comfy-Org/embedded-docs/blob/main/comfyui_embedded_docs/docs/MiniMaxH3SigmaShift/en.md)）。10Eros beta6 用 10/3，beta7 用 12/3。
- **步数与音质的实测**（[zenn 文章](https://zenn.dev/nekod/articles/c9505022fb8661?locale=en)，ComfyUI 0.33.1，底模，单 prompt 单 seed）：20 步和 8 步合格；7 步开始发闷发机械；4 步完全机器人声。Turbo LoRA 在 4 步时比底模响约 16 dB（峰值 −4.7 dBFS），8 步时仍响 4.5 dB；把 Turbo 8 步降 11 dB 后，听感仍不如底模 8 步。Turbo 8 步和底模 8 步耗时几乎相同，所以**出最终音频时 turbo 没有速度优势**。
- ComfyUI 版本：PR #15243（v0.31.0）把音频改成 `ModelSamplingAV` 并入视频调度；joyfox 指出 v0.31.0 相比 0.30.0 音质有退化（[joyfox/MiniMax-H3-Turbo](https://huggingface.co/joyfox/MiniMax-H3-Turbo)），zenn 在 0.33.1 上没复现"4 步爆音"。**建议 gpu3 使用 ≥0.33 版本，并核对当前版本号。**【未验证 gpu3 当前版本】
- **10Eros-Max（NSFW 合并模型）**【社区】：作者原话是 "Non-turbo full step audio will always be better than audio on turbo versions"；turbo 档里音频最好的是 **LCM/simple 6–8 步**（[TenStrip/10Eros-Max](https://huggingface.co/TenStrip/10Eros-Max)）。Civitai 用户反馈：turbo 版在 NSFW 场景里有夸张的 thumping/knocking（撞击、咀嚼类）伪音，非 turbo 版没有这个问题但手指崩坏（[civarchive beta5](https://civarchive.com/models/2851079?modelVersionId=3294059)）。beta6 换了 turbo 混合，据称能避开 4 步音频问题【未验证】。许可：H3 Community License，外加 LTX 2.3 / Wan 2.2 / Krea 2 的各自许可。
- **PinkCherry**：本次没有检索到相关音频说明。【未找到】

### 1.4 已知弱点
- **Issue #17：多说话人音色串扰**（[MiniMax-H3#17](https://github.com/MiniMax-AI/MiniMax-H3/issues/17)，状态 open，无官方回复）：同性别说话人会塌缩成同一个声音，异性也会串。FL2VA 单张合成首帧同样能复现。社区规避方法：
  - 非说话角色不要带任何无格式的笑声或轻哼，删掉后问题消失。这一点对亲密戏**非常关键**：男方的喘息很可能被当作发声而串进林晚的声线。
  - 每个镜头 ≤6 个对白轮次；时长改 1–2 秒有时能修好；返场说话人换新的 ID 并复制一份参考音频。
  - 实用结论：**亲密戏每个镜头只让林晚一人发声**，soundscape 里明确写 "no male voice"，男方的呼吸放到后期再加。【未验证】
- 镜头开头 0.5–1 秒的含糊嘟囔：上一段继承来的嘴部 latent 会造成这个问题（Rule 41）。
- 时长决定语速：时长太短会赶台词，太长会拖慢或出现填充语。时长按"台词时长 + 约 1 秒"设置（Rule 32/47）。
- 内容审核：只针对官方托管服务（[模型卡](https://huggingface.co/MiniMaxAI/MiniMax-H3)），本地权重不受影响。**许可提醒**：Civitai 页面称 H3 Community License 的授权范围不含 EU/UK/韩国/美国（[civitai H3](https://civitai.com/models/2821932/minimax-h3)），发行地区需要法务确认。【未验证条款原文】

### 1.5 音频参考能力【已证实 + 社区】
- **Ref2VA**：最多 3 段音频，每段 2–15 秒，总长 ≤15 秒；音频不能是唯一的参考类型；模型会**重新生成**音频，不会拷贝原波形（[模型卡](https://huggingface.co/MiniMaxAI/MiniMax-H3)、[Wuli Turbo](https://huggingface.co/Wuli-art/MiniMax-H3-Turbo)）。prompt 里用 `<Audio 1>` 引用。
- 社区实测（[discussion #64](https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/64)、[#91](https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/91)、[HF 论坛](https://discuss.huggingface.co/t/i-am-having-two-major-issues-with-minimax-h3-ref2va/190009)、[ComfyUI_frontend#15040](https://github.com/Comfy-Org/ComfyUI_frontend/issues/15040)）：
  - 写 "<Audio 1> is the voice-timbre reference for <Subject 1>" **多数时候仍然失败**；有时会出现两个声音叠加，音色和参考差距明显。
  - 静音段会出现参考音频的乱码复述；有时会从头把参考音频念出来。**把参考音频裁到和台词一样长**可以缓解。
  - 加了音频后人物外观会被重铸（#91）。有人反馈只有接 `ref_video_audio` 输入才生效。
  - 接了参考音频以后，模型会按音频驱动嘴型，覆盖文字里的静音指令；无台词的镜头要断开参考音频（Rule 57）。
- **MiniMaxH3AddGuide**（[PR #15439](https://github.com/Comfy-Org/ComfyUI/pull/15439)）：可以在任意帧锚定图像、短片、音频，或"片段 + 原声"，模型在此基础上**续写**两路信号。它不是音色参考；审阅者也说明音频参考没有做端到端测试。需要 ComfyUI ≥0.33（推荐 0.36+）。
- **Audio-drive（音频锁定）**：[comfyui-h3-audio-drive-auto](https://github.com/lebao-arch/comfyui-h3-audio-drive-auto)（MIT，作者在 3090 Ti 上测试）把给定音频对齐到 17k+5 网格并冻结进 AV latent（音频 mask=0，只对视频去噪），H3 会按这段音频生成嘴型和动作。README 提到的 latent 来源节点是 I2V / Ref2V，**没有提 FL2VA**；非语音音频驱动也没有测试过。另有 "MiniMax H3 • LipSync Latent Setup" 节点可以分别设置音频和视频的 denoise（[comfy.icu](https://comfy.icu/node/MiniMaxH3LatentLabLipSyncSetup)）。

---

## 2. 方案 A：现在就能在 H3 内做的（模板 + 设置）

### 2.1 设置
| 项 | 推荐值 | 说明 |
|---|---|---|
| 模型 | 底模 FL2VA，或 10Eros 非 turbo 版 | 最终音频不用 turbo |
| 步数 | 12–20（最低 8） | 8 步是音质底线【社区】 |
| 采样器 | Euler/simple 或 er_sde/sgm_uniform | 如果必须用 turbo，选 LCM/simple 6–8 步 |
| shift | video 12 / audio 3 | 不要拿 shift 调音量 |
| guider | BasicGuider，cfg 1 | 官方设置 |
| 时长 | 台词时长 + 约 1 秒，帧数满足 17k+5 | |
| ComfyUI | ≥0.33 | 避开 0.31 的音频退化 |

**省时的两段式做法【未验证】**：先用 turbo 低清快速选构图和动作 → 选中的 seed 用底模 16–20 步、低分辨率重跑一遍拿到好音频 → 用 audio-drive 把这段音频锁进最终的高清（可以是 turbo）视频渲染。社区确实有人报告"低清生成音频再作为高清的参考"更稳（#64）。

### 2.2 Prompt 模板（中性技术写法，按镜头替换括号内容）
```
integrated_multimodal_description: [Shot 1] (镜头/构图/动作描述……) (S1) Lin Wan, a woman in her late twenties with a soft, low, slightly husky voice, breathes unevenly through parted lips, eyes half-closed. At 00:02.000, (S1) leans close and whispers, breathy and trembling: <d>[Chinese] <breath> 别停。</d> Her lips close after the line. The man stays silent with his mouth closed throughout.
overall_soundscape: Quiet bedroom room tone, close and intimate. The only human sounds are the woman's soft, uneven breathing and small involuntary gasps, rising slightly in pace toward the end. Soft rustle of cotton sheets, a faint rhythmic creak of a wooden bed frame, and a light metallic clink of small ball jewellery with each movement. No male voice, no speech other than her single whispered line.
non_diegetic_music: N/A
```
要点：
- 女主的音色描述（年龄、音高、质感）**每集逐字一致**，固化成 shot spec 编译器里的常量。
- soundscape 用 "The only human sounds are …" 这种**正向限定**，代替"不要 thumping"这类否定句（cfg=1 没有负向分支）。
- 声音母题（高跟、铃铛、漆皮吱呀）在 H3 里只写一句淡淡的提示，用来帮助画面动作对拍。**最终声音用后期样本覆盖**，保证 60 集一致。
- 没有台词的亲密镜头：去掉 `<d>`，加一句 "no words are spoken"。呻吟作为非语言声写进 soundscape（例如 "soft involuntary moans"），强度用 pace/volume 词控制，不写拟声。

---

## 3. 方案 B：林晚的声线一致性（可选，按可靠度排序）

1. **合成声线 + audio-drive（推荐优先测试）**：用固定的合成声线生成林晚的台词音频，冻结进 latent，让 H3 只做口型和画面。
   - 优点：60 集音色完全一致，和后期内心独白（TTS）是同一个声线。
   - 风险：FL2VA 能否接入未验证；首尾帧约束和锁定音频会不会冲突；呼吸/呻吟这类非语音能不能驱动出合理的面部动作。
2. **H3 原生生成 + 后期变声（VC）保底**：保留 H3 的表演和时间轴（口型天然对齐），后期用 RVC（MIT）或 Seed-VC（GPL-3.0）把人声转换成林晚的标准音色。需要先用 Demucs / UVR 之类工具把人声和 SFX 分离。VC 对喘息、呻吟的保真度【未验证】。
3. **H3 角色 LoRA 带音频训练**（见第 5 节）：musubi 的 "ref" teacher 能学到身份和声音。
4. **Ref2VA `<Audio 1>` 音色参考**：目前不可靠（1.5 节），只作为实验组。如果要用：参考音频裁到和台词等长，只接在有台词的 A-roll 镜头上。
5. **AddGuide 在第 0 帧锚定一小段林晚原声（约 0.9 秒 / 22 帧）**，让模型"续写"同一个声音，再在后期裁掉开头。纯推断【未验证】。

**合成声线的合法来源**：
- (a) TTS 的"音色设计"或随机说话人，从中选定一个，不克隆任何真人；
- (b) 签约配音演员，书面授权写明"AI 声线建模 + 成人内容 + 商用"。
- 绝不使用抓取来的真人录音。

---

## 4. 方案 C：后期制作栈（全部可以在 gpu3 的单张 3090 上运行）

### 4.1 视频→音频（拟音）
| 模型 | 用途 | 显存 | 许可 | 备注 |
|---|---|---|---|---|
| [HunyuanVideo-Foley](https://github.com/Tencent-Hunyuan/HunyuanVideo-Foley) XL / XXL | 布料、身体接触、床响、环境 | XL 16 GB（offload 8 GB）；XXL 20 GB（offload 12 GB） | Tencent-Hunyuan-Community（EU/UK/KR 除外） | 48 kHz，支持文本提示；[ComfyUI 节点](https://github.com/phazei/ComfyUI-HunyuanVideo-Foley) fp8 版 <8 GB【社区】；训练数据过滤过"不适宜内容"，对亲密画面的表现【未验证】 |
| [MMAudio](https://github.com/hkchengrex/MMAudio) | 同上，速度快 | 约 6 GB【未验证】 | 代码 MIT，权重 **CC-BY-NC-4.0** | 不可商用 |
| [ThinkSound](https://github.com/QwenAudio/ThinkSound) | 带 CoT 的可编辑拟音 | 未查到 | 代码 Apache，模型**仅限研究** | 不可商用 |
| [ControlFoley](https://github.com/xiaomi-research/controlfoley)（2026，Xiaomi） | 支持文本/音频条件的可控 V2A | 未查到 | 未查到 | 【未验证】 |
| Kling-Foley、AudioX | — | — | 权重或许可未确认 / AudioX 为 NC【未验证】 | 不建议 |

结论：V2A 模型**擅长物理拟音**，不擅长人声（呼吸、呻吟），所以只用它们生成"物理声层"。商用要求下，目前只有 HunyuanVideo-Foley 勉强可用，地区和商用条款需要法务核对（[reeleehq/foley 许可围栏](https://github.com/reeleehq/foley/pull/174)把它标成 commercial_ok=False，和腾讯条款的解读存在分歧）。

### 4.2 文本→音效
- Stable Audio Open（Stability Community License，年营收低于阈值可商用）：生成环境声和 whoosh 层。AudioLDM2、Tango 2 是 NC 许可，不建议。【许可凭记忆，未逐一复核】
- **标志性母题（高跟、铃铛、金属珠、漆皮）**：强烈建议**买授权音效库或自己实录**，每种母题建 10–20 个变体样本，在全片统一使用。生成模型无法保证 60 集的一致性。

### 4.3 TTS（耳语台词 / 内心独白 / 可选的 audio-drive 源）
| 模型 | 中文 | 非语言能力 | 许可 |
|---|---|---|---|
| CosyVoice 3 | 强 | `[breath]` `[laughter]`，耳语靠自然语言指令；社区测得 `[breath]` 命中率低（约 25%） | Apache-2.0 |
| IndexTTS2 | 强 | 8 维情感向量，可用参考音频或文本控情感；时长可控 | bilibili 模型许可（有用户数/营收上限，原文未查到） |
| GPT-SoVITS v4 | 强 | 靠训练语料的风格，可以用气声语料微调 | MIT |
| Fish Audio S2 Pro | 支持 80+ 语言 | 自由文本标签：`[whisper]` `[inhale]` `[exhale]` `[sigh]` `[gasp]` | **Research License，商用需另购** |
| Dia2 / Chatterbox / Orpheus | 以英文为主 | (gasps) / [sigh] 等 | Apache 等 |
| Higgs Audio v2 | 有 | 表现力强 | "other"，商用需单独申请 |
| F5-TTS | 有 | 无 | 权重 CC-BY-NC |
| Kokoro | 有 | 无，也不能克隆 | Apache |

结论：TTS 适合做**台词、耳语和内心独白**；**呻吟、叫床这类持续非语言发声，现有 TTS 都不可靠**。论文也指出"在指定位置生成可信的非语言发声"仍然没有解决（[arXiv 2609.14231](https://arxiv.org/pdf/2609.14231)、[NVV-SuperBench](https://arxiv.org/pdf/2604.16211)）。这部分用 H3 原生生成，或者用授权音效。
链接：[Fish S2 Pro](https://huggingface.co/fishaudio/s2-pro)、[CosyVoice3 tags 指南](https://github.com/diodiogod/TTS-Audio-Suite/blob/main/docs/COSYVOICE3_TAGS_GUIDE.md)

### 4.4 授权的成人向音效库
Pond5、AudioJungle、TunePocket（明确写了 adult video 用途）、Depositphotos、freesoundeffects.com 都有呼吸、呻吟类素材（[Pond5 示例](https://www.pond5.com/sound-effects/item/323552992-deep-breathing-and-moaning-woman)、[TunePocket](https://www.tunepocket.com/royalty-free-music/girl-moan-long-5/)）。
- **逐条核对许可**：是否允许成人内容使用，是否有表演者的成人用途授权（release）。
- 不要混用多个不同女声，否则会破坏林晚声线的一致性。最好由同一位签约演员一次性录一套"林晚非语言声库"。
- Pixabay 之类免费站的成人素材来源和授权链不清楚，**不建议使用**。

---

## 5. 方案 D：H3 音频 LoRA

- **工具**：[musubi-tuner H3 文档](https://github.com/kohya-ss/musubi-tuner/blob/main/docs/minimax_h3.md)【已证实】
  - 支持 T2VA / FL2VA / Ref2VA 三种模式。目标音频可以来自同名 `.wav` 旁挂文件、视频内嵌音轨或 JSONL 里的 `audio_path`，按 32 kHz 立体声解码，**必须和第一帧对齐**。
  - `--audio_loss_weight`（默认 1.0）只对带真实音频的样本生效。`--video_only` 会关闭音频监督。
  - **H3 是单流结构：纯视频训练的 LoRA 也会改动音频路径的权重，音频可能失去约束。** 已有的林晚角色 LoRA 如果是用 video_only 或纯图片训练的，可能正在拖累音频，值得在 A/B 测试里单独测一组。
  - teacher "ref" 能学到身份和声音；"first,last" teacher 保留底模的音频行为。
  - 需要 `--audio_vae`（fp32）。示例配置 `--blocks_to_swap 48` 加梯度检查点；12 GB 显存可以训练（[note.com 教程](https://note.com/sepiablue/n/nc1ce412d6ea2?hl=en)）。
- ai-toolkit 也支持 H3 联合去噪（[comfyui-wiki](https://comfyui-wiki.com/en/news/2026-08-03-ai-toolkit-minimax-h3-training)），音频监督的细节【未验证】。
- **现成的音频类 LoRA**：Natural Face & Speech（[civarchive](https://civarchive.com/models/2925394)，英文说话，权重 0.6–0.8）；带 SFX 设计的 Third-person-view LoRA；多镜头工作流里的 voice_ref 输入。**没有找到**专门针对亲密或非语言人声的音频 LoRA。另有一篇 [Civitai 文章](https://civitai.com/articles/36097/training-h3-loras-on-small-datasets-what-ive-learned-so-far) 说 H3 能从"音频片段 + 简单转写"学到角色声线（页面 403，细节未读到）。
- **合法数据来源（按推荐顺序）**：
  1. **自蒸馏**：从 H3 自己的生成结果里挑出音频最好的林晚片段（底模 20 步），约 30–80 段，每段 3–8 秒。完全合法，风格也一致。【数量为经验估计】
  2. 合成声线（第 3 节）配到 H3 视频上，用 audio-drive 生成成对的数据。
  3. 签约配音演员的录音（授权写明 AI 训练、成人内容、商用），加授权音效。
  - 转写统一用 `<d>[Chinese] …</d>`，非语言声写在 soundscape 风格的 caption 里。
  - 绝不使用抓取的真人亲密录音。
- **建议**：先完成 A/B 测试。如果底模 20 步的原生音频加 prompt 模板已经够用，就不训练；只有当"声线漂移"或"thumping 伪音"在 A/B 里仍然严重时，才训练"林晚身份 + 声音"的联合 LoRA，`audio_loss_weight` 设为 1.0。

---

## 6. 方案 E：单镜头 A/B 测试计划

**固定条件**：同一个 5 秒亲密镜头（含 1 句耳语台词），同一张首尾帧，seed 固定，768p，在 gpu3 上跑。跑之前先确认 8765 端口有没有其他 agent 在用。

| 组 | 配置 |
|---|---|
| A1 | 底模 FL2VA，20 步，2.2 节模板（基线） |
| A2 | 底模 8 步 |
| A3 | 10Eros beta5 **turbo**，LCM/simple 8 步 |
| A4 | 10Eros beta5 **非 turbo**，16 步 |
| B1 | A1，但非语言声改用 `<d>` 内行内标签（`<breath>` `<sighs>`） |
| B2 | Ref2VA + `<Audio 1>`（林晚合成声线，裁到台词长度） |
| C1 | A3 的视频 + A1 的音频，用 audio-drive 锁定 |
| C2 | A3 的视频 + 全后期栈（Foley + 授权非语言声 + TTS 耳语 + 母题样本） |

**评估方法**：
- 3 人盲听，按 1–5 分打分，维度：自然度、音画同步、林晚声线一致性、伪音（thumping、双声、嘟囔）。
- 客观指标：峰值 dBFS 和 LUFS（ffmpeg ebur128）；用 ECAPA / WavLM 计算与林晚标准声线的余弦相似度；记录耗时。
- 判定：如果 A1 或 A4 达到 ≥4 分，就走方案 A；如果 C1 明显更好，就把"先音后画"做进批量管线。

---

## 7. 混音（方案 C/E 的落地）

1. **分轨**：H3 原声 → 用 Demucs/UVR 分离成"人声"和"其余"两轨；Foley 层；母题样本层；TTS 内心独白层；（可选）音乐层。
2. **台词口型**：台词保留 H3 原声，或者用时间轴完全一致的 VC 版本替换。**不要**用重新生成的 TTS 直接替换镜头内台词，口型会对不上；除非走 audio-drive 先音后画。
3. **对拍**：母题样本对齐画面动作节点。shot spec 里已经有动作时间码，可以直接导出 cue 表；或者用光流检测脚步、撞击的帧号【未验证】。也可以先让 H3 原声里的同类声音做时间参考，再用样本替换。
4. **ducking**：Foley 和母题对人声做 sidechain 压缩，衰减 −6 到 −10 dB（ffmpeg `sidechaincompress`）。内心独白期间，场景声整体压低 8–12 dB，独白加轻微的近讲 EQ，和场内声音区分开。
5. **响度**：竖屏短剧平台建议整体约 −14 LUFS，真峰值 ≤ −1 dBTP（ffmpeg `loudnorm` 两遍法）。Turbo 产生的高电平原声要先归一化再混。【平台目标值为行业惯例，未逐一核对平台规范】
6. 每个镜头输出 stems 和 cue 表并归档，方便 60 集复用和返修。

---

## 8. 未解决 / 需要实测的问题
- FL2VA 能否接入 audio-drive 或 AddGuide 的音频锁定。
- Ref2VA 的音色克隆能否通过"裁剪参考音频 + 单说话人"变得可用。
- HunyuanVideo-Foley 对亲密画面会不会输出静音或乱声（训练数据做过过滤）。
- VC 对喘息和呻吟的保真度。
- H3 Community License 的地区条款，以及 HunyuanVideo-Foley 的商用条款（需要法务确认）。
- gpu3 当前的 ComfyUI 版本号。
