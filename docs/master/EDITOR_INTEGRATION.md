# 修图编辑器 × 自动化出图：整体架构（总调度 fredw-2b，11-02 13:0x，L-117 草案）

> 项目方原话（11-02 13:0x）：“系统有时在资产出，也就是剧本图出现的时候，我可以进行修改。点击‘修改图’按钮，就可以跳转到这个页面进行局部修改。我觉得可以把这个‘修图’的功能跟你‘自动化作图’的功能做一个整合……人在你自动生成图片后，如果反馈不好，我可以来到这个 Editor 里面进行局部修整；修整完之后，采用这个最新版本，更新到剧本相关的镜头里……先来个 full picture……整一个 infra 的 architect 问题，才是往下走。”

## 0. 一句话
编辑器不是一个独立工具，而是自动化出图链路上的“人工分支”。人修过的图和自动出的图进同一本账、过同一套质检、走同一条“采用 → 下游重做”路径；每一次人工修改都变成系统的学习信号。

## 1. 现状（各块已经有什么）
| 块 | 现状 | 位置 |
|---|---|---|
| 自动出图 | producer 派单 → ComfyUI → 契约打分（Q1 / Q1a / Q3 / V6 / gaze）→ 机签 → 当前版本 | tools/autopilot/producer.py，tools/vqa/* |
| 版本账本 | 每镜 takes.json（image / last / video），active 指当前版本，locked 是项目方定稿锁 | data/renders/epNN/SN/takes/，两台服务器各一份 |
| 资产 | 设定图 / 单品 / 身份脸，set_sheet 登记，asset_refs 决定每镜参考图 | data/assetmaster，asset_refs.py |
| 下游失效 | E24：首帧签名变了 → 自动重出；refs 变了 → 受影响的镜重出 | producer |
| 局部重绘 | 已有矩形遮罩重绘作业 | :8800 frame / regen |
| 编辑器 | 只有设计稿 image_edit.html，产品里没有 | data/review_pages/filmui/ |
| 反馈 | FEEDBACK 后台刚开（反馈 → 分类 → 修复 → 补检测） | docs/feedback/ |

## 2. 目标流程
```
自动出图 ──► 质检 / 机签 ──► 当前版本（镜头 / 资产）
                               │  项目方觉得不好
                               ▼
                 [修改图] 按钮（镜头行 / 总览帧 / 资产卡 / 待你看 / 反馈）
                               ▼
        编辑会话 edit_session（带上下文：镜号、阶段、底版 take、编译提示词、参考图、底模配方）
                               ▼
         局部操作：遮罩重绘 / 修手 / 修脸 / 换背景 / 重打光 / 扩图 / 改姿势 / 整张重出
           每次操作 = 一个作业 → 产出一个新 take（parent = 上一版，origin = manual_edit，记操作参数）
                               ▼
             自动质检（同一套契约），结果就地显示；人可以“仍然采用”（记审计）
                               ▼
                    [采用到镜头] / [采用为资产]
                               ▼
  采用 = 设为 active + 加项目方定稿锁 + 下游失效：
    · 首帧变了 → 尾帧（FL2V 依赖）、视频按签名重出
    · 资产（设定图 / 单品）变了 → 受影响的镜列表先给人看数量，确认后按 E24 重出
                               ▼
     学习回路：这次人修了什么（遮罩区域 + 操作类型 + 原因）→ FEEDBACK → 补规则 / 补闸门 / 回归样本
```

## 3. 关键设计决定
1. **一本账**：人工版本写进同一个 takes.json，字段 origin=manual_edit、parent、ops（操作链）、editor_session。不另起账本，界面、质检、同步、回退都复用。
   **（SYSARCH 评审补充，11-02）一本账的前提是“一个写者”**：现在每镜 takes.json 有 4 类写者（服务器 producer、:8800 API、merge_pull、register_takes / night），锁只是进程内 RLock（pipeline.py:240 注释“只管本进程”），笔记本和服务器各一份、各写各的（ARCH_ROADMAP §11 / Top15 #5、#16）。编辑器再加一个写者会让问题更重。定为：
   - **权威副本 = 镜头所属主机**（data/state/netfix/partition 的 images 归属，经 state_paths 读）。笔记本那份是只读副本，只由 puller 按 outbox 事件更新；**:8800 不直接写服务器镜头的 takes.json**。
   - 编辑器的写入一律变成**命令**投到所属主机的 inbox（edit_op / adopt，带幂等键 op_id），由该主机 producer 这一个进程落账，再发 outbox 事件回笔记本。
   - takes.json 加单调递增 seq（每次写 +1）；merge_pull 见到副本 seq ≥ 权威 seq 的冲突就报警，不再“后写覆盖”。
2. **编辑在镜头所在的服务器上跑**：作业按镜头分区派到对应主机（避免两台账本不同步，E25 的教训）。编辑作业走“交互优先”队列：插到该主机队列最前面，并且预留一条交互道（默认 gpu36:1 的实验窗口改成“交互优先 + 空闲时实验”），保证人点了几十秒内出图。
3. **质检不豁免**：人修的图也跑契约。不过就显示原因；人可以“仍然采用”，这算项目方本人决定，记审计，并作为误拦样本进机签回归集。
4. **采用是一个事务**：设 active → 加锁 → 写失效清单 → 推到服务器 → 拉回笔记本，全部成功才算完成；失败就回滚到原 active。采用资产前先展示“将影响 N 镜”。
   **（SYSARCH 评审改写）跨两台机器 + 不稳定跳板做“全部成功否则回滚”的分布式事务做不可靠**（推送成功、拉回超时时，回滚本身也要跨机，会留下半状态）。改为：
   - **采用镜头 = 所属主机本地的一次原子写**：一次 takes.json 原子替换里同时写 active、locked、invalidate（下游尾帧 / 视频失效清单）、seq+1、op_id。成就全成，不成就没发生，不需要回滚。
   - 笔记本只投 adopt 命令（op_id 幂等，重投不会重复采用），界面显示“采用中”直到 outbox 回执；超过 SLO（建议 60 s）未回执 → 显式报“采用未确认”并开 SENTINEL 单，不静默。
   - **采用为资产**不走事务：资产是跨主机共享的决策文件，走 FACTORY 的目标状态（inbox expected_refs + deps 闭包按 sha，K-OPS-F02/F03/F09）——笔记本改资产登记 → sync push → 两台各自 preflight 比对 → 受影响镜由各自主机按 E24 重出；“影响 N 镜”的数字由 deps 闭包算，不另写一套。
5. **底模可以混用，但要守身份**：编辑器里可以用 Qwen / FLUX 3 Klein / MOSS 修，采用前强制 Q1 身份分 ≥ 原版，保护 L-086。
6. **上下文自动带入**：编辑会话打开时，提示词、参考图槽、景别、镜头、灯光都从这一镜的编译结果带入，人只需要涂遮罩、写一句改什么。
7. **学习回路**：每次采用的人工版本，自动生成一条 FEEDBACK 记录（原版 vs 修后、遮罩位置、操作类型）。FEEDBACK 负责分析“为什么自动没做好”并落成规则或检查。人工修改的频率按类别进 RSI 线 1 的分数，修得越少分越高。
8. **一切走现有闸门**：freeze_guard、arch_scan、system_version 照旧；编辑器后端是 :8800 的新模块，producer 侧只加“接受外部 take + 失效”接口。
9. **（SYSARCH 评审新增）交互优先用“道”，不用“插队”**：ComfyUI 队列插到最前面也抢不了正在跑的作业（单张 40 s–2 min），“几十秒出图”靠插队保证不了。定为：在 config/factory/hosts.json 给交互道加 roles=["interactive","image"]（不另建道表，4-2 已收口），编辑器只派交互道；人没开编辑器时 producer 照常用它出生产图，人一打开编辑会话就不再往这条道派新的生产单（不杀正在跑的）。SENTINEL 的 GPU 利用率按“交互道空等不计生产空闲”口径算，另加交互出图 p50 SLO。
10. **（SYSARCH 评审新增）状态放哪 / 冻结锁关系**：edit_session、版本树、操作参数、“仍然采用”审计 = 运行期状态 → data/（经 state_paths；会话随镜头放 data/renders/…/edits/），不进 config/；编辑配方（底模、遮罩参数默认值）= 人写的配置 → config/editor/。编辑器运行只写 data/，冻结锁不拦（冻结只管代码目录）；编辑器后端代码改动照常受冻结锁和 arch_scan 约束。

## 4. 组件与归属
| 组件 | 内容 | 负责 |
|---|---|---|
| 入口按钮 | 镜头行首帧 / 尾帧、总览帧右键、资产卡、待你看项、反馈项上的“修改图” | UIRSI2 |
| 编辑器页面 | #/image-edit?session=…，胶片 A 风格（设计稿已有） | FILMUI |
| edit_session API | 新建会话（带上下文）、操作 → 作业、版本树、采用 | UIRSI2（:8800）+ FACTORY 评审 |
| 编辑作业 | 遮罩重绘 / 修手 / 修脸 / 重打光 / 扩图 / 换背景；多底模配方 | IMGLAB（配方），IMGFIX（编译层） |
| 交互优先队列 | producer 接受 interactive 作业并插队；交互道预留 | DEBUG-RSI + NETFIX |
| 采用事务 + 下游失效 | set active / lock / E24 失效 / 推送 / 拉回 / 回滚 | DEBUG-RSI（producer）+ WORKFLOW（同步） |
| 质检 | 对 manual_edit take 跑契约；“仍然采用”进机签误拦样本 | VQAGATE |
| 学习回路 | 采用的人工版本 → FEEDBACK 记录 → 规则 / 闸门 / 回归 | FEEDBACK |
| 架构评审 | 一本账、事务、跨主机一致性 | SYSARCH |

## 5. 分期
- **P1（最小闭环）**：镜头首帧“修改图” → 编辑器带上下文打开 → 矩形或画笔遮罩重绘（Qwen）→ 新 take 进账 + 质检 → “采用到镜头”（active + 锁 + 视频失效）。
- **P2**：修手（HandDetailer）、整张重出变体、资产“采用为资产”（影响数量确认 + E24）、交互优先队列。
- **P3**：重打光（Light-Migration）、换背景、扩图、FLUX 3 Klein / MOSS 底模、改姿势；学习回路接 RSI 分数。

## 6. 风险
- 两台服务器账本不同步：编辑必须派到镜头所在主机（E25），采用后立即拉回。**（SYSARCH）只“派到所属主机”不够**：借道 / 改分区会让镜头换主机，换主机时 takes.json 要随所有权交接（旧主机停写 → 发最后 seq → 新主机接收后才开始写），否则两边各写一段。P1 前必须先有 §3-1 的单写者 + seq；交接流程归 NETFIX（partition 写方）+ DEBUG-RSI（producer），见 ARCH_ROADMAP §11。
- **（SYSARCH）命令丢失 / 重放**：inbox 命令跨跳板可能重复到达或晚到 → 所有编辑命令带 op_id，producer 落账前查重；晚到的 adopt 若底版已不是 active（期间又采用了别的）→ 拒绝并回执“底版已变”，不悄悄覆盖。
- **（SYSARCH）笔记本副本过期时人在上面编辑**：会话打开时带上副本 seq；命令到主机时 seq 落后 → 主机先回执最新版本，由人确认再编辑，避免基于旧图修改。
- 采用资产会引发大面积重出：必须先展示影响数量并确认。
- 人工版本被自动流程覆盖：采用即加定稿锁，E23 保证不再自动重出。
- 交互作业抢生产：交互道只在人打开编辑器时优先，空闲时还给生产 / 实验。


## 附录 A：接口契约（SYSARCH 统一，11-02；各方照此实现，改动先改这里）

> **附录 A 为准**（总调度 11-02 13:2x 定）。排期：先做 ARCH_ROADMAP §11 结构问题 #16 第 1–3 步（sv-11），再上 P1；不走“只限笔记本镜头”。在此之前 FILMUI 先做编辑器页面 / 出图 / 对比 / 版本树（接现有出图接口），“采用到镜头”按钮显示“等一本账上线”并禁用。
> 合并了本文 §3 与 docs/debug/EDITOR_PRODUCER_DESIGN.md（DEBUG-RSI）。两处冲突按下面裁定：**adopt 在镜头所属主机本地执行，一次原子写，不做跨机推送 / 回滚**（原设计第 4–5 步“推送 → 拉回、失败回滚并撤回远端”取消）；理由见 §3-4 评审改写。

### A1. 权威与传输
- **权威副本**：镜头所属主机（`state_paths.read_state("netfix/partition")["images"]`）上的 takes.json。笔记本副本只读。
- **传输**：笔记本 :8800 → 所属主机，统一 `tools/netfix/rssh.run_retry(host, "cd <repo> && <python> tools/autopilot/producer.py <子命令> --json -", input=<JSON>, timeout=<见下>, tries=1, text=True)`；repo / python 从 `tools/factory/hosts.py`（hosts.server_root / hosts.python）取，不写死（K-OPS-Y02 服务器环境契约测试要覆盖）。
- **幂等**：每个命令带 `op_id`（UUID，:8800 生成）。所属主机在 `data/producer/edit_ops.jsonl` 记已执行的 op_id；重复到达直接返回上次结果。
- **返回**：JSON 一行 `{"ok": bool, "code": "<下表>", "seq": <落账后 seq>, ...}`；rc≠0 或非 JSON = 传输失败（界面显示“未确认”，不是“失败”）。

| code | 含义 | 界面 |
|---|---|---|
| ok | 已落账 | 显示新版本 |
| wrong_host | 镜头不归这台（分区已变） | 刷新所属主机后重试一次 |
| stale_base | 底版 / 副本 seq 落后 | 先拉最新版本给人确认 |
| parent_missing / bad_file | 底版不存在 / 文件坏 | 显示原因 |
| contract_fail | 契约不过且没选“仍然采用” | 显示失败项，给“仍然采用”按钮 |
| identity_drop | Q1 身份分低于原 active（L-086） | 拒绝，force 也不放行 |
| locked_by_other | 另一采用进行中（adopt 锁） | 稍后重试 |

### A2. takes.json 新增字段（DEBUG-RSI 落实，ns_render.pipeline 唯一写入口）
- 文件级：`seq`（int，每次写 +1）、`last_op`（op_id）。
- 每个 take：`origin`（"auto" | "manual_edit"）、`parent`（int|null）、`ops`（list：`{type, mask_ref, prompt_delta, model, params}`）、`editor_session`（str）、`inputs_sha`（取底版）。
- 采用相关：`locked[stage]=n`、`locked_by={by, n, at, op_id, force}`、`invalidations=[obj…]`。

### A3. producer 子命令（DEBUG-RSI，tools/autopilot/edit_bridge.py + producer.py CLI，在所属主机运行）
| 子命令 | 输入 | 行为 | timeout |
|---|---|---|---|
| `accept-take` | op_id, run, sid, stage, file（主机本地路径）, parent, ops, session, base_seq | 校验 host / parent / 文件 → `_add_take(activate=False)` → 跑契约（同自动出图，口径见 A6）→ 返回 take_n + postflight；不计次、不自动设当前 | 300 s |
| `adopt` | op_id, run, sid, stage, n, by, force, base_seq | 预检（Q1 ≥ 原 active；契约不过且 !force → contract_fail）→ **一次原子写**：active=n、locked、locked_by、invalidations（首帧 → 尾帧 + 视频；尾帧 → 视频）、seq+1 → 写 current_changes.jsonl + log manual_adopt → 发 outbox 事件 `adopt`。adopt 锁 `data/producer/locks/adopt_<sid>.lock` 只在本机 | 60 s |
| `adopt-asset-preview` | op_id, asset_id, take | 只读：按 deps 闭包 / asset_refs 反查受影响镜 → `{affected_shots, list}` | 120 s |
| `submit-interactive` | op_id, job（编译好的 graph）, sid, editor_active_until | 进 interactive_q，每拍先派，只派本机，ComfyUI `/prompt` front=true，绕过积压闸 E05 | 30 s |
- **采用为资产（P2）**不在 producer 做事务：笔记本改资产登记 → FACTORY `sync push`（目标状态 + sha，K-OPS-F02/F03/F09）→ 各主机 preflight 比对 → 受影响镜按 E24 自然重出。

### A4. 笔记本副本更新（WORKFLOW + NETFIX）
- 所属主机 outbox 事件 `take_added` / `adopt`（含 sid、stage、seq、文件 sha；**outbox manifest 现在没有 seq 字段，FACTORY 补**）→ puller 拉单镜 takes.json + 新图到笔记本副本（`merge_pull` 唯一调用方是 puller，持 puller.lock）。
- 副本只接受 seq 更大的版本；seq 相同而内容不同 = 冲突，报警（SENTINEL），保留权威。
- :8800 的“采用中”等 outbox `adopt` 回执；60 s 未到 → 显示“采用未确认”并开单（不静默，不重试 adopt——op_id 幂等可安全重投一次）。

### A5. edit_session（UIRSI2，:8800；状态放 data/，经 state_paths）
- 位置：`data/renders/<ep>/<sid>/edits/<session>.json`（随镜头）。
- 字段：`session, run, sid, stage, host, base_n, base_seq, context{prompt, refs, size, camera, lighting, recipe}, ops[{op_id, type, mask_ref, params, model, take_n, status, code}], opened_at, last_heartbeat, editor_active_until`。
- 心跳：前端每 30 s 续 `editor_active_until = now + 10 min`；随每个 `submit-interactive` 带过去。

### A6. 交互道与 editor_active（NETFIX + DEBUG-RSI；道表只在 hosts.json）
- `config/factory/hosts.json` 给交互道加 `roles` 含 `"interactive"`（默认 gpu36:1）；不另建道表。
- **editor_active 落点（NETFIX 13:1x 提，SYSARCH 定）**：:8800 经 state_paths 写 `data/state/editor/active.json`（`{lane, until, session}`，心跳续期），NETFIX dispatch 只读、在算 hold 时把未过期的交互道并进所有生产 / 实验 producer 的 hold，随现有 control 推送（三方合并 + 指纹重推）到服务器，不另开通道；所属主机 producer 另以 interactive 作业自带的 `editor_active_until` 兜底。过期自动还给生产 / 实验，不杀在跑的。gpu33 分区的镜：插到 gpu33 最空的道，不预留。
- SENTINEL：交互出图 p50 / p90（S-int）；GPU 利用率口径里交互道在 editor_active 期间的空等不计生产空闲。

### A7. 契约口径（VQAGATE）
- manual_edit take 跑和自动版本同一套契约（Q1 / Q1a / Q3 / V6 / gaze）；Q1 额外要求：对 L-086 的锚分 ≥ 原 active 的锚分 − 0.03，且仍按三段线判（identity_drop，force 不放行）。比的是锚分（evidence.anchor，不是身份库 top-k）；容差 0.03 = 同一人不同版本 ArcFace 的正常波动（GATE_CALIBRATION §17 / §18），不留容差会把手修后的正常版本误拦。
- “仍然采用”（force）= 项目方本人决定：记 locked_by.force=true + 审计；契约被拦而被 force 采用的样本记 `tools/vqa/autosign.py false-reject <file> <说明>`（data/vqa/autosign_false_reject.jsonl，机签误拦面），VQAGATE 亲看后再转成 data/vqa/regression/ 用例（不自动进：force 可能是审美决定，不一定是闸门判错）。
- manual_edit take 不参与 auto_current 自动选当前。

### A8. 测试归属（每方随实现交）
DEBUG-RSI：A2 字段 / A3 四个子命令（含 op_id 重放、wrong_host、stale_base、identity_drop、并发 adopt 锁、一次原子写无半状态）；WORKFLOW + NETFIX：A4 seq 冲突与回执；UIRSI2：A5 会话与“未确认”显示；NETFIX：A6 editor_active 过期还道；VQAGATE：A7；SYSARCH：K-OPS-Y02 契约测试加 accept-take / adopt 的服务器环境用例 + arch_scan“笔记本代码直接写服务器镜头 takes = 退化”。
