# 出图模型真人质感对决（BAKEOFF）· 2026-10-31

起因：项目方原话："Image2.1 出问题了，真人的质感完全没有……对比看看哪个做真人效果最好……ComfyUI 里关于 Image2.1 的图片编辑（edit）功能也不太行……我希望你做一下 RSI 这方面的对比设置。"

分工：IMGGEN 修 Qwen-Image 2.1 自身的配方；BAKEOFF（本文）负责换模型这条线。两条线最好的结果最后放在一起比。

工具：`tools/bakeoff/`，包括 run.py、score_srv.py、page.py、dl_manifest.tsv、dl_weights.sh、gated_dl.sh。
- 数据：`data/ab/image_bakeoff/`
- 对照页：`data/review_pages/image_bakeoff/index.html`

## 1. 候选清单

查证方式：HF API、Civitai API、本地 owner_workflows。sha256 都等于 HF LFS oid，记录在 gpu36 的 `/root/work/fredw/dl/sha256.log`。

| 候选 | 权重（gpu36 models/） | 许可 | 参考图 | ComfyUI | 来源 | 置信度 |
|---|---|---|---|---|---|---|
| Qwen-Image 2.1 Turbo（基线，徕卡 S★，去 lin_wan_qi） | 已有 | **Qwen Research License，仅非商用** | 最多 10 张 | 原生 TextEncodeQwenImage21 | [HF](https://huggingface.co/Qwen/Qwen-Image-2.1) | 高 |
| Krea 2 Turbo / Raw（12.9B） | krea2_turbo/raw_int8_convrot 13.5 GB；qwen3vl_4b_int8_convrot；qwen_image_vae | Krea 2 Community：年收入低于 100 万美元可商用 | 原生只有风格参考；身份参考走 EditPlus 编码（ganloss 07-08 写法） | 原生（CLIPLoader 类型 krea2） | [Comfy-Org/Krea-2@1171f4d](https://huggingface.co/Comfy-Org/Krea-2) | 高 |
| Krea 2 Identity Edit V2 / General Edit V2 LoRA | 各 1.83 GB | **仅非商用**（krea-2-identity-edit-v2-license），项目方本地自用 | 2 口：场景 + 人物 | 要装 comfyui-krea2edit v2.0.0（项目方 10-31 批准，代码已审，见 §5） | [conradlocke/krea2-identity-edit@f33b262](https://huggingface.co/conradlocke/krea2-identity-edit) | 高 |
| Z-Image Turbo / Base（6B） | z_image_turbo / z_image_int8_convrot 6.2 GB；qwen_3_4b；ae | Apache-2.0 | 无（Z-Image-Edit 还没发布） | 原生（lumina2） | [Comfy-Org/Z-Image-Turbo](https://huggingface.co/Comfy-Org/Z-Image-Turbo)、[Comfy-Org/Z-Image](https://huggingface.co/Comfy-Org/Z-Image) | 高 |
| FLUX.2 [klein] 4B / 4B Base | 各 7.75 GB；qwen_3_4b；flux2-vae | Apache-2.0 | 多参考（ReferenceLatent） | 原生（flux2） | [Comfy-Org/Flux-2-Klein-4B](https://huggingface.co/Comfy-Org/Flux-2-Klein-4B) | 高 |
| FLUX.2 [klein] 9B / 9B Base | 各 18.2 GB；qwen_3_8b_fp8mixed | **FLUX Non-Commercial** | 多参考 | 原生 | [9B](https://huggingface.co/black-forest-labs/FLUX.2-klein-9B)、[9B Base](https://huggingface.co/black-forest-labs/FLUX.2-klein-base-9B)（gated，等项目方的令牌） | 高 |
| FLUX.3 Image Klein（2026-10-14） | int8_convrot 5.8 GB | FLUX Kommunity：年收入低于 500 万美元可商用出图 | 最多 10 张 | CLIPLoader 有 flux3 类型；工作流等 gated README | [flux-3-image-klein-comfy](https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy)（gated） | 中 |
| Qwen-Image-Edit-2511 | qwen_image_edit_2511_int8_convrot 20.5 GB；qwen_2.5_vl_7b_fp8_scaled；Lightning 4 步 LoRA | Apache-2.0 | 3 张 | 原生 TextEncodeQwenImageEditPlus | [Comfy-Org/Qwen-Image-Edit](https://huggingface.co/Comfy-Org/Qwen-Image-Edit)、[lightx2v Lightning](https://huggingface.co/lightx2v/Qwen-Image-Edit-2511-Lightning) | 高 |
| FireRed-Image-Edit 1.1 | 社区 fp8_scaled 20.4 GB（官方 bf16 40.9 GB，超过 25 GB，没下）；Lightning 8 步 v1.2 | Apache-2.0 | 3 张（Qwen-Edit 架构） | 原生 Qwen-Edit 节点 | [drbaph quants](https://huggingface.co/drbaph/FireRed-Image-Edit-1.1_ComfyUI_Quants)、[官方](https://huggingface.co/FireRedTeam/FireRed-Image-Edit-1.1-ComfyUI) | 中（fp8 是社区量化） |
| MOSS-Image SFT（ganloss 10-30） | 没下 | Apache-2.0 | 编辑要靠 LoRA | 原生 moss_image | [Comfy-Org/MOSS-Image](https://huggingface.co/Comfy-Org/MOSS-Image) | 下一轮 |
| JoyAI Image Edit（ganloss 07-22） | 没下 | 见仓库 | 有 | 原生 TextEncodeJoyImageEdit | ganloss 07-22 | 下一轮 |

Civitai 写实微调和写实 LoRA（各基模下载量前三，详细数字见调研记录）：
- **Krea 2**：Real Dream ckpt（mv 3396368，19.2 万下载，Image+Sell）、Realistic Snapshot LoRA（3371723）、Realism Engine LoRA（3109006）
- **Z-Image Turbo**：Real Dream（3032830）、Realistic Snapshot（2617751）
- **Klein 9B**：Real Dream（3108757）、UltraReal（3370879）
- **第 2 轮计划**：Civitai 下载要用 Civitai 令牌。第 1 轮先比各基模的原版，胜出的基模在第 2 轮叠它的写实微调或 LoRA。

ganloss 工作流里没有本地副本的：z_image 系列 01-29、02-03、11-28，fireRed 02-26。这些按 Comfy 官方模板的写法做。

## 2. 对照协议（固定、可复现；GEN_CONTRACT v1）

见 `tools/bakeoff/run.py` 的文件头。

**8 个镜头**
- B1 ep01-S5：林晚，近景
- B2 ep10-S4：林晚，中近景
- B3 ep01-S1：林晚，特写
- B4 ep01-S3：林晚，中全景（全身）
- B5 ep09-S2：顾沉，中景
- B6 ep05-S2：阿岚，特写
- B7 ep01-S6：双人
- B8：办公区空镜

**两组**
- contract：契约输入。槽位优先级：身份脸 > 造型设定图 > 场景（I9）。
- text：只给文字，作对照。

**其他设定**
- 每组 2 个 seed。
- 统一 1.5 倍出图（1152×2016），再 lanczos 缩到 768×1344，不锐化。
- 现行出图（IMGGEN 的 series10 首帧）一起打分，作为"已知差"的参照。

**编辑对比**：源图是 ep05-S5_s20262612（IMGGEN 判不合格，林晚 0.534）。
- E1：换成林晚的脸
- E2：去油光、加毛孔
- E3：背景换成深夜办公室（sk_office）

**质检**：Q1–Q7，见 score_srv.py。

**提示词**：剧本内容不改。系统层只做这几件事：
- 去掉旧的参考图注释和 lnwan_qi 触发词（I8）
- 旧后缀"奶油虚化 / 浓郁饱和"换成徕卡 S★ 后缀（I7）
- 参考图注释按各模型写法重标：Qwen 2.1 用 `<imageN>`，Qwen-Edit / Krea2 用"图N"，Klein 用"image N"
- 剧本原文是中文，所有模型的文本编码器都是 Qwen 系多语模型，所以不翻译（翻译属于内容改写，Claude 不做）

## 3. 结果（第 1 轮，2026-11-01）

**覆盖范围**：各模型主要跑了第 1 个 seed，共 164 张，含编辑 18 张、现行出图和 IMGGEN 参照 11 张。夜里 GPU 让给出帧，按 K-OPS-B06 处理，所以以下几组还缺：
- FireRed 契约组只有 1 张；
- Z-Image Base、Klein 4B Base 各只有 1 张；
- v9 重档 0 张；
- Klein 9B、FLUX.3 klein：令牌无效，没测。

这几组的结论都标"待补"。

**数据位置**：
- 契约逐项：data/ab/image_bakeoff/rescore_pf33.json（11-01 用现行口径重打 188 张；旧的 all_pf33.json / heldout_pf33.json 保留作对照）。用的是 REFLOCK 的 remote_score.postflight_full（gpu33 CLIP），Q1–Q7 通过 / 不通过 / 不适用 / 未测。
- 质感综合：BAKEOFF 的脸部指标，见 score_srv.py。
- 接触印样：data/review_pages/image_bakeoff/contact_t2i.jpg、contact_edit.jpg。

**表格说明**：
- 下表按质感综合分排序。
- 百分比 = 过线张数 ÷（过线 + 不过线）；不适用和未测不进分母，未测数单列。
- *Q4 的契约线留出复核不成立（K-REV-B02），这一列只作参考。

| 模型 · 组 | 张数 | 质感综合 | 林晚余弦(ref2va) | Q1 | Q2 | Q3 | Q4* | Q5 | Q6 | Q7 | 未测 | 单张 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Z-Image Base（纯文字，无参考槽） · text | 1 | 1.150 | -0.085 | 0% | 100% | 100% | 100% | 0% | 100% | 100% | 0 | 185s |
| FLUX.2 [klein] 4B（蒸馏 4 步，多参考） · face | 7 | 0.701 | 0.429 | 14% | 86% | 100% | 100% | 100% | 100% | 100% | 0 | 25s |
| FLUX.2 [klein] 4B（蒸馏 4 步，多参考） · text | 8 | 0.680 | 0.162 | 0% | 86% | 100% | 100% | 88% | 100% | 100% | 0 | 14s |
| FLUX.2 [klein] 4B（蒸馏 4 步，多参考） · contract | 8 | 0.640 | 0.426 | 12% | 86% | 100% | 100% | 100% | 100% | 100% | 0 | 27s |
| Krea 2 Raw + Turbo LoRA 0.6 · 参考图（ganloss 07-0 · text | 7 | 0.592 | 0.173 | 0% | 100% | 86% | 100% | 100% | 100% | 100% | 0 | 77s |
| FLUX.2 [klein] 4B Base（50 步 cfg4，多参考） · text | 1 | 0.460 | -0.066 | 0% | 100% | 100% | — | 0% | 100% | 100% | 0 | 93s |
| Qwen-Image-Edit-2511 + Lightning 4 步 · text | 8 | 0.386 | 0.292 | 0% | 86% | 100% | 100% | 100% | 100% | 100% | 0 | 86s |
| Krea 2 Turbo + Identity Edit V2 / General Edit · contract | 6 | 0.314 | 0.509 | 17% | 100% | 100% | 100% | 83% | 100% | 100% | 0 | 212s |
| IMGGEN S★+脸+去头造型图（写实·中，含锐化） · IMGGEN S★+脸+去头造型 | 2 | 0.252 | 0.774 | 100% | 100% | 100% | 100% | 50% | 100% | 100% | 0 | — |
| FLUX.2 [klein] 4B Base（50 步 cfg4，多参考） · contract | 1 | 0.183 | 0.226 | 0% | 100% | 100% | — | 100% | 0% | 100% | 0 | 359s |
| Z-Image Turbo（纯文字，无参考槽） · text | 15 | 0.170 | 0.402 | 0% | 92% | 100% | 100% | 93% | 93% | 100% | 0 | 46s |
| IMGGEN REFLOCK 资产槽位 S★（含锐化） · IMGGEN REFLOCK 资 | 2 | 0.159 | 0.734 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 0 | — |
| FireRed-Image-Edit 1.1 fp8 + Lightning 8 步 · contract | 1 | -0.004 | 0.801 | 100% | 100% | 100% | — | 100% | 100% | 100% | 0 | 55s |
| Qwen-Image 2.1 Turbo · 徕卡 S★（现行基线，去 lin_wan_qi · text | 14 | -0.116 | 0.190 | 7% | 100% | 100% | 100% | 93% | 100% | 100% | 0 | 48s |
| Qwen-Image 2.1 Turbo · 徕卡 S★（现行基线，去 lin_wan_qi · face | 11 | -0.150 | 0.719 | 82% | 100% | 100% | 100% | 91% | 100% | 91% | 0 | 51s |
| FLUX.2 [klein] 4B（蒸馏 4 步，多参考） · edit·未比对造型 | 3 | -0.219 | 0.516 | 0% | — | — | 100% | 100% | 100% | — | 0 | 16s |
| Qwen-Image-Edit-2511 + Lightning 4 步 · contract | 8 | -0.291 | 0.635 | 62% | 86% | 100% | 100% | 100% | 100% | 100% | 0 | 68s |
| Qwen-Image 2.1 Turbo · 徕卡 S★（现行基线，去 lin_wan_qi · contract | 13 | -0.335 | 0.662 | 54% | 100% | 100% | 100% | 85% | 100% | 100% | 0 | 68s |
| Krea 2 Turbo + Identity Edit V2 / General Edit · edit·未比对造型 | 3 | -0.337 | 0.561 | 0% | — | — | 100% | 100% | 100% | — | 0 | 103s |
| R2 对照：同上去噪 0.30，不保护脸（看脸会不会被改掉） · r2 | 8 | -0.339 | 0.623 | 38% | 100% | 100% | 100% | 100% | 88% | 100% | 0 | 11s |
| Qwen-Image 2.1 Turbo · 徕卡 S★（现行基线，去 lin_wan_qi · edit·未比对造型 | 3 | -0.373 | 0.605 | 33% | — | — | 100% | 100% | 100% | — | 0 | 40s |
| R2：Qwen 2.1 S★ → Klein 4B 质感加工（去噪 0.30，脸部掩码保护） · r2 | 8 | -0.383 | 0.616 | 38% | 100% | 100% | 100% | 100% | 88% | 100% | 0 | 37s |
| Krea 2 Turbo（纯文字） · text | 16 | -0.402 | 0.283 | 0% | 86% | 71% | — | 88% | 100% | 79% | 0 | 66s |
| Qwen-Image-Edit-2511 + Lightning 4 步 · face | 3 | -0.412 | 0.523 | 0% | 100% | 100% | 100% | 67% | 100% | 100% | 0 | 185s |
| R2：Qwen 2.1 S★ → Klein 4B 质感加工（去噪 0.45，脸部掩码保护） · r2 | 8 | -0.418 | 0.615 | 38% | 100% | 100% | 100% | 100% | 100% | 100% | 0 | 20s |
| FireRed-Image-Edit 1.1 fp8 + Lightning 8 步 · edit·未比对造型 | 3 | -0.501 | 0.591 | 33% | — | — | — | 100% | 100% | — | 0 | 37s |
| 现行出图（IMGGEN series10 第一轮，带 lin_wan_qi） · 现行 | 7 | -0.566 | 0.917 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 0 | — |
| Krea 2 Raw + Turbo LoRA 0.6 · 参考图（ganloss 07-0 · edit·未比对造型 | 3 | -0.653 | 0.397 | 0% | — | — | 100% | 100% | 100% | — | 0 | 39s |
| Qwen-Image-Edit-2511 + Lightning 4 步 · edit·未比对造型 | 3 | -0.735 | 0.502 | 0% | — | — | — | 100% | 100% | — | 0 | 252s |
| FireRed-Image-Edit 1.1 fp8 + Lightning 8 步 · text | 1 | -1.103 | 0.202 | 0% | 100% | 100% | — | 100% | 100% | 100% | 0 | 22s |
| Krea 2 Raw + Turbo LoRA 0.6 · 参考图（ganloss 07-0 · contract·输出=参考板（ | 6 | — | — | — | — | — | — | — | — | — | 0 | — |

（11-01 上午更新：契约逐项改用 rescore_pf33.json，即现行口径的 Q5 / 新 Q1；“输出=参考板”的整组和单张不计分，单列；编辑组标“未比对造型”；第 2 轮 r2_* 三组见 docs/ep02_iter/bakeoff_r2.md。）

**编辑对比**：源图是 ep05-S5_s20262612（IMGGEN 判不合格，林晚 0.534）。
- E1：换成林晚的脸
- E2：去油光、加毛孔
- E3：背景换成深夜办公室（sk_office）

**质检**：Q1–Q7，见 score_srv.py。

**提示词**：剧本内容不改。系统层只做这几件事：
- 去掉旧的参考图注释和 lnwan_qi 触发词（I8）
- 旧后缀"奶油虚化 / 浓郁饱和"换成徕卡 S★ 后缀（I7）
- 参考图注释按各模型写法重标：Qwen 2.1 用 `<imageN>`，Qwen-Edit / Krea2 用"图N"，Klein 用"image N"
- 剧本原文是中文，所有模型的文本编码器都是 Qwen 系多语模型，所以不翻译（翻译属于内容改写，Claude 不做）

## 3. 结果（第 1 轮，2026-11-01）

**覆盖范围**：各模型主要跑了第 1 个 seed，共 164 张，含编辑 18 张、现行出图和 IMGGEN 参照 11 张。夜里 GPU 让给出帧，按 K-OPS-B06 处理，所以以下几组还缺：
- FireRed 契约组只有 1 张；
- Z-Image Base、Klein 4B Base 各只有 1 张；
- v9 重档 0 张；
- Klein 9B、FLUX.3 klein：令牌无效，没测。

这几组的结论都标"待补"。

**数据位置**：
- 契约逐项：data/ab/image_bakeoff/rescore_pf33.json（11-01 用现行口径重打 188 张；旧的 all_pf33.json / heldout_pf33.json 保留作对照）。用的是 REFLOCK 的 remote_score.postflight_full（gpu33 CLIP），Q1–Q7 通过 / 不通过 / 不适用 / 未测。
- 质感综合：BAKEOFF 的脸部指标，见 score_srv.py。
- 接触印样：data/review_pages/image_bakeoff/contact_t2i.jpg、contact_edit.jpg。

**表格说明**：
- 下表按质感综合分排序。
- 百分比 = 过线张数 ÷（过线 + 不过线）；不适用和未测不进分母，未测数单列。
- *Q4 的契约线留出复核不成立（K-REV-B02），这一列只作参考。

| 模型 · 组 | 张数 | 质感综合 | 林晚余弦(ref2va) | Q1 | Q2 | Q3 | Q4* | Q5 | Q6 | Q7 | 未测 | 单张 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Z-Image Base（纯文字，无参考槽） · text | 1 | 1.078 | -0.085 | 0% | 100% | 100% | 100% | 0% | 100% | 100% | 0 | 185s |
| FLUX.2 [klein] 4B（蒸馏 4 步，多参考） · face | 7 | 0.633 | 0.429 | 14% | 86% | 100% | 86% | 100% | 100% | 100% | 0 | 25s |
| FLUX.2 [klein] 4B（蒸馏 4 步，多参考） · text | 8 | 0.605 | 0.162 | 0% | 86% | 100% | 62% | 88% | 100% | 100% | 0 | 14s |
| FLUX.2 [klein] 4B（蒸馏 4 步，多参考） · contract | 8 | 0.575 | 0.426 | 12% | 86% | 100% | 75% | 75% | 100% | 100% | 0 | 27s |
| Krea 2 Raw + Turbo LoRA 0.6 · 参考图（ganloss 07-0 · text | 7 | 0.514 | 0.173 | 0% | 86% | 86% | 86% | 86% | 100% | 100% | 0 | 77s |
| FLUX.2 [klein] 4B Base（50 步 cfg4，多参考） · text | 1 | 0.398 | -0.066 | 0% | 100% | 100% | 0% | 0% | 100% | 100% | 0 | 93s |
| Qwen-Image-Edit-2511 + Lightning 4 步 · text | 8 | 0.323 | 0.292 | 0% | 86% | 100% | 38% | 100% | 100% | 100% | 0 | 86s |
| Krea 2 Turbo + Identity Edit V2 / General Edit · contract | 6 | 0.251 | 0.509 | 0% | 100% | 100% | 83% | 67% | 100% | 100% | 0 | 212s |
| IMGGEN S★+脸+去头造型图（写实·中，含锐化） · IMGGEN S★+ | 2 | 0.195 | 0.774 | 100% | 100% | 100% | 100% | 0% | 100% | 100% | 0 | — |
| Krea 2 Raw + Turbo LoRA 0.6 · 参考图（ganloss 07-0 · contract | 6 | 0.146 | 0.406 | 0% | 83% | 83% | 100% | 67% | 17% | 83% | 0 | 84s |
| FLUX.2 [klein] 4B Base（50 步 cfg4，多参考） · contract | 1 | 0.126 | 0.226 | 0% | 100% | 100% | 0% | 0% | 0% | 100% | 0 | 359s |
| Z-Image Turbo（纯文字，无参考槽） · text | 15 | 0.112 | 0.402 | 0% | 86% | 100% | 67% | 80% | 93% | 100% | 0 | 46s |
| IMGGEN REFLOCK 资产槽位 S★（含锐化） · IMGGEN REF | 2 | 0.103 | 0.734 | 100% | 100% | 100% | 100% | 100% | 100% | 100% | 0 | — |
| FireRed-Image-Edit 1.1 fp8 + Lightning 8 步 · contract | 1 | -0.057 | 0.801 | 100% | 100% | 100% | 0% | 100% | 100% | 100% | 0 | 55s |
| Qwen-Image 2.1 Turbo · 徕卡 S★（现行基线，去 lin_wan_qi · text | 14 | -0.172 | 0.190 | 7% | 91% | 100% | 17% | 86% | 100% | 100% | 4 | 48s |
| Qwen-Image 2.1 Turbo · 徕卡 S★（现行基线，去 lin_wan_qi · face | 11 | -0.202 | 0.719 | 73% | 91% | 100% | 18% | 64% | 100% | 91% | 0 | 51s |
| FLUX.2 [klein] 4B（蒸馏 4 步，多参考） · edit | 3 | -0.269 | 0.516 | 0% | — | — | 33% | 100% | 100% | — | 0 | 16s |
| Qwen-Image-Edit-2511 + Lightning 4 步 · contract | 8 | -0.346 | 0.635 | 50% | 100% | 100% | 38% | 75% | 100% | 100% | 0 | 68s |
| Krea 2 Turbo + Identity Edit V2 / General Edit · edit | 3 | -0.386 | 0.561 | 0% | — | — | 33% | 100% | 100% | — | 0 | 103s |
| Qwen-Image 2.1 Turbo · 徕卡 S★（现行基线，去 lin_wan_qi · contract | 13 | -0.387 | 0.662 | 46% | 100% | 100% | 62% | 85% | 100% | 100% | 0 | 68s |
| Qwen-Image 2.1 Turbo · 徕卡 S★（现行基线，去 lin_wan_qi · edit | 3 | -0.423 | 0.605 | 33% | — | — | 67% | 67% | 100% | — | 0 | 40s |
| Krea 2 Turbo（纯文字） · text | 16 | -0.450 | 0.283 | 0% | 86% | 71% | 0% | 88% | 100% | 79% | 0 | 66s |
| Qwen-Image-Edit-2511 + Lightning 4 步 · face | 3 | -0.465 | 0.523 | 0% | 100% | 100% | 33% | 33% | 100% | 100% | 0 | 185s |
| FireRed-Image-Edit 1.1 fp8 + Lightning 8 步 · edit | 3 | -0.548 | 0.591 | 33% | — | — | 0% | 100% | 100% | — | 0 | 37s |
| 现行出图（IMGGEN series10 第一轮，带 lin_wan_qi） · 现行 | 7 | -0.611 | 0.917 | 86% | 86% | 100% | 14% | 100% | 100% | 100% | 0 | — |
| Krea 2 Raw + Turbo LoRA 0.6 · 参考图（ganloss 07-0 · edit | 3 | -0.716 | 0.397 | 0% | — | — | 100% | 100% | 100% | — | 0 | 39s |
| Qwen-Image-Edit-2511 + Lightning 4 步 · edit | 3 | -0.782 | 0.502 | 0% | — | — | 0% | 67% | 100% | — | 0 | 252s |
| FireRed-Image-Edit 1.1 fp8 + Lightning 8 步 · text | 1 | -1.142 | 0.202 | 0% | 100% | 100% | 0% | 100% | 100% | 100% | 0 | 22s |

**编辑对比**（ep05-S5_s20262612，源图林晚 0.534；seed 20261031）：

| 任务 | Qwen 2.1 | Qwen-Edit 2511 | FireRed 1.1 | Klein 4B | Krea2 IdEdit/GenEdit | Krea2 ref |
|---|---|---|---|---|---|---|
| E1 换脸（林晚余弦） | **0.753** | 0.564 | 0.711 | 0.682 | 0.628 | 0.571（构图被改成两联图） |
| E2 去油加毛孔（脸部高频 / 林晚余弦） | 1.65 / 0.50 | 1.48 / 0.49 | 1.38 / 0.56 | **2.12** / 0.39 | 1.41 / 0.53 | 1.35 / 0.24（漆皮油光 0.11） |
| E3 换背景（颜色直方图代理，仅参考 / 接触印样观感） | 0.87，构图被重排 | 0.16，换了 | 0.02，没换 | 0.06，换了 | 0.01，没换 | 0.02，两联图 |

## 4. 排名与推荐

**排名**：两个维度分开排，因为没有一个模型同时赢两项。

- **质感**（脸部综合分，契约组；11-01 现行口径重算，见 data/ab/image_bakeoff/summary.json）：Klein 4B（+0.64）> Krea2 IdEdit（+0.31）> Z-Image Turbo（纯文字，+0.17）> FireRed（0.00，n=1）> 2511（−0.29）> Qwen 2.1 S★（−0.34）> 现行出图（−0.57）。Krea2 ref 契约组是参考板拼图，不计分。
  IMGGEN 修过的 2.1 配方 v10 / vR 是 +0.20 / +0.10，但含锐化后处理，不完全可比。
- **身份**（契约 Q1 过线率 / 林晚余弦）：
  - 现行出图 86% / 0.92（靠已禁用的 lin_wan_qi）
  - IMGGEN v10 / vR 100% / 0.77、0.73（n=2）
  - FireRed 100% / 0.80（n=1）
  - Qwen 2.1 只挂脸 82% / 0.72
  - 2511 契约组 62% / 0.64
  - Qwen 2.1 契约组 54% / 0.66
  - Krea2 IdEdit 17% / 0.51；Klein 4B 12–14% / 0.43；只给文字的各组 ≤7%

**推荐（不切换，等项目方看对照页）**：

1. 首帧主模型不换，继续用 Qwen 系（2.1 S★，或 FireRed 1.1，后者等补测）。Klein、Z-Image、Krea 2 的写实度明显更高，但带参考图也保不住林晚的脸，契约 Q1 过不了。
2. 第 2 轮已经验证、结果不成立（K-REN-B09，见 docs/ep02_iter/bakeoff_r2.md）的方案："Qwen 出图（身份 + 构图 + 造型）→ Klein 4B 第二段质感加工"。做法是低去噪重绘或 E2 式去油编辑，脸部用掩码保护，身份过 Q1 才放行。
   - 要改的地方：出图图里加一段 Klein 4B（原生节点 ReferenceLatent、Flux2Scheduler，4 步 cfg 1，约 10–25 秒 / 张）；config/render_quality.json 加预设；REFLOCK lora_allow 不用动（没有挂 LoRA）。
   - 先不改，等项目方看过对照页再说。
3. 指令改图：换脸继续用 Qwen 2.1 edit（E1 最好）。去油、加毛孔改用 Klein 4B，但必须过身份闸门（E2 的林晚余弦掉到 0.39）。EDITDEL 的 edit_engines.json 里，等项目方确认后再打开 flux2_klein。
4. 许可提醒：Qwen-Image 2.1 是研究许可，只能非商用；Klein 4B、Z-Image、2511、FireRed 是 Apache-2.0；Krea 2 年收入低于 100 万美元可商用；Krea2 Identity Edit LoRA 只能非商用。

## 6. 让道事故与修复

11-01 13:04 我把 hold 文件删了，只靠"队列里有别人的任务就让"。但出帧方是等道空了才提交，结果 02:27 BAKEOFF 占满了 gpu36:0/1。

修复：hold 文件常驻，再加上"空闲 180 秒才交"（run.py wait_yield，tests/test_bakeoff.py）。见 K-OPS-B06。

## 5. 第三方节点审查记录：comfyui-krea2edit

- **版本**：v2.0.0，commit 13ef60f20828949becada815d3cbc371eb5ccaab，codeload tar 的 sha256 是 b9d5df4f…99f645e3。
- **审查结论**：538 行的 `__init__.py` 逐行读过：
  - 没有网络访问、subprocess、eval/exec、pickle/torch.load；
  - 唯一的读文件操作是读自己的 pyproject 拿版本号；
  - 依赖为空，所以不用 pip 安装；
  - node.zip 是 `__init__.py` 的重复副本（sha 相同），已排除。
- **安装**：装到 gpu36 的 `custom_nodes/comfyui-krea2edit`。装前装后的 pip freeze 相同，`__init__.py` 的 sha 是 20c89b7a…f1731bf77，导入检查通过。
