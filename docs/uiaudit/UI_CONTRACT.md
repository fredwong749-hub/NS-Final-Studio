# momoso 界面契约（UI_CONTRACT v1，UIAUDIT 2026-10-31）

这份契约是界面的"骨架"：**每一类对象必须具备哪些操作**，以及每个操作在后端有没有接口。
每轮验收（`docs/uiaudit/detect_rN.md`）按这里逐格打分：用真实界面（无头 Chrome，`apps/web/e2e/uiaudit/detect.mjs`）点出来才算，不看报告。

项目方原话（契约的来源）：
- "声音模型那边，我需要监听它的播放，行不行？接不接受？能不能修改？我连播放按钮都没有。"
- "系统是在我 login 的……我选这个图按一下就可以了"（一键即确认、不打字）
- "需要把 edit 和 delete 的功能全部加上去"
- "UI 的排版细节……字号、换行、边距、颜色"；"看到最新东西都不太行"
- "这个交互反人类啊！我连向下滑拖都不太行，我怎么用啊？"（10-31 23:48，资产中心林晚页）

---

## 0. 操作列（每列的验收口径）

| 列 | 名称 | 验收口径（界面上必须做到） |
|---|---|---|
| V | 查看 | 图能开大图（≥ 视口高 80%，原图分辨率）；文字能看全文（不截断、不藏在 tooltip） |
| P | 预览 / 播放 | 图片放大 + 左右翻；**视频能播（带进度、静音切换）；音频能播（▶ 按钮在对象卡上，一键试听，带进度条 / 波形）** |
| C | 对比 | 新旧版、候选之间并排（图：并排 / 滑块；视频：同步播放；**音频：A/B 一键切换，同一句台词**） |
| S | 选定 / 接受 | 一键（登录即身份，不打字）；选完立刻可见"当前"标记；**5 秒内可撤销**，之后能在版本条上改回 |
| E | 编辑 | 文字反馈 / 框选 / 时间点打点 → 系统去改（`/api/edits`）；改完出新版本，不覆盖旧版 |
| N | 新增 / 上传 | 有"＋"入口；图片 / 音频 / 文本支持拖拽、粘贴、选文件；上传后立即出现在列表里 |
| D | 删除 | 每个对象都有删除；先显示影响面（`/api/trash/impact`），删到回收站（`/api/trash/object`），提示条带"撤销" |
| H | 版本与回滚 | 版本条（#1 #2 …，当前高亮）；点任一版即可设为当前；回滚一键 |
| B | 批量 | 多选（框选 / Shift）→ 批量选定 / 批量删除 / 批量重出；结果按对象分开显示 |
| T | 状态与进度 | 对象卡上直接显示：草稿 / 候选 / 当前 / 作废；生成中显示进度和预计时长，可取消 |
| X | 出错提示 | 人话 + 原因 + 下一步按钮（重试 / 去补）；技术细节折叠；不出现 sid、rev、json 路径等内部字段作为主信息 |

## 0.1 全站必检项（每一页、每一轮都测，任何一项不过 = 该页不及格）

| 编号 | 必检项 | 测法（detect.mjs） |
|---|---|---|
| **G0** | **不白屏、不出 vite 报错层**：任何一页打开后没有 `vite-error-overlay`，`#root` 有内容；改路由前先建好文件、tsc 通过（K-UI-031） | detect.mjs 每个流程开头自动查，命中打印 `[G0 P0 …]`，该轮该页结果作废并直接打回 |
| G1 | **滚动可达**：在 1440×900 和 **1280×720** 两种尺寸下，用滚轮 / 触控板 / 拖滚动条都能滚到页面最后一块内容 | `{scroll}` 步骤：内容区真实滚轮 25×600px → `scroll.js` 的 `lastInView=true`、`notBottom=[]` |
| G2 | **只有一层主滚动**：页面主体只有一个滚动容器（侧栏 / 弹层自带一层除外）；不允许"卡片里再滚、卡片外不滚" | `scroll.js` 的 `nested=0`、`depth≤2`、`lockedCards=[]` |
| G3 | **不裁内容**：没有 overflow:hidden 把文字 / 图切掉又滚不出来；截断文字必须能悬停或点开看全文 | `clippedN=0`；audit.js `clipNoTitle=0` |
| G4 | **吸顶不遮挡**：吸顶 / 固定条合计 ≤ 视口高 15%（1280×720 下 ≤ 108px），且不盖住正文第一行 | `stickyCoverPct≤15` + 截图人工看。**口径 v2（2026-11-01 起）**：只算"此刻真的贴在上方"的条（fixed 照算；sticky 须 rect.top ≤ 所在滚动区顶 + 自己的 top + 1；互相包含只算一次）。v1 把页面上所有 sticky 元素加总，会把同一时刻只贴住 1 个的分段标题算成多个（UIMASTER 指出，UIAUDIT 认可）。scroll.js 输出 `stickyRule:"v2"` |
| G5 | **不留大空白**：内容没到底时，视口下 30% 不应是空背景 | `blankRows=0`（内容区在视口下部有东西）+ 截图 |
| G6 | 排版：字号只用 12/13/14/16/20（标题另计），行高 ≥1.3，单字不成行，对比度 ≥4.5（次要文字 ≥3） | `uirsi/audit.js` 全套 |
| G7 | 登录：所有"你确认"的操作都是一键，不弹原话输入框 | 拦截到的 POST 体里没有空 `owner_quote` 提示；界面无"请输入原话" |
| G8 | 最新可见：打开任何对象，默认看到的是**最新 / 当前**版本；新出的图 / 视频在列表里 10 秒内出现且有"新"标记 | 人工 + 截图 |
| G9 | 每页有返回路径（面包屑或返回键），浏览器后退不丢位置 | 人工 |
| G10 | **功能不回退**（项目方 11-01：“剧本的页面你改坏了……之前起码有前后帧，还有视频”）：改版前列旧版功能清单，新版逐项对照；旧功能只能“保留 / 换位置 / 收起（写明怎么打开）”，删除要有项目方或总调度原话 | 每页功能清单 vs 上一轮同页截图与清单逐项对照；少一项 = 该页不及格（UIRSI 加，规则 K-UI-030）。**UIAUDIT 测法**：基线清单 `apps/web/e2e/uiaudit/baseline_features.json`（35 条，来源 git `e66903c` 的 apps/web/src + `data/_archive/20261031/code/apps_web/` 归档的 22 个下线文件 + ux4/ux5 截图）；静态 `node regress.mjs HEAD`（基线里有、当前代码里消失的操作文字）；动态 `node detect.mjs flows_regress.json rN` → `node regress_check.mjs rN_detect.json`（只看正文，不算顶栏 / 步骤条里的字）。**全站找不到 = P0 打回；换了页面、原页面没有 = P1**；`dropped` 里写明原话出处的不算。每轮必跑，任何改版交付前先跑 |
| G11 | **小图都能放大**（项目方 11-01："我点这个小图标可以放大,这样就可以检阅图里面的东西是对还是错…把全部类似的地方都改一下"）：任何 < 160px 的 img 都能看原图大图。小图本身不可点 → 直接点开；原来点了有别的作用 → 原作用不变，改用悬停放大镜 / Alt+点 / 焦点上按 Z。大图要求：原图（不是缩略图）、说明这是什么 + 文件名、Esc 关、←/→ 翻同组、滚轮缩放 + 拖动。统一组件 ds/ZoomLayer.tsx | `apps/web/e2e/uimaster/crawl.mjs` 的 zoomCheck：每页抽 ≤10 张小图，悬停必须出 .zl-mag；Alt+点必须打开 .zl-box，原图 naturalWidth>0 且 src 不含 /api/thumb，Esc 能关。不过的记 g11_nozoom / g11_nobox / g11_noload / g11_thumb / g11_esc。规则 K-UI-M01。UIAUDIT 独立复核：`flows_g11.json`（同一断言，用 detect.mjs 跑） |
| G12 | **字 / 按钮不互相压住**（项目方 11-01 截图“排版问题，类似问题很多”：审片行首帧 #4 底边“渲染中 / 过期·需重出 / ✎ 改 / 🗑”四样叠在一起）：任意两个可见的文字或可点元素，盒子相交 ≤2px；图 / 视频格子一个角落只放一个定位容器（ds/TileBar：flex + gap，状态牌单行省略号 + title，格子 < 180px 宽时操作收进 ⋯），不许多个标签各自 absolute；按钮和状态一个都不删（G10）。规则 K-UI-P10 | `node apps/web/e2e/uipixel/scan.mjs rN --kinds=overlap --sizes=1280x720,1440x900,1920x1080 --themes=dark`：`overlap`=0（悬停才出现的格内按钮按“显示时”算；弹层 / 抽屉 / 吸顶条与正文不同层不算；刻意叠放的角标进 check.js 的 OVERLAP_OK 白名单）；格子特写 `node cardshot.mjs` 前后对比 |
---

## 1. 对象 × 操作矩阵

图例：● 必须有　○ 应该有　— 不适用。后端：✅ 有接口　⚠ 部分 / 需包装　❌ 没有（要后端补）。

### 1.1 剧本与写作

| 对象 | V | P | C | S | E | N | D | H | B | T | X | 后端接口 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 剧本（一次写作运行 story-run） | ● | — | ○ | ●（送导入 / 设为正式） | ●（改原文 / 返修） | ●（新建剧本） | ● | ● | ○ | ● | ● | ✅ `GET/POST /api/story-runs`、`…/artifact/{node}` GET/PUT、`…/retry`、`…/send-to-import`；删除 ✅ `/api/trash/object?type=story_run`；编辑 ✅ `/api/edits type=script id=run:{id}/P{n}` |
| 提纲 P0 | ● | — | — | — | ● | ●（粘贴 / 上传 .md .txt） | ○ | ○ | — | — | ● | ✅ story-runs artifact P0 |
| 各段产物 P1 故事线 / P2 大纲 / P3 剧本 / P4 分镜 | ●（排版全文） | — | ●（返修前后并排） | ●（采用这一版） | ●（改原文 / 反馈返修） | — | ○（挪到 superseded） | ● | — | ●（轮数 / 花费 / 阻塞） | ●（规则号 + 原话 + 字段） | ✅ artifact、retry；版本对比 ⚠（superseded 目录在，缺 GET 版本列表 → 用 `/api/edits/versions?type=script`） |
| 导入候选稿 | ● | — | ●（与现行剧本 diff） | ●（一键导入） | ○ | ●（粘贴 / 上传） | ● | ●（导入前自动备份，可还原） | — | ● | ● | ✅ `/api/script-inbox/*`、`/api/script-input/*`；删 ✅ `type=import_candidate` |
| 集（episode） | ●（本集全部镜头 + 成片入口） | ○（整集预览） | — | — | ○ | — | ○ | — | ● | ●（每集进度） | ● | ✅ `/api/episodes`、`/summary`、`/{n}` |
| 镜头（shot） | ●（剧本原文、表情、对白、声音、参考） | ● | — | ●（审片：通过 / 打回） | ●（改提示词 / 改字段） | — | ○ | ● | ●（多选） | ● | ● | ✅ `/api/shots/{id}`、`/edit`、`/review`；编辑 ✅ `/api/edits type=prompt` |

### 1.2 画面

| 对象 | V | P | C | S | E | N | D | H | B | T | X | 后端接口 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 首帧图 / 尾帧图（take） | ●（大图） | ●（放大、翻版本） | ●（A/B 并排 / 滑块） | ●（设为当前，一键 + 撤销） | ●（文字 / 框选 → 改图） | ○（上传替换） | ● | ● | ●（批量出 / 批量删） | ●（生成中 + 预计时长 + 取消） | ● | ✅ `frame-jobs`、`takes/{stage}/{n}/activate|lock|final|unlock`；编辑 ✅ `/api/edits type=image id=take:…`；删 ✅ `type=take`；"新图·未登记"⚠（流水线出图没进 takes，界面显示 0 版） |
| 视频（take） | ● | ●（播放器：进度、逐帧、静音、循环） | ●（两版同步播放） | ●（通过 / 设为当前） | ●（时间轴打点 → 改） | — | ● | ● | ● | ● | ● | ✅ `video-jobs`、`video-takes`；编辑 ✅ `type=video`；删 ✅ `type=take` |
| 成片（cut） | ● | ●（整集播放、按镜跳转） | ●（两版同步，已有） | ●（交付确认） | ○（按镜打回） | ●（合成新版本） | ● | ● | — | ● | ● | ✅ `/api/episodes/{n}/cuts`、`cut-job`、`cut/deps`；删 ✅ `type=cut` |

### 1.3 人物资产

| 对象 | V | P | C | S | E | N | D | H | B | T | X | 后端接口 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 角色 | ●（一页看全：脸 / 造型 / 单品 / 声音 / 出场） | ● | — | — | ●（改名 / 描述） | ●（新建人物） | ●（归档） | ○ | — | ●（缺什么） | ● | ✅ `/api/people`、`/api/assets/characters`；删 ✅ `type=asset` |
| 身份脸（face reference） | ●（大图） | ● | ●（候选并排） | ●（一键定脸） | ● | ●（上传参考） | ● | ● | — | ● | ● | ✅ `/api/projects/{slug}/characters/{cid}/references|confirm`、`/api/assets/{id}/refs` |
| 造型 look（设定图） | ●（三视图大图） | ● | ●（候选并排） | ●（选这张，一键 + 撤销） | ●（反馈 → 重出） | ●（新增造型） | ● | ● | ○ | ● | ● | ✅ `/api/looks/looks/{id}`、`/api/story-images/pick`、`/api/assets/{id}/versions|chain|chain/set-current`；编辑 ✅ `type=asset` |
| 单品（衣 / 鞋 / 饰 / 甲） | ●（单品图大图） | ● | ○ | ●（挂到造型 / 取下） | ● | ●（**拖图上传**） | ● | ● | ○ | ●（缺图 / 仅设定图） | ● | ✅ `POST /api/looks/wardrobe/items`、`…/{id}/images`、`PUT …/{id}`、`PUT /api/looks/looks/{id}`（挂到造型）；删 ⚠（`type=asset` 是否覆盖单品待核） |
| 场景 / 子场景 | ●（底图大图） | ● | ● | ●（定底图） | ● | ●（上传底图） | ● | ● | ○ | ● | ● | ✅ `/api/assets/scenes/{id}/plate` POST/DELETE |
| 道具·产品 | ● | ● | ○ | ● | ● | ● | ● | ● | ○ | ● | ● | ✅ `/api/props` GET/POST/PUT；删 ⚠ |

### 1.4 声音（项目方点名要的）

| 对象 | V | P | C | S | E | N | D | H | B | T | X | 后端接口 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 角色音色（Kokoro 说话人） | ●（人话描述：性别 / 音区 / 气质，不是 sid） | **●（卡上 ▶ 试听：同一句标准台词 + 本剧一句台词）** | **●（A/B：当前音色 vs 候选，同一句）** | **●（一键"用这个音色"+ 撤销）** | ●（语速 / 音高微调 → 重新试听） | ○（从音色库挑候选） | ○ | ● | — | ● | ● | ⚠ `GET /api/voices`、`POST /api/voices/{cid}/proposals`（只能"提议"）；**❌ 没有试听样本接口**（需 `GET /api/voices/{cid}/sample?text=` 返回缓存音频；`data/cache/tts/*.wav` 已有缓存可复用）；**❌ 没有候选音色库接口** |
| 旁白音色 | ● | **●（▶ 试听 ref.wav + 一句成片旁白）** | **●（候选 A/B，挑选页数据已在 `data/review_pages/narrator_pick/`）** | ● | ● | ○ | — | ● | — | ● | ● | ⚠ 文件可直接播：`/files/assets/voices/narrator_qag/ref.wav`、`/files/review_pages/narrator_pick/*.mp3`（已实测 200、支持 Range）；❌ 候选清单接口 |
| 对白 / 旁白音频（每镜每句） | ●（台词原文 + 说话人） | **●（逐句 ▶，整镜连播）** | ●（重配前后 A/B） | ●（采用） | ●（改语气 / 换说话人 → 重配） | — | ○ | ● | ○ | ● | ● | ⚠ `GET /api/post/dialogue-source`；音频在 `data/cache/tts/`（`/files/cache/tts/…` 可播）；❌ 缺"镜头 → 每句音频 URL"索引接口 |
| 配乐 BGM（整集） | ●（提示点 / 时长） | **●（整集播放 + 按镜跳到提示点，波形）** | ●（新旧 BGM A/B） | ● | ●（文字反馈） | ○（上传替换） | ○ | ● | — | ●（"需要重出"警告已存在于 cuts timeline） | ● | ⚠ 文件在 `data/music/ep0N.wav` + `.json`（`/files/music/ep02.wav` 实测 200）；❌ 没有 `/api/music` 列表 / 版本接口 |

### 1.5 模型与配方

| 对象 | V | P | C | S | E | N | D | H | B | T | X | 后端接口 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| LoRA | ●（触发词、训练图样张） | ●（样张） | ○ | ●（启用 / 停用） | ○ | ○（登记） | ○ | ● | — | ●（训练中 / 可用） | ● | ✅ `/api/loras`、`/registry`、`/{id}/status` |
| 出图预设 | ●（参数人话 + 样张） | ● | ●（同一镜两预设对比） | ●（设为默认） | ● | ● | ● | ○ | — | — | ● | ✅ `/api/render/image-presets` GET/POST/DELETE |
| 视频配方（出片方式 / 底模 + LoRA） | ● | ●（样片） | ○ | ● | ○ | — | — | ○ | — | — | ● | ✅ `/api/video-bases`、`/api/video-loras`、`/api/render/lanes` |
| 提示词模板 | ●（全文） | — | ●（版本 diff） | ● | ● | ● | ● | ● | — | ●（用在几镜） | ● | ✅ `/api/prompt-templates` GET/POST/PUT、`/usage` |
| 写作 / 出图模型（API 配置） | ● | — | — | ● | ● | ○ | — | — | — | ●（连通测试） | ● | ✅ `/api/llm/*`、`/api/render/endpoints` |

### 1.6 系统对象

| 对象 | V | P | C | S | E | N | D | H | B | T | X | 后端接口 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 修改记录（edit） | ●（反馈原文 + 改法 + 前后图） | ● | ●（改前 / 改后） | ●（采用 / 不采用） | — | — | ○ | ●（回滚） | — | ●（进行中） | ● | ✅ `/api/edits/*`（adopt / reject / rollback / versions） |
| 任务（job） | ● | — | — | — | — | — | —（取消） | — | ○ | ● | ● | ✅ `/api/jobs`、`/{id}/cancel` |
| 审计日志 | ●（谁、何时、对什么、结果） | — | — | — | — | — | — | — | — | — | ● | ✅ `GET /api/audit` |
| 回收站 | ●（缩略图 + 来自哪里 + 删除人 / 时间） | ● | — | ●（还原） | — | — | ●（永久删除：确认短语） | — | ●（批量还原） | — | ● | ✅ `/api/trash`、`/{id}/restore`、`/{id}/purge`、`/impact` |
| 账户 | ●（右上角当前账户） | — | — | — | — | — | — | — | — | — | ● | ✅ `/api/auth/me|login|logout|setup` |

---

## 2. 后端缺口（要后端补的，按优先级）

| # | 缺什么 | 为什么 | 建议接口 |
|---|---|---|---|
| BE-1 | 音色试听样本 | 角色音色没有可播文件，界面无法 ▶ | `GET /api/voices/{cid}/sample?line=std|ep` → `{url}`，先查 `data/cache/tts/` 命中，没有则排一个 CPU 小任务（不是渲染） |
| BE-2 | 候选音色清单 | 换音色只能手填 sid | `GET /api/voices/candidates?gender=` → 每个候选 `{voice, sid, sample_url, f0_hz, 描述}` |
| BE-3 | 镜头每句音频索引 | 逐句试听对白 / 旁白 | `GET /api/shots/{id}/audio` → `[{line, speaker, text, url, dur}]` |
| BE-4 | 配乐清单与版本 | BGM 无入口 | `GET /api/music?ep=` → `{url, json, cues[], versions[]}` |
| BE-5 | 流水线出图登记为 take | "新图·未登记"在详情里显示 0 版，看不到最新图 | 读取时自动登记 / `POST /api/shots/{id}/takes/register` |
| BE-6 | 单品 / 道具删除类型 | trash 的 type 列表里没有 wardrobe item / prop | `type=wardrobe_item`、`type=prop` |
