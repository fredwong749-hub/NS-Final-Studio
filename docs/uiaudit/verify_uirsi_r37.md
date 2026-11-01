# UIAUDIT 复核：UIRSI r37（证据 r22*，18:04–18:40，全部晚于 r37.md 的 18:00:38）

OT1、OT2、OT4、OT6

**结论：通过。**这是 UIRSI 连续第三轮通过复核（r35、r36、r37），按停止条件本 loop 停。

- 全部用真实 CDP 鼠标和键盘操作；写请求全部被拦下。
- `uirsi37_detect.json`、`uirsi37b_detect.json` 是 UIRSI 自己的测试输出，不算本方证据。
- UIRSI 的 `flows_r37.json` 已复制到 `apps/web/e2e/uiaudit/flows_r37.json`，`run_round.ps1` 每轮都会跑它（输出 `rNu_detect.json`），本方的 r37 复核流程 `flows_r37v.json` 也一起跑（输出 `rNv_detect.json`）。

| # | 检查 | 实测 | 证据 | 判定 |
|---|---|---|---|---|
| 1 | 真实鼠标点候选格的图 | 尾帧打开“S1 尾帧 候选版本”，首帧打开“S1 首帧 候选版本”；都不出放大框 | `r22v_detect.json` X1_click、`r22u_detect.json` R37_candbox_real | ✓（上一轮 P1-1 关闭） |
| 1 | Alt+点 | 打开大图框（zl-box），不出候选弹窗 | X1_alt | ✓ |
| 1 | 悬停 | 出放大镜 | X1_hover | ✓ |
| 1 | 键盘 | 小图 tabIndex=0；焦点在图上按 Z → 大图框；按 Enter → 大图框；真实 Tab 走 25 步，没有一个焦点被盖住 | X1_key | ✓ |
| 2 | 画布 ep02 窄格平时 | 标签和 ↻ 的 opacity 0、pointer-events none；右上角点下去落在图上，不在按钮上。截图里人脸露出来了（`r22v_X2_reveal_idle.png`） | X2_reveal | ✓（上一轮 P1-3 关闭） |
| 2 | 悬停 / 焦点 | 悬停那一格 opacity 1、按钮能点，别的格仍隐藏（`r22v_X2_reveal_hover.png`）；焦点落在 ↻ 上时那一格显示 | X2_reveal | ✓ |
| 2 | 剧本页宽格（142px） | opacity 1，一直显示 | X2_wide、R37_script_wide | ✓ |
| 3 | 9 s 取样 ep04–ep10（同上一轮的测法） | 写“未出”但后端有候选：0 格；“读取中…”3 格（ep09）；一致 178 格 | `r22b_parity2.md`（parity2_check 新增“读取中”判法） | ✓（上一轮 P1-2 关闭） |
| 3 | 场景小卡三态 | 正常时是 has / loading / none。“无底图”3 格，经核对是后端 ep05-S3、S5 和 ep10-S1 的 `/refs` effective 确实为空。只让 `/refs` 失败时（`DETECT_FAIL_RE`），8 格全写“读不到”，没有一格写“无底图” | `r22b_detect.json`、`r22f_detect.json` | ✓ |
| 4 | 视频格 | ep02 S1、S3、S8 写“视频 1 版待选”，接口里这三镜 video 都为空、各有 1 个视频版本；点 S1 跳到 #ep02-S1，精修显示“视频 · #1”，口径一致 | X4_video | ✓ |
| 4 | 总览 | 写“2 / 1 / 11 / 9 / 10 张候选”，旧写法“候选 N”0 处 | X4_overview | ✓ |
| 5 | 林晚身份脸 | 4 个候选里只有 ar-f9519334bc（360×203，宽高比 1.77）标“不是脸部裁切”。点图和点“用这张”都只弹说明，写请求 0（`r22x_X5_noncrop_b.png`、`r22y_X5_verdict_a.png`）；点脸部裁切候选照常提交，拦下 `POST /api/character-hub/lin_wan/face {"file":"…lin_wan_face_ref2va.png"}` | `r22x_detect.json`、`r22y_detect.json` | ✓（后端 422 兜底那条要等 :8800 重启，**未测**） |
| 6 | G10 | P0 0 / 35，P1 只有老问题 F19 | `r22_regress.md`，`r22g_detect.json` 18:21:49 | ✓ |
| — | 回归 | 旧口径内容断言 30/30（`r22_parity.md`）；data_parity PASS，80 镜 1526 项（`r22_data_parity.json`）；滚动 38/38（`r22_scroll.md`）；任务 T1–T10：T3 这次能做完，T7 的 MISS 是老问题（“显示旧剧本的成片 / 两版对比”） | — | ✓ |

## 附带发现（不算 r37 的问题）
- ep02-S8 的当前首帧和视频，在 17:02:02 被 auto_current 清空（`data/producer/current_changes.jsonl`：“契约没过；这一阶段没有过契约的版本，清空当前”）。界面跟着显示“视频 1 版待选”，和后端一致。只是告知。
- 顶栏写“118 等待 · 14 失败 · 出图未连上”：跳板 16:57 起断了（r37 也记了），属基础设施问题，不归界面。
- 项目方今天的新决定：
  - “身份脸只收脸部裁切”已纳入本方回归（flows_r37face*.json）；
  - “所有画面不能看镜头”“锐化保持 R0”“Pika 全量”属于生成内容和配置，界面检查测不到，**未测**，应由生成契约和 defect_hunt 负责。

## 本轮给工具加的东西
- `detect.mjs`：`{clickAt, alt:true}` 可做 Alt+点；环境变量 `DETECT_FAIL_RE` 只让匹配的接口失败。
- `parity2_check.mjs`：“读取中…”记为未测，不判错；写“未出”而后端有，仍算不一致。
- 流程：`flows_r37.json`（UIRSI 的）、`flows_r37v.json`、`flows_r37busy.json`、`flows_r37refs.json`、`flows_r37face.json`、`flows_r37face2.json`。
