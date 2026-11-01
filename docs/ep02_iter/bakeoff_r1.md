# BAKEOFF 第 1 轮报告（2026-11-01，按 docs/ITERATION_PROTOCOL.md 七步）

完整协议、候选清单和许可见 docs/ep02_iter/image_bakeoff.md。

## 1 项目方任务（场景）
OT9：生成结果要合格。

项目方原话："Image2.1 出问题了，真人的质感完全没有……对比看看哪个做真人效果最好……ComfyUI 里关于 Image2.1 的图片编辑（edit）功能也不太行。"（见 docs/ep02_iter/image_bakeoff.md 文首）

## 2 度量（先测正确性）
- **契约 Q1–Q7**：用 REFLOCK 的 postflight（tools/gen_contract/remote_score.py，gpu33 上跑 CLIP）测了 164 张。结果在 data/ab/image_bakeoff/all_pf33.json 和 data/ab/image_bakeoff/heldout_pf33.json。
  - 通过 / 不通过 / 不适用 / 未测分开记。未测有 4 项，全是 B1 qwen21 只给文字的那组：显存不够，Q2 测不了（见 data/ab/image_bakeoff/summary.json 的 untested 列）。
- **质感**：BAKEOFF 自己的脸部指标（tools/bakeoff/score_srv.py），汇总在 data/ab/image_bakeoff/summary.json。
  - 契约现行的 Q4 线在留出复核里不成立：判对率 0.587，AUC 0.41（见 data/review_pages/asset_reflock/heldout_bakeoff.json）。所以 Q4 只作参考，不用来排名。
- **身份与质感结果**（都出自 data/ab/image_bakeoff/summary.json）：

| 模型 · 组 | Q1 过线率 | 林晚余弦 | 质感综合 | 出处 |
|---|---|---|---|---|
| Klein 4B 契约组 | 12% | 0.43 | +0.58 | data/ab/image_bakeoff/summary.json |
| Qwen 2.1 S★ 只挂脸 | 73% | 0.72 | −0.20 | data/ab/image_bakeoff/summary.json |
| Qwen 2.1 S★ 契约组 | 46% | 0.66 | −0.39 | data/ab/image_bakeoff/summary.json |
| 2511 契约组 | 50% | 0.64 | −0.35 | data/ab/image_bakeoff/summary.json |
| 现行出图 | 86% | 0.92 | −0.61 | data/ab/image_bakeoff/summary.json |

- **编辑**（数据出自 data/ab/image_bakeoff/results.json）：
  - E1 换脸后的林晚余弦：Qwen 2.1 0.753，FireRed 0.711，Klein 4B 0.682，2511 0.564。
  - E2 去油后的脸部高频：Klein 4B 2.12，其余 1.35–1.65。但 Klein 的林晚余弦掉到 0.39。
- **任务能不能做完**：对照页 data/review_pages/image_bakeoff/index.html 已生成，接触印样是 data/review_pages/image_bakeoff/contact_t2i.jpg 和 data/review_pages/image_bakeoff/contact_edit.jpg。
  - 还缺：FireRed 契约组 7 张、v9 重档 16 张、Klein 9B 和 FLUX.3（令牌无效）。原因是让道，见 knowledge/rules/render_bakeoff.yaml 的 K-OPS-B06。

## 3 改动
新增的文件：
- tools/bakeoff/run.py、tools/bakeoff/score_srv.py、tools/bakeoff/page.py、tools/bakeoff/post_local.py、tools/bakeoff/heldout.py
- tools/bakeoff/dl_manifest.tsv、tools/bakeoff/dl_weights.sh、tools/bakeoff/gated_dl.sh
- tests/test_bakeoff.py

gpu36 上：
- 装了 comfyui-krea2edit。项目方已批准，代码审查记录在 docs/ep02_iter/image_bakeoff.md §5。
- 下了 20 个权重文件，sha256 都核对过，日志在 gpu36 的 /root/work/fredw/dl/sha256.log。

生产配置没有动，也没有切换任何模型。

## 4 独立复核
- 复核方是 REFLOCK，看契约口径和阈值。请它复核 data/ab/image_bakeoff/all_pf33.json 和本报告。
- 反向那一份已经交付：我给 REFLOCK 做了阈值的留出复核，见 data/review_pages/asset_reflock/heldout_bakeoff.json。标签由总调度给出，在 data/review_pages/asset_reflock/heldout_labels.json。

## 5 回归
- tests/test_bakeoff.py：3 个测试全部通过，包括提示词清理、预检和白名单闸门、让道。
- tools/knowledge/compile.py --check 通过。
- 契约逐项结果见 data/ab/image_bakeoff/all_pf33.json。"冒充通过"为 0（见 data/qa/iter_gate/BAKEOFF_r1.md 的 C1）。

## 6 证据与入账
- 账本：knowledge/RSI_LEDGER.md 的 BK 节，BK1 到 BK7。
- 每个数字的出处都写在本报告和 data/ab/image_bakeoff/summary.json 里。

## 7 规则
knowledge/rules/render_bakeoff.yaml 新增 6 条，每条都带 check：
- K-REN-B01、K-REV-B02、K-REV-B03、K-REN-B04、K-REN-B05、K-OPS-B06

## 结论与下一轮
- **结论**：没有哪个模型在身份和质感上同时胜出，所以不切主模型（依据 data/ab/image_bakeoff/summary.json）。
- **下一轮假设**："Qwen 出图 → Klein 4B 第二段质感加工"，脸部用掩码保护，身份要过 Q1。

还需要：
- 道空闲时补跑：FireRed 契约组、v9 重档、第二个 seed（缺口清单见 data/ab/image_bakeoff/summary.json）。
- Klein 9B 和 FLUX.3：等项目方放一个有效令牌。
