# gpu3 上 Claude 这一侧在跑什么（给另一个开发 agent 和项目方看）

> 2026-10-30 写。项目方要求两个 agent 共同开发、互相监督，并且一切按 `D:\NS-Final Studio`（PLAN.md、script play lib）来做。这份文件说明我这边在 gpu3 上的东西，避免重复和抢卡。

## 机器约定（gpu3）

- **GPU 2 硬件故障**：显存超过约 11 GB 就会静默算错（`/root/README-GPU2-FAULTY.txt`）。只用 GPU 0、1、3；`train_both.sh` 这类脚本请勿把 `CUDA_VISIBLE_DEVICES` 设成 2。
- 每张好卡一个 ComfyUI：gpu0 `:8188`、gpu1 `:8189`、gpu3 `:8191`（systemd `ns-comfy@*`），模型在 `/root/claude-kimi-ns-studio-v1/ComfyUI/models`。
- **分卡（2026-10-30 起）**：GPU 0、GPU 3（ComfyUI `:8188`、`:8191`）只给出片；GPU 1（`:8189`）给所有训练和训练数据生成，顺序是首饰 → 林晚 → 鞋服。占 GPU 1 前取 `/root/.local/state/NS-Studio/gpu.lock.gpu1`，训练期间另写 `train.lock.gpu1`；已有锁就排队。
- huggingface.co 在 gpu3 上 DNS 被劫持，下载走 `hf-mirror.com`，并用 huggingface.co API 的 sha256 校验。

## 正在做的

| 事项 | 位置（gpu3） | 状态 |
|---|---|---|
| 《为他而骚》ep01 微型测试 → 锁定 → ep02–ep60 连跑 | `ns-studio/data/run/weita/`，状态行 `STATUS.log`（PLAN/纠正器格式） | ep01 A/B 进行中 |
| 首饰 LoRA（乳环 `nprng2`、阴环 `lbrng9`、珠串 `lbrng9_beads`），Blender + MPFB 合成数据 | `ns-studio/data/train/jewellery/` | 渲染样张中 |
| 鞋/服装 LoRA（`hh12clear` 透明高跟优先，漆皮束腰/捆绑/风衣/乳胶衣） | `ns-studio/data/train/wardrobe/` | 数据集构建中 |
| 林晚 H3 LoRA（`lnwan01`，musubi-tuner） | `ns-studio/data/train/lin_wan_h3/` | 数据集生成中 |
| 难镜头服务（Blender 摆姿势 → ControlNet 首帧；常用亲密构图训成 LoRA） | `ns-studio/data/run/weita/HARD_SHOTS.jsonl` | 刚开始 |
| 4K 成片（QA 通过后最后一步：SeedVR2 3B → 2160×3840，H.264 + HEVC10），触发：STATUS.log 最后一行 ✅ 或 `QA_PASS` 标记 | `ns-studio/scripts/upscale_4k.py`，说明 `docs/upscale_4k.md` | 已建成；GPU 测试排队中（只用借出/空闲的 GPU 3/0，每镜一锁） |

LoRA 注册表：`ComfyUI/models/loras/LORA_REGISTRY.json`（触发词 → 文件 → 强度）。交付：`D:\NS-Final Studio\assets\{piercing,high heels,clothes,poses}\`；预览：`D:\NS-Final Studio\previews\`。

## 已验证的结论（可直接用）

- 锁首帧用 **H3 FL2VA int8**（`minimax_h3_fl2va_pruned_int8_convrot`），768×1344，10 秒 = 243 帧；Ref2VA 系（PRISM、Singularity）锁帧弱。
- H3 会把**双引号里的文字画成字幕**：对白用 `(S1) says: <d>[Chinese] …</d>`，人物用 (S1)/(S2) + 外貌描述，不写人名；ComfyUI 的 minimax 分词器注册了 `<d>`/`</d>`。
- 林晚身份参考只用**脸部裁切**（项目方的蓝发特写），否则参考图里的粉裙、草莓项链会串进每个镜头。
- 剧本已按项目方要求改为 **12cm 透明细高跟**，并写入 LoRA 触发词（`script play lib` 里的剧本与 image 提示词，原文备份 `*.bak-20261029*`）。
- 训练数据只用合成图或无人的商品图；带真人的照片只当款式参考，不直接训练。

## 和这边 `training/`、`tools/render_batch.py` 的关系

2026-10-30 与 fredw-d9 会话约定的分工：

- **fredw-d9 负责**：界面 `apps/web`、API `services/api/ns_api`（:8800）、`services/agent`（导入、编译、造型库）、`data/looks`（造型库唯一来源）、`data/renders`（带版本的 takes 布局）、`tools/render_batch.py`、笔记本本地 ComfyUI。
- **我这边负责**：gpu3 全部生产（出片、LoRA 训练、QC）、`services/canvas_api`（只做 gpu3 桥接，以后并入 ns_api）、本文件、`docs/qa_issues.md`、`docs/canvas*.md`、LoRA 交付到 `assets/`。
- **gpu3 产物只写到 `data/renders_gpu3/epXX/SN/`**，绝不写 `data/renders/`；fredw-d9 会把它导入画布作为 source=gpu3 的 take。
- **重渲队列**：`data/renders_gpu3/rerender_queue.jsonl`（ns_api 追加，格式 {shot, version, scope frame|video|both, keep_seed, overrides}），gpu3 处理后回写 `data/renders_gpu3/rerender_done.jsonl`。
- **造型库**：在项目方审阅 `data/looks` 之前，两边都不把它注入提示词；gpu3 暂用剧本原文 + 装饰码。
- 黑漆皮高跟 `nsheels` 归 fredw-d9；透明高跟 `hh12clear` 和其余 LoRA 归我这边。

## 更新 2026-10-29 17:10 UTC（weita 系列渲染器）

- **已锁定**：`ns-studio/data/run/weita/PIPELINE_LOCKED.md/.json`。量产视频 = H3 FL2VA int8 + LightX2V FL2V 8 步 v1.0（shift 6/3，euler），768×1344，243 帧，约 28 分钟/镜；升级重试 = base 20 步（约 64 分钟/镜）。首帧 = Qwen-Image 2.1 Turbo（🔴/露体镜用 NoctQ V4），texture-fix VAE，脸部裁切做身份参考，项目方画面风格后缀已加。
- **编排器**：systemd `weita-series-r3`（`ns-studio/data/run/weita/series.sh run --from 1 --to 60`），只用 gpu0、gpu3；遇到 `train.lock.*` / `GPU_IN_USE_*.json` 自动避让；gpu1 不提交。状态行 `STATUS.log`，难镜 `HARD_SHOTS.jsonl`，阻断 `BLOCKED.jsonl`，暂缓 `HELD.jsonl`，连续性 `continuity_ledger.json`。
- **暂缓**：林晚面部参考来源待项目方确认，含林晚的成人/露体镜（🔴集或画面有身体/首饰）不渲染（目前 175 镜，16 集可完整出片）。`ns-studio/data/run/weita/face_reference.json` 改为 `approved_for_adult: true` 后自动补跑。
- **画布产物**：gpu3 `/root/claude-kimi-ns-studio-v1/nsfs_mirror/data/renders_gpu3/epXX/SN/`（takes.json + takes/image_NNN.png / video_NNN.mp4 / video_NNN_last.png，以及 frame.png / video.mp4 / last.png / compiled.json / status.json）。重渲队列 `renders_gpu3/rerender_queue.jsonl`（nsfs_canvas.rerender/v1），进度 `rerender_events.jsonl`。笔记本镜像 `D:\NS-Final Studio\data\renders_gpu3\`（从不写 `data\renders\`）。
- **本地视觉检查**：ComfyUI `TextGenerate` + Qwen3-VL 8B（文本编码器）回答透明高跟 / 乳环数 / 钢珠数 / 人数（不算倒影）/ 衣着完整 / 朝向。
- **导入器对比**：nsfs `data/import/script_v2.json` 与 weita 解析器的 360 个镜号、img/motion/sound 原文一致；nsfs 对白拆分有误（例：ep02s2 两句合一、引号内按“／”拆开、舞台说明当台词、ep53s5/ep56s1 说话人成了“接通）（她”），系列渲染器用 weita 解析结果，详见 gpu3 `nsfs_mirror/data/import/parser_diff.txt`。
