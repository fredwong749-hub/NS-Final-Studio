# Render bench（RTX 4080 Laptop 12GB / 32GB RAM，ComfyUI 0.39.0）

更新：2026-10-30 02:30。**本轮在途中被叫停**：系统内存严重不足，Claude Code 杀掉了 ComfyUI（:8188）和 API（:8800）。
下面标注 ⛔ 的部分没做完。

## 1. 基线首帧批量（旧风格，Turbo t2i）

- 178/178 个非成人镜头全部出图，0 失败；`--report` 已把旧输出迁移成 take v1（`takes.json`，workflow=qwen_t2i）。
- 速度：ComfyUI 内部执行约 12 s/张；整批热机后约 15 s/张（报告平均 15 s）。最开始的“35 s/张”是冷启动加载。
- 这些都是旧风格。新风格的 `--force` 重出 ⛔ **没跑**（被叫停）。

## 2. 视频冒烟测试：ep01-S1，H3 FL2VA w4a8 + 8 步 turbo LoRA，576×1024，243 帧（10.125 s，24 fps）

| 项目 | 数值 |
|---|---|
| 结果 | ✅ 第一次就成功，没有 OOM，`--reserve-vram 1` 原配置即可 |
| 总耗时 | 485 s（ComfyUI 内部 483 s；采样 8 步 × 约 55 s = 7 分 19 秒，其余是文本编码、加载和 VAE 解码） |
| 显存峰值 | 11.4 GB / 12.3 GB（动态显存加载：H3 暂存 11956 MB，按需搬运） |
| 系统内存 | **空闲最低只剩 0.95 GB / 32 GB**（全机统计，含另外两个 Claude 会话）。H3 的 UNET 12.5 GB 和 32B 文本编码器 15.7 GB 都要放进内存 |
| 输出 | h264 576×1024 243 帧 + AAC 音频；last.png 已抽出 |
| 画面 | 上摇运镜连贯，没有崩坏。抽帧拼图：`golden/video_smoke/ep01-S1_contact.jpg` |

问题：ep01-S1 的首帧只拍到脚，脸是 H3 自己编的（蓝色短发波波头、欧美脸），剧本写的是“蓝发及腰齐刘海”。
只给首帧锁脸，这类“从脚摇到脸”的镜头锁不住身份。可选办法：FL2VA 的尾帧给一张锁过脸的林晚图（`edits.last_frame`），
或者试 `minimax_h3_ref2va`（模型已经下载到本机）。

内存结论：H3 和 Qwen 不要同时常驻，也不要在出视频时跑 CPU 质检（CLIP-L 约 2 GB）。机器上还开着别的会话时，32 GB 已经到极限。
重启 ComfyUI 之后、出 Qwen 和 H3 之间建议调一次 `/free`。

## 3. Base 还是 Turbo（非成人防裸露）⚠ 部分完成

设置：同一编译提示词、同一种子，负面词追加 `裸体、裸露、裸背、赤裸上身、露出乳房、内衣外露、性感暴露`（只追加，正面词不动）。
Base = `qwen_image_2.1_int8_convrot`，25 步 euler/simple。每张图都过裸露质检（见第 4 节）。原始数据：`golden/base_vs_turbo/results.json`。

**速度**：Turbo 12–21 s/张（中位 18 s），Base 66–72 s/张，约慢 **3.8 倍**。按 178 镜头算：Turbo 约 55 分钟，Base 约 3.4 小时。

**裸露拦截率（质检判定为裸露的比例）**

| 镜头组 | Turbo（CFG 1） | Base CFG 2.5 | Base CFG 3 | Base CFG 4 |
|---|---|---|---|---|
| A：ep01-S5、ep01-S3、ep02-S1、ep10-S2（各 1 个种子） | **0/4** | 2/4 | — | 1/4 |
| B：基线里被 NudeNet 标出的镜头 ep11-S1、ep16-S4、ep26-S1、ep27-S3、ep29-S6、ep40-S1（2 个种子；ep40-S1 只跑完种子 0，之后被叫停 ⛔） | 11/11 | — | 10/11 | 10/11 |

结论：
- **Base + 真实 CFG 并没有减少裸露。** A 组 Turbo 反而全部干净，B 组三种设置几乎全部被拦。CFG 把正面词（G罩杯等）放大的程度，不比负面词压制的少。
- Base CFG 4 明显过饱和（发色变成荧光蓝）；CFG 2.5–3 好一些，但仍比 Turbo 艳。
- ep01-S5（基线里赤裸背影的那个镜头）：新风格下 Turbo、Base 2.5 和 Base 4 都穿着上衣，三张都通过质检。我看过这三张：`golden/base_vs_turbo/ep01-S5_turbo_base4_base2.5.jpg`。Base 4 那张下身只穿内裤，质检不把这个算裸露。
- **建议**：防裸露靠质检闸门，模型改回 Turbo（`pipeline.NON_ADULT_USE_BASE = False`），速度快 3.8 倍。
  代码里目前仍按负责人要求用 Base（`NON_ADULT_USE_BASE = True`），改一个常量即可。
- **B 组 6 个镜头不管用哪个模型、哪个种子，几乎都会出裸露**，很可能是编译器漏判的成人镜头（关键词表没覆盖）。
  需要负责人或项目方复核分类（compiler.py 不归我改）。ep26-S1 Base 3 和 ep29-S6 Base 4 各有一张通过质检，CLIP 分数在 0.68–0.80，处在阈值边缘，不能当成安全。

## 4. 非成人裸露自动质检（已实现，已接入流水线）

- `services/render_router/ns_render/qc.py`：NudeNet 3.4（露出的胸部、生殖器、臀部、肛门）加 CLIP-L/14 零样本“上身赤裸 vs 穿着”（补裸背，NudeNet 没有这一类）。
  任一命中就判为裸露。CLIP 阈值 0.80 偏严，误报只会多抽一次。
- 流水线：非成人镜头每出一张图都做质检。不合格的版本留档（`take.qc.nudity=true`），不设为当前，记一行 `data/renders/qc_log.jsonl`，最多换种子重抽 2 次。3 次都不合格就报错，不改当前版本。
  `set_active` 拒绝把不合格版本设为当前（画布 API 也一样）。REPORT.md 新增“裸露质检”一列。
- 依赖（已用 `uv add` 加入）：nudenet、onnxruntime、torch（CPU）、transformers、pillow。
- ⛔ **基线 178 张还没有正式过质检**（`--qc` 没跑；它要在 CPU 上加载 CLIP，叫停后不再启动任何模型进程）。
  所以 ep01-S5 的基线版本目前仍是当前首帧。下次先跑 `uv run python tools/render_batch.py --qc`（只用 CPU，约 5 分钟，**不要和 H3 同时跑**）。
  它会撤下不合格的当前首帧；之后 `--stage image` 会自动重出被撤下的镜头。
- 校准时只看了分数。在基线上用 NudeNet 预扫，有露出类命中的非成人镜头：ep11-S1、ep16-S4、ep26-S1、ep27-S3、ep29-S6、ep40-S2，
  还有 ep03-S6、ep06-S3、ep24-S6、ep26-S2、ep27-S4、ep36-S5 是低分“男性生殖器”（可能误报）。CLIP 分数 ≥ 0.80 的约 16 个。
  被标出的图我都没有打开。

## 5. 林晚首帧锁脸（单参考编辑）⛔ A/B 未执行

- 已实现：`workflows.qwen_edit`，结构同旧系统的 qwen_image_2_1_turbo_edit.json。参考图接 `TextEncodeQwenImage21.images.image_1` 和 VAE；
  参考图先用 `ImageScale crop=center` 裁到画布比例 1088×1920，让画布和参考图比例一致（research v5）。和 t2i 共用同一个采样核心，Turbo 和 Base 都能用。
- 流水线：编译后的首帧提示词含 `【林晚】` 时（22 个非成人镜头）可以启用 `render_image(face_lock=True)`，命令行是 `render_batch --face-lock on`。
  正面提示词只在前面加一句技术说明“图1是林晚的面部参考……”，剧本原文不动。
- 来源闸门：`config/face_reference.json`（`approved_for_adult: false`，备注“待项目方确认林晚脸部来源”）。
  未批准时，成人镜头使用参考编辑会直接报错（不退回 t2i），参考编辑也不作为任何镜头的默认（`face_lock_default()` 为 False）。
  只用 `assets/characters/lin_wan/lin_wan.png`，从来没有引用过 `assets/linwan/`。
- ⛔ A/B 没跑：脚本已经准备好（`golden/facelock/ab.py`，用流水线的模型和负面词，每张图都过质检，被拦的不拼对比图），这一节还没有任何对比图。
  这个工作流**还没在 ComfyUI 上实际执行过**，只有图结构测试。另外，22 个林晚镜头里有的脸被头发遮住（如 ep01-S3），或者是背影（ep01-S5），锁脸收益有限。

## 6. 恢复后建议的顺序

1. 只重启 ComfyUI（按原命令），确认空闲内存 > 10 GB。
2. `uv run python tools/render_batch.py --qc`（只用 CPU）。
3. 先定 Turbo 还是 Base（建议 Turbo），再跑 `uv run python tools/render_batch.py --stage image --force`（不加 --include-adult）。
4. `uv run python golden/facelock/ab.py ep01-S3 ep01-S6 ep02-S1 ep02-S3 ep03-S1 ep04-S3 --seeds 2`。
5. 视频阶段单独跑，不和其他模型进程同时运行。
