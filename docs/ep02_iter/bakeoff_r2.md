# BAKEOFF 第 2 轮报告（2026-11-01 上午，按 docs/ITERATION_PROTOCOL.md 七步）

## 1 项目方任务（场景）

OT9：生成结果合格。项目方原话见 docs/ep02_iter/image_bakeoff.md 文首。

本轮做的是总调度 11-01 在 data/review_pages/image_bakeoff/master_review.md 签字后批准的三件事：

- 把"输出 = 参考板"判掉，不计分；
- 单独核查阿岚的身份；
- 试"Qwen 出首帧 → Klein 4B 质感加工（脸部掩码保护，Q1 过才放行）"。

## 2 度量（先测正确性）

- **契约逐项**：用 REFLOCK 现行口径（新 Q1：每张脸都要认得出；Q5 停用"肢体比例"规则）重打了 188 张，结果在 data/ab/image_bakeoff/rescore_pf33.json，排名在 data/ab/image_bakeoff/summary.json，表格在 data/ab/image_bakeoff/contract_table.md。
- **重打后的 Q1 过线率**（出处：data/ab/image_bakeoff/summary.json）：

| 模型 · 组 | Q1 过线率 | 出处 |
|---|---|---|
| Qwen 2.1 S★ 只挂脸 | 82% | data/ab/image_bakeoff/summary.json |
| Qwen 2.1 S★ 契约组 | 54% | data/ab/image_bakeoff/summary.json |
| 2511 契约组 | 62% | data/ab/image_bakeoff/summary.json |
| Krea2 IdEdit | 17% | data/ab/image_bakeoff/summary.json |
| Klein 4B 契约组 | 12% | data/ab/image_bakeoff/summary.json |
| Klein 4B 只挂脸 | 14% | data/ab/image_bakeoff/summary.json |

- **质感综合分**（出处：data/ab/image_bakeoff/summary.json）：Klein 4B 契约组 +0.64，Qwen 2.1 契约组 −0.34，现行出图 −0.57。
- **输出 = 参考板**（tools/bakeoff/refcopy.py + score_srv 的 ref_copy，结果在 data/ab/image_bakeoff/results.json）：
  - Krea2 ref 契约组 6 张里抓到 4 张，其余 182 张 0 误报（data/ab/image_bakeoff/results.json 的 ref_copy）。
  - 总调度亲审已判定整组为拼图，整组单列为"输出=参考板"，不计分。
  - 漏抓的 2 张靠亲审结论覆盖（data/review_pages/image_bakeoff/master_review.md）。
- **阿岚身份**（出处：data/ab/image_bakeoff/results.json 的 B6_*）：
  - 两张阿岚参考图的 sha256 相同（REFLOCK 核查），参考图本身没问题。
  - 各模型对阿岚的余弦：

| 模型 · 组 | 阿岚余弦 | 出处 |
|---|---|---|
| Qwen 2.1 契约组 | 0.94 | data/ab/image_bakeoff/results.json |
| Qwen 2.1 只挂脸 | 0.91 | data/ab/image_bakeoff/results.json |
| 现行出图 | 0.90 | data/ab/image_bakeoff/results.json |
| Krea2 IdEdit | 0.66 | data/ab/image_bakeoff/results.json |
| 2511 契约组 | 0.60 | data/ab/image_bakeoff/results.json |
| Klein 4B 契约组 | 0.57 | data/ab/image_bakeoff/results.json |
| Klein 4B 只挂脸 | 0.46 | data/ab/image_bakeoff/results.json |
| 只给文字的各组 | 0.00–0.37（Z-Image Turbo 那张 0.13，出成了男性） | data/ab/image_bakeoff/results.json |

- **第 2 轮 Klein 4B 质感加工**（24 张，第一段 = Qwen 2.1 S★ 契约组 seed 20261031，出处：data/ab/image_bakeoff/summary.json 的 r2_*）：
  - 质感综合分：去噪 0.30 加掩码 −0.38，去噪 0.45 加掩码 −0.42，去噪 0.30 不加掩码 −0.34。第一段同镜组是 −0.335，没有提升。
  - 整图 Laplacian（出处：data/ab/image_bakeoff/results.json）：B1 从 121.5 降到 90.7–93.6；B8 从 234.8 降到 186.2。
  - 林晚余弦变化在 ±0.01 以内，例如 B1：score_srv 口径（对 ref2va）0.694 → 0.697，见 data/ab/image_bakeoff/results.json；契约 postflight 口径 0.6995 → 0.6945，见 data/ab/image_bakeoff/rescore_pf33.json。两种口径的变化都在 ±0.02 以内。
  - Q1 过线率 38%，第一段也是同样几镜不过（B4 0.62、B7 林晚 0.34），所以这个数反映的是第一段的问题，不是加工造成的（data/ab/image_bakeoff/results.json）。
- **未测 / 不适用**：编辑组的 Q2 和 Q7 记"不适用"，表里标"未比对造型"。Q4 的契约线经留出复核不成立（K-REV-B02），只作参考。

## 3 改动

- 新增：tools/bakeoff/refcopy.py、tools/bakeoff/rescore.py。
- 修改 tools/bakeoff/run.py：
  - 加入第 2 轮的 refine 族和 r2_inputs；
  - 身份脸改由 face_of 解析；
  - 阿岚统一用 data/assets/identity_refs/ch_a_lan/ch_a_lan_face_ref2va.png。
- 修改 tools/bakeoff/score_srv.py：加入 ref_copy、重复人脸检测，按别名排除同一人的参考。
- 修改 tools/bakeoff/page.py：用 rescore 结果；整组不计分时单列；编辑组标"未比对造型"。
- 修改 tests/test_bakeoff.py：
  - 用独立模块名加载 run.py。REFLOCK 全量测试时发现它和 tools/autopilot/run.py 同名冲突。
  - 新增参考板拼图检测的测试。
- 生产配置没有改。GPU 只在 gpu36:1 上按让道模式出了 24 张，每张约 10 s（gpu36 的 /root/work/fredw/bakeoff/srv/bakeoff.log，与 data/ab/image_bakeoff/gen_meta.jsonl 一致）。gpu36 上的 hold 文件（/root/work/fredw/bakeoff/srv/run/hold）现在 8188 和 8189 两行都在。

## 4 独立复核

- 第 1 轮：REFLOCK 已复核，证据是 data/review_pages/image_bakeoff/verify_reflock_r1.md。结论是"有条件通过"，条件是按新 Q5 重打。本轮已经重打，结果在 data/ab/image_bakeoff/rescore_pf33.json，待 REFLOCK 核对 Q5 那一列。
- 第 2 轮：复核方是 REFLOCK，要看的是 data/ab/image_bakeoff/summary.json 里 r2_* 三组和 ref_copy 检查，还没复核。

## 5 回归

- tests/test_bakeoff.py：4 个测试全部通过。和 tests/test_knowledge_autopilot.py 两种先后顺序一起跑，都是 20 个全部通过。
- tools/knowledge/compile.py --check 通过。
- 契约逐项结果在 data/ab/image_bakeoff/rescore_pf33.json，测量出错 0 张（日志 data/ab/image_bakeoff/rescore.log）。

## 6 证据与入账

- knowledge/RSI_LEDGER.md 的 BK 节新增 BK8–BK11。
- 本报告每个数字都在同一行写了出处。

## 7 规则

knowledge/rules/render_bakeoff.yaml 新增 K-REV-B07、K-REN-B08、K-REN-B09，并修订了 K-REV-B02（REFLOCK 复核得出 face_hf 的 AUC 为 0.58），每条都带检查。

## 结论与下一步

结论：

- "Qwen 出首帧 + Klein 4B 低去噪加工"这条路不成立。脸被保护时没有变化，整图反而略微变软（出处：knowledge/rules/render_bakeoff.yaml 的 K-REN-B09）。
- 要提升脸部质感，就必须重绘脸；而重绘脸会掉身份，E2 里林晚的余弦掉到了 0.39。

下一步的候选（等首帧全部出完、总调度通知后才会占 GPU）：

- 用身份引导做脸部细节重绘，例如 Qwen 2.1 或 FireRed 用身份参考做局部重绘，以 Q1 作闸门；
- 补齐 FireRed 契约组的 7 张（出处：data/ab/image_bakeoff/summary.json 里 n=1）。
