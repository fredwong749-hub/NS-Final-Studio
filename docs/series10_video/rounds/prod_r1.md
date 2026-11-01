# VIDEO10 · PROD r1（fredw-2b 派，2026-11-01 16:00–17:xx）

## 1 场景（项目方任务）
OT7 看成片（项目方原话“s5等视频出来很糊”“估计你的参数坏了”，总调度 16:25 转）；OT9 一镜生成结果合格（离线期间渲染错误归因）。

## G0 扫描记录
检索词：truncated、截断、原子写、TtsUnavailable、NS_TTS_PYTHON、assemble_failed、merge_pull、FaceModels、execution_interrupted、find_models、代理、SeedVR2、4K。
命中：docs/SOP_production.md §12（4K 只做已批准片，K-EDT-V07）；docs/vqa/STATE.md（SeedVR2 实测）；services/post/ns_post/upscale4k.py（已有 SeedVR2 入口，复用）；docs/overnight/OFFLINE_20261101.md（merge_pull 说明）；tools/series10_video/vidgen.py jsave（tmp + replace 原子写，sync 照此做）。night.py 重出路由归 VQAGATE，本轮只动 finalize / 合成 / STATUS 段。

## 2 度量（正确性）
- 成片输入分辨率：ep01_v2 的 S5 输入是代理 540×960（data/pipeline/runs/series10_v1/video/episodes/ep01/manifest.json），原片 768×1344（总调度核实，gpu33 ComfyUI 输出）。
- 清晰度（拉普拉斯方差，data/review_pages/series10_upscale_s5/metrics.json）：旧成片全帧 48.0、脸 76.5；原片 + lanczos/unsharp 全帧 127.3、脸 161.6；兜底放大 3.7 s/镜（data/review_pages/series10_upscale_s5/index.html）。
- SeedVR2 1080（gpu33:/root/work/fredw/prod_sr/out/ep01-S5_v1.4k.json）：175 帧 SR 405 s / 总 472 s；身份最低 0.912；ΔE 1.99；静区闪烁 1.67×（上限 1.6×，docs/SOP_production.md §12）→ 不过，用兜底。
- 离线错误（data/pipeline/runs/series10_v1/video/night.log）：LOOP_ERR 截断 3 次、FaceModels 2 次、JSONDecodeError 1 次、ep04 TtsUnavailable 1 次。

## 3 改动
| 问题（出处） | 根因 | 改了什么 | 规则 | 检查 |
|---|---|---|---|---|
| LOOP_ERR 截断（night.log 10:44–10:52） | 离线拷贝中断留下截断 PNG，一张坏图崩整轮 | 该镜本轮跳过；坏设定图从 data/_offline_pull/_backup 恢复 | K-OPS-306、K-OPS-311 | tests/test_video10_resilience.py |
| build_jobs FaceModels（night.log 10:46） | 服务器副本没模型，无条件加载 | 只在要新裁时加载 | K-OPS-307 | tests/test_video10_resilience.py |
| register_takes JSONDecodeError（night.log 10:54） | sync 非原子写 | .part + os.replace，坏 JSON 不覆盖 | K-OPS-308 | tests/test_video10_resilience.py |
| ep04 assemble_failed（night.log 11:11） | 服务器副本无配音解释器；assemble_failed 是死状态 | hold_tts + 自动重试 + rc≠0 不认旧残片 | K-OPS-309 | tests/test_video10_resilience.py |
| error "[]"（data/pipeline/runs/series10_v1/video/state_gpu33.json、state_gpu36.json） | ComfyUI 中断无 execution_error | 记 interrupted；两镜已由后续变体定下 | K-OPS-310 | tests/test_video10_resilience.py |
| W4 很糊（episodes/ep01/manifest.json） | 合成用代理；原片从没同步回本机 | sync 拉原片；合成只用原片 / 放大版；tools/series10_video/upscale_preview.py | K-EDT-V10 | tests/test_video10_resilience.py |

## 4 独立复核
未做：等总调度亲审 data/review_pages/series10_upscale_s5/index.html 与本轮代码（V1 记未测）。

## 5 回归
tests/test_video10_resilience.py、tests/test_video10_register.py；knowledge/generated/index.json（compile.py --check 通过）；data/qa/iter_gate/VIDEO10_prod_r1.md。

## 6 证据
data/qa/iter_gate/VIDEO10_prod_r1.md；data/_quarantine/prod_20261101_truncated_sheets/；data/review_pages/series10_upscale_s5/index.html；data/qa/defect_hunt/state.json。

## 7 规则
knowledge/rules/render_video_s10.yaml：K-OPS-306…311、K-EDT-V10；账本 knowledge/RSI_LEDGER.md V16–V18。

## 同步的文件
knowledge/rules/render_video_s10.yaml、knowledge/RSI_LEDGER.md、docs/SOP_production.md §12、docs/series10_video/STATUS.md（night.py 自动写，含当前配方）、docs/CHANGELOG_AGENTS.md。

## r2 附：W5 局部特写编译器（CONSENT REFLOCK / ITERAUDIT -> VIDEO10，docs/uimaster/LOCKS.md）
- 场景：OT9（ep05-S3 手部大特写驳回 8 次，总调度 11-01）。度量：阿岚手套参考 torso_share 0.499 → 0.0（data/pipeline/runs/series10_v1/images/refcrops/ch_a_lan_lookA_v2_s101_front_hand2.png）。
- 改动：services/agent/ns_agent/asset_refs.py、services/agent/ns_agent/framing.py、tools/qa/writer_lints.py；规则 K-AST-V10、K-REN-V11、K-WRT-V10；同步 docs/GEN_CONTRACT.md I4、docs/playbooks/CONSIST.md 第 8 条、knowledge/RSI_LEDGER.md V19。
- 回归：tests/test_video10_resilience.py、tests/test_gen_contract.py、tests/test_writer_lints.py 66 条通过；独立复核与 ep05-S3 出图验证待网络恢复。证据见 tests/test_video10_resilience.py。

## r3 附：PRODUCER 审计 / 驳回即撤下 / D-SCR-07 导入
- 场景：OT2（打回一个候选：驳回版不能当当前）、OT8（新剧本走到导入）。度量：tests/test_active_audit.py 白名单 producer 去掉后静态检查通过；readiness 前后见 data/script_rsi/d07_full/readiness_prod_import/。
- 改动：tools/autopilot/producer.py（master_reject 驳回即 clear_active；master_approve 走 set_active / clear_active 并传 actor；reconcile_demoted 跳过带驳回的当前；import-staged 命令）；规则 K-OPS-V12；回归 tests/test_producer.py、tests/test_active_audit.py、tests/test_image_jobs.py。
- 独立复核：待 AUDIT。证据：data/producer/log.jsonl（imported_staged）、data/import/backups/script_v2.20261101-182438.json。
