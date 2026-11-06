# 会话内大脑（PS-MASTER 当 BRAIN）操作手册

API 常驻（brain_api.py）没开 / 没凭据时，总调度会话（PS-MASTER，Claude Code）自己当大脑：看同一份快照、按同一份规则（prompt.md）、
走同一个执行器（actions.py，护栏一样）。目的：决定与动作全部进 data/brain/decisions.jsonl + STATUS.md，项目方能看。

## 一轮（约 2 分钟，建议每 5–10 分钟一轮；生产高峰 3 分钟）
1. 出快照 + 提示（离线，不连 API，只读服务器）：
   ```
   .venv/Scripts/python.exe tools/brain/brain_api.py --offline
   ```
   产出：data/brain/snapshot.json（< 15 KB）、snapshot.md（一屏摘要）、next_prompt.md（系统提示词 + 动作目录 + 快照，整份可直接读）。
   只看摘要：`.venv/Scripts/python.exe tools/brain/telemetry.py md`
2. 读 data/brain/next_prompt.md（或 snapshot.md），按 prompt.md 的优先级判断：空道有活 → 卡住的镜 → 让人知道 → no_action。
3. 把动作写成 JSON 列表，先 dry-run 看护栏：
   ```
   .venv/Scripts/python.exe tools/brain/actions.py run '[{"kind":"producer_retry","host":"gpu33","obj":"first:ep02-S3","reason":"attention: first:ep02-S3 blocked 等 23 min，原因 基础设施退避；gpu33:0 空闲","expected_effect":"下轮 S3 first 变 running","check_after_s":300}]' --dry-run --snapshot-hash <snapshot.hash>
   ```
   没被拒 → 去掉 `--dry-run` 真做。每个动作必填 reason / expected_effect / check_after_s。
   `actions.py catalog` 列动作与参数；`actions.py tools` 输出 strict 工具定义。
4. 下轮快照里 recent_decisions 带上轮结果：复查 expected_effect 有没有兑现；没兑现就换思路或 report_issue，不重复同一动作（幂等 10 分钟内会拒）。
5. 里程碑 / 需要项目方决定 → note_to_owner（写 owner_notes.md + V2_LIVE 顶部一行）。STATUS.md 每次 actions.py run 后自动重生成。

## 护栏（执行器硬拦，不靠自觉）
永不 gpu33:2；永不删除；永不成人镜；速率上限（目录里）；重启每台 30 分钟一次；hold / video_lanes / 阶段覆盖必须带到期（≤ 6 h）；
schema 不符直接拒；dry-run 不计速率。被拒的记录也进 decisions.jsonl。

## 切到 API 常驻
1. 凭据：`ant auth login`（SDK 自动读 profile）或设 ANTHROPIC_API_KEY（不要写进仓库）。
2. 试一轮（动作只记不做）：`.venv/Scripts/python.exe tools/brain/brain_api.py --once --dry-run`，看 data/brain/STATUS.md 的决定合不合理。
3. config/brain/brain.json：enabled=true（先留 dry_run=true 看几轮），满意后 dry_run=false；`brain_api.py --loop` 常驻（或挂进 resident）。
4. 预算 budget_usd_day 到顶当天自动停；每轮费用 / 今日累计在 STATUS.md 最近轮次里。
