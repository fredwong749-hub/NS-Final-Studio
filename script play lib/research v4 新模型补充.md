# NS-Final Studio · 调研 v4：v3 之后的新图像 / 视频模型（写实向）

> 日期：2026-10-30。只补充 `research v3 模型与LoRA.md` 里没有的内容，不重复 v3。
> 一手来源以 ComfyUI 官方 changelog（docs.comfy.org/changelog.md）和 Hugging Face 模型卡为准；标 ⚠ 的条目只有二手来源，未核实。
> 所有结论**都没有经过我们自己的测试**，以 3090 上的金标镜头 A/B 为准。

## 0. 结论

1. **视频主力仍是 MiniMax H3**：没有找到写实度有可信证据超过 H3 FL2VA/Ref2VA 的开源视频模型；中文对白准确度 H3 也领先（LTX 2.5 双人对白 CER 9.5%，H3 0%）。
2. **图像端值得加两条对照路线**：FLUX.3 Image Klein（许可比 qwen-research 宽松）和 SenseNova U1.5（原生 4K、多参考编辑）。
3. **闭源 API 不能用于成人镜头**：Kling / Seedance / Wan / 各家图像 API 都有内容审核或规则不明。只能用在非成人镜头上，作为「真人感上限」的参照。

## 1. 图像模型

| 模型 | 日期 | 开/闭 | 相对现有栈的优势 | 3×3090 可行性 | 许可 | 来源 |
|---|---|---|---|---|---|---|
| **FLUX.3 Image Klein**（base + 蒸馏） | 10-13 | 开源 | 文生图、编辑、≤10 张多参考合在一个模型里，支持 bbox 控制；模型卡**没有**声称写实优势 | 5.6B DiT + Qwen3-VL-4B 编码器；BF16 峰值约 31GB，FP8 约 26GB；INT8 + 卸载可行（INT8 8GB ⚠） | FLUX Kommunity：年营收 <500 万美元可商用 | huggingface.co/black-forest-labs/flux-3-image-klein |
| **SenseNova U1.5 8B-MoT** | 08-20（ComfyUI 09-09） | 开源 | 原生 4K；多参考编辑 ≤10 张；自称材质、光线更写实，身份更稳；已知过锐、过饱和 | 8B，INT8 应能放进 24GB（⚠未实测） | Apache 2.0 ⚠ | huggingface.co/sensenova/SenseNova-U1.5-8B-MoT |
| FIBO 2.0 Dev / Edit Turbo | 10-20 | 开源 | 编辑榜开源第一、文生图与 Qwen 2.1 持平 ⚠；只用授权数据训练，写实上限存疑 | 8B，可行 | CC BY-NC，商用需另签 | comfyui-wiki.com/en/news/2026-10-20-fibo-2-0 |
| Nano Banana 2.1、Krea 3、FLUX 3 Max、HY Image 3.5 Preview、Seedream 5.0 Flash | 9–10 月 | 闭源 | 写实度可能更高 | — | 有内容审核 | docs.comfy.org/changelog.md |

## 2. 视频模型

| 模型 | 日期 | 开/闭 | 相对现有栈的优势 | 3×3090 可行性 | 许可 / 限制 | 来源 |
|---|---|---|---|---|---|---|
| **LTX 2.5**（22B 音视频） | 08-11 | 开源 | 速度约为 H3 的 3 倍；IC-LoRA：Refine-Details、Restore（09-27）、Slow-Motion-Control（09-15）。中文双人对白 CER 9.5%（H3 0%） | 5090 峰值 31.7GB；3090 需 INT8 + 卸载 | LTX 许可 | huggingface.co/Lightricks；ai-muninn.com/en/blog/ltx25-vs-minimax-h3-rtx5090 |
| Kandinsky 6.0 Pro 30B / Lite 3B | 09-09 | 开源 | 音视频同步、带口型 | 有社区 INT8（kabachuha int8-convrot）；**每段 5 秒、基础 864×480** | MIT，仓库需申请 | huggingface.co/kandinskylab/Kandinsky-6.0-Pro-5s-Diffusers |
| Kandinsky 6.0 VSR | 09-15 / 09-21 | 开源 | 视频超分 ×2–×4，有 2 步蒸馏版 | 未写显存 | MIT | 同上 |
| Hunyuan Prism | 10 月上旬 | 开源（研究预览）⚠ | 原生 720p–2K 音视频，约 10 秒 | 720p 需 80GB ⚠；HF 上没找到仓库 | MIT ⚠ | kombitz.com 10-10 新闻汇总 |
| Hy-Nomas | 10-21 | 开源 | 文生视频世界模型，**不支持图生视频**，不适用 | — | Apache 2.0 | huggingface.co/tencent/Hy-Nomas |
| Kling 4.0 | 10-15 | 闭源 | 单段最长 30 秒、1080p、立体声、口型更准；参考 15 张 | — | 约 $0.17/秒（Pro 1080p，⚠）；全档位禁性暗示 ⚠ | kling.ai 博客；docs.comfy.org/changelog.md |
| Seedance 2.5 | 07-31 | 闭源 | 30 秒，参考素材 30+ | API 最高 720p；脸部偏「过 HDR」 | 有审核 | fal.ai/learn/devs/seedance-2-5-vs-seedance-2-0 |
| Wan 3.0 | 08-06 | 闭源公测 | 30 秒，Omni-Reference | — | 闭源 | instasd.com/post/wan-3-0-comfyui-what-is-real |
| H3 Max（fal） | 09-02 | 闭源 | 图生视频带音频榜第 1（1204 vs H3 1184 ⚠） | 768p 上限 | 审核规则不明 | suno.bi/en/blog/minimax-h3-open-source-ecosystem-explained |
| FLUX 3 Video、Vidu Q4 Preview、PixVerse V6 Max、VEED Lipsync 2.0；超分 Crystal Video Upscaler、vCube Enhance 8K | 8–10 月 | 闭源 | 未评估 | — | 有审核 | docs.comfy.org/changelog.md |

## 3. 加入 M1 bake-off 的建议

1. **图像**：FLUX.3 Klein（base 用 INT8，蒸馏版做快速预览）、SenseNova U1.5（专测多参考编辑），与 Qwen 2.1 / NoctQ 对比首帧皮肤质感和多参考身份保持。
2. **视频**：主力仍是 H3。新增 LTX 2.5 + IC-LoRA Refine-Details / Restore，测两件事：作为 H3 输出的 v2v 细节精修；作为无对白镜头的快速替代。**有对白的镜头不用 LTX。**
3. **闭源参照**：只用非成人金标镜头（如 ep01、ep59）各跑一次 Kling 4.0，作为「真人感上限」，不进生产。
4. **暂缓**：Kandinsky 6.0（5 秒、480p）、Hunyuan Prism（80GB、仓库未核实）、Hy-Nomas（不支持图生视频）。
