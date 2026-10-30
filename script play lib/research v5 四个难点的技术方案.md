# NS-Final Studio · 调研 v5：四个难点的技术方案

> 日期：2026-10-30。v3 / v4 只列了模型，本篇查的是**做法**：身份一致、饰品数量、多人同框、高清。
> 均未实测；⚠ = 单一或二手来源。已在本机 ComfyUI 核实的条目标 ✔。

## 0. 结论（按影响排序）

1. **身份问题主要在首帧端。** FL2VA 锁首帧时身份保持得最好（InsightFace 余弦均值 0.886；Ref2VA + 音频只有 0.07–0.09，有争议 ⚠）。所以先把首帧的脸锁住，视频端尽量用 FL2VA。
2. **首帧锁脸：训练林晚的 Qwen 2.1 图像 LoRA + 单参考编辑。** ai-toolkit 已支持 `arch: qwen_image_2`（不能沿用旧 Qwen 配置），12GB 卡可训。没有 Qwen 2.1 的 PuLID / InstantID。
3. **饰品数量（如九环九串、左 5 右 4）不能靠模型数数。** 改为确定性合成：Blender 渲染饰品 → 贴到首帧 → 低重绘融合 → 自动数数质检。H3 会把小而低对比的细节“平均化”，视频端把握低。
4. **高清：** 先出 768 级视频，再分块精修到 1440p/2K，最后在后期加调色和颗粒。
5. ✔ **H3 帧数须落在 17k+5 网格**（节点会向上取整）：10 秒 = 243 帧；训练范围约 124–362 帧。

## 1. 女主身份一致性（置信度：中）

| 方法 | 证据 | 结论 |
|---|---|---|
| FL2VA 锁首帧 | 同图同提示词对比，FL2VA 0.886 vs Ref2VA+音频 0.07–0.09 ⚠ https://huggingface.co/MiniMaxAI/MiniMax-H3/discussions/91 | 视频主路线 |
| Qwen 2.1 角色 LoRA | ai-toolkit `arch: qwen_image_2`；12GB 配置：31 张、rank 16、2000 步、adamw8bit、LR 1e-4、convrot8 量化 + 层卸载，4070 约 3.5 小时；作者测的是动漫角色，写实效果为转述 ⚠ https://note.com/sepiablue/n/n9372886b9e5d | 必须做；3090 或本机都能训 |
| musubi-tuner | 是否支持 2.1，两个来源说法相反 ⚠ https://www.orcarouter.ai/blog/qwen-image-2-1-lora | 先用 ai-toolkit |
| 多参考编辑 | 1 张参考图就能保持身份；画布尺寸要和参考图一致（眼距波动 ±3.9%，不一致时 ±18.9%）；23 次里 7 次要重抽 https://ai-muninn.com/en/blog/qwen-image-21-same-face-8-outfits-rtx-5090 | 与 LoRA 组合用 |
| ReActor（inswapper_128） | 128px 分辨率，视频里会闪烁 | 只补救单张首帧 |
| H3 Character-Swap | Ref2VA 换人，作者称实验性、会漂移 https://huggingface.co/akatz-ai/MiniMax-H3-Character-Swap-LoRA | 兜底 |

配套：建 ArcFace 质检门（阈值约 0.8 ⚠），首帧和视频抽帧都要过。

## 2. 小饰品数量与纹身（置信度：图像端 中，视频端 低）

推荐流程：
1. 用 Blender 渲染饰品资产，带 alpha、法线、深度通道；纹身（含“沉”字）做成矢量贴花，按镜头光照角度渲染。
2. 把渲染结果贴到首帧，用 Qwen 2.1 遮罩局部重绘融合（crop-and-stitch），低重绘约 0.2–0.35 ⚠；或用 Fun ControlNet 的 inpaint + canny 组合，只改光影、不改结构。
   - Fun ControlNet Union 是单个 7.5GB 文件，含 8 种控制 + inpaint；ComfyUI 支持截至 9-24 仍在 PR #16519 审核中，需核实是否已合并 ⚠ https://comfyui-wiki.com/en/news/2026-09-24-qwen-image-2-1-fun-controlnet-union
   - 官方有 Relight Composited Product 模板可参考：https://comfy.org/workflows/templates-qwen_image_edit-crop_and_stitch-fusion-ae12a241076c/
3. 用 VLM 或检测模型自动数环数，数错就重做。
4. 视频端：H3 会把小而低对比的细节“平均化”，细笔画文字会变软、变形 ⚠ https://github.com/teskor-hub/minimax-h3-skill/blob/main/portable-prompt.md
   - 对策：提示词写明位置和尺寸，饰品镜头用中近景、小动作。
   - 纹身镜头生成后，用平面或点追踪（CoTracker / Resolve）把贴花回贴到每一帧。

服务器上的另一个工作流（`data/train/jewellery`，Blender `jwl_scene.py` + `jwl_photoreal.py`）走的正是第 1–2 步的方向。

## 3. 2–3 人同框（置信度：中）

- **图像端：**
  1. 先用 pose ControlNet 或剪影定好构图。
  2. 每个人单独做一次局部重绘，只在这一遍加载该角色的 LoRA，不全局叠加多个 LoRA。
  3. 也可以把每人一张参考图喂给多参考编辑。
  - 没找到 Qwen 2.1 的区域提示或注意力遮罩节点；现有的 Regional/Couple 节点是 SD 时代的，兼容性未知 ⚠。
- **视频端：**
  - Ref2VA 双人测试（每人一张全身设定图，用 `<Subject N>` 标签，每镜重写完整外貌）无串脸，但 n=1，且两人外貌差异极大 https://ai-muninn.com/en/blog/minimax-h3-ref2va-two-characters
  - 有用户报告多人时声音会串到别人身上，FL2VA 同样出现 https://github.com/MiniMax-AI/MiniMax-H3/issues/17
- **3 人没有任何测试数据。** 三人镜头用剪影或背影，只露一张正脸；角色外貌差异做大；对白尽量拆成单人镜头。

## 4. 高清与电影感（置信度：中）

- **显存实测：**
  - 5090 上 INT8，864×480、243 帧：峰值 28.6GB、185 秒（10 步）→ 3090 必须开卸载 https://ai-muninn.com/en/blog/minimax-h3-nvfp4-rtx5090
  - 3090 上 832×480、362 帧：峰值 19.8GB、23 分 17 秒（量化方式不明 ⚠）
  - 3090 跑 768×1344 / 243 帧：无公开数据，预计每段 15–30 分钟 ⚠，需自测
- **精修选项：**
  - **Open-H3-Regenerate-2K**：LoRA，输入 1344×768、121 帧，3 步 Euler 输出 2560×1440；B200 BF16 用时 87 秒；没有显存数据和画质指标；243 帧要按时间分段 https://huggingface.co/Efficient-Large-Model/Open-H3-Regenerate-2K
  - **MMH3 Ultimate Upscale**：按时间分段 + 空间分块，显存峰值只取决于一块；有用户跑到 2550×1920，音频原样保留 https://comfyui-wiki.com/en/news/2026-08-25-mmh3-ultimate-upscale
  - **SelfLift**：免训练的渐进分辨率采样，H3 起点 rho 0.6，H3 支持为实验性 ⚠ https://comfyui-wiki.com/en/news/2026-09-19-comfyui-selflift
  - **SeedVR2**：时间一致性要求批大小 ≥5，大批量超过 24GB，可用 BlockSwap 卸载但慢 https://github.com/numz/ComfyUI-SeedVR2_VideoUpscaler
- **后期：** `ffmpeg -vf "lut3d=film.cube,noise=alls=5:allf=t+u"`，颗粒在超分之后加。

## 5. 测试优先级

1. 3090 上测 H3 INT8：768×1344 / 243 帧，块卸载，8 步 Turbo 的显存和速度。这决定整个排期。
2. ai-toolkit `qwen_image_2` 训练林晚写实 LoRA，同时建 ArcFace 质检门。
3. 对比首帧路线：LoRA / 单参考编辑 / 两者结合，再接 FL2VA，比较最终视频的身份相似度。
4. 搭饰品“合成 → 低重绘融合”流程（先核实 PR #16519），用 ep21 测 FL2VA 下饰品保留情况。
5. 精修链对比：MMH3 Ultimate Upscale / Regenerate-2K / SeedVR2，记录每 10 秒的耗时。
6. 双人测试：分区重绘 + FL2VA 对比 Ref2VA，检查串脸和串声。
7. 纹身追踪回贴（只在第 4 步发现 H3 丢细节时才做）。
