# NS-Final Studio v1 使用说明（2026-10-31，fredw-92）

## 打开
- 画布：http://127.0.0.1:5173（前端）；后端 API :8800。开机自启：项目方运行一次 `ops\autostart\register_owner.ps1` 注册计划任务（未注册前由会话手动启动）。
- 依赖的隧道（自启脚本会拉起）：15180 渲染桥、18099 信箱、18188 → gpu3 GPU0 ComfyUI（出图）、18191 → gpu3 GPU3 ComfyUI（视频）。
- 写作模型：abliteration `abliterated-model-large-flash`（密钥：环境变量 `ABLITERATION_API_KEY`）。千问写作模型已撤下（gpu3 GPU1 上的服务待项目方确认后再停）。

## 一集的流程
1. **① 剧本**（#/script-create）：贴提纲 → 选集数范围、镜头数、时长、规则版本 → 下方“模型设置”选模型（默认 large-flash，显示预计费用）→ 写作 → 自动格式校验 → “送到剧本导入”→ 在“工具 › 剧本导入”里确认导入。同一提纲可交给两个模型，进 A/B 对比。
2. **审片模式**（进集默认）：一镜一行，首尾帧大图、剧本、表情、对白、本镜人物、提示词（折叠）、一个状态点和一句“下一步”。主按钮就是下一步（出首帧 / 审首帧 / 审尾帧 / 出视频 / 审视频）。底部片段条可多选批量出。
3. **精修模式**（L、Enter 或双击行；Esc 返回）：
   - 中间：首帧 | 尾帧 | 视频。不满意 → “修改诉求”：改提示词重出 / 指令改图（写一句要求，幅度小中大）/ 换参考再改；或“重新生成”。每次都是一个新版本，挂在上一版下面，可并排对比、回退、从任一版继续改。
   - 满意 → “定稿首帧” → 出尾帧（由定稿首帧编辑而来）→ 定稿尾帧 → “出视频”（gpu3 GPU3，MiniMax H3）。视频不满意 → 改种子 / 步数 / 时长 / LoRA 强度 / 提示词 → 重渲。改了已定稿的首帧，尾帧和视频自动标“过期”。
   - 右栏：提示词（含导演加强，⚙ 可换模型）| 版本 | 规则 | 高级。
4. **本镜参考**（首尾帧上方的人物 / 场景卡，审片行的小卡也能点）：整套换形象、单件换（服装 / 鞋 / 妆 / 甲 / 发 / 饰）、换场景底图、借用其他镜的设置；应用前先看影响面（哪些镜过期、衔接风险），范围：只这一镜 / 本场景 / 本集（本集需勾“我是项目方”，造型确认需重做）。
5. **人物资产**（#/assets 或参考卡里“编辑这个资产”）：给资产挂参考图（上传 / 从某一版设为参考 / 从其他资产复制），标用途（人物 / 风格 / 色彩 / 单件），写提示词 → image2img 生成 → 存为“只这一镜 / 资产新版本 / 本集默认”。
6. **模型与 API**（工具 › 模型与 API）：各家服务商地址、模型、参数、密钥（只写不显示）、测试连接；按用途指定默认模型；出图 / 视频端点与连通状态。

## 实测耗时（2026-10-30/31，gpu3 3090，经跳板机隧道）
- 首帧：约 55–140 s（GPU 本身约 15–95 s，其余是传输）；指令改图约 63–76 s；尾帧约 133–161 s。
- H3 视频（6 s）：每版约 12–14 min（GPU3 的 ComfyUI 以 `--cache-none` 启动，每版都重新加载模型；去掉该参数需重启 gpu3 上该进程，待项目方同意）。
- 写作：large-flash 写 1 集（7 镜）约 43 s，约 $0.04。

## 本地实现：渲染道（gpu33 + gpu36，fredw-92/G36，2026-10-31）
- **道（lane）**：一张卡 = 一个 ComfyUI = 一条道，同一条道一次只跑一个任务（ns_api.jobs 按道串行）。gpu33 的道仍写数字 `0 / 1 / 3`（GPU2 故障，排除）；其他服务器写 `服务器:卡号`，如 `gpu36:0 / gpu36:1 / gpu36:2`（`gpu33:0` 等同 `0`）。frame-jobs / video-jobs / 资产生成的 `gpu` 字段两种都收；不填或填 `"auto"` 就自动分配。
- **自动分配**（项目方：“当 gpu 不做 image 的时候也可以转成 rendering video 啊”）：卡不再固定成“出图卡 / 视频卡”。出图任务先找空闲道，偏好 gpu33:0，没有就用任意空闲道（包括 gpu36）；都忙时排到最短的队（按预计秒数算，视频约 840 s、出图约 70 s）。视频任务任何空闲道都能接，gpu33:0 只在没有排队的出图任务时才接视频；gpu33:0 在出视频时，新的出图任务自动改派到别的空闲道。ComfyUI 自己队列里有别人直接投的任务，也算忙。连不上的道跳过。
- **配置**：`config/render_endpoints.json` 里的 `lanes` 表，写法 `{"gpu36:0": "http://127.0.0.1:18288"}`，也可以写成 `{url, max_frames, label}`。改这个文件只做局部插入，不要整份覆盖。`GET /api/render/lanes` 返回每条道的可达性和当前在做什么（`status_text` 如“gpu36:1 · 出视频”）；`GET /api/render/endpoints` 在 image / video 两行后面列出每条道（`kind:"lane"`），`PUT /api/render/endpoints/gpu36:1 {url}` 可以改某条道的地址。顶栏 GPU 胶囊显示成“33:0 出图 · 33:1 出视频 · 36:0 空闲 …”。
- **gpu36**（3×RTX 3090，共用机器；用户 flab / loki / tom / yuheng 也在用）：所有文件都在 `/root/work/fredw/`。ComfyUI 0.42.0 和 custom_nodes（KJNodes、SelfLift、Minimax_h3_latent_Upscaler）从 gpu33 原样复制，节点表与 gpu33 一致（1262 个）。Python 3.12.16（uv 管理，装在 `/root/work/fredw/python`），私有 venv 在 `/root/work/fredw/venv`，包版本与 gpu33 的 env/comfy 相同（torch 2.11.0+cu128、comfy-kitchen 0.2.39 等；sageattention 没装，启动参数里也不用）。公共 py311 是 3.11，装不上 gpu33 那套版本（av 19 要求 3.12），所以没用它。模型从 gpu33 走机房局域网复制（gpu33 上跑 rsync 到 10.0.0.36，笔记本 ssh-agent 转发登录，主机指纹已核对），每个文件两端各算一次 sha256 比对。
  - 启停：`ssh gpu36 '/root/work/fredw/comfy/comfy.sh start|stop|restart|status [0 1 2]'`。GPU0→:8188、GPU1→:8189、GPU2→:8190，只绑 127.0.0.1。输出目录 `/root/work/fredw/comfy/output/gpuN`，PID 文件在 `comfy/run/`，日志在 `comfy/logs/`。启动参数和 gpu33 GPU0 相同：`--reserve-vram 1 --cache-none --preview-method none`。没有用 gpu33 视频卡的 `--cache-ram 140 200`，原因是 gpu36 是共用机器，内存 440 GB 要分给三个实例和其他用户。
  - **GPU2 = 长镜头道 gpu36:2**（fredw-92/LS，2026-10-31）：镜头长度由剧本决定，系统不截短。gpu33 的视频卡用默认参数一次最多出 260 帧（10.8 s），再长就 OOM；GPU2 用 `--novram` 起（权重留在内存逐层上卡），实测 294 帧 32 min、362 帧（15 s）53 min 都能出。超过所选道上限的镜头由 video_jobs 自动改派到 gpu36:2（任务 params.route 写 rerouted_from）；出图和短视频不会派过去（lanes 记录 `long_only: true`）。启停：`ssh gpu36 '/root/work/fredw/longshot/lane.sh start|stop|restart|status'`（:8190，PID 文件 longshot/run/lane.pid，不用 comfy.sh 起 gpu2）。长镜头道没起时，超过 260 帧的镜头提交会返回 409 说明原因。
  - 笔记本隧道：`ops/autostart/tunnel_gpu36.sh`，把 18288→gpu36:8188、18289→:8189、18290→:8190。由 tunnel.sh 顺带拉起，laptop_autostart.ps1 也会检查这三个端口。
  - 注意：三张卡同时满载 15–20 分钟后，机器会自动把功耗压到 200 W，降温后恢复，属于正常现象，不要处理。禁止执行 `nvidia-smi -pl`。gpu36 网口只协商到 100 Mb/s，跨机复制约 11 MB/s。
- **gpu36 实测**（2026-10-31，冷加载）：Turbo 首帧 21 s（ComfyUI 执行 18 s）；H3 5 s 视频（124 帧）545 s，约 4.4 s/帧，和 gpu33 的视频卡差不多（约 4.7–5.5 s/帧）。验证产物在 data/ab/gpu36_check/。
- **跨服务器的帧**：每个 ComfyUI 的输出目录各自独立，实例标识里带服务器名（`gpu36|out:…`）。所以 gpu33 出的定稿帧交给 gpu36 出视频时要上传一次（经跳板，上行慢），同一实例内的帧直接引用、不上传。

## 出图预设（LCA，2026-10-31）
- **默认 = 徕卡 S★**（项目方原话：“leica_sharp效果最好，用他”，选“S★ 全套组合”）。画布出图参数下拉里显示为“徕卡 S★（默认）”；不选预设出的首帧 / 尾帧 / 指令改图 / 换参考都用它。
- S★ = C（Turbo 8 步、cfg 1、texture_fix VAE、krea2 0.5 + 林晚 lin_wan_qi_v1 0.6）+ 1.5 倍出图 1152×2016 → lanczos 缩回 768×1344 + USM 锐化（半径 1.2、强度 60%、阈值 2）+ 风格后缀（写作模型候选1 原样，前加“，”接在提示词末尾）。
- 每一版另存放大原图（take.params.post.from），交付图是 *_post.png；版本参数里能看到“放大出图 / 锐化 / 风格后缀”的实际值。
- 带底图的改图（指令改图、换参考的底图重绘）不放大，按 768×1344 出，后缀和锐化照做；改图底图用父版本锐化前的原图。资产 / 场景图生成选了预设时同样处理。
- 旧默认“C·Turbo 质感”仍可在下拉里选；改回默认 = config/render_quality.json 的 default_preset 设成 c_turbo_texture。定稿档不受影响。

## 规则
- 不做内容检测、不做成人拦截（项目方 2026-10-30 夜决定，暂时）；露骨红标的人工标记维持原处理。
- 系统不写、不改、不评剧本和提示词；你写的修改要求原样交给 Image 2.1 / H3。

## 已知缺口
- 局部重绘（蒙版）：需要在 gpu3 新增 ComfyUI 流程，界面上已占位、不可用。
- gpu3 视频卡 `--cache-none`（见上）；GPU1 的千问服务待停。
- 跳板机上行只有 8–25 KB/s：同一张卡上的图已改为直接引用不再上传，跨卡（GPU0 出的帧给 GPU3 出视频）仍需上传一次。
- “我是项目方”只是界面勾选 + 请求字段，没有真正的身份鉴权（API 只监听本机）。
- 详细改动：docs/CHANGELOG_AGENTS.md；需求与进度：docs/TODO_v1_close.md；接口：docs/api_v1_contract.md；界面规格：docs/canvas-ui-spec-v3-merge.md。
