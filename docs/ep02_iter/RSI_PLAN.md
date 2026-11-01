# ep02 RSI 计划（2026-10-31 17:40 起，约 7–8 小时，至 11-01 约 01:30 交结论）

项目方原话要点：“把它们的 workflow 学会，然后把我们 ComfyUI 的参数调到最好”；“整一个 system 的画布，包括工作流的开发和很多细节”；“学习小云雀以及其他公司是如何工作的”；“只对 episode two 进行 iterations”；“两个 loop combine 在一起……做出一个比 Seedance 更强大的、做短剧的 flow system”；“interface 比较难用”；“每次跑完之后 learn from the mistake”。

## 两个 loop

| Loop | 内容 | 负责 | 产物 |
|---|---|---|---|
| A 系统 | 学习（GitHub ganloss / 官方 skills / Civitai / RunningHub / 小云雀）→ 配方引擎 + Shot Spec + 自动迭代 Loop → UI/UX 画布 | WFLIB、CIVIT、RHUB、EXPERT（已交）、ARCH、FIX、UI5 | services/recipes、tools/iterate_loop、apps/web、docs/ep02_iter/*.md |
| B ep02 | 出片 → 剪辑导演打分（7 维，每维 ≥7 才给看）→ 改参数/配方 → 重出 → 合成 ep02_vN → 写回 LEARNED_SPECS | RR、LAB、CONSIST、DIR | data/episodes/ep02_vN.mp4、docs/ep02_iter/vN_review.md |

A 的每个结论都要在 B 上实测；B 的每个教训都要写回 A（配方 provenance、LEARNED_SPECS、rules.yaml）。

## 每轮固定步骤（learn from the mistake）
1. 合成 vN → `tools/ep02_director/review.py` 打分 + 接触印样。
2. 列出未达标维度 → 对应规则/实验 → 参数改动（带 provenance）。
3. 重出未达标镜（每镜 ≤3 次，之后标“待项目方”）。
4. 有效改动写回配方与 LEARNED_SPECS；无效的写进 LEARNING_BACKLOG（避免重复踩坑）。
5. vN 链接给项目方（私有网页）。

## 闸门（不因全自动而取消）
定妆/角色身份设为当前、删除、花钱超出已授权范围、推翻旧决定 → 项目方。剧本内容 → 写作模型。

## 进度日志
- 17:40 计划建立。v1 等 RR 收尾；P0 修复（FIX）与资产版本 P0 待重启 API 生效。
