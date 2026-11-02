# 修图编辑器 × producer 侧设计（DEBUG-RSI，11-02 13:0x，依据 docs/master/EDITOR_INTEGRATION.md L-117 草案）

> ⤴ **接口契约以 docs/master/EDITOR_INTEGRATION.md 附录 A（SYSARCH 评审）为准**，本文与附录 A 冲突处按附录 A。SYSARCH 裁定要点：
> - adopt 改为在所属主机本地做一次 takes.json 原子写（active、locked、locked_by、invalidations、seq+1），然后发 outbox 事件 adopt；
> - 取消下文 ② 的第 4–5 步（推送 → 拉回、跨机回滚）；
> - 四个子命令（accept-take / adopt / adopt-asset-preview / submit-interactive）都在所属主机上跑，带 op_id 防重放，错误码见附录 A1；
> - takes.json 加文件级 seq 和 last_op，写入只走 pipeline 一个入口，加跨进程文件锁（ARCH_ROADMAP #16 第 1 步，编辑器 P1 之前先做）；
> - 交互道以最近一个 interactive 作业带来的 editor_active_until 为准（附录 A6）。

排期：waiting_asset 之后。冻结期间只写设计，解冻后实现。改动集中在 tools/autopilot/producer.py（DEBUG_RSI 所有）和一个新模块 tools/autopilot/edit_bridge.py；同步交 WORKFLOW，交互道交 NETFIX。

## ① 接受外部 take（一本账）

- **接口**：`edit_bridge.accept_take(run, sid, stage, file, parent, ops, session, host) -> take_n`。由 :8800 的 edit_session 在作业完成后调用，在镜头所在的主机上执行（经 rsh 调服务器 CLI `producer.py accept-take …`）。
- **写入同一本 takes.json**：用 `ns_render.pipeline._add_take`（activate=False），新增字段：
  - `origin="manual_edit"`
  - `parent=<底版 n>`
  - `ops=[{type, mask_ref, prompt_delta, model, params}]`
  - `editor_session`
  - `inputs_sha`（取底版的，用于签名比对）
- **质检**：照常跑契约（`UF._postflight` + `vqa_gate`），结果写进 postflight。人工版本**不**走 auto_current 自动设为当前，只能经 ② 采用。
- **账本**：attempts 不计次（manual 不进 3 次上限）；log 记 `manual_take`。
- **校验**（拒绝时返回原因）：
  - 主机必须等于该镜所在分区（E25）；
  - parent 必须存在于本机 takes；
  - 文件可解码、尺寸和同阶段一致。

## ② 采用事务（adopt）

`edit_bridge.adopt(run, sid, stage, n, by, force=False)`，按步骤执行，任何一步失败都回滚到采用前的快照：

| 步 | 动作 | 回滚 |
|---|---|---|
| 0 | 预检：Q1 身份分 ≥ 原 active 版（L-086，设计决定 5）；契约不过且 force=False → 拒绝；force=True 记“项目方仍然采用”审计 + VQAGATE 误拦样本 | — |
| 1 | 快照：takes.json 的 active / locked / locked_by，账本对象记录 | — |
| 2 | `pipeline.set_active` 设为当前 + 写 `locked[stage]=n`、`locked_by={by: owner, n, at}`（E23：之后不自动重出） | 还原快照 |
| 3 | 下游失效：首帧采用 → 同镜尾帧、视频的 `passed_sig` / `be_basis` 失效（E24 签名变化即重出）；尾帧采用 → 视频失效；写失效清单 `invalidations=[obj…]` | 还原账本 |
| 4 | 推送：笔记本 → 镜头所在主机（WORKFLOW push_control 同款按对象合并），核对 sha | 还原 + 撤回远端 |
| 5 | 拉回：主机 → 笔记本（resident_sync pull 单镜），核对 active 一致 | 还原 |
| 6 | 审计：current_changes.jsonl + log `manual_adopt`（含失效清单、force） | — |

- **采用为资产（P2）**：`adopt_asset(asset_id, take)` 先返回 `{"affected_shots": N, "list": […]}`。按 asset_refs 反查哪些镜引用了这个资产，不落盘。人确认后才执行，执行时写资产登记，受影响的镜按 E24 签名变化自动重出（不计次）。
- **幂等**：同一个 (sid, stage, n) 重复采用直接返回成功；进行中加 `data/producer/locks/adopt_<sid>.lock`，防止并发采用。

## ③ 交互优先作业

- **作业**：edit_session 发来的作业带 `priority="interactive"`、`host`（镜头所在主机）、`lane_hint`。producer 维护一个内存队列 `interactive_q`，每拍先派它。
  - 只派到 host 本机的道；
  - 绕过积压闸 E05（交互作业很少，人在等结果）；
  - 照常记租约和日志 `interactive_dispatch`。
- **插队**：`probe_lanes` 对交互作业放宽预取：允许在本机任一道的队列最前面插入。ComfyUI 用 `/prompt` 的 `front: true`，不打断在跑的作业。
- **交互道（和 NETFIX 定）**：gpu36:1 从“实验窗口”改成“交互优先 + 空闲时实验”。
  - 编辑器有会话打开时（:8800 心跳 `editor_active`），这条道只接交互作业，实验借道暂停新交单；
  - 会话关闭 10 分钟后，还给实验 / 生产。
  - 第一季、第二季 ep 在 gpu33 分区的镜，交互作业派到 gpu33：插队到最空的那条道，不预留。
- **SLA 指标**：交互作业从提交到出图 p50 / p90，进 SENTINEL（新探针 S-int）。

## 测试（解冻后随实现一起写）

- accept_take：字段齐全；跨主机拒绝；parent 不存在拒绝；不进 3 次上限；不自动设为当前。
- adopt：成功路径（active、锁、失效清单）；第 4 步失败时回滚到原 active 和原锁；Q1 低于原版拒绝；force 记审计。
- adopt_asset：只返回影响数量、不落盘；确认后受影响的镜签名变化。
- interactive：交互作业先于普通作业；只派本机；front=true；绕过积压闸。

## 依赖 / 待定

- edit_session API 字段（UIRSI2）；推送 / 拉回单镜接口（WORKFLOW）；`editor_active` 信号和交互道规则（NETFIX）；契约对 manual take 的口径（VQAGATE）。
