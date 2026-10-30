# QA 问题记录（夜间监督，追加式，最新在上）

格式：时间（gpu3 本地 EDT）｜级别（P0 停产 / P1 可见质量缺陷 / P2 次要）｜位置｜证据｜建议修复｜负责 agent

---

## 第 8 轮 2026-10-29 17:11 EDT（最后一轮）

### [P1] ep05s1 成人首帧和剧本不符，而且 VLM 检查是空的
- 剧本镜1：「高级衣帽间，射灯聚焦**挂在墙上**的黑色漆皮束腰…蓝发女性**立于其前一臂之遥**」；motion：「她走进衣帽间，视线被束腰钉住」；sound：「高跟鞋踩地毯」。她这时还没穿上束腰。
- 首帧（`ep05/frames/ep05s1.png`，以及 alt；见 `previews\qa\r8_ep05s1.jpg`）：她已经穿着束腰，下身全裸，**赤脚没穿高跟鞋**，墙上还挂着第二件束腰（道具重复）。漆皮镜面反光 ✔，5 cm 镶钻长甲 ✔，ep01–08 无穿孔 ✔，身份相似度 0.85 ✔。
- `ep05s1.pick.json`：两张候选的 `"vlm": {}` —— weita_adult 没有做任何 VLM 检查（高跟、穿着、道具数量）。
- 建议：成人镜头同样按剧本的 img 文本检查——这一镜不该裸露、要穿 12 cm 透明细跟高跟、束腰只出现在墙上；VLM 检查项不能为空。
- 负责：weita 渲染 agent

### 状态
- 没有出视频的单元。gpu0 借给 weita-v3-llm（锁内容与实际一致），gpu3 在跑 weita-adult-frames2（ep05），gpu1 在跑 wardrobe / 首饰。GPU 2 空闲。磁盘 1.2 TB 可用。
- ep01 仍然只有 s1、s2、s4 三条片子；全部 60 集里完成 0 集。
- QC 测试：`-k "owner_script or weita"` 64 通过 1 跳过；QC_VERSION 2026-10-29.6。

---

## 第 7 轮 2026-10-29 16:35 EDT

新增检查项（项目方）：12cm 高跟，约 6 mm 筷子粗细的细针跟（粗跟 = P1）；漆皮要超亮的镜面湿润感（哑光 = P1）；林晚上班穿亮黑漆皮超短裙；手入镜时要有 5 cm 透明镶钻长甲；暖调浓郁、奶油焦外。

### [P1] 进度：开跑约 6 小时，**还没有一集完成**
- weita-series 自 15:40 停止后没有再启动；ep01 只有 s1、s2、s4 三条片子，s3/s5/s6 还在反复重做（s3 20:12Z 又失败：identity_jump + 人脸检测置信度低，t=3.75–9.75 s）。ep02 的 turbo 首帧已作废（`ep02_turbo_superseded/`）。
- 目前 GPU 上：gpu3 在跑 `weita-adult-frames`（weita_adult.py，为 ep01–10 预生成成人镜头首帧，正在 ep05）；gpu0、gpu1 在跑首饰 ControlNet 和 wardrobe 数据集；`weita-v3-sample` 用 CPU 上的 LLM 改写 ep1–3 剧本。**没有任何进程在出视频。**
- 按现在每镜头约 25 分钟、两张卡计算，60 集（约 360 个镜头）至少要 75 小时，今晚完不成。需要协调者重新分配 GPU 和优先级。
- 负责：协调者 / weita 渲染 agent

### [已修复 by weita] ep01s5 裸背首帧已作废，新首帧是黑色吊带裙 ✔
- `ep01/frames/ep01s5.png`（c2）：背对镜头，黑吊带裙，窗玻璃里有倒影，5 cm 镶钻长甲 ✔，浅雾蓝发色 ✔。VLM 新增了「穿着衣服」检查（第 6 轮的建议已采纳）。证据：`previews\qa\r7_frames.jpg` 左图。
- **[P1 风险]** `ep01s5.alt.png` 是 c1——**全裸背面，而且 VLM「穿着衣服=false」没通过**（`r7_frames.jpg` 中间图）。series 重试时会用「备选候选帧」，如果这张没通过 VLM 的图被拿来当 alt，就会渲出裸体片。**已在代码里确认**：`weita_series.py` 第 608–612 行 alt = 分数第二高的候选，不检查 `scores[k]["fail"]`；第 716 行在重试的第 2 步就会用 alt 出片。建议：改成 `ranked = [k for k in ... if not scores[k]["fail"]]`。
- 负责：weita 渲染 agent

### [P2] ep02s1（已作废的 turbo 版）构图不符
- 剧本：「深夜写字楼**全景**，整层黑只剩两盏台灯…独自伏案」；首帧是正脸半身肖像。作废后请在新版里检查这一点（`r7_frames.jpg` 右图）。

### 健康
- GPU 2 空闲；磁盘 1.3 TB 可用；锁：gpu3 由 weita_adult（pid 430766）持有，跟实际使用一致。llama-server 跑在 CPU 上。

---

## 第 6 轮 2026-10-29 16:00 EDT（weita-series 在 15:40 被 weita agent 停掉（r5、r6 都只跑了几分钟），正在手动收尾 ep01）

### [P1] ep01s5 新首帧是裸背（臀部也露出），剧本是穿着衣服洗碗
- 证据：`previews\qa\r6_frames.jpg` 中间那张 = `ep01/frames/ep01s5.png`（15:32，选中的是 c2）。提示词里写了「衣装保守完整，无裸露」，剧本镜5 是普通家常洗碗；旧版首帧是白色吊带。
- 原因：VLM 的 `no_nudity` 只问「露点」，背面全裸不算露点，所以通过了（`ep01s5.pick.json`：`{"露点": false}`）。林晚成人许可解除（face_reference.json 19:21Z）后，这种情况会更常见。
- 建议：凡是剧本没写裸露的镜头（`shows_body()==False`），VLM 改问「人物是否穿着上衣和下装（衣着完整）」——ep01s1 用的就是这个问法；不通过就淘汰。
- 负责：weita 渲染 agent

### [P1] ep01s6 新首帧仍然不是「眼睛极近特写」
- 证据：`r6_frames.jpg` 右图：中景，她正对镜头，双手拿着东西，陈宇的脸基本是清晰的，没有车灯流光。剧本要的是前景睁着的眼睛极近特写，陈宇的侧脸虚化在背景。
- 建议：构图前缀（像 s1/s5 那样的「构图（最重要）」）写成「画面只有她的一只眼睛和眉毛占满画面…」；VLM 检查加「是否眼部特写」。
- 负责：weita 渲染 agent

### [P2] ep01s3 新首帧：低头侧脸 ✔，有进步；但头发偏深海军蓝（参照是浅雾蓝），背景仍是素墙。

### [P1] 吞吐：gpu3 从 15:40 起空闲，gpu1 被训练/数据集占用，出片只剩 gpu0 上一个手动的 ep01s3_h3 任务
- 证据：nvidia-smi gpu3 0%；`weita-lend-gpu3` 在等 `ep01/ep01_final.mp4` 出现后才把 gpu3 借出去，但 series 已停，ep01 成片还没出来。8188 上 ep01s3_h3 的客户端 pid 382996 已经退出，weita agent 有两个 shell 在等这个任务跑完再到输出目录取片（是有意为之，我没有动这个队列）。
- 建议：尽快恢复 weita-series（续跑 ep01 → 拼装 → ep02），或者先把 gpu3 借给训练用。
- 负责：weita 渲染 agent

### 其他
- weita-v3-llm：llama-server 27B 跑在 CPU 上（-ngl 0），没有占 GPU，没问题。GPU 2 空闲；磁盘 1.3 TB 可用。
- ep01s4 新片子（19:34Z PASS）就是第 5 轮看过、符合剧本的那条。

---

## 第 5 轮 2026-10-29 15:20 EDT（weita-series-r4 14:03 重启后在跑，QC 锁修复已生效：重启后没有再出现 OpenCV 崩溃）

### [P1 → 已修复 QC 侧] ep01s3 正式片子（a2）后半段人脸「溶解/重影」，QC 却判 PASS
- 证据：`previews\qa\r5_s3_strip.jpg`（每秒一帧）：4 秒起蓝发半透明地扫过脸，两张脸叠在一起，7 秒后已经认不出脸。`ep01/clips/ep01s3.result.json`：qc pass，end_identity None。联系表 `previews\qa\r5_ep01_clips.jpg` 第 3 行。
- 原因：逐帧检查都过了。脸部清晰度从 ~310 跌到 95 后，人脸被判成「非人脸」剔除，后面 6 秒没有人脸；原来的 dropout 检查要求人脸「消失又回来」才报。
- 修复（我的职责范围）：`owner_script_qc.py` QC_VERSION 2026-10-29.6 新增 `face_dissolve`。条件是：大脸（≥200 px）起初清晰，同一跟踪的最后 3 个样本清晰度跌到 ≤45–75%，并且结尾 30% 的样本里再也没有人脸 → 1.0（fail，会触发重渲）。只是后段变糊、脸还在（移焦/转头）的，最多给 warn。
- 验证：用新版本重新跑 ep01 全部 8 个 attempt 和 6 条 A/B 片。只有 s3_a2 由 PASS 变 FAIL，其余结论都不变（s3_a1、s6_a1 本来就是 FAIL）。新增单元测试，`-k "owner_script or weita"` 64 通过 1 跳过。备份 `/root/qa_supervisor/backup3/`。
- **需要**：series 进程会缓存 QC 模块，下次重启 weita-series 才生效；ep01s3 需要重渲（当前 clips/ep01s3.mp4 不能用）。
- 负责：weita 渲染 agent

### [P1] ep01s2 文件夹凭空出现；s1→s2 服装不连续
- 证据：`previews\qa\r5_ep01_clips.jpg` 第 2 行：剧本是「抱紧怀里的文件夹贴在胸前」，但 0–5 秒她手里没有文件夹，10 秒时突然抱着一个灰色文件夹。服装方面，镜1 是藏青西装 + 白衬衫 + 西装裙，镜2 变成黑西装、深 V 没有衬衫。同一个早晨，同一套衣服应该一致。
- 镜1 里文件夹也从藏青色（5 s）变成灰色（10 s）。
- 建议：首帧提示词带上本集的服装锁定行（同场景镜头复用同一段服装描述）；道具在首帧里就要出现。
- 负责：weita 渲染 agent

### [P2] series 的「结尾身份漂移」检查在脸被遮挡时误判
- 证据：ep01s4_a1（`previews\qa\r5_s4s6.jpg` 第 1 行）完全符合剧本：揉头发、她笑着躲、低头喝汤。但它因为「identity drift at the end: SFace 0.18」被判失败——结尾她正在用碗挡着脸喝汤。这会白白浪费一次约 25 分钟的重渲。
- 建议：结尾脸太小、被遮挡（YuNet 置信度低或 landmarks 失败）时跳过身份比较，或改用最后一个清晰人脸帧来比。
- 负责：weita 渲染 agent

### 已正确拦下
- ep01s6_a1（`r5_s4s6.jpg` 第 2 行）：5–10 秒人脸和一只巨大的眼睛叠化（重影），QC fail，正确。

### 剧本朝向/姿态对照（新增的检查项）
- s1（fix 版）：鞋尖朝镜头的正面低机位，上摇到脸 ✔（第 4 轮的背面问题已修好）。
- s2：两人并排、男方侧目、她低头 ✔；文件夹问题见上。
- s3：低头、嘴角上扬 ✔（但溶解，需重渲）。
- s4：✔。
- s5：剧本是「背影」，片子开头她回头看镜头，2 秒后转成背面，结尾是侧脸看窗 → 基本符合，开头不符（P2）。
- s6：剧本是「极缓推近眼睛」，片子推近了，但出现重影 → 已 fail。

---

## 第 4 轮 2026-10-29 13:57 EDT

### [P0] QC 多线程崩溃第二次发生，这次丢掉的是 ep01s3 的视频阶段——正在运行的 series 进程还在用旧的 QC 模块
- 证据：`logs/series.log` 17:34:50Z `[gpu3] ep01s3: error: OpenCV(5.0.0) ... (-215:Assertion failed) buf.shape() == m.shape() in function 'forwardGraph'`（第一次是 16:58:48Z 的 ep01s2）。`weita_series.py` 的 worker 循环把异常吞掉后直接处理下一个镜头，这个镜头不会重试 → ep01 现在 6 个镜头里有 2 个丢了（s2 没首帧，s3 没片子）。照这个频率 60 集每集都会缺镜头。
- 修复已部署（第 3 轮，QC_VERSION 2026-10-29.5，`Models` 加锁），但 `weita_render._load()` 把模块缓存在 `sys.modules` 里，weita-series-r3（pid 282037，12:58 启动）要**重启**才会用上新代码。
- 需要：weita agent 在当前镜头结束后重启 weita-series（它可以续跑），并重跑 ep01s2、ep01s3。
- 负责：weita 渲染 agent（我已上报协调者）

### [P1 跟进] ep01s1 第一条正式片子（t8，QC pass）：开头是背面，镜头上摇途中人物转成正面
- 证据：`previews\qa\r4_ep01s1_clip.jpg`：t=0 是背面的腿 + 透明高跟（鞋跟朝镜头）；t=5 s 已经是正面的腿；t=10 s 正面看脸，裙装和文件夹都对。开头那几帧头发是深海军蓝，后面变成浅蓝。片子 10.125 s，有音轨；首帧 PSNR 35.3，结尾身份相似度 0.879。
- weita agent 已经在用 `weita-fix-s1`（scripts/weita_fix_s1.py）修这个镜头，目前在等 gpu0 的锁。
- 另：PIPELINE_LOCKED.json 16:55Z 改为 t8（之前是 t4）——说明一下，不算问题。

### 健康
- 三张好卡 100%；GPU 2 空闲；磁盘 1.3 TB 可用。gpu0/gpu3 锁由 series 持有，weita-fix-s1 在排队等 gpu0（没有死锁：8188 上正在跑 series 的任务）。

---

## 第 3 轮 2026-10-29 13:20 EDT（weita-series-r3 在跑 ep01，首帧阶段，尚无视频）

### [P1 → 已修复 QC 侧] ep01s2 首帧阶段崩溃：OpenCV DNN 多线程冲突
- 证据：`logs/series.log` 16:58:48Z `[gpu3] ep01s2: error: OpenCV(5.0.0) ... (-215:Assertion failed) buf.u == m.u in function 'forwardGraph'`。ep01/frames 里没有 ep01s2.png。
- 原因：weita_render 的 `qc_models()` 让 gpu0/gpu3 两个线程共用一个 QC `Models`；`faces()`（YuNet）和 `qc.check()` 没有加锁，OpenCV 5 DNN 不是线程安全的。
- 修复（我的职责范围）：`owner_script_qc.py` QC_VERSION 2026-10-29.5，`Models` 内部加 RLock，所有 YuNet/SFace/FaceLandmarker 调用都持锁。新增多线程单元测试（旧版本上能复现失败，新版本通过）；相关测试 63 通过 1 跳过。备份在 gpu3 `/root/qa_supervisor/backup2/`。
- **注意**：正在跑的 weita-series-r3 进程已经加载了旧模块，下次重启 series 才生效。ep01s2 需要重跑首帧。
- 负责：weita 渲染 agent（重启/重跑 ep01s2）

### [P1] ep01s1 仍是背面构图，6 张候选全部未通过 VLM「正面朝向」检查
- 证据：`ep01/frames/ep01s1.pick.json`：c1–c6、c90 全部 `VLM facing: 正面朝向镜头 false`，最后还是选了 c1（背面），已记入 HARD_SHOTS.jsonl。联系表 `previews\qa\r3_ep01_frames.jpg` 第 1 张。
- 建议：低机位脚部特写时 Turbo 一直画背影。可试：提示词写「脚尖朝向镜头走来，鞋头和脚背正对镜头，前景是鞋尖」；或者改用 NoctQ；或者 Blender 难镜头服务出一个正面脚部的 ControlNet 构图。
- 负责：weita 渲染 agent

### [P1] ep01s3、s5、s6 首帧和剧本的人物朝向/构图不符（脸部参考图把人都拉成正脸）
- 镜3 剧本：「极近特写，林晚**低头侧脸**，齐刘海的阴影盖住上半张脸，嘴角极轻微上扬」→ 首帧是正脸直视镜头，素色背景，没有刘海阴影（像证件照，不是电影画面）。
- 镜5 剧本：「林晚**背对镜头**洗碗…窗外玻璃映出自己模糊的脸」→ 首帧是回头正脸看镜头。
- 镜6 剧本：「极近特写…陈宇熟睡侧脸**虚化**在背景，前景林晚睁着的眼，**黑暗中**车灯流光扫过瞳孔」→ 首帧是中近景、偏亮，陈宇的脸清晰，没有车灯流光。
- 证据：`previews\qa\r3_ep01_frames.jpg`（第 3、5、6 张）。镜4 符合剧本（暖黄台灯、端汤、两人）。
- 建议：剧本写了「背对/侧脸/低头/背影」的镜头，VLM 检查加一项「人物朝向是否与剧本一致」；这类镜头脸部参考图降权或只用单参考；镜6 加「浅景深，背景人物虚化，低照度」。
- 负责：weita 渲染 agent

### 正面
- 林晚身份一致性好（5 个镜头同一张脸，浅蓝长发、齐刘海）；透明高跟正确；镜4 的暖光、构图、两人数量正确；没有烧进画面的文字。

### 健康
- 三张好卡都在 100% 跑；GPU 2 空闲；磁盘 1.3 TB 可用。gpu0/gpu3 锁都由 series（pid 282037）持有，ab 实验已停 → 第 2 轮的争用问题已解决。gpu1 由 lw-newface2 + wardrobe 使用。

---

## 第 2 轮 2026-10-29 12:45 EDT（weita-series 已于 16:38Z 开跑 ep01→ep60，锁定 t4 方案）

### [P1] 新 ep01s1 首帧两个候选都是**背面**（看到鞋跟和小腿后侧），尾帧是正面
- 位置：`ep01/frames/cand/ep01s1_c1.png`、`ep01s1_c2.png`（12:40）、`ep01s1_last_c1.png`
- 证据：`previews\qa\r2_series_ep01s1_cands.jpg`。透明高跟和裙装已经对了（比第 1 轮好很多），但首帧是从背后拍腿，尾帧是正面看脸 → FL2VA 只能让人物在上摇过程中转身（A/B 里 lora 变体就因为「上摇途中转身」被否掉）。代码里写了「人物正面朝向镜头」，两张候选都没听。
- 另：首帧里的头发是深海军蓝，尾帧是浅蓝（参照是浅蓝）。
- 建议：首帧 QC/VLM 增加「朝向：正面/背面」判断，背面候选淘汰；提示词加「脚尖朝向镜头，鞋头在前，看到脚背」。
- 负责：weita 渲染 agent

### [P1] 已锁定方案后，A/B 实验单元 weita-ab2c 仍在占 gpu3，正式出片在等锁
- 证据：`logs/series.log` 16:38Z「[gpu3] waiting for the GPU lock」；`fuser gpu.lock.gpu3` → pid 235723 = `weita_render.py ab --variants t4,t8`（已跑 33 分钟），之后还排着 `t4+vbvr` 在 gpu0。PIPELINE_LOCKED.json 16:40Z 已选 t4。gpu1 被 lw-newface（lw agent）和 wardrobe-gen-gpu1 占用。结果：60 集正式出片目前实际只有 gpu0 一张卡。
- 建议：如果 t8 / vbvr 对比不再影响决定，停掉 weita-ab2c 的后半段；或把实验挪到 gpu1。
- 负责：weita 渲染 agent

### [P1 跟进] 旧方案片子（t4 / base）尾帧仍是西裤
- 证据：`previews\qa\r2_ep01s1_t4.jpg`：t4 片 10 秒处是黑西裤；weita agent 自己的 VLM 测试（`logs/vlmtest.log`）也判为「下装: 裤子」。新的系列尾帧候选已是裙装（见上），所以只需确认 ab 目录下的片子不会进成片。
- 负责：weita 渲染 agent

### 状态
- 首帧风格：剧本已加「每条img统一后缀」（电影感、通透明亮、暖调、f/1.4 浅景深、无字幕），weita_render 已接入 → 第 1b 轮的风格问题在新候选里部分改善（尾帧更暖更亮；首帧背景虚化仍偏弱）。
- t4 片：768×1344、243 帧、10.125 s、AAC 32 kHz 音轨有声。
- GPU 2 空闲；磁盘 1.3 TB 可用；无失败单元（redis 除外）。

---

## 第 1b 轮 2026-10-29 12:15 EDT（项目方新增画面标准：无字幕、电影感干净画面、明亮饱和的暖色柔光（参照 `refs/style_ref_owner.png`）、大光圈浅景深奶油焦外、夜景干净有暗部细节）

### [P1] ep01s1 三条 A/B 片都不符合项目方的画面风格
- 证据：`previews\qa\r1_ep01s1_ab.jpg` 与 `previews\qa\style_ref_owner.png` 对比：大堂是偏冷的灰蓝色调、平光；**背景（旋转门、玻璃幕墙、远处楼群）全部清晰，没有浅景深/焦外**；没有参照图那种大面积柔光、暖色粉彩高光。客观值：平均亮度 0.42（参照 0.71），暖度 R-B 约 -5～+8（参照 +16），近黑像素占 4–6%（黑西装）。
- 原因：首帧提示词（manifest.jsonl 中 ep01s1 候选帧）的风格尾句只有「真人写实摄影，8K，自然皮肤纹理，9:16竖屏，静态构图」，没有光线/色彩/景深要求。
- 建议：在 weita_render 的首帧提示词尾句加入固定的风格段，例如「大光圈浅景深，背景奶油般柔焦虚化，柔和大面积柔光，明亮通透，暖色粉彩高光，色彩饱和而干净，电影感画面，画面简洁不杂乱」；夜景镜头加「夜景干净，暗部保留细节，不发灰不死黑」。首帧决定整段视频的光色，所以必须在首帧阶段改。
- 负责：weita 渲染 agent

### [已修复] QC 工具新增「画面观感」检查（我的职责范围）
- `ns-studio/scripts/owner_script_qc.py` QC_VERSION 2026-10-29.4：新增 `look_dark`（偏暗）、`look_grey`（发灰/低饱和）、`look_crushed_shadows`（暗部死黑）三项全局标记，最多到 warn（不会让片子 fail 或触发重渲）。阈值按参照图和 ep01s1 校准；ep01s1 A/B 三条不触发（它们的问题是冷色/无景深，不是发灰发暗——这两项靠人工看）。
- 新增 2 个单元测试；`test_owner_script_qc + test_weita_render + test_owner_script_render` 62 通过 1 跳过。原文件备份在 gpu3 `/root/qa_supervisor/backup/`。
- 版本号提升后，watch 模式会把已检查过的片子按新版本重新检查一遍。

---

## 第 1 轮 2026-10-29 12:00 EDT

### [P1] ep01s1 首帧是改剧本之前生成的：黑色漆皮高跟，不是 12cm 透明细高跟
- 位置：`ns-studio/data/run/weita/ep01/frames/ep01s1.png`、`ep01s1.last.png`，以及用它们生成的 A/B 片 `ab/{base,tst,lora}/clips/ep01s1.mp4`
- 证据：manifest.jsonl 中 ep01s1 候选帧（14:41Z）提示词为「一双黑色细高跟鞋」；剧本改为 `hh12clear … 12cm透明细高跟` 的时间是 14:56Z（`.bak-20261029-heels`）。联系表 `D:\NS-Final Studio\previews\qa\r1_ep01s1_ab.jpg` 第 1 列三条片都是黑漆皮尖头鞋。
- 建议：锁定 ep01 之前用新剧本重出 ep01s1 首帧/尾帧（含 hh12clear 描述；hh12clear LoRA 训好后再出一次）。A/B 结论（base/tst/lora 对比）仍可用，但这些片不能进成片。
- 负责：weita 渲染 agent

### [P1] ep01s1 服装漂移：西装裙 → 西裤
- 位置：`ep01/frames/ep01s1.last.png`（尾帧）及三条 A/B 片的末帧；lora 变体在 5 秒处已变成西裤
- 证据：`previews\qa\r1_ep01s1_ab.jpg`：首帧是及膝西装裙，三条片末帧都是黑色西裤；剧本写「西装裙摆」「沿西装裙、腰线…摇至脸」。
- 建议：尾帧提示词明确「黑色及膝西装包臀裙，无裤子」，并把服装写进 QC 检查项；尾帧候选里选裙装的。
- 负责：weita 渲染 agent

### [P1] ep01s1 lora 变体中段文件夹变形
- 证据：`r1_ep01s1_ab.jpg` 第 2 行第 3 列（lora t=5.06s）：手中文件夹扭成灰色弯曲块状。base/tst 无此问题。
- 建议：A/B 打分时计入；若选 lora 变体需重抽种子。
- 负责：weita 渲染 agent

### [P1] GPU 争用：出片等锁 1 小时以上
- 位置：weita-ab1（gpu0 base 变体 10:52 起一直「waiting for the GPU lock」，lock 被 lw-lora-dataset（pid 217589）持有）；同时 wardrobe-gen-clear 的 client `wardrobe-196197ae` 往 8188/8189/8191 三个 ComfyUI 都投任务（不经过 gpu.lock）。
- 证据：`logs/ab1.log`；`fuser gpu.lock.gpu0` → 217589；ComfyUI /queue 里 wardrobe 任务在三台实例上排队。
- 影响：60 集连跑开始后，出片会被数据集生成/衣服生成抢占。文档约定「出片优先占两张卡」，目前没有执行机制。
- 建议：lw-lora-dataset 与 wardrobe 生成只用一张卡（例如 gpu3/8191），或在 weita 正式开跑时暂停；wardrobe 的 comfy_gen.py 也应取 gpu.lock。
- 负责：lw / wardrobe agent（协调：weita agent）

### [P2] weita-ab1 的 gpu3 线程崩溃（已修复）
- 证据：`logs/ab1.log`：`AttributeError: module 'owner_script_render' has no attribute 'Worker'`（weita_render.py:726）。现在 `owner_script_render.py:613` 已有 `class Worker`，后续 ab1c / ab(t4,t8) 运行正常。
- 建议：无需处理；留意同一进程（pid 171683）还在跑旧代码。
- 负责：weita 渲染 agent

### [P2] 文档中的 LoRA 注册表文件不存在
- 证据：`ComfyUI/models/loras/LORA_REGISTRY.json` 不存在；weita_render 实际从 image 提示词 v2 的「数据E」读取注册表，并且只保留有 LoRA 文件的触发词（代码 active_loras），所以不会出现「有触发词无 LoRA」的问题。
- 建议：status 文档改成实际位置，或训练完成时写出该 JSON。
- 负责：jwl / wardrobe / lw agent

### [P2] VLM 质检日志曾失败（模型当时不存在 + 无 CUDA）
- 证据：`logs/vlm.log`（11:49）：找不到 `models/llm/Qwen3.8-27B-Uncensored-Q4_K_M.gguf`，并且 `no CUDA-capable device`。模型文件现在已经存在。候选帧 QC 的 `face_px/similarity` 为 None（ep01s1 镜1 从腿部起拍，合理）。
- 建议：正式开跑前确认 VLM 质检能启动并用上 GPU。
- 负责：weita 渲染 agent

### 健康状况（无问题）
- GPU 2 空闲（18 MiB），没有进程使用。磁盘 1.4 TB 可用。失败单元只有 redis-server（与本项目无关）。
- 单元测试：test_weita_render + test_owner_script_qc 56 通过；owner_script_render / lora_training_core / narrative_qc 40 通过 1 跳过。
- 片子规格：768×1344、24fps、243 帧、10.125 秒、有音轨（放大前的中间片）。
