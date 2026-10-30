# 生产工作流与分工（项目方 2026-10-30 对齐，唯一准绳）

> **现行（项目方 2026-10-30 夜，取代下面所有“Qwen 写作 / GPU1 = Qwen”的说法）**：**撤下千问语言模型**。项目方原话：“现在整体反馈不太好，我可能会不用千问了。我打算直接在那边做一个 Docker，调度外部的 API 来进行写作和 Lora 训练的大语言模型，这样可以省出一张 3090 的显卡。”
> - 写作（剧本、分镜、H3 提示词）与 LoRA 训练所需的大语言模型 → gpu3 上新建的 **LLM 网关 Docker**，调用**外部 API**（DeepSeek、MiniMax 等，按画布「模型与 API」页配置，见 docs/canvas-ui-spec-v3-merge.md §8）。gpu3 本地 Qwen 写作模型（:8098）与 qwen-agent 下线；画布剧本创作页不再默认千问。
> - **GPU1 释放**，与 GPU0、GPU3 一样用于 Image 2.1 / H3 / LoRA 训练（GPU2 坏卡不变）。
> - **千问 Image 2.1 Turbo（出图模型）保留**：画布“改了就重出”的链路直接把参考图 + 提示词送 gpu3 的 ComfyUI（Image 2.1 Turbo）出图，结果回画布，不满意再点；视频同理（MiniMax H3：审片 → 改参数 / 提示词 → 重渲）。
> - **内容检测（含成人检测）暂时跳过**（项目方原话：“之前一直有的‘成员问题检测’，现在可以暂时跳过”）；露骨红标的人工标记仍按原样处理，直到项目方另行决定。
> - 撤换前已在 Qwen 信箱里的任务、已训练的 LoRA（如 lin_wan_qi_v1）保留可用。gpu3 上停 Qwen 服务、腾 GPU1 属于有影响的操作，按项目方确认后执行。

> **现行（封板修复 2026-10-30 晚，REQUIREMENTS G8）**：**写作 = gpu3 本地 Qwen（:8098）**。项目方先让 abliteration.ai 写（原话“qwen写作部分交给abliteration来做”），后改回（原话“还是用qwen写吧，api那个太贵了”）：abliteration 太贵、已放弃，只保留为可选后端。入口：画布「剧本创作对话框」#/script-chat（fredw-c8，provider=qwen）与 `tools/qwen_repair_loop.py`；规则文件 `config/script_chat_rules.md` + 格式契约不变。
> **S3 首尾帧（现行）**：项目方定“系统自动补”——首尾帧提示词由编译器按规则从剧本拼出并自动补规格词（触发词含 lnwan_qi、材质 / 鞋跟 / 脚趾甲、特写 / 暗场 / 安全镜，写作者已写过的不重复），gpu3 渲染器（weita_series）出帧；下文 §2 S3 / §4 的 `frames.json` 透传方案**作废**。
> **Qwen Docker 现在主要做 LoRA 训练与 Blender**；出图队列 qwen-image-api（:8100）保留可用。Claude 的职责不变：只写系统、不写不评内容。
> 历史：2026-10-30 下午曾把排在 Qwen 信箱里的 34 个剧本写作任务撤到 gpu3 `mailbox/cancelled_fredw92/`（保留可恢复）。

> 项目方原话要点：claude 负责系统开发、负责 minimax 规则的画布；采用**首尾帧提示词**制造；claude 负责把 qwen 写的剧本和提示词给 minimax h3 生产，**claude 不做任何内容检测，只负责生产代码交付**。qwen 负责内容创作（剧本、镜头提示词，必须满足 minimax h3 提示词格式），还负责**首尾帧图片提示词**（基于 qwen 的剧本，严格遵守 image 2.1 turbo 格式），并**调度 image 2.1 turbo 生成首尾帧**，调度剧本提及的人物 / pose / 衣服 / 指甲 / 高跟鞋 lora 到 image 2.1；这些 lora 需要时也调度到 minimax h3。**gpu1 一直给 qwen 作语言模型；gpu0 和 gpu3 可随意给 qwen 和 claude 调用；现在 gpu 主要把 lora 做完。**
>
> 相关：`docs/REQUIREMENTS.md` G1–G7、`docs/qwen_comms.md`（信箱接口）、`docs/qwen_writing_contract.md`（剧本格式契约）、`docs/SOP_production.md` §9A（H3 官方规范）。

## 1. 分工

| 方 | 负责 | 不做 |
|---|---|---|
| **写作方**（~~Qwen：`qwen-llm` GPU1 常驻 + `qwen-agent`~~ → 2026-10-30 夜起：gpu3 LLM 网关 Docker 调外部 API） | 剧本、分镜、H3 视频提示词（符合 §9A）、**首尾帧图片提示词**（Image 2.1 Turbo 格式）、**调度 Image 2.1 Turbo 出首尾帧**、选用并调度 LoRA（人物 / pose / 衣服 / 指甲 / 高跟鞋）到 Image 2.1 与（需要时）H3、LoRA 训练与评测、Blender、爬虫、**一切内容上的检查、挑选与返工** | — |
| **Claude 系统**（画布 = fredw-92；gpu3 基础设施 / 信箱 / Docker = fredw-d9） | 系统代码：画布（MiniMax H3 规则）、信箱收发、剧本**格式**校验与原样导入、H3 视频生产（用 Qwen 的提示词与 LoRA 清单原样执行）、后期装配、GPU 调度与锁、技术检查（格式、字段、尺寸、帧数、哈希、版本、同步） | 不写、不改、不润色内容；**不做内容检测**（不判断像不像、好不好看、对不对剧本） |
| **项目方** | 各确认关口拍板（剧本采纳、母版 / 样片、成片验收） | — |

## 2. 生产流（每集）

| 阶段 | 谁 | 输入 → 输出 | 系统闸门（只查格式 / 技术） |
|---|---|---|---|
| S1 剧本 | Qwen 写；Claude 收、校验、导入 | 信箱 `kind:script` → `script.md`（格式见 qwen_writing_contract.md） | `tools/validate_qwen_script.py`：不过 → 报错原文作为新任务发回 Qwen；过 → 项目方在画布点「导入」 |
| S2 LoRA | Qwen 训练 / 选择；Claude 登记 | `kind:lora` → `<name>.safetensors` + README（触发词、底模、用途：image / h3） | 文件存在、sha256、登记表 `LORA_REGISTRY.json` |
| S3 首尾帧 | **系统**（编译器自动补规格词；gpu3 weita_series 出帧）——项目方 2026-10-30 定“系统自动补” | 剧本 img / motion → 编译器首帧 / 尾帧提示词（触发词含 lnwan_qi、规格词去重）→ 每镜首帧、尾帧 | 尺寸 768×1344（9:16）、文件齐全、首尾同一镜号、哈希入账；不看画面内容（~~Qwen 写图片提示词 + `frames.json`~~ 作废） |
| S4 视频 | **Claude 执行 MiniMax H3**（gpu3） | 剧本 `**H3提示词**` 原样 + S3 的首尾帧；LoRA 按剧本触发词 + `LORA_REGISTRY.json`（accepted） | §9A 机检（格式、帧数网格、对齐句）、首尾帧与视频同源记录 |
| S5 成片 | Claude 装配；Qwen 内容复核；项目方验收 | 片段 + 声音 + 配乐 → `epXX_final.mp4` | 时长、响度、封装参数；内容返工意见只来自 Qwen / 项目方 |

## 3. GPU

| 卡 | 用途 |
|---|---|
| GPU1 | ~~Qwen 语言模型常驻（:8098）~~ → 2026-10-30 夜撤下千问后释放，与 GPU0 / GPU3 同用于 Image 2.1 / H3 / LoRA 训练 |
| GPU0、GPU3 | Qwen 与 Claude 都可调用（Image 2.1、LoRA 训练、H3 视频、Blender）；按 `gpu.lock` / `train.lock` 在任务边界接手，不杀进程 |
| GPU2 | 坏卡，永不使用 |
| **当前优先级** | **先把 LoRA 做完**（林晚出图 LoRA → 林晚视频 LoRA → 衣服 / 高跟鞋 / 指甲 / pose） |

## 4. ~~首尾帧交付格式（Qwen → Claude，`frames.json`）~~ —— 作废（封板修复 2026-10-30：S3 改为系统自动补规格词的编译器路径，见开头“现行”）

```json
{
  "project": "weita", "episode": 1,
  "shots": [{
    "shot": "ep01-S1",
    "first": {"file": "ep01/S1/first.png", "prompt": "<Qwen 写的 Image 2.1 Turbo 提示词，原样>", "loras": [["lin_wan_qi_v1", 1.0]], "seed": 0},
    "last":  {"file": "ep01/S1/last.png",  "prompt": "<原样>", "loras": [], "seed": 0},
    "h3_loras": [["<H3 用的 LoRA 名>", 1.0]]
  }]
}
```
Claude 只读这些字段、检查文件与尺寸，原样用于 H3；不改提示词、不重选图。

## 5. TODO（分工与调度）

### Claude · 画布 / 生产（fredw-92）
- [x] 画布 H3 规则面板、§9A 机检、配乐进 H3、镜头行 / 查看器 / 版本条、资产角色卡
- [x] Qwen 信箱代理 + 剧本取回 → 校验 → 返修 → 项目方确认导入
- [x] Qwen 写作格式契约 + 校验器 + 逐镜格式返修循环（v3 → v3.1，进行中）
- [x] ~~**编译器改为透传**~~（作废：项目方 2026-10-30 定：系统自动补，不透传——首尾帧都按规则补规格词，写作者已写过的同一条目不重复加；fredw-5c 已实现）：首帧 / 尾帧提示词 = Qwen 的 Image 2.1 提示词原样；去掉 Claude 侧追加的内容性文字（DNA 锁、徕卡措辞、鞋跟 / 漆皮 / 美甲条目、纠正器条目、风格后缀）——这些规则改由 Qwen 在写提示词时遵守（格式契约里列出）
- [x] ~~**S3 接入**：画布导入 Qwen 的 `frames.json` + 图片为镜头版本~~（作废：S3 走系统自动补的编译器路径）
- [ ] **S4 H3 执行器**：读系统首尾帧 + 剧本 H3 提示词原样出视频（gpu3 GPU0/3，按锁调度），记录首尾帧哈希与提示词哈希
- [ ] **内容检测撤出 Claude 侧**：人脸相似度、发色、服装漂移、VLM 核对剧本、裸露以外的画面判断，改为只报数值给 Qwen 或关闭阻断；Claude 闸门只保留格式 / 尺寸 / 帧数 / 哈希 / 版本 / 同步（`packages/qc` 与渲染器评分相应调整）
- [ ] 林晚视频 LoRA 在出图 LoRA 交付后切到 GPU0（项目方已指示）

### Claude · gpu3 基础设施（fredw-d9）
- [x] Image Docker（ComfyUI + Qwen Image 2.1 Turbo，按需在 GPU0/GPU3 启动；image_docker.sh :8190 + 出图队列 :8100，GPU3 实测通过）+ 接口写进 qwen_comms.md §6
- [x] Qwen :8098 迁到 GPU1（现行 G3：GPU1 = Qwen 语言模型常驻）
- [ ] gpu3 渲染器的研究补丁（docs/research_adoption.md §三 G1–G8，只限参数 / 技术项）

### Qwen（Docker）
- [ ] 剧本：rules_v2 逐集重写（画布「剧本创作」，provider=qwen）。历史：信箱任务 20261030T022135-b2c39613（v3 的 8 集重写 + 80 个 H3-D7 冲突镜头）已被 rules_v2 流程取代
- [x] ~~每镜首尾帧图片提示词 + 调度 Image 2.1 出图 → 交 `frames.json`~~（作废：S3 由系统自动补规格词）
- [ ] LoRA：林晚出图 / 视频验收样图评测；衣服、高跟鞋、指甲、pose LoRA 训练（GPU0/GPU3 空闲时）
- [ ] 内容复核：首尾帧、视频的内容问题（像不像、对不对剧本）由 Qwen 判断并发返工任务

### 项目方
- [ ] 采纳剧本稿（画布「导入」）
- [ ] 林晚出图 / 视频 LoRA 样图验收
- [ ] 第一集样片参数锁定
