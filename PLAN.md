# NS-Final Studio · 自动化短剧生成系统建设计划

> 依据：`script play lib/` 下的剧本、image 提示词、提示词纠正器、`design md file.md`（v1 设计）和 `design v2 research.md`（模型栈调研）。
> 本计划回答三件事：**做什么、按什么顺序做、每一步怎样算完成**。技术细节和来源见两份设计文档，这里不重复。

---

## 1. 需求复述（从资料中提炼）

| 需求 | 资料依据 | 系统对应 |
|---|---|---|
| 输入剧本、镜头分镜、图生视频脚本 | 剧本 v2：60 集 × 6 镜 × 10 秒，每镜 img / motion / sound / 对白 / 🎙 | 导入器 + 分镜表 |
| Agent 自动识别每集人物资产 | 角色锁（林晚/顾沉/陈宇/Alex/Ryan/Kai/Leo）、REF-LW-01..03、装饰锁 D0–D10、场景锁 SK-* | 解析器 + abliteration.ai 抽取 Agent |
| 衣服库（上传参考图）、鞋、美甲、美发、身材等风格管理 | 剧本中的漆皮束腰、黑丝、高跟鞋、妆面变化等 | 资产衣橱（插槽化、版本化） |
| 基于剧本和图片的画布 | 小云雀式资产画布 | React Flow 画布：资产节点 + 镜头节点 + 参考连线 |
| Image 2.1 Turbo 出首帧，MiniMax H3 出视频 | image 提示词文档 AGENT-1 / AGENT-2 | Qwen 2.1（ComfyUI）+ H3 FL2VA / Ref2VA |
| 多 GPU 阵列渲染 | — | 每卡一个 ComfyUI + 模型亲和调度 |
| 画面接近实拍、去 AI 塑料感；人物全部为合成角色 | 项目方 2026-10-30 | 写实 LoRA / 精修链路；参考素材登记为 `generated` |
| 成人镜头只在本地生成 | 项目方 2026-10-30 | 路由硬规则：成人镜头只走本地模型，闭源 API 只用于非成人镜头对照 |
| 唯一人工门：资产锁定；其余自动 | v1 设计 §1.2 | Temporal 工作流 + QC + 异常队列 |

---

## 2. 架构总览

```
┌──────────── 创作页 (Next.js) ────────────┐
│ 剧本分镜 │ 资产衣橱 │ 画布 │ 渲染农场 │ 异常 │
└───────────────────┬──────────────────────┘
                    │ REST + WebSocket
┌───────────────────▼──────────────────────┐
│ API (FastAPI)  ── PostgreSQL / MinIO / Redis │
└───────┬───────────────────────┬──────────┘
        │                       │
┌───────▼────────┐     ┌────────▼─────────────────┐
│ Agent 服务      │     │ Orchestrator (Temporal)   │
│ abliteration.ai │     │ 镜头 DAG / 重试 / 熔断       │
│ 解析·绑定·编译·QC│     └────────┬─────────────────┘
└────────────────┘              │
                       ┌────────▼─────────┐
                       │ Render Router     │── 模型亲和 / 档位优先级
                       └─┬──────┬──────┬──┘
                   GPU0..n 每卡一个 headless ComfyUI
                   [Qwen 池] [H3-FL2VA 池] [H3-Ref2VA 池] [QC 池]  + 后期(FFmpeg/TTS)
```

---

## 3. 代码仓库结构

```
NS-Final Studio/
├── script play lib/          # 原始资料，只读，不改
├── apps/web/                 # Next.js 创作页
├── services/
│   ├── api/                  # FastAPI：项目/剧集/镜头/资产 CRUD、上传、WebSocket
│   ├── agent/                # LLMProvider(abliteration.ai / 本地)、解析器、抽取、提示词编译、VLM QC
│   ├── orchestrator/         # Temporal workflows + activities
│   ├── render_router/        # GPU 池注册、调度、ComfyUI 客户端
│   ├── qc/                   # 人脸相似度、抽帧、黑帧/闪烁检测、ASR
│   └── post/                 # TTS、字幕、FFmpeg 装配
├── packages/schema/          # Pydantic 模型 → 导出 JSON Schema → 生成前端 TS 类型
├── comfy/
│   ├── workflows/            # 版本化工作流模板（API 格式 JSON）
│   ├── nodes.lock            # 自定义节点 commit 锁定
│   └── models.lock           # 模型文件名 + sha256
├── infra/docker-compose.yml  # postgres, minio, redis, temporal
├── golden/                   # 金标镜头集与 POC 结果
└── docs/                     # 设计文档（v1/v2 链接到 script play lib）
```

---

## 4. 里程碑

总周期约 8–10 周（按 2–3 名工程师 + 1 名模型/基础设施工程师估算）。**M0–M1 必须先做**，它们决定后面的模型路由和 GPU 配置。

### M0 · 环境与单镜打通（第 1 周）

目标：不写任何界面，用命令行把**一个镜头**从剧本跑到视频。

- [ ] 安装 ComfyUI（≥0.30，原生 H3）并锁定版本；安装 Omnichar、MiniMaxH3Mod、SelfLift、H3 Latent Upscaler，记录 commit 到 `comfy/nodes.lock`
- [ ] 下载模型：Qwen 2.1 base/turbo/turbo-LoRA/Fun ControlNet/VAE/qwen3vl_8b；AnyAngle LoRA；H3 FL2VA + Ref2VA；FastH3-Omni；H3 qwen3vl_32b 编码器 + 视频/音频 VAE；（实验）PRISM 合并版。全部记 sha256
- [ ] 从 ComfyUI 导出 API 格式工作流模板：`qwen_t2i_turbo`、`qwen_edit_multiref`、`qwen_anyangle`、`h3_fl2va`、`h3_ref2va_fast`、`h3_2pass_upscale`
- [ ] `services/render_router/comfy_client.py`：提交 `/prompt`、监听 `/ws`、取 `/history`、下载产物
- [ ] `services/agent/providers/ablit.py`：OpenAI SDK + `base_url`，`response_format=json_schema`，本地 Pydantic 再校验
- [ ] 脚本 `tools/render_shot.py ep01 S1`：解析 → 编译提示词 → Qwen 首帧 → H3 视频 → 存盘

**完成标准**：ep01-S1 一条命令出 10 秒视频；同参数重跑结果可复现；每台机器每卡的显存/耗时写进 `golden/bench.csv`。

### M1 · 模型 bake-off 与路由定型（第 2 周）

- [ ] 金标集 12–18 镜：ep01-S1/S2/S3/S6、ep06、ep21、ep28、ep59 等（见 v2 §7.1）
- [ ] 跑 v2 §7.2 对比矩阵：首帧（base/turbo/参考张数）、转面（AnyAngle）、视频（FL2VA vs 10Eros vs FastH3 vs PRISM）、提速（SelfLift / 2-pass）、RefMod
- [ ] 人工标注“接受/拒绝”，校准人脸相似度和 VLM QC 阈值
- [ ] 产出 `golden/routing.yaml`：每类镜头用哪条工作流、哪个 checkpoint、几个候选

**完成标准**：ep01 六镜按路由全自动跑完；得到每档每镜的实测 GPU 秒，替换设计文档里所有“需实测”。

### M2 · 数据模型、导入器与 Agent（第 3–4 周）

- [ ] `packages/schema`：Project / Episode / Shot / Character / CharacterLook / WardrobeItem / OutfitSet / AdornmentState / LookSchedule / SceneAsset / ReferenceAsset / ShotAppearance / RenderJob / QCResult / AssetPackVersion
- [ ] 数据库迁移（Alembic）+ MinIO 桶 + 内容哈希去重
- [ ] **确定性导入器**：解析三份 v2 Markdown → 360 镜结构；装饰状态总表 → LookSchedule；角色锁 → Character
- [ ] **抽取 Agent**：代称消解、可见资产、状态变化，输出带证据和置信度（v2 §4.2 契约）；360 镜跑完后对“缺输出”报错
- [ ] **冲突检查器**（v2 §4.3）
- [ ] **提示词编译器**：Qwen 首帧提示词；H3 四段式视频提示词 + `<Picture N>` 引用来自实际 reference map
- [ ] **Reference Planner**：按景别/可见部位挑 3–6 张参考

**完成标准**：导入 60 集后，ep01–ep10 的绑定人工抽查准确率达到约定值（建议 ≥95%），所有低置信项进入待确认列表。

### M3 · 创作页 MVP（第 4–6 周，与 M4 并行）

- [ ] 外壳：顶栏（项目/集/资产版本/档位/预算/锁定/开始生产）、左侧剧集树、右侧检查器
- [ ] **剧本分镜**标签：TanStack Table、`@` 资产引用、TTS 预演超时标红
- [ ] **资产衣橱**标签：分类、拖拽批量上传、自动去背景与标签、单品卡、“补全参考”、“试穿”、装饰状态时间轴
- [ ] **画布**标签：`@xyflow/react`，资产节点/镜头节点/参考连线（顺序+职责），画布状态存数据库
- [ ] **资产锁定**流程：生成不可变 `asset_pack_version`，导出 `.char` / RefMod / 镜头绑定清单
- [ ] **渲染农场**和**异常队列**标签（数据来自 M4）

**完成标准**：从空项目开始，在页面里导入剧本、上传林晚的参考、确认绑定、锁定资产包，全程不碰命令行。

### M4 · 编排与多 GPU 渲染（第 4–7 周）

- [ ] Temporal workflow：导入 → 绑定 → 预检 → 锁定 → TTS 预演 → 首帧候选 → 图片 QC → 视频 → 视频 QC → 重试 → 后期 → 成集 QC
- [ ] Render Router：worker 注册（卡号、显存、常驻模型）、模型亲和分配、T0 > 重试 > T1 > T2 优先级、熔断
- [ ] 每卡 ComfyUI 的进程管理（`--cuda-device N`，systemd 或 supervisor），启动预热
- [ ] LLM 令牌桶（按 abliteration.ai 档位的 RPM/并发）与 GPU 队列分离
- [ ] 幂等：每个 activity 以“输入哈希”为键，崩溃重放不重复生成
- [ ] QC 服务：人脸 embedding、首/尾帧一致性、抽帧 + 异常加密、黑帧/冻结/闪烁、VLM 检查（每请求 ≤4 图）

**完成标准**：杀掉任意一个 worker，任务自动迁移且已完成阶段不重做；一集 6 镜在多卡上并行完成。

### M5 · 后期与成集（第 7–8 周）

- [ ] 固定音色 TTS（每角色一个授权音色版本），独白可跨镜、对白不超时
- [ ] FFmpeg 装配：按帧计算时间轴、转场、字幕、响度、1080×1920 H.264 24fps 导出
- [ ] 成集 QC 与归档；未通过的镜头阻断该集导出

**完成标准**：ep01–ep10 全自动出片，每集只能是“已导出”或“带原因阻断”。

### M6 · 规模化（第 9–10 周起）

- [ ] 60 集全量；GPU 小时与 API 费用仪表盘；缓存命中率
- [ ] 多节点后引入 Kubernetes + Kueue
- [ ] 按瓶颈迭代：3D 预演、多人复杂镜、Compressed RefMod、团队协作审批

---

## 5. 开工前必须先解决的阻塞项（非技术）

| # | 事项 | 为什么阻塞 | 负责人 |
|---|---|---|---|
| 1 | Qwen Image 2.1 商用授权 | 本地权重是 qwen-research 许可，无授权不能商业发行 | 项目方 |
| 2 | 公司主体与发行地域 | H3 许可排除美/欧/英/韩 | 项目方 + 法务 |
| 3 | 发行平台对成人内容的规则 | 决定能否发布，与模型能力无关 | 项目方 |
| 4 | GPU 清单（型号、数量、单机/多机） | 决定 M0 的量化选择与池子划分 | 项目方 |
| 5 | abliteration.ai 新 key + 账号档位 | 当前提供的 key 返回 `invalid_api_key`；档位决定并发 | 项目方 |
| 6 | 音色授权记录 | 人物已确认全部为合成角色（2026-10-30）；TTS 音色若克隆自真人仍需授权 | 项目方 |

---

## 6. 第一周的具体任务（可以立刻开始）

1. 建仓库骨架（§3）、`infra/docker-compose.yml` 起 Postgres/MinIO/Redis/Temporal。
2. 一台 GPU 机器上装 ComfyUI + 节点 + 模型，写 `nodes.lock` / `models.lock`。
3. 写确定性导入器，把三份 v2 Markdown 解析成 360 条 JSON，人工核对 ep01。
4. 接入 abliteration.ai，跑 ep01 的抽取 + 提示词编译。
5. 用 `tools/render_shot.py` 跑通 ep01-S1，记录显存与耗时。
