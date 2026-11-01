# Civitai 学习笔记（CIVIT）

> 负责人：CIVIT。日期：2026-10-31。范围：MiniMax H3、Qwen-Image 2.1/Edit、短剧后期通用环节、Wan/LTX 可迁移经验。
> 只记系统与参数，不涉及剧本内容。未提交渲染、未改 config、未登录、未付费。

## 0. 结论先行

1. **Civitai 匿名能拿到的东西比预期少，但示例视频里藏着完整工作流。** 匿名 API 下载约 70% 的工作流/LoRA 文件会被重定向到登录页（`reason=download-auth`）；`/api/v1/images` 匿名返回的 `meta` 全是 null。但示例媒体原件（`image.civitai.com/.../original=true/...mp4|png`）保留了 ComfyUI 元数据：mp4 的 `udta/meta/mdta` 里有 `workflow`（UI 格式）和 `prompt`（API 格式）两份 JSON。只取文件头 3MB 和尾部 4MB 就能抽到，不必下载整片。
2. **社区 H3 参数共识**（309 份 H3 工作流 JSON 的统计，见 §3）：sigma shift 12/3 占绝大多数（6/3 只配 768p lightx2v turbo；10/3 用于 0.5MP 底）；调度器 simple 为主、beta/beta57 次之；采样器 euler 与 res_multistep 两强，er_sde 第三；步数 20（基模）/ 8 / 6 / 4（turbo）；两段式第二段 ManualSigmas `0.9035, 0.8000, 0.6316, 0.3158, 0` 或 `0.9035, 0.6316, 0.3158, 0` 出现最多，与我们 h3_comfy_expert 的结论一致。
3. **身份一致最有价值的新做法**来自 LongTake（2942000）：换人时把**脸部特写作为第二张参考图**（作者测得相似度 +0.04~0.05），并把原视频里人物的脸**模糊但保留嘴部**（`blur_keep_mouth`），让身份只来自参考图，同时保住口型（相似度 0.41→0.52，原人物渗漏 0.41→0.22）；提示词里**不要写表情**，否则可能让换人失效。
4. **长镜头接缝**：2852849 用原生 *Masked AV Latent Continuation*，把上一段尾部的视频+音频 latent 直接拷入下一段并保护不去噪，作者说明显减少段间亮度/色彩跳变。Endless（2909076）在 latent 级拼接，避免“解码再编码”。
5. **本轮下载到 gpu36 的 LoRA 共 16 个，2.9GB**（sha256 全部与 Civitai 一致），另有 24 个对口 LoRA 需要登录，已跳过并记录线索（§6）。gpu33 上已有 11 个 Civitai 同款（hash 对上），清单见 §2。

## 1. 方法与落盘

- 工具：`tools/workflow_lib/civitai_fetch.py`（只做 HTTP GET，不执行下载内容）
  - `catalog`：按预设查询（基模过滤 `MiniMax H3` / `Qwen 2.1` + 主题关键词）分页，写 `_catalog/models.json`（1326 个模型）
  - `workflows`：Workflows 类型每个模型取最多 3 个版本，zip 只解压 json/png/txt/md
  - `sidefiles`：LoRA/模型页附带的示例工作流（json/zip 附件）
  - `images`：每个模型首版本的示例媒体列表（`_catalog/images/<id>.json`）
  - `media`：从示例 mp4/png 原件抽内嵌工作流，存为 `media<imageId>__ui_<hash>.json`；同一张图有 UI 版时删掉 API 版（WFLIB 要求，避免参数分布重复计数）
- 落盘：`D:\NS-Final Studio\data\ab\owner_workflows\civitai\<modelId>__<名字>\`，每个目录有 `meta.json`（链接、作者、版本、下载数、评分、许可、触发词、描述、下载日志）。
- 解析：复用 WFLIB 的 `tools/workflow_lib/parse.py`，结果并入 `data/ab/owner_workflows/_meta/parsed.json` 和 `docs/ep02_iter/workflow_library.md`。
- 访问情况：工作流 663 个：134 个匿名直接下到文件，517 个需登录（其中 245 个模型从示例媒体补回了内嵌工作流，共 523 份 UI 版 + 52 份 API 版）。LoRA（H3+Qwen2.1 前 300 个）：82 个匿名可下，218 个需登录。
- 许可列含义：Civitai 的 `allowCommercialUse` 里有 `Image` 才表示“生成结果可商用”。没有 `Image` 的一律标“**产出禁商用/未授权**”，上线前需人工确认（有些是 HF 原版的转载，原版许可另算）。

## 2. LoRA 清单（按问题）

本地一列的含义：“gpu36 `loras/civitai/…`”= 本轮已下（路径 `/root/work/fredw/comfy/ComfyUI/models/loras/civitai/`）；“已在 gpu33”= 那台机器上已有 hash 相同的文件；“需登录，跳过”= 匿名下载被重定向到登录页。

| 问题 | 模型 (id) | 基模 | 用途 / 推荐参数 | 触发词 | 下载/赞 | 许可 | 本地 |
|---|---|---|---|---|---|---|---|
| 迭代速度 | [Minimax H3 Turbo LoRas](https://civitai.com/models/2837571) (2837571) | MiniMax H3 | turbo 合集：DMAD 4step（6-8 步 er_sde/euler simple，shift 12/2）；taomate fl2va 3step（4-6 步，强度 0.75）；ref2v_turbo_8step（8-12 步 er_sde/res_multistep）；通用 shift 12/3 | 无 | 52091/1287 | 产出可商用 | gpu36 `loras/civitai/minimax_h3_taomate_3step_lora_avg_rank_19_bf16.safetensors` |
| 迭代速度 | [Minimax H3 Turbo / REF2VA / FL2VA / Hybrid](https://civitai.com/models/2929860) (2929860) | MiniMax H3 | Darksidewalker 4 步混合：DMAD+Hyperflow R256（作者：Hyperflow 能稳运动、压"烤焦"感），Euler+simple/beta，shift 12/3 | 无 | 11193/395 | 产出可商用 | 需登录，跳过 |
| 迭代速度 | [ComfyUI FastVideo FastH3 4-step LoRa (unofficial](https://civitai.com/models/2898443) (2898443) | MiniMax H3 | FastH3 4 步（FastVideo 官方 PEFT→Comfy 转换），1GB | 无 | 899/35 | **产出禁商用/未授权** | gpu36 `loras/civitai/FastH3_comfyui.safetensors` |
| 迭代速度 | [Minimax H3 HardGravy 6-step Turbo Merge](https://civitai.com/models/2923611) (2923611) | MiniMax H3 | HardGravy 6 步 turbo（lightx2v+larryvrh+JonXL 写实合并），附 h3_fast.json | 无 | 1770/80 | 产出可商用 | gpu36 `loras/civitai/h3_hard_gravy_6stepturbo_r64_v1.0.safetensors` |
| 卡顿/慢 | [BUNNY General Motion Continuity Repair](https://civitai.com/models/2890788) (2890788) | MiniMax H3 | BUNNY Motion Repair V2：通用动态修复（跑跳/打斗/互动），作者配 SelfLift 1080P 工作流 | 无 | 9177/503 | 产出可商用 | 已在 gpu33（Motion_Repair_V2） |
| 卡顿/慢 | [Better Human Motion Minimax H3](https://civitai.com/models/2734359) (2734359) | MiniMax H3 | Better Human Motion：0.4-0.8，720x1280，15-30 步；句子要短防"提示词渗漏" | 无 | 16426/682 | 产出可商用 | 需登录，跳过 |
| 卡顿/慢 | [Motion-Speed-MMH3-SLIDER](https://civitai.com/models/2985458) (2985458) | MiniMax H3 | 运动/动作速度滑杆：默认 ±4（±1~2 微调，<4 基本不改原内容），负值=自然慢动作 | 无 | 4621/247 | 产出可商用 | 需登录，跳过 |
| 卡顿/慢 | [SSS Rank Minimax H3 (Smooth, Slow, Sync)](https://civitai.com/models/2985070) (2985070) | MiniMax H3 | SSS 平滑+慢速+同步：会把无音频引导的声音去掉；在站上 ref2v 偏卡通 | 无 | 2153/158 | 产出可商用 | 需登录，跳过 |
| 多腿鬼影 | [Minimax H3: t2va (T2V) – Polyhedron: Perfect Eye](https://civitai.com/models/2899220) (2899220) | MiniMax H3 | Polyhedron 眼/皮肤/手（t2va），作者说可能过拟合，低权重 | perfe8ct, perfect hands | 3882/141 | **产出禁商用/未授权** | 需登录，跳过 |
| 多腿鬼影 | [MMH3 - Locked Stabilization (Camera locked to ta](https://civitai.com/models/2975645) (2975645) | MiniMax H3 | Locked Stabilization：0.8 轻/1.0 满，触发 "the camera is centred on <subject>" | the camera is centred on, lockstab | 2423/145 | 产出可商用 | gpu36 `loras/civitai/MMH3-LOCKSTAB-MORE.safetensors` |
| 身份一致 | [FaceSwap - MiniMax REF2VA](https://civitai.com/models/2940916) (2940916) | MiniMax H3 | FaceSwap REF2VA：强度 1，触发 Faceswap；附原生工作流 zip（CRT-Nodes 2.19） | Faceswap | 3205/141 | 产出可商用 | 需登录，跳过 |
| 身份一致 | [[MiniMax H3] AsianMix Lora](https://civitai.com/models/2961302) (2961302) | MiniMax H3 | AsianMix v1.4（东亚女性外观倾向） | asian woman | 954/65 | 产出可商用 | 需登录，跳过 |
| 身份一致 | [Qwen Image 2.1 Consistency LoRA](https://civitai.com/models/2969143) (2969143) | Qwen 2.1 | Qwen2.1 Consistency：编辑时画面不漂移/不放大（step1500，HF 有 step2000 更紧） | 无 | 7169/275 | **产出禁商用/未授权** | gpu36 `loras/civitai/qwen-image-2.1-consistency.safetensors` |
| 身份一致 | [Qwen Image 2.1 Outfit Swap Consistency LoRA](https://civitai.com/models/2983159) (2983159) | Qwen 2.1 | Qwen2.1 Outfit Swap Consistency：换装时人物不位移、脸不变 | 无 | 3827/176 | **产出禁商用/未授权** | 已在 gpu33（outfit-swap） |
| 身份一致 | [Character Sheet Edit LoRA (Qwen Image 2.1) - one](https://civitai.com/models/2995608) (2995608) | Qwen 2.1 | 单图→3x2 角色设定（角度模式最强），附工作流 zip | 无 | 1880/90 | **产出禁商用/未授权** | gpu36 `loras/civitai/character-sheet-qwen-image-2.1-edit-lora-e9.safetensors` |
| 身份一致 | [QMA - Qwen Image 2.1 Multi Camera Angle LoRA](https://civitai.com/models/2998617) (2998617) | Qwen 2.1 | QMA 多机位：`<qma> {azimuth} {elevation} {distance}` | <qma> {azimuth} {elevation} {distance}, <qma> righ | 958/52 | **产出禁商用/未授权** | 需登录，跳过 |
| 身份一致 | [AnyAngle - Arbitrary Camera Angles for Qwen Imag](https://civitai.com/models/2970214) (2970214) | Qwen 2.1 | AnyAngle：Change the camera angle from <image2> to <image1> | Change the camera angle from <image2> to <image1> | 1302/86 | 产出可商用 | 已在 gpu33（AnyAngle） |
| 身份一致 | [VNCCS PoseStudio Qwen Image 2.1](https://civitai.com/models/2957080) (2957080) | Qwen 2.1 | VNCCS PoseStudio v2：3D 摆姿/机位/灯光参考（需 VNCCS 节点），附 json | 无 | 2706/226 | 产出可商用 | 需登录，跳过 |
| 脸部细节 | [MiniMaxH3_Enhancers](https://civitai.com/models/3025511) (3025511) | MiniMax H3 | Enhancers：去糊、脸部细节、背景清洁（epoch10 强/epoch5 柔） | 无 | 1676/97 | 产出可商用 | 需登录，跳过 |
| 脸部细节 | [Sharper Video](https://civitai.com/models/3018990) (3018990) | MiniMax H3 | Sharper Video：1.5（1.0-2.0）+ 提示 "Everything becomes sharper, with clearer details and crisper edges." | 无 | 780/32 | 产出可商用 | 需登录，跳过 |
| 脸部细节 | [Restore Enhance Improve](https://civitai.com/models/2989135) (2989135) | MiniMax H3 | Restore Enhance Improve：强度 1.0，视频接 ref2va 视频参考，潜空间比例要与输入一致；也能延长 | Restore this video to high visual quality by recov | 2317/169 | 产出可商用 | 需登录，跳过 |
| 脸部细节 | [[MMH3] Detail Slider](https://civitai.com/models/2929154) (2929154) | MiniMax H3 | Detail Slider：-2~2，rank1 跳过前几层，不改构图 | 无 | 4017/223 | 产出可商用 | 需登录，跳过 |
| 口型 | [Natural Face & Speech Minimax H3](https://civitai.com/models/2925394) (2925394) | MiniMax H3 | Natural Face & Speech v2：0.6-0.8，固定 seed+统一开头词防声音漂移；提示 "she is speaking into a mic ... saying: '...'" | 无 | 4394/182 | 产出可商用 | 需登录，跳过 |
| 口型 | [Kokoro Female Voices LoRAs (Minimax H3)](https://civitai.com/models/2933702) (2933702) | MiniMax H3 | Kokoro 女声音频 LoRA：0.5-0.7，过高会盖掉其他声音并伤口型 | 无 | 1449/42 | 产出可商用 | 可匿名下，未下 |
| 泛红/调色 | [Vibrant Slider](https://civitai.com/models/2775079) (2775079) | MiniMax H3 | Vibrant Slider：负值去饱和（再低变灰） | 无 | 2068/140 | 产出可商用 | 需登录，跳过 |
| 泛红/调色 | [[MMH3] Exposure Slider](https://civitai.com/models/2946844) (2946844) | MiniMax H3 | Exposure Slider：-6~+6，只动最后两层 | 无 | 1595/118 | 产出可商用 | gpu36 `loras/civitai/MMH3-ExposureSlider-V1.safetensors` |
| 泛红/调色 | [[MMH3] DayNight Slider](https://civitai.com/models/2949040) (2949040) | MiniMax H3 | DayNight Slider：冷夜↔暖日光方向，需提示词先描述场景 | 无 | 1226/87 | 产出可商用 | gpu36 `loras/civitai/MMH3-DayNightSlider-V1.safetensors` |
| 泛红/调色 | [CinemaGrade - MiniMax H3 Style LoRA](https://civitai.com/models/2927223) (2927223) | MiniMax H3 | CinemaGrade：触发 cinemagradestyle 放句首，1.0；ep35 柔/ep50 强 | cinemagradestyle | 1593/78 | **产出禁商用/未授权** | 需登录，跳过 |
| 泛红/调色 | [RAW style photo](https://civitai.com/models/1751076) (1751076) | Qwen 2.1 | Qwen RAW photo：触发 "Change to RAW photo"，中性色光；T2I 0.3 起 | Change to RAW photo | 2240/106 | 产出可商用 | gpu36 `loras/civitai/change_to_raw_photo_v3_qi21.safetensors` |
| 泛红/调色 | [zjourney - Fantasy Realism Refiner Ideogram 4/Kr](https://civitai.com/models/2686999) (2686999) | Qwen 2.1 | zjourney：0.5-0.6，配 turbo 去烤焦/高对比/黄偏色 | 无 | 2981/151 | **产出禁商用/未授权** | gpu36 `loras/civitai/zjourneyqwen.safetensors` |
| 质感 | [[MMH3] Realism Slider](https://civitai.com/models/3014078) (3014078) | MiniMax H3 | Realism Slider：+1~1.5（0.25-2），去油光塑料皮，保留毛孔；作者建议不叠 turbo 测 | 无 | 5393/298 | 产出可商用 | gpu36 `loras/civitai/MMH3-RealismSlider-V1.safetensors` |
| 质感 | [fal/MiniMax-H3-Realism-People-LoRA](https://civitai.com/models/2994195) (2994195) | MiniMax H3 | fal Realism-People（HF 原版）t2v/i2v/r2v | 无 | 1159/52 | **产出禁商用/未授权** | 已在 gpu33（realism-people） |
| 质感 | [Minimax H3 Cinematic V2](https://civitai.com/models/2890588) (2890588) | MiniMax H3 | 电影感 V2：0.85；V1 正式版 0.7，高动态 0.5（官方说明：去塑料感/过锐/硬光） | 无 | 7425/289 | **产出禁商用/未授权** | 需登录，跳过 |
| 质感 | [Amateur Hour](https://civitai.com/models/2530917) (2530917) | MiniMax H3 | Amateur Hour：降对比、去光泽、加一点雾感 | 无 | 8348/413 | 产出可商用 | 需登录，跳过 |
| 质感 | [InstaPic : Ultrareal The Authentic Social Media ](https://civitai.com/models/2168120) (2168120) | MiniMax H3 | InstaPic M3 V2：社媒随手拍真实感 | 无 | 25622/789 | 产出可商用 | gpu36 `loras/civitai/Instapic_M3_V2.safetensors` |
| 质感 | [PureLens Realism](https://civitai.com/models/2728005) (2728005) | Qwen 2.1 | PureLens（Qwen2.1）：RAW 照片训练，毛孔纹理；背景偶尔乱 | p3r4l4ns | 11438/474 | 产出可商用 | 需登录，跳过 |
| 质感 | [Lenovo UltraReal](https://civitai.com/models/1662740) (1662740) | Qwen 2.1 | Lenovo UltraReal（Qwen2.1）：cfg 3-4（糊了降到 1），beta，res_2s/res_2m/res_multistep | 无 | 212676/5725 | 产出可商用 | gpu36 `loras/civitai/lenovo_qwen21.safetensors` |
| 质感 | [GrainScape UltraReal](https://civitai.com/models/1332651) (1332651) | Qwen 2.1 | GrainScape（Qwen2.1）：0.7 | 无 | 26108/1615 | 产出可商用 | gpu36 `loras/civitai/grainscape_qwen21.safetensors` |
| 质感 | [Canon UltraReal](https://civitai.com/models/2783143) (2783143) | Qwen 2.1 | Canon UltraReal（Qwen2.1）：0.7，触发 c2n0n | c2n0n | 12141/536 | 产出可商用 | 已在 gpu33（canon_qwen21） |
| 质感 | [Qwen-Image 2.1 — Krea2 35mm Film Texture & Reali](https://civitai.com/models/3010645) (3010645) | Qwen 2.1 | Krea2 35mm Film Texture（Qwen2.1） | 无 | 1161/44 | 产出可商用 | 已在 gpu33（krea2_film_texture） |
| 质感 | [Qwen Image 2.1 Fix v2.0](https://civitai.com/models/2957332) (2957332) | Qwen 2.1 | Qwen2.1 Fix v2.0：细节修复；作者配 DPM++2M Sharp 采样器（envy-ai 节点） | 无 | 3837/131 | 产出可商用 | 需登录，跳过 |
| 质感 | [Qwen Image 2.1 Restore LoRA](https://civitai.com/models/2989697) (2989697) | Qwen 2.1 | Qwen2.1 Restore：柔化 2.1 自带放大的过锐，少编造 | 无 | 5158/228 | **产出禁商用/未授权** | 已在 gpu33（qwen restore） |
| 长镜头 | [camera_motion_h3](https://civitai.com/models/2914784) (2914784) | MiniMax H3 | camera_motion_h3：触发 "camera motion" 必须放句首 | 无 | 1608/83 | 产出可商用 | 已在 gpu33（camera_motion_h3） |
| 长镜头 | [Shaky, handheld camera](https://civitai.com/models/2592748) (2592748) | MiniMax H3 | Shaky handheld：加手持抖动（静/动机位都可） | 无 | 1555/88 | 产出可商用 | 需登录，跳过 |
| 竖屏 | [Qwen Image 2.1 Outpaint LoRA — Extend Any Side](https://civitai.com/models/2967375) (2967375) | Qwen 2.1 | Qwen2.1 Outpaint v2：灰边填充，任意边扩展，1-2MP；可把横图扩成 9:16 | Outpaint the image: replace the solid gray areas w | 3558/170 | **产出禁商用/未授权** | gpu36 `loras/civitai/qwen-image-2.1-outpaint-v2.safetensors` |

### 2.1 本轮下载到 gpu36 的文件与 sha256

总量 2.9GB（预算 20GB），单个最大 1.0GB。全部 `.safetensors`，Civitai 页面的 pickle/virus 扫描均为 Success。gpu33 需要时从 gpu36 内网复制。

| 文件 | sha256 |
|---|---|
| `MMH3-RealismSlider-V1.safetensors` | `96a7bed24f7aa1351c6066666495ee64046faf130f53224f4e4a44b3b49b038d` |
| `MMH3-ExposureSlider-V1.safetensors` | `530334bb668fc222a179d55097632ef398288e497728518b096fb69e38c8d9f7` |
| `MMH3-LOCKSTAB-MORE.safetensors` | `d77e1746407c8f00dfcf70755318db992711a2d4cc10ea7fd76904edded31f53` |
| `Instapic_M3_V2.safetensors` | `f4fdbf0dab08a233f1425e381b20d386d666cbf7a61668a2e688294384cb5cfd` |
| `FastH3_comfyui.safetensors` | `1cc39a5fdb172e0641232452800ce7af0c980336705abc296f68cf09abb5aceb` |
| `minimax_h3_taomate_3step_lora_avg_rank_19_bf16.safetensors` | `de9663d974a884b477556748239c6f28239f7ca1825be270f98f023ff5dab6a7` |
| `qwen-image-2.1-consistency.safetensors` | `4f44ada1be2189cc23b3d010f9603543403f48454e2f76842a3d30109b20bd63` |
| `character-sheet-qwen-image-2.1-edit-lora-e9.safetensors` | `e180b4d7a108585859eb5f15a467821eb2b8fdb71a1798943bab376c23391d51` |
| `lenovo_qwen21.safetensors` | `7f1e95c3ec1e9c7cea197f7b6f80f601af8e6b479f6ead78ab16df542f447c0e` |
| `change_to_raw_photo_v3_qi21.safetensors` | `b268f11347c54091de5ca7ab2d66bc2538bb2c87adfd1445c8dfc56550aa282f` |
| `qwen-image-2.1-outpaint-v2.safetensors` | `3611a5ccae5f790405eeacf1dfb2c89285c1e4f2987b9abc88cd0161a60eca28` |
| `zjourneyqwen.safetensors` | `1db31a4ff282db67bc74b85feb35c85098b9b049750f80041ec319a77713c8ff` |
| `niceasians_qwen21.safetensors` | `57d622238be975469d51309bf4f6835ffa8efd74557edd2cd6c3fe26cd9841b2` |
| `grainscape_qwen21.safetensors` | `b04b226561c5c3cc65a8e5f79a63a831ffb068d8bd3f156271650cb46e1dc2bf` |
| `MMH3-DayNightSlider-V1.safetensors` | `813c9c30b5a935cb77c739cae5838537ba92bd1e0d349b9b4c92fc2150c1adf2` |
| `h3_hard_gravy_6stepturbo_r64_v1.0.safetensors` | `c599a27e970583a970316ed8050bd274e245bf182c479aea3ec85333aaa98b15` |

用途（下载前已定）：Realism/Exposure/DayNight 三个滑杆 = 质感与泛红/光线；LOCKSTAB = 跟拍稳定；Instapic = 写实对照；FastH3 / taomate 3step / HardGravy 6step = 预览加速 A/B；Qwen2.1 的 consistency / character-sheet / outpaint = 角色设定、编辑不漂移、竖屏扩图；lenovo / raw_photo / zjourney / grainscape / niceasians = 参考图写实与去偏色。

## 3. 社区参数分布（从工作流 JSON 统计）

样本：civitai/ 下解析出 840 份工作流 JSON（含示例媒体抽出的 523 份 UI 版、52 份只有 API 版），按节点类型分为 H3 309 份（155 个模型）、Qwen 274 份（122 个）、Wan 30 份、其他 227 份。下面只统计**激活**的节点（bypass/mute 不算）。数字是“出现次数”，不是“推荐值”。

**H3（309 份）**

| 参数 | 分布（次数） | 解读 |
|---|---|---|
| SigmaShift（视频/音频） | 12/3 ×69，6/3 ×27，10/3 ×10，6/6 ×6，12/6 ×4，8/3 ×2 | 12/3 是默认；6/3 只配 768p lightx2v turbo；10/3 用于 0.5MP 左右的底；音频改到 6 的是少数 |
| 采样器 | res_multistep 146，euler 128，er_sde 48，euler_a 9 | 官方模板 res_multistep；turbo 多用 euler；er_sde 多见于 SEED HUNTER、LipSync、DMAD 推荐 |
| 调度器 | simple 265，beta 60，beta57 17 | beta/beta57 主要出现在 er_sde 组合里 |
| 步数 | 20 ×95，8 ×82，4 ×55，6 ×47，10/5 ×12，25 ×10 | 基模 20；turbo 8 > 4 > 6 |
| CFG | 1 ×62，1.5 ×5 | 1.5 只出现在 LipSync 的第二段 |
| 两段式第二段 ManualSigmas | `0.9035, 0.8000, 0.6316, 0.3158, 0` ×11；`0.9231, 0.8780, 0.8000, 0.6316, 0.3158, 0` ×8；`0.9035, 0.6316, 0.3158, 0` ×8；`0.85, 0.7250, 0.4219, 0` ×8；`0.7, 0.55, 0.3, 0` ×3 | 起点 0.90–0.92 是共识；0.85/0.7 起点改动更小，更像“只锐化” |
| 分辨率（宽x高x帧） | 1344x768x124 ×80，1344x768x73 ×68，736x1280x124 ×8，960x544x124 ×6 | 竖屏 736x1280 是少数派，我们 9:16 方向需要自己验证 |
| 放大 | MinimaxH3LatentUpscaler3D（LBH conv_v1 / 3d bf16·fp16）≥23；LTX 2.5/2.3 latent spatial x2 ≥8；RTX VSR 33；SeedVR2 13；RIFE 38 | 3D latent upscaler 是 H3 社区主流第二段 |
| 注意力/加速 | ModelAttentionBackend(comfy kitchen) 100，Sage 67，Spectrum 47，BlockSparse 32，SolAttn 19，H3SLA 10 | 我们现在关掉了 Spectrum/缓存（会改长相/加杂音），社区开的多，取舍不同 |

**H3 LoRA 实际用到的强度（中位数）**：fl2v_turbo_8step_v1.0 1.0（28 次）；fl2v_turbo_4step_v1.2 1.0（18）；ref2v_turbo_8step 1.0（14）；larryvrh v4 step600 ema 1.0（13）；lightx2v 4step v0.1 0.75（10）；HardGravy 6step 1.0（7）；ref LoRA r256 1.0（MICW 用 0.4）；**Motion Repair v1 0.25、V2 0.4**；电影感 V2 0.85、V1 正式版 0.6、V0.1 0.3；Detail Slider 2.0；**Exposure / DayNight 滑杆都只用 0.1**；realism-people 0.4。

**Qwen（274 份，含 2509/2511 老版）**：euler 为主，simple 调度；步数 25（2.1 全模型）/ 4、8（turbo/lightning）；cfg 1；ModelSamplingAuraFlow shift 3 左右；2.1 turbo 的 ManualSigmas `1.0, 0.978453, 0.95418, 0.926626, 0.89508, 0.845148, 0.704534, 0.414568, 0` 出现最多，常在 0.414568 处切成两段；分辨率 1024x1024 最常见，竖向 1024x1536 次之。

**我们机器上缺的节点（H3 工作流里出现最多的，按 gpu33 节点表）**：VHS_VideoCombine 75、SpectrumApplyMiniMaxH3 47、rgthree Power Lora Loader 46、RTXVideoSuperResolution 33、RIFE VFI 25、MiniMaxH3TurboSampler/TurboLoRA 20+、SolAttnPatch 19、SeedVR2 三件套 13、H3SigmaRefiner 13、H3SLAAttention 10。导入社区工作流前要先确认这些节点包（不在本轮范围，不装）。

## 4. 工作流清单（重点）

| 问题 | 工作流 (id) | 基模 | 要点 | 下载/赞 | 许可 | 本地 json |
|---|---|---|---|---|---|---|
| 迭代速度/质感 | [Minimax H3 SEED HUNTER - Latent Upscaler + Seamles](https://civitai.com/models/2881362) (2881362) | MiniMax H3 | SEED HUNTER：先出 3 条低分辨率预览挑种子，再对选中的跑 3D latent upscaler 定稿；er_sde+beta 8 步；comfy kitchen 注意力 + BlockSparse（sol-attn tau1.3 / sla tau10-20，start 0.2）；RIFE 24→48/60；作者提醒 ComfyUI 0.40 会弄坏很多工作流 | 37608/1085 | 产出可商用 | `civitai/2881362__Minimax_H3_SEED_HUNTER_-_Latent_Upscaler___Seamless_Video_Co/`（3 个） |
| 身份一致 | [MiniMax H3 Reference to Video - keep the same pers](https://civitai.com/models/2896536) (2896536) | MiniMax H3 | ref2va "保持同一人"：1-3 张同一人不同角度，混两人会得到第三个人；ref_image_size=match 快、max（短边 2048）像但慢数倍；帧数 17k+5（73/124/192/277）；turbo 版 8 步 165s vs 20 步 349s | 2501/65 | 产出可商用 | `civitai/2896536__MiniMax_H3_Reference_to_Video_-_keep_the_same_person_in_any_/`（2 个） |
| 身份一致/长镜头 | [MiniMax H3 LongTake — long videos clip by clip / c](https://civitai.com/models/2942000) (2942000) | MiniMax H3 | LongTake：Character Swap LoRA 1.0 + ref2v turbo 8step 0.95，res_multistep/simple 8 步，shift 10/3（0.5MP 底）；脸部特写作 <Picture 2> 相似度 +0.04-0.05；source_face=blur_keep_mouth 让原视频身份不渗漏（0.41→0.52）且保口型；提示词不要写表情（会让换人失效）；4-5s 一段 | 1984/62 | 产出可商用 | `civitai/2942000__MiniMax_H3_LongTake___long_videos_clip_by_clip___character_s/`（1 个） |
| 身份一致 | [Minimax H3 - Character Swap - Latent Upscale 2 Pas](https://civitai.com/models/2990259) (2990259) | MiniMax H3 | Character Swap 两段：er_sde+beta57，20 步在第 3 步切 + 6 步，3D latent upscaler 0.8MP；参考图越多越稳；提示词写清"把谁换成谁" | 1893/56 | 产出可商用 | `civitai/2990259__Minimax_H3_-_Character_Swap_-_Latent_Upscale_2_Pass_Workflow/`（2 个） |
| 长镜头 | [H3 Infinite Video Continuation and automatic Stitc](https://civitai.com/models/2852849) (2852849) | MiniMax H3 | FL2VA 无限续接：v1.4 起用原生 Masked AV Latent Continuation——把上一段安全部分的视频+音频 latent 直接拷入下一段并保护不去噪，作者说明显减少段间亮度/色彩跳变 | 3047/90 | 产出可商用 | 仅 meta（文件需登录） |
| 长镜头 | [MiniMax-H3 Multishot — Seamless Chain: multi-shot ](https://civitai.com/models/2833322) (2833322) | MiniMax H3 | Multishot Seamless Chain：多镜头作为一个连续 take 一次渲染，不靠尾帧链，镜间无质量损失（节点包 MiniMax-H3 Multishot） | 11289/244 | 产出可商用 | 仅 meta（文件需登录） |
| 长镜头/口型 | [Endless MiniMax H3 (with Endless LipSync)](https://civitai.com/models/2909076) (2909076) | MiniMax H3 | Endless + LipSync：ComfyUI-H3-Motion-Context + Clip Stitcher，保存每段 latent 在 latent 级拼接（避免解码再编码）；自定义音频直接替换音频 latent 迫使画面对口型；Spectrum 默认 audio_blend_weight=0（音频混合会口吃） | 2512/95 | 产出可商用 | `civitai/2909076__Endless_MiniMax_H3__with_Endless_LipSync/`（1 个） |
| 长镜头 | [MiniMax H3 Continuum – Long-Form Video & Audio for](https://civitai.com/models/2860061) (2860061) | MiniMax H3 | Continuum：基模 res_multistep/simple 20 步；Pika LoRA 版 lcm + ManualSigmas 1.0,.973,.923,.8,.571,.333,0（6 步）；ref2v turbo 8step 0.75-1.0 euler/simple 8 步 | 7204/190 | 产出可商用 | `civitai/2860061__MiniMax_H3_Continuum___Long-Form_Video___Audio_for_ComfyUI/`（8 个） |
| 口型 | [MiniMax H3 - LipSync](https://civitai.com/models/2935228) (2935228) | MiniMax H3 | LipSync V4：竖屏 736x1280x124，两段 er_sde simple 8 步 cfg 1 / 1.5；ScheduledSolAttention tau 1.3→0.8 线性；AddGuide frame 0 ×3；歌词对齐+分块写盘 | 2312/73 | **产出禁商用/未授权** | `civitai/2935228__MiniMax_H3_-_LipSync/`（4 个） |
| 迭代速度 | [Minimax Speed x 6 Workflow (Sage+Sol+Latent upscal](https://civitai.com/models/2890123) (2890123) | MiniMax H3 | Speed x6：Sage + SolAttn（tau1.3, 0.2-0.9）+ 3D latent upscaler ×2；res_multistep/simple 20 步在第 15 步切；作者推荐把安装说明交给编码 Agent | 4639/95 | 产出可商用 | `civitai/2890123__Minimax_Speed_x_6_Workflow__Sage_Sol_Latent_upscale/`（1 个） |
| 迭代速度 | [Fast MiniMax H3](https://civitai.com/models/2906467) (2906467) | MiniMax H3 | Fast MiniMax：fused turbo int8 底模 + comfy kitchen + sol attention；0.4MP 5s 约 70s（4060Ti）；ManualSigmas 4 步 0.9999,0.9728,0.9231,…；第二档 0.6-1.0MP | 3551/79 | 产出可商用 | 仅 meta（文件需登录） |
| 迭代速度 | [MiniMax H3 Ultra Fastest True 4 Steps + HD Sound /](https://civitai.com/models/2835250) (2835250) | MiniMax H3 | True 4 Steps：作者认为 6-8 步是平衡点；"Step 600 Lighting LoRA"推荐；Spectrum 只在 8 步时开 | 14175/281 | 产出可商用 | 仅 meta（文件需登录） |
| 迭代速度/卡顿 | [PlagueKind - Minimax H3 Sparse  Attention - Refmod](https://civitai.com/models/2663838) (2663838) | MiniMax H3 | PlagueKind：去掉 turbo（作者：turbo 毁画面和音频），默认 "9 步跳 4 步"；H3SLAAttention 稀疏 0.7-0.9 + reference_protection；linear_quadratic 15 步 | 26704/530 | 产出可商用 | `civitai/2663838__PlagueKind_-_Minimax_H3_Sparse_Attention_-_Refmod_-_LTX_Work/`（1 个） |
| 身份一致 | [MICW - Fast Character Sheet Generator Using Refere](https://civitai.com/models/2926613) (2926613) | MiniMax H3 | MICW 角色设定：H3 ref2va 直出多视角（ref LoRA r256 0.4 + ref2v turbo 4step）+ Qwen2.1 8 步后处理；shift 8/3；两段 ManualSigmas .9231…/.9035…；EasyCache 0.2 | 4983/199 | 产出可商用 | `civitai/2926613__MICW_-_Fast_Character_Sheet_Generator_Using_Reference_Images/`（1 个） |
| 身份一致 | [H3 Character Sheet Designer for ComfyUI -Image Gen](https://civitai.com/models/2983933) (2983933) | MiniMax H3 | H3 Character Sheet Designer：H3 当图片模型出 13 视角（头/全身/服装/手/鞋），1 主图+3 参考 | 2427/102 | 产出可商用 | `civitai/2983933__H3_Character_Sheet_Designer_for_ComfyUI_-Image_Generation/`（6 个） |
| 身份一致 | [[Qwen Image 2.1] Character Design Sheet Maker (Wor](https://civitai.com/models/2960750) (2960750) | Qwen 2.1 | [Qwen2.1] Character Design Sheet Maker V3（静态提示词或自动 PE） | 6298/184 | 产出可商用 | `civitai/2960750__Qwen_Image_2.1__Character_Design_Sheet_Maker__Workflow/`（8 个） |
| 身份一致 | [Qwen Image 2.1 Character Reference Sheet Generator](https://civitai.com/models/2960890) (2960890) | Qwen 2.1 | Qwen2.1 角色参考表：服装/脸/姿势三路分离输入 | 3834/109 | 产出可商用 | `civitai/2960890__Qwen_Image_2.1_Character_Reference_Sheet_Generator___Face___/`（3 个） |
| 身份一致 | [Character Sheet Edit LoRA (Qwen Image 2.1) - one p](https://civitai.com/models/2995608) (2995608) | Qwen 2.1 | Qwen2.1 单图→3x2 设定表（LoRA+工作流 zip）：euler/simple 25 步 cfg1 | 1880/90 | **产出禁商用/未授权** | `civitai/2995608__Character_Sheet_Edit_LoRA__Qwen_Image_2.1__-_one_photo_to_a_/`（2 个） |
| 身份一致 | [Qwen Image 2.1 Person Swap / Head or Full Body](https://civitai.com/models/2980685) (2980685) | Qwen 2.1 | Qwen2.1 换人（头或全身，BFS LoRA）+ Pruna 8 步 | 3419/137 | **产出禁商用/未授权** | `civitai/2980685__Qwen_Image_2.1_Person_Swap___Head_or_Full_Body/`（3 个） |
| 质感 | [Qwen Image 2.1 Generate + Edit / Full Model, Auto ](https://civitai.com/models/2962616) (2962616) | Qwen 2.1 | Qwen2.1 Generate+Edit（AusBoss）：1MP、边长对齐 32；euler/simple 25 步 cfg1；风格改动会让画面亮/上色，要在提示里写"保持…"；编辑时自动开 Consistency LoRA | 5122/153 | **产出禁商用/未授权** | `civitai/2962616__Qwen_Image_2.1_Generate___Edit___Full_Model__Auto_Prompt/`（6 个） |
| 迭代速度 | [Qwen Image 2.1 Turbo Generate + Edit / 8 Steps, Au](https://civitai.com/models/2994247) (2994247) | Qwen 2.1 | Qwen2.1 Turbo 8 步：ManualSigmas 1.0,.978,.954,.927,.895,.845,.705,.415,0；可分两段在 .415 切 | 2999/107 | **产出禁商用/未授权** | `civitai/2994247__Qwen_Image_2.1_Turbo_Generate___Edit___8_Steps__Auto_Prompt/`（5 个） |
| 质感 | [Qwen Image 2.1 Tiled Upscale / Up to 8 MP](https://civitai.com/models/2988629) (2988629) | Qwen 2.1 | Qwen2.1 分块重绘放大到 4/8MP（tile 2MP，overlap 128，keep_colors） | 3555/163 | **产出禁商用/未授权** | `civitai/2988629__Qwen_Image_2.1_Tiled_Upscale___Up_to_8_MP/`（3 个） |
| 竖屏 | [Qwen Image 2.1 Outpaint / Auto Prompt](https://civitai.com/models/2964810) (2964810) | Qwen 2.1 | Qwen2.1 Outpaint：选比例或拖边，Qwen3-VL 写提示，原图贴回 | 3608/148 | 产出可商用 | `civitai/2964810__Qwen_Image_2.1_Outpaint___Auto_Prompt/`（4 个） |
| 后期/超分 | [Video upscale workflow for Low VRAM (Extreme FAST)](https://civitai.com/models/2871874) (2871874) | MiniMax H3 | 低显存超分：SeedVR2/VOSR2 → 模型放大 → RTX VSR；H3 原生竖屏 480x864 → 1152x2072 | 2131/61 | 产出可商用 | 仅 meta（文件需登录） |
| 后期/超分 | [SeedVR2: one-step 4X video/image upscaling (and be](https://civitai.com/models/1769163) (1769163) | Other | SeedVR2 一步 4× 视频超分 + BlockSwap（AInVFX 教程） | 5802/87 | 产出可商用 | `civitai/1769163__SeedVR2__one-step_4X_video_image_upscaling__and_beyond__with/`（3 个） |
| 后期/换脸 | [🔥 Face Swap Video Workflow / ReActor + VideoHelper](https://civitai.com/models/2461437) (2461437) | Other | ReActor + VHS 视频换脸（inswapper_128 + CodeFormer + RetinaFace） | 2030/19 | 产出可商用 | 仅 meta（文件需登录） |
| 口型 | [InfiniteTalk - with Single speaker - Simple workfl](https://civitai.com/models/1710081) (1710081) | Wan Video 14B i2v 720p | Wan InfiniteTalk 单人口型（subgraph） | 2433/88 | 产出可商用 | `civitai/1710081__InfiniteTalk_-_with_Single_speaker_-_Simple_workflow__subgra/`（2 个） |

全部 831 个工作流目录、840 份 JSON 都在 `civitai/` 下，总表见 `docs/ep02_iter/workflow_library.md`（WFLIB 生成，civitai 计入“社区”一列）。

## 5. 按问题归类

### 身份一致
- **ref2va 参考图怎么给**（2896536）：1–3 张**同一人**的不同角度；混两个人会得到“第三个人”。`ref_image_size=match` 快，`max`（短边 2048）更像但慢数倍——参考 token 每一步都要重读。
- **换人配方**（2942000）：Character Swap LoRA（`h3_character_swap_pro4500_1000`，gpu33 已有）1.0 + ref2v turbo 8step 0.95，res_multistep/simple 8 步，shift 10/3；脸部特写作 `<Picture 2>`；原视频人脸 `blur_keep_mouth`；4–5 秒一段；某段只换了衣服没换脸时，换 seed 重做该段。提示词公式：“Replace only <谁，带可见特征> in <Video 1> with the character in <Picture 1>: …”，写发型、脸部特征、服装，不写表情。
- **2990259** 两段式换人：er_sde + beta57，20 步在第 3 步切 + 第二段 6 步，3D latent upscaler 0.8MP；参考图越多越稳。
- **Qwen2.1 侧**：Consistency LoRA（编辑不漂移/不放大，HF 上有更紧的 step2000）；Outfit Swap Consistency（gpu33 已有）；单图→3x2 设定表（禁商用，只作内部参考）；QMA/AnyAngle 多机位；角色设定工作流（2960750、2960890、2926613 用 H3 直接出多视角）。
- **H3 ref2va FaceSwap LoRA**（2940916，需登录）：强度 1，触发词 Faceswap。

### 卡顿 / 慢
- Motion Repair（gpu33 已有 V2）：社区工作流里实际强度中位数 v1 0.25、V2 0.4（常挂第二段或与 turbo 同挂）；h3_comfy_expert 记的 0.9 是作者给的上限。
- Better Human Motion 0.4–0.8（需登录）；运动速度滑杆默认 ±4，负值是自然慢动作（需登录）。
- PlagueKind（2663838）作者把 turbo 去掉了，原话大意是“turbo 毁画面和音频”，默认改成 9 步里跳 4 步。说明 turbo 是“卡顿/音频差”的一个可疑来源，值得和基模做对照。

### 多腿鬼影
- 社区没有专门针对“多腿”的 H3 LoRA；相关的是 Motion Repair、Polyhedron（手/眼/皮肤，需登录、禁商用）、LockStab（主体锁定，已下）。2975183 “Trileg” 是故意生成三条腿的风格 LoRA，不要误用。
- 工作流层面：稀疏注意力的前 20% 步保留全注意力（start_percent 0.2）是共识；H3SLAAttention 带 `reference_protection` 和 `stabilize_motion` 开关。

### 脸部细节
- Enhancers（需登录）、Sharper Video 1.5（需登录）、Restore Enhance Improve（需登录，可当 ref2va 修复/延长用）。
- 可用的：两段式 3D latent upscaler（LBH `minimax_h3_latent_upscaler_3d_conv_v1`）是社区最常见的“补脸部细节”手段；LTX 2.5 spatial upscaler x2 作第二段 refine 也有人用（2831976、2883915）。
- 后期：ReActor（inswapper_128 + CodeFormer）、FaceDetailer、PuLID 在 Civitai 上都是图像/SD 时代的工作流，对 H3 直接可用的只有逐帧换脸（2461437），会丢失口型细节，排在 H3 内部方案之后。

### 泛红 / 调色
- H3：Exposure 滑杆（-6~+6，只动最后两层，已下）、DayNight 滑杆（冷夜↔暖日光，已下）、Vibrant 滑杆负值去饱和（需登录）、CinemaGrade（需登录）。
- Qwen2.1 参考图：RAW photo v3 “Change to RAW photo”（中性色光，已下）；zjourney 0.5–0.6 专门压 turbo 的烤焦、高对比和偏黄（已下）；Lenovo cfg 3–4、beta、res_2s（已下）。
- 输出编码：VHS 编码可能偏色（h3_comfy_expert 已记）；MOSS（579280）用 LCS 潜空间颜色子空间节点在采样中控色（facok/ComfyUI-LCS，MIT），可作调色思路储备。

### 口型
- 自定义音频直接替换音频 latent，迫使画面对口型（2909076、2834514 “Forced Custom Audio”）。
- Spectrum 加速的 H3 版默认 `audio_blend_weight=0`，作者原因是音频混合会造成口吃/口型回退。
- LipSync V4（2935228）：竖屏 736x1280x124，两段 er_sde 8 步（cfg 1 / 1.5），ScheduledSolAttention tau 1.3→0.8。
- Natural Face & Speech 0.6–0.8（需登录）：固定 seed、台词用同一个开头词来防声音漂移。Kokoro 声音 LoRA 0.5–0.7，过高会伤口型（英语声线）。
- Wan InfiniteTalk、LatentSync 在 Civitai 上只有少量工作流（1710081 等），只作储备。

### 长镜头
- Masked AV Latent Continuation（2852849）、Multishot 一次渲染多镜头（2833322）、Motion-Context latent 级拼接（2909076）、LongTake 按 5 秒一段+每段身份参考（2942000）。
- 注意 h3_comfy_expert 已记：两段式放大会让接缝处像素位移，长链拼接适合单段采样。

### 质感 / 去塑料感
- H3：Realism Slider +1~1.5（已下；作者建议先不叠 turbo 测）；realism-people（gpu33 已有）；电影感 V1/V2（0.7/0.85，高动态 0.5，需登录）；Amateur Hour（降对比去光泽，需登录）；Instapic V2（已下）。社区工作流里 realism-people 实际用到 0.4（中位数）。
- Qwen2.1：PureLens（需登录）、Lenovo/Canon/GrainScape/Film Texture（已有或已下）、Fix v2.0（需登录，配 DPM++2M Sharp 采样器）、Restore（gpu33 已有）。

### 迭代速度
- 预览策略：SEED HUNTER（2881362）一次出 3 条低分辨率预览挑种，再只对选中的做 3D latent 放大定稿。
- 加速 LoRA（作者推荐设置）：DMAD 4step 6–8 步 er_sde/euler simple shift 12/2；taomate fl2va 3step 4–6 步 0.75；ref2v turbo 8step 8–12 步 er_sde/res_multistep；DMAD+Hyperflow 4 步 Euler simple/beta 12/3。
- 注意力：comfy kitchen + BlockSparse/Sol（tau 1.3，start 0.2，end 0.9–1），min_tokens 12288；Sage 和 kitchen 不能同时开（2862009 作者说明）；Sol 的 `int8_qk` 噪点多时关掉。
- 分辨率表（社区通用，multiple=32）：0.4MP 864x480、0.5MP 960x544、0.8MP 1216x672、0.98MP 1344x768（官方 768p）、2.0MP 1920x1088；竖屏取对调值（736x1280 常见）。帧数 17k+5（73/124/192/277）。

## 6. 需登录、已跳过的对口 LoRA（只记线索）

匿名下载会被重定向到 `/login?reason=download-auth`。下面这些都按规则跳过，没有登录。有 HuggingFace 原版线索的已经注明；是否改从 HF 获取由总调度决定（本轮范围只限 Civitai）。

| LoRA（Civitai id） | 文件 | 大小 | 用途 | 线索 |
|---|---|---|---|---|
| Natural Face & Speech v2 (2925394) | nafasp_h3_lora_v2_500 | 296MB | 口型、脸部肌肉 | 无 |
| Better Human Motion (2734359) | mvmt_h3_lora_v1_500 | 296MB | 卡顿 | 无 |
| Detail Slider (2929154) | DetailSlider-V1 | 5MB | 细节 | 作者其他滑杆匿名可下，这个不行 |
| Vibrant Slider (2775079) | h3_Vibrant_slider_rank4 | 4MB | 泛红（负值） | 无 |
| Motion/Action Speed Slider (2985458) | motion_speed / action_speed | ≤4MB | 卡顿/慢动作 | 无 |
| FaceSwap REF2VA (2940916) | SS_FaceSwap_MiniMax_H3_REF2VA | 63MB | 身份 | 作者说“更多示例在 HuggingFace” |
| Restore Enhance Improve (2989135) | Restore_Enhance_Improve_rank16 | 142MB | 修复/延长 | 无 |
| SSS Smooth Slow Sync (2985070) | Smooth_Slow_Sync | 296MB | 平滑/同步 | 无 |
| 电影感 V2 (2890588) | H3电影感V2.0 | 148MB | 质感 | RunningHub 有在线版 |
| CinemaGrade (2927223) | cinemagrade_style_h3_ep35 | 68MB | 调色 | 无 |
| Sharper Video (3018990) | Salia_Upscale_mmh3 | 250MB | 锐化 | 无 |
| Enhancers (3025511) | MiniMaxH3_Enhancer_epoch_10 | 296MB | 脸部清晰 | 无 |
| Shaky handheld (2592748) | handheld_h3_100 | 74MB | 运镜 | 作者 HF blog（neph1） |
| AsianMix H3 v1.4 (2961302) | hina_MiniMaxH3_AsianMix_v1.4 | 296MB | 东亚外观 | 作者训练器在 GitHub |
| Amateur Hour (2530917) | AmateurHour_H3 | 148MB | 降对比 | 无 |
| Polyhedron Perfect (2899220) | polyhedron_…_perfe8ct | 296MB | 手/眼/皮肤（禁商用） | 无 |
| DMAD+Hyperflow 4step (2929860) | minimax_h3_DMAD_Hyperflow_4step_r256 | 1.3GB | 加速 | HF silveroxides/MiniMax-H3_tests |
| QMA 多机位 (2998617) | qwen21_camera_angles_qma | 304MB | 多角度 | 无（gpu33 已有 AnyAngle 可替代） |
| Qwen2.1 Fix v2.0 (2957332) | qwen2.1-detail-fix-2.0 | 52MB | 细节 | 附带的对比工作流已下 |
| PureLens (2728005) | purelens_qwen21 | 152MB | 皮肤纹理 | 无 |
| Anything2RealCharacters (2808492) | Qwen2.1_Anything2RealCharacters | 304MB | 转写实 | 无 |
| VNCCS PoseStudio v2 (2957080) | VNCCS_QI2_PoseStudioV2 | 152MB | 姿势 | HF MIUProject/VNCCS_PoseStudio_QI2.1 |
| AsianMix Qwen2.1 v3 (1905553) | hina_QwenImage2.1_asianMix_v3.0-rank64 | 320MB | 东亚外观 | 作者训练器 GitHub hinablue/qwen-image-21-trainer |

工作流方面：Workflows 类型共 663 个，匿名直接下到文件的 134 个，517 个要登录；其中 245 个模型从示例媒体里补回了内嵌工作流。

## 7. Wan 2.2 / LTX 2.x 可迁移要点

- Wan 2.2 Lightning 4+4 步：步数越多，lightning LoRA 强度越低（6+6/7+7 步用 1.0 的经验因工作流而异）（1822764）。
- Wan 长视频：SVI（Stable Video Infinity）做多段一致性，2+2(+2) 采样器分段（2203691）；与 H3 的 Motion-Context/Masked Continuation 思路相同：续接靠 latent 而不是只靠尾帧。
- LTX 2.3/2.5：distill LoRA + 分辨率放大器 x2 两段式；LTX 2.5 支持 multishot；社区普遍把 LTX 作为 H3 输出的第二段 refiner（2831976、2883915），但要求“只用一种放大器，不然 LTX 会 OOM”。
- FastWan/TAE 预览：先用 tiny VAE（taeh3，Kijai/MiniMax-H3-TAE）预览，满意再完整解码——H3 同样可用 `ModelPreviewOverrideKJ` + taeh3 做快速预览。

## 8. 前 10 个值得在 ep02 实测

（只给配方，由 LAB 排期执行；本会话未提交任何渲染）

| # | 实测项 | 针对问题 | 配方要点 | 依据 | 文件是否就绪 |
|---|---|---|---|---|---|
| 1 | 换人/身份：脸部特写作第二参考 + 原脸 blur_keep_mouth | 身份一致、口型 | character_swap_pro4500 1.0 + ref2v turbo 8step 0.95，res_multistep/simple 8 步，shift 10/3，4–5 s/段，不写表情 | 2942000 实测数字 | gpu33 已有 |
| 2 | ref2va 参考组织：1–3 张同一人多角度；match vs max A/B | 身份一致 | 同 seed，比较 ref_image_size match/max 的相似度和耗时 | 2896536 | 现有 |
| 3 | H3 Realism Slider | 质感/塑料感 | 1.0 与 1.5，不挂 turbo；与 realism-people 0.4/1.0 对照 | 3014078 作者 | gpu36 已下 |
| 4 | Exposure / DayNight 滑杆修偏色与亮度 | 泛红、光线一致 | 社区实际只用 0.1 左右：从 ±0.1/±0.3 小步试；DayNight 先在提示词写清时间段 | 2946844、2949040 | gpu36 已下 |
| 5 | Masked AV Latent Continuation 续接 | 长镜头接缝、亮度跳变 | 上段尾部 V+A latent 拷入下段并保护 | 2852849 | 需节点包（工作流已存） |
| 6 | SEED HUNTER：3 条低分辨率挑种 → 3D latent 放大定稿 | 迭代速度 | 0.4MP 预览，选中后 latent upscaler conv_v1 到 0.98MP | 2881362 | 工作流已存 |
| 7 | 预览加速 LoRA A/B | 迭代速度、卡顿 | taomate 3step 0.75（4–6 步）/ FastH3 4 步 / HardGravy 6 步 vs 现用 lightx2v 8step；同 seed 比运动与音频 | 2837571、2898443、2923611 | gpu36 已下 |
| 8 | 基模 vs turbo 的卡顿/音频对照 | 卡顿、口型 | PlagueKind 结论“turbo 伤画面和音频”；基模 res_multistep 20 步 vs turbo 8 步 | 2663838 | 现有 |
| 9 | Qwen2.1 角色设定链：Consistency + Outfit Swap + Outpaint 9:16 | 身份一致、竖屏 | 编辑时开 Consistency；灰边扩图到 9:16；1MP、边长对齐 32、euler/simple 25 步 cfg1 | AusBoss 系列 | gpu36/gpu33 已有 |
| 10 | Qwen2.1 turbo 出图去偏黄 | 泛红/质感、迭代速度 | 8 步 ManualSigmas `1.0,.978453,.95418,.926626,.89508,.845148,.704534,.414568,0` + zjourney 0.5–0.6 或 Lenovo；参考图再过 RAW photo 0.3 | 2994247、2686999、2958738 | gpu36 已下 |

## 9. 许可提醒

- 产出禁商用/未授权（本轮已下的）：FastH3（只 Rent）、character-sheet edit LoRA（None）、zjourney（Rent）。只能内部对比，上线前要换或找原作者授权。
- gpu33 上已有的 realism-people（Civitai 转载页只写 Rent；原版在 fal HF，许可以 HF 为准）、Qwen Restore/Outfit Swap/Consistency（AusBoss，只 RentCivit）同样需要人工确认。
- MoreReal、High resolution（NO8D）页面明说禁止商用，未下载。

## 10. 成人向（本地专用）

> **只能在本地 ComfyUI（gpu33/gpu36）使用，不得经任何外部 API 调用或上传。** 角色全部为合成成年人（见 docs/UNCENSORED_INVENTORY.md、config/adult_overrides.json）。本节只记技术信息（基模、文件、触发词、权重、对画面的作用），不涉及剧本内容；未生成任何内容，未查看示例图。

### 10.1 筛选方法

- 来源：Civitai API `nsfw=true`，基模 `MiniMax H3` / `Qwen 2.1` / `Krea 2` 的 LoRA，以及 H3 / Qwen 2.1 的工作流，按下载量取前 500/300/300/200/100。
- 只保留模型级 `nsfw=true` 的条目；Civitai 自带的 `poi`（真实人物）或 `minor` 标记为真的一律排除。
- 自动排除（标题、标签、触发词、描述任一命中即排除）：
  - 未成年或儿童化相关词：loli、shota、teen、young、petite、child、school、student、uniform、tiny、flat chest、chibi、age/aging 等
  - 非自愿、暴力、兽交、非人类相关词：rape、forced、non-con、drug、sleep、hypno、bondage、bdsm、choke、slap、blood、gore、tentacle、animal、monster、furry 等
  - 动漫、卡通、Pony、Illustrious 风格：这类风格里成年与否不可靠，全部排除
  - 带“人物”类标签：character、celebrity、influencer、model、cosplay、girl(s) 等
  - LoRA 没有 concept/style/pose/action/clothing/slider 一类标签的：多为特定人物 LoRA，存疑排除
- 人工二审，存疑的再排除：真实片商或品牌风格、疑似真人艺名、偷拍类、BDSM/窒息/呕吐倾向、变身幻想、去马赛克（可作用于真人片源）、文件名与页面不符等。
- **结果：通过 174 个（LoRA 160、工作流 14）。共排除 435 个，被排除的不记名字：自动词表 372，人物标签 37，人工二审 26。**
- 局限：没有逐张查看示例图，靠的是 Civitai 自身的标记加上文字层面的严格过滤。LAB 首次加载任何一个 LoRA 前，若发现画面人物不明显是成年人，立即停用并删除。

### 10.2 已下载（gpu36 `/root/work/fredw/comfy/ComfyUI/models/loras/civitai/adult/`，14 个，3.7GB，sha256 全部校验通过）

匿名能下的 H3/Qwen2.1 成人 LoRA 只有 15 个，其中 1 个人工二审排除，其余全下。另外 74 个（H3 60、Qwen2.1 14）需要登录，已跳过。

| 文件 | 基模 | 作用（技术层面） | 触发词 | 权重 | 许可 | sha256（前 16 位） |
|---|---|---|---|---|---|---|
| MinimaxH3-Fingering_000002000 | H3 | 手部动作与接触细节 | 无 | 页面未写，从 0.6–1.0 试 | 产出禁商用 | e758e831ff85aeb4 |
| HMInnie_v1_e50 | H3 | 女性解剖细节 | inniepussy | 未写 | 产出可商用 | 499196c9d0e5f81f |
| blowJobMinimax_v1 | H3 | 口部动作 | 无 | 未写 | 产出禁商用 | 0d1542e274d970be |
| h3lineupbjhjsmilev1_v1 | H3 | 多人动作编排 | 无 | 1.0（作者） | 产出禁商用 | 77a6b152213f8796 |
| CumBlast_minimaxh3_3265653_epoch_8 | H3 | 液体特效 | SlimeBlast | 未写 | 产出禁商用 | 9d31501c9dc38e4a |
| blowjobSandwichH3_v2 | H3 | 多人动作编排 | 无 | 1.0（作者） | 产出禁商用 | f0dcad62cdc637dc |
| H3BJGestureV1_v1 | H3 | 手势与动作 | 无 | 1.0（作者） | 产出禁商用 | 1c7129a4bea76a33 |
| pokiesMinimaxH3_v1 | H3 | 衣物下的身体细节 | pokies | 未写 | 产出可商用 | 47341e0035e86c0f |
| justnaked（Classic Beauty） | H3 | 复古风格裸体 | 无 | 未写 | 产出可商用 | c366e539c3dedfc7 |
| nippleLickingHandjob_v1 | H3 | 双人动作 | nipple licking handjob | 未写 | 产出可商用 | a5c247f33066b9a5 |
| latexClothesMinimax_v1 | H3 | 乳胶服装材质 | latex | 未写 | 产出可商用 | aa4349b7e773783f |
| boobtwistfuckForH3_minimax_v1 | H3 | 双人动作 | 无 | 1.0（作者，可在提示里加强运动描述） | 产出禁商用 | 4fd6968ae8bb1802 |
| foreskin_stretch_v1.1 | H3 | 男性解剖细节，手部动作 | fskin_stretch | 未写 | 产出可商用 | 2afdeb58470568e6 |
| qwen21_v2_000002750（qwen 2.1 vagina） | Qwen 2.1 | 静帧解剖细节，用于首尾帧或参考图 | 无 | 未写 | 产出可商用 | 71d8edbfbb693da3 |

完整 sha256 在 gpu36 同目录的 `_download.log`。目录元数据在 `data/ab/owner_workflows/civitai/_catalog/adult_models.json`：174 个通过项全都有基模、权重说明、触发词、许可和访问状态，排除项只记数量。

### 10.3 已在 gpu33 的同类文件

MysticXXX_MMH3-V4、HMNSFW-AIO-V2.5、Minimax_H3_Unlocked_V2.1（H3），qwen2_1-femaledVaginus（Qwen2.1）。社区 H3 工作流里出现最多的成人 LoRA 是 DR34ML4Y AIO（52 万下载，需登录，只许 RentCivit）和 HMNSFW-AIO，作用都是给基模“解锁”解剖细节和动作。H3 基模本身已能生成裸体，这类 LoRA 主要补的是解剖准确度和动作连贯性。

### 10.4 Krea 2 基模的条目

通过筛选的 Krea 2 LoRA 有 72 个，其中质量类工具不少：Realistic Slider、NSFW Helper Slider、PhotoReal BetterNudes、Krea2 AIO NSFW 等。**我们的机器上没有 Krea 2 基模**（出图用 Qwen-Image 2.1，`krea2_film_texture_qwen21` 是 Qwen2.1 的 LoRA），所以只记入目录，没有下载。以后接入 Krea 2 基模再按目录取用。

### 10.5 工作流

成人向的 H3/Qwen2.1 工作流共 14 个，6 个可匿名下载，已存到 `data/ab/owner_workflows/civitai/adult/<id>__名字/`，其余需登录。它们主要是 Qwen2.1 的稳定出图/编辑参数模板、人像调参、Mannequin 摆姿，以及 H3 TFL2VA；技术上与普通工作流没有差别，参数已并入 parsed.json。
