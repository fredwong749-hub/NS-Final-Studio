# Qwen-Image 2.1 深入研究：可续跑笔记（BAKEOFF，R11-12）

> 项目方原话（docs/REQUIREMENTS.md R11-12）："把 flux 调参数的也学明白，启动 agent 上去学习，然后回来检测我们的剧本提示词对不对？把学会的规则和 bad cases 写入本地规则系统，然后每次新剧本写的时候 follow 这些规则系统"。
> 事实：生产出图不是 FLUX，是 Qwen Image 2.1（frame_v9 预设，统一路径），所以按原意改成研究 Qwen Image 2.1。
> 总调度 11-01 派给 BAKEOFF。GPU 只能用 hold 道（等首帧全部出完）或让道模式；改生产默认要总调度批。

## 进度（每完成一步就更新，断线后从这里接着做）

| # | 步骤 | 状态 | 产物 |
|---|---|---|---|
| 1 | 调研：官方文档、模型卡、社区指南（参数 + 提示词写法）；R11-13 社区写实调参（各候选） | 完成 | docs/qwen21/RESEARCH.md、docs/qwen21/COMMUNITY_PHOTOREAL.md |
| 2 | 回查：series10 当前首帧提示词（frame_job 编译结果）+ 真实坏例（master_reject / 契约不过） | 完成（11-01）：lint 10 条（tools/bakeoff/qwen21_lint.py），367 个坏例、506 个版本的命中与不过率对照 | docs/qwen21/BACKCHECK.md、docs/qwen21/BAD_CASES.md、data/ab/qwen21/ |
| 3 | 写进系统：规则 + 检查、writer_text / QW lint、编译器问题转 REFLOCK | 完成：9 条规则（K-REN-Q21…K-WRT-Q29）、lint QL01–QL15 + 测试；REFLOCK 已改 A2/A3 部分、放行 A/B；A1 等总调度；QW-W5–W8 待 ITERAUDIT | knowledge/rules/render_qwen21.yaml、tests/test_qwen21_lint.py、docs/qwen21/PROPOSALS.md |
| 4 | GPU A/B（参数改动，带契约分） | 已编好 10 组 × 8 镜（seed 20261031）：qa_base / qa_imgtag / qa_native / qa_lora0 / qa_suffix / qa_all / qa_lenovo / qa_niceasian / qa_grain / bb_2511_official；全部过 preflight；等 hold 解除 | tools/bakeoff/run.py、data/ab/image_bakeoff/plan.json |
| 5 | 报告 + 拟议默认改动（需总调度批） | 待做 | docs/qwen21/REPORT.md |

## 断线续跑提示
- 调研 agent 的结果会写在 docs/qwen21/RESEARCH.md；如果文件不存在，重新派一个，按本文第 1 步的要求做。
- 回查脚本在 tools/bakeoff/qwen21_backcheck.py（建成后），重跑一次就能生成 BACKCHECK.md。

## 已知结论（续跑时先读）
- 命中 QL01（特写 / 近景要求裙裤鞋入画）的版本 Q3 不过 29%，未命中 6%；QL02（局部特写写了身份 / 脸）Q1 不过 9/9；QL06（两人同框 + 一人前景虚化）Q1 不过 83%，未命中 49%；QL03（正向里的否定句）Q2 不过 31%，未命中 13%。都是相关，因果要 GPU A/B。
- writer_lints.py 归 ITERAUDIT，不能直接改；写作方规则以提案形式交（docs/qwen21/PROPOSALS.md）。编译器问题交 REFLOCK。
- 重跑：`.venv/Scripts/python.exe tools/bakeoff/qwen21_backcheck.py bad|lint|assoc|gallery`

## 续跑步骤（笔记本回来后，或 gpu36 能连上时）
1. 推最新 plan 和代码：`scp tools/bakeoff/run.py data/ab/image_bakeoff/plan.json gpu36:/root/work/fredw/bakeoff/srv/`，然后 `python tools/bakeoff/run.py push`（只补缺的参考图）。
   - 本机 plan.json 的 md5 是 eb5312310c77aa64cf36e9490c115855（11-01 晚）。服务器上的若不一样，说明 11-01 那次 scp 因断线没推上。
2. 布好出图：`python tools/bakeoff/run.py start --models=qa_base,qa_native,qa_lora0,qa_imgtag,qa_suffix,qa_all,qa_lenovo,qa_niceasian,qa_grain,bb_2511_official --modes=contract --seed0`
   - 进程守 hold 文件；hold 解除后按让道模式出图（别人任务结束后空闲满 180 秒才交，每道一次 1 个）。出完自动跑 score_srv。
3. 拉回结果并打契约分：`python tools/bakeoff/run.py pull`；把新 id 加进 rescore_jobs.json，然后 `python tools/bakeoff/rescore.py data/ab/image_bakeoff/rescore_jobs.json data/ab/image_bakeoff/rescore_pf33.json`；最后 `python tools/bakeoff/run.py page`。
4. 比对：qa_* 和 qa_base 同镜同种子比 Q1、Q2、Q3 和质感分，结果写进 docs/qwen21/REPORT.md 和 RSI_LEDGER 的 BK 节。改生产默认要总调度批。

## 注意
- 林晚身份脸 11-01 10:58 被项目方在资产中心换成设定图整张 ar-f9519334bc，是不是本意还在等总调度。A/B 要和 qa_base 同批比，不能和之前的分数比。
- 其它候选模型的写实 LoRA 在 Civitai 上，下载要 API 令牌（匿名返回 401）。清单：Lenovo Krea2 v3075606、Realistic Snapshot ZIT v5 v2617751、Amateur Selfies Klein4B v2666766、Anything to Real 2511 v2581471，文件名和 sha256 见 COMMUNITY_PHOTOREAL.md 和本会话记录。
