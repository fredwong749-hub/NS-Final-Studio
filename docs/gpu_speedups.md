# gpu3 RTX 3090 软件提速：现状、实测与建议

> 2026-10-30，claude（speedup 任务）。所有改动只在用户态：没有重启任何 ComfyUI，没有中断任何任务，也没有碰 kernel、grub 或驱动。
> 基准程序是 `/root/build_sage/bench2.py`，它遵守 SOP 测速规则：
> - 只在调度器 `scheduler_plan.json` 把这张卡标成 unlocked 且 unassigned、并且 util≤10% 持续 60 s 时才拿 `gpu.lock.gpuN`；
> - 单次 ≤10 min；
> - 只要 S1/S2 有待办、原生队列来了任务或出现 train.lock，就立刻中止并释放。

## 1. 已安装 / 已做

| 项 | 状态 | 位置 |
|---|---|---|
| SageAttention 2.2.0（sm86，torch 2.11 cu128 源码编译，`TORCH_CUDA_ARCH_LIST=8.6`） | 已装进 `env/comfy`（`--no-deps`）。CPU 侧 import 正常，`_qattn_sm80` 和 `_fused` 两个扩展都能加载 | wheel 备份：`env/wheels/sageattention-2.2.0+sm86torch2.11cu128-cp312-cp312-linux_x86_64.whl` |
| ComfyUI-KJNodes（ab72eda） | 已克隆到 `ComfyUI/custom_nodes/`，依赖已装（color-matcher、matplotlib、mss、opencv-headless，只新增，没有升降级任何已有包）。**随 22:36 的 gpu-unlock 重启已经在三个生产实例生效**：`/object_info/PathchSageAttentionKJ` 在 8188、8189、8191 上都可用 | — |
| 安装前备份 | `/root/env_comfy_freeze_before_speedups.txt`（120 个包）。安装后 diff 只有新增，torch 2.11.0+cu128 和 triton 3.6.0 没动 | — |
| vmtouch（apt） | 已装。热模型集 120 GB 已预读进 page cache，驻留率从 60% 提到 100% | 清单：`/root/build_sage/hot_models.txt` |

**一个重要发现：现在不重启就能用 int8 注意力。** ComfyUI 0.42 自带核心节点 **`ModelAttentionBackend`**（Model Attention Backend）。在运行中的三个实例上，它的选项里已经有 `comfy kitchen attention`（comfy-kitchen 0.2.39 的 INT8 量化注意力，思路和 Sage 相同，支持 3090）。FastH3 ref2va 图已经在用它；FL2VA 和 Qwen-Image 的图目前都没用。

## 2. 实测

> 所有基准都在 **gpu-unlock 生效后**跑（见 §8）。环境：GPU1，2026-10-29 22:56–23:03（共占卡 456 s），用的是临时 ComfyUI :8199，生产实例没动。之后的窗口按 SOP 测速规则执行：只用调度器标记为空闲的卡，单次 ≤10 min，一旦有 S1/S2 待办就让出。

### 2.1 Sage 内核微基准（bf16，1×24×8192×128）
- 与 SDPA 输出的余弦相似度 **0.99991**，最大绝对误差 0.0032。
- 耗时：SDPA **7.37 ms**，Sage **6.97 ms**，只快 **1.06×**。

**原因。** 3090 解锁前，fp32 累加的张量核只有半速，fp16 累加和 int8 是全速，这正是 Sage 在 GeForce 上的优势来源（QK 走 int8，PV 走 fp16 累加）。gpu-unlock 把 SDPA/flash 的 fp32 累加路径也提到了全速（BF16 约 117 TFLOPS），Sage 的相对优势基本就没了。

### 2.2 Qwen-Image 2.1（NoctQ V4 int8 + latex_megapack 0.8 + krea2_film 0.4，1024×1472≈1.5 MP，er_sde/beta 25 步，cfg 2.5，seed 20261030）

| 配置 | 采样 s/it | Prompt 执行 s | 相对基线 | 与基线的差异 | 画质（脸 / 首饰 / 漆皮） |
|---|---|---|---|---|---|
| 基线（pytorch SDPA） | 4.27 | 113.9（含首次加载） | 1.00 | — | — |
| comfy kitchen int8（`ModelAttentionBackend`） | 4.20 | 106.6 | **1.016×** | PSNR 27.0 dB，4.96% 像素 >16 | 无退化，只有随机性细节变化（耳钉第二颗石头位置略有不同） |
| Sage auto（`Patch Sage Attention KJ`） | 4.24 | 109.1 | **1.007×** | PSNR 28.8 dB，2.67% 像素 >16 | 无退化 |
| Sage + fp16 累加（`Model Patch Torch Settings`） | 4.25 | 107.7 | 1.005× | 与 Sage **逐位相同** | 同 Sage。这证实 fp16 累加对 bf16/int8 模型不起作用 |

- **结论：在 Qwen-Image 1.5 MP 上，两种 int8 注意力的提速都在噪声范围内（≤1.6%）。** 原因有两个：一是图像 token 只有约 5.9k，耗时主要在 20B 的 int8 线性层，注意力占比很小；二是解锁后 SDPA 本身已经全速。
- 并排裁切图（脸、耳钉和项链、手套和戒指、风衣漆皮高光）：`D:\NS-Final Studio\previews\gpu_speedups\qwen_attention_crops.jpg`。原图在同一目录。

### 2.3 H3 FL2VA int8（768×1344，49 帧，20 步，seed 424242，首帧用林晚 REF-LW-01）
⏳ **还没测。** 从 03:28Z 起调度器显示 S2 的 pose-lora 在等 GPU 0/3/1，按 SOP 不能占卡。
- 已经排好、而且守规则的任务链是 `/root/build_sage/chain.sh`：窗口 A 跑基线和 Sage，窗口 B 跑 kitchen，各 ≤10 min。结果写到 `/root/build_sage/bench_h3a.out` 和 `bench_h3b.out`，视频在 `/root/build_sage/bench_out/h3a|h3b/`。
- 预期：H3 的 token 数是 Qwen 的十倍左右，注意力占比更高，所以收益会比 Qwen 大。但 §2.1 显示解锁后 Sage 内核只快 1.06×，因此**预计整段提速在 0–10% 之间**，要以实测为准。

### 2.5 ai-toolkit 训练（lin_wan_qi_v1 配置，Qwen-Image 2.1 int8 convrot，768×1024，bs1，16 张图，40 步 dry run，不采样，输出到 `/root/build_sage/aitk_out_*` 后删除）
⏳ **还没测**，原因同上。对比两组：`low_vram: true`（现行配置）和 `low_vram: false`。结果会写到 `/root/build_sage/bench_train.out`，里面有 s/it、峰值显存和是否 OOM。
- Sage 和 kitchen 都**不能用于训练**：Sage 没有 backward，kitchen int8 注意力只用于推理。ai-toolkit 的 `attention_backend` 留 `native`（SDPA；解锁后 bf16 已经全速）。

### 2.4 fp16 累加：代码层面的结论（不依赖实测）
- `torch.backends.cuda.matmul.allow_fp16_accumulation` 和 ComfyUI 的 `ck.fp16_linear` 只在**激活是 fp16** 时才起作用（见 `comfy/ops.py` 的 `_fp16_linear_wanted`）。
- Qwen-Image 2.1 和 MiniMax H3 的 `supported_inference_dtypes` 都只有 bf16/fp32，日志也显示 `manual cast: torch.bfloat16`。权重是 int8 convrot，走的是 int8 GEMM。
- **结论：在我们的管线里 fp16 累加基本不起作用，所以既不提速，也不伤画质。** 想让它起作用，得用 `ModelComputeDtype` 把模型强制成 fp16，而 Qwen-Image 在 fp16 下有已知的溢出和黑图风险。**不推荐。**

## 3. 模型加载分析（从三个实例 36 h 的 journald 日志统计，没有重启）

### 3.1 现状：加载并不是瓶颈
这版 ComfyUI 默认开着 **Dynamic VRAM + fast_disk**。日志里每次都有 `Model storage policy: fast_disk=True` 和 `prepared for dynamic VRAM loading … Staged`：权重以 mmap 方式按需从 page cache 流进显存，不是“从磁盘反序列化一整份”。三个实例共用同一份 page cache。

Qwen 出图任务的时间分解（ns-comfy@1-8189，214 个任务，取中位数；另外两个实例差不多）：

| 阶段 | 中位 | p90 |
|---|---|---|
| got prompt → 开始加载 TE（建图、各 Loader） | 1.3 s | 2.1 s |
| 文本编码（含 TE 流入显存） | 1.7 s | 4.1 s |
| 采样器内 “Model Initializing”（DiT 权重流入、LoRA patch、Comfy compiler） | 4.0 s | 14 s |
| 采样 | 79 s | — |
| VAE 解码 + 保存 | 1.2 s | 2.0 s |
| **合计** | **83 s** | — |

所以和加载相关的开销约 **5–6 s / 83 s ≈ 7%**；p90 那种 14 s 主要来自 page cache 不热或换了 LoRA。H3 任务采样器之前只有约 7 s，采样约 720 s，加载占比 **<1%**。

### 3.2 磁盘与内存
- 模型放在 `/dev/nvme0n1p3`（WD_BLACK SN7100 2TB，ext4）。O_DIRECT 实测读速 **6.0 GB/s**；page cache 读速 **8.9 GB/s**（单线程 dd）。
- 内存 503 GB：已用 25 GB，page cache 340→388 GB，可用约 470 GB。
- 热模型集（Qwen 2.1 base/turbo int8、NoctQ V4、H3 fl2va int8/w4a8、ref2va int8、两个 TE、三个 VAE、全部 LoRA，共 120 GB）预读前驻留 60%，其中 H3 fl2va int8 只有 15%。用 `vmtouch -t` 冷读 48 GB 花了 42 s（ionice idle），现在 100% 驻留。
- tmpfs **不会比 page cache 快**：tmpfs 本身就是 page cache，而且是双份占用。**不推荐。**

### 3.3 各选项的收益、代价和风险

| 选项 | 预期收益 | RAM / VRAM 代价 | 风险 / 备注 |
|---|---|---|---|
| 去掉 `--cache-none`，改为 `--cache-ram A B`（RAM 压力缓存，ComfyUI 默认模式） | 省掉 Loader 和 model 对象重建，同一 LoRA 组合连续出图时也省掉 patch：**约 1–4 s/图（2–5%）**。H3 可以忽略 | 每实例常驻 RAM 会多几十 GB（缓存 ModelPatcher 和节点输出）；VRAM 由 dynamic VRAM 管理，不会因此变多 | 三个实例看到的是同一个“系统空闲 RAM”。阈值设太小，三个实例会一起把内存吃到只剩 10 GB（默认值），所以必须调大，并配 systemd MemoryHigh/Max（见 §5） |
| `--cache-lru N` | 和上一项差不多 | 不受 RAM 压力控制，N 一大就难以预测 | 不如 `--cache-ram` 安全，不推荐 |
| page cache 预热 / 锁定（vmtouch） | 消除冷启动：20 GB 的 H3 DiT 冷读约 3.5 s（NVMe）vs 约 2.3 s（RAM）。主要作用是把 p90 的 14 s init 压回 4 s 左右 | 120 GB RAM（只是 cache，内存紧张时可回收）；用 `-l` 锁定后不可回收 | `-t` 已做。开机自动预读建议用 `-t`；`-l` 只锁 Qwen 和 H3 的核心 60 GB 左右（见 §5） |
| safetensors mmap vs 换盘 | 已经是 mmap + NVMe 6 GB/s，换盘没有收益 | — | 不需要动 |
| 同一 GPU 按模型批处理（frames lane 不在 Qwen 和 H3 之间来回切） | 每次切换省约 4–14 s 的 init，加上 H3 TE（15.7 GB）的重新流入 | 无 | 是调度层的改动，建议 scheduler 对同一张卡尽量连续派同模型的任务 |
| 预合并常用 LoRA | 省掉 init 里的 LoRA patch（估计 1–3 s/图） | 每个组合多一份 7–21 GB 的模型文件 | int8 convrot 合并后要重新量化，有画质风险，而且 LoRA 组合经常变。**不推荐**，只有固定组合大批量生产时才考虑 |
| torch.compile 缓存持久化 | 见 §4 | — | — |
| 已有的低精度 / 少步数版本 | **最大的一块**：Qwen 2.1 turbo int8、H3 8-step / 4-step turbo（`fasth3_omniref_8step`、`10Eros…8stepTURBO`、`minimax_h3_fl2v_turbo_8step/4step` LoRA）。20 步→8 步约 **2.5×** | 磁盘上已有 | 是画质决策，不是纯提速。研究笔记已记录 w4a8 在细节和快速运动上噪声最大；要上的话需要业主做 A/B |

## 4. 其他提速手段（都没做，只做评估）

| 手段 | 预期收益（3090） | 说明 / 风险 |
|---|---|---|
| **torch.compile**（KJ `TorchCompileModel*` 或 musubi `--compile`） | DiT 采样约 5–15% | 这版 ComfyUI **已经默认开着 Comfy model compiler + CUDA graphs**（日志 `Comfy model compiler graph breaks: 1`），剩下能拿的主要是 inductor 的算子融合。首次编译 1–3 min，分辨率或 LoRA 一变就重编；在 `--cache-none` 下每个任务都可能重编，得持久化 `TORCHINDUCTOR_CACHE_DIR` 才划算。和 dynamic VRAM 权重流、int8 自定义算子的兼容性要单独验证。性价比低，暂不推荐 |
| **降压 / 锁频**（`nvidia-smi -lgc 1695` 加降压曲线；Linux 下一般用 `-lgc` + `-pl` 近似） | 同等功耗下 0–5%，或同等速度下省 15–25% 功耗和温度 | 现在 350 W 已经是上限。降压主要换来温度和稳定性，不是速度。要动驱动层设置，属于系统级改动，不在我的权限内 |
| **P2P 驱动 hack**（tinygrad / aikitoravs 开源驱动补丁） | 对我们 **0%** | 每张卡跑独立任务，没有卡间通信。只有多卡张量并行训练或推理才有用。和本次 gpu-unlock 无关，不建议 |
| **fp16 累加**（`--fast fp16_accumulation` 或 KJ `Model Patch Torch Settings`） | 我们的管线约 0% | 见 §2.4：模型跑 bf16 和 int8，这个开关不起作用 |

## 5. 内存（512 GB）使用方案

### 5.1 现在已做（用户态，不打断任何东西）
- `vmtouch -t` 预读了热模型集（120 GB，现在 100% 驻留）。

### 5.2 重启时一并应用（**还没应用**，等协调者确认后交给 gpu-unlock agent 的 `/root/gpu_unlock_restart.sh`）

**(a) ComfyUI 启动参数**：`deploy/gpu3/comfy-launch.sh` 的 exec 行改成下面这样。`--cache-ram 140 200` 的意思是：系统空闲 RAM 低于 140 GB 时开始驱逐活动缓存，低于 200 GB 时驱逐非活动缓存和 pin。三个实例合起来最多吃到约 330 GB，仍然给训练和 LLM 留出 140 GB 以上。

```bash
exec "$B/env/comfy/bin/python" main.py --listen 127.0.0.1 --port "$port" --reserve-vram 1 --cache-ram 140 200 \
  --preview-method none --disable-auto-launch --output-directory "$B/ComfyUI/output/gpu$gpu"
```

- **不建议**在启动参数里加 `--use-sage-attention`（全局开启，所有工作流都受影响）。用 §6 的节点按工作流开。
- **不加** `--fast`（fp16 累加没用，其余 fast 项目没测过）。

**(b) systemd 内存上限**：用 drop-in `/etc/systemd/system/ns-comfy@.service.d/memory.conf`。mmap 进来的 page cache 也算进 cgroup，但超过 High 时内核优先回收它，不会 OOM。

```ini
[Service]
MemoryHigh=80G
MemoryMax=110G
```

**(c) 开机预热**：一个 oneshot unit，After=local-fs.target。

```ini
[Service]
Type=oneshot
ExecStart=/usr/bin/ionice -c3 /usr/bin/vmtouch -t -q -f /root/claude-kimi-ns-studio-v1/ComfyUI/models/diffusion_models/NoctQ_V4_int8_convrot.safetensors /root/claude-kimi-ns-studio-v1/ComfyUI/models/diffusion_models/qwen_image_2.1_int8_convrot.safetensors /root/claude-kimi-ns-studio-v1/ComfyUI/models/diffusion_models/minimax_h3_fl2va_pruned_int8_convrot.safetensors /root/claude-kimi-ns-studio-v1/ComfyUI/models/diffusion_models/minimax_h3_fl2va_pruned_w4a8_mixed.safetensors /root/claude-kimi-ns-studio-v1/ComfyUI/models/text_encoders/qwen3vl_8b_int8_convrot.safetensors /root/claude-kimi-ns-studio-v1/ComfyUI/models/text_encoders/qwen3vl_32b_minimax_h3_nvfp4_awq.safetensors /root/claude-kimi-ns-studio-v1/ComfyUI/models/vae /root/claude-kimi-ns-studio-v1/ComfyUI/models/loras
```

（完整清单见 `/root/build_sage/hot_models.txt`。想锁定就改成 `vmtouch -l -d`，这样会常驻一个进程，锁住约 80 GB，不可回收。建议先用 `-t` 观察一周。）

**(d) CPU 版 llama-server**（canvas 用；`tools/weita_v3/v3_finish.sh` 第 21 行。这个脚本属于别的 agent，这里只给建议）：

```bash
llama-server -m …/Qwen3.8-27B-Uncensored-Q4_K_M.gguf --host 127.0.0.1 --port 8097 \
  -ngl 0 --mlock -t 48 -tb 96 -c 98304 --parallel 1 --jinja
```

- `--mlock` 锁住 17 GB 的权重，加上约 98k 上下文的 KV（几 GB）。
- EPYC 7K62 是 48 物理核：生成阶段用 `-t 48`，prompt 阶段用 `-tb 96`。
- CPU 生成受内存带宽限制，提速有限；用 `--mlock` 主要是为了避免被换出后首 token 卡顿。

### 5.3 训练（musubi-tuner，`tools/lw_lora/train.sh`）
- 现在已经在用 `--blocks_to_swap 36 --block_swap_h2d_only` 往 RAM 卸载，latent 和 TE 也已经缓存（`cache.sh` 写的 safetensors 文件，读的时候走 page cache）。
- **建议加 `--use_pinned_memory_for_block_swap`**（musubi 支持）。用 pinned RAM 做 H2D 拷贝，带宽高于 pageable 内存；在 block swap 是瓶颈的步骤上，预计每步快 10–20%（未实测）。代价是额外 pin 住约 15 GB RAM，对 512 GB 来说没问题。
- 数据集放 tmpfs：缓存文件已经在 page cache 里，**没有收益**。
- 更大 batch：瓶颈在 24 GB 显存，不在 RAM。可以试 `SWAP` 加大、batch 翻倍，但要实测显存。
- **SageAttention 不要用于训练**：它没有 backward。

## 6. 管线如何按工作流开启（不重启）

**Qwen-Image 出图 / 编辑**（UNETLoader → LoraLoaderModelOnly × N →【插这里】→ BasicScheduler、CFGGuider 的 model 输入）：
1. **现在就能用（不用重启）**：核心节点 `ModelAttentionBackend`，`attention="comfy kitchen attention"`。API：
   ```json
   {"class_type": "ModelAttentionBackend", "inputs": {"model": ["<最后一个LoRA>", 0], "attention": "comfy kitchen attention"}}
   ```
2. **现在也已可用**（KJNodes 已随 22:36 的重启加载）：`PathchSageAttentionKJ`（显示名 “Patch Sage Attention KJ”）。在 3090 上，`sage_attention="auto"` 会走 `sageattn_qk_int8_pv_fp16_cuda`。API：
   ```json
   {"class_type": "PathchSageAttentionKJ", "inputs": {"model": [...], "sage_attention": "auto", "allow_compile": false}}
   ```
3. `ModelPatchTorchSettings`（fp16 累加）：**不要加**（§2.4）。

**H3 FL2VA / ref2va**（UNETLoader →【插这里】→ BasicGuider、BasicScheduler）：
- `ns-studio/adapters/video/comfy_h3/workflow.py` 的 FastGraph 已经支持 `attention_backend="comfy kitchen attention"`（目前只在 ref2va 两段式图里用）。要推广到 FL2VA，就在 `build_workflow` 里对所有模式插 `ModelAttentionBackend`（节点号 151）。
- 重启后也可以换成 KJ 的 `PathchSageAttentionKJ`，或 `MiniMaxH3MemoryEfficientSageAttentionPatch`（H3 专用，省峰值显存）。

**全局启动参数**（只有约定重启时才用）：`--use-sage-attention` 或 `--use-ck-attention`。不推荐，因为会影响 VAE 以外的所有模型，没法按工作流回退。

## 7. 建议
1. **首尾帧（Qwen-Image 出图）：什么都不用加。** 实测 kitchen int8 快 1.6%，Sage 快 0.7%，都在噪声范围内。画质没有退化，但也没有收益，不值得改图。gpu-unlock 已经让这条线的线性层和注意力都拿到了全速 BF16（§8）。
2. **视频（H3）：先不改**，等 §2.3 实测。如果 Sage 或 kitchen ≥10% 并且脸部没有退化，就在 UNETLoader 之后插 `PathchSageAttentionKJ(auto)`，或者插 `ModelAttentionBackend(comfy kitchen attention)`。两者现在都**不用重启就能用**，因为 KJNodes 已经随 22:36 的重启加载了。FastH3 ref2va 现有的 kitchen 节点保持不动。
3. **训练：不开任何注意力替换。** ai-toolkit 保持 `native`；musubi 保持 `--sdpa`，再加上 `--use_pinned_memory_for_block_swap`（§5.3）。`low_vram` 怎么设，等 §2.5 的数据再定。
4. fp16 累加：**不开**。实测与 Sage **逐位相同**，对 bf16/int8 模型不起作用。
5. 加载：只占约 7%（Qwen）和不到 1%（H3）。重启后 page cache 是冷的，我已经重新预读了一次：120 GB 用了 71 s，现在 100% 驻留。最值的两件事是 page cache 预热（已做）和下次重启时把 `--cache-none` 换成 `--cache-ram 140 200` 并加 systemd MemoryHigh/Max，预计每张图省 1–4 s。
6. torch.compile、降压、P2P：暂不做。
7. 真正的大头是步数（turbo 和 8-step 模型约 2.5×），这需要业主做画质决策。

## 8. gpu-unlock（GeForce 张量核半速限制解除，2026-10-29 22:36 起生效）

**来源与审计。** https://github.com/Zagitta/gpu-unlock（GPL-2.0），固定在 commit `7eb51bccae0a0b7e599e084d971170e9a1e82d0c`，源码在 gpu3 `/root/gpu_unlock_src`。装的是 Debian 包 `gpu-unlock-dkms` + `gpu-unlock-firmware` 2.0.0（DKMS，已为 6.8.0-138 和 6.8.0-79 编译）。审计结果是**干净的**：
- 网络：只从 download.nvidia.com 下载 610.43.03 驱动包，用来提取固件。强制 HTTPS，上限 1 GiB。仓库**没有固定哈希**，只校验版本号和结构，这一点算小缺点。
- 内核模块：没有文件读写、usermode helper、socket、kallsyms、kprobe/ftrace、netlink 或改 cr0 / 系统调用表的代码。固件走标准的 request_firmware，没有混淆的二进制块。参数只有 `targets` 和 `resume`。命令行里没有 `gpu_unlock.targets=` 时它什么都不做。
- 写入范围：只有 DKMS 源码、`/usr/lib/firmware/gpu-unlock/`、initramfs-tools / dracut drop-in（含 init-top 脚本，用来解决 issue #171/#11：3090 上 nvidia 先加载导致 -EBUSY），没有额外持久化。不改驱动，不刷 VBIOS。
- 相关 issue：#137 报告过 3070 上 5 次解锁启动有 1 次死机。没找到 580.x 的阻塞问题。

**目标（显式 PCI 地址，绝不用 all）。** 内核参数是 `gpu_unlock.targets=0000:01:00.0,0000:41:00.0,0000:c1:00.0`，即 GPU0/1/3。**GPU2（0000:81:00.0）有故障，不在目标里**，dmesg 中没有它的任何 gpu_unlock 记录。重启后 dmesg 显示三张卡都是 `gpu_unlock: unlocked`（stage=handoff ret=0）。4 张卡全部可见，驱动 580.196.07 正常。

**实测（重启后、恢复任务前，每张卡单独跑，`/root/gpu_unlock_bench.py`，8192² matmul，torch 2.11 cu128）：**

| GPU | BF16 TFLOPS | FP16 TFLOPS | TF32 TFLOPS | 确定性测试 sha256 |
|---|---|---|---|---|
| 0 | 116.9 | 112.0 | 63.6 | e66ff304…b8d18 |
| 1 | 116.3 | 110.5 | 63.3 | e66ff304…b8d18 |
| 3 | 118.8 | 114.2 | 64.2 | e66ff304…b8d18 |

- 解锁前没有本机基线：当时三张好卡都满载，GPU2 有故障不能用。所以对照的是 3090 官方规格，FP16/BF16 稠密、FP32 累加约 71 TFLOPS（作者实测 75→125）。**BF16 约 +64%**，TF32 约是规格 35.6 的 1.8 倍。INT8 / FP8 / 解码不受影响（作者说明）。
- 确定性测试：固定 seed 的 BF16 matmul+tanh 链，三张卡输出的 sha256 **逐位一致**（`e66ff3048ea73b647f0bcb2a806d04cd4b5c44e4f77cb793c366346e541b8d18`）。没有解锁前的哈希可比，只能做卡间一致性检查。原始数据在 `/root/gpu_unlock_bench_after.jsonl`。

**回滚。** 运行 `/root/gpu_unlock_revert.sh`（从 `/etc/default/grub` 删掉参数、update-grub、purge 两个包、`update-initramfs -u -k all`），然后重启，再按 `/root/units_before_unlock.txt` 恢复任务。备份：`/root/grub.default.pre-unlock.bak`、`/root/initrd.img-6.8.0-138-generic.pre-unlock.bak`。重新启用用 `/root/gpu_unlock_apply.sh`。

**重启后恢复的任务（`/root/gpu_unlock_restart.sh`，ExecStart/环境与重启前一致）：**
- 开机自启：nsfs-canvas-bridge。手动启动：ns-comfy@0-8188 / @1-8189 / @3-8191（flag 不变）。
- weita-v3-llm：GPU0，`-ngl 99`，`CUDA_DEVICE_ORDER=PCI_BUS_ID CUDA_VISIBLE_DEVICES=0`，端口 8097。
- weita-v3-finish3（续跑 v3_finish.sh）、lend-gpu0-after-v3c、ns-sched（scheduler_mode 保持 dry-run）。
- jwl-pipeline、wardrobe-gen（从 hh12clear foot_14 续上）、wardrobe-pipe-heels、wardrobe-pipe-clothes、lw-lora-pipeline、nsaudio-watch。
- 锁文件：删掉旧 pid 的 gpu.lock，gpu.lock.gpu0 改写为新的 llama pid。lend.gpu0（weita-v3-llm）和 lend.gpu3（wardrobe）没动。
- **up4k-test 启动即失败**：输入 `data/run/weita/ep01/clips/ep01s4.mp4` 在 21:42 已被移到 superseded（ep01 被替换），与重启无关，没有改它。
- 没有启动 weita-frames* / weita-ep01b / weita-series。§5.2 的 ComfyUI `--cache-ram` / 内存 drop-in **没有应用**，等协调者决定。
