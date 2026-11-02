# 总调度决策 M-AUTOPIPE-01（11-03 00:1x）：把三个卡点做进流水线

> 项目方原话：“任何卡住的 bug 都是修改规则和 pipeline 的最好机会，你要从 code 和逻辑层去修复……要为以后的自动化工作流。这是核心目标。”
> 判断标准：下一集遇到同样的情况，不靠任何 agent 手工操作，系统自己就能走过去。

## 卡点 1：出图前资产不齐（第 1 集缺场景底图、3 个配角的脸、卓琳的音色）
现在的做法（修修补补）：总调度临时派 CAST-S / VOICE-S 去出候选，再派 GOLDEN-S 手工补清单、裁 SH1。
改成流水线阶段 **A（资产）**，接在导入之后、出图之前：
1. 导入成功 → 跑 `episode_ready`（已有）→ 每个缺口生成一个**资产作业**，写入 `data/pipeline/asset_jobs/<run>/`。这一步由系统完成，不经过 agent。
2. 资产作业分类型，由常驻服务调度执行（借道统一走 lanes hold，并行使用空闲的 GPU 道）：
   - `face`：新人物身份脸候选，P1 文字设定 → 文生图 → 出图契约（成年观感、OCR、人数）→ 取 3 个候选；
   - `scene`：场景底图候选，P1 / P4 的场景描述 → 文生图 → 契约 → 取 2 个候选；
   - `voice`：配角音色候选，P1 的声音描述 → voice_v2 设计 + 复刻 + check → 取 3 个候选；
   - `item`：单品图，如果项目方原图里有，就按规则从原图裁出（例如 SH1），否则生成候选；
   - `display_name / 造型排期`：直接从 P1 写入，这类不需要项目方挑。
3. 候选通过契约后，自动投递到 `/api/owner/inbox`，成为 pick 条目，网页上可以直接预览、试听，一键选定。
4. 项目方选定后，pick 处理器自动完成登记：face / scene / item 写进 manifest 并记 sha，voice 写进 voices_v2，然后推送到两台服务器。
5. 登记完成后重跑 `episode_ready`，全部就绪就自动进入阶段 B（金样首帧）。

## 卡点 2：项目方的选择没办法在网页上完成并生效
改成统一的 pick 机制：`POST /api/owner/pick` 先回 202，再按 kind 分派处理器（voice / face / scene / item），处理完自动登记、自动消失。INBOXPICK-S 已经在做 voice 这部分，其余 kind 接在同一个入口上。

## 卡点 3：agent 撞上额度就全线停摆
原因：太多事靠 agent 接力推进，比如手工派评委、手工推进、手工出候选。
改法：
- 流水线推进只靠常驻服务，资产作业、金样作业也由常驻服务执行，不需要 agent；
- 只有“写”和“评”这类必须用模型的步骤才由 agent 做，而且通过 inbox 请求文件派发（judge_request / review_request 已有）；
- 模型按 Fable 优先、Sonnet 补位的顺序选，Opus 只用于少数难活。

## 分工（1:50 额度恢复后执行，Fable 优先）
| 件 | 负责 | 说明 |
|---|---|---|
| 阶段 A：资产作业生成与调度 | FACTORY（常驻服务、lanes） + PROMPTFIX（face / scene 出图走唯一编译入口 + 契约） | 作业定义、调度、契约复用 golden_v2 / preflight，不另写一份规则 |
| voice 作业 | STYLE-V2 | 把 voice_v2 改成可由作业调用 |
| pick 处理器（face / scene / item） | INBOXPICK-S 的机制 + ASSETUX | 登记 manifest、sha、推送 |
| 阶段 B：就绪后自动出金样首帧 | PROMPTFIX + FACTORY | golden_v2 --shot 做成作业，由常驻服务触发 |
| 写进 SOP 与 episode_ready | SOPLOOP / HOLLYWOOD | PIPELINE_SOP_V2 第 8、9 步改成“系统自动” |
| 复审 | OVERSIGHT-F（Fable） | 判断标准：下一集能否无人值守走过阶段 A、B |

## 过渡期
CAST-S 正在手工出的候选可以继续出完，作为阶段 A 的样例数据，出完后由 pick 机制接走。之后不再派这类一次性 agent。

## 11-03 02:xx 总调度裁定（AUTOPIPE-A 交付后，ISS-1103-003637-9d25）
1. apply_meta 开（P1 直写 display_name/造型骨架/排期，不需项目方挑）；push 保持开（verified_install 核 sha，整闭包交 FACTORY auto）。
2. render / voice / golden 暂关：等 OVERSIGHT-A（Fable）复审通过 + RESTARTFIX-O 修好重启并复审 → 受控重启（resident + :8800）→ owner_pick replay → 再开。
3. sheet（配角造型设定图）作业类型批准，纳入阶段 A。
4. test_episode_ready_series10_v2_ep1_lists_all_gaps 断言过时（卓琳音色已选），随下一轮修。

## 11-03 02:0x 执行状态（1:50 定时派单核对：分工表大部分已由 Opus 修 bug 线完成，不重复派）
- 阶段 A 作业/调度/pick 处理器（face/scene/item/sheet/look）：AUTOPIPE-A 建 → OVERSIGHT-A 两轮复审 → AUTOFIX-O 修 P0/P1；resident 已 --detach 受控重启，apply_meta+render 开。进行中：sheet I4 豁免 + sheet→item 自动裁图链（AUTOFIX-O）。
- 重启修复：RESTARTFIX-O 修 → OVERSIGHT-R 第 18 轮“可受控重启、不可开自动”→ 01:48 真 :8800 受控重启成功（managed=true）。遗留 P1：ps1 不返回 + 看门狗未脱离调用方作业对象（RESTARTFIX-O 修）。
- V1 泄漏（导入器/状态表/ref_switch/写作链全局头/规则正文）：V2CUT-O、HEADER-O 已根治。
- sv-17：SV17-O 待命，等 AUTOFIX-O 收工后冻结 cut + deploy（--verify-shot 8）。
- 未开：voice 作业开关、golden（阶段 B）开关——第 1 集 sheet 选定、episode_ready 全绿后，派 Fable 复审阶段 B 执行器再开。
