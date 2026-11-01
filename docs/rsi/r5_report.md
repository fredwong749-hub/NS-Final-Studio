# RSI r5（fredw-2b 派：G20 / G21、改当前版本不留审计、loop 登记；时间以文件修改时间为准）

## 1 项目方任务
OT6（挑设定图 / 定脸：L-086 林晚身份脸）、OT2（接受 / 打回一个候选：打回后当前版本必须可信）。

## 2 度量（先测正确性）
- G20：项目方 AskUserQuestion 选了“只是嫌画质差”。改之前，data/looks/face_overrides.json 指向整张 4 栏设定图 ar-f9519334bc（1984×1120），左栏大头本身只有约 615 px 宽（YuNet 脸框 249×339，tools/qa/active_audit.py 之外另跑的检测脚本）。
- 改之后：
  - data/assets/identity_refs/lin_wan/lin_wan_face_hd_A_s202.png，478×479，按原图分辨率裁，头顶到下巴，不含项链；
  - face_crop_check：宽高比 1.00，人脸占 37%；整张设定图因宽高比 1.77 被拒（services/api/ns_api/character_hub.py）。
- G21：first_frame_jobs.json 重编（data/pipeline/runs/series10_v1/assets/first_frame_jobs.json）。80 个作业里 70 个挂新脸、0 个挂整张设定图、0 个被 preflight 拦下。data/renders 下的 takes 里，没有任何一个用过整张设定图。
- 改当前版本不留审计（ep01-S5）：data/audit/20261101.jsonl 第 388 行，17:39:39 项目方在 v4 上点了“不要”。takes_ui.reject 退回 clean[-1] = v3，v3 带 master_reject（07:41 总调度驳回）；set_active 当时既不查驳回、也不写 data/producer/current_changes.jsonl。
- 80 镜扫描（data/qa/active_audit/report.md）：
  - ep05-S3 当前 v7 是 10:21 总调度驳回过的版本 → 已用 clear_active 清空（带审计）；
  - ep01-S2 当前 v6 是项目方 17:43:02 用 API activate 设的，当时 activate 还不写审计 → 属于合法操作，只是没留痕，现在已经会记。

## 3 改动
- G20 / G21：新裁的脸、character_hub.set_face 登记（加 face_crop_check）、manifest 更新（含原话）、first_frame_jobs 重编；改前都有备份（*.before_L086_20261101.json）。tests/test_character_hub_assetux.py 新增校验用例，tests/test_unified_frame.py 改成断言“manifest 登记的那张脸”。docs/master/MASTER_PICTURE.md 新增 L-086，G20 / G21 已关；config/owner_decisions.yaml 新增 D-AST-86a/b/c。
- K-OPS-Q23：
  - services/render_router/ns_render/pipeline.py：set_active 是唯一入口，新增 ineligible_reason（坏图 / 不要 / 总调度驳回）、audit_active、clear_active；deactivate 只退到可用版本，并记审计。
  - services/api/ns_api/takes_ui.py：reject 只退到可用版本、unset 记审计。
  - services/api/ns_api/trash.py：_clear_active 记审计。
  - 新增 tools/qa/active_audit.py、tests/test_active_audit.py（含“不许新增直接写 active 的代码”的静态检查）；缺陷猎捕新增 DH-F19 / DH-F20。
- tools/qa/ownership.yaml：登记 AUDIT、VIDEO_RCA；VQAGATE 补上 vqa 代码目录；auto_current 设为共享；tests/test_video10_resilience.py → VIDEO10；data/ab/realism_ab/** → RESEARCH。tools/qa/iter_gate.py 新增别名 WORKFLOW→AUTOPILOT、VIDEO-RCA→VIDEO_RCA，以及组别 PROD = VIDEO10 + PRODUCER。docs/uimaster/LOCKS.md 新增 VQAGATE 的 4 条 CONSENT，以及本轮自己改动用到的 CONSENT。

## 4 独立复核
待 AUDIT 复核 r4 + r5。

## 5 回归
- 定向：tests/test_active_audit.py、tests/test_iter_gate.py、tests/test_decision_propagation.py、tests/test_takes_ui_uirsi.py、tests/test_character_hub_assetux.py、tests/test_single_identity_face.py、tests/test_unified_frame.py、tests/test_image_jobs.py 全过；跑了所有引用 set_active / takes_ui / trash 的测试，146 条全过。
- data_parity：PASS，30 镜、739 项、0 不一致（tools/qa/data_parity.py）。
- 全量 tests/：1669 过、3 不过、4 跳过、1 xfail（耗时 318.16 秒）。3 条不过是 G22 / G23 / G24 遗留：test_image_framing 断言过期，归 REFLOCK；test_review_fixes_d9 读真实 looks；test_fix_ep02_round2 已知。G20 / G21 那 3 条已经转绿。

## 6 证据
data/qa/active_audit/report.md、data/producer/current_changes.jsonl、data/audit/20261101.jsonl、data/looks/character_hub_log.jsonl、data/assets/identity_refs/manifest.json。

## 7 规则
K-OPS-Q23（knowledge/rules/ops_iteration.yaml）；决定 L-086 → D-AST-86a/b/c。
