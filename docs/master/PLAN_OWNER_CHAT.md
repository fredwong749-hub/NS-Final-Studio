# PLAN · 通知中心 → 带 chat 的项目方助手（项目方 11-03 16:0x 需求；总调度出 plan 待项目方过目）

项目方原话：通知"设计和通知做的很糟糕……一旦需要我做什么就直接谈信息出来……改成带 chat 的 llm 模型……我在 chat 里点击、回复、upload……这个 chat 通知自动帮我完成对应的工作……整个到这个网页系统来，uiux 也要统一修改。llm 模型用我 flash 那个 api，现在为了省钱，你用 fable 来接管，等项目开发完成后再切换到 flash api"。

## 0. 原则（不变）
- 只有一条登记链：chat 的每个动作都落到现有后端入口（owner_pick / decide / gate / inbox / undo），不另起第二套状态（C-10、K-OPS）。
- 需要项目方做的事，系统主动说"现在要你做什么、为什么、点哪里"；不需要项目方的事不出现（C-11 只问删除/花钱/越权/推翻）。
- 模型只做"翻译与整理"：把系统待办翻成一句人话、把项目方的回复翻成结构化动作；最终执行仍由后端规则校验（模型不能绕闸门、不能替项目方做 C-11 四类决定）。
- 成人相关候选只在自有机器看图，不经外部 API（K-REV-V01）。

## 1. 信息架构（每条通知 = 一句"要你做什么" + 可点动作）
| 来源（现有） | 一句话模板 | 动作（按钮 = 后端入口） |
|---|---|---|
| decide（花钱/删除/推翻/导入新季） | "需要你批准：{事}。不批准则{后果}。" | 批准 / 不批准 → POST /api/owner/decide |
| gate（稿子等看） | "第 {ep} 集{阶段}写好了，看完点'用这版'。" | 用这版 / 退回修改（附意见）→ owner_gates |
| pick（挑一张） | "第 {ep} 集 {镜} 首帧请你挑：系统推荐 {n} 号（理由）。30 分钟没挑系统代选，之后可改。" | 用推荐 / 挑 n 号 / 都不行重出 → POST /api/owner/pick、undo |
| spot（抽查） | "抽查：这张已自动通过，看一眼。" | 没问题 / 有问题（原因）→ owner_pick spot 入口 |
| asset（资产缺口要你挑） | "第 {ep} 集缺 {角色} 身份脸 / 场景底图，候选 {n} 张。" | 挑 / 上传参考图 → inbox 登记 |
| 系统卡点（只读） | "{卡点}，系统已派 {who} 处理，不需要你做事。" | 无按钮 |
- 排序：要你做的在前（按阻塞程度），只读在后；每条带"为什么找你"一行。
- 一键生效：按钮点下 = 后端入口 + 审计行（已有 data/audit）。

## 2. chat 助手（LLM）
- 入口：#/queue 顶部常驻对话框（不是独立页）；每条通知可"在 chat 里回复"。
- 模型用途开关：config/llm_providers.json 新增 purpose `owner_chat`：开发期 provider=claude（Fable，经现有 agent_dispatcher 的 claude 通道或 API key），完成后改为 provider=abliteration model=abliterated-model-large-flash。只改配置不改代码。
- 工具（function calling，白名单，服务端执行并校验）：
  - list_todo() → 现有 /api/owner/queue
  - pick(item_id, choice) → /api/owner/pick；decide(item_id, verdict, note) → /api/owner/decide；gate(ep, stage, verdict, note) → owner_gates；undo(item_id)
  - upload_ref(file, kind, character/scene) → 存 data/factory/inbox + 登记（走现有 inbox 规则，sha 去重）
  - explain(item_id) → 把系统理由（contract items / rubric）翻成人话（只读）
- 主动提醒：常驻每拍（autoflow_resident）把"新出现的要你做的事"合成一句推到 chat（和网页通知同源），可选推到手机（已有 PushNotification 通道的话复用）。
- 回复解析：项目方自然语言 → 模型给出"拟执行动作 + 参数"，chat 先回显"我将：挑 3 号 / 退回第 2 集大纲并附意见……"，项目方点确认才执行（C-11 四类必须确认；其余可设"直接执行"开关）。
- 上传：chat 里拖入图片/文件 → upload_ref；成人相关图不上传给外部模型，只本地登记。

## 3. UI/UX 统一
- 一套组件（apps/web/src/v3）：通知卡（标题 = 要你做什么，副标题 = 为什么，右侧按钮 ≤3 个，缩略图可放大）、chat 面板、动作回显。
- 统一文案规范：动词开头、不出现系统内部 id（镜号/集数用人话）、每条 ≤2 行；颜色只表阻塞程度（红=阻断、黄=等你、灰=只读）。
- 移动端可用（项目方常用手机看）。

## 4. 分期（RSI 实施包：Phase R 达标前不加新功能——分期 1 属"把现有通知改成直接说要做什么"，可与 Phase R 并行；2–4 等冒烟门 8/8）
1. **通知直说**（1 轮）：现有 5 类通知按 §1 模板改文案 + 按钮，不加 chat。验收：项目方打开 #/queue 不用问"这要我干嘛"。
2. **chat 只读**（1 轮）：对话框 + list_todo/explain，模型 = Fable。验收：问"现在要我做什么"得到正确清单。
3. **chat 动作**（1–2 轮）：pick/decide/gate/undo/upload，确认后执行，审计行齐全。验收：全流程在 chat 内完成一集的挑图与放行。
4. **切模型**：owner_chat provider → abliteration flash；回归 2–3 的测试。

## 5. 测试与冒烟
- 后端：tests/test_owner_chat.py（工具白名单、未确认不执行、C-11 四类必须确认、成人图不外传、动作落审计）。
- 前端：tsc + 通知文案快照测试。
- 冒烟门 G8（无人值守）不受影响：chat 是给项目方用的，不在冒烟路径上。

## 6. 请项目方点选（C-20 选择题）
- Q1 分期 1 现在就做（与 Phase R 并行，1 轮）还是全部等冒烟门 8/8 之后？
- Q2 chat 执行方式：A 一律先回显再确认；B 只有 C-11 四类确认，其余直接执行。
- Q3 开发期模型：A Fable（Claude，经 Orca/CLI）；B Sonnet（更省）。完成后都切 flash。
- Q4 主动提醒除了网页，要不要推手机（有则复用现有通道）？
