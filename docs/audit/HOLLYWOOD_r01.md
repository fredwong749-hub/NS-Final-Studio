# AUDIT · HOLLYWOOD ep01 试点复核 r01（2026-11-01 22:10–22:11，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG “20:2x HOLLYWOOD”、data/review_pages/hollywood_ep01/{config_audit.md, run/, run2/}、tools/script_rsi/hollywood.py、tests/test_hollywood.py。
边界：**AUDIT 不评价剧本内容**（包括评审给的 39/50 分），只核对系统层的不变量、配置盘点里写的代码位置对不对、费用。机读版：data/qa/audit/HOLLYWOOD_r01.json

## 结论：通过

### 1 不变量 I0–I7（AUDIT 用 importer.script_md 独立重算，比对 run2/input.md 和 run2/final.md，选中第 3 轮）

| 项 | AUDIT 复测 | 结论 |
|---|---|---|
| I0 能导入 | final.md 解析成功，只含 ep01（不会动到其它集） | 通过 |
| I1 台词 / 独白逐字同序 | ep01 对白 + 独白 6 句，说话人和文本序列完全相同 | 通过 |
| I2 集头逐字（剧情 / 人物卡 / 造型） | `## ep01` 到镜1 之间的原文：1226 字对 1226 字，**完全相同**；解析后的 title / cast / scene_ids / looks 都相同；全剧 globals（含人物表 character_registry）完全相同 | 通过 |
| I3 场景 / 出场人物不新增 | 新稿的场景 id 是原稿的子集，出场人物是原稿的子集（新增的为空集） | 通过 |
| I4 镜数 ≤ 上限 | 9 → 10 镜，shot_cap = 10 | 通过（正好顶到上限） |
| I5 集时长 | 各镜时长加起来 60 秒，在 report.json 的 dur_window [60, 75] 里（正好压在下限）。之后 D-SCR-08 把窗口改成 60–120 秒，本轮是改之前跑的 | 通过 |
| I6 lint 每个码不比原稿多 | report.json 前后对比：H3-A10 1→0、QW-W1 6→0、QW-W4 9→1、QW-W5 1→0，其余码持平，没有变多的；validate 告警 40→24 | 通过（采信 report.json 的 lint 结果，lint 本身没有另外重跑） |
| I7 P4 阻断 = 0（人物卡冻结项除外） | validate_after.blocking = 0；shot_block 从 2 条到 []；frozen_block 剩 1 条“西装裙没写裙型”，属于人物卡冻结项，按 I2 不能改，正确 | 通过 |
| 测试 | tests/test_hollywood.py：8 passed（CHANGELOG 写的是 7 过，后来又加了 1 条） | 通过 |

### 2 config 盘点表抽查（代码位置）
抽了 6 处，用 sed 看对应行：

| 盘点表写的位置 | 实际 | 对不对 |
|---|---|---|
| image_params.py:157 default_preset() | 第 158 行 def default_preset | ✅（差 1 行） |
| image_params.py apply():523 换 VAE | 第 523–524 行 VAELoader vae_name = VAES[eff["vae"]] | ✅ |
| image_params.py apply():541 KSamplerSelect | 第 541–542 行 wf["36"] sampler_name | ✅ |
| image_params.py apply():557 出图尺寸 × render_scale | 第 557–558 行 scale_for / _r16(width*rs) | ✅ |
| image_params.py post_file():744 USM | 第 744–745 行 ImageFilter.UnsharpMask | ✅ |
| final_tier.py:39 auto_final_on_lock | 第 40 行 def auto_final_on_lock | ✅（差 1 行） |

6/6 都对。盘点表写的是“只列出、只建议，不改任何配置”，凡是项目方已定的都写了“保持 + 决策号”（L-087 / L-051 等），没有越权建议。

### 3 费用
- run/report.json usage：5 次调用，失败 0，$0.2312（首跑作废）；run2/report.json：32 次，失败 0，$0.5644。合计 **37 次，$0.7956**，和 CHANGELOG 写的“37 次约 $0.80”一致。单价按 prompt $1 / M、completion $2 / M 记账。
- 写作 API 是外部收费服务。按照“花钱要找项目方”的规则，这次是总调度派的试点，金额小，CHANGELOG 有记录，可以接受；如果推广到 10 集（约 $8），建议先问项目方。

## 提醒
- I4、I5 都正好压在边界上（10/10 镜、60/60 秒），说明写作模型在贴着上下限写。D-SCR-08 把时长改成 60–120 秒以后，下一轮的镜数上限也会跟着变（⌈总时长 ÷ 6⌉），推广前要用新窗口重跑一次。
- 本试点没有导入（CHANGELOG 写了“未导入”），生产剧本没有被改：data/import/script_v2.json 还是 18:24 的 rsiD07 那版（见 SCRIPT_RSI_r01）。
