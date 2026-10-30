# 乳环 / 阴环 Blender → LoRA → 林晚画面（2026-10-31）

> 项目方：Blender 生成更多乳环、阴环；Claude 停止的 Blender 细节 LoRA 补上；在 gpu3 完成；补充更多林晚性感画面。
> 本文记录数据、脚本、GPU 和当前进度；代码/脚本在 gpu3 的 `ns-studio/data/train/jewellery/`，不在本仓库。

## 1. 已有资产

- Blender 4.2.9 + MPFB2，在 `/root/claude-kimi-ns-studio-v1/env/blender/`。
- 场景生成：`data/train/jewellery/tools/jwl_scene.py`（MPFB 成人身体；乳环/阴环几何；每张 `beauty.png` / `nojewel.png` / `mask.png` / `depth.png` / `meta.json`）。
- Photoreal：`jwl_photoreal.py`（NoctQ V4 img2img；只给无珠宝图，再把 Blender 珠宝按 alpha + 接触阴影贴回，件数不漂移）。
- 数据集：`jwl_dataset.py`（只收 `all_pieces_visible` + 对齐成功的图；生成 caption/manifest）。
- 训练：`jwl_train_config.py`（ai-toolkit，NoctQ V4 int8，rank 16，768×1024）+ `jwl_train_config` 的 sample prompts。
- 登记：`lora_registry.py` → `nsfs_mirror/data/renders_gpu3/LORA_REGISTRY.json`。

## 2. 概念与触发词

| 概念 | 内容 | 触发词 | 已有场景 |
|---|---|---|---|
| `nprng2` | 左右乳头各一枚钢环（captive bead / stirrup + bells） | `nprng2` | 重新生成中 |
| `lbrng9` | 左大阴唇 4 + 右大阴唇 4 + 阴蒂包皮 1，共 9 枚 | `lbrng9` | 重新生成中 |
| `lbrng9_beads` | 9 枚阴环各挂 1 颗 5mm 不锈钢球 | `lbrng9_beads` | 重新生成中 |

规格来源：`script play lib/为他而骚（剧本和镜头）v2.md` 头部（乳环 2 枚；阴环左 4 右 4 阴蒂 1；每环 5mm 钢珠）。

## 3. 本轮执行（gpu3）

### 3.1 Blender 场景

- `nprng2`：`--start 0 --count 30`（cbr）+ `--start 30 --count 30 --variant stirrup_bells`，64 samples。
- `lbrng9`：`--start 0 --count 60`，64 samples。
- `lbrng9_beads`：`--start 0 --count 60`，64 samples。
- 输出：`data/train/jewellery/render/<concept>_<idx>/`。
- 每个场景 `meta.json` 记录 `all_pieces_visible`、`counts`、`variant`、`pose`、`framing`、`lighting`。

### 3.2 Photoreal

- `jwl_comfy.py` 的 `wait_idle_gpu` 已允许 GPU 0/1/3（原来只允许 GPU1）；GPU2 坏卡不用。
- `jwl_photoreal.py --render render --concept <c> --tag v1 --gpu <0|3>`。
- 选择空闲 GPU：GPU0/3 目前被 H3/其他任务占用时自动等；不杀进程。
- 输出：每个场景 `final_v1.png`，`meta.photoreal.v1` 记录 GPU、denoise、LoRA、对齐结果。

### 3.3 数据集与训练

- `jwl_dataset.py --render render --concept <c> --tag v1 --out <c> --max 60`
- `jwl_train_config.py <c> --steps 1200`（pilot）/ 2000（正式）
- 训练：`env/aitk/bin/python run.py configs/jewellery_<c>_v1.json`，`CUDA_VISIBLE_DEVICES=0`（GPU0 空时；GPU1 留给 Qwen，GPU2 不用）。
- 完成后复制到 `ComfyUI/models/loras/jewellery_<c>_v1.safetensors`，写 sha256 与 `LORA_REGISTRY.json`（status=training，待样图审核后 accepted）。

### 3.4 林晚画面

- 训练完成后用 `jwl_comfy.t2i_graph` 加载 LoRA，生成 768×1024 / 768×1344 的胸部、半身、骨盆、全身多姿势图；输出 `data/train/jewellery/showcase_<c>/` + contact sheet。
- 也可复用 `hs_showcase.py` 的 Blender 相机/姿势库 + 现有 `showcase2` 4 个姿势，追加乳环/阴环变体。

## 4. 当前进度（2026-10-31 01:xx JST）

- Blender：`nprng2` 25+、`lbrng9` 27+、`lbrng9_beads` 10+ 个场景已生成（后台继续）。
- Photoreal：`nprng2` 9 张 `final_v1` 已完成；`lbrng9` 已启动；GPU 0/3 被 H3/其它队列占用时排队。
- LoRA：配置已生成（`configs/jewellery_{nprng2,lbrng9,lbrng9_beads}_v1.json`），等待数据集与 GPU 空闲后训练。
- 样图：`previews/jwl_nprng2_0000_final.png`、`0009_final.png` 已拉回本机供检查；乳环清晰，身体/光照可继续用 LoRA 精修。

## 5. 注意

- GPU1 是 Qwen 写作模型；训练/出图默认避开，除非它空闲且不抢模型。
- GPU2 坏卡永不使用。
- 场景是合成的成年身体；不是真人。
- 这套是**内容数据/LoRA**，不改 audit/debug 代码；等 audit 稳定后再与解锁流程合流。
