当前线：线 4（§2 防重合成验收）——线 2 ✅ 清零；线 3 卡在 G4（裁决 #4/#5 未回），按止损律跳线
已同步至：1aca3ee7（GitHub master / nsfinalstudio = 本地 HEAD，11-07 22:5x JST）
新基线冒烟：3/8（eval/results/20261107-0838.json；code=1aca3ee7）；最新 A10 3/8（eval/results/20261107-1322.json，code 354e80c0）
线 4 验收：同输入连跑两遍 0 新版本文件；断一台同步 30 分钟 0 新版本文件；ep01 版本号只因真实新素材 +1；查清 ep_sig 的 "missing:<路径>" 嫌疑并给结论

# STATE — NS-Final Studio（唯一当前真相；每个会话结束覆盖更新；≤80 行）

- 更新：2026-11-07 23:1x JST（PS-MASTER；工作方式按《破循环指令 20261107》，代码项按审计 20261106 + 补丁 v3）
- 当前阶段：**Phase R（跑通）—— 冻结期**：禁止新功能、新计划文档、cut 新版本；唯一目标 = 冒烟可证明 ≥6/8
- 仓库 HEAD：1aca3ee7（已推送）；服务器实跑：**sv-20261107-13**（ec89806e，11-07 20:24 deploy 两台）。已知：发版工具提交信息仍是“系统版本（K-OPS-V01）”模板（违反审计规则，排队）
- 自动发版：**已冻结**（config/pipeline/release.json enabled=false，11-07 10:4x）
- 冒烟分数：**3/8**（11-07 23:06，code 1aca3ee7，eval/results/20261107-0838.json；G1/G2/G7 过）。证据：A9 后 smoke_v2 control 22:40:59 写成 only=[S1,S2,S3]、hold 仅 gpu36:2/laptop:0 且窗口内未被覆盖；smoke producer 只记 priority_yield→series10_v2（22:45:02），0 派图

## 各环节最后一次成功证据（series10_v2 真实数据，非冒烟）
- 剧本 / 分镜 / 提示词：ep01–ep04 已过（sop_gate 阶段见 data/pipeline/runs/series10_v2/）
- 首帧 / 尾帧：ep01 15/16 有视频（S1 缺首帧）；ep02 首帧 16/16、尾帧 12/16；ep03 首尾帧齐、11 镜视频排队；ep04 首尾帧齐（/api/videos/overview，11-07 10:4x）
- 视频：ep01 待审 15；ep02 尽力版 12 + 排队 3 + 待审 1；ep04 待审 7 + 尽力版 5；ep03 0（gpu33 本机把阶段算成 frames，没视频道）
- 整集合成：ep04_v3.mp4（11-07 10:00）；ep01_v72/_v73_post（11-07 08:27 / 10:56）；ep01 首次全自动成片 ep01_v1.mp4（11-04 08:53，45.04 s）
- 复盘：RETRO_ep01.md（11-04 07:56，film_score 28.3/50）

## 已知坏点（≤5）
1. 项目方 11-08 报“S4 尾帧 文件不在”：04:1x 复查 ep01–ep04 S4 原图 / 缩略图 / 候选全部 200、文件在盘（ep01-S4 是 L-204 D8 不用尾帧）；未复现。嫌疑：ep02-S4 23:10 重出后 gpu36→笔记本回拉有分钟级延迟，LoadImg 4 次重试（约 30 s）后定格“文件不在”且不再重查。待项目方给页面 / 集号；单线律下只排队
2. ~~gpu33 视频道为 0~~ 11-07 18:24 已修：项目方 a 放行，两台 run_phase enforce（回退：ops/psmaster/runphase_enforce_1107.py --revert）；ep03 11 镜 rendering。gpu36 三卡仍空：ep02 3 镜排队未派（jobs.json 未重建，待查）
3. ~~ep01 整集反复合成~~ 代码已修未上线（补丁 v3 §2）：a 内容签名 6107bdd2、b 同输入不占版本号 3de38aa1、c 单一递增者=视频机 ef01f578、d 预算按集累计 043333a7、e sweep 熔断 5b53e5d5。已上线 sv-20261107-13（11-07 20:24，项目方 both 放行）；签名口径切换致 ep01/ep04 各重开一次（ep01→v76，预期）；验收（同输入 0 新版本 / 断同步 30 min 0 新版本）观察中
4. **常驻进程动物园**：resident_sync / autoflow / api / tunnel / producer / night / gpu36 看图 多进程分三台；死一个就停（11-07 视频页全黑 = 当前版本视频回拉只剩手动，01:45 自查已报无人修；已加常驻回拉线，笔记本侧生效）
5. 冒烟 G4 0 派图：第一层（旧码 tunnel_supervisor 每 30 s 写 smoke control）已除；第二层 = producer.py:3959 优先级让路（smoke_v2 priority 50 让 series10_v2 0）→ 根因报告 R1，待裁决 #1。另：笔记本内存常剩 4–7 GB

- 坏点 6（项目方 11-08 报，只排队）：#/script-create?ep=5&run=series10_v2 显示的是 ep02 的镜（S11/S15 剧本原文 = ep02“零点”）。证据：NewScriptPage 用 storyApi.get(id, ep) 带 ?ep=5，但 /api/story-runs/series10_v2 忽略 ep（该写作运行 series=false、episode=2、status=void）→ ScriptFullRows ep={run.episode}=2，页面不提示“第 5 集还没写”。同屏另三处口径打架：①胶片格 ReviewRow.tsx:425 有首帧就写“定稿 #N”（first_locked=null 也写）；②“首帧已过期，需重出”来自 stale_global=编译器升级（app.py:435 自述全局升级只该在检查器显示），每镜都挂、还给“重出首帧”按钮；③“资料不全 3”（readiness：sk_rooftop_bar 无定稿底图、祁念 / 黎岸无身份参考）与事实矛盾——这两镜首帧已过契约、S11 视频已出（readiness 与 producer 用的参考来源不是一份，疑为补丁 v3 §5 影子法官同型）

## 线序（破循环指令 §3；前一线不过不进下一线）
- 线 0 ✅ 462b230f：已推送 + 基线 3/8
- 线 1 ✅（根因报告 R1）：G4 待裁决 #1
- 线 2 ✅ 素材清零：ASSETS-MISSING.md 4/4 销账（ep01-S1 首尾帧 + 新视频；ep02-S1/S4/S7 本剧首帧）
- 线 3 ⏸ 冒烟冲 6/8：G4 未过 → G5 起全跳；等裁决 #4/#5
- 线 4 ▶ §2 两条硬验收 + 查 night.py ep_sig 的 "missing:<路径>" 嫌疑（已观察：ep01 停 v76，22:23:55 FINALIZE_SAME_INPUT 跳过，但 22:23:28 仍有 REOPEN）

## 项目方裁决清单（≤5，每条带缺省；清单外不停工）
1. ✅ 已执行 354e80c0（项目方批准“改 1”，按意图取 -1：series10_v2 是 0）。结果 A10：3/8 平，G4 不再超时、15.8 s 结束，新拦截见 R2
2. A9（41da4458）按“平→回滚”规则回滚与否：回滚 = 重新挂上已证实的第一层拦截，且需再重启 tunnel_supervisor 才生效。**缺省：保留**
3. ep01 整集 45 s < 60 s（L-092）与 11-04 起 6 个待复核版本。**缺省：线 4 验收后逐一给结论，旧版本标废弃不删**

4. G4 第三层（R2）：tools/factory/inbox.py _runs 把 runs.json kind=smoke 的剧也建进期望 refs 表（不论 status），附复现测试（红→绿同 commit）。代价：笔记本 inbox 每次 build 多一部 3 镜小剧。**缺省：改**
5. G4 第四层（R2）：producer.py:3853 一行日志文案“（免 OOM）”→“（免显存不足）”，避开评估器 OOM 正则误报（评估器不动；producer 冻结的冒烟直接相关小改，1 行）。**缺省：改**

## 禁区
- eval/ 评分表与冒烟判定逻辑：修门期间不许改（评估器与工人分离）
- producer.py：冻结，只许改冒烟门直接相关的行
