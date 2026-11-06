# 流水线里“等项目方”的点（L-215 / L-216 盘点，W-KICKOFF 11-07 04:3x JST）

L-215：开工后不再等项目方，原来要他点的改成开项目时定好的规则 / 默认 / 代选 / 自动兜底，事后汇报。
L-216：成人镜是项目级常设授权，新出现的成人镜自动写进触发清单。
规则文件：`config/pipeline/kickoff.json`（每部剧一份 policy，缺的项按零等待默认）；确认单和答复用 `tools/pipeline/kickoff.py`（checklist / record / sync-adult / policy）。
没有 kickoff.json 的根目录（老测试、临时根目录）照旧行为，`kickoff.configured()` 为 False。

| 等待点 | 位置 file:line | 在等什么 | L-215 替代 | 状态 |
|---|---|---|---|---|
| 成人镜等触发 `adult_wait_owner` | tools/autopilot/producer.py:3918（`adult_blocked` :674） | 项目方在网页逐镜点“出这一镜” | **开项目规则** adult_authorization=all：`kickoff.sync_adult` 经 `adult_trigger.apply` 写触发清单（by="项目方（开项目常设授权 L-216）"，via="kickoff"，先审计再原子写，只增不减），**只认导入稿 shot.adult**（PS-MASTER 11-07：普通镜碰到成人资产被拦的，仍要项目方本人触发）。调用点有两个：导入后 `import_events.append_import`，以及 :8800 每拍 `owner_delegate.tick`。producer 不用改 | ✅（现在真实数据 dry-run 结果为 0 个待加，63 个对象 01:4x 已触发） |
| sop_gate `pending_owner`（成人镜） | tools/master/sop_gate.py:160, :1107 | 同上（阶段判定把这些镜记成待项目方） | 跟着触发清单走，常设授权进清单后这些镜就不再算 pending_owner | ✅（随上一条） |
| 资产作业 `awaiting_pick` | tools/pipeline/asset_worker.py:535, :1420–1446；asset_jobs.py:626 | 项目方挑候选 | **代选** picks=delegate_always：`owner_delegate.active()` 一直返回 True，项目方在网页做决定也不再让代选到期，只有他明确撤销（revoked）才关。他的选择照样随时覆盖 | ✅ |
| 代选到期（L-136 `on_owner_decision`） | services/api/ns_api/owner_delegate.py:144 | 项目方做任何决定后代选关闭，之后改成等他挑 | 同上（`delegate_always`，:135） | ✅ |
| 每集“确认本集造型” | services/api/ns_api/look_confirm.py:185（sync_picks） | 项目方逐集点确认 | **默认** look_confirm=auto：资产齐了的集直接 `confirm(via="kickoff")`，造型来自 P1 排期、hub_episode_looks、shot_looks，不再投通知，旧通知作废 | ✅ |
| 资产失败“需要修改描述”卡（W-FIX-PIPE #13，今晚加的） | tools/pipeline/asset_worker.py:701（escalate）→ :716 | 项目方写一句新描述 | **自动兜底** asset_failure=best_effort（`fallback_ladder` :830），在自动重排用完之后依次走三步：① 去掉易出错元素（logo、字样、商标等，OCR 读到字时再去掉图案和印花），提示词里删掉含这些词的分句并把词加进负面词；② 换一批远种子（+50000）；③ 只有单品会借：同一角色另一套造型里同部位、描述最接近的已通过图，系统自动选用登记；设定图不借。三步都失败就标 best_effort、记日志，继续往下走；资产页顶部显示“尽力版”小标记（GET /api/assets/best-effort） | ✅ |
| `asset_revise` 红卡（owner_queue） | services/api/ns_api/owner_queue.py:823, :689 | 同上（红色，计入待办数） | asset_revise=notice：所有 asset_revise 改成灰色“事后可改”告知，不计入待办、不挡流水线；卡上仍有“修改”（L-123），也可以在对话里说 | ✅ |
| review_needed 当阻断 | sop_gate.py:467、series10_video/build_jobs.py:225、lane_roles.py:141 | 项目方复核尽力版 | review_needed=never_blocks：三处原本就按通过算，只记录不挡。规则已写进 kickoff.json | ✅（已是） |
| sop_gate 里写着“项目方”的挡 | sop_gate.py:1107（只有成人镜这一处） | 成人镜触发 | 见第一行 | ✅ |
| 剧本闸门 owner_gate（P1 / 各集 awaiting_owner_*） | tools/script_rsi/owner_gate.py:169（act）；owner_delegate.py:477（waiting_gates） | 项目方点“用这版 / 修改” | **代选**：gate 在代选范围里，现在代选一直开，评委分过线就自动 approve。P1 归开项目确认（kickoff 确认单） | ✅（评委不过线 / owner_direction 见下） |
| 剧本 `owner_direction`（评委升级要项目方定方向） | owner_delegate.py:10–12, :487 | 项目方定剧情方向 | 写死不代（代选不能冒充项目方） | ⏳ 仍等，见下 |
| 首帧代选不代成人镜 | owner_delegate.py:221 never_reason、:817 | 项目方挑成人镜首帧 | 写死不代（agent 不看成人内容）。producer 自己按契约 + 看图闸门自动采用，所以这里只是覆盖入口，不挡流水线 | ⚠️ 不挡（待 E2E 实测核实） |
| owner_queue `decide`（删除 / 花钱 / 推翻旧决定 / 导入新季） | owner_queue.py:280, :664 | 项目方批准 | 硬规矩，不在开工流程里 | ⏳ 保留（规矩） |
| 机签抽检 `spot` | owner_queue.py（spot_items） | 项目方抽看 | 系统已自动签过，只做抽检，不挡 | ✅（已是） |
| 重出 / 修改要项目方去页面 | （新）services/api/ns_api/owner_redo.py | — | 每镜的首帧、尾帧、视频各一个“重做”按钮，点一下即生效，不弹确认。首帧和尾帧走 `producer reject --n 0`（master_rejects），视频写 master_rejects[video:镜号]，由 vidgen.check_lip_redo 处理（master_rejects 按 mtime 缓存），不受重出次数上限限制，也不占口型重出次数；成人镜如果还没进触发清单，会提示“在等进触发清单” | ✅ |

## 还在等项目方的（以及原因）
1. **剧本 owner_direction**：评委把剧情方向升级给项目方，属于创作决定，代选不能冒充他。按 L-215 应该在开项目时把 P1 方向定死，减少升级。下一步可以考虑：给定方向后自动按评委建议改，再升级一次就按尽力版放行（要先跟项目方讨论，属于重大规则）。
2. **decide 类硬规矩**：删除、花钱、密钥、推翻他的旧决定。这些不属于流水线等待，是安全底线，不改。
3. **成人镜候选的人工挑选**：系统和 agent 写死不看、不挑。producer 照常自动采用，所以不挡。

4. **普通镜碰到成人资产被拦的**（adult_trigger 里登记表认出来的那一类）：不在常设授权范围内（PS-MASTER 11-07 定），仍要项目方本人在网页触发。
