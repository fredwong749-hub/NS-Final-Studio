# 真人写实调参：社区做法补充 + 现行参数对照 + 锐化 A/B（R11-12 / R11-13）

> 2026-11-01，RESEARCH（总调度 fredw-2b 派）。按 §G0，先读了已有成果，没有重做：docs/qwen21/RESEARCH.md（官方参数 20 条）、docs/qwen21/COMMUNITY_PHOTOREAL.md（Civitai 写实 LoRA）、docs/research/quality_deep/03_image21_film_look.md、docs/ep02_iter/workflow_library.md（236 个 Qwen 2.1 工作流参数分布）、docs/research_adoption.md、knowledge/rules/render_qwen21.yaml（K-REN-Q21…K-WRT-Q29）、RSI_LEDGER BK1–BK11、契约 Q4。
> 这里只写三样新东西：①上面没有覆盖的社区原文（锐化、Turbo 加速 LoRA、放大重绘、两段式、厂商横评）；②现行参数逐项对照；③锐化三档 A/B 的数字（CPU，同一张生产原图）。
> 置信度：高 = 官方或作者原话 / 我们自己的可复现测量；中 = 多来源一致或作者自述；低 = 单帖、厂商博客或推断。Reddit 不能直连，只能用 reddit.sentinel-team.org 快照。


> ⤴ **结论（11-01 17:5x，L-087）**：项目方看过锐化三档，原话“realism_ab……这个版本出来的东西,无论是画面效果还是颜色,都非常满意……很棒哎!”，并选“R0 现在这样”。现行徕卡 S★ 全套（USM 1.2/60/2、后缀、系统规格句）和契约 Q4 口径都不改；下文“建议改锐化 / 后缀 / Q4”的部分不采纳，GPU 档 G1 / G2 取消。研究记录保留。

## 一、新补的社区结论（每条带原文）

| # | 结论 | 原文（节选） | 来源 | 置信度 |
|---|---|---|---|---|
| N1 | 在 Turbo checkpoint 上再叠加速 LoRA 会出皮革感和颗粒（与 RESEARCH #20 一致，补作者原话） | “Do not add a speed LoRA.” / “Viggle Turbo on top of this checkpoint broke the picture” / “leathery skin and grit” | https://civarchive.com/models/2994247 （Qwen Image 2.1 Turbo Generate + Edit v1.2） | 中 |
| N2 | 普通 KSampler 设 8 步（不用官方 sigma）出图发“砂”；我们用官方 ManualSigmas，一致 | “A plain KSampler set to 8 steps came out gritty in my tests, so there is no Steps box.” | 同上 | 中 |
| N3 | 出图太小会丢微小皮肤痕迹，约 2MP 能保住；我们第一遍 1152×2016≈2.3MP，一致 | “From a very small picture, tiny marks like small freckles can go; from 2 megapixels they stay.” | 同上 | 中低（单作者） |
| N4 | 用 Qwen 自己做放大是“重画”，细节是编出来的；v1.1 放大曾在皮肤上画出细黑线 | “The upscale is a redraw. Fine detail is made up to fit.” / “Upscale the result drew fine dark lines on skin.” | 同上 | 中 |
| N5 | 放大 / 修复时 Qwen 2.1 会凭空加毛孔、雀斑、胡茬，让脸显老；Restore LoRA 就是为压这个训练的（step 1500 最接近原图但皮肤略光，1250 保留更多纹理） | 中文版：普通 Qwen-Image 2.1 会在小图或压缩图上虚构毛孔、雀斑和胡茬，让人脸看起来老几岁 | https://comfyui-wiki.com/zh/news/2026-10-07-qwen-image-2-1-restore-lora | 中（作者实测转述；HF 原页没打开） |
| N6 | 社区 4 步两段式：832×1248 出图 → 细节第二遍 denoise 0.35 到 1664×2496；simple 调度偶尔出“淡淡的第二个人”，beta 没有 | “4 steps, CFG 1, euler, beta.” / “a faint second copy of the person” | https://civitai.com/api/v1/models/2994006 | 低（单作者，加速 LoRA 路线，不是官方 Turbo） |
| N7 | 厂商横评：Qwen 2.1 零样本写实 3.0/5；强光近景鼻额油光；皮肤放大后有重复的微纹理 | “specular highlights can appear overly harsh, leaving an artificially oily sheen across the nose and forehead” / “micro-pattern repetition under zoom” | https://www.atlascloud.ai/blog/tips/gpt-image-2.5-vs-qwen-image-2.1 | 低（厂商自测，有利益相关） |
| N8 | 过度锐化是“假”的常见来源；r/StableDiffusion 一个“去塑料感”算法帖，被大量评论指出只是重度 USM | “A very strong "unsharp mask" filter, too much for me.” / “It looks completelly sharpned to death.” / “They look even more fake, sorry.” | https://reddit.sentinel-team.org/posts/1s8ppel/snapshots/2026-04-03T19%3A17%3A05.459795Z （Z-Image 帖，不是 Qwen） | 中（多人一致，模型不同） |
| N9 | 锐化补不出模型没生成的纹理；去 AI 感常用的是轻颗粒，不是锐化 | “sharpening can't restore texture the model never generated”（转述） | https://www.weshop.ai/blog/?p=120027 、https://www.runcomfy.com/comfyui-nodes/comfyui-propost/ProPostFilmGrain | 低 |
| N10 | 真实照片训练的亚洲人像 LoRA：NiceGirls Asians 作者推荐 0.6–0.8，可与其它风格 LoRA 叠 | “Use it with strength 0.6-0.8.” / “Can be used with other loras” | https://huggingface.co/Danrisi/niceasians_qwen2.1 （许可标 qwen-research） | 中（作者自述，Turbo 上没人测过） |
| N11 | texture_fix VAE 只重训解码器、潜空间不变，修棋盘格；作者用风景图对比，没有专门测人脸 | “keeps the exact same latent space, and only retrains the decoder” | https://comfyui-wiki.com/en/news/2026-09-24-texture-fix-vae-qwen-image-2-1 | 中（我们已在用） |
| N12 | WarmBloodAban 的 Anything2RealCharacters（插画转真人）推荐 euler + FlowMatchEulerDiscrete，0.6–0.8；是 edit 用途，和我们的 T2I 首帧不对口 | “start LoRA strength between 0.6 and 0.8” | https://comfyui-wiki.com/en/news/2026-09-27-qwen-image-2-1-loras | 低 |
| — | 手部：没找到 Qwen 2.1 专门的修手做法；社区只有“低 / 中 denoise 再过一遍”的泛说法。官方文档写手指约 30 步收敛（RESEARCH S10），只对 base 有意义 | — | https://reddit.sentinel-team.org/posts/1t8ognk/snapshots/2026-05-15T21%3A30%3A42.175693Z | 低 |

FLUX.2 Klein 只作对照：参数和 LoRA 已在 COMMUNITY_PHOTOREAL §一；BK1 实测 Klein 4B 质感 +0.58 但林晚 Q1 过线 12%，不能直接换（K-REN-B01）。本轮没有新增。

## 二、现行参数对照（frame_v9 / leica_sstar 预览档；定稿档 final）

| 项 | 现行 | 研究结论 | 判定 | 建议 |
|---|---|---|---|---|
| 采样 | Turbo int8，官方 8 个 sigma + 0，euler，cfg 1 | 官方逐位一致（RESEARCH #1）；N2 | 一致 | 不改（K-REN-Q21） |
| 负面提示 | Turbo 不送（cfg 1）；定稿档 cfg 3 送“塑料皮肤，过度磨皮…” | cfg 1 负面无效；base cfg 3–4 + 负面是社区修塑料 / 手的常用法 | 一致 | — |
| 出图尺寸 | 1152×2016 出 → lanczos 缩回 768×1344 | 原生 9:16 是 1536×2752（RESEARCH #8）；≈2MP 保微痕（N3） | 部分 | 原生尺寸由 BAKEOFF qa_native 验，不重复 |
| 后处理锐化 | USM 半径 1.2 / 60% / 阈值 2 | 过度锐化显假（N8、N9）；本轮实测：USM 让整图 Laplacian 翻倍、边缘过冲 +53–71%，“塑料脸”探针 p_plastic 不变（§三） | 不一致（对“真人感”无帮助，只抬指标） | 项目方选定的 S★，不改默认；建议 A/B 给项目方盲看 R0/R1/R2（🔴 见报告） |
| 风格后缀 | “…焦点锐利，微反差强，皮肤纹理清晰，自然高光，暖调通透，干净真实” | 官方改写器不写助推词（RESEARCH #7）；固定“暖调”与 35/80 条正文冷光冲突（RL02） | 不一致 | 后缀改写属推翻项目方选择，交总调度；A/B 组 G1 / qa_suffix |
| 系统规格句 | “面部清晰对焦，五官锐利”、lens_template“锐利解析力与微反差…毛孔” | 同上，叠在 USM 上是三重锐化（RL01 80/80） | 不一致 | 同上 |
| 写实套话 | 写作方按附录固定写“真实皮肤质感，可见细小毛孔与细软绒毛…” | QL10 / QL13；N5：Qwen 本来就爱“加毛孔、显老” | 存疑 | 项目方 10-29 原话定的写法，不动；A/B G1 测删掉后的效果 |
| 写实 LoRA | krea2_film_texture 0.5 | 作者在 base 40 步 CFG 2 训练，Turbo 未验证；训练数据是生成图（RESEARCH #10、quality_deep 03 §0.2） | 部分 | A/B G2 换真实照片数据训练的 NiceGirls Asians 0.6（gpu36 已有） |
| 加速 LoRA | 不叠 | N1 | 一致 | 保持 |
| VAE | texture_fix | N11、RESEARCH #13 | 一致 | — |
| 身份 | 林晚 LoRA 已撤，身份脸参考 | BK2：Qwen 契约组有参考时质感降约 0.2 | 一致（项目方定） | — |
| 定稿档第二遍 | Base denoise 0.30 重绘 1152×2016 | N4 / N5：Qwen 重绘会编纹理、显老；>0.4 脸漂（D2） | 部分 | 定稿档目前不出图（owner_decisions L-017 被 frame_v9 取代）；若恢复，第二遍考虑 Restore LoRA（需下载，见报告） |
| 契约 Q4 | lap_full ≥175，在锐化后的交付图上测 | §三：去掉 USM 后 3/3 从过线变不过线 | 不一致 | K-REV-X01；交 REFLOCK / 总调度改口径（在 raw 或未锐化图上测，或干脆只看脸部指标） |

## 三、锐化三档 A/B（CPU，已跑）

- 做法：tools/research/realism_ab.py。ep01-S1（特写）、S2（中景）、S5（近景），都是办公室夜景、非亲密；取生产当前首帧的 1152×2016 原图（take.raw_file），按 ns_render.image_params.post_file 同一后处理重做。R0 与生产交付图逐像素平均差 = 0.0（复现的就是同一条链）。没用 GPU，没写 takes.json。
- 数字（data/ab/realism_ab/metrics.json）：

| 镜 | lap_full R0 / R1 / R2 | halo R0 / R1 / R2 | face_hf R0 / R1 / R2 | p_plastic（三档） |
|---|---|---|---|---|
| ep01-S1 特写 | 235.7 / 112.4 / 146.3 | 2.83 / 1.66 / 1.92 | 2.27 / 1.84 / 1.92 | 0.9999 / 0.9999 / 0.9999 |
| ep01-S2 中景 | 187.2 / 90.6 / 116.0 | 3.00 / 1.96 / 2.19 | 2.22 / 1.78 / 1.86 | 0.9999 / 0.9999 / 0.9999 |
| ep01-S5 近景 | 200.0 / 98.8 / 126.6 | 3.45 / 2.26 / 2.55 | 3.04 / 2.33 / 2.49 | 0.9994 / 0.9995 / 0.9995 |

- 读法：①USM 单独把 lap_full 抬到 2.02–2.10 倍，契约 Q4 线 175 在这 3 镜上完全是 USM 决定的（R1 全不过、R0 全过）；leica_sharp 旧图 Sstar_g→Sstar 同样 ×2.05–2.14（ep02 三镜）。②边缘过冲 +53–71%，发丝 / 下颌白边肉眼可见（亲审 crop_face.png）。③塑料脸探针三档都 ≈1：锐化不改变“塑料 / 娃娃脸”，那是生成本身的问题（脸型、大眼、磨皮、腮红），要从提示词 / LoRA / 参考下手。④探针在这 3 张上饱和（0.9994–0.9999），本身也没有区分度（与 K-REV-B02 一致）。
- 审片页：data/review_pages/realism_ab/index.html（本地打开）。

## 四、GPU 档方案（未跑）

见 data/ab/realism_ab/gpu_plan.json：3 镜 × G0 现行（复用生产图）/ G1 只改提示词（去锐度与助推词、后缀换具体光线）/ G2 = G1 + NiceGirls Asians 0.6 换 krea2，共 6 张约 3–4 分钟 GPU。16:31 PRODUCER 在出帧，按派单不跑。不走 frame-jobs 的原因：会写进生产 takes.json，可能被 auto_current 设成当前。

## 五、没找到 / 不能确认

1. Qwen 2.1 Turbo 上任何写实 LoRA 的独立实测（Canon / NiceGirls / Lenovo 作者都只在 base 上给参数）。
2. Restore LoRA 的 HF 原页（只读到 comfyui-wiki 转述）和许可证。
3. 专门针对 Qwen 2.1 手部的修法。
4. e-n-v-y “Qwen-Image-2.1-Fix” 的参数（模型卡只写“下载工作流 zip”，按规定不下载）。
