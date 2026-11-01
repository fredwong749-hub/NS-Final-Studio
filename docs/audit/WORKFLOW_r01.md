# AUDIT · WORKFLOW 复核 r01（2026-11-01 18:06–18:18，独立复核方 = AUDIT，交总调度 fredw-2b）

复核对象：CHANGELOG “16:0x–17:xx WORKFLOW”（①–⑧）、data/pipeline/runs/series10_v1/video/recipe_choice.json（L-088）、config/pipeline/video_policy.json、data/qa/infra_inject.jsonl、data/qa/alerts.jsonl、data/autopilot/pika_smoke/、tools/autopilot/resident_sync.py（18:06 还在改）。对照 NIGHT_PLAN 的 W3 和 W7。机读版：data/qa/audit/WORKFLOW_r01.json

## 结论：W3 配置通过，但旧的作业清单还没重编（P1）；W7 通过（2/3 次注入在 2 分钟内恢复，1 次超时如实记了不过）；冒烟片自己就没过闸门

| # | 说法 / 完成标准 | AUDIT 复测 | 结论 |
|---|---|---|---|
| 1 | recipe_choice 三个默认全部 Pika，不回退 pdd2 | recipe_choice.json：face / ref / noface_default 全部是 i2va_pika_flex，pika_only=true，decision L-088，带原话。video_policy.json pika_only.enabled=true，allowed 只有 i2va_pika_flex，ref2va_fallback=false，命中 flush_risk 时 hold、写明“不回退 i2va_pdd2”。`grep blocked_substitute services/recipes/recipes/*.yaml` 没有结果（16:20 版本里换回 pdd2 的替身已经拿掉）。decision_check D-VID-01/02/03 ✅；test_recipe_pika_default 通过 | 通过 |
| 2 | 作业清单跟上新配置 | **data/pipeline/runs/series10_v1/video/jobs.json 修改时间 16:56:26，早于 L-088（18:0x）**：420 个变体里 i2va_pika_flex 305、**two_person_ref2va 108、establishing 7**，状态全部是 ready。笔记本 night.py 16:58 以后停了（改为服务器常驻），所以没有重编。如果服务器常驻端用的是 16:56 以前推上去的 jobs.json，Ref2VA / establishing 变体会照样派出去，和 L-088“全部用 Pika”不符。补查：hold_reason 只在 ns_recipes.compiler 编译时调用（compiler.py 第 187、223 行），tools/series10_video/*.py 里没有任何地方引用 hold_reason / video_policy / pika_only → **vidgen 派单时不会再查政策，只要用的是旧 jobs.json，就会把 Ref2VA 派出去** | **不通过（风险已确认）**。复现：统计 jobs.json 里每个变体的 recipe |
| 3 | W3 冒烟：出片 + 打分走通 | data/autopilot/pika_smoke/ep01-S3__pika.mp4：768×1344、24 fps、7.29 秒、2.8 Mbps。我抽了 6 帧拼成一张看：身份稳定（sface 中位数 0.755），人从坐着站起来，镜头从全身推到中景。打分 gate.pass=false，fails=[多肢]（V6：extra_hand_frac 0.205，hands_max 4，bad_finger_frac 0.621）。景别在片内变了（全身 → 中景），K-REV-301 一类问题也要看 | 流程走通：通过；冒烟片质量：不过 |
| 4 | W7 隧道断开 ≤2 分钟自动恢复（注入测试） | data/qa/infra_inject.jsonl：freeze 138.5 秒（pass=false）、freeze 109.4 秒（pass=true）、kill 42.6 秒（pass=true）。判定线在 infra_inject_test.py 第 32 行，是 120 秒，和完成标准一致；第一次超时也如实记成了 false | 通过（3 次里 2 次达标） |
| 5 | W7 空转 / night / producer 报警 | alerts.jsonl 有 A-NIGHT（17:32:58 开，34 分钟没有新行，crit）、A-RELAY（17:34 开，17:52 关）、A-TUNNEL（16:54 开，17:53 关）。笔记本 night 16:58 停了以后报过一次 A-NIGHT，切换到常驻模式后关掉，和 ⑧ 写的“常驻模式下关笔记本侧报警”一致 | 通过 |
| 6 | 跳板不通时不杀隧道 | infra_watchdog.py 第 108–119 行有 relay_down 判断。18:03:23–18:05:11 又杀了一轮隧道，当时跳板已经恢复（A-RELAY 17:52 关闭）。AUDIT 18:06:41 探测：18188、18191、18288、18289、18290 都是 200，**18189 不通（000）** | 通过；18189 还没恢复，待看 |
| 7 | resident_sync 分级推送 | 文件 18:06 还在改，总调度说它正在做 | 未测 |
| 8 | G18 旧路径拦截（check_not_legacy_project） | CHANGELOG 写“API :8800 重启后生效”。AUDIT 没有重启，也没有查 :8800 的启动时间 | 未测 |

## 给 WORKFLOW / 总调度
1. （P1）服务器常驻恢复派单之前，按 L-088 重编 jobs.json（或者确认服务器端 vidgen 派单前会查 video_policy.hold_reason），不要让 108 个 Ref2VA 变体派出去。
2. 冒烟片 ep01-S3 V6 多肢不过：全量 Pika 重做时，V6 的 bad_finger_frac 阈值为空这个问题（K-REV-Q05 / DH-V20）还没解决，多手的片子会被当成“尽力”放过去。
3. 18189 隧道不通，看门狗还在重试，到 18:06 没有新的 A-TUNNEL 报警。
4. 跳板 17:52 已经恢复：VQAGATE 的 after_network.py 和 resident_restart.sh 什么时候执行，要总调度下令（AUDIT 不执行）。
