# ep01 渲染记录（fredw-d9，2026-10-30；供新旧版对比）

## 旧版（当前画布上的 ep01，gpu3 `nsfs_mirror/data/renders_gpu3/ep01/`）

- **剧本**：共享导入 `nsfs_mirror/data/import/script_v2.json`（v2 剧本，**没有 H3提示词 字段**）。
- **H3 提示词来源**：6 镜全部是 `fallback:template`，即渲染器在剧本没有 H3提示词 时用模板拼的英文提示词，**不是剧本原文**。这是旧版 H3 提示词“没按规则”的系统原因。
  渲染器规则（`weita_render.py: h3_prompt`）：画布修改 > 剧本 **H3提示词** 原文（`script_field`，只按实际帧数改秒数）> 模板。新剧本带 H3提示词 字段 → 会原样使用。
- **首帧提示词**：剧本 img 原文 + 剧本人物锁定行原文 + 《image提示词》§1.2 结构标签（构图、装饰锁等），由 frame_spec 拼装；`loras_image` 为空（当时林晚出图 LoRA 还没训完）。
- **视频参数（S1–S5 相同）**：`h3_fl2va_int8`，加速 LoRA `minimax_h3_fl2v_turbo_8step_v1.0_768p_comfyui_bf16` 强度 1，8 步，768×1344，243 帧 @ 24 fps（≈10 s），首尾帧模式；种子每镜固定（S1 1101683047、S2 3518236295、S3 3857003321、S4 1035648402、S5 900381660）。S1 有尾帧锚点 `ns-studio/data/run/weita/ep01/frames/ep01s1.last.png`，S2–S5 没有。
- **时间**：视频 10-29 14:00–14:57；首帧 10-29 12:43–16:26。**S3、S5 的当前首帧比视频新**（S3 首帧 15:31 / 视频 14:31，S5 16:26 / 14:01）→ 画布显示的首帧不是视频实际用的那张（与 qc_ep01 S3 结构相关性 0.118 一致）。
- **S6**：没有视频版本。
- 所有 compiled.json 于 10-30 03:50 UTC 重新编译过提示词，但视频没有重出。

## 新版（待渲染）

前提：fredw-92 导入新规则版 ep01 并同步到 gpu3 `nsfs_mirror/data/import/script_v2.json` 后通知。

- 首尾帧：`:8100` → Qwen Image 2.1 Turbo，林晚 LoRA 用最终版 `lin_wan_qi_v1.safetensors`（sha 873b727b…，项目方指定）。
- 视频：H3，参数同旧版，提示词用剧本 H3提示词 原文（compiled.json `h3_prompt_source` 应为 `script_field`，渲染后逐镜核对）。
- GPU：GPU3 整卡；GPU0 继续 lnwan01。
- 产物目录与 A/B 约定见 fredw-92：笔记本 `data/ab_renders/<version>/epXX/S<n>/{first.png|frame.png, last.png, video.mp4}` + 每版 `manifest.json`。
