# IMGLAB 07 · 去塑料感 / AI 感与真人皮肤质感（Qwen-Image 2.1 Turbo · FLUX.3 Image Klein · MOSS-Image SFT）

> 2026-11-02，IMGLAB 研究子 agent。只读调研：没有下载、没有用 GPU、没有改其他文件。
> 起因：项目方原话“太塑料感，而且很 AI 感，细节也不够好，不够真人美女的细腻感，肤色、腿的肤色等细节”。
> 按 §G0 先读了已有成果，下文**不重复**：`docs/research/realism_tuning_20261101.md`（N1–N12、锐化三档 A/B、L-087）、`docs/research/quality_deep/03_image21_film_look.md`（Canon / Restore / filmstills / GrainScape / Dot Film / Fix v2 / Detail Daemon）、`knowledge/rules/research_realism.yaml`（K-WRT-X05 光线写方向）、`docs/qwen21/COMMUNITY_PHOTOREAL.md`（FLUX.2 klein / FLUX.3 Klein 官方参数与许可 O10–O18、C5–C29）。
> 置信度：**高** = 官方文档 / 作者原话 / 我们本地源码核对；**中** = 作者自测有数字，或多人一致；**低** = 单帖、厂商博客、推断。
> 现行约束（不在本文推翻）：L-087 徕卡 S★（USM 1.2/60/2、后缀、Q4）项目方已选定；D7 首帧颗粒 ≤σ2、颗粒只在成片加；Claude 不写剧本内容，下文的提示词片段只是**技术模板**，交写作方 / writer_knowledge 决定是否采用。

---

## 摘要（10 条）

1. **MOSS 官方原话点名了“写实 vs 细节”的开关**：“Turning off SLG will make the output image look very realistic, but it may also cause some details to collapse.”（USERGUIDE）。我们现行 SLG 22 恰好是“偏细节、偏 AI 精致”的一侧。→ MOSS 应 A/B 一档“SLG 降强度 / 提前结束 / 关闭”。**高**（官方原话；效果幅度未测）。
2. **cfg 1 下负面提示：ComfyUI 自带的 NAGuidance 对我们三个基座都不生效**。笔记本 ComfyUI（355cd6b，10-18）里 NAG 靠 `attn1_output_patch` 生效，只有 `ldm/flux/layers.py`（FLUX.1/2）、`ldm/krea2`、UNet 实现了这个钩子；`qwen_image21`、`flux3`、`moss_image` 都没有。**高**（本地源码核对；gpu33 的 8e3feba 未核）。→ Qwen Turbo / Klein 去塑料只能靠正向描述、LoRA、或换到 cfg>1 的档（Qwen Base / Turbo-LoRA 20 步 cfg 3；MOSS cfg 2.5 本来就吃负面）。
3. **int8 会削弱写实 LoRA**：Candid Amateur iPhone 作者原话 “Quantized int8 weights noticeably weaken the LoRA, so use bf16 if you can.” 我们 Qwen Turbo 是 int8，`krea2_film_texture` 0.5 的实际作用可能比标称小。**中低**（单作者，MOSS 上的观察）。
4. **“cinematic / professional” 这类词会把画面拉回棚拍 / 精修感**：同一作者（Qwen 2.1 版）“Skip words like "cinematic" or "professional", they pull the picture back to the studio look.” 我们的徕卡后缀里没有这两个词，但写作方正文是否有，值得 lint 一下。**低到中**（单作者，但与 realism_tuning N8/N9“助推词无益”方向一致）。
5. **精修种子不能和出图种子相同**：Qwen-Image 2.1 官方讨论 #61，“reference image was generated with seed 42 and then sent for editing with the same seed 42”，产生“Pervasive etched textures from noise patterns”，“Changing the second seed resolves this problem.” 任何低 denoise 二遍 / edit 精修都要换种子。**中**（单帖但机制清楚：同噪声与参考图强相关）。
6. **“先缩小再超分”是社区一致的去塑料精修路线**：Candid 作者 “downscale ×0.5 → SeedVR2 3B upscale … color correction lab”；r/StableDiffusion StableLlama “First downscale the image (yes, downscale!), e.g. by 1/2 or 1/4”，再加噪后 SeedVR2。SeedVR2 也有人嫌“super AIRBRUSHED”，所以必须和不精修 A/B。**中**（≥2 个独立来源）。
7. **MOSS 生态里真实照片训练的写实 LoRA 已有一批，许可干净**：UltraReal MOSS_V2（vizsumit，“reducing the soft & smooth AI look”，0.6–0.8）、[Moss] Realism Enhancer（“trained exclusively on high quality, 2048px plus realistic images”，从 1.0 起，er_sde/bong_tangent 更好）、Danrisi 的 Canon / NiceGirls / Lenovo MOSS 版。MOSS 底模 Apache-2.0，这些 LoRA 的 Civitai 权限都含 `Image`（出图可商用）。**中**（作者原话 + API 字段；没有独立横评）。
8. **FLUX.3 Klein 的写实生态仍很薄，而且社区反映脸弱**：HF 官方讨论 #22 “the faces are still mangled even at 8mp”“it's best over 2048”；#40 “Set the resolution selector to 2.1 megapixels”。写实相关只有一个 HF 社区“natural facial skin texture”编辑式 LoRA（0 下载）、MoreReal（禁止商用）、ausboss Restore LoRA（放大用）。**中低**。→ Klein 作为写实主力的证据不足，只适合做“第二遍 / 放大”的对手。
9. **腿部 / 膝盖 / 手肘的肤色不均没有任何模型专项资料**；能用的只有：皮肤学测量证明“redness (a*) … primarily due to different body locations”（Xiao 2017），以及通用写法“subtle uneven pigmentation, slight natural redness”。→ 只能在提示词里按部位点名，并用指标（a* 分区差）验收。**低**（写法未在三个基座上实测）。
10. **可量化指标**：整图 Laplacian 已证明被 USM 主导（realism_tuning §三）；建议改量“皮肤掩膜内、未锐化图上”的 ①小波最细层高频能量对真实照片参考集的 S_HF 分（arXiv 2602.13303 公式）、②GLCM 对比度、③a* 低频斑驳度与“膝 / 肘 − 大腿”a* 差、④镜面高光面积。**公开文献里没有可直接用的阈值**，必须用 30–50 张真实人像参考集自己标定（见第六节）。

---

## 一、塑料感 / AI 感：成因与对策（只列新证据）

| # | 成因 / 对策 | 原文（英文节选） | 来源 | 置信度 |
|---|---|---|---|---|
| P1 | MOSS 的 SLG 越强越“精致”，关掉更写实但细节会塌 | “Turning off SLG will make the output image look very realistic, but it may also cause some details to collapse.” / “We recommend uncond skip, with 22 as the recommended skip layer (0-indexed).” / “Layers 22, 24, and 26 can all help improve image quality.” / “Standard SLG: scale 3, 0.01-1.0.” | https://github.com/OpenMOSS/MOSS-Image/blob/main/USERGUIDE.md | 高 |
| P2 | MOSS 官方推荐 ≥50 步、cfg 3–6、shift 5、Euler；我们 25 步 cfg 2.5 是社区（DeBand 作者）的测试档，不是官方档 | “Best results are achieved with ≥ 50 steps.” / “Default 3.0 (recommended range: 3.0–6.0).” / shift “Default 5.0.” / “Euler is the recommended default.” | 同上；HF 模型卡 https://huggingface.co/OpenMOSS-Team/MOSS-Image-SFT （“Flow-matching Euler, 50 steps, CFG 3, shift 5”） | 高 |
| P3 | MOSS SFT 在平滑区（墙、雾、背景，含人像盲测）有竖条纹，会让皮肤 / 背景显“数码”；有 DeBand LoRA | “often draws faint, evenly spaced vertical color stripes across smooth areas like skies, fog, backdrops and walls”；测试设置“ER-SDE, CFG 3 … skip-layer guidance on layers 22 and 24”；条纹分 Off 2.04 → Quality 1.39（SSIM 86%） | https://huggingface.co/MATLOWAI/MOSS-Image-SFT-DeBand | 中（作者 12 图中位数） |
| P4 | 蒸馏 / 少步数让皮肤偏软、人显年轻 | MOSS：“On 8 steps, busy group scenes and fine skin come out softer and people can look a few years younger. 50 steps gives the most detail.” | https://civitai.com/models/3012015 （Candid Amateur iPhone，Artfat） | 中低（单作者，有对比图） |
| P5 | DMD2 加速 LoRA 强度过高会改脸并给皮肤加光泽 | “Keep DMD2 at 0.8 too. At 1.0 it changes the face more (eye colour, blush) and adds a little shine to the skin.” | 同上 | 中低 |
| P6 | int8 削弱 LoRA | “Quantized int8 weights noticeably weaken the LoRA, so use bf16 if you can.” | 同上 | 中低 |
| P7 | 助推词把画面拉回棚拍 / 精修 | “Skip words like "cinematic" or "professional", they pull the picture back to the studio look.” | 同上（Qwen 2.1 版说明） | 低到中 |
| P8 | 同种子做精修 → 蚀刻纹理 | “Pervasive etched textures from noise patterns” / “Changing the second seed resolves this problem.” | https://huggingface.co/Qwen/Qwen-Image-2.1/discussions/61 | 中 |
| P9 | Qwen 2.1 cfg 偏高或调度不对 → “noisy, muddy, overprocessed” | “a CFG that is too high or a different scheduler”；Turbo“needs custom sigmas” | https://huggingface.co/Qwen/Qwen-Image-2.1/discussions/56 | 低（与我们已用官方 sigma 一致，无新动作） |
| P10 | Turbo 合并版作者：静态 shift 3 用于“natural skin”，shift 5 发糊；4 步出重影 | “the same 6 sigmas with a static shift of 3”（推荐给 text / posters / natural skin，作者描述为更平滑的皮肤和更安静的微纹理）；避免 “static shift 5”（soft, smeared detail）与 “4 steps [1, 0.75, 0.5, 0.25]”（ghosted double contours） | https://huggingface.co/WaveCut/TurboImage2.1 | 低（第三方合并版；注意“更平滑”未必是我们要的方向） |
| P11 | FLUX.3 Klein 分辨率低于约 2MP 时脸和身体更容易坏 | “Set the resolution selector to 2.1 megapixels.”（#40）/ “it's best over 2048”、“the faces are still mangled even at 8mp”（#22） | https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/discussions/40 、/22 | 中低 |
| P12 | FLUX.3 Klein 不开 prompt upsampler 效果明显变弱；ComfyUI 模板默认开 | BFL：“Do not use it without its prompt upsampler.” / “a prompt sent as typed gives noticeably weaker results.”；ComfyUI：“To skip it, turn off `enable_prompt_upsampler`” | https://docs.bfl.ml/flux_3/flux3_image_klein.md 、https://docs.comfy.org/tutorials/flux/flux-3-klein | 高 |
| P13 | Klein 放大重绘时脸部阴影会被画成胡茬 | “Shadows on a face can come back as stubble.” / “Stubble on a woman's face? Say who is in the picture … like "a young woman".” | https://civitai.com/models/3007200 （ausboss FLUX 3 Klein Upscale） | 中（作者 ~40 种方案盲评） |
| P14 | SeedVR2 本身也可能“塑料” | “i hated how seedvr2 made skin look super AIRBRUSHED”；“it is unnaturally sharp and tends to smooth out skin detail too much.”；另一人 “3b_Q8 to be the best balance” | https://reddit.sentinel-team.org/posts/1rrk71v/snapshots/2026-03-16T19%3A47%3A17.577801Z | 中（多人，结论分歧） |
| P15 | 负面提示在 cfg 1 无效；ComfyUI 内置 NAG 对三基座无效（见摘要 2） | 节点说明 “enabling negative prompts on distilled/schnell models”；实现为 `m.set_model_attn1_output_patch(...)` | 本地 `D:\kimi-ns-storyboard\ComfyUI\comfy_extras\nodes_nag.py`；`grep attn1_output_patch comfy/ldm` 只命中 flux/krea2/modules | 高（本地，该版本） |

**怎么用这些成因**（推断，低）：项目方说的“塑料感”在我们链路里大概率是三层叠加 ——①Turbo 8 步本身偏软偏年轻（P4 同类现象）；②写实 LoRA 在 int8 上被削弱（P6）；③徕卡后缀 + USM 把“软而干净”的皮肤锐化成“硬而干净”（realism_tuning §三：USM 不改 p_plastic）。①②在生成端，③在后处理端（L-087 已定不动）。所以优先动生成端：换 / 加真实照片 LoRA、给 cfg>1 档负面、精修换种子、降采样再超分。

---

## 二、皮肤质感：提示词、负面替代、LoRA

### 2.1 证据

| # | 结论 | 原文 | 来源 | 置信度 |
|---|---|---|---|---|
| S1 | 官方（FLUX.2）：把提示写成“正在拍的真实照片”，明确要真实纹理 | “Prompt the model as if describing a real photograph: specify lens, lighting, framing, and texture details.” / 纹理例 “pores, wrinkles, fabric wear, imperfections” | https://docs.bfl.ml/guides/usecases_t2i_photorealistic.md | 高（只对 FLUX.2 声明） |
| S2 | Klein 3 没有负面，要把“不要的”改写成“有什么” | “Klein has no negative prompt, so say” … “a plain unlabeled bottle” | https://runware.ai/docs/models/bfl-flux-3-image-klein/guides/prompting | 中（第三方文档，但与 BFL 一致） |
| S3 | Klein 3 提示结构：取景在前 → 主体 → 背景 → 光线 → 末尾一句风格行（媒介、镜头、景深、色板） | “Framing goes first” / “A short style line at the end sets the medium, the lens, the depth of field and the palette.” | 同上 | 中 |
| S4 | 平光藏纹理；写光源与方向 | Candid 作者 “Name the light and its side ("a warm bedside lamp on the right")”；deAPI “Lighting descriptions have the single highest impact on output quality.” | civitai 3012015；https://deapi.ai/blog/prompting-flux-2-klein-what-works-what-doesnt-and-why | 中（已入 K-WRT-X05，这里只补证据） |
| S5 | 次表面散射 / 皮肤词 + cfg 2.3–2.8（只对有 cfg 的档） | “(subsurface scattering:1.5)”、cfg “2.3 to 2.8”、euler_a + beta/beta57 | https://reddit.sentinel-team.org/posts/1r1v8da/snapshots/2026-02-12T02%3A50%3A19.493258Z | 低（单评论，FLUX.2 Klein） |
| S6 | 写实 LoRA 有时会“压掉次表面反射”，皮肤变平 | Better Skin v2 帖：“mutes all the subsurface reflections.” | https://reddit.sentinel-team.org/posts/1tdkvb2/snapshots/2026-05-22T22%3A46%3A47.697486Z | 低 |
| S7 | 细绒毛要靠逆光 / 轮廓光才显 | vellus hair LoRA 作者建议 backlighting / rim lighting（WebSearch 摘要） | https://civarchive.com/models/80920 | 低 |
| S8 | 局部泛红与色素不均是“真照片”线索 | “subtle uneven pigmentation and slight natural redness”（示例提示） | https://claid.ai/blog/article/fix-ai-skin-texture | 低（商业博客） |
| S9 | 不同身体部位泛红差异显著（真人测量） | “Between different body locations, there are significant variations in redness (a*) … Individual differences in lightness and yellowness are mostly due to ethnicity, whereas differences in redness are primarily due to different body locations.” | Xiao et al. 2017, Skin Research and Technology，https://eprints.whiterose.ac.uk/id/eprint/100718/ | 中（只测额、颊、手背、前臂内侧，**没有膝 / 肘**） |
| S10 | MOSS 写实 LoRA 训练数据是真实高分辨率照片 | Realism Enhancer：“trained exclusively on high quality, 2048px plus realistic images … When the image is already realistic, it can improve skin and textures considerably.” UltraReal MOSS_V2：“reducing the soft & smooth AI look and adds more texture … especially well for close-ups and medium shots” | https://civitai.com/models/3023438 、https://civitai.com/models/2462105 | 中（作者原话） |
| S11 | 腿部 / 膝 / 肘专项提示或 LoRA | **未查到**（Civitai、HF、Reddit 镜像都没有） | — | — |

### 2.2 提示词模板（技术模板，交写作方；三基座都未实测，低）

规则：①写在人物描述之后、光线句之前；②**按镜头里实际露出的部位写**，不露腿就不写腿；③每句都绑一个光线落点（K-WRT-X05）；④不写 “flawless / perfect / cinematic / professional / 8k / masterpiece”。

- 脸（特写 / 近景）
  - EN：`natural skin with fine visible pores on the nose and cheeks, faint peach fuzz along the jawline catching the side light, a slightly warmer flush on the cheeks and nose tip, a soft satin sheen on the cheekbone rather than a glossy highlight`
  - 中：`皮肤自然，鼻翼和脸颊有细小可见的毛孔，下颌线的细软绒毛被侧光勾出，脸颊和鼻尖略微泛红偏暖，颧骨上是柔和的缎面光泽而不是油亮高光`
- 腿 / 手臂（中景 / 全身，露腿时）
  - EN：`bare legs with natural uneven skin tone, faint pinkish redness on the knees, slightly darker skin at the ankles, subtle visible texture on the shins under the window light, no glossy sheen`
  - 中：`裸露的双腿肤色自然不均，膝盖微微泛粉红，脚踝处肤色略深，窗光下小腿皮肤有细微可见的纹理，没有油亮反光`
  - 手肘 / 手：`slight redness on the elbows and knuckles` / `手肘和指关节略微泛红`
- 光（让纹理可见）：`soft window light from camera left grazing across the skin` / `柔和窗光从画面左侧斜掠过皮肤`；需要绒毛时加逆光：`thin rim light from behind outlining the fine hairs on her arms` / `身后一道细轮廓光勾出手臂上的细绒毛`
- 镜头 / 胶片：**一个镜头词 + 一个光或胶片词即可**，不要堆（03 §0.7、fliki 指南转述的 r/StableDiffusion 观察，低）。

### 2.3 cfg 1 下负面无效时的替代（按可行性排序）

1. **正向改写**（S2）：把“不要塑料皮肤”写成“有毛孔、哑光、局部泛红”（上节模板）。零成本，适用三基座。
2. **换到 cfg>1 的档跑负面**：
   - Qwen：Candid 作者的 Qwen 2.1 档是 “Qwen Image 2.1 bf16 … Turbo LoRA: Qwen-Image-2.1-Turbo-LoRA r128 at 0.95 · 20 steps · CFG 3 · euler · simple · 1024×1792”，即 **Base + Turbo LoRA + cfg 3**，负面可用；Lenovo 作者 Qwen2.1 “3-4 cfg … beta scheduler, res_2m / res_2s”。负面词：`plastic skin, waxy skin, airbrushed, retouched, doll, CGI, 3d render, overly smooth skin, oily shine`。**低到中**（作者档，与 Turbo 8 步 int8 不同）。
   - MOSS：现行 cfg 2.5 负面本来就生效；官方建议负面 “nsfw, worst quality, bad anatomy, watermark, jpeg artifact”，可追加上面的皮肤负面词。**中**。
   - Klein 3：Base 50 步 cfg 3.5 才有负面，速度不可接受，不建议。
3. **LoRA 当“负面”**：写实 LoRA（第三节）本质是把分布从“精修 / 生成图”推向“真实照片”，是 cfg 1 下最直接的替代。
4. **NAG**：ComfyUI 内置节点对 qwen_image21 / flux3 / moss_image 无钩子（P15），**当前不可用**；第三方 ComfyUI-NAG-Extended 只声明 Flux 2 Klein / Anima（https://github.com/BigStationW/ComfyUI-NAG-Extended ，低）。不建议投入。

---

## 三、写实 / 时尚人像 LoRA 与精修工作流（新增部分）

### 3.1 精修链（二次处理）证据

| # | 做法 | 原文 | 来源 | 置信度 |
|---|---|---|---|---|
| W1 | 降一半 → SeedVR2 3B → lab 校色 | MOSS 版：“optional last pass: downscale ×0.5 → SeedVR2 3B upscale to 2560 px, color correction lab. It adds the fine phone-sharp detail and leaves the picture as it is.” Qwen 2.1 版：“skin detail model 1x-ITF-SkinDiffDetail-Lite-v1, scale ×0.5, then SeedVR2 3B (seedvr2_ema_3b-Q4_K_M) to 2340×4096, colour correction lab” | civitai 3012015 | 中低 |
| W2 | 先降 1/2 或 1/4、加噪，再 SeedVR2，挑区域合成 | “First downscale the image (yes, downscale!), e.g. by 1/2 or 1/4.” | reddit 1r1v8da（同上） | 低到中 |
| W3 | SeedVR2 参数：lab 校色“highest fidelity”；输入噪声 0.1–0.3 治高分伪影；latent 噪声 0.05–0.15 可软化过量细节；7B 曾有 torch.compile 导致“overly plastic”的 bug（已修） | “recommended for highest fidelity to original”；input_noise_scale “0.1–0.3”；latent_noise_scale “0.05–0.15” | https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler | 高（README） |
| W4 | Klein 3 放大：小图先 SeedVR2 3B 再 Klein 分块（约 2MP 一块）重绘；生成图走 4x-UltraSharpV2 + 分块；Restore LoRA 让脸更接近原图（7/8 脸、8/8 颜色更近） | “SeedVR2 first, then FLUX 3 tiles, was my pick for small photos.” / “It is a redraw: fine detail is made up to fit” | civitai 3007200；https://huggingface.co/ausboss/FLUX-3-Image-Klein-Restore-LoRA | 中（作者 ~40 方案盲评，单种子） |
| W5 | 颗粒 | ComfyUI-Advanced-Photo-Grain 范围 0.01–1.0；PhotoRX 人像示例 intensity 0.3 | https://comfyai.run/custom_node/ComfyUI-Advanced-Photo-Grain | 低。**项目规则 D7：首帧颗粒 ≤σ2，颗粒只在成片加**——这里只作成片阶段参考 |
| W6 | 1x 皮肤细节模型 1x-ITF-SkinDiffDetail-Lite-v1 | “Adds plausible high frequency detail and removes subtle blur.” / “designed specifically for enhancing detail on skin diffuse textures of 3d characters.” | https://openmodeldb.info/models/1x-ITF-SkinDiffDetail-Lite-v1 | 低。**CC-BY-NC-SA-4.0 不可商用**；训练对象是 3D 角色贴图，可能反而加“CG 感” |
| W7 | 局部皮肤重绘（低 denoise 0.2–0.35） | **未查到**三基座上带数字的社区实测；已有的 Qwen 结论见 realism_tuning N4/N5（重绘会编毛孔、显老），03 §2.2 Restore LoRA | — | — |

### 3.2 LoRA（只列本文新增；Qwen 2.1 的 Canon / NiceGirls / filmstills / GrainScape / Restore / Fix v2 见 03 文档）

| 基座 | LoRA | 作者原话（强度 / 用法） | 依据 | 置信度 |
|---|---|---|---|---|
| MOSS | UltraReal MOSS_V2（vizsumit） | “Weight: 0.6-0.8” / “Moss_V2: Trained on SFW images, more human subjects in dataset … Prefer this for generating pics of human subjects.” 无触发词 | civitai 2462105 v3416438；12.9k 下载（全系列 51.7k） | 中 |
| MOSS | [Moss] Realism Enhancer（v1.0） | “I recommend starting at strength 1 … ER_SDE/Bong_Tangent worked even better in my tests.” | civitai 3023438；3.1k 下载、183 赞 | 中低 |
| MOSS | Canon UltraReal MOSS 版（Danrisi） | 作者只写了 Qwen2.1 “0.7”；MOSS 版无参数；触发 `c2n0n`；要求描述前景 / 背景焦外物体 | civitai 2783143 v3410539 | 低 |
| MOSS | NiceGirls UltraReal v2 MOSS 版 | MOSS 版无参数；同作者其它底模 “0.6-0.8”；Qwen 版有专门亚洲版，**MOSS 版未说明人种** | civitai 1862761 v3410486 | 低 |
| MOSS | Lenovo UltraReal MOSS 版 | 触发 `l3n0v0`；业余手机感，03 文档已否决同类（与时尚大片相反） | civitai 1662740 v3410543 | — 不推荐 |
| MOSS | Moss-image-beauty-lora（axiomofmind，HF） | “A portrait and beauty-photography LoRA … LoRA scale 1.0 (0.7 to 0.9 also tested)”，30 步 cfg 3，触发 `moss_beauty_style`；“datasets include only female subjects” | https://huggingface.co/axiomofmind/Moss-image-beauty-lora | 低（“polished … editorial beauty”，可能反而更精修，需 A/B） |
| MOSS | Kromoss 8-steps-dmd2-lora（lodestones，加速） | “Distilled from MOSS-Image-Base, then refined with a DMD2 GAN stage against real images.” 0.8；res_6s / bong_tangent，8 步 cfg 1 | civitai 3006599；https://huggingface.co/lodestones/Kromoss | 中低（速度档，不是写实档；P5 强度别上 1.0） |
| MOSS | DeBand 修复（MATLOWAI） | 主修复 L37-41 “1.0”；Quality+ 叠 L32-36 “1.0” | HF MATLOWAI/MOSS-Image-SFT-DeBand | 中 |
| FLUX.3 Klein | Flux3 natural facial skin texture LoRA（yang520333，HF） | “adds natural-looking facial skin texture, subtle pores, and fine microtexture”；78 对图训练，**编辑式**（“Describe the desired edit in natural language”）；5000 / 5600 步最常测；蒸馏版 “Try starting at 0.7 or higher”，保存的工作流 16 步 cfg 1 euler/simple、强度 1.0 | https://huggingface.co/yang520333/Flux3-image-klein-natural-facial-skin-texture-lora | 低（0 下载，作者自测 5 张对比） |
| FLUX.3 Klein | FLUX 3 Image Klein Restore LoRA（ausboss） | 放大重绘时让脸 / 颜色更接近原图；rank 32，step 1500 | HF ausboss/FLUX-3-Image-Klein-Restore-LoRA | 中 |
| FLUX.3 Klein | MoreReal F3K | 作者 “Do not use it for any commercial activities”；本质是 A2R（插画转照片）“Convert this image into a photograph” 0.6–0.9 | civitai 2904424 | 低；许可不合适 |
| FLUX.3 Klein-base | Piss Filter Remover | 去职业照常见的偏黄滤镜，“neutralize the colors … without unnecessarily altering the actual content” | civitai 3028743 | 低（可作色彩对照，非皮肤） |
| FLUX.2 klein | UltraReal KL9_V3 / V5_Pro 等 | 已在 COMMUNITY_PHOTOREAL C5；补一句作者对 V3：“applies very subtle skin texture which looks more realistic, without producing freckles and burnes” | civitai 2462105 | 中 |
| Qwen 2.1 | Candid Amateur iPhone Qwen 2.1 版（Artfat） | “cndamiph 0.9” + Turbo LoRA r128 0.95，20 步 cfg 3；“hands and skin look younger and less wrinkled than plain Qwen 2.1”；**业余手机感**，“dramatic studio light → flat everyday light” | civitai 3012015 v3441588 | 低；风格与“时尚大片”相反，只建议作为“去塑料”极端对照 |

---

## 四、时尚摄影词（镜头 / 光线 / 胶片）在这几个 DiT 上的证据

| # | 结论 | 原文 | 来源 | 置信度 |
|---|---|---|---|---|
| F1 | BFL（FLUX.2）：用摄影语言写镜头 / 光线 / 取景，要求真实纹理 | 见 S1 | docs.bfl.ml | 高（只对 FLUX.2） |
| F2 | Klein 3：镜头词放在末尾风格行，例 “85mm lens, shallow depth of field”、光线例 “Soft daylight from a large window on the left” | 见 S3 | runware Klein 3 指南 | 中 |
| F3 | Klein 3 / Klein 2：散文优于关键词串 | “FLUX.2 Klein rewards prose over keywords.” | deAPI | 低 |
| F4 | 胶片名（Kodak Portra 等）在 Qwen 2.1 / Klein 3 / MOSS 上的效果 | **未查到**可复现的对比测试（Civitai、HF、Reddit 镜像、厂商博客都没有） | — | — |
| F5 | 反例：“cinematic / professional” 把 Qwen 2.1 拉回棚拍 | 见 P7 | civitai 3012015 | 低到中 |
| F6 | 一个镜头词 + 一个光 / 胶片词，堆多了稀释 | 指南转述 r/StableDiffusion（Z-Image）：“Pick one camera phrase and one film or lighting phrase per prompt. Stacking more than two dilutes the effect.” | https://fliki.ai/blog/z-image-turbo-prompting-guide | 低（营销文转述，模型不同） |
| F7 | MOSS 官方：英文提示效果最好；没有任何摄影词指引 | “We recommend English, which has the most training data.” | MOSS USERGUIDE | 高（MOSS 走中文提示要注意） |
| F8 | Canon UltraReal 作者：焦外要靠描述前景 / 背景虚化物体触发 | 已在 03 §2.1 | — | — |

**落地建议**（推断，低）：时尚感优先靠“光的布置”（主光方向、柔光箱 / 窗光、轮廓光）而不是相机 / 胶片品牌名；胶片名做 A/B 前不进写作规则。MOSS 若作为基座，送进模型的提示要英文（我们写作方产出中文 img，需要翻译 / 改写步骤）。

---

## 五、各基座“写实候选配方”（全部未在我们机器上测；用于 A/B 设计）

公共约定：同镜同提示同身份参考；精修 / 第二遍**种子 = 出图种子 + 1**（P8）；指标在**未锐化**的图上量（第六节）；交付图仍走 L-087 的 S★ 后处理，不改。

### 5.1 Qwen-Image 2.1（现行主力）

| 方案 | 设置 | 依据 | 置信度 |
|---|---|---|---|
| Q-A 现行 + 只换 LoRA / 提示 | Turbo int8，官方 8 sigma，euler，cfg 1，texture_fix VAE，1152×2016 → 768×1344。LoRA 三选一对照：krea2_film_texture 0.5（现行）/ niceasians_qwen21 0.6–0.7 / canon_qwen21 0.5（+`c2n0n`、写焦外物）。int8 削弱 LoRA（P6），各加一档 +0.15。提示：删 “cinematic / professional / flawless”，按 2.2 节加部位皮肤句 | P6、P7、03 §2.1、realism_tuning N10 | 中低 |
| Q-B cfg 3 档（负面生效） | Qwen 2.1 Base（int8，3090 上）+ Qwen-Image-2.1-Turbo-LoRA r128 0.95，20 步，cfg 3，euler / simple，约 1024×1792；负面写皮肤负面词（2.3 节）；写实 LoRA 同 Q-A | Candid 作者 Qwen 2.1 档原样；Lenovo 作者 “3-4 cfg … beta … res_2s” 可作第二组 | 低到中（作者档；20 步 × cfg>1 双前向 ≈ 40 次模型调用，约为 Turbo 8 次的 5 倍） |
| Q-C 降采样再超分精修 | Q-A 出 1152×2016 → lanczos ×0.5 → SeedVR2 3B（fp16 或 Q8；不用 Q4）→ 短边 1536，color_correction=lab，input_noise 0 起、伪影时 0.1–0.3 → 缩回 768×1344 → S★ 后处理 | W1、W2、W3 | 中低；须和 Q-A 盲比（P14 有人嫌 SeedVR2 磨皮） |
| Q-D Restore 精修 | 已在 03 §2.2（Restore 1500/1250 0.75，denoise 0.30）；补：种子换新（P8） | 03、P8 | 中 |

### 5.2 FLUX.3 Image Klein（候选基座）

| 方案 | 设置 | 依据 | 置信度 |
|---|---|---|---|
| K-A 官方蒸馏档 | 蒸馏 int8_convrot，16 步，cfg 1，er_sde / simple（t2i 模板），**≥2.1MP**（例 1152×2048 或 1216×2160，16 的倍数），prompt upsampler **开**；或关掉并自己写完整 caption（取景 → 主体 → 背景 → 光线 → 风格行）。无负面 | P11、P12、S3、COMMUNITY_PHOTOREAL O14/O17 | 中 |
| K-B K-A + 皮肤编辑 LoRA 第二遍 | K-A 出图 → 以图为参考做编辑：yang520333 natural facial skin texture（step 5000）1.0 / 0.7 两档，16 步 cfg 1 euler/simple，指令用自然语言（例 “add natural facial skin texture and subtle pores, keep identity, expression, skin tone and lighting”） | 该 LoRA 模型卡 | 低 |
| K-C Klein 放大 | ausboss 工作流 “Generated picture” 模式（4x-UltraSharpV2 → Klein 分块 ~2MP）+ Restore LoRA；提示写 “a young woman” 防胡茬 | W4、P13 | 中；4x-UltraSharpV2 为 CC BY-NC-SA（非商用） |

Klein 作为写实主力的风险：社区脸部问题（#22 #37 #40）、BK1 实测 Klein 4B 身份过线率低（K-REN-B01，FLUX.2）。**建议只在 K-C（放大对手）里用。**

### 5.3 MOSS-Image SFT（候选基座）

| 方案 | 设置 | 依据 | 置信度 |
|---|---|---|---|
| M-A 现行 + DeBand | 25 步，cfg 2.5，er_sde，SLG layer 22（scale 3），+ DeBand 主修复 L37-41 1.0（LoraLoaderModelOnly）；英文提示；负面 = 官方 + 皮肤负面词 | P1、P3、F7 | 中 |
| M-B SLG 写实档 | 同 M-A，SLG 三档：scale 3（对照）/ scale 1.5 / 关闭（或 end_percent 0.5）。看“写实感 ↑ 与细节塌陷”的平衡 | P1 官方原话 | 中（方向官方，幅度要测） |
| M-C 写实 LoRA | M-A + UltraReal MOSS_V2 0.7，或 Realism Enhancer 1.0（同时试 er_sde/bong_tangent，需 RES4LYF 调度器）；身份参考 / 身份 LoRA 叠加时写实 LoRA 降到 0.5 | S10、W 表 | 中低 |
| M-D 50 步官方档 | Euler，50 步，cfg 3，shift 5，SLG 22（官方默认）+ M-C 最好的 LoRA。只作质量上限参照 | P2 | 高（官方档）/ 时间成本高 |
| （速度档，可选） | Kromoss 8-steps-dmd2 0.8，8 步 cfg 1，res_6s / bong_tangent；负面失效 | P5、civitai 3006599 | 低；DMD2 1.0 会加皮肤光泽 |

---

## 六、推荐 LoRA / 权重下载清单（未下载；sha256 为 Civitai API 返回值，HF 上的标“见仓库”）

“Civitai 权限”字段：`Image` = LoRA 作者允许出图商用；`RentCivit` = 只能在 Civitai 在线生成；`Sell` = 可卖模型。**底模许可优先**：Qwen-Image 2.1 = Qwen Research License（非商用研究与评估；Candid 作者与 WaveCut 卡均写明）；MOSS-Image = Apache-2.0；FLUX.3 Klein = FLUX Kommunity License（年营收 < 500 万美元的 Qualifying User 可商用输出，模型本身仅非商用，见 COMMUNITY_PHOTOREAL O16）。项目现在是非商用测试，下表照实标注。

| 优先 | 名称 / 文件 | 基座 | 来源 | 大小 | SHA256 | 许可 / 商用 |
|---|---|---|---|---|---|---|
| 1 | ultra_real_moss_v2.safetensors（UltraReal MOSS_V2） | MOSS | civitai 2462105 / v3416438 | 123.0 MB | B7574656D90D668BDE19C809812CEE5F342433533173E34416F6177CD736BA4E | Image/RentCivit/Rent/Sell/SellMerge；允许衍生；底模 Apache → 出图可商用 |
| 1 | Moss-RealismEnhancer-V1.safetensors | MOSS | civitai 3023438 / v3433342 | 69.2 MB | 4A187913365A862503A4297D26248D95B440636B68E60239E68FFC952B737E70 | 同上（全权限） |
| 1 | moss_image_sft_banding_fix_L37-41_bf16.safetensors（DeBand 主修复） | MOSS | HF MATLOWAI/MOSS-Image-SFT-DeBand | 1.13 GB | 01329abd340dd9cf55677381a11558fe5307c7fd648f1988b441172fbbd86fd5 | Apache-2.0 |
| 2 | canon_moss.safetensors | MOSS | civitai 2783143 / v3410539 | 61.5 MB | 49804D73F98DD110216EFBBB82D769ED4872F8BDD28BC2E256CA76BAE06628EF | 全权限；允许衍生 |
| 2 | nicegirls_v2_moss.safetensors | MOSS | civitai 1862761 / v3410486 | 61.5 MB | 544264014D2712BC812C78920AE8480C8BFA0826736309D6B428ECCE55783B5C | 全权限；**不允许衍生（不能合并再发布）** |
| 2 | niceasians_qwen21.safetensors（NiceGirls v1.0 Asians） | Qwen 2.1 | civitai 1862761 / v3349898（HF Danrisi/niceasians_qwen2.1） | 76.0 MB | 57D622238BE975469D51309BF4F6835FFA8EFD74557EDD2CD6C3FE26CD9841B2 | LoRA 全权限；底模非商用 → **整体非商用**（realism_tuning 说 gpu36 已有，需核对 sha） |
| 2 | canon_qwen21.safetensors | Qwen 2.1 | civitai 2783143 / v3352035 | 76.0 MB | 5D59914DFAF18DEE544862F5C41B333005FDEB11233F04CC44607BEAC08F9B1A | 同上，整体非商用 |
| 2 | qwen-image-2.1-restore.safetensors | Qwen 2.1 | civitai 2989697 / v3390033；HF ausboss | 152.1 MB | 65DE4F6C2468071D5AA6FFBD82C76BFEE7CC8AC28FE960E91BBCA4A58F43C08C | Civitai 只 RentCivit；qwen-research；非商用 |
| 2 | SeedVR2 3B（seedvr2_ema_3b fp16 或 Q8_0）+ seedvr2_ema_vae_fp16 | 通用 | HF Comfy-Org / numz 仓库 | 3B int8 约 3.46 GB；VAE 501 MB | 见仓库 | Apache-2.0（ByteDance Seed） |
| 3 | 8-steps-dmd2-lora.safetensors（Kromoss） | MOSS | HF lodestones/Kromoss | 未查到 | 见仓库 | Apache-2.0 |
| 3 | Flux3 natural facial skin texture（step 5000） | FLUX.3 Klein | HF yang520333/Flux3-image-klein-natural-facial-skin-texture-lora | 306.44 MiB / 个 | 仓库 SHA256SUMS.txt | FLUX Kommunity（作者明确“不意味 Apache”） |
| 3 | flux-3-image-klein-restore.safetensors | FLUX.3 Klein | HF ausboss/FLUX-3-Image-Klein-Restore-LoRA | 161 MB | 见仓库 | FLUX Kommunity |
| 3 | Moss-image-beauty-lora（MOSS-Image-Beauty-LoRA-ComfyUI.safetensors） | MOSS | HF axiomofmind | 70.93 MiB | 见仓库 | Apache-2.0；仅女性数据，偏精修，A/B 负对照 |
| 对照 | cndamiph_Candid_Amateur_iPhone_Qwen21_v1 / _MOSS_v1 | Qwen 2.1 / MOSS | civitai 3012015 | 304.1 MB / 138.4 MB | A1199D1725C1440E4F03F3DDA44B13530C38EF769594C602B92565BFB0985AF4 / D2161FCFD335D813E3D56DDFB2C9EF93E162EF32052A7FAC96615C241065EEFA | Image/RentCivit/Rent；Qwen 版作者写明不可商用 |
| 不推荐 | MoreReal F3K | FLUX.3 Klein | civitai 2904424 | 76.7 MB | 9779D7579553EB9783D968F8F389C52D56B1D900353DC2106DCC89C748294D30 | 作者禁止商用；A2R 用途 |
| 不推荐 | 1x-ITF-SkinDiffDetail-Lite-v1 | 通用超分 | openmodeldb | 19.2 MB | 未查到 | CC-BY-NC-SA-4.0；3D 贴图训练 |

---

## 七、可量化的皮肤质感指标（定义 + 阈值现状）

背景：`services/agent/ns_agent/gen_contract/metrics.py::face_texture` 已有 face_hf（|g − Gσ2| 均值）、face_lap、face_oil（V>235 且 S<60 占比）、p_plastic（CLIP 探针，已知饱和）。realism_tuning §三证明整图 / 交付图 Laplacian 被 USM 主导。下面是**新增或改造**建议，全部在**未锐化的 raw 图**（1152×2016 出图或缩回后、USM 之前）上量。

| 指标 | 定义 | 文献依据 | 阈值现状 |
|---|---|---|---|
| K1 skin_mask | 皮肤掩膜：脸用现有 bbox；腿 / 臂用 YCrCb 肤色阈值或人像解析模型（如 SAM3 已装则用），腐蚀 3px 去边缘 | — | — |
| K2 S_HF（皮肤） | 灰度皮肤块统一缩放到“脸高 256px”或“腿宽 128px”；sym4 小波一层分解，E_HF = ‖W₁‖²（三个细节子带）；对真实人像参考集求 μ = mean(log E_HF)；S_HF = 1 − clip(|log E_HF − μ| / |μ|, 0, 1)。≈1 正常，偏低 = 磨皮，偏高 = 过锐 / 编毛孔 | arXiv 2602.13303：“S_HF ≈ 1 indicates typical high-frequency energy, while S_HF ≈ 0 indicates a strong deficit or excess”；“the fitted slope is typically close to −3.5, yielding sym4” | 论文没有皮肤专用阈值（**未查到**）；需自标定 |
| K3 hf_lf_ratio | 同块的小波高频 / 低频能量比（各层），专看毛孔尺度可只用对角子带 | 皮肤评估专利（WebSearch 摘要：“ratio of high-frequency to low-frequency energy … roughness”；“diagonal detail bands … pore-scale”），USPTO 10702160 / 11154200 | 未查到数值 |
| K4 GLCM 对比度 | 皮肤块灰度量化到 32 级，距离 1、4 方向平均的 GLCM contrast | arXiv 2309.14756：“smooth and blurred generated textures are expected to result in lower GLCM Contrast values for generated images” | 未查到皮肤阈值 |
| K5 a* 斑驳度 | 皮肤掩膜转 CIELAB；对 a*、b* 做 σ = 掩膜宽 2% 的高斯低通，取掩膜内标准差 std(a*_lp)、std(b*_lp)。过低 = “一整块均匀肤色”（塑料） | getimg 指南“compresses this into one clean skin tone with a smooth gradient”（低）；Xiao 2017 部位差异（中） | 未查到单张图内的参考值；需自标定 |
| K6 部位泛红差 Δa* | 有腿 / 臂镜：膝盖（或手肘）区 a* 中位数 − 大腿（或上臂）区 a* 中位数；预期 > 0 | Xiao 2017：泛红主要随部位变化（只测了额 / 颊 / 手背 / 前臂内侧）；韩国女性面部 a* 均值约 9.8–12.6、组内 SD 1.4–1.7（WebSearch 摘要，Springer s41702-017-0002-7，原文未打开） | 膝 / 肘数值**未查到**；先把“> 0 且 < 6”作为待验证的工作假设（推断） |
| K7 镜面高光面积 | 皮肤掩膜内 L* > 掩膜 L* 的 p98 + 10 且 C*（彩度）< 10 的像素占比；分脸（鼻额）与腿两处报 | 厂商横评说 Qwen 2.1 “artificially oily sheen across the nose and forehead”（realism_tuning N7，低）；现有 face_oil 是同思路 | 未查到；自标定 |
| K8 微纹理重复 | 皮肤块 FFT 幅度谱非 DC 峰值 / 中位数（查 8px 网格与重复纹理） | 03 §2.8（sd.cpp #2041 转述“eight-pixel grid”，低）；N7 “micro-pattern repetition under zoom” | 未查到 |

**标定方法**（建议，推断）：收 30–50 张真实时尚 / 生活人像（同分辨率区间、含 20 张露腿全身），作者授权或 CC0 来源；与现行出图各算 K2–K8，取真实集的 [p10, p90] 作为初始通过区间，再拿项目方盲选结果（“更像真人”的那张）回查 AUC，AUC < 0.65 的指标不进契约（与 11-01 lap_full AUC 0.41 作废同一标准）。

---

## 八、没找到 / 不能确认

1. 三个基座上任何“腿部 / 膝盖 / 手肘肤色”专项 LoRA 或带对比图的提示写法。
2. Kodak Portra 等胶片名、相机机身名在 Qwen 2.1 / Klein 3 / MOSS 上的可复现对比。
3. 皮肤质感指标的公开阈值（S_HF、GLCM、a* 斑驳、高光面积都只有方法，没有皮肤专用数值）；膝 / 肘 a* 的真人测量值。
4. NAG 在 gpu33 ComfyUI（8e3feba，10-28）里是否已给 qwen_image21 / flux3 / moss_image 加了钩子（只核了笔记本 355cd6b）。
5. MOSS 写实 LoRA（UltraReal / Realism Enhancer / Canon / NiceGirls）是在 Base 还是 SFT 上训练、在 SFT + SLG 22 上的效果：作者没写，没人测。
6. Qwen 2.1 Turbo int8 上写实 LoRA 的实际削弱幅度（只有 MOSS 上的一句作者观察）。
7. 低 denoise（0.2–0.35）皮肤局部重绘在这三个基座上的社区数字。
8. Civitai 评论区内容（API 401 / 页面 403），所以“中”最多来自作者原话 + 下载 / 点赞数。

## 来源汇总

- 官方：MOSS USERGUIDE https://github.com/OpenMOSS/MOSS-Image/blob/main/USERGUIDE.md ；MOSS-Image-SFT 模型卡 https://huggingface.co/OpenMOSS-Team/MOSS-Image-SFT ；BFL Klein 3 https://docs.bfl.ml/flux_3/flux3_image_klein.md ；BFL 写实指南 https://docs.bfl.ml/guides/usecases_t2i_photorealistic.md ；ComfyUI Klein 3 https://docs.comfy.org/tutorials/flux/flux-3-klein ；ComfyUI NAGuidance https://docs.comfy.org/built-in-nodes/NAGuidance.md
- HF 讨论：Qwen-Image-2.1 #56 #61 https://huggingface.co/Qwen/Qwen-Image-2.1/discussions ；flux-3-image-klein-comfy #22 #25 #37 #40 #41 https://huggingface.co/black-forest-labs/flux-3-image-klein-comfy/discussions
- HF 模型：MATLOWAI/MOSS-Image-SFT-DeBand、WaveCut/TurboImage2.1、axiomofmind/Moss-image-beauty-lora、yang520333/Flux3-image-klein-natural-facial-skin-texture-lora、darask0/MOSS-Image_4-step_adapter_lora、ausboss/FLUX-3-Image-Klein-Restore-LoRA、lodestones/Kromoss
- Civitai（API `/api/v1/models`、`/api/v1/model-versions`，2026-11-02 抓取）：3012015、2462105、3023438、3007815、2783143、1862761、1662740、2904424、3006241、3006599、3028743、2134096、2989697、2957332、3007200、3006443
- Reddit 镜像：1tdkvb2（Better Skin v2）、1rv6juw（Klein Consistency）、1r1v8da（skin texture）、1rrk71v（SeedVR2 plastic）、1rm8p5o
- 工具：https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler ；https://openmodeldb.info/models/1x-ITF-SkinDiffDetail-Lite-v1 ；https://github.com/BigStationW/ComfyUI-NAG-Extended
- 论文 / 皮肤学：arXiv 2602.13303（Spectral Collapse in Diffusion Inversion）；arXiv 2309.14756；Xiao et al. 2017 https://eprints.whiterose.ac.uk/id/eprint/100718/ ；Springer s41702-017-0002-7（摘要转述）
- 低置信博客：https://deapi.ai/blog/prompting-flux-2-klein-what-works-what-doesnt-and-why 、https://runware.ai/docs/models/bfl-flux-3-image-klein/guides/prompting 、https://claid.ai/blog/article/fix-ai-skin-texture 、https://fliki.ai/blog/z-image-turbo-prompting-guide
- 本地：`D:\kimi-ns-storyboard\ComfyUI\comfy_extras\nodes_nag.py`、`comfy\ldm\{flux,flux3,qwen_image21,moss_image,krea2}`；`services/agent/ns_agent/gen_contract/metrics.py`
