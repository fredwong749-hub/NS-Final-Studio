# AUDIT · RESEARCH 续派复核 r02（2026-11-01 17:01–17:02，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG“17:0x RESEARCH fredw-2b 派 续”，内容是 frame-jobs 新增 scope=ab，unified_frame.render_ab，tests/test_frame_ab_scope.py，K-WRT-Q29 两处标 ⤴，tools/research/realism_gpu_ab.py。
AUDIT 没有改产品文件，没有提交任何作业。机读版：data/qa/audit/RESEARCH_r02.json

## 结论：通过（实验图和生产数据确实隔开了，授权齐全）；GPU A/B 本身还没出图 = 未测

| # | 说法 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | 授权 | docs/uimaster/LOCKS.md 第 53–55 行有 REFLOCK / 总调度 / BAKEOFF → RESEARCH 三条授权，第 61 行补了 ITERAUDIT → RESEARCH（writer_lints.py，总调度认领）。r01 记的 O1 越界已经关闭 | 通过 |
| 2 | scope=ab 不写 takes.json，不进 auto_current / 契约账本 | 读了代码：`render_ab`（unified_frame.py 第 161–216 行）只调 `_run` 和追加 data/ab/<实验>/takes.jsonl。`_run` 在 rel_dir 不为空时序号固定为 0，图存 data/ab/…，本身不调 `P._add_take`。`_add_take` 只在生产路径 render（第 141 行）和 render_last（第 229 行）里调。`_pf_write` 只被生产的 postflight 后台线程调用 | 通过 |
| 3 | 生产默认不变 | build_graph / _run 新加的参数默认都是 None，生产调用没有传这几个参数（第 133、138 行的调用） | 通过 |
| 4 | preflight 只放开 I7 后缀 | 只有 prompt_edits 不为空时才声明 scope=bakeoff + suffix_variant，这是现成的 BAKEOFF 口径；改写的原文不在提示词里时直接报错，不会悄悄失效 | 通过 |
| 5 | 测试 | test_frame_ab_scope / test_frame_jobs_w2 / test_unified_frame / test_image_jobs / test_realism_lint / test_writer_lints：40 过 2 不过。不过的是 test_unified_frame::test_canvas_regen_graph_equals_unified_builder 和 test_image_jobs::test_series_jobs_prompt_equals_compiler_output，都是之前就有的 G20（身份脸是整张设定图）/ G21（作业清单过期），不是本次改动造成的 | 通过（本次改动没有引入新的不过） |
| 6 | data_parity PASS（30 镜 748 项 0 不一致） | AUDIT 没有重跑（要等 :8800 在线）。RSI r3 的 iter_gate D1 在 16:42 是 PASS，846 项 0 不一致 | 未测（只引用对方的数） |
| 7 | GPU A/B（G0/G1/G2 + 盲看页） | data/ab/realism_ab/ 里还没有 G 档的图，也没有 blind_key.json；data/review_pages/realism_ab/ 里只有 16:45 的 index.html | 未测（还没跑） |

## 提醒
- 盲看页的答案放在 data/ab/realism_ab/blind_key.json。给项目方之前，按 C2 规则先由总调度签 master_review；AUDIT 等出图后再看图复核。
- K-WRT-Q29 第 5、6 条标 ⤴ 都写了取代者（附录的漆皮镜面句 / 成年人底线），满足 G0 第 3 步。

## 给 RESEARCH
- 跑完 GPU 档以后通知复核：要逐张看 G0/G1/G2，核对 blind_key 和 takes.jsonl 的记录对得上，并确认生产 takes.json 的修改时间没有变化。
- r01 留下的 K-REN-X03（没有真正的检查）、K-WRT-X05（缺 lint）这次的交付没有提到，仍未关闭。
