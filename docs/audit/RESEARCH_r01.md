# AUDIT · RESEARCH 复核 r01（2026-11-01 16:49–16:56，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：docs/research/realism_tuning_20261101.md（16:48:17）、data/ab/realism_ab/、data/review_pages/realism_ab/index.html（16:45:46）、tools/research/realism_ab.py / realism_lint.py、knowledge/rules/research_realism.yaml、tools/qa/writer_lints.py 新加的 QW-W9。对照 NIGHT_PLAN W9 的完成标准：研究报告要带出处和置信度；能落地的参数做小 A/B；规则进 knowledge。
AUDIT 没有改产品文件。机读版：data/qa/audit/RESEARCH_r01.json

## 结论：研究和 A/B 通过；规则部分不通过（2 条规则不合协议，1 处越界改文件）；GPU 档 A/B 未做（RESEARCH 自己写明了“未跑”，没有冒充）

| # | 说法 / 完成标准 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | 报告每条带原文、链接、置信度 | N1–N12 每条都有原文节选、URL、置信度，低置信度的写了理由（单帖 / 厂商 / 转述）。抽查 N10：WebFetch https://huggingface.co/Danrisi/niceasians_qwen2.1，原文 “Use it with strength 0.6-0.8. Can be used with other loras”，许可 qwen-research，和报告一致。其余 11 条没有逐条去抓 | 通过（抽查 1/12） |
| 2 | 先读已有成果，不重复做（G0） | 报告开头列了已读的 8 份旧研究和规则；GPU 原生尺寸这一项交给 BAKEOFF qa_native，不重复做 | 通过 |
| 3 | 锐化三档 A/B（CPU），R0 和生产交付图逐像素一致 | 我自己用 cv2 按 metrics.py 第 165–167 行的口径重算：交付图 raw_post.png lap_full = 235.5，R0 = 235.5，R1 = 112.4，R2 = 146.2（报告写的是 235.7 / 112.4 / 146.3，差 0.2 以内，是存 PNG 前后的取整）；R0 和交付图逐像素平均差 0.0 | 通过 |
| 4 | USM 造成边缘过冲 | 我看了 data/ab/realism_ab/ep01-S1/crop_face.png：R0 的发丝外缘和脸颊轮廓有白边，R1 / R2 没有。“塑料脸”R0、R1、R2 三档看起来一样，和报告“锐化不改塑料感”的读法一致 | 通过 |
| 5 | 契约 Q4 线 175 实际上是 USM 决定的 | config/gen_contract.json 第 131 行 lap_full_min 175；这 3 镜 R0 全部 ≥175，R1 全部 <175。和报告一致。这个发现很重要：Q4 拦“糊 / 塑料”，量的其实是锐化强度 | 通过（交 REFLOCK / 总调度，见 §3） |
| 6 | 测试 | tests/test_realism_lint.py + tests/test_writer_lints.py：17 条全过 | 通过 |
| 7 | 没改生产默认，没写 takes.json | 报告和 CHANGELOG 都这样写；A/B 输出只在 data/ab/realism_ab/ | 通过（按文件位置核对） |
| 8 | GPU 档 A/B | gpu_plan.json 只有方案，生产繁忙没跑；报告第四节写明了“未跑” | 未测（如实写了） |
| 9 | 新规则都要带检查（协议 §1 第 7 步） | **K-REN-X03** 的 check 字段写的是“做不成自动检查：……”，status 却是“确认”。协议规定给不出检查的规则只能放 knowledge/inbox/ 当草案 | **不通过** |
| 10 | 写作规则要完整（协议 §1 第 7a 步：targets + writer_text + lint） | **K-WRT-X05** 有 targets 和 writer_text，但**没有 `lint:` 字段**。QW-W9 已经在 writer_lints.py 第 32、152 行实现了，规则里没有引用 | **不通过**（补一行 `lint: [QW-W9]` 即可） |
| 11 | 文件归属 | tools/qa/writer_lints.py 归 ITERAUDIT（ownership.yaml 第 58 行），docs/uimaster/LOCKS.md 里没有 ITERAUDIT → RESEARCH 的授权行；RESEARCH 自己在 ownership.yaml 里也没有条目（tools/research/**、knowledge/rules/research_realism.yaml、data/ab/realism_ab/** 都没有 owner） | **不通过**（O1 越界 + 自己的文件没有 owner） |

## 复现
- 第 9、10 条：`grep -n -E "id:|check:|lint:" knowledge/rules/research_realism.yaml` → K-REN-X03 的 check 是一句说明而不是路径；K-WRT-X05 没有 lint 行。
- 第 11 条：`grep -n RESEARCH tools/qa/ownership.yaml docs/uimaster/LOCKS.md` → 没有结果。

## 问题和建议
1. （P1，交 RESEARCH）把 K-REN-X03 移到 knowledge/inbox/，或者给它一个真正的检查（报告里自己提到第 2、3、5 条可以用 bakeoff / workflows 的固定值断言）；K-WRT-X05 补上 `lint: [QW-W9]`。
2. （P1，交总调度）RESEARCH 改 writer_lints.py 要补授权（`CONSENT: ITERAUDIT -> RESEARCH : tools/qa/writer_lints.py`），或者改为交给 RSI/ITERAUDIT 来改；ownership.yaml 要给 RESEARCH 登记 tools/research/**、knowledge/rules/research_realism.yaml、data/ab/realism_ab/**。
3. （P1，交 REFLOCK / 总调度）契约 Q4（lap_full ≥175）是在锐化后的交付图上测的，等于在量 USM 强度，不是在量“糊 / 塑料”。如果项目方在 A/B 里选了轻锐化或不锐化，Q4 会把所有图都判成不过。改 S★ 默认之前要先改 Q4 的测量位置（K-REV-X01，status 建议）。这一项涉及项目方选过的 S★，需要总调度出选择题。
4. 审片页 data/review_pages/realism_ab/index.html 的内容和本文核对的数字是同一份（metrics.json）。是否交给项目方盲看，由总调度按 master_review 决定，AUDIT 不替代总调度亲审。
