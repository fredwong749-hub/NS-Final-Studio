# 逐镜审计报告（shot_audit 干跑，剧本 为他而骚 （剧本和镜头）v2.md）

- 版本：shot_audit/2；规则表 rule_ids/v1（docs/audit/rule_ids.md）；时间 2026-10-30T03:27:24Z
- 镜头 360；通过 0；带 `**H3提示词**` 字段 0；lint 来源 —；另有 73 镜因部署政策不出图不出视频（blocked: explicit_content_not_supported，不属于审计规则，与 verdict 无关）
- block 失败 → `verdict = fail`，视频渲染器硬拦截；warn 只记录。机器暂不检查的 warn 规则：H3-A6（n-gram threshold 待定）、H3-A9（VLM/LLM 判定待定）、H3-D9（script marks no cutoff）、S1-W5（LLM 判定）、S1-W6（词表映射待定）、S3-K3（LLM 判定）

| rule_id | 级别 | 失败镜头数 | 失败条数 | 警告镜头数 | SOP 出处 |
|---|---|---|---|---|---|
| H3-A1 | block | 0 | 0 | 0 | §9A.1 #1 |
| H3-A2 | block | 0 | 0 | 0 | §9A.1 #2 |
| H3-A3 | block | 0 | 0 | 0 | §9A.1 #3 |
| H3-A4 | block | 0 | 0 | 0 | §9A.1 #4 |
| H3-A5 | block | 0 | 0 | 0 | §9A.1 #8 |
| H3-A6 | warn | 0 | 0 | 0 | §9A.1 #5 |
| H3-A7 | block | 360 | 360 | 0 | §9A.1 #7 |
| H3-A8 | block | 0 | 0 | 0 | §9A.1 #6 |
| H3-A9 | warn（待验证） | 0 | 0 | 0 | §9A.1 #9 |
| H3-A10 | warn（“一镜一运镜”待验证） | 0 | 0 | 137 | §9A.1 #10、运镜词汇 |
| H3-A11 | block | 0 | 0 | 0 | §9A.1 长度 |
| H3-A12 | warn（待验证） | 0 | 0 | 0 | §9A.1 长度 |
| H3-D1 | block | 0 | 0 | 0 | §9A.1 对白 |
| H3-D2 | block | 13 | 13 | 0 | §9A.1 对白 |
| H3-D3 | block | 0 | 0 | 0 | §9A.1 对白；S1 逐字规则 |
| H3-D4 | block | 104 | 104 | 0 | §9A.1 对白；已知坑 |
| H3-D5 | block | 6 | 12 | 0 | §9A.1 对白 |
| H3-D6 | block | 1 | 1 | 0 | §9A.1 对白 |
| H3-D7 | 亲密镜 block，其余 warn（待项目方定） | 0 | 0 | 30 | §9A.1 本项目附加规则 |
| H3-D8 | warn（待验证） | 0 | 0 | 118 | §9A.1 对白 |
| H3-D9 | warn | 0 | 0 | 0 | §9A.1 对白 |
| H3-S1 | block | 360 | 360 | 0 | §9A.1 soundscape |
| H3-S2 | block | 0 | 0 | 0 | §9A.1 soundscape |
| H3-S3 | block | 0 | 0 | 0 | §9A.1 music；参数表 |
| P-A1 | block | 0 | 0 | 0 | 参数表 S4 模型 |
| P-A2 | block | 0 | 0 | 0 | §9A.3 CFG |
| P-A3 | block（配对规则） | 0 | 0 | 0 | §9A.3 Turbo |
| P-A4 | warn（需 A/B） | 0 | 0 | 0 | 参数表 S4 加速 LoRA 版本 |
| P-A5 | block | 0 | 0 | 0 | §9A.3 |
| P-A6 | 不用 ancestral/SDE 这一条为 block；euler/simple 本身为 warn（待验证） | 0 | 0 | 0 | §9A.3 采样器 |
| P-A7 | block（SOP 先禁用） | 0 | 0 | 0 | §9A.3 缓存 |
| P-A8 | warn（需 A/B） | 0 | 0 | 0 | §9A.3 中间关键帧 |
| P-B1 | block | 360 | 360 | 0 | §6 表；§9A.3 |
| P-B2 | block | 360 | 360 | 0 | §9A.3 首尾帧预裁 |
| P-B3 | block | 0 | 0 | 0 | §9A.3 |
| R-C1 | block | 360 | 2000 | 0 | ★1；AUD §2 |
| R-C2 | block | 360 | 360 | 0 | ★3；AUD §2.1 |
| R-C3 | block | 360 | 360 | 0 | ★1 S1；参数表 v3 切换闸门 |
| R-C4 | block | 338 | 338 | 0 | ★1 S2 |
| R-C5 | block | 0 | 0 | 0 | ★1 S2；state_timeline 评审 |
| R-C6 | block | 360 | 360 | 0 | ★1 S3 |
| R-C7 | block | 360 | 360 | 0 | AUD §3.4 |
| R-C8 | block | 360 | 720 | 0 | ★3 |
| R-C9 | block（重复即 skip） | 0 | 0 | 0 | 参数表 S4 去重键 |
| R-C10 | block | 354 | 354 | 0 | ★3、G4 |
| S1-W1 | block | 50 | 50 | 0 | §6 #1 |
| S1-W2 | block | 360 | 360 | 0 | §6 #2 |
| S1-W3 | block | 360 | 360 | 0 | §6 #3 |
| S1-W4 | block | 97 | 103 | 0 | §6 #4 |
| S1-W5 | warn | 0 | 0 | 0 | §6 #5 |
| S1-W6 | warn | 0 | 0 | 0 | §6 #6 |
| S1-W7 | block | 360 | 360 | 0 | §6 #7 |
| S1-W8 | 同各原规则的级别 | 0 | 0 | 0 | §6 #7；§9A.1 |
| S1-W9 | block | 0 | 0 | 0 | §6 #7 |
| S3-K1 | block | 360 | 360 | 0 | §8 |
| S3-K2 | warn | 0 | 0 | 17 | §8；§9A.3 失败模式 |
| S3-K3 | warn | 0 | 0 | 0 | §8 |
| S3-F1 | block | 1 | 1 | 0 | 参数表 S3 |
| S3-F2 | block | 5 | 5 | 0 | 参数表 S3 |
| S3-F3 | block | 5 | 5 | 0 | 参数表 S3 |
| S3-F4 | block | 5 | 5 | 0 | 参数表 S3 |
| S3-F5 | block | 1 | 1 | 0 | 参数表 S3 |
| S3-F6 | block | 0 | 0 | 0 | 参数表 S3 |
| S3-F7 | block | 5 | 5 | 0 | 参数表 S3 |
| S3-F8 | block | 1 | 1 | 0 | 固定约束 |

## 每镜

| 镜头 | 结论 | block 失败 | warn |
|---|---|---|---|
| ep01-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-F1 S3-F2 S3-F3 S3-F4 S3-F5 S3-F7 S3-K1 | H3-A10 |
| ep01-S2 | fail | H3-A7 H3-D2 H3-S1 P-B1 P-B2 R-C1 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-F2 S3-F3 S3-F4 S3-F7 S3-K1 | H3-D7 H3-D8 |
| ep01-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-F2 S3-F3 S3-F4 S3-F7 S3-F8 S3-K1 | H3-A10 |
| ep01-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-F2 S3-F3 S3-F4 S3-F7 S3-K1 | H3-D7 H3-D8 |
| ep01-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-F2 S3-F3 S3-F4 S3-F7 S3-K1 |  |
| ep01-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep02-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 S3-K2 |
| ep02-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep02-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep02-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep02-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep02-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep03-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D7 |
| ep03-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep03-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep03-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep03-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep03-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep04-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep04-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep04-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep04-S4 | fail | H3-A7 H3-D2 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep04-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep04-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep05-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep05-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep05-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep05-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep05-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep05-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep06-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep06-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep06-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep06-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep06-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep06-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep07-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep07-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep07-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep07-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep07-S5 | fail | H3-A7 H3-D2 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep07-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep08-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep08-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep08-S3 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep08-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep08-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep08-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep09-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 S3-K2 |
| ep09-S2 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep09-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep09-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep09-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep09-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep10-S1 | fail | H3-A7 H3-D4 H3-D5 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep10-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep10-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep10-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep10-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep10-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep11-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep11-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep11-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep11-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep11-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep11-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep12-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep12-S2 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep12-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep12-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep12-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep12-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep13-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep13-S2 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep13-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep13-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep13-S5 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D2 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep13-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep14-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep14-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep14-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep14-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep14-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep14-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep15-S1 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep15-S2 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep15-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep15-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep15-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep15-S6 | fail | H3-A7 H3-D4 H3-D6 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep16-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep16-S2 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep16-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep16-S4 | fail | H3-A7 H3-D4 H3-D5 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep16-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep16-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep17-S1 | fail | H3-A7 H3-D5 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep17-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep17-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep17-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep17-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep17-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep18-S1 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep18-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep18-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep18-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep18-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep18-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep19-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep19-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep19-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep19-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D2 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 H3-D7 |
| ep19-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep19-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 S3-K2 |
| ep20-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep20-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep20-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep20-S4 | fail | H3-A7 H3-D2 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep20-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep20-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 S3-K2 |
| ep21-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep21-S2 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep21-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep21-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep21-S5 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep21-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep22-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep22-S2 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep22-S3 | fail | H3-A7 H3-D5 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 S3-K2 |
| ep22-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep22-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep22-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | S3-K2 |
| ep23-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep23-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep23-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep23-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep23-S5 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep23-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep24-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep24-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep24-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep24-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep24-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep24-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep25-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep25-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep25-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep25-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep25-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 S3-K2 |
| ep25-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep26-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep26-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep26-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep26-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep26-S5 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep26-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep27-S1 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep27-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep27-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep27-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep27-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep27-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep28-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep28-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep28-S3 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep28-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep28-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep28-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep29-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep29-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep29-S3 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep29-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep29-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep29-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep30-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep30-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep30-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep30-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep30-S5 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep30-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 S3-K2 |
| ep31-S1 | fail | H3-A7 H3-D2 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep31-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep31-S3 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep31-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep31-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep31-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep32-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep32-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep32-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep32-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep32-S5 | fail | H3-A7 H3-D2 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep32-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep33-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 |
| ep33-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep33-S3 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep33-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep33-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep33-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep34-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep34-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep34-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep34-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep34-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep34-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep35-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep35-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep35-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep35-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep35-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep35-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep36-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep36-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep36-S3 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep36-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep36-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep36-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep37-S1 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep37-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep37-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep37-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | S3-K2 |
| ep37-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep37-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep38-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep38-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep38-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D2 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep38-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 H3-D7 H3-D8 |
| ep38-S5 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep38-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep39-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep39-S2 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep39-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep39-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep39-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep39-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep40-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep40-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep40-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep40-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep40-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep40-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep41-S1 | fail | H3-A7 H3-D2 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep41-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep41-S3 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep41-S4 | fail | H3-A7 H3-D2 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep41-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep41-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep42-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep42-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep42-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep42-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | S3-K2 |
| ep42-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep42-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D7 H3-D8 |
| ep43-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep43-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep43-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep43-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep43-S5 | fail | H3-A7 H3-D5 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep43-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep44-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep44-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | S3-K2 |
| ep44-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep44-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep44-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep44-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep45-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep45-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep45-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep45-S4 | fail | H3-A7 H3-D2 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep45-S5 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep45-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep46-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep46-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep46-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep46-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep46-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep46-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep47-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep47-S2 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep47-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | S3-K2 |
| ep47-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep47-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep47-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep48-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep48-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 S3-K2 |
| ep48-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep48-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep48-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep48-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep49-S1 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep49-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep49-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep49-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep49-S5 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep49-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep50-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep50-S2 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep50-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep50-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep50-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep50-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep51-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep51-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep51-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep51-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep51-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep51-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep52-S1 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W1 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep52-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep52-S3 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep52-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep52-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep52-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep53-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep53-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep53-S3 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep53-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | S3-K2 |
| ep53-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 |
| ep53-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep54-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep54-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep54-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep54-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep54-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep54-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep55-S1 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep55-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep55-S3 | fail | H3-A7 H3-D2 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 H3-D7 H3-D8 |
| ep55-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep55-S5 | fail | H3-A7 H3-D5 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep55-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep56-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep56-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep56-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep56-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-D8 |
| ep56-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep56-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep57-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep57-S2 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep57-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep57-S4 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep57-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep57-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep58-S1 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 S3-K2 |
| ep58-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep58-S3 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep58-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 S3-K2 |
| ep58-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 H3-D8 |
| ep58-S6 | fail (blocked: explicit_content_not_supported) | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
| ep59-S1 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep59-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep59-S3 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep59-S4 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 |
| ep59-S5 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep59-S6 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 | H3-A10 S3-K2 |
| ep60-S1 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep60-S2 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D7 H3-D8 |
| ep60-S3 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 |  |
| ep60-S4 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-D8 |
| ep60-S5 | fail | H3-A7 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W7 S3-K1 |  |
| ep60-S6 | fail | H3-A7 H3-D4 H3-S1 P-B1 P-B2 R-C1 R-C10 R-C2 R-C3 R-C4 R-C6 R-C7 R-C8 S1-W2 S1-W3 S1-W4 S1-W7 S3-K1 | H3-A10 |
